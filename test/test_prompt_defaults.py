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
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "script", "odoo", "migration"))
sys.path.insert(0, os.path.join(REPO, "script", "addons"))

from script.todo import auto_ask  # noqa: E402
from script.todo.todo_upgrade import TodoUpgrade  # noqa: E402


@contextlib.contextmanager
def closed_after(count):
    """Une entrée fermée bornée pour le port scripté : ses `count`
    premières questions lèvent EOFError, comme Ctrl+D, la suivante
    AssertionError. Une question qui revient sans fin fait échouer le test
    au lieu de le bloquer."""
    from unittest import mock

    from script.todo.ui.port import ScriptedPort

    original, asked = ScriptedPort._answer, []

    def answer(port, message):
        asked.append(message)
        if len(asked) > count:
            raise AssertionError("the question keeps coming back")
        return original(port, message)

    with mock.patch.object(ScriptedPort, "_answer", answer):
        yield


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

    def test_a_yes_no_question_of_the_migration_too(self):
        # Au terminal, hors mode auto : l'invite dit le défaut, [O/n] ou
        # [o/N], et une réponse vide le prend.
        from unittest import mock

        from script.todo import todo_i18n

        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("fr")
        for nom, cle, defaut in SIMPLE:
            with self.subTest(nom=nom):
                migration = SimplePrompt()
                with (
                    mock.patch("builtins.input", return_value="") as lu,
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    agi = migration.act(nom)
                (invite,) = [appel.args[0] for appel in lu.call_args_list]
                indice = "[O/n] : " if defaut else "[o/N] : "
                attendu = f"{simple_prompt(nom, cle)} {indice}"
                if nom != "neutralize_cow_views":
                    self.assertEqual(invite, attendu)
                self.assertTrue(invite.startswith(attendu[:-4]), invite)
                self.assertEqual(agi, int(defaut))


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


class TestHowLongTheCountdownLasts(EnvCase):
    """Cinq secondes ne suffisaient pas à LIRE la question.

    Le compte à rebours n'existe pas pour aller vite : il existe pour
    qu'on puisse s'absenter. Trop court, il fait l'inverse — on répond par
    réflexe, ou l'on subit un défaut qu'on n'a pas eu le temps de lire.
    """

    def test_the_default_leaves_time_to_read_and_decide(self):
        self.assertGreaterEqual(auto_ask.DEFAULT_DELAY, 15)

    def test_the_environment_still_wins(self):
        # C'est le seul canal qui traverse un fork : une valeur posée par
        # le pilote doit primer sur celle écrite ici.
        os.environ[auto_ask.ENV_DELAY] = "3"
        self.assertEqual(3, auto_ask.delay())


class TestTheDatabaseNameTheFileSuggests(unittest.TestCase):
    """« test » ne disait rien de ce qu'on migrait.

    Trois migrations de suite portaient le même nom, et retrouver
    laquelle avait échoué demandait de relire le journal. Le fichier de
    sauvegarde porte déjà le nom du client — c'est la seule information
    disponible au moment où la question se pose.
    """

    def nom(self, chemin, **kw):
        from script.todo.todo_upgrade import database_name_from_file

        return database_name_from_file(chemin, **kw)

    def test_the_zip_extension_goes_away(self):
        self.assertEqual("garance3", self.nom("image_db/garance3.zip"))

    def test_an_uppercase_extension_goes_away_too(self):
        self.assertEqual("client", self.nom("image_db/CLIENT.ZIP"))

    def test_a_real_backup_name_survives_whole(self):
        self.assertEqual(
            "technolibre_2026_08_26_02h41m23s",
            self.nom("image_db/technolibre_2026-08-26_02h41m23s.zip"),
        )

    def test_a_file_without_extension_still_names_a_base(self):
        # Une sauvegarde peut être posée sans « .zip » ; elle s'ouvre
        # quand même comme une archive.
        self.assertEqual("technolibre", self.nom("image_db/technolibre"))

    def test_spaces_and_punctuation_become_underscores(self):
        # Le nom finit dans un createdb et dans des noms de fichiers.
        self.assertEqual(
            "client_final_2026", self.nom("image_db/Client Final (2026).zip")
        )

    def test_it_never_starts_with_a_digit(self):
        # PostgreSQL refuse un identifiant nu qui commence par un chiffre.
        nom = self.nom("image_db/2026-backup.zip")
        self.assertFalse(nom[0].isdigit(), nom)

    def test_nothing_usable_falls_back_to_the_default(self):
        for chemin in ("", None, "image_db/.zip", "image_db/---.zip"):
            self.assertEqual("test", self.nom(chemin))

    def test_a_long_name_leaves_room_for_the_suffixes(self):
        # Le pilote ajoute « _neutralize » puis « _upgrade_<version> ».
        # PostgreSQL tronque à 63 octets : sans marge, deux paliers
        # finiraient sur le MÊME nom et le second écraserait le premier.
        from script.todo.todo_upgrade import database_name_from_file

        nom = database_name_from_file("image_db/" + "a" * 90 + ".zip")
        complet = nom + "_neutralize_upgrade_18"
        self.assertLessEqual(len(complet), 63, complet)

    def test_it_does_not_end_on_a_separator(self):
        nom = self.nom("image_db/" + "a" * 40 + "-suite.zip")
        self.assertFalse(nom.endswith("_"), nom)


class TestTheMigrationUsesThatName(unittest.TestCase):
    def test_the_prompt_offers_what_the_file_suggests(self):
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        pose = source.index("database_name_from_file(")
        invite = source.index("Which database name do you want to work with?")
        # Il faut le calculer AVANT de le proposer.
        self.assertLess(pose, invite)

    def test_a_remote_download_keeps_the_name_the_server_gave(self):
        # Le serveur sait mieux que le nom du fichier téléchargé.
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        fenetre = source[
            source.index("database_name_from_file(") - 400 : source.index(
                "database_name_from_file("
            )
        ]
        self.assertIn('default_database_name == "test"', fenetre)


class TestTheQuestionThatCannotAnswerItself(EnvCase):
    """Celle-là engage toutes les suivantes : elle ne se prend pas seule.

    Une variable `ERPLIBRE_AUTO_EXECUTE` héritée du shell ferait répondre
    « oui » à la place de quelqu'un, et cette réponse-là décide de toutes
    les autres pendant des heures.
    """

    def answer(self, *typed):
        """`auto_execute` après la question, chaque `input` répondu par
        `typed`, une exception levée ; toute réponse doit être lue."""
        from unittest import mock

        obj = TodoUpgrade.__new__(TodoUpgrade)
        suite = iter(typed)
        with (
            mock.patch("builtins.input", side_effect=suite),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            obj.prompt_auto_execute()
        self.assertIsNone(next(suite, None), "réponse non lue")
        return obj.auto_execute

    def asked(self, answers, previous=False):
        """Les événements du port scripté qui répond `answers`, et l'état
        du mode auto qu'il voyait à chaque question ; `previous`, le mode
        d'une reprise précédente sur le même objet."""
        from script.todo import ui
        from script.todo.ui.port import ScriptedPort

        vu = []

        class Port(ScriptedPort):
            def menu(self, view):
                vu.append(auto_ask.enabled())
                return super().menu(view)

        obj = TodoUpgrade.__new__(TodoUpgrade)
        obj.auto_execute = previous
        with (
            contextlib.redirect_stdout(io.StringIO()),
            ui.bind(Port(list(answers))) as port,
        ):
            obj.prompt_auto_execute()
        self.assertEqual(port.answers, [])
        return port.events, vu

    def test_enter_says_no(self):
        self.assertFalse(self.answer(""))

    def test_the_default_is_written_down_not_deduced(self):
        # Une question oui/non dont le défaut, non, se lit dans le message,
        # sans compte à rebours : ce n'est pas au délai de l'activer.
        for previous in (False, True):
            with self.subTest(previous=previous):
                events, _vu = self.asked([""], previous)
                (asked,) = events
                self.assertEqual(asked["kind"], "confirm")
                self.assertEqual(asked["default"], "n")
                self.assertNotIn("timeout_s", asked)

    def test_an_inherited_flag_cannot_switch_it_on(self):
        os.environ[auto_ask.ENV_ENABLED] = "1"
        os.environ[auto_ask.ENV_DELAY] = "5"
        self.assertFalse(self.answer(""))
        self.assertFalse(self.answer(EOFError()))

    def test_the_inherited_flag_is_cleared_before_asking(self):
        os.environ[auto_ask.ENV_ENABLED] = "1"
        os.environ[auto_ask.ENV_DELAY] = "5"
        _events, vu = self.asked(["n"], previous=True)
        self.assertEqual(vu, [False])

    def test_yes_still_says_yes(self):
        for typed in ("y", "o", "oui", "YES"):
            with self.subTest(typed=typed):
                self.assertTrue(self.answer(typed))


class TestEveryPromptAnnouncesTheCountdown(EnvCase):
    """Une invite qui a l'air d'attendre indéfiniment n'invite pas à
    s'absenter — et c'est pourtant tout l'intérêt du mode auto."""

    def ask(self, default="d", seconds=5):
        import select

        original = select.select
        select.select = lambda r, w, x, t: ([], [], [])
        self.addCleanup(setattr, select, "select", original)
        auto_ask.export(True, seconds)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            auto_ask.ask("💬 q : ", default=default)
        return out.getvalue()

    def test_the_delay_is_announced_before_the_question(self):
        texte = self.ask()
        self.assertIn("⏱5s", texte)
        self.assertLess(texte.index("⏱5s"), texte.index("💬"))

    def test_it_shows_the_real_delay(self):
        self.assertIn("⏱2s", self.ask(seconds=2))

    def test_nothing_is_announced_outside_auto_mode(self):
        import builtins

        auto_ask.export(False)
        original = builtins.input
        vu = []
        builtins.input = lambda prompt="": vu.append(prompt) or "x"
        self.addCleanup(setattr, builtins, "input", original)
        auto_ask.ask("💬 q : ", default="d")
        self.assertNotIn("⏱", vu[0])

    def test_the_clock_announces_AND_reports(self):
        # Le même symbole des deux côtés : il annonce l'attente, puis rend
        # compte de la réponse. Deux symboles feraient deux mécanismes.
        texte = self.ask()
        self.assertEqual(texte.count("⏱"), 2)

    def test_a_yes_no_question_announces_it_too(self):
        # Une question oui/non de la migration, au terminal en mode auto :
        # le délai avant la question, puis le défaut pris, non.
        import select

        original = select.select
        select.select = lambda r, w, x, t: ([], [], [])
        self.addCleanup(setattr, select, "select", original)
        migration = SimplePrompt(auto=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(migration.act("prompt_purge_dead_attachments"), 0)
        texte = out.getvalue()
        self.assertIn(f"⏱{TodoUpgrade.AUTO_DELAY}s 💬", texte)
        self.assertEqual(texte.count("⏱"), 2)


class TestNoPromptOfTheMigrationCanHang(unittest.TestCase):
    """Un `input()` nu ne sait rien du mode auto : il attend, pour toujours.

    Le garde-fou regarde TOUTES les méthodes du chemin de migration, et
    non la seule `execute_odoo_upgrade` : une invite posée dans une
    méthode voisine, comme la prédiction COW ou le choix de
    désinstallation, y échapperait sinon.
    """

    METHODES = (
        "execute_odoo_upgrade",
        "copy_to_image_db",
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
        "confirm_rewind",
        "prompt_fix_view_type",
        "prompt_purge_dead_attachments",
        "neutralize_cow_views",
    )

    def calls(self, nom, appel):
        """Les lignes des appels de `nom` dont la fonction, sous
        `ast.unparse`, est `appel`."""
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
            if isinstance(node, ast.Call) and ast.unparse(node.func) == appel
        ]

    def culprits(self, appel):
        return {
            nom: self.calls(nom, appel)
            for nom in self.METHODES
            if self.calls(nom, appel)
        }

    def test_none_of_them_asks_outside_the_timer(self):
        self.assertEqual(
            self.culprits("input"), {}, "invites hors du mode auto"
        )

    def test_their_yes_no_questions_count_down(self):
        # `ui.confirm` tel quel ne compte pas à rebours en mode auto : une
        # question oui/non du chemin de migration passe par `self.confirm`.
        self.assertEqual(self.culprits("ui.confirm"), {})


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

        source = "".join(
            inspect.getsource(getattr(TodoUpgrade, nom))
            for nom in (
                "_module_upgrade_what",
                "_module_upgrade_by_name",
                "_module_upgrade_versions",
            )
        )
        for question in ("Module name", "Path", "From odoo version"):
            self.assertIn(question, source)


class TestWhatEnterDoesIsWritten(unittest.TestCase):
    """La question doit dire la vérité à qui appuie sur Entrée.

    Les trois portes oui/non posent leur question par `self.confirm`,
    dont l'indice suit le défaut : celui-ci se lit dans le relevé des
    défauts (`test_todo_yes_no.survey`). Désinstaller un thème et nettoyer
    la base écrivent en base : non. Interroger les pages : oui."""

    def source(self, nom):
        import inspect

        return inspect.getsource(getattr(TodoUpgrade, nom))

    def defaults(self, nom, cle):
        from test.test_todo_yes_no import survey

        ligne = ("script/todo/todo_upgrade.py", f"TodoUpgrade.{nom}", cle)
        return survey().get(ligne)

    def test_the_theme_prompt_defaults_to_no(self):
        cle = "Uninstall them properly before migrating?"
        self.assertEqual(self.defaults("prompt_uninstall_theme", cle), [False])

    def test_the_cleanup_prompt_defaults_to_no(self):
        cle = "Clean the database before testing the pages?"
        nom = "prompt_database_cleanup"
        self.assertEqual(self.defaults(nom, cle), [False])

    def test_the_smoke_prompt_defaults_to_yes(self):
        cle = "Request every public URL of this database now?"
        nom = "prompt_smoke_public_url"
        self.assertEqual(self.defaults(nom, cle), [True])

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


DB = "forged_yesno_db"
# (méthode, clé de la question, défaut, outil qu'un oui lance).
GATES = (
    (
        "prompt_uninstall_theme",
        "Uninstall them properly before migrating?",
        False,
        "uninstall_addons_theme.sh",
    ),
    (
        "prompt_database_cleanup",
        "Clean the database before testing the pages?",
        False,
        "database_cleanup.py",
    ),
    (
        "prompt_smoke_public_url",
        "Request every public URL of this database now?",
        True,
        "smoke_public_url.py",
    ),
)
YES = (["o"], ["oui"], ["y"], ["YES"])
# Une faute est dite, puis Ctrl+D vaut non ; Ctrl+D seul aussi.
REFUSED = (["n"], ["non"], ["peut-être", EOFError()], [EOFError()])
NEUTRALIZE = (
    "Neutralize these copies so the upgrade can proceed?"
    " Their arch is kept and the change is reversible."
)
# (méthode, clé de la question, défaut) : les questions oui/non simples de
# la migration, posées par `TodoUpgrade.confirm`. Un oui rembobine la
# progression, corrige les vues, purge les pièces jointes mortes ou
# neutralise les copies COW.
SIMPLE = (
    ("confirm_rewind", "Confirm?", False),
    ("prompt_fix_view_type", "Correct them?", True),
    ("prompt_purge_dead_attachments", "Delete them?", False),
    ("neutralize_cow_views", NEUTRALIZE, True),
)


def simple_prompt(nom, cle):
    """La question de `nom` (SIMPLE) sans indice, dans la langue choisie ;
    `confirm_rewind` y nomme « n », une nouvelle migration."""
    from script.todo.todo_i18n import t

    if nom == "confirm_rewind":
        return f"💬 {t('New migration, erase everything')}. {t(cle)}"
    return f"💬 {t(cle)}"


class SimplePrompt:
    """Une migration montée pour les questions de SIMPLE, sur la base
    DB : `todo_upgrade_execute` note chaque commande dans `lst_cmd` sans
    rien lancer ; l'outil de rapport trouve quelque chose (statut 1),
    l'application et la purge réussissent ; l'audit des pièces jointes en
    trouve deux mortes ; `show_cow_drift` note son mode dans `drift`."""

    def __init__(self, auto=False):
        self.lst_cmd, self.drift = [], []
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.dct_progression = {}
        upgrade.lst_command_executed = []
        upgrade.todo_upgrade_execute = self.execute
        upgrade.show_cow_drift = lambda db, v, mode: self.drift.append(mode)
        if auto:
            upgrade.auto_execute = True
        self.upgrade = upgrade

    def execute(self, cmd, get_output=False, **_kw):
        self.lst_cmd.append(cmd)
        status = 0 if self.acts(cmd) else 1
        return (status, cmd, ["DELETE 2"]) if get_output else (status, cmd)

    @staticmethod
    def acts(cmd):
        return "--apply" in cmd or cmd.startswith("psql")

    def act(self, nom):
        """Joue `nom` ; 1 si un oui y a agi (rembobiner, appliquer,
        purger), 0 sinon."""
        from unittest import mock

        if nom == "confirm_rewind":
            return int(self.upgrade.confirm_rewind("n"))
        rapport = {
            "dead_ids": [1, 2],
            "dead_kept_size": 2048,
            "groups": {"dead_field": []},
            "dead_kept": [],
        }
        with mock.patch.multiple(
            "script.analyse.check_filestore",
            audit=lambda database: rapport,
            purge_dead_sql=lambda r: "DELETE FROM ir_attachment",
            summarise=lambda groups: [],
            rows_deleted=lambda sortie: 2,
        ):
            args = (DB, 16) if nom == "neutralize_cow_views" else (DB,)
            getattr(self.upgrade, nom)(*args)
        return len([cmd for cmd in self.lst_cmd if self.acts(cmd)])


class TestTheGatesAreYesNoQuestions(EnvCase):
    """Le thème, le nettoyage et le test de fumée : trois questions oui/non
    de `TodoUpgrade.confirm`, avec « b » (revenir à une étape) et « t »
    (l'état de la migration) à côté de oui et non.

    Désinstaller le thème et nettoyer la base écrivent en base : non par
    défaut, en mode automatique aussi, où l'échéance du compte à rebours
    et l'annulation de la page prennent ce défaut. Rien n'est lancé :
    `run_captured` et `todo_upgrade_execute` sont des doubles qui notent."""

    def setUp(self):
        super().setUp()
        from script.todo import todo_i18n

        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("fr")

    def upgrade(self, auto=False):
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.dct_progression = {}
        upgrade.lst_command_executed = []
        upgrade.write_config = lambda: None
        upgrade.installed_theme = lambda db: ["forged_yesno_theme"]
        self.lst_cmd = []
        upgrade.run_captured = lambda cmd: self.lst_cmd.append(cmd) or 0
        upgrade.todo_upgrade_execute = lambda cmd, **kw: (
            self.lst_cmd.append(cmd) or (False, cmd, [])
        )
        self.shown, self.rewinds = [], []
        upgrade.show_migration_status = lambda: self.shown.append(1)
        if auto:
            upgrade.auto_execute = True
        return upgrade

    def play(self, nom, answers, auto=False, rewind=False):
        """Les événements du port scripté, après `nom` joué sur `answers` ;
        « b » rembobine si `rewind`, sinon on y renonce."""
        from unittest import mock

        from script.todo import ui
        from script.todo.ui.port import ScriptedPort

        upgrade = self.upgrade(auto)

        def rewind_to_chosen_step():
            self.rewinds.append(1)
            return rewind

        upgrade.rewind_to_chosen_step = rewind_to_chosen_step
        with (
            mock.patch("builtins.input", side_effect=AssertionError),
            contextlib.redirect_stdout(io.StringIO()),
            ui.bind(ScriptedPort(list(answers))) as port,
        ):
            getattr(upgrade, nom)(DB)
        self.assertEqual(port.answers, [])
        return port.events

    def confirms(self, events):
        return [e for e in events if e.get("kind") == "confirm"]

    def test_each_gate_states_its_default_and_its_letters(self):
        from script.todo.todo_i18n import t

        for nom, cle, defaut, _outil in GATES:
            with self.subTest(nom=nom):
                (asked,) = self.confirms(self.play(nom, ["n"]))
                self.assertEqual(asked["prompt"], f"💬 {t(cle)}")
                self.assertEqual(asked["default"], "y" if defaut else "n")
                self.assertEqual(
                    [option["key"] for option in asked["options"]],
                    ["b", "t"],
                )
                indice = "[O/n" if defaut else "[o/N"
                self.assertEqual(
                    asked["text"],
                    f"💬 {t(cle)} {indice}, b = {t('Go back to a step')},"
                    f" t = {t('Migration state (full screen)')}] : ",
                )
                self.assertNotIn("timeout_s", asked)

    def test_a_yes_runs_the_tool_and_a_refusal_runs_nothing(self):
        from script.todo.todo_i18n import t

        for nom, _cle, defaut, outil in GATES:
            vide = [([""], defaut)]
            cases = [(a, False) for a in REFUSED] + [(a, True) for a in YES]
            for answers, runs in vide + cases:
                with self.subTest(nom=nom, answers=answers):
                    events = self.play(nom, answers)
                    lances = [c for c in self.lst_cmd if outil in c]
                    self.assertEqual(len(lances), int(runs))
                    fois = 2 if "peut-être" in answers else 1
                    self.assertEqual(len(self.confirms(events)), fois)
                    if fois == 2:
                        self.assertIn(
                            f"{t('Answer yes or no: ')}peut-être",
                            [e.get("text") for e in events],
                        )

    def test_in_auto_mode_the_deadline_erases_nothing(self):
        # Au terminal, l'échéance du compte à rebours d'auto_ask rend le
        # défaut de la question ; le mode automatique est exporté avant.
        from unittest import mock

        from script.todo.ui import port

        heard = []

        def deadline(text, default, seconds):
            heard.append((default, seconds, auto_ask.enabled()))
            return default

        for nom, _cle, defaut, outil in GATES:
            with self.subTest(nom=nom):
                heard.clear()
                upgrade = self.upgrade(auto=True)
                with (
                    mock.patch.dict(port.ORIGINAL, {"auto_ask.ask": deadline}),
                    mock.patch("builtins.input", side_effect=AssertionError),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    getattr(upgrade, nom)(DB)
                # Le défaut, dans la langue choisie : l'échéance l'affiche.
                attendu = "Oui" if defaut else "Non"
                self.assertEqual(
                    heard, [(attendu, TodoUpgrade.AUTO_DELAY, True)]
                )
                lances = [c for c in self.lst_cmd if outil in c]
                self.assertEqual(len(lances), int(defaut))

    def test_in_auto_mode_a_cancelled_countdown_erases_nothing(self):
        # Le journal des tâches change l'annulation d'un compte à rebours
        # en Entrée ; Ctrl+D y vaut Entrée aussi.
        for nom, _cle, defaut, outil in GATES:
            for answers in ([""], [EOFError()]):
                with self.subTest(nom=nom, answers=answers):
                    events = self.play(nom, answers, auto=True)
                    (asked,) = self.confirms(events)
                    self.assertEqual(
                        asked["timeout_s"], TodoUpgrade.AUTO_DELAY
                    )
                    lances = [c for c in self.lst_cmd if outil in c]
                    self.assertEqual(len(lances), int(defaut))

    def test_b_then_refusing_the_rewind_asks_the_same_question(self):
        for nom, _cle, _defaut, outil in GATES:
            with self.subTest(nom=nom):
                events = self.play(nom, ["b", "n"])
                premiere, seconde = self.confirms(events)
                self.assertEqual(premiere, seconde)
                self.assertEqual(self.rewinds, [1])
                self.assertEqual(self.lst_cmd, [])

    def test_b_then_a_rewind_stops_the_migration(self):
        from script.todo.todo_upgrade import MigrationRewind

        for nom, _cle, _defaut, _outil in GATES:
            with self.subTest(nom=nom):
                with self.assertRaises(MigrationRewind):
                    self.play(nom, ["b"], rewind=True)
                self.assertEqual(self.lst_cmd, [])

    def test_t_shows_the_state_then_asks_the_same_question(self):
        for nom, _cle, _defaut, outil in GATES:
            with self.subTest(nom=nom):
                events = self.play(nom, ["t", "t", "o"])
                self.assertEqual(len(self.confirms(events)), 3)
                self.assertEqual(len(self.shown), 2)
                self.assertEqual(
                    len([c for c in self.lst_cmd if outil in c]), 1
                )

    def test_a_closed_input_ends_each_gate(self):
        for nom, _cle, _defaut, _outil in GATES:
            with self.subTest(nom=nom), closed_after(1):
                events = self.play(nom, [])
                self.assertEqual(len(self.confirms(events)), 1)
                self.assertEqual(self.lst_cmd, [])


class TestTheGateKeepsItsTextCallers(unittest.TestCase):
    """`ask_gate` reste une question texte pour trois invites qui ne sont
    pas des oui/non : la neutralisation (« 1 » la saute), la pause avant
    un palier (Entrée rend la main) et la remise des copies COW (des
    numéros, « a », « n »). Les trois portes oui/non passent par
    `self.confirm`."""

    @staticmethod
    def tree():
        chemin = os.path.join(REPO, "script", "todo", "todo_upgrade.py")
        with open(chemin, encoding="utf-8") as handle:
            return ast.parse(handle.read())

    @staticmethod
    def names(node, ctx):
        return {
            n.id
            for n in ast.walk(node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ctx)
        }

    @staticmethod
    def constants(node):
        return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant)}

    def calls(self, methode):
        found = []
        for node in ast.walk(self.tree()):
            if not isinstance(node, ast.FunctionDef):
                continue
            for call in ast.walk(node):
                func = getattr(call, "func", None)
                if (
                    isinstance(call, ast.Call)
                    and isinstance(func, ast.Attribute)
                    and func.attr == methode
                    and getattr(func.value, "id", "") == "self"
                ):
                    found.append(node.name)
        return sorted(found)

    def test_the_text_callers_stay(self):
        self.assertEqual(
            self.calls("ask_gate"),
            [
                "execute_odoo_upgrade",
                "execute_odoo_upgrade",
                "prompt_reset_stale_cow_views",
            ],
        )

    def test_the_yes_no_gates_confirm(self):
        appelants = self.calls("confirm")
        for nom, _cle, _defaut, _outil in GATES:
            self.assertIn(nom, appelants)

    def test_a_text_answer_passes_through_untouched(self):
        # « 1 » saute la neutralisation, Entrée rend la main : ask_gate rend
        # la réponse telle quelle, sans la lire comme un oui ou un non.
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        for reponse in ("1", "", "1,2", "a"):
            with self.subTest(reponse=reponse):
                upgrade.ask = lambda prompt, default="", r=reponse: r
                self.assertEqual(upgrade.ask_gate("? "), reponse)

    def neutralize(self, reponse):
        """Le nom de base, `do_neutralize` et les écritures du journal après
        le vrai bloc de neutralisation d'`execute_odoo_upgrade`, exécuté
        seul : `ask` rend `reponse` au vrai `ask_gate`."""
        import builtins

        from script.todo.todo_i18n import t

        (bloc,) = [
            node
            for node in ast.walk(self.tree())
            if isinstance(node, ast.If)
            and "state_1_neutralize_database" in self.constants(node.test)
        ]
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.dct_progression = {}
        ecrit, asks = [], []
        upgrade.write_config = lambda: ecrit.append(1)
        upgrade.ask = lambda prompt, default="": asks.append(prompt) or reponse
        scope = {
            "__builtins__": builtins,
            "self": upgrade,
            "t": t,
            "database_name": DB,
            "do_neutralize": False,
        }
        code = compile(ast.Module(body=[bloc], type_ignores=[]), "<n>", "exec")
        with contextlib.redirect_stdout(io.StringIO()):
            exec(code, scope)
        self.assertEqual(len(asks), 1)
        self.assertIn(t("Neutralize database, press to continue"), asks[0])
        return scope["database_name"], scope["do_neutralize"], len(ecrit)

    def test_1_skips_the_neutralization(self):
        self.assertEqual(self.neutralize("1"), (DB, False, 0))
        self.assertEqual(self.neutralize(" 1 "), (DB, False, 0))

    def test_enter_neutralizes(self):
        self.assertEqual(self.neutralize(""), (f"{DB}_neutralize", True, 1))

    def test_enter_at_the_pause_hands_back(self):
        # La pause avant un palier rend la main après une seule question,
        # et rien ne lit sa réponse avant que `status` reçoive celui de la
        # commande suivante : aucune réponse n'y décide de rien.
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        asks = []
        upgrade.ask = lambda prompt, default="": asks.append(prompt) or ""
        self.assertEqual(upgrade.ask_gate("? "), "")
        self.assertEqual(len(asks), 1)

        tree = self.tree()
        (pause,) = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and "Press to continue" in self.constants(node.value)
            and "ask_gate"
            in {
                n.attr
                for n in ast.walk(node.value)
                if isinstance(n, ast.Attribute)
            }
        ]
        self.assertEqual(self.names(pause, ast.Store), {"status"})
        (corps,) = [
            body
            for node in ast.walk(tree)
            for body in (getattr(node, "body", None),)
            if isinstance(body, list) and pause in body
        ]
        suite = corps[corps.index(pause) + 1 :]
        relu = []
        for statement in suite:
            relu.append("status" in self.names(statement, ast.Load))
            if "status" in self.names(statement, ast.Store):
                break
        else:
            self.fail("status n'est pas réaffecté après la pause")
        self.assertNotIn(True, relu)


class TestTheSimplePromptsAreYesNoQuestions(EnvCase):
    """Rembobiner, corriger les vues, purger les pièces jointes mortes et
    neutraliser les copies COW : les questions oui/non de SIMPLE, posées
    par `TodoUpgrade.confirm` ; « v » et « w » montrent les copies avant
    de répondre.

    Rembobiner et purger effacent : non par défaut, en mode automatique
    aussi, où l'échéance du compte à rebours et l'annulation de la page
    prennent ce défaut. Rien n'est lancé (`SimplePrompt`)."""

    def setUp(self):
        super().setUp()
        from script.todo import todo_i18n

        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("fr")

    def play(self, nom, answers, auto=False):
        """(migration, actions d'un oui, événements du port scripté) après
        `nom` joué sur `answers`, qui doivent toutes être lues."""
        from unittest import mock

        from script.todo import ui
        from script.todo.ui.port import ScriptedPort

        migration = SimplePrompt(auto)
        with (
            mock.patch("builtins.input", side_effect=AssertionError),
            contextlib.redirect_stdout(io.StringIO()),
            ui.bind(ScriptedPort(list(answers))) as port,
        ):
            agi = migration.act(nom)
        self.assertEqual(port.answers, [])
        return migration, agi, port.events

    @staticmethod
    def confirms(events):
        return [e for e in events if e.get("kind") == "confirm"]

    def test_each_prompt_states_its_default(self):
        from script.todo.todo_i18n import t

        for nom, cle, defaut in SIMPLE:
            with self.subTest(nom=nom):
                (asked,) = self.confirms(self.play(nom, ["n"])[2])
                prompt = simple_prompt(nom, cle)
                self.assertEqual(asked["prompt"], prompt)
                self.assertEqual(asked["default"], "y" if defaut else "n")
                self.assertNotIn("timeout_s", asked)
                indice = "[O/n" if defaut else "[o/N"
                if nom == "neutralize_cow_views":
                    indice += (
                        f", v = {t('View the differences')},"
                        f" w = {t('Full screen')}"
                    )
                self.assertEqual(asked["text"], f"{prompt} {indice}] : ")

    def test_a_yes_acts_and_a_refusal_does_nothing(self):
        from script.todo.todo_i18n import t

        for nom, _cle, defaut in SIMPLE:
            vide = [([""], defaut)]
            cases = [(a, False) for a in REFUSED] + [(a, True) for a in YES]
            for answers, agit in vide + cases:
                with self.subTest(nom=nom, answers=answers):
                    _m, agi, events = self.play(nom, answers)
                    self.assertEqual(agi, int(agit))
                    fois = 2 if "peut-être" in answers else 1
                    self.assertEqual(len(self.confirms(events)), fois)
                    if fois == 2:
                        self.assertIn(
                            f"{t('Answer yes or no: ')}peut-être",
                            [e.get("text") for e in events],
                        )

    def test_in_auto_mode_the_deadline_takes_the_default(self):
        # Au terminal, l'échéance du compte à rebours d'auto_ask rend le
        # défaut : rembobiner et purger n'effacent rien. Le mode
        # automatique est exporté avant.
        from unittest import mock

        from script.todo.ui import port

        heard = []

        def deadline(text, default, seconds):
            heard.append((default, seconds, auto_ask.enabled()))
            return default

        for nom, _cle, defaut in SIMPLE:
            with self.subTest(nom=nom):
                heard.clear()
                migration = SimplePrompt(auto=True)
                with (
                    mock.patch.dict(port.ORIGINAL, {"auto_ask.ask": deadline}),
                    mock.patch("builtins.input", side_effect=AssertionError),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    agi = migration.act(nom)
                # Le défaut, dans la langue choisie : l'échéance l'affiche.
                attendu = "Oui" if defaut else "Non"
                self.assertEqual(
                    heard, [(attendu, TodoUpgrade.AUTO_DELAY, True)]
                )
                self.assertEqual(agi, int(defaut))

    def test_in_auto_mode_a_cancelled_countdown_takes_the_default(self):
        # Le journal des tâches change l'annulation d'un compte à rebours
        # en Entrée ; Ctrl+D y vaut Entrée aussi.
        for nom, _cle, defaut in SIMPLE:
            for answers in ([""], [EOFError()]):
                with self.subTest(nom=nom, answers=answers):
                    _m, agi, events = self.play(nom, answers, auto=True)
                    (asked,) = self.confirms(events)
                    self.assertEqual(
                        asked["timeout_s"], TodoUpgrade.AUTO_DELAY
                    )
                    self.assertEqual(agi, int(defaut))

    def test_a_closed_input_ends_each_prompt(self):
        for nom, _cle, _defaut in SIMPLE:
            with self.subTest(nom=nom), closed_after(1):
                _m, agi, events = self.play(nom, [])
                self.assertEqual(len(self.confirms(events)), 1)
                self.assertEqual(agi, 0)


class TestTheBackupAtTheEnd(unittest.TestCase):
    """Au bout de plusieurs heures, l'archive est ce qu'on voulait.

    Trois réponses, trois sens, et le troisième est celui qui piège : un
    mot de non refuse, un mot de oui ou Entrée prend le nom horodaté, dans
    les deux langues, et TOUT LE RESTE est un nom de fichier. « non.zip »
    est donc un fichier, pas un refus.
    """

    TPL = "./odoo_bin.sh db dump x --image"
    DEFAUT = "./odoo_bin.sh db dump x --image x_f_2026"

    def cmd(self, answer):
        return TodoUpgrade.backup_command(answer, self.TPL, self.DEFAUT)

    def test_yes_takes_the_timestamped_name(self):
        self.assertEqual(self.cmd("y"), self.DEFAUT)

    def test_case_does_not_matter(self):
        self.assertEqual(self.cmd("Y"), self.DEFAUT)

    def test_every_yes_of_both_languages_takes_it(self):
        for answer in ("o", "oui", "yes", "OUI", " Yes "):
            with self.subTest(answer=answer):
                self.assertEqual(self.cmd(answer), self.DEFAUT)

    def test_n_refuses(self):
        # Le défaut ne retire pas le choix : il ne fait qu'en proposer un.
        self.assertEqual(self.cmd("n"), "")
        self.assertEqual(self.cmd("N"), "")

    def test_every_no_of_both_languages_refuses(self):
        for answer in ("non", "no", "NON", " No "):
            with self.subTest(answer=answer):
                self.assertEqual(self.cmd(answer), "")

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
        # Le défaut oui, et l'indice du port qui le dit dans la langue
        # choisie, [O/n] ou [Y/n], suivi du nom de fichier qu'on peut taper.
        import inspect

        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        debut = source.index('t("[Y/n]: ")')
        fenetre = source[debut : debut + 300]
        self.assertIn("or type filename.zip", fenetre)
        self.assertIn("Export a backup?", fenetre)
        self.assertIn('default="y"', fenetre)


class Stopped(Exception):
    """Lancée par le double de `todo_upgrade_execute` : la migration
    s'arrête à sa première commande."""


class MigrationRun(EnvCase):
    """Une migration reprise de la sauvegarde DB d'Odoo 16, en français,
    jouée par `execute_odoo_upgrade` dans un répertoire jetable qui tient
    lieu de checkout. Rien n'est lancé : `execute`, le double de
    `todo_upgrade_execute`, note la commande, puis lève Stopped."""

    def setUp(self):
        super().setUp()
        from script.todo import todo_i18n

        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("fr")
        home = self.enterContext(tempfile.TemporaryDirectory())
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(home)
        os.mkdir("image_db")
        self.backup = os.path.join(home, f"{DB}.zip")
        manifest = {"version": "16.0", "modules": {"base": {}}}
        with zipfile.ZipFile(self.backup, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
        self.image = os.path.join("image_db", f"{DB}.zip")
        self.lst_cmd = []

    def execute(self, cmd, **_kw):
        self.lst_cmd.append(cmd)
        raise Stopped()

    def upgrade(self, auto, **progression):
        from unittest import mock

        from script.todo import todo_upgrade

        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.dct_progression = {
            "migration_file": self.backup,
            "target_odoo_version": "17.0",
            "config_database_name": DB,
            "state_1_neutralize_database": True,
            **progression,
        }
        upgrade.lst_command_executed = []
        upgrade.todo = mock.MagicMock()
        upgrade.prompt_auto_execute = lambda: None
        upgrade.ask_ui = lambda: "cli"
        upgrade.write_config = lambda: None
        upgrade.open_step_log = lambda msg: None
        upgrade.switch_odoo = lambda version: None
        upgrade.check_addons_exist = lambda modules, get_all_info: (
            ["forged_yesno_module"],
            [],
            [],
            [],
        )
        upgrade.todo_upgrade_execute = self.execute
        if auto:
            upgrade.auto_execute = True
        absent = os.path.join(os.getcwd(), "absent.json")
        self.enterContext(
            mock.patch.object(
                todo_upgrade, "UPGRADE_DATABASE_CONFIG_LOG", absent
            )
        )
        versions = ([{"odoo_version": "17.0"}], [], "odoo16.0")
        self.enterContext(
            mock.patch.object(
                todo_upgrade, "get_odoo_version", return_value=versions
            )
        )
        return upgrade

    def run_upgrade(self, upgrade):
        """Ce que rend la migration, ou Stopped à sa première commande."""
        try:
            return upgrade.execute_odoo_upgrade()
        except Stopped:
            return Stopped

    def play(self, answers, auto=False, **progression):
        """(issue, événements du port scripté) de la migration jouée sur
        `answers`, qui doivent toutes être lues."""
        from unittest import mock

        from script.todo import ui
        from script.todo.ui.port import ScriptedPort

        upgrade = self.upgrade(auto, **progression)
        with (
            mock.patch("builtins.input", side_effect=AssertionError),
            contextlib.redirect_stdout(io.StringIO()),
            ui.bind(ScriptedPort(list(answers))) as port,
        ):
            issue = self.run_upgrade(upgrade)
        self.assertEqual(port.answers, [])
        return issue, [e for e in port.events if e.get("kind") == "confirm"]


class TestTheRunOfTheMigration(MigrationRun):
    """Les questions oui/non du début du déroulé, vers Odoo 17 : installer
    la version d'Odoo qui manque, continuer malgré des modules manquants,
    remplacer l'image déjà copiée sous image_db/.

    Remplacer l'image efface l'ancienne : non par défaut. Hors compte à
    rebours, Ctrl+D arrête la migration, là où un non restaure l'ancienne
    image ; à rebours, l'échéance et Ctrl+D prennent le défaut."""

    def old_image(self):
        with open(self.image, "w") as handle:
            handle.write("forged old image")

    def image_kept(self):
        with open(self.image, "rb") as handle:
            return handle.read() == b"forged old image"

    def test_a_missing_odoo_is_installed_only_on_a_yes(self):
        from script.todo.todo_i18n import t

        cle = "Would you like to install '%s'?"
        for answers, installe in [([""], False), *REFUSED_RUN, *YES_RUN]:
            with self.subTest(answers=answers):
                self.lst_cmd.clear()
                issue, asked = self.play(answers)
                self.assertEqual(
                    asked[0]["prompt"], f"💬 {t(cle) % 'odoo16.0'}"
                )
                self.assertEqual(asked[0]["default"], "n")
                if installe:
                    self.assertIs(issue, Stopped)
                    self.assertEqual(self.lst_cmd, ["make install_odoo_16"])
                else:
                    self.assertIsNone(issue)
                    self.assertEqual(self.lst_cmd, [])

    def test_missing_modules_stop_the_migration_unless_yes(self):
        from script.todo.todo_i18n import t

        cle = (
            "Missing or duplicate module detected at init,"
            " do you want to continue?"
        )
        fait = {"state_0_install_odoo": True}
        for answers, continue_ in [([""], False), *REFUSED_RUN, *YES_RUN]:
            with self.subTest(answers=answers):
                self.lst_cmd.clear()
                if os.path.exists(self.image):
                    os.remove(self.image)
                issue, asked = self.play(answers, **fait)
                self.assertEqual(asked[0]["prompt"], f"💬 {t(cle)}")
                self.assertEqual(asked[0]["default"], "n")
                if continue_:
                    self.assertIs(issue, Stopped)
                    self.assertIn("db_restore.py", self.lst_cmd[0])
                else:
                    self.assertIsNone(issue)
                    self.assertEqual(self.lst_cmd, [])

    RESUMED = {
        "state_0_install_odoo": True,
        "state_0_search_missing_module": True,
    }

    def test_the_image_is_replaced_only_on_a_yes(self):
        from script.todo.todo_i18n import t

        cle = "A file already exists, do you want to continue?"
        refus = [([""], False), (["n"], False), (["non"], False)]
        refus += [(["peut-être", "n"], False)]
        for answers, remplace in refus + list(YES_RUN):
            with self.subTest(answers=answers):
                self.lst_cmd.clear()
                self.old_image()
                issue, asked = self.play(answers, **self.RESUMED)
                self.assertEqual(asked[0]["prompt"], f"💬 {t(cle)}")
                self.assertEqual(asked[0]["default"], "n")
                self.assertTrue(asked[0]["back"])
                self.assertIs(issue, Stopped)
                self.assertIn("db_restore.py", self.lst_cmd[0])
                self.assertEqual(self.image_kept(), not remplace)

    def test_ctrl_d_stops_the_migration_and_keeps_the_image(self):
        for answers in ([EOFError()], ["peut-être", EOFError()]):
            with self.subTest(answers=answers):
                self.lst_cmd.clear()
                self.old_image()
                issue, _asked = self.play(answers, **self.RESUMED)
                self.assertIsNone(issue)
                self.assertEqual(self.lst_cmd, [])
                self.assertTrue(self.image_kept())

    def test_in_auto_mode_the_deadline_keeps_the_image(self):
        from unittest import mock

        from script.todo.ui import port

        heard = []

        def deadline(text, default, seconds):
            heard.append((default, seconds, auto_ask.enabled()))
            return default

        self.old_image()
        upgrade = self.upgrade(True, **self.RESUMED)
        with (
            mock.patch.dict(port.ORIGINAL, {"auto_ask.ask": deadline}),
            mock.patch("builtins.input", side_effect=AssertionError),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            issue = self.run_upgrade(upgrade)
        self.assertEqual(heard, [("Non", TodoUpgrade.AUTO_DELAY, True)])
        self.assertIs(issue, Stopped)
        self.assertIn("db_restore.py", self.lst_cmd[0])
        self.assertTrue(self.image_kept())

    def test_in_auto_mode_a_cancelled_countdown_keeps_the_image(self):
        # Le journal des tâches change l'annulation d'un compte à rebours
        # en Entrée ; Ctrl+D y vaut Entrée aussi : le défaut, non.
        for answers in ([""], [EOFError()]):
            with self.subTest(answers=answers):
                self.lst_cmd.clear()
                self.old_image()
                issue, asked = self.play(answers, True, **self.RESUMED)
                self.assertEqual(asked[0]["timeout_s"], TodoUpgrade.AUTO_DELAY)
                self.assertIs(issue, Stopped)
                self.assertIn("db_restore.py", self.lst_cmd[0])
                self.assertTrue(self.image_kept())


class TestTheBumpsOfTheMigration(MigrationRun):
    """Les questions oui/non des paliers et de la fin du déroulé, sur une
    migration vers Odoo 18 reprise juste avant OpenUpgrade : deux paliers,
    17 puis 18. À chacun : mettre à jour tous les modules (oui par défaut),
    ouvrir le serveur avec Selenium (non par défaut, « a » l'ouvre à ce
    palier et aux suivants sans plus demander). À la fin : tester la
    migration (non par défaut).

    Ici `execute` réussit chaque commande ; les outils de chaque palier,
    sa porte d'attente et la sauvegarde finale (une question texte, à
    laquelle le double répond non) sont des doubles muets."""

    BUMPS = {
        "target_odoo_version": "18.0",
        "state_0_install_odoo": True,
        "state_0_search_missing_module": True,
        "state_1_restore_database": True,
        "state_1_update_all": True,
        "state_2_update_all": True,
        "state_1_theme_uninstalled": True,
        "state_1_uninstall_module": True,
        "state_1_install_module": True,
        "state_3_clean_database": True,
        "state_4_clone_odoo_lst": [True, True],
        "state_4_switch_odoo_lst": [True, True],
        "state_4_module_migrate_odoo_lst": [True, True],
        "state_4_uninstall_module": [True, True],
        "state_4_install_module": [True, True],
        "state_4_search_missing_module": [True, True],
        "state_4_fix_migration_odoo_lst": [["forged"], ["forged"]],
    }
    TOOLS = (
        "prompt_cow_prediction",
        "prompt_database_cleanup",
        "prompt_smoke_public_url",
        "snapshot_cow_views",
        "diff_cow_views",
        "repair_cow_render",
        "neutralize_cow_views",
        "run_on_terminal",
        "run_captured",
        "run_tool",
        "drop_duplicate_index",
        "restore_config_defaults",
        "prompt_purge_dead_attachments",
    )
    UPGRADE_ALL = "Do you want to upgrade all addons of the database?"
    SELENIUM = "Open the server with Selenium to test this upgrade?"
    EVERY = "Open it at EVERY version bump, stop asking"
    TEST = "Test the migration?"

    def execute(self, cmd, **_kw):
        self.lst_cmd.append(cmd)
        return 0, cmd

    def upgrade(self, auto, **progression):
        """La migration de `MigrationRun`, aux paliers ; gardée dans
        `self.played` pour lire sa progression et ses appels."""
        upgrade = super().upgrade(auto, **{**self.BUMPS, **progression})
        for nom in self.TOOLS:
            setattr(upgrade, nom, lambda *_a, **_kw: 0)
        upgrade.get_rename_module = lambda modules, version: list(modules)
        upgrade.ask_gate = lambda prompt, default="": ""
        upgrade.ask = lambda prompt, default="": "n"
        # Le journal, dans l'ordre : ce que chaque écriture de la
        # progression retient de « a », puis chaque base ouverte.
        self.journal = []
        upgrade.write_config = lambda: self.journal.append(
            upgrade.dct_progression.get("state_4_selenium_every_bump")
        )
        upgrade.todo.prompt_execute_selenium_and_run_db.side_effect = (
            self.journal.append
        )
        self.played = upgrade
        return upgrade

    def opened(self):
        """Les bases ouvertes avec Selenium, dans l'ordre."""
        selenium = self.played.todo.prompt_execute_selenium_and_run_db
        return [call.args[0] for call in selenium.call_args_list]

    def upgraded_all(self):
        return [cmd for cmd in self.lst_cmd if "update_addons_all.sh" in cmd]

    def test_every_addon_is_upgraded_unless_no(self):
        from script.todo.todo_i18n import t

        attendre = f" ({t('or wait next version')} 🤖)"
        for answers, oui in [([""], True), *REFUSED_RUN, *YES_RUN]:
            with self.subTest(answers=answers):
                self.lst_cmd.clear()
                issue, asked = self.play([*answers, "n", *answers, "n", "n"])
                self.assertIsNone(issue)
                fois = 1 + answers.count("peut-être")
                upgrade_all = [a for a in asked if a["default"] == "y"]
                self.assertEqual(
                    [a["prompt"] for a in upgrade_all],
                    [f"💬 {t(self.UPGRADE_ALL)}{attendre}"] * fois
                    + [f"💬 {t(self.UPGRADE_ALL)}"] * fois,
                )
                attendu = [f"./script/addons/update_addons_all.sh {DB}"]
                self.assertEqual(
                    self.upgraded_all(),
                    [f"{attendu[0]}_upgrade_17", f"{attendu[0]}_upgrade_18"]
                    if oui
                    else [],
                )

    def test_selenium_opens_at_a_bump_only_on_a_yes(self):
        from script.todo.todo_i18n import t

        for answers, oui in [([""], False), *REFUSED_RUN, *YES_RUN]:
            with self.subTest(answers=answers):
                issue, asked = self.play(["", *answers, "", *answers, "n"])
                self.assertIsNone(issue)
                selenium = [a for a in asked if a.get("options")]
                fois = 1 + answers.count("peut-être")
                self.assertEqual(len(selenium), 2 * fois)
                for question in selenium:
                    self.assertEqual(
                        question["prompt"], f"💬 {t(self.SELENIUM)}"
                    )
                    self.assertEqual(question["default"], "n")
                    self.assertEqual(
                        [o["key"] for o in question["options"]], ["a"]
                    )
                    self.assertEqual(
                        question["options"][0]["label"], t(self.EVERY)
                    )
                self.assertEqual(
                    self.opened(),
                    [f"{DB}_upgrade_17", f"{DB}_upgrade_18"] if oui else [],
                )
                self.assertNotIn(
                    "state_4_selenium_every_bump", self.played.dct_progression
                )

    def test_a_opens_selenium_at_every_bump_and_asks_once(self):
        issue, asked = self.play(["", "a", "", "n"])
        self.assertIsNone(issue)
        self.assertEqual(len([a for a in asked if a.get("options")]), 1)
        self.assertEqual(
            self.opened(), [f"{DB}_upgrade_17", f"{DB}_upgrade_18"]
        )
        self.assertIs(
            self.played.dct_progression["state_4_selenium_every_bump"], True
        )
        # Écrit AVANT d'ouvrir le serveur : une reprise après ce palier ne
        # repose pas la question.
        self.assertLess(
            self.journal.index(True), self.journal.index(f"{DB}_upgrade_17")
        )

    def test_the_remembered_a_skips_the_question(self):
        issue, asked = self.play(
            ["", "", "n"], state_4_selenium_every_bump=True
        )
        self.assertIsNone(issue)
        self.assertEqual([a for a in asked if a.get("options")], [])
        self.assertEqual(
            self.opened(), [f"{DB}_upgrade_17", f"{DB}_upgrade_18"]
        )

    def test_the_migration_is_tested_at_the_end_only_on_a_yes(self):
        from script.todo.todo_i18n import t

        for answers, oui in [([""], False), *REFUSED_RUN, *YES_RUN]:
            with self.subTest(answers=answers):
                issue, asked = self.play(["", "n", "", "n", *answers])
                self.assertIsNone(issue)
                self.assertEqual(asked[-1]["prompt"], f"💬 {t(self.TEST)}")
                self.assertEqual(asked[-1]["default"], "n")
                self.assertEqual(
                    self.opened(), [f"{DB}_upgrade_18"] if oui else []
                )

    def test_a_closed_input_ends_the_run(self):
        with closed_after(5):
            issue, asked = self.play([])
        self.assertIsNone(issue)
        self.assertEqual(len(asked), 5)
        self.assertEqual(self.opened(), [])
        self.assertEqual(self.upgraded_all(), [])


# (réponses, oui) : refus du déroulé, dont Ctrl+D hors `back`, puis oui.
REFUSED_RUN = tuple((answers, False) for answers in REFUSED)
YES_RUN = tuple((answers, True) for answers in YES)


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
        self.assertIn("status = True", fenetre)

    def test_it_belongs_to_step_four(self):
        # Le nom porte sa propriété : un retour avant l'étape 4 doit
        # l'effacer, comme tout ce que l'étape 4 a décidé.
        from script.todo.todo_upgrade import STEP_PREFIX_RE

        match = STEP_PREFIX_RE.match("state_4_selenium_every_bump")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "4")


if __name__ == "__main__":
    unittest.main()
