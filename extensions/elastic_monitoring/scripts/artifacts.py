"""Resolve once, cache by hash, and verify Sysmon artifacts on subsequent runs.

No third-party Python dependencies. Windows performs Authenticode verification
before execution. A recorded download hash provides reproducibility, not publisher
authentication. Never use this module to validate Elastic packages.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.request import urlopen
import zipfile
import xml.etree.ElementTree as ET

SYSMON_URL = 'https://download.sysinternals.com/files/Sysmon.zip'
MAX_BYTES = 32 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_revision(revision):
    if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Use a complete lowercase Hartong Git commit SHA, not master/latest')


def validate_xml(data):
    # Reject UTF-16 and entities before parsing untrusted XML.
    text = data.decode('utf-8-sig')
    if '\x00' in text or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('Sysmon configuration must be UTF-8 XML without DTD/entities')
    root = ET.fromstring(text)
    if root.tag != 'Sysmon' or not root.attrib.get('schemaversion'):
        raise ValueError('Not a versioned Sysmon configuration')
    return root.attrib['schemaversion']


def validate_zip(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = [entry for entry in archive.infolist() if entry.filename == 'Sysmon64.exe']
        if len(entries) != 1 or not 0 < entries[0].file_size <= MAX_BYTES:
            raise ValueError('Archive must contain exactly one bounded Sysmon64.exe')
        # Validate CRC without extracting arbitrary archive members.
        archive.read(entries[0])


def download(url):
    with urlopen(url, timeout=60) as response:
        if not response.url.startswith('https://'):
            raise ValueError('Refusing a non-HTTPS redirect')
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Artifact exceeds the 32-MiB limit')
    return data


def atomic_write(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.artifact-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def verify_lock(lock_path, revision):
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    artifacts = lock['monitoring_artifacts']
    if artifacts['hartong_revision'] != revision:
        raise ValueError('Hartong revision changed; use a new cache directory for review')
    for name in ('sysmon_zip', 'sysmon_config'):
        path = Path(artifacts[name]).resolve()
        if path.parent != lock_path.parent.resolve():
            raise ValueError('Cached artifact must remain inside the lock directory')
        if digest(path.read_bytes()) != artifacts[name + '_sha256']:
            raise ValueError('Cached artifact changed; refusing to replace it automatically')
    return lock


def resolve(cache, revision, fetch=download):
    validate_revision(revision)
    cache = Path(cache).resolve()
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = cache / 'artifacts.lock.json'
    if lock_path.exists():
        return verify_lock(lock_path, revision)
    config_url = f'https://raw.githubusercontent.com/olafhartong/sysmon-modular/{revision}/sysmonconfig.xml'
    binary, config = fetch(SYSMON_URL), fetch(config_url)
    validate_zip(binary)
    schema = validate_xml(config)
    zip_path = cache / (digest(binary) + '.zip')
    config_path = cache / (digest(config) + '.xml')
    atomic_write(zip_path, binary)
    atomic_write(config_path, config)
    lock = {'monitoring_artifacts': {
        'sysmon_zip': str(zip_path), 'sysmon_zip_sha256': digest(binary),
        'sysmon_config': str(config_path), 'sysmon_config_sha256': digest(config),
        'hartong_revision': revision, 'sysmon_config_schema': schema,
        'sysmon_url': SYSMON_URL, 'sysmon_config_url': config_url,
    }}
    atomic_write(lock_path, (json.dumps(lock, indent=2) + '\n').encode())
    return lock


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', required=True, help='New directory for refresh; existing cache is verified/reused')
    parser.add_argument('--hartong-revision', required=True)
    args = parser.parse_args()
    resolve(args.cache, args.hartong_revision)
    print(str(Path(args.cache).resolve() / 'artifacts.lock.json'))
