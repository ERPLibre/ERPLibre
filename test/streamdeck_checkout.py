#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une copie réduite du dépôt, pour lancer la passation du deck ou le
fragment make du Stream Deck sans dépendre des vrais jeux.

Les jeux sont un dépôt à part, cloné dans script/stream_deck/games/ : un
checkout peut ne pas les avoir, et la passation comme les cibles de jeux
refusent alors de tourner. copier_depot() pose la passation, la
bibliothèque des réglages et deck_lock.py, copiés du dépôt, et, avec
jeux=True, un faux games/ réduit à games_cli.py, le fichier que
deck_games_present cherche.

Sans le préfixe test_, le lanceur unitaire ne prend pas ce module pour un
fichier de tests.
"""

import shutil
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
FICHIERS = (
    "script/install/erplibre_home_handover.sh",
    "script/install/erplibre_home_settings.sh",
    "script/stream_deck/deck_lock.py",
)
JEUX = "script/stream_deck/games"


def copier_depot(destination, jeux=True):
    """Pose la copie sous `destination`, créé au besoin, et la rend en Path.
    Les fichiers copiés gardent leur mode : la passation reste
    exécutable."""
    destination = Path(destination)
    for relatif in FICHIERS:
        (destination / relatif).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RACINE / relatif, destination / relatif)
    if jeux:
        (destination / JEUX).mkdir(parents=True, exist_ok=True)
        (destination / JEUX / "games_cli.py").write_text(
            "import argparse\n", encoding="utf-8"
        )
    return destination
