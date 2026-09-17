# SSMS repeat-install recovery (2026-09-17)

SRV02 (Windows Server 2019) downloaded SSMS 22.10.1 from the role's moving
download URL. The role checked only the SSMS 18 directory and invoked the
new bootstrapper with legacy arguments. The user supplied vswhere output
showing SSMS 22 complete, launchable, and not requiring reboot, while another
legacy-command installation was running.

The role now queries vswhere before any download or installation. It accepts
only complete, launchable registrations whose product executable exists.
Incomplete registrations or discovery failures stop provisioning for recovery.
A pending reboot on a completed registration is handled explicitly.

The original tasks are preserved in tasks/legacy.yml for hosts without a
modern registered installation. This is a targeted recovery change, NOT the
final fresh-install fix. Version-pinned downloads, OS compatibility selection,
signature/checksum verification, modern installer arguments and post-install
validation remain outstanding. Do not claim reproducible fresh deployment yet.

Validation: both task files parse as YAML. No Windows/Ansible execution was
available here. The next live check is that SRV02 skips the legacy task include.
Do not resume provisioning while an earlier SSMS installer remains active.
After pulling this change on the Windows controller, run sync_source_jumpbox
in the loaded GOAD instance before resuming from servers.yml; Ansible runs
from the Linux provisioning VM's copy.

The SQL database engine failures on SRV03 are separate from this SSMS issue.
