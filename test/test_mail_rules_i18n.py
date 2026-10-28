#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import re
import unittest
from pathlib import Path

import script.todo.mail.rules as rules_pkg
from script.todo.mail.rules.guards import (
    ENGINE_REASONS,
    REASONS,
    SILENT_REASONS,
)
from script.todo.mail.rules.model import OUTCOMES, STATS_VARIABLES
from script.todo.mail.rules.report import REPORT_KEYS
from script.todo.todo_i18n import TRANSLATIONS

# Codes que le moteur journalise sans qu'ils figurent dans les listes de
# `guards` : un UID disparu du serveur, un rattrapage dépassé.
EXTRA_REASONS = {"gone", "catchup_overflow"}


class TestRulesKeysAreTranslated(unittest.TestCase):
    """Le même filet que pour `mail/*.py`, sur le sous-paquet `rules`.

    `t()` rend la clé elle-même quand elle manque : rien n'échoue, et
    l'écran affiche « mail_rules_reason_x » en toutes lettres.
    """

    def assert_declared(self, keys):
        missing = sorted(key for key in keys if key not in TRANSLATIONS)
        self.assertEqual(missing, [], f"clés non traduites : {missing}")

    def test_every_key_used_in_the_rules_package_is_declared(self):
        pattern = re.compile(r"""(?<![A-Za-z_])t\((["'])(mail_[a-z_]+)\1\)""")
        used = set()
        for path in Path(rules_pkg.__file__).parent.glob("*.py"):
            used |= {m.group(2) for m in pattern.finditer(path.read_text())}
        self.assertTrue(
            used, "aucune clé trouvée : le motif ne correspond plus"
        )
        self.assert_declared(used)

    def test_every_logged_reason_has_a_label(self):
        codes = (set(REASONS) - SILENT_REASONS) | set(ENGINE_REASONS)
        codes |= EXTRA_REASONS
        self.assert_declared({f"mail_rules_reason_{code}" for code in codes})

    def test_every_outcome_has_a_label(self):
        self.assert_declared({f"mail_rules_outcome_{o}" for o in OUTCOMES})

    def test_every_report_label_exists_in_both_languages(self):
        keys = set(REPORT_KEYS)
        keys |= {f"mail_stats_var_{name}" for name in STATS_VARIABLES}
        keys |= {"mail_stats_default_body"}
        self.assert_declared(keys)
        for key in sorted(keys):
            with self.subTest(key=key):
                entry = TRANSLATIONS[key]
                self.assertTrue(entry.get("fr"))
                self.assertTrue(entry.get("en"))

    def test_labels_exist_in_both_languages(self):
        codes = (set(REASONS) - SILENT_REASONS) | set(ENGINE_REASONS)
        keys = {f"mail_rules_reason_{c}" for c in codes | EXTRA_REASONS}
        keys |= {f"mail_rules_outcome_{o}" for o in OUTCOMES}
        for key in sorted(keys):
            with self.subTest(key=key):
                entry = TRANSLATIONS[key]
                self.assertTrue(entry.get("fr"))
                self.assertTrue(entry.get("en"))


if __name__ == "__main__":
    unittest.main()
