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
import shutil
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
echo "LDFLAGS=${LDFLAGS}"
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
        # L'enveloppe source la bibliothèque LDAP du dépôt qui l'a posée.
        lib = self.racine / "script" / "install" / "lib_ldap_compat.sh"
        lib.parent.mkdir(parents=True)
        lib.write_text(
            (RACINE / "script/install/lib_ldap_compat.sh").read_text(
                encoding="utf-8"
            )
        )
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

    def _faux_gcc(self, ldap_r_present):
        """Un gcc qui répond à -print-file-name comme sur un système avec ou
        sans libldap_r : le nom seul quand le fichier est introuvable."""
        libldap = self.racine / "libldap.so"
        libldap.write_text("")
        bin_dir = self.racine / "faux_bin"
        bin_dir.mkdir(exist_ok=True)
        ldap_r = (
            str(self.racine / "libldap_r.so")
            if ldap_r_present
            else "libldap_r.so"
        )
        (bin_dir / "gcc").write_text(
            "#!/usr/bin/env bash\n"
            'case "$1" in\n'
            f'  -print-file-name=libldap_r.so) echo "{ldap_r}" ;;\n'
            f'  -print-file-name=libldap.so) echo "{libldap}" ;;\n'
            "esac\n"
        )
        (bin_dir / "gcc").chmod(0o755)
        return f"{bin_dir}:{os.environ['PATH']}"

    def test_sans_libldap_r_un_lien_vers_libldap_est_fourni(self):
        """OpenLDAP 2.5 a fondu libldap_r dans libldap ; pyldap 2.4, épinglé
        par Odoo 10, se lie encore à -lldap_r."""
        vu = self._appel(self.racine, PATH=self._faux_gcc(False))
        compat = self.racine / VENV / "lib" / "ldap_r_compat"
        self.assertIn(f"-L{compat}", vu["LDFLAGS"])
        self.assertEqual(
            self.racine / "libldap.so", (compat / "libldap_r.so").resolve()
        )

    def test_avec_libldap_r_rien_n_est_ajoute(self):
        vu = self._appel(self.racine, PATH=self._faux_gcc(True))
        self.assertNotIn("ldap_r_compat", vu["LDFLAGS"])

    def test_un_venv_existant_n_est_pas_recree(self):
        """Le faux virtualenv échoue : l'atteindre ferait échouer setUp."""
        self.assertTrue((self.racine / VENV / "bin/poetry").is_file())


class TestSansPythonPourPoetry(unittest.TestCase):
    """Le conseil donné quand aucun Python 3 ne peut porter Poetry."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.racine = Path(self._tmp.name).resolve()
        lib = self.racine / "script" / "install" / "lib_python_provider.sh"
        lib.parent.mkdir(parents=True)
        lib.write_text(
            (RACINE / "script/install/lib_python_provider.sh").read_text(
                encoding="utf-8"
            )
        )
        self.home = self.racine / "home"
        self.home.mkdir()
        # Un PATH qui ne porte que bash : aucun mise du système n'y répond.
        self.bin = self.racine / "bin"
        self.bin.mkdir()
        os.symlink(shutil.which("bash"), self.bin / "bash")

    def lancer(self, **env):
        return subprocess.run(
            [
                str(self.bin / "bash"),
                str(SCRIPT),
                VENV,
                "/bin/false",
                "1.1.15",
            ],
            cwd=self.racine,
            env={
                "PATH": str(self.bin),
                "HOME": str(self.home),
                "PYENV_ROOT": str(self.racine / "pyenv"),
                "EL_PYTHON_PROVIDER": "mise",
                **env,
            },
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_un_mise_hors_du_path_est_nomme_par_son_chemin(self):
        mise = self.home / ".local" / "bin" / "mise"
        mise.parent.mkdir(parents=True)
        mise.write_text("#!/bin/bash\nexit 1\n")
        mise.chmod(0o755)
        sortie = self.lancer()
        self.assertEqual(1, sortie.returncode)
        self.assertIn(f"Voir : {mise} install python@3.11.16", sortie.stdout)

    def test_sans_mise_la_pose_est_conseillee(self):
        sortie = self.lancer()
        self.assertEqual(1, sortie.returncode)
        self.assertIn("make install_mise", sortie.stdout)
        self.assertNotIn("mise install", sortie.stdout)

    def test_un_interpreteur_designe_introuvable_est_nomme(self):
        absent = self.racine / "absent" / "python3"
        sortie = self.lancer(EL_PY2_HELPER_PYTHON=str(absent))
        self.assertEqual(1, sortie.returncode)
        self.assertIn(f"EL_PY2_HELPER_PYTHON={absent}", sortie.stdout)
        self.assertNotIn("mise", sortie.stdout)


class TestAliasSwigHorsPython2(unittest.TestCase):
    def test_l_alias_est_garde_par_la_version_de_python(self):
        """PyInt_FromLong est une vraie fonction en Python 2 : l'alias de
        swig_compat.h la remplacerait par PyLong_FromLong."""
        source = (RACINE / "script/install/install_locally.sh").read_text(
            encoding="utf-8"
        )
        garde = source.index('if [[ "${EL_PYTHON_ODOO_VERSION}" != 2.* ]]')
        alias = source.index("-include ${swig_compat}")
        fin = source.index("fi", alias)
        self.assertLess(garde, alias)
        self.assertLess(alias, fin)


class TestLdapRCheminAbsolu(unittest.TestCase):
    def test_un_repertoire_relatif_donne_un_chemin_absolu(self):
        """install_locally.sh passe un chemin relatif au dépôt ; Poetry
        compile ailleurs, où « -L.venv... » ne mène nulle part."""
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp).resolve()
            libldap = racine / "libldap.so"
            libldap.write_text("")
            bin_dir = racine / "bin"
            bin_dir.mkdir()
            (bin_dir / "gcc").write_text(
                "#!/usr/bin/env bash\n"
                'case "$1" in\n'
                "  -print-file-name=libldap_r.so) echo libldap_r.so ;;\n"
                f'  -print-file-name=libldap.so) echo "{libldap}" ;;\n'
                "esac\n"
            )
            (bin_dir / "gcc").chmod(0o755)
            sortie = subprocess.run(
                [
                    "bash",
                    "-c",
                    f". {RACINE}/script/install/lib_ldap_compat.sh && "
                    'el_ldap_r_compat .venv.x/lib/compat && echo "$LDFLAGS"',
                ],
                cwd=racine,
                env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                f"-L{racine}/.venv.x/lib/compat", sortie.stdout.strip()
            )


class TestLdapRAvantPoetryInstall(unittest.TestCase):
    def test_le_lien_est_pose_avant_l_installation(self):
        """pyldap 2.4 est aussi dans les verrous Python 3 d'Odoo 11 et 12 : le
        lien libldap_r doit exister quand « poetry install » le compile."""
        source = (RACINE / "script/install/install_locally.sh").read_text(
            encoding="utf-8"
        )
        lien = source.index('el_ldap_r_compat "${VENV_ODOO_PATH}')
        installe = source.index('"${POETRY_ODOO_PATH}" install --no-root')
        self.assertLess(lien, installe)


def _pose(racine, chemin, contenu):
    """Un fichier exécutable sous racine, dossiers compris."""
    fichier = racine / chemin
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(contenu)
    fichier.chmod(0o755)


# Un script qui inscrit son nom et ses arguments au journal, puis réussit.
TRACEUR = '#!/usr/bin/env bash\necho "{nom} $*" >> journal\n'

# Un python 2.7.18 qui suffit à install_venv.sh : sa version et pip.
PYTHON_27 = """#!/bin/sh
case "$1" in
  -c) echo 2.7.18 ;;
  -m) echo "pip 20.3.4" ;;
esac
exit 0
"""


class TestPoetryDuVenvPython2(unittest.TestCase):
    """install_venv.sh donne à install_venv_python2.sh le Poetry passé en
    quatrième argument, et celui de .poetry-version sans lui."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self._tmp.name).resolve()
        (self.racine / ".poetry-version").write_text("2.5.1\n")
        _pose(
            self.racine,
            "script/install/lib_python_provider.sh",
            (RACINE / "script/install/lib_python_provider.sh").read_text(
                encoding="utf-8"
            ),
        )
        _pose(self.racine, "pyenv/versions/2.7.18/bin/python", PYTHON_27)
        # Le bouchon pose le venv qu'attend le contrôle final.
        _pose(
            self.racine,
            "script/install/install_venv_python2.sh",
            TRACEUR.format(nom="install_venv_python2")
            + 'mkdir -p "$1/bin" && : > "$1/pyvenv.cfg"'
            ' && : > "$1/bin/activate"'
            ' && cp pyenv/versions/2.7.18/bin/python "$1/bin/python"\n',
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _lance(self, *poetry):
        sortie = subprocess.run(
            ["bash", str(RACINE / "script/install/install_venv.sh")]
            + ["Odoo", VENV, "2.7.18", *poetry],
            cwd=self.racine,
            env={
                **os.environ,
                "PYENV_ROOT": str(self.racine / "pyenv"),
                "EL_PYTHON_PROVIDER": "pyenv",
            },
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, sortie.returncode, sortie.stdout + sortie.stderr)
        return (self.racine / "journal").read_text().split()

    def test_le_poetry_passe_l_emporte_sur_le_fichier(self):
        self.assertEqual("1.1.15", self._lance("1.1.15")[-1])

    def test_sans_argument_le_fichier_decide(self):
        self.assertEqual("2.5.1", self._lance()[-1])


# Ce que la phase poetry d'install_locally.sh source et appelle, réduit à
# des traceurs : aucun pip, aucun Poetry réel ne tourne.
ENV_VAR = """EL_ODOO_VERSION={odoo}
EL_POETRY_VERSION={poetry}
EL_PYTHON_ODOO_VERSION={python}
EL_ERPLIBRE_VERSION={erplibre}
"""


class TestPhasePoetryEnPython2(unittest.TestCase):
    """La phase poetry ne pip-installe pas Poetry dans un venv Python 2 :
    pip n'y en voit jamais, et l'installer y écraserait l'enveloppe."""

    def _lance(self, odoo, python, poetry):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        racine = Path(tmp.name).resolve()
        erplibre = f"odoo{odoo}_python{python}"
        venv = f".venv.{erplibre}"
        (racine / "env_var.sh").write_text(
            ENV_VAR.format(
                odoo=odoo, poetry=poetry, python=python, erplibre=erplibre
            )
        )
        (racine / "conf").mkdir()
        (racine / "conf/python-erplibre-venv").write_text(".venv.erplibre\n")
        for chemin, contenu in {
            # Comme un vrai « pip install poetry », il réécrit bin/poetry en
            # simple script de console : l'enveloppe et son VIRTUAL_ENV
            # disparaîtraient.
            "script/install/lib_pip_provider.sh": (
                "el_pip_install() {\n"
                '    echo "el_pip_install $*" >> journal\n'
                "    printf '#!/bin/sh\\necho \"poetry $*\" >> journal\\n'"
                ' > "$1/bin/poetry"\n'
                '    chmod +x "$1/bin/poetry"\n'
                "}\n"
            ),
            "script/install/S390x/lib_lowmem.sh": "",
            "script/install/lib_ldap_compat.sh": "el_ldap_r_compat() { :; }\n",
            "script/install/install_venv_python2.sh": TRACEUR.format(
                nom="install_venv_python2"
            ),
            f"{venv}/bin/activate": "",
            # Muet à « pip show poetry », comme un vrai venv 2.7.
            f"{venv}/bin/python": TRACEUR.format(nom="python"),
            f"{venv}/bin/poetry": "#!/usr/bin/env bash\n"
            'export VIRTUAL_ENV="${VENV}"\n'
            'echo "poetry $*" >> journal\n',
            ".venv.erplibre/bin/activate": "",
            ".venv.erplibre/bin/python": "#!/bin/sh\nexit 0\n",
            "faux_bin/pip": "#!/bin/sh\nexit 0\n",
        }.items():
            _pose(racine, chemin, contenu)
        sortie = subprocess.run(
            ["bash", str(RACINE / "script/install/install_locally.sh")],
            cwd=racine,
            env={
                **os.environ,
                "EL_PHASE": "poetry",
                "PATH": f"{racine}/faux_bin:{os.environ['PATH']}",
            },
            capture_output=True,
            text=True,
        )
        journal = (racine / "journal").read_text().splitlines()
        self.assertIn(
            "poetry install --no-root", journal, sortie.stdout + sortie.stderr
        )
        return journal, (racine / venv / "bin/poetry").read_text()

    def test_python_2_repasse_par_le_script_dedie(self):
        journal, enveloppe = self._lance("10.0", "2.7.18", "1.1.15")
        venv = ".venv.odoo10.0_python2.7.18"
        self.assertIn(
            f"install_venv_python2 {venv} {venv}/bin/python 1.1.15", journal
        )
        self.assertFalse(
            [ligne for ligne in journal if ligne.startswith("el_pip_install")]
        )
        self.assertIn("VIRTUAL_ENV", enveloppe)

    def test_python_3_installe_poetry_par_pip(self):
        journal, _ = self._lance("18.0", "3.12.16", "2.5.1")
        self.assertIn(
            "el_pip_install .venv.odoo18.0_python3.12.16 poetry==2.5.1",
            journal,
        )
        self.assertFalse(
            [ligne for ligne in journal if "install_venv_python2" in ligne]
        )


if __name__ == "__main__":
    unittest.main()
