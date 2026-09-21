#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le carnet d'adresses du site : qui a le droit d'être joint, et d'où.

SANS LUI, LE SEUL PROFIL QUI CONFINE EST INUTILISABLE. « VM paranoid »
nomme sept rôles, et le déploiement REFUSE tant que l'un d'eux n'a pas
d'adresse — « dns-resolver n'a pas d'adresse dans la configuration du
site ». Rien dans le dépôt n'écrivait ce carnet : le mécanisme complet
existait, et le premier pas manquait.

TROIS FICHIERS SE FUSIONNENT, ET LEUR NATURE DIFFÈRE.

`script/todo/todo.json` SUIT LE DÉPÔT. Le carnet ne contient que des
ADRESSES — l'allowlist refuse un nom d'hôte, « le résoudre figerait
l'adresse » — et une adresse IP hors de `private/` devient publique au
premier envoi du fork. Ce fichier est donc REFUSÉ, par son nom, plutôt que
d'être lu.

`private/todo/todo_override.json` se tient à la main et peut être commité
sur un dépôt PRIVÉ : c'est le carnet que l'équipe partage.

`private/todo/todo_override_private.json` est celui que ce module écrit, en
0600 atomique. C'est le carnet de CETTE machine.

LA FUSION ÉTEND LES LISTES, ELLE NE LES REMPLACE PAS. Un rôle présent dans
deux fichiers porte donc la réunion de leurs adresses, et retirer la
sienne ne retire pas celle de l'équipe. Un écran qui promettrait la
suppression mentirait : `shared_networks` dit ce qu'une suppression ne
pourra pas atteindre.
"""
from __future__ import annotations

import json
import os

from script.config import config_file as config_module
from script.config.config_file import ConfigFile
from script.lib_valid import ValidationError
from script.posture import allowlist

# La clé de section, dans les trois fichiers de configuration.
BOOK_KEY = "egress_destinations"

# D'où vient une adresse. Les jetons sont clos : un quatrième fichier se
# déclare ici, où les appelants le verront.
TRACKED = "tracked"
TEAM = "team"
MACHINE = "machine"
SOURCES = (TRACKED, TEAM, MACHINE)


# Le fichier de chaque source. Les CHEMINS sont relus à l'appel et non
# figés à l'import : les épreuves les déplacent dans un temporaire, et une
# constante importée par valeur écrirait dans le vrai carnet de qui les
# lance.
def _fichiers() -> dict:
    return {
        TRACKED: config_module.CONFIG_FILE,
        TEAM: config_module.CONFIG_OVERRIDE_FILE,
        MACHINE: config_module.CONFIG_OVERRIDE_PRIVATE_FILE,
    }


def _lire(chemin) -> dict:
    """Le carnet d'UN fichier, {} s'il est absent ou illisible.

    Illisible n'est pas vide : un JSON tronqué doit laisser le reste
    fonctionner, parce que le carnet d'un fichier n'engage pas les autres.
    """
    if not chemin or not os.path.exists(chemin):
        return {}
    try:
        with open(chemin, encoding="utf-8") as fichier:
            charge = json.load(fichier)
    except (OSError, ValueError):
        return {}
    carnet = charge.get(BOOK_KEY) if isinstance(charge, dict) else None
    return carnet if isinstance(carnet, dict) else {}


def tracked_roles() -> tuple:
    """Les rôles écrits dans le fichier SUIVI, qu'il ne doit pas porter.

    Vide est l'état correct. Non vide, une adresse du site est en route
    vers le dépôt public — et c'est la seule chose de ce module qui soit
    une faute et non un réglage.
    """
    return tuple(sorted(_lire(_fichiers()[TRACKED])))


def refuse_tracked() -> None:
    """Lève si le fichier suivi porte un carnet. Ne rend rien.

    Nommé pour être appelé AVANT toute lecture : lire d'abord donnerait un
    déploiement qui marche, et la fuite ne se verrait jamais.
    """
    roles = tracked_roles()
    if not roles:
        return
    raise ValidationError(
        f"« {BOOK_KEY} » se trouve dans {config_module.CONFIG_FILE}, que"
        " git suit. Le carnet ne contient que des adresses, et une adresse"
        " y devient publique. Déplacer ces rôles dans private/ :"
        f" {', '.join(roles)}."
    )


def read(config=None) -> dict:
    """Le carnet que le déploiement voit, fusion comprise.

    Refuse d'abord le fichier suivi : rendre le carnet puis signaler la
    fuite laisserait un déploiement réussi derrière lui.
    """
    refuse_tracked()
    cfg = config or ConfigFile()
    carnet = cfg.get_config(BOOK_KEY)
    return carnet if isinstance(carnet, dict) else {}


def _reseaux(entree) -> list:
    """Les réseaux d'une entrée, quelle que soit sa forme."""
    if isinstance(entree, dict):
        valeur = entree.get("networks", ())
    else:
        valeur = entree
    if isinstance(valeur, str):
        return [valeur]
    return list(valeur or ())


def shared_networks(role: str) -> list:
    """Les adresses de ce rôle qu'une suppression ICI ne retirera PAS.

    Elles vivent dans le fichier de l'équipe ou dans le fichier suivi, et
    la fusion ÉTEND les listes : les retirer du carnet de la machine les
    laisse dans la liste blanche. Le dire est ce qui évite de croire une
    adresse retirée alors qu'elle est encore ouverte.
    """
    ailleurs = []
    for source in (TRACKED, TEAM):
        ailleurs.extend(_reseaux(_lire(_fichiers()[source]).get(role)))
    return ailleurs


def machine_book() -> dict:
    """Le carnet de CETTE machine seul, celui que ce module écrit.

    L'écriture doit repartir de lui et non de la fusion : réécrire la
    fusion recopierait les adresses de l'équipe dans le fichier de la
    machine, qui se retrouveraient alors en DOUBLE à la lecture suivante.
    """
    return dict(_lire(_fichiers()[MACHINE]))


def validate(role: str, networks, ports=()) -> tuple:
    """(réseaux, ports) contrôlés, ou ValidationError.

    Le contrôle est celui de l'allowlist, et il a lieu À LA SAISIE. Il
    avait lieu au DÉPLOIEMENT : une faute de frappe se découvrait après un
    formulaire entier, sur le refus d'un rôle qu'on croyait bon.
    """
    permis = allowlist.resolve(role, networks, ports)
    return tuple(permis.networks), tuple(permis.ports)


def save(role: str, networks, ports=(), config=None) -> dict:
    """Valide puis écrit le rôle dans le carnet de la machine.

    N'écrit RIEN si la saisie est refusée : un carnet à moitié valide se
    relit sans se plaindre, et la panne se découvre au déploiement.
    """
    reseaux, ports_propres = validate(role, networks, ports)
    carnet = machine_book()
    # LES PORTS NE SONT ÉCRITS QUE SI LE SITE EN A DONNÉ. `resolve` remplit
    # ceux du rôle quand l'appelant se tait — les recopier ici en ferait une
    # copie FIGÉE de ce que le dépôt possède : un rôle qui gagnerait un port
    # demain garderait l'ancien dans le carnet, et la liste blanche
    # fermerait un port que le dépôt croit ouvert.
    carnet[role] = (
        {"networks": list(reseaux), "ports": list(ports_propres)}
        if ports
        else list(reseaux)
    )
    (config or ConfigFile()).set_config_value([BOOK_KEY], carnet)
    return carnet


def forget(role: str, config=None) -> bool:
    """Retire le rôle du carnet de la MACHINE. Rend False s'il n'y était pas.

    Faux ne veut pas dire « pas d'adresse » : le rôle peut vivre dans le
    carnet de l'équipe, que ce module ne touche pas. `shared_networks` dit
    ce qui reste.
    """
    carnet = machine_book()
    if role not in carnet:
        return False
    del carnet[role]
    (config or ConfigFile()).set_config_value([BOOK_KEY], carnet)
    return True
