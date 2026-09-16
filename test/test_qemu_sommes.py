#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'image téléchargée est vérifiée contre la somme que son éditeur publie.

La vérification existait, sous un drapeau, et pour Ubuntu SEULEMENT : les
huit autres images arrivaient sans que rien ne les regarde, alors que leurs
éditeurs publient tous une somme à côté. Le risque couvert est une image
substituée sur un miroir, et le coût une lecture du fichier qu'on vient de
télécharger.

Ni le nom du fichier de sommes ni l'algorithme ne se devinent, et les
extraits plus bas sont pris des dépôts eux-mêmes : Debian publie du sha512
quand tout le reste est en sha256, les familles RHEL nomment leur fichier
« CHECKSUM » sans dire l'algorithme, Rocky l'écrit en forme BSD, et Arch
comme openSUSE posent une somme PAR image.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]


def _deploy_qemu():
    chemin = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()

# Un extrait de chaque format, relevé sur le dépôt de la distribution. Les
# empreintes sont RACCOURCIES et inventées : ce qu'on éprouve est
# l'appariement, pas la valeur, et une somme réelle figée ici vieillirait au
# premier renouvellement d'image.
FORMATS = {
    "ubuntu": (
        "aaaa *autre-image-amd64.img\n"
        "bbbb *ubuntu-24.04-server-cloudimg-amd64.img\n",
        "ubuntu-24.04-server-cloudimg-amd64.img",
        "bbbb",
    ),
    "debian": (
        "cccc  debian-12-genericcloud-arm64.qcow2\n"
        "dddd  debian-12-genericcloud-amd64.qcow2\n",
        "debian-12-genericcloud-amd64.qcow2",
        "dddd",
    ),
    "rocky": (
        "# Rocky-10-GenericCloud.latest.x86_64.qcow2: 544997376 bytes\n"
        "SHA256 (Rocky-10-GenericCloud.latest.x86_64.qcow2) = eeee\n",
        "Rocky-10-GenericCloud.latest.x86_64.qcow2",
        "eeee",
    ),
    "opensuse": (
        "ffff  Leap-16.0-Minimal-VM.x86_64-Cloud.qcow2\n",
        "Leap-16.0-Minimal-VM.x86_64-Cloud.qcow2",
        "ffff",
    ),
}


class LAppariement(unittest.TestCase):
    def test_every_published_format_is_read(self):
        for distro, (texte, nom, attendu) in FORMATS.items():
            with self.subTest(distro=distro):
                self.assertEqual(attendu, DQ.expected_sum(texte, nom))

    def test_a_longer_name_ending_the_same_is_not_a_match(self):
        """Le nom est comparé EN ENTIER, pas par sa fin. Un fichier de sommes
        porte toutes les images d'un répertoire, et un nom plus long qui se
        termine par celui qu'on cherche rendrait la somme d'une AUTRE image —
        la vérification échouerait alors en accusant l'image juste.

        La forme d'origine comparait la fin de la LIGNE, ce qui revient au
        même défaut."""
        texte = "1111  prefixe-image.qcow2\n2222  image.qcow2\n"
        self.assertEqual("2222", DQ.expected_sum(texte, "image.qcow2"))

    def test_signature_and_comment_lines_fall_away(self):
        texte = (
            "-----BEGIN PGP SIGNED MESSAGE-----\n"
            "Hash: SHA256\n"
            "\n"
            "# une ligne de commentaire\n"
            "3333  image.qcow2\n"
        )
        self.assertEqual("3333", DQ.expected_sum(texte, "image.qcow2"))

    def test_an_absent_name_yields_nothing(self):
        self.assertEqual("", DQ.expected_sum("4444  autre.qcow2\n", "x.qcow2"))


class OuChaqueDistributionPublie(unittest.TestCase):
    def test_the_six_that_publish_are_resolved(self):
        """Une somme par répertoire chez les uns, à côté de l'image chez les
        autres : le nom ne se déduit pas de l'image seule."""
        for distro in DQ.SUMS_SOURCE:
            with self.subTest(distro=distro):
                url = f"https://exemple.invalid/d/image-{distro}.qcow2"
                su, algo = DQ.sums_url_for(url, distro)
                self.assertTrue(su.startswith("https://exemple.invalid/d/"))
                self.assertIn(algo, ("sha256", "sha512"))

    def test_debian_is_the_one_in_sha512(self):
        """L'algorithme vient de la table, pas du nom du fichier."""
        self.assertEqual("sha512", DQ.SUMS_SOURCE["debian"][1])
        for distro, (_nom, algo) in DQ.SUMS_SOURCE.items():
            if distro != "debian":
                with self.subTest(distro=distro):
                    self.assertEqual("sha256", algo)

    def test_the_per_image_forms_carry_the_image_name(self):
        for distro in ("opensuse", "arch"):
            with self.subTest(distro=distro):
                url = "https://exemple.invalid/d/monimage.qcow2"
                su, _a = DQ.sums_url_for(url, distro)
                self.assertIn("monimage.qcow2", su)

    def test_a_distribution_that_publishes_nothing_says_so(self):
        """NixOS a sa somme ÉPINGLÉE dans le dépôt, vérifiée toujours ; son
        image tierce ne publie rien à côté."""
        self.assertNotIn("nixos", DQ.SUMS_SOURCE)
        self.assertEqual(
            ("", ""), DQ.sums_url_for("https://x/i.qcow2", "nixos")
        )


class LaVerificationEstLeDefaut(unittest.TestCase):
    SRC = (RACINE / "script/qemu/deploy_qemu.py").read_text(encoding="utf-8")

    def test_no_flag_is_needed_any_more(self):
        self.assertIn("do_verify = not args.no_verify", self.SRC)

    def test_skipping_it_must_be_asked_for(self):
        self.assertIn('"--no-verify"', self.SRC)

    def test_unreachable_sums_do_not_stop_a_deployment(self):
        """Un fichier de sommes injoignable est une panne de DISPONIBILITÉ —
        miroir en travaux, réseau coupé. Refuser de déployer pour cela
        rendrait la vérification plus coûteuse que le risque qu'elle couvre.
        """
        i = self.SRC.index("def verify_sha256(")
        corps = self.SRC[i : self.SRC.index("def hash_password", i)]
        self.assertIn("image NON vérifiée", corps)
        self.assertNotIn('sys.exit(f"Impossible', corps)

    def test_a_mismatch_still_stops_everything(self):
        """Elle, c'est une panne d'INTÉGRITÉ."""
        i = self.SRC.index("def verify_sha256(")
        corps = self.SRC[i : self.SRC.index("def hash_password", i)]
        self.assertIn("NON conforme", corps)
        self.assertIn("image.unlink", corps)


if __name__ == "__main__":
    unittest.main()
