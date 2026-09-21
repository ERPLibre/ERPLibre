
# Posture réseau

Ce que le réseau d'une VM atteint, décidé avant que la machine existe.

Une posture est **une donnée, pas un comportement** : une ligne de registre
qui dit ce que le réseau autorise. Rien dans ce paquet ne lance de commande
ni n'affiche d'écran — il rend du texte et des jetons, ce qui le rend
éprouvable sans machine, sans terminal et sans privilège.

## Les quatre postures, et ce que chacune tient VRAIMENT

| Posture | Profil | Ce qu'elle tient |
|---|---|---|
| `open` | Sandbox | NAT. Rien n'est confiné, et c'est le principe |
| `connected` | VM Connecté | Ports bornés, destinations libres : `53,123/udp`, `22,80,443/tcp` vers n'importe où |
| `paranoid` | VM paranoid | Destinations bornées, prises dans le carnet d'adresses du site |
| `local-only` | local-webui | Sortie coupée, et une interface web joignable depuis l'hôte |

Le **profil** est le nom qu'un humain reconnaît ; la **posture** est ce que
la spec porte. Les séparer est délibéré : c'est ce qui permet de servir
autre chose sur la même posture.

## La règle d'or

Le couple *(posture, données réelles)* est refusé **avant que la machine
existe** — le seul moment où un refus ne coûte rien. Trois champs, et aucun
ne se déduit des autres :

- `install.prod` — OÙ ça s'installe ;
- `posture` — CE QUE LE RÉSEAU atteint ;
- `real_data` — SI LA MACHINE porte des données réelles.

Les confondre produit les deux accidents symétriques : une maquette de
démonstration qui parle à tout l'Internet parce qu'elle n'est « pas en
production », et une machine de production confinée au point de ne plus
pouvoir se mettre à jour.

Seule une posture dont les destinations sont bornées, dont les règles sont
appliquées et dont le mécanisme attrape le trafic des conteneurs peut porter
des données réelles. C'est aujourd'hui `local-only` et elle seule — et un
écran qui offrirait une posture que la garde refusera fait répondre à une
douzaine de questions de plus avant de le dire.

## Où les règles se posent, selon le backend

| Backend | Comment | Quand |
|---|---|---|
| libvirt / QEMU | `write_files` de cloud-init, ou le `late_command` de l'installateur | **avant** le premier démarrage |
| Proxmox VE | poussées dans l'invité après la création | **après** le premier démarrage — d'où une fenêtre ouverte |
| Lima | bloc `provision:` de l'instance, `mode: system` | au premier démarrage |

Lima **refuse** `local-only` : le réseau en mode utilisateur donne toujours
la sortie, et aucun réglage d'instance ne la retire. Promettre le contraire
serait le nom rassurant que le registre s'interdit.

## Ce qui n'est pas tenu, et qui le dit

Un mécanisme muet sur ce qu'il n'applique pas est ce qui fait croire à un
confinement qui n'existe pas. Quatre jetons, vocabulaire clos :

- `no-rendering` — la posture déclare une politique que rien n'installe ;
- `reload-failure-unseen` — un rechargement qui échoue à un démarrage
  ultérieur n'est pas signalé ;
- `containers-unproven` — le trafic des conteneurs traverse FORWARD, et
  aucune confrontation ne l'a encore mesuré ;
- `boot-window-open` — les règles n'arrivent qu'une fois la machine debout.

## Le carnet d'adresses

`paranoid` nomme sept rôles et le déploiement REFUSE tant que chacun n'a pas
d'adresse. Le carnet vit dans trois fichiers qui se fusionnent ; celui que
git suit est **refusé par construction**, parce qu'une adresse IP hors de
`private/` devient publique au premier envoi d'un fork.

```bash
# Ce qu'une posture rend, sans machine :
python3 -c "from script.posture import registry, rules; \
  print(rules.render_egress(registry.get_posture('connected'), ()))"
```