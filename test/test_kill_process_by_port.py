#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import io
import unittest
from unittest.mock import MagicMock, patch

import psutil

from script.process import kill_process_by_port as kpp
from script.process.kill_process_by_port import (
    PROTECTED_NAMES,
    ask_target,
    choose_target,
    executed_program,
    find_listeners,
    get_ancestry,
    kill_process,
    proc_desc,
    service_of_cgroup,
    stop_procs,
    tree_of,
)


def _make_proc(pid, name="python", cmdline=None, username="user"):
    """Create a mock psutil.Process."""
    p = MagicMock(spec=psutil.Process)
    p.pid = pid
    p.name.return_value = name
    p.cmdline.return_value = cmdline or [name]
    p.username.return_value = username
    p.children.return_value = []
    p.is_running.return_value = True
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
        p3 = _make_proc(98, "bash", ["-bash"])
        p4 = _make_proc(1, "systemd", ["systemd"])
        chain = [p1, p2, p3, p4]
        target, lst = choose_target(chain)
        self.assertEqual(target.pid, 99)
        self.assertEqual([p.pid for p in lst], [100, 99])

    def test_stops_at_odoo_bin_sh(self):
        p1 = _make_proc(200, "python", ["python", "odoo-bin"])
        p2 = _make_proc(199, "bash", ["/bin/bash", "./odoo_bin.sh", "-c"])
        p3 = _make_proc(198, "make", ["make", "run"])
        chain = [p1, p2, p3]
        target, lst = choose_target(chain)
        self.assertEqual(target.pid, 199)

    def test_nb_parent_counts_parents_above_the_listener(self):
        p1 = _make_proc(300, "python", ["python"])
        p2 = _make_proc(299, "bash", ["bash"])
        p3 = _make_proc(1, "systemd", ["systemd"])
        chain = [p1, p2, p3]
        self.assertEqual(choose_target(chain, 0)[0].pid, 300)
        self.assertEqual(choose_target(chain, 1)[0].pid, 299)

    def test_nb_parent_never_goes_past_a_protected_process(self):
        """Un nb_parent qui vise au-delà d'un Odoo orphelin, dont le seul
        parent est systemd, s'arrête sur Odoo lui-même."""
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

    def test_a_launcher_naming_run_sh_in_its_arguments_is_spared(self):
        chain = _chaine(
            ODOO,
            (499, "bash", ["bash", "./run.sh"]),
            (498, "fake_term", ["fake_term", "./run.sh", "8069"]),
            SYSTEMD,
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


class TestLeProgrammeExecute(unittest.TestCase):
    """Le programme est argv[0], ou ce qu'exécute un interpréteur."""

    def test_argv0_by_its_basename(self):
        self.assertEqual(executed_program(["./run.sh", "-x"]), "run.sh")
        self.assertEqual(executed_program(["/venv/bin/odoo"]), "odoo")

    def test_the_script_after_a_shell_and_its_options(self):
        self.assertEqual(
            executed_program(["/bin/bash", "-e", "./odoo_bin.sh", "-c"]),
            "odoo_bin.sh",
        )

    def test_the_script_after_python_and_its_options(self):
        args = ["python3.12", "-W", "ignore", "-u", "./odoo/odoo-bin", "-c"]
        self.assertEqual(executed_program(args), "odoo-bin")

    def test_python_m_odoo(self):
        self.assertEqual(executed_program(["python3", "-m", "odoo"]), "odoo")

    def test_coverage_run(self):
        args = ["/venv/bin/python", "/venv/bin/coverage", "run", "-p"]
        args += ["./odoo/odoo-bin", "-c", "c"]
        self.assertEqual(executed_program(args), "odoo-bin")
        args = ["python", "-m", "coverage", "run", "--rcfile", "r", "x/odoo"]
        self.assertEqual(executed_program(args), "odoo")

    def test_debugpy_options_with_a_value(self):
        args = ["python", "-m", "debugpy", "--listen", "5678", "odoo-bin"]
        self.assertEqual(executed_program(args), "odoo-bin")

    def test_arguments_of_the_program_are_not_read(self):
        self.assertEqual(
            executed_program(["fake_term", "./run.sh", "8069"]), "fake_term"
        )
        self.assertEqual(
            executed_program(["python", "serve.py", "odoo-bin"]), "serve.py"
        )

    def test_inline_code_and_empty_line(self):
        self.assertIsNone(executed_program(["bash", "-c", "./run.sh"]))
        self.assertIsNone(executed_program([]))


class TestLeServiceSystemd(unittest.TestCase):
    def test_a_system_service_v2(self):
        text = "0::/system.slice/odoo18.service\n"
        self.assertEqual(service_of_cgroup(text), ("odoo18.service", False))

    def test_a_system_service_v1(self):
        text = "12:cpu:/\n1:name=systemd:/system.slice/odoo.service\n"
        self.assertEqual(service_of_cgroup(text), ("odoo.service", False))

    def test_a_user_service(self):
        text = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/o.service"
        self.assertEqual(service_of_cgroup(text), ("o.service", True))

    def test_a_terminal_or_ssh_session_is_not_a_service(self):
        for text in (
            "0::/user.slice/user-1000.slice/session-3.scope",
            "0::/user.slice/user-1000.slice/user@1000.service/app.slice/"
            "app-org.gnome.Terminal.slice/vte-spawn-1.scope",
            "0::/user.slice/user-1000.slice/user@1000.service/"
            "gnome-terminal-server.service",
            "0::/user.slice/user-1000.slice/user@1000.service",
            "",
        ):
            self.assertIsNone(service_of_cgroup(text), text)


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


RUN_SH = (498, "bash", ["/bin/bash", "./run.sh"])
ODOO_BIN_SH = (499, "bash", ["/bin/bash", "./odoo_bin.sh", "-c", "c"])
SHELL = (497, "bash", ["-bash"])


class TestLeDeroule(unittest.TestCase):
    """main() de bout en bout, les processus et le port simulés."""

    def lancer(self, chain, reponses, liberes, options=(), service=None):
        """Lance main() ; rend (code, signaux, texte affiché). Chaque signal
        est (pids signalés, force). `liberes` donne les écouteurs à chaque
        appel de find_listeners."""
        signaux = []
        ecoute = iter(liberes)
        lignes = []

        def stop(procs, force):
            signaux.append(([p.pid for p in procs], force))
            return [], []

        def imprime(*a, **_k):
            lignes.append(" ".join(str(x) for x in a))

        with (
            patch("sys.argv", ["kill", "8069", *options]),
            patch.object(
                kpp, "find_listeners", side_effect=lambda port: next(ecoute)
            ),
            patch.object(kpp, "get_ancestry", return_value=chain),
            patch.object(kpp, "stop_procs", side_effect=stop),
            patch.object(kpp, "systemd_service", return_value=service),
            patch.object(kpp, "GRACE_SECONDS", 0),
            patch("builtins.input", side_effect=reponses),
            patch("builtins.print", side_effect=imprime),
        ):
            code = kpp.main()
        return code, signaux, "\n".join(lignes)

    def test_an_orphan_odoo_is_stopped(self):
        chain = _chaine(ODOO, SYSTEMD)
        # écouteurs : au départ, puis libre
        code, signaux, _ = self.lancer(chain, [""], [[500], []])
        self.assertEqual((code, signaux), (0, [([500], False)]))

    def test_kill_tree_adds_the_children_of_the_listener(self):
        chain = _chaine(ODOO, SYSTEMD)
        chain[0].children.return_value = [_make_proc(501), _make_proc(502)]
        code, signaux, _ = self.lancer(
            chain, [""], [[500], []], options=["--kill-tree"]
        )
        self.assertEqual(signaux, [([501, 502, 500], False)])

    def test_a_wrapper_target_is_stopped_with_its_tree_without_kill_tree(self):
        chain = _chaine(ODOO, ODOO_BIN_SH, RUN_SH, SHELL, SYSTEMD)
        chain[2].children.return_value = [chain[1], chain[0]]
        code, signaux, _ = self.lancer(chain, [""], [[500], []])
        self.assertEqual((code, signaux), (0, [([499, 500, 498], False)]))

    def test_a_systemd_service_is_refused_with_the_hint(self):
        chain = _chaine(ODOO, RUN_SH, SYSTEMD)
        code, signaux, texte = self.lancer(
            chain, [], [[500]], service=("odoo.service", True)
        )
        self.assertEqual((code, signaux), (0, []))
        self.assertIn("If this unit is the Odoo service", texte)
        self.assertIn("systemctl --user stop odoo.service", texte)

    def test_access_denied_is_reported(self):
        chain = _chaine(ODOO, SYSTEMD)
        chain[0].terminate.side_effect = psutil.AccessDenied(500)
        with (
            patch("sys.argv", ["kill", "8069", "--automatic"]),
            patch.object(kpp, "find_listeners", side_effect=[[500], []]),
            patch.object(kpp, "get_ancestry", return_value=chain),
            patch.object(kpp, "systemd_service", return_value=None),
            patch.object(kpp, "GRACE_SECONDS", 0),
            patch.object(kpp.psutil, "wait_procs", return_value=([], [])),
            patch("sys.stderr", new_callable=io.StringIO) as err,
            patch("sys.stdout", new_callable=io.StringIO) as out,
        ):
            self.assertEqual(kpp.main(), 0)
        self.assertIn("AccessDenied: pid=500", err.getvalue())
        self.assertNotIn("Still running", out.getvalue())

    def test_a_port_still_held_offers_sigkill_on_odoo_only(self):
        chain = _chaine(ODOO, SYSTEMD)
        # écouteurs : départ, attente (tenu), avant SIGKILL, attente (libre)
        code, signaux, _ = self.lancer(
            chain, ["", "o"], [[500], [500], [500], []]
        )
        self.assertEqual(code, 0)
        self.assertEqual(signaux, [([500], False), ([500], True)])

    def test_sigkill_forces_the_tree_chosen_by_the_user(self):
        chain = _chaine(ODOO, ODOO_BIN_SH, RUN_SH, SHELL, SYSTEMD)
        chain[1].children.return_value = [chain[0]]
        chain[2].children.return_value = [chain[1], chain[0]]
        # Index 1 choisi : odoo_bin.sh, et non run.sh, la cible par défaut.
        code, signaux, _ = self.lancer(
            chain, ["1", "o"], [[500], [500], [500], []]
        )
        self.assertEqual(code, 0)
        self.assertEqual(signaux, [([500, 499], False), ([500, 499], True)])

    def test_sigkill_leaves_an_unconfirmed_listener_alone(self):
        odoo = _chaine(ODOO, SYSTEMD)
        autre = _chaine((700, "python", ["python", "serve.py"]), SYSTEMD)
        ancetres = {500: odoo, 700: autre}
        signaux = []
        lignes = []

        def stop(procs, force):
            signaux.append(([p.pid for p in procs], force))
            return [], []

        def imprime(*a, **_k):
            lignes.append(" ".join(str(x) for x in a))

        with (
            patch("sys.argv", ["kill", "8069"]),
            patch.object(
                kpp,
                "find_listeners",
                side_effect=[[500, 700], [700], [700], [700]],
            ),
            patch.object(kpp, "get_ancestry", side_effect=ancetres.get),
            patch.object(kpp, "stop_procs", side_effect=stop),
            patch.object(kpp, "systemd_service", return_value=None),
            patch.object(kpp, "GRACE_SECONDS", 0),
            # Odoo confirmé, l'autre annulé, puis SIGKILL accepté.
            patch("builtins.input", side_effect=["", "c", "o"]),
            patch("builtins.print", side_effect=imprime),
        ):
            self.assertEqual(kpp.main(), 1)
        self.assertEqual(signaux, [([500], False), ([500], True)])
        self.assertIn(
            "Listener pid=700 was not confirmed: left alone.", lignes
        )


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


class TestStopProcs(unittest.TestCase):
    """stop_procs appliqué à un arbre, tel que main() l'emploie."""

    @patch("script.process.kill_process_by_port.psutil.wait_procs")
    def test_kills_children_then_root(self, mock_wait):
        root = _make_proc(10, "root_proc")
        child1 = _make_proc(11, "child1")
        child2 = _make_proc(12, "child2")
        root.children.return_value = [child1, child2]
        mock_wait.return_value = ([root, child1, child2], [])

        alive, denied = stop_procs(tree_of(root), force=False)
        child1.terminate.assert_called_once()
        child2.terminate.assert_called_once()
        root.terminate.assert_called_once()
        self.assertEqual((alive, denied), ([], []))

    @patch("script.process.kill_process_by_port.psutil.wait_procs")
    def test_returns_alive_processes(self, mock_wait):
        root = _make_proc(10)
        mock_wait.return_value = ([], [root])

        alive, _denied = stop_procs(tree_of(root), force=True)
        self.assertEqual(len(alive), 1)
        root.kill.assert_called_once()

    @patch("script.process.kill_process_by_port.psutil.wait_procs")
    def test_handles_psutil_error_on_child(self, mock_wait):
        root = _make_proc(10)
        child = _make_proc(11)
        child.terminate.side_effect = psutil.NoSuchProcess(11)
        root.children.return_value = [child]
        mock_wait.return_value = ([child, root], [])

        alive, denied = stop_procs(tree_of(root), force=False)
        self.assertEqual((alive, denied), ([], []))

    @patch("script.process.kill_process_by_port.psutil.wait_procs")
    def test_access_denied_is_collected_and_not_awaited(self, mock_wait):
        root = _make_proc(10)
        child = _make_proc(11)
        child.terminate.side_effect = psutil.AccessDenied(11)
        root.children.return_value = [child]
        mock_wait.return_value = ([root], [])

        alive, denied = stop_procs(tree_of(root), force=False)
        self.assertEqual([p.pid for p in denied], [11])
        self.assertEqual(alive, [])
        root.terminate.assert_called_once()
        self.assertEqual(mock_wait.call_args.args[0], [root])

    def test_tree_of_a_vanished_root_is_the_root_alone(self):
        root = _make_proc(10)
        root.children.side_effect = psutil.NoSuchProcess(10)
        self.assertEqual(tree_of(root), [root])


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
        self.assertIn("sshd-session", PROTECTED_NAMES)

    def test_editors_are_protected(self):
        for name in ("code-oss", "codium", "electron"):
            self.assertIn(name, PROTECTED_NAMES)


if __name__ == "__main__":
    unittest.main()
