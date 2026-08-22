#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installation Poetry survit à SWIG >= 4.3.

pykcs11 — tiré par endesive, donc dans les locks Odoo 14, 15 et 17 — ne livre
aucun wrapper pré-généré : SWIG tourne à chaque installation. Son
« requires = ["setuptools", "swig"] » n'étant pas borné, Poetry prend la
DERNIÈRE version de PyPI. SWIG 4.3 a retiré les alias Python 2 que les
versions antérieures écrivaient dans le code généré, et le typemap CK_RV de
pykcs11 en utilise un : « ‘PyInt_FromLong’ was not declared in this scope »,
55 fois, et install_odoo_17 s'arrête.

Ces tests gardent les trois choses que l'enquête a coûté :

- CPPFLAGS, pas CFLAGS. Un .cpp est compilé par « compiler_so_cxx », qui lit
  CXXFLAGS et CPPFLAGS ; CFLAGS ne l'atteint JAMAIS. Le premier correctif a
  échoué exactement là.
- La définition doit être identique TOKEN POUR TOKEN à celle de SWIG 4.2,
  sinon les hôtes qui ont encore un vieux SWIG récoltent un avertissement de
  redéfinition à chaque fichier.
- Le drapeau doit être posé AVANT « poetry install », et s'ajouter à un
  CPPFLAGS existant au lieu de l'écraser.
"""

import os
import re
import shutil
import subprocess
import sysconfig
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/install/install_locally.sh"
SOURCE = SCRIPT.read_text(encoding="utf-8")

# La ligne que SWIG <= 4.2 plaçait lui-même dans le wrapper généré.
SWIG_42 = "#define PyInt_FromLong(x) PyLong_FromLong(x)"

# Ce que produit SWIG >= 4.3 : l'appel, sans l'alias.
APPEL_SWIG_43 = """
#include <Python.h>
PyObject *sonde(long v) { return PyInt_FromLong(v); }
"""


def _drapeau():
    """Le -D tel qu'il est écrit dans le script — source unique."""
    m = re.search(r"export CPPFLAGS=\"[^\"]*?(-DPyInt_FromLong[^\" ]*)\"", SOURCE)
    return m.group(1) if m else ""


def _compilateur():
    return shutil.which("c++") or shutil.which("g++")


def _compile(source, drapeaux):
    """(succès, sortie) d'une compilation de syntaxe seule."""
    inc = sysconfig.get_paths()["include"]
    if not Path(inc, "Python.h").exists():
        return None, "Python.h absent"
    with tempfile.TemporaryDirectory() as tmp:
        fichier = Path(tmp, "sonde.cpp")
        fichier.write_text(source, encoding="utf-8")
        res = subprocess.run(
            [_compilateur(), "-fsyntax-only", *drapeaux, "-I", inc, str(fichier)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    return res.returncode == 0, res.stdout + res.stderr


class TestLeDrapeauDansLeScript(unittest.TestCase):
    def test_it_is_exported(self):
        self.assertTrue(_drapeau(), "aucun -DPyInt_FromLong dans le script")

    def test_it_is_set_before_poetry_install(self):
        """Posé après, il n'atteindrait rien : c'est « poetry install » qui
        lance les compilations."""
        export = SOURCE.index("export CPPFLAGS=")
        install = SOURCE.index('install --no-root ${POETRY_VERBOSE}')
        self.assertLess(export, install)

    def test_it_appends_instead_of_replacing(self):
        """Écraser CPPFLAGS jetterait ce que l'appelant y avait mis — sur
        s390x et openSUSE, des chemins d'en-têtes y passent."""
        self.assertIn('${CPPFLAGS:+${CPPFLAGS} }', SOURCE)

    def test_it_is_cppflags_and_not_cflags(self):
        """Le piège qui a fait échouer le premier correctif : le fichier fautif
        est un .cpp, et CFLAGS ne va qu'aux .c."""
        self.assertNotIn("export CFLAGS=", SOURCE)

    def test_the_shell_builds_the_value_it_claims(self):
        """Les parenthèses du -D sont des métacaractères du shell : mal
        protégées, la variable serait tronquée ou le script casserait."""
        for depart, attendu in (
            ("", "-DPyInt_FromLong(x)=PyLong_FromLong(x)"),
            ("-DDEJA=1", "-DDEJA=1 -DPyInt_FromLong(x)=PyLong_FromLong(x)"),
        ):
            res = subprocess.run(
                [
                    "bash",
                    "-c",
                    f'export CPPFLAGS="{depart}"; '
                    'export CPPFLAGS="${CPPFLAGS:+${CPPFLAGS} }'
                    f'{_drapeau()}"; printf %s "$CPPFLAGS"',
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(attendu, res.stdout)

    def test_the_script_still_parses(self):
        res = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(0, res.returncode, res.stderr)


@unittest.skipUnless(_compilateur(), "aucun compilateur C++")
class TestLeDrapeauCompile(unittest.TestCase):
    """Le drapeau fait-il ce qu'on lui prête ? Compilé, pas supposé."""

    def test_swig_43_output_fails_without_it(self):
        """Sans quoi le test suivant ne prouverait rien : c'est bien CE
        symptôme que le drapeau soigne."""
        ok, sortie = _compile(APPEL_SWIG_43, [])
        if ok is None:
            self.skipTest(sortie)
        self.assertFalse(ok)
        self.assertIn("PyInt_FromLong", sortie)

    def test_the_same_source_compiles_with_it(self):
        ok, sortie = _compile(APPEL_SWIG_43, [_drapeau()])
        if ok is None:
            self.skipTest(sortie)
        self.assertTrue(ok, sortie[-400:])

    def test_it_does_not_clash_with_an_older_swig(self):
        """Un hôte dont le SWIG écrit encore l'alias verrait, sinon, un
        avertissement de redéfinition par fichier compilé. En -Werror, ce
        serait un échec."""
        ok, sortie = _compile(
            SWIG_42 + APPEL_SWIG_43, ["-Werror", _drapeau()]
        )
        if ok is None:
            self.skipTest(sortie)
        self.assertTrue(ok, sortie[-400:])
        self.assertNotIn("redefined", sortie)


class TestHypotheseSetuptools(unittest.TestCase):
    """L'hypothèse dont dépend le choix de CPPFLAGS, écrite noir sur blanc.

    Si un setuptools futur change de câblage, c'est ici qu'on l'apprend — pas
    au milieu d'une installation de VM.
    """

    def test_cppflags_reaches_the_cxx_compiler_but_cflags_does_not(self):
        try:
            from setuptools._distutils.ccompiler import new_compiler
            from setuptools._distutils.sysconfig import customize_compiler
        except ImportError as exc:  # pragma: no cover - setuptools trop vieux
            self.skipTest(f"distutils vendu introuvable : {exc}")
        garde = {v: os.environ.get(v) for v in ("CFLAGS", "CPPFLAGS")}
        os.environ["CFLAGS"] = "-DVU_PAR_CFLAGS=1"
        os.environ["CPPFLAGS"] = "-DVU_PAR_CPPFLAGS=1"
        try:
            compilateur = new_compiler()
            customize_compiler(compilateur)
            cxx = getattr(compilateur, "compiler_so_cxx", None)
            if not cxx:
                self.skipTest("pas de compiler_so_cxx dans ce setuptools")
            self.assertIn("-DVU_PAR_CPPFLAGS=1", cxx)
            self.assertNotIn("-DVU_PAR_CFLAGS=1", cxx)
        finally:
            for var, val in garde.items():
                if val is None:
                    os.environ.pop(var, None)
                else:
                    os.environ[var] = val


if __name__ == "__main__":
    unittest.main(verbosity=1)
