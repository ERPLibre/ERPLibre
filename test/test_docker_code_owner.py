#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le propriétaire du code de l'image : celui que demande la construction.

erplibre_info_git_fetch tire le code depuis Odoo, et un fetch écrit dans les
« .git » : le compte qui fait tourner Odoo doit en être propriétaire.
ERPLIBRE_CODE_OWNER choisit ce compte à la construction, « odoo » par
défaut, « root » pour une image qu'Odoo ne peut pas réécrire.

Ce que ces tests gardent :

- toute étape qui écrit dans /ERPLibre s'exécute sous ERPLIBRE_CODE_OWNER.
  Une étape restée sous root y laisse des fichiers que le compte odoo ne peut
  plus réécrire, et le prochain tirage échoue sur ce dépôt-là ;
- aucun « chown -R » ne rattrape la propriété après coup : il recopierait
  l'arbre entier dans une nouvelle couche de l'image ;
- la valeur est vérifiée avant toute étape, et docker_build.sh la transmet.
"""

import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
PROD = (RACINE / "docker/Dockerfile.prod.pkg").read_text(encoding="utf-8")
BUILD = (RACINE / "script/docker/docker_build.sh").read_text(encoding="utf-8")
ENTREE = (RACINE / "docker/entrypoint_pip_extra.sh").read_text(
    encoding="utf-8"
)


def _instructions(texte):
    """Les instructions du Dockerfile, lignes continuées par « \\ » réunies et
    commentaires retirés, dans l'ordre."""
    lignes, courante = [], ""
    for ligne in texte.splitlines():
        brute = ligne.strip()
        if not courante and (not brute or brute.startswith("#")):
            continue
        if brute.startswith("#"):
            continue
        courante += " " + brute.rstrip("\\").strip()
        if not brute.endswith("\\"):
            lignes.append(courante.strip())
            courante = ""
    return lignes


def _run_par_compte(texte):
    """[(compte de l'instruction USER en vigueur, commande RUN)]."""
    compte, couples = None, []
    for instruction in _instructions(texte):
        mot, _, reste = instruction.partition(" ")
        if mot == "USER":
            compte = reste.strip()
        elif mot == "RUN":
            couples.append((compte, reste))
    return couples


class TestProprietaireDuCode(unittest.TestCase):
    def test_odoo_par_defaut(self):
        self.assertRegex(PROD, r"(?m)^ARG ERPLIBRE_CODE_OWNER=odoo$")

    def test_ce_qui_ecrit_dans_erplibre_tourne_sous_le_proprietaire(self):
        ecrit = re.compile(r"\$ODOO_PREFIX|/ERPLibre\b|\bgit clone\b")
        fautifs = [
            run
            for compte, run in _run_par_compte(PROD)
            if ecrit.search(run)
            and "/odoo.conf" not in run
            and compte != "${ERPLIBRE_CODE_OWNER}"
        ]
        self.assertEqual([], fautifs)

    def test_root_ne_sert_plus_qu_a_apt_et_a_odoo_conf(self):
        sous_root = [
            run for compte, run in _run_par_compte(PROD) if compte == "root"
        ]
        self.assertEqual(2, len(sous_root), sous_root)
        self.assertIn("apt install", sous_root[0])
        self.assertIn("cp /etc/odoo/odoo.conf /odoo.conf", sous_root[1])

    def test_la_valeur_est_verifiee_avant_toute_etape(self):
        premier = _run_par_compte(PROD)[1][1]
        self.assertIn('case "${ERPLIBRE_CODE_OWNER}" in', premier)
        self.assertIn("odoo|root)", premier)

    def test_aucun_chown_recursif(self):
        self.assertNotRegex(" ".join(_instructions(PROD)), r"chown\s+-R")

    def test_l_image_finit_sous_odoo(self):
        users = [i for i in _instructions(PROD) if i.startswith("USER ")]
        self.assertEqual("USER odoo", users[-1])

    def test_docker_build_transmet_la_valeur(self):
        self.assertIn(
            "--build-arg ERPLIBRE_CODE_OWNER=${ERPLIBRE_CODE_OWNER}", BUILD
        )

    def test_pip_extra_tourne_sous_le_proprietaire_du_venv(self):
        self.assertIn('stat -c %u "${venv}"', ENTREE)
        self.assertIn('"${sous[@]}" "${python}" -m pip install', ENTREE)


if __name__ == "__main__":
    unittest.main()
