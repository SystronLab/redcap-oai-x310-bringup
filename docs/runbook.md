# Replication runbook

## 1. Reference topology and variables

The verified machine used the following values:

| Item | Verified value |
|---|---|
| X310 address | `192.168.40.2` |
| X310 host NIC/address | `ens7f0`, `192.168.40.1/24` |
| X310 MTU | `9000` |
| RF board | Slot A / Radio 0, UBX-160 v2 |
| RF mode | SISO, 1 TX / 1 RX, internal clock |
| Band/carrier | n78, 30 kHz SCS, 106 PRB |
| SSB ARFCN | `641280` (3619.2 MHz) |
| Point A | `640752` (3611.28 MHz) |
| gNB center frequency | 3630.36 MHz |
| PLMN/TAC | `001/01`, TAC 1 |
| Slice | SST 1, SD `FFFFFF` |
| DNN | `oai` |
| Core bridge | `192.168.70.128/26` |
| Host N2/N3 | `192.168.70.129` |
| AMF/UPF | `192.168.70.132` / `192.168.70.134` |

Determine every Docker address again on the new machine. They are examples,
not universal defaults.

## 2. Inspect before changing anything

Run:

```bash
./scripts/inspect.sh ens7f0 192.168.40.2
docker inspect oai-amf
docker network ls
docker network inspect NETWORK_NAME
```

Required conditions:

- X310 is found and `uhd_usrp_probe` identifies both UBX boards.
- The selected host route to the X310 uses the dedicated NIC.
- OAI AMF, SMF, UPF, AUSF, UDM, UDR, NRF, MySQL and external DN are healthy.
- The built `nr-softmodem` has USRP support.
- The modem appears as MBIM/QMI or exposes documented serial ports.

Do not rebuild or redeploy components merely because they already exist.

## 3. Tune the X310 link

The supplied script checks NIC ring maxima before changing them:

```bash
sudo ./scripts/tune-x310.sh ens7f0
ping -c 3 192.168.40.2
uhd_usrp_probe --args="addr=192.168.40.2"
```

It configures MTU 9000, the maximum supported RX/TX rings, and 62,500,000-byte
socket buffer defaults/maxima. The current OAI X3xx UHD code may lower the two
live `*_max` values to 33,554,432 when opening the device. Restore them after
gNB startup if the deployment requires the larger values:

```bash
sudo sysctl -w net.core.wmem_max=62500000 net.core.rmem_max=62500000
```

## 4. Provision and verify the subscriber

Provision subscriber authentication out of band. Never commit K or OPc.
Verify without modifying the row:

```sql
SELECT ueid, authenticationManagementField, encPermanentKey, encOpcKey,
       sequenceNumber
FROM AuthenticationSubscription
WHERE ueid='IMSI';

SELECT ueid, servingPlmnid, singleNssai, dnnConfigurations
FROM SessionManagementSubscriptionData
WHERE ueid='IMSI';
```

Confirm AMF `8000`, the intended PLMN, SST/SD, DNN, and static address. Leave
SQN unchanged. A successful authentication legitimately advances it.

## 5. Build the X310 RedCap YAML

Use the RedCap YAML in the installed OAI revision as the source of truth:

```bash
cd /path/to/openairinterface5g/targets/PROJECTS/GENERIC-NR-5GC/CONF
cp -a gnb.sa.band78.fr1.106PRB.usrpb210.redcap.yaml \
  gnb.sa.band78.fr1.106PRB.usrpx310.redcap.yaml
```

Keep its `first_active_bwp`, `bwp_list`, initial 20 MHz BWPs, RedCap section,
timers, ARFCNs, Point A, carrier bandwidth and numerology unchanged. Replace
only live network addresses and X310 RF fields, following the fragment in
`config/x310-redcap-ru.yaml`.

Validate the result:

```bash
python3 - /path/to/gnb.sa.band78.fr1.106PRB.usrpx310.redcap.yaml <<'PY'
import sys, yaml
with open(sys.argv[1]) as f:
    yaml.safe_load(f)
print("YAML OK")
PY
```

In this OAI revision, `tx_subdev` and `rx_subdev` are supported YAML fields.
`A:0` selects the first UBX. OAI/UHD selected `TX/RX` for TX and `RX2` for RX;
verify the actual antenna ports printed at startup and cable accordingly.

The X310 calibration table uses an internal calibrated gain reference. Inspect
the exact revision's `radio/USRP/usrp_lib.cpp` and X310 examples. Do not assume
that `max_rxgain` is identical to the UBX hardware's 31.5 dB range, and do not
copy the B210 value 114.

## 6. Start logs before the gNB

```bash
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p "$HOME/redcap-bringup-logs"
docker logs --since 1m -f oai-amf >"$HOME/redcap-bringup-logs/$stamp-amf.log" 2>&1 &
docker logs --since 1m -f oai-smf >"$HOME/redcap-bringup-logs/$stamp-smf.log" 2>&1 &
docker logs --since 1m -f oai-upf >"$HOME/redcap-bringup-logs/$stamp-upf.log" 2>&1 &
```

Some OAI images buffer Docker stdout. If files remain empty, snapshot with
`docker logs --since TIMESTAMP CONTAINER` after the event.

## 7. Launch the gNB

From the build directory:

```bash
sudo env LD_LIBRARY_PATH="$PWD${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  stdbuf -oL -eL ./nr-softmodem \
  -O ../../../targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb.sa.band78.fr1.106PRB.usrpx310.redcap.yaml \
  --gNBs.[0].min_rxtxtime 6 \
  --usrp-tx-thread-config 1 \
  -E --continuous-tx 2>&1 | tee "$HOME/redcap-bringup-logs/$stamp-gnb.log"
```

`LD_LIBRARY_PATH` is required when `libparams_yaml.so` is present beside the
binary but is not installed in the dynamic loader's default path.

Do not proceed until the log confirms:

- X310 opens on channel A:0.
- Internal clock and time source are selected.
- RX/TX streaming starts without fatal errors.
- `Received NGSetupResponse from AMF` appears.

## 8. Prepare and connect the EM8695

The verified EM8695 USB composition was MBIM-only (`1199:90e5`), exposing
`/dev/cdc-wdm1` and `wwan0` with no `/dev/ttyUSB*`. Do not guess an AT port.

If ModemManager reports the populated SIM in an inactive slot:

```bash
mmcli -m MODEM_ID
sudo mmcli -m MODEM_ID --set-primary-sim-slot=2
```

Wait for re-enumeration; the modem number may change. Verify the IMSI before
registration:

```bash
mbimcli -d /dev/cdc-wdm1 --query-subscriber-ready-status --device-open-proxy
```

Stop if the IMSI is not the provisioned subscriber.

Connect the IPv4 `oai` context:

```bash
sudo mmcli -m MODEM_ID --simple-connect='apn=oai,ip-type=ipv4'
mmcli -m MODEM_ID
mmcli -b BEARER_ID
```

For a serial composition, use the vendor-documented AT port and inspect band
profiles before issuing `AT!BAND`. Do not apply undocumented profiles or reset
the modem.

## 9. Configure the MBIM host interface and internet policy

Use the address, prefix and gateway reported by `mmcli -b BEARER_ID`:

```bash
sudo ip link set wwan0 up
sudo ip addr replace UE_ADDRESS/PREFIX dev wwan0
sudo ./scripts/ue-policy-route.sh wwan0 UE_ADDRESS UE_GATEWAY
```

Why source policy is necessary on an all-in-one host:

```text
locally generated test traffic, source UE IP -> wwan0 -> modem
UPF-forwarded traffic, source UPF bridge IP -> normal host uplink
```

A destination route such as `8.8.8.8/32 via UE_GATEWAY dev wwan0` matches both
flows. It sends the UPF's already-decapsulated packet back into the modem,
causing a loop. The script installs a rule matching only the UE source address.

The UPF must SNAT UE traffic toward its core-facing interface, and Docker must
masquerade the core subnet toward the physical uplink. Inspect with:

```bash
docker exec oai-upf iptables -t nat -S
sudo iptables -t nat -S
```

## 10. Acceptance tests

Registration evidence:

- Modem state `registered` or `connected`.
- Operator `00101`, access technology `5gnr`, packet service attached.
- gNB logs PRACH, RRC Setup Complete, Initial UE Message and Security Mode Complete.
- Core logs successful 5G-AKA and Registration Accept.

PDU evidence:

- MBIM connection state `activated`.
- gNB creates PDU session, DRB and N3 GTP-U tunnel.
- SMF sends PDU Session Establishment Accept.
- UPF has matching PDR/FAR entries.

Traffic tests:

```bash
ping -I wwan0 -c 3 8.8.8.8
curl --interface wwan0 --max-time 15 -o /dev/null \
  -w 'HTTP=%{http_code} IP=%{remote_ip}\n' https://www.google.com/
mbimcli -d /dev/cdc-wdm1 --query-packet-statistics --device-open-proxy
```

The verified result was HTTP 200 and ICMP replies with zero MBIM errors or
discards.
