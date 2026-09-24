#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo $0 [NIC]" >&2
  exit 1
fi

nic=${1:-ens7f0}
ip link show "$nic" >/dev/null
ip link set dev "$nic" mtu 9000

# The launcher gives OAI one logical CPU from each P-core (0,2,4,6) plus four
# E-cores (8-11), for eight distinct physical cores. Keep the X310 interrupts
# on the remaining E-cores (12-15). Governors and IRQ placement revert at
# reboot, so restore them before opening the X310.
for cpu in {0..15}; do
  governor=/sys/devices/system/cpu/cpu${cpu}/cpufreq/scaling_governor
  available=/sys/devices/system/cpu/cpu${cpu}/cpufreq/scaling_available_governors
  [[ -w $governor ]] || {
    echo "CPU $cpu governor is unavailable or not writable: $governor" >&2
    exit 1
  }
  [[ ! -r $available ]] || grep -qw performance "$available" || {
    echo "CPU $cpu does not offer the performance governor" >&2
    exit 1
  }
  printf '%s\n' performance >"$governor"
  [[ $(<"$governor") == performance ]] || {
    echo "Failed to set CPU $cpu governor to performance" >&2
    exit 1
  }
done

ethtool -C "$nic" rx-usecs 8 tx-usecs 8
coalesce_output=$(ethtool -c "$nic")
current_rx_usecs=$(awk '/^rx-usecs:/{print $2; exit}' <<<"$coalesce_output")
current_tx_usecs=$(awk '/^tx-usecs:/{print $2; exit}' <<<"$coalesce_output")
[[ $current_rx_usecs == 8 && $current_tx_usecs == 8 ]] || {
  echo "Failed to set $nic coalescing to rx-usecs 8 and tx-usecs 8" >&2
  exit 1
}

# Keep the high-rate X310 IRQ/softirq work off OAI's CPU set. The NIC exposes
# eight traffic vectors plus a management vector; distribute every live vector
# over the otherwise unallocated E-cores 12-15.
irq_cpus=(12 13 14 15)
irq_index=0
for irq_path in /sys/class/net/"$nic"/device/msi_irqs/*; do
  irq=${irq_path##*/}
  affinity=/proc/irq/$irq/smp_affinity_list
  [[ -w $affinity ]] || continue
  target_cpu=${irq_cpus[irq_index % ${#irq_cpus[@]}]}
  printf '%s\n' "$target_cpu" >"$affinity"
  effective=$(<"/proc/irq/$irq/effective_affinity_list")
  [[ $effective == "$target_cpu" ]] || {
    echo "Failed to move $nic IRQ $irq to CPU $target_cpu (effective: $effective)" >&2
    exit 1
  }
  ((irq_index += 1))
done
((irq_index > 0)) || {
  echo "No writable MSI IRQs found for $nic" >&2
  exit 1
}

ring_output=$(ethtool -g "$nic")
max_rx=$(awk '/Pre-set maximums:/{p=1;next} p && /^RX:/{print $2; exit}' <<<"$ring_output")
max_tx=$(awk '/Pre-set maximums:/{p=1;next} p && /^TX:/{print $2; exit}' <<<"$ring_output")

if [[ $max_rx =~ ^[0-9]+$ && $max_tx =~ ^[0-9]+$ ]]; then
  ethtool -G "$nic" rx "$max_rx" tx "$max_tx"
else
  echo "Could not parse supported ring maxima; leaving rings unchanged" >&2
fi

sysctl -w \
  net.core.wmem_max=62500000 \
  net.core.rmem_max=62500000 \
  net.core.wmem_default=62500000 \
  net.core.rmem_default=62500000

ip -d link show "$nic"
ethtool -g "$nic"
printf 'CPU 0-15 governor: performance\n'
printf '%s IRQs assigned to CPUs 12-15: %d\n' "$nic" "$irq_index"
printf '%s\n' "$coalesce_output"
