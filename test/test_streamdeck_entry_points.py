#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les points d'entrée du Stream Deck tournent sous .venv.streamdeck.

Le code du deck importe StreamDeck, PIL, cv2, pyudev, requests et keyboard :
lancé par son shebang « #!/usr/bin/env python3 », il prend le python du
système, où ces modules manquent, et tombe à l'import. Chaque point d'entrée
nomme donc l'interpréteur du venv dédié.

Ce que ces tests gardent :

- toute recette du fragment make qui appelle python passe par
  $(STREAMDECK_PY), hors la migration de l'extension, son aide
  d'activation et le compilateur des locales, qui ne sont pas du code du
  deck et gardent le python du système ; toute cible qui s'en sert l'a en
  prérequis : sans venv, elle s'arrête sur la commande qui le bâtit,
  make erplibre_home_streamdeck_install ;
- requirements.txt porte ce que le code importe, et plus lz4, que le venv
  ne sert pas ;
- la galerie lance un jeu sous son propre interpréteur, cité pour bash ;
- le menu TODO lance un jeu sous le python du venv, et sans venv il le dit
  dans la langue de l'utilisateur sans rien lancer ;
- launch_game.sh, que rien n'appelait, n'existe plus.
"""

import contextlib
import importlib.util
import io
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import todo as todo_mod  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "conf" / "make.streamdeck.Makefile"
DECK_DIR = ROOT / "script" / "stream_deck"
REQUIREMENTS = DECK_DIR / "requirements.txt"
VENV_REF = "$(STREAMDECK_PY)"
INSTALL_DECK = "make erplibre_home_streamdeck_install"
MESSAGE_SANS_VENV = (
    "ERPLibre Home Stream Deck is not installed:"
    " make erplibre_home_streamdeck_install"
)

# Un appel à python sous toutes ses formes : l'interpréteur nommé, pip, ou un
# fichier .py exécuté par son shebang.
APPEL_PYTHON = re.compile(r"\bpython3?\s|\bpip3?\s+install|\S+\.py\b")
# Trois appels restent hors du venv. La migration de l'ancienne identité de
# l'extension et son aide d'activation passent par leur shebang : elles
# n'importent que la bibliothèque standard et tournent avant que le venv
# existe. Le compilateur des locales n'est pas un point d'entrée du deck :
# il garde le python3 du système.
HORS_VENV = re.compile(
    r"/tools/(migrate_legacy|enable_next_login)\.py\b"
    r"|/po/compile_locales\.py\b"
)
SHEBANG_DECK = re.compile(r"\./script/stream_deck/\w+\.py")
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


def jeux():
    """Les jeux du dépôt : game_<id>.py -> id."""
    return sorted(p.stem[len("game_") :] for p in DECK_DIR.glob("game_*.py"))


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

    def test_the_rules_were_actually_parsed(self):
        # Une forme de fichier que l'analyse ne lit plus doit tomber ici,
        # plutôt que de déclarer conforme une liste vide.
        self.assertGreater(len(self.regles), 50)
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

    def test_every_game_has_its_target_under_the_venv(self):
        self.assertIn("snake", jeux())
        for jeu in jeux():
            cible = f"streamdeck_{jeu}"
            self.assertIn(cible, self.regles)
            self.assertEqual(
                self.regles[cible][1],
                [f"{VENV_REF} script/stream_deck/game_{jeu}.py"],
            )

    def test_the_spec_entry_points_use_the_venv(self):
        attendus = {
            "streamdeck": "erplibre_controller.py",
            "streamdeck_gallery": "gallery_server.py",
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
                re.escape(VENV_REF) + r" [^;]*" + re.escape(fragment),
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
class TestMakefileGuard(unittest.TestCase):
    def make(self, *args):
        return subprocess.run(
            ["make", "-s", "-f", str(MAKEFILE), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_a_missing_venv_stops_with_the_install_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            absent = os.path.join(tmp, "absent", "python")
            res = self.make(f"STREAMDECK_PY={absent}", "streamdeck_snake")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Stream Deck venv missing: " + INSTALL_DECK, res.stderr)

    def test_a_present_venv_runs_the_game_under_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            faux = os.path.join(tmp, "python")
            with open(faux, "w", encoding="utf-8") as f:
                f.write('#!/bin/sh\necho "faux-python $*"\n')
            os.chmod(faux, os.stat(faux).st_mode | stat.S_IXUSR)
            res = self.make(f"STREAMDECK_PY={faux}", "streamdeck_snake")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(
            res.stdout.strip(), "faux-python script/stream_deck/game_snake.py"
        )


class TestRequirements(unittest.TestCase):
    def noms(self):
        noms = set()
        for ligne in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
            ligne = ligne.split("#", 1)[0].strip()
            if ligne:
                noms.add(
                    re.split(r"[<>=!~\[; ]", ligne, maxsplit=1)[0].lower()
                )
        return noms

    def test_what_the_deck_imports_is_required(self):
        for nom in ("requests", "keyboard", "pyudev", "streamdeck"):
            self.assertIn(nom, self.noms())

    def test_lz4_left_the_venv(self):
        self.assertNotIn("lz4", self.noms())


def charger_galerie():
    """Charge gallery_server.py par son chemin : script/stream_deck n'est
    pas un paquet."""
    chemin = DECK_DIR / "gallery_server.py"
    spec = importlib.util.spec_from_file_location("gallery_server", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGalleryLaunch(unittest.TestCase):
    def test_the_game_runs_under_the_server_interpreter(self):
        galerie = charger_galerie()
        jeu = "/srv/jeux de test/game_demo.py"
        commande = galerie._game_bash_cmd(jeu)
        self.assertIn(
            f"{shlex.quote(sys.executable)} {shlex.quote(jeu)};", commande
        )
        self.assertNotIn("python3 ", commande)

    def test_the_loop_really_starts_that_interpreter(self):
        galerie = charger_galerie()
        with tempfile.TemporaryDirectory(prefix="jeu demo ") as tmp:
            jeu = os.path.join(tmp, "game_demo.py")
            with open(jeu, "w", encoding="utf-8") as f:
                f.write("import sys\nprint(sys.executable)\n")
            # stdin fermé : le « read » de fin de partie échoue et la boucle
            # s'arrête après un tour.
            res = subprocess.run(
                ["bash", "-c", galerie._game_bash_cmd(jeu)],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(res.stdout.splitlines()[0], sys.executable)


class TestLaunchGameScriptGone(unittest.TestCase):
    def test_the_script_is_removed(self):
        self.assertFalse((DECK_DIR / "launch_game.sh").exists())

    def test_nothing_refers_to_it(self):
        for chemin in DECK_DIR.rglob("*"):
            if chemin.suffix not in {".py", ".js", ".html", ".md", ".sh"}:
                continue
            if "node_modules" in chemin.parts:
                continue
            texte = chemin.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn("launch_game.sh", texte, str(chemin))


class TestTodoGamesLauncher(unittest.TestCase):
    """Le menu des jeux, sur un venv simulé : un faux python exécutable
    quand il est présent, un chemin qui n'existe pas quand il manque."""

    JEU = "/srv/jeux de test/game_demo.py"

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.present = os.path.join(dossier.name, "python")
        with open(self.present, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        os.chmod(self.present, 0o755)
        self.absent = os.path.join(dossier.name, "absent", "python")
        self.addCleanup(setattr, todo_i18n, "_current_lang", None)

    def menu(self, python, reponses=("1", "0")):
        """Joue le menu des jeux ; rend (todo, rendu, sortie)."""
        todo = todo_mod.TODO.__new__(todo_mod.TODO)
        todo._scan_streamdeck_games = mock.Mock(
            return_value=[
                {
                    "name": "Demo",
                    "description": "Demo — demo",
                    "path": self.JEU,
                }
            ]
        )
        todo.fill_help_info = lambda choices: ""
        todo.execute = mock.Mock()
        sortie = io.StringIO()
        with (
            mock.patch.object(todo_mod, "VENV_STREAMDECK_PYTHON", python),
            mock.patch.object(
                todo_mod.click, "prompt", side_effect=list(reponses)
            ),
            contextlib.redirect_stdout(sortie),
        ):
            rendu = todo.prompt_execute_streamdeck_games()
        return todo, rendu, sortie.getvalue()

    def test_the_command_names_the_streamdeck_venv(self):
        todo = todo_mod.TODO.__new__(todo_mod.TODO)
        commande = todo._streamdeck_game_command(self.JEU)
        python = commande.split(" ", 1)[0]
        self.assertTrue(
            python.endswith(os.path.join(".venv.streamdeck", "bin", "python"))
        )
        self.assertTrue(commande.endswith(" " + shlex.quote(self.JEU)))

    def test_the_menu_runs_the_chosen_game_with_that_command(self):
        todo, rendu, _sortie = self.menu(self.present)
        self.assertFalse(rendu)
        todo.execute.exec_command_live.assert_called_once_with(
            f"{shlex.quote(self.present)} {shlex.quote(self.JEU)}",
            source_erplibre=False,
        )

    def test_without_the_venv_it_says_so_and_launches_nothing(self):
        attendus = {
            "en": MESSAGE_SANS_VENV,
            "fr": "ERPLibre Home Stream Deck n'est pas installé :"
            " make erplibre_home_streamdeck_install",
        }
        for langue, message in attendus.items():
            with self.subTest(langue=langue):
                todo_i18n._current_lang = langue
                todo, rendu, sortie = self.menu(self.absent, reponses=())
                self.assertFalse(rendu)
                self.assertIn(message, sortie)
                todo.execute.exec_command_live.assert_not_called()
                todo._scan_streamdeck_games.assert_not_called()


if __name__ == "__main__":
    unittest.main()
