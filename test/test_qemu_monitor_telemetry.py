#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Barre de télémétrie du suivi d'installation : CPU, RAM, disque.

L'épuisement mémoire ne se voit nulle part ailleurs : un processus que le
noyau tue faute de RAM, sur un hôte sans swap, laisse le CPU et le disque au
vert. La barre porte donc la RAM entre les deux.

Ce qui se vérifie ici : le chiffre lu est celui que le noyau dit pouvoir
rendre, le swap n'occupe la barre que s'il existe, le disque se mesure même
quand le dossier des images n'existe pas encore, et une lecture impossible
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


class TestLogSilence(unittest.TestCase):
    """Une installation morte et une qui travaille portent le même sablier.

    Une installation dont la session ssh est tombée meurt sans marqueur de
    sortie, et garde « ⏳ » indéfiniment. Le marqueur manque dans les deux
    cas : seule la date d'écriture du journal les sépare.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "vm.log"
        self.log.write_text("== installation ==\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_fresh_log_is_not_silent(self):
        self.assertLess(m.log_idle(str(self.log)), 5)

    def test_an_old_log_reports_its_age(self):
        import os
        import time

        old = time.time() - 3000
        os.utime(self.log, (old, old))
        self.assertAlmostEqual(m.log_idle(str(self.log)), 3000, delta=5)

    def test_a_missing_log_is_not_reported_as_silent(self):
        """-1 plutôt que 0 : « absent » n'est pas « à l'instant », et surtout
        pas « silencieux depuis toujours »."""
        self.assertEqual(m.log_idle("/nonexistent/erplibre.log"), -1.0)
        self.assertEqual(m.state_mark("⏳", -1.0), "⏳")

    def test_below_the_threshold_the_cell_stays_bare(self):
        """Plusieurs étapes sont muettes quelques minutes — un téléchargement
        d'Android Studio, une compilation dont la sortie va ailleurs."""
        self.assertEqual(m.state_mark("⏳", 0), "⏳")
        self.assertEqual(m.state_mark("⏳", m.IDLE_HINT_SECS), "⏳")

    def test_above_the_threshold_the_cell_says_how_long(self):
        mark = m.state_mark("⏳", 2900)
        self.assertNotEqual(mark, "⏳")
        self.assertIn("48", mark)

    def test_the_threshold_clears_the_longest_measured_silence(self):
        """Mesuré : le téléchargement d'Android Studio reste ~5 min sans une
        ligne. Un seuil en dessous transformerait chaque installation en alerte,
        et l'alerte cesserait d'être lue."""
        studio_download = 5 * 60
        self.assertGreater(m.IDLE_HINT_SECS, studio_download)
        # Et pas si haut qu'une installation morte passe la demi-heure.
        self.assertLessEqual(m.IDLE_HINT_SECS, 1200)


class TestDiskSegment(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_an_existing_dir_is_its_own_ancestor(self):
        self.assertEqual(m._existing_ancestor(self.tmp.name), self.tmp.name)

    def test_a_missing_dir_climbs_to_what_exists(self):
        absent = Path(self.tmp.name) / "libvirt" / "images"
        self.assertEqual(m._existing_ancestor(str(absent)), self.tmp.name)

    def test_the_root_ends_the_climb(self):
        self.assertEqual(m._existing_ancestor("/"), "/")
        self.assertEqual(m._existing_ancestor(""), "/")

    def test_a_missing_dir_measures_the_filesystem_it_will_live_on(self):
        """Un hôte sans /var/lib/libvirt/images garde son segment disque :
        c'est le système de fichiers du parent qui recevra les images."""
        absent = str(Path(self.tmp.name) / "libvirt" / "images")
        attendu = m.shutil.disk_usage(self.tmp.name)
        with mock.patch.object(
            m.shutil, "disk_usage", wraps=m.shutil.disk_usage
        ) as mesure:
            segment = m._disk_tele(absent)
        mesure.assert_called_once_with(self.tmp.name)
        self.assertIn(f"💽 {absent}:", segment)
        self.assertIn(m._fmt_size(attendu.total), segment)

    def test_an_unmeasurable_disk_gives_no_segment(self):
        with mock.patch.object(m.shutil, "disk_usage", side_effect=OSError):
            self.assertEqual(m._disk_tele(self.tmp.name), "")


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

    def test_a_host_without_the_images_dir_keeps_the_whole_bar(self):
        self.app._disk_dir = str(Path(self.tmp.name) / "absent" / "images")
        bar = self.app._collect_tele()
        self.assertIn("CPU", bar)
        self.assertIn("RAM", bar)
        self.assertIn(f"💽 {self.app._disk_dir}:", bar)

    def test_an_unmeasurable_disk_keeps_cpu_and_ram(self):
        with mock.patch.object(m.shutil, "disk_usage", side_effect=OSError):
            bar = self.app._collect_tele()
        self.assertIn("CPU", bar)
        self.assertIn("RAM", bar)
        self.assertNotIn("💽", bar)

    def test_the_bar_survives_a_mute_proc(self):
        with mock.patch.object(m, "_host_mem", return_value=(0, 0, 0, 0)):
            bar = self.app._collect_tele()
        self.assertIn("CPU", bar)
        self.assertIn("💽", bar)
        self.assertNotIn("RAM", bar)


if __name__ == "__main__":
    unittest.main()
