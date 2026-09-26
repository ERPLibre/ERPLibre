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

from script.setops import ansible_env, engine, runner  # noqa: E402
from script.setops import runbooks as R  # noqa: E402

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def registre_reel():
    """Le registre du MOTEUR tel qu'il est sur ce poste, ou None s'il n'y est
    pas.

    Le chemin vient du manifeste, seule autorité : l'écrire ici en ferait une
    copie, qui dérive au premier déplacement. Un poste sans moteur rapatrié
    fait SAUTER les épreuves qui en dépendent, plutôt que rougir sur une
    absence qui n'est pas un défaut.
    """
    decl = engine.declaration(RACINE)
    if decl is None or not decl.path:
        return None
    moteur = os.path.join(RACINE, decl.path)
    if not os.path.isdir(moteur):
        return None
    vu = runner.jouer(
        R.ARGV_REGISTRE,
        env=ansible_env.environnement(RACINE, moteur, runner.base()),
        cwd=moteur,
    )
    return R.lit_registre(vu.sortie)


REEL = registre_reel()
AVEC_MOTEUR = unittest.skipUnless(
    REEL is not None, "registre du moteur illisible"
)

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


class TestLesPortes(unittest.TestCase):
    """Onze portes, dérivées du registre. Le nom de la méthode qui ouvre
    chacune se DÉDUIT de la cible, donc aucune table n'est à tenir."""

    def test_the_method_name_comes_from_the_target(self):
        self.assertEqual(
            "_setops_geste_instancier_appliquer",
            R.methode("instancier-appliquer"),
        )

    def test_every_door_names_a_distinct_target(self):
        self.assertEqual(len(R.PORTES), len(set(R.PORTES.values())))

    def test_a_target_declared_once_is_found(self):
        lus = R.lit_registre(REGISTRE)
        self.assertEqual("banc-ecrire", R.trouve(lus, "banc-ecrire").cible)

    def test_a_target_the_registry_ignores_is_not_found(self):
        lus = R.lit_registre(REGISTRE)
        self.assertIsNone(R.trouve(lus, "banc-fictif-jamais-declare"))
        self.assertIsNone(R.trouve(None, "banc-ecrire"))

    def test_two_sequences_declaring_the_same_target_alike_is_no_problem(self):
        """L'ordre d'une séquence à l'autre peut répéter une cible ; tant que
        la déclaration est la même, la porte en ouvre une sans ambiguïté."""
        deux = REGISTRE.replace("banc-fictif-sequence", "banc-fictif-bis")
        lus = R.lit_registre(REGISTRE[:-2] + "," + deux[1:])
        self.assertEqual(2, len(lus))
        self.assertIsNotNone(R.trouve(lus, "banc-ecrire"))

    def test_two_sequences_that_disagree_open_no_door(self):
        """Une porte qui trancherait au hasard lancerait parfois l'autre
        geste."""
        autre = REGISTRE.replace("banc-fictif-sequence", "banc-fictif-bis")
        autre = autre.replace('"libelle": "Ecrit"', '"libelle": "Autre chose"')
        lus = R.lit_registre(REGISTRE[:-2] + "," + autre[1:])
        self.assertEqual(2, len(lus))
        self.assertIsNone(R.trouve(lus, "banc-ecrire"))


class TestLesEcarts(unittest.TestCase):
    """Ce que todo sait et que le registre ne dit pas ENCORE."""

    def test_a_target_without_a_divergence_has_an_empty_one(self):
        """Jamais None : l'appelant lit toujours des champs."""
        vide = R.ecart("banc-fictif-sans-ecart")
        self.assertFalse(vide.interactif or vide.ecrit or vide.drapeau)

    def test_an_assistant_that_writes_is_a_write_whatever_its_nature(self):
        etape = R.Etape(
            cible="config",
            libelle="",
            portee=R.TENANT,
            nature=R.MESURE,
            pourquoi="",
            duree="",
            variables=(),
            exige_confirmation=False,
            facultative=False,
        )
        self.assertTrue(R.ecrit(etape))
        self.assertTrue(R.interactif(etape))

    def test_a_plain_measure_stays_a_measure(self):
        self.assertFalse(R.ecrit(etape(nature=R.MESURE)))
        self.assertFalse(R.interactif(etape(nature=R.MESURE)))

    def test_the_switch_is_named_only_where_there_is_one(self):
        self.assertEqual(
            "FORCE", R.drapeau(etape(cible="instancier-appliquer"))
        )
        self.assertEqual("", R.drapeau(etape(cible="deployer")))
        self.assertEqual("", R.drapeau(None))

    def test_every_divergence_says_why_it_exists(self):
        """Une dérogation sans raison écrite est une dérogation qu'on
        reconduit sans savoir pourquoi."""
        for cible, vu in R.ECARTS.items():
            with self.subTest(cible=cible):
                self.assertTrue(vu.pourquoi, cible)


@AVEC_MOTEUR
class TestContreLeRegistreReel(unittest.TestCase):
    """Les épreuves qui interrogent le MOTEUR de ce poste. Elles sautent
    là où il n'est pas rapatrié : son absence n'est pas un défaut."""

    def test_every_door_names_a_target_the_engine_declares(self):
        """Une porte dont la cible a disparu du registre mène à un écran qui
        refuse, et le menu l'annonce quand même."""
        for cible in R.PORTES:
            with self.subTest(cible=cible):
                self.assertIsNotNone(R.trouve(REEL, cible), cible)

    def test_every_divergence_names_a_target_the_engine_declares(self):
        for cible in R.ECARTS:
            with self.subTest(cible=cible):
                self.assertIsNotNone(R.trouve(REEL, cible), cible)

    def test_the_write_divergence_is_still_one(self):
        """LE JOUR OÙ LE REGISTRE LE DIT LUI-MÊME, cette épreuve rougit et
        l'entrée d'`ECARTS` doit partir : la garder masquerait la correction
        en amont."""
        for cible, vu in R.ECARTS.items():
            if not vu.ecrit:
                continue
            with self.subTest(cible=cible):
                self.assertEqual(R.MESURE, R.trouve(REEL, cible).nature, cible)

    def test_the_switch_divergence_is_still_one(self):
        """Même chose : si le registre déclare enfin ce drapeau comme une
        variable, l'entrée doit partir."""
        for cible, vu in R.ECARTS.items():
            if not vu.drapeau:
                continue
            with self.subTest(cible=cible):
                declarees = {v.nom for v in R.trouve(REEL, cible).variables}
                self.assertNotIn(vu.drapeau, declarees)


if __name__ == "__main__":
    unittest.main()
