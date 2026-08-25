#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le monitoring : ce qu'il refuse, et ce qu'il avoue ne pas savoir.

Deux propriétés valent d'être épinglées, et ce ne sont pas les plus
visibles.

La première est un refus. Toutes les analyses du dépôt lisent par psql en
`default_transaction_read_only=on` : c'est le SERVEUR qui interdit
d'écrire. Une session RPC n'a pas d'équivalent — rien n'empêche un
`write` sur la production d'un client. La liste blanche est donc appliquée
dans le passe-plat lui-même, et non chez l'appelant, pour qu'aucune
analyse à venir ne puisse s'en dispenser par distraction.

La seconde est un aveu. Une provenance qui ne permet pas une analyse doit
le DIRE. Une analyse muette qu'on prend pour rassurante est pire que pas
d'analyse : c'est la faute que ce dépôt a déjà corrigée trois fois.
"""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.analyse import check_migration_residue as residue  # noqa: E402
from script.analyse import monitoring  # noqa: E402
from script.analyse import monitoring_tui  # noqa: E402


class TestWhatTheProxyRefuses(unittest.TestCase):
    """Le passe-plat RPC n'accepte que la lecture."""

    def test_a_write_is_refused_before_any_network_call(self):
        # Aucune URL joignable ici : si l'appel partait, le test échouerait
        # par timeout au lieu de PermissionError. C'est le contrôle qu'on
        # veut — le refus vient AVANT le réseau.
        for methode in ("write", "create", "unlink", "execute", "load"):
            with self.assertRaises(PermissionError):
                monitoring.live_call(
                    "http://127.0.0.1:1", "db", 1, "x", "res.partner", methode
                )

    def test_the_allowlist_holds_nothing_that_writes(self):
        interdits = ("write", "create", "unlink", "copy", "load", "execute")
        for methode in monitoring.RPC_READ_ONLY:
            self.assertNotIn(methode, interdits)

    def test_the_refusal_names_the_method(self):
        with self.assertRaises(PermissionError) as capture:
            monitoring.live_call(
                "http://127.0.0.1:1", "db", 1, "x", "res.partner", "unlink"
            )
        self.assertIn("unlink", str(capture.exception))


class TestWhatASourceAdmits(unittest.TestCase):
    """Ce qu'une provenance ne permet pas doit être dit, pas caché."""

    def test_every_analysis_says_why_it_cannot_do_live(self):
        for analyse in monitoring.ANALYSES:
            self.assertTrue(analyse["needs_sql"].strip(), analyse["key"])

    def test_available_and_unavailable_cover_every_analysis(self):
        for genre in (monitoring.KIND_DATABASE, monitoring.KIND_LIVE):
            total = len(monitoring.available(genre)) + len(
                monitoring.unavailable(genre)
            )
            self.assertEqual(total, len(monitoring.ANALYSES))

    def test_a_restored_backup_and_a_database_are_the_same_thing(self):
        """Passé la restauration, la provenance ne se distingue plus."""
        self.assertTrue(monitoring.available(monitoring.KIND_DATABASE))

    def test_an_unknown_key_gives_none_rather_than_raising(self):
        self.assertIsNone(monitoring.analysis_by_key("pas_une_analyse"))

    def test_the_command_names_the_database(self):
        analyse = monitoring.ANALYSES[0]
        cmd = monitoring.command_for(analyse, "ma_base")
        self.assertIn("-d", cmd)
        self.assertEqual(cmd[cmd.index("-d") + 1], "ma_base")
        self.assertIn(analyse["script"], cmd)


class TestWhetherTheNeutralisationTook(unittest.TestCase):
    """Poser la question et ne pas vérifier, c'est l'illusion mesurée."""

    def test_a_missing_flag_is_reported_as_not_neutralised(self):
        rapport = monitoring.neutralize_report(
            {"flag": 0, "cron_active": 35, "mail_server": 0, "payment_live": 1}
        )
        self.assertIn("❌", rapport)
        self.assertIn("35", rapport)

    def test_no_mail_server_is_a_warning_and_never_a_reassurance(self):
        """Zéro serveur NE prouve PAS la sûreté : Odoo retombe sur la conf.

        C'est pour cela que le `neutralize.sql` d'Odoo INSÈRE un serveur
        bouchon au lieu de tout supprimer. Compter zéro et conclure « sûr »
        se tromperait dans le mauvais sens.
        """
        rapport = monitoring.neutralize_report(
            {"flag": 1, "cron_active": 0, "mail_server": 0, "payment_live": 0}
        )
        self.assertIn("⚠", rapport)
        self.assertIn("smtp_server", rapport)

    def test_a_table_that_does_not_exist_is_not_counted_as_zero(self):
        """Absent n'est pas nul, et surtout pas une bonne nouvelle."""
        appels = []

        class FauxLib:
            @staticmethod
            def run_psql(database, sql, config_path=None):
                appels.append(sql)
                raise RuntimeError("relation does not exist")

        # `from script.analyse import lib_analyse` lit l'ATTRIBUT du paquet :
        # remplacer l'entrée de sys.modules ne change rien, et le vrai psql
        # tourne. Le compteur d'appels est là pour le prouver — sans lui, ce
        # test passait au vert avec ZÉRO appel bouchonné.
        import script.analyse as paquet

        sauvegarde = paquet.lib_analyse
        paquet.lib_analyse = FauxLib
        try:
            etat = monitoring.neutralize_state("peu_importe")
        finally:
            paquet.lib_analyse = sauvegarde
        for valeur in etat.values():
            self.assertIsNone(valeur)
        self.assertEqual(len(appels), len(monitoring.NEUTRALIZE_SQL))

    def test_a_live_payment_provider_is_an_error_not_a_warning(self):
        rapport = monitoring.neutralize_report(
            {"flag": 1, "cron_active": 0, "mail_server": 1, "payment_live": 2}
        )
        ligne = [
            texte
            for texte in rapport.splitlines()
            if "payment" in texte or "paiement" in texte
        ]
        self.assertTrue(ligne)
        self.assertTrue(ligne[0].startswith("❌"))


class TestTheChooserScreen(unittest.TestCase):
    """L'écran ne fait que choisir — mais il doit choisir juste."""

    def test_every_analysis_is_shown_even_when_it_cannot_run(self):
        lignes = monitoring_tui.rows(monitoring.KIND_LIVE)
        self.assertEqual(len(lignes), len(monitoring.ANALYSES))

    def test_an_unusable_line_carries_its_reason(self):
        for _key, _label, utilisable, raison in monitoring_tui.rows(
            monitoring.KIND_LIVE
        ):
            if not utilisable:
                self.assertTrue(raison.strip())

    def test_a_usable_line_carries_no_excuse(self):
        for _key, _label, utilisable, raison in monitoring_tui.rows(
            monitoring.KIND_DATABASE
        ):
            if utilisable:
                self.assertEqual(raison, "")

    def test_the_detail_pane_says_when_a_source_cannot_serve(self):
        texte = monitoring_tui.detail(
            monitoring.ANALYSES[0]["key"], monitoring.KIND_LIVE
        )
        self.assertIn("✖", texte)

    def test_the_detail_pane_of_an_unknown_key_is_empty(self):
        self.assertEqual(
            monitoring_tui.detail("pas_une_analyse", monitoring.KIND_DATABASE),
            "",
        )


class TestWhatAMigrationLeftBehind(unittest.TestCase):
    """Le classement, et surtout ce qu'il refuse de taire."""

    def test_broken_is_read_before_watch(self):
        resultats = {c["key"]: 0 for c in residue.CONTROLES}
        resultats["duplicate_index"] = 400  # watch
        resultats["lang_active_null"] = 1  # broken
        trouve, _ = residue.judge(resultats)
        self.assertEqual(trouve[0][0]["key"], "lang_active_null")

    def test_a_check_that_could_not_run_is_not_a_check_that_found_nothing(
        self,
    ):
        resultats = {c["key"]: 0 for c in residue.CONTROLES}
        resultats["missing_pricelist"] = {"error": "relation absente"}
        trouve, illisibles = residue.judge(resultats)
        self.assertEqual(trouve, [])
        self.assertEqual(len(illisibles), 1)

    def test_the_report_shows_the_unreadable_ones(self):
        resultats = {c["key"]: 0 for c in residue.CONTROLES}
        resultats["missing_pricelist"] = {"error": "relation absente"}
        texte = residue.render("base", resultats, colour=False)
        self.assertIn("❔", texte)
        self.assertIn("relation absente", texte)

    def test_a_clean_database_states_what_it_could_not_see(self):
        """Un vert qui ne dit pas sa portée se lit comme une garantie."""
        resultats = {c["key"]: 0 for c in residue.CONTROLES}
        texte = residue.render("base", resultats, colour=False)
        self.assertIn("✅", texte)
        self.assertIn(
            residue.t("This reads one database on its own — it cannot see"),
            texte,
        )

    def test_every_finding_names_a_repair_or_says_there_is_none(self):
        resultats = {c["key"]: 1 for c in residue.CONTROLES}
        texte = residue.render("base", resultats, colour=False)
        for controle in residue.CONTROLES:
            attendu = controle["repair"] or residue.t("no repair tool yet")
            self.assertIn(attendu, texte)

    def test_each_check_is_declared_completely(self):
        cles = set()
        for controle in residue.CONTROLES:
            for champ in ("key", "title", "why", "sql", "gravity"):
                self.assertTrue(controle.get(champ), controle["key"])
            self.assertIn(controle["gravity"], ("broken", "watch"))
            self.assertNotIn(controle["key"], cles)
            cles.add(controle["key"])

    def test_each_query_reads_and_returns_one_number(self):
        """Une seule colonne, un seul SELECT : `inspect` en fait un int."""
        for controle in residue.CONTROLES:
            sql = " ".join(controle["sql"].split())
            self.assertTrue(sql.upper().startswith("SELECT"), controle["key"])
            for interdit in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER"):
                self.assertNotIn(f" {interdit} ", f" {sql.upper()} ")

    def test_the_exit_code_separates_nothing_from_something(self):
        vide = {c["key"]: 0 for c in residue.CONTROLES}
        self.assertEqual(residue.judge(vide)[0], [])
        plein = dict(vide, lang_active_null=3)
        self.assertTrue(residue.judge(plein)[0])


if __name__ == "__main__":
    unittest.main()


class TestTheScreenAnswersKeys(unittest.TestCase):
    """Presser les touches, et pas seulement lire les fonctions pures.

    `ListView` consomme Entrée pour émettre son propre `Selected` : la
    liaison de l'application ne la voit jamais. L'écran ne répondait donc
    pas à Entrée, et `rows()` comme `detail()` restaient parfaitement
    justes — aucun test de fonction pure ne pouvait le montrer.
    """

    def setUp(self):
        try:
            import textual  # noqa: F401
        except ImportError:
            self.skipTest("Textual absent de cet interpréteur")

    def _presser(self, kind, touches):
        import asyncio

        async def jouer():
            app = monitoring_tui.build_app(kind, "ma_base")
            async with app.run_test() as pilot:
                for touche in touches:
                    await pilot.press(touche)
                await pilot.pause()
            return app.return_value

        return asyncio.run(jouer())

    def test_enter_chooses_the_highlighted_analysis(self):
        self.assertEqual(
            self._presser(monitoring.KIND_DATABASE, ["enter"]),
            monitoring.ANALYSES[0]["key"],
        )

    def test_moving_down_then_enter_chooses_the_second(self):
        self.assertEqual(
            self._presser(monitoring.KIND_DATABASE, ["down", "enter"]),
            monitoring.ANALYSES[1]["key"],
        )

    def test_enter_on_an_unusable_line_chooses_nothing(self):
        """Et ne lève pas : un écran qui plante vaut moins qu'un refus."""
        self.assertIsNone(self._presser(monitoring.KIND_LIVE, ["enter"]))

    def test_q_gives_up(self):
        self.assertIsNone(self._presser(monitoring.KIND_DATABASE, ["q"]))


class TestTheSourceMenuIsWrittenTwice(unittest.TestCase):
    """Les numéros affichés mènent-ils où ils le disent ?

    `_monitoring_select_source` imprime « [2] Une sauvegarde .zip » d'un
    côté et teste `answer == "2"` de l'autre. Rien ne relie les deux :
    insérer « une base locale » en tête décale tout le reste à la main.
    C'est le piège exact que `MenuCoherence` garde pour les autres menus,
    et celui-ci n'entre pas dans son moule — il s'imprime, il ne se
    déclare pas.
    """

    def setUp(self):
        import re
        from pathlib import Path

        todo = (
            Path(__file__).resolve().parent.parent
            / "script"
            / "todo"
            / "todo.py"
        )
        source = todo.read_text(encoding="utf-8")
        debut = source.index("def _monitoring_select_source(self):")
        fin = source.index("def _monitoring_live(self):", debut)
        self.corps = source[debut:fin]
        self.affiches = re.findall(r'print\(f"\[(\d+)\] \{t\(', self.corps)
        self.branches = re.findall(r'if answer == "(\d+)":', self.corps)

    def test_the_menu_was_actually_parsed(self):
        """Sur des listes vides, tout passe : mieux vaut tomber ici."""
        self.assertGreaterEqual(len(self.affiches), 4)

    def test_every_shown_entry_has_a_branch(self):
        montres = [n for n in self.affiches if n != "0"]
        self.assertEqual(sorted(montres), sorted(self.branches))

    def test_the_numbering_is_contiguous_from_one(self):
        montres = sorted(int(n) for n in self.affiches if n != "0")
        self.assertEqual(montres, list(range(1, len(montres) + 1)))

    def test_a_local_database_is_offered_first(self):
        """La provenance la plus directe, et l'ordre du menu d'à côté."""
        self.assertEqual(self.affiches[0], "1")
        self.assertIn("A local database", self.corps.split("if answer")[0])
