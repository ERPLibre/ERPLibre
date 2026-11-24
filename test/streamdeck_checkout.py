#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une copie réduite du dépôt, pour lancer la passation du deck ou le
fragment make du Stream Deck sans dépendre des vrais jeux.

Les jeux et le programme du deck sont des dépôts à part, clonés dans
script/stream_deck/games/ et script/stream_deck/deck/ : un checkout peut ne
pas les avoir, et la passation comme les cibles de jeux refusent alors de
tourner. copier_depot() pose la passation et la bibliothèque des réglages,
copiées du dépôt ; avec jeux=True, un faux games/ réduit à games_cli.py, le
fichier que deck_games_present cherche ; avec deck=True, un clone du deck
réduit à son témoin, erplibre_streamdeck/__main__.py, que deck_repo_present
cherche, à un CONTRACT.md que deck_contract_ok lit, et au deck_lock.py du
vrai clone quand il est là. Le CONTRACT.md est celui du vrai clone quand
il est là, celui qui va avec son deck_lock.py ; sinon, ou avec contrat=,
une ligne « **Contract version: X.Y** » porte la version demandée, celle
de deck_contract par défaut.

Sans le préfixe test_, le lanceur unitaire ne prend pas ce module pour un
fichier de tests.
"""

import shutil
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
FICHIERS = (
    "script/install/erplibre_home_streamdeck_handover.sh",
    "script/install/erplibre_home_settings.sh",
    "script/stream_deck/deck_contract",
)
JEUX = "script/stream_deck/games"
DECK = "script/stream_deck/deck"


def copier_depot(destination, jeux=True, deck=True, contrat=None):
    """Pose la copie sous `destination`, créé au besoin, et la rend en Path.
    Les fichiers copiés gardent leur mode : la passation reste
    exécutable. `contrat`, une version « X.Y », remplace le CONTRACT.md du
    clone du deck par une ligne qui la porte."""
    destination = Path(destination)
    for relatif in FICHIERS:
        (destination / relatif).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RACINE / relatif, destination / relatif)
    if jeux:
        (destination / JEUX).mkdir(parents=True, exist_ok=True)
        (destination / JEUX / "games_cli.py").write_text(
            "import argparse\n", encoding="utf-8"
        )
    if deck:
        temoin = destination / DECK / "erplibre_streamdeck" / "__main__.py"
        temoin.parent.mkdir(parents=True, exist_ok=True)
        temoin.write_text("", encoding="utf-8")
        verrou = RACINE / DECK / "deck_lock.py"
        if verrou.is_file():
            shutil.copy2(verrou, destination / DECK / "deck_lock.py")
        reel = RACINE / DECK / "CONTRACT.md"
        if contrat is None and reel.is_file():
            shutil.copy2(reel, destination / DECK / "CONTRACT.md")
        else:
            if contrat is None:
                contrat = (
                    (RACINE / "script/stream_deck/deck_contract")
                    .read_text(encoding="utf-8")
                    .strip()
                )
            (destination / DECK / "CONTRACT.md").write_text(
                "# Contract\n\n**Contract version: %s**\n" % contrat,
                encoding="utf-8",
            )
    return destination
