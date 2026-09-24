#!/usr/bin/env bash
set -Eeuo pipefail

build_dir=/home/systron/redcap-bringup/oai-reference/build-uhd410
config=/home/systron/redcap-bringup/gnb-reference.yaml

cd "$build_dir"
export LD_LIBRARY_PATH="$build_dir"

# Use one logical CPU from each P-core plus four E-cores. CPUs 12-15 are
# reserved for the X310 IRQs by tune-x310.sh.
exec taskset -c 0,2,4,6,8-11 stdbuf -oL -eL ./nr-softmodem \
  -O "$config" \
  --gNBs.[0].min_rxtxtime 6 \
  --usrp-tx-thread-config 0 \
  -E --continuous-tx
