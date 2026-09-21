#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le nom du venv Odoo se LIT, il ne se compose pas de tête.

Il porte le COUPLE Odoo/Python — « .venv.odoo18.0_python3.12.10 » — et la
moitié Python bouge : le catalogue en porte déjà deux valeurs distinctes
pour les versions vivantes. Une commande qui écrit ce nom en littéral vise
donc un interpréteur que la prochaine montée renomme.

CE QUI REND LA PANNE MUETTE : la commande fautive tourne sous « parallel »,
où l'échec de chaque branche se noie dans la sortie, et l'appelant enchaîne.
On ne saurait ni que rien n'a migré, ni pourquoi.

Le CLAUDE.md du dépôt interdit nommément ce geste — « le retrouver par
ls -d .venv.odoo* plutôt que de le composer de tête ». Ces épreuves le
tiennent pour le code, là où la consigne ne tenait que pour les humains.
"""

import ast
import io
import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.todo.version_manager import (  # noqa: E402
    get_odoo_version,
    get_venv_python,
)


class TestLeNomVientDuCatalogue(unittest.TestCase):
    def test_every_catalogued_version_yields_its_own_interpreter(self):
        """Chaque version connue rend un chemin, et deux versions ne
        partagent pas le même : c'est tout l'objet du couple."""
        versions, _i, _c = get_odoo_version()
        rendus = {
            e["odoo_version"]: get_venv_python(e["odoo_version"])
            for e in versions
            if e.get("odoo_version")
        }
        self.assertTrue(rendus)
        for version, chemin in rendus.items():
            with self.subTest(version=version):
                self.assertTrue(chemin.startswith(".venv.odoo"))
                self.assertTrue(chemin.endswith("/bin/python"))
                self.assertIn(version, chemin)

    def test_the_python_half_is_the_one_the_catalogue_names(self):
        """LA MOITIÉ QUI BOUGE. C'est elle qu'un littéral fige, et le
        catalogue en porte déjà deux valeurs pour les versions vivantes."""
        versions, _i, _c = get_odoo_version()
        for entree in versions:
            version = entree.get("odoo_version")
            if not version:
                continue
            with self.subTest(version=version):
                self.assertIn(
                    entree["python_version"], get_venv_python(version)
                )

    def test_an_unknown_version_is_refused_rather_than_composed(self):
        """Un venv inventé échoue dans le shell, où le message ne dit pas
        d'où vient le nom."""
        with self.assertRaises(Exception) as vu:
            get_venv_python("99.0")
        self.assertIn("99.0", str(vu.exception))


class TestAucuneCommandeNeLeCompose(unittest.TestCase):
    """La consigne du dépôt, tenue par une épreuve et non par la mémoire.

    Un littéral « .venv.odoo<version>_python<version> » dans du CODE fige le
    couple. En PROSE il décrit une recette qu'un humain adaptera, et c'est
    autre chose : l'épreuve ne regarde donc que les chaînes du code.
    """

    FICHIERS = (
        os.path.join("script", "todo", "todo_upgrade.py"),
        os.path.join("script", "todo", "todo.py"),
        os.path.join("script", "todo", "version_manager.py"),
    )

    @staticmethod
    def litteraux(chemin):
        """Les chaînes du CODE qui nomment un venv Odoo, docstrings et
        commentaires exclus — l'analyseur ne rend que les vraies chaînes."""
        with io.open(os.path.join(RACINE, chemin), encoding="utf-8") as fh:
            arbre = ast.parse(fh.read())
        # Les docstrings sont des chaînes comme les autres pour l'analyseur :
        # les écarter demande de les NOMMER, une par porteur. Sans cela
        # l'épreuve attrape la prose qui décrit la forme, et l'on croit à un
        # littéral fautif là où il n'y a qu'une explication.
        proses = set()
        for noeud in ast.walk(arbre):
            if isinstance(
                noeud,
                (
                    ast.Module,
                    ast.ClassDef,
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            ):
                corps = getattr(noeud, "body", None) or []
                if (
                    corps
                    and isinstance(corps[0], ast.Expr)
                    and isinstance(corps[0].value, ast.Constant)
                    and isinstance(corps[0].value.value, str)
                ):
                    proses.add(id(corps[0].value))
        return [
            n.value
            for n in ast.walk(arbre)
            if isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and ".venv.odoo" in n.value
            and id(n) not in proses
        ]

    def test_no_command_writes_the_couple_by_hand(self):
        for chemin in self.FICHIERS:
            with self.subTest(fichier=chemin):
                self.assertEqual([], self.litteraux(chemin))

    def test_the_sweep_reads_what_it_claims(self):
        """Contrôle du banc : un chemin fautif rendrait zéro littéral, et
        l'épreuve passerait sans avoir rien lu."""
        source = io.open(
            os.path.join(RACINE, self.FICHIERS[0]), encoding="utf-8"
        ).read()
        self.assertIn("get_venv_python", source)


if __name__ == "__main__":
    unittest.main()
