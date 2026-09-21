#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une liste blanche qui laisse passer tout est le mensonge à tuer.

Le registre a déjà retiré une posture pour cela : « restricted » annonçait
une politique de liste blanche sans liste, se comportait comme une sortie
libre, et donnait l'assurance du contraire. Ces épreuves tiennent la même
frontière un cran plus bas — sur la liste elle-même.

`cidr_list` normalise et ne juge pas : elle rend la route par défaut sans
broncher. Chacun des refus mesurés ici est donc AJOUTÉ, aucun n'est hérité,
et un refus retiré ne se verrait nulle part ailleurs.

Toutes les adresses écrites ici sont des plages de documentation (RFC 5737,
RFC 3849) et les noms sont en « .example » (RFC 2606) : une épreuve fige
pour toujours ce qu'elle cite, et citer un vrai site parce qu'il est
parlant est exactement le réflexe que la règle du dépôt combat.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.lib_valid import ValidationError  # noqa: E402
from script.posture import allowlist as A  # noqa: E402

# Un /24 de documentation : assez étroit pour être accepté, assez large
# pour qu'on voie qu'il n'est pas ramené à un /32.
RESEAU = "198.51.100.0/24"


class TestLeRapprochement(unittest.TestCase):
    def test_a_known_symbol_brings_its_ports_and_its_reason(self):
        permis = A.resolve("forge", [RESEAU])
        self.assertEqual("forge", permis.symbol)
        self.assertEqual((RESEAU,), permis.networks)
        self.assertEqual(A.SYMBOLS["forge"].ports, permis.ports)
        self.assertEqual(A.SYMBOLS["forge"].reason, permis.reason)

    def test_a_bare_address_becomes_a_single_host(self):
        self.assertEqual(
            ("198.51.100.7/32",),
            A.resolve("vault", ["198.51.100.7"]).networks,
        )

    def test_a_tuple_of_networks_is_accepted_like_a_list(self):
        """Une fiche relue rend des tuples ; les refuser ferait écrire une
        conversion chez chaque appelant, et l'un d'eux l'oublierait."""
        self.assertEqual((RESEAU,), A.resolve("forge", (RESEAU,)).networks)

    def test_the_same_network_twice_is_listed_once(self):
        self.assertEqual(
            (RESEAU,), A.resolve("forge", [RESEAU, RESEAU]).networks
        )

    def test_an_unknown_symbol_names_the_ones_that_exist(self):
        """Le vocabulaire est clos : le dire est ce qui envoie déclarer le
        besoin dans le tableau plutôt que l'ajouter au moment du rendu."""
        with self.assertRaises(ValidationError) as leve:
            A.resolve("proxy-maison", [RESEAU])
        self.assertIn("forge", str(leve.exception))

    def test_get_answers_none_without_raising(self):
        """Une configuration de site peut nommer un symbole retiré, et
        l'écran doit pouvoir le dire plutôt que de s'interrompre."""
        self.assertIsNone(A.get("proxy-maison"))
        self.assertIsNotNone(A.get("forge"))


class TestLesQuatreRefusAjoutes(unittest.TestCase):
    """Aucun n'est hérité : `cidr_list` rend « 0.0.0.0/0 » sans broncher."""

    def test_the_default_route_is_refused_and_named_for_what_it_is(self):
        """Le plancher de préfixe la refuserait aussi, par sa largeur. Ce
        que l'épreuve tient est le MESSAGE : « couvre tout » se lit et se
        corrige, « préfixe trop large » envoie chercher un /16."""
        self.assertTrue(
            A.ROUTES_PAR_DEFAUT, "aucune route : rien n'est prouvé"
        )
        for route in A.ROUTES_PAR_DEFAUT:
            with self.subTest(route=route):
                with self.assertRaises(ValidationError) as leve:
                    A.resolve("forge", [route])
                self.assertIn("couvre tout", str(leve.exception))

    def test_cidr_list_alone_would_have_accepted_it(self):
        """Le contrôle qui prouve que le refus est AJOUTÉ ici. Sans lui,
        l'épreuve d'à côté passerait aussi sur un code qui délègue tout."""
        from script.lib_valid import cidr_list

        self.assertEqual(["0.0.0.0/0"], cidr_list("0.0.0.0/0"))

    def test_two_halves_cover_the_internet_and_are_refused_too(self):
        """Le contournement de la route par défaut : ne jamais l'écrire, et
        couvrir tout quand même. Refuser la seule route par défaut serait
        une garde qu'une ligne de configuration défait."""
        with self.assertRaises(ValidationError):
            A.resolve("forge", ["0.0.0.0/1", "128.0.0.0/1"])

    def test_a_prefix_wider_than_the_floor_is_refused(self):
        for reseau in ("10.0.0.0/8", "2001:db8::/24"):
            with self.subTest(reseau=reseau):
                with self.assertRaises(ValidationError):
                    A.resolve("forge", [reseau])

    def test_the_floor_itself_is_accepted(self):
        """Contrôle positif : le seuil borne, il n'interdit pas."""
        for reseau in ("10.0.0.0/16", "2001:db8::/32"):
            with self.subTest(reseau=reseau):
                self.assertTrue(A.resolve("forge", [reseau]).networks)

    def test_an_empty_list_is_refused_rather_than_rendered_empty(self):
        """Sans ce refus, l'absence se découvrirait sur la machine."""
        for vide in ([], (), "", None):
            with self.subTest(vide=repr(vide)):
                with self.assertRaises(ValidationError):
                    A.resolve("forge", vide)

    def test_a_hostname_is_refused_and_the_reason_is_the_freezing(self):
        """Un « refusé » sec enverrait chercher une faute de frappe. Ce
        qu'il faut lire, c'est que résoudre fige l'adresse du jour."""
        with self.assertRaises(ValidationError) as leve:
            A.resolve("forge", ["forge.example"])
        self.assertIn("forge.example", str(leve.exception))
        self.assertIn("fige", str(leve.exception))

    def test_a_hostname_given_as_text_is_refused_the_same_way(self):
        """L'entrée accepte aussi une chaîne : le refus ne peut pas ne
        valoir que pour les listes."""
        with self.assertRaises(ValidationError) as leve:
            A.resolve("forge", "forge.example")
        self.assertIn("fige", str(leve.exception))

    def test_a_malformed_address_keeps_its_own_message(self):
        """Contrôle positif : la relève du message ne doit pas avaler tout
        ce qui échoue et faire lire « c'est un nom » sur une faute."""
        with self.assertRaises(ValidationError) as leve:
            A.resolve("forge", ["198.51.100.999/24"])
        self.assertNotIn("fige", str(leve.exception))


class TestLesPorts(unittest.TestCase):
    def test_the_site_may_serve_the_same_role_elsewhere(self):
        self.assertEqual(
            (8443,), A.resolve("forge", [RESEAU], ports=[8443]).ports
        )

    def test_no_override_keeps_the_defaults(self):
        self.assertEqual(
            A.SYMBOLS["forge"].ports, A.resolve("forge", [RESEAU]).ports
        )

    def test_they_come_back_sorted_and_deduplicated(self):
        """L'ordre fait le rendu : deux listes équivalentes doivent écrire
        le même fichier, sans quoi un diff signale un changement qui
        n'existe pas."""
        self.assertEqual(
            (22, 443),
            A.resolve("forge", [RESEAU], ports=[443, 22, 443]).ports,
        )

    def test_a_port_outside_the_range_is_refused(self):
        for port in (0, 65536, -1):
            with self.subTest(port=port):
                with self.assertRaises(ValidationError):
                    A.resolve("forge", [RESEAU], ports=[port])

    def test_a_port_that_is_not_a_number_is_refused(self):
        with self.assertRaises(ValidationError):
            A.resolve("forge", [RESEAU], ports=["https"])

    def test_a_port_written_as_text_is_accepted(self):
        """Une valeur relue d'un fichier de configuration arrive en texte."""
        self.assertEqual(
            (8443,), A.resolve("forge", [RESEAU], ports=["8443"]).ports
        )

    def test_an_override_that_empties_the_list_is_refused(self):
        """Une règle sans port ouvrirait les 65 534 autres avec le bon.
        Une chaîne de blancs est ce qui y mène : elle est vraie, donc elle
        ne retombe pas sur les ports par défaut."""
        with self.assertRaises(ValidationError) as leve:
            A.resolve("forge", [RESEAU], ports="  ")
        self.assertIn("aucun port", str(leve.exception))

    def test_a_single_port_written_as_text_is_not_iterated(self):
        """« 443 » parcouru caractère par caractère rend les ports 3 et 4 :
        une règle qui ouvre deux ports au hasard, et pas celui demandé."""
        self.assertEqual(
            (443,), A.resolve("forge", [RESEAU], ports="443").ports
        )

    def test_several_ports_in_one_string_are_split(self):
        """Une valeur relue d'un fichier de configuration arrive ainsi."""
        self.assertEqual(
            (80, 443), A.resolve("forge", [RESEAU], ports="443, 80").ports
        )


class TestLeTableauLuiMeme(unittest.TestCase):
    def test_there_is_something_to_check(self):
        self.assertGreaterEqual(len(A.SYMBOLS), 4)

    def test_every_symbol_keys_itself(self):
        """Une clé et un champ qui divergent feraient rendre une règle sous
        un nom que la configuration du site ne porte pas."""
        for nom, destination in A.SYMBOLS.items():
            with self.subTest(symbol=nom):
                self.assertEqual(nom, destination.symbol)

    def test_every_protocol_is_in_the_closed_vocabulary(self):
        for nom, destination in A.SYMBOLS.items():
            with self.subTest(symbol=nom):
                self.assertTrue(destination.protocols)
                for protocole in destination.protocols:
                    self.assertIn(protocole, A.PROTOCOLS)

    def test_every_symbol_names_at_least_one_valid_port(self):
        for nom, destination in A.SYMBOLS.items():
            with self.subTest(symbol=nom):
                self.assertTrue(destination.ports)
                for port in destination.ports:
                    self.assertTrue(1 <= port <= 65535)

    def test_every_symbol_says_why_it_would_ever_be_opened(self):
        """La raison part en commentaire au-dessus de la règle rendue. Une
        règle qui ne dit pas pourquoi elle existe est une règle que
        personne n'ose retirer."""
        for nom, destination in A.SYMBOLS.items():
            with self.subTest(symbol=nom):
                self.assertGreater(len(destination.reason), 40)

    def test_every_symbol_resolves_against_a_documentation_network(self):
        """Aucun symbole ne se contente d'exister : chacun doit traverser
        les contrôles avec ses propres valeurs par défaut."""
        for nom in A.symbol_names():
            with self.subTest(symbol=nom):
                self.assertTrue(A.resolve(nom, [RESEAU]).ports)


if __name__ == "__main__":
    unittest.main()
