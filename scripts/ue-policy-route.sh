#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo $0 INTERFACE UE_ADDRESS UE_GATEWAY [TABLE]" >&2
  exit 1
fi

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "Usage: $0 INTERFACE UE_ADDRESS UE_GATEWAY [TABLE]" >&2
  exit 2
fi

interface=$1
ue_address=$2
ue_gateway=$3
table=${4:-100}
priority=100

ip link show "$interface" >/dev/null
ip route replace table "$table" default via "$ue_gateway" dev "$interface" src "$ue_address"

if ! ip rule show | grep -Fq "from $ue_address lookup $table"; then
  ip rule add priority "$priority" from "$ue_address/32" table "$table"
fi

ip rule show
ip route show table "$table"

