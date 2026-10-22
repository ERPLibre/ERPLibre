#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les jeux du Stream Deck sont un dépôt à part, cloné dans
script/stream_deck/games/ ; le programme du deck et ses outils restent dans
script/stream_deck/.

Ce que ces tests gardent :

- ERPLibre ne suit aucun fichier de games/, qu'il ignore, ni aucun jeu à
  côté du programme du deck ;
- le manifeste des jeux suit leur branche main, à leur chemin ; seule
  conf/git_manifest_streamdeck.csv le nomme, que git_merge_repo_manifest.py
  ne lit que si les jeux sont là ou avec --with_streamdeck, comme pour le
  mobile : un serveur Odoo ne les clone pas ;
- games_contract porte une version MAJEUR.MINEUR, et des jeux clonés dont
  la version MAJEURE diffère font échouer la suite ;
- le menu TODO et la galerie trouvent exactement les jeux du clone.

Ce qui lit les vrais jeux est sauté, avec sa raison, quand games/ manque.
Les jeux eux-mêmes se testent dans leur dépôt (tests/test_contract.py).
"""

import csv
import importlib.util
import re
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
DECK_DIR = ROOT / "script" / "stream_deck"
GAMES_DIR = DECK_DIR / "games"
GAMES_PATH = "script/stream_deck/games"
MANIFESTE = "manifest/git_manifest_streamdeck_game.xml"
CONTRAT = DECK_DIR / "games_contract"
sys.argv = ["todo.py"]
from script.todo import todo as todo_mod  # noqa: E402

SANS_JEUX = unittest.skipUnless(
    (GAMES_DIR / "games_cli.py").is_file(),
    "script/stream_deck/games/ absent : make erplibre_home_streamdeck_install",
)


def git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True
    )


def charger(nom, chemin):
    """Charge un module par son chemin : games/ n'est pas un paquet."""
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LaFrontiere(unittest.TestCase):
    def test_erplibre_tracks_nothing_under_games(self):
        suivis = git("ls-files", GAMES_PATH)
        self.assertEqual(0, suivis.returncode, suivis.stderr)
        self.assertEqual("", suivis.stdout)

    def test_the_games_directory_is_ignored(self):
        for chemin in (GAMES_PATH + "/games_cli.py", GAMES_PATH + "/save/x"):
            with self.subTest(chemin=chemin):
                self.assertEqual(
                    0, git("check-ignore", "-q", chemin).returncode
                )

    def test_no_game_is_left_next_to_the_deck_program(self):
        self.assertEqual(
            "", git("ls-files", "script/stream_deck/game_*.py").stdout
        )

    def test_the_assets_stay_with_the_controller(self):
        self.assertTrue((DECK_DIR / "Assets").is_dir())
        self.assertTrue((DECK_DIR / "erplibre_controller.py").is_file())


class LeManifeste(unittest.TestCase):
    def setUp(self):
        self.racine = ET.parse(ROOT / MANIFESTE).getroot()
        (self.projet,) = [
            p
            for p in self.racine.iter("project")
            if p.get("path") == GAMES_PATH
        ]

    def test_it_follows_the_main_branch_of_the_games(self):
        """Une version MAJEURE du contrat qui change sur main touche tout
        checkout à sa prochaine mise à jour : LeContrat le surveille."""
        remotes = {
            r.get("name"): r.get("fetch") for r in self.racine.iter("remote")
        }
        self.assertEqual("streamdeck_game.git", self.projet.get("name"))
        self.assertEqual(
            "https://github.com/TechnoLibre/",
            remotes[self.projet.get("remote")],
        )
        self.assertEqual("main", self.projet.get("revision"))

    def test_only_the_streamdeck_list_names_it(self):
        """Les listes générales entrent dans toute fusion, celle d'un
        serveur Odoo comprise ; la liste du Stream Deck n'y entre que pour
        un checkout qui a les jeux."""
        for liste, nomme in (
            ("git_manifest_streamdeck.csv", True),
            ("git_manifest.csv", False),
            ("git_manifest_mobile.csv", False),
            ("git_manifest_odoo.csv", False),
        ):
            with self.subTest(liste=liste):
                with open(ROOT / "conf" / liste, encoding="utf-8") as fh:
                    fichiers = [l["filepath"] for l in csv.DictReader(fh)]
                self.assertEqual(nomme, MANIFESTE in fichiers)


class LeContrat(unittest.TestCase):
    def majeure(self, version):
        self.assertRegex(version, r"^\d+\.\d+$")
        return version.split(".")[0]

    def test_games_contract_holds_one_version(self):
        self.majeure(CONTRAT.read_text(encoding="utf-8").strip())

    @SANS_JEUX
    def test_the_cloned_games_share_its_major(self):
        """Une MAJEURE qui diffère : ERPLibre et les jeux ne s'entendent
        plus sur CONTRACT.md ; main des jeux a changé de MAJEURE sans que
        games_contract suive."""
        attendue = CONTRAT.read_text(encoding="utf-8").strip()
        clonee = charger(
            "games_cli", GAMES_DIR / "games_cli.py"
        ).CONTRACT_VERSION
        self.assertEqual(self.majeure(attendue), self.majeure(clonee))


@SANS_JEUX
class LEnTeteDActionDeLaGalerie(unittest.TestCase):
    """Une route de la galerie qui agit exige un en-tête (contrat 2.0) :
    l'extension GNOME l'envoie à /launch/<id>, sous le nom que la galerie
    du clone attend."""

    EXTENSION = ROOT / "script/gnome-extension/erplibre_home"

    def test_the_extension_sends_the_header_the_gallery_requires(self):
        galerie = charger("gallery_server", GAMES_DIR / "gallery_server.py")
        lib = (self.EXTENSION / "lib/gallery-launch.js").read_text(
            encoding="utf-8"
        )
        (nom,) = re.findall(
            r"export const GALLERY_ACTION_HEADER = '([^']+)';", lib
        )
        self.assertEqual(galerie.GameHandler.ACTION_HEADER, nom)
        controleur = (self.EXTENSION / "indicators/controller.js").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "get_request_headers().append(GALLERY_ACTION_HEADER, '1')",
            controleur,
        )


@SANS_JEUX
class LesVraisScans(unittest.TestCase):
    """Sans simulation : un chemin oublié ne montre qu'une liste vide."""

    def jeux_du_clone(self):
        return sorted(str(p) for p in GAMES_DIR.glob("game_*.py"))

    def test_todo_finds_exactly_the_games_of_games_dir(self):
        todo = todo_mod.TODO.__new__(todo_mod.TODO)
        trouves = sorted(g["path"] for g in todo._scan_streamdeck_games())
        self.assertIn(str(GAMES_DIR / "game_snake.py"), trouves)
        self.assertEqual(self.jeux_du_clone(), trouves)

    def test_the_gallery_lists_the_games_and_not_the_tiler(self):
        """Le vrai glob de la galerie ; seul « --meta » est simulé, car
        les jeux n'y répondent que sous .venv.streamdeck, qui porte leurs
        dépendances."""
        galerie = charger("gallery_server", GAMES_DIR / "gallery_server.py")
        scannes = []

        def meta(argv, **_kw):
            scannes.append(argv[1])
            return subprocess.CompletedProcess(argv, 0, '{"name": "x"}', "")

        with mock.patch.object(galerie.subprocess, "run", side_effect=meta):
            ids = {g["id"] for g in galerie._scan_games()}
        self.assertEqual(self.jeux_du_clone(), sorted(scannes))
        self.assertIn("snake", ids)
        self.assertNotIn("tiler", ids)
        self.assertEqual(ROOT, Path(galerie.ERPLIBRE_DIR))


if __name__ == "__main__":
    unittest.main()
