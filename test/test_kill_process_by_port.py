#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import unittest
from unittest.mock import MagicMock, patch

import psutil

from script.process import kill_process_by_port as kpp
from script.process.kill_process_by_port import (
    PROTECTED_NAMES,
    WRAPPER_SCRIPT_NAMES,
    ask_target,
    choose_target,
    find_listeners,
    get_ancestry,
    kill_process,
    kill_tree,
    proc_desc,
)


def _make_proc(pid, name="python", cmdline=None, username="user"):
    """Create a mock psutil.Process."""
    p = MagicMock(spec=psutil.Process)
    p.pid = pid
    p.name.return_value = name
    p.cmdline.return_value = cmdline or [name]
    p.username.return_value = username
    return p


class TestProcDesc(unittest.TestCase):
    def test_normal_process(self):
        p = _make_proc(123, "python", ["python", "app.py"])
        result = proc_desc(p)
        self.assertIn("pid=123", result)
        self.assertIn("python app.py", result)
        self.assertIn("user=user", result)

    def test_empty_cmdline_uses_name(self):
        p = _make_proc(42, "bash", [])
        result = proc_desc(p)
        self.assertIn("pid=42", result)
        self.assertIn("name=bash", result)

    def test_psutil_error_fallback(self):
        p = MagicMock(spec=psutil.Process)
        p.pid = 99
        p.cmdline.side_effect = psutil.Error("gone")
        result = proc_desc(p)
        self.assertEqual(result, "pid=99")


class TestGetAncestry(unittest.TestCase):
    @patch("script.process.kill_process_by_port.psutil.Process")
    def test_nonexistent_pid(self, mock_proc_cls):
        mock_proc_cls.side_effect = psutil.NoSuchProcess(99999)
        chain = get_ancestry(99999)
        self.assertEqual(chain, [])

    @patch("script.process.kill_process_by_port.psutil.Process")
    def test_chain_stops_at_pid_1(self, mock_proc_cls):
        p_child = MagicMock()
        p_child.pid = 100
        p_child.ppid.return_value = 1

        p_init = MagicMock()
        p_init.pid = 1

        mock_proc_cls.side_effect = [p_child, p_init]
        chain = get_ancestry(100)
        self.assertEqual(len(chain), 2)
        self.assertEqual(chain[0].pid, 100)
        self.assertEqual(chain[1].pid, 1)

    @patch("script.process.kill_process_by_port.psutil.Process")
    def test_chain_stops_at_ppid_zero(self, mock_proc_cls):
        p = MagicMock()
        p.pid = 50
        p.ppid.return_value = 0

        mock_proc_cls.return_value = p
        chain = get_ancestry(50)
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0].pid, 50)


class TestChooseTarget(unittest.TestCase):
    def test_empty_chain_returns_none(self):
        result = choose_target([], 1)
        self.assertIsNone(result)

    def test_stops_at_run_sh(self):
        p1 = _make_proc(100, "python", ["python", "odoo-bin"])
        p2 = _make_proc(99, "bash", ["./run.sh"])
        p3 = _make_proc(1, "systemd", ["systemd"])
        chain = [p1, p2, p3]
        target, lst = choose_target(chain, 1)
        self.assertEqual(target.pid, 99)

    def test_stops_at_odoo_bin_sh(self):
        p1 = _make_proc(200, "python", ["python", "odoo-bin"])
        p2 = _make_proc(199, "bash", ["./odoo_bin.sh"])
        chain = [p1, p2]
        target, lst = choose_target(chain, 1)
        self.assertEqual(target.pid, 199)

    def test_nb_parent_counts_parents_above_the_listener(self):
        p1 = _make_proc(300, "python", ["python"])
        p2 = _make_proc(299, "bash", ["bash"])
        p3 = _make_proc(1, "systemd", ["systemd"])
        chain = [p1, p2, p3]
        self.assertEqual(choose_target(chain, 0)[0].pid, 300)
        self.assertEqual(choose_target(chain, 1)[0].pid, 299)

    def test_nb_parent_never_goes_past_a_protected_process(self):
        """Le cas qui ne tuait rien : un Odoo orphelin, dont le seul parent
        est systemd, et un nb_parent qui visait ce parent."""
        odoo = _make_proc(470, "python", ["python", "./odoo/odoo-bin"])
        chain = [odoo, _make_proc(1, "systemd", ["systemd"])]
        self.assertEqual(choose_target(chain, 5)[0].pid, 470)


def _chaine(*specs):
    return [_make_proc(pid, nom, cmd) for pid, nom, cmd in specs]


ODOO = (500, "python", ["python", "./odoo18.0/odoo/odoo-bin", "-c", "c"])
SYSTEMD = (1, "systemd", ["/usr/lib/systemd/systemd"])


class TestLaCibleReconnue(unittest.TestCase):
    """Sans nb_parent : le plus haut ancêtre qui fait partie de
    l'exécution d'Odoo, et jamais au-delà."""

    def test_an_orphan_odoo_is_its_own_target(self):
        chain = _chaine(ODOO, SYSTEMD)
        self.assertEqual(choose_target(chain)[0].pid, 500)

    def test_run_sh_is_the_target_and_the_shell_above_is_spared(self):
        chain = _chaine(
            ODOO,
            (499, "bash", ["/bin/bash", "./odoo_bin.sh", "-c", "c"]),
            (498, "bash", ["/bin/bash", "./run.sh"]),
            (497, "bash", ["-bash"]),
            (496, "gnome-terminal-server", ["gnome-terminal-server"]),
            SYSTEMD,
        )
        target, ancetres = choose_target(chain)
        self.assertEqual(target.pid, 498)
        self.assertEqual([p.pid for p in ancetres], [500, 499, 498])

    def test_run_sh_by_absolute_path_is_recognized(self):
        chain = _chaine(
            ODOO, (499, "bash", ["bash", "/opt/erplibre/run.sh"]), SYSTEMD
        )
        self.assertEqual(choose_target(chain)[0].pid, 499)

    def test_an_ide_above_odoo_is_never_the_target(self):
        chain = _chaine(ODOO, (400, "java", ["java", "-jar", "ide.jar"]))
        self.assertEqual(choose_target(chain)[0].pid, 500)

    def test_an_unrecognized_listener_stays_the_target_to_confirm(self):
        chain = _chaine((600, "python", ["python", "serveur.py"]), SYSTEMD)
        target, _ = choose_target(chain)
        self.assertEqual(target.pid, 600)
        self.assertFalse(kpp.is_odoo_execution(target))

    def test_a_protected_listener_is_reported_as_such(self):
        chain = _chaine((22, "sshd", ["sshd"]), SYSTEMD)
        self.assertTrue(kpp.is_protected(choose_target(chain)[0]))


class TestLaQuestion(unittest.TestCase):
    def test_enter_keeps_the_default(self):
        chain = _chaine(ODOO, SYSTEMD)
        with patch("builtins.input", return_value=""):
            self.assertEqual(ask_target(chain, chain[0]).pid, 500)

    def test_a_protected_index_is_refused_and_asked_again(self):
        chain = _chaine(ODOO, SYSTEMD)
        with (
            patch("builtins.input", side_effect=["1", "0"]),
            patch("builtins.print"),
        ):
            self.assertEqual(ask_target(chain, chain[0]).pid, 500)

    def test_c_cancels(self):
        chain = _chaine(ODOO, SYSTEMD)
        with patch("builtins.input", return_value="c"):
            self.assertIsNone(ask_target(chain, chain[0]))


class TestLeDeroule(unittest.TestCase):
    """main() de bout en bout, les processus et le port simulés."""

    def lancer(self, chain, reponses, liberes):
        tues = []
        ecoute = iter(liberes)
        with (
            patch("sys.argv", ["kill", "8069", "--kill-tree"]),
            patch.object(
                kpp, "find_listeners", side_effect=lambda port: next(ecoute)
            ),
            patch.object(kpp, "get_ancestry", return_value=chain),
            patch.object(
                kpp,
                "kill_tree",
                side_effect=lambda p, force: tues.append((p.pid, force)) or [],
            ),
            patch.object(kpp, "GRACE_SECONDS", 0),
            patch("builtins.input", side_effect=reponses),
            patch("builtins.print"),
        ):
            code = kpp.main()
        return code, tues

    def test_an_orphan_odoo_is_stopped(self):
        chain = _chaine(ODOO, SYSTEMD)
        # écouteurs : au départ, puis libre
        code, tues = self.lancer(chain, [""], [[500], []])
        self.assertEqual((code, tues), (0, [(500, False)]))

    def test_a_port_still_held_offers_sigkill_on_odoo_only(self):
        chain = _chaine(ODOO, SYSTEMD)
        # écouteurs : départ, attente (tenu), avant SIGKILL, attente (libre)
        code, tues = self.lancer(chain, ["", "o"], [[500], [500], [500], []])
        self.assertEqual(code, 0)
        self.assertEqual(tues, [(500, False), (500, True)])


class TestKillProcess(unittest.TestCase):
    def test_terminate_called(self):
        p = _make_proc(10)
        kill_process(p, force=False)
        p.terminate.assert_called_once()
        p.kill.assert_not_called()

    def test_kill_called_with_force(self):
        p = _make_proc(10)
        kill_process(p, force=True)
        p.kill.assert_called_once()
        p.terminate.assert_not_called()


class TestKillTree(unittest.TestCase):
    @patch("script.process.kill_process_by_port.psutil.wait_procs")
    def test_kills_children_then_root(self, mock_wait):
        root = _make_proc(10, "root_proc")
        child1 = _make_proc(11, "child1")
        child2 = _make_proc(12, "child2")
        root.children.return_value = [child1, child2]
        mock_wait.return_value = (
            [root, child1, child2],
            [],
        )

        alive = kill_tree(root, force=False)
        child1.terminate.assert_called_once()
        child2.terminate.assert_called_once()
        root.terminate.assert_called_once()
        self.assertEqual(alive, [])

    @patch("script.process.kill_process_by_port.psutil.wait_procs")
    def test_returns_alive_processes(self, mock_wait):
        root = _make_proc(10)
        root.children.return_value = []
        mock_wait.return_value = ([], [root])

        alive = kill_tree(root, force=True)
        self.assertEqual(len(alive), 1)

    @patch("script.process.kill_process_by_port.psutil.wait_procs")
    def test_handles_psutil_error_on_child(self, mock_wait):
        root = _make_proc(10)
        child = _make_proc(11)
        child.terminate.side_effect = psutil.NoSuchProcess(11)
        root.children.return_value = [child]
        mock_wait.return_value = ([root], [])

        alive = kill_tree(root, force=False)
        self.assertEqual(alive, [])


class TestFindListeners(unittest.TestCase):
    @patch("script.process.kill_process_by_port.psutil.net_connections")
    def test_finds_listening_pid(self, mock_conns):
        conn = MagicMock()
        conn.laddr = MagicMock()
        conn.laddr.port = 8069
        conn.status = psutil.CONN_LISTEN
        conn.pid = 1234
        mock_conns.return_value = [conn]

        result = find_listeners(8069)
        self.assertEqual(result, [1234])

    @patch("script.process.kill_process_by_port.psutil.net_connections")
    def test_ignores_different_port(self, mock_conns):
        conn = MagicMock()
        conn.laddr = MagicMock()
        conn.laddr.port = 9999
        conn.status = psutil.CONN_LISTEN
        conn.pid = 1234
        mock_conns.return_value = [conn]

        result = find_listeners(8069)
        self.assertEqual(result, [])

    @patch("script.process.kill_process_by_port.psutil.net_connections")
    def test_ignores_non_listen_status(self, mock_conns):
        conn = MagicMock()
        conn.laddr = MagicMock()
        conn.laddr.port = 8069
        conn.status = psutil.CONN_ESTABLISHED
        conn.pid = 1234
        mock_conns.return_value = [conn]

        result = find_listeners(8069)
        self.assertEqual(result, [])

    @patch("script.process.kill_process_by_port.psutil.net_connections")
    def test_no_connections(self, mock_conns):
        mock_conns.return_value = []
        result = find_listeners(8069)
        self.assertEqual(result, [])

    @patch("script.process.kill_process_by_port.psutil.net_connections")
    def test_deduplicates_pids(self, mock_conns):
        conn1 = MagicMock()
        conn1.laddr = MagicMock()
        conn1.laddr.port = 8069
        conn1.status = psutil.CONN_LISTEN
        conn1.pid = 100
        conn2 = MagicMock()
        conn2.laddr = MagicMock()
        conn2.laddr.port = 8069
        conn2.status = psutil.CONN_LISTEN
        conn2.pid = 100
        mock_conns.return_value = [conn1, conn2]

        result = find_listeners(8069)
        self.assertEqual(result, [100])


class TestProtectedNames(unittest.TestCase):
    def test_systemd_is_protected(self):
        self.assertIn("systemd", PROTECTED_NAMES)

    def test_gnome_shell_is_protected(self):
        self.assertIn("gnome-shell", PROTECTED_NAMES)

    def test_sshd_is_protected(self):
        self.assertIn("sshd", PROTECTED_NAMES)


class TestStopParentKill(unittest.TestCase):
    def test_contains_run_sh(self):
        self.assertIn("./run.sh", WRAPPER_SCRIPT_NAMES)

    def test_contains_odoo_bin_sh(self):
        self.assertIn("./odoo_bin.sh", WRAPPER_SCRIPT_NAMES)


if __name__ == "__main__":
    unittest.main()
