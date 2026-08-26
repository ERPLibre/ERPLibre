
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