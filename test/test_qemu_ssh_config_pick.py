#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""QEMU/KVM › SSH configuration : les machines qu'une réponse désigne.

Le parcours qui suit le choix écrit une entrée ~/.ssh/config par machine
et s'y connecte en SSH sans autre question. Une réponse vide prend donc
toutes les VM, ou tous les hôtes de ~/.ssh/config ; une réponse qui n'en
désigne aucune (« 01 », « +1 », un nom absent) n'en prend aucune et le
dit, au lieu de se lire comme « toutes ».

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
    def test_a_rank_not_as_shown_picks_no_vm(self):
        for raw in ("01", "+1", "١", "forged_vm_z", "0", "9"):
            with self.subTest(raw=raw):
                self.assertNothingWritten(self._play("1", raw, ""))

    def test_a_rank_as_shown_picks_that_vm(self):
        self._play("1", "1", "")
        self.assertEqual(self.walks, [["forged_vm_a"]])

    def test_a_blank_answer_picks_every_vm(self):
        self._play("1", "", "")
        self.assertEqual(self.walks, [VMS])

    def test_the_picker_returns_what_the_answer_names(self):
        for raw, expected in (("01", []), ("1", VMS[:1]), ("", VMS)):
            with (
                self.subTest(raw=raw),
                mock.patch("builtins.input", lambda *a, r=raw: r),
                mock.patch("sys.stdout", io.StringIO()),
            ):
                self.assertEqual(self.todo._qemu_pick_domains(), expected)


class TestHostsOfSshConfig(_PickCase):
    def test_a_rank_not_as_shown_picks_no_host(self):
        for raw in ("01", "+1", "١", "forged_host_z", "0", "9"):
            with self.subTest(raw=raw):
                self.assertNothingWritten(self._play("2", raw, ""))

    def test_a_rank_as_shown_picks_that_host(self):
        self._play("2", "2", "")
        self.assertEqual(self.walks, [["forged_host_b"]])

    def test_a_blank_answer_picks_every_host(self):
        self._play("2", "", "")
        self.assertEqual(self.walks, [HOSTS])


if __name__ == "__main__":
    unittest.main()
