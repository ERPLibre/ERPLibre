#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""QEMU/KVM et Proxmox VE : la branche, dev ou prod, et ce qu'on installe
sur une VM, sous les règles des choix.

Chacune se choisit par son numéro, ou par le nom ou le libellé que la
liste écrit ; une réponse vide prend le défaut marqué ; une faute est dite
et la question revient, au lieu de prendre le défaut en silence. [0]
renonce : au déploiement QEMU, dont rien n'est encore créé ; à
l'installation seule sur Proxmox, où la VM existe déjà. Chaque liste de
réponses finit par une réponse acceptée ou « 0 ».

Les branches, l'hôte, le module de déploiement et les commandes sont
doublés : rien n'est lancé.
"""

import io
import sys
import types
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest import mock

sys.argv = ["todo.py"]
from script.proxmox import proxmox_deploy  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

BRANCHES = ["develop", "master", "forged_branch"]


class _Cas(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.todo._qemu_branch_list = lambda: list(BRANCHES)

    def play(self, call, *answers):
        """Ce que rend `call()` quand `input` reçoit `answers` ; ce qui
        s'imprime va dans `self.shown`, les invites dans `self.asked`."""
        out = io.StringIO()
        with (
            mock.patch("builtins.input", side_effect=answers) as asked,
            redirect_stdout(out),
        ):
            got = call()
        self.shown = out.getvalue()
        self.asked = [c.args[0] for c in asked.call_args_list]
        return got

    def refused(self):
        return [
            line[len(t("Invalid choice: ")) :]
            for line in self.shown.splitlines()
            if line.startswith(t("Invalid choice: "))
        ]


class TestLesTroisQuestions(_Cas):
    def test_the_branch_by_number_or_name_and_master_by_default(self):
        pick = self.todo._qemu_pick_branch
        for answer, branch in (("", "master"), ("3", "forged_branch")):
            with self.subTest(answer=answer):
                self.assertEqual(self.play(pick, answer), branch)
        self.assertEqual(self.play(pick, "develop"), "develop")
        self.assertIn(f"[2] master {t('(default)')}\n", self.shown)
        wrong = ["01", "Master", "4", "forged"]
        self.assertIsNone(self.play(pick, *wrong, "0"))
        self.assertEqual(self.refused(), wrong)
        # Sans liste lisible, la branche se tape, master par défaut ; « 0 »
        # renonce, comme [0].
        self.todo._qemu_branch_list = lambda: []
        self.assertEqual(self.play(pick, ""), "master")
        self.assertEqual(self.play(pick, "forged_typed"), "forged_typed")
        self.assertIsNone(self.play(pick, "0"))

    def test_dev_or_prod_and_dev_by_default(self):
        ask = self.todo._qemu_ask_prod
        self.assertIs(self.play(ask, ""), False)
        self.assertIn(t("(default)"), self.shown.splitlines()[1])
        self.assertIs(self.play(ask, "2"), True)
        # Toute autre réponse que 2 valait dev, sans un mot.
        self.assertIsNone(self.play(ask, "prod", "3", "0"))
        self.assertEqual(self.refused(), ["prod", "3"])

    def test_the_profile_by_number_or_label_the_imposed_one_first(self):
        pick = self.todo._qemu_pick_install_profile
        label, cmd = self.play(lambda: pick("ubuntu"), "")
        self.assertIn("install_odoo_18", cmd)
        label, cmd = self.play(lambda: pick("proxmox"), "")
        self.assertIn("install_proxmox.sh", cmd)
        wanted = t("ERPLibre only (no Odoo)")
        self.assertEqual(self.play(lambda: pick(""), wanted)[0], wanted)
        self.assertEqual(self.play(lambda: pick(""), "2")[1].count("17"), 1)
        # Une faute prenait Odoo 18 en silence.
        wrong = ["13", "01", "Odoo 18"]
        self.assertIsNone(self.play(lambda: pick(""), *wrong, "0"))
        self.assertEqual(self.refused(), wrong)

    def test_zero_at_any_question_gives_up_the_three(self):
        ask = self.todo._qemu_install_questions
        for answers in (("0",), ("", "0"), ("", "", "0")):
            with self.subTest(answers=answers):
                self.assertIsNone(self.play(ask, *answers))
                self.assertEqual(len(self.asked), len(answers))
        branch, prod, (label, cmd) = self.play(ask, "", "2", "")
        self.assertEqual((branch, prod), ("master", True))
        self.assertIn("install_odoo_18", cmd)


class TestLeDeploiementQemu(_Cas):
    """Le déploiement QEMU par questions : [0] à une question
    d'installation y renonce, sans un mot, avant toute autre question."""

    def setUp(self):
        super().setUp()
        todo = self.todo
        todo._qemu_default_ssh_key = lambda: "/forged/id_ed25519.pub"
        todo._qemu_ask_timezone = lambda: "UTC"
        todo._qemu_ask_locale = lambda: "C.UTF-8"
        todo._qemu_ask_desktop = lambda: ""
        todo._qemu_desktop_suffixes = lambda: {}
        todo._qemu_ask_app_store = lambda vms: "deb"
        todo._qemu_ask_vm_tools = lambda vms: ()
        todo._qemu_ask_python_provider = lambda arches: "mise"
        todo._qemu_list_domains = lambda: self.fail("déploiement poursuivi")

    def collect(self, *answers):
        vms = [{"name": "forged-vm", "distro": "debian", "arch": "amd64"}]
        call = lambda: self.todo._qemu_collect_options_cli(vms, "x1")  # noqa: E731
        return self.play(call, *answers)

    def test_zero_at_an_install_question_deploys_nothing(self):
        # La clé, puis « installer ERPLibre ? », puis la branche, dev ou
        # prod et le profil.
        for back in (("0",), ("", "0"), ("", "", "0")):
            with self.subTest(back=back):
                self.assertIsNone(self.collect("", "", *back))
                self.assertEqual(len(self.asked), 2 + len(back))
                self.assertNotIn(t("Cancelled."), self.shown)


class TestLeDeploiementProxmox(_Cas):
    """Le déploiement Proxmox par questions : l'installation se demande
    une fois la VM créée ; [0] à la branche ou au profil n'y installe
    rien, et l'épilogue reçoit une installation vide."""

    MOD = types.SimpleNamespace(
        DISTROS={"debian": ({"12": ("bookworm", "o", 1024, "8G")}, "12")},
        image_url=lambda *a: "https://forged.example.net/image.qcow2",
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
        "ipconfig_for": "ip=192.0.2.20/24",
        "ip_from_ipconfig": "192.0.2.20",
        "image_fetch_cmd": "forged fetch",
        "create_cmds": ["forged create"],
    }

    def setUp(self):
        super().setUp()
        todo = self.todo
        self.installs = []
        todo._pve_host = lambda: {"target": "root@forged-pve"}
        todo._qemu_import_module = lambda: self.MOD
        todo._qemu_ask_ram = lambda *a: 1024
        todo._qemu_ask_cpu = lambda *a: 2
        todo._pve_show = lambda cmd, **k: (0, "")
        todo._pve_vms = lambda: []
        todo._qemu_default_ssh_key = lambda: ""
        todo._pve_user_data = lambda *a: ""
        todo._qemu_host_timezone = lambda: "UTC"
        todo._pve_after_create = lambda host, spec, names, key: (
            self.installs.append(spec["install"])
        )
        todo._pve_print_summary = lambda *a: None

    def deploy(self, *answers):
        with ExitStack() as stack:
            for name, value in self.PVE.items():
                stack.enter_context(
                    mock.patch.object(
                        proxmox_deploy, name, lambda *a, v=value, **k: v
                    )
                )
            # Debian, sa version par défaut, le nom, le disque, « déployer ? »
            # et « installer ERPLibre ? » par défaut, puis `answers`.
            first = ("2", "", "", "", "", "")
            self.play(self.todo._pve_deploy_prompts, *first, *answers)
        return self.installs.pop()

    def test_zero_at_the_branch_or_the_profile_installs_nothing(self):
        for back in (("0",), ("", "0")):
            with self.subTest(back=back):
                self.assertIsNone(self.deploy(*back))
        install = self.deploy("", "")
        self.assertEqual(install["branch"], "master")
        self.assertIn("install_odoo_18", install["cmd"])


if __name__ == "__main__":
    unittest.main()
