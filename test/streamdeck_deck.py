#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le programme du deck vu des tests d'ERPLibre.

Le programme du deck (le paquet erplibre_streamdeck, le contrôleur, le
verrou du deck, le traducteur) est un dépôt à part, cloné dans
script/stream_deck/deck/ par Google Repo ou par
install_erplibre_home.sh --stream-deck : un checkout peut ne pas l'avoir.
Un test qui lit un de ses fichiers, ou importe un de ses modules, porte
SANS_DECK, et se dit sauté, avec la commande qui le clone, au lieu
d'échouer sur un fichier absent. erplibre_streamdeck/__main__.py est le
témoin, comme pour deck_repo_present de erplibre_home_settings.sh. Le deck
lui-même se teste dans son dépôt.

Sans le préfixe test_, le lanceur unitaire ne prend pas ce module pour un
fichier de tests.
"""

import importlib.util
import re
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
CHEMIN = "script/stream_deck/deck"
DECK = RACINE / CHEMIN
PRESENT = (DECK / "erplibre_streamdeck/__main__.py").is_file()

SANS_DECK = unittest.skipUnless(
    PRESENT, CHEMIN + " absent : make erplibre_home_streamdeck_install"
)


def importable():
    """Met la racine du clone en tête de sys.path, une seule fois, pour
    importer erplibre_streamdeck ; rend PRESENT. Sans le clone, sys.path
    ne change pas."""
    if PRESENT and str(DECK) not in sys.path:
        sys.path.insert(0, str(DECK))
    return PRESENT


def charger(nom, chemin):
    """Charge un module du clone par son chemin, relatif à sa racine : les
    fichiers de sa racine ne forment pas un paquet."""
    spec = importlib.util.spec_from_file_location(nom, DECK / chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def version_du_contrat():
    """(MAJEURE, MINEURE) de la ligne « **Contract version: X.Y** » du
    CONTRACT.md du clone ; AssertionError s'il n'en porte pas exactement
    une."""
    texte = (DECK / "CONTRACT.md").read_text(encoding="utf-8")
    versions = re.findall(
        r"^\*\*Contract version: (\d+)\.(\d+)\*\*$", texte, re.M
    )
    if len(versions) != 1:
        raise AssertionError("CONTRACT.md : versions %s" % versions)
    return tuple(int(nombre) for nombre in versions[0])
