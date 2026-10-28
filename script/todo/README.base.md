<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
TODO is an assistant robot to use ERPLibre
Execute it with `./script/todo/todo.py` or `make todo`.

For a new project, copy todo_example.json to private/todo/todo_override.json | private/todo/todo_override_private.json and edit it.

The `mail/` package is the mail client reachable from `Assistant > Mail`:
several IMAP/SMTP accounts, a local cache, and a Textual TUI. See
[../../doc/EMAIL.md](../../doc/EMAIL.md). Its `mail/rules/` subpackage holds
the incoming mail rules — model, filter, safeguards, reply rendering,
the statistics report (`report.py`), forwarding (inline, as an attachment,
or a true redirect under `Resent-*`, to one or more destinations), storage
and the engine that runs after each sync pass (see "Incoming mail rules" in
that guide). From the menu, `Mail > [6] Incoming mail rules` lists the
rules — a forward rule with its mode and destinations under its filter —
and orders them; its `[6]` sets the statistics report of an account and
prints a preview, its `[7]` tries a rule on a recent inbox message and can
send the trial to the account itself.

## Where the code lives

`todo.py` carries the menus and the general helpers. Everything around a
single subject sits in its own file, and the whole thing is assembled by
mixins on the `TODO` class — one file, one subject, its header states its
boundary.

| File | What it owns |
|------|--------------|
| `todo.py` | the menus, the configuration, the general helpers |
| `qemu_menu.py` | the QEMU/KVM menu, the image catalogue, the statistics |
| `qemu_deploy.py` | deciding then running a deployment |
| `qemu_install.py` | the recipes run inside a VM |
| `qemu_manage.py` | lifecycle, disks, hardware, cleanup, addresses |
| `qemu_access.py` | SSH, tunnels, consoles, Android emulator |
| `proxmox_menu.py` | the same, on a REMOTE Proxmox VE host |

The two deployment forms — libvirt here, Proxmox over there — ask the same
questions, so they share a foundation rather than each holding a copy:

| File | What it owns |
|------|--------------|
| `deploy_form_lib.py` | pure logic (sizes, plan, totals, spec), the shared CSS, the resource-row factory, the progress view |
| `deploy_form_plan.py` | the plan's gestures: overrides, locks, copies, renaming, free values |
| `qemu_deploy_form.py` | what QEMU/KVM adds: desktops, tools, branches, install profiles |
| `proxmox_deploy_form.py` | what Proxmox adds: host, storage, bridge, VMID, address |

A form inherits `PlanMixin` and provides three hooks: which presets each
resource offers, the name a VM would fall back to, and what a lock freezes.
`test_todo_deploy_form_lib.py` fails if a form redefines a gesture the
foundation already carries — that is what keeps the architecture from drifting
back into two copies.


<!-- [fr] -->
TODO est un robot assistant pour utiliser ERPLibre
Exécutez-le avec `./script/todo/todo.py` ou `make todo`.

Pour un nouveau projet, copiez todo_example.json vers private/todo/todo_override.json | private/todo/todo_override_private.json et modifiez-le.

Le paquet `mail/` est le client courriel accessible depuis
`Assistant > Courriel` : plusieurs comptes IMAP/SMTP, un cache local, et un
TUI Textual. Voir [../../doc/EMAIL.fr.md](../../doc/EMAIL.fr.md). Son
sous-paquet `mail/rules/` porte les règles du courrier entrant — modèle,
filtre, garde-fous, rendu de la réponse, rapport de statistiques
(`report.py`), redirection (transfert dans le corps, en pièce jointe, ou
vraie redirection sous `Resent-*`, vers une ou plusieurs destinations),
stockage et le moteur qui tourne après chaque passe de synchronisation
(voir « Règles du courrier entrant » dans ce guide). Depuis le menu,
`Courriel > [6] Règles du courrier entrant` liste les règles — une règle
de redirection avec son mode et ses destinations sous son filtre — et les
ordonne ; son `[6]` règle le rapport de statistiques d'un compte et en
imprime un aperçu, son `[7]` essaie une règle sur un message récent de la
boîte de réception et peut envoyer l'essai au compte lui-même.

## Où vit le code

`todo.py` porte les menus et les aides générales. Tout ce qui tourne autour
d'un même sujet vit dans son fichier, et l'ensemble est assemblé par des
mixins sur la classe `TODO` — un fichier, un sujet, son en-tête dit sa
frontière.

| Fichier | Ce qu'il porte |
|---------|----------------|
| `todo.py` | les menus, la configuration, les aides générales |
| `qemu_menu.py` | le menu QEMU/KVM, le catalogue d'images, les statistiques |
| `qemu_deploy.py` | décider puis exécuter un déploiement |
| `qemu_install.py` | les recettes exécutées DANS une VM |
| `qemu_manage.py` | cycle de vie, disques, matériel, nettoyage, adresses |
| `qemu_access.py` | SSH, tunnels, consoles, émulateur Android |
| `proxmox_menu.py` | la même chose, sur un hôte Proxmox VE DISTANT |

Les deux formulaires de déploiement — libvirt ici, Proxmox ailleurs — posent
les mêmes questions : ils partagent donc un socle au lieu d'en garder chacun
une copie.

| Fichier | Ce qu'il porte |
|---------|----------------|
| `deploy_form_lib.py` | la logique pure (tailles, plan, totaux, spec), le CSS commun, la fabrique des rangées de ressources, la vue de progression |
| `deploy_form_plan.py` | les gestes du plan : surcharges, verrous, exemplaires, renommage, valeurs libres |
| `qemu_deploy_form.py` | ce que QEMU/KVM ajoute : bureaux, outils, branches, profils d'installation |
| `proxmox_deploy_form.py` | ce que Proxmox ajoute : hôte, stockage, pont, VMID, adresse |

Un formulaire hérite de `PlanMixin` et fournit trois crochets : les
préréglages de chaque ressource, le nom auquel une VM retombe, et ce qu'un
verrou fige. `test_todo_deploy_form_lib.py` échoue si un formulaire redit un
geste que le socle porte déjà — c'est ce qui empêche l'architecture de
retomber en deux copies.
