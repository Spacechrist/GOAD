import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from config import validate


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            'elastic_version': '9.5.3', 'fleet_url': 'https://fleet.example.test:8220',
            'elasticsearch_url': 'https://elastic.example.test:9200',
            'kibana_url': 'https://kibana.example.test:5601', 'targets': ['srv02'],
            'min_free_gb': 8, 'event_log_bytes': 134217728, 'security_log_bytes': 268435456,
        }

    def test_valid_configuration(self):
        self.assertEqual(validate(self.config), self.config)

    def test_https_ipv6_supported(self):
        self.config['fleet_url'] = 'https://[::1]:8220'
        validate(self.config)

    def test_invalid_origins(self):
        for value in ('http://fleet:8220', 'https://user:secret@fleet', 'https://fleet/path',
                      'https://fleet/?key=secret', 'https://fleet/#frag', 'https://fleet:0',
                      'https://fleet:65536', 'https://fleet:bad', 'https://', ' https://fleet', 42):
            with self.subTest(value=value):
                config = copy.deepcopy(self.config)
                config['fleet_url'] = value
                with self.assertRaises(ValueError):
                    validate(config)

    def test_target_patterns_rejected(self):
        for targets in ([], 'srv02', ['all'], ['*'], ['dc*'], ['srv02:dc01'],
                        ['localhost'], ['srv02', 'srv02'], ['../x'], [None]):
            with self.subTest(targets=targets):
                config = copy.deepcopy(self.config)
                config['targets'] = targets
                with self.assertRaises(ValueError):
                    validate(config)

    def test_log_size_constraints(self):
        for size in (True, '134217728', 0, 1048577, 4294967296):
            with self.subTest(size=size):
                self.config['event_log_bytes'] = size
                with self.assertRaises(ValueError):
                    validate(self.config)

    def test_free_space_constraints(self):
        for size in (True, 0, '8', -1, 1025):
            self.config['min_free_gb'] = size
            with self.assertRaises(ValueError):
                validate(self.config)

    def test_version_pin(self):
        self.config['elastic_version'] = 'latest'
        with self.assertRaises(ValueError):
            validate(self.config)

    def test_missing_key(self):
        del self.config['fleet_url']
        with self.assertRaises(ValueError):
            validate(self.config)

    def test_extra_secret_rejected(self):
        self.config['password'] = 'never-put-secrets-here'
        with self.assertRaises(ValueError):
            validate(self.config)

    def test_non_object_rejected(self):
        with self.assertRaises(ValueError):
            validate([])
