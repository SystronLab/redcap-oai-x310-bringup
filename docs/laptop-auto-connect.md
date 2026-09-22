# Laptop UE connection helper

Run this on the **laptop with the EM8695 attached**, not on the gNB server.
Requires Python 3, ModemManager/mmcli and NetworkManager/nmcli. It targets the
tested mmcli 1.20 interface. Both management services must already be running.

```bash
sudo python3 scripts/connect-ue.py --watch
```

Leave the terminal open. The script detects an already attached modem or waits
for a new one, checks its active SIM, selects 5G-only/n78 if necessary, requests
PLMN `00101`, then activates IPv4 APN `oai` through NetworkManager. It does not
guess PINs, change SIM slots by default, explicitly reset the modem, or restart
the core/gNB. If the occupied slot is not active, specify it explicitly:

```bash
sudo python3 scripts/connect-ue.py --watch --sim-slot 1
```

Use `--sim-slot 2` if the SIM is physically in slot 2. The helper switches only
when needed and follows the same modem's stable device ID if its ModemManager
index changes. It waits up to 90 seconds after the switch command for the chosen
slot and SIM to appear. Firmware may restart/re-enumerate during slot switching.
It refuses to switch a modem with an active/transitioning data connection; first
disconnect that connection yourself. It never guesses which physical slot is occupied.
`sim-pin2` alone is not treated as a registration-blocking PIN request.

For one attempt, omit `--watch`. To register without a data session or profile:

```bash
sudo python3 scripts/connect-ue.py --register-only
```

Defaults: discovery waits up to 180 seconds (indefinitely with `--watch`), one
registration request waits up to 120 seconds, and one data activation waits up
to 120 seconds. A failed attempt stops, or waits for a USB replug in watch mode.
It deliberately does not repeatedly reset or reconnect an attached failed UE.
ModemManager/firmware can perform their own internal retries.

The watcher handles changing modem indices. If multiple EM8695s are present,
use `--modem DEVICE_ID`, taking the stable device ID from `mmcli -m ID`.
Other options: `--plmn 00101`, `--apn oai`, `--wait 180`. Band n78 is fixed
for this lab. Stop other connection scripts before running it.

## Host networking and cleanup

To use the UE for the laptop's internet access (Wi-Fi can be off), run:

```bash
sudo python3 scripts/connect-ue.py --watch --sim-slot 1 --internet
```

This option creates a separate `oai-ue-...-internet` GSM profile. NetworkManager
installs the active bearer's IPv4 address, prefix, gateway and DNS. The cellular
default route has metric 50 and DNS priority -50; another lower-metric route can
still take precedence. No address is hardcoded and no firewall rules are flushed.
An existing connected bearer must be disconnected before switching profiles.
The default mode below continues to preserve existing default routes and DNS.

After `DATA CONNECTION ACTIVE`, verify on the laptop:

```bash
ip -4 route get 1.1.1.1
ping -c 3 1.1.1.1
curl -4 --max-time 15 https://example.com
```

The route should show the modem's data interface and assigned source address.

For this server's deployment, test both directions through the radio link:

```bash
# Server: external DN routes through the UPF to the current UE address.
docker exec oai-ext-dn ping -c 4 10.0.0.2

# Laptop: bind to the actual modem data interface.
ping -I wwan0 -c 4 192.168.70.129
```

Replace `10.0.0.2` with the active bearer's address and `wwan0` with its data
interface. `192.168.70.129` is this server's OAI Docker bridge address.
On 2026-09-22, the fresh run established the `oai` session at `10.0.0.2`;
server-to-UE ping returned 3/3 replies at about 27 ms, and the laptop operator
confirmed UE-to-server ping. These checks do not establish public internet or
DNS connectivity; use the separate tests above for those.

If activation says `No suitable device`, collect `nmcli radio all`,
`nmcli device status`, and `mmcli -m CURRENT_MODEM_ID`. NetworkManager needs an
available managed GSM device. An unavailable Wi-Fi device mentioned in that
error does not mean Wi-Fi is required. If WWAN is disabled, enable it with
`sudo nmcli radio wwan on`. Address/route commands cannot repair a rejected
PDU session: confirm a connected bearer before configuring IP manually.

Data mode creates a persistent, modem-specific profile with a deterministic
`oai-ue-...` name and a NetworkManager-assigned UUID. Autoconnect is disabled:
this script initiates activation. Existing matching profiles are reused after
checking their device/APN/network and route/DNS settings.
NetworkManager obtains and installs the bearer IP configuration. Without `--internet`, the profile
does not replace the laptop's default route or DNS, so ordinary internet traffic
continues over Wi-Fi. No source-policy internet route is installed by this helper.
For internet testing over the UE, separately use `scripts/ue-policy-route.sh`
with the actual interface/address/gateway displayed by NetworkManager.

Ctrl-C stops the watcher but leaves the connection up. To disconnect or remove
the helper's profile, identify its exact UUID with `nmcli connection show`, then:

```bash
sudo nmcli connection down uuid PROFILE_UUID
sudo nmcli connection delete uuid PROFILE_UUID
```

Do not run these placeholder commands without substituting the actual UUID.
No boot service or udev rule is installed; `--watch` operates only while running.

## What success means

Registration success is the modem's report of home/roaming registration on the
requested PLMN, not independent proof of matching core state. Confirm it against
AMF/gNB logs, especially after restarting the core. Data success is an active
NetworkManager profile, not an end-to-end ping test. Automation cannot guarantee
immediate registration or repair missing RF coverage, radio/firmware faults,
subscriber mismatches, or the observed gNB reestablishment assertion.

If it fails, retain the printed error and collect:

```bash
mmcli -L
mmcli -m CURRENT_MODEM_ID
sudo journalctl -u ModemManager --since '5 minutes ago' --no-pager
```

The helper prints connection details, including the modem's stable device ID;
redact identifiers before sharing logs publicly.
