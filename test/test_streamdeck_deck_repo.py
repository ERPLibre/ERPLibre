#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le programme du deck est un dépôt à part, cloné dans
script/stream_deck/deck/ ; ERPLibre garde, sous script/stream_deck/, le
guide d'installation et les captures.

Ce que ces tests gardent :

- ERPLibre ne suit aucun fichier de deck/, qu'il ignore, ni aucun fichier
  du programme du deck à son ancienne place, script/stream_deck/ ;
- le manifeste du deck suit sa branche main, à son chemin, dans le groupe
  streamdeck, sous le remote TechnoLibre du mobile ; seule
  conf/git_manifest_streamdeck.csv le nomme, que git_merge_repo_manifest.py
  ne lit que si le deck est là ou avec --with_streamdeck, comme pour le
  mobile : un serveur Odoo ne le clone pas ;
- deck_contract porte une version MAJEUR.MINEUR, et un deck cloné dont le
  CONTRACT.md porte une autre version MAJEURE, ou une MINEURE plus basse,
  fait échouer la suite ;
- les chemins qu'ERPLibre lance dans le clone existent : les deux
  programmes de DECK_PROGRAM, le verrou du deck, requirements.txt et les
  outils du traducteur.

Ce qui lit le vrai deck est sauté, avec sa raison, quand deck/ manque. Le
deck lui-même se teste dans son dépôt (tests/test_contract.py).
"""

import csv
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from streamdeck_deck import (  # noqa: E402
    DECK,
    SANS_DECK,
    version_du_contrat,
)

ROOT = Path(__file__).resolve().parent.parent
DECK_PATH = "script/stream_deck/deck"
MANIFESTE = "manifest/git_manifest_erplibre_streamdeck_deck.xml"
CONTRAT = ROOT / "script/stream_deck/deck_contract"
SETTINGS = ROOT / "script/install/erplibre_home_settings.sh"


def git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True
    )


def deck_program_path(programme):
    """Ce que rend deck_program_path de la bibliothèque des réglages."""
    return subprocess.run(
        [
            "bash",
            "-c",
            '. "$1" && deck_program_path "$2"',
            "-",
            str(SETTINGS),
            programme,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


class LaFrontiere(unittest.TestCase):
    def test_erplibre_tracks_nothing_under_deck(self):
        suivis = git("ls-files", DECK_PATH)
        self.assertEqual(0, suivis.returncode, suivis.stderr)
        self.assertEqual("", suivis.stdout)

    def test_the_deck_directory_is_ignored(self):
        for chemin in (
            DECK_PATH + "/erplibre_controller.py",
            DECK_PATH + ".avant-repo-20260101-000000/erplibre_controller.py",
        ):
            with self.subTest(chemin=chemin):
                self.assertEqual(
                    0, git("check-ignore", "-q", chemin).returncode
                )

    def test_no_deck_file_is_left_at_its_former_place(self):
        for motif in (
            "script/stream_deck/erplibre_streamdeck",
            "script/stream_deck/*.py",
            "script/stream_deck/requirements.txt",
            "script/stream_deck/Assets",
            "test/test_erplibre_streamdeck_*.py",
            "test/fixtures/erplibre_streamdeck",
        ):
            with self.subTest(motif=motif):
                self.assertEqual("", git("ls-files", motif).stdout)


class LeManifeste(unittest.TestCase):
    def setUp(self):
        self.racine = ET.parse(ROOT / MANIFESTE).getroot()
        (self.projet,) = [
            p
            for p in self.racine.iter("project")
            if p.get("path") == DECK_PATH
        ]

    def test_it_follows_the_main_branch_of_the_deck(self):
        """Une version MAJEURE du contrat qui change sur main touche tout
        checkout à sa prochaine mise à jour : LeContrat le surveille."""
        remotes = {
            r.get("name"): r.get("fetch") for r in self.racine.iter("remote")
        }
        self.assertEqual("erplibre_streamdeck.git", self.projet.get("name"))
        self.assertEqual(
            "https://github.com/TechnoLibre/",
            remotes[self.projet.get("remote")],
        )
        self.assertEqual("main", self.projet.get("revision"))

    def test_it_belongs_to_the_streamdeck_group(self):
        """Les init de repo qui nomment leurs groupes prennent le deck par
        streamdeck ; un projet hors de ce groupe en sortirait, et repo
        supprimerait le programme que lance le service."""
        groupes = self.projet.get("groups", "").split(",")
        self.assertEqual(["streamdeck"], groupes)

    def test_its_remote_is_named_technolibre_like_the_mobile(self):
        self.assertEqual("TechnoLibre", self.projet.get("remote"))
        mobile = ET.parse(ROOT / "manifest/git_manifest_mobile_home.xml")
        remotes_du_mobile = {
            r.get("name"): r.get("fetch")
            for r in mobile.getroot().iter("remote")
        }
        (remote,) = [
            r
            for r in self.racine.iter("remote")
            if r.get("name") == "TechnoLibre"
        ]
        self.assertEqual(remotes_du_mobile["TechnoLibre"], remote.get("fetch"))

    def test_only_the_streamdeck_list_names_it(self):
        """Les listes générales entrent dans toute fusion, celle d'un
        serveur Odoo comprise ; la liste du Stream Deck n'y entre que pour
        un checkout qui a le deck."""
        for liste, nomme in (
            ("git_manifest_streamdeck.csv", True),
            ("git_manifest.csv", False),
            ("git_manifest_mobile.csv", False),
            ("git_manifest_odoo.csv", False),
            ("git_manifest_erplibre_home.csv", False),
        ):
            with self.subTest(liste=liste):
                with open(ROOT / "conf" / liste, encoding="utf-8") as fh:
                    fichiers = [
                        ligne["filepath"] for ligne in csv.DictReader(fh)
                    ]
                self.assertEqual(nomme, MANIFESTE in fichiers)


class LeContrat(unittest.TestCase):
    def version(self, texte):
        """(MAJEURE, MINEURE) d'un texte « X.Y »."""
        self.assertRegex(texte, r"^\d+\.\d+$")
        return tuple(int(nombre) for nombre in texte.split("."))

    def attendue(self):
        return self.version(CONTRAT.read_text(encoding="utf-8").strip())

    def test_deck_contract_holds_one_version(self):
        self.attendue()

    @SANS_DECK
    def test_the_cloned_deck_shares_its_major(self):
        """Une MAJEURE qui diffère : ERPLibre et le deck ne s'entendent
        plus sur CONTRACT.md ; main du deck a changé de MAJEURE sans que
        deck_contract suive."""
        self.assertEqual(self.attendue()[0], version_du_contrat()[0])

    @SANS_DECK
    def test_the_cloned_deck_has_at_least_the_expected_minor(self):
        """Une MINEURE du clone plus basse que celle de deck_contract : le
        clone n'a pas ce qu'ERPLibre en attend, une commande ou une clé que
        cette MINEURE ajoute. Un clone gardé sur une branche, ou qu'aucun
        repo sync n'a mis à jour, en est le cas."""
        attendue = self.attendue()
        clone = version_du_contrat()
        self.assertEqual(attendue[0], clone[0])
        self.assertGreaterEqual(
            clone[1],
            attendue[1],
            "deck %d.%d < deck_contract %d.%d" % (clone + attendue),
        )


@SANS_DECK
class CeQuERPLibreLance(unittest.TestCase):
    """Chaque fichier du clone qu'ERPLibre lance ou charge par son chemin,
    tel que CONTRACT.md le place."""

    def test_the_deck_programs_exist(self):
        self.assertTrue(
            (ROOT / deck_program_path("tiler") / "__main__.py").is_file()
        )
        self.assertTrue((ROOT / deck_program_path("controller")).is_file())

    def test_the_files_erplibre_runs_exist(self):
        for nom in (
            "deck_lock.py",
            "requirements.txt",
            "translator_doctor.py",
            "translator_test.py",
            "translator_stream.py",
            "erplibre_streamdeck/plugins",
        ):
            with self.subTest(fichier=nom):
                self.assertTrue((DECK / nom).exists())


if __name__ == "__main__":
    unittest.main()
