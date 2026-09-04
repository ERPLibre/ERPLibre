#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Profils VPN : validation et aller-retour sur disque.

Ni root, ni réseau, ni serveur VPN. Les trois fichiers de configuration
fusionnés sont déplacés dans un répertoire temporaire : un test qui écrirait
dans `private/todo/todo_override_private.json` détruirait les profils de la
personne qui le lance.
"""

import json
import os
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.vpn import profiles
from script.vpn.profiles import ProfileError

VALID = {
    "name": "acme",
    "driver": "l2tp_ipsec",
    "server": "vpn.acme.example",
    "ppp_user": "ACME\\user",
    "routes": ["10.20.0.0/16"],
}


class VpnProfileConfig(unittest.TestCase):
    """Fusion et écriture, avec les trois fichiers dans un temporaire."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.join(self.tmp.name, "todo.json")
        with open(base, "w") as fh:
            json.dump({"vpn": []}, fh)
        self.private = os.path.join(self.tmp.name, "private.json")
        self.patches = [
            patch("script.config.config_file.CONFIG_FILE", base),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_FILE",
                os.path.join(self.tmp.name, "override.json"),
            ),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
                self.private,
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def test_save_then_load(self):
        profiles.save(VALID)
        loaded = profiles.load("acme")
        self.assertEqual(loaded["server"], "vpn.acme.example")
        self.assertEqual(loaded["routes"], ["10.20.0.0/16"])
        # Les défauts sont appliqués à la lecture.
        self.assertEqual(loaded["mtu"], 1280)
        self.assertFalse(loaded["default_route"])

    def test_private_file_is_owner_only(self):
        """Le fichier des profils est en 0600.

        Il ne contient pas de secret, mais il nomme les serveurs et les
        utilisateurs d'un client : c'est une carte, et une carte se garde."""
        profiles.save(VALID)
        mode = stat.S_IMODE(os.stat(self.private).st_mode)
        self.assertEqual(mode, 0o600, oct(mode))

    def test_save_twice_updates_in_place(self):
        profiles.save(VALID)
        profiles.save(dict(VALID, server="autre.example"))
        self.assertEqual(len(profiles.load_all()), 1)
        self.assertEqual(profiles.load("acme")["server"], "autre.example")

    def test_delete(self):
        profiles.save(VALID)
        self.assertTrue(profiles.delete("acme"))
        self.assertIsNone(profiles.load("acme"))
        self.assertFalse(profiles.delete("acme"))

    def test_shared_profile_is_not_deletable(self):
        """Un profil venu du fichier partagé se lit mais ne s'efface pas
        d'ici : `delete` doit rendre False, pas faire semblant."""
        with open(os.path.join(self.tmp.name, "todo.json"), "w") as fh:
            json.dump({"vpn": [dict(VALID, name="partage")]}, fh)
        self.assertIsNotNone(profiles.load("partage"))
        self.assertFalse(profiles.delete("partage"))
        self.assertIsNotNone(profiles.load("partage"))

    def test_shared_and_private_do_not_duplicate(self):
        """Écrire un profil privé ne doit pas recopier ceux du partagé.

        La fusion ÉTEND les listes : réécrire la vue fusionnée ferait
        apparaître le profil partagé deux fois à la lecture suivante."""
        with open(os.path.join(self.tmp.name, "todo.json"), "w") as fh:
            json.dump({"vpn": [dict(VALID, name="partage")]}, fh)
        profiles.save(dict(VALID, name="prive"))
        noms = profiles.names()
        self.assertEqual(sorted(noms), ["partage", "prive"], noms)


class VpnProfileValidation(unittest.TestCase):
    def test_valid(self):
        clean = profiles.validate(VALID)
        self.assertEqual(clean["name"], "acme")

    def test_name_must_be_tame(self):
        """Le nom devient un nom de connexion IPsec, de répertoire et de
        fichier : ce qui n'est pas dans l'alphabet prévu est refusé."""
        for bad in ("Acme", "a b", "../evil", "a;rm -rf /", "", "é"):
            with self.assertRaises(ProfileError, msg=bad):
                profiles.validate(dict(VALID, name=bad))

    def test_server_refuses_shell_metacharacters(self):
        for bad in ("vpn.example;reboot", "vpn example", "$(id)", "a|b"):
            with self.assertRaises(ProfileError, msg=bad):
                profiles.validate(dict(VALID, server=bad))

    def test_unknown_driver(self):
        with self.assertRaises(ProfileError):
            profiles.validate(dict(VALID, driver="carrier-pigeon"))

    def test_routes_normalised_to_cidr(self):
        clean = profiles.validate(
            dict(VALID, routes="10.0.0.0/8, 192.168.1.5")
        )
        self.assertEqual(clean["routes"], ["10.0.0.0/8", "192.168.1.5/32"])

    def test_bad_route(self):
        with self.assertRaises(ProfileError):
            profiles.validate(dict(VALID, routes=["10.0.0.0/99"]))

    def test_a_tunnel_without_destination_is_accepted_where_it_helps(self):
        """Ni route déclarée, ni route par défaut : accepté pour L2TP.

        Un site ne remet souvent qu'une passerelle et des identifiants.
        Refuser ce profil laissait sans issue : il joint l'hôte distant, et
        l'adresse qu'on y obtient dit quel réseau ajouter. Le menu le dit,
        et le montage le suggère."""
        clean = profiles.validate(dict(VALID, routes=[], default_route=False))
        self.assertEqual(clean["routes"], [])
        self.assertFalse(clean["default_route"])

    def test_it_stays_refused_where_the_technology_cannot_do_without(self):
        """WireGuard sans AllowedIPs : wg-quick refuse la configuration
        entière. sshuttle sans réseau : rien à détourner. Là, l'exigence
        reste dure."""
        for driver, extra in (
            (
                "wireguard",
                {
                    "wg_address": "10.7.0.2/32",
                    "wg_peer_key": (
                        "SGVsbG9Xb3JsZEV4YW1wbGVLZXkxMjM0NTY3ODkwYWI="
                    ),
                },
            ),
            ("sshuttle", {}),
        ):
            with self.subTest(driver=driver):
                with self.assertRaises(ProfileError):
                    profiles.validate(
                        dict(
                            VALID,
                            driver=driver,
                            routes=[],
                            default_route=False,
                            **extra,
                        )
                    )

    def test_default_route_alone_is_enough(self):
        clean = profiles.validate(dict(VALID, routes=[], default_route=True))
        self.assertTrue(clean["default_route"])

    def test_mtu_bounds(self):
        for bad in (10, 9000, "beaucoup"):
            with self.assertRaises(ProfileError, msg=str(bad)):
                profiles.validate(dict(VALID, mtu=bad))

    def test_probe_must_be_an_address(self):
        with self.assertRaises(ProfileError):
            profiles.validate(dict(VALID, probe="serveur-interne"))
        self.assertEqual(
            profiles.validate(dict(VALID, probe="10.20.0.1"))["probe"],
            "10.20.0.1",
        )

    def test_l2tp_needs_a_ppp_user(self):
        """Exigence propre au pilote, pas au format de profil."""
        with self.assertRaises(ProfileError):
            profiles.validate(dict(VALID, ppp_user=""))

    def test_secret_title_is_derived_from_the_name(self):
        self.assertEqual(profiles.secret_title("acme"), "ERPLibre VPN / acme")


if __name__ == "__main__":
    unittest.main()
