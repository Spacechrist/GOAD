# Recovery boundaries — milestone 1

No automatic uninstall, domain restore, binary downgrade, or full rollback command
is shipped yet. Use a tested lab snapshot/recovery process before canary mutation.
The scripts stop on unexpected existing installations rather than adopt them.

## Backups produced

Inside `%ProgramData%\GOAD-Monitoring` (SYSTEM/Administrators only):

- Content-addressed Sysmon ZIPs and XML files, plus the verified staged binary.
- `sysmon-state.json`: last verified managed binary/configuration, version, and
  Hartong revision. Before a config change, the old state is saved under its
  previous config hash. Older XML files remain available.
- `audit-policy-before.csv`: original system audit-policy backup.
- `logging-baseline.json`: original values/types/presence for managed registry
  settings, channel state/capacity/mode, and checksum of the audit backup.

These are configuration backups, not event-log exports, filesystem snapshots,
GPO backups, or domain-controller system-state backups. Copy protected backups
off-host before any maintenance that could destroy the VM or its state disk.
Do not publish them in Git or attach secrets to a PR.

## Sysmon configuration recovery

Use the previously verified binary and the retained previous XML during an
operator-controlled maintenance window. Check both hashes against the saved
state, apply the old XML using Microsoft's documented configuration-update
operation, then verify service health and Sysmon's reported active config hash.
Update the selected artifact lock consistently before the next Ansible run, or
the desired configuration will be reapplied. Do not uninstall Sysmon merely to
change its configuration.

Binary upgrades/downgrades are not automated. A mismatched binary, renamed
service, or unmanaged installation stops the role for manual review. If a first
installation succeeds but writing the state fails, the next run deliberately
treats it as unmanaged: inspect the live binary/configuration and recover through
a reviewed procedure rather than manufacturing a success marker.

## Logging recovery

Compare the baseline to current configuration first. A whole audit-policy
restore can overwrite changes made by other administrators since the baseline.
Restore only approved values/subcategories where possible. For registry values
that were originally absent, remove only that value, not the entire key. Preserve
unrelated registry entries and GPO ownership.

Shrinking log files or changing retention can discard evidence or halt future
logging. Export/archive required events before such an operation. The deployment
role never shrinks logs or changes retention. Take a new reviewed baseline if
expanding the managed channel/registry scope; the role refuses to silently reuse
an incomplete baseline.

After any restore, refresh policy through your normal management process and
verify effective settings. `validate-logging.yml` checks the deployed desired
preset, not the historical baseline; it is expected to fail after intentionally
restoring a different baseline. A future dedicated rollback validator will
compare against saved historical state.

## Removal and future stack work

Sysmon removal is an explicit operator action using Microsoft's documented
uninstall procedure after reviewing evidence-retention requirements. Do not
delete the entire state directory as an uninstall shortcut. This milestone has
not created Fleet policies, tokens, agents, Docker containers, volumes, or GPOs,
so there are no such objects for it to remove.
