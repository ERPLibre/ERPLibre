#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les cibles make du Stream Deck lancent le programme du deck, cloné dans
script/stream_deck/deck/, et les jeux, clonés dans script/stream_deck/games/,
sous .venv.streamdeck.

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
- le fragment ne nomme aucun jeu : une seule règle à motif,
  streamdeck_%, lance game_<id>.py à travers la passation du deck, après
  la garde des jeux ; un id sans fichier sort en erreur en le nommant ;
  streamdeck_games liste les jeux à partir des fichiers, et chaque cible
  streamdeck_* explicite garde sa propre recette ;
- les cibles de tests du deck lancent sa suite depuis la racine du clone ;
- la galerie lance un jeu sous son propre interpréteur, cité pour bash, et
  toute sa boucle de parties dans une seule passation du deck ;
- le menu TODO lance un jeu sous le python du venv, à travers la passation
  du deck, et sans venv il le dit dans la langue de l'utilisateur sans rien
  lancer ;
- launch_game.sh, que rien n'appelait, n'existe plus ;
- le programme du deck refuse --meta, l'option qui fait reconnaître un jeu
  à la galerie.

Les jeux et la galerie sont un dépôt à part, cloné dans
script/stream_deck/games/ ; leur propre ligne de commande se teste là-bas
(tests/test_contract.py). Ici, les cibles make tournent dans une copie
réduite du dépôt avec un faux games/, et ce qui lit les vrais jeux ou la
vraie galerie est sauté, avec sa raison, quand games/ manque ; ce qui lit
le programme du deck, ou passe le deck par son verrou, quand son clone
manque (SANS_DECK). La ligne de commande du programme du deck et du
contrôleur, et requirements.txt, se testent dans le dépôt du deck
(tests/test_entry_points.py).
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
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from streamdeck_checkout import copier_depot  # noqa: E402
from streamdeck_deck import DECK, SANS_DECK  # noqa: E402

sys.argv = ["todo.py"]
from script.todo import todo as todo_mod  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "conf" / "make.streamdeck.Makefile"
GARDE = "streamdeck_games_guard"
STREAM_DECK_DIR = ROOT / "script" / "stream_deck"
GAMES_DIR = STREAM_DECK_DIR / "games"
DECK_REF = "$(STREAMDECK_DECK)"
DECK_GUARD = "streamdeck_deck_present"
VENV_REF = "$(STREAMDECK_PY)"
INSTALL_DECK = "make erplibre_home_streamdeck_install"
MESSAGE_SANS_VENV = (
    "ERPLibre Home Stream Deck is not installed:"
    " make erplibre_home_streamdeck_install"
)

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
# Un fichier du deck nommé à son ancienne place, hors des deux clones.
ANCIENNE_PLACE = re.compile(r"script/stream_deck/(?!deck\b|games\b)\w")
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


# Les tests qui lisent les vrais jeux ou la vraie galerie : un checkout
# peut ne pas avoir cloné leur dépôt.
SANS_JEUX = unittest.skipUnless(
    (GAMES_DIR / "games_cli.py").is_file(),
    "script/stream_deck/games/ absent : make erplibre_home_streamdeck_install",
)
# Des ids inventés, qu'aucun dépôt ne porte : le faux games/ les pose, et
# ils tiennent lieu de jeux du clone quand games/ manque.
JEU_INVENTE = "fauxjeu"
AUTRE_JEU_INVENTE = "autrejeu"
PASSATION = "script/install/erplibre_home_streamdeck_handover.sh"
REGLE_DES_JEUX = re.compile(r"(?m)^streamdeck_%:(.*)$")


def jeux_installes():
    """Les jeux clonés dans games/ : game_<id>.py -> id."""
    return sorted(p.stem[len("game_") :] for p in GAMES_DIR.glob("game_*.py"))


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

    def test_the_makefile_names_no_game(self):
        """Un jeu ajouté au dépôt des jeux ne demande aucun commit ici :
        le fragment ne nomme ni son fichier ni sa cible."""
        for jeu in jeux_installes() or [JEU_INVENTE]:
            with self.subTest(jeu=jeu):
                for motif in (
                    rf"\bgame_{jeu}\.py\b",
                    rf"\bstreamdeck_{jeu}\b",
                ):
                    trouve = re.search(motif, self.texte)
                    self.assertIsNone(trouve, trouve and trouve.group())

    def test_one_pattern_rule_runs_every_game_behind_the_guard(self):
        regles_ = REGLE_DES_JEUX.findall(self.texte)
        self.assertEqual(1, len(regles_), "streamdeck_%: absent ou doublé")
        prerequis = regles_[0].split()
        self.assertEqual([VENV_REF, GARDE], prerequis)

    @SANS_JEUX
    def test_no_game_of_the_clone_is_hidden_by_an_explicit_target(self):
        """make préfère une cible explicite à la règle à motif : un jeu dont
        l'id donne le nom d'une cible du fragment ne se lancerait pas."""
        for jeu in jeux_installes():
            self.assertFalse(f"streamdeck_{jeu}" in self.regles, jeu)

    def test_the_deck_tools_are_never_gated(self):
        for cible in (
            "streamdeck",
            "streamdeck_erplibre",
            "streamdeck_tiler",
            "streamdeck_translator_doctor",
            "streamdeck_gallery",
        ):
            self.assertNotIn(GARDE, self.regles[cible][0], cible)

    def test_the_translator_targets_are_never_gated(self):
        """Les outils du traducteur ne sont pas des jeux : ni GAMES ni
        l'absence de games/ ne les arrêtent."""
        cibles = [
            c for c in self.regles if c.startswith("streamdeck_translator")
        ]
        for cible in (
            "streamdeck_translator_test",
            "streamdeck_translator_stream",
            "streamdeck_translator_unittest",
            "streamdeck_translator_install_whisper",
            "streamdeck_translator_install_ollama",
        ):
            self.assertIn(cible, cibles)
        for cible in cibles:
            prerequis = self.regles[cible][0]
            self.assertNotIn(GARDE, prerequis, cible)
            self.assertNotIn("streamdeck_games_present", prerequis, cible)

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
        self.assertGreater(len(self.regles), 30)
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
            "streamdeck_gallery": "gallery_server.py",
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
class TestMakefileGuard(unittest.TestCase):
    """Le fragment tourne dans une copie réduite du dépôt, avec ou sans
    faux games/ et faux clone du deck, sous un faux python qui affiche ses
    arguments. Le faux games/ porte game_<id>.py pour les ids inventés.
    Une cible de jeu passe par la passation : HOME, XDG_RUNTIME_DIR et
    systemctl sont ceux d'environnement_isole, avec une unité inactive ;
    self.conf est le fichier de réglages sous ce HOME."""

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.tmp = dossier.name
        self.faux = os.path.join(self.tmp, "python")
        with open(self.faux, "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\necho "faux-python $*"\n')
        os.chmod(self.faux, os.stat(self.faux).st_mode | stat.S_IXUSR)
        self.env, self.journal = environnement_isole(
            self.tmp, unite_active=False
        )
        self.conf = os.path.join(
            self.env["HOME"], ".config", "erplibre-home", "streamdeck.conf"
        )
        os.makedirs(os.path.dirname(self.conf))

    def depot(self, jeux=True, deck=True):
        """La copie réduite, avec game_<id>.py des ids inventés quand
        `jeux` ; rend son Path."""
        depot = copier_depot(
            os.path.join(
                self.tmp,
                ("avec" if jeux else "sans") + ("" if deck else "_sans_deck"),
            ),
            jeux=jeux,
            deck=deck,
        )
        if jeux:
            for jeu in (JEU_INVENTE, AUTRE_JEU_INVENTE):
                (depot / "script/stream_deck/games" / f"game_{jeu}.py").touch()
        return depot

    def make(
        self,
        cible,
        jeux=True,
        python=None,
        deck=True,
        depot=None,
        options=("-s",),
    ):
        return subprocess.run(
            [
                "make",
                *options,
                "-f",
                str(MAKEFILE),
                f"STREAMDECK_PY={python or self.faux}",
                cible,
            ],
            cwd=depot or self.depot(jeux=jeux, deck=deck),
            capture_output=True,
            text=True,
            timeout=30,
            env=self.env,
        )

    def test_a_missing_venv_stops_with_the_install_command(self):
        absent = os.path.join(self.tmp, "absent", "python")
        res = self.make(f"streamdeck_{JEU_INVENTE}", python=absent)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Stream Deck venv missing: " + INSTALL_DECK, res.stderr)

    def test_games_off_stops_a_game_target_with_the_message(self):
        conf = self.conf
        with open(conf, "w", encoding="utf-8") as f:
            f.write("GAMES=off\n")
        res = self.make(f"streamdeck_{JEU_INVENTE}")
        self.assertNotEqual(0, res.returncode)
        self.assertIn("Stream Deck games are disabled", res.stderr)
        self.assertNotIn("faux-python", res.stdout)
        res = self.make("streamdeck_erplibre")
        self.assertEqual(0, res.returncode, res.stderr)

    def test_an_unknown_games_value_stops_a_game_target_too(self):
        """Une valeur inconnue fait rendre 2 à deck_games_enabled, et non
        1 : la garde refuse aussi, avec la valeur dans le message."""
        conf = self.conf
        for valeur in ("yes", ""):
            with self.subTest(valeur=valeur):
                with open(conf, "w", encoding="utf-8") as f:
                    f.write(f"GAMES={valeur}\n")
                res = self.make(f"streamdeck_{JEU_INVENTE}")
                self.assertNotEqual(0, res.returncode)
                self.assertIn(
                    f"Stream Deck games are disabled (GAMES={valeur} in",
                    res.stderr,
                )
                self.assertNotIn("faux-python", res.stdout)

    def test_games_off_never_gates_the_translator_tools(self):
        conf = self.conf
        with open(conf, "w", encoding="utf-8") as f:
            f.write("GAMES=off\n")
        for cible in (
            "streamdeck_translator_doctor",
            "streamdeck_translator_test",
            "streamdeck_translator_stream",
            "streamdeck_translator_unittest",
        ):
            with self.subTest(cible=cible):
                res = self.make(cible, jeux=False)
                self.assertEqual(0, res.returncode, res.stderr)
                self.assertIn("faux-python", res.stdout)

    def test_the_gallery_runs_the_server_of_the_games_clone(self):
        res = self.make("streamdeck_gallery")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual(
            "faux-python script/stream_deck/games/gallery_server.py",
            res.stdout.strip(),
        )

    def test_a_missing_clone_stops_with_the_install_command(self):
        for cible in ("streamdeck_erplibre", "streamdeck", "streamdeck_tiler"):
            with self.subTest(cible=cible):
                res = self.make(cible, deck=False)
                self.assertNotEqual(0, res.returncode)
                self.assertNotIn("faux-python", res.stdout)
                self.assertIn("deck program is not installed", res.stderr)
                self.assertIn(INSTALL_DECK, res.stderr)

    def test_the_unittest_targets_run_the_deck_suite_from_the_clone(self):
        """streamdeck_tiler_unittest garde son nom et lance toute la suite
        du deck ; streamdeck_translator_unittest, celle du traducteur.
        Les deux depuis la racine du clone, qui trouve tests/."""
        ici = os.path.join(self.tmp, "python_ici")
        with open(ici, "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\necho "faux-python $(pwd) $*"\n')
        os.chmod(ici, 0o755)
        clone = os.path.realpath(
            os.path.join(self.tmp, "avec", "script/stream_deck/deck")
        )
        for cible, motif in (
            ("streamdeck_tiler_unittest", None),
            ("streamdeck_translator_unittest", "test_*translator.py"),
        ):
            with self.subTest(cible=cible):
                res = self.make(cible, python=ici)
                self.assertEqual(0, res.returncode, res.stderr)
                mots = res.stdout.split()
                self.assertEqual(["faux-python", clone], mots[:2])
                self.assertEqual(["-m", "unittest", "discover"], mots[2:5])
                self.assertEqual("tests", mots[mots.index("-s") + 1])
                if motif:
                    self.assertEqual(motif, mots[mots.index("-p") + 1])
                else:
                    self.assertNotIn("-p", mots)

    def test_missing_games_stop_the_game_and_gallery_targets(self):
        """Ni games/ ni la galerie : le programme du deck, lui, ne dépend
        pas des jeux."""
        for cible in (
            f"streamdeck_{JEU_INVENTE}",
            "streamdeck_gallery",
            "streamdeck_games",
        ):
            with self.subTest(cible=cible):
                res = self.make(cible, jeux=False)
                self.assertNotEqual(0, res.returncode)
                self.assertIn(
                    "Stream Deck games are not installed"
                    " (no games_cli.py in script/stream_deck/games/);"
                    " install them with " + INSTALL_DECK,
                    res.stderr,
                )
                self.assertNotIn("faux-python", res.stdout)
        res = self.make("streamdeck_erplibre", jeux=False)
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertIn("faux-python", res.stdout)

    def test_a_dry_run_hands_the_game_over_after_the_guard(self):
        """make -n montre la recette : la garde des jeux d'abord, puis la
        passation, qui reçoit le python du venv et le fichier du jeu."""
        res = self.make(f"streamdeck_{JEU_INVENTE}", options=("-n",))
        self.assertEqual(0, res.returncode, res.stderr)
        attendu = (
            f"{PASSATION} {self.faux}"
            f" script/stream_deck/games/game_{JEU_INVENTE}.py"
        )
        # Une commande continuée par « \ » s'affiche sur plusieurs lignes :
        # elles sont rejointes.
        lignes = re.sub(r"\s*\\\n\s*", " ", res.stdout).splitlines()
        self.assertIn(attendu, lignes)
        garde = next(
            i
            for i, ligne in enumerate(lignes)
            if "deck_games_enabled" in ligne
        )
        self.assertLess(garde, lignes.index(attendu))

    @SANS_DECK
    def test_a_game_runs_under_the_venv_through_the_handover(self):
        """Le faux systemctl voit la passation demander l'état du service :
        le jeu n'est pas lancé directement."""
        res = self.make(f"streamdeck_{JEU_INVENTE}")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual(
            f"faux-python script/stream_deck/games/game_{JEU_INVENTE}.py",
            res.stdout.strip(),
        )
        with open(self.journal, encoding="utf-8") as f:
            self.assertEqual(
                [
                    "systemctl --user is-active"
                    " erplibre-home-streamdeck.service"
                ],
                f.read().splitlines(),
            )

    @SANS_DECK
    def test_a_file_named_like_the_target_does_not_shadow_it(self):
        """La règle à motif ne peut être .PHONY, qui sauterait la recherche
        de règle implicite ; la garde, .PHONY, en est un prérequis : la
        cible est refaite même quand un fichier porte son nom."""
        depot = self.depot()
        (depot / f"streamdeck_{JEU_INVENTE}").touch()
        res = self.make(f"streamdeck_{JEU_INVENTE}", depot=depot)
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertIn("faux-python", res.stdout)

    def test_an_unknown_game_fails_with_its_name(self):
        res = self.make("streamdeck_nosuchgame")
        self.assertNotEqual(0, res.returncode)
        self.assertIn("Unknown Stream Deck game: nosuchgame", res.stderr)
        self.assertIn("make streamdeck_games", res.stderr)
        self.assertNotIn("faux-python", res.stdout)
        with open(self.journal, encoding="utf-8") as f:
            self.assertEqual("", f.read())

    def test_every_explicit_target_keeps_its_own_recipe(self):
        """make prend la règle à motif pour une cible explicite sans
        recette, sauf .PHONY. make -n de chaque cible streamdeck* ne doit
        ni passer le deck ni chercher un jeu. Une recette qui appelle
        $(MAKE) tourne même sous -n : la sienne, propre, suffit."""
        regles_ = regles(MAKEFILE.read_text(encoding="utf-8"))
        cibles = sorted(c for c in regles_ if c.startswith("streamdeck"))
        self.assertIn("streamdeck_tiler", cibles)
        self.assertIn("streamdeck_games", cibles)
        depot = self.depot()
        for cible in cibles:
            with self.subTest(cible=cible):
                commandes = regles_[cible][1]
                if any("$(MAKE)" in c for c in commandes):
                    continue
                res = self.make(cible, depot=depot, options=("-n",))
                self.assertNotIn("Unknown Stream Deck game", res.stderr)
                self.assertNotIn(PASSATION, res.stdout)

    def test_the_games_target_lists_the_ids_of_the_files(self):
        res = self.make("streamdeck_games")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual(
            sorted([JEU_INVENTE, AUTRE_JEU_INVENTE]), res.stdout.split()
        )

    @SANS_JEUX
    def test_the_games_target_lists_the_games_of_the_clone(self):
        """Lancée dans le checkout : streamdeck_games ne lit que les
        fichiers, sans python ni deck."""
        res = subprocess.run(
            ["make", "-s", "-f", str(MAKEFILE), "streamdeck_games"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=self.env,
        )
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual(jeux_installes(), res.stdout.split())


def charger_galerie():
    """Charge gallery_server.py par son chemin : script/stream_deck n'est
    pas un paquet."""
    chemin = GAMES_DIR / "gallery_server.py"
    spec = importlib.util.spec_from_file_location("gallery_server", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Un faux systemctl : chaque appel au journal, l'état de l'unité dans un
# fichier. Il n'est jamais le vrai : les tests qui lancent la passation
# posent aussi un HOME temporaire.
FAUX_SYSTEMCTL = """#!/bin/sh
echo "systemctl $*" >>"$JOURNAL"
case "$2" in
    is-active) cat "$ETAT"; [ "$(cat "$ETAT")" = active ] ;;
    stop) echo inactive >"$ETAT" ;;
    start) echo active >"$ETAT" ;;
esac
"""


def environnement_isole(tmp, unite_active):
    """Un environnement où la passation ne voit que des faux : HOME sous
    `tmp`, un fichier d'unité, le faux systemctl en tête du PATH, et
    XDG_RUNTIME_DIR sous `tmp`, où la passation prend le verrou du deck au
    lieu de celui du compte qui lance les tests. Rend (env, journal)."""
    home = os.path.join(tmp, "home")
    unite = os.path.join(
        home, ".config/systemd/user/erplibre-home-streamdeck.service"
    )
    os.makedirs(os.path.dirname(unite))
    with open(unite, "w", encoding="utf-8") as f:
        f.write("[Unit]\n")
    faux = os.path.join(tmp, "bin")
    os.makedirs(faux)
    with open(os.path.join(faux, "systemctl"), "w", encoding="utf-8") as f:
        f.write(FAUX_SYSTEMCTL)
    os.chmod(os.path.join(faux, "systemctl"), 0o755)
    etat = os.path.join(tmp, "etat")
    with open(etat, "w", encoding="utf-8") as f:
        f.write("active\n" if unite_active else "inactive\n")
    journal = os.path.join(tmp, "journal")
    open(journal, "w", encoding="utf-8").close()
    run_dir = os.path.join(tmp, "run")
    os.makedirs(run_dir, mode=0o700)
    env = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
    env.update(
        {
            "HOME": home,
            "XDG_RUNTIME_DIR": run_dir,
            "PATH": faux + os.pathsep + env.get("PATH", ""),
            "JOURNAL": journal,
            "ETAT": etat,
        }
    )
    return env, journal


@SANS_JEUX
@SANS_DECK
class TestGalleryLaunch(unittest.TestCase):
    def test_the_game_runs_under_the_server_interpreter(self):
        galerie = charger_galerie()
        jeu = "/srv/jeux de test/game_demo.py"
        mots = shlex.split(galerie._game_bash_cmd(jeu))
        self.assertEqual(
            mots[:6],
            [
                "cd",
                galerie.ERPLIBRE_DIR,
                "&&",
                str(
                    ROOT
                    / "script/install/erplibre_home_streamdeck_handover.sh"
                ),
                "bash",
                "-c",
            ],
        )
        boucle = mots[6]
        self.assertIn(
            f"{shlex.quote(sys.executable)} {shlex.quote(jeu)};", boucle
        )
        self.assertNotIn("python3 ", boucle)

    def test_the_loop_really_starts_that_interpreter(self):
        galerie = charger_galerie()
        with tempfile.TemporaryDirectory(prefix="jeu demo ") as tmp:
            env, _journal = environnement_isole(tmp, unite_active=False)
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
                env=env,
                timeout=30,
            )
        self.assertEqual(res.stdout.splitlines()[0], sys.executable)

    def test_two_rounds_run_inside_one_handover(self):
        """« r » puis Entrée relance la partie sans rendre le deck : le
        service s'arrête une fois avant la première, revient une fois après
        la dernière."""
        galerie = charger_galerie()
        with tempfile.TemporaryDirectory(prefix="jeu demo ") as tmp:
            env, journal = environnement_isole(tmp, unite_active=True)
            jeu = os.path.join(tmp, "game_demo.py")
            with open(jeu, "w", encoding="utf-8") as f:
                f.write(
                    "import os\n"
                    "with open(os.environ['JOURNAL'], 'a') as j:\n"
                    "    j.write('partie\\n')\n"
                )
            res = subprocess.run(
                ["bash", "-c", galerie._game_bash_cmd(jeu)],
                input="r\n\n",
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            with open(journal, encoding="utf-8") as f:
                appels = f.read().splitlines()
        unite = "erplibre-home-streamdeck.service"
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual(
            appels,
            [
                f"systemctl --user is-active {unite}",
                f"systemctl --user stop {unite}",
                "partie",
                "partie",
                f"systemctl --user reset-failed {unite}",
                f"systemctl --user start {unite}",
            ],
        )


@SANS_JEUX
class TestGalleryGames(unittest.TestCase):
    """La galerie relit GAMES à chaque lancement : off refuse, sans
    redémarrage."""

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.conf = Path(dossier.name, "erplibre-home", "streamdeck.conf")
        self.conf.parent.mkdir(parents=True)
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": dossier.name})
        env.start()
        self.addCleanup(env.stop)
        self.galerie = charger_galerie()

    def test_refusal_follows_the_file(self):
        self.assertIsNone(self.galerie._games_refusal())
        self.conf.write_text("GAMES=off\n", encoding="utf-8")
        self.assertIn("GAMES=off", self.galerie._games_refusal())
        self.conf.write_text("GAMES=on\n", encoding="utf-8")
        self.assertIsNone(self.galerie._games_refusal())

    def test_unreadable_setting_refuses(self):
        """Un réglage qu'on ne sait pas lire refuse, comme une valeur
        inconnue : la ligne dit pourquoi, et la galerie ne plante pas."""
        echecs = [
            FileNotFoundError(2, "No such file or directory", "bash"),
            subprocess.TimeoutExpired(["bash"], 10),
        ]
        for echec in echecs:
            vue = types.SimpleNamespace(
                run=mock.Mock(side_effect=echec),
                TimeoutExpired=subprocess.TimeoutExpired,
            )
            with mock.patch.object(self.galerie, "subprocess", vue):
                refus = self.galerie._games_refusal()
            self.assertIn("cannot read the GAMES setting", refus)
            self.assertNotIn("\n", refus)

    def test_main_refuses_to_start(self):
        self.conf.write_text("GAMES=off\n", encoding="utf-8")
        with (
            mock.patch.object(self.galerie.http.server, "HTTPServer") as srv,
            mock.patch("sys.stderr", new_callable=io.StringIO) as err,
        ):
            with self.assertRaises(SystemExit) as fin:
                self.galerie.main()
        self.assertEqual(1, fin.exception.code)
        srv.assert_not_called()
        self.assertIn("Stream Deck games are disabled", err.getvalue())

    def test_launch_rereads_the_setting(self):
        """Une galerie lancée avec on refuse dès que le fichier dit off."""
        gestionnaire = self.galerie.GameHandler.__new__(
            self.galerie.GameHandler
        )
        gestionnaire.wfile = io.BytesIO()
        codes = []
        gestionnaire.send_response = codes.append
        gestionnaire.send_header = lambda *a: None
        gestionnaire.end_headers = lambda: None
        self.conf.write_text("GAMES=off\n", encoding="utf-8")
        # subprocess.run appelle Popen : on ne remplace Popen que dans la
        # vue qu'en a la galerie, pour que la lecture du réglage tourne.
        popen = mock.Mock()
        vue = types.SimpleNamespace(run=subprocess.run, Popen=popen)
        with mock.patch.object(self.galerie, "subprocess", vue):
            gestionnaire._launch_game("snake")
        self.assertEqual([403], codes)
        popen.assert_not_called()
        self.assertIn(b"GAMES=off", gestionnaire.wfile.getvalue())


class TestLaunchGameScriptGone(unittest.TestCase):
    def test_the_script_is_removed(self):
        self.assertFalse((STREAM_DECK_DIR / "launch_game.sh").exists())

    def test_nothing_refers_to_it(self):
        """games/ et deck/ sont d'autres dépôts, et ne sont pas lus."""
        for chemin in STREAM_DECK_DIR.rglob("*"):
            if chemin.suffix not in {".py", ".js", ".html", ".md", ".sh"}:
                continue
            if (
                "node_modules" in chemin.parts
                or GAMES_DIR in chemin.parents
                or DECK in chemin.parents
            ):
                continue
            texte = chemin.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn("launch_game.sh", texte, str(chemin))


@SANS_DECK
class TestTheDeckProgramIsNotAGame(unittest.TestCase):
    def test_it_refuses_meta_and_declares_no_game_meta(self):
        """« --meta » est l'option par laquelle la galerie reconnaît un
        jeu : le programme du deck la refuse comme toute option inconnue,
        sans importer la bibliothèque Stream Deck, et son paquet ne déclare
        pas de GAME_META."""
        res = subprocess.run(
            [sys.executable, str(DECK / "erplibre_streamdeck"), "--meta"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(2, res.returncode, res.stderr)
        self.assertIn("usage:", res.stderr)
        self.assertEqual("", res.stdout)
        for source in (DECK / "erplibre_streamdeck").rglob("*.py"):
            texte = source.read_text(encoding="utf-8")
            self.assertNotIn("GAME_META", texte, str(source))


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
            mock.patch.object(todo_mod, "STREAMDECK_GAMES_CLI", self.present),
            mock.patch.object(
                todo_mod.click, "prompt", side_effect=list(reponses)
            ),
            contextlib.redirect_stdout(sortie),
        ):
            rendu = todo.prompt_execute_streamdeck_games()
        return todo, rendu, sortie.getvalue()

    def test_missing_games_say_how_to_install_them_and_scan_nothing(self):
        for langue, attendu in (
            (
                "en",
                "Stream Deck games are not installed"
                " (no games_cli.py in script/stream_deck/games/):"
                " make erplibre_home_streamdeck_install",
            ),
            (
                "fr",
                "Les jeux Stream Deck ne sont pas installés"
                " (pas de games_cli.py dans script/stream_deck/games/) :"
                " make erplibre_home_streamdeck_install",
            ),
        ):
            with self.subTest(langue=langue):
                todo_i18n._current_lang = langue
                todo = todo_mod.TODO.__new__(todo_mod.TODO)
                with (
                    mock.patch.object(
                        todo_mod, "VENV_STREAMDECK_PYTHON", self.present
                    ),
                    mock.patch.object(
                        todo_mod, "STREAMDECK_GAMES_CLI", self.absent
                    ),
                    mock.patch.object(
                        todo_mod.TODO, "_scan_streamdeck_games"
                    ) as scan,
                    mock.patch("sys.stdout", new_callable=io.StringIO) as out,
                ):
                    self.assertFalse(todo.prompt_execute_streamdeck_games())
                scan.assert_not_called()
                self.assertEqual(attendu, out.getvalue().strip())

    def test_the_games_cli_witness_is_the_one_of_the_checkout(self):
        self.assertEqual(
            str(GAMES_DIR / "games_cli.py"), todo_mod.STREAMDECK_GAMES_CLI
        )

    def test_games_off_says_so_and_scans_nothing(self):
        for langue, attendu in (
            (
                "en",
                "Stream Deck games are disabled (GAMES): enable them in"
                " TODO › ERPLibre Home › Games on/off, or set GAMES=on in ",
            ),
            (
                "fr",
                "Les jeux Stream Deck sont désactivés (GAMES) : activez-les"
                " dans TODO › ERPLibre Home › Jeux on/off, ou mettez GAMES=on"
                " dans ",
            ),
        ):
            with self.subTest(langue=langue):
                todo_i18n._current_lang = langue
                todo = todo_mod.TODO.__new__(todo_mod.TODO)
                with (
                    mock.patch.object(
                        todo_mod.os, "access", return_value=True
                    ),
                    mock.patch.object(
                        todo_mod, "STREAMDECK_GAMES_CLI", self.present
                    ),
                    mock.patch.object(
                        todo_mod.service,
                        "read_settings",
                        return_value={"GAMES": "off"},
                    ),
                    mock.patch.object(
                        todo_mod.TODO, "_scan_streamdeck_games"
                    ) as scan,
                    mock.patch("sys.stdout", new_callable=io.StringIO) as out,
                ):
                    self.assertFalse(todo.prompt_execute_streamdeck_games())
                scan.assert_not_called()
                self.assertIn(attendu, out.getvalue())
                self.assertIn(todo_mod.service.settings_path(), out.getvalue())

    def refus_des_jeux(self, python, valeur):
        """Joue le menu des jeux avec `python` pour venv et GAMES=`valeur`
        dans les réglages ; rend (rendu, sortie, scan)."""
        todo = todo_mod.TODO.__new__(todo_mod.TODO)
        with (
            mock.patch.object(todo_mod, "VENV_STREAMDECK_PYTHON", python),
            mock.patch.object(todo_mod, "STREAMDECK_GAMES_CLI", self.present),
            mock.patch.object(
                todo_mod.service,
                "read_settings",
                return_value={"GAMES": valeur},
            ),
            mock.patch.object(
                todo_mod.TODO, "_scan_streamdeck_games", return_value=[]
            ) as scan,
            mock.patch("sys.stdout", new_callable=io.StringIO) as out,
        ):
            rendu = todo.prompt_execute_streamdeck_games()
        return rendu, out.getvalue(), scan

    def test_an_unknown_games_value_is_refused_too(self):
        todo_i18n._current_lang = "en"
        for valeur in ("yes", ""):
            with self.subTest(valeur=valeur):
                rendu, sortie, scan = self.refus_des_jeux(self.present, valeur)
                self.assertFalse(rendu)
                self.assertIn("Stream Deck games are disabled (GAMES)", sortie)
                scan.assert_not_called()

    def test_the_venv_is_checked_before_the_games_setting(self):
        """Sans venv, le menu dit d'abord comment l'installer : GAMES=on
        n'y suffirait pas."""
        todo_i18n._current_lang = "en"
        rendu, sortie, scan = self.refus_des_jeux(self.absent, "off")
        self.assertFalse(rendu)
        self.assertEqual(MESSAGE_SANS_VENV, sortie.strip())
        scan.assert_not_called()

    def test_a_game_is_described_by_its_file_name_key(self):
        """game_<id>.py prend la description de la clé i18n « game_<id> »,
        dans la langue de l'utilisateur ; sans clé, la première ligne de
        sa docstring."""
        with tempfile.TemporaryDirectory() as tmp:
            chemins = []
            for nom in ("game_2048.py", "game_exemple_sans_cle.py"):
                chemin = os.path.join(tmp, nom)
                with open(chemin, "w", encoding="utf-8") as f:
                    f.write('"""\nLa docstring du jeu.\n"""\n')
                chemins.append(chemin)
            for langue in ("en", "fr"):
                with self.subTest(langue=langue):
                    todo_i18n._current_lang = langue
                    todo = todo_mod.TODO.__new__(todo_mod.TODO)
                    with mock.patch("glob.glob", return_value=chemins):
                        jeux = todo._scan_streamdeck_games()
                    attendu = todo_i18n.TRANSLATIONS["game_2048"][langue]
                    self.assertEqual(
                        [
                            f"2048 — {attendu}",
                            "Exemple Sans Cle — La docstring du jeu.",
                        ],
                        [j["description"] for j in jeux],
                    )

    def test_the_command_hands_the_deck_over_to_the_streamdeck_venv(self):
        todo = todo_mod.TODO.__new__(todo_mod.TODO)
        mots = shlex.split(todo._streamdeck_game_command(self.JEU))
        self.assertEqual(
            mots,
            [
                str(
                    ROOT
                    / "script/install/erplibre_home_streamdeck_handover.sh"
                ),
                str(ROOT / ".venv.streamdeck/bin/python"),
                self.JEU,
            ],
        )

    def test_the_menu_runs_the_chosen_game_with_that_command(self):
        todo, rendu, _sortie = self.menu(self.present)
        self.assertFalse(rendu)
        todo.execute.exec_command_live.assert_called_once_with(
            f"{shlex.quote(todo_mod.ERPLIBRE_HOME_STREAMDECK_HANDOVER)}"
            f" {shlex.quote(self.present)} {shlex.quote(self.JEU)}",
            source_erplibre=False,
            recap=False,
        )

    @SANS_DECK
    def test_the_command_really_runs_the_game(self):
        """La commande, jouée par bash : la passation, sans unité, lance
        le python du venv sur le jeu. Elle tourne dans une copie réduite du
        dépôt, avec un faux games/."""
        with tempfile.TemporaryDirectory(prefix="jeu demo ") as tmp:
            env, _journal = environnement_isole(tmp, unite_active=False)
            python = os.path.join(tmp, "python")
            with open(python, "w", encoding="utf-8") as f:
                f.write('#!/bin/sh\necho "$1"\n')
            os.chmod(python, 0o755)
            passation = copier_depot(os.path.join(tmp, "depot")) / (
                "script/install/erplibre_home_streamdeck_handover.sh"
            )
            todo = todo_mod.TODO.__new__(todo_mod.TODO)
            with (
                mock.patch.object(todo_mod, "VENV_STREAMDECK_PYTHON", python),
                mock.patch.object(
                    todo_mod,
                    "ERPLIBRE_HOME_STREAMDECK_HANDOVER",
                    str(passation),
                ),
            ):
                commande = todo._streamdeck_game_command(self.JEU)
            res = subprocess.run(
                ["bash", "-c", commande],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual(self.JEU, res.stdout.strip())

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
