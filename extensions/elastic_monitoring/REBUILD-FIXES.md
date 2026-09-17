# VMware deployment fixes and rebuild acceptance

These changes are a rebuild candidate. The earlier manually recovered lab
completed provisioning; a fresh deployment of this revision has not yet been
demonstrated. Keep that distinction when recording results.

## Implemented changes

| Incident | Deployment change | Remaining verification |
| --- | --- | --- |
| Windows provider discovery crashed in `is_in_path` | Existing signature fix retained | Already passed the user's dependency check |
| WinRM stalled while changing Ethernet1 | Schedule the validated address change at startup, reload through `vagrant-reload`, then verify address, prefix and DHCP state | First boot on VMware Workstation Windows |
| SQL launcher stalled and cached downloads were reused | Validate Microsoft signature, product identity, minimum version and optional SHA256; replace obsolete cache only after validating a staged download | Fresh SQL installation on both member servers |
| Partial SQL instance was mistaken for success | Check sustained SQL queries with all four system databases online; refuse orphaned database files; fail with recovery instructions | Fresh installation and second run |
| Setup was repeated over partial SQL databases | One bounded installer attempt; no automatic whole-playbook retry in VM provisioner | Confirm a deliberate failure stops once |
| SSMS latest download changed installer generation | Fixed SSMS 20.2.1 full-package URL and matching arguments for fresh installs; complete modern installations recognized with `vswhere` | Fresh install and second-run skip |
| Windows fork differed from provisioning VM | Transfer tracked local sources plus selected instance inventory; validate SHA256 manifest on the VM before each playbook | Confirm logged receipt and changed task names |
| Recreated VM reused a global SSH host entry | Per-instance SSH known-hosts file, accept first key and reject later changes | First connection and subsequent reconnect |
| Vagrant action lock or stopped VMware Utility | Documented recovery retained; no automatic process killing | Operational check when encountered |

The SQL health check uses the configured domain administrator's Windows identity
over local shared memory. It does not infer success from the service registration
or a briefly open TCP port. If that account lacks SQL access on an existing
instance, investigate that access failure rather than reinstalling it.

SQL installation configuration contains credentials. Staging access is restricted
to administrators and SYSTEM, task output is suppressed, and the rendered INI is
removed after the attempt. Installer failures retain database files and logs.

## Artifact selection

The SQL 2019 URL in this repository is still the URL advertised by the
[Microsoft download page](https://www.microsoft.com/en-us/download/details.aspx?id=101064).
The observed obsolete launcher was `15.2204.5490.2`; the replacement reported in
the recovery was `15.2607.0.1`. The role now rejects the obsolete version rather
than accepting any file that happens to exist.

Fresh SSMS installations use the full SSMS 20.2.1 package from Microsoft's
[release history](https://learn.microsoft.com/en-us/ssms/release-history).
This avoids feeding legacy `/install` arguments to the new SSMS 22 bootstrapper.
An existing complete, launchable modern SSMS installation is preserved. Partial
modern installations fail for explicit recovery. This does not pin SQL Engine
media downloaded internally by the SQL web launcher.

Each verified installer gets a neighboring `.artifact.json` receipt containing
its URL, detected version and SHA256. Approved hashes can be pinned with
`sql_launcher_sha256_2019`, `sql_launcher_sha256_2022`, and `ssms_sha256`.
Defaults intentionally contain no invented hashes. Without operator-approved
pins, different fresh deployments may obtain different signed SQL launchers.
`sql_refresh_installer` and `ssms_refresh_installer` request a refresh; previous
binaries are retained under hash-qualified names. A recorded cache whose hash
unexpectedly changes is rejected.

## Before replacing the working lab

1. Preserve a powered-off VM backup or consistent snapshots, your workspace,
   inventories, credentials, installer receipts and successful provisioning logs.
2. In Windows PowerShell at `C:\lab\GOAD`, inspect `git status --short` and
   preserve local changes, particularly earlier manual `fix_ip.ps1` edits. Do not
   discard changes merely to make a pull succeed.
3. Update `feature/elastic-monitoring` with `git pull --ff-only` after resolving
   any local changes. Record `git rev-parse HEAD` with the test results.
4. Verify VMware Utility is running and `vagrant-reload` and
   `vagrant-vmware-desktop` are installed. Run the existing GOAD dependency check.
5. Run the checks below before scheduling replacement of the lab. Destruction is
   a separate explicit operation; these changes do not destroy VMs or databases.

Existing generated workspace Vagrantfiles are not rewritten by a Git pull.
The updated VMware template is intended for a newly generated workspace.
The provisioning VM no longer clones upstream GOAD during setup: the selected
Windows checkout is its source. SSH uses a key, batch mode and a per-instance
`goad_known_hosts` file. Verify unexpected key changes through the VM console;
do not disable host-key checks.

Only tracked deployment sources and selected instance inventory files are
synchronized. Untracked custom roles must be reviewed and added to Git before
use. Private keys and common local secret files are excluded. Generated inventory
can contain credentials and is transferred over SSH. Source hashes describe the
actual working-tree files, including tracked local edits, rather than claiming
they equal a clean commit. Avoid editing sources while a playbook is running.

## Checks and acceptance

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s extensions/elastic_monitoring/tests -v
powershell.exe -NoProfile -File extensions\elastic_monitoring\tests\Test-PowerShellSyntax.ps1
```

Local Linux verification covers Python behavior and YAML structure; it cannot
prove Windows installer or VMware behavior. PowerShell parsing does not execute
the scripts. The fresh Windows run must establish:

- Each host obtains its intended Ethernet1 address after reload without losing
  the provisioning session during an in-session address change.
- The provisioning source SHA256 receipt is logged before playbook execution.
- SQL setup completes, all system databases remain online, and the expected
  instance continues listening after reboot.
- SSMS discovery finds an executable and a complete registration; a second run
  skips installation and download.
- No stale credential INI remains, no automatic setup retry occurs after failure,
  and the final recap has zero failed or unreachable supported hosts.

Record actual installer receipts, SQL version, SSMS version and both run logs.
The monitoring extension has its own validation requirements; a successful core
lab rebuild does not establish Fleet, EDR or ingestion readiness.

See [the incident record](DEPLOYMENT-TROUBLESHOOTING.md),
[SQL recovery evidence](MSSQL-INSTALLER-INCIDENT.md), and
[SSMS recovery evidence](SSMS-RECOVERY.md). Earlier manual workarounds remain
historical evidence, not instructions to repeat after these fixes.
