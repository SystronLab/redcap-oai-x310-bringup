#!/usr/bin/env python3
"""Send interactive UDP messages through the UE and print echo replies."""

import argparse
import socket


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', default='192.168.70.129')
    parser.add_argument('--port', type=int, default=5005)
    parser.add_argument('--interface', default='wwan0')
    args = parser.parse_args()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                          args.interface.encode() + b'\0')
        client.settimeout(5)
        client.connect((args.server, args.port))
        print(f'UDP to {args.server}:{args.port} via {args.interface}. '
              'Type a message; /quit exits.')
        while True:
            try:
                message = input('message> ')
            except EOFError:
                break
            if message == '/quit':
                break
            data = message.encode('utf-8')
            if len(data) > 1200:
                print('Keep messages within 1200 UTF-8 bytes.')
                continue
            try:
                client.send(data)
                reply = client.recv(65535)
                print('echo:', repr(reply.decode('utf-8', errors='replace')))
            except socket.timeout:
                print('No reply within 5 seconds; delivery is unconfirmed.')
            except OSError as error:
                print(f'UDP error: {error}')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nUDP client stopped.')
    except OSError as error:
        raise SystemExit(f'Cannot open UE connection: {error}. '
                         'Run with sudo and check the route through wwan0.')
