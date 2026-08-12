#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le journal de migration doit survivre à la migration suivante.

Il ne vit qu'à un seul endroit, et repartir de zéro écrit par-dessus. Ce qu'on
perdait — quels paliers étaient passés, quels modules manquaient — est
précisément ce qu'on cherche APRÈS avoir dû recommencer.

Ces tests portent sur deux choses distinctes : que la copie contienne bien ce
qu'elle doit contenir, et qu'elle parte au bon moment — ni sur une reprise
partielle, qui ne perd rien, ni sur un journal qui n'a rien à dire.
"""

import glob
import json
import os
import tempfile
import unittest

from script.todo.todo_upgrade import TodoUpgrade


def progression(**override):
    """Un journal ayant réellement avancé."""
    data = {
        "date_create": "2026-08-11 12:05:08",
        "date_update": "2026-08-12 01:13:23",
        "migration_file": "./image_db/technolibre_2026-08-12_02h36m38s.zip",
        "config_database_name": "technolibre_migration_01_neutralize",
        "state_0_install_odoo": True,
        "state_1_restore_database": True,
        "state_4_switch_odoo_lst": [True, False, False],
    }
    data.update(override)
    return data


class ArchiveCase(unittest.TestCase):
    def setUp(self):
        # Chaque test dans un arbre neuf : l'archive s'écrit sous un chemin
        # relatif, donc le répertoire courant EST le contexte.
        self.previous = os.getcwd()
        self.addCleanup(os.chdir, self.previous)
        os.chdir(tempfile.mkdtemp())

    def archives(self):
        return sorted(
            glob.glob("private/odoo/migration/*/migration_log/*.json")
        )


class TestWhatIsKept(ArchiveCase):
    def test_the_whole_log_is_copied_untouched(self):
        old = progression()
        path = TodoUpgrade.archive_progression(old, "restart_from_zero")
        saved = json.load(open(path))
        for key, value in old.items():
            self.assertEqual(saved[key], value, key)

    def test_the_copy_says_when_and_from_which_database(self):
        # La demande, mot pour mot : une date de la copie et le nom de la base
        # d'origine.
        path = TodoUpgrade.archive_progression(
            progression(), "restart_from_zero"
        )
        saved = json.load(open(path))
        self.assertEqual(
            saved["archived_database"], "technolibre_migration_01_neutralize"
        )
        self.assertTrue(saved["archived_at"].startswith("20"))
        self.assertEqual(saved["archived_reason"], "restart_from_zero")

    def test_the_file_name_carries_both_too(self):
        # Pour qu'un fichier déplacé hors de son dossier se décrive encore.
        path = TodoUpgrade.archive_progression(progression(), "x")
        name = os.path.basename(path)
        self.assertTrue(
            name.startswith("technolibre_migration_01_neutralize_")
        )
        self.assertRegex(name, r"_\d{4}-\d{2}-\d{2}_\d{2}h\d{2}m\d{2}s\.json$")

    def test_it_lands_under_private_not_in_the_venv(self):
        # Une réinstallation efface .venv.erplibre/, donc y garder l'historique
        # reviendrait à le perdre au pire moment.
        path = TodoUpgrade.archive_progression(progression(), "x")
        self.assertTrue(path.startswith(os.path.join("private", "odoo")))
        self.assertNotIn(".venv", path)

    def test_the_database_name_falls_back_to_the_backup_name(self):
        old = progression()
        del old["config_database_name"]
        path = TodoUpgrade.archive_progression(old, "x")
        self.assertIn("technolibre_2026-08-12_02h36m38s", path)

    def test_two_restarts_in_the_same_second_do_not_overwrite_each_other(self):
        # L'horodatage est à la seconde : deux copies rapprochées portent le
        # même nom. Écraser la première annulerait la perte qu'on évite — et
        # un test qui saute ce cas ne vérifie rien.
        first = TodoUpgrade.archive_progression(progression(), "x")
        second = TodoUpgrade.archive_progression(
            progression(date_update="2026-08-12 02:00:00"), "y"
        )
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.archives()), 2)
        self.assertEqual(
            json.load(open(first))["date_update"], "2026-08-12 01:13:23"
        )
        self.assertEqual(
            json.load(open(second))["date_update"], "2026-08-12 02:00:00"
        )


class TestWhenNothingIsKept(ArchiveCase):
    def test_an_empty_log_is_not_archived(self):
        self.assertIsNone(TodoUpgrade.archive_progression({}, "x"))
        self.assertEqual(self.archives(), [])

    def test_a_log_without_any_state_is_not_archived(self):
        # Un journal qui n'a rien enregistré n'apprend rien à personne ;
        # l'archiver ne ferait qu'accumuler des fichiers vides.
        self.assertIsNone(
            TodoUpgrade.archive_progression({"migration_file": "a.zip"}, "x")
        )
        self.assertEqual(self.archives(), [])


class TestWhenItTriggers(ArchiveCase):
    """Seules les réponses qui repartent de zéro archivent."""

    def answer(self, letter):
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        result = TodoUpgrade.apply_resume_answer(
            upgrade, progression(), letter, {"versions": []}
        )
        return result, self.archives()

    def test_restart_from_zero_archives(self):
        result, archives = self.answer("n")
        self.assertEqual(result, ({}, True))
        self.assertEqual(len(archives), 1)

    def test_restart_with_the_same_backup_archives(self):
        # « r » garde le zip mais jette tous les états : la perte est la même.
        result, archives = self.answer("r")
        self.assertTrue(result[1])
        self.assertNotIn("state_0_install_odoo", result[0])
        self.assertEqual(len(archives), 1)

    def test_continuing_archives_nothing(self):
        result, archives = self.answer("c")
        self.assertEqual(archives, [])
        self.assertIn("state_0_install_odoo", result[0])

    def test_rewinding_to_a_step_archives_nothing(self):
        # Une reprise partielle garde le journal : rien n'est perdu, donc rien
        # n'est à sauver.
        _, archives = self.answer("0")
        self.assertEqual(archives, [])


if __name__ == "__main__":
    unittest.main()
