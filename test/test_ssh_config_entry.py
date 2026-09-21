#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le bloc écrit dans ~/.ssh/config, épinglé au caractère près.

Cinq sites d'appel écrivent dans le fichier ssh de l'utilisateur, et rien ne
disait ce qu'ils y produisent. Ces épreuves le FIGENT : une option ajoutée
plus tard pour une posture ne doit rien changer là où personne ne l'a
demandée, et « rien changer » ne se constate qu'en ayant écrit d'avance ce
qui sortait.

Le fichier est déplacé dans un temporaire par HOME : une épreuve qui
écrirait dans le vrai ~/.ssh/config détruirait la configuration de la
personne qui la lance.

Les adresses sont celles que la RFC 5737 réserve à la documentation, et les
noms sont inventés.
"""

import io
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.todo.todo import TODO  # noqa: E402

IP = "192.0.2.10"
CLE = "~/.ssh/parc_essai"


class ConfigSsh(unittest.TestCase):
    """~/.ssh/config déplacé dans un temporaire, par HOME."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcheur = patch.dict(os.environ, {"HOME": self.tmp.name})
        patcheur.start()
        self.addCleanup(patcheur.stop)
        self.addCleanup(self.tmp.cleanup)
        self.chemin = os.path.join(self.tmp.name, ".ssh", "config")
        self.menu = TODO.__new__(TODO)

    def ecrire(self, *args, **kwargs):
        """Écrit un bloc et rend le contenu entier du fichier."""
        with redirect_stdout(io.StringIO()):
            self.menu._write_ssh_config_entry(*args, **kwargs)
        return self.lire()

    def lire(self):
        if not os.path.exists(self.chemin):
            return ""
        with open(self.chemin, encoding="utf-8") as fh:
            return fh.read()


class TestLesOctetsDuBloc(ConfigSsh):
    """Ce que produit chaque forme d'appel, figé.

    Ces cinq formes sont celles des cinq sites d'appel réels. Les épingler
    est ce qui permettra d'ajouter une option sans se demander si les
    anciens appels ont bougé.
    """

    def test_an_alias_with_a_key_is_the_minimal_block(self):
        self.assertEqual(
            "Host essai\n"
            f"    HostName {IP}\n"
            "    User erplibre\n"
            "    StrictHostKeyChecking no\n"
            "    UserKnownHostsFile /dev/null\n"
            f"    IdentityFile {CLE}\n"
            "    IdentitiesOnly yes\n",
            self.ecrire("essai", "erplibre", IP, identity_file=CLE),
        )

    def test_a_jump_lands_after_the_key(self):
        self.assertEqual(
            "Host essai\n"
            f"    HostName {IP}\n"
            "    User erplibre\n"
            "    StrictHostKeyChecking no\n"
            "    UserKnownHostsFile /dev/null\n"
            f"    IdentityFile {CLE}\n"
            "    IdentitiesOnly yes\n"
            "    ProxyJump rebond\n",
            self.ecrire(
                "essai",
                "erplibre",
                IP,
                identity_file=CLE,
                proxy_jump="rebond",
            ),
        )

    def test_a_list_of_names_shares_one_block(self):
        contenu = self.ecrire(
            ["court", "court+rebond"], "erplibre", IP, identity_file=CLE
        )
        self.assertTrue(
            contenu.startswith("Host court court+rebond\n"), contenu
        )
        self.assertEqual(1, contenu.count("HostName"))

    def test_without_a_key_neither_line_appears(self):
        """Contrôle positif : les deux lignes ne sont pas systématiques."""
        contenu = self.ecrire("essai", "erplibre", IP)
        self.assertNotIn("IdentityFile", contenu)
        self.assertNotIn("IdentitiesOnly", contenu)

    def test_identities_only_never_travels_without_the_key(self):
        """Sans elle, IdentityFile s'AJOUTE aux clés de l'agent au lieu de
        les remplacer, et le serveur coupe après cinq essais."""
        contenu = self.ecrire("essai", "erplibre", IP, identity_file=CLE)
        self.assertEqual(
            contenu.count("IdentityFile"), contenu.count("IdentitiesOnly")
        )

    def test_the_host_key_checks_are_always_off_for_these_hosts(self):
        """Des IP DHCP réutilisées entre VM feraient échouer la connexion
        sur un changement de clé qui n'en est pas un."""
        for kwargs in ({}, {"identity_file": CLE}, {"proxy_jump": "rebond"}):
            with self.subTest(kwargs=sorted(kwargs)):
                self.setUp()
                contenu = self.ecrire("essai", "erplibre", IP, **kwargs)
                self.assertIn("StrictHostKeyChecking no", contenu)
                self.assertIn("UserKnownHostsFile /dev/null", contenu)


class TestCeQuiEstRemplaceEtCeQuiSurvit(ConfigSsh):
    def test_rewriting_a_host_replaces_its_block(self):
        self.ecrire("essai", "erplibre", IP, identity_file=CLE)
        contenu = self.ecrire("essai", "erplibre", "192.0.2.11")
        self.assertEqual(1, contenu.count("Host essai"))
        self.assertIn("192.0.2.11", contenu)
        self.assertNotIn(IP, contenu)

    def test_an_unrelated_block_survives(self):
        os.makedirs(os.path.dirname(self.chemin), exist_ok=True)
        with open(self.chemin, "w", encoding="utf-8") as fh:
            fh.write("Host ailleurs\n    HostName 198.51.100.7\n")
        contenu = self.ecrire("essai", "erplibre", IP)
        self.assertIn("Host ailleurs", contenu)
        self.assertIn("Host essai", contenu)

    def test_also_drop_removes_a_block_the_new_name_would_not_touch(self):
        """Une convention de nommage qui change laisserait deux blocs vers
        la même machine, ce qu'on venait justement d'enlever."""
        self.ecrire("ancien-nom", "erplibre", IP)
        contenu = self.ecrire(
            "nouveau-nom", "erplibre", IP, also_drop=("ancien-nom",)
        )
        self.assertNotIn("ancien-nom", contenu)
        self.assertIn("Host nouveau-nom", contenu)

    def test_removing_without_writing_leaves_no_nude_host(self):
        """Un « Host » nu suivi d'un HostName vide s'applique à rien et
        brouille la lecture du fichier."""
        self.ecrire("essai", "erplibre", IP)
        contenu = self.ecrire([], "erplibre", IP, also_drop=("essai",))
        self.assertEqual("", contenu)

    def test_removing_keeps_what_it_was_not_asked_to_remove(self):
        self.ecrire("garde", "erplibre", IP)
        self.ecrire("part", "erplibre", "192.0.2.11")
        contenu = self.ecrire([], "erplibre", IP, also_drop=("part",))
        self.assertIn("Host garde", contenu)
        self.assertNotIn("Host part", contenu)


class TestLeFichierResteAuProprietaire(ConfigSsh):
    def test_the_file_is_owner_only(self):
        """ssh REFUSE de lire une configuration trop ouverte."""
        self.ecrire("essai", "erplibre", IP, identity_file=CLE)
        mode = stat.S_IMODE(os.stat(self.chemin).st_mode)
        self.assertEqual(0o600, mode, oct(mode))

    def test_it_stays_owner_only_after_a_removal(self):
        self.ecrire("essai", "erplibre", IP)
        self.ecrire([], "erplibre", IP, also_drop=("essai",))
        mode = stat.S_IMODE(os.stat(self.chemin).st_mode)
        self.assertEqual(0o600, mode, oct(mode))


class TestCeQueLesCinqSitesEcrivent(ConfigSsh):
    """Les cinq formes réelles, jouées telles quelles.

    Nommées ici pour qu'un changement de signature les casse toutes en même
    temps, plutôt que d'attendre qu'un déploiement le découvre.
    """

    FORMES = (
        ("clé seule", ("un",), {"identity_file": CLE}),
        (
            "clé et rebond",
            ("deux",),
            {"identity_file": CLE, "proxy_jump": "rebond"},
        ),
        (
            "liste, clé, rebond, retrait",
            (["trois", "trois+rebond"],),
            {
                "identity_file": CLE,
                "proxy_jump": "rebond",
                "also_drop": ("perime",),
            },
        ),
        ("rien de plus", ("quatre",), {}),
        ("retrait seul", ([],), {"also_drop": ("cinq",)}),
    )

    def test_every_shape_writes_a_readable_file(self):
        self.assertEqual(5, len(self.FORMES))
        for nom, args, kwargs in self.FORMES:
            with self.subTest(forme=nom):
                self.setUp()
                contenu = self.ecrire(*args, "erplibre", IP, **kwargs)
                # Aucune ligne « Host » sans nom, quelle que soit la forme.
                for ligne in contenu.splitlines():
                    self.assertNotEqual("Host", ligne.strip())


class TestUneValeurNePeutPasAjouterDeDirective(ConfigSsh):
    """Dans ce fichier, une LIGNE est une directive.

    Il n'y a ni guillemets ni échappement : un saut de ligne dans une valeur
    ajoute une directive que ssh appliquera à l'hôte en cours. La valeur
    piégée est inventée — un test fige pour toujours ce qu'il cite.
    """

    PIEGE = "essai\n    ProxyCommand /tmp/rien-de-reel"

    def test_every_written_value_refuses_a_second_line(self):
        champs = (
            ("host", (self.PIEGE, "erplibre", IP), {}),
            ("host dans une liste", ([self.PIEGE], "erplibre", IP), {}),
            ("user", ("essai", self.PIEGE, IP), {}),
            ("ip", ("essai", "erplibre", self.PIEGE), {}),
            (
                "proxy_jump",
                ("essai", "erplibre", IP),
                {"proxy_jump": self.PIEGE},
            ),
            (
                "identity_file",
                ("essai", "erplibre", IP),
                {"identity_file": self.PIEGE},
            ),
            (
                "also_drop",
                ([], "erplibre", IP),
                {"also_drop": (self.PIEGE,)},
            ),
        )
        self.assertEqual(7, len(champs))
        for nom, args, kwargs in champs:
            with self.subTest(champ=nom):
                with self.assertRaises(ValueError):
                    self.ecrire(*args, **kwargs)

    def test_a_carriage_return_is_refused_too(self):
        """Certains éditeurs en produisent, et ssh coupe la ligne dessus."""
        with self.assertRaises(ValueError):
            self.ecrire("essai\r    ProxyCommand /tmp/rien", "erplibre", IP)

    def test_the_file_is_left_untouched_when_a_value_is_refused(self):
        """Refuser après avoir réécrit le fichier aurait effacé un bloc
        pour rien."""
        self.ecrire("garde", "erplibre", IP)
        avant = self.lire()
        with self.assertRaises(ValueError):
            self.ecrire(self.PIEGE, "erplibre", IP)
        self.assertEqual(avant, self.lire())

    def test_the_refusal_names_the_field(self):
        """« une valeur est refusée » n'aide pas à trouver laquelle."""
        with self.assertRaises(ValueError) as pris:
            self.ecrire("essai", "erplibre", IP, proxy_jump=self.PIEGE)
        self.assertIn("ProxyJump", str(pris.exception))

    def test_an_ordinary_value_still_goes_through(self):
        """Contrôle positif : tout refuser passerait les épreuves ci-dessus."""
        contenu = self.ecrire(
            "essai.exemple-1", "erplibre-2", IP, identity_file=CLE
        )
        self.assertIn("Host essai.exemple-1", contenu)
        self.assertIn("User erplibre-2", contenu)


class TestLesOptionsDePosture(ConfigSsh):
    """Trois options viennent d'une posture, et sans elle rien ne bouge."""

    def test_the_defaults_write_what_was_written_before(self):
        """Une machine déployée sans posture ne doit pas changer de
        configuration parce que la notion est apparue."""
        avant = self.ecrire("essai", "erplibre", IP, identity_file=CLE)
        self.setUp()
        apres = self.ecrire(
            "essai",
            "erplibre",
            IP,
            identity_file=CLE,
            host_keys=None,
            forward_agent=None,
            forwards=(),
        )
        self.assertEqual(avant, apres)

    def test_throwaway_is_what_the_default_already_did(self):
        avant = self.ecrire("essai", "erplibre", IP)
        self.setUp()
        self.assertEqual(
            avant, self.ecrire("essai", "erplibre", IP, host_keys="throwaway")
        )

    def test_accept_new_keeps_the_key_instead_of_ignoring_it(self):
        """« no » n'a jamais refusé un changement de clé ; « accept-new »
        retient la première et refuse la suivante."""
        contenu = self.ecrire("essai", "erplibre", IP, host_keys="accept-new")
        self.assertIn("StrictHostKeyChecking accept-new", contenu)
        self.assertNotIn("UserKnownHostsFile /dev/null", contenu)

    def test_strict_accepts_nothing_unknown(self):
        contenu = self.ecrire("essai", "erplibre", IP, host_keys="strict")
        self.assertIn("StrictHostKeyChecking yes", contenu)
        self.assertNotIn("UserKnownHostsFile /dev/null", contenu)

    def test_an_unknown_policy_names_the_known_ones(self):
        with self.assertRaises(ValueError) as pris:
            self.ecrire("essai", "erplibre", IP, host_keys="peut-etre")
        self.assertIn("throwaway", str(pris.exception))


class TestLeRefusDeTransfererLAgent(ConfigSsh):
    """Un refus s'écrit ; il ne s'omet pas."""

    def test_refusing_writes_the_line(self):
        """OpenSSH ne transfère pas par défaut, donc omettre suffirait —
        mais le fichier ne dirait plus la différence entre « on l'a
        interdit » et « personne n'y a pensé »."""
        contenu = self.ecrire("essai", "erplibre", IP, forward_agent=False)
        self.assertIn("ForwardAgent no", contenu)

    def test_allowing_writes_the_line_too(self):
        contenu = self.ecrire("essai", "erplibre", IP, forward_agent=True)
        self.assertIn("ForwardAgent yes", contenu)

    def test_saying_nothing_writes_nothing(self):
        """Contrôle positif : la ligne n'est pas systématique."""
        self.assertNotIn("ForwardAgent", self.ecrire("essai", "erplibre", IP))


class TestLesRedirections(ConfigSsh):
    def test_each_kind_writes_its_directive(self):
        contenu = self.ecrire(
            "essai",
            "erplibre",
            IP,
            forwards=(
                ("local", "8069 localhost:8069"),
                ("remote", "9000 localhost:9000"),
                ("dynamic", "1080"),
            ),
        )
        self.assertIn("LocalForward 8069 localhost:8069", contenu)
        self.assertIn("RemoteForward 9000 localhost:9000", contenu)
        self.assertIn("DynamicForward 1080", contenu)

    def test_no_forward_writes_no_line(self):
        contenu = self.ecrire("essai", "erplibre", IP)
        self.assertNotIn("Forward", contenu)

    def test_an_unknown_kind_is_refused_before_the_file_is_touched(self):
        """ssh refuse le FICHIER entier sur une directive inconnue, donc
        toutes les machines pour une seule entrée mal formée."""
        self.ecrire("garde", "erplibre", IP)
        avant = self.lire()
        with self.assertRaises(ValueError) as pris:
            self.ecrire("essai", "erplibre", IP, forwards=(("lateral", "1"),))
        self.assertIn("local", str(pris.exception))
        self.assertEqual(avant, self.lire())

    def test_a_forward_cannot_add_a_directive_either(self):
        with self.assertRaises(ValueError):
            self.ecrire(
                "essai",
                "erplibre",
                IP,
                forwards=(("local", "1\n    ProxyCommand /tmp/rien"),),
            )


class TestLaCoutureAvecLeRegistre(ConfigSsh):
    """Le registre décide, l'écrivain applique : ils doivent s'accorder."""

    def test_every_policy_of_the_registry_is_understood_here(self):
        from script import posture

        self.assertTrue(posture.HOST_KEY_POLICIES)
        for politique in posture.HOST_KEY_POLICIES:
            with self.subTest(politique=politique):
                self.setUp()
                contenu = self.ecrire(
                    "essai", "erplibre", IP, host_keys=politique
                )
                self.assertIn("StrictHostKeyChecking", contenu)

    def test_the_two_vocabularies_are_the_same_set(self):
        """Une politique connue d'un seul côté est soit une option morte,
        soit une exception au moment du déploiement."""
        from script import posture

        self.assertEqual(
            set(posture.HOST_KEY_POLICIES),
            set(TODO._SSH_HOST_KEY_LINES),
        )

    def test_a_posture_drives_the_block_it_describes(self):
        """Le bout en bout : une posture, et le bloc qu'elle produit."""
        from script import posture

        stricte = posture.get_posture("paranoid")
        contenu = self.ecrire(
            "essai" + stricte.name_suffix,
            "erplibre",
            IP,
            host_keys=stricte.host_keys,
            forward_agent=stricte.forward_agent,
        )
        self.assertIn("Host essai-paranoid", contenu)
        self.assertIn("ForwardAgent no", contenu)


if __name__ == "__main__":
    unittest.main()
