#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'une VM a le droit d'atteindre, déclaré à un seul endroit.

Une POSTURE dit ce que le réseau autorise, et rien d'autre. Elle ne dit pas
ce qu'on installe sur la machine — ça, c'est un profil d'installation — ni où
on l'installe. Les trois se choisissent séparément, et les confondre est ce
qui produit une « machine de démonstration » qui parle à toute l'Internet.

TROIS CONSOMMATEURS la lisent : le déploiement de VM (quel genre de réseau),
la politique SSH (transfert d'agent, clés d'hôte) et le routage IA (les
fournisseurs distants sont-ils joignables). C'est pour cela qu'elle ne vit
chez AUCUN des trois : rangée chez le premier, elle se ferait recopier par
le deuxième.

DEUX NOMS HONNÊTES. « Allowlist » ne dit pas si la liste borne quelque
chose : une posture peut filtrer les PORTS en laissant les destinations
ouvertes à tout l'Internet, et s'annoncer « en liste blanche » sans rien
confiner. `destinations_bounded` et `ports_bounded` le disent séparément,
parce que ce sont deux garanties différentes et qu'une seule des deux
protège une donnée réelle.

`egress_enforced` DIT LA VÉRITÉ SUR LE CODE, et non sur l'intention : une
posture peut décrire une politique que rien n'applique encore. Une politique
déclarée sans mécanisme se comporte exactement comme l'absence de politique,
tout en donnant l'assurance du contraire — c'est le pire des deux mondes, et
ce champ est ce qui l'empêche de passer inaperçu.
"""

from __future__ import annotations

from typing import NamedTuple

# Le genre de réseau libvirt que la posture demande. « isolated » n'a pas de
# route vers l'extérieur du tout ; « nat » sort par l'hôte.
NETWORK_KINDS = ("isolated", "nat")

# La politique de sortie. « none » : rien ne sort. « allowlist » : ce qui est
# nommé sort. « nat » : tout sort.
EGRESS_KINDS = ("none", "allowlist", "nat")

# Le DNS que l'invité utilise. Une liste blanche qui laisse passer le DNS
# fuit — les noms demandés sortent en clair ; une qui le bloque casse apt.
# La politique est donc un CHOIX par posture, et non un oubli.
DNS_KINDS = ("none", "resolver", "host")

# Ce qu'on fait de la clé d'hôte. « throwaway » : machines jetables dont l'IP
# se réutilise, où la vérification refuserait une machine neuve à chaque fois.
HOST_KEY_POLICIES = ("throwaway", "accept-new", "strict")


class Posture(NamedTuple):
    """Ce que le réseau d'une VM autorise. Des données, aucun comportement.

    `destinations_bounded` : l'ensemble des destinations joignables est-il
    fini et nommé ? C'est la seule garantie qui protège une donnée réelle.

    `ports_bounded` : les ports sont-ils restreints ? Utile, mais borner les
    ports d'une destination ouverte à tout l'Internet ne confine rien.

    `egress_enforced` : du code applique-t-il cette politique aujourd'hui ?
    Faux, la posture n'est qu'une intention, et ce qui en dépend doit le
    savoir plutôt que de s'y fier.

    `covers_containers` : le mécanisme attrape-t-il le trafic des conteneurs ?
    Il traverse la chaîne FORWARD et non OUTPUT, donc un verrou accroché à
    OUTPUT laisse sortir tout ce qu'un conteneur émet, sans rien signaler.

    `forward_agent` : l'agent SSH peut-il être transféré ? Faux se traduit
    par un REFUS écrit, et non par une omission — omettre laisse croire que
    la question ne s'est pas posée.
    """

    name: str
    network_kind: str
    egress: str
    destinations_bounded: bool
    ports_bounded: bool
    dns: str
    egress_enforced: bool
    covers_containers: bool
    forward_agent: bool
    host_keys: str
    cloud: bool
    needs_forge: bool
    name_suffix: str


# `restricted` N'EXISTE PAS ICI, et c'est délibéré. Il déclarait une politique
# de liste blanche sans liste, se comportait donc comme une sortie libre, et
# donnait l'assurance du contraire. Une posture qui n'a pas de mécanisme n'est
# pas une posture — c'est un nom rassurant. Une épreuve interdit son retour.
POSTURES = {
    # Bac à sable : rien ne la contraint, et c'est assumé. Le nom dit ce
    # qu'elle est, aucune promesse à tenir.
    "open": Posture(
        name="open",
        network_kind="nat",
        egress="nat",
        destinations_bounded=False,
        ports_bounded=False,
        dns="host",
        egress_enforced=True,
        covers_containers=True,
        forward_agent=False,
        host_keys="throwaway",
        cloud=True,
        needs_forge=True,
        name_suffix="",
    ),
    # Connectée : les ports sont bornés, les destinations NON. Elle
    # s'annonçait « en liste blanche », ce qui laissait croire l'inverse :
    # une liste qui porte 0.0.0.0/0 sur 80 et 443 ne borne aucune
    # destination, elle borne des ports.
    "connected": Posture(
        name="connected",
        network_kind="nat",
        egress="allowlist",
        destinations_bounded=False,
        ports_bounded=True,
        dns="host",
        egress_enforced=False,
        covers_containers=False,
        forward_agent=False,
        host_keys="throwaway",
        cloud=True,
        needs_forge=True,
        name_suffix="-connected",
    ),
    # Paranoïde : destinations ET ports bornés, DNS par un résolveur nommé.
    # L'agent SSH est REFUSÉ : le transférer donnerait à la machine confinée
    # de quoi s'authentifier partout où l'agent le peut, ce qui annule le
    # confinement sans rien changer aux règles réseau.
    "paranoid": Posture(
        name="paranoid",
        network_kind="nat",
        egress="allowlist",
        destinations_bounded=True,
        ports_bounded=True,
        dns="resolver",
        egress_enforced=False,
        covers_containers=False,
        forward_agent=False,
        host_keys="throwaway",
        cloud=False,
        needs_forge=True,
        name_suffix="-paranoid",
    ),
    # Locale : rien ne sort. C'est la moitié « réseau » de ce qu'on appelait
    # « local-webui » ; l'autre moitié est un profil d'installation, et les
    # séparer est ce qui permet de servir autre chose sur la même posture.
    "local-only": Posture(
        name="local-only",
        network_kind="isolated",
        egress="none",
        destinations_bounded=True,
        ports_bounded=True,
        dns="none",
        egress_enforced=True,
        covers_containers=True,
        forward_agent=False,
        host_keys="throwaway",
        cloud=False,
        needs_forge=False,
        name_suffix="-local",
    ),
}

# L'ordre est celui du plus libre au plus contraint, et c'est aussi celui
# dans lequel un écran les propose : on descend vers la contrainte, on n'y
# tombe pas par défaut.
DEFAULT_POSTURE = "open"


def get_posture(name):
    """La posture `name`, ou None.

    Ne lève pas : une fiche peut nommer une posture retirée, et l'écran doit
    pouvoir le DIRE plutôt que de s'interrompre.
    """
    return POSTURES.get(name)


def posture_names():
    """Les noms dans l'ordre du registre, du plus libre au plus contraint."""
    return list(POSTURES)


def allows_real_data(posture) -> bool:
    """Des données réelles peuvent-elles vivre sous cette posture ?

    DÉDUIT, et non déclaré. Un champ de plus pourrait répondre « oui » sur
    une posture dont les destinations ne sont pas bornées, et c'est
    exactement la contradiction que la règle existe pour empêcher.

    Les trois conditions comptent, et chacune pour un chemin de fuite qui
    lui est propre : des destinations non bornées laissent la donnée sortir
    par la porte, une politique que rien n'applique ne borne rien du tout —
    si bien nommée soit-elle —, et un mécanisme qui manque le trafic des
    conteneurs la laisse sortir par la fenêtre pendant que les règles
    affichent complet.
    """
    if posture is None:
        return False
    return (
        posture.destinations_bounded
        and posture.egress_enforced
        and posture.covers_containers
    )
