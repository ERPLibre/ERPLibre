#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce que l'outil doit garantir avant qu'on lui fasse confiance.

Deux propriétés valent tous les autres tests. La première : un module
absent n'est pas UNE catégorie — dire « manquant » là où il fallait dire
« absent du chemin des addons » envoie installer ce qui ne peut pas
l'être. La seconde : l'outil vise des bases 12 à 18 dans la même session,
et `shortdesc` y est tantôt varchar tantôt jsonb ; se tromper fait
échouer la requête entière et l'outil déclare la base illisible alors
qu'elle se porte bien.
"""

import ast
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.analyse import check_module_package as modules  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

PACKAGES = {
    "odoo18.0_base": {
        "base": "",
        "image_list": [{"module": ["queue_job", "web_dark_mode"]}],
    },
    "odoo18.0_website": {
        "base": "odoo18.0_base",
        "image_list": [{"module": ["website_extra", "queue_job"]}],
    },
    "boucle_a": {"base": "boucle_b", "image_list": [{"module": ["a"]}]},
    "boucle_b": {"base": "boucle_a", "image_list": [{"module": ["b"]}]},
}


class TestThePackageFile(unittest.TestCase):
    def test_the_path_is_absolute(self):
        # Un chemin relatif ne marchait que depuis la racine du dépôt :
        # lancé du menu TODO ou d'ailleurs, l'outil disait « fichier de
        # packages illisible » et envoyait chercher au mauvais endroit.
        self.assertTrue(os.path.isabs(modules.PACKAGE_FILE))

    def test_the_real_file_parses(self):
        reel = modules.read_packages()
        self.assertIn("odoo18.0_base", reel)

    def test_an_unreadable_file_is_empty_not_a_crash(self):
        self.assertEqual(modules.read_packages("/nowhere/at/all.json"), {})

    def test_a_file_that_is_not_a_dict_is_refused(self):
        chemin = os.path.join(os.path.dirname(__file__), "..", "README.md")
        self.assertEqual(modules.read_packages(chemin), {})


class TestTheChain(unittest.TestCase):
    def test_it_runs_root_first(self):
        self.assertEqual(
            modules.package_chain("odoo18.0_website", PACKAGES),
            ["odoo18.0_base", "odoo18.0_website"],
        )

    def test_a_root_is_alone(self):
        self.assertEqual(
            modules.package_chain("odoo18.0_base", PACKAGES), ["odoo18.0_base"]
        )

    def test_an_unknown_name_gives_nothing(self):
        self.assertEqual(modules.package_chain("pas_moi", PACKAGES), [])

    def test_a_cycle_stops_instead_of_spinning(self):
        # Sans garde, `base` circulaire ferait tourner l'outil sans fin.
        chaine = modules.package_chain("boucle_a", PACKAGES)
        self.assertEqual(sorted(chaine), ["boucle_a", "boucle_b"])


class TestWhatAPackageSuggests(unittest.TestCase):
    def test_it_inherits_from_its_base(self):
        trouve = modules.package_modules("odoo18.0_website", PACKAGES)
        self.assertEqual(
            sorted(trouve), ["queue_job", "web_dark_mode", "website_extra"]
        )

    def test_it_keeps_the_package_of_ORIGIN(self):
        # Savoir qu'un module vient de la base et non de l'extension dit
        # s'il est fondamental ou accessoire ; garder le dernier vu
        # attribuerait tout à la feuille.
        trouve = modules.package_modules("odoo18.0_website", PACKAGES)
        self.assertEqual(trouve["queue_job"], "odoo18.0_base")
        self.assertEqual(trouve["website_extra"], "odoo18.0_website")

    def test_the_real_18_package_has_its_fifteen(self):
        reel = modules.read_packages()
        self.assertEqual(
            len(modules.package_modules("odoo18.0_base", reel)), 15
        )


class TestTheVersion(unittest.TestCase):
    def test_it_keeps_two_components(self):
        self.assertEqual(modules.default_package("18.0"), "odoo18.0_base")

    def test_no_version_gives_no_package(self):
        self.assertIsNone(modules.default_package(None))


class TestReadingAColumn(unittest.TestCase):
    """`shortdesc` est varchar jusqu'en 15, jsonb ensuite."""

    def test_a_plain_column_is_read_plainly(self):
        sql = modules.as_text("shortdesc", {"shortdesc": "character varying"})
        self.assertNotIn("->>", sql)
        self.assertIn("shortdesc", sql)

    def test_a_jsonb_column_is_extracted(self):
        sql = modules.as_text("shortdesc", {"shortdesc": "jsonb"})
        self.assertIn("->>", sql)
        self.assertIn("en_US", sql)

    def test_an_unknown_column_is_treated_as_plain(self):
        self.assertNotIn("->>", modules.as_text("shortdesc", {}))


class TestTheVerdicts(unittest.TestCase):
    CONNUS = {
        "installe": ("installed", "", False, "Odoo"),
        "a_maj": ("to upgrade", "", False, "Odoo"),
        "dispo": ("uninstalled", "", False, "OCA"),
        "casse": ("uninstallable", "", False, "OCA"),
        "en_cours": ("to install", "", False, "OCA"),
    }

    def test_each_state_maps_to_its_verdict(self):
        for nom, attendu in (
            ("installe", "installed"),
            ("a_maj", "installed"),
            ("dispo", "available"),
            ("casse", "uninstallable"),
            ("en_cours", "pending"),
        ):
            self.assertEqual(
                modules.verdict_of(nom, self.CONNUS), attendu, nom
            )

    def test_a_module_the_database_never_heard_of_is_unknown(self):
        # Le distinguer de « disponible » est tout l'intérêt : il n'y a
        # rien à installer tant que le chemin des addons est incomplet.
        self.assertEqual(
            modules.verdict_of("jamais_vu", self.CONNUS), "unknown"
        )

    def test_an_unexpected_state_is_not_silently_installed(self):
        # Un état qu'Odoo ajouterait demain ne doit pas passer pour
        # installé : mieux vaut le signaler que de le taire.
        etrange = {"x": ("something_new", "", False, "")}
        self.assertNotEqual(modules.verdict_of("x", etrange), "installed")


class TestBlockingDependencies(unittest.TestCase):
    CONNUS = {
        "moi": ("uninstalled", "", False, ""),
        "ok": ("installed", "", False, ""),
        "dispo": ("uninstalled", "", False, ""),
        "casse": ("uninstallable", "", False, ""),
    }

    def test_only_what_truly_blocks_is_listed(self):
        depend = {"moi": ["ok", "dispo", "casse", "absent"]}
        self.assertEqual(
            modules.blocking_dependencies("moi", self.CONNUS, depend),
            ["absent", "casse"],
        )

    def test_no_dependency_is_no_problem(self):
        self.assertEqual(
            modules.blocking_dependencies("moi", self.CONNUS, {}), []
        )


class FakeBase:
    """Une base qui répond, sans PostgreSQL.

    On aiguille sur le SQL plutôt que sur l'ordre des appels : un test qui
    compte les appels casse dès qu'on réordonne le code sans rien changer
    au comportement.
    """

    def __init__(
        self,
        connus,
        depend=None,
        jsonb=False,
        muette=False,
        sans_colonnes=False,
        sans_recensement=False,
    ):
        self.connus = connus
        self.depend = depend or {}
        self.jsonb = jsonb
        self.muette = muette
        self.sans_colonnes = sans_colonnes
        self.sans_recensement = sans_recensement
        self.vues = []

    def __call__(self, database, sql):
        self.vues.append(sql)
        if self.muette:
            return None
        if "information_schema.columns" in sql:
            if self.sans_colonnes:
                return []
            desc = "jsonb" if self.jsonb else "character varying"
            return [
                ["name", "character varying"],
                ["shortdesc", desc],
                ["author", "character varying"],
                ["state", "character varying"],
            ]
        if "latest_version" in sql:
            return [["18.0.1.3"]]
        if "ir_module_module_dependency" in sql:
            return [
                [mod, dep] for mod, lst in self.depend.items() for dep in lst
            ]
        if "FROM ir_module_module" in sql:
            if self.sans_recensement:
                return None
            return [
                [nom, etat, desc, "1" if app else "0", auteur]
                for nom, (etat, desc, app, auteur) in self.connus.items()
            ]
        return []


CONNUS = {
    "queue_job": ("uninstalled", "Job Queue", False, "OCA"),
    "web_dark_mode": ("installed", "Dark Mode", False, "OCA"),
    "base": ("installed", "Base", False, "Odoo S.A."),
    "casse": ("uninstallable", "Cassé", False, "OCA"),
}


class TestTheAudit(unittest.TestCase):
    def setUp(self):
        self.vrai = modules.run_psql

    def tearDown(self):
        modules.run_psql = self.vrai

    def audite(self, connus=None, depend=None, jsonb=False, package=None):
        modules.run_psql = FakeBase(
            CONNUS if connus is None else connus, depend, jsonb
        )
        return modules.audit("db", package=package, packages=PACKAGES)

    def test_it_finds_the_package_from_the_database_version(self):
        rapport = self.audite()
        self.assertEqual(rapport["version"], "18.0")
        self.assertEqual(rapport["package"], "odoo18.0_base")
        self.assertTrue(rapport["package_known"])

    def test_it_classifies_each_suggested_module(self):
        rapport = self.audite()
        verdicts = {
            ligne["module"]: ligne["verdict"] for ligne in rapport["lines"]
        }
        self.assertEqual(
            verdicts, {"queue_job": "available", "web_dark_mode": "installed"}
        )

    def test_a_module_absent_from_the_database_is_unknown(self):
        rapport = self.audite(
            connus={"base": ("installed", "", False, "Odoo")}
        )
        verdicts = {
            ligne["module"]: ligne["verdict"] for ligne in rapport["lines"]
        }
        self.assertEqual(verdicts["queue_job"], "unknown")

    def test_it_reports_what_installing_would_still_need(self):
        rapport = self.audite(
            depend={"queue_job": ["casse", "base", "fantome"]}
        )
        ligne = [x for x in rapport["lines"] if x["module"] == "queue_job"][0]
        self.assertEqual(ligne["needs"], ["casse", "fantome"])

    def test_a_jsonb_database_is_read_not_refused(self):
        # Sur une base 16+, `shortdesc` est jsonb. Une requête écrite pour
        # du varchar y échoue ENTIÈREMENT et l'outil déclarerait la base
        # illisible.
        rapport = self.audite(jsonb=True)
        self.assertFalse(rapport.get("unavailable"))
        recensement = [
            s
            for s in modules.run_psql.vues
            if "FROM ir_module_module" in s
            and "dependency" not in s
            and "latest_version" not in s
        ]
        self.assertTrue(any("->>" in s for s in recensement), recensement)

    def test_a_silent_database_is_unavailable_not_empty(self):
        # Rendre un rapport vide ferait croire à une base sans modules.
        modules.run_psql = FakeBase({}, muette=True)
        self.assertTrue(modules.audit("db", packages=PACKAGES)["unavailable"])

    def test_a_database_without_the_module_table_is_unavailable(self):
        # Pas de table `ir_module_module` : ce n'est pas une base Odoo.
        modules.run_psql = FakeBase(CONNUS, sans_colonnes=True)
        self.assertTrue(modules.audit("db", packages=PACKAGES)["unavailable"])

    def test_a_census_query_that_fails_is_unavailable(self):
        # Les colonnes répondent, le recensement non — l'autre garde. Les
        # tester ensemble laissait chacune masquer la panne de l'autre.
        modules.run_psql = FakeBase(CONNUS, sans_recensement=True)
        self.assertTrue(modules.audit("db", packages=PACKAGES)["unavailable"])

    def test_the_census_counts_every_module_not_only_the_suggested(self):
        rapport = self.audite()
        self.assertEqual(rapport["total"], len(CONNUS))
        self.assertEqual(rapport["by_state"]["installed"], 2)

    def test_extras_are_what_is_installed_beyond_the_package(self):
        rapport = self.audite()
        self.assertIn("base", rapport["extra"])
        self.assertNotIn("web_dark_mode", rapport["extra"])

    def test_an_unknown_package_is_flagged_not_silently_empty(self):
        rapport = self.audite(package="jamais_defini")
        self.assertFalse(rapport["package_known"])
        self.assertEqual(rapport["lines"], [])


class TestTheOrderOfTheReport(unittest.TestCase):
    def ligne(self, module, verdict):
        return {
            "module": module,
            "verdict": verdict,
            "from": "p",
            "state": "",
            "shortdesc": "",
            "needs": [],
        }

    def test_the_worst_comes_first(self):
        # « unknown » demande de réparer le chemin des addons avant tout
        # le reste : le lire en dernier ferait installer dans le vide.
        rapport = {
            "lines": [
                self.ligne("aaa", "available"),
                self.ligne("zzz", "unknown"),
                self.ligne("mmm", "uninstallable"),
                self.ligne("bbb", "installed"),
            ]
        }
        self.assertEqual(
            [x["module"] for x in modules.missing(rapport)],
            ["zzz", "mmm", "aaa"],
        )

    def test_installed_modules_never_appear(self):
        rapport = {"lines": [self.ligne("z", "installed")]}
        self.assertEqual(modules.missing(rapport), [])

    def test_every_verdict_has_a_rank_and_an_icon_and_a_wording(self):
        # Un verdict sans rang ferait planter le tri ; sans libellé, le
        # rapport nommerait l'état sans nommer le geste.
        for verdict in modules.VERDICTS:
            self.assertIn(verdict, modules.ICONE)
            self.assertIn(verdict, modules.EXPLICATION)
        for verdict in modules.ETAT_VERS_VERDICT.values():
            self.assertIn(verdict, modules.VERDICTS)


class TestTheRendering(unittest.TestCase):
    def rapport(self, **extra):
        base = {
            "database": "db",
            "version": "18.0",
            "package": "odoo18.0_base",
            "package_known": True,
            "chain": ["odoo18.0_base"],
            "lines": [],
            "by_state": {"installed": 2},
            "total": 2,
            "installed": ["base"],
            "extra": [],
            "authors": [("Odoo S.A.", 2)],
        }
        base.update(extra)
        return base

    def test_a_clean_database_says_so(self):
        texte = "\n".join(modules.render(self.rapport()))
        self.assertIn(
            todo_i18n.t("Every suggested module is installed."), texte
        )

    def test_an_unknown_package_never_claims_success(self):
        # Comparé à rien, TOUT semble installé : le dire serait un
        # mensonge tranquille, le pire des rapports.
        texte = "\n".join(
            modules.render(self.rapport(package_known=False, package="?"))
        )
        self.assertNotIn(
            todo_i18n.t("Every suggested module is installed."), texte
        )
        self.assertIn(
            todo_i18n.t("No default package known for this version"), texte
        )

    def test_a_missing_module_names_the_action(self):
        ligne = {
            "module": "queue_job",
            "verdict": "unknown",
            "from": "p",
            "state": "",
            "shortdesc": "Job Queue",
            "needs": [],
        }
        texte = "\n".join(modules.render(self.rapport(lines=[ligne])))
        self.assertIn("queue_job", texte)
        self.assertIn(
            todo_i18n.t("absent from the addons path — sync the repo first"),
            texte,
        )

    def test_an_unreadable_database_renders_without_crashing(self):
        texte = "\n".join(
            modules.render({"unavailable": True, "database": "x"})
        )
        self.assertIn("x", texte)

    def test_the_limit_caps_the_list_and_says_how_many_were_hidden(self):
        lignes = [
            {
                "module": f"m{i}",
                "verdict": "available",
                "from": "p",
                "state": "",
                "shortdesc": "",
                "needs": [],
            }
            for i in range(10)
        ]
        texte = "\n".join(modules.render(self.rapport(lines=lignes), limit=3))
        self.assertIn("m0", texte)
        self.assertNotIn("m9", texte)
        self.assertIn(f"7 {todo_i18n.t('more')}", texte)


class TestTheCommandLine(unittest.TestCase):
    def setUp(self):
        self.vrai = modules.run_psql

    def tearDown(self):
        modules.run_psql = self.vrai

    @classmethod
    def setUpClass(cls):
        import json
        import tempfile

        cls.dossier = tempfile.TemporaryDirectory()
        cls.fichier = os.path.join(cls.dossier.name, "packages.json")
        with io.open(cls.fichier, "w", encoding="utf-8") as handle:
            json.dump(PACKAGES, handle)

    @classmethod
    def tearDownClass(cls):
        cls.dossier.cleanup()

    def lance(self, argv, connus=CONNUS, muette=False):
        modules.run_psql = FakeBase(connus, muette=muette)
        argv = list(argv) + ["--file", self.fichier]
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            code = modules.main(argv)
        return code, tampon.getvalue()

    def test_nothing_missing_exits_zero(self):
        code, _ = self.lance(
            ["-d", "db", "-p", "odoo18.0_base"],
            connus={
                "web_dark_mode": ("installed", "", False, ""),
                "queue_job": ("installed", "", False, ""),
            },
        )
        self.assertEqual(code, 0)

    def test_a_finding_exits_one(self):
        code, sortie = self.lance(["-d", "db"])
        self.assertEqual(code, 1)
        self.assertIn("queue_job", sortie)

    def test_an_unreadable_database_exits_two(self):
        # 2 dit « l'outil a échoué », pas « rien trouvé » : un script qui
        # confond les deux conclurait que tout va bien.
        code, _ = self.lance(["-d", "db"], muette=True)
        self.assertEqual(code, 2)

    def test_listing_packages_needs_no_database(self):
        code, sortie = self.lance(["--list-packages"])
        self.assertEqual(code, 0)
        self.assertIn("odoo18.0_base", sortie)

    def test_json_output_is_parseable(self):
        import json

        code, sortie = self.lance(["-d", "db", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(sortie)["package"], "odoo18.0_base")


class TestTheWiring(unittest.TestCase):
    RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

    def source(self, chemin):
        with io.open(os.path.join(self.RACINE, chemin), encoding="utf-8") as f:
            return f.read()

    def test_every_translation_key_exists(self):
        # Une clé absente s'affiche en anglais au milieu du français, et
        # rien ne le signale à l'exécution.
        src = self.source("script/analyse/check_module_package.py")
        arbre = ast.parse(src)
        cles = set()
        for node in ast.walk(arbre):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "t"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                cles.add(node.args[0].value)
        cles.update(modules.EXPLICATION.values())
        manquantes = [c for c in cles if c not in todo_i18n.TRANSLATIONS]
        self.assertEqual(manquantes, [])

    def test_the_menu_offers_the_entry_and_dispatches_it(self):
        src = self.source("script/todo/todo.py")
        self.assertIn("Modules missing from the default package", src)
        self.assertIn("self.execute_analyse_module_package()", src)
        self.assertIn("def execute_analyse_module_package", src)

    def test_the_menu_has_as_many_entries_as_branches(self):
        # Ajouter une entrée sans son aiguillage donne « Command not
        # found » sur un choix que le menu vient d'afficher.
        src = self.source("script/todo/todo.py")
        debut = src.index("def prompt_execute_analyse")
        fin = src.index("def execute_analyse_module_package")
        self.assertLess(debut, fin)
        bloc = src[debut:fin]
        entrees = bloc.count('"prompt_description"')
        branches = sum(
            f'status == "{n}"' in bloc for n in range(1, entrees + 2)
        )
        self.assertEqual(entrees, branches)


if __name__ == "__main__":
    unittest.main()
