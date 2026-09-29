#!/usr/bin/env python3
"""Read-only, filtered AMF/gNB connection events for the current OAI run."""

import argparse
import os
import re
import selectors
import signal
import subprocess
import sys

ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
EVENTS = {
    'AMF': re.compile(r'5GMM|registration|authentication|PDU[ _](?:session|resource)|'
                      r'IMSI/SUPI|SUPI|RAN UE NGAP|reject|fail', re.I),
    'gNB': re.compile(r'RedCap|Msg4|RRC_CONNECTED|DRB|RRCReconfigurationComplete|'
                      r'RRC Release|UE Context Release|Remove UE|Assertion|fatal|NGSetupResponse', re.I),
}
# Authentication debug dumps are not suitable for a connection summary.
SECRETS = re.compile(r'\b(?:K|OPc|RAND|AUTN|AUTS|XRES\w*|HXRES\w*|Kausf|Kseaf|Kamf|'
                     r'encPermanentKey|encOpcKey|key)\b', re.I)


class EventView:
    def __init__(self):
        self.amf_table = False
        self.amf_border = ''

    @staticmethod
    def emit(source, line):
        print(f'[{source}] {line}', flush=True)

    def display(self, source, raw):
        line = ANSI.sub('', raw.decode(errors='replace')).rstrip()
        if source == 'AMF':
            border = bool(re.fullmatch(r'\s*\|[-+| ]+\|', line))
            if "UEs' Information" in line:
                if self.amf_border:
                    self.emit(source, self.amf_border)
                self.amf_table = True
                self.emit(source, line)
                return
            if self.amf_table and line.lstrip().startswith('|'):
                self.emit(source, line)
                if border:
                    self.amf_table = False
                return
            self.amf_table = False
            self.amf_border = line if border else ''
        if not EVENTS[source].search(line) or SECRETS.search(line):
            return
        # Exclude JSON/debug payloads while keeping AMF event messages.
        if source == 'AMF' and ('{' in line or '[' not in line):
            return
        self.emit(source, line)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--amf-only', action='store_true',
                        help='show the AMF UE table and registration/session events only')
    parser.add_argument('--invocation', help='gNB systemd invocation ID; default: current run')
    args = parser.parse_args()
    commands = {'AMF': ['docker', 'logs', '--since', '2m', '--follow', 'oai-amf']}
    if not args.amf_only:
        invocation = args.invocation or subprocess.check_output(
            ['systemctl', 'show', 'oai-redcap-gnb.service', '-p', 'InvocationID', '--value'],
            text=True).strip()
        if not re.fullmatch(r'[0-9a-fA-F]{32}', invocation):
            raise RuntimeError('No current gNB invocation. Start the network first.')
        commands['gNB'] = ['journalctl', f'_SYSTEMD_INVOCATION_ID={invocation}', '--no-pager',
                           '--output=cat', '--since', '2 minutes ago', '--lines=all', '--follow']
    print('LIVE AMF VIEW: UE registration table and PDU-session events.\n'
          'Recent 2 minutes replayed, then live updates. Ctrl+C exits the view only.\n'
          '5GMM-REGISTERED confirms registration; verify packet delivery from the UE host.',
          flush=True)
    if not args.amf_only:
        print('Also following gNB: RedCap, RRC_CONNECTED and DRB events.', flush=True)
    view = EventView()
    children = []
    buffers = {}
    try:
        with selectors.DefaultSelector() as selector:
            for source, command in commands.items():
                # Children do not receive terminal Ctrl+C; finally reaps both.
                child = subprocess.Popen(command, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, start_new_session=True)
                children.append(child)
                selector.register(child.stdout, selectors.EVENT_READ, source)
                buffers[source] = b''
            while True:
                for key, _ in selector.select():
                    source = key.data
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        if buffers[source]:
                            view.display(source, buffers[source])
                        print(f'{source} log stream ended; viewer exiting. Network state unchanged.',
                              file=sys.stderr, flush=True)
                        return 1
                    lines = (buffers[source] + chunk).split(b'\n')
                    buffers[source] = lines.pop()
                    for line in lines:
                        view.display(source, line)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            child.stdout.close()


def interrupted(signum, frame):
    raise KeyboardInterrupt


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, interrupted)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nViewer stopped. Network left running.')
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Viewer error: {error}. Network state unchanged.', file=sys.stderr)
        sys.exit(1)
