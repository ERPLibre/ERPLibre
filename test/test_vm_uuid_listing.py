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


# La forme sous LC_ALL=C. Le pilote de test ne sait PAS rendre de baux
# (« virNetworkGetDHCPLeases » n'y est pas pris en charge), donc aucune
# confrontation au binaire n'est possible ici : cet échantillon est le
# contrat, et les colonnes sont ce qui ne dépend d'aucune langue.
BAUX = (
    " Expiry Time           MAC address         Protocol   IP address"
    "           Hostname   Client ID or DUID\n"
    "-------------------------------------------------------------\n"
    " 2026-09-08 10:00:00   52:54:00:11:22:33   ipv4"
    "       192.0.2.10/24        vm-a       -\n"
    " 2026-09-08 10:05:00   52:54:00:44:55:66   ipv4"
    "       192.0.2.11/24        -          -\n"
)


class TestLesBaux(unittest.TestCase):
    """L'inventaire est TRADUIT : sous une locale française ses en-têtes
    deviennent « Adresse IP » et « Nom d'hôte ». Un analyseur qui cherche
    ses étiquettes rend une liste vide — laquelle se lit « aucun bail »,
    ce qui est un mensonge tranquille."""

    def test_it_reads_the_address_and_the_name(self):
        baux = B.parse_leases(BAUX)
        self.assertEqual(2, len(baux))
        self.assertEqual("192.0.2.10", baux[0].address)
        self.assertEqual("vm-a", baux[0].hostname)

    def test_the_header_is_not_a_lease(self):
        """Les en-têtes et la ligne de tirets ne portent aucune adresse :
        c'est la FORME qui les écarte, pas leur position."""
        self.assertEqual((), B.parse_leases(BAUX.splitlines()[0]))

    def test_a_translated_header_changes_nothing(self):
        """Ce que la locale change, ce sont les ÉTIQUETTES ; l'ordre des
        colonnes, lui, ne dépend d'aucune langue."""
        traduit = BAUX.replace("IP address", "Adresse IP").replace(
            "Hostname", "Nom d'hôte"
        )
        self.assertEqual(B.parse_leases(BAUX), B.parse_leases(traduit))

    def test_a_missing_name_is_empty_and_not_a_dash(self):
        """Garder le tiret ferait comparer un nom de machine à « - »."""
        self.assertEqual("", B.parse_leases(BAUX)[1].hostname)

    def test_the_prefix_describes_the_network_not_the_machine(self):
        for bail in B.parse_leases(BAUX):
            with self.subTest(bail=bail):
                self.assertNotIn("/", bail.address)

    def test_the_name_is_found_by_the_address_already_resolved(self):
        """La demander à nouveau coûterait une lecture de plus pour une
        réponse qu'on a déjà."""
        self.assertEqual("vm-a", B.lease_hostname(BAUX, "192.0.2.10"))
        self.assertEqual("", B.lease_hostname(BAUX, "192.0.2.11"))
        self.assertEqual("", B.lease_hostname(BAUX, "198.51.100.9"))

    def test_an_address_given_with_its_prefix_still_matches(self):
        self.assertEqual("vm-a", B.lease_hostname(BAUX, "192.0.2.10/24"))

    def test_the_first_address_of_a_line_is_the_one_served(self):
        """Une machine peut porter un NOM qui ressemble à une adresse. Sans
        cette borne, une ligne en rendrait deux baux : le vrai, et un
        fantôme dont l'adresse est le nom du premier."""
        ligne = (
            " 2026-09-08 10:00:00   52:54:00:11:22:33   ipv4"
            "       192.0.2.10/24        192.0.2.99       -\n"
        )
        baux = B.parse_leases(ligne)
        self.assertEqual(1, len(baux), baux)
        self.assertEqual("192.0.2.10", baux[0].address)
        self.assertEqual("192.0.2.99", baux[0].hostname)

    def test_an_empty_listing_is_no_lease(self):
        for vide in ("", None, "\n---\n"):
            with self.subTest(vide=repr(vide)):
                self.assertEqual((), B.parse_leases(vide))


if __name__ == "__main__":
    unittest.main()
