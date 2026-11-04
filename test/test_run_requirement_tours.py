#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le lanceur des tours de requis, sans navigateur ni serveur.

Le verdict d'un tour passe par trois traductions : la console de la page
vers (ok, message), (ok, message) vers une valeur record_result, puis
l'ensemble des valeurs vers un code de sortie. Chacune peut rendre un vert
immérité sans bruit — un tour absent compté comme réussi, un verdict non
remonté oublié, zéro tour lu comme zéro échec. Ces tests les fixent avec un
pilote et un serveur XML-RPC simulés.

Les identifiants, codes et noms de tours sont inventés.
"""

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import xml.parsers.expat
import xmlrpc.client
from types import SimpleNamespace
from unittest import mock

sys.path.insert(
    0, os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from selenium.common.exceptions import WebDriverException  # noqa: E402

from script.selenium import run_requirement_tours as rrt  # noqa: E402
from script.selenium import selenium_lib, web_login  # noqa: E402

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
TOUR_AUTOMATIC = os.path.join(
    RACINE,
    "odoo18.0/odoo/addons/web_tour/static/src/tour_service/tour_automatic.js",
)


def parser_complet():
    # Celui de main() : un réglage du parseur, comme allow_abbrev, est
    # éprouvé là où il sert.
    return rrt.construire_parser()


def config(*argv, environ=None):
    """Rend la configuration de argv ; l'environnement vaut {} par défaut,
    pour que les variables de la machine ne changent pas le résultat."""
    args = parser_complet().parse_args(list(argv))
    rrt.compute_args(args, environ={} if environ is None else environ)
    return args


ENV_EXEC = {
    rrt.ENV_LOGIN_DEFAUT: "exec_tours_invente",
    rrt.ENV_PASSWORD_DEFAUT: "mdp-invente-7391",
}


class TestVerdictVersResultat(unittest.TestCase):
    def test_trois_issues(self):
        self.assertEqual(rrt.resultat_du_verdict(True), "passed")
        self.assertEqual(rrt.resultat_du_verdict(False), "failed")
        self.assertEqual(rrt.resultat_du_verdict(None), "error")

    def test_une_valeur_vraie_non_booleenne_n_est_pas_un_succes(self):
        """Seul True passe : un message non vide n'est pas un verdict."""
        self.assertEqual(rrt.resultat_du_verdict("tour succeeded"), "error")
        self.assertEqual(rrt.resultat_du_verdict(1), "error")

    def test_les_valeurs_rendues_sont_celles_de_record_result(self):
        for ok in (True, False, None):
            self.assertIn(rrt.resultat_du_verdict(ok), rrt.RESULTATS)


def ligne(resultat, remonte=True):
    return {
        "code": "ZZ-01",
        "reference": "t",
        "resultat": resultat,
        "remonte": remonte,
    }


class TestCodeDeSortie(unittest.TestCase):
    def test_tout_passe(self):
        self.assertEqual(rrt.code_de_sortie([ligne("passed")] * 3), 0)

    def test_un_echec(self):
        lignes = [ligne("passed"), ligne("failed")]
        self.assertEqual(rrt.code_de_sortie(lignes), 1)

    def test_aucun_resultat_n_est_pas_un_vert(self):
        self.assertEqual(rrt.code_de_sortie([]), 2)

    def test_erreur_outil(self):
        self.assertEqual(
            rrt.code_de_sortie([ligne("passed")], "navigateur absent"), 2
        )

    def test_un_verdict_inconnu_l_emporte_sur_un_echec(self):
        lignes = [ligne("failed"), ligne("error")]
        self.assertEqual(rrt.code_de_sortie(lignes), 2)

    def test_un_verdict_non_remonte_est_une_erreur(self):
        self.assertEqual(rrt.code_de_sortie([ligne("passed", False)]), 2)

    def test_remontee_non_tentee_ne_compte_pas(self):
        self.assertEqual(rrt.code_de_sortie([ligne("passed", None)]), 0)


class TestTroncature(unittest.TestCase):
    def test_texte_court_intact(self):
        self.assertEqual(rrt.tronquer("FAILED: x", 100), "FAILED: x")

    def test_vide_et_none(self):
        self.assertEqual(rrt.tronquer(None, 10), "")
        self.assertEqual(rrt.tronquer("", 10), "")

    def test_borne_respectee_et_tete_gardee(self):
        texte = "FAILED: étape 3" + "x" * 50000
        for limite in (200, 1000, rrt.LIMITE_JOURNAL):
            coupe = rrt.tronquer(texte, limite)
            self.assertLessEqual(len(coupe), limite)
            self.assertTrue(coupe.startswith("FAILED: étape 3"))
            self.assertIn("tronqué", coupe)

    def test_la_marque_compte_juste(self):
        texte = "a" * 5000
        coupe = rrt.tronquer(texte, 300)
        gardes = coupe.index("\n")
        self.assertIn(f"{5000 - gardes} caractères omis", coupe)

    def test_pile_a_la_limite_n_est_pas_coupe(self):
        self.assertEqual(rrt.tronquer("b" * 50, 50), "b" * 50)

    def test_limite_plus_petite_que_la_marque(self):
        coupe = rrt.tronquer("c" * 500, 5)
        self.assertNotIn("c", coupe.split("\n")[0])


class TestToursAJouer(unittest.TestCase):
    LIGNES = [
        {"requirement_id": [2, "B"], "reference": "zz_b_tour"},
        {"requirement_id": [1, "A"], "reference": " zz_a_tour "},
        {"requirement_id": [1, "A"], "reference": "zz_a_tour"},
        {"requirement_id": [1, "A"], "reference": "zz_a_autre"},
        {"requirement_id": False, "reference": "zz_orphelin"},
    ]
    CODES = {1: "ZZ-01", 2: "ZZ-02"}

    def test_dedoublonne_et_trie(self):
        tours, manquants = rrt.tours_a_jouer(self.LIGNES, self.CODES)
        self.assertEqual(
            tours,
            [
                {"code": "", "reference": "zz_orphelin"},
                {"code": "ZZ-01", "reference": "zz_a_autre"},
                {"code": "ZZ-01", "reference": "zz_a_tour"},
                {"code": "ZZ-02", "reference": "zz_b_tour"},
            ],
        )
        self.assertEqual(manquants, [])

    def test_codes_demandes_sans_ligne(self):
        _, manquants = rrt.tours_a_jouer(
            self.LIGNES, self.CODES, ["ZZ-02", "ZZ-99"]
        )
        self.assertEqual(manquants, ["ZZ-99"])

    def test_codes_de_l_option(self):
        self.assertEqual(
            rrt.codes_demandes(["ZZ-01,ZZ-02", " ZZ-03 ", "ZZ-01", ""]),
            ["ZZ-01", "ZZ-02", "ZZ-03"],
        )
        self.assertEqual(rrt.codes_demandes(None), [])


class TestIdentifiantsRpc(unittest.TestCase):
    def test_l_environnement_l_emporte(self):
        cfg = config()
        env = {
            rrt.ENV_LOGIN_DEFAUT: "exec_tours_invente",
            rrt.ENV_PASSWORD_DEFAUT: "mdp-invente-7391",
        }
        self.assertEqual(
            rrt.identifiants_rpc(cfg, env),
            ("exec_tours_invente", "mdp-invente-7391", "environnement"),
        )

    def test_repli_sur_le_compte_navigateur(self):
        cfg = config(
            "--default_email_auth",
            "nav_invente",
            "--default_password_auth_env",
            "VAR_INVENTEE_MDP",
        )
        login, password, origine = rrt.identifiants_rpc(
            cfg, {"VAR_INVENTEE_MDP": "mdp-invente-1155"}
        )
        self.assertEqual(
            (login, password, origine),
            ("nav_invente", "mdp-invente-1155", "compte navigateur"),
        )

    def test_le_mot_de_passe_d_argv_n_est_jamais_repris(self):
        """--default_password_auth, et son défaut « admin », restent au
        navigateur : sans variable, le RPC s'arrête."""
        cfg = config("--default_password_auth", "mdp-invente-2208")
        with self.assertRaises(ValueError) as ctx:
            rrt.identifiants_rpc(cfg, {})
        self.assertIn(rrt.ENV_LOGIN_DEFAUT, str(ctx.exception))
        self.assertIn(rrt.ENV_PASSWORD_DEFAUT, str(ctx.exception))
        self.assertNotIn("mdp-invente-2208", str(ctx.exception))

    def test_une_seule_variable_nomme_la_manquante(self):
        cfg = config()
        for posee, manquante in (
            (rrt.ENV_LOGIN_DEFAUT, rrt.ENV_PASSWORD_DEFAUT),
            (rrt.ENV_PASSWORD_DEFAUT, rrt.ENV_LOGIN_DEFAUT),
        ):
            env = {posee: "valeur-inventee", "VAR_INVENTEE_MDP": "x"}
            cfg.default_password_auth_env = "VAR_INVENTEE_MDP"
            with self.assertRaises(ValueError) as ctx:
                rrt.identifiants_rpc(cfg, env)
            self.assertIn(manquante, str(ctx.exception))

    def test_noms_de_variables_configurables(self):
        cfg = config("--rpc_login_env", "L_INV", "--rpc_password_env", "P_INV")
        self.assertEqual(
            rrt.identifiants_rpc(cfg, {"L_INV": "x", "P_INV": "y"})[:2],
            ("x", "y"),
        )

    def test_aucune_option_ne_prend_un_mot_de_passe_rpc(self):
        """Le mot de passe RPC ne passe jamais par argv."""
        options = [
            o for a in parser_complet()._actions for o in a.option_strings
        ]
        rpc = [o for o in options if o.startswith("--rpc_")]
        self.assertTrue(rpc)
        self.assertTrue(all(o.endswith("_env") for o in rpc), rpc)


class TestOptions(unittest.TestCase):
    def test_defauts(self):
        cfg = config("--code", "ZZ-01,ZZ-02", "--code", "ZZ-03")
        self.assertEqual(cfg.code, ["ZZ-01", "ZZ-02", "ZZ-03"])
        self.assertEqual(cfg.start_path, "/odoo")
        self.assertEqual(cfg.step_delay, 0)
        self.assertTrue(cfg.report_json.startswith(cfg.screenshot_dir))
        self.assertIn("screencasts", cfg.screenshot_dir)
        # configure() lit config.debug avec --gecko_binary_path.
        self.assertTrue(hasattr(cfg, "debug"))

    def test_le_navigateur_suit_le_compte_executant(self):
        cfg = config(environ=ENV_EXEC)
        self.assertEqual(cfg.default_email_auth, "exec_tours_invente")
        self.assertEqual(
            cfg.default_password_auth_env, rrt.ENV_PASSWORD_DEFAUT
        )

    def test_compte_navigateur_explicite_garde(self):
        cfg = config("--default_email_auth", "nav_invente", environ=ENV_EXEC)
        self.assertEqual(cfg.default_email_auth, "nav_invente")
        self.assertIsNone(cfg.default_password_auth_env)

    def test_sans_variables_le_navigateur_garde_admin(self):
        cfg = config(environ={rrt.ENV_LOGIN_DEFAUT: "exec_tours_invente"})
        self.assertEqual(cfg.default_email_auth, "admin")
        self.assertIsNone(cfg.default_password_auth_env)

    def test_url_sans_barre_finale(self):
        self.assertEqual(
            config("--url", "http://127.0.0.1:8069/").url,
            "http://127.0.0.1:8069",
        )

    def test_nom_capture_sur(self):
        chemin = rrt.nom_capture("d", "ZZ/01", "a b;c", "20260101_000000")
        self.assertEqual(
            chemin, os.path.join("d", "ZZ_01_a_b_c_20260101_000000.png")
        )
        self.assertTrue(
            rrt.nom_capture("d", "", "", "h").endswith(
                "sans_code_sans_tour_h.png"
            )
        )


class FauxPilote:
    def __init__(self):
        self.pages = []
        self.captures = []
        self.current_url = "http://127.0.0.1:8069/odoo"
        # localStorage de la page : current_tour au moment de chaque get.
        self.stockage = {}
        self.tour_au_chargement = []

    def get(self, url):
        self.pages.append(url)
        self.tour_au_chargement.append(self.stockage.get("current_tour"))

    def save_screenshot(self, chemin):
        self.captures.append(chemin)
        return True


class FauxOutil:
    """Rend, tour par tour, le verdict prévu dans verdicts."""

    def __init__(self, verdicts):
        self.driver = FauxPilote()
        self.verdicts = verdicts
        self.joues = []
        self.onboarding = None
        self.ecritures_onboarding = []

    def odoo_read_onboarding(self):
        return self.onboarding

    def odoo_set_onboarding(self, valeur):
        self.ecritures_onboarding.append(valeur)
        return True, ""

    def odoo_clear_tour_state(self):
        self.driver.stockage.pop("current_tour", None)

    def odoo_disable_onboarding(self):
        # Comme le vrai : passe par odoo_set_onboarding, donc toute coupure
        # se voit dans ecritures_onboarding.
        self.odoo_clear_tour_state()
        return self.odoo_set_onboarding(False)

    def odoo_run_tour(self, nom, step_delay=0, timeout=180):
        self.joues.append((nom, step_delay, timeout))
        # Le tour démarre : tour_state.js écrit son nom. Un tour sans
        # verdict est un tour qui tourne encore, son état reste.
        self.driver.stockage["current_tour"] = nom
        issue = self.verdicts[nom]
        if isinstance(issue, Exception):
            raise issue
        if issue[0] is not None:
            self.driver.stockage.pop("current_tour", None)
        return issue


class FauxRpc:
    def __init__(self, reponse=True):
        self.appels = []
        self.reponse = reponse

    def remonter(self, code, reference, resultat, journal, duree):
        self.appels.append((code, reference, resultat, journal, duree))
        if isinstance(self.reponse, Exception):
            raise self.reponse
        return self.reponse


class TestJouer(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="test_tours_")
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.cfg = config(
            "--screenshot_dir", self.dossier, "--step_delay", "5"
        )

    def jouer(self, verdicts, rpc=None, tours=None):
        outil = FauxOutil(verdicts)
        rpc = rpc or FauxRpc()
        tours = tours or [
            {"code": f"ZZ-0{i}", "reference": nom}
            for i, nom in enumerate(verdicts, 1)
        ]
        with mock.patch("builtins.print"):
            resultats = rrt.jouer(self.cfg, outil, rpc, tours)
        return outil, rpc, resultats

    def test_chaque_tour_part_de_la_page_de_depart(self):
        outil, _, _ = self.jouer({"zz_a": (True, "ok"), "zz_b": (True, "ok")})
        self.assertEqual(
            outil.driver.pages, ["http://127.0.0.1:8069/odoo"] * 2
        )
        self.assertEqual(outil.joues[0], ("zz_a", 5, 180.0))

    def test_un_tour_interrompu_n_est_pas_repris_par_le_suivant(self):
        outil, _, resultats = self.jouer(
            {"zz_long": (None, "sans verdict en 180 s"), "zz_b": (True, "")}
        )
        self.assertEqual(outil.driver.tour_au_chargement, [None, None])
        self.assertEqual(
            [r["resultat"] for r in resultats], ["error", "passed"]
        )

    def test_remontee_et_capture(self):
        outil, rpc, resultats = self.jouer(
            {
                "zz_ok": (True, "réussi"),
                "zz_ko": (False, "FAILED: étape 2"),
                "zz_absent": (None, "absent du registre"),
            }
        )
        self.assertEqual(
            [r["resultat"] for r in resultats], ["passed", "failed", "error"]
        )
        self.assertEqual(
            [(a[0], a[1], a[2]) for a in rpc.appels],
            [
                ("ZZ-01", "zz_ok", "passed"),
                ("ZZ-02", "zz_ko", "failed"),
                ("ZZ-03", "zz_absent", "error"),
            ],
        )
        self.assertEqual(rpc.appels[1][3], "FAILED: étape 2")
        # Pas de capture pour un succès, une par tour non réussi.
        self.assertIsNone(resultats[0]["capture"])
        self.assertEqual(len(outil.driver.captures), 2)
        self.assertTrue(
            all(c.startswith(self.dossier) for c in outil.driver.captures)
        )
        self.assertTrue(all(r["remonte"] for r in resultats))
        self.assertEqual(rrt.code_de_sortie(resultats), 2)

    def test_journal_tronque_avant_remontee(self):
        _, rpc, resultats = self.jouer({"zz_bavard": (False, "F" * 50000)})
        self.assertLessEqual(len(rpc.appels[0][3]), rrt.LIMITE_JOURNAL)
        self.assertEqual(resultats[0]["message"], rpc.appels[0][3])

    def test_exception_du_navigateur_donne_error(self):
        _, rpc, resultats = self.jouer(
            {"zz_plante": WebDriverException("onglet fermé")}
        )
        self.assertEqual(resultats[0]["resultat"], "error")
        self.assertIn("onglet fermé", resultats[0]["message"])
        self.assertEqual(rpc.appels[0][2], "error")

    def test_record_result_faux_ou_refuse(self):
        _, _, resultats = self.jouer({"zz_a": (True, "")}, FauxRpc(False))
        self.assertIs(resultats[0]["remonte"], False)
        self.assertEqual(rrt.code_de_sortie(resultats), 2)

        refus = xmlrpc.client.Fault(1, "AccessError")
        _, _, resultats = self.jouer({"zz_a": (True, "")}, FauxRpc(refus))
        self.assertIs(resultats[0]["remonte"], False)
        self.assertEqual(rrt.code_de_sortie(resultats), 2)

    def test_reponse_non_xml_a_la_remontee_garde_les_resultats(self):
        html = xml.parsers.expat.ExpatError("syntax error: line 1")
        _, _, resultats = self.jouer(
            {"zz_a": (True, ""), "zz_b": (True, "")}, FauxRpc(html)
        )
        self.assertEqual(len(resultats), 2)
        self.assertTrue(all(r["remonte"] is False for r in resultats))
        self.assertEqual(rrt.code_de_sortie(resultats), 2)

    def test_no_record(self):
        self.cfg.no_record = True
        _, rpc, resultats = self.jouer({"zz_a": (True, "")})
        self.assertEqual(rpc.appels, [])
        self.assertIsNone(resultats[0]["remonte"])
        self.assertEqual(rrt.code_de_sortie(resultats), 0)

    def test_ligne_sans_tour_ni_code_n_est_pas_jouee(self):
        outil, rpc, resultats = self.jouer(
            {},
            tours=[
                {"code": "ZZ-01", "reference": ""},
                {"code": "", "reference": "zz_orphelin"},
            ],
        )
        self.assertEqual(outil.joues, [])
        self.assertEqual(rpc.appels, [])
        self.assertEqual([r["resultat"] for r in resultats], ["error"] * 2)


class TestRapport(unittest.TestCase):
    def test_contenu_et_absence_de_secret(self):
        cfg = config(
            "--db",
            "base_inventee",
            "--default_password_auth",
            "mdp-invente-4471",
        )
        resultats = [
            ligne("passed"),
            ligne("failed"),
            rrt.ligne_manquante("ZZ-09"),
        ]
        rapport = rrt.construire_rapport(
            cfg, "2026-01-01T00:00:00", 1.5, resultats, 2, None
        )
        self.assertEqual(rapport["totaux"]["passed"], 1)
        self.assertEqual(rapport["totaux"]["failed"], 1)
        self.assertEqual(rapport["totaux"]["error"], 1)
        self.assertEqual(rapport["code_sortie"], 2)
        self.assertEqual(rapport["db"], "base_inventee")
        texte = json.dumps(rapport)
        self.assertNotIn("mdp-invente-4471", texte)

        dossier = tempfile.mkdtemp(prefix="test_rapport_")
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        chemin = os.path.join(dossier, "sous", "rapport.json")
        rrt.ecrire_rapport(chemin, rapport)
        with open(chemin, encoding="utf-8") as fichier:
            self.assertEqual(json.load(fichier)["totaux"]["error"], 1)


class TestPreparerRpc(unittest.TestCase):
    def setUp(self):
        patcheur = mock.patch.dict(os.environ, ENV_EXEC)
        patcheur.start()
        self.addCleanup(patcheur.stop)

    def test_zero_ligne_est_une_erreur(self):
        cfg = config("--db", "base_inventee")
        with (
            mock.patch.object(rrt.Rpc, "authentifier", return_value=7),
            mock.patch.object(rrt.Rpc, "lire_tours", return_value=([], [])),
            mock.patch("builtins.print"),
        ):
            _, tours, manquants, erreur = rrt.preparer_rpc(cfg)
        self.assertEqual((tours, manquants), ([], []))
        self.assertTrue(erreur)

    def test_authentification_refusee(self):
        cfg = config("--db", "base_inventee")
        with (
            mock.patch.object(rrt.Rpc, "authentifier", return_value=False),
            mock.patch("builtins.print"),
        ):
            self.assertIn("refusée", rrt.preparer_rpc(cfg)[3])

    def test_reponse_html_est_une_erreur_d_outil(self):
        """Une page HTML servie en 200 lève ExpatError, ni
        xmlrpc.client.Error ni OSError : elle ne sort pas de preparer_rpc."""
        cfg = config("--db", "base_inventee")
        html = xml.parsers.expat.ExpatError("syntax error: line 1")
        with (
            mock.patch.object(rrt.Rpc, "authentifier", side_effect=html),
            mock.patch("builtins.print"),
        ):
            rpc, _, _, erreur = rrt.preparer_rpc(cfg)
        self.assertIsNone(rpc)
        self.assertIn("RPC impossible", erreur)
        with mock.patch.object(rrt.Rpc, "liste_bases", side_effect=html):
            self.assertIsNone(rrt.resoudre_base(config())[0])

    def test_identifiants_absents_est_une_erreur_d_outil(self):
        cfg = config("--db", "base_inventee")
        with (
            mock.patch.dict(os.environ, clear=True),
            mock.patch.object(rrt.Rpc, "authentifier") as authentifier,
        ):
            rpc, _, _, erreur = rrt.preparer_rpc(cfg)
        self.assertIsNone(rpc)
        self.assertIn(rrt.ENV_PASSWORD_DEFAUT, erreur)
        authentifier.assert_not_called()

    def test_plusieurs_bases_sans_db(self):
        cfg = config()
        with mock.patch.object(
            rrt.Rpc, "liste_bases", return_value=["a", "b"]
        ):
            base, erreur = rrt.resoudre_base(cfg)
        self.assertIsNone(base)
        self.assertIn("--db", erreur)
        with mock.patch.object(rrt.Rpc, "liste_bases", return_value=["seule"]):
            self.assertEqual(rrt.resoudre_base(cfg), ("seule", None))

    def test_lire_tours_domaine_et_codes(self):
        rpc = rrt.Rpc("http://127.0.0.1:8069", "base_inventee", "l", "p")
        appels = []

        def appel(modele, methode, args, kwargs=None):
            appels.append((modele, methode, args, kwargs))
            if methode == "search_read":
                return [{"requirement_id": [4, "X"], "reference": "zz_x"}]
            return [{"id": 4, "code": "ZZ-04"}]

        with mock.patch.object(rpc, "appel", side_effect=appel):
            tours, manquants = rpc.lire_tours(["ZZ-04"])
        self.assertEqual(tours, [{"code": "ZZ-04", "reference": "zz_x"}])
        self.assertEqual(manquants, [])
        domaine = appels[0][2][0]
        self.assertIn(("kind", "=", "tour"), domaine)
        self.assertIn(("requirement_id.code", "in", ["ZZ-04"]), domaine)

    def test_remonter_appelle_record_result(self):
        rpc = rrt.Rpc("http://127.0.0.1:8069", "base_inventee", "l", "p")
        with mock.patch.object(rpc, "appel", return_value=True) as appel:
            self.assertTrue(rpc.remonter("ZZ-01", "zz_a", "passed", "j", 1.2))
        appel.assert_called_once_with(
            "devops.requirement.test",
            "record_result",
            ["ZZ-01", "tour", "zz_a", "passed"],
            {"log": "j", "duration": 1.2},
        )


class TestPreparerSession(unittest.TestCase):
    def test_un_refus_de_connexion_arrete_sans_repli(self):
        """Les verdicts portent le nom du compte demandé : pas de repli
        sur test/test, qui jouerait les tours sous un autre compte."""
        outil = FauxOutil({})
        with mock.patch.object(
            rrt.web_login, "run", return_value=False
        ) as connexion:
            erreur = rrt.preparer_session(config(), outil)
        self.assertEqual("connexion navigateur refusée", erreur)
        self.assertTrue(connexion.call_args.kwargs["no_try_test"])

    def test_onboarding_non_coupe_est_une_erreur_d_outil(self):
        """La visite native achevée écrirait le même « tour succeeded »."""
        outil = FauxOutil({})
        outil.onboarding = True
        outil.odoo_disable_onboarding = lambda: (False, "AccessError")
        with mock.patch.object(rrt.web_login, "run"):
            erreur = rrt.preparer_session(config(), outil)
        self.assertIn("Onboarding", erreur)
        self.assertIn("AccessError", erreur)

    def test_onboarding_coupe(self):
        outil = FauxOutil({})
        outil.onboarding = True
        with mock.patch.object(rrt.web_login, "run"):
            self.assertIsNone(rrt.preparer_session(config(), outil))
        self.assertEqual(outil.ecritures_onboarding, [False])

    def test_onboarding_allume_au_depart_est_retabli(self):
        """Couper l'Onboarding écrit en base : la passe rend le compte tel
        qu'elle l'a trouvé."""
        outil = FauxOutil({})
        outil.config = config()
        outil.onboarding = True
        with mock.patch.object(rrt.web_login, "run"):
            rrt.preparer_session(config(), outil)
        rrt.restaurer_onboarding(outil)
        self.assertEqual(outil.ecritures_onboarding, [False, True])

    def test_onboarding_eteint_n_est_pas_rallume(self):
        outil = FauxOutil({})
        outil.config = config()
        outil.onboarding = False
        with mock.patch.object(rrt.web_login, "run"):
            self.assertIsNone(rrt.preparer_session(config(), outil))
        rrt.restaurer_onboarding(outil)
        self.assertEqual(outil.ecritures_onboarding, [False])

    def test_onboarding_illisible_arrete_la_passe_sans_rien_ecrire(self):
        """Coupé sans valeur d'origine, il resterait coupé pour de bon."""
        outil = FauxOutil({})
        outil.config = config()
        outil.onboarding = None
        with mock.patch.object(rrt.web_login, "run"):
            erreur = rrt.preparer_session(config(), outil)
        self.assertIn("illisible", erreur)
        rrt.restaurer_onboarding(outil)
        self.assertEqual(outil.ecritures_onboarding, [])

    def test_retablissement_en_echec_est_signale_sans_lever(self):
        outil = FauxOutil({})
        outil.config = config()
        outil.onboarding_initial = True
        outil.odoo_set_onboarding = lambda valeur: (False, "AccessError")
        with mock.patch("sys.stderr", new_callable=io.StringIO) as erreur:
            alerte = rrt.restaurer_onboarding(outil)
        self.assertIn("AccessError", alerte)
        self.assertIn("AccessError", erreur.getvalue())

    def test_retablissement_reussi_ne_rend_rien(self):
        outil = FauxOutil({})
        outil.config = config()
        outil.onboarding_initial = True
        self.assertIsNone(rrt.restaurer_onboarding(outil))


class TestFinDePasse(unittest.TestCase):
    """Ce qui rate après les verdicts va au rapport, sans changer la sortie."""

    def test_un_quit_qui_leve_devient_une_alerte(self):
        outil = mock.Mock()
        outil.quit.side_effect = RuntimeError("session distante morte")
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            alerte = rrt.fermer_navigateur(outil)
        self.assertIn("session distante morte", alerte)

    def test_un_quit_reussi_ne_rend_rien(self):
        self.assertIsNone(rrt.fermer_navigateur(mock.Mock()))

    def test_les_alertes_sont_au_rapport_sans_changer_la_sortie(self):
        resultats = [{"resultat": "passed"}]
        rapport = rrt.construire_rapport(
            config(),
            "2026-01-01T00:00:00",
            1.0,
            resultats,
            rrt.code_de_sortie(resultats, None),
            None,
            ["Onboarding non rétabli"],
        )
        self.assertEqual(rapport["alertes"], ["Onboarding non rétabli"])
        self.assertEqual(rapport["code_sortie"], 0)


class TestParser(unittest.TestCase):
    def test_une_abreviation_est_refusee(self):
        """Un script qui réserve --code ne doit pas se voir contourner
        par --cod, qu'argparse développerait par défaut."""
        with (
            mock.patch("sys.stderr", new_callable=io.StringIO),
            self.assertRaises(SystemExit) as sortie,
        ):
            rrt.construire_parser().parse_args(["--cod", "ZZ-01"])
        self.assertEqual(sortie.exception.code, 2)

    def test_le_nom_complet_passe(self):
        args = rrt.construire_parser().parse_args(["--code", "ZZ-01"])
        self.assertEqual(args.code, ["ZZ-01"])


class PiloteDeTour:
    """Simule la page : rend un relevé par appel, dans l'ordre donné."""

    def __init__(self, sonde, releves):
        self.sonde = sonde
        self.releves = list(releves)
        self.scripts = []
        self.appels = []
        self.pages = []

    def get(self, url):
        self.pages.append(url)

    def execute_script(self, script, *args):
        self.scripts.append(script)
        self.appels.append((script, args))
        if script is selenium_lib._JS_TOUR_SONDE:
            return self.sonde
        if script is selenium_lib._JS_TOUR_RELEVE:
            issue = self.releves.pop(0)
            if isinstance(issue, Exception):
                raise issue
            return issue
        if "pathname" in script:
            return "/odoo"
        return True


def outil_de_tour(sonde, releves):
    outil = selenium_lib.SeleniumLib.__new__(selenium_lib.SeleniumLib)
    outil.driver = PiloteDeTour(sonde, releves)
    outil.config = SimpleNamespace(url="http://127.0.0.1:8069/")
    return outil


def options_de_demarrage(outil):
    """Les options passées à odoo.startTour."""
    for script, args in outil.driver.appels:
        if script is selenium_lib._JS_TOUR_DEMARRE:
            return args[2]
    raise AssertionError("tour non démarré")


PRET = {"etape": "pret", "connu": True}
EN_COURS = {
    "crochet": True,
    "lance": True,
    "verdict": None,
    "courant": "zz_tour",
    "index": "1",
}


class TestCrochetPermanent(unittest.TestCase):
    """L'enveloppe de la console se précharge une fois par pilote BiDi."""

    def outil(self, bidi=True, websocket="ws://essai.invalid/session"):
        outil = selenium_lib.SeleniumLib.__new__(selenium_lib.SeleniumLib)
        outil.bidi = bidi
        outil.driver = mock.Mock()
        outil.driver.capabilities = {"webSocketUrl": websocket}
        return outil

    def test_pose_une_fois_un_script_qui_porte_l_enveloppe(self):
        outil = self.outil()
        self.assertTrue(outil.odoo_pose_crochet_permanent())
        self.assertTrue(outil.odoo_pose_crochet_permanent())
        appel = outil.driver.script.add_preload_script
        appel.assert_called_once()
        script = appel.call_args.args[0]
        self.assertIn("__erplibre_tour_crochet", script)
        self.assertIn(json.dumps(selenium_lib._TOUR_CLE), script)

    def test_sans_bidi_rien_n_est_pose(self):
        for outil in (self.outil(bidi=False), self.outil(websocket=None)):
            self.assertFalse(outil.odoo_pose_crochet_permanent())
            outil.driver.script.add_preload_script.assert_not_called()

    def test_un_refus_du_navigateur_retombe_sur_la_reinjection(self):
        outil = self.outil()
        outil.driver.script.add_preload_script.side_effect = RuntimeError(
            "non"
        )
        with mock.patch("builtins.print"):
            self.assertFalse(outil.odoo_pose_crochet_permanent())


class TestOdooRunTour(unittest.TestCase):
    def setUp(self):
        patcheur = mock.patch.object(selenium_lib.time, "sleep")
        patcheur.start()
        self.addCleanup(patcheur.stop)

    def test_succes(self):
        outil = outil_de_tour(
            PRET, [EN_COURS, dict(EN_COURS, verdict="succes")]
        )
        ok, message = outil.odoo_run_tour("zz_tour")
        self.assertIs(ok, True)
        self.assertIn("réussi", message)

    def test_un_tour_avec_url_demarre_sur_son_url_sans_redirection(self):
        """Comme HttpCase.start_tour : l'url est chargée, puis donnée en
        startUrl. Lue sur la page, elle différerait (/odoo devient
        /odoo/action-<id>) et Odoo rechargerait la page pendant le tour."""
        sonde = dict(PRET, url="/odoo")
        outil = outil_de_tour(sonde, [dict(EN_COURS, verdict="succes")])
        ok, _ = outil.odoo_run_tour("zz_tour")
        self.assertIs(ok, True)
        self.assertEqual(outil.driver.pages, ["http://127.0.0.1:8069/odoo"])
        self.assertEqual(options_de_demarrage(outil)["startUrl"], "/odoo")

    def test_un_tour_sans_url_part_de_la_page_courante(self):
        outil = outil_de_tour(PRET, [dict(EN_COURS, verdict="succes")])
        outil.odoo_run_tour("zz_tour")
        self.assertEqual(outil.driver.pages, [])
        self.assertEqual(options_de_demarrage(outil)["startUrl"], "/odoo")

    def test_url_absolue(self):
        outil = outil_de_tour(PRET, [])
        self.assertEqual(
            outil._url_absolue("/my/account"),
            "http://127.0.0.1:8069/my/account",
        )
        self.assertEqual(
            outil._url_absolue("https://autre.example/x"),
            "https://autre.example/x",
        )

    def test_succes_avec_console_error_est_un_echec(self):
        """HttpCase fait échouer le tour au premier console.error."""
        releve = dict(
            EN_COURS, verdict="succes", erreurs=["Uncaught TypeError: x"]
        )
        ok, message = outil_de_tour(PRET, [releve]).odoo_run_tour("zz_tour")
        self.assertIs(ok, False)
        self.assertIn("1 console.error", message)
        self.assertIn("Uncaught TypeError: x", message)

    def test_echec_porte_l_etape_et_les_erreurs(self):
        releve = dict(
            EN_COURS,
            verdict="echec",
            message="FAILED: [3/5] Tour zz_tour → Step x",
            details="---- FAILED ----",
            erreurs=["owl: autre erreur"],
        )
        ok, message = outil_de_tour(PRET, [releve]).odoo_run_tour("zz_tour")
        self.assertIs(ok, False)
        self.assertTrue(message.startswith("FAILED: [3/5]"))
        self.assertIn("---- FAILED ----", message)
        self.assertIn("owl: autre erreur", message)

    def test_tour_absent_du_registre(self):
        outil = outil_de_tour({"etape": "pret", "connu": False}, [])
        ok, message = outil.odoo_run_tour("zz_tour")
        self.assertIsNone(ok)
        self.assertIn("absent du registre", message)
        self.assertIn("web.assets_tests", message)
        # Aucun démarrage tenté.
        self.assertNotIn(selenium_lib._JS_TOUR_DEMARRE, outil.driver.scripts)

    def test_page_de_connexion(self):
        ok, message = outil_de_tour({"etape": "connexion"}, []).odoo_run_tour(
            "zz_tour"
        )
        self.assertIsNone(ok)
        self.assertIn("connexion", message)

    def test_rechargement_reinjecte_l_enveloppe(self):
        releves = [
            WebDriverException("document unloaded"),
            dict(EN_COURS, crochet=False),
            dict(EN_COURS, verdict="succes"),
        ]
        outil = outil_de_tour(PRET, releves)
        ok, _ = outil.odoo_run_tour("zz_tour")
        self.assertIs(ok, True)
        crochets = [
            s
            for s in outil.driver.scripts
            if s is selenium_lib._JS_TOUR_CROCHET
        ]
        self.assertEqual(len(crochets), 2)
        # La remise à zéro ne se fait qu'au démarrage, jamais à la
        # réinjection : elle effacerait un verdict déjà écrit.
        razs = [
            s for s in outil.driver.scripts if s is selenium_lib._JS_TOUR_RAZ
        ]
        self.assertEqual(len(razs), 1)

    def test_tour_fini_sans_verdict_lisible(self):
        releve = dict(EN_COURS, courant=None)
        ok, message = outil_de_tour(PRET, [releve]).odoo_run_tour("zz_tour")
        self.assertIsNone(ok)
        self.assertIn("sans verdict lisible", message)

    def test_delai_depasse(self):
        horloge = iter([0, 0, 0, 1000, 1000])
        outil = outil_de_tour(PRET, [EN_COURS] * 5)
        with mock.patch.object(
            selenium_lib.time, "time", side_effect=lambda: next(horloge)
        ):
            ok, message = outil.odoo_run_tour("zz_tour", timeout=10)
        self.assertIsNone(ok)
        self.assertIn("sans verdict en 10 s", message)
        # Le tour tourne encore : son état ne doit pas être repris.
        self.assertIn(selenium_lib._JS_TOUR_ETAT_EFFACE, outil.driver.scripts)

    def test_erreur_au_demarrage(self):
        releve = dict(EN_COURS, verdict="erreur", message="schéma invalide")
        ok, message = outil_de_tour(PRET, [releve]).odoo_run_tour("zz_tour")
        self.assertIsNone(ok)
        self.assertIn("schéma invalide", message)


class TestSignauxDOdoo(unittest.TestCase):
    """L'enveloppe guette des chaînes qu'Odoo écrit : elles ne doivent pas
    dériver sans qu'un test le dise."""

    def test_chaines_guettees_presentes_dans_odoo(self):
        if not os.path.isfile(TOUR_AUTOMATIC):
            self.skipTest("sources Odoo 18 absentes")
        with open(TOUR_AUTOMATIC, encoding="utf-8") as fichier:
            source = fichier.read()
        self.assertIn('browser.console.log("tour succeeded")', source)
        self.assertIn("browser.console.error([`FAILED:", source)
        self.assertIn("browser.console.dir(this.describeWhereIFailed)", source)
        # Égalité stricte, comme HttpCase : une description d'étape qui
        # contient la phrase n'est pas un succès.
        self.assertIn(
            'args.length === 1 && args[0] === "tour succeeded"',
            selenium_lib._JS_TOUR_CROCHET,
        )
        self.assertNotIn("includes(", selenium_lib._JS_TOUR_CROCHET)
        self.assertIn('startsWith("FAILED")', selenium_lib._JS_TOUR_CROCHET)

    def test_cles_de_tour_state(self):
        etat = TOUR_AUTOMATIC.replace("tour_automatic.js", "tour_state.js")
        if not os.path.isfile(etat):
            self.skipTest("sources Odoo 18 absentes")
        with open(etat, encoding="utf-8") as fichier:
            source = fichier.read()
        for cle in ('"current_tour"', '"current_tour.index"'):
            self.assertIn(cle, source)
            self.assertIn(cle, selenium_lib._JS_TOUR_RELEVE)
        # L'effacement couvre toutes les clés que tourState.clear() retire.
        for cle in (
            '"current_tour"',
            '"current_tour.config"',
            '"current_tour.index"',
            '"current_tour.on_error"',
        ):
            self.assertIn(cle, source)
            self.assertIn(cle, selenium_lib._JS_TOUR_ETAT_EFFACE)


if __name__ == "__main__":
    unittest.main()
