# Successful server handoff

This document captures the server environment that successfully registered the
EM8695 RedCap UE on 21 September 2026. Use it when moving the X310 to another
computer. Values under **adapt on the new host** describe this machine and must
not be copied blindly.

## Proven result

The following sequence completed on the reference server:

1. All OAI Core v2.2.1 network functions became healthy.
2. The gNB sent `NGSetupRequest` and received `NGSetupResponse` from the AMF.
3. Random access completed at Msg4 and the UE reached `RRC_CONNECTED`.
4. The AMF reported subscriber `001010000134378` as `5GMM-REGISTERED` on
   PLMN `001/01`.
5. The gNB created DRB 1 (5QI 9), a PDU session, and an N3 GTP-U tunnel to the
   UPF.

Registration was proven. During the final run, a later PDU-session retry also
reported `UE_NOT_RESPONDING`; therefore verify the bearer and user-plane
traffic independently rather than treating registration alone as proof of
internet connectivity.

## Reference software and hardware

| Component | Working value |
|---|---|
| OS | Ubuntu 22.04.5 LTS |
| Kernel | `5.15.0-1032-realtime` (`PREEMPT_RT`) |
| Logical CPUs | 48 |
| Docker | 28.4.0 |
| OAI RAN | `develop` commit `1143f7500e5e5a9cd258148f8429230cc2759554` |
| OAI Core images | v2.2.1 |
| MySQL image | 9.6 |
| UHD | `4.9.0.0-107-gea40e659` |
| Radio | Ettus X310, serial `344F176`, HG FPGA, FPGA version 39.3 |
| Daughterboards | Two UBX-160 v2 boards; the run used slot A (`A:0`) |
| RF mode | SISO, internal clock, TX/RX on `A:0`, RX on `A:0`/RX2 |

The serial number is informational. Do not require the replacement machine to
see the same serial unless the same physical X310 was moved.

## Reference topology

| Purpose | Working value | Adapt on new host? |
|---|---|---:|
| Server management NIC/IP | `enp1s0`, `144.32.194.249/24` | yes |
| X310 NIC/IP | `ens7f0`, `192.168.40.1/24` | NIC name yes |
| X310 IP | `192.168.40.2` | only if radio was readdressed |
| X310 NIC MTU | 9000 | no, if NIC supports it |
| Core Docker bridge | `oai-cn5g`, `192.168.70.128/26` | normally no |
| Host N2/N3 address | `192.168.70.129` | discover and configure |
| NRF | `192.168.70.130` | normally no |
| MySQL | `192.168.70.131` | normally no |
| AMF | `192.168.70.132` | discover and configure |
| SMF | `192.168.70.133` | normally no |
| UPF | `192.168.70.134` | discover and configure |
| External DN | `192.168.70.135` | normally no |
| UDR/UDM/AUSF | `.136`/`.137`/`.138` | normally no |
| UE address pool | `10.0.0.0/24` (within `10.0.0.0/16` routing) | no |

The management network is not part of N2, N3, or the UE data path. The X310
must use its dedicated Ethernet link.

## Radio and mobile-network parameters

| Parameter | Working value |
|---|---|
| PLMN | MCC `001`, MNC `01` (two digits) |
| TAC | 1 |
| gNB ID/name | `0xe00`, `gNB-OAI` |
| Cell ID / PCI | `12345678` / 0 |
| Slice | SST 1, SD `FFFFFF` |
| DNN/APN | `oai` |
| Band | n78 |
| Duplex/numerology | TDD, 30 kHz SCS (mu 1) |
| Carrier bandwidth | 106 PRB |
| SSB ARFCN | 641280 |
| Point A | 640752 |
| Actual tuned RF frequency | 3.630360 GHz |
| Sample rate / master clock | 46.08 MS/s / 184.32 MHz |
| BWP | active BWP 1, start 0, size 106 |
| RedCap | type-1 and type-2 barred flags set to 1 as in OAI RedCap template |
| TX settings | `att_tx: 12`, OAI reported actual UBX gain 19.5 dB |
| RX settings | `att_rx: 12`, `max_rxgain: 31`; OAI reported actual gain 0 dB |
| Launch timing | `min_rxtxtime 6`, USRP TX thread config 1 |

Use [x310-redcap-ru.yaml](../config/x310-redcap-ru.yaml) as the machine-specific
overlay. The complete working YAML was made by copying
`gnb.sa.band78.fr1.106PRB.usrpb210.redcap.yaml` from the exact OAI commit to
`gnb.sa.band78.fr1.106PRB.usrpx310.redcap.yaml`, retaining all RedCap/BWP/timer
fields, and applying that overlay.

## Recreate the exact core bundle

At the reference commit, the running core directory was an unmodified copy of:

```text
openairinterface5g/doc/tutorial_resources/oai-cn5g/
```

The working copy and the source files had matching SHA-256 hashes:

```text
docker-compose.yaml  2b888e8dcad8c74bd3efc14b952c714cb2c425a43a8acb93f960924262e3b9eb
conf/config.yaml      68ef8c05f9087583b9298dfd30e541e012993e11177fb64df3818dbb815e6817
```

After checking out the pinned OAI commit, copy that directory to a writable
location and start its `docker-compose.yaml`. Do not mix it with any Open5GS
containers that may exist on the new host. Confirm every required OAI
container is healthy before launching the gNB.

The compose network deliberately uses bridge name `oai-cn5g`, subnet
`192.168.70.128/26`, and host bridge address `192.168.70.129`. The gNB binds
both N2 and N3 to that host bridge address and connects to AMF `.132`. The UPF
SNATs `10.0.0.0/24` through its core-facing address; Docker adds host-side
masquerading for the core bridge. The reference host had
`net.ipv4.ip_forward=1`.

## Subscriber state: migration-critical

The credential-bearing snapshot is
`config/subscriber-001010000134378.sql`. Repository access must remain private
and restricted because it contains the live IMSI, K, and OPc.

The snapshot SQN was refreshed after the successful registration to
`000000001161`. Do not lower or reset it. If the SIM is used again before the
migration, export the newer live `AuthenticationSubscription` row or update
only the snapshot SQN before starting the new core. An older SQN can cause
5G-AKA synchronization failure.

Import it once MySQL is healthy:

```bash
./scripts/provision-subscriber.sh
```

The script does not print K or OPc and provisions authentication plus the
`oai` DNN, S-NSSAI, QoS/AMBR, and static UE address.

## Bring-up order on the new server

1. Clone this repository and the OAI RAN repository.
2. Check out OAI commit `1143f7500e5e5a9cd258148f8429230cc2759554` and build
   `nr-softmodem` with USRP support.
3. Install UHD 4.9 and confirm `uhd_usrp_probe --args=addr=192.168.40.2` sees
   the X310, HG FPGA, and both UBX boards.
4. Give the dedicated X310 NIC `192.168.40.1/24`; do not add a gateway.
5. Run `sudo ./scripts/tune-x310.sh NEW_X310_NIC`.
6. Recreate the pinned core bundle, start it, and wait for healthy containers.
7. Import the current subscriber snapshot without changing SQN.
8. Discover the actual Docker bridge, host N2/N3, AMF, and UPF addresses.
9. Build the X310 RedCap YAML from the pinned template and adapt only the
   discovered addresses, NIC/radio address, and X310 RU fields.
10. Validate YAML, start the gNB, and wait for `Received NGSetupResponse from
    AMF` and `RU 0 RF started` before enabling the UE.

Reference launch command (change paths only):

```bash
cd /path/to/openairinterface5g/cmake_targets/ran_build/build
sudo env LD_LIBRARY_PATH="$PWD${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  ./nr-softmodem \
  -O ../../../targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb.sa.band78.fr1.106PRB.usrpx310.redcap.yaml \
  --gNBs.[0].min_rxtxtime 6 \
  --usrp-tx-thread-config 1 \
  -E --continuous-tx
```

After UHD opens the radio, restore socket maxima if UHD lowered them:

```bash
sudo sysctl -w net.core.wmem_max=62500000 net.core.rmem_max=62500000
```

## Expected success markers

Look for all of these, in order:

```text
Send NGSetupRequest to AMF
Received NGSetupResponse from AMF
Found USRP x300
RU 0 RF started
Received Ack of Msg4. CBRA procedure succeeded (UE Connected)
Received RRCSetupComplete (RRC_CONNECTED reached)
Initial Context Setup ... 1 PDU session(s)
created new DRB 1 for QFI 1 (5QI 9)
N3 GTP-U tunnel
Received RRCReconfigurationComplete
```

The AMF status table must independently show `5GMM-REGISTERED`. For complete
acceptance, the UE bearer must also be active and UE-originated ping/curl must
pass; see [runbook.md](runbook.md).

## Prompt for Codex on the replacement host

```text
This is the replacement server for the verified RedCap deployment. Read
README.md, docs/runbook.md, docs/troubleshooting.md, and
docs/successful-host-handoff.md completely before acting. Inspect this host,
the moved X310, NICs, installed UHD/OAI/Docker, and existing containers first.
Reproduce the pinned environment and bring up OAI Core plus the OAI gNB in the
documented order. Adapt machine-specific NIC and Docker addresses from live
discovery; do not copy the old management IP. Preserve unrelated workloads,
do not run Open5GS in parallel, do not print K/OPc, and never lower/reset SQN.
Use the tracked subscriber snapshot only after MySQL is healthy. Stop before RF
transmission if cabling/attenuation or local spectrum authorization is not
confirmed. Wait for NGSetupResponse and healthy X310 streaming, then report
that the UE can be enabled. Continue monitoring through 5GMM registration,
PDU-session/DRB establishment, and user-plane acceptance tests.
```

