#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Rendus de référence de trois menus de TODO : l'entrée [4] (Navigation
telemetry), Configuration et Update.

Module d'aide et non fichier de tests : son nom ne commence pas par
« test_ ». `capture()` rend, en français et en anglais :
- `terminal` : pour chaque menu appelé seul, qui reçoit ANSWERS (une
  réponse vide, un numéro sans entrée, 0), ce que montre le terminal,
  réponses tapées comprises, ce que rend le menu, les clés de télémétrie
  qu'il enregistre et le nombre de sondes du hub web ;
- `session` : quand le vrai TODO, sous la capture de la session web comme
  dans le worker, suit WALK, les messages `menu` des trois menus, le fil
  d'Ariane de chaque menu traversé et les clés de télémétrie. WALK ne
  répond qu'à des menus, jamais à une feuille : une étape nomme l'entrée
  d'un sous-menu par sa clé de traduction, ou est « 0 ».
La configuration est CONFIG, les préférences celles d'un HOME vide, et le
hub web ne tourne pas (`launcher.status` rend None).

    python3 test/todo_menu_golden.py   (depuis la racine du dépôt)

réécrit GOLDEN, que test_todo_menu_golden.py compare au code courant.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import warnings
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
GOLDEN = Path(__file__).resolve().parent / "todo_menu_golden.json"
LANGS = ("en", "fr")
MENUS = ("prompt_telemetry", "prompt_configuration", "prompt_execute_update")
CRUMBS = ("Navigation telemetry", "Configuration", "Update")
ANSWERS = ("", "9", "0")
# Largeur au-delà de laquelle le fichier de référence ouvre une liste ou
# un dict, un élément par ligne.
WIDTH = 200
CONFIG = {
    "code_from_makefile": [],
    "update_from_makefile": [
        {
            "prompt_description_key": (
                "Update all erplibre_base on database test"
            ),
            "makefile_cmd": "forged_update_all",
            "database": "forged",
        },
        {"prompt_description": "Forged update", "makefile_cmd": "forged"},
    ],
}
WALK = (
    ["Configuration"],
    "0",
    ["Navigation telemetry"],
    "0",
    ["Execute"],
    ["Code - Developer tools"],
    ["Update - Update all developed staging source code"],
    "0",
    "0",
    "0",
    "0",
)

# Le vrai TODO sous la capture, dans l'ordre du worker : urwid, la
# capture, puis `import todo` en mode script. argv : la langue, WALK en
# JSON, le todo.json à lire, le fichier du rapport.
SESSION = r"""
import json, os, sys
import click
import urwid
from script.config import config_file
from script.todo import todo_i18n, todo_telemetry
from script.todo.ui import legacy, port
from script.todo.web import launcher

lang, walk, config, report = sys.argv[1:5]
todo_i18n.use_lang(lang)
config_file.CONFIG_FILE = config
config_file.CONFIG_OVERRIDE_FILE = config + ".absent"
config_file.CONFIG_OVERRIDE_PRIVATE_FILE = config + ".absent"
launcher.status = lambda root: None
keys = []
todo_telemetry.record = keys.append


class Walk(port.ScriptedPort):
    # Une étape [clé] répond l'entrée dont le libellé est t(clé) ; une
    # question qui n'est pas un menu arrête tout. Une entrée absente aussi,
    # par une EOFError qui nomme la clé, gardée dans `lost`.
    lost = None

    def _answer(self, message):
        if message["t"] != "menu" or not self.answers:
            self.answers = [EOFError(message.get("text"))]
        elif isinstance(self.answers[0], list):
            key = self.answers[0][0]
            found = [
                item["key"]
                for item in message["items"]
                if item["label"] == todo_i18n.t(key)
            ]
            if not found:
                self.lost = key
            self.answers[0] = found[0] if found else EOFError(key)
        return super()._answer(message)


scripted = Walk(json.loads(walk))
legacy.install(scripted)
sys.path.insert(0, os.path.join(os.getcwd(), "script", "todo"))
import todo
todo.lang_is_configured = lambda: True
legacy.wrap_menus(todo.TODO)
# Le rapport s'écrit aussi quand TODO sort par SystemExit.
try:
    todo.TODO().run()
except (EOFError, click.exceptions.Abort):
    pass
finally:
    with open(report, "w") as out:
        json.dump(
            {"events": scripted.events, "keys": keys, "lost": scripted.lost},
            out,
        )
"""


def _environment(base) -> dict:
    """L'environnement d'un TODO lancé à part : HOME et XDG_RUNTIME_DIR
    sous `base`, sans affichage ni canal de session web."""
    env = dict(os.environ, HOME=str(base / "home"))
    env["XDG_RUNTIME_DIR"] = str(base / "run")
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "TODO_WEB_FD", "TODO_WEB_PID"):
        env.pop(name, None)
    (base / "home").mkdir()
    (base / "run").mkdir(mode=0o700)
    return env


def terminal(method, lang) -> dict:
    """Ce que montre `TODO().<method>()`, en `lang`, quand il reçoit
    ANSWERS : `screen`, ses lignes ; `back`, ce qu'il rend ; `keys`, les
    clés de télémétrie enregistrées ; `probes`, les sondes du hub web."""
    from script.config import config_file
    from script.todo import todo_i18n
    from script.todo.todo import TODO
    from script.todo.web import launcher

    shown, answers = io.StringIO(), iter(ANSWERS)

    def typed(prompt):
        # L'invite, puis la réponse et le saut de ligne que le terminal
        # fait écho.
        answer = next(answers)
        shown.write(f"{prompt}{answer}\n")
        return answer

    with ExitStack() as stack:
        saved = todo_i18n._current_lang
        stack.callback(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang(lang)
        base = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        (base / "todo.json").write_text(json.dumps(CONFIG))
        absent = str(base / "absent.json")
        for patcher in (
            patch.dict(os.environ, {"HOME": str(base)}),
            patch.object(config_file, "CONFIG_FILE", str(base / "todo.json")),
            patch.object(config_file, "CONFIG_OVERRIDE_FILE", absent),
            patch.object(config_file, "CONFIG_OVERRIDE_PRIVATE_FILE", absent),
            patch("click.termui.visible_prompt_func", typed),
            # Un menu qui lirait le terminal bloquerait le test : `input`,
            # une question masquée (`click.prompt(hide_input=True)`,
            # `getpass`) lèvent, et l'entrée standard est vide.
            patch("builtins.input", side_effect=AssertionError("input")),
            patch(
                "click.termui.hidden_prompt_func",
                side_effect=AssertionError("hidden_prompt_func"),
            ),
            patch("getpass.getpass", side_effect=AssertionError("getpass")),
            patch.object(sys, "stdin", io.StringIO()),
        ):
            stack.enter_context(patcher)
        probe = stack.enter_context(
            patch.object(launcher, "status", return_value=None)
        )
        record = stack.enter_context(
            patch("script.todo.todo_telemetry.record")
        )
        # Les modules déplacés d'urwid avertissent quand `inspect.stack`,
        # qui dessine le fil d'Ariane, lit leur `__file__`.
        stack.enter_context(warnings.catch_warnings())
        warnings.filterwarnings(
            "ignore", r"urwid\.\S+ is moved to", DeprecationWarning
        )
        stack.enter_context(redirect_stdout(shown))
        back = getattr(TODO(), method)()
    return {
        "screen": shown.getvalue().split("\n"),
        "back": back,
        "keys": [call.args[0] for call in record.call_args_list],
        "probes": probe.call_count,
    }


def session(lang) -> dict:
    """Ce que voit la capture de la session web quand le vrai TODO, en
    `lang`, suit WALK : `crumbs`, le fil d'Ariane de chaque menu traversé ;
    `menus`, les messages `menu` des trois menus ; `keys`, les clés de
    télémétrie enregistrées. EOFError, qui nomme sa clé, pour une étape
    de WALK dont le menu n'a pas l'entrée."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        config = base / "todo.json"
        config.write_text(json.dumps(CONFIG))
        report = base / "report.json"
        result = subprocess.run(
            [sys.executable, "-c", SESSION, lang, json.dumps(WALK)]
            + [str(config), str(report)],
            cwd=REPO,
            env=_environment(base),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])
        seen = json.loads(report.read_text())
    if seen["lost"] is not None:
        raise EOFError(f"no menu entry for the WALK step {seen['lost']!r}")
    menus = [event for event in seen["events"] if event["t"] == "menu"]
    return {
        "crumbs": [" › ".join(menu["crumbs"]) for menu in menus],
        "menus": [menu for menu in menus if menu["crumbs"][-1] in CRUMBS],
        "keys": seen["keys"],
    }


def capture() -> dict:
    return {
        "terminal": {
            lang: {method: terminal(method, lang) for method in MENUS}
            for lang in LANGS
        },
        "session": {lang: session(lang) for lang in LANGS},
    }


def dump(value, depth=0) -> str:
    """JSON de `value`, clés triées : une liste ou un dict tient sur une
    ligne s'il y tient en WIDTH caractères, retrait compris ; sinon un
    élément par ligne, en retrait de deux espaces."""
    flat = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if not isinstance(value, (dict, list)) or len(flat) + depth <= WIDTH:
        return flat
    pad = "  " * (depth + 1)
    if isinstance(value, dict):
        lines = [
            f"{pad}{json.dumps(key, ensure_ascii=False)}: "
            + dump(value[key], depth + 1)
            for key in sorted(value)
        ]
        opening, closing = "{", "}"
    else:
        lines = [pad + dump(item, depth + 1) for item in value]
        opening, closing = "[", "]"
    return f"{opening}\n" + ",\n".join(lines) + f"\n{'  ' * depth}{closing}"


if __name__ == "__main__":
    GOLDEN.write_text(dump(capture()) + "\n", encoding="utf-8")
    print(GOLDEN)
