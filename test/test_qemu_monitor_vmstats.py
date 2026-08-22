#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Statistiques par VM du suivi d'installation : écriture, RAM, disque.

Trois chiffres par VM, tirés d'UN appel « virsh domstats » pour tout le parc :
ce qu'elle écrit (moyenne sur dix secondes), sa RAM occupée/totale, son disque
occupé/total.

Ce que ces tests gardent, appris en les construisant contre des VM réelles :

- Le seed ISO doit être ÉCARTÉ des disques. Monté en lecture seule, il n'est
  jamais écrit, et sa capacité minuscule l'aurait fait passer pour le disque
  système d'une VM dont le qcow2 n'est pas encore alloué.
- Un compteur d'écriture qui RECULE veut dire que le domaine a redémarré —
  ce qu'une installation fait. Sans garde, le débit devient négatif.
- Le ballon mémoire ne publie ses compteurs que si une période de collecte est
  armée. Un relevé vieux d'une demi-heure doit être TAISÉ, pas affiché :
  mesuré, il annonçait 388 Mo pour une VM qui occupait 1,1 Go.
- La ligne du tableau doit tenir : trois colonnes de plus, et « Disque »
  sortait de l'écran sur un terminal de 150 colonnes.
"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from script.todo import qemu_install_monitor as mon
from script.todo.qemu_install_monitor import (
    BALLOON_MAX_AGE,
    COL_DEFAULT_WIDTHS,
    WRITE_WINDOW,
    WriteWindow,
    _fmt_tight,
    fmt_pair,
    fmt_rate,
    parse_domstats,
    ram_pair,
    vm_stats_line,
)

# Sortie RÉELLE de « virsh domstats --balloon --block » sur deux VM du parc :
# une VM de migration en travail, et son seed ISO en second périphérique.
DOMSTATS = """Domain: 'erplibre-ubuntu-2404-MIGRATION'
  balloon.current=12582912
  balloon.maximum=12582912
  balloon.swap_in=0
  balloon.unused=936072
  balloon.available=12242352
  balloon.usable=11064740
  balloon.last-update=1787392761
  balloon.rss=12623896
  block.count=2
  block.0.name=vda
  block.0.path=/var/lib/libvirt/images/erplibre-ubuntu-2404.qcow2
  block.0.rd.bytes=9664722944
  block.0.wr.reqs=2969857
  block.0.wr.bytes=165796498432
  block.0.allocation=67263266816
  block.0.capacity=69793218560
  block.0.physical=67265261568
  block.1.name=vdb
  block.1.path=/var/lib/libvirt/images/iso/erplibre-ubuntu-2404-seed.iso
  block.1.wr.bytes=4096
  block.1.allocation=380928
  block.1.capacity=380928
Domain: 'erplibre-ubuntu-2604'
  balloon.current=12582912
  balloon.available=12237092
  balloon.usable=11054184
  balloon.last-update=1787392782
  block.count=1
  block.0.name=vda
  block.0.path=/var/lib/libvirt/images/erplibre-ubuntu-2604.qcow2
  block.0.wr.bytes=48117251072
  block.0.allocation=43900928000
  block.0.capacity=69793218560
"""

MIGRATION = "erplibre-ubuntu-2404-MIGRATION"


class TestLecture(unittest.TestCase):
    def test_it_reads_both_domains(self):
        st = parse_domstats(DOMSTATS)
        self.assertEqual({MIGRATION, "erplibre-ubuntu-2604"}, set(st))

    def test_ram_is_available_minus_usable(self):
        """Calibrée en son temps contre le « free » de deux invités : c'est
        « available - usable » qui suit ce qu'ils occupent, pas « unused »,
        qui compte le cache."""
        rec = parse_domstats(DOMSTATS)[MIGRATION]
        self.assertEqual(12242352 * 1024, rec["ram_total"])
        self.assertEqual((12242352 - 11064740) * 1024, rec["ram_used"])

    def test_the_seed_iso_is_left_out_of_the_disk(self):
        """Sa capacité (372 Ko) l'emporterait sur un qcow2 pas encore alloué,
        et le tableau annoncerait un disque plein à 100 %."""
        rec = parse_domstats(DOMSTATS)[MIGRATION]
        self.assertEqual(69793218560, rec["disk_total"])
        self.assertEqual(67263266816, rec["disk_used"])

    def test_the_seed_iso_writes_are_left_out_too(self):
        """4096 octets écrits sur un ISO en lecture seule : anecdotique ici,
        mais compter un périphérique qu'on n'affiche pas rend un débit qu'on
        ne peut relier à rien."""
        rec = parse_domstats(DOMSTATS)[MIGRATION]
        self.assertEqual(165796498432, rec["wr_bytes"])

    def test_a_single_disk_vm_is_read_too(self):
        rec = parse_domstats(DOMSTATS)["erplibre-ubuntu-2604"]
        self.assertEqual(48117251072, rec["wr_bytes"])
        self.assertEqual(69793218560, rec["disk_total"])

    def test_empty_or_broken_output_gives_nothing(self):
        for texte in ("", "erreur: pas de connexion", None):
            self.assertEqual({}, parse_domstats(texte))

    def test_a_domain_without_balloon_stats_is_not_invented(self):
        """Une VM éteinte, ou dont le pilote n'a rien publié : pas de RAM
        plutôt qu'un zéro qui passerait pour une mesure."""
        rec = parse_domstats("Domain: 'x'\n  block.count=0\n")["x"]
        self.assertEqual(0, rec["ram_total"])
        self.assertEqual("-", ram_pair(rec, time.time()))


class TestFenetreEcriture(unittest.TestCase):
    def test_two_samples_ten_seconds_apart_give_the_rate(self):
        w = WriteWindow(10.0)
        w.add("vm", 0, 1000.0)
        w.add("vm", 10 << 20, 1010.0)
        self.assertAlmostEqual(1 << 20, w.rate("vm"), delta=1024)

    def test_one_sample_is_not_a_rate(self):
        """Au premier tour, la colonne doit dire « - » et non « 0 » : un débit
        nul et un débit inconnu ne se ressemblent pas."""
        w = WriteWindow()
        w.add("vm", 12345, 1000.0)
        self.assertIsNone(w.rate("vm"))
        self.assertEqual("-", fmt_rate(w.rate("vm")))

    def test_samples_too_close_together_are_not_a_rate(self):
        """Deux relevés à 200 ms d'intervalle donnent un chiffre absurde ;
        mieux vaut attendre le tour suivant."""
        w = WriteWindow()
        w.add("vm", 0, 1000.0)
        w.add("vm", 1 << 20, 1000.2)
        self.assertIsNone(w.rate("vm"))

    def test_the_window_keeps_about_ten_seconds(self):
        """Sinon la moyenne porterait sur toute la durée de l'installation, et
        ne montrerait plus ce qui se passe MAINTENANT."""
        w = WriteWindow(10.0)
        # Une minute de relevés toutes les deux secondes, débit constant.
        for i in range(31):
            w.add("vm", i * (2 << 20), 1000.0 + 2 * i)
        span = w._hist["vm"][-1][0] - w._hist["vm"][0][0]
        self.assertLessEqual(span, 12.0)
        self.assertGreaterEqual(span, 10.0)
        self.assertAlmostEqual(1 << 20, w.rate("vm"), delta=1024)

    def test_a_restart_resets_the_window_instead_of_going_negative(self):
        """Le compteur appartient au processus QEMU : un redémarrage du domaine
        le remet à zéro, et une installation redémarre la VM."""
        w = WriteWindow(10.0)
        w.add("vm", 500 << 20, 1000.0)
        w.add("vm", 501 << 20, 1002.0)
        w.add("vm", 1 << 20, 1004.0)  # domaine redémarré
        self.assertIsNone(w.rate("vm"))
        w.add("vm", 3 << 20, 1014.0)
        self.assertIsNotNone(w.rate("vm"))
        self.assertGreater(w.rate("vm"), 0)

    def test_vms_do_not_mix(self):
        w = WriteWindow(10.0)
        w.add("a", 0, 1000.0)
        w.add("b", 0, 1000.0)
        w.add("a", 10 << 20, 1010.0)
        w.add("b", 1 << 20, 1010.0)
        self.assertAlmostEqual(1 << 20, w.rate("a"), delta=1024)
        self.assertAlmostEqual(1 << 20, w.rate("b") * 10, delta=10240)

    def test_the_window_is_the_ten_seconds_announced(self):
        """La colonne dit « moyenne 10 s » : la constante doit le tenir."""
        self.assertEqual(10.0, WRITE_WINDOW)


class TestFraicheurRam(unittest.TestCase):
    def test_a_stale_balloon_report_is_hidden(self):
        rec = parse_domstats(DOMSTATS)[MIGRATION]
        vieux = rec["ram_at"] + BALLOON_MAX_AGE + 5
        self.assertEqual("-", ram_pair(rec, vieux))

    def test_a_fresh_report_is_shown(self):
        rec = parse_domstats(DOMSTATS)[MIGRATION]
        self.assertEqual("1.1G/12G", ram_pair(rec, rec["ram_at"] + 2))

    def test_a_report_without_a_date_is_still_shown(self):
        """libvirt joint toujours « last-update » quand le ballon a parlé ;
        sans elle on ne sait pas juger, et taire la valeur perdrait la seule
        information disponible."""
        rec = dict(parse_domstats(DOMSTATS)[MIGRATION], ram_at=0)
        self.assertNotEqual("-", ram_pair(rec, time.time()))


class TestFormats(unittest.TestCase):
    def test_the_decimal_goes_away_above_ten_units(self):
        """« 63G » plutôt que « 62.6G » : ces deux caractères décident si
        « Disque » reste visible."""
        self.assertEqual("63G", _fmt_tight(67263266816))
        self.assertEqual("1.1G", _fmt_tight(1130479616))
        self.assertEqual("12G", _fmt_tight(12536168448))

    def test_a_pair_without_a_total_says_nothing(self):
        self.assertEqual("-", fmt_pair(1024, 0))
        self.assertEqual("-", fmt_pair(None, None))

    def test_the_rate_carries_its_unit(self):
        self.assertEqual("1.0M/s", fmt_rate(1 << 20))
        self.assertEqual("-", fmt_rate(None))

    def test_the_pairs_fit_the_columns(self):
        """Une valeur tronquée dans un tableau est un piège : on lit « 1001M/1 »
        et on croit une VM à 1 Go."""
        for used, total, cle in (
            (1001 << 20, 128 << 30, "ram"),
            (12 << 30, 128 << 30, "ram"),
            (999 << 30, 1 << 40, "disk"),
            (67263266816, 69793218560, "disk"),
        ):
            self.assertLessEqual(
                len(fmt_pair(used, total)), COL_DEFAULT_WIDTHS[cle]
            )
        for bps in (0, 1 << 10, 12.3 * (1 << 20), 2 << 30):
            self.assertLessEqual(len(fmt_rate(bps)), COL_DEFAULT_WIDTHS["wr"])


class TestSection(unittest.TestCase):
    def test_it_names_the_three_measures(self):
        rec = parse_domstats(DOMSTATS)[MIGRATION]
        ligne = vm_stats_line(
            MIGRATION, rec, 1 << 20, rec["ram_at"] + 1, rec["wr_bytes"]
        )
        self.assertIn(MIGRATION, ligne)
        self.assertIn("1.0M/s", ligne)
        self.assertIn("1.1G/12G", ligne)
        self.assertIn("63G/65G", ligne)

    def test_it_shows_percentages(self):
        """« 63G/65G » ne dit pas d'un coup d'œil que le disque est à 96 %."""
        rec = parse_domstats(DOMSTATS)[MIGRATION]
        ligne = vm_stats_line(MIGRATION, rec, 0, rec["ram_at"] + 1)
        self.assertIn("(96%)", ligne)
        self.assertIn("(9%)", ligne)

    def test_a_vm_without_stats_says_so(self):
        ligne = vm_stats_line("vm-x", None, None, time.time())
        self.assertIn("vm-x", ligne)
        self.assertNotIn("RAM", ligne)


class TestColonnes(unittest.TestCase):
    def test_the_three_columns_exist(self):
        for cle in ("wr", "ram", "disk"):
            self.assertIn(cle, COL_DEFAULT_WIDTHS)

    def test_the_row_fits_a_150_column_terminal(self):
        """La table est bornée à 66 % de l'écran, et le journal prend le reste.
        Trois colonnes de plus, et « Disque » sortait du cadre : le total est
        donc surveillé, padding de DataTable compris (2 par colonne)."""
        besoin = sum(COL_DEFAULT_WIDTHS.values()) + 2 * len(COL_DEFAULT_WIDTHS)
        self.assertLessEqual(besoin, int(150 * 0.66))


class TestEcranMonte(unittest.IsolatedAsyncioTestCase):
    """Le suivi monté pour de vrai : les colonnes portent-elles les chiffres ?

    Aucun appel à libvirt : « read_domstats » rend la sortie enregistrée
    ci-dessus. Un test qui lance sudo ne tournerait ni en CI ni sur un poste
    sans le parc.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        for nom in (MIGRATION, "erplibre-ubuntu-2604"):
            (base / f"{nom}.log").write_text("===> install\nligne\n")
        manifeste = {
            "branch": "develop",
            "started": time.time() - 300,
            "vms": [
                {
                    "name": nom,
                    "ip": "127.0.0.9",
                    "arch": "amd64",
                    "log": str(base / f"{nom}.log"),
                    "ssh": f"ssh erplibre@{nom}",
                    "disk": str(base / f"{nom}.qcow2"),
                }
                for nom in (MIGRATION, "erplibre-ubuntu-2604")
            ],
        }
        self.manifest = base / "session.json"
        self.manifest.write_text(json.dumps(manifeste))
        # Le relevé du ballon doit paraître FRAIS, sinon la colonne RAM se
        # taira — ce qui est le comportement voulu, mais pas ce qu'on teste.
        self.stats = DOMSTATS.replace(
            "balloon.last-update=1787392761",
            f"balloon.last-update={int(time.time())}",
        ).replace(
            "balloon.last-update=1787392782",
            f"balloon.last-update={int(time.time())}",
        )

    async def _monte(self, taille=(150, 24)):
        from textual.widgets import DataTable, Static

        with mock.patch.object(
            mon, "read_domstats", lambda: self.stats
        ), mock.patch.object(
            mon, "arm_balloon", lambda names: None
        ), mock.patch.object(
            mon,
            "virsh_domstates",
            lambda: {MIGRATION: "running", "erplibre-ubuntu-2604": "running"},
        ), mock.patch.object(
            mon, "_port_open", lambda ip, port=8069, timeout=0.5: False
        ):
            app = mon.run_monitor(str(self.manifest), run_app=False)
            async with app.run_test(size=taille) as pilot:
                await pilot.pause()
                # Le tick du tableau tourne toutes les deux secondes : on
                # l'appelle plutôt que d'attendre, et on antidate un premier
                # relevé pour que la fenêtre ait de quoi conclure.
                app._wrate.add(MIGRATION, 100 << 20, time.time() - 10)
                await app._tick_table()
                await pilot.pause()
                table = app.query_one("#vms", DataTable)
                cellules = {
                    cle: str(table.get_cell(MIGRATION, cle))
                    for cle in ("wr", "ram", "disk")
                }
                section = str(app.query_one("#vmstats", Static).content)
                besoin = table.virtual_size.width
                visible = table.size.width
            return cellules, section, besoin, visible

    async def test_the_columns_carry_the_numbers(self):
        cellules, _section, _b, _v = await self._monte()
        self.assertEqual("1.1G/12G", cellules["ram"])
        self.assertEqual("63G/65G", cellules["disk"])
        self.assertTrue(cellules["wr"].endswith("/s"), cellules["wr"])

    async def test_the_selected_vm_has_its_statistics_section(self):
        _c, section, _b, _v = await self._monte()
        self.assertIn(MIGRATION, section)
        self.assertIn("1.1G/12G", section)
        self.assertIn("63G/65G", section)

    async def test_nothing_scrolls_out_of_a_150_column_terminal(self):
        """Le vrai garde-fou de la largeur : mesuré sur la table montée, pas
        calculé à la main."""
        _c, _s, besoin, visible = await self._monte((150, 24))
        self.assertGreaterEqual(visible, besoin)


if __name__ == "__main__":
    unittest.main(verbosity=1)
