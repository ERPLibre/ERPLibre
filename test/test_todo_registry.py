#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le registre des menus, son navigateur, l'arbre de télémétrie qui lit
les menus déclarés, la TUI de télémétrie qui en lance les feuilles, et
les fichiers de menus de TODO.

Le navigateur tourne sur un double de TODO (`FakeTodo`), dont chaque
action, état, suffixe ou intro note son appel ; les réponses viennent de
`click.prompt` simulé, ou d'un ScriptedPort sous la capture de la session
web. L'arbre se lit dans un répertoire temporaire : un todo.py minimal,
une copie du module du registre et des fichiers de menus écrits par le
test ; rien n'y est importé. La TUI tourne sous `run_test`, sur l'arbre
de TODO et un HOME temporaire : elle rend l'action choisie sans jamais
l'appeler. Les fichiers de menus de TODO sont lus par AST, puis
importés, et les méthodes qu'ils nomment ne sont jamais appelées : seule
leur signature est liée.
"""

import ast
import asyncio
import importlib
import inspect
import io
import os
import shutil
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, call, patch

import click

from script.todo import todo_i18n, todo_telemetry
from script.todo.todo_i18n import t
from script.todo.ui import legacy, port, registry
from script.todo.ui.navigator import navigate
from script.todo.ui.registry import Entry, FromConfig, Menu, Section

REPO = Path(__file__).resolve().parent.parent
REGISTRY_PY = REPO / "script" / "todo" / "ui" / "registry.py"
MENUS_DIR = REPO / "script" / "todo" / "menus"


class FakeTodo:
    """Double de TODO : toute méthode qu'un menu nomme note son appel dans
    `calls` et rend « <nom> » ; `fill_help_info` numérote les entrées comme
    celui de TODO et note ce qu'il reçoit dans `drawn` ;
    `config_file.get_config` rend une copie de `config[clé]`, None pour
    une clé absente, et compte ses lectures dans `reads`."""

    def __init__(self, config=None):
        self.calls, self.drawn, self.reads = [], [], 0
        self.config = config or {}
        self.config_file = types.SimpleNamespace(get_config=self.get_config)

    def get_config(self, key):
        self.reads += 1
        if key not in self.config:
            return None
        return [dict(element) for element in self.config[key]]

    def fill_help_info(self, choices, state=None):
        self.drawn.append((choices, state))
        lines, number = [state] if state else [], 0
        for choice in choices:
            if choice.get("section"):
                lines.append(f"── {choice['section']} ──")
                continue
            number += 1
            key = choice.get("prompt_description_key")
            label = t(key) if key else choice["prompt_description"]
            lines.append(f"[{number}] {label}")
        return "\n".join([*lines, "[0] Back", ""])

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def method(**kwargs):
            self.calls.append((name, kwargs))
            return f"<{name}>"

        return method


def _english(test):
    saved = todo_i18n._current_lang
    test.addCleanup(setattr, todo_i18n, "_current_lang", saved)
    todo_i18n.use_lang("en")


class TestRegistry(unittest.TestCase):
    def test_a_menu_is_drawn_each_turn_or_once(self):
        self.assertEqual(Menu("forged_menu", "Forged", []).render, "each")
        Menu("forged_menu", "Forged", [], render="once")
        with self.assertRaises(ValueError):
            Menu("forged_menu", "Forged", [], render="twice")

    def test_a_declaration_is_frozen(self):
        entry = Entry("Forged", "forged_action")
        with self.assertRaises(AttributeError):
            entry.action = "other_action"


class TestNavigator(unittest.TestCase):
    def setUp(self):
        _english(self)
        self.out = self.enterContext(redirect_stdout(io.StringIO()))

    def navigate(self, menu, answers, todo=None):
        """Rend (ce que rend `navigate`, le double, les textes posés)."""
        todo = todo or FakeTodo()
        with patch("click.prompt", side_effect=answers) as prompt:
            back = navigate(todo, menu)
        return back, todo, [call.args[0] for call in prompt.call_args_list]

    def test_a_number_runs_the_entry_at_its_place(self):
        menu = Menu(
            "forged_menu",
            "Forged",
            [
                Section("Forged section"),
                Entry("First", "first_action"),
                Section("Other section"),
                Entry("Second", "second_action", kwargs={"key": "b"}),
            ],
        )
        back, todo, texts = self.navigate(menu, ["2", "1", "0"])
        self.assertIs(back, False)
        self.assertEqual(
            todo.calls, [("second_action", {"key": "b"}), ("first_action", {})]
        )
        self.assertEqual(
            texts[0],
            "── Forged section ──\n[1] First\n── Other section ──\n"
            "[2] Second\n[0] Back\n",
        )

    def test_zero_gives_back_what_the_menu_declares(self):
        for back in (None, False):
            menu = Menu("forged_menu", "Forged", [], back=back)
            self.assertIs(self.navigate(menu, ["0"])[0], back)

    def test_any_other_answer_is_not_found_and_asks_again(self):
        menu = Menu("forged_menu", "Forged", [Entry("First", "first")])
        answers = ["2", "01", " 1", "-1", "x", "0"]
        _, todo, texts = self.navigate(menu, answers)
        self.assertEqual(todo.calls, [])
        self.assertEqual(len(texts), 6)
        self.assertEqual(self.out.getvalue().count("Command not found !"), 5)

    def test_each_turn_redraws_and_rereads_the_configuration(self):
        todo = FakeTodo({"forged_list": [{"prompt_description": "One"}]})

        def grow(**kwargs):
            todo.calls.append(("grow", kwargs))
            todo.config["forged_list"].append({"prompt_description": "Two"})

        todo.grow = grow
        menu = Menu(
            "forged_menu",
            "Forged",
            [
                FromConfig("forged_list", "run_element", "element"),
                Entry("Grow", "grow"),
            ],
            state="forged_state",
        )
        _, _, texts = self.navigate(menu, ["2", "3", "0"], todo)
        self.assertEqual(
            texts,
            [
                "<forged_state>\n[1] One\n[2] Grow\n[0] Back\n",
                "<forged_state>\n[1] One\n[2] Two\n[3] Grow\n[0] Back\n",
                "<forged_state>\n[1] One\n[2] Two\n[3] Two\n[4] Grow\n"
                "[0] Back\n",
            ],
        )
        self.assertEqual(todo.reads, 3)
        self.assertEqual(
            [name for name, _ in todo.calls].count("forged_state"), 3
        )

    def test_a_configured_element_is_given_to_its_action(self):
        element = {"prompt_description_key": "Back", "makefile_cmd": "x"}
        todo = FakeTodo({"forged_list": [element]})
        menu = Menu(
            "forged_menu",
            "Forged",
            [FromConfig("forged_list", "run_element", "instance")],
        )
        _, _, texts = self.navigate(menu, ["1", "0"], todo)
        self.assertEqual(todo.calls, [("run_element", {"instance": element})])
        self.assertEqual(texts[0], "[1] 🔙 Back\n[0] Back\n")

    def test_once_draws_and_reads_once_and_the_intro_shows_once(self):
        todo = FakeTodo({"forged_list": [{"prompt_description": "One"}]})
        menu = Menu(
            "forged_menu",
            "Forged",
            [FromConfig("forged_list", "run_element", "element")],
            intro="forged_intro",
            render="once",
        )
        _, _, texts = self.navigate(menu, ["9", "1", "0"], todo)
        self.assertEqual(len(set(texts)), 1)
        self.assertEqual((len(texts), len(todo.drawn), todo.reads), (3, 1, 1))
        self.assertEqual(todo.calls[0], ("forged_intro", {}))
        self.assertEqual(
            [name for name, _ in todo.calls], ["forged_intro", "run_element"]
        )

    def test_a_suffix_is_asked_with_the_entry_kwargs(self):
        menu = Menu(
            "forged_menu",
            "Forged",
            [Entry("Pick", "pick", kwargs={"key": "k"}, suffix="pick_label")],
            intro="forged_intro",
        )
        _, todo, texts = self.navigate(menu, ["1", "0"])
        self.assertEqual(texts[0], "[1] Pick  (<pick_label>)\n[0] Back\n")
        self.assertEqual(
            todo.calls,
            [
                ("forged_intro", {}),
                ("pick_label", {"key": "k"}),
                ("pick", {"key": "k"}),
                ("pick_label", {"key": "k"}),
            ],
        )

    def test_a_list_absent_from_the_configuration_adds_no_entry(self):
        menu = Menu(
            "forged_menu",
            "Forged",
            [
                FromConfig("absent_list", "run_element", "element"),
                Entry("Last", "last"),
            ],
        )
        _, todo, texts = self.navigate(menu, ["1", "0"])
        self.assertEqual(texts[0], "[1] Last\n[0] Back\n")
        self.assertEqual(todo.calls, [("last", {})])

    def test_a_language_change_shows_at_the_next_turn(self):
        todo = FakeTodo()
        todo.speak_french = lambda: todo_i18n.use_lang("fr")
        menu = Menu("forged_menu", "Forged", [Entry("Back", "speak_french")])
        _, _, texts = self.navigate(menu, ["1", "0"], todo)
        self.assertEqual(
            texts, ["[1] 🔙 Back\n[0] Back\n", "[1] 🔙 Retour\n[0] Back\n"]
        )

    def test_an_abort_or_an_error_leaves_the_menu_as_before(self):
        # Ctrl+C ou Ctrl+D à la question (Abort de click), une action qui
        # lève : le navigateur ne rattrape rien, comme un menu écrit à la
        # main.
        menu = Menu("forged_menu", "Forged", [Entry("First", "first")])
        with self.assertRaises(click.exceptions.Abort):
            self.navigate(menu, [click.exceptions.Abort()])
        todo = FakeTodo()
        todo.first = lambda: 1 / 0
        with self.assertRaises(ZeroDivisionError):
            self.navigate(menu, ["1"], todo)

    def test_the_menu_goes_through_the_port_of_a_session(self):
        class Wrapped(FakeTodo):
            pass

        legacy.wrap_menus(Wrapped)
        scripted = port.ScriptedPort(["", "1", "0"])
        self.addCleanup(legacy.install(scripted))
        menu = Menu(
            "forged_menu",
            "Forged",
            [Section("Forged section"), Entry("First", "first_action")],
            back=None,
        )
        todo = Wrapped()
        self.assertIsNone(navigate(todo, menu))
        self.assertEqual(todo.calls, [("first_action", {})])
        menus = [e for e in scripted.events if e["t"] == "menu"]
        self.assertEqual(len(menus), 3)
        self.assertEqual(
            [(i["key"], i["label"], i["section"]) for i in menus[0]["items"]],
            [("1", "First", "Forged section"), ("0", "Back", None)],
        )
        self.assertEqual({m["source"] for m in menus}, {"fill_help_info"})


def _assert_nothing_imported(test, before, todo_dir):
    """Aucun module importé depuis `before`, un ensemble de noms de
    sys.modules, ne vient de `todo_dir`, ni n'est todo.py ou un fichier
    de menus de TODO."""
    for name in set(sys.modules) - before:
        path = str(getattr(sys.modules[name], "__file__", None) or "")
        test.assertFalse(path.startswith(str(todo_dir)), name)
        test.assertNotEqual(name, "script.todo.todo")
        test.assertFalse(name.startswith("script.todo.menus"), name)


# Un todo.py minimal : le menu principal ouvre Configuration, déclarée au
# registre, et Forged, que son code dérive.
FAKE_TODO = """\
class TODO:
    _MENU_LABELS = {
        "run": "TODO",
        "prompt_configuration": "Configuration",
        "prompt_forged": "Forged",
    }

    def run(self):
        choices = [
            {"prompt_description": t("Configuration")},
            {"prompt_description": t("Forged")},
        ]
        status = input()
        if status == "1":
            self.prompt_configuration()
        elif status == "2":
            self.prompt_forged()

    def prompt_configuration(self):
        return navigate(self, menus.CONFIGURATION)

    def prompt_forged(self):
        choices = [{"prompt_description": t("Stay")}]
        status = input()
        if status == "1":
            self.stay()
"""

FAKE_MENUS = """\
from script.todo.ui.registry import Entry, FromConfig, Menu, Section

CONFIGURATION = Menu(
    "prompt_configuration",
    "Configuration",
    [
        Section("Interface"),
        Entry("Language", "change_language", suffix="language_label"),
        Entry("Pick", "pick", kwargs={"key": "forged_key"}),
        Entry("Forged", "prompt_forged"),
        Section("Maintenance"),
        FromConfig("forged_list", "run_element", "instance"),
    ],
    back=None,
)
"""


class TestDeclaredTree(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "todo.py").write_text(FAKE_TODO)
        (self.dir / "ui").mkdir()
        shutil.copy(REGISTRY_PY, self.dir / "ui" / "registry.py")
        (self.dir / "menus").mkdir()
        self.menus_py = self.dir / "menus" / "forged.py"
        self.menus_py.write_text(FAKE_MENUS)
        (self.dir / "todo.json").write_text(
            '{"forged_list": [{"prompt_description": "Forged element"}]}'
        )

    def tree(self):
        """L'arbre de `self.dir`, lu sans rien importer : aucun module neuf
        ne vient de `self.dir`, et ni todo.py ni les menus de TODO."""
        before = set(sys.modules)
        tree = todo_telemetry.build_code_tree(self.dir / "todo.py")
        _assert_nothing_imported(self, before, self.dir)
        return tree

    def test_a_declared_menu_is_read_from_its_declaration(self):
        [configuration, forged] = self.tree()["children"]
        self.assertEqual(
            (configuration["label"], configuration["entry"]),
            ("Configuration", "Configuration"),
        )
        [language, pick, submenu, element] = configuration["children"]
        self.assertEqual(
            language,
            {
                "label": "Language",
                "is_menu": False,
                "children": [],
                "method": "change_language",
                "kwargs": {},
                "section": "Interface",
                "entry": "",
            },
        )
        self.assertEqual(
            (pick["method"], pick["kwargs"], "entry" in pick),
            ("pick", {"key": "forged_key"}, False),
        )
        # Une entrée qui ouvre un menu : son nœud, et le libellé qui l'ouvre.
        self.assertEqual(
            (submenu["label"], submenu["is_menu"], submenu["entry"]),
            ("Forged", True, "Forged"),
        )
        self.assertEqual(submenu["children"], forged["children"])
        self.assertEqual(
            element,
            {
                "label": "Forged element",
                "is_menu": False,
                "children": [],
                "method": "run_element",
                "kwargs": {
                    "instance": {"prompt_description": "Forged element"}
                },
                "section": "Maintenance",
            },
        )

    def test_a_dangerous_entry_is_marked_in_the_tree(self):
        # Une feuille ou un sous-menu déclarés `danger=True` portent
        # "danger" ; une autre entrée, `danger=False` comprise, non.
        self.menus_py.write_text(
            FAKE_MENUS.replace(
                'kwargs={"key": "forged_key"}',
                'kwargs={"key": "forged_key"}, danger=True',
            )
            .replace('"prompt_forged")', '"prompt_forged", danger=True)')
            .replace('"language_label"', '"language_label", danger=False')
        )
        [configuration, forged] = self.tree()["children"]
        [language, pick, submenu, element] = configuration["children"]
        self.assertEqual(
            [node.get("danger") for node in configuration["children"]],
            [None, True, True, None],
        )
        self.assertNotIn("danger", language)
        self.assertNotIn("danger", forged)

    def test_a_computed_value_declares_nothing(self):
        # Une valeur calculée, un mot-clé inconnu, une clé non hachable, un
        # fichier à moitié écrit, puis un littéral du mauvais type : un nom
        # de menu, une action, des kwargs, une entrée, des kwargs que JSON
        # n'écrit pas, un `danger` qui n'est pas un booléen.
        for n, text in enumerate(
            (
                "import os\n" + FAKE_MENUS.replace('"Language"', "os.sep"),
                FAKE_MENUS.replace('"Language"', 't("Language")'),
                FAKE_MENUS.replace("back=None", "forged=None"),
                FAKE_MENUS.replace('{"key": "forged_key"}', '{["key"]: 1}'),
                FAKE_MENUS + "OTHER = Menu(",
                FAKE_MENUS.replace(
                    '"prompt_configuration",', '["prompt_configuration"],'
                ),
                FAKE_MENUS.replace('"pick", kwargs', '["pick"], kwargs'),
                FAKE_MENUS.replace('{"key": "forged_key"}', "[1]"),
                FAKE_MENUS.replace('Section("Maintenance")', '"Maintenance"'),
                FAKE_MENUS.replace('"forged_key"', "{1}"),
                FAKE_MENUS.replace(
                    '"pick", kwargs', '"pick", danger=1, kwargs'
                ),
            )
        ):
            with self.subTest(case=n):
                self.assertNotEqual(text, FAKE_MENUS)
                self.menus_py.write_text(text)
                with self.assertLogs(
                    todo_telemetry.__name__, "WARNING"
                ) as logs:
                    menus = todo_telemetry._declared_menus(self.dir)
                    [configuration, _] = self.tree()["children"]
                self.assertEqual(menus, {})
                self.assertEqual(configuration["children"], [])
                # Chaque lecture nomme le fichier.
                self.assertEqual(len(logs.records), 2)
                for record in logs.records:
                    self.assertIn(str(self.menus_py), record.getMessage())

    def test_a_menu_file_that_declares_nothing_is_logged(self):
        with self.assertNoLogs(todo_telemetry.__name__, "WARNING"):
            self.assertTrue(todo_telemetry._declared_menus(self.dir))
        self.menus_py.write_text(
            FAKE_MENUS.replace('"Language"', 't("Language")')
        )
        with self.assertLogs(todo_telemetry.__name__, "WARNING") as logs:
            self.assertEqual(todo_telemetry._declared_menus(self.dir), {})
        [record] = logs.records
        self.assertEqual(
            record.getMessage(),
            f"{self.menus_py} declares no menu: "
            "ValueError: not a registry call: t('Language')",
        )

    def test_the_fields_come_from_the_registry_module(self):
        fields = todo_telemetry._registry_fields(REGISTRY_PY)
        self.assertEqual(
            fields["Menu"],
            ["name", "crumb", "entries", "state", "intro", "back", "render"],
        )
        self.assertEqual(
            fields["FromConfig"], ["config_key", "action", "kwarg"]
        )
        self.assertEqual(fields["Section"], ["key"])
        self.assertEqual(
            fields["Entry"][:4], ["key", "action", "kwargs", "suffix"]
        )


def _tree_nodes(node):
    """`node`, un nœud d'un Tree de Textual, puis tous ses descendants."""
    yield node
    for child in node.children:
        yield from _tree_nodes(child)


class TestTelemetryTui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # L'arbre de TODO réduit au menu Configuration, que déclare le
        # registre : la Liste et le Kanban n'ont que ses cartes à monter.
        tree = todo_telemetry.build_code_tree()
        cls.tree = {
            **tree,
            "children": [
                node
                for node in tree["children"]
                if node["label"] == "Configuration"
            ],
        }

    def setUp(self):
        # `load` lit les compteurs sous ~/.erplibre.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for patcher in (
            patch.dict(os.environ, {"HOME": tmp.name}),
            patch.object(
                todo_telemetry, "build_code_tree", return_value=self.tree
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        _english(self)

    def select(self, mode, methods):
        """[(action rendue, appels de `notify`), …] quand, dans la vue
        `mode` de la TUI, Entrée est pressée sur la feuille qui lance
        chaque méthode de `methods`, dans l'ordre : un relevé après
        chacune."""
        from textual.widgets import ListView, Tree

        app = todo_telemetry.run_tui(run_app=False, state={"mode": mode})
        app.notify = Mock()
        seen = []

        async def scenario():
            async with app.run_test() as pilot:
                await pilot.pause()
                for method in methods:
                    if mode == "tree":
                        tree = app.query_one("#nav", Tree)
                        [node] = [
                            node
                            for node in _tree_nodes(tree.root)
                            if (node.data or {}).get("method") == method
                        ]
                        tree.move_cursor(node)
                        tree.focus()
                    else:
                        [(view, index)] = [
                            (view, index)
                            for view in app.query(ListView)
                            for index, item in enumerate(view.children)
                            if getattr(item, "cmd_method", None) == method
                        ]
                        view.index = index
                        view.focus()
                    await pilot.pause()
                    await pilot.press("enter")
                    await pilot.pause()
                    seen.append((app._action, list(app.notify.call_args_list)))

        asyncio.run(scenario())
        return seen

    def test_a_dangerous_entry_shows_a_notice_and_launches_nothing(self):
        # Reset, déclaré dangereux, laisse la TUI ouverte, sans action ;
        # Fork, choisi ensuite, rend la sienne.
        notice = call(
            t("Dangerous command: run it from its menu."), severity="warning"
        )
        for mode in ("tree", "list", "kanban"):
            with self.subTest(mode=mode):
                self.assertEqual(
                    self.select(mode, ["_reset_preferences", "_fork_todo"]),
                    [(None, [notice]), (("_fork_todo", {}), [notice])],
                )


def _rebuilt(value):
    """L'objet du registre que décrit `value`, une valeur de `_declared` :
    un dict qui porte "type" devient l'appel de son constructeur."""
    if isinstance(value, list):
        return [_rebuilt(item) for item in value]
    if isinstance(value, dict) and "type" in value:
        fields = {k: _rebuilt(v) for k, v in value.items() if k != "type"}
        return getattr(registry, value["type"])(**fields)
    return value


def _imported_menus() -> dict:
    """{méthode: Menu} des fichiers de menus de TODO, importés ; le paquet
    lui-même, `__init__.py`, n'en déclare aucun."""
    menus = {}
    for path in sorted(MENUS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        module = importlib.import_module(f"script.todo.menus.{path.stem}")
        for value in vars(module).values():
            if isinstance(value, Menu):
                menus[value.name] = value
    return menus


class TestTodoMenuFiles(unittest.TestCase):
    def test_a_menu_file_is_registry_calls_and_literals(self):
        fields = todo_telemetry._registry_fields(REGISTRY_PY)
        paths = sorted(MENUS_DIR.glob("*.py"))
        self.assertEqual(
            [p.name for p in paths], ["__init__.py", "execute.py", "main.py"]
        )
        for path in paths:
            for stmt in ast.parse(path.read_text(encoding="utf-8")).body:
                with self.subTest(file=path.name, line=stmt.lineno):
                    if isinstance(stmt, ast.ImportFrom):
                        self.assertEqual(
                            stmt.module, "script.todo.ui.registry"
                        )
                    elif isinstance(stmt, ast.Expr):
                        self.assertIsInstance(stmt.value, ast.Constant)
                    else:
                        self.assertIsInstance(stmt, ast.Assign)
                        todo_telemetry._declared(stmt.value, fields)

    def test_the_tree_reads_what_python_imports(self):
        declared = todo_telemetry._declared_menus(REPO / "script" / "todo")
        imported = _imported_menus()
        self.assertEqual(
            sorted(imported),
            [
                "prompt_configuration",
                "prompt_execute_update",
                "prompt_telemetry",
            ],
        )
        rebuilt = {name: _rebuilt(v) for name, v in declared.items()}
        self.assertEqual(rebuilt, imported)

    def test_each_key_is_translated_in_both_languages(self):
        # Les clés du registre ne sont pas des appels de `t()` : ce test
        # tient pour elles la table de traduction.
        keys = set()
        for menu in _imported_menus().values():
            keys |= {
                item.key
                for item in menu.entries
                if isinstance(item, (Entry, Section))
            }
        self.assertGreater(len(keys), 10)
        for key in sorted(keys):
            with self.subTest(key=key):
                languages = todo_i18n.TRANSLATIONS.get(key, {})
                self.assertLessEqual({"fr", "en"}, set(languages))

    def test_each_method_named_binds_its_arguments(self):
        from script.todo.todo import TODO

        menus = _imported_menus()
        self.assertEqual(len(menus), 3)
        for menu in menus.values():
            calls = [(menu.name, {}), (menu.state, {}), (menu.intro, {})]
            for item in menu.entries:
                if isinstance(item, Entry):
                    kwargs = item.kwargs or {}
                    calls += [(item.action, kwargs), (item.suffix, kwargs)]
                elif isinstance(item, FromConfig):
                    calls.append((item.action, {item.kwarg: {}}))
            for name, kwargs in calls:
                if name is None:
                    continue
                with self.subTest(menu=menu.name, method=name):
                    method = getattr(TODO, name)
                    inspect.signature(method).bind(None, **kwargs)


if __name__ == "__main__":
    unittest.main()
