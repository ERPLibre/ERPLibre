#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La frontière entre le paquet assistant et le CLI qui s'en sert.

Le paquet doit rester importable SEUL. Importer `script.todo.todo` coûte près
d'une seconde et imprime sur la sortie : un module du paquet qui le tire fait
payer ce prix à tout ce qui l'importe, y compris aux neuf fichiers de test qui
n'en ont pas besoin, et rend la boucle d'écriture inutilisable.

**Pourquoi cette garde vit ici et non dans chaque fichier.** Elle s'écrivait
`assertNotIn("script.todo.todo", sys.modules)`, une fois par fichier de test du
paquet. Une telle affirmation ne dit quelque chose que si RIEN d'autre n'a
importé le CLI avant elle — or la découverte d'unittest importe TOUS les
modules de test avant d'en lancer un seul, et dix fichiers de test du dépôt
importent `todo` au niveau module. Les six gardes étaient donc vertes en
fichier isolé et rouges en suite complète, sans jamais rien surveiller. Une
garde dont le verdict dépend de l'ordre de découverte ne garde rien.

**Deux lectures, parce qu'aucune ne suffit seule.** La structure lit le texte
des modules et voit tout import écrit, y compris à l'intérieur d'une fonction
et sous sa forme relative — mais pas un import composé à l'exécution à partir
d'une chaîne. L'exécution importe le paquet dans un interpréteur NEUF et
regarde ce qui a atterri dans `sys.modules` — elle voit l'import dynamique et
l'import transitif, au prix d'un sous-processus.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAQUET = os.path.join(RACINE, "script", "todo", "assistant")

# Le module que le paquet ne doit pas tirer, et le préfixe de ses propres
# modules, dont les chemins relatifs se résolvent.
INTERDIT = "script.todo.todo"
PREFIXE = "script.todo.assistant"


def modules():
    """(nom pointé, chemin) de chaque module du paquet, `__init__` compris.

    Marche l'arborescence plutôt que de tenir une liste : un sous-paquet neuf
    — `agents`, `harness` — entre dans la garde sans qu'on y pense, ce qui est
    exactement ce qu'une liste tenue à la main rate.
    """
    trouves = []
    for dossier, sous, fichiers in os.walk(PAQUET):
        sous[:] = [d for d in sous if d != "__pycache__"]
        for nom in sorted(fichiers):
            if not nom.endswith(".py"):
                continue
            chemin = os.path.join(dossier, nom)
            relatif = os.path.relpath(chemin, RACINE)[: -len(".py")]
            trouves.append((relatif.replace(os.sep, "."), chemin))
    return sorted(trouves)


def _resoudre(module, noeud):
    """Le module qu'un `from … import` désigne, chemins relatifs résolus.

    `level` porte le nombre de points : `from ..todo import x` écrit dans
    `script.todo.assistant.gpt` remonte de deux crans et désigne
    `script.todo.todo`. Sans cette résolution, la forme relative passerait.
    """
    if not noeud.level:
        return noeud.module or ""
    morceaux = module.split(".")[: -noeud.level]
    if noeud.module:
        morceaux.append(noeud.module)
    return ".".join(morceaux)


def importe_interdit(module, source):
    """Les formes par lesquelles `source` importe le CLI. Fonction PURE.

    Quatre formes comptent, et trois se ressemblent assez pour qu'une seule
    oubliée rende la garde muette : `import script.todo.todo`,
    `from script.todo.todo import x`, `from script.todo import todo` — qui
    importe le module sans jamais le nommer en entier — et la forme relative.
    """
    tete, _, feuille = INTERDIT.rpartition(".")
    fautes = []
    for noeud in ast.walk(ast.parse(source)):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                if alias.name == INTERDIT or alias.name.startswith(
                    INTERDIT + "."
                ):
                    fautes.append(
                        f"ligne {noeud.lineno} : import {alias.name}"
                    )
        elif isinstance(noeud, ast.ImportFrom):
            cible = _resoudre(module, noeud)
            if cible == INTERDIT or cible.startswith(INTERDIT + "."):
                fautes.append(f"ligne {noeud.lineno} : from {cible} import …")
            elif cible == tete:
                for alias in noeud.names:
                    if alias.name == feuille:
                        fautes.append(
                            f"ligne {noeud.lineno} : from {cible}"
                            f" import {feuille}"
                        )
    return fautes


class TestLaFrontiereDansLeTexte(unittest.TestCase):
    """Ce que les modules ÉCRIVENT. Instantané, et sans ordre à respecter."""

    def test_the_package_has_modules_to_check(self):
        """Une garde qui ne regarde rien passe toujours."""
        self.assertGreater(len(modules()), 10)

    def test_no_module_of_the_package_imports_the_cli(self):
        fautes = {}
        for module, chemin in modules():
            with open(chemin, encoding="utf-8") as fh:
                trouve = importe_interdit(module, fh.read())
            if trouve:
                fautes[module] = trouve
        self.assertEqual(fautes, {})

    def test_the_reader_sees_each_form(self):
        """Un test de la garde elle-même : muette, elle passerait partout.

        Les quatre formes sont écrites ici parce qu'une seule oubliée dans le
        lecteur laisserait passer les trois autres sans que rien ne baisse.
        """
        for source in (
            "import script.todo.todo",
            "import script.todo.todo as cli",
            "from script.todo.todo import TODO",
            "from script.todo import todo",
            "def f():\n    from script.todo.todo import TODO\n",
            "from ..todo import TODO",
        ):
            self.assertTrue(
                importe_interdit(f"{PREFIXE}.un_module", source), source
            )

    def test_the_reader_does_not_cry_wolf(self):
        """Le paquet importe ses propres voisins, et `todo_i18n` est du CLI
        sans être le CLI : le confondre condamnerait chaque module traduit."""
        for source in (
            "from script.todo.todo_i18n import t",
            "from script.todo.assistant import servers",
            "from script.todo import todo_prefs",
            "from . import journal",
            "import os",
        ):
            self.assertEqual(
                importe_interdit(f"{PREFIXE}.un_module", source), [], source
            )


class TestLaFrontiereALExecution(unittest.TestCase):
    """Ce que les modules FONT, dans un interpréteur neuf.

    Un seul sous-processus importe tout le paquet : c'est ce qui attrape
    l'import composé à partir d'une chaîne et l'import transitif, que la
    lecture du texte ne voit pas.
    """

    @classmethod
    def setUpClass(cls):
        noms = [m for m, _ in modules() if not m.endswith(".__init__")]
        programme = (
            "import importlib, sys\n"
            f"noms = {noms!r}\n"
            "rates = []\n"
            "for nom in noms:\n"
            "    try:\n"
            "        importlib.import_module(nom)\n"
            "    except Exception as souci:\n"
            "        rates.append('%s : %r' % (nom, souci))\n"
            f"tire = {INTERDIT!r} in sys.modules\n"
            "print(int(tire))\n"
            "print('\\n'.join(rates))\n"
        )
        cls.noms = noms
        cls.fini = subprocess.run(
            [sys.executable, "-c", programme],
            cwd=RACINE,
            text=True,
            capture_output=True,
        )

    def test_the_subprocess_ran(self):
        self.assertEqual(self.fini.returncode, 0, self.fini.stderr[-800:])
        self.assertTrue(self.noms)

    def test_every_module_imports_on_its_own(self):
        """Un module qui ne s'importe pas rendrait la garde suivante vide."""
        rates = self.fini.stdout.splitlines()[1:]
        self.assertEqual([r for r in rates if r.strip()], [])

    def test_importing_the_whole_package_does_not_pull_the_cli(self):
        self.assertEqual(
            self.fini.stdout.splitlines()[0],
            "0",
            f"{INTERDIT} importé par le paquet",
        )


if __name__ == "__main__":
    unittest.main()
