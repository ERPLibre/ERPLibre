#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le filestore, l'analyse des modules, Monitoring, les images, le test
d'un module, Poetry et l'application mobile : les questions oui/non de
todo.py, plus celles de l'écran de qualité d'une migration, sous les
règles de `ui.confirm`.

Chaque question est non par défaut, sauf trois qui sont oui : neutraliser
la base restaurée par Monitoring, lier la sauvegarde sous image_db/,
basculer le checkout avant de rejouer un test de qualité. Un
refus — Entrée là où le défaut est non, n, non, une faute puis Ctrl+D,
Ctrl+D — n'efface, n'installe, ne lie, ne bascule ni ne lance rien ; o,
oui, y et yes agissent.

Les quatre questions de l'analyse (purge des pièces jointes, rangement du
filestore, installation des modules et sa confirmation) comptent à
rebours en mode automatique seulement ; l'échéance et l'annulation d'un
compte à rebours par la page prennent le défaut, non : rien ne s'efface.

« Neutraliser la base ? » prend `back` : Ctrl+D n'y restaure rien.
« Garder la base temporaire ? » aussi, à polarité inversée : Entrée et non
effacent la base de test, Ctrl+D la garde.

Rien ne part : `exec_command_live` est un double qui note ; ce qui
s'écrit vraiment vit dans un dossier temporaire. Un `ScriptedPort` répond
aux questions du port ; `input` ne lit que les valeurs tapées.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.analyse import check_filestore as fs  # noqa: E402
from script.analyse import check_migration_quality_tui as qtui  # noqa: E402
from script.todo import auto_ask, todo_i18n, ui  # noqa: E402
from script.todo import todo as todo_module  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402
from script.todo.ui import port  # noqa: E402
from script.todo.ui.port import ScriptedPort  # noqa: E402

DB = "forged_yesno_db"
MODULE = "forged_yesno_mod"
# Défaut non : une réponse vide, une faute puis Ctrl+D, Ctrl+D refusent.
REFUS = ([""], ["n"], ["peut-être", EOFError()], [EOFError()])
OUI = (["o"], ["oui"], ["y"], ["YES"])
# Défaut oui : n, non, une faute puis Ctrl+D, Ctrl+D refusent.
REFUS_OUI = (["n"], ["non"], ["peut-être", EOFError()], [EOFError()])
OUI_OUI = ([""], *OUI)


class _Execute:
    """Note chaque commande, sans rien lancer ; une commande qui demande
    sa sortie reçoit « DELETE 1 »."""

    def __init__(self):
        self.cmds = []

    def exec_command_live(self, cmd, **opts):
        self.cmds.append(cmd)
        if opts.get("return_status_and_output"):
            return 0, ["DELETE 1"]
        return 0


def _todo():
    todo = TODO.__new__(TODO)
    todo.execute = _Execute()
    return todo


class _Base(unittest.TestCase):
    def setUp(self):
        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("fr")
        environ = mock.patch.dict(os.environ)
        environ.start()
        self.addCleanup(environ.stop)
        os.environ.pop(auto_ask.ENV_ENABLED, None)

    def auto(self, seconds="7"):
        """Le mode automatique, pour la durée du test."""
        os.environ[auto_ask.ENV_ENABLED] = "1"
        os.environ[auto_ask.ENV_DELAY] = seconds

    def play(self, call, answers, typed=()):
        """Ce que rend `call()` quand `answers` répondent, dans l'ordre, par
        un `ScriptedPort` (`self.port`) ; `typed` répond aux valeurs lues
        par `input`, qu'aucune autre question ne lit. `self.out` garde ce
        qui s'imprime."""
        with (
            mock.patch(
                "builtins.input",
                side_effect=list(typed) if typed else AssertionError,
            ),
            mock.patch("builtins.print") as self.out,
            ui.bind(ScriptedPort(list(answers))) as self.port,
        ):
            return call()

    def confirms(self):
        return [e for e in self.port.events if e.get("kind") == "confirm"]

    def asked(self, prompt):
        """Chaque question oui/non `prompt` posée, (texte, défaut « y » ou
        « n », `back`), une fois de plus après chaque faute."""
        return [
            (e["prompt"], e["default"], e.get("back", False))
            for e in self.confirms()
            if e["prompt"] == prompt
        ]

    def notices(self):
        return [e["text"] for e in self.port.events if e.get("t") == "notice"]

    def check(
        self,
        make,
        prompt,
        default=False,
        back=False,
        pre=(),
        post=(),
        after=(),
        typed=(),
    ):
        """`make()` rend (`call`, `acted`), neufs pour chaque cas ; la
        question oui/non `prompt`, de défaut `default`, suit les réponses
        `pre` du port et les valeurs tapées `typed` ; `post` suit un oui,
        `after` toute réponse. Chaque refus laisse `acted()` faux, chaque
        oui le rend vrai, chaque réponse est lue ; une faute est dite, puis
        la question revient ; le message porte `back` quand il est dit."""
        refus, oui = (REFUS_OUI, OUI_OUI) if default else (REFUS, OUI)
        cases = [(r, False) for r in refus] + [(o, True) for o in oui]
        for answers, expected in cases:
            with self.subTest(answers=answers):
                call, acted = make()
                tail = [*post] if expected else []
                self.play(call, [*pre, *answers, *tail, *after], typed)
                fois = 2 if "peut-être" in answers else 1
                posee = (prompt, "y" if default else "n", back)
                self.assertEqual(self.asked(prompt), [posee] * fois)
                self.assertEqual(self.port.answers, [])
                self.assertIs(acted(), expected)
                if "peut-être" in answers:
                    self.assertIn(
                        f"{t('Answer yes or no: ')}peut-être", self.notices()
                    )


def _rapport(racine="/fs/db"):
    groupes = {verdict: [] for verdict in fs.VERDICTS}
    groupes["dead_field"] = [
        {
            "store_fname": "a/1",
            "model": "",
            "id": "7",
            "field": "",
            "res_id": "1",
            "name": "x",
            "size": 1024,
            "mimetype": "image/png",
            "created": "2019-11-30",
        }
    ]
    return {"root": racine, "groups": groupes, "dead_ids": [3]}


def purge_question():
    return f"{t('Delete these')} 1 {t('attachment row(s) for good?')}"


class TestTheFilestoreRepairs(_Base):
    """Purger les pièces jointes mortes efface des lignes en base, ranger
    le filestore efface des doublons : non par défaut, à rebours en mode
    automatique seulement."""

    def setUp(self):
        super().setUp()
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine, True)

    def purge(self):
        todo = _todo()

        def call():
            return todo._filestore_purge_dead(DB, _rapport())

        return call, lambda: any("psql" in c for c in todo.execute.cmds)

    def nest(self):
        """(`call`, `acted`) du rangement d'un filestore imbriqué neuf :
        un fichier à remonter, un doublon pur."""
        base = tempfile.mkdtemp(dir=self.racine)
        for chemin, contenu in (
            ("aa/deja", "bon"),
            ("filestore/aa/deja", "bon"),
            ("filestore/bb/absent", "utile"),
        ):
            complet = os.path.join(base, chemin)
            os.makedirs(os.path.dirname(complet), exist_ok=True)
            with open(complet, "w", encoding="utf-8") as handle:
                handle.write(contenu)
        todo = _todo()

        def call():
            return todo._filestore_tidy_nested({"root": base})

        nid = os.path.join(base, "filestore")
        return call, lambda: not os.path.isdir(nid)

    def test_the_purge_deletes_on_a_yes_only(self):
        self.check(self.purge, purge_question())

    def test_the_tidy_moves_and_deletes_on_a_yes_only(self):
        self.check(self.nest, t("Go ahead?"))

    def test_both_count_down_in_auto_mode_only(self):
        for make in (self.purge, self.nest):
            with self.subTest(make=make.__name__):
                call, _acted = make()
                self.play(call, ["n"])
                self.assertNotIn("timeout_s", self.confirms()[0])
                self.auto()
                call, _acted = make()
                self.play(call, ["n"])
                self.assertEqual(self.confirms()[0]["timeout_s"], 7)
                os.environ.pop(auto_ask.ENV_ENABLED)

    def test_the_deadline_deletes_nothing(self):
        # Au terminal, l'échéance du compte à rebours d'auto_ask rend le
        # défaut de la question, en un mot de la langue choisie.
        self.auto()
        heard = []

        def deadline(text, default, seconds):
            heard.append((text, default, seconds))
            return default

        for make in (self.purge, self.nest):
            with self.subTest(make=make.__name__):
                call, acted = make()
                with (
                    mock.patch.dict(port.ORIGINAL, {"auto_ask.ask": deadline}),
                    mock.patch("builtins.print"),
                ):
                    self.assertFalse(call())
                self.assertFalse(acted())
        self.assertEqual(
            heard,
            [
                (f"{purge_question()} [o/N] : ", "Non", 7),
                (f"{t('Go ahead?')} [o/N] : ", "Non", 7),
            ],
        )

    def test_a_countdown_cancelled_by_the_page_deletes_nothing(self):
        # Le journal des tâches change l'annulation d'un compte à rebours
        # en Entrée, que le worker lit ; Ctrl+D y vaut Entrée aussi.
        self.auto()
        for make in (self.purge, self.nest):
            for answers in ([""], [EOFError()]):
                with self.subTest(make=make.__name__, answers=answers):
                    call, acted = make()
                    self.assertFalse(self.play(call, answers))
                    self.assertFalse(acted())
                    self.assertEqual(self.port.answers, [])


RAPPORT = {
    "lines": [
        {
            "module": module,
            "verdict": verdict,
            "from": "p",
            "state": "",
            "shortdesc": "",
            "needs": [],
        }
        for module, verdict in (
            ("queue_job", "available"),
            ("web_dark_mode", "available"),
            ("absent", "unknown"),
        )
    ]
}


class TestTheModuleInstall(_Base):
    """Installer des modules dans la base analysée : non par défaut, à
    l'offre comme à la confirmation de la liste choisie ; à rebours en
    mode automatique seulement."""

    def setUp(self):
        super().setUp()
        from script.odoo.migration import database_cleanup

        garde = mock.patch.object(
            database_cleanup, "require_matching_version", lambda base: None
        )
        garde.start()
        self.addCleanup(garde.stop)

    def install(self):
        todo = _todo()
        self.todo = todo

        def call():
            return todo._analyse_offer_install(DB, RAPPORT)

        return call, lambda: bool(todo.execute.cmds)

    def offer(self):
        return (
            f"{t('Install some of the')} 2"
            f" {t('suggested module(s) waiting in this database?')}"
            f" (1 {t('need repair first')})"
        )

    def test_the_offer_installs_on_a_yes_only(self):
        self.check(self.install, self.offer(), post=["1", "o"])

    def test_the_list_installs_on_a_yes_only(self):
        self.check(self.install, t("Go ahead?"), pre=["o", "1"])

    def test_a_yes_installs_exactly_the_chosen_module(self):
        call, _acted = self.install()
        self.play(call, ["o", "1", "o"])
        self.assertEqual(
            self.todo.execute.cmds,
            [f"./script/addons/install_addons.sh {DB} queue_job"],
        )

    def test_both_questions_count_down_in_auto_mode_only(self):
        call, _acted = self.install()
        self.play(call, ["o", "1", "n"])
        self.assertEqual(
            [e.get("timeout_s") for e in self.confirms()], [None, None]
        )
        self.auto()
        call, acted = self.install()
        self.play(call, ["", EOFError()])
        self.assertEqual([e["timeout_s"] for e in self.confirms()], [7])
        call, acted = self.install()
        self.play(call, ["o", "1", ""])
        self.assertEqual([e["timeout_s"] for e in self.confirms()], [7, 7])
        self.assertFalse(acted())


class TestMonitoring(_Base):
    """Les options d'anonymisation, la neutralisation de la base restaurée
    et le lien sous image_db/."""

    def options(self, question):
        """(`call`, `acted`) des options du mode hybride : `acted` dit si
        l'option de `question` est retenue."""
        option = {
            "logins": "--include-logins",
            "digits": "--keep-digits",
        }[question]
        rendu = []
        todo = _todo()

        def call():
            rendu.append(todo._monitoring_anonymize_options())

        return call, lambda: option in rendu[0]

    def test_the_logins_are_anonymised_on_a_yes_only(self):
        self.check(
            lambda: self.options("logins"),
            t("Anonymise the logins too?"),
            pre=["1"],
            after=["n"],
            typed=["", ""],
        )

    def test_the_digit_count_is_kept_on_a_yes_only(self):
        self.check(
            lambda: self.options("digits"),
            t("Keep the digit count?"),
            pre=["1", "n"],
            typed=["", ""],
        )

    def restore(self):
        """(`call`, `acted`) d'une restauration de `DB` : `acted` dit si
        elle part neutralisée ; `self.rendu` garde ce qu'elle rend."""
        todo = _todo()
        self.todo = todo
        self.rendu = []
        from script.analyse import monitoring

        def call():
            with (
                mock.patch.object(
                    TODO, "_monitoring_image_name", return_value=DB
                ),
                mock.patch.object(monitoring, "neutralize_state"),
                mock.patch.object(
                    monitoring, "neutralize_report", return_value=""
                ),
            ):
                self.rendu.append(todo._monitoring_restore("/forged.zip"))

        return call, lambda: any(
            "--neutralize" in c for c in todo.execute.cmds
        )

    def test_the_restore_is_neutralized_unless_refused(self):
        self.check(
            self.restore,
            t("Neutralize the database?"),
            default=True,
            back=True,
            typed=[""],
        )

    def test_ctrl_d_at_neutralize_restores_nothing(self):
        for answers in ([EOFError()], ["peut-être", EOFError()]):
            with self.subTest(answers=answers):
                call, _acted = self.restore()
                self.play(call, answers, typed=[""])
                self.assertEqual(self.rendu, [None])
                self.assertEqual(self.todo.execute.cmds, [])

    def test_a_refusal_restores_without_neutralizing(self):
        call, _acted = self.restore()
        self.play(call, ["n"], typed=[""])
        self.assertEqual(self.rendu, [DB])
        [restore] = self.todo.execute.cmds
        self.assertIn(f"-d {DB} --ignore_cache", restore)

    def link(self):
        """(`call`, `acted`) du lien d'une sauvegarde hors d'image_db/,
        dans un dossier de travail neuf ; `self.rendu` garde le nom
        rendu."""
        racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, racine, True)
        sauvegarde = os.path.join(racine, f"{DB}.zip")
        open(sauvegarde, "w").close()
        travail = os.path.join(racine, "checkout")
        os.mkdir(travail)
        self.rendu = []
        todo = _todo()

        def call():
            avant = os.getcwd()
            os.chdir(travail)
            try:
                self.rendu.append(todo._monitoring_image_name(sauvegarde))
            finally:
                os.chdir(avant)

        cible = os.path.join(travail, "image_db", f"{DB}.zip")
        self.cible = cible
        return call, lambda: os.path.islink(cible)

    def test_the_backup_is_linked_unless_refused(self):
        # Le chemin du lien, dans la question, change à chaque cas.
        cases = [(r, False) for r in REFUS_OUI] + [(o, True) for o in OUI_OUI]
        for answers, expected in cases:
            with self.subTest(answers=answers):
                call, acted = self.link()
                self.play(call, answers)
                prompt = (
                    t("db_restore only reads image_db/. Link it there (%s)?")
                    % self.cible
                )
                fois = 2 if "peut-être" in answers else 1
                posee = [(prompt, "y", False)] * fois
                self.assertEqual(self.asked(prompt), posee)
                self.assertIs(acted(), expected)
                self.assertEqual(self.rendu, [DB if expected else None])


class TestImageVersionSwitch(_Base):
    """Générer des images avec une autre version installée que l'active
    demande de basculer le checkout : non par défaut."""

    def switch(self):
        todo = _todo()
        from script.database import image_db

        def call():
            with (
                mock.patch.object(
                    todo_module,
                    "get_odoo_version",
                    return_value=([], ["odoo17.0", "odoo18.0"], "odoo18.0"),
                ),
                mock.patch.object(image_db, "load_image_config"),
                mock.patch.object(
                    image_db,
                    "versions_with_images",
                    return_value=["17.0", "18.0"],
                ),
            ):
                return todo._image_db_choose_version(generer=True)

        return call, lambda: "make switch_odoo_17" in todo.execute.cmds

    def test_the_checkout_switches_on_a_yes_only(self):
        prompt = t(
            "The images are generated with the active Odoo: switch to"
            " Odoo %s now (make switch_odoo_%s)?"
        ) % ("17.0", "17")
        self.check(self.switch, prompt, pre=["1"])


class TestTheTemporaryDatabase(_Base):
    """« Garder la base temporaire ? », non par défaut : Entrée et non
    effacent la base de test qu'Execute › Test a module vient de créer ;
    oui et Ctrl+D la gardent."""

    def test_enter_and_no_drop_it_yes_and_ctrl_d_keep_it(self):
        drop = f"./odoo_bin.sh db drop {DB}"
        prompt = t("Keep the temporary database?")
        cases = [
            ([""], True),
            (["n"], True),
            (["non"], True),
            (["o"], False),
            (["oui"], False),
            (["YES"], False),
            ([EOFError()], False),
            (["peut-être", EOFError()], False),
        ]
        for answers, dropped in cases:
            with self.subTest(answers=answers):
                todo = _todo()
                self.play(
                    todo.execute_test_module,
                    answers,
                    typed=[MODULE, DB, "", ""],
                )
                self.assertIs(drop in todo.execute.cmds, dropped)
                self.assertEqual(todo.execute.cmds[0].split()[-1], DB)
                fois = 2 if "peut-être" in answers else 1
                self.assertEqual(
                    self.asked(prompt), [(prompt, "n", True)] * fois
                )


class TestUpgradePoetry(_Base):
    """Récupérer les dépôts, puis installer les dépendances : non par
    défaut, les deux."""

    def poetry(self, command):
        todo = _todo()
        return todo.upgrade_poetry, lambda: any(
            command in c for c in todo.execute.cmds
        )

    def test_the_repositories_are_fetched_on_a_yes_only(self):
        self.check(
            lambda: self.poetry("update_manifest_local_dev.sh"),
            t("The update needs your git repositories: fetch them all first?"),
            after=["n"],
        )

    def test_the_dependencies_are_installed_on_a_yes_only(self):
        self.check(
            lambda: self.poetry("EL_PHASE=poetry"),
            t("Install the new dependencies in the Odoo venv now?"),
            pre=["n"],
        )


class TestTheMobileApplication(_Base):
    """Personnaliser l'application, la compiler en débogage, changer
    l'image du menu, tolérer le HTTP en clair : non par défaut."""

    NAMES = ["Forged Yesno", "ca.forged.yesno", "https://forged.invalid", "x"]

    def mobile(self, acted):
        todo = _todo()
        dotenv = mock.MagicMock()
        dotenv.get_key.return_value = "x"

        def call():
            with (
                mock.patch.object(todo_module, "dotenv", dotenv),
                mock.patch.object(
                    todo_module, "STRINGS_FILE", "/nonexistent/strings.xml"
                ),
            ):
                todo.callback_make_mobile_home()

        return call, lambda: acted(todo.execute.cmds, dotenv)

    def test_the_application_is_personalized_on_a_yes_only(self):
        def personalized(cmds, _dotenv):
            return "Forged Yesno" in cmds[0]

        self.check(
            lambda: self.mobile(personalized),
            t("Do you want to personalize the mobile application?"),
            post=["n", "n"],
            after=["n"],
            typed=self.NAMES,
        )

    def test_debug_is_compiled_in_on_a_yes_only(self):
        def debug(_cmds, dotenv):
            return (
                mock.call(
                    mock.ANY, "VITE_DEBUG_DEV", "true", quote_mode="never"
                )
                in dotenv.set_key.call_args_list
            )

        self.check(
            lambda: self.mobile(debug),
            t("Compile with debug information?"),
            pre=["o"],
            after=["n", "n"],
            typed=self.NAMES,
        )

    def test_android_studio_opens_on_a_yes_only(self):
        def studio(cmds, _dotenv):
            return any("npx cap open android" in c for c in cmds)

        self.check(
            lambda: self.mobile(studio),
            t("Android Studio is needed: change the menu picture?"),
            pre=["o", "n"],
            after=["n"],
            typed=[*self.NAMES, ""],
        )

    def test_plain_http_is_tolerated_on_a_yes_only(self):
        def cleartext(cmds, _dotenv):
            return cmds[-1].endswith("--lan-cleartext")

        self.check(
            lambda: self.mobile(cleartext),
            t("mobile_lan_cleartext_ask"),
            pre=["n"],
        )


class TestTheQualityScreenSwitch(_Base):
    """Rejouer un test de l'écran de qualité sur un palier d'une autre
    version : « make switch_odoo_N d'abord ? », oui par défaut, puis, si la
    bascule échoue, « lancer le test quand même ? », non par défaut.
    « ok » et « yolo » ne valent plus oui. Ctrl+C abandonne sans rien
    lancer de plus."""

    def run_test(self, make_code=0, make_raises=None):
        """`make_raises`, une exception que la bascule lève au lieu de
        rendre `make_code`."""
        lances = []

        def run_in_terminal(command, wait=True, capture=None):
            lances.append(command)
            if command.startswith("make") and make_raises:
                raise make_raises
            return (make_code if command.startswith("make") else 0), True

        rendu = []

        def call():
            with (
                mock.patch.object(qtui, "run_in_terminal", run_in_terminal),
                mock.patch.object(
                    qtui.quality, "checkout_version", return_value=18
                ),
            ):
                rendu.append(
                    qtui.run_with_switch("smoke -d x", (16, "switch_odoo_16"))
                )

        self.lances, self.rendu = lances, rendu
        return call

    def test_the_switch_runs_first_unless_refused(self):
        def make():
            call = self.run_test()
            lances = self.lances
            return call, lambda: lances[0] == "make switch_odoo_16"

        prompt = f"  {t('run')} « make switch_odoo_16 » {t('first?')}"
        self.check(make, prompt.rstrip(), default=True)

    def test_a_refused_switch_still_runs_the_test(self):
        call = self.run_test()
        self.play(call, ["n"])
        self.assertEqual(self.lances, ["smoke -d x"])

    def test_a_failed_switch_runs_the_test_on_a_yes_only(self):
        def make():
            call = self.run_test(make_code=2)
            lances = self.lances
            return call, lambda: "smoke -d x" in lances

        self.check(make, f"  {t('run the test anyway?')}", pre=[""])

    def test_ctrl_c_runs_nothing_more(self):
        """Ctrl+C à la question ou pendant la bascule rend (None, False) :
        le test ne part pas, et rien ne remonte jusqu'à l'écran."""
        cases = (
            ("question", {}, [KeyboardInterrupt()], []),
            (
                "bascule",
                {"make_raises": KeyboardInterrupt()},
                [""],
                ["make switch_odoo_16"],
            ),
        )
        for nom, opts, answers, lances in cases:
            with self.subTest(nom):
                call = self.run_test(**opts)
                self.play(call, answers)
                self.assertEqual(self.lances, lances)
                self.assertEqual(self.rendu, [(None, False)])
                self.assertEqual(self.port.answers, [])

    def test_ok_and_yolo_are_typos(self):
        for mot in ("ok", "yolo"):
            with self.subTest(mot=mot):
                call = self.run_test()
                self.play(call, [mot, EOFError()])
                self.assertEqual(self.lances, ["smoke -d x"])
                self.assertIn(
                    f"{t('Answer yes or no: ')}{mot}", self.notices()
                )


if __name__ == "__main__":
    unittest.main()
