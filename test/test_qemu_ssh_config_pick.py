#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""QEMU/KVM › SSH configuration : les machines qu'une réponse désigne.

Le parcours qui suit le choix écrit une entrée ~/.ssh/config par machine
et s'y connecte en SSH sans autre question. Les VM et les hôtes se
choisissent donc sous les règles d'un choix multiple : un numéro tel que
la liste l'écrit, un nom, une plage ou `tout` ; une réponse vide ou [0]
n'en prend aucune et le dit, sans rien écrire ; une réponse invalide
(« 01 », « +1 », un nom absent) est nommée, et la question revient.

Les noms de VM et d'hôtes sont inventés. Le parcours est remplacé par un
enregistreur, et HOME pointe un répertoire jetable.
"""

import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

VMS = ["forged_vm_a", "forged_vm_b", "forged_vm_c"]
HOSTS = ["forged_host_a", "forged_host_b"]


class _PickCase(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.home = home.name
        env = mock.patch.dict(os.environ, {"HOME": self.home})
        env.start()
        self.addCleanup(env.stop)
        self.todo = TODO.__new__(TODO)
        self.todo._qemu_list_domains = lambda: list(VMS)
        self.todo._qemu_resolve_ips = lambda names, timeout=300: {
            name: f"forged-ip-{name}" for name in names
        }
        self.todo._ssh_config_hosts = lambda: list(HOSTS)
        self.todo._ssh_config_user = lambda host: ""
        self.walks = []
        self.todo._qemu_ssh_walk = lambda roots, depth: self.walks.append(
            [root["alias"] for root in roots]
        )

    def _play(self, *answers):
        it = iter(answers)
        out = io.StringIO()
        with (
            mock.patch("builtins.input", lambda *a: next(it)),
            mock.patch("sys.stdout", out),
        ):
            self.todo._qemu_ssh_config_menu()
        return out.getvalue()

    def assertNothingWritten(self, out):
        self.assertIn(t("Nothing selected."), out)
        self.assertEqual(self.walks, [])
        config = os.path.join(self.home, ".ssh", "config")
        self.assertFalse(os.path.exists(config))


class TestLocalVms(_PickCase):
    def test_a_rank_not_as_shown_is_named_and_asked_again(self):
        for raw in ("01", "+1", "١", "forged_vm_z", "9", "0 1"):
            with self.subTest(raw=raw):
                out = self._play("1", raw, "0")
                self.assertIn(f"{t('Invalid choice: ')}{raw}", out)
                self.assertNothingWritten(out)

    def test_a_rank_as_shown_picks_that_vm(self):
        self._play("1", "1", "")
        self.assertEqual(self.walks, [["forged_vm_a"]])

    def test_a_blank_answer_or_zero_picks_no_vm(self):
        # Une réponse vide ne prend aucune VM : chacune recevrait une entrée
        # ~/.ssh/config et une connexion SSH.
        for raw in ("", "0"):
            with self.subTest(raw=raw):
                self.assertNothingWritten(self._play("1", raw))

    def test_all_a_range_or_a_name_pick_those_vms(self):
        for raw, expected in (
            ("tout", VMS),
            ("*", VMS),
            ("2-3", VMS[1:]),
            ("forged_vm_c, 1", [VMS[0], VMS[2]]),
        ):
            with self.subTest(raw=raw):
                self.walks.clear()
                self._play("1", raw, "")
                self.assertEqual(self.walks, [expected])

    def test_the_picker_returns_what_the_answer_names(self):
        for answers, expected in (
            (["01", "0"], []),
            (["1"], VMS[:1]),
            ([""], []),
            (["all"], VMS),
        ):
            with (
                self.subTest(answers=answers),
                mock.patch("builtins.input", side_effect=answers),
                mock.patch("sys.stdout", io.StringIO()),
            ):
                self.assertEqual(self.todo._qemu_pick_domains(), expected)


class TestHostsOfSshConfig(_PickCase):
    def test_a_rank_not_as_shown_is_named_and_asked_again(self):
        for raw in ("01", "+1", "١", "forged_host_z", "9"):
            with self.subTest(raw=raw):
                out = self._play("2", raw, "0")
                self.assertIn(f"{t('Invalid choice: ')}{raw}", out)
                self.assertNothingWritten(out)

    def test_a_rank_as_shown_picks_that_host(self):
        self._play("2", "2", "")
        self.assertEqual(self.walks, [["forged_host_b"]])

    def test_a_blank_answer_or_zero_picks_no_host(self):
        # Une réponse vide ne prend aucun hôte de ~/.ssh/config.
        for raw in ("", "0"):
            with self.subTest(raw=raw):
                self.assertNothingWritten(self._play("2", raw))

    def test_all_or_a_name_pick_those_hosts(self):
        for raw, expected in (("tout", HOSTS), ("forged_host_b", HOSTS[1:])):
            with self.subTest(raw=raw):
                self.walks.clear()
                self._play("2", raw, "")
                self.assertEqual(self.walks, [expected])


class TestWhereTheMachinesComeFrom(_PickCase):
    def test_a_blank_answer_takes_the_local_vms_marked_as_default(self):
        out = self._play("", "1", "")
        self.assertEqual(self.walks, [["forged_vm_a"]])
        line = next(row for row in out.splitlines() if row.startswith("[1] "))
        self.assertIn(t("(default)"), line)

    def test_zero_or_an_invalid_answer_writes_nothing(self):
        # Une provenance hors de la liste est nommée, et [0] n'écrit rien.
        for answers in (["0"], ["4", "0"], ["x", "0"]):
            with self.subTest(answers=answers):
                out = self._play(*answers)
                for refused in answers[:-1]:
                    self.assertIn(f"{t('Invalid choice: ')}{refused}", out)
                self.assertEqual(self.walks, [])
                config = os.path.join(self.home, ".ssh", "config")
                self.assertFalse(os.path.exists(config))


if __name__ == "__main__":
    unittest.main()
