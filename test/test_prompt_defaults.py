#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce que fait Entrée, et ce que fait le silence.

Une migration pose une quarantaine de questions dont la réponse était
presque toujours la même. Le mode auto promettait de les prendre « par
défaut » — sauf que le défaut était VIDE partout : il ne faisait rien, et
la moitié des invites vivent de toute façon dans des outils lancés à part,
qui ne savaient rien du mode auto et attendaient une frappe pour toujours.

Deux exigences, donc, et elles sont indissociables :

- ce que fait Entrée doit être ÉCRIT dans la question. Une invite qui
  annonce « y/N » et désinstalle est pire que pas d'invite du tout ;
- aucune invite du chemin de migration ne doit rester un `input()` nu. Ce
  n'est pas une faute qu'on commet exprès, c'est une faute qu'on commet
  par habitude — d'où le test qui refuse la construction elle-même.
"""

import ast
import contextlib
import io
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "script", "odoo", "migration"))
sys.path.insert(0, os.path.join(REPO, "script", "addons"))

from script.todo import auto_ask  # noqa: E402
from script.todo.todo_upgrade import TodoUpgrade  # noqa: E402


class EnvCase(unittest.TestCase):
    def setUp(self):
        avant = {
            key: os.environ.get(key)
            for key in (auto_ask.ENV_ENABLED, auto_ask.ENV_DELAY)
        }

        def remettre():
            for key, value in avant.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.addCleanup(remettre)
        auto_ask.export(False)


class TestTheChannelThatCrossesAFork(EnvCase):
    """L'environnement, parce que c'est le SEUL canal partagé.

    Le désinstalleur de thème, le détecteur de SCSS figé et le test de
    fumée sont des processus séparés. Ils ne voient ni l'objet du pilote ni
    sa mémoire ; sans une variable d'environnement, ils attendraient une
    frappe qui ne vient jamais, et l'automatisation s'arrêterait là — sans
    message, puisque la question, elle, a bien été posée.
    """

    def test_export_puts_it_where_a_child_will_read_it(self):
        auto_ask.export(True, 3)
        self.assertEqual(os.environ[auto_ask.ENV_ENABLED], "1")
        self.assertEqual(os.environ[auto_ask.ENV_DELAY], "3")
        self.assertTrue(auto_ask.enabled())

    def test_turning_it_off_REMOVES_it(self):
        # Y écrire « 0 » laisserait un reste de session précédente décider à
        # notre place : ce qui n'existe pas ne peut pas se tromper.
        auto_ask.export(True, 3)
        auto_ask.export(False)
        self.assertNotIn(auto_ask.ENV_ENABLED, os.environ)
        self.assertFalse(auto_ask.enabled())

    def test_a_real_child_process_takes_the_default(self):
        # LE test qui compte : un vrai sous-processus, un vrai stdin fermé.
        code = (
            "import sys; sys.path.insert(0, %r);"
            "from script.todo import auto_ask;"
            "print(auto_ask.ask('q : ', default='d'))" % REPO
        )
        env = dict(os.environ)
        env[auto_ask.ENV_ENABLED] = "1"
        env[auto_ask.ENV_DELAY] = "1"
        done = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
            cwd=REPO,
            env=env,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("d", done.stdout.strip().splitlines()[-1])

    def test_a_child_without_the_flag_still_asks(self):
        # Hors mode auto, on ne décide à la place de personne : le tuyau
        # fermé rend une ligne vide, et le défaut n'arrive que là.
        code = (
            "import sys; sys.path.insert(0, %r);"
            "from script.todo import auto_ask;"
            "print('RÉPONSE=' + auto_ask.ask('q : ', default='d'))" % REPO
        )
        done = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            input="k\n",
            timeout=30,
            cwd=REPO,
        )
        self.assertIn("RÉPONSE=k", done.stdout)

    def test_a_broken_delay_does_not_freeze_anything(self):
        os.environ[auto_ask.ENV_DELAY] = "plus tard"
        self.assertEqual(auto_ask.delay(), auto_ask.DEFAULT_DELAY)

    def test_a_zero_delay_is_refused(self):
        # Sans fenêtre, on ne peut pas reprendre la main : « auto » ne veut
        # pas dire « sans recours ».
        os.environ[auto_ask.ENV_DELAY] = "0"
        self.assertEqual(auto_ask.delay(), auto_ask.DEFAULT_DELAY)


class TestEnterMeansTheDefault(EnvCase):
    """Hors mode auto AUSSI : sinon la question mentirait à qui la lit."""

    def test_an_empty_answer_takes_the_default(self):
        import builtins

        original = builtins.input
        builtins.input = lambda prompt="": ""
        self.addCleanup(setattr, builtins, "input", original)
        self.assertEqual(auto_ask.ask("q : ", default="y"), "y")

    def test_a_typed_answer_wins(self):
        import builtins

        original = builtins.input
        builtins.input = lambda prompt="": "n"
        self.addCleanup(setattr, builtins, "input", original)
        self.assertEqual(auto_ask.ask("q : ", default="y"), "n")

    def test_the_driver_exports_it_on_every_ask(self):
        # Un outil lancé plus bas doit voir le mode auto même si la question
        # d'activation date d'une reprise précédente.
        import builtins

        original = builtins.input
        builtins.input = lambda prompt="": ""
        self.addCleanup(setattr, builtins, "input", original)
        obj = TodoUpgrade.__new__(TodoUpgrade)
        obj.auto_execute = True
        obj.AUTO_DELAY = 0.2
        with contextlib.redirect_stdout(io.StringIO()):
            obj.ask("q : ", default="y")
        self.assertEqual(os.environ.get(auto_ask.ENV_ENABLED), "1")


class TestTheCountdownSpeaksThePromptsLanguage(EnvCase):
    """« ⏱ → d » nommait une réponse qui n'était PAS au menu.

    L'invite annonce « Entrée = effacer, k = garder » : elle ne mentionne
    « d » nulle part. Afficher la valeur brute obligeait donc à deviner ce
    que l'outil venait de décider — alors que la décision était exactement
    celle qu'Entrée promettait.
    """

    def setUp(self):
        super().setUp()
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def tick(self, default):
        """Forcer le chemin du DÉLAI, celui qui affiche la ligne."""
        import select

        original = select.select
        select.select = lambda r, w, x, t: ([], [], [])
        self.addCleanup(setattr, select, "select", original)
        auto_ask.export(True, 0.01)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            valeur = auto_ask.ask("q : ", default=default)
        return valeur, out.getvalue()

    def test_it_names_what_the_prompt_offered(self):
        _valeur, texte = self.tick("d")
        self.assertIn("Enter", texte)

    def test_the_raw_value_stays_for_precision(self):
        # La nommer reste utile : deux invites voisines peuvent avoir des
        # défauts différents, et l'on relit ces lignes après coup.
        _valeur, texte = self.tick("d")
        self.assertIn("(d)", texte)

    def test_an_empty_default_shows_no_parentheses(self):
        # « Entrée () » n'aurait aucun sens : il n'y a rien à préciser.
        _valeur, texte = self.tick("")
        self.assertIn("Enter", texte)
        self.assertNotIn("(", texte)

    def test_the_answer_itself_is_unchanged(self):
        # L'affichage seul change : ce que la migration reçoit reste la
        # valeur, sinon toutes les invites changeraient de comportement.
        valeur, _texte = self.tick("d")
        self.assertEqual(valeur, "d")

    def test_it_follows_the_language_of_the_migration(self):
        from script.todo import todo_i18n

        todo_i18n._current_lang = "fr"
        _valeur, texte = self.tick("d")
        self.assertIn("Entrée", texte)


class TestNoPromptOfTheMigrationCanHang(unittest.TestCase):
    """Un `input()` nu ne sait rien du mode auto : il attend, pour toujours.

    Vécu à l'échelle du fichier : deux invites avaient échappé au premier
    passage — la prédiction COW et le choix de désinstallation — parce que
    le garde-fou ne regardait qu'`execute_odoo_upgrade`. On regarde
    désormais TOUTES les méthodes du chemin de migration.
    """

    METHODES = (
        "execute_odoo_upgrade",
        # Appelée DEPUIS execute_odoo_upgrade : c'est par elle que le
        # « validez que le dépôt est prêt » arrivait, et il bloquait.
        "internal_module_upgrade",
        "prompt_cow_prediction",
        "prompt_uninstall_theme",
        "prompt_reset_stale_cow_views",
        "prompt_database_cleanup",
        "prompt_smoke_public_url",
        "split_present_missing",
        "prompt_uninstall_missing",
        "todo_upgrade_execute",
    )

    def bare_inputs(self, nom):
        chemin = os.path.join(REPO, "script", "todo", "todo_upgrade.py")
        with open(chemin) as handle:
            tree = ast.parse(handle.read())
        cible = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == nom
        ]
        self.assertEqual(len(cible), 1, f"méthode introuvable : {nom}")
        return [
            node.lineno
            for node in ast.walk(cible[0])
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "input"
        ]

    def test_none_of_them_asks_outside_the_timer(self):
        coupables = {
            nom: self.bare_inputs(nom)
            for nom in self.METHODES
            if self.bare_inputs(nom)
        }
        self.assertEqual(coupables, {}, "invites hors du mode auto")


class TestWhereBlockingIsStillRight(unittest.TestCase):
    """Tout ne doit pas prendre un défaut : certaines questions n'en ont pas.

    `execute_module_upgrade` demande un nom de module, un chemin, une
    version de départ. Rendre « » au bout de cinq secondes n'y serait pas
    une commodité mais une réponse fausse. Ces invites restent bloquantes,
    et c'est correct — à une condition, vérifiée ici : qu'aucune migration
    automatique ne passe par elles.
    """

    def test_the_module_menu_is_not_on_the_automatic_path(self):
        import inspect

        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        self.assertNotIn("execute_module_upgrade", source)

    def test_but_the_step_it_shares_IS(self):
        # `internal_module_upgrade` est appelée des DEUX côtés : par le
        # menu et par la migration. C'est ce qui la rend obligatoire.
        import inspect

        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        self.assertIn("internal_module_upgrade", source)

    def test_its_prompts_ask_for_values_with_no_default(self):
        # Si l'un d'eux devenait un oui/non, il faudrait le faire passer
        # par le lecteur temporisé comme les autres.
        import inspect

        source = inspect.getsource(TodoUpgrade.execute_module_upgrade)
        for question in ("Module name", "Path", "From odoo version"):
            self.assertIn(question, source)


class TestWhatEnterDoesIsWritten(unittest.TestCase):
    """La question doit dire la vérité à qui appuie sur Entrée."""

    def source(self, nom):
        import inspect

        return inspect.getsource(getattr(TodoUpgrade, nom))

    def test_the_theme_prompt_announces_Y(self):
        source = self.source("prompt_uninstall_theme")
        self.assertIn("(Y/n,", source)
        self.assertIn('default="y"', source)

    def test_the_cleanup_prompt_announces_Y(self):
        source = self.source("prompt_database_cleanup")
        self.assertIn("(Y/n,", source)
        self.assertIn('default="y"', source)

    def test_the_smoke_prompt_announces_Y(self):
        source = self.source("prompt_smoke_public_url")
        self.assertIn("(Y/n,", source)
        self.assertIn('default="y"', source)

    def test_the_reset_prompt_says_enter_is_all(self):
        source = self.source("prompt_reset_stale_cow_views")
        self.assertIn("Enter = all", source)
        self.assertIn('default="a"', source)

    def test_the_cow_prediction_says_enter_neutralizes(self):
        source = self.source("prompt_cow_prediction")
        self.assertIn("Enter = neutralize now", source)
        self.assertIn('default="a"', source)

    def test_the_uninstall_strategy_defaults_to_one(self):
        source = self.source("prompt_uninstall_missing")
        self.assertIn("Enter = 1", source)
        self.assertIn('default="1"', source)

    def test_every_default_has_a_way_to_say_no(self):
        # Un défaut qui agit sans issue n'est plus un défaut, c'est un ordre.
        for nom, refus in (
            ("prompt_reset_stale_cow_views", '== "n"'),
            ("prompt_uninstall_missing", '== "3"'),
            ("prompt_cow_prediction", "n = "),
        ):
            self.assertIn(refus, self.source(nom), nom)


class TestTheBackupAtTheEnd(unittest.TestCase):
    """Au bout de plusieurs heures, l'archive est ce qu'on voulait.

    Trois réponses, trois sens, et le troisième est celui qui piège : « n »
    refuse, « y » ou Entrée prend le nom horodaté, et TOUT LE RESTE est un
    nom de fichier. « non.zip » est donc un fichier, pas un refus.
    """

    TPL = "./odoo_bin.sh db --backup --database x --restore_image"
    DEFAUT = "./odoo_bin.sh db --backup --database x --restore_image x_f_2026"

    def cmd(self, answer):
        return TodoUpgrade.backup_command(answer, self.TPL, self.DEFAUT)

    def test_yes_takes_the_timestamped_name(self):
        self.assertEqual(self.cmd("y"), self.DEFAUT)

    def test_case_does_not_matter(self):
        self.assertEqual(self.cmd("Y"), self.DEFAUT)

    def test_n_refuses(self):
        # Le défaut ne retire pas le choix : il ne fait qu'en proposer un.
        self.assertEqual(self.cmd("n"), "")
        self.assertEqual(self.cmd("N"), "")

    def test_anything_else_is_a_filename(self):
        self.assertTrue(self.cmd("archive.zip").endswith(" archive.zip"))

    def test_a_filename_that_STARTS_with_n_is_still_a_filename(self):
        # Le piège : comparer un début de mot au lieu de la réponse
        # entière ferait passer « non.zip » pour un refus, et l'on
        # perdrait l'archive d'une migration de plusieurs heures.
        self.assertTrue(self.cmd("non.zip").endswith(" non.zip"))

    def test_blanks_are_not_a_filename(self):
        self.assertEqual(self.cmd("   "), "")

    def test_none_does_not_crash(self):
        self.assertEqual(self.cmd(None), "")

    def test_enter_backs_up_because_the_default_says_so(self):
        import inspect

        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        debut = source.index("Export a backup?")
        fenetre = source[debut : debut + 200]
        self.assertIn('default="y"', fenetre)
        self.assertIn("(Y/n,", fenetre)


class TestTheToolsLaunchedApart(unittest.TestCase):
    def test_the_leftovers_default_to_deleting(self):
        import theme_leftover

        self.assertEqual(theme_leftover.DEFAULT_ANSWER, "d")

    def test_the_leftovers_are_saved_BEFORE_being_deleted(self):
        # C'est ce qui rend ce défaut tenable. Sans la sauvegarde, il aurait
        # dû rester « garder » : on ne fait pas d'une décision irréversible
        # la réponse qu'on obtient en ne répondant pas.
        import inspect

        import theme_leftover

        source = inspect.getsource(theme_leftover.prompt)
        self.assertLess(
            source.index("backup_attachments"),
            source.index("delete_attachments"),
        )

    def test_the_leftovers_prompt_says_enter_deletes(self):
        import inspect

        import theme_leftover

        source = inspect.getsource(theme_leftover.prompt)
        self.assertIn("Enter = delete", source)
        self.assertIn("k = ", source)

    def test_the_smoke_reset_defaults_to_all(self):
        import smoke_public_url

        self.assertEqual(smoke_public_url.DEFAULT_ANSWER, "a")

    def test_the_scss_default_follows_what_the_checkout_can_do(self):
        # « a » là où `reset_asset` n'existe pas (avant la 13.0) ferait
        # boucler l'invite sur elle-même : le défaut suit la capacité.
        import inspect

        import check_stale_scss

        source = inspect.getsource(check_stale_scss.prompt)
        self.assertIn('defaut = "a" if can_reset else "n"', source)

    def test_each_of_them_can_run_without_a_driver(self):
        # Le repli compte : ces outils se lancent aussi à la main, et une
        # ImportError les rendrait inutilisables hors migration.
        import check_stale_scss
        import smoke_public_url
        import theme_leftover

        for module in (theme_leftover, smoke_public_url, check_stale_scss):
            import inspect

            self.assertIn(
                "auto_ask = None",
                inspect.getsource(module),
                module.__name__,
            )


class TestTestingEveryBump(unittest.TestCase):
    """« a » dit une fois ce qu'on répétait six fois."""

    def source(self):
        import inspect

        return inspect.getsource(TodoUpgrade.execute_odoo_upgrade)

    def test_the_option_is_offered(self):
        self.assertIn("Open it at EVERY version bump", self.source())

    def test_it_is_remembered_in_the_progression(self):
        # Sinon une reprise après interruption reposerait la question, et
        # l'automatisation s'arrêterait au premier palier suivant.
        source = self.source()
        self.assertIn("state_4_selenium_every_bump", source)
        self.assertIn("self.write_config()", source)

    def test_the_memory_stops_the_question(self):
        source = self.source()
        debut = source.index("state_4_selenium_every_bump")
        fenetre = source[debut : debut + 400]
        self.assertIn('status = "y"', fenetre)

    def test_it_belongs_to_step_four(self):
        # Le nom porte sa propriété : un retour avant l'étape 4 doit
        # l'effacer, comme tout ce que l'étape 4 a décidé.
        from script.todo.todo_upgrade import STEP_PREFIX_RE

        match = STEP_PREFIX_RE.match("state_4_selenium_every_bump")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "4")


if __name__ == "__main__":
    unittest.main()
