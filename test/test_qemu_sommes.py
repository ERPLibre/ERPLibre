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


class UneImageGardeeQuiAVieilli(unittest.TestCase):
    """« latest » avance à chaque version mineure : l'image gardée cesse de
    correspondre à la somme publiée sans que rien ne soit corrompu.

    La supprimer puis abandonner coûtait la campagne entière — trente minutes
    et trois VM — là où un seul téléchargement suffit. Un second écart, lui,
    porte sur des octets neufs : c'est une panne d'intégrité, et elle arrête.
    """

    NOM = "ubuntu-24.04-server-cloudimg-amd64.img"
    URL = f"https://miroir.invalid/d/{NOM}"

    def jouer(
        self,
        sur_disque,
        retelecharge=None,
        publie=b"publie",
        urls=("https://m/i",),
    ):
        """Rend (sorti, nombre de téléchargements, contenu final).

        « publie » est ce que le fichier de sommes DÉCLARE ; « retelecharge »
        ce qu'un nouveau téléchargement pose vraiment. Les confondre rend le
        second écart impossible à éprouver : les octets repris concordent
        alors toujours, et le cas « faux deux fois » n'existe plus.
        """
        import hashlib
        import tempfile
        from unittest import mock

        pose = retelecharge if retelecharge is not None else publie
        somme = hashlib.sha256(publie).hexdigest()
        sums = f"{somme}  {self.NOM}\n".encode()

        class Reponse:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return sums

        with tempfile.TemporaryDirectory() as d:
            image = Path(d) / self.NOM
            image.write_bytes(sur_disque)
            appels = []

            def faux_telechargement(urls_, dest, dry_run, timeout=None):
                appels.append(tuple(urls_))
                Path(dest).write_bytes(pose)

            sorti = False
            with mock.patch.object(
                DQ.urllib.request, "urlopen", lambda *a, **k: Reponse()
            ), mock.patch.object(DQ, "download_image", faux_telechargement):
                try:
                    DQ.verify_sha256(self.URL, image, False, "ubuntu", urls)
                except SystemExit:
                    sorti = True
            final = image.read_bytes() if image.exists() else b""
        return sorti, len(appels), final

    def test_une_image_perimee_est_reprise_une_fois(self):
        sorti, n, final = self.jouer(b"vieille", b"publie")
        self.assertFalse(sorti, "une péremption arrête encore le déploiement")
        self.assertEqual(
            1, n, "l'image n'a pas été reprise exactement une fois"
        )
        self.assertEqual(b"publie", final)

    def test_un_second_ecart_arrete_tout(self):
        """Des octets fraîchement téléchargés qui ne concordent pas ne sont
        plus une péremption : la vérification doit alors refuser."""
        sorti, n, final = self.jouer(b"vieille", b"faux-aussi")
        self.assertTrue(sorti, "une image fausse deux fois passe")
        self.assertEqual(1, n, "la reprise boucle au lieu d'arrêter")
        self.assertEqual(b"", final, "l'image fausse est restée sur le disque")

    def test_sans_miroir_le_comportement_ne_change_pas(self):
        """Appelée sans liste de miroirs — le mode épinglé, un appelant tiers
        — la vérification garde sa forme d'avant : supprimer et sortir."""
        sorti, n, final = self.jouer(b"vieille", b"publie", urls=())
        self.assertTrue(sorti)
        self.assertEqual(0, n)
        self.assertEqual(b"", final)

    def test_une_image_conforme_ne_declenche_rien(self):
        sorti, n, final = self.jouer(b"publie", b"publie")
        self.assertFalse(sorti)
        self.assertEqual(0, n, "une image conforme a été retéléchargée")
        self.assertEqual(b"publie", final)


if __name__ == "__main__":
    unittest.main()
