#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le formulaire d'un parc OpenTofu, monté sans terminal.

Un moteur factice enregistre ses appels et rend des changements figés :
aucun `tofu`, aucun réseau. Le coffre vit dans un dossier temporaire.
"""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ["todo.py"]
from script.opentofu import coffre  # noqa: E402
from script.opentofu import spec as sp  # noqa: E402
from script.opentofu.moteur import Changement, Resultat  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from script.todo.opentofu_form import (  # noqa: E402
    run_opentofu_form,
    vm_depuis_saisie,
)

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False

_LANGUE_ORIGINE = todo_i18n._current_lang
# Jeton inventé : il ne doit apparaître dans aucun widget.
_JETON = "tofu@pve!parc-a=0f0f0f0f-fausse-valeur-de-jeton"


def setUpModule():
    """Fixe « fr » en mémoire. set_lang() écrirait env_var.sh, qui est suivi."""
    todo_i18n._current_lang = "fr"


def tearDownModule():
    todo_i18n._current_lang = _LANGUE_ORIGINE


class FauxMoteur:
    """Moteur qui note ses appels ; `planifier` résout le stockage."""

    nom = "tofu"

    def __init__(self, racine, changements=None):
        self.racine = Path(racine)
        self.appels = []
        self.changements = changements or [
            Changement("creer", "parc-a-vm-1", "vm")
        ]

    def binaire(self):
        return None

    def planifier(self, spec, journal):
        self.appels.append("planifier")
        journal("ligne du moteur")
        spec["cible"]["stockage"] = "local-lvm"
        return Resultat(True, "plan prêt"), list(self.changements)

    def appliquer(self, spec, journal):
        self.appels.append("appliquer")
        return Resultat(True, "appliqué")

    def detruire(self, spec, journal):
        self.appels.append("detruire")
        return Resultat(True, "détruit")


def _textes(app):
    """Tout le texte affiché : chaque widget de chaque écran, onglets cachés
    compris, plus la capture de l'écran visible."""
    from textual.widgets import Button, DataTable, Input, Log, Static

    out = []
    for ecran in app.screen_stack:
        for w in ecran.query("*"):
            if isinstance(w, Input):
                out.append(w.value)
            elif isinstance(w, Log):
                out.extend(w.lines)
            elif isinstance(w, DataTable):
                for i in range(w.row_count):
                    out.extend(str(c) for c in w.get_row_at(i))
            elif isinstance(w, (Static, Button)):
                out.append(str(w.render()))
    out.append(app.export_screenshot())
    return "\n".join(out)


class TestSaisie(unittest.TestCase):
    def test_entiers_convertis_texte_garde(self):
        base = sp.nouvelle_spec("parc-a", "hote-x")["vms"][0]
        vm = vm_depuis_saisie(
            base,
            {
                "vcpus": "4",
                "ram": "abc",
                "vmid": "",
                "dns": "1.1.1.1, 9.9.9.9",
            },
        )
        self.assertEqual(vm["vcpus"], 4)
        self.assertEqual(vm["ram"], "abc")
        self.assertIsNone(vm["vmid"])
        self.assertEqual(vm["dns"], ["1.1.1.1", "9.9.9.9"])
        self.assertEqual(base["vcpus"], 2)


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestEcran(unittest.TestCase):
    def _rendu(self, gestes, changements=None, jeton=None):
        with tempfile.TemporaryDirectory() as racine:
            if jeton:
                coffre.ecrire("parc-a", {"jeton": jeton}, racine)
            moteur = FauxMoteur(racine, changements)
            sauves = []
            resultat = {}

            async def scenario():
                spec = sp.nouvelle_spec("parc-a", "hote-x")
                app = run_opentofu_form(
                    spec, moteur, sauves.append, run_app=False
                )
                async with app.run_test(size=(200, 50)) as pilote:
                    await pilote.pause()
                    resultat["sortie"] = await gestes(app, pilote)
                    resultat["app"] = app

            asyncio.run(scenario())
        return resultat["app"], moteur, sauves, resultat["sortie"]

    @staticmethod
    async def _attendre(app, pilote):
        await app.workers.wait_for_complete()
        await pilote.pause()
        await pilote.pause()

    async def _onglet_vm(self, app, pilote):
        from textual.widgets import TabbedContent

        app.query_one(TabbedContent).active = "tab_vm"
        await pilote.pause()

    def test_ajouter_une_vm_puis_sauver(self):
        async def gestes(app, pilote):
            await self._onglet_vm(app, pilote)
            await pilote.click("#vm_ajouter")
            await pilote.pause()
            await pilote.click("#vmf_ok")
            await pilote.pause()
            await pilote.press("s")
            await pilote.pause()

        app, _, sauves, _ = self._rendu(gestes)
        self.assertEqual(len(sauves), 1)
        noms = [vm["nom"] for vm in sauves[0]["vms"]]
        self.assertEqual(noms, ["parc-a-vm-1", "parc-a-vm-2"])
        self.assertEqual(app.result["vms"], sauves[0]["vms"])

    def test_ram_invalide_affiche_l_erreur_et_ne_sauve_pas(self):
        async def gestes(app, pilote):
            from textual.widgets import Input, Static

            await self._onglet_vm(app, pilote)
            await pilote.click("#vm_editer")
            await pilote.pause()
            app.screen.query_one("#vmf_ram", Input).value = "abc"
            await pilote.click("#vmf_ok")
            await pilote.pause()
            erreur = str(app.screen.query_one("#vmf_erreurs", Static).render())
            return erreur, type(app.screen).__name__

        app, _, sauves, (erreur, ecran) = self._rendu(gestes)
        self.assertIn("ram", erreur)
        self.assertEqual(ecran, "EcranVM")
        self.assertEqual(sauves, [])
        self.assertEqual(app.s["vms"][0]["ram"], 4096)
        self.assertIsNone(app.result)

    def test_plan_remplit_le_panneau_et_reprend_la_resolution(self):
        async def gestes(app, pilote):
            from textual.widgets import Input, Log

            await pilote.press("p")
            await self._attendre(app, pilote)
            return (
                list(app.query_one("#plan", Log).lines),
                list(app.query_one("#journal", Log).lines),
                app.query_one("#c_stockage", Input).value,
            )

        _, moteur, sauves, (plan, journal, stockage) = self._rendu(gestes)
        self.assertEqual(moteur.appels, ["planifier"])
        self.assertIn("+ créer parc-a-vm-1 (vm)", plan)
        self.assertIn("ligne du moteur", journal)
        self.assertEqual(stockage, "local-lvm")
        self.assertEqual(sauves[-1]["cible"]["stockage"], "local-lvm")

    async def _retaper(self, app, pilote, touche, nom):
        from textual.widgets import Input

        await pilote.press(touche)
        await pilote.pause()
        app.screen.query_one("#nom_saisie", Input).value = nom
        await pilote.click("#nom_ok")
        await self._attendre(app, pilote)

    def test_detruire_avec_un_mauvais_nom_n_appelle_pas_le_moteur(self):
        async def gestes(app, pilote):
            await self._retaper(app, pilote, "d", "parc-b")

        _, moteur, _, _ = self._rendu(gestes)
        self.assertEqual(moteur.appels, [])

    def test_detruire_avec_le_bon_nom_appelle_le_moteur(self):
        async def gestes(app, pilote):
            await self._retaper(app, pilote, "d", "parc-a")

        _, moteur, _, _ = self._rendu(gestes)
        self.assertEqual(moteur.appels, ["detruire"])

    def test_appliquer_sans_plan_n_appelle_pas_le_moteur(self):
        async def gestes(app, pilote):
            from textual.widgets import Log

            await pilote.press("a")
            await self._attendre(app, pilote)
            return list(app.query_one("#journal", Log).lines)

        _, moteur, _, journal = self._rendu(gestes)
        self.assertEqual(moteur.appels, [])
        self.assertIn("Planifier d'abord.", "\n".join(journal))

    def test_appliquer_un_plan_simple_demande_une_confirmation(self):
        async def gestes(app, pilote):
            await pilote.press("p")
            await self._attendre(app, pilote)
            await pilote.press("a")
            await pilote.pause()
            await pilote.click("#oui")
            await self._attendre(app, pilote)

        _, moteur, _, _ = self._rendu(gestes)
        self.assertEqual(moteur.appels, ["planifier", "appliquer"])

    def test_appliquer_un_plan_destructeur_exige_le_nom(self):
        remplacer = [Changement("remplacer", "parc-a-vm-1", "vm")]

        async def gestes(app, pilote):
            await pilote.press("p")
            await self._attendre(app, pilote)
            await self._retaper(app, pilote, "a", "faux")
            avant = list(app.moteur.appels)
            await self._retaper(app, pilote, "a", "parc-a")
            return avant

        _, moteur, _, avant = self._rendu(gestes, changements=remplacer)
        self.assertEqual(avant, ["planifier"])
        self.assertEqual(moteur.appels, ["planifier", "appliquer"])

    def test_aucun_widget_ne_montre_la_valeur_du_jeton(self):
        async def gestes(app, pilote):
            from textual.widgets import TabbedContent

            textes = []
            for onglet in ("tab_cible", "tab_vm", "tab_options", "tab_tofu"):
                app.query_one(TabbedContent).active = onglet
                await pilote.pause()
                textes.append(_textes(app))
            await pilote.press("p")
            await self._attendre(app, pilote)
            textes.append(_textes(app))
            return "\n".join(textes)

        _, _, _, texte = self._rendu(gestes, jeton=_JETON)
        self.assertIn("présent", texte)
        self.assertNotIn(_JETON, texte)
        self.assertNotIn("fausse-valeur-de-jeton", texte)


if __name__ == "__main__":
    unittest.main()
