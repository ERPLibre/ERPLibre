#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La fenêtre bureautique de TODO, pywebview SIMULÉ.

Un faux module `webview`, posé dans sys.modules, note la fenêtre créée et
rend la main de `start` aussitôt, comme une fenêtre qu'on ferme : ni
affichage ni moteur web n'est nécessaire. Une fausse fenêtre joue les
chargements de page que pywebview signale (`before_load`, puis `loaded`).
Le hub est vrai quand un test le dit, HOME et XDG_RUNTIME_DIR temporaires.
Le pont de la page (`static/src/desktop.js`) tourne sous node, quand il
est installé.
"""

import contextlib
import inspect
import io
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from test_todo_web_launcher import _login
from test_todo_web_static import _node_json
from todo_web_env import private_env

from script.todo import todo_i18n, todo_install
from script.todo.web import desktop, launcher, paths

REPO = Path(__file__).resolve().parent.parent
ORIGIN = "http://127.0.0.1:43817"
as_user = unittest.skipIf(os.geteuid() == 0, "le lanceur refuse root")
as_user = unittest.skipIf(os.geteuid() == 0, "le lanceur refuse root")


class FakeEvent:
    """Évènement de pywebview : `+=` ajoute un gestionnaire, `set` les
    appelle, dans ce fil."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def set(self):
        for handler in self.handlers:
            handler()


class FakeWindow:
    """Fausse fenêtre : note ses titres, ses fonctions exposées et les URL
    qu'on lui demande de charger ; `get_current_url` rend `current`."""

    def __init__(self, title, url, options):
        self.title, self.url, self.options = title, url, options
        self.current = url
        self.titles, self.exposed, self.loads = [], [], []
        self.events = types.SimpleNamespace(
            before_load=FakeEvent(), loaded=FakeEvent()
        )

    def set_title(self, title):
        self.titles.append(title)

    def expose(self, *functions):
        self.exposed.extend(functions)

    def get_current_url(self):
        return self.current

    def load_url(self, url):
        self.loads.append(url)

    def load(self, url, loaded=True):
        """Un chargement de `url` tel que pywebview le signale : avant
        l'injection de son API, puis, avec `loaded`, après."""
        self.current = url
        self.events.before_load.set()
        if loaded:
            self.events.loaded.set()


class FakeWebview(types.ModuleType):
    """Faux pywebview : `create_window` note la fenêtre, `start` note ses
    arguments et rend la main, ou lève l'exception `fail`."""

    class WebViewException(Exception):
        pass

    def __init__(self, fail=None):
        super().__init__("webview")
        self.windows, self.starts, self.fail = [], [], fail

    def create_window(self, title, url=None, **options):
        window = FakeWindow(title, url, options)
        self.windows.append(window)
        return window

    def start(self, **options):
        self.starts.append(options)
        if self.fail:
            raise self.fail


class FakeGi(types.ModuleType):
    """Faux PyGObject : seules les versions de `typelibs` existent."""

    def __init__(self, typelibs):
        super().__init__("gi")
        self.typelibs = typelibs

    def require_version(self, namespace, version):
        if (namespace, version) not in self.typelibs:
            raise ValueError(f"Namespace {namespace} not available")


class Terminal(io.StringIO):
    """Sortie qui se dit terminal."""

    def isatty(self):
        return True


def _program(test, name, body) -> Path:
    """Script shell `name` de corps `body`, seul dans un répertoire
    temporaire que le nettoyage de `test` retire."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    script = Path(tmp.name, name)
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(0o755)
    return script


def _fake_webview(test, fail=None):
    fake = FakeWebview(fail)
    patcher = patch.dict(sys.modules, {"webview": fake})
    patcher.start()
    test.addCleanup(patcher.stop)
    return fake


def _wait(predicate, timeout=5.0) -> bool:
    """Vrai dès que `predicate()` l'est, faux après `timeout` s."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


def _resolve(window, name):
    """Ce que pywebview 5.4 appelle quand la page envoie `name`
    (`util.js_bridge_call`) : une fonction exposée de ce nom exact, sinon
    le chemin pointé suivi dans le `js_api` par getattr."""
    found = {func.__name__: func for func in window.exposed}.get(name)
    if found is not None:
        return found
    target = window.options.get("js_api")
    for attr in name.split("."):
        target = getattr(target, attr, None)
        if target is None:
            return None
    return target


class TestAvailability(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(sys, "platform", "linux")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_without_pywebview_nothing_is_available(self):
        with patch.dict(sys.modules, {"webview": None}):
            self.assertIsNone(desktop.engine())
            self.assertFalse(desktop.available())

    def test_gtk_comes_before_qt_as_in_pywebview(self):
        _fake_webview(self)
        gtk = FakeGi({("Gtk", "3.0"), ("WebKit2", "4.0")})
        qt = {"qtpy", "PyQt6.QtWebEngineWidgets"}
        found = patch.object(desktop, "_found", side_effect=qt.__contains__)
        libraries = patch.object(desktop, "_qt_libraries", return_value=True)
        with found, libraries, patch.dict(sys.modules, {"gi": gtk}):
            self.assertEqual(desktop.engine(), "gtk")
        # GTK sans WebKit2, comme sur un poste sans WebKitGTK.
        without = FakeGi({("Gtk", "3.0")})
        with found, libraries, patch.dict(sys.modules, {"gi": without}):
            self.assertEqual(desktop.engine(), "qt")
        with found, libraries, patch.dict(sys.modules, {"gi": None}):
            self.assertTrue(desktop.available())
        # QtPy sans QtWebEngine n'est pas un moteur.
        bare = patch.object(
            desktop, "_found", side_effect={"qtpy"}.__contains__
        )
        with bare, libraries, patch.dict(sys.modules, {"gi": None}):
            self.assertIsNone(desktop.engine())

    def test_qt_without_its_system_libraries_is_no_engine(self):
        # L'environnement, les bibliothèques que l'éditeur de liens trouve,
        # le moteur attendu : xcb exige libxcb-cursor, wayland et offscreen
        # s'en passent, et libxkbfile manque à tout QtWebEngine.
        _fake_webview(self)
        qt = {"qtpy", "PyQt6.QtWebEngineWidgets"}
        cases = [
            ("DISPLAY=:0", "xkbfile xcb-cursor", "qt"),
            ("DISPLAY=:0", "xkbfile", None),
            ("DISPLAY=:0 WAYLAND_DISPLAY=w", "xkbfile", "qt"),
            ("DISPLAY=:0 QT_QPA_PLATFORM=offscreen", "xkbfile", "qt"),
            ("WAYLAND_DISPLAY=w QT_QPA_PLATFORM=xcb", "xkbfile", None),
            ("WAYLAND_DISPLAY=w", "xcb-cursor", None),
        ]
        for env, found, expected in cases:
            variables = dict(pair.split("=") for pair in env.split())
            libraries = found.split()
            with (
                patch.dict(os.environ, variables),
                patch.object(desktop, "_found", side_effect=qt.__contains__),
                patch.dict(sys.modules, {"gi": None}),
                patch(
                    "ctypes.util.find_library",
                    side_effect=lambda name, libraries=libraries: (
                        f"lib{name}.so" if name in libraries else None
                    ),
                ),
            ):
                for name in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM"):
                    if name not in variables:
                        os.environ.pop(name, None)
                self.assertEqual(desktop.engine(), expected, (env, found))

    def test_a_display_is_named_by_the_environment(self):
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}):
            os.environ.pop("DISPLAY", None)
            self.assertTrue(desktop.has_display())
            os.environ.pop("WAYLAND_DISPLAY")
            self.assertFalse(desktop.has_display())

    def test_the_hint_names_pip_in_the_venv_then_the_system_libraries(self):
        python = launcher.venv_python(REPO)
        pip = shlex.join(
            [python, "-m", "pip", "install"] + [desktop.PYWEBVIEW]
        )
        with patch.object(todo_install, "family", return_value="pacman"):
            self.assertEqual(
                desktop.install_hint(REPO),
                [
                    pip,
                    "sudo pacman -S --needed --noconfirm libxkbfile"
                    " xcb-util-cursor",
                ],
            )
        self.assertIn(" 'pywebview[qt]>=5,<6'", pip)
        with patch.object(todo_install, "family", return_value=None):
            self.assertEqual(desktop.install_hint(REPO), [pip])
        # Sous macOS, pywebview prend le moteur du système : ni Qt ni
        # bibliothèques.
        with (
            patch.object(sys, "platform", "darwin"),
            patch.object(todo_install, "family", return_value="brew"),
        ):
            self.assertEqual(
                desktop.install_hint(REPO),
                [f"{shlex.quote(python)} -m pip install 'pywebview>=5,<6'"],
            )


class TestBridge(unittest.TestCase):
    def on_the_hub(self, window):
        """Les deux fonctions du pont de `window`, sa page du hub chargée ;
        le chargement applique le titre de base."""
        functions = desktop.bridge(window, ORIGIN)
        window.load(ORIGIN + "/#view=telemetry")
        self.assertTrue(_wait(lambda: window.titles))
        self.assertEqual(window.titles.pop(), "ERPLibre TODO")
        return functions

    def test_the_page_reaches_two_functions_only(self):
        window = FakeWindow("", "", {})
        functions = desktop.bridge(window, ORIGIN)
        window.expose(*functions)
        self.assertEqual(
            sorted(func.__name__ for func in functions),
            ["notify", "set_title"],
        )
        self.assertTrue(all(map(inspect.isfunction, functions)))
        self.assertIs(_resolve(window, "set_title"), functions[0])
        # Sans js_api, un chemin pointé venu de la page n'atteint rien.
        for name in (
            "_window.gui.os.system",
            "set_title.__globals__.__setitem__",
            "__class__.__init__.__globals__.__setitem__",
        ):
            self.assertIsNone(_resolve(window, name), name)

    def test_the_title_is_one_clean_line(self):
        window = FakeWindow("", "", {})
        set_title, _ = self.on_the_hub(window)
        set_title("TODO › Execute\n\x1b[31m‮Forged " + "x" * 300)
        set_title(" \t")
        [shown, empty] = window.titles
        self.assertTrue(shown.startswith("TODO › Execute [31m Forged xx"))
        self.assertEqual(len(shown), desktop.TITLE_MAX)
        self.assertTrue(shown.isprintable(), shown)
        self.assertEqual(empty, "ERPLibre TODO")

    def test_a_title_sent_during_the_load_applies_once_on_the_hub(self):
        window = FakeWindow("", "", {})
        set_title, _ = desktop.bridge(window, ORIGIN)
        window.load(ORIGIN + "/", loaded=False)
        set_title("TODO")
        self.assertEqual(window.titles, [])
        window.events.loaded.set()
        self.assertTrue(_wait(lambda: window.titles))
        self.assertEqual(window.titles, ["TODO"])

    def notify_send(self, body):
        """Un notify-send de corps `body`, seul programme du PATH ; rend son
        répertoire."""
        base = _program(self, "notify-send", body).parent
        patcher = patch.dict(os.environ, {"PATH": str(base)})
        patcher.start()
        self.addCleanup(patcher.stop)
        return base

    def test_a_foreign_page_reaches_nothing_and_goes_back_to_the_hub(self):
        base = self.notify_send('echo >> "${0%/*}/calls"')
        window = FakeWindow("", "", {})
        set_title, notify = desktop.bridge(window, ORIGIN)
        foreign = [
            "http://forged.invalid/",
            ORIGIN + "0/",
            ORIGIN + ".forged.invalid/",
            "file:///forged.html",
            None,
        ]
        for number, url in enumerate(foreign, 1):
            window.load(url)
            self.assertTrue(_wait(lambda: len(window.loads) == number))
            set_title("Forged")
            self.assertFalse(notify("Forged", "body"))
        self.assertEqual(window.loads, [ORIGIN + "/"] * len(foreign))
        self.assertEqual(window.titles, [])
        self.assertFalse((base / "calls").exists())
        # De retour sur le hub, la page retrouve le pont.
        window.load(ORIGIN + "/")
        self.assertTrue(_wait(lambda: window.titles))
        self.assertTrue(notify("TODO", "body"))

    def test_a_foreign_document_reaches_nothing_before_before_load(self):
        """Le canal qui porte les fonctions exposées écoute toute page dès
        son premier script ; seul `before_load` referme le pont, au
        chargement fini. Une page étrangère qui l'atteint avant ce signal,
        `hub` encore vrai du chargement précédent, ne trouve donc rien."""
        window = FakeWindow("", "", {})
        set_title, notify = self.on_the_hub(window)
        window.current = "http://forged.invalid/"
        self.assertFalse(notify("Forged", "body"))
        set_title("Forged")
        self.assertEqual(window.titles, [])

    def test_the_page_notifies_once_a_second_at_most(self):
        base = self.notify_send('echo >> "${0%/*}/calls"')
        _, notify = self.on_the_hub(FakeWindow("", "", {}))
        with patch.object(desktop, "NOTIFY_INTERVAL", 0.2):
            self.assertTrue(notify("TODO", "first"))
            self.assertFalse(notify("TODO", "too soon"))
            time.sleep(0.25)
            self.assertTrue(notify("TODO", "later"))
        self.assertEqual((base / "calls").read_text(), "\n\n")

    def test_notify_passes_an_argument_list_without_a_shell(self):
        base = self.notify_send('printf "%s\\n" "$@" > "${0%/*}/argv"')
        marker = base / "marker"
        body = f"<b>x</b> $(touch {marker}); `touch {marker}`"
        with patch.object(
            desktop.subprocess, "run", wraps=subprocess.run
        ) as run:
            self.assertTrue(desktop.send_notification("-u critical", body))
        self.assertIsInstance(run.call_args.args[0], list)
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        argv = (base / "argv").read_text().splitlines()
        # Le corps est du balisage pour le serveur de notifications.
        escaped = f"&lt;b&gt;x&lt;/b&gt; $(touch {marker}); `touch {marker}`"
        self.assertEqual(
            argv, ["--app-name=ERPLibre TODO", "--", "-u critical", escaped]
        )
        self.assertFalse(marker.exists())

    def test_notify_is_silent_when_notify_send_is_absent_or_fails(self):
        # Résolu avant que notify_send() ne restreigne PATH au faux
        # programme, seul moyen d'y trouver encore un vrai sleep.
        sleep = shutil.which("sleep")
        base = self.notify_send("exit 1")
        self.assertFalse(desktop.send_notification("title", "body"))
        (base / "notify-send").unlink()
        self.assertFalse(desktop.send_notification("title", "body"))
        self.notify_send(f"exec {sleep} 5")
        with patch.object(desktop, "NOTIFY_TIMEOUT", 0.2):
            start = time.monotonic()
            self.assertFalse(desktop.send_notification("title", "body"))
        # Faux forcément par le délai, jamais par un code de sortie.
        self.assertGreaterEqual(time.monotonic() - start, 0.2)


@as_user
class TestOpenWindow(unittest.TestCase):
    """Un vrai hub par test, lancé par open_window ou avant lui."""

    def setUp(self):
        self.base = private_env(self.addCleanup)
        self.addCleanup(launcher.stop, REPO)
        os.environ["DISPLAY"] = ":0"
        self.webview = _fake_webview(self)
        engine = patch.object(desktop, "engine", return_value="qt")
        engine.start()
        self.addCleanup(engine.stop)
        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)

    def test_the_window_gets_the_code_and_no_process_argv_does(self):
        with patch.object(
            launcher.subprocess, "Popen", wraps=subprocess.Popen
        ) as popen:
            self.assertEqual(desktop.open_window(REPO, lang="en"), 0)
        [window] = self.webview.windows
        fragment = parse_qs(urlsplit(window.url).fragment)
        [code] = fragment["login"]
        self.assertEqual(
            (fragment["view"], fragment["lang"]), (["telemetry"], ["en"])
        )
        # Le hub a été lancé ici : un argv existe, sans le code.
        self.assertEqual(popen.call_count, 1)
        self.assertNotIn(code, repr(popen.call_args))
        port = launcher.status(REPO)["port"]
        self.assertTrue(window.url.startswith(f"http://127.0.0.1:{port}/#"))
        self.assertEqual(_login(port, code), 200)
        self.assertEqual(window.title, "ERPLibre TODO")
        # Deux fonctions exposées par leur nom, aucun js_api.
        self.assertNotIn("js_api", window.options)
        self.assertEqual(
            sorted(func.__name__ for func in window.exposed),
            ["notify", "set_title"],
        )
        [options] = self.webview.starts
        storage = Path(options["storage_path"])
        self.assertEqual(storage, paths.data_dir(REPO) / "desktop")
        self.assertEqual(stat.S_IMODE(storage.stat().st_mode), 0o700)
        self.assertIs(options["private_mode"], True)

    def test_closing_the_window_sends_nothing_to_the_hub(self):
        before = launcher.ensure_running(REPO)
        with patch.object(launcher, "_ctl", wraps=launcher._ctl) as ctl:
            self.assertEqual(desktop.open_window(REPO), 0)
        self.assertEqual(
            [call.args[1] for call in ctl.call_args_list], ["status", "mint"]
        )
        self.assertEqual(launcher.status(REPO)["pid"], before["pid"])

    def test_root_is_refused_before_any_file(self):
        with (
            patch("os.geteuid", return_value=0),
            self.assertRaisesRegex(launcher.LaunchError, "root") as ctx,
        ):
            desktop.open_window(REPO)
        self.assertEqual(ctx.exception.kind, "root")
        self.assertEqual(self.webview.windows, [])
        self.assertFalse((self.base / "run" / paths.APP).exists())
        self.assertFalse((self.base / "home" / ".erplibre").exists())

    def test_invalid_view_or_language_is_refused(self):
        with self.assertRaises(ValueError):
            desktop.open_window(REPO, view="x&login=y")
        with self.assertRaises(ValueError):
            desktop.open_window(REPO, lang="de")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(desktop.main(["open", "--view", "X"]), 2)
        self.assertEqual(self.webview.windows, [])

    def fallback(self, *argv, lang="en", out=None):
        """`main(["open", *argv])` quand il retombe sur le navigateur :
        rend les lignes de sa sortie d'erreur, puis celles de sa sortie
        (`out`, un tuyau par défaut) ; le lanceur est simulé."""
        page = launcher.OpenResult(
            ORIGIN + "/", ORIGIN + "/#login=forged", True, False
        )
        out = out or io.StringIO()
        err = io.StringIO()
        with (
            patch.dict(os.environ, {"TODO_LANG": lang}),
            patch.object(launcher, "open_page", return_value=page) as browser,
            patch.object(todo_install, "family", return_value="apt-get"),
            contextlib.redirect_stderr(err),
            contextlib.redirect_stdout(out),
        ):
            self.assertEqual(desktop.main(["open", *argv]), 0)
        browser.assert_called_once_with(str(REPO), view="telemetry", lang=lang)
        return err.getvalue().splitlines(), out.getvalue().splitlines()

    def test_without_pywebview_main_opens_the_browser(self):
        with patch.dict(sys.modules, {"webview": None}):
            lines, _ = self.fallback("--root", str(REPO))
        self.assertEqual(
            lines[:2], ["pywebview is not installed", "install it with:"]
        )
        self.assertEqual(lines[2], "  " + desktop.install_hint(REPO)[0])
        self.assertEqual(
            lines[3:],
            [
                "  sudo apt-get install -y libxkbfile1 libxcb-cursor0",
                "opening the page in the browser instead",
            ],
        )

    def test_without_an_engine_main_opens_the_browser(self):
        with patch.object(desktop, "engine", return_value=None):
            lines, _ = self.fallback("--root", str(REPO))
        self.assertEqual(
            lines[:2], ["pywebview finds no web engine", "install it with:"]
        )
        self.assertEqual(lines[2], "  " + desktop.install_hint(REPO)[0])
        self.assertEqual(
            lines[3:],
            [
                "  sudo apt-get install -y libxkbfile1 libxcb-cursor0",
                "opening the page in the browser instead",
            ],
        )
        self.assertEqual(self.webview.windows, [])

    def test_without_a_display_main_opens_the_browser(self):
        os.environ.pop("DISPLAY")
        lines, _ = self.fallback("--root", str(REPO))
        self.assertEqual(
            lines,
            [
                "no display on this host",
                "opening the page in the browser instead",
            ],
        )
        self.assertEqual(self.webview.windows, [])

    def test_an_engine_that_does_not_load_opens_the_browser(self):
        failures = [
            self.webview.WebViewException("You must have either QT or GTK"),
            RuntimeError("Gtk couldn't be initialized"),
        ]
        for fail in failures:
            self.webview.fail = fail
            lines, _ = self.fallback("--root", str(REPO), lang="fr")
            self.assertEqual(
                lines[0],
                f"pywebview did not start: {type(fail).__name__}: {fail}",
            )
            self.assertEqual(
                lines[-1], "opening the page in the browser instead"
            )
        # TODO_LANG fixe la langue de la fenêtre, puis celle du navigateur.
        window = self.webview.windows[-1]
        self.assertEqual(
            parse_qs(urlsplit(window.url).fragment)["lang"], ["fr"]
        )
        self.assertEqual(todo_i18n.get_lang(), "fr")

    def test_the_login_link_is_printed_to_a_terminal_only(self):
        self.webview.fail = RuntimeError("forged")
        err, out = self.fallback("--root", str(REPO))
        # Lancée par le menu ou par le bureau, la sortie est un journal.
        self.assertEqual(out, [f"url: {ORIGIN}/"])
        self.assertNotIn("login=", "\n".join(err + out))
        _, out = self.fallback("--root", str(REPO), out=Terminal())
        self.assertEqual(
            out, [f"url: {ORIGIN}/", f"link: {ORIGIN}/#login=forged"]
        )

    def test_a_hub_that_does_not_start_is_not_a_missing_pywebview(self):
        tornado = launcher.LaunchError(
            "the web hub did not start",
            "ModuleNotFoundError: No module named 'tornado'",
            kind="missing",
            pkg="tornado",
        )
        err = io.StringIO()
        with (
            patch.object(launcher, "ensure_running", side_effect=tornado),
            patch.object(launcher, "open_page") as browser,
            contextlib.redirect_stderr(err),
        ):
            self.assertEqual(desktop.main(["open", "--root", str(REPO)]), 1)
        browser.assert_not_called()
        self.assertEqual(
            err.getvalue().splitlines(),
            [
                "the web hub did not start",
                "ModuleNotFoundError: No module named 'tornado'",
            ],
        )

    def test_the_make_target_opens_the_window(self):
        out = subprocess.run(
            ["make", "-n", "-f", "conf/make.todo.Makefile", "todo_desktop"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertIn("-m script.todo.web.desktop open", out)


# Le pont dans un navigateur, puis dans une fenêtre dont l'API arrive
# après le pont, avec `pywebviewready` ; enfin une API qui échoue.
BRIDGE_CHECK = r"""
const calls = [];
const record = (name) => (...args) => {
    calls.push([name, ...args]);
    return Promise.resolve(null);
};
const dropped = (target) => {
    const event = new Event("drop", {cancelable: true});
    target.dispatchEvent(event);
    return event.defaultPrevented;
};
const browser = new EventTarget();
const plain = m.desktopBridge(browser, "ERPLibre TODO");
plain.title(["TODO"]);
plain.notify("body");
browser.dispatchEvent(new Event("pywebviewready"));
const win = new EventTarget();
const bridge = m.desktopBridge(win, "ERPLibre TODO");
bridge.title(["TODO", "Execute"]);
win.pywebview = {api: {set_title: record("set_title"), notify: record("notify")}};
win.dispatchEvent(new Event("pywebviewready"));
bridge.title(["TODO", "Execute"]);
bridge.title(["TODO"]);
bridge.notify("Command ended");
bridge.title([]);
const broken = new EventTarget();
broken.pywebview = {api: {
    set_title: () => Promise.reject(new Error("forged")),
    notify: () => { throw new Error("forged"); },
}};
const failing = m.desktopBridge(broken, "ERPLibre TODO");
failing.title(["TODO"]);
failing.notify("body");
await new Promise((resolve) => setTimeout(resolve, 0));
const t = (key) => key;
console.log(JSON.stringify({
    browser: "pywebview" in browser,
    calls,
    dropped: [dropped(browser), dropped(win)],
    long: [{t: "run_end", secs: 10}, {t: "run_end", secs: 10.5},
        {t: "run_start", secs: 60}, {t: "run_end"}].map(m.endsLongRun),
    bodies: [m.runEndBody(t, {rc: 2, secs: 11.6}),
        m.runEndBody(t, {rc: null, secs: 42})],
}));
"""


@unittest.skipUnless(shutil.which("node"), "node absent")
class TestPageBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = _node_json(BRIDGE_CHECK, "desktop.js")

    def test_the_page_calls_the_bridge_only_when_it_exists(self):
        # Dans un navigateur, rien ne part et rien n'apparaît.
        self.assertIs(self.out["browser"], False)
        self.assertEqual(
            self.out["calls"],
            [
                ["set_title", "TODO › Execute — ERPLibre TODO"],
                ["set_title", "TODO — ERPLibre TODO"],
                ["notify", "TODO — ERPLibre TODO", "Command ended"],
                ["set_title", "ERPLibre TODO"],
            ],
        )

    def test_a_drop_is_refused_in_the_window_only(self):
        # Le moteur chargerait le lien ou le fichier déposé à la place de
        # la page ; un navigateur garde son comportement.
        self.assertEqual(self.out["dropped"], [False, True])

    def test_only_a_command_longer_than_ten_seconds_notifies(self):
        self.assertEqual(self.out["long"], [False, True, False, False])
        self.assertEqual(
            self.out["bodies"],
            [
                "Command ended: exit code 2, 12 s",
                "Command ended: exit code —, 42 s",
            ],
        )


if __name__ == "__main__":
    unittest.main()
