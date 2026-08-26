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

import io
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
            self.assertTrue(analyse["why_not"].strip(), analyse["key"])

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


class TestAMissingPricelistOnlyCountsWhenTheFeatureIsOn(unittest.TestCase):
    """Une liste de prix absente n'est un défaut que si on l'a demandée.

    Mesuré : six utilisateurs étaient membres DIRECTS de
    `product.group_product_pricelist` — hérité d'un palier de migration —
    alors que `base.group_user` ne l'impliquait pas. La case des réglages
    était donc décochée, et la réparation créait quand même une liste.
    Odoo prévenait ensuite à chaque ouverture des réglages qu'il allait
    l'archiver.

    `res.config.settings` lit ce que `base.group_user` IMPLIQUE ; le
    contrôle pose désormais la même question.
    """

    def _controle(self):
        for controle in residue.CONTROLES:
            if controle["key"] == "missing_pricelist":
                return controle
        raise AssertionError("contrôle introuvable")

    def test_it_asks_whether_the_feature_is_implied(self):
        sql = " ".join(self._controle()["sql"].split())
        self.assertIn("res_groups_implied_rel", sql)
        self.assertIn("group_product_pricelist", sql)
        self.assertIn("group_user", sql)

    def test_it_does_not_settle_for_direct_membership(self):
        """`res_groups_users_rel` dirait « quelqu'un est dans le groupe »,
        ce qui était vrai et menait au faux positif."""
        self.assertNotIn("res_groups_users_rel", self._controle()["sql"])

    def test_it_still_requires_the_module_and_the_table(self):
        sql = " ".join(self._controle()["sql"].split())
        self.assertIn("ir_module_module", sql)
        self.assertIn("to_regclass", sql)


class TestTheRepairAsksItsOwnDetector(unittest.TestCase):
    """Une réparation qui n'écoute pas son détecteur fabrique des doublons.

    Mesuré sur une migration de bout en bout : la liste de prix avait
    traversé les six paliers, PARTAGÉE entre sociétés (company_id vide).
    `_activate_or_create_pricelists` ne compte pas une liste partagée
    comme appartenant à la société — elle en a donc créé une seconde,
    vide, à côté de celle du client.

    Le détecteur `pricelist_missing`, lui, disait déjà « rien ne manque ».
    Il fallait que la réparation le lui demande.
    """

    def _source(self):
        from pathlib import Path

        chemin = (
            Path(__file__).resolve().parent.parent
            / "script"
            / "odoo"
            / "migration"
            / "restore_config_defaults.py"
        )
        return chemin.read_text(encoding="utf-8")

    def _garde(self):
        """Le texte qui précède l'APPEL, pas sa mention dans la docstring.

        `index` trouvait la PREMIÈRE occurrence — celle de l'en-tête du
        module, qui explique justement ce que fait cette méthode. Le test
        s'évaluait alors sur un extrait de prose et échouait. `rindex`
        prend la dernière, qui est l'appel.
        """
        source = self._source()
        debut = source.rindex("_activate_or_create_pricelists()")
        return source[max(0, debut - 400) : debut]

    def test_the_repair_is_gated_on_an_empty_count(self):
        self.assertIn("pricelist_before", self._garde())

    def test_the_feature_condition_is_still_there(self):
        self.assertIn("pricelist_group", self._garde())

    def test_the_feature_is_read_from_the_implication(self):
        """Et non de l'appartenance de celui qui exécute."""
        source = self._source()
        self.assertIn("implied_ids", source)
        self.assertNotIn(
            'env.user.has_group(\n            "product.group_product_pricelist"',
            source,
        )


def verdict(**champs):
    """Un événement du journal de progression, forme réelle."""
    brut = {
        "at": "2026-08-26 03:19:59.846453",
        "step": "4.1.I - Migrate database",
        "kind": "test",
        "name": "smoke_public_url",
        "status": 1,
        "detail": ".venv.erplibre/bin/python3"
        " ./script/odoo/migration/smoke_public_url.py"
        " -d test_neutralize_upgrade_14 --internal-required",
    }
    brut.update(champs)
    return brut


class TestTheVerdictsSection(unittest.TestCase):
    """Ce que les contrôles SQL ne peuvent structurellement pas voir.

    Un test de fumée qui échoue n'écrit rien en base : rien n'est cassé,
    la requête suivante répond. Aucun contrôle lisant la base ne le
    retrouvera jamais — et c'était la moitié de ce qu'une migration peut
    rater.
    """

    def setUp(self):
        import json
        import shutil
        import tempfile

        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier)
        self.chemin = os.path.join(self.dossier, "progression.json")
        self.json = json

    def ecrire(self, evenements):
        with io.open(self.chemin, "w", encoding="utf-8") as handle:
            self.json.dump({"lst_event": evenements}, handle)
        return self.chemin

    def test_two_steps_of_one_migration_are_the_same_lineage(self):
        # Interroger la base 18 doit montrer l'échec du palier 14 : c'est
        # le seul endroit où il subsiste.
        self.assertEqual(
            residue.famille("test_neutralize_upgrade_14"),
            residue.famille("test_neutralize_upgrade_18"),
        )

    def test_a_plain_name_is_its_own_lineage(self):
        self.assertEqual("copy_chezlepro3", residue.famille("copy_chezlepro3"))

    def test_another_migration_verdicts_are_not_shown(self):
        # Deux migrations partagent le fichier. Attribuer l'échec de
        # l'une à l'autre enverrait chercher une panne qui n'existe pas.
        chemin = self.ecrire([verdict()])
        _tous, ratés = residue.verdicts("autre_client_upgrade_18", chemin)
        self.assertEqual([], ratés)

    def test_the_failure_of_an_earlier_step_is_shown(self):
        chemin = self.ecrire([verdict()])
        _tous, ratés = residue.verdicts("test_neutralize_upgrade_18", chemin)
        self.assertEqual(["smoke_public_url"], [e["name"] for e in ratés])

    def test_a_step_is_named_by_its_odoo_version(self):
        chemin = self.ecrire([verdict()])
        texte = "\n".join(
            residue.verdicts_block("test_neutralize_upgrade_18", False, chemin)
        )
        self.assertIn("14", texte)
        self.assertIn("smoke_public_url", texte)

    def test_no_file_says_nothing_at_all(self):
        # Devant la sauvegarde d'un client, il n'y a jamais eu de
        # migration locale : annoncer l'absence d'un fichier qu'on
        # n'attendait pas ne renseigne personne.
        absent = os.path.join(self.dossier, "jamais_ecrit.json")
        self.assertEqual([], residue.verdicts_block("base", False, absent))

    def test_all_green_is_stated_not_left_silent(self):
        chemin = self.ecrire([verdict(status=0), verdict(status=0)])
        texte = "\n".join(
            residue.verdicts_block("test_neutralize_upgrade_18", False, chemin)
        )
        self.assertIn("2", texte)
        self.assertIn(residue.t("checks, all passed"), texte)

    def test_the_report_says_these_are_not_from_the_database(self):
        # Sans cette phrase, un verdict d'il y a quatre paliers se lirait
        # comme un défaut présent de la base qu'on a sous les yeux.
        chemin = self.ecrire([verdict()])
        texte = "\n".join(
            residue.verdicts_block("test_neutralize_upgrade_18", False, chemin)
        )
        self.assertIn(
            residue.t("These come from the file, not the database:"), texte
        )

    def test_a_past_verdict_does_not_become_a_finding(self):
        # Le code de sortie dit « la BASE porte un défaut ». Y compter un
        # verdict passé rendrait 1 pour toujours, et le pilote traiterait
        # une base saine comme cassée à chaque appel.
        vide = {c["key"]: 0 for c in residue.CONTROLES}
        trouve, _illisibles = residue.judge(vide)
        self.assertEqual([], trouve)

    def test_the_clean_report_still_carries_the_verdicts(self):
        # Le cas qui compte : aucun résidu en base, et pourtant un test
        # de fumée a échoué en chemin. Le rapport « rien trouvé » ne doit
        # pas être le dernier mot.
        chemin = self.ecrire([verdict()])
        ancien = residue.quality.DEFAULT_PROGRESSION
        residue.quality.DEFAULT_PROGRESSION = chemin
        self.addCleanup(
            setattr, residue.quality, "DEFAULT_PROGRESSION", ancien
        )
        vide = {c["key"]: 0 for c in residue.CONTROLES}
        texte = residue.render(
            "test_neutralize_upgrade_18", vide, colour=False
        )
        self.assertIn(residue.t("None of the checks found anything."), texte)
        self.assertIn("smoke_public_url", texte)

    def test_the_colour_it_asks_for_exists(self):
        # `paint` retombe sur une chaîne vide suivie d'un RESET quand le
        # genre est inconnu : cela n'annule rien et ne teinte rien.
        chemin = self.ecrire([verdict()])
        for ligne in residue.verdicts_block(
            "test_neutralize_upgrade_18", True, chemin
        ):
            if ligne and ligne.endswith(residue.RESET):
                self.assertNotEqual(residue.RESET, ligne.strip())


if __name__ == "__main__":
    unittest.main()
