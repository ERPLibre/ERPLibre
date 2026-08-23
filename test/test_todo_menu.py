#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le menu Execute : les numéros affichés mènent-ils où ils le disent ?

Le menu est écrit deux fois — une f-string qui affiche « [7] … », et une
chaîne d'`elif status == "7"` qui dispatche. Rien ne les reliait : insérer une
entrée au milieu oblige à décaler les deux à la main, et une seule erreur
envoie l'utilisateur dans le mauvais écran sans que rien ne proteste.

Ce test relit les deux et les apparie. Il ne juge pas le contenu du menu :
ajouter, retirer ou réordonner reste libre, tant que l'affichage et le
dispatch racontent la même histoire.
"""

import ast
import re
import unittest
from pathlib import Path

TODO_PY = (
    Path(__file__).resolve().parent.parent / "script" / "todo" / "todo.py"
)

# « [12] {t("Deploy - …")} » en début de ligne, dans la f-string du menu.
RE_SHOWN = re.compile(r'^\[(\d+)\] \{t\("([^"]+)"\)\}', re.M)
# « elif status == "12": » suivi de « status = self.prompt_execute_deploy() »
RE_DISPATCH = re.compile(
    r'elif status == "(\d+)":\s*\n\s*status = self\.(\w+)\(\)'
)


def prompt_execute_source():
    """Le corps de prompt_execute(), affichage et dispatch compris."""
    source = TODO_PY.read_text(encoding="utf-8")
    start = source.index("def prompt_execute(self):")
    end = source.index("def prompt_install(self):", start)
    return source[start:end]


class TestExecuteMenuNumbering(unittest.TestCase):
    def setUp(self):
        self.body = prompt_execute_source()
        # [0] Retour est traité par le « if status == "0" » qui précède la
        # chaîne d'elif : il s'affiche mais n'a pas de branche de dispatch.
        self.shown = [
            (int(num), label)
            for num, label in RE_SHOWN.findall(self.body)
            if num != "0"
        ]
        self.dispatch = [
            (int(num), method)
            for num, method in RE_DISPATCH.findall(self.body)
        ]

    def test_the_menu_was_actually_parsed(self):
        # Si la forme du menu change, ce test doit tomber ici plutôt que de
        # déclarer « tout va bien » sur une liste vide.
        self.assertGreater(len(self.shown), 5)
        self.assertEqual(len(self.shown), len(self.dispatch))

    def test_zero_is_handled_before_the_elif_chain(self):
        self.assertIn('if status == "0":', self.body)

    def test_numbering_is_contiguous_from_one(self):
        numbers = [num for num, _ in self.shown]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_every_shown_entry_has_the_matching_dispatch(self):
        self.assertEqual(
            [num for num, _ in self.shown],
            [num for num, _ in self.dispatch],
        )

    def test_no_dispatch_branch_is_unreachable(self):
        shown = {num for num, _ in self.shown}
        for num, method in self.dispatch:
            self.assertIn(
                num,
                shown,
                f"la branche [{num}] -> {method} n'est affichée nulle part",
            )

    # Chaque entrée du menu et la méthode qu'elle DOIT atteindre, par le début
    # de son libellé. Sans cette table, le test ne vérifie que l'alignement des
    # numéros — et laisse passer le défaut même qu'une renumérotation produit :
    # une entrée qui garde son rang mais atterrit dans le mauvais écran.
    #
    # Une renumérotation, l'opération risquée, ne touche PAS cette table. Ajouter
    # ou retirer une entrée demande d'y toucher, et c'est voulu : c'est le seul
    # moment où quelqu'un doit dire où mène la nouvelle entrée.
    EXPECTED = {
        "Code": "prompt_execute_code",
        "Config": "prompt_execute_config",
        "Run": "prompt_execute_instance",
        "Test": "prompt_execute_test",
        "Process": "prompt_execute_process",
        "Database": "prompt_execute_database",
        "Analyse": "prompt_execute_analyse",
        "Git": "prompt_execute_git",
        "Doc": "prompt_execute_doc",
        "GPT code": "prompt_execute_gpt_code",
        "Automation": "prompt_execute_function",
        "Deploy": "prompt_execute_deploy",
        "Network": "prompt_execute_network",
        "Security": "prompt_execute_security",
        "Language": "_change_language",
    }

    def _entry_key(self, label):
        """« Doc - Documentation search » -> « Doc »."""
        return label.split(" - ", 1)[0].strip()

    def test_every_entry_reaches_the_method_it_names(self):
        dct_dispatch = dict(self.dispatch)
        for num, label in self.shown:
            key = self._entry_key(label)
            self.assertIn(
                key,
                self.EXPECTED,
                f"entrée [{num}] « {label} » absente de EXPECTED :"
                " déclarez où elle mène",
            )
            self.assertEqual(
                dct_dispatch.get(num),
                self.EXPECTED[key],
                f"[{num}] « {label} » mène à"
                f" {dct_dispatch.get(num)} au lieu de {self.EXPECTED[key]}",
            )

    def test_expected_table_has_no_stale_entry(self):
        # Une entrée retirée du menu doit sortir d'EXPECTED, sinon la table
        # devient un cimetière qui ne protège plus rien.
        shown_keys = {self._entry_key(label) for _, label in self.shown}
        self.assertEqual(set(self.EXPECTED) - shown_keys, set())


class TestQemuMenuNumbering(unittest.TestCase):
    """Le menu QEMU : même piège, autre forme.

    Il ne s'écrit pas en f-string mais en liste de dictionnaires, où seules les
    entrées « prompt_description » consomment un numéro — les « section » sont
    des titres. Le décalage y est donc encore moins visible à l'œil : insérer
    une entrée avant la dernière renumérote tout ce qui suit, et le dispatch ne
    proteste pas. C'est arrivé en ajoutant l'émulateur Android avant
    « List available images ».
    """

    RE_ENTRY = re.compile(
        r'"(section|prompt_description)": t\(\s*\n?\s*"([^"]+)"'
    )
    RE_DISPATCH_CALL = re.compile(
        r'(?:el)?if status == "(\d+)":\s*\n\s*(?:status = )?self\.(\w+)\('
    )

    def setUp(self):
        source = TODO_PY.read_text(encoding="utf-8")
        start = source.index("def prompt_execute_qemu(self):")
        end = source.index("def _qemu_tunnel_menu(self):", start)
        self.body = source[start:end]
        num = 0
        self.shown = []
        for kind, label in self.RE_ENTRY.findall(self.body):
            if kind == "prompt_description":
                num += 1
                self.shown.append((num, label))
        self.dispatch = [
            (int(n), m) for n, m in self.RE_DISPATCH_CALL.findall(self.body)
        ]

    def test_the_menu_was_actually_parsed(self):
        """Sur une liste vide, tout test passe : mieux vaut tomber ici."""
        self.assertGreater(len(self.shown), 10)
        self.assertEqual(len(self.shown), len(self.dispatch))

    def test_numbering_is_contiguous_from_one(self):
        self.assertEqual(
            [n for n, _ in self.shown],
            list(range(1, len(self.shown) + 1)),
        )

    def test_every_shown_entry_has_the_matching_dispatch(self):
        self.assertEqual(
            [n for n, _ in self.shown], [n for n, _ in self.dispatch]
        )

    # Où mène chaque entrée, par le début de son libellé. Une renumérotation ne
    # touche PAS cette table ; ajouter une entrée l'exige, et c'est le seul
    # moment où quelqu'un doit dire où elle mène.
    EXPECTED = {
        "Deploy VM(s)": "_qemu_deploy",
        "Preview a deployment": "_qemu_deploy",
        "Download a cloud image only": "_qemu_download_image",
        "Reopen": "_qemu_reopen_monitor",
        "List VMs": "_qemu_list_vms",
        "Show a VM IP address": "_qemu_show_ip",
        "Open the console on a VM": "_qemu_console",
        "Resize a VM disk": "_qemu_resize_disk",
        "Delete VM(s)": "_qemu_delete_vm",
        "Clean up QEMU": "_qemu_cleanup",
        "Test": "_qemu_test_vm",
        "Statistics": "_qemu_stats",
        "SSH configuration": "_qemu_ssh_config_menu",
        "Remote desktop tunnel": "_qemu_tunnel_menu",
        "Android emulator": "_qemu_emulator_menu",
        "List available images": "_qemu_list_images",
    }

    def _key(self, label):
        for key in self.EXPECTED:
            if label.startswith(key):
                return key
        return label

    def test_every_entry_reaches_the_method_it_names(self):
        dct = dict(self.dispatch)
        for num, label in self.shown:
            key = self._key(label)
            self.assertIn(
                key,
                self.EXPECTED,
                f"entrée [{num}] « {label} » absente d'EXPECTED :"
                " déclarez où elle mène",
            )
            self.assertEqual(
                dct.get(num),
                self.EXPECTED[key],
                f"[{num}] « {label} » mène à {dct.get(num)}"
                f" au lieu de {self.EXPECTED[key]}",
            )

    def test_expected_table_has_no_stale_entry(self):
        keys = {self._key(label) for _, label in self.shown}
        self.assertEqual(set(self.EXPECTED) - keys, set())


class TestMenuLabels(unittest.TestCase):
    """Toute méthode de menu doit avoir son étiquette de fil d'Ariane.

    Sans elle, `_menu_header` n'affiche pas le segment et
    `todo_telemetry.build_code_tree` traite le menu comme une COMMANDE :
    il apparaît en feuille, sous son nom de méthode brut. Trois menus en
    souffrent déjà — la liste est figée ici pour que le nombre ne grandisse
    pas, pas pour bénir ce qu'elle contient.
    """

    KNOWN_MISSING = {
        "prompt_execute_test",
        "prompt_execute_network",
        "prompt_execute_security",
    }

    def setUp(self):
        source = TODO_PY.read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
        self.labels = set()
        for node in cls.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(tg, ast.Name) and tg.id == "_MENU_LABELS"
                for tg in node.targets
            ):
                continue
            self.labels = {
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant)
            }
        self.dispatched = {
            method
            for _, method in RE_DISPATCH.findall(prompt_execute_source())
        }

    def test_menu_labels_was_parsed(self):
        self.assertIn("prompt_execute", self.labels)

    def test_analyse_menu_has_a_breadcrumb_label(self):
        self.assertIn("prompt_execute_analyse", self.labels)

    def test_no_new_menu_forgets_its_label(self):
        submenus = {
            method
            for method in self.dispatched
            if method.startswith("prompt_execute_")
        }
        missing = submenus - self.labels - self.KNOWN_MISSING
        self.assertEqual(
            missing,
            set(),
            f"menus sans étiquette dans _MENU_LABELS : {sorted(missing)}",
        )


if __name__ == "__main__":
    unittest.main()
