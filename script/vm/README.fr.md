
# Backends de VM

Trois backends, un seul vocabulaire : **l'identité choisit le backend**, et
un écran n'a plus à savoir lequel.

## Le paquet ne dépend de rien

Ni menu, ni écran, ni terminal — **pas même des postures**. Une épreuve le
tient au niveau du PAQUET, pour que le module écrit ensuite hérite de la
règle sans que personne y pense. Ce qu'elle protège n'est pas une élégance :
un backend qui importerait un module de menu deviendrait inéprouvable sans
terminal, et le premier consommateur d'un deuxième écran en ferait une copie
plutôt que de tirer sur ce fil.

C'est l'APPELANT qui rapproche les deux. Les règles de sortie atteignent une
instance sous forme de script composé, jamais d'une posture que le paquet
irait lire.

## La poignée : de quoi commander une machine, et prouver que c'est la bonne

| Champ | Ce que c'est |
|---|---|
| `backend` | `libvirt`, `pve` ou `lima` |
| `name` | Ce qu'un humain appelle |
| `key` | Ce qui ADRESSE — un nom pour libvirt, un VMID sur un hôte Proxmox |
| `proof` | Ce qui PROUVE — un UUID de domaine, le nom qu'un VMID doit encore porter |
| `address` | OÙ le service écoute. Vide n'est pas « injoignable » |
| `alias` | Le nom qu'un `~/.ssh/config` sait résoudre seul. Pour une VM d'hôte distant ce n'est PAS son adresse : celle-ci n'est routable que depuis l'hôte, l'alias porte le chemin complet |
| `host` | La fiche de la machine qui l'héberge — vide en local. C'est ce qui permet à un verbe de savoir qu'il doit passer par quelqu'un d'autre |

`handle_of(entry)` lit la forme que les manifestes ont aujourd'hui. Une
entrée qui porte `pve` vit sur un hôte Proxmox ; une qui porte `lima` est une
instance ; les autres sont locales. Elle rend `None` quand rien n'est
ADRESSABLE — jamais parce qu'un champ manque : une VM distante s'adresse par
son VMID et reste commandable sans nom, simplement **désarmée**.

## Pourquoi la preuve existe

Un nom de domaine libvirt se réemploie ; un VMID libéré est réattribué.
Effacer « le 101 » d'un manifeste de mars, c'est effacer ce qui porte le 101
aujourd'hui. Tout verbe destructeur porte donc un garde d'identité qui
S'ARRÊTE si la clé ne porte plus ce nom — et `is_armed` dit quand il n'y a
aucune preuve pour l'armer.

## Éprouvé, et non éprouvé

`libvirt` et `pve` ont tourné contre de vraies machines. **`lima` non**, et
le paquet le dit plutôt que de laisser un écran le supposer. « Non éprouvé »
ne veut pas dire douteux : il veut dire que ce que `limactl` fait du texte
rendu n'a jamais été mesuré. `long_test/lima_confront.py` est ce qui lèvera
la mention — pas une relecture.

```bash
# L'identité d'une fiche de manifeste, et ce qu'elle arme :
python3 -c "from script.vm import backend as B; \
  h = B.handle_of({'name': 'vm-a', 'uuid': 'abc'}); \
  print(h.backend, h.key, B.is_armed(h))"
```