#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le verrou du Stream Deck : un programme du deck à la fois.

Les détenteurs sont de vrais processus python, chacun avec son propre
verrou dans un répertoire temporaire : flock appartient à la description de
fichier ouverte, et seul un autre processus prouve qu'il tient jusqu'à la
sortie et pas au-delà.

Ce que ces tests gardent :

- un second preneur sort en 2 et nomme le programme et le PID du premier ;
- le verrou part avec le processus qui le tient, et se reprend ensuite ;
- deux ouvertures du même fichier s'excluent, même dans un seul processus,
  d'où l'exec du point d'entrée du service ;
- holder() dit qui tient le deck sans le prendre ;
- un lien à la place du verrou, ou un dossier ouvert aux autres comptes,
  est refusé sans rien écrire ; holder() n'y lit rien non plus, ne bloque
  pas sur une FIFO et ne rend qu'un PID fait de chiffres ;
- deck_lock.py lancé en commande tient le verrou au nom de « game » le
  temps de la commande, sans le passer à ses enfants, et rend son code ;
  un programme du deck qu'il lance, directement ou non, s'y range ;
- SIGTERM devient SystemExit : les finally et atexit d'un programme du
  deck passent ;
- le tiler et le contrôleur prennent le verrou avant d'ouvrir le deck.
"""

import ast
import fcntl
import importlib.util
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DECK_DIR = RACINE / "script/stream_deck"


def charger():
    """deck_lock.py par son chemin : script/stream_deck n'est pas un
    paquet."""
    spec = importlib.util.spec_from_file_location(
        "deck_lock", DECK_DIR / "deck_lock.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Le programme d'un preneur : argv = dossier du module, programme, chemin.
PRENDRE = (
    "import sys; sys.path.insert(0, sys.argv[1]); import deck_lock;"
    " deck_lock.{fonction}(sys.argv[2], sys.argv[3]);"
    " print('pret', flush=True); sys.stdin.read()"
)


class Verrou(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.chemin = os.path.join(dossier.name, "erplibre-home", "deck.lock")
        self.deck_lock = charger()

    def detenteur(self, programme="tiler"):
        """Un processus qui prend le verrou et le garde jusqu'à ce que son
        entrée standard se ferme. Rend le Popen une fois le verrou pris."""
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                PRENDRE.format(fonction="acquire"),
                str(DECK_DIR),
                programme,
                self.chemin,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(proc.wait, 10)
        self.addCleanup(proc.stdin.close)
        self.assertEqual("pret\n", proc.stdout.readline())
        return proc

    def second(self, programme="controller"):
        return subprocess.run(
            [
                sys.executable,
                "-c",
                PRENDRE.format(fonction="acquire_or_exit"),
                str(DECK_DIR),
                programme,
                self.chemin,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_a_second_holder_exits_two_and_names_the_first(self):
        premier = self.detenteur("tiler")
        fini = self.second("controller")
        self.assertEqual(2, fini.returncode, fini.stderr)
        self.assertEqual("", fini.stdout)
        self.assertIn("tiler", fini.stderr)
        self.assertIn("PID %d" % premier.pid, fini.stderr)

    def test_the_lock_leaves_with_its_process(self):
        premier = self.detenteur()
        premier.stdin.close()
        premier.wait(10)
        self.assertTrue(os.path.exists(self.chemin))
        fini = self.second()
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual("pret\n", fini.stdout)

    def test_two_opens_in_one_process_exclude_each_other(self):
        tenu = self.deck_lock.acquire("tiler", self.chemin)
        self.addCleanup(tenu.close)
        with self.assertRaises(self.deck_lock.DeckBusy) as pris:
            self.deck_lock.acquire("controller", self.chemin)
        self.assertEqual((str(os.getpid()), "tiler"), pris.exception.holder)

    def test_holder_names_who_holds_and_takes_nothing(self):
        self.assertIsNone(self.deck_lock.holder(self.chemin))
        premier = self.detenteur("tiler")
        for _fois in range(2):
            self.assertEqual(
                (str(premier.pid), "tiler"), self.deck_lock.holder(self.chemin)
            )
        premier.stdin.close()
        premier.wait(10)
        self.assertIsNone(self.deck_lock.holder(self.chemin))

    def test_the_directory_is_private(self):
        self.detenteur()
        mode = os.stat(os.path.dirname(self.chemin)).st_mode & 0o777
        self.assertEqual(0o700, mode)

    def test_a_symlinked_lock_is_refused_and_its_target_kept(self):
        """Un lien posé à la place du verrou n'est pas suivi : le fichier
        qu'il désigne garde son contenu."""
        dossier = os.path.dirname(self.chemin)
        os.makedirs(dossier, mode=0o700)
        cible = os.path.join(os.path.dirname(dossier), "cible")
        with open(cible, "w", encoding="utf-8") as fh:
            fh.write("exemple\n")
        os.symlink(cible, self.chemin)
        with self.assertRaises(OSError):
            self.deck_lock.acquire("tiler", self.chemin)
        with open(cible, encoding="utf-8") as fh:
            self.assertEqual("exemple\n", fh.read())

    def test_holder_does_not_follow_a_symlink(self):
        dossier = os.path.dirname(self.chemin)
        os.makedirs(dossier, mode=0o700)
        cible = os.path.join(os.path.dirname(dossier), "cible")
        with open(cible, "w", encoding="utf-8") as fh:
            fh.write("1 exemple\n")
        os.symlink(cible, self.chemin)
        tenu = open(cible, encoding="utf-8")
        self.addCleanup(tenu.close)
        fcntl.flock(tenu, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertIsNone(self.deck_lock.holder(self.chemin))

    def test_a_directory_open_to_others_is_refused(self):
        dossier = os.path.dirname(self.chemin)
        os.makedirs(dossier)
        os.chmod(dossier, 0o777)
        with self.assertRaises(OSError):
            self.deck_lock.acquire("tiler", self.chemin)
        self.assertFalse(os.path.exists(self.chemin))


class HolderPrudent(unittest.TestCase):
    """holder() lit un fichier que Status affiche, et dont la diagnostic tire
    un « kill <pid> » : rien n'y est repris sans contrôle."""

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.chemin = os.path.join(dossier.name, "erplibre-home", "deck.lock")
        self.deck_lock = charger()

    def tenir(self, texte, mode=0o700):
        """Pose le verrou avec `texte` et le tient par une ouverture à part,
        dans un dossier de mode `mode`."""
        dossier = os.path.dirname(self.chemin)
        os.makedirs(dossier, exist_ok=True)
        os.chmod(dossier, mode)
        fh = open(self.chemin, "w", encoding="utf-8")
        self.addCleanup(fh.close)
        fh.write(texte)
        fh.flush()
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_only_a_numeric_pid_is_kept(self):
        self.tenir("12;reboot tiler\n")
        self.assertEqual(("?", "tiler"), self.deck_lock.holder(self.chemin))

    def test_an_odd_program_name_is_not_kept(self):
        self.tenir("12 $(exemple)\n")
        self.assertEqual(("12", "?"), self.deck_lock.holder(self.chemin))

    def test_a_directory_open_to_others_gives_no_holder(self):
        self.tenir("12 tiler\n", mode=0o777)
        self.assertIsNone(self.deck_lock.holder(self.chemin))

    def test_a_fifo_does_not_hang(self):
        """Une FIFO sans écrivain bloquerait un open() sans O_NONBLOCK."""
        dossier = os.path.dirname(self.chemin)
        os.makedirs(dossier, mode=0o700)
        os.mkfifo(self.chemin)
        fini = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]);"
                " import deck_lock; print(deck_lock.holder(sys.argv[2]))",
                str(DECK_DIR),
                self.chemin,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual("None\n", fini.stdout)


# Un programme python qui écrit le détenteur vu de l'intérieur de la
# commande, et le PID de son parent : argv = dossier du module, chemin.
VU_DEDANS = (
    "import os, sys; sys.path.insert(0, sys.argv[1]); import deck_lock;"
    " print(deck_lock.holder(sys.argv[2]), os.getppid())"
)


class LaCommandeSousVerrou(unittest.TestCase):
    """deck_lock.py <programme> <commande…> : ce que la passation lance."""

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.run_dir = dossier.name
        self.chemin = os.path.join(self.run_dir, "erplibre-home", "deck.lock")
        self.deck_lock = charger()
        self.environ = dict(os.environ, XDG_RUNTIME_DIR=self.run_dir)

    def lancer(self, *commande, **kw):
        return subprocess.run(
            [sys.executable, str(DECK_DIR / "deck_lock.py"), *commande],
            capture_output=True,
            text=True,
            env=self.environ,
            timeout=30,
            **kw,
        )

    def test_the_command_runs_under_the_lock_as_game(self):
        fini = self.lancer(
            "game", sys.executable, "-c", VU_DEDANS, str(DECK_DIR), self.chemin
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        tenu, parent = fini.stdout.rsplit(" ", 1)
        self.assertEqual(str((parent.strip(), "game")), tenu)
        self.assertIsNone(self.deck_lock.holder(self.chemin))

    def test_the_exit_code_and_a_signal_pass_through(self):
        self.assertEqual(
            7, self.lancer("game", "sh", "-c", "exit 7").returncode
        )
        self.assertEqual(
            128 + signal.SIGTERM,
            self.lancer("game", "sh", "-c", "kill -TERM $$").returncode,
        )

    def test_a_missing_command_says_so(self):
        fini = self.lancer("game", os.path.join(self.run_dir, "absent"))
        self.assertEqual(127, fini.returncode)
        self.assertIn("absent", fini.stderr)

    def test_no_command_is_a_usage_error(self):
        fini = self.lancer("game")
        self.assertEqual(1, fini.returncode)
        self.assertIn("usage", fini.stderr)

    def test_a_child_left_behind_does_not_keep_the_lock(self):
        """Le descripteur du verrou ne passe pas à la commande : un enfant
        qu'elle laisse derrière elle ne tient pas le deck."""
        fini = self.lancer(
            "game", "sh", "-c", "sleep 30 >/dev/null 2>&1 & echo $!"
        )
        orphelin = int(fini.stdout)
        self.addCleanup(os.kill, orphelin, signal.SIGKILL)
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertIsNone(self.deck_lock.holder(self.chemin))

    def test_a_busy_deck_runs_nothing_and_exits_two(self):
        tenu = self.deck_lock.acquire("tiler", self.chemin)
        self.addCleanup(tenu.close)
        marque = os.path.join(self.run_dir, "marque")
        fini = self.lancer("game", "touch", marque)
        self.assertEqual(2, fini.returncode)
        self.assertIn("tiler", fini.stderr)
        self.assertFalse(os.path.exists(marque))

    def test_a_deck_program_under_the_command_shares_its_lock(self):
        """Le tiler lancé comme un jeu, par TODO (enfant direct) ou la
        galerie (sous bash) : il trouve le verrou tenu par un ancêtre au nom
        de « game » et tourne au lieu de sortir en 2."""
        prendre = PRENDRE.format(fonction="acquire_or_exit")
        for commande in (
            [sys.executable, "-c", prendre, str(DECK_DIR), "tiler"],
            [
                "sh",
                "-c",
                '"$@"',
                "sh",
                sys.executable,
                "-c",
                prendre,
                str(DECK_DIR),
                "tiler",
            ],
        ):
            with self.subTest(commande=commande[0]):
                fini = self.lancer(
                    "game", *commande, self.chemin, stdin=subprocess.DEVNULL
                )
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertEqual("pret\n", fini.stdout)

    def test_a_deck_program_outside_the_command_still_exits_two(self):
        jeu = subprocess.Popen(
            [
                sys.executable,
                str(DECK_DIR / "deck_lock.py"),
                "game",
                "sleep",
                "30",
            ],
            env=self.environ,
        )
        self.addCleanup(jeu.wait, 10)
        self.addCleanup(jeu.kill)
        self.attendre_le_jeu(jeu)
        fini = subprocess.run(
            [
                sys.executable,
                "-c",
                PRENDRE.format(fonction="acquire_or_exit"),
                str(DECK_DIR),
                "tiler",
                self.chemin,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(2, fini.returncode, fini.stderr)
        self.assertIn("game (PID %d)" % jeu.pid, fini.stderr)

    def attendre_le_jeu(self, jeu):
        for _fois in range(100):
            if self.deck_lock.holder(self.chemin) == (str(jeu.pid), "game"):
                return
            time.sleep(0.05)
        self.fail("the lock was never taken as game")

    def test_sigterm_to_the_wrapper_ends_the_game(self):
        """« kill <pid> », que la diagnostic propose quand un jeu tient le
        deck, vise l'enveloppe : elle passe SIGTERM au jeu et sort avec son
        code."""
        jeu = subprocess.Popen(
            [
                sys.executable,
                str(DECK_DIR / "deck_lock.py"),
                "game",
                "sleep",
                "30",
            ],
            env=self.environ,
        )
        self.addCleanup(jeu.kill)
        self.attendre_le_jeu(jeu)
        jeu.send_signal(signal.SIGTERM)
        self.assertEqual(128 + signal.SIGTERM, jeu.wait(10))
        self.assertIsNone(self.deck_lock.holder(self.chemin))


# Un programme du deck réduit à son nettoyage : argv = dossier du module,
# fichier où noter ce qui a tourné.
NETTOYAGE = """
import atexit, sys, time
sys.path.insert(0, sys.argv[1])
import deck_lock
deck_lock.exit_on_sigterm()
def noter(quoi):
    with open(sys.argv[2], "a") as fh:
        fh.write(quoi + "\\n")
atexit.register(noter, "atexit")
try:
    print("pret", flush=True)
    time.sleep(30)
finally:
    noter("finally")
"""


class SigtermPropre(unittest.TestCase):
    def test_sigterm_runs_finally_and_atexit(self):
        with tempfile.TemporaryDirectory() as dossier:
            notes = os.path.join(dossier, "notes")
            proc = subprocess.Popen(
                [sys.executable, "-c", NETTOYAGE, str(DECK_DIR), notes],
                stdout=subprocess.PIPE,
                text=True,
            )
            self.addCleanup(proc.kill)
            self.assertEqual("pret\n", proc.stdout.readline())
            proc.send_signal(signal.SIGTERM)
            self.assertEqual(128 + signal.SIGTERM, proc.wait(10))
            proc.stdout.close()
            with open(notes, encoding="utf-8") as fh:
                self.assertEqual(["finally", "atexit"], fh.read().split())


class LeChemin(unittest.TestCase):
    def test_under_the_runtime_dir(self):
        deck_lock = charger()
        self.assertEqual(
            "/exemple/run/erplibre-home/deck.lock",
            deck_lock.lock_path({"XDG_RUNTIME_DIR": "/exemple/run"}),
        )

    def test_without_runtime_dir_a_per_user_temp_dir(self):
        deck_lock = charger()
        self.assertEqual(
            os.path.join(
                tempfile.gettempdir(),
                "erplibre-home-%d" % os.getuid(),
                "deck.lock",
            ),
            deck_lock.lock_path({}),
        )


def fonction(source, nom):
    arbre = ast.parse(source)
    return next(
        n
        for n in ast.walk(arbre)
        if isinstance(n, ast.FunctionDef) and n.name == nom
    )


def appel_du_verrou(instruction):
    """« deck_lock.acquire_or_exit('<programme>') » : rend le programme,
    None pour toute autre instruction."""
    if not isinstance(instruction, ast.Expr):
        return None
    appel = instruction.value
    if (
        isinstance(appel, ast.Call)
        and isinstance(appel.func, ast.Attribute)
        and isinstance(appel.func.value, ast.Name)
        and appel.func.value.id == "deck_lock"
        and appel.func.attr == "acquire_or_exit"
        and len(appel.args) == 1
        and isinstance(appel.args[0], ast.Constant)
    ):
        return appel.args[0].value
    return None


class LesProgrammesLePrennent(unittest.TestCase):
    """Le verrou se prend AVANT d'ouvrir le deck : le second programme sort
    sans avoir touché au périphérique du premier."""

    def test_the_tiler_takes_it_first_thing_in_main(self):
        source = (DECK_DIR / "game_tiler.py").read_text(encoding="utf-8")
        main = fonction(source, "main")
        self.assertEqual("tiler", appel_du_verrou(main.body[0]))
        self.assertIn("\nimport deck_lock\n", source)

    def test_the_controller_takes_it_before_its_pidfile(self):
        source = (DECK_DIR / "erplibre_controller.py").read_text(
            encoding="utf-8"
        )
        arbre = ast.parse(source)
        principal = next(
            n
            for n in arbre.body
            if isinstance(n, ast.If)
            and isinstance(n.test, ast.Compare)
            and isinstance(n.test.left, ast.Name)
            and n.test.left.id == "__name__"
        )
        self.assertEqual("controller", appel_du_verrou(principal.body[0]))
        self.assertIn("\nimport deck_lock\n", source)


if __name__ == "__main__":
    unittest.main()
