"""Offline tests: no modem, NetworkManager, or host network is modified."""
import argparse
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('connect_ue', Path(__file__).with_name('connect-ue.py'))
ue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ue)

DATA = {'modem': {
    'generic': {'model': 'Sierra Wireless EM8695', 'device-identifier': 'test-id',
                'primary-sim-slot': '1', 'sim': '/org/freedesktop/ModemManager1/SIM/10',
                'unlock-required': 'sim-pin2', 'state': 'enabled',
                'current-modes': 'allowed: 5g; preferred: none',
                'current-bands': ['ngran-78']},
    '3gpp': {'registration-state': 'idle', 'operator-code': '--'}}}
PATH = '/org/freedesktop/ModemManager1/Modem/10'


class ConnectTests(unittest.TestCase):
    def setUp(self):
        self.data = copy.deepcopy(DATA)
        self.args = argparse.Namespace(plmn='00101', apn='oai', register_only=True)
        self.quiet = patch.object(ue, 'log')
        self.quiet.start()
        self.addCleanup(self.quiet.stop)

    def registered(self):
        data = copy.deepcopy(self.data)
        data['modem']['generic']['state'] = 'registered'
        data['modem']['3gpp'] = {'registration-state': 'home', 'operator-code': '00101'}
        return data

    def test_dynamic_modem_discovery(self):
        with patch.object(ue, 'modem_paths', return_value=[PATH]), \
                patch.object(ue, 'mm_json', return_value=self.data):
            self.assertEqual(ue.discover(None)[0], PATH)
            self.assertEqual(ue.discover('test-id')[0], PATH)
            self.assertIsNone(ue.discover('wrong-id'))

    def test_ambiguous_modems_are_rejected(self):
        with patch.object(ue, 'modem_paths', return_value=[PATH, PATH + '1']), \
                patch.object(ue, 'mm_json', return_value=self.data):
            with self.assertRaisesRegex(ue.ConnectionError, 'Multiple'):
                ue.discover(None)

    def test_pin2_allowed_but_pin1_blocks(self):
        ue.check_sim(self.data)
        self.data['modem']['generic']['unlock-required'] = 'sim-pin'
        with self.assertRaisesRegex(ue.ConnectionError, 'Unlock'):
            ue.check_sim(self.data)

    def test_missing_sim_blocks_before_mutation(self):
        self.data['modem']['generic']['sim'] = '--'
        with patch.object(ue, 'run') as run:
            with self.assertRaisesRegex(ue.ConnectionError, 'No active SIM'):
                ue.connect(PATH, self.data, self.args)
            run.assert_not_called()

    def test_registration_without_reset_or_reconfiguration(self):
        with patch.object(ue, 'mm_json', side_effect=[self.data, self.registered()]), \
                patch.object(ue, 'run') as run:
            ue.connect(PATH, self.data, self.args)
            run.assert_called_once_with('mmcli', '-m', PATH,
                                        '--3gpp-register-in-operator=00101',
                                        '--timeout=120', timeout=130)

    def test_registration_failure_does_not_activate_data(self):
        self.args.register_only = False
        with patch.object(ue, 'mm_json', return_value=self.data), \
                patch.object(ue, 'run', side_effect=ue.ConnectionError('NetworkTimeout')), \
                patch.object(ue, 'activate_data') as activate:
            with self.assertRaisesRegex(ue.ConnectionError, 'NetworkTimeout'):
                ue.connect(PATH, self.data, self.args)
            activate.assert_not_called()

    def test_already_registered_skips_request(self):
        data = self.registered()
        with patch.object(ue, 'mm_json', return_value=data), patch.object(ue, 'run') as run:
            ue.connect(PATH, data, self.args)
            run.assert_not_called()

    def test_wrong_operator_not_success(self):
        data = self.registered()
        data['modem']['3gpp']['operator-code'] = '23415'
        self.assertFalse(ue.registered(data, '00101'))

    def test_slot_selection_is_opt_in_and_idempotent(self):
        with patch.object(ue, 'run') as run:
            self.assertEqual(ue.select_sim_slot(PATH, self.data, None), (PATH, self.data))
            self.assertEqual(ue.select_sim_slot(PATH, self.data, 1), (PATH, self.data))
            run.assert_not_called()

    def test_slot_switch_rediscovers_same_device_with_new_id(self):
        switched = copy.deepcopy(self.data)
        self.data['modem']['generic']['primary-sim-slot'] = '2'
        self.data['modem']['generic']['sim'] = '--'
        new_path = '/org/freedesktop/ModemManager1/Modem/12'
        with patch.object(ue, 'run') as run, patch.object(ue.time, 'sleep'), \
                patch.object(ue, 'discover', side_effect=[ue.ConnectionError('gone'), None,
                                                        (new_path, switched)]) as discover:
            self.assertEqual(ue.select_sim_slot(PATH, self.data, 1), (new_path, switched))
            run.assert_called_once_with('mmcli', '-m', PATH, '--set-primary-sim-slot=1',
                                        '--timeout=60', timeout=70)
            discover.assert_called_with('test-id')

    def test_slot_switch_error_requires_actual_confirmation(self):
        switched = copy.deepcopy(self.data)
        self.data['modem']['generic']['primary-sim-slot'] = '2'
        with patch.object(ue, 'run', side_effect=ue.ConnectionError('object disappeared')), \
                patch.object(ue.time, 'sleep'), \
                patch.object(ue, 'discover', return_value=(PATH, switched)):
            self.assertEqual(ue.select_sim_slot(PATH, self.data, 1), (PATH, switched))

    def test_slot_switch_timeout_fails(self):
        self.data['modem']['generic']['primary-sim-slot'] = '2'
        with patch.object(ue, 'run'), patch.object(ue.time, 'sleep'), \
                patch.object(ue.time, 'monotonic', side_effect=[0, 1, 91]), \
                patch.object(ue, 'discover', return_value=(PATH, self.data)):
            with self.assertRaisesRegex(ue.ConnectionError, 'not confirmed'):
                ue.select_sim_slot(PATH, self.data, 1)

    def test_slot_switch_preserves_connected_bearer(self):
        self.data['modem']['generic']['state'] = 'connected'
        with patch.object(ue, 'run') as run:
            with self.assertRaisesRegex(ue.ConnectionError, 'Disconnect'):
                ue.select_sim_slot(PATH, self.data, 2)
            run.assert_not_called()

    def test_data_profile_preserves_default_route(self):
        name = 'oai-ue-' + str(ue.uuid.uuid5(ue.uuid.NAMESPACE_URL, 'urn:oai-connect-ue:test-id:00101:oai'))
        profile = '80c9c07b-d572-4f1c-9072-b1e0d53928ab'
        settings = 'test-id\noai\n00101\nyes\nyes\ndisabled'
        with patch.object(ue, 'run', side_effect=['', 'Created', f'{profile}:{name}', settings,
                                                '', '', profile, 'IP4 settings']) as run:
            ue.activate_data(PATH, self.registered(), self.args)
            creation = run.call_args_list[1].args
            self.assertNotIn('connection.uuid', creation)
            self.assertIn('gsm.device-id', creation)
            self.assertEqual(creation[creation.index('ipv4.never-default') + 1], 'yes')
            self.assertEqual(creation[creation.index('connection.autoconnect') + 1], 'no')
            self.assertEqual(creation[creation.index('ipv4.ignore-auto-dns') + 1], 'yes')

    def test_existing_profile_reused_without_creation(self):
        name = 'oai-ue-' + str(ue.uuid.uuid5(ue.uuid.NAMESPACE_URL, 'urn:oai-connect-ue:test-id:00101:oai'))
        with patch.object(ue, 'run', side_effect=[f'generated-uuid:{name}',
                                                'test-id\noai\n00101\nyes\nyes\ndisabled']) as run:
            self.assertEqual(ue.ensure_data_profile(self.data, self.args), 'generated-uuid')
            self.assertTrue(all('add' not in call.args for call in run.call_args_list))

    def test_internet_uses_separate_profile_with_default_route_and_dns(self):
        self.args.internet = True
        base = 'oai-ue-' + str(ue.uuid.uuid5(ue.uuid.NAMESPACE_URL,
                                          'urn:oai-connect-ue:test-id:00101:oai'))
        existing = f'old-uuid:{base}'
        settings = 'test-id\noai\n00101\nno\nno\ndisabled\n50\n-50'
        with patch.object(ue, 'run', side_effect=[existing, 'Created',
                                                existing + f'\nnew-uuid:{base}-internet',
                                                settings]) as run:
            self.assertEqual(ue.ensure_data_profile(self.data, self.args), 'new-uuid')
            creation = run.call_args_list[1].args
            self.assertEqual(creation[creation.index('ipv4.never-default') + 1], 'no')
            self.assertEqual(creation[creation.index('ipv4.ignore-auto-dns') + 1], 'no')
            self.assertEqual(creation[creation.index('ipv4.method') + 1], 'auto')
            self.assertTrue(all('modify' not in call.args for call in run.call_args_list))

    def test_internet_does_not_interrupt_existing_bearer(self):
        self.args.internet = True
        data = self.registered()
        data['modem']['generic']['state'] = 'connected'
        with patch.object(ue, 'ensure_data_profile', return_value='internet-uuid'), \
                patch.object(ue, 'run', return_value='other-uuid') as run:
            with self.assertRaisesRegex(ue.ConnectionError, 'different bearer'):
                ue.activate_data(PATH, data, self.args)
            self.assertTrue(all('up' not in call.args for call in run.call_args_list))

    def test_unavailable_device_reports_cellular_diagnostics(self):
        with patch.object(ue, 'ensure_data_profile', return_value='profile'), \
                patch.object(ue, 'run', side_effect=['', ue.ConnectionError('No suitable device')]):
            with self.assertRaisesRegex(ue.ConnectionError, 'managed GSM modem'):
                ue.activate_data(PATH, self.registered(), self.args)

    def test_changed_profile_rejected(self):
        name = 'oai-ue-' + str(ue.uuid.uuid5(ue.uuid.NAMESPACE_URL, 'urn:oai-connect-ue:test-id:00101:oai'))
        with patch.object(ue, 'run', side_effect=[f'generated-uuid:{name}', 'other-device']):
            with self.assertRaisesRegex(ue.ConnectionError, 'unexpected settings'):
                ue.ensure_data_profile(self.data, self.args)


if __name__ == '__main__':
    unittest.main()
