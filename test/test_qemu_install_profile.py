#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'un système IMPOSE d'installer sur la VM.

Choisir « Proxmox VE » comme système, c'est demander qu'il soit installé : ni
ERPLibre ni Odoo n'ont leur place sur un hyperviseur. L'invite en ligne le
savait déjà — elle remontait le profil hyperviseur en tête — mais le
formulaire, lui, posait « ERPLibre + Odoo 18 » par défaut, et lui ajoutait
même les cinq gigaoctets réservés au dépôt ERPLibre.

La règle vit maintenant en un seul endroit et les deux chemins la lisent. Ces
tests gardent les deux, plus le fait qu'un choix explicite l'emporte toujours
sur elle.
"""

import asyncio
import builtins
import contextlib
import io
import sys
import unittest

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False

PVE_CMD = "./script/proxmox/install_proxmox.sh"


class TestLaRegle(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_proxmox_imposes_the_hypervisor_profile(self):
        label, cmd = self.todo._qemu_distro_profile("proxmox")
        self.assertEqual(cmd, PVE_CMD)
        self.assertIn("Proxmox", label)

    def test_an_ordinary_system_imposes_nothing(self):
        for distro in ("ubuntu", "debian", "fedora", "arch"):
            self.assertIsNone(self.todo._qemu_distro_profile(distro))

    def test_every_mapped_label_still_exists_in_the_list(self):
        # La table désigne un profil PAR SON LIBELLÉ : renommer le profil sans
        # toucher la table ferait disparaître la règle en silence.
        for distro in self.todo._QEMU_DISTRO_PROFILE:
            self.assertIsNotNone(
                self.todo._qemu_distro_profile(distro), distro
            )

    def test_the_prompt_offers_it_first(self):
        # Réponse vide = premier de la liste : c'est ce qui rend le défaut.
        with contextlib.redirect_stdout(io.StringIO()):
            vrai_input, builtins.input = builtins.input, lambda _p="": ""
            try:
                label, cmd = self.todo._qemu_pick_install_profile("proxmox")
                ordinaire = self.todo._qemu_pick_install_profile("ubuntu")
            finally:
                builtins.input = vrai_input
        self.assertEqual(cmd, PVE_CMD)
        self.assertIn("odoo_18", ordinaire[1])


class TestUneSeuleVM(unittest.TestCase):
    """Le piège du parc d'UNE machine.

    L'exécution ne passait à une commande par VM que si DEUX VM différaient
    entre elles. Déployée seule, une VM Proxmox donnait un ensemble d'un seul
    élément : tout retombait sur le choix commun, et l'hyperviseur recevait
    ERPLibre et Odoo 18 — le défaut corrigé dans le formulaire, réintroduit à
    l'exécution."""

    def test_a_lone_vm_with_its_own_command_needs_the_map(self):
        self.assertTrue(
            TODO._qemu_per_vm({"a": PVE_CMD}, "make install_odoo_18")
        )

    def test_a_lone_vm_on_the_common_choice_does_not(self):
        self.assertFalse(
            TODO._qemu_per_vm(
                {"a": "make install_odoo_18"}, "make install_odoo_18"
            )
        )

    def test_two_identical_vms_do_not(self):
        self.assertFalse(TODO._qemu_per_vm({"a": "x", "b": "x"}, "x"))

    def test_two_different_vms_do(self):
        self.assertTrue(TODO._qemu_per_vm({"a": "x", "b": "y"}, "x"))

    def test_an_empty_plan_never_asks_for_a_map(self):
        # Une carte vide passée à l'installateur y serait prise pour une
        # commande : le repli sur le choix commun est le seul sûr.
        self.assertFalse(TODO._qemu_per_vm({}, "x"))

    def test_the_same_trap_held_for_the_branch(self):
        self.assertTrue(TODO._qemu_per_vm({"a": "master"}, "develop"))


class TestLaCommandeConstruite(unittest.TestCase):
    """La commande deploy_qemu.py doit dire la même chose que le plan."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def _parts(self, distro, disque, cmd_vm="", installe=True):
        vm = {
            "name": "essai",
            "distro": distro,
            "version": "24.04" if distro == "ubuntu" else "9",
            "arch": "amd64",
            "vcpus": 2,
            "ram": 2048,
            "disk": disque,
            "desktop": "",
            "branch": "",
            "install_cmd": cmd_vm,
            "install_label": "",
        }
        spec = {
            "vms": [vm],
            "existing": [],
            "ssh_key": "",
            "timezone": "",
            "desktop": "",
            "vm_tools": (),
            "python_provider": "",
            "app_store": "deb",
            "install": (
                {
                    "branch": "develop",
                    "prod": False,
                    "label": "x",
                    "monitor": True,
                    "cmd": "make install_os && make install_odoo_18",
                }
                if installe
                else None
            ),
            "monitor": True,
            "add_ssh_config": True,
            "parallelism": 1,
            "res_label": "x1",
        }
        return self.todo._qemu_deploy_parts_for(vm, spec, dry_run=True)

    def _taille(self, parts):
        return parts[parts.index("--disk-size") + 1]

    def test_a_proxmox_vm_gets_no_erplibre_margin(self):
        parts = self._parts("proxmox", "32G", PVE_CMD)
        self.assertEqual(self._taille(parts), "32G")

    def test_an_ordinary_vm_keeps_its_margin(self):
        parts = self._parts("ubuntu", "20G")
        self.assertEqual(self._taille(parts), "25G")

    def test_a_proxmox_vm_advertises_no_erplibre_in_its_guide(self):
        # Le guide affiché à la connexion SSH ne doit pas annoncer un dépôt
        # qui n'existera pas sur cette VM.
        parts = self._parts("proxmox", "32G", PVE_CMD)
        self.assertNotIn("--erplibre-make", parts)
        self.assertNotIn("--erplibre-dir", parts)
        self.assertIn("--erplibre-dir", self._parts("ubuntu", "20G"))

    def test_a_chosen_size_is_never_dropped(self):
        # Sans le drapeau, deploy_qemu.py reprend la taille du catalogue : une
        # VM réglée à 60 G mais sans rien à installer repartait à 20 G.
        parts = self._parts("ubuntu", "60G", installe=False)
        self.assertEqual(self._taille(parts), "60G")


def contexte():
    todo = TODO.__new__(TODO)
    mod = todo._qemu_import_module()
    todo._qemu_list_domains = lambda: []
    todo._qemu_branch_list = lambda: ["develop", "master"]
    return todo._qemu_form_context(mod)


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLeFormulaire(unittest.TestCase):
    """Le formulaire doit appliquer la règle AU MODÈLE : le déploiement lit
    « install_cmd » VM par VM, pas ce que la liste affiche."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = contexte()
        cls.rangs = {}
        for i, e in enumerate(cls.ctx["catalog"]["amd64"]):
            cls.rangs.setdefault(e["distro"], i)

    def _plan(self, distros, gestes=None):
        from script.todo.qemu_deploy_form import run_deploy_form

        vu = {}

        async def scenario():
            from textual.widgets import SelectionList

            app = run_deploy_form(self.ctx, run_app=False)
            async with app.run_test(size=(200, 50)) as pilote:
                await pilote.pause()
                liste = app.query_one(SelectionList)
                for d in distros:
                    liste.select(
                        liste.get_option_at_index(self.rangs[d]).value
                    )
                await pilote.pause()
                await pilote.pause()
                if gestes:
                    await gestes(app, pilote)
                vu["app"] = app
                vu["par_distro"] = {r["vm"]["distro"]: r for r in app.rows}

        asyncio.run(scenario())
        return vu

    def test_a_proxmox_vm_installs_the_hypervisor_not_erplibre(self):
        r = self._plan(["proxmox"])["par_distro"]["proxmox"]
        self.assertEqual(r["vm"]["install_cmd"], PVE_CMD)
        self.assertIn("Proxmox", r["vm"]["install_label"])

    def test_an_ordinary_vm_still_follows_the_common_choice(self):
        # « » sur une VM veut dire « le choix du formulaire » : le déploiement
        # y met alors la commande commune.
        r = self._plan(["ubuntu"])["par_distro"]["ubuntu"]
        self.assertEqual(r["vm"]["install_cmd"], "")

    def test_a_mixed_plan_gives_each_vm_its_own(self):
        par = self._plan(["proxmox", "ubuntu"])["par_distro"]
        self.assertEqual(par["proxmox"]["vm"]["install_cmd"], PVE_CMD)
        self.assertEqual(par["ubuntu"]["vm"]["install_cmd"], "")

    def test_the_erplibre_disk_supplement_skips_it(self):
        # Cinq gigaoctets pour un dépôt qu'une VM Proxmox ne clonera pas.
        par = self._plan(["proxmox", "ubuntu"])["par_distro"]
        pve, ubu = par["proxmox"], par["ubuntu"]
        self.assertEqual(pve["disk_gb"], int(pve["vm"]["disk"].rstrip("G")))
        self.assertGreater(ubu["disk_gb"], int(ubu["vm"]["disk"].rstrip("G")))

    def test_mounting_marks_nothing_as_customised(self):
        # Le disque de Proxmox (32 G) n'est pas dans les préréglages : sa
        # saisie libre émettait un Changed au montage, écrit comme une
        # surcharge, et la rangée s'affichait ✎ sans qu'on l'ait touchée.
        app = self._plan(["proxmox"])["app"]
        self.assertEqual(app.overrides, {})
        self.assertNotIn("✎", app._row_head(0, app.rows[0]))

    def test_an_explicit_choice_beats_the_rule(self):
        async def gestes(app, pilote):
            from textual.widgets import Select

            app.query_one("#v0_prof", Select).value = 0  # ERPLibre + Odoo 18
            await pilote.pause()
            await pilote.pause()

        r = self._plan(["proxmox"], gestes)["par_distro"]["proxmox"]
        self.assertIn("odoo_18", r["vm"]["install_cmd"])

    def test_resetting_the_row_returns_to_the_rule(self):
        async def gestes(app, pilote):
            from textual.widgets import Select

            app.query_one("#v0_prof", Select).value = 0
            await pilote.pause()
            app.query_one("#v0_prof", Select).focus()
            await pilote.pause()
            app.action_clear_vm()
            await pilote.pause()
            await pilote.pause()

        r = self._plan(["proxmox"], gestes)["par_distro"]["proxmox"]
        self.assertEqual(r["vm"]["install_cmd"], PVE_CMD)

    def test_a_real_keystroke_still_lands(self):
        # La règle de l'écho ne doit pas avaler une VRAIE saisie.
        async def gestes(app, pilote):
            from textual.widgets import Input

            app.query_one("#c0_disk", Input).value = "60G"
            await pilote.pause()
            await pilote.pause()

        r = self._plan(["proxmox"], gestes)["par_distro"]["proxmox"]
        self.assertEqual(r["vm"]["disk"], "60G")


if __name__ == "__main__":
    unittest.main(verbosity=2)
