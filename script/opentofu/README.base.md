<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Deploying a fleet of VMs with OpenTofu

<!-- [fr] -->
# Déployer un parc de VM avec OpenTofu

<!-- [en] -->
A **fleet** is a set of VMs described by a JSON spec,
`private/opentofu/<fleet>/spec.json` (git-ignored, like all of `private/`).
OpenTofu (`tofu`) plans, applies and destroys it on a Proxmox VE host. The
menu and the form only talk to the engine interface of
`script/opentofu/moteur.py`: `tofu` is one engine behind it, and a Python
engine may replace it later without touching the menu.

## Where to find it

`TODO › Execute › Deploy › OpenTofu`. The menu has four sections:

- **Fleets**: create a fleet, edit it in the form, list the fleets.
- **Operations**: plan, apply, destroy, show the tofu state, show the VM
  addresses.
- **Proxmox**: prepare the host (role, user, API token).
- **Tool**: check or install `tofu`.

The form (a Textual TUI) edits the spec in tabs, with the plan and the
engine log at the bottom. Keys: `s` save, `p` plan, `a` apply, `d` destroy,
`q` quit. While `tofu` runs, the form is busy: the actions and `Ctrl+Q` are
disabled until it returns, so a run is never cut halfway. An apply that
replaces or destroys a VM, and every destroy, asks you to retype the fleet
name. A destroy also removes the VMs' SSH aliases from `~/.ssh/config`.

## First run

1. **Tool**: the menu checks `tofu` against `conf/opentofu.json`. Where
   `pacman` exists (Arch), it installs the package; elsewhere it downloads
   the release zip, verifies the checksum file and its GPG signature
   (fingerprint pinned in `conf/opentofu.json`), then installs the binary
   into `~/.local/bin`. Either way it asks for confirmation [y/N] first.
2. **Create a fleet**: a name (`^[a-z][a-z0-9-]{0,30}$`) and the SSH target
   of the Proxmox host. The spec starts with one default VM.
3. **Prepare the host**: over SSH, creates the role `ERPLibreTofu`, the user
   `tofu@pve` and the API token `tofu@pve!<fleet>`, and enables the
   `snippets` and `import` contents on a storage. The token secret is shown
   by Proxmox once: it goes straight into the fleet's `secrets.json`.
4. **Plan**, then **apply**. The plan lists what is created, replaced or
   destroyed; apply creates the VMs, then adds an SSH alias
   `<host>+<vm>` to `~/.ssh/config` (the Proxmox host as jump host). A VM
   marked `installer_erplibre` then goes through the ERPLibre install of the
   QEMU/KVM menu.

## The spec

`"schema": 1`. Top level: `nom` (the fleet), `moteur` (`tofu`), `cible`,
`compte`, `vms`.

| Field | Meaning |
|-------|---------|
| `cible.type` | target kind: `proxmox` |
| `cible.hote` | SSH access to the host: `target`, `jump`, `port`, `sudo` (`"sudo "` or `""`) |
| `cible.api_url` | Proxmox API URL; empty, it becomes `https://<host>:8006/` |
| `cible.insecure` | accept the host's self-signed certificate |
| `cible.noeud` | Proxmox node name |
| `cible.stockage` | storage for disks and images |
| `cible.stockage_snippets` | storage that accepts snippets (cloud-init) |
| `cible.pont` | network bridge |
| `compte.user`, `compte.ssh_key` | account created in the VMs, path of the public key file put in it (default `~/.ssh/id_ed25519.pub`), not the key itself |
| `vms[].nom` | VM name, `^[a-z][a-z0-9-]{0,62}$`, unique in the fleet |
| `vms[].vmid` | Proxmox VMID; empty, the first free one |
| `vms[].distro`, `version`, `arch` | image from the deployment catalog |
| `vms[].vcpus`, `ram`, `disque` | vCPUs, RAM in MiB (512 or more), disk like `20G` |
| `vms[].ip` | `auto`, `dhcp`, or a fixed `a.b.c.d/nn` |
| `vms[].passerelle`, `dns` | gateway and resolvers of a fixed address |
| `vms[].demarrer` | start the VM after creation |
| `vms[].installer_erplibre`, `branche` | install ERPLibre after the apply, on that branch |

The fields left empty are **resolved on the host** the first time and
**written back to the spec**: `api_url`, `noeud`, `stockage`,
`stockage_snippets`, `pont`, `vmid`, and for `ip: "auto"` the address (`dhcp`
on a bridge that faces the LAN, otherwise a fixed address derived from the
VMID, with `passerelle` and `dns`). A field already filled is never read
again nor overwritten, so a second plan right after an apply is empty.
Renaming a VM in the spec makes `tofu` destroy and recreate it: the plan says
so and asks for a confirmation.

A spec edited by hand and broken (invalid JSON, missing field, duplicate VM)
gives a list of readable errors, not a traceback.

## Secrets and state

- `private/opentofu/<fleet>/secrets.json` (mode 0600, directory 0700) holds
  the API token and the passphrase that encrypts the state.
- The state and the plan files are encrypted: the engine sets `TF_ENCRYPTION`
  (key provider `pbkdf2`, method `aes_gcm`, `enforced = true`), so a clear
  state or plan is refused.
- The token and the passphrase reach `tofu` through its environment only:
  never on the command line, in the generated `.tf.json` or in the log, which
  masks them. The inherited `TF_LOG*` variables are dropped, since a trace
  copies the authorization header.
- **A lost or overwritten `secrets.json` makes the state unreadable.** Restore
  it from a backup. Without a backup, the VMs still exist on the host.
  Destroy ONLY the VMIDs listed in the fleet's `spec.json` (`vms[].vmid`),
  and confirm each one first with `qm config <vmid>` (the name must match
  the spec); touch no other VM. Then delete the fleet's state directory,
  `private/opentofu/<fleet>/.tofu/`, and run Prepare the host again,
  answering YES to recreating the token: the old token still exists on the
  host with no local secret, so the preparation refuses otherwise.

## Limits of v1

- Proxmox only (libvirt later). No jump host to reach the Proxmox API, no
  USB or GPU passthrough.
- One token per fleet, with the role on `/`. The role carries the privilege
  list of the bpg/proxmox documentation example, which is wider than needed
  and is to be narrowed.
- On a production host, the SSH account that writes the snippets needs a
  restricted sudoers rule: passwordless `/usr/sbin/pvesm apiinfo` and
  `tee` into the snippets directory, nothing more. A host that lets the
  account run any command through sudo needs none.

## Licence

OpenTofu and the `bpg/proxmox` provider are MPL-2.0. They run as separate
programs: nothing of them is copied into this repository. Providers come from
`registry.opentofu.org` only, at the version pinned in
`conf/opentofu.json`; `terraform` and `registry.terraform.io` are never used.

## Long test

`long_test/opentofu_proxmox.py` runs a fleet end to end on a disposable
Proxmox VE: `--dry-run` stops at the plan, `--detruire` removes what the run
built. See `long_test/README.md`.

<!-- [fr] -->
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
et tout destroy, demandent de retaper le nom du parc. Un destroy retire aussi les alias SSH
des VM de `~/.ssh/config`.

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
| `compte.user`, `compte.ssh_key` | compte créé dans les VM, chemin du fichier de clé publique qui y est posée (défaut `~/.ssh/id_ed25519.pub`), pas la clé elle-même |
| `vms[].nom` | nom de VM, `^[a-z][a-z0-9-]{0,62}$`, unique dans le parc |
| `vms[].vmid` | VMID Proxmox ; vide, le premier libre |
| `vms[].distro`, `version`, `arch` | image du catalogue de déploiement |
| `vms[].vcpus`, `ram`, `disque` | vCPU, RAM en Mio (512 ou plus), disque du type `20G` |
| `vms[].ip` | `auto`, `dhcp`, ou une adresse fixe `a.b.c.d/nn` |
| `vms[].passerelle`, `dns` | passerelle et résolveurs d'une adresse fixe |
| `vms[].demarrer` | démarrer la VM après sa création |
| `vms[].installer_erplibre`, `branche` | installer ERPLibre après l'apply, sur cette branche |

Les champs laissés vides sont **résolus sur l'hôte** la première fois puis
**réécrits dans la spec** : `api_url`, `noeud`, `stockage`,
`stockage_snippets`, `pont`, `vmid`, et pour `ip: "auto"` l'adresse (`dhcp`
sur un pont qui donne sur le LAN, sinon une adresse fixe dérivée du VMID,
avec `passerelle` et `dns`). Un champ déjà rempli n'est jamais relu ni
écrasé, donc un second plan juste après un apply est vide. Renommer une VM
dans la spec fait détruire puis recréer la VM par `tofu` : le plan le dit et
demande une confirmation.

Une spec abîmée à la main (JSON invalide, champ manquant, VM en double)
donne une liste d'erreurs lisibles, jamais une trace Python.

## Secrets et état

- `private/opentofu/<parc>/secrets.json` (mode 0600, dossier 0700) porte le
  jeton d'API et la phrase qui chiffre l'état.
- L'état et les fichiers de plan sont chiffrés : le moteur pose
  `TF_ENCRYPTION` (fournisseur de clé `pbkdf2`, méthode `aes_gcm`,
  `enforced = true`), donc un état ou un plan en clair est refusé.
- Le jeton et la phrase n'arrivent à `tofu` que par son environnement :
  jamais en ligne de commande, dans le `.tf.json` généré ni dans le journal,
  qui les masque. Les variables `TF_LOG*` héritées sont retirées, car une
  trace recopie l'en-tête d'autorisation.
- **Un `secrets.json` perdu ou écrasé rend l'état illisible.** Le restaurer
  depuis une sauvegarde. Sans sauvegarde, les VM existent toujours sur
  l'hôte. Détruire UNIQUEMENT les VMID listés dans le `spec.json` du parc
  (`vms[].vmid`), en confirmant chacun d'abord par `qm config <vmid>` (le
  nom doit correspondre à la spec) ; ne toucher à aucune autre VM. Puis
  supprimer le dossier d'état du parc, `private/opentofu/<parc>/.tofu/`, et
  relancer Préparer l'hôte en répondant OUI à la recréation du jeton :
  l'ancien jeton existe encore sur l'hôte sans secret local, donc la
  préparation refuse autrement.

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
