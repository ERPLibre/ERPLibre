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
"""

import io
import unittest
from pathlib import Path

from script.odoo import warmup_http as warmup

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


if __name__ == "__main__":
    unittest.main()
