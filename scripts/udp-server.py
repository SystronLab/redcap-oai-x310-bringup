#!/usr/bin/env python3
"""Print and echo UDP messages received from the lab UE."""

import argparse
import datetime
import socket


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='192.168.70.129')
    parser.add_argument('--port', type=int, default=5005)
    args = parser.parse_args()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind((args.bind, args.port))
        print(f'UDP server listening on {args.bind}:{args.port}; echo replies enabled.',
              flush=True)
        while True:
            data, peer = server.recvfrom(65535)
            stamp = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
            print(f'{stamp} {peer[0]}:{peer[1]} ({len(data)} bytes): '
                  f'{data.decode("utf-8", errors="replace")!r}', flush=True)
            try:
                server.sendto(data, peer)
            except OSError as error:
                print(f'Reply to {peer} failed: {error}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nUDP server stopped.')
