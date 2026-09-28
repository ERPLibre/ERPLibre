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
[../../doc/EMAIL.md](../../doc/EMAIL.md).

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

## Web interface and desktop window

TODO also runs in a browser page or in a desktop window, served by a local
hub, one per checkout, under the user's account. Each web session is the real
TODO in a terminal of its own: menus and questions become buttons and fields,
and the terminal still answers everything.

- Open: TODO › [4] Navigation telemetry › [2] WEB, or `make todo_web`. The
  page opens in the browser, and its one-time link is also printed in the
  terminal; without a display, TODO prints the SSH tunnel to run from the
  workstation.
- Stop: [4] › [3], or `make todo_web_stop`. The hub also stops by itself
  after 30 minutes with no session and no request.
- Desktop window: [4] › [4], or `make todo_desktop`, opens the same page in a
  native window (pywebview, not installed by default: TODO prints the
  commands to install it).
  `make todo_desktop_install` adds an ERPLibre TODO entry for this checkout
  to the desktop's application menu.
- File picker: when a command asks for a file or a directory, the page shows
  a picker, and the desktop window also offers the system's file dialog.
- Task logs: each task run in a web session is kept 30 days under
  `~/.erplibre/todo_web/`, 0600, secrets masked; `make todo_web_purge`
  removes those older than 30 days.
- Source: the footer of the page offers its source, as section 13 of the
  AGPL asks.

Security model:

- the hub listens on 127.0.0.1 only;
- a login is a one-time code, valid 120 s, carried by the fragment of the
  link, never by a command line;
- the session cookie bears the hub's port in its name, `HttpOnly` and
  `SameSite=Strict`, and every write carries a CSRF token;
- every write and every WebSocket must come from the exact Origin of the
  page;
- the hub refuses to run as root: sudo stays per command, on the terminal
  of the session.

Limits: 3 sessions at once; at most 5 new sessions per minute; a login lasts
12 hours, and 16 live at once. Refused login codes count against no limit: a
good code is always accepted. A ▶ launch refused by the limit has already
closed the idle session it was to replace; the page shows the wait in seconds
at the refusal, without counting it down.


<!-- [fr] -->
TODO est un robot assistant pour utiliser ERPLibre
Exécutez-le avec `./script/todo/todo.py` ou `make todo`.

Pour un nouveau projet, copiez todo_example.json vers private/todo/todo_override.json | private/todo/todo_override_private.json et modifiez-le.

Le paquet `mail/` est le client courriel accessible depuis
`Assistant > Courriel` : plusieurs comptes IMAP/SMTP, un cache local, et un
TUI Textual. Voir [../../doc/EMAIL.fr.md](../../doc/EMAIL.fr.md).

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

## Interface web et fenêtre bureautique

TODO tourne aussi dans une page du navigateur ou dans une fenêtre
bureautique, servie par un hub local, un par checkout, sous le compte de
l'utilisateur. Chaque session web est le vrai TODO dans un terminal à elle :
menus et questions y deviennent boutons et champs, et le terminal répond
toujours à tout.

- Ouvrir : TODO › [4] Télémétrie de navigation › [2] WEB, ou `make todo_web`.
  La page s'ouvre dans le navigateur, et son lien à usage unique s'affiche
  aussi dans le terminal ; sans affichage, TODO donne le tunnel SSH à lancer
  depuis le poste de travail.
- Arrêter : [4] › [3], ou `make todo_web_stop`. Le hub s'arrête aussi de
  lui-même après 30 minutes sans session ni requête.
- Fenêtre bureautique : [4] › [4], ou `make todo_desktop`, ouvre la même page
  dans une fenêtre native (pywebview, pas installé par défaut : TODO donne
  les commandes pour l'installer). `make todo_desktop_install` ajoute au menu
  des applications du bureau une entrée ERPLibre TODO pour ce checkout.
- Sélecteur de fichiers : quand une commande demande un fichier ou un
  répertoire, la page montre un sélecteur, et la fenêtre bureautique offre
  aussi le dialogue de fichiers du système.
- Journaux des tâches : chaque tâche lancée dans une session web est gardée
  30 jours sous `~/.erplibre/todo_web/`, en 0600, secrets masqués ;
  `make todo_web_purge` retire celles de plus de 30 jours.
- Source : le pied de la page offre sa source, comme le demande l'article 13
  de l'AGPL.

Modèle de sécurité :

- le hub n'écoute que sur 127.0.0.1 ;
- une connexion est un code à usage unique, valable 120 s, porté par le
  fragment du lien, jamais par une ligne de commande ;
- le cookie de session porte le port du hub dans son nom, `HttpOnly` et
  `SameSite=Strict`, et chaque écriture porte un jeton CSRF ;
- chaque écriture et chaque WebSocket doivent venir de l'Origin exacte de la
  page ;
- le hub refuse de tourner en root : sudo reste par commande, sur le terminal
  de la session.

Limites : 3 sessions à la fois ; au plus 5 sessions neuves par minute ; une
connexion vaut 12 heures, et 16 vivent à la fois. Les codes de connexion
refusés ne comptent dans aucune limite : un bon code est toujours accepté. Un
lancement ▶ refusé par la limite a déjà fermé la session oisive qu'il devait
remplacer ; la page montre l'attente en secondes au moment du refus, sans la
décompter.
