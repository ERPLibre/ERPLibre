#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les menus de TODO : les numéros affichés mènent-ils où ils le disent ?

Un menu écrit à la main l'est deux fois — une liste d'entrées que
`fill_help_info` numérote, et une chaîne d'`elif status == "7"` qui
dispatche. Rien ne les relie : insérer une entrée au milieu oblige à décaler
les deux à la main, et une seule erreur envoie l'utilisateur dans le mauvais
écran sans que rien ne proteste. `MenuCoherence` relit les deux et les
apparie. Un menu déclaré au registre n'a qu'une liste, dont la place fait le
numéro : `RegistryCoherence` vérifie où mène chaque entrée.

Ces tests ne jugent pas le contenu des menus : ajouter, retirer ou
réordonner reste libre, tant que l'affichage et le dispatch racontent la
même histoire.
"""

import ast
import io
import json
import os
import re
import tempfile
import unicodedata
import unittest
import warnings
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from script.todo.ui.registry import Entry

TODO_DIR = Path(__file__).resolve().parent.parent / "script" / "todo"
TODO_PY = TODO_DIR / "todo.py"


class MenuCoherence:
    """Socle : un menu écrit en liste de dictionnaires est-il cohérent ?

    Ce piège-là ne dépend pas du menu : seules les entrées
    « prompt_description » consomment un numéro (les « section » sont des
    titres), et le dispatch les renumérote à la main. Insérer une entrée avant
    la dernière décale tout ce qui suit sans que rien ne proteste — c'est
    arrivé en ajoutant l'émulateur Android avant « List available images ».

    Depuis que les menus vivent dans leurs propres fichiers (le refactor de
    todo.py), ce socle sert DEUX menus : QEMU/KVM et Proxmox. Un troisième
    n'aura qu'à déclarer ses quatre attributs.

    Une entrée peut aussi porter sa destination dans « method » plutôt que
    dans un « elif status » numéroté. Elle échappe alors à la renumérotation
    par construction, et EXPECTED la vérifie contre cette clé.

    À déclarer par la sous-classe : SOURCE (le fichier), ENTRY (la ligne
    « def prompt_execute_… »), END (le membre suivant, qui borne la lecture) et
    EXPECTED (où mène chaque entrée, par le début de son libellé).
    """

    SOURCE = None
    ENTRY = ""
    END = ""
    EXPECTED = {}
    MINIMUM = 10

    RE_ENTRY = re.compile(
        r'"(section|prompt_description)": t\(\s*\n?\s*"([^"]+)"'
    )
    # Les lignes de COMMENTAIRE entre le « elif » et l'appel sont sautées :
    # une entrée expliquée devenait invisible pour ce test, qui annonçait alors
    # « 18 affichées, 17 dispatchées » sans qu'aucune entrée ne manque. Un test
    # ne doit pas dépendre de l'endroit où quelqu'un met un commentaire.
    RE_DISPATCH_CALL = re.compile(
        r'(?:el)?if status == "(\d+)":\s*\n(?:\s*#.*\n)*'
        r"\s*(?:status = )?self\.(\w+)\("
    )
    # Une entrée qui porte sa destination dans « method » se dispatche seule,
    # par le repli générique. Elle n'a pas de numéro dans le code, donc aucune
    # renumérotation ne peut la désaligner : c'est le seul moyen de placer une
    # entrée codée en dur APRÈS des entrées venues de la configuration, dont
    # le nombre n'est pas connu à la lecture du source.
    RE_SELF_DISPATCH = re.compile(
        r'"prompt_description": t\(\s*\n?\s*"([^"]+)"\s*\)?,?\s*\n'
        r'\s*"method": "(\w+)"'
    )

    def setUp(self):
        source = self.SOURCE.read_text(encoding="utf-8")
        start = source.index(self.ENTRY)
        end = source.index(self.END, start)
        self.body = source[start:end]
        self.self_dispatch = dict(self.RE_SELF_DISPATCH.findall(self.body))
        num = 0
        self.shown = []
        for kind, label in self.RE_ENTRY.findall(self.body):
            if kind == "prompt_description":
                num += 1
                self.shown.append((num, label))
        self.numbered = [
            (n, label)
            for n, label in self.shown
            if label not in self.self_dispatch
        ]
        self.dispatch = [
            (int(n), m) for n, m in self.RE_DISPATCH_CALL.findall(self.body)
        ]

    def test_the_menu_was_actually_parsed(self):
        """Sur une liste vide, tout test passe : mieux vaut tomber ici."""
        self.assertGreater(len(self.shown), self.MINIMUM)
        self.assertEqual(len(self.numbered), len(self.dispatch))

    def test_numbering_is_contiguous_from_one(self):
        self.assertEqual(
            [n for n, _ in self.shown],
            list(range(1, len(self.shown) + 1)),
        )

    def test_every_shown_entry_has_the_matching_dispatch(self):
        self.assertEqual(
            [n for n, _ in self.numbered], [n for n, _ in self.dispatch]
        )

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
            atteint = self.self_dispatch.get(label, dct.get(num))
            self.assertEqual(
                atteint,
                self.EXPECTED[key],
                f"[{num}] « {label} » mène à {atteint}"
                f" au lieu de {self.EXPECTED[key]}",
            )

    def test_expected_table_has_no_stale_entry(self):
        keys = {self._key(label) for _, label in self.shown}
        self.assertEqual(set(self.EXPECTED) - keys, set())

    def test_self_dispatched_entries_name_a_real_method(self):
        """« method » est une chaîne : rien ne la relie au code sans ceci."""
        from script.todo.todo import TODO

        for label, method in self.self_dispatch.items():
            self.assertTrue(
                hasattr(TODO, method),
                f"« {label} » mène à {method}, qui n'existe pas",
            )


class TestExecuteMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Execute : seize sous-menus, en cinq sections.

    Une entrée se reconnaît au début de son libellé, avant « - » : « Doc »
    et « Docker / Podman » commencent de même.
    """

    SOURCE = TODO_PY
    ENTRY = "def prompt_execute(self):"
    END = "def prompt_install(self):"

    # Chaque entrée du menu et la méthode qu'elle DOIT atteindre. Sans cette
    # table, le test ne vérifie que l'alignement des numéros — et laisse
    # passer le défaut même qu'une renumérotation produit : une entrée qui
    # garde son rang mais atterrit dans le mauvais écran.
    #
    # Une renumérotation, l'opération risquée, ne touche PAS cette table.
    # Ajouter ou retirer une entrée demande d'y toucher, et c'est voulu :
    # c'est le seul moment où quelqu'un doit dire où mène la nouvelle entrée.
    EXPECTED = {
        "Code": "prompt_execute_code",
        "Config": "prompt_execute_config",
        "Run": "prompt_execute_instance",
        "Test": "prompt_execute_test",
        "Process": "prompt_execute_process",
        "Database": "prompt_execute_database",
        "Analyse": "prompt_execute_analyse",
        "Transform data": "prompt_execute_transform",
        "Git": "prompt_execute_git",
        "Doc": "prompt_execute_doc",
        "GPT code": "prompt_execute_gpt_code",
        "Automation": "prompt_execute_function",
        "Deploy": "prompt_execute_deploy",
        "Network": "prompt_execute_network",
        "Security": "prompt_execute_security",
        "Docker / Podman": "prompt_execute_container",
    }

    def _key(self, label):
        """« Doc - Documentation search » -> « Doc »."""
        return label.split(" - ", 1)[0].strip()


class TestLaParitéProxmox(unittest.TestCase):
    """Deux capacités du menu QEMU/KVM que le menu Proxmox offre aussi.

    Changer l'état d'une VM depuis la liste (QEMU/KVM le fait dans
    « Lister les VM »), et lancer les commandes ajoutées par todo.json.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = (TODO_DIR / "proxmox_menu.py").read_text(encoding="utf-8")

    def test_the_list_offers_to_change_the_state(self):
        self.assertIn("_pve_change_state", self.src)
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO as CLASSE

        self.assertTrue(callable(CLASSE._pve_change_state))

    def test_a_clean_shutdown_comes_before_pulling_the_plug(self):
        # « shutdown » laisse Odoo fermer ses connexions PostgreSQL ; « stop »
        # coupe le courant. L'ordre des choix est la seule chose qui le dit.
        self.assertLess(
            self.src.index("shutdown (clean)"),
            self.src.index("stop (pulls the plug)"),
        )

    def test_the_menu_reads_its_extra_commands_from_todo_json(self):
        self.assertIn('get_config("proxmox_from_makefile")', self.src)
        # Et le dispatch sait les lancer, sections non comptées.
        self.assertIn("execute_from_configuration", self.src)


class TestLesIconesDuMenuProxmox(unittest.TestCase):
    """L'icône vit DANS la chaîne traduite, et les deux langues la portent.

    Une entrée sans icône se perd dans une liste de dix-huit : l'œil s'y
    repère par le pictogramme avant de lire. Le même pictogramme dit la même
    chose partout dans l'outil — 📋 liste, 🧹 nettoie, 📊 mesure — et ce
    tableau est ce qui l'empêche de dériver d'un menu à l'autre.
    """

    ICONES = {
        "Deploy a VM on the Proxmox host": "🚀",
        "Preview a deployment (dry-run, nothing sent)": "🔍",
        "Download a cloud image on the host": "📥",
        "Reopen install monitoring (last run / history)": "📈",
        "List VMs (qm list)": "📋",
        "Show a VM IP address": "🌐",
        "Open the console on a VM": "🖥",
        "Resize a VM disk": "📐",
        "Delete VM(s)": "🗑",
        "Clean up (orphan disks)": "🧹",
        "Test a VM (open Odoo in a CLI browser)": "🧪",
        "Statistics (host and VMs)": "📊",
        "SSH configuration (~/.ssh/config, ProxyJump)": "🔑",
        "Remote desktop tunnel (VNC/RDP over SSH)": "🖥",
        "Android emulator (start, tunnel, scrcpy)": "📱",
        "List available images and their specs": "🗂",
        "Proxmox - example sequence (dry-run)": "🎬",
        "Change the Proxmox host": "🔀",
        "Host": "🏠",
    }

    def test_chaque_entree_porte_son_icone(self):
        from script.todo import todo_i18n

        for cle, icone in self.ICONES.items():
            entree = todo_i18n.TRANSLATIONS[cle]
            for langue in ("fr", "en"):
                self.assertTrue(
                    entree[langue].startswith(icone),
                    f"« {cle} » ({langue}) ne commence pas par {icone} :"
                    f" {entree[langue]}",
                )

    def test_le_menu_affiche_bien_ces_entrees(self):
        """Le tableau ci-dessus ne vaut que s'il décrit le menu RÉEL : une
        entrée renommée le laisserait figer une icône que personne ne voit."""
        src = (TODO_DIR / "proxmox_menu.py").read_text(encoding="utf-8")
        for cle in self.ICONES:
            # La chaîne SEULE : une entrée longue s'écrit « t( » sur une
            # ligne et sa chaîne sur la suivante, et chercher l'appel entier
            # ne trouverait que les courtes.
            self.assertIn(
                f'"{cle}"', src, f"« {cle} » n'est plus dans le menu"
            )


class TestLArbreDesMenus(unittest.TestCase):
    """L'écran de télémétrie lit le CODE, pas la classe assemblée.

    `build_code_tree()` parse un fichier et n'y prend que la première classe.
    Depuis le découpage, les menus QEMU/KVM et Proxmox vivent dans des mixins :
    leur colonne avait disparu de cet écran — les commandes s'exécutaient
    toujours, mais on ne pouvait plus les lancer de là ni les lire. C'est ce
    que « il manque plein d'informations qu'il y avait avant » désignait.
    """

    @classmethod
    def setUpClass(cls):
        from script.todo.todo_telemetry import build_code_tree

        cls.arbre = build_code_tree()

    def _noeud(self, libelle, noeud=None):
        noeud = noeud if noeud is not None else self.arbre
        if noeud.get("label") == libelle:
            return noeud
        for enfant in noeud.get("children") or []:
            trouve = self._noeud(libelle, enfant)
            if trouve:
                return trouve
        return None

    def test_the_tree_is_built_at_all(self):
        self.assertIsNotNone(self.arbre)

    def test_the_mixin_files_come_from_the_imports(self):
        # Lus dans les imports de todo.py : un mixin ajouté demain apparaît
        # sans qu'on pense à l'inscrire ici.
        from script.todo.todo_telemetry import _mixin_files

        noms = {f.name for f in _mixin_files(TODO_DIR / "todo.py")}
        self.assertIn("qemu_menu.py", noms)
        self.assertIn("proxmox_menu.py", noms)

    def test_the_qemu_column_carries_its_commands(self):
        noeud = self._noeud("QEMU/KVM")
        self.assertIsNotNone(noeud, "colonne QEMU/KVM absente de l'arbre")
        self.assertGreaterEqual(len(noeud.get("children") or []), 15)

    def test_the_proxmox_column_too(self):
        noeud = self._noeud("Proxmox VE")
        self.assertIsNotNone(noeud, "colonne Proxmox VE absente de l'arbre")
        self.assertGreaterEqual(len(noeud.get("children") or []), 15)

    def test_the_telemetry_entry_is_a_menu_of_four_leaves(self):
        # [4] du menu principal est un sous-menu de quatre feuilles ; les
        # autres entrées gardent leur numéro.
        noeud = self._noeud("Navigation telemetry")
        self.assertIsNotNone(noeud, "menu Navigation telemetry absent")
        self.assertTrue(noeud["is_menu"])
        self.assertEqual(
            [(f["label"], f["method"]) for f in noeud["children"]],
            [
                ("Navigation telemetry (TUI)", "_todo_telemetry_tui"),
                ("Navigation telemetry (WEB)", "_todo_telemetry_web"),
                ("Stop the web interface", "_todo_web_stop"),
                ("Desktop window", "_todo_desktop_window"),
            ],
        )
        racine = [enfant["label"] for enfant in self.arbre["children"]]
        self.assertEqual(
            racine,
            [
                "Execute",
                "Install",
                "Assistant",
                "Navigation telemetry",
                "Configuration",
            ],
        )

    def test_update_lists_each_configured_update(self):
        # Chaque entrée d'`update_from_makefile` est une feuille d'Update,
        # que lance execute_from_configuration avec l'entrée elle-même.
        config = json.loads((TODO_DIR / "todo.json").read_text())
        expected = [
            ("execute_from_configuration", {"instance": entry})
            for entry in config["update_from_makefile"]
        ]
        [update] = [
            n
            for n in self._noeud("Code")["children"]
            if n["label"] == "Update"
        ]
        leaves = [(f["method"], f["kwargs"]) for f in update["children"]]
        self.assertTrue(expected)
        self.assertEqual(leaves[: len(expected)], expected)

    def test_configuration_and_update_come_from_the_registry(self):
        # Le registre donne ce que la dérivation AST ne voit pas dans
        # `return navigate(…)` : Fork et Reset, les kwargs de _pref_edit, la
        # méthode d'Upgrade Odoo. Un libellé qui finit par un suffixe
        # calculé n'a pas d'entrée fixe.
        [configuration] = [
            n for n in self.arbre["children"] if n["label"] == "Configuration"
        ]
        self.assertEqual(
            [
                (f["label"], f["method"], f["kwargs"], f["section"])
                + ((f["entry"],) if "entry" in f else ())
                for f in configuration["children"]
            ],
            [
                ("Language / Langue", "_change_language", {}, "Interface", ""),
                (
                    "QEMU deployment interface",
                    "_pref_edit",
                    {"key": "qemu_deploy_ui"},
                    "Interface",
                    "",
                ),
                (
                    "Display while deploying",
                    "_pref_edit",
                    {"key": "qemu_deploy_progress"},
                    "Interface",
                    "",
                ),
                (
                    "Odoo migration interface",
                    "_pref_edit",
                    {"key": "migration_ui"},
                    "Interface",
                    "",
                ),
                (
                    "Fork - Open TODO in a new tab",
                    "_fork_todo",
                    {},
                    "Interface",
                ),
                (
                    "Reset all preferences",
                    "_reset_preferences",
                    {},
                    "Maintenance",
                ),
            ],
        )
        [update] = [
            n
            for n in self._noeud("Code")["children"]
            if n["label"] == "Update"
        ]
        config = json.loads((TODO_DIR / "todo.json").read_text())
        self.assertEqual(
            [
                (f["label"], f["method"], f["kwargs"])
                for f in update["children"]
            ],
            [
                (
                    e.get("prompt_description_key") or e["prompt_description"],
                    "execute_from_configuration",
                    {"instance": e},
                )
                for e in config["update_from_makefile"]
            ]
            + [
                ("Upgrade Odoo - Migration Database", "_upgrade_odoo", {}),
                ("Upgrade Poetry - Dependency of Odoo", "upgrade_poetry", {}),
            ],
        )

    def test_reset_is_the_only_dangerous_node(self):
        # Seul un nœud qui porte "danger" ne se lance ni de la TUI ni de
        # la page web.
        dangerous = []

        def walk(node, path):
            for child in node["children"]:
                here = f"{path} › {child['label']}"
                if child.get("danger"):
                    dangerous.append(here)
                walk(child, here)

        walk(self.arbre, "TODO")
        self.assertEqual(
            dangerous, ["TODO › Configuration › Reset all preferences"]
        )

    def test_a_computed_label_keeps_the_numbering(self):
        # fill_help_info numérote chaque entrée qui n'est pas une section,
        # son libellé écrit ou calculé : la troisième reste la troisième, et
        # une section au titre calculé n'en prend aucun.
        from script.todo.todo_telemetry import _choice_entries

        func = ast.parse(
            "def menu(self):\n"
            "    choices = [\n"
            '        {"section": titre},\n'
            '        {"prompt_description": parler},\n'
            '        {"prompt_description": f"{t(\'A\')}  ({x})"},\n'
            '        {"prompt_description": t("Second")},\n'
            '        {"section": t("Server")},\n'
            '        {"prompt_description_key": "Third"},\n'
            "    ]\n"
        ).body[0]
        self.assertEqual(
            _choice_entries(func),
            [
                {"label": None, "section": None},
                {"label": None, "section": None},
                {"label": "Second", "section": None},
                {"label": "Third", "section": "Server"},
            ],
        )

    def test_the_breadcrumb_names_the_proxmox_menu(self):
        # Sans étiquette, le fil d'Ariane sautait le menu Proxmox : on lisait
        # « TODO › Execute › Deploy » en étant deux niveaux plus bas.
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO as CLASSE

        self.assertIn("prompt_execute_proxmox", CLASSE._MENU_LABELS)

    def test_a_submenu_carries_the_entry_its_parent_shows(self):
        # Le fil d'Ariane dit « Code », le menu Exécution montre « Code -
        # Developer tools » : la page web cherche celle-ci pour y entrer.
        # Écrite dans une f-string « [N] {t(…)} », dans une liste
        # « choices », ou ajoutée par « choices.append ».
        code = self._noeud("Code")
        self.assertEqual(code["entry"], "Code - Developer tools")
        deploy = self._noeud("Deploy")
        [ssh] = [n for n in deploy["children"] if n["label"] == "SSH"]
        self.assertEqual(ssh["entry"], "SSH (remote host)...")
        [update] = [n for n in code["children"] if n["label"] == "Update"]
        self.assertEqual(
            update["entry"],
            "Update - Update all developed staging source code",
        )
        # Deux menus « Actions » : leurs entrées les distinguent.
        server = self._noeud("Git local server")
        self.assertEqual(
            [n["entry"] for n in server["children"]],
            [
                "Deploy a local git server (~/.git-server)",
                "Deploy a production git server (/srv/git, root required)",
            ],
        )
        # Une feuille n'en porte pas : son libellé est celui de son entrée.
        self.assertNotIn("entry", self._noeud("Show code status"))
        # Deux libellés calculés en tête du menu LLM : Search garde le sien,
        # et une feuille que son menu ne nomme pas a une entrée vide.
        llm = self._noeud("LLM")
        self.assertEqual(
            self._noeud("Search", llm)["entry"], "Search for a server…"
        )
        [gpt] = [
            n
            for n in llm["children"]
            if n.get("method") == "_llm_gpt_catalogue"
        ]
        self.assertEqual(
            (gpt["label"], gpt["entry"]), ("llm gpt catalogue", "")
        )

    def test_a_submenu_its_parent_does_not_name_has_an_empty_entry(self):
        # Le menu LLM calcule le libellé de l'entrée qui ouvre Servers : son
        # `entry` est vide, comme celui d'une feuille que son menu ne nomme
        # pas, et la page ne donne de ▶ ni à lui ni à ses feuilles.
        servers = self._noeud("Servers", self._noeud("LLM"))
        self.assertTrue(servers["is_menu"])
        self.assertEqual(servers["entry"], "")

    def test_a_computed_appended_label_is_no_command(self):
        # Le menu Servers ajoute une entrée par serveur connu, au libellé
        # calculé à l'affichage : il n'en reste que « — », qu'aucune entrée
        # ne montre. Ses deux commandes écrites restent, chacune avec sa
        # méthode, que la place de l'entrée calculée situe encore.
        from script.todo.todo_telemetry import _choices_children

        servers = self._noeud("Servers", self._noeud("LLM"))
        self.assertEqual(
            [n["label"] for n in servers["children"]],
            ["Add a server by hand", "Delete a server"],
        )
        func = ast.parse(
            "def menu(self):\n"
            "    choices = []\n"
            "    for nom in noms:\n"
            '        choices.append({"prompt_description": f"{nom} — {x}"})\n'
            '    choices.append({"prompt_description": t("Add")})\n'
            '    choices.append({"prompt_description": t("Delete")})\n'
            "    if status == str(len(choices) - 1):\n"
            "        self.add()\n"
            "    elif status == str(len(choices)):\n"
            "        self.delete()\n"
        ).body[0]
        self.assertEqual(
            _choices_children(func, TODO_DIR),
            [("Add", "add", {}), ("Delete", "delete", {})],
        )

    def test_a_computed_label_counts_for_the_entries_before_it(self):
        # Le dispatch compte depuis la fin : l'entrée calculée entre Add et
        # Delete situe Add, à « len(choices) - 2 ». Une méthode qui lui
        # répond en fait une commande, gardée avec le libellé qui en reste.
        from script.todo.todo_telemetry import _choices_children

        source = (
            "def menu(self):\n"
            "    choices = []\n"
            '    choices.append({"prompt_description": t("Add")})\n'
            "    for nom in noms:\n"
            '        choices.append({"prompt_description": f"{nom} — {x}"})\n'
            '    choices.append({"prompt_description": t("Delete")})\n'
            "    if status == str(len(choices) - 2):\n"
            "        self.add()\n"
            "    elif status == str(len(choices)):\n"
            "        self.delete()\n"
        )
        func = ast.parse(source).body[0]
        self.assertEqual(
            _choices_children(func, TODO_DIR),
            [("Add", "add", {}), ("Delete", "delete", {})],
        )
        func = ast.parse(
            source
            + "    elif status == str(len(choices) - 1):\n"
            + "        self.show()\n"
        ).body[0]
        self.assertEqual(
            _choices_children(func, TODO_DIR),
            [
                ("Add", "add", {}),
                (" — ", "show", {}),
                ("Delete", "delete", {}),
            ],
        )

    def test_a_label_that_is_not_a_string_leaves_the_tree_built(self):
        # « t(5) » n'est pas un libellé : son entrée garde son numéro, sans
        # libellé, et l'arbre se bâtit.
        import tempfile

        from script.todo.todo_telemetry import _str_of, build_code_tree

        self.assertIsNone(_str_of(ast.parse("t(5)", mode="eval").body))
        with tempfile.TemporaryDirectory() as tmp:
            todo_py = Path(tmp) / "todo.py"
            todo_py.write_text(
                "class TODO:\n"
                '    _MENU_LABELS = {"run": "TODO"}\n'
                "\n"
                "    def run(self):\n"
                "        choices = [\n"
                '            {"prompt_description": t(5)},\n'
                '            {"prompt_description": t("Second")},\n'
                "        ]\n"
                "        status = input()\n"
                '        if status == "1":\n'
                "            self.first()\n"
                '        elif status == "2":\n'
                "            self.second()\n",
                encoding="utf-8",
            )
            arbre = build_code_tree(todo_py)
        self.assertEqual(
            [(n["label"], n.get("entry")) for n in arbre["children"]],
            [("first", ""), ("Second", None)],
        )

    def test_no_submenu_entry_is_a_sibling_leaf_label(self):
        # La page répond à un menu l'entrée d'un sous-menu par ses lettres
        # et ses chiffres : une feuille voisine qui s'y réduit lancerait sa
        # commande au lieu d'ouvrir le sous-menu.
        def reduit(libelle):
            texte = unicodedata.normalize("NFD", libelle).lower()
            return "".join(
                c for c in texte if unicodedata.category(c)[0] in "LN"
            )

        def parcours(noeud):
            feuilles = {
                reduit(n["label"])
                for n in noeud["children"]
                if not n["is_menu"]
            }
            for enfant in noeud["children"]:
                if enfant["is_menu"]:
                    cle = reduit(enfant.get("entry", enfant["label"]))
                    if cle:
                        self.assertNotIn(cle, feuilles, enfant["label"])
                    parcours(enfant)

        parcours(self.arbre)

    def test_the_unit_test_entries_carry_their_pattern(self):
        # [4] › [1] lance une feuille par sa méthode et ses kwargs : sans son
        # motif, Mail unit tests y lancerait toute la suite.
        kwargs = {
            n["label"]: n.get("kwargs")
            for n in self._noeud("Test")["children"]
        }
        self.assertEqual(kwargs["ERPLibre unit tests"], {})
        self.assertEqual(
            kwargs["Mail unit tests"], {"pattern": "test_mail*.py"}
        )
        self.assertEqual(
            kwargs["Analyse unit tests"], {"pattern": "test_analyse*.py"}
        )

    def test_a_help_line_names_its_entry_once(self):
        # « [N] {t("…")} » dans une f-string ; un libellé calculé n'y entre
        # pas, ni un numéro que la méthode écrit avec deux libellés.
        from script.todo.todo_telemetry import _help_entries

        func = ast.parse(
            "def menu(self):\n"
            "    print(f\"[1] {t('One')}\\n[2] {t('Two')}\\n[3] {nom}\")\n"
            "    if autre:\n"
            "        print(f\"[1] {t('Other')}\")\n"
        ).body[0]
        self.assertEqual(_help_entries(func), {2: "Two"})


class TestQemuMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu QEMU/KVM, désormais dans script/todo/qemu_menu.py."""

    SOURCE = TODO_DIR / "qemu_menu.py"
    ENTRY = "def prompt_execute_qemu(self):"
    END = "def _qemu_stats(self):"

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
        "Recover files from a VM disk (libguestfs)": "_qemu_recover_files",
        "Diagnostics (report to share)": "_qemu_diagnostics",
        "Show the libvirt network state": "_qemu_network_status",
        "Recreate the VM subnet": "_qemu_network_recreate",
    }


class TestAnalyseMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Analyse, qui n'avait aucun garde.

    Il en a pourtant besoin plus que les autres : ses entrées sont
    regroupées en cinq sections, et une section ne consomme pas de numéro.
    Ajouter « Instance » avant la dernière entrée décalait tout ce qui
    suivait sans que rien ne proteste.
    """

    SOURCE = TODO_DIR / "todo.py"
    ENTRY = "def prompt_execute_analyse(self):"
    END = "def execute_analyse_module_package(self):"
    MINIMUM = 5

    EXPECTED = {
        "Tables and database size": "execute_analyse_schema_size",
        "Customised views": "execute_analyse_view_custom",
        "Studio and hand-made": "execute_analyse_custom_field",
        "Quality of a migration": "execute_analyse_migration_quality",
        "Modules missing": "execute_analyse_module_package",
        "Dependencies between": "execute_analyse_module_dependency",
        "Attachment files missing": "execute_analyse_filestore",
        "Monitoring - a backup": "execute_analyse_monitoring",
    }


class TestDatabaseMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Database, qui manie des bases entières.

    Il n'avait aucun garde, et c'est celui où une renumérotation coûte le
    plus cher : sa dernière entrée EFFACE une base. Insérer « Dupliquer »
    avant elle décale « Effacer » de [4] à [5] — si le dispatch ne suit
    pas, taper [4] efface au lieu de copier.
    """

    SOURCE = TODO_DIR / "todo.py"
    ENTRY = "def prompt_execute_database(self):"
    END = "def prompt_execute_analyse(self):"
    MINIMUM = 4

    # Ce menu délègue à `self.db_manager.methode()`, pas à `self.methode()`.
    # Le motif du socle ne voit que la forme courte : sans cette surcharge
    # il lit ZÉRO dispatch et ne compare plus rien — un garde qui passe au
    # vert sans rien garder.
    RE_DISPATCH_CALL = re.compile(
        r'(?:el)?if status == "(\d+)":\s*\n(?:\s*#.*\n)*'
        r"\s*(?:status = )?self\.(?:\w+\.)*(\w+)\("
    )

    EXPECTED = {
        "Create backup": "create_backup_from_database",
        "Download database": "download_database_backup_cli",
        "Restore from backup": "restore_from_database",
        "Duplicate a database": "duplicate_database",
        "Erase a database": "drop_database",
    }


class TestProxmoxMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Proxmox : dix-huit entrées, le même piège.

    Quatre d'entre elles mènent VOLONTAIREMENT à des méthodes du menu QEMU —
    c'est le même travail, et le refactor n'a pas dupliqué ce code. La table
    le dit noir sur blanc : si quelqu'un les recopiait un jour, ce test
    montrerait que la cible a changé.
    """

    SOURCE = TODO_DIR / "proxmox_menu.py"
    ENTRY = "def prompt_execute_proxmox(self):"
    END = "def _pve_fetch_image(self):"
    MINIMUM = 15

    EXPECTED = {
        "Deploy a VM on the Proxmox host": "_pve_deploy",
        "Preview a deployment": "_pve_deploy",
        "Download a cloud image on the host": "_pve_fetch_image",
        "Reopen": "_qemu_reopen_monitor",
        "List VMs (qm list)": "_pve_list",
        "Show a VM IP address": "_pve_vm_ip",
        "Open the console on a VM": "_pve_console",
        "Resize a VM disk": "_pve_resize",
        "Delete VM(s)": "_pve_delete",
        "Clean up (orphan disks)": "_pve_cleanup",
        "Test a VM": "_pve_test_vm",
        "Statistics (host and VMs)": "_pve_stats",
        "SSH configuration": "_pve_ssh_config",
        "Remote desktop tunnel": "_qemu_tunnel_menu",
        "Android emulator": "_qemu_emulator_menu",
        "List available images": "_qemu_list_images",
        "Proxmox - example sequence": "_pve_example",
        "Change the Proxmox host": "_pve_forget_host",
    }


class TestGitMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Git, le seul dont todo.json suit des entrées codées en dur.

    Ses premières entrées sont écrites à la main, les suivantes viennent de
    `git_from_makefile` et le repli générique les renumérote tout seul :
    ajouter une entrée codée en dur pousse celles de todo.json d'un rang sans
    que rien ne le dise. Une entrée codée en dur oubliée dans le dispatch
    ferait lancer la commande du voisin sous le libellé attendu.
    """

    SOURCE = TODO_DIR / "todo.py"
    ENTRY = "def prompt_execute_git(self):"
    END = "def _git_install_hooks(self):"
    MINIMUM = 2

    EXPECTED = {
        "Local git server": "prompt_execute_git_local_server",
        "Add a remote to a local repository": "_git_add_remote",
        "Install git hooks": "_git_install_hooks",
        "Set merge.conflictStyle": "_git_set_conflict_style",
        "Install Starship on Shell": "_shell_install_starship",
        "Install Claude Code": "_shell_install_claude_code",
        "Install opencode": "_shell_install_opencode",
    }


class RegistryCoherence:
    """Socle : un menu déclaré au registre mène-t-il où il le dit ?

    Le numéro d'une entrée est sa place dans la déclaration : affichage et
    dispatch ne peuvent pas se désaligner. Reste à dire où mène chaque
    entrée, par le début de sa clé, et c'est EXPECTED, qu'ajouter une
    entrée oblige à compléter. À déclarer par la sous-classe : MENU (la
    méthode de TODO qui ouvre le menu), EXPECTED et BACK (ce que rend [0]).
    """

    MENU = ""
    EXPECTED = {}
    BACK = False

    def setUp(self):
        from script.todo.todo import TODO

        opened = []
        with patch(
            "script.todo.todo.navigate", lambda todo, menu: opened.append(menu)
        ):
            getattr(TODO, self.MENU)(None)
        [self.menu] = opened
        self.entries = [e for e in self.menu.entries if isinstance(e, Entry)]

    def _key(self, label):
        for key in self.EXPECTED:
            if label.startswith(key):
                return key
        return label

    def test_its_method_opens_the_menu_it_names(self):
        self.assertEqual(self.menu.name, self.MENU)

    def test_every_entry_reaches_the_method_it_names(self):
        for entry in self.entries:
            key = self._key(entry.key)
            self.assertIn(
                key,
                self.EXPECTED,
                f"« {entry.key} » absente d'EXPECTED : déclarez où elle mène",
            )
            self.assertEqual(entry.action, self.EXPECTED[key], entry.key)

    def test_expected_table_has_no_stale_entry(self):
        keys = {self._key(entry.key) for entry in self.entries}
        self.assertEqual(set(self.EXPECTED) - keys, set())

    def test_zero_goes_back(self):
        self.assertIs(self.menu.back, self.BACK)


class TestTelemetryMenuNumbering(RegistryCoherence, unittest.TestCase):
    """L'entrée [4] du menu principal : TUI, WEB, arrêt de l'interface web,
    fenêtre bureautique.

    [3] arrête un serveur que d'autres onglets peuvent employer : un
    décalage entre l'affichage et le dispatch arrêterait au lieu d'ouvrir.
    """

    MENU = "prompt_telemetry"
    EXPECTED = {
        "Navigation telemetry (TUI)": "_todo_telemetry_tui",
        "Navigation telemetry (WEB)": "_todo_telemetry_web",
        "Stop the web interface": "_todo_web_stop",
        "Desktop window": "_todo_desktop_window",
    }


class TestConfigurationMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Configuration : la langue, trois préférences, Fork, et la remise à
    zéro de toutes les préférences, qui ne se défait pas."""

    MENU = "prompt_configuration"
    BACK = None
    EXPECTED = {
        "Language / Langue": "_change_language",
        "QEMU deployment interface": "_pref_edit",
        "Display while deploying": "_pref_edit",
        "Odoo migration interface": "_pref_edit",
        "Fork - Open TODO in a new tab": "_fork_todo",
        "Reset all preferences": "_reset_preferences",
    }

    def test_each_preference_is_the_one_its_entry_names(self):
        from script.todo.todo import TODO

        for entry in self.entries:
            if entry.action == "_pref_edit":
                title = TODO._PREF_CHOICES[entry.kwargs["key"]][0]
                self.assertEqual(title, entry.key)


class TestUpdateMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Update : les mises à jour de todo.json, puis la migration d'Odoo et
    celle de Poetry, toujours les deux dernières."""

    MENU = "prompt_execute_update"
    EXPECTED = {
        "Upgrade Odoo": "_upgrade_odoo",
        "Upgrade Poetry": "upgrade_poetry",
    }

    def test_the_configured_updates_come_first(self):
        first = self.menu.entries[0]
        self.assertEqual(
            (first.config_key, first.action, first.kwarg),
            ("update_from_makefile", "execute_from_configuration", "instance"),
        )


class TestUpdateMenu(unittest.TestCase):
    """Mise à jour : chaque numéro lance l'entrée qu'il montre, et aucune
    autre réponse ne lance rien.

    Les entrées de `update_from_makefile` d'abord, puis Upgrade Odoo et
    Upgrade Poetry. Les commandes sont des doubles, aucune ne part ; HOME
    est temporaire, la langue fixée et la télémétrie de navigation
    neutralisée.
    """

    ENTRIES = [
        {"prompt_description": "Forged one", "makefile_cmd": "forged_one"},
        {"prompt_description": "Forged two", "makefile_cmd": "forged_two"},
    ]

    def setUp(self):
        from script.todo import todo_i18n
        from script.todo.todo import TODO

        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("en")
        # Les modules déplacés d'urwid avertissent quand `inspect.stack`,
        # qui dessine le fil d'Ariane, lit leur `__file__` : sous
        # `-W error`, l'avertissement ferait tomber le menu.
        self.enterContext(warnings.catch_warnings())
        warnings.filterwarnings(
            "ignore", r"urwid\.\S+ is moved to", DeprecationWarning
        )
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        for patcher in (
            patch.dict(os.environ, {"HOME": home.name}),
            patch("script.todo.todo_telemetry.record"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.todo = TODO()
        self.todo.config_file.get_config = lambda key: [
            dict(entry) for entry in self.ENTRIES
        ]

    def answer(self, answers):
        """(configurations lancées, migrations, mises à jour de Poetry,
        texte affiché) quand Mise à jour reçoit `answers`, puis « 0 »."""
        from script.todo.todo import TODO

        ran = []

        def run(todo, instance, **options):
            ran.append(instance.get("makefile_cmd"))

        with (
            patch.object(TODO, "execute_from_configuration", run),
            patch("script.todo.todo.todo_upgrade", create=True) as upgrade,
            patch.object(TODO, "upgrade_poetry") as poetry,
            patch("click.prompt", side_effect=[*answers, "0"]),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertIs(self.todo.prompt_execute_update(), False)
        migration = upgrade.TodoUpgrade.return_value.execute_odoo_upgrade
        return ran, migration.call_count, poetry.call_count, out.getvalue()

    def test_each_number_runs_the_entry_it_shows(self):
        # « 5 » n'est pas affiché ; « 01 » et « 1 » entouré de blancs ne
        # sont pas le numéro affiché.
        answers = ["1", "2", "3", "4", "5", "01", " 1"]
        ran, migrations, poetry, out = self.answer(answers)
        self.assertEqual(ran, ["forged_one", "forged_two"])
        self.assertEqual((migrations, poetry), (1, 1))
        self.assertEqual(out.count("Command not found !"), 3)

    def test_a_list_absent_from_the_configuration_adds_no_entry(self):
        self.todo.config_file.get_config = lambda key: None
        ran, migrations, poetry, out = self.answer(["1"])
        self.assertEqual((ran, migrations, poetry), ([], 1, 0))
        self.assertNotIn("Command not found !", out)


class TestCodeMenu(unittest.TestCase):
    """Code : les entrées de `code_from_makefile`, puis Open SHELL, Upgrade
    Module, Debug et Update, toujours les quatre dernières.

    Les commandes sont des doubles, aucune ne part ; HOME est temporaire,
    la langue fixée et la télémétrie de navigation neutralisée.
    """

    ENTRIES = [
        {"prompt_description": "Forged one", "makefile_cmd": "forged_one"},
        {"prompt_description": "Forged two", "makefile_cmd": "forged_two"},
    ]

    def setUp(self):
        from script.todo import todo_i18n
        from script.todo.todo import TODO

        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("en")
        # Les modules déplacés d'urwid avertissent quand `inspect.stack`,
        # qui dessine le fil d'Ariane, lit leur `__file__` : sous
        # `-W error`, l'avertissement ferait tomber le menu.
        self.enterContext(warnings.catch_warnings())
        warnings.filterwarnings(
            "ignore", r"urwid\.\S+ is moved to", DeprecationWarning
        )
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        for patcher in (
            patch.dict(os.environ, {"HOME": home.name}),
            patch("script.todo.todo_telemetry.record"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.todo = TODO()
        self.todo.config_file.get_config = lambda key: [
            dict(entry) for entry in self.ENTRIES
        ]

    def answer(self, answers):
        """(configurations lancées, appels d'Open SHELL, d'Upgrade Module,
        de Debug et d'Update, texte affiché) quand Code reçoit `answers`,
        puis « 0 »."""
        from script.todo.todo import TODO

        ran = []

        def run(todo, instance, **options):
            ran.append(instance.get("makefile_cmd"))

        with (
            patch.object(TODO, "execute_from_configuration", run),
            patch.object(TODO, "open_shell_on_database") as shell,
            patch.object(TODO, "upgrade_module") as upgrade,
            patch.object(TODO, "debug_ide") as debug,
            patch.object(TODO, "prompt_execute_update") as update,
            patch("click.prompt", side_effect=[*answers, "0"]),
            redirect_stdout(io.StringIO()) as out,
        ):
            update.return_value = False
            self.assertIs(self.todo.prompt_execute_code(), False)
        fixed = [d.call_count for d in (shell, upgrade, debug, update)]
        return ran, fixed, out.getvalue()

    def test_a_list_absent_from_the_configuration_adds_no_entry(self):
        # Sans la liste, Open SHELL est [1] et Update [4].
        self.todo.config_file.get_config = lambda key: None
        ran, fixed, out = self.answer(["1", "4"])
        self.assertEqual((ran, fixed), ([], [1, 0, 0, 1]))
        self.assertNotIn("Command not found !", out)

    def test_each_number_runs_the_entry_it_shows(self):
        # « 7 » n'est pas affiché ; « 01 », « 1 » entouré de blancs, « +2 »,
        # « ١ » (le chiffre un en écriture arabe) et « 05 », qui écrit la
        # place de Debug, ne sont pas le numéro affiché.
        answers = ["1", "2", "3", "4", "5", "6", "7"]
        answers += ["01", " 1", "1 ", "+2", "١", "05"]
        ran, fixed, out = self.answer(answers)
        self.assertEqual(ran, ["forged_one", "forged_two"])
        self.assertEqual(fixed, [1, 1, 1, 1])
        self.assertEqual(out.count("Command not found !"), 7)


class TestMenuLabels(unittest.TestCase):
    """Toute méthode de menu doit avoir son étiquette de fil d'Ariane.

    Sans elle, `_menu_header` n'affiche pas le segment et
    `todo_telemetry.build_code_tree` traite le menu comme une COMMANDE :
    il apparaît en feuille, sous son nom de méthode brut.

    Les menus se trouvent par ce qu'ils APPELLENT — `fill_help_info` ou
    `_menu_header` — dans tout le paquet, et non par la table de répartition
    du menu Exécution. Chercher là ne voyait que les sous-menus atteints
    depuis cette table : un menu ouvert depuis ailleurs, ou défini dans un
    mixin, n'était jamais examiné, et c'est ainsi que le sous-menu VPN a
    passé le contrôle sans étiquette.

    Cinq méthodes sont exemptées, et pour la même raison : ce sont des
    ACTIONS qui posent une question — un choix de méthode d'installation, un
    « aller plus loin » après un rapport — et non des écrans où l'on
    navigue. Leur donner un segment mettrait une miette sur une invite
    passagère.
    """

    ECRANS_EXEMPTES = {
        "_analyse_follow_up",
        "rtk_install",
        "generate_config_from_preconfiguration",
        "debug_ide",
        "execute_odoo_upgrade",
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

    def test_menu_labels_was_parsed(self):
        self.assertIn("prompt_execute", self.labels)

    def test_analyse_menu_has_a_breadcrumb_label(self):
        self.assertIn("prompt_execute_analyse", self.labels)

    @staticmethod
    def _menus_du_paquet():
        """Toute méthode qui dessine un menu, dans tout script/todo/*.py.

        Une méthode dessine un menu quand elle appelle `fill_help_info` ou
        `_menu_header` : c'est par là que passe l'en-tête, donc c'est là que
        l'étiquette manque ou non. Les deux fonctions elles-mêmes sortent.
        Un menu du registre s'ouvre par `navigate(self, …)`, qui les
        appelle : sa méthode compte aussi."""
        trouves = set()
        for chemin in sorted(TODO_DIR.glob("*.py")):
            arbre = ast.parse(chemin.read_text(encoding="utf-8"))
            for noeud in ast.walk(arbre):
                if not isinstance(noeud, ast.FunctionDef):
                    continue
                appels = {
                    c.func.attr
                    for c in ast.walk(noeud)
                    if isinstance(c, ast.Call)
                    and isinstance(c.func, ast.Attribute)
                } | {
                    c.func.id
                    for c in ast.walk(noeud)
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                }
                if not {"fill_help_info", "_menu_header", "navigate"} & appels:
                    continue
                if noeud.name in ("fill_help_info", "_menu_header"):
                    continue
                trouves.add(noeud.name)
        return trouves

    def test_the_package_menus_were_found(self):
        """Le détecteur voit bien des menus : sinon tout passerait."""
        menus = self._menus_du_paquet()
        self.assertIn("prompt_execute_qemu", menus)
        self.assertIn("prompt_execute_vpn", menus)
        self.assertGreater(len(menus), 20)

    def test_no_new_menu_forgets_its_label(self):
        missing = self._menus_du_paquet() - self.labels - self.ECRANS_EXEMPTES
        self.assertEqual(
            missing,
            set(),
            f"menus sans étiquette dans _MENU_LABELS : {sorted(missing)}",
        )

    def test_the_vpn_submenu_leaves_a_crumb(self):
        """Le cas nommé : il était le seul menu invisible au contrôle."""
        self.assertIn("prompt_execute_vpn", self.labels)

    def test_each_declared_menu_keeps_its_crumb(self):
        """Un menu du registre garde l'étiquette de sa méthode, qui est son
        `crumb` : le fil d'Ariane et la clé de télémétrie ne changent pas."""
        from script.todo.todo import TODO
        from script.todo.todo_telemetry import _declared_menus

        declared = _declared_menus(TODO_DIR)
        self.assertLessEqual(
            {
                "prompt_telemetry",
                "prompt_configuration",
                "prompt_execute_update",
            },
            set(declared),
        )
        for name, menu in declared.items():
            self.assertEqual(TODO._MENU_LABELS.get(name), menu["crumb"], name)

    def test_no_stale_exemption(self):
        """Une exemption qui ne nomme plus un menu est à retirer."""
        fantomes = self.ECRANS_EXEMPTES - self._menus_du_paquet()
        self.assertEqual(fantomes, set())

    def test_an_exemption_is_never_also_labelled(self):
        """Exempter ET étiqueter dirait deux choses opposées du même écran."""
        self.assertEqual(self.ECRANS_EXEMPTES & self.labels, set())


if __name__ == "__main__":
    unittest.main()
