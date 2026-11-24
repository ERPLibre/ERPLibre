#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le ballon mémoire virtio : un plafond au-dessus de la RAM, et la RAM
d'une VM allumée déplacée sous ce plafond.

<memory> est le plafond fixé au démarrage, <currentMemory> la cible du
ballon. Le ballon déplace la RAM entre ~0 et le plafond, jamais au-delà.

Ce que ces tests gardent :

- le formulaire matériel sépare RAM et RAM max, et changer la RAM seule ne
  referme plus la marge au-dessus d'elle ;
- un plafond au-dessus de la RAM sans ballon reçoit un ballon, posé en
  place quand un <memballoon model='none'/> existe ;
- la RAM à chaud refuse tout ce qui ferait tuer des processus dans
  l'invité ou échanger l'hôte, et ne lance rien sans o/N ;
- deploy_qemu.py n'écrit la forme « memory=,currentMemory= » qu'avec
  --max-memory, et la commande sans lui reste identique ;
- le champ du formulaire de déploiement va jusqu'à --max-memory.

Les noms et les valeurs sont inventés.
"""

import asyncio
import contextlib
import importlib.util
import io
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import qemu_hardware as hw  # noqa: E402
from script.todo.deploy_form_lib import balloon_max, build_spec  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False


def _deploy_qemu():
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()

NOM = "vm-essai-ballon"


def xml(memory=8192, current=None, balloon="virtio", fpr=True):
    """XML persistant réduit à la mémoire et au ballon, tailles en Mio."""
    current = memory if current is None else current
    ballon = ""
    if balloon is not None:
        attr = " freePageReporting='on'" if fpr else ""
        ballon = f"<memballoon model='{balloon}'{attr}/>"
    return (
        "<domain type='kvm'>"
        f"<name>{NOM}</name>"
        f"<memory unit='KiB'>{memory * 1024}</memory>"
        f"<currentMemory unit='KiB'>{current * 1024}</currentMemory>"
        "<vcpu placement='static'>2</vcpu>"
        f"<devices>{ballon}</devices>"
        "</domain>"
    )


def stats_txt(actual=4096, usable=3072, available=3900, last=1000):
    """Sortie de « virsh dommemstat », tailles en Mio converties en KiB."""
    lignes = [f"actual {actual * 1024}", "swap_in 0", "rss 2000000"]
    if usable is not None:
        lignes += [
            f"unused {usable * 1024}",
            f"available {available * 1024}",
            f"usable {usable * 1024}",
            f"last_update {last}",
        ]
    return "\n".join(lignes) + "\n"


class LeBallonSeLit(unittest.TestCase):
    def test_a_virtio_balloon_is_read_with_its_page_reporting(self):
        st = hw.hw_state(xml())
        self.assertEqual("virtio", st["balloon"])
        self.assertTrue(st["balloon_elem"])
        self.assertTrue(st["free_page_reporting"])

    def test_model_none_is_no_balloon_but_an_element(self):
        """model='none' refuse le ballon ; l'élément existe pourtant, et
        en ajouter un second serait refusé."""
        st = hw.hw_state(xml(balloon="none", fpr=False))
        self.assertEqual("", st["balloon"])
        self.assertTrue(st["balloon_elem"])

    def test_no_element_no_balloon(self):
        st = hw.hw_state(xml(balloon=None))
        self.assertEqual("", st["balloon"])
        self.assertFalse(st["balloon_elem"])
        self.assertFalse(st["free_page_reporting"])

    def test_the_summary_names_the_max_and_the_balloon(self):
        resume = hw.hw_summary(hw.hw_state(xml(16384, 4096)))
        self.assertIn("4 Go (max 16 Go)", resume)
        self.assertIn(f"{hw.t('balloon')} virtio", resume)
        resume = hw.hw_summary(hw.hw_state(xml(balloon=None)))
        self.assertNotIn("max", resume)
        self.assertIn(hw.t("no balloon"), resume)


class LePlanGardeLaMarge(unittest.TestCase):
    def _plan(self, doc, **want):
        return hw.hw_plan(hw.hw_state(doc), want)

    def _memoire(self, plan):
        return [c for e in plan for c in e.get("cmd", ()) if "memory=" in c]

    def test_lowering_the_ram_keeps_the_max(self):
        """Changer la RAM seule garde le plafond : la marge au-dessus d'elle
        reste disponible pour le ballon."""
        plan = self._plan(xml(16384, 8192), ram=4096)
        self.assertEqual(
            ["memory=16384,currentMemory=4096"], self._memoire(plan)
        )

    def test_ram_above_the_max_raises_it(self):
        plan = self._plan(xml(8192), ram=12288)
        self.assertEqual(
            ["memory=12288,currentMemory=12288"], self._memoire(plan)
        )

    def test_raising_only_the_max_keeps_the_ram(self):
        plan = self._plan(xml(8192), max_ram=16384)
        self.assertEqual(
            ["memory=16384,currentMemory=8192"], self._memoire(plan)
        )
        self.assertEqual(1, len(plan), "ballon déjà présent")

    def test_one_command_writes_both_values(self):
        plan = self._plan(xml(8192), ram=4096, max_ram=16384)
        self.assertEqual(
            ["memory=16384,currentMemory=4096"], self._memoire(plan)
        )
        self.assertIn("--define", plan[0]["cmd"])
        self.assertIn("qemu:///system", plan[0]["cmd"])

    def test_a_max_below_the_ram_is_a_skip_with_a_reason(self):
        plan = self._plan(xml(8192), ram=8192, max_ram=4096)
        self.assertEqual(1, len(plan))
        self.assertNotIn("cmd", plan[0])
        self.assertIn(hw.t("below the RAM of the VM"), plan[0]["skip"])

    def test_headroom_without_a_balloon_adds_one(self):
        plan = self._plan(xml(8192, balloon=None), max_ram=16384)
        ballon = [e["cmd"] for e in plan if "--memballoon" in e.get("cmd", ())]
        self.assertEqual(1, len(ballon))
        self.assertIn("--add-device", ballon[0])
        self.assertEqual("model=virtio", ballon[0][-1])

    def test_a_none_balloon_is_edited_in_place(self):
        plan = self._plan(xml(8192, balloon="none"), max_ram=16384)
        ballon = [e["cmd"] for e in plan if "--memballoon" in e.get("cmd", ())]
        self.assertEqual(1, len(ballon))
        self.assertIn("--edit", ballon[0])
        self.assertNotIn("--add-device", ballon[0])

    def test_no_headroom_no_balloon_added(self):
        plan = self._plan(xml(8192, balloon=None), ram=12288)
        self.assertFalse(any("--memballoon" in e.get("cmd", ()) for e in plan))

    def test_the_same_values_change_nothing(self):
        self.assertEqual(
            [], self._plan(xml(16384, 4096), ram=4096, max_ram=16384)
        )

    def test_build_want_defaults_keep_the_headroom(self):
        """_qemu_start_failed appelle build_want en POSITIONNEL, sans plafond :
        retirer la 3D ne doit pas toucher à la mémoire d'une VM à marge."""
        st = hw.hw_state(xml(16384, 4096, balloon=None))
        want = hw.build_want(st, None, None, False, False)
        self.assertEqual(16384, want["max_ram"])
        self.assertEqual([], hw.hw_plan(st, want))

    def test_build_want_reads_the_max_field(self):
        st = hw.hw_state(xml(8192))
        want = hw.build_want(st, "", "4G", 0, 0, max_ram="16G")
        self.assertEqual((4096, 16384), (want["ram"], want["max_ram"]))


class LeReleveDuBallon(unittest.TestCase):
    def test_dommemstat_is_parsed_in_kib(self):
        st = hw.parse_dommemstat(stats_txt())
        self.assertEqual(4096 * 1024, st["actual"])
        self.assertEqual(3072 * 1024, st["usable"])
        self.assertEqual(1000, st["last_update"])

    def test_the_dashed_spelling_becomes_one_key(self):
        st = hw.parse_dommemstat("actual 1024\nlast-update 77\nbruit\n")
        self.assertEqual(77, st["last_update"])

    def test_without_the_guest_driver_there_are_no_guest_stats(self):
        self.assertFalse(
            hw.guest_reports(hw.parse_dommemstat(stats_txt(usable=None)))
        )
        self.assertTrue(hw.guest_reports(hw.parse_dommemstat(stats_txt())))

    def test_a_stale_report_counts_as_silent(self):
        st = hw.parse_dommemstat(stats_txt(last=1000))
        self.assertTrue(hw.guest_reports(st, now=1000 + hw.LIVE_STATS_MAX_AGE))
        self.assertFalse(
            hw.guest_reports(st, now=1001 + hw.LIVE_STATS_MAX_AGE)
        )

    def test_meminfo_available(self):
        texte = "MemTotal: 9000000 kB\nMemAvailable:   2097152 kB\n"
        self.assertEqual(2048, hw.meminfo_available_mib(texte))
        self.assertEqual(0, hw.meminfo_available_mib("MemTotal: 1 kB\n"))


class LaRamAChaud(unittest.TestCase):
    """live_ram_plan : VM de plafond 16 Go, ballon à 4 Go, 1 Go occupé."""

    def _plan(self, want, doc=None, host=8192, **stats):
        st = hw.hw_state(doc or xml(16384, 4096))
        relevé = hw.parse_dommemstat(stats_txt(**stats))
        return hw.live_ram_plan(st, relevé, want, host, now=1000)

    def test_an_increase_within_bounds_is_planned(self):
        plan = self._plan(6144)
        self.assertTrue(plan["ok"], plan["reason"])
        self.assertEqual(
            [
                "virsh",
                "--connect",
                "qemu:///system",
                "setmem",
                NOM,
                "6144M",
                "--live",
                "--config",
            ],
            plan["cmd"],
        )

    def test_no_balloon_is_refused(self):
        plan = self._plan(6144, doc=xml(16384, 4096, balloon="none"))
        self.assertFalse(plan["ok"])
        self.assertNotIn("cmd", plan)
        self.assertEqual(hw.t("this VM has no balloon device"), plan["reason"])

    def test_a_silent_guest_is_refused(self):
        plan = self._plan(6144, usable=None)
        self.assertFalse(plan["ok"])
        self.assertIn(
            hw.t("the guest balloon driver reports no statistics"),
            plan["reason"],
        )

    def test_above_the_max_points_at_the_hardware_form(self):
        plan = self._plan(20480)
        self.assertFalse(plan["ok"])
        self.assertIn(
            hw.t("raise the max with the VM shut off (hardware form)"),
            plan["reason"],
        )

    def test_up_to_the_max_is_allowed(self):
        self.assertTrue(self._plan(16384, host=32768)["ok"])

    def test_below_the_used_memory_plus_margin_is_refused(self):
        """actual 4096 - usable 3072 = 1024 occupés ; plancher 1536."""
        self.assertFalse(self._plan(1535)["ok"])
        self.assertTrue(self._plan(1536)["ok"])

    def test_an_increase_the_host_cannot_cover_is_refused(self):
        """+2048 demandés, marge 512 : il faut 2560 disponibles."""
        self.assertFalse(self._plan(6144, host=2559)["ok"])
        self.assertTrue(self._plan(6144, host=2560)["ok"])

    def test_a_decrease_ignores_the_host_and_warns(self):
        plan = self._plan(2048, host=0)
        self.assertTrue(plan["ok"])
        self.assertTrue(plan["warnings"])

    def test_the_same_size_launches_nothing(self):
        plan = self._plan(4096)
        self.assertFalse(plan["ok"])
        self.assertNotIn("cmd", plan)


class LeMenuAChaud(unittest.TestCase):
    """_qemu_balloon_live : ce qui s'affiche, ce qui se lance, et quand."""

    def _todo(self, domstate="running", releves=None, doc=None, rc=0):
        todo = TODO.__new__(TODO)
        todo._qemu_domstate = lambda name: domstate
        todo._qemu_dumpxml = lambda name, inactive=True: (
            doc or xml(16384, 4096)
        )
        suite = iter(releves or [stats_txt(last=10**10)])
        dernier = {"txt": ""}

        def releve(name):
            dernier["txt"] = next(suite, dernier["txt"])
            return dernier["txt"]

        todo._qemu_dommemstat_raw = releve
        todo._qemu_host_mem_available = lambda: 8192
        todo.launched = []
        todo.execute = mock.Mock()

        def lance(cmd, **kw):
            todo.launched.append(cmd)
            return rc

        todo.execute.exec_command_live = lance
        return todo

    def _run(self, todo, answers, now=10**10):
        it = iter(answers)
        out = io.StringIO()
        with (
            mock.patch("builtins.input", lambda *a: next(it, "")),
            mock.patch("script.todo.qemu_manage.time.sleep"),
            mock.patch("script.todo.qemu_manage.time.time", return_value=now),
            contextlib.redirect_stdout(out),
        ):
            todo._qemu_balloon_live([NOM])
        return out.getvalue()

    def test_a_shut_off_vm_is_left_alone(self):
        todo = self._todo(domstate="shut off")
        out = self._run(todo, ["6G", "o"])
        self.assertEqual([], todo.launched)
        self.assertIn(NOM, out)

    def test_it_shows_then_runs_setmem_on_yes(self):
        todo = self._todo(
            releves=[
                stats_txt(last=10**10),
                stats_txt(actual=6144, last=10**10),
            ]
        )
        out = self._run(todo, ["6G", "o"])
        self.assertEqual(1, len(todo.launched))
        self.assertIn("setmem", todo.launched[0])
        self.assertIn("6144M --live --config", todo.launched[0])
        self.assertIn(hw.t("Will execute:"), out)
        self.assertIn(hw.t("Balloon now at:") + " 6 Go", out)

    def test_a_failed_setmem_is_reported_not_reread(self):
        """Un setmem au code non nul s'affiche en échec : relire le ballon
        afficherait l'ancienne valeur comme si elle allait suivre."""
        todo = self._todo(rc=1)
        out = self._run(todo, ["6G", "o"])
        self.assertEqual(1, len(todo.launched))
        self.assertIn(hw.t("Command failed."), out)
        self.assertNotIn(hw.t("Balloon now at:"), out)

    def test_a_failed_period_does_not_blame_the_guest(self):
        todo = self._todo(releves=[stats_txt(usable=None)], rc=1)
        out = self._run(todo, ["o", "6G", "o"])
        self.assertEqual(1, len(todo.launched))
        self.assertIn(hw.t("Command failed."), out)
        self.assertNotIn(hw.t("still no statistics from the guest:"), out)

    def test_the_raw_reader_is_not_the_vm_table_one(self):
        """Le chemin réel, sans remplacer de méthode : seul subprocess.run
        est simulé. Deux méthodes du même nom dans la classe se
        masqueraient, et le relevé arriverait sous une autre forme."""
        todo = TODO.__new__(TODO)
        todo._qemu_host_mem_available = lambda: 8192
        todo.launched = []
        todo.execute = mock.Mock()

        def lance(cmd, **kw):
            todo.launched.append(cmd)
            return 0

        todo.execute.exec_command_live = lance
        doc = xml(16384, 4096)

        def faux_run(argv, **kw):
            if "domstate" in argv:
                sortie = "running\n"
            elif "dumpxml" in argv:
                sortie = doc
            elif "dommemstat" in argv:
                sortie = stats_txt(last=10**10)
            else:
                sortie = ""
            return subprocess.CompletedProcess(argv, 0, sortie, "")

        with mock.patch(
            "script.todo.qemu_manage.subprocess.run", side_effect=faux_run
        ) as run:
            out = self._run(todo, ["6G", "o"])
        self.assertEqual(1, len(todo.launched))
        self.assertIn("setmem", todo.launched[0])
        self.assertIn(hw.t("Balloon now at:"), out)
        lances = [c.args[0] for c in run.call_args_list]
        self.assertFalse(
            [a for a in lances if "dommemstat" in a and "--period" in a]
        )

    def test_no_means_nothing_runs(self):
        todo = self._todo()
        self._run(todo, ["6G", "n"])
        self.assertEqual([], todo.launched)

    def test_a_refused_target_runs_nothing(self):
        todo = self._todo()
        out = self._run(todo, ["32G", "o"])
        self.assertEqual([], todo.launched)
        self.assertIn(hw.t("above the RAM max of the VM"), out)

    def test_a_silent_guest_is_offered_the_period_first(self):
        todo = self._todo(releves=[stats_txt(usable=None)])
        self._run(todo, ["n"])
        self.assertEqual([], todo.launched)

    def test_still_silent_after_arming_is_refused(self):
        todo = self._todo(releves=[stats_txt(usable=None)])
        out = self._run(todo, ["o", "6G", "o"])
        self.assertEqual(1, len(todo.launched))
        self.assertIn("dommemstat", todo.launched[0])
        self.assertIn("--period 5 --live", todo.launched[0])
        self.assertIn(hw.t("still no statistics from the guest:"), out)

    def test_armed_then_reporting_goes_on(self):
        todo = self._todo(
            releves=[
                stats_txt(usable=None),
                stats_txt(last=10**10),
                stats_txt(actual=6144, last=10**10),
            ]
        )
        self._run(todo, ["o", "6G", "o"])
        self.assertEqual(2, len(todo.launched))
        self.assertIn("setmem", todo.launched[1])

    def test_the_lower_of_live_and_persistent_max_bounds(self):
        """La définition, modifiée VM allumée, peut porter un plafond plus
        bas que celui du démarrage : « --config » doit y tenir aussi."""
        todo = self._todo()
        todo._qemu_dumpxml = lambda name, inactive=True: (
            xml(8192, 4096) if inactive else xml(16384, 4096)
        )
        out = self._run(todo, ["12G", "o"])
        self.assertEqual([], todo.launched)
        self.assertIn(hw.t("above the RAM max of the VM"), out)

    def test_the_menu_offers_it_next_to_the_hardware(self):
        todo = TODO.__new__(TODO)
        todo._qemu_list_domains = lambda: [NOM]
        vus = []
        todo._qemu_balloon_live = lambda names: vus.append(list(names))
        it = iter(["all", "4"])
        with (
            mock.patch("builtins.input", lambda *a: next(it, "")),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            todo._qemu_change_state()
        self.assertEqual([[NOM]], vus)
        self.assertIn(
            hw.t("Change RAM of a running VM (balloon)"), out.getvalue()
        )


class LeBallonSeSuit(unittest.TestCase):
    """Après « setmem », l'écran suit « actual » jusqu'à la cible : le pilote
    invité rend la mémoire page par page, un relevé pris deux secondes après
    la commande montre une valeur en chemin."""

    def test_the_state_of_a_balloon_on_its_way(self):
        etat = hw.balloon_wait_state
        self.assertEqual("done", etat(16384, 16384, 0, 0))
        self.assertEqual("done", etat(16384, 16384 + 16, 0, 0))
        self.assertEqual("moving", etat(16384, 20000, 0, 10))
        self.assertEqual("stalled", etat(16384, 20000, hw.BALLOON_STALL_S, 10))
        self.assertEqual(
            "timeout", etat(16384, 20000, 0, hw.BALLOON_WAIT_MAX_S)
        )
        # La cible l'emporte : atteinte au dernier relevé, elle est atteinte.
        self.assertEqual(
            "done",
            etat(16384, 16384, hw.BALLOON_STALL_S, hw.BALLOON_WAIT_MAX_S),
        )

    def _follow(self, valeurs, want=16384, sleep=None):
        todo = TODO.__new__(TODO)
        suite = iter(valeurs)
        dernier = {"txt": ""}

        def releve(name):
            v = next(suite, None)
            if v is not None:
                dernier["txt"] = (
                    "" if v == "vide" else stats_txt(actual=v, last=10**10)
                )
            return dernier["txt"]

        todo._qemu_dommemstat_raw = releve
        dodo = mock.Mock(side_effect=sleep)
        out = io.StringIO()
        with (
            mock.patch("script.todo.qemu_manage.time.sleep", dodo),
            contextlib.redirect_stdout(out),
        ):
            todo._qemu_balloon_follow(NOM, want)
        return out.getvalue(), dodo.call_count

    def test_it_waits_until_the_target(self):
        out, dodos = self._follow([24000, 22000, 19000, 16384])
        self.assertEqual(3, dodos)
        self.assertIn(hw.t("Balloon now at:") + " 16 Go", out)
        self.assertNotIn("⚠", out)

    def test_a_balloon_that_stops_moving_is_reported(self):
        out, dodos = self._follow([24000, 20000])
        self.assertEqual(1 + hw.BALLOON_STALL_S, dodos)
        self.assertIn(hw.fmt_mib(20000), out)
        self.assertIn(hw.t("the balloon stopped short of the target"), out)

    def test_a_slow_balloon_is_left_moving_after_the_delay(self):
        out, dodos = self._follow(range(90000, 20000, -100))
        self.assertEqual(hw.BALLOON_WAIT_MAX_S, dodos)
        self.assertIn(hw.t("the balloon keeps moving toward the target"), out)

    def test_ctrl_c_only_leaves_the_screen(self):
        out, dodos = self._follow(
            [24000, 22000], sleep=[None, KeyboardInterrupt]
        )
        self.assertEqual(2, dodos)
        self.assertIn(hw.t("Balloon now at:") + " " + hw.fmt_mib(22000), out)
        self.assertIn(hw.t("the balloon keeps moving toward the target"), out)

    def test_an_unreadable_balloon_stops_the_wait(self):
        out, dodos = self._follow(["vide"])
        self.assertEqual(0, dodos)
        self.assertIn(hw.t("Balloon size unreadable."), out)

    def test_outside_a_terminal_only_the_last_value_prints(self):
        out, _ = self._follow([24000, 22000, 16384])
        self.assertNotIn("\r", out)
        self.assertEqual(1, out.count(hw.t("Balloon now at:")))


class LesInvites(unittest.TestCase):
    """Repli sans Textual : le plafond n'est demandé qu'à bon escient."""

    def _want(self, doc, answers):
        todo = TODO.__new__(TODO)
        it = iter(answers)
        with (
            mock.patch("builtins.input", lambda *a: next(it, "")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return todo._qemu_hw_prompts(
                [hw.hw_state(doc)], "", ["network:default"]
            )[NOM]

    def test_a_typed_ram_asks_for_the_max(self):
        want = self._want(xml(8192), ["", "4G", "16G"])
        self.assertEqual((4096, 16384), (want["ram"], want["max_ram"]))

    def test_an_empty_ram_on_a_vm_without_headroom_asks_nothing_more(self):
        # vCPU, RAM, puis 3D refusée (pas d'écran), démarrage auto, CPU.
        want = self._want(xml(8192), ["", "", "o"])
        self.assertEqual(8192, want["max_ram"])
        self.assertTrue(want["autostart"])


class DeployQemu(unittest.TestCase):
    def _args(self, **extra):
        base = dict(
            name="vm-a",
            memory=4096,
            vcpus=2,
            arch="amd64",
            network="network=default,model=virtio",
            graphics="none",
            desktop=False,
            gpu="off",
            gpu_node="",
            attach_console=False,
            bios=False,
        )
        base.update(extra)
        return SimpleNamespace(**base)

    def _cmd(self, args):
        lances = []

        class FauxRunner:
            dry_run = False
            use_sudo = False

            def run(self, cmd, *, privileged=False, check=True, capture=False):
                lances.append(list(cmd))
                return (0, "") if capture else None

        with (
            mock.patch.object(DQ, "host_arch", return_value="amd64"),
            mock.patch.object(DQ, "kvm_available", return_value=True),
            mock.patch.object(DQ, "os") as faux_os,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            faux_os.getuid.return_value = 1000
            DQ.virt_install(
                args,
                Path("/tmp/d.qcow2"),
                Path("/tmp/s.iso"),
                "ubuntu26.04",
                FauxRunner(),
            )
        return lances[0]

    def test_without_max_memory_the_command_is_unchanged(self):
        """Absent, None ou égal à --memory : la même commande, octet pour
        octet, avec « --memory 4096 »."""
        base = self._cmd(self._args())
        self.assertEqual(base, self._cmd(self._args(max_memory=None)))
        self.assertEqual(base, self._cmd(self._args(max_memory=4096)))
        self.assertEqual("4096", base[base.index("--memory") + 1])
        self.assertNotIn("--memballoon", base)

    def test_with_max_memory_both_values_and_a_balloon(self):
        cmd = self._cmd(self._args(max_memory=16384))
        self.assertEqual(
            "memory=16384,currentMemory=4096", cmd[cmd.index("--memory") + 1]
        )
        self.assertEqual("model=virtio", cmd[cmd.index("--memballoon") + 1])
        self.assertEqual(1, cmd.count("--memory"))

    def test_memory_args(self):
        self.assertEqual(["--memory", "2048"], DQ.memory_args(2048))
        self.assertEqual(["--memory", "2048"], DQ.memory_args(2048, 1024))

    def test_the_option_is_parsed_and_documented(self):
        p = DQ.build_parser()
        self.assertEqual(
            16384, p.parse_args(["--max-memory", "16384"]).max_memory
        )
        self.assertIsNone(p.parse_args([]).max_memory)
        aide = p.format_help()
        self.assertIn("--max-memory", aide)
        self.assertIn("1,6 %", aide)

    def test_a_max_below_the_memory_is_an_argparse_error(self):
        res = subprocess.run(
            [
                sys.executable,
                str(RACINE / "script/qemu/deploy_qemu.py"),
                "--distro",
                "ubuntu",
                "--name",
                "vm-a",
                "--memory",
                "4096",
                "--max-memory",
                "2048",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(2, res.returncode, res.stdout + res.stderr)
        self.assertIn("--max-memory", res.stderr)


class LeFormulaireDeDeploiement(unittest.TestCase):
    def test_the_field_is_validated_against_every_vm(self):
        vms = [{"ram": 2048}, {"ram": 4096}]
        self.assertEqual((0, ""), balloon_max("", vms))
        self.assertEqual((8192, ""), balloon_max("8G", vms))
        self.assertEqual((4096, ""), balloon_max("4096", vms))
        self.assertEqual(0, balloon_max("2G", vms)[0])
        self.assertTrue(balloon_max("2G", vms)[1])
        self.assertTrue(balloon_max("beaucoup", vms)[1])

    def test_the_field_counts_the_desktop_floor(self):
        """Comparé à la RAM que recevra la VM, plancher d'un bureau
        compris : un plafond accepté ici est celui que la commande garde."""
        vms = [{"ram": 1024, "desktop": "gnome"}]
        self.assertEqual((2048, ""), balloon_max("2G", vms))
        self.assertTrue(balloon_max("2G", vms, 4096)[1])
        self.assertEqual((8192, ""), balloon_max("8G", vms, 4096))
        # Type commun : une VM qui ne porte pas le sien prend celui-là.
        self.assertTrue(balloon_max("2G", [{"ram": 1024}], 4096, "gnome")[1])
        self.assertFalse(balloon_max("2G", [{"ram": 1024}], 4096)[1])

    def test_the_cli_asks_until_the_value_is_valid(self):
        todo = TODO.__new__(TODO)
        vms = [{"ram": 4096, "desktop": ""}]
        it = iter(["2G", "beaucoup", "8G"])
        with (
            mock.patch("builtins.input", lambda *a: next(it)),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(8192, todo._qemu_ask_max_ram(vms))
        self.assertIn(
            hw.t("RAM max (balloon) is below the RAM of a VM"),
            out.getvalue(),
        )
        self.assertIn(
            hw.t("RAM max (balloon): unreadable value"), out.getvalue()
        )

    def test_the_cli_empty_answer_keeps_the_ram(self):
        todo = TODO.__new__(TODO)
        with (
            mock.patch("builtins.input", lambda *a: ""),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(0, todo._qemu_ask_max_ram([{"ram": 4096}]))

    def test_the_spec_carries_it(self):
        form = {
            "res_label": "x1",
            "ssh_key": "",
            "install": None,
            "add_ssh_config": True,
            "parallelism": 1,
        }
        self.assertEqual(0, build_spec([], [], form)["max_ram"])
        form["max_ram"] = 8192
        self.assertEqual(8192, build_spec([], [], form)["max_ram"])

    def _parts(self, max_ram=None, ram=4096, desktop=""):
        todo = TODO.__new__(TODO)
        # L'empreinte du mot de passe est salée, et le cache dépend de
        # l'hôte : deux commandes ne se comparent qu'une fois les deux figés.
        todo._qemu_vm_password_hash = lambda spec: ""
        todo._qemu_cache_active = lambda: False
        vm = {
            "name": "vm-a",
            "distro": "ubuntu",
            "version": "24.04",
            "arch": "amd64",
            "ram": ram,
            "vcpus": 2,
            "disk": "20G",
            "desktop": desktop,
        }
        spec = {"vms": [vm], "install": None, "ssh_key": "", "vm_tools": ()}
        if max_ram is not None:
            spec["max_ram"] = max_ram
        return todo._qemu_deploy_parts_for(vm, spec, dry_run=True)

    def test_it_reaches_max_memory(self):
        parts = self._parts(8192)
        self.assertEqual("8192", parts[parts.index("--max-memory") + 1])

    def test_without_it_the_command_is_unchanged(self):
        base = self._parts()
        self.assertNotIn("--max-memory", base)
        self.assertEqual(base, self._parts(0))
        self.assertEqual(base, self._parts(4096))

    def test_the_desktop_floor_counts(self):
        """Un bureau monte la RAM à son plancher : un plafond qui ne le
        dépasse pas ne donne aucune marge, donc aucune option."""
        plancher = TODO.QEMU_DESKTOP_MIN_RAM_MB
        parts = self._parts(plancher, ram=1024, desktop="gnome")
        self.assertNotIn("--max-memory", parts)


@unittest.skipUnless(TEXTUAL, "Textual absent")
class LeChampDuFormulaire(unittest.TestCase):
    def _monter(self, valeur):
        from textual.widgets import Input, SelectionList

        from script.todo.qemu_deploy_form import run_deploy_form

        todo = TODO.__new__(TODO)
        todo._qemu_list_domains = lambda: []
        todo._qemu_branch_list = lambda: ["develop", "master"]
        ctx = todo._qemu_form_context(todo._qemu_import_module())
        vu = {}

        async def scenario():
            app = run_deploy_form(ctx, run_app=False)
            async with app.run_test(size=(220, 70)) as pilote:
                await pilote.pause()
                liste = app.query_one(SelectionList)
                liste.select(liste.get_option_at_index(0).value)
                await pilote.pause()
                app.query_one("#f_max_ram", Input).value = valeur
                await pilote.pause()
                vu["form"] = app._form_values()
                vu["ram"] = max(vm["ram"] for vm in app.vms)
                notes = []
                app.notify = lambda msg, **kw: notes.append(msg)
                app.action_deploy()
                vu["notes"] = notes
                vu["spec"] = app._result["spec"]

        asyncio.run(scenario())
        return vu

    def test_the_value_reaches_the_form_values(self):
        vu = self._monter("64G")
        self.assertEqual(65536, vu["form"]["max_ram"])

    def test_a_max_below_the_ram_blocks_the_deploy(self):
        vu = self._monter("1")
        self.assertIsNone(vu["spec"])
        self.assertTrue(
            any(
                hw.t("RAM max (balloon) is below the RAM of a VM") in n
                for n in vu["notes"]
            ),
            vu["notes"],
        )


if __name__ == "__main__":
    unittest.main()
