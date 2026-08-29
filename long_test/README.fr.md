
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