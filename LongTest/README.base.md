<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
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

### The resource algorithm — sized from the bottom up

The first version handed down whatever the parent could spare, and a real
descent showed what that costs. Level 4 ended up with 44 GB of memory and
2 vCPU **on a host that had 2** — a hundred percent overcommit, at every
level, with the hypervisor itself to serve on top. Its install ran past two
and a half hours against thirteen minutes for level 3, and extrapolating that
ratio gave five years for the tenth.

So the direction is reversed. The deepest level gets what a test Proxmox
actually asks for — 4 GB of memory, 25 GB of disk, 2 vCPU — and every parent
above it adds its own overhead and nothing else: one vCPU, 2 GiB, 10 GB. A
ten-level descent therefore asks its first level for 11 vCPU, 22 GB and
115 GB, where handing resources down wanted 50 GB of memory for the same
depth.

Three budgets can bound the depth, and `script/proxmox/nesting.py` names the
one that ran out:

* **memory** — every level must run its own daemons (`pve-cluster`,
  `pvestatd`, `pvedaemon`, `pveproxy`) *and* hold its child;
* **disk** — the child's disk lives *inside* the parent's, which must also
  hold its own system;
* **processor** — each level wants one vCPU more than its child, so ten levels
  ask eleven of the first. Half the physical cores is the ceiling: the
  orchestrator runs on that machine too.

That third budget is measured, not assumed. Twelve vCPU at the fourth level
froze the guest kernel in early boot — same instruction pointer at three
readings two minutes apart — while two progressed. The number was not the
culprit: that VM had twelve vCPU on a host with two, six times wider than its
own machine. Overcommit freezes, not the twelve.

Memory is not the lever. On that same manual VM, dropping it from 9 GB to 2 GB
moved nothing — it stopped after reading the same 32 MiB, which is simply the
size of the boot files.

The plan is printed **before** anything is created, and the script never
promises a depth it knows will not fit — better to announce six levels and
reach six than to promise ten and die at the seventh without knowing why.

<!-- [fr] -->
# LongTest — des tests qui créent de vraies machines

Ce ne sont pas des tests unitaires. Ils créent des machines virtuelles, y
installent des systèmes, et durent des heures. Ils vivent ici et **non** dans
`test/`, que le lanceur unitaire balaie : `./script/test/run_unit_test.sh`
doit rester lançable en quelques secondes, sur n'importe quelle machine, y
compris sans virtualisation.

Ils se lancent depuis le menu — `TODO › Execute › Test › Tests longs` — ou
directement.

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
./LongTest/deep_proxmox.py --depth 10 --dry-run   # le plan, rien de créé
./LongTest/deep_proxmox.py --depth 10             # des heures
./LongTest/deep_proxmox.py --detruire             # défaire
```

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

Le sens est donc inversé. Le plus profond reçoit ce qu'un Proxmox de test
demande vraiment — 4 Go de mémoire, 25 Go de disque, 2 vCPU — et chaque parent
au-dessus ajoute son propre surcoût, rien d'autre : un vCPU, 2 Gio, 10 Go. Une
descente à dix étages demande ainsi 11 vCPU, 22 Go et 115 Go à son premier
étage, là où la cession de haut en bas voulait 50 Go de mémoire pour la même
profondeur.

Trois budgets peuvent borner la profondeur, et `script/proxmox/nesting.py`
nomme celui qui a manqué :

* **la mémoire** — chaque étage doit faire tourner ses propres démons
  (`pve-cluster`, `pvestatd`, `pvedaemon`, `pveproxy`) *et* héberger son
  enfant ;
* **le disque** — le disque de l'enfant vit *dans* celui du parent, qui doit
  aussi contenir son propre système ;
* **le processeur** — chaque étage en veut un de plus que son enfant, donc dix
  étages en demandent onze au premier. La moitié des cœurs physiques est le
  plafond : l'orchestrateur tourne sur cette machine lui aussi.

Ce troisième budget est mesuré, pas supposé. Douze vCPU au quatrième étage ont
gelé le noyau invité en tout début de démarrage — même pointeur d'instruction à
trois relevés, deux minutes d'écart — quand deux avançaient. Le nombre n'était
pas le fautif : cette VM avait douze vCPU sur un hôte qui en avait deux, six
fois plus large que sa propre machine. C'est le surengagement qui gèle, pas le
douze.

La mémoire n'est pas le levier. Sur cette même VM examinée à la main, la faire
passer de 9 Go à 2 Go n'a rien déplacé : elle s'arrêtait après avoir lu les
mêmes 32 Mio, c'est-à-dire simplement la taille des fichiers d'amorçage.

Le plan est affiché **avant** que quoi que ce soit ne soit créé, et le script
ne promet jamais une profondeur qu'il sait irréalisable — mieux vaut annoncer
six étages et en réussir six que d'en promettre dix et mourir au septième sans
savoir pourquoi.
