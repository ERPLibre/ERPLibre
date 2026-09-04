#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu VPN : le chemin que l'utilisateur emprunte vraiment.

Les pilotes sont testés ailleurs. Ici on vérifie que le FORMULAIRE reste
agnostique : il déroule les questions déclarées par le pilote choisi, sans
rien savoir de L2TP ni de WireGuard. C'est ce qui fait qu'ajouter une
technologie n'ajoute pas une ligne au menu — et c'est donc ce qui doit
casser bruyamment si quelqu'un y remet un cas particulier.

Aucune saisie réelle : `input` est remplacé par une liste de réponses, dans
l'ordre où les questions sont posées.
"""

import base64
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)
sys.argv = ["todo.py"]

from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402
from script.todo.vpn_menu import (  # noqa: E402
    DRIVER_LETTERS,
    UNPROVEN_NOTE,
    match_driver,
)
from script.vpn import profiles  # noqa: E402
from script.vpn.drivers import DRIVERS  # noqa: E402

WG_PUBLIC = base64.b64encode(bytes(range(32, 64))).decode()


class MenuBase(unittest.TestCase):
    """Les trois fichiers de configuration dans un temporaire : un test qui
    écrirait dans le fichier privé détruirait les profils de qui le lance."""

    def setUp(self):
        self.todo = TODO()
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.join(self.tmp.name, "todo.json")
        with open(base, "w") as fh:
            json.dump({"vpn": [], "kdbx": {"path": "", "password": ""}}, fh)
        self.patches = [
            patch("script.config.config_file.CONFIG_FILE", base),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_FILE",
                os.path.join(self.tmp.name, "override.json"),
            ),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
                os.path.join(self.tmp.name, "private.json"),
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def answering(self, *answers):
        """Remplace `input` par une suite de réponses. Une question de plus
        que prévu lève StopIteration — et c'est bien : cela veut dire que le
        formulaire a changé sans que le test le sache."""
        return patch("builtins.input", side_effect=list(answers))


class MatchDriver(unittest.TestCase):
    """La correspondance est pure : elle se juge sans menu ni saisie.

    Elle existe parce qu'une liste numérotée juste après un menu numéroté
    fait taper un numéro de menu — et que devant « [L2TP/IPsec PSK] », on
    tape « L ». Les deux doivent marcher.
    """

    def setUp(self):
        self.names = list(DRIVERS)

    def test_the_displayed_letter(self):
        for index, name in enumerate(self.names):
            with self.subTest(name=name):
                letter = DRIVER_LETTERS[index]
                self.assertEqual(match_driver(letter, self.names), name)
                self.assertEqual(
                    match_driver(letter.upper(), self.names), name
                )

    def test_the_rank_still_works(self):
        """Quelqu'un tapera un chiffre, et il a raison de le faire vu le
        menu qui précède."""
        for index, name in enumerate(self.names, start=1):
            with self.subTest(rang=index):
                self.assertEqual(match_driver(str(index), self.names), name)

    def test_the_start_of_the_label(self):
        """« L » devant « L2TP/IPsec PSK » : le geste qui a motivé tout
        ceci."""
        for answer, expected in (
            ("L", "l2tp_ipsec"),
            ("l2tp", "l2tp_ipsec"),
            ("w", "wireguard"),
            ("WireG", "wireguard"),
            ("openv", "openvpn"),
            ("openc", "openconnect"),
            ("ssh", "sshuttle"),
        ):
            with self.subTest(answer=answer):
                self.assertEqual(match_driver(answer, self.names), expected)

    def test_an_ambiguous_prefix_names_the_candidates(self):
        """« open » désigne deux pilotes : le dire vaut mieux qu'en choisir
        un au hasard."""
        result = match_driver("open", self.names)
        self.assertIsInstance(result, list)
        self.assertEqual(sorted(result), ["openconnect", "openvpn"])

    def test_nothing_matches_nothing(self):
        for answer in ("x", "9", "0", "", "   ", "carrier-pigeon"):
            with self.subTest(answer=answer):
                self.assertEqual(match_driver(answer, self.names), "")


class DriverPicker(MenuBase):
    def test_an_empty_answer_keeps_the_current_driver(self):
        with self.answering(""):
            with redirect_stdout(io.StringIO()):
                chosen = self.todo._vpn_pick_driver("wireguard")
        self.assertEqual(chosen.name, "wireguard")

    def test_a_letter_picks_from_the_list(self):
        names = list(DRIVERS)
        with self.answering("c"):
            with redirect_stdout(io.StringIO()):
                chosen = self.todo._vpn_pick_driver(None)
        self.assertEqual(chosen.name, names[2])

    def test_a_number_still_picks_from_the_list(self):
        names = list(DRIVERS)
        with self.answering("3"):
            with redirect_stdout(io.StringIO()):
                chosen = self.todo._vpn_pick_driver(None)
        self.assertEqual(chosen.name, names[2])

    def test_the_start_of_a_label_picks_too(self):
        with self.answering("L"):
            with redirect_stdout(io.StringIO()):
                chosen = self.todo._vpn_pick_driver(None)
        self.assertEqual(chosen.name, "l2tp_ipsec")

    def test_the_list_is_lettered_and_offers_a_way_back(self):
        buffer = io.StringIO()
        with self.answering(""):
            with redirect_stdout(buffer):
                self.todo._vpn_pick_driver(None)
        printed = buffer.getvalue()
        for letter in DRIVER_LETTERS[: len(DRIVERS)]:
            self.assertIn(f"[{letter}]", printed)
        self.assertNotIn("[1]", printed)
        self.assertIn("[0]", printed)

    def test_zero_goes_back_without_scolding(self):
        """Sans sortie explicite, on est coincé dans le formulaire dès
        qu'on a tapé un nom de profil."""
        buffer = io.StringIO()
        with self.answering("0"):
            with redirect_stdout(buffer):
                self.assertIsNone(self.todo._vpn_pick_driver(None))
        self.assertNotIn("✗", buffer.getvalue())
        self.assertNotIn("inconnu", buffer.getvalue().lower())

    def test_an_ambiguous_answer_says_which_ones(self):
        buffer = io.StringIO()
        with self.answering("open"):
            with redirect_stdout(buffer):
                self.assertIsNone(self.todo._vpn_pick_driver(None))
        printed = buffer.getvalue()
        self.assertIn("OpenVPN", printed)
        self.assertIn("OpenConnect", printed)

    def test_an_out_of_range_answer_gives_up(self):
        with self.answering("99"):
            with redirect_stdout(io.StringIO()):
                self.assertIsNone(self.todo._vpn_pick_driver(None))

    def test_every_driver_shows_its_hint(self):
        """C'est la seule décision où l'utilisateur a besoin d'un conseil."""
        buffer = io.StringIO()
        with self.answering(""):
            with redirect_stdout(buffer):
                self.todo._vpn_pick_driver(None)
        printed = buffer.getvalue()
        for cls in DRIVERS.values():
            self.assertIn(cls.label, printed)

    def test_only_the_unproven_technologies_wear_a_star(self):
        """Sans marque, la liste montre des choix d'apparence égale, et
        rien ne dit lequel a déjà abouti contre un vrai serveur."""
        buffer = io.StringIO()
        with self.answering(""):
            with redirect_stdout(buffer):
                self.todo._vpn_pick_driver(None)
        starred = {
            line.split("]")[1].strip().split(" ")[0]
            for line in buffer.getvalue().splitlines()
            if line.startswith("[") and "*" in line
        }
        expected = {
            cls.label.split(" ")[0]
            for cls in DRIVERS.values()
            if not cls.proven
        }
        self.assertEqual(starred, expected)

    def test_the_star_is_explained(self):
        """Une marque sans légende inquiète sans informer."""
        buffer = io.StringIO()
        with self.answering(""):
            with redirect_stdout(buffer):
                self.todo._vpn_pick_driver(None)
        self.assertIn(t(UNPROVEN_NOTE), buffer.getvalue())


class TheFormIsDriverAgnostic(MenuBase):
    def test_it_builds_a_wireguard_profile_from_typed_answers(self):
        names = list(DRIVERS)
        answers = [
            "acme-wg",  # nom du profil
            DRIVER_LETTERS[names.index("wireguard")],  # technologie
            "vpn.acme.example",  # serveur
            "10.7.0.2/32",  # wg_address
            WG_PUBLIC,  # wg_peer_key
            "10.7.0.0/24",  # réseaux
            "",  # tout le trafic ? défaut non
            "",  # témoin
            "n",  # réglages avancés ?
        ]
        with self.answering(*answers):
            with redirect_stdout(io.StringIO()):
                self.todo._vpn_edit_profile()
        saved = profiles.load("acme-wg")
        self.assertIsNotNone(saved, "profil non enregistré")
        self.assertEqual(saved["driver"], "wireguard")
        self.assertEqual(saved["wg_address"], "10.7.0.2/32")
        self.assertEqual(saved["wg_peer_key"], WG_PUBLIC)
        self.assertEqual(saved["routes"], ["10.7.0.0/24"])
        self.assertFalse(saved["default_route"])
        # Le défaut du pilote, jamais demandé, doit être là quand même.
        self.assertEqual(saved["port"], 51820)

    def test_it_builds_an_sshuttle_profile_with_no_secret_question(self):
        names = list(DRIVERS)
        answers = [
            "acme-ssh",
            DRIVER_LETTERS[names.index("sshuttle")],
            "erplibre@bastion.acme.example",
            "10.40.0.0/16",
            "",
            "10.40.0.1",  # témoin
            "n",  # pas de réglages avancés
        ]
        with self.answering(*answers):
            with redirect_stdout(io.StringIO()):
                self.todo._vpn_edit_profile()
        saved = profiles.load("acme-ssh")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["server"], "erplibre@bastion.acme.example")
        self.assertEqual(saved["probe"], "10.40.0.1")

    def test_the_mtu_is_not_asked_when_the_driver_ignores_it(self):
        """sshuttle ne prend pas le MTU du profil : le demander serait une
        question sans effet. Si le formulaire le demandait, la liste de
        réponses serait épuisée et le test lèverait StopIteration."""
        names = list(DRIVERS)
        answers = [
            "acme-ssh2",
            str(names.index("sshuttle") + 1),
            "bastion.acme.example",
            "10.41.0.0/16",
            "",
            "",
            "o",  # réglages avancés OUI
            "2222",  # port SSH
            "",  # DNS dans le tunnel : défaut
        ]
        with self.answering(*answers):
            with redirect_stdout(io.StringIO()):
                self.todo._vpn_edit_profile()
        saved = profiles.load("acme-ssh2")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["port"], 2222)

    def test_editing_keeps_what_is_not_retyped(self):
        profiles.save(
            {
                "name": "acme-wg",
                "driver": "wireguard",
                "server": "vpn.acme.example",
                "wg_address": "10.7.0.2/32",
                "wg_peer_key": WG_PUBLIC,
                "routes": ["10.7.0.0/24"],
                "wg_keepalive": 17,
            }
        )
        names = list(DRIVERS)
        answers = [
            "acme-wg",
            str(names.index("wireguard") + 1),
            "",  # serveur inchangé
            "",  # wg_address inchangée
            "",  # wg_peer_key inchangée
            "10.7.0.0/24, 10.9.0.0/16",  # routes élargies
            "",
            "",
            "n",
        ]
        with self.answering(*answers):
            with redirect_stdout(io.StringIO()):
                self.todo._vpn_edit_profile()
        saved = profiles.load("acme-wg")
        self.assertEqual(saved["server"], "vpn.acme.example")
        self.assertEqual(saved["wg_peer_key"], WG_PUBLIC)
        self.assertEqual(saved["routes"], ["10.7.0.0/24", "10.9.0.0/16"])
        # Un réglage avancé jamais réaffiché ne doit pas être perdu.
        self.assertEqual(saved["wg_keepalive"], 17)

    def test_a_refused_profile_saves_nothing(self):
        names = list(DRIVERS)
        answers = [
            "acme-bad",
            str(names.index("wireguard") + 1),
            "vpn.acme.example",
            "10.7.0.2/32",
            "pas-une-cle",  # clé de pair invalide
            "10.7.0.0/24",
            "",
            "",
            "n",
        ]
        buffer = io.StringIO()
        with self.answering(*answers):
            with redirect_stdout(buffer):
                self.todo._vpn_edit_profile()
        self.assertIsNone(profiles.load("acme-bad"))
        self.assertIn("✗", buffer.getvalue())


class OnlyWhatTheSiteGaveYou(MenuBase):
    """Le cas réel : le site remet une passerelle, un utilisateur, un mot de
    passe et une clé. Rien sur les réseaux derrière.

    Ce profil DOIT s'enregistrer. Il ne joint que l'hôte distant, le menu le
    dit, et le premier montage proposera le réseau que l'adresse révèle —
    refuser l'enregistrement laissait sans issue.
    """

    def test_a_profile_without_routes_is_accepted_and_flagged(self):
        names = list(DRIVERS)
        answers = [
            "novipro",
            DRIVER_LETTERS[names.index("l2tp_ipsec")],
            "vpn.novipro.example",  # la passerelle
            "user",  # l'utilisateur PPP
            "",  # réseaux : le site n'en a pas donné
            "",  # tout le trafic ? non
            "",  # témoin
            "n",
        ]
        buffer = io.StringIO()
        with self.answering(*answers):
            with redirect_stdout(buffer):
                self.todo._vpn_edit_profile()
        saved = profiles.load("novipro")
        self.assertIsNotNone(saved, "profil refusé alors qu'il est utilisable")
        self.assertEqual(saved["routes"], [])
        self.assertFalse(saved["default_route"])
        printed = buffer.getvalue()
        self.assertIn("✓", printed)
        self.assertIn("hôte distant", printed)

    def test_the_first_mount_suggests_the_network(self):
        """Sans route déclarée, le montage propose le /24 de l'adresse
        obtenue — en disant que c'est une hypothèse."""
        from script.vpn.drivers.l2tp_ipsec import L2tpIpsecDriver
        from script.vpn.runner import Runner

        profile = profiles.validate(
            {
                "name": "novipro",
                "driver": "l2tp_ipsec",
                "server": "127.0.0.1",
                "ppp_user": "user",
            }
        )
        driver = L2tpIpsecDriver(profile, {"psk": "x", "password": "y"})
        runner = Runner(dry_run=True)
        buffer = io.StringIO()
        with patch(
            "script.vpn.drivers.base.interface_addresses",
            return_value=["192.168.50.20", "192.168.50.1"],
        ):
            with redirect_stdout(buffer):
                driver.suggest_routes(runner, "ppp0")
        printed = buffer.getvalue()
        self.assertIn("192.168.50.0/24", printed)
        self.assertIn("hypothèse", printed)

    def test_nothing_is_suggested_when_routes_are_declared(self):
        """La suggestion ne s'invite pas quand la question est réglée."""
        from script.vpn.drivers.l2tp_ipsec import L2tpIpsecDriver
        from script.vpn.runner import Runner

        profile = profiles.validate(
            {
                "name": "novipro",
                "driver": "l2tp_ipsec",
                "server": "127.0.0.1",
                "ppp_user": "user",
                "routes": ["10.20.0.0/16"],
            }
        )
        driver = L2tpIpsecDriver(profile, {"psk": "x", "password": "y"})
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            driver.suggest_routes(Runner(dry_run=True), "ppp0")
        self.assertEqual(buffer.getvalue(), "")

    def test_wireguard_still_requires_its_allowed_ips(self):
        """L'exigence reste DURE là où elle l'est vraiment : sans
        AllowedIPs, wg-quick refuse la configuration entière."""
        from script.vpn.valid import ProfileError

        with self.assertRaises(ProfileError):
            profiles.validate(
                {
                    "name": "beta",
                    "driver": "wireguard",
                    "server": "127.0.0.1",
                    "wg_address": "10.7.0.2/32",
                    "wg_peer_key": WG_PUBLIC,
                }
            )


class SecretsOnlyWhenThereAreSome(MenuBase):
    def test_a_driver_without_secrets_does_not_open_the_vault(self):
        """sshuttle s'authentifie par SSH. Demander le mot de passe maître
        du coffre pour lui serait une saisie pour rien."""
        profiles.save(
            {
                "name": "acme-ssh",
                "driver": "sshuttle",
                "server": "bastion.acme.example",
                "routes": ["10.40.0.0/16"],
            }
        )
        buffer = io.StringIO()
        with patch.object(
            self.todo, "_vpn_select_profile", return_value="acme-ssh"
        ):
            with patch.object(self.todo.kdbx_manager, "get_kdbx") as opened:
                with redirect_stdout(buffer):
                    self.todo._vpn_store_secrets()
        opened.assert_not_called()
        self.assertIn("SSH", buffer.getvalue())

    def test_creating_the_vault_does_not_reask_the_master_password(self):
        """Six saisies masquées, pas sept.

        Deux pour créer le coffre, quatre pour les deux secrets confirmés.
        `create_database` rend la base DÉJÀ ouverte : sans l'adopter, le mot
        de passe maître était redemandé dans la seconde suivant les deux
        saisies de la création.
        """
        profiles.save(
            {
                "name": "novipro",
                "driver": "l2tp_ipsec",
                "server": "vpn.novipro.example",
                "ppp_user": "user",
            }
        )
        coffre = os.path.join(self.tmp.name, "secrets.kdbx")
        typed = []

        def masked(prompt=""):
            typed.append(prompt)
            if len(typed) <= 2:
                return "maitre"
            return "secret"

        with patch.object(
            self.todo, "_vpn_select_profile", return_value="novipro"
        ):
            with self.answering(coffre, "o"):
                with patch("getpass.getpass", masked):
                    with redirect_stdout(io.StringIO()):
                        self.todo._vpn_store_secrets()
        self.assertEqual(len(typed), 6, typed)
        self.assertTrue(os.path.exists(coffre))

    def test_an_empty_answer_on_an_empty_field_is_reported(self):
        """« Une réponse vide garde la valeur en place » est un piège quand
        il n'y a RIEN en place : le secret restait vide en silence, et le
        premier montage échouait sur « Secrets manquants ». L'invite dit
        maintenant l'état, et le bilan nomme ce qui manque encore.
        """
        profiles.save(
            {
                "name": "novipro",
                "driver": "l2tp_ipsec",
                "server": "vpn.novipro.example",
                "ppp_user": "user",
            }
        )
        coffre = os.path.join(self.tmp.name, "secrets.kdbx")
        typed = []

        def masked(prompt=""):
            typed.append(prompt)
            if len(typed) <= 2:
                return "maitre"
            # La PSK et sa confirmation, puis Entrée sur le mot de passe.
            return "LaClePSK" if len(typed) <= 4 else ""

        buffer = io.StringIO()
        with patch.object(
            self.todo, "_vpn_select_profile", return_value="novipro"
        ):
            with self.answering(coffre, "o"):
                with patch("getpass.getpass", masked):
                    with redirect_stdout(buffer):
                        self.todo._vpn_store_secrets()
        printed = buffer.getvalue()
        self.assertIn("Mot de passe PPP", printed)
        self.assertIn("Toujours manquant", printed)
        # Chaque invite annonce ce qu'il y a derrière.
        self.assertTrue(
            [p for p in typed if "[vide]" in p],
            typed,
        )

    def test_a_field_already_set_says_so(self):
        profiles.save(
            {
                "name": "novipro",
                "driver": "l2tp_ipsec",
                "server": "vpn.novipro.example",
                "ppp_user": "user",
            }
        )
        coffre = os.path.join(self.tmp.name, "secrets.kdbx")
        typed = []

        def masked(prompt=""):
            typed.append(prompt)
            if len(typed) <= 2:
                return "maitre"
            return "valeur"

        with patch.object(
            self.todo, "_vpn_select_profile", return_value="novipro"
        ):
            with self.answering(coffre, "o"):
                with patch("getpass.getpass", masked):
                    with redirect_stdout(io.StringIO()):
                        self.todo._vpn_store_secrets()
            # Deuxième passage : tout est en place, et les invites le disent.
            typed.clear()
            with patch(
                "getpass.getpass",
                lambda prompt="": (typed.append(prompt) or ""),
            ):
                with redirect_stdout(io.StringIO()):
                    self.todo._vpn_store_secrets()
        self.assertTrue([p for p in typed if "[déjà en place]" in p], typed)
        self.assertFalse([p for p in typed if "[vide]" in p], typed)

    def test_a_mismatched_confirmation_stores_nothing(self):
        with patch("getpass.getpass", side_effect=["un", "deux"]):
            with redirect_stdout(io.StringIO()):
                self.assertIsNone(self.todo._vpn_ask_secret("PSK"))

    def test_an_empty_answer_keeps_the_stored_value(self):
        with patch("getpass.getpass", return_value=""):
            self.assertEqual(self.todo._vpn_ask_secret("PSK"), "")


class FromPreset(MenuBase):
    """Le chemin « créer un profil à partir d'un préréglage ».

    Le préréglage porte ce que l'établissement publie ; il ne reste qu'un
    identifiant à taper. Le formulaire est celui de `_vpn_edit_profile`,
    amorcé — dupliquer les questions ferait vivre deux formulaires qui
    divergeraient au prochain champ ajouté à un pilote.
    """

    # Passerelle INVENTÉE : voir la règle du dépôt sur ce qu'un exemple
    # a le droit de nommer.
    PRESET = {
        "preset": "campus",
        "label": "Campus SSL VPN",
        "driver": "openconnect",
        "server": "ssl.vpn.example-campus.net",
        "oc_protocol": "anyconnect",
        "oc_usergroup": "SSLProfileCampus",
        "oc_authgroup": "CampusSSL",
        "oc_password_len": 8,
    }

    def choosing(self, *answers):
        """Le préréglage servi sans toucher au disque, et les réponses."""
        return patch(
            "script.vpn.presets.load_all",
            return_value=([dict(self.PRESET)], []),
        ), self.answering(*answers)

    def test_only_the_identity_is_left_to_type(self):
        """Aucune question sur la technologie : le préréglage y a répondu.
        Si le formulaire la posait, la liste de réponses serait décalée et
        le profil ne porterait pas les bonnes valeurs."""
        loading, answering = self.choosing(
            "1",  # le préréglage
            "campus_me",  # nom du profil
            "",  # serveur : celui du préréglage
            "someone",  # oc_user
            "",  # protocole
            "",  # groupe de connexion (chemin d'URL)
            "",  # SSO ? défaut non
            "",  # réseaux
            "",  # tout le trafic ? défaut non
            "",  # témoin
            "n",  # réglages avancés ?
        )
        with loading:
            with answering:
                with redirect_stdout(io.StringIO()):
                    self.todo._vpn_from_preset()
        saved = profiles.load("campus_me")
        self.assertIsNotNone(saved, "profil non enregistré")
        self.assertEqual(saved["driver"], "openconnect")
        self.assertEqual(saved["server"], self.PRESET["server"])
        # Le chemin d'URL : le champ qui décide QUEL service du
        # concentrateur on joint, et celui qu'on ne devine pas.
        self.assertEqual(saved["oc_usergroup"], "SSLProfileCampus")
        self.assertEqual(saved["oc_authgroup"], "CampusSSL")
        self.assertEqual(saved["oc_user"], "someone")
        # La borne du concentrateur est un réglage AVANCÉ, jamais demandé
        # ici : elle doit venir du préréglage quand même.
        self.assertEqual(saved["oc_password_len"], 8)

    def test_going_back_saves_nothing(self):
        loading, answering = self.choosing("0")
        with loading:
            with answering:
                with redirect_stdout(io.StringIO()):
                    self.todo._vpn_from_preset()
        self.assertEqual(profiles.names(), [])

    def test_an_unreadable_preset_is_reported(self):
        with patch(
            "script.vpn.presets.load_all",
            return_value=([], ["campus.json : ligne 3"]),
        ):
            with redirect_stdout(io.StringIO()) as out:
                self.todo._vpn_from_preset()
        self.assertIn("campus.json", out.getvalue())

    def test_replaying_refreshes_the_gateway_and_keeps_the_identity(self):
        """Rejouer un préréglage sur un profil existant sert à le remettre à
        jour — passerelle déménagée, groupe renommé. Ce qui est PERSONNEL et
        qu'aucun préréglage ne porte se garde : identifiant, routes ajoutées
        à la main, certificat épinglé."""
        profiles.save(
            {
                "name": "campus_me",
                "driver": "openconnect",
                "server": "ssl.vpn.example-campus.net",
                "oc_user": "someone",
                "oc_authgroup": "OldGroup",
                "oc_servercert": "sha256:abc",
                "routes": ["10.60.0.0/16"],
                "oc_password_len": 0,
            }
        )
        moved = dict(
            self.PRESET,
            server="ssl2.vpn.example-campus.net",
            oc_authgroup="NewGroup",
        )
        with patch("script.vpn.presets.load_all", return_value=([moved], [])):
            with self.answering(
                "1",
                "campus_me",
                "",  # serveur : celui du préréglage, désormais à jour
                "",  # oc_user : gardé
                "",  # protocole
                "",  # groupe de connexion : celui du préréglage
                "",  # SSO ?
                "",  # réseaux : gardés
                "",  # tout le trafic ?
                "",  # témoin
                "n",  # réglages avancés ?
            ):
                with redirect_stdout(io.StringIO()):
                    self.todo._vpn_from_preset()
        saved = profiles.load("campus_me")
        # Le préréglage rafraîchit ce qu'il déclare.
        self.assertEqual(saved["server"], "ssl2.vpn.example-campus.net")
        self.assertEqual(saved["oc_authgroup"], "NewGroup")
        self.assertEqual(saved["oc_password_len"], 8)
        # Le profil garde ce qui est personnel.
        self.assertEqual(saved["oc_user"], "someone")
        self.assertEqual(saved["oc_servercert"], "sha256:abc")
        self.assertEqual(saved["routes"], ["10.60.0.0/16"])

    def test_replaying_over_another_technology_drags_nothing_along(self):
        """Un profil qui change de technologie ne doit pas faire suivre une
        clé WireGuard dans un profil OpenConnect, où rien ne la lirait."""
        profiles.save(
            {
                "name": "campus_me",
                "driver": "wireguard",
                "server": "vpn.acme.example",
                "wg_address": "10.7.0.2/32",
                "wg_peer_key": WG_PUBLIC,
                "routes": ["10.7.0.0/24"],
            }
        )
        loading, answering = self.choosing(
            "1",
            "campus_me",
            "",  # serveur
            "someone",  # oc_user
            "",  # protocole
            "",  # groupe de connexion
            "",  # SSO ?
            "",  # réseaux
            "",  # tout le trafic ?
            "",  # témoin
            "n",  # réglages avancés ?
        )
        with loading:
            with answering:
                with redirect_stdout(io.StringIO()):
                    self.todo._vpn_from_preset()
        saved = profiles.load("campus_me")
        self.assertEqual(saved["driver"], "openconnect")
        self.assertNotIn("wg_peer_key", saved)
        self.assertNotIn("wg_address", saved)

    def test_no_preset_says_where_to_put_one(self):
        with patch("script.vpn.presets.load_all", return_value=([], [])):
            with redirect_stdout(io.StringIO()) as out:
                self.todo._vpn_from_preset()
        self.assertIn("conf/vpn_presets", out.getvalue())


if __name__ == "__main__":
    unittest.main()
