import os.path
import shlex
import subprocess
from goad.log import Log
from goad.utils import *
from goad.goadpath import GoadPath
from goad.jumpbox import JumpBox
from goad.source_sync import sync_checkout, ssh_arguments


class LocalJumpBox(JumpBox):
    def __init__(self, instance, creation=False):
        super().__init__(instance, creation)
        self.username = 'vagrant'

    def provision(self):
        return self.run_command('bash scripts/setup_local_jumpbox.sh', '/home/vagrant/GOAD')

    def get_jumpbox_key(self, creation=False):
        if not creation:
            folder = f'{self.instance_path}/provider/.vagrant/machines/PROVISIONING/'.replace('/', os.path.sep)
            providers = Utils.list_folders(folder)
            if providers:
                return folder + providers[0] + os.path.sep + 'private_key'
            Log.error(f'PROVISIONING ssh key not found at : {folder}')
        return None

    def sync_sources(self):
        try:
            receipt = sync_checkout(GoadPath.get_project_path(), self.instance_path,
                                    self.ssh_key, self.username, self.ip)
            Log.success(f'Provisioning source SHA256 verified: {receipt}')
            return True
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            Log.error(f'Source synchronization failed; provisioning stopped: {error}')
            return False

    def run_command(self, command, path):
        try:
            directory = '$HOME' if path == '~' else shlex.quote(path)
            result = subprocess.run(ssh_arguments(self.ssh_key, self.username, self.ip) +
                                    [f'cd {directory} && {command}'])
            return result.returncode == 0
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            Log.error(f'Provisioning SSH command failed: {error}')
            return False
