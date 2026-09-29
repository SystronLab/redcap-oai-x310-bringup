# UDP messages over the UE connection

The server listens on its OAI bridge address, `192.168.70.129:5005`, prints
received messages, and echoes their bytes back to the sender. The laptop
client binds to `wwan0`, so it cannot silently send over Wi-Fi instead.

## Server

Start the mobile network first. If the temporary background listener from the
initial setup is still running, stop it to free the port:

```bash
sudo systemctl stop redcap-udp-server.service
```

If systemd says the unit is not loaded, continue: no such background listener
exists. Run the server in the foreground:

```bash
cd /home/systron/Desktop/redcap-oai-x310-bringup
python3 scripts/udp-server.py
```

Incoming messages appear in this terminal. Ctrl+C stops the UDP server and
leaves the mobile network running. The network start/stop script does not
manage the UDP listener.

## Laptop

From the laptop's clone of this repository, get the new client and connect
the UE with `connect-ue.py`:

```bash
git pull --ff-only
sudo python3 scripts/connect-ue.py --watch
```

Leave the connection helper running and open another terminal in the same
repository directory.

With the verified EM8695 MBIM data interface `wwan0`, add a route for this lab
server and start the client:

```bash
sudo ip route replace 192.168.70.129/32 dev wwan0
sudo python3 scripts/udp-client.py
```

This route targets only the lab server and preserves the laptop's default
route. If your data interface has another name, use that name in the route
and pass `--interface NAME` to the client. The route may need adding again
after a USB reconnect.

Type a message and press Enter. A displayed `echo:` confirms a round trip.
Type `/quit` or press Ctrl+C to stop the client. UDP does not guarantee
delivery or ordering; a timeout means no reply was received within five
seconds. Messages are limited to 1200 UTF-8 bytes by this client.

Remove the test route when finished:

```bash
sudo ip route del 192.168.70.129/32 dev wwan0
```

The UPF performs source NAT, so server logs can show its address
`192.168.70.134` instead of the UE's `10.0.0.x` address.
