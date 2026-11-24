#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un déploiement raté ne laisse pas de disque orphelin derrière lui.

Un qcow2 resté sans domaine bloque le déploiement suivant du même nom :
deploy_qemu refuse d'écraser sans --force. `Defaire` retire donc ce que le
lancement a créé quand il s'arrête avant que le domaine n'existe.

Ce que ces tests gardent :

- seul ce que CE lancement a créé part : un disque présent avant (--force)
  reste, quoi qu'il arrive ;
- rien ne part quand un domaine porte ce nom, ni quand on ne sait pas
  l'établir ;
- l'erreur d'origine remonte intacte, même quand l'annulation échoue ;
- l'annulation va jusqu'au rm sur un terminal fermé ou sous un second
  signal ;
- un domaine existant est refusé avant toute écriture, même avec --force.
"""

import io
import os
import signal
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.argv = ["todo.py"]
from test.test_qemu_egl_fallback import DQ  # noqa: E402


class FauxRunner:
    """Retient (cmd, privileged, check) au lieu de lancer quoi que ce soit."""

    def __init__(self, dry_run=False, use_sudo=False, rm_leve=None):
        self.dry_run = dry_run
        self.use_sudo = use_sudo
        self.rm_leve = rm_leve
        self.cmds = []

    def run(self, cmd, *, privileged=False, check=True, capture=False):
        self.cmds.append((list(cmd), privileged, check))
        if self.rm_leve is not None and cmd[:1] == ["rm"]:
            raise self.rm_leve
        return (0, "") if capture else None

    def rms(self):
        return [c for c in self.cmds if c[0][:1] == ["rm"]]


class Annulation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.disque = self.tmp / "vm-a.qcow2"
        self.runner = FauxRunner()

    def tearDown(self):
        self._tmp.cleanup()

    def _echouer(self, d, exc, domaine=False):
        """Lève `exc` dans `with d:` et rend (exception vue, sortie)."""
        out = io.StringIO()
        with (
            mock.patch.object(DQ, "domaine_present", return_value=domaine),
            redirect_stdout(out),
            self.assertRaises(BaseException) as cm,
        ):
            with d:
                raise exc
        return cm.exception, out.getvalue()

    def test_a_disk_created_by_the_run_is_removed_after_a_failure(self):
        d = DQ.Defaire("vm-a", self.runner)
        self.assertTrue(d.noter(self.disque))
        self.disque.touch()
        vue, _out = self._echouer(d, SystemExit("Échec X"))
        self.assertIsInstance(vue, SystemExit)
        self.assertEqual("Échec X", vue.code)
        self.assertEqual(
            [(["rm", "-f", "--", str(self.disque)], True, False)],
            self.runner.rms(),
        )

    def test_a_disk_that_existed_before_the_run_is_kept(self):
        self.disque.touch()
        d = DQ.Defaire("vm-a", self.runner)
        self.assertFalse(d.noter(self.disque))
        self._echouer(d, SystemExit("Échec X"))
        self.assertEqual([], self.runner.rms())

    def test_nothing_is_removed_when_the_domain_exists(self):
        d = DQ.Defaire("vm-a", self.runner)
        d.noter(self.disque)
        _vue, out = self._echouer(d, SystemExit("Échec X"), domaine=True)
        self.assertEqual([], self.runner.rms())
        self.assertIn("vm-a", out)
        self.assertIn("virsh undefine", out)

    def test_nothing_is_removed_when_the_domain_state_is_unknown(self):
        d = DQ.Defaire("vm-a", self.runner)
        d.noter(self.disque)
        _vue, out = self._echouer(d, SystemExit("Échec X"), domaine=None)
        self.assertEqual([], self.runner.rms())
        self.assertIn(str(self.disque), out)

    def test_dry_run_records_nothing(self):
        runner = FauxRunner(dry_run=True)
        d = DQ.Defaire("vm-a", runner)
        self.assertFalse(d.noter(self.disque))
        sonde = mock.Mock(return_value=False)
        with (
            mock.patch.object(DQ, "domaine_present", sonde),
            self.assertRaises(SystemExit),
        ):
            with d:
                sys.exit("Échec X")
        self.assertEqual([], runner.cmds)
        sonde.assert_not_called()

    def test_ctrl_c_also_rolls_back_and_is_re_raised(self):
        d = DQ.Defaire("vm-a", self.runner)
        d.noter(self.disque)
        vue, _out = self._echouer(d, KeyboardInterrupt())
        self.assertIsInstance(vue, KeyboardInterrupt)
        self.assertEqual(1, len(self.runner.rms()))

    def test_a_success_or_exit_zero_removes_nothing(self):
        d = DQ.Defaire("vm-a", self.runner)
        d.noter(self.disque)
        with mock.patch.object(DQ, "domaine_present", return_value=False):
            with d:
                pass
            with self.assertRaises(SystemExit) as cm:
                with d:
                    sys.exit(0)
        self.assertEqual(0, cm.exception.code)
        self.assertEqual([], self.runner.cmds)

    def test_a_failing_rollback_does_not_mask_the_original_error(self):
        runner = FauxRunner(rm_leve=SystemExit("rm cassé"))
        d = DQ.Defaire("vm-a", runner)
        d.noter(self.disque)
        vue, out = self._echouer(d, SystemExit("Échec X"))
        self.assertEqual("Échec X", vue.code)
        self.assertIn("Annulation interrompue", out)

    def test_existence_is_tri_state(self):
        self.assertIs(False, DQ.chemin_present(self.disque, False))
        self.disque.touch()
        self.assertIs(True, DQ.chemin_present(self.disque, False))
        refus = mock.patch.object(DQ.os, "lstat", side_effect=PermissionError)
        with refus:
            self.assertIsNone(DQ.chemin_present(self.disque, False))
            d = DQ.Defaire("vm-a", self.runner)
            self.assertFalse(d.noter(self.disque))
            self.assertEqual([], d.crees)
            absent = SimpleNamespace(returncode=1, stderr=b"")
            with mock.patch.object(
                DQ.subprocess, "run", return_value=absent
            ) as run:
                self.assertIs(False, DQ.chemin_present(self.disque, True))
            p = str(self.disque)
            self.assertEqual(
                ["sudo", "-n", "test", "-e", p, "-o", "-L", p],
                run.call_args.args[0],
            )
            parle = SimpleNamespace(returncode=1, stderr=b"sudo: password")
            with mock.patch.object(DQ.subprocess, "run", return_value=parle):
                self.assertIsNone(DQ.chemin_present(self.disque, True))

    def test_a_dangling_symlink_counts_as_present(self):
        self.disque.symlink_to(self.tmp / "cible-absente.qcow2")
        self.assertIs(True, DQ.chemin_present(self.disque, False))
        d = DQ.Defaire("vm-a", self.runner)
        self.assertFalse(d.noter(self.disque))
        self._echouer(d, SystemExit("Échec X"))
        self.assertEqual([], self.runner.rms())

    def test_a_dead_terminal_neither_skips_rm_nor_masks_the_error(self):
        class Morte:
            def write(self, _s):
                raise OSError(5, "Input/output error")

            def flush(self):
                raise OSError(5, "Input/output error")

        class RunnerBavard(FauxRunner):
            # Comme Runner.run : la commande est affichée avant d'être lancée.
            def run(self, cmd, **kw):
                print("  $ " + " ".join(cmd))
                return super().run(cmd, **kw)

        for runner in (RunnerBavard(), RunnerBavard(rm_leve=SystemExit(1))):
            d = DQ.Defaire("vm-a", runner)
            d.noter(self.disque)
            with (
                mock.patch.object(DQ, "domaine_present", return_value=False),
                redirect_stdout(Morte()),
                self.assertRaises(BaseException) as cm,
            ):
                with d:
                    raise SystemExit(129)
            self.assertIsInstance(cm.exception, SystemExit)
            self.assertEqual(129, cm.exception.code)
            self.assertEqual(1, len(runner.rms()))

    def test_domain_presence_falls_back_to_plain_virsh(self):
        def rep(rc, err=""):
            return SimpleNamespace(returncode=rc, stdout="", stderr=err)

        mdp = rep(1, "sudo: a password is required")
        cas = [
            ([mdp, rep(0)], True),
            ([mdp, rep(1, "error: failed to get domain 'vm-a'")], False),
            ([mdp, rep(1, "error: authentication failed")], None),
        ]
        for reponses, attendu in cas:
            with mock.patch.object(
                DQ.subprocess, "run", side_effect=reponses
            ) as run:
                self.assertIs(attendu, DQ.domaine_present("vm-a", True))
            premier, second = (c.args[0] for c in run.call_args_list)
            self.assertEqual(["sudo", "-n"], premier[:2])
            self.assertEqual(premier[2:], second)
            for c in run.call_args_list:
                self.assertIs(DQ.subprocess.DEVNULL, c.kwargs["stdin"])

    def test_domain_presence_reads_virsh_in_c_locale(self):
        def rep(rc, err=""):
            return SimpleNamespace(returncode=rc, stdout="", stderr=err)

        cas = [
            (rep(0), True),
            (rep(1, "error: failed to get domain 'vm-a'"), False),
            (rep(1, "error: Domain not found: vm-a"), False),
            (rep(1, "error: failed to connect to the hypervisor"), None),
        ]
        for res, attendu in cas:
            with mock.patch.object(DQ.subprocess, "run", return_value=res):
                self.assertIs(attendu, DQ.domaine_present("vm-a", False))
        with mock.patch.object(DQ.subprocess, "run", side_effect=OSError):
            self.assertIsNone(DQ.domaine_present("vm-a", False))
        with mock.patch.object(
            DQ.subprocess, "run", return_value=rep(0)
        ) as run:
            DQ.domaine_present("vm-a", True)
        argv = run.call_args.args[0]
        self.assertEqual(["sudo", "-n"], argv[:2])
        self.assertIn("domstate", argv)
        self.assertIn(DQ.LIBVIRT_URI, argv)
        self.assertEqual("C", run.call_args.kwargs["env"]["LC_ALL"])
        self.assertIn("timeout", run.call_args.kwargs)

    def test_sigterm_becomes_a_rollback(self):
        avant = signal.getsignal(signal.SIGTERM)
        d = DQ.Defaire("vm-a", self.runner)
        d.noter(self.disque)
        out = io.StringIO()
        with (
            mock.patch.object(DQ, "domaine_present", return_value=False),
            redirect_stdout(out),
            self.assertRaises(SystemExit) as cm,
        ):
            with d:
                os.kill(os.getpid(), signal.SIGTERM)
                # Le gestionnaire lève au prochain point de contrôle.
                for _ in range(1000):
                    pass
        self.assertEqual(128 + signal.SIGTERM, cm.exception.code)
        self.assertEqual(1, len(self.runner.rms()))
        self.assertEqual(avant, signal.getsignal(signal.SIGTERM))

    def test_a_second_signal_does_not_interrupt_the_rollback(self):
        """Un SIGHUP ou SIGTERM reçu pendant l'annulation reste sans effet."""
        avant = signal.getsignal(signal.SIGTERM)

        def sonde(*_a):
            os.kill(os.getpid(), signal.SIGTERM)
            for _ in range(1000):
                pass
            return False

        for origine, attendu in (
            (signal.SIGTERM, 128 + signal.SIGTERM),
            (None, None),
        ):
            runner = FauxRunner()
            d = DQ.Defaire("vm-a", runner)
            d.noter(self.disque)
            with (
                mock.patch.object(DQ, "domaine_present", sonde),
                redirect_stdout(io.StringIO()),
                self.assertRaises(BaseException) as cm,
            ):
                with d:
                    if origine is None:
                        raise KeyboardInterrupt
                    os.kill(os.getpid(), origine)
                    for _ in range(1000):
                        pass
            if attendu is None:
                self.assertIsInstance(cm.exception, KeyboardInterrupt)
            else:
                self.assertEqual(attendu, cm.exception.code)
            self.assertEqual(1, len(runner.rms()))
            self.assertEqual(avant, signal.getsignal(signal.SIGTERM))


class LeBlocCouvreDuDisqueAVirtInstall(unittest.TestCase):
    """Garde-fou de source : l'ordre des appels dans main()."""

    def setUp(self):
        import inspect

        self.src = inspect.getsource(DQ.main)

    def test_main_guards_the_disk_to_virt_install_range(self):
        src = self.src
        debut = src.index("with Defaire(")
        for appel in (
            "prepare_disk(",
            "create_blank_disk(disk",
            "build_seed(",
            "virt_install(args, disk",
        ):
            self.assertLess(debut, src.index(appel), appel)
        self.assertEqual(2, src.count("defaire.noter(disk)"))
        self.assertEqual(1, src.count("defaire.noter(seed)"))
        self.assertEqual(1, src.count("defaire.noter(initrd)"))
        lignes = src.splitlines()

        def retrait(motif):
            ligne = next(x for x in lignes if motif in x)
            return len(ligne) - len(ligne.lstrip())

        # Le « if installer: » qui porte le suivi est hors du bloc : le
        # domaine existe alors, et un échec ne doit plus rien retirer.
        i = next(
            n
            for n, x in enumerate(lignes)
            if "watch_and_restart(args.name" in x
        )
        garde = lignes[i - 1]
        self.assertEqual("if installer:", garde.strip())
        self.assertLess(
            len(garde) - len(garde.lstrip()),
            retrait("virt_install(args, disk"),
        )
        self.assertLess(
            src.index("domaine_present(args.name"), src.index("with Defaire(")
        )


class BoutEnBout(unittest.TestCase):
    """main() entier, chaque étape système remplacée par un faux."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.runner = FauxRunner()
        self.prepare = mock.Mock(side_effect=self._prepare)

    def tearDown(self):
        self._tmp.cleanup()

    def _prepare(self, image, disk, size, runner, force):
        disk.touch()

    @staticmethod
    def _seed(cfg, hostname, seed, runner, net):
        seed.touch()

    def _lancer(self, *extra, domaine=False, virt=None):
        argv = [
            "deploy_qemu.py",
            "--distro",
            "debian",
            "--name",
            "vm-t",
            "--disk-dir",
            str(self.tmp),
            "--seed-dir",
            str(self.tmp),
            "--no-verify",
            "--no-wait-ip",
            *extra,
            str(self.tmp / "image.qcow2"),
        ]
        faux = {
            "Runner": lambda **_kw: self.runner,
            "ensure_tools": mock.Mock(),
            "host_arch": lambda: "amd64",
            "image_candidates": lambda *a, **k: ["https://x.invalid/i"],
            "download_image": mock.Mock(),
            "verify_pinned_sha256": mock.Mock(),
            "image_en_cache": lambda _p: True,
            "resolve_password": lambda _a: "$6$faux",
            "load_ssh_keys": lambda _p: [],
            "prepare_disk": self.prepare,
            "build_cloud_config": lambda *a: "",
            "build_seed": self._seed,
            "osinfo_arg": lambda *a: "debian13",
            "ensure_network": mock.Mock(),
            "cache_bypass_apply": mock.Mock(),
            "virt_install": virt or mock.Mock(side_effect=SystemExit("x")),
            "domaine_present": lambda *_a: domaine,
        }
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.multiple(DQ, **faux),
            redirect_stdout(io.StringIO()),
            mock.patch("sys.stderr", io.StringIO()),
            self.assertRaises(SystemExit) as cm,
        ):
            DQ.main()
        return cm.exception

    def test_a_failed_virt_install_removes_disk_and_seed(self):
        vue = self._lancer()
        self.assertEqual("x", vue.code)
        self.assertEqual(
            [
                (
                    [
                        "rm",
                        "-f",
                        "--",
                        str(self.tmp / "vm-t.qcow2"),
                        str(self.tmp / "vm-t-seed.iso"),
                    ],
                    True,
                    False,
                )
            ],
            self.runner.rms(),
        )

    def test_an_existing_domain_is_refused_before_any_disk_write(self):
        for extra in ((), ("--force",)):
            vue = self._lancer(*extra, domaine=True)
            self.assertIn("vm-t", str(vue.code))
            self.prepare.assert_not_called()
        self._lancer(domaine=None)
        self.prepare.assert_called_once()


if __name__ == "__main__":
    unittest.main()
