#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Instances d'un ERP (script/erp_common/instances) : saisies et registre.

Ce qui se garde :
- le nom d'instance, préfixé de « <erp>_ », tient dans les 32 caractères
  d'un compte système : la borne suit le nom de l'ERP reçu ;
- l'identifiant d'administrateur et le port refusent ce qui casserait argv
  ou demanderait un port privilégié ;
- le registre se lit sous private/<erp>/instances.json ; absent, il est
  vide ; illisible, il LÈVE au lieu de se croire vide.
Chaque test qui dépend du nom de l'ERP tourne pour deux noms.
"""

import json
import os
import sys
import tempfile
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from script.erp_common import instances  # noqa: E402

# Deux noms : celui d'un ERP réel et un nom inventé, pour prouver que rien
# n'est écrit en dur.
ERPS = ("dolibarr", "acme")


class TestInstanceName(unittest.TestCase):
    # Le nom devient nom de base, de pool, d'unité systemd, de répertoire et
    # de compte système « <erp>_<nom> », que useradd borne à 32 caractères :
    # tout ce qui casse l'un de ces usages est refusé.
    ACCEPTES = ("dolibarr", "doli_2", "ab")
    REFUSES = (
        "",
        None,
        "a",  # trop court pour se distinguer
        "Dolibarr",  # majuscule
        "2dolibarr",  # commence par un chiffre
        "doli-barr",  # tiret : invalide en nom de base MariaDB sans quotes
        "doli barr",
        "../etc",
        "doli.barr",
    )

    def test_accepted_names(self):
        for erp in ERPS:
            longest = "a" * instances.instance_name_max(erp)
            for name in self.ACCEPTES + (longest,):
                with self.subTest(erp=erp, name=name):
                    self.assertTrue(instances.valid_instance_name(erp, name))

    def test_refused_names(self):
        for erp in ERPS:
            too_long = "a" * (instances.instance_name_max(erp) + 1)
            for name in self.REFUSES + (too_long,):
                with self.subTest(erp=erp, name=name):
                    self.assertFalse(instances.valid_instance_name(erp, name))

    def test_the_prefixed_account_fits_32_characters(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                longest = instances.instance_name_max(erp)
                self.assertEqual(len(f"{erp}_" + "a" * longest), 32)
        self.assertEqual(instances.instance_name_max("dolibarr"), 23)
        self.assertEqual(instances.instance_name_max("acme"), 27)

    def test_an_erp_name_leaving_no_room_is_refused(self):
        with self.assertRaises(ValueError):
            instances.valid_instance_name("x" * 30, "ab")


class TestLogin(unittest.TestCase):
    # L'identifiant part dans argv et dans la base de l'ERP : ni espace ni
    # métacaractère, et pas d'option déguisée en tête (« -x »).
    ACCEPTES = ("admin", "jean.dupont", "ops@example.org", "a", "x_1-2")
    REFUSES = ("", None, " admin", "adm in", "-x", "x;id", "a" * 51, "é")

    def test_accepted(self):
        for login in self.ACCEPTES:
            with self.subTest(login=login):
                self.assertTrue(instances.valid_login(login))

    def test_refused(self):
        for login in self.REFUSES:
            with self.subTest(login=login):
                self.assertFalse(instances.valid_login(login))


class TestParsePort(unittest.TestCase):
    CAS = (
        ("", 8080, 8080),  # vide : le défaut
        (None, 8080, 8080),
        ("  9000 ", 8080, 9000),
        ("1024", 8080, 1024),
        ("65535", 8080, 65535),
        ("1023", 8080, None),  # privilégié : un utilisateur ne l'ouvre pas
        ("65536", 8080, None),
        ("80a", 8080, None),
        ("-1", 8080, None),
    )

    def test_cases(self):
        for texte, defaut, attendu in self.CAS:
            with self.subTest(texte=texte):
                self.assertEqual(instances.parse_port(texte, defaut), attendu)


class TestFreePort(unittest.TestCase):
    def test_first_free_port_from_the_start(self):
        occupes = {8080, 8081}
        self.assertEqual(
            instances.free_port(8080, lambda p: p not in occupes), 8082
        )

    def test_the_start_itself_when_free(self):
        self.assertEqual(instances.free_port(8080, lambda p: True), 8080)

    def test_none_when_every_port_is_taken(self):
        self.assertIsNone(instances.free_port(8080, lambda p: False, limit=5))


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def _ecrire(self, erp, contenu):
        chemin = os.path.join(self.root, instances.registry_path(erp))
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as f:
            f.write(contenu)

    def test_the_registry_lives_under_private_and_the_erp_name(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                self.assertEqual(
                    instances.registry_path(erp),
                    os.path.join("private", erp, "instances.json"),
                )

    def test_no_registry_means_no_instance(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                self.assertEqual(instances.load_registry(erp, self.root), {})

    def test_instances_are_keyed_by_name(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                self._ecrire(erp, json.dumps({"instances": {"erp": {"m": 1}}}))
                self.assertEqual(
                    instances.load_registry(erp, self.root),
                    {"erp": {"m": 1}},
                )

    def test_each_erp_reads_only_its_own_registry(self):
        self._ecrire("acme", json.dumps({"instances": {"erp": {}}}))
        self.assertEqual(instances.load_registry("dolibarr", self.root), {})
        self.assertEqual(
            instances.load_registry("acme", self.root), {"erp": {}}
        )

    def test_an_unreadable_registry_is_an_error_not_an_empty_one(self):
        # Le lire vide ferait croire qu'aucune instance n'existe, et laisserait
        # installer par-dessus une instance vivante.
        for erp in ERPS:
            with self.subTest(erp=erp):
                self._ecrire(erp, "{ pas du json")
                with self.assertRaises(instances.RegistryError) as cm:
                    instances.load_registry(erp, self.root)
                self.assertTrue(
                    str(cm.exception).startswith(
                        instances.registry_path(erp) + ": "
                    )
                )

    def test_a_registry_without_an_instances_object_is_an_error(self):
        for erp in ERPS:
            for contenu in ("[]", '{"instances": []}', "{}"):
                with self.subTest(erp=erp, contenu=contenu):
                    self._ecrire(erp, contenu)
                    with self.assertRaises(instances.RegistryError):
                        instances.load_registry(erp, self.root)


if __name__ == "__main__":
    unittest.main()
