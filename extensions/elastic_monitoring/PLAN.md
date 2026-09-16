# Implementation roadmap

## Architecture and scope

Keep all customization additive under `extensions/elastic_monitoring` until the
standalone roles are validated. Reuse GOAD inventories and native provider
workflows instead of maintaining a second copy of domain provisioning. Preserve
the existing `elk` extension. Elastic components are pinned to 9.5.3; integration
package versions will be selected for that version and recorded separately.

| Milestone | Deliverables | Acceptance gate |
| --- | --- | --- |
| 1 — Host telemetry foundation | Explicit target selection, configuration checks, readiness reports, pinned artifact cache, Sysmon install/config update, local logging subset | Offline tests plus Windows canary and repeat-run evidence |
| 2 — Existing Docker-ELK and Fleet | Read-only stack inspection, compatible Compose override, service token, Fleet policy, TLS/CA wiring, readiness checks | Existing data/credentials/project identity preserved; three TLS paths verified |
| 3 — Fleet policies and agents | Separate DC/member policies; Defend, Windows and System integrations; verified Agent installer; explicit policy/upgrade lifecycle | Supported host Agent/Endpoint health, policy revision, benign telemetry ingestion |
| 4 — Domain logging | Dedicated GPOs, effective-policy checks, optional targeted SACLs and transcription | Settings survive Group Policy refresh; backups and scoped restoration verified |
| 5 — Optional fresh deployment | Native GOAD setup entry point and optional pinned Docker-ELK initialization | Provider-specific canary; no replacement of existing installations |
| 6 — Full validation and recovery | Ingestion/dedup checks, retention policy, machine-readable rollout results, removal/recovery tasks | Member canary, DC canary, staged rollout, no unnecessary second-run changes |

Milestone 1's source and the VMware Workstation portion of milestone 5 are
implemented in this draft. `scripts/workstation.py` provides a read-only plan,
explicit optional native GOAD creation, and existing-instance inventory handoff.
No milestone has yet passed live lab acceptance. Remaining milestones are not stub playbooks that pretend to
work. Native extension registration and end-to-end `site.yml` come only once
their dependencies are real.

## Decisions needed before stack/provider work

- Provider confirmed: **VMware Workstation** (`vmware`, not `vmware_esxi`).
  Still needed for live setup: host/controller OS and method, lab variant,
  instance identity (when reusing a lab), subnet and complete inventory inputs.
- Docker-ELK checkout path, commit/branch, Compose files/project name, and whether
  the running stack already uses TLS; inspect rather than assume.
- VM-reachable Fleet/Elasticsearch DNS names, certificate SANs, CA ownership, and
  where Fleet Server will run. Keep container-internal and VM-facing URLs separate.
- Baseline license and protection requirements. Report unsupported capabilities;
  do not rely on a trial remaining active.
- Per-component OS support: Sysmon, Elastic Agent, and Elastic Defend are separate
  checks. Log-only fallback requires an explicit decision, never a silent skip.
- Data-stream retention and disk budget, separate from Windows log capacity.

## Fleet implementation requirements

1. Verify existing Elasticsearch/Kibana versions and license without changing
   them. Never silently upgrade/downgrade an existing volume.
2. Initialize Fleet, install a compatible Fleet Server package, create/reuse its
   policy, configure URLs/outputs, and create/reuse the service token.
3. Use the correct server-capable Elastic Agent container for the pinned release.
   Validate Agent → Fleet, Agent/Endpoint → Elasticsearch, and Fleet → Elasticsearch
   certificates independently; no insecure enrollment bypasses.
4. Reconcile integration policies without generating new IDs/tokens on every run.
   Windows collects Sysmon/PowerShell; System collects Security/System/Application.
   Assign extra event channels to exactly one collector.
5. Enroll one Agent per compatible host, detect existing installations, and make
   reinstall, upgrade, policy reassignment, and removal explicit operations.
6. Use Vault and `no_log` for secret-bearing tasks; avoid embedding credentials in
   Git, logs, command-line arguments, URLs, or generated world-readable files.
7. Validate recent events using host identity, dataset, and a bounded time window.
   Correlated Sysmon and Endpoint events are not duplicate channel collection.

## Bootstrap and rollback requirements

`bootstrap-elk.sh` will default to inspecting an existing checkout. Fresh mode
must be explicit, use a recorded upstream revision, and never run initialization
over an existing deployment. Preserve Compose project identity, networks,
credentials, volumes, and TLS. No `down -v`, secret rotation, or trust changes
without an explicit reviewed operation.

Future rollback must distinguish configuration rollback from binary downgrade,
agent removal, policy deletion, and stack data recovery. Require canary evidence
for every destructive recovery procedure; never label a config backup as a full
domain or Elasticsearch backup.
