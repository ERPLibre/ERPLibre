#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les outils de production se lancent aussi sous le python3 d'un serveur,
d'une image Docker ou d'un hôte Proxmox : rien au-delà de Python 3.7.

Un seul garde pour tous ces fichiers. Il lit chaque source sans
l'importer : la syntaxe par `ast.parse(feature_version=(3, 7))`, les
f-strings imbriquées de PEP 701 que ce parse laisse passer, et une liste
d'API qui se lisent en 3.7 mais lèvent une erreur à l'appel. La liste des
fichiers est aussi celle de `per-file-target-version` dans `.ruff.toml` :
sans elle, `make format` récrirait ces fichiers en syntaxe py310.
"""

import ast
import glob
import io
import os
import re
import tokenize
import unittest

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

# Les programmes, chemins relatifs à la racine du dépôt ; s'y ajoutent
# toutes les bibliothèques de script/lib_ops/, qu'ils importent.
PROGRAMMES = (
    "script/proxmox/host_perf_audit.py",
    "script/odoo/update_module.py",
    "script/odoo/log_check.py",
    "script/odoo/mail_retry.py",
    "script/odoo/health_check.py",
    "script/odoo/warmup_http.py",
    "script/database/odoo_backup.py",
    "script/systemd/install_backup_timer.py",
)
LIB_OPS = "script/lib_ops/*.py"

# Les programmes qui se lancent par leur nom : un shebang et le bit x.
EXECUTABLES = (
    "script/proxmox/host_perf_audit.py",
    "script/odoo/update_module.py",
    "script/odoo/log_check.py",
    "script/odoo/mail_retry.py",
    "script/odoo/health_check.py",
    "script/database/odoo_backup.py",
    "script/systemd/install_backup_timer.py",
)

# API absentes de Python 3.7, ou trop limitées : la syntaxe passe le garde,
# l'appel échoue à l'exécution. fromisoformat existe en 3.7 mais n'y lit
# qu'une partie de l'ISO 8601.
API_RECENTES = (
    "shlex.join",
    ".removeprefix(",
    ".removesuffix(",
    "fromisocalendar",
    "fromisoformat",
    "dirs_exist_ok",
    "math.dist(",
    "math.prod",
    "BooleanOptionalAction",
    "cached_property",
    "zoneinfo",
    "importlib.metadata",
)

# functools.cache (3.9) s'écrit surtout en décorateur nu, sans parenthèse ;
# la frontière de mot écarte cached_property et lru_cache, déjà couverts
# ou présents en 3.7.
API_RECENTES_MOTIFS = (
    re.compile(r"\bfunctools\.cache\b"),
    re.compile(r"^\s*from\s+functools\s+import\s[^\n]*\bcache\b", re.M),
)

# « f"{x=}" » date de 3.8 et passe pourtant ast.parse(feature_version=(3, 7)).
FSTRING_EGAL = re.compile(r"""f["'][^"'\n]*\{[^}]*=\}""")


def fichiers():
    """Les chemins relatifs du garde, programmes puis lib_ops, triés."""
    libs = sorted(
        os.path.relpath(p, RACINE)
        for p in glob.glob(os.path.join(RACINE, LIB_OPS))
    )
    return list(PROGRAMMES) + libs


def lire(relatif):
    with open(os.path.join(RACINE, relatif), encoding="utf-8") as f:
        return f.read()


def imbrications_pep701(source):
    """Positions des chaînes imbriquées dans une f-string avec le même
    guillemet — légal seulement depuis Python 3.12 (PEP 701). Rend [] sur
    un tokenizer antérieur à 3.12, qui ne découpe pas les f-strings."""
    fautes = []
    pile = []
    debut_f = getattr(tokenize, "FSTRING_START", None)
    fin_f = getattr(tokenize, "FSTRING_END", None)
    if debut_f is None:
        return fautes
    for jeton in tokenize.generate_tokens(io.StringIO(source).readline):
        if jeton.type in (debut_f, tokenize.STRING):
            guillemet = jeton.string.lstrip("rRbBuUfF")
            if pile and any(guillemet.startswith(g) for g in pile):
                fautes.append(jeton.start)
            if jeton.type == debut_f:
                pile.append(guillemet)
        elif jeton.type == fin_f:
            pile.pop()
    return fautes


class TestPython37(unittest.TestCase):
    def test_le_garde_lit_bien_ses_fichiers(self):
        """Un glob vide ou un chemin renommé laisserait passer tout."""
        tous = fichiers()
        self.assertGreater(len(tous), len(PROGRAMMES) + 5)
        for relatif in tous:
            with self.subTest(fichier=relatif):
                self.assertTrue(os.path.isfile(os.path.join(RACINE, relatif)))

    def test_syntaxe_37(self):
        for relatif in fichiers():
            with self.subTest(fichier=relatif):
                ast.parse(lire(relatif), feature_version=(3, 7))

    def test_le_garde_37_voit_un_morse(self):
        with self.assertRaises(SyntaxError):
            ast.parse("(x := 1)", feature_version=(3, 7))

    def test_aucune_imbrication_pep701(self):
        for relatif in fichiers():
            with self.subTest(fichier=relatif):
                self.assertEqual(imbrications_pep701(lire(relatif)), [])

    def test_le_garde_pep701_voit_une_imbrication(self):
        if not hasattr(tokenize, "FSTRING_START"):
            self.skipTest("tokenizer antérieur à 3.12")
        self.assertTrue(imbrications_pep701('x = f"{d["k"]}"\n'))
        self.assertEqual(imbrications_pep701("x = f\"{d['k']}\"\n"), [])
        self.assertEqual(imbrications_pep701('x = f"""{d["k"]}"""\n'), [])

    def test_aucune_api_posterieure_a_37(self):
        for relatif in fichiers():
            source = lire(relatif)
            for api in API_RECENTES:
                with self.subTest(fichier=relatif, api=api):
                    self.assertNotIn(api, source)
            for motif in API_RECENTES_MOTIFS:
                with self.subTest(fichier=relatif, motif=motif.pattern):
                    self.assertIsNone(motif.search(source))

    def test_le_garde_voit_functools_cache_en_decorateur(self):
        def vu(source):
            return any(m.search(source) for m in API_RECENTES_MOTIFS)

        self.assertTrue(vu("@functools.cache\ndef f():\n    pass\n"))
        self.assertTrue(vu("x = functools.cache(f)\n"))
        self.assertTrue(vu("from functools import partial, cache\n"))
        self.assertFalse(vu("@functools.lru_cache(maxsize=None)\n"))
        self.assertFalse(vu("from functools import lru_cache\n"))
        self.assertFalse(vu("@functools.cached_property\n"))

    def test_aucun_fstring_egal(self):
        for relatif in fichiers():
            with self.subTest(fichier=relatif):
                self.assertIsNone(FSTRING_EGAL.search(lire(relatif)))

    def test_le_garde_fstring_egal_voit_un_egal(self):
        self.assertTrue(FSTRING_EGAL.search('print(f"{x=}")'))
        self.assertIsNone(FSTRING_EGAL.search('print(f"{x}={y}")'))

    def test_annotations_differees(self):
        """`list[str]` dans une annotation se lit en 3.7 seulement si
        l'annotation n'est pas évaluée."""
        for relatif in fichiers():
            with self.subTest(fichier=relatif):
                self.assertIn(
                    "from __future__ import annotations", lire(relatif)
                )

    def test_executable(self):
        for relatif in EXECUTABLES:
            with self.subTest(fichier=relatif):
                chemin = os.path.join(RACINE, relatif)
                self.assertTrue(os.access(chemin, os.X_OK))
                with open(chemin, "rb") as f:
                    self.assertEqual(f.read(2), b"#!")


class TestRuffPy37(unittest.TestCase):
    """`.ruff.toml` cible py37 exactement pour les fichiers du garde."""

    def setUp(self):
        if tomllib is None:
            self.skipTest("tomllib absent avant Python 3.11")
        with open(os.path.join(RACINE, ".ruff.toml"), "rb") as f:
            self.config = tomllib.load(f)

    def test_chaque_fichier_du_garde_est_formate_en_py37(self):
        cibles = self.config.get("per-file-target-version", {})
        attendu = dict.fromkeys(PROGRAMMES + (LIB_OPS,), "py37")
        self.assertEqual(cibles, attendu)

    def test_le_reste_garde_sa_cible(self):
        self.assertEqual(self.config.get("target-version"), "py310")


if __name__ == "__main__":
    unittest.main()
