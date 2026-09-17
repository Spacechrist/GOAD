# MSSQL installer incident and required deployment fix

Recorded: 2026-09-17. Applies to the native Windows / VMware Workstation deployment
on branch `feature/elastic-monitoring`.

## Confirmed failure

During `servers.yml`, SRV02 and SRV03 stalled at `mssql : Install the database`.
The cached executable at `C:\setup\mssql\sql_installer.exe` was the SQL Server
2019 Express download launcher, not the full database installation media:

- Original filename: `SQL2019-SSEI-Expr.exe`.
- Product version: `15.2204.5490.2`.
- Size observed: 6,379,936 bytes.
- Only the launcher and `sql_conf.ini` were visible under the media staging tree.
- The launcher process remained alive; no separate SQL setup process was observed.
- `C:\Program Files\Microsoft SQL Server\150\SSEI\LogFiles\SSEI-Expr_20260917020712.txt`
  existed but was empty.
- Opening the launcher interactively displayed: "This version of the installer
  is no longer supported. Please download again from the download site."

This confirms rejection of that launcher version. A quiet task alone does not
establish this diagnosis on another host. It does not mean SQL Server 2019 itself
is unsupported for this deployment.

The role displayed this configured URL:
`https://download.microsoft.com/download/7/f/8/7f8a9c43-8c8a-4f7c-9f92-83c18d96b681/SQL2019-SSEI-Expr.exe`.
We have not independently established which bytes that URL serves now.

## Recovery used in this session

1. Stop the active Ansible run before attempting another installation.
2. Stop the stalled `sql_installer` launcher on the affected guest; do not
   indiscriminately terminate unrelated Windows Installer or database processes.
3. Download the SQL Server **2019 Express** launcher from Microsoft's official
   page: https://www.microsoft.com/en-us/download/details.aspx?id=101064 .
4. Open the replacement interactively to check that the expired-launcher error
   is gone. The supplied screenshot showed version `15.2607.0.1` and the normal
   Basic / Custom / Download Media selection screen.
5. Close the interactive launcher. Back up the old executable and copy the new
   launcher from `C:\Setup\sql_installer.exe` to the exact path GOAD invokes:
   `C:\setup\mssql\sql_installer.exe`. Preserve `sql_conf.ini`.
6. Resume in the GOAD management console using `load <existing-instance-id>`
   followed by `provision_lab_from servers.yml`. This resumes at that playbook
   and includes subsequent playbooks; `provision servers.yml` runs only one.

The role in `ansible/roles/mssql/tasks/main.yml` downloads only when its target
file is absent. Thus changing the URL alone does not replace an obsolete cache.
It also explains why the debug output can still print the old configured URL
while `get the installer` is skipped and the replacement executable is used.

SRV03 was subsequently reported to have a similar stall. Its installer version
and exact error have not been supplied. Verify its configured SQL major version
and edition before applying a replacement; do not assume SRV02's package fits.

## Required deployment changes (pending implementation)

- Use an official Microsoft source appropriate to each configured SQL major
  version and edition; record the resolved artifact URL and version.
- Replace existence-only cache acceptance with version/edition checks and
  checksum validation against an approved artifact record. Explicitly reject
  the known obsolete 2019 launcher observed above.
- Validate the downloaded executable's Authenticode signature and Microsoft
  publisher before execution. Record version and SHA-256; the replacement's
  checksum has not yet been captured in this session.
- Stage and validate replacements before swapping files; retain the old file
  for rollback and preserve SQL configuration, credentials and installed data.
- Make artifact refresh explicit. Pin artifacts for reproducibility, while
  recognizing that an online bootstrapper can later be rejected by its service.
  Evaluate verified full installation media to remove that runtime dependency.
- Bound installation waits and report relevant bootstrap/setup log paths on
  failure. Do not silently retry a known unsupported executable three times.
- Keep credential-bearing configuration and installer arguments out of reports.
- Add regression coverage for obsolete cached launchers, valid cache reuse,
  failed artifact verification and SQL version/edition selection.

## Validation still required

The fresh launcher opening successfully is confirmed. Successful unattended SQL
installation and complete GOAD provisioning have **not** yet been reported.
Before treating this as a verified deployment fix, collect:

- The replacement's version, SHA-256 and validated publisher/signature status.
- SQL setup's successful final result and exit code.
- A running configured SQL service, expected listener, and successful remaining
  role tasks (a running service alone is insufficient).
- GOAD's completion message and final recap with no failed or unreachable hosts.
- A fresh deployment on the user's second lab system using one recorded commit,
  with no manual executable replacement, followed by a repeat-run check.

This document records the incident and recovery procedure; it does not change
the MSSQL role or claim that the permanent fix has been implemented.
