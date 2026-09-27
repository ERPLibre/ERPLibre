#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La télémétrie dans le navigateur depuis TODO : ouvrir la page par le hub
web de ce checkout, dire pourquoi il n'a pas démarré, l'arrêter.

Le lanceur est simulé, sauf dans TestWithARealHub, qui démarre un vrai hub.
HOME, et XDG_RUNTIME_DIR pour le vrai hub, pointent vers un répertoire
temporaire. La langue est fixée par test (`use_lang`, sans écrire
env_var.sh) et la télémétrie de navigation, que chaque menu enregistre, est
neutralisée.
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import click

from script.todo import todo_i18n
from script.todo.todo import TODO, VENV_ERPLIBRE, new_path
from script.todo.web import launcher, paths

URL = "http://127.0.0.1:43817/"
LINK = URL + "#login=forged&view=telemetry&lang=en"
RUNNING = {"pid": 1, "port": 43817, "sessions": 2, "running": 0}


def _short_tmp() -> str:
    """Base des répertoires temporaires : celle du système si elle tient en
    40 octets, /tmp sinon. Le chemin de ctl.sock y ajoute 56 octets, et
    AF_UNIX n'en accepte que 103 à 107."""
    base = tempfile.gettempdir()
    return base if len(os.fsencode(base)) <= 40 else "/tmp"


def _page(opened=True, headless=False):
    return launcher.OpenResult(URL, LINK, opened, headless)


class MenuCase(unittest.TestCase):
    def setUp(self):
        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("en")
        tmp = tempfile.TemporaryDirectory(dir=_short_tmp())
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        for patcher in (
            patch.dict(os.environ, {"HOME": os.path.join(tmp.name, "home")}),
            patch("script.todo.todo_telemetry.record"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.mkdir(os.environ["HOME"])
        self.todo = TODO()

    def printed(self, method):
        """Lignes qu'affiche `method()` ; elle ne doit rien rendre."""
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertIsNone(method())
        return out.getvalue().splitlines()


class TestTelemetryWeb(MenuCase):
    def web(self, **mock):
        with patch.object(launcher, "open_page", **mock) as open_page:
            lines = self.printed(self.todo._todo_telemetry_web)
        open_page.assert_called_once_with(
            new_path, view="telemetry", lang=todo_i18n.get_lang()
        )
        return lines

    def failure(self, *args, **kwargs):
        error = launcher.LaunchError(*args, **kwargs)
        return self.web(side_effect=error)

    def test_a_browser_that_opened_the_page(self):
        self.assertEqual(
            self.web(return_value=_page()),
            [
                f"✅ Web interface ready — {URL}",
                "   Opened in your browser. The link works once, for 2"
                " minutes.",
                "   If the page did not open, use this link within 2 minutes:",
                f"   {LINK}",
            ],
        )

    def test_a_browser_that_did_not_open_the_page(self):
        lines = self.web(return_value=_page(opened=False))
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[2], f"   {LINK}")
        self.assertNotIn("Opened", "\n".join(lines))

    def test_no_display_gives_the_ssh_tunnel(self):
        with patch("socket.gethostname", return_value="devbox.example"):
            lines = self.web(return_value=_page(opened=False, headless=True))
        self.assertEqual(
            lines[1:],
            [
                "   No display on this host. On your workstation, run:",
                "   ssh -L 43817:127.0.0.1:43817 devbox",
                "   Then open this link within 2 minutes:",
                f"   {LINK}",
            ],
        )

    def test_the_french_success_is_the_one_of_the_spec(self):
        todo_i18n.use_lang("fr")
        self.assertEqual(
            self.web(return_value=_page()),
            [
                f"✅ Interface web prête — {URL}",
                "   Ouverte dans votre navigateur. Le lien ne sert qu'une"
                " fois, pendant 2 minutes.",
                "   Si la page ne s'est pas ouverte, utilisez ce lien dans"
                " les 2 minutes :",
                f"   {LINK}",
            ],
        )

    def test_root_is_refused(self):
        lines = self.failure("the web hub refuses to run as root", kind="root")
        self.assertEqual(
            lines, ["❌ The web interface refuses to run as root."]
        )

    def test_a_missing_tornado_gives_the_install_command(self):
        lines = self.failure(
            "the web hub did not start", kind="missing", pkg="tornado"
        )
        self.assertEqual(
            lines,
            [
                "❌ The web interface needs tornado. Install it with:",
                f"   {VENV_ERPLIBRE}/bin/pip install 'tornado>=6.5.10,<7'",
            ],
        )

    def test_a_hub_that_did_not_start_shows_its_log(self):
        lines = self.failure("the web hub did not start", "boom-marker\nend")
        self.assertEqual(
            lines,
            [
                "❌ The web interface did not start. Last lines of its log:",
                f"   {paths.log_path(new_path)}",
                "   boom-marker",
                "   end",
            ],
        )

    def test_without_a_log_the_launcher_says_why(self):
        lines = self.failure("cannot run /nowhere/python: forged")
        self.assertEqual(lines[-1], "   cannot run /nowhere/python: forged")

    def test_an_unexpected_error_stays_in_the_menu(self):
        lines = self.web(side_effect=RuntimeError("forged"))
        self.assertEqual(
            lines[0],
            "❌ The web interface did not start. Last lines of its log:",
        )
        self.assertEqual(lines[-1], "   RuntimeError: forged")

    def test_ctrl_c_while_starting_returns_to_the_choice(self):
        self.assertEqual(self.web(side_effect=KeyboardInterrupt), [""])


class TestWebStop(MenuCase):
    def stop(self, status, confirm=True, stopped=True):
        # Un double lève l'exception que porte son side_effect et rend toute
        # autre valeur : `confirm` et `stopped` sont l'une ou l'autre.
        with (
            patch.object(launcher, "status", return_value=status),
            patch.object(launcher, "stop", side_effect=[stopped]) as stop,
            patch("click.confirm", side_effect=[confirm]) as question,
        ):
            lines = self.printed(self.todo._todo_web_stop)
        return lines, stop, question

    def test_a_stopped_hub_is_left_alone(self):
        lines, stop, question = self.stop(None)
        self.assertEqual(lines, ["ℹ️ The web interface is not running."])
        stop.assert_not_called()
        question.assert_not_called()

    def test_an_idle_hub_stops_without_a_question(self):
        lines, stop, question = self.stop(RUNNING)
        self.assertEqual(lines, ["⏹️ Web interface stopped"])
        stop.assert_called_once_with(new_path)
        question.assert_not_called()

    def test_running_sessions_ask_first_and_no_stops_nothing(self):
        busy = dict(RUNNING, running=2)
        lines, stop, question = self.stop(busy, confirm=False)
        self.assertEqual(lines, [])
        stop.assert_not_called()
        question.assert_called_once_with(
            "2 web sessions are running a command. Stop them anyway?",
            default=False,
        )
        lines, stop, _ = self.stop(busy, confirm=True)
        self.assertEqual(lines, ["⏹️ Web interface stopped"])
        stop.assert_called_once_with(new_path)

    def test_ctrl_c_or_ctrl_d_at_the_question_stops_nothing(self):
        # click.confirm lève Abort pour l'un comme pour l'autre.
        busy = dict(RUNNING, running=1)
        lines, stop, _ = self.stop(busy, confirm=click.exceptions.Abort())
        self.assertEqual(lines, [""])
        stop.assert_not_called()

    def test_a_hub_still_answering_is_not_announced_stopped(self):
        lines, stop, _ = self.stop(RUNNING, stopped=False)
        self.assertEqual(lines, [])
        stop.assert_called_once_with(new_path)

    def test_an_interrupted_or_failed_stop_stays_in_the_menu(self):
        lines, _, _ = self.stop(RUNNING, stopped=KeyboardInterrupt())
        self.assertEqual(lines, [""])
        lines, _, _ = self.stop(RUNNING, stopped=OSError("forged"))
        self.assertEqual(lines, ["Command failed: forged"])


@unittest.skipIf(os.geteuid() == 0, "le lanceur refuse root")
@unittest.skipIf(
    sys.platform == "darwin", "macOS ouvre toujours le navigateur"
)
class TestWithARealHub(MenuCase):
    def setUp(self):
        super().setUp()
        run = os.path.join(self.tmp, "run")
        os.mkdir(run, 0o700)
        for patcher in (
            patch.dict(os.environ, {"XDG_RUNTIME_DIR": run}),
            patch.object(
                launcher.webbrowser, "open_new_tab", return_value=False
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("DISPLAY", None)
        os.environ.pop("WAYLAND_DISPLAY", None)
        self.addCleanup(launcher.stop, new_path)

    def test_open_then_stop_a_real_hub(self):
        lines = self.printed(self.todo._todo_telemetry_web)
        port = launcher.status(new_path)["port"]
        url = f"http://127.0.0.1:{port}/"
        self.assertEqual(lines[0], f"✅ Web interface ready — {url}")
        self.assertTrue(lines[2].startswith(f"   ssh -L {port}:127.0.0.1:"))
        self.assertRegex(lines[-1], rf"^   {url}#login=\S+&view=telemetry")
        self.assertEqual(
            self.printed(self.todo._todo_web_stop),
            ["⏹️ Web interface stopped"],
        )
        self.assertIsNone(launcher.status(new_path))


if __name__ == "__main__":
    unittest.main()
