#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le fuseau écrit dans le seed est un nom que l'invité sait lire.

Une VM hérite du fuseau de l'hôte qui la déploie. Le nom passait tel quel, et
les images cloud d'Ubuntu 24.04 ne portent plus les alias historiques —
Canada/*, US/*, Brazil/*, Asia/Calcutta… — déplacés dans un paquet
« tzdata-legacy » qu'elles n'installent pas. cloud-init refuse alors le
fuseau, la VM RESTE en UTC, et le module se solde par un échec qui ne se voit
qu'aux horodatages, longtemps après le déploiement.

La traduction se fait sur la table de l'HÔTE (/usr/share/zoneinfo/tzdata.zi),
et non sur une copie écrite ici : une table figée dans un test vieillit, celle
du système suit tzdata. Ces tests la fournissent donc en mémoire pour éprouver
la lecture, et n'exigent du vrai fichier que ce qui ne change plus.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]


def _deploy_qemu():
    """deploy_qemu.py chargé comme module, comme le fait todo.py."""
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()

# Une tzdata.zi réduite : les lignes « L <canonique> <alias> » sont les seules
# qui portent un lien, le reste du fichier décrit les règles horaires.
TABLE = """# tzdata.zi, extrait
R d 1974 ma 1 - Ap Su>=1 2 1 D
Z America/Toronto -5:17:32 - LMT 1895
L America/Toronto Canada/Eastern
L America/Los_Angeles US/Pacific
L Asia/Kolkata Asia/Calcutta
L Etc/UTC UTC
L UTC Universal
"""


class LaTraduction(unittest.TestCase):
    def setUp(self):
        self.lecture = mock.patch.object(
            DQ.Path, "read_text", return_value=TABLE
        )
        self.lecture.start()
        self.addCleanup(self.lecture.stop)

    def test_a_legacy_alias_becomes_its_canonical_name(self):
        """Le cas qui casse : l'alias que l'image cloud ne porte plus."""
        self.assertEqual(
            DQ.canonical_timezone("Canada/Eastern"), "America/Toronto"
        )
        self.assertEqual(
            DQ.canonical_timezone("US/Pacific"), "America/Los_Angeles"
        )

    def test_a_renamed_zone_follows_the_rename(self):
        """Un fuseau renommé en amont est un lien comme un autre."""
        self.assertEqual(
            DQ.canonical_timezone("Asia/Calcutta"), "Asia/Kolkata"
        )

    def test_a_canonical_name_passes_through_untouched(self):
        """Traduire ce qui n'a pas besoin de l'être serait une régression : le
        fuseau demandé est celui qu'on veut, quand l'invité sait le lire."""
        self.assertEqual(
            DQ.canonical_timezone("America/Toronto"), "America/Toronto"
        )
        self.assertEqual(DQ.canonical_timezone("Europe/Paris"), "Europe/Paris")

    def test_an_alias_of_an_alias_resolves(self):
        """« Universal » pointe « UTC », qui pointe « Etc/UTC » : deux tours
        suffisent, et la table n'en enchaîne pas davantage."""
        self.assertEqual(DQ.canonical_timezone("Universal"), "Etc/UTC")

    def test_an_empty_zone_stays_empty(self):
        """Rien à traduire, et surtout rien à inventer."""
        self.assertEqual(DQ.canonical_timezone(""), "")


class SansTable(unittest.TestCase):
    def test_a_host_without_the_table_keeps_the_zone_asked_for(self):
        """Un hôte sans tzdata.zi — macOS, une image trop maigre — n'empêche
        pas de déployer : mieux vaut le fuseau demandé qu'un fuseau deviné."""
        with mock.patch.object(DQ.Path, "read_text", side_effect=OSError):
            self.assertEqual(
                DQ.canonical_timezone("Canada/Eastern"), "Canada/Eastern"
            )


class LesDeuxPointsDEcriture(unittest.TestCase):
    """Le seed cloud-init et le preseed Debian écrivent tous deux un fuseau.
    Traduire à un seul endroit laisserait l'autre défaillant."""

    SRC = (RACINE / "script/qemu/deploy_qemu.py").read_text(encoding="utf-8")

    def test_the_cloud_config_writes_a_canonical_zone(self):
        self.assertIn(
            "timezone: {canonical_timezone(args.timezone)}", self.SRC
        )

    def test_the_preseed_writes_a_canonical_zone(self):
        self.assertIn(
            "d-i time/zone string {canonical_timezone(args.timezone)}",
            self.SRC,
        )

    def test_no_hand_written_alias_table_is_kept_here(self):
        """Une table figée dans le code vieillit sans qu'on le sache : c'est
        celle du système qui fait foi."""
        self.assertIn("/usr/share/zoneinfo/tzdata.zi", self.SRC)


class LeVraiFichier(unittest.TestCase):
    """Ce que la vraie table garantit, sur un hôte qui la porte."""

    def setUp(self):
        if not Path("/usr/share/zoneinfo/tzdata.zi").exists():
            self.skipTest("hôte sans tzdata.zi")

    def test_the_zone_written_exists_in_the_guest_tzdata(self):
        """L'épreuve qui compte : le nom rendu est un fichier de zoneinfo, ce
        que cloud-init vérifie chez l'invité avant de poser /etc/localtime."""
        for zone in ("Canada/Eastern", "US/Pacific", "America/Toronto"):
            with self.subTest(zone=zone):
                rendu = DQ.canonical_timezone(zone)
                self.assertTrue(Path("/usr/share/zoneinfo", rendu).exists())


if __name__ == "__main__":
    unittest.main()
