# Elastic monitoring for GOAD — host telemetry and Workstation setup (draft)

An additive, standalone Ansible companion for an existing GOAD inventory.
Target Elastic version: **9.5.3**. This is **not yet** the full Fleet/EDR solution.
The monitoring playbooks remain standalone. This branch also includes targeted
Windows launcher and SSMS detection fixes in GOAD's core deployment code.
The existing `extensions/elk` Filebeat-based extension is unchanged.

See [DEPLOYMENT-TROUBLESHOOTING.md](DEPLOYMENT-TROUBLESHOOTING.md) for observed
errors, recovery steps, evidence, and outstanding deployment fixes.

## Current implementation

| Component | Status |
| --- | --- |
| Explicit target selection and configuration checks | Implemented; offline tests pass |
| Read-only Windows observations and controller-side JSON reports | Implemented; live WinRM testing pending |
| Sysmon artifact cache, hash checks, Microsoft signature check | Implemented; live Windows testing pending |
| Fresh Sysmon install and managed configuration updates | Implemented; canary testing pending |
| Local audit, PowerShell, command-line, and channel logging | Implemented; English Windows preset; canary testing pending |
| Post-GPO effective logging verification | Implemented; operator controls GPO refresh |
| VMware Workstation creation/provisioning wrapper | Implemented; native GOAD CLI reused; live provider testing pending |
| Optional Docker-ELK bootstrap and Fleet Server | Planned; no stack mutation in this milestone |
| Agent installation, Fleet policies, Elastic Defend/EDR | Planned; not installed by these playbooks |
| GPO management, targeted SACLs, transcription | Planned |
| Ingestion checks, data-stream retention, automated rollback | Planned |

There is deliberately no `extension.json` or native `install_extension` hook yet.
Use these standalone playbooks, not `install_extension elastic_monitoring`.
Do not run the Windows mutation playbook on all hosts before a canary review.

## Prerequisites and boundaries

- An isolated GOAD lab; use the same inventory files, credentials, and
  WinRM/PSRP settings as its current provisioner. This extension does not deploy
  a domain through its monitoring playbooks or change firewall exposure.
  For optional native GOAD creation on the selected VMware Workstation provider,
  see [VMWARE-WORKSTATION.md](VMWARE-WORKSTATION.md).
- Linux Ansible controller with Python 3.11+, Ansible Core 2.18-compatible
  environment, and the collection pinned in `requirements.yml`. Keep a separate
  virtual environment if the existing GOAD installation pins different versions.
- Windows PowerShell 5.1, an elevated administrator session, AMD64 Windows,
  at least the configured free space, and an explicit Sysmon OS support review.
- The audit-policy preset uses English subcategory names and is intentionally
  gated to English Windows (OSLanguage 1033). Sysmon alone has no language gate.
- HTTPS origins are required in configuration. Preflight currently tests **TCP
  reachability only**, not certificates, HTTP health, credentials, Elastic
  version availability, OS support for Agent/Endpoint, or ingestion. Reports
  explicitly mark those checks as `not_evaluated`.
- Preflight does not require healthy Fleet/Elasticsearch ports to collect local
  facts: they may not exist yet. Host telemetry installation is independent of
  those connections. Future Agent enrollment will have a separate TLS gate.
- Local registry/audit changes are opt-in. A GPO can override them. Use dedicated
  logging GPOs for centrally managed policy; automatic GPO creation is pending.
- No secrets go into committed files, command-line `-e key=secret` arguments,
  report files, or shell tracing. Keep real variables in ignored local files and
  encrypted Vault files. Windows logs can contain sensitive command lines and
  scripts: restrict access and plan storage/retention accordingly.

## 1. Configure and inspect one member host

From this directory, install the collection in your chosen Ansible environment:

```bash
ansible-galaxy collection install -r requirements.yml
cp config.example.yml config.local.yml
```

Edit `config.local.yml`: replace the HTTPS origins and select the **inventory
alias** of one member host under `monitoring_targets`. Do not put a new IP address
there or create a second host alias for an existing VM. Leave `monitoring_apply`
false. The example aliases and URLs are placeholders, not discovery results.

Run from `ansible/`, supplying **all** inventory inputs used for that GOAD
instance. The following paths are placeholders, not a universal GOAD layout:

```bash
cd ansible
ansible-playbook \
  -i /absolute/path/to/goad/lab-inventory \
  -i /absolute/path/to/goad/provider-inventory \
  -i /absolute/path/to/goad/globalsettings.ini \
  -i ../inventory.example.ini \
  -e @../config.local.yml \
  preflight.yml
```

The overlay maps GOAD's `domain` group into `monitoring_windows` and defines a
local controller. If your inventory uses a different group, make a local overlay
and adjust it. Include enabled extension inventories and `globalsettings.ini`
when present; `scripts/workstation.py inspect` reports the full ordered path
list for your Workstation instance without printing credentials.
`monitoring_targets` is mandatory and must be a nonempty subset of
that group. Do not use `--limit` or `--start-at-task`: they can skip controller
gates or report generation. Narrow the target list instead. Run this workflow
once at a time against a given lab/cache; concurrent mutation is not supported.

Reports are saved under `.local/reports/`, one SHA-256-named file per inventory
alias, with the alias inside the JSON. A report says `observed`, not `ready`:
observations are evidence, not a support certification. Raw WinRM failures are
not copied into reports. Preserve timestamped copies when comparing runs.
Unreachable/failed hosts cause preflight to fail after reports are saved.

## 2. Resolve reproducible Sysmon artifacts

Select and review a complete 40-character commit from
[Hartong's configuration](https://github.com/olafhartong/sysmon-modular).
From the extension directory:

```bash
python3 scripts/artifacts.py \
  --hartong-revision YOUR_REVIEWED_40_CHARACTER_COMMIT \
  --cache .local/artifacts/canary-01
```

The first run fetches Microsoft's current Sysmon ZIP and the XML at that exact
commit, validates their basic formats, caches both by SHA-256, and creates
`artifacts.lock.json`. Subsequent runs verify/reuse the cache without downloading.
To refresh, use a **new cache directory** and review the changed artifacts on a
canary. Never silently overwrite an old lock. Do not run two resolvers against
the same new directory concurrently. Actual binary version/signature validation
happens on Windows before installation; a locally recorded download checksum
does not authenticate the publisher.

This tool needs controller egress to Microsoft Sysinternals and GitHub. Windows
receives the artifacts from Ansible and may need certificate-chain/revocation
connectivity for Authenticode. Nothing disables signature or TLS validation.

## 3. Apply host telemetry on the canary

Before proceeding:

1. Review the preflight report and snapshot the lab using its supported process.
2. Review the actual XML: Hartong's default is a starting point, not guaranteed
   coverage of every event. Approve the observed OS build for Sysmon in
   `monitoring_sysmon_approved_builds`, based on Microsoft's requirements.
3. Set `monitoring_apply: true`. If local logging is wanted, explicitly set
   `monitoring_allow_local_logging: true` after reviewing applicable GPOs.
4. Do not approve DC changes until a member-host canary has passed. DC changes
   additionally require `monitoring_allow_dc_changes: true`.
5. If Filebeat/Winlogbeat exists, investigate its channel collection first. The
   extension reports it and blocks mutation unless explicitly acknowledged; it
   does not uninstall or reconfigure the existing collector.

From `ansible/`, use the same inventory inputs as preflight:

```bash
ansible-playbook \
  -i /absolute/path/to/goad/lab-inventory \
  -i /absolute/path/to/goad/provider-inventory \
  -i /absolute/path/to/goad/globalsettings.ini \
  -i ../inventory.example.ini \
  -e @../config.local.yml \
  -e @../.local/artifacts/canary-01/artifacts.lock.json \
  windows.yml
```

This applies Sysmon first, then the local logging preset, **serially, one host at
a time**. Any host failure stops the deployment. It installs no Elastic Agent.
`--check` is not an installation preview: the mutation play explicitly rejects
check mode because executable installation and backup semantics need a real
canary. Use `preflight.yml` for read-only observations.

Artifacts and settings backups remain under `%ProgramData%\GOAD-Monitoring`,
restricted to SYSTEM and Administrators. The Sysmon role refuses unmanaged
existing installations and binary upgrades; neither is silently replaced. It
retains previous managed XML files and configuration-state snapshots, checks
the installed binary hash, and reads Sysmon's active configuration hash.
If Sysmon does not report the expected hash, deployment stops without writing a
success marker. See [rollback and recovery](ROLLBACK.md) before retrying.

The logging preset enables process command lines, PowerShell script-block/module
logging, selected audit subcategories, and operational channels. It only
increases log capacity, preserves retention modes, and does not clear logs.
Success/failure auditing is enabled for selected subcategories without reducing
existing audit flags; unrelated subcategories remain untouched. DC-specific
Kerberos auditing is added only on detected DCs. No broad SACL or transcription
changes are made. Windows PowerShell logging does not configure PowerShell 7.

## 4. Verify and repeat

- Confirm Sysmon64 is running and its reported configuration hash matches the
  artifact lock; the installation role checks both.
- In an appropriate maintenance window, refresh domain Group Policy using your
  normal management process. This repository does not trigger it automatically.
- Run `validate-logging.yml` with the same inventories and configuration used
  above. It reads registry/channels and checks audit policy without changing it.
  A mismatch is a policy conflict to investigate, not a reason to repeatedly
  overwrite domain policy.
- Repeat `windows.yml` on the same canary with the same lock and require no
  unnecessary Windows changes. Controller reports are refreshed independently.
- Inspect benign process and PowerShell events **locally**. Central ingestion,
  Endpoint health, duplicate collection checks, and applied Fleet revisions
  cannot pass until the Fleet/Agent milestones are implemented.

## Tests and current validation limits

```bash
python3 -m unittest discover -s tests -v
```

The offline suite requires PyYAML (already a GOAD dependency). It checks config
validation, artifact-cache behavior, tamper detection, XML/ZIP constraints, YAML
parsing/duplicate keys, deployment defaults, and the VMware native-workflow
wrapper. It uses fake in-memory artifacts and temporary metadata/fake processes,
never real Sysmon binaries, hypervisors, or network access.

On a controller with the pinned collection installed, run Ansible syntax checks
for `preflight.yml`, `windows.yml`, and `validate-logging.yml`. On Windows
PowerShell 5.1, run `tests/Test-PowerShellSyntax.ps1`. That helper parses `.ps1`
files without executing them; it does not parse inline YAML scripts. Neither
syntax checking nor the Python tests proves WinRM, Sysmon, GPO, or idempotency
behavior. Those require canary testing.

See [PLAN.md](PLAN.md) for the remaining full-stack milestones.

## Sources

- [GOAD extension conventions](https://orange-cyberdefense.github.io/GOAD/)
- [Microsoft Sysmon](https://learn.microsoft.com/en-us/sysinternals/downloads/sysmon)
- [Sysmon Modular](https://github.com/olafhartong/sysmon-modular)
- [Yamato logging guidance](https://github.com/Yamato-Security/EnableWindowsLogSettings)
- [Elastic support matrix](https://www.elastic.co/support/matrix)

The logging tasks are a limited, independently implemented preset informed by
these sources, not a complete translation or execution of Yamato's scripts.
