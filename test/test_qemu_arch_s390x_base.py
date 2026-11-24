#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Emplacement de l'image Arch Linux s390x, sans valeur par défaut.

Arch ne publie aucune image s390x : celle-ci vient du portage communautaire
archlinux-s390x, servie par un hôte que seul l'utilisateur connaît. Le code
ne porte donc aucune adresse, et EL_ARCH_S390X_BASE est obligatoire pour ce
seul couple. Ces tests gardent les deux côtés :

- sans la variable, Arch s390x s'arrête sur un message qui la nomme, et
  main() s'arrête avant de résoudre la moindre URL d'image ;
- avec elle, l'URL se construit dessus, barre oblique finale ou non ;
- les autres distributions sur s390x, et Arch sur x86_64, n'en dépendent
  jamais.

L'environnement réel n'entre pas en jeu : chaque test pose ou retire la
variable lui-même.
"""

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
DEPLOY = RACINE / "script/qemu/deploy_qemu.py"
sys.path.insert(0, str(RACINE))

_spec = importlib.util.spec_from_file_location("deploy_qemu", DEPLOY)
DQ = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(DQ)

VAR = "EL_ARCH_S390X_BASE"
BASE = "http://portage-s390x.example.invalid/images"
IMAGE = "Arch-Linux-s390x-cloudimg.qcow2"


def _sans_variable():
    env = {k: v for k, v in os.environ.items() if k != VAR}
    return mock.patch.dict(os.environ, env, clear=True)


def _avec_variable(valeur):
    return mock.patch.dict(os.environ, {VAR: valeur})


def _candidats(distro, arch):
    return DQ.image_candidates(distro, "latest", arch, "latest", True)


class TestSansVariable(unittest.TestCase):
    def test_arch_s390x_refuses_and_names_the_variable(self):
        with _sans_variable():
            with self.assertRaises(SystemExit) as ctx:
                _candidats("arch", "s390x")
        message = str(ctx.exception.code)
        self.assertIn(VAR, message)
        self.assertIn(IMAGE, message)

    def test_empty_value_counts_as_unset(self):
        for valeur in ("", "   ", "/"):
            with self.subTest(valeur=valeur), _avec_variable(valeur):
                self.assertIn(VAR, DQ.arch_s390x_refusal("arch", "s390x"))
                with self.assertRaises(SystemExit):
                    _candidats("arch", "s390x")

    def test_refusal_says_where_the_image_comes_from(self):
        with _sans_variable():
            message = DQ.arch_s390x_refusal("arch", "s390x")
        self.assertIn("archlinux-s390x", message)

    def test_main_stops_before_any_image_resolution(self):
        argv = ["deploy_qemu.py", "--distro", "arch", "--arch", "s390x"]
        argv += ["--name", "essai-s390x", "--dry-run"]
        with _sans_variable(), mock.patch.object(sys, "argv", argv):
            with mock.patch.object(DQ, "image_candidates") as candidats:
                with self.assertRaises(SystemExit) as ctx:
                    DQ.main()
        self.assertIn(VAR, str(ctx.exception.code))
        candidats.assert_not_called()

    def test_import_does_not_need_the_variable(self):
        with _sans_variable():
            spec = importlib.util.spec_from_file_location("dq_bis", DEPLOY)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.assertIn("arch", module.S390X_DISTROS)


class TestAvecVariable(unittest.TestCase):
    def test_url_is_built_from_the_variable(self):
        with _avec_variable(BASE):
            self.assertEqual([f"{BASE}/{IMAGE}"], _candidats("arch", "s390x"))
            self.assertEqual("", DQ.arch_s390x_refusal("arch", "s390x"))

    def test_trailing_slash_gives_the_same_url(self):
        for valeur in (BASE + "/", BASE + "//", f"  {BASE}/  "):
            with self.subTest(valeur=valeur), _avec_variable(valeur):
                self.assertEqual(
                    [f"{BASE}/{IMAGE}"], _candidats("arch", "s390x")
                )


class TestAutresCouplesIndependants(unittest.TestCase):
    def test_other_distros_on_s390x_ignore_the_variable(self):
        for distro in ("ubuntu", "almalinux", "rocky", "opensuse"):
            versions, defaut = DQ.DISTROS[distro]
            code = versions[defaut][0]
            with self.subTest(distro=distro):
                self.assertEqual("", DQ.arch_s390x_refusal(distro, "s390x"))
                with _sans_variable():
                    sans = DQ.image_candidates(
                        distro, code, "s390x", defaut, True
                    )
                with _avec_variable(BASE):
                    avec = DQ.image_candidates(
                        distro, code, "s390x", defaut, True
                    )
                self.assertEqual(sans, avec)
                self.assertTrue(all(BASE not in u for u in sans), sans)

    def test_arch_on_x86_64_keeps_the_upstream_image(self):
        with _sans_variable():
            self.assertEqual("", DQ.arch_s390x_refusal("arch", "amd64"))
            urls = _candidats("arch", "amd64")
        self.assertEqual(1, len(urls))
        self.assertTrue(urls[0].startswith(DQ.ARCH_CLOUD_BASE), urls)
        self.assertTrue(urls[0].endswith("x86_64-cloudimg.qcow2"), urls)


if __name__ == "__main__":
    unittest.main()
