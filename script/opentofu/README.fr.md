
# Déployer un parc de VM avec OpenTofu

Un **parc** est un ensemble de VM décrit par une spec JSON,
`private/opentofu/<parc>/spec.json` (ignorée par git, comme tout
`private/`). OpenTofu (`tofu`) le planifie, l'applique et le détruit sur un
hôte Proxmox VE. Le menu et le formulaire ne parlent qu'à l'interface de
moteur de `script/opentofu/moteur.py` : `tofu` n'est qu'un moteur derrière
elle, et un moteur Python pourra le remplacer sans toucher au menu.

## Où le trouver

`TODO › Exécution › Déploiement › OpenTofu`. Le menu a quatre sections :

- **Parcs** : créer un parc, l'éditer dans le formulaire, lister les parcs.
- **Opérations** : planifier, appliquer, détruire, afficher l'état tofu,
  afficher les adresses des VM.
- **Proxmox** : préparer l'hôte (rôle, utilisateur, jeton d'API).
- **Outil** : vérifier ou installer `tofu`.

Le formulaire (un TUI Textual) édite la spec par onglets, avec le plan et le
journal du moteur en bas. Touches : `s` enregistrer, `p` planifier, `a`
appliquer, `d` détruire, `q` quitter. Tant que `tofu` tourne, le formulaire
est occupé : les actions et `Ctrl+Q` sont désactivés jusqu'au retour, donc un
passage n'est jamais coupé en deux. Un apply qui remplace ou détruit une VM,
et tout destroy, demandent de retaper le nom du parc. Un destroy, du menu ou
du formulaire, retire aussi les alias SSH des VM de `~/.ssh/config`, comme un
apply pour les VM qu'il détruit.

## Première utilisation

1. **Outil** : le menu vérifie `tofu` contre `conf/opentofu.json`. Là où
   `pacman` existe (Arch), il installe le paquet ; ailleurs il télécharge le
   zip de la version, vérifie le fichier de sommes et sa signature GPG
   (empreinte épinglée dans `conf/opentofu.json`), puis installe le binaire
   dans `~/.local/bin`. Dans les deux cas il demande d'abord confirmation [y/N].
2. **Créer un parc** : un nom (`^[a-z][a-z0-9-]{0,30}$`) et la cible SSH de
   l'hôte Proxmox. La spec démarre avec une VM par défaut.
3. **Préparer l'hôte** : par SSH, crée le rôle `ERPLibreTofu`, l'utilisateur
   `tofu@pve` et le jeton d'API `tofu@pve!<parc>`, et active les contenus
   `snippets` et `import` sur un stockage. Proxmox ne montre le secret du
   jeton qu'une fois : il va aussitôt dans le `secrets.json` du parc.
4. **Plan**, puis **apply**. Le plan liste ce qui est créé, remplacé ou
   détruit ; l'apply crée les VM, puis ajoute un alias SSH `<hôte>+<vm>` à
   `~/.ssh/config` (l'hôte Proxmox en rebond). Une VM marquée
   `installer_erplibre` passe ensuite par l'installation ERPLibre du menu
   QEMU/KVM.

## La spec

`"schema": 1`. Racine : `nom` (le parc), `moteur` (`tofu`), `cible`,
`compte`, `vms`.

| Champ | Sens |
|-------|------|
| `cible.type` | genre de cible : `proxmox` |
| `cible.hote` | accès SSH à l'hôte : `target`, `jump`, `port`, `sudo` (`"sudo "` ou `""`) |
| `cible.api_url` | URL de l'API Proxmox ; vide, devient `https://<hôte>:8006/` |
| `cible.insecure` | accepter le certificat auto-signé de l'hôte |
| `cible.noeud` | nom du nœud Proxmox |
| `cible.stockage` | stockage des disques et des images |
| `cible.stockage_snippets` | stockage qui accepte les snippets (cloud-init) |
| `cible.pont` | pont réseau |
| `cible.ssh_user`, `cible.ssh_port` | compte et port que `ssh -G` donne pour la cible de l'hôte ; le fournisseur s'en sert pour écrire les snippets |
| `compte.user`, `compte.ssh_key` | compte créé dans les VM, chemin du fichier de clé publique qui y est posée (défaut : le premier qui existe de `~/.ssh/id_ed25519.pub` et `~/.ssh/id_rsa.pub`, sinon `~/.ssh/id_ed25519.pub`), pas la clé elle-même |
| `vms[].nom` | nom de VM, `^[a-z][a-z0-9-]{0,62}$`, unique dans le parc |
| `vms[].vmid` | VMID Proxmox ; vide, le premier libre |
| `vms[].distro`, `version`, `arch` | image du catalogue de déploiement |
| `vms[].vcpus`, `ram`, `disque` | vCPU, RAM en Mio (512 ou plus), disque du type `20G` |
| `vms[].ip` | `auto`, `dhcp`, ou une adresse fixe `a.b.c.d/nn` |
| `vms[].passerelle`, `dns` | passerelle et résolveurs d'une adresse fixe |
| `vms[].demarrer` | démarrer la VM après sa création |
| `vms[].installer_erplibre`, `branche` | installer ERPLibre après l'apply, sur cette branche |

Les champs laissés vides sont **résolus sur l'hôte** la première fois puis
**réécrits dans la spec** : `api_url`, `ssh_user`, `ssh_port`, `noeud`,
`stockage`, `stockage_snippets`, `pont`, `vmid`, et pour `ip: "auto"`
l'adresse (`dhcp` sur un pont qui donne sur le LAN, sinon une adresse fixe
dérivée du VMID, avec `passerelle` et `dns`). Un champ déjà rempli n'est
jamais relu ni écrasé, donc un second plan juste après un apply est vide. Le
cloud-init de chaque VM est écrit dans le stockage des snippets sous
`erplibre-<parc>-<vm>.yml`.

Renommer une VM la fait détruire par `tofu` puis recréer **sous un nouveau
VMID** : le plan le dit et demande une confirmation. Le formulaire vide le
VMID d'une VM renommée, et une adresse dérivée de ce VMID redevient `auto`.
En renommant à la main dans `spec.json`, vider soi-même `vmid` (et une telle
`ip`) : sinon la VM neuve est créée sur le VMID de celle qui part, et
l'apply échoue.

Une spec abîmée à la main (JSON invalide, champ manquant ou mal typé, nom de
VM ou VMID en double) donne une liste d'erreurs lisibles, jamais une trace
Python.

## Secrets et état

- `private/opentofu/<parc>/secrets.json` (mode 0600, dossier 0700) porte le
  jeton d'API et la phrase qui chiffre l'état.
- L'état et les fichiers de plan sont chiffrés : le moteur pose
  `TF_ENCRYPTION` (fournisseur de clé `pbkdf2`, méthode `aes_gcm`,
  `enforced = true`), donc un état ou un plan en clair est refusé.
- Le jeton et la phrase n'arrivent à `tofu` que par son environnement :
  jamais en ligne de commande, dans le `.tf.json` généré ni dans le journal,
  qui les masque. Toute variable `PROXMOX_VE_*` héritée est retirée, car
  elle appartient à un autre parc ou hôte, comme les variables `TF_LOG*`, car
  une trace recopie l'en-tête d'autorisation.
- Quand `conf/opentofu.json` épingle une autre version du fournisseur, le plan
  suivant lance `tofu init -upgrade` pour que le fichier de verrou suive.
- **Un `secrets.json` perdu ou écrasé rend l'état illisible.** Le moteur refuse
  alors de planifier plutôt que de créer une phrase neuve à côté de l'état
  existant. Restaurer `secrets.json` depuis une sauvegarde. Sans sauvegarde, les
  VM existent toujours sur l'hôte. Détruire UNIQUEMENT les VMID listés dans le
  `spec.json` du parc (`vms[].vmid`), en confirmant chacun d'abord par `qm
  config <vmid>` (le nom doit correspondre à la spec) ; ne toucher à aucune
  autre VM. Puis supprimer le dossier d'état du parc,
  `private/opentofu/<parc>/.tofu/`, et relancer Préparer l'hôte en répondant OUI
  à la recréation du jeton : l'ancien jeton existe encore sur l'hôte sans secret
  local, donc la préparation refuse autrement.

## Limites de la v1

- Proxmox seulement (libvirt viendra). Pas de rebond pour joindre l'API
  Proxmox, pas de passthrough USB ni GPU.
- Un jeton par parc, avec le rôle sur `/`. Le rôle porte la liste de
  privilèges de l'exemple de la documentation de bpg/proxmox, plus large que
  nécessaire et à resserrer.
- Sur un hôte de production, le compte SSH qui écrit les snippets exige une
  règle sudoers restreinte : `/usr/sbin/pvesm apiinfo` et `tee` vers le
  dossier des snippets, sans mot de passe, rien de plus. Un hôte qui laisse
  le compte lancer toute commande par sudo n'en a pas besoin.

## Licence

OpenTofu et le fournisseur `bpg/proxmox` sont sous MPL-2.0. Ils tournent
comme des programmes séparés : rien d'eux n'est copié dans ce dépôt. Les
fournisseurs viennent de `registry.opentofu.org` seulement, à la version
épinglée dans `conf/opentofu.json` ; `terraform` et `registry.terraform.io`
ne sont jamais utilisés.

## Test long

`long_test/opentofu_proxmox.py` fait tenir un parc de bout en bout sur un
Proxmox VE jetable : `--dry-run` s'arrête au plan, `--detruire` retire ce que
la course a bâti. Voir `long_test/README.fr.md`.