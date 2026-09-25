#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La sonde de version d'install.sh : lire la version en exécutant du code.

« python -V » répond avant le chargement de la bibliothèque standard. Un venv
dont l'interpréteur ne trouve pas celle-ci — un checkout monté depuis une
autre machine — rend donc sa version, passe pour sain, et meurt au lancement
de TODO avec son pavé d'initialisation. La sonde doit le déclarer muet.
"""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

# Répond à -V comme un vrai interpréteur, échoue sur tout le reste : c'est la
# conduite d'un python qui ne trouve pas sa bibliothèque standard.
PYTHON_MORT = """#!/bin/sh
if [ "$1" = "-V" ]; then echo "Python 3.12.10"; exit 0; fi
echo "Fatal Python error: init_fs_encoding" >&2
exit 1
"""


def el_mineure(executable):
    """Rend la sortie de la fonction el_mineure d'install.sh sur l'exécutable."""
    script = (
        "source <(sed -n '/^el_mineure()/,/^}/p' install.sh); "
        'el_mineure "$1"'
    )
    return subprocess.run(
        ["bash", "-c", script, "sonde", executable],
        cwd=RACINE,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()


class TestSondeDeVersion(unittest.TestCase):
    def test_un_interpreteur_sain_rend_majeure_mineure(self):
        python = subprocess.run(
            ["python3", "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertEqual(el_mineure("python3"), python)

    def test_un_interpreteur_qui_ne_demarre_pas_ne_rend_rien(self):
        with tempfile.TemporaryDirectory() as dossier:
            faux = os.path.join(dossier, "python")
            Path(faux).write_text(PYTHON_MORT)
            os.chmod(faux, os.stat(faux).st_mode | stat.S_IEXEC)
            self.assertEqual(el_mineure(faux), "")

    def test_un_interpreteur_absent_ne_rend_rien(self):
        self.assertEqual(el_mineure("/chemin/qui/n/existe/pas"), "")


if __name__ == "__main__":
    unittest.main()
