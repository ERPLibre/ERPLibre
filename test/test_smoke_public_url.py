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
            smoke.check_urls(["http://h/bad"]), [("http://h/bad", 500, [])]
        )

    def test_a_404_fails_too(self):
        # Le sitemap est la liste PUBLIQUE : une page qui y figure et répond
        # 404 est aussi fausse qu'un 500, juste plus discrète.
        self.answers["http://h/gone"] = (404, "")
        self.assertEqual(len(smoke.check_urls(["http://h/gone"])), 1)

    def test_no_answer_at_all_fails(self):
        self.answers["http://h/dead"] = (0, "")
        self.assertEqual(
            smoke.check_urls(["http://h/dead"]), [("http://h/dead", 0, [])]
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
        text = smoke.render(["a"], [("http://h/blog/x", 500, [])])
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
        original_stop = smoke.stop_server
        original_port = smoke.port_is_taken
        smoke.start_server = (
            lambda db, port, cfg="./config.conf", log_path=None: FakeServer()
        )
        smoke.wait_ready = lambda base, timeout=180, sleep=2: False
        smoke.stop_server = lambda server: stopped.append("terminate")
        smoke.port_is_taken = lambda port, host="127.0.0.1": False
        self.addCleanup(setattr, smoke, "start_server", original_start)
        self.addCleanup(setattr, smoke, "wait_ready", original_wait)
        self.addCleanup(setattr, smoke, "stop_server", original_stop)
        self.addCleanup(setattr, smoke, "port_is_taken", original_port)
        with self.assertRaises(RuntimeError):
            smoke.run("db", 8169, "./config.conf")
        self.assertEqual(stopped, ["terminate"])

    def test_a_distinct_port_by_default(self):
        # 8069 est souvent pris par l'instance de travail : le lui voler
        # ferait échouer le test pour une raison sans rapport.
        self.assertNotEqual(smoke.DEFAULT_PORT, 8069)


class TestTheCulpritViewsAreNamed(unittest.TestCase):
    """Détecter sans nommer laisse relever des ids dans une trace à la main."""

    def test_the_parent_is_read_from_the_error_context(self):
        # C'est le PARENT le coupable : la copie figée dans laquelle
        # l'enfant ne trouve plus son xpath.
        line = "[view_id: 3282, xml_id: n/a, model: n/a, parent_id: 3281]"
        self.assertEqual(smoke.RE_CONTEXT.findall(line), [("3282", "3281")])

    def test_the_context_line_is_not_translated(self):
        # La phrase qui précède l'est, celle-ci non : la lire marche donc
        # sur un système français comme anglais.
        self.assertEqual(
            smoke.RE_CONTEXT.findall("[view_id: 1, parent_id: 2]"),
            [("1", "2")],
        )

    def test_a_late_context_is_still_attached(self):
        # Odoo vide son tampon à l'arrêt : le journal se lit APRÈS, et rien
        # ne doit dépendre du moment où la ligne est apparue.
        lst_failure = [("http://h/a", 500, [])]
        log = ["[view_id: 3288, model: n/a, parent_id: 2841]"]
        rebuilt = smoke.attach_missing_parents(lst_failure, log)
        self.assertIn("2841", rebuilt[0][2])

    def test_both_the_parent_and_the_child_are_proposed(self):
        # LE défaut mesuré sur /contactus : le parent (3281) était IDENTIQUE
        # à sa vue module, et c'est l'enfant (3282) qui portait l'arch
        # périmée. Ne nommer que le parent envoyait réinitialiser une copie
        # qui allait déjà bien, et la page restait en 500.
        lst_failure = [("http://h/contactus", 500, [])]
        log = ["[view_id: 3282, model: n/a, parent_id: 3281]"]
        rebuilt = smoke.attach_missing_parents(lst_failure, log)
        self.assertEqual(rebuilt[0][2], ["3281", "3282"])

    def test_the_parent_comes_first(self):
        # C'est le cas le plus fréquent — le blogue — donc en tête de liste.
        lst_failure = [("http://h/a", 500, [])]
        log = ["[view_id: 3288, model: n/a, parent_id: 2841]"]
        rebuilt = smoke.attach_missing_parents(lst_failure, log)
        self.assertEqual(rebuilt[0][2][0], "2841")

    def test_an_already_attributed_id_is_not_duplicated(self):
        lst_failure = [("http://h/a", 500, ["2841"])]
        log = ["[view_id: 3288, model: n/a, parent_id: 2841]"]
        rebuilt = smoke.attach_missing_parents(lst_failure, log)
        self.assertEqual(rebuilt[0][2].count("2841"), 1)


class TestARenderFailureNamesItsTemplate(unittest.TestCase):
    """Une QWebException ne porte pas de bloc [view_id …] : elle nomme le
    gabarit.

    Mesuré au palier 17 : une copie figée appelait `submenu.clean_url()`,
    méthode renommée `_clean_url()` par la version. 34 URL sur 37 rendaient
    500, et l'outil répondait « aucune vue parente nommée » — il ne lisait
    que le contexte d'héritage, absent ici.
    """

    def test_the_template_line_is_read(self):
        self.assertEqual(
            smoke.RE_TEMPLATE.findall("Template: website.submenu"),
            ["website.submenu"],
        )

    def test_prose_is_not_mistaken_for_a_key(self):
        # « Template: » suivi d'une phrase n'est pas un gabarit.
        self.assertEqual(
            smoke.RE_TEMPLATE.findall("Template: not a key, just words"), []
        )

    def test_only_keys_with_a_copy_are_proposed(self):
        # Proposer une clé sans copie COW enverrait réinitialiser une vue
        # module : la commande tournerait sans rien faire.
        seen = {}
        original = smoke.run_psql
        smoke.run_psql = lambda db, sql: (
            seen.update(sql=sql),
            [["website.submenu"]],
        )[1]
        self.addCleanup(setattr, smoke, "run_psql", original)
        got = smoke.template_keys(
            ["Template: website.submenu", "Template: website.layout"], "db"
        )
        self.assertEqual(got, ["website.submenu"])
        self.assertIn("website_id IS NOT NULL", seen["sql"])

    def test_no_template_line_asks_nothing_of_the_database(self):
        called = []
        original = smoke.run_psql
        smoke.run_psql = lambda db, sql: called.append(sql) or []
        self.addCleanup(setattr, smoke, "run_psql", original)
        self.assertEqual(smoke.template_keys(["rien ici"], "db"), [])
        self.assertEqual(called, [])

    def test_a_quote_in_a_key_is_escaped(self):
        seen = {}
        original = smoke.run_psql
        smoke.run_psql = lambda db, sql: (seen.update(sql=sql), [])[1]
        self.addCleanup(setattr, smoke, "run_psql", original)
        smoke.template_keys(["Template: a.b"], "db")
        self.assertIn("'a.b'", seen["sql"])

    def test_both_sources_feed_the_proposal(self):
        # Le contexte d'héritage quand il existe, le gabarit quand l'échec
        # vient du rendu : l'un ne remplace pas l'autre.
        import inspect

        source = inspect.getsource(smoke.run)
        self.assertIn("culprit_keys(", source)
        self.assertIn("template_keys(", source)


class TestTheServerIsKilledForReal(unittest.TestCase):
    """« ./run.sh » est un script bash : il ne transmet pas les signaux."""

    def test_it_starts_its_own_process_group(self):
        # Sans cela, terminate() tue l'enveloppe et laisse odoo-bin vivant.
        # Mesuré : six serveurs orphelins, un par essai, et les essais
        # suivants interrogeaient sans le savoir celui d'avant.
        import inspect

        source = inspect.getsource(smoke.start_server)
        self.assertIn("start_new_session=True", source)

    def test_it_kills_the_group_not_just_the_wrapper(self):
        import inspect

        source = inspect.getsource(smoke.stop_server)
        self.assertIn("killpg", source)

    def test_a_taken_port_is_refused_not_tested(self):
        # Un serveur resté d'un essai précédent répond « prêt » : on
        # testerait sa base à lui en croyant tester la sienne.
        original = smoke.port_is_taken
        smoke.port_is_taken = lambda port, host="127.0.0.1": True
        self.addCleanup(setattr, smoke, "port_is_taken", original)
        with self.assertRaises(RuntimeError) as caught:
            smoke.run("db", 8169, "./config.conf")
        self.assertIn("8169", str(caught.exception))


class TestOfferingTheFix(unittest.TestCase):
    def setUp(self):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"
        self.applied = []
        original = smoke.apply_reset
        smoke.apply_reset = lambda db, keys: (
            self.applied.append(keys),
            (0, "ok"),
        )[1]
        self.addCleanup(setattr, smoke, "apply_reset", original)

    def run_prompt(self, answer, lst_key=None):
        import contextlib
        import io

        if lst_key is None:
            lst_key = ["website_blog.blog_post_complete", "website_form.x"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            done = smoke.prompt(
                "db",
                [("http://h/a", 500, ["2841"])],
                lst_key,
                ask=lambda prompt: answer,
            )
        return done, out.getvalue()

    def test_every_key_is_numbered(self):
        _done, text = self.run_prompt("")
        self.assertIn("[1] website_blog.blog_post_complete", text)
        self.assertIn("[a]", text)

    def test_a_number_applies_only_that_one(self):
        done, _text = self.run_prompt("1")
        self.assertEqual(done, ["website_blog.blog_post_complete"])
        self.assertEqual(self.applied, [["website_blog.blog_post_complete"]])

    def test_a_applies_them_all(self):
        done, _text = self.run_prompt("a")
        self.assertEqual(len(done), 2)

    def test_empty_applies_nothing(self):
        done, text = self.run_prompt("")
        self.assertEqual(done, [])
        self.assertEqual(self.applied, [])
        self.assertIn("Kept", text)

    def test_an_unknown_answer_applies_nothing(self):
        done, text = self.run_prompt("9")
        self.assertEqual(self.applied, [])
        self.assertIn("Unknown choice", text)

    def test_no_key_found_says_so(self):
        done, text = self.run_prompt("a", lst_key=[])
        self.assertEqual(done, [])
        self.assertIn("nothing to offer", text)


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
        # Le doublon HONORE le défaut, comme le vrai `ask_gate`.
        upgrade.ask_gate = lambda prompt, default="": answer or default
        upgrade.prompt_smoke_public_url("db_upgrade_13")
        return lst_cmd

    def test_the_default_runs_it(self):
        # Une page cassée qu'on ne demande pas reste cassée. Le coût est
        # quelques minutes de serveur ; le prix de l'ignorer est de
        # découvrir le 500 six paliers plus loin.
        lst_cmd = self.run_prompt("")
        self.assertEqual(len(lst_cmd), 1)
        self.assertIn("smoke_public_url.py", lst_cmd[0])

    def test_saying_no_still_skips_it(self):
        self.assertEqual(self.run_prompt("n"), [])

    def test_yes_runs_it_on_the_upgraded_database(self):
        lst_cmd = self.run_prompt("y")
        self.assertEqual(len(lst_cmd), 1)
        self.assertIn("smoke_public_url.py", lst_cmd[0])
        self.assertIn("-d db_upgrade_13", lst_cmd[0])

    def test_it_is_also_asked_before_the_first_bump(self):
        # LA mesure de départ : sans elle, une page qui rendait déjà 500
        # avant la migration se lit comme un dégât du palier, et l'on
        # cherche des heures du mauvais côté.
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        self.assertEqual(source.count("prompt_smoke_public_url"), 2)
        premier = source.index("prompt_smoke_public_url")
        self.assertLess(
            premier, source.index("4 - Upgrade version with OpenUpgrade")
        )

    def test_the_baseline_runs_on_the_database_before_the_bump(self):
        # Sur la base d'AVANT, pas sur une base de palier qui n'existe pas
        # encore : la mesurer après ne dirait plus d'où vient la panne.
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        premier = source.index("prompt_smoke_public_url")
        fenetre = source[premier : premier + 90]
        self.assertIn("database_name", fenetre)
        self.assertNotIn("database_name_upgrade", fenetre)
        self.assertIn("baseline=True", fenetre)

    def test_the_baseline_says_what_it_measures(self):
        # Un même écran à deux moments différents : sans un mot, on croit
        # que la migration a déjà eu lieu.
        import contextlib
        import io

        from script.todo import todo_i18n
        from script.todo.todo_upgrade import TodoUpgrade

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.dct_progression = {}
        upgrade.lst_command_executed = []
        upgrade.write_config = lambda: None
        upgrade.run_on_terminal = lambda cmd: 0
        upgrade.ask_gate = lambda prompt, default="": "n"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            upgrade.prompt_smoke_public_url("db", baseline=True)
        self.assertIn("Before starting", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            upgrade.prompt_smoke_public_url("db")
        self.assertNotIn("Before starting", out.getvalue())

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
