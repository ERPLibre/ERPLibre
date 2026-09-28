#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le formulaire de déploiement Proxmox VE, monté sans terminal.

Séparé de `test_proxmox_form.py` pour la durée : chaque cas monte l'écran,
et les deux fichiers tournent en parallèle dans le lanceur unitaire.
"""

import asyncio
import os
import sys
import unittest

sys.argv = ["todo.py"]
from script.todo.proxmox_deploy_form import run_proxmox_form  # noqa: E402

# Le module d'appui voisin, comme llm_fake_server : test/ n'est pas un
# paquet, son répertoire entre donc à la main dans le chemin.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# setUpModule est lu par unittest dans CE module : l'importer suffit.
from proxmox_form_context import contexte, setUpModule  # noqa: E402,F401

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestEcran(unittest.TestCase):
    """Le formulaire, monté sans terminal."""

    def _rendu(self, gestes):
        ctx = contexte()
        resultat = {}

        async def scenario():
            from textual.widgets import SelectionList

            app = run_proxmox_form(ctx, run_app=False)
            async with app.run_test(size=(200, 50)) as pilote:
                await pilote.pause()
                liste = app.query_one(SelectionList)
                for i in range(3):
                    liste.select(liste.get_option_at_index(i).value)
                await pilote.pause()
                await pilote.pause()
                await gestes(app, pilote)
                # Relevé AVANT la sortie du contexte : `run_test` démonte
                # l'écran, et « #totals » n'existe plus après.
                from textual.widgets import Static

                widget = app.query_one("#totals", Static)
                app.ligne_totaux = str(
                    getattr(widget, "_content", "") or widget.render()
                )
                resultat["app"] = app

        asyncio.run(scenario())
        return resultat["app"]

    def test_the_plan_shows_a_row_per_selected_system(self):
        async def rien(app, pilote):
            pass

        app = self._rendu(rien)
        self.assertEqual(len(app.rows), 3)

    def test_the_head_line_carries_the_vmid_and_the_address(self):
        async def rien(app, pilote):
            pass

        app = self._rendu(rien)
        tete = app._row_head(0, app.rows[0])
        self.assertIn("VMID", tete)
        self.assertIn("10.10.10.", tete)

    def test_an_existing_vm_is_marked_and_gets_no_vmid(self):
        async def rien(app, pilote):
            pass

        app = self._rendu(rien)
        deja = [r for r in app.rows if r["state"] == "exists"]
        self.assertEqual(len(deja), 1)
        self.assertNotIn("VMID", app._row_head(1, deja[0]))

    def test_mounting_does_not_mark_every_row_as_custom(self):
        # Poser « value= » sur un Select fait émettre un Changed : pris pour
        # une saisie, il surchargeait les trois champs de CHAQUE VM et toutes
        # les rangées portaient la marque ✎ avant qu'on ne touche à rien.
        async def rien(app, pilote):
            pass

        app = self._rendu(rien)
        self.assertEqual(app.overrides, {})
        self.assertNotIn("✎", app._row_head(0, app.rows[0]))

    def test_a_lock_survives_a_common_setting(self):
        async def gestes(app, pilote):
            app._set_lock(0, True)
            await pilote.pause()
            app.custom["ram"] = 8192
            app.profile = "custom"
            app._clear_overrides(("ram",))
            app._recompute()
            await pilote.pause()

        app = self._rendu(gestes)
        self.assertEqual(app.rows[0]["vm"]["ram"], 2048)

    def test_a_copy_adds_a_vm_with_its_own_vmid(self):
        async def gestes(app, pilote):
            app._add_copy(0, 1)
            await pilote.pause()

        app = self._rendu(gestes)
        self.assertEqual(len(app.rows), 4)
        vmids = [r["vm"]["vmid"] for r in app.rows if r["state"] != "exists"]
        self.assertEqual(len(vmids), len(set(vmids)))

    def test_deploying_yields_a_spec_the_engine_can_run(self):
        async def gestes(app, pilote):
            app.action_deploy()

        app = self._rendu(gestes)
        spec = app.result
        self.assertEqual(len(spec["vms"]), 2)
        self.assertEqual(spec["existing"], ["erplibre-debian-13"])
        self.assertEqual(spec["storage"], "local-lvm")
        self.assertEqual(spec["bridge"], "vmbr0")
        for vm in spec["vms"]:
            self.assertIn("vmid", vm)
            self.assertIn("ip=", vm["ipconfig"])
        self.assertEqual(spec["install"]["branch"], "develop")

    def _totaux(self, app):
        return app.ligne_totaux

    def test_the_totals_line_shows_the_room_left_on_the_storage(self):
        async def rien(app, pilote):
            pass

        ligne = self._totaux(self._rendu(rien))
        # « pvesm status » donne déjà la place : la demande du plan s'affiche
        # donc à côté d'elle, sans un aller-retour de plus vers l'hôte.
        self.assertIn("/ 90 G", ligne)
        self.assertIn("local-lvm", ligne)

    def test_changing_the_storage_changes_the_room(self):
        # La marque de génération ne vaut que pour les widgets de RANGÉE :
        # l'exiger des widgets globaux faisait taire tous les réglages
        # communs, stockage compris.
        async def gestes(app, pilote):
            from textual.widgets import Select

            app.query_one("#f_storage", Select).value = "local"
            await pilote.pause()
            await pilote.pause()

        ligne = self._totaux(self._rendu(gestes))
        self.assertIn("/ 12 G", ligne)
        self.assertIn("local", ligne)

    def test_a_plan_bigger_than_the_storage_is_flagged(self):
        async def gestes(app, pilote):
            from textual.widgets import Select

            app.query_one("#f_storage", Select).value = "local"
            await pilote.pause()
            await pilote.pause()

        self.assertIn("⚠", self._totaux(self._rendu(gestes)))

    def test_a_common_setting_reaches_every_vm(self):
        async def gestes(app, pilote):
            # « value = True » sur le bouton : action_next_button() ne
            # déplace que la surbrillance et n'émet aucun message.
            list(app.query("#f_profile RadioButton"))[2].value = True
            await pilote.pause()
            await pilote.pause()

        app = self._rendu(gestes)
        self.assertEqual(app.profile, "3")
        self.assertTrue(all(r["vm"]["ram"] == 6144 for r in app.rows))

    def test_the_resource_label_survives_the_markup(self):
        # « [x1] » se faisait manger : Static lit le balisage Rich, et une
        # balise inconnue disparaît avec son contenu.
        async def rien(app, pilote):
            pass

        self.assertIn("x1", self._totaux(self._rendu(rien)))

    def test_a_nested_proxmox_guest_installs_its_hypervisor(self):
        # Même défaut que sur l'écran QEMU/KVM avant correction : un Proxmox
        # imbriqué recevait ERPLibre et Odoo 18.
        async def gestes(app, pilote):
            from textual.widgets import SelectionList

            liste = app.query_one(SelectionList)
            liste.select(liste.get_option_at_index(3).value)
            await pilote.pause()
            await pilote.pause()

        app = self._rendu(gestes)
        par = {r["vm"]["distro"]: r for r in app.rows}
        self.assertEqual(
            par["proxmox"]["vm"]["install_cmd"],
            "./script/proxmox/install_proxmox.sh",
        )
        # Et ses voisines gardent le choix commun.
        self.assertEqual(par["ubuntu"]["vm"]["install_cmd"], "")
        # Cinq gigaoctets pour un dépôt qu'elle ne clonera pas.
        self.assertEqual(par["proxmox"]["disk_gb"], 32)
        self.assertEqual(par["ubuntu"]["disk_gb"], 42)

    def test_text_prompts_are_not_a_cancellation(self):
        # {} n'est pas None : l'appelant distingue « annulé » de
        # « pose-moi les questions à l'ancienne ».
        async def gestes(app, pilote):
            from textual.widgets import Button

            app.on_button_pressed(
                type("E", (), {"button": Button("x", id="prompts")})()
            )

        app = self._rendu(gestes)
        self.assertEqual(app.result, {})

    def test_cancelling_yields_nothing(self):
        async def gestes(app, pilote):
            app.action_cancel()

        self.assertIsNone(self._rendu(gestes).result)


if __name__ == "__main__":
    unittest.main()
