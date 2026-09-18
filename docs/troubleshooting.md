# Troubleshooting

## No NG Setup

Do not debug the SIM first. Check AMF IP, host N2 address, SCTP/38412, Docker
routing, PLMN and TAC. The gNB must receive `NGSetupResponse` before UE work.

## No cell found

Check n78 antennas, SSB frequency, RF cabling, gain, LO state, RedCap SIB
signalling and local spectrum constraints.

## Cell found but no RACH/RRC

Check the RX connector actually selected by UHD, uplink gain, timing, antenna
isolation and PRACH configuration. OAI prints `UE ... is RedCap` after decoding
the RedCap request.

## Authentication failure

Confirm the IMSI first. Compare AMF, K/OPc and SQN privately. Never reset SQN
as a first response. Authentication resynchronization should be diagnosed from
AUSF/UDM/UDR logs.

## PDU succeeds but gets a pool address instead of the provisioned static IP

In the verified deployment, MySQL contained static `10.0.0.6`, but the modem
received `10.0.0.2`. SMF logged:

```text
The Session Management Subscription data is not available
Retrieve Session Management Subscription data from local configuration
PAA, Ipv4 Address: 10.0.0.2
```

It also received HTTP 404 while registering the SMF session with UDM. This is a
core subscription-retrieval/API issue, not a malformed MySQL record. Preserve
authentication data and repair the UDM/UDR/SMF API path before expecting the
static address.

## External DN works but public internet does not

Test in layers:

1. UE to UPF gateway.
2. UE to external-DN container.
3. External-DN to host Docker gateway.
4. Host to internet.
5. UE to a known reachable internet endpoint.

Inspect both NAT layers:

- UPF: UE subnet to UPF bridge address.
- Docker host: core bridge subnet to physical uplink.

Use `tcpdump` simultaneously on the core bridge and physical uplink. If a UE
SYN appears repeatedly on the core bridge but never on the uplink, inspect host
policy routing. Remove destination-specific routes through `wwan0` and use the
source-based helper script.

Some networks block public ICMP or port 80. Test HTTPS as well as ping, and
first verify that the host itself can reach the chosen endpoint.

## YAML module cannot load

If startup reports `libparams_yaml.so: cannot open shared object file` while the
file exists in the build directory, launch with that directory in
`LD_LIBRARY_PATH`. A rebuild is unnecessary.

## X310 RX gain is unexpectedly zero

OAI applies `calib_table_x310` before calling UHD. `max_rxgain` is therefore a
calibrated OAI reference rather than a direct UBX gain command. Inspect startup
lines showing requested gain, calibration offset and actual UHD gain. Use the
checked-out X310 examples/code to choose values; do not use B210's 114 blindly.

