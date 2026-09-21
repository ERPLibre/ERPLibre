#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La configuration d'une instance Lima, et la lecture de son inventaire.

RIEN ICI N'A ÉTÉ CONFRONTÉ au vrai outil. Ces épreuves tiennent ce qu'on
COMPOSE et ce qu'on ANALYSE — pas ce que « limactl » en fait. La
confrontation est dans `long_test/`, et le backend se déclare non éprouvé
tant qu'elle n'a pas eu lieu.

Le rendu est écrit ligne à ligne pour rester lisible ; il est donc relu ici
par un analyseur YAML, qui rattrape ce que l'écriture manuelle risque de
casser.
"""

import os
import sys
import unittest

import yaml

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script import posture as P  # noqa: E402
from script.vm import lima as L  # noqa: E402

IMAGE = "https://exemple.invalid/ubuntu-24.04-arm64.img"


class TestLeRenduSeRelit(unittest.TestCase):
    """Écrit à la main pour rester commentable, relu par un analyseur."""

    def rendu(self, **kw):
        return yaml.safe_load(L.render_config(IMAGE, **kw))

    def test_it_is_valid_yaml_on_both_systems(self):
        for macos in (False, True):
            with self.subTest(macos=macos):
                self.assertIsInstance(self.rendu(macos=macos), dict)

    def test_the_image_and_the_size_are_what_was_asked(self):
        lu = self.rendu(cpus=8, memory="16GiB", disk="120GiB")
        self.assertEqual(IMAGE, lu["images"][0]["location"])
        self.assertEqual(8, lu["cpus"])
        self.assertEqual("16GiB", lu["memory"])
        self.assertEqual("120GiB", lu["disk"])

    def test_the_architecture_travels_where_it_matters(self):
        lu = self.rendu(arch="aarch64")
        self.assertEqual("aarch64", lu["arch"])
        self.assertEqual("aarch64", lu["images"][0]["arch"])

    def test_nothing_of_the_host_is_ever_mounted(self):
        """Lima monte le répertoire personnel par défaut : une VM censée
        être confinée y lirait tout ce que l'utilisateur possède, sans
        qu'une seule règle réseau soit en cause."""
        for macos in (False, True):
            with self.subTest(macos=macos):
                self.assertEqual([], self.rendu(macos=macos)["mounts"])

    def test_the_host_keys_stay_on_the_host_by_default(self):
        """Le canal d'exec passe par la clé que l'outil génère : l'invité
        n'a pas à connaître les identités de qui le lance."""
        self.assertFalse(self.rendu()["ssh"]["loadDotSSHPubKeys"])
        self.assertTrue(
            self.rendu(load_host_keys=True)["ssh"]["loadDotSSHPubKeys"]
        )


class TestCeQuiNExistePasPartout(unittest.TestCase):
    """Deux réglages font ÉCHOUER le démarrage là où ils n'existent pas."""

    def rendu(self, **kw):
        return yaml.safe_load(L.render_config(IMAGE, **kw))

    def test_the_apple_engine_is_named_only_on_macos(self):
        self.assertEqual(L.VM_TYPE_MACOS, self.rendu(macos=True)["vmType"])
        self.assertNotIn("vmType", self.rendu(macos=False))

    def test_a_reachable_address_is_asked_for_only_on_macos(self):
        """Elle passe par socket_vmnet, qui n'existe pas ailleurs."""
        self.assertIn("networks", self.rendu(macos=True, reachable=True))
        self.assertNotIn("networks", self.rendu(macos=False, reachable=True))

    def test_without_asking_there_is_no_network_block(self):
        """Contrôle positif : le bloc n'est pas systématique."""
        self.assertNotIn("networks", self.rendu(macos=True))


class TestCeQueLaConfigurationNeTientPas(unittest.TestCase):
    """Une configuration muette sur ce qu'elle n'applique pas fait croire à
    un confinement qui n'existe pas."""

    def test_no_posture_promises_nothing(self):
        self.assertEqual((), L.unenforceable(None))

    def test_cutting_egress_is_beyond_an_instance_file(self):
        """Le réseau en mode utilisateur donne TOUJOURS la sortie, et aucun
        réglage d'instance ne la retire."""
        self.assertIn(
            "egress-none",
            L.unenforceable(P.get_posture("local-only"), macos=True),
        )

    def test_an_allowlist_is_beyond_it_too(self):
        """Elle se pose dans l'invité, pas dans la description."""
        self.assertIn(
            "destinations-bounded",
            L.unenforceable(P.get_posture("paranoid"), macos=True),
        )

    def test_a_reachable_address_is_missing_off_macos(self):
        self.assertIn(
            "reachable-address", L.unenforceable(P.get_posture("open"))
        )
        self.assertNotIn(
            "reachable-address",
            L.unenforceable(P.get_posture("open"), macos=True),
        )

    def test_the_freest_posture_is_fully_holdable_on_macos(self):
        """Contrôle positif : tout déclarer manquant ne prouverait rien."""
        self.assertEqual(
            (), L.unenforceable(P.get_posture("open"), macos=True)
        )

    def test_every_posture_gets_an_answer(self):
        for nom in P.posture_names():
            with self.subTest(posture=nom):
                self.assertIsInstance(
                    L.unenforceable(P.get_posture(nom), macos=True), tuple
                )


class TestLireLInventaire(unittest.TestCase):
    """Deux formes acceptées, et ce n'est pas de l'indécision : selon la
    version, l'inventaire rend un objet par ligne ou un tableau unique.
    Parier sur l'une rendrait une liste vide sur l'autre — et une liste vide
    se lit comme « aucune instance », ce qui est un mensonge tranquille."""

    LIGNES = (
        '{"name":"a","status":"Running","arch":"aarch64",'
        '"sshLocalPort":60022}\n'
        '{"name":"b","status":"Stopped"}'
    )
    TABLEAU = (
        '[{"name":"a","status":"Running"},{"name":"b","status":"Stopped"}]'
    )

    def test_one_object_per_line_is_read(self):
        vues = L.parse_instances(self.LIGNES)
        self.assertEqual(["a", "b"], [i.name for i in vues])
        self.assertEqual("60022", vues[0].ssh_port)

    def test_a_single_array_is_read_too(self):
        self.assertEqual(
            ["a", "b"], [i.name for i in L.parse_instances(self.TABLEAU)]
        )

    def test_both_forms_agree_on_what_runs(self):
        for nom, texte in (("lignes", self.LIGNES), ("tableau", self.TABLEAU)):
            with self.subTest(forme=nom):
                vues = L.parse_instances(texte)
                self.assertEqual(
                    [True, False], [L.is_running(i) for i in vues]
                )

    def test_a_truncated_line_does_not_lose_the_others(self):
        """Une instance en cours de création peut produire une ligne
        partielle ; perdre les autres pour elle serait pire."""
        vues = L.parse_instances(self.LIGNES + "\n{ tronqué")
        self.assertEqual(["a", "b"], [i.name for i in vues])

    def test_an_entry_without_a_name_is_dropped(self):
        self.assertEqual((), L.parse_instances('{"status":"Running"}'))

    def test_nothing_reads_as_nothing(self):
        for texte in ("", "   ", None, "pas du json du tout"):
            with self.subTest(texte=texte):
                self.assertEqual((), L.parse_instances(texte))

    def test_the_running_state_is_read_without_case(self):
        """La valeur est un mot capitalisé ; un jour minuscule ferait
        passer une instance vivante pour éteinte."""
        for mot in ("Running", "running", "RUNNING"):
            with self.subTest(mot=mot):
                vues = L.parse_instances('{"name":"a","status":"%s"}' % mot)
                self.assertTrue(L.is_running(vues[0]))

    def test_anything_else_is_not_running(self):
        for mot in ("Stopped", "Broken", ""):
            with self.subTest(mot=mot):
                vues = L.parse_instances('{"name":"a","status":"%s"}' % mot)
                self.assertFalse(L.is_running(vues[0]))

    def test_finding_by_name(self):
        vues = L.parse_instances(self.LIGNES)
        self.assertEqual("b", L.find(vues, "b").name)
        self.assertIsNone(L.find(vues, "jamais-vue"))
        self.assertIsNone(L.find((), "a"))


class TestElleNeLanceRien(unittest.TestCase):
    def test_the_module_runs_nothing_and_prints_nothing(self):
        import ast

        chemin = os.path.join(RACINE, "script", "vm", "lima.py")
        with open(chemin, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        noms = [
            n.func.id
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        ]
        self.assertTrue(noms, "aucun appel lu : rien n'est prouvé")
        for interdit in ("print", "input", "run", "system", "Popen"):
            self.assertNotIn(interdit, noms)


if __name__ == "__main__":
    unittest.main()
