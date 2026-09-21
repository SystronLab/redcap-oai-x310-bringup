# Two-computer replication runbook

## 1. Topology and roles

- **Server**: OAI 5G Core containers, OAI gNB, and the Ethernet-attached X310.
- **Laptop**: USB-attached EM8695, ModemManager/MBIM, `wwan0`, and UE tests.
- **Management network**: optional Ethernet/Wi-Fi for Git, SSH, and logs. It is
  separate from the cellular data path.

```text
                              SERVER
                 +-----------------------------+
internet <------>| host NAT -> UPF -> N3       |
                 |              AMF <- N2      |
                 |                    OAI gNB   |
                 +-----------------------+-----+
                                         | dedicated Ethernet
                                      X310/UBX
                                         |
                                     n78 radio
                                         |
                                    EM8695/USB
                                         |
                 +-----------------------+-----+
                 | wwan0                       | LAPTOP
                 | source-routed UE traffic    |
                 +-----------------------------+
```

N2 and N3 remain local to the server. The laptop needs no route to the AMF,
UPF, or Docker bridge. Its `wwan0` address comes from the 5G PDU session, not
the management LAN. Do not bridge `wwan0` to Wi-Fi/Ethernet.

| Item | Verified example | Owner |
|---|---|---|
| X310 address | `192.168.40.2` | X310 |
| X310 NIC/address | `ens7f0`, `192.168.40.1/24` | server |
| X310 MTU | `9000` | server |
| RF board/mode | Slot A, UBX-160 v2, SISO | server |
| Band/carrier | n78, 30 kHz SCS, 106 PRB | radio |
| SSB ARFCN / Point A | `641280` / `640752` | gNB config |
| PLMN/TAC | `001/01`, TAC 1 | core and gNB |
| Slice / DNN | SST 1, SD `FFFFFF` / `oai` | core and gNB |
| Core bridge | `192.168.70.128/26` | server |
| Server N2/N3 | `192.168.70.129` | server |
| AMF/UPF | `192.168.70.132` / `192.168.70.134` | containers |

Rediscover Docker addresses on the server. The values above are not universal.
The server management IP is only for SSH; do not put it in the gNB YAML unless
the core was deliberately deployed on that network.

## 2. Clone and inspect

Clone this repository independently on both computers. Before changing either
one, identify its role and inspect the existing state.

On the **server**:

```bash
git status --short
./scripts/inspect.sh ens7f0 192.168.40.2
docker ps
docker network ls
docker inspect oai-amf oai-smf oai-upf
docker network inspect CORE_NETWORK_NAME
```

Confirm the X310 uses its dedicated NIC, both UBX boards probe, all required
core NFs are healthy, `nr-softmodem` has USRP support, and PLMN/TAC/slice/DNN
and N2/N3 addresses agree. Do not redeploy healthy components.

On the **laptop**:

```bash
uname -a
ip -br address
ip route
lsusb
ls -l /dev/cdc-wdm* /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true
mmcli -L
```

Confirm the EM8695, its control device, and its network interface are present.
The laptop must retain a normal management/default route independently of
`wwan0`. Do not put subscriber secrets or identifiers in this repository or a
Codex prompt/transcript.

## 3. Server setup

### Tune the X310 link

```bash
sudo ./scripts/tune-x310.sh ens7f0
ping -c 3 192.168.40.2
uhd_usrp_probe --args="addr=192.168.40.2"
```

The script sets MTU 9000, supported ring maxima, and 62,500,000-byte socket
buffers. OAI may lower live `*_max` values while opening an X3xx. Restore them
after gNB startup if needed:

```bash
sudo sysctl -w net.core.wmem_max=62500000 net.core.rmem_max=62500000
```

### Verify the subscriber

Provision authentication on the server out of band. Never commit K or OPc.
Verify the existing row without modifying it:

```sql
SELECT ueid, authenticationManagementField, encPermanentKey, encOpcKey,
       sequenceNumber
FROM AuthenticationSubscription WHERE ueid='IMSI';

SELECT ueid, servingPlmnid, singleNssai, dnnConfigurations
FROM SessionManagementSubscriptionData WHERE ueid='IMSI';
```

Confirm AMF `8000`, PLMN, SST/SD, DNN, and any static address. Leave SQN
unchanged; successful authentication legitimately advances it.

### Build the X310 RedCap YAML

Use the RedCap YAML from the installed OAI revision as the source of truth:

```bash
cd /path/to/openairinterface5g/targets/PROJECTS/GENERIC-NR-5GC/CONF
cp -a gnb.sa.band78.fr1.106PRB.usrpb210.redcap.yaml \
  gnb.sa.band78.fr1.106PRB.usrpx310.redcap.yaml
```

Keep its RedCap section, BWPs, timers, ARFCNs, Point A, carrier bandwidth, and
numerology. Replace only live server/core addresses and X310 RF fields using
`config/x310-redcap-ru.yaml` as a guide.

```bash
python3 - /path/to/gnb.sa.band78.fr1.106PRB.usrpx310.redcap.yaml <<'PY'
import sys, yaml
with open(sys.argv[1]) as f:
    yaml.safe_load(f)
print("YAML OK")
PY
```

`A:0` selects the first UBX. Verify ports printed at startup and cable them
accordingly. X310 gain is an OAI calibrated reference; never copy B210's 114.

### Start the core and logs

Use the procedure belonging to the installed OAI Core checkout. Do not assume
a Compose filename or redeploy healthy containers. Then capture logs:

```bash
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p "$HOME/redcap-bringup-logs"
docker logs --since 1m -f oai-amf >"$HOME/redcap-bringup-logs/$stamp-amf.log" 2>&1 &
docker logs --since 1m -f oai-smf >"$HOME/redcap-bringup-logs/$stamp-smf.log" 2>&1 &
docker logs --since 1m -f oai-upf >"$HOME/redcap-bringup-logs/$stamp-upf.log" 2>&1 &
```

### Launch the gNB

From the server's OAI build directory:

```bash
sudo env LD_LIBRARY_PATH="$PWD${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  stdbuf -oL -eL ./nr-softmodem \
  -O ../../../targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb.sa.band78.fr1.106PRB.usrpx310.redcap.yaml \
  --gNBs.[0].min_rxtxtime 6 \
  --usrp-tx-thread-config 1 \
  -E --continuous-tx 2>&1 | tee "$HOME/redcap-bringup-logs/$stamp-gnb.log"
```

Do not start laptop registration until X310 streaming is healthy and the log
contains `Received NGSetupResponse from AMF`.

## 4. Laptop setup

The verified EM8695 was MBIM-only (`1199:90e5`), with `/dev/cdc-wdm1` and
`wwan0` but no serial ports. Discover the actual names; do not guess an AT port.

If the populated SIM is in an inactive slot:

```bash
mmcli -m MODEM_ID
sudo mmcli -m MODEM_ID --set-primary-sim-slot=2
```

Wait for re-enumeration; the modem ID may change. Verify the SIM identity
locally, without pasting it into Codex, and stop if it is not the provisioned
subscriber:

```bash
mbimcli -d /dev/cdc-wdm1 --query-subscriber-ready-status --device-open-proxy
```

Once the server is ready, connect and inspect the bearer:

```bash
sudo mmcli -m MODEM_ID --disable
sudo mmcli -m MODEM_ID --set-allowed-modes='5g'
sudo mmcli -m MODEM_ID --enable
sudo mmcli -m MODEM_ID --simple-connect='apn=oai,ip-type=ipv4'
mmcli -m MODEM_ID
mmcli -b BEARER_ID
```

The verified EM8695 needed its supported 5G-only mode for NR SA data-session
activation. In dual LTE/5G mode it registered home on `00101`, reported packet
service attached and LTE plus 5G NR, but the `oai` bearer timed out and then
failed with `org.freedesktop.ModemManager1.Error.MobileEquipment.Unknown`.
After switching to 5G-only mode, the same bearer request succeeded. Setting
the mode while disabled makes the transition explicit; allow registration to
settle after enabling if it does not complete immediately.

Use the address, prefix, and gateway reported by that bearer:

```bash
sudo ip link set wwan0 up
sudo ip addr replace UE_ADDRESS/PREFIX dev wwan0
sudo ./scripts/ue-policy-route.sh wwan0 UE_ADDRESS UE_GATEWAY
ip rule show
ip route show table 100
```

This routes only traffic sourced from the UE address into `wwan0`, preserving
the laptop's management default route. Do not replace that default route or add
destination-specific routes such as `8.8.8.8/32 via UE_GATEWAY`.

## 5. Server forwarding and NAT

The UPF must SNAT UE traffic toward its core-facing interface, and the server
must masquerade the core subnet toward its physical internet uplink. Check
these only on the server:

```bash
docker exec oai-upf iptables -t nat -S
sudo iptables -t nat -S
sysctl net.ipv4.ip_forward
```

The laptop needs no core routes, forwarding, or NAT for its own UE traffic.

## 6. Acceptance tests

On the **server**, confirm successful AKA/Registration Accept, RedCap RRC,
PDU session and DRB creation, N3 GTP-U, and matching UPF PDR/FAR entries.

On the **laptop**, confirm operator `00101`, access technology `5gnr`, and an
activated bearer, then run:

```bash
ping -I wwan0 -c 3 8.8.8.8
curl --interface wwan0 --max-time 15 -o /dev/null \
  -w 'HTTP=%{http_code} IP=%{remote_ip}\n' https://www.google.com/
mbimcli -d /dev/cdc-wdm1 --query-packet-statistics --device-open-proxy
```

Correlate laptop timestamps with server gNB/AMF/SMF/UPF logs. See
[troubleshooting.md](troubleshooting.md) if a layer fails.

## 7. Prompts for Codex on each computer

Run Codex from the respective clone. Replace path/interface placeholders, but
never add subscriber secrets.

**Server prompt:**

```text
This is the server role from docs/runbook.md. It should run the OAI 5G Core,
OAI gNB, and X310; the EM8695 is on another laptop. Read the documentation,
inspect this host and existing OAI/core checkouts, and report discovered NIC,
X310, Docker, N2/N3, PLMN, slice, and DNN values before changing anything.
Then perform the server-side setup in order. Preserve healthy containers and
unrelated workloads. Do not request, print, or commit K/OPc. Stop before RF
transmission if spectrum authorization or RF cabling is unclear.
```

**Laptop prompt:**

```text
This is the laptop/UE role from docs/runbook.md. The core, gNB, and X310 run on
another machine; this laptop owns only the USB EM8695, ModemManager/MBIM,
wwan0, source-policy routing, and UE traffic tests. Read the documentation and
inspect the modem and networking before changing anything. Preserve the normal
Wi-Fi/Ethernet default route. Do not request, print, or commit SIM identity or
authentication secrets. Wait until I confirm the server gNB has received
NGSetupResponse, then connect APN oai, use bearer values actually reported by
ModemManager, and run the acceptance tests.
```

The two Codex sessions do not synchronize merely because both clones contain
the same repository. Manually relay the readiness statement and relevant
non-secret log lines, or use SSH/shared terminals.
