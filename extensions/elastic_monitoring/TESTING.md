# Validation record

## Completed in the development workspace

- `python3 -m unittest discover -s tests -v`: **48 tests passed**.
- YAML parsed with duplicate-key rejection.
- Reviewed Windows mutation gates, private state storage, artifact integrity
  checks, preexisting-installation refusal, and report status semantics.
- Changes are confined to a new `extensions/elastic_monitoring` directory.
- Workstation wrapper tests cover native argv construction, subnet/method gates,
  metadata-based failure detection, inventory handoff without credential output,
  concurrent-create locking, and a fake child-process failure. They launch no VMs.

The tests cover Python logic, fake process handling, and static repository
properties. They do not execute Ansible modules, install software, contact a lab,
or test Windows APIs.

## Not run in this environment

- Ansible syntax/module-resolution checks: Ansible is not installed here.
- PowerShell syntax checks: Windows PowerShell / `pwsh` is not installed here.
- Live WinRM/PSRP preflight, Sysmon install/configuration update, logging changes,
  GPO refresh, rollback, and repeat-run idempotency.
- Authenticode validation with the lab's trust/revocation connectivity.
- VMware Workstation/Vagrant dependency checks, native GOAD provisioning,
  native Windows `vm` provisioning method, and inventory transfer to a controller.
- Fleet, Elastic Agent, Elastic Defend, and ingestion: these are not implemented
  in milestone 1 and must not be inferred from a passing offline test suite.

## Required before live acceptance

1. Install the pinned Ansible collection on a test controller and syntax-check
   each playbook using the actual inventory inputs and local config file.
2. Parse the PowerShell files with `tests/Test-PowerShellSyntax.ps1` on Windows
   PowerShell 5.1 and review the inline state-directory script in the YAML role.
3. Run preflight with one member host; verify that wrong targets, wrong transports,
   unavailable hosts, and an empty Sysmon support-review list fail appropriately.
4. Resolve/review artifacts and canary-test Sysmon. Verify service signature,
   actual binary version, hash-field parsing from `sysmon64 -c`, and local events.
5. Test local logging backup/restore in the disposable canary. Verify effective
   policy after a controlled GPO refresh and check log-volume impact.
6. Repeat with the same configuration and require no unnecessary Windows changes.
7. Review a DC canary separately before enabling DC mutation or wider rollout.

Do not claim end-to-end acceptance until the remaining roadmap is implemented
and supported hosts produce the expected centrally ingested events.
