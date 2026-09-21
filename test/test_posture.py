#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les postures réseau : leur vocabulaire, et la règle d'or mécanisée.

« Des données réelles et une sortie libre ne cohabitent jamais » est une
phrase qu'on affiche, jusqu'à ce qu'une fonction la calcule. Ces épreuves
tiennent le calcul, et surtout ses TROIS chemins de fuite : la porte (des
destinations non bornées), la fiction (une politique que rien n'applique) et
la fenêtre (un mécanisme qui manque les conteneurs).

Rien ici ne touche à une machine : une posture est une donnée.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script import posture as P  # noqa: E402
from script.posture import rules  # noqa: E402


class TestLaDocumentationSuitLeRegistre(unittest.TestCase):
    """Une posture ajoutée sans être documentée est une posture qu'on
    découvre à l'usage.

    Le README du paquet nomme les quatre et dit ce que chacune tient
    VRAIMENT. Ajouter la cinquième sans y toucher laisserait un lecteur
    croire que la table est complète — et une table incomplète se lit comme
    une table, pas comme un morceau de table.

    Le contrôle porte sur la SOURCE bilingue : les deux fichiers rendus en
    sont dérivés, et corriger l'un d'eux se perd au prochain rendu.
    """

    @staticmethod
    def source():
        chemin = os.path.join(RACINE, "script", "posture", "README.base.md")
        with open(chemin, encoding="utf-8") as fichier:
            return fichier.read()

    @classmethod
    def moities(cls):
        """(anglais, français) — le contrôle porte sur CHAQUE langue.

        Une ligne retirée d'une seule moitié laisserait l'autre complète, et
        une vérification sur le texte entier ne verrait rien.
        """
        anglais, _sep, francais = cls.source().partition("<!-- [fr] -->")
        return anglais, francais

    @staticmethod
    def lignes_de_table(moitie):
        """Les lignes de la table des postures, qui commencent par « | ` »."""
        return [
            ligne
            for ligne in moitie.splitlines()
            if ligne.strip().startswith("| `")
        ]

    def test_the_table_has_exactly_one_row_per_posture(self):
        """Une table amputée se lit comme une table, pas comme un morceau
        de table : compter est ce qui distingue les deux."""
        attendu = len(P.posture_names())
        for moitie in self.moities():
            with self.subTest(langue=moitie[:40]):
                self.assertEqual(attendu, len(self.lignes_de_table(moitie)))

    def test_every_posture_has_its_own_row_in_both_languages(self):
        for moitie in self.moities():
            lignes = "\n".join(self.lignes_de_table(moitie))
            for nom in P.posture_names():
                with self.subTest(posture=nom):
                    self.assertIn(f"| `{nom}` |", lignes)

    def test_no_posture_is_named_that_the_registry_dropped(self):
        """« restricted » a été retirée du registre parce qu'elle donnait
        l'assurance du contraire de ce qu'elle tenait. La documenter
        encore la ferait chercher."""
        self.assertNotIn("`restricted`", self.source())

    def test_every_gap_token_is_named_in_both_languages(self):
        for moitie in self.moities():
            for jeton in rules.UNENFORCED_TOKENS:
                with self.subTest(jeton=jeton, langue=moitie[:40]):
                    self.assertIn(f"`{jeton}`", moitie)


class TestLeVocabulaireEstClos(unittest.TestCase):
    """Une valeur hors vocabulaire ne se voit qu'au moment où elle décide."""

    def test_the_registry_is_not_empty(self):
        """Sur un registre vide, toutes les épreuves d'à côté passent."""
        self.assertTrue(P.POSTURES)
        self.assertEqual(len(P.POSTURES), len(P.posture_names()))

    def test_every_field_stays_inside_its_vocabulary(self):
        for nom, posture in P.POSTURES.items():
            with self.subTest(posture=nom):
                self.assertEqual(nom, posture.name)
                self.assertIn(posture.network_kind, P.NETWORK_KINDS)
                self.assertIn(posture.egress, P.EGRESS_KINDS)
                self.assertIn(posture.dns, P.DNS_KINDS)
                self.assertIn(posture.host_keys, P.HOST_KEY_POLICIES)

    def test_every_flag_is_a_real_boolean(self):
        """Une chaîne « False » serait vraie, et la règle d'or dirait oui."""
        drapeaux = (
            "destinations_bounded",
            "ports_bounded",
            "egress_enforced",
            "covers_containers",
            "forward_agent",
            "cloud",
            "needs_forge",
        )
        for nom, posture in P.POSTURES.items():
            for champ in drapeaux:
                with self.subTest(posture=nom, champ=champ):
                    self.assertIsInstance(getattr(posture, champ), bool)

    def test_the_default_posture_exists(self):
        self.assertIsNotNone(P.get_posture(P.DEFAULT_POSTURE))

    def test_an_unknown_name_is_said_and_not_raised(self):
        """Une fiche peut nommer une posture retirée, et l'écran doit
        pouvoir le dire plutôt que de s'interrompre."""
        self.assertIsNone(P.get_posture("jamais-vue"))

    def test_the_suffixes_never_collide(self):
        """Deux postures qui suffixent pareil rendraient deux machines
        indiscernables dans ~/.ssh/config."""
        suffixes = [p.name_suffix for p in P.POSTURES.values()]
        self.assertEqual(len(suffixes), len(set(suffixes)))


class TestLeFantomeNeRevientPas(unittest.TestCase):
    """Une posture sans mécanisme est un nom rassurant, pas une posture."""

    def test_restricted_is_not_a_posture(self):
        """Elle déclarait une liste blanche sans liste : elle se comportait
        comme une sortie libre en donnant l'assurance du contraire."""
        self.assertIsNone(P.get_posture("restricted"))

    def test_local_webui_is_not_a_posture_either(self):
        """C'était une posture ET un profil d'installation confondus. Les
        séparer permet de servir autre chose sur la même posture."""
        self.assertIsNone(P.get_posture("local-webui"))


class TestLaRegleDOr(unittest.TestCase):
    """Trois chemins de fuite, trois conditions, et aucune n'est en trop.

    Chaque épreuve part de la posture ENTIÈREMENT confinée et ne défait
    qu'un champ. C'est la seule façon de prouver qu'une condition porte :
    sur une posture qui échoue déjà par ailleurs, retirer la condition
    qu'on croit éprouver ne change rien, et l'épreuve reste verte.
    """

    def confinee(self):
        posture = P.get_posture("local-only")
        self.assertTrue(
            P.allows_real_data(posture),
            "le point de départ n'est plus confiné : rien n'est prouvé",
        )
        return posture

    def test_nothing_is_allowed_without_a_posture(self):
        self.assertFalse(P.allows_real_data(None))

    def test_unbounded_destinations_are_refused(self):
        """La porte : la donnée sort vers n'importe quelle adresse."""
        self.assertFalse(
            P.allows_real_data(
                self.confinee()._replace(destinations_bounded=False)
            )
        )

    def test_a_policy_nothing_applies_is_refused(self):
        """La fiction : la politique borne sur le papier, et aucun code
        n'écrit encore la règle qui le ferait."""
        self.assertFalse(
            P.allows_real_data(self.confinee()._replace(egress_enforced=False))
        )

    def test_a_mechanism_that_misses_containers_is_refused(self):
        """La fenêtre : leur trafic traverse FORWARD, et un verrou accroché
        à OUTPUT les laisse sortir sans rien signaler."""
        self.assertFalse(
            P.allows_real_data(
                self.confinee()._replace(covers_containers=False)
            )
        )

    def test_a_fully_confined_posture_is_allowed(self):
        """Contrôle positif : refuser TOUT passerait les trois épreuves
        d'au-dessus sans rien prouver."""
        self.assertTrue(P.allows_real_data(P.get_posture("local-only")))

    def test_no_posture_of_the_registry_allows_it_by_accident(self):
        for nom, posture in P.POSTURES.items():
            with self.subTest(posture=nom):
                attendu = (
                    posture.destinations_bounded
                    and posture.egress_enforced
                    and posture.covers_containers
                )
                self.assertEqual(attendu, P.allows_real_data(posture))

    def test_paranoid_is_refused_today_and_says_why(self):
        """Elle borne ses destinations, mais rien n'applique encore la
        politique et le mécanisme prévu manque les conteneurs. Le jour où
        ces deux-là changent, elle deviendra utilisable — et cette épreuve
        le dira en tombant."""
        stricte = P.get_posture("paranoid")
        self.assertTrue(stricte.destinations_bounded)
        self.assertFalse(stricte.egress_enforced)
        self.assertFalse(stricte.covers_containers)
        self.assertFalse(P.allows_real_data(stricte))


class TestLesInvariantsEntreChamps(unittest.TestCase):
    def test_connected_does_not_claim_to_bound_destinations(self):
        """LE mensonge à tuer : elle s'annonçait « en liste blanche » avec
        une liste portant 0.0.0.0/0 sur 80 et 443. Cela borne des PORTS et
        aucune destination, et les deux garanties ne se valent pas."""
        connectee = P.get_posture("connected")
        self.assertEqual("allowlist", connectee.egress)
        self.assertTrue(connectee.ports_bounded)
        self.assertFalse(connectee.destinations_bounded)

    def test_a_confining_posture_never_forwards_the_agent(self):
        """Le transférer donnerait à la machine confinée de quoi
        s'authentifier partout où l'agent le peut : le confinement tombe
        sans qu'une seule règle réseau ait changé."""
        for nom, posture in P.POSTURES.items():
            if posture.destinations_bounded:
                with self.subTest(posture=nom):
                    self.assertFalse(posture.forward_agent)

    def test_no_egress_means_an_isolated_network(self):
        """Annoncer « rien ne sort » sur un réseau NAT laisserait la route
        en place, et la promesse ne tiendrait qu'aux règles."""
        for nom, posture in P.POSTURES.items():
            if posture.egress == "none":
                with self.subTest(posture=nom):
                    self.assertEqual("isolated", posture.network_kind)

    def test_an_isolated_network_reaches_neither_cloud_nor_forge(self):
        for nom, posture in P.POSTURES.items():
            if posture.network_kind == "isolated":
                with self.subTest(posture=nom):
                    self.assertFalse(posture.cloud)
                    self.assertFalse(posture.needs_forge)

    def test_bounding_ports_is_implied_by_bounding_destinations(self):
        """L'inverse est faux, et c'est tout l'objet des deux champs."""
        for nom, posture in P.POSTURES.items():
            if posture.destinations_bounded:
                with self.subTest(posture=nom):
                    self.assertTrue(posture.ports_bounded)


class TestElleNeSaitRienDeLHyperviseur(unittest.TestCase):
    """Trois consommateurs la lisent ; elle n'appartient à aucun."""

    def test_it_names_no_hypervisor(self):
        chemin = os.path.join(RACINE, "script", "posture", "registry.py")
        with open(chemin, encoding="utf-8") as handle:
            source = handle.read().lower()
        for mot in ("qemu", "proxmox", "lima", "virsh", "pveversion"):
            # Message court : l'échec par défaut recracherait le fichier.
            self.assertNotIn(mot, source, f"« {mot} » nommé dans le registre")

    def test_it_imports_only_the_standard_library(self):
        import ast

        chemin = os.path.join(RACINE, "script", "posture", "registry.py")
        with open(chemin, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        racines = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                racines.update(a.name.split(".")[0] for a in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                racines.add(noeud.module.split(".")[0])
        self.assertTrue(racines, "aucun import lu : rien n'est prouvé")
        self.assertEqual(set(), racines - set(sys.stdlib_module_names))


if __name__ == "__main__":
    unittest.main()
