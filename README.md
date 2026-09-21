# OAI 5G RedCap bring-up with an X310 and EM8695

Reproducible runbook for a two-computer standalone 5G RedCap system:

```text
SERVER / gNB-core host                         LAPTOP / UE host

OAI 5G Core (Docker) <-- N2/N3 --> OAI gNB    applications and test traffic
                                    |           |
                              Ettus X310      wwan0 / USB
                                    | n78       |
                                    +------ EM8695 RedCap UE

Both computers may also use an ordinary LAN/Wi-Fi connection for management.
That management connection does not carry N2, N3, or NR user traffic.
```

This repository documents a verified deployment using OAI `develop` commit
`1143f7500e`, UHD 4.9.0.0, an X310 with HG FPGA, and OAI Core v2.2.1. Clone
this repository on both computers. Adapt interface names, addresses, and
subscriber values to each computer instead of copying examples blindly.

## Which computer does what

| Responsibility | Server / gNB-core host | Laptop / UE host |
|---|---:|---:|
| OAI 5G Core containers and subscriber database | yes | no |
| OAI `nr-softmodem` | yes | no |
| X310 Ethernet and UHD | yes | no |
| EM8695 USB, ModemManager, and `wwan0` | no | yes |
| UE-side ping/curl tests | no | yes |

The X310 must be connected directly (or through a suitable dedicated 10 GbE
network) to the server. Connect the EM8695 by USB to the laptop. No physical
Ethernet connection between the EM8695 and server is required: their data path
is the n78 radio link.

## Verified outcome

The reference deployment achieved NG Setup, RedCap UE identification, 5G-AKA
registration on PLMN `001/01`, NR SA attachment on band n78, an IPv4 PDU
session on DNN `oai`, and bidirectional UE-to-external-DN/internet traffic.

## Repository map

- [docs/runbook.md](docs/runbook.md): complete two-computer bring-up procedure.
- [docs/troubleshooting.md](docs/troubleshooting.md): failure isolation and known issues.
- [config/x310-redcap-ru.yaml](config/x310-redcap-ru.yaml): server-side RF/network fragment.
- [scripts/inspect.sh](scripts/inspect.sh): server-oriented, non-mutating inventory.
- [scripts/tune-x310.sh](scripts/tune-x310.sh): server-side NIC and socket tuning.
- [scripts/ue-policy-route.sh](scripts/ue-policy-route.sh): laptop-side source-policy route.

## Important safety rules

- Never copy, publish, or commit subscriber K/OPc values or SIM identifiers.
- Never reset SQN during routine bring-up. Successful AKA advances SQN normally.
- Inspect the running core before changing it; do not redeploy healthy NFs.
- Do not stop unrelated Docker workloads.
- Start from the RedCap configuration shipped by the exact OAI checkout.
- Do not use B210 gain values on an X310/UBX.
- Confirm local spectrum authorization and use appropriate attenuation/shielding.

## Quick start

On the **server**, inspect and tune the X310 link, start the core, and launch
the gNB as described in the runbook:

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

After the gNB receives `NGSetupResponse`, use the **laptop** to connect the
modem. Configure the address and gateway reported by its bearer:

```bash
sudo mmcli -m MODEM_ID --simple-connect='apn=oai,ip-type=ipv4'
mmcli -b BEARER_ID
sudo ip link set wwan0 up
sudo ip addr replace UE_ADDRESS/PREFIX dev wwan0
sudo ./scripts/ue-policy-route.sh wwan0 UE_ADDRESS UE_GATEWAY
```

See [docs/runbook.md](docs/runbook.md) for prerequisites, exact ordering, and
copy-paste prompts to give Codex on each computer.
