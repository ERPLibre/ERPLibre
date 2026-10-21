#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installation Poetry survit à SWIG >= 4.3, et autotools survit au remède.

pykcs11 — tiré par endesive, donc dans les locks Odoo 14, 15 et 17 — ne livre
aucun wrapper pré-généré : SWIG tourne à chaque installation. Son
« requires = ["setuptools", "swig"] » n'étant pas borné, Poetry prend la
DERNIÈRE version de PyPI. SWIG 4.3 a retiré les alias Python 2 que les
versions antérieures écrivaient dans le code généré, et le typemap CK_RV de
pykcs11 en utilise un : « ‘PyInt_FromLong’ was not declared in this scope ».

L'alias est rendu par script/install/swig_compat.h, inclus de force par
CPPFLAGS. Ces tests gardent ce qui en dépend :

- CPPFLAGS, pas CFLAGS. Un .cpp est compilé par « compiler_so_cxx », qui lit
  CXXFLAGS et CPPFLAGS ; CFLAGS ne l'atteint JAMAIS.
- La définition doit être identique TOKEN POUR TOKEN à celle de SWIG 4.2,
  sinon les hôtes qui ont encore un vieux SWIG récoltent un avertissement de
  redéfinition à chaque fichier.
- Le drapeau doit être posé AVANT « poetry install », et s'ajouter à un
  CPPFLAGS existant au lieu de l'écraser.
- Le drapeau ne porte AUCUN métacaractère du shell. CPPFLAGS atteint aussi
  chaque paquet bâti par autotools, dont les Makefiles le recopient sans
  guillemets dans une commande shell : la forme fonction d'un -D, avec ses
  parenthèses, y casse libsodium, que pynacl compile là où PyPI n'a pas de
  roue.
"""

import os
import re
import shlex
import shutil
import subprocess
import sysconfig
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/install/install_locally.sh"
SOURCE = SCRIPT.read_text(encoding="utf-8")
ENTETE = RACINE / "script/install/swig_compat.h"

# Le drapeau tel que l'écrit l'image, avant expansion de PWD : sa racine est
# un chemin fixe, sans espace.
DRAPEAU = "-include ${PWD}/script/install/swig_compat.h"

# Le bloc du script qui bâtit CPPFLAGS, de la variable à l'export : exécuté
# tel quel par les tests plutôt que recopié.
BLOC = re.search(
    r"^\s*swig_compat=.*?^\s*export CPPFLAGS=[^\n]*$", SOURCE, re.S | re.M
)

# La ligne que SWIG <= 4.2 plaçait lui-même dans le wrapper généré.
SWIG_42 = "#define PyInt_FromLong(x) PyLong_FromLong(x)"

# Ce que produit SWIG >= 4.3 : l'appel, sans l'alias.
APPEL_SWIG_43 = """
#include <Python.h>
PyObject *sonde(long v) { return PyInt_FromLong(v); }
"""

# Forme d'une règle de Makefile autotools : $(CPPFLAGS) recopié tel quel dans
# la commande que make confie au shell.
MAKEFILE_AUTOTOOLS = "all:\n\t@echo CC $(CPPFLAGS) sonde.lo\n"

# La même règle, qui demande au préprocesseur de LIRE l'en-tête désigné.
MAKEFILE_CPP = "all:\n\t@cc -E $(CPPFLAGS) -x c /dev/null > /dev/null\n"


def _drapeau_developpe():
    """Le drapeau tel que le shell le développe depuis la racine du dépôt."""
    return ["-include", str(ENTETE)]


def _cppflags(racine, depart=""):
    """CPPFLAGS tel que le bloc du script le bâtit depuis `racine`."""
    res = subprocess.run(
        [
            "bash",
            "-c",
            'cd "$1"; export CPPFLAGS="$2"; '
            + BLOC.group(0)
            + '\nprintf %s "$CPPFLAGS"',
            "bash",
            str(racine),
            depart,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return res.stdout


def _make(makefile, cppflags):
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "Makefile").write_text(makefile, encoding="utf-8")
        return subprocess.run(
            ["make", "-s", "-C", tmp, f"CPPFLAGS={cppflags}"],
            # Message du shell en anglais, quelle que soit la locale.
            env={**os.environ, "LC_ALL": "C"},
            capture_output=True,
            text=True,
            timeout=30,
        )


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
            [
                _compilateur(),
                "-fsyntax-only",
                *drapeaux,
                "-I",
                inc,
                str(fichier),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    return res.returncode == 0, res.stdout + res.stderr


class TestLeDrapeauDansLeScript(unittest.TestCase):
    def test_it_is_exported(self):
        self.assertIsNotNone(BLOC, "bloc swig_compat= ... export introuvable")
        self.assertIn(
            'swig_compat="${PWD}/script/install/swig_compat.h"', BLOC.group(0)
        )
        self.assertIn(
            'export CPPFLAGS="${CPPFLAGS:+${CPPFLAGS} }-include ${swig_compat}"',
            BLOC.group(0),
        )

    def test_the_header_exists(self):
        self.assertTrue(ENTETE.is_file(), ENTETE)

    def test_it_is_set_before_poetry_install(self):
        """Posé après, il n'atteindrait rien : c'est « poetry install » qui
        lance les compilations."""
        export = SOURCE.index("export CPPFLAGS=")
        install = SOURCE.index("install --no-root ${POETRY_VERBOSE}")
        self.assertLess(export, install)

    def test_it_appends_instead_of_replacing(self):
        """Écraser CPPFLAGS jetterait ce que l'appelant y avait mis — sur
        s390x et openSUSE, des chemins d'en-têtes y passent."""
        self.assertIn("${CPPFLAGS:+${CPPFLAGS} }", SOURCE)

    def test_it_is_cppflags_and_not_cflags(self):
        """Le fichier fautif est un .cpp, et CFLAGS ne va qu'aux .c."""
        self.assertNotIn("export CFLAGS=", SOURCE)

    def test_no_function_like_define_left(self):
        """La forme -DNOM(x)=... est celle qui casse autotools."""
        self.assertIsNone(re.search(r"-D\w+\(", SOURCE))

    def test_the_shell_builds_the_value_it_claims(self):
        attendu = f"-include {ENTETE}"
        for depart, prefixe in (("", ""), ("-DDEJA=1", "-DDEJA=1 ")):
            self.assertEqual(prefixe + attendu, _cppflags(RACINE, depart))

    def test_a_path_with_a_space_stays_one_word(self):
        """Découpé comme le font setuptools et le shell d'un Makefile, le
        chemin doit rester un seul argument."""
        with tempfile.TemporaryDirectory(suffix=" a b") as tmp:
            mots = shlex.split(_cppflags(tmp))
        self.assertEqual(
            ["-include", f"{tmp}/script/install/swig_compat.h"], mots
        )

    def test_the_script_still_parses(self):
        res = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(0, res.returncode, res.stderr)


class TestLEnTete(unittest.TestCase):
    def test_it_carries_the_swig_42_definition(self):
        self.assertIn(SWIG_42, ENTETE.read_text(encoding="utf-8"))

    def test_it_is_guarded(self):
        """Gardé par #ifndef : un alias déjà posé par l'appelant prime."""
        self.assertIn(
            "#ifndef PyInt_FromLong", ENTETE.read_text(encoding="utf-8")
        )


@unittest.skipUnless(shutil.which("make"), "make absent")
class TestAutotools(unittest.TestCase):
    """Une règle de Makefile recopie CPPFLAGS sans guillemets dans le shell.

    C'est par là que pynacl casse : sur une architecture sans roue, il
    compile libsodium par configure et make."""

    def test_a_function_like_define_breaks_the_recipe(self):
        """Sans quoi le test suivant ne prouverait rien. « Syntax error »
        chez dash, le /bin/sh de Debian, « syntax error » chez bash."""
        res = _make(
            MAKEFILE_AUTOTOOLS, "-DPyInt_FromLong(x)=PyLong_FromLong(x)"
        )
        self.assertNotEqual(0, res.returncode)
        self.assertIn("syntax error", res.stderr.lower())

    def test_the_include_survives_the_recipe(self):
        res = _make(MAKEFILE_AUTOTOOLS, _cppflags(RACINE))
        self.assertEqual(0, res.returncode, res.stderr)

    @unittest.skipUnless(shutil.which("cc"), "aucun compilateur C")
    def test_the_header_is_read_through_a_path_with_a_space(self):
        """Le préprocesseur, lancé par la règle, trouve l'en-tête même quand
        la racine du dépôt porte une espace."""
        with tempfile.TemporaryDirectory(suffix=" a b") as tmp:
            cible = Path(tmp, "script/install")
            cible.mkdir(parents=True)
            shutil.copy(ENTETE, cible / "swig_compat.h")
            res = _make(MAKEFILE_CPP, _cppflags(tmp))
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
        ok, sortie = _compile(APPEL_SWIG_43, _drapeau_developpe())
        if ok is None:
            self.skipTest(sortie)
        self.assertTrue(ok, sortie[-400:])

    def test_it_does_not_clash_with_an_older_swig(self):
        """Un hôte dont le SWIG écrit encore l'alias verrait, sinon, un
        avertissement de redéfinition par fichier compilé. En -Werror, ce
        serait un échec."""
        ok, sortie = _compile(
            SWIG_42 + APPEL_SWIG_43, ["-Werror", *_drapeau_developpe()]
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


class TestLeDrapeauDansLImage(unittest.TestCase):
    """L'image Docker lance son propre « poetry install », hors de
    install_locally.sh : sans le même drapeau, les images d'Odoo 14, 15 et 17
    meurent sur le même PyInt_FromLong que l'hôte a déjà guéri."""

    DOCKERFILE = RACINE / "docker/Dockerfile.prod.pkg"

    def test_l_image_porte_le_drapeau(self):
        self.assertIn(DRAPEAU, self.DOCKERFILE.read_text(encoding="utf-8"))

    def test_l_image_n_a_plus_de_define_a_parentheses(self):
        texte = self.DOCKERFILE.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"-D\w+\(", texte))

    def test_il_precede_poetry_install_dans_la_meme_commande(self):
        """Posé dans une autre couche RUN, il n'atteindrait pas Poetry. Et
        PWD n'y est la racine du dépôt qu'après le « cd » de cette couche."""
        texte = self.DOCKERFILE.read_text(encoding="utf-8")
        ligne = texte.index(DRAPEAU)
        install = texte.index("poetry install", ligne)
        self.assertNotIn("\nRUN ", texte[ligne:install])
        debut = texte.rindex("\nRUN ", 0, ligne)
        self.assertIn("cd $ODOO_PREFIX", texte[debut:ligne])


if __name__ == "__main__":
    unittest.main(verbosity=1)
