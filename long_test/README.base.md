<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# long_test — tests that create real machines

These are not unit tests. They create virtual machines, install systems on
them, and take hours. They live here and **not** in `test/`, which the unit
runner sweeps: `./script/test/run_unit_test.sh` must stay runnable in seconds
on any machine, including one without virtualisation.

The two depth descents run from the menu — `TODO › Execute › Test ›
Long tests`. The two confrontations run **directly**: the menu does not
carry them, and one of them cuts this machine's network.

## lima_confront.py — the backend nobody has ever run

The Lima backend was written with no machine to test it on. Its unit tests
hold what it COMPOSES and what it PARSES, not what `limactl` does with any of
it. It therefore declares itself unproven, and this script is what will lift
that mention — not a code review.

Four questions, none deducible from the code: which SHAPE the inventory
answers in, whether it carries anything that could PROVE an identity, whether
a compound command really survives the exec channel, and whether the rendered
configuration actually starts.

It exits 20 — dependency absent — where `limactl` is not installed.

```
./long_test/lima_confront.py              # the four questions
./long_test/lima_confront.py --dry-run    # what it would do, nothing done
./long_test/lima_confront.py --detruire   # remove the trial instance
```

## egress_confront.py — the forward chain nobody has ever tried

The egress rules are tested on what they COMPOSE, and real `nft` accepts the
rendered file. None of that says the FORWARD chain catches what a container
emits: a lock hooked to the host's own output lets container traffic straight
through, and the rules read as complete while data leaves by the window.

Three questions: whether a NAMED destination is reachable from inside a
container, whether one OUTSIDE the list is refused, and whether that refusal
survives a restart of the container engine — which writes its own rules on
start-up.

**The ground is a disposable Lima instance**, and that is the default. The
ruleset loads with `policy drop` on output and forward into the tables of
whatever machine hosts it: on the host, an ssh session drops with everything
else, including the one reading the output. The instance carries all of it,
the host risks nothing, and `--detruire` removes it.

`--terrain hote` keeps the older way, for a machine already decided to be
disposable. It asks for a typed `OUI` before loading, and **that refusal stops
the trial**: with no rules, the probes measure an ordinary machine and answer
« passes » twice, which reads as a conclusive confrontation. `--dry-run`
renders the file and loads nothing.

**What made it inconclusive was the trial, not the chain.** It aimed at two
documentation addresses, and neither answers: both probes returned the same
exhausted timeout. Two listeners now ANSWER, alike but for their address, on a
network separate from the prober's so the traffic crosses forward. The verdict
is then a DIFFERENCE, and it reads without interpretation.

The exit codes, and the vocabulary is closed: `0` the trial went all the way,
`20` the tooling is missing and nothing was attempted, `30` something stopped
it before it measured — a refusal to load, listeners that do not answer.
Confusing `0` and `30` would read « conclusive » over a trial that confronted
nothing.

```
./long_test/egress_confront.py                  # inside a Lima instance
./long_test/egress_confront.py --terrain hote   # HERE, and it cuts egress
./long_test/egress_confront.py --dry-run        # what it would do
./long_test/egress_confront.py --detruire       # remove the ground
```

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

## qemu_cache.py — does the download cache really serve the second VM?

Two sibling VMs, the same distribution, the same packages. The first fills the
cache, the second must be served by it.

**Zero upstream bytes is the headline, not the criterion.** Arch is a rolling
release: between the two deployments a mirror can publish a newer version,
which the second VM legitimately fetches — the cache never serves an index
while upstream answers, so the VM sees it. A criterion built on volume alone
would call the cache broken while it works.

The criterion is therefore: **no URL requested by BOTH VMs is fetched upstream
a second time.** What the second VM discovers on its own is counted, shown,
and does not fail.

`--hors-ligne` adds the counter-proof, which is what makes the test worth its
hours: it cuts the upstream of the cache SERVICE alone — by its system
account, not by a blanket rule that would take down the ssh session running
the test — and deploys a third VM, which must build from the stored index.

```
./long_test/qemu_cache.py                 # two VMs
./long_test/qemu_cache.py --dry-run       # the plan, nothing created
./long_test/qemu_cache.py --hors-ligne    # + the third VM, upstream cut
./long_test/qemu_cache.py --detruire      # undo it
```

It needs the cache installed and running — `TODO › Deployment › QEMU cache` —
and it refuses to create anything before saying which prerequisite is missing.
Among those prerequisites: the rules must target the subnet libvirt actually
serves, which is not always 192.168.122.0/24.

What governs the duration is the FIRST VM's download, everything else being
boot and install: minutes on a machine with nested KVM and a nearby mirror,
much longer on a slow link. The second VM does not download at all — that is
what is being measured.

One limit the counter-proof exposes: with upstream cut, the repository
database SIGNATURES are missing from the cache, the mirror answering 404 for
them, so the cache returns its named 504. pacman treats them as optional and
carries on. A distribution that required them would stop there.
## install_nixos.py — ERPLibre s'installe-t-il sur NixOS ?

Not a depth: one machine, one binary question. The other two measure how far
nesting goes; this one asks whether the path the menu takes reaches the end on
a **declarative** system, where nothing is installed one command at a time.

It sends the menu's own remote command, `_qemu_erplibre_remote_cmd`, taken as
it is. A test that installed by its own means would prove *its* path, not the
product's — and that is exactly where the failures hid: a bootstrap with no
nix branch, a Makefile assuming `/bin/bash`, compile paths read from a session
older than the module it had just applied.

The block goes in **one** ssh session, as the deployment does. That is the
condition that exposes the first-pass failure: the session opens before
`make install_os` applies the module, so before `pam_env` sets `CPATH`, and
the packages with no upstream wheel stopped there. Replaying the install in a
fresh session succeeds and proves the wrong thing.

The verdict is the **state of the machine**, not a return code:
`nixos-rebuild switch` returns 4 on a system that is nonetheless activated,
and every tool block of the menu returns 0 by construction. So it checks what
`envfs` makes (`/bin/bash`, `/usr/bin/env`, `/usr/bin/python3.x`), the venv,
the four modules that have no wheel and must compile — psycopg2, python-ldap,
pycups, mysqlclient — the absence of the HTML manuals, and Odoo answering.

```
./long_test/install_nixos.py                 # create the VM, install, judge
./long_test/install_nixos.py --dry-run       # the plan and the commands
./long_test/install_nixos.py --hote nixos-1  # on a machine you already have
./long_test/install_nixos.py --detruire      # undo it
```

`--hote` expects a machine that **already runs NixOS**: the script installs
ERPLibre there, it does not install the system.

It clones from the **published** repository, on the branch asked for
(`develop` by default). That is deliberate — the test measures what a user
receives, not what a local checkout holds. Say it before running: a fix still
on an unmerged branch is *not* in the VM, and the test will fail on whatever
that fix repairs.

## setops_banc.py — does the engine hold on a disposable cluster?

The Set-OPS engine is driven from TODO's menu, and its gestures are guarded
there. Nothing says they hold against a real cluster, from the golden template
to the razing.

**The terrain is named, not guessed.** `deep_proxmox.py` serves development; the
real case is a cluster one owns. The bench takes a terrain as an argument so the
same trial serves the rehearsal and then the real case — and it touches no lab:
it lays down ITS bridge and ITS API user, and modifies neither.

**One floor is enough**, and the shallowest is the right one: a nested Proxmox
is a Proxmox, and each floor deeper runs 15 to 30 times slower. The bench tries
the engine, not the nesting.

**Two repositories, not one.** The engine reaches its cluster through the vault
of an UNDERLAY, at the hoster, and refuses without the link that names it — so a
bench with a single repository cannot materialise a VM. The bench lays down a
sibling pair, `SITE-…` for the fabric and `OPS-…` for the plan, and mounts both
through the two links the engine reads BY THEIR PATH — its playbook looks at
neither `SETOPS_UNDERLAY` nor `SETOPS_INSTANCE`. It refuses if either name is
already taken, a dangling link included: that link is an operator's, and
replacing it would aim their next gesture at the bench's ecosystem, whose razing
destroys everything the inventory names. It also poses one vault key per
repository, and undoes both LAST: a key opens the vault that carries the token,
and the token is what joins the cluster.

**The plan is activated surgically.** The shipped model declares every server
`planifie`, and the inventory files as active only what says exactly `actif` — a
plan copied without that flip yields an inventory with no active host, and the
materialising and the razing then both exit zero having done nothing, which
reads as a success. The bench flips one attribute of one line and renders the
rest of the file as it stands, comments included.

**Two passes, and they do not prove the same thing.** The first carries the token
through the ENVIRONMENT, which the engine's playbook accepts as a fallback: it
validates the CLUSTER. The second seals it in the bench ecosystem's vault and
replays the loop through TODO's own doors: it validates TODO'S PATH, whose
runner deliberately passes no `PROXMOX_*`.

Exit codes, and the vocabulary is closed: `0` the trial went all the way, `20`
the tooling is missing and nothing was attempted, `30` something stopped it
before it measured.

**What is posed today are the DECISIONS, and they are all guarded** —
prerequisites said before anything is created, the terrain, a free bridge, the
shape of the token, the order of the undoing, the footprint. The verbs that
create need a cluster to be proven, so a real run refuses and says so rather
than running code nothing has checked.

The menu of long trials offers it too, and the confirmation comes from the
same place as the others: the plan asks nothing, since it creates nothing, and a
prompt one learns to confirm without reading protects nothing the day it counts.
The terrain can be NAMED there — the bench deduces the last floor the lab laid,
which serves the rehearsal, while a cluster one owns is designated.

```
./long_test/setops_banc.py --dry-run          # the plan, nothing created
./long_test/setops_banc.py --detruire         # undo what was laid down
./long_test/setops_banc.py --terrain <alias>  # a cluster one owns
./long_test/setops_banc.py --passe env        # token through the environment
```

**The token's secret crosses memory only.** The cluster shows it once, at
creation, and never again. It goes to two places — the environment of a gesture,
or the tool that encrypts it, reached through standard input — and to nothing
else: written in clear and encrypted afterwards, it would stay in the freed
blocks and in any backup taken between the two gestures. Anything the bench
prints or logs is redacted first, and the command line never carries it, since a
command line is readable in the machine's process table by any account.

**A vlan-aware bridge separates, it does not route.** The tenant's hosts come up
with a tagged NIC in a broadcast domain where no address answers: their gateway
stays mute, they reach only their neighbours under the same tag, and the failure
looks like a firewall. So the bench poses one ROUTED interface per zone, and it
does not compute which — the engine derives each zone's tag and gateway from the
plan's single index, and the bench reads them from the GENERATED inventory. A
second derivation written in the bench would diverge the day the engine's rule
changes, and the bench would then route domains where nobody lives. A host
missing one of the three values refuses the whole read: routing one zone out of
two leaves half the fleet unreachable, and nothing in the inventory says which.

**The golden template is required after the pose, and the bench does not make
it.** The engine's procedure installs it from the ISO on purpose: `genericcloud` ships
configured for the legacy PCI chipset, and converting it afterwards does not
change a setting — it replaces the virtual hardware under a system that believes
it knows its own. Predictable interface names derive from the PCI path, so the
machine loses its network; disk paths move; each of the failures that follow
looks like something other than its cause. A machine is born `q35` or it will
never be so cleanly. The bench therefore MEASURES: is a VM of the declared name
there, is it converted to a template, and does it carry the hardware the
procedure requires — the very check the procedure calls "the last moment when the
correction is free". A missing key counts as non-conforming, because the
configuration only prints what differs from the default and the defaults are
exactly what the procedure refuses. Every refusal names the procedure, since the
bench does not make the template and must say where its making is described.

It is required AFTER the site is posed, and not among the prerequisites,
because the template is an artefact OF the site: the preparation the engine
applies to it demands an artefact server and a resolver that the SITE's plan
declares, and the site exists only once posed. Requiring it first would refuse
on the opening round what only that round makes possible. The state is READ
again on the cluster at that point, never carried over from a measure taken
before the pose — in between, the operator may have built it. A refusal there
leaves the pose standing, which `--detruire` takes back, and answers "not
conclusive" rather than "nothing was attempted": the loop is what did not run.

The tenant's placement — the file the cloning reads to know WHERE it lands —
names the template's VMID, so it is written at that same moment. A VMID taken
from anywhere else, the first FREE one of the range for instance, is free
PRECISELY because the template occupies the one before it; the engine then
refuses on "no node holds the template", and nothing says the number came
from there.

**The terrain is reached as an ordinary account, and that decides everything.**
A hypervisor's tools live in `/usr/sbin`, which a non-interactive ssh session's
PATH does not carry, and its cluster daemon only talks to root. Played without
elevation, a command does not say "refused": it says "command not found", or
complains about its communication channel — a diagnosis that sends you looking
for a broken daemon where there is only an account without rights. The bench
measures once whether the session is already root and whether `sudo` answers
WITHOUT a password: a session with no terminal cannot type one, and an
interactive sudo does not fail, it WAITS until the deadline. Every command then
carries that decision, and the executor refuses to run anything without one.

**The loop is the engine's own, not a recomposition of its pieces.**
`reconstruire` chains the flows, the fleet's creation, the wait, the socle's
bootstrap and then the layered deployment. The order matters there: without the
flows FIRST, the derived-rules directory is empty and the socle lays a firewall
that denies by default WITH NO RULE AT ALL — the fleet comes up, ssh answers
from administration, and everything else is a wall, a failure that shows up
neither at creation nor in an exit code. So the bench calls the target and reads
its verdict; it does not re-sequence the steps, which is how it would drop that
one the day the engine adds another.

**The fleet lives behind the terrain, so the bench hands ssh the jump.** The
fleet's addresses are those of the internal network the bench laid, and the
station does not route to them: the wait that pings the fleet would run its
whole deadline and then call it unreachable, while it answers and the terrain
reaches it. The jump goes into `ANSIBLE_SSH_ARGS`, APPENDED to the `ssh_args`
the engine's own configuration declares — read there, never copied here, since
posting the jump alone drops the engine's key-only restriction and a host that
asked for a password would hold the deadline instead of failing at once.

The bootstrap derives ITS hosts from the plan — the certificate authority first,
then what enrols with it — so the bench reads that list instead of writing one.
Two hosts of the shipped model are therefore activated, and the rest of the fleet
stays planned: `reconstruire` only creates the VMs of ACTIVE hosts.

The plan announces what each step costs, and **says when a duration is only
announced**: ~30 s for the bridge, ~10 s for the token, ~10 min for the golden
template, then per pass ~5 s for each of the two inventory gestures — both
measured — and, still to be timed, ~45 min for the reconstruction and ~2 min for
the razing. A plan that gave both in the same tone would promise a time nobody
has clocked.

## Starting from a host you already have

The three scripts take `--hote`. Creating a head VM to host a hypervisor you
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

<!-- [fr] -->
# long_test — des tests qui créent de vraies machines

Ce ne sont pas des tests unitaires. Ils créent des machines virtuelles, y
installent des systèmes, et durent des heures. Ils vivent ici et **non** dans
`test/`, que le lanceur unitaire balaie : `./script/test/run_unit_test.sh`
doit rester lançable en quelques secondes, sur n'importe quelle machine, y
compris sans virtualisation.

Les deux descentes se lancent depuis le menu — `TODO › Execute › Test ›
Tests longs`. Les deux confrontations se lancent **directement** : le menu
ne les porte pas, et l'une d'elles coupe le réseau de cette machine.

## lima_confront.py — le backend que personne n'a jamais lancé

Le backend Lima a été écrit sans machine pour l'éprouver. Ses tests unitaires
tiennent ce qu'il COMPOSE et ce qu'il ANALYSE, pas ce que « limactl » en fait.
Il se déclare donc non éprouvé, et ce script est ce qui lèvera la mention —
pas une relecture.

Quatre questions dont aucune ne se déduit du code : sous quelle FORME
l'inventaire répond, s'il porte de quoi PROUVER une identité, si une suite de
commandes traverse vraiment le canal d'exec, et si la configuration rendue
démarre.

Il rend 20 — dépendance absente — là où « limactl » n'est pas installé.

```
./long_test/lima_confront.py              # les quatre questions
./long_test/lima_confront.py --dry-run    # ce qui serait fait, rien de fait
./long_test/lima_confront.py --detruire   # retirer l'instance d'essai
```

## egress_confront.py — la chaîne forward que personne n'a jamais tentée

Les règles de sortie sont éprouvées sur ce qu'elles COMPOSENT, et le vrai
`nft` accepte le fichier rendu. Rien de cela ne dit que la chaîne FORWARD
attrape ce qu'un conteneur émet : un verrou accroché à la sortie de l'hôte
laisse passer le trafic d'un conteneur, et les règles affichent complet
pendant que la donnée sort par la fenêtre.

Trois questions : une destination NOMMÉE est-elle joignable depuis un
conteneur, une destination HORS LISTE est-elle refusée, et ce refus survit-il
au redémarrage du moteur de conteneurs — qui écrit ses propres règles à son
démarrage.

**Le terrain est une instance Lima jetable**, et c'est le défaut. Le jeu de
règles se charge en `policy drop` sur output et forward dans les tables de la
machine qui l'accueille : sur l'hôte, une session ssh tombe avec le reste, y
compris celle qui lit la sortie. L'instance porte donc tout, l'hôte ne risque
rien, et `--detruire` la retire.

`--terrain hote` garde l'ancienne voie, pour une machine dont on a décidé
qu'elle est jetable. Elle demande un `OUI` tapé avant de charger, et **ce
refus arrête l'épreuve** : sans règles, les sondes mesurent une machine
ordinaire et rendent deux fois « passe », ce qui se lit comme une
confrontation concluante. `--dry-run` rend le fichier et ne charge rien.

**Ce qui la rendait non concluante était l'épreuve, pas la chaîne.** Elle
visait deux adresses de documentation, et ni l'une ni l'autre ne répond : les
deux sondes rendaient le même délai épuisé. Deux écouteurs RÉPONDENT
maintenant, à un adressage près identiques, sur un réseau séparé de celui du
sondeur pour que le trafic traverse forward. Le verdict est alors une
DIFFÉRENCE, qui se lit sans interprétation.

Les sorties, et le vocabulaire est clos : `0` l'épreuve est allée au bout,
`20` l'outillage manque et rien n'a été tenté, `30` quelque chose l'a arrêtée
avant qu'elle mesure — un refus de charger, des témoins qui ne répondent pas.
Confondre `0` et `30` ferait lire « concluant » sur une épreuve qui n'a rien
confronté.

```
./long_test/egress_confront.py                  # dans une instance Lima
./long_test/egress_confront.py --terrain hote   # ICI, et ça coupe la sortie
./long_test/egress_confront.py --dry-run        # ce qui serait fait
./long_test/egress_confront.py --detruire       # retirer le terrain
```

## deep_proxmox.py — jusqu'à quel étage un Proxmox dans un Proxmox tient-il ?

La profondeur d'imbrication praticable ne se déduit pas, elle se mesure — et
une mesure n'est pas une mesure.

Un examen à la main d'UNE VM du quatrième étage a trouvé un invité **36 fois
plus lent que le temps réel** (583 secondes d'horloge pour 16 secondes de
temps invité, chaque ligne d'ACPI prenant une seconde), puis un noyau gelé :
même RIP à trois relevés deux minutes d'écart, et **pas un octet écrit** sur
le disque.

Lancer ce script a **réfuté la conclusion qu'on en avait tirée**. Sa propre VM
du quatrième étage — 2 vCPU là où celle de la main en avait 12 — a démarré,
s'est installée, et a écrit des gigaoctets. Ce qui ressemblait à un plafond
d'imbrication était un plafond de *parallélisme* sous imbrication. C'est
précisément ce que l'algorithme borne, et c'est ainsi qu'il a cessé d'être une
supposition.

D'où le script : un chiffre obtenu une fois, sur une machine, dans une chaîne,
est une anecdote.

```
./long_test/deep_proxmox.py                        # trois étages, ~30 minutes
./long_test/deep_proxmox.py --dry-run              # le plan, rien de créé
./long_test/deep_proxmox.py --depth 5              # en demander plus, sciemment
./long_test/deep_proxmox.py --detruire             # défaire
```

### Quelle profondeur vaut la peine d'être demandée

La profondeur est le seul réglage, et **trois** est le défaut parce que trois
marche. Mesuré sur une machine à 28 cœurs, une descente complète par ligne :

| étage | amorçage (ssh) | installation | total |
|------:|---------------:|-------------:|------:|
| 1 | 0 s | 200 s | 280 s |
| 2 | 37 s | 344 s | 495 s |
| 3 | 93 s | 777 s | 1 064 s |
| 4 | **15 608 s** | **26 306 s** | n'a pas abouti |

Trois étages coûtent une demi-heure. Le **quatrième** a coûté 4 h 20
d'amorçage et 7 h 18 d'installation sur la même machine — tout y est 15 à 30
fois plus lent, pas une seule étape. Et cela tombe précisément là où les
fabricants s'arrêtent : le quatrième étage est le *troisième* hyperviseur
imbriqué, et AMD en documente deux.

Un invité plus large aggrave brutalement : au quatrième étage, un vCPU de plus
a multiplié l'amorçage par 9,4 (1 664 s à deux vCPU, 15 608 s à trois), et à
huit vCPU l'invité a lu 32 Mio en 106 minutes, pointeur d'instruction
immobile. Aux étages 2 et 3, ce même vCPU ne coûte rien.

Donc : trois par défaut, cinq pour savoir, dix seulement pour voir le mur.

La descente est **uniforme**. Chaque étage, le premier compris, passe par les
mêmes six étapes : créer, attendre le ssh, installer Proxmox, redémarrer et
vérifier le noyau, remettre pmxcfs debout, contrôler le stockage. Seule la
création diffère — libvirt en local, `qm` ensuite.

Il envoie **notre** `install_proxmox.sh` par scp au lieu de laisser la VM
cloner le dépôt : c'est notre code qu'on veut éprouver, et le dépôt distant
est souvent en retard sur le checkout — un correctif absent du distant a fait
« revenir » le même défaut sur trois VM de suite.

### L'algorithme de ressources — dimensionné depuis le bas

La première version cédait à l'enfant ce que le parent pouvait céder, et une
descente réelle a montré ce que cela coûte. L'étage 4 se retrouvait avec 44 Go
de mémoire et 2 vCPU **sur un hôte qui en avait 2** — cent pour cent de
surengagement, à chaque étage, avec l'hyperviseur lui-même à servir par-dessus.
Son installation dépassait deux heures et demie contre treize minutes pour
l'étage 3, et l'extrapolation de ce rapport donnait cinq ANS pour le dixième.

Le sens est donc inversé pour la **mémoire et le disque**. Le plus profond
reçoit ce qu'un Proxmox de test demande vraiment — 4 Go de mémoire, 25 Go de
disque — et chaque parent au-dessus ajoute son propre surcoût, rien d'autre :
2 Gio et 10 Go. Une descente à dix étages demande ainsi 22 Go et 115 Go à son
premier étage, là où la cession de haut en bas voulait 50 Go de mémoire pour la
même profondeur. Le processeur, lui, suit une autre règle — voir plus bas.

Trois budgets peuvent borner la profondeur, et `script/proxmox/nesting.py`
nomme celui qui a manqué :

* **la mémoire** — chaque étage doit faire tourner ses propres démons
  (`pve-cluster`, `pvestatd`, `pvedaemon`, `pveproxy`) *et* héberger son
  enfant ;
* **le disque** — le disque de l'enfant vit *dans* celui du parent, qui doit
  aussi contenir son propre système ;
* **le processeur** — il ne croît *pas* avec la profondeur. Tout étage
  imbriqué garde une largeur fixe et étroite ; seul le premier compte sur les
  cœurs physiques. Ou la machine peut porter ce premier étage, ou elle ne peut
  rien.

Cette troisième règle est mesurée, et il a fallu deux descentes pour la poser
juste. Un invité imbriqué au **quatrième** étage gèle en tout début de
démarrage dès qu'il est large : douze vCPU la première fois, huit la seconde —
même pointeur d'instruction à trois relevés espacés de cinq minutes, 32 Mio lus
et plus un octet pendant 106 minutes. Deux vCPU démarrent.

Le premier gel avait été imputé au **surengagement** : cette VM à douze vCPU
tournait sur un hôte qui en avait deux. La seconde mesure l'a réfuté — huit
vCPU sur un parent qui en avait **neuf**, charge 1,47, aucun surengagement, et
le même gel. C'est le nombre de vCPU de l'invité imbriqué, et non son rapport à
celui de son hôte.

Au troisième étage, 9 vCPU démarrent en 117 s. Le seuil est entre le troisième
et le quatrième étage : aucun étage imbriqué n'est donc rendu large. Une version
précédente de cet algorithme donnait un vCPU de plus à chaque parent, ce qui
rendait l'étage 4 large de huit — exactement le cas gelé. La règle rendait large
ce qui doit rester étroit.

D'où trois largeurs fixes : `VCPU_METAL` pour l'étage 1 (sur le métal, aucun
risque de gel — onze vCPU y ont démarré en 42 s), `VCPU_IMBRIQUE` pour le plus
profond, et `VCPU_INTERMEDIAIRE` entre les deux, juste assez large pour héberger
son enfant sans être aussi étroit que lui. Ce nombre du milieu est une
**hypothèse** : deux démarre au quatrième étage, huit gèle, et rien n'est mesuré
entre les deux. C'est la descente qui tranche.

La mémoire n'est pas le levier. Sur cette même VM examinée à la main, la faire
passer de 9 Go à 2 Go n'a rien déplacé : elle s'arrêtait après avoir lu les
mêmes 32 Mio, c'est-à-dire simplement la taille des fichiers d'amorçage.

Le plan est affiché **avant** que quoi que ce soit ne soit créé, et le script
ne promet jamais une profondeur qu'il sait irréalisable — mieux vaut annoncer
six étages et en réussir six que d'en promettre dix et mourir au septième sans
savoir pourquoi.

## deep_qemu.py — jusqu'à quel étage une QEMU dans une QEMU tient-elle ?

La même descente, une autre pile — et c'est le couple qui compte. Le
ralentissement du quatrième étage vient du **processeur** : de ce que coûte une
sortie de VM sous pagination imbriquée. Le *coût* par étage, lui, vient de ce
qu'on installe. Un nœud Proxmox pose un noyau, corosync, ceph et une interface
web ; un hôte libvirt pose `libvirtd` et `qemu-kvm`. Mesurées ensemble, les
deux séparent ce qui tient au matériel de ce qui tient à la pile — deux choses
que la seule mesure Proxmox confond.

### Ce que ce test doit prouver avant de mesurer quoi que ce soit

`deploy_qemu.py` ne passe jamais `--cpu host-passthrough`, et quand
`/dev/kvm` manque il n'échoue **pas** : il pose `--virt-type qemu`, avertit sur
une ligne, et crée une VM entièrement **émulée**. Sept minutes et demie de
démarrage, et aucun code de retour ne le dit.

Sans garde, ce script mesurerait de la TCG empilée en croyant mesurer de
l'imbrication — et rendrait un chiffre plus flatteur qui ne veut rien dire.
Chaque étage doit donc prouver, et non supposer :

* `/dev/kvm` est lisible ;
* `/sys/module/kvm_amd|kvm_intel/parameters/nested` vaut `Y` ;
* le domaine de l'enfant est `<domain type='kvm'>`, vérifié juste après sa
  création.

**Ce qui n'a pas été lu vaut NON.** Un fichier `/sys/module` absent, c'est un
module non chargé, pas un problème de permission. Un étage qui échoue à cela
arrête la descente au lieu de la prolonger dans le vide.

## qemu_cache.py — le cache de téléchargement sert-il vraiment la seconde VM ?

Deux machines sœurs, la même distribution, les mêmes paquets. La première
remplit le cache, la seconde doit être servie par lui.

**« Zéro octet d'amont » est la manchette, pas le critère.** Arch est une
publication continue : entre les deux déploiements, un miroir peut publier une
version neuve, que la seconde VM tire légitimement — le cache ne sert jamais
un index tant que l'amont répond, donc elle la voit. Un critère fondé sur le
seul volume déclarerait le cache en panne alors qu'il fonctionne.

Le critère est donc : **aucune URL demandée par les DEUX VM n'est retirée de
l'amont une seconde fois.** Ce que la seconde découvre seule est compté,
montré, et n'échoue pas.

« --hors-ligne » ajoute la contre-épreuve, qui fait la valeur de ces heures :
elle coupe l'amont du SEUL service du cache — par son compte système, non par
une règle générale qui emporterait la session ssh depuis laquelle le test se
lance — et déploie une troisième VM, qui doit se bâtir sur l'index stocké.

```
./long_test/qemu_cache.py                 # deux VM
./long_test/qemu_cache.py --dry-run       # le plan, rien de créé
./long_test/qemu_cache.py --hors-ligne    # + la troisième VM, amont coupé
./long_test/qemu_cache.py --detruire      # défaire
```

Il exige le cache installé et actif — « TODO › Déploiement › Cache QEMU » — et
refuse de rien créer avant d'avoir dit lequel des préalables manque. Parmi
eux : les règles doivent viser le sous-réseau que libvirt sert vraiment, qui
n'est pas toujours 192.168.122.0/24.

Ce qui gouverne la durée est le téléchargement de la PREMIÈRE VM, le reste
n'étant que démarrage et installation : quelques minutes sur une machine à
KVM imbriqué et miroir proche, bien davantage sur une liaison lente. La
seconde VM ne télécharge rien — c'est précisément ce qu'on mesure.

Une limite que la contre-épreuve met au jour : amont coupé, les SIGNATURES
des bases de dépôt manquent au cache, le miroir y répondant 404, et le cache
rend donc son 504 nommé. pacman les traite comme optionnelles et poursuit.
Une distribution qui les exigerait s'arrêterait là.
## install_nixos.py — ERPLibre s'installe-t-il sur NixOS ?

Pas une profondeur : une machine, une question binaire. Les deux autres
mesurent jusqu'où l'imbrication tient ; celui-ci demande si le chemin que le
menu emprunte aboutit sur un système **déclaratif**, où rien ne s'installe
commande par commande.

Il envoie la commande distante du menu, `_qemu_erplibre_remote_cmd`, prise
telle quelle. Un test qui installerait par ses propres soins prouverait *son*
chemin, pas celui du produit — et c'est justement là que se cachaient les
pannes : un amorçage sans branche nix, un Makefile qui présumait `/bin/bash`,
des chemins de compilation lus d'une session plus vieille que le module
qu'elle venait d'appliquer.

Le bloc part en **une** session ssh, comme le déploiement le fait. C'est la
condition qui expose la panne du premier passage : la session est ouverte
avant que `make install_os` n'applique le module, donc avant que `pam_env` ne
pose `CPATH`, et les paquets sans roue amont s'y arrêtaient. Rejouer
l'installation dans une session neuve réussit et donne raison à tort.

Le verdict est l'**état de la machine**, pas un code de retour :
`nixos-rebuild switch` rend 4 sur un système pourtant activé, et chaque bloc
d'outil du menu rend 0 par construction. On contrôle donc ce que fabrique
`envfs` (`/bin/bash`, `/usr/bin/env`, `/usr/bin/python3.x`), le venv, les
quatre modules sans roue qui doivent se compiler — psycopg2, python-ldap,
pycups, mysqlclient —, l'absence des manuels HTML, et Odoo qui répond.

```
./long_test/install_nixos.py                 # crée la VM, installe, juge
./long_test/install_nixos.py --dry-run       # le plan et les commandes
./long_test/install_nixos.py --hote nixos-1  # sur une machine qu'on a déjà
./long_test/install_nixos.py --detruire      # défaire ce qui a été posé
```

`--hote` attend une machine qui porte **déjà** NixOS : le script y installe
ERPLibre, il n'y installe pas le système.

Le clone vient du dépôt **publié**, sur la branche demandée (`develop` par
défaut). C'est voulu : le test mesure ce qu'un utilisateur reçoit, pas ce
qu'un checkout local contient. À dire avant de lancer : un correctif encore
sur une branche non fusionnée n'est *pas* dans la VM, et le test échouera sur
ce que ce correctif répare.

## setops_banc.py — le moteur tient-il sur une grappe jetable ?

Le moteur Set-OPS se pilote depuis le menu de TODO, et ses gestes y sont gardés.
Rien ne dit qu'ils tiennent contre une vraie grappe, du gabarit doré au rasage.

**Le terrain se désigne, il ne se devine pas.** `deep_proxmox.py` sert au
développement ; le cas réel est une grappe qu'on possède. Le banc prend un
terrain en argument, pour que la même épreuve serve à la répétition puis au cas
réel — et il ne touche à aucun labo : il pose SON pont et SON utilisateur d'API,
et n'en modifie aucun.

**Un seul étage suffit**, et c'est le moins profond : un Proxmox imbriqué est un
Proxmox, et chaque étage de plus tourne 15 à 30 fois plus lentement. Le banc
éprouve le moteur, pas l'imbrication.

**Deux dépôts, pas un.** Le moteur joint sa grappe par la voûte d'un UNDERLAY,
chez l'hébergeur, et refuse sans le lien qui le désigne : un banc à un seul
dépôt ne peut donc pas matérialiser de VM. Le banc pose une paire de dossiers
frères, `SITE-…` pour la fabric et `OPS-…` pour le plan, et monte les deux par
les liens que le moteur lit PAR LEUR CHEMIN — son playbook ne regarde ni
`SETOPS_UNDERLAY` ni `SETOPS_INSTANCE`. Il refuse si l'un des deux noms est déjà
pris, lien brisé compris : ce lien est celui d'un exploitant, et le remplacer
dirigerait son geste suivant vers l'écosystème du banc, dont le rasage détruit
tout ce que l'inventaire nomme. Il pose aussi une clé de voûte par dépôt, et les
défait EN DERNIER : une clé ouvre la voûte qui porte le jeton, et c'est le jeton
qui joint la grappe.

**Le plan s'active chirurgicalement.** Le modèle livré déclare tous ses serveurs
`planifie`, et l'inventaire ne range parmi les actifs que ce qui porte
exactement `actif` : un plan recopié sans la bascule produit un inventaire sans
aucun hôte actif, et la matérialisation comme le rasage sortent alors à zéro
sans avoir rien fait — ce qui se lit comme une réussite. Le banc bascule un
attribut d'une ligne et rend le reste du fichier tel quel, commentaires
compris.

**Deux passes, et elles ne prouvent pas la même chose.** La première porte le
jeton par l'ENVIRONNEMENT, ce que le playbook du moteur accepte en repli : elle
valide la GRAPPE. La seconde le chiffre dans la voûte de l'écosystème de banc et
rejoue la boucle par les portes de TODO : elle valide LE CHEMIN DE TODO, dont
l'exécuteur ne transmet exprès aucun `PROXMOX_*`.

Codes de sortie, et le vocabulaire est clos : `0` l'épreuve est allée au bout,
`20` l'outillage manque et rien n'a été tenté, `30` quelque chose l'a arrêtée
avant qu'elle mesure.

**Ce qui est posé aujourd'hui, ce sont les DÉCISIONS, et elles sont toutes
gardées** — préalables dits avant toute création, terrain, pont libre, forme du
jeton, ordre de la défaite, empreinte. Les verbes qui créent exigent une grappe
pour être prouvés : un lancement réel refuse en le disant, plutôt que d'exécuter
du code que rien n'a vérifié.

Le menu des épreuves longues le propose aussi, et la confirmation vient du
même endroit que pour les autres : le plan ne demande rien, puisqu'il ne crée
rien, et une invite qu'on apprend à confirmer sans lire ne protège plus rien le
jour où elle compte. Le terrain s'y NOMME — le banc déduit le dernier étage posé
par le labo, ce qui sert à la répétition, là où une grappe qu'on possède se
désigne.

```
./long_test/setops_banc.py --dry-run          # le plan, rien de créé
./long_test/setops_banc.py --detruire         # défaire ce qui a été posé
./long_test/setops_banc.py --terrain <alias>  # une grappe qu'on possède
./long_test/setops_banc.py --passe env        # jeton par l'environnement
```

**Le secret du jeton ne traverse que la mémoire.** La grappe ne l'affiche qu'une
fois, à sa création, et jamais plus. Il ne va qu'à deux endroits — l'environnement
d'un geste, ou l'outil qui le chiffre, atteint par l'entrée standard — et nulle
part ailleurs : écrit en clair puis chiffré, il resterait dans les blocs libérés
et dans toute sauvegarde prise entre les deux gestes. Ce que le banc affiche ou
journalise est expurgé d'abord, et la ligne de commande ne le porte jamais — une
ligne de commande se lit dans la table des processus, par n'importe quel compte.

**Un pont conscient des VLAN sépare, il ne route pas.** Les hôtes du locataire
démarrent avec une carte étiquetée dans un domaine de diffusion où aucune adresse
ne répond : leur passerelle reste muette, ils ne joignent que leurs voisines de
la même étiquette, et la panne ressemble à un pare-feu. Le banc pose donc une
interface ROUTÉE par zone, et il ne calcule pas lesquelles — le moteur dérive
l'étiquette et la passerelle de chaque zone du seul index du plan, et le banc les
LIT dans l'inventaire généré. Une seconde dérivation écrite dans le banc
divergerait de la sienne le jour où sa règle change, et le banc routerait alors
des domaines où personne n'habite. Un hôte à qui manque l'une des trois valeurs
fait refuser toute la lecture : router une zone sur deux laisse la moitié de la
flotte injoignable, et rien dans l'inventaire ne dit laquelle.

**Le gabarit doré est exigé après la pose, et le banc ne le fabrique pas.** La
procédure du moteur l'installe depuis l'ISO exprès : `genericcloud` est livrée
configurée pour le chipset PCI hérité, et la convertir après coup ne change pas
un réglage — elle remplace le matériel virtuel sous un système qui croit
connaître le sien. Les noms d'interfaces prédictibles dérivent du chemin PCI,
donc la machine perd son réseau ; les chemins de disques bougent ; et chacune des
pannes qui suivent ressemble à autre chose qu'à sa cause. Une machine naît `q35`
ou ne le sera jamais proprement. Le banc MESURE donc : une VM du nom déclaré
est-elle là, est-elle convertie en modèle, et porte-t-elle le matériel que la
procédure exige — la vérification même que la procédure appelle « le dernier
moment où la correction est gratuite ». Une clé absente compte comme non
conforme, la configuration n'imprimant que ce qui diffère du défaut et les
défauts étant justement ce que la procédure refuse. Chaque refus nomme la
procédure, le banc ne fabriquant pas le gabarit et devant dire où sa fabrication
est décrite.

Il est exigé APRÈS la pose du site, et non parmi les préalables, parce que le
gabarit est un artefact DU site : la préparation que le moteur lui applique
réclame un serveur d'artefacts et un résolveur que le plan du SITE déclare, et
le site n'existe qu'une fois posé. L'exiger avant refuserait au premier tour ce
que ce tour est seul à rendre possible. L'état est RELU sur la grappe à ce
moment-là, jamais repris d'une mesure d'avant-pose — entre les deux,
l'exploitant a pu le bâtir. Un refus y laisse la pose en place, que `--detruire`
reprend, et rend « non concluante » plutôt que « rien n'a été tenté » : c'est la
boucle qui n'a pas joué.

Le placement du locataire — le fichier que le clonage lit pour savoir OÙ il se
pose — nomme le VMID du gabarit, et s'écrit donc au même moment. Un VMID pris
ailleurs, le premier LIBRE de la plage par exemple, est libre PRÉCISÉMENT parce
que le gabarit occupe celui d'avant ; le moteur refuse alors sur « aucun nœud ne
détient le gabarit », et rien ne dit que le numéro venait de là.

**Le terrain se joint par un compte ordinaire, et cela décide de tout.** Les
outils d'un hyperviseur vivent dans `/usr/sbin`, que le PATH d'une session ssh
non interactive ne porte pas, et son démon de grappe ne parle qu'à root. Jouée
sans élévation, une commande ne dit pas « refusé » : elle dit « commande
introuvable », ou se plaint de son canal de communication — un diagnostic qui
envoie chercher un démon en panne là où il n'y a qu'un compte sans droits. Le
banc mesure une fois si la session est déjà root et si `sudo` répond SANS mot de
passe : une session sans terminal ne peut pas en taper un, et un sudo interactif
n'échoue pas, il ATTEND jusqu'à la borne. Chaque commande porte ensuite cette
décision, et l'exécuteur refuse de rien jouer sans elle.

**La boucle est celle du moteur, pas une recomposition de ses morceaux.**
`reconstruire` enchaîne les flux, la création de la flotte, l'attente,
l'amorçage du socle puis le déploiement par couches. L'ordre y compte : sans les
flux D'ABORD, le dossier des règles dérivées est vide et le socle pose un
pare-feu en refus par défaut SANS AUCUNE RÈGLE — la flotte monte, ssh répond
depuis l'administration, et tout le reste est mur, une panne qui ne se voit ni à
la création ni dans un code de retour. Le banc appelle donc la cible et lit son
verdict ; il ne réordonne pas les étapes, ce qui est la façon de laisser tomber
celle-là le jour où le moteur en ajoute une.

**La flotte vit derrière le terrain, donc le banc tend le saut à ssh.** Ses
adresses sont celles du réseau interne que le banc a posé, et la station n'y
route pas : l'attente qui interroge la flotte jouerait sa borne entière puis la
déclarerait injoignable, alors qu'elle répond et que le terrain la joint. Le
saut se pose dans `ANSIBLE_SSH_ARGS`, AJOUTÉ aux `ssh_args` que la configuration
du moteur déclare — lus chez lui, jamais recopiés ici, parce que poser le seul
saut perdrait sa restriction aux clés et qu'un hôte qui demanderait un mot de
passe tiendrait la borne au lieu d'échouer tout de suite.

L'amorçage dérive SES hôtes du plan — l'autorité de certification d'abord, puis
ce qui s'enrôle auprès d'elle — et le banc lit cette liste au lieu d'en écrire
une. Deux hôtes du modèle livré sont donc activés, et le reste de la flotte
demeure planifié : `reconstruire` ne crée que les VM des hôtes ACTIFS.

Le plan annonce ce que chaque étape coûte, et **dit quand une durée n'est
qu'annoncée** : ~30 s pour le pont, ~10 s pour le jeton, ~10 min pour le gabarit
doré, puis par passe ~5 s pour chacun des deux gestes d'inventaire — les deux
chronométrés — et, encore à relever, ~45 min pour la reconstruction et ~2 min
pour le rasage. Un plan qui donnerait les deux du même ton promettrait un temps
que personne n'a chronométré.

## Partir d'un hôte qu'on possède déjà

Les trois scripts acceptent `--hote`. Créer une VM de tête pour héberger un
hyperviseur qu'on a sous la main coûte cinq minutes *et* un étage
d'imbrication — donc de la lenteur, puisque c'est justement elle qu'on mesure.

```
./long_test/deep_proxmox.py --hote root@203.0.113.5      # un Proxmox existant
./long_test/deep_qemu.py --hote erplibre@203.0.113.7     # un hôte libvirt existant
```

Trois choses en découlent, et elles ne sont pas décoratives :

* le plan se dimensionne sur la **racine**, lue par ssh — le dimensionner sur
  la machine locale quand les étages vivent ailleurs annoncerait des étages qui
  ne tiennent pas ;
* les délais comptent la profondeur **absolue** : un enfant de niveau 1 posé
  dans une racine déjà au troisième étage est en réalité au quatrième ;
* la racine n'est **jamais** un étage atteint, et **jamais** détruite. Un hôte
  emprunté n'a pas d'UUID libvirt local, donc `--detruire` refuse de se rabattre
  sur son nom — `virsh undefine --remove-all-storage` efface un disque pour de
  bon.

Le menu propose l'hôte déjà retenu sans le rechercher, et défait chaque pile
séparément : elles partagent le dossier des rapports, mais chacune ne connaît
que les siens.
