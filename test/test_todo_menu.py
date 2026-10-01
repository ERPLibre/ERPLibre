#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les menus de TODO : les numéros affichés mènent-ils où ils le disent ?

Un menu déclaré au registre n'a qu'une liste, dont la place fait le
numéro : `RegistryCoherence` vérifie où mène chaque entrée, par le début
de son libellé.

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
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, call, patch

from script.todo.ui.registry import Entry, FromConfig

TODO_DIR = Path(__file__).resolve().parent.parent / "script" / "todo"


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
        entrée renommée le laisserait figer une icône que personne ne voit.
        Le menu se lit dans sa déclaration, entrées et sections."""
        from script.todo.menus import proxmox

        cles = {getattr(item, "key", None) for item in proxmox.PROXMOX.entries}
        for cle in self.ICONES:
            self.assertIn(cle, cles, f"« {cle} » n'est plus dans le menu")


class TestLArbreDesMenus(unittest.TestCase):
    """L'arbre de télémétrie se lit dans les DÉCLARATIONS, sans rien importer.

    `build_code_tree()` lit les menus du registre (`menus/*.py`), le module
    du registre et todo.json : un menu déclaré garde sa colonne, où que
    vive sa méthode. Chaque feuille porte la méthode et les kwargs que la
    TUI de télémétrie lui passe.
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

    def test_the_tree_reads_only_the_declared_menus(self):
        # Les fichiers de menus, le module du registre et todo.json
        # suffisent : sans todo.py ni ses mixins, l'arbre est le même,
        # nœud pour nœud.
        import shutil

        from script.todo.todo_telemetry import build_code_tree

        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp)
            shutil.copytree(TODO_DIR / "menus", copy / "menus")
            (copy / "ui").mkdir()
            shutil.copy(TODO_DIR / "ui" / "registry.py", copy / "ui")
            shutil.copy(TODO_DIR / "todo.json", copy)
            self.assertEqual(build_code_tree(copy / "todo.py"), self.arbre)

    def test_each_menu_of_the_tree_is_declared(self):
        # Le segment de chaque menu de l'arbre est déclaré : le `crumb`
        # d'un menu du registre, ou celui d'une entrée dont l'action
        # dessine son propre écran. Un segment que seul le code donnait
        # manquerait à l'arbre qui ne lit que les déclarations.
        from script.todo.todo_telemetry import _declared_menus

        declared = set()
        for menu in _declared_menus(TODO_DIR).values():
            declared.add(menu["crumb"])
            declared |= {item.get("crumb") for item in menu["entries"]}

        def segments(node):
            yield node["label"]
            for child in node["children"]:
                if child["is_menu"]:
                    yield from segments(child)

        self.assertEqual(set(segments(self.arbre)) - declared, set())

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

    def test_install_lists_what_it_installs_by_a_key(self):
        # Les trois installations par touche sont des feuilles sans
        # entrée, la question d'Install n'étant pas un message `menu`, et
        # dangereuses : elles posent des paquets. Ni la TUI ni la page web
        # ne les lancent. Les versions d'Odoo, que rend une méthode, ne se
        # lisent pas sans l'appeler.
        noeud = self._noeud("Install")
        self.assertEqual(
            [
                (
                    f["label"],
                    f["method"],
                    f["kwargs"],
                    f.get("entry"),
                    f.get("danger"),
                )
                for f in noeud["children"]
            ],
            [
                (
                    "ERPLibre only without Odoo, with the required Python",
                    "_install_run",
                    {"cmd": "./script/install/install_erplibre.sh"},
                    "",
                    True,
                ),
                (
                    "Install all Odoo version with ERPLibre",
                    "_install_run",
                    {"cmd": "make install_odoo_all_version"},
                    "",
                    True,
                ),
                (
                    "ERPLibre with mobile home",
                    "_install_run",
                    {"cmd": "./mobile/install_and_run.sh"},
                    "",
                    True,
                ),
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
        # Le registre donne chaque entrée : Fork et Reset, les kwargs de
        # _pref_edit, la méthode d'Upgrade Odoo. Un libellé qui finit par
        # un suffixe calculé n'a pas d'entrée fixe.
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

    def test_the_dangerous_nodes_are_the_declared_ones(self):
        # Seul un nœud qui porte "danger" ne se lance ni de la TUI ni de
        # la page web : l'effacement d'une base, les actions du serveur git
        # de production, qui tournent en root, les installateurs de shell,
        # chaque entrée des familles QEMU et Proxmox qui efface ce que la
        # TUI ne rend pas par elle-même, pose des paquets ou un service, ici
        # ou sur un hôte distant, agit en root sur un hôte, écrit la
        # configuration SSH du compte ou crée de vraies machines, la
        # suppression d'un serveur de modèles connu, les deux recherches qui
        # sondent sans confirmation les VM de la machine ou les hôtes de
        # ~/.ssh/config, et la remise à zéro des préférences. Les `kwargs`
        # distinguent les actions de production de celles du serveur local,
        # au même chemin.
        dangerous = []

        def walk(node, path):
            for child in node["children"]:
                here = f"{path} › {child['label']}"
                if child.get("danger"):
                    dangerous.append((here, child.get("kwargs")))
                walk(child, here)

        walk(self.arbre, "TODO")
        longtest = "TODO › Execute › Test › Long test"
        actions = "TODO › Execute › Git › Git local server › Actions"
        git = "TODO › Execute › Git"
        deploy = "TODO › Execute › Deploy"
        cache = f"{deploy} › QEMU cache"
        network = "TODO › Execute › Network"
        docker = "TODO › Execute › Docker / Podman"
        self.assertEqual(
            dangerous,
            [
                *[
                    (f"{longtest} › {label}", kwargs)
                    for label, kwargs in (
                        (
                            "Nested Proxmox depth: run it",
                            {"script": "deep_proxmox.py"},
                        ),
                        (
                            "Nested QEMU depth: run it",
                            {"script": "deep_qemu.py"},
                        ),
                        (
                            "Download cache: two VMs, measure",
                            {"nom": "qemu_cache.py", "args": ""},
                        ),
                        (
                            "Download cache: measure, then cut the upstream",
                            {"nom": "qemu_cache.py", "args": "--hors-ligne"},
                        ),
                        ("ERPLibre on NixOS: run it", {}),
                        ("Undo what the descent created", {}),
                    )
                ],
                ("TODO › Execute › Database › Erase a database", {}),
                *[
                    (
                        f"{actions} › {label}",
                        {"production_ready": True, "action": action},
                    )
                    for label, action in (
                        ("Run all (init + remote + push + serve)", "all"),
                        ("Init - Create bare repos", "init"),
                        ("Remote - Add local remotes", "remote"),
                        ("Push - Push to local server", "push"),
                        ("Serve - Start git daemon", "serve"),
                    )
                ],
                (f"{git} › Install Starship on Shell", {}),
                (f"{git} › Install Claude Code", {}),
                (f"{git} › Install opencode", {}),
                *[
                    (f"{deploy} › SSH › SSH - {label}", {})
                    for label in (
                        "Sync files (rsync)",
                        "Install ERPLibre",
                        "Install systemd service",
                        "Configure nginx + SSL",
                    )
                ],
                *[
                    (f"{deploy} › QEMU/KVM › {label}", {})
                    for label in (
                        "Resize a VM disk",
                        "Delete VM(s)",
                        "SSH configuration (~/.ssh/config, ProxyJump)",
                        "Recreate the VM subnet (stop, redefine, restart)",
                        "Clean up QEMU (orphan files)",
                    )
                ],
                *[
                    (f"{deploy} › Proxmox VE › {label}", {})
                    for label in (
                        "Deploy a VM on the Proxmox host",
                        "Download a cloud image on the host",
                        "Resize a VM disk",
                        "Delete VM(s)",
                        "Clean up (orphan disks)",
                        "SSH configuration (~/.ssh/config, ProxyJump)",
                    )
                ],
                (f"{deploy} › Deploy - Install NTFY notification server", {}),
                *[
                    (f"{cache} › {label}", {})
                    for label in (
                        "Cache - Install or reinstall",
                        "Exceptions › Exceptions - Remove the stale ones",
                        "Exceptions › Exceptions - Remove one by its MAC",
                        "Git mirrors › Mirrors - Remove one",
                    )
                ],
                *[
                    (f"{cache} › Age and cleanup › Clean - {label}", {})
                    for label in (
                        "What has not served for a while",
                        "Everything",
                        "Forget one URL",
                    )
                ],
                (
                    f"{cache} › Tests › Test - Undo the machines created",
                    {"nom": "qemu_cache.py", "args": "--detruire"},
                ),
                (
                    f"{cache} › Automatic cleanup › Cleanup - Run now",
                    {"a_blanc": False},
                ),
                *[
                    (f"{vpn} › VPN - {label}", {})
                    for vpn in (f"{deploy} › VPN", f"{network} › VPN")
                    for label in (
                        "Connect a profile",
                        "Disconnect a profile",
                        "Delete a profile",
                        "Install the client packages",
                    )
                ],
                (f"{docker} › Install Docker", {"moteur": "docker"}),
                (f"{docker} › Install Podman", {"moteur": "podman"}),
                *[
                    (f"{docker} › {label}", {})
                    for label in (
                        "Remove unused images, containers and volumes",
                        "By workspace - a compose project and what it holds",
                        "Images one by one",
                    )
                ],
                (f"{docker} › Compose › Stop", {"args": ["down"]}),
                *[
                    (f"TODO › Install › {label}", {"cmd": cmd})
                    for label, cmd in (
                        (
                            "ERPLibre only without Odoo, with the required"
                            " Python",
                            "./script/install/install_erplibre.sh",
                        ),
                        (
                            "Install all Odoo version with ERPLibre",
                            "make install_odoo_all_version",
                        ),
                        (
                            "ERPLibre with mobile home",
                            "./mobile/install_and_run.sh",
                        ),
                    )
                ],
                (
                    "TODO › Assistant › LLM › Servers › Delete a server",
                    {},
                ),
                *[
                    (f"TODO › Assistant › LLM › Search › {label}", {})
                    for label in (
                        "The QEMU VMs of this machine (virsh)",
                        "The hosts of ~/.ssh/config",
                    )
                ],
                ("TODO › Configuration › Reset all preferences", {}),
            ],
        )

    def test_a_submenu_carries_the_entry_its_parent_shows(self):
        # Le fil d'Ariane dit « Code », le menu Exécution montre « Code -
        # Developer tools » : la page web cherche celle-ci pour y entrer,
        # la clé de l'entrée déclarée qui ouvre le sous-menu.
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
        # Le menu LLM : Search garde son entrée, et une feuille dont le
        # libellé finit par un suffixe calculé a une entrée vide.
        llm = self._noeud("LLM")
        self.assertEqual(
            self._noeud("Search", llm)["entry"], "Search for a server…"
        )
        [gpt] = [
            n
            for n in llm["children"]
            if n.get("method") == "_llm_gpt_catalogue"
        ]
        self.assertEqual((gpt["label"], gpt["entry"]), ("gpt tools", ""))

    def test_assistant_opens_llm_and_mail(self):
        # Le courriel, dont les menus sans segment restent hors de
        # l'arbre, y est une feuille : la TUI l'ouvre par la méthode de
        # TODO qui passe la main à mail/menu.py.
        assistant = self._noeud("Assistant")
        self.assertEqual(
            [
                (node["label"], node["is_menu"], node.get("method"))
                for node in assistant["children"]
            ],
            [("LLM", True, None), ("mail_menu", False, "_assistant_mail")],
        )

    def test_a_submenu_its_parent_does_not_name_has_an_empty_entry(self):
        # Le menu LLM calcule le libellé de l'entrée qui ouvre Servers : son
        # `entry` est vide, comme celui d'une feuille que son menu ne nomme
        # pas, et la page ne donne de ▶ ni à lui ni à ses feuilles.
        servers = self._noeud("Servers", self._noeud("LLM"))
        self.assertTrue(servers["is_menu"])
        self.assertEqual(servers["entry"], "")

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

    def test_each_leaf_of_the_tree_binds_its_arguments(self):
        # [4] › [1] appelle une feuille avec ses kwargs : une méthode qui
        # attend un argument que l'arbre ne donne pas lève dans la TUI au
        # lieu de lancer sa commande. Chaque feuille de l'arbre, toutes
        # familles, lie les siens ; seule Mobile, gardée (`when`), n'a pas
        # de méthode, et la TUI ne la lance pas.
        import inspect

        from script.todo.todo import TODO

        def leaves(node):
            for child in node["children"]:
                if child["is_menu"]:
                    yield from leaves(child)
                else:
                    yield child

        found = list(leaves(self.arbre))
        bound = [leaf for leaf in found if leaf.get("method")]
        self.assertGreater(len(bound), 250)
        self.assertEqual(
            [leaf["label"] for leaf in found if not leaf.get("method")],
            ["Mobile - Compile and run software"],
        )
        for leaf in bound:
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

    def test_changing_the_proxmox_host_from_the_tui_picks_another(self):
        # La TUI lance une feuille par sa méthode et ses kwargs : celle de
        # « Change the Proxmox host » oublie l'hôte retenu PUIS en fait
        # choisir un autre, comme le menu ; oublier seul laisserait Proxmox
        # VE sans hôte.
        from script.todo.todo import TODO

        [leaf] = [
            child
            for child in self._noeud("Proxmox VE")["children"]
            if child["label"] == "Change the Proxmox host"
        ]
        calls = []
        with (
            patch.object(
                TODO, "_pve_forget_host", lambda todo: calls.append("forget")
            ),
            patch.object(
                TODO, "_pve_pick_host", lambda todo: calls.append("pick")
            ),
        ):
            getattr(TODO.__new__(TODO), leaf["method"])(**leaf["kwargs"])
        self.assertEqual(calls, ["forget", "pick"])


class TestQemuMenu(unittest.TestCase):
    """QEMU/KVM : vingt entrées fixes, puis celles de `qemu_from_makefile`,
    dont une section, qui ne prend pas de numéro.

    Les commandes sont des doubles, aucune ne part ; virsh est tenu pour
    présent, HOME est temporaire, la langue fixée et la télémétrie de
    navigation neutralisée.
    """

    ENTRIES = [
        {"prompt_description": "Forged one", "bash_command": "forged_one"},
        {"section": "Forged section"},
        {"prompt_description": "Forged two", "bash_command": "forged_two"},
    ]

    def setUp(self):
        from script.todo import todo_i18n
        from script.todo.todo import TODO

        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("en")
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        for patcher in (
            patch.dict(os.environ, {"HOME": home.name}),
            patch("script.todo.todo_telemetry.record"),
            patch.object(TODO, "_qemu_ensure_tools", return_value=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.todo = TODO()
        self.todo.config_file.get_config = lambda key: [
            dict(entry) for entry in self.ENTRIES
        ]

    def answer(self, answers):
        """(configurations lancées, appels de [1] et de [20], texte
        affiché) quand QEMU/KVM reçoit `answers`, puis « 0 »."""
        from script.todo.todo import TODO

        ran = []

        def run(todo, instance, **options):
            ran.append(instance.get("bash_command"))

        with (
            patch.object(TODO, "execute_from_configuration", run),
            patch.object(TODO, "_qemu_deploy") as deploy,
            patch.object(TODO, "_qemu_list_images") as images,
            patch("click.prompt", side_effect=[*answers, "0"]),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertIs(self.todo.prompt_execute_qemu(), False)
        return ran, [deploy.call_count, images.call_count], out.getvalue()

    def test_each_number_runs_the_entry_it_shows(self):
        # [21] et [22] lancent les deux entrées de la configuration, que
        # sépare une section. « 23 » n'est pas affiché ; « 01 », « 1 »
        # entouré de blancs, « +21 », « ٢١ » (vingt et un en écriture arabe)
        # et « 021 » ne sont pas un numéro affiché.
        answers = ["1", "20", "21", "22", "23"]
        answers += ["01", " 1 ", "+21", "٢١", "021"]
        ran, fixed, out = self.answer(answers)
        self.assertEqual(ran, ["forged_one", "forged_two"])
        self.assertEqual(fixed, [1, 1])
        self.assertEqual(out.count("Command not found !"), 6)


class TestQemuStatistics(unittest.TestCase):
    """Statistics : [r] remet l'historique à zéro, après sa question o/N ;
    une réponse vide, [0], « tout » ou un numéro reviennent sans rien
    effacer. L'historique et libvirt sont des doubles."""

    SUMMARY = {"total": 2, "ok": 2, "failed": 0, "first_ts": 0}
    SUMMARY.update(last_ts=0, median=60, min=60, max=60, total_secs=120)

    def test_only_r_then_yes_erases_the_history(self):
        from script.todo import qemu_install_monitor as mon
        from script.todo import todo_i18n
        from script.todo.todo import TODO

        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("en")
        todo = TODO.__new__(TODO)
        cases = [([""], 0), (["0"], 0), (["tout", "0"], 0), (["1", ""], 0)]
        cases += [(["r", "n", "0"], 0), (["R", "y", "0"], 1)]
        refused = []
        for answers, erased in cases:
            with (
                self.subTest(answers=answers),
                patch.object(mon, "stats_summary", return_value=self.SUMMARY),
                patch.object(mon, "stats_by", return_value=[]),
                patch.object(mon, "virsh_domstates", return_value={}),
                patch.object(mon, "reset_stats", return_value=2) as reset,
                patch("builtins.input", side_effect=answers),
                redirect_stdout(io.StringIO()) as out,
            ):
                todo._qemu_stats()
            self.assertEqual(reset.call_count, erased)
            refused += re.findall(r"Invalid choice: (.*)", out.getvalue())
        question = "\nQEMU statistics\n[r] Reset the statistics\n[0] 🔙 Back"
        self.assertIn(question, out.getvalue())
        # « tout » et « 1 » sont dits invalides, puis la question revient.
        self.assertEqual(refused, ["tout", "1"])


class TestProxmoxMenu(unittest.TestCase):
    """Proxmox VE : dix-huit entrées fixes, puis celles de
    `proxmox_from_makefile`, dont une section, qui ne prend pas de numéro.

    Les commandes sont des doubles, aucune ne part ; l'hôte est tenu pour
    retenu, HOME est temporaire, la langue fixée et la télémétrie de
    navigation neutralisée.
    """

    ENTRIES = [
        {"prompt_description": "Forged one", "bash_command": "forged_one"},
        {"section": "Forged section"},
        {"prompt_description": "Forged two", "bash_command": "forged_two"},
    ]

    def setUp(self):
        from script.todo import todo_i18n
        from script.todo.todo import TODO

        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("en")
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        host = {"target": "root@forged-pve", "jump": ""}
        for patcher in (
            patch.dict(os.environ, {"HOME": home.name}),
            patch("script.todo.todo_telemetry.record"),
            patch.object(TODO, "_pve_host", return_value=host),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.todo = TODO()
        self.todo.config_file.get_config = lambda key: [
            dict(entry) for entry in self.ENTRIES
        ]

    def answer(self, answers):
        """(configurations lancées, appels de [1] et de [17], texte
        affiché) quand Proxmox VE reçoit `answers`, puis « 0 »."""
        from script.todo.todo import TODO

        ran = []

        def run(todo, instance, **options):
            ran.append(instance.get("bash_command"))

        with (
            patch.object(TODO, "execute_from_configuration", run),
            patch.object(TODO, "_pve_deploy") as deploy,
            patch.object(TODO, "_pve_example") as example,
            patch("click.prompt", side_effect=[*answers, "0"]),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertIs(self.todo.prompt_execute_proxmox(), False)
        return ran, [deploy.call_count, example.call_count], out.getvalue()

    def test_each_number_runs_the_entry_it_shows(self):
        # [19] et [20] lancent les deux entrées de la configuration, que
        # sépare une section. « 21 » n'est pas affiché ; « 01 », « 1 »
        # entouré de blancs, « +19 », « ١٩ » (dix-neuf en écriture arabe)
        # et « 019 » ne sont pas un numéro affiché.
        answers = ["1", "17", "19", "20", "21"]
        answers += ["01", " 1 ", "+19", "١٩", "019"]
        ran, fixed, out = self.answer(answers)
        self.assertEqual(ran, ["forged_one", "forged_two"])
        self.assertEqual(fixed, [1, 1])
        self.assertEqual(out.count("Command not found !"), 6)

    def test_without_a_host_it_neither_draws_nor_asks(self):
        # Sans hôte retenu ni choisi, Proxmox VE rend False sans dessiner
        # son menu ni poser sa question.
        from script.todo.todo import TODO

        with (
            patch.object(TODO, "_pve_host", return_value=None),
            patch("click.prompt", side_effect=AssertionError("prompt")),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertIs(self.todo.prompt_execute_proxmox(), False)
        self.assertEqual(
            out.getvalue(), "🤖 Deploy a virtual machine on Proxmox VE!\n"
        )


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


class TestDeployMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Deploy : cloner, monter et joindre ERPLibre en local, puis les hôtes
    distants, les VM et le cache de leurs téléchargements, et les VPN.
    Une entrée se reconnaît au début de son libellé."""

    MENU = "prompt_execute_deploy"
    EXPECTED = {
        "Clone ERPLibre locally": "_deploy_clone_erplibre",
        "Configure sshfs": "_configure_sshfs",
        "SSH port forwarding": "_deploy_port_forward",
        "Configure a SOCKS proxy": "_deploy_socks_proxy",
        "SSH (remote host)": "prompt_execute_deploy_ssh",
        "QEMU/KVM": "prompt_execute_qemu",
        "Proxmox VE": "prompt_execute_proxmox",
        "Deploy - Install NTFY": "_deploy_ntfy_server",
        "QEMU cache": "prompt_execute_qemu_cache",
        "VPN": "prompt_execute_vpn",
    }


class TestSshMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Deploy › SSH : les opérations sur un hôte distant, dont démarrer,
    arrêter et redémarrer Odoo, trois entrées voisines qu'un décalage
    confondrait."""

    MENU = "prompt_execute_deploy_ssh"
    EXPECTED = {
        "SSH - Check connection": "_deploy_ssh_check",
        "SSH - Sync files": "_deploy_ssh_push",
        "SSH - Install ERPLibre": "_deploy_ssh_install",
        "SSH - Start Odoo": "_deploy_ssh_run",
        "SSH - Stop Odoo": "_deploy_ssh_stop",
        "SSH - Restart Odoo": "_deploy_ssh_restart",
        "SSH - Service status": "_deploy_ssh_status",
        "SSH - View logs": "_deploy_ssh_logs",
        "SSH - Run make target": "_deploy_ssh_make",
        "SSH - Install systemd service": "_deploy_ssh_install_systemd",
        "SSH - Configure nginx": "_deploy_ssh_install_nginx",
    }


class TestQemuMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Le menu QEMU/KVM (QEMU, `menus/deploy.py`), qu'ouvre `qemu_menu.py` :
    vingt entrées, puis celles de `qemu_from_makefile`."""

    MENU = "prompt_execute_qemu"

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

    def test_the_configured_entries_follow_the_catalog(self):
        last = self.menu.entries[-1]
        self.assertEqual(
            (last.config_key, last.action, last.kwarg),
            ("qemu_from_makefile", "execute_from_configuration", "instance"),
        )


class TestProxmoxMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Le menu Proxmox VE (PROXMOX, `menus/proxmox.py`), qu'ouvre
    `proxmox_menu.py` : dix-huit entrées, puis celles de
    `proxmox_from_makefile`.

    Quatre d'entre elles mènent VOLONTAIREMENT à des méthodes du menu QEMU :
    c'est le même travail, fait par le même code. La table le dit noir sur
    blanc : si quelqu'un les recopiait un jour, ce test montrerait que la
    cible a changé.
    """

    MENU = "prompt_execute_proxmox"

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
        "Change the Proxmox host": "_pve_change_host",
    }

    def test_the_configured_entries_follow_the_catalog(self):
        last = self.menu.entries[-1]
        self.assertEqual(
            (last.config_key, last.action, last.kwarg),
            (
                "proxmox_from_makefile",
                "execute_from_configuration",
                "instance",
            ),
        )


class TestVpnMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Le menu VPN (VPN, `menus/proxmox.py`), qu'ouvre `vpn_menu.py`
    depuis Deploy et depuis Network : se connecter, tenir ses profils et
    leurs secrets, équiper la machine."""

    MENU = "prompt_execute_vpn"
    EXPECTED = {
        "VPN - Connect a profile": "_vpn_connect",
        "VPN - Disconnect a profile": "_vpn_disconnect",
        "VPN - Status and diagnosis": "_vpn_diagnose",
        "VPN - Create a profile from a site preset": "_vpn_from_preset",
        "VPN - Import an AnyConnect profile": "_vpn_import_anyconnect",
        "VPN - Add or edit a profile": "_vpn_edit_profile",
        "VPN - Store secrets in the vault": "_vpn_store_secrets",
        "VPN - Show the rendered configuration": "_vpn_show_config",
        "VPN - Delete a profile": "_vpn_delete_profile",
        "VPN - Install the client packages": "_vpn_install",
        "VPN - What can this machine do?": "_vpn_check",
    }


class TestLongTestMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Le menu des tests longs (LONGTEST, `menus/proxmox.py`), qu'ouvre
    `longtest_menu.py` depuis Test : deux descentes imbriquées, le cache de
    téléchargement, ERPLibre sur NixOS, chacun à blanc puis pour de vrai,
    et le défaire."""

    MENU = "prompt_execute_longtest"
    EXPECTED = {
        "Nested Proxmox depth": "_longtest_descente",
        "Nested QEMU depth": "_longtest_descente",
        "Download cache": "_longtest_run",
        "ERPLibre on NixOS": "_longtest_nixos",
        "Undo what the descent created": "_longtest_defaire",
    }


class TestInstallMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Install (INSTALL, `menus/proxmox.py`), qu'ouvre le menu principal :
    trois installations par leur touche, puis une par version d'Odoo, que
    rend `_install_versions` ; [0] quitte, et Install se referme après une
    installation."""

    MENU = "prompt_install"
    BACK = None
    EXPECTED = {
        "ERPLibre only without Odoo": "_install_run",
        "Install all Odoo version": "_install_run",
        "ERPLibre with mobile home": "_install_run",
    }

    def test_each_installation_answers_its_key(self):
        self.assertEqual(
            [(entry.hotkey, entry.kwargs["cmd"]) for entry in self.entries],
            [
                ("q", "./script/install/install_erplibre.sh"),
                ("w", "make install_odoo_all_version"),
                ("m", "./mobile/install_and_run.sh"),
            ],
        )
        last = self.menu.entries[-1]
        self.assertEqual(
            (last.method, last.action, last.kwarg),
            ("_install_versions", "_install_version", "version"),
        )
        self.assertTrue(self.menu.closes)


class TestNetworkMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Network : tunnels SSH, mesure de débit, VPN, mandataire inverse
    d'Odoo et certificats locaux."""

    MENU = "prompt_execute_network"
    EXPECTED = {
        "SSH port-forwarding": "generate_network_port_forwarding",
        "Network performance": "generate_network_performance_test",
        "VPN": "prompt_execute_vpn",
        "Odoo reverse proxy": "network_reverse_proxy",
        "Local TLS certificates": "network_local_certificates",
    }


class TestSecurityMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Security : l'audit des dépendances Python."""

    MENU = "prompt_execute_security"
    EXPECTED = {"pip-audit": "execute_pip_audit"}


class TestContainerMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Docker / Podman : le moteur, l'inventaire, les nettoyages, qui
    effacent, et les images ERPLibre ; Install Docker et Install Podman
    lancent le même installateur, chacun pour son moteur."""

    MENU = "prompt_execute_container"
    EXPECTED = {
        "Diagnostic": "_container_diagnostic",
        "Service": "_container_service",
        "Install Docker": "_container_install",
        "Install Podman": "_container_install",
        "Images one by one": "_container_nettoyer_images",
        "Images": "_container_inventaire",
        "Containers": "_container_inventaire",
        "Networks": "_container_reseaux",
        "Remove unused": "_container_nettoyage",
        "By workspace": "_container_nettoyer_projets",
        "Build an image": "_container_build_odoo",
        "Compose": "_container_compose",
        "ERPLibre container": "_container_erplibre",
    }

    def test_each_install_names_its_engine(self):
        installs = [
            e for e in self.entries if e.action == "_container_install"
        ]
        self.assertEqual(
            [(e.key, e.kwargs) for e in installs],
            [
                ("Install Docker", {"moteur": "docker"}),
                ("Install Podman", {"moteur": "podman"}),
            ],
        )


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


class TestDebugMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Debug : une entrée, qui ouvre todo.py dans l'IDE."""

    MENU = "debug_ide"
    EXPECTED = {"Debug todo.py": "_debug_todo_py"}

    def test_its_entry_opens_todo_py_in_the_ide(self):
        from script.todo.todo import TODO

        opened = []
        todo = TODO.__new__(TODO)
        todo.open_pycharm_file = lambda *paths: opened.append(paths)
        getattr(todo, self.entries[0].action)()
        folder = os.getcwd()
        self.assertEqual(
            opened, [(folder, os.path.join(folder, "script/todo/todo.py"))]
        )
        self.assertEqual(
            (self.menu.crumb, self.menu.render), ("Debug", "once")
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


class TestPreconfigurationMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Generate from pre-configuration : trois groupes préréglés, puis
    tout ; chaque entrée génère la configuration de son groupe."""

    MENU = "generate_config_from_preconfiguration"
    EXPECTED = {"base": "generate_config", "all": "generate_config"}

    def test_each_entry_generates_its_group(self):
        self.assertEqual(
            [(entry.key, entry.kwargs) for entry in self.entries],
            [
                ("base", {"add_arg": "--group base"}),
                (
                    "base + code_generator",
                    {"add_arg": "--group base,code_generator"},
                ),
                ("base + image_db", {"add_arg": "--group base,image_db"}),
                ("all", None),
            ],
        )
        self.assertEqual(
            (self.menu.crumb, self.menu.render),
            ("Generate from pre-configuration", "once"),
        )


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
        # Sans segment, ce menu n'a pas de nœud dans l'arbre, où Database
        # le montre comme une feuille. Qu'il en gagne un, et ni la TUI ni
        # la page web ne lancent un effacement.
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

    def test_only_the_shell_installers_are_dangerous(self):
        # Ils lancent un installateur, du paquet ou de l'amont, et
        # écrivent dans le fichier du shell : ni la TUI ni la page web ne
        # les lancent.
        self.assertEqual(
            [entry.action for entry in self.entries if entry.danger],
            [
                "_shell_install_starship",
                "_shell_install_claude_code",
                "_shell_install_opencode",
            ],
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
    mode local ; aucune n'est dangereuse."""

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

    def test_each_entry_is_dangerous_in_production_only(self):
        # En production, les actions tournent en root, sous /srv/git : ni
        # la TUI ni la page web ne les lancent.
        self.assertEqual(
            {bool(entry.danger) for entry in self.entries}, {self.PRODUCTION}
        )


class TestGitServerProductionMenuNumbering(TestGitServerLocalMenuNumbering):
    """Actions du serveur git de production : les mêmes cinq étapes, en
    mode production, chacune dangereuse."""

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


class TestMainMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Le menu principal : ses cinq entrées, dessinées une fois après le
    logo et la langue ; [0] quitte TODO."""

    MENU = "run"
    BACK = None
    EXPECTED = {
        "Execute": "prompt_execute",
        "Install": "prompt_install",
        "Assistant": "prompt_assistant",
        "Navigation telemetry": "prompt_telemetry",
        "Configuration": "prompt_configuration",
    }

    def setUp(self):
        # `run` écrit le logo et demande la langue avant d'ouvrir le menu :
        # le logo est un fichier vide, la langue ne se demande pas.
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        todo.config_file = Mock()
        todo.config_file.get_logo_ascii_file_path.return_value = os.devnull
        opened = []
        with (
            patch(
                "script.todo.todo.navigate",
                lambda todo, menu: opened.append(menu),
            ),
            patch.object(TODO, "_ask_language"),
            redirect_stdout(io.StringIO()),
        ):
            todo.run()
        [self.menu] = opened
        self.entries = [e for e in self.menu.entries if isinstance(e, Entry)]

    def test_it_quits_todo_and_is_drawn_once(self):
        self.assertIs(self.menu.quits, True)
        self.assertEqual(self.menu.render, "once")
        self.assertEqual(
            self.menu.intro, "=> Enter your choice by number and press Enter!"
        )


class TestAssistantMenuNumbering(RegistryCoherence, unittest.TestCase):
    """L'entrée [3] du menu principal : une question à un modèle, et le
    courriel, que TODO ouvre par une méthode qui passe la main à
    mail/menu.py."""

    MENU = "prompt_assistant"
    BACK = None
    EXPECTED = {
        "AI question - Ask a model, local or remote": "prompt_assistant_llm",
        "mail_menu": "_assistant_mail",
    }


class TestLlmMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Assistant › LLM : parler, un outil gpt, les serveurs connus, la
    recherche, la fiche du serveur, chacun avec ce que son libellé dit
    entre parenthèses ; Ctrl+C ou Ctrl+D ramènent à Assistant."""

    MENU = "prompt_assistant_llm"
    BACK = None
    EXPECTED = {
        "Free question": "_llm_conversation",
        "gpt tools": "_llm_gpt_catalogue",
        "Known servers": "_llm_servers",
        "Search for a server…": "_llm_search",
        "Server card": "_llm_server_card",
    }

    def test_each_computed_label_names_its_method(self):
        self.assertEqual(
            [entry.suffix for entry in self.entries],
            [
                "_llm_talks_to",
                "_llm_gpt_count",
                "_llm_servers_count",
                None,
                "_llm_card_hint",
            ],
        )
        self.assertIs(self.menu.abort_closes, True)


class TestServersMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Assistant › LLM › Servers : les serveurs connus, puis l'ajout à la
    main et la suppression, qui efface un serveur."""

    MENU = "_llm_servers"
    BACK = None
    EXPECTED = {
        "Add a server by hand": "_llm_add_server",
        "Delete a server": "_llm_delete_server",
    }

    def test_the_known_servers_come_first_and_delete_is_dangerous(self):
        from script.todo.ui.registry import FromMethod

        known = self.menu.entries[0]
        self.assertIsInstance(known, FromMethod)
        self.assertEqual(
            (known.method, known.action, known.kwarg),
            ("_llm_known_servers", "_llm_use_server", "server"),
        )
        self.assertEqual(
            [entry.danger for entry in self.entries], [None, True]
        )
        self.assertEqual(self.menu.opens, "_llm_servers_open")


class TestSearchMenuNumbering(RegistryCoherence, unittest.TestCase):
    """Assistant › LLM › Search : cette machine, ses VM, ses hôtes SSH, les
    réseaux qu'elle porte, puis ce qu'on tape ; la question est redite
    avant chaque réponse."""

    MENU = "_llm_search"
    BACK = None
    EXPECTED = {
        "Here (127.0.0.1)": "_llm_search_here",
        "The QEMU VMs of this machine (virsh)": "_llm_search_qemu",
        "The hosts of ~/.ssh/config": "_llm_search_ssh",
        "An address I type": "_llm_add_server",
        "A network I type (CIDR)": "_llm_search_cidr",
        "The networks of a machine over SSH": "_llm_search_remote",
    }

    def test_the_probes_that_do_not_confirm_are_dangerous(self):
        # Les VM de la machine et les hôtes de ~/.ssh/config se sondent dès
        # l'entrée choisie ; le reste de Search confirme, demande l'hôte ou
        # ne joint que cette machine.
        self.assertEqual(
            [entry.danger for entry in self.entries],
            [None, True, True, None, None, None],
        )

    def test_the_networks_come_after_the_hosts_of_the_machine(self):
        from script.todo.ui.registry import FromMethod

        networks = self.menu.entries[3]
        self.assertIsInstance(networks, FromMethod)
        self.assertEqual(
            (networks.method, networks.action, networks.kwarg),
            ("_llm_networks", "_llm_search_network", "network"),
        )
        self.assertEqual(self.menu.before, "_llm_search_where")


class MailCoherence(RegistryCoherence):
    """Socle des menus du courriel : ils s'ouvrent par une fonction de
    mail/menu.py, sur MailMenus, sans segment de fil d'Ariane, et rendent
    None sur [0]. Le journal du paquet n'est pas branché."""

    BACK = None

    def _owner(self):
        from script.todo.mail import menu

        return menu

    def setUp(self):
        with patch("script.todo.mail.menu._configure_mail_logging"):
            super().setUp()

    def test_it_has_no_crumb(self):
        self.assertIsNone(self.menu.crumb)


class TestMailMenuNumbering(MailCoherence, unittest.TestCase):
    """Assistant › Mail : le client, les comptes, une synchronisation, le
    cache."""

    MENU = "prompt_execute_mail"
    EXPECTED = {
        "mail_open_tui": "_open_tui",
        "mail_accounts_menu": "prompt_mail_accounts",
        "mail_sync_now": "_sync_now",
        "mail_cache_menu": "prompt_mail_cache",
    }


class TestMailAccountsMenuNumbering(MailCoherence, unittest.TestCase):
    """Assistant › Mail › Accounts : la suppression d'un compte efface le
    compte et son secret."""

    MENU = "prompt_mail_accounts"
    EXPECTED = {
        "mail_account_list": "_list_accounts",
        "mail_account_add": "_add_account",
        "mail_account_delete": "_delete_account",
        "mail_account_template": "_write_template",
        "mail_account_test": "_test_account",
    }

    def test_only_delete_is_dangerous(self):
        dangerous = [entry.key for entry in self.entries if entry.danger]
        self.assertEqual(dangerous, ["mail_account_delete"])


class TestMailCacheMenuNumbering(MailCoherence, unittest.TestCase):
    """Assistant › Mail › Cache : le mode par défaut, montré entre
    parenthèses, celui d'un compte, et la purge, qui efface un cache."""

    MENU = "prompt_mail_cache"
    EXPECTED = {
        "mail_cache_default_mode": "_set_cache_mode",
        "mail_cache_account_mode": "_set_account_cache_mode",
        "mail_cache_size_purge": "_cache_size_and_purge",
    }

    def test_the_default_mode_shows_and_purge_is_dangerous(self):
        self.assertEqual(
            [(entry.suffix, entry.danger) for entry in self.entries],
            [("_cache_mode", None), (None, None), (None, True)],
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


class TestInstallMenu(unittest.TestCase):
    """Install : la première installation du système, puis le choix de ce
    qu'on installe, par sa touche. Rien ne part : PyCharm est tenu pour
    absent, les versions d'Odoo sont inventées, HOME est temporaire, et
    chaque réponse vient d'une liste."""

    VERSIONS = (
        [
            {
                "odoo_version": "16.0",
                "erplibre_version": "odoo16.0_forged",
                "is_deprecated": True,
            },
            {"odoo_version": "17.0", "erplibre_version": "odoo17.0_forged"},
            {
                "odoo_version": "18.0",
                "erplibre_version": "odoo18.0_forged",
                "default": True,
            },
        ],
        ["odoo17.0", "odoo18.0"],
        "odoo18.0",
    )

    def setUp(self):
        from script.todo import todo_i18n
        from script.todo.todo import TODO

        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        for patcher in (
            patch.dict(os.environ, {"HOME": home.name}),
            patch(
                "script.todo.todo.get_odoo_version",
                return_value=self.VERSIONS,
            ),
            patch(
                "script.todo.todo.subprocess.run",
                return_value=Mock(returncode=1),
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.todo = TODO()

    def screen(self, lang, answers):
        """Ce qu'Install écrit en `lang`, réponses comprises, quand il
        reçoit `answers`."""
        from script.todo import todo_i18n

        todo_i18n.use_lang(lang)
        shown, answers = io.StringIO(), iter(answers)

        def typed(prompt=""):
            answer = next(answers)
            shown.write(f"{prompt}{answer}\n")
            return answer

        with patch("builtins.input", typed), redirect_stdout(shown):
            self.assertIsNone(self.todo.prompt_install())
        return shown.getvalue()

    def test_each_key_runs_what_it_names(self):
        # « w » lance l'installation de toutes les versions ; « 1 », la
        # première version montrée, puis « 2 », avec ses modules extra ;
        # « 3 », puis « 0 », rien.
        from script.todo import todo

        for answers, command in (
            (["n", "w"], "make install_odoo_all_version"),
            (
                ["n", "1", "2"],
                "./script/version/update_env_version.py --erplibre_version"
                " odoo18.0_forged --install_dev --with_extra",
            ),
            (["n", "3", "0"], None),
        ):
            with self.subTest(answers=answers):
                todo.subprocess.run.reset_mock()
                self.screen("en", answers)
                ran = [
                    call.args[0]
                    for call in todo.subprocess.run.call_args_list
                    if call.kwargs.get("shell")
                ]
                self.assertEqual(ran, [command] if command else [])

    def test_it_speaks_the_chosen_language(self):
        # En français, aucun texte d'Install ne reste en anglais : la
        # détection, la question de la première installation, les trois
        # installations par touche et l'état de chaque version.
        english = self.screen("en", ["n", "0"])
        french = self.screen("fr", ["n", "0"])
        for text in (
            "Detect first installation",
            "First system installation?",
            "q: ERPLibre only without Odoo",
            "w: Install all Odoo version",
            "m: ERPLibre with mobile home",
            "Odoo 18.0 - Installed - Actual - Default",
            "Odoo 16.0 - Deprecated",
        ):
            with self.subTest(text=text):
                self.assertIn(text, english)
                self.assertNotIn(text, french)


class TestMainMenu(AnsweredMenu, unittest.TestCase):
    """Le menu principal, après le logo et « Opening TODO ... », la langue
    tenue pour choisie : chaque réponse vient d'une liste, et [0] quitte
    TODO."""

    def run_todo(self, *answers):
        """(ce que rend `run`, ce qu'il écrit) quand il reçoit `answers`."""
        shown = io.StringIO()
        with (
            patch("script.todo.todo.lang_is_configured", return_value=True),
            patch("click.prompt", side_effect=answers),
            redirect_stdout(shown),
        ):
            back = self.todo.run()
        return back, shown.getvalue()

    def test_quit_writes_nothing_after_its_answer(self):
        # [0] referme le menu sur la ligne vide qui suit toute réponse :
        # rien de la réponse ne s'écrit après elle.
        from script.todo.todo_i18n import t

        back, shown = self.run_todo("0")
        self.assertIsNone(back)
        intro = t("=> Enter your choice by number and press Enter!")
        self.assertTrue(shown.endswith(f"🤖 {intro}\n\n"), shown[-60:])

    def test_each_number_opens_the_menu_it_shows(self):
        # Chaque sous-menu est un double ; le menu se dessine une fois, et
        # « 9 », qu'il ne montre pas, n'est pas trouvé.
        from script.todo.todo import TODO
        from script.todo.todo_i18n import t

        names = (
            "prompt_execute",
            "prompt_install",
            "prompt_assistant",
            "prompt_telemetry",
            "prompt_configuration",
        )
        opened = Mock()
        with ExitStack() as stack:
            for name in names:
                stack.enter_context(
                    patch.object(TODO, name, getattr(opened, name))
                )
            back, shown = self.run_todo("1", "2", "3", "4", "5", "9", "0")
        self.assertIsNone(back)
        self.assertEqual([c[0] for c in opened.mock_calls], list(names))
        self.assertEqual(shown.count(t("Command not found !")), 1)

    def test_ctrl_c_at_its_question_ends_todo_without_a_word(self):
        # Ctrl+C ou Ctrl+D à la question du menu principal (l'Abort de
        # click) terminent TODO par SystemExit 0, sans ligne vide ; dans un
        # sous-menu, l'Abort remonte au-delà de `run`, que `__main__` ou le
        # worker rattrapent.
        import click

        from script.todo.todo import TODO
        from script.todo.todo_i18n import t

        shown = io.StringIO()
        with (
            patch("script.todo.todo.lang_is_configured", return_value=True),
            patch("click.prompt", side_effect=click.exceptions.Abort),
            redirect_stdout(shown),
            self.assertRaises(SystemExit) as ended,
        ):
            self.todo.run()
        self.assertEqual(ended.exception.code, 0)
        intro = t("=> Enter your choice by number and press Enter!")
        self.assertTrue(shown.getvalue().endswith(f"🤖 {intro}\n"))
        with (
            patch.object(
                TODO, "prompt_execute", side_effect=click.exceptions.Abort
            ),
            self.assertRaises(click.exceptions.Abort),
        ):
            self.run_todo("1")

    def test_its_zero_reads_quit(self):
        # [0] du menu principal quitte TODO : `fill_help_info` l'écrit
        # « 🚪 Quit », et une session web lit ce libellé pour [0].
        from script.todo.todo_i18n import t

        choices = [{"prompt_description": "Forged"}]
        text = self.todo.fill_help_info(choices, quits=True)
        self.assertTrue(text.endswith(f"[1] Forged\n[0] 🚪 {t('Quit')}\n"))


class TestMenuLabels(unittest.TestCase):
    """Tout menu tient son segment de fil d'Ariane de sa déclaration.

    Le navigateur ajoute au fil le `crumb` du menu qu'il ouvre, et celui
    d'une entrée qui en déclare un le temps de son action ; `_menu_header`
    écrit ce fil et en fait la clé de télémétrie. Un écran dessiné hors de
    là s'afficherait sous le fil de son parent, avec sa clé.

    Les écrans se trouvent par ce qu'ils APPELLENT — `navigate`,
    `fill_help_info` ou `_menu_header` — dans tout script/todo/*.py, et non
    par la table d'un menu : un écran ouvert depuis ailleurs, ou défini
    dans un mixin, comme le sous-menu VPN, serait manqué. Chacun est un
    menu déclaré avec son segment, l'un des menus déclarés sans segment
    que nomme `MENUS_SANS_SEGMENT`, l'action d'une entrée qui déclare son
    segment, ou l'une des exceptions.

    Quatre méthodes sont exemptées, qui s'affichent sous le fil du menu
    qui les ouvre : trois ACTIONS qui posent une question — un choix de
    méthode d'installation, un « aller plus loin » après un rapport — et
    non des écrans où l'on navigue, et `select_database`, celle de
    DatabaseManager, qui choisit une base. Leur donner un segment
    mettrait une miette sur une invite passagère.
    """

    ECRANS_EXEMPTES = {
        "_analyse_follow_up",
        "rtk_install",
        "execute_odoo_upgrade",
        "select_database",
    }
    # Les menus déclarés sans segment : chacun s'affiche sous le fil du
    # menu qui l'ouvre, sans clé de télémétrie à lui, et l'arbre fait une
    # feuille de l'entrée qui l'ouvre. La liste ne fait que rétrécir : un
    # menu neuf déclare son `crumb`.
    MENUS_SANS_SEGMENT = {
        "drop_database",
        "prompt_execute_mail",
        "prompt_mail_accounts",
        "prompt_mail_cache",
    }
    # Le segment de chaque menu déclaré, le dernier de sa clé de
    # télémétrie : un segment renommé change la clé, et les compteurs
    # d'avant ne s'y ajoutent plus.
    SEGMENTS = {
        "prompt_telemetry": "Navigation telemetry",
        "prompt_configuration": "Configuration",
        "prompt_execute": "Execute",
        "prompt_execute_code": "Code",
        "debug_ide": "Debug",
        "prompt_execute_config": "Config",
        "generate_config_from_preconfiguration": (
            "Generate from pre-configuration"
        ),
        "prompt_execute_process": "Process",
        "prompt_execute_test": "Test",
        "prompt_execute_update": "Update",
        "prompt_execute_instance": "Run",
        "prompt_execute_database": "Database",
        "drop_database": None,
        "prompt_execute_analyse": "Analyse",
        "prompt_execute_transform": "Transform data",
        "prompt_execute_doc": "Doc",
        "prompt_execute_git": "Git",
        "prompt_execute_git_local_server": "Git local server",
        "_prompt_git_server_local": "Actions",
        "_prompt_git_server_production": "Actions",
        "prompt_execute_gpt_code": "GPT code",
        "_prompt_claude_configs": "Claude configs",
        "prompt_execute_claude_plugins": "Plugins",
        "prompt_execute_rtk": "RTK",
        "prompt_claude_sessions": "Claude Code",
        "prompt_execute_function": "Automation",
        "prompt_execute_deploy": "Deploy",
        "prompt_execute_deploy_ssh": "SSH",
        "prompt_execute_network": "Network",
        "prompt_execute_security": "Security",
        "prompt_execute_qemu": "QEMU/KVM",
        "prompt_execute_qemu_cache": "QEMU cache",
        "_cache_service": "Service",
        "_cache_exceptions": "Exceptions",
        "_cache_miroir_git": "Git mirrors",
        "_cache_age": "Age and cleanup",
        "_cache_tests": "Tests",
        "_cache_journaux": "Logs",
        "_cache_nettoyage_auto": "Automatic cleanup",
        "prompt_execute_container": "Docker / Podman",
        "_container_service": "Service",
        "_container_compose": "Compose",
        "_container_erplibre": "ERPLibre container",
        "prompt_execute_proxmox": "Proxmox VE",
        "prompt_execute_vpn": "VPN",
        "prompt_execute_longtest": "Long test",
        "prompt_install": "Install",
        "prompt_assistant": "Assistant",
        "prompt_assistant_llm": "LLM",
        "_llm_servers": "Servers",
        "_llm_search": "Search",
        "prompt_execute_mail": None,
        "prompt_mail_accounts": None,
        "prompt_mail_cache": None,
        "run": "TODO",
    }

    @classmethod
    def setUpClass(cls):
        from script.todo.todo_telemetry import _declared_menus

        cls.menus = _declared_menus(TODO_DIR)
        # {action: segment} des entrées qui déclarent le leur.
        cls.ecrans = {
            item["action"]: item["crumb"]
            for menu in cls.menus.values()
            for item in menu["entries"]
            if item.get("crumb")
        }

    @staticmethod
    def _menus_par_fichier():
        """(fichier, méthode) de toute méthode qui dessine un écran, dans
        tout script/todo/*.py.

        Une méthode dessine un écran quand elle appelle `navigate`, qui
        ouvre un menu déclaré, ou `fill_help_info` ou `_menu_header`, qui
        écrivent l'en-tête. Les deux fonctions elles-mêmes sortent."""
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

    def test_no_screen_forgets_its_crumb(self):
        """Chaque écran est un menu déclaré avec son segment, l'un des
        MENUS_SANS_SEGMENT, l'action d'une entrée qui déclare son segment,
        ou une exception."""
        avec_segment = {n for n, m in self.menus.items() if m["crumb"]}
        missing = (
            self._menus_du_paquet()
            - avec_segment
            - self.MENUS_SANS_SEGMENT
            - set(self.ecrans)
            - self.ECRANS_EXEMPTES
        )
        self.assertEqual(missing, set(), "écrans sans segment déclaré")

    def test_no_new_menu_goes_without_a_crumb(self):
        """Un menu déclaré sans segment est l'un des MENUS_SANS_SEGMENT, où
        qu'il soit ouvert : la liste refuse un nom de plus, et un nom qui
        a désormais son segment."""
        sans = {n for n, m in self.menus.items() if m["crumb"] is None}
        self.assertEqual(
            sorted(sans - self.MENUS_SANS_SEGMENT),
            [],
            "donner son segment au menu neuf : Menu(name, crumb, …)",
        )
        self.assertEqual(
            sorted(self.MENUS_SANS_SEGMENT - sans),
            [],
            "ces menus ont leur segment : les retirer de MENUS_SANS_SEGMENT",
        )

    def test_each_declared_menu_keeps_its_crumb(self):
        """Un menu du registre garde son segment, le dernier de sa clé de
        télémétrie, et Over SSH, l'écran d'une entrée de Search, le sien."""
        self.assertEqual(
            {name: self.menus[name]["crumb"] for name in self.SEGMENTS},
            self.SEGMENTS,
        )
        self.assertEqual(self.ecrans, {"_llm_search_remote": "Over SSH"})
        # Une entrée qui ouvre un menu déclaré ne déclare pas de segment : le
        # navigateur empilerait les deux, et l'en-tête s'écarterait du
        # chemin de l'arbre, qui ne garde que celui du menu.
        self.assertEqual(set(self.ecrans) & set(self.menus), set())

    def test_no_second_list_repeats_the_crumbs(self):
        """Les segments ne s'écrivent qu'au registre : un dict de
        script/todo/ qui en répète plusieurs, en clés ou en valeurs, serait
        une seconde liste, que rien ne garderait d'accord avec les
        déclarations."""
        segments = {menu["crumb"] for menu in self.menus.values()} - {None}
        copies = []
        for chemin in sorted(TODO_DIR.rglob("*.py")):
            arbre = ast.parse(chemin.read_text(encoding="utf-8"))
            for noeud in ast.walk(arbre):
                if not isinstance(noeud, ast.Dict):
                    continue
                # Une clé dont la valeur est un dict est une entrée de la
                # table des traductions, qui traduit chaque libellé.
                cles = [
                    k
                    for k, v in zip(noeud.keys, noeud.values)
                    if not isinstance(v, ast.Dict)
                ]
                valeurs = {
                    c.value
                    for c in [*cles, *noeud.values]
                    if isinstance(c, ast.Constant)
                }
                if len(valeurs & segments) >= 3:
                    copies.append(f"{chemin.name}:{noeud.lineno}")
        self.assertEqual(copies, [])

    def test_the_database_manager_exemption_holds_in_its_file_only(self):
        """`select_database` n'est exemptée que dans database_manager.py :
        une méthode de même nom qui dessinerait un écran ailleurs resterait
        sans segment sans que rien ne le dise."""
        self.assertEqual(
            {
                f
                for f, n in self._menus_par_fichier()
                if n == "select_database"
            },
            {"database_manager.py"},
        )

    def test_no_stale_exemption(self):
        """Une exemption qui ne nomme plus un écran est à retirer."""
        fantomes = self.ECRANS_EXEMPTES - self._menus_du_paquet()
        self.assertEqual(fantomes, set())

    def test_an_exemption_is_never_also_declared(self):
        """Exempter ET déclarer dirait deux choses opposées du même écran."""
        declares = set(self.menus) | set(self.ecrans)
        self.assertEqual(self.ECRANS_EXEMPTES & declares, set())


if __name__ == "__main__":
    unittest.main()
