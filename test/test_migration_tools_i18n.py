#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les outils de migration parlaient anglais sur un système en français.

Ils tournent en sous-processus depuis le pilote, et n'avaient aucun i18n : la
migration alternait donc les deux langues d'une ligne à l'autre.

Deux choses à tenir, et la seconde est un piège : le pilote CHERCHAIT des
phrases anglaises dans leur sortie pour décider s'il devait poser une question
(« will break when moving to », « No website COW view to neutralize »).
Traduire ces phrases l'aurait rendu muet — sans erreur, sans trace. Le lien
passe désormais par le code de sortie, que la langue ne touche pas.
"""

import ast
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Les outils COW, ceux que la migration lance et dont la sortie est lue par un
# humain au milieu d'une migration de plusieurs heures.
TOOLS = (
    "check_cow_views.py",
    "cow_drift.py",
    "neutralize_cow_views.py",
    "reset_stale_cow_views.py",
    "snapshot_cow_views.py",
)

# Ce qui n'est pas de la prose : du SQL, des chemins, des drapeaux.
NOT_PROSE = ("SELECT ", "UPDATE ", "./script/", "--", "id=", "<!--")


def displayed_strings(path):
    """Chaînes affichées sans passer par t(), et qui sont de la prose."""
    with open(path) as handle:
        tree = ast.parse(handle.read())
    translated, keys = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "t":
            for arg in node.args:
                translated.add(id(arg))
        if isinstance(node, ast.Subscript) and isinstance(
            node.slice, ast.Constant
        ):
            keys.add(id(node.slice))
    found = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") in ("print", "input")
        ):
            continue
        for sub in ast.walk(node):
            if not (
                isinstance(sub, ast.Constant) and isinstance(sub.value, str)
            ):
                continue
            if id(sub) in translated or id(sub) in keys:
                continue
            text = sub.value.strip()
            if len(text.split()) < 2 or not any(c.isalpha() for c in text):
                continue
            if any(mark in text for mark in NOT_PROSE):
                continue
            found.append((sub.lineno, text))
    return found


class TestNoEnglishLeftInTheTools(unittest.TestCase):
    def test_every_displayed_sentence_goes_through_t(self):
        for name in TOOLS:
            path = os.path.join(REPO, "script", "odoo", "migration", name)
            with self.subTest(tool=name):
                self.assertEqual(displayed_strings(path), [], name)

    def test_the_detector_is_not_blind(self):
        # Un test de couverture qui ne voit rien passe toujours. On lui donne
        # une phrase non traduite, il doit la trouver.
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False
        ) as handle:
            handle.write('print("this sentence is not translated")\n')
            handle.write("print(f\"{t('this one is')}\")\n")
        self.addCleanup(os.unlink, handle.name)
        found = displayed_strings(handle.name)
        self.assertEqual(
            [text for _, text in found], ["this sentence is not translated"]
        )


class TestTheDriverNoLongerReadsEnglish(unittest.TestCase):
    """Le lien pilote/outil doit survivre à une traduction."""

    def source(self):
        path = os.path.join(REPO, "script", "todo", "todo_upgrade.py")
        with open(path) as handle:
            return handle.read()

    def test_no_output_text_matching_is_left(self):
        # LE piège : `if "will break when moving to" in "\n".join(output)`.
        # Muet, sans erreur, dès que l'outil parle une autre langue.
        self.assertNotIn('in "\\n".join(output', self.source())

    def test_the_cow_decisions_use_the_exit_code(self):
        source = self.source()
        self.assertIn("if status == 1:", source)
        self.assertIn("if status == 0:", source)


class TestTheExitCodesTheDriverRelieson(unittest.TestCase):
    """0 = rien, 1 = des copies concernées, 2 = l'outil a échoué."""

    def run_tool(self, name, args):
        return subprocess.run(
            [sys.executable, f"./script/odoo/migration/{name}", *args],
            cwd=REPO,
            capture_output=True,
            text=True,
        )

    def test_a_missing_target_version_is_a_tool_failure(self):
        # Pas 1 : 1 veut dire « des copies casseront », et confondre les deux
        # ferait poser une question sur un résultat qui n'existe pas.
        for name in ("check_cow_views.py", "neutralize_cow_views.py"):
            with self.subTest(tool=name):
                done = self.run_tool(name, ["-d", "x", "-t", "odoo99.0"])
                self.assertEqual(done.returncode, 2, done.stdout)

    def test_the_failure_message_is_translated(self):
        done = self.run_tool("check_cow_views.py", ["-d", "x", "-t", "zz9.0"])
        self.assertNotIn("not found", done.stdout)

    def test_check_cow_views_reports_findings_with_1(self):
        # Le chemin qui compte demande une base ; on vérifie la décision
        # elle-même, à la source.
        path = os.path.join(
            REPO, "script", "odoo", "migration", "check_cow_views.py"
        )
        with open(path) as handle:
            self.assertIn("return 1 if lst_at_risk else 0", handle.read())


class TestAllToolsKeepWorkingStandalone(unittest.TestCase):
    def test_they_import_without_the_repo_on_the_path(self):
        # L'import d'i18n remonte trois répertoires ; une faute s'y voit
        # seulement à l'exécution, et alors la migration est déjà lancée.
        for name in TOOLS:
            with self.subTest(tool=name):
                done = subprocess.run(
                    [sys.executable, f"./script/odoo/migration/{name}", "-h"],
                    cwd=REPO,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
