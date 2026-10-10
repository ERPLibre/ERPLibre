#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran d'installation d'Apertus : séquentiel, et il s'arrête.

Ce qui distingue cet écran du suivi de déploiement, dont il emprunte la forme,
est qu'il mène des étapes ORDONNÉES et renonce à la première qui casse. Le
suivi de déploiement mène des travaux parallèles et les mène tous ; ici,
poursuivre après l'échec du contrôle de version téléchargerait plusieurs
gigaoctets pour un moteur qui ne peut pas les lire.

Les commandes jouées ici sont `true`, `false` et `echo` : aucune machine n'est
touchée, et le test reste dans la seconde.
"""

import asyncio
import sys
import unittest
from dataclasses import dataclass

sys.argv = ["todo.py"]
from script.todo.apertus_form import run_apertus_progress  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False


@dataclass(frozen=True)
class Etape:
    """La forme minimale que l'écran consomme."""

    cle: str
    label: str
    commande: str
    deja_fait: str = ""
    critique: bool = True


def titres(app):
    """Les titres des blocs, dans l'ordre où ils sont dessinés."""
    from textual.widgets import Collapsible

    return [bloc.title for bloc in app.query(Collapsible)]


def joue(etapes, depart=1, notes=None):
    """Fait tourner l'écran jusqu'au bout et rend (titres, rang en échec)."""

    async def scenario():
        app = run_apertus_progress(
            etapes,
            depart,
            # Le rappel reçoit cinq arguments ; on les empaquette pour que le
            # test lise un tuple par étape.
            on_step=(
                None if notes is None else lambda *fait: notes.append(fait)
            ),
            run_app=False,
        )
        async with app.run_test(size=(100, 40)) as pilote:
            # Le travail vit sur un autre fil : la pause rend la main à la
            # boucle de dessin, qui applique ce que le fil a demandé.
            for _ in range(40):
                await asyncio.sleep(0.05)
                await pilote.pause()
                if app.resultat["echec"] or not any(
                    "⏳" in x for x in titres(app)
                ):
                    if not any("⬜" in x for x in titres(app)):
                        break
            return titres(app), app.resultat["echec"]

    return asyncio.run(scenario())


@unittest.skipUnless(TEXTUAL, "Textual absent")
class UnBlocParEtape(unittest.TestCase):
    def test_chaque_etape_a_son_bloc(self):
        etapes = [
            Etape("a", "Reach the target", "true"),
            Etape("b", "Check sudo", "true"),
            Etape("c", "Check free space", "true"),
        ]
        vus, echec = joue(etapes)
        self.assertEqual(len(vus), 3, vus)
        self.assertEqual(echec, 0, vus)

    def test_une_etape_reussie_porte_la_marque_de_succes(self):
        vus, echec = joue([Etape("a", "Reach the target", "true")])
        self.assertTrue(vus[0].startswith("✅"), vus)
        self.assertEqual(echec, 0)

    def test_les_etapes_deja_franchies_partent_pliees_et_marquees(self):
        """Reprendre à l'étape 3 montre les deux premières comme faites."""
        etapes = [
            Etape("a", "Reach the target", "true"),
            Etape("b", "Check sudo", "true"),
            Etape("c", "Check free space", "true"),
        ]
        vus, _ = joue(etapes, depart=3)
        self.assertTrue(vus[0].startswith("✅"), vus)
        self.assertTrue(vus[1].startswith("✅"), vus)


@unittest.skipUnless(TEXTUAL, "Textual absent")
class LArretSurEchec(unittest.TestCase):
    def test_une_etape_critique_en_echec_arrete_la_suite(self):
        """L'invariant de l'écran : ce qui suit une casse n'est pas joué.

        La troisième étape écrirait un fichier si elle tournait. Elle ne
        tourne pas, donc la deuxième l'a bien arrêtée.
        """
        etapes = [
            Etape("a", "Reach the target", "true"),
            Etape("b", "Check the engine version", "false"),
            Etape("c", "Pull the model", "true"),
        ]
        vus, echec = joue(etapes)
        self.assertEqual(echec, 2, vus)
        self.assertTrue(vus[1].startswith("⛔"), vus)
        # La troisième n'a jamais commencé : elle garde sa marque de départ.
        self.assertTrue(vus[2].startswith("⬜"), vus)

    def test_une_etape_non_critique_en_echec_laisse_courir(self):
        etapes = [
            Etape("a", "Reach the target", "true"),
            Etape("b", "Start the service", "false", critique=False),
            Etape("c", "Check it listens", "true"),
        ]
        vus, echec = joue(etapes)
        self.assertEqual(echec, 0, vus)
        self.assertTrue(vus[1].startswith("⚠️"), vus)
        self.assertTrue(vus[2].startswith("✅"), vus)


@unittest.skipUnless(TEXTUAL, "Textual absent")
class LesEtapesDejaFaites(unittest.TestCase):
    def test_un_test_de_completion_satisfait_saute_l_etape(self):
        etapes = [
            Etape("a", "Pull the model", "false", deja_fait="true"),
        ]
        vus, echec = joue(etapes)
        # La commande aurait échoué ; le test de complétion l'a évitée.
        self.assertEqual(echec, 0, vus)
        self.assertTrue(vus[0].startswith("⏭"), vus)


@unittest.skipUnless(TEXTUAL, "Textual absent")
class CeQueLEcranRapporte(unittest.TestCase):
    def test_chaque_etape_est_annoncee_a_l_appelant(self):
        """C'est par là que la progression descend sur le disque."""
        notes = []
        etapes = [
            Etape("a", "Reach the target", "echo salut"),
            Etape("b", "Check sudo", "false"),
        ]
        joue(etapes, notes=notes)
        rangs = [n[0] for n in notes]
        cles = [n[1] for n in notes]
        codes = [n[2] for n in notes]
        self.assertEqual(rangs, [1, 2], notes)
        self.assertEqual(cles, ["a", "b"], notes)
        self.assertEqual(codes[0], 0, notes)
        self.assertNotEqual(codes[1], 0, notes)

    def test_la_sortie_de_la_commande_est_transmise(self):
        notes = []
        joue(
            [Etape("a", "Reach the target", "echo bonjour-du-test")],
            notes=notes,
        )
        self.assertIn("bonjour-du-test", notes[0][3])


@unittest.skipUnless(TEXTUAL, "Textual absent")
class LIdentifiantDeWidget(unittest.TestCase):
    def test_une_cle_a_ponctuation_donne_un_identifiant_acceptable(self):
        """Un identifiant Textual refuse le point et le tiret en tête.

        Une clé d'étape n'est pas garantie d'en être exempte, et un
        identifiant refusé ferait lever `compose` au lieu d'afficher.
        """
        vus, echec = joue([Etape("8b-q4.mini", "Pull the model", "true")])
        self.assertEqual(len(vus), 1, vus)
        self.assertEqual(echec, 0)


if __name__ == "__main__":
    unittest.main()
