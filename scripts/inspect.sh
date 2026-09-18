#!/usr/bin/env bash
set -euo pipefail

nic=${1:-ens7f0}
usrp_addr=${2:-192.168.40.2}

uname -a
ip -br addr
ip route get "$usrp_addr"
ip -d link show "$nic"
ethtool -g "$nic"
sysctl net.core.wmem_max net.core.rmem_max \
  net.core.wmem_default net.core.rmem_default
ping -c 3 "$usrp_addr"
uhd_find_devices
uhd_usrp_probe --args="addr=$usrp_addr"
docker ps
lsusb
ls -l /dev/ttyUSB* /dev/ttyACM* /dev/cdc-wdm* 2>/dev/null || true
mmcli -L 2>/dev/null || true

