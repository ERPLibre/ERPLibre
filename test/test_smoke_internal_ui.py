#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ouvrir le back-office comme quelqu'un qui s'y connecte.

Le test de fumée public ouvre ce qu'un visiteur atteint. Il ne dit RIEN du
back-office, où une migration fait pourtant l'essentiel de ses dégâts : un
champ retiré du modèle mais toujours nommé dans un formulaire, un modèle
dont le code n'accompagne plus la version cible. Rien de tout cela n'arrête
le chargement des modules ; cela arrête le jour où quelqu'un ouvre l'appli.

Ce que ces tests verrouillent est ce que l'exécution réelle a corrigé — et
chaque point ci-dessous a d'abord été un vrai défaut, mesuré sur une base
18.0 de 25 applications :

- `web_search_read` a changé de signature en 17 (`fields` est devenu
  `specification`). Seize applications sur vingt-deux échouaient sur MON
  appel. `search_read` n'a pas bougé depuis la 12 ;
- un modèle absent du registre rend un « 404 Not Found » nu, illisible,
  alors que c'est la trouvaille la plus nette d'une migration ;
- lire les champs d'un arch à l'expression régulière ramasse ceux des
  SOUS-VUES : neuf applications rapportées « nommant un champ absent »,
  toutes fausses, parce que les lignes d'une facture ne sont pas des
  champs de la facture ;
- `run_psql` rend une liste vide aussi bien pour « aucune ligne » que pour
  « requête refusée » : un SQL fautif faisait dire « base non neutralisée ».
"""

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "script", "odoo", "migration"))

import smoke_internal_ui as ui  # noqa: E402


class TestFindingTheFirstPageOfEachApp(unittest.TestCase):
    """Ce que le client web ouvre au clic : le premier menu avec une action."""

    MENUS = [
        {
            "id": 1,
            "name": "Ventes",
            "parent_id": False,
            "sequence": 10,
            "action": False,
        },
        {
            "id": 2,
            "name": "Commandes",
            "parent_id": [1, "Ventes"],
            "sequence": 5,
            "action": False,
        },
        {
            "id": 3,
            "name": "Devis",
            "parent_id": [2, "Commandes"],
            "sequence": 1,
            "action": "ir.actions.act_window,42",
        },
        {
            "id": 4,
            "name": "Clients",
            "parent_id": [1, "Ventes"],
            "sequence": 9,
            "action": "ir.actions.act_window,43",
        },
        {
            "id": 5,
            "name": "Réglages",
            "parent_id": False,
            "sequence": 99,
            "action": "ir.actions.act_window,7",
        },
        {
            "id": 6,
            "name": "Vide",
            "parent_id": False,
            "sequence": 50,
            "action": False,
        },
    ]

    def test_it_descends_to_the_first_actionable_menu(self):
        trouve = dict(
            (app["name"], first["name"] if first else None)
            for app, first in ui.apps(self.MENUS)
        )
        self.assertEqual(trouve["Ventes"], "Devis")

    def test_sequence_decides_not_the_id(self):
        # « Commandes » (5) passe avant « Clients » (9) : l'ordre affiché
        # est celui que l'utilisateur voit, pas l'ordre d'insertion.
        trouve = dict(
            (app["name"], first["name"] if first else None)
            for app, first in ui.apps(self.MENUS)
        )
        self.assertNotEqual(trouve["Ventes"], "Clients")

    def test_an_app_carrying_its_own_action_is_its_own_first_page(self):
        trouve = dict(
            (app["name"], first["name"] if first else None)
            for app, first in ui.apps(self.MENUS)
        )
        self.assertEqual(trouve["Réglages"], "Réglages")

    def test_an_app_without_any_action_is_not_an_error(self):
        # Elle n'a rien à ouvrir. La compter comme un échec ferait chercher
        # un dégât là où il n'y a qu'un menu de regroupement.
        trouve = dict(
            (app["name"], first["name"] if first else None)
            for app, first in ui.apps(self.MENUS)
        )
        self.assertIsNone(trouve["Vide"])

    def test_a_menu_loop_does_not_hang(self):
        # Une base migrée porte parfois des données incohérentes ; un
        # parcours naïf tournerait indéfiniment sans rien dire.
        boucle = [
            {
                "id": 1,
                "name": "A",
                "parent_id": False,
                "sequence": 1,
                "action": False,
            },
            {
                "id": 2,
                "name": "B",
                "parent_id": [1, "A"],
                "sequence": 1,
                "action": False,
            },
            {
                "id": 3,
                "name": "C",
                "parent_id": [2, "B"],
                "sequence": 1,
                "action": False,
            },
        ]
        boucle[0]["parent_id"] = [3, "C"]
        self.assertIsInstance(ui.apps(boucle), list)


class TestReadingTheFieldsOfAPage(unittest.TestCase):
    """Les champs de la page, et RIEN de ce qui appartient aux sous-vues."""

    FORM = {
        "views": {
            "form": {
                "arch": (
                    "<form>"
                    '<field name="partner_id"/>'
                    '<field name="line_ids">'
                    '<list><field name="product_id"/>'
                    '<field name="price_unit"/></list>'
                    "</field>"
                    '<field name="amount_total"/>'
                    "</form>"
                )
            }
        }
    }

    def test_the_top_level_fields_are_taken(self):
        self.assertEqual(
            ui.arch_fields(self.FORM),
            ["partner_id", "line_ids", "amount_total"],
        )

    def test_the_fields_of_an_embedded_view_are_NOT(self):
        # Le défaut mesuré : `product_id` et `price_unit` sont des champs de
        # la LIGNE de facture. Les attribuer à la facture faisait rapporter
        # neuf applications cassées qui allaient parfaitement bien.
        lst = ui.arch_fields(self.FORM)
        self.assertNotIn("product_id", lst)
        self.assertNotIn("price_unit", lst)

    def test_a_dotted_name_is_left_alone(self):
        views = {"a": {"arch": '<list><field name="partner_id.name"/></list>'}}
        self.assertEqual(ui.arch_fields(views), [])

    def test_an_unreadable_arch_yields_nothing_rather_than_nonsense(self):
        views = {"a": {"arch": "<form><field name='x'"}}
        self.assertEqual(ui.arch_fields(views), [])

    def test_it_finds_arch_wherever_the_version_put_it(self):
        # `views` en 16+, `fields_views` avant : chercher à plat évite de
        # tenir deux chemins en dur qui dérivent l'un de l'autre.
        ancien = {
            "fields_views": {
                "list": {"arch": '<list><field name="x"/></list>'}
            }
        }
        self.assertEqual(ui.arch_fields(ancien), ["x"])


class TestTheThreeStatesOfTheTestUser(unittest.TestCase):
    """« je ne sais pas » n'est pas « il n'y en a pas ».

    Vécu : un « id » ambigu dans MON SQL faisait rendre une liste vide, et
    l'outil annonçait tranquillement que la base n'avait pas été
    neutralisée. Le back-office n'était pas testé, et rien ne le disait.
    """

    def test_a_row_saying_one_is_present(self):
        self.assertEqual(
            ui.user_state("db", run_psql=lambda d, s: [["1"]]), "present"
        )

    def test_a_row_saying_zero_is_absent(self):
        self.assertEqual(
            ui.user_state("db", run_psql=lambda d, s: [["0"]]), "absent"
        )

    def test_no_row_at_all_is_unknown(self):
        self.assertEqual(
            ui.user_state("db", run_psql=lambda d, s: []), "unknown"
        )

    def test_a_psql_that_raises_is_unknown(self):
        def explose(database, sql):
            raise OSError("psql absent")

        self.assertEqual(ui.user_state("db", run_psql=explose), "unknown")

    def test_it_counts_rather_than_selects(self):
        # Un COUNT rend TOUJOURS une ligne quand la requête aboutit : c'est
        # ce qui sépare « aucun utilisateur » de « requête refusée ».
        vu = {}
        ui.user_state(
            "db", run_psql=lambda d, s: vu.setdefault("sql", s) and []
        )
        self.assertIn("count(", vu["sql"].lower())


class TestTellingRealBreakageFromNoise(unittest.TestCase):
    def test_a_bare_404_means_the_model_is_not_registered(self):
        # Le message d'Odoo — « 404 Not Found: The requested URL... » — ne
        # dit rien. Ce qu'il faut savoir : le module est installé dans la
        # base et son code manque à cette version.
        self.assertTrue(
            ui.model_is_unregistered({"name": "werkzeug.exceptions.NotFound"})
        )

    def test_an_access_error_is_not_that(self):
        self.assertFalse(
            ui.model_is_unregistered({"name": "odoo.exceptions.AccessError"})
        )

    def test_a_missing_method_is_recognised(self):
        self.assertTrue(
            ui._is_missing_method(
                {
                    "name": "builtins.AttributeError",
                    "message": "object has no attribute 'load_views'",
                }
            )
        )

    def test_a_real_failure_is_not_mistaken_for_one(self):
        # Retomber sur l'ancien nom de méthode après une vraie panne
        # masquerait la panne derrière un « méthode inconnue » sans rapport.
        self.assertFalse(
            ui._is_missing_method(
                {"name": "odoo.exceptions.AccessError", "message": "refusé"}
            )
        )


class TestNotEvaluatingWhatComesFromTheDatabase(unittest.TestCase):
    """Un domaine d'action est parfois du Python. On ne l'exécute pas."""

    def test_a_literal_domain_is_used(self):
        self.assertEqual(
            ui.literal("[('a','=',1)]", []), ([("a", "=", 1)], False)
        )

    def test_an_expression_falls_back_and_SAYS_so(self):
        # `uid`, `context_today` : seul le navigateur sait les évaluer. Le
        # second membre du couple est ce qui permet de le dire au rapport
        # au lieu de faire passer une approximation pour une mesure.
        valeur, approx = ui.literal("[('user_id','=',uid)]", [])
        self.assertEqual(valeur, [])
        self.assertTrue(approx)

    def test_an_empty_domain_is_not_an_approximation(self):
        self.assertEqual(ui.literal("[]", []), ([], False))


class TestWhatIsWorthOpening(unittest.TestCase):
    def test_a_window_action_is_split(self):
        self.assertEqual(
            ui.split_action("ir.actions.act_window,42"),
            ("ir.actions.act_window", 42),
        )

    def test_a_server_action_is_recognised_and_left_alone(self):
        session = object()
        app = {"id": 1, "name": "X"}
        menu = {"id": 2, "name": "Y", "action": "ir.actions.server,9"}
        # Une action serveur ÉCRIT : l'exécuter pour « voir si ça marche »
        # ferait justement ce qu'un test ne doit pas faire.
        result = ui.check_entry(session, app, menu)
        self.assertEqual(result["kind"], "ir.actions.server")
        self.assertIsNone(result["error"])
        self.assertIsNone(result["model"])

    def test_qweb_is_not_a_page_to_open(self):
        self.assertEqual(
            ui.view_pairs("list,qweb,form"), [[False, "list"], [False, "form"]]
        )

    def test_no_view_mode_still_gives_something(self):
        self.assertTrue(ui.view_pairs(None))


class TestLoadingTheFirstPage(unittest.TestCase):
    """L'appel qui charge les enregistrements, et sa forme exacte.

    C'EST le défaut qui a coûté le plus cher : `web_search_read` a changé
    de signature en 17 — `fields`, une liste, est devenu `specification`,
    un dictionnaire. Mesuré sur une base 18.0 : seize applications sur
    vingt-deux échouaient sur « unexpected keyword argument 'fields' »,
    c'est-à-dire sur MON appel et non sur la base. `search_read` n'a pas
    bougé depuis la 12.
    """

    def call(self, lst_field=None):
        session = ui.Session("http://x")
        vu = {}

        def faux(model, method, args, kwargs=None):
            vu.update(
                model=model, method=method, args=args, kwargs=kwargs or {}
            )
            return [], None

        session.call_kw = faux
        session.first_page("sale.order", [], {}, 20, lst_field=lst_field)
        return vu

    def test_it_uses_the_call_that_never_changed(self):
        self.assertEqual(self.call(["name"])["method"], "search_read")

    def test_the_fields_go_where_search_read_expects_them(self):
        vu = self.call(["name", "partner_id"])
        self.assertEqual(vu["args"], [[], ["name", "partner_id"]])
        self.assertEqual(vu["kwargs"]["limit"], 20)

    def test_without_fields_it_still_loads_something(self):
        self.assertEqual(self.call()["args"][1], ["display_name"])

    def test_the_page_reads_the_columns_it_shows(self):
        # Lire `display_name` seul ne prouverait presque rien : ce sont les
        # colonnes de la liste qui font travailler l'ORM, et c'est là qu'un
        # champ calculé cassé par la migration se manifeste.
        import inspect

        source = inspect.getsource(ui.check_entry)
        self.assertIn("arch_fields(views)", source)
        self.assertIn("lst_field=lst_read", source)

    def test_a_field_the_model_lacks_is_never_requested(self):
        # Le demander ferait échouer la lecture par NOTRE faute, et l'on
        # perdrait le vrai signal derrière une erreur qu'on a causée.
        source = __import__("inspect").getsource(ui.check_entry)
        self.assertIn("if name in lst_known", source)


class TestTheViewsAreRenderedServerSide(unittest.TestCase):
    def test_it_tries_the_modern_name_then_the_old_one(self):
        # get_views depuis la 16, load_views avant, et la 18 n'a plus que le
        # premier : une seule des deux ne couvrirait pas 12→18.
        import inspect

        source = inspect.getsource(ui.Session.views_of)
        self.assertIn("get_views", source)
        self.assertIn("load_views", source)
        self.assertLess(source.index("get_views"), source.index("load_views"))

    def test_the_resolved_name_is_remembered(self):
        # Chercher à chaque application doublerait le nombre de requêtes.
        session = ui.Session("http://x")
        appels = []

        def faux(model, method, args, kwargs=None):
            appels.append(method)
            if method == "get_views":
                return None, {
                    "name": "builtins.AttributeError",
                    "message": "has no attribute",
                }
            return {"views": {}}, None

        session.call_kw = faux
        session.views_of("m", [[False, "list"]])
        session.views_of("m", [[False, "list"]])
        self.assertEqual(appels, ["get_views", "load_views", "load_views"])


class TestASkipThatHidesAFailure(unittest.TestCase):
    """Tous les sauts ne se valent pas, et c'est mesuré.

    L'utilisateur `test` survit aux paliers 12 à 15 puis DISPARAÎT : relevé
    sur les six bases d'une vraie migration, présent jusqu'à 15, absent en
    17 et 18. La passe back-office s'arrêtait donc sans bruit exactement là
    où une migration fait le plus de dégâts, et le rapport disait
    tranquillement « la base n'a pas été neutralisée » — ce qui était faux.

    `required` porte ce que la migration SAIT : elle a neutralisé cette
    base, le compte devrait y être. Son absence devient alors une
    trouvaille, pas une formalité.
    """

    def setUp(self):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"
        import smoke_public_url

        self.public = smoke_public_url
        original = smoke_public_url.run_psql
        self.addCleanup(setattr, smoke_public_url, "run_psql", original)

    def phase(self, rows, **kw):
        self.public.run_psql = lambda db, sql: rows
        return self.public.internal_phase("http://x", "db", enabled=True, **kw)

    def test_no_user_on_a_plain_database_is_a_quiet_skip(self):
        rapport = self.phase([["0"]])
        self.assertIn("not neutralized", rapport["skipped"])
        self.assertFalse(rapport.get("loud"))

    def test_no_user_on_a_NEUTRALIZED_database_is_a_finding(self):
        rapport = self.phase([["0"]], required=True)
        self.assertIn("NOT checked", rapport["skipped"])
        self.assertTrue(rapport["loud"])

    def test_a_finding_counts_as_a_failure(self):
        # Sinon le code de sortie annonce que tout va bien alors que le
        # back-office n'a jamais été ouvert.
        import contextlib
        import io

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            echec = self.public.render_internal(
                {"skipped": "disparu", "loud": True}
            )
        self.assertTrue(echec)
        self.assertIn("NOT browsed", out.getvalue())

    def test_a_quiet_skip_does_not(self):
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(
                self.public.render_internal({"skipped": "pas neutralisée"})
            )

    def test_an_unreadable_database_is_never_silent(self):
        rapport = self.phase([])
        self.assertTrue(rapport["loud"])

    def test_a_missing_tool_is_never_silent(self):
        # `except ImportError: return None` faisait disparaître la passe
        # ENTIÈRE sans un mot, et l'on croyait le back-office testé.
        import inspect

        source = inspect.getsource(self.public.internal_phase)
        debut = source.index("except ImportError")
        self.assertIn("loud", source[debut : debut + 400])

    def test_the_migration_asks_for_it_when_it_neutralized(self):
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.prompt_smoke_public_url)
        self.assertIn("--internal-required", source)
        self.assertIn('"_neutralize" in database_name', source)

    def test_the_migration_says_UP_FRONT_what_will_be_browsed(self):
        # Un saut annoncé en une ligne à la fin d'un long rapport ne se
        # voit pas : on croit alors le back-office testé.
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.prompt_smoke_public_url)
        self.assertLess(
            source.index("Public pages only:"),
            source.index("run_tool("),
        )


class TestThePortalPage(unittest.TestCase):
    """/my n'est ni le site public ni le back-office : c'est un troisième
    rendu, en QWeb frontend, avec ses compteurs qui interrogent chacun leur
    modèle. Le sitemap ne le liste pas — la page demande une session — et
    aucun appel RPC ne passe par là. Une migration peut donc le casser sans
    que rien ailleurs ne le dise.
    """

    def setUp(self):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def session(self, status, body, url=None):
        session = ui.Session("http://x")
        session.last_url = url or ("http://x/my")

        def faux(path, data=None, headers=None):
            return status, body

        session.open = faux
        return session

    def test_a_page_that_answers_is_a_success(self):
        item = ui.check_portal(
            self.session(200, "<html>Mon compte</html>"), "/my"
        )
        self.assertIsNone(item["error"])
        self.assertEqual(item["status"], 200)

    def test_a_five_hundred_is_a_failure(self):
        item = ui.check_portal(self.session(500, "<html>oups</html>"), "/my")
        self.assertEqual(item["stage"], ui.PORTAL_KIND)
        self.assertIn("500", item["error"]["name"])

    def test_a_dead_connection_is_a_failure(self):
        item = ui.check_portal(self.session(0, "connexion refusée"), "/my")
        self.assertIsNotNone(item["error"])

    def test_a_login_form_served_with_200_is_NOT_a_success(self):
        # MESURÉ : /my demandé sans session redirige vers
        # /web/login?redirect=/my et rend 200. Compter cela comme une
        # réussite serait le mensonge le plus coûteux du lot — on
        # annoncerait un portail sain sans l'avoir jamais vu.
        page = '<form><input name="login"/><input name="password"/></form>'
        item = ui.check_portal(self.session(200, page), "/my")
        self.assertIsNotNone(item["error"])

    def test_a_redirect_to_the_login_is_caught_even_without_the_form(self):
        item = ui.check_portal(
            self.session(
                200, "<html>rien</html>", url="http://x/web/login?redirect=/my"
            ),
            "/my",
        )
        self.assertIsNotNone(item["error"])

    def test_the_word_login_alone_does_not_condemn_a_page(self):
        # Le mot est partout dans le portail. N'exiger que lui rejetterait
        # des pages parfaitement saines.
        page = "<html>Votre login est test. Bienvenue.</html>"
        item = ui.check_portal(self.session(200, page), "/my")
        self.assertIsNone(item["error"])

    def test_the_error_page_is_read_without_its_stylesheet(self):
        # MESURÉ : « Internal Server Error html { font-size: 14px; } Home
        # Back 500 » — du CSS présenté comme un diagnostic.
        page = (
            "<html><style>html { font-size: 14px; }</style>"
            "<body>500: Internal Server Error</body></html>"
        )
        self.assertNotIn("font-size", ui.error_from_page(page))

    def test_it_is_checked_before_the_apps(self):
        # L'ordre n'est pas indifférent : si la session est perdue, tout le
        # reste échouera aussi, et l'on veut la cause en tête du rapport.
        import inspect

        source = inspect.getsource(ui.crawl)
        self.assertLess(
            source.index("check_portal"), source.index("check_entry")
        )

    def test_asking_for_no_portal_path_checks_none(self):
        session = self.session(200, "ok")
        session.call_kw = lambda *a, **kw: ([], None)
        lst_result, _ = ui.crawl(session, lst_portal=[])
        self.assertEqual(
            [x for x in lst_result if x["kind"] == ui.PORTAL_KIND], []
        )

    def test_the_default_path_is_my(self):
        self.assertEqual(ui.DEFAULT_PORTAL_PATHS, ("/my",))


class TestBlamingTheRightRequest(unittest.TestCase):
    """Une cause fausse coûte plus cher qu'une cause absente.

    Vécu : le portail est interrogé en PREMIER, donc sa trace est la
    première du journal. En prenant simplement la dernière, on accusait /my
    d'une panne appartenant à une application testée bien après — et l'on
    aurait cherché des heures du mauvais côté, avec confiance.
    """

    JOURNAL = [
        "AttributeError: 'res.users' object has no attribute 'portal_360'",
        '... werkzeug: "GET /my HTTP/1.1" 500 - 8 0.004 0.029',
        "ValueError: Invalid field project.project.is_project_br",
        '... werkzeug: "POST /web/dataset/call_kw HTTP/1.1" 200 - 3 0.01',
    ]

    def test_the_trace_of_that_very_request_is_taken(self):
        self.assertIn("portal_360", ui.reason_for_path(self.JOURNAL, "/my"))

    def test_the_trace_of_another_request_is_NOT(self):
        self.assertNotIn(
            "is_project_br", ui.reason_for_path(self.JOURNAL, "/my") or ""
        )

    def test_a_healthy_answer_wipes_the_slate(self):
        journal = [
            "ValueError: sans rapport",
            '... werkzeug: "GET /my HTTP/1.1" 200 - 8 0.004',
        ]
        self.assertIsNone(ui.reason_for_path(journal, "/my"))

    def test_a_redirected_path_still_matches(self):
        # /my renvoie vers /my/home : la trace est loggée sous le second.
        journal = [
            "KeyError: compteur",
            '... werkzeug: "GET /my/home HTTP/1.1" 500 - 8 0.004',
        ]
        self.assertIn("KeyError", ui.reason_for_path(journal, "/my"))

    def test_a_similar_path_is_not_confused_with_it(self):
        journal = [
            "KeyError: ailleurs",
            '... werkzeug: "GET /myaccount HTTP/1.1" 500 - 8 0.004',
        ]
        self.assertIsNone(ui.reason_for_path(journal, "/my"))

    def test_an_rpc_message_is_never_overwritten(self):
        # Un appel RPC nomme précisément SON erreur ; le journal est un flux
        # partagé. Écraser le premier par le second serait perdre la seule
        # information sûre.
        item = ui.blank_entry("Ventes", "Devis", kind="ir.actions.act_window")
        item["error"] = {"name": "KeyError", "message": "précis"}
        ui.attach_log_reason(
            [item], ["ValueError: du journal", '"GET /my" 500']
        )
        self.assertNotIn("log", item["error"])

    def test_the_server_is_asked_to_log_its_requests(self):
        # Sans les lignes d'accès, aucune trace ne peut être rattachée à un
        # chemin : elles coûtent deux lignes par requête.
        import inspect

        import smoke_public_url as public

        self.assertIn("werkzeug:INFO", inspect.getsource(public.start_server))


class TestTheReport(unittest.TestCase):
    def setUp(self):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def entry(self, **kw):
        item = {
            "app": "Sales",
            "menu": "Quotations",
            "model": "sale.order",
            "kind": "ir.actions.act_window",
            "error": None,
            "stage": None,
            "domain_ignored": False,
            "unknown_fields": [],
            "fields_read": 3,
        }
        item.update(kw)
        return item

    def test_all_clean_says_so(self):
        text = ui.render([self.entry()], [])
        self.assertIn("1/1", text)
        self.assertIn("opened its first page", text)

    def test_a_registry_failure_explains_itself(self):
        # Le 404 nu est illisible : le rapport doit dire ce qu'il signifie.
        item = self.entry(
            stage="registry",
            error={"name": "werkzeug.exceptions.NotFound", "message": "404"},
        )
        text = ui.render([item], [item])
        self.assertIn("addons path", text)
        self.assertNotIn("The requested URL", text)

    def test_ghost_fields_are_reported_without_being_a_failure(self):
        # Une vue qui nomme un champ disparu n'empêche pas toujours la page
        # de s'ouvrir. Le taire laisserait passer la cause d'une panne à
        # venir ; le compter comme un échec ferait crier au loup.
        item = self.entry(unknown_fields=["grant_offer_id"])
        text = ui.render([item], [])
        self.assertIn("grant_offer_id", text)
        self.assertIn("1/1", text)

    def test_an_approximate_domain_is_admitted(self):
        text = ui.render([self.entry(domain_ignored=True)], [])
        self.assertIn("empty domain", text)

    def test_the_report_says_the_public_test_cannot_see_this(self):
        item = self.entry(
            stage="records", error={"name": "KeyError", "message": "x"}
        )
        text = ui.render([item], [item])
        self.assertIn(
            "back-office", text.lower().replace("back office", "back-office")
        )


class TestItRidesTheServerAlreadyRunning(unittest.TestCase):
    """Le démarrage d'Odoo coûte des minutes ; les requêtes, non."""

    def test_the_public_tool_runs_it_in_the_same_session(self):
        import inspect

        import smoke_public_url as public

        source = inspect.getsource(public.run)
        debut = source.index("check_urls(")
        arret = source.index("stop_server(server)")
        self.assertLess(debut, source.index("internal_phase("))
        self.assertLess(source.index("internal_phase("), arret)

    def test_an_unknown_state_is_not_reported_as_healthy(self):
        import smoke_public_url as public

        rapport = public.internal_phase("http://x", "db", enabled=True)
        self.assertIsNotNone(rapport)

    def test_disabling_it_returns_nothing(self):
        import smoke_public_url as public

        self.assertIsNone(
            public.internal_phase("http://x", "db", enabled=False)
        )


if __name__ == "__main__":
    unittest.main()
