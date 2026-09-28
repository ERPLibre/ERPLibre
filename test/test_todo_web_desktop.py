#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le pont de la fenêtre bureautique de TODO, pywebview SIMULÉ.

Une fausse fenêtre joue les chargements de page que pywebview signale
(`before_load`, puis `loaded`) et note ce que le pont lui demande ; un faux
notify-send, seul programme du PATH, note ses arguments.
"""

import inspect
import os
import shutil
import subprocess
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from script.todo.web import desktop

ORIGIN = "http://127.0.0.1:43817"


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


def _program(test, name, body) -> Path:
    """Script shell `name` de corps `body`, seul dans un répertoire
    temporaire que le nettoyage de `test` retire."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    script = Path(tmp.name, name)
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(0o755)
    return script


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


if __name__ == "__main__":
    unittest.main()
