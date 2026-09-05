
# long_test — tests that create real machines

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
./long_test/deep_proxmox.py                        # three levels, ~30 minutes
./long_test/deep_proxmox.py --dry-run              # the plan, nothing created
./long_test/deep_proxmox.py --depth 5              # ask for more, knowingly
./long_test/deep_proxmox.py --detruire             # undo it
```

### How deep is worth asking for

The depth is the only setting, and **three** is the default because three
works. Measured on a 28-core machine, one full descent per row:

| level | boot (ssh) | install | total |
|------:|-----------:|--------:|------:|
| 1 | 0 s | 200 s | 280 s |
| 2 | 37 s | 344 s | 495 s |
| 3 | 93 s | 777 s | 1 064 s |
| 4 | **15 608 s** | **26 306 s** | did not finish |

Three levels cost half an hour. The **fourth** cost 4 h 20 of boot and 7 h 18
of install on the same machine — everything there is 15 to 30 times slower, not
just one step. And it lands exactly where the hardware vendors stop: level 4 is
the *third* nested hypervisor, and AMD documents two.

A wider guest makes it worse, sharply: at level 4, one extra vCPU multiplied
the boot by 9.4 (1 664 s at two vCPU, 15 608 s at three), and at eight vCPU the
guest read 32 MiB in 106 minutes with a static instruction pointer. At levels 2
and 3 that same vCPU costs nothing.

So: three by default, five if you want to know, ten only to watch the wall.

The descent is **uniform**. Every level, the first included, goes through the
same six steps: create, wait for ssh, install Proxmox, reboot and check the
kernel, bring pmxcfs back up, check the storage. Only creation differs —
libvirt locally, `qm` afterwards.

It sends **our** `install_proxmox.sh` over scp instead of letting the VM clone
the repository: it is our code we want to exercise, and the remote is often
behind the checkout — a fix absent from the remote made the same defect "come
back" on three VMs in a row.

### The resource algorithm — sized from the bottom up

The first version handed down whatever the parent could spare, and a real
descent showed what that costs. Level 4 ended up with 44 GB of memory and
2 vCPU **on a host that had 2** — a hundred percent overcommit, at every
level, with the hypervisor itself to serve on top. Its install ran past two
and a half hours against thirteen minutes for level 3, and extrapolating that
ratio gave five years for the tenth.

So the direction is reversed for **memory and disk**. The deepest level gets
what a test Proxmox actually asks for — 4 GB of memory, 25 GB of disk — and
every parent above it adds its own overhead and nothing else: 2 GiB and 10 GB.
A ten-level descent therefore asks its first level for 22 GB and 115 GB, where
handing resources down wanted 50 GB of memory for the same depth. The
processor follows a different rule; see below.

Three budgets can bound the depth, and `script/proxmox/nesting.py` names the
one that ran out:

* **memory** — every level must run its own daemons (`pve-cluster`,
  `pvestatd`, `pvedaemon`, `pveproxy`) *and* hold its child;
* **disk** — the child's disk lives *inside* the parent's, which must also
  hold its own system;
* **processor** — it does *not* grow with depth. Every nested level keeps a
  fixed, narrow width; only the first level counts against the physical cores.
  Either the machine can carry that first level or it can carry nothing.

That third rule is measured, and it cost two descents to get right. A nested
guest at the **fourth** level freezes in early boot as soon as it is wide:
twelve vCPU the first time, eight the second — same instruction pointer at
three readings five minutes apart, 32 MiB read and not one byte more for 106
minutes. Two vCPU boots.

The first freeze was blamed on **overcommit**: that VM had twelve vCPU on a
host with two. The second measurement refuted it — eight vCPU on a parent with
**nine**, load 1.47, no overcommit at all, and the same freeze. It is the
nested guest's vCPU count, not its ratio to its host's.

At the third level, 9 vCPU boots in 117 s. The threshold sits between the
third and fourth level, so no nested level is ever made wide. An earlier
version of this algorithm gave each parent one vCPU more than its child, which
made level 4 eight wide — exactly the frozen case. The rule made wide what
must stay narrow.

Hence three fixed widths: `VCPU_METAL` for level 1 (on bare metal, no freeze
risk — eleven vCPU booted there in 42 s), `VCPU_IMBRIQUE` for the deepest, and
`VCPU_INTERMEDIAIRE` in between, wide enough to host its child without being
as narrow as it. That middle number is a **hypothesis**: two is proven to boot
at the fourth level and eight is proven to freeze, with nothing measured in
between. The descent decides.

Memory is not the lever. On that same manual VM, dropping it from 9 GB to 2 GB
moved nothing — it stopped after reading the same 32 MiB, which is simply the
size of the boot files.

The plan is printed **before** anything is created, and the script never
promises a depth it knows will not fit — better to announce six levels and
reach six than to promise ten and die at the seventh without knowing why.

## deep_qemu.py — how deep does QEMU-in-QEMU go?

The same descent, a different stack — and the pair is the point. The fourth
level's slowdown comes from the **processor**: what a VM exit costs under
nested paging. The per-level *cost*, though, comes from what you install. A
Proxmox node lays down a kernel, corosync, ceph and a web UI; a libvirt host
lays down `libvirtd` and `qemu-kvm`. Measured together, the two separate what
is due to the hardware from what is due to the stack — two things the Proxmox
measurement alone confounds.

### What this test must prove before it measures anything

`deploy_qemu.py` never passes `--cpu host-passthrough`, and when `/dev/kvm` is
missing it does **not** fail: it sets `--virt-type qemu`, warns on one line,
and creates a fully **emulated** VM. Seven and a half minutes to boot, and no
exit code says so.

Unguarded, this script would measure stacked TCG while believing it measured
nesting — and return a more flattering number that means nothing. So every
level must prove, not assume:

* `/dev/kvm` is readable;
* `/sys/module/kvm_amd|kvm_intel/parameters/nested` reads `Y`;
* the child's domain is `<domain type='kvm'>`, checked right after creation.

**What was not read counts as NO.** An absent `/sys/module` file means an
unloaded module, not a permissions problem. A level that fails these stops the
descent instead of prolonging it into the void.

## Starting from a host you already have

Both scripts take `--hote`. Creating a head VM to host a hypervisor you
already own costs five minutes *and* one level of nesting — that is, slowness,
which is the very thing being measured.

```
./long_test/deep_proxmox.py --hote root@203.0.113.5      # an existing Proxmox
./long_test/deep_qemu.py --hote erplibre@203.0.113.7     # an existing libvirt host
```

Three things follow, and they are not decorative:

* the plan is sized on the **root**, read over ssh — sizing it on the local
  machine while the levels live elsewhere would announce levels that do not
  fit;
* the delays count **absolute** depth: a level-1 child placed in a root that
  is already at the third level is really at the fourth;
* the root is **never** a level reached, and **never** destroyed. A borrowed
  host has no local libvirt UUID, so `--detruire` refuses to fall back on its
  name — `virsh undefine --remove-all-storage` erases a disk for good.

The menu offers the host already chosen without searching for it, and undoes
each stack separately: they share the report directory, but each knows only
its own reports.
