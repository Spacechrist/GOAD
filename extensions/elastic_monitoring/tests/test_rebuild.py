"""Executable transfer tests plus deployment task contract checks.

The remote extraction program runs locally against an isolated directory; no
SSH, Windows, VMware, Ansible actions or lab accounts are needed.
"""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('source_sync_under_test', ROOT / 'goad/source_sync.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class SourceSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / 'checkout with spaces'
        self.project.mkdir()
        self.instance = self.project / 'workspace/test-goad-vmware'
        self.instance.mkdir(parents=True)
        self.destination = self.base / 'remote'
        for name, data in {
            'ansible/build.yml': b'---\r\n- hosts: all\r\n',
            'ansible/roles/demo/tasks/main.yml': b'- debug: msg=updated\n',
            'scripts/setup_local_jumpbox.sh': b'#!/bin/bash\r\nexit 0\r\n',
            'requirements.yml': b'pywinrm\n',
            'workspace/test-goad-vmware/inventory': b'[all]\nlab\n',
            'extensions/demo/.local/secret': b'never copy',
            'ad/demo/ssh_keys/key.pem': b'never copy',
        }.items():
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        subprocess.run(['git', 'init', '-q'], cwd=self.project, check=True)
        subprocess.run(['git', 'add', '.'], cwd=self.project, check=True)
        subprocess.run(['git', 'update-index', '--chmod=+x', 'scripts/setup_local_jumpbox.sh'],
                       cwd=self.project, check=True)

    def apply_remote(self, payload):
        code = sync.REMOTE_APPLY.replace("root = pathlib.Path.home() / 'GOAD'",
                                        'root = pathlib.Path(' + repr(str(self.destination)) + ')')
        return subprocess.run([sys.executable, '-c', code], input=payload, capture_output=True)

    def test_bundle_roundtrip_updates_actual_content_and_modes(self):
        payload, receipt = sync.build_bundle(self.project, self.instance)
        result = self.apply_remote(payload)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout.decode().strip(), receipt)
        self.assertEqual((self.destination / 'ansible/build.yml').read_bytes(), b'---\n- hosts: all\n')
        self.assertTrue(os.access(self.destination / 'scripts/setup_local_jumpbox.sh', os.X_OK))
        self.assertFalse((self.destination / 'ad/demo/ssh_keys/key.pem').exists())
        self.assertFalse((self.destination / 'extensions/demo/.local/secret').exists())

    def test_repeat_updates_roles_and_removes_only_previously_managed_files(self):
        self.assertEqual(self.apply_remote(sync.build_bundle(self.project, self.instance)[0]).returncode, 0)
        unmanaged = self.destination / 'operator-note'
        unmanaged.write_text('keep')
        role = self.project / 'ansible/roles/demo/tasks/main.yml'
        role.unlink()
        subprocess.run(['git', 'add', '-u'], cwd=self.project, check=True)
        (self.project / 'ansible/build.yml').write_text('changed\n')
        result = self.apply_remote(sync.build_bundle(self.project, self.instance)[0])
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertFalse((self.destination / 'ansible/roles/demo/tasks/main.yml').exists())
        self.assertEqual(unmanaged.read_text(), 'keep')
        self.assertEqual((self.destination / 'ansible/build.yml').read_text(), 'changed\n')

    def test_tampered_archive_rejected_before_overwrite(self):
        payload, _ = sync.build_bundle(self.project, self.instance)
        self.assertEqual(self.apply_remote(payload).returncode, 0)
        output = io.BytesIO()
        with tarfile.open(fileobj=io.BytesIO(payload)) as source, tarfile.open(fileobj=output, mode='w:gz') as dest:
            for entry in source:
                data = source.extractfile(entry).read()
                if entry.name == 'ansible/build.yml':
                    data = b'tampered'
                    entry.size = len(data)
                dest.addfile(entry, io.BytesIO(data))
        result = self.apply_remote(output.getvalue())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'checksum mismatch', result.stderr)
        self.assertEqual((self.destination / 'ansible/build.yml').read_bytes(), b'---\n- hosts: all\n')

    def test_remote_symlink_rejected(self):
        self.destination.mkdir()
        outside = self.base / 'outside'
        outside.mkdir()
        (self.destination / 'ansible').symlink_to(outside, target_is_directory=True)
        result = self.apply_remote(sync.build_bundle(self.project, self.instance)[0])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    def test_local_symlink_rejected(self):
        role = self.project / 'ansible/roles/demo/tasks/main.yml'
        role.unlink()
        role.symlink_to(self.project / 'requirements.yml')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            sync.build_bundle(self.project, self.instance)

    def test_other_instance_rejected(self):
        with self.assertRaisesRegex(ValueError, 'checkout workspace'):
            sync.build_bundle(self.project, self.base / 'outside')

    def test_path_filter(self):
        for name in ('../escape', '/escape', 'ansible/../../escape', 'ansible\\escape',
                     'workspace/other/inventory', 'extensions/demo/vault.yml'):
            self.assertFalse(sync.allowed_path(name, self.instance.name), name)

    def test_missing_required_source_rejected(self):
        (self.project / 'ansible/build.yml').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing required source'):
            sync.build_bundle(self.project, self.instance)

    def test_sync_rejects_wrong_remote_receipt(self):
        key = self.base / 'key'
        key.write_text('test key')
        with patch.object(sync, 'build_bundle', return_value=(b'archive', 'expected')):
            with patch.object(sync.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'wrong')):
                with self.assertRaisesRegex(RuntimeError, 'checksum'):
                    sync.sync_checkout(self.project, self.instance, key, 'vagrant', '192.168.56.3')

    def test_sync_retries_transport_failure_then_succeeds(self):
        key = self.base / 'key'
        key.write_text('test key')
        with patch.object(sync, 'build_bundle', return_value=(b'archive', 'expected')):
            unavailable = subprocess.CompletedProcess([], 255, b'', b'connection timed out')
            available = subprocess.CompletedProcess([], 0, b'expected', b'')
            with patch.object(sync.subprocess, 'run', side_effect=[unavailable, available]) as run:
                self.assertEqual(sync.sync_checkout(self.project, self.instance, key, 'vagrant',
                                                    '192.168.56.3', attempts=2, delay=0), 'expected')
                self.assertEqual(run.call_count, 2)

    def test_sync_does_not_retry_remote_validation_failure(self):
        key = self.base / 'key'
        key.write_text('test key')
        rejected = subprocess.CompletedProcess([], 1, b'', b'checksum mismatch')
        with patch.object(sync, 'build_bundle', return_value=(b'archive', 'expected')):
            with patch.object(sync.subprocess, 'run', return_value=rejected) as run:
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    sync.sync_checkout(self.project, self.instance, key, 'vagrant',
                                       '192.168.56.3', attempts=3, delay=0)
                self.assertEqual(run.call_count, 1)

    def test_sql_2019_uses_stable_microsoft_redirect(self):
        defaults = yaml.safe_load((ROOT / 'ansible/roles/mssql/defaults/main.yml').read_text())
        self.assertEqual(defaults['download_url_2019'],
                         'https://go.microsoft.com/fwlink/?linkid=866658')
        self.assertEqual(defaults['sql_launcher_minimum_2019'], '15.2607.0.1')
        self.assertEqual(
            defaults['sql_launcher_sha256_2019'],
            '37cc32717aba3b6633071ec176c6728e05570cfa5cf4c67f54421a0a2b4493c2',
        )
        self.assertNotIn('7f8a9c43-8c8a-4f7c-9f92-83c18d96b681',
                         defaults['download_url_2019'])

    def test_ssh_uses_argument_vector_and_instance_host_identity(self):
        key = self.base / 'key with spaces'
        key.write_text('not a real key')
        args = sync.ssh_arguments(key, 'vagrant', '192.168.56.3')
        self.assertIn(str(key), args)
        self.assertIn('StrictHostKeyChecking=accept-new', args)
        self.assertIn('UserKnownHostsFile=' + str(key.parent / 'goad_known_hosts'), args)
        self.assertNotIn('StrictHostKeyChecking=no', args)


def walk_tasks(tasks):
    for task in tasks:
        yield task
        for key in ('block', 'rescue', 'always'):
            yield from walk_tasks(task.get(key, []))


class RebuildContractTests(unittest.TestCase):
    def test_sql_installer_runs_once_with_bounded_time_and_cleanup(self):
        tasks = list(walk_tasks(yaml.safe_load((ROOT / 'ansible/roles/mssql/tasks/main.yml').read_text())))
        install = next(t for t in tasks if t.get('name') == 'Install the database once with a time limit')
        self.assertNotIn('retries', install)
        self.assertIn('async', install)
        self.assertTrue(install['no_log'])
        self.assertTrue(any('always' in t for t in tasks))

    def test_sql_launcher_preserves_connection_profile(self):
        tasks = list(walk_tasks(yaml.safe_load((ROOT / 'ansible/roles/mssql/tasks/main.yml').read_text())))
        install = next(t for t in tasks if t.get('name') == 'Install the database once with a time limit')
        self.assertEqual(install['args']['chdir'], 'C:\\setup')
        self.assertEqual(
            install['vars']['ansible_become_flags'],
            'logon_type=new_credentials logon_flags=netcredentials_only',
        )
        self.assertNotIn('logon_type=interactive', install['vars']['ansible_become_flags'])

    def test_ssms_has_no_legacy_directory_only_gate_or_evergreen_url(self):
        source = (ROOT / 'ansible/roles/mssql_ssms/tasks/main.yml').read_text()
        self.assertNotIn('Management Studio 18', source)
        self.assertNotIn('ssmsfullsetup', source)
        self.assertIn('discover.yml', source)
        self.assertIn('ssms_install_timeout', source)
        self.assertFalse((ROOT / 'ansible/roles/mssql_ssms/tasks/legacy.yml').exists())

    def test_vmware_reboots_before_ip_verification(self):
        text = (ROOT / 'template/provider/vmware/Vagrantfile').read_text()
        self.assertLess(text.index('fix_ip.ps1'), text.index('provision :reload'))
        self.assertLess(text.index('provision :reload'), text.index('verify_ip.ps1'))
        self.assertIn('box[:forwarded_port].each', text)
        self.assertIn('v.enable_vmrun_ip_lookup = false', text)
        forwarding = next(line for line in text.splitlines() if 'guest: forwarded_port[:guest]' in line)
        self.assertIn('auto_correct: true', forwarding)
        self.assertIn('host_ip: "127.0.0.1"', forwarding)
        for script in ('fix_ip.ps1', 'verify_ip.ps1'):
            line = next(line for line in text.splitlines() if script in line)
            self.assertIn('privileged: false', line)
            self.assertNotIn('privileged: true', line)

    def test_setup_never_clones_upstream(self):
        text = (ROOT / 'scripts/setup_local_jumpbox.sh').read_text()
        self.assertNotIn('git clone', text)
        self.assertNotIn('git pull', text)
        self.assertIn('set -euo pipefail', text)


if __name__ == '__main__':
    unittest.main()
