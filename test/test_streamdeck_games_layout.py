#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les jeux du Stream Deck vivent dans script/stream_deck/games/ ; le
programme du deck et ses outils restent dans script/stream_deck/."""

import importlib.util
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
DECK_DIR = ROOT / "script" / "stream_deck"
GAMES_DIR = DECK_DIR / "games"
sys.argv = ["todo.py"]
from script.todo import todo as todo_mod  # noqa: E402


def suivis(motif):
    """Les fichiers suivis par git qui répondent à `motif` : une copie
    non suivie laissée dans un checkout ne compte pas."""
    sortie = subprocess.run(
        ["git", "ls-files", motif],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(ROOT / ligne for ligne in sortie.splitlines())


class LaDisposition(unittest.TestCase):
    def test_no_game_is_left_next_to_the_deck_program(self):
        self.assertEqual([], suivis("script/stream_deck/game_*.py"))

    def test_the_games_moved_with_their_mode_and_shebang(self):
        jeux = suivis("script/stream_deck/games/game_*.py")
        self.assertEqual(45, len(jeux))
        for jeu in jeux:
            with self.subTest(jeu=jeu.name):
                self.assertTrue(os.access(jeu, os.X_OK))
                premiere = jeu.read_text(encoding="utf-8").split("\n")[0]
                self.assertTrue(premiere.startswith("#!"), premiere)

    def test_no_game_imports_a_sibling_module(self):
        """Sauf games_cli, la ligne de commande commune des jeux, qui
        vit à côté d'eux et n'importe que la bibliothèque standard."""
        voisins = {p.stem for p in DECK_DIR.glob("*.py")}
        voisins |= {p.stem for p in GAMES_DIR.glob("*.py")}
        voisins |= {p.parent.name for p in DECK_DIR.glob("*/__init__.py")}
        voisins.discard("games_cli")
        motif = re.compile(r"^\s*(?:import|from)\s+(\w+)", re.M)
        for jeu in suivis("script/stream_deck/games/game_*.py"):
            with self.subTest(jeu=jeu.name):
                importes = set(motif.findall(jeu.read_text(encoding="utf-8")))
                self.assertEqual(set(), importes & voisins)

    def test_the_assets_stay_with_the_controller(self):
        self.assertTrue((DECK_DIR / "Assets").is_dir())
        self.assertTrue((DECK_DIR / "erplibre_controller.py").is_file())

    def test_every_game_reads_its_command_line_through_games_cli(self):
        for jeu in suivis("script/stream_deck/games/game_*.py"):
            with self.subTest(jeu=jeu.name):
                texte = jeu.read_text(encoding="utf-8")
                self.assertIn("\nimport games_cli\n", texte)
                self.assertIn("games_cli.parser(__doc__)", texte)

    def test_games_cli_is_not_listed_as_a_game(self):
        """La galerie et le menu TODO prennent tout game_*.py pour un
        jeu ; games_cli n'en est pas un."""
        cli = GAMES_DIR / "games_cli.py"
        self.assertTrue(cli.is_file())
        self.assertNotIn(cli, list(GAMES_DIR.glob("game_*.py")))
        motif = re.compile(r"^\s*(?:import|from)\s+(\w+)", re.M)
        importes = set(motif.findall(cli.read_text(encoding="utf-8")))
        self.assertEqual({"argparse"}, importes)

    def test_the_gallery_and_its_page_are_in_games(self):
        self.assertTrue((GAMES_DIR / "gallery_server.py").is_file())
        self.assertTrue((GAMES_DIR / "index.html").is_file())


class LesVraisScans(unittest.TestCase):
    """Sans simulation : un chemin oublié ne montre qu'une liste vide."""

    def test_todo_finds_exactly_the_games_of_games_dir(self):
        todo = todo_mod.TODO.__new__(todo_mod.TODO)
        trouves = sorted(
            g["path"] for g in todo._scan_streamdeck_games()
        )
        attendus = sorted(
            str(p) for p in suivis("script/stream_deck/games/game_*.py")
        )
        self.assertEqual(attendus, trouves)
        self.assertNotIn("tiler", " ".join(trouves))

    def test_the_gallery_lists_the_games_and_not_the_tiler(self):
        """Le vrai glob de la galerie ; seul « --meta » est simulé, car
        les jeux n'y répondent que sous .venv.streamdeck, qui porte leurs
        dépendances."""
        spec = importlib.util.spec_from_file_location(
            "gallery_server", GAMES_DIR / "gallery_server.py"
        )
        galerie = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(galerie)
        scannes = []

        def meta(argv, **_kw):
            scannes.append(argv[1])
            return subprocess.CompletedProcess(argv, 0, '{"name": "x"}', "")

        with mock.patch.object(galerie.subprocess, "run", side_effect=meta):
            ids = {g["id"] for g in galerie._scan_games()}
        attendus = [
            str(p) for p in suivis("script/stream_deck/games/game_*.py")
        ]
        self.assertEqual(attendus, sorted(scannes))
        self.assertIn("snake", ids)
        self.assertNotIn("tiler", ids)
        self.assertEqual(ROOT, Path(galerie.ERPLIBRE_DIR))


if __name__ == "__main__":
    unittest.main()
