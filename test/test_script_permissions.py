#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Un script avec shebang doit être exécutable — et pas inscriptible en groupe.

Le bit d'exécution n'accorde rien : qui peut lire le fichier peut déjà faire
« python3 fichier ». Ce qui compte est la PAIRE : un fichier à la fois
exécuté par d'autres et modifiable par le groupe laisse un membre du groupe
changer ce que les autres lancent. L'umask 0002 du poste crée exactement
cette paire dès qu'on ajoute +x sans y penser (664 -> 775).

Git ne stocke que le bit d'exécution, jamais 664 contre 644 : le mode complet
ne se vérifie donc que sur le disque, ici.
"""

import glob
import os
import stat
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATTERNS = (
    "script/analyse/*.py",
    "script/analyse/*/*.py",
    "script/odoo/migration/*.py",
)


def scripts():
    """(chemin, a un shebang) pour chaque script des dossiers visés."""
    found = []
    for pattern in PATTERNS:
        for path in sorted(glob.glob(os.path.join(REPO, pattern))):
            with open(path, "rb") as handle:
                found.append((path, handle.read(2) == b"#!"))
    return found


class TestExecutableBit(unittest.TestCase):
    def test_the_inventory_is_not_empty(self):
        # Un test qui ne trouve rien passe toujours.
        self.assertGreater(len(scripts()), 10)

    def test_every_shebang_script_is_executable(self):
        for path, has_shebang in scripts():
            if not has_shebang:
                continue
            with self.subTest(script=os.path.relpath(path, REPO)):
                self.assertTrue(os.access(path, os.X_OK))

    def test_none_is_writable_by_group_or_others(self):
        # LE point qui compte : exécuté par d'autres ET modifiable par eux.
        for path, _ in scripts():
            mode = stat.S_IMODE(os.stat(path).st_mode)
            with self.subTest(script=os.path.relpath(path, REPO)):
                self.assertFalse(
                    mode & (stat.S_IWGRP | stat.S_IWOTH), oct(mode)
                )

    def test_none_is_setuid_or_setgid(self):
        for path, _ in scripts():
            mode = os.stat(path).st_mode
            with self.subTest(script=os.path.relpath(path, REPO)):
                self.assertFalse(mode & (stat.S_ISUID | stat.S_ISGID))


class TestTheTuiSaysWhyItRefuses(unittest.TestCase):
    """Rendre un script lançable ouvre un chemin sans le venv.

    Le shebang est « #!/usr/bin/env python3 » : lancé directement depuis un
    shell où le venv n'est pas actif, c'est le python du système qui répond,
    et Textual n'y est pas. La TUI retombait alors sur le rapport texte sans
    rien dire — le même défaut muet que le tube de sortie.
    """

    def run_tui(self):
        import sys

        sys.path.insert(0, os.path.join(REPO, "script", "odoo", "migration"))
        self.addCleanup(sys.path.remove, sys.path[0])
        from cow_drift_tui import run_tui

        return run_tui

    def finding(self):
        return {
            "id": 1,
            "key": "k",
            "website_id": 1,
            "reason": "r",
            "module_id": 2,
            "module_arch": "a",
            "copy_arch": "b",
            "decl_current": None,
            "decl_target": None,
            "current_version": "odoo12.0",
            "target_version": "odoo13.0",
        }

    def test_a_pipe_is_explained_not_swallowed(self):
        import io
        from contextlib import redirect_stdout

        out = io.StringIO()
        with redirect_stdout(out):
            result = self.run_tui()([self.finding()])
        self.assertFalse(result)
        self.assertTrue(out.getvalue().strip(), "refus muet")

    def test_nothing_to_show_stays_silent(self):
        # Une liste vide n'est pas un refus : il n'y a rien à annoncer.
        import io
        from contextlib import redirect_stdout

        out = io.StringIO()
        with redirect_stdout(out):
            self.assertFalse(self.run_tui()([]))
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
