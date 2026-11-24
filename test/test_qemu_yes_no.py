#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""QEMU/KVM : les questions oui/non de la gestion des VM, du réseau, des
statistiques et du secours, sous les règles de `ui.confirm`.

Chaque question qui efface, éteint de force ou réécrit ~/.ssh/config est
non par défaut : Entrée, une faute puis Ctrl+D et Ctrl+D n'y lancent rien ;
o, oui, y et yes agissent. La sauvegarde avant réduction prend `back` :
Ctrl+D y arrête la réduction entière. Le matériel d'une VM prend son état
pour défaut, et Ctrl+D le garde. La réduction se confirme en tapant le nom
de la VM.

virsh, sudo et rm ne partent jamais : `execute` et
`todo_journal.lancer_journalise` notent chaque commande. Un `ScriptedPort`
répond aux questions du port ; `input` ne lit que les questions texte.
"""

import itertools
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import qemu_manage as qm  # noqa: E402
from script.todo import qemu_recover, todo_i18n, ui  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402
from script.todo.ui.port import ScriptedPort  # noqa: E402

VM = "forged-yesno-vm"
IMAGES = "/var/lib/libvirt/images"
# Une réponse vide, une faute puis Ctrl+D, Ctrl+D : chacune vaut non.
REFUS = ([""], ["peut-être", EOFError()], [EOFError()])
OUI = (["o"], ["oui"], ["y"], ["YES"])


class _Execute:
    """Note chaque commande, sans rien lancer."""

    def __init__(self):
        self.cmds = []

    def exec_command_live(self, cmd, **opts):
        self.cmds.append(cmd)
        return (0, []) if opts.get("return_status_and_output") else 0


class _Base(unittest.TestCase):
    def setUp(self):
        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("fr")
        self.enterContext(mock.patch.object(qm, "sudo_prefix", lambda: ""))
        self.enterContext(
            mock.patch.object(qm, "virsh_argv", lambda *a: ["virsh", *a])
        )
        self.journal = []
        self.enterContext(
            mock.patch.object(
                qm.todo_journal,
                "lancer_journalise",
                lambda argv: self.journal.append(argv) or 0,
            )
        )
        self.todo = TODO.__new__(TODO)
        self.todo.execute = _Execute()

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

    def backs(self):
        """Vrai quand chaque question oui/non posée porte `back`."""
        return all(
            event.get("back")
            for event in self.port.events
            if event.get("kind") == "confirm"
        )

    def assert_refused(self, refus):
        """Chaque réponse de `refus` a été lue ; une faute a été dite."""
        self.assertEqual(self.port.answers, [])
        notices = [
            e["text"] for e in self.port.events if e.get("t") == "notice"
        ]
        if "peut-être" in refus:
            self.assertIn(f"{t('Answer yes or no: ')}peut-être", notices)


class TestLeNettoyage(_Base):
    """Clean up QEMU : fichiers orphelins, images en double, tout le cache
    d'images de base ; chaque lot ne part que sur son oui."""

    FILES = {
        (IMAGES, "*.qcow2"): [(3, f"{IMAGES}/{VM}.qcow2")],
        (f"{IMAGES}/iso", "*-server-cloudimg-*.img"): [
            (2, f"{IMAGES}/iso/forged-server-cloudimg-amd64.img")
        ],
        (f"{IMAGES}/iso", "*"): [(1, f"{IMAGES}/iso/forged-yesno-base.img")],
    }

    def setUp(self):
        super().setUp()
        self.todo._qemu_list_domains = lambda: []
        self.todo._qemu_find_files = lambda d, p: list(
            self.FILES.get((d, p), [])
        )
        self.todo._qemu_split_orphans = lambda found: (list(found), [])
        self.todo._cleanup_ghost_domains = lambda: None
        self.todo._cleanup_ssh_config = lambda domains: None
        self.todo._cleanup_stale_leases = lambda: None

    def test_each_batch_is_deleted_only_on_its_yes(self):
        for refus in REFUS:
            with self.subTest(refus=refus):
                self.todo.execute.cmds.clear()
                self.play(self.todo._qemu_cleanup, [*refus] * 3)
                self.assertEqual(self.todo.execute.cmds, [])
                self.assert_refused(refus)
        self.assertEqual(
            self.asked(),
            [
                (t("Delete these orphan files?"), "n"),
                (t("Delete these duplicate images?"), "n"),
                (t("Delete ALL cached base images?"), "n"),
            ],
        )
        for oui in OUI:
            with self.subTest(oui=oui):
                self.todo.execute.cmds.clear()
                self.play(self.todo._qemu_cleanup, oui * 3)
                self.assertEqual(
                    [cmd.split(" ", 3)[3] for cmd in self.todo.execute.cmds],
                    [path for [(_s, path)] in self.FILES.values()],
                )

    def test_the_deployment_asks_with_the_same_rules(self):
        # Les disques restés seuls d'un déploiement passent par la même
        # liste, sous leur propre question.
        items = [(4, f"{IMAGES}/{VM}.qcow2")]
        prompt = t("Delete them and continue?")
        call = lambda: self.todo._cleanup_delete_files("forged", items, prompt)
        for refus in REFUS:
            self.play(call, refus)
            self.assertEqual(self.todo.execute.cmds, [])
        self.play(call, ["oui"])
        self.assertEqual(self.todo.execute.cmds, [f"sudo rm -f {items[0][1]}"])
        self.assertEqual(self.asked(), [(prompt, "n")])


class TestEffacerUneVm(_Base):
    """Delete VM(s) : les disques ne partent que sur leur oui, la VM que
    sur celui de la confirmation."""

    def setUp(self):
        super().setUp()
        self.todo._qemu_list_vms = lambda *a, **k: None
        self.todo._qemu_list_domains = lambda: [VM]
        self.todo._qemu_vm_own_files = lambda name: [f"{IMAGES}/{name}.qcow2"]
        self.enterContext(mock.patch.object(qm, "bypass_menage", lambda e: 0))

    def test_the_vm_and_its_disks_go_only_on_their_yes(self):
        for refus in REFUS:
            with self.subTest(refus=refus):
                self.todo.execute.cmds.clear()
                self.play(self.todo._qemu_delete_vm, ["1", "o", *refus])
                self.assertEqual(self.todo.execute.cmds, [])
                self.assert_refused(refus)
                self.play(self.todo._qemu_delete_vm, ["1", *refus, "oui"])
                [cmd] = self.todo.execute.cmds
                self.assertIn(f"undefine {VM}", cmd)
                self.assertNotIn("rm -f", cmd)
        self.assertEqual(
            self.asked(),
            [
                (t("Also delete disk images (qcow2 + seed ISO)?"), "n"),
                (t("Confirm deletion?"), "n"),
            ],
        )
        self.todo.execute.cmds.clear()
        self.play(self.todo._qemu_delete_vm, ["1", "y", "yes"])
        [cmd] = self.todo.execute.cmds
        self.assertIn(f"sudo rm -f {IMAGES}/{VM}.qcow2", cmd)


class TestLesDomainesFantomes(_Base):
    def test_a_ghost_is_undefined_only_on_yes(self):
        listing = f"Type Device Target Source\n---\nfile disk vda {IMAGES}/x\n"

        def run(argv, **_kw):
            if "domblklist" in argv:
                return subprocess.CompletedProcess(argv, 0, listing, "")
            return subprocess.CompletedProcess(argv, 1, "", "")

        self.todo._qemu_list_domains = lambda: [VM]
        self.enterContext(mock.patch.object(qm.subprocess, "run", run))
        for refus in REFUS:
            with self.subTest(refus=refus):
                self.play(self.todo._cleanup_ghost_domains, refus)
                self.assertEqual(self.todo.execute.cmds, [])
                self.assert_refused(refus)
        self.assertEqual(
            self.asked(), [(t("Undefine these ghost domains?"), "n")]
        )
        self.play(self.todo._cleanup_ghost_domains, ["oui"])
        [cmd] = self.todo.execute.cmds
        self.assertIn(f"undefine {VM}", cmd)


class TestLesEntreesSsh(_Base):
    def test_an_orphan_entry_is_removed_only_on_yes(self):
        home = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.dict(os.environ, {"HOME": home}))
        os.mkdir(os.path.join(home, ".ssh"))
        cfg = os.path.join(home, ".ssh", "config")
        content = f"Host erplibre-{VM}\n    User forged\n"
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(content)
        self.todo._qemu_vm_ip_now = lambda name: None
        self.todo._pve_host = lambda ask=False: None
        for refus in REFUS:
            with self.subTest(refus=refus):
                self.play(lambda: self.todo._cleanup_ssh_config(set()), refus)
                with open(cfg, encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), content)
                self.assert_refused(refus)
        self.assertEqual(
            self.asked(), [(t("Remove these ~/.ssh/config entries?"), "n")]
        )
        self.play(lambda: self.todo._cleanup_ssh_config(set()), ["o"])
        with open(cfg, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")


class TestLesBauxPerimes(_Base):
    def test_stale_leases_are_cleared_only_on_yes(self):
        lease = '[{"mac-address": "52:54:00:00:00:99", "hostname": "x"}]'
        self.enterContext(
            mock.patch.object(
                qm.subprocess,
                "run",
                lambda argv, **kw: subprocess.CompletedProcess(
                    argv, 0, lease, ""
                ),
            )
        )
        self.todo._qemu_domain_macs = lambda: set()
        for refus in REFUS:
            with self.subTest(refus=refus):
                self.play(self.todo._cleanup_stale_leases, refus)
                self.assertEqual(self.todo.execute.cmds, [])
                self.assert_refused(refus)
        self.assertEqual(self.asked(), [(t("Clear these stale leases?"), "n")])
        # Le fichier de travail s'écrirait dans /tmp : un double le reçoit.
        with mock.patch.object(qm, "open", mock.mock_open(), create=True):
            self.play(self.todo._cleanup_stale_leases, ["yes"])
        [cmd] = self.todo.execute.cmds
        self.assertIn("virbr0.status", cmd)


class TestLeRedimensionnement(_Base):
    """Resize a VM disk, en réduction : la VM ne s'éteint que sur un oui,
    la réduction ne part qu'au nom de la VM tapé, la sauvegarde ne
    s'efface que sur un oui."""

    def setUp(self):
        super().setUp()
        self.state = "shut off"
        self.stopped, self.shrunk = [], []
        todo = self.todo
        todo._qemu_list_vms = lambda *a, **k: None
        todo._qemu_pick_vm = lambda multi=False: VM
        todo._qemu_main_disk = lambda name: f"{IMAGES}/{name}.qcow2"
        todo._qemu_disk_virtual_bytes = lambda disk: 20 << 30
        todo._qemu_disk_sizes = lambda disk: (20 << 30, 5 << 30)
        todo._qemu_domstate = lambda name: self.state
        todo._qemu_shutdown_wait = lambda name: self.stopped.append(name) or 1
        todo._qemu_safe_shrink = lambda n, d, gb: self.shrunk.append(gb) or 1
        self.enterContext(
            mock.patch.object(
                qm.shutil,
                "disk_usage",
                lambda path: types.SimpleNamespace(free=0),
            )
        )

    def resize(self, answers):
        self.todo.execute.cmds.clear()
        return self.play(self.todo._qemu_resize_disk, answers, typed=["-5"])

    def test_the_shrink_goes_only_on_the_vm_name_typed(self):
        # Ctrl+D, comme l'Annuler de la page, vaut un autre nom : l'action
        # s'annule sans exception.
        for answers in ([""], ["o"], ["y"], ["forged-yesno"], [EOFError()]):
            with self.subTest(answers=answers):
                self.assertIsNone(self.resize(answers))
                self.assertEqual(self.shrunk, [])
                self.assertEqual(self.port.answers, [])
        [asked] = [e for e in self.port.events if e.get("kind") == "typed"]
        self.assertEqual(asked["expected"], VM)
        self.assertIn(VM, asked["text"])
        self.resize([VM])
        self.assertEqual(self.shrunk, [15.0])

    def test_a_running_vm_is_shut_down_only_on_yes(self):
        self.state = "running"
        for refus in REFUS:
            with self.subTest(refus=refus):
                self.resize(refus)
                self.assertEqual((self.stopped, self.shrunk), ([], []))
                self.assertEqual(self.todo.execute.cmds[1:], [])
                self.assert_refused(refus)
        # Éteinte pour l'occasion, elle ne redémarre que sur un oui.
        for refus in REFUS:
            with self.subTest(refus=refus):
                self.resize(["oui", VM, *refus])
                self.assertEqual(self.todo.execute.cmds[1:], [])
        self.assertEqual(
            self.asked(),
            [
                (t("The VM must be off. Shut it down and retry?"), "n"),
                (t("Start the VM now?"), "n"),
            ],
        )
        self.todo.execute.cmds.clear()
        self.resize(["o", VM, "o"])
        self.assertTrue(self.todo.execute.cmds[-1].endswith(f"start {VM}"))
        # Une réduction annulée, par un autre nom ou par Ctrl+D, propose
        # aussi le redémarrage, et rien n'est réduit.
        for annule in ("forged-yesno", EOFError()):
            with self.subTest(annule=annule):
                del self.shrunk[:]
                self.resize(["o", annule, "o"])
                self.assertEqual(self.shrunk, [])
                self.assertTrue(
                    self.todo.execute.cmds[-1].endswith(f"start {VM}")
                )

    def test_the_backup_is_deleted_only_on_yes(self):
        bak = os.path.join(
            self.enterContext(tempfile.TemporaryDirectory()), "forged.bak"
        )
        open(bak, "w").close()

        def shrink(name, disk, gb):
            self.todo._shrink_backup = bak
            return True

        self.todo._qemu_safe_shrink = shrink
        for refus in REFUS:
            with self.subTest(refus=refus):
                self.resize([VM, *refus])
                self.assertEqual(self.journal, [])
                self.assert_refused(refus)
        self.assertEqual(self.asked(), [(t("Delete this backup now?"), "n")])
        self.resize([VM, "y"])
        self.assertEqual(self.journal, [["sudo", "rm", "-f", bak]])


class TestLaSauvegardeAvantReduction(_Base):
    """Ctrl+D, ou l'Annuler de la page, à la question de la sauvegarde
    arrête la réduction : ni copie, ni nbd, ni e2fsck."""

    def setUp(self):
        super().setUp()
        self.enterContext(
            mock.patch.object(qm.shutil, "which", lambda b: f"/usr/bin/{b}")
        )
        self.todo._qemu_nbd_connect = lambda disk: self.fail("nbd")

    def test_ctrl_d_stops_the_shrink_with_room_or_without(self):
        gib = 1 << 30
        for (need, free), question, default in (
            ((1 * gib, 9 * gib), "Back up the disk before shrinking?", "y"),
            (
                (9 * gib, 1 * gib),
                "Back up anyway, at the risk of filling the disk?",
                "n",
            ),
        ):
            self.todo._qemu_backup_need_and_free = lambda d: (need, free)
            for answers in (["peut-être", EOFError()], [EOFError()]):
                with self.subTest(question=question, answers=answers):
                    got = self.play(
                        lambda: self.todo._qemu_safe_shrink(VM, "/forged", 1),
                        answers,
                    )
                    self.assertFalse(got)
                    self.assertEqual(self.journal, [])
                    self.assertEqual(
                        set(self.asked()), {(t(question), default)}
                    )
                    self.assertTrue(self.backs())


class TestLArretForce(_Base):
    def test_destroy_runs_only_on_yes(self):
        self.todo._qemu_domname = lambda name: name
        self.todo._qemu_domstate = lambda name: "running"
        clock = types.SimpleNamespace(sleep=lambda s: None)
        for answers in (*REFUS, ["oui"]):
            with self.subTest(answers=answers):
                self.todo.execute.cmds.clear()
                clock.time = itertools.count(0, 500).__next__
                with mock.patch.object(qm, "time", clock):
                    got = self.play(
                        lambda: self.todo._qemu_shutdown_wait(VM), answers
                    )
                destroyed = [
                    c for c in self.todo.execute.cmds if "destroy" in c
                ]
                self.assertEqual(len(destroyed), answers == ["oui"])
                self.assertFalse(got)
        self.assertEqual(
            self.asked(),
            [(t("Graceful shutdown timed out. Force off (destroy)?"), "n")],
        )


class TestLeMaterielGardeSonEtat(_Base):
    """La 3D et le démarrage automatique : l'état actuel est le défaut, que
    l'indice dit ; Ctrl+D le garde, une faute redemande."""

    def test_enter_and_ctrl_d_keep_the_state(self):
        for state in (True, False):
            for answers, expected in (
                ([""], state),
                ([EOFError()], state),
                (["peut-être", ""], state),
                (["peut-être", EOFError()], state),
                (["n"], False),
                (["oui"], True),
            ):
                with self.subTest(state=state, answers=answers):
                    got = self.play(
                        lambda: self.todo._qemu_ask_bool("forged ?", state),
                        answers,
                    )
                    self.assertIs(got, expected)
                    self.assert_refused(answers)
                    defaults = {d for _p, d in self.asked()}
                    self.assertEqual(defaults, {"y" if state else "n"})
                    self.assertTrue(self.backs())


class TestLesStatistiques(_Base):
    SUMMARY = {"total": 2, "ok": 2, "failed": 0, "first_ts": 0}
    SUMMARY.update(last_ts=0, median=60, min=60, max=60, total_secs=120)

    def test_the_history_is_erased_only_on_yes(self):
        from script.todo import qemu_install_monitor as mon

        self.enterContext(
            mock.patch.object(mon, "stats_summary", return_value=self.SUMMARY)
        )
        self.enterContext(mock.patch.object(mon, "stats_by", return_value=[]))
        self.enterContext(
            mock.patch.object(mon, "virsh_domstates", return_value={})
        )
        reset = self.enterContext(
            mock.patch.object(mon, "reset_stats", return_value=2)
        )
        # La boucle finit sur une entrée fermée, après la question comprise.
        for answers in ([], ["r"], *(["r", *r] for r in REFUS)):
            with self.subTest(answers=answers):
                self.play(self.todo._qemu_stats, answers)
                reset.assert_not_called()
        question = "   " + t("Erase %s recorded runs?") % 2
        self.assertEqual(self.asked(), [(question, "n")])
        self.play(self.todo._qemu_stats, ["r", "oui", "0"])
        reset.assert_called_once_with()


class TestLeReseau(_Base):
    def test_vms_are_powered_off_only_on_yes(self):
        self.todo._qemu_network_status = lambda: None
        self.todo._qemu_network_cmd = lambda *a: " ".join(["forged", *a])
        for answers in (*REFUS, ["y"]):
            with self.subTest(answers=answers):
                self.todo.execute.cmds.clear()
                self.play(
                    self.todo._qemu_network_recreate,
                    answers,
                    typed=["", ""],
                )
                [cmd] = self.todo.execute.cmds
                self.assertEqual("--force-off" in cmd, answers == ["y"])
        self.assertEqual(
            self.asked(),
            [(t("Power off VMs that ignore the shutdown?"), "n")],
        )


class TestLesOutilsAInstaller(_Base):
    """libvirt et libguestfs s'installent sur Entrée (défaut oui) ; non,
    une faute puis Ctrl+D et Ctrl+D n'installent rien."""

    NON = (["n"], ["peut-être", EOFError()], [EOFError()])

    def test_libvirt(self):
        self.enterContext(
            mock.patch.object(qm.shutil, "which", lambda b: None)
        )
        self.todo._qemu_warn_libvirt_access = lambda: None
        for answers in self.NON:
            with self.subTest(answers=answers):
                self.assertFalse(
                    self.play(self.todo._qemu_ensure_tools, answers)
                )
                self.assertEqual(self.todo.execute.cmds, [])
        self.play(self.todo._qemu_ensure_tools, [""])
        [cmd] = self.todo.execute.cmds
        self.assertIn("--setup-host", cmd)
        self.assertEqual(
            self.asked()[-1], (t("Install the QEMU/libvirt tools now?"), "y")
        )

    def test_libguestfs(self):
        self.enterContext(
            mock.patch.object(qemu_recover.shutil, "which", lambda b: None)
        )
        self.enterContext(
            mock.patch.object(
                qemu_recover,
                "guestfs_install_cmd",
                lambda: ("forged install libguestfs", "libguestfs"),
            )
        )
        for answers in self.NON:
            with self.subTest(answers=answers):
                got = self.play(self.todo._qemu_recover_ensure_tools, answers)
                self.assertFalse(got)
                self.assertEqual(self.todo.execute.cmds, [])
        self.play(self.todo._qemu_recover_ensure_tools, [""])
        self.assertEqual(self.todo.execute.cmds, ["forged install libguestfs"])
        self.assertEqual(self.asked()[-1], (t("Install libguestfs now?"), "y"))


if __name__ == "__main__":
    unittest.main()
