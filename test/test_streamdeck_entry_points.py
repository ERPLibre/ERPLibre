#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les cibles make du Stream Deck lancent le programme du deck, cloné dans
script/stream_deck/deck/, sous .venv.streamdeck.

Le code du deck importe StreamDeck, PIL, cv2, pyudev, requests et keyboard :
lancé par son shebang « #!/usr/bin/env python3 », il prend le python du
système, où ces modules manquent, et tombe à l'import. Chaque point d'entrée
nomme donc l'interpréteur du venv dédié.

Ce que ces tests gardent :

- toute recette du fragment make qui appelle python passe par
  $(STREAMDECK_PY), hors l'aide d'activation de l'extension et le
  compilateur des locales, qui ne sont pas du code du deck et gardent le
  python du système ; toute cible qui s'en sert l'a en prérequis : sans
  venv, elle s'arrête sur la commande qui le bâtit,
  make erplibre_home_streamdeck_install ;
- toute cible qui lance un fichier du deck le prend dans le clone, et a
  streamdeck_deck_present en prérequis : sans le clone, elle s'arrête sur
  la même commande ;
- les cibles de tests du deck lancent sa suite depuis la racine du clone.

Les cibles make tournent dans un faux checkout temporaire, sous un faux
python qui affiche ses arguments. La ligne de commande du programme du
deck et du contrôleur, et requirements.txt, se testent dans le dépôt du
deck (tests/test_entry_points.py).
"""

import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "conf" / "make.streamdeck.Makefile"
SETTINGS = ROOT / "script" / "install" / "erplibre_home_settings.sh"
DECK_REF = "$(STREAMDECK_DECK)"
DECK_GUARD = "streamdeck_deck_present"
VENV_REF = "$(STREAMDECK_PY)"
INSTALL_DECK = "make erplibre_home_streamdeck_install"

# Un appel à python sous toutes ses formes : l'interpréteur nommé, pip, ou un
# fichier .py exécuté par son shebang.
APPEL_PYTHON = re.compile(r"\bpython3?\s|\bpip3?\s+install|\S+\.py\b")
# Deux appels restent hors du venv. L'aide d'activation de l'extension passe
# par son shebang : elle n'importe que la bibliothèque standard et tourne
# avant que le venv existe. Le compilateur des locales n'est pas un point
# d'entrée du deck : il garde le python3 du système.
HORS_VENV = re.compile(
    r"/tools/enable_next_login\.py\b|/po/compile_locales\.py\b"
)
SHEBANG_DECK = re.compile(r"\./script/stream_deck/[\w/]+\.py")
# Un fichier du deck nommé à son ancienne place, hors du clone.
ANCIENNE_PLACE = re.compile(r"script/stream_deck/(?!deck\b)\w")
REGLE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(?!=)(.*)$")


def regles(texte):
    """Rend {cible: (prérequis, [commandes])} des règles nommées du texte.

    Une commande est une ligne logique de recette : les lignes terminées par
    « \\ » y sont jointes. Une ligne à tabulation qui suit une affectation
    de variable n'est pas une recette et n'est rattachée à aucune cible.
    """
    resultat = {}
    cible = None
    en_cours = ""
    for ligne in texte.split("\n"):
        if ligne.startswith("\t") and cible is not None:
            en_cours += ligne.strip().rstrip("\\") + " "
            if not ligne.rstrip().endswith("\\"):
                resultat[cible][1].append(en_cours.strip())
                en_cours = ""
            continue
        if ligne.startswith("\t"):
            continue
        m = REGLE.match(ligne)
        if m:
            cible = m.group(1)
            resultat[cible] = (m.group(2).split(), [])
        elif ligne.strip() and not ligne.startswith("#"):
            cible = None
    return resultat


class TestMakefileUsesTheVenv(unittest.TestCase):
    def setUp(self):
        self.texte = MAKEFILE.read_text(encoding="utf-8")
        self.regles = regles(self.texte)

    def test_the_variable_is_defined(self):
        self.assertTrue(
            re.search(
                r"(?m)^STREAMDECK_PY := \.venv\.streamdeck/bin/python$",
                self.texte,
            ),
            "STREAMDECK_PY absent du fragment",
        )

    def test_the_deck_program_targets_are_phony(self):
        """Sans .PHONY, un fichier du même nom à la racine rendrait la
        cible « à jour » et le programme du deck ne démarrerait pas."""
        phony = set()
        for ligne in re.findall(r"(?m)^\.PHONY:(.*)$", self.texte):
            phony.update(ligne.split())
        for cible in ("streamdeck_erplibre", "streamdeck_tiler"):
            self.assertIn(cible, phony)

    def test_the_rules_were_actually_parsed(self):
        # Une forme de fichier que l'analyse ne lit plus doit tomber ici,
        # plutôt que de déclarer conforme une liste vide.
        self.assertGreater(len(self.regles), 20)
        self.assertIn("streamdeck", self.regles)

    def test_no_recipe_calls_a_deck_script_by_its_shebang(self):
        for cible, (_, commandes) in self.regles.items():
            for commande in commandes:
                self.assertNotRegex(commande, SHEBANG_DECK, cible)

    def test_every_python_call_goes_through_the_venv(self):
        for cible, (_, commandes) in self.regles.items():
            for commande in commandes:
                if HORS_VENV.search(commande):
                    continue
                if APPEL_PYTHON.search(commande):
                    self.assertIn(VENV_REF, commande, cible)

    def test_every_target_using_the_venv_requires_it(self):
        for cible, (prerequis, commandes) in self.regles.items():
            if any(VENV_REF in c for c in commandes):
                self.assertIn(VENV_REF, prerequis, cible)

    def test_the_tiler_target_is_an_alias(self):
        prerequis, commandes = self.regles["streamdeck_tiler"]
        self.assertEqual(["streamdeck_erplibre"], prerequis)
        self.assertEqual([], commandes)

    def test_the_tiler_runs_the_package_directory(self):
        commandes = " ".join(self.regles["streamdeck_erplibre"][1])
        self.assertRegex(
            commandes, re.escape(DECK_REF) + r"/erplibre_streamdeck(?![\w./])"
        )

    def test_the_clone_is_where_the_deck_repository_is_cloned(self):
        self.assertTrue(
            re.search(
                r"(?m)^STREAMDECK_DECK := script/stream_deck/deck$",
                self.texte,
            ),
            "STREAMDECK_DECK absent du fragment",
        )

    def test_no_recipe_names_a_deck_file_at_its_former_place(self):
        for cible, (_, commandes) in self.regles.items():
            for commande in commandes:
                self.assertNotRegex(commande, ANCIENNE_PLACE, cible)

    def test_every_target_running_the_clone_requires_it(self):
        for cible, (prerequis, commandes) in self.regles.items():
            if any(DECK_REF in c for c in commandes):
                self.assertIn(DECK_GUARD, prerequis, cible)

    def test_the_spec_entry_points_use_the_venv(self):
        attendus = {
            "streamdeck": "erplibre_controller.py",
            "streamdeck_erplibre": "erplibre_streamdeck",
            "streamdeck_translator_doctor": "translator_doctor.py",
            "streamdeck_translator_test": "translator_test.py",
            "streamdeck_translator_stream": "translator_stream.py",
            "streamdeck_translator_install_ollama": "translator_doctor.py",
            "streamdeck_translator_unittest": "-m unittest",
            "streamdeck_tiler_unittest": "-m unittest",
            "streamdeck_translator_install_vosk_fr": "-m pip install vosk",
        }
        for cible, fragment in attendus.items():
            commandes = " ".join(self.regles[cible][1])
            self.assertRegex(
                commandes,
                re.escape(VENV_REF) + r"\)? [^;]*" + re.escape(fragment),
                cible,
            )

    def test_the_locale_compiler_keeps_the_system_python(self):
        """compile_locales.py n'est pas du code du deck : sa cible tourne
        sans venv, et ne l'exige pas."""
        prerequis, commandes = self.regles["erplibre_home_compile_locale"]
        self.assertEqual(
            commandes,
            ["@python3 $(ERPLIBRE_HOME_EXT_SRC)/po/compile_locales.py"],
        )
        self.assertNotIn(VENV_REF, prerequis)

    def test_pip_never_installs_for_the_user(self):
        self.assertNotIn("pip install --user", self.texte)


@unittest.skipUnless(shutil.which("make"), "make absent")
class TestMakefileTargets(unittest.TestCase):
    """Le fragment tourne dans un faux checkout temporaire, sous un faux
    python qui affiche ses arguments et un XDG_CONFIG_HOME temporaire. Le
    faux checkout porte la bibliothèque des réglages, que lit
    streamdeck_deck_present, et un clone du deck réduit à son témoin et à
    un dossier tests/."""

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.tmp = dossier.name
        self.faux = os.path.join(self.tmp, "python")
        with open(self.faux, "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\necho "faux-python $(pwd) $*"\n')
        os.chmod(self.faux, os.stat(self.faux).st_mode | stat.S_IXUSR)
        install = Path(self.tmp, "script", "install")
        install.mkdir(parents=True)
        shutil.copy(SETTINGS, install)
        self.deck = Path(self.tmp, "script", "stream_deck", "deck")
        (self.deck / "erplibre_streamdeck").mkdir(parents=True)
        (self.deck / "erplibre_streamdeck" / "__main__.py").write_text("")
        (self.deck / "tests").mkdir()

    def make(self, cible, python=None):
        return subprocess.run(
            [
                "make",
                "-s",
                "-f",
                str(MAKEFILE),
                f"STREAMDECK_PY={python or self.faux}",
                cible,
            ],
            cwd=self.tmp,
            capture_output=True,
            text=True,
            timeout=30,
            env=dict(os.environ, XDG_CONFIG_HOME=self.tmp),
        )

    def test_a_missing_venv_stops_with_the_install_command(self):
        absent = os.path.join(self.tmp, "absent", "python")
        res = self.make("streamdeck_erplibre", python=absent)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Stream Deck venv missing: " + INSTALL_DECK, res.stderr)

    def test_a_missing_clone_stops_with_the_install_command(self):
        shutil.rmtree(self.deck / "erplibre_streamdeck")
        for cible in ("streamdeck_erplibre", "streamdeck", "streamdeck_tiler"):
            with self.subTest(cible=cible):
                res = self.make(cible)
                self.assertNotEqual(0, res.returncode)
                self.assertNotIn("faux-python", res.stdout)
                self.assertIn("deck program is not installed", res.stderr)
                self.assertIn(INSTALL_DECK, res.stderr)

    def test_the_translator_tools_run_under_the_venv(self):
        for cible in (
            "streamdeck_translator_doctor",
            "streamdeck_translator_test",
            "streamdeck_translator_stream",
            "streamdeck_translator_unittest",
        ):
            with self.subTest(cible=cible):
                res = self.make(cible)
                self.assertEqual(0, res.returncode, res.stderr)
                self.assertIn("faux-python", res.stdout)

    def test_the_unittest_targets_run_the_deck_suite_from_the_clone(self):
        """streamdeck_tiler_unittest garde son nom et lance toute la suite
        du deck ; streamdeck_translator_unittest, celle du traducteur.
        Les deux depuis la racine du clone, qui trouve tests/."""
        for cible, motif in (
            ("streamdeck_tiler_unittest", None),
            ("streamdeck_translator_unittest", "test_*translator.py"),
        ):
            with self.subTest(cible=cible):
                res = self.make(cible)
                self.assertEqual(0, res.returncode, res.stderr)
                mots = res.stdout.split()
                self.assertEqual("faux-python", mots[0])
                self.assertEqual(str(self.deck.resolve()), mots[1])
                self.assertEqual(["-m", "unittest", "discover"], mots[2:5])
                self.assertEqual("tests", mots[mots.index("-s") + 1])
                if motif:
                    self.assertEqual(motif, mots[mots.index("-p") + 1])
                else:
                    self.assertNotIn("-p", mots)

    def test_a_present_venv_runs_the_deck_program_under_it(self):
        res = self.make("streamdeck_erplibre")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(
            res.stdout.strip(),
            "faux-python %s script/stream_deck/deck/erplibre_streamdeck"
            % os.path.realpath(self.tmp),
        )


if __name__ == "__main__":
    unittest.main()
