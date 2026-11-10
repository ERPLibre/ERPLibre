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

Sans le préfixe test_, le lanceur unitaire ne prend pas ce module pour un
fichier de tests.
"""

import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
CHEMIN = "script/gnome-extension/erplibre_home"
EXTENSION = RACINE / CHEMIN
PRESENTE = (EXTENSION / "metadata.json").is_file()

SANS_EXTENSION = unittest.skipUnless(
    PRESENTE, CHEMIN + " absent : make erplibre_home_install"
)
