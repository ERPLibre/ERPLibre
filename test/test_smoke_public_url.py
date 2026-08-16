#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Une migration peut réussir et servir quand même des 500.

Mesuré sur une vraie migration 12 → 13 : tous les modules chargés, aucune
erreur au journal, et pourtant deux pages publiques sur trente-trois
répondaient 500 — un billet de blogue et /contactus. Rien ne les distinguait
avant de les demander.

La liste vient du sitemap, celle qu'Odoo publie pour les moteurs de
recherche. Elle ne se lit PAS depuis « odoo-bin shell » : enumerate_pages()
réclame http.root.get_db_router(request.db) et lève « object unbound » sans
requête réelle. D'où le serveur démarré, interrogé, arrêté.
"""

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "script", "odoo", "migration"))

import smoke_public_url as smoke  # noqa: E402


class TestTheUrlAreBroughtHome(unittest.TestCase):
    """Le sitemap porte le domaine du site ; on teste une base locale."""

    def test_the_host_is_replaced(self):
        # Garder le domaine ferait interroger la PRODUCTION depuis une
        # migration. C'est le genre d'erreur qui ne se voit qu'après.
        url = smoke.local_url(
            "http://127.0.0.1:8169", "https://technolibre.ca/blog/x-3/post/y-5"
        )
        self.assertEqual(url, "http://127.0.0.1:8169/blog/x-3/post/y-5")

    def test_a_query_string_survives(self):
        url = smoke.local_url("http://127.0.0.1:8169", "https://a.ca/p?x=1")
        self.assertEqual(url, "http://127.0.0.1:8169/p?x=1")

    def test_a_bare_domain_becomes_the_root(self):
        url = smoke.local_url("http://127.0.0.1:8169", "https://a.ca")
        self.assertEqual(url, "http://127.0.0.1:8169/")

    def test_a_trailing_slash_on_the_base_does_not_double(self):
        url = smoke.local_url("http://127.0.0.1:8169/", "https://a.ca/p")
        self.assertEqual(url, "http://127.0.0.1:8169/p")


class TestReadingTheSitemap(unittest.TestCase):
    def setUp(self):
        self.answers = {}
        self.original = smoke.fetch
        smoke.fetch = lambda url, timeout=30: self.answers.get(url, (404, ""))
        self.addCleanup(setattr, smoke, "fetch", self.original)

    def test_a_plain_sitemap(self):
        self.answers["http://h/sitemap.xml"] = (
            200,
            "<urlset><loc>https://a.ca/x</loc><loc>https://a.ca/y</loc></urlset>",
        )
        lst_url, status = smoke.sitemap_urls("http://h")
        self.assertEqual(status, 200)
        self.assertEqual(lst_url, ["http://h/x", "http://h/y"])

    def test_an_index_is_followed(self):
        # Odoo découpe le sitemap au-delà d'un certain nombre de pages : ne
        # pas descendre d'un cran ferait tester deux fichiers XML au lieu du
        # site, et conclure « tout va bien ».
        self.answers["http://h/sitemap.xml"] = (
            200,
            "<sitemapindex><loc>https://a.ca/sitemap-1-1.xml</loc>"
            "</sitemapindex>",
        )
        self.answers["http://h/sitemap-1-1.xml"] = (
            200,
            "<urlset><loc>https://a.ca/deep</loc></urlset>",
        )
        lst_url, _status = smoke.sitemap_urls("http://h")
        self.assertEqual(lst_url, ["http://h/deep"])

    def test_duplicates_are_dropped(self):
        self.answers["http://h/sitemap.xml"] = (
            200,
            "<urlset><loc>https://a.ca/x</loc><loc>https://a.ca/x</loc></urlset>",
        )
        lst_url, _status = smoke.sitemap_urls("http://h")
        self.assertEqual(lst_url, ["http://h/x"])

    def test_an_unreachable_sitemap_is_reported_not_taken_as_empty(self):
        # Sans cela, un sitemap injoignable se lirait comme « aucune page à
        # tester », c'est-à-dire comme un succès.
        lst_url, status = smoke.sitemap_urls("http://h")
        self.assertEqual(lst_url, [])
        self.assertEqual(status, 404)


class TestWhatCountsAsAFailure(unittest.TestCase):
    def setUp(self):
        self.answers = {}
        self.original = smoke.fetch
        smoke.fetch = lambda url, timeout=30: self.answers.get(url, (200, ""))
        self.addCleanup(setattr, smoke, "fetch", self.original)

    def test_a_500_fails(self):
        self.answers["http://h/bad"] = (500, "")
        self.assertEqual(
            smoke.check_urls(["http://h/bad"]), [("http://h/bad", 500)]
        )

    def test_a_404_fails_too(self):
        # Le sitemap est la liste PUBLIQUE : une page qui y figure et répond
        # 404 est aussi fausse qu'un 500, juste plus discrète.
        self.answers["http://h/gone"] = (404, "")
        self.assertEqual(len(smoke.check_urls(["http://h/gone"])), 1)

    def test_no_answer_at_all_fails(self):
        self.answers["http://h/dead"] = (0, "")
        self.assertEqual(
            smoke.check_urls(["http://h/dead"]), [("http://h/dead", 0)]
        )

    def test_a_200_passes(self):
        self.assertEqual(smoke.check_urls(["http://h/ok"]), [])


class TestTheReport(unittest.TestCase):
    def setUp(self):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def test_all_green_says_how_many(self):
        text = smoke.render(["a", "b"], [])
        self.assertIn("2", text)
        self.assertIn("✅", text)

    def test_a_failure_shows_the_status_and_the_url(self):
        text = smoke.render(["a"], [("http://h/blog/x", 500)])
        self.assertIn("500", text)
        self.assertIn("http://h/blog/x", text)

    def test_an_empty_sitemap_is_not_a_success(self):
        # « rien testé » ne doit pas se lire « rien de cassé ».
        text = smoke.render([], [])
        self.assertIn("⚠️", text)


class TestTheServerIsAlwaysStopped(unittest.TestCase):
    """Un serveur oublié tient le port et fait échouer le palier suivant."""

    def test_it_is_terminated_even_when_the_sitemap_fails(self):
        stopped = []

        class FakeServer:
            def terminate(self):
                stopped.append("terminate")

            def wait(self, timeout=None):
                return 0

            def kill(self):
                stopped.append("kill")

        original_start = smoke.start_server
        original_wait = smoke.wait_ready
        smoke.start_server = lambda db, port, cfg="./config.conf": FakeServer()
        smoke.wait_ready = lambda base, timeout=180, sleep=2: False
        self.addCleanup(setattr, smoke, "start_server", original_start)
        self.addCleanup(setattr, smoke, "wait_ready", original_wait)
        with self.assertRaises(RuntimeError):
            smoke.run("db", 8169, "./config.conf")
        self.assertEqual(stopped, ["terminate"])

    def test_a_distinct_port_by_default(self):
        # 8069 est souvent pris par l'instance de travail : le lui voler
        # ferait échouer le test pour une raison sans rapport.
        self.assertNotEqual(smoke.DEFAULT_PORT, 8069)


class TestTheMigrationOffersIt(unittest.TestCase):
    def setUp(self):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def run_prompt(self, answer):
        from script.todo.todo_upgrade import TodoUpgrade

        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.dct_progression = {}
        upgrade.lst_command_executed = []
        upgrade.write_config = lambda: None
        lst_cmd = []
        upgrade.run_on_terminal = lambda cmd: lst_cmd.append(cmd) or 0
        upgrade.ask_gate = lambda prompt: answer
        upgrade.prompt_smoke_public_url("db_upgrade_13")
        return lst_cmd

    def test_the_default_runs_nothing(self):
        # Cela démarre un serveur et peut durer : pas à chaque palier sans
        # qu'on l'ait demandé.
        self.assertEqual(self.run_prompt(""), [])

    def test_yes_runs_it_on_the_upgraded_database(self):
        lst_cmd = self.run_prompt("y")
        self.assertEqual(len(lst_cmd), 1)
        self.assertIn("smoke_public_url.py", lst_cmd[0])
        self.assertIn("-d db_upgrade_13", lst_cmd[0])

    def test_it_is_asked_before_the_selenium_prompt(self):
        # Après, la question arriverait une fois le navigateur ouvert : on
        # aurait déjà cherché à la main ce que le test nomme.
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        self.assertLess(
            source.index("prompt_smoke_public_url"),
            source.index("Open the server with Selenium"),
        )


if __name__ == "__main__":
    unittest.main()
