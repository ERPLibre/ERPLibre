#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La vérification de santé : des verdicts justes, sans faux échec.

Les verdicts sont épinglés sur des fonctions pures (réponses fabriquées,
dates de certificat, sorties de dig et de host) ; le parcours entier sur
un faux Odoo HTTP local (`fake_odoo_http`), sur 127.0.0.1. Le TLS ne
contacte aucun serveur : le connecteur est remplacé. Le DNS passe par un
lanceur remplacé : ni dig ni host ne sont lancés. Les noms d'hôte sont
inventés (example.org, example.net).
"""

import contextlib
import io
import json
import os
import ssl
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest import mock

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "test"))

from fake_odoo_http import FauxOdoo  # noqa: E402

from script.odoo import health_check as hc  # noqa: E402

MAINTENANT = hc.epoque_expiration("Jan  1 00:00:00 2030 GMT")
VERSION_18 = (
    200,
    {"Content-Type": "application/json"},
    '{"jsonrpc": "2.0", "id": 1, "result": {"server_version_info":'
    ' [18, 0, 0, "final", 0, ""]}}',
)
DESACTIVE = (
    '<div class="o_database_list"><div class="alert">'
    "The database manager has been disabled by the administrator</div>"
)
FORMULAIRE = (
    '<div class="o_database_list"><form action="/web/database/backup">'
    '<input name="master_pwd"/></form>'
)


def dig(*enregistrements, statut="NOERROR", nom="example.org."):
    """La sortie de `dig +noall +comments +answer TXT nom` : l'en-tête
    porte le statut, la section réponse un TXT par donnée."""
    lignes = [
        ";; Got answer:",
        f";; ->>HEADER<<- opcode: QUERY, status: {statut}, id: 4242",
        f";; flags: qr rd ra; QUERY: 1, ANSWER: {len(enregistrements)},"
        " AUTHORITY: 0, ADDITIONAL: 0",
        "",
    ]
    if enregistrements:
        lignes.append(";; ANSWER SECTION:")
        lignes += [f"{nom}\t\t300\tIN\tTXT\t{e}" for e in enregistrements]
    return 0, "\n".join(lignes) + "\n\n"


def rep(statut=200, corps="", erreur="", **entetes):
    return hc.Reponse(
        statut,
        {k.replace("_", "-"): v for k, v in entetes.items()},
        corps,
        erreur,
    )


class FauxSysteme(hc.Systeme):
    """Binaires, DNS, TLS, horloges et systemctl de théâtre ; HTTP réel
    vers le faux Odoo, ou réponses servies par `reponses`."""

    def __init__(self):
        super().__init__()
        self.binaires = {"dig"}
        self.dns = {}
        self.appels = []
        self.cert = {"notAfter": "Jun  1 00:00:00 2030 GMT"}
        self.der = None
        self.instant = MAINTENANT
        self.horloges = []
        self.reponses = None
        self.wd = ""
        self.unite = "erplibre_demo.service"

    def quel(self, nom):
        return f"/usr/bin/{nom}" if nom in self.binaires else None

    def lanceur(self, argv, timeout=60):
        self.appels.append(list(argv))
        if argv[0] == "dig":
            return self.dns.get(argv[-1], dig())
        if argv[0] == "host":
            return self.dns.get(argv[-1], (0, ""))
        if argv[:2] == ["systemctl", "show"]:
            return 0, (
                "LoadState=loaded\nActiveState=active\nUser=demo\n"
                f"WorkingDirectory={self.wd}\n"
                "ExecStart={ path=/bin/bash ; argv[]=/bin/bash"
                f" {self.wd}/run.sh ; ignore_errors=no }}\n"
                "Environment=\n"
            )
        return 1, "commande inattendue"

    def certificat(self, hote, port, delai):
        self.appels.append(["tls", hote, port])
        if isinstance(self.cert, Exception):
            raise self.cert
        return self.cert

    def certificat_brut(self, hote, port, delai):
        return self.der

    def maintenant(self):
        return self.instant

    def horloge(self):
        return self.horloges.pop(0) if self.horloges else 0.0

    def ouvrir(self, url, delai, donnees=None, entetes=None):
        if self.reponses is None:
            return super().ouvrir(url, delai, donnees, entetes)
        self.appels.append(["http", url])
        return self.reponses.get(url, rep(404))


def refus_tls(code, message):
    erreur = ssl.SSLCertVerificationError(1, "certificate verify failed")
    erreur.verify_code = code
    erreur.verify_message = message
    return erreur


class TestTls(unittest.TestCase):
    def test_jours_restants(self):
        fin = hc.epoque_expiration("Jun  1 00:00:00 2030 GMT")
        self.assertEqual(hc.jours_restants(fin, MAINTENANT), 151)
        self.assertEqual(hc.jours_restants(fin, fin + 3600), -1)
        self.assertEqual(hc.jours_restants(fin, fin - 3600), 0)

    def test_bornes_de_l_expiration(self):
        for jours, attendu in (
            (21, hc.OK),
            (20, hc.ATTN),
            (7, hc.ATTN),
            (6, hc.FAIL),
            (0, hc.FAIL),
            (-1, hc.FAIL),
        ):
            with self.subTest(jours=jours):
                self.assertEqual(hc.classer_expiration(jours), attendu)

    def test_cause_d_un_refus(self):
        for code, mot in (
            (62, "host name"),
            (10, "expired"),
            (18, "self-signed"),
            (19, "self-signed"),
            (20, "unknown issuer"),
        ):
            with self.subTest(code=code):
                self.assertIn(mot, hc.classer_erreur_tls(code, "x"))
        self.assertIn("{reason}", hc.classer_erreur_tls(99, "x"))

    def test_date_d_un_der(self):
        der = (
            b"\x30\x82\x01\x00junk\x17\x0d250101000000Z"
            b"\x17\x0d300601000000Z\xa3extensions"
        )
        self.assertEqual(
            hc.fin_validite_der(der),
            hc.epoque_expiration("Jun  1 00:00:00 2030 GMT"),
        )
        long_ = b"\x18\x0f20250101000000Z\x18\x0f20500101000000Z"
        self.assertEqual(
            hc.fin_validite_der(long_),
            hc.epoque_expiration("Jan  1 00:00:00 2050 GMT"),
        )
        self.assertIsNone(hc.fin_validite_der(b"\x17\x0d250101000000Z"))
        self.assertIsNone(hc.fin_validite_der(None))

    def cible(self):
        return hc.normaliser_url("https://www.example.org")

    def test_certificat_valide(self):
        systeme = FauxSysteme()
        resultat = hc.verifier_tls(self.cible(), systeme, 5)
        self.assertEqual(resultat.statut, hc.OK)
        self.assertEqual(resultat.donnees["days_left"], 151)
        self.assertIn(["tls", "www.example.org", 443], systeme.appels)

    def test_certificat_bientot_expire(self):
        systeme = FauxSysteme()
        systeme.cert = {"notAfter": "Jan 11 00:00:00 2030 GMT"}
        resultat = hc.verifier_tls(self.cible(), systeme, 5)
        self.assertEqual(resultat.statut, hc.ATTN)
        self.assertIn("10", resultat.message())
        systeme.cert = {"notAfter": "Dec 30 00:00:00 2029 GMT"}
        resultat = hc.verifier_tls(self.cible(), systeme, 5)
        self.assertEqual(resultat.statut, hc.FAIL)
        self.assertIn("expired", resultat.message())

    def test_certificat_refuse_date_lue_sans_openssl(self):
        systeme = FauxSysteme()
        systeme.binaires = set()
        systeme.cert = refus_tls(62, "Hostname mismatch")
        systeme.der = b"\x17\x0d250101000000Z\x17\x0d300601000000Z"
        resultat = hc.verifier_tls(self.cible(), systeme, 5)
        self.assertEqual(resultat.statut, hc.FAIL)
        self.assertIn("host name", resultat.message())
        self.assertEqual(resultat.donnees["not_after"], "2030-06-01")
        self.assertIn("www.example.org", resultat.conseil())

    def test_certificat_refuse_sans_date(self):
        systeme = FauxSysteme()
        systeme.cert = refus_tls(20, "unable to get local issuer")
        systeme.der = b""
        resultat = hc.verifier_tls(self.cible(), systeme, 5)
        self.assertEqual(resultat.statut, hc.FAIL)
        self.assertNotIn("not_after", resultat.donnees)

    def test_date_illisible(self):
        systeme = FauxSysteme()
        for cert in ({}, {"notAfter": "bientôt"}):
            with self.subTest(cert=cert):
                systeme.cert = cert
                resultat = hc.verifier_tls(self.cible(), systeme, 5)
                self.assertEqual(resultat.statut, hc.ATTN)
                self.assertIn("unreadable", resultat.message())

    def test_connexion_impossible(self):
        systeme = FauxSysteme()
        systeme.cert = ConnectionRefusedError(111, "Connection refused")
        resultat = hc.verifier_tls(self.cible(), systeme, 5)
        self.assertEqual(resultat.statut, hc.FAIL)
        self.assertIn("443", resultat.conseil())


class TestRedirectionEtHsts(unittest.TestCase):
    def test_redirection(self):
        hote = "www.example.org"
        for reponse, attendu in (
            (rep(301, location="https://www.example.org/x"), hc.OK),
            (rep(308, location="https://www.example.org/"), hc.OK),
            (rep(301, location="https://other.example.net/"), hc.ATTN),
            (rep(302, location="http://www.example.org/"), hc.ATTN),
            (rep(200), hc.FAIL),
            (rep(0, erreur="Connection refused"), hc.ATTN),
            (rep(404), hc.ATTN),
        ):
            with self.subTest(statut=reponse.statut, loc=reponse.entetes):
                resultat = hc.classer_redirection(reponse, hote)
                self.assertEqual(resultat.statut, attendu)
                resultat.conseil()

    def test_hsts(self):
        self.assertEqual(hc.classer_hsts("").statut, hc.ATTN)
        self.assertEqual(hc.classer_hsts("max-age=300").statut, hc.ATTN)
        self.assertEqual(
            hc.classer_hsts("max-age=31536000; includeSubDomains").statut,
            hc.OK,
        )


class TestGestionnaireDeBases(unittest.TestCase):
    def test_pages(self):
        for reponse, page, publique, attendu in (
            (rep(200, DESACTIVE), "manager", True, hc.OK),
            (rep(200, FORMULAIRE), "manager", True, hc.FAIL),
            (rep(200, FORMULAIRE), "manager", False, hc.ATTN),
            (
                rep(200, "your Odoo database manager is not protected"),
                "manager",
                True,
                hc.FAIL,
            ),
            (rep(403), "manager", True, hc.OK),
            (rep(404), "manager", True, hc.OK),
            (rep(303, location="/web/login"), "manager", True, hc.OK),
            (rep(500), "manager", True, hc.ATTN),
            (rep(0, erreur="timeout"), "manager", True, hc.ATTN),
            (rep(200, FORMULAIRE), "selector", True, hc.ATTN),
            (rep(200, DESACTIVE), "selector", True, hc.OK),
            (rep(200, "<html>a website page</html>"), "manager", True, hc.OK),
        ):
            with self.subTest(page=page, statut=reponse.statut):
                resultat = hc.classer_gestionnaire(reponse, page, publique)
                self.assertEqual(resultat.statut, attendu)
                self.assertEqual(
                    resultat.ident,
                    "db_manager" if page == "manager" else "db_selector",
                )

    def test_list_db(self):
        self.assertEqual(hc.classer_list_db(None).statut, hc.ATTN)
        self.assertEqual(hc.classer_list_db("False").statut, hc.OK)
        self.assertEqual(hc.classer_list_db("True").statut, hc.ATTN)
        self.assertIn("True by default", hc.classer_list_db("").message())

    def test_list_db_absent_traduit_en_entier(self):
        """Absent, le message a son propre modèle : aucun fragment anglais
        ne passe par une valeur dans la phrase traduite."""
        from script.todo import todo_i18n

        resultat = hc.classer_list_db(None)
        self.assertEqual(resultat.valeurs["value"], "")
        self.assertIsNone(resultat.json()["data"]["value"])
        francais = todo_i18n.TRANSLATIONS[resultat.modele]["fr"]
        self.assertEqual(resultat.message(lambda cle: francais), francais)
        self.assertNotIn("default", francais)
        self.assertIn("True", hc.classer_list_db("True").message())


class TestBus(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(hc.classer_bus(rep(400), "/websocket").statut, hc.OK)
        self.assertEqual(hc.classer_bus(rep(426), "/websocket").statut, hc.OK)
        self.assertEqual(
            hc.classer_bus(rep(404), "/websocket").statut, hc.ATTN
        )
        self.assertEqual(
            hc.classer_bus(rep(502), "/websocket").statut, hc.FAIL
        )

    def test_chemin_selon_la_version(self):
        self.assertEqual(hc.chemin_bus(15), "/longpolling/poll")
        self.assertEqual(hc.chemin_bus(12), "/longpolling/poll")
        self.assertEqual(hc.chemin_bus(16), "/websocket")
        self.assertEqual(hc.chemin_bus(None), "/websocket")

    def test_version_inconnue_essaie_l_autre_chemin(self):
        systeme = FauxSysteme()
        cible = hc.normaliser_url("https://www.example.org")
        systeme.reponses = {
            "https://www.example.org/websocket": rep(404),
            "https://www.example.org/longpolling/poll": rep(200),
        }
        resultat = hc.verifier_bus(cible, systeme, 5)
        self.assertEqual(resultat.statut, hc.OK)
        self.assertEqual(resultat.donnees["path"], "/longpolling/poll")
        cible.version = 15
        systeme.appels = []
        hc.verifier_bus(cible, systeme, 5)
        self.assertEqual(
            systeme.appels,
            [["http", "https://www.example.org/longpolling/poll"]],
        )


class TestRobots(unittest.TestCase):
    def test_verdicts(self):
        site = "User-agent: *\nSitemap: https://www.example.org/sitemap.xml"
        self.assertEqual(hc.classer_robots(rep(200, site)).statut, hc.OK)
        # Le gabarit de website quand l'URL n'est pas le domaine du site.
        decale = (
            "User-agent: *\nDisallow: /\n"
            "Sitemap: https://www.example.org/sitemap.xml\n"
        )
        self.assertEqual(hc.classer_robots(rep(200, decale)).statut, hc.ATTN)
        odoo18 = "User-agent: *\nDisallow: /\nAllow: /web/"
        resultat = hc.classer_robots(rep(200, odoo18))
        self.assertEqual(resultat.statut, hc.OK)
        self.assertIn("no public website", resultat.message())
        self.assertEqual(hc.classer_robots(rep(404)).statut, hc.SKIP)
        self.assertEqual(hc.classer_robots(rep(500)).statut, hc.ATTN)
        partiel = "User-agent: *\nDisallow: /web/\nSitemap: /sitemap.xml"
        self.assertEqual(hc.classer_robots(rep(200, partiel)).statut, hc.OK)

    def test_le_sitemap_n_est_pas_demande(self):
        with FauxOdoo(routes_saines()) as serveur:
            hc.verifier_cible(hc.normaliser_url(serveur.url), FauxSysteme(), 5)
            chemins = serveur.chemins()
        self.assertIn("/robots.txt", chemins)
        self.assertNotIn("/sitemap.xml", chemins)


class TestSante(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(
            hc.classer_sante(rep(200, '{"status": "pass"}')).statut, hc.OK
        )
        self.assertEqual(
            hc.classer_sante(rep(500, '{"status": "fail"}')).statut, hc.FAIL
        )
        self.assertEqual(hc.classer_sante(rep(404)).statut, hc.SKIP)
        self.assertEqual(
            hc.classer_sante(rep(0, erreur="Connection refused")).statut,
            hc.FAIL,
        )
        self.assertEqual(hc.classer_sante(rep(200, "<html>")).statut, hc.ATTN)


class TestPageDeConnexion(unittest.TestCase):
    def cible(self, url="https://www.example.org"):
        return hc.normaliser_url(url)

    def verifier(self, reponses, horloges=(0.0, 0.2), url=None):
        systeme = FauxSysteme()
        systeme.reponses = reponses
        systeme.horloges = list(horloges)
        cible = self.cible(url or "https://www.example.org")
        resultats = hc.verifier_cible(cible, systeme, 5)
        self.systeme = systeme
        return {r.ident: r for r in resultats}

    def test_la_redirection_https_sonde_le_port_80_du_meme_hote(self):
        r = self.verifier(
            {
                "https://www.example.org/web/login": rep(200),
                "http://www.example.org/": rep(
                    301, location="https://www.example.org/"
                ),
            }
        )
        self.assertEqual(r["http_redirect"].statut, hc.OK)
        self.assertIn(["http", "http://www.example.org/"], self.systeme.appels)
        r = self.verifier(
            {
                "https://www.example.org:8443/web/login": rep(200),
                "http://www.example.org/": rep(
                    301, location="https://www.example.org:8443/"
                ),
            },
            url="https://www.example.org:8443",
        )
        self.assertEqual(r["http_redirect"].statut, hc.OK)

    def test_un_refus_de_la_page_de_connexion_est_un_fail(self):
        for statut in (403, 404):
            with self.subTest(statut=statut):
                resultat = hc.classer_login(rep(statut), "", "", 0.1)
                self.assertEqual(resultat.statut, hc.FAIL)

    def test_200_avec_la_duree(self):
        r = self.verifier({"https://www.example.org/web/login": rep(200)})
        self.assertEqual(r["http_login"].statut, hc.OK)
        self.assertEqual(r["http_login"].donnees["seconds"], 0.2)
        self.assertIn("0.20", r["http_login"].message())

    def test_lente(self):
        r = self.verifier(
            {"https://www.example.org/web/login": rep(200)}, (0.0, 6.0)
        )
        self.assertEqual(r["http_login"].statut, hc.ATTN)

    def test_selecteur_de_bases(self):
        r = self.verifier(
            {
                "https://www.example.org/web/login": rep(
                    303, location="/web/database/selector"
                )
            }
        )
        self.assertEqual(r["http_login"].statut, hc.ATTN)
        self.assertIn("selector", r["http_login"].message())

    def test_retour_au_clair(self):
        r = self.verifier(
            {
                "https://www.example.org/web/login": rep(
                    303, location="http://www.example.org/odoo"
                )
            }
        )
        self.assertEqual(r["http_login"].statut, hc.ATTN)
        self.assertIn("proxy_mode", r["http_login"].conseil())

    def test_redirection_suivie_sur_le_meme_hote(self):
        r = self.verifier(
            {
                "https://www.example.org/web/login": rep(
                    303, location="/fr/web/login"
                ),
                "https://www.example.org/fr/web/login": rep(
                    200, strict_transport_security="max-age=31536000"
                ),
            }
        )
        self.assertEqual(r["http_login"].statut, hc.OK)
        self.assertEqual(r["hsts"].statut, hc.OK)

    def test_502_et_refus(self):
        r = self.verifier({"https://www.example.org/web/login": rep(502)})
        self.assertEqual(r["http_login"].statut, hc.FAIL)
        self.assertEqual(r["hsts"].statut, hc.SKIP)
        r = self.verifier(
            {"https://www.example.org/web/login": rep(0, erreur="refused")}
        )
        self.assertEqual(r["http_login"].statut, hc.FAIL)

    def test_delai_borne(self):
        def lent(_requete):
            time.sleep(1.5)
            return 200, {}, "tard"

        with FauxOdoo({"/web/login": lent}) as serveur:
            debut = time.monotonic()
            reponse = hc.ouvrir_http(serveur.url + "/web/login", 0.3)
            self.assertLess(time.monotonic() - debut, 1.2)
        self.assertEqual(reponse.statut, 0)
        self.assertEqual(
            hc.classer_login(reponse, "", "", 0.3).statut, hc.FAIL
        )


class TestOuvrirHttp(unittest.TestCase):
    """`ouvrir_http` sur de vraies sockets : aucune redirection suivie,
    aucun proxy de l'environnement, aucun cookie gardé. Un second faux
    serveur, nommé `localhost`, tient lieu d'« autre hôte » : une
    redirection suivie par erreur y arriverait, sans quitter la machine."""

    def test_une_redirection_est_rendue_telle_quelle(self):
        with FauxOdoo() as autre:
            ailleurs = f"http://localhost:{autre.port}/"
            routes = {"/": (301, {"Location": ailleurs}, "")}
            with FauxOdoo(routes) as serveur:
                reponse = hc.ouvrir_http(serveur.url + "/", 5)
                requetes = serveur.requetes
            self.assertEqual(autre.requetes, [])
        self.assertEqual(reponse.statut, 301)
        self.assertEqual(reponse.entete("location"), ailleurs)
        self.assertEqual(len(requetes), 1)

    def test_une_redirection_vers_un_autre_hote_n_est_pas_suivie(self):
        with FauxOdoo() as autre:
            ailleurs = f"http://localhost:{autre.port}/web/login"
            routes = routes_saines()
            routes["/web/login"] = (303, {"Location": ailleurs}, "")
            with FauxOdoo(routes) as serveur:
                cible = hc.normaliser_url(serveur.url)
                resultats = hc.verifier_cible(cible, FauxSysteme(), 5)
                chemins = serveur.chemins()
            self.assertEqual(autre.requetes, [])
        login = {r.ident: r for r in resultats}["http_login"]
        self.assertEqual(login.statut, hc.ATTN)
        self.assertEqual(login.donnees["url"], ailleurs)
        self.assertIn("redirects to", login.message())
        self.assertEqual(chemins.count("/web/login"), 1)

    def test_trop_de_redirections(self):
        routes = {
            "/web/login": (303, {"Location": "/r1"}, ""),
            "/r1": (303, {"Location": "/r2"}, ""),
            "/r2": (303, {"Location": "/r3"}, ""),
            "/r3": (303, {"Location": "/r4"}, ""),
            "/r4": (200, {}, "fin"),
        }
        with FauxOdoo(routes) as serveur:
            cible = hc.normaliser_url(serveur.url)
            reponse, finale, raison = hc.suivre(
                serveur.url + "/web/login", cible, FauxSysteme(), 5
            )
            chemins = serveur.chemins()
        self.assertEqual(raison, "too_many")
        self.assertEqual(reponse.statut, 303)
        self.assertEqual(chemins, ["/web/login", "/r1", "/r2", "/r3"])
        resultat = hc.classer_login(reponse, finale, raison, 0.1)
        self.assertEqual(resultat.statut, hc.ATTN)

    def test_le_proxy_de_l_environnement_est_ignore(self):
        variables = {
            "http_proxy": "http://127.0.0.1:9",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "no_proxy": "",
            "NO_PROXY": "",
        }
        with FauxOdoo({"/web/login": (200, {}, "ok")}) as serveur:
            with mock.patch.dict(os.environ, variables):
                reponse = hc.ouvrir_http(serveur.url + "/web/login", 5)
            requetes = serveur.requetes
        self.assertEqual(reponse.statut, 200)
        self.assertEqual(len(requetes), 1)

    def test_aucun_cookie_n_est_garde(self):
        """Chaque requête a son propre ouvreur : sans HTTPCookieProcessor,
        un Set-Cookie ne revient jamais."""
        vrai = urllib.request.build_opener
        gestionnaires = []

        def espion(*args):
            gestionnaires.extend(args)
            return vrai(*args)

        routes = {"/web/login": (200, {"Set-Cookie": "s=1; Path=/"}, "ok")}
        with FauxOdoo(routes) as serveur:
            with mock.patch.object(urllib.request, "build_opener", espion):
                hc.ouvrir_http(serveur.url + "/web/login", 5)
                hc.ouvrir_http(serveur.url + "/web/login", 5)
            requetes = serveur.requetes
        self.assertTrue(gestionnaires)
        for gestionnaire in gestionnaires:
            self.assertNotIsInstance(
                gestionnaire, urllib.request.HTTPCookieProcessor
            )
        self.assertNotIn("cookie", requetes[1].entetes)


class TestDns(unittest.TestCase):
    def verifier(self, zone, selecteur=None, binaires=("dig",)):
        systeme = FauxSysteme()
        systeme.binaires = set(binaires)
        systeme.dns = zone
        resultats = hc.verifier_courriel("example.org", selecteur, systeme, 5)
        return {r.ident: r for r in resultats}, systeme

    def test_spf(self):
        for sortie, attendu in (
            (dig('"v=spf1 mx -all"'), hc.OK),
            (dig('"v=spf1 mx ~all"'), hc.OK),
            (dig('"v=spf1 mx -all"', '"v=spf1 a -all"'), hc.FAIL),
            (dig('"google-site-verification=abc"'), hc.FAIL),
            (dig('"v=spf1 +all"'), hc.FAIL),
            (dig('"v=spf1 mx ?all"'), hc.ATTN),
            (dig(statut="NXDOMAIN"), hc.FAIL),
        ):
            with self.subTest(sortie=sortie):
                r, _ = self.verifier({"example.org": sortie})
                self.assertEqual(r["mail_spf"].statut, attendu)

    def test_txt_en_plusieurs_morceaux(self):
        self.assertEqual(
            hc.joindre_txt('"v=spf1 include:a.example.net " "-all"'),
            "v=spf1 include:a.example.net -all",
        )
        r, _ = self.verifier({"example.org": dig('"v=spf1 mx " "-all"')})
        self.assertEqual(r["mail_spf"].statut, hc.OK)

    def test_dmarc(self):
        r, _ = self.verifier(
            {"_dmarc.example.org": dig('"v=DMARC1; p=reject"')}
        )
        self.assertEqual(r["mail_dmarc"].statut, hc.OK)
        self.assertIn("reject", r["mail_dmarc"].message())
        r, _ = self.verifier({})
        self.assertEqual(r["mail_dmarc"].statut, hc.ATTN)

    def test_dkim(self):
        nom = "s1._domainkey.example.org"
        r, _ = self.verifier({nom: dig('"v=DKIM1; k=rsa; p=MIIBIj"')}, "s1")
        self.assertEqual(r["mail_dkim"].statut, hc.OK)
        r, _ = self.verifier({}, "s1")
        self.assertEqual(r["mail_dkim"].statut, hc.FAIL)
        r, _ = self.verifier({nom: dig('"v=DKIM1; p="')}, "s1")
        self.assertEqual(r["mail_dkim"].statut, hc.FAIL)
        self.assertIn("revoked", r["mail_dkim"].message())
        r, _ = self.verifier({})
        self.assertNotIn("mail_dkim", r)

    def test_recherche_en_echec_n_est_pas_une_absence(self):
        r, _ = self.verifier(
            {
                "example.org": (
                    9,
                    ";; connection timed out; no servers could be reached\n",
                )
            }
        )
        self.assertEqual(r["mail_spf"].statut, hc.SKIP)
        self.assertIn("failed", r["mail_spf"].message())

    def test_dig_rend_0_sur_un_serveur_en_echec(self):
        """dig rend 0 pour toute réponse reçue : un SERVFAIL ou un REFUSED
        n'a qu'une section réponse vide, et seul le statut de l'en-tête le
        distingue d'un nom sans enregistrement."""
        nom = "s1._domainkey.example.org"
        for statut in ("SERVFAIL", "REFUSED"):
            with self.subTest(statut=statut):
                zone = {
                    "example.org": dig(statut=statut),
                    "_dmarc.example.org": dig(statut=statut),
                    nom: dig(statut=statut),
                }
                r, systeme = self.verifier(zone, "s1")
                self.assertEqual([x.statut for x in r.values()], [hc.SKIP] * 3)
                self.assertIsNone(hc.lire_txt("dig", 0, zone[nom][1]))
        commande = systeme.appels[0]
        self.assertNotIn("+short", commande)
        self.assertIn("+comments", commande)
        self.assertEqual(commande[-2:], ["TXT", "example.org"])

    def test_sortie_de_dig(self):
        self.assertEqual(hc.lire_txt("dig", 0, dig()[1]), [])
        self.assertEqual(hc.lire_txt("dig", 0, dig(statut="NXDOMAIN")[1]), [])
        self.assertEqual(
            hc.lire_txt("dig", 0, dig('"v=spf1 mx " "-all"', '"x"')[1]),
            ["v=spf1 mx -all", "x"],
        )
        # Un CNAME de la section réponse n'est pas un TXT.
        cname = dig()[1] + (
            ";; ANSWER SECTION:\n"
            "_dmarc.example.org.\t300\tIN\tCNAME\tdmarc.example.net.\n"
        )
        self.assertEqual(hc.lire_txt("dig", 0, cname), [])
        # Sans en-tête (sortie tronquée, option ignorée), rien n'est sûr.
        self.assertIsNone(hc.lire_txt("dig", 0, ""))
        self.assertIsNone(hc.lire_txt("dig", 0, '"v=spf1 -all"\n'))
        # Un premier serveur muet, puis un second qui répond : le dernier
        # statut tranche.
        reprise = (
            ";; communications error to 127.0.0.1#53: timed out\n"
            + dig('"v=spf1 -all"')[1]
        )
        self.assertEqual(hc.lire_txt("dig", 0, reprise), ["v=spf1 -all"])

    def test_ni_dig_ni_host(self):
        r, systeme = self.verifier({}, "s1", binaires=())
        self.assertEqual(
            [x.statut for x in r.values()], [hc.SKIP, hc.SKIP, hc.SKIP]
        )
        self.assertEqual(systeme.appels, [])

    def test_sortie_de_host(self):
        sortie = (
            'example.org descriptive text "v=spf1 mx " "-all"\n'
            'example.org descriptive text "other"\n'
        )
        self.assertEqual(
            hc.lire_txt("host", 0, sortie), ["v=spf1 mx -all", "other"]
        )
        self.assertEqual(
            hc.lire_txt(
                "host", 1, "Host x.example.org not found: 3(NXDOMAIN)\n"
            ),
            [],
        )
        self.assertIsNone(hc.lire_txt("host", 1, ";; connection timed out\n"))
        r, systeme = self.verifier(
            {"example.org": (0, sortie)}, binaires=("host",)
        )
        self.assertEqual(r["mail_spf"].statut, hc.OK)
        self.assertEqual(systeme.appels[0][:4], ["host", "-W", "3", "-t"])

    def test_noms_refuses_avant_tout_appel(self):
        systeme = FauxSysteme()
        for argv in (
            ["--url", "example.org", "--mail-domain=-f/etc/passwd"],
            ["--url", "example.org", "--mail-domain", "-f/etc/passwd"],
            [
                "--url",
                "example.org",
                "--mail-domain",
                "example.org",
                "--dkim-selector",
                "a;b",
            ],
            ["--url", "example.org", "--dkim-selector", "s1"],
        ):
            with self.subTest(argv=argv):
                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as fin,
                ):
                    hc.main(argv, systeme=systeme, flux=io.StringIO())
                self.assertEqual(fin.exception.code, 2)
        self.assertEqual(systeme.appels, [])


class TestUrl(unittest.TestCase):
    def test_normalisation(self):
        self.assertEqual(
            hc.normaliser_url("example.org").url, "https://example.org"
        )
        self.assertEqual(
            hc.normaliser_url("https://example.org/web?x=1").url,
            "https://example.org",
        )
        self.assertEqual(
            hc.normaliser_url("http://example.org:8069").url,
            "http://example.org:8069",
        )
        self.assertEqual(
            hc.normaliser_url("https://example.org:443").url,
            "https://example.org",
        )
        cible = hc.normaliser_url("http://[2001:db8::1]:8069")
        self.assertEqual(cible.url, "http://[2001:db8::1]:8069")
        self.assertEqual(cible.hote, "2001:db8::1")

    def test_refus(self):
        for texte in (
            "ftp://example.org",
            "https://u:p@example.org",
            "https://u@example.org",
            "https://",
            "",
            "https://example.org:99999",
        ):
            with self.subTest(texte=texte):
                with self.assertRaises(ValueError):
                    hc.normaliser_url(texte)

    def test_ligne_de_commande(self):
        for argv in (["--url", "ftp://x"], ["--url", "https://u:p@x"], []):
            with self.subTest(argv=argv):
                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as fin,
                ):
                    hc.analyser(argv)
                self.assertEqual(fin.exception.code, 2)


def routes_saines():
    """Un Odoo 18 derrière rien : gestionnaire désactivé, bus relayé."""
    return {
        "/web/webclient/version_info": VERSION_18,
        "/web/login": (
            200,
            {"Set-Cookie": "session_id=abc; Path=/"},
            "<html>login</html>",
        ),
        "/web/health": (200, {}, '{"status": "pass"}'),
        "/web/database/manager": (200, {}, DESACTIVE),
        "/web/database/selector": (200, {}, DESACTIVE),
        "/websocket": (400, {}, "Bad Request"),
        "/robots.txt": (200, {}, "User-agent: *\nDisallow: /\nAllow: /web/"),
    }


class TestParcoursComplet(unittest.TestCase):
    """`--url http://127.0.0.1:P` sur le faux Odoo : TLS, redirection et
    HSTS sautés, un ATTN « pas en HTTPS »."""

    CLES = {"id", "target", "status", "message", "hint", "data"}

    def lancer(self, serveur, *options):
        sortie = io.StringIO()
        with contextlib.redirect_stderr(io.StringIO()):
            code = hc.main(
                ["--url", serveur.url] + list(options),
                systeme=FauxSysteme(),
                flux=sortie,
            )
        return code, sortie.getvalue()

    def test_sain_rend_0_avec_un_attn(self):
        with FauxOdoo(routes_saines()) as serveur:
            code, texte = self.lancer(serveur)
            requetes = serveur.requetes
        self.assertEqual(code, hc.CODE_OK, texte)
        self.assertIn("[ATTN]", texte)
        self.assertIn("OK ", texte)
        self.assertIn("SKIP 3", texte)
        for requete in requetes:
            self.assertNotIn("authorization", requete.entetes)
            self.assertNotIn("cookie", requete.entetes)
            self.assertEqual(
                requete.entetes.get("user-agent"), "ERPLibre-health-check"
            )

    def test_json_stable(self):
        with FauxOdoo(routes_saines()) as serveur:
            code, texte = self.lancer(serveur, "--json")
        resume = json.loads(texte)
        self.assertEqual(
            set(resume),
            {
                "tool",
                "odoo_version",
                "targets",
                "checks",
                "summary",
                "exit_code",
            },
        )
        self.assertEqual(resume["tool"], "health_check")
        self.assertEqual(resume["odoo_version"], 18)
        self.assertEqual(resume["exit_code"], code)
        self.assertEqual(
            set(resume["summary"]), {"ok", "attn", "fail", "skip"}
        )
        self.assertEqual(
            set(resume["targets"][0]), {"kind", "url", "odoo_version"}
        )
        statuts = set()
        for verdict in resume["checks"]:
            self.assertEqual(set(verdict), self.CLES)
            statuts.add(verdict["status"])
        self.assertLessEqual(statuts, set(hc.STATUTS))
        idents = {v["id"]: v["status"] for v in resume["checks"]}
        self.assertEqual(idents["https"], "ATTN")
        self.assertEqual(idents["tls_certificate"], "SKIP")
        self.assertEqual(idents["db_manager"], "OK")
        self.assertEqual(idents["websocket"], "OK")
        self.assertEqual(idents["robots"], "OK")

    def test_version_inconnue(self):
        """Sans version lisible (route absente, ou corps qui n'est pas du
        JSON), le bus essaie /websocket puis /longpolling/poll."""
        for version in (None, (200, {}, "<html>pas du json</html>")):
            with self.subTest(version=version):
                routes = routes_saines()
                del routes["/web/webclient/version_info"]
                if version:
                    routes["/web/webclient/version_info"] = version
                del routes["/websocket"]
                routes["/longpolling/poll"] = (400, {}, "Bad Request")
                with FauxOdoo(routes) as serveur:
                    code, texte = self.lancer(serveur, "--json")
                    chemins = serveur.chemins()
                resume = json.loads(texte)
                self.assertIsNone(resume["odoo_version"])
                bus = [c for c in resume["checks"] if c["id"] == "websocket"]
                self.assertEqual(bus[0]["status"], "OK")
                self.assertEqual(bus[0]["data"]["path"], "/longpolling/poll")
                self.assertLess(
                    chemins.index("/websocket"),
                    chemins.index("/longpolling/poll"),
                )

    def test_web_health_demande_l_etat_de_postgresql(self):
        with FauxOdoo(routes_saines()) as serveur:
            self.lancer(serveur)
            chemins = serveur.chemins()
        self.assertIn("/web/health?db_server_status=1", chemins)

    def test_le_delai_est_transmis_a_chaque_requete(self):
        delais = []

        class Compteur(FauxSysteme):
            def ouvrir(self, url, delai, donnees=None, entetes=None):
                delais.append(delai)
                return super().ouvrir(url, delai, donnees, entetes)

        with FauxOdoo(routes_saines()) as serveur:
            with contextlib.redirect_stderr(io.StringIO()):
                hc.main(
                    ["--url", serveur.url, "--timeout", "7"],
                    systeme=Compteur(),
                    flux=io.StringIO(),
                )
        self.assertTrue(delais)
        self.assertEqual(set(delais), {7.0})

    def test_erreur_imprevue_rend_2_et_ctrl_c_130(self):
        class Panne(FauxSysteme):
            def __init__(self, erreur):
                super().__init__()
                self.erreur = erreur

            def ouvrir(self, url, delai, donnees=None, entetes=None):
                raise self.erreur

        sortie, erreurs = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(erreurs):
            code = hc.main(
                ["--url", "example.org", "--json"],
                systeme=Panne(RuntimeError("boom")),
                flux=sortie,
            )
        self.assertEqual(code, hc.CODE_REFUS)
        resume = json.loads(sortie.getvalue())
        self.assertEqual(resume["exit_code"], hc.CODE_REFUS)
        self.assertIn("boom", resume["error"])
        self.assertIn("boom", erreurs.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            code = hc.main(
                ["--url", "example.org"],
                systeme=Panne(KeyboardInterrupt()),
                flux=io.StringIO(),
            )
        self.assertEqual(code, hc.CODE_INTERROMPU)

    def test_gestionnaire_expose_rend_1(self):
        routes = routes_saines()
        routes["/web/database/manager"] = (200, {}, FORMULAIRE)
        with FauxOdoo(routes) as serveur:
            code, texte = self.lancer(serveur)
        self.assertEqual(code, hc.CODE_FAIL)
        self.assertIn("[FAIL]", texte)
        self.assertIn("db_manager (FAIL)", texte)

    def test_mail_avec_le_parcours(self):
        systeme = FauxSysteme()
        systeme.dns = {"example.org": dig('"v=spf1 mx -all"')}
        sortie = io.StringIO()
        with FauxOdoo(routes_saines()) as serveur:
            code = hc.main(
                [
                    "--url",
                    serveur.url,
                    "--mail-domain",
                    "example.org",
                    "--json",
                ],
                systeme=systeme,
                flux=sortie,
            )
        resume = json.loads(sortie.getvalue())
        mails = [c for c in resume["checks"] if c["id"].startswith("mail_")]
        self.assertEqual([c["status"] for c in mails], ["OK", "ATTN"])
        self.assertEqual(mails[0]["target"], "example.org")
        self.assertEqual(code, hc.CODE_OK)


class TestModeLocal(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.wd = d.name
        with open(os.path.join(self.wd, "run.sh"), "w") as f:
            f.write("#!/bin/bash\n")

    def config(self, port, extra=""):
        chemin = os.path.join(self.wd, "config.conf")
        with open(chemin, "w") as f:
            f.write(f"[options]\nhttp_port = {port}\ndb_name = base1\n{extra}")
        return chemin

    def systeme(self):
        systeme = FauxSysteme()
        systeme.wd = self.wd
        return systeme

    def test_sonde_l_adresse_de_la_configuration(self):
        with FauxOdoo(routes_saines()) as serveur:
            self.config(serveur.port, "list_db = False\n")
            avant = sorted(os.listdir(self.wd))
            sortie = io.StringIO()
            code = hc.main(
                ["--local", "--service", "erplibre_demo", "--json"],
                systeme=self.systeme(),
                flux=sortie,
            )
            chemins = serveur.chemins()
        self.assertEqual(code, hc.CODE_OK, sortie.getvalue())
        self.assertIn("/web/login?db=base1", chemins)
        self.assertNotIn("/robots.txt", chemins)
        self.assertEqual(sorted(os.listdir(self.wd)), avant)
        resume = json.loads(sortie.getvalue())
        idents = {c["id"]: c["status"] for c in resume["checks"]}
        self.assertEqual(idents["list_db"], "OK")
        self.assertEqual(idents["websocket"], "SKIP")
        self.assertEqual(resume["targets"][0]["kind"], "local")

    def test_gestionnaire_joignable_en_local_n_echoue_pas(self):
        routes = routes_saines()
        routes["/web/database/manager"] = (200, {}, FORMULAIRE)
        with FauxOdoo(routes) as serveur:
            self.config(serveur.port)
            version, resultats = hc.verifier_local(
                "127.0.0.1", serveur.port, "base1", None, 5, self.systeme()
            )
        idents = {r.ident: r.statut for r in resultats}
        self.assertEqual(version, 18)
        self.assertEqual(idents["db_manager"], hc.ATTN)
        self.assertEqual(idents["list_db"], hc.ATTN)
        self.assertNotIn(hc.FAIL, idents.values())

    def test_configuration_illisible_rend_2_avec_sudo(self):
        if os.geteuid() == 0:
            self.skipTest("root lit tout")
        chemin = self.config(8069)
        os.chmod(chemin, 0)
        self.addCleanup(os.chmod, chemin, 0o600)
        erreurs = io.StringIO()
        with contextlib.redirect_stderr(erreurs):
            code = hc.main(
                ["--local", "--service", "erplibre_demo"],
                systeme=self.systeme(),
                flux=io.StringIO(),
            )
        self.assertEqual(code, hc.CODE_REFUS)
        self.assertIn("sudo", erreurs.getvalue())

    def test_service_sans_local_refuse(self):
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            hc.analyser(["--url", "example.org", "--service", "x"])


class TestMessages(unittest.TestCase):
    def test_traduction_qui_nomme_une_valeur_absente(self):
        resultat = hc.Resultat("x", hc.OK, "a {absent} b")
        self.assertEqual(resultat.message(), "a {absent} b")

    def test_json_en_anglais(self):
        resultat = hc.Resultat(
            "x", hc.ATTN, "Login page: HTTP {status}.", {"status": 500}
        )
        resultat.cible = "https://example.org"
        self.assertEqual(resultat.json()["message"], "Login page: HTTP 500.")


if __name__ == "__main__":
    unittest.main()
