#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lire ce que le moteur imprime de ses écosystèmes, sans jamais deviner.

Le moteur n'offre pas de `--json` : il imprime un tableau fait pour un
humain. Un adaptateur qui devine y gagne des lignes fausses, et le nom qu'il
lit sert à BASCULER l'écosystème actif — se tromper de nom, c'est basculer
vers autre chose.

DEUX ERREURS, ET LA SECONDE COÛTE PLUS CHER. Refuser une sortie valide
oblige à tout faire à la main ; accepter une sortie qu'on lit mal fait agir
sur la mauvaise cible. D'où : forme inattendue → `None`, jamais une liste
partielle. Les refus sont donc éprouvés un par un, et le contrôle positif —
lire une vraie sortie — vaut autant qu'eux.

Le tableau ci-dessous a la forme exacte de ce que le moteur imprime ; ses
noms sont inventés et n'existent nulle part ailleurs dans le dépôt.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.setops import ecosystems as E  # noqa: E402

TABLEAU = (
    "  INSTANCE               INDEX  VLAN        FEDERE  PROD \n"
    "  OPS-Fictif-Dolomie         7  1071-1079   oui     ?    \n"
    "* OPS-Fictif-Ankerite       12  —           LOCAL   non  \n"
    "\n"
    "* = instance active (symlink 'instance')."
    "  Basculer : make instance-utiliser NOM=<depot>\n"
)

VIDE = (
    "Aucune instance decouverte (depots freres avec plan/nomenclature.yml).\n"
)

MODELES = (
    "  socle\n  integral\n\n"
    "Index fédérés déjà pris : [7] (choisir un index libre).\n"
)


class TestLeTableau(unittest.TestCase):
    def test_a_real_table_is_read_line_by_line(self):
        """Le contrôle positif : sans lui, un adaptateur qui refuse tout
        passerait chacun des refus éprouvés plus bas."""
        lus = E.lit_instances(TABLEAU)
        self.assertEqual(2, len(lus))
        self.assertEqual(
            E.Ecosysteme(
                nom="OPS-Fictif-Dolomie",
                index=7,
                vlans="1071-1079",
                federe=True,
                production=None,
                actif=False,
            ),
            lus[0],
        )

    def test_the_marker_says_which_one_is_mounted(self):
        """C'est la seule chose qui distingue l'écosystème actif, et elle
        tient à une colonne qu'un découpage par blancs perdrait."""
        lus = E.lit_instances(TABLEAU)
        self.assertEqual([False, True], [e.actif for e in lus])

    def test_the_words_of_the_columns_are_translated_to_values(self):
        lus = E.lit_instances(TABLEAU)
        self.assertEqual([True, False], [e.federe for e in lus])
        self.assertEqual([None, False], [e.production for e in lus])

    def test_no_ecosystem_is_empty_and_not_unknown(self):
        """« Rien à monter, en créer un » et « forme illisible » sont deux
        nouvelles différentes : la première appelle une création, la seconde
        une lecture à la main."""
        self.assertEqual((), E.lit_instances(VIDE))


class TestCeQuIlRefuse(unittest.TestCase):
    def sans_entete(self):
        return "\n".join(TABLEAU.splitlines()[1:])

    def test_a_table_without_its_header_is_unknown(self):
        self.assertIsNone(E.lit_instances(self.sans_entete()))

    def test_a_header_without_a_single_row_is_unknown(self):
        """Le moteur dit « aucune instance » par une phrase, jamais par un
        tableau vide : un tableau vide est donc une autre sortie."""
        entete = TABLEAU.splitlines()[0]
        self.assertIsNone(E.lit_instances(entete + "\n"))

    def test_a_row_with_a_missing_field_is_unknown(self):
        ampute = TABLEAU.replace(
            "  OPS-Fictif-Dolomie         7", "  OPS-Fictif-Dolomie"
        )
        self.assertIsNone(E.lit_instances(ampute))

    def test_a_row_with_an_extra_field_is_unknown(self):
        enfle = TABLEAU.replace("oui     ?    ", "oui     ?    encore")
        self.assertIsNone(E.lit_instances(enfle))

    def test_an_unknown_word_in_a_column_is_unknown(self):
        """Une colonne qui gagne une valeur est un changement du moteur :
        la traduire au jugé inventerait un état."""
        for avant, apres in (
            ("oui     ?    ", "peut-etre ?  "),
            ("LOCAL   non  ", "LOCAL   parfois"),
        ):
            with self.subTest(colonne=apres.strip()):
                self.assertIsNone(
                    E.lit_instances(TABLEAU.replace(avant, apres))
                )

    def test_a_non_numeric_index_is_unknown(self):
        self.assertIsNone(
            E.lit_instances(TABLEAU.replace("       7  ", "       X  "))
        )

    def test_a_row_that_starts_in_the_first_column_is_unknown(self):
        """La première colonne porte le marqueur : un nom qui y commence
        n'est pas une ligne du tableau."""
        colle = TABLEAU.replace("  OPS-Fictif-Dolomie", "OPS-Fictif-Dolomie ")
        self.assertIsNone(E.lit_instances(colle))

    def test_nothing_at_all_is_unknown(self):
        self.assertIsNone(E.lit_instances(""))
        self.assertIsNone(E.lit_instances(None))


class TestLEcosystemeMonte(unittest.TestCase):
    def test_a_mounted_one_gives_the_name_the_switch_expects(self):
        """Le moteur écrit un chemin ; `instance-utiliser` attend un nom."""
        self.assertEqual(
            "OPS-Fictif-Dolomie",
            E.lit_courante("instance -> ../OPS-Fictif-Dolomie\n"),
        )

    def test_nothing_mounted_is_empty_and_not_unknown(self):
        self.assertEqual("", E.lit_courante("instance -> (non monté)\n"))

    def test_another_sentence_is_unknown(self):
        self.assertIsNone(E.lit_courante("tout va bien\n"))
        self.assertIsNone(E.lit_courante(""))

    def test_a_trailing_slash_does_not_make_an_empty_name(self):
        self.assertEqual(
            "OPS-Fictif-Dolomie",
            E.lit_courante("instance -> ../OPS-Fictif-Dolomie/\n"),
        )


class TestLeLienLuSurLeDisque(unittest.TestCase):
    """`monte()` ouvre chaque écran qui agit : il ne lance rien."""

    def setUp(self):
        self.moteur = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.moteur, True)
        self.lien = os.path.join(self.moteur, E.LIEN)

    def test_a_mounted_link_gives_its_name(self):
        cible = os.path.join(self.moteur, "..", "OPS-Fictif-Dolomie")
        os.makedirs(os.path.normpath(cible), exist_ok=True)
        self.addCleanup(shutil.rmtree, os.path.normpath(cible), True)
        os.symlink(cible, self.lien)
        self.assertEqual("OPS-Fictif-Dolomie", E.monte(self.moteur))

    def test_a_broken_link_keeps_its_name(self):
        """« Monté sur X, qui n'existe plus » se répare ; « rien » envoie
        chercher une panne ailleurs."""
        os.symlink(
            os.path.join(self.moteur, "..", "OPS-Fictif-Disparu"), self.lien
        )
        self.assertEqual("OPS-Fictif-Disparu", E.monte(self.moteur))

    def test_no_link_is_nothing_mounted(self):
        self.assertEqual("", E.monte(self.moteur))

    def test_a_real_folder_is_not_a_mounted_ecosystem(self):
        """Le moteur refuse de basculer quand `instance` est un vrai
        dossier : le nommer comme un écosystème monté mentirait."""
        os.makedirs(self.lien)
        self.assertEqual("", E.monte(self.moteur))

    def test_an_unreadable_engine_is_nothing_mounted(self):
        self.assertEqual("", E.monte(None))


class TestLesModeles(unittest.TestCase):
    def test_the_templates_and_the_taken_indexes_are_read(self):
        self.assertEqual((("socle", "integral"), (7,)), E.lit_modeles(MODELES))

    def test_none_taken_is_an_empty_tuple(self):
        sortie = MODELES.replace("[7]", E.AUCUN_PRIS)
        self.assertEqual((("socle", "integral"), ()), E.lit_modeles(sortie))

    def test_without_the_sentence_it_is_unknown(self):
        """La phrase est ce qui dit que la sortie est bien celle-là ; sans
        elle, les lignes indentées pourraient être n'importe quoi."""
        self.assertIsNone(E.lit_modeles("  socle\n  integral\n"))


class TestLIndexPropose(unittest.TestCase):
    """Une PROPOSITION : le moteur valide lui-même l'index qu'il reçoit."""

    def test_the_smallest_free_one_is_proposed(self):
        self.assertEqual(0, E.index_libre(()))
        self.assertEqual(1, E.index_libre((0,)))
        self.assertEqual(2, E.index_libre((0, 1, 3)))

    def test_a_taken_one_is_never_proposed(self):
        pris = tuple(range(0, 20))
        self.assertNotIn(E.index_libre(pris), pris)

    def test_no_room_left_proposes_nothing(self):
        """Proposer un index hors bornes ferait taper une valeur que le
        moteur refuse, sans dire pourquoi."""
        self.assertIsNone(E.index_libre(range(E.INDEX_MIN, E.INDEX_MAX + 1)))


if __name__ == "__main__":
    unittest.main()
