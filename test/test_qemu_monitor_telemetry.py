#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Barre de télémétrie du suivi d'installation : CPU, RAM, disque.

La RAM manquait, et son absence a coûté : une compilation mobile s'est fait
tuer par le noyau sur une VM de 12 Go sans swap, pendant que le suivi affichait
sereinement le CPU et le disque. L'épuisement mémoire ne se voit nulle part
ailleurs — le disque va bien, la charge CPU aussi, et la machine meurt.

Ce qui se vérifie ici : le chiffre lu est celui que le noyau dit pouvoir
rendre, le swap n'occupe la barre que s'il existe, et une lecture impossible
laisse la barre utile au lieu de la vider.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "script/todo"))
import qemu_install_monitor as m  # noqa: E402

GB = 1 << 30


class TestHostMem(unittest.TestCase):
    def test_it_reads_the_real_proc(self):
        total, avail, sw_total, sw_free = m._host_mem()
        self.assertGreater(total, 0, "aucune RAM lue dans /proc/meminfo")
        self.assertLessEqual(avail, total)
        self.assertLessEqual(sw_free, sw_total)

    def test_it_reports_what_the_kernel_can_give_back(self):
        """« MemAvailable » et non « MemFree » : sur une machine qui travaille,
        MemFree est presque nul parce que le cache occupe le reste, et
        alarmerait pour rien."""
        proc = (
            "MemTotal:       12000000 kB\n"
            "MemFree:          100000 kB\n"
            "MemAvailable:    8000000 kB\n"
            "SwapTotal:             0 kB\n"
            "SwapFree:              0 kB\n"
        )
        with mock.patch("builtins.open", mock.mock_open(read_data=proc)):
            total, avail, _, _ = m._host_mem()
        self.assertEqual(avail, 8000000 * 1024)
        self.assertEqual(total, 12000000 * 1024)

    def test_an_unreadable_proc_gives_zeros_not_a_crash(self):
        """Le suivi tourne pendant une heure d'installation : il ne meurt pas
        parce qu'une lecture a échoué."""
        with mock.patch("builtins.open", side_effect=OSError):
            self.assertEqual(m._host_mem(), (0, 0, 0, 0))

    def test_a_malformed_line_is_not_fatal(self):
        with mock.patch(
            "builtins.open", mock.mock_open(read_data="MemTotal: beaucoup\n")
        ):
            self.assertEqual(m._host_mem(), (0, 0, 0, 0))


class TestMemSegment(unittest.TestCase):
    def test_the_used_share_is_total_minus_available(self):
        got = m._mem_tele(12 * GB, 3 * GB, 0, 0)
        self.assertIn("9.0G/12.0G", got)
        self.assertIn("(75%)", got)

    def test_the_available_figure_is_shown_as_such(self):
        self.assertIn("3.0G", m._mem_tele(12 * GB, 3 * GB, 0, 0))

    def test_swap_appears_only_when_the_machine_has_some(self):
        """Un « swap 0/0 » occuperait la barre pour ne rien dire. Mais dès
        qu'il existe, il est montré même à zéro : une machine qui commence à
        échanger explique une lenteur, et c'est ce qu'on cherche ici."""
        self.assertNotIn("swap", m._mem_tele(12 * GB, 3 * GB, 0, 0))
        self.assertIn(
            "swap 0K/4.0G", m._mem_tele(12 * GB, 3 * GB, 4 * GB, 4 * GB)
        )
        self.assertIn(
            "swap 1.0G/4.0G", m._mem_tele(12 * GB, 3 * GB, 4 * GB, 3 * GB)
        )

    def test_nothing_read_means_no_segment_not_a_zero_segment(self):
        """La barre garde alors le CPU et le disque, qui eux ont répondu."""
        self.assertEqual(m._mem_tele(0, 0, 0, 0), "")

    def test_more_available_than_total_does_not_show_negative_use(self):
        """Cas absurde mais possible entre deux lectures : on ne veut pas
        « -1.0G » dans la barre."""
        self.assertIn("0K/12.0G", m._mem_tele(12 * GB, 13 * GB, 0, 0))


class TestTheRealBar(unittest.TestCase):
    """La barre telle que le suivi la construit, sans lancer la TUI."""

    def setUp(self):
        try:
            import textual  # noqa: F401
        except ImportError:
            self.skipTest("textual absent de ce venv")
        self.tmp = tempfile.TemporaryDirectory()
        log = Path(self.tmp.name) / "vm-a.log"
        log.write_text("== installation ==\n")
        manifest = Path(self.tmp.name) / "session.json"
        manifest.write_text(
            json.dumps(
                {
                    "branch": "develop",
                    "started": 0,
                    "vms": [
                        {
                            "name": "vm-a",
                            "ip": "192.168.123.2",
                            "log": str(log),
                            "ssh": "ssh erplibre@192.168.123.2",
                        }
                    ],
                }
            )
        )
        self.app = m.run_monitor(str(manifest), run_app=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_bar_carries_the_three_resources(self):
        bar = self.app._collect_tele()
        self.assertIn("CPU", bar)
        self.assertIn("RAM", bar)
        self.assertIn("💽", bar)

    def test_ram_sits_between_cpu_and_disk(self):
        """L'ordre est celui du coût : le CPU se voit ailleurs, la RAM nulle
        part, le disque partout."""
        bar = self.app._collect_tele()
        self.assertLess(bar.index("CPU"), bar.index("RAM"))
        self.assertLess(bar.index("RAM"), bar.index("💽"))

    def test_the_bar_survives_a_mute_proc(self):
        with mock.patch.object(m, "_host_mem", return_value=(0, 0, 0, 0)):
            bar = self.app._collect_tele()
        self.assertIn("CPU", bar)
        self.assertIn("💽", bar)
        self.assertNotIn("RAM", bar)


if __name__ == "__main__":
    unittest.main()
