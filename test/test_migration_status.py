#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""« Où en est-on, et qu'est-ce qui a cassé ? »

Une migration traverse six paliers, lance des centaines de commandes et
dure des heures. Le journal existant dit ce qui a été LANCÉ ; il ne dit
jamais ce que cela a donné. Trois heures plus tard on relit deux cents
lignes de commandes sans savoir laquelle a échoué, ni ce que le test de
fumée a conclu.

Deux choses se vérifient ici, et la seconde est la moins évidente :

- un outil relancé APRÈS correction a deux verdicts contradictoires dans
  le journal, et c'est le dernier qui décrit la base telle qu'elle est.
  Les afficher tous les deux sans les distinguer ferait lire une
  réparation comme un échec persistant ;
- l'écran ne doit RIEN toucher. On l'ouvre en pleine migration, souvent
  pendant qu'un serveur tourne.
"""

import io
import os
import shutil
import unittest
from contextlib import redirect_stdout

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from script.todo import migration_status as status  # noqa: E402
from script.todo import migration_status_tui as tui  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from script.todo.todo_upgrade import TodoUpgrade  # noqa: E402


def progression(**override):
    dct = {
        "migration_file": "/a/b/technolibre_2026.zip",
        "config_database_name": "test_neutralize",
        "date_create": "2026-08-18 03:25:25",
        "date_update": "2026-08-18 06:38:55",
        "command_executed": [
            "# 0 - Inspect zip",
            "make switch_odoo_12",
            "# 2 - Succeed update all addons",
            "./script/addons/update_addons_all.sh test",
            "./script/odoo/migration/check_cow_views.py -d test",
        ],
        "lst_event": [
            {
                "at": "05:01",
                "step": "2 - Succeed update all addons",
                "kind": "command",
                "name": "update_addons_all.sh test",
                "status": 1,
                "detail": "",
            },
            {
                "at": "05:20",
                "step": "2 - Succeed update all addons",
                "kind": "test",
                "name": "smoke_public_url",
                "status": 2,
                "detail": "",
            },
            {
                "at": "05:44",
                "step": "2 - Succeed update all addons",
                "kind": "test",
                "name": "smoke_public_url",
                "status": 0,
                "detail": "",
            },
        ],
    }
    dct.update(override)
    return dct


class Base(unittest.TestCase):
    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"


class TestCuttingTheJournalByStep(Base):
    def test_the_step_headers_are_the_cut(self):
        # On réutilise le marquage « # » que la migration dépose déjà.
        # En inventer un second qui divergerait serait pire que rien.
        lst = status.journal_by_step(progression())
        self.assertEqual(
            [s["step"] for s in lst],
            ["0 - Inspect zip", "2 - Succeed update all addons"],
        )

    def test_the_commands_land_under_their_step(self):
        lst = status.journal_by_step(progression())
        self.assertEqual(len(lst[1]["lst_cmd"]), 2)

    def test_a_command_before_any_header_is_not_lost(self):
        dct = progression(command_executed=["make quelque_chose"])
        lst = status.journal_by_step(dct)
        self.assertEqual(len(lst), 1)
        self.assertEqual(lst[0]["lst_cmd"], ["make quelque_chose"])

    def test_an_empty_progression_yields_nothing(self):
        self.assertEqual(status.journal_by_step({}), [])


class TestARepairMustNotReadAsAFailure(Base):
    """LE point délicat du résumé.

    `smoke_public_url` a rendu 2 puis 0 : il a échoué, on a réparé, il est
    repassé. Montrer les deux verdicts côte à côte ferait conclure que la
    base est toujours cassée.
    """

    def test_the_LAST_verdict_wins(self):
        lst = status.tests_summary(progression())
        smoke = [x for x in lst if x["name"] == "smoke_public_url"][0]
        self.assertEqual(smoke["status"], 0)

    def test_the_verdicts_are_kept_PER_STEP(self):
        """La demande, et le défaut qu'elle a révélé.

        Une migration lance le test de fumée à CHAQUE palier. Regrouper sur
        le seul nom d'outil n'en laissait qu'une ligne : on lisait
        « smoke_public_url ✅ » sans voir que le palier 14 était passé et
        le 17 tombé.
        """
        dct = progression(
            lst_event=[
                {
                    "at": "1",
                    "step": "4.1 - v14",
                    "kind": "test",
                    "name": "smoke_public_url",
                    "status": 0,
                },
                {
                    "at": "2",
                    "step": "4.2 - v15",
                    "kind": "test",
                    "name": "smoke_public_url",
                    "status": 2,
                },
            ]
        )
        lst = status.tests_summary(dct)
        self.assertEqual(len(lst), 2)
        self.assertEqual(
            [(x["step"], x["status"]) for x in lst],
            [("4.1 - v14", 0), ("4.2 - v15", 2)],
        )

    def test_a_repair_within_a_step_still_collapses(self):
        # Deux verdicts pour le MÊME palier : c'est une réparation, pas
        # deux paliers. Le second décrit la base telle qu'elle est.
        dct = progression(
            lst_event=[
                {
                    "at": "1",
                    "step": "4.2 - v15",
                    "kind": "test",
                    "name": "smoke_public_url",
                    "status": 2,
                },
                {
                    "at": "2",
                    "step": "4.2 - v15",
                    "kind": "test",
                    "name": "smoke_public_url",
                    "status": 0,
                },
            ]
        )
        lst = status.tests_summary(dct)
        self.assertEqual(len(lst), 1)
        self.assertEqual(lst[0]["status"], 0)
        self.assertEqual(lst[0]["runs"], 2)

    def test_the_order_is_the_migration_s_own(self):
        # Trier les étapes par leur nom mettrait « 4.10 » avant « 4.2 ».
        dct = progression(
            lst_event=[
                {
                    "at": "1",
                    "step": "4.2 - v15",
                    "kind": "test",
                    "name": "outil",
                    "status": 0,
                },
                {
                    "at": "2",
                    "step": "4.10 - v18",
                    "kind": "test",
                    "name": "outil",
                    "status": 0,
                },
            ]
        )
        self.assertEqual(
            [etape for etape, _lst in status.tests_by_step(dct)],
            ["4.2 - v15", "4.10 - v18"],
        )

    def test_the_report_shows_the_step_number(self):
        dct = progression(
            lst_event=[
                {
                    "at": "1",
                    "step": "4.1 - Ready to work with version 14",
                    "kind": "test",
                    "name": "database_cleanup",
                    "status": 0,
                },
            ]
        )
        texte = status.render_text(dct, colour=False)
        self.assertIn("4.1 - Ready to work with version 14", texte)

    def test_the_full_screen_shows_it_too(self):
        dct = progression(
            lst_event=[
                {
                    "at": "1",
                    "step": "4.1 - v14",
                    "kind": "test",
                    "name": "smoke_public_url",
                    "status": 0,
                },
            ]
        )
        ligne = [x for x in tui.rows(dct) if x["kind"] == "test"][0]
        self.assertIn("4.1", ligne["label"])

    def test_but_the_earlier_runs_are_still_counted(self):
        # Les taire ferait croire à un premier essai réussi, et l'on
        # perdrait la trace de ce qui a demandé une réparation.
        lst = status.tests_summary(progression())
        smoke = [x for x in lst if x["name"] == "smoke_public_url"][0]
        self.assertEqual(smoke["runs"], 2)

    def test_the_report_shows_both_facts(self):
        text = status.render_text(progression())
        self.assertIn("smoke_public_url", text)
        self.assertIn("2 runs", text)
        self.assertIn("nothing to report", text)


class TestTheExitCodeConvention(Base):
    """0 rien, 1 des trouvailles, 2 l'outil a échoué — partout la même."""

    def test_zero_is_not_alarming(self):
        self.assertEqual(status.verdict(0)[1], "nothing to report")

    def test_one_is_findings_not_a_crash(self):
        # Le dire « échec » inquiéterait pour rien : 1 veut dire qu'il y a
        # quelque chose à regarder, ce qui est le but de l'outil.
        self.assertEqual(status.verdict(1)[1], "findings to look at")

    def test_two_is_the_tool_itself(self):
        self.assertEqual(status.verdict(2)[1], "the tool itself failed")

    def test_anything_else_is_admitted_as_unknown(self):
        self.assertEqual(status.verdict(77)[1], "unknown result")


class TestFailedCommands(Base):
    def test_they_are_listed_newest_first(self):
        dct = progression()
        dct["lst_event"].append(
            {
                "at": "06:00",
                "step": "3",
                "kind": "command",
                "name": "récente",
                "status": 1,
                "detail": "",
            }
        )
        self.assertEqual(status.failures(dct)[0]["name"], "récente")

    def test_they_carry_the_step_they_happened_in(self):
        # Sans l'étape, il faut relire tout le journal pour savoir OÙ.
        self.assertIn(
            "2 - Succeed update all addons",
            status.failures(progression())[0]["step"],
        )

    def test_tests_are_not_mixed_in_with_them(self):
        self.assertEqual(len(status.failures(progression())), 1)


class TestItTouchesNothing(Base):
    """On l'ouvre en pleine migration, souvent serveur allumé."""

    def test_reading_a_missing_file_is_not_an_error(self):
        self.assertEqual(status.read("/nexiste/pas.json"), {})

    def test_reading_a_broken_file_is_not_an_error(self):
        import tempfile

        chemin = os.path.join(tempfile.gettempdir(), "erplibre_casse.json")
        with open(chemin, "w") as handle:
            handle.write("{ pas du json")
        self.addCleanup(os.remove, chemin)
        self.assertEqual(status.read(chemin), {})

    def test_nothing_in_the_module_writes_or_connects(self):
        import inspect

        source = inspect.getsource(status)
        for interdit in ("psql", "subprocess", "odoo_bin", 'open(.*, "w")'):
            self.assertNotIn(interdit, source, interdit)

    def test_an_empty_progression_says_so_rather_than_crashing(self):
        self.assertIn("No migration in progress", status.render_text({}))


class TestTheFullScreenShowsTheSameThing(Base):
    def test_it_reads_the_same_assembly_as_the_text(self):
        # Deux assemblages sépareraient les deux vues, et l'on finirait
        # par lire deux états contradictoires de la même migration.
        import inspect

        self.assertIn("import migration_status", inspect.getsource(tui))

    def test_the_tests_come_before_the_steps(self):
        # C'est la question qu'on se pose en ouvrant cet écran.
        lst = tui.rows(progression())
        self.assertEqual(lst[0]["kind"], "test")
        self.assertTrue(any(x["kind"] == "step" for x in lst))

    def test_the_head_never_hides_what_failed(self):
        texte = tui.head_text(progression())
        self.assertIn("test_neutralize", texte)
        self.assertIn("1", texte)

    def test_a_step_pane_names_its_own_failures(self):
        lst = tui.rows(progression())
        etape = [x for x in lst if x["kind"] == "step"][1]
        self.assertIn(
            "update_addons_all.sh test", tui.pane_text(progression(), etape)
        )

    def test_a_test_pane_gives_the_exit_code(self):
        lst = tui.rows(progression())
        texte = tui.pane_text(progression(), lst[0])
        self.assertIn("smoke_public_url", texte)

    def test_a_pipe_is_explained_rather_than_silent(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertFalse(tui.run_tui(progression()))
        self.assertTrue(out.getvalue().strip())

    def test_nothing_to_show_stays_silent(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertFalse(tui.run_tui({}))
        self.assertEqual(out.getvalue(), "")


class TestTheLetterIsFreeAndUniform(Base):
    """« v » était pris : il veut dire « voir les différences » ailleurs."""

    def test_v_is_taken_by_the_diff_prompts(self):
        import inspect

        source = inspect.getsource(TodoUpgrade.prompt_cow_prediction)
        self.assertIn('"v"', source)

    def test_the_state_letter_is_t_everywhere(self):
        import inspect

        source = inspect.getsource(TodoUpgrade.ask_gate)
        self.assertIn('reponse == "t"', source)

    def test_every_gate_prompt_announces_it(self):
        chemin = os.path.join(REPO, "script", "todo", "todo_upgrade.py")
        with open(chemin) as handle:
            texte = handle.read()
        # Une seule chaîne porte les deux raccourcis : les annoncer
        # séparément les laisserait diverger d'une invite à l'autre.
        self.assertGreaterEqual(texte.count("t = show the migration state"), 1)
        self.assertNotIn("(b = go back to a previous step)", texte)

    def test_t_collides_with_no_other_answer(self):
        import inspect

        for methode in (
            "prompt_uninstall_theme",
            "prompt_database_cleanup",
            "prompt_smoke_public_url",
            "prompt_reset_stale_cow_views",
        ):
            source = inspect.getsource(getattr(TodoUpgrade, methode))
            self.assertNotIn('== "t"', source, methode)


class TestLookingIsNotAnswering(Base):
    def test_the_state_reopens_the_same_question(self):
        obj = TodoUpgrade.__new__(TodoUpgrade)
        vu = []
        obj.show_migration_status = lambda: vu.append("ouvert")
        reponses = iter(["t", "t", "y"])
        obj.ask = lambda prompt, default="": next(reponses)
        self.assertEqual(obj.ask_gate("q : "), "y")
        self.assertEqual(len(vu), 2)

    def test_it_writes_before_it_reads(self):
        # L'écran lit le FICHIER de progression : ce qui vient de se passer
        # n'y serait pas encore.
        import inspect

        source = inspect.getsource(TodoUpgrade.show_migration_status)
        self.assertLess(
            source.index("write_config"), source.index("subprocess.call")
        )

    def test_it_survives_a_screen_opened_before_anything_is_loaded(self):
        """`show_stats` tourne AVANT que la progression ne soit en mémoire.

        Elle est ouverte tout au début d'`execute_odoo_upgrade`, avant même
        le choix du fichier. Y appeler `write_config` échouait alors sur un
        attribut qui n'existe pas encore — et l'écran d'état, ouvert depuis
        là, aurait planté au lieu de s'afficher.
        """
        import script.todo.todo_upgrade as tu

        obj = TodoUpgrade.__new__(TodoUpgrade)
        appels = []
        obj.write_config = lambda: appels.append("écrit")
        original = tu.subprocess.call
        tu.subprocess.call = lambda *a, **kw: 0
        self.addCleanup(setattr, tu.subprocess, "call", original)
        obj.show_migration_status()
        self.assertEqual(appels, [], "rien en mémoire, rien à écrire")

    def test_but_it_does_write_what_it_has(self):
        # Sans rien en mémoire le fichier est déjà la vérité ; avec quelque
        # chose, il ne l'est plus tant qu'on ne l'a pas écrit.
        import script.todo.todo_upgrade as tu

        obj = TodoUpgrade.__new__(TodoUpgrade)
        obj.dct_progression = {"config_database_name": "db"}
        appels = []
        obj.write_config = lambda: appels.append("écrit")
        original = tu.subprocess.call
        tu.subprocess.call = lambda *a, **kw: 0
        self.addCleanup(setattr, tu.subprocess, "call", original)
        obj.show_migration_status()
        self.assertEqual(appels, ["écrit"])

    def test_looking_does_not_pollute_the_journal(self):
        # `run_on_terminal` consigne ce qu'il lance, et le journal est
        # justement ce que cet écran montre.
        import inspect

        source = inspect.getsource(TodoUpgrade.show_migration_status)
        # L'APPEL, pas le mot : le commentaire du correctif nomme lui-même
        # ce qu'il faut éviter, et le chercher à l'aveugle se déclenchait
        # sur la prose plutôt que sur le code.
        self.assertNotIn("self.run_on_terminal(", source)


class DiskCase(Base):
    """Un répertoire jetable : les chemins de journal sont RELATIFS."""

    def setUp(self):
        super().setUp()
        import tempfile

        self.dossier = tempfile.mkdtemp(prefix="erplibre_essai_")
        avant = os.getcwd()
        os.chdir(self.dossier)
        self.addCleanup(shutil.rmtree, self.dossier, True)
        self.addCleanup(os.chdir, avant)

    def upgrade(self, database="essai_db"):
        obj = TodoUpgrade.__new__(TodoUpgrade)
        obj.dct_progression = {"config_database_name": database}
        obj.lst_command_executed = []
        obj.write_config = lambda: None
        return obj


class TestWhatSurvivesClosingTheTool(DiskCase):
    """Le fichier de progression est ARCHIVÉ puis remis à zéro.

    Recommencer une migration effaçait donc tout ce que l'écran d'état
    savait — au moment précis où l'on cherche à comprendre pourquoi il a
    fallu recommencer. Le journal permanent, lui, ne fait que s'allonger.
    """

    def test_events_are_found_again_with_nothing_in_memory(self):
        obj = self.upgrade()
        obj.print_step("4.2.I - Migrate database")
        obj.record_event("command", "update_addons_all.sh", 1)
        obj.record_event("test", "smoke_public_url", 0)
        obj.close_step_log()
        # Une progression NEUVE : c'est l'état après réouverture.
        neuf = {"config_database_name": "essai_db"}
        lst = status.merge_events(neuf)
        self.assertEqual(len(lst), 2)
        self.assertEqual(lst[0]["name"], "update_addons_all.sh")

    def test_the_step_survives_with_them(self):
        # Un événement sans étape oblige à relire tout le journal pour
        # savoir OÙ il s'est produit.
        obj = self.upgrade()
        obj.print_step("4.2.I - Migrate database")
        obj.record_event("test", "database_cleanup", 1)
        obj.close_step_log()
        lst = status.merge_events({"config_database_name": "essai_db"})
        self.assertEqual(lst[0]["step"], "4.2.I - Migrate database")

    def test_memory_and_disk_are_not_counted_twice(self):
        obj = self.upgrade()
        obj.print_step("2 - Succeed update all addons")
        obj.record_event("test", "smoke_public_url", 0)
        obj.close_step_log()
        # `obj.dct_progression` porte DÉJÀ l'événement : les deux sources se
        # recouvrent, et les additionner le montrerait en double.
        self.assertEqual(len(status.merge_events(obj.dct_progression)), 1)

    def test_a_truncated_line_does_not_lose_the_others(self):
        # Une écriture interrompue laisse une ligne tronquée ; refuser le
        # fichier en bloc perdrait tout pour une seule ligne.
        obj = self.upgrade()
        obj.print_step("1 - Import database from zip")
        obj.record_event("test", "premier", 0)
        obj.close_step_log()
        chemin = os.path.join(
            "private",
            "odoo",
            "migration",
            "essai_db",
            "step_log",
            "events.jsonl",
        )
        with open(chemin, "a") as handle:
            handle.write('{"at": "x", "name": "coup\n')
        obj.record_event("test", "dernier", 0)
        noms = [
            x["name"]
            for x in status.merge_events({"config_database_name": "essai_db"})
        ]
        self.assertIn("premier", noms)
        self.assertIn("dernier", noms)

    def test_a_step_header_becomes_the_current_step(self):
        """La cause racine de « ça semble global ».

        Vingt en-têtes d'étape passent par `add_comment_progression` contre
        sept par `print_step`, et toute la boucle des paliers n'utilise que
        la première. Ne poser l'étape courante que dans l'autre laissait
        chaque verdict estampillé d'une étape périmée.
        """
        obj = self.upgrade()
        obj.add_comment_progression("4.2 - Ready to work with version 15")
        obj.record_event("test", "smoke_public_url", 0)
        obj.close_step_log()
        lst = status.merge_events({"config_database_name": "essai_db"})
        self.assertEqual(lst[0]["step"], "4.2 - Ready to work with version 15")

    def test_a_step_header_opens_its_log_too(self):
        # Même raison : sans cela, la sortie des commandes d'un palier
        # allait dans le fichier de l'étape d'AVANT.
        obj = self.upgrade()
        obj.add_comment_progression("4.2 - Migrate database")
        obj.note_step_log("quelque chose")
        obj.close_step_log()
        self.assertIsNotNone(
            status.step_log_path(
                {"config_database_name": "essai_db"}, "4.2 - Migrate database"
            )
        )

    def test_two_bumps_do_not_share_a_step(self):
        # Le symptôme exact : six paliers, un seul nom d'étape.
        obj = self.upgrade()
        for palier in ("4.1 - version 14", "4.2 - version 15"):
            obj.add_comment_progression(palier)
            obj.record_event("test", "smoke_public_url", 0)
        obj.close_step_log()
        lst = status.merge_events({"config_database_name": "essai_db"})
        self.assertEqual(
            [x["step"] for x in lst], ["4.1 - version 14", "4.2 - version 15"]
        )

    def test_logs_written_before_the_name_are_brought_back(self):
        """Les deux premières étapes tournent avant qu'on nomme la base.

        Leurs journaux atterrissaient sous « sans-nom », c'est-à-dire hors
        de la migration à laquelle ils appartiennent : mesuré sur la VM,
        deux fichiers invisibles depuis l'écran d'état, et l'on cherchait
        des logs manquants qui étaient simplement à côté.
        """
        from script.todo import todo_upgrade as tu

        anonyme = TodoUpgrade.__new__(TodoUpgrade)
        anonyme.dct_progression = {}
        anonyme.lst_command_executed = []
        anonyme.write_config = lambda: None
        anonyme.add_comment_progression("0 - Inspect zip")
        anonyme.note_step_log("avant le nom")
        anonyme.close_step_log()
        self.assertTrue(
            os.path.isdir(
                os.path.join(
                    "private",
                    "odoo",
                    "migration",
                    tu.UNNAMED_MIGRATION,
                    "step_log",
                )
            )
        )
        # La base prend son nom : les journaux doivent la rejoindre.
        nomme = self.upgrade()
        nomme.log_dir()
        tail, _total = status.step_log_tail(
            {"config_database_name": "essai_db"}, "0 - Inspect zip"
        )
        self.assertIn("avant le nom", "\n".join(tail))

    def test_the_unnamed_folder_is_left_empty_behind(self):
        from script.todo import todo_upgrade as tu

        anonyme = TodoUpgrade.__new__(TodoUpgrade)
        anonyme.dct_progression = {}
        anonyme.lst_command_executed = []
        anonyme.write_config = lambda: None
        anonyme.add_comment_progression("0 - Inspect zip")
        anonyme.note_step_log("x")
        anonyme.close_step_log()
        self.upgrade().log_dir()
        self.assertFalse(
            os.path.isdir(
                os.path.join(
                    "private",
                    "odoo",
                    "migration",
                    tu.UNNAMED_MIGRATION,
                    "step_log",
                )
            )
        )

    def test_an_existing_file_is_APPENDED_to_not_replaced(self):
        # Une reprise peut avoir écrit des deux côtés ; écraser perdrait
        # le premier passage.
        nomme = self.upgrade()
        nomme.add_comment_progression("0 - Inspect zip")
        nomme.note_step_log("déjà là")
        nomme.close_step_log()
        anonyme = TodoUpgrade.__new__(TodoUpgrade)
        anonyme.dct_progression = {}
        anonyme.lst_command_executed = []
        anonyme.write_config = lambda: None
        anonyme.add_comment_progression("0 - Inspect zip")
        anonyme.note_step_log("venu de sans-nom")
        anonyme.close_step_log()
        neuf = self.upgrade()
        neuf.log_dir()
        texte = "\n".join(
            status.step_log_tail(
                {"config_database_name": "essai_db"}, "0 - Inspect zip"
            )[0]
        )
        self.assertIn("déjà là", texte)
        self.assertIn("venu de sans-nom", texte)

    def test_a_migration_without_a_database_writes_nowhere(self):
        obj = self.upgrade(database=None)
        obj.dct_progression = {}
        obj.print_step("0 - Inspect zip")
        obj.record_event("test", "x", 0)
        obj.close_step_log()
        # Rien ne doit planter, et rien ne doit se perdre ailleurs.
        self.assertEqual(len(obj.dct_progression["lst_event"]), 1)


class TestTheStepLogs(DiskCase):
    def test_each_step_gets_its_own_file(self):
        obj = self.upgrade()
        for etape in ("0 - Inspect zip", "4.2.C - Install module"):
            obj.print_step(etape)
            obj.note_step_log("quelque chose")
        obj.close_step_log()
        dossier = os.path.join(
            "private", "odoo", "migration", "essai_db", "step_log"
        )
        self.assertEqual(
            sorted(x for x in os.listdir(dossier) if x.endswith(".log")),
            ["0_inspect-zip.log", "4.2.c_install-module.log"],
        )

    def test_the_numbered_prefix_keeps_them_in_order(self):
        # Un `ls` trié est la première chose qu'on fait dans ce répertoire.
        self.assertTrue(
            status.step_slug("4.2.C - Install module").startswith("4.2.c")
        )

    def test_replaying_a_step_ADDS_to_what_was_known(self):
        # Une étape rejouée après un retour en arrière ne doit pas effacer
        # l'historique : c'est justement ce qu'on vient relire.
        obj = self.upgrade()
        obj.print_step("2 - Succeed update all addons")
        obj.note_step_log("premier passage")
        obj.close_step_log()
        obj.print_step("2 - Succeed update all addons")
        obj.note_step_log("second passage")
        obj.close_step_log()
        tail, _total = status.step_log_tail(
            {"config_database_name": "essai_db"},
            "2 - Succeed update all addons",
        )
        texte = "\n".join(tail)
        self.assertIn("premier passage", texte)
        self.assertIn("second passage", texte)

    def test_the_command_and_its_verdict_are_kept(self):
        # `run_on_terminal` n'a PAS de sortie capturable — un tube y ferait
        # renoncer les pleins écrans. On garde au moins ces deux-là.
        obj = self.upgrade()
        obj.print_step("3 - Clean up database")
        obj.run_on_terminal("true")
        obj.close_step_log()
        texte = "\n".join(
            status.step_log_tail(
                {"config_database_name": "essai_db"}, "3 - Clean up database"
            )[0]
        )
        self.assertIn("$ true", texte)
        self.assertIn("-> 0", texte)

    def test_a_step_never_run_has_no_file(self):
        self.assertIsNone(
            status.step_log_path(
                {"config_database_name": "essai_db"}, "9 - jamais"
            )
        )

    def test_the_name_is_computed_in_ONE_place(self):
        # Deux formules dériveraient, et l'écran chercherait un fichier que
        # personne n'écrit — sans rien signaler, puisqu'un fichier absent
        # se lit comme une étape sans journal.
        self.assertIs(TodoUpgrade.step_slug, status.step_slug)


class TestTheCommandOutputItself(DiskCase):
    """Ce qui manquait vraiment : ce que les commandes ont RÉPONDU."""

    def test_the_lines_land_in_the_step_log(self):
        from script.execute import execute as ex

        obj = self.upgrade()
        obj.execute = ex.Execute()
        obj.print_step("2 - Succeed update all addons")
        with redirect_stdout(io.StringIO()):
            obj.todo_upgrade_execute(
                "echo première && echo seconde >&2", wait_at_error=False
            )
        obj.close_step_log()
        texte = "\n".join(
            status.step_log_tail(
                {"config_database_name": "essai_db"},
                "2 - Succeed update all addons",
            )[0]
        )
        self.assertIn("première", texte)
        # stderr aussi : c'est là que les erreurs d'Odoo se trouvent.
        self.assertIn("seconde", texte)

    def test_a_broken_sink_never_breaks_the_command(self):
        # Journaliser est un service rendu, pas une condition de marche.
        from script.execute import execute as ex

        class PuitsCasse:
            def write(self, texte):
                raise OSError("disque plein")

        moteur = ex.Execute()
        moteur.log_sink = PuitsCasse()
        with redirect_stdout(io.StringIO()):
            status_code = moteur.exec_command_live(
                "echo bonjour", source_erplibre=False, quiet=True
            )
        self.assertEqual(status_code, 0)

    def test_nothing_is_logged_without_a_step(self):
        from script.execute import execute as ex

        moteur = ex.Execute()
        self.assertIsNone(getattr(moteur, "log_sink", None))


class TestColour(Base):
    """Distinguer d'un coup d'œil ce qui a été LANCÉ du reste.

    Une liste de commandes en texte plat se confond avec ses titres dès
    qu'elle dépasse l'écran, et c'est justement quand elle le dépasse qu'on
    la lit.
    """

    def rapport(self, colour):
        dct = progression()
        return status.render_text(dct, colour=colour)

    def test_the_commands_are_coloured(self):
        texte = self.rapport(True)
        self.assertIn(status.ANSI["cmd"], texte)

    def test_a_verdict_wears_the_colour_of_its_meaning(self):
        # 1 n'est pas une panne : c'est « il y a quelque chose à regarder ».
        # Le peindre en rouge inquiéterait pour rien.
        self.assertEqual(status.VERDICT_COLOUR[0], "ok")
        self.assertEqual(status.VERDICT_COLOUR[1], "warn")
        self.assertEqual(status.VERDICT_COLOUR[2], "fail")

    def test_a_failed_command_is_red(self):
        self.assertIn(status.ANSI["fail"], self.rapport(True))

    def test_every_colour_is_closed(self):
        # Une séquence ouverte teinte tout ce qui suit, y compris l'invite
        # du terminal une fois l'outil terminé.
        texte = self.rapport(True)
        ouvertures = sum(texte.count(code) for code in status.ANSI.values())
        self.assertEqual(texte.count(status.RESET), ouvertures)

    def test_plain_output_carries_no_escape_at_all(self):
        self.assertNotIn("\033", self.rapport(False))

    def test_paint_returns_the_text_untouched_when_off(self):
        self.assertEqual(status.paint("make", "cmd", False), "make")

    def test_an_unknown_colour_never_invents_one(self):
        self.assertEqual(status.paint("make", "mauve", True), "make")


class TestWhenColourWouldBeAMistake(Base):
    """Un tube n'est pas un écran, et chacun de ces refus a coûté.

    Un fichier de journal truffé de codes d'échappement, un `grep` qui ne
    trouve plus rien, un terminal qui les affiche en clair.
    """

    def setUp(self):
        super().setUp()
        self.avant = {cle: os.environ.get(cle) for cle in ("NO_COLOR", "TERM")}

        def remettre():
            for cle, valeur in self.avant.items():
                if valeur is None:
                    os.environ.pop(cle, None)
                else:
                    os.environ[cle] = valeur

        self.addCleanup(remettre)

    class FauxEcran:
        def __init__(self, tty):
            self.tty = tty

        def isatty(self):
            return self.tty

    def test_a_pipe_gets_no_colour(self):
        os.environ["TERM"] = "xterm"
        os.environ.pop("NO_COLOR", None)
        self.assertFalse(status.supports_colour(self.FauxEcran(False)))

    def test_a_terminal_does(self):
        os.environ["TERM"] = "xterm"
        os.environ.pop("NO_COLOR", None)
        self.assertTrue(status.supports_colour(self.FauxEcran(True)))

    def test_NO_COLOR_is_honoured(self):
        # Convention respectée par la plupart des outils : la contredire
        # oblige à nettoyer une sortie à la main.
        os.environ["TERM"] = "xterm"
        os.environ["NO_COLOR"] = "1"
        self.assertFalse(status.supports_colour(self.FauxEcran(True)))

    def test_a_dumb_terminal_gets_none(self):
        os.environ.pop("NO_COLOR", None)
        os.environ["TERM"] = "dumb"
        self.assertFalse(status.supports_colour(self.FauxEcran(True)))

    def test_a_stream_that_cannot_answer_gets_none(self):
        os.environ["TERM"] = "xterm"
        os.environ.pop("NO_COLOR", None)

        class Muet:
            def isatty(self):
                raise OSError("fermé")

        self.assertFalse(status.supports_colour(Muet()))

    def test_the_report_decides_by_itself_when_not_told(self):
        import inspect

        source = inspect.getsource(status.render_text)
        self.assertIn("colour = supports_colour()", source)


class TestTheFullScreenColoursToo(Base):
    def test_the_pane_can_be_coloured(self):
        lst = tui.rows(progression())
        etape = [x for x in lst if x["kind"] == "step"][0]
        self.assertIn(
            status.ANSI["cmd"],
            tui.pane_text(progression(), etape, colour=True),
        )

    def test_it_stays_plain_by_default(self):
        # `pane_text` sert aussi aux tests et au repli texte.
        lst = tui.rows(progression())
        etape = [x for x in lst if x["kind"] == "step"][0]
        self.assertNotIn("\033", tui.pane_text(progression(), etape))

    def test_rich_decodes_the_colours_instead_of_showing_them(self):
        from rich.text import Text

        lst = tui.rows(progression())
        etape = [x for x in lst if x["kind"] == "step"][0]
        texte = Text.from_ansi(
            tui.pane_text(progression(), etape, colour=True)
        )
        self.assertNotIn("\033", texte.plain)
        self.assertTrue(texte.spans)

    def test_a_bracket_in_a_command_is_NOT_eaten_as_markup(self):
        # Piège latent d'avant la couleur : Textual interprète le balisage
        # Rich, et « [1] » disparaissait sans que rien ne le signale.
        from rich.text import Text

        dct = progression(
            command_executed=["# 2 - Update", "make config [1] et [/bold]"]
        )
        lst = tui.rows(dct)
        etape = [x for x in lst if x["kind"] == "step"][0]
        texte = Text.from_ansi(tui.pane_text(dct, etape, colour=True))
        self.assertIn("[1]", texte.plain)
        self.assertIn("[/bold]", texte.plain)

    def test_the_screen_goes_through_from_ansi(self):
        import inspect

        # Le rendu est sorti de la classe pour la rendre testable : c'est
        # `show_pane` qui porte maintenant les deux propriétés.
        source = inspect.getsource(tui.show_pane)
        self.assertIn("Text.from_ansi", source)
        self.assertIn("colour=True", source)


class TestHowLongItTook(Base):
    """Du premier écrit à la dernière écriture du journal.

    La progression est réécrite après chaque geste, donc sa date de mise à
    jour EST la fin — ou l'instant présent si la migration tourne encore.
    """

    def dct(self, debut, fin):
        return progression(date_create=debut, date_update=fin)

    def test_it_counts_from_the_start_to_the_last_write(self):
        info = status.overview(
            self.dct("2026-08-19 09:06:27", "2026-08-19 10:19:18")
        )
        self.assertEqual(info["elapsed"], "1 h 12 min")

    def test_a_short_run_is_given_in_minutes(self):
        info = status.overview(
            self.dct("2026-08-19 09:06:00", "2026-08-19 09:41:00")
        )
        self.assertEqual(info["elapsed"], "35 min")

    def test_a_long_run_is_given_in_days(self):
        info = status.overview(
            self.dct("2026-08-17 09:00:00", "2026-08-19 11:30:00")
        )
        self.assertIn("j", info["elapsed"])

    def test_a_missing_date_never_invents_a_duration(self):
        self.assertEqual(status.overview(self.dct(None, None))["elapsed"], "?")

    def test_the_report_shows_it(self):
        texte = status.render_text(
            self.dct("2026-08-19 09:06:27", "2026-08-19 10:19:18"),
            colour=False,
        )
        self.assertIn("1 h 12 min", texte)

    def test_the_full_screen_shows_it_too(self):
        texte = tui.head_text(
            self.dct("2026-08-19 09:06:27", "2026-08-19 10:19:18")
        )
        self.assertIn("1 h 12 min", texte)

    def test_it_is_computed_in_ONE_place(self):
        # L'écran de statistiques porte déjà ce calcul. Deux formules
        # donneraient deux durées pour la même migration selon l'écran
        # qu'on ouvre.
        import inspect

        source = inspect.getsource(status.elapsed)
        self.assertIn(
            "from script.todo.migration_stats import fmt_delay", source
        )


class TestReadingTheLogForTheUser(DiskCase):
    """Compter les erreurs à la place de quelqu'un.

    Un journal d'étape atteint treize mégaoctets — mesuré. Personne ne le
    lit, et la question qu'on se pose devant lui tient en deux mots : où
    est-ce que ça a mal tourné ? C'est cette question-là que l'écran doit
    savoir répondre sans qu'on ouvre le fichier.
    """

    JOURNAL = (
        "2026-08-19 09:21:07,074 132948 ERROR base13"
        " odoo.tools.translate: couldn't read translation file\n"
        "Traceback (most recent call last):\n"
        "2026-08-19 09:34:27,088 133771 ERROR base14"
        " odoo.modules.registry: Model account.bank.statement.import"
        " has no table.\n"
        "2026-08-19 09:34:28,088 133771 ERROR base14"
        " odoo.modules.registry: Model account.bank.statement.import"
        " has no table.\n"
        "2026-08-19 09:44:51,959 134592 CRITICAL base15"
        " odoo.service.server: Failed to initialize database.\n"
        "2026-08-19 09:44:52,000 134592 WARNING base15"
        " odoo.schema: unable to add constraint\n"
        "2026-08-19 09:44:53,000 134592 INFO base15"
        " odoo.modules.loading: Modules loaded.\n"
    )

    def poser(self, contenu=None, etape="4 - Upgrade"):
        obj = self.upgrade()
        obj.add_comment_progression(etape)
        obj.close_step_log()
        chemin = os.path.join(
            "private",
            "odoo",
            "migration",
            "essai_db",
            "step_log",
            status.step_slug(etape) + ".log",
        )
        with open(chemin, "w") as handle:
            handle.write(contenu if contenu is not None else self.JOURNAL)
        # La progression de l'objet, pas un dict nu : c'est elle qui porte
        # `command_executed`, donc le découpage par étape.
        return obj.dct_progression

    def test_it_counts_the_severities(self):
        scan = status.step_log_scan(self.poser(), "4 - Upgrade")
        self.assertEqual(scan["count"]["ERROR"], 3)
        self.assertEqual(scan["count"]["CRITICAL"], 1)
        self.assertEqual(scan["count"]["WARNING"], 1)
        self.assertEqual(scan["count"]["TRACEBACK"], 1)

    def test_the_severe_ones_are_summed(self):
        # ERROR et CRITICAL, pas WARNING : une migration en produit des
        # milliers, et un compte qui les inclut ne veut plus rien dire.
        scan = status.step_log_scan(self.poser(), "4 - Upgrade")
        self.assertEqual(status.severe_count(scan), 4)

    def test_the_same_message_is_counted_ONCE(self):
        # Quarante-huit fois « Model X has no table » est UN problème vu
        # quarante-huit fois, pas quarante-huit problèmes.
        scan = status.step_log_scan(self.poser(), "4 - Upgrade")
        modele = [e for e in scan["errors"] if "has no table" in e["message"]]
        self.assertEqual(len(modele), 1)
        self.assertEqual(modele[0]["times"], 2)

    def test_the_loudest_comes_first(self):
        scan = status.step_log_scan(self.poser(), "4 - Upgrade")
        self.assertEqual(scan["errors"][0]["times"], 2)

    def test_each_error_carries_its_database(self):
        # Six paliers ont pu écrire dans le même fichier : sans la base,
        # on ne sait pas lequel a souffert.
        scan = status.step_log_scan(self.poser(), "4 - Upgrade")
        bases = {e["database"] for e in scan["errors"]}
        self.assertEqual(bases, {"base13", "base14", "base15"})

    def test_it_carries_the_logger_too(self):
        scan = status.step_log_scan(self.poser(), "4 - Upgrade")
        loggers = {e["logger"] for e in scan["errors"]}
        self.assertIn("odoo.tools.translate", loggers)

    def test_warnings_are_never_listed_as_errors(self):
        scan = status.step_log_scan(self.poser(), "4 - Upgrade")
        self.assertNotIn(
            "unable to add constraint",
            " ".join(e["message"] for e in scan["errors"]),
        )

    def test_a_step_without_a_log_counts_zero(self):
        self.assertEqual(
            status.severe_count(
                status.step_log_scan(
                    {"config_database_name": "essai_db"}, "9 - rien"
                )
            ),
            0,
        )

    def test_a_healthy_log_shows_no_alarm(self):
        dct = self.poser(
            "2026-08-19 09:00:00,000 1 INFO db odoo.modules: Modules loaded.\n"
        )
        self.assertEqual(
            status.severe_count(status.step_log_scan(dct, "4 - Upgrade")), 0
        )
        # La LIGNE d'étape, pas tout le rapport : celui-ci porte toujours
        # l'en-tête « Commandes en échec », qui a le même symbole.
        etapes = status.render_text(dct, colour=False).split("step by step")[1]
        self.assertNotIn("❌", etapes)

    def test_the_report_names_the_count_and_the_top_errors(self):
        texte = status.render_text(self.poser(), colour=False)
        self.assertIn("❌ 4", texte)
        self.assertIn("has no table", texte)

    def test_the_full_screen_lists_them_with_their_source(self):
        dct = self.poser()
        etape = [x for x in tui.rows(dct) if x["kind"] == "step"][0]
        texte = tui.pane_text(dct, etape, show_log=False)
        self.assertIn("×2", texte)
        self.assertIn("odoo.modules.registry", texte)
        self.assertIn("base14", texte)

    def test_the_left_column_shows_the_count(self):
        dct = self.poser()
        etape = [x for x in tui.rows(dct) if x["kind"] == "step"][0]
        self.assertEqual(etape["severe"], "4")

    def test_a_clean_step_leaves_the_column_empty(self):
        # Un « 0 » dans chaque ligne n'apprend rien et occupe la place.
        dct = self.poser(
            "2026-08-19 09:00:00,000 1 INFO db odoo.modules: ok\n"
        )
        etape = [x for x in tui.rows(dct) if x["kind"] == "step"][0]
        self.assertEqual(etape["severe"], "")


class TestReadingItTwiceIsFree(DiskCase):
    """L'écran se redessine à chaque touche.

    Relire treize mégaoctets à chaque frappe rendrait l'écran inutilisable.
    """

    def test_the_second_read_does_not_touch_the_disk(self):
        obj = self.upgrade()
        obj.add_comment_progression("4 - Upgrade")
        obj.close_step_log()
        chemin = os.path.join(
            "private",
            "odoo",
            "migration",
            "essai_db",
            "step_log",
            status.step_slug("4 - Upgrade") + ".log",
        )
        with open(chemin, "w") as handle:
            handle.write("2026-08-19 09:00:00,000 1 ERROR db odoo.x: boum\n")
        dct = {"config_database_name": "essai_db"}
        premier = status.step_log_scan(dct, "4 - Upgrade")
        lectures = []
        vrai_open = open

        def compter(*args, **kwargs):
            lectures.append(args[0])
            return vrai_open(*args, **kwargs)

        import builtins

        builtins.open = compter
        self.addCleanup(setattr, builtins, "open", vrai_open)
        second = status.step_log_scan(dct, "4 - Upgrade")
        self.assertEqual(premier, second)
        self.assertEqual([x for x in lectures if str(x).endswith(".log")], [])

    def test_a_changed_file_IS_read_again(self):
        # Sinon « r » ne rafraîchirait rien : la migration écrit pendant
        # qu'on regarde.
        obj = self.upgrade()
        obj.add_comment_progression("4 - Upgrade")
        obj.close_step_log()
        chemin = os.path.join(
            "private",
            "odoo",
            "migration",
            "essai_db",
            "step_log",
            status.step_slug("4 - Upgrade") + ".log",
        )
        dct = {"config_database_name": "essai_db"}
        with open(chemin, "w") as handle:
            handle.write("2026-08-19 09:00:00,000 1 ERROR db odoo.x: un\n")
        self.assertEqual(
            status.severe_count(status.step_log_scan(dct, "4 - Upgrade")), 1
        )
        with open(chemin, "a") as handle:
            handle.write("2026-08-19 09:00:01,000 1 ERROR db odoo.y: deux\n")
        self.assertEqual(
            status.severe_count(status.step_log_scan(dct, "4 - Upgrade")), 2
        )


class TestSeparatingCommandsFromLogs(Base):
    """Les deux mélangés dans un même panneau se confondent.

    La liste des commandes dit ce qui a été LANCÉ ; le journal dit ce que
    cela a RÉPONDU. Ce sont deux lectures différentes, et l'une noie
    l'autre : un `update_addons_all` écrit des dizaines de milliers de
    lignes au-dessus desquelles trois commandes disparaissent.
    """

    def dct(self):
        return progression(command_executed=["# 2 - Update", "./run.sh -d db"])

    def etape(self, dct):
        return [x for x in tui.rows(dct) if x["kind"] == "step"][0]

    def test_hiding_the_log_keeps_the_commands(self):
        dct = self.dct()
        texte = tui.pane_text(dct, self.etape(dct), show_log=False)
        self.assertIn("./run.sh -d db", texte)

    def test_hiding_it_never_hides_it_SILENTLY(self):
        # Un panneau qui se vide sans un mot se lit comme « il n'y a rien »,
        # ce qui est exactement le contraire de ce qui vient de se passer.
        import tempfile

        dossier = tempfile.mkdtemp(prefix="erplibre_essai_")
        avant = os.getcwd()
        os.chdir(dossier)
        self.addCleanup(shutil.rmtree, dossier, True)
        self.addCleanup(os.chdir, avant)
        chemin = os.path.join("private", "odoo", "migration", "db", "step_log")
        os.makedirs(chemin)
        with open(
            os.path.join(chemin, status.step_slug("2 - Update") + ".log"), "w"
        ) as handle:
            handle.write("\n".join(f"ligne {i}" for i in range(50)))
        dct = self.dct()
        dct["config_database_name"] = "db"
        texte = tui.pane_text(dct, self.etape(dct), show_log=False)
        self.assertIn("50", texte)
        self.assertNotIn("ligne 49", texte)

    def test_showing_it_says_how_much_is_cut(self):
        # « il manque des logs » venait de là : on montrait la fin sans
        # dire qu'on cachait le début.
        lst, total = ([f"l{i}" for i in range(400)], 12843)
        self.assertLess(len(lst), total)

    def test_the_tail_reports_the_total(self):
        import tempfile

        dossier = tempfile.mkdtemp(prefix="erplibre_essai_")
        avant = os.getcwd()
        os.chdir(dossier)
        self.addCleanup(shutil.rmtree, dossier, True)
        self.addCleanup(os.chdir, avant)
        chemin = os.path.join("private", "odoo", "migration", "db", "step_log")
        os.makedirs(chemin)
        with open(
            os.path.join(chemin, status.step_slug("2 - Update") + ".log"), "w"
        ) as handle:
            handle.write("\n".join(f"ligne {i}" for i in range(1000)))
        lst, total = status.step_log_tail(
            {"config_database_name": "db"}, "2 - Update", lines=400
        )
        self.assertEqual(total, 1000)
        self.assertEqual(len(lst), 400)
        self.assertEqual(lst[-1], "ligne 999")

    def test_a_step_without_a_log_reports_zero(self):
        self.assertEqual(
            status.step_log_tail({"config_database_name": "db"}, "9 - rien"),
            ([], 0),
        )


class TestTheThreePanelStates(Base):
    """Un simple bascule ne libérait que quatre lignes.

    Ce qui prend la place, c'est la COLONNE de gauche — et sur un journal
    de serveur, chaque caractère gagné en largeur compte. D'où trois états,
    du plus complet au plus dépouillé.
    """

    def test_the_first_state_shows_everything(self):
        self.assertEqual(tui.panel_visibility(0), (True, True))

    def test_the_second_drops_the_summary(self):
        self.assertEqual(tui.panel_visibility(1), (False, True))

    def test_the_third_leaves_the_detail_alone(self):
        self.assertEqual(tui.panel_visibility(2), (False, False))

    def test_it_comes_back_round(self):
        # Sans retour, le troisième état serait un cul-de-sac : la liste
        # cachée, on ne peut plus changer d'entrée.
        self.assertEqual(tui.panel_visibility(3), tui.panel_visibility(0))

    def test_there_are_exactly_three(self):
        self.assertEqual(len(tui.PANELS), 3)

    def test_each_state_has_a_name(self):
        # Un panneau qui disparaît sans un mot se lit comme un écran cassé.
        noms = {tui.panel_label(i) for i in range(3)}
        self.assertEqual(len(noms), 3)
        for nom in noms:
            self.assertTrue(nom.strip())

    def test_p_is_bound_to_the_cycle(self):
        app = tui.build_app(progression())
        action = [
            entree[1] for entree in app.BINDINGS if "p" in entree[0].split(",")
        ]
        self.assertEqual(action, ["cycle_panels"])

    def test_the_name_is_shown_where_it_stays_visible(self):
        # Le sous-titre est dans l'en-tête de Textual, qui reste affiché
        # dans les trois états — contrairement au panneau de résumé.
        import inspect

        source = inspect.getsource(tui.apply_panels)
        self.assertIn("app.sub_title", source)


class TestTheGuardsThatCameOutOfTheClass(Base):
    def test_no_row_selected_is_not_an_error(self):
        self.assertIsNone(tui.current_row([], 0))

    def test_an_index_past_the_end_is_not_an_error(self):
        # Un rafraîchissement peut raccourcir la liste sous le curseur.
        self.assertIsNone(tui.current_row([{"a": 1}], 5))

    def test_rereading_without_a_path_yields_nothing(self):
        self.assertIsNone(tui.reread(None))

    def test_the_width_stays_between_its_bounds(self):
        app = tui.build_app(progression())
        self.assertLess(app.LEFT_MIN, app.LEFT_MAX)
        self.assertGreaterEqual(app.left_width, app.LEFT_MIN)
        self.assertLessEqual(app.left_width, app.LEFT_MAX)


class TestTheKeyboard(Base):
    """Ce que l'écran promet dans son pied de page doit exister."""

    def app(self):
        return tui.build_app(progression(), path="/un/chemin.json")

    def touches(self):
        return {
            touche
            for entree in self.app().BINDINGS
            for touche in entree[0].split(",")
        }

    def test_every_promised_key_is_bound(self):
        attendues = {"q", "escape", "r", "l", "p", "plus", "minus"}
        self.assertTrue(attendues <= self.touches(), self.touches())

    def test_each_binding_has_an_action_that_exists(self):
        # Un raccourci annoncé dont l'action manque échoue à la frappe,
        # c'est-à-dire au pire moment.
        app = self.app()
        for _touches, action, _libelle in app.BINDINGS:
            self.assertTrue(hasattr(app, f"action_{action}"), action)

    def test_the_width_is_bounded_on_both_sides(self):
        # Une colonne de zéro ne se retrouve plus ; une qui mange tout
        # l'écran ne laisse rien à lire.
        app = self.app()
        for _ in range(50):
            app.left_width = max(
                app.LEFT_MIN, min(app.LEFT_MAX, app.left_width - app.LEFT_STEP)
            )
        self.assertEqual(app.left_width, app.LEFT_MIN)
        for _ in range(50):
            app.left_width = max(
                app.LEFT_MIN, min(app.LEFT_MAX, app.left_width + app.LEFT_STEP)
            )
        self.assertEqual(app.left_width, app.LEFT_MAX)

    def test_refreshing_rereads_the_disk(self):
        """La migration ÉCRIT pendant qu'on regarde.

        Sans cela il fallait fermer et rouvrir l'écran pour voir le palier
        suivant — sur une migration de plusieurs heures, on le fait.
        """
        import inspect

        # La relecture est sortie de la classe pour la rendre testable :
        # on vérifie donc les DEUX moitiés, la lecture et le remontage.
        self.assertIn("status.read(path)", inspect.getsource(tui.reread))
        self.assertIn(
            "self.lst_row = rows(self.dct)", inspect.getsource(tui.build_app)
        )

    def test_refreshing_without_a_path_does_nothing(self):
        app = tui.build_app(progression(), path=None)
        app.action_refresh()  # ne doit pas lever

    def test_the_log_toggle_flips(self):
        app = self.app()
        self.assertTrue(app.show_log)


class TestTheStatisticsScreenOffersIt(Base):
    """L'écran de statistiques répond « qu'a-t-on supprimé, et pourquoi ».

    L'état, lui, répond « où en est-on, et qu'est-ce qui a cassé ». Deux
    questions voisines, posées au même moment : les séparer par un menu
    plutôt que par deux commandes à retenir est ce qui les rend
    utilisables.
    """

    def stats(self, lst_answer):
        obj = TodoUpgrade.__new__(TodoUpgrade)
        self.vu = []
        obj.show_migration_status = lambda: self.vu.append("ouvert")
        reponses = iter(lst_answer)
        obj.ask = lambda prompt, default="": next(reponses)
        obj.print_stats = staticmethod(lambda ctx, stats: None)
        obj.read_progression = staticmethod(
            lambda: {"config_database_name": "db"}
        )
        obj.resume_context = lambda dct: {"steps": [], "versions": []}
        return obj

    def test_t_opens_the_full_screen(self):
        import script.todo.todo_upgrade as tu

        obj = self.stats(["t", "0"])
        original_exists = tu.os.path.exists
        tu.os.path.exists = lambda path: True
        self.addCleanup(setattr, tu.os.path, "exists", original_exists)
        import script.todo.migration_stats as ms

        original = ms.compute
        ms.compute = lambda *a, **kw: {
            "uninstall": {},
            "journal": {"comments": [], "commands": []},
            "origin_count": 0,
            "evolution": [],
            "removed_total": 0,
            "missing": [],
            "duplicate": [],
            "fixes": [],
            "cow": [],
            "delay": "0s",
        }
        self.addCleanup(setattr, ms, "compute", original)
        with redirect_stdout(io.StringIO()):
            obj.show_stats()
        self.assertEqual(self.vu, ["ouvert"])

    def test_the_menu_announces_it(self):
        import inspect

        source = inspect.getsource(TodoUpgrade.show_stats)
        self.assertIn("Migration state (full screen)", source)
        self.assertIn('answer == "t"', source)

    def test_it_is_the_SAME_letter_as_the_prompts(self):
        # Une lettre qui change de sens d'un écran à l'autre ne s'apprend
        # pas. Les deux endroits doivent tester la même.
        import inspect

        self.assertIn(
            'reponse == "t"', inspect.getsource(TodoUpgrade.ask_gate)
        )
        self.assertIn(
            'answer == "t"', inspect.getsource(TodoUpgrade.show_stats)
        )

    def test_looking_returns_to_the_statistics(self):
        # Comme dans les invites : regarder n'est pas répondre.
        import inspect

        source = inspect.getsource(TodoUpgrade.show_stats)
        debut = source.index('answer == "t"')
        self.assertIn("continue", source[debut : debut + 400])


class TestNothingOnThatScreenCanHang(Base):
    """L'écran est atteint APRÈS la question d'auto-exécution.

    `ask_ui` est la toute première question posée ensuite, et elle était un
    `input()` nu : une migration automatique s'arrêtait là, avant même
    d'avoir commencé, sans que rien ne le signale.
    """

    def test_the_interface_question_goes_through_the_timer(self):
        import inspect

        source = inspect.getsource(TodoUpgrade.ask_ui)
        self.assertIn("auto_ask.ask(", source)
        # L'APPEL, pas le mot : le commentaire du correctif nomme lui-même
        # ce qu'il remplace, et le chercher à l'aveugle se déclenche sur la
        # prose. Deuxième fois que ce piège se referme sur moi.
        self.assertNotIn("= input(", source)

    def test_the_statistics_menu_too(self):
        import inspect

        source = inspect.getsource(TodoUpgrade.show_stats)
        self.assertIn("self.ask(", source)
        self.assertNotIn("= input(", source)

    def test_the_default_interface_is_still_the_form(self):
        # Le défaut ne doit pas changer en passant par le lecteur temporisé.
        import script.todo.todo_prefs as prefs

        original = prefs.get
        prefs.get = lambda key: "ask"
        self.addCleanup(setattr, prefs, "get", original)
        from script.todo import auto_ask

        avant = os.environ.pop(auto_ask.ENV_ENABLED, None)
        if avant is not None:
            self.addCleanup(
                os.environ.__setitem__, auto_ask.ENV_ENABLED, avant
            )
        import builtins

        original_input = builtins.input
        builtins.input = lambda prompt="": ""
        self.addCleanup(setattr, builtins, "input", original_input)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(TodoUpgrade.ask_ui(), "tui")


class TestWhatGetsRecorded(Base):
    def upgrade(self):
        obj = TodoUpgrade.__new__(TodoUpgrade)
        obj.dct_progression = {}
        obj.lst_command_executed = []
        obj.write_config = lambda: None
        obj.current_step = "4.2.I - Migrate database"
        return obj

    def test_a_tool_run_keeps_its_verdict(self):
        obj = self.upgrade()
        obj.run_on_terminal = lambda cmd: 1
        self.assertEqual(obj.run_tool("smoke_public_url", "cmd"), 1)
        event = obj.dct_progression["lst_event"][0]
        self.assertEqual(event["kind"], "test")
        self.assertEqual(event["status"], 1)
        self.assertEqual(event["step"], "4.2.I - Migrate database")

    def test_the_list_is_bounded(self):
        # Une migration lance des centaines de commandes ; un fichier qui
        # enfle sans limite coûte plus cher à écrire qu'à lire.
        obj = self.upgrade()
        for index in range(TodoUpgrade.MAX_EVENT + 25):
            obj.record_event("test", f"outil{index}", 0)
        self.assertEqual(
            len(obj.dct_progression["lst_event"]), TodoUpgrade.MAX_EVENT
        )

    def test_the_newest_survive_the_trimming(self):
        obj = self.upgrade()
        for index in range(TodoUpgrade.MAX_EVENT + 3):
            obj.record_event("test", f"outil{index}", 0)
        dernier = obj.dct_progression["lst_event"][-1]
        self.assertEqual(dernier["name"], f"outil{TodoUpgrade.MAX_EVENT + 2}")

    def test_the_step_is_captured_when_it_is_printed(self):
        import inspect

        source = inspect.getsource(TodoUpgrade.print_step)
        self.assertIn("self.current_step = msg", source)

    def test_a_failing_command_is_recorded_before_the_prompt(self):
        # Si l'on répond ctrl+c, l'échec doit tout de même figurer dans
        # l'état : c'est précisément celui qu'on cherchera en revenant.
        import inspect

        # Le menu d'erreur vit dans `_prompt_on_error`, extrait de
        # `todo_upgrade_execute` quand celui-ci a passé le seuil de
        # complexité. Lire les deux : c'est le CHEMIN d'erreur qu'on
        # éprouve, pas une méthode en particulier.
        source = inspect.getsource(
            TodoUpgrade.todo_upgrade_execute
        ) + inspect.getsource(TodoUpgrade._prompt_on_error)
        self.assertLess(
            source.index('record_event("command"'),
            source.index("Error detected"),
        )


if __name__ == "__main__":
    unittest.main()
