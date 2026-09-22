#!/usr/bin/env python3
"""Register an EM8695 on the lab SA network; optionally activate an NM bearer."""

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid


class ConnectionError(RuntimeError):
    pass


def log(message):
    print(time.strftime('[%H:%M:%S]'), message, flush=True)


def run(*command, timeout=40):
    try:
        result = subprocess.run(command, text=True, capture_output=True,
                                timeout=timeout, env={**os.environ, 'LC_ALL': 'C'})
    except subprocess.TimeoutExpired as error:
        raise ConnectionError(f'{command[0]} timed out after {timeout}s') from error
    if result.returncode:
        raise ConnectionError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def mm_json(*arguments):
    try:
        return json.loads(run('mmcli', '--timeout=25', '-J', *arguments))
    except ValueError as error:
        raise ConnectionError('Invalid JSON from mmcli') from error


def field(data, path, default=''):
    for key in path.split('.'):
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return data


def modem_paths():
    return mm_json('-L').get('modem-list', [])


def discover(selector):
    matches = []
    for path in modem_paths():
        data = mm_json('-m', path)
        model = field(data, 'modem.generic.model')
        identity = field(data, 'modem.generic.device-identifier')
        if selector:
            selected = selector in (path, path.rsplit('/', 1)[-1], identity)
        else:
            selected = 'EM8695' in model.upper()
        if selected:
            matches.append((path, data))
    if len(matches) > 1:
        raise ConnectionError('Multiple matching modems; select one with --modem DEVICE_ID.')
    return matches[0] if matches else None


def registered(data, plmn):
    return (field(data, 'modem.3gpp.registration-state') in ('home', 'roaming')
            and field(data, 'modem.3gpp.operator-code') == plmn)


def check_sim(data):
    slot = field(data, 'modem.generic.primary-sim-slot', 'unknown')
    sim = field(data, 'modem.generic.sim')
    log(f'Active SIM slot: {slot}; SIM: {sim or "not detected"}')
    if not isinstance(sim, str) or not sim.startswith('/org/freedesktop/ModemManager1/SIM/'):
        raise ConnectionError('No active SIM. Check the occupied slot and rerun with '
                              '--sim-slot 1 or --sim-slot 2, as appropriate.')
    lock = field(data, 'modem.generic.unlock-required')
    if lock not in ('', '--', 'none', 'sim-pin2', 'sim-puk2'):
        raise ConnectionError(f'SIM/modem lock: {lock}. Unlock it manually; no PIN is guessed.')


def select_sim_slot(path, data, slot):
    if slot is None or str(field(data, 'modem.generic.primary-sim-slot')) == str(slot):
        return path, data
    if field(data, 'modem.generic.state') in ('connected', 'connecting', 'disconnecting'):
        raise ConnectionError('Disconnect the current data connection before switching SIM slots.')
    identity = field(data, 'modem.generic.device-identifier')
    if not identity or identity == '--':
        raise ConnectionError('Cannot safely rediscover modem after slot switch: missing device ID.')
    log(f'Selecting SIM slot {slot}; waiting for the same modem to reappear (up to 90s).')
    switch_error = ''
    try:
        run('mmcli', '-m', path, f'--set-primary-sim-slot={slot}',
            '--timeout=60', timeout=70)
    except ConnectionError as error:
        # A disappearing D-Bus object may interrupt the reply despite a successful switch.
        switch_error = str(error)
        log(f'Slot-switch reply: {switch_error}. Checking the actual slot before continuing.')
    deadline = time.monotonic() + 90
    last_match = None
    while time.monotonic() < deadline:
        time.sleep(3)
        try:
            match = discover(identity)
        except ConnectionError:
            # Re-enumeration can invalidate a path between listing and reading it.
            continue
        if not match:
            continue
        new_path, new_data = match
        if str(field(new_data, 'modem.generic.primary-sim-slot')) != str(slot):
            continue
        last_match = match
        sim = field(new_data, 'modem.generic.sim')
        if (field(new_data, 'modem.generic.state') not in ('unknown', 'initializing')
                and isinstance(sim, str) and sim.startswith('/org/freedesktop/ModemManager1/SIM/')):
            log(f'SIM slot {slot} confirmed on {new_path}.')
            return match
    if last_match:
        # Return the new path so the caller can report the actual SIM/lock failure
        # and mark this incarnation as attempted rather than retrying endlessly.
        return last_match
    raise ConnectionError(f'SIM slot {slot} was not confirmed within 90s. {switch_error}')


def ensure_data_profile(data, args):
    identity = field(data, 'modem.generic.device-identifier')
    if not identity or identity == '--':
        raise ConnectionError('Missing stable device identifier; cannot bind a data profile safely.')
    # Older nmcli rejects setting connection.uuid even during add. Let NM assign
    # it; use a deterministic name to find this helper's profile on subsequent runs.
    name = 'oai-ue-' + str(uuid.uuid5(uuid.NAMESPACE_URL,
                                    f'urn:oai-connect-ue:{identity}:{args.plmn}:{args.apn}'))
    internet = getattr(args, 'internet', False)
    if internet:
        name += '-internet'
    preserve_routes = 'no' if internet else 'yes'
    internet_settings = (('ipv4.route-metric', '50', 'ipv4.dns-priority', '-50')
                         if internet else ())

    def lookup():
        rows = run('nmcli', '-t', '-f', 'UUID,NAME', 'connection', 'show').splitlines()
        matches = [row.partition(':')[0] for row in rows if row.partition(':')[2] == name]
        if len(matches) > 1:
            raise ConnectionError(f'Multiple profiles named {name}; resolve duplicates manually.')
        return matches[0] if matches else None

    profile = lookup()
    if profile is None:
        log('Creating a modem-specific profile' +
            (' with cellular default route and DNS.' if internet else ' for UE-only traffic.'))
        run('nmcli', 'connection', 'add', 'type', 'gsm', 'ifname', '*',
            'con-name', name,
            'connection.autoconnect', 'no', 'gsm.device-id', identity,
            'gsm.apn', args.apn, 'gsm.auto-config', 'no', 'gsm.network-id', args.plmn,
            'ipv4.method', 'auto', 'ipv4.never-default', preserve_routes,
            'ipv4.ignore-auto-dns', preserve_routes, 'ipv6.method', 'disabled',
            *internet_settings)
        profile = lookup()
        if profile is None:
            raise ConnectionError('Created data profile could not be located.')
    # Refuse to use a same-name profile that has been changed outside this helper.
    properties = 'gsm.device-id,gsm.apn,gsm.network-id,ipv4.never-default,ipv4.ignore-auto-dns,ipv6.method'
    expected = [identity, args.apn, args.plmn, preserve_routes, preserve_routes, 'disabled']
    if internet:
        properties += ',ipv4.route-metric,ipv4.dns-priority'
        expected += ['50', '-50']
    values = run('nmcli', '-g', properties, 'connection', 'show', 'uuid', profile).splitlines()
    if values != expected:
        raise ConnectionError(f'Profile {profile} has unexpected settings; leaving it untouched.')
    return profile


def activate_data(path, data, args):
    profile = ensure_data_profile(data, args)
    active = run('nmcli', '-g', 'UUID', 'connection', 'show', '--active').splitlines()
    if profile not in active:
        if field(data, 'modem.generic.state') == 'connected':
            raise ConnectionError('A different bearer is already connected. Leaving it untouched; '
                                  'disconnect it manually or use --register-only.')
        log(f'Activating IPv4 APN {args.apn} once (up to 120s).')
        try:
            run('nmcli', '--wait', '120', 'connection', 'up', 'uuid', profile, timeout=135)
        except ConnectionError as error:
            if 'No suitable device' in str(error):
                raise ConnectionError(
                    f'{error}\nCheck nmcli radio all and nmcli device status: '
                    'NetworkManager must see an available, managed GSM modem. '
                    'A Wi-Fi device named in this error does not imply Wi-Fi is required.') from error
            raise
    if profile not in run('nmcli', '-g', 'UUID', 'connection', 'show', '--active').splitlines():
        raise ConnectionError('NetworkManager did not report the profile active.')
    log('DATA CONNECTION ACTIVE. Assigned host settings:')
    print(run('nmcli', '-f', 'GENERAL,IP4', 'connection', 'show', 'uuid', profile), flush=True)
    if getattr(args, 'internet', False):
        log('Cellular IPv4 default route and bearer DNS enabled. '
            'Verify with ip -4 route get 1.1.1.1 and curl -4 --max-time 15 https://example.com.')
    else:
        log('Existing default route and DNS are preserved. Use --internet for cellular internet.')
    log('Profile activation does not verify end-to-end packet delivery.')


def connect(path, data, args):
    ready_deadline = time.monotonic() + 45
    while field(data, 'modem.generic.state') in ('unknown', 'initializing'):
        if time.monotonic() >= ready_deadline:
            raise ConnectionError('Modem initialization did not finish within 45 seconds.')
        time.sleep(3)
        data = mm_json('-m', path)
    check_sim(data)
    state = field(data, 'modem.generic.state')
    modes = field(data, 'modem.generic.current-modes')
    bands = field(data, 'modem.generic.current-bands')
    if state == 'connected' and not registered(data, args.plmn):
        raise ConnectionError('Modem connected on another network; leaving it untouched.')
    mode_ok = modes == 'allowed: 5g; preferred: none'
    band_ok = bands == ['ngran-78'] or bands == 'ngran-78'
    if not mode_ok or not band_ok:
        if state == 'connected':
            raise ConnectionError('Connected modem has different radio settings; not interrupting it.')
        log('Selecting 5G-only and n78. SIM slot and stored APNs are unchanged.')
        if state != 'disabled':
            run('mmcli', '-m', path, '--disable')
        if not mode_ok:
            run('mmcli', '-m', path, '--set-allowed-modes=5g')
        if not band_ok:
            run('mmcli', '-m', path, '--set-current-bands=ngran-78')
        state = 'disabled'
    if state == 'disabled':
        run('mmcli', '-m', path, '--enable', '--timeout=60', timeout=70)
    data = mm_json('-m', path)
    if not registered(data, args.plmn):
        log(f'Requesting registration on {args.plmn} (up to 120s).')
        error_text = ''
        try:
            run('mmcli', '-m', path, f'--3gpp-register-in-operator={args.plmn}',
                '--timeout=120', timeout=130)
        except ConnectionError as error:
            error_text = str(error)
        data = mm_json('-m', path)
        if not registered(data, args.plmn):
            raise ConnectionError(f'Registration not confirmed: '
                                  f'{field(data, "modem.3gpp.registration-state")}. {error_text}')
    log(f'MODEM REPORTS REGISTERED on {args.plmn}. Core logs are the independent confirmation.')
    if not args.register_only:
        activate_data(path, data, args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true', help='stay running for USB reconnects')
    parser.add_argument('--register-only', action='store_true', help='do not create a data connection')
    parser.add_argument('--internet', action='store_true',
                        help='install cellular IPv4 default route (metric 50) and use bearer DNS')
    parser.add_argument('--modem', help='stable device ID (recommended) or current modem index/path')
    parser.add_argument('--sim-slot', type=int, choices=(1, 2),
                        help='explicitly select SIM slot 1 or 2 before registration; default: keep current')
    parser.add_argument('--plmn', default='00101')
    parser.add_argument('--apn', default='oai')
    parser.add_argument('--wait', type=int, default=180, help='initial discovery timeout, seconds')
    args = parser.parse_args()
    if args.internet and args.register_only:
        parser.error('--internet cannot be combined with --register-only')
    if not re.fullmatch(r'[0-9]{5,6}', args.plmn):
        parser.error('--plmn must contain 5 or 6 digits')
    if not re.fullmatch(r'[a-zA-Z0-9.-]+', args.apn) or args.wait < 1:
        parser.error('invalid APN or discovery timeout')
    if os.geteuid() != 0:
        parser.error('run with sudo')
    for command in ('mmcli',) + (() if args.register_only else ('nmcli',)):
        if not shutil.which(command):
            parser.error(f'{command} is required')
    # The root-owned runtime directory prevents lock-file symlink substitution.
    os.makedirs('/run/oai-connect-ue', mode=0o700, exist_ok=True)
    with open('/run/oai-connect-ue/lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('another connect-ue instance is running')
        slot_message = (f'Will select SIM slot {args.sim_slot} if needed.' if args.sim_slot
                        else 'Keeping the current SIM slot.')
        log(f'Waiting for EM8695. {slot_message} No explicit modem resets will be performed.')
        seen = set()
        deadline = time.monotonic() + args.wait
        while True:
            paths = set(modem_paths())
            seen.intersection_update(paths)
            match = discover(args.modem)
            if match and match[0] not in seen:
                path, data = match
                seen.add(path)
                log(f'Detected {path}')
                identity = field(data, 'modem.generic.device-identifier')
                if args.modem and identity and identity != '--':
                    args.modem = identity  # Preserve an explicit selection across modem-ID changes.
                try:
                    path, data = select_sim_slot(path, data, args.sim_slot)
                    seen.add(path)
                    connect(path, data, args)
                except ConnectionError as error:
                    log(f'FAILED: {error}')
                    log(f'Diagnostics: mmcli -m {path}; '
                        'sudo journalctl -u ModemManager --since "5 minutes ago" --no-pager')
                    if not args.watch:
                        return 1
                else:
                    if not args.watch:
                        return 0
                log('Waiting for USB removal/reconnection. No automatic retry storm; Ctrl-C to exit.')
            if not args.watch and time.monotonic() >= deadline:
                raise ConnectionError('No matching modem appeared before the discovery timeout.')
            time.sleep(3)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ConnectionError as error:
        log(f'FAILED: {error}')
        sys.exit(1)
    except KeyboardInterrupt:
        log('Stopped watcher; any established connection is left up.')
        sys.exit(130)
