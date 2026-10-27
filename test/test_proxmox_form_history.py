#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'historique des modifications du formulaire Proxmox.

Le mécanisme est celui du formulaire QEMU/KVM, que
`test_deploy_form_history.py` éprouve en détail. Ce qui est gardé ici est
ce que Proxmox a de propre :

- le catalogue porte des identités, pas des rangs, et une architecture
  change la liste elle-même ;
- « créer un pont » déclenche une action sur l'hôte : il n'est jamais gardé,
  donc jamais rejoué ; annuler revient au pont d'avant ;
- la case 3D peut apparaître en cours de route, après la pose du GPU sur
  l'hôte : une annulation ne la fait pas passer pour un changement ;
- une valeur libre commune ne s'applique qu'à Entrée ;
- F4 rend aussi le verrou, sous son propre nom ;
- F4 et les boutons d'une rangée, reçus pendant une restauration, visent la
  VM qu'on voyait, et non celle qui prend son rang dans le plan restauré ;
- une restauration remet les surcharges et l'état grisé des ressources ;
- F5 pendant une restauration attend qu'elle soit finie ;
- F7 coche les versions par défaut par leur identité, et l'historique le
  suit ;
- un texte libre tapé sans Entrée n'est pas un état ;
- un changement arrivé pendant que la liste est ouverte est relevé avant
  d'y choisir une entrée.
"""

import contextlib
import sys
import threading
import types
import unittest

sys.argv = ["todo.py"]
sys.path.insert(0, "test")

from async_case import AsyncCase  # noqa: E402
from proxmox_form_context import contexte, setUpModule  # noqa: E402,F401

from script.todo.deploy_form_history import SETTLE_DELAY  # noqa: E402
from script.todo.deploy_form_lib import entry_key  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestFormulaireProxmox(AsyncCase):
    def ecran(self, ctx=None):
        from script.todo.proxmox_deploy_form import run_proxmox_form

        self.app = run_proxmox_form(ctx or contexte(), run_app=False)
        return self.app

    async def calme(self, pilote):
        for _ in range(4):
            await pilote.pause()

    async def ouvert(self, pilote):
        await self.calme(pilote)
        self.app._hist_settle()
        self.assertIsNotNone(self.app._hist)

    def coche(self, *rangs):
        liste = self.app._catalog()
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
        )

    def ram_autre(self, index=0):
        app = self.app
        return [
            v
            for v in app._presets()["ram"]
            if v != app.rows[index]["vm"]["ram"]
        ][0]

    async def test_f6_then_ctrl_z_gives_back_the_plan(self):
        from textual.widgets import Select

        app = self.ecran()
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
            self.coche(0, 1)
            await self.calme(pilote)
            ram = self.ram_autre()
            app.query_one("#v0_ram", Select).value = ram
            await self.calme(pilote)
            await pilote.click("#l1")
            await self.calme(pilote)
            avant = self.etat()
            app._catalog().highlighted = 2
            await pilote.press("f6")
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertEqual(avant, self.etat())
            self.assertEqual(2, self.cartes())
            # Même architecture : la liste n'est pas reconstruite, et garde
            # sa position.
            self.assertEqual(2, app._catalog().highlighted)
            self.assertEqual(ram, app.query_one("#v0_ram", Select).value)

    async def test_back_to_an_empty_plan_shows_no_card(self):
        app = self.ecran()
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
            await pilote.press("f6")
            await self.calme(pilote)
            self.assertGreater(self.cartes(), 0)
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertEqual([], app.rows)
            self.assertEqual(0, self.cartes())

    async def test_an_arch_change_is_undone(self):
        from textual.widgets import RadioButton, RadioSet

        app = self.ecran()
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
            self.coche(1)
            await self.calme(pilote)
            app._hist_settle()
            avant = (app.arch, app._hist_catalog())
            radio = app.query_one("#f_arch", RadioSet)
            list(radio.query(RadioButton))[1].value = True
            await self.calme(pilote)
            self.assertEqual("arm64", app.arch)
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertEqual(avant, (app.arch, app._hist_catalog()))
            self.assertEqual(0, radio.pressed_index)
            self.assertEqual(
                {entry_key(e) for e in app._entries()},
                {o.value for o in app._catalog().options},
            )

    async def test_creating_a_bridge_is_never_replayed(self):
        from textual.widgets import Select

        from script.todo.proxmox_deploy_form import CREER_PONT

        appels = []
        libre = threading.Event()

        def creer():
            # L'hôte met du temps : le relevé tombe pendant la création.
            libre.wait(10)
            appels.append(1)
            return "vmbr9", ""

        ctx = contexte()
        ctx["make_bridge"] = creer
        ctx["internal_bridge"] = ("vmbr9", "10.10.10.1/24")
        app = self.ecran(ctx)
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
            pont = app.query_one("#f_bridge", Select)
            pont.value = CREER_PONT
            await self.calme(pilote)
            self.assertEqual(CREER_PONT, pont.value)
            app._hist_settle()
            self.assertEqual(
                "vmbr0", app._hist.entries[-1]["snap"]["widgets"]["f_bridge"]
            )
            libre.set()
            await app.workers.wait_for_complete()
            await self.calme(pilote)
            self.assertEqual("vmbr9", pont.value)
            app._hist_settle()
            gardes = [
                e["snap"]["widgets"].get("f_bridge") for e in app._hist.entries
            ]
            self.assertNotIn(CREER_PONT, gardes)
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertEqual("vmbr0", pont.value)
            await pilote.press("ctrl+y")
            await self.calme(pilote)
            self.assertEqual("vmbr9", pont.value)
            self.assertEqual(1, len(appels))

    async def test_a_3d_box_offered_midway_is_not_a_change(self):
        from textual.widgets import Button

        ctx = contexte()
        ctx["gpu_offert"] = False
        ctx["gpu_manque"] = "libegl1"
        ctx["installer_gpu"] = lambda paquets: True
        ctx["sonder_gpu"] = lambda: (True, "")
        app = self.ecran(ctx)
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
            app.suspend = lambda: contextlib.nullcontext()
            self.coche(0)
            await self.calme(pilote)
            app._hist_settle()
            app.query_one("#f_gpu_poser", Button).press()
            await self.calme(pilote)
            self.assertTrue(app.query("#f_gpu3d"))
            # La case apparue n'est pas une modification de l'usager.
            avant_annulation = len(app._hist.entries)
            await pilote.pause(SETTLE_DELAY + 0.3)
            app._hist_settle()
            self.assertEqual(avant_annulation, len(app._hist.entries))
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            entrees = len(app._hist.entries)
            await pilote.pause(SETTLE_DELAY + 0.3)
            app._hist_settle()
            self.assertEqual(entrees, len(app._hist.entries))
            self.assertTrue(app.query_one("#f_gpu3d").value)

    async def test_a_restored_profile_keeps_the_restored_overrides(self):
        from textual.widgets import RadioButton, RadioSet, Select

        app = self.ecran()
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
            self.coche(0)
            await self.calme(pilote)
            boutons = list(
                app.query_one("#f_profile", RadioSet).query(RadioButton)
            )
            boutons[1].value = True
            await self.calme(pilote)
            ram = self.ram_autre()
            app.query_one("#v0_ram", Select).value = ram
            await self.calme(pilote)
            app._hist_settle()
            cle = app._row_key(0)
            boutons[4].value = True
            await self.calme(pilote)
            self.assertNotIn("ram", app.overrides.get(cle, {}))
            self.assertFalse(app.query_one("#f_vcpus", Select).disabled)
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertEqual("2", app.profile)
            self.assertEqual(ram, app.overrides[cle]["ram"])
            self.assertEqual(
                1, app.query_one("#f_profile", RadioSet).pressed_index
            )
            self.assertTrue(app.query_one("#f_vcpus", Select).disabled)

    async def test_a_common_free_value_applied_on_enter_is_undone(self):
        from textual.widgets import Input, RadioButton, RadioSet, Select

        from script.todo.deploy_form_lib import FREE

        app = self.ecran()
        async with app.run_test(size=(200, 60)) as pilote:
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
            avant = dict(app.custom)
            saisie = app.query_one("#c_ram", Input)
            saisie.focus()
            for chiffre in "6000":
                await pilote.press(chiffre)
            await pilote.press("enter")
            await self.calme(pilote)
            self.assertEqual(6000, app.custom["ram"])
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertEqual(avant, app.custom)
            self.assertEqual("", saisie.value)
            self.assertTrue(saisie.display)

    async def test_a_free_input_hidden_by_a_profile_comes_back(self):
        from textual.widgets import Input, RadioButton, RadioSet, Select

        from script.todo.deploy_form_lib import FREE

        app = self.ecran()
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
            boutons = list(
                app.query_one("#f_profile", RadioSet).query(RadioButton)
            )
            boutons[4].value = True
            await self.calme(pilote)
            app.query_one("#f_ram", Select).value = FREE
            await self.calme(pilote)
            saisie = app.query_one("#c_ram", Input)
            self.assertTrue(saisie.display)
            app._hist_settle()
            boutons[1].value = True
            await self.calme(pilote)
            self.assertFalse(saisie.display)
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertTrue(saisie.display)
            self.assertFalse(saisie.disabled)

    async def test_a_rename_is_recorded_without_any_message(self):
        from textual.widgets import Input

        app = self.ecran()
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
            self.coche(0)
            await self.calme(pilote)
            app._hist_settle()
            avant = len(app._hist.entries)
            app._rename(0)
            await self.calme(pilote)
            app.screen.query_one("#renval", Input).value = "vm-essai"
            # La frappe dans la fenêtre arme le minuteur : on le laisse
            # passer, sans effet sur le formulaire.
            await pilote.pause(SETTLE_DELAY + 0.3)
            self.assertEqual(avant, len(app._hist.entries))
            app.screen.query_one("#ren_ok").press()
            await self.calme(pilote)
            # Le minuteur, pas un relevé forcé : c'est le recalcul qui doit
            # l'armer, le renommage ne passant par aucun message du
            # formulaire.
            await pilote.pause(SETTLE_DELAY + 0.3)
            self.assertEqual(avant + 1, len(app._hist.entries))
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertNotEqual("vm-essai", app.rows[0]["vm"]["name"])

    async def test_f4_is_its_own_entry_and_gives_back_the_lock(self):
        app = self.ecran()
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
            self.coche(0)
            await self.calme(pilote)
            await pilote.click("#l0")
            await self.calme(pilote)
            cle = app._row_key(0)
            self.assertIn(cle, app.locked)
            app.query_one("#v0_ram").focus()
            await pilote.press("f4")
            await self.calme(pilote)
            self.assertNotIn(cle, app.locked)
            self.assertTrue(app._hist.entries[-1]["label"].startswith("F4"))
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertIn(cle, app.locked)

    async def deux_figees_puis_la_premiere_retiree(self, pilote):
        """Deux VM figées, puis la première décochée : la seconde passe au
        rang 0. Une annulation la remettra au rang 1. Rend leurs clés."""
        app = self.app
        self.coche(0, 1)
        await self.calme(pilote)
        a, b = app._row_key(0), app._row_key(1)
        await pilote.click("#l0")
        await self.calme(pilote)
        await pilote.click("#l1")
        await self.calme(pilote)
        app._hist_settle()
        liste = app._catalog()
        liste.deselect(liste.get_option_at_index(0).value)
        await self.calme(pilote)
        app._hist_settle()
        self.assertEqual((b,), app._row_ids())
        return a, b

    async def test_f4_during_a_restore_resets_the_vm_that_was_shown(self):
        app = self.ecran()
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
            a, b = await self.deux_figees_puis_la_premiere_retiree(pilote)
            app.query_one("#v0_ram").focus()
            await self.calme(pilote)
            self.assertEqual("v0_ram", app.focused.id)
            app.action_undo()
            app.action_clear_vm()
            await self.calme(pilote)
            self.assertEqual((a, b), app._row_ids())
            self.assertEqual(({a}, [a]), (app.locked, list(app.overrides)))
            self.assertTrue(app._hist.entries[-1]["label"].startswith("F4"))

    async def test_a_row_button_during_a_restore_acts_on_the_vm_shown(self):
        app = self.ecran()
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
            a, b = await self.deux_figees_puis_la_premiere_retiree(pilote)
            bouton = app.query_one("#l0")
            app.action_undo()
            app.on_button_pressed(types.SimpleNamespace(button=bouton))
            await self.calme(pilote)
            await pilote.pause(SETTLE_DELAY + 0.3)
            self.assertEqual((a, b), app._row_ids())
            self.assertEqual({a}, app.locked)
            self.assertEqual(len(app._hist.entries) - 1, app._hist.cursor)

    async def test_f5_during_a_restore_deploys_the_restored_plan(self):
        app = self.ecran()
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
            await pilote.press("f6")
            await self.calme(pilote)
            app.action_undo()
            app.action_deploy()
            await self.calme(pilote)
            self.assertIsNone(app.result)
            self.assertTrue(app.is_running)

    async def test_f7_ticks_the_default_versions_and_is_undone(self):
        ctx = contexte()
        # Le vrai catalogue marque la version par défaut de chaque système.
        ctx["catalog"]["amd64"][1]["default"] = True
        app = self.ecran(ctx)
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
            self.coche(2)
            await self.calme(pilote)
            await pilote.press("f7")
            await self.calme(pilote)
            attendu = (entry_key(ctx["catalog"]["amd64"][1]),)
            self.assertEqual(attendu, app._hist_catalog())
            self.assertEqual(1, len(app.rows))
            self.assertTrue(app._hist.entries[-1]["label"].startswith("F7"))
            await pilote.press("ctrl+z")
            await self.calme(pilote)
            self.assertTrue(app.is_running)
            self.assertEqual(
                (entry_key(ctx["catalog"]["amd64"][2]),), app._hist_catalog()
            )

    async def test_a_foreign_value_in_the_list_does_not_stop_the_history(self):
        app = self.ecran()
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
            # Textual accepte de cocher une valeur qu'aucune option ne porte.
            app._catalog().select(1)
            self.coche(0)
            await self.calme(pilote)
            app._hist_settle()
            self.assertEqual(2, len(app._hist.entries))
            self.assertEqual(
                (app._catalog().get_option_at_index(0).value,),
                app._hist_catalog(),
            )

    async def test_a_free_value_typed_without_enter_is_not_a_state(self):
        from textual.widgets import Input, RadioButton, RadioSet, Select

        from script.todo.deploy_form_lib import FREE

        app = self.ecran()
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
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
            for chiffre in "6000":
                await pilote.press(chiffre)
            await pilote.pause(SETTLE_DELAY + 0.3)
            self.assertEqual(avant, len(app._hist.entries))
            await pilote.press("enter")
            await pilote.pause(SETTLE_DELAY + 0.3)
            self.assertEqual(avant + 1, len(app._hist.entries))

    async def test_a_change_while_the_list_is_open_is_kept(self):
        from textual.widgets import Checkbox

        app = self.ecran()
        async with app.run_test(size=(200, 60)) as pilote:
            await self.ouvert(pilote)
            self.coche(0)
            await self.calme(pilote)
            app._hist_settle()
            app._catalog().focus()
            await pilote.press("h")
            await self.calme(pilote)
            self.assertEqual("HistoryScreen", type(app.screen).__name__)
            # Ce qu'un fil peut poser pendant que la liste est ouverte.
            app.query_one("#f_start", Checkbox).value = False
            await pilote.press("end")
            await pilote.press("enter")
            await self.calme(pilote)
            gardes = [
                e["snap"]["widgets"]["f_start"] for e in app._hist.entries
            ]
            self.assertIn(False, gardes)

    async def test_offline_and_the_monitor_it_forces_come_back(self):
        from textual.widgets import Checkbox

        app = self.ecran()
        async with app.run_test(size=(200, 70)) as pilote:
            await self.ouvert(pilote)
            suivi = app.query_one("#f_monitor", Checkbox)
            coupe = app.query_one("#f_offline", Checkbox)
            suivi.value = False
            await self.calme(pilote)
            app._hist_settle()
            coupe.value = True
            await self.calme(pilote)
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
            coupe.value = False
            await self.calme(pilote)
            self.assertFalse(suivi.value)


if __name__ == "__main__":
    unittest.main()
