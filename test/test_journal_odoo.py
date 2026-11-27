#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""journal_odoo : quelles lignes d'un journal Odoo font échouer un
scénario, lesquelles ne sont que comptées.

Les listes d'ignore et le classement sont ceux de l'ancien lanceur
asyncio des scénarios, repris à l'identique : un journal qui faisait
échouer un scénario le fait toujours, et inversement.
"""

import unittest

from script.test import journal_odoo

# Un journal inventé : un échec d'Odoo, des messages connus et bénins,
# une ligne qui est à la fois erreur et avertissement, une casse variée.
JOURNAL = "\n".join(
    [
        "2031-02-03 04:05:06,789 4242 INFO base_fictive odoo.modules: chargé",
        "2031-02-03 04:05:07,001 4242 ERROR base_fictive odoo.registry:"
        " échec du chargement",
        "2031-02-03 04:05:07,002 4242 WARNING base_fictive odoo.fields:"
        " Field x and y have the same label: Nom",
        "2031-02-03 04:05:07,003 4242 WARNING base_fictive odoo.models:"
        " champ obsolète",
        'odoo.sql_db: bad query: ALTER TABLE "db_backup" DROP CONSTRAINT'
        ' "db_backup_db_backup_name_unique"',
        "module fetchmail_notify_error_to_sender introuvable",
        "Traceback: ValueError raised",
        "warning et error sur la même ligne",
        "odoo.addons.code_generator.extractor_module_file: Ignore next error"
        " about ALTER TABLE DROP CONSTRAINT.",
        "",
    ]
)


class TestClasserLignes(unittest.TestCase):
    def test_an_odoo_error_line_is_kept(self):
        erreurs, _ = journal_odoo.classer_lignes(JOURNAL)
        self.assertTrue(any("odoo.registry" in e for e in erreurs))

    def test_known_benign_errors_are_ignored(self):
        erreurs, _ = journal_odoo.classer_lignes(JOURNAL)
        for e in erreurs:
            self.assertNotIn("db_backup_db_backup_name_unique", e)
            self.assertNotIn("fetchmail_notify_error_to_sender", e)
            self.assertNotIn("Ignore next error", e)

    def test_the_match_ignores_case(self):
        erreurs, _ = journal_odoo.classer_lignes(
            "Traceback: ValueError raised"
        )
        self.assertEqual(erreurs, ["Traceback: ValueError raised"])

    def test_warnings_are_counted_apart(self):
        erreurs, avertissements = journal_odoo.classer_lignes(JOURNAL)
        self.assertTrue(any("champ obsolète" in a for a in avertissements))
        self.assertFalse(any("same label" in a for a in avertissements))
        self.assertFalse(any("champ obsolète" in e for e in erreurs))

    def test_a_line_can_be_both(self):
        erreurs, avertissements = journal_odoo.classer_lignes(
            "warning et error sur la même ligne"
        )
        self.assertEqual(len(erreurs), 1)
        self.assertEqual(len(avertissements), 1)

    def test_an_empty_text_has_nothing(self):
        self.assertEqual(journal_odoo.classer_lignes(""), ([], []))


class TestExtractResult(unittest.TestCase):
    def test_a_non_zero_code_names_the_test(self):
        erreurs, avertissements = [], []
        journal_odoo.extract_result(
            ("ligne a\nligne b", 2), "scenario_fictif", erreurs, avertissements
        )
        self.assertEqual(
            erreurs, ["Return status error for test scenario_fictif"]
        )

    def test_a_one_line_log_is_quoted(self):
        erreurs = []
        journal_odoo.extract_result(("sortie", 1), "s", erreurs, [])
        self.assertEqual(erreurs, ["Return status error for test s : sortie"])


class TestMoniteurInstallation(unittest.TestCase):
    def test_the_install_monitor_uses_the_shared_lists(self):
        from script.todo import qemu_install_monitor as moniteur

        self.assertIs(moniteur._LST_IGNORE_ERROR, journal_odoo.IGNORE_ERREUR)
        for chaine in journal_odoo.IGNORE_AVERTISSEMENT:
            self.assertIn(chaine, moniteur._LST_IGNORE_WARNING)
        # Le moniteur garde son ajout propre aux connexions ssh.
        self.assertIn(
            "Warning: Permanently added", moniteur._LST_IGNORE_WARNING
        )


if __name__ == "__main__":
    unittest.main()
