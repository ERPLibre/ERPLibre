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
            # De la prose, pas de la ponctuation d'invite ni un nom de
            # commande : au moins deux mots réellement alphabétiques.
            # « ' (y/Y) : » n'en a aucun, « make repo_show_status » un seul.
            words = [w for w in text.split() if w.isalpha() and len(w) > 2]
            if len(words) < 2:
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


class TestTheDatabaseMigrationSpeaksFrench(unittest.TestCase):
    """Le parcours que l'on suit pendant des heures, en une seule langue.

    `execute_odoo_upgrade` est la migration de base : c'est ce qui défile à
    l'écran de l'étape 0 à l'étape 6. Elle alternait les deux langues.
    """

    def driver(self):
        path = os.path.join(REPO, "script", "todo", "todo_upgrade.py")
        with open(path) as handle:
            return ast.parse(handle.read()), path

    def test_no_english_sentence_is_displayed_raw(self):
        tree, path = self.driver()
        target = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "execute_odoo_upgrade"
        ]
        self.assertEqual(len(target), 1, "fonction introuvable")
        left = [
            text
            for _, text in displayed_strings(path)
            if target[0].lineno <= _ <= target[0].end_lineno
            # Ponctuation d'invite : « (y/Y) : » n'est pas une phrase.
            and len(text.split()) > 2
        ]
        self.assertEqual(left, [])

    def test_every_t_key_has_a_translation(self):
        # `t()` rend sa CLÉ quand la traduction manque : une clé oubliée
        # s'affiche en anglais sans que rien ne signale l'oubli.
        from script.todo.todo_i18n import TRANSLATIONS

        tree, _ = self.driver()
        missing = sorted(
            {
                arg.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "t"
                for arg in node.args
                if isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and arg.value not in TRANSLATIONS
            }
        )
        self.assertEqual(missing, [])

    def test_the_step_headers_translate_only_their_label(self):
        # L'en-tête part AUSSI dans le journal, que l'écran de reprise
        # relit : traduire ce qui est écrit rendrait un journal illisible
        # pour l'autre langue.
        import io
        from contextlib import redirect_stdout

        from script.todo import todo_i18n
        from script.todo.todo_upgrade import TodoUpgrade

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "fr"
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        out = io.StringIO()
        with redirect_stdout(out):
            upgrade.print_step("2 - Succeed update all addons")
        printed = out.getvalue()
        self.assertIn("🔷 2 - ", printed)
        self.assertNotIn("Succeed", printed)


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
        #
        # On lit le RETURN, pas une ligne recopiée : l'outil a gagné une
        # seconde famille de trouvailles (les copies qui rendront 500),
        # et figer le texte faisait échouer le test sur un ajout juste.
        # Ce qui doit rester vrai, c'est que CHAQUE famille pèse sur le
        # code de sortie.
        import ast

        path = os.path.join(
            REPO, "script", "odoo", "migration", "check_cow_views.py"
        )
        with open(path) as handle:
            arbre = ast.parse(handle.read())
        retours = [
            ast.dump(noeud)
            for fonction in ast.walk(arbre)
            if isinstance(fonction, ast.FunctionDef)
            and fonction.name == "main"
            for noeud in ast.walk(fonction)
            if isinstance(noeud, ast.Return)
        ]
        decision = [r for r in retours if "lst_at_risk" in r]
        self.assertEqual(1, len(decision), retours)
        self.assertIn("lst_no_render", decision[0])


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
