
# LongTest — tests that create real machines

These are not unit tests. They create virtual machines, install systems on
them, and take hours. They live here and **not** in `test/`, which the unit
runner sweeps: `./script/test/run_unit_test.sh` must stay runnable in seconds
on any machine, including one without virtualisation.

Run them from the menu — `TODO › Execute › Test › Long tests` — or directly.

## deep_proxmox.py — how deep does Proxmox-in-Proxmox go?

The practicable nesting depth cannot be deduced, only measured. A manual
measurement found, at the fourth level, a guest **36 times slower than real
time** — 583 seconds of wall clock for 16 seconds of guest time, each ACPI
line taking a second — then a guest kernel frozen at the **same byte**
whatever the resources. A number obtained once, on one machine, is not a
number: this script redoes it on demand and says exactly where it breaks.

```
./LongTest/deep_proxmox.py --depth 10 --dry-run   # the plan, nothing created
./LongTest/deep_proxmox.py --depth 10             # hours
./LongTest/deep_proxmox.py --detruire             # undo it
```

The descent is **uniform**. Every level, the first included, goes through the
same six steps: create, wait for ssh, install Proxmox, reboot and check the
kernel, bring pmxcfs back up, check the storage. Only creation differs —
libvirt locally, `qm` afterwards.

It sends **our** `install_proxmox.sh` over scp instead of letting the VM clone
the repository: it is our code we want to exercise, and the remote is often
behind the checkout — a fix absent from the remote made the same defect "come
back" on three VMs in a row.

### The resource algorithm

Two things run out going down, and a third degrades. What runs out is
arithmetic, and `script/proxmox/nesting.py` computes it:

* **memory** — each level keeps what its own daemons need (`pve-cluster`,
  `pvestatd`, `pvedaemon`, `pveproxy`) before handing the rest down;
* **disk** — the child's disk lives *inside* the parent's, which must also
  hold its own system.

What degrades is measured, not assumed: past the second level, vendors
document nothing. Hence one capped number — **2 vCPU** for every nested
level. Twelve vCPU at the fourth level froze the guest kernel in early boot;
the same two progressed. Bringing twelve processors online costs as many
round trips through the whole stack.

Memory is **not** capped: the same VM froze at the same byte with 9 GB and
with 2 GB, so trimming it would gain nothing and starve the level below.

The plan is printed **before** anything is created, and the script never
promises a depth it knows will not fit — better to announce six levels and
reach six than to promise ten and die at the seventh without knowing why.
