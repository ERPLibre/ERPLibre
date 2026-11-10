#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les choix d'Upgrade Module et de la reprise d'une migration, sous des
doubles.

`execute_module_upgrade` choisit ce qu'il migre, puis bascule le checkout
sur une version d'Odoo, clone le migrateur et migre le code. Ici, rien de
cela ne part : `switch_odoo`, `install_OCA_odoo_module_migrator`,
`internal_module_upgrade` et `todo_upgrade_execute` sont des doubles qui
notent leur appel, le navigateur de fichiers un double qui ne choisit
rien, et le journal de migration un fichier d'un répertoire jetable. La
reprise d'une migration et l'étape à rejouer tournent dans un répertoire
courant jetable, où s'écrit l'archive du journal.
"""

import builtins
import contextlib
import glob
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from script.todo import auto_ask, todo_upgrade
from script.todo.todo_i18n import t
from script.todo.todo_upgrade import TodoUpgrade


class Arret(Exception):
    """Levée par le double de `switch_odoo` : la migration s'arrête là."""


class NavigateurQuiRenonce:
    """Le navigateur de fichiers quitté sans rien choisir : son rappel
    n'est jamais appelé."""

    ouverts = []

    def __init__(self, start, callback, open_dir=False):
        NavigateurQuiRenonce.ouverts.append((start, open_dir))

    def run_main_frame(self):
        pass


class NavigateurQuiChoisit(NavigateurQuiRenonce):
    """Le navigateur où l'on choisit le répertoire `choix` : son rappel
    reçoit ce chemin."""

    choix = None

    def __init__(self, start, callback, open_dir=False):
        super().__init__(start, callback, open_dir)
        self.callback = callback

    def run_main_frame(self):
        self.callback(NavigateurQuiChoisit.choix)


class Banc(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        journal = os.path.join(dossier.name, "migration_log.json")
        patcher = mock.patch.object(
            todo_upgrade, "UPGRADE_DATABASE_CONFIG_LOG", journal
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        NavigateurQuiRenonce.ouverts = []
        self.trouves = [["forged_module", "/forged"]]

    def migrer(self, reponses, arret=True, navigateur=NavigateurQuiRenonce):
        """Lance execute_module_upgrade ; rend les gestes notés, dans
        l'ordre. Une réponse qui est une exception est levée (EOFError,
        Ctrl+D) ; une question de plus que de réponses fait échouer le
        test en le disant, une réponse restée non lue aussi : un retour
        qui vient avant la question visée ne passe pas pour elle. Le
        premier `switch_odoo` arrête la migration après l'avoir noté
        (`Arret`), sauf avec `arret` faux : la migration va alors au bout,
        et `ask`, la pause après chaque palier, est noté aussi.
        `check_addons_exist` trouve le module demandé, `self.trouves`.
        `navigateur` double le navigateur de fichiers, sans la boucle
        urwid que son choix quitte (`exit_program`). L'écran imprimé est
        dans `self.ecran`."""
        upgrade = TodoUpgrade(todo=None)
        gestes = []

        def noter(nom):
            def double(*args, **kwargs):
                gestes.append((nom, args))
                if nom == "switch_odoo" and arret:
                    raise Arret
                if nom == "check_addons_exist":
                    return [], [], self.trouves, []
                if nom == "ask":
                    return ""

            return double

        for nom in (
            "switch_odoo",
            "install_OCA_odoo_module_migrator",
            "internal_module_upgrade",
            "todo_upgrade_execute",
            "check_addons_exist",
            "ask",
        ):
            setattr(upgrade, nom, noter(nom))
        suite = iter(reponses)

        def repondre(prompt=""):
            try:
                reponse = next(suite)
            except StopIteration:
                raise AssertionError(
                    f"question sans réponse prévue : {prompt!r}"
                ) from None
            if isinstance(reponse, BaseException):
                raise reponse
            return reponse

        ecran = io.StringIO()
        with (
            mock.patch.object(builtins, "input", repondre),
            mock.patch.object(
                todo_upgrade.todo_file_browser, "FileBrowser", navigateur
            ),
            mock.patch.object(todo_upgrade.todo_file_browser, "exit_program"),
            contextlib.redirect_stdout(ecran),
        ):
            try:
                upgrade.execute_module_upgrade()
            except Arret:
                pass
        self.ecran = ecran.getvalue()
        self.assertEqual(next(suite, None), None, "réponse non lue")
        return gestes


class TestLeNavigateurQuitte(Banc):
    def test_leaving_the_browser_migrates_nothing(self):
        """Le navigateur de répertoires quitté sans choix : la migration
        revient sans erreur, sans basculer de version ni rien migrer."""
        gestes = self.migrer([""])
        self.assertEqual(len(NavigateurQuiRenonce.ouverts), 1)
        self.assertEqual(gestes, [])


class TestLesChoix(Banc):
    """Ce qu'on migre, comment on trouve le module, et les deux versions :
    des choix sous les règles d'un sélecteur."""

    def setUp(self):
        super().setUp()
        depot = tempfile.TemporaryDirectory()
        self.addCleanup(depot.cleanup)
        self.depot = depot.name

    def test_back_at_each_choice_migrates_nothing(self):
        """[0] ou Ctrl+D à chaque choix, et une réponse vide à une version,
        qui n'a pas de défaut : aucune version basculée, rien de migré."""
        avants = (
            [],
            ["1"],
            ["1", "2", "forged_module"],
            ["1", "2", "forged_module", "1"],
            ["2", self.depot],
            ["2", self.depot, "1"],
            ["1", "1", self.depot],
            ["1", "1", self.depot, "1"],
        )
        for avant in avants:
            vides = ("",) if len(avant) > 1 else ()
            for retour in ("0", EOFError(), *vides):
                with self.subTest(avant=avant, retour=retour):
                    gestes = self.migrer([*avant, retour])
                    self.assertEqual(gestes, [])

    def test_ctrl_d_at_the_module_name_or_the_path_migrates_nothing(self):
        """Ctrl+D au nom du module, au chemin du module ou à celui du
        dépôt : la migration revient sans ouvrir le navigateur, sans
        basculer de version ni rien migrer."""
        for avant in (["1", "2"], ["1", "1"], ["2"]):
            with self.subTest(avant=avant):
                self.assertEqual(self.migrer([*avant, EOFError()]), [])
        self.assertEqual(NavigateurQuiRenonce.ouverts, [])

    def test_an_empty_module_name_switches_nothing(self):
        """Un nom de module vide, ou fait de blancs, revient avant que les
        versions soient demandées : le checkout ne bascule pas."""
        for nom in ("", "   "):
            with self.subTest(nom=nom):
                self.assertEqual(self.migrer(["1", "2", nom]), [])

    def test_a_module_by_name_switches_to_the_chosen_start(self):
        """Le module par son nom, la version de départ par la version
        affichée, l'arrivée par son numéro : le checkout bascule sur le
        départ, et rien d'autre ne part avant."""
        gestes = self.migrer(["1", "2", "forged_module", "12", "3"])
        self.assertEqual(gestes, [("switch_odoo", (12,))])

    def test_a_repo_climbs_from_the_version_after_its_start(self):
        gestes = self.migrer(["2", self.depot, "4", "18"])
        self.assertEqual(gestes, [("switch_odoo", (16,))])

    def test_the_arrival_offers_only_the_later_versions(self):
        self.migrer(["2", self.depot, "18", "17", "0"])
        self.assertIn(f"{t('Invalid choice: ')}18", self.ecran)
        arrivee = self.ecran.rsplit(t("To odoo version"), 1)[1]
        self.assertIn("[1] 18\n", arrivee)
        self.assertNotIn("[2] ", arrivee)

    def test_the_letters_of_old_are_said_invalid(self):
        """« m » et « r » sont des fautes : un numéro, ou Entrée pour le
        navigateur, le défaut marqué."""
        gestes = self.migrer(["m", "r", "0"])
        self.assertEqual(gestes, [])
        self.assertEqual(self.ecran.count(t("Invalid choice: ")), 2)
        self.assertIn(f"{t('Directory browser')} {t('(default)')}", self.ecran)


class TestLaMigrationDuCode(Banc):
    """La migration du code, une fois ses choix faits, palier par palier :
    chaque geste noté par un double, dans l'ordre, pour un module de
    `forged_repo` présent sous odoo12.0 et odoo13.0."""

    def setUp(self):
        super().setUp()
        racine = tempfile.TemporaryDirectory()
        self.addCleanup(racine.cleanup)
        for version in (12, 13):
            depot = os.path.join(
                racine.name, f"odoo{version}.0", "forged_repo"
            )
            os.makedirs(os.path.join(depot, "forged_notes"))
            os.makedirs(os.path.join(depot, "forged_module"))
            manifeste = os.path.join(depot, "forged_module", "__manifest__.py")
            open(manifeste, "w").close()
        self.depot = os.path.join(racine.name, "odoo12.0", "forged_repo")
        self.module = os.path.join(self.depot, "forged_module")
        self.trouves = [["forged_module", self.module]]

    def paliers(self, depart, arrivee):
        """Les gestes de chaque palier de `depart` à `arrivee` : basculer,
        cloner le migrateur, migrer le module, commiter son dépôt, puis
        attendre la validation des commits."""
        gestes = []
        for version in range(depart, arrivee):
            suivante = version + 1
            source = self.module.replace("odoo12.0", f"odoo{version}.0")
            cible = source.replace(f"odoo{version}.0", f"odoo{suivante}.0")
            module = {
                "source_module_path": source,
                "source_manifest_path": os.path.join(
                    source, "__manifest__.py"
                ),
                "source_addons_path": os.path.dirname(source),
                "target_module_path": cible,
                "target_manifest_path": os.path.join(cible, "__manifest__.py"),
                "target_addons_path": os.path.dirname(cible),
                "module_name": "forged_module",
                "source_version_odoo": version,
                "target_version_odoo": suivante,
            }
            commit = (
                "./script/code/git_commit_migration_addons_path.py"
                f" --path {os.path.dirname(cible)}"
                f" --odoo_version {suivante}.0"
            )
            pause = (
                f"💬 {t('Please validate git commit on repos, press to')}"
                f" {t('continue')} : "
            )
            gestes += [
                ("switch_odoo", (suivante,)),
                ("install_OCA_odoo_module_migrator", ()),
                ("internal_module_upgrade", (suivante, [module], [])),
                ("todo_upgrade_execute", (commit,)),
                ("ask", (pause,)),
            ]
        return gestes

    def test_a_repo_migrates_each_of_its_modules_at_each_step(self):
        gestes = self.migrer(["2", self.depot, "1", "2"], arret=False)
        self.assertEqual(gestes, self.paliers(12, 14))

    def test_a_module_by_its_path_migrates_one_step(self):
        gestes = self.migrer(["1", "1", self.module, "1", "1"], arret=False)
        self.assertEqual(gestes, self.paliers(12, 13))

    def test_a_directory_from_the_browser_migrates_its_modules(self):
        NavigateurQuiChoisit.choix = self.depot
        gestes = self.migrer(
            ["", "1", "1"], arret=False, navigateur=NavigateurQuiChoisit
        )
        self.assertEqual(gestes, self.paliers(12, 13))

    def test_a_module_by_its_name_switches_to_the_start_first(self):
        gestes = self.migrer(
            ["1", "2", "forged_module", "12", "2"], arret=False
        )
        trouve = ("check_addons_exist", (["forged_module"],))
        self.assertEqual(
            gestes, [("switch_odoo", (12,)), trouve, *self.paliers(12, 14)]
        )


class TestLesInstantanesCOW(unittest.TestCase):
    """Les statistiques de migration › COW : deux instantanés à comparer,
    l'un puis l'autre ; la comparaison est un double."""

    SNAPS = [
        {"label": "forged_snap_before", "count": 3, "taken_at": "t1"},
        {"label": "forged_snap_after", "count": 4, "taken_at": "t2"},
        {"label": "forged_snap_final", "count": 5, "taken_at": "t3"},
    ]

    def comparer(self, *reponses, snaps=None):
        """Les paires comparées, et l'écran imprimé dans `self.ecran` ;
        une réponse restée non lue fait échouer le test."""
        upgrade = TodoUpgrade(todo=None)
        paires = []
        upgrade.diff_cow_views = lambda base, a, b: paires.append((a, b))
        suite = iter(reponses)
        ecran = io.StringIO()
        with (
            mock.patch.object(builtins, "input", side_effect=suite),
            contextlib.redirect_stdout(ecran),
        ):
            upgrade.stats_cow({"cow": snaps or self.SNAPS}, "forged_db")
        self.ecran = ecran.getvalue()
        self.assertEqual(next(suite, None), None, "réponse non lue")
        return paires

    def test_two_snapshots_by_number_or_name(self):
        self.assertEqual(
            self.comparer("1", "forged_snap_final"),
            [("forged_snap_before", "forged_snap_final")],
        )

    def test_back_an_empty_answer_or_ctrl_d_at_either_compare_nothing(self):
        for avant in ([], ["2"]):
            for retour in ("0", "", EOFError()):
                with self.subTest(avant=avant, retour=retour):
                    self.assertEqual(self.comparer(*avant, retour), [])

    def test_a_typo_is_said_and_asked_again(self):
        self.assertEqual(
            self.comparer("1,2", "1", "3", "1"),
            [("forged_snap_before", "forged_snap_after")],
        )
        self.assertEqual(self.ecran.count(t("Invalid choice: ")), 2)

    def test_the_second_choice_offers_the_others_only(self):
        """Le second choix n'offre plus le premier : son nom n'y est pas
        lu, et ses numéros ne vont que jusqu'au nombre qui reste."""
        self.assertEqual(
            self.comparer("1", "forged_snap_before", "3", "1"),
            [("forged_snap_before", "forged_snap_after")],
        )
        self.assertEqual(self.ecran.count(t("Invalid choice: ")), 2)

    def test_a_single_snapshot_asks_nothing(self):
        self.assertEqual(self.comparer(snaps=self.SNAPS[:1]), [])
        self.assertIn(t("Need two snapshots to diff."), self.ecran)


class Reprise(unittest.TestCase):
    """Une migration arrêtée au premier de ses deux paliers, vers 16 : le
    journal de migration est un fichier d'un répertoire courant jetable,
    sous lequel `archive_progression` écrit ses archives (private/…)."""

    # Les fonctions qui effacent la progression, ou l'archivent avant.
    EFFACENT = (
        "archive_progression",
        "rewind_progression",
        "rewind_version_bump",
    )

    PROGRESSION = {
        "migration_file": "./image_db/forged_resume.zip",
        "config_database_name": "forged_resume_db",
        "target_odoo_version": "16.0",
        "state_0_install_odoo": True,
        "state_1_restore_database": True,
        "state_4_switch_odoo_lst": [True, False],
    }

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(dossier.name)
        self.journal = os.path.join(dossier.name, "migration_log.json")
        patcher = mock.patch.object(
            todo_upgrade, "UPGRADE_DATABASE_CONFIG_LOG", self.journal
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def repondre(self, action, reponses):
        """Ce que rend `action()`, chaque `input` répondu par `reponses` ;
        l'écran dans `self.ecran`, les invites passées à `input` dans
        `self.invites`, celles des fonctions d'EFFACENT qui ont été
        appelées dans `self.effacements` ; une réponse restée non lue fait
        échouer le test."""
        suite = iter(reponses)
        ecran = io.StringIO()
        with contextlib.ExitStack() as pile:
            entree = pile.enter_context(
                mock.patch.object(builtins, "input", side_effect=suite)
            )
            espions = {
                nom: pile.enter_context(
                    mock.patch.object(
                        TodoUpgrade, nom, side_effect=getattr(TodoUpgrade, nom)
                    )
                )
                for nom in self.EFFACENT
            }
            pile.enter_context(contextlib.redirect_stdout(ecran))
            rendu = action()
        self.ecran = ecran.getvalue()
        self.invites = [appel.args[0] for appel in entree.call_args_list]
        self.effacements = [
            n for n, espion in espions.items() if espion.called
        ]
        self.assertEqual(next(suite, None), None, "réponse non lue")
        return rendu

    @staticmethod
    def archives():
        return glob.glob("private/odoo/migration/*/migration_log/*.json")

    def attendu(self, rembobiner, *args):
        """La progression que rend `rembobiner(PROGRESSION, *args)`, ce
        qu'il imprime tu."""
        with contextlib.redirect_stdout(io.StringIO()):
            return rembobiner(dict(self.PROGRESSION), *args)


class TestLaReprise(Reprise):
    """Upgrade Odoo - Migration Database, une migration en cours : la
    reprise par le port, sur une progression qui n'est pas écrite ici
    (l'appelant l'écrit quand elle change)."""

    def reprendre(self, *reponses, auto=False):
        """La reprise par le port ; avec `auto`, en mode automatique, où
        une question à compte à rebours imprimerait « ⏱ »."""
        upgrade = TodoUpgrade(todo=None)
        if auto:
            upgrade.auto_execute = True
            auto_ask.export(True, upgrade.AUTO_DELAY)
            self.addCleanup(auto_ask.export, False)
        progression = dict(self.PROGRESSION)
        return self.repondre(
            lambda: upgrade.prompt_resume(progression), reponses
        )

    def test_an_empty_answer_or_c_continues_without_a_question(self):
        """La réponse vide prend le défaut marqué, [c], et « c » tapé, sans
        casse, continue aussi : sans confirmation, ni compte à rebours en
        mode automatique."""
        for auto in (False, True):
            for reponse in ("", "c", "C"):
                with self.subTest(auto=auto, reponse=reponse):
                    rendu = self.reprendre(reponse, auto=auto)
                    self.assertEqual(rendu, (self.PROGRESSION, False))
                    self.assertEqual(self.invites, [": "])
                    self.assertNotIn("⏱", self.ecran)
                    self.assertEqual(self.effacements, [])
        self.assertIn(
            f"[c] {t('Continue where it stopped')} {t('(default)')}\n",
            self.ecran,
        )
        self.assertEqual(self.archives(), [])

    def test_back_or_ctrl_d_quits_and_erases_nothing(self):
        for reponse in ("0", EOFError()):
            with self.subTest(reponse=reponse):
                self.assertIsNone(self.reprendre(reponse))
                self.assertEqual(self.effacements, [])
        self.assertEqual(self.archives(), [])

    def test_a_typo_is_said_and_asked_again(self):
        """« q » ne se lit ni comme un numéro, ni comme une lettre, ni
        comme un nom de la liste : une faute, comme un numéro qu'elle
        n'affiche pas ; la question revient."""
        self.assertIsNone(self.reprendre("q", "9", "0"))
        self.assertEqual(self.ecran.count(t("Invalid choice: ")), 2)
        self.assertEqual(self.archives(), [])

    def test_new_or_keep_the_zip_archive_the_log_once_confirmed(self):
        cas = (
            ("n", {}),
            ("r", {"migration_file": "./image_db/forged_resume.zip"}),
        )
        for nombre, (lettre, reste) in enumerate(cas, 1):
            with self.subTest(lettre=lettre):
                progression, change = self.reprendre(lettre, "y")
                self.assertTrue(change)
                self.assertEqual(
                    {k: v for k, v in progression.items() if v}, reste
                )
                self.assertEqual(len(self.archives()), nombre)
                self.assertEqual(self.effacements, ["archive_progression"])
        self.assertIn(
            f"[n] {t('New migration, erase everything')}\n", self.ecran
        )
        self.assertEqual(
            self.invites[-1],
            f"💬 {t('Keep the zip only, ask every question again')}."
            f" {t('Confirm? (y/N): ')}",
        )

    def test_a_step_by_its_number_or_its_name_rewinds_once_confirmed(self):
        """L'étape 0 par le numéro que la liste affiche, [1], ou par son
        nom, puis oui : la progression rembobinée, sans archive. La
        confirmation nomme l'étape."""
        attendu = self.attendu(TodoUpgrade.rewind_progression, 0)
        for reponse in ("1", f"{t('Step')} 0"):
            with self.subTest(reponse=reponse):
                self.assertEqual(self.reprendre(reponse, "y"), (attendu, True))
                self.assertEqual(self.effacements, ["rewind_progression"])
        self.assertNotIn("state_0_install_odoo", attendu)
        self.assertIn(f"[1] {t('Step')} 0 · ", self.ecran)
        self.assertTrue(
            self.invites[-1].startswith(
                f"💬 {t('Step')} 0 : {t('Replay from that step')}"
            )
        )
        self.assertEqual(self.archives(), [])

    def test_a_bump_by_its_number_or_its_name_rewinds_once_confirmed(self):
        attendu = self.attendu(TodoUpgrade.rewind_version_bump, 0)
        self.assertEqual(attendu["state_4_switch_odoo_lst"], [False, False])
        for reponse in ("6", f"{t('Step')} 4.15"):
            with self.subTest(reponse=reponse):
                self.assertEqual(self.reprendre(reponse, "o"), (attendu, True))
                self.assertEqual(self.effacements, ["rewind_version_bump"])
        self.assertIn(f"[6] {t('Step')} 4.15 · ", self.ecran)
        self.assertEqual(self.archives(), [])

    def test_an_erasing_answer_not_confirmed_changes_nothing(self):
        """n, r, une étape ou un palier, puis une réponse vide, une faute,
        « n » ou Ctrl+D à la confirmation : rien d'archivé ni de rembobiné,
        et la question revient ; [0] quitte ensuite."""
        for efface in ("n", "r", "1", f"{t('Step')} 4.15"):
            for refus in ("", "x", "n", EOFError()):
                with self.subTest(efface=efface, refus=refus):
                    self.assertIsNone(self.reprendre(efface, refus, "0"))
                    self.assertEqual(self.effacements, [])
        self.assertEqual(self.archives(), [])

    def test_an_answer_no_screen_returns_changes_nothing(self):
        """« q » de l'écran Textual, ou une chaîne qu'aucun écran ne rend
        (un palier hors de la migration) : None, rien d'archivé."""
        upgrade = TodoUpgrade(todo=None)
        ctx = upgrade.resume_context(dict(self.PROGRESSION))
        for reponse in ("q", "4.17", "x"):
            with self.subTest(reponse=reponse):
                rendu = upgrade.apply_resume_answer(
                    dict(self.PROGRESSION), reponse, ctx
                )
                self.assertIsNone(rendu)
        self.assertEqual(self.archives(), [])


class TestLEtapeARejouer(Reprise):
    """« b » à une invite de la migration : l'étape à rejouer, puis la
    progression rembobinée et écrite dans le journal."""

    def rejouer(self, *reponses):
        upgrade = TodoUpgrade(todo=None)
        upgrade.dct_progression = dict(self.PROGRESSION)
        return self.repondre(upgrade.rewind_to_chosen_step, reponses)

    def test_a_step_by_its_number_or_its_name_is_written_once_confirmed(
        self,
    ):
        attendu = self.attendu(TodoUpgrade.rewind_progression, 0)
        for reponse in ("1", f"{t('Step')} 0"):
            with self.subTest(reponse=reponse):
                self.assertTrue(self.rejouer(reponse, "y"))
                self.assertEqual(self.effacements, ["rewind_progression"])
                with open(self.journal) as journal:
                    ecrit = json.load(journal)
                for date in ("date_create", "date_update"):
                    ecrit.pop(date)
                self.assertEqual(ecrit, attendu)
        self.assertIn(f"[1] {t('Step')} 0 · ", self.ecran)
        self.assertTrue(self.invites[-1].startswith(f"💬 {t('Step')} 0 : "))

    def test_a_step_not_confirmed_writes_nothing(self):
        """Une étape, puis une réponse vide, une faute, « n » ou Ctrl+D à
        la confirmation : rien de rembobiné ni d'écrit."""
        for refus in ("", "x", "n", EOFError()):
            with self.subTest(refus=refus):
                self.assertFalse(self.rejouer("1", refus))
                self.assertEqual(self.effacements, [])
        self.assertFalse(os.path.exists(self.journal))

    def test_back_an_empty_answer_or_ctrl_d_writes_nothing(self):
        for reponse in ("0", "", EOFError()):
            with self.subTest(reponse=reponse):
                self.assertFalse(self.rejouer(reponse))
                self.assertEqual(self.effacements, [])
        self.assertFalse(os.path.exists(self.journal))

    def test_a_typo_is_said_and_asked_again(self):
        self.assertFalse(self.rejouer("6", "x", "0"))
        self.assertEqual(self.ecran.count(t("Invalid choice: ")), 2)
        self.assertFalse(os.path.exists(self.journal))


if __name__ == "__main__":
    unittest.main()
