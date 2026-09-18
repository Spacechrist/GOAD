"""Optional VMware Workstation entry point around GOAD's native CLI.

plan/inspect are read-only. create launches GOAD's native installer, leaves its
confirmation prompt intact, and never starts monitoring or installs host tools.
This wrapper uses only the Python standard library; the invoked goad.py needs
the existing GOAD environment. Tested against the upstream CLI at 992307ad.
"""
import argparse
from contextlib import contextmanager
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

LABS = ('GOAD', 'GOAD-Light', 'MINILAB')
METHODS = ('local', 'vm')
PRIVATE_RANGES = tuple(ipaddress.IPv4Network(cidr) for cidr in
                       ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
ID_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')


def validate_prefix(prefix):
    if not isinstance(prefix, str) or not re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{1,3}){2}', prefix):
        raise ValueError('Use three IPv4 octets, e.g. 192.168.56; not a host or CIDR')
    try:
        subnet = ipaddress.IPv4Network(prefix + '.0/24')
    except ValueError as exc:
        raise ValueError('Invalid IPv4 prefix') from exc
    if not any(subnet.subnet_of(network) for network in PRIVATE_RANGES):
        raise ValueError('Use an RFC1918 private lab subnet')
    return prefix


def checked_identifier(value, label):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError(f'Invalid {label}; use a single inventory/instance identifier')
    return value


def repo_path(value):
    root = Path(value).resolve()
    if not (root / 'goad.py').is_file() or not (root / 'template/provider/vmware/Vagrantfile').is_file():
        raise ValueError('Expected a complete GOAD checkout with its native VMware template')
    if not (root / 'workspace').is_dir():
        raise ValueError('GOAD workspace directory is missing')
    return root


def read_instances(root):
    instances = {}
    workspace = (root / 'workspace').resolve()
    for path in sorted(workspace.glob('*/instance.json')):
        if path.resolve().parent.parent != workspace or path.parent.is_symlink() or path.is_symlink():
            raise ValueError('Instance metadata must be a regular file inside the workspace')
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, OSError) as exc:
            raise ValueError(f'Unreadable instance metadata: {path.parent.name}') from exc
        if not isinstance(state, dict) or state.get('id') != path.parent.name:
            raise ValueError(f'Instance identifier mismatch: {path.parent.name}')
        checked_identifier(state['id'], 'instance ID')
        # Validate every record, even another provider, to avoid overlooking an
        # existing subnet when metadata is corrupt. Do not print raw metadata.
        for key in ('lab', 'provider', 'provisioner', 'status'):
            if not isinstance(state.get(key), str):
                raise ValueError(f'Instance metadata missing {key}: {state["id"]}')
        validate_prefix(state.get('ip_range'))
        if not isinstance(state.get('extensions', []), list):
            raise ValueError(f'Invalid extension list: {state["id"]}')
        for extension in state.get('extensions', []):
            checked_identifier(extension, 'extension name')
        instances[state['id']] = state
    return instances


def make_plan(root, lab, prefix, method, python=None, platform=None):
    if lab not in LABS or method not in METHODS:
        raise ValueError('Unsupported lab or provisioning method for this wrapper')
    validate_prefix(prefix)
    platform = os.name if platform is None else platform
    if platform == 'nt' and method != 'vm':
        raise ValueError('Native Windows requires --method vm; use Linux/WSL for local Ansible')
    if not (root / 'ad' / lab / 'providers/vmware/Vagrantfile').is_file():
        raise ValueError('Selected lab has no native VMware provider template in this checkout')
    conflicts = [state['id'] for state in read_instances(root).values()
                 if state['ip_range'] == prefix]
    if conflicts:
        raise ValueError('Subnet already recorded in workspace: ' + ', '.join(conflicts)
                         + '. Inspect/reuse the existing instance instead of creating another.')
    command = [str(python or sys.executable), str(root / 'goad.py'), '-t', 'install',
               '-p', 'vmware', '-l', lab, '-ip', prefix, '-m', method]
    return {
        'action': 'create_native_goad_instance',
        'provider': 'vmware', 'lab': lab, 'ip_range': prefix, 'provisioner': method,
        'working_directory': str(root), 'argv': command,
        'monitoring_will_run': False,
        'requirements': ['VMware Workstation', 'Vagrant', 'Vagrant VMware Utility',
                         'vagrant-vmware-desktop and GOAD-required Vagrant plugins',
                         'GOAD dependencies in the selected Python environment'],
        'checks_not_performed': ['hypervisor/plugin health', 'available RAM/disk',
                                 'subnet conflicts outside this checkout',
                                 'VMware virtual-network isolation/reachability'],
    }


def inspect_instance(root, instance_id, inventory_mode='standard'):
    checked_identifier(instance_id, 'instance ID')
    state = read_instances(root).get(instance_id)
    if state is None:
        raise ValueError('Instance not found in this checkout')
    if state['provider'] != 'vmware':
        raise ValueError('Selected instance is not a VMware Workstation instance')
    if state['lab'] not in LABS:
        raise ValueError('This wrapper currently supports GOAD, GOAD-Light and MINILAB')
    if inventory_mode not in ('standard', 'disabled-vagrant'):
        raise ValueError('Unknown inventory mode')
    folder = root / 'workspace' / instance_id
    if inventory_mode == 'disabled-vagrant':
        inventories = [folder / 'inventory_disable_vagrant']
    else:
        inventories = [root / 'ad' / state['lab'] / 'data/inventory', folder / 'inventory']
    inventories.extend(folder / (name + '_inventory') for name in state.get('extensions', []))
    if (root / 'globalsettings.ini').is_file():
        inventories.append(root / 'globalsettings.ini')
    inventories.append(root / 'extensions/elastic_monitoring/inventory.example.ini')
    return {
        'instance_id': state['id'], 'provider': state['provider'], 'lab': state['lab'],
        'provisioner': state['provisioner'], 'ip_range': state['ip_range'],
        'native_status': state['status'], 'live_readiness': 'not_evaluated',
        'inventory_mode': inventory_mode,
        'inventory_paths': [str(path) for path in inventories],
        'missing_inventory_paths': [str(path) for path in inventories if not path.is_file()],
        'note': 'Paths belong to this checkout. Re-run inspect inside a Linux controller checkout; '
                'do not pass Windows host paths to a provisioning VM. No inventory contents are returned.',
    }


@contextmanager
def creation_lock(root):
    directory = root / 'extensions/elastic_monitoring/.local'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / 'workstation-create.lock'
    token = f'{os.getpid()}:{uuid.uuid4().hex}'
    try:
        handle = path.open('x', encoding='utf-8')
    except FileExistsError as exc:
        raise ValueError('Workstation creation lock exists. Check for an active run; '
                         'review a stale lock manually after interruption.') from exc
    try:
        with handle:
            handle.write(token)
        yield
    finally:
        # Never remove another process's replacement lock.
        if path.exists() and path.read_text(encoding='utf-8') == token:
            path.unlink()


def run_native(command, root):
    # GOAD retains interactive stdin. Its messages/prompts go to stderr so the
    # wrapper's stdout contains only the final JSON handoff. No shell/eval.
    return subprocess.run(command, cwd=root, stdout=sys.stderr, stderr=sys.stderr,
                          check=False).returncode


def create_instance(root, lab, prefix, method, runner=run_native, python=None):
    # The lock prevents parallel invocations of this wrapper. Native GOAD runs
    # outside this wrapper still require operator coordination.
    with creation_lock(root):
        plan = make_plan(root, lab, prefix, method, python=python)
        before = read_instances(root)
        rc = runner(plan['argv'], root)
        if rc != 0:
            raise ValueError(f'Native GOAD exited with code {rc}; inspect partial state before retrying')
        after = read_instances(root)
        new_ids = set(after) - set(before)
        if len(new_ids) != 1:
            raise ValueError('Expected exactly one new instance; install may have been declined, '
                             'failed, or run concurrently. No success is recorded.')
        instance_id = new_ids.pop()
        state = after[instance_id]
        expected = {'provider': 'vmware', 'lab': lab, 'ip_range': prefix,
                    'provisioner': method, 'status': 'installed'}
        if any(state.get(key) != value for key, value in expected.items()):
            raise ValueError('New instance metadata does not record the requested successful '
                             'provisioning. Inspect it with the inspect subcommand.')
        handoff = inspect_instance(root, instance_id)
        if handoff['missing_inventory_paths']:
            raise ValueError('Native provisioning recorded success, but required inventory files '
                             'are missing. Inspect before proceeding.')
        return handoff


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3],
                        help='GOAD checkout (default: the checkout containing this script)')
    subparsers = parser.add_subparsers(dest='action', required=True)
    for name in ('plan', 'create'):
        sub = subparsers.add_parser(name)
        sub.add_argument('--lab', choices=LABS, default='GOAD')
        sub.add_argument('--ip-prefix', required=True, help='Explicit isolated RFC1918 /24 prefix')
        sub.add_argument('--method', choices=METHODS, required=True,
                         help='local for Linux/WSL controller; vm for native Windows')
    inspect = subparsers.add_parser('inspect')
    inspect.add_argument('--instance', required=True)
    inspect.add_argument('--inventory-mode', choices=('standard', 'disabled-vagrant'), default='standard')
    args = parser.parse_args(argv)
    try:
        root = repo_path(args.repo)
        if args.action == 'inspect':
            result = inspect_instance(root, args.instance, args.inventory_mode)
        elif args.action == 'plan':
            result = make_plan(root, args.lab, args.ip_prefix, args.method)
        else:
            result = create_instance(root, args.lab, args.ip_prefix, args.method)
    except (ValueError, OSError) as exc:
        print(f'Workstation setup stopped: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
