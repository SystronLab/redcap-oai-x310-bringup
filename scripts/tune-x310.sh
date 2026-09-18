#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo $0 [NIC]" >&2
  exit 1
fi

nic=${1:-ens7f0}
ip link show "$nic" >/dev/null
ip link set dev "$nic" mtu 9000

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

