#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les écosystèmes que le moteur découvre, lus dans ce qu'il imprime.

Le moteur n'offre pas de `--json` : ses cibles `instances`, `instance-courante`
et `instance-modeles` impriment un tableau et des phrases, faits pour un
humain. Ce module les lit.

**FERMÉ PAR DÉFAUT.** Une forme inattendue rend `None`, jamais une liste
partielle. Deviner coûterait plus cher que refuser : le nom lu sert à
BASCULER l'écosystème actif, et un nom mal découpé ferait basculer vers autre
chose — ou ferait croire qu'un écosystème a disparu. Un appelant qui reçoit
`None` dit « illisible » et nomme la commande à rejouer à la main.

Rien ici ne lance quoi que ce soit : le texte arrive de l'exécuteur.
"""

from __future__ import annotations

import os
import re
from typing import NamedTuple

# Le lien que le moteur bascule d'un écosystème à l'autre.
LIEN = "instance"

# Ce que le moteur imprime quand aucun dépôt frère ne porte de plan.
AUCUNE = "Aucune instance decouverte"

# L'en-tête du tableau, mot à mot. Sa présence dit que la suite est un
# tableau ; son absence, qu'on lit autre chose.
ENTETE = ("INSTANCE", "INDEX", "VLAN", "FEDERE", "PROD")

# La ligne qui ferme le tableau et explique l'astérisque.
PIED = "* = instance active"

# Le marqueur de l'écosystème monté, en première colonne.
ACTIF = "*"

# Ce que le moteur écrit dans la colonne FEDERE, et dans PROD.
FEDERE = {"oui": True, "LOCAL": False}
PRODUCTION = {"oui": True, "non": False, "?": None}

# La colonne VLAN d'un écosystème sans zone déclarée.
SANS_VLAN = "—"

# La phrase d'`instance-modeles` qui porte les index déjà pris.
PRIS = re.compile(r"Index fédérés déjà pris\s*:\s*(.+?)\s*\(", re.M)
AUCUN_PRIS = "aucun"

# Les bornes d'un index. Le moteur les tient — il refuse lui-même un index
# hors bornes, et c'est LUI l'autorité. Elles ne sont ici que pour PROPOSER
# un index libre, et le second octet d'une IPv4 est ce qui les fixe.
INDEX_MIN, INDEX_MAX = 0, 255


class Ecosysteme(NamedTuple):
    """Une ligne du tableau, telle que le moteur l'écrit."""

    nom: str
    index: int
    vlans: str
    federe: bool
    production: bool | None
    actif: bool


def _ligne(texte):
    """Un `Ecosysteme` depuis une ligne du tableau, ou None.

    La première colonne porte le marqueur et n'est pas séparée du reste par
    un blanc quand elle est vide : elle se lit par sa POSITION, le reste par
    ses blancs. Cinq champs exactement, sinon la forme a changé.
    """
    if not texte or texte[0] not in (ACTIF, " "):
        return None
    champs = texte[1:].split()
    if len(champs) != len(ENTETE):
        return None
    nom, index, vlans, federe, production = champs
    if federe not in FEDERE or production not in PRODUCTION:
        return None
    try:
        rang = int(index)
    except ValueError:
        return None
    return Ecosysteme(
        nom=nom,
        index=rang,
        vlans=vlans,
        federe=FEDERE[federe],
        production=PRODUCTION[production],
        actif=texte[0] == ACTIF,
    )


def lit_instances(sortie):
    """Les écosystèmes découverts, `()` s'il n'y en a aucun, None si la
    forme n'est pas celle attendue.

    `()` et None sont deux nouvelles différentes : la première dit « rien à
    monter, en créer un », la seconde « le moteur a répondu autre chose que
    ce que cette version sait lire ».
    """
    lignes = (sortie or "").splitlines()
    if any(ligne.lstrip().startswith(AUCUNE) for ligne in lignes):
        return ()
    entete = next(
        (
            i
            for i, ligne in enumerate(lignes)
            if tuple(ligne.split()) == ENTETE
        ),
        None,
    )
    if entete is None:
        return None
    trouves = []
    for ligne in lignes[entete + 1 :]:
        if not ligne.strip() or ligne.lstrip().startswith(PIED):
            break
        lu = _ligne(ligne)
        if lu is None:
            return None
        trouves.append(lu)
    # Un en-tête sans une seule ligne est une forme inattendue : le moteur
    # dit « aucune instance » par une phrase, jamais par un tableau vide.
    return tuple(trouves) or None


def lit_courante(sortie):
    """Le nom de l'écosystème monté, `""` si aucun, None si illisible.

    Le moteur écrit « instance -> ../<nom> », ou « instance -> (non monté) ».
    Le chemin est rendu à son dernier segment : c'est le nom que
    `instance-utiliser` attend en retour.
    """
    for ligne in (sortie or "").splitlines():
        gauche, fleche, droite = ligne.partition("->")
        if not fleche or gauche.split() != ["instance"]:
            continue
        cible = droite.strip()
        if not cible:
            return None
        if cible.startswith("(") and cible.endswith(")"):
            return ""
        return cible.rstrip("/").rsplit("/", 1)[-1]
    return None


def lit_modeles(sortie):
    """(modèles, index déjà pris) depuis `instance-modeles`, ou None.

    Les modèles s'écrivent indentés, un par ligne, avant la phrase qui
    porte les index. Une sortie sans cette phrase n'est pas celle qu'on
    croit lire.
    """
    texte = sortie or ""
    prise = PRIS.search(texte)
    if prise is None:
        return None
    brut = prise.group(1).strip()
    if brut == AUCUN_PRIS:
        pris = ()
    else:
        nombres = re.findall(r"-?\d+", brut)
        if not nombres:
            return None
        pris = tuple(int(n) for n in nombres)
    modeles = tuple(
        ligne.strip()
        for ligne in texte[: prise.start()].splitlines()
        if ligne.startswith(" ") and ligne.strip()
    )
    return modeles, pris


def index_libre(pris, mini=INDEX_MIN, maxi=INDEX_MAX):
    """Le plus petit index libre dans les bornes, ou None s'il n'y en a pas.

    Ce n'est qu'une PROPOSITION : le moteur valide lui-même l'index reçu et
    refuse une collision fédérée. Proposer épargne à l'opérateur de lire un
    tableau pour trouver un trou ; cela ne le dispense pas de choisir.
    """
    occupes = set(pris)
    for rang in range(mini, maxi + 1):
        if rang not in occupes:
            return rang
    return None


def monte(moteur):
    """Le nom de l'écosystème monté sous `moteur`, lu sur le lien.

    `""` quand rien n'est monté. Un lien BRISÉ garde son nom : un écran doit
    pouvoir dire « monté sur X, qui n'existe plus » plutôt que « rien »,
    faute de quoi l'opérateur cherche une panne là où il y a un lien à
    refaire. NE LANCE PERSONNE : ce nom s'affiche en tête de chaque écran.
    """
    try:
        lien = os.path.join(moteur, LIEN)
        if os.path.islink(lien):
            return os.path.basename(os.path.realpath(lien))
    except (OSError, ValueError, TypeError):
        return ""
    return ""
