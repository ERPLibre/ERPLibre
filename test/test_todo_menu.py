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
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, call, patch

from script.todo.ui.registry import Entry, FromConfig

TODO_DIR = Path(__file__).resolve().parent.parent / "script" / "todo"
TODO_PY = TODO_DIR / "todo.py"


class MenuCoherence:
    """Socle : un menu écrit en liste de dictionnaires est-il cohérent ?

    Ce piège-là ne dépend pas du menu : seules les entrées
    « prompt_description » consomment un numéro (les « section » sont des
    titres), et le dispatch les renumérote à la main. Insérer une entrée avant
    la dernière décale tout ce qui suit sans que rien ne proteste.

    Ce socle sert les menus encore écrits à la main ; un autre n'a qu'à
    déclarer ses quatre attributs.

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
    # une branche qu'un commentaire explique compte comme les autres, où
    # que le commentaire s'écrive.
    RE_DISPATCH_CALL = re.compile(
        r'(?:el)?if status == "(\d+)":\s*\n(?:\s*#.*\n)*'
        r"\s*(?:status = )?self\.(\w+)\("
    )

    def setUp(self):
        source = self.SOURCE.read_text(encoding="utf-8")
        start = source.index(self.ENTRY)
        end = source.index(self.END, start)
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
        self.assertGreater(len(self.shown), self.MINIMUM)
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
            atteint = dct.get(num)
            self.assertEqual(
                atteint,
                self.EXPECTED[key],
                f"[{num}] « {label} » mène à {atteint}"
                f" au lieu de {self.EXPECTED[key]}",
            )

    def test_expected_table_has_no_stale_entry(self):
        keys = {self._key(label) for _, label in self.shown}
        self.assertEqual(set(self.EXPECTED) - keys, set())


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
    """L'arbre de télémétrie se lit dans le CODE, sans la classe assemblée.

    `build_code_tree()` lit la classe TODO de todo.py, les mixins que
    todo.py importe (QEMU/KVM, Proxmox…) et les menus du registre : un menu
    qui vit hors de todo.py garde sa colonne. Chaque feuille porte la
    méthode et les kwargs que la TUI de télémétrie lui passe.
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

    def test_only_the_reset_and_the_erase_are_dangerous_nodes(self):
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
            dangerous,
            [
                "TODO › Execute › Database › Erase a database",
                "TODO › Configuration › Reset all preferences",
            ],
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

    def test_each_leaf_of_the_git_family_binds_its_arguments(self):
        # [4] › [1] appelle une feuille avec ses kwargs : une méthode qui
        # attend un argument que l'arbre ne donne pas lève dans la TUI au
        # lieu de lancer sa commande.
        import inspect

        from script.todo.todo import TODO

        def leaves(node):
            for child in node["children"]:
                if child["is_menu"]:
                    yield from leaves(child)
                else:
                    yield child

        found = [
            leaf
            for menu in ("Git", "GPT code", "Automation")
            for leaf in leaves(self._noeud(menu))
        ]
        self.assertGreater(len(found), 30)
        for leaf in found:
            with self.subTest(leaf=leaf["label"]):
                method = getattr(TODO, leaf["method"])
                inspect.signature(method).bind(None, **leaf["kwargs"])

    def test_the_session_listing_keeps_its_key(self):
        # Le libellé de [1] finit par le compte des sessions, calculé au
        # dessin : sa feuille garde la clé de l'entrée, et une entrée vide.
        sessions = self._noeud("Claude Code")
        self.assertEqual(
            [
                (n["label"], n["method"], n.get("entry"))
                for n in sessions["children"]
            ],
            [
                ("List local sessions", "_claude_lister", ""),
                ("Ask a question to a session", "_claude_questionner", None),
                (
                    "Resume a session in a new terminal",
                    "_claude_reprendre",
                    None,
                ),
            ],
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

    def test_git_lists_its_configured_entries_and_shell_tools(self):
        # Les éléments de `git_from_makefile` suivent les quatre entrées
        # fixes, chacun lancé par `_git_from_configuration`, et les trois
        # outils de shell ferment la liste.
        config = json.loads((TODO_DIR / "todo.json").read_text())
        git = self._noeud("Git")
        self.assertEqual(
            [
                (n["label"], n["method"], n["kwargs"])
                for n in git["children"]
                if not n["is_menu"]
            ],
            [
                ("Add a remote to a local repository", "_git_add_remote", {}),
                (
                    "Install git hooks (commit-msg, pre-commit)",
                    "_git_install_hooks",
                    {},
                ),
                (
                    "Set merge.conflictStyle to zdiff3 (global)",
                    "_git_set_conflict_style",
                    {},
                ),
            ]
            + [
                (
                    e["prompt_description_key"],
                    "_git_from_configuration",
                    {"instance": e},
                )
                for e in config["git_from_makefile"]
            ]
            + [
                ("Install Starship on Shell", "_shell_install_starship", {}),
                ("Install Claude Code", "_shell_install_claude_code", {}),
                ("Install opencode", "_shell_install_opencode", {}),
            ],
        )

    def test_each_actions_menu_passes_its_mode(self):
        # [4] › [1] lance une feuille par sa méthode et ses kwargs : sans
        # `production_ready`, une action du serveur de production se
        # lancerait en mode local.
        server = self._noeud("Git local server")
        self.assertEqual(
            [
                {n["kwargs"].get("production_ready") for n in m["children"]}
                for m in server["children"]
            ],
            [{False}, {True}],
        )


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


class RegistryCoherence:
    """Socle : un menu déclaré au registre mène-t-il où il le dit ?

    Le numéro d'une entrée est sa place dans la déclaration : affichage et
    dispatch ne peuvent pas se désaligner. Reste à dire où mène chaque
    entrée, par le début de sa clé, et c'est EXPECTED, qu'ajouter une
    entrée oblige à compléter. À déclarer par la sous-classe : MENU (la
    méthode qui ouvre le menu, de TODO sauf si `_owner` rend une autre
    classe), EXPECTED et BACK (ce que rend [0]).
    """

    MENU = ""
    EXPECTED = {}
    BACK = False

    def _owner(self):
        """La classe dont MENU est une méthode."""
        from script.todo.todo import TODO

        return TODO

    def setUp(self):
        # `navigate` se remplace dans le module qui définit la méthode :
        # todo.py, un mixin ou database_manager.py.
        method = getattr(self._owner(), self.MENU)
        opened = []
        with patch(
            f"{method.__module__}.navigate",
            lambda todo, menu: opened.append(menu),
        ):
            method(None)
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


class TestExecuteMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Le menu Execute : seize sous-menus, en cinq sections.

    Une entrée se reconnaît au début de son libellé, avant « - » : « Doc »
    et « Docker / Podman » commencent de même.
    """

    MENU = "prompt_execute"
    BACK = None
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

    def test_each_submenu_gives_back_false(self):
        # Le navigateur ne lit pas ce que rend une action : un sous-menu qui
        # rendrait autre chose que False pour refermer Execute ne le
        # refermerait plus. Écrit à la main, il ne rend que False ; déclaré,
        # il rend navigate(self, menus_<famille>.<MENU>), dont le menu a
        # `back=False`. Un `return` nu compte pour None, et rien ne tombe de
        # la fin de la méthode, qui rendrait None aussi : sa dernière
        # instruction est un `return`, ou un `while True` sans aucun `break`.
        import inspect
        import textwrap

        from script.todo import menus
        from script.todo.todo import TODO

        for entry in self.entries:
            source = textwrap.dedent(
                inspect.getsource(getattr(TODO, entry.action))
            )
            [method] = ast.parse(source).body
            last = method.body[-1]
            if isinstance(last, ast.While):
                self.assertIsInstance(last.test, ast.Constant, entry.action)
                self.assertIs(last.test.value, True, entry.action)
                breaks = [
                    n for n in ast.walk(last) if isinstance(n, ast.Break)
                ]
                self.assertFalse(breaks, entry.action)
            else:
                self.assertIsInstance(last, ast.Return, entry.action)
            returns = [
                r.value or ast.Constant(None)
                for r in ast.walk(method)
                if isinstance(r, ast.Return)
            ]
            self.assertTrue(returns, entry.action)
            for value in returns:
                if isinstance(value, ast.Constant):
                    self.assertIs(value.value, False, entry.action)
                    continue
                self.assertIsInstance(value, ast.Call, entry.action)
                func = ast.unparse(value.func)
                self.assertEqual(func, "navigate", entry.action)
                self.assertEqual(len(value.args), 2, entry.action)
                menu = value.args[1]
                self.assertIsInstance(menu, ast.Attribute, entry.action)
                self.assertIsInstance(menu.value, ast.Name, entry.action)
                family = menu.value.id.removeprefix("menus_")
                module = getattr(menus, family)
                self.assertIs(
                    getattr(module, menu.attr).back, False, entry.action
                )


class TestCodeMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Code : les entrées de todo.json, puis Open SHELL, Upgrade Module,
    Debug et Update, toujours les quatre dernières."""

    MENU = "prompt_execute_code"
    EXPECTED = {
        "Open SHELL": "open_shell_on_database",
        "Upgrade Module": "upgrade_module",
        "Debug": "debug_ide",
        "Update": "prompt_execute_update",
    }

    def test_the_configured_entries_come_first(self):
        first = self.menu.entries[0]
        self.assertEqual(
            (first.config_key, first.action, first.kwarg),
            ("code_from_makefile", "execute_from_configuration", "instance"),
        )


class TestConfigMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Config : quatre générations de la configuration, puis la file
    d'attente des tâches."""

    MENU = "prompt_execute_config"
    EXPECTED = {
        "Generate all configuration": "generate_config",
        "Generate from pre-configuration": (
            "generate_config_from_preconfiguration"
        ),
        "Generate from backup file": "generate_config_from_backup",
        "Generate from database": "generate_config_from_database",
        "Setup queue job": "generate_config_queue_job",
    }


class TestProcessMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Process : arrêter Odoo sur son port, ou le serveur git daemon."""

    MENU = "prompt_execute_process"
    EXPECTED = {
        "Kill Odoo process": "process_kill_from_port",
        "Kill git daemon": "process_kill_git_daemon",
    }


class TestTestMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Test : un module, avec ou sans couverture, trois suites unitaires,
    et les tests longs, qui créent de vraies machines."""

    MENU = "prompt_execute_test"
    EXPECTED = {
        "Test a module": "execute_test_module",
        "ERPLibre unit tests": "execute_unit_tests",
        "Mail unit tests": "execute_unit_tests",
        "Analyse unit tests": "execute_unit_tests",
        "Long tests": "prompt_execute_longtest",
    }

    def test_each_entry_passes_the_arguments_its_label_names(self):
        self.assertEqual(
            [(e.key, e.kwargs) for e in self.entries if e.kwargs],
            [
                ("Test a module", {"coverage": False}),
                ("Test a module with code coverage", {"coverage": True}),
                ("Mail unit tests", {"pattern": "test_mail*.py"}),
                ("Analyse unit tests", {"pattern": "test_analyse*.py"}),
            ],
        )


class TestRunMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Run : « Choose your database », les instances de todo.json, puis
    Mobile, montré seulement quand son répertoire existe."""

    MENU = "prompt_execute_instance"
    EXPECTED = {
        "Choose your database": "callback_execute_custom_database",
        "Mobile": "callback_make_mobile_home",
    }

    def test_each_instance_asks_before_it_runs_and_mobile_is_guarded(self):
        [database, instances, mobile] = self.menu.entries
        self.assertEqual(
            (instances.config_key, instances.action, instances.kwarg),
            ("instance", "_run_instance", "instance"),
        )
        self.assertEqual(
            (database.when, mobile.when), (None, "_mobile_exists")
        )

    def test_the_tui_runs_each_instance_through_its_question(self):
        # La TUI de télémétrie lance une feuille par sa méthode : chaque
        # instance de todo.json passe par _run_instance, qui pose la
        # question et ouvre sa base, comme depuis le menu.
        from script.todo.todo_telemetry import _config_list, build_code_tree

        [execute] = [
            n for n in build_code_tree()["children"] if n["label"] == "Execute"
        ]
        [run] = [n for n in execute["children"] if n["label"] == "Run"]
        instances = _config_list("instance", TODO_DIR)
        self.assertTrue(instances)
        self.assertEqual(
            [
                (n["method"], n["kwargs"]["instance"])
                for n in run["children"]
                if "instance" in n["kwargs"]
            ],
            [("_run_instance", instance) for instance in instances],
        )


class TestDatabaseMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Le menu Database, qui manie des bases entières.

    C'est celui où une renumérotation coûte le plus cher : sa dernière
    entrée EFFACE une base. Chaque entrée nomme la méthode de TODO qui
    passe la main à celle de même nom de `db_manager`.
    """

    MENU = "prompt_execute_database"
    EXPECTED = {
        "Create backup": "create_backup_from_database",
        "Download database": "download_database_backup_cli",
        "Restore from backup": "restore_from_database",
        "Duplicate a database": "duplicate_database",
        "Erase a database": "drop_database",
    }

    def test_each_entry_hands_over_to_the_database_manager(self):
        from script.todo.todo import TODO

        for entry in self.entries:
            todo = Mock()
            getattr(TODO, entry.action)(todo)
            called = getattr(todo.db_manager, entry.action)
            self.assertEqual(called.call_args_list, [call()], entry.action)


class TestEraseMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Database › Erase a database, que DatabaseManager ouvre : toutes les
    bases, ou une seule, puis le menu se referme."""

    MENU = "drop_database"
    BACK = None
    EXPECTED = {
        "Erase ALL databases": "_drop_all_databases",
        "Erase a single database": "_drop_single_database",
    }

    def _owner(self):
        from script.todo.database_manager import DatabaseManager

        return DatabaseManager

    def test_it_closes_once_an_entry_has_run(self):
        self.assertIs(self.menu.closes, True)

    def test_each_entry_is_dangerous(self):
        # `drop_database` n'est pas dans `_MENU_LABELS` : l'arbre n'a pas de
        # nœud pour ce menu. Qu'il en gagne un, et ni la TUI ni la page web
        # ne lancent un effacement.
        self.assertEqual({e.danger for e in self.entries}, {True})


class TestAnalyseMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Le menu Analyse : huit analyses en six sections, qui ne prennent
    pas de numéro."""

    MENU = "prompt_execute_analyse"
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


class TestTransformMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Transform data : lire un fichier ou anonymiser une base, puis
    l'environnement de lecture et ce qu'il a produit."""

    MENU = "prompt_execute_transform"
    EXPECTED = {
        "Open a file and read its report": "_transform_open_and_report",
        "Anonymise an Odoo database": "_transform_anonymise_base",
        "Install the reading environment": "_transform_install_env",
        "What can this machine read?": "_transform_capabilities",
        "Copies produced": "_transform_copies",
        "Databases produced": "_transform_bases_produites",
    }


class TestDocMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Doc : deux adresses qui dépendent d'une version tapée, puis deux
    pages de l'OCA."""

    MENU = "prompt_execute_doc"
    EXPECTED = {
        "Migration module coverage": "_doc_migration_coverage",
        "What change between version": "_doc_version_changes",
        "OCA guidelines": "_doc_link",
        "OCA migration Odoo 19 milestone": "_doc_link",
    }

    def test_each_link_is_the_page_its_label_names(self):
        self.assertEqual(
            [(e.key, e.kwargs) for e in self.entries if e.kwargs],
            [
                (
                    "OCA guidelines",
                    {
                        "url": "https://github.com/OCA/odoo-community.org"
                        "/blob/master/website/Contribution/CONTRIBUTING.rst"
                    },
                ),
                (
                    "OCA migration Odoo 19 milestone",
                    {
                        "url": "https://github.com/OCA/maintainer-tools/issues/658"
                    },
                ),
            ],
        )


class TestGitMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Le menu Git : quatre entrées fixes, les éléments de
    `git_from_makefile`, puis trois outils de shell, dont la place suit le
    nombre de ces éléments : la déclaration les numérote tous."""

    MENU = "prompt_execute_git"
    EXPECTED = {
        "Local git server": "prompt_execute_git_local_server",
        "Add a remote to a local repository": "_git_add_remote",
        "Install git hooks": "_git_install_hooks",
        "Set merge.conflictStyle": "_git_set_conflict_style",
        "Install Starship on Shell": "_shell_install_starship",
        "Install Claude Code": "_shell_install_claude_code",
        "Install opencode": "_shell_install_opencode",
    }

    def test_the_configured_entries_follow_the_fixed_ones(self):
        [configured] = [
            e for e in self.menu.entries if isinstance(e, FromConfig)
        ]
        self.assertIs(self.menu.entries[4], configured)
        self.assertEqual(
            (configured.config_key, configured.action, configured.kwarg),
            ("git_from_makefile", "_git_from_configuration", "instance"),
        )


class TestGitLocalServerMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Git local server : les actions du serveur local, puis celles du
    serveur de production, chacune son menu."""

    MENU = "prompt_execute_git_local_server"
    EXPECTED = {
        "Deploy a local git server": "_prompt_git_server_local",
        "Deploy a production git server": "_prompt_git_server_production",
    }


class TestGitServerLocalMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Actions du serveur git local : les cinq étapes du déploiement, en
    mode local."""

    MENU = "_prompt_git_server_local"
    PRODUCTION = False
    EXPECTED = {
        "Run all": "_deploy_git_server",
        "Init": "_deploy_git_server",
        "Remote": "_deploy_git_server",
        "Push": "_deploy_git_server",
        "Serve": "_deploy_git_server",
    }

    def test_each_entry_passes_its_step_and_mode(self):
        self.assertEqual(
            [entry.kwargs for entry in self.entries],
            [
                {"production_ready": self.PRODUCTION, "action": action}
                for action in ("all", "init", "remote", "push", "serve")
            ],
        )


class TestGitServerProductionMenuNumbering(TestGitServerLocalMenuNumbering):
    """Actions du serveur git de production : les mêmes cinq étapes, en
    mode production."""

    MENU = "_prompt_git_server_production"
    PRODUCTION = True


class TestGptCodeMenuNumbering(RegistryCoherence, unittest.TestCase):
    """GPT code : Claude configs, l'ajout d'une automatisation, RTK, le
    contexte donné à Claude, Plugins et les sessions de Claude Code."""

    MENU = "prompt_execute_gpt_code"
    EXPECTED = {
        "Configure Claude Code configurations": "_prompt_claude_configs",
        "Add an automation with Claude": "_claude_add_automation",
        "RTK": "prompt_execute_rtk",
        "Show the context given to Claude": "_show_claude_context",
        "Claude Code plugins": "prompt_execute_claude_plugins",
        "Claude Code - local sessions": "prompt_claude_sessions",
    }


class TestClaudeConfigsMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Claude configs : quatre déploiements de commandes `/…`, dont un de
    deux commandes, puis la liste de celles qui sont installées."""

    MENU = "_prompt_claude_configs"
    EXPECTED = {
        "Commit": "_setup_claude_command",
        "Git prepare merge": "_setup_claude_command",
        "Todo Add Command + Plan Max": "_setup_claude_todo_commands",
        "Todo Generate Code": "_setup_claude_command",
        "Show installed custom commands": "_list_claude_commands",
    }

    def test_each_deployment_names_its_command_and_template(self):
        # Le gabarit que nomme une entrée est celui de sa commande dans la
        # table que lisent la liste et l'écran de contexte.
        from script.todo.todo import TODO

        deployed = [
            entry.kwargs
            for entry in self.entries
            if entry.action == "_setup_claude_command"
        ]
        self.assertEqual(len(deployed), 3)
        for kwargs in deployed:
            with self.subTest(command=kwargs["command_name"]):
                self.assertEqual(
                    TODO._CLAUDE_COMMAND_TEMPLATES[kwargs["command_name"]],
                    kwargs["template_filename"],
                )
        self.assertEqual(
            [k.get("personalize", False) for k in deployed],
            [True, False, False],
        )


class TestPluginsMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Plugins : l'inventaire, l'installation, puis la maintenance des
    plugins et des marketplaces de Claude Code."""

    MENU = "prompt_execute_claude_plugins"
    EXPECTED = {
        "List installed plugins": "_claude_plugin_exec",
        "List configured marketplaces": "_claude_plugin_exec",
        "Search a plugin": "_claude_plugin_search",
        "Show a plugin detail": "_claude_plugin_details",
        "Install the ERPLibre preferred list": (
            "_claude_install_preferred_plugins"
        ),
        "Install a plugin by name": "_claude_plugin_install_by_name",
        "Add a marketplace": "_claude_marketplace_add",
        "Update the marketplaces": "_claude_plugin_update",
        "Uninstall a plugin": "_claude_plugin_uninstall",
    }

    def test_each_listing_passes_its_subcommand(self):
        self.assertEqual(
            [e.kwargs for e in self.entries if e.kwargs],
            [{"args": "list"}, {"args": "marketplace list"}],
        )


class TestRtkMenuNumbering(RegistryCoherence, unittest.TestCase):
    """RTK : l'installation et le crochet global, l'état, puis les
    occasions d'économiser des jetons."""

    MENU = "prompt_execute_rtk"
    EXPECTED = {
        "Install RTK": "rtk_install",
        "Initialize global auto-rewrite hook": "rtk_init_global",
        "Check RTK version": "rtk_check_version",
        "Check RTK status": "rtk_check_status",
        "Show cumulative token savings": "rtk_show_gain",
        "Discover optimization opportunities": "rtk_discover",
    }


class TestClaudeCodeMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Claude Code, dans `assistant_menu.py` : lister les sessions de la
    machine, en interroger une, ou la reprendre. Ctrl+C à sa question
    ramène à GPT code."""

    MENU = "prompt_claude_sessions"
    BACK = None
    EXPECTED = {
        "List local sessions": "_claude_lister",
        "Ask a question to a session": "_claude_questionner",
        "Resume a session": "_claude_reprendre",
    }

    def test_the_listing_counts_and_ctrl_c_goes_back(self):
        self.assertEqual(
            [entry.suffix for entry in self.entries],
            ["_claude_sessions_count", None, None],
        )
        self.assertEqual(
            (self.menu.render, self.menu.abort_closes), ("each", True)
        )


class TestAutomationMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Automation : une entrée par élément de `function`, et aucune
    autre."""

    MENU = "prompt_execute_function"
    EXPECTED = {}

    def test_each_element_of_function_is_an_entry(self):
        [configured] = self.menu.entries
        self.assertEqual(
            (configured.config_key, configured.action, configured.kwarg),
            ("function", "execute_from_configuration", "instance"),
        )
        self.assertEqual(self.menu.render, "once")


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


class TestRunMenu(unittest.TestCase):
    """Run : « Choose your database », les instances de `instance`, puis
    Mobile, quand son répertoire existe.

    Les commandes sont des doubles, aucune ne part ; HOME est temporaire,
    le répertoire de Mobile absent, la langue fixée et la télémétrie de
    navigation neutralisée.
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
        self.mobile = os.path.join(home.name, "mobile")
        for patcher in (
            patch.dict(os.environ, {"HOME": home.name}),
            patch("script.todo.todo_telemetry.record"),
            patch("script.todo.todo.MOBILE_HOME_PATH", self.mobile),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.todo = TODO()
        self.todo.config_file.get_config = lambda key: [
            dict(entry) for entry in self.ENTRIES
        ]

    def answer(self, answers, new=True):
        """(instances lancées, questions « nouvelle instance ? », appels de
        « Choose your database » et de Mobile, texte affiché) quand Run
        reçoit `answers`, puis « 0 », la question rendant `new` ; chaque
        question posée est « Do you want a new instance? ». Une instance
        lancée est (makefile_cmd, exec_run_db, ignore_makefile)."""
        from script.todo.todo import TODO

        ran = []

        def run(todo, instance, exec_run_db=False, ignore_makefile=False):
            command = instance["makefile_cmd"]
            ran.append((command, exec_run_db, ignore_makefile))

        with (
            patch.object(TODO, "execute_from_configuration", run),
            patch.object(TODO, "callback_execute_custom_database") as db,
            patch.object(TODO, "callback_make_mobile_home") as mobile,
            patch("click.confirm", return_value=new) as confirm,
            patch("click.prompt", side_effect=[*answers, "0"]),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertIs(self.todo.prompt_execute_instance(), False)
        self.assertEqual(
            confirm.call_args_list,
            [call("Do you want a new instance?")] * confirm.call_count,
        )
        calls = (confirm.call_count, db.call_count, mobile.call_count)
        return ran, calls, out.getvalue()

    def test_each_instance_asks_for_a_new_one_and_opens_its_database(self):
        # [1] est « Choose your database » : les instances sont [2] et [3].
        ran, calls, out = self.answer(["2", "3"], new=False)
        self.assertEqual(
            ran, [("forged_one", True, True), ("forged_two", True, True)]
        )
        self.assertEqual(calls, (2, 0, 0))

    def test_each_number_runs_the_entry_it_shows(self):
        # Avec Mobile, [4]. « 5 » n'est pas affiché ; « 00 », « -1 »,
        # « 01 », « 2 » entouré de blancs, « +2 », « ٢ » (le chiffre deux
        # en écriture arabe) et « -9 » ne sont pas le numéro affiché.
        os.mkdir(self.mobile)
        answers = ["1", "2", "3", "4", "5", "00", "-1", "01", " 2", "2 "]
        answers += ["+2", "٢", "-9"]
        ran, calls, out = self.answer(answers)
        self.assertEqual(
            ran, [("forged_one", True, False), ("forged_two", True, False)]
        )
        self.assertEqual(calls, (2, 1, 1))
        self.assertEqual(out.count("Command not found !"), 9)

    def test_a_list_absent_from_the_configuration_adds_no_entry(self):
        # Sans la liste, et sans Mobile, Run ne montre que [1].
        self.todo.config_file.get_config = lambda key: None
        ran, calls, out = self.answer(["1", "2"])
        self.assertEqual((ran, calls), ([], (0, 1, 0)))
        self.assertEqual(out.count("Command not found !"), 1)

    def test_choose_your_database_opens_only_a_chosen_database(self):
        # select_database rend False sur [0], sans base, ou quand
        # PostgreSQL ne répond pas.
        from script.todo.todo import TODO

        chosen = [False, "forged"]
        with (
            patch.object(
                self.todo.db_manager, "select_database", side_effect=chosen
            ),
            patch.object(TODO, "prompt_execute_selenium_and_run_db") as run,
            patch("click.prompt", side_effect=["1", "1", "0"]),
            redirect_stdout(io.StringIO()),
        ):
            self.assertIs(self.todo.prompt_execute_instance(), False)
        self.assertEqual([c.args for c in run.call_args_list], [("forged",)])


class TestDocMenu(unittest.TestCase):
    """Doc : ses deux questions de version, puis l'adresse de la page de
    cette version. HOME est temporaire et la télémétrie de navigation
    neutralisée."""

    def test_the_version_questions_are_in_the_chosen_language(self):
        from script.todo import todo_i18n
        from script.todo.todo import TODO

        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("fr")
        # Les modules déplacés d'urwid avertissent quand `inspect.stack`,
        # qui dessine le fil d'Ariane, lit leur `__file__` : sous
        # `-W error`, l'avertissement ferait tomber le menu.
        self.enterContext(warnings.catch_warnings())
        warnings.filterwarnings(
            "ignore", r"urwid\.\S+ is moved to", DeprecationWarning
        )
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        with (
            patch.dict(os.environ, {"HOME": home.name}),
            patch("script.todo.todo_telemetry.record"),
            patch("builtins.input", return_value="17") as asked,
            patch("click.prompt", side_effect=["1", "2", "0"]),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertIs(TODO().prompt_execute_doc(), False)
        self.assertEqual(
            [c.args for c in asked.call_args_list],
            [
                ("Version d'Odoo CE à migrer (5-17) : ",),
                ("Version d'Odoo CE dont voir les changements (8-18) : ",),
            ],
        )
        self.assertIn("coverage_analysis/modules170-180.html", out.getvalue())
        self.assertIn("wiki/Migration-to-version-17.0", out.getvalue())


class TestEraseMenu(unittest.TestCase):
    """Database › Erase a database, qu'ouvre DatabaseManager : les deux
    effacements sont des doubles, HOME est temporaire, la langue fixée et
    la télémétrie de navigation relevée."""

    def test_it_shows_under_the_crumb_of_database(self):
        # Database › Erase a database › [0] › [0] : le menu d'effacement
        # n'ajoute pas de segment ; son en-tête et sa clé de télémétrie
        # sont ceux de Database.
        from script.todo import todo_i18n
        from script.todo.database_manager import DatabaseManager
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
        keys = []
        with (
            patch.dict(os.environ, {"HOME": home.name}),
            patch.object(DatabaseManager, "_drop_all_databases") as every,
            patch.object(DatabaseManager, "_drop_single_database") as one,
            patch("script.todo.todo_telemetry.record", keys.append),
            patch("click.prompt", side_effect=["5", "0", "0"]) as prompt,
            redirect_stdout(io.StringIO()),
        ):
            self.assertIs(TODO().prompt_execute_database(), False)
        erase = prompt.call_args_list[1].args[0]
        self.assertTrue(erase.startswith("📍 Database\nCommand:\n[1] Erase"))
        self.assertEqual(keys, ["Database", "Database"])
        self.assertEqual((every.call_count, one.call_count), (0, 0))


class AnsweredMenu:
    """Socle d'un test qui répond à un menu de TODO : `self.todo` tourne
    sur un HOME temporaire, en anglais, sa télémétrie de navigation
    neutralisée, et `get_config` y rend une copie d'ENTRIES pour toute
    clé. Chaque test pose ses doubles : aucune commande ne part."""

    ENTRIES = []

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


class TestAutomationMenu(AnsweredMenu, unittest.TestCase):
    """Automation : une entrée par élément de `function`, que lance
    execute_from_configuration."""

    ENTRIES = [
        {"prompt_description": "Forged one", "command": "forged_one"},
        {"prompt_description": "Forged two", "command": "forged_two"},
    ]

    def answer(self, answers):
        """(configurations lancées, texte affiché) quand Automation reçoit
        `answers`, puis « 0 »."""
        from script.todo.todo import TODO

        ran = []

        def run(todo, instance, **options):
            ran.append(instance.get("command"))

        with (
            patch.object(TODO, "execute_from_configuration", run),
            patch("click.prompt", side_effect=[*answers, "0"]),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertIs(self.todo.prompt_execute_function(), False)
        return ran, out.getvalue()

    def test_a_list_absent_from_the_configuration_adds_no_entry(self):
        # Sans la liste, le menu n'a que [0] : « 1 » n'y est pas.
        self.todo.config_file.get_config = lambda key: None
        ran, out = self.answer(["1"])
        self.assertEqual(ran, [])
        self.assertEqual(out.count("Command not found !"), 1)

    def test_each_number_runs_the_entry_it_shows(self):
        # « 3 » n'est pas affiché ; « 01 », « 1 » entouré de blancs, « +1 »
        # et « ١ » (le chiffre un en écriture arabe) ne sont pas le numéro
        # affiché.
        answers = ["1", "2", "3", "01", " 1", "1 ", "+1", "١"]
        ran, out = self.answer(answers)
        self.assertEqual(ran, ["forged_one", "forged_two"])
        self.assertEqual(out.count("Command not found !"), 6)


class TestGitMenu(AnsweredMenu, unittest.TestCase):
    """Git : quatre entrées fixes, les éléments de `git_from_makefile`,
    puis Starship, Claude Code et opencode, toujours les trois
    dernières."""

    ENTRIES = [
        {"prompt_description": "Forged one", "bash_command": "forged_one"},
        {"prompt_description": "Forged two", "bash_command": "forged_two"},
    ]
    # Les méthodes des entrées fixes, dans l'ordre du menu.
    FIXED = (
        "prompt_execute_git_local_server",
        "_git_add_remote",
        "_git_install_hooks",
        "_git_set_conflict_style",
        "_shell_install_starship",
        "_shell_install_claude_code",
        "_shell_install_opencode",
    )

    def answer(self, answers):
        """(configurations lancées, appels de chaque méthode de FIXED,
        texte affiché) quand Git reçoit `answers`, puis « 0 »."""
        from script.todo.todo import TODO

        ran = []

        def run(todo, instance, **options):
            ran.append(instance.get("bash_command"))

        with ExitStack() as stack:
            doubles = [
                stack.enter_context(
                    patch.object(TODO, name, return_value=False)
                )
                for name in self.FIXED
            ]
            for patcher in (
                patch.object(TODO, "execute_from_configuration", run),
                patch("click.prompt", side_effect=[*answers, "0"]),
            ):
                stack.enter_context(patcher)
            out = stack.enter_context(redirect_stdout(io.StringIO()))
            self.assertIs(self.todo.prompt_execute_git(), False)
        return ran, [d.call_count for d in doubles], out.getvalue()

    def test_each_number_runs_the_entry_it_shows(self):
        # « 10 » n'est pas affiché ; « 01 », « 1 » entouré de blancs, « +5 »,
        # « ١ » (le chiffre un en écriture arabe) et « 05 », qui écrit la
        # place du premier élément de todo.json, ne sont pas le numéro
        # affiché.
        answers = [str(n) for n in range(1, 11)]
        answers += ["01", " 1", "1 ", "+5", "١", "05"]
        ran, fixed, out = self.answer(answers)
        self.assertEqual(ran, ["forged_one", "forged_two"])
        self.assertEqual(fixed, [1] * 7)
        self.assertEqual(out.count("Command not found !"), 7)

    def test_an_element_that_names_a_method_runs_it(self):
        # Un élément de todo.json qui porte « method » lance cette méthode
        # de TODO, sans passer par execute_from_configuration.
        self.todo.config_file.get_config = lambda key: [
            {"prompt_description": "Forged", "method": "_git_add_remote"}
        ]
        ran, fixed, _ = self.answer(["5"])
        self.assertEqual(ran, [])
        self.assertEqual(fixed, [0, 1, 0, 0, 0, 0, 0])

    def test_a_list_absent_from_the_configuration_adds_no_entry(self):
        # Sans la liste, Starship est [5] et opencode [7] ; « 8 » n'est
        # pas affiché.
        self.todo.config_file.get_config = lambda key: None
        ran, fixed, out = self.answer(["5", "7", "8"])
        self.assertEqual(ran, [])
        self.assertEqual(fixed, [0, 0, 0, 0, 1, 0, 1])
        self.assertEqual(out.count("Command not found !"), 1)


class TestClaudeConfigsMenu(AnsweredMenu, unittest.TestCase):
    """Claude configs : [3] déploie /todo_plan_max, puis
    /todo_add_command, chacune par `_setup_claude_command`, un double."""

    def test_three_deploys_plan_max_then_add_command(self):
        from script.todo.todo import TODO

        with (
            patch.object(TODO, "_setup_claude_command") as deploy,
            patch("click.prompt", side_effect=["3", "0"]),
            redirect_stdout(io.StringIO()),
        ):
            self.assertIs(self.todo._prompt_claude_configs(), False)
        self.assertEqual(
            deploy.call_args_list,
            [
                call(
                    "todo_plan_max",
                    "template_claude_commands_todo_plan_max.md",
                ),
                call(
                    "todo_add_command",
                    "template_claude_commands_todo_add_command.md",
                ),
            ],
        )


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
    passagère. Deux autres, `select_database` et `drop_database`, sont
    celles de DatabaseManager : le fil d'Ariane ne lit que les cadres de
    TODO et ne peut pas leur donner de segment ; elles s'affichent sous le
    menu de TODO qui les ouvre.
    """

    ECRANS_EXEMPTES = {
        "_analyse_follow_up",
        "rtk_install",
        "generate_config_from_preconfiguration",
        "debug_ide",
        "execute_odoo_upgrade",
        "select_database",
        "drop_database",
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
    def _menus_par_fichier():
        """(fichier, méthode) de toute méthode qui dessine un menu, dans tout
        script/todo/*.py.

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
                trouves.add((chemin.name, noeud.name))
        return trouves

    @classmethod
    def _menus_du_paquet(cls):
        """Les noms de méthode de `_menus_par_fichier`."""
        return {nom for _, nom in cls._menus_par_fichier()}

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
                "prompt_execute",
                "prompt_execute_code",
                "prompt_execute_config",
                "prompt_execute_process",
                "prompt_execute_test",
                "prompt_execute_update",
                "prompt_execute_instance",
                "prompt_execute_database",
                "drop_database",
                "prompt_execute_analyse",
                "prompt_execute_transform",
                "prompt_execute_doc",
                "prompt_execute_git",
                "prompt_execute_git_local_server",
                "_prompt_git_server_local",
                "_prompt_git_server_production",
                "prompt_execute_gpt_code",
                "_prompt_claude_configs",
                "prompt_execute_claude_plugins",
                "prompt_execute_rtk",
                "prompt_claude_sessions",
                "prompt_execute_function",
            },
            set(declared),
        )
        for name, menu in declared.items():
            self.assertEqual(TODO._MENU_LABELS.get(name), menu["crumb"], name)

    def test_the_database_manager_exemptions_hold_in_its_file_only(self):
        """`select_database` et `drop_database` ne sont exemptées que dans
        database_manager.py : une méthode de même nom qui dessinerait un
        menu ailleurs resterait sans segment sans que rien ne le dise."""
        noms = {"select_database", "drop_database"}
        self.assertEqual(
            {(f, n) for f, n in self._menus_par_fichier() if n in noms},
            {("database_manager.py", n) for n in noms},
        )

    def test_no_stale_exemption(self):
        """Une exemption qui ne nomme plus un menu est à retirer."""
        fantomes = self.ECRANS_EXEMPTES - self._menus_du_paquet()
        self.assertEqual(fantomes, set())

    def test_an_exemption_is_never_also_labelled(self):
        """Exempter ET étiqueter dirait deux choses opposées du même écran."""
        self.assertEqual(self.ECRANS_EXEMPTES & self.labels, set())


if __name__ == "__main__":
    unittest.main()
