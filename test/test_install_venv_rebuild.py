#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""install_venv.sh détruit un venv : sous quelles conditions, exactement ?

C'est le seul endroit du dépôt qui efface le travail de quelqu'un. Un venv
porte ce qu'on y a posé à la main — bin/repo, uv, des paquets — et le nom
.venv.erplibre ne dit pas sa version : rien ne distingue de l'extérieur celui
qu'il faut rebâtir de celui qu'il faut garder.

Ces tests pèsent donc les REFUS autant que les destructions :

- un répertoire sans pyvenv.cfg n'est pas un venv et garde son contenu ;
- un venv sur un système de fichiers monté appartient à une autre machine, et
  l'effacer le ferait à travers le réseau ;
- un venv utilisable est conservé, sans quoi chaque installation rebâtirait
  ce qui marche.

L'interpréteur est un bouchon annoncé par PYENV_ROOT : les tests restent hors
réseau, et rien ne dépend de ce que cette machine a installé.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/install/install_venv.sh"

VOULUE = "9.99.0"
AUTRE = "9.98.0"

# Un python qui suffit à ce que le script lui demande : sa version, la création
# d'un venv, et la présence de pip.
BOUCHON = """#!/bin/sh
VERSION=__VERSION__
case "$1" in
  -V|--version) echo "Python ${VERSION}" ;;
  -c) echo "${VERSION}" ;;
  -m)
    case "$2" in
      venv)
        mkdir -p "$3/bin" || exit 1
        printf 'version = %s\\n' "${VERSION}" > "$3/pyvenv.cfg"
        sed "s/^VERSION=.*/VERSION=${VERSION}/" "$0" > "$3/bin/python"
        chmod +x "$3/bin/python"
        : > "$3/bin/activate"
        ;;
      pip) echo "pip 99.0 from nowhere" ;;
      *) exit 1 ;;
    esac
    ;;
  *) exit 1 ;;
esac
exit 0
"""


def pose_bouchon(chemin, version):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        BOUCHON.replace("__VERSION__", version), encoding="utf-8"
    )
    chemin.chmod(0o755)


class BancInstallVenv(unittest.TestCase):
    """Un PYENV_ROOT bouchonné, et un répertoire de travail jetable."""

    def setUp(self):
        self.coin = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.coin, ignore_errors=True)
        pose_bouchon(
            self.coin / "pyenv" / "versions" / VOULUE / "bin" / "python",
            VOULUE,
        )
        self.bin = self.coin / "bin"
        self.bin.mkdir()

    def env(self):
        return dict(
            os.environ,
            PYENV_ROOT=str(self.coin / "pyenv"),
            PATH=f"{self.bin}:{os.environ['PATH']}",
            EL_PYTHON_PROVIDER="pyenv",
        )

    def lance(self, chemin_venv, contexte="ERPLibre"):
        return subprocess.run(
            [str(SCRIPT), contexte, str(chemin_venv), VOULUE],
            cwd=RACINE,
            capture_output=True,
            text=True,
            env=self.env(),
        )

    def venv_factice(self, nom, version):
        """Un venv complet, comme « python -m venv » le laisse."""
        chemin = self.coin / nom
        (chemin / "bin").mkdir(parents=True)
        (chemin / "pyvenv.cfg").write_text(f"version = {version}\n")
        pose_bouchon(chemin / "bin" / "python", version)
        (chemin / "bin" / "activate").touch()
        (chemin / "TEMOIN").write_text("pose a la main\n")
        return chemin


class TestCeQuIlConserve(BancInstallVenv):
    def test_un_venv_a_la_bonne_version_est_garde(self):
        venv = self.venv_factice("bon", VOULUE)
        fin = self.lance(venv)
        self.assertEqual(0, fin.returncode, fin.stdout + fin.stderr)
        self.assertTrue(
            (venv / "TEMOIN").exists(), "il a été rebâti pour rien"
        )

    def test_un_chemin_neuf_est_simplement_cree(self):
        venv = self.coin / "neuf"
        fin = self.lance(venv)
        self.assertEqual(0, fin.returncode, fin.stdout + fin.stderr)
        self.assertTrue((venv / "pyvenv.cfg").exists())


class TestCeQuIlDetruit(BancInstallVenv):
    def test_un_venv_d_une_autre_version_est_rebati(self):
        venv = self.venv_factice("perime", AUTRE)
        fin = self.lance(venv)
        self.assertEqual(0, fin.returncode, fin.stdout + fin.stderr)
        self.assertIn("DESTRUCTION", fin.stdout)
        self.assertFalse((venv / "TEMOIN").exists())
        self.assertIn(VOULUE, (venv / "pyvenv.cfg").read_text())

    def test_la_destruction_est_annoncee_avant_d_avoir_lieu(self):
        """Dans un journal de milliers de lignes, l'avis doit précéder."""
        venv = self.venv_factice("perime", AUTRE)
        fin = self.lance(venv)
        self.assertLess(
            fin.stdout.index("DESTRUCTION"),
            fin.stdout.index("Create Virtual environment"),
        )

    def test_un_venv_sans_pip_est_rebati(self):
        """Ce que laisse « python -m venv » quand ensurepip manque."""
        venv = self.venv_factice("sans_pip", VOULUE)
        (venv / "bin" / "activate").unlink()
        fin = self.lance(venv)
        self.assertEqual(0, fin.returncode, fin.stdout + fin.stderr)
        self.assertFalse((venv / "TEMOIN").exists())


class TestLExigenceDePatch(BancInstallVenv):
    """Le patch ne borne que le venv d'Odoo, contraint par son pyproject.

    Sur le venv d'outillage, l'exiger écarterait le Python des distributions
    dès qu'il est d'un cran en retard — et ferait compiler CPython pour une
    différence que rien ne réclame."""

    PATCH_PLUS_BAS = "9.99.0"
    DEMANDE = "9.99.4"

    def setUp(self):
        super().setUp()
        pose_bouchon(
            self.coin / "pyenv" / "versions" / self.DEMANDE / "bin" / "python",
            self.DEMANDE,
        )

    def joue(self, contexte, venv):
        return subprocess.run(
            [str(SCRIPT), contexte, str(venv), self.DEMANDE],
            cwd=RACINE,
            capture_output=True,
            text=True,
            env=self.env(),
        )

    def test_l_outillage_garde_un_patch_plus_ancien(self):
        venv = self.venv_factice("outils", self.PATCH_PLUS_BAS)
        fin = self.joue("ERPLibre", venv)
        self.assertEqual(0, fin.returncode, fin.stdout + fin.stderr)
        self.assertTrue((venv / "TEMOIN").exists(), fin.stdout)

    def test_odoo_refuse_un_patch_plus_ancien(self):
        """Poetry refuserait un patch inférieur à ce que borne le pyproject."""
        venv = self.venv_factice("odoo", self.PATCH_PLUS_BAS)
        fin = self.joue("Odoo", venv)
        self.assertIn("conserve", fin.stdout + fin.stderr)

    def test_une_autre_mineure_ne_passe_jamais(self):
        venv = self.venv_factice("mineure", "9.98.0")
        fin = self.joue("ERPLibre", venv)
        self.assertIn("DESTRUCTION", fin.stdout)


class TestCeQueLeContexteDecide(BancInstallVenv):
    """Rebâtir le venv d'outillage coûte une installation pip ; rebâtir celui
    d'Odoo en refait une de Poetry entière. L'écart de version ne vaut donc
    destruction que pour le premier."""

    def test_le_venv_odoo_d_une_autre_version_est_conserve(self):
        venv = self.venv_factice("odoo", AUTRE)
        fin = self.lance(venv, contexte="Odoo")
        self.assertEqual(0, fin.returncode, fin.stdout + fin.stderr)
        self.assertIn("conserve", fin.stdout)
        self.assertTrue((venv / "TEMOIN").exists())

    def test_le_venv_odoo_hors_service_est_rebati_quand_meme(self):
        """Une autre version se tolère ; un interpréteur mort, non."""
        venv = self.venv_factice("odoo_casse", VOULUE)
        (venv / "bin" / "python").write_text("#!/bin/sh\nexit 1\n")
        fin = self.lance(venv, contexte="Odoo")
        self.assertEqual(0, fin.returncode, fin.stdout + fin.stderr)
        self.assertIn("DESTRUCTION", fin.stdout)
        self.assertFalse((venv / "TEMOIN").exists())


class TestCeQuIlRefuse(BancInstallVenv):
    def test_un_repertoire_sans_pyvenv_cfg_garde_son_contenu(self):
        pas_un_venv = self.coin / "donnees"
        (pas_un_venv / "sous").mkdir(parents=True)
        (pas_un_venv / "sous" / "PRECIEUX").write_text("ne pas effacer\n")
        fin = self.lance(pas_un_venv)
        self.assertEqual(1, fin.returncode)
        self.assertIn("Refus de detruire", fin.stdout)
        self.assertTrue((pas_un_venv / "sous" / "PRECIEUX").exists())

    def test_un_venv_monte_a_distance_est_epargne(self):
        """Il appartient à une autre machine : l'effacer traverse le réseau."""
        faux_findmnt = self.bin / "findmnt"
        faux_findmnt.write_text("#!/bin/sh\necho fuse.sshfs\n")
        faux_findmnt.chmod(0o755)
        venv = self.venv_factice("monte", AUTRE)
        fin = self.lance(venv)
        self.assertEqual(1, fin.returncode)
        self.assertIn("monte a distance", fin.stdout)
        self.assertTrue((venv / "TEMOIN").exists())

    def test_un_repertoire_vide_ne_demande_pas_d_intervention(self):
        """Rien à perdre : rmdir suffit, et l'installation continue."""
        vide = self.coin / "vide"
        vide.mkdir()
        fin = self.lance(vide)
        self.assertEqual(0, fin.returncode, fin.stdout + fin.stderr)
        self.assertNotIn("Refus", fin.stdout)

    def test_la_racine_est_refusee(self):
        fin = subprocess.run(
            [str(SCRIPT), "ERPLibre", "/", VOULUE],
            cwd=RACINE,
            capture_output=True,
            text=True,
            env=self.env(),
        )
        self.assertEqual(1, fin.returncode)
        self.assertNotIn("DESTRUCTION", fin.stdout)


class TestSansInterpreteur(BancInstallVenv):
    def test_aucune_destruction_quand_l_interpreteur_manque(self):
        """L'interpréteur est obtenu AVANT : sinon on reste sans venv."""
        venv = self.venv_factice("perime", AUTRE)
        env = dict(self.env(), PYENV_ROOT=str(self.coin / "nulle_part"))
        fin = subprocess.run(
            [str(SCRIPT), "ERPLibre", str(venv), VOULUE],
            cwd=RACINE,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(1, fin.returncode)
        self.assertTrue((venv / "TEMOIN").exists())


if __name__ == "__main__":
    unittest.main()
