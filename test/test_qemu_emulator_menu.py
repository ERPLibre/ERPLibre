#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu de l'émulateur Android : démarrage, fenêtre ou non, tunnel adb.

Ce qui se vérifie ici sans VM tient à ce qui a réellement cassé sur la VM de
preuve : une commande privée de son chemin absolu (« emulator: command not
found », un ssh non interactif ne lisant aucun rc), un second émulateur sur le
même AVD (« Running multiple emulators »), une clé d'hôte refusée sur une IP
recyclée, et un tunnel visant une adresse que l'émulateur n'écoute pas.

Le tunnel est le point délicat : l'émulateur n'écoute que sur le 127.0.0.1 de
la VM (« ss -ltn » dans l'invité ; l'hyperviseur reçoit un refus sur
IP_VM:5555). Une redirection vers l'IP de la VM ne peut donc PAS aboutir, et
seul un dernier saut dans la VM place « localhost » au bon endroit.
"""

import socket
import subprocess
import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402


def _run_ok(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestSshOptions(unittest.TestCase):
    """La politique de clés d'hôte n'est PAS la même selon la provenance."""

    def test_local_vm_tolerates_a_recycled_host_key(self):
        """Une IP libvirt est réattribuée d'un déploiement au suivant : la clé
        change sous la même adresse et ssh refuse — « Host key verification
        failed », vécu dans ce menu même."""
        opts = TODO._qemu_ssh_opts("virsh")
        self.assertIn("StrictHostKeyChecking=no", opts)
        self.assertIn("UserKnownHostsFile=/dev/null", opts)

    def test_a_configured_host_keeps_its_own_key_policy(self):
        """Un hôte de ~/.ssh/config appartient à l'utilisateur : sa clé est un
        garde-fou, et le désarmer en son nom serait une décision volée."""
        opts = TODO._qemu_ssh_opts("ssh_config")
        self.assertNotIn("StrictHostKeyChecking=no", opts)
        self.assertNotIn("UserKnownHostsFile=/dev/null", opts)
        self.assertIn("BatchMode=yes", opts)

    def test_both_refuse_to_hang_on_a_password_prompt(self):
        for src in ("virsh", "ssh_config"):
            self.assertIn("BatchMode=yes", TODO._qemu_ssh_opts(src), src)


class TestSshTarget(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_a_configured_host_is_named_as_is(self):
        """C'est l'entrée ssh_config qui porte le ProxyJump : la réécrire à la
        main reviendrait à deviner la chaîne de sauts."""
        self.todo._qemu_resolve_ips = lambda *a, **k: {}
        self.assertEqual(
            self.todo._qemu_ssh_target("test-vm_02+proof", "ssh_config"),
            "test-vm_02+proof",
        )

    def test_a_local_vm_is_reached_by_ip_as_erplibre(self):
        self.todo._qemu_resolve_ips = lambda names, labels=None: {
            "vm-a": "192.168.123.81"
        }
        self.assertEqual(
            self.todo._qemu_ssh_target("vm-a", "virsh"),
            "erplibre@192.168.123.81",
        )

    def test_no_ip_yields_no_target_rather_than_a_broken_one(self):
        """Une VM éteinte n'a pas d'IP. Rendre « erplibre@None » enverrait ssh
        résoudre un nom absurde au lieu de le dire."""
        self.todo._qemu_resolve_ips = lambda names, labels=None: {}
        self.assertEqual(self.todo._qemu_ssh_target("vm-a", "virsh"), "")


class TestEmulatorRunning(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_counts_what_pgrep_reports(self):
        with mock.patch("subprocess.run", return_value=_run_ok("1\n")):
            self.assertEqual(self.todo._qemu_emulator_running("h"), 1)

    def test_reads_the_last_line_so_a_warning_does_not_fool_it(self):
        """ssh écrit ses avertissements sur stdout dans certains cas ; le compte
        est la DERNIÈRE ligne."""
        with mock.patch(
            "subprocess.run", return_value=_run_ok("Warning: added key\n0\n")
        ):
            self.assertEqual(self.todo._qemu_emulator_running("h"), 0)

    def test_an_unreachable_vm_is_unknown_not_zero(self):
        """Zéro voudrait dire « libre » et autoriserait un second émulateur sur
        le même AVD. L'inconnu se distingue donc du vide."""
        with mock.patch("subprocess.run", side_effect=OSError):
            self.assertEqual(self.todo._qemu_emulator_running("h"), -1)
        with mock.patch("subprocess.run", return_value=_run_ok("bavardage\n")):
            self.assertEqual(self.todo._qemu_emulator_running("h"), -1)


class TestEmulatorReady(unittest.TestCase):
    """Une seule lecture répond aux deux questions : binaire, puis AVD."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_a_complete_vm_is_ready(self):
        with mock.patch("subprocess.run", return_value=_run_ok("")):
            self.assertEqual(self.todo._qemu_emulator_ready("h"), (True, ""))

    def test_the_missing_piece_is_named(self):
        for probe, word in (("NO_SDK\n", "SDK"), ("NO_AVD\n", "AVD")):
            with mock.patch("subprocess.run", return_value=_run_ok(probe)):
                ready, why = self.todo._qemu_emulator_ready("h")
            self.assertFalse(ready, probe)
            self.assertIn(word, why, probe)

    def test_the_sdk_is_reported_before_the_avd(self):
        """Sans SDK, l'absence d'AVD n'est qu'une conséquence : nommer la cause
        évite d'envoyer l'utilisateur créer un AVD qu'il ne peut pas créer."""
        with mock.patch(
            "subprocess.run", return_value=_run_ok("NO_SDK\nNO_AVD\n")
        ):
            _, why = self.todo._qemu_emulator_ready("h")
        self.assertIn("SDK", why)

    def test_an_unreachable_vm_is_not_declared_ready(self):
        with mock.patch("subprocess.run", side_effect=OSError):
            ready, why = self.todo._qemu_emulator_ready("h")
        self.assertFalse(ready)
        self.assertTrue(why)


class _MenuCase(unittest.TestCase):
    """Socle commun : une VM locale, des réponses scriptées, aucun vrai ssh."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.todo._ssh_config_hosts = lambda: []
        self.todo._qemu_list_domains = lambda: ["vm-a"]
        self.todo._qemu_resolve_ips = lambda names, labels=None: {
            "vm-a": "192.168.123.81"
        }
        self.todo._qemu_self_address = staticmethod(lambda: ("10.0.0.2", True))
        self.calls = []

    def _play(self, answers, running=0, start_rc=0, port_taken=False,
              probe="", running_after=1, log="rien"):
        """Joue le menu avec des réponses données ; rend (sortie, commandes).

        « running » est le compte AVANT le démarrage, « running_after » celui
        d'après : c'est cette distinction qui dit si l'émulateur a réellement
        pris, le code de retour d'un « setsid » détaché ne valant rien.
        """
        state = {"started": False}

        def fake_run(cmd, *a, **k):
            self.calls.append(cmd)
            joined = " ".join(cmd)
            if "pgrep -c qemu-system" in joined:
                n = running_after if state["started"] else running
                return _run_ok(f"{n}\n")
            if "NO_SDK" in joined:
                return _run_ok(probe)
            if "setsid" in joined:
                state["started"] = True
                return _run_ok(returncode=start_rc, stderr="boum")
            if "tail -5" in joined:
                return _run_ok(log)
            return _run_ok()

        it = iter(answers)
        with mock.patch("subprocess.run", side_effect=fake_run), mock.patch(
            "builtins.input", lambda *a: next(it)
        ), mock.patch.object(
            TODO, "_port_in_use", staticmethod(lambda p: port_taken)
        ), mock.patch(
            "script.todo.todo.time.sleep", lambda *a: None
        ), mock.patch(
            "sys.stdout", new_callable=__import__("io").StringIO
        ) as out:
            self.todo._qemu_emulator_menu()
        return out.getvalue(), self.calls

    @staticmethod
    def _started(calls):
        return [c for c in calls if any("setsid" in x for x in c)]

    @staticmethod
    def _tunnels(calls):
        return [c for c in calls if "-f" in c and "-N" in c]


class TestEmulatorMenu(_MenuCase):
    def test_no_target_at_all_says_so_without_touching_ssh(self):
        self.todo._qemu_list_domains = lambda: []
        out, calls = self._play([])
        self.assertIn("~/.ssh/config", out)
        self.assertEqual(calls, [])

    def test_an_off_vm_is_reported_before_any_start(self):
        self.todo._qemu_resolve_ips = lambda names, labels=None: {}
        out, calls = self._play(["1"])
        self.assertIn("IP", out.upper())
        self.assertEqual(self._started(calls), [])

    def test_a_running_emulator_is_seen_and_refusing_stops_there(self):
        """Deux émulateurs sur un même AVD, et le second meurt sur « Running
        multiple emulators with the same AVD » — vécu deux fois. On le dit
        AVANT, et un refus ne démarre rien."""
        out, calls = self._play(["1", "n"], running=1)
        self.assertIn("pkill -f", out)
        # « [q]emu » : la classe empêche le pkill de se trouver lui-même.
        self.assertIn("[q]emu-system", out)
        self.assertEqual(self._started(calls), [])

    def test_accepting_closes_the_other_one_then_starts(self):
        out, calls = self._play(["1", "o", "1", "n"], running=1)
        killed = [c for c in calls if any("pkill" in x for x in c)]
        self.assertTrue(killed, "aucun pkill envoyé")
        self.assertTrue(self._started(calls), "rien démarré après fermeture")

    def test_the_window_choice_is_delegated_to_the_workstation(self):
        """L'écran appartient au poste : cette commande ne peut pas partir de
        l'hyperviseur, qui n'a aucun affichage à lui prêter."""
        out, calls = self._play(["1", "2"])
        self.assertIn("ssh -XC", out)
        self.assertEqual(self._started(calls), [])
        self.assertEqual(self._tunnels(calls), [])

    def test_the_headless_start_carries_what_the_vm_needs(self):
        out, calls = self._play(["1", "1", "n"])
        started = self._started(calls)
        self.assertEqual(len(started), 1)
        cmd = started[0][-1]
        # Chemin absolu : « ssh hôte 'commande' » ne lit ni ~/.profile ni
        # ~/.bashrc, et « emulator » seul rend « command not found » — vécu.
        self.assertIn("$HOME/android/emulator/emulator", cmd)
        self.assertIn("-no-window", cmd)
        # sg kvm : sans le groupe, l'émulateur n'a pas /dev/kvm et renonce.
        self.assertIn("sg kvm", cmd)
        # setsid : il doit survivre à la fermeture de ce ssh.
        self.assertIn("setsid -f", cmd)
        self.assertIn("/tmp/erplibre-emulator.log", cmd)

    def test_the_start_command_is_valid_shell(self):
        """Une apostrophe ou un guillemet de trop, et la VM répond par une
        erreur de syntaxe — déjà rencontré dans ce même fichier."""
        _, calls = self._play(["1", "1", "n"])
        cmd = self._started(calls)[0][-1]
        res = subprocess.run(
            ["bash", "-n"], input=cmd, capture_output=True, text=True
        )
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_a_failed_start_does_not_offer_a_tunnel_to_nothing(self):
        out, calls = self._play(["1", "1"], start_rc=1)
        self.assertIn("boum", out)
        self.assertEqual(self._tunnels(calls), [])

    def test_a_vm_without_the_sdk_is_diagnosed_before_anything_else(self):
        """Une VM déployée sans cocher l'outil est le cas NORMAL. Le menu le
        dit avant même de demander la fenêtre — mesuré sur une VM de migration,
        où le démarrage détaché rendait 0 et le journal disait « not found »."""
        out, calls = self._play(["1"], probe="NO_SDK\n")
        self.assertIn("SDK", out)
        self.assertNotIn("[1]", out.split("VM locale")[-1])
        self.assertEqual(self._started(calls), [])

    def test_a_vm_without_the_avd_is_named_as_such(self):
        out, calls = self._play(["1"], probe="NO_AVD\n")
        self.assertIn("AVD", out)
        self.assertEqual(self._started(calls), [])

    def test_a_stray_answer_cancels_instead_of_starting(self):
        """« n » à une question à deux crans partait démarrer l'émulateur :
        tout ce qui n'était pas « 2 » valait « sans fenêtre ». Observé."""
        for stray in ("n", "3", "oui"):
            self.calls = []
            out, calls = self._play(["1", stray])
            self.assertEqual(self._started(calls), [], stray)

    def test_a_start_that_never_appears_reports_the_log_not_a_success(self):
        """Le code de retour d'un « setsid » détaché vaut 0 quoi qu'il arrive :
        seule la présence du processus prouve le démarrage."""
        out, calls = self._play(
            ["1", "1"], running_after=0, log="emulator: not found"
        )
        self.assertIn("not found", out)
        self.assertNotIn("scrcpy -s", out)

    def test_a_successful_start_chains_into_the_tunnel_help(self):
        out, _ = self._play(["1", "1", "n"])
        self.assertIn("scrcpy", out)
        self.assertIn("adb connect localhost:5555", out)


class TestScrcpyTunnel(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.todo._qemu_resolve_ips = lambda names, labels=None: {
            "vm-a": "192.168.123.81"
        }
        self.todo._qemu_self_address = staticmethod(lambda: ("10.0.0.2", True))
        self.calls = []

    def _play(
        self,
        src="virsh",
        answers=("n",),
        rc=0,
        port_taken=False,
        started=False,
        name="vm-a",
    ):
        def fake_run(cmd, *a, **k):
            self.calls.append(cmd)
            return _run_ok(returncode=rc, stderr="refus")

        it = iter(answers)
        with mock.patch("subprocess.run", side_effect=fake_run), mock.patch(
            "builtins.input", lambda *a: next(it)
        ), mock.patch.object(
            TODO, "_port_in_use", staticmethod(lambda p: port_taken)
        ), mock.patch.dict(
            "os.environ", {"USER": "poste"}
        ), mock.patch(
            "sys.stdout", new_callable=__import__("io").StringIO
        ) as out:
            self.todo._qemu_scrcpy_tunnel(name, src, started=started)
        return out.getvalue(), self.calls

    def test_a_local_vm_needs_the_vm_as_the_LAST_hop(self):
        """L'émulateur n'écoute que sur le 127.0.0.1 de la VM. Une redirection
        vers IP_VM:5555 depuis l'hyperviseur est refusée (mesuré) : « localhost »
        ne vaut que sur le dernier saut, d'où -J."""
        out, _ = self._play(src="virsh")
        self.assertIn("-L 5555:localhost:5555", out)
        self.assertIn("-J poste@10.0.0.2", out)
        self.assertIn("erplibre@192.168.123.81", out)
        self.assertNotIn("-L 5555:192.168.123.81:5555", out)

    def test_a_configured_host_rides_its_own_proxyjump(self):
        out, _ = self._play(src="ssh_config", name="test-vm_02+proof")
        self.assertIn("-L 5555:localhost:5555 test-vm_02+proof", out)
        self.assertNotIn("-J", out)
        self.assertIn("ProxyJump", out)

    def test_it_gives_the_three_workstation_commands(self):
        """Le tunnel ne sert à rien seul : la connexion adb et scrcpy le
        suivent, et scrcpy n'est pas installé par défaut."""
        out, _ = self._play()
        self.assertIn("adb connect localhost:5555", out)
        self.assertIn("scrcpy -s localhost:5555", out)
        self.assertIn("apt install scrcpy", out)

    def test_this_path_never_falls_back_to_x11(self):
        """Tout l'intérêt : plus de X11 nulle part, le flux est du H.264."""
        out, _ = self._play()
        self.assertNotIn("ssh -X", out)

    def test_the_tunneled_port_is_the_device_not_the_adb_server(self):
        """5037 est le serveur adb du poste : le tunneler obligerait à tuer
        celui de l'utilisateur, qui occupe le même port. 5555 est l'appareil.
        """
        out, _ = self._play()
        self.assertNotIn("5037", out)
        self.assertIn("5555", out)

    def test_it_does_not_repeat_the_start_command_after_starting(self):
        out, _ = self._play(started=True)
        self.assertNotIn("-no-window", out)
        out, _ = self._play(started=False)
        self.assertIn("-no-window", out)
        self.assertIn("$HOME/android/emulator/emulator", out)

    def test_declining_opens_nothing(self):
        _, calls = self._play(answers=("n",))
        self.assertEqual(calls, [])

    def test_accepting_opens_a_detached_tunnel_that_fails_loudly(self):
        """« -f » sans « ExitOnForwardFailure » rend 0 alors que la redirection
        a échoué : un succès annoncé pour un tunnel absent."""
        out, calls = self._play(answers=("o",))
        self.assertEqual(len(calls), 1)
        cmd = calls[0]
        self.assertIn("-f", cmd)
        self.assertIn("-N", cmd)
        self.assertIn("ExitOnForwardFailure=yes", cmd)
        self.assertIn("5555:localhost:5555", cmd)
        self.assertIn("erplibre@192.168.123.81", cmd)
        self.assertIn("✅", out)

    def test_an_occupied_port_is_named_instead_of_a_silent_bind_error(self):
        """Le « bind: Address already in use » d'ssh se perd en mode détaché."""
        out, calls = self._play(answers=("o",), port_taken=True)
        self.assertEqual(calls, [])
        self.assertIn("5555", out)
        self.assertIn("pkill", out)

    def test_a_refused_tunnel_is_reported(self):
        out, _ = self._play(answers=("o",), rc=255)
        self.assertIn("refus", out)
        self.assertNotIn("✅", out)


class TestPortInUse(unittest.TestCase):
    def test_a_listening_socket_is_seen(self):
        with socket.socket() as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            self.assertTrue(TODO._port_in_use(srv.getsockname()[1]))

    def test_a_closed_port_is_free(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.assertFalse(TODO._port_in_use(port))


if __name__ == "__main__":
    unittest.main()
