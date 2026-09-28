
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