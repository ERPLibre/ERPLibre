#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Tableau des infos avancées : RAM utilisée, uptime, largeur.

Deux colonnes ont changé de sens. « RAM » disait l'allocation, elle dit
maintenant l'usage — sur un hyperviseur, savoir qu'une VM de 32 Go n'en occupe
que 4,7 décide s'il reste de la place pour la suivante. Et l'uptime est apparu :
libvirt ne l'expose nulle part, mais le processus QEMU du domaine est né avec
lui.

Ce que ces tests gardent : la formule de la RAM, calibrée contre le « free » de
deux VM réelles, et la largeur de la ligne — un tableau qui déborde de 80
colonnes se replie et devient illisible.
"""

import io
import contextlib
import subprocess
import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

# Sortie réelle de « virsh dommemstat » sur la VM de migration, en KiO. Le
# « free » de l'invité disait alors : total 11955, used 1216.
DOMMEMSTAT = """actual 12582912
swap_in 0
swap_out 0
major_fault 0
minor_fault 0
unused 1197056
available 12242432
usable 11027456
last_update 1787359366
disk_caches 8211456
"""


class TestUptimeFormat(unittest.TestCase):
    def test_seconds_then_minutes_then_hours_then_days(self):
        self.assertEqual("45s", TODO._fmt_uptime(45))
        self.assertEqual("12m", TODO._fmt_uptime(12 * 60 + 30))
        self.assertEqual("19h55", TODO._fmt_uptime(19 * 3600 + 55 * 60))
        self.assertEqual("10j13h", TODO._fmt_uptime(10 * 86400 + 13 * 3600))

    def test_it_never_exceeds_six_characters(self):
        """La colonne fait six caractères : au-delà, le tableau se décale."""
        for secs in (0, 59, 60, 3599, 3600, 86399, 86400, 400 * 86400):
            self.assertLessEqual(len(TODO._fmt_uptime(secs)), 6, secs)

    def test_precision_drops_as_the_duration_grows(self):
        """Personne ne lit les secondes d'un uptime de dix jours."""
        self.assertNotIn("s", TODO._fmt_uptime(19 * 3600))
        self.assertNotIn("m", TODO._fmt_uptime(10 * 86400))


class TestMemStat(unittest.TestCase):
    def _stat(self, out):
        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, out, ""),
        ):
            return TODO._qemu_dommemstat("vm")

    def test_used_is_available_minus_usable(self):
        """Calibré contre le « free » de deux VM : 1186 contre 1216 Mo lus dans
        l'invité, et 4831 contre 4838 sur l'autre. « available - unused »
        donnait 10,8 Go pour une VM qui en occupait 1,2 — il compte le cache.
        """
        used, total = self._stat(DOMMEMSTAT)
        self.assertAlmostEqual(used / 1024, 1186, delta=5)
        self.assertAlmostEqual(total / 1024, 11955, delta=5)

    def test_a_stopped_vm_gives_zero_without_crashing(self):
        used, total = self._stat("")
        self.assertEqual((0, 0), (used, total))

    def test_it_survives_virsh_failing(self):
        with mock.patch("subprocess.run", side_effect=OSError):
            self.assertEqual((0, 0), TODO._qemu_dommemstat("vm"))

    def test_missing_usable_is_not_taken_for_zero_use(self):
        """Sans « usable », on ne sait pas : mieux vaut ne rien dire que
        d'annoncer une VM qui n'utiliserait rien."""
        used, total = self._stat("available 12242432\nunused 1197056\n")
        self.assertEqual(0, used)
        self.assertGreater(total, 0)

    def test_it_asks_for_a_collection_period_first(self):
        """Sans période, le ballon ne rafraîchit rien : une VM qui occupait
        4,8 Go en annonçait 490 Mo — vécu. « --live » ne touche pas le XML."""
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess([], 0, DOMMEMSTAT, "")

        with mock.patch("subprocess.run", side_effect=fake_run):
            TODO._qemu_dommemstat("vm")
        self.assertIn("--period", calls[0])
        self.assertIn("--live", calls[0])


class TestDomainUptime(unittest.TestCase):
    def test_it_reads_the_age_of_the_qemu_process(self):
        outs = [
            subprocess.CompletedProcess([], 0, "1137455\n", ""),
            subprocess.CompletedProcess([], 0, "  1195\n", ""),
        ]
        with mock.patch("subprocess.run", side_effect=outs):
            self.assertEqual(1195, TODO._qemu_domain_uptime("vm"))

    def test_the_pattern_ends_with_a_comma(self):
        """« guest=vm, » et non « guest=vm » : sinon « vm » matcherait aussi
        « vm-2 », et l'uptime affiché serait celui d'une autre machine."""
        seen = {}

        def fake_run(cmd, **kw):
            seen.setdefault("cmd", cmd)
            return subprocess.CompletedProcess([], 0, "", "")

        with mock.patch("subprocess.run", side_effect=fake_run):
            TODO._qemu_domain_uptime("vm")
        self.assertIn("guest=vm,", seen["cmd"])

    def test_a_stopped_domain_has_no_uptime(self):
        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess([], 1, "", ""),
        ):
            self.assertIsNone(TODO._qemu_domain_uptime("vm"))


class TestTheTable(unittest.TestCase):
    def _render(self, uptime=1195, mem=(1214 * 1024, 11955 * 1024)):
        todo = TODO.__new__(TODO)
        todo._qemu_list_domains = lambda: ["erplibre-ubuntu-2604-gnome"]
        todo._qemu_domstate = lambda n: "running"
        todo._qemu_dominfo = staticmethod(lambda n: (8, 12 * 1024 * 1024))
        todo._qemu_main_disk = lambda n: "/var/lib/libvirt/images/x.qcow2"
        todo._qemu_disk_sizes = staticmethod(
            lambda d: (65 * (1 << 30), 62 * (1 << 30))
        )
        todo._qemu_dommemstat = staticmethod(lambda n: mem)
        todo._qemu_domain_uptime = staticmethod(lambda n: uptime)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            todo._qemu_list_vms_advanced()
        return buf.getvalue()

    def test_every_line_fits_in_eighty_columns(self):
        """Le tableau est lu dans un terminal : au-delà de 80, il se replie."""
        for line in self._render().splitlines():
            if line.startswith("Stockage") or not line.strip():
                continue
            self.assertLessEqual(len(line), 80, line)

    def test_ram_shows_use_over_allocation(self):
        out = self._render()
        self.assertIn("1.2G/12G", out)

    def test_the_uptime_column_is_there(self):
        out = self._render()
        self.assertIn("Uptime", out)
        self.assertIn("19m", out)

    def test_a_vm_without_stats_shows_a_dash_not_a_zero(self):
        """« 0.0G/12G » ferait croire à une VM au repos ; « -/12G » dit qu'on
        ne sait pas."""
        out = self._render(uptime=None, mem=(0, 0))
        self.assertIn("-/12G", out)
        self.assertNotIn("0.0G/12G", out)

    def test_the_full_vm_name_survives_when_it_fits(self):
        """C'est le nom qui distingue les machines : le tronquer trop tôt les
        rend indiscernables."""
        self.assertIn("erplibre-ubuntu-2604-gnome", self._render())


if __name__ == "__main__":
    unittest.main()
