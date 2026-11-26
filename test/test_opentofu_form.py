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
import threading
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
    """Moteur qui note ses appels ; `planifier` résout le stockage et
    attend `barriere` quand elle est posée ; `appliquer` rend `apply_ok`."""

    nom = "tofu"

    def __init__(self, racine, changements=None):
        self.racine = Path(racine)
        self.appels = []
        self.changements = changements or [
            Changement("creer", "parc-a-vm-1", "vm")
        ]
        self.barriere = None
        self.apply_ok = True

    def disponible(self):
        return True, "9.8.7"

    def planifier(self, spec, journal):
        self.appels.append("planifier")
        journal("ligne du moteur")
        if self.barriere is not None:
            self.barriere.wait(10)
        spec["cible"]["stockage"] = "local-lvm"
        return Resultat(True, "plan prêt"), list(self.changements)

    def appliquer(self, spec, journal):
        self.appels.append("appliquer")
        return Resultat(self.apply_ok, "appliqué" if self.apply_ok else "")

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


class TestRenommer(unittest.TestCase):
    """Une VM renommée est une VM neuve pour `tofu` : son ancien VMID et
    l'adresse qui en dérive iraient en collision avec la VM qu'il détruit."""

    def _base(self, **champs):
        base = sp.nouvelle_spec("parc-a", "hote-x")["vms"][0]
        base.update(
            vmid=105,
            ip="10.10.10.155/24",
            passerelle="10.10.10.1",
            dns=["192.0.2.1"],
        )
        base.update(champs)
        return base

    def test_renommer_vide_le_vmid_et_l_adresse_derivee(self):
        vm = vm_depuis_saisie(self._base(), {"nom": "web", "vmid": "105"})
        self.assertIsNone(vm["vmid"])
        self.assertEqual(
            (vm["ip"], vm["passerelle"], vm["dns"]), ("auto", "", [])
        )

    def test_renommer_garde_une_adresse_choisie(self):
        base = self._base(ip="10.10.10.20/24")
        vm = vm_depuis_saisie(base, {"nom": "web", "vmid": "105"})
        self.assertIsNone(vm["vmid"])
        self.assertEqual(vm["ip"], "10.10.10.20/24")
        self.assertEqual(vm["passerelle"], "10.10.10.1")

    def test_renommer_garde_un_vmid_saisi(self):
        vm = vm_depuis_saisie(self._base(), {"nom": "web", "vmid": "130"})
        self.assertEqual(vm["vmid"], 130)
        self.assertEqual(vm["ip"], "10.10.10.155/24")

    def test_sans_renommer_rien_ne_change(self):
        vm = vm_depuis_saisie(
            self._base(), {"nom": "parc-a-vm-1", "vmid": "105"}
        )
        self.assertEqual(vm["vmid"], 105)
        self.assertEqual(vm["ip"], "10.10.10.155/24")


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
    def _rendu(
        self,
        gestes,
        changements=None,
        jeton=None,
        quand=None,
        regler=None,
        detruit=None,
    ):
        """Monte l'écran, joue `gestes`, rend (app, moteur, sauvés, sortie).
        `regler(moteur)` ajuste le moteur factice avant le montage."""
        with tempfile.TemporaryDirectory() as racine:
            if jeton:
                coffre.ecrire("parc-a", {"jeton": jeton}, racine)
            moteur = FauxMoteur(racine, changements)
            if regler:
                regler(moteur)
            sauves = []
            resultat = {}

            async def scenario():
                spec = sp.nouvelle_spec("parc-a", "hote-x")
                app = run_opentofu_form(
                    spec,
                    moteur,
                    sauves.append,
                    quand_applique=quand,
                    quand_detruit=detruit,
                    run_app=False,
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

    def _appliquer(self, app, pilote):
        """Gestes : plan, puis apply confirmé."""

        async def suite():
            await pilote.press("p")
            await self._attendre(app, pilote)
            await pilote.press("a")
            await pilote.pause()
            await pilote.click("#oui")
            await self._attendre(app, pilote)

        return suite()

    def test_apply_reussi_mene_aux_suites_apres_la_sortie(self):
        appels = []
        plan = [
            Changement("creer", "parc-a-vm-1", "vm"),
            Changement("modifier", "parc-a-vm-2", "vm"),
            Changement("remplacer", "parc-a-vm-3", "vm"),
            Changement("creer", "parc-a-vm-1", "fichier"),
        ]

        async def gestes(app, pilote):
            # Le plan remplace une VM : l'apply exige le nom retapé.
            await pilote.press("p")
            await self._attendre(app, pilote)
            await self._retaper(app, pilote, "a", "parc-a")

        def quand(spec, nouvelles, detruites):
            appels.append((spec["cible"]["stockage"], nouvelles, detruites))

        app, moteur, _, _ = self._rendu(gestes, plan, quand=quand)
        self.assertEqual(moteur.appels, ["planifier", "appliquer"])
        self.assertEqual(appels, [])
        app.conclure()
        self.assertEqual(
            appels, [("local-lvm", {"parc-a-vm-1", "parc-a-vm-3"}, set())]
        )

    def test_apply_transmet_les_vm_detruites(self):
        appels = []
        plan = [
            Changement("detruire", "parc-a-vm-9", "vm"),
            Changement("detruire", "parc-a-vm-9", "cloud-init"),
            Changement("detruire", "parc-a-vm-1", "cloud-init"),
        ]

        async def gestes(app, pilote):
            await pilote.press("p")
            await self._attendre(app, pilote)
            await self._retaper(app, pilote, "a", "parc-a")

        app, _, _, _ = self._rendu(
            gestes, plan, quand=lambda *a: appels.append(a[1:])
        )
        app.conclure()
        self.assertEqual(appels, [(set(), {"parc-a-vm-9"})])

    def test_destroy_reussi_mene_au_retrait_des_alias(self):
        detruits, appliques = [], []

        async def gestes(app, pilote):
            await self._appliquer(app, pilote)
            await self._retaper(app, pilote, "d", "parc-a")

        app, moteur, _, _ = self._rendu(
            gestes,
            quand=lambda *a: appliques.append(a),
            detruit=detruits.append,
        )
        self.assertEqual(moteur.appels, ["planifier", "appliquer", "detruire"])
        self.assertEqual(detruits, [])
        app.conclure()
        self.assertEqual([s["nom"] for s in detruits], ["parc-a"])
        # L'apply précède le destroy : ses VM n'existent plus.
        self.assertEqual(appliques, [])

    def test_onglet_tofu_montre_la_disponibilite_du_moteur(self):
        async def gestes(app, pilote):
            from textual.widgets import Static

            return str(app.query_one("#t_outil", Static).render())

        _, _, _, texte = self._rendu(gestes)
        self.assertIn("9.8.7", texte)

    def test_apply_en_echec_ne_mene_a_rien(self):
        appels = []

        async def gestes(app, pilote):
            await self._appliquer(app, pilote)

        def regler(moteur):
            moteur.apply_ok = False

        app, moteur, _, _ = self._rendu(
            gestes, quand=lambda *a: appels.append(a), regler=regler
        )
        self.assertEqual(moteur.appels, ["planifier", "appliquer"])
        app.conclure()
        self.assertEqual(appels, [])

    def test_ctrl_q_pendant_un_appel_ne_quitte_pas(self):
        barriere = threading.Event()

        def regler(moteur):
            moteur.barriere = barriere

        async def gestes(app, pilote):
            await pilote.press("p")
            await pilote.pause()
            await pilote.press("ctrl+q")
            await pilote.pause()
            vivant = app.is_running
            barriere.set()
            await self._attendre(app, pilote)
            return vivant

        _, moteur, _, vivant = self._rendu(gestes, regler=regler)
        self.assertTrue(vivant)
        self.assertEqual(moteur.appels, ["planifier"])

    def test_champ_modifie_apres_le_plan_exige_un_nouveau_plan(self):
        async def gestes(app, pilote):
            from textual.widgets import Input, Log

            await pilote.press("p")
            await self._attendre(app, pilote)
            app.query_one("#c_pont", Input).value = "vmbr9"
            await pilote.press("a")
            await self._attendre(app, pilote)
            return list(app.query_one("#journal", Log).lines)

        _, moteur, _, journal = self._rendu(gestes)
        self.assertEqual(moteur.appels, ["planifier"])
        self.assertIn("✗ Planifier d'abord.", journal)


if __name__ == "__main__":
    unittest.main()
