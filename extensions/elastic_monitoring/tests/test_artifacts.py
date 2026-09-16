import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from artifacts import resolve, validate_revision, validate_xml, validate_zip


def sample_zip():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('Sysmon64.exe', b'unit-test-only-not-an-executable')
    return stream.getvalue()


class ArtifactTests(unittest.TestCase):
    revision = 'a' * 40
    xml = b'<Sysmon schemaversion="4.90"><EventFiltering /></Sysmon>'

    def test_full_revision_required(self):
        for revision in ('master', 'latest', 'abc', 'A' * 40, '../main', None):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                validate_revision(revision)

    def test_valid_xml(self):
        self.assertEqual(validate_xml(self.xml), '4.90')

    def test_reject_dtd(self):
        with self.assertRaises(ValueError):
            validate_xml(b'<!DOCTYPE Sysmon [<!ENTITY x "expanded">]><Sysmon schemaversion="4"/>')

    def test_reject_utf16(self):
        with self.assertRaises(ValueError):
            validate_xml('<Sysmon schemaversion="4"/>'.encode('utf-16-le'))

    def test_reject_other_xml(self):
        with self.assertRaises(ValueError):
            validate_xml(b'<NotSysmon/>')

    def test_zip_member_required(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('../Sysmon64.exe', b'invalid member')
        with self.assertRaises(ValueError):
            validate_zip(stream.getvalue())

    def test_download_once_then_reuse(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return sample_zip() if url.endswith('.zip') else self.xml
        with tempfile.TemporaryDirectory() as folder:
            first = resolve(folder, self.revision, fetch)
            second = resolve(folder, self.revision, fetch)
            self.assertEqual(first, second)
            self.assertEqual(len(calls), 2)
            self.assertIn('/' + self.revision + '/', calls[1])

    def test_changed_artifact_rejected_without_download(self):
        def fetch(url):
            return sample_zip() if url.endswith('.zip') else self.xml
        with tempfile.TemporaryDirectory() as folder:
            lock = resolve(folder, self.revision, fetch)
            Path(lock['monitoring_artifacts']['sysmon_config']).write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'Cached artifact changed'):
                resolve(folder, self.revision, lambda _: self.fail('Must not download'))

    def test_changed_revision_requires_new_cache(self):
        def fetch(url):
            return sample_zip() if url.endswith('.zip') else self.xml
        with tempfile.TemporaryDirectory() as folder:
            resolve(folder, self.revision, fetch)
            with self.assertRaisesRegex(ValueError, 'revision changed'):
                resolve(folder, 'b' * 40, lambda _: self.fail('Must not download'))

    def test_lock_cannot_point_outside_cache(self):
        def fetch(url):
            return sample_zip() if url.endswith('.zip') else self.xml
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / 'cache'
            lock = resolve(cache, self.revision, fetch)
            lock['monitoring_artifacts']['sysmon_zip'] = str(Path(folder) / 'elsewhere.zip')
            (cache / 'artifacts.lock.json').write_text(json.dumps(lock))
            with self.assertRaisesRegex(ValueError, 'inside the lock directory'):
                resolve(cache, self.revision, lambda _: self.fail('Must not download'))

    def test_failed_download_does_not_create_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(OSError):
                resolve(folder, self.revision, lambda _: (_ for _ in ()).throw(OSError('offline')))
            self.assertFalse((Path(folder) / 'artifacts.lock.json').exists())
