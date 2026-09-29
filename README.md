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
- [docs/successful-host-handoff.md](docs/successful-host-handoff.md): exact
  working server inventory and replacement-host replication checklist.
- [docs/troubleshooting.md](docs/troubleshooting.md): failure isolation and known issues.
- [config/x310-redcap-ru.yaml](config/x310-redcap-ru.yaml): server-side RF/network fragment.
- [scripts/inspect.sh](scripts/inspect.sh): server-oriented, non-mutating inventory.
- [scripts/tune-x310.sh](scripts/tune-x310.sh): server-side NIC and socket tuning.
- [scripts/network-fresh.sh](scripts/network-fresh.sh): this server's full lab
  stop/fresh-start helper; see [state-reset details](docs/fresh-network-start.md).
- [scripts/watch-ue.py](scripts/watch-ue.py): live AMF UE tables and optional gNB events;
  `network-fresh.sh watch` opens the AMF view without restarting the network.
- [docs/udp-messages.md](docs/udp-messages.md): manual UDP server and laptop client commands.
- [scripts/ue-policy-route.sh](scripts/ue-policy-route.sh): laptop-side source-policy route.
- [scripts/connect-ue.py](scripts/connect-ue.py): laptop EM8695 registration/data helper;
  run with `sudo python3 scripts/connect-ue.py --watch` for USB reconnects.
  Add `--internet` to use cellular IPv4 default routing and bearer DNS.
  See [laptop helper instructions](docs/laptop-auto-connect.md) for limitations.
- [scripts/provision-subscriber.sh](scripts/provision-subscriber.sh): idempotently imports a
  private subscriber snapshot into the running OAI MySQL container.

The verified subscriber snapshot is stored at
`config/subscriber-001010000134378.sql`. It contains the SIM identity, K, OPc,
and SQN in plaintext. To reproduce the setup after cloning, run:

```bash
./scripts/provision-subscriber.sh
```

## Important safety rules

- The tracked subscriber snapshot contains live K/OPc values and a SIM
  identifier; restrict repository access accordingly.
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
sudo mmcli -m MODEM_ID --disable
sudo mmcli -m MODEM_ID --set-allowed-modes='5g'
sudo mmcli -m MODEM_ID --enable
sudo mmcli -m MODEM_ID --simple-connect='apn=oai,ip-type=ipv4'
mmcli -b BEARER_ID
sudo ip link set wwan0 up
sudo ip addr replace UE_ADDRESS/PREFIX dev wwan0
sudo ./scripts/ue-policy-route.sh wwan0 UE_ADDRESS UE_GATEWAY
```

See [docs/runbook.md](docs/runbook.md) for prerequisites, exact ordering, and
copy-paste prompts to give Codex on each computer.
