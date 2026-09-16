"""Static checks only; these do not replace Ansible or Windows execution."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    output = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in output:
            raise ValueError(f'Duplicate YAML key: {key}')
        output[key] = loader.construct_object(value_node, deep=deep)
    return output


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


class RepositoryTests(unittest.TestCase):
    def test_all_yaml_parses_without_duplicate_keys(self):
        for path in ROOT.rglob('*.yml'):
            if '.local' in path.parts:
                continue
            with self.subTest(path=str(path.relative_to(ROOT))):
                yaml.load(path.read_text(), Loader=UniqueKeyLoader)

    def test_defaults_do_not_authorize_changes(self):
        config = yaml.safe_load((ROOT / 'config.example.yml').read_text())
        for name in ('monitoring_apply', 'monitoring_allow_dc_changes',
                     'monitoring_allow_local_logging', 'monitoring_allow_existing_collectors'):
            self.assertIs(config[name], False)
        self.assertEqual(config['monitoring_sysmon_approved_builds'], [])

    def test_deployment_runs_preflight_first(self):
        plays = yaml.safe_load((ROOT / 'ansible/windows.yml').read_text())
        self.assertEqual(plays[0]['ansible.builtin.import_playbook'], 'preflight.yml')
        self.assertEqual(plays[1]['serial'], 1)
        self.assertIs(plays[1]['any_errors_fatal'], True)

    def test_no_core_or_provider_install_hook_yet(self):
        # Don't advertise a fully operational native extension before Fleet,
        # rollback, and provider integration milestones have been delivered.
        self.assertFalse((ROOT / 'extension.json').exists())

    def test_ps1_files_have_no_ansible_interpolation(self):
        for path in ROOT.rglob('*.ps1'):
            with self.subTest(path=path.name):
                self.assertNotIn('{{', path.read_text())

    def test_secret_and_artifact_paths_ignored(self):
        ignored = (ROOT / '.gitignore').read_text().splitlines()
        for name in ('.local/', 'vault.yml', 'config.local.yml'):
            self.assertIn(name, ignored)
