#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Image cloud téléchargée selon la distribution, la version et le bureau.

Ce que ces tests gardent :

- Debian : la variante « genericcloud » porte un noyau compilé sans DRM, donc
  sans écran pour un bureau. Debian 13 ne publie que « generic » ; Debian 12
  publie les deux, et prend « generic » dès qu'un bureau est demandé. Le nom
  de cache suit la variante, sinon une image sans écran serait réutilisée
  pour une VM graphique.
- Les deux variantes partagent le même SHA512SUMS : l'appariement doit
  distinguer « generic » de « genericcloud », qui y vivent côte à côte.
- Fedora : seules des versions servies sous releases/ figurent au catalogue,
  la version par défaut en fait partie, et s390x n'en propose aucune hors
  catalogue.
"""

import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
DEPLOY = RACINE / "script/qemu/deploy_qemu.py"
sys.path.insert(0, str(RACINE))

_spec = importlib.util.spec_from_file_location("deploy_qemu", DEPLOY)
DQ = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(DQ)


class TestDebianVariant(unittest.TestCase):
    def test_debian_13_is_always_generic(self):
        """trixie ne publie pas d'image genericcloud : la viser rend 404
        sur chaque miroir."""
        for arch in ("amd64", "arm64"):
            for bureau in (False, True):
                with self.subTest(arch=arch, bureau=bureau):
                    urls = DQ.image_candidates(
                        "debian", "trixie", arch, "13", True, bureau
                    )
                    self.assertEqual(len(DQ.DEBIAN_CLOUD_BASES), len(urls))
                    for url in urls:
                        self.assertTrue(
                            url.endswith(
                                f"/trixie/latest/debian-13-generic-{arch}"
                                ".qcow2"
                            ),
                            url,
                        )
                    self.assertEqual(
                        f"debian-13-generic-{arch}.qcow2",
                        DQ.default_image_name(
                            "debian", "trixie", arch, "13", bureau
                        ),
                    )

    def test_debian_12_server_keeps_genericcloud(self):
        url = DQ.image_url("debian", "bookworm", "amd64", "12")
        self.assertTrue(url.endswith("debian-12-genericcloud-amd64.qcow2"))
        self.assertEqual(
            "debian-12-genericcloud-amd64.qcow2",
            DQ.default_image_name("debian", "bookworm", "amd64", "12"),
        )

    def test_debian_12_desktop_takes_the_kernel_that_displays(self):
        for arch in ("amd64", "arm64"):
            with self.subTest(arch=arch):
                url = DQ.image_url("debian", "bookworm", arch, "12", True)
                self.assertTrue(
                    url.endswith(f"debian-12-generic-{arch}.qcow2"), url
                )
                self.assertEqual(
                    f"debian-12-generic-{arch}.qcow2",
                    DQ.default_image_name(
                        "debian", "bookworm", arch, "12", True
                    ),
                )

    def test_the_two_variants_never_share_a_cache_name(self):
        serveur = DQ.default_image_name("debian", "bookworm", "amd64", "12")
        bureau = DQ.default_image_name(
            "debian", "bookworm", "amd64", "12", True
        )
        self.assertNotEqual(serveur, bureau)

    def test_an_unlisted_version_gets_generic(self):
        """Une version ajoutée au catalogue sans revue de ses variantes prend
        la seule que toutes publient."""
        self.assertEqual("generic", DQ.debian_variant("99"))
        self.assertEqual("genericcloud", DQ.debian_variant("12"))
        self.assertEqual("generic", DQ.debian_variant("12", True))

    def test_the_desktop_changes_no_other_distribution(self):
        for distro, version, code in (
            ("ubuntu", "24.04", "noble"),
            ("arch", "latest", "latest"),
            ("rocky", "10", "10"),
        ):
            with self.subTest(distro=distro):
                self.assertEqual(
                    DQ.image_candidates(distro, code, "amd64", version, True),
                    DQ.image_candidates(
                        distro, code, "amd64", version, True, True
                    ),
                )
                self.assertEqual(
                    DQ.default_image_name(distro, code, "amd64", version),
                    DQ.default_image_name(
                        distro, code, "amd64", version, True
                    ),
                )

    def test_the_sums_file_is_the_same_directory(self):
        url = DQ.image_url("debian", "bookworm", "amd64", "12", True)
        sums, algo = DQ.sums_url_for(url, "debian")
        self.assertEqual("sha512", algo)
        self.assertEqual(
            "https://cloud.debian.org/images/cloud/bookworm/latest/SHA512SUMS",
            sums,
        )

    def test_the_sums_tell_generic_from_genericcloud(self):
        """Empreintes inventées : seul l'appariement est éprouvé."""
        sums = (
            "aaaa  debian-12-genericcloud-amd64.qcow2\n"
            "bbbb  debian-12-generic-amd64.qcow2\n"
            "cccc  debian-12-nocloud-amd64.qcow2\n"
        )
        self.assertEqual(
            "bbbb", DQ.expected_sum(sums, "debian-12-generic-amd64.qcow2")
        )
        self.assertEqual(
            "aaaa",
            DQ.expected_sum(sums, "debian-12-genericcloud-amd64.qcow2"),
        )

    def test_the_command_line_threads_desktop_to_the_image(self):
        """--desktop atteint bien l'URL ET le nom de cache, pas seulement
        l'écran de virt-install."""
        with tempfile.TemporaryDirectory() as rep:
            base = [
                sys.executable,
                str(DEPLOY),
                "--download-only",
                "--dry-run",
                "--distro",
                "debian",
                "--version",
                "12",
                "--image-dir",
                rep,
            ]
            avec = subprocess.run(
                base + ["--desktop"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            sans = subprocess.run(
                base, capture_output=True, text=True, timeout=60
            )
        self.assertEqual(0, avec.returncode, avec.stderr)
        self.assertEqual(0, sans.returncode, sans.stderr)
        self.assertIn("latest/debian-12-generic-amd64.qcow2 ->", avec.stdout)
        self.assertIn(f"{rep}/debian-12-generic-amd64.qcow2", avec.stdout)
        self.assertIn("debian-12-genericcloud-amd64.qcow2", sans.stdout)
        self.assertNotIn("debian-12-generic-amd64", sans.stdout)


# Index HTML réduit à ce que resolve_fedora_url y cherche ; les numéros de
# compilation sont inventés.
INDEX_FEDORA = (
    '<a href="Fedora-Cloud-Base-Generic-45-1.2.{a}.qcow2">x</a>\n'
    '<a href="Fedora-Cloud-Base-Generic-45-1.4.{a}.qcow2">x</a>\n'
    '<a href="Fedora-Cloud-Base-AmazonEC2-45-1.4.{a}.raw.xz">x</a>\n'
)


class _Reponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestFedoraCatalogue(unittest.TestCase):
    def test_the_catalogue(self):
        versions, defaut = DQ.DISTROS["fedora"]
        self.assertEqual(["44", "45"], list(versions))
        self.assertEqual("44", defaut)

    def test_s390x_offers_only_catalogue_versions(self):
        s390x = DQ.ARCH_ONLY_VERSIONS["s390x"]["fedora"]
        self.assertEqual(("44", "45"), s390x)
        versions = DQ.DISTROS["fedora"][0]
        self.assertEqual(
            list(s390x), DQ.arch_versions("fedora", "s390x", versions)
        )

    def test_the_url_pattern_per_arch(self):
        for arch, a, arbre in (
            ("amd64", "x86_64", "fedora/linux"),
            ("arm64", "aarch64", "fedora/linux"),
            ("s390x", "s390x", "fedora-secondary"),
        ):
            with self.subTest(arch=arch):
                url = DQ.resolve_fedora_url("45", arch, True)
                self.assertIn(f"/{arbre}/releases/45/Cloud/{a}/images/", url)
                self.assertTrue(
                    url.endswith(
                        f"Fedora-Cloud-Base-Generic-45-<build>.{a}" ".qcow2"
                    ),
                    url,
                )

    def test_the_newest_build_of_the_index_is_taken(self):
        for arch, a in (("amd64", "x86_64"), ("arm64", "aarch64")):
            with self.subTest(arch=arch):
                html = INDEX_FEDORA.format(a=a).encode()
                with mock.patch.object(
                    DQ.urllib.request,
                    "urlopen",
                    side_effect=lambda *_a, **_k: _Reponse(html),
                ):
                    url = DQ.resolve_fedora_url("45", arch, False)
                self.assertTrue(
                    url.endswith(
                        f"/45/Cloud/{a}/images/"
                        f"Fedora-Cloud-Base-Generic-45-1.4.{a}.qcow2"
                    ),
                    url,
                )

    def test_an_unknown_osinfo_falls_back_to_the_last_known_fedora(self):
        """Un osinfo-db qui ne connaît pas encore fedora45 replie sur
        fedora44, et non sur la détection automatique."""
        with mock.patch.object(
            DQ, "osinfo_known", side_effect=lambda i: i == "fedora44"
        ), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual("fedora44", DQ.osinfo_arg("fedora45", "fedora"))

    def test_an_osinfo_db_older_than_the_catalogue_takes_the_family(self):
        """Un osinfo-db qui ne connaît AUCUNE version du catalogue Fedora
        replie sur « fedora-unknown » avant la détection automatique."""
        with mock.patch.object(
            DQ, "osinfo_known", side_effect=lambda i: i == "fedora-unknown"
        ), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                "fedora-unknown", DQ.osinfo_arg("fedora45", "fedora")
            )

    def test_without_a_family_id_detection_is_the_last_resort(self):
        with mock.patch.object(
            DQ, "osinfo_known", return_value=False
        ), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                "detect=on,require=off", DQ.osinfo_arg("fedora45", "fedora")
            )

    def test_the_menu_offers_the_same_catalogue(self):
        """Le sélecteur de todo.py recopie le catalogue : une version qu'il
        garde après son retrait d'ici est refusée au déploiement."""
        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        versions, defaut = DQ.DISTROS["fedora"]
        menu, menu_defaut = TODO._QEMU_DISTROS["fedora"]
        self.assertEqual(list(versions), list(menu))
        self.assertEqual(defaut, menu_defaut)


if __name__ == "__main__":
    unittest.main()
