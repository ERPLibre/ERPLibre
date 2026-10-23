#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'historique des modifications du formulaire de déploiement.

Ce que ces tests gardent :

- F6 pressée par erreur se défait d'un ctrl+z, même aussitôt pressé, et
  rend EXACTEMENT le plan d'avant : surcharges, verrous, noms, et les
  cartes du panneau droit ;
- un plan ramené à vide n'affiche plus aucune carte ;
- une rafale de messages (F7, une frappe) donne UNE entrée ;
- revenir en arrière puis modifier ne perd rien : l'état quitté est rejoué
  en tête avant la modification ;
- « h » ouvre la liste hors d'un champ texte et s'écrit dans un champ ;
  F2 et ctrl+z marchent de partout ; Échap ferme la liste, pas le
  formulaire ;
- une restauration ne laisse pas les gestionnaires effacer les surcharges
  remises, et rend aux champs leur état grisé.
"""

import asyncio
import sys
import unittest

sys.argv = ["todo.py"]
sys.path.insert(0, "test")

from async_case import AsyncCase  # noqa: E402

from script.todo.deploy_form_history import (  # noqa: E402
    SETTLE_DELAY,
    History,
    describe,
    label_for,
)
from script.todo.todo import TODO  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False


class TestHistoryPure(unittest.TestCase):
    def test_undo_redo_and_the_cursor(self):
        h = History({"n": 0}, "origine", 0.0)
        h.record("un", {"n": 1}, 1.0)
        h.record("deux", {"n": 2}, 2.0)
        defaite, atteinte = h.undo()
        self.assertEqual(
            ("deux", {"n": 1}), (defaite["label"], atteinte["snap"])
        )
        self.assertEqual({"n": 2}, h.redo()["snap"])
        self.assertIsNone(h.redo())
        h.undo(), h.undo()
        self.assertIsNone(h.undo())

    def test_a_change_after_going_back_loses_nothing(self):
        h = History({"n": 0}, "origine", 0.0)
        h.record("un", {"n": 1}, 1.0)
        h.record("deux", {"n": 2}, 2.0)
        h.jump(0)
        h.record("trois", {"n": 3}, 3.0, back=lambda x: f"retour {x}")
        self.assertEqual(
            ["origine", "un", "deux", "retour origine", "trois"],
            [e["label"] for e in h.entries],
        )
        self.assertEqual({"n": 0}, h.entries[3]["snap"])
        self.assertEqual(4, h.cursor)

    def test_typing_in_one_field_merges(self):
        h = History({}, "origine", 0.0)
        h.record("a", {"v": "8"}, 1.0, key="c_ram")
        h.record("b", {"v": "81"}, 2.0, key="c_ram")
        self.assertEqual(2, len(h.entries))
        self.assertEqual({"v": "81"}, h.entries[-1]["snap"])
        # Un autre champ, ou trop tard : une nouvelle entrée.
        h.record("c", {"v": "x"}, 2.5, key="f_git_name")
        h.record("d", {"v": "xy"}, 9.0, key="f_git_name")
        self.assertEqual(4, len(h.entries))

    def test_typing_back_to_the_previous_value_drops_the_entry(self):
        h = History({"v": ""}, "origine", 0.0)
        h.record("a", {"v": "a"}, 1.0, key="f_git_name")
        h.record("b", {"v": ""}, 2.0, key="f_git_name")
        self.assertEqual(1, len(h.entries))
        self.assertIsNone(h.undo())

    def test_the_cap_drops_the_oldest_and_ids_stay(self):
        h = History({"n": 0}, "origine", 0.0, cap=3)
        for n in range(1, 6):
            h.record(str(n), {"n": n}, float(n))
        self.assertEqual([3, 4, 5], [e["id"] for e in h.entries])
        self.assertEqual(2, h.cursor)
        self.assertEqual({"n": 4}, h.jump(4)["snap"])

    def test_describe_says_what_changed(self):
        cle = ("distro-fictive", "9", "x86_64", 0)
        avant = {
            "catalog": (),
            "arch": "x86_64",
            "overrides": {},
            "locked": set(),
            "copies": {},
            "widgets": {"f_gpu3d": False},
        }
        apres = dict(
            avant,
            catalog=(cle,),
            overrides={cle: {"ram": 8192, "name": "vm-essai"}},
            widgets={"f_gpu3d": True},
        )
        parts = describe(avant, apres, {"names": {"f_gpu3d": "3D"}})
        self.assertEqual("+1 VM", parts[0])
        self.assertIn("distro-fictive 9 → vm-essai", parts)
        self.assertTrue(any("vm-essai" in p and "8192" in p for p in parts))
        self.assertIn("3D : ✓", parts)
        self.assertEqual(
            f"F6 — +1 VM (+{len(parts) - 1})", label_for(parts, "F6")
        )

    def test_a_removed_name_reads_as_the_automatic_one(self):
        cle = ("distro-fictive", "9", "x86_64", 1)
        avant = {"overrides": {cle: {"name": "vm-essai"}}}
        parts = describe(avant, {"overrides": {}})
        self.assertIn("vm-essai → distro-fictive 9 #2", parts)


def contexte():
    """Contexte du formulaire QEMU, sans hôte réel."""
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
class TestFormulaireQemu(AsyncCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        from script.todo.qemu_deploy_form import run_deploy_form

        self.app = run_deploy_form(contexte(), run_app=False)

    async def calme(self, pilote):
        for _ in range(4):
            await pilote.pause()

    async def ouvert(self, pilote):
        """Le formulaire monté, son origine prise."""
        await self.calme(pilote)
        self.app._hist_settle()
        self.assertIsNotNone(self.app._hist)

    def coche(self, *rangs):
        from textual.widgets import SelectionList

        liste = self.app.query_one(SelectionList)
        for i in rangs:
            liste.select(liste.get_option_at_index(i).value)

    def cartes(self):
        return len(self.app.query_one("#plan").children)

    def etat(self):
        app = self.app
        return (
            app._hist_catalog(),
            {k: dict(v) for k, v in app.overrides.items()},
            set(app.locked),
            dict(app.copies),
            [r["vm"]["name"] for r in app.rows],
        )

    async def test_f6_then_ctrl_z_gives_back_the_plan(self):
        from textual.widgets import Select

        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            self.coche(0, 1)
            await self.calme(pilote)
            ram = [
                v
                for v in app._presets()["ram"]
                if v != app.rows[0]["vm"]["ram"]
            ][0]
            app.query_one("#v0_ram", Select).value = ram
            await self.calme(pilote)
            await pilote.click("#l1")
            await self.calme(pilote)
            cle = app._row_key(0)
            app.overrides.setdefault(cle, {})["name"] = "vm-essai"
            app._recompute()
            app._mount_rows()
            await self.calme(pilote)
            # Aucun silence n'a laissé le minuteur relever ces réglages :
            # F6 doit les relever avant d'ouvrir sa propre entrée.
            avant = self.etat()
            self.assertEqual(ram, avant[1][cle]["ram"])
            await pilote.press("f6")
            # Aucune pause : le réflexe arrive avant que le minuteur ne
            # relève F6.
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertEqual(avant, self.etat())
            self.assertEqual(2, self.cartes())
            self.assertEqual(ram, app.query_one("#v0_ram", Select).value)
            self.assertIn("F6", app._hist.entries[-1]["label"])

    async def test_back_to_an_empty_plan_shows_no_card(self):
        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            await pilote.press("f6")
            await self.calme(pilote)
            self.assertGreater(self.cartes(), 0)
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertEqual([], app.rows)
            self.assertEqual(0, self.cartes())
            await pilote.press("ctrl+y")
            await self.calme(pilote)
            self.assertEqual(len(app._entries()), len(app.rows))

    async def test_one_f7_is_one_entry(self):
        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            await pilote.press("f7")
            await self.calme(pilote)
            app._hist_settle()
            self.assertEqual(2, len(app._hist.entries))
            self.assertTrue(app._hist.entries[-1]["label"].startswith("F7"))
            # Les échos du montage des rangées ne comptent pas.
            await self.calme(pilote)
            app._hist_settle()
            self.assertEqual(2, len(app._hist.entries))

    async def test_a_checkbox_click_is_recorded(self):
        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            app.query_one("#f_gpu3d").focus()
            await pilote.press("space")
            await self.calme(pilote)
            # Le minuteur, pas un relevé forcé : c'est le message de la case
            # qui doit l'armer.
            self.assertIsNotNone(app._hist_timer)
            await pilote.pause(SETTLE_DELAY + 0.3)
            self.assertEqual(2, len(app._hist.entries))

    async def test_typing_in_a_field_is_one_entry(self):
        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            app.query_one("#f_git_name").focus()
            for lettre in "Nom":
                await pilote.press(lettre)
            await self.calme(pilote)
            app._hist_settle()
            self.assertEqual(2, len(app._hist.entries))

    async def test_h_lists_and_enter_goes_back_without_losing(self):
        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            await pilote.press("f6")
            await self.calme(pilote)
            await pilote.press("f8")
            await self.calme(pilote)
            app.query_one("#f_catalog").focus()
            await pilote.press("h")
            await self.calme(pilote)
            self.assertEqual("HistoryScreen", type(app.screen).__name__)
            # L'origine est en bas de la liste.
            await pilote.press("end")
            await pilote.press("enter")
            await self.calme(pilote)
            self.assertEqual(1, len(app.screen_stack))
            self.assertEqual(0, app._hist.cursor)
            self.coche(0)
            await self.calme(pilote)
            app._hist_settle()
            labels = [e["label"] for e in app._hist.entries]
            self.assertEqual(5, len(labels))
            self.assertIn(labels[0], labels[3])
            self.assertEqual("+1 VM", labels[4])

    async def test_h_types_in_a_text_field_f2_and_ctrl_z_still_work(self):
        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            await pilote.press("f6")
            await self.calme(pilote)
            champ = app.query_one("#f_git_name")
            avant = champ.value
            champ.focus()
            await pilote.press("h")
            await self.calme(pilote)
            self.assertTrue(champ.value.endswith("h"))
            self.assertEqual(1, len(app.screen_stack))
            await pilote.press("f2")
            await self.calme(pilote)
            self.assertEqual("HistoryScreen", type(app.screen).__name__)
            await pilote.press("escape")
            await self.calme(pilote)
            self.assertTrue(app.is_running)
            self.assertEqual(1, len(app.screen_stack))
            champ.focus()
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertEqual(avant, champ.value)

    async def test_a_restored_profile_keeps_the_restored_overrides(self):
        from textual.widgets import RadioButton, RadioSet, Select

        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            self.coche(0)
            await self.calme(pilote)
            boutons = list(
                app.query_one("#f_profile", RadioSet).query(RadioButton)
            )
            boutons[1].value = True  # x2
            await self.calme(pilote)
            ram = [
                v
                for v in app._presets()["ram"]
                if v != app.rows[0]["vm"]["ram"]
            ][0]
            app.query_one("#v0_ram", Select).value = ram
            await self.calme(pilote)
            app._hist_settle()
            cle = app._row_key(0)
            self.assertEqual(ram, app.overrides[cle]["ram"])
            boutons[4].value = True  # personnalisé : efface la RAM réglée
            await self.calme(pilote)
            self.assertNotIn("ram", app.overrides.get(cle, {}))
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertEqual("2", app.profile)
            self.assertEqual(ram, app.overrides[cle]["ram"])
            self.assertEqual(
                1, app.query_one("#f_profile", RadioSet).pressed_index
            )
            self.assertTrue(app.query_one("#f_vcpus", Select).disabled)

    async def test_an_arch_change_is_undone(self):
        from textual.widgets import RadioButton, RadioSet

        app = self.app
        arches = contexte()["arches"]
        if len(arches) < 2:
            self.skipTest("une seule architecture au catalogue")
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            self.coche(0)
            await self.calme(pilote)
            app._hist_settle()
            avant = (app.arch, app._hist_catalog())
            radio = app.query_one("#f_arch", RadioSet)
            autre = 1 if radio.pressed_index == 0 else 0
            list(radio.query(RadioButton))[autre].value = True
            await self.calme(pilote)
            self.assertNotEqual(avant[0], app.arch)
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertEqual(avant, (app.arch, app._hist_catalog()))
            self.assertEqual(arches.index(app.arch), radio.pressed_index)

    async def test_f5_confirmations_are_reset(self):
        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            await pilote.press("f6")
            await self.calme(pilote)
            app._orphan_ack = app._offline_ack = True
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertFalse(app._orphan_ack)
            self.assertFalse(app._offline_ack)

    async def test_offline_and_the_monitor_it_forces_come_back(self):
        from textual.widgets import Checkbox

        from script.todo.qemu_deploy_form import run_deploy_form

        self.app = app = run_deploy_form(
            dict(contexte(), cache_offert=True), run_app=False
        )
        async with app.run_test(size=(200, 70)) as pilote:
            await self.ouvert(pilote)
            suivi = app.query_one("#f_monitor", Checkbox)
            coupe = app.query_one("#f_offline", Checkbox)
            suivi.value = False
            await self.calme(pilote)
            app._hist_settle()
            coupe.value = True
            await self.calme(pilote)
            self.assertEqual((True, True), (suivi.value, suivi.disabled))
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertEqual(
                (False, False, False),
                (coupe.value, suivi.value, suivi.disabled),
            )
            await pilote.press("ctrl+y")
            await self.calme(pilote)
            self.assertEqual(
                (True, True, True), (coupe.value, suivi.value, suivi.disabled)
            )
            # Le suivi d'avant la coupure est resté en mémoire : décocher la
            # coupure à la main le rend tel qu'il était.
            coupe.value = False
            await self.calme(pilote)
            self.assertFalse(suivi.value)

    async def test_a_bracket_in_a_value_does_not_break_the_list(self):
        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            app.query_one("#f_git_name").value = "a[/] [b]x"
            await self.calme(pilote)
            app._hist_settle()
            await pilote.press("f2")
            await self.calme(pilote)
            self.assertEqual("HistoryScreen", type(app.screen).__name__)
            await pilote.press("escape")
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            # Le libellé reprend la saisie : la notification ne l'interprète
            # pas, sinon « [b] » y disparaîtrait.
            avis = list(app._notifications)[-1]
            self.assertFalse(avis.markup)
            self.assertIn("a[/] [b]x", avis.message)
            await pilote.press("ctrl+y")
            await self.calme(pilote)
            self.assertTrue(app.is_running)
            self.assertEqual("a[/] [b]x", app.query_one("#f_git_name").value)

    async def test_a_row_free_value_stays_shown_after_undo(self):
        from textual.widgets import Input, Select

        from script.todo.deploy_form_lib import FREE

        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            self.coche(0)
            await self.calme(pilote)
            app.query_one("#v0_ram", Select).value = FREE
            await self.calme(pilote)
            app.query_one("#c0_ram", Input).value = "7000"
            await self.calme(pilote)
            app._hist_settle()
            app.query_one("#f_gpu3d").focus()
            await pilote.press("space")
            await self.calme(pilote)
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            saisie = app.query_one("#c0_ram", Input)
            self.assertTrue(saisie.display)
            self.assertEqual(7000, app.rows[0]["vm"]["ram"])

    async def test_f5_right_after_ctrl_z_deploys_the_restored_plan(self):
        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            await pilote.press("f6")
            await self.calme(pilote)
            # Dans le même tour, comme des touches tamponnées : F5 arrive
            # avant que la restauration ait remis le plan.
            app.action_undo()
            app.action_deploy()
            await self.calme(pilote)
            self.assertIsNone(app._result["spec"])
            self.assertTrue(app.is_running)

    async def test_a_gesture_during_a_restore_gets_its_entry(self):
        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            self.coche(0)
            await self.calme(pilote)
            app._hist_settle()
            app.action_undo()
            app.action_select_all()
            await self.calme(pilote)
            self.assertEqual(len(app._entries()), len(app.rows))
            self.assertTrue(app._hist.entries[-1]["label"].startswith("F6"))
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertEqual([], app.rows)

    async def test_a_change_during_a_restore_is_recorded_after_it(self):
        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            self.coche(0)
            await self.calme(pilote)
            app._hist_settle()
            app.action_undo()
            # Une case cochée pendant que la restauration se fait.
            app.query_one("#f_gpu3d").value = True
            await self.calme(pilote)
            await pilote.pause(SETTLE_DELAY + 0.3)
            self.assertTrue(
                app._hist.entries[-1]["snap"]["widgets"]["f_gpu3d"]
            )
            self.assertEqual(len(app._hist.entries) - 1, app._hist.cursor)

    async def test_a_gesture_that_changes_nothing_lends_no_name(self):
        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            await pilote.press("f8")
            app.query_one("#f_gpu3d").focus()
            await pilote.press("space")
            await pilote.pause(SETTLE_DELAY + 0.3)
            self.assertEqual(2, len(app._hist.entries))
            self.assertFalse(app._hist.entries[-1]["label"].startswith("F8"))

    async def test_slow_typing_in_a_resource_field_is_one_entry(self):
        from textual.widgets import Input, RadioButton, RadioSet, Select

        from script.todo.deploy_form_lib import FREE

        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            self.coche(0)
            boutons = list(
                app.query_one("#f_profile", RadioSet).query(RadioButton)
            )
            boutons[4].value = True
            await self.calme(pilote)
            app.query_one("#f_ram", Select).value = FREE
            await self.calme(pilote)
            app._hist_settle()
            avant = len(app._hist.entries)
            app.query_one("#c_ram", Input).focus()
            for chiffre in "7000":
                await pilote.press(chiffre)
                # Plus long que le silence, moins que la fusion.
                await pilote.pause(SETTLE_DELAY + 0.2)
            self.assertEqual(avant + 1, len(app._hist.entries))

    async def test_a_pending_timer_after_teardown_is_harmless(self):
        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            await pilote.press("f6")
        app._hist_settle()

    async def test_nothing_to_undo_says_so(self):
        app = self.app
        async with app.run_test(size=(200, 50)) as pilote:
            await self.ouvert(pilote)
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertEqual(1, len(app._hist.entries))


if __name__ == "__main__":
    asyncio.run(unittest.main())
