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
import contextlib
import re
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
    # Jusqu'à la méthode SUIVANTE, quelle qu'elle soit : une méthode insérée
    # après prompt_execute ne doit pas entrer dans le corps analysé.
    end = source.index("\n    def ", start)
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
        "Uninstall": "prompt_execute_uninstall",
        "Image Odoo": "prompt_execute_image_db",
        "Analyse module": "prompt_execute_module_analysis",
        "Python": "prompt_execute_python",
        "Git repository": "prompt_execute_git",
        "Database": "prompt_execute_database",
        "Analyse": "prompt_execute_analyse",
        "Transform data": "prompt_execute_transform",
        "Shell": "prompt_execute_shell",
        "Doc": "prompt_execute_doc",
        "GPT code": "prompt_execute_gpt_code",
        "Automation": "prompt_execute_function",
        "Deploy": "prompt_execute_deploy",
        "Network": "prompt_execute_network",
        "Security": "prompt_execute_security",
        "Docker / Podman": "prompt_execute_container",
        "System": "prompt_execute_system",
        "ERPLibre Home": "prompt_execute_streamdeck",
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


class TestLaParitéProxmox(unittest.TestCase):
    """Le menu Proxmox tient deux capacités que son vis-à-vis porte.

    Changer l'état d'une VM, que QEMU/KVM offre dans « Lister les VM », et
    accepter les commandes ajoutées par todo.json. Deux menus qui gèrent des
    machines et divergent sur ce point obligent à savoir lequel on a ouvert
    avant de savoir ce qu'on peut y faire.
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

    Une entrée sans icône se perd dans une liste de dix-neuf : l'œil s'y
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
        "USB devices (Stream Deck)": "🔌",
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
        "Reinstall QEMU/libvirt": "_qemu_reinstall_host",
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
        "USB devices": "_qemu_usb_menu",
    }


class TestQemuUsbMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le sous-menu USB de QEMU/KVM, dans script/todo/qemu_usb_menu.py :
    trois sections, neuf entrées."""

    SOURCE = TODO_DIR / "qemu_usb_menu.py"
    ENTRY = "def _qemu_usb_menu(self):"
    END = "def _qemu_usb_capture("
    MINIMUM = 6

    EXPECTED = {
        "List the USB devices": "_qemu_usb_list",
        "Attach a USB device": "_qemu_usb_attach",
        "Detach a USB device": "_qemu_usb_detach",
        "Show the USB devices of a VM": "_qemu_usb_show",
        "Open virt-viewer": "_qemu_usb_viewer",
        "Enable SPICE USB redirection": "_qemu_usb_enable_spice",
        "Disable SPICE USB redirection": "_qemu_usb_disable_spice",
        "Auto-reattach on replug": "_qemu_usb_autoreattach",
        "Restart a USB device": "_qemu_usb_restart",
    }


class TestContainerMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Docker / Podman, dont les sections ne consomment pas de
    numéro : la section des bases, ajoutée en fin, ne doit rien décaler."""

    SOURCE = TODO_DIR / "container_menu.py"
    ENTRY = "def prompt_execute_container(self):"
    END = "def _container_libelle_moteur(self, nom):"

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
        "Disk space": "_container_espace_disque",
        "Restore a .zip backup": "_container_restaurer_base",
        "Delete a database": "_container_supprimer_base",
    }


class TestStreamDeckMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu ERPLibre Home, dans script/todo/streamdeck_menu.py :
    extension GNOME, Stream Deck, réglages du deck, état, jeux, réunis sous
    une entrée d'Exécution."""

    SOURCE = TODO_DIR / "streamdeck_menu.py"
    ENTRY = "def prompt_execute_streamdeck(self):"
    END = "def _streamdeck_probe(argv):"
    MINIMUM = 9

    # « Games on/off » avant « Games » : _key prend le premier préfixe.
    EXPECTED = {
        "Games on/off": "_streamdeck_games_setting",
        "Plugins on/off": "_streamdeck_plugins_setting",
        "Session refresh": "_streamdeck_session_refresh_setting",
        "Games": "prompt_execute_streamdeck_games",
        "Status": "_streamdeck_status",
        "Service": "_streamdeck_service",
        "Deck program": "_streamdeck_program",
        "Autostart": "_streamdeck_autostart",
        "Diagnosis": "_streamdeck_diagnosis",
        "Install the GNOME extension": "_erplibre_home_install_local",
        "Install the Stream Deck": "_erplibre_home_streamdeck_install_local",
        "Uninstall everything": "_erplibre_home_uninstall_all",
        "Uninstall the Stream Deck level": "_streamdeck_uninstall",
        "Extension": "_streamdeck_extension",
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


class TestPythonMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Python regroupe des outils qui vivent AUSSI ailleurs.

    « Upgrade Poetry » est dans Code › Update et pip-audit dans Security :
    les deux chemins doivent mener à la MÊME méthode. Une copie ici
    divergerait en silence de l'original au premier correctif.
    """

    SOURCE = TODO_DIR / "python_menu.py"
    ENTRY = "def prompt_execute_python(self):"
    END = "def _python_versions_etat(self):"
    MINIMUM = 5

    EXPECTED = {
        "Lock drift": "execute_poetry_drift",
        "Python versions": "execute_python_versions",
        "Upgrade Poetry": "upgrade_poetry",
        "pip-audit": "execute_pip_audit",
        "Install mise": "execute_install_mise",
        "Install uv": "execute_install_uv",
    }

    def test_les_deux_chemins_menent_a_la_meme_methode(self):
        todo_py = (TODO_DIR / "todo.py").read_text(encoding="utf-8")
        debut = todo_py.index("def prompt_execute_update(self):")
        update = todo_py[debut : todo_py.index("help_info =", debut)]
        self.assertIn('"method": "upgrade_poetry"', update)
        debut = todo_py.index("def prompt_execute_security(self):")
        fin = todo_py.index("def prompt_execute_test", debut)
        securite = todo_py[debut:fin]
        self.assertIn("self.execute_pip_audit()", securite)


class TestSecurityMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Security : l'audit des dépendances, puis la génération de
    clé, sceau PAdES (sous-menu) et clé SSH."""

    SOURCE = TODO_PY
    ENTRY = "def prompt_execute_security(self):"
    END = "def prompt_execute_test(self):"
    MINIMUM = 2

    EXPECTED = {
        "pip-audit": "execute_pip_audit",
        "Seal for PAdES signature": "prompt_execute_seal",
        "SSH key": "execute_generate_ssh_key",
    }


class TestSealMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le sous-menu du sceau PAdES, dans script/todo/seal_menu.py."""

    SOURCE = TODO_DIR / "seal_menu.py"
    ENTRY = "def prompt_execute_seal(self):"
    END = "def execute_seal_status(self):"
    MINIMUM = 2

    EXPECTED = {
        "Status of the generated seals": "execute_seal_status",
        "Internal or external key?": "execute_seal_guide",
        "Generate an internal PAdES seal": "execute_generate_seal",
    }

    def test_the_texts_cite_the_entries_they_name(self):
        """seal_menu.py renvoie à « l'entrée 1 » : ses ENTREE_* doivent
        suivre la numérotation du sous-menu."""
        from script.todo import seal_menu

        rangs = {label: str(num) for num, label in self.shown}
        self.assertEqual(
            seal_menu.ENTREE_ETAT, rangs["Status of the generated seals"]
        )
        self.assertEqual(
            seal_menu.ENTREE_GUIDE, rangs["Internal or external key?"]
        )
        self.assertEqual(
            seal_menu.ENTREE_GENERER,
            rangs["Generate an internal PAdES seal (self-signed)"],
        )


class TestInstallUpdateMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Installation › Mise à jour, dans install_update_menu.py :
    chaque entrée mène à la méthode du menu Python ou des dépôts qui fait
    déjà le travail."""

    SOURCE = TODO_DIR / "install_update_menu.py"
    ENTRY = "def prompt_install_update(self):"
    END = "def execute_update_repos("
    MINIMUM = 3

    EXPECTED = {
        "Python versions": "execute_python_versions",
        "Lock drift": "execute_poetry_drift",
        "Resynchronize the repositories": "execute_update_repos",
        "⬇️ Pull the repositories": "_git_repo_tirer",
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
        "Erase databases": "drop_database",
    }


class TestProxmoxMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Proxmox : dix-neuf entrées, le même piège.

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
        "USB devices (Stream Deck)": "_pve_usb",
        "List available images": "_qemu_list_images",
        "Proxmox - example sequence": "_pve_example",
        "Change the Proxmox host": "_pve_forget_host",
    }


class TestGitMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Git, où les entrées de todo.json s'insèrent entre sections.

    Les entrées de `git_from_makefile` vont dans la section que nomme leur
    « menu_group » : leur nombre n'est pas connu à la lecture du source, donc
    chaque entrée codée en dur porte « method » et aucune n'a de numéro
    dans un « elif ». Une entrée codée en dur sans « method » lancerait la
    commande de configuration du même rang sous son libellé.
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
        "🔃 Update git repo": "prompt_execute_git_repo",
        "🍴 Fork a repository for an organisation": "_git_fork_organisation",
        "➕ Add a repository to a manifest": "_git_ajouter_depot",
        "📁 Add a repository from an existing directory": "_git_ajouter_existant",
        "🌿 Create a branch in a repository": "_git_creer_branche",
        "🌳 Create the same branch in several repositories": "_git_creer_branche_plusieurs",
        "🔭 Add the upstream remote of a repository": "_git_ajouter_amont",
        "⏩ Update forks from their upstream on GitHub": "_git_mettre_forks_a_jour",
        "🪦 List the orphan forks of an organisation": "_git_forks_orphelins",
        "➖ Remove a repository from a manifest": "_git_retirer_depot",
        "🔄 Synchronise one repository": "_git_synchroniser_depot",
        "🧊 Freeze one repository on a commit": "_git_regeler_depot",
        "🧹 Clean the merged branches of a repository": "_git_nettoyer_branches",
        "📋 List the pull requests of an organisation": "_git_lister_pull_requests",
        "📬 Open a pull request from the current branch": "_git_creer_pull_request",
        "🚦 Status of my pull requests (review, CI, merged)": "_git_statut_mes_pull_requests",
        "🔑 Check the GitHub token (scopes, organisation)": "_git_verifier_jeton",
        "Kill git daemon server process": "process_kill_git_daemon",
    }


class TestShellMenu(unittest.TestCase):
    """Le menu Shell garde ce que le menu Git avait d'étranger à git."""

    def test_shell_lists_the_three_installations(self):
        import sys
        from unittest import mock

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO
        from script.todo.todo_i18n import t

        obj = TODO.__new__(TODO)
        appels = []
        with (
            mock.patch.object(TODO, "fill_help_info", return_value="") as aide,
            mock.patch(
                "script.todo.todo.click.prompt", side_effect=["2", "0"]
            ),
            mock.patch.object(
                TODO,
                "_shell_install_claude_code",
                lambda _self: appels.append("claude"),
            ),
            mock.patch("builtins.print"),
        ):
            self.assertIs(obj.prompt_execute_shell(), False)
        self.assertEqual(appels, ["claude"])
        libelles = [
            c.get("prompt_description") for c in aide.call_args.args[0]
        ]
        self.assertEqual(
            libelles,
            [
                None,
                t("Install Starship on Shell"),
                t("Install Claude Code"),
                t("Install opencode"),
            ],
        )


class TestGitMenuSections(unittest.TestCase):
    """Le menu Git tel qu'il s'affiche, entrées de todo.json comprises."""

    @classmethod
    def setUpClass(cls):
        import json
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        cls.TODO = TODO
        with open(TODO_DIR / "todo.json", encoding="utf-8") as fh:
            cls.config = json.load(fh)["git_from_makefile"]

    def setUp(self):
        self.obj = self.TODO.__new__(self.TODO)

    def libelles(self, choices):
        """(section, libellé de l'entrée) dans l'ordre affiché."""
        rangs, section = [], None
        for c in choices:
            if c.get("section"):
                section = c["section"]
                continue
            libelle = c.get("prompt_description_key") or c.get(
                "prompt_description"
            )
            rangs.append((section, libelle))
        return rangs

    def test_sections_and_order(self):
        from script.todo.todo_i18n import t

        rangs = self.libelles(self.obj._git_menu_choices(self.config))
        self.assertEqual(
            rangs,
            [
                (t("Repositories"), t("🔃 Update git repo")),
                (t("Repositories"), "Show code status"),
                (t("Repositories"), "Stash all code"),
                (t("Repositories"), t("🔄 Synchronise one repository")),
                (t("Repositories"), t("🧊 Freeze one repository on a commit")),
                (t("Manifest"), t("➕ Add a repository to a manifest")),
                (
                    t("Manifest"),
                    t("📁 Add a repository from an existing directory"),
                ),
                (t("Manifest"), t("➖ Remove a repository from a manifest")),
                (t("Forks"), t("🍴 Fork a repository for an organisation")),
                (t("Forks"), t("🔭 Add the upstream remote of a repository")),
                (
                    t("Forks"),
                    t("⏩ Update forks from their upstream on GitHub"),
                ),
                (t("Forks"), t("🪦 List the orphan forks of an organisation")),
                (
                    t("Forks"),
                    t("🔑 Check the GitHub token (scopes, organisation)"),
                ),
                (t("Branches"), t("🌿 Create a branch in a repository")),
                (
                    t("Branches"),
                    t("🌳 Create the same branch in several repositories"),
                ),
                (
                    t("Branches"),
                    t("🧹 Clean the merged branches of a repository"),
                ),
                (
                    t("Pull requests"),
                    t("📋 List the pull requests of an organisation"),
                ),
                (
                    t("Pull requests"),
                    t("📬 Open a pull request from the current branch"),
                ),
                (
                    t("Pull requests"),
                    t("🚦 Status of my pull requests (review, CI, merged)"),
                ),
                (
                    t("Settings"),
                    t("Install git hooks (commit-msg, pre-commit)"),
                ),
                (
                    t("Settings"),
                    t("Set merge.conflictStyle to zdiff3 (global)"),
                ),
                (t("Settings"), "Configure git local editor to vim"),
                (t("Tools"), t("Add a remote to a local repository")),
                (t("Tools"), "Generate git patch to /tmp"),
                (t("Server"), t("Local git server")),
                (t("Server"), t("Kill git daemon server process")),
            ],
        )

    def test_no_section_holds_more_than_five_entries(self):
        """Au-delà de cinq entrées, une section se lit mal : on la coupe."""
        from collections import Counter

        rangs = self.libelles(self.obj._git_menu_choices(self.config))
        trop = {
            section: nombre
            for section, nombre in Counter(s for s, _l in rangs).items()
            if nombre > 5
        }
        self.assertEqual(trop, {})

    def test_an_entry_without_group_lands_in_tools(self):
        """« Ajouter une automatisation » écrit une entrée sans groupe."""
        from script.todo.todo_i18n import t

        ajout = {"prompt_description": "X", "bash_command": "true"}
        inconnu = dict(ajout, prompt_description="Y", menu_group="zzz")
        rangs = self.libelles(self.obj._git_menu_choices([ajout, inconnu]))
        self.assertIn((t("Tools"), "X"), rangs)
        self.assertIn((t("Tools"), "Y"), rangs)

    def test_the_typed_number_skips_the_sections(self):
        """[22] est l'éditeur vim, après vingt et une entrées et six sections."""
        from unittest import mock

        self.obj.config_file = mock.Mock()
        self.obj.config_file.get_config.return_value = self.config
        appels = []
        with (
            mock.patch.object(self.TODO, "fill_help_info", return_value=""),
            mock.patch(
                "script.todo.todo.click.prompt", side_effect=["22", "1", "0"]
            ),
            mock.patch.object(
                self.TODO,
                "execute_from_configuration",
                lambda _self, inst: appels.append(inst["bash_command"]),
                create=True,
            ),
            mock.patch.object(
                self.TODO,
                "prompt_execute_git_repo",
                lambda _self: appels.append("repo"),
            ),
        ):
            self.assertIs(self.obj.prompt_execute_git(), False)
        self.assertEqual(
            appels, ['git config --global core.editor "vim"', "repo"]
        )


class TestGitRepoMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu de mise à jour et de mise à niveau des dépôts git.

    Ses entrées sont séparées par des titres de section, qui ne consomment
    aucun numéro : une section ajoutée entre deux entrées ne doit décaler
    aucun dispatch, et c'est précisément ce que ce socle vérifie.
    """

    SOURCE = TODO_DIR / "git_repo_menu.py"
    ENTRY = "def prompt_execute_git_repo(self):"
    END = "def _git_repo_sync(self):"
    MINIMUM = 9

    EXPECTED = {
        "🔄 Synchronize the repositories": "_git_repo_sync",
        "🔁 Switch to development: each repository follows its branch": "_git_repo_reconfigurer",
        "⬇️ Pull the repositories": "_git_repo_tirer",
        "🌐 Add the upstream remotes": "_git_repo_ajouter_remotes",
        "🔍 Upgrade — dry run": "_git_repo_a_sec",
        "⬆️ Apply the upgrade": "_git_repo_appliquer",
        "🧩 Conflict queue": "_git_repo_file_conflits",
        "📤 Publish the updated forks": "_git_repo_publier",
        "📊 Report of the last pass": "_git_repo_rapport",
        "🖥️ Browse the upgrade on screen": "_git_repo_ecran",
        "🔗 Fork and upstream status": "_git_repo_etat_forks",
        "🧊 Freeze the versions": "_git_repo_geler",
        "📌 Switch to production: each repository on its frozen commit": "_git_repo_reconfigurer",
        "🫗 Unfreeze the versions": "_git_repo_geler",
        "🔀 Compare two freezes": "_git_repo_comparer",
        "📡 Push the repositories to a remote": "_git_repo_pousser_remote",
        "📬 Open pull requests on a forge": "_git_repo_pull_requests",
        "🧭 Sync from a forge: private manifest overlay": "_git_repo_surcouche",
    }

    def test_the_upstream_remotes_come_before_the_dry_run(self):
        """« Tirer les dépôts » ferme la section de la mise à jour en [3] ;
        « Ajouter les remotes amont » ouvre celle de la mise à niveau en
        [4], la passe à sec suit en [5], la comparaison en [15]."""
        rangs = {label: num for num, label in self.shown}
        self.assertEqual(rangs["⬇️ Pull the repositories"], 3)
        self.assertEqual(rangs["🌐 Add the upstream remotes"], 4)
        self.assertEqual(rangs["🔍 Upgrade — dry run"], 5)
        self.assertEqual(rangs["🔀 Compare two freezes"], 15)

    def test_the_upstream_remotes_entry_reports_without_diagnosing(self):
        from unittest import mock

        from script.todo import git_repo_menu

        lst = [
            {"chemin": "x/a", "cible": "U/18.0"},
            {"chemin": "x/b", "cible": None},
        ]

        class Menu(git_repo_menu.GitRepoMenuMixin):
            pass

        ru = git_repo_menu.repo_upgrade
        with mock.patch.object(
            ru, "versions_installees", return_value=["18.0"]
        ), mock.patch.object(
            ru, "ajouter_remotes", return_value=lst
        ) as ajouter, mock.patch.object(
            ru, "render_remotes", return_value=""
        ) as rendu, mock.patch.object(
            ru, "passe_diagnostic"
        ) as diagnostic, mock.patch(
            "builtins.print"
        ):
            self.assertEqual(Menu()._git_repo_choix("4"), None)
        ajouter.assert_called_once()
        rendu.assert_called_once()
        diagnostic.assert_not_called()

    def test_the_upstream_remotes_entry_covers_every_installed_version(self):
        """Chaque version d'Odoo du checkout, dans l'ordre, et non la
        seule active : synchroniser une autre version en a besoin."""
        from unittest import mock

        from script.todo import git_repo_menu

        class Menu(git_repo_menu.GitRepoMenuMixin):
            pass

        ru = git_repo_menu.repo_upgrade
        with mock.patch.object(
            ru, "versions_installees", return_value=["16.0", "17.0", "18.0"]
        ), mock.patch.object(
            ru, "ajouter_remotes", return_value=[{"cible": "U/x"}]
        ) as ajouter, mock.patch.object(
            ru, "render_remotes", return_value=""
        ) as rendu, mock.patch(
            "builtins.print"
        ):
            recuperes = Menu()._git_repo_ajouter_remotes()
        self.assertEqual(
            ["16.0", "17.0", "18.0"],
            [appel.args[0] for appel in ajouter.call_args_list],
        )
        self.assertEqual(3, rendu.call_count)
        self.assertEqual(3, recuperes)


class TestGitRepoApprofondir(unittest.TestCase):
    """Les clones superficiels du diagnostic : une question, non par défaut,
    puis le diagnostic refait sur les clones complétés. `repo_upgrade` est
    simulé."""

    CANDIDAT = {
        "chemin": "odooX.0/odoo",
        "revision": "ERPLibre/X.0",
        "amont": {"remote": "OCA", "branche": "X.0"},
        "verdict": "non_comparable",
    }

    def _lancer(self, reponse, issue="complet"):
        from unittest import mock

        from script.todo import git_repo_menu

        class Menu(git_repo_menu.GitRepoMenuMixin):
            pass

        ru = git_repo_menu.repo_upgrade
        refait = [dict(self.CANDIDAT, verdict="a_rebaser")]
        res = {"issue": issue, "erreur": None, "commandes": ["git fetch"]}
        with mock.patch.object(
            ru, "a_approfondir", side_effect=lambda x, _r: "amont" in x
        ), mock.patch.object(
            ru, "approfondir", return_value=res
        ) as approfondir, mock.patch.object(
            ru, "passe_diagnostic", return_value=refait
        ) as diagnostic, mock.patch.object(
            ru, "render_diagnostic", return_value=""
        ), mock.patch(
            "builtins.input", return_value=reponse
        ), mock.patch(
            "builtins.print"
        ):
            lst = [self.CANDIDAT, {"chemin": "autre"}]
            rendu = Menu()._git_repo_approfondir(lst, "X.0")
        return lst, rendu, approfondir, diagnostic, refait

    def test_sans_oui_rien_n_est_lance(self):
        lst, rendu, approfondir, diagnostic, _refait = self._lancer("")
        self.assertIs(rendu, lst)
        approfondir.assert_not_called()
        diagnostic.assert_not_called()

    def test_oui_complete_puis_refait_le_diagnostic(self):
        _lst, rendu, approfondir, diagnostic, refait = self._lancer("o")
        approfondir.assert_called_once()
        self.assertEqual(approfondir.call_args.args[0], self.CANDIDAT)
        diagnostic.assert_called_once()
        self.assertIs(rendu, refait)

    def test_un_echec_ne_refait_pas_le_diagnostic(self):
        lst, rendu, approfondir, diagnostic, _r = self._lancer(
            "y", issue="fork_echoue"
        )
        approfondir.assert_called_once()
        diagnostic.assert_not_called()
        self.assertIs(rendu, lst)


class TestGitRepoPull(unittest.TestCase):
    """« Tirer les dépôts » : l'essai à sec d'abord, chaque question à part,
    et la passe seulement sur un oui. `repo_pull` est simulé."""

    SHA_C = "c" * 40
    SHA_H = "d" * 40

    def setUp(self):
        from unittest import mock

        from script.git import repo_pull
        from script.todo import git_repo_menu

        self.mock = mock
        self.rp = repo_pull
        self.menu = git_repo_menu

        class Menu(git_repo_menu.GitRepoMenuMixin):
            pass

        self.obj = Menu()

    def donnees(self, plan=(), superficiel=(), nouveaux=(), sale=False):
        depots = [
            {
                "chemin": p,
                "sale": sale,
                "sauvegarde_prefixe": "X.0_avant_pull_",
            }
            for p in list(plan) + list(superficiel)
        ]
        return {
            "plan": list(plan),
            "plan_superficiel": list(superficiel),
            "plan_nouveaux": list(nouveaux),
            "attendus": [f"{p}={self.SHA_C}:{self.SHA_H}" for p in plan],
            "attendus_superficiel": [
                f"{p}={self.SHA_C}:{self.SHA_H}" for p in superficiel
            ],
            "depots": depots,
        }

    def tirer(
        self,
        donnees,
        reponses,
        charge=None,
        code=0,
        installe=({}, 0),
        verrou=None,
    ):
        """Lance l'entrée, `repo_pull` simulé ; `verrou` remplace celui du
        checkout. Rend (passe, installer, input) ; les lignes affichées
        sont dans `self.affiche`."""
        charge = charge or {
            "horodatage": "20990101T0800",
            "dossier": "tasks/git_repo_pull/20990101T0800",
            "resultats": [],
            "dependances": {"a_installer": False},
        }
        m = self.mock
        verrou = verrou or (lambda racine: contextlib.nullcontext())
        with (
            m.patch.object(self.rp, "verrou", side_effect=verrou),
            m.patch.object(
                self.rp, "diagnostic", return_value=(donnees, 0)
            ) as self.diagnostic,
            m.patch.object(self.rp, "render_diagnostic", return_value=""),
            m.patch.object(self.rp, "render_passe", return_value=""),
            m.patch.object(
                self.rp, "passe", return_value=(charge, code)
            ) as passe,
            m.patch.object(
                self.rp, "installer_dependances", return_value=installe
            ) as installer,
            m.patch.object(
                self.menu.click, "prompt", side_effect=["1", "rebase"]
            ) as self.prompt,
            m.patch.object(
                self.menu.repo_upgrade, "version_active", return_value="X.0"
            ),
            m.patch("builtins.input", side_effect=list(reponses)) as entree,
            m.patch("builtins.print") as affiche,
        ):
            self.obj._git_repo_tirer()
        self.affiche = "\n".join(
            " ".join(str(x) for x in c.args) for c in affiche.call_args_list
        )
        return passe, installer, entree

    def test_plan_vide_ne_demande_rien(self):
        passe, _i, entree = self.tirer(self.donnees(), [])
        passe.assert_not_called()
        entree.assert_not_called()

    def test_non_n_ecrit_rien(self):
        passe, _i, entree = self.tirer(self.donnees(["x/a"]), ["n"])
        passe.assert_not_called()
        self.assertEqual(entree.call_count, 1)

    def test_oui_passe_les_attendus_de_l_essai(self):
        donnees = self.donnees(["x/a"])
        passe, _i, _e = self.tirer(donnees, ["y"])
        passe.assert_called_once()
        kw = passe.call_args.kwargs
        self.assertEqual(kw["attendus"], ["x/a"])
        self.assertEqual(
            kw["epingles"],
            {"x/a": {"cible_sha": self.SHA_C, "head": self.SHA_H}},
        )
        self.assertFalse(kw["approfondir"])
        self.assertFalse(kw["cloner"])
        self.assertEqual(passe.call_args.args[2:4], ("manifeste", "rebase"))

    def test_superficiel_et_nouveaux_demandes_a_part(self):
        donnees = self.donnees(["x/a"], ["x/s"], ["x/n"])
        passe, _i, entree = self.tirer(donnees, ["o", "oui", "yes"])
        self.assertEqual(entree.call_count, 3)
        kw = passe.call_args.kwargs
        self.assertEqual(kw["attendus"], ["x/a", "x/s"])
        self.assertTrue(kw["approfondir"])
        self.assertTrue(kw["cloner"])
        self.assertEqual(kw["attendus_clone"], ["x/n"])

    def test_dependances_demandees_seulement_a_installer(self):
        charge = {
            "horodatage": "20990101T0800",
            "dossier": None,
            "resultats": [],
            "dependances": {"a_installer": True, "commande": "poetry"},
        }
        _p, installer, entree = self.tirer(
            self.donnees(["x/a"]), ["y", "y"], charge
        )
        self.assertEqual(entree.call_count, 2)
        installer.assert_called_once_with(
            self.menu.RACINE, "X.0", "20990101T0800", en_direct=True
        )
        _p, installer, entree = self.tirer(self.donnees(["x/a"]), ["y"])
        self.assertEqual(entree.call_count, 1)
        installer.assert_not_called()

    def charge_a_installer(self):
        return {
            "horodatage": "20990101T0800",
            "dossier": "tasks/git_repo_pull/20990101T0800",
            "resultats": [],
            "dependances": {"a_installer": True, "commande": "poetry"},
        }

    def test_installation_refusee_donne_la_commande_gardee(self):
        self.tirer(
            self.donnees(["x/a"]), ["y", "n"], self.charge_a_installer()
        )
        self.assertIn(
            "script/git/repo_pull.py --install-deps --confirm X.0"
            " --pass 20990101T0800",
            self.affiche,
        )
        self.assertNotIn("bin/poetry install", self.affiche)

    def test_installation_echouee_le_dit(self):
        dossier = "tasks/git_repo_pull/20990101T0800"
        absent = (
            {
                "error": "poetry not found: .venv.x/bin/poetry",
                "code": None,
                "dossier": dossier,
            },
            self.rp.EXIT_DEPS,
        )
        self.tirer(
            self.donnees(["x/a"]),
            ["y", "y"],
            self.charge_a_installer(),
            installe=absent,
        )
        self.assertIn(".venv.x/bin/poetry", self.affiche)
        self.assertIn(str(self.rp.EXIT_DEPS), self.affiche)
        self.assertNotIn("deps.log", self.affiche)
        self.assertIn("--install-deps", self.affiche)
        echec = (
            {"error": "poetry install failed", "code": 1, "dossier": dossier},
            self.rp.EXIT_DEPS,
        )
        self.tirer(
            self.donnees(["x/a"]),
            ["y", "y"],
            self.charge_a_installer(),
            installe=echec,
        )
        self.assertIn(f"{dossier}/deps.log", self.affiche)
        self.assertIn("--install-deps", self.affiche)

    def test_installation_reussie_le_dit(self):
        self.tirer(
            self.donnees(["x/a"]),
            ["y", "y"],
            self.charge_a_installer(),
            installe=({"code": 0}, 0),
        )
        self.assertIn(
            self.menu.t("The Python dependencies are installed."), self.affiche
        )

    def test_rien_a_tirer_apres_les_refus(self):
        donnees = self.donnees([], ["x/s"], ["x/n"])
        passe, _i, entree = self.tirer(donnees, ["n", "n"])
        self.assertEqual(entree.call_count, 2)
        passe.assert_not_called()

    def test_clonage_seul_annonce(self):
        donnees = self.donnees([], [], ["x/n"])
        donnees["manifeste"] = {"changements": [{"chemin": "x/n"}]}
        passe, _i, entree = self.tirer(donnees, ["y", "y"])
        self.assertEqual(entree.call_count, 2)
        passe.assert_called_once()
        self.assertIn("x/n", self.affiche)
        self.assertIn("erplibre_manifest.xml", self.affiche)

    def test_essai_sous_le_verrou(self):
        tenus = []

        @contextlib.contextmanager
        def verrou(racine):
            tenus.append(racine)
            yield

        self.tirer(self.donnees(), [], verrou=verrou)
        self.assertEqual(tenus, [self.menu.RACINE])
        self.diagnostic.assert_called_once()

    def test_verrou_pris_n_interroge_rien(self):
        def verrou(racine):
            raise self.rp.Occupe("pris")

        passe, _i, entree = self.tirer(
            self.donnees(["x/a"]), [], verrou=verrou
        )
        self.diagnostic.assert_not_called()
        passe.assert_not_called()
        self.assertIn(
            self.menu.t("Another pull is running on this checkout."),
            self.affiche,
        )

    def test_le_mode_est_un_choix(self):
        self.tirer(self.donnees(), [])
        _args, kw = self.prompt.call_args_list[0]
        self.assertEqual(list(kw["type"].choices), ["1", "2"])


class TestGitRepoPushToRemote(unittest.TestCase):
    """L'entrée « Pousser les dépôts vers un remote » : le choix du remote,
    d'un remote neuf posé à partir de l'URL d'une forge, du contenu, et la
    confirmation avant tout push. Git est remplacé : ses effets se testent
    dans test_push_remote."""

    PROJETS = [
        {
            "chemin": "odooX.0/a",
            "nom": "a.git",
            "remote": "Orig",
            "branche": "X.0",
            "proprietaire": "Proprio",
        },
        {
            "chemin": "odooX.0/b",
            "nom": "b.git",
            "remote": "Orig",
            "branche": "X.0",
            "proprietaire": None,
        },
    ]

    def setUp(self):
        import copy
        from unittest import mock

        from script.todo import git_repo_menu

        self.mock = mock
        self.menu = git_repo_menu
        self.prm = git_repo_menu.push_remote
        self.poussees = []
        self.poses = []
        self.approfondis = []
        self.etat_pose = "ajoute"

        def pousser(cibles, jobs=None, suivi=None):
            self.poussees.extend(cibles)
            return [dict(c, code=0, erreur="") for c in cibles]

        def poser(chemin, nom, url):
            self.poses.append((chemin, nom, url))
            return self.etat_pose, None

        for nom, valeur in (
            ("projets_actifs", lambda: copy.deepcopy(self.PROJETS)),
            ("remotes_des_clones", lambda chemins, jobs=8: {"Orig": 2}),
            ("projet_racine", lambda racine, remote="origin": None),
            ("pousser_en_parallele", pousser),
            ("poser_remote", poser),
            (
                "approfondir",
                lambda chemin, remote: self.approfondis.append(chemin)
                or (0, ""),
            ),
            (
                "preparer_cibles",
                lambda projets, remote, mode: (
                    [
                        {
                            "chemin": p["chemin"],
                            "remote": remote,
                            "specs": [mode],
                        }
                        for p in projets
                    ],
                    [],
                ),
            ),
        ):
            patcheur = mock.patch.object(self.prm, nom, side_effect=valeur)
            patcheur.start()
            self.addCleanup(patcheur.stop)
        superficiel = mock.patch.object(
            git_repo_menu.repo_upgrade,
            "est_superficiel",
            side_effect=lambda chemin: chemin.endswith("odooX.0/a")
            and self.superficiel,
        )
        superficiel.start()
        self.addCleanup(superficiel.stop)
        self.superficiel = False

        class Menu(git_repo_menu.GitRepoMenuMixin):
            pass

        self.obj = Menu()

    def lancer(self, prompts, confirms):
        with self.mock.patch.object(
            self.menu.click, "prompt", side_effect=list(prompts)
        ), self.mock.patch.object(
            self.menu.click, "confirm", side_effect=list(confirms)
        ) as confirm, self.mock.patch(
            "builtins.print"
        ):
            code = self.obj._git_repo_pousser_remote()
        return code, confirm

    def test_an_existing_remote_pushes_after_consent(self):
        code, _ = self.lancer(["1", "manifest"], [True])
        self.assertEqual(code, 0)
        self.assertEqual({c["remote"] for c in self.poussees}, {"Orig"})
        self.assertEqual(
            {tuple(c["specs"]) for c in self.poussees}, {("manifest",)}
        )
        self.assertTrue(
            all(
                c["chemin"].startswith(self.menu.RACINE) for c in self.poussees
            )
        )

    def test_nothing_is_pushed_without_consent(self):
        self.lancer(["1", "all"], [False])
        self.assertEqual(self.poussees, [])

    def test_the_lightest_content_is_the_default(self):
        with self.mock.patch.object(
            self.menu.click, "prompt", side_effect=["1", "manifest"]
        ) as prompt, self.mock.patch.object(
            self.menu.click, "confirm", return_value=False
        ), self.mock.patch(
            "builtins.print"
        ):
            self.obj._git_repo_pousser_remote()
        self.assertEqual(
            prompt.call_args_list[1].kwargs["default"], self.prm.MODE_MANIFESTE
        )

    def test_a_new_remote_is_set_from_the_forge_url(self):
        self.lancer(
            ["n", "forge", "ssh://git@forge.example.invalid:2222", "manifest"],
            # Ajouter le remote, ne pas préparer la forge, pousser.
            [True, False, True],
        )
        self.assertEqual(len(self.poses), 1)
        chemin, nom, url = self.poses[0]
        self.assertTrue(chemin.endswith("odooX.0/a"))
        self.assertEqual(
            (nom, url),
            ("forge", "ssh://git@forge.example.invalid:2222/Proprio/a.git"),
        )
        # Le projet sans propriétaire connu n'est ni posé ni poussé.
        self.assertEqual(
            [c["chemin"].rsplit("/", 1)[1] for c in self.poussees], ["a"]
        )
        self.assertEqual({c["remote"] for c in self.poussees}, {"forge"})

    def test_a_clone_whose_remote_points_elsewhere_is_left_out(self):
        self.etat_pose = "autre_url"
        self.lancer(
            ["n", "forge", "https://forge.example.invalid", "manifest"],
            [True, True],
        )
        self.assertEqual(self.poussees, [])

    def test_a_forge_that_cannot_be_prepared_stops_unless_pushing_anyway(self):
        """Forge non préparée (client None) : « pousser quand même » non
        par défaut, et rien ne part sur un non."""
        with self.mock.patch.object(
            type(self.obj), "_git_forge_client", return_value=None
        ):
            self.lancer(
                ["n", "forge", "https://forge.example.invalid", "manifest"],
                [True, True, False],
            )
        self.assertEqual(self.poussees, [])

    def test_an_unsafe_remote_name_is_refused(self):
        code, confirm = self.lancer(["n", "equipe/forge"], [])
        self.assertEqual((code, self.poses, self.poussees), (0, [], []))
        confirm.assert_not_called()

    def test_a_manifest_remote_name_is_refused(self):
        code, confirm = self.lancer(["n", "Orig"], [])
        self.assertEqual(code, 0)
        self.assertEqual((self.poses, self.poussees), ([], []))
        confirm.assert_not_called()

    def test_a_string_that_is_not_a_forge_url_is_refused(self):
        self.lancer(["n", "forge", "forge.example.invalid"], [])
        self.assertEqual((self.poses, self.poussees), ([], []))

    def test_shallow_clones_are_deepened_only_on_request(self):
        self.superficiel = True
        self.lancer(["1", "manifest"], [False, True])
        self.assertEqual(self.approfondis, [])
        self.poussees.clear()
        self.lancer(["1", "manifest"], [True, True])
        self.assertEqual(len(self.approfondis), 1)
        self.assertTrue(self.approfondis[0].endswith("odooX.0/a"))

    def test_qemu_creates_the_forge_then_its_base_is_used(self):
        base = "ssh://git@192.0.2.7:2222"
        with self.mock.patch.object(
            type(self.obj), "_git_forge_creer_vm", return_value=base
        ) as creer:
            self.lancer(
                ["n", "forge", "qemu", "manifest"],
                # Ajouter le remote, ne pas préparer la forge, pousser.
                [True, False, True],
            )
        self.assertEqual(
            [p["proprietaire"] for p in creer.call_args[0][0]],
            ["Proprio", None],
        )
        self.assertEqual(self.poses[0][2], f"{base}/Proprio/a.git")

    def test_a_forge_vm_not_created_cancels(self):
        with self.mock.patch.object(
            type(self.obj), "_git_forge_creer_vm", return_value=None
        ):
            code, _ = self.lancer(["n", "forge", "qemu"], [])
        self.assertEqual((code, self.poses, self.poussees), (0, [], []))

    def test_the_erplibre_repository_is_pushed_first_on_request(self):
        racine = {
            "cle": "erplibre",
            "chemin": self.menu.RACINE,
            "nom": "erplibre",
            "remote": "origin",
            "branche": "dev/x",
            "proprietaire": "ERPLibre",
        }
        with self.mock.patch.object(
            self.prm, "projet_racine", return_value=dict(racine)
        ):
            self.lancer(["1", "manifest"], [True, True])
        self.assertEqual(self.poussees[0]["chemin"], self.menu.RACINE)
        self.assertEqual(len(self.poussees), 3)
        self.poussees.clear()
        with self.mock.patch.object(
            self.prm, "projet_racine", return_value=dict(racine)
        ):
            self.lancer(["1", "manifest"], [False, True])
        self.assertNotIn(
            self.menu.RACINE, [c["chemin"] for c in self.poussees]
        )

    def test_the_overlay_is_offered_after_a_push_to_a_forge(self):
        """Après un push vers un remote de forge, la surcouche se propose
        pour les clones poussés, jamais pour le dépôt ERPLibre."""
        base = "ssh://git@forge.example.invalid:2222"
        racine = {
            "cle": "erplibre",
            "chemin": self.menu.RACINE,
            "nom": "erplibre",
            "remote": "origin",
            "branche": "dev/x",
            "proprietaire": "ERPLibre",
        }
        with self.mock.patch.object(
            self.prm, "projet_racine", return_value=racine
        ), self.mock.patch.object(
            self.menu.forge_manifest, "base_du_remote", return_value=base
        ), self.mock.patch.object(
            type(self.obj), "_git_repo_ecrire_surcouche", return_value=True
        ) as ecrire:
            self.lancer(
                ["n", "forge", base, "manifest"],
                # Le dépôt ERPLibre, ajouter le remote, ne pas préparer la
                # forge, pousser, écrire la surcouche.
                [True, True, False, True, True],
            )
        nom, base_ecrite, projets = ecrire.call_args[0]
        self.assertEqual((nom, base_ecrite), ("forge", base))
        self.assertEqual(
            [p["chemin"].rsplit("/", 1)[1] for p in projets], ["a"]
        )

    def test_no_overlay_for_a_manifest_remote(self):
        with self.mock.patch.object(
            type(self.obj), "_git_repo_proposer_surcouche"
        ) as proposer:
            self.lancer(["1", "manifest"], [True])
        proposer.assert_not_called()


class TestGitForgeCreerVm(unittest.TestCase):
    """La forge créée dans une VM QEMU au choix du remote : la VM, son
    jeton et son mot de passe administrateur, et la session qui retient
    l'URL web et le jeton. `forge_vm.deployer` est remplacé."""

    BASE = "ssh://git@192.0.2.7:2222"
    WEB = "http://192.0.2.7:3000"

    def setUp(self):
        from unittest import mock

        from script.todo import git_repo_menu

        self.mock = mock
        self.menu = git_repo_menu
        from script.forgejo import forge_vm

        self.fv = forge_vm
        self.forge = {
            "nom": "forge-x",
            "uuid": "u",
            "ip": "192.0.2.7",
            "web": self.WEB,
            "base_ssh": self.BASE,
            "admin": "forge-admin",
            "mot_de_passe": "mdp-tire-au-hasard",
            "jeton": "jeton-neuf",
            "version": "17.0",
            "client": None,
        }
        for nom, valeur in (
            ("cle_publique", "/k.pub"),
            ("enregistrer_cle_hote", True),
        ):
            p = mock.patch.object(forge_vm, nom, return_value=valeur)
            p.start()
            self.addCleanup(p.stop)
        self.deployer = mock.patch.object(
            forge_vm, "deployer", return_value=dict(self.forge)
        ).start()
        self.addCleanup(mock.patch.stopall)
        self.sudo = mock.patch(
            "subprocess.run", return_value=mock.Mock(returncode=0)
        ).start()
        self.dossier = mock.patch("os.makedirs").start()

        class Menu(git_repo_menu.GitRepoMenuMixin):
            _QEMU_ERPLIBRE_VENV_CMD = "venv"

            def _qemu_vm_ip(self, nom, timeout=600):
                return "192.0.2.7"

            def _qemu_cache_ca_path(self):
                return ""

        self.obj = Menu()
        self.ranges = []
        self.coffre = True

        def ranger(titre, secret, compte=""):
            if self.coffre:
                self.ranges.append((titre, secret, compte))
            return self.coffre

        mock.patch.object(
            Menu, "_git_forge_ranger", side_effect=ranger
        ).start()
        mock.patch.object(
            Menu, "_git_forge_creer_coffre", return_value=False
        ).start()

    def creer(self, prompts, confirms, projets=()):
        sortie = []
        with self.mock.patch.object(
            self.menu.click, "prompt", side_effect=list(prompts)
        ), self.mock.patch.object(
            self.menu.click, "confirm", side_effect=list(confirms)
        ), self.mock.patch(
            "builtins.print",
            side_effect=lambda *a, **k: sortie.append(" ".join(map(str, a))),
        ):
            base = self.obj._git_forge_creer_vm(list(projets))
        return base, "\n".join(sortie)

    def test_the_vm_is_created_and_its_secrets_stored(self):
        base, sortie = self.creer(["forge-x", "forge-admin"], [True])
        self.assertEqual(base, self.BASE)
        args = self.deployer.call_args
        self.assertEqual(args[0][:2], ("forge-x", "forge-admin"))
        self.assertEqual(args[0][5], "venv")
        self.assertEqual(args.kwargs["cache"], ["--cache-bypass"])
        self.assertEqual(
            self.ranges,
            [
                ("Forgejo token 192.0.2.7:3000", "jeton-neuf", ""),
                (
                    "Forgejo admin 192.0.2.7:3000",
                    "mdp-tire-au-hasard",
                    "forge-admin",
                ),
            ],
        )
        self.assertNotIn("mdp-tire-au-hasard", sortie)
        self.assertEqual(
            self.obj._git_forge_session[self.BASE],
            {"web": self.WEB, "jeton": "jeton-neuf"},
        )

    def test_without_vault_the_password_is_shown_once(self):
        self.coffre = False
        base, sortie = self.creer(["forge-x", "forge-admin"], [True])
        self.assertEqual(base, self.BASE)
        self.assertEqual(sortie.count("mdp-tire-au-hasard"), 1)

    def test_an_admin_named_like_an_owner_is_refused(self):
        base, _ = self.creer(
            ["forge-x", "proprio"], [], projets=[{"proprietaire": "Proprio"}]
        )
        self.assertIsNone(base)
        self.deployer.assert_not_called()

    def test_refused_sudo_creates_nothing(self):
        self.sudo.return_value = self.mock.Mock(returncode=1)
        base, _ = self.creer(["forge-x", "forge-admin"], [True])
        self.assertIsNone(base)
        self.deployer.assert_not_called()

    def test_a_failed_deployment_leaves_no_session(self):
        self.deployer.return_value = None
        base, _ = self.creer(["forge-x", "forge-admin"], [True])
        self.assertIsNone(base)
        self.assertFalse(getattr(self.obj, "_git_forge_session", {}))

    def test_the_session_spares_the_token_question(self):
        self.creer(["forge-x", "forge-admin"], [True])
        client = self.mock.Mock()
        client.version.return_value = "17.0"
        client.identite.return_value = "forge-admin"
        with self.mock.patch.object(
            self.menu.forgejo_client, "ClientForgejo", return_value=client
        ) as classe, self.mock.patch.object(
            self.menu.click, "prompt"
        ) as prompt, self.mock.patch.object(
            self.menu.click, "confirm"
        ) as confirm, self.mock.patch(
            "builtins.print"
        ):
            self.assertIs(self.obj._git_forge_client(self.BASE), client)
        self.assertEqual(
            classe.call_args, self.mock.call(self.WEB, jeton_api="jeton-neuf")
        )
        prompt.assert_not_called()
        # Ni jeton à saisir ni HTTP en clair à confirmer : la forge vient
        # d'être créée par cette session.
        confirm.assert_not_called()


class TestGitRepoSurcouche(unittest.TestCase):
    """La surcouche privée de manifeste, depuis le menu : écrire, retirer,
    reconfigurer dans le mode du checkout. `forge_manifest` est remplacé."""

    BASE = "ssh://git@forge.example.invalid:2222"

    def setUp(self):
        from unittest import mock

        from script.todo import git_repo_menu

        self.mock = mock
        self.menu = git_repo_menu
        self.fm = git_repo_menu.forge_manifest
        self.addCleanup(mock.patch.stopall)

        class Menu(git_repo_menu.GitRepoMenuMixin):
            pass

        self.obj = Menu()
        self.reconf = mock.patch.object(Menu, "_git_repo_reconfigurer").start()
        mock.patch.object(
            git_repo_menu, "etat_manifeste_local", return_value=(5, 10)
        ).start()

    def lancer(self, prompts, confirms, methode="_git_repo_surcouche", *args):
        with self.mock.patch.object(
            self.menu.click, "prompt", side_effect=list(prompts)
        ), self.mock.patch.object(
            self.menu.click, "confirm", side_effect=list(confirms)
        ), self.mock.patch(
            "builtins.print"
        ):
            return getattr(self.obj, methode)(*args)

    def test_remove_then_reconfigure_in_the_frozen_mode(self):
        self.mock.patch.object(
            self.fm, "surcouches", return_value=["forge"]
        ).start()
        self.mock.patch.object(self.fm, "lire", return_value={}).start()
        retirer = self.mock.patch.object(self.fm, "retirer").start()
        self.assertTrue(self.lancer(["r"], [True, True]))
        retirer.assert_called_once_with(self.menu.RACINE, "forge")
        self.reconf.assert_called_once_with(freeze=True)

    def test_write_for_the_clones_on_the_forge(self):
        self.mock.patch.object(self.fm, "surcouches", return_value=[]).start()
        projets = [
            {"chemin": "/r/a", "cle": "a", "affiche": "a"},
            {"chemin": "/r/b", "cle": "b", "affiche": "b"},
        ]
        self.mock.patch.object(
            type(self.obj), "_git_repo_projets_absolus", return_value=projets
        ).start()
        self.mock.patch.object(
            type(self.obj),
            "_git_repo_choisir_remote_forge",
            return_value="forge",
        ).start()
        self.mock.patch.object(
            self.fm, "base_du_remote", return_value=self.BASE
        ).start()
        sur_la_forge = self.mock.patch.object(
            type(self.obj),
            "_git_repo_sur_la_forge",
            return_value=[projets[0]],
        ).start()
        ecrire = self.mock.patch.object(
            type(self.obj), "_git_repo_ecrire_surcouche", return_value=True
        ).start()
        self.assertTrue(self.lancer(["w"], [False]))
        sur_la_forge.assert_called_once_with(projets, "forge", self.BASE)
        self.assertEqual(
            ecrire.call_args[0], ("forge", self.BASE, [projets[0]])
        )
        self.reconf.assert_not_called()

    def ecrire_surcouche(self, choix, nom="forge"):
        projets = [
            {"cle": "a", "remote": "Amont", "proprietaire": "Amont"},
            {"cle": "c", "remote": "Commun", "proprietaire": "Commun"},
        ]
        return self.lancer(
            choix,
            [],
            "_git_repo_ecrire_surcouche",
            nom,
            self.BASE,
            projets,
        )

    def test_uncovered_projects_leave_their_remote_by_default(self):
        """Un remote qui sert aussi un projet absent de la forge (un
        fragment commun) reste sur son URL par « partial », le défaut."""
        self.mock.patch.object(
            self.fm,
            "projets_non_couverts",
            return_value={"x+commun/x": "Commun"},
        ).start()
        ecrire = self.mock.patch.object(self.fm, "ecrire").start()
        with self.mock.patch.object(
            self.menu.click, "prompt", return_value="partial"
        ) as prompt, self.mock.patch("builtins.print"):
            self.assertTrue(
                self.obj._git_repo_ecrire_surcouche(
                    "forge",
                    self.BASE,
                    [
                        {
                            "cle": "a",
                            "remote": "Amont",
                            "proprietaire": "Amont",
                        },
                        {
                            "cle": "c",
                            "remote": "Commun",
                            "proprietaire": "Commun",
                        },
                    ],
                )
            )
        self.assertEqual(prompt.call_args.kwargs["default"], "partial")
        self.assertEqual(
            ecrire.call_args[0],
            (self.menu.RACINE, "forge", {"Amont": f"{self.BASE}/Amont/"}),
        )
        ecrire.reset_mock()
        self.assertTrue(self.ecrire_surcouche(["all"]))
        self.assertEqual(set(ecrire.call_args[0][2]), {"Amont", "Commun"})
        ecrire.reset_mock()
        self.assertFalse(self.ecrire_surcouche(["cancel"]))
        ecrire.assert_not_called()

    def test_an_unsafe_remote_name_writes_nothing(self):
        ecrire = self.mock.patch.object(self.fm, "ecrire").start()
        self.assertFalse(self.ecrire_surcouche([], nom="equipe/forge"))
        ecrire.assert_not_called()

    def test_only_clones_whose_branch_is_on_the_forge_count(self):
        projets = [
            {
                "chemin": c,
                "nom": f"{c[-1]}.git",
                "proprietaire": "P",
                "branche": "X.0",
            }
            for c in ("/r/a", "/r/b", "/r/c")
        ]
        urls = {
            "/r/a": f"{self.BASE}/P/a.git",
            "/r/b": f"{self.BASE}/P/b.git",
            "/r/c": "ssh://ailleurs.example.invalid/P/c.git",
        }
        self.mock.patch.object(
            self.menu.repo_upgrade,
            "url_du_remote",
            side_effect=lambda chemin, nom: urls[chemin],
        ).start()
        self.mock.patch.object(
            self.menu.repo_upgrade,
            "git",
            side_effect=lambda args, cwd, delai=None: (
                ("abc\trefs/heads/X.0\n", "", 0)
                if cwd == "/r/a"
                else ("", "", 0)
            ),
        ).start()
        self.assertEqual(
            [
                p["chemin"]
                for p in self.obj._git_repo_sur_la_forge(
                    projets, "forge", self.BASE
                )
            ],
            ["/r/a"],
        )


class TestGitRepoPullRequests(unittest.TestCase):
    """Les pull requests sur la forge : une par clone dont la branche
    extraite n'est pas celle du manifeste. Git, le push et l'API sont
    remplacés."""

    BASE = "ssh://git@forge.example.invalid:2222"

    def setUp(self):
        from unittest import mock

        from script.todo import git_repo_menu

        self.mock = mock
        self.menu = git_repo_menu
        self.addCleanup(mock.patch.stopall)
        self.tetes = {"/r/a": "dev/a", "/r/b": "X.0", "/r/c": "HEAD"}
        projets = [
            {
                "chemin": c,
                "affiche": c,
                "branche": "X.0",
                "nom": c[-1] + ".git",
            }
            for c in sorted(self.tetes)
        ]

        def git(args, cwd, delai=None):
            if args[:2] == ["rev-parse", "--abbrev-ref"]:
                return self.tetes[cwd] + "\n", "", 0
            if args[0] == "log":
                return "Sujet du commit\n", "", 0
            return "", "", 1

        mock.patch.object(
            git_repo_menu.repo_upgrade, "git", side_effect=git
        ).start()
        mock.patch.object(
            git_repo_menu.repo_upgrade,
            "url_du_remote",
            side_effect=lambda c, n: f"{self.BASE}/Proprio/{c[-1]}.git",
        ).start()
        mock.patch.object(
            git_repo_menu.repo_upgrade, "commit_de", return_value="tete"
        ).start()
        mock.patch.object(
            git_repo_menu.forge_manifest,
            "base_du_remote",
            return_value=self.BASE,
        ).start()
        self.pousser = mock.patch.object(
            git_repo_menu.push_remote,
            "pousser_en_parallele",
            side_effect=lambda cibles: [
                dict(c, code=0, erreur="") for c in cibles
            ],
        ).start()

        class Menu(git_repo_menu.GitRepoMenuMixin):
            pass

        mock.patch.object(
            Menu, "_git_repo_projets_absolus", return_value=projets
        ).start()
        mock.patch.object(
            Menu, "_git_repo_choisir_remote_forge", return_value="forge"
        ).start()
        self.client = mock.Mock()
        self.client.commit_de_branche.return_value = "base"
        self.client.assurer_pull_request.return_value = (
            "creee",
            {"number": 3, "html_url": "u"},
        )
        mock.patch.object(
            Menu, "_git_forge_client", return_value=self.client
        ).start()
        self.obj = Menu()

    def lancer(self, confirms):
        with self.mock.patch.object(
            self.menu.click, "confirm", side_effect=list(confirms)
        ), self.mock.patch("builtins.print"):
            return self.obj._git_repo_pull_requests()

    def test_one_pull_request_per_clone_off_its_manifest_branch(self):
        self.assertEqual(self.lancer([True]), 0)
        (cibles,) = self.pousser.call_args[0]
        self.assertEqual(
            cibles,
            [
                {
                    "chemin": "/r/a",
                    "remote": "forge",
                    "specs": ["refs/heads/dev/a:refs/heads/dev/a"],
                }
            ],
        )
        self.client.assurer_pull_request.assert_called_once_with(
            "Proprio", "a", "dev/a", "X.0", "Sujet du commit"
        )

    def test_nothing_is_pushed_without_consent(self):
        self.lancer([False])
        self.pousser.assert_not_called()

    def test_a_remote_that_is_no_forge_stops_before_any_question(self):
        self.menu.forge_manifest.base_du_remote.return_value = None
        self.assertEqual(self.lancer([]), 0)
        self.pousser.assert_not_called()

    def test_a_base_branch_absent_from_the_forge_skips(self):
        self.client.commit_de_branche.return_value = None
        self.lancer([True])
        self.client.assurer_pull_request.assert_not_called()

    def test_a_branch_already_on_the_base_has_nothing_to_merge(self):
        self.client.commit_de_branche.return_value = "tete"
        self.lancer([True])
        self.client.assurer_pull_request.assert_not_called()


class TestGitRepoPrepareForge(unittest.TestCase):
    """La préparation d'une forge Forgejo avant le push : organisations
    absentes créées privées après confirmation, dépôts créés par l'API
    seulement sur demande. Le client est remplacé par un faux."""

    class FauxClient:
        def __init__(self, existantes, refus=()):
            self.existantes = set(existantes)
            self.refus = set(refus)
            self.creees = []
            self.depots = []

        def organisation(self, nom):
            return {"username": nom} if nom in self.existantes else None

        def nature_proprietaire(self, nom):
            if nom == "moi":
                return "compte"
            if nom == "lui":
                return "utilisateur"
            return "organisation" if nom in self.existantes else "absent"

        def assurer_organisation(self, nom, visibilite="private"):
            from script.git import forgejo_client

            if nom in self.refus:
                raise forgejo_client.ErreurForgejo("403 forbidden", 403)
            self.creees.append((nom, visibilite))
            return "creee", {}

        def assurer_depot(self, proprietaire, nom, prive=True):
            self.depots.append((proprietaire, nom, prive))
            return "cree", {}

    POSES = [
        ({"proprietaire": "OCA", "nom": "a.git", "affiche": "a"}, "u1"),
        (
            {"proprietaire": "TechnoLibre", "nom": "b.git", "affiche": "b"},
            "u2",
        ),
        (
            {"proprietaire": "technolibre", "nom": "c.git", "affiche": "c"},
            "u3",
        ),
    ]

    def setUp(self):
        from unittest import mock

        from script.todo import git_repo_menu

        self.mock = mock
        self.menu = git_repo_menu

        class Menu(git_repo_menu.GitRepoMenuMixin):
            pass

        self.obj = Menu()

    def preparer(self, client, confirms):
        with self.mock.patch.object(
            type(self.obj), "_git_forge_client", return_value=client
        ), self.mock.patch.object(
            self.menu.click, "confirm", side_effect=list(confirms)
        ), self.mock.patch(
            "builtins.print"
        ):
            return self.obj._git_repo_preparer_forge(
                "https://f.invalid", self.POSES
            )

    def test_missing_organisations_are_created_private_once_per_name(self):
        client = self.FauxClient({"OCA"})
        self.assertTrue(self.preparer(client, [True, True, False]))
        self.assertEqual(client.creees, [("TechnoLibre", "private")])
        self.assertEqual(client.depots, [])

    def test_repositories_only_on_request(self):
        client = self.FauxClient({"OCA", "TechnoLibre"})
        self.assertTrue(self.preparer(client, [True, True]))
        # Les dépôts se créent en parallèle : l'ordre d'arrivée varie.
        self.assertEqual(
            sorted(d[:2] for d in client.depots),
            [
                ("OCA", "a.git"),
                ("TechnoLibre", "b.git"),
                ("technolibre", "c.git"),
            ],
        )
        self.assertTrue(all(d[2] for d in client.depots))

    def test_declining_the_organisations_creates_none(self):
        client = self.FauxClient(set())
        self.preparer(client, [True, False, False])
        self.assertEqual(client.creees, [])

    def test_a_refused_creation_does_not_stop_the_push(self):
        client = self.FauxClient(set(), refus={"OCA"})
        self.assertTrue(self.preparer(client, [True, True, False]))
        self.assertEqual(client.creees, [("TechnoLibre", "private")])

    def test_the_token_account_and_other_users(self):
        """Le compte du jeton n'est pas une organisation à créer ; un autre
        compte est laissé hors des créations de dépôts."""
        poses = self.POSES + [
            ({"proprietaire": "moi", "nom": "m.git", "affiche": "m"}, "u4"),
            ({"proprietaire": "lui", "nom": "l.git", "affiche": "l"}, "u5"),
        ]
        client = self.FauxClient({"OCA", "TechnoLibre"})
        with self.mock.patch.object(
            type(self.obj), "_git_forge_client", return_value=client
        ), self.mock.patch.object(
            self.menu.click, "confirm", side_effect=[True, True]
        ), self.mock.patch(
            "builtins.print"
        ):
            self.assertTrue(
                self.obj._git_repo_preparer_forge("https://f.invalid", poses)
            )
        self.assertEqual(client.creees, [])
        self.assertIn(("moi", "m.git", True), client.depots)
        self.assertNotIn("lui", [d[0] for d in client.depots])

    def test_a_failed_owner_lookup_offers_to_push_anyway(self):
        fc = self.menu.forgejo_client
        client = self.FauxClient(set())

        def refuse(nom):
            raise fc.ErreurForgejo(f"GET /orgs/{nom} : 403", 403)

        client.nature_proprietaire = refuse
        self.assertFalse(self.preparer(client, [True, False]))
        self.assertTrue(self.preparer(client, [True, True]))
        self.assertEqual(client.creees, [])

    def test_skipping_the_check_touches_nothing(self):
        with self.mock.patch.object(
            type(self.obj), "_git_forge_client"
        ) as fabrique, self.mock.patch.object(
            self.menu.click, "confirm", return_value=False
        ):
            self.assertTrue(
                self.obj._git_repo_preparer_forge(
                    "https://f.invalid", self.POSES
                )
            )
        fabrique.assert_not_called()


class TestGitForgeToken(unittest.TestCase):
    """Le jeton d'une forge : une entrée du coffre par hôte, jamais
    affiché ; un jeton refusé ne donne pas de client."""

    def setUp(self):
        from unittest import mock

        from script.todo import git_repo_menu

        self.mock = mock
        self.menu = git_repo_menu

        class Menu(git_repo_menu.GitRepoMenuMixin):
            pass

        self.obj = Menu()

    def test_the_vault_entry_is_per_host(self):
        class Entree:
            password = "jeton-h1"

        class Coffre:
            def __init__(self):
                self.titres = []

            def find_entries_by_title(self, titre, first=True):
                self.titres.append(titre)
                return Entree() if titre.endswith("h1.invalid") else None

        coffre = Coffre()
        self.obj._git_coffre = lambda: coffre
        self.assertEqual(
            self.obj._git_forge_jeton_du_coffre("h1.invalid"), "jeton-h1"
        )
        self.assertEqual(self.obj._git_forge_jeton_du_coffre("h2.invalid"), "")
        self.assertNotEqual(coffre.titres[0], coffre.titres[1])

    def test_without_vault(self):
        self.assertEqual(self.obj._git_forge_jeton_du_coffre("h.invalid"), "")
        self.assertFalse(self.obj._git_forge_ranger_jeton("h.invalid", "x"))

    def test_a_refused_token_gives_no_client(self):
        fc = self.menu.forgejo_client

        class Refuse:
            def __init__(self, *a, **kw):
                pass

            def version(self):
                return "1.0"

            def identite(self):
                raise fc.ErreurForgejo("GET /user : 401", 401)

        with self.mock.patch.dict(
            "os.environ", {"EL_FORGEJO_TOKEN": "faux"}
        ), self.mock.patch.object(
            fc, "ClientForgejo", Refuse
        ), self.mock.patch.object(
            self.menu.click, "confirm", return_value=False
        ) as confirm, self.mock.patch(
            "builtins.print"
        ) as imprime:
            self.assertIsNone(self.obj._git_forge_client("https://f.invalid"))
        sortie = " ".join(str(a) for c in imprime.mock_calls for a in c.args)
        self.assertNotIn("faux", sortie)
        # Un jeton refusé propose d'en saisir un autre ; non : pas de client.
        confirm.assert_called_once()

    def test_a_refused_token_can_be_typed_again_and_stored(self):
        fc = self.menu.forgejo_client
        tentatives = []

        class Client:
            def __init__(self, web, jeton_api=None):
                tentatives.append(jeton_api)
                self.jeton = jeton_api

            def version(self):
                return "1.0"

            def identite(self):
                if self.jeton != "bon":
                    raise fc.ErreurForgejo("GET /user : 401", 401)
                return "moi"

        ranges = []
        self.obj._git_forge_ranger_jeton = (
            lambda forge, j: ranges.append((forge, j)) or True
        )
        with self.mock.patch.dict(
            "os.environ", {"EL_FORGEJO_TOKEN": "perime"}
        ), self.mock.patch.object(
            fc, "ClientForgejo", Client
        ), self.mock.patch.object(
            self.menu.click, "confirm", side_effect=[True, True]
        ), self.mock.patch.object(
            self.menu.click, "prompt", return_value="paste"
        ), self.mock.patch(
            "getpass.getpass", return_value="bon"
        ), self.mock.patch(
            "builtins.print"
        ):
            client = self.obj._git_forge_client("https://f.invalid:3000")
        self.assertIsNotNone(client)
        self.assertEqual(tentatives, ["perime", "bon"])
        self.assertEqual(ranges, [("f.invalid:3000", "bon")])

    def _obtenir(
        self,
        prompts,
        getpass_valeurs=(),
        confirms=(),
        web="http://forge.invalid:3000",
    ):
        with self.mock.patch.object(
            self.menu.click, "prompt", side_effect=list(prompts)
        ), self.mock.patch.object(
            self.menu.click, "confirm", side_effect=list(confirms)
        ), self.mock.patch(
            "getpass.getpass", side_effect=list(getpass_valeurs)
        ), self.mock.patch(
            "builtins.print"
        ):
            return self.obj._git_forge_obtenir_jeton(web)

    def test_pasting_is_the_default(self):
        with self.mock.patch.object(
            self.menu.click, "prompt", return_value="paste"
        ) as prompt, self.mock.patch(
            "getpass.getpass", return_value=" colle "
        ), self.mock.patch(
            "builtins.print"
        ):
            jeton = self.obj._git_forge_obtenir_jeton(
                "http://forge.invalid:3000"
            )
        self.assertEqual(jeton, "colle")
        self.assertEqual(prompt.call_args.kwargs["default"], "paste")

    def test_a_token_created_on_the_host_by_ssh(self):
        fc = self.menu.forgejo_client
        with self.mock.patch.object(
            fc, "creer_jeton_par_ssh", return_value=("neuf", "")
        ) as creer:
            jeton = self._obtenir(
                ["ssh", "erplibre@forge.invalid", "erplibre"]
            )
        self.assertEqual(jeton, "neuf")
        cible, compte, nom = creer.call_args.args
        self.assertEqual(
            (cible, compte), ("erplibre@forge.invalid", "erplibre")
        )
        self.assertTrue(nom.startswith("erplibre-todo-"))

    def test_the_ssh_target_defaults_to_the_forge_host(self):
        fc = self.menu.forgejo_client
        with self.mock.patch.object(
            fc,
            "creer_jeton_par_ssh",
            return_value=("", "sudo: a password is required"),
        ), self.mock.patch.object(
            self.menu.click, "prompt", side_effect=["ssh", "x", "y"]
        ) as prompt, self.mock.patch(
            "builtins.print"
        ):
            self.assertEqual(
                self.obj._git_forge_obtenir_jeton("http://forge.invalid:3000"),
                "",
            )
        self.assertEqual(
            prompt.call_args_list[1].kwargs["default"],
            "erplibre@forge.invalid",
        )

    def test_a_token_created_with_the_account_password(self):
        fc = self.menu.forgejo_client
        crees = []

        class Client:
            def __init__(self, web, identifiants=None, jeton_api=None):
                self.identifiants = identifiants

            def creer_jeton(self, nom, portees):
                crees.append((self.identifiants, tuple(portees)))
                return "par-api"

        with self.mock.patch.object(fc, "ClientForgejo", Client):
            jeton = self._obtenir(
                ["password", "moi"], ["secret"], web="https://forge.invalid"
            )
        self.assertEqual(jeton, "par-api")
        self.assertEqual(crees, [(("moi", "secret"), fc.PORTEES)])

    def test_the_password_over_plain_http_needs_its_own_consent(self):
        """Consentir à envoyer le jeton en clair ne couvre pas le mot de
        passe du compte : une seconde question, non par défaut."""
        fc = self.menu.forgejo_client
        with self.mock.patch.object(fc, "ClientForgejo") as fabrique:
            self.assertEqual(self._obtenir(["password"], confirms=[False]), "")
        fabrique.assert_not_called()

    def test_an_empty_account_cancels(self):
        fc = self.menu.forgejo_client
        with self.mock.patch.object(fc, "ClientForgejo") as fabrique:
            self.assertEqual(
                self._obtenir(
                    ["password", ""], ["x"], web="https://forge.invalid"
                ),
                "",
            )
        fabrique.assert_not_called()

    def test_a_missing_vault_can_be_created_then_holds_the_token(self):
        essais = []

        def ranger(forge, jeton):
            essais.append(forge)
            return len(essais) > 1

        self.obj._git_forge_ranger_jeton = ranger
        self.obj._git_forge_creer_coffre = lambda: True
        fc = self.menu.forgejo_client

        class Client:
            def __init__(self, web, jeton_api=None):
                pass

            def version(self):
                return "1"

            def identite(self):
                return "moi"

        with self.mock.patch.dict(
            "os.environ", {}, clear=False
        ), self.mock.patch.object(
            fc, "jeton", return_value=("", "")
        ), self.mock.patch.object(
            fc, "ClientForgejo", Client
        ), self.mock.patch.object(
            type(self.obj), "_git_forge_obtenir_jeton", return_value="neuf"
        ), self.mock.patch.object(
            self.menu.click, "confirm", return_value=True
        ), self.mock.patch(
            "builtins.print"
        ) as imprime:
            self.assertIsNotNone(
                self.obj._git_forge_client("https://f.invalid")
            )
        self.assertEqual(len(essais), 2)
        sortie = " ".join(str(a) for c in imprime.mock_calls for a in c.args)
        self.assertIn(self.menu.GROUPE_FORGE, sortie)

    def _avec_coffre(self, chemin):
        """Une session TODO factice dont « kdbx.path » vaut `chemin`."""
        vault = self.mock.Mock()
        vault.vault_path.return_value = chemin
        self.obj._git_forge_vault = lambda: vault
        return vault

    def test_a_configured_vault_that_did_not_open_is_not_recreated(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".kdbx") as fichier:
            vault = self._avec_coffre(fichier.name)
            with self.mock.patch.object(
                self.menu.click, "confirm"
            ) as confirm, self.mock.patch("builtins.print") as imprime:
                self.assertFalse(self.obj._git_forge_creer_coffre())
        confirm.assert_not_called()
        vault.ensure_vault.assert_not_called()
        sortie = " ".join(str(a) for c in imprime.mock_calls for a in c.args)
        self.assertIn(
            self.menu.t(
                "The KeePass vault could not be opened: the token stays for"
                " this session only."
            ),
            sortie,
        )

    def test_a_missing_vault_is_created_without_a_second_question(self):
        vault = self._avec_coffre("")
        vault.ensure_vault.return_value = "/x/secrets.kdbx"
        with self.mock.patch.object(
            self.menu.click, "confirm", return_value=True
        ):
            self.assertTrue(self.obj._git_forge_creer_coffre())
        self.assertIs(
            vault.ensure_vault.call_args.kwargs["confirm_create"], False
        )

    def test_a_vault_that_cannot_be_written_does_not_crash_the_menu(self):
        for erreur in (PermissionError("refusé"), EOFError()):
            with self.subTest(erreur=type(erreur).__name__):
                vault = self._avec_coffre("")
                vault.ensure_vault.side_effect = erreur
                with self.mock.patch.object(
                    self.menu.click, "confirm", return_value=True
                ), self.mock.patch("builtins.print"):
                    self.assertFalse(self.obj._git_forge_creer_coffre())

    def test_a_configured_path_whose_file_is_gone_is_not_opened(self):
        """PyKeePass lèverait FileNotFoundError après avoir demandé le mot
        de passe maître : le coffre est traité comme absent."""
        self._avec_coffre("/chemin/qui/n-existe/pas.kdbx")
        ouvertures = []
        self.obj._git_coffre = lambda: ouvertures.append(1)
        self.assertEqual(self.obj._git_forge_jeton_du_coffre("h"), "")
        self.assertFalse(self.obj._git_forge_ranger_jeton("h", "j"))
        self.assertEqual(ouvertures, [])

    def test_vault_creation_needs_the_todo_session(self):
        """Hors du CLI TODO (ni config ni gestionnaire), rien n'est proposé."""
        with self.mock.patch.object(self.menu.click, "confirm") as confirm:
            self.assertFalse(self.obj._git_forge_creer_coffre())
        confirm.assert_not_called()

    def test_plain_http_to_another_host_needs_consent(self):
        with self.mock.patch.object(
            self.menu.click, "confirm", return_value=False
        ) as confirm, self.mock.patch.object(
            self.menu.forgejo_client, "ClientForgejo"
        ) as fabrique, self.mock.patch(
            "builtins.print"
        ):
            self.assertIsNone(self.obj._git_forge_client("http://f.invalid"))
        self.assertIs(confirm.call_args.kwargs["default"], False)
        fabrique.assert_not_called()

    def test_an_ssh_base_asks_for_the_web_url(self):
        with self.mock.patch.object(
            self.menu.click, "prompt", return_value="pas une url"
        ), self.mock.patch("builtins.print"):
            self.assertIsNone(
                self.obj._git_forge_client("ssh://git@f.invalid:2222")
            )


class TestGitRepoFreezeEntries(unittest.TestCase):
    """Les entrées du gel : ce qu'elles lancent, et dans quel ordre.

    Le gel et le dégel écrivent des fichiers suivis par git ; la passe à sec
    tourne donc toujours avant, et rien ne s'écrit sans confirmation. Le
    mode affiché se lit dans le manifeste local, jamais dans un état
    enregistré.
    """

    SHA = "0123456789abcdef0123456789abcdef01234567"

    def setUp(self):
        from unittest import mock

        from script.todo import git_repo_menu

        self.mock = mock
        self.menu = git_repo_menu
        self.cmds = []
        self.status = []

        class Execute:
            def exec_command_live(inner, cmd, source_erplibre=True):
                self.cmds.append(cmd)
                return self.status.pop(0) if self.status else 0

        class Menu(git_repo_menu.GitRepoMenuMixin):
            execute = Execute()

        self.obj = Menu()

    def _manifeste(self, dossier, texte):
        import os

        chemin = os.path.join(dossier, self.menu.MANIFESTE_LOCAL)
        os.makedirs(os.path.dirname(chemin))
        with open(chemin, "w") as fh:
            fh.write(texte)

    def test_mode_is_read_from_the_local_manifest(self):
        import tempfile

        with tempfile.TemporaryDirectory() as dossier:
            self.assertIsNone(self.menu.etat_manifeste_local(dossier))
            self._manifeste(
                dossier,
                "<manifest>\n"
                f'  <project name="a" path="x/a" revision="{self.SHA}"/>\n'
                '  <project name="b" path="x/b" revision="18.0"/>\n'
                f'  <!-- <project name="c" path="x/c"'
                f' revision="{self.SHA}"/> -->\n'
                "</manifest>\n",
            )
            etat = self.menu.etat_manifeste_local(dossier)
        self.assertEqual(etat, (1, 2))
        self.assertTrue(self.menu.libelle_mode(etat).startswith("1/2 "))
        self.assertEqual(
            self.menu.libelle_mode((0, 2)),
            self.menu.t("follows the branches"),
        )

    def test_header_counts_the_active_version_files_only(self):
        import os
        import tempfile

        gel = 'freeze-revision="' + self.SHA + '"'
        with tempfile.TemporaryDirectory() as dossier:
            os.mkdir(os.path.join(dossier, "manifest"))
            with open(os.path.join(dossier, ".odoo-version"), "w") as fh:
                fh.write("X.0\n")
            for fichier, projets in (
                (
                    "git_manifest_odooX.0.xml",
                    f'<project name="a" path="x/a"'
                    f' revision="X.0" {gel}/><project name="b" path="x/b"'
                    ' revision="X.0"/>',
                ),
                (
                    "git_manifest_erplibre_odoo.xml",
                    f'<project name="c"' f' path="x/c" revision="X.0" {gel}/>',
                ),
            ):
                with open(
                    os.path.join(dossier, "manifest", fichier), "w"
                ) as fh:
                    fh.write(f"<manifest>{projets}</manifest>\n")
            self.assertEqual(self.menu.gel_des_sources(dossier), (1, 2))
            self.assertEqual(
                self.menu.gel_des_sources(dossier, odoo_version="X.0"), (1, 2)
            )
            self.assertEqual(
                self.menu.gel_des_sources(dossier, odoo_version="Y.0"), (0, 0)
            )

    def _geler(self, confirme, amont=False, branches=False, **kw):
        """Lance le gel. `amont` et `branches` répondent aux questions de la
        base amont et des branches, posées avant la passe à sec ;
        `confirme`, à celle de l'écriture. La publication des branches est
        remplacée : ses tests sont à part."""
        reponses = (
            [confirme] if kw.get("unfreeze") else [amont, branches, confirme]
        )
        with self.mock.patch.object(
            self.menu.click, "confirm", side_effect=reponses
        ) as confirm, self.mock.patch.object(
            type(self.obj), "_git_repo_publier_branches", return_value=0
        ) as publier:
            code = self.obj._git_repo_geler(**kw)
        self.publier_branches = publier
        return code, confirm

    def test_freeze_runs_the_dry_run_and_stops_without_consent(self):
        code, confirm = self._geler(False)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.cmds), 1)
        self.assertIn("git_freeze_manifest.py --dry-run", self.cmds[0])
        self.assertEqual(confirm.call_count, 3)

    def test_freeze_writes_after_consent(self):
        code, _ = self._geler(True)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.cmds), 2)
        self.assertTrue(self.cmds[1].endswith("git_freeze_manifest.py"))

    def test_upstream_base_is_off_by_default(self):
        _code, confirm = self._geler(True)
        self.assertIs(confirm.call_args_list[0].kwargs["default"], False)
        self.assertNotIn("--upstream", " ".join(self.cmds))

    def test_upstream_base_passes_its_flag_to_both_runs(self):
        self._geler(True, amont=True)
        self.assertIn("--upstream --dry-run", self.cmds[0])
        self.assertTrue(self.cmds[1].endswith("--upstream"))

    def test_branches_are_off_by_default(self):
        _code, confirm = self._geler(True)
        self.assertIs(confirm.call_args_list[1].kwargs["default"], False)
        self.assertNotIn("--branches", " ".join(self.cmds))
        self.publier_branches.assert_not_called()

    def test_branches_pass_their_flag_to_both_runs_after_publishing(self):
        self._geler(True, branches=True)
        self.assertIn("--branches --dry-run", self.cmds[0])
        self.assertTrue(self.cmds[1].endswith("--branches"))
        self.publier_branches.assert_called_once()

    def test_unfreeze_asks_nothing_about_the_branches(self):
        self._geler(True, unfreeze=True)
        self.assertNotIn("--branches", " ".join(self.cmds))
        self.publier_branches.assert_not_called()

    def _publier_branches(
        self, choix, confirms=(), codes=None, remotes=None, remote_choisi=None
    ):
        """Lance la publication des branches sur deux branches factices.

        `choix` répond à « toutes, une à une, aucune » ; `remotes` est ce que
        portent les clones (par défaut, le seul remote du manifeste, et la
        question du remote n'est pas posée) ; `remote_choisi` y répond.
        Rend (nombre poussé, cibles passées au push parallèle)."""
        gfm = self.menu.git_freeze_manifest
        prm = self.menu.push_remote
        lst = [
            {
                "chemin": "odooX.0/a",
                "remote": "R",
                "branche": "X_maj_1",
                "motif": gfm.BRANCHE_ABSENTE,
            },
            {
                "chemin": "odooX.0/b",
                "remote": "R",
                "branche": "X_maj_1",
                "motif": gfm.BRANCHE_EN_AVANCE,
            },
        ]
        codes = list(codes or [(0, ""), (0, "")])
        poussees = []

        def pousser(cibles, jobs=prm.PARALLELE, suivi=None):
            resultats = []
            for c in cibles:
                code, erreur = codes.pop(0)
                r = dict(c, code=code, erreur=erreur)
                poussees.append(c)
                if suivi:
                    suivi(r)
                resultats.append(r)
            return resultats

        reponses = [choix] + ([remote_choisi] if remote_choisi else [])
        with self.mock.patch.object(
            gfm, "branches_a_publier", return_value=lst
        ), self.mock.patch.object(
            prm, "remotes_des_clones", return_value=remotes or {"R": 2}
        ), self.mock.patch.object(
            prm, "pousser_en_parallele", side_effect=pousser
        ), self.mock.patch.object(
            self.menu.click, "prompt", side_effect=reponses
        ), self.mock.patch.object(
            self.menu.click, "confirm", side_effect=list(confirms)
        ):
            n = self.obj._git_repo_publier_branches()
        return n, poussees

    def test_publishing_branches_defaults_to_none(self):
        n, poussees = self._publier_branches("none")
        self.assertEqual((n, poussees), (0, []))

    def test_publishing_all_branches_pushes_each_once(self):
        n, poussees = self._publier_branches("all")
        self.assertEqual(n, 2)
        self.assertEqual(len(poussees), 2)
        self.assertTrue(poussees[0]["chemin"].endswith("odooX.0/a"))
        self.assertEqual(poussees[0]["remote"], "R")
        self.assertEqual(
            poussees[0]["specs"], ["refs/heads/X_maj_1:refs/heads/X_maj_1"]
        )

    def test_publishing_each_branch_asks_one_by_one(self):
        n, poussees = self._publier_branches("each", confirms=[False, True])
        self.assertEqual(n, 1)
        self.assertEqual(len(poussees), 1)
        self.assertTrue(poussees[0]["chemin"].endswith("odooX.0/b"))

    def test_a_refused_push_is_not_counted(self):
        with self.mock.patch("builtins.print") as imprime:
            n, _ = self._publier_branches(
                "all", codes=[(1, "rejected"), (0, "")]
            )
        self.assertEqual(n, 1)
        sortie = " ".join(str(a) for c in imprime.mock_calls for a in c.args)
        self.assertIn(
            self.menu.t(
                "If the remote already has this branch, fetch it,"
                " then freeze again."
            ),
            sortie,
        )

    def test_another_remote_of_the_clones_can_be_chosen(self):
        with self.mock.patch("builtins.print") as imprime:
            n, poussees = self._publier_branches(
                "all", remotes={"R": 2, "forge": 2}, remote_choisi="forge"
            )
        self.assertEqual(n, 2)
        self.assertEqual({c["remote"] for c in poussees}, {"forge"})
        sortie = " ".join(str(a) for c in imprime.mock_calls for a in c.args)
        self.assertIn(
            self.menu.t(
                "The freeze writes a branch only when the manifest remote"
                " carries it."
            ),
            sortie,
        )

    def test_the_manifest_remote_stays_the_default(self):
        _n, poussees = self._publier_branches(
            "all", remotes={"R": 2, "forge": 1}, remote_choisi="manifest"
        )
        self.assertEqual({c["remote"] for c in poussees}, {"R"})

    def test_nothing_to_publish_asks_nothing(self):
        gfm = self.menu.git_freeze_manifest
        with self.mock.patch.object(
            gfm, "branches_a_publier", return_value=[]
        ), self.mock.patch.object(self.menu.click, "prompt") as prompt:
            self.assertEqual(self.obj._git_repo_publier_branches(), 0)
        prompt.assert_not_called()

    def test_unfreeze_asks_nothing_about_the_upstream_base(self):
        _code, confirm = self._geler(True, unfreeze=True)
        confirm.assert_called_once()
        self.assertNotIn("--upstream", " ".join(self.cmds))

    def test_header_counts_the_forks_with_an_upstream_base(self):
        forks = [{"base_gelee": "1" * 40}, {"base_gelee": None}, {}]
        ligne = self.menu.ligne_du_gel((4, 9), forks)
        self.assertIn("4/9", ligne)
        self.assertIn(f"1/3 {self.menu.t('forks with upstream base')}", ligne)
        self.assertNotIn(
            self.menu.t("forks with upstream base"),
            self.menu.ligne_du_gel((4, 9), []),
        )
        self.assertIsNone(self.menu.ligne_du_gel(None, forks))

    def test_unfreeze_passes_its_flag_to_both_runs(self):
        self._geler(True, unfreeze=True)
        self.assertIn("--unfreeze --dry-run", self.cmds[0])
        self.assertTrue(self.cmds[1].endswith("--unfreeze"))

    def test_a_failed_dry_run_asks_nothing(self):
        """Seules les questions de la base amont et des branches, qui
        précèdent la passe à sec, ont été posées : l'écriture n'est pas
        proposée."""
        self.status = [1]
        code, confirm = self._geler(True)
        self.assertEqual(code, 1)
        self.assertEqual(len(self.cmds), 1)
        self.assertEqual(confirm.call_count, 2)
        self.status = [1]
        code, confirm = self._geler(True, unfreeze=True)
        self.assertEqual(code, 1)
        confirm.assert_not_called()

    def test_reconfigure_follows_branches_without_the_argument(self):
        self.obj._git_repo_reconfigurer()
        self.assertTrue(self.cmds[0].endswith("make repo_configure_all"))

    def test_reconfigure_on_frozen_commits_passes_freeze(self):
        with self.mock.patch.object(
            self.menu, "gel_des_sources", return_value=(3, 5)
        ):
            self.obj._git_repo_reconfigurer(freeze=True)
        self.assertTrue(
            self.cmds[0].endswith("make repo_configure_all FREEZE=1")
        )

    def test_reconfigure_on_frozen_commits_refuses_an_empty_freeze(self):
        with self.mock.patch.object(
            self.menu, "gel_des_sources", return_value=(0, 5)
        ):
            code = self.obj._git_repo_reconfigurer(freeze=True)
        self.assertEqual(code, 1)
        self.assertEqual(self.cmds, [])


class TestGitRepoPublish(unittest.TestCase):
    """La publication des forks et la file des conflits, côté menu.

    `repo_apply` est remplacé : ces tests vérifient qu'aucun push ne part
    sans confirmation, et que la passe enregistre l'issue de chaque geste.
    """

    SHA_A = "a" * 40
    SHA_B = "b" * 40

    def setUp(self):
        from unittest import mock

        from script.todo import git_repo_menu

        self.mock = mock
        self.menu = git_repo_menu
        self.ra = git_repo_menu.repo_apply

        class Menu(git_repo_menu.GitRepoMenuMixin):
            execute = None

        self.obj = Menu()
        self.res = {
            "chemin": "x/a",
            "etat": "rebase",
            "branche": "X.0_maj_20990101",
            "remote": "fork_origin_amont",
            "revision": "X.0",
        }
        self.passe = {
            "horodatage": "20990101T0800",
            "version": "X.0",
            "resultats": [self.res],
        }

    def _plan(self, force=False, a_retenir=()):
        return {
            "remote": "fork_origin_amont",
            "revision": "X.0",
            "branche": "X.0_maj_20990101",
            "ancien": self.SHA_A,
            "nouveau": self.SHA_B,
            "gel": None,
            "force": force,
            "a_retenir": list(a_retenir),
        }

    def _publier(self, plan, confirms, prompts=(), saisie="1", **remplaces):
        """Lance la publication, `repo_apply` et les questions remplacés.

        `saisie` répond au choix des numéros ; `remplaces` remplace d'autres
        fonctions de `repo_apply` (nom=mock). Rend (code, publier, retenir,
        mettre_a_jour_passe, geler)."""
        from contextlib import ExitStack

        mock = self.mock
        with ExitStack() as pile:

            def remplacer(nom, **kw):
                return pile.enter_context(
                    mock.patch.object(self.ra, nom, **kw)
                )

            remplacer("lire_passe", return_value=self.passe)
            remplacer("plan_publication", return_value=plan)
            publier = remplacer("publier", return_value=("", "", 0))
            retenir = remplacer("retenir", return_value=("", "", 0))
            remplacer("a_retenir", return_value=[])
            maj = remplacer("mettre_a_jour_passe")
            remplacer("version_erplibre", return_value="9.9.9")
            remplacer("tags", return_value=set())
            for nom, faux in remplaces.items():
                pile.enter_context(mock.patch.object(self.ra, nom, faux))
            pile.enter_context(
                mock.patch("builtins.input", return_value=saisie)
            )
            pile.enter_context(
                mock.patch.object(
                    self.menu.click, "confirm", side_effect=list(confirms)
                )
            )
            pile.enter_context(
                mock.patch.object(
                    self.menu.click, "prompt", side_effect=list(prompts)
                )
            )
            geler = pile.enter_context(
                mock.patch.object(type(self.obj), "_git_repo_geler")
            )
            code = self.obj._git_repo_publier()
        return code, publier, retenir, maj, geler

    def test_no_push_without_confirmation(self):
        code, publier, _r, maj, _g = self._publier(self._plan(), [False])
        self.assertEqual(code, 0)
        publier.assert_not_called()
        maj.assert_not_called()

    def test_confirmed_push_is_recorded_then_refreeze_offered(self):
        code, publier, _r, maj, geler = self._publier(
            self._plan(), [True, True]
        )
        self.assertEqual(code, 1)
        publier.assert_called_once()
        champs = maj.call_args[0][2]
        self.assertEqual(champs, {"etat": "publie", "publie": self.SHA_B})
        geler.assert_called_once_with()

    def test_retention_ref_needs_its_own_confirmation(self):
        plan = self._plan(force=True, a_retenir=[self.SHA_A])
        code, publier, retenir, _m, _g = self._publier(
            plan, [False], prompts=["tag", "ERPLibre/v9.9.9_odooX.0"]
        )
        self.assertEqual(code, 0)
        retenir.assert_not_called()
        publier.assert_not_called()

    def test_retention_ref_pushed_before_the_forced_push(self):
        plan = self._plan(force=True, a_retenir=[self.SHA_A])
        _c, publier, retenir, _m, _g = self._publier(
            plan, [True, True, False], prompts=["branch", "X.0_avant"]
        )
        retenir.assert_called_once_with(
            self.mock.ANY,
            self.SHA_A,
            "fork_origin_amont",
            "branche",
            "X.0_avant",
        )
        publier.assert_called_once()

    def test_selection_out_of_range_is_refused(self):
        """« 0 » et les négatifs indexeraient la liste par la fin."""
        for saisie in ("0", "-1", "2", "1,0", "x"):
            with self.subTest(saisie=saisie), self.mock.patch(
                "builtins.print"
            ) as affiche:
                code, publier, _r, _m, _g = self._publier(
                    self._plan(), [], saisie=saisie
                )
                self.assertEqual(code, 0)
                publier.assert_not_called()
                affiche.assert_any_call(self.menu.t("Command not found !"))

    def test_numbers_pick_their_repositories(self):
        lst = [{"n": 1}, {"n": 2}, {"n": 3}]
        self.assertEqual(
            self.menu.choix_numeros("3,1", lst), [{"n": 3}, {"n": 1}]
        )
        self.assertEqual(self.menu.choix_numeros("all", lst), lst)
        self.assertIsNone(self.menu.choix_numeros("4", lst))

    def test_a_refused_plan_pushes_nothing_and_asks_nothing(self):
        plan = dict(self._plan(), refus="remote moved")
        code, publier, retenir, maj, _g = self._publier(plan, [])
        self.assertEqual(code, 0)
        publier.assert_not_called()
        retenir.assert_not_called()
        maj.assert_not_called()

    def test_a_rebase_finished_outside_the_menu_becomes_publishable(self):
        self.res["etat"] = "conflit"

        def reconcilier(passe, racine=None):
            self.res["etat"] = "rebase"
            return [(self.res, "conflit", "rebase")]

        faux = self.mock.Mock(side_effect=reconcilier)
        code, publier, _r, _m, _g = self._publier(
            self._plan(), [True, False], reconcilier_passe=faux
        )
        faux.assert_called_once()
        self.assertEqual(code, 1)
        publier.assert_called_once()

    def test_a_single_repository_reads_in_the_singular(self):
        from script.todo import todo_i18n

        for etat, cle in (
            ("publie", "published (one)"),
            ("avance", "fast-forwarded (one)"),
            ("rebase", "rebased (one)"),
        ):
            self.assertEqual(self.menu.ETATS[etat], cle)
            self.assertIn(cle, todo_i18n.TRANSLATIONS)
        self.assertEqual(
            todo_i18n.TRANSLATIONS["published (one)"]["fr"], "publié"
        )
        with self.mock.patch.object(self.menu, "t", side_effect=lambda c: c):
            self.assertEqual(
                self.menu.decompte(1, "publie"), "1 published (one)"
            )
            self.assertEqual(self.menu.decompte(2, "publie"), "2 published")

    def test_the_report_and_the_queue_reconcile_first(self):
        passe = dict(self.passe, resultats=[])
        for methode in ("_git_repo_rapport", "_git_repo_file_conflits"):
            with self.subTest(methode=methode), self.mock.patch.object(
                self.ra, "lire_passe", return_value=passe
            ), self.mock.patch.object(
                self.ra, "reconcilier_passe", return_value=[]
            ) as faux:
                getattr(self.obj, methode)()
                faux.assert_called_once_with(passe, racine=self.menu.RACINE)

    def test_abort_in_the_conflict_queue_is_recorded(self):
        patch = self.mock.patch.object
        with patch(self.ra, "fichiers_en_conflit", return_value=[]), patch(
            self.ra, "abandonner_rebase"
        ), patch(self.ra, "noter_resolution") as noter, self.mock.patch(
            "builtins.input", return_value="7"
        ):
            self.obj._git_repo_resoudre(self.res, "20990101T0800")
        self.assertEqual(
            noter.call_args[0][:3], ("20990101T0800", self.res, "abandonne")
        )

    def test_continue_that_finishes_records_the_rebase(self):
        patch = self.mock.patch.object
        with patch(self.ra, "fichiers_en_conflit", return_value=[]), patch(
            self.ra, "continuer_rebase", return_value=("", "", 0)
        ), patch(self.ra, "rebase_en_cours", return_value=False), patch(
            self.ra, "noter_resolution"
        ) as noter, self.mock.patch(
            "builtins.input", return_value="5"
        ):
            self.obj._git_repo_resoudre(self.res, "20990101T0800")
        self.assertEqual(noter.call_args[0][2], "rebase")


class TestGitRepoCompareFreezes(unittest.TestCase):
    """L'entrée qui compare deux gels : le choix des côtés, puis les gestes.

    Le rapport et l'historique viennent de `git_freeze_diff`, remplacé ici :
    ces tests vérifient seulement ce que le menu en demande.
    """

    def setUp(self):
        from unittest import mock

        from script.todo import git_repo_menu

        self.mock = mock
        self.menu = git_repo_menu
        self.fd = git_repo_menu.git_freeze_diff

        class Menu(git_repo_menu.GitRepoMenuMixin):
            execute = None

        self.obj = Menu()

    def choisir(self, *saisies):
        with self.mock.patch("builtins.input", side_effect=saisies):
            return self.obj._git_repo_choisir_comparaison()

    def test_les_cas_courants(self):
        self.assertEqual(self.choisir("1"), ("HEAD", self.fd.CLONES))
        self.assertEqual(self.choisir("2"), (self.fd.WORKTREE, self.fd.CLONES))
        self.assertEqual(self.choisir("3"), ("HEAD", self.fd.WORKTREE))
        self.assertIsNone(self.choisir("0"))
        self.assertIsNone(self.choisir(""))

    def test_gel_precedent(self):
        with self.mock.patch.object(
            self.fd, "previous_freeze", return_value=("a", "b")
        ):
            self.assertEqual(self.choisir("4"), ("a", "b"))
        with self.mock.patch.object(
            self.fd, "previous_freeze", return_value=None
        ):
            self.assertIsNone(self.choisir("4"))

    def test_deux_revisions_dont_un_numero_de_la_liste(self):
        gels = [
            ("f" * 40, "2026-01-02", "gel 2"),
            ("e" * 40, "2026-01-01", "x"),
        ]
        refs = [("release, origin/release", "d" * 40)]
        with self.mock.patch.object(
            self.fd, "freeze_commits", return_value=gels
        ), self.mock.patch.object(
            self.fd, "frozen_refs", return_value=(refs, 0)
        ), self.mock.patch.object(
            self.menu.click, "prompt", side_effect=["2", "3"]
        ):
            self.assertEqual(self.choisir("5"), ("e" * 40, "d" * 40))

    def test_la_matrice(self):
        with self.mock.patch.object(
            self.fd, "default_matrix_sides", return_value=["v1", "clones"]
        ), self.mock.patch.object(
            self.menu.click, "prompt", return_value="v1, clones"
        ), self.mock.patch.object(
            self.fd, "matrix", return_value={"columns": [], "rows": []}
        ) as matrice, self.mock.patch.object(
            self.fd, "render_matrix", return_value=["ok"]
        ):
            self.assertIsNone(self.choisir("6"))
        self.assertEqual(matrice.call_args[0][1], ["v1", "clones"])
        with self.mock.patch.object(
            self.fd, "default_matrix_sides", return_value=[]
        ), self.mock.patch.object(
            self.menu.click, "prompt", return_value="nulle"
        ), self.mock.patch.object(
            self.fd, "matrix", side_effect=ValueError("unknown revision")
        ):
            self.assertEqual(self.obj._git_repo_matrice(), 2)

    def rapport(self, manquant=False):
        stats = {"missing": ["new"] if manquant else [], "files": []}
        ligne = {
            "status": self.fd.STATUS_CHANGED,
            "path": "x/a",
            "stats": stats,
        }
        return {"rows": [ligne, dict(ligne, path="x/b")]}

    def parcourir(self, rapport, *saisies):
        with self.mock.patch(
            "builtins.input", side_effect=list(saisies) + [""]
        ), self.mock.patch.object(
            self.fd, "open_history", return_value=0
        ) as tig, self.mock.patch(
            "builtins.print"
        ) as sortie:
            self.obj._git_repo_parcourir_comparaison(rapport)
        return tig, sortie

    def test_tig_sur_un_numero_puis_sur_chacun(self):
        rapport = self.rapport()
        tig, _ = self.parcourir(rapport, "2", "a")
        chemins = [appel.args[1]["path"] for appel in tig.call_args_list]
        self.assertEqual(chemins, ["x/b", "x/a", "x/b"])

    def test_un_commit_absent_offre_la_recherche(self):
        rapport = self.rapport(manquant=True)
        with self.mock.patch.object(
            self.fd, "fetch_missing", return_value={}
        ) as recherche, self.mock.patch.object(
            self.fd, "render_summary", return_value=[]
        ):
            tig, sortie = self.parcourir(rapport, "1", "f")
        tig.assert_not_called()
        recherche.assert_called_once()
        texte = " ".join(str(a) for c in sortie.call_args_list for a in c.args)
        self.assertIn(
            self.menu.t("Refresh: branches, tags and missing commits"), texte
        )

    def test_le_graphe_d_un_projet(self):
        rapport = self.rapport()
        with self.mock.patch.object(
            self.fd, "open_graph", return_value=0
        ) as graphe:
            tig, _ = self.parcourir(rapport, "b 2", "b9")
        tig.assert_not_called()
        self.assertEqual(
            [c.args[1]["path"] for c in graphe.call_args_list], ["x/b"]
        )

    def test_le_regroupement_tourne(self):
        rapport = self.rapport()
        with self.mock.patch.object(
            self.fd, "render_details", return_value=[]
        ) as details:
            self.parcourir(rapport, "g", "d", "g", "g", "d", "s2")
        groupes = [c.kwargs["group_by"] for c in details.call_args_list]
        self.assertEqual(groupes, ["module", "ext", "ext"])
        self.assertEqual(details.call_args_list[-1].kwargs["numeros"], {2})
        self.assertEqual(details.call_args_list[-1].kwargs["stat_count"], 0)

    def test_tig_a_la_suite_s_arrete_sur_une_sortie_en_erreur(self):
        rapport = self.rapport()
        with self.mock.patch(
            "builtins.input", side_effect=["a", ""]
        ), self.mock.patch.object(
            self.fd, "open_history", return_value=-2
        ) as tig, self.mock.patch(
            "builtins.print"
        ):
            self.obj._git_repo_parcourir_comparaison(rapport)
        self.assertEqual(tig.call_count, 1)

    def test_saisies_hors_limites(self):
        rapport = self.rapport()
        with self.mock.patch.object(
            self.fd, "render_details", return_value=[]
        ) as details:
            tig, sortie = self.parcourir(rapport, "s 9", "s", "²", "S x", "9")
        details.assert_not_called()
        tig.assert_not_called()
        texte = " ".join(str(a) for c in sortie.call_args_list for a in c.args)
        self.assertIn(
            self.menu.t("No changed project with both commits here."), texte
        )

    def test_une_revision_inconnue_rend_2(self):
        with self.mock.patch.object(
            self.obj, "_git_repo_choisir_comparaison", return_value=("x", "y")
        ), self.mock.patch.object(
            self.fd, "build", side_effect=ValueError("unknown revision: x")
        ):
            self.assertEqual(self.obj._git_repo_comparer(), 2)


class TestGitRepoForkCommits(unittest.TestCase):
    """Les gestes qui suivent l'état des forks : tig sur « base..gel ».

    La table vient de `repo_upgrade.nos_commits_geles`, et l'ouverture de
    `git_freeze_diff.open_range`, remplacées ici : aucun terminal ni clone.
    """

    def setUp(self):
        from unittest import mock

        from script.todo import git_repo_menu

        self.mock = mock
        self.menu = git_repo_menu

        class Menu(git_repo_menu.GitRepoMenuMixin):
            execute = None

        self.obj = Menu()

    def ligne(self, chemin, motif=None):
        return {
            "chemin": chemin,
            "dossier": f"/racine/{chemin}",
            "base": "b" * 40,
            "gel": "9" * 40,
            "nos": None if motif else 2,
            "motif": motif,
        }

    def parcourir(self, lignes, *saisies, code=0):
        with self.mock.patch.object(
            self.menu.repo_upgrade, "nos_commits_geles", return_value=lignes
        ), self.mock.patch(
            "builtins.input", side_effect=list(saisies) + [""]
        ) as saisie, self.mock.patch.object(
            self.menu.git_freeze_diff, "open_range", return_value=code
        ) as tig, self.mock.patch(
            "builtins.print"
        ) as sortie:
            self.obj._git_repo_parcourir_forks([])
        texte = " ".join(str(a) for c in sortie.call_args_list for a in c.args)
        return tig, saisie, texte

    def lignes(self):
        return [
            self.ligne("x/a"),
            self.ligne("x/b", motif="not cloned"),
            self.ligne("x/c"),
        ]

    def test_un_numero_ouvre_sa_plage(self):
        tig, _, texte = self.parcourir(self.lignes(), "3")
        tig.assert_called_once_with("/racine/x/c", f"{'b' * 40}..{'9' * 40}")
        self.assertIn(f"{'b' * 12}..{'9' * 12}", texte)
        self.assertIn(f"+2 {self.menu.t('ours')}", texte)
        self.assertIn("not cloned", texte)

    def test_a_ouvre_chacune_et_s_arrete_sur_une_erreur(self):
        tig, _, _ = self.parcourir(self.lignes(), "a")
        self.assertEqual(
            [c.args[0] for c in tig.call_args_list],
            ["/racine/x/a", "/racine/x/c"],
        )
        tig, _, _ = self.parcourir(self.lignes(), "a", code=-2)
        self.assertEqual(tig.call_count, 1)

    def test_une_ligne_sans_plage_dit_sa_raison(self):
        tig, _, texte = self.parcourir(self.lignes(), "2")
        tig.assert_not_called()
        self.assertIn("x/b — not cloned", texte)

    def test_saisies_refusees(self):
        tig, saisie, texte = self.parcourir(
            self.lignes(), "-1", "4", "x", "all", "1,", "0"
        )
        tig.assert_not_called()
        self.assertEqual(texte.count(self.menu.t("Command not found !")), 5)
        # « 0 » revient : la saisie vide ajoutée derrière n'est pas lue.
        self.assertEqual(saisie.call_count, 6)

    def test_rien_a_offrir(self):
        tig, saisie, _ = self.parcourir([])
        saisie.assert_not_called()
        tig, saisie, texte = self.parcourir(
            [self.ligne("x/b", motif="not cloned")]
        )
        saisie.assert_not_called()
        self.assertIn("not cloned", texte)

    def test_l_etat_des_forks_mene_aux_gestes(self):
        with self.mock.patch.object(
            self.menu.repo_upgrade, "version_active", return_value="X"
        ), self.mock.patch.object(
            self.menu.repo_upgrade, "etat_forks", return_value=[]
        ) as etat, self.mock.patch.object(
            self.menu.repo_upgrade, "render", return_value=""
        ), self.mock.patch.object(
            self.obj, "_git_repo_parcourir_forks"
        ) as gestes, self.mock.patch(
            "builtins.print"
        ):
            self.assertEqual(self.obj._git_repo_etat_forks(), 0)
        etat.assert_called_once_with("X", verifier=True)
        gestes.assert_called_once_with([])


class TestUpdateMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Update, dont le repli générique soustrayait deux fois.

    Ses entrées codées en dur suivent celles de todo.json, donc leur rang
    n'est pas connu à la lecture du source : elles portent « method ». Le
    repli calculait « int(status) - 1 » puis indexait encore à « - 1 »,
    ce qui rendait la PREMIÈRE entrée injoignable.
    """

    SOURCE = TODO_DIR / "todo.py"
    ENTRY = "def prompt_execute_update(self):"
    END = "def _update_odoo_migration(self):"
    MINIMUM = 1

    EXPECTED = {
        "Upgrade Odoo - Migration Database": "_update_odoo_migration",
        "Upgrade Poetry - Dependency of Odoo": "upgrade_poetry",
    }


class TestCodeMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Code, dont la queue s'adressait par arithmétique.

    « str(len(choices) - 2) » tient tant que rien ne s'insère, et désigne
    le voisin le jour où quelque chose s'insère. Les quatre entrées codées
    en dur portent donc leur destination.
    """

    SOURCE = TODO_DIR / "todo.py"
    ENTRY = "def prompt_execute_code(self):"
    END = "_GIT_HOOKS = ("
    MINIMUM = 3

    EXPECTED = {
        "Open SHELL": "open_shell_on_database",
        "Upgrade Module": "upgrade_module",
        "Debug": "debug_ide",
        "Update - Update all developed staging source code": (
            "prompt_execute_update"
        ),
    }


class TestPremiereEntreeJoignable(unittest.TestCase):
    """Non-régression : l'entrée [1] d'un menu doit être atteignable.

    Un repli qui soustrait deux fois laisse « 0 < 0 » faux pour le premier
    rang, et le menu répond « Command not found » sur une entrée qu'il
    vient d'afficher. Le défaut est muet : rien ne casse, une commande
    n'existe simplement plus.
    """

    def _repli(self, nom, fin):
        source = (TODO_DIR / "todo.py").read_text(encoding="utf-8")
        start = source.index(f"def {nom}(self):")
        return source[start : source.index(fin, start)]

    def test_update_ne_soustrait_pas_deux_fois(self):
        corps = self._repli(
            "prompt_execute_update", "def _update_odoo_migration"
        )
        self.assertIn("int_cmd = int(status)\n", corps)
        self.assertNotIn("int_cmd = int(status) - 1", corps)

    def test_code_ne_soustrait_pas_deux_fois(self):
        corps = self._repli("prompt_execute_code", "_GIT_HOOKS = (")
        self.assertIn("int_cmd = int(status)\n", corps)
        self.assertNotIn("int_cmd = int(status) - 1", corps)


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


if __name__ == "__main__":
    unittest.main()
