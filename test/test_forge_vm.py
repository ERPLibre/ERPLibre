#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La forge Forgejo dans une VM : l'enchaînement des étapes, sans VM.

Propriétés gardées :
- le mot de passe administrateur passe par l'entrée standard, jamais par
  une ligne de commande ;
- l'installateur reçoit push-to-create, inscriptions fermées, dépôts
  privés et push de clone superficiel ;
- la première étape échouée arrête tout, et une VM qui existe déjà n'est
  jamais recréée ;
- la clé d'hôte de la forge remplace l'ancienne de la même adresse, et
  elle seule.

Les VM, ssh et l'API sont remplacés. L'adresse est inventée (192.0.2.0/24,
réservée à la documentation).
"""

import os
import tempfile
import unittest
from unittest import mock

from script.forgejo import forge_vm as fv

IP = "192.0.2.7"


class TestCommandes(unittest.TestCase):
    def test_the_installer_settings_and_no_password_in_the_command(self):
        cmd = fv.commande_forgejo("forge-admin")
        for reglage in (
            "FORGEJO_ADMIN_USER=forge-admin",
            "FORGEJO_PUSH_CREATE=1",
            "FORGEJO_DISABLE_REGISTRATION=1",
            "FORGEJO_DEFAULT_PRIVATE=1",
            "FORGEJO_SHALLOW_PUSH=1",
            f"FORGEJO_SSH_PORT={fv.PORT_SSH}",
        ):
            self.assertIn(reglage, cmd)
        self.assertIn("read -r FORGEJO_ADMIN_PASSWORD", cmd)

    def test_the_password_is_read_before_the_preamble(self):
        cmd = fv.commande_forgejo("forge-admin", "attendre cloud-init")
        self.assertLess(
            cmd.index("read -r FORGEJO_ADMIN_PASSWORD"),
            cmd.index("attendre cloud-init"),
        )
        self.assertIn("{ attendre cloud-init; } </dev/null", cmd)

    def test_creation_line_carries_the_key_and_the_cache_flags(self):
        argv = fv.argv_creation("forge-x", "/k.pub", ["--cache-bypass"])
        self.assertIn("--ssh-key", argv)
        self.assertEqual(argv[-1], "--cache-bypass")
        self.assertEqual(argv[argv.index("--name") + 1], "forge-x")

    def test_urls(self):
        self.assertEqual(
            fv.urls(IP),
            (f"http://{IP}:{fv.PORT_HTTP}", f"ssh://git@{IP}:{fv.PORT_SSH}"),
        )


class TestDeployer(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.journal = os.path.join(self._tmp.name, "j.log")
        self.etapes = []
        self.lances = []
        self.uuid = ""

        def lancer(argv, journal, delai, entree=None):
            self.lances.append((argv, entree))
            self.uuid = "u-1"
            return 0

        def ssh(cible, commande, journal, delai, entree=None):
            self.lances.append((["ssh", cible, commande], entree))
            return 0

        for nom, valeur in (
            ("_lancer", lancer),
            ("ssh", ssh),
            ("uuid_libvirt", lambda nom: self.uuid),
            ("attendre_ssh", lambda cible: True),
            ("deposer_code", lambda *a, **k: True),
        ):
            p = mock.patch.object(fv, nom, side_effect=valeur)
            p.start()
            self.addCleanup(p.stop)

    def etape(self, nom, ok, detail=""):
        self.etapes.append((nom, bool(ok)))
        return ok

    def deployer(self):
        return fv.deployer(
            "forge-x",
            "forge-admin",
            self.journal,
            self._tmp.name,
            lambda nom: IP,
            "venv-cmd",
            self.etape,
            cle_pub="/k.pub",
            preambule="attendre;",
        )

    def test_every_step_then_the_bootstrapped_forge(self):
        client = mock.Mock()
        with mock.patch.object(
            fv, "amorcer", return_value=(client, "jeton", "17.0")
        ) as amorcer:
            forge = self.deployer()
        self.assertEqual([e for e, _ in self.etapes], list(fv.ETAPES))
        self.assertTrue(all(ok for _, ok in self.etapes))
        self.assertEqual(forge["base_ssh"], f"ssh://git@{IP}:{fv.PORT_SSH}")
        self.assertEqual(forge["jeton"], "jeton")
        mot_de_passe = forge["mot_de_passe"]
        self.assertGreaterEqual(len(mot_de_passe), 24)
        # Le mot de passe va à l'entrée standard de l'installateur, jamais
        # dans une ligne de commande.
        for argv, entree in self.lances:
            self.assertNotIn(mot_de_passe, " ".join(argv))
        self.assertIn(mot_de_passe + "\n", [e for _, e in self.lances])
        self.assertEqual(
            amorcer.call_args[0][1:3], ("forge-admin", mot_de_passe)
        )
        # cloud-init s'attend seul, puis en tête du venv : jamais « ;; ».
        commandes = [argv[-1] for argv, _ in self.lances if argv[0] == "ssh"]
        self.assertEqual(commandes[0], "attendre")
        self.assertTrue(commandes[1].startswith("attendre; cd ~/git/erplibre"))
        self.assertNotIn(";;", " ".join(commandes))

    def test_an_existing_vm_is_never_recreated(self):
        self.uuid = "deja"
        self.assertIsNone(self.deployer())
        self.assertEqual(self.etapes, [("vm", False)])
        self.assertEqual(self.lances, [])

    def test_the_first_failed_step_stops(self):
        with mock.patch.object(fv, "attendre_ssh", return_value=False):
            self.assertIsNone(self.deployer())
        self.assertEqual(self.etapes, [("vm", True), ("ssh", False)])

    def test_an_api_failure_is_reported(self):
        with mock.patch.object(
            fv, "amorcer", side_effect=fv.fc.ErreurForgejo("refusé")
        ):
            self.assertIsNone(self.deployer())
        self.assertEqual(self.etapes[-1], ("api", False))


class TestCleHote(unittest.TestCase):
    def test_the_old_key_of_the_address_is_replaced_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            connus = os.path.join(tmp, "known_hosts")
            with open(connus, "w") as fh:
                fh.write(f"[{IP}]:{fv.PORT_SSH} ssh-ed25519 AAAAancienne\n")
                fh.write("autre.invalid ssh-ed25519 AAAAautre\n")
            vraie = fv.subprocess.run

            def run(argv, **kw):
                if argv[0] == "ssh-keyscan":
                    return mock.Mock(
                        stdout=f"# commentaire\n[{IP}]:{fv.PORT_SSH}"
                        " ssh-ed25519 AAAAneuve\n"
                    )
                return vraie(argv, **kw)

            with mock.patch.object(fv.subprocess, "run", side_effect=run):
                self.assertTrue(fv.enregistrer_cle_hote(IP, connus=connus))
            with open(connus) as fh:
                texte = fh.read()
        self.assertNotIn("AAAAancienne", texte)
        self.assertIn("AAAAneuve", texte)
        self.assertIn("AAAAautre", texte)

    def test_no_key_read_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            connus = os.path.join(tmp, "known_hosts")
            with mock.patch.object(
                fv.subprocess, "run", return_value=mock.Mock(stdout="")
            ):
                self.assertFalse(fv.enregistrer_cle_hote(IP, connus=connus))
            self.assertFalse(os.path.exists(connus))


if __name__ == "__main__":
    unittest.main()
