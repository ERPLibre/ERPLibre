#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La case d'installation : son nom, sa place, et ce qu'elle grise.

Elle s'appelait « Installer ERPLibre » alors qu'elle commande TOUTE
installation — l'hyperviseur Proxmox VE compris. Rapporté après coup : une VM
Proxmox déployée avec la case décochée est restée une Debian nue, et rien ne
disait que la case l'expliquait.

Elle est donc renommée, placée juste sous le type de VM (les sections qu'elle
commande viennent après), et ce qu'elle rend sans effet se grise. Trois états
et non deux : sans installation mais avec un bureau, il se pose encore des
paquets — griser le magasin d'applications mentirait autant que de laisser
actif ce qui ne fait rien.
"""

import asyncio
import sys
import unittest
from pathlib import Path

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

FORM = (
    Path(__file__).resolve().parent.parent / "script/todo/qemu_deploy_form.py"
)

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False


class TestSaPlace(unittest.TestCase):
    """L'ordre du panneau est une décision, pas un hasard.

    Relevé sur l'ÉCRAN MONTÉ et non dans la source : depuis que les réglages
    du système invité viennent d'un socle partagé, le fichier ne contient
    plus qu'un « yield from » là où le test cherchait un identifiant. Il
    passait au vert sur un écran qu'il ne lisait plus — puis au rouge sans
    qu'aucun ordre ait bougé. Le DOM, lui, dit ce que l'utilisateur voit."""

    @classmethod
    def setUpClass(cls):
        cls.src = FORM.read_text(encoding="utf-8")
        cls.ordre = ordre_du_panneau(contexte()) if TEXTUAL else []

    def _rang(self, ident):
        self.assertIn(ident, self.ordre, ident)
        return self.ordre.index(ident)

    @unittest.skipUnless(TEXTUAL, "Textual absent")
    def test_the_install_section_sits_under_the_vm_type(self):
        self.assertLess(self._rang("f_type"), self._rang("t_install"))

    @unittest.skipUnless(TEXTUAL, "Textual absent")
    def test_and_before_the_sections_it_commands(self):
        # Magasin d'applications, outils : ils dépendent d'elle, donc ils
        # viennent après.
        for apres in ("t_store", "t_tools"):
            self.assertLess(self._rang("t_install"), self._rang(apres))

    def test_the_checkbox_no_longer_claims_to_be_about_erplibre(self):
        self.assertNotIn('t("Install ERPLibre")', self.src)

    @unittest.skipUnless(TEXTUAL, "Textual absent")
    def test_the_monitor_left_the_install_section(self):
        # Rangé dedans, il se serait grisé avec elle — et décocher ERPLibre
        # avait déjà fait disparaître le tableau de bord une fois.
        self.assertLess(self._rang("t_deploy"), self._rang("f_monitor"))


def ordre_du_panneau(ctx, forme="qemu"):
    """Les identifiants du panneau gauche, dans l'ordre où ils s'affichent."""
    from script.todo.proxmox_deploy_form import run_proxmox_form
    from script.todo.qemu_deploy_form import run_deploy_form

    vu = []

    async def scenario():
        app = (
            run_deploy_form(ctx, run_app=False)
            if forme == "qemu"
            else run_proxmox_form(ctx, run_app=False)
        )
        async with app.run_test(size=(200, 60)) as pilote:
            await pilote.pause()
            vu.extend(w.id for w in app.query("#fields *") if w.id)

    asyncio.run(scenario())
    return vu


def contexte():
    todo = TODO.__new__(TODO)
    mod = todo._qemu_import_module()
    todo._qemu_list_domains = lambda: []
    todo._qemu_branch_list = lambda: ["develop", "master"]
    return todo._qemu_form_context(mod)


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestCeQuElleGrise(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = contexte()

    def _etats(self):
        """Relève l'état des champs dans les trois situations."""
        from script.todo.qemu_deploy_form import run_deploy_form

        vu = {}

        async def scenario():
            from textual.widgets import Checkbox, SelectionList

            app = run_deploy_form(self.ctx, run_app=False)
            async with app.run_test(size=(200, 60)) as pilote:
                await pilote.pause()
                liste = app.query_one(SelectionList)
                liste.select(liste.get_option_at_index(0).value)
                await pilote.pause()
                await pilote.pause()

                def relever():
                    etat = {}
                    for cible in (
                        "f_branch",
                        "f_profile_install",
                        "f_python",
                        "f_prod",
                        "f_store",
                        "f_type",
                        "f_monitor",
                        "v0_branch",
                        "v0_prof",
                    ):
                        try:
                            etat[cible] = app.query_one(f"#{cible}").disabled
                        except Exception:
                            etat[cible] = None
                    etat["outils"] = {
                        w.id[7:]: w.disabled
                        for w in app.query(Checkbox)
                        if str(w.id or "").startswith("f_tool_")
                    }
                    etat["titres"] = {
                        w.id
                        for w in app.query("#fields Static")
                        if "off" in w.classes
                    }
                    return etat

                vu["installe"] = relever()
                app.query_one("#f_install", Checkbox).value = False
                await pilote.pause()
                await pilote.pause()
                vu["rien"] = relever()
                list(app.query("#f_type RadioButton"))[1].value = True
                await pilote.pause()
                await pilote.pause()
                vu["bureau_seul"] = relever()
                # Retour au SERVEUR avant de recocher : le magasin
                # d'applications a sa propre raison de se griser (aucune VM
                # graphique sur une distribution à snap), et comparer deux
                # états de type différent ne dirait rien de la case.
                list(app.query("#f_type RadioButton"))[0].value = True
                app.query_one("#f_install", Checkbox).value = True
                await pilote.pause()
                await pilote.pause()
                vu["recoche"] = relever()

        asyncio.run(scenario())
        return vu

    @classmethod
    def etats(cls):
        if not hasattr(cls, "_vu"):
            cls._vu = cls()._etats()
        return cls._vu

    def test_the_branch_and_the_profile_only_serve_an_install(self):
        vu = self.etats()
        for champ in ("f_branch", "f_profile_install", "v0_branch", "v0_prof"):
            self.assertFalse(vu["installe"][champ], champ)
            self.assertTrue(vu["rien"][champ], champ)
            # Même avec un bureau : ils ne servent QU'à ERPLibre.
            self.assertTrue(vu["bureau_seul"][champ], champ)

    def test_a_desktop_only_install_keeps_what_it_really_uses(self):
        # Le magasin d'applications et « production » servent encore : la
        # commande distante pose des paquets et coupe les mises à jour.
        vu = self.etats()
        self.assertTrue(vu["rien"]["f_store"])
        self.assertFalse(vu["bureau_seul"]["f_store"])
        self.assertTrue(vu["rien"]["f_prod"])
        self.assertFalse(vu["bureau_seul"]["f_prod"])

    def test_the_tools_that_live_in_the_repository_need_the_install(self):
        # « after » = dans le dépôt ERPLibre. Sans installation, ils n'ont
        # rien où s'installer, bureau ou pas — la commande distante les saute.
        vu = self.etats()
        phases = self.ctx["vm_tool_phases"]
        apres = [k for k, v in phases.items() if v == "after"]
        avant = [k for k, v in phases.items() if v != "after"]
        self.assertTrue(apres and avant, phases)
        for k in apres:
            self.assertTrue(vu["bureau_seul"]["outils"][k], k)
        for k in avant:
            self.assertFalse(vu["bureau_seul"]["outils"][k], k)
        for k in phases:
            self.assertTrue(vu["rien"]["outils"][k], k)

    def test_the_vm_type_and_the_dashboard_are_never_greyed(self):
        # Le type est l'AUTRE moitié de la décision ; le suivi regarde la VM
        # arriver même quand rien ne s'installe.
        vu = self.etats()
        for cas in ("installe", "rien", "bureau_seul"):
            self.assertFalse(vu[cas]["f_type"], cas)
            self.assertFalse(vu[cas]["f_monitor"], cas)

    def test_a_greyed_section_reads_as_inactive(self):
        vu = self.etats()
        self.assertEqual(vu["installe"]["titres"], set())
        self.assertIn("t_store", vu["rien"]["titres"])
        self.assertIn("t_tools", vu["rien"]["titres"])

    def test_ticking_it_back_restores_everything(self):
        vu = self.etats()
        for champ, valeur in vu["recoche"].items():
            if champ in ("outils", "titres"):
                continue
            self.assertEqual(valeur, vu["installe"][champ], champ)


if __name__ == "__main__":
    unittest.main(verbosity=2)
