#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'URL qui a échoué n'est pas toujours celle qu'on a demandée.

Sur un site Odoo, chaque page traverse deux ou trois redirections —
mesuré, 146 pour 55 pages, entre la langue et le slug canonique. Quand
la DERNIÈRE rend 500, l'outil nommait la première : on allait vérifier
une page parfaitement saine et l'on concluait que le test se trompait.

Et un dépassement de délai ne rend PAS 500 : `fetch` rend 0, que le
rapport écrit « aucune réponse ». Confondre les deux enverrait chercher
une lenteur là où le serveur a répondu par une erreur.
"""

import http.server
import io
import os
import socketserver
import sys
import threading
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.odoo.migration import smoke_public_url as smoke  # noqa: E402
from script.todo import todo_i18n  # noqa: E402


class Chaine(http.server.BaseHTTPRequestHandler):
    """/depart → 303 → /milieu → 303 → /fin, qui décide."""

    fin_status = 500

    def do_GET(self):
        if self.path == "/depart":
            self.send_response(303)
            self.send_header("Location", "/milieu")
            self.end_headers()
        elif self.path == "/milieu":
            self.send_response(303)
            self.send_header("Location", "/fin")
            self.end_headers()
        elif self.path == "/direct":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"boum")
        else:
            self.send_response(self.fin_status)
            self.end_headers()
            self.wfile.write(b"boum")

    def log_message(self, *args):
        pass


class TestFetchFollowsTheChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = socketserver.TCPServer(("127.0.0.1", 0), Chaine)
        cls.port = cls.srv.server_address[1]
        cls.fil = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.fil.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def url(self, chemin):
        return f"http://127.0.0.1:{self.port}{chemin}"

    def test_it_reports_the_url_that_actually_failed(self):
        # LE point : la 500 est au bout de la chaîne, pas au départ.
        statut, _corps, finale = smoke.fetch(self.url("/depart"), timeout=5)
        self.assertEqual(statut, 500)
        self.assertTrue(finale.endswith("/fin"), finale)

    def test_without_a_redirect_both_are_the_same(self):
        statut, _corps, finale = smoke.fetch(self.url("/direct"), timeout=5)
        self.assertEqual(statut, 500)
        self.assertEqual(finale, self.url("/direct"))

    def test_a_success_also_carries_its_final_url(self):
        Chaine.fin_status = 200
        try:
            statut, _corps, finale = smoke.fetch(
                self.url("/depart"), timeout=5
            )
            self.assertEqual(statut, 200)
            self.assertTrue(finale.endswith("/fin"), finale)
        finally:
            Chaine.fin_status = 500

    def test_a_dead_host_is_zero_NOT_five_hundred(self):
        # C'est ce qui distingue « le serveur a répondu par une erreur »
        # de « il n'a pas répondu ». Les confondre envoie chercher une
        # lenteur là où il y a une exception.
        statut, corps, finale = smoke.fetch(
            "http://127.0.0.1:1/jamais", timeout=1
        )
        self.assertEqual(statut, 0)
        self.assertEqual(corps, "")
        self.assertEqual(finale, "http://127.0.0.1:1/jamais")

    def test_check_urls_keeps_the_final_url(self):
        echecs = smoke.check_urls([self.url("/depart")], timeout=5)
        self.assertEqual(len(echecs), 1)
        url, statut, parents, finale = echecs[0]
        self.assertEqual(url, self.url("/depart"))
        self.assertEqual(statut, 500)
        self.assertEqual(parents, [])
        self.assertTrue(finale.endswith("/fin"))

    def test_a_page_that_answers_is_not_a_failure(self):
        Chaine.fin_status = 200
        try:
            self.assertEqual(
                smoke.check_urls([self.url("/depart")], timeout=5), []
            )
        finally:
            Chaine.fin_status = 500


class TestTheReport(unittest.TestCase):
    def test_it_names_the_final_url_when_it_differs(self):
        texte = smoke.render(
            ["a", "b"], [("http://x/depart", 500, [], "http://x/fin")]
        )
        self.assertIn("http://x/depart", texte)
        self.assertIn(todo_i18n.t("failed at"), texte)
        self.assertIn("http://x/fin", texte)

    def test_it_stays_quiet_when_they_are_the_same(self):
        # Répéter la même URL sur deux lignes n'apprend rien et allonge
        # un rapport qui peut compter trente-quatre entrées.
        texte = smoke.render(
            ["a"], [("http://x/page", 500, [], "http://x/page")]
        )
        self.assertNotIn(todo_i18n.t("failed at"), texte)

    def test_no_answer_is_worded_apart_from_a_status(self):
        texte = smoke.render(
            ["a"], [("http://x/page", 0, [], "http://x/page")]
        )
        self.assertIn(todo_i18n.t("no answer"), texte)
        self.assertNotIn("[500]", texte)


class TestNothingUnpacksTheFailureTupleBlindly(unittest.TestCase):
    """Ajouter un champ au tuple d'échec a cassé une migration en cours.

    Le tuple est passé de trois à quatre éléments et deux sites
    dépaquetaient encore trois — `too many values to unpack`, en plein
    milieu, APRÈS la réinitialisation d'une copie COW. Le commentaire
    « TOUJOURS quatre éléments » ne protège de rien : il faut ne pas
    dépaqueter quand on ne veut qu'un champ.
    """

    CHEMIN = os.path.join(
        os.path.dirname(__file__),
        "..",
        "script",
        "odoo",
        "migration",
        "smoke_public_url.py",
    )

    def source(self):
        with io.open(self.CHEMIN, encoding="utf-8") as handle:
            return handle.read()

    def test_no_three_element_unpack_survives(self):
        import re

        motif = re.compile(
            r"for\s+[a-z_]+,\s*[a-z_]+,\s*[a-z_]+\s+in\s+lst_failure"
        )
        trouves = motif.findall(self.source())
        self.assertEqual(trouves, [], f"dépaquetage à trois : {trouves}")

    def test_taking_only_the_url_uses_an_index(self):
        # Indexer survit au prochain champ ajouté ; dépaqueter non.
        self.assertIn("[echec[0] for echec in lst_failure]", self.source())


class TestRecheckingAfterAReset(unittest.TestCase):
    """La passe qui a cassé, exercée pour de vrai.

    Elle ne tournait sous aucun test : c'est pourquoi le dépaquetage à
    trois y a survécu à la suite complète, aux mutations, et n'est
    tombé qu'en production.
    """

    def setUp(self):
        self.vrais = {
            nom: getattr(smoke, nom)
            for nom in (
                "start_server",
                "wait_ready",
                "check_urls",
                "internal_needs_retry",
                "stop_server",
            )
            if hasattr(smoke, nom)
        }
        self.vus = []

        class FauxServeur:
            def __init__(self):
                self.arrete = False

        smoke.start_server = lambda *a, **k: FauxServeur()
        smoke.wait_ready = lambda *a, **k: True
        smoke.internal_needs_retry = lambda rapport: False
        if hasattr(smoke, "stop_server"):
            smoke.stop_server = lambda *a, **k: None

        def faux_check(lst_url, timeout=30):
            self.vus.append(list(lst_url))
            return []

        smoke.check_urls = faux_check

    def tearDown(self):
        for nom, valeur in self.vrais.items():
            setattr(smoke, nom, valeur)

    def test_it_rechecks_exactly_the_urls_that_had_failed(self):
        echecs = [
            ("http://h/contactus", 500, ["2837"], "http://h/en/contactus"),
            ("http://h/blog", 500, [], "http://h/blog"),
        ]
        smoke.recheck_after_reset(
            "db",
            8169,
            "./config.conf",
            "http://h",
            None,
            echecs,
            {"failures": []},
            internal=False,
        )
        self.assertEqual(self.vus, [["http://h/contactus", "http://h/blog"]])

    def test_it_rechecks_the_REQUESTED_url_not_the_final_one(self):
        # On revérifie ce que le sitemap publie : c'est cette adresse-là
        # que les visiteurs demandent.
        echecs = [("http://h/a", 500, [], "http://h/z")]
        smoke.recheck_after_reset(
            "db",
            8169,
            "./config.conf",
            "http://h",
            None,
            echecs,
            {"failures": []},
            internal=False,
        )
        self.assertEqual(self.vus, [["http://h/a"]])

    def test_an_empty_failure_list_rechecks_nothing(self):
        smoke.recheck_after_reset(
            "db",
            8169,
            "./config.conf",
            "http://h",
            None,
            [],
            {"failures": []},
            internal=False,
        )
        self.assertEqual(self.vus, [[]])


class TestTheLogSurvives(unittest.TestCase):
    def test_the_previous_run_is_kept(self):
        # Le journal était ouvert en « w » : relancer le test effaçait la
        # trace de l'échec qu'on venait de voir.
        with io.open(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "script",
                "odoo",
                "migration",
                "smoke_public_url.py",
            ),
            encoding="utf-8",
        ) as handle:
            src = handle.read()
        debut = src.index("def start_server")
        fin = src.index("subprocess.Popen", debut)
        self.assertIn("os.replace(log_path, log_path", src[debut:fin])


if __name__ == "__main__":
    unittest.main()
