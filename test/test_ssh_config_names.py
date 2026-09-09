#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'est un nom de machine dans ~/.ssh/config, et pourquoi c'est partagé.

Trois lecteurs de ce fichier vivent dans ce dépôt, et ils tranchaient la même
question autrement : l'un comparait le mot-clé avec la casse, un autre
exigeait un espace là où une tabulation est légale, un troisième laissait
passer le motif nié. Une découverte voyait donc un alias que le menu de
montage ne voyait pas, ce qui se lit comme une panne intermittente et non
comme trois filtres différents.

Ces tests portent sur la décision elle-même, puis sur le fait que les trois
lecteurs la partagent — cette dernière assertion est ce qui empêche qu'un
quatrième filtre se réinstalle en douce.

Les alias sont inventés : `ssh_config` ne résout rien et ne touche aucun
fichier, donc aucun nom réel n'est nécessaire ici.
"""

import unittest

from script.todo import ssh_config as sc


class TestCeQuiEstUneDeclaration(unittest.TestCase):
    def test_a_plain_host_line(self):
        self.assertEqual(sc.declared_names("Host alpha"), ["alpha"])

    def test_lowercase_keyword(self):
        """ssh_config ne distingue pas la casse de ses mots-clés."""
        self.assertEqual(sc.declared_names("host alpha"), ["alpha"])

    def test_uppercase_keyword(self):
        self.assertEqual(sc.declared_names("HOST alpha"), ["alpha"])

    def test_tab_separator(self):
        """Une tabulation sépare aussi légalement qu'un espace."""
        self.assertEqual(sc.declared_names("Host\talpha"), ["alpha"])

    def test_indented_declaration(self):
        self.assertEqual(sc.declared_names("    Host alpha"), ["alpha"])

    def test_several_names_on_one_line(self):
        self.assertEqual(
            sc.declared_names("Host alpha beta gamma"),
            ["alpha", "beta", "gamma"],
        )

    def test_hostname_is_not_a_declaration(self):
        """Le blanc exigé derrière le mot-clé est ce qui sépare les deux."""
        self.assertIsNone(sc.declared_names("    HostName 10.83.4.19"))

    def test_another_directive_is_not_a_declaration(self):
        self.assertIsNone(sc.declared_names("    User quelquun"))

    def test_an_empty_line_is_not_a_declaration(self):
        self.assertIsNone(sc.declared_names(""))
        self.assertIsNone(sc.declared_names(None))


class TestCeQuiNeDesigneAucuneMachine(unittest.TestCase):
    def test_a_wildcard_is_a_rule(self):
        self.assertEqual(sc.declared_names("Host *"), [])

    def test_a_partial_wildcard_is_a_rule(self):
        self.assertEqual(sc.declared_names("Host web-*"), [])

    def test_a_single_char_wildcard_is_a_rule(self):
        self.assertEqual(sc.declared_names("Host web-?"), [])

    def test_a_negated_pattern_is_removed(self):
        """`!nom` RETIRE un nom : le retenir donne une cible en « ! »."""
        self.assertEqual(sc.declared_names("Host alpha !beta"), ["alpha"])

    def test_only_a_negation_declares_nothing(self):
        self.assertEqual(sc.declared_names("Host !beta"), [])

    def test_a_declaration_naming_nothing_is_still_a_declaration(self):
        """None et [] ne veulent pas dire la même chose.

        `Host *` EST une déclaration : le lecteur qui accumule un bloc doit
        clore le précédent, sinon les directives du bloc générique se
        rattachent au bloc d'avant."""
        self.assertIsNotNone(sc.declared_names("Host *"))
        self.assertIsNone(sc.declared_names("Compression yes"))


class TestLesTroisLecteursPartagentLaDecision(unittest.TestCase):
    """Les assertions qui empêchent un quatrième filtre de se réinstaller.

    Elles comptent les APPELS à la décision partagée, lus dans l'arbre
    syntaxique : un lecteur qui recompile son propre motif cesse d'appeler,
    et le compte tombe. Compter dans le texte accuserait le bon code, une
    docstring qui nomme la fonction n'étant pas un appel."""

    def _source(self, chemin):
        from pathlib import Path

        racine = Path(__file__).resolve().parents[1]
        return (racine / chemin).read_text(encoding="utf-8")

    def _appels(self, chemin):
        """Le nombre d'APPELS à la décision partagée, lus dans l'arbre.

        Compté sur l'arbre et non dans le texte : une docstring qui NOMME la
        fonction n'est pas un appel, et une assertion sur le texte compterait
        les deux."""
        import ast

        arbre = ast.parse(self._source(chemin))
        return sum(
            1
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "declared_names"
        )

    def test_qemu_manage_delegates(self):
        self.assertEqual(self._appels("script/todo/qemu_manage.py"), 1)

    def test_todo_delegates_twice(self):
        """Les DEUX lecteurs de todo.py, pas seulement celui qu'on a corrigé."""
        self.assertEqual(self._appels("script/todo/todo.py"), 2)

    def test_parse_ssh_blocks_sees_a_lowercase_alias(self):
        """Le bout de bout : la forme qui échappait aux trois."""
        from script.todo.qemu_manage import parse_ssh_blocks

        blocs = parse_ssh_blocks("host alpha\n\tHostName 10.83.4.19\n")
        self.assertIn("alpha", blocs)
        self.assertEqual(blocs["alpha"]["hostname"], "10.83.4.19")

    def test_parse_ssh_blocks_drops_a_negation(self):
        from script.todo.qemu_manage import parse_ssh_blocks

        blocs = parse_ssh_blocks("Host alpha !beta\n\tUser quelquun\n")
        self.assertIn("alpha", blocs)
        self.assertNotIn("!beta", blocs)


if __name__ == "__main__":
    unittest.main()
