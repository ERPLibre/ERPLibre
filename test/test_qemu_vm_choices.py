#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""QEMU/KVM : les listes qui changent l'état d'une VM, l'effacent, ou
rouvrent un suivi, sous les règles des choix.

Changer l'état et Effacer des VM lancent virsh après leurs confirmations :
une réponse vide, [0], Ctrl+D ou une faute n'en lancent aucun et ne posent
pas la confirmation ; `tout` y mène, et seules ses réponses oui agissent.
Chaque liste de réponses finit par une réponse acceptée ou « 0 » : une
réponse invalide repose la question.

Les VM, les suivis et les navigateurs sont inventés ; virsh n'est jamais
lancé, `execute` note chaque commande.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

VMS = ["forged_vm_a", "forged_vm_b"]


class _Execute:
    """Note chaque commande, sans rien lancer ; un démarrage rend le
    couple (code, lignes) que son appelant attend."""

    def __init__(self):
        self.cmds = []

    def exec_command_live(self, cmd, **opts):
        self.cmds.append(cmd)
        return (0, []) if opts.get("return_status_and_output") else 0


class _Cas(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.todo.execute = _Execute()
        self.todo._qemu_list_domains = lambda: list(VMS)
        self.todo._qemu_list_vms = lambda *a, **k: None
        self.todo._qemu_adjust_hardware = lambda names: self.fail(
            "matériel ouvert"
        )

    def play(self, method, *answers):
        """(ce que rend la méthode, ce qu'elle imprime) quand elle reçoit
        `answers` ; les invites d'`input` vont dans `self.asked`."""
        out = io.StringIO()
        with (
            mock.patch("builtins.input", side_effect=answers) as asked,
            mock.patch(
                "script.todo.qemu_manage.bypass_menage", return_value=0
            ),
            redirect_stdout(out),
        ):
            got = getattr(self.todo, method)()
        self.asked = [call.args[0] for call in asked.call_args_list]
        return got, out.getvalue()

    def virsh(self):
        return [cmd for cmd in self.todo.execute.cmds if "virsh" in cmd]


class TestChangerLEtat(_Cas):
    def test_nothing_starts_or_stops_without_a_choice_and_both_yes(self):
        for answers, refused in (
            ([""], []),
            (["0"], []),
            (["01", "forged_vm_z", "0"], ["01", "forged_vm_z"]),
            (["tout", "0"], []),
            (["tout", "4", "0"], ["4"]),
            (["tout", "2", "n"], []),
            (["tout", "2", "o", "n"], []),
        ):
            with self.subTest(answers=answers):
                self.todo.execute.cmds.clear()
                _, out = self.play("_qemu_change_state", *answers)
                self.assertEqual(self.virsh(), [])
                for answer in refused:
                    self.assertIn(f"{t('Invalid choice: ')}{answer}", out)
                # La confirmation nomme les deux VM avant son premier oui.
                if answers[-1] == "n":
                    self.assertIn(
                        "forged_vm_a, forged_vm_b",
                        [p for p in self.asked if t("Apply:") in p][0],
                    )

    def test_a_name_or_all_picks_the_vms_to_stop(self):
        self.play("_qemu_change_state", "forged_vm_b", "2", "o", "o")
        self.assertEqual(len(self.virsh()), 1)
        self.assertTrue(self.virsh()[0].endswith("shutdown forged_vm_b"))
        self.todo.execute.cmds.clear()
        self.play("_qemu_change_state", "tout", "2", "o", "o")
        self.assertEqual(len(self.virsh()), 2)

    def test_ctrl_d_at_either_list_changes_nothing(self):
        # Ctrl+D aux VM ou à l'état cible revient sans rien lancer ni
        # demander de confirmation.
        for answers in ([EOFError], ["tout", EOFError]):
            with self.subTest(answers=answers):
                self.todo.execute.cmds.clear()
                self.play("_qemu_change_state", *answers)
                self.assertEqual(self.virsh(), [])
                self.assertEqual(len(self.asked), len(answers))

    def test_nothing_selected_answers_only_an_empty_answer(self):
        # [0] et Ctrl+D reviennent sans un mot.
        for answers, said in (
            ([""], True),
            (["0"], False),
            ([EOFError], False),
        ):
            with self.subTest(answers=answers):
                _, out = self.play("_qemu_change_state", *answers)
                self.assertEqual(t("Nothing selected.") in out, said)

    def test_starting_asks_for_the_hardware_then_both_confirmations(self):
        # [1] Ouvrir pose une question de plus, le matériel, avant les deux
        # confirmations ; seules leurs deux réponses oui démarrent la VM.
        adjusted = []
        self.todo._qemu_adjust_hardware = adjusted.append
        for answers, hardware, started in (
            (["1", "1", "n", "n"], [], []),
            (["1", "1", "n", "o", "n"], [], []),
            (["1", "1", "o", "n"], [["forged_vm_a"]], []),
            (["forged_vm_b", "1", "n", "o", "o"], [], ["forged_vm_b"]),
        ):
            with self.subTest(answers=answers):
                adjusted.clear()
                self.todo.execute.cmds.clear()
                self.play("_qemu_change_state", *answers)
                self.assertIn(
                    t("Adjust hardware before starting? (y/N): "),
                    self.asked[2],
                )
                self.assertEqual(adjusted, hardware)
                self.assertEqual(
                    [cmd.rsplit(" ", 1)[1] for cmd in self.virsh()], started
                )
                for cmd in self.virsh():
                    self.assertIn(" start ", cmd)


class TestEffacerDesVm(_Cas):
    def test_nothing_is_deleted_without_a_choice_and_its_yes(self):
        for answers, refused in (
            ([""], []),
            (["0"], []),
            (["x", "1-3", "0"], ["x", "1-3"]),
            (["tout", "n", "n"], []),
        ):
            with self.subTest(answers=answers):
                self.todo.execute.cmds.clear()
                _, out = self.play("_qemu_delete_vm", *answers)
                self.assertEqual(self.virsh(), [])
                for answer in refused:
                    self.assertIn(f"{t('Invalid choice: ')}{answer}", out)
                if answers[0] == "tout":
                    self.assertIn(
                        f"{t('Will delete:')} forged_vm_a, forged_vm_b", out
                    )

    def test_only_the_chosen_vm_is_deleted(self):
        self.play("_qemu_delete_vm", "2", "n", "o")
        self.assertEqual(len(self.virsh()), 1)
        self.assertIn("undefine forged_vm_b", self.virsh()[0])
        self.assertNotIn("forged_vm_a", self.virsh()[0])

    def test_a_blank_zero_or_ctrl_d_deletes_nothing(self):
        # Aucun ne pose la question des disques ; une réponse vide dit
        # qu'aucune VM n'est choisie, [0] et Ctrl+D reviennent sans un mot.
        for answers, said in (
            ([""], True),
            (["0"], False),
            ([EOFError], False),
        ):
            with self.subTest(answers=answers):
                self.todo.execute.cmds.clear()
                _, out = self.play("_qemu_delete_vm", *answers)
                self.assertEqual(self.virsh(), [])
                self.assertEqual(len(self.asked), 1)
                self.assertEqual(t("Nothing selected.") in out, said)


class TestLaListeDesVm(_Cas):
    def test_the_list_offers_two_ways_and_back(self):
        vus = []
        self.todo._qemu_list_vms_advanced = lambda: vus.append("advanced")
        self.todo._qemu_change_state = lambda: vus.append("state")
        del self.todo._qemu_list_vms
        self.todo._qemu_list_domains = lambda: list(VMS)
        for answers, expected in (
            ([""], []),
            (["0"], []),
            ([EOFError], []),
            (["3", "1"], ["advanced"]),
            (["2"], ["state"]),
        ):
            with self.subTest(answers=answers):
                vus.clear()
                out = io.StringIO()
                with (
                    mock.patch("builtins.input", side_effect=answers),
                    redirect_stdout(out),
                ):
                    self.todo._qemu_list_vms(ask_advanced=True)
                self.assertEqual(vus, expected)
                # Un numéro hors de la liste est nommé, et la question
                # revient.
                self.assertEqual(
                    f"{t('Invalid choice: ')}3" in out.getvalue(),
                    "3" in answers,
                )


RUNS = [
    {"label": "forged run 2", "vms": [{"name": "a"}], "manifest": "m2"},
    {"label": "forged run 1", "vms": [{"name": "b"}], "manifest": "m1"},
]


class TestLesSuivis(_Cas):
    def setUp(self):
        super().setUp()
        self.opened = []
        self.todo._qemu_open_monitor = self.opened.append

    def test_a_past_run_reopens_by_number_the_last_by_default(self):
        for answers, expected in (
            ([""], ["m2"]),
            (["2"], ["m1"]),
            (["3", "0"], []),
        ):
            with self.subTest(answers=answers):
                self.opened.clear()
                with mock.patch(
                    "script.todo.qemu_install_monitor.list_install_runs",
                    return_value=RUNS,
                ):
                    _, out = self.play("_qemu_reopen_monitor", *answers)
                self.assertEqual(self.opened, expected)
        self.assertIn(f"{t('Invalid choice: ')}3", out)

    def test_a_running_install_reopens_deploys_or_goes_back(self):
        run = dict(RUNS[0], active=1, total=1, idle=None)
        for answers, expected, opened in (
            ([""], True, ["m2"]),
            (["2"], False, []),
            (["0"], True, []),
            (["x", "2"], False, []),
        ):
            with self.subTest(answers=answers):
                self.opened.clear()
                with mock.patch(
                    "script.todo.qemu_install_monitor.active_run",
                    return_value=run,
                ):
                    got, _ = self.play("_qemu_active_install", *answers)
                self.assertEqual((got, self.opened), (expected, opened))


class TestLeNavigateur(_Cas):
    def test_an_installed_browser_by_number_or_name_or_i_to_install(self):
        self.todo._qemu_install_cli_browser = lambda: "forged_installed"
        for answers, expected in (
            ([""], "w3m"),
            (["lynx"], "lynx"),
            (["I"], "forged_installed"),
            (["9", "0"], None),
        ):
            with (
                self.subTest(answers=answers),
                mock.patch(
                    "script.todo.qemu_manage.shutil.which",
                    lambda b: b in ("w3m", "lynx") and f"/bin/{b}",
                ),
            ):
                got, _ = self.play("_qemu_choose_cli_browser", *answers)
            self.assertEqual(got, expected)

    def test_the_browser_to_install_is_asked_before_any_command(self):
        asked = []
        for answers, expected in (
            ([""], ["w3m"]),
            (["2"], ["lynx"]),
            (["links"], ["links"]),
            (["x", "0"], []),
        ):
            with (
                self.subTest(answers=answers),
                mock.patch(
                    "script.todo.qemu_install_monitor.browser_install_command",
                    lambda b: asked.append(b),
                ),
            ):
                asked.clear()
                got, _ = self.play("_qemu_install_cli_browser", *answers)
            self.assertEqual((got, asked), (None, expected))


if __name__ == "__main__":
    unittest.main()
