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

        source = inspect.getsource(TodoUpgrade.todo_upgrade_execute)
        self.assertLess(
            source.index('record_event("command"'),
            source.index("Error detected"),
        )


if __name__ == "__main__":
    unittest.main()
