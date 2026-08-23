#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Résumé d'un journal d'installation : ce qui a échoué doit se voir.

Le détail des erreurs cherchait la sous-chaîne « error ». Or le journal de
l'installation qui a réellement échoué — erplibre-ubuntu-2604-gnome, APK tué
par le noyau — ne contient AUCUNE ligne « error » : 0 sur 8765, mesuré. Le
volet annonçait donc « aucune erreur détectée » sur une installation ratée,
et le tableau de bord comptait 0 erreur.

Ces tests fixent la règle inverse : une étape en échec, un « FAILURE » de
Gradle, une trace Python ou une mort par mémoire se voient, et le résumé les
présente AVANT les centaines de lignes du détail.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "script/todo"))
import qemu_install_monitor as m  # noqa: E402

# Journal réduit à sa forme réelle : les marqueurs de l'installation, puis
# l'échec tel que Gradle l'écrit. Aucune ligne ne contient « error ».
LOG_GRADLE_OOM = """\
== ERPLibre mobile, SDK Android (long) ==
   -> venv ERPLibre (tout ce qui suit en dépend)
   -> dépendances npm
   -> APK debug (gradle)
   ⚠ ÉCHEC : APK debug (gradle)
   aucun motif connu, dernières lignes :

     FAILURE: Build failed with an exception.

     * What went wrong:
     Gradle build daemon disappeared unexpectedly (it may have been killed)
   ⚠ aucun APK produit
__ERPLIBRE_EXIT__ 1
"""


def _log(text):
    fh = tempfile.NamedTemporaryFile(
        "w", suffix=".log", delete=False, encoding="utf-8"
    )
    fh.write(text)
    fh.close()
    return fh.name


class TestFailedStepsAreSeen(unittest.TestCase):
    def setUp(self):
        self.path = _log(LOG_GRADLE_OOM)

    def tearDown(self):
        Path(self.path).unlink(missing_ok=True)

    def test_the_reference_log_has_no_line_saying_error(self):
        """La prémisse de tout le reste : la détection par sous-chaîne ne
        pouvait RIEN trouver ici."""
        self.assertNotIn("error", LOG_GRADLE_OOM.lower())

    def test_the_failed_step_is_named(self):
        got = m.scan_log_summary(self.path)
        self.assertEqual(
            [s["label"] for s in got["steps"]], ["APK debug (gradle)"]
        )

    def test_the_step_carries_its_diagnostic(self):
        """L'échec nomme l'étape ; c'est le diagnostic qui porte la cause."""
        diag = "\n".join(m.scan_log_summary(self.path)["steps"][0]["diag"])
        self.assertIn("FAILURE: Build failed", diag)
        self.assertIn("daemon disappeared", diag)

    def test_the_exit_marker_is_not_a_diagnostic(self):
        diag = "\n".join(m.scan_log_summary(self.path)["steps"][0]["diag"])
        self.assertNotIn(m.EXIT_MARKER, diag)

    def test_the_diagnostic_stops_at_the_next_step(self):
        """Sinon le diagnostic avale la suite de l'installation et ne désigne
        plus rien."""
        text = LOG_GRADLE_OOM + "   -> étape suivante\n   bruit\n"
        path = _log(text)
        try:
            diag = "\n".join(m.scan_log_summary(path)["steps"][0]["diag"])
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertNotIn("bruit", diag)

    def test_hard_signals_are_listed(self):
        hard = " ".join(
            h["text"] for h in m.scan_log_summary(self.path)["hard"]
        )
        self.assertIn("FAILURE", hard)
        self.assertIn("disappeared unexpectedly", hard)

    def test_the_dashboard_no_longer_counts_zero_errors(self):
        """Le compte alimente le tableau de bord : « 0 erreur » sur une
        installation morte est un mensonge, pas une nuance."""
        nerr, _ = m.scan_log_errors(self.path)
        self.assertGreater(nerr, 0)

    def test_the_detail_pane_is_no_longer_empty(self):
        errs, _ = m.scan_log_error_lines(self.path)
        self.assertTrue(errs)
        self.assertTrue(any("ÉCHEC" in e or "FAILURE" in e for e in errs))


class TestOtherRealFailures(unittest.TestCase):
    """Chaque motif dur est là parce qu'il est apparu dans un vrai journal."""

    def _first_hard(self, line):
        path = _log(f"   -> étape\n{line}\n")
        try:
            return m.scan_log_summary(path)["hard"]
        finally:
            Path(path).unlink(missing_ok=True)

    def test_python_traceback(self):
        self.assertTrue(self._first_hard("Traceback (most recent call last):"))

    def test_git_fatal(self):
        self.assertTrue(self._first_hard("fatal: repository not found"))

    def test_apt_missing_package(self):
        self.assertTrue(
            self._first_hard("E: Unable to locate package python3.12-venv")
        )

    def test_kernel_oom(self):
        self.assertTrue(
            self._first_hard("Out of memory: Killed process 37603 (java)")
        )

    def test_missing_command(self):
        self.assertTrue(self._first_hard("bash: emulator: command not found"))

    def test_a_benign_probe_is_not_a_hard_signal(self):
        """« No such file or directory » sortait 5 fois sur 7 d'une sonde
        bénigne (« cat: .odoo-version ») : le bruit dilue un résumé dont tout
        l'intérêt est d'être court."""
        self.assertFalse(
            self._first_hard("cat: .odoo-version: No such file or directory")
        )


class TestGrouping(unittest.TestCase):
    def test_repeats_are_counted_not_repeated(self):
        """Un journal répète la même erreur des centaines de fois avec un
        chemin qui change : on veut « ×200 », pas 200 lignes."""
        lines = "\n".join(
            f"ERROR: cannot read /var/lib/x/file{i}.txt" for i in range(200)
        )
        path = _log(lines + "\n")
        try:
            groups = m.scan_log_summary(path)["groups"]
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["count"], 200)

    def test_the_most_frequent_comes_first(self):
        path = _log(
            "ERROR: rare thing\n"
            + "\n".join(f"ERROR: common {i}" for i in range(5))
            + "\n"
        )
        try:
            groups = m.scan_log_summary(path)["groups"]
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(groups[0]["count"], 5)

    def test_warnings_are_grouped_apart_from_errors(self):
        path = _log("WARNING: a\nERROR: b\n")
        try:
            kinds = {g["kind"] for g in m.scan_log_summary(path)["groups"]}
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(kinds, {"error", "warning"})


class TestQuietLogs(unittest.TestCase):
    def test_a_clean_log_stays_clean(self):
        """Le résumé ne doit pas inventer d'échec là où il n'y en a pas."""
        path = _log("== installation ==\n   -> étape\n   ✅ terminé\n")
        try:
            got = m.scan_log_summary(path)
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(got["steps"], [])
        self.assertEqual(got["hard"], [])
        self.assertEqual(got["groups"], [])

    def test_a_missing_log_is_not_a_crash(self):
        got = m.scan_log_summary("/nonexistent/erplibre.log")
        self.assertEqual(got["steps"], [])
        self.assertEqual(got["nerr"], 0)


if __name__ == "__main__":
    unittest.main()
