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
from script.todo.todo_upgrade import TodoUpgrade


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
        test en le disant. L'écran imprimé est dans `self.ecran`."""
        upgrade = TodoUpgrade(todo=None)
        gestes = []
        for nom in (
            "switch_odoo",
            "install_OCA_odoo_module_migrator",
            "internal_module_upgrade",
            "todo_upgrade_execute",
            "check_addons_exist",
        ):
            setattr(
                upgrade,
                nom,
                lambda *a, _nom=nom, **k: gestes.append((_nom, a)),
            )
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
            upgrade.execute_module_upgrade()
        self.ecran = ecran.getvalue()
        return gestes


class TestLeNavigateurQuitte(Banc):
    def test_leaving_the_browser_migrates_nothing(self):
        """Le navigateur de répertoires quitté sans choix : la migration
        revient sans erreur, sans basculer de version ni rien migrer."""
        gestes = self.migrer([""])
        self.assertEqual(len(NavigateurQuiRenonce.ouverts), 1)
        self.assertEqual(gestes, [])


if __name__ == "__main__":
    unittest.main()
