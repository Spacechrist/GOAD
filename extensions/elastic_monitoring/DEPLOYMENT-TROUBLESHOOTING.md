# Deployment incident and recovery record

## Fresh rebuild regression: elevated wrapper UserId error

The fresh deployment of `5bffdbc` failed on DC01 at `fix_ip.ps1` with
`(10,8):UserId:` and a wrapper line `$username = 'vagrant'`. The stack identifies
`winrm-elevated` / `Shell: Elevated`. Earlier scripts using ordinary WinRM had
completed. Vagrant then logged reload-provisioner cleanup, stopping and deleting
DC01, followed by connection-reset and timeout errors. Those later exceptions
must not obscure the initial task-registration error. Deletion completion and
the state of other machines require checking; do not assume all VMs were removed.

Cause assessment: the newly enabled `privileged: true` path invoked Vagrant's
scheduled-task elevation wrapper, which failed on this box before the IP script
reported success. The precise Windows account-resolution cause is unconfirmed.

Correction: restore `privileged: false` for both IP scripts, using the same
administrative WinRM session as the preceding provisioning scripts. The IP
script explicitly checks the effective administrator token and fails clearly if
it is unavailable. No UAC or authentication settings are weakened. The startup
task, reboot and post-reboot verification remain. Existing generated workspace
Vagrantfiles need updating as well as the source template.

Status: correction prepared from the failure evidence; successful Windows runtime
verification is pending. The previous PowerShell syntax pass did not exercise
Vagrant's generated elevation wrapper and could not detect this regression.

Last updated: 2026-09-17. This records the evidence available in the deployment
conversation, not a claim of completed end-to-end validation.

Deployment changes addressing these incidents are now described in
[REBUILD-FIXES.md](REBUILD-FIXES.md). They require a fresh Windows/VMware run;
the recovered lab's success does not validate the new automated path.

## Environment

- Windows host, VMware Workstation Pro, Vagrant 2.4.9, VMware plugin 3.0.5,
  vagrant-reload 0.0.1, native Python 3.10 virtual environment.
- GOAD checkout: `C:\lab\GOAD`; branch: `feature/elastic-monitoring`.
- Existing instance: `fbfe51-goad-vmware`; provisioning method: `vm`.
- Linux provisioning VM: `192.168.56.3`; source: `/home/vagrant/GOAD`.
- Lab Windows addresses observed: DC01 `.10`, DC03 `.12`, SRV02 `.22`.
- Docker-ELK checkout: `C:\lab\docker-elk`, not started during these incidents.

## 1. GOAD crashes before provider startup on Windows

Error: `WindowsCommand.is_in_path() takes 2 positional arguments but 3 were given`.
Startup constructs providers and calls the inherited `on_ludus()` probe even
when VMware was selected. That probe passes `show_log=False`; the Windows
override lacked that argument.

Fix: add `show_log=True` to the Windows override and honor it for logging.
Commit: `17253a99f6a7944df5ffe63804200b0a8c89f4d7`.
Validation: 51 local Python tests passed, including mocked Windows regression
tests. The user's next dependency check passed the previous crash and found
Vagrant, VMware and the required plugins. No Ludus installation was needed.
Repeated Windows `where` informational messages were still observed; suppressing
those native messages was not part of this fix.

## 2. Windows VMware provisioning hangs at fix_ip.ps1

Observed on DC01, DC03 and SRV02; DC02 was reported to work. The original script
always ran `netsh.exe int ip set address Ethernet1 static <ip> 255.255.255.0`.
Guest checks showed the desired address was Preferred, DHCP Disabled, Ethernet1
Connected, and no remaining netsh process. WinRM responded on the new address.
DC01 initially used a DHCP lab address, then changed to `.10`; a later attempt
used forwarded WinRM `127.0.0.1:55985`, which also responded.

Diagnosis: a disrupted/stalled provisioning session after changing the network
is plausible. The exact mechanism was not proven, particularly for the forwarded
connection. Do not treat this as a confirmed universal VMware root cause.

Workaround applied locally in `C:\lab\GOAD\vagrant\fix_ip.ps1`: validate the
requested IP; inspect Ethernet1's IPv4 address/prefix/state and DHCP setting;
return success without netsh when already Preferred at the requested /24 with
DHCP disabled. Otherwise run netsh and fail on nonzero exit. The old script was
backed up as `fix_ip.ps1.before-recovery`.

After stopping the previous controller action, retry only the affected machine
from `workspace\fbfe51-goad-vmware\provider`, e.g. `vagrant provision GOAD-DC01`.
DC01 explicitly returned `already configured ... no change needed`. Subsequent
lab provisioning advanced. Repeat this recovery only after checking current
guest state and ensuring no earlier Vagrant action is active.

Status: local retry workaround, not a committed permanent first-install fix.
Remaining: idempotent script in the fork, reliable management connectivity during
first address assignment, and fresh-host validation without manual intervention.

## 3. Vagrant reports another action holds the VM lock

Cause/evidence: an earlier Vagrant action had not exited. A parent/child Python
pair with Vagrant and Ruby descendants is one process chain, not automatically
multiple installations. A process listing plus `vmrun list` showed one active
chain and one running VM in an earlier investigation.

Recovery: Ctrl+C once in the original controller terminal and wait for exit.
If it does not stop, inspect current PIDs and command lines before terminating
only that stalled action tree. Do not reuse old PIDs, delete lock files, kill
all Ruby/Python processes, or launch overlapping installations. No confirmed
specific forced process-termination command was recorded.

## 4. VMware Utility connection refused on 127.0.0.1:9922

This failure occurred before guest provisioning. Earlier service output identified
the local service name as `VagrantVMware`.

Recovery on the Windows host, elevated PowerShell:

```powershell
Restart-Service -Name VagrantVMware -ErrorAction Stop
Get-Service -Name VagrantVMware
Test-NetConnection 127.0.0.1 -Port 9922
```

Retry the selected VM's provisioning only after Running/port success. The user's
next DC01 provisioning completed the guarded IP task. This does not require
deleting or powering off the guest.

## 5. Provisioning VM SSH host-key mismatch and missing source

Errors: `REMOTE HOST IDENTIFICATION HAS CHANGED`, authentication restrictions,
and `/home/vagrant/GOAD/ansible/: No such file or directory`.
RDP access to Windows guests is unrelated. An old/recreated machine at the same
address is plausible; the host-key warning alone does not prove that cause.

Recovery: verify the provisioning VM's address and ED25519 host fingerprint from
its VMware console. Only after matching the presented fingerprint, remove the
specific stale entry on the Windows host:

```powershell
ssh-keygen -R 192.168.56.3 -f "$env:USERPROFILE\.ssh\known_hosts"
ssh vagrant@192.168.56.3
```

Accept only the independently verified key. Do not disable host-key checks as
the repair. SSH login was reported successful. In GOAD's management console:

```text
load fbfe51-goad-vmware
prepare_jumpbox
sync_source_jumpbox
```

Verify `/home/vagrant/GOAD/ansible/build.yml` exists, then `provision_lab`.
The user reported lab provisioning started. Creating an empty directory would
not restore the Ansible content.

## 6. Obsolete SQL Server Express download launcher

See [MSSQL-INSTALLER-INCIDENT.md](MSSQL-INSTALLER-INCIDENT.md).
Confirmed: SQL2019-SSEI-Expr launcher version `15.2204.5490.2` refused to proceed
with an unsupported-installer message. Silent operation appeared hung and the
SSEI bootstrap log was empty. Running it visibly exposed the error.

Replacement from Microsoft's SQL Server 2019 Express download page opened
successfully as version `15.2607.0.1`. The recovery instruction backed up and
replaced `C:\setup\mssql\sql_installer.exe`, preserving `sql_conf.ini`.
`C:\Setup\sql_installer.exe` alone is not the path GOAD executes.
The role reuses any existing cached file, so changing its URL alone is inadequate.
Resume at `provision_lab_from servers.yml`, not a new lab creation.

Later recaps show SRV02 passed servers.yml while SRV03 failed. This supports
progress on SRV02, not full-lab completion or successful fresh reproduction.
SRV03's subsequent incomplete-engine failure must be tracked separately.
Permanent artifact/version/signature/cache handling remains unimplemented.

## 7. SRV03 partial SQL installation and master.mdf conflict

The installer exhausted three retries with error `-2061893587` / `0x851a002d`:
master.mdf already existed under `MSSQL15.SQLEXPRESS\MSSQL\DATA`.
The SQLEXPRESS service and registry mapping existed, but this did not demonstrate
a successfully configured engine.

Starting the service briefly succeeded, then it stopped. ERRORLOG showed model
and msdb referencing inaccessible `D:\dbs\...\mkmastr.proj` paths, errors
17204/5120/17207/945. Reboot did not resolve this. A later log proved 1433 bound
successfully before shutdown: the port timeout was a consequence of engine
failure, not evidence that firewall changes were needed. Automatic SPN
registration warnings were also present but were not the shutdown cause shown.

Attempted repair from full media `Express_ENU\SETUP.EXE` targeted SQLEXPRESS.
It failed with `-2068578302` / `0x84B40002`: the engine was never successfully
configured and could not be repaired. The `RulesEng\SETUP.EXE` filename/size or
SHA-1 alone was not proof of the correct media entry point.

Recovery prescribed: snapshot SRV03; use SQL Setup's Remove workflow for only
SQLEXPRESS Database Engine Services; preserve shared features. After successful
removal and any requested reboot, confirm the service is absent. Preserve any
remaining DATA directory by timestamped rename rather than deletion. Retain the
verified new launcher, then resume from servers.yml.

An initial post-removal check still showed the service, and Summary.txt still
described Repair: removal was not confirmed at that point. The user later
reported rebooting/resuming, but no successful uninstall summary, sustained SQL
health result or complete final recap was supplied. Do not mark this resolved.

Permanent requirement: recognize partial installation, stop blind installer
retries, preserve logs/data, and test sustained service/database recovery. Do not
automate destructive cleanup merely because setup returned nonzero.

## 8. SSMS 22 repeatedly installed by a role expecting SSMS 18

See [SSMS-RECOVERY.md](SSMS-RECOVERY.md).
The moving `aka.ms/ssmsfullsetup` URL supplied SSMS 22.10.1 on SRV02, Windows
Server 2019. GOAD passed `/install /quiet /norestart` and checked only an SSMS 18
directory. These assumptions do not match the documented modern installer.
An initial absence of the executable during diagnosis prompted verifying the
guest identity; it was not established as an installer failure.

Visible retry with documented `--passive --norestart --wait` was suggested after
stopping the old launchers. The user reported a successful step on a rerun but
did not establish which action caused success. Do not attribute success solely
to the suggested argument change.

Conclusive later evidence: vswhere reported SSMS 22.10.1, isComplete=true,
isLaunchable=true, isRebootRequired=false, while another legacy invocation was
running. This confirms installed product detection was inadequate.

Committed targeted fix: `8c61d7cac7df56d3f257cc852837d5147c1e79a2`.
The role queries modern registered installations and checks their executable;
complete installations skip legacy tasks, incomplete registrations fail clearly,
and pending reboot is handled. Original installation tasks remain in legacy.yml.
YAML parsing passed; live behavior after deploying this commit is still pending.
Fresh-install pinning, arguments, compatibility and verification remain pending.

## Applying repository changes and continuing safely

Stop any existing controller action and affected redundant installer before a
retry. Preserve local changes such as fix_ip.ps1; do not reset the checkout.
Pull `feature/elastic-monitoring` with fast-forward only. In the GOAD console:

```text
load fbfe51-goad-vmware
sync_source_jumpbox
provision_lab_from servers.yml
```

Wait for synchronization to succeed before provisioning. The provisioning VM
executes its own source copy; a Windows-host git pull alone is insufficient.
`provision servers.yml` runs only that playbook; `provision_lab_from servers.yml`
continues the remaining sequence. Do not rerun the creation wrapper for recovery.

## Completion and reproducibility gates

- Record one exact fork commit for the second lab system.
- Verify fresh provisioning needs no manual installer replacement or IP recovery.
- Confirm SQL remains running after system-database recovery, expected listeners
  and role tasks succeed, and SSMS is complete and launchable.
- Collect the final recap and GOAD success message; a quiet task, transient
  running service, TCP response or intermediate successful step is insufficient.
- Check a repeat run avoids unnecessary installation.
- Keep secrets, SQL configuration contents and private SSH keys out of this log.

At the initial recording, full-lab success and second-system reproduction had not
been reported. See the later successful resumed provisioning milestone below.
Fleet, Elastic Agent/EDR and Docker-ELK automation are separate unfinished scope.

## 9. Fixed SSMS role remained stale on the provisioning VM

The Windows checkout was confirmed at commit 8c61d7c, but reading
/home/vagrant/GOAD/ansible/roles/mssql_ssms/tasks/main.yml over SSH still showed
the original installer-first tasks. A subsequent remote check still showed old
content after synchronization was advised. The underlying synchronization failure
was not diagnosed; no successful sync command output was supplied.

Recovery instructed: stop provisioning and redundant SSMS launchers; use scp
from the Windows checkout to copy both main.yml and legacy.yml into the existing
remote role tasks directory. Verify the remote file starts with the modern
discovery task, then resume from servers.yml. Copying only main.yml is insufficient
because it includes legacy.yml. The user next reported completed provisioning.

Permanent requirement: investigate native Windows source synchronization and
verify remote source hashes/revision before executing Ansible. Direct scp is a
workaround, not proof that sync_source_jumpbox is fixed.

## Successful resumed provisioning milestone

User-reported final output on 2026-09-17:
`Provisioned from servers.yml in 01:29:23`, followed by the GOAD prompt for
instance fbfe51-goad-vmware.

| Host | ok | changed | unreachable | failed | skipped | rescued | ignored |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dc01 | 11 | 4 | 0 | 0 | 1 | 0 | 0 |
| dc02 | 16 | 14 | 0 | 0 | 6 | 0 | 0 |
| dc03 | 10 | 7 | 0 | 0 | 0 | 0 | 0 |
| srv02 | 13 | 10 | 0 | 0 | 1 | 0 | 0 |
| srv03 | 13 | 11 | 0 | 0 | 1 | 0 | 0 |

This confirms completion of the resumed playbook sequence as reported by GOAD.
The supplied recap is the final play's recap, not cumulative task totals for all
playbooks. This supersedes earlier statements that no completion output had been
received. It does not establish the exact successful SQL reinstall steps, every
intermediate SSMS task result, ongoing service health, repeat-run idempotency,
or fresh reproducibility on the second system. Monitoring deployment has not
been performed by this successful GOAD provisioning run.
