#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qui décide qu'une VM fraîchement déployée est JOIGNABLE.

Deux réglages du cloud-init, deux façons d'obtenir une machine qui démarre,
applique la clé SSH, et n'ouvre jamais de session. Aucune des deux ne se voit
en lisant un journal d'installation : la VM est « verte » et inutilisable.

- Le NETWORK-CONFIG du seed. Le renderer networkd de cloud-init — celui
  d'Arch comme celui de NixOS — ignore le « match » et écrit la CLÉ telle
  quelle en « Name= ». Une clé « eth0 » sur une image dont le NIC s'appelle
  enp0s2 fait attendre systemd-networkd-wait-online sans fin, et TOUT ce qui
  suit network-online.target reste en file : sshd-keygen, cloud-init.service,
  cloud-config.service, sshd lui-même. Mettre un glob en clé règle networkd
  et CASSE netplan, qui refuse « Definition ID 'e*' must not use globbing » —
  les deux ont été mesurés. D'où un réglage par distribution, et le repli de
  cloud-init là où le nom du NIC n'est pas connu d'avance.

- Le SHELL du compte. sshd refuse un compte dont le shell n'existe pas, avant
  l'authentification : « User <x> not allowed because shell /bin/bash does
  not exist ». NixOS ne peuple pas /bin — il n'y met que « sh ».

Chaque test dit ce que le code REFUSE désormais, et pourquoi le refus n'a pas
la même valeur d'une famille de renderer à l'autre.
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]

try:
    import yaml

    YAML = True
except Exception:  # pragma: no cover - dépend de l'environnement
    YAML = False


def _deploy_qemu():
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()


class LeDocumentReseau(unittest.TestCase):
    def _cle(self):
        """La clé de l'unique interface déclarée par le network-config."""
        cles = [
            ligne.strip().rstrip(":").strip('"')
            for ligne in DQ.NETWORK_CONFIG.splitlines()
            if ligne.startswith("  ") and not ligne.startswith("    ")
        ]
        self.assertEqual(1, len(cles), cles)
        return cles[0]

    def test_the_key_is_never_a_glob(self):
        """netplan REFUSE un identifiant qui globe — « Definition ID 'e*'
        must not use globbing » — et cloud-init.service échoue alors en
        entier : ni compte, ni clé SSH, sur Ubuntu et Debian."""
        self.assertNotIn("*", self._cle())

    def test_the_match_stays_for_the_renderers_that_honour_it(self):
        """netplan et ENI lisent le « match » : c'est lui qui désigne
        l'interface là où la clé n'est qu'une étiquette."""
        self.assertIn("match:", DQ.NETWORK_CONFIG)
        self.assertIn('name: "e*"', DQ.NETWORK_CONFIG)

    @unittest.skipUnless(YAML, "PyYAML absent")
    def test_it_stays_parsable(self):
        vu = yaml.safe_load(DQ.NETWORK_CONFIG)
        self.assertEqual(2, vu["version"])
        self.assertEqual(1, len(vu["ethernets"]))
        (reglage,) = vu["ethernets"].values()
        self.assertTrue(reglage["dhcp4"])
        self.assertFalse(reglage["dhcp6"])


class LeChoixDuDocument(unittest.TestCase):
    """À qui l'on donne un document réseau, et à qui l'on n'en donne pas."""

    def test_nixos_gets_none_so_cloud_init_finds_the_nic_itself(self):
        """Son image nomme le NIC selon la machine émulée (enp0s2 en q35,
        ens3 en i440fx) : aucune clé écrite d'avance ne peut tomber juste.
        Sans document, cloud-init produit son repli — DHCP sur la première
        interface, désignée par son vrai nom."""
        self.assertIsNone(DQ.network_config_for("nixos"))

    def test_everyone_else_keeps_the_document_unchanged(self):
        """Le corriger pour NixOS ne doit rien changer aux autres : Arch a le
        même renderer mais nomme son NIC eth0, que la clé couvre."""
        for distro in ("ubuntu", "debian", "fedora", "arch", "opensuse"):
            with self.subTest(distro=distro):
                self.assertEqual(
                    DQ.NETWORK_CONFIG, DQ.network_config_for(distro)
                )

    def test_the_seed_omits_the_option_when_there_is_no_document(self):
        """cloud-localds appelé avec « --network-config » et un fichier vide
        écrirait un document VIDE, ce qui n'est pas la même chose que pas de
        document : cloud-init ne replierait pas."""
        lancees = []
        runner = mock.MagicMock()
        runner.dry_run = False
        runner.run.side_effect = lambda cmd, **kw: lancees.append(cmd)
        with tempfile.TemporaryDirectory() as tmp:
            cible = Path(tmp) / "seed.iso"
            with mock.patch.object(DQ.shutil, "which", return_value="/x"):
                DQ.build_seed("#cloud-config\n", "vm", cible, runner, None)
                DQ.build_seed(
                    "#cloud-config\n", "vm", cible, runner, DQ.NETWORK_CONFIG
                )
        sans, avec = lancees[0], lancees[2]
        self.assertNotIn("--network-config", sans)
        self.assertIn("--network-config", avec)


class LeShellDuCompte(unittest.TestCase):
    def test_nixos_gets_the_only_shell_its_bin_holds(self):
        """/bin n'y contient que « sh », lien vers le bash du store : c'est
        donc bash en mode POSIX, pas dash."""
        self.assertEqual("/bin/sh", DQ.user_shell("nixos"))

    def test_everyone_else_keeps_bash(self):
        """Sur Debian et Ubuntu, /bin/sh EST dash : y basculer tout le monde
        pour réparer NixOS coûterait l'historique et la complétion à ceux
        qui n'ont rien demandé."""
        for distro in ("ubuntu", "debian", "fedora", "arch", "opensuse"):
            with self.subTest(distro=distro):
                self.assertEqual("/bin/bash", DQ.user_shell(distro))

    def test_an_unknown_distro_gets_the_common_shell(self):
        self.assertEqual("/bin/bash", DQ.user_shell("cequonnaitpas"))


class LeCloudConfig(unittest.TestCase):
    """Le réglage doit ATTEINDRE le document, pas seulement exister."""

    def _config(self, distro):
        args = DQ.build_parser().parse_args(
            ["--distro", "fedora", "--hostname", "vm"]
        )
        args.distro = distro
        return DQ.build_cloud_config(args, None, ["ssh-ed25519 AAAA essai"])

    def test_the_shell_reaches_the_user_block(self):
        self.assertIn("shell: /bin/sh", self._config("nixos"))
        self.assertIn("shell: /bin/bash", self._config("debian"))

    @unittest.skipUnless(YAML, "PyYAML absent")
    def test_the_document_stays_parsable_for_every_distro(self):
        for distro in ("ubuntu", "debian", "fedora", "arch", "nixos"):
            with self.subTest(distro=distro):
                vu = yaml.safe_load(self._config(distro))
                (compte,) = vu["users"]
                self.assertEqual(DQ.user_shell(distro), compte["shell"])
                self.assertEqual("erplibre", compte["name"])


if __name__ == "__main__":
    unittest.main()
