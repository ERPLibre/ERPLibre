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

import json
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


class TestLeMinuteurDesMiroirs(unittest.TestCase):
    """L'installation et le pilotage du minuteur des miroirs par SSH :
    l'ordre des commandes, le compte sans jeton, la configuration par
    l'entrée standard. ssh et scp sont remplacés."""

    CIBLE = f"erplibre@{IP}"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.journal = os.path.join(self._tmp.name, "j.log")
        self.lances = []
        self.codes = []

        def lancer(argv, journal, delai, entree=None):
            self.lances.append((argv, entree))
            return self.codes.pop(0) if self.codes else 0

        p = mock.patch.object(fv, "_lancer", side_effect=lancer)
        p.start()
        self.addCleanup(p.stop)

    def test_installer_copie_puis_lance(self):
        options = ["-o", "BatchMode=yes"]
        self.assertTrue(
            fv.installer_synchro(
                self.CIBLE, self.journal, "forge-admin", options
            )
        )
        argvs = [a for a, _ in self.lances]
        self.assertEqual([a[0] for a in argvs], ["ssh", "scp", "ssh"])
        self.assertIn("mkdir -p ~/.erplibre-forge-sync", argvs[0][-1])
        self.assertEqual(argvs[1][1:3], options)
        copies = argvs[1][3:-1]
        self.assertEqual(
            [os.path.relpath(c, fv.RACINE) for c in copies],
            list(fv.SYNCHRO_FICHIERS),
        )
        self.assertEqual(argvs[1][-1], f"{self.CIBLE}:.erplibre-forge-sync/")
        commande = argvs[2][-1]
        self.assertIn("FORGE_SYNC_ACCOUNT=forge-admin", commande)
        self.assertIn("FORGE_SYNC_CALENDAR=hourly", commande)
        self.assertIn("install_forge_sync.sh", commande)
        self.assertNotIn("TOKEN", commande)
        for argv in argvs:
            self.assertEqual(argv[1:3], options)

    def test_un_echec_a_chaque_etape_rend_faux(self):
        for rang in range(3):
            with self.subTest(rang=rang):
                self.lances.clear()
                self.codes = [0] * rang + [1]
                self.assertFalse(
                    fv.installer_synchro(
                        self.CIBLE, self.journal, "forge-admin"
                    )
                )
                self.assertEqual(len(self.lances), rang + 1)

    def test_un_compte_invalide_ne_lance_rien(self):
        for compte in ("", "-oProxyCommand=x", "a b", "x;rm"):
            with self.subTest(compte=compte):
                self.assertFalse(
                    fv.installer_synchro(self.CIBLE, self.journal, compte)
                )
        self.assertEqual(self.lances, [])

    def test_la_configuration_passe_par_l_entree_standard(self):
        config = {"version": 1, "paires": [{"depot": "Org/r"}]}
        self.assertTrue(
            fv.ecrire_config_synchro(self.CIBLE, config, self.journal)
        )
        argv, entree = self.lances[0]
        self.assertEqual(json.loads(entree), config)
        self.assertNotIn("Org/r", " ".join(argv))
        self.assertIn("sudo -n", argv[-1])
        self.assertEqual(argv[1 : 1 + len(fv.OPTIONS_SSH)], fv.OPTIONS_SSH)
        self.codes = [1]
        self.assertFalse(
            fv.ecrire_config_synchro(self.CIBLE, config, self.journal)
        )

    def test_retirer_des_paires_de_l_hote(self):
        self.assertTrue(
            fv.retirer_paires_synchro(
                self.CIBLE, ["Org/r", "Org/s.t"], self.journal
            )
        )
        commande = self.lances[0][0][-1]
        self.assertIn(f"test ! -e {fv.SYNCHRO_SCRIPT} ||", commande)
        self.assertIn("sudo -n", commande)
        self.assertTrue(commande.endswith(" retirer Org/r Org/s.t"))
        self.lances.clear()
        for depots in (["-oProxyCommand=x/y"], ["a/b;rm"], ["a"]):
            with self.subTest(depots=depots):
                self.assertFalse(
                    fv.retirer_paires_synchro(self.CIBLE, depots, self.journal)
                )
        self.assertTrue(
            fv.retirer_paires_synchro(self.CIBLE, [], self.journal)
        )
        self.assertEqual(self.lances, [])

    def test_lancer_passe_rend_le_code(self):
        self.codes = [3]
        self.assertEqual(fv.lancer_passe(self.CIBLE, self.journal), 3)
        self.assertIn(
            "systemctl start erplibre-forge-sync.service",
            self.lances[0][0][-1],
        )

    def test_lire_l_etat(self):
        cas = [
            (
                mock.Mock(returncode=0, stdout='{"jeton": true}'),
                {"jeton": True},
            ),
            (mock.Mock(returncode=0, stdout="pas du json"), None),
            (mock.Mock(returncode=0, stdout="[1]"), None),
            (mock.Mock(returncode=1, stdout='{"jeton": true}'), None),
        ]
        for rendu, attendu in cas:
            with self.subTest(rendu=rendu.stdout):
                with mock.patch.object(
                    fv.subprocess, "run", return_value=rendu
                ):
                    self.assertEqual(fv.lire_etat_synchro(self.CIBLE), attendu)
        with mock.patch.object(
            fv.subprocess,
            "run",
            side_effect=fv.subprocess.TimeoutExpired("ssh", 1),
        ):
            self.assertIsNone(fv.lire_etat_synchro(self.CIBLE))

    def test_ssh_garde_ses_options_par_defaut(self):
        fv.ssh(self.CIBLE, "true", self.journal, 10)
        fv.ssh(self.CIBLE, "true", self.journal, 10, options=["-x"])
        self.assertEqual(
            self.lances[0][0], ["ssh", *fv.OPTIONS_SSH, self.CIBLE, "true"]
        )
        self.assertEqual(self.lances[1][0], ["ssh", "-x", self.CIBLE, "true"])

    def test_les_etapes_du_deploiement_ne_changent_pas(self):
        self.assertEqual(
            fv.ETAPES,
            ("vm", "ssh", "cloud-init", "code", "venv", "forgejo", "api"),
        )


if __name__ == "__main__":
    unittest.main()
