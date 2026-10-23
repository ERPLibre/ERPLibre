#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La traduction de la syntaxe d'Odoo 18 vers les anciens drapeaux.

translate() est pure : chaque cas compare la liste exacte des étapes. Les
noms de bases, d'images et de fichiers sont inventés. main() est éprouvé
avec subprocess bouchonné : aucun Odoo, aucune base.
"""

import ast
import importlib.util
import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(RACINE, "script", "database", "odoo_db_legacy.py")

_spec = importlib.util.spec_from_file_location("odoo_db_legacy", SCRIPT)
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)

ENV = {"ERPLIBRE_ODOO_CLI_LEGACY": "1"}


def odoo(*argv, env=None):
    return L.Step("odoo_bin", ["db"] + list(argv), env or ENV)


class Base(unittest.TestCase):
    version = "14.0"

    def t(self, *argv):
        return L.translate(list(argv), self.version)

    def refus(self, *argv):
        with self.assertRaises(L.LegacyUsageError) as ctx:
            self.t(*argv)
        return str(ctx.exception)


class TestLesListes(Base):
    def test_list(self):
        self.assertEqual([odoo("--list")], self.t("db", "list"))

    def test_list_incompatible(self):
        self.assertEqual(
            [odoo("--list_incompatible_db")],
            self.t("db", "list-incompatible"),
        )

    def test_version(self):
        self.assertEqual([odoo("--version")], self.t("db", "version"))

    def test_c_devient_odoo_rc(self):
        env = dict(ENV, ODOO_RC="/srv/x/autre.conf")
        for forme in (
            ["-c", "/srv/x/autre.conf"],
            ["--config", "/srv/x/autre.conf"],
            ["--config=/srv/x/autre.conf"],
        ):
            self.assertEqual(
                [odoo("--list", env=env)], self.t("db", *forme, "list")
            )

    def test_une_autre_globale_est_refusee(self):
        message = self.refus("db", "--db_host", "hote_invente", "list")
        self.assertIn("--db_host", message)
        self.assertIn("erplibre_odoo_cli_base", message)


class TestCreate(Base):
    def test_seulement_le_nom(self):
        self.assertEqual(
            [odoo("--create", "--database", "base_bidon")],
            self.t("db", "create", "base_bidon"),
        )

    def test_toutes_les_options(self):
        self.assertEqual(
            [
                odoo(
                    "--create",
                    "--database",
                    "base_bidon",
                    "--demo",
                    "--user_lang",
                    "en_US",
                    "--user_login",
                    "chef",
                    "--user_password",
                    "secret_invente",
                    "--user_phone",
                    "5550000",
                    "--user_country_code",
                    "fr",
                )
            ],
            self.t(
                "db",
                "create",
                "--lang",
                "en_US",
                "--login",
                "chef",
                "--password",
                "secret_invente",
                "--phone",
                "5550000",
                "--country",
                "fr",
                "base_bidon",
                "--demo",
            ),
        )

    def test_force_supprime_d_abord(self):
        self.assertEqual(
            [
                odoo("--drop", "--database", "base_bidon"),
                odoo("--create", "--database", "base_bidon"),
            ],
            self.t("db", "create", "-f", "base_bidon"),
        )


class TestDrop(Base):
    def test_strict_verifie_l_existence(self):
        self.assertEqual(
            [
                L.Step("require_db", ["base_bidon"], ENV),
                odoo("--drop", "--database", "base_bidon"),
            ],
            self.t("db", "drop", "base_bidon"),
        )

    def test_if_exists_supprime_directement(self):
        self.assertEqual(
            [odoo("--drop", "--database", "base_bidon")],
            self.t("db", "drop", "--if-exists", "base_bidon"),
        )


class TestLoad(Base):
    def test_image_avec_base(self):
        self.assertEqual(
            [
                odoo(
                    "--restore",
                    "--database",
                    "base_bidon",
                    "--restore_image",
                    "image_bidon",
                )
            ],
            self.t("db", "load", "base_bidon", "--image", "image_bidon"),
        )

    def test_image_sans_base_prend_le_nom_de_l_image(self):
        for valeur in ("image_bidon", "image_bidon.zip"):
            self.assertEqual(
                [
                    odoo(
                        "--restore",
                        "--database",
                        "image_bidon",
                        "--restore_image",
                        valeur,
                    )
                ],
                self.t("db", "load", "--image=" + valeur),
            )

    def test_image_chemin_devient_un_fichier(self):
        self.assertEqual(
            [
                odoo(
                    "--restore",
                    "--database",
                    "copie",
                    "--restore_db_file",
                    "/srv/sauvegardes/copie.zip",
                )
            ],
            self.t("db", "load", "--image", "/srv/sauvegardes/copie"),
        )

    def test_fichier_avec_base(self):
        self.assertEqual(
            [
                odoo(
                    "--restore",
                    "--database",
                    "base_bidon",
                    "--restore_db_file",
                    "./x/copie.zip",
                )
            ],
            self.t("db", "load", "base_bidon", "./x/copie.zip"),
        )

    def test_fichier_seul_prend_son_nom(self):
        self.assertEqual(
            [
                odoo(
                    "--restore",
                    "--database",
                    "copie",
                    "--restore_db_file",
                    "./x/copie.zip",
                )
            ],
            self.t("db", "load", "./x/copie.zip"),
        )

    def test_force_supprime_d_abord(self):
        etapes = self.t("db", "load", "-f", "base_bidon", "--image", "img")
        self.assertEqual(odoo("--drop", "--database", "base_bidon"), etapes[0])
        self.assertEqual(2, len(etapes))

    def test_move_est_accepte_sans_drapeau_avant_16(self):
        self.assertEqual(
            self.t("db", "load", "base_bidon", "--image", "img"),
            self.t("db", "load", "--move", "base_bidon", "--image", "img"),
        )

    def test_neutralize_refuse_avant_16(self):
        message = self.refus("db", "load", "-n", "b", "--image", "img")
        self.assertIn("--neutralize needs Odoo 16", message)

    def test_url_refusee(self):
        message = self.refus("db", "load", "https://exemple.invalid/a.zip")
        self.assertIn("URL", message)

    def test_rien_a_charger(self):
        self.refus("db", "load")

    def test_image_et_deux_positionnels(self):
        self.refus("db", "load", "a", "b", "--image", "img")

    def test_image_vide(self):
        self.refus("db", "load", "--image=")


class TestLoadDes16(Base):
    version = "16.0"

    def test_neutralize_et_move_passent(self):
        self.assertEqual(
            [
                odoo(
                    "--restore",
                    "--database",
                    "base_bidon",
                    "--restore_image",
                    "img",
                    "--neutralize",
                    "--move_database",
                )
            ],
            self.t(
                "db", "load", "-n", "--move", "base_bidon", "--image", "img"
            ),
        )

    def test_duplicate_neutralize(self):
        self.assertEqual(
            [
                odoo(
                    "--clone",
                    "--from_database",
                    "a",
                    "--database",
                    "b",
                    "--neutralize",
                )
            ],
            self.t("db", "duplicate", "a", "b", "--neutralize"),
        )


class TestDump(Base):
    def test_image(self):
        self.assertEqual(
            [
                odoo(
                    "--backup",
                    "--database",
                    "base_bidon",
                    "--restore_image",
                    "img",
                )
            ],
            self.t("db", "dump", "base_bidon", "--image", "img"),
        )

    def test_image_chemin(self):
        self.assertEqual(
            [
                odoo(
                    "--backup",
                    "--database",
                    "base_bidon",
                    "--restore_db_file",
                    "./x/img.zip",
                )
            ],
            self.t("db", "dump", "base_bidon", "--image", "./x/img"),
        )

    def test_chemin(self):
        self.assertEqual(
            [
                odoo(
                    "--backup",
                    "--database",
                    "base_bidon",
                    "--restore_db_file",
                    "/srv/s.zip",
                )
            ],
            self.t("db", "dump", "base_bidon", "/srv/s.zip"),
        )

    def test_vers_stdout_refuse(self):
        for argv in (("base_bidon",), ("base_bidon", "-")):
            message = self.refus("db", "dump", *argv)
            self.assertIn("stdout", message)


class TestDuplicateRename(Base):
    def test_duplicate(self):
        self.assertEqual(
            [odoo("--clone", "--from_database", "a", "--database", "b")],
            self.t("db", "duplicate", "a", "b"),
        )

    def test_duplicate_force(self):
        self.assertEqual(
            [
                odoo("--drop", "--database", "b"),
                odoo("--clone", "--from_database", "a", "--database", "b"),
            ],
            self.t("db", "duplicate", "-f", "a", "b"),
        )

    def test_duplicate_neutralize_refuse_avant_16(self):
        self.refus("db", "duplicate", "-n", "a", "b")

    def test_rename_refuse(self):
        message = self.refus("db", "rename", "a", "b")
        self.assertIn("rename", message)
        self.assertIn("erplibre_odoo_cli_base", message)


class TestRefusDes16(Base):
    """Un fork 16 ou 17 sans le module garde l'ancienne commande : ce
    qu'elle ne sait pas faire reste refusé, sans prétendre qu'il suffirait
    d'Odoo 16."""

    version = "16.0"

    def test_aucun_refus_ne_reclame_odoo_16(self):
        for argv in (
            ("db", "rename", "a", "b"),
            ("db", "dump", "base_bidon"),
            ("db", "load", "https://exemple.invalid/a.zip"),
            ("db", "--db_host", "hote_invente", "list"),
        ):
            message = self.refus(*argv)
            self.assertNotIn("Odoo 16", message)
            self.assertIn("erplibre_odoo_cli_base", message)


class TestLesErreursDeSyntaxe(Base):
    def test_sous_commande_inconnue(self):
        self.refus("db", "inconnue")

    def test_option_abregee_refusee(self):
        # allow_abbrev=False : « --if » n'est pas « --if-exists ».
        self.refus("db", "drop", "--if", "b")

    def test_commande_inconnue(self):
        self.refus("autre", "x")

    def test_db_seul_affiche_l_aide_et_sort_en_1(self):
        erreur = io.StringIO()
        with redirect_stderr(erreur), self.assertRaises(SystemExit) as ctx:
            self.t("db")
        self.assertEqual(1, ctx.exception.code)
        self.assertIn("usage", erreur.getvalue())

    def test_aide_sort_en_0(self):
        sortie = io.StringIO()
        with redirect_stdout(sortie), self.assertRaises(SystemExit) as ctx:
            self.t("db", "-h")
        self.assertEqual(0, ctx.exception.code)
        self.assertIn("list-incompatible", sortie.getvalue())


class TestModuleTheme(Base):
    def test_module_uninstall(self):
        self.assertEqual(
            [
                L.Step(
                    "run_sh",
                    [
                        "--no-http",
                        "--stop-after-init",
                        "-d",
                        "b",
                        "--uninstall",
                        "m1,m2",
                    ],
                    ENV,
                )
            ],
            self.t("module", "uninstall", "-d", "b", "m1,m2"),
        )

    def test_module_uninstall_c_et_globales(self):
        (etape,) = self.t(
            "module",
            "uninstall",
            "-c",
            "f.conf",
            "--db_port",
            "5999",
            "-d",
            "b",
            "m1",
        )
        self.assertEqual(
            [
                "--no-http",
                "--stop-after-init",
                "-d",
                "b",
                "--uninstall",
                "m1",
                "-c",
                "f.conf",
                "--db_port",
                "5999",
            ],
            etape.args,
        )

    def test_theme_apply_passe_par_le_shell(self):
        self.assertEqual(
            [
                L.Step(
                    "odoo_bin",
                    ["shell", "--no-http", "-d", "b", "-c", "f.conf"],
                    dict(ENV, ERPLIBRE_THEME_APPLY="theme_bidon"),
                    L.SCRIPT_THEME,
                )
            ],
            self.t("theme", "apply", "-c", "f.conf", "-d", "b", "theme_bidon"),
        )

    def test_theme_apply_globales(self):
        (etape,) = self.t(
            "theme", "apply", "--db_port", "5999", "-d", "b", "theme_bidon"
        )
        self.assertEqual(
            ["shell", "--no-http", "-d", "b", "--db_port", "5999"],
            etape.args,
        )

    def test_le_script_du_theme(self):
        """Le script compile en 3.7, lit le nom dans l'environnement et
        n'appelle pas button_choose_theme, dont l'action de redirection
        exige une requête HTTP."""
        ast.parse(L.SCRIPT_THEME, feature_version=(3, 7))
        self.assertIn('os.environ["ERPLIBRE_THEME_APPLY"]', L.SCRIPT_THEME)
        self.assertNotIn("button_choose_theme", L.SCRIPT_THEME)
        for appel in (
            "button_immediate_install()",
            "_theme_remove(site)",
            "_theme_upgrade_upstream()",
            "env.cr.commit()",
        ):
            self.assertIn(appel, L.SCRIPT_THEME)

    def _est_theme(self):
        """est_theme du script, isolé : la partie qui précède l'appel à env."""
        source = L.SCRIPT_THEME.split("\ntheme = env")[0]
        espace = {}
        with mock.patch.dict(
            sys.modules, {"odoo": mock.MagicMock()}
        ), mock.patch.dict(os.environ, {"ERPLIBRE_THEME_APPLY": "t"}):
            exec(source, espace)
        return espace["est_theme"]

    def test_le_domaine_des_themes_vient_de_get_themes_domain(self):
        """15 et plus : le domaine d'Odoo, complété de l'id du module."""
        module = mock.Mock(spec=["get_themes_domain", "search_count"])
        module.get_themes_domain.return_value = [("x", "=", 1)]
        module.search_count.return_value = 1
        e = {"website": object(), "ir.module.module": module}
        self.assertTrue(self._est_theme()(e, mock.Mock(id=7)))
        module.search_count.assert_called_once_with(
            [("x", "=", 1), ("id", "=", 7)]
        )

    def test_avant_15_le_domaine_est_la_categorie_theme(self):
        """12 à 14 n'ont pas get_themes_domain : la catégorie Theme et ses
        sous-catégories font le domaine."""
        module = mock.Mock(spec=["search_count"])
        module.search_count.return_value = 0
        e = mock.MagicMock()
        e.__contains__.side_effect = lambda cle: cle == "website"
        e.__getitem__.side_effect = lambda cle: module
        e.ref.return_value = mock.Mock(id=42)
        self.assertFalse(self._est_theme()(e, mock.Mock(id=7)))
        e.ref.assert_called_once_with("base.module_category_theme")
        module.search_count.assert_called_once_with(
            [("category_id", "child_of", 42), ("id", "=", 7)]
        )

    def test_module_uninstall_n_a_pas_d_entree(self):
        (etape,) = self.t("module", "uninstall", "-d", "b", "m1")
        self.assertIsNone(etape.stdin)

    def test_d_obligatoire(self):
        self.refus("module", "uninstall", "m1")
        self.refus("theme", "apply", "theme_bidon")

    def test_sans_action_sort_en_1(self):
        for commande in ("module", "theme"):
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    self.t(commande)
            self.assertEqual(1, ctx.exception.code)


class TestToutesLesEtapesMarquentLeurEnvironnement(Base):
    def test_chaque_etape_porte_la_variable(self):
        for argv in (
            ("db", "list"),
            ("db", "drop", "b"),
            ("db", "create", "-f", "b"),
            ("db", "load", "-f", "b", "--image", "img"),
            ("module", "uninstall", "-d", "b", "m"),
            ("theme", "apply", "-d", "b", "t"),
        ):
            for etape in self.t(*argv):
                self.assertEqual("1", etape.env["ERPLIBRE_ODOO_CLI_LEGACY"])


class TestMain(unittest.TestCase):
    def lancer(self, argv, codes, liste="base_bidon\nautre\n"):
        """main() avec .odoo-version à 14.0 et des enfants bouchonnés.

        codes : le code de chaque appel à subprocess.call, dans l'ordre.
        """
        appels = []

        def call(argv_enfant, env=None):
            appels.append((argv_enfant, env))
            return codes.pop(0)

        fait = subprocess.CompletedProcess([], 0, stdout=liste)
        erreur = io.StringIO()
        with mock.patch.object(L, "lire_version", return_value="14.0"):
            with mock.patch.object(L.subprocess, "call", side_effect=call):
                with mock.patch.object(
                    L.subprocess, "run", return_value=fait
                ) as run:
                    with redirect_stderr(erreur):
                        code = L.main(argv)
        return code, appels, run, erreur.getvalue()

    def test_les_etapes_s_enchainent(self):
        code, appels, _run, _err = self.lancer(
            ["db", "create", "-f", "b"], [0, 0]
        )
        self.assertEqual(0, code)
        self.assertEqual(
            [
                ["./odoo_bin.sh", "db", "--drop", "--database", "b"],
                ["./odoo_bin.sh", "db", "--create", "--database", "b"],
            ],
            [a for a, _env in appels],
        )
        self.assertEqual("1", appels[0][1]["ERPLIBRE_ODOO_CLI_LEGACY"])

    def test_la_premiere_qui_echoue_arrete_tout(self):
        code, appels, _run, _err = self.lancer(
            ["db", "create", "-f", "b"], [3, 0]
        )
        self.assertEqual(3, code)
        self.assertEqual(1, len(appels))

    def test_require_db_absente(self):
        code, appels, run, err = self.lancer(["db", "drop", "absente"], [])
        self.assertEqual(1, code)
        self.assertEqual([], appels)
        self.assertIn("Database absente does not exist.", err)
        self.assertEqual(
            ["./odoo_bin.sh", "db", "--list"], run.call_args[0][0]
        )
        self.assertIs(subprocess.DEVNULL, run.call_args[1]["stderr"])

    def test_require_db_presente(self):
        code, appels, _run, _err = self.lancer(["db", "drop", "autre"], [0])
        self.assertEqual(0, code)
        self.assertEqual(
            ["./odoo_bin.sh", "db", "--drop", "--database", "autre"],
            appels[0][0],
        )

    def test_c_passe_par_odoo_rc(self):
        _code, appels, _run, _err = self.lancer(
            ["db", "-c", "/srv/x/autre.conf", "list"], [0]
        )
        self.assertEqual("/srv/x/autre.conf", appels[0][1]["ODOO_RC"])

    def test_run_sh_pour_module(self):
        _code, appels, _run, _err = self.lancer(
            ["module", "uninstall", "-d", "b", "m"], [0]
        )
        self.assertEqual("./run.sh", appels[0][0][0])

    def test_theme_donne_le_script_sur_stdin(self):
        code, appels, run, _err = self.lancer(
            ["theme", "apply", "-d", "b", "theme_bidon"], []
        )
        self.assertEqual(0, code)
        self.assertEqual([], appels)
        self.assertEqual(
            ["./odoo_bin.sh", "shell", "--no-http", "-d", "b"],
            run.call_args[0][0],
        )
        self.assertEqual(L.SCRIPT_THEME, run.call_args[1]["input"])
        env = run.call_args[1]["env"]
        self.assertEqual("theme_bidon", env["ERPLIBRE_THEME_APPLY"])
        self.assertEqual("1", env["ERPLIBRE_ODOO_CLI_LEGACY"])

    def test_erreur_d_usage_sort_en_2(self):
        code, appels, _run, err = self.lancer(["db", "rename", "a", "b"], [])
        self.assertEqual(2, code)
        self.assertEqual([], appels)
        self.assertIn("db rename is not supported", err)


class TestPython37(unittest.TestCase):
    """Le script tourne dans le venv d'Odoo 12 et 13 : Python 3.7."""

    def source(self):
        with open(SCRIPT, encoding="utf-8") as fichier:
            return fichier.read()

    def test_la_syntaxe_est_celle_de_3_7(self):
        ast.parse(self.source(), feature_version=(3, 7))

    def test_aucune_methode_venue_apres_3_7(self):
        for absent in ("removesuffix", "removeprefix", ":="):
            self.assertNotIn(absent, self.source())
            self.assertNotIn(absent, L.SCRIPT_THEME)


if __name__ == "__main__":
    unittest.main()
