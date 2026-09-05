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
./long_test/qemu_cache.py                 # two VMs, ~40 minutes
./long_test/qemu_cache.py --dry-run       # the plan, nothing created
./long_test/qemu_cache.py --hors-ligne    # + the third VM, upstream cut
./long_test/qemu_cache.py --detruire      # undo it
```

It needs the cache installed and running — `TODO › Deployment › QEMU cache` —
and it refuses to create anything before saying which prerequisite is missing.

## Starting from a host you already have

Both scripts take `--hote`. Creating a head VM to host a hypervisor you
already own costs five minutes *and* one level of nesting — that is, slowness,
which is the very thing being measured.

```
./long_test/deep_proxmox.py --hote root@10.0.0.5      # an existing Proxmox
./long_test/deep_qemu.py --hote erplibre@10.0.0.7     # an existing libvirt host
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
./long_test/qemu_cache.py                 # deux VM, ~40 minutes
./long_test/qemu_cache.py --dry-run       # le plan, rien de créé
./long_test/qemu_cache.py --hors-ligne    # + la troisième VM, amont coupé
./long_test/qemu_cache.py --detruire      # défaire
```

Il exige le cache installé et actif — « TODO › Déploiement › Cache QEMU » — et
refuse de rien créer avant d'avoir dit lequel des préalables manque.

## Partir d'un hôte qu'on possède déjà

Les deux scripts acceptent `--hote`. Créer une VM de tête pour héberger un
hyperviseur qu'on a sous la main coûte cinq minutes *et* un étage
d'imbrication — donc de la lenteur, puisque c'est justement elle qu'on mesure.

```
./long_test/deep_proxmox.py --hote root@10.0.0.5      # un Proxmox existant
./long_test/deep_qemu.py --hote erplibre@10.0.0.7     # un hôte libvirt existant
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
