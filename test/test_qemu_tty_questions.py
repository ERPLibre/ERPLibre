#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les questions oui/non de deploy_qemu et de network_qemu, sur un vrai
terminal.

Chaque question tourne dans un processus enfant dont un pty neuf est le
terminal de contrôle : /dev/tty y désigne ce pty. L'entrée standard est
/dev/null, quand l'entrée standard du script est redirigée, ou le pty
lui-même, quand un parent relaie la sortie du script par un tube comme
`exec_command_live` sous le menu TODO. Le test lit la question sur le
maître du pty, puis y tape la réponse. Rien d'autre ne tourne : seul le
module est chargé.
"""

import os
import select
import subprocess
import sys
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# Dans l'enfant, chef d'une session neuve : le pty, reçu au descripteur
# argv[3], devient son terminal de contrôle, et ce descripteur reste ouvert
# jusqu'à sa sortie (sans lui, le maître lirait EIO avant la question) ;
# puis `m`, le module de script/qemu nommé argv[1], évalue l'appel argv[2],
# dont le résultat s'imprime.
CHILD = r"""
import fcntl, importlib.util, sys, termios
fcntl.ioctl(int(sys.argv[3]), termios.TIOCSCTTY, 0)
name, call = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location(name, f"script/qemu/{name}.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(repr(eval(call, {"m": module})))
"""
# Le relais d'`exec_command_live`, en petit : chef d'une session neuve dont
# le pty, son entrée standard, est le terminal de contrôle, il lance le
# script argv[1], qui hérite de cette entrée, sa sortie dans un tube, et
# recopie ce tube sur le pty.
RELAY = r"""
import fcntl, os, subprocess, sys, termios
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
child = subprocess.Popen(
    [sys.executable, "-c", sys.argv[1]],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
while data := os.read(child.stdout.fileno(), 4096):
    os.write(1, data)
sys.exit(child.wait())
"""
# Le script relayé : deux lignes, puis la question de deploy_qemu, puis ce
# qu'elle rend.
LINES = r"""
import importlib.util
path = "script/qemu/deploy_qemu.py"
spec = importlib.util.spec_from_file_location("deploy_qemu", path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print("Forged manager: forged")
print("Forged command: forged install")
print(repr(m.prompt_yes_no("Forged install?", default=False)))
"""
# Secondes au plus pour qu'une question paraisse et que l'enfant finisse.
LIMIT = 20.0


def converse(master, child, answer, question) -> str:
    """Lit le maître du pty jusqu'à la fin de `child` ; `answer` et Entrée
    y sont tapés dès que `question` y paraît. Rend ce que le pty a montré,
    écho de la réponse compris."""
    shown, typed = b"", False
    deadline = time.monotonic() + LIMIT
    while time.monotonic() < deadline:
        ready, _, _ = select.select([master], [], [], 0.1)
        if not ready:
            if child.poll() is not None:
                break
            continue
        try:
            chunk = os.read(master, 4096)
        except OSError:  # EIO : l'enfant a fermé le pty en sortant
            break
        shown += chunk
        if not typed and question.encode() in shown:
            os.write(master, answer.encode() + b"\n")
            typed = True
    return shown.decode(errors="replace")


def ask(module, call, answer, question):
    """`call`, `m` étant le module `module`, dans un enfant dont un pty est
    le terminal de contrôle et dont l'entrée standard est /dev/null ;
    `answer` et Entrée sont tapés sur le pty dès que `question` y paraît.
    Rend ce que l'enfant imprime et ce que le pty a montré."""
    master, slave = os.openpty()
    try:
        child = subprocess.Popen(
            [sys.executable, "-c", CHILD, module, call, str(slave)],
            cwd=REPO,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(slave,),
            start_new_session=True,
        )
    finally:
        os.close(slave)
    try:
        shown = converse(master, child, answer, question)
        out, err = child.communicate(timeout=LIMIT)
    finally:
        os.close(master)
        if child.poll() is None:
            child.kill()
            child.wait()
    if child.returncode:
        raise AssertionError(err.decode(errors="replace"))
    return out.decode(), shown


def relayed(answer, question) -> str:
    """LINES sous RELAY, le pty pour entrée et sortie du relais ; `answer`
    et Entrée sont tapés dès que `question` paraît. Rend ce que le pty a
    montré : les lignes relayées, la question, l'écho, le résultat."""
    master, slave = os.openpty()
    try:
        child = subprocess.Popen(
            [sys.executable, "-c", RELAY, LINES],
            cwd=REPO,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
        )
    finally:
        os.close(slave)
    try:
        shown = converse(master, child, answer, question)
        child.wait(timeout=LIMIT)
    finally:
        os.close(master)
        if child.poll() is None:
            child.kill()
            child.wait()
    if child.returncode:
        raise AssertionError(shown)
    return shown


class TestYesNoOnTheTerminal(unittest.TestCase):
    def test_deploy_qemu_asks_and_reads_on_the_terminal(self):
        out, shown = ask(
            "deploy_qemu",
            "m.prompt_yes_no('Forged question?', default=False)",
            "o",
            "Forged question? [o/N] ",
        )
        self.assertIn("Forged question? [o/N] ", shown)
        self.assertEqual(out.strip(), "True")

    def test_utf8_both_ways_and_an_empty_line_keeps_the_default(self):
        out, shown = ask(
            "deploy_qemu",
            "m.prompt_yes_no('Déployer « forgé » ?', default=True)",
            "",
            "« forgé » ? [O/n] ",
        )
        self.assertIn("Déployer « forgé » ? [O/n] ", shown)
        self.assertEqual(out.strip(), "True")
        out, shown = ask(
            "deploy_qemu", "m.read_tty_line('Nom ? ')", "forgé", "Nom ? "
        )
        self.assertEqual(out.strip(), repr("forgé"))

    def test_network_qemu_asks_and_reads_on_the_terminal(self):
        out, shown = ask(
            "network_qemu",
            "m.demander('Recreate the forged network? [o/N] ')",
            "oui",
            "forged network? [o/N] ",
        )
        self.assertIn("Recreate the forged network? [o/N] ", shown)
        self.assertEqual(out.strip(), "True")

    def test_under_a_relay_the_question_follows_its_lines(self):
        # L'entrée standard est le clavier, la sortie un tube que le parent
        # relaie : la question passe par ce tube, après les lignes qui la
        # précèdent, et non directement sur le terminal, devant elles.
        shown = relayed("n", "[o/N] ")
        self.assertLess(
            shown.index("Forged command"), shown.index("[o/N]"), shown
        )
        self.assertIn("False", shown[shown.index("[o/N]") :])

    def test_without_a_terminal_standard_input_answers(self):
        # Sans terminal de contrôle, `input` lit l'entrée standard.
        code = (
            "import importlib.util\n"
            "spec = importlib.util.spec_from_file_location("
            "'deploy_qemu', 'script/qemu/deploy_qemu.py')\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "print('', m.prompt_yes_no('Forged question?', default=False))\n"
        )
        done = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO,
            input="o\n",
            capture_output=True,
            text=True,
            timeout=LIMIT,
            start_new_session=True,
            check=True,
        )
        self.assertEqual(done.stdout, "Forged question? [o/N]  True\n")


if __name__ == "__main__":
    unittest.main()
