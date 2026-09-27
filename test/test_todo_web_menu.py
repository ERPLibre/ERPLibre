#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'entrée [4] du menu principal, qui propose la télémétrie en TUI ou dans
le navigateur et l'arrêt de l'interface web, et ses méthodes web : ouvrir la
page par le hub de ce checkout, dire pourquoi il n'a pas démarré, l'arrêter.

La TUI et le lanceur sont simulés, sauf dans TestWithARealHub, qui démarre un
vrai hub.
HOME, et XDG_RUNTIME_DIR pour le vrai hub, pointent vers un répertoire
temporaire ; TODO_WEB_FD et TODO_WEB_PID sont retirés, sauf dans
TestInsideAWebSession, qui les pose comme le worker d'une session. La langue
est fixée par test (`use_lang`, sans écrire env_var.sh) et la télémétrie de
navigation, que chaque menu enregistre, est neutralisée.
"""

import io
import os
import socket
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import click

from script.todo import todo_i18n, todo_telemetry
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
        os.environ.pop("TODO_WEB_FD", None)
        os.environ.pop("TODO_WEB_PID", None)
        self.todo = TODO()

    def printed(self, method):
        """Lignes qu'affiche `method()` ; elle ne doit rien rendre."""
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertIsNone(method())
        return out.getvalue().splitlines()

    def menu(self, status=None):
        """Texte que prompt_telemetry soumet à click.prompt, puis [0].
        `status` est ce que rend launcher.status, ou l'exception qu'il
        lève."""
        with (
            patch.object(launcher, "status", side_effect=[status]) as probe,
            patch("click.prompt", side_effect=["0"]) as prompt,
            redirect_stdout(io.StringIO()),
        ):
            self.assertIs(self.todo.prompt_telemetry(), False)
        probe.assert_called_with(new_path)
        return prompt.call_args.args[0].splitlines()


class TestPromptTelemetry(MenuCase):
    def test_each_number_reaches_its_method_and_zero_goes_back(self):
        with (
            patch.object(TODO, "_todo_telemetry_tui") as tui,
            patch.object(TODO, "_todo_telemetry_web") as web,
            patch.object(TODO, "_todo_web_stop") as stop,
            patch.object(launcher, "status", return_value=None),
            patch("click.prompt", side_effect=["1", "2", "3", "9", "0"]),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertIs(self.todo.prompt_telemetry(), False)
        for method in (tui, web, stop):
            method.assert_called_once_with()
        self.assertIn("Command not found !", out.getvalue())

    def test_the_french_menu_is_the_one_of_the_spec(self):
        todo_i18n.use_lang("fr")
        self.assertEqual(
            self.menu(),
            [
                "📍 Navigation telemetry",
                "🌐 Interface web : arrêtée",
                "Commande :",
                "[1] 📊 Télémétrie de navigation (TUI)",
                "[2] 🌐 Télémétrie de navigation (WEB)",
                "[3] ⏹️ Arrêter l'interface web",
                "[0] 🔙 Retour",
            ],
        )

    def test_a_running_hub_shows_its_address_and_sessions(self):
        self.assertEqual(
            self.menu(RUNNING)[1],
            f"🌐 Web interface: running on {URL} (sessions: 2)",
        )

    def test_an_unreadable_hub_shows_stopped(self):
        lines = self.menu(OSError("forged"))
        self.assertIn("🌐 Web interface: stopped", lines)


class TestTelemetryTui(MenuCase):
    def tui(self, result):
        """[1] puis [0] : `run_tui` rend `result`, ou le lève. Rend ce qui
        s'affiche ; rien ne doit remonter."""
        with (
            patch("script.todo.textual_setup.ensure", return_value=True),
            patch.object(todo_telemetry, "run_tui", side_effect=[result]),
            patch.object(launcher, "status", return_value=None),
            patch("click.prompt", side_effect=["1", "0"]) as prompt,
            patch("builtins.input", return_value=""),
            redirect_stdout(io.StringIO()) as out,
        ):
            try:
                self.assertIs(self.todo.prompt_telemetry(), False)
            except (KeyboardInterrupt, EOFError, click.exceptions.Abort) as e:
                self.fail(f"{type(e).__name__} left the menu")
        self.assertEqual(prompt.call_count, 2)
        return out.getvalue()

    def test_nothing_from_the_tui_leaves_the_menu(self):
        for error in (KeyboardInterrupt, EOFError, click.exceptions.Abort):
            with self.subTest(error=error.__name__):
                self.tui(error())
        out = self.tui(ValueError("boom-marker"))
        self.assertIn("Command failed: boom-marker", out)

    def test_a_command_it_launches_keeps_the_path_of_its_menu(self):
        def forged_command(todo):
            todo._menu_header()

        path = "TODO › Execute › Git › Forged command"
        action = ("forged_command", {})
        with patch.object(TODO, "forged_command", forged_command, create=True):
            self.tui((action, {"path": path}))
        keys = [c.args[0] for c in todo_telemetry.record.call_args_list]
        self.assertEqual(
            keys,
            [
                "Navigation telemetry",
                path,
                "TODO › Execute › Git",
                "Navigation telemetry",
            ],
        )


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
        self.assertEqual(
            lines,
            [
                "❌ The web interface did not start.",
                "   cannot run /nowhere/python: forged",
            ],
        )

    def test_an_unexpected_error_stays_in_the_menu(self):
        lines = self.web(side_effect=RuntimeError("forged"))
        self.assertEqual(
            lines,
            ["❌ The web interface did not start.", "   RuntimeError: forged"],
        )

    def test_a_missing_package_always_names_tornado(self):
        # `exc.pkg` ne vaut aujourd'hui que "tornado" (seul appel du
        # lanceur avec kind="missing") : la commande affichée l'ignore
        # sans se tromper pour autant.
        lines = self.failure(
            "the web hub did not start", kind="missing", pkg="other"
        )
        self.assertEqual(
            lines[-1],
            f"   {VENV_ERPLIBRE}/bin/pip install 'tornado>=6.5.10,<7'",
        )

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

    def test_ctrl_c_during_the_status_probe_stays_in_the_menu(self):
        with (
            patch.object(launcher, "status", side_effect=KeyboardInterrupt),
            patch.object(launcher, "stop") as stop,
        ):
            lines = self.printed(self.todo._todo_web_stop)
        self.assertEqual(lines, [""])
        stop.assert_not_called()

    def test_an_unreadable_hub_is_not_running(self):
        with (
            patch.object(launcher, "status", side_effect=OSError("forged")),
            patch.object(launcher, "stop") as stop,
        ):
            lines = self.printed(self.todo._todo_web_stop)
        self.assertEqual(lines, ["ℹ️ The web interface is not running."])
        stop.assert_not_called()


class TestInsideAWebSession(MenuCase):
    def channel(self, pid=None):
        """Le canal comme le pose le worker : rend l'extrémité du hub."""
        hub, worker = socket.socketpair()
        self.addCleanup(hub.close)
        self.addCleanup(worker.close)
        env = {"TODO_WEB_FD": str(worker.fileno())}
        env["TODO_WEB_PID"] = str(pid or os.getpid())
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        return hub

    def test_telemetry_opens_in_the_page_and_starts_nothing(self):
        hub = self.channel()
        with patch.object(launcher, "open_page") as open_page:
            lines = self.printed(self.todo._todo_telemetry_web)
        self.assertEqual(lines, ["Telemetry opened in this page."])
        open_page.assert_not_called()
        line = b'{"t": "open_view", "view": "telemetry"}\n'
        self.assertEqual(hub.recv(4096), line)

    def test_a_channel_that_fails_opens_the_page_as_usual(self):
        # Le hub a fermé son extrémité : l'écriture échoue (EPIPE).
        self.channel().close()
        with patch.object(
            launcher, "open_page", return_value=_page()
        ) as open_page:
            lines = self.printed(self.todo._todo_telemetry_web)
        open_page.assert_called_once()
        self.assertEqual(lines[0], f"✅ Web interface ready — {URL}")
        self.assertNotIn("Telemetry opened in this page.", lines)

    def test_a_todo_started_from_a_session_opens_the_page_as_usual(self):
        # Il hérite des variables, pas du descripteur : un autre pid.
        hub = self.channel(pid=1)
        with patch.object(
            launcher, "open_page", return_value=_page()
        ) as open_page:
            lines = self.printed(self.todo._todo_telemetry_web)
        open_page.assert_called_once()
        self.assertEqual(lines[0], f"✅ Web interface ready — {URL}")
        hub.setblocking(False)
        with self.assertRaises(BlockingIOError):
            hub.recv(4096)

    def test_stop_stops_nothing(self):
        self.channel(pid=1)
        # Un hub arrêté : sans la branche de session, [3] le dit et rend la
        # main, sans jamais poser de question.
        with (
            patch.object(launcher, "status", return_value=None) as status,
            patch.object(launcher, "stop") as stop,
        ):
            lines = self.printed(self.todo._todo_web_stop)
        self.assertEqual(
            lines,
            [
                "This TODO runs in the web interface: stop the interface from"
                " a terminal."
            ],
        )
        status.assert_not_called()
        stop.assert_not_called()


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
        self.assertIn(f"running on {url} (sessions: 0)", self.menu_text())
        self.assertEqual(
            self.printed(self.todo._todo_web_stop),
            ["⏹️ Web interface stopped"],
        )
        self.assertIsNone(launcher.status(new_path))

    def menu_text(self):
        with (
            patch("click.prompt", side_effect=["0"]) as prompt,
            redirect_stdout(io.StringIO()),
        ):
            self.todo.prompt_telemetry()
        return prompt.call_args.args[0]


if __name__ == "__main__":
    unittest.main()
