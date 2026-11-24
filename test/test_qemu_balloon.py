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
  place quand un <memballoon model='none'/> existe.

Les noms et les valeurs sont inventés.
"""

import contextlib
import io
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
