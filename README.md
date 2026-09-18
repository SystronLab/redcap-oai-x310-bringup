# OAI 5G RedCap bring-up with an X310 and EM8695

Reproducible runbook for a standalone 5G RedCap system:

```text
Semtech/Sierra Wireless EM8695
        | n78 RF
Ettus USRP X310 + UBX-160 v2
        |
OAI nr-softmodem gNB
        | N2/N3
OAI 5G Core in Docker
        |
external DN / internet
```

This repository documents a verified deployment using OAI `develop` commit
`1143f7500e`, UHD 4.9.0.0, an X310 with HG FPGA, and OAI Core v2.2.1. Adapt
addresses and subscriber values to the target machine instead of copying them
blindly.

## Verified outcome

The reference deployment achieved:

- NG Setup with the OAI AMF.
- OAI identification of the EM8695 as a RedCap UE.
- 5G-AKA registration on PLMN `001/01`.
- NR SA packet attachment on band n78.
- IPv4 PDU session on DNN `oai`.
- Bidirectional UE-to-external-DN traffic.
- Public internet access through the UPF and host uplink.

## Repository map

- [docs/runbook.md](docs/runbook.md): complete bring-up procedure.
- [docs/troubleshooting.md](docs/troubleshooting.md): failure isolation and known issues.
- [config/x310-redcap-ru.yaml](config/x310-redcap-ru.yaml): RF/network fragment to apply to the checked-out OAI RedCap reference.
- [scripts/inspect.sh](scripts/inspect.sh): non-mutating host/hardware inventory.
- [scripts/tune-x310.sh](scripts/tune-x310.sh): idempotent NIC and socket tuning.
- [scripts/ue-policy-route.sh](scripts/ue-policy-route.sh): source-policy route for locally attached MBIM UEs.

## Important safety rules

- Never copy, publish, or regenerate subscriber K/OPc values.
- Never reset SQN during routine bring-up. Successful AKA advances SQN normally.
- Inspect the running core before changing it; do not redeploy healthy NFs.
- Do not stop unrelated Docker workloads.
- Start from the RedCap configuration shipped by the exact OAI checkout.
- Do not use B210 gain values on an X310/UBX.
- Confirm local spectrum authorization and use appropriate attenuation/shielding.

## Quick start

Read the full runbook first. At a high level:

```bash
./scripts/inspect.sh ens7f0 192.168.40.2
sudo ./scripts/tune-x310.sh ens7f0

cd /path/to/openairinterface5g/cmake_targets/ran_build/build
sudo env LD_LIBRARY_PATH="$PWD${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  ./nr-softmodem \
  -O ../../../targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb.sa.band78.fr1.106PRB.usrpx310.redcap.yaml \
  --gNBs.[0].min_rxtxtime 6 \
  --usrp-tx-thread-config 1 \
  -E --continuous-tx
```

After the modem establishes its `oai` bearer, configure its reported IP and
gateway on `wwan0`, then install source-policy routing:

```bash
sudo ip link set wwan0 up
sudo ip addr replace UE_ADDRESS/PREFIX dev wwan0
sudo ./scripts/ue-policy-route.sh wwan0 UE_ADDRESS UE_GATEWAY
```

Do not add destination-specific routes such as `8.8.8.8/32 via UE_GATEWAY`.
They also capture forwarded UPF packets and create a routing loop.

