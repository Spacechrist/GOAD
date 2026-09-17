"""Verified local-fork transfer using native OpenSSH, including on Windows."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import tarfile

ROOT_FILES = {'requirements.yml', 'noansible_requirements.yml', 'globalsettings.ini'}
SOURCE_ROOTS = {'ansible', 'ad', 'extensions', 'scripts'}
EXCLUDED = {'.git', '.venv', '.vagrant', '.local', '__pycache__', 'ssh_keys', 'node_modules'}


def allowed_path(name, instance_id):
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or '..' in path.parts or '\\' in name:
        return False
    if any(part in EXCLUDED for part in path.parts):
        return False
    if path.name in {'private_key', 'vault.yml', 'config.local.yml'} or path.suffix == '.pem':
        return False
    return (name in ROOT_FILES or path.parts[0] in SOURCE_ROOTS or
            (len(path.parts) == 3 and path.parts[:2] == ('workspace', instance_id)))


def build_bundle(project, instance_path):
    project, instance_path = Path(project).resolve(), Path(instance_path).resolve()
    instance_id = instance_path.name
    if not re.fullmatch(r'[A-Za-z0-9_-]+', instance_id):
        raise ValueError('Invalid instance ID')
    if instance_path.parent != project / 'workspace':
        raise ValueError('Instance must belong to this checkout workspace')
    tracked = subprocess.run(['git', 'ls-files', '--stage', '-z'], cwd=project, check=True,
                             stdout=subprocess.PIPE).stdout.decode('utf-8').split('\0')
    modes = {}
    for entry in tracked:
        if not entry:
            continue
        header, name = entry.split('\t', 1)
        mode, _, stage = header.split()
        if stage != '0':
            raise ValueError('Resolve git index conflicts before synchronization')
        if allowed_path(name, instance_id):
            if mode not in {'100644', '100755'}:
                raise ValueError('Unsupported source entry: ' + name)
            modes[name] = 0o700 if mode == '100755' else 0o600
    names = set(modes)
    if (project / 'globalsettings.ini').is_file():
        names.add('globalsettings.ini')
    names.update(p.relative_to(project).as_posix() for p in instance_path.iterdir()
                 if p.is_file() and (p.name.endswith('_inventory') or
                                    p.name in {'inventory', 'inventory_disable_vagrant'}))
    files = {}
    for name in sorted(names):
        if not allowed_path(name, instance_id):
            continue
        path = project / name
        for parent in [path, *path.parents]:
            if parent == project:
                break
            if parent.is_symlink():
                raise ValueError('Symlink in source: ' + name)
        if not path.is_file():
            continue
        data = path.read_bytes()
        if path.suffix in {'.sh', '.py', '.yml', '.yaml', '.j2', '.ini', '.ps1'}:
            data = data.replace(b'\r\n', b'\n')
        files[name] = data
    for required in ('ansible/build.yml', 'scripts/setup_local_jumpbox.sh',
                     'requirements.yml', f'workspace/{instance_id}/inventory'):
        if required not in files:
            raise ValueError('Missing required source: ' + required)
    manifest = {p: {'sha256': hashlib.sha256(data).hexdigest(), 'mode': modes.get(p, 0o600)}
                for p, data in files.items()}
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    receipt = hashlib.sha256(manifest_bytes).hexdigest()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w:gz') as tar:
        for name, data in [*files.items(), ('.goad-source-manifest.json', manifest_bytes)]:
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.mtime = len(data), modes.get(name, 0o600), 0
            tar.addfile(entry, io.BytesIO(data))
    return archive.getvalue(), receipt


# No extractall: validate names/types/hashes before touching the destination.
REMOTE_APPLY = r'''
import fcntl, hashlib, io, json, os, pathlib, sys, tarfile, tempfile
root = pathlib.Path.home() / 'GOAD'
if root.is_symlink(): raise RuntimeError('GOAD directory is a symlink')
root.mkdir(mode=0o700, exist_ok=True)
if (root / '.goad-sync.lock').is_symlink(): raise RuntimeError('Sync lock is a symlink')
lock = open(root / '.goad-sync.lock', 'a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
def safe(name):
    p = pathlib.PurePosixPath(name)
    return (bool(p.parts) and not p.is_absolute() and '..' not in p.parts and '\\' not in name
            and (p.parts[0] in {'ansible','ad','extensions','scripts','workspace'}
                 or name in {'requirements.yml','noansible_requirements.yml','globalsettings.ini'}))
archive = tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()), mode='r:gz')
members = archive.getmembers()
if len({m.name for m in members}) != len(members): raise RuntimeError('Duplicate archive path')
data = {}
for m in members:
    if not m.isfile() or (m.name != '.goad-source-manifest.json' and not safe(m.name)):
        raise RuntimeError('Invalid source archive entry')
    data[m.name] = archive.extractfile(m).read()
manifest_bytes = data.pop('.goad-source-manifest.json')
manifest = json.loads(manifest_bytes)
if set(manifest) != set(data): raise RuntimeError('Manifest mismatch')
for name, content in data.items():
    if hashlib.sha256(content).hexdigest() != manifest[name]['sha256']: raise RuntimeError('Source checksum mismatch')
    if manifest[name]['mode'] not in (0o600, 0o700): raise RuntimeError('Invalid source mode')
old_path = root / '.goad-source-manifest.json'
if old_path.is_symlink(): raise RuntimeError('Manifest is a symlink')
old = json.loads(old_path.read_text()) if old_path.exists() else {}
for name in set(old) | set(data):
    if not safe(name): raise RuntimeError('Invalid previous manifest path')
    for parent in [root / name, *(root / name).parents]:
        if parent == root: break
        if parent.is_symlink(): raise RuntimeError('Symlink in destination path')
with tempfile.TemporaryDirectory(prefix='.goad-stage-', dir=root) as temp:
    stage = pathlib.Path(temp)
    for name, content in data.items():
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(manifest[name]['mode'])
    for name in data:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stage / name, target)
    for name in set(old) - set(data):
        target = root / name
        if target.is_file(): target.unlink()
    (stage / 'manifest').write_bytes(manifest_bytes)
    os.replace(stage / 'manifest', old_path)
print(hashlib.sha256(manifest_bytes).hexdigest())
'''


def ssh_arguments(key, username, ip):
    import ipaddress
    ipaddress.IPv4Address(ip)
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*', username):
        raise ValueError('Invalid SSH username')
    if not key or not Path(key).is_file():
        raise ValueError('Missing provisioning SSH key')
    return ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new',
            '-o', 'UserKnownHostsFile=' + str(Path(key).parent / 'goad_known_hosts'),
            '-o', 'ConnectTimeout=15', '-i', str(key), f'{username}@{ip}']


def sync_checkout(project, instance_path, key, username, ip):
    payload, expected = build_bundle(project, instance_path)
    result = subprocess.run(ssh_arguments(key, username, ip) +
                            ['python3 -c ' + shlex.quote(REMOTE_APPLY)],
                            input=payload, stdout=subprocess.PIPE, timeout=300, check=True)
    if result.stdout.decode().strip() != expected:
        raise RuntimeError('Provisioning VM did not confirm the expected source checksum')
    return expected
