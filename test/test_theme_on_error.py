#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Proposer de retirer un thème SEULEMENT quand il est en cause.

La propriété qui porte tout : deux conditions, jamais une seule. Un
thème doit être installé — sinon il n'y a rien à retirer — ET son nom
doit figurer dans ce que la commande vient d'écrire. Offrir la
désinstallation à chaque échec reviendrait à proposer de casser le
design du site pour une panne qui n'a rien à voir.

La question était déjà posée à l'étape 1, une fois, et un drapeau
l'empêchait de revenir. Or un thème devient incompatible à un PALIER
précis, des heures plus tard : la poser au départ ne pouvait pas suffire.
"""

import io
import os
import sys
import tempfile
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.todo import todo_i18n  # noqa: E402
from script.todo.todo_upgrade import TodoUpgrade  # noqa: E402


class TestTheDetection(unittest.TestCase):
    def setUp(self):
        self.obj = TodoUpgrade.__new__(TodoUpgrade)
        self.dossier = tempfile.mkdtemp()
        self.obj.log_dir = lambda: self.dossier
        self.obj.current_step = "4.5.J - Migrate database"
        self.obj.step_slug = staticmethod(lambda msg: "etape")
        self.obj.installed_theme = lambda base: ["theme_buzzy"]

    def journal(self, texte):
        with io.open(
            os.path.join(self.dossier, "etape.log"), "w", encoding="utf-8"
        ) as handle:
            handle.write(texte)

    def test_a_theme_named_by_the_error_is_blamed(self):
        self.journal(
            "ERROR ... /addons/odoo_design-themes/theme_buzzy/data/x.xml"
        )
        self.assertEqual(
            self.obj.theme_blamed_by_the_error("db"), ["theme_buzzy"]
        )

    def test_an_error_that_never_mentions_it_blames_nothing(self):
        # C'est LA protection : une erreur de compte ne doit pas faire
        # proposer d'effacer le design du site.
        self.journal("ERROR relation discuss_channel does not exist")
        self.assertEqual(self.obj.theme_blamed_by_the_error("db"), [])

    def test_no_theme_installed_blames_nothing(self):
        self.obj.installed_theme = lambda base: []
        self.journal("theme_buzzy partout dans le journal")
        self.assertEqual(self.obj.theme_blamed_by_the_error("db"), [])

    def test_no_theme_installed_never_even_reads_the_log(self):
        # Le garde n'est pas décoratif : sans lui on ouvrirait et lirait
        # 64 ko à CHAQUE erreur d'une migration, pour une liste vide.
        lectures = []
        self.obj.installed_theme = lambda base: []
        self.obj.step_log_tail = lambda *a, **k: lectures.append(1) or ""
        self.obj.theme_blamed_by_the_error("db")
        self.assertEqual(lectures, [])

    def test_no_log_blames_nothing(self):
        # Sans journal on ne SAIT pas : accuser au hasard serait pire
        # que se taire.
        self.assertEqual(self.obj.theme_blamed_by_the_error("db"), [])

    def test_no_database_blames_nothing(self):
        self.journal("theme_buzzy")
        self.assertEqual(self.obj.theme_blamed_by_the_error(""), [])

    def test_only_the_themes_actually_named_are_returned(self):
        self.obj.installed_theme = lambda base: ["theme_buzzy", "theme_zap"]
        self.journal("erreur dans theme_zap/data/ir_asset.xml")
        self.assertEqual(
            self.obj.theme_blamed_by_the_error("db"), ["theme_zap"]
        )


class TestReadingTheTail(unittest.TestCase):
    def setUp(self):
        self.obj = TodoUpgrade.__new__(TodoUpgrade)
        self.dossier = tempfile.mkdtemp()
        self.obj.log_dir = lambda: self.dossier
        self.obj.current_step = "etape"
        self.obj.step_slug = staticmethod(lambda msg: "etape")

    def test_it_reads_from_the_END(self):
        # Une mise à jour de modules écrit des dizaines de milliers de
        # lignes : charger tout le fichier pour en lire vingt coûterait
        # plus que l'erreur qu'on cherche.
        with io.open(
            os.path.join(self.dossier, "etape.log"), "w", encoding="utf-8"
        ) as handle:
            handle.write("debut\n" + ("x" * 100000) + "\nLA_FIN\n")
        fin = self.obj.step_log_tail(octets=1000)
        self.assertIn("LA_FIN", fin)
        self.assertNotIn("debut", fin)
        self.assertLessEqual(len(fin), 1100)

    def test_a_missing_log_is_empty_not_a_crash(self):
        self.assertEqual(self.obj.step_log_tail(), "")

    def test_no_step_is_empty(self):
        self.obj.current_step = ""
        self.assertEqual(self.obj.step_log_tail(), "")

    def test_broken_bytes_do_not_stop_it(self):
        # Un journal de migration mêle les encodages : refuser de le lire
        # ferait perdre la détection au moment où elle sert.
        with open(os.path.join(self.dossier, "etape.log"), "wb") as handle:
            handle.write(b"avant \xff\xfe theme_buzzy apres")
        self.assertIn("theme_buzzy", self.obj.step_log_tail())


class TestTheMenu(unittest.TestCase):
    RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

    def source(self):
        with io.open(
            os.path.join(self.RACINE, "script", "todo", "todo_upgrade.py"),
            encoding="utf-8",
        ) as handle:
            src = handle.read()
        debut = src.index("def _prompt_on_error")
        fin = src.index("def prompt_fix_view_type")
        return src[debut:fin]

    def test_the_entry_is_conditional(self):
        # Affichée sans condition, elle proposerait de retirer le thème
        # à chaque erreur, quelle qu'elle soit.
        bloc = self.source()
        self.assertIn("if themes:", bloc)
        self.assertIn('f"[6] ', bloc)

    def test_the_branch_requires_a_blamed_theme(self):
        bloc = self.source()
        self.assertIn('if wait_status == "6" and themes:', bloc)

    def test_the_detection_runs_once_outside_the_loop(self):
        # La boucle peut tourner huit fois ; la détection lit un journal
        # et interroge la base.
        bloc = self.source()
        self.assertEqual(bloc.count("theme_blamed_by_the_error"), 1)
        self.assertLess(
            bloc.index("theme_blamed_by_the_error"), bloc.index("while True:")
        )

    def test_uninstalling_asks_for_a_retry(self):
        bloc = self.source()
        debut = bloc.index('if wait_status == "6"')
        fin = bloc.index('if wait_status == "5"')
        morceau = bloc[debut:fin]
        self.assertIn('wait_status = "1"', morceau)
        self.assertIn("repare = True", morceau)

    def test_it_goes_through_the_real_terminal(self):
        # `uninstall_addons_theme.sh` finit par poser une question ; un
        # tube la rendrait invisible et l'on répondrait à l'aveugle.
        bloc = self.source()
        debut = bloc.index('if wait_status == "6"')
        fin = bloc.index('if wait_status == "5"')
        self.assertIn("run_on_terminal", bloc[debut:fin])

    def test_the_label_is_translated(self):
        self.assertIn(
            "Uninstall the theme(s) the error names", todo_i18n.TRANSLATIONS
        )


if __name__ == "__main__":
    unittest.main()
