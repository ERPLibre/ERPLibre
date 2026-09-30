#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La capture héritée : les questions de TODO passent par le port lié.

Un ScriptedPort répond et garde ce qu'on lui a demandé ; aucune question
ne lit un vrai terminal, et le navigateur de fichiers n'ouvre jamais la
boucle d'urwid. L'ordre d'import (les `ask=input` liés à l'import, le
sys.stdout d'urwid, le navigateur que todo.py importe sous son nom court)
et les menus du vrai TODO se vérifient dans un processus à part, HOME
temporaire, la capture posée avant tout import de TODO comme dans le
worker. Deux gardes lisent le code : les écrans qui numérotent sans
crochets, épinglés, et les formes que la capture ne voit pas.
"""

import ast
import builtins
import getpass
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import click
import urwid
from test_todo_ui_port import FakeLoop
from todo_web_env import private_env

from script.todo import auto_ask, todo_file_browser, todo_i18n, ui
from script.todo.todo_i18n import t
from script.todo.ui import legacy, port

REPO = Path(__file__).resolve().parent.parent

# Le vrai TODO sous la capture, dans l'ordre du worker : urwid, la
# capture, puis `import todo` en mode script. Écrit dans argv[2] ce que les
# `ask=input` liés à l'import désignent et ce que le port a vu.
REAL_TODO = r"""
import builtins, json, os, sys
import urwid
import urwid.display._posix_raw_display as raw
from script.todo import todo_i18n
from script.todo.ui import legacy, port
todo_i18n.use_lang("en")
scripted = port.ScriptedPort(json.loads(sys.argv[1]))
legacy.install(scripted)
sys.path.insert(0, os.path.join(os.getcwd(), "script", "todo"))
import todo
from script.todo import textual_setup, transform_setup
from script.vpn import vault
todo.lang_is_configured = lambda: True
legacy.wrap_menus(todo.TODO)
hooked = builtins.input
bound = {
    "transform_setup.create": transform_setup.create.__defaults__[0],
    "transform_setup.ensure": transform_setup.ensure.__defaults__[-1],
    "textual_setup.ensure": textual_setup.ensure.__defaults__[-1],
    "vault.ensure_vault": vault.VpnVault.ensure_vault.__defaults__[0],
}
report = {name: ask is hooked for name, ask in bound.items()}
browser = todo.todo_file_browser.FileBrowser.run_main_frame
report["todo_file_browser"] = browser is legacy._run_main_frame
defaults = raw.Screen.__init__.__defaults__
report["urwid"] = not any(isinstance(d, legacy.Tee) for d in defaults)
try:
    todo.TODO().run()
except EOFError:
    pass
with open(sys.argv[2], "w") as out:
    json.dump({"bound": report, "events": scripted.events}, out)
"""


# Écrans connus qui numérotent sans crochets : ils restent des questions
# texte. La liste ne fait que rétrécir : un écran neuf numérote entre
# crochets, et un écran converti en sort.
EXCEPTIONS = {
    ("script/todo/container_menu.py", "_container_install"),
    ("script/todo/database_manager.py", "download_database_backup_cli"),
    ("script/todo/qemu_access.py", "_qemu_scrcpy_tunnel"),
    ("script/todo/qemu_cache_menu.py", "_cache_sans_sudo_la_bas"),
    ("script/todo/qemu_network.py", "_qemu_network_recreate"),
    ("script/todo/todo_upgrade.py", "execute_odoo_upgrade"),
}
ASKS = {"input", "click.prompt", "click.confirm", "self.ask", "auto_ask.ask"}
NUMBERINGS = {
    "bracket": re.compile(r"^\s*\[(\d+|\{\}|[a-zA-Z]{1,3})\]\s"),
    "paren": re.compile(r"^\s*(\d+|\{\})\)\s"),
    "dot": re.compile(r"^\s*(\d+|\{\})\.\s"),
    "dash": re.compile(r"^\s*(\d+|\{\})\s+[-–]\s"),
}
# TODO et les paquets qu'il importe, qui posent des questions.
GUARDED = (
    "script/todo",
    "script/execute",
    "script/config",
    "script/analyse",
    "script/git",
    "script/odoo/migration",
    "script/proxmox",
    "script/qemu",
    "script/reverse_proxy",
    "script/vpn",
)
# Lisent sys.stdin de plein droit : auto_ask.py, que la capture remplace ;
# cache_journal.py, que TODO lance en commande derrière `tail`.
STDIN_READERS = ("script/todo/auto_ask.py", "script/qemu/cache_journal.py")
# Appels bruts de questions, par fichier de GUARDED : un compte ne fait
# que baisser. Une question neuve passe par `script.todo.ui` ; un fichier
# qui en convertit baisse son compte ici. Un fichier absent en compte 0.
RAW_PROMPTS = {
    "input",
    "click.prompt",
    "click.confirm",
    "getpass",
    "getpass.getpass",
}
RAW_CALLS = {
    "script/analyse/check_migration_quality_tui.py": 2,
    "script/odoo/migration/check_stale_scss.py": 1,
    "script/odoo/migration/smoke_public_url.py": 1,
    "script/qemu/deploy_qemu.py": 3,
    "script/qemu/network_qemu.py": 1,
    "script/todo/assistant_menu.py": 20,
    "script/todo/auto_ask.py": 2,
    "script/todo/container_menu.py": 13,
    "script/todo/database_manager.py": 16,
    "script/todo/kdbx_manager.py": 1,
    "script/todo/longtest_menu.py": 7,
    "script/todo/mail/menu.py": 20,
    "script/todo/proxmox_menu.py": 22,
    "script/todo/qemu_access.py": 14,
    "script/todo/qemu_cache_menu.py": 18,
    "script/todo/qemu_deploy.py": 31,
    "script/todo/qemu_install.py": 2,
    "script/todo/qemu_install_monitor.py": 8,
    "script/todo/qemu_manage.py": 44,
    "script/todo/qemu_menu.py": 6,
    "script/todo/qemu_network.py": 3,
    "script/todo/qemu_recover.py": 7,
    "script/todo/todo.py": 105,
    "script/todo/todo_install.py": 1,
    "script/todo/todo_telemetry.py": 1,
    "script/todo/todo_upgrade.py": 14,
    "script/todo/transform_menu.py": 6,
    "script/todo/ui/navigator.py": 1,
    "script/todo/vpn_menu.py": 16,
    "script/vpn/runner.py": 1,
    "script/vpn/vault.py": 2,
}


def _dotted(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def raw_calls(source) -> int:
    """Nombre d'appels de `source` à une fonction de RAW_PROMPTS."""
    return sum(
        isinstance(node, ast.Call) and _dotted(node.func) in RAW_PROMPTS
        for node in ast.walk(ast.parse(source))
    )


def _own_nodes(function):
    """Les nœuds de `function`, sans ceux des fonctions et classes qu'elle
    définit : chacune est son propre écran."""
    stack = list(function.body)
    while stack:
        node = stack.pop()
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
        ):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _skeleton(node) -> str:
    """Le texte d'une chaîne, `{}` à la place de chaque valeur d'une
    f-string."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) else "{}"
            for v in node.values
        )
    return ""


def screens() -> dict:
    """(fichier, fonction) -> numérotations de chaque écran de script/todo :
    une fonction qui pose une question et dont les chaînes portent des
    lignes numérotées, ou qui appelle fill_help_info (des crochets)."""
    found = {}
    for path in sorted((REPO / "script" / "todo").rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(
                function, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            asks, numberings = False, set()
            for node in _own_nodes(function):
                if isinstance(node, ast.Call):
                    name = _dotted(node.func)
                    asks = asks or name in ASKS
                    if name.endswith("fill_help_info"):
                        numberings.add("bracket")
                for line in _skeleton(node).splitlines():
                    numberings.update(
                        kind
                        for kind, pattern in NUMBERINGS.items()
                        if pattern.match(line)
                    )
            if asks and numberings:
                found[(rel, function.name)] = numberings
    return found


def blind_spots(source, rel) -> list:
    """Les formes que la capture ne voit pas : un nom importé de click,
    getpass ou builtins reste lié à l'original, et sys.stdin se lit sans
    `input`, hors STDIN_READERS. `sys.stdin.isatty()` et `.fileno()` ne
    lisent rien."""
    tree = ast.parse(source)
    harmless = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr in ("isatty", "fileno")
    }
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = {alias.name for alias in node.names}
            hooked = {
                "click": {"prompt", "confirm", "*"},
                "click.termui": {"prompt", "confirm", "*"},
                "getpass": names,
                "builtins": {"input", "*"},
                "sys": {"stdin", "__stdin__", "*"},
            }.get(node.module, set())
            if names & hooked:
                found.append(f"{rel}:{node.lineno} from {node.module} import")
        elif (
            isinstance(node, ast.Attribute)
            and node.attr in ("stdin", "__stdin__")
            and _dotted(node.value) == "sys"
            and id(node) not in harmless
            and rel not in STDIN_READERS
        ):
            found.append(f"{rel}:{node.lineno} sys.{node.attr}")
    return found


class CaptureCase(unittest.TestCase):
    def capture(self, *answers, target=None):
        """La capture liée à un ScriptedPort de `answers` (ou à `target`) ;
        la sortie, Tee compris, va dans `self.out`."""
        self.out = io.StringIO()
        self.enterContext(redirect_stdout(self.out))
        scripted = target or port.ScriptedPort(answers)
        self.addCleanup(legacy.install(scripted))
        return scripted


class TestClick(CaptureCase):
    def test_click_keeps_its_validation_loop(self):
        scripted = self.capture("forged", "4")
        self.assertEqual(click.prompt("Count", type=int), 4)
        self.assertEqual([e["text"] for e in scripted.events], ["Count: "] * 2)
        self.assertIn(
            "Error: 'forged' is not a valid integer.", self.out.getvalue()
        )

    def test_a_default_and_a_hidden_input(self):
        scripted = self.capture("", "hunter2")
        self.assertEqual(click.prompt("Mode", default="2"), "2")
        self.assertEqual(click.prompt("Password", hide_input=True), "hunter2")
        ask, secret = scripted.events
        self.assertEqual(
            (ask["kind"], ask["text"], ask["default"]),
            ("text", "Mode [2]: ", "2"),
        )
        self.assertEqual(
            (secret["kind"], secret["text"]), ("secret", "Password: ")
        )

    def test_confirm_is_a_confirmation_with_its_default(self):
        scripted = self.capture("maybe", "y", "")
        self.assertTrue(click.confirm("Go?"))
        self.assertTrue(click.confirm("Keep?", default=True))
        kinds = [(e["kind"], e["text"], e["default"]) for e in scripted.events]
        self.assertEqual(
            kinds,
            [
                ("confirm", "Go? [y/N]: ", "n"),
                ("confirm", "Go? [y/N]: ", "n"),
                ("confirm", "Keep? [Y/n]: ", "y"),
            ],
        )

    def test_cancel_is_ctrl_d_and_ctrl_c_stays_an_interrupt(self):
        self.capture(EOFError(), EOFError(), KeyboardInterrupt())
        with self.assertRaises(click.exceptions.Abort):
            click.prompt("Name")
        with self.assertRaises(EOFError):
            input("Name: ")
        with self.assertRaises(KeyboardInterrupt):
            input("Name: ")


class TestInput(CaptureCase):
    def test_answers_ending_the_prompt_make_a_confirmation(self):
        cases = [
            ("Continue anyway? (y/N): ", "n"),
            ("💬 Continue? (Y/N): ", None),
            ("Show the differences? [o/N] ", "n"),
            ("Keep it? (O/n) : ", "y"),
            ("Replace it? (y/Y): ", "n"),
            ("Run it now? [y/o/N] ", "n"),
            ("Continue? (y/n): ", None),
        ]
        scripted = self.capture(*["y"] * len(cases))
        for text, _ in cases:
            self.assertEqual(input(text), "y")
        seen = [(e["kind"], e["text"], e["default"]) for e in scripted.events]
        self.assertEqual(seen, [("confirm", text, d) for text, d in cases])

    def test_typed_confirmations_secrets_and_the_rest(self):
        scripted = self.capture("forged", "o", "hunter2", "addons_forged")
        input("Type the database name to confirm (empty to cancel): ")
        input("Tapez o pour confirmer le risque (o/N, défaut : non) : ")
        getpass.getpass("Password: ")
        input("Module name to test: ")
        kinds = [(e["kind"], e["default"]) for e in scripted.events]
        self.assertEqual(
            kinds,
            [
                ("typed", None),
                ("typed", None),
                ("secret", None),
                ("text", None),
            ],
        )


class TestAutoAsk(CaptureCase):
    def test_the_auto_mode_counts_down_to_the_default(self):
        scripted = self.capture("", "n")
        with patch.dict(os.environ, {auto_ask.ENV_ENABLED: "1"}):
            self.assertEqual(auto_ask.ask("Go? (Y/n) ", "y", 7), "y")
            self.assertEqual(auto_ask.make_ask("y", 7)("Go? (Y/n) "), "n")
        [first, _] = scripted.events
        self.assertEqual(
            (first["kind"], first["default"], first["timeout_s"]),
            ("countdown", "y", 7),
        )

    def test_otherwise_its_question_is_what_its_text_says(self):
        scripted = self.capture("", "")
        with patch.dict(os.environ, {auto_ask.ENV_ENABLED: ""}):
            self.assertEqual(auto_ask.ask("Go? (Y/n) ", "y"), "y")
            self.assertEqual(auto_ask.ask("Name: "), "")
        kinds = [(e["kind"], e["default"]) for e in scripted.events]
        self.assertEqual(kinds, [("confirm", "y"), ("text", None)])


class TestInstall(CaptureCase):
    def test_the_tee_keeps_the_end_of_what_was_printed(self):
        inner = io.StringIO()
        tee = legacy.Tee(inner)
        with patch.object(legacy, "TEE_LIMIT", 10):
            for n in range(30):
                tee.write(f"{n % 10}")
            self.assertEqual(tee.since(), "0123456789")
        self.assertEqual(len(inner.getvalue()), 30)
        tee.clear()
        self.assertEqual(tee.since(), "")
        self.assertEqual(tee.getvalue(), "0123456789" * 3)

    def test_the_terminal_port_calls_the_originals_under_the_capture(self):
        typed = []

        def fake_input(text):
            typed.append(text)
            return "forged"

        self.enterContext(patch.dict(port.ORIGINAL, input=fake_input))
        self.capture(target=port.TerminalPort())
        self.assertEqual(input("Name: "), "forged")
        self.assertEqual(click.prompt("Mode", default="2"), "forged")
        self.assertEqual(typed, ["Name: ", "Mode [2]: "])

    def test_uninstall_puts_everything_back_once(self):
        hooked = [
            (builtins, "input"),
            (getpass, "getpass"),
            (click, "prompt"),
            (click, "confirm"),
            (click.termui, "visible_prompt_func"),
            (click.termui, "hidden_prompt_func"),
            (auto_ask, "ask"),
            (todo_file_browser.FileBrowser, "run_main_frame"),
            (sys, "stdout"),
        ]
        before = [getattr(owner, name) for owner, name in hooked]
        uninstall = legacy.install(port.ScriptedPort())
        try:
            self.assertIs(ui.current().__class__, port.ScriptedPort)
            self.assertIs(sys.modules["todo_file_browser"], todo_file_browser)
            with self.assertRaises(RuntimeError):
                legacy.install(port.ScriptedPort())
        finally:
            uninstall()
        after = [getattr(owner, name) for owner, name in hooked]
        self.assertEqual(before, after)
        self.assertNotIn("todo_file_browser", sys.modules)
        self.assertIs(ui.current(), ui.TERMINAL)
        # Une seconde fois, même après une nouvelle capture : rien.
        again = legacy.install(port.ScriptedPort())
        try:
            uninstall()
            self.assertIs(builtins.input, legacy._input)
        finally:
            again()
        self.assertEqual([getattr(o, n) for o, n in hooked], before)

    def test_a_countdown_under_the_terminal_reaches_the_original(self):
        # Sans l'original gardé par `install`, TerminalPort rappellerait
        # le crochet, qui le rappellerait sans fin.
        self.enterContext(patch.dict(port.ORIGINAL))
        port.ORIGINAL.pop("auto_ask.ask", None)
        read, write = os.pipe()
        self.addCleanup(os.close, write)
        stdin = self.enterContext(os.fdopen(read))
        self.enterContext(patch.object(sys, "stdin", stdin))
        self.capture(target=port.TerminalPort())
        with patch.dict(os.environ, {auto_ask.ENV_ENABLED: "1"}):
            self.assertEqual(auto_ask.ask("Go? (Y/n) ", "y", 0.05), "y")
        self.assertIn("⏱0.05s Go? (Y/n) ", self.out.getvalue())


class TestFileBrowser(CaptureCase):
    """Un vrai FileBrowser sous la capture : la boucle d'urwid ne tourne
    plus, le port lié fait choisir le chemin, et le rappel du navigateur
    le reçoit."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = tmp.name
        Path(self.base, "forged.zip").touch()
        Path(self.base, "forged_dir").mkdir()
        self.chosen = []
        refused = AssertionError("the urwid loop ran")
        self.enterContext(patch.object(urwid, "MainLoop", side_effect=refused))

    def browse(self, callback=None, open_dir=False):
        callback = callback or self.chosen.append
        browser = todo_file_browser.FileBrowser(self.base, callback, open_dir)
        browser.run_main_frame()

    def test_the_choice_goes_to_the_callback(self):
        zipped = os.path.join(self.base, "forged.zip")
        scripted = self.capture(zipped, "forged_dir")
        self.browse()
        self.browse(open_dir=True)
        folder = os.path.join(self.base, "forged_dir")
        self.assertEqual(self.chosen, [zipped, folder])
        asked = [
            (e["kind"], e["start"], e["directory"]) for e in scripted.events
        ]
        self.assertEqual(
            asked, [("path", self.base, False), ("path", self.base, True)]
        )

    def test_giving_up_never_calls_back(self):
        # Annuler, comme Ctrl+D, ou une réponse vide : comme « q ».
        self.capture(EOFError(), "")
        self.browse()
        self.browse()
        self.assertEqual(self.chosen, [])

    def test_a_callback_that_closes_urwid_ends_quietly(self):
        # Les rappels de TodoUpgrade ferment eux-mêmes l'écran d'urwid.
        def close(path):
            self.chosen.append(path)
            todo_file_browser.exit_program()

        self.capture("forged.zip")
        self.browse(close)
        self.assertEqual(self.chosen, [os.path.join(self.base, "forged.zip")])

    def test_a_terminal_port_runs_the_urwid_browser_once(self):
        # Le mode enregistrement lie un port dérivé de TerminalPort : son
        # pick_path lance la boucle d'origine du navigateur, jamais le
        # navigateur capturé, qui le rappellerait sans fin.
        class Recording(port.TerminalPort):
            pass

        self.capture(target=Recording())
        self.enterContext(patch.object(urwid, "MainLoop", FakeLoop))
        self.enterContext(patch.object(FakeLoop, "press", "forged.zip"))
        self.browse()
        self.assertEqual(self.chosen, [os.path.join(self.base, "forged.zip")])

    def test_the_next_question_reads_a_fresh_screen(self):
        # Ce qui précède le navigateur ne fait pas un menu de la question
        # qui le suit.
        scripted = self.capture("forged.zip", "forged")
        print("[1] Stale entry")
        self.browse()
        self.assertEqual(input("Name: "), "forged")
        self.assertEqual(scripted.events[-1]["t"], "ask")
        self.assertEqual(scripted.events[-1]["kind"], "text")


class Menus:
    """Double de TODO : le format de `fill_help_info`, sous un fil
    d'Ariane, la ligne d'état `state` sous lui."""

    def fill_help_info(self, choices, state=None):
        text = "📍 TODO › Execute\n"
        if state:
            text += f"{state}\n"
        text += f"{t('Command:')}\n"
        number = 0
        for choice in choices:
            if choice.get("section"):
                text += f"\n── {choice['section']} ──\n"
                continue
            number += 1
            text += f"[{number}] {choice['prompt_description']}\n"
        return text + "[0] Back\n"


class Transcribing(port.ScriptedPort):
    """ScriptedPort qui, comme PipePort après une réponse de la page,
    écrit dans le terminal la transcription de la réponse à un menu."""

    def menu(self, view):
        answer = super().menu(view)
        print(f"{answer} → {view['items'][0]['label']}")
        return answer


class TestMenus(CaptureCase):
    def wrapped(self):
        """`Menus` dont `fill_help_info` rend un MenuText, en anglais."""
        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("en")
        original = Menus.fill_help_info
        legacy.wrap_menus(Menus)
        self.addCleanup(setattr, Menus, "fill_help_info", original)
        return Menus()

    def test_a_menu_says_whether_todo_printed_since_the_last_answer(self):
        # Ni une ligne vide, ni la transcription de la réponse, ni le texte
        # du menu lui-même : ce qu'une feuille imprime avant de rendre la
        # main à son menu, que les boutons ne montrent pas.
        text = self.wrapped().fill_help_info(
            [{"prompt_description": "Test a module"}]
        )
        main = "📍 TODO\nCommand:\n[1] Execute\n[0] Quit\n: "
        scripted = self.capture(target=Transcribing(["1"] * 7))
        click.prompt(text)
        print()
        click.prompt(text)
        print("Module name is required!")
        click.prompt(text)
        print("Command not found !")
        input(main)
        input(main)
        print("📍 TODO › Test\n[1] Module")
        input("[0] Back: ")
        print("Compiling...\n📍 TODO › Test\n[1] Module")
        input("[0] Back: ")
        self.assertEqual(
            [(e["source"], e["printed"]) for e in scripted.events],
            [
                ("fill_help_info", False),
                ("fill_help_info", False),
                ("fill_help_info", True),
                ("text", True),
                ("text", False),
                ("text", False),
                ("text", True),
            ],
        )

    def test_a_menu_carries_the_lines_its_buttons_do_not_say(self):
        # La ligne d'état sous le fil d'Ariane, une ligne à crochets qui
        # n'est pas une entrée ; ni le fil, ni les sections, ni les
        # entrées, ni « Command: », ni l'invite « : ».
        menus = self.wrapped()
        choices = [{"section": "Web"}, {"prompt_description": "Stop"}]
        scripted = self.capture("0", "0", "0")
        click.prompt(menus.fill_help_info(choices, state="Forged state: on"))
        click.prompt(menus.fill_help_info(choices))
        input(
            "📍 TODO\nCommand:\n  [Enter] Nothing\n[1] Execute\n[0] Quit\n: "
        )
        self.assertEqual(
            [e["notes"] for e in scripted.events],
            [["Forged state: on"], [], ["[Enter] Nothing"]],
        )

    def test_the_rest_of_a_label_on_two_lines_is_no_note(self):
        # La suite du libellé d'une entrée est dans son bouton : la redire
        # en note la montrerait deux fois. La ligne d'état reste une note.
        choices = [
            {"prompt_description": "Two\nlines"},
            {"prompt_description": "Stop"},
        ]
        scripted = self.capture("0")
        click.prompt(
            self.wrapped().fill_help_info(choices, state="Forged state: on")
        )
        [menu] = scripted.events
        self.assertEqual(menu["items"][0]["label"], "Two\nlines")
        self.assertEqual(menu["notes"], ["Forged state: on"])

    def test_a_menu_text_prompt_gives_its_exact_entries(self):
        choices = [
            {"section": "Development"},
            {"prompt_description": "Code - tools"},
            {"prompt_description": "Two\nlines"},
            {"section": "Data"},
            {"prompt_description": "Database"},
        ]
        plain = Menus().fill_help_info(choices)
        original = Menus.fill_help_info
        legacy.wrap_menus(Menus)
        self.addCleanup(setattr, Menus, "fill_help_info", original)
        text = Menus().fill_help_info(choices)
        self.assertEqual(str(text), plain)
        scripted = self.capture("2")
        self.assertEqual(click.prompt(text), "2")
        [menu] = scripted.events
        self.assertEqual(
            (menu["t"], menu["source"], menu["text"]),
            ("menu", "fill_help_info", plain + ": "),
        )
        self.assertEqual(menu["crumbs"], ["TODO", "Execute"])
        self.assertEqual(menu["sections"], ["Development", "Data"])
        self.assertEqual(
            [(i["key"], i["label"], i["section"]) for i in menu["items"]],
            [
                ("1", "Code - tools", "Development"),
                ("2", "Two\nlines", "Development"),
                ("3", "Database", "Data"),
                ("0", "Back", None),
            ],
        )

    def test_a_printed_bracket_screen_is_a_menu_until_it_is_answered(self):
        scripted = self.capture("1", "addons_forged")
        print("[7] output of an earlier command")
        print("📍 TODO › Test\n\n── Odoo ──\n[1] Module\n  [2] Coverage")
        # L'invite suit la dernière entrée sur sa ligne, comme sous click.
        self.assertEqual(input("[0] Back: "), "1")
        input("Module name to test: ")
        menu, ask = scripted.events
        self.assertEqual((menu["t"], menu["source"]), ("menu", "text"))
        self.assertEqual(menu["crumbs"], ["TODO", "Test"])
        self.assertEqual(
            [(i["key"], i["label"], i["section"]) for i in menu["items"]],
            [
                ("1", "Module", "Odoo"),
                ("2", "Coverage", "Odoo"),
                ("0", "Back", "Odoo"),
            ],
        )
        self.assertEqual((ask["t"], ask["kind"]), ("ask", "text"))

    def test_without_a_crumb_only_the_block_ending_at_the_prompt_counts(self):
        earlier = "Compiling...\n[1] 48213\nsome log line\n"
        self.assertIsNone(legacy.read_screen(earlier + "Database name: "))
        scripted = self.capture("forged", "2", "0")
        print(earlier, end="")
        input("Database name: ")
        print(earlier + "\nWhich host?\n  [1] Local\n  [2] Address")
        input("Choice: ")
        # L'invite collée à la dernière entrée est dans le bloc.
        print(earlier + "[1] Local\n[2] Address")
        input("[0] Back: ")
        ask, menu, glued = scripted.events
        self.assertEqual((ask["t"], ask["kind"]), ("ask", "text"))
        self.assertEqual((menu["t"], menu["crumbs"]), ("menu", []))
        self.assertEqual(
            [(i["key"], i["label"]) for i in menu["items"]],
            [("1", "Local"), ("2", "Address")],
        )
        self.assertEqual([i["key"] for i in glued["items"]], ["1", "2", "0"])

    def test_notes_between_the_entries_and_the_prompt_keep_the_menu(self):
        # Un écran de qemu_deploy.py : entrées, une note au même retrait,
        # puis l'invite ; une ligne vide peut aussi les séparer.
        scripted = self.capture("1", "2")
        print("\nApplication store (graphical Ubuntu VMs):")
        print("  [1] deb (apt) *\n  [2] snap + deb")
        print("  ⚠ snap needs the store; slow under emulation.")
        input("Choice [1]: ")
        print("Interface:\n  [1] TUI form *\n  [2] Classic questions\n")
        input("Choice: ")
        store, interface = scripted.events
        self.assertEqual(
            [(i["key"], i["label"]) for i in store["items"]],
            [("1", "deb (apt) *"), ("2", "snap + deb")],
        )
        self.assertEqual([i["key"] for i in interface["items"]], ["1", "2"])
        # Ce qui n'est pas la note d'un menu : une ligne sans retrait ; des
        # entrées sans retrait, devant des notes ou une ligne vide ; une
        # note à un autre retrait que les entrées ; trois notes ; deux
        # lignes vides. Les crochets d'avant restent hors menu.
        for screen in (
            "[1] 48213\n  at step 2\nsome log line\nDatabase name: ",
            "[1] 48213\n  at step 2\n  at step 3\nDatabase name: ",
            "[a] warning: foo\n    File x.py\n    raise X\n\nContinue? ",
            "[1] 48213\n\nDatabase name: ",
            "  [1] one\n    deeper note\nChoice: ",
            "  [1] one\n  note\n  note\n  note\nChoice: ",
            "  [1] one\n\n\nChoice: ",
        ):
            with self.subTest(screen):
                self.assertIsNone(legacy.read_screen(screen))

    def test_a_screen_numbered_otherwise_stays_a_text_question(self):
        screens = [
            "1. first step\n2. second step",
            "  1) shared group\n  2) one per account",
            "1 - daily\n2 - weekly",
            "[1] forged\n2 - mixed",
        ]
        scripted = self.capture(*["1"] * len(screens))
        for screen in screens:
            print(screen)
            input("Choice: ")
        self.assertEqual([e["kind"] for e in scripted.events], ["text"] * 4)


class TestGuards(unittest.TestCase):
    def test_only_the_known_screens_number_without_brackets(self):
        found = screens()
        others = {key for key, kinds in found.items() if kinds != {"bracket"}}
        self.assertEqual(others, EXCEPTIONS)
        self.assertGreater(len(found), 2 * len(others))

    def test_no_form_escapes_the_capture(self):
        found = []
        for top in GUARDED:
            for path in sorted((REPO / top).rglob("*.py")):
                rel = path.relative_to(REPO).as_posix()
                found += blind_spots(path.read_text(encoding="utf-8"), rel)
        self.assertEqual(found, [])

    def test_raw_prompt_calls_only_decrease(self):
        counts = {}
        for top in GUARDED:
            for path in sorted((REPO / top).rglob("*.py")):
                rel = path.relative_to(REPO).as_posix()
                counts[rel] = raw_calls(path.read_text(encoding="utf-8"))
        grown = [
            f"{rel}: {count} raw calls, {RAW_CALLS.get(rel, 0)} pinned"
            for rel, count in counts.items()
            if count > RAW_CALLS.get(rel, 0)
        ]
        self.assertEqual(grown, [], "ask through script.todo.ui instead")
        lower = [
            f"{rel}: {counts.get(rel, 0)} raw calls, {pinned} pinned"
            for rel, pinned in RAW_CALLS.items()
            if counts.get(rel, 0) < pinned
        ]
        self.assertEqual(lower, [], "lower RAW_CALLS to these counts")

    def test_the_count_sees_each_raw_call(self):
        source = (
            "import click, getpass\n"
            "input('a')\nclick.prompt('b')\nclick.confirm('c')\n"
            "getpass.getpass()\nui.ask('d')\nself.input('e')\n"
        )
        self.assertEqual(raw_calls(source), 4)

    def test_the_guard_sees_each_form(self):
        forms = [
            "from click import prompt",
            "from click import confirm as ask",
            "from getpass import getpass",
            "from builtins import input",
            "from sys import stdin",
            "import sys\nline = sys.stdin.readline()",
        ]
        for source in forms:
            with self.subTest(source=source):
                self.assertEqual(len(blind_spots(source, "forged.py")), 1)
        self.assertEqual(
            blind_spots("import sys\nsys.stdin", "script/todo/auto_ask.py"), []
        )
        for call in ("isatty", "fileno"):
            source = f"import sys\nsys.stdin.{call}()"
            self.assertEqual(blind_spots(source, "forged.py"), [], source)


class TestRealTodo(unittest.TestCase):
    def real_todo(self, *answers) -> dict:
        """Ce que REAL_TODO rapporte, le vrai TODO répondu par `answers`."""
        base = private_env(self.addCleanup)
        report = base / "report.json"
        result = subprocess.run(
            [sys.executable, "-c", REAL_TODO, json.dumps(answers), report],
            cwd=REPO,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(report.read_text())

    def test_the_ask_defaults_bound_at_import_are_the_capture(self):
        seen = self.real_todo("0")
        self.assertEqual(set(seen["bound"].values()), {True}, seen["bound"])

    def test_the_menus_of_the_real_todo(self):
        # TODO › Configuration › Back › Assistant › mail › Back › Back › Quit
        seen = self.real_todo("5", "0", "3", "2", "0", "0", "0")
        menus = [
            (e["source"], e["crumbs"], [i["key"] for i in e["items"]])
            for e in seen["events"]
        ]
        self.assertEqual(
            menus,
            [
                ("fill_help_info", ["TODO"], ["1", "2", "3", "4", "5", "0"]),
                (
                    "fill_help_info",
                    ["TODO", "Configuration"],
                    ["1", "2", "3", "4", "5", "6", "0"],
                ),
                ("fill_help_info", ["TODO"], ["1", "2", "3", "4", "5", "0"]),
                ("fill_help_info", ["TODO", "Assistant"], ["1", "2", "0"]),
                (
                    "fill_help_info",
                    ["TODO", "Assistant"],
                    ["1", "2", "3", "4", "0"],
                ),
                ("fill_help_info", ["TODO", "Assistant"], ["1", "2", "0"]),
                ("fill_help_info", ["TODO"], ["1", "2", "3", "4", "5", "0"]),
            ],
        )
        quit_entry = seen["events"][0]["items"][-1]
        self.assertEqual(quit_entry["label"], "🚪 Quit")
        self.assertEqual(quit_entry["speak"], "Quit")

    def test_execute_gives_a_session_its_exact_entries(self):
        # TODO › Execute › Back › Quit : Execute passe par fill_help_info, et
        # la session reçoit ses entrées telles qu'il les numérote, sans
        # relire l'écran : [0] n'est d'aucune section.
        seen = self.real_todo("1", "0", "0")
        [execute] = [
            e for e in seen["events"] if e["crumbs"] == ["TODO", "Execute"]
        ]
        self.assertEqual(execute["source"], "fill_help_info")
        self.assertEqual(
            [i["key"] for i in execute["items"]],
            [str(n) for n in range(1, 17)] + ["0"],
        )
        self.assertEqual(len(execute["sections"]), 5)
        self.assertIsNone(execute["items"][-1]["section"])

    def test_what_a_leaf_prints_flags_the_menu_that_follows(self):
        # TODO › Execute › Test › Test a module, sans nom : « Module name is
        # required! » précède le menu Test qui revient. Back, Back, puis
        # Navigation telemetry, dont la ligne d'état est une note ; Back,
        # Quit. Le logo précède le premier menu, la bannière de Test le sien.
        seen = self.real_todo("1", "4", "1", "", "0", "0", "4", "0", "0")
        stopped = todo_i18n.translate("Web interface: stopped", "en")
        menus = [
            (e["crumbs"][-1], e["printed"], e["notes"])
            for e in seen["events"]
            if e["t"] == "menu"
        ]
        self.assertEqual(
            menus,
            [
                ("TODO", True, []),
                ("Execute", False, []),
                ("Test", True, []),
                ("Test", True, []),
                ("Execute", False, []),
                ("TODO", False, []),
                ("Navigation telemetry", False, [stopped]),
                ("TODO", False, []),
            ],
        )


if __name__ == "__main__":
    unittest.main()
