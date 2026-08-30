#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Capturer la sortie d'un test SANS que le test s'en aperçoive.

Le journal d'étape gardait la commande et son code, jamais ce que la
commande avait écrit. Mesuré sur une vraie migration : « $ …
smoke_public_url.py … » suivi IMMÉDIATEMENT de « -> 1 », zéro ligne entre
les deux, trois fois de suite. L'écran d'analyse ne pouvait donc rien
montrer de ce qui avait échoué.

Un tube aurait suffi à capturer, et aurait changé le programme :
`smoke_public_url` appelle `can_ask()`, qui exige stdin ET stdout sur un
terminal (smoke_public_url.py:63-72). Derrière un tube il cesse d'offrir
la réparation des vues COW — en silence, ce qui est le pire.

D'où le pseudo-terminal. Ce fichier vérifie les deux moitiés de la
promesse : que la sortie arrive dans le journal, et que l'enfant continue
de voir un vrai terminal.
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from script.todo.todo_upgrade import TodoUpgrade  # noqa: E402


class Pilote:
    """Le strict nécessaire : `run_captured` ne touche à rien d'autre.

    Instancier le vrai pilote demanderait une configuration, une base et
    un dépôt Odoo. La méthode, elle, n'a besoin que d'un journal ouvert et
    de deux listes — c'est ce qui la rend testable.
    """

    RE_ANSI = TodoUpgrade.RE_ANSI
    run_captured = TodoUpgrade.run_captured

    def __init__(self, handle):
        self.step_log = handle
        self.lst_command_executed = []
        self.dct_progression = {}
        self.notes = []

    def write_config(self):
        pass

    def note_step_log(self, texte):
        self.notes.append(texte)
        if self.step_log:
            self.step_log.write(texte + "\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier)
        self.chemin = os.path.join(self.dossier, "etape.log")

    def outil(self, source):
        chemin = os.path.join(self.dossier, "outil.py")
        with io.open(chemin, "w", encoding="utf-8") as handle:
            handle.write(source)
        return f"{sys.executable} {chemin}"

    def lancer(self, cmd, avec_journal=True):
        muet = os.open(os.devnull, os.O_WRONLY)
        garde = os.dup(1)
        os.dup2(muet, 1)
        try:
            return self._lancer(cmd, avec_journal)
        finally:
            os.dup2(garde, 1)
            os.close(garde)
            os.close(muet)

    def _lancer(self, cmd, avec_journal=True):
        tampon = io.StringIO()
        if not avec_journal:
            pilote = Pilote(None)
            with redirect_stdout(tampon):
                code = pilote.run_captured(cmd)
            return code, "", pilote
        with io.open(
            self.chemin, "w", encoding="utf-8", buffering=1
        ) as handle:
            pilote = Pilote(handle)
            with redirect_stdout(tampon):
                code = pilote.run_captured(cmd)
        with io.open(self.chemin, encoding="utf-8") as handle:
            return code, handle.read(), pilote


class TestTheChildStillSeesATerminal(Base):
    """La moitié qui n'a l'air de rien, et qui décide de tout."""

    def test_stdout_is_a_terminal_for_the_child(self):
        # Derrière un tube, `can_ask()` rend False et le test de fumée
        # cesse d'offrir la réparation, sans le dire.
        _code, journal, _p = self.lancer(
            self.outil(
                "import sys\nprint('T' if sys.stdout.isatty() else 'F')\n"
            )
        )
        self.assertIn("\nT\n", "\n" + journal)

    def test_stdin_is_a_terminal_for_the_child(self):
        _code, journal, _p = self.lancer(
            self.outil(
                "import sys\nprint('T' if sys.stdin.isatty() else 'F')\n"
            )
        )
        self.assertIn("\nT\n", "\n" + journal)

    def test_the_exit_code_survives(self):
        # C'est lui qui devient le verdict : 0 rien, 1 des trouvailles,
        # 2 l'outil a échoué. Le perdre viderait `record_event` de sens.
        code, _journal, _p = self.lancer(
            self.outil("import sys\nsys.exit(4)\n")
        )
        self.assertEqual(4, code)

    def test_a_zero_stays_a_zero(self):
        code, _journal, _p = self.lancer(self.outil("pass\n"))
        self.assertEqual(0, code)


class TestWhatTheLogKeeps(Base):
    def test_the_output_is_there(self):
        _code, journal, _p = self.lancer(
            self.outil("print('la ligne qui manquait')\n")
        )
        self.assertIn("la ligne qui manquait", journal)

    def test_the_command_and_its_code_frame_it(self):
        _code, journal, _p = self.lancer(self.outil("print('milieu')\n"))
        lignes = journal.splitlines()
        self.assertTrue(lignes[0].startswith("$ "))
        self.assertIn("milieu", journal)
        self.assertTrue(lignes[-1].strip().startswith("-> "))

    def test_colour_is_stripped_from_the_file(self):
        # L'enfant se croit — à juste titre — sur un terminal, donc il
        # colorie. Une seule séquence suffit à rendre l'extrait illisible.
        _code, journal, _p = self.lancer(
            self.outil("print('\\x1b[31mrouge\\x1b[0m nu')\n")
        )
        self.assertIn("rouge nu", journal)
        self.assertNotIn("\x1b", journal)

    def test_a_sequence_split_across_two_reads_leaves_no_debris(self):
        # On n'écrit qu'une fois la ligne complète : autrement les débris
        # d'une séquence coupée restent dans le fichier.
        source = (
            "import sys, time\n"
            "sys.stdout.write('\\x1b[3')\n"
            "sys.stdout.flush()\n"
            "time.sleep(0.2)\n"
            "sys.stdout.write('1mtardif\\x1b[0m\\n')\n"
            "sys.stdout.flush()\n"
        )
        _code, journal, _p = self.lancer(self.outil(source))
        self.assertIn("tardif", journal)
        self.assertNotIn("\x1b", journal)

    def test_secrets_go_through_the_same_filter_as_everything_else(self):
        _code, journal, _p = self.lancer(
            self.outil("print('outil --db_password TRESSECRET -d base')\n")
        )
        self.assertNotIn("TRESSECRET", journal)
        self.assertIn("--db_password", journal)

    def test_the_last_line_without_a_newline_is_not_lost(self):
        _code, journal, _p = self.lancer(
            self.outil(
                "import sys\nsys.stdout.write('sans saut final')\n"
                "sys.stdout.flush()\n"
            )
        )
        self.assertIn("sans saut final", journal)

    def test_carriage_returns_do_not_survive(self):
        # Un terminal en pose à chaque ligne ; dans un fichier ils
        # produisent des lignes qui s'écrasent à la lecture.
        _code, journal, _p = self.lancer(self.outil("print('normale')\n"))
        self.assertNotIn("\r", journal)


class TestWithoutAnOpenLog(Base):
    """Sans journal, rien à gagner et un pty à payer."""

    def test_the_command_still_runs_and_returns_its_code(self):
        code, _journal, _p = self.lancer(
            self.outil("import sys\nsys.exit(5)\n"), avec_journal=False
        )
        self.assertEqual(5, code)

    def test_no_terminal_is_fabricated_when_there_is_nothing_to_keep(self):
        """Sans journal, `run_captured` doit valoir `run_on_terminal`.

        Fabriquer un pseudo-terminal changerait ce que la commande voit —
        couleur, invites, mise en page — pour un journal qui n'existe pas.
        L'enfant écrit son verdict dans un fichier À CÔTÉ, car sa sortie
        standard est précisément ce qu'on est en train de mesurer.
        """
        temoin = os.path.join(self.dossier, "temoin.txt")
        cmd = self.outil(
            "import io, sys\n"
            f"io.open({temoin!r}, 'w').write(str(sys.stdout.isatty()))\n"
        )
        self.lancer(cmd, avec_journal=False)
        with io.open(temoin, encoding="utf-8") as handle:
            self.assertEqual("False", handle.read())

    def test_a_terminal_IS_fabricated_when_there_is_a_log(self):
        # Le pendant : c'est ce qui permet à l'outil de poser sa question.
        temoin = os.path.join(self.dossier, "temoin2.txt")
        cmd = self.outil(
            "import io, sys\n"
            f"io.open({temoin!r}, 'w').write(str(sys.stdout.isatty()))\n"
        )
        self.lancer(cmd, avec_journal=True)
        with io.open(temoin, encoding="utf-8") as handle:
            self.assertEqual("True", handle.read())

    def test_the_command_is_still_recorded(self):
        _code, _journal, pilote = self.lancer(
            self.outil("pass\n"), avec_journal=False
        )
        self.assertEqual(1, len(pilote.lst_command_executed))
        self.assertEqual(
            pilote.lst_command_executed,
            pilote.dct_progression["command_executed"],
        )


class TestTheDriverUsesIt(unittest.TestCase):
    """Le câblage : quels appels passent par la capture, et lesquels non."""

    def setUp(self):
        import inspect

        self.source = inspect.getsource(TodoUpgrade)

    def test_every_tool_verdict_goes_through_the_capture(self):
        import inspect

        run_tool = inspect.getsource(TodoUpgrade.run_tool)
        self.assertIn("run_captured", run_tool)
        self.assertNotIn("run_on_terminal", run_tool)

    def test_the_hidden_models_check_is_a_recorded_verdict(self):
        # Il suit la même convention de code de sortie que les autres et
        # tournait pourtant sans que rien ne retienne sa conclusion.
        avant = self.source.index("check_hidden_models.py")
        debut = self.source.rindex("self.run_", 0, avant)
        self.assertTrue(
            self.source[debut:avant].startswith("self.run_tool("),
            self.source[debut:avant][:60],
        )

    def test_only_full_screen_paths_stay_outside_the_capture(self):
        """La frontière, épinglée par ce qu'elle laisse dehors.

        Elle a une raison mesurée : `pty.spawn` crée son terminal en 0×0
        et l'enfant lit sa taille avant le premier octet. Sans effet sur
        un outil qui écrit des lignes ; fatal pour une application qui se
        dispose. Tout le reste doit donc être capturé.
        """
        import re

        lignes = self.source.split("\n")
        dehors = []
        for rang, ligne in enumerate(lignes):
            if "self.run_on_terminal(" not in ligne:
                continue
            suite = " ".join(x.strip() for x in lignes[rang : rang + 7])
            trouve = re.search(r"(\w+\.(?:py|sh))", suite)
            if trouve:
                dehors.append((trouve.group(1), "--tui" in suite))
        self.assertTrue(dehors, "plus aucun appel : la garde ne garde rien")
        for outil, tui in dehors:
            # Soit il demande explicitement un plein écran, soit son
            # invite peut en ouvrir un — check_stale_scss le fait sur « w ».
            self.assertTrue(
                tui or outil == "check_stale_scss.py",
                f"{outil} n'est pas un plein écran : il devrait être capturé",
            )

    def test_the_tools_captured_do_not_read_the_terminal_width(self):
        # C'est ce qui rend le 0×0 sans conséquence pour eux. Si l'un s'y
        # mettait, sa mise en page partirait sur une largeur nulle.
        import glob

        for chemin in glob.glob(
            os.path.join(REPO, "script", "odoo", "migration", "*.py")
        ):
            if os.path.basename(chemin) in (
                "check_stale_scss.py",
                "reset_stale_cow_views.py",
            ):
                continue
            with io.open(chemin, encoding="utf-8") as handle:
                source = handle.read()
            if "run_captured" in source:
                continue
            self.assertNotIn(
                "get_terminal_size", source, os.path.basename(chemin)
            )

    def test_the_full_screen_path_still_captures_nothing(self):
        # C'est sa raison d'être : un plein écran derrière un tube
        # renonce et retombe sur son rapport texte.
        import inspect

        import ast

        import textwrap

        arbre = ast.parse(
            textwrap.dedent(inspect.getsource(TodoUpgrade.run_on_terminal))
        )
        corps = arbre.body[0].body
        if isinstance(corps[0], ast.Expr) and isinstance(
            corps[0].value, ast.Constant
        ):
            corps = corps[1:]
        code = "\n".join(ast.unparse(noeud) for noeud in corps)
        self.assertIn("subprocess.call", code)
        self.assertNotIn("pty", code)

    def test_the_viewer_of_cow_copies_keeps_its_full_screen(self):
        avant = self.source.index("cow_drift.py")
        suite = self.source[avant : avant + 600]
        self.assertIn("self.run_on_terminal(cmd)", suite)


if __name__ == "__main__":
    unittest.main()
