#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un objet, un maître : ce que todo ne doit pas toucher sur une grappe.

Les deux outils travaillent sur la même grappe Proxmox et chacun ne garde que
SES objets. Le menu Proxmox de todo propose donc le gabarit et les VM d'un
plan Set-OPS à l'effacement, reconfigure sans contrôle une VM posée sur un
VMID déclaré, et pose une posture de sortie ou une dérogation de cache sur un
invité que le moteur administre déjà. Ce module donne de quoi le refuser.

DEUX MARQUEURS, LUS SUR LA GRAPPE ET DANS LE PLAN. Le moteur verse chaque VM
dans un POOL qui porte le nom de son dépôt d'écosystème, et il DÉRIVE un VMID
de neuf chiffres — VLAN sur quatre, hôte sur trois, rang sur deux. Le pool dit
l'appartenance déclarée ; la forme du VMID rattrape une VM qu'on a sortie de
son pool à la main.

LE POOL NOMMÉ « Set-OPS » N'EST PAS UN MARQUEUR. Une grappe de référence en
porte un, qui regroupe des VM ANTÉRIEURES au moteur ; le moteur n'y verse
rien et n'y touche pas. Le confondre avec un pool du moteur ferait refuser
des gestes sur des machines dont todo est légitimement le maître.

FERMÉ PAR DÉFAUT. Quand la grappe ou le plan ne se lisent pas, l'état rendu
est `INCONNU`, et l'appelant refuse : sans preuve d'appartenance, aucun geste.
C'est le même parti que « ne libérer que ce qui se prouve orphelin ».
"""

from __future__ import annotations

import json
from typing import NamedTuple

# Le VMID que le moteur dérive fait toujours neuf chiffres : le VLAN en porte
# quatre (1000 + index x 10 + zone, borné sous les 4094 du 802.1Q), l'hôte
# trois, le rang deux. Un VMID plus court n'a pas pu être dérivé.
VMID_CHIFFRES = 9

# Le pool des machines du génome — cache, forge, AC, noms, dépôt. Il ne
# dérive d'aucun index : elles sont l'infrastructure SUR laquelle les index
# vivent, et le nom reste le même d'un hébergeur à l'autre.
POOL_SITE = "Site-OPS"

# L'ANCIEN MONDE, à ne pas prendre pour un marqueur. Voir l'en-tête.
POOL_ANCIEN = "Set-OPS"

# Le vocabulaire des états, et il est CLOS. Quatre mots, parce que « libre »
# et « lecture impossible » ne se confondent pas : le premier autorise, le
# second refuse.
LIBRE = "libre"
GERE = "gere"
DERIVE = "derive"
INCONNU = "inconnu"
ETATS = (LIBRE, GERE, DERIVE, INCONNU)

# Ce qu'un geste de todo fait d'un invité que le moteur administre. Le
# vocabulaire est CLOS lui aussi, et le plus strict est le DÉFAUT : un geste
# neuf qui ne se déclare pas hérite du refus, jamais du silence.
AUCUNE = "aucune"
RETAPER = "retaper"
REFUS = "refus"
GARDES = (AUCUNE, RETAPER, REFUS)


class Declaration(NamedTuple):
    """Ce que les plans des écosystèmes découverts déclarent.

    `pools` sont les noms de pool attendus ; `proprietaire` associe chaque
    VMID déclaré au (pool, nom) que le plan lui donne. Le NOM sert à
    distinguer une VM de la flotte déjà matérialisée — mais pas encore
    versée dans son pool — d'une VM étrangère qui occuperait le même VMID.
    Les deux viennent du même devis, d'un seul appel au moteur.
    """

    pools: frozenset
    proprietaire: dict


class Invite(NamedTuple):
    """Une VM telle que la grappe la décrit."""

    vmid: int
    nom: str
    noeud: str
    pool: str


def vmid_derive(vmid) -> bool:
    """Le VMID a-t-il la forme que le moteur dérive ?

    La forme seule ne prouve pas l'appartenance — un exploitant peut avoir
    tapé neuf chiffres à la main — mais elle la rend assez probable pour
    qu'on ne détruise pas sans demander.
    """
    if isinstance(vmid, bool) or not isinstance(vmid, int) or vmid < 0:
        return False
    return len(str(vmid)) == VMID_CHIFFRES


def lit_devis(sortie):
    """La `Declaration` que porte le devis des pools, ou None.

    Le moteur rend ce devis en JSON, et la recette `make` ÉCHO la commande
    avant lui : la lecture commence donc à la première accolade. Tout ce qui
    n'a pas la forme attendue — document tronqué, pools sans nom, VMID qui
    n'est pas un entier — rend None plutôt qu'une déclaration partielle, qui
    ferait passer pour libre un VMID que le plan revendique.
    """
    texte = sortie or ""
    debut = texte.find("{")
    if debut < 0:
        return None
    try:
        lu, _fin = json.JSONDecoder().raw_decode(texte[debut:])
    except ValueError:
        return None
    if not isinstance(lu, dict):
        return None
    blocs = lu.get("pools")
    if not isinstance(blocs, list):
        return None
    pools, proprietaire = set(), {}
    for bloc in blocs:
        if not isinstance(bloc, dict):
            return None
        nom = bloc.get("pool")
        if not isinstance(nom, str) or not nom.strip():
            return None
        pools.add(nom.strip())
        membres = bloc.get("membres")
        if not isinstance(membres, list):
            return None
        for membre in membres:
            if not isinstance(membre, dict):
                return None
            vmid = membre.get("vmid")
            # Borne alignée sur `vmid_derive` : un VMID nul ou négatif
            # n'existe pas sur Proxmox, et -1 est la sentinelle que
            # l'appelant fabrique pour « VMID illisible ».
            if isinstance(vmid, bool) or not isinstance(vmid, int) or vmid < 1:
                return None
            # DEUX POOLS SUR UN VMID N'ONT PAS DE MAÎTRE. Écraser le premier
            # ferait nommer le mauvais dépôt à l'écran de refus, et ferait
            # accuser la VM légitime du premier pool d'occuper un VMID
            # « prévu » pour le second. Le moteur porte ce contrôle dans son
            # « --verifier », qui rend AVANT d'imprimer le JSON : la lecture
            # d'ici ne le voit donc jamais.
            if vmid in proprietaire:
                return None
            declare = membre.get("nom")
            proprietaire[vmid] = (
                nom.strip(),
                declare.strip() if isinstance(declare, str) else "",
            )
    # Le pool du site ne dérive d'aucun index : le devis le nomme quand des
    # machines de génome existent, et son absence ne dit rien.
    return Declaration(frozenset(pools), proprietaire)


def etat(invite, devis):
    """(état, maître) de `invite` : todo peut-il le toucher ?

    `devis` vaut None quand le plan n'a pas pu être lu — l'état est alors
    `INCONNU` pour tout le monde, y compris pour une VM dont le VMID n'a
    rien de dérivé : sans plan, on ne peut pas dire qu'elle est libre.

    L'ordre des trois lectures va du plus sûr au plus probable : un VMID que
    le plan REVENDIQUE nomme son pool ; un pool attendu nomme lui-même ; une
    forme de VMID dérivée n'accuse personne mais suffit à ne pas détruire.
    """
    if devis is None or invite is None:
        return INCONNU, ""
    pool = (invite.pool or "").strip()
    # LE POOL DU SITE SE RECONNAÎT SANS LE DEVIS. Il ne dérive d'aucun index
    # et son nom ne change pas d'un hébergeur à l'autre ; le devis, lui, ne
    # le nomme que si un underlay est monté. Sans ce raccourci, les machines
    # du génome — cache, forge, AC, noms, dépôt, gabarit doré — reviennent
    # LIBRES, et leur VMID ne dérive de rien qui les rattrape.
    if pool == POOL_SITE:
        return GERE, POOL_SITE
    revendique = devis.proprietaire.get(invite.vmid)
    if revendique:
        return GERE, revendique[0]
    if pool and pool != POOL_ANCIEN and pool in devis.pools:
        return GERE, pool
    if vmid_derive(invite.vmid):
        return DERIVE, ""
    return LIBRE, ""


def vmid_revendique(vmid, devis):
    """Le pool qui DÉCLARE ce VMID, « » si aucun, None si le plan est illisible.

    Sert au déploiement : créer une VM sur un VMID qu'un plan revendique la
    rendrait indiscernable de celle que le moteur posera, et la collision ne
    se verrait qu'au moment où le moteur matérialise la sienne.
    """
    if devis is None:
        return None
    revendique = devis.proprietaire.get(vmid)
    return revendique[0] if revendique else ""


class Collision(NamedTuple):
    """Un VMID que le plan déclare et qu'une VM étrangère occupe déjà."""

    vmid: int
    declare_par: str
    nom_declare: str
    occupe_par: str
    pool_occupant: str


def collisions(invites, devis):
    """Les collisions de VMID entre le plan et ce que porte la grappe.

    C'EST LE CONSTAT QUI COÛTE LE PLUS CHER. Une flotte ne renomme pas ses
    machines pour contourner un VMID pris : on change l'INDEX de la flotte et
    on régénère — sauvegarder, raser, changer l'index, déployer, restaurer.
    Le constat doit donc tomber AVANT un déploiement, pas pendant.

    Une VM n'entre pas en collision avec elle-même : celle du plan déjà
    matérialisée porte soit le pool qui la déclare, soit le nom que le plan
    lui donne. Le nom rattrape la VM posée mais pas encore versée dans son
    pool, que le pool seul ferait passer pour une étrangère.

    Rend None quand l'un des deux côtés ne se lit pas : sans les deux, une
    absence de collision ne prouverait rien.
    """
    if devis is None or invites is None:
        return None
    trouvees = []
    for invite in invites:
        revendique = devis.proprietaire.get(invite.vmid)
        if not revendique:
            continue
        pool_declare, nom_declare = revendique
        occupant = (invite.pool or "").strip()
        if occupant == pool_declare:
            continue
        # LE RATTRAPAGE NE VISE QUE LA VM SANS POOL. L'homonymie est
        # VOULUE — le même nom court désigne la même fonction chez deux
        # locataires —, donc un nom qui concorde ne prouve rien dès que
        # l'occupant porte un pool. Appliqué largement, il avale le constat
        # le plus cher : une étrangère homonyme passerait pour la machine du
        # plan, et l'écran annoncerait « aucune collision ».
        if (
            not occupant
            and nom_declare
            and (invite.nom or "").strip() == nom_declare
        ):
            continue
        trouvees.append(
            Collision(
                vmid=invite.vmid,
                declare_par=pool_declare,
                nom_declare=nom_declare,
                occupe_par=(invite.nom or "").strip(),
                pool_occupant=occupant,
            )
        )
    return tuple(sorted(trouvees))
