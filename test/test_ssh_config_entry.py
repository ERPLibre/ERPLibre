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


if __name__ == "__main__":
    unittest.main()
