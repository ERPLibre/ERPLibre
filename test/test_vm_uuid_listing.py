#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lire le nom ET la preuve d'un domaine en UN seul appel.

Un nom de domaine se réemploie, un UUID naît et meurt avec le domaine. Pour
qu'un écran puisse armer le garde d'identité, il lui faut les deux — et les
demander séparément coûterait un appel par machine devant un menu.

DEUX ÉTAGES, ET C'EST VOULU. Un échantillon ÉPINGLÉ porte le contrat et
tourne partout ; une confrontation au vrai binaire dit si l'inventaire a
changé de forme. L'échantillon seul se figerait sur une forme périmée sans
que rien ne le dise ; la confrontation seule ne tournerait pas là où l'outil
manque.

La confrontation n'exige AUCUN hyperviseur : le pilote de test intégré à
libvirt a toujours un domaine et ne touche à rien. C'est ce qui permet de
mesurer la forme réelle depuis une station, en millisecondes.

Les UUID écrits ici sont inventés ; seule la confrontation lit celui du
pilote, et elle en vérifie la FORME, pas la valeur.
"""

import os
import re
import shutil
import subprocess
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.vm import backend as B  # noqa: E402

# La forme de l'inventaire : UUID en tête, nom ensuite, une ligne par
# domaine. La confrontation d'en bas dit si elle a changé.
ECHANTILLON = (
    "aaaaaaaa-1111-2222-3333-444444444444 machine-a\n"
    "bbbbbbbb-1111-2222-3333-444444444444 machine-b\n"
    "\n"
)

# L'inventaire du pilote de test. Il ne demande aucun hyperviseur.
URI_ESSAI = "test:///default"
VIRSH = shutil.which("virsh")


class TestLaFormeEpinglee(unittest.TestCase):
    def test_it_reads_the_name_and_the_proof_of_each_domain(self):
        domaines = B.parse_uuid_listing(ECHANTILLON)
        self.assertEqual(
            ["machine-a", "machine-b"], [d.name for d in domaines]
        )
        for domaine in domaines:
            with self.subTest(nom=domaine.name):
                self.assertTrue(domaine.proof)

    def test_a_split_on_whitespace_would_have_given_four_tokens(self):
        """LE piège : un écran qui numérote cette liste proposerait des
        UUID comme s'ils étaient des machines."""
        self.assertEqual(4, len(ECHANTILLON.split()))
        self.assertEqual(2, len(B.parse_uuid_listing(ECHANTILLON)))

    def test_the_order_of_the_listing_is_kept(self):
        """L'écran numérote : un ordre qui bouge change ce que « 2 »
        désigne entre l'affichage et la sélection."""
        inverse = "\n".join(reversed(ECHANTILLON.strip().splitlines()))
        self.assertEqual(
            ["machine-b", "machine-a"],
            [d.name for d in B.parse_uuid_listing(inverse)],
        )

    def test_an_empty_listing_is_no_domain(self):
        for vide in ("", None, "\n\n  \n"):
            with self.subTest(vide=repr(vide)):
                self.assertEqual((), B.parse_uuid_listing(vide))

    def test_a_name_may_carry_a_space(self):
        """Deux champs et non plus : le nom est ce qui reste après la
        preuve, espaces compris."""
        domaine = B.parse_uuid_listing(
            "aaaaaaaa-1111-2222-3333-444444444444 un nom espace\n"
        )[0]
        self.assertEqual("un nom espace", domaine.name)
        self.assertTrue(domaine.proof)

    def test_they_are_real_libvirt_identities(self):
        """Passées telles quelles au verbe : le nom adresse, l'UUID
        prouve."""
        domaine = B.parse_uuid_listing(ECHANTILLON)[0]
        self.assertEqual(B.LIBVIRT, domaine.backend)
        self.assertEqual(domaine.name, domaine.key)
        self.assertTrue(B.is_armed(domaine))


class TestCeQuiNAPasDePreuve(unittest.TestCase):
    """Une machine sans preuve ne DISPARAÎT pas : l'appelant doit pouvoir
    la nommer pour la refuser."""

    def test_a_line_with_a_single_field_keeps_its_name(self):
        domaine = B.parse_uuid_listing("juste-un-nom\n")[0]
        self.assertEqual("juste-un-nom", domaine.name)
        self.assertEqual("", domaine.proof)
        self.assertFalse(B.is_armed(domaine))

    def test_a_first_field_that_is_not_a_uuid_proves_nothing(self):
        """Si l'inventaire changeait l'ordre de ses colonnes, un nom pris
        pour une preuve armerait un garde qui comparerait un nom à un
        UUID — et refuserait tout, ou pire, concorderait par hasard."""
        domaine = B.parse_uuid_listing("machine-a 12345\n")[0]
        self.assertEqual("machine-a 12345", domaine.name)
        self.assertEqual("", domaine.proof)

    def test_a_truncated_uuid_is_not_a_uuid(self):
        domaine = B.parse_uuid_listing("aaaaaaaa-1111 machine-a\n")[0]
        self.assertEqual("", domaine.proof)

    def test_the_case_of_the_hexadecimal_does_not_matter(self):
        """Contrôle positif : refuser les majuscules rejetterait des
        preuves valides."""
        domaine = B.parse_uuid_listing(
            "AAAAAAAA-1111-2222-3333-444444444444 machine-a\n"
        )[0]
        self.assertTrue(domaine.proof)


@unittest.skipUnless(VIRSH, "virsh absent de la station")
class TestLaConfrontationAuVraiBinaire(unittest.TestCase):
    """Ce que l'échantillon épinglé ne peut pas savoir : si l'inventaire a
    changé de forme. Aucun hyperviseur n'est touché."""

    @classmethod
    def setUpClass(cls):
        cls.brut = subprocess.run(
            [
                VIRSH,
                "--connect",
                URI_ESSAI,
                "list",
                "--all",
                "--uuid",
                "--name",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout

    def test_the_two_options_are_not_exclusive(self):
        """Si elles le devenaient, une seule colonne sortirait et l'écran
        perdrait soit les noms, soit les preuves."""
        domaines = B.parse_uuid_listing(self.brut)
        self.assertEqual(1, len(domaines), self.brut)
        self.assertEqual("test", domaines[0].name)

    def test_the_proof_comes_first_and_has_the_shape_of_a_uuid(self):
        """La VALEUR n'est pas épinglée : c'est la colonne qui compte."""
        domaine = B.parse_uuid_listing(self.brut)[0]
        self.assertRegex(
            domaine.proof,
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
            r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        )

    def test_the_flag_order_on_the_command_line_changes_nothing(self):
        """Écrire « --name --uuid » ne met pas le nom en tête : c'est ce
        qui permet de n'écrire l'ordre qu'à un seul endroit."""
        inverse = subprocess.run(
            [
                VIRSH,
                "--connect",
                URI_ESSAI,
                "list",
                "--all",
                "--name",
                "--uuid",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        self.assertEqual(
            [(d.name, d.proof) for d in B.parse_uuid_listing(self.brut)],
            [(d.name, d.proof) for d in B.parse_uuid_listing(inverse)],
        )


if __name__ == "__main__":
    unittest.main()
