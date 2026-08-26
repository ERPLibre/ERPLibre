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

La profondeur d'imbrication praticable ne se déduit pas, elle se mesure. Une
mesure à la main a trouvé, au quatrième étage, un invité **36 fois plus lent
que le temps réel** — 583 secondes d'horloge pour 16 secondes de temps
invité, chaque ligne d'ACPI prenant une seconde — puis un noyau invité gelé au
**même octet** quelles que soient les ressources. Un chiffre obtenu une fois,
sur une machine, n'est pas un chiffre : ce script le refait à la demande et
dit exactement où ça casse.

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

### L'algorithme de ressources

Deux choses s'épuisent en descendant, et une troisième se dégrade. Ce qui
s'épuise est de l'arithmétique, et `script/proxmox/nesting.py` la calcule :

* **la mémoire** — chaque étage garde de quoi faire tourner ses propres démons
  (`pve-cluster`, `pvestatd`, `pvedaemon`, `pveproxy`) avant de céder le
  reste ;
* **le disque** — le disque de l'enfant vit *dans* celui du parent, qui doit
  aussi contenir son propre système.

Ce qui se dégrade est mesuré, pas supposé : au-delà du deuxième étage, les
fabricants ne documentent rien. D'où un seul nombre borné — **2 vCPU** pour
tout étage imbriqué. Douze vCPU au quatrième étage ont gelé le noyau invité en
tout début de démarrage ; les mêmes deux avançaient. Amener douze processeurs
en ligne coûte autant d'allers-retours à travers toute la pile.

La mémoire n'est **pas** bornée : la même VM gelait au même octet avec 9 Go et
avec 2 Go, donc la rogner ne gagnerait rien et priverait l'étage du dessous.

Le plan est affiché **avant** que quoi que ce soit ne soit créé, et le script
ne promet jamais une profondeur qu'il sait irréalisable — mieux vaut annoncer
six étages et en réussir six que d'en promettre dix et mourir au septième sans
savoir pourquoi.
