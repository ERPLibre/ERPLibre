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
- deck_lock.py lancé en commande tient le verrou au nom de « game » et le
  passe à la commande : tant qu'un processus du jeu vit, le deck reste
  pris, l'enveloppe fût-elle tuée ; il rend le code de la commande ;
- SIGTERM ou SIGINT envoyé à l'enveloppe atteint tous ses descendants, un
  jeu lancé sous un shell compris, et l'enveloppe attend leur fin ; SIGINT
  épargne ceux que le terminal a déjà frappés ;
- un programme du deck lancé sous le jeu tourne sous son verrou, et le
  reprend à son compte s'il survit au jeu sans en avoir hérité ;
- SIGTERM devient SystemExit : les finally et atexit d'un programme du
  deck passent ;
- le tiler et le contrôleur prennent le verrou avant d'ouvrir le deck,
  remettent le deck à zéro sur SIGTERM, et le tiler sort en 3 sans deck.
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
        self.addCleanup(proc.stdout.close)
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

    def test_a_holder_leaving_during_acquire_hands_the_lock_over(self):
        """Le détenteur sort entre l'échec du flock et la recherche d'un
        descripteur hérité : acquire() prend le verrou par son propre
        fichier, au lieu de rouvrir un descripteur qu'il vient de fermer."""
        premier = self.detenteur("tiler")
        lire = self.deck_lock.parse_holder

        def le_detenteur_sort(texte):
            premier.stdin.close()
            premier.wait(10)
            return lire(texte)

        self.deck_lock.parse_holder = le_detenteur_sort
        tenu = self.deck_lock.acquire("controller", self.chemin)
        self.addCleanup(tenu.close)
        self.assertEqual(
            (str(os.getpid()), "controller"),
            self.deck_lock.holder(self.chemin),
        )

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

    def test_holder_pids_names_the_processes_with_the_lock_open(self):
        self.assertEqual([], self.deck_lock.holder_pids(self.chemin))
        premier = self.detenteur("tiler")
        self.assertEqual(
            [premier.pid], self.deck_lock.holder_pids(self.chemin)
        )
        premier.stdin.close()
        premier.wait(10)
        self.assertEqual([], self.deck_lock.holder_pids(self.chemin))

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


# Un programme du deck qui prend le verrou puis reste : argv = dossier du
# module, programme, chemin.
RESTER = (
    "import sys, time; sys.path.insert(0, sys.argv[1]); import deck_lock;"
    " deck_lock.acquire_or_exit(sys.argv[2], sys.argv[3]);"
    " print('pret', flush=True); time.sleep(30)"
)


def vivant(pid):
    """Le processus `pid` existe et n'est pas un zombie."""
    try:
        with open("/proc/%d/stat" % pid, encoding="utf-8") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] not in "ZX"
    except OSError:
        return False


def tuer(pid):
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    for _fois in range(200):
        if not vivant(pid):
            return
        time.sleep(0.05)


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

    def test_a_child_left_behind_keeps_the_deck(self):
        """Le descripteur du verrou passe à la commande et à ses enfants : un
        processus que le jeu laisse derrière lui tient encore le deck, et le
        service relancé sort en 2 au lieu de s'y superposer."""
        fini = self.lancer(
            "game", "sh", "-c", "sleep 30 >/dev/null 2>&1 & echo $!"
        )
        orphelin = int(fini.stdout)
        self.addCleanup(tuer, orphelin)
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual("game", self.deck_lock.holder(self.chemin)[1])
        tuer(orphelin)
        self.attendre_le_verrou_libre()

    def test_the_deck_stays_locked_when_the_wrapper_is_killed(self):
        marque = os.path.join(self.run_dir, "jeu.pid")
        jeu = self.envelopper(
            "sh", "-c", 'echo $$ > "$0"; exec sleep 30', marque
        )
        pid = self.lire_pid(marque)
        self.addCleanup(tuer, pid)
        jeu.kill()
        jeu.wait(10)
        self.assertEqual(
            (str(jeu.pid), "game"), self.deck_lock.holder(self.chemin)
        )
        tuer(pid)
        self.attendre_le_verrou_libre()

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

    def envelopper(self, *commande):
        """L'enveloppe lancée sur `commande`, dans sa propre session : sans
        terminal, aucun signal ne lui vient du terminal du lanceur de
        tests."""
        jeu = subprocess.Popen(
            [
                sys.executable,
                str(DECK_DIR / "deck_lock.py"),
                "game",
                *commande,
            ],
            env=self.environ,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.addCleanup(jeu.wait, 10)
        self.addCleanup(jeu.kill)
        self.attendre_le_jeu(jeu)
        return jeu

    def lire_pid(self, marque):
        for _fois in range(200):
            try:
                with open(marque, encoding="utf-8") as fh:
                    texte = fh.read().strip()
            except FileNotFoundError:
                texte = ""
            if texte:
                return int(texte)
            time.sleep(0.05)
        self.fail("the game never wrote its PID")

    def attendre_le_verrou_libre(self):
        for _fois in range(200):
            if self.deck_lock.holder(self.chemin) is None:
                return
            time.sleep(0.05)
        self.fail("the lock is still held")

    def test_holder_pids_names_the_whole_game(self):
        """La diagnostic nomme chaque processus qui tient le deck : le PID
        du verrou, l'enveloppe, peut être mort quand le jeu tourne encore."""
        marque = os.path.join(self.run_dir, "jeu.pid")
        jeu = self.envelopper(
            "sh", "-c", 'echo $$ > "$0"; exec sleep 30', marque
        )
        pid = self.lire_pid(marque)
        self.assertEqual(
            [jeu.pid, pid], self.deck_lock.holder_pids(self.chemin)
        )

    def test_a_signal_reaches_a_game_under_a_shell(self):
        """La galerie lance « bash -c '<boucle>' » : le jeu est un
        petit-enfant de l'enveloppe, et un shell non interactif meurt sur
        SIGTERM ou SIGINT sans le passer. L'enveloppe le passe à tous ses
        descendants et ne sort qu'après leur fin : le service relancé ensuite
        ne trouve plus le jeu sur le deck. « ; : » empêche sh de remplacer
        son processus par la commande, ce qui cacherait le petit-enfant."""
        for signum in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=signum.name):
                marque = os.path.join(self.run_dir, "%s.pid" % signum.name)
                jeu = self.envelopper(
                    "sh",
                    "-c",
                    'sh -c \'echo $$ > "$0"; exec sleep 30\' "$0"; :',
                    marque,
                )
                pid = self.lire_pid(marque)
                self.addCleanup(tuer, pid)
                jeu.send_signal(signum)
                self.assertEqual(128 + signum, jeu.wait(10))
                self.assertFalse(vivant(pid), "the game outlived its wrapper")
                self.assertIsNone(self.deck_lock.holder(self.chemin))

    def test_a_stopped_game_still_ends_on_sigterm(self):
        """Un processus arrêté (état T) garde SIGTERM en suspens : l'enveloppe
        lui envoie aussi SIGCONT, sans quoi elle attendrait sa fin pour
        toujours."""
        marque = os.path.join(self.run_dir, "jeu.pid")
        jeu = self.envelopper(
            "sh", "-c", 'echo $$ > "$0"; exec sleep 30', marque
        )
        pid = self.lire_pid(marque)
        self.addCleanup(tuer, pid)
        os.kill(pid, signal.SIGSTOP)
        for _fois in range(100):
            if self.deck_lock.process_table().get(pid, "....")[3] == "T":
                break
            time.sleep(0.05)
        else:
            self.fail("the game never stopped")
        jeu.send_signal(signal.SIGTERM)
        self.assertEqual(128 + signal.SIGTERM, jeu.wait(10))
        self.assertFalse(vivant(pid), "the game outlived its wrapper")

    def test_a_deck_program_that_lost_the_lock_takes_it_over(self):
        """Un programme du deck lancé par un subprocess python (close_fds) n'a
        pas hérité du verrou : il tourne sous celui du jeu, son ancêtre, et
        le reprend à son nom dès que le jeu le rend."""
        lancer = (
            "import subprocess, sys;"
            " p = subprocess.Popen(sys.argv[1:], stdout=subprocess.PIPE,"
            " stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,"
            " text=True);"
            " assert p.stdout.readline() == 'pret\\n'; print(p.pid)"
        )
        fini = self.lancer(
            "game",
            sys.executable,
            "-c",
            lancer,
            sys.executable,
            "-c",
            RESTER,
            str(DECK_DIR),
            "tiler",
            self.chemin,
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        programme = int(fini.stdout)
        self.addCleanup(tuer, programme)
        for _fois in range(200):
            if self.deck_lock.holder(self.chemin) == (str(programme), "tiler"):
                break
            time.sleep(0.05)
        else:
            self.fail(
                "the deck program never took the lock over: %s"
                % (self.deck_lock.holder(self.chemin),)
            )

    def test_a_deck_program_that_inherited_the_lock_holds_it(self):
        """Le verrou hérité suffit, même quand le PID que le verrou nomme
        n'est plus un ancêtre (l'enveloppe tuée) : le programme tourne, et
        le texte nomme encore le jeu."""
        os.makedirs(os.path.dirname(self.chemin), mode=0o700)
        tenu = open(self.chemin, "w", encoding="utf-8")
        self.addCleanup(tenu.close)
        tenu.write("4000000000 game\n")
        tenu.flush()
        fcntl.flock(tenu, fcntl.LOCK_EX | fcntl.LOCK_NB)
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
            pass_fds=(tenu.fileno(),),
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual("pret\n", fini.stdout)
        self.assertEqual(
            ("4000000000", "game"), self.deck_lock.holder(self.chemin)
        )

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


class LesCiblesDuSignal(unittest.TestCase):
    """signal_targets() sur une table écrite à la main : 10 est l'enveloppe,
    11 le shell de la galerie, 12 le jeu, 13 un zombie, 14 un processus d'un
    autre groupe, 20 un étranger. Le groupe 10 est au premier plan de son
    terminal, le groupe 14 non."""

    TABLE = {
        10: (1, 10, 10, "S"),
        11: (10, 10, 10, "S"),
        12: (11, 10, 10, "S"),
        13: (11, 10, 10, "Z"),
        14: (12, 14, 10, "S"),
        20: (1, 20, 20, "S"),
    }

    def test_sigterm_reaches_every_live_descendant(self):
        self.assertEqual(
            [11, 12, 14],
            charger().signal_targets(signal.SIGTERM, 10, self.TABLE),
        )

    def test_sigint_spares_the_terminal_foreground(self):
        """Un Ctrl-C a déjà frappé le groupe au premier plan : seul le
        processus d'un autre groupe le reçoit de l'enveloppe."""
        self.assertEqual(
            [14], charger().signal_targets(signal.SIGINT, 10, self.TABLE)
        )

    def test_without_a_terminal_sigint_reaches_everyone(self):
        table = {
            pid: (p, g, -1, e) for pid, (p, g, _t, e) in self.TABLE.items()
        }
        self.assertEqual(
            [11, 12, 14],
            charger().signal_targets(signal.SIGINT, 10, table),
        )

    def test_the_live_table_finds_this_process(self):
        table = charger().process_table()
        self.assertEqual(os.getppid(), table[os.getpid()][0])


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


def appel_du_verrou(instruction, attr="acquire_or_exit"):
    """« deck_lock.<attr>(…) » : rend le premier argument constant (None
    sans argument), ou False pour toute autre instruction."""
    if not isinstance(instruction, ast.Expr):
        return False
    appel = instruction.value
    if (
        isinstance(appel, ast.Call)
        and isinstance(appel.func, ast.Attribute)
        and isinstance(appel.func.value, ast.Name)
        and appel.func.value.id == "deck_lock"
        and appel.func.attr == attr
    ):
        if not appel.args:
            return None
        if isinstance(appel.args[0], ast.Constant):
            return appel.args[0].value
    return False


def principal(source):
    """Le bloc « if __name__ == "__main__": » du module."""
    return next(
        n
        for n in ast.parse(source).body
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.Compare)
        and isinstance(n.test.left, ast.Name)
        and n.test.left.id == "__name__"
    )


class LesProgrammesLePrennent(unittest.TestCase):
    """Le verrou se prend AVANT d'ouvrir le deck : le second programme sort
    sans avoir touché au périphérique du premier. SIGTERM se change ensuite
    en SystemExit, pour que le deck soit remis à zéro."""

    def test_the_tiler_takes_it_first_thing_in_main(self):
        source = (DECK_DIR / "game_tiler.py").read_text(encoding="utf-8")
        main = fonction(source, "main")
        self.assertEqual("tiler", appel_du_verrou(main.body[0]))
        self.assertIsNone(appel_du_verrou(main.body[1], "exit_on_sigterm"))
        self.assertIn("\nimport deck_lock\n", source)

    def test_the_tiler_exits_three_without_a_visual_deck(self):
        """L'unité ne relance pas un tiler qui ne trouve aucun deck à écran
        (un autre périphérique Elgato a passé ExecCondition)."""
        self.assertEqual(3, charger().NO_DECK_EXIT)
        source = (DECK_DIR / "game_tiler.py").read_text(encoding="utf-8")
        self.assertIn(
            'print("No visual Stream Deck found.")\n'
            "        sys.exit(deck_lock.NO_DECK_EXIT)",
            source,
        )

    def test_the_controller_takes_it_before_its_pidfile(self):
        source = (DECK_DIR / "erplibre_controller.py").read_text(
            encoding="utf-8"
        )
        bloc = principal(source)
        self.assertEqual("controller", appel_du_verrou(bloc.body[0]))
        self.assertIsNone(appel_du_verrou(bloc.body[1], "exit_on_sigterm"))
        self.assertIn("\nimport deck_lock\n", source)

    def test_the_controller_closes_its_decks_on_the_way_out(self):
        """Ses fils d'animation tournent tant que le deck est ouvert : sans
        cette fermeture, SystemExit attendrait leur fin pour toujours."""
        source = (DECK_DIR / "erplibre_controller.py").read_text(
            encoding="utf-8"
        )
        essai = next(
            n for n in principal(source).body if isinstance(n, ast.Try)
        )
        self.assertEqual(
            "sdc.close_decks()", ast.unparse(essai.finalbody[0]).strip()
        )
        self.assertIn("self.lst_deck.append(deck)", source)


if __name__ == "__main__":
    unittest.main()
