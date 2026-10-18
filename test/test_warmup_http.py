#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le réveil HTTP : il doit se taire, et ne jamais gêner.

Cette sonde tourne à côté du serveur, pas devant lui. Tout ce qu'elle
peut faire de mal, elle le ferait en parlant : un message d'erreur dans
le journal de `run.sh` ferait chercher une panne d'Odoo qui n'existe pas,
et un code de retour non nul ferait échouer un démarrage réussi.

D'où les deux propriétés que ce fichier épingle avant les autres : elle
rend TOUJOURS 0, et elle n'écrit qu'une ligne — l'adresse choisie, parce
que c'est la seule chose qui permette de comprendre après coup un réveil
qui n'a pas eu lieu.

Le troisième sujet est l'option elle-même. `--erplibre-disable-warmup-http`
doit être RETIRÉE avant `odoo_bin.sh` : Odoo meurt sur « no such option »,
et le démarrage entier tombe pour un confort.

Le mode profond (`--deep`) se joue sur un faux Odoo HTTP local
(`fake_odoo_http`, 127.0.0.1) : pages, sitemap, assets et /jsonrpc.
Aucun accès au réseau extérieur ; les URL du sitemap nomment un domaine
inventé, qui ne doit jamais être contacté.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_odoo_http import FauxOdoo  # noqa: E402

from script.odoo import health_check  # noqa: E402
from script.odoo import warmup_http as warmup  # noqa: E402

RUN_SH = Path(__file__).resolve().parent.parent / "run.sh"


class TestWhereItKnocks(unittest.TestCase):
    """Le port, dans l'ordre de ce qui fait autorité."""

    def test_the_command_line_wins_over_everything(self):
        for argv in (
            ["-p", "8090"],
            ["--http-port", "8090"],
            ["--http-port=8090"],
        ):
            self.assertEqual(warmup.port_de_la_ligne(argv), 8090, argv)

    def test_a_port_that_is_not_a_number_is_ignored(self):
        self.assertIsNone(warmup.port_de_la_ligne(["-p", "huit-mille"]))
        self.assertIsNone(warmup.port_de_la_ligne(["-p"]))

    def test_without_anything_it_falls_back_on_the_default(self):
        vrai = warmup.lib_analyse.read_config
        warmup.lib_analyse.read_config = lambda *a, **k: {}
        try:
            self.assertEqual(
                warmup.adresse(),
                (warmup.HOTE_PAR_DEFAUT, warmup.PORT_PAR_DEFAUT),
            )
        finally:
            warmup.lib_analyse.read_config = vrai

    def test_an_empty_interface_means_ourselves(self):
        """`http_interface =` veut dire « toutes » ; 0.0.0.0 n'est pas une
        adresse de destination."""
        vrai = warmup.lib_analyse.read_config
        for valeur in ("", "False", "0.0.0.0", "::"):
            warmup.lib_analyse.read_config = lambda *a, v=valeur, **k: {
                "http_interface": v
            }
            try:
                self.assertEqual(warmup.adresse()[0], "127.0.0.1", valeur)
            finally:
                warmup.lib_analyse.read_config = vrai

    def test_a_real_interface_is_used_as_is(self):
        vrai = warmup.lib_analyse.read_config
        warmup.lib_analyse.read_config = lambda *a, **k: {
            "http_interface": "10.0.0.5",
            "http_port": "8071",
        }
        try:
            self.assertEqual(warmup.adresse(), ("10.0.0.5", 8071))
        finally:
            warmup.lib_analyse.read_config = vrai

    def test_the_old_xmlrpc_port_name_is_read_too(self):
        vrai = warmup.lib_analyse.read_config
        warmup.lib_analyse.read_config = lambda *a, **k: {
            "xmlrpc_port": "7069",
        }
        try:
            self.assertEqual(warmup.adresse(journal="/nonexistent")[1], 7069)
        finally:
            warmup.lib_analyse.read_config = vrai


class TestReadingTheExecutionLog(unittest.TestCase):
    """La seule source exacte quand le port demandé était déjà pris."""

    def _journal(self, contenu):
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, encoding="utf-8"
        )
        handle.write(contenu)
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return handle.name

    def test_it_reads_the_address_odoo_announced(self):
        chemin = self._journal(
            "blah\nHTTP service (werkzeug) running on 127.0.0.1:8075\nblah\n"
        )
        self.assertEqual(
            warmup.adresse_du_journal(chemin), ("127.0.0.1", 8075)
        )

    def test_the_last_line_wins(self):
        """Un redémarrage laisse les deux ; la dernière est la vraie."""
        chemin = self._journal(
            "HTTP service (werkzeug) running on 127.0.0.1:8069\n"
            "HTTP service (werkzeug) running on 127.0.0.1:8070\n"
        )
        self.assertEqual(warmup.adresse_du_journal(chemin)[1], 8070)

    def test_a_missing_or_silent_log_says_nothing(self):
        self.assertEqual(warmup.adresse_du_journal(None), (None, None))
        self.assertEqual(warmup.adresse_du_journal("/pas/la"), (None, None))
        self.assertEqual(
            warmup.adresse_du_journal(self._journal("rien\n")), (None, None)
        )

    def test_the_command_line_still_wins_over_the_log(self):
        chemin = self._journal(
            "HTTP service (werkzeug) running on 127.0.0.1:8075\n"
        )
        self.assertEqual(
            warmup.adresse(["-p", "8090"], journal=chemin)[1], 8090
        )


class TestWhichDatabase(unittest.TestCase):
    def test_the_one_run_sh_just_chose(self):
        self.assertEqual(warmup.base_a_reveiller(["-d", "ma_base"]), "ma_base")
        self.assertEqual(
            warmup.base_a_reveiller(["--database=ma_base"]), "ma_base"
        )

    def test_otherwise_the_one_odoo_would_use(self):
        vrai = warmup.lib_analyse.read_config
        warmup.lib_analyse.read_config = lambda *a, **k: {"db_name": "prod"}
        try:
            self.assertEqual(warmup.base_a_reveiller([]), "prod")
        finally:
            warmup.lib_analyse.read_config = vrai

    def test_db_name_false_is_not_a_database(self):
        vrai = warmup.lib_analyse.read_config
        for valeur in ("False", "", "None"):
            warmup.lib_analyse.read_config = lambda *a, v=valeur, **k: {
                "db_name": v
            }
            try:
                self.assertIsNone(warmup.base_a_reveiller([]), valeur)
            finally:
                warmup.lib_analyse.read_config = vrai

    def test_the_name_is_escaped_in_the_url(self):
        self.assertIn("db=ma%20base", warmup.url("127.0.0.1", 8069, "ma base"))

    def test_without_a_database_the_url_carries_no_parameter(self):
        self.assertEqual(
            warmup.url("127.0.0.1", 8069), "http://127.0.0.1:8069/web/login"
        )


class TestWhenItStops(unittest.TestCase):
    """N'importe quelle réponse suffit ; seul le refus fait recommencer."""

    def _sonder(self, reponses, delai=10.0):
        import urllib.error
        import urllib.request

        essais = []
        temps = [0.0]

        def faux_urlopen(cible, timeout=None):
            essais.append(cible)
            resultat = (
                reponses.pop(0) if reponses else ConnectionRefusedError()
            )
            if isinstance(resultat, Exception):
                raise resultat
            return io.BytesIO(b"")

        vrai = urllib.request.urlopen
        urllib.request.urlopen = faux_urlopen
        try:
            venu = warmup.sonder(
                "http://x",
                delai_total=delai,
                entre_essais=0,
                horloge=lambda: temps[0],
                dormir=lambda s: temps.__setitem__(0, temps[0] + 1),
            )
        finally:
            urllib.request.urlopen = vrai
        return venu, essais

    def test_a_first_answer_ends_it(self):
        venu, essais = self._sonder([None])
        self.assertTrue(venu)
        self.assertEqual(len(essais), 1)

    def test_an_http_error_is_an_answer(self):
        """303, 404, 500 : tous prouvent que le registre est chargé."""
        import urllib.error

        erreur = urllib.error.HTTPError("u", 500, "boom", {}, None)
        venu, essais = self._sonder([erreur])
        self.assertTrue(venu)
        self.assertEqual(len(essais), 1)

    def test_a_refused_connection_makes_it_try_again(self):
        venu, essais = self._sonder([ConnectionRefusedError(), None])
        self.assertTrue(venu)
        self.assertEqual(len(essais), 2)

    def test_it_gives_up_at_the_deadline(self):
        venu, essais = self._sonder([], delai=5.0)
        self.assertFalse(venu)
        self.assertEqual(len(essais), 5)

    def test_the_default_deadline_is_two_minutes(self):
        self.assertEqual(warmup.DELAI_TOTAL, 120.0)


class TestItNeverGetsInTheWay(unittest.TestCase):
    """La propriété qui compte le plus : elle ne peut pas nuire."""

    def test_it_always_returns_zero(self):
        vrai = warmup.sonder
        warmup.sonder = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("x")
        )
        try:
            self.assertEqual(warmup.main(["--quiet"]), 0)
        finally:
            warmup.sonder = vrai

    def test_a_broken_config_does_not_stop_it(self):
        vrai = warmup.lib_analyse.read_config
        warmup.lib_analyse.read_config = lambda *a, **k: (_ for _ in ()).throw(
            OSError("illisible")
        )
        try:
            self.assertEqual(warmup.main(["--quiet"]), 0)
        finally:
            warmup.lib_analyse.read_config = vrai

    def test_it_announces_the_address_it_chose(self):
        """La seule ligne qu'elle écrit, et celle qui rend le silence
        compréhensible plus tard."""
        import contextlib

        vrai = warmup.sonder
        warmup.sonder = lambda *a, **k: True
        sortie = io.StringIO()
        try:
            with contextlib.redirect_stdout(sortie):
                warmup.main(["-d", "ma_base", "--", "-p", "8090"])
        finally:
            warmup.sonder = vrai
        texte = sortie.getvalue()
        self.assertEqual(len(texte.strip().splitlines()), 1)
        self.assertIn("ma_base", texte)

    def test_an_option_it_does_not_know_cannot_kill_it(self):
        """Les arguments d'Odoo nous traversent : l'un d'eux ressemblera un
        jour à une option inconnue, et `parse_args` sortirait par SystemExit.
        """
        vrai = warmup.sonder
        warmup.sonder = lambda *a, **k: True
        try:
            self.assertEqual(warmup.main(["--quiet", "--option-a-odoo"]), 0)
        finally:
            warmup.sonder = vrai

    def test_quiet_says_nothing_at_all(self):
        import contextlib

        vrai = warmup.sonder
        warmup.sonder = lambda *a, **k: True
        sortie = io.StringIO()
        try:
            with contextlib.redirect_stdout(sortie):
                warmup.main(["--quiet"])
        finally:
            warmup.sonder = vrai
        self.assertEqual(sortie.getvalue(), "")


class TestHowRunShWiresIt(unittest.TestCase):
    """Une option qu'Odoo ne connaît pas le tue au démarrage."""

    @classmethod
    def setUpClass(cls):
        cls.source = RUN_SH.read_text(encoding="utf-8")

    def test_the_flag_is_stripped_and_never_forwarded(self):
        bloc = self.source[
            self.source.index("--erplibre-disable-warmup-http)") :
        ][:120]
        self.assertNotIn("EL_ARGS+=", bloc)

    def test_no_http_disables_it_but_still_reaches_odoo(self):
        """Rien à réveiller, mais Odoo doit garder son option."""
        bloc = self.source[
            self.source.index("--no-http|--stop-after-init)") :
        ][:200]
        self.assertIn("EL_WARMUP=0", bloc)
        self.assertIn('EL_ARGS+=("$1")', bloc)

    def test_it_runs_in_parallel(self):
        lancement = [
            texte
            for texte in self.source.splitlines()
            if texte.strip().endswith("&") and "2>/dev/null" in texte
        ]
        self.assertTrue(lancement, "le réveil ne part pas en arrière-plan")

    def test_it_does_not_survive_the_server(self):
        self.assertIn("trap", self.source)
        self.assertIn("EL_WARMUP_PID", self.source)

    def test_its_own_errors_are_swallowed(self):
        self.assertIn("2>/dev/null &", self.source)

    def test_odoo_arguments_are_separated_by_a_double_dash(self):
        """Sans `--`, un « -c » destiné à Odoo serait lu comme le nôtre."""
        self.assertIn('-- "${EL_ARGS[@]}" 2>/dev/null &', self.source)


class TestDeepNeverChangesTheDefaultPath(unittest.TestCase):
    """`--deep` n'existe qu'avant `--` ; le mode par défaut garde sa
    promesse, même devant une option nouvelle tronquée ou invalide."""

    def setUp(self):
        for nom, valeur in (
            ("sonder", lambda *a, **k: True),
            ("prechauffer_profond", mock.Mock(side_effect=AssertionError)),
            ("principal_profond", mock.Mock(side_effect=AssertionError)),
        ):
            rustine = mock.patch.object(warmup, nom, valeur)
            rustine.start()
            self.addCleanup(rustine.stop)

    def jouer(self, argv):
        sortie = io.StringIO()
        with (
            contextlib.redirect_stdout(sortie),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            code = warmup.main(argv)
        return code, sortie.getvalue()

    def test_deep_after_the_double_dash_belongs_to_odoo(self):
        code, texte = self.jouer(["-c", "/nonexistent.conf", "--", "--deep"])
        self.assertEqual(code, 0)
        self.assertEqual(len(texte.strip().splitlines()), 1)
        self.assertIn("🔥 warmup: http://", texte)
        warmup.principal_profond.assert_not_called()

    def test_abbreviations_and_bad_values_return_zero(self):
        for argv in (
            ["--lo"],
            ["--quiet", "--de"],
            ["--quiet", "--timeout", "abc"],
            ["--quiet", "--repeat", "99"],
            ["--quiet", "--max-pages"],
            # `--deep` après `--` est à Odoo : une valeur invalide avant
            # lui ne doit pas donner le code d'usage du mode profond.
            ["--quiet", "--timeout", "abc", "--", "--deep"],
        ):
            with self.subTest(argv=argv):
                self.assertEqual(self.jouer(argv)[0], 0)


ASSET_JS = "/web/assets/u1/web.assets_frontend.min.js"
ASSET_CSS = "/web/assets/u1/web.assets_frontend.min.css?x=1&y=2"
ASSET_ANCIEN = "/web/content/12-ab/web.assets_common.js"
PAGE_LOGIN = (
    f'<html><script src="{ASSET_JS}"></script>'
    '<link rel="stylesheet" href="/web/assets/u1/'
    'web.assets_frontend.min.css?x=1&amp;y=2"/></html>'
)
PAGE_ACCUEIL = (
    f'<html><script src="{ASSET_JS}"></script>'
    f"<script src='{ASSET_ANCIEN}'></script>"
    '<a href="/web/content/99/attachment.pdf">pdf</a></html>'
)
SITEMAP = (
    "<urlset>"
    "<url><loc>https://www.example.org/page-a</loc></url>"
    "<url><loc>https://www.example.org/page-b</loc></url>"
    "<url><loc>https://www.example.org/logo.png</loc></url>"
    "<url><loc>https://www.example.org/page-a</loc></url>"
    "</urlset>"
)


def routes_publiques():
    def connexion(requete):
        entetes = {}
        if "db=base1" in requete.chemin:
            entetes["Set-Cookie"] = "session_id=s1; Path=/"
        return 200, entetes, PAGE_LOGIN

    return {
        "/web/login": connexion,
        "/": (200, {}, PAGE_ACCUEIL),
        "/sitemap.xml": (200, {}, SITEMAP),
        "/page-a": (200, {}, "<html>a</html>"),
        "/page-b": (500, {}, "boom"),
        ASSET_JS: (200, {}, "js" * 100000),
        "/web/assets/u1/web.assets_frontend.min.css": (200, {}, "css"),
        ASSET_ANCIEN: (200, {}, "js"),
    }


class TestDeepPublicPart(unittest.TestCase):
    def prechauffer(self, routes=None, **options):
        with FauxOdoo(routes or routes_publiques()) as serveur:
            bilan = warmup.prechauffer_profond(
                serveur.url, "base1", delai=10, **options
            )
            self.requetes = serveur.requetes
            self.port = serveur.port
        self.chemins = [r.chemin for r in self.requetes]
        return bilan

    def test_pages_sitemap_and_assets(self):
        bilan = self.prechauffer(repeat=2)
        self.assertEqual(self.chemins[0], "/web/login?db=base1")
        self.assertEqual(self.chemins.count("/page-a"), 2)
        self.assertEqual(self.chemins.count("/web/login"), 2)
        self.assertNotIn("/logo.png", self.chemins)
        self.assertEqual(bilan.pages, 4)
        self.assertEqual(bilan.assets, 3)
        self.assertEqual(self.chemins.count(ASSET_JS), 2)
        self.assertEqual(self.chemins.count(ASSET_CSS), 2)
        self.assertNotIn("/web/content/99/attachment.pdf", self.chemins)
        self.assertEqual(bilan.echecs, [("/page-b", 500)])
        self.assertEqual(bilan.non_publics, [])

    def test_nothing_goes_to_the_sitemap_domain(self):
        """Les `<loc>` nomment un AUTRE serveur local (localhost) : seul
        leur chemin part, vers la cible ; l'autre ne reçoit rien."""
        with FauxOdoo() as autre:
            ailleurs = f"http://localhost:{autre.port}"
            routes = routes_publiques()
            routes["/sitemap.xml"] = (
                200,
                {},
                f"<urlset><url><loc>{ailleurs}/page-a</loc></url></urlset>",
            )
            bilan = self.prechauffer(routes=routes, repeat=1)
            self.assertEqual(autre.requetes, [])
        self.assertIn("/page-a", self.chemins)
        self.assertEqual(bilan.pages, 3)
        for requete in self.requetes:
            self.assertNotIn("authorization", requete.entetes)

    def test_a_malformed_loc_is_dropped(self):
        """Collé derrière l'adresse de la cible, un `<loc>` qui ne commence
        pas par « / » en changerait le port ou l'hôte."""
        for loc in (
            ":9999/x",
            ".other.example/x",
            "@other.example/x",
            "other.example/x",
            "//other.example/x",
            "mailto:a@example.org",
        ):
            with self.subTest(loc=loc):
                self.assertIsNone(warmup.chemin_local(loc))
        self.assertEqual(warmup.chemin_local("/rel/x"), "/rel/x")
        self.assertEqual(warmup.chemin_local("https://www.example.org"), "/")
        routes = routes_publiques()
        routes["/sitemap.xml"] = (
            200,
            {},
            "<urlset><url><loc>:9999/page-a</loc></url>"
            "<url><loc>.other.example/page-a</loc></url>"
            "<url><loc>https://www.example.org/page-a</loc></url></urlset>",
        )
        bilan = self.prechauffer(routes=routes, repeat=1)
        self.assertEqual(bilan.pages, 3)
        self.assertEqual(self.chemins.count("/page-a"), 1)

    def test_a_redirection_to_another_host_is_not_followed(self):
        """La cible est locale et la clé d'API passe par ce client : une
        redirection vers un autre hôte est rendue (3xx), jamais suivie ;
        une redirection sur le même hôte l'est."""
        with FauxOdoo() as autre:
            routes = routes_publiques()
            routes["/page-a"] = (
                302,
                {"Location": f"http://localhost:{autre.port}/page-a"},
                "",
            )
            routes["/"] = (302, {"Location": "/fr/"}, "")
            routes["/fr/"] = (200, {}, PAGE_ACCUEIL)
            debut = time.monotonic()
            bilan = self.prechauffer(routes=routes, repeat=2)
            self.assertLess(time.monotonic() - debut, 5)
            with FauxOdoo(routes) as serveur:
                client = warmup.Client(serveur.url, 5)
                self.assertEqual(client.obtenir("/page-a"), (302, ""))
            self.assertEqual(autre.requetes, [])
        self.assertEqual(self.chemins.count("/page-a"), 2)
        self.assertIn("/fr/", self.chemins)
        self.assertEqual(bilan.echecs, [("/page-b", 500)])
        self.assertEqual(bilan.non_publics, [])
        # /fr/ cite l'asset ancien : la redirection a bien été suivie.
        self.assertIn(ASSET_ANCIEN, self.chemins)

    def test_repeats_run_at_the_same_time(self):
        """`--repeat` vise plusieurs workers : les requêtes d'une page, et
        les répétitions d'un asset après sa construction, arrivent
        ensemble. Une barrière qui casse au bout de 2 s rend 500 : servies
        l'une après l'autre, elles échoueraient toutes."""
        repeat = 3

        def barriere(nombre):
            mur = threading.Barrier(nombre, timeout=2)

            def route(_requete):
                try:
                    mur.wait()
                except threading.BrokenBarrierError:
                    return 500, {}, "seule"
                return 200, {}, "<html></html>"

            return route

        construits = []
        repetitions = barriere(repeat - 1)

        def asset(requete):
            with verrou:
                premier = not construits
                construits.append(requete.chemin)
            if premier:
                return 200, {}, "js"
            return repetitions(requete)

        verrou = threading.Lock()
        routes = routes_publiques()
        routes["/page-a"] = barriere(repeat)
        routes["/page-b"] = (200, {}, "b")
        routes[ASSET_JS] = asset
        bilan = self.prechauffer(routes=routes, repeat=repeat)
        self.assertEqual(bilan.echecs, [])
        self.assertEqual(self.chemins.count("/page-a"), repeat)
        self.assertEqual(len(construits), repeat)

    def test_a_failure_wins_over_an_earlier_success(self):
        self.assertEqual(warmup._pire([200, 500]), 500)
        self.assertEqual(warmup._pire([200, 0]), 0)
        self.assertEqual(warmup._pire([200, 404]), 404)
        self.assertEqual(warmup._pire([404, 502]), 502)
        self.assertEqual(warmup._pire([302, 200]), 302)
        compte = []
        verrou = threading.Lock()

        def intermittente(_requete):
            with verrou:
                compte.append(1)
                rang = len(compte)
            return (200 if rang % 2 else 500), {}, "a"

        routes = routes_publiques()
        routes["/page-a"] = intermittente
        routes["/page-b"] = (200, {}, "b")
        bilan = self.prechauffer(routes=routes, repeat=2)
        self.assertEqual(bilan.echecs, [("/page-a", 500)])

    def test_an_absent_sitemap(self):
        routes = routes_publiques()
        routes["/sitemap.xml"] = (404, {}, "<loc>/page-a</loc>")
        bilan = self.prechauffer(routes=routes, repeat=1)
        self.assertEqual(bilan.pages, 2)
        self.assertNotIn("/page-a", self.chemins)

    def test_the_session_cookie_is_reused(self):
        self.prechauffer()
        for requete in self.requetes[1:]:
            self.assertIn("session_id=s1", requete.entetes.get("cookie", ""))

    def test_max_pages(self):
        bilan = self.prechauffer(max_pages=1, repeat=1)
        self.assertIn("/page-a", self.chemins)
        self.assertNotIn("/page-b", self.chemins)
        self.assertEqual(bilan.pages, 3)

    def test_a_404_is_not_public_not_a_failure(self):
        routes = routes_publiques()
        routes["/page-b"] = (404, {}, "")
        bilan = self.prechauffer(routes=routes, repeat=1)
        self.assertEqual(bilan.echecs, [])
        self.assertEqual(bilan.non_publics, [("/page-b", 404)])

    def test_sitemap_index(self):
        routes = routes_publiques()
        routes["/sitemap.xml"] = (
            200,
            {},
            "<sitemapindex><sitemap><loc>https://www.example.org/"
            "sitemap-1.xml</loc></sitemap></sitemapindex>",
        )
        routes["/sitemap-1.xml"] = (
            200,
            {},
            "<urlset><url><loc>https://www.example.org/page-c?x=1&amp;y=2"
            "</loc></url></urlset>",
        )
        routes["/page-c"] = (200, {}, "c")
        self.prechauffer(routes=routes, repeat=1)
        self.assertIn("/sitemap-1.xml", self.chemins)
        self.assertIn("/page-c?x=1&y=2", self.chemins)

    def test_each_asset_is_built_alone_first(self):
        moments = []
        verrou = threading.Lock()

        def asset(_requete):
            debut = time.monotonic()
            with verrou:
                premier = not moments
            if premier:
                time.sleep(0.2)
            with verrou:
                moments.append((debut, time.monotonic()))
            return 200, {}, "js"

        routes = routes_publiques()
        routes[ASSET_JS] = asset
        self.prechauffer(routes=routes, repeat=4)
        self.assertEqual(len(moments), 4)
        moments.sort()
        fin_du_premier = moments[0][1]
        for debut, _fin in moments[1:]:
            self.assertGreaterEqual(debut, fin_du_premier)

    def test_the_environment_proxy_is_ignored(self):
        variables = {
            "http_proxy": "http://127.0.0.1:9",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "no_proxy": "",
            "NO_PROXY": "",
        }
        with mock.patch.dict(os.environ, variables):
            bilan = self.prechauffer(repeat=1)
        self.assertEqual(bilan.pages, 4)
        self.assertIn("/page-a", self.chemins)

    def test_asset_extraction(self):
        self.assertEqual(
            warmup.assets_de(PAGE_LOGIN + PAGE_LOGIN), [ASSET_JS, ASSET_CSS]
        )
        self.assertEqual(
            warmup.assets_de(PAGE_ACCUEIL), [ASSET_JS, ASSET_ANCIEN]
        )
        self.assertEqual(
            warmup.chemin_local("https://www.example.org/a?b=1&amp;c=2"),
            "/a?b=1&c=2",
        )
        self.assertEqual(
            warmup.chemin_local("https://www.example.org/été page?q=a b"),
            "/%C3%A9t%C3%A9%20page?q=a%20b",
        )
        self.assertEqual(
            warmup.chemin_local("https://www.example.org/caf%C3%A9"),
            "/caf%C3%A9",
        )
        self.assertTrue(warmup.est_html("/shop/page"))
        self.assertFalse(warmup.est_html("/web/image/logo.PNG"))


class FauxRpc:
    """Le point /jsonrpc d'un faux Odoo : `version` majeure servie,
    `login` qui accepte ou non, appels `execute_kw` retenus."""

    def __init__(self, version=18, uid=2, cle="cle-secrete-1234"):
        self.version = version
        self.uid = uid
        self.cle = cle
        self.appels = []
        self.verrou = threading.Lock()

    def __call__(self, requete):
        params = json.loads(requete.corps)["params"]
        service, methode, args = (
            params["service"],
            params["method"],
            params["args"],
        )
        if (service, methode) == ("common", "version"):
            resultat = {"server_version_info": [self.version, 0, 0]}
        elif (service, methode) == ("common", "login"):
            resultat = self.uid if args[2] == self.cle else False
        else:
            _db, _uid, _cle, modele, meth, margs, kwargs = args
            with self.verrou:
                self.appels.append((modele, meth, margs, kwargs))
            if modele == "res.broken":
                erreur = {
                    "message": "Odoo Server Error",
                    "data": {"message": f"boom with {self.cle}"},
                }
                return 200, {}, json.dumps({"id": 1, "error": erreur})
            resultat = {"lang": "fr_FR"} if meth == "context_get" else {}
        return (
            200,
            {},
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": resultat}),
        )


class TestDeepAuthenticatedPart(unittest.TestCase):
    def prechauffer(self, rpc, modeles=("res.partner",), repeat=2):
        routes = routes_publiques()
        routes["/page-b"] = (200, {}, "b")
        routes["/jsonrpc"] = rpc
        with FauxOdoo(routes) as serveur:
            return warmup.prechauffer_profond(
                serveur.url,
                "base1",
                repeat=repeat,
                login="admin",
                cle="cle-secrete-1234",
                modeles=modeles,
                delai=10,
            )

    def test_views_by_version(self):
        for version, methode, liste in (
            (18, "get_views", "list"),
            (17, "get_views", "tree"),
            (16, "get_views", "tree"),
            (15, "load_views", "tree"),
        ):
            with self.subTest(version=version):
                rpc = FauxRpc(version)
                bilan = self.prechauffer(rpc)
                self.assertEqual(bilan.version, version)
                vues = [a for a in rpc.appels if a[0] == "res.partner"]
                self.assertEqual({a[1] for a in vues}, {methode})
                self.assertEqual(vues[0][2][0][0], [False, liste])

    def test_only_whitelisted_calls_each_repeated(self):
        rpc = FauxRpc()
        bilan = self.prechauffer(rpc, ("res.partner", "res.users"), repeat=3)
        paires = [(a[0], a[1]) for a in rpc.appels]
        permis = {
            ("res.users", "context_get"),
            ("ir.ui.menu", "load_menus"),
            ("res.partner", "get_views"),
            ("res.users", "get_views"),
        }
        self.assertLessEqual(set(paires), permis)
        for paire in permis:
            self.assertEqual(paires.count(paire), 3, paire)
        self.assertEqual(bilan.connexion, "ok")
        self.assertEqual(bilan.echecs, [])
        menus = [a for a in rpc.appels if a[1] == "load_menus"]
        self.assertEqual(menus[0][3]["context"], {"lang": "fr_FR"})

    def test_login_refused(self):
        bilan = self.prechauffer(FauxRpc(uid=False))
        self.assertEqual(bilan.connexion, "refused")
        self.assertEqual(len(bilan.echecs), 1)

    def test_the_key_never_appears_in_an_error(self):
        bilan = self.prechauffer(FauxRpc(), ("res.broken",), repeat=1)
        texte = repr(bilan.echecs)
        self.assertIn("boom with ***", texte)
        self.assertNotIn("cle-secrete-1234", texte)

    def test_the_whitelist_is_enforced_in_the_callee(self):
        for modele, methode in (
            ("res.partner", "write"),
            ("res.partner", "unlink"),
            ("res.partner", "load_menus"),
            ("ir.ui.menu", "context_get"),
            ("Bad Model", "get_views"),
        ):
            with self.subTest(methode=methode):
                with self.assertRaises(ValueError):
                    warmup.executer_lecture(
                        None, "b", 2, "k", modele, methode, [], {}
                    )

    def test_vues_a_charger(self):
        self.assertEqual(warmup.vues_a_charger(None)[0], "get_views")
        self.assertEqual(warmup.vues_a_charger(None)[1][0], [False, "list"])
        self.assertEqual(warmup.vues_a_charger(14)[0], "load_views")


class TestDeepCommandLine(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dossier = d.name
        self.cle = os.path.join(self.dossier, "cle")
        with open(self.cle, "w") as f:
            f.write("cle-secrete-1234\n")
        os.chmod(self.cle, 0o600)

    def jouer(self, argv, routes=None, systeme=None, serveur=None):
        routes = routes or routes_publiques()
        sortie, erreurs = io.StringIO(), io.StringIO()
        with serveur or FauxOdoo(routes) as serveur:
            argv = [a.replace("URL", serveur.url) for a in argv]
            with (
                contextlib.redirect_stdout(sortie),
                contextlib.redirect_stderr(erreurs),
            ):
                code = warmup.main(argv, systeme=systeme)
            self.requetes = serveur.requetes
            self.chemins = serveur.chemins()
        self.sortie, self.erreurs = sortie.getvalue(), erreurs.getvalue()
        return code

    def test_summary_and_exit_codes(self):
        argv = ["--deep", "--url", "URL", "-d", "base1", "--repeat", "1"]
        self.assertEqual(self.jouer(argv), 0)
        self.assertIn("🔥 warmup --deep:", self.sortie)
        resume = warmup.t(
            "Pages: {pages} · assets: {assets} · RPC calls: {rpc} ·"
            " failures: {failures} · not public: {private} · {seconds} s"
        ).split("{")[0]
        self.assertIn(resume, self.sortie)
        self.assertIn("/page-b: 500", self.sortie)
        self.assertEqual(self.jouer(argv + ["--strict"]), 1)

    def test_authenticated_with_a_key_file(self):
        routes = routes_publiques()
        routes["/jsonrpc"] = FauxRpc()
        argv = [
            "--deep",
            "--url",
            "URL",
            "-d",
            "base1",
            "--login",
            "admin",
            "--api-key-file",
            self.cle,
            "--repeat",
            "1",
        ]
        self.assertEqual(self.jouer(argv, routes), 0)
        self.assertNotIn("cle-secrete-1234", self.sortie + self.erreurs)
        self.assertIn("/jsonrpc", self.chemins)
        # La clé ne part que dans le corps des appels /jsonrpc : ni dans un
        # chemin, ni dans un en-tête, ni ailleurs.
        for requete in self.requetes:
            visible = requete.chemin + repr(requete.entetes)
            self.assertNotIn("cle-secrete-1234", visible)
            if requete.chemin != "/jsonrpc":
                self.assertNotIn(b"cle-secrete-1234", requete.corps)

    def test_login_refused_is_attn_and_strict_fails(self):
        routes = routes_publiques()
        routes["/jsonrpc"] = FauxRpc(uid=False)
        routes["/page-b"] = (200, {}, "b")
        argv = [
            "--deep",
            "--url",
            "URL",
            "-d",
            "base1",
            "--login",
            "admin",
            "--api-key-file",
            self.cle,
            "--repeat",
            "1",
        ]
        self.assertEqual(self.jouer(argv, routes), 0)
        self.assertIn("[ATTN]", self.sortie)
        self.assertEqual(self.jouer(argv + ["--strict"], routes), 1)

    def test_usage_errors_return_2(self):
        absent = os.path.join(self.dossier, "absent")
        lien = os.path.join(self.dossier, "lien")
        os.symlink(self.cle, lien)
        vide = os.path.join(self.dossier, "vide")
        open(vide, "w").close()
        base = ["--deep", "--url", "URL", "-d", "base1"]
        for options in (
            ["--login", "admin", "--api-key-file", absent],
            ["--login", "admin", "--api-key-file", lien],
            ["--login", "admin", "--api-key-file", vide],
            ["--login", "admin"],
            ["--api-key-file", self.cle],
            ["--models", "Bad Model"],
            ["--repeat", "99"],
            ["--unknown-option"],
            ["--service", "x"],
        ):
            with self.subTest(options=options):
                self.assertEqual(self.jouer(base + options), 2)
                self.assertNotIn("cle-secrete-1234", self.erreurs)
        sans_base = ["--deep", "--url", "URL", "--login", "admin"]
        self.assertEqual(
            self.jouer(sans_base + ["--api-key-file", self.cle]), 2
        )
        self.assertEqual(
            self.jouer(["--deep", "--url", "ftp://example.org"]), 2
        )

    def test_a_key_readable_by_others_is_flagged(self):
        os.chmod(self.cle, 0o644)
        routes = routes_publiques()
        routes["/jsonrpc"] = FauxRpc()
        argv = [
            "--deep",
            "--url",
            "URL",
            "-d",
            "base1",
            "--login",
            "admin",
            "--api-key-file",
            self.cle,
            "--repeat",
            "1",
        ]
        self.assertEqual(self.jouer(argv, routes), 0)
        self.assertIn("chmod 600", self.sortie)

    def avec_cle(self, url):
        return [
            "--deep",
            "--url",
            url,
            "-d",
            "base1",
            "--login",
            "admin",
            "--api-key-file",
            self.cle,
        ]

    def test_the_key_never_crosses_plain_http_to_another_host(self):
        with mock.patch.object(
            warmup, "sonder", side_effect=AssertionError
        ) as sonde:
            code = self.jouer(self.avec_cle("http://www.example.org"))
        self.assertEqual(code, 2)
        sonde.assert_not_called()
        self.assertEqual(self.chemins, [])
        self.assertIn("https://", self.erreurs)
        self.assertNotIn("cle-secrete-1234", self.sortie + self.erreurs)
        # https, ou http vers la boucle locale, passent la garde.
        with mock.patch.object(warmup, "sonder", return_value=False):
            self.assertEqual(
                self.jouer(self.avec_cle("https://www.example.org")), 0
            )
        for url, permise in (
            ("https://www.example.org", True),
            ("http://127.0.0.1:8069", True),
            ("http://127.1.2.3:8069", True),
            ("http://[::1]:8069", True),
            ("http://localhost:8069", True),
            ("http://www.example.org", False),
            ("http://10.0.0.5:8069", False),
            ("http://localhost.example.org", False),
        ):
            with self.subTest(url=url):
                self.assertEqual(warmup.chiffree_ou_locale(url), permise)

    def test_ctrl_c_returns_130(self):
        with mock.patch.object(
            warmup, "sonder", side_effect=KeyboardInterrupt
        ):
            self.assertEqual(self.jouer(["--deep", "--url", "URL"]), 130)

    def test_no_answer(self):
        with mock.patch.object(warmup, "sonder", return_value=False):
            argv = ["--deep", "--url", "URL", "--timeout", "1"]
            self.assertEqual(self.jouer(argv), 0)
            self.assertEqual(self.jouer(argv + ["--strict"]), 1)


class FauxSystemeLocal(health_check.Systeme):
    """Une unité systemd de théâtre, dont le dossier de travail porte
    `config.conf` : seule `systemctl show` répond."""

    def __init__(self, wd):
        super().__init__()
        self.wd = wd
        self.appels = []

    def lanceur(self, argv, timeout=60):
        self.appels.append(list(argv))
        if argv[:2] == ["systemctl", "show"]:
            return 0, (
                "LoadState=loaded\nActiveState=active\nUser=demo\n"
                f"WorkingDirectory={self.wd}\n"
                "ExecStart={ path=/bin/bash ; argv[]=/bin/bash"
                f" {self.wd}/run.sh ; ignore_errors=no }}\n"
                "Environment=\n"
            )
        return 1, "commande inattendue"


class TestDeepTargets(unittest.TestCase):
    """`--deep --local` (l'entrée du menu Production) et `--deep` sans
    `--url` (l'adresse du mode par défaut) : le port et la base viennent
    de la configuration, et la première requête porte `?db=`."""

    setUp = TestDeepCommandLine.setUp
    jouer = TestDeepCommandLine.jouer

    def config(self, port):
        with open(os.path.join(self.dossier, "run.sh"), "w") as f:
            f.write("#!/bin/bash\n")
        chemin = os.path.join(self.dossier, "config.conf")
        with open(chemin, "w") as f:
            f.write(f"[options]\nhttp_port = {port}\ndb_name = base1\n")
        return chemin

    def test_local_uses_the_unit_configuration(self):
        serveur = FauxOdoo(routes_publiques())
        self.config(serveur.port)
        systeme = FauxSystemeLocal(self.dossier)
        argv = ["--deep", "--local", "--service", "erplibre_demo"]
        code = self.jouer(argv + ["--repeat", "1"], None, systeme, serveur)
        self.assertEqual(code, 0, self.erreurs)
        self.assertEqual(self.chemins[:2], ["/web/login?db=base1"] * 2)
        self.assertIn("/page-a", self.chemins)
        self.assertEqual(systeme.appels[0][:2], ["systemctl", "show"])
        self.assertIn("erplibre_demo.service", systeme.appels[0])

    def test_without_url_the_default_address(self):
        serveur = FauxOdoo(routes_publiques())
        chemin = self.config(serveur.port)
        argv = ["--deep", "-c", chemin, "--repeat", "1"]
        self.assertEqual(self.jouer(argv, serveur=serveur), 0, self.erreurs)
        self.assertEqual(self.chemins[:2], ["/web/login?db=base1"] * 2)
        self.assertIn("/page-a", self.chemins)


if __name__ == "__main__":
    unittest.main()
