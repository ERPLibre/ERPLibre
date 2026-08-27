
# LongTest — tests that create real machines

These are not unit tests. They create virtual machines, install systems on
them, and take hours. They live here and **not** in `test/`, which the unit
runner sweeps: `./script/test/run_unit_test.sh` must stay runnable in seconds
on any machine, including one without virtualisation.

Run them from the menu — `TODO › Execute › Test › Long tests` — or directly.

## deep_proxmox.py — how deep does Proxmox-in-Proxmox go?

The practicable nesting depth cannot be deduced, only measured — and one
measurement is not a measurement.

A manual look at one fourth-level VM found a guest **36 times slower than real
time** (583 seconds of wall clock for 16 seconds of guest time, each ACPI line
taking a second) and then a frozen kernel: identical RIP across three samples
two minutes apart, and **not one byte written** to disk.

Running this script **refuted the conclusion drawn from it**. Its own
fourth-level VM — 2 vCPU where the manual one had 12 — booted, installed, and
wrote gigabytes. What looked like a nesting ceiling was a *parallelism*
ceiling under nesting. That is exactly what the algorithm caps, and this is
how it stopped being a guess.

Which is the point of the script: a number obtained once, on one machine, in
one chain, is an anecdote.

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

Memory is **not** capped. On that one manual VM, dropping it from 9 GB to
2 GB moved nothing — it stopped after reading the same 32 MiB, which is simply
the size of the boot files. Memory was not the lever; the vCPU count was. And
trimming memory would starve the level below, which needs it to host the
next.

The plan is printed **before** anything is created, and the script never
promises a depth it knows will not fit — better to announce six levels and
reach six than to promise ten and die at the seventh without knowing why.
