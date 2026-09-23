<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# VM backends

Three backends, one vocabulary: **the identity chooses the backend**, and a
screen no longer has to know which one.

## The package depends on nothing

Not a menu, not a screen, not a terminal — **not even the postures**. A test
holds it at the level of the PACKAGE, so that the module written next
inherits the rule without anyone thinking about it. What it protects is not
an elegance: a backend importing a menu module would become untestable
without a terminal, and the first consumer of a second screen would copy it
rather than pull on that thread.

It is the CALLER that brings the two together. Egress rules reach an
instance as a composed script, never as a posture the package would read.

## The handle: what commands a machine, and proves it is the right one

| Field | What it is |
|---|---|
| `backend` | `libvirt`, `pve` or `lima` |
| `name` | What a human calls it |
| `key` | What ADDRESSES it — a name for libvirt, a VMID on a Proxmox host |
| `proof` | What PROVES it — a domain UUID, the name a VMID must still bear |
| `address` | WHERE the service listens. Empty is not "unreachable" |
| `alias` | The name a `~/.ssh/config` resolves on its own. For a remote-host VM this is NOT its address: that one only routes from the host, the alias carries the whole path |
| `host` | The record of the machine hosting it — empty locally. It is what lets a verb know it must go through someone else |

`handle_of(entry)` reads the shape the manifests have today. An entry
carrying `pve` lives on a Proxmox host; one carrying `lima` is an instance;
the others are local. It returns `None` when nothing is ADDRESSABLE — never
because a field is missing: a remote VM is addressed by its VMID and stays
commandable without a name, simply **disarmed**.

## Why the proof exists

A libvirt domain name is reused; a VMID is reassigned once freed. Deleting
"the 101" from a manifest written in March deletes whatever bears 101 today.
Every destructive verb therefore carries an identity guard that **stops**
when the key no longer bears that name — and `is_armed` says when there is
no proof to arm it with.

## Proven, and not proven

All three backends have run against a real machine, through the WHOLE
lifecycle: create, start, list, execute a command chain, stop, delete.
"Unproven" never meant doubtful — it meant that what the tool makes of the
rendered text had not been measured. `long_test/lima_confront.py` is what
lifted the mention on `lima` — not a code review.

That distinction earns its keep: the instance description the package
rendered parsed perfectly as YAML and did not start, because the `arch`
field has a vocabulary of its own — `x86_64` where the repository and the
image both say `amd64`. No amount of reading finds that; one boot does.

A backend absent from the table is unproven by default: doubt leans towards
the side that promises nothing.

<!-- [fr] -->
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

Les trois backends ont tourné contre une vraie machine, sur le cycle de vie
ENTIER : créer, démarrer, inventorier, exécuter une suite, arrêter,
supprimer. « Non éprouvé » n'a jamais voulu dire douteux — il voulait dire
que ce que l'outil fait du texte rendu n'avait pas été mesuré.
`long_test/lima_confront.py` est ce qui a levé la mention sur `lima` — pas
une relecture.

La distinction gagne son prix : la description d'instance que le paquet
rendait se relisait parfaitement en YAML et ne démarrait pas, le champ
« arch » ayant son propre vocabulaire — `x86_64` là où le dépôt et l'image
disent tous deux `amd64`. Aucune lecture ne trouve cela ; un démarrage si.

Un backend absent de la table est non éprouvé par défaut : le doute penche
du côté qui ne promet rien.

<!-- [common] -->
```bash
# L'identité d'une fiche de manifeste, et ce qu'elle arme :
python3 -c "from script.vm import backend as B; \
  h = B.handle_of({'name': 'vm-a', 'uuid': 'abc'}); \
  print(h.backend, h.key, B.is_armed(h))"
```
