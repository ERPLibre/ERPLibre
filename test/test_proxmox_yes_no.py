#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu Proxmox VE, ses VPN et ses tests longs : les questions oui/non,
sous les règles de `ui.confirm`.

Chaque question est non par défaut, sauf trois qui sont oui : déployer la
VM récapitulée, y installer ERPLibre, parcourir le dossier des profils
AnyConnect. Un refus — Entrée là où le défaut est non, n, non, une faute
puis Ctrl+D, Ctrl+D — ne lance, n'efface, n'enregistre ni ne libère rien ;
o, oui, y et yes agissent. Les drapeaux d'un profil VPN prennent l'état du
profil pour défaut, et Ctrl+D garde cet état.

ssh, ssh-keyscan, qm, pvesm, le CLI VPN et les tests longs ne partent
jamais : `execute`, `_pve_show`, `pve.run` et `subprocess.run` sont des
doubles qui notent. Un `ScriptedPort` répond aux questions du port ;
`input` ne lit que les valeurs tapées.
"""

import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack
from unittest import mock

sys.argv = ["todo.py"]
from script.proxmox import proxmox_deploy as pve  # noqa: E402
from script.todo import (  # noqa: E402
    longtest_menu,
    proxmox_menu,
    todo_i18n,
    ui,
    vpn_menu,
)
from script.todo.longtest_menu import SCRIPTS_DEFAISABLES  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402
from script.todo.ui.port import ScriptedPort  # noqa: E402
from script.vpn.drivers import DRIVERS  # noqa: E402

VM = "forged-yesno-vm"
HOST = "forged-yesno-host"
PROFILE = "forged_yesno_profile"
# Défaut non : une réponse vide, une faute puis Ctrl+D, Ctrl+D refusent.
REFUS = ([""], ["peut-être", EOFError()], [EOFError()])
OUI = (["o"], ["oui"], ["y"], ["YES"])
# Défaut oui : n, non, une faute puis Ctrl+D, Ctrl+D refusent.
REFUS_OUI = (["n"], ["non"], ["peut-être", EOFError()], [EOFError()])
OUI_OUI = ([""], *OUI)


class _Execute:
    """Note chaque commande, sans rien lancer."""

    def __init__(self):
        self.cmds = []

    def exec_command_live(self, cmd, **_opts):
        self.cmds.append(cmd)
        return 0


class _Base(unittest.TestCase):
    def setUp(self):
        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("fr")

    def new(self):
        todo = TODO.__new__(TODO)
        todo.execute = _Execute()
        return todo

    def play(self, call, answers, typed=()):
        """Ce que rend `call()` quand `answers` répondent, dans l'ordre, par
        un `ScriptedPort` (`self.port`) ; `typed` répond aux valeurs lues
        par `input`, qu'aucune autre question ne lit."""
        with (
            mock.patch(
                "builtins.input",
                side_effect=list(typed) if typed else AssertionError,
            ),
            mock.patch("builtins.print"),
            ui.bind(ScriptedPort(list(answers))) as self.port,
        ):
            return call()

    def asked(self):
        """(texte sans indice, défaut « y » ou « n ») de chaque question
        oui/non posée, une fois de plus après chaque faute."""
        return [
            (event["prompt"], event["default"])
            for event in self.port.events
            if event.get("kind") == "confirm"
        ]

    def check(self, make, prompt, default=False, pre=(), before=()):
        """`make()` rend (`call`, `acted`), neufs pour chaque cas ; la
        question oui/non `prompt`, de défaut `default`, suit les réponses
        `pre` et les questions `before` ((texte, défaut) déjà acceptées) :
        chaque refus laisse `acted()` faux, chaque oui le rend vrai, chaque
        réponse est lue ; une faute est dite, puis la question revient. Un
        refus n'en pose aucune autre ; après un oui, une question qui suit
        lit une entrée fermée."""
        refus, oui = (REFUS_OUI, OUI_OUI) if default else (REFUS, OUI)
        cases = [(r, False) for r in refus] + [(o, True) for o in oui]
        for answers, expected in cases:
            with self.subTest(answers=answers):
                call, acted = make()
                self.play(call, [*pre, *answers])
                fois = 2 if "peut-être" in answers else 1
                posee = (prompt, "y" if default else "n")
                wanted = [*before, *[posee] * fois]
                asked = self.asked()
                self.assertEqual(asked[: len(wanted)], wanted)
                if not expected:
                    self.assertEqual(len(asked), len(wanted))
                self.assertEqual(self.port.answers, [])
                self.assertIs(acted(), expected)
                if "peut-être" in answers:
                    self.assertIn(
                        f"{t('Answer yes or no: ')}peut-être",
                        [
                            e["text"]
                            for e in self.port.events
                            if e.get("t") == "notice"
                        ],
                    )


class TestLesVmProxmox(_Base):
    """La clé d'hôte, l'état, la suppression et le nettoyage des VM."""

    def test_the_host_key_is_recorded_on_a_yes_only(self):
        def make():
            todo = self.new()
            todo._ssh_resolve = lambda target: {}
            run = mock.Mock(
                return_value=subprocess.CompletedProcess([], 1, "", "")
            )

            def call():
                with mock.patch.object(proxmox_menu.subprocess, "run", run):
                    return todo._pve_add_hostkey({"target": f"root@{HOST}"})

            return call, lambda: run.called

        self.check(make, t("Record it?"))

    def test_a_state_change_waits_for_a_yes(self):
        def make():
            todo = self.new()
            todo._pve_pick_vm = lambda *a, **k: [{"vmid": "9", "name": VM}]
            todo._pve_host = lambda: {"target": f"root@{HOST}"}
            run = mock.Mock(return_value=(0, ""))

            def call():
                with mock.patch.object(pve, "run", run):
                    todo._pve_change_state()

            return call, lambda: run.called

        self.check(make, t("Confirm?"), pre=["2"])

    def _deletion(self):
        shown = []
        todo = self.new()
        todo._pve_pick_vm = lambda *a, **k: [{"vmid": "9", "name": VM}]
        todo._pve_show = lambda cmd, **k: shown.append(cmd) or (0, "")
        return todo._pve_delete, lambda: bool(shown)

    def test_deleting_vms_waits_for_the_first_yes(self):
        """« --purge » emporte disques et sauvegardes : un refus à la
        première question n'en pose pas de seconde, un oui la pose."""
        second = (t("Confirm for real?"), "n")

        def make():
            call, _destroyed = self._deletion()
            return call, lambda: second in self.asked()

        self.check(make, t("Apply: %s?") % f"9 ({VM})")

    def test_deleting_vms_waits_for_the_second_yes(self):
        apply = (t("Apply: %s?") % f"9 ({VM})", "n")
        self.check(
            self._deletion,
            t("Confirm for real?"),
            pre=["o"],
            before=[apply],
        )

    def test_orphan_disks_are_freed_on_a_yes_only(self):
        def make():
            freed = []
            todo = self.new()
            todo._pve_vms = lambda: []

            def show(cmd, **_k):
                if cmd.startswith("pvesm free"):
                    freed.append(cmd)
                return 0, ""

            todo._pve_show = show
            orphans = [("local:vm-9-disk-0", 1 << 30)]

            def call():
                with mock.patch.object(
                    pve, "parse_orphans", return_value=orphans
                ):
                    todo._pve_cleanup()

            return call, lambda: bool(freed)

        self.check(make, t("Free them?"))

    def test_the_recap_deploys_by_default(self):
        spec = {
            "storage": "local",
            "bridge": "vmbr0",
            "res_label": "",
            "vms": [
                {
                    "name": VM,
                    "vmid": "9",
                    "vcpus": 1,
                    "ram": 512,
                    "disk": "8G",
                }
            ],
        }

        def make():
            todo = self.new()
            todo._pve_label = lambda host: HOST
            todo._qemu_login_line = lambda spec: ""
            got = []

            def call():
                got.append(todo._pve_confirm_spec({"target": HOST}, spec))

            return call, lambda: got[0]

        self.check(make, t("Deploy this VM now?"), default=True)


class TestLeDeploiementParQuestions(_Base):
    """Déployer la VM, puis y installer ERPLibre : oui par défaut, et un
    refus au déploiement ne crée rien."""

    MOD = types.SimpleNamespace(
        DISTROS={"debian": ({"12": ("bookworm", "o", 1024, "8G")}, "12")},
        image_url=lambda *a: "https://forged-yesno.example.net/image.qcow2",
        default_image_name=lambda *a: "forged.qcow2",
        requiert_uefi=lambda distro: False,
        pinned_sha256=lambda distro: "",
    )
    PVE = {
        "parse_storages": ["local"],
        "parse_bridges": ["vmbr0"],
        "parse_bridge_config": {},
        "pick_storage": "local",
        "pick_bridge": "vmbr0",
        "next_vmid": 100,
        "ipconfig_for": "ip=192.0.2.83/24",
        "ip_from_ipconfig": "192.0.2.83",
        "image_fetch_cmd": "forged fetch",
        "create_cmds": ["forged create"],
    }

    def deploy(self):
        """(`call`, ce que `_pve_show` a lancé, les questions
        d'installation posées)."""
        shown, installs = [], []
        todo = self.new()
        todo._pve_host = lambda: {"target": f"root@{HOST}"}
        todo._qemu_import_module = lambda: self.MOD
        todo._qemu_prompt_distro = lambda: "debian"
        todo._qemu_prompt_version = lambda distro: "12"
        todo._qemu_ask_ram = lambda *a: 1024
        todo._qemu_ask_cpu = lambda *a: 2
        todo._pve_show = lambda cmd, **k: shown.append(cmd) or (0, "")
        todo._pve_vms = lambda: []
        todo._qemu_default_ssh_key = lambda: ""
        todo._pve_user_data = lambda *a, **k: ""
        todo._qemu_host_timezone = lambda: "UTC"
        todo._qemu_install_questions = lambda *a, **k: installs.append(a)
        todo._pve_after_create = lambda *a: None
        todo._pve_print_summary = lambda *a: None

        def call():
            with ExitStack() as stack:
                for name, value in self.PVE.items():
                    stack.enter_context(
                        mock.patch.object(
                            pve, name, lambda *a, v=value, **k: v
                        )
                    )
                stack.enter_context(
                    mock.patch("builtins.input", side_effect=["", ""])
                )
                todo._pve_deploy_prompts()

        return call, shown, installs

    def play(self, call, answers):
        """Le nom et le disque se lisent par `input` dans `call`."""
        with (
            mock.patch("builtins.print"),
            ui.bind(ScriptedPort(list(answers))) as self.port,
        ):
            return call()

    def test_the_vm_is_created_on_a_yes_only(self):
        def make():
            call, shown, _ = self.deploy()
            return call, lambda: "forged create" in shown

        # Le oui au déploiement mène à l'installation, refusée ensuite.
        deploy = (t("Deploy this VM now?"), "y")
        install = (t("Install ERPLibre on it?"), "y")
        for answers in REFUS_OUI:
            with self.subTest(answers=answers):
                call, acted = make()
                self.play(call, answers)
                self.assertFalse(acted())
                self.assertEqual(self.port.answers, [])
                fois = 2 if "peut-être" in answers else 1
                self.assertEqual(self.asked(), [deploy] * fois)
        for answers in OUI_OUI:
            with self.subTest(answers=answers):
                call, acted = make()
                self.play(call, [*answers, "n"])
                self.assertTrue(acted())
                self.assertEqual(self.asked()[-1], install)

    def test_erplibre_is_installed_on_a_yes_only(self):
        def make():
            call, _, installs = self.deploy()
            return call, lambda: bool(installs)

        deploy = (t("Deploy this VM now?"), "y")
        self.check(
            make,
            t("Install ERPLibre on it?"),
            default=True,
            pre=["o"],
            before=[deploy],
        )


class TestLeVpn(_Base):
    """Le tunnel, le greffon SSO, le dossier AnyConnect, les réglages
    avancés, la suppression d'un profil et ses drapeaux."""

    def vpn(self, up=True):
        todo = self.new()
        todo._vpn_select_profile = lambda: PROFILE
        todo._vpn_is_up = lambda profile: up
        todo._vpn_secrets_env = lambda name: {}
        return todo

    def connect(self, todo):
        def call():
            with mock.patch.object(vpn_menu.profiles, "load", return_value={}):
                todo._vpn_connect()

        return call

    def test_reconnecting_a_live_tunnel_waits_for_a_yes(self):
        def make():
            todo = self.vpn()
            return self.connect(todo), lambda: bool(todo.execute.cmds)

        self.check(make, t("Connect it again?"))

    def test_the_tunnel_comes_up_after_its_plan_on_a_yes_only(self):
        def make():
            todo = self.vpn(up=False)

            def acted():
                self.assertTrue(
                    todo.execute.cmds[0].endswith("--dry-run"),
                    "le plan manque",
                )
                return len(todo.execute.cmds) == 2

            return self.connect(todo), acted

        self.check(make, t("Run this plan?"))

    def test_the_sso_helper_is_installed_on_a_yes_only(self):
        def make():
            todo = self.vpn()
            todo._vpn_pick_driver = lambda current: DRIVERS["openconnect"]

            def call():
                with mock.patch.object(
                    vpn_menu, "_sso_helper_seen", return_value=False
                ):
                    todo._vpn_install()

            def acted():
                self.assertEqual(len(todo.execute.cmds), 1)
                return "--with-sso" in todo.execute.cmds[0]

            return call, acted

        self.check(make, t("Install it as well?"))

    def test_the_anyconnect_folder_is_browsed_by_default(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)

        def make():
            todo = self.vpn()
            browsers = []

            class Browser:
                def __init__(self, start, on_selected):
                    browsers.append(start)

                def run_main_frame(self):
                    pass

            fake = types.SimpleNamespace(FileBrowser=Browser)

            def call():
                with (
                    mock.patch.object(
                        vpn_menu, "ANYCONNECT_DIRS", (folder.name,)
                    ),
                    mock.patch.object(vpn_menu, "todo_file_browser", fake),
                    mock.patch("builtins.input", side_effect=[""]),
                ):
                    todo._vpn_select_xml()

            return call, lambda: browsers == [folder.name]

        self.check(make, t("Browse it?"), default=True)

    def edit(self, saved):
        """`call` qui remplit le profil sshuttle `PROFILE`, chaque valeur
        tapée gardée ; `saved` reçoit ce que le formulaire enregistre."""
        todo = self.vpn()
        seed = {"name": PROFILE, "driver": "sshuttle", "server": HOST}

        def save(draft):
            saved.append(draft)
            return dict(draft, routes=[], default_route=False)

        def call():
            with (
                mock.patch.object(vpn_menu.profiles, "save", save),
                mock.patch("builtins.input", side_effect=lambda *_a: ""),
            ):
                todo._vpn_edit_profile(seed=seed)

        return call

    def test_advanced_settings_wait_for_a_yes(self):
        """Le port SSH, tapé, et le DNS par le tunnel, un drapeau, ne se
        demandent qu'après un oui ; le profil s'enregistre dans les deux
        cas."""
        traffic = (t("Send ALL traffic through the tunnel?"), "n")
        dns = (t("Also send DNS queries through the tunnel?"), "y")
        for answers, expected in [(r, False) for r in REFUS] + [
            (o, True) for o in OUI
        ]:
            with self.subTest(answers=answers):
                saved = []
                self.play(self.edit(saved), ["", *answers, ""])
                asked = self.asked()
                self.assertEqual(asked[0], traffic)
                self.assertEqual(asked[-1] == dns, expected)
                self.assertEqual(len(saved), 1)
                if not expected:
                    self.assertEqual(
                        asked[1:],
                        [(t("Advanced settings?"), "n")]
                        * (2 if "peut-être" in answers else 1),
                    )

    def test_deleting_a_profile_waits_for_a_yes(self):
        def make():
            todo = self.vpn()
            deleted = []

            def call():
                with mock.patch.object(
                    vpn_menu.profiles, "delete", side_effect=deleted.append
                ):
                    todo._vpn_delete_profile()

            return call, lambda: deleted == [PROFILE]

        self.check(make, t("Delete profile « %s »?") % PROFILE)

    def test_a_flag_takes_the_state_of_the_profile_for_default(self):
        """Entrée, une faute puis Ctrl+D et Ctrl+D gardent l'état ; o et n
        le fixent. L'indice suit l'état."""
        label = t("Send ALL traffic through the tunnel?")
        for state in (True, False):
            for answers, expected in (
                ([""], state),
                (["peut-être", EOFError()], state),
                ([EOFError()], state),
                (["o"], True),
                (["non"], False),
            ):
                with self.subTest(state=state, answers=answers):
                    got = self.play(
                        lambda s=state: TODO._vpn_ask_flag(label, s), answers
                    )
                    self.assertIs(got, expected)
                    fois = 2 if "peut-être" in answers else 1
                    self.assertEqual(
                        self.asked(), [(label, "y" if state else "n")] * fois
                    )


class TestLesTestsLongs(_Base):
    """Lancer un test long ou défaire ses machines : non par défaut."""

    def longtest(self):
        todo = self.new()
        todo._longtest_script = lambda nom: (
            f"{longtest_menu.LONGTEST_DIR}/{nom}"
        )
        return todo

    def test_a_long_test_runs_on_a_yes_only(self):
        for args, prompt in (
            ("", "Run this long test?"),
            ("--detruire", "Destroy the machines of this test?"),
        ):
            with self.subTest(args=args):

                def make(args=args):
                    todo = self.longtest()
                    return (
                        lambda: todo._longtest_run("deep_qemu.py", args),
                        lambda: bool(todo.execute.cmds),
                    )

                self.check(make, t(prompt))

    def test_undoing_destroys_on_a_yes_only(self):
        """Chaque pile montre d'abord son plan à blanc ; un refus, ou une
        entrée fermée, n'en détruit aucune, et la question revient pour
        la suivante."""
        n = len(SCRIPTS_DEFAISABLES)
        for answers, destroyed in (
            ([], 0),
            (["", "peut-être", EOFError()], 0),
            (["o"], 1),
            (["", "oui"], 1),
        ):
            with self.subTest(answers=answers):
                todo = self.longtest()
                self.play(todo._longtest_defaire, answers)
                fois = n + answers.count("peut-être")
                self.assertEqual(
                    self.asked(), [(t("Destroy all that?"), "n")] * fois
                )
                dry = [c for c in todo.execute.cmds if "--dry-run" in c]
                self.assertEqual(len(dry), n)
                self.assertEqual(len(todo.execute.cmds) - n, destroyed)


if __name__ == "__main__":
    unittest.main()
