#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'enveloppe bin/poetry d'un venv Python 2 donne-t-elle à Poetry le bon
environnement ?

Tout le dépôt appelle Poetry par « .venv.<version>/bin/poetry ». En Python 2,
ce chemin est une enveloppe vers le Poetry d'un venv Python 3 voisin, et
c'est elle qui décide où Poetry installe :

- VIRTUAL_ENV épinglé sur le venv 2.7. Avec « virtualenvs.create = false »,
  Poetry installerait sinon dans le venv Python 3 qui le fait tourner ;
- POETRY_CACHE_DIR absolu : Poetry 1.1 refuse le « cache-dir = "./" »
  relatif de poetry.toml quand il en fait une URI ;
- -fpermissive ajouté aux CFLAGS de l'appelant, sans les remplacer.

Les pièces lourdes — venv de Poetry, venv 2.7 — sont remplacées par des
bouchons déjà en place, que le script garde : il n'écrit que l'enveloppe.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/install/install_venv_python2.sh"
VENV = ".venv.odoo10.0_python2.7.18"
AIDE = ".venv.poetry1.1.15"

# Le faux Poetry imprime ce que l'enveloppe lui transmet.
FAUX_POETRY = """#!/usr/bin/env bash
echo "VIRTUAL_ENV=${VIRTUAL_ENV}"
echo "POETRY_CACHE_DIR=${POETRY_CACHE_DIR}"
echo "CFLAGS=${CFLAGS}"
echo "ARGS=$*"
"""


class TestEnveloppePoetry(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self._tmp.name).resolve()
        for bouchon, contenu in {
            f"{AIDE}/bin/poetry": FAUX_POETRY,
            f"{AIDE}/bin/virtualenv": "#!/usr/bin/env bash\nexit 1\n",
        }.items():
            chemin = self.racine / bouchon
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text(contenu)
            chemin.chmod(0o755)
        (self.racine / VENV / "bin").mkdir(parents=True)
        (self.racine / VENV / "pyvenv.cfg").write_text("version = 2.7.18\n")
        sortie = subprocess.run(
            ["bash", str(SCRIPT), VENV, "/bin/false", "1.1.15"],
            cwd=self.racine,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, sortie.returncode, sortie.stdout + sortie.stderr)

    def tearDown(self):
        self._tmp.cleanup()

    def _appel(self, cwd, **env):
        environ = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        environ.update(env)
        sortie = subprocess.run(
            [str(self.racine / VENV / "bin/poetry"), "install", "--no-root"],
            cwd=cwd,
            env=environ,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, sortie.returncode, sortie.stderr)
        return dict(
            ligne.split("=", 1) for ligne in sortie.stdout.splitlines()
        )

    def test_le_venv_2_7_est_epingle(self):
        vu = self._appel(self.racine)
        self.assertEqual(str(self.racine / VENV), vu["VIRTUAL_ENV"])
        self.assertEqual("install --no-root", vu["ARGS"])

    def test_le_cache_est_absolu_quel_que_soit_le_repertoire(self):
        vu = self._appel(self.racine / VENV / "bin")
        self.assertEqual(f"{self.racine}/", vu["POETRY_CACHE_DIR"])

    def test_les_cflags_de_l_appelant_sont_gardes(self):
        vu = self._appel(self.racine, CFLAGS="-O1")
        self.assertEqual("-O1 -fpermissive", vu["CFLAGS"])

    def test_un_venv_existant_n_est_pas_recree(self):
        """Le faux virtualenv échoue : l'atteindre ferait échouer setUp."""
        self.assertTrue((self.racine / VENV / "bin/poetry").is_file())


class TestAliasSwigHorsPython2(unittest.TestCase):
    def test_l_alias_est_garde_par_la_version_de_python(self):
        """PyInt_FromLong est une vraie fonction en Python 2 : l'alias de
        SWIG 4.3 la remplacerait par PyLong_FromLong."""
        source = (RACINE / "script/install/install_locally.sh").read_text(
            encoding="utf-8"
        )
        garde = source.index('if [[ "${EL_PYTHON_ODOO_VERSION}" != 2.* ]]')
        alias = source.index("-DPyInt_FromLong(x)=PyLong_FromLong(x)")
        fin = source.index("fi", alias)
        self.assertLess(garde, alias)
        self.assertLess(alias, fin)


if __name__ == "__main__":
    unittest.main()
