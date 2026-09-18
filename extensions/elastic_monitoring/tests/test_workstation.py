import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from workstation import (create_instance, creation_lock, inspect_instance,
                         make_plan, read_instances, repo_path, validate_prefix)


class WorkstationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='goad test ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for file in ('goad.py', 'template/provider/vmware/Vagrantfile',
                     'ad/GOAD/providers/vmware/Vagrantfile', 'ad/GOAD/data/inventory',
                     'extensions/elastic_monitoring/inventory.example.ini', 'globalsettings.ini'):
            path = self.root / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# fixture, not a real lab\n')
        (self.root / 'workspace').mkdir()

    def state(self, instance='abc123-goad-vmware', **overrides):
        result = dict(id=instance, provider='vmware', lab='GOAD', ip_range='192.168.56',
                      provisioner='local', status='installed', extensions=[])
        result.update(overrides)
        folder = self.root / 'workspace' / instance
        folder.mkdir(exist_ok=True)
        (folder / 'instance.json').write_text(json.dumps(result))
        (folder / 'inventory').write_text('# test inventory\n')
        return result

    def test_repo_validation(self):
        self.assertEqual(repo_path(self.root), self.root)
        (self.root / 'goad.py').unlink()
        with self.assertRaises(ValueError):
            repo_path(self.root)

    def test_private_prefixes(self):
        for prefix in ('10.0.2', '172.16.1', '172.31.255', '192.168.56'):
            self.assertEqual(validate_prefix(prefix), prefix)

    def test_invalid_prefixes(self):
        for prefix in ('8.8.8', '127.0.0', '169.254.0', '172.32.0', '192.168.56.1',
                       '192.168.56.0/24', '192.168.999', '192.168.056', '192.168.56;id', None):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                validate_prefix(prefix)

    def test_plan_is_read_only_and_uses_native_provider(self):
        before = sorted(self.root.rglob('*'))
        plan = make_plan(self.root, 'GOAD', '192.168.56', 'local')
        self.assertEqual(sorted(self.root.rglob('*')), before)
        self.assertEqual(plan['argv'][2:], ['-t', 'install', '-p', 'vmware', '-l', 'GOAD',
                                           '-ip', '192.168.56', '-m', 'local'])
        self.assertIs(plan['monitoring_will_run'], False)

    def test_native_windows_rejects_local_ansible(self):
        with self.assertRaises(ValueError):
            make_plan(self.root, 'GOAD', '192.168.56', 'local', platform='nt')
        self.assertEqual(make_plan(self.root, 'GOAD', '192.168.56', 'vm', platform='nt')['provisioner'], 'vm')

    def test_existing_subnet_blocks_another_create(self):
        self.state()
        with self.assertRaisesRegex(ValueError, 'Subnet already recorded'):
            make_plan(self.root, 'GOAD', '192.168.56', 'local')

    def test_inspect_returns_paths_not_inventory_secrets(self):
        state = self.state()
        (self.root / 'globalsettings.ini').write_text('credential=DO_NOT_REPORT\n')
        report = inspect_instance(self.root, state['id'])
        self.assertNotIn('DO_NOT_REPORT', json.dumps(report))
        self.assertEqual(report['live_readiness'], 'not_evaluated')
        self.assertEqual(report['missing_inventory_paths'], [])
        self.assertEqual(report['inventory_paths'][-2], str(self.root / 'globalsettings.ini'))

    def test_missing_extension_inventory_reported(self):
        state = self.state(extensions=['elk'])
        report = inspect_instance(self.root, state['id'])
        self.assertEqual(report['missing_inventory_paths'],
                         [str(self.root / 'workspace' / state['id'] / 'elk_inventory')])

    def test_disabled_vagrant_uses_separate_inventory(self):
        state = self.state()
        path = self.root / 'workspace' / state['id'] / 'inventory_disable_vagrant'
        path.write_text('# domain credential inventory fixture\n')
        report = inspect_instance(self.root, state['id'], 'disabled-vagrant')
        self.assertEqual(report['inventory_paths'][0], str(path))
        self.assertNotIn(str(self.root / 'ad/GOAD/data/inventory'), report['inventory_paths'])

    def test_wrong_provider_refused(self):
        state = self.state(provider='vmware_esxi')
        with self.assertRaisesRegex(ValueError, 'not a VMware Workstation'):
            inspect_instance(self.root, state['id'])

    def test_instance_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            inspect_instance(self.root, '../outside')

    def test_malformed_state_is_not_skipped(self):
        self.state()
        (self.root / 'workspace/abc123-goad-vmware/instance.json').write_text('not JSON')
        with self.assertRaisesRegex(ValueError, 'Unreadable'):
            read_instances(self.root)

    def test_success_needs_new_installed_instance_and_inventories(self):
        def runner(command, cwd):
            self.assertEqual(cwd, self.root)
            self.state()
            return 0
        report = create_instance(self.root, 'GOAD', '192.168.56', 'local', runner=runner)
        self.assertEqual(report['native_status'], 'installed')
        self.assertFalse((self.root / 'extensions/elastic_monitoring/.local/workstation-create.lock').exists())

    def test_zero_exit_without_new_state_is_failure(self):
        with self.assertRaisesRegex(ValueError, 'exactly one new instance'):
            create_instance(self.root, 'GOAD', '192.168.56', 'local', runner=lambda *_: 0)

    def test_zero_exit_with_incomplete_provisioning_is_failure(self):
        def runner(*_):
            self.state(status='ready for provisioning')
            return 0
        with self.assertRaisesRegex(ValueError, 'does not record'):
            create_instance(self.root, 'GOAD', '192.168.56', 'local', runner=runner)

    def test_nonzero_exit_preserves_partial_state(self):
        def runner(*_):
            self.state(status='not provided')
            return 7
        with self.assertRaisesRegex(ValueError, 'code 7'):
            create_instance(self.root, 'GOAD', '192.168.56', 'local', runner=runner)
        self.assertTrue((self.root / 'workspace/abc123-goad-vmware/instance.json').exists())

    def test_concurrent_creation_refused(self):
        with creation_lock(self.root):
            with self.assertRaisesRegex(ValueError, 'lock exists'):
                with creation_lock(self.root):
                    self.fail('Second lock must not be acquired')

    def test_inspect_missing_instance(self):
        with self.assertRaisesRegex(ValueError, 'not found'):
            inspect_instance(self.root, 'missing')

    def test_multiple_new_instances_not_guessed(self):
        def runner(*_):
            self.state()
            self.state(instance='def456-goad-vmware', ip_range='192.168.57')
            return 0
        with self.assertRaisesRegex(ValueError, 'exactly one new instance'):
            create_instance(self.root, 'GOAD', '192.168.56', 'local', runner=runner)

    def test_cli_plan_does_not_execute_goad(self):
        # If executed, the fake native entry point exits with 99. The plan command
        # must remain independent of GOAD imports and dependencies.
        (self.root / 'goad.py').write_text('raise SystemExit(99)\n')
        script = Path(__file__).resolve().parents[1] / 'scripts/workstation.py'
        completed = subprocess.run([sys.executable, str(script), '--repo', str(self.root),
                                    'plan', '--method', 'vm', '--ip-prefix', '192.168.56'],
                                   capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['provider'], 'vmware')

    def test_cli_create_propagates_failure_from_fake_native_entrypoint(self):
        (self.root / 'goad.py').write_text('raise SystemExit(17)\n')
        script = Path(__file__).resolve().parents[1] / 'scripts/workstation.py'
        completed = subprocess.run([sys.executable, str(script), '--repo', str(self.root),
                                    'create', '--method', 'vm', '--ip-prefix', '192.168.56'],
                                   capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 2)
        self.assertIn('code 17', completed.stderr)
        self.assertEqual(completed.stdout, '')
