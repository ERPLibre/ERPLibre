#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'extension GNOME vue des tests d'ERPLibre.

L'extension est un dépôt à part, cloné dans
script/gnome-extension/erplibre_home/ par Google Repo ou par
install_erplibre_home.sh : un checkout peut ne pas l'avoir. Un test qui lit
un de ses fichiers porte SANS_EXTENSION, et se dit sauté, avec la commande
qui la clone, au lieu d'échouer sur un fichier absent. metadata.json est le
témoin, comme pour erplibre_home_extension_present de
erplibre_home_settings.sh. L'extension elle-même se teste dans son dépôt.

Ce qu'un test lit du clone passe par CONTRACT.md : les fonctions
ci-dessous en tirent le tableau D-Bus, l'objet et l'interface, et le
tableau des enregistrements.

Sans le préfixe test_, le lanceur unitaire ne prend pas ce module pour un
fichier de tests.
"""

import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
CHEMIN = "script/gnome-extension/erplibre_home"
EXTENSION = RACINE / CHEMIN
PRESENTE = (EXTENSION / "metadata.json").is_file()

SANS_EXTENSION = unittest.skipUnless(
    PRESENTE, CHEMIN + " absent : make erplibre_home_install"
)

# Les types D-Bus simples : chacun compte pour un argument.
TYPES_SIMPLES = "ybnqiuxtdsogh"


def contrat():
    """Le texte de CONTRACT.md du clone.

    Les tests d'ERPLibre ne lisent du clone que ce que CONTRACT.md énonce,
    et les valeurs qu'il donne : le code de l'extension, sa forme, ses
    noms de constantes et l'endroit où elles vivent, changent librement
    tant que ses propres tests le tiennent au contrat."""
    return (EXTENSION / "CONTRACT.md").read_text(encoding="utf-8")


def contrat_a_plat():
    """CONTRACT.md, chaque suite de blancs réduite à une espace : une
    valeur que le texte coupe en fin de ligne se lit d'un seul tenant."""
    return re.sub(r"\s+", " ", contrat())


def valeur_du_contrat(motif):
    """La valeur que donne le groupe 1 de `motif` dans le contrat à plat,
    la même à chaque occurrence ; AssertionError s'il n'en donne aucune ou
    en donne plusieurs."""
    trouves = set(re.findall(motif, contrat_a_plat()))
    if len(trouves) != 1:
        raise AssertionError(
            "CONTRACT.md : %s donne %s" % (motif, sorted(trouves))
        )
    return trouves.pop()


def objet_et_interface():
    """(chemin d'objet, interface) que le contrat donne au bus D-Bus."""
    return (
        valeur_du_contrat(r"object `(/[^`]+)`"),
        valeur_du_contrat(r"interface `([\w.]+)`"),
    )


def methodes_promises():
    """{méthode: nombre d'arguments d'entrée} du tableau D-Bus du
    contrat. Chaque type d'entrée y est simple, d'une lettre : un type
    composé lèverait plutôt que de se compter faux."""
    methodes = {}
    for nom, entree in re.findall(
        r"^\s*\| `(\w+)` \|\s*`?([a-z]*)`?\s*\| `[a-z]+` \|$",
        contrat(),
        re.M,
    ):
        if entree.strip(TYPES_SIMPLES):
            raise AssertionError("%s : type composé %s" % (nom, entree))
        methodes[nom] = len(entree)
    return methodes


def enregistrements():
    """{enregistrement: {clé: type}} du tableau des enregistrements du
    contrat ; le type est text, integer ou number."""
    tableau = {}
    for nom, cle, type_ in re.findall(
        r"^\s*\| `([^`]+)` \| `(\w+)` \| (text|integer|number)\b",
        contrat(),
        re.M,
    ):
        tableau.setdefault(nom, {})[cle] = type_
    return tableau
