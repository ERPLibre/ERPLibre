#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le carnet d'adresses : d'où vient chaque adresse, et ce qu'on ne peut pas
retirer.

CE QU'IL DÉBLOQUE. « VM paranoid » nomme sept rôles et le déploiement REFUSE
tant que l'un d'eux n'a pas d'adresse. Rien dans le dépôt n'écrivait ce
carnet : le mécanisme complet existait, et le premier pas manquait.

DEUX PIÈGES, MESURÉS ET NON DÉDUITS.

LE FICHIER SUIVI. Le carnet ne porte que des ADRESSES — l'allowlist refuse
un nom d'hôte — et `script/todo/todo.json` suit le dépôt. Une adresse y
devient publique au premier envoi d'un fork.

LA FUSION ÉTEND. Un rôle présent dans deux fichiers porte la RÉUNION de
leurs adresses. Retirer la sienne ne retire pas celle de l'équipe, et un
écran qui promettrait la suppression laisserait croire une adresse fermée
alors qu'elle est encore ouverte.

Les trois fichiers sont déplacés dans un temporaire : écrire dans le vrai
carnet détruirait celui de la personne qui lance l'épreuve.
"""

import json
import os
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.lib_valid import ValidationError  # noqa: E402
from script.todo import egress_book as B  # noqa: E402


class CarnetDeBanc(unittest.TestCase):
    """Les trois fichiers, dans un temporaire."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.chemins = {
            B.TRACKED: os.path.join(self.tmp.name, "todo.json"),
            B.TEAM: os.path.join(self.tmp.name, "equipe.json"),
            B.MACHINE: os.path.join(self.tmp.name, "machine.json"),
        }
        self.patches = [
            patch(
                "script.config.config_file.CONFIG_FILE",
                self.chemins[B.TRACKED],
            ),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_FILE",
                self.chemins[B.TEAM],
            ),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
                self.chemins[B.MACHINE],
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.ecrire(B.TRACKED, {})

    def ecrire(self, source, carnet):
        with open(self.chemins[source], "w", encoding="utf-8") as fichier:
            json.dump({B.BOOK_KEY: carnet} if carnet else {}, fichier)


class TestLeFichierSuiviEstRefuse(CarnetDeBanc):
    """Une adresse y devient publique au premier envoi d'un fork."""

    def test_an_empty_tracked_file_is_the_correct_state(self):
        self.assertEqual((), B.tracked_roles())
        B.refuse_tracked()

    def test_a_role_written_there_is_named_and_refused(self):
        self.ecrire(B.TRACKED, {"forge": ["203.0.113.7"]})
        self.assertEqual(("forge",), B.tracked_roles())
        with self.assertRaises(ValidationError) as pris:
            B.refuse_tracked()
        self.assertIn("forge", str(pris.exception))

    def test_the_message_names_the_file_so_one_knows_where_to_look(self):
        self.ecrire(B.TRACKED, {"vault": ["203.0.113.8"]})
        with self.assertRaises(ValidationError) as pris:
            B.refuse_tracked()
        self.assertIn("todo.json", str(pris.exception))

    def test_reading_refuses_before_returning_anything(self):
        """Rendre le carnet puis signaler la fuite laisserait un
        déploiement réussi derrière lui."""
        self.ecrire(B.TRACKED, {"ntp": ["192.0.2.1"]})
        self.ecrire(B.MACHINE, {"forge": ["203.0.113.7"]})
        with self.assertRaises(ValidationError):
            B.read()

    def test_a_clean_tracked_file_lets_the_book_through(self):
        """Contrôle positif : refuser toujours rendrait le carnet
        inutilisable."""
        self.ecrire(B.MACHINE, {"forge": ["203.0.113.7"]})
        self.assertEqual({"forge": ["203.0.113.7"]}, B.read())


class TestDouViennentLesAdresses(CarnetDeBanc):
    def test_each_file_is_read_apart(self):
        self.ecrire(B.TEAM, {"forge": ["198.51.100.9"]})
        self.ecrire(B.MACHINE, {"vault": ["203.0.113.8"]})
        par_source = B.by_source()
        self.assertEqual({"forge": ["198.51.100.9"]}, par_source[B.TEAM])
        self.assertEqual({"vault": ["203.0.113.8"]}, par_source[B.MACHINE])

    def test_a_missing_file_is_an_empty_book_and_not_a_crash(self):
        os.remove(self.chemins[B.TRACKED])
        self.assertEqual({}, B.by_source()[B.TRACKED])

    def test_a_truncated_file_does_not_take_the_others_down(self):
        """Le carnet d'un fichier n'engage pas les autres."""
        with open(self.chemins[B.TEAM], "w", encoding="utf-8") as fichier:
            fichier.write('{"egress_destinations": ')
        self.ecrire(B.MACHINE, {"vault": ["203.0.113.8"]})
        self.assertEqual({}, B.by_source()[B.TEAM])
        self.assertEqual({"vault": ["203.0.113.8"]}, B.machine_book())

    def test_a_file_without_the_key_is_an_empty_book(self):
        with open(self.chemins[B.TEAM], "w", encoding="utf-8") as fichier:
            json.dump({"autre_chose": 1}, fichier)
        self.assertEqual({}, B.by_source()[B.TEAM])

    def test_every_source_is_in_the_closed_vocabulary(self):
        self.assertEqual(set(B.SOURCES), set(B.by_source()))


class TestCeQuUneSuppressionNeRetirePas(CarnetDeBanc):
    """LA FUSION ÉTEND : mesuré, pas déduit."""

    def test_two_files_give_the_union_and_not_the_last_word(self):
        self.ecrire(B.TEAM, {"forge": ["198.51.100.9"]})
        self.ecrire(B.MACHINE, {"forge": ["203.0.113.7"]})
        self.assertEqual(["203.0.113.7", "198.51.100.9"], B.read()["forge"])

    def test_the_team_addresses_are_named_as_unremovable(self):
        self.ecrire(B.TEAM, {"forge": ["198.51.100.9"]})
        self.assertEqual(["198.51.100.9"], B.shared_networks("forge"))

    def test_a_role_only_here_has_nothing_unremovable(self):
        """Contrôle positif : tout déclarer indéracinable ne dirait rien."""
        self.ecrire(B.MACHINE, {"vault": ["203.0.113.8"]})
        self.assertEqual([], B.shared_networks("vault"))

    def test_forgetting_here_leaves_the_team_address_in_place(self):
        """LE PIÈGE : l'opérateur croirait l'adresse fermée."""
        self.ecrire(B.TEAM, {"forge": ["198.51.100.9"]})
        B.save("forge", ["203.0.113.7"])
        self.assertTrue(B.forget("forge"))
        self.assertEqual(["198.51.100.9"], B.read()["forge"])

    def test_a_dict_entry_is_read_for_its_networks(self):
        self.ecrire(
            B.TEAM, {"forge": {"networks": ["198.51.100.9"], "ports": [22]}}
        )
        self.assertEqual(["198.51.100.9"], B.shared_networks("forge"))

    def test_a_bare_string_counts_as_one_network(self):
        self.ecrire(B.TEAM, {"forge": "198.51.100.9"})
        self.assertEqual(["198.51.100.9"], B.shared_networks("forge"))


class TestLaSaisieEstControleeAvantDEtreEcrite(CarnetDeBanc):
    """Le contrôle avait lieu au DÉPLOIEMENT : une faute de frappe se
    découvrait après un formulaire entier."""

    def test_a_hostname_is_refused(self):
        """« Le résoudre figerait l'adresse. »"""
        with self.assertRaises(ValidationError):
            B.save("forge", ["forge.example"])

    def test_the_default_route_is_refused(self):
        with self.assertRaises(ValidationError):
            B.save("forge", ["0.0.0.0/0"])

    def test_an_over_wide_prefix_is_refused(self):
        with self.assertRaises(ValidationError):
            B.save("forge", ["10.0.0.0/8"])

    def test_an_empty_list_is_refused(self):
        with self.assertRaises(ValidationError):
            B.save("forge", [])

    def test_a_refused_entry_writes_nothing(self):
        """Un carnet à moitié valide se relit sans se plaindre."""
        with self.assertRaises(ValidationError):
            B.save("forge", ["forge.example"])
        self.assertEqual({}, B.machine_book())

    def test_a_good_address_is_normalised_and_written(self):
        """Contrôle positif : tout refuser rendrait le carnet
        inutilisable."""
        B.save("forge", ["203.0.113.7"])
        self.assertEqual(["203.0.113.7/32"], B.machine_book()["forge"])

    def test_an_unknown_role_is_refused_by_name(self):
        with self.assertRaises(ValidationError):
            B.save("role-jamais-declare", ["203.0.113.7"])


class TestLEcritureVaDansLeBonFichier(CarnetDeBanc):
    def test_it_writes_the_machine_file_and_not_the_others(self):
        B.save("vault", ["203.0.113.8"])
        self.assertEqual({}, B.by_source()[B.TEAM])
        self.assertEqual({}, B.by_source()[B.TRACKED])
        self.assertIn("vault", B.by_source()[B.MACHINE])

    def test_the_machine_file_is_owner_only(self):
        """Il nomme les machines d'un site : c'est une carte, et une carte
        se garde."""
        B.save("vault", ["203.0.113.8"])
        mode = stat.S_IMODE(os.stat(self.chemins[B.MACHINE]).st_mode)
        self.assertEqual(0o600, mode, oct(mode))

    def test_writing_starts_from_the_machine_book_and_not_the_merge(self):
        """Réécrire la fusion recopierait les adresses de l'équipe ici,
        qui se retrouveraient en DOUBLE à la lecture suivante."""
        self.ecrire(B.TEAM, {"forge": ["198.51.100.9"]})
        B.save("vault", ["203.0.113.8"])
        self.assertNotIn("forge", B.machine_book())
        self.assertEqual(["198.51.100.9"], B.read()["forge"])

    def test_saving_twice_replaces_and_does_not_double(self):
        B.save("vault", ["203.0.113.8"])
        B.save("vault", ["203.0.113.9"])
        self.assertEqual(["203.0.113.9/32"], B.machine_book()["vault"])

    def test_a_role_with_its_own_ports_keeps_them(self):
        """Un site sert parfois le même rôle sur un autre port."""
        B.save("forge", ["203.0.113.7"], ports=[2222])
        entree = B.machine_book()["forge"]
        self.assertEqual([2222], entree["ports"])

    def test_the_roles_own_ports_are_not_frozen_into_the_book(self):
        """`resolve` remplit ceux du rôle quand le site se tait. Les
        recopier ici en ferait une copie FIGÉE de ce que le dépôt possède :
        un rôle qui gagnerait un port demain garderait l'ancien, et la
        liste blanche fermerait un port que le dépôt croit ouvert.
        """
        from script.posture import allowlist

        defaut = allowlist.get("forge").ports
        self.assertTrue(defaut, "le rôle n'a plus de port : rien n'est prouvé")
        B.save("forge", ["203.0.113.7"])
        entree = B.machine_book()["forge"]
        self.assertNotIsInstance(entree, dict)
        self.assertEqual(["203.0.113.7/32"], entree)

    def test_the_deploy_still_gets_the_roles_own_ports(self):
        """Contrôle positif : ne pas les écrire ne doit pas les perdre —
        c'est `resolve` qui les rend, au déploiement."""
        from script.posture import allowlist

        B.save("forge", ["203.0.113.7"])
        permis = allowlist.resolve("forge", B.read()["forge"])
        self.assertEqual(allowlist.get("forge").ports, permis.ports)

    def test_forgetting_says_no_when_it_was_not_here(self):
        self.assertFalse(B.forget("jamais-vu"))

    def test_forgetting_removes_it_from_the_machine_book(self):
        B.save("vault", ["203.0.113.8"])
        self.assertTrue(B.forget("vault"))
        self.assertEqual({}, B.machine_book())


class TestLeCheminDeDeploiementPasseParLa(CarnetDeBanc):
    """Lire directement laisserait le refus du fichier suivi hors du chemin
    emprunté — le motif que ce dépôt combat."""

    def test_the_deploy_reads_the_book_through_this_module(self):
        chemin = os.path.join(RACINE, "script", "todo", "qemu_deploy.py")
        with open(chemin, encoding="utf-8") as fichier:
            source = fichier.read()
        self.assertIn("egress_book.read(", source)
        self.assertNotIn(
            "self.config_file.get_config(self.EGRESS_BOOK_KEY)", source
        )

    def test_the_key_is_relayed_and_not_copied(self):
        import sys as _sys

        _sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        self.assertEqual(B.BOOK_KEY, TODO.EGRESS_BOOK_KEY)


if __name__ == "__main__":
    unittest.main()
