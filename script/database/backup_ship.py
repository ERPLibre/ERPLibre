#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Déposer une sauvegarde vérifiée AILLEURS, et prouver qu'elle y est.

CE QUE LE DÉPÔT PROMETTAIT SANS LE TENIR. « backup-target » est dans le
SOCLE des destinations de sortie — le jeu que toute posture bornée nomme —
avec son port et sa raison écrite : « La cible des sauvegardes. L'ouvrir en
sortie est ce qui permet de sauvegarder sans monter le disque de la machine
sur l'hôte. » Le pare-feu d'une VM confinée ouvrait donc cette porte, et il
n'y avait rien derrière.

CE QUI SE VÉRIFIE À DISTANCE, ET CE QUI NE SE VÉRIFIE PAS. Les cinq
contrôles de `backup_verify` sont du Python : les rejouer là-bas demanderait
d'y pousser du code, donc d'y installer un dépôt. Ce qui se prouve sans
mentir est que les OCTETS sont arrivés entiers — une empreinte des deux
côtés. Le verdict dit donc « déposée, empreinte identique », jamais « saine
là-bas ».

Ce module ne joint rien : le transport est INJECTÉ, ce qui rend la décision
vérifiable sans machine.
"""

from __future__ import annotations

import hashlib
import os
import shlex
from typing import NamedTuple

# Le vocabulaire des verdicts, clos. « Rien lu » n'est pas « différent » :
# l'un dit qu'on n'a pas pu regarder, l'autre qu'on a regardé — et les
# confondre ferait passer une panne de transport pour une archive corrompue.
SHIPPED = "shipped"
MISMATCH = "mismatch"
UNREACHABLE = "unreachable"
REFUSED = "refused"
VERDICTS = (SHIPPED, MISMATCH, UNREACHABLE, REFUSED)

# Ce qu'on demande à la cible pour relire ce qu'elle a reçu. Nommé ici et
# nulle part ailleurs : recopié chez un appelant, il deviendrait une
# divergence le jour où l'outil change de nom.
FINGERPRINT_TOOL = "sha256sum"

# Par blocs : une sauvegarde de production tient rarement en mémoire, et la
# lire d'un bloc ferait payer sa taille en RAM sur la machine qui la produit.
CHUNK = 1 << 20


# Le nom sous lequel l'archive VOYAGE. Distinct du nom final, et retiré
# quand l'envoi échoue : c'est ce qui fait que le nom d'une sauvegarde ne
# désigne jamais autre chose qu'une sauvegarde entière et vérifiée.
SUFFIXE_PARTIEL = ".partiel"


def remote_path(target: dict, name: str) -> str:
    """Où l'archive se pose chez la cible. Lève si le nom sort du chemin.

    Le nom vient d'une saisie : un « ../ » écrirait hors du répertoire que
    la cible a donné, et un chemin absolu ignorerait ce répertoire tout
    court. Le contrôle se fait ICI parce que c'est le seul endroit qui
    compose les deux.
    """
    base = str((target or {}).get("path") or "").strip()
    if not base:
        raise ValueError("La cible ne nomme aucun chemin distant.")
    propre = str(name or "").strip()
    if not propre:
        raise ValueError("Aucun nom d'archive.")
    if propre.startswith("/") or ".." in propre.split("/"):
        raise ValueError(
            f"« {propre} » sortirait du chemin de la cible : le nom d'une"
            " archive ne remonte pas."
        )
    return f"{base.rstrip('/')}/{propre}"


def local_fingerprint(path: str) -> str:
    """L'empreinte des octets du fichier, lue par blocs."""
    empreinte = hashlib.sha256()
    with open(path, "rb") as fichier:
        for bloc in iter(lambda: fichier.read(CHUNK), b""):
            empreinte.update(bloc)
    return empreinte.hexdigest()


def fingerprint_command(chemin: str) -> str:
    """Ce qu'on demande à la cible. Le chemin est cité par l'appelant."""
    return f"{FINGERPRINT_TOOL} {chemin}"


def parse_fingerprint(sortie: str):
    """L'empreinte que la cible a rendue, ou None si rien n'a été lu.

    L'outil rend « <empreinte>  <chemin> » : n'en garder que le premier mot,
    sinon la comparaison porte aussi sur le chemin, qui diffère des deux
    côtés par construction.
    """
    premier = (sortie or "").strip().split()
    return premier[0] if premier else None


def compare(local: str, distant) -> str:
    """Le verdict du dépôt, depuis les deux empreintes."""
    if not distant:
        return UNREACHABLE
    return SHIPPED if local == distant else MISMATCH


class Shipping(NamedTuple):
    """Ce que le dépôt a donné, et de quoi l'écrire.

    `detail` est la ligne qui APPREND quelque chose — le chemin visé, ou ce
    que la cible a répondu — et non la répétition du verdict.
    """

    verdict: str
    detail: str = ""
    remote: str = ""


def ship(
    target: dict, host: dict, local: str, name: str, run, ask=input
) -> Shipping:
    """Dépose l'archive chez la cible, et relit ce qui y est arrivé.

    QUATRE TEMPS, ET CHACUN PEUT S'ARRÊTER. Le chemin se compose et se
    refuse s'il sort du répertoire de la cible ; une archive qui s'y trouve
    déjà fait RETAPER son nom, parce que l'écraser est destructeur et que
    le nom par défaut porte la date à la seconde — une collision est donc
    une décision, jamais un hasard ; l'envoi passe par l'entrée standard du
    transport, sous masque, parce que la charge est un dump de production ;
    et la relecture compare les octets des deux côtés.

    Un envoi qui échoue ne PRÉTEND PAS relire : demander son empreinte à
    une cible muette rendrait « rien lu », qui se lit comme un transport en
    panne alors que c'est l'envoi qui n'a pas eu lieu.

    DEUX DICTS, et ils ne se confondent pas : `target` est ce qu'on écrit
    et relit — son chemin distant en vient — et `host` est la fiche que le
    transport consomme. C'est la distinction que `deploy_target.fiche` a
    déjà posée ; la perdre ferait passer un nom d'écran dans une ligne ssh.

    `run` et `ask` sont injectés : la décision se vérifie sans machine.
    """
    try:
        distant = remote_path(target, name)
    except ValueError as refus:
        return Shipping(REFUSED, str(refus))
    cite = shlex.quote(distant)

    code, _sortie = run(host, f"test -e {cite}")
    if code == 0:
        print_detail = (
            f"{distant} existe déjà chez la cible et serait écrasée."
        )
        if str(ask(distant)).strip() != name:
            return Shipping(REFUSED, print_detail, distant)

    # LE NOM DÉFINITIF NE PARAÎT QU'AU BOUT. Une redirection CRÉE le
    # fichier avant le premier octet : un transport coupé laissait sinon,
    # chez la cible, une archive tronquée sous le nom exact d'une vraie
    # sauvegarde — au seul endroit où l'on ira chercher le jour d'une
    # panne, et aucun des contrôles locaux ne se rejoue là-bas.
    travail = distant + SUFFIXE_PARTIEL
    cite_travail = shlex.quote(travail)

    # SOUS MASQUE, et non par un chmod après : une redirection ne prend pas
    # de mode, et la charge serait lisible de tous le temps de son écriture.
    with open(local, "rb") as flux:
        code, sortie = run(
            host, f"umask 0077 && cat > {cite_travail}", entree=flux
        )
    if code:
        # RETIRÉ, et non laissé : un nom de travail qui traîne ferait
        # échouer la reprise sur la garde de collision, pour un fichier
        # mort.
        run(host, f"rm -f {cite_travail}")
        return Shipping(UNREACHABLE, sortie or "envoi refusé", distant)

    code, sortie = run(host, fingerprint_command(cite_travail))
    distante = parse_fingerprint(sortie if code == 0 else "")
    verdict = compare(local_fingerprint(local), distante)
    if verdict != SHIPPED:
        run(host, f"rm -f {cite_travail}")
        return Shipping(verdict, sortie.strip(), distant)

    # RENOMMAGE DANS LE MÊME RÉPERTOIRE, donc atomique : il n'existe aucun
    # instant où le nom final désigne un fichier incomplet.
    code, sortie_mv = run(host, f"mv -f {cite_travail} {cite}")
    if code:
        # Le contenu est bon et n'est pas à sa place : dire « déposé »
        # enverrait chercher un fichier qui n'existe pas.
        return Shipping(UNREACHABLE, sortie_mv or "renommage refusé", distant)
    return Shipping(verdict, sortie.strip(), distant)
