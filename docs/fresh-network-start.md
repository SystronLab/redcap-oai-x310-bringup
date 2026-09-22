# Fresh network start on this server

This helper is specific to `/home/systron/redcap-bringup` on this server, the
`redcap-oai` Compose project, and the X310 interface `enp46s0` at
`192.168.40.1/24`. It launches the pinned OAI checkout's UHD 4.10 build through
`/home/systron/redcap-bringup/start-gnb-uhd410.sh` as the transient systemd unit
`redcap-gnb-uhd410.service`.
It does not stop unrelated Docker projects or modify the management NIC.

1. Stop the laptop connection watcher and **power off the UE**. Resetting only
   the core cannot clear the modem's stored registration context.
2. On the server:

   ```bash
   cd /home/systron/Mohit/redcap-oai-x310-bringup
   sudo ./scripts/network-fresh.sh start --ue-off
   ```

3. Wait for `NETWORK READY`, then power on the UE and run the laptop helper.
   The command remains open with a filtered live AMF view. A successfully
   registered UE appears as `5GMM-REGISTERED`. Press `Ctrl+C` to close the view;
   this does not stop the core or gNB.
   This readiness message means the core passed health checks and the current
   gNB invocation logged NG Setup acceptance and RF startup. It does not prove
   RF coverage, UE registration, or user-plane connectivity.

Other commands:

```bash
sudo ./scripts/network-fresh.sh check  # read-only preflight; no startup
sudo ./scripts/network-fresh.sh stop   # stop gNB and all nine lab containers
sudo ./scripts/network-fresh.sh watch  # re-open the live AMF UE/session view
sudo journalctl -u redcap-gnb-uhd410.service -f
```

## What is reset

- gNB process state, RRC/NGAP contexts, and in-process radio state.
- All nine lab containers are recreated: MySQL, NRF, UDR, UDM, AUSF, AMF,
  SMF, UPF, and external DN. No image pulls/upgrades occur.
- In-memory registration/session contexts and UPF container network state.
- Rows in the runtime MySQL tables `Amf3GppAccessRegistration`,
  `SmfRegistrations`, `SdmSubscriptions`, and `AuthenticationStatus`.
  These are deleted transactionally while all other core functions are stopped.
  No runtime-table backup is made; those rows cannot be restored by this script.

## What must remain

Subscriber credentials, subscription/DNN/slice configuration, and the current
AKA sequence counters in `AuthenticationSubscription` are retained. Erasing
these or importing an old snapshot is not a safe way to reset network sessions.
The script verifies that the existing MySQL data volume is reused across
container recreation. It refuses to proceed if that volume/container is absent.
Compose recreation preserves mounted volumes; do not add `--renew-anon-volumes`
or use `down -v`. See the [Docker Compose documentation](https://docs.docker.com/reference/cli/docker/compose/up/).

Existing configuration, Docker bridge, images, host routing/conntrack, journal
history, and modem/SIM nonvolatile state are not globally erased. This is a
**fresh runtime/session start**, not a factory reset or a claim of total statelessness.
Container recreation removes their old writable layers/logs; journal history
remains available. The X310 is reopened, not physically power-cycled.

The helper tunes the dedicated NIC/rings, sets host socket buffers and enables
IPv4 forwarding using the existing lab tuning procedure. Those host settings
are not rolled back on shutdown. No software or boot services are installed.

On startup failure the helper attempts to stop all lab components and returns
nonzero. The gNB has automatic restart disabled, so a crash is visible rather
than silently beginning a different run. Inspect logs and address the error
before another fresh start. The known RRC reestablishment assertion is not fixed
by this helper.

Validation: shell syntax and real read-only preflight passed during creation.
On 2026-09-22 the operator ran a full fresh start; current-invocation logs
confirmed NG Setup and RF startup, followed by UE registration and an active
`oai` PDU session at `10.0.0.2`. External-DN-to-UE ping returned 3/3 replies,
and the laptop operator confirmed UE-to-server ping. Public internet access
from the laptop was not independently verified.
