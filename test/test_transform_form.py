#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'écran de périmètre de « Transform data ».

Un fichier À PART, et non une classe de plus dans
`test_transform_external.py` : celui-là s'importe sous DEUX interpréteurs
— celui du CLI, et le venv dédié qui bâtit les fixtures de classeur et
n'a ni `click` ni `textual`. Y mettre un test d'écran casserait la moitié
de ce fichier sur un `ModuleNotFoundError` sans rapport avec ce qu'il
éprouve.

Deux niveaux de preuve :

- les fonctions PURES et la structure de l'app, sans monter un widget ;
- un pilotage RÉEL par `run_test()`, qui seul prouve que l'écran répond
  aux touches. Le reste peut passer sur un écran qui ne s'affiche pas.
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from script.todo import transform_form  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except ImportError:  # pragma: no cover - textual peut manquer
    TEXTUAL = False

SANS_TEXTUAL = (
    "textual est absent de cet interpréteur : installer les dépendances du"
    " CLI, ou lancer ce fichier sous .venv.erplibre"
)


def rapport():
    """Un rapport de moteur, réduit à ce que l'écran en lit.

    Trois colonnes qui posent chacune un cas : une étiquetée, une SANS
    libellé — le cas de la majorité des colonnes d'un export réel —, et
    une planchéiée, qu'aucune réponse ne doit pouvoir cocher.
    """
    return {
        "chemin": "/tmp/classeur.xlsx",
        "format": "xlsx",
        "feuilles": [
            {
                "nom": "Ventes",
                "lignes": 4,
                "colonnes_n": 3,
                "lignes_entete": [1],
                "ligne_champs": 1,
                "entete_declaree": False,
                "colonnes": [
                    {
                        "index": 1,
                        "etiquette": "montant",
                        "type": "nombre",
                        "remplies": 3,
                        "distinctes": 3,
                        "exemples": ["12", "13", "14"],
                        "plancher": False,
                    },
                    {
                        "index": 2,
                        "etiquette": "",
                        "type": "texte",
                        "remplies": 3,
                        "distinctes": 3,
                        "exemples": ["aboulie", "acai", "adobe"],
                        "plancher": False,
                    },
                    {
                        "index": 3,
                        "etiquette": "partner_id",
                        "type": "texte",
                        "remplies": 3,
                        "distinctes": 3,
                        "exemples": ["base.p1"],
                        "plancher": True,
                    },
                ],
                "lignes_sondees": [
                    {
                        "numero": 1,
                        "apercu": ["montant", "", "partner_id"],
                        "pleines": 2,
                        "mesure": {
                            "contraste": 0.5,
                            "hors_colonne": 1.0,
                            "accord": 0.0,
                        },
                    },
                    {
                        "numero": 2,
                        "apercu": ["12", "aboulie", "base.p1"],
                        "pleines": 3,
                        "mesure": {
                            "contraste": 0.0,
                            "hors_colonne": 0.3,
                            "accord": 1.0,
                        },
                    },
                ],
            },
            {
                "nom": "Achats",
                "lignes": 2,
                "colonnes_n": 1,
                "lignes_entete": [],
                "ligne_champs": None,
                "entete_declaree": False,
                "colonnes": [
                    {
                        "index": 1,
                        "etiquette": "",
                        "type": "texte",
                        "remplies": 2,
                        "distinctes": 2,
                        "exemples": ["acanthe", "adelphique"],
                        "plancher": False,
                    }
                ],
                "lignes_sondees": [
                    {
                        "numero": 1,
                        "apercu": ["acanthe"],
                        "pleines": 1,
                        "mesure": None,
                    }
                ],
            },
        ],
    }


class TestContexte(unittest.TestCase):
    """Le contexte est de la donnée PURE, tirée du rapport.

    C'est ce qui garantit que l'écran n'ouvre rien lui-même : aucune
    entrée-sortie et aucun sous-processus depuis l'affichage.
    """

    def setUp(self):
        self.ctx = transform_form.contexte_depuis_rapport(rapport())

    def test_chaque_feuille_traverse(self):
        self.assertEqual(
            [f["nom"] for f in self.ctx["feuilles"]], ["Ventes", "Achats"]
        )

    def test_l_empan_mesure_traverse(self):
        self.assertEqual(self.ctx["feuilles"][0]["lignes_entete"], [1])
        self.assertEqual(self.ctx["feuilles"][1]["lignes_entete"], [])
        self.assertIsNone(self.ctx["feuilles"][1]["ligne_champs"])

    def test_un_rapport_vide_ne_leve_pas(self):
        vide = transform_form.contexte_depuis_rapport({})
        self.assertEqual(vide["feuilles"], [])
        self.assertEqual(vide["fichier"], "")

    def test_une_feuille_sans_colonne_ni_sondee_ne_leve_pas(self):
        ctx = transform_form.contexte_depuis_rapport(
            {"feuilles": [{"nom": "F"}]}
        )
        feuille = ctx["feuilles"][0]
        self.assertEqual(feuille["colonnes"], [])
        self.assertEqual(feuille["lignes_sondees"], [])


class TestMemoireDansLeContexte(unittest.TestCase):
    """Ce qu'une table de lot se rappelle arrive PRÉ-COCHÉ et MARQUÉ.

    Jamais appliqué en silence : une réponse fausse appliquée sans être
    vue est exactement comment une erreur gagne tout un lot.
    """

    def test_sans_memoire_l_empan_est_celui_de_la_mesure(self):
        ctx = transform_form.contexte_depuis_rapport(rapport())
        self.assertEqual(ctx["feuilles"][0]["lignes_entete"], [1])
        self.assertFalse(ctx["feuilles"][0]["entete_memorisee"])

    def test_la_memoire_remplace_l_empan_et_se_MARQUE(self):
        ctx = transform_form.contexte_depuis_rapport(
            rapport(), {"Achats": [1, 2]}
        )
        achats = ctx["feuilles"][1]
        self.assertEqual(achats["lignes_entete"], [1, 2])
        self.assertTrue(achats["entete_memorisee"])

    def test_une_memoire_VIDE_veut_dire_pas_d_en_tete(self):
        """Et se distingue d'une absence de mémoire : l'une répond « pas
        d'en-tête », l'autre laisse la mesure trancher."""
        ctx = transform_form.contexte_depuis_rapport(rapport(), {"Ventes": []})
        ventes = ctx["feuilles"][0]
        self.assertEqual(ventes["lignes_entete"], [])
        self.assertTrue(ventes["entete_memorisee"])

    def test_une_feuille_hors_memoire_garde_sa_mesure(self):
        ctx = transform_form.contexte_depuis_rapport(
            rapport(), {"Achats": [1]}
        )
        self.assertEqual(ctx["feuilles"][0]["lignes_entete"], [1])
        self.assertFalse(ctx["feuilles"][0]["entete_memorisee"])

    def test_des_lignes_en_chaines_sont_normalisees(self):
        """Elles arrivent d'un JSON relu à la main."""
        ctx = transform_form.contexte_depuis_rapport(
            rapport(), {"Achats": ["2", "1", "1"]}
        )
        self.assertEqual(ctx["feuilles"][1]["lignes_entete"], [1, 2])


@unittest.skipUnless(TEXTUAL, SANS_TEXTUAL)
class TestMemoireALEcran(unittest.TestCase):
    """L'écran part de la mémoire, et la montre."""

    def test_l_empan_de_depart_vient_de_la_memoire(self):
        app = transform_form.run_transform_form(
            transform_form.contexte_depuis_rapport(
                rapport(), {"Achats": [1, 2]}
            ),
            run_app=False,
        )
        self.assertEqual(app._entetes["Achats"], {1, 2})
        self.assertEqual(app._entetes["Ventes"], {1})

    def test_la_legende_nomme_les_quatre_marques(self):
        """Un marqueur qu'il faut deviner n'est pas offert."""
        from script.todo.todo_i18n import t as traduire

        legende = traduire(
            "[x] untouched · [!] floored · * corrected · = from"
            " the batch table"
        )
        for marque in ("[x]", "[!]", "*", "="):
            with self.subTest(marque=marque):
                self.assertIn(marque, legende)


class TestLibelles(unittest.TestCase):
    """Ce que l'écran montre d'une colonne et d'une ligne."""

    def setUp(self):
        self.ctx = transform_form.contexte_depuis_rapport(rapport())
        self.colonnes = self.ctx["feuilles"][0]["colonnes"]

    def test_une_colonne_sans_libelle_le_DIT(self):
        """Un blanc se lit comme une erreur d'affichage plutôt que comme
        un fait, et c'est le cas de la majorité des colonnes."""
        cellules = transform_form.libelle_de_colonne(
            self.colonnes[1], transform_form.MARQUE_EN_PORTEE
        )
        self.assertTrue(cellules[2].strip())
        self.assertNotEqual(cellules[2], "")

    def test_les_exemples_sont_la_derniere_cellule(self):
        """CE qui distingue deux colonnes sans libellé : ni le type, ni
        le compte, ni les bornes n'y suffisent."""
        cellules = transform_form.libelle_de_colonne(
            self.colonnes[1], transform_form.MARQUE_EN_PORTEE
        )
        self.assertIn("aboulie", cellules[-1])
        self.assertIn("acai", cellules[-1])

    def test_toutes_les_cellules_sont_des_chaines(self):
        for colonne in self.colonnes:
            with self.subTest(colonne=colonne["index"]):
                for cellule in transform_form.libelle_de_colonne(
                    colonne, transform_form.MARQUE_EN_PORTEE
                ):
                    self.assertIsInstance(cellule, str)

    def test_une_ligne_sondee_montre_ses_MESURES(self):
        """L'opérateur voit POURQUOI la mesure a tranché avant de la
        contredire — contredire un verdict qu'on ne voit pas est un
        pari."""
        sondee = self.ctx["feuilles"][0]["lignes_sondees"][0]
        cellules = transform_form.libelle_de_ligne_sondee(sondee, True)
        self.assertEqual(cellules[0], transform_form.MARQUE_INTACTE)
        self.assertIn("1.00", cellules[-1])

    def test_une_ligne_sans_mesure_ne_montre_pas_de_zeros(self):
        """Rien à comparer n'est pas « toutes les mesures à zéro »."""
        sondee = self.ctx["feuilles"][1]["lignes_sondees"][0]
        cellules = transform_form.libelle_de_ligne_sondee(sondee, False)
        self.assertEqual(cellules[-1], "")


class TestCleDeColonne(unittest.TestCase):
    """Ce par quoi une réponse DÉSIGNE une colonne.

    La même règle que `colonne_repondue` du moteur, faute de quoi l'écran
    cocherait une case dont la réponse ne porterait pas.
    """

    def test_l_etiquette_quand_il_y_en_a_une(self):
        self.assertEqual(
            transform_form.cle_de_colonne(
                {"index": 4, "etiquette": "montant"}
            ),
            "montant",
        )

    def test_l_index_sinon(self):
        for etiquette in ("", "   ", None):
            with self.subTest(etiquette=etiquette):
                self.assertEqual(
                    transform_form.cle_de_colonne(
                        {"index": 4, "etiquette": etiquette}
                    ),
                    "4",
                )


class TestBasculer(unittest.TestCase):
    """La décision, séparée du rendu pour être éprouvable."""

    def test_ajoute_puis_retire(self):
        ensemble = set()
        self.assertTrue(transform_form.basculer(ensemble, "a"))
        self.assertEqual(ensemble, {"a"})
        self.assertFalse(transform_form.basculer(ensemble, "a"))
        self.assertEqual(ensemble, set())


class TestSpec(unittest.TestCase):
    """La spec traverse un `json.dumps` : ni `set`, ni clé tuple."""

    def setUp(self):
        self.ctx = transform_form.contexte_depuis_rapport(rapport())

    def test_la_spec_est_serialisable(self):
        import json

        spec = transform_form.spec_depuis_etat(
            self.ctx, {"Ventes": {"montant"}}, {"Ventes": {1, 2}}
        )
        json.dumps(spec, allow_nan=False)
        self.assertEqual(
            spec["colonnes_intactes_par_feuille"], {"Ventes": ["montant"]}
        )
        self.assertEqual(spec["entetes_par_feuille"]["Ventes"], [1, 2])

    def test_une_feuille_sans_colonne_cochee_ne_figure_pas(self):
        spec = transform_form.spec_depuis_etat(
            self.ctx, {"Ventes": set(), "Achats": set()}, {}
        )
        self.assertEqual(spec["colonnes_intactes_par_feuille"], {})

    def test_CHAQUE_feuille_porte_son_empan_meme_vide(self):
        """Un empan vide veut dire « pas d'en-tête », ce qui met la ligne
        1 en portée : le taire vaudrait « la ligne 1 », l'inverse."""
        spec = transform_form.spec_depuis_etat(self.ctx, {}, {"Ventes": {1}})
        self.assertEqual(
            sorted(spec["entetes_par_feuille"]), ["Achats", "Ventes"]
        )
        self.assertEqual(spec["entetes_par_feuille"]["Achats"], [])


@unittest.skipUnless(TEXTUAL, SANS_TEXTUAL)
class TestStructureDeLApp(unittest.TestCase):
    """Ce que l'app promet, sans monter un widget."""

    def setUp(self):
        self.app = transform_form.run_transform_form(
            transform_form.contexte_depuis_rapport(rapport()), run_app=False
        )

    def _touches(self):
        rendu = {}
        for item in self.app.BINDINGS:
            if isinstance(item, tuple):
                rendu[item[0]] = item[1]
            else:
                rendu[item.key] = item.action
        return rendu

    def test_chaque_touche_a_son_action(self):
        for touche, action in self._touches().items():
            with self.subTest(touche=touche):
                self.assertTrue(
                    hasattr(self.app, "action_%s" % action),
                    "action_%s manque" % action,
                )

    def test_les_touches_promises_sont_la(self):
        touches = self._touches()
        for touche in ("space", "f5", "f9", "escape"):
            with self.subTest(touche=touche):
                self.assertIn(touche, touches)

    def test_l_empan_mesure_est_le_point_de_depart(self):
        """Une correction part de ce que le moteur a trouvé ; les cases
        de colonne partent VIDES, une réponse ne se pré-cochant pas."""
        self.assertEqual(self.app._entetes, {"Ventes": {1}, "Achats": set()})
        self.assertEqual(
            self.app._intactes, {"Ventes": set(), "Achats": set()}
        )


@unittest.skipUnless(TEXTUAL, SANS_TEXTUAL)
class TestPilotage(unittest.TestCase):
    """L'écran répond-il aux touches ? Seul un pilotage le prouve.

    Tout le reste passerait sur un écran qui ne s'affiche pas.
    """

    def _piloter(self, scenario):
        app = transform_form.run_transform_form(
            transform_form.contexte_depuis_rapport(rapport()), run_app=False
        )

        async def tourner():
            async with app.run_test() as pilote:
                await pilote.pause()
                await scenario(app, pilote)

        asyncio.run(tourner())
        return app

    def test_les_deux_tableaux_se_remplissent(self):
        vu = {}

        async def scenario(app, pilote):
            vu["colonnes"] = app.query_one("#colonnes").row_count
            vu["sondees"] = app.query_one("#sondees").row_count

        self._piloter(scenario)
        self.assertEqual(vu["colonnes"], 3)
        self.assertEqual(vu["sondees"], 2)

    def test_espace_sur_une_colonne_la_laisse_intacte(self):
        async def scenario(app, pilote):
            app.query_one("#colonnes").focus()
            await pilote.pause()
            await pilote.press("space")
            await pilote.pause()

        app = self._piloter(scenario)
        self.assertEqual(app._intactes["Ventes"], {"montant"})

    def test_espace_sur_une_colonne_PLANCHEIEE_ne_fait_rien(self):
        """Le plancher passe avant la réponse : une case qui ne
        changerait rien serait un mensonge."""

        async def scenario(app, pilote):
            table = app.query_one("#colonnes")
            table.focus()
            await pilote.pause()
            table.move_cursor(row=2)
            await pilote.pause()
            await pilote.press("space")
            await pilote.pause()

        app = self._piloter(scenario)
        self.assertEqual(app._intactes["Ventes"], set())

    def test_espace_sur_une_ligne_ajoute_une_ligne_d_en_tete(self):
        """Plusieurs lignes d'en-tête : un export porte souvent une ligne
        de catégorie au-dessus de la ligne de champs."""

        async def scenario(app, pilote):
            table = app.query_one("#sondees")
            table.focus()
            await pilote.pause()
            table.move_cursor(row=1)
            await pilote.pause()
            await pilote.press("space")
            await pilote.pause()

        app = self._piloter(scenario)
        self.assertEqual(app._entetes["Ventes"], {1, 2})
        self.assertIn("Ventes", app._corrigees)

    def test_f4_rend_la_feuille_a_la_mesure(self):
        async def scenario(app, pilote):
            app.query_one("#sondees").focus()
            await pilote.pause()
            await pilote.press("space")
            await pilote.pause()
            await pilote.press("f4")
            await pilote.pause()

        app = self._piloter(scenario)
        self.assertEqual(app._entetes["Ventes"], {1})
        self.assertNotIn("Ventes", app._corrigees)

    def test_f5_rend_la_spec(self):
        async def scenario(app, pilote):
            await pilote.press("f5")
            await pilote.pause()

        app = self._piloter(scenario)
        spec = app._resultat["spec"]
        self.assertIsInstance(spec, dict)
        self.assertIn("entetes_par_feuille", spec)

    def test_f9_rend_un_dict_VIDE_et_non_None(self):
        """L'appelant distingue « poser les questions » de « annuler » :
        les confondre supprimerait le repli."""

        async def scenario(app, pilote):
            await pilote.press("f9")
            await pilote.pause()

        app = self._piloter(scenario)
        self.assertEqual(app._resultat["spec"], {})

    def test_echap_annule(self):
        async def scenario(app, pilote):
            await pilote.press("escape")
            await pilote.pause()

        app = self._piloter(scenario)
        self.assertIsNone(app._resultat["spec"])


if __name__ == "__main__":
    unittest.main()
