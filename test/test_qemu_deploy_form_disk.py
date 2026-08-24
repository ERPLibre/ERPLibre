#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La ligne de totaux du formulaire QEMU/KVM : la place, pas seulement la
demande.

La ligne disait « ~126 G » sans dire sur quoi : on découvrait au déploiement
qu'il ne restait pas la place. Elle dit maintenant la demande, ce qui reste et
la capacité — et elle prévient quand ça ne rentre pas, pour les trois limites
(RAM, disque, cœurs) au lieu d'une seule à la fois.

La sonde disque est vérifiée à part : elle doit tomber sur une partition qui
existe même quand le répertoire d'images n'a jamais été créé.
"""

import asyncio
import sys
import unittest

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False


class TestSondeDisque(unittest.TestCase):
    def test_it_measures_the_filesystem_that_will_hold_the_disks(self):
        libre, total = TODO._host_disk_gb()
        self.assertGreater(total, 0)
        self.assertLessEqual(libre, total)

    def test_a_missing_directory_falls_back_to_a_parent(self):
        # /var/lib/libvirt/images n'existe qu'après le premier déploiement :
        # sans repli, la place s'afficherait comme inconnue sur une machine
        # neuve, là où elle est justement la plus utile.
        libre, total = TODO._host_disk_gb("/n/existe/pas/du/tout")
        self.assertGreater(total, 0)

    def test_it_never_raises(self):
        self.assertEqual(len(TODO._host_disk_gb("")), 2)


def contexte():
    """Contexte minimal du formulaire, avec des mesures CHOISIES : la ligne
    doit se lire pareil quelle que soit la machine qui lance le test."""
    todo = TODO.__new__(TODO)
    mod = todo._qemu_import_module()
    todo._qemu_list_domains = lambda: []
    todo._qemu_branch_list = lambda: ["develop", "master"]
    ctx = todo._qemu_form_context(mod)
    ctx["free_disk"] = 500
    ctx["total_disk"] = 900
    ctx["free_ram"] = 64000
    ctx["host_cpu"] = 64
    return ctx


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLigneDeTotaux(unittest.TestCase):
    def _ligne(self, combien, ctx=None):
        from script.todo.qemu_deploy_form import run_deploy_form

        ctx = ctx or contexte()
        vu = {}

        async def scenario():
            from textual.widgets import SelectionList, Static

            app = run_deploy_form(ctx, run_app=False)
            async with app.run_test(size=(200, 50)) as pilote:
                await pilote.pause()
                liste = app.query_one(SelectionList)
                for i in range(combien):
                    liste.select(liste.get_option_at_index(i).value)
                await pilote.pause()
                await pilote.pause()
                widget = app.query_one("#totals", Static)
                vu["ligne"] = str(
                    getattr(widget, "_content", "") or widget.render()
                )
                vu["vms"] = len(app.vms)

        asyncio.run(scenario())
        return vu

    def test_nothing_ticked_says_how_to_fill_the_list(self):
        # Un total à zéro n'apprend rien.
        self.assertNotIn("~", self._ligne(0)["ligne"])

    def test_it_shows_the_demand_the_room_and_the_capacity(self):
        ligne = self._ligne(2)["ligne"]
        self.assertIn("~", ligne)
        self.assertIn("500 G", ligne)
        self.assertIn("900 G", ligne)

    def test_a_plan_bigger_than_the_room_is_flagged(self):
        ctx = contexte()
        ctx["free_disk"] = 1
        ctx["total_disk"] = 900
        self.assertIn("⚠", self._ligne(2, ctx)["ligne"])

    def test_the_three_limits_are_reported_together(self):
        # N'en montrer qu'une cachait les autres : on corrigeait la première
        # pour découvrir la suivante au déploiement.
        ctx = contexte()
        ctx["free_disk"] = 1
        ctx["free_ram"] = 1
        ctx["host_cpu"] = 1
        ligne = self._ligne(2, ctx)["ligne"]
        self.assertEqual(ligne.count("⚠"), 1)
        for morceau in ("RAM", "disque", "cœurs"):
            self.assertIn(morceau, ligne, ligne)

    def test_an_unknown_measure_shows_no_room_at_all(self):
        ctx = contexte()
        ctx["free_disk"] = 0
        ctx["total_disk"] = 0
        ligne = self._ligne(2, ctx)["ligne"]
        self.assertIn("~", ligne)
        self.assertNotIn("/", ligne)


if __name__ == "__main__":
    unittest.main(verbosity=2)
