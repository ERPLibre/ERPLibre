#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce que l'outillage importe doit être déclaré, pas seulement installé.

Un paquet peut vivre dans `.venv.erplibre` sans figurer nulle part : arrivé
par la dépendance d'un autre, ou posé à la main un jour. Rien ne le réclame,
donc rien ne le réinstalle — il disparaît au prochain venv neuf, et l'outil
qui s'en servait tombe chez le suivant, pas chez celui qui l'a écrit.

Le fichier porte déjà ce raisonnement en commentaire pour lxml. Ce test le
rend vérifiable au lieu de le laisser à la vigilance.

Portée : le venv d'OUTILS. Les venvs Odoo ont leurs propres requirements, et
psycopg2 y est déclaré parce qu'Odoo en a besoin — l'outillage, lui, parle à
PostgreSQL par psql en sous-processus.
"""

import ast
import glob
import os
import re
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(REPO, "requirement", "erplibre_require-ments.txt")

PATTERNS = (
    "script/*.py",
    "script/analyse/*.py",
    "script/analyse/*/*.py",
    "script/odoo/migration/*.py",
    "script/todo/*.py",
)

# Ce que l'on écrit pour importer n'est pas ce que l'on écrit pour installer.
# La table est explicite : un nouveau décalage doit être ajouté ici en
# connaissance de cause, plutôt que d'être toléré par une correspondance
# approximative qui laisserait passer une vraie absence.
PACKAGE_OF_MODULE = {
    "dotenv": "python-dotenv",
}

# Modules fournis par l'environnement, jamais par ce fichier.
PROVIDED_ELSEWHERE = {
    # Le venv Odoo, pas celui des outils : ces scripts tournent sous
    # `odoo-bin shell`, qui apporte son propre interpréteur.
    "odoo",
}


def tooling_files():
    return sorted(
        {p for m in PATTERNS for p in glob.glob(os.path.join(REPO, m))}
    )


def third_party_imports():
    """{module: {fichiers qui l'importent}}, hors stdlib et hors modules locaux."""
    files = tooling_files()
    local = {os.path.basename(p)[:-3] for p in files}
    found = {}
    for path in files:
        with open(path) as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and not node.level
            ):
                names = [node.module.split(".")[0]]
            for name in names:
                if (
                    name in sys.stdlib_module_names
                    or name in local
                    or name in PROVIDED_ELSEWHERE
                    or name == "script"
                ):
                    continue
                found.setdefault(name, set()).add(os.path.relpath(path, REPO))
    return found


def declared():
    with open(REQUIREMENTS) as handle:
        return handle.read()


class TestEveryImportIsDeclared(unittest.TestCase):
    def test_the_scan_finds_something(self):
        # Un test qui n'inspecte rien passe toujours.
        self.assertGreater(len(tooling_files()), 20)
        self.assertGreater(len(third_party_imports()), 5)

    def test_no_third_party_import_is_undeclared(self):
        text = declared()
        missing = []
        for module, users in sorted(third_party_imports().items()):
            package = PACKAGE_OF_MODULE.get(module, module)
            # En début de ligne : « lxml » ne doit pas être satisfait par
            # une mention en commentaire ni par « python-lxml-stubs ».
            if not re.search(
                rf"^\s*{re.escape(package)}\b", text, re.M | re.I
            ):
                missing.append(f"{module} ({package}) <- {sorted(users)[0]}")
        self.assertEqual(missing, [])

    def test_the_alias_table_has_no_dead_entry(self):
        # Une correspondance qui ne sert plus masque le jour où le module
        # revient sous un autre nom.
        imported = set(third_party_imports())
        for module in PACKAGE_OF_MODULE:
            with self.subTest(module=module):
                self.assertIn(module, imported)

    def test_the_check_would_notice_a_removal(self):
        # La preuve que la recherche mord : un paquet réellement déclaré,
        # retiré du texte, doit être vu comme manquant.
        # `assertRegex` cherche SANS re.M : « ^ » n'y vaut qu'au tout début
        # de la chaîne, et la vérification ci-dessus, elle, lit ligne à ligne.
        # Un motif compilé fait dire au test la même chose qu'au code.
        motif = re.compile(r"^\s*lxml\b", re.M)
        text = declared()
        self.assertRegex(text, motif)
        without = motif.sub("", text)
        self.assertNotRegex(without, motif)


class TestPsycopg2StaysOutOfTheToolingVenv(unittest.TestCase):
    """Décision prise, et la raison avec — sinon elle se reprend à l'aveugle.

    Les outils d'analyse interrogent PostgreSQL par `psql` en sous-processus :
    un choix délibéré, qui porte la garantie de lecture seule côté serveur
    (PGOPTIONS). Déclarer psycopg2 ici ferait compiler une extension C à
    chaque installation neuve, sans que rien ne l'importe.
    """

    def test_nothing_in_the_tooling_imports_psycopg2(self):
        self.assertNotIn("psycopg2", third_party_imports())

    def test_the_analysis_tools_query_through_psql(self):
        path = os.path.join(REPO, "script", "analyse", "lib_analyse.py")
        with open(path) as handle:
            source = handle.read()
        self.assertIn('"psql"', source)
        self.assertIn("default_transaction_read_only=on", source)


if __name__ == "__main__":
    unittest.main()
