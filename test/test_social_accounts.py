#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les comptes de réseaux sociaux, et ce que leur fichier n'a pas le droit
de contenir.

Un compte social porte un jeton qui vaut le compte entier : Mastodon
publie et lit avec, Bluesky ouvre une session avec. Ce fichier-ci ne doit
donc jamais en voir un — il ne garde qu'une référence vers le coffre,
exactement comme `accounts.json` du courriel.

L'autre chose que ces tests fixent est une CONSTATATION sur les API
publiées, pas une préférence : LinkedIn ne laisse pas lire le fil d'un
membre en libre-service. Un compte LinkedIn publie et ne lit pas, et le
code doit pouvoir le dire avant d'ouvrir un écran vide.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.social.accounts import (
    PRESETS,
    SCHEMA_VERSION,
    SocialAccount,
    SocialAccountError,
    account_from_preset,
    find,
    load,
    save,
)


class ComptesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "social" / "accounts.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _compte(self, **kw):
        params = dict(
            name="perso", handle="@moi@exemple.ca", platform="mastodon"
        )
        params.update(kw)
        return account_from_preset(
            params.pop("name"),
            params.pop("handle"),
            params.pop("platform"),
            **params,
        )


class TestWhatAnAccountRefuses(ComptesCase):
    def test_a_nameless_account_is_refused(self):
        with self.assertRaises(SocialAccountError):
            SocialAccount(
                name="",
                handle="@moi@exemple.ca",
                platform="mastodon",
                secret_ref="kdbx:x",
                base_url="https://exemple.ca",
            )

    def test_a_name_with_a_slash_is_refused(self):
        """Le nom sert de nom de dossier au cache : une barre oblique y
        écrirait ailleurs que prévu."""
        with self.assertRaises(SocialAccountError):
            self._compte(name="per/so", base_url="https://exemple.ca")

    def test_a_hidden_name_is_refused(self):
        with self.assertRaises(SocialAccountError):
            self._compte(name=".perso", base_url="https://exemple.ca")

    def test_an_unknown_platform_is_refused(self):
        with self.assertRaises(SocialAccountError):
            self._compte(platform="reseau-inconnu")

    def test_an_unknown_cache_mode_is_refused(self):
        with self.assertRaises(SocialAccountError):
            SocialAccount(
                name="perso",
                handle="@moi@exemple.ca",
                platform="mastodon",
                secret_ref="kdbx:x",
                base_url="https://exemple.ca",
                cache_mode="presque-chiffre",
            )

    def test_mastodon_without_an_instance_is_refused(self):
        """Il n'y a pas d'hôte Mastodon par défaut : sans instance, il n'y
        a pas de serveur à qui parler."""
        with self.assertRaises(SocialAccountError):
            self._compte()


class TestWhatEachPlatformCanDo(ComptesCase):
    def test_mastodon_reads_and_writes(self):
        compte = self._compte(base_url="https://exemple.ca")
        self.assertTrue(compte.peut_lire())
        self.assertTrue(compte.peut_publier())

    def test_bluesky_reads_and_writes(self):
        compte = self._compte(platform="bluesky", handle="moi.exemple.ca")
        self.assertTrue(compte.peut_lire())
        self.assertTrue(compte.peut_publier())

    def test_linkedin_publishes_but_does_not_read(self):
        """Constatation, pas préférence : lire le fil d'un membre exige une
        autorisation que LinkedIn n'accorde pas en libre-service, et son
        API de fil d'activité est dépréciée."""
        compte = self._compte(platform="linkedin", handle="moi")
        self.assertTrue(compte.peut_publier())
        self.assertFalse(compte.peut_lire())

    def test_bluesky_has_a_default_host(self):
        compte = self._compte(platform="bluesky", handle="moi.exemple.ca")
        self.assertEqual(compte.base_url, "https://bsky.social")

    def test_a_given_host_wins_over_the_default(self):
        """Un compte Bluesky hébergé sur son propre PDS n'a rien à faire du
        service par défaut."""
        compte = self._compte(
            platform="bluesky",
            handle="moi.exemple.ca",
            base_url="https://pds.exemple.ca",
        )
        self.assertEqual(compte.base_url, "https://pds.exemple.ca")

    def test_a_trailing_slash_is_dropped(self):
        """Sans cela, chaque adresse construite porterait une double barre."""
        compte = self._compte(base_url="https://exemple.ca/")
        self.assertEqual(compte.base_url, "https://exemple.ca")


class TestTheFileOnDisk(ComptesCase):
    def test_a_saved_account_comes_back_the_same(self):
        compte = self._compte(base_url="https://exemple.ca")
        save([compte], self.path)
        relu = load(self.path)
        self.assertEqual(len(relu), 1)
        self.assertEqual(relu[0].handle, "@moi@exemple.ca")
        self.assertEqual(relu[0].platform, "mastodon")

    def test_no_secret_ever_reaches_the_file(self):
        """Le garde-fou grossier : aucun mot évoquant un secret ne doit
        apparaître dans ce fichier, jeton compris."""
        save([self._compte(base_url="https://exemple.ca")], self.path)
        texte = self.path.read_text().lower()
        for interdit in ("password", "token", "jeton", "motdepasse"):
            self.assertNotIn(interdit, texte)

    def test_only_a_reference_to_the_vault_is_kept(self):
        save([self._compte(base_url="https://exemple.ca")], self.path)
        data = json.loads(self.path.read_text())
        self.assertEqual(
            data["accounts"][0]["secret_ref"], "kdbx:ERPLibre/Social/perso"
        )

    def test_the_file_is_not_readable_by_others(self):
        save([self._compte(base_url="https://exemple.ca")], self.path)
        self.assertEqual(os.stat(self.path).st_mode & 0o077, 0)

    def test_an_absent_file_is_not_an_error(self):
        self.assertEqual(load(self.path), [])

    def test_a_file_that_is_not_json_says_so(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{ pas du json")
        with self.assertRaises(SocialAccountError):
            load(self.path)

    def test_a_file_from_the_future_is_refused_not_guessed(self):
        """Le relire champ par champ perdrait en silence ce que cette
        version ne connaît pas, puis le réécrirait amputé par-dessus."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"version": SCHEMA_VERSION + 1, "accounts": []})
        )
        with self.assertRaises(SocialAccountError):
            load(self.path)

    def test_two_accounts_of_the_same_name_are_refused(self):
        compte = self._compte(base_url="https://exemple.ca")
        with self.assertRaises(SocialAccountError):
            save([compte, compte], self.path)

    def test_an_account_missing_a_field_says_which(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"version": 1, "accounts": [{"name": "perso"}]})
        )
        with self.assertRaises(SocialAccountError) as pris:
            load(self.path)
        self.assertIn("handle", str(pris.exception))

    def test_an_account_is_found_by_its_name(self):
        compte = self._compte(base_url="https://exemple.ca")
        self.assertIs(find([compte], "perso"), compte)
        self.assertIsNone(find([compte], "absent"))


class TestTheCacheKey(ComptesCase):
    def test_it_is_not_the_token_reference(self):
        """Les confondre ferait qu'un jeton renouvelé rendrait le cache
        illisible."""
        compte = self._compte(base_url="https://exemple.ca")
        self.assertNotEqual(compte.cache_key_ref(), compte.secret_ref)
        self.assertTrue(compte.cache_key_ref().startswith(compte.secret_ref))


class TestThePresets(ComptesCase):
    def test_every_preset_declares_what_it_can_do(self):
        for cle, preset in PRESETS.items():
            self.assertTrue(preset["capacites"], cle)

    def test_no_preset_ships_a_client_identifier(self):
        """Le dépôt ne livre aucune identité d'application : elle serait
        publique dès le premier clone."""
        texte = json.dumps(
            {
                cle: {k: v for k, v in preset.items() if k != "capacites"}
                for cle, preset in PRESETS.items()
            }
        ).lower()
        for interdit in ("client_id", "client_secret", "api_key"):
            self.assertNotIn(interdit, texte)


if __name__ == "__main__":
    unittest.main()
