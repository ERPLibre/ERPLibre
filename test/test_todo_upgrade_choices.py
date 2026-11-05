#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les choix d'Upgrade Module, sous des doubles.

`execute_module_upgrade` choisit ce qu'il migre, puis bascule le checkout
sur une version d'Odoo, clone le migrateur et migre le code. Ici, rien de
cela ne part : `switch_odoo`, `install_OCA_odoo_module_migrator`,
`internal_module_upgrade` et `todo_upgrade_execute` sont des doubles qui
notent leur appel, le navigateur de fichiers un double qui ne choisit
rien, et le journal de migration un fichier d'un répertoire jetable.
"""

import builtins
import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

from script.todo import todo_upgrade
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

    def migrer(self, reponses):
        """Lance execute_module_upgrade ; rend les gestes notés, dans
        l'ordre. Une réponse qui est une exception est levée (EOFError,
        Ctrl+D) ; une question de plus que de réponses fait échouer le
        test en le disant. Le premier `switch_odoo` arrête la migration
        après l'avoir noté (`Arret`), et `check_addons_exist` trouve le
        module demandé. L'écran imprimé est dans `self.ecran`."""
        upgrade = TodoUpgrade(todo=None)
        gestes = []

        def noter(nom):
            def double(*args, **kwargs):
                gestes.append((nom, args))
                if nom == "switch_odoo":
                    raise Arret
                if nom == "check_addons_exist":
                    return [], [], [["forged_module", "/forged"]], []

            return double

        for nom in (
            "switch_odoo",
            "install_OCA_odoo_module_migrator",
            "internal_module_upgrade",
            "todo_upgrade_execute",
            "check_addons_exist",
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
                todo_upgrade.todo_file_browser,
                "FileBrowser",
                NavigateurQuiRenonce,
            ),
            contextlib.redirect_stdout(ecran),
        ):
            try:
                upgrade.execute_module_upgrade()
            except Arret:
                pass
        self.ecran = ecran.getvalue()
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
        )
        for avant in avants:
            vides = ("",) if len(avant) > 1 else ()
            for retour in ("0", EOFError(), *vides):
                with self.subTest(avant=avant, retour=retour):
                    gestes = self.migrer([*avant, retour])
                    self.assertEqual(gestes, [])

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
        """« m » et « r » ne se lisent plus : un numéro, ou Entrée pour le
        navigateur, le défaut marqué."""
        gestes = self.migrer(["m", "r", "0"])
        self.assertEqual(gestes, [])
        self.assertEqual(self.ecran.count(t("Invalid choice: ")), 2)
        self.assertIn(f"{t('Directory browser')} {t('(default)')}", self.ecran)


if __name__ == "__main__":
    unittest.main()
