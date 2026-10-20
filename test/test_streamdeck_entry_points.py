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
  $(STREAMDECK_PY), hors l'aide d'activation de l'extension et le
  compilateur des locales, qui ne sont pas du code du deck et gardent le
  python du système ; toute cible qui s'en sert l'a en prérequis : sans
  venv, elle s'arrête sur la commande qui le bâtit,
  make erplibre_home_streamdeck_install ;
- requirements.txt porte ce que le code importe, et plus lz4, que le venv
  ne sert pas ;
- la galerie lance un jeu sous son propre interpréteur, cité pour bash, et
  toute sa boucle de parties dans une seule passation du deck ;
- le menu TODO lance un jeu sous le python du venv, à travers la passation
  du deck, et sans venv il le dit dans la langue de l'utilisateur sans rien
  lancer ;
- launch_game.sh, que rien n'appelait, n'existe plus ;
- le programme du deck, le contrôleur et chaque jeu répondent à -h,
  --help et à une option inconnue sans importer le matériel ni prendre le
  verrou du deck ; --meta d'un jeu rend toujours son JSON.
"""

import concurrent.futures
import contextlib
import importlib.util
import io
import json
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

sys.argv = ["todo.py"]
from script.todo import todo as todo_mod  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "conf" / "make.streamdeck.Makefile"
GARDE = "streamdeck_games_guard"
DECK_DIR = ROOT / "script" / "stream_deck"
GAMES_DIR = DECK_DIR / "games"
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
# Deux appels restent hors du venv. L'aide d'activation de l'extension passe
# par son shebang : elle n'importe que la bibliothèque standard et tourne
# avant que le venv existe. Le compilateur des locales n'est pas un point
# d'entrée du deck : il garde le python3 du système.
HORS_VENV = re.compile(
    r"/tools/enable_next_login\.py\b|/po/compile_locales\.py\b"
)
SHEBANG_DECK = re.compile(r"\./script/stream_deck/[\w/]+\.py")
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

    def test_every_game_target_requires_the_games_guard(self):
        for jeu in jeux():
            self.assertIn(GARDE, self.regles[f"streamdeck_{jeu}"][0], jeu)

    def test_the_deck_tools_are_never_gated(self):
        for cible in (
            "streamdeck",
            "streamdeck_erplibre",
            "streamdeck_tiler",
            "streamdeck_translator_doctor",
            "streamdeck_gallery",
        ):
            self.assertNotIn(GARDE, self.regles[cible][0], cible)

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
                [f"{VENV_REF} script/stream_deck/games/game_{jeu}.py"],
            )

    def test_the_tiler_target_is_an_alias(self):
        prerequis, commandes = self.regles["streamdeck_tiler"]
        self.assertEqual(["streamdeck_erplibre"], prerequis)
        self.assertEqual([], commandes)

    def test_the_tiler_runs_the_package_directory(self):
        commandes = " ".join(self.regles["streamdeck_erplibre"][1])
        self.assertRegex(
            commandes, r"script/stream_deck/erplibre_streamdeck(?![\w./])"
        )

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

    def test_games_off_stops_a_game_target_with_the_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = os.path.join(tmp, "erplibre-home", "streamdeck.conf")
            os.makedirs(os.path.dirname(conf))
            with open(conf, "w", encoding="utf-8") as f:
                f.write("GAMES=off\n")
            faux = os.path.join(tmp, "python")
            with open(faux, "w", encoding="utf-8") as f:
                f.write('#!/bin/sh\necho "faux-python $*"\n')
            os.chmod(faux, 0o755)
            env = dict(os.environ, XDG_CONFIG_HOME=tmp)

            def make(cible):
                return subprocess.run(
                    [
                        "make",
                        "-s",
                        "-f",
                        str(MAKEFILE),
                        f"STREAMDECK_PY={faux}",
                        cible,
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env,
                )

            res = make("streamdeck_snake")
            self.assertNotEqual(0, res.returncode)
            self.assertIn("Stream Deck games are disabled", res.stderr)
            self.assertNotIn("faux-python", res.stdout)
            res = make("streamdeck_erplibre")
            self.assertEqual(0, res.returncode, res.stderr)

    def test_a_present_venv_runs_the_game_under_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            faux = os.path.join(tmp, "python")
            with open(faux, "w", encoding="utf-8") as f:
                f.write('#!/bin/sh\necho "faux-python $*"\n')
            os.chmod(faux, os.stat(faux).st_mode | stat.S_IXUSR)
            res = self.make(f"STREAMDECK_PY={faux}", "streamdeck_snake")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(
            res.stdout.strip(),
            "faux-python script/stream_deck/games/game_snake.py",
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

    def test_polib_left_the_venv(self):
        """compile_locales.py tourne sous le python3 du système, et
        l'installateur compile par msgfmt : rien du venv n'importe polib."""
        self.assertNotIn("polib", self.noms())


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
                str(ROOT / "script/install/erplibre_home_handover.sh"),
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
        self.assertFalse((DECK_DIR / "launch_game.sh").exists())

    def test_nothing_refers_to_it(self):
        for chemin in DECK_DIR.rglob("*"):
            if chemin.suffix not in {".py", ".js", ".html", ".md", ".sh"}:
                continue
            if "node_modules" in chemin.parts:
                continue
            texte = chemin.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn("launch_game.sh", texte, str(chemin))


# De faux paquets du matériel (StreamDeck, PIL, cv2...), placés en tête de
# PYTHONPATH : les importer écrit un témoin et tue le processus. Un
# programme du deck lancé par erreur ne touche donc jamais un vrai deck, et
# le témoin le dit.
FAUX_MATERIEL = """import os
with open(os.environ["TEMOIN_MATERIEL"], "w") as f:
    f.write(__name__)
os._exit(99)
"""


# Les paquets que les points d'entrée du deck importent pour le matériel.
PAQUETS_MATERIEL = ("StreamDeck", "PIL", "cv2", "requests", "pyudev")


def executer_sans_materiel(script, *args):
    """Lance `script` sous le python des tests avec les faux paquets du
    matériel et un XDG_RUNTIME_DIR temporaire. Rend le CompletedProcess, si
    un faux a posé son témoin, et le contenu du répertoire du verrou du
    deck. N'affirme rien : un fil peut l'appeler."""
    with tempfile.TemporaryDirectory() as tmp:
        faux = os.path.join(tmp, "faux")
        for paquet in PAQUETS_MATERIEL:
            os.makedirs(os.path.join(faux, paquet))
            init = os.path.join(faux, paquet, "__init__.py")
            with open(init, "w", encoding="utf-8") as f:
                f.write(FAUX_MATERIEL)
        run_dir = os.path.join(tmp, "run")
        os.makedirs(run_dir, mode=0o700)
        temoin = os.path.join(tmp, "temoin")
        env = dict(
            os.environ,
            PYTHONPATH=faux,
            XDG_RUNTIME_DIR=run_dir,
            XDG_CONFIG_HOME=os.path.join(tmp, "config"),
            XDG_CACHE_HOME=os.path.join(tmp, "cache"),
            HOME=os.path.join(tmp, "home"),
            TEMOIN_MATERIEL=temoin,
        )
        res = subprocess.run(
            [sys.executable, str(script)] + list(args),
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return res, os.path.exists(temoin), os.listdir(run_dir)


def lancer_sans_materiel(cas, script, *args, materiel=False):
    """executer_sans_materiel(), puis échoue si le verrou du deck a été
    pris, et si un faux a posé son témoin ou non selon `materiel`. Rend le
    CompletedProcess."""
    res, importe, verrou = executer_sans_materiel(script, *args)
    cas.assertEqual(materiel, importe, res.stderr)
    cas.assertEqual([], verrou, "le verrou du deck a été pris")
    return res


class TestTilerCommandLine(unittest.TestCase):
    """La ligne de commande du programme du deck : -h et --help affichent
    l'aide et sortent en 0, toute autre option l'affiche sur la sortie
    d'erreur et sort en 2. Ni l'une ni l'autre n'importe le matériel ni ne
    prend le verrou du deck, posé ici sous un XDG_RUNTIME_DIR temporaire."""

    def lancer(self, *args):
        return lancer_sans_materiel(
            self, DECK_DIR / "erplibre_streamdeck", *args
        )

    def test_help_prints_the_usage_and_exits_0(self):
        for option in ("-h", "--help"):
            res = self.lancer(option)
            self.assertEqual(0, res.returncode, res.stderr)
            self.assertIn("usage:", res.stdout)
            self.assertIn("--list-plugins", res.stdout)
            self.assertIn("erplibre-home/streamdeck.conf", res.stdout)
            self.assertEqual("", res.stderr)

    def test_help_names_the_exit_codes(self):
        aide = self.lancer("--help").stdout
        for code in ("2", "3", "143"):
            self.assertRegex(aide, r"(?m)^\s+%s\s" % code)

    def test_an_unknown_option_exits_2_with_the_usage(self):
        for args in (
            ["--bogus"],
            ["run"],
            ["--list"],
            ["--list-plugins", "x"],
        ):
            res = self.lancer(*args)
            self.assertEqual(2, res.returncode, args)
            self.assertIn("usage:", res.stderr, args)
            self.assertEqual("", res.stdout, args)


class TestControllerCommandLine(unittest.TestCase):
    """La ligne de commande du contrôleur : -h et --help sortent en 0, une
    option inconnue en 2 avec l'usage sur la sortie d'erreur, avant les
    imports de cv2, de PIL et de StreamDeck et sans le verrou du deck."""

    SCRIPT = DECK_DIR / "erplibre_controller.py"

    def test_help_prints_the_usage_and_exits_0(self):
        for option in ("-h", "--help"):
            res = lancer_sans_materiel(self, self.SCRIPT, option)
            self.assertEqual(0, res.returncode, res.stderr)
            self.assertIn("usage:", res.stdout)
            self.assertIn("deck lock", res.stdout)
            self.assertRegex(res.stdout, r"(?m)^\s+2\s")
            self.assertRegex(res.stdout, r"(?m)^\s+143\s")
            self.assertEqual("", res.stderr)

    def test_an_unknown_option_exits_2_with_the_usage(self):
        for args in (["--bogus"], ["run"], ["--hel"], ["-x"]):
            res = lancer_sans_materiel(self, self.SCRIPT, *args)
            self.assertEqual(2, res.returncode, args)
            self.assertIn("usage:", res.stderr, args)
            self.assertEqual("", res.stdout, args)

    def test_without_an_option_it_goes_on_to_the_hardware(self):
        """Sans option, rien ne s'arrête à la ligne de commande : le
        premier import du matériel est atteint, et son faux tue le
        processus avant le verrou."""
        res = lancer_sans_materiel(self, self.SCRIPT, materiel=True)
        self.assertEqual(99, res.returncode, res.stderr)


def en_parallele(fonction, appels):
    """fonction(*appel) pour chaque appel, sur 8 fils : un processus par
    jeu reste rapide. Rend les résultats dans l'ordre des appels."""
    with concurrent.futures.ThreadPoolExecutor(8) as fils:
        return list(fils.map(lambda appel: fonction(*appel), appels))


class TestGamesCommandLine(unittest.TestCase):
    """La ligne de commande de chaque jeu, que games_cli lui donne : -h et
    --help sortent en 0, une option inconnue en 2, avant l'import de PIL et
    de StreamDeck et sans le verrou du deck ; sans option, le jeu va
    jusqu'au matériel. --meta garde la sortie que lit la galerie."""

    def lancer_tous(self, *args):
        """(jeu, CompletedProcess, témoin posé, verrou) pour chaque jeu."""
        chemins = [GAMES_DIR / ("game_%s.py" % jeu) for jeu in jeux()]
        resultats = en_parallele(
            executer_sans_materiel, [(c,) + args for c in chemins]
        )
        return [(c.name,) + r for c, r in zip(chemins, resultats)]

    def test_every_game_answers_help_with_its_usage(self):
        resultats = self.lancer_tous("-h")
        self.assertEqual(45, len(resultats))
        for jeu, res, importe, verrou in resultats:
            with self.subTest(jeu=jeu):
                self.assertFalse(importe, res.stderr)
                self.assertEqual([], verrou)
                self.assertEqual(0, res.returncode, res.stderr)
                self.assertIn("usage: %s" % jeu, res.stdout)
                self.assertIn("--meta", res.stdout)
                self.assertEqual("", res.stderr)

    def test_every_game_refuses_an_unknown_option_with_2(self):
        for jeu, res, importe, verrou in self.lancer_tous("--bogus"):
            with self.subTest(jeu=jeu):
                self.assertFalse(importe, res.stderr)
                self.assertEqual([], verrou)
                self.assertEqual(2, res.returncode, res.stderr)
                self.assertIn("usage:", res.stderr)
                self.assertEqual("", res.stdout)

    def test_without_an_option_every_game_goes_on_to_the_hardware(self):
        for jeu, res, importe, verrou in self.lancer_tous():
            with self.subTest(jeu=jeu):
                self.assertTrue(importe, res.stderr)
                self.assertEqual(99, res.returncode, res.stderr)

    def test_the_options_of_a_game_are_still_read(self):
        """Hangman et Minesweeper ajoutent les leurs au parseur commun :
        elles passent la ligne de commande et vont jusqu'au matériel."""
        for jeu, args in (
            ("game_hangman.py", ["-l", "en"]),
            ("game_minesweeper.py", ["-m", "6", "-v"]),
        ):
            res = lancer_sans_materiel(
                self, GAMES_DIR / jeu, *args, materiel=True
            )
            self.assertEqual(99, res.returncode, (jeu, res.stderr))
        res = lancer_sans_materiel(
            self, GAMES_DIR / "game_hangman.py", "-l", "de"
        )
        self.assertEqual(2, res.returncode, res.stderr)

    @unittest.skipUnless(
        (ROOT / ".venv.streamdeck" / "bin" / "python").exists(),
        "sans .venv.streamdeck, les jeux n'importent pas leurs dépendances",
    )
    def test_meta_prints_the_json_the_gallery_reads(self):
        """Le vrai --meta, sous le python du venv comme dans la galerie :
        il importe la bibliothèque Stream Deck sans ouvrir le deck."""
        python = str(ROOT / ".venv.streamdeck" / "bin" / "python")

        def meta(jeu):
            return subprocess.run(
                [python, str(GAMES_DIR / ("game_%s.py" % jeu)), "--meta"],
                capture_output=True,
                text=True,
                timeout=30,
            )

        tous = jeux()
        for jeu, res in zip(tous, en_parallele(meta, [(j,) for j in tous])):
            with self.subTest(jeu=jeu):
                self.assertEqual(0, res.returncode, res.stderr)
                self.assertIn("name", json.loads(res.stdout))


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

    def test_games_off_says_so_and_scans_nothing(self):
        for langue, attendu in (
            (
                "en",
                "Stream Deck games are disabled (GAMES): enable them in"
                " TODO › Stream Deck › Games on/off, or set GAMES=on in ",
            ),
            (
                "fr",
                "Les jeux Stream Deck sont désactivés (GAMES) : activez-les"
                " dans TODO › Stream Deck › Jeux on/off, ou mettez GAMES=on"
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
                self.assertIn(
                    todo_mod.service.settings_path(), out.getvalue()
                )

    def test_the_command_hands_the_deck_over_to_the_streamdeck_venv(self):
        todo = todo_mod.TODO.__new__(todo_mod.TODO)
        mots = shlex.split(todo._streamdeck_game_command(self.JEU))
        self.assertEqual(
            mots,
            [
                str(ROOT / "script/install/erplibre_home_handover.sh"),
                str(ROOT / ".venv.streamdeck/bin/python"),
                self.JEU,
            ],
        )

    def test_the_menu_runs_the_chosen_game_with_that_command(self):
        todo, rendu, _sortie = self.menu(self.present)
        self.assertFalse(rendu)
        todo.execute.exec_command_live.assert_called_once_with(
            f"{shlex.quote(todo_mod.ERPLIBRE_HOME_HANDOVER)}"
            f" {shlex.quote(self.present)} {shlex.quote(self.JEU)}",
            source_erplibre=False,
            recap=False,
        )

    def test_the_command_really_runs_the_game(self):
        """La commande, jouée par bash : la passation, sans unité, lance
        le python du venv sur le jeu."""
        with tempfile.TemporaryDirectory(prefix="jeu demo ") as tmp:
            env, _journal = environnement_isole(tmp, unite_active=False)
            python = os.path.join(tmp, "python")
            with open(python, "w", encoding="utf-8") as f:
                f.write('#!/bin/sh\necho "$1"\n')
            os.chmod(python, 0o755)
            todo = todo_mod.TODO.__new__(todo_mod.TODO)
            with mock.patch.object(todo_mod, "VENV_STREAMDECK_PYTHON", python):
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
