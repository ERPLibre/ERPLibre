#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Profils de forge : ce qui est refusé, et ce qui atterrit sur le disque.

Ni réseau, ni forge, ni jeton. Les trois fichiers de configuration fusionnés
sont déplacés dans un répertoire temporaire : un test qui écrirait dans
`private/todo/todo_override_private.json` détruirait les profils de la
personne qui le lance.

LE PROFIL NE PORTE PAS DE SECRET, et c'est le cœur du dispositif. Le jeton
d'API vit dans le coffre ; ce fichier-ci se lit, se montre et se compare.
Une adresse « https://compte:motdepasse@forge/ » y mettrait un secret par la
bande, et c'est pour ça qu'elle est refusée.
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

from script.forge import profiles, valid  # noqa: E402
from script.forge.profiles import ProfileError  # noqa: E402
from script.lib_valid import ValidationError  # noqa: E402

VALIDE = {
    "name": "atelier",
    "url": "https://forge.example",
    "owner": "erplibre",
}


class TestLAdresseDeLaForge(unittest.TestCase):
    """Un jeton d'API voyage dans un en-tête : l'adresse décide qui le lit."""

    def refuse(self, url, **champs):
        record = {"url": url}
        record.update(champs)
        with self.assertRaises(ValidationError):
            valid.base_url(record, "url", "Adresse")

    def accepte(self, url, **champs):
        record = {"url": url}
        record.update(champs)
        return valid.base_url(record, "url", "Adresse")

    def test_a_plain_https_address_passes(self):
        self.assertEqual(
            "https://forge.example", self.accepte("https://forge.example")
        )

    def test_the_trailing_slash_goes(self):
        """Les appels ajoutent « /api/v1/… » ; une barre en trop donne un
        chemin doublé qu'une forge accepte et l'autre non."""
        self.assertEqual(
            "https://forge.example", self.accepte("https://forge.example/")
        )
        self.assertEqual(
            "https://forge.example/git",
            self.accepte("https://forge.example/git//"),
        )

    def test_a_credential_in_the_address_is_refused(self):
        """Le coffre porte les secrets ; ce fichier-ci se montre."""
        self.refuse("https://compte:motdepasse@forge.example")
        self.refuse("https://compte@forge.example")

    def test_a_scheme_that_is_not_a_forge_is_refused(self):
        """« ssh:// » et « file:// » arrivent par copier-coller depuis un
        remote git."""
        for url in (
            "ssh://forge.example",
            "file:///srv/git",
            "git://forge.example",
            "forge.example",
        ):
            with self.subTest(url=url):
                self.refuse(url)

    def test_plaintext_to_a_remote_address_is_refused(self):
        """Le jeton part dans un en-tête, à chaque appel, sur tout le
        segment."""
        self.refuse("http://192.0.2.10:3000")
        self.refuse("http://forge.example")

    def test_plaintext_to_the_loopback_needs_nothing(self):
        """Rien ne passe sur un câble : il n'y a rien à exiger."""
        self.assertEqual(
            "http://127.0.0.1:3000", self.accepte("http://127.0.0.1:3000")
        )
        self.assertEqual(
            "http://[::1]:3000", self.accepte("http://[::1]:3000")
        )

    def test_localhost_is_not_taken_for_the_loopback(self):
        """Il se résout où le résolveur le dit ; seule une adresse
        littérale prouve que le jeton ne quitte pas la machine."""
        self.refuse("http://localhost:3000")

    def test_plaintext_can_be_declared_and_has_to_be(self):
        """Contrôle positif : le refuser toujours retirerait l'usage d'une
        forge de laboratoire sans certificat."""
        self.assertEqual(
            "http://192.0.2.10:3000",
            self.accepte("http://192.0.2.10:3000", allow_plaintext=True),
        )

    def test_the_declaration_does_not_open_the_other_refusals(self):
        """Un seul drapeau ne doit pas être une clé passe-partout."""
        self.refuse("ssh://forge.example", allow_plaintext=True)
        self.refuse("http://compte:mdp@192.0.2.10", allow_plaintext=True)

    def test_https_never_needs_the_flag(self):
        """Le drapeau ne parle que de http : le poser ne change rien
        ailleurs, et l'oublier n'empêche rien en https."""
        self.assertEqual(
            "https://forge.example",
            self.accepte("https://forge.example", allow_plaintext=False),
        )

    def test_whitespace_is_refused(self):
        """Une adresse finit dans une ligne de commande."""
        self.refuse("https://forge.example/ un")
        self.refuse("https://forge .example")

    def test_a_query_or_an_anchor_is_refused(self):
        self.refuse("https://forge.example/?a=1")
        self.refuse("https://forge.example/#x")

    def test_a_dot_dot_in_the_path_is_refused(self):
        self.refuse("https://forge.example/../autre")

    def test_an_address_without_a_host_is_refused(self):
        self.refuse("https://")

    def test_an_empty_address_is_refused_when_required(self):
        self.refuse("")
        record = {"url": ""}
        self.assertEqual(
            "", valid.base_url(record, "url", "Adresse", required=False)
        )


class TestLeProfilValide(unittest.TestCase):
    def test_the_defaults_are_the_cautious_ones(self):
        profil = profiles.validate(VALIDE)
        self.assertTrue(profil["verify_tls"])
        self.assertFalse(profil["allow_plaintext"])
        self.assertEqual("forgejo", profil["driver"])

    def test_a_written_false_does_not_open_plaintext(self):
        """La chaîne « false » vaut vrai pour `bool` ; un profil écrit à la
        main ne doit pas ouvrir ce qu'il croit fermer."""
        profil = profiles.validate({**VALIDE, "allow_plaintext": "false"})
        self.assertIs(False, profil["allow_plaintext"])

    def test_a_written_true_does_open_it(self):
        """Contrôle positif : tout rendre faux retirerait l'usage."""
        profil = profiles.validate(
            {
                **VALIDE,
                "url": "http://192.0.2.10:3000",
                "allow_plaintext": "true",
            }
        )
        self.assertIs(True, profil["allow_plaintext"])

    def test_the_flags_are_judged_before_the_address(self):
        """`base_url` LIT « allow_plaintext » pour décider. Le normaliser
        après le laisserait décider sur la chaîne « false », qui est vraie —
        et une adresse en clair passerait sur un profil qui la refuse."""
        with self.assertRaises(ProfileError):
            profiles.validate(
                {
                    **VALIDE,
                    "url": "http://192.0.2.10:3000",
                    "allow_plaintext": "false",
                }
            )

    def test_an_unknown_driver_is_refused_and_names_the_known_ones(self):
        with self.assertRaises(ProfileError) as refus:
            profiles.validate({**VALIDE, "driver": "github"})
        self.assertIn("forgejo", str(refus.exception))

    def test_a_bad_url_comes_back_as_a_profile_error(self):
        """L'appelant attrape ProfileError ; laisser filer une
        ValidationError lui ferait manquer le refus."""
        with self.assertRaises(ProfileError):
            profiles.validate({**VALIDE, "url": "ssh://forge.example"})

    def test_a_name_is_required(self):
        with self.assertRaises(ValidationError):
            profiles.validate({k: v for k, v in VALIDE.items() if k != "name"})

    def test_an_owner_is_required(self):
        """Sans lui, créer un dépôt ne sait pas où le mettre."""
        with self.assertRaises(ValidationError):
            profiles.validate({**VALIDE, "owner": ""})

    def test_the_secret_reference_is_derived_and_not_stored(self):
        """Deux sources de vérité pour un même lien divergent ; un profil
        renommé chercherait son jeton sous l'ancienne référence."""
        self.assertNotIn("secret_ref", profiles.validate(VALIDE))
        self.assertIn("atelier", profiles.secret_ref("atelier"))
        self.assertNotEqual(profiles.secret_ref("a"), profiles.secret_ref("b"))

    def test_the_secret_reference_is_one_the_repository_store_parses(self):
        """La forme du coffre VPN — un titre à plat — ne serait pas
        analysée par `SecretStore`, et le jeton irait nulle part."""
        from script.vault.store import SecretStore

        schema, chemin = SecretStore._parse(profiles.secret_ref("atelier"))
        self.assertEqual("kdbx", schema)
        self.assertTrue(chemin.endswith("/atelier"), chemin)
        self.assertIn("/", chemin.rstrip("/atelier"))

    def test_the_profile_carries_no_token_field(self):
        """Le jeton vit dans le coffre. Un champ ici serait une invitation
        à l'y écrire, et le fichier se montre."""
        profil = profiles.validate(VALIDE)
        for interdit in ("token", "password", "secret", "api_key"):
            self.assertNotIn(interdit, profil)


class TestLAllerRetourSurDisque(unittest.TestCase):
    """Les trois fichiers fusionnés, déplacés dans un temporaire."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.join(self.tmp.name, "todo.json")
        with open(base, "w") as fh:
            json.dump({"forge": []}, fh)
        self.prive = os.path.join(self.tmp.name, "prive.json")
        self.patches = [
            patch("script.config.config_file.CONFIG_FILE", base),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_FILE",
                os.path.join(self.tmp.name, "override.json"),
            ),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
                self.prive,
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def test_save_then_load(self):
        profiles.save(VALIDE)
        relu = profiles.load("atelier")
        self.assertEqual("https://forge.example", relu["url"])
        self.assertTrue(relu["verify_tls"])

    def test_the_private_file_is_owner_only(self):
        """Il ne porte pas de secret, mais il nomme la forge d'un client :
        c'est une carte, et une carte se garde."""
        profiles.save(VALIDE)
        mode = stat.S_IMODE(os.stat(self.prive).st_mode)
        self.assertEqual(0o600, mode, oct(mode))

    def test_a_refused_profile_writes_nothing(self):
        """Un profil à moitié valide sur le disque est pire qu'un refus :
        il se relit sans se plaindre."""
        with self.assertRaises(ValidationError):
            profiles.save({**VALIDE, "url": "ssh://forge.example"})
        self.assertFalse(os.path.exists(self.prive))
        self.assertEqual([], profiles.names())

    def test_saving_twice_replaces_and_does_not_double(self):
        profiles.save(VALIDE)
        profiles.save({**VALIDE, "owner": "autre"})
        self.assertEqual(["atelier"], profiles.names())
        self.assertEqual("autre", profiles.load("atelier")["owner"])

    def test_delete_says_no_when_there_was_nothing(self):
        """Un profil venu de `todo.json` n'est pas supprimable d'ici, et le
        dire vaut mieux que de faire semblant."""
        self.assertFalse(profiles.delete("jamais-vu"))
        profiles.save(VALIDE)
        self.assertTrue(profiles.delete("atelier"))
        self.assertIsNone(profiles.load("atelier"))

    def test_an_unknown_name_loads_as_none(self):
        self.assertIsNone(profiles.load("jamais-vu"))

    def test_a_missing_section_is_an_empty_list_and_not_a_crash(self):
        self.assertEqual([], profiles.load_all())
        self.assertEqual([], profiles.names())

    def test_a_null_field_does_not_crush_its_default(self):
        """Un champ absent d'un JSON et un champ à null disent la même
        chose — « rien de dit »."""
        complet = profiles.with_defaults({"name": "x", "verify_tls": None})
        self.assertTrue(complet["verify_tls"])


class TestLeModuleNeParleAPersonne(unittest.TestCase):
    """Il décrit une forge ; il ne l'appelle pas, et n'affiche rien."""

    def test_it_neither_prints_nor_prompts_nor_calls_out(self):
        import ast

        racine = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        for module in ("profiles.py", "valid.py"):
            chemin = os.path.join(racine, "script", "forge", module)
            with open(chemin, encoding="utf-8") as fichier:
                arbre = ast.parse(fichier.read())
            noms = [
                noeud.func.id
                for noeud in ast.walk(arbre)
                if isinstance(noeud, ast.Call)
                and isinstance(noeud.func, ast.Name)
            ]
            with self.subTest(module=module):
                self.assertTrue(noms, "aucun appel lu : rien n'est prouvé")
                for interdit in ("print", "input", "urlopen", "run"):
                    self.assertNotIn(interdit, noms)


class TestLeRoleDAutorite(unittest.TestCase):
    """Un profil dit ce qu'il EST : un atelier, ou l'autorité.

    Vide, c'est un atelier — on y travaille, et ce qu'on y pose peut se
    refaire. « canonical » nomme celle dont on repart quand la station
    brûle, et c'est ce qui donne un sens à « pousser vers l'autorité ».

    Le vocabulaire est CLOS, comme celui des pilotes : un rôle inconnu est
    refusé plutôt que deviné. Replier sur « atelier » ferait travailler sans
    autorité une installation qui croyait en avoir une.
    """

    def profil(self, **extra):
        base = {
            "name": "atelier",
            "url": "https://forge.example",
            "owner": "equipe",
        }
        base.update(extra)
        return base

    def test_a_profile_without_a_role_is_a_workshop(self):
        """Un site qui n'a qu'une forge n'a rien à déclarer : l'exiger
        ferait refuser une configuration qui marchait."""
        self.assertEqual("", profiles.validate(self.profil())["role"])

    def test_the_authority_says_so(self):
        vu = profiles.validate(self.profil(role="canonical"))
        self.assertEqual("canonical", vu["role"])

    def test_an_unknown_role_is_refused_and_not_folded_back(self):
        with self.assertRaises(profiles.ProfileError) as refus:
            profiles.validate(self.profil(role="principale"))
        self.assertIn("principale", str(refus.exception))


class TestUneSeuleAutorite(unittest.TestCase):
    """Deux profils canoniques, ce sont DEUX vérités.

    Les gestes qui poussent « vers l'autorité » en choisiraient une au
    hasard, et l'autre vieillirait sans que rien ne le dise. C'est
    exactement ce dont une autorité doit protéger.
    """

    def config(self, *profils):
        class Faux:
            def get_config(self, _cle):
                return list(profils)

        return Faux()

    def test_no_authority_is_not_a_failure(self):
        """None n'est pas une panne : c'est l'appelant qui décide si
        l'absence l'empêche."""
        self.assertIsNone(
            profiles.canonical(self.config({"name": "a", "url": "https://x"}))
        )

    def test_the_only_authority_comes_back_complete(self):
        vu = profiles.canonical(
            self.config(
                {"name": "atelier", "url": "https://a.example"},
                {
                    "name": "amont",
                    "url": "https://b.example",
                    "role": "canonical",
                },
            )
        )
        self.assertEqual("amont", vu["name"])
        self.assertIn("driver", vu, "le profil doit être complété")

    def test_two_authorities_are_refused_rather_than_picked(self):
        with self.assertRaises(profiles.ProfileError) as refus:
            profiles.canonical(
                self.config(
                    {"name": "une", "url": "https://a", "role": "canonical"},
                    {"name": "deux", "url": "https://b", "role": "canonical"},
                )
            )
        for nom in ("une", "deux"):
            self.assertIn(nom, str(refus.exception))


if __name__ == "__main__":
    unittest.main()
