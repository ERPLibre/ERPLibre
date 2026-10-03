#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""QEMU/KVM › Deploy VM(s) : les questions à défaut du déploiement par
questions, sous les règles des choix.

L'interface, les ressources, le type de VM, le magasin d'applications,
l'interpréteur Python et l'agent d'IA se choisissent par leur numéro, ou
par le nom que la liste écrit quand elle en écrit un ; une réponse vide
prend le défaut marqué ; une faute est dite et la question revient, au
lieu de prendre le défaut en silence. [0] renonce au déploiement, sans
un mot, rien n'étant encore créé, avant toute autre question. Chaque
liste de réponses finit par une réponse acceptée ou « 0 ».

Le catalogue, les préférences et le reste du déploiement sont doublés :
rien n'est créé.
"""

import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import todo_i18n, todo_prefs  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

MOD = types.SimpleNamespace(
    DISTROS={"forged_a": ({"1": ("c", "o", 1024, "10G")}, "1")}
)


class _Cas(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.enterContext(mock.patch.object(todo_prefs, "get", lambda k: None))

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


class TestLesQuestionsADefaut(_Cas):
    def test_each_list_takes_its_marked_default_on_an_empty_answer(self):
        todo = self.todo
        gui = [{"desktop": "gnome", "distro": "ubuntu"}]
        cases = (
            (todo._qemu_ask_ui, "tui"),
            (todo._qemu_ask_desktop, ""),
            (lambda: todo._qemu_ask_app_store(gui), "deb"),
            (lambda: todo._qemu_ask_python_provider(["amd64"]), "mise"),
            (lambda: todo._qemu_ask_ai_tools(("aidev",))[0], "claude"),
        )
        todo._qemu_host_git = lambda key: "forged"
        for call, default in cases:
            with self.subTest(default=default):
                self.assertEqual(self.play(call, "", "", ""), default)
                self.assertEqual(self.shown.count(t("(default)")), 1)

    def test_a_number_or_a_shown_name(self):
        todo = self.todo
        todo._qemu_host_git = lambda key: "forged"
        gui = [{"desktop": "gnome", "distro": "ubuntu"}]
        cases = (
            (todo._qemu_ask_ui, "2", "cli"),
            (todo._qemu_ask_desktop, "GNOME", "gnome"),
            (todo._qemu_ask_desktop, "2", "gnome"),
            (lambda: todo._qemu_ask_app_store(gui), "3", "snap"),
            (lambda: todo._qemu_ask_app_store(gui), "flatpak", "flatpak"),
            (
                lambda: todo._qemu_ask_python_provider(["amd64"]),
                "pyenv",
                "pyenv",
            ),
            (
                lambda: todo._qemu_ask_ai_tools(("aidev",))[0],
                "opencode",
                "opencode",
            ),
        )
        for call, answer, expected in cases:
            with self.subTest(answer=answer):
                self.assertEqual(self.play(call, answer, "", ""), expected)

    def test_each_store_shows_the_name_it_answers_to(self):
        # Un magasin se nomme par ce que la liste écrit : son libellé
        # commence par le nom que la réponse accepte, dans les deux langues.
        self.addCleanup(todo_i18n.use_lang, todo_i18n.get_lang())
        gui = [{"desktop": "gnome", "distro": "ubuntu"}]
        stores = ("deb", "flatpak", "snap")
        for lang in ("fr", "en"):
            todo_i18n.use_lang(lang)
            for number, name in enumerate(stores, 1):
                with self.subTest(lang=lang, name=name):
                    got = self.play(
                        lambda: self.todo._qemu_ask_app_store(gui), name
                    )
                    self.assertEqual(got, name)
                    self.assertIn(f"\n[{number}] {name} ", self.shown)

    def test_an_invalid_answer_is_named_and_zero_goes_back(self):
        # Une faute est nommée et la question revient : elle ne prend pas
        # en silence le défaut, la TUI, le serveur, deb, mise ou l'agent.
        todo = self.todo
        gui = [{"desktop": "gnome", "distro": "ubuntu"}]
        for call in (
            todo._qemu_ask_ui,
            todo._qemu_ask_desktop,
            lambda: todo._qemu_ask_app_store(gui),
            lambda: todo._qemu_ask_python_provider(["amd64"]),
            lambda: todo._qemu_ask_ai_tools(("aidev",)),
        ):
            with self.subTest(call=call):
                wrong = ["9", "01", "x"]
                self.assertIsNone(self.play(call, *wrong, "0"))
                self.assertEqual(self.refused(), wrong)

    def test_the_resources_by_multiplier_or_custom(self):
        selected = [("forged_a", "1", 1024, "10G", "amd64")]
        ask = self.todo._qemu_prompt_resources
        label, vms = self.play(lambda: ask(selected, 8, 0), "")
        self.assertEqual((label, vms[0][2], vms[0][5]), ("x1", 1024, 2))
        self.assertIn("[1] x1  2 vCPU/VM", self.shown)
        label, vms = self.play(lambda: ask(selected, 8, 0), "3")
        self.assertEqual((label, vms[0][2], vms[0][5]), ("x3", 3072, 6))
        label, vms = self.play(lambda: ask(selected, 8, 0), "x2")
        self.assertEqual((label, vms[0][2], vms[0][5]), ("x2", 2048, 4))
        # [5] pose les vCPU, la RAM et le disque une fois pour tout le
        # parc ; une réponse vide garde la valeur du catalogue.
        custom = [("forged_a", "1", 4096, "40G", "amd64", 4)]
        got = self.play(lambda: ask(selected, 8, 0), "5", "4", "4096", "40")
        self.assertEqual(got, (t("custom"), custom))
        kept = [("forged_a", "1", 1024, "10G", "amd64", 2)]
        got = self.play(lambda: ask(selected, 8, 0), "5", "", "", "")
        self.assertEqual(got, (t("custom"), kept))
        self.assertEqual(len(self.asked), 4)
        # Une faute est nommée et redemandée : elle ne prend pas x1 en
        # silence.
        self.assertIsNone(self.play(lambda: ask(selected, 8, 0), "6", "0"))
        self.assertEqual(self.refused(), ["6"])


class TestZeroRenonceAuDeploiement(_Cas):
    def test_zero_at_the_interface_opens_nothing(self):
        todo = self.todo
        todo._qemu_import_module = lambda: MOD
        todo._qemu_last_run_line = lambda: ""
        todo._qemu_check_libvirt_group = lambda: None
        todo._qemu_check_kvm = lambda: None
        todo._qemu_deploy_form = lambda *a: self.fail("formulaire ouvert")
        todo._qemu_collect_vms_cli = lambda *a: self.fail("questions posées")
        self.assertIsNone(self.play(lambda: todo._qemu_deploy(True), "0"))

    def test_zero_at_the_resources_asks_nothing_more(self):
        todo = self.todo
        todo._qemu_prompt_infra_arch = lambda: "amd64"
        todo._qemu_arch_distros = lambda arch: None
        todo._qemu_stat_avg = lambda *a: ""
        todo._host_free_ram_mb = lambda: 8192
        todo._qemu_customize_vms = lambda *a: self.fail("VM personnalisées")
        # La distribution, sa version, puis [0] aux ressources.
        got = self.play(lambda: todo._qemu_collect_vms_cli(MOD), "1", "1", "0")
        self.assertIsNone(got)
        self.assertEqual(len(self.asked), 3)

    def test_zero_at_an_option_list_deploys_nothing(self):
        todo = self.todo
        todo._qemu_default_ssh_key = lambda: "/forged/id_ed25519.pub"
        todo._qemu_ask_timezone = lambda: "UTC"
        todo._qemu_ask_locale = lambda: "C.UTF-8"
        todo._qemu_desktop_suffixes = lambda: {}
        todo._qemu_ask_vm_tools = lambda vms: ("aidev",)
        todo._qemu_cache_active = lambda: False
        todo._qemu_list_domains = lambda: self.fail("déploiement poursuivi")
        vms = [{"name": "forged-vm", "distro": "ubuntu", "arch": "amd64"}]
        # La clé, puis le type de VM, le magasin (un bureau Ubuntu), Python,
        # « installer ERPLibre ? », « suivre ? », la 3D, puis l'agent.
        for answers in (
            ("", "0"),
            ("", "2", "0"),
            ("", "", "0"),
            ("", "", "", "n", "n", "n", "0"),
        ):
            with self.subTest(answers=answers):
                vm = [dict(v) for v in vms]
                call = lambda: todo._qemu_collect_options_cli(vm, "x1")  # noqa: B023,E731
                self.assertIsNone(self.play(call, *answers))
                self.assertEqual(len(self.asked), len(answers))
                self.assertNotIn(t("Cancelled."), self.shown)


SELECTED = [
    ("forged_a", "1", 1024, "10G", "amd64", 2),
    ("forged_b", "2", 2048, "20G", "amd64", 2),
]
TOOLS = [("pycharm", "PyCharm", "IDE"), ("forgejo", "Forgejo", "forge")]


class TestLesChoixMultiples(_Cas):
    """Les VM à personnaliser et les outils de développement : un choix
    multiple, par numéro, plage, nom ou `tout` ; une réponse vide n'en
    prend aucun ; une faute redemande la réponse entière au lieu d'en
    écarter un morceau sans rien dire, et `tous` ne se lit plus."""

    def setUp(self):
        super().setUp()
        todo = self.todo
        todo._qemu_infra_name = lambda d, v, a: f"forged-vm-{d[-1]}"
        todo._qemu_vm_tool_choices = lambda: list(TOOLS)
        todo._qemu_tools_for = lambda *a: ["x"]
        todo._QEMU_VM_TOOLS = {
            "pycharm": {"disk_gb": 3},
            "forgejo": {"disk_gb": 1},
        }

    def customize(self, *answers):
        call = lambda: self.todo._qemu_customize_vms(SELECTED, 8)  # noqa: E731
        return self.play(call, *answers)

    def test_the_vms_to_customize(self):
        # Une VM choisie pose quatre questions : son nom, son disque, sa
        # RAM et ses vCPU, une réponse vide gardant chacun.
        names, _ = self.customize("")
        self.assertEqual(names, ["forged-vm-a", "forged-vm-b"])
        self.assertEqual(len(self.asked), 1)
        names, _ = self.customize("2", "forged_new", "", "", "")
        self.assertEqual(names, ["forged-vm-a", "forged_new"])
        names, _ = self.customize("forged-vm-a", "forged_renamed", "", "", "")
        self.assertEqual(names, ["forged_renamed", "forged-vm-b"])
        self.customize("tout", *[""] * 8)
        self.assertEqual(len(self.asked), 9)
        wrong = ["tous", "1 x", "3"]
        self.assertIsNone(self.customize(*wrong, "0"))
        self.assertEqual(self.refused(), wrong)

    def test_the_development_tools(self):
        ask = lambda *answers: self.play(  # noqa: E731
            lambda: self.todo._qemu_ask_vm_tools([{}]), *answers
        )
        self.assertEqual(ask(""), ())
        self.assertEqual(ask("2"), ("forgejo",))
        self.assertEqual(ask("PyCharm"), ("pycharm",))
        self.assertEqual(ask("tout"), ("pycharm", "forgejo"))
        self.assertIn("PyCharm +3 Go, Forgejo +1 Go", self.shown)
        wrong = ["tous", "toutes", "1 9"]
        self.assertIsNone(ask(*wrong, "0"))
        self.assertEqual(self.refused(), wrong)
        # Coupé aux espaces, « Android Studio » ne se tape pas : son outil
        # se choisit par son numéro.
        self.todo._qemu_vm_tool_choices = lambda: [
            ("android", "Android Studio", "IDE")
        ]
        self.todo._QEMU_VM_TOOLS["android"] = {"disk_gb": 9}
        self.assertEqual(ask("Android Studio", "1"), ("android",))
        self.assertEqual(self.refused(), ["Android Studio"])

    def test_zero_at_either_list_deploys_nothing(self):
        todo = self.todo
        todo._qemu_prompt_infra_arch = lambda: "amd64"
        todo._qemu_arch_distros = lambda arch: None
        todo._qemu_stat_avg = lambda *a: ""
        todo._host_free_ram_mb = lambda: 8192
        todo._qemu_print_plan = lambda *a: self.fail("plan imprimé")
        # La distribution, sa version, les ressources, puis [0].
        got = self.play(
            lambda: todo._qemu_collect_vms_cli(MOD), "1", "1", "", "0"
        )
        self.assertIsNone(got)
        todo._qemu_default_ssh_key = lambda: "/forged/id_ed25519.pub"
        todo._qemu_ask_timezone = lambda: "UTC"
        todo._qemu_ask_locale = lambda: "C.UTF-8"
        todo._qemu_desktop_suffixes = lambda: {}
        todo._qemu_list_domains = lambda: self.fail("déploiement poursuivi")
        vms = [{"name": "forged-vm", "distro": "forged_a", "arch": "amd64"}]
        # La clé, un serveur, puis [0] aux outils.
        call = lambda: todo._qemu_collect_options_cli(vms, "x1")  # noqa: E731
        self.assertIsNone(self.play(call, "", "", "0"))
        self.assertEqual(len(self.asked), 3)
        self.assertNotIn(t("Cancelled."), self.shown)


if __name__ == "__main__":
    unittest.main()
