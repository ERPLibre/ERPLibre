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
import unicodedata
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)
sys.argv = ["todo.py"]

from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402
from script.todo.vpn_menu import UNPROVEN_NOTE  # noqa: E402
from script.vpn import profiles  # noqa: E402
from script.vpn.drivers import DRIVERS  # noqa: E402
from script.vpn.drivers.openconnect import (  # noqa: E402
    OpenconnectDriver,
)

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


class DriverPicker(MenuBase):
    """La technologie se choisit par son numéro tel que la liste l'écrit ou
    par son libellé exact ; une réponse vide garde la courante, marquée
    comme le défaut ; toute autre réponse est dite invalide, et la question
    revient. Chaque liste de réponses finit par une réponse acceptée."""

    def picking(self, *answers, current=None):
        """(la technologie choisie ou None, ce qui s'est imprimé)."""
        buffer = io.StringIO()
        with self.answering(*answers), redirect_stdout(buffer):
            chosen = self.todo._vpn_pick_driver(current)
        return chosen, buffer.getvalue()

    def test_an_empty_answer_keeps_the_current_driver(self):
        chosen, printed = self.picking("", current="wireguard")
        self.assertEqual(chosen.name, "wireguard")
        line = next(row for row in printed.splitlines() if "WireGuard" in row)
        self.assertIn(t("(default)"), line)

    def test_a_shown_number_picks_from_the_list(self):
        chosen, _ = self.picking("3")
        self.assertEqual(chosen.name, list(DRIVERS)[2])

    def test_only_the_exact_label_names_a_driver(self):
        # Une lettre, le début d'un libellé et le nom interne ne sont pas
        # des réponses : chacun est dit invalide, et la question revient.
        for answer in ("c", "L", "open", "wireguard", "02", "²"):
            with self.subTest(answer=answer):
                chosen, printed = self.picking(answer, "L2TP/IPsec PSK")
                self.assertEqual(chosen.name, "l2tp_ipsec")
                self.assertIn(f"{t('Invalid choice: ')}{answer}", printed)

    def test_the_list_is_numbered_and_offers_a_way_back(self):
        _, printed = self.picking("")
        for number in range(1, len(DRIVERS) + 1):
            self.assertIn(f"[{number}] ", printed)
        self.assertNotIn("[a]", printed)
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

    def test_an_out_of_range_answer_is_asked_again(self):
        chosen, printed = self.picking("99", "tout", "0")
        self.assertIsNone(chosen)
        self.assertIn(f"{t('Invalid choice: ')}99", printed)
        self.assertIn(f"{t('Invalid choice: ')}tout", printed)

    def test_install_runs_only_for_a_chosen_or_default_driver(self):
        # Installer les paquets d'un client passe par sudo : « 0 », ou une
        # faute suivie de « 0 », n'installent rien ; une réponse vide
        # installe la technologie marquée par défaut, la première.
        launched = []
        for answers, expected in (
            (["0"], []),
            (["x", "0"], []),
            ([""], [f"install --driver {list(DRIVERS)[0]}"]),
        ):
            launched.clear()
            with (
                self.subTest(answers=answers),
                patch(
                    "script.todo.vpn_menu._sso_helper_seen", return_value=True
                ),
                patch.object(
                    self.todo,
                    "_vpn_cli",
                    lambda arguments, secrets_env=None: launched.append(
                        arguments
                    ),
                ),
                self.answering(*answers),
                redirect_stdout(io.StringIO()) as out,
            ):
                self.todo._vpn_install()
            self.assertEqual(launched, expected)
            if "x" in answers:
                self.assertIn(f"{t('Invalid choice: ')}x", out.getvalue())

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
            str(names.index("wireguard") + 1),  # technologie
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
            str(names.index("sshuttle") + 1),
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
    """Un site peut ne remettre qu'une passerelle, un utilisateur, un mot
    de passe et une clé, sans rien sur les réseaux derrière.

    Ce profil DOIT s'enregistrer. Il ne joint que l'hôte distant, le menu le
    dit, et le premier montage proposera le réseau que l'adresse révèle —
    refuser l'enregistrement laisserait sans issue.
    """

    def test_a_profile_without_routes_is_accepted_and_flagged(self):
        names = list(DRIVERS)
        answers = [
            "forged-site",
            str(names.index("l2tp_ipsec") + 1),
            "vpn.forged-site.example",  # la passerelle
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
        saved = profiles.load("forged-site")
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
                "name": "forged-site",
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
            return_value=["192.0.2.20", "192.0.2.1"],
        ):
            with redirect_stdout(buffer):
                driver.suggest_routes(runner, "ppp0")
        printed = buffer.getvalue()
        self.assertIn("192.0.2.0/24", printed)
        self.assertIn("hypothèse", printed)

    def test_nothing_is_suggested_when_routes_are_declared(self):
        """La suggestion ne s'invite pas quand la question est réglée."""
        from script.vpn.drivers.l2tp_ipsec import L2tpIpsecDriver
        from script.vpn.runner import Runner

        profile = profiles.validate(
            {
                "name": "forged-site",
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
        de passe maître serait redemandé dans la seconde suivant les deux
        saisies de la création.
        """
        profiles.save(
            {
                "name": "forged-site",
                "driver": "l2tp_ipsec",
                "server": "vpn.forged-site.example",
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
            self.todo, "_vpn_select_profile", return_value="forged-site"
        ):
            with self.answering(coffre, "o"):
                with patch("getpass.getpass", masked):
                    with redirect_stdout(io.StringIO()):
                        self.todo._vpn_store_secrets()
        self.assertEqual(len(typed), 6, typed)
        self.assertTrue(os.path.exists(coffre))

    def test_an_empty_answer_on_an_empty_field_is_reported(self):
        """« Une réponse vide garde la valeur en place » est un piège quand
        il n'y a RIEN en place : le secret resterait vide en silence, et le
        premier montage échouerait sur « Secrets manquants ». L'invite dit
        donc l'état, et le bilan nomme ce qui manque encore.
        """
        profiles.save(
            {
                "name": "forged-site",
                "driver": "l2tp_ipsec",
                "server": "vpn.forged-site.example",
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
            self.todo, "_vpn_select_profile", return_value="forged-site"
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
                "name": "forged-site",
                "driver": "l2tp_ipsec",
                "server": "vpn.forged-site.example",
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
            self.todo, "_vpn_select_profile", return_value="forged-site"
        ):
            with self.answering(coffre, "o"):
                with patch("getpass.getpass", masked):
                    with redirect_stdout(io.StringIO()):
                        self.todo._vpn_store_secrets()
            # Deuxième passage : tout est en place, et les invites le disent.
            typed.clear()
            with patch(
                "getpass.getpass",
                lambda prompt="": typed.append(prompt) or "",
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


class SsoHelperOffer(MenuBase):
    """La proposition d'installer le greffon SSO.

    Elle doit être ÉCLAIRÉE et ne pas se répéter : le greffon ne sert
    qu'aux passerelles à navigateur intégré, et proposer d'installer ce qui
    est déjà installé fait douter de ce qu'on lit.
    """

    def installing(self, driver, absent, *answers):
        """Déroule `_vpn_install` et rend (sortie, commandes lancées)."""
        launched = []
        with patch(
            "script.todo.vpn_menu._sso_helper_seen", return_value=not absent
        ):
            with patch.object(
                self.todo, "_vpn_pick_driver", return_value=DRIVERS[driver]
            ):
                with patch.object(
                    self.todo,
                    "_vpn_cli",
                    lambda arguments, env=None: launched.append(arguments),
                ):
                    with self.answering(*answers):
                        out = io.StringIO()
                        with redirect_stdout(out):
                            self.todo._vpn_install()
        return out.getvalue(), launched

    def test_it_is_offered_when_the_helper_is_missing(self):
        printed, launched = self.installing("openconnect", True, "o")
        self.assertIn("No SSO handler", printed)
        self.assertEqual(launched, ["install --driver openconnect --with-sso"])

    def test_declining_installs_only_the_packages(self):
        _, launched = self.installing("openconnect", True, "n")
        self.assertEqual(launched, ["install --driver openconnect"])

    def test_it_is_not_offered_when_the_helper_is_there(self):
        """Une liste de réponses VIDE : si la question était posée, le test
        lèverait StopIteration."""
        printed, launched = self.installing("openconnect", False)
        self.assertNotIn("No SSO handler", printed)
        self.assertEqual(launched, ["install --driver openconnect"])

    def test_it_is_not_offered_for_a_driver_that_cannot_use_it(self):
        """WireGuard n'a pas de formulaire web : la question serait sans
        objet, et la liste de réponses vide le prouve."""
        printed, launched = self.installing("wireguard", True)
        self.assertNotIn("No SSO handler", printed)
        self.assertEqual(launched, ["install --driver wireguard"])

    def test_the_offer_says_the_upstream_is_unmaintained(self):
        """La réponse doit être éclairée : le greffon porte une dette, et
        la taire ferait accepter sans savoir."""
        printed, _ = self.installing("openconnect", True, "n")
        self.assertIn("entretenu", printed)


def largeur_affichee(texte):
    """Largeur de `texte` en colonnes de terminal.

    Les caractères que la norme Unicode classe « W » (wide) ou « F »
    (fullwidth) — dont les emoji — en occupent deux pour un seul
    caractère. Une colonne alignée à l'écran ne l'est donc pas dans
    l'index de la chaîne, et l'inverse.
    """
    return sum(
        2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in texte
    )


class TheDefaultRouteQuestion(MenuBase):
    """« Tout le trafic ? » n'est posée qu'aux pilotes qui posent la route.

    Demander à qui n'a pas la main dessus, puis sanctionner la réponse par
    un ✗ sur un tunnel sain, serait la pire des trois façons de traiter la
    question : un champ qui ne sert à rien et fait échouer le diagnostic.
    """

    def filling(self, seed, *answers):
        """Déroule le formulaire et rend (questions posées, sortie)."""
        prompts = []
        suite = iter(answers)

        def fake(prompt=""):
            prompts.append(prompt.strip())
            return next(suite)

        with patch("builtins.input", fake):
            out = io.StringIO()
            with redirect_stdout(out):
                try:
                    self.todo._vpn_edit_profile(seed=dict(seed))
                except StopIteration:
                    pass
        return prompts, out.getvalue()

    OPENCONNECT = {
        "name": "oc",
        "driver": "openconnect",
        "server": "ssl.vpn.example-campus.net",
        "oc_user": "someone",
    }
    WIREGUARD = {
        "name": "wg",
        "driver": "wireguard",
        "server": "gw.example-campus.net",
        "wg_address": "10.9.0.2/32",
        "wg_peer_key": WG_PUBLIC,
    }

    def test_a_server_routed_driver_is_not_asked(self):
        prompts, printed = self.filling(self.OPENCONNECT, *[""] * 20)
        self.assertFalse([p for p in prompts if "trafic" in p], prompts)
        self.assertIn("passerelle décide", printed)

    def test_the_escape_hatch_is_named(self):
        """Retirer la question sans dire par quoi la remplacer se lirait
        comme une capacité perdue : `routes` reste honorée."""
        _, printed = self.filling(self.OPENCONNECT, *[""] * 20)
        self.assertIn("0.0.0.0/0", printed)

    def test_a_driver_that_lays_the_route_is_still_asked(self):
        prompts, _ = self.filling(self.WIREGUARD, *[""] * 20)
        self.assertTrue([p for p in prompts if "trafic" in p], prompts)

    def test_the_flag_is_not_kept_on_a_driver_that_ignores_it(self):
        """Un drapeau laissé à vrai resterait un champ sans effet, et la
        liste des profils continuerait d'annoncer « tout le trafic »."""
        seed = dict(self.OPENCONNECT, default_route=True)
        self.filling(seed, *([""] * 8 + ["n"]))
        saved = profiles.load("oc")
        self.assertIsNotNone(saved, "profil non enregistré")
        self.assertFalse(saved["default_route"])


class ShowingWhatIsConnected(MenuBase):
    """L'état de chaque profil, dans la liste qui sert à choisir.

    La même liste sert à connecter et à déconnecter : sans l'état, on
    descend un tunnel déjà mort ou on remonte celui qui tient, et la
    sortie du CLI est la première chose qui le dit — trop tard.
    """

    def setUp(self):
        super().setUp()
        profiles.save(
            {
                "name": "vivant",
                "driver": "openconnect",
                "server": "ssl.vpn.example-campus.net",
                "oc_user": "someone",
            }
        )
        profiles.save(
            {
                "name": "mort",
                "driver": "openconnect",
                "server": "ssl.vpn.example-campus.net",
                "oc_user": "someone",
            }
        )

    def listing(self, up):
        """La liste, avec `up` disant quels profils sont montés."""
        with patch.object(
            OpenconnectDriver,
            "is_up",
            lambda self: self.profile["name"] in up,
        ):
            with self.answering("0"):
                out = io.StringIO()
                with redirect_stdout(out):
                    self.todo._vpn_select_profile()
        return out.getvalue()

    def test_the_connected_profile_is_marked(self):
        printed = self.listing({"vivant"})
        vivant = [l for l in printed.splitlines() if "vivant" in l][0]
        mort = [l for l in printed.splitlines() if "mort" in l][0]
        self.assertIn("🟢", vivant)
        self.assertNotIn("🟢", mort)

    def test_the_columns_stay_aligned(self):
        """Un emoji occupe deux COLONNES pour un seul caractère : la ligne
        non marquée en réserve deux, sinon tout ce qui suit se décale.

        La mesure porte donc sur les colonnes affichées et non sur
        `str.index`, qui compte des caractères — l'écart d'un caractère
        entre les deux lignes est précisément ce qui les aligne à l'écran.
        """
        printed = self.listing({"vivant"})
        lignes = [l for l in printed.splitlines() if "example-campus" in l]
        self.assertEqual(len(lignes), 2, printed)
        colonnes = {
            largeur_affichee(l[: l.index("ssl.vpn.example-campus.net")])
            for l in lignes
        }
        self.assertEqual(len(colonnes), 1, lignes)

    def test_a_profile_is_picked_by_its_shown_number_or_its_name(self):
        # « 2 » choisit le deuxième profil de la liste, affiché [2], et son
        # nom exact le choisit aussi ; « 02 », « ٢ » (deux en écriture
        # arabe), « ² » ou « tout » sont dits invalides, et « 0 » renonce.
        second = profiles.with_defaults(profiles.load_all()[1])["name"]
        for answers, expected in (
            (["2"], second),
            ([second], second),
            (["02", "٢", "²", "tout", "0"], None),
            ([""], None),
        ):
            with (
                self.subTest(answers=answers),
                patch.object(OpenconnectDriver, "is_up", lambda self: False),
                self.answering(*answers),
                redirect_stdout(io.StringIO()) as out,
            ):
                self.assertEqual(self.todo._vpn_select_profile(), expected)
            refused = answers[:-1] if expected is None else []
            for answer in refused:
                self.assertIn(
                    f"{t('Invalid choice: ')}{answer}", out.getvalue()
                )

    def test_only_a_chosen_profile_is_disconnected_or_deleted(self):
        # Déconnecter lance « down » sans autre question : une réponse vide,
        # « 0 », « tout » ou une faute n'en lancent aucun ; Supprimer n'en
        # retire aucun et ne pose pas sa confirmation.
        launched = []
        for answers in ([""], ["0"], ["tout", "0"], ["*", "01", "x", ""]):
            launched.clear()
            with (
                self.subTest(answers=answers),
                patch.object(OpenconnectDriver, "is_up", lambda self: True),
                patch.object(
                    self.todo,
                    "_vpn_cli",
                    lambda arguments, env=None: launched.append(arguments),
                ),
                patch.object(profiles, "delete") as delete,
                self.answering(*answers, *answers),
                redirect_stdout(io.StringIO()),
            ):
                self.todo._vpn_disconnect()
                self.todo._vpn_delete_profile()
            self.assertEqual(launched, [])
            delete.assert_not_called()
        launched.clear()
        with (
            patch.object(OpenconnectDriver, "is_up", lambda self: True),
            patch.object(
                self.todo,
                "_vpn_cli",
                lambda arguments, env=None: launched.append(arguments),
            ),
            self.answering("mort"),
            redirect_stdout(io.StringIO()),
        ):
            self.todo._vpn_disconnect()
        self.assertEqual(launched, ["down --profile mort"])

    def test_an_unknown_driver_does_not_break_the_listing(self):
        """Un pilote retiré de la configuration ne doit pas empêcher de
        lister les profils, ni de supprimer celui qui le nomme."""
        self.assertFalse(
            self.todo._vpn_is_up({"name": "x", "driver": "disparu"})
        )

    def test_connecting_what_is_already_up_asks_first(self):
        """Remonter un tunnel qui tient rejoue toute l'authentification —
        jusqu'à un formulaire web — pour aboutir à une interface qui
        existe déjà."""
        launched = []
        with patch.object(OpenconnectDriver, "is_up", lambda self: True):
            with patch.object(
                self.todo, "_vpn_select_profile", return_value="vivant"
            ):
                with patch.object(
                    self.todo,
                    "_vpn_cli",
                    lambda arguments, env=None: launched.append(arguments),
                ):
                    with self.answering("n"):
                        out = io.StringIO()
                        with redirect_stdout(out):
                            self.todo._vpn_connect()
        self.assertIn("déjà connecté", out.getvalue())
        self.assertEqual(launched, [], "rien ne devait être lancé")

    def test_disconnecting_what_is_down_says_so_but_proceeds(self):
        """« down » reste utile : c'est lui qui efface l'état laissé dans
        /run par un tunnel mort sans lui."""
        launched = []
        with patch.object(OpenconnectDriver, "is_up", lambda self: False):
            with patch.object(
                self.todo, "_vpn_select_profile", return_value="mort"
            ):
                with patch.object(
                    self.todo,
                    "_vpn_cli",
                    lambda arguments, env=None: launched.append(arguments),
                ):
                    out = io.StringIO()
                    with redirect_stdout(out):
                        self.todo._vpn_disconnect()
        self.assertIn("n'est pas connecté", out.getvalue())
        self.assertEqual(launched, ["down --profile mort"])


class ChoosingTheXmlProfile(MenuBase):
    """Le choix du fichier `.xml` : parcours d'abord, saisie ensuite.

    Ni l'un ni l'autre ne suffit. Le parcours part des répertoires du
    client de Cisco et n'aide pas si le fichier vient d'ailleurs ; le
    chemin tapé oblige à le connaître, or personne ne retient
    « /opt/cisco/secureclient/vpn/profile ».
    """

    def setUp(self):
        super().setUp()
        self.xml = os.path.join(self.tmp.name, "campus.xml")
        with open(self.xml, "w") as fh:
            fh.write("<AnyConnectProfile/>")

    def browsing(self, chosen, *answers, dirs=None):
        """Déroule `_vpn_select_xml` avec un parcours qui rend `chosen`."""
        picked = []

        class FauxNavigateur:
            def __init__(self, start, callback):
                picked.append(start)
                self._callback = callback

            def run_main_frame(inner):
                if chosen is not None:
                    inner._callback(chosen)

        with patch(
            "script.todo.vpn_menu.ANYCONNECT_DIRS",
            dirs if dirs is not None else (self.tmp.name,),
        ):
            with patch(
                "script.todo.vpn_menu.todo_file_browser.FileBrowser",
                FauxNavigateur,
            ):
                with self.answering(*answers):
                    with redirect_stdout(io.StringIO()):
                        return self.todo._vpn_select_xml(), picked

    def test_the_browser_starts_in_the_cisco_directory(self):
        path, started = self.browsing(self.xml, "")
        self.assertEqual(path, self.xml)
        self.assertEqual(started, [self.tmp.name])

    def test_declining_the_browser_falls_back_to_typing(self):
        path, started = self.browsing(self.xml, "n", self.xml)
        self.assertEqual(path, self.xml)
        self.assertEqual(started, [], "le parcours ne devait pas s'ouvrir")

    def test_leaving_the_browser_empty_falls_back_to_typing(self):
        """On peut sortir du parcours sans rien choisir : la saisie reste."""
        path, _ = self.browsing(None, "", self.xml)
        self.assertEqual(path, self.xml)

    def test_a_path_that_is_not_a_file_does_not_pass_as_chosen(self):
        """Le parcours peut rendre un répertoire : il ne vaut pas fichier,
        et la saisie reprend la main."""
        path, _ = self.browsing(self.tmp.name, "", self.xml)
        self.assertEqual(path, self.xml)

    def test_no_cisco_directory_means_no_offer(self):
        """Ouvrir un parcours sur un chemin absent afficherait une liste
        vide, ce qui ressemble à une panne. Liste de réponses courte : si
        la question était posée, le test lèverait StopIteration."""
        path, started = self.browsing(
            self.xml, self.xml, dirs=("/nowhere/cisco",)
        )
        self.assertEqual(path, self.xml)
        self.assertEqual(started, [])

    def test_a_typed_path_is_expanded(self):
        path, _ = self.browsing(None, "n", "~")
        self.assertEqual(path, os.path.expanduser("~"))

    def test_giving_up_returns_nothing(self):
        path, _ = self.browsing(None, "n", "")
        self.assertEqual(path, "")


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

    def test_a_preset_is_picked_only_by_its_shown_number(self):
        # « 01 », « ١ » (un en écriture arabe), « ² » et « campus », son
        # identifiant que la liste ne montre pas, ne désignent pas le
        # préréglage : chacun est dit invalide, « 0 » renonce, et rien
        # n'est créé.
        for answer in ("01", "١", "²", "campus"):
            loading, answering = self.choosing(answer, "0")
            with (
                self.subTest(answer=answer),
                loading,
                answering,
                redirect_stdout(io.StringIO()) as out,
            ):
                self.todo._vpn_from_preset()
                self.assertEqual(profiles.names(), [])
                self.assertIn(
                    f"{t('Invalid choice: ')}{answer}", out.getvalue()
                )

    def test_a_preset_is_picked_by_its_label(self):
        loading, answering = self.choosing(
            "Campus SSL VPN",
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
        with loading, answering, redirect_stdout(io.StringIO()):
            self.todo._vpn_from_preset()
        self.assertEqual(profiles.load("campus_me")["oc_user"], "someone")

    def test_a_label_two_presets_share_picks_neither(self):
        # Deux préréglages ne sont uniques que par leur identifiant : leur
        # libellé commun est dit invalide, et seul le numéro les distingue.
        twin = dict(
            self.PRESET, preset="campus-two", server="forged.example.net"
        )
        seeds = []
        with (
            patch(
                "script.vpn.presets.load_all",
                return_value=([dict(self.PRESET), twin], []),
            ),
            patch.object(
                self.todo, "_vpn_edit_profile", lambda seed: seeds.append(seed)
            ),
            self.answering("Campus SSL VPN", "2", "campus_me"),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.todo._vpn_from_preset()
        self.assertIn(f"{t('Invalid choice: ')}Campus SSL VPN", out.getvalue())
        self.assertEqual([s["server"] for s in seeds], ["forged.example.net"])

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
