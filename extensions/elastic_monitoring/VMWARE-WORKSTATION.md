# VMware Workstation deployment

The selected hypervisor is **VMware Workstation**, using GOAD's native `vmware`
provider and Vagrant's `vagrant-vmware-desktop` plugin. This is not the
`vmware_esxi` provider. Existing GOAD deployment templates remain unchanged.

`scripts/workstation.py` adds three operations:

| Operation | Behavior |
| --- | --- |
| `plan` | Reads this checkout and prints the proposed native GOAD command as JSON; launches nothing |
| `create` | Calls native `goad.py -t install -p vmware`, preserves GOAD's confirmation, and checks the new saved instance state |
| `inspect` | Reads one explicitly selected existing instance and reports inventory paths without their contents; launches nothing |

Use `inspect` for an existing lab. `create` is optional and is **not idempotent**:
it creates a new lab. It refuses a subnet already recorded in this checkout and
never falls back to a default instance. It does not offer destroy/reset, silently
resume failed provisioning, install host dependencies, or run monitoring.

## Choose the controller environment

| Host/controller setup | GOAD method | Monitoring controller |
| --- | --- | --- |
| Workstation on Linux | `local` | Prepared Linux Ansible environment |
| Workstation on Windows, with GOAD run in WSL | `local` | Prepared WSL/Linux Ansible environment; follow upstream WSL setup constraints |
| Workstation on Windows, with native Windows Python | `vm` | GOAD's Linux provisioning VM or another prepared Linux controller |

The wrapper requires an explicit method. Native Windows Python cannot select
`local`. It invokes the **same Python executable that runs the wrapper**, so
activate the prepared GOAD environment first. A Python installation that can
print a plan may still lack the dependencies needed to execute `goad.py`.

Prepare Workstation, Vagrant, Vagrant VMware Utility, the required Vagrant
plugins, GOAD Python dependencies, and Ansible dependencies using the fork's
[provider instructions](../../docs/mkdocs/docs/providers/vmware.md) and
[host installation instructions](../../docs/mkdocs/docs/installation/index.md).
The wrapper does not download or install any of these. It also does not run
GOAD's dependency checker implicitly, since native checks may offer installation.

Allocate capacity for both the lab and monitoring. Confirm that the selected
private subnet does not overlap your host/VPN/other labs, and verify the actual
VMware virtual-network configuration. Prefix validation checks RFC1918 syntax,
not network isolation, routing, RAM, disk, or hypervisor health.

## Optional new lab

From `extensions/elastic_monitoring`, in the prepared Linux/WSL GOAD environment:

```bash
python3 scripts/workstation.py plan \
  --lab GOAD --ip-prefix 192.168.56 --method local
```

The subnet is an example; choose your own conflict-free lab network. `GOAD`,
`GOAD-Light`, and `MINILAB` are supported by this initial wrapper if their native
VMware templates exist in the checkout.

After reviewing the plan, creating/provisioning the new lab is an explicit command:

```bash
python3 scripts/workstation.py create \
  --lab GOAD --ip-prefix 192.168.56 --method local
```

For native Windows Python, use the activated Windows GOAD environment and `vm`:

```powershell
python scripts/workstation.py plan --lab GOAD --ip-prefix 192.168.56 --method vm
python scripts/workstation.py create --lab GOAD --ip-prefix 192.168.56 --method vm
```

GOAD retains its own interactive creation prompt. Native output goes to stderr;
stdout contains the final JSON inventory handoff only if the wrapper's checks
pass. A normal exit from native GOAD is not enough: this version can log an error
without returning a failing process exit code. The wrapper additionally requires:

1. Exactly one newly recorded instance.
2. Matching provider, lab, subnet, and provisioning method.
3. Native status `installed`.
4. All required inventory paths present.

Even those checks only establish **recorded native provisioning success**.
They do not prove current VM reachability, directory health, Sysmon/Agent support,
or telemetry ingestion. The JSON sets `live_readiness: not_evaluated`.

Concurrent `create` operations through this wrapper use an exclusive lock at
`.local/workstation-create.lock`. Do not run native GOAD creation concurrently
outside the wrapper. After an abrupt interruption, inspect any active processes
and partial VMs before manually removing a stale lock. Failures preserve native
workspace/VM state; recover using GOAD's existing instance workflow. Do not keep
retrying `create`, which could otherwise request another lab.

## Existing lab and inventory handoff

Use the exact instance ID recorded under this checkout's `workspace` directory:

```bash
python3 scripts/workstation.py inspect --instance YOUR_INSTANCE_ID
```

For normal credentials the inventory order is:

1. `ad/<lab>/data/inventory`.
2. `workspace/<instance>/inventory` (the rendered provider inventory).
3. Any enabled extensions' rendered inventories.
4. `globalsettings.ini`, when present.
5. This companion's `inventory.example.ini` overlay.

If GOAD's `disable_vagrant` workflow has already been applied, explicitly select
the domain-credential inventory instead:

```bash
python3 scripts/workstation.py inspect --instance YOUR_INSTANCE_ID \
  --inventory-mode disabled-vagrant
```

The wrapper cannot infer which credentials are currently valid from the native
instance metadata. It returns paths, never passwords or the contents of inventory
files. Include every returned inventory, in order, in the monitoring Ansible
invocation described in [README.md](README.md). Check `missing_inventory_paths`
before running it. Keep `monitoring_targets` limited to one member-host canary.

For a provisioning VM or other remote controller, the host's absolute paths are
not usable there. Ensure that the matching branch/source and the selected
instance's current rendered inventory are available on that Linux controller,
then run `inspect` in that checkout. Provisioning the lab from native Windows
does not make Ansible Windows-host execution supported.

## Elastic stack placement

GOAD VMs must reach Fleet and Elasticsearch by stable, certificate-matching names.
Do not configure `localhost` or Docker-internal service names as agent-facing
URLs. A Workstation guest's `localhost` refers to that guest.

This wrapper does not create an ELK VM or alter your existing Docker-ELK setup.
The location of the Docker host and its VM-reachable DNS/IPs remain configuration
inputs for the next Fleet/Agent milestone. Docker-ELK bootstrap and EDR are still
pending; creating the GOAD lab does not install them.

## Validation status

The offline tests exercise plan/inspect behavior, argv construction, explicit
provider/method selection, subnet conflicts, malformed state, inventory handoff,
creation locking, and failure detection. A fake native entry point tests process
failure propagation. **No VMware, Vagrant, GOAD VM creation, or live Ansible run
has been executed in the development workspace.**
