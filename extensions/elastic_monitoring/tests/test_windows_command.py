"""Exercise actual command classes with subprocess and unrelated imports mocked."""
import importlib.util
from pathlib import Path
import subprocess
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WindowsCommandTests(unittest.TestCase):
    def setUp(self):
        stubs = {}
        for name, attribute in [('goad.log', 'Log'), ('goad.utils', 'Utils'),
                                ('goad.dependencies', 'Dependencies'), ('psutil', None)]:
            module = ModuleType(name)
            if attribute:
                setattr(module, attribute, Mock())
            stubs[name] = module
        with patch.dict(sys.modules, stubs):
            base = load_module('goad.command.cmd', ROOT / 'goad/command/cmd.py')
            with patch.dict(sys.modules, {'goad.command.cmd': base}):
                self.windows = load_module('windows_under_test', ROOT / 'goad/command/windows.py')
        self.command = self.windows.WindowsCommand()
        self.log = self.windows.Log

    def test_ludus_probe_found_and_missing_is_silent(self):
        for found in (True, False):
            with self.subTest(found=found):
                self.log.reset_mock()
                failure = None if found else subprocess.CalledProcessError(1, 'where ludus')
                with patch.object(self.windows.subprocess, 'run', side_effect=failure) as run:
                    self.assertIs(self.command.on_ludus(), found)
                    run.assert_called_once_with('where ludus >nul', shell=True, check=True)
                self.assertEqual(self.log.mock_calls, [])

    def test_default_lookup_logs_success_and_failure(self):
        for found in (True, False):
            with self.subTest(found=found):
                self.log.reset_mock()
                failure = None if found else subprocess.CalledProcessError(1, 'where vagrant.exe')
                with patch.object(self.windows.subprocess, 'run', side_effect=failure):
                    self.assertIs(self.command.check_vagrant(), found)
                if found:
                    self.log.success.assert_called_once_with('vagrant.exe found in PATH')
                    self.log.error.assert_not_called()
                else:
                    self.log.error.assert_called_once_with('vagrant.exe not found in PATH')
                    self.log.success.assert_not_called()

    def test_keyword_silent_lookup(self):
        with patch.object(self.windows.subprocess, 'run'):
            self.assertTrue(self.command.is_in_path('vagrant.exe', show_log=False))
        self.assertEqual(self.log.mock_calls, [])


if __name__ == '__main__':
    unittest.main()
