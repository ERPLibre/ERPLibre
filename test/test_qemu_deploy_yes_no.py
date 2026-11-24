#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""QEMU/KVM › Deploy VM(s) : les questions oui/non du déploiement, sous
les règles de `ui.confirm`.

Chaque question a son défaut, que l'indice du port dit dans la langue
choisie ; o, oui, y et yes y valent oui, une faute est dite et la question
revient, Ctrl+D vaut non. Le suivi interactif garde son défaut réel, oui.
La confirmation finale (`_confirm_or_discard`) repose la question sur un
non tant qu'on garde ses réponses, et finit sur une entrée fermée. Ctrl+D
à « garder le mot de passe dans la VM ? » renonce au déploiement et retire
le clair.

Rien ne part : sudo, `os.system`, `ssh-keygen` et les commandes de la
coupure sont des doubles qui notent. Un `ScriptedPort` répond aux questions
du port ; `input` ne lit que les questions texte.
"""

import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.qemu import cache_offline  # noqa: E402
from script.todo import qemu_deploy as qd  # noqa: E402
from script.todo import todo_i18n, ui  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402
from script.todo.ui.port import ScriptedPort  # noqa: E402

VM = "forged-yesno-vm"
SONDE = "forged-yesno-secret"
# Une réponse vide, une faute puis Ctrl+D, Ctrl+D.
VIDE, FAUTE, FIN = [""], ["peut-être", EOFError()], [EOFError()]
# Ce qui vaut non à une question dont le défaut est non.
REFUS = (VIDE, FAUTE, FIN, ["n"], ["non"])
# Ce qui vaut non à une question dont le défaut est oui.
REFUS_OUI = (FAUTE, FIN, ["n"], ["NON"], ["no"])
OUI = (["o"], ["oui"], ["y"], ["YES"])


class _Base(unittest.TestCase):
    def setUp(self):
        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("fr")
        self.todo = TODO.__new__(TODO)

    def play(self, call, answers, typed=()):
        """Ce que rend `call()` quand `answers` répondent, dans l'ordre, par
        un `ScriptedPort` (`self.port`) ; `typed` répond aux questions texte
        lues par `input`, qu'aucune autre question ne lit."""
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
        """(texte sans indice, défaut) de chaque question oui/non posée."""
        return [
            (event["prompt"], event["default"])
            for event in self.port.events
            if event.get("kind") == "confirm"
        ]

    def assert_read(self, answers):
        """Chaque réponse a été lue ; une faute a été dite."""
        self.assertEqual(self.port.answers, [])
        notices = [
            e["text"] for e in self.port.events if e.get("t") == "notice"
        ]
        if "peut-être" in answers:
            self.assertIn(f"{t('Answer yes or no: ')}peut-être", notices)


class TestLaConfirmationFinale(_Base):
    """`_confirm_or_discard` : « Déployer ? », oui par défaut ; sur un non,
    « Garder vos réponses et redemander ? », oui par défaut, repose la
    première question ; un non ou Ctrl+D y abandonne."""

    QUESTION = "Deploy these VMs now?"

    def confirm(self, answers):
        call = lambda: self.todo._confirm_or_discard(t(self.QUESTION))  # noqa: E731
        return self.play(call, answers)

    def test_a_closed_input_discards_and_ends(self):
        self.assertFalse(self.confirm([]))
        keep = t("Keep your answers and ask again?")
        self.assertEqual(self.asked(), [(t(self.QUESTION), "y"), (keep, "y")])

    def test_enter_or_a_yes_word_deploys(self):
        for answers in (VIDE, *OUI):
            with self.subTest(answers=answers):
                self.assertTrue(self.confirm(answers))
                self.assertEqual(len(self.asked()), 1)
                self.assert_read(answers)

    def test_no_then_enter_asks_again(self):
        self.assertTrue(self.confirm(["n", "", "o"]))
        first = (t(self.QUESTION), "y")
        self.assertEqual([self.asked()[0], self.asked()[2]], [first, first])
        self.assert_read([])

    def test_no_then_no_or_ctrl_d_discards(self):
        for answers in (["n", "n"], ["n", EOFError()], ["non", *FAUTE]):
            with self.subTest(answers=answers):
                self.assertFalse(self.confirm(answers))
                # Une faute repose la même question : une lecture chacune.
                self.assertEqual(len(self.asked()), len(answers))
                self.assert_read(answers)

    def test_the_question_carries_no_hint(self):
        self.confirm(["o"])
        event = self.port.events[0]
        self.assertTrue(event["text"].endswith(f"{t(self.QUESTION)} [O/n] : "))


class TestLeMotDePasseDansLaVM(_Base):
    """`_qemu_ask_vm_account` : « Garder le mot de passe dans la VM ? »,
    non par défaut, avec `back` : Ctrl+D y renonce au déploiement et retire
    le clair, y compris celui d'un déploiement précédent."""

    def account(self, answers):
        self.todo._qemu_vm_secret = SONDE
        return self.play(
            self.todo._qemu_ask_vm_account, ["", "", *answers, "de trop"]
        )

    def test_ctrl_d_goes_back_and_drops_the_secret(self):
        for answers in (FIN, FAUTE):
            with self.subTest(answers=answers):
                self.assertIsNone(self.account(answers))
                self.assertIsNone(self.todo._qemu_vm_secret)
                self.assertEqual(self.port.answers, ["de trop"])
                confirms = [
                    e for e in self.port.events if e.get("kind") == "confirm"
                ]
                self.assertTrue(confirms and all(e["back"] for e in confirms))

    def test_enter_or_no_keeps_it_out_of_the_vm(self):
        for answers in (VIDE, ["n"], ["non"]):
            with self.subTest(answers=answers):
                got = self.account(answers)
                self.assertEqual(got[1:], (True, False))
                self.assertEqual(
                    self.asked(), [(t("Keep the password in the VM?"), "n")]
                )

    def test_a_yes_word_keeps_it(self):
        for answers in OUI:
            with self.subTest(answers=answers):
                self.assertTrue(self.account(answers)[2])


class TestLesOptionsDuDeploiement(_Base):
    """`_qemu_collect_options_cli` : installer ERPLibre (oui), le suivi
    interactif (oui, son défaut réel), la 3D (non), le cache (non),
    ~/.ssh/config (oui), puis la confirmation finale (oui). Les autres
    étapes sont doublées ; rien n'est déployé."""

    def setUp(self):
        super().setUp()
        todo = self.todo
        todo._qemu_collect_guest_cli = lambda vms: {"vm_tools": ()}
        todo._qemu_install_questions = lambda distro: (
            "forged-branch",
            False,
            ("forged", "make forged"),
        )
        todo._qemu_cache_active = lambda: True
        todo._qemu_ask_ai_tools = lambda tools: ("", "", "")
        todo._qemu_ask_vm_account = lambda: ("forged", True, False)
        todo._qemu_list_domains = lambda: []
        todo._qemu_print_recap = lambda spec, existing: None
        todo._qemu_vm_secret = SONDE

    def collect(self, answers):
        vms = [{"name": VM, "distro": "debian", "arch": "amd64"}]
        call = lambda: self.todo._qemu_collect_options_cli(vms, "x1")  # noqa: E731
        return self.play(call, answers, typed=[""])

    def test_enter_takes_each_default(self):
        spec = self.collect([""] * 6)
        self.assertEqual(
            self.asked(),
            [
                (t("Install ERPLibre into ~/git/erplibre on each VM?"), "y"),
                (t("Interactive monitoring dashboard?"), "y"),
                (t("3D acceleration (host GPU), even without a screen?"), "n"),
                (t("Keep this VM out of the download cache?"), "n"),
                (t("Add each VM to ~/.ssh/config?"), "y"),
                (t("Deploy these VMs now?"), "y"),
            ],
        )
        self.assertEqual(spec["install"]["branch"], "forged-branch")
        self.assertTrue(spec["monitor"])
        self.assertTrue(spec["install"]["monitor"])
        self.assertFalse(spec["gpu3d"])
        self.assertFalse(spec["cache_bypass"])
        self.assertTrue(spec["add_ssh_config"])
        # L'indice du suivi interactif dit son défaut réel.
        self.assertTrue(self.port.events[1]["text"].endswith("[O/n] : "))

    def test_without_install_watching_is_asked_yes_by_default(self):
        spec = self.collect(["n", "", "", "", "", ""])
        self.assertIsNone(spec["install"])
        self.assertTrue(spec["monitor"])
        self.assertEqual(
            self.asked()[1], (t("Watch the VMs start (no install)?"), "y")
        )

    def test_each_no_is_read(self):
        for answers in (FAUTE, FIN, ["n"]):
            with self.subTest(answers=answers):
                # ERPLibre, suivi, 3D, cache, ~/.ssh/config, puis oui.
                spec = self.collect(
                    [*answers, *answers, "", "", *answers, "o"]
                )
                self.assertIsNone(spec["install"])
                self.assertFalse(spec["monitor"])
                self.assertFalse(spec["add_ssh_config"])
                self.assert_read(answers)

    def test_each_yes_word_is_read(self):
        for answers in OUI:
            with self.subTest(answers=answers):
                spec = self.collect(["", "", *answers, *answers, "", ""])
                self.assertTrue(spec["gpu3d"])
                self.assertTrue(spec["cache_bypass"])

    def test_refusing_the_deployment_drops_the_secret(self):
        for answers in (["n", "n"], ["n", EOFError()], [EOFError()]):
            with self.subTest(answers=answers):
                self.todo._qemu_vm_secret = SONDE
                self.assertIsNone(self.collect([""] * 5 + answers))
                self.assertIsNone(self.todo._qemu_vm_secret)


class TestLaCleSSH(_Base):
    """`_qemu_collect_guest_cli` sans clé publique : « En générer une
    maintenant ? », oui par défaut."""

    def setUp(self):
        super().setUp()
        todo = self.todo
        self.generated = []
        todo._qemu_default_ssh_key = lambda: None
        todo._ssh_ensure_key = lambda: self.generated.append(1) or None
        todo._qemu_ask_timezone = lambda: "UTC"
        todo._qemu_ask_locale = lambda: "C.UTF-8"
        todo._qemu_ask_desktop = lambda distros: None

    def guest(self, answers):
        call = lambda: self.todo._qemu_collect_guest_cli([])  # noqa: E731
        return self.play(call, answers, typed=[""])

    def test_enter_or_yes_generates_one(self):
        for answers in (VIDE, *OUI):
            with self.subTest(answers=answers):
                self.generated.clear()
                self.assertIsNone(self.guest(answers))
                self.assertEqual(self.generated, [1])
                self.assertEqual(self.asked(), [(t("Generate one now?"), "y")])

    def test_no_or_ctrl_d_generates_none(self):
        for answers in REFUS_OUI:
            with self.subTest(answers=answers):
                self.generated.clear()
                self.guest(answers)
                self.assertEqual(self.generated, [])
                self.assert_read(answers)


class TestLeGroupeLibvirt(_Base):
    """`_qemu_check_libvirt_group` : « L'exécuter maintenant ? », oui par
    défaut, avant `sudo usermod -aG libvirt` (un double qui note)."""

    def check(self, answers):
        self.ran = []
        probe = mock.Mock(returncode=1, stderr="")
        with (
            mock.patch.object(qd.subprocess, "run", return_value=probe),
            mock.patch.object(qd.grp, "getgrnam", side_effect=KeyError),
            mock.patch.object(qd.getpass, "getuser", return_value="forged"),
            mock.patch.object(
                qd.os, "system", lambda cmd: self.ran.append(cmd) or 0
            ),
        ):
            self.play(self.todo._qemu_check_libvirt_group, answers)

    def test_enter_or_yes_runs_it(self):
        for answers in (VIDE, *OUI):
            with self.subTest(answers=answers):
                self.check(answers)
                self.assertEqual(self.ran, ["sudo usermod -aG libvirt forged"])
                self.assertEqual(self.asked(), [(t("Run it now?"), "y")])

    def test_no_or_ctrl_d_runs_nothing(self):
        for answers in REFUS_OUI:
            with self.subTest(answers=answers):
                self.check(answers)
                self.assertEqual(self.ran, [])
                self.assert_read(answers)


class TestLesGardesDuDeploiement(_Base):
    """Disques orphelins gardés, noms en collision, coupure tenue par un
    autre déploiement, coupure restée seule : chaque question est non par
    défaut et ne laisse partir le déploiement que sur un oui."""

    def setUp(self):
        super().setUp()
        self.shell = []
        self.coupure = {}
        self.todo._qemu_shell = lambda cmd, timeout=60: (
            self.shell.append(cmd) or self.coupure.get(cmd, 1)
        )

    def each(self, call, question):
        """`call()` rend False à chaque refus, True à chaque oui, et pose
        `question`, non par défaut."""
        for answers in REFUS:
            with self.subTest(answers=answers):
                self.assertFalse(self.play(call, answers))
                self.assertEqual(set(self.asked()), {(t(question), "n")})
                self.assert_read(answers)
        for answers in OUI:
            with self.subTest(answers=answers):
                self.assertTrue(self.play(call, answers))

    def test_orphan_disks_kept(self):
        self.todo._qemu_orphan_disks = lambda names: [
            (VM, f"/var/lib/libvirt/images/{VM}.qcow2")
        ]
        self.todo._cleanup_delete_files = lambda *a: None
        call = lambda: self.todo._qemu_offer_orphan_removal([VM])  # noqa: E731
        self.each(call, "Continue anyway?")

    def test_name_collisions(self):
        self.todo._qemu_orphan_disks = lambda names: []
        call = lambda: self.todo._qemu_confirm_collisions([VM], [])  # noqa: E731
        self.each(call, "Continue despite these collisions?")

    def test_a_cut_held_by_another_deployment(self):
        self.coupure = {cache_offline.guet_actif_cmd(): 0}
        call = self.todo._qemu_en_ligne_malgre_la_coupure
        self.each(call, "Deploy anyway, offline?")

    def test_a_cut_left_alone_is_lifted_only_on_yes(self):
        self.coupure = {cache_offline.table_posee_cmd(): 0}
        restore = cache_offline.restore_cmd()
        for answers in REFUS:
            with self.subTest(answers=answers):
                self.shell.clear()
                self.assertFalse(
                    self.play(self.todo._qemu_coupure_libre, answers)
                )
                self.assertNotIn(restore, self.shell)
                self.assertEqual(
                    set(self.asked()), {(t("Lift it and continue?"), "n")}
                )
        for answers in OUI:
            with self.subTest(answers=answers):
                self.shell.clear()
                self.assertTrue(
                    self.play(self.todo._qemu_coupure_libre, answers)
                )
                self.assertIn(restore, self.shell)


if __name__ == "__main__":
    unittest.main()
