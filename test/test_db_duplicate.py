#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Dupliquer : ce qui se refuse AVANT de créer quoi que ce soit.

Une duplication rate de deux façons. Elle peut échouer — c'est le cas
bénin, on recommence. Ou elle peut RÉUSSIR sur la mauvaise base : écraser
une copie qui contenait autre chose, ou rendre une copie qui n'est pas
neutralisée alors qu'on l'a demandé. Ces deux-là ne se rattrapent pas, et
c'est ce que ce fichier épingle.

La neutralisation n'existe qu'à partir d'Odoo 16 : `neutralize.py` est
absent avant, et `exp_duplicate_database` n'y prend que deux arguments.
Demander la neutralisation sous Odoo 15 doit être REFUSÉ, jamais ignoré
en silence — une copie qu'on croit neutralisée est pire qu'une copie
qu'on sait brute.
"""

import unittest

from script.database import db_duplicate as dup


class TestWhatANameMayBe(unittest.TestCase):
    """Le nom entre dans du SQL par `database_identifier` : il se filtre."""

    def test_ordinary_names_pass(self):
        for nom in ("sireine", "el_essai", "a", "base-2024", "_interne"):
            self.assertTrue(dup.nom_valide(nom), nom)

    def test_a_name_that_could_carry_sql_is_refused(self):
        for nom in ('a"; DROP DATABASE x; --', "a b", "a'b", "a;b", "a(b)"):
            self.assertFalse(dup.nom_valide(nom), nom)

    def test_an_empty_or_oversized_name_is_refused(self):
        self.assertFalse(dup.nom_valide(""))
        self.assertFalse(dup.nom_valide(None))
        self.assertFalse(dup.nom_valide("x" * 64))
        self.assertTrue(dup.nom_valide("x" * 63))

    def test_a_name_starting_with_a_digit_is_refused(self):
        self.assertFalse(dup.nom_valide("2024_base"))


class TestWhatIsRefusedBeforeAnythingIsCreated(unittest.TestCase):
    def setUp(self):
        # On ne veut pas d'un PostgreSQL réel : le sujet est la décision,
        # pas la connexion. `None` = « je n'ai pas pu demander », ce qui
        # doit laisser passer plutôt que d'inventer un refus.
        self._vrai = dup.bases_existantes
        dup.bases_existantes = lambda: {"source", "deja_la"}
        self.addCleanup(setattr, dup, "bases_existantes", self._vrai)

    def test_the_same_name_twice_is_refused(self):
        refus = dup.verifier("source", "source", False)
        self.assertTrue(any("nom" in r or "name" in r for r in refus))

    def test_an_unknown_source_is_refused(self):
        self.assertTrue(dup.verifier("pas_la", "neuve", False))

    def test_overwriting_an_existing_database_is_refused(self):
        """Le contenu d'avant n'existerait plus nulle part."""
        refus = dup.verifier("source", "deja_la", False)
        self.assertTrue(refus)
        self.assertTrue(any("deja_la" in r for r in refus))

    def test_a_plain_duplication_passes(self):
        self.assertEqual(dup.verifier("source", "neuve", False), [])

    def test_when_postgres_cannot_be_asked_we_do_not_invent_a_refusal(self):
        dup.bases_existantes = lambda: None
        self.assertEqual(dup.verifier("source", "neuve", False), [])


class TestNeutralisationIsRefusedBeforeOdoo16(unittest.TestCase):
    def test_the_boundary_is_sixteen(self):
        self.assertFalse(dup.supporte_neutralisation("15.0"))
        self.assertTrue(dup.supporte_neutralisation("16.0"))
        self.assertTrue(dup.supporte_neutralisation("18.0"))

    def test_an_unreadable_version_is_treated_as_unsupported(self):
        """Dans le doute, refuser : le silence serait un faux calme."""
        for version in (None, "", "quatorze"):
            self.assertFalse(dup.supporte_neutralisation(version))

    def test_an_old_checkout_falls_back_instead_of_refusing(self):
        """De 12 à 15, le dépôt a sa technique : on l'emploie."""
        self._vrai = dup.bases_existantes
        dup.bases_existantes = lambda: {"source"}
        vraie_version = dup.lire_version
        dup.lire_version = lambda nom: "15.0"
        try:
            refus = dup.verifier("source", "neuve", True)
            technique = dup.technique_neutralisation()
        finally:
            dup.bases_existantes = self._vrai
            dup.lire_version = vraie_version
        self.assertEqual(
            refus, [], "la demande a été refusée au lieu de basculer"
        )
        self.assertEqual(technique, dup.NEUTRALISATION_SCRIPT)

    def test_the_route_is_chosen_by_the_version(self):
        for version, attendu in (
            ("12.0", dup.NEUTRALISATION_SCRIPT),
            ("15.0", dup.NEUTRALISATION_SCRIPT),
            ("16.0", dup.NEUTRALISATION_ODOO),
            ("18.0", dup.NEUTRALISATION_ODOO),
        ):
            self.assertEqual(
                dup.technique_neutralisation(version), attendu, version
            )

    def test_a_missing_script_is_the_one_case_still_refused(self):
        """Sinon la copie sortirait brute en se croyant neutralisée."""
        self._vrai = dup.bases_existantes
        dup.bases_existantes = lambda: {"source"}
        vraie_version = dup.lire_version
        vrai_isfile = dup.os.path.isfile
        dup.lire_version = lambda nom: "14.0"
        dup.os.path.isfile = lambda chemin: False
        try:
            refus = dup.verifier("source", "neuve", True)
        finally:
            dup.bases_existantes = self._vrai
            dup.lire_version = vraie_version
            dup.os.path.isfile = vrai_isfile
        self.assertTrue(refus)
        self.assertTrue(any("update_prod_to_dev" in r for r in refus))


class TestTheProgramHandedToOdoo(unittest.TestCase):
    """Ce qu'on exécute, et surtout ce qu'on n'exécute pas par mégarde."""

    def test_it_parses_the_config_before_duplicating(self):
        """Sans parse_config, Registry.new échoue APRÈS avoir créé la base."""
        code = dup.script_python("a", "b", False, "config.conf")
        self.assertIn("parse_config", code)
        self.assertLess(
            code.index("parse_config"), code.index("exp_duplicate")
        )

    def test_odoo_is_not_asked_to_neutralise_when_it_cannot(self):
        """Sous 12→15, exp_duplicate_database ne prend que deux arguments :
        lui en passer un troisième ferait échouer la duplication."""
        # `lire_version` sert AUSSI à composer le venv : lui faire dire
        # « 14.0 » partout rendait le chemin introuvable et `dupliquer`
        # sortait avant d'appeler quoi que ce soit — un test vert pour
        # rien. On ne détourne donc que la version d'Odoo.
        vraie = dup.lire_version
        appels = []
        dup.lire_version = lambda nom: (
            "14.0" if nom == ".odoo-version" else vraie(nom)
        )
        vrais_chemins = dup.chemins_odoo
        dup.chemins_odoo = lambda: ("/usr/bin/python3", "/tmp")
        vrai_run = dup.subprocess.run

        class Faux:
            returncode = 0
            stdout = ""
            stderr = ""

        def espion(cmd, **kw):
            appels.append(cmd)
            return Faux()

        dup.subprocess.run = espion
        try:
            dup.dupliquer("a", "b", neutraliser=True)
        finally:
            dup.lire_version = vraie
            dup.chemins_odoo = vrais_chemins
            dup.subprocess.run = vrai_run
        programme = [c for c in appels if "-c" in c]
        self.assertTrue(programme)
        self.assertNotIn("True", programme[0][-1])
        # …et le script du dépôt a bien été lancé ensuite.
        self.assertTrue(
            any(
                dup.SCRIPT_PROD_TO_DEV in " ".join(map(str, c)) for c in appels
            )
        )

    def test_a_failing_script_makes_the_whole_thing_fail(self):
        """Le cas vraiment dangereux : la copie existe, le script a
        échoué, et l'on annoncerait « neutralisée ». Avaler ce code de
        retour rendrait une base brute indiscernable d'une base traitée.
        """
        vraie = dup.lire_version
        dup.lire_version = lambda nom: (
            "14.0" if nom == ".odoo-version" else vraie(nom)
        )
        vrais_chemins = dup.chemins_odoo
        dup.chemins_odoo = lambda: ("/usr/bin/python3", "/tmp")
        vrai_run = dup.subprocess.run

        class Reponse:
            def __init__(self, code, sortie=""):
                self.returncode = code
                self.stdout = sortie
                self.stderr = sortie

        def espion(cmd, **kw):
            # La duplication réussit, le script échoue.
            if dup.SCRIPT_PROD_TO_DEV in " ".join(map(str, cmd)):
                return Reponse(1, "install_addons_dev.sh a échoué")
            return Reponse(0)

        dup.subprocess.run = espion
        try:
            code, sortie = dup.dupliquer("a", "b", neutraliser=True)
        finally:
            dup.lire_version = vraie
            dup.chemins_odoo = vrais_chemins
            dup.subprocess.run = vrai_run
        self.assertNotEqual(code, 0, "l'échec du script a été avalé")
        self.assertIn("install_addons_dev", sortie)

    def test_neutralisation_is_passed_only_when_asked(self):
        self.assertIn("'a', 'b', True", dup.script_python("a", "b", True, "c"))
        self.assertIn("'a', 'b')", dup.script_python("a", "b", False, "c"))

    def test_the_names_travel_as_python_literals(self):
        """Ils sont interpolés dans du code : `repr` et rien d'autre."""
        code = dup.script_python("a'b", "c", False, "config.conf")
        self.assertIn(repr("a'b"), code)

    def test_the_odoo_path_is_read_from_the_version_files(self):
        """Composer le nom de tête, c'est se tromper un jour sur l'une
        des deux versions qu'il porte."""
        import inspect

        source = inspect.getsource(dup.chemins_odoo)
        self.assertIn(".erplibre-version", source)
        self.assertIn(".odoo-version", source)


class TestTheContractOfTheCommandLine(unittest.TestCase):
    def test_a_refusal_exits_two_and_creates_nothing(self):
        appels = []
        vrai = dup.dupliquer
        dup.dupliquer = lambda *a, **k: appels.append(a) or (0, "")
        vraies_bases = dup.bases_existantes
        dup.bases_existantes = lambda: {"source", "deja_la"}
        try:
            code = dup.main(["-s", "source", "-d", "deja_la"])
        finally:
            dup.dupliquer = vrai
            dup.bases_existantes = vraies_bases
        self.assertEqual(code, 2)
        self.assertEqual(appels, [], "la duplication a été tentée quand même")


if __name__ == "__main__":
    unittest.main()
