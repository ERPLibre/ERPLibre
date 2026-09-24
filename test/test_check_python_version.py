#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le contrôle voit-il ce que le Python du dépôt refuse ?

Ce contrôle existe parce qu'aucun autre outil ne voit ce défaut : la cible de
black borne ce qu'il ÉCRIT, jamais ce qu'il accepte, et flake8 analyse avec
l'interpréteur courant. Une syntaxe que la version déclarée ne connaît pas ne
casse donc qu'au chargement, loin du commit qui l'a introduite.

Sa portée suit conf/python-erplibre-version : il ne signale que ce que CETTE
version refuse. Le dépôt déclarant aujourd'hui la plus récente des versions
publiées, seuls un source cassé et un source écrit pour plus récent encore lui
échappent — d'où les tests qui déclarent une version ancienne pour éprouver le
mécanisme lui-même.

Deux exigences que ces tests gardent, et qu'il serait facile de perdre :

- SANS interpréteur de la version voulue, le contrôle DIT qu'il n'a pas
  vérifié. Un outil qui rend 0 en silence laisse croire qu'il a regardé.
- Les dépôts rapatriés sous script/ sont écartés même quand leur chemin est
  NOMMÉ : sans « force-exclude », l'exclusion ne vaudrait qu'à la découverte,
  et le contrôle irait juger l'historique d'autrui.
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
OUTIL = RACINE / "script/analyse/check_python_version.py"

sys.path.insert(0, str(RACINE / "script" / "analyse"))

import check_python_version as controle  # noqa: E402

# Cas INVENTÉS, jamais copiés d'un fichier du dépôt : un exemple qui illustre
# un interdit ne se prend pas dans le parc.
#
# Une f-string PEP 701 — des guillemets doubles dans une f-string à guillemets
# doubles — que Python refuse avant 3.12 et accepte depuis.
PEP_701 = 'x = f"{"a"}"\n'
# Cassé sous toute version.
CASSE = "def f(:\n    pass\n"


@contextlib.contextmanager
def version_declaree(valeur):
    """Fait dire au dépôt qu'il vise `valeur`, le temps d'un test."""
    with tempfile.TemporaryDirectory() as coin:
        fichier = Path(coin) / "python-erplibre-version"
        fichier.write_text(valeur, encoding="utf-8")
        ancien, controle.VERSION = controle.VERSION, str(fichier)
        try:
            yield
        finally:
            controle.VERSION = ancien


def juge(contenu, version):
    """Ce que l'outil imprime sur un fichier portant `contenu`."""
    with tempfile.TemporaryDirectory() as coin:
        cible = Path(coin) / "echantillon.py"
        cible.write_text(contenu, encoding="utf-8")
        sortie = io.StringIO()
        with version_declaree(version), contextlib.redirect_stdout(sortie):
            code = controle.main([str(cible)])
    return code, sortie.getvalue()


def interpreteur_absent(version):
    return controle.interpreteur(version) is None


class TestCeQuIlVoit(unittest.TestCase):
    def test_un_source_casse_est_signale(self):
        version = controle.version_voulue()
        if interpreteur_absent(version):
            self.skipTest(f"aucun Python {version} ici")
        code, sortie = juge(CASSE, version)
        self.assertIn("echantillon.py", sortie)
        self.assertIn("🔴", sortie)
        self.assertEqual(0, code, "il informe, il ne bloque pas")

    def test_une_syntaxe_plus_recente_que_la_version_declaree(self):
        """Le mécanisme même : PEP 701 refusé quand le dépôt vise 3.10."""
        if interpreteur_absent("3.10"):
            self.skipTest("aucun Python 3.10 ici")
        _, sortie = juge(PEP_701, "3.10")
        self.assertIn("echantillon.py", sortie)

    def test_la_meme_syntaxe_passe_sous_une_version_qui_la_connait(self):
        if interpreteur_absent("3.12"):
            self.skipTest("aucun Python 3.12 ici")
        _, sortie = juge(PEP_701, "3.12")
        self.assertEqual("", sortie.strip())

    def test_un_source_ordinaire_ne_dit_rien(self):
        version = controle.version_voulue()
        if interpreteur_absent(version):
            self.skipTest(f"aucun Python {version} ici")
        _, sortie = juge("import os\n\nprint(os.sep)\n", version)
        self.assertEqual("", sortie.strip())

    def test_le_depot_lui_meme_passe(self):
        fin = subprocess.run(
            [sys.executable, str(OUTIL), "script/"],
            cwd=RACINE,
            capture_output=True,
            text=True,
        )
        self.assertEqual("", fin.stdout.strip(), fin.stdout)
        self.assertEqual(0, fin.returncode)


class TestCeQuIlReconnait(unittest.TestCase):
    def test_un_executable_sans_suffixe_au_hashbang_python(self):
        """Les deux hooks du dépôt n'ont pas de suffixe : ils comptent."""
        with tempfile.TemporaryDirectory() as coin:
            hook = Path(coin) / "pre-commit"
            hook.write_text(
                "#!/usr/bin/env python3\nx = 1\n", encoding="utf-8"
            )
            self.assertTrue(controle.est_python(str(hook)))

    def test_un_fichier_sans_suffixe_ni_hashbang_python_est_ignore(self):
        with tempfile.TemporaryDirectory() as coin:
            texte = Path(coin) / "LISEZMOI"
            texte.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            self.assertFalse(controle.est_python(str(texte)))

    def test_un_depot_rapatrie_est_ecarte_meme_nomme(self):
        self.assertFalse(
            controle.est_python("script/OCA_maintainer-tools/tools/config.py")
        )
        self.assertFalse(controle.est_python("addons/module/models/x.py"))


class TestQuandIlNePeutPasVerifier(unittest.TestCase):
    def test_sans_interpreteur_il_dit_qu_il_n_a_pas_verifie(self):
        """Le silence ferait croire à un contrôle qui n'a pas eu lieu."""
        aveugle = dict(
            os.environ,
            PATH="/nonexistent",
            PYENV_ROOT="/nonexistent",
            MISE_DATA_DIR="/nonexistent",
        )
        with tempfile.TemporaryDirectory() as coin:
            cible = Path(coin) / "echantillon.py"
            cible.write_text(CASSE, encoding="utf-8")
            fin = subprocess.run(
                [sys.executable, str(OUTIL), str(cible)],
                cwd=RACINE,
                capture_output=True,
                text=True,
                env=aveugle,
            )
        if fin.stdout.strip():
            self.skipTest("un interpréteur de la version reste joignable ici")
        self.assertTrue(fin.stderr.strip(), "l'avertissement manque")
        self.assertEqual(0, fin.returncode)

    def test_sans_fichier_de_version_rien_n_est_affirme(self):
        with tempfile.TemporaryDirectory() as coin:
            ancien = controle.VERSION
            controle.VERSION = str(Path(coin) / "absent")
            try:
                self.assertIsNone(controle.version_voulue())
            finally:
                controle.VERSION = ancien


class TestLaVersionLue(unittest.TestCase):
    def test_la_premiere_ligne_utile_est_retenue(self):
        with version_declaree("# un commentaire\n\n3.14.7\n"):
            self.assertEqual("3.14.7", controle.version_voulue())

    def test_le_depot_declare_bien_une_version(self):
        self.assertRegex(controle.version_voulue(), r"^\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
