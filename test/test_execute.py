#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import glob
import os
import pty
import select
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from script.execute.execute import (
    Execute,
    redact_for_storage,
    redact_secrets,
)

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


class TestExecuteInit(unittest.TestCase):
    """Test Execute class initialization."""

    @patch("shutil.which")
    def test_init_with_gnome_terminal(self, mock_which):
        mock_which.side_effect = lambda x: (
            "/usr/bin/gnome-terminal" if x == "gnome-terminal" else None
        )
        exe = Execute()
        self.assertIn("gnome-terminal", exe.cmd_source_erplibre)
        self.assertIn(".venv.erplibre", exe.cmd_source_erplibre)
        self.assertIn("gnome-terminal", exe.cmd_source_default)

    @patch("shutil.which")
    def test_init_with_osascript(self, mock_which):
        mock_which.side_effect = lambda x: (
            "/usr/bin/osascript" if x == "osascript" else None
        )
        exe = Execute()
        self.assertIn("osascript", exe.cmd_source_erplibre)

    @patch("shutil.which", return_value=None)
    def test_init_fallback_source(self, mock_which):
        exe = Execute()
        self.assertIn(".venv.erplibre/bin/activate", exe.cmd_source_erplibre)
        self.assertEqual(exe.cmd_source_default, "")


class TestExecCommandLive(unittest.TestCase):
    """Test exec_command_live method."""

    def setUp(self):
        with patch("shutil.which", return_value=None):
            self.exe = Execute()

    def test_simple_command_returns_zero(self):
        result = self.exe.exec_command_live(
            "echo hello",
            source_erplibre=False,
            quiet=True,
        )
        self.assertEqual(result, 0)

    def test_failing_command_returns_nonzero(self):
        result = self.exe.exec_command_live(
            "exit 42",
            source_erplibre=False,
            quiet=True,
        )
        self.assertEqual(result, 42)

    def test_return_status_and_output(self):
        status, output = self.exe.exec_command_live(
            "echo hello",
            source_erplibre=False,
            quiet=True,
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, ["hello"])

    def test_events_announce_each_command_redacted(self):
        self.assertIsNone(Execute.events)
        events = []
        self.exe.events = events.append
        rc = self.exe.exec_command_live(
            "MY_PASSWORD=hunter2 true; exit 3",
            source_erplibre=False,
            quiet=True,
        )
        self.assertEqual(rc, 3)
        start, end = events
        self.assertEqual(
            start, {"t": "run_start", "cmd": "MY_PASSWORD='***' true; exit 3"}
        )
        self.assertEqual((end["t"], end["rc"]), ("run_end", 3))
        self.assertIsInstance(end["secs"], float)

    def test_a_broken_event_hook_never_breaks_the_command(self):
        def hook(message):
            raise RuntimeError("forged failure")

        self.exe.events = hook
        rc = self.exe.exec_command_live(
            "exit 4", source_erplibre=False, quiet=True
        )
        self.assertEqual(rc, 4)

    def test_an_interrupted_command_still_ends(self):
        events = []
        self.exe.events = events.append
        with patch("subprocess.Popen", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.exe.exec_command_live(
                    "true", source_erplibre=False, quiet=True
                )
        self.assertEqual([e["t"] for e in events], ["run_start", "run_end"])
        self.assertIsNone(events[1]["rc"])

    def test_a_terminal_that_fails_still_ends_the_command(self):
        events = []
        self.exe.events = events.append
        with patch.object(Execute, "_job_control_tty", side_effect=OSError):
            rc = self.exe.exec_command_live(
                "true", source_erplibre=False, quiet=True
            )
        self.assertEqual(rc, 1)
        self.assertEqual([e["t"] for e in events], ["run_start", "run_end"])

    def test_an_interrupt_while_announcing_opens_no_terminal(self):
        def hook(message):
            raise KeyboardInterrupt

        self.exe.events = hook
        with patch.object(Execute, "_job_control_tty") as tty:
            with self.assertRaises(KeyboardInterrupt):
                self.exe.exec_command_live(
                    "true", source_erplibre=False, quiet=True
                )
        tty.assert_not_called()

    def test_return_status_and_output_multiline(self):
        status, output = self.exe.exec_command_live(
            "echo -e 'line1\nline2\nline3'",
            source_erplibre=False,
            quiet=True,
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, ["line1", "line2", "line3"])

    def test_return_status_and_command(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=False,
            quiet=True,
            return_status_and_command=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(cmd, "echo test")

    def test_return_status_and_output_and_command(self):
        status, cmd, output = self.exe.exec_command_live(
            "echo result",
            source_erplibre=False,
            quiet=True,
            return_status_and_output_and_command=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(cmd, "echo result")
        self.assertEqual(output, ["result"])

    def test_source_erplibre_prepends_activate(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=True,
            quiet=True,
            return_status_and_command=True,
        )
        self.assertIn(".venv.erplibre/bin/activate", cmd)

    def test_single_source_erplibre(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=False,
            single_source_erplibre=True,
            quiet=True,
            return_status_and_command=True,
        )
        self.assertIn(".venv.erplibre/bin/activate", cmd)
        self.assertIn("echo test", cmd)

    def test_single_source_odoo_no_version_returns_error(self):
        with patch("os.path.exists", return_value=False):
            result = self.exe.exec_command_live(
                "echo test",
                source_erplibre=False,
                single_source_odoo=True,
                source_odoo="",
                quiet=True,
            )
        # `1`, pas `-1` : e24b185 a rendu à ce chemin la FORME que
        # l'appelant demande (un tuple s'il en attend un) et en a profité
        # pour donner un vrai code de sortie. Aucun appelant ne compare à
        # -1, qui n'est d'ailleurs pas un code de sortie valide.
        self.assertEqual(result, 1)

    def test_single_source_odoo_with_version(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=False,
            single_source_odoo=True,
            source_odoo="odoo18",
            quiet=True,
            return_status_and_command=True,
        )
        self.assertIn(".venv.odoo18/bin/activate", cmd)

    def test_new_env_passed_to_subprocess(self):
        status, output = self.exe.exec_command_live(
            "echo $MY_TEST_VAR",
            source_erplibre=False,
            quiet=True,
            new_env={"MY_TEST_VAR": "test_value_123"},
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, ["test_value_123"])

    def test_empty_output_command(self):
        status, output = self.exe.exec_command_live(
            "true",
            source_erplibre=False,
            quiet=True,
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, [])


# Tient le rôle du worker d'une session web : rétablit SIGINT (un SIGINT
# ignoré s'hérite, d'un lanceur en arrière-plan), prend le PTY comme terminal
# de contrôle, lance une commande avec le contrôle de tâches, puis dit son
# code, si le terminal lui est revenu, et qu'il vit encore.
JOB_CHILD = r"""
import fcntl, os, signal, termios
signal.signal(signal.SIGINT, signal.default_int_handler)
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
from script.execute.execute import Execute
exe = Execute()
exe.job_control = True
rc = exe.exec_command_live('read -r x; echo "got $x"; sleep 30', False)
back = os.tcgetpgrp(0) == os.getpgrp()
print(f"rc={rc} back={back}", flush=True)
print("alive", flush=True)
"""


def _descendant_stopped(pid, timeout=0.3):
    """Vrai si un descendant de `pid` (via /proc) atteint l'état arrêté (T)
    avant le délai ; balaie l'arbre des enfants à chaque tour, un stade
    stoppé n'apparaissant que sous son parent direct."""

    def any_stopped(root):
        for children_path in glob.glob(f"/proc/{root}/task/*/children"):
            try:
                with open(children_path) as f:
                    kids = f.read().split()
            except OSError:
                continue
            for kid in kids:
                try:
                    with open(f"/proc/{kid}/status") as f:
                        status = f.read()
                except OSError:
                    continue
                if "State:\tT" in status or any_stopped(kid):
                    return True
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any_stopped(pid):
            return True
        time.sleep(0.01)
    return False


def _read_until(fd, marker, timeout=10.0):
    """Octets lus sur `fd` jusqu'à `marker` compris ; échec au délai."""
    out = b""
    deadline = time.monotonic() + timeout
    while marker not in out:
        left = deadline - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            raise AssertionError(f"{marker!r} not seen in {out!r}")
        try:
            out += os.read(fd, 65536)
        except OSError:  # EIO : plus personne au bout de l'esclave
            raise AssertionError(f"{marker!r} not seen in {out!r}")
    return out


class TestJobControl(unittest.TestCase):
    def test_off_by_default_the_command_shares_the_caller_group(self):
        with patch("shutil.which", return_value=None):
            exe = Execute()
        self.assertIs(exe.job_control, False)
        with (
            patch("subprocess.Popen", wraps=subprocess.Popen) as popen,
            patch("os.tcsetpgrp") as tcsetpgrp,
        ):
            rc = exe.exec_command_live("true", False, quiet=True)
        self.assertEqual(rc, 0)
        self.assertNotIn("process_group", popen.call_args.kwargs)
        tcsetpgrp.assert_not_called()

    def test_without_a_controlling_terminal_it_runs_as_in_the_cli(self):
        with patch("shutil.which", return_value=None):
            exe = Execute()
        exe.job_control = True
        with (
            patch("os.open", side_effect=OSError("no terminal")),
            patch("subprocess.Popen", wraps=subprocess.Popen) as popen,
        ):
            rc = exe.exec_command_live("true", False, quiet=True)
        self.assertEqual(rc, 0)
        self.assertNotIn("process_group", popen.call_args.kwargs)

    def test_outside_the_main_thread_it_runs_as_in_the_cli(self):
        with patch("shutil.which", return_value=None):
            exe = Execute()
        exe.job_control = True
        ttys = []
        with patch("os.open") as open_:
            thread = threading.Thread(
                target=lambda: ttys.append(exe._job_control_tty())
            )
            thread.start()
            thread.join()
        self.assertEqual(ttys, [None])
        open_.assert_not_called()

    def test_a_foreground_refused_leaves_no_command_behind(self):
        with patch("shutil.which", return_value=None):
            exe = Execute()
        exe.job_control = True
        tty = os.open(os.devnull, os.O_RDWR)
        started, real = [], subprocess.Popen

        def popen(*args, **kwargs):
            started.append(real(*args, **kwargs))
            return started[-1]

        with (
            patch.object(Execute, "_job_control_tty", return_value=tty),
            patch(
                "script.execute.execute._set_foreground",
                side_effect=OSError(5, "EIO"),
            ),
            patch("subprocess.Popen", side_effect=popen),
            patch("os.close", wraps=os.close) as close,
        ):
            rc = exe.exec_command_live("sleep 30", False, quiet=True)
        started[0].stdout.close()
        # Tuée et attendue ; le descripteur se ferme malgré l'échec.
        self.assertEqual((rc, started[0].returncode), (1, -signal.SIGKILL))
        close.assert_any_call(tty)

    def test_ctrl_c_stops_the_command_and_not_its_caller(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        child = subprocess.Popen(
            [sys.executable, "-c", JOB_CHILD],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=REPO,
            start_new_session=True,
        )
        os.close(slave)
        # Sur un échec, les nettoyages tournent en ordre inverse, child.kill
        # d'abord : la mort du chef de session envoie SIGHUP au groupe au
        # premier plan de son terminal, la commande qui y est restée.
        self.addCleanup(child.wait, 10)
        self.addCleanup(child.kill)
        _read_until(master, b"Execute command")
        # La commande lit le terminal : elle y est au premier plan.
        os.write(master, b"yes\n")
        out = _read_until(master, b"got yes")
        os.write(master, b"\x03")
        out += _read_until(master, b"alive")
        self.assertIn(b"rc=-2 back=True", out)
        self.assertEqual(child.wait(10), 0)

    def test_ctrl_z_does_not_suspend_and_ctrl_c_still_stops_it(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        child = subprocess.Popen(
            [sys.executable, "-c", JOB_CHILD],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=REPO,
            start_new_session=True,
        )
        os.close(slave)
        self.addCleanup(child.wait, 10)
        self.addCleanup(child.kill)
        _read_until(master, b"Execute command")
        os.write(master, b"yes\n")
        out = _read_until(master, b"got yes")
        # VSUSP désactivé : Ctrl+Z ne met pas la commande en état arrêté (T),
        # où elle resterait faute d'un shell pour la reprendre. On laisse le
        # temps à un état T de s'installer avant Ctrl+C : sans le délai, les
        # deux octets sont traités avant qu'un SIGTSTP délivré n'ait figé le
        # groupe, et le test réussirait même sans le correctif.
        os.write(master, b"\x1a")
        self.assertFalse(_descendant_stopped(child.pid))
        os.write(master, b"\x03")
        out += _read_until(master, b"alive")
        self.assertIn(b"rc=-2 back=True", out)
        self.assertEqual(child.wait(10), 0)


class TestRedactSecrets(unittest.TestCase):
    """Ce qui doit disparaître d'une commande affichée, et ce qui doit rester.

    Le caviardage est le DERNIER rempart et non le premier : un secret sur
    argv est déjà lisible par tout compte de la machine dans
    /proc/<pid>/cmdline, où aucun filtre n'atteint. Ces tests défendent donc
    la trace — terminal, journal, sortie CI — et rien d'autre.

    Trois familles portent un secret, et elles ne se ressemblent pas. Une
    option se reconnaît par son nom, une variable d'environnement par le
    sien, et un jeton d'en-tête n'a NI l'un NI l'autre : il suit le mot
    « Bearer ». Un filtre bâti sur les deux premières laisse passer la
    troisième, qui est exactement celle qu'une API de modèle emploie.

    Les valeurs sont inventées, comme l'exige la règle du dépôt pour tout
    exemple qui illustre un interdit.
    """

    def test_env_api_key_is_redacted(self):
        sortie = redact_secrets("OPENAI_API_KEY=sk-inventeXYZ python x.py")
        self.assertNotIn("sk-inventeXYZ", sortie)
        self.assertIn("OPENAI_API_KEY='***'", sortie)

    def test_env_apikey_without_separator(self):
        sortie = redact_secrets("MISTRAL_APIKEY=abc123 ./run")
        self.assertNotIn("abc123", sortie)

    def test_bearer_header_is_redacted(self):
        sortie = redact_secrets(
            "curl -H 'Authorization: Bearer sk-inventeABC' http://h/v1/models"
        )
        self.assertNotIn("sk-inventeABC", sortie)
        self.assertIn("Authorization: Bearer '***'", sortie)

    def test_basic_header_is_redacted(self):
        sortie = redact_secrets("Authorization: Basic dXNlcjpmYXV4")
        self.assertNotIn("dXNlcjpmYXV4", sortie)

    def test_header_case_is_ignored(self):
        sortie = redact_secrets("authorization: bearer sk-inventeDEF")
        self.assertNotIn("sk-inventeDEF", sortie)

    def test_option_password_still_redacted(self):
        sortie = redact_secrets("odoo --db_password 'inventeGHI'")
        self.assertNotIn("inventeGHI", sortie)

    def test_option_name_survives(self):
        """Le nom de l'option reste : la commande doit rester reproductible."""
        sortie = redact_secrets("odoo --db_password 'inventeJKL'")
        self.assertIn("--db_password", sortie)

    def test_a_pwd_variable_is_redacted_not_the_directory(self):
        sortie = redact_secrets("MASTER_PWD=inventeMNO PWD=/tmp OLDPWD=/srv")
        self.assertEqual(sortie, "MASTER_PWD='***' PWD=/tmp OLDPWD=/srv")

    def test_a_long_word_or_run_of_dashes_is_fast(self):
        """Une option ne commence ni après un caractère de mot ni après un
        tiret, et ne se lit, comme une variable, que suivie d'un blanc ou
        d'un « = » : une ligne de séparateurs, de mots liés par des tirets
        ou d'un mot qui se répète coûte un temps proportionnel à sa
        longueur, jamais à son carré."""
        for ligne in (
            "-" * 16384 + " token",
            "a-" * 8192 + " token",
            "--" + "token" * 3277,
            "PASSWORD" * 8192,
        ):
            with self.subTest(debut=ligne[:4]):
                debut = time.monotonic()
                redact_secrets(ligne)
                self.assertLess(time.monotonic() - debut, 0.5)

    def test_a_path_is_not_a_secret(self):
        """Rien ne disparaît d'une commande qui ne porte aucun secret."""
        commande = "make test_unit_file F=test/test_execute.py"
        self.assertEqual(redact_secrets(commande), commande)

    def test_empty_text_survives(self):
        self.assertEqual(redact_secrets(""), "")
        self.assertIsNone(redact_secrets(None))


class TestRedactUrlCredentials(unittest.TestCase):
    """Identifiants portés par une URL (userinfo, RFC 3986 §3.2.1).

    Ni nom d'option ni nom de variable : le secret suit « user: » ou tient
    lieu de nom d'utilisateur. Schéma, hôte, chemin et nom d'utilisateur
    ordinaire restent, pour que la commande reste lisible. Valeurs inventées.
    """

    def test_password_in_userinfo_is_masked(self):
        sortie = redact_secrets(
            "psql postgresql://odoo:inventeMNO@db.example/base"
        )
        self.assertNotIn("inventeMNO", sortie)
        self.assertIn("postgresql://odoo:***@db.example/base", sortie)

    def test_token_as_password_is_masked(self):
        sortie = redact_secrets(
            "git clone https://x-access-token:inventePQR@forge.example/o/r.git"
        )
        self.assertNotIn("inventePQR", sortie)
        self.assertIn("https://x-access-token:***@forge.example", sortie)

    def test_prefixed_token_as_user_is_masked(self):
        sortie = redact_secrets(
            "git clone https://ghp_inventeSTU@forge.example/o/r.git"
        )
        self.assertNotIn("ghp_inventeSTU", sortie)
        self.assertIn("https://***@forge.example/o/r.git", sortie)

    def test_long_opaque_user_is_masked(self):
        jeton = "invente" + "x" * 30
        sortie = redact_secrets(f"curl https://{jeton}@forge.example/api")
        self.assertNotIn(jeton, sortie)

    def test_token_followed_by_a_password_is_masked(self):
        """Forme GitHub : le jeton tient lieu de nom d'utilisateur ET porte
        un mot de passe (« x-oauth-basic »). La règle du mot de passe masque
        d'abord ce second segment ; celle du jeton doit encore reconnaître
        l'@ à travers le « :*** » qui reste, sans quoi le jeton passe seul en
        clair."""
        jeton = "invente" + "T" * 33
        sortie = redact_secrets(
            f"git clone https://{jeton}:x-oauth-basic@forge.example/o/r.git"
        )
        self.assertNotIn(jeton, sortie)
        self.assertNotIn("x-oauth-basic", sortie)
        self.assertIn("https://***:***@forge.example/o/r.git", sortie)

    def test_password_with_unencoded_at_sign_is_masked_in_full(self):
        """Un « @ » non encodé dans le mot de passe (RFC 3986 l'interdit,
        ça arrive) ne doit pas fuir sa moitié : le masquage s'étend, glouton,
        jusqu'au DERNIER @ avant l'hôte."""
        sortie = redact_secrets(
            "psql postgresql://odoo:inventeP@ss@db.example/base"
        )
        self.assertNotIn("inventeP@ss", sortie)
        self.assertIn("postgresql://odoo:***@db.example/base", sortie)

    def test_a_password_with_a_stop_character_stays_masked(self):
        """Sans « @ » avant « ? », « # », une virgule ou un guillemet, le
        masque va jusqu'au dernier « @ » : un mot de passe qui porte l'un
        d'eux reste caché en entier."""
        for mot in ("ab,cd", "it's", "pa?ss", "pa#ss", 'q"x'):
            ligne = f"git clone https://u:{mot}@forge.example/r.git"
            with self.subTest(mot=mot):
                self.assertEqual(
                    redact_secrets(ligne),
                    "git clone https://u:***@forge.example/r.git",
                )

    def test_the_mask_stops_before_a_query_a_comma_or_a_quote(self):
        """Un « @ » plus loin sur la ligne, après « ? », « # », une virgule
        ou un guillemet, n'appartient pas à l'userinfo : le masque s'arrête
        avant, et l'hôte affiché reste le vrai."""
        for suite in (
            "?next=forged@example",
            "#forged@example",
            ",odoo@db2.example/base",
            '",mail="forged@example',
            "',forged@example",
        ):
            ligne = f"psql postgresql://odoo:inventeYZ@db.example{suite}"
            with self.subTest(suite=suite):
                sortie = redact_secrets(ligne)
                self.assertNotIn("inventeYZ", sortie)
                self.assertEqual(
                    sortie, f"psql postgresql://odoo:***@db.example{suite}"
                )

    def test_ordinary_user_survives(self):
        for commande in (
            "git clone ssh://git@forge.example/o/r.git",
            "curl https://alice@forge.example/x",
        ):
            self.assertEqual(redact_secrets(commande), commande)

    def test_port_and_path_colon_survive(self):
        for commande in (
            "curl http://localhost:8069/web/login",
            "curl https://forge.example/a:b@c",
        ):
            self.assertEqual(redact_secrets(commande), commande)

    def test_url_in_the_middle_of_a_printed_line_is_masked(self):
        ligne = "Cloning from https://u:inventeVWX@forge.example/o/r.git\n"
        self.assertNotIn("inventeVWX", redact_secrets(ligne))

    def test_long_line_without_a_scheme_is_fast(self):
        """Le schéma des deux motifs est borné (32 caractères) : sur une
        ligne sans « :// », chaque position n'essaie qu'un préfixe
        `[a-z0-9+.-]` de 32 caractères au plus avant d'abandonner, et le
        temps reste proportionnel à la longueur, jamais à son carré."""
        ligne = "a." * 10000
        debut = time.monotonic()
        redact_secrets(ligne)
        self.assertLess(time.monotonic() - debut, 1.0)


class TestRedactForStorage(unittest.TestCase):
    """Ce qu'une ligne de sortie devient avant d'être gardée sur disque :
    `redact_secrets`, puis le reste d'une ligne qui imprime un mot de passe
    après son mot. Valeurs inventées."""

    def test_a_printed_password_is_masked_after_its_word(self):
        for ligne, attendu in (
            ("Password: inventeAB", "Password: ***"),
            ("admin password=inventeCD", "admin password=***"),
            ("passwd inventeEF", "passwd ***"),
            ("Mot de passe : inventeGH", "Mot de passe : ***"),
            ("PASSWORD:inventeIJ et la suite", "PASSWORD:***"),
            ("a\nPassword: inventeKL\nb", "a\nPassword: ***\nb"),
            # Une clé de configuration ou de JSON, et l'espace insécable
            # de la typographie française.
            ("admin_passwd = inventeMN", "admin_passwd = ***"),
            ("db_password = inventeOP", "db_password = ***"),
            ("POSTGRES_PASSWORD: inventeQR", "POSTGRES_PASSWORD: ***"),
            ('{"password": "inventeST"}', '{"password": ***'),
            ("{'password': 'inventeUV'}", "{'password': ***"),
            ("Mot de passe : inventeWX", "Mot de passe : ***"),
        ):
            with self.subTest(ligne=ligne):
                self.assertEqual(redact_for_storage(ligne), attendu)

    def test_each_mask_passes_the_fast_path(self):
        """Une ligne sans mot de `_TRIGGERS` n'essaie aucun motif : chaque
        forme qu'un motif masque en porte donc un, casse comprise (« ſ »
        égale « s » sans casse)."""
        for ligne in (
            "mysql --password inventeAB",
            "PGPASSWORD=inventeCD psql",
            "MASTER_PWD=inventeEF odoo",
            "Authorization: Bearer inventeGH",
            "git clone https://u:inventeIJ@forge.example/r",
            "git clone https://ghp_inventeKL@forge.example/r",
            "Password: inventeMN",
            "Paſſword: inventeOP",
        ):
            with self.subTest(ligne=ligne):
                self.assertNotIn("invente", redact_for_storage(ligne))

    def test_redact_secrets_comes_first(self):
        ligne = "Cloning https://u:inventeMN@forge.example/o/r.git"
        self.assertEqual(
            redact_for_storage(ligne),
            "Cloning https://u:***@forge.example/o/r.git",
        )

    def test_a_prompt_and_other_words_survive(self):
        for ligne in (
            "Password: ",
            "[sudo] password:",
            "Passwords rotate daily",
            "passwordless login",
            "make test_unit",
            "",
        ):
            with self.subTest(ligne=ligne):
                self.assertEqual(redact_for_storage(ligne), ligne)
        self.assertIsNone(redact_for_storage(None))


if __name__ == "__main__":
    unittest.main()
