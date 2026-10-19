
# Déployer des VM sur un hôte Proxmox VE

Deux choses différentes vivent dans ce répertoire :

- `install_proxmox.sh` transforme une Debian en hyperviseur Proxmox. Voir
  `script/qemu/README.fr.md`, qui documente la distro `proxmox` du catalogue
  de déploiement.
- `proxmox_deploy.py` déploie des VM **sur** un tel hôte, depuis
  `TODO › Execute › Deploy › Proxmox VE`, juste sous `QEMU/KVM`.
- `host_perf_audit.py` mesure, en lecture seule, ce qui limite les
  performances d'un tel hôte (ou de tout serveur Linux). Voir
  [Audit de performance de l'hôte](#audit-de-performance-de-lhôte-lecture-seule).

## Toute la différence : l'hyperviseur est ailleurs

Avec QEMU/KVM, l'hyperviseur est la machine qui exécute le script. Avec
Proxmox il est ailleurs : la première question est donc **quel hôte** — et la
réponse est retenue pour la session. Trois voies, toutes proposées par le menu :

1. **Depuis les VM QEMU locales** — une VM `proxmox` déployée ici. Son adresse
   vient du bail DHCP, rien à retaper.
2. **Par adresse** — `utilisateur@hôte`, plus un rebond SSH facultatif.
3. **Depuis `~/.ssh/config`** — l'alias porte déjà l'utilisateur, le port et le
   ProxyJump ; on ne demande rien d'autre.

L'hôte choisi est ensuite **vérifié**, pas supposé : `pveversion` prouve que
c'en est un, `id -u` et `sudo -n true` décident s'il faut `sudo`, et une clé
d'hôte inconnue est proposée à l'enregistrement (par `ssh-keyscan`, jamais en
désactivant la vérification — un hyperviseur n'est pas une VM jetable).

```bash
# Ce que l'outil envoie, et qu'on peut rejouer à la main :
ssh erplibre@pve1 sudo sh -c 'qm list'
ssh erplibre@pve1 sudo sh -c 'pvesm status --content images'
```

## Pourquoi SSH et `qm`, pas l'API REST

L'API demande un jeton ou un ticket à créer et à renouveler. `qm` est la voie
que tout administrateur Proxmox connaît, le dépôt sait déjà gérer des accès SSH
(`~/.ssh/config`, ProxyJump, clés), et les commandes restent lisibles dans le
journal — donc rejouables à la main. C'est ainsi que chaque panne de ce module
a été diagnostiquée.

`sudo sh -c '<toute la commande>'` et non `sudo <commande>` : ces commandes sont
des suites et des redirections. Préfixer par sudo n'élèverait que le premier
mot, et la redirection resterait celle du shell non privilégié.

## Quatre pièges rencontrés sur un hôte réel

Une Proxmox installée **sur Debian** n'a aucun `vmbr0` — l'installateur ISO en
crée un, cette procédure non. Or `qm create` exige un pont.

Le menu propose alors un pont **interne** (`vmbr0`, `10.10.10.1/24`, NAT par la
sortie). Ne jamais ajouter l'interface physique à un pont est un choix : cela
déplace l'adresse de l'hôte et coupe la session SSH en cours — à distance, sans
retour. Pour un pont donnant sur le LAN, la strophe est affichée, à appliquer
depuis une console.

Sur un pont interne, aucun DHCP ne répond : l'adresse est donc **fixe**, dérivée
du VMID — donc connue avant que la VM ne démarre. La chercher ensuite était
absurde.

L'image cloud Debian n'embarque pas `qemu-guest-agent`, et Proxmox ne connaît
pas l'adresse d'un invité en DHCP : il ne distribue pas les baux. Le repli est
le voisinage de l'hôte (`ip neigh`), qui ne demande rien à l'invité.

## Le menu, entrée par entrée

Les dix-sept entrées de QEMU/KVM ont leur équivalent. Quatre sont le **même
code**, parce que c'est le même travail : rouvrir le suivi d'installation, le
tunnel bureau distant, l'émulateur Android et le catalogue d'images. Elles
atteignent les invités Proxmox par les entrées `~/.ssh/config` que l'entrée 13
écrit, avec l'hôte Proxmox en ProxyJump.

```text
[1] Déployer une VM        [8]  Redimensionner un disque   [15] Émulateur Android *
[2] Prévisualiser          [9]  Effacer des VM             [16] Catalogue d'images *
[3] Télécharger une image  [10] Nettoyer (orphelins)       [17] Exemple (dry-run)
[4] Rouvrir le suivi *     [11] Tester une VM (Odoo)       [18] Changer d'hôte
[5] Lister (qm list)       [12] Statistiques               [19] Audit de performance
[6] Adresse IP d'une VM    [13] Configuration SSH
[7] Console d'une VM       [14] Tunnel bureau distant *
                                        * code partagé avec le menu QEMU/KVM
```

## Audit de performance de l'hôte (lecture seule)

`host_perf_audit.py` échantillonne `/proc` et `/sys` toutes les
`--interval` secondes (5 par défaut) pendant `--duration` (`60`, `30s`,
`10m`, `2h`, `1h30m` ; de 1 seconde à 7 jours), puis rend un verdict par
ressource — `ok`, `watch` ou `limiting` — pour le processeur, la mémoire,
les disques et le réseau, la réponse à « des disques SSD sont-ils
justifiés ? », et les réglages à envisager (compression et atime ZFS,
maximum de l'ARC, `vm.swappiness`, options des disques de VM…), chacun
**affiché** avec la commande qui l'appliquerait. Rien n'est jamais modifié.

Il couvre la pression (PSI, `/proc/pressure`), l'utilisation et l'attente
de chaque disque (un disque rotatif est jugé sur son utilisation et son
attente, un SSD ou un NVMe sur son attente seulement), l'activité du swap,
ZFS (taux de succès de l'ARC, remplissage, fragmentation, santé, latence
des pools) et, sur un hôte Proxmox en cgroup v2, chaque conteneur et VM en
marche, nommés d'après `/etc/pve`. Les disques d'un pool sont lus dans ses
propres vdev (`zpool status -P -L`) : un HDD de sauvegarde oisif, hors de
tout pool, ne fait jamais répondre « oui, des SSD ».

C'est un seul fichier, bibliothèque standard seulement, lançable par le
`python3` d'un hôte dès Debian 10. L'entrée `[19]` de ce menu l'envoie à
l'hôte retenu par `ssh -T`, le fichier sur stdin, ou le lance sur ce
poste ; `TODO › Exécuter › Production` le lance aussi en local. Ctrl-C
arrête la mesure plus tôt et donne quand même le rapport quand le script
tourne sur l'hôte lui-même ; par ssh, un Ctrl-C local ferme la connexion
et le rapport est perdu. `--json` produit un document aux clés stables,
`--csv FICHIER` garde les échantillons bruts ; une erreur d'écriture
(disque plein) coupe le fichier, pas l'audit. Chaque commande lancée une
fois (`zpool`, `zfs`, `smartctl`) est abandonnée après 20 s, même bloquée
sur un pool suspendu, et `smartctl` laisse dormir un disque en veille.
Codes de sortie : 0 audit
fait, 2 impossible, 130 interrompu avant la mesure.

```bash
./script/proxmox/host_perf_audit.py --duration 10m
sudo ./script/proxmox/host_perf_audit.py --duration 24h --csv /var/tmp/perf.csv
ssh -T root@pve.example.org python3 -I - --duration 2h < script/proxmox/host_perf_audit.py
```

## Vérifié

Déploiement d'une VM dans une Proxmox qui tourne elle-même dans une VM
libvirt : image téléchargée sur l'hôte, pont interne créé, adresse fixe,
utilisateur et clé par cloud-init, disque redimensionné, `qm start`. Puis
`ssh vm-essai` depuis l'extérieur l'atteint par le rebond — trois niveaux
imbriqués. Redimensionnement `12G → 16G`, effacement avec `--purge`, recherche
d'orphelins : tout contrôlé contre Proxmox VE 9.2.11.