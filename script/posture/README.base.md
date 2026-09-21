<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Network posture

What a VM's network reaches, decided before the machine exists.

A posture is **data, not behaviour**: a row in a registry saying what the
network allows. Nothing in this package runs a command or prints a screen —
it renders text and returns tokens, which is what makes it testable without
a machine, a terminal or a privilege.

## The four postures, and what each one really holds

| Posture | Profile | What it holds |
|---|---|---|
| `open` | Sandbox | NAT. Nothing is confined, and that is the point |
| `connected` | VM Connecté | Ports bounded, destinations free: `53,123/udp`, `22,80,443/tcp` toward anywhere |
| `paranoid` | VM paranoid | Destinations bounded, taken from the site's address book |
| `local-only` | local-webui | Egress cut, and a web interface reachable from the host |

The **profile** is the name a human recognises; the **posture** is what the
spec carries. They are separated on purpose: it is what allows serving
something else on the same posture.

## The golden rule

The couple *(posture, real data)* is refused **before the machine exists** —
the only moment at which a refusal costs nothing. Three fields, and none is
deduced from the others:

- `install.prod` — WHERE it installs;
- `posture` — WHAT THE NETWORK reaches;
- `real_data` — WHETHER the machine carries real data.

Confusing them produces the two symmetric accidents: a demo mock-up talking
to the whole Internet because it is "not production", and a production
machine confined to the point of no longer being able to update itself.

Only a posture whose destinations are bounded, whose rules are enforced and
whose mechanism catches container traffic may carry real data. Today that is
`local-only` alone — and a screen that offers a posture the guard will refuse
makes you answer a dozen more questions before saying so.

## Where the rules are laid, per backend

| Backend | How | When |
|---|---|---|
| libvirt / QEMU | cloud-init `write_files`, or the installer's `late_command` | **before** first boot |
| Proxmox VE | pushed into the guest after creation | **after** first boot — hence an open window |
| Lima | instance `provision:` block, `mode: system` | at first boot |

Lima **refuses** `local-only`: user-mode networking always gives egress, and
no instance setting removes it. Promising otherwise would be the reassuring
name the registry forbids itself.

## What is not held, and says so

A mechanism silent about what it does not apply is what makes people believe
in a confinement that does not exist. Four tokens, a closed vocabulary:

- `no-rendering` — the posture states a policy that nothing installs;
- `reload-failure-unseen` — a failed reload on a later boot is not reported;
- `containers-unproven` — container traffic crosses FORWARD, and no
  confrontation has measured it yet;
- `boot-window-open` — the rules arrive only once the machine answers.

## The address book

`paranoid` names seven roles and the deployment REFUSES until each has an
address. The book lives in three files that merge; the one tracked by git is
**refused by construction**, because an IP address outside `private/` becomes
public on the first push of a fork.

<!-- [fr] -->
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

<!-- [common] -->
```bash
# Ce qu'une posture rend, sans machine :
python3 -c "from script.posture import registry, rules; \
  print(rules.render_egress(registry.get_posture('connected'), ()))"
```
