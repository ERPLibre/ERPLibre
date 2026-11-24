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
  l'invité ou échanger l'hôte, et ne lance rien sans o/N.

Les noms et les valeurs sont inventés.
"""

import contextlib
import io
import subprocess
import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import qemu_hardware as hw  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
