#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La fenêtre bureautique de TODO, pywebview SIMULÉ.

Un faux module `webview`, posé dans sys.modules, note la fenêtre créée et
rend la main de `start` aussitôt, comme une fenêtre qu'on ferme : ni
affichage ni moteur web n'est nécessaire. Une fausse fenêtre joue les
chargements de page que pywebview signale (`before_load`, puis `loaded`),
avec l'attente et la baisse de `loaded` de pywebview 5.4, et son dialogue
de fichiers rend ce que le test lui donne.
Le hub est vrai quand un test le dit, HOME et XDG_RUNTIME_DIR temporaires.
Le processus détaché de `spawn` est un faux python, un script shell ;
l'entrée du bureau s'écrit sous un XDG_DATA_HOME temporaire. Le pont de la
page (`static/src/desktop.js`) tourne sous node, quand il
est installé.
"""

import contextlib
import hmac
import inspect
import io
import os
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
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
# Jeton du pont des fausses fenêtres, tiré comme celui d'`open_window`.
TOKEN = secrets.token_urlsafe(32)
# Secondes que `get_current_url` de pywebview 5.4 attend `loaded`.
LOADED_WAIT = 20
as_user = unittest.skipIf(os.geteuid() == 0, "le lanceur refuse root")


class FakeEvent:
    """Évènement de pywebview (`webview.event.Event`) : `+=` ajoute un
    gestionnaire ; `set` lève le drapeau, puis appelle les gestionnaires
    dans ce fil ; `is_set`, `wait` et `clear` lisent, attendent et baissent
    le drapeau."""

    def __init__(self):
        self.handlers = []
        self.flag = threading.Event()

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def set(self):
        self.flag.set()
        for handler in self.handlers:
            handler()

    def is_set(self):
        return self.flag.is_set()

    def wait(self, timeout=None):
        return self.flag.wait(timeout)

    def clear(self):
        self.flag.clear()


class FakeWindow:
    """Fausse fenêtre au contrat de pywebview 5.4 : `get_current_url`
    attend `events.loaded`, LOADED_WAIT s au plus, puis rend `current` ;
    `load_url` baisse `loaded` et fait de l'URL demandée la courante, comme
    le moteur qui y bascule aussitôt. Note ses titres, ses fonctions
    exposées, les URL que `load_url` reçoit et chaque dialogue de fichiers
    ouvert (`opened`), qui rend le suivant de `dialogs` une fois `hold`
    levé, s'il y en a un."""

    def __init__(self, title, url, options):
        self.title, self.url, self.options = title, url, options
        self.current = url
        self.titles, self.exposed, self.loads = [], [], []
        self.dialogs, self.opened, self.hold = [], [], None
        self.events = types.SimpleNamespace(
            before_load=FakeEvent(), loaded=FakeEvent()
        )

    def set_title(self, title):
        self.titles.append(title)

    def expose(self, *functions):
        self.exposed.extend(functions)

    def get_current_url(self):
        if not self.events.loaded.wait(LOADED_WAIT):
            raise RuntimeError("Main window failed to load")
        return self.current

    def load_url(self, url):
        self.loads.append(url)
        self.events.loaded.clear()
        self.current = url

    def create_file_dialog(self, dialog_type, directory=""):
        self.opened.append((dialog_type, directory))
        if self.hold is not None:
            self.hold.wait(10)
        return self.dialogs.pop(0)

    def load(self, url, loaded=True):
        """Un chargement de `url` fini, tel que pywebview le signale :
        `before_load` avant l'injection de son API, puis, avec `loaded`,
        `loaded` après. Sans `load_url`, un lien suivi par exemple, le
        drapeau `loaded` du chargement précédent reste levé."""
        self.current = url
        self.events.before_load.set()
        if loaded:
            self.events.loaded.set()


class FakeWebview(types.ModuleType):
    """Faux pywebview : `create_window` note la fenêtre, `start` note ses
    arguments et rend la main, ou lève l'exception `fail`."""

    class WebViewException(Exception):
        pass

    # Les types de dialogue de pywebview 5.4.
    OPEN_DIALOG = 10
    FOLDER_DIALOG = 20

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


def _at_once(test, function, *args):
    """`function(*args)` dans un fil, qui doit rendre en moins d'une
    seconde : un appel du pont reçu `loaded` baissé n'attend pas le
    chargement d'une page."""
    result = []
    thread = threading.Thread(
        target=lambda: result.append(function(*args)), daemon=True
    )
    thread.start()
    thread.join(1.0)
    test.assertFalse(thread.is_alive(), f"{function.__name__} waits")
    return result[0]


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
        """Les trois fonctions du pont de `window`, de jeton TOKEN, sa page
        du hub chargée ; le chargement applique le titre de base."""
        functions = desktop.bridge(window, ORIGIN, TOKEN)
        window.load(ORIGIN + "/#view=telemetry")
        self.assertTrue(_wait(lambda: window.titles))
        self.assertEqual(window.titles.pop(), "ERPLibre TODO")
        return functions

    def test_the_page_reaches_three_functions_only(self):
        window = FakeWindow("", "", {})
        functions = desktop.bridge(window, ORIGIN, TOKEN)
        window.expose(*functions)
        self.assertEqual(
            sorted(func.__name__ for func in functions),
            ["notify", "pick_path", "set_title"],
        )
        self.assertTrue(all(map(inspect.isfunction, functions)))
        self.assertIs(_resolve(window, "set_title"), functions[0])

    def test_the_title_is_one_clean_line(self):
        window = FakeWindow("", "", {})
        set_title, *_ = self.on_the_hub(window)
        set_title(TOKEN, "TODO › Execute\n\x1b[31m\u202eForged " + "x" * 300)
        set_title(TOKEN, " \t")
        [shown, empty] = window.titles
        self.assertTrue(shown.startswith("TODO › Execute [31m Forged xx"))
        self.assertEqual(len(shown), desktop.TITLE_MAX)
        self.assertTrue(shown.isprintable(), shown)
        self.assertEqual(empty, "ERPLibre TODO")

    def test_a_title_sent_during_a_reload_applies_once_on_the_hub(self):
        # `before_load` a fermé le pont ; `loaded`, levé depuis la page
        # précédente, laisse lire l'URL : le titre est gardé, puis appliqué.
        window = FakeWindow("", "", {})
        set_title, *_ = self.on_the_hub(window)
        window.load(ORIGIN + "/", loaded=False)
        set_title(TOKEN, "TODO")
        self.assertEqual(window.titles, [])
        window.events.loaded.set()
        self.assertTrue(_wait(lambda: window.titles))
        self.assertEqual(window.titles, ["TODO"])

    def test_a_call_before_the_first_load_ends_is_refused_at_once(self):
        window = FakeWindow("", "", {})
        set_title, notify, _ = desktop.bridge(window, ORIGIN, TOKEN)
        window.load(ORIGIN + "/", loaded=False)
        _at_once(self, set_title, TOKEN, "TODO")
        self.assertFalse(_at_once(self, notify, TOKEN, "TODO", "body"))
        window.events.loaded.set()
        self.assertTrue(_wait(lambda: window.titles))
        # Refusé, le titre n'a pas été gardé : la page garde le titre de
        # base.
        self.assertEqual(window.titles, ["ERPLibre TODO"])

    def test_only_the_window_token_opens_the_bridge(self):
        base = self.notify_send('echo >> "${0%/*}/calls"')
        window = FakeWindow("", "", {})
        set_title, notify, _ = self.on_the_hub(window)
        other = "A" if TOKEN[0] != "A" else "B"
        forged = [
            None,
            "",
            43,
            [TOKEN],
            TOKEN[:-1],
            TOKEN + "x",
            other + TOKEN[1:],
            "é" * len(TOKEN),
            "\ud800",
            "Forged",
        ]
        with patch.object(
            desktop.hmac, "compare_digest", wraps=hmac.compare_digest
        ) as compare:
            for token in forged:
                set_title(token, "Forged")
                self.assertFalse(notify(token, "Forged", "body"), token)
            self.assertTrue(notify(TOKEN, "TODO", "body"))
        self.assertTrue(compare.called)
        self.assertEqual(window.titles, [])
        self.assertEqual((base / "calls").read_text(), "\n")
        with self.assertRaises(ValueError):
            desktop.bridge(FakeWindow("", "", {}), ORIGIN, "")

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
        set_title, notify, _ = desktop.bridge(window, ORIGIN, TOKEN)
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
            # Le jeton n'y suffit pas : la page n'est pas celle du hub.
            _at_once(self, set_title, TOKEN, "Forged")
            self.assertFalse(_at_once(self, notify, TOKEN, "Forged", "body"))
        self.assertEqual(window.loads, [ORIGIN + "/"] * len(foreign))
        self.assertEqual(window.titles, [])
        self.assertFalse((base / "calls").exists())
        # De retour sur le hub, la page retrouve le pont.
        window.load(ORIGIN + "/")
        self.assertTrue(_wait(lambda: window.titles))
        self.assertTrue(notify(TOKEN, "TODO", "body"))

    def test_a_call_held_across_the_redirect_is_refused(self):
        """Le garde renvoie une page étrangère au hub par `load_url`, qui
        baisse `loaded` et fait de l'URL du hub la courante avant que la
        page étrangère ne cesse de tourner. Un appel qu'elle envoie alors
        est refusé sur-le-champ, jeton ou non : il n'attend pas le hub pour
        être jugé sur son URL, et son titre n'est pas gardé."""
        base = self.notify_send('echo >> "${0%/*}/calls"')
        window = FakeWindow("", "", {})
        set_title, notify, _ = self.on_the_hub(window)
        window.load("file:///forged.html")
        self.assertTrue(_wait(lambda: window.loads))
        self.assertEqual(window.current, ORIGIN + "/")
        for token in ("Forged", TOKEN):
            self.assertFalse(_at_once(self, notify, token, "Forged", "x"))
            _at_once(self, set_title, token, "Forged")
        window.load(ORIGIN + "/")
        self.assertTrue(_wait(lambda: window.titles))
        self.assertEqual(window.titles, ["ERPLibre TODO"])
        self.assertFalse((base / "calls").exists())

    def test_a_failed_page_check_leaves_the_bridge_closed_and_logged(self):
        # Sortie d'erreur du processus de la fenêtre : son journal.
        base = self.notify_send('echo >> "${0%/*}/calls"')
        window = FakeWindow("", "", {})
        _, notify, _ = desktop.bridge(window, ORIGIN, TOKEN)
        err = io.StringIO()
        with (
            patch.object(window, "set_title", side_effect=RuntimeError("x")),
            contextlib.redirect_stderr(err),
        ):
            window.load(ORIGIN + "/")
            self.assertTrue(_wait(err.getvalue))
        self.assertEqual(
            err.getvalue(), "desktop window: page check failed: RuntimeError\n"
        )
        self.assertFalse(notify(TOKEN, "TODO", "body"))
        self.assertFalse((base / "calls").exists())

    def test_a_foreign_document_reaches_nothing_before_before_load(self):
        """Le canal qui porte les fonctions exposées écoute toute page dès
        son premier script ; seul `before_load` referme le pont, au
        chargement fini. Une page étrangère qui l'atteint avant ce signal,
        `hub` encore vrai du chargement précédent, ne trouve donc rien."""
        window = FakeWindow("", "", {})
        set_title, notify, _ = self.on_the_hub(window)
        window.current = "http://forged.invalid/"
        self.assertFalse(notify(TOKEN, "Forged", "body"))
        set_title(TOKEN, "Forged")
        self.assertEqual(window.titles, [])

    def test_the_page_notifies_once_a_second_at_most(self):
        base = self.notify_send('echo >> "${0%/*}/calls"')
        _, notify, _ = self.on_the_hub(FakeWindow("", "", {}))
        clock = [1000.0]
        with patch.object(
            desktop.time, "monotonic", side_effect=lambda: clock[0]
        ):
            self.assertTrue(notify(TOKEN, "TODO", "first"))
            clock[0] += desktop.NOTIFY_INTERVAL / 2
            self.assertFalse(notify(TOKEN, "TODO", "too soon"))
            clock[0] += desktop.NOTIFY_INTERVAL / 2
            self.assertTrue(notify(TOKEN, "TODO", "later"))
        self.assertEqual((base / "calls").read_text(), "\n\n")

    def test_the_system_dialog_picks_a_file_or_a_directory(self):
        fake = _fake_webview(self)
        window = FakeWindow("", "", {})
        _, _, pick_path = self.on_the_hub(window)
        window.dialogs = [
            ("/srv/forged.zip",),
            ("/srv/forged_dir",),
            "/srv/forged.zip",
            (),
            None,
        ]
        self.assertEqual(pick_path(TOKEN, "/srv", False), "/srv/forged.zip")
        self.assertEqual(pick_path(TOKEN, "/srv", True), "/srv/forged_dir")
        # Un chemin rendu seul, hors d'un tuple, vaut aussi ; un tuple vide
        # ne choisit rien.
        self.assertEqual(pick_path(TOKEN, "/srv", False), "/srv/forged.zip")
        self.assertIsNone(pick_path(TOKEN, "/srv", False))
        # Renoncé ; un départ qui n'est pas un texte ouvre sans répertoire.
        self.assertIsNone(pick_path(TOKEN, 43, "true"))
        self.assertEqual(
            window.opened,
            [
                (fake.OPEN_DIALOG, "/srv"),
                (fake.FOLDER_DIALOG, "/srv"),
                (fake.OPEN_DIALOG, "/srv"),
                (fake.OPEN_DIALOG, "/srv"),
                (fake.OPEN_DIALOG, ""),
            ],
        )

    def test_the_system_dialog_needs_the_token_and_the_hub(self):
        _fake_webview(self)
        window = FakeWindow("", "", {})
        _, _, pick_path = desktop.bridge(window, ORIGIN, TOKEN)
        window.dialogs = [("/srv/forged.zip",)]
        # Pendant le premier chargement, avant la page du hub.
        window.load(ORIGIN + "/", loaded=False)
        self.assertIsNone(_at_once(self, pick_path, TOKEN, "/srv", False))
        window.events.loaded.set()
        self.assertTrue(_wait(lambda: window.titles))
        for token in (None, "", 43, "Forged", TOKEN[:-1], TOKEN + "x"):
            self.assertIsNone(pick_path(token, "/srv", False), token)
        # Une page étrangère, jeton compris.
        window.load("file:///forged.html")
        self.assertTrue(_wait(lambda: window.loads))
        self.assertIsNone(_at_once(self, pick_path, TOKEN, "/srv", False))
        self.assertEqual(window.opened, [])

    def test_one_system_dialog_at_a_time(self):
        _fake_webview(self)
        window = FakeWindow("", "", {})
        _, _, pick_path = self.on_the_hub(window)
        window.dialogs = [("/srv/first.zip",), ("/srv/second.zip",)]
        window.hold = threading.Event()
        first = []
        thread = threading.Thread(
            target=lambda: first.append(pick_path(TOKEN, "/srv", False))
        )
        thread.start()
        self.assertTrue(_wait(lambda: window.opened))
        self.assertIsNone(_at_once(self, pick_path, TOKEN, "/srv", False))
        window.hold.set()
        thread.join(5)
        self.assertEqual(first, ["/srv/first.zip"])
        self.assertEqual(pick_path(TOKEN, "/srv", False), "/srv/second.zip")
        self.assertEqual(len(window.opened), 2)

    def test_a_page_loaded_under_the_dialog_gets_no_path(self):
        """Le dialogue est modal et peut durer : le chemin choisi ne va
        qu'à la page qui l'a demandé, ni à une page étrangère chargée
        entre-temps, ni à une nouvelle page du hub."""
        _fake_webview(self)
        window = FakeWindow("", "", {})
        _, _, pick_path = self.on_the_hub(window)

        def under_the_dialog(load):
            """Ce que rend un dialogue pendant lequel `load()` charge une
            page."""
            window.dialogs = [("/srv/forged.zip",)]
            window.hold = threading.Event()
            opened, chosen = len(window.opened), []
            thread = threading.Thread(
                target=lambda: chosen.append(pick_path(TOKEN, "/srv", False))
            )
            thread.start()
            self.assertTrue(_wait(lambda: len(window.opened) > opened))
            load()
            window.hold.set()
            thread.join(5)
            return chosen

        def foreign():
            window.load("file:///forged.html")
            self.assertTrue(_wait(lambda: window.loads))

        def reload():
            window.titles.clear()
            window.load(ORIGIN + "/#view=sessions")
            self.assertTrue(_wait(lambda: window.titles))

        self.assertEqual(under_the_dialog(foreign), [None])
        reload()
        self.assertEqual(under_the_dialog(reload), [None])
        self.assertEqual(len(window.opened), 2)

    def test_a_failing_system_dialog_answers_none_and_is_logged(self):
        _fake_webview(self)
        window = FakeWindow("", "", {})
        _, _, pick_path = self.on_the_hub(window)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(pick_path(TOKEN, "/srv", False))
        self.assertEqual(
            err.getvalue(), "desktop window: file dialog failed: IndexError\n"
        )
        # Sans pywebview, rien ne s'ouvre ni ne se dit en échec ; le
        # dialogue suivant peut s'ouvrir.
        quiet = io.StringIO()
        with (
            patch.dict(sys.modules, {"webview": None}),
            contextlib.redirect_stderr(quiet),
        ):
            self.assertIsNone(pick_path(TOKEN, "/srv", False))
        self.assertEqual(quiet.getvalue(), "")
        self.assertEqual(len(window.opened), 1)
        window.dialogs = [("/srv/forged.zip",)]
        self.assertEqual(pick_path(TOKEN, "/srv", False), "/srv/forged.zip")

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
        [secret] = fragment["bridge"]
        self.assertEqual(
            (fragment["view"], fragment["lang"]), (["telemetry"], ["en"])
        )
        self.assertGreaterEqual(len(secret), 43)
        # Le hub a été lancé ici : un argv existe, sans le code ni le jeton.
        self.assertEqual(popen.call_count, 1)
        self.assertNotIn(code, repr(popen.call_args))
        self.assertNotIn(secret, repr(popen.call_args))
        port = launcher.status(REPO)["port"]
        self.assertTrue(window.url.startswith(f"http://127.0.0.1:{port}/#"))
        self.assertEqual(_login(port, code), 200)
        self.assertEqual(window.title, "ERPLibre TODO")
        # Trois fonctions exposées par leur nom, aucun js_api : un chemin
        # pointé venu de la page n'atteint rien.
        self.assertNotIn("js_api", window.options)
        self.assertEqual(
            sorted(func.__name__ for func in window.exposed),
            ["notify", "pick_path", "set_title"],
        )
        for name in (
            "_window.gui.os.system",
            "set_title.__globals__.__setitem__",
            "__class__.__init__.__globals__.__setitem__",
        ):
            self.assertIsNone(_resolve(window, name), name)
        # Le jeton du fragment ouvre le pont de cette fenêtre ; aucun
        # fichier ne le porte, et la fenêtre suivante en tire un autre.
        set_title = _resolve(window, "set_title")
        window.load(f"http://127.0.0.1:{port}/")
        self.assertTrue(_wait(lambda: window.titles))
        set_title(secret, "TODO")
        self.assertEqual(window.titles, ["ERPLibre TODO", "TODO"])
        for path in self.base.rglob("*"):
            if path.is_file():
                self.assertNotIn(secret.encode(), path.read_bytes(), path)
        self.assertEqual(desktop.open_window(REPO, lang="en"), 0)
        other = parse_qs(urlsplit(self.webview.windows[-1].url).fragment)
        self.assertNotEqual(other["bridge"], [secret])
        [options, _] = self.webview.starts
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

    def fallback(self, *argv, lang="en", out=None, headless=False):
        """`main(["open", *argv])` quand il retombe sur le navigateur :
        rend les lignes de sa sortie d'erreur, puis celles de sa sortie
        (`out`, un tuyau par défaut) ; le lanceur est simulé, et la page
        s'ouvre dans un navigateur, ou, `headless`, n'a pas d'affichage."""
        page = launcher.OpenResult(
            ORIGIN + "/", ORIGIN + "/#login=forged", not headless, headless
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

    def test_without_a_display_main_prints_the_address(self):
        # Aucun navigateur ne s'ouvre sans affichage : l'adresse, et sur un
        # terminal le tunnel et le lien, sont ce que `main` offre.
        os.environ.pop("DISPLAY")
        lines, out = self.fallback("--root", str(REPO), headless=True)
        self.assertEqual(
            lines,
            ["no display on this host", "printing the page's address instead"],
        )
        self.assertEqual(out, [f"url: {ORIGIN}/"])
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


class TestBrowser(unittest.TestCase):
    """`_browser`, le repli de `main`, le lanceur simulé."""

    def browse(self, out, **launch):
        """Code de `_browser`, puis les lignes de ses sorties d'erreur et
        standard ; `launch` configure `launcher.open_page`."""
        err = io.StringIO()
        with (
            patch.object(launcher, "open_page", **launch) as open_page,
            contextlib.redirect_stderr(err),
            contextlib.redirect_stdout(out),
        ):
            code = desktop._browser(REPO, "telemetry", "en")
        open_page.assert_called_once_with(REPO, view="telemetry", lang="en")
        return code, err.getvalue().splitlines(), out.getvalue().splitlines()

    def test_a_hub_that_does_not_start_is_reported(self):
        failure = launcher.LaunchError(
            "the web hub did not start", "forged failure"
        )
        code, err, out = self.browse(Terminal(), side_effect=failure)
        self.assertEqual(code, 1)
        self.assertEqual(err, ["the web hub did not start", "forged failure"])
        self.assertEqual(out, [])

    def test_a_display_without_a_browser_is_no_success(self):
        # Un affichage, mais aucun navigateur n'a pris la page : NO_BROWSER,
        # que le menu de TODO lit pour en donner le lien lui-même.
        page = launcher.OpenResult(
            ORIGIN + "/", ORIGIN + "/#login=forged", False, False
        )
        code, err, out = self.browse(io.StringIO(), return_value=page)
        self.assertEqual(code, desktop.NO_BROWSER)
        self.assertEqual(err, ["no browser took the page"])
        self.assertEqual(out, [f"url: {ORIGIN}/"])
        # Aucun des codes que `main` rend déjà.
        self.assertNotIn(desktop.NO_BROWSER, (0, 1, 2))

    def test_without_a_display_a_terminal_gets_the_tunnel(self):
        page = launcher.OpenResult(
            ORIGIN + "/", ORIGIN + "/#login=forged", False, True
        )
        code, err, out = self.browse(Terminal(), return_value=page)
        self.assertEqual(code, 0)
        self.assertEqual(err, [])
        self.assertEqual(
            out,
            [
                f"url: {ORIGIN}/",
                "tunnel: ssh -L 43817:127.0.0.1:43817 <this host>",
                f"link: {ORIGIN}/#login=forged",
            ],
        )
        # Dans un journal, ni tunnel ni lien.
        _, _, out = self.browse(io.StringIO(), return_value=page)
        self.assertEqual(out, [f"url: {ORIGIN}/"])


@as_user
class TestSpawn(unittest.TestCase):
    def setUp(self):
        self.base = private_env(self.addCleanup)

    def test_the_window_process_is_detached_with_a_fixed_argv(self):
        out = self.base / "out"
        out.mkdir()
        fake = _program(
            self,
            "python",
            f'printf "%s\\n" "$@" > {out}/argv\n'
            f'echo "$TODO_LANG" > {out}/lang\n'
            f"readlink /proc/$$/fd/0 > {out}/stdin\n"
            "echo log-marker\n"
            "echo err-marker >&2\n"
            f"touch {out}/done\n"
            "exec sleep 30",
        )
        # Le journal d'un lancement précédent.
        log = desktop.log_path(REPO)
        log.write_text("stale-marker\n")
        with patch.object(launcher, "venv_python", return_value=str(fake)):
            proc = desktop.spawn(REPO, lang="en")
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        self.assertTrue(_wait((out / "done").exists))
        self.assertEqual(
            (out / "argv").read_text().splitlines(),
            ["-m", "script.todo.web.desktop", "open", "--view", "telemetry"],
        )
        self.assertEqual((out / "lang").read_text(), "en\n")
        self.assertEqual((out / "stdin").read_text(), "/dev/null\n")
        # Sa propre session : Ctrl+C dans le terminal de TODO ne l'atteint
        # pas.
        self.assertEqual(os.getsid(proc.pid), proc.pid)
        # Vidé à ce lancement, il reçoit ses deux sorties.
        self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600)
        self.assertEqual(log.read_text(), "log-marker\nerr-marker\n")
        # Fermée, la fenêtre ne reste pas zombie : personne ne l'attend ici.
        proc.kill()
        self.assertTrue(_wait(lambda: proc.returncode is not None))

    def test_root_or_a_bad_argument_starts_nothing(self):
        with (
            patch("os.geteuid", return_value=0),
            patch.object(desktop.subprocess, "Popen") as as_root,
            self.assertRaisesRegex(launcher.LaunchError, "root"),
        ):
            desktop.spawn(REPO)
        as_root.assert_not_called()
        with patch.object(desktop.subprocess, "Popen") as popen:
            with self.assertRaises(ValueError):
                desktop.spawn(REPO, view="x --root /")
            with self.assertRaises(ValueError):
                desktop.spawn(REPO, lang="de")
        popen.assert_not_called()
        self.assertFalse((self.base / "home" / ".erplibre").exists())


@as_user
class TestDesktopEntry(unittest.TestCase):
    def setUp(self):
        self.base = private_env(self.addCleanup)
        self.data = self.base / "data"
        patcher = patch.dict(os.environ, {"XDG_DATA_HOME": str(self.data)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_entry_runs_the_venv_python_from_the_checkout(self):
        ran = self.base / "ran"
        tool = _program(self, "update-desktop-database", f'echo "$@" > {ran}')
        with patch.dict(os.environ, {"PATH": str(tool.parent)}):
            path = desktop.install_entry(REPO)
        cid = paths.checkout_id(REPO)
        folder = self.data / "applications"
        self.assertEqual(path, folder / f"erplibre-todo-{cid}.desktop")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        python = launcher.venv_python(os.path.realpath(REPO))
        self.assertEqual(
            path.read_text().splitlines(),
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=ERPLibre TODO",
                f"Comment={os.path.realpath(REPO)}",
                f"TryExec={python}",
                f"Exec={python} -m script.todo.web.desktop open",
                f"Path={os.path.realpath(REPO)}",
                "Icon=applications-system",
                "Terminal=false",
                "Categories=Development;",
            ],
        )
        self.assertTrue(os.path.isabs(python))
        self.assertEqual(ran.read_text(), f"{folder}\n")

    def test_without_xdg_data_home_the_entry_goes_under_local_share(self):
        os.environ.pop("XDG_DATA_HOME")
        with patch.dict(os.environ, {"PATH": ""}):
            path = desktop.install_entry(REPO)
        home = self.base / "home" / ".local" / "share" / "applications"
        self.assertEqual(path.parent, home)

    def test_an_exec_argument_is_quoted_as_the_specification_says(self):
        self.assertEqual(
            desktop._exec_arg("/opt/erp libre/100%/a$b\\c"),
            '"/opt/erp libre/100%%/a\\\\$b\\\\\\\\c"',
        )
        self.assertEqual(desktop._exec_arg("/opt/erplibre"), "/opt/erplibre")

    def test_an_unprintable_checkout_or_root_writes_nothing(self):
        with self.assertRaises(ValueError):
            desktop.install_entry(str(self.base / "x\nExec=forged"))
        with (
            patch("os.geteuid", return_value=0),
            self.assertRaisesRegex(launcher.LaunchError, "root"),
        ):
            desktop.install_entry(REPO)
        self.assertFalse(self.data.exists())

    def test_the_make_target_installs_the_entry(self):
        out = subprocess.run(
            ["make", "-n", "-f", "conf/make.todo.Makefile"]
            + ["todo_desktop_install"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertIn("-m script.todo.web.desktop install", out)


# Le pont dans un navigateur, puis dans une fenêtre dont l'API arrive
# après le pont, avec `pywebviewready` ; une API qui échoue ; une fenêtre
# sans jeton. Puis le jeton pris au fragment et gardé par fenêtre. Enfin le
# dialogue de fichiers : une fenêtre qui l'offre, choisi puis renoncé, une
# API qui le rejette, une fenêtre sans jeton.
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
const plain = m.desktopBridge(browser, "ERPLibre TODO", null);
plain.title(["TODO"]);
plain.notify("body");
browser.dispatchEvent(new Event("pywebviewready"));
const win = new EventTarget();
const bridge = m.desktopBridge(win, "ERPLibre TODO", "tok");
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
const failing = m.desktopBridge(broken, "ERPLibre TODO", "tok");
failing.title(["TODO"]);
failing.notify("body");
const bare = new EventTarget();
bare.pywebview = {api: {set_title: record("bare"), notify: record("bare")}};
const tokenless = m.desktopBridge(bare, "ERPLibre TODO", null);
bare.dispatchEvent(new Event("pywebviewready"));
tokenless.title(["TODO"]);
tokenless.notify("body");
await new Promise((resolve) => setTimeout(resolve, 0));
// Une fenêtre : son sessionStorage, propre à l'origine et à la fenêtre.
const storage = () => {
    const items = new Map();
    return {
        getItem: (key) => items.get(key) ?? null,
        setItem: (key, value) => items.set(key, String(value)),
        items,
    };
};
const take = (target, hash) => {
    const fragment = new URLSearchParams(hash);
    const token = m.takeToken(target, fragment);
    return [token, fragment.toString()];
};
const first = {sessionStorage: storage()};
const refused = {get sessionStorage() { throw new Error("forged"); }};
const tokens = {
    first: take(first, "view=telemetry&bridge=tok&lang=en"),
    reload: take(first, "view=telemetry"),
    other: take(first, "bridge=forged"),
    stored: [...first.sessionStorage.items.values()],
    browser: take({sessionStorage: storage()}, "view=telemetry"),
    refused: take(refused, "bridge=tok"),
    none: take(refused, ""),
};
const picks = [];
const picker = new EventTarget();
picker.pywebview = {api: {pick_path: (...args) => {
    picks.push(args);
    return Promise.resolve(picks.length === 1 ? "/srv/forged.zip" : null);
}}};
const picking = m.desktopBridge(picker, "ERPLibre TODO", "tok");
const blind = m.desktopBridge(picker, "ERPLibre TODO", null);
const refusing = new EventTarget();
refusing.pywebview = {api: {
    pick_path: () => Promise.reject(new Error("forged")),
}};
const rejecting = m.desktopBridge(refusing, "ERPLibre TODO", "tok");
const pick = {
    can: [plain, picking, bridge, blind].map((one) => one.canPick()),
    chosen: [await picking.pickPath("/srv", false),
        await picking.pickPath("/srv", true)],
    refused: await rejecting.pickPath("/srv", false),
    browser: await plain.pickPath("/srv", false),
    tokenless: await blind.pickPath("/srv", false),
    picks,
};
const t = (key) => key;
console.log(JSON.stringify({
    browser: "pywebview" in browser,
    pick,
    calls,
    dropped: [dropped(browser), dropped(win)],
    tokens,
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
        # Chaque appel porte d'abord le jeton ; sans jeton, rien ne part.
        self.assertEqual(
            self.out["calls"],
            [
                ["set_title", "tok", "TODO › Execute — ERPLibre TODO"],
                ["set_title", "tok", "TODO — ERPLibre TODO"],
                ["notify", "tok", "TODO — ERPLibre TODO", "Command ended"],
                ["set_title", "tok", "ERPLibre TODO"],
            ],
        )

    def test_the_token_leaves_the_fragment_for_the_window_storage(self):
        tokens = self.out["tokens"]
        # Pris au fragment, dont il sort, puis relu du stockage au
        # rechargement, sans fragment.
        self.assertEqual(tokens["first"], ["tok", "view=telemetry&lang=en"])
        self.assertEqual(tokens["reload"], ["tok", "view=telemetry"])
        # Un lien vers le hub qui porte un autre jeton ne remplace pas celui
        # de la fenêtre.
        self.assertEqual(tokens["other"], ["tok", ""])
        self.assertEqual(tokens["stored"], ["tok"])
        # Dans un navigateur, aucun jeton ; un stockage refusé garde celui
        # du fragment pour cette page seulement.
        self.assertEqual(tokens["browser"], [None, "view=telemetry"])
        self.assertEqual(tokens["refused"], ["tok", ""])
        self.assertEqual(tokens["none"], [None, ""])

    def test_a_drop_is_refused_in_the_window_only(self):
        # Le moteur chargerait le lien ou le fichier déposé à la place de
        # la page ; un navigateur garde son comportement.
        self.assertEqual(self.out["dropped"], [False, True])

    def test_the_system_dialog_answers_in_the_window_only(self):
        pick = self.out["pick"]
        # Le navigateur, une fenêtre sans `pick_path`, une fenêtre sans
        # jeton n'offrent pas le dialogue.
        self.assertEqual(pick["can"], [False, True, False, False])
        self.assertEqual(pick["chosen"], ["/srv/forged.zip", None])
        self.assertEqual(
            pick["picks"], [["tok", "/srv", False], ["tok", "/srv", True]]
        )
        for case in ("refused", "browser", "tokenless"):
            self.assertIsNone(pick[case], case)

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
