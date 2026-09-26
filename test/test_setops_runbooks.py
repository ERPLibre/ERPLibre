#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les séquences du moteur, et ce que todo en conduit — sans rien masquer.

Le Makefile du moteur ne dit nulle part dans quel ordre jouer ses cibles ; le
registre le dit. Une séquence dont on retirerait ce que todo ne lance pas
mentirait donc par omission, et le pire cas n'est pas théorique : une séquence
de trois étapes se réduirait à zéro, et une autre commencerait à son étape 2.

Ce qui est éprouvé ici : la lecture fermée par défaut, la règle de périmètre
écrite UNE fois, et le fait que chaque étape porte sa barrière plutôt que de
disparaître.

Les identifiants de runbook et de cible sont inventés et n'existent nulle part
ailleurs dans le dépôt.
"""

import os
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.setops import runbooks as R  # noqa: E402

# La forme exacte que rend « runbooks.py lister --json ».
REGISTRE = """[
  {
    "id": "banc-fictif-sequence",
    "titre": "Une sequence de banc",
    "portee": "tenant",
    "but": "Eprouver la lecture.",
    "etapes": [
      {"cible": "banc-mesurer", "libelle": "Mesure", "portee": "toute",
       "nature": "mesure", "pourquoi": "Parce que.", "duree": "",
       "variables": [], "fixes": {}},
      {"cible": "banc-ecrire", "libelle": "Ecrit", "portee": "tenant",
       "nature": "ecriture", "pourquoi": "Parce que.", "duree": "long",
       "variables": [{"nom": "NOM", "invite": "Le nom", "facultatif": false},
                     {"nom": "SEUL", "invite": "Un seul", "facultatif": true}],
       "fixes": {}},
      {"cible": "banc-raser", "libelle": "Detruit", "portee": "site",
       "nature": "destructif", "pourquoi": "Parce que.", "duree": "",
       "variables": [], "fixes": {"CONFIRMER": "true"}},
      {"cible": "banc-garde", "libelle": "Garde du moteur", "portee": "toute",
       "nature": "ecriture", "pourquoi": "Parce que.", "duree": "",
       "variables": [], "fixes": {"CONFIRMER": "true"}}
    ]
  }
]
"""


def etape(**champs):
    base = dict(
        cible="banc-fictif",
        libelle="",
        portee=R.TOUTE,
        nature=R.MESURE,
        pourquoi="",
        duree="",
        variables=(),
        exige_confirmation=False,
        facultative=False,
    )
    base.update(champs)
    return R.Etape(**base)


class TestLaLectureDuRegistre(unittest.TestCase):
    def test_a_real_registry_is_read_in_order(self):
        """Le contrôle positif : sans lui, un lecteur qui refuse tout
        passerait chacun des refus éprouvés plus bas."""
        lus = R.lit_registre(REGISTRE)
        self.assertEqual(1, len(lus))
        self.assertEqual("banc-fictif-sequence", lus[0].id)
        self.assertEqual(
            ["banc-mesurer", "banc-ecrire", "banc-raser", "banc-garde"],
            [e.cible for e in lus[0].etapes],
        )

    def test_the_confirmation_a_step_demands_is_read(self):
        lus = R.lit_registre(REGISTRE)
        self.assertEqual(
            [False, False, True, True],
            [e.exige_confirmation for e in lus[0].etapes],
        )

    def test_a_warning_before_the_document_does_not_hide_it(self):
        """Un avertissement de Python sur la sortie ne doit pas rendre le
        registre illisible."""
        self.assertIsNotNone(
            R.lit_registre("DeprecationWarning: …\n" + REGISTRE)
        )

    def test_anything_that_is_not_a_list_is_unknown(self):
        for texte in ("{}", "rien", "", None, "[]"):
            with self.subTest(texte=texte):
                self.assertIsNone(R.lit_registre(texte))

    def test_a_step_whose_nature_is_unknown_refuses_the_whole_registry(self):
        """Une séquence partielle est pire qu'une absence : son ORDRE est ce
        qu'on vient y chercher."""
        self.assertIsNone(
            R.lit_registre(
                REGISTRE.replace('"nature": "mesure"', '"nature": "peut-etre"')
            )
        )

    def test_a_runbook_without_a_step_is_unknown(self):
        self.assertIsNone(
            R.lit_registre('[{"id": "x", "portee": "toute", "etapes": []}]')
        )

    def test_a_scope_outside_the_vocabulary_is_unknown(self):
        self.assertIsNone(
            R.lit_registre(
                REGISTRE.replace('"portee": "tenant"', '"portee": "ailleurs"')
            )
        )


class TestLaRegleDePerimetre(unittest.TestCase):
    """Écrite UNE fois, dans `barriere()`. Deux copies diraient tôt ou tard
    deux choses différentes du même geste."""

    def test_what_destroys_is_never_driven_from_here(self):
        self.assertEqual(
            R.DESTRUCTIVE,
            R.barriere(etape(nature=R.DESTRUCTIF), "eco", "site"),
        )

    def test_what_the_engine_gates_stays_with_the_engine(self):
        self.assertEqual(
            R.CONFIRMATION_MOTEUR,
            R.barriere(etape(exige_confirmation=True), "eco", "site"),
        )

    def test_a_tenant_step_needs_a_mounted_ecosystem(self):
        self.assertEqual(
            R.SANS_ECOSYSTEME, R.barriere(etape(portee=R.TENANT), "", "site")
        )
        self.assertEqual("", R.barriere(etape(portee=R.TENANT), "eco", ""))

    def test_a_site_step_needs_a_mounted_site(self):
        self.assertEqual(
            R.SANS_SITE, R.barriere(etape(portee=R.SITE), "eco", "")
        )
        self.assertEqual("", R.barriere(etape(portee=R.SITE), "", "site"))

    def test_a_station_step_needs_nothing(self):
        for portee in (R.POSTE, R.TOUTE):
            with self.subTest(portee=portee):
                self.assertEqual("", R.barriere(etape(portee=portee), "", ""))

    def test_an_unreadable_step_is_never_driven(self):
        self.assertEqual(R.FORME_INCONNUE, R.barriere(None, "eco", "site"))

    def test_every_barrier_named_is_in_the_closed_vocabulary(self):
        """Une barrière hors vocabulaire ne se traduirait pas à l'écran."""
        vues = {
            R.barriere(etape(nature=n, portee=p, exige_confirmation=c), "", "")
            for n in R.NATURES
            for p in R.PORTEES
            for c in (True, False)
        }
        for barriere in vues - {""}:
            with self.subTest(barriere=barriere):
                self.assertIn(barriere, R.BARRIERES)


class TestRienNestMasque(unittest.TestCase):
    """Le cœur du parti : ce qui ne se lance pas d'ici reste AFFICHÉ."""

    def setUp(self):
        self.runbook = R.lit_registre(REGISTRE)[0]

    def test_the_sequence_keeps_every_step_whatever_the_station(self):
        self.assertEqual(4, len(self.runbook.etapes))

    def test_the_count_says_how_many_of_how_many(self):
        """Une liste dont on ne sait pas combien elle offre se parcourt en
        entier pour le découvrir."""
        self.assertEqual((1, 4), R.compte(self.runbook, "", ""))
        self.assertEqual((2, 4), R.compte(self.runbook, "eco", "site"))

    def test_a_sequence_that_offers_nothing_still_shows_its_steps(self):
        """Le pire cas, et il n'est pas théorique : une séquence de trois
        étapes se réduirait à zéro si l'on masquait les barrées."""
        seulement_barrees = REGISTRE.replace(
            '"nature": "mesure"', '"nature": "destructif"'
        ).replace('"nature": "ecriture"', '"nature": "destructif"')
        runbook = R.lit_registre(seulement_barrees)[0]
        self.assertEqual((0, 4), R.compte(runbook, "eco", "site"))
        self.assertEqual(4, len(runbook.etapes))


class TestLesVariablesSontDesTables(unittest.TestCase):
    """Le registre écrit {nom, invite, facultatif}, pas un nom.

    Les traiter comme des chaînes faisait demander une valeur pour
    « {'nom': 'HOTE', …} » et passait cette table à `make` comme nom de
    variable. La fixture disait « ["NOM"] » — une forme INVENTÉE, jamais
    capturée du moteur, et c'est ce qui a laissé passer le défaut.
    """

    def setUp(self):
        self.runbook = R.lit_registre(REGISTRE)[0]

    def test_a_variable_carries_the_prompt_the_engine_wrote(self):
        """Le reformuler ferait deux libellés pour la même question."""
        attendue = self.runbook.etapes[1].variables[0]
        self.assertEqual("NOM", attendue.nom)
        self.assertEqual("Le nom", attendue.invite)
        self.assertFalse(attendue.facultative)

    def test_an_optional_variable_says_it_is(self):
        """Sept des trente-quatre variables réelles sont facultatives :
        exiger une réponse les rendrait bloquantes."""
        self.assertTrue(self.runbook.etapes[1].variables[1].facultative)

    def test_a_variable_that_is_not_a_table_refuses_the_registry(self):
        self.assertIsNone(
            R.lit_registre(
                REGISTRE.replace('"variables": [', '"variables": ["NOM", ', 1)
            )
        )

    def test_a_variable_without_a_name_refuses_the_registry(self):
        self.assertIsNone(
            R.lit_registre(REGISTRE.replace('"nom": "NOM"', '"nom": "  "', 1))
        )


class TestCeQuiEcrit(unittest.TestCase):
    """Todo pose sa PROPRE confirmation sur une écriture : la ligne affichée
    porte `CONFIRMER=false`, et pour ces cibles-là le drapeau ne veut rien
    dire — elles écrivent quand même."""

    def test_a_write_is_named_as_such(self):
        self.assertTrue(R.ecrit(etape(nature=R.ECRITURE)))

    def test_a_measure_is_not(self):
        self.assertFalse(R.ecrit(etape(nature=R.MESURE)))

    def test_nothing_is_not_a_write(self):
        self.assertFalse(R.ecrit(None))


if __name__ == "__main__":
    unittest.main()
