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
import json
import re
import tempfile
import unittest
from pathlib import Path

TODO_DIR = Path(__file__).resolve().parent.parent / "script" / "todo"
TODO_PY = TODO_DIR / "todo.py"

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
        "Transform data": "prompt_execute_transform",
        "Git": "prompt_execute_git",
        "Doc": "prompt_execute_doc",
        "GPT code": "prompt_execute_gpt_code",
        "Automation": "prompt_execute_function",
        "Deploy": "prompt_execute_deploy",
        "Devstack": "prompt_execute_devstack",
        "Network": "prompt_execute_network",
        "Security": "prompt_execute_security",
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
    # Le point où les entrées de todo.json entrent dans la liste. C'est LUI
    # qui coupe, et non le premier « get_config » venu : un menu peut lire une
    # préférence avant de bâtir ses choix, sans que le rang de rien ne bouge.
    RE_CONFIG_GRAFT = re.compile(
        r"choices\.extend\(|choices = self\.config_file\.get_config\("
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

    # Un numéro d'entrée écrit EN DUR dans un message d'aide. Rien ne le
    # relie à la liste : insérer une entrée au-dessus décale la cible, le
    # message continue de s'afficher, et il envoie désormais ailleurs.
    # La table est déclarative comme EXPECTED — un renvoi non déclaré est
    # un échec, sans quoi le prochain échapperait au contrôle.
    RENVOIS = {}
    # « \bt( » et non « t( » : sans la frontière, le motif attrape la fin
    # de « print( » et prend tout message imprimé pour un texte traduit.
    RE_RENVOI = re.compile(
        r"""\bt\(\s*\n?\s*["']([^"']*\[(\d+)\][^"']*)["']"""
    )

    def _entrees_par_numero(self):
        return {n: label for n, label in self.shown}

    def test_every_hardcoded_entry_number_points_where_it_means(self):
        source = self.SOURCE.read_text(encoding="utf-8")
        par_numero = self._entrees_par_numero()
        vus = set()
        for message, numero in self.RE_RENVOI.findall(source):
            numero = int(numero)
            vus.add((message, numero))
            self.assertIn(
                (message, numero),
                set(self.RENVOIS),
                f"« {message} » renvoie à [{numero}] et n'est pas déclaré :"
                " dire vers quelle entrée il pointe",
            )
            vise = par_numero.get(numero, "")
            self.assertTrue(
                vise.startswith(self.RENVOIS[(message, numero)]),
                f"« {message} » renvoie à [{numero}], qui est désormais"
                f" « {vise} » et non « {self.RENVOIS[(message, numero)]} »",
            )

    def test_no_stale_hardcoded_reference_is_declared(self):
        """Un renvoi déclaré que le code n'écrit plus laisse croire qu'un
        message est tenu alors qu'il a disparu."""
        source = self.SOURCE.read_text(encoding="utf-8")
        vus = {(m, int(n)) for m, n in self.RE_RENVOI.findall(source)}
        self.assertEqual(set(), set(self.RENVOIS) - vus)

    def test_self_dispatched_entries_name_a_real_method(self):
        """« method » est une chaîne : rien ne la relie au code sans ceci."""
        from script.todo.todo import TODO

        for label, method in self.self_dispatch.items():
            self.assertTrue(
                hasattr(TODO, method),
                f"« {label} » mène à {method}, qui n'existe pas",
            )

    def test_no_numbered_entry_follows_the_config_entries(self):
        """Une entrée codée en dur posée APRÈS les entrées de todo.json
        décale son propre rang du nombre d'entrées de configuration, que ce
        fichier ne peut pas connaître : son « elif status » atteint alors le
        voisin, et l'alignement numéro/dispatch reste vert. Le garde exige
        donc que tout ce qui suit la configuration porte « method », la seule
        forme dont le rang n'entre pas dans le calcul.
        """
        greffe = self.RE_CONFIG_GRAFT.search(self.body)
        coupe = greffe.start() if greffe else -1
        if coupe < 0:
            # Menu sans greffe de configuration : rien à contraindre. Le
            # contrôle positif plus bas prouve que la règle mord ailleurs.
            return
        for found in self.RE_ENTRY.finditer(self.body):
            if found.start() < coupe or found.group(1) != "prompt_description":
                continue
            self.assertIn(
                found.group(2),
                self.self_dispatch,
                f"« {found.group(2)} » suit les entrées de todo.json :"
                ' déclarez-la par "method", son numéro affiché n\'est pas'
                " celui que compte ce fichier",
            )


class TestLaParitéProxmox(unittest.TestCase):
    """Deux capacités que le menu QEMU/KVM a et que celui-ci doit avoir.

    Changer l'état d'une VM — que l'autre offre dans « Lister les VM » — et
    accepter les commandes ajoutées par todo.json. Deux menus qui visent le
    même travail et divergent sur ce qu'ils savent faire obligent à savoir
    lequel on a ouvert avant de chercher une entrée.
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

    def test_the_list_offers_the_detail_of_one_vm(self):
        """La liste rend cinq colonnes ; « qm status --verbose » en rend
        bien plus, et c'est le seul endroit du dépôt qui le demande.

        Le bâtisseur existait sans appelant : écrit, jamais câblé, donc
        invisible à l'usage — un écran ne dit pas ce qu'il ne montre pas.
        """
        import sys

        sys.argv = ["todo.py"]
        from script.proxmox import proxmox_deploy as pve
        from script.todo.todo import TODO as CLASSE

        self.assertIn("_pve_detail", self.src)
        self.assertTrue(callable(CLASSE._pve_detail))
        self.assertIn("status_cmd", self.src)
        self.assertIn("--verbose", pve.status_cmd(1))

    def test_typing_2_in_the_list_really_runs_the_detail(self):
        """L'entrée est IMPRIMÉE : la garde structurelle ne voit pas qu'elle
        mène nulle part.

        Une entrée affichée dont la répartition ne reconnaît pas le numéro
        rend la main sans un mot — l'écran promet alors une action qui
        n'existe pas. Chercher la méthode dans le source ne voit rien de
        cela : le numéro peut ne plus lui mener.
        """
        import builtins
        import io as _io
        import sys
        from contextlib import redirect_stdout

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO as CLASSE

        todo = CLASSE.__new__(CLASSE)
        vms = [
            {
                "vmid": 142,
                "name": "vm-essai",
                "status": "running",
                "mem": "2048",
                "disk": "12G",
            }
        ]
        jouees = []
        todo._pve_vms = lambda: list(vms)
        todo._pve_show = lambda cmd, timeout=120, quiet=False: (
            jouees.append(cmd) or (0, "")
        )
        saisies = iter(["2", "1"])
        vrai = builtins.input
        builtins.input = lambda *_a, **_k: next(saisies)
        try:
            with redirect_stdout(_io.StringIO()):
                todo._pve_list()
        finally:
            builtins.input = vrai
        self.assertEqual(["qm status 142 --verbose"], jouees)

    def test_the_detail_reuses_the_list_it_was_called_from(self):
        """Redemander « qm list » renumérote sur une liste qui peut avoir
        changé, et le numéro tapé porte alors sur la voisine. L'épreuve
        tient le PASSAGE de la liste, que rien d'autre ne rend visible."""
        import inspect
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO as CLASSE

        self.assertIn("vms", inspect.signature(CLASSE._pve_pick_vm).parameters)
        corps = inspect.getsource(CLASSE._pve_detail)
        self.assertIn("vms=vms", corps)

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

    def test_the_breadcrumb_names_the_proxmox_menu(self):
        # Sans étiquette, le fil d'Ariane sautait le menu Proxmox : on lisait
        # « TODO › Execute › Deploy » en étant deux niveaux plus bas.
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO as CLASSE

        self.assertIn("prompt_execute_proxmox", CLASSE._MENU_LABELS)


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


class TestDropDatabaseMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le sous-menu « Effacer une base », qui n'avait aucune table.

    LE TROU N'ÉTAIT PAS DANS UNE TABLE, IL ÉTAIT DANS LEUR LISTE. Chacune
    couvre exactement son écran, et les gardes du fichier rendent une
    entrée manquante impossible à laisser passer — mais seulement sur les
    écrans déclarés ici. Celui-ci ne l'était pas, et c'est le plus cher de
    tous : ses DEUX entrées effacent, et les intervertir efface tout là où
    l'on voulait effacer une seule base.
    """

    SOURCE = TODO_DIR / "database_manager.py"
    ENTRY = "def drop_database(self) -> None:"
    END = "def _drop_all_databases(self) -> None:"
    # Le plancher se FRANCHIT, il ne s'atteint pas : deux entrées demandent
    # donc 1. Le poser à 2 rendrait ce garde rouge sur un menu correct.
    MINIMUM = 1

    EXPECTED = {
        "Erase ALL databases": "_drop_all_databases",
        "Erase a single database": "_drop_single_database",
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
    """Le menu Proxmox : dix-huit entrées numérotées, le même piège.

    Quatre d'entre elles mènent VOLONTAIREMENT à des méthodes du menu QEMU —
    c'est le même travail, et le refactor n'a pas dupliqué ce code. La table
    le dit noir sur blanc : si quelqu'un les recopiait un jour, ce test
    montrerait que la cible a changé.
    """

    SOURCE = TODO_DIR / "proxmox_menu.py"
    ENTRY = "def prompt_execute_proxmox(self):"
    END = "def _pve_fetch_image(self):"
    MINIMUM = 15

    # Deux messages nomment une entrée par son NUMÉRO. Ils visent juste
    # aujourd'hui ; ils le resteront tant que ceci tient.
    RENVOIS = {
        ("No address yet. Try [6] later.", 6): "Show a VM IP address",
        (
            "Use [13] to add a ProxyJump entry, then a tunnel.",
            13,
        ): "SSH configuration",
    }

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
        # DÉCLARÉE PAR « method » et posée en fin de liste : son numéro
        # dépasse la chaîne d'elif, donc le repli lit la clé. C'est ce qui
        # permet d'ajouter une entrée sans décaler les dix-huit autres.
        "Verify a VM's egress posture": "_pve_verify_egress",
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
        "Forge (Forgejo/Gitea)": "prompt_execute_forge",
        "Install Starship on Shell": "_shell_install_starship",
        "Install Claude Code": "_shell_install_claude_code",
        "Install opencode": "_shell_install_opencode",
    }


class TestDeployMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Deploy, porte d'entrée de cinq sous-menus.

    Quatre de ses dix entrées OUVRENT un menu (SSH, QEMU/KVM, Proxmox VE,
    cache QEMU) et une cinquième un menu de mixin (VPN) : une renumérotation
    n'y donne pas une commande de travers, elle envoie dans le mauvais écran.
    """

    SOURCE = TODO_DIR / "todo.py"
    ENTRY = "def prompt_execute_deploy(self):"
    END = "def prompt_execute_deploy_ssh(self):"
    MINIMUM = 5

    EXPECTED = {
        "Clone ERPLibre locally": "_deploy_clone_erplibre",
        "Configure sshfs": "_configure_sshfs",
        "SSH port forwarding": "_deploy_port_forward",
        "Configure a SOCKS proxy over SSH": "_deploy_socks_proxy",
        "SSH (remote host)": "prompt_execute_deploy_ssh",
        "QEMU/KVM - Deploy an Ubuntu VM": "prompt_execute_qemu",
        "Proxmox VE - Deploy a VM": "prompt_execute_proxmox",
        "Deploy - Install NTFY": "_deploy_ntfy_server",
        "QEMU cache - Download mirror for local VMs": "prompt_execute_qemu_cache",
        "VPN - Tunnels": "prompt_execute_vpn",
        # NEUVIÈME, déclarée par « method » : son rang n'entre pas dans le
        # calcul, et c'est pourquoi les huit qui la précèdent n'ont pas
        # bougé — dont les rangs 6 et 7, qu'une épreuve Proxmox cherche en
        # chaînes littérales.
        "Deploy - VM backends": "_deploy_vm_backends",
        # ONZIÈME, greffée par « method » juste après le choix des
        # backends : c'est là qu'on lit ce qu'une machine atteint.
        "Deploy - Site address book": "prompt_execute_egress_book",
        # DOUZIÈME, même greffe et même raison.
        "Lima - instances": "prompt_execute_lima",
        # DIXIÈME, même greffe et même raison : les rangs codés en dur
        # s'arrêtent à huit, et une entrée posée plus haut les décalerait.
        "Deploy - verify this station, layer by layer": (
            "_qemu_verify_station"
        ),
        "Deploy - verify a deployed VM, layer by layer": "_qemu_verify_vm",
    }


class TestDeploySshMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Deploy › SSH : onze entrées, aucune section, aucun garde.

    Ses cinq dernières AGISSENT sur un hôte distant — installer, redémarrer,
    poser une unité systemd, réécrire un vhost nginx. Un décalage d'un rang
    y fait redémarrer Odoo là où on demandait un journal.
    """

    SOURCE = TODO_DIR / "todo.py"
    ENTRY = "def prompt_execute_deploy_ssh(self):"
    END = "def _native_arch():"
    MINIMUM = 8

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
        # Déclarée par « method » : son rang n'entre pas dans le calcul, et
        # c'est pourquoi les onze qui la précèdent n'ont pas bougé.
        "SSH - Choose the target machine": "_deploy_ssh_targets",
    }


class TestVpnMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu VPN : onze entrées en trois sections, aucun garde.

    Sa neuvième EFFACE un profil et ses secrets ; ses trois sections font
    qu'aucun rang ne se lit à l'œil sur la liste.
    """

    SOURCE = TODO_DIR / "vpn_menu.py"
    ENTRY = "def prompt_execute_vpn(self):"
    END = "def _vpn_cli(self, arguments, secrets_env=None):"
    MINIMUM = 5

    EXPECTED = {
        "VPN - Connect a profile": "_vpn_connect",
        "VPN - Disconnect a profile": "_vpn_disconnect",
        "VPN - Status and diagnosis": "_vpn_diagnose",
        "VPN - Create a profile from a site preset": "_vpn_from_preset",
        "VPN - Import an AnyConnect profile (.xml)": "_vpn_import_anyconnect",
        "VPN - Add or edit a profile": "_vpn_edit_profile",
        "VPN - Store secrets": "_vpn_store_secrets",
        "VPN - Show the rendered configuration": "_vpn_show_config",
        "VPN - Delete a profile": "_vpn_delete_profile",
        "VPN - Install the client packages": "_vpn_install",
        "VPN - What can this machine do?": "_vpn_check",
    }


class TestLimaMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Lima : huit entrées en trois sections, aucun garde.

    Sa sixième DÉTRUIT une instance et son disque ; sa huitième lance une
    installation détachée qui dure une demi-heure. Trois sections font
    qu'aucun rang ne se lit à l'œil sur la liste, et un « elif » oublié
    ferait lancer l'entrée voisine sous le libellé attendu.
    """

    SOURCE = TODO_DIR / "lima_menu.py"
    ENTRY = "def prompt_execute_lima(self):"
    END = "def _lima_tool(self):"
    MINIMUM = 5

    EXPECTED = {
        "Lima - How this host gets the tool": "_lima_tool",
        "Lima - List the instances": "_lima_list",
        "Lima - Create and start an instance": "_lima_create",
        "Lima - Start an instance": "_lima_power",
        "Lima - Stop an instance": "_lima_power",
        "Lima - Delete an instance": "_lima_delete",
        "Lima - Open a shell in an instance": "_lima_shell",
        "Lima - Install ERPLibre in an instance": "_lima_install_erplibre",
        "Lima - Verify an instance's egress posture": "_lima_verify_egress",
    }


class TestQemuNetworkSection(unittest.TestCase):
    """La section « VM network » du menu QEMU/KVM est un point de greffe.

    Une entrée qui s'y ajoute tombe AU MILIEU de la liste : tout ce qui suit
    se renumérote, et TestQemuMenuNumbering le voit. Ce qu'il ne voit pas,
    c'est une entrée réseau posée sous une AUTRE section — elle s'affiche
    alors sous « VM access » ou « Troubleshoot », où personne ne la cherche.
    Ce test épingle l'appartenance, que le socle ne regarde pas.
    """

    SECTION = "VM network"
    MEMBRES = (
        "Show the libvirt network state",
        "Recreate the VM subnet (stop, redefine, restart)",
    )

    def setUp(self):
        source = (TODO_DIR / "qemu_menu.py").read_text(encoding="utf-8")
        start = source.index("def prompt_execute_qemu(self):")
        end = source.index("def _qemu_stats(self):", start)
        section = None
        self.par_section = {}
        for kind, label in MenuCoherence.RE_ENTRY.findall(source[start:end]):
            if kind == "section":
                section = label
                continue
            self.par_section.setdefault(section, []).append(label)

    def test_the_sections_were_actually_parsed(self):
        self.assertGreater(len(self.par_section), 3)

    def test_the_network_section_holds_exactly_its_entries(self):
        self.assertEqual(
            tuple(self.par_section.get(self.SECTION, ())), self.MEMBRES
        )


# Un menu de banc d'essai : trois entrées, deux sections, aucun rapport avec
# le dépôt. Les noms sont INVENTÉS — un exemple qui illustre un défaut ne se
# prend pas dans le code réel, sinon le contrôle fige un vrai libellé.
BANC_MENU_SAIN = """
    def prompt_execute_banc(self):
        choices = [
            {"section": t("Banc alpha")},
            {"prompt_description": t("Banc - premiere entree")},
            {"prompt_description": t("Banc - deuxieme entree")},
            {"section": t("Banc beta")},
            {"prompt_description": t("Banc - troisieme entree")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            if status == "0":
                return False
            elif status == "1":
                self._banc_une()
            elif status == "2":
                self._banc_deux()
            elif status == "3":
                self._banc_trois()

    def _banc_fin(self):
        pass
"""

BANC_EXPECTED = {
    "Banc - premiere entree": "_banc_une",
    "Banc - deuxieme entree": "_banc_deux",
    "Banc - troisieme entree": "_banc_trois",
}


def _banc_echecs(source, expected=None):
    """Fait tourner le socle sur un menu de banc d'essai et rend le NOM des
    tests qui tombent. Le fichier est écrit dans un répertoire temporaire :
    le socle lit du texte, il n'a besoin d'aucun module importable."""
    with tempfile.TemporaryDirectory() as tmp:
        chemin = Path(tmp) / "banc_menu.py"
        chemin.write_text(source, encoding="utf-8")
        classe = type(
            "BancMenuNumbering",
            (MenuCoherence, unittest.TestCase),
            {
                "SOURCE": chemin,
                "ENTRY": "def prompt_execute_banc(self):",
                "END": "def _banc_fin(self):",
                "MINIMUM": 2,
                "EXPECTED": dict(
                    BANC_EXPECTED if expected is None else expected
                ),
            },
        )
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(classe)
        resultat = unittest.TestResult()
        suite.run(resultat)
        return {
            cas._testMethodName
            for cas, _ in (resultat.failures + resultat.errors)
        }


class TestLeGardeAttrapeUneMauvaiseInsertion(unittest.TestCase):
    """Le contrôle positif du garde lui-même.

    Les sous-classes ci-dessus prouvent que rien n'est cassé AUJOURD'HUI.
    Elles ne prouvent pas que le socle attraperait une faute : un motif qui
    ne correspond à rien lit zéro entrée et passe au vert sur tout. Chaque
    test ci-dessous abîme le banc d'une façon précise et exige que le socle
    tombe, sur le test qu'on croit.
    """

    def test_the_sane_bench_passes(self):
        # Sans celui-ci, un banc cassé pour une raison quelconque ferait
        # passer les cinq autres pour de bonnes nouvelles.
        self.assertEqual(_banc_echecs(BANC_MENU_SAIN), set())

    def test_a_swapped_dispatch_is_caught(self):
        abime = BANC_MENU_SAIN.replace(
            "self._banc_deux()", "self._banc_trois()"
        ).replace(
            'elif status == "3":\n                self._banc_trois()',
            'elif status == "3":\n                self._banc_deux()',
        )
        self.assertIn(
            "test_every_entry_reaches_the_method_it_names",
            _banc_echecs(abime),
        )

    def test_an_entry_without_dispatch_is_caught(self):
        abime = BANC_MENU_SAIN.replace(
            '{"prompt_description": t("Banc - troisieme entree")},',
            '{"prompt_description": t("Banc - troisieme entree")},\n'
            '            {"prompt_description": t("Banc - quatrieme entree")},',
        )
        echecs = _banc_echecs(
            abime,
            dict(BANC_EXPECTED, **{"Banc - quatrieme entree": "_banc_quatre"}),
        )
        self.assertIn("test_the_menu_was_actually_parsed", echecs)
        self.assertIn(
            "test_every_shown_entry_has_the_matching_dispatch", echecs
        )

    def test_an_insertion_in_the_middle_is_caught(self):
        # La faute exacte que ce fichier existe pour attraper : une entrée
        # posée avant la dernière, dispatchée au rang qu'elle occupait avant.
        abime = BANC_MENU_SAIN.replace(
            '{"prompt_description": t("Banc - deuxieme entree")},',
            '{"prompt_description": t("Banc - intercalee")},\n'
            '            {"prompt_description": t("Banc - deuxieme entree")},',
        ).replace(
            'elif status == "1":\n                self._banc_une()',
            'elif status == "1":\n                self._banc_une()\n'
            '            elif status == "4":\n'
            "                self._banc_intercalee()",
        )
        self.assertIn(
            "test_every_entry_reaches_the_method_it_names",
            _banc_echecs(
                abime,
                dict(
                    BANC_EXPECTED,
                    **{"Banc - intercalee": "_banc_intercalee"},
                ),
            ),
        )

    def test_an_entry_missing_from_expected_is_caught(self):
        abime = BANC_MENU_SAIN.replace(
            "Banc - troisieme entree", "Banc - jamais declaree"
        )
        self.assertIn(
            "test_every_entry_reaches_the_method_it_names",
            _banc_echecs(abime),
        )

    def test_a_method_naming_nothing_is_caught(self):
        abime = BANC_MENU_SAIN.replace(
            '{"prompt_description": t("Banc - troisieme entree")},',
            "{\n"
            '                "prompt_description": t('
            '"Banc - troisieme entree"),\n'
            '                "method": "_banc_methode_absente",\n'
            "            },",
        ).replace(
            'elif status == "3":\n                self._banc_trois()', ""
        )
        self.assertIn(
            "test_self_dispatched_entries_name_a_real_method",
            _banc_echecs(
                abime,
                dict(
                    BANC_EXPECTED,
                    **{"Banc - troisieme entree": "_banc_methode_absente"},
                ),
            ),
        )

    def test_a_numbered_entry_after_the_config_entries_is_caught(self):
        # Le trou que ce garde bouche : l'entrée codée en dur posée après
        # la greffe de todo.json garde un alignement numéro/dispatch parfait
        # dans le source, et s'affiche pourtant deux rangs plus loin.
        abime = BANC_MENU_SAIN.replace(
            "        help_info = self.fill_help_info(choices)",
            "        extra = self.config_file.get_config('banc_from_makefile')"
            "\n        if extra:\n            choices.extend(extra)\n"
            "        choices.append(\n"
            '            {"prompt_description": t("Banc - apres config")}\n'
            "        )\n"
            "        help_info = self.fill_help_info(choices)",
        ).replace(
            'elif status == "3":\n                self._banc_trois()',
            'elif status == "3":\n                self._banc_trois()\n'
            '            elif status == "4":\n'
            "                self._banc_apres()",
        )
        self.assertIn(
            "test_no_numbered_entry_follows_the_config_entries",
            _banc_echecs(
                abime,
                dict(BANC_EXPECTED, **{"Banc - apres config": "_banc_apres"}),
            ),
        )


class TestLaGreffeEstJouable(unittest.TestCase):
    """Une entrée de todo.json affichée mais injouable est décorative.

    Le rang d'une entrée greffée dépasse la chaîne d'« elif » codée en dur du
    menu : sans le repli, la taper répond « commande introuvable ». Les
    épreuves de TestMenuDispatchExtra exercent le repli SEUL — retirer son
    appel du menu les laisse toutes vertes, et c'est le câblage qui compte.
    """

    GREFFE = re.compile(
        r"choices\.extend\(|choices = self\.config_file\.get_config\("
    )
    # Deux façons de jouer une entrée greffée : le repli partagé, ou la copie
    # que six menus portent encore en propre. L'épreuve tient sur la CAPACITÉ,
    # pas sur le moyen — router les six est un commit à part.
    REPLIS = ("_menu_dispatch_extra", "execute_from_configuration")

    def menus_greffes(self, chemin):
        """(nom, corps) de chaque prompt_execute_* qui lit todo.json."""
        source = chemin.read_text(encoding="utf-8")
        arbre = ast.parse(source)
        trouves = []
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.FunctionDef):
                continue
            if not noeud.name.startswith("prompt_execute"):
                continue
            corps = ast.get_source_segment(source, noeud) or ""
            if self.GREFFE.search(corps):
                trouves.append((noeud.name, corps))
        return trouves

    def test_every_grafted_menu_routes_its_fallback(self):
        greffes = []
        for chemin in (TODO_DIR / "todo.py", TODO_DIR / "qemu_menu.py"):
            greffes += self.menus_greffes(chemin)
        self.assertTrue(greffes, "aucune greffe trouvée : rien n'est prouvé")
        sans_repli = [
            nom
            for nom, corps in greffes
            if not any(repli in corps for repli in self.REPLIS)
        ]
        self.assertEqual(
            [],
            sans_repli,
            "ces menus affichent des entrées de todo.json sans pouvoir les"
            f" jouer : {', '.join(sans_repli)}",
        )

    def test_the_scan_would_notice_a_menu_without_the_fallback(self):
        """Contrôle positif : sans lui, un scanner qui ne trouve aucun menu
        greffé passerait l'épreuve ci-dessus en n'ayant rien regardé."""
        faux = (
            "def prompt_execute_banc(self):\n"
            "    choices = self.config_file.get_config('banc')\n"
            "    return choices\n"
        )
        arbre = ast.parse(faux)
        corps = ast.get_source_segment(faux, arbre.body[0])
        self.assertTrue(self.GREFFE.search(corps))
        for repli in self.REPLIS:
            self.assertNotIn(repli, corps)


class TestMenuDispatchExtra(unittest.TestCase):
    """Le repli des menus : le rang tapé désigne-t-il l'entrée affichée ?

    Rien n'exerçait ce chemin. Il porte pourtant deux pièges : les sections,
    qui s'affichent sans consommer de numéro, et la clé « method », que
    execute_from_configuration ne lit pas — une entrée qui la porte
    s'exécuterait en silence sans rien faire si le repli ne la voyait pas.
    """

    def setUp(self):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        self.todo = TODO()
        self.joues = []
        self.todo.execute_from_configuration = self.joues.append
        self.todo._banc_greffe = lambda: self.joues.append("_banc_greffe")
        self.choices = [
            {"section": "Banc alpha"},
            {"prompt_description": "Banc - une"},
            {"section": "Banc beta"},
            {"prompt_description": "Banc - deux"},
            {"prompt_description": "Banc - trois", "method": "_banc_greffe"},
        ]

    def test_a_section_does_not_consume_a_number(self):
        self.assertTrue(self.todo._menu_dispatch_extra(self.choices, "2"))
        self.assertEqual(self.joues, [{"prompt_description": "Banc - deux"}])

    def test_a_method_entry_calls_its_method(self):
        self.assertTrue(self.todo._menu_dispatch_extra(self.choices, "3"))
        self.assertEqual(self.joues, ["_banc_greffe"])

    def test_a_rank_past_the_end_plays_nothing(self):
        self.assertFalse(self.todo._menu_dispatch_extra(self.choices, "4"))
        self.assertEqual(self.joues, [])

    def test_zero_plays_nothing(self):
        self.assertFalse(self.todo._menu_dispatch_extra(self.choices, "0"))
        self.assertEqual(self.joues, [])

    def test_a_non_numeric_answer_plays_nothing(self):
        self.assertFalse(self.todo._menu_dispatch_extra(self.choices, "oui"))
        self.assertEqual(self.joues, [])


class TestTodoJsonExtensionPoints(unittest.TestCase):
    """Les points de greffe déclarés dans todo.json.

    get_config rend None sur une clé absente : un menu qui lit une clé jamais
    déclarée se tait, et l'extension n'existe que dans le code. Les déclarer
    VIDES est ce qui les rend trouvables par qui cherche où greffer.
    """

    @classmethod
    def setUpClass(cls):
        cls.conf = json.loads(
            (TODO_DIR / "todo.json").read_text(encoding="utf-8")
        )

    def test_deploy_has_its_extension_key(self):
        self.assertIsInstance(self.conf.get("deploy_from_makefile"), list)

    def test_the_devstack_section_is_a_mapping(self):
        self.assertIsInstance(self.conf.get("devstack"), dict)

    def test_every_key_a_menu_reads_is_declared(self):
        lues = set()
        for fichier in sorted(TODO_DIR.glob("*.py")):
            lues |= set(
                re.findall(
                    r'get_config\("(\w+_from_makefile)"\)',
                    fichier.read_text(encoding="utf-8"),
                )
            )
        # Sur un motif qui ne trouve rien, la comparaison suivante est vraie
        # sans rien prouver.
        self.assertGreater(len(lues), 3)
        self.assertEqual(lues - set(self.conf), set())


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

    # VIDE, et c'est le but : la liste était « figée pour que le nombre ne
    # grandisse pas, pas pour bénir ce qu'elle contient ». Les trois ont
    # leur étiquette.
    ECRANS_EXEMPTES: set = set()

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

    @staticmethod
    def _menus_du_paquet():
        """Toute méthode qui dessine un menu, dans tout script/todo/*.py.

        Une méthode dessine un menu quand elle appelle `fill_help_info` ou
        `_menu_header` : c'est par là que passe l'en-tête, donc c'est là que
        l'étiquette manque ou non. Les deux fonctions elles-mêmes sortent."""
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
                }
                if not {"fill_help_info", "_menu_header"} & appels:
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

    def test_no_stale_exemption(self):
        """Une exemption qui ne nomme plus un menu est à retirer."""
        fantomes = self.ECRANS_EXEMPTES - self._menus_du_paquet()
        self.assertEqual(fantomes, set())

    def test_an_exemption_is_never_also_labelled(self):
        """Exempter ET étiqueter dirait deux choses opposées du même écran."""
        self.assertEqual(self.ECRANS_EXEMPTES & self.labels, set())

    def test_no_menu_anywhere_forgets_its_label(self):
        """La garde ne voyait que les menus atteints depuis « Execute ».

        Elle en connaissait trois sans étiquette ; il y en avait NEUF. Les
        six autres se rejoignent depuis un autre menu — Deploy, Database —
        et leur fil d'Ariane était muet sans que rien ne le dise.

        Ce qui fait un menu, et non une action : il liste des choix et
        boucle sur une saisie. `prompt_uninstall_theme` fait une chose et
        rend la main ; il n'a rien à situer.
        """
        racine = TODO_PY.parent
        manquants = []
        for chemin in sorted(racine.rglob("*.py")):
            arbre = ast.parse(chemin.read_text(encoding="utf-8"))
            lignes = chemin.read_text(encoding="utf-8").splitlines()
            for noeud in ast.walk(arbre):
                if not isinstance(noeud, ast.FunctionDef):
                    continue
                if not noeud.name.startswith("prompt_"):
                    continue
                corps = "\n".join(lignes[noeud.lineno - 1 : noeud.end_lineno])
                if "fill_help_info" not in corps or "while True" not in corps:
                    continue
                if noeud.name not in self.labels:
                    manquants.append(
                        f"{chemin.name}:{noeud.lineno} {noeud.name}"
                    )
        self.assertEqual([], manquants)

    def test_the_menu_scan_actually_finds_menus(self):
        """Sur zéro menu trouvé, la garde passe et ne tient rien."""
        self.assertGreater(len(self.labels), 25)


if __name__ == "__main__":
    unittest.main()
