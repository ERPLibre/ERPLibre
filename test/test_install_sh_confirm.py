#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La question qu'install.sh pose avant l'installation du venv d'outillage.

L'installation peut SUPPRIMER un .venv.erplibre existant : elle ne part que
sur un oui explicite. La réponse se donne en français ou en anglais (o, oui,
y, yes, toute casse) ; Entrée seule vaut non. Sans terminal sur l'entrée,
personne ne peut consentir, et la réponse est non sans question posée.
"""

import os
import select
import subprocess
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SCRIPT = (
    "source <(sed -n '/^el_confirmer()/,/^}/p' install.sh); "
    'el_confirmer "Lancer ?"'
)


def repondre_au_terminal(reponse):
    """Lance el_confirmer sur un pseudo-terminal, y tape la réponse.

    Rend le code de sortie et ce que le terminal a affiché.
    """
    maitre, esclave = os.openpty()
    proc = subprocess.Popen(
        ["bash", "-c", SCRIPT],
        cwd=RACINE,
        stdin=esclave,
        stdout=esclave,
        stderr=esclave,
    )
    os.close(esclave)
    os.write(maitre, (reponse + "\n").encode())
    code = proc.wait(timeout=10)
    lu = b""
    while select.select([maitre], [], [], 0.2)[0]:
        try:
            morceau = os.read(maitre, 4096)
        except OSError:
            break
        if not morceau:
            break
        lu += morceau
    os.close(maitre)
    return code, lu.decode(errors="replace")


class TestConfirmer(unittest.TestCase):
    def test_oui_en_francais_et_en_anglais(self):
        for reponse in ("o", "O", "oui", "Oui", "y", "Y", "yes", "YES"):
            with self.subTest(reponse=reponse):
                self.assertEqual(repondre_au_terminal(reponse)[0], 0)

    def test_entree_seule_et_non_refusent(self):
        for reponse in ("", "n", "non", "no", "ouais", "x"):
            with self.subTest(reponse=reponse):
                self.assertEqual(repondre_au_terminal(reponse)[0], 1)

    def test_la_question_annonce_le_defaut(self):
        self.assertIn("Lancer ? [o/N]", repondre_au_terminal("n")[1])

    def test_sans_terminal_la_reponse_est_non(self):
        proc = subprocess.run(
            ["bash", "-c", SCRIPT],
            cwd=RACINE,
            input="o\n",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("[o/N]", proc.stdout)


if __name__ == "__main__":
    unittest.main()
