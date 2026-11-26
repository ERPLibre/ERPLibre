#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Recherche, version et installation signée de `tofu`."""

import hashlib
import io
import os
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ["todo.py"]
from script.opentofu import outil  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

_LANGUE_ORIGINE = todo_i18n._current_lang
EMPREINTE = "AAAA1111BBBB2222CCCC3333DDDD4444EEEE5555"
VERSION = "9.8.7"

FAUX_TOFU = """#!/bin/sh
echo '{{"terraform_version": "{version}"}}'
"""

# Faux gpg : `--import` réussit, `--list-keys` annonce l'empreinte,
# `--verify` écrit VALIDSIG quand le test le veut.
FAUX_GPG = """#!/bin/sh
for a in "$@"; do
  case "$a" in
    --import) exit 0 ;;
    --list-keys) echo "fpr:::::::::{cle}:"; exit 0 ;;
    --verify) {verify}; exit 0 ;;
  esac
done
exit 1
"""


def setUpModule():
    todo_i18n._current_lang = "fr"


def tearDownModule():
    todo_i18n._current_lang = _LANGUE_ORIGINE


class TestVersion(unittest.TestCase):
    def test_suffisante(self):
        self.assertFalse(outil.version_suffisante("1.9.1", ">= 1.10"))
        self.assertTrue(outil.version_suffisante("1.13.9", ">= 1.10"))
        self.assertTrue(outil.version_suffisante("1.10", ">= 1.10"))
        self.assertTrue(outil.version_suffisante("1.10.0", ">= 1.10"))

    def test_prerelease_insuffisante_a_base_egale(self):
        self.assertFalse(outil.version_suffisante("1.14.0-beta1", ">= 1.14"))
        self.assertTrue(outil.version_suffisante("1.15.0-beta1", ">= 1.14"))

    def test_ordures(self):
        self.assertFalse(outil.version_suffisante("", ">= 1.10"))
        self.assertFalse(outil.version_suffisante("abc", ">= 1.10"))
        self.assertFalse(outil.version_suffisante("1.13", "n'importe"))

    def test_arch(self):
        for machine, attendu in (
            ("x86_64", "amd64"),
            ("aarch64", "arm64"),
            ("riscv64", ""),
        ):
            with mock.patch.object(
                outil.platform, "machine", return_value=machine
            ):
                self.assertEqual(outil.arch_tofu(), attendu)

    def test_noms_assets(self):
        noms = outil.noms_assets("1.2.3", "amd64")
        self.assertEqual(noms["zip"], "tofu_1.2.3_linux_amd64.zip")
        self.assertEqual(noms["sommes"], "tofu_1.2.3_SHA256SUMS")
        self.assertEqual(noms["signature"], "tofu_1.2.3_SHA256SUMS.gpgsig")

    def test_commande_paquet(self):
        with mock.patch.object(
            outil, "install_cmd_for", return_value=("c", "p")
        ) as m:
            self.assertEqual(outil.commande_paquet(), ("c", "p"))
        m.assert_called_once_with({"pacman": "opentofu"})


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.dest = self.tmp / "dest"
        arch = outil.arch_tofu() or "amd64"
        self.noms = outil.noms_assets(VERSION, arch)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(
                "tofu",
                FAUX_TOFU.format(version=VERSION),
            )
            z.writestr("LICENSE", "x")
        self.zip = buf.getvalue()
        self.somme = hashlib.sha256(self.zip).hexdigest()
        self.sommes = f"{self.somme}  {self.noms['zip']}\n".encode()
        self.conf = {
            "version": VERSION,
            "gpg_fingerprint": EMPREINTE,
            "cle_gpg_url": "https://exemple.invalide/cle.asc",
        }
        self.pris = []

    def gpg(self, valide=True, cle=EMPREINTE, verify=None):
        if verify is None:
            verify = (
                f'echo "[GNUPG:] VALIDSIG {EMPREINTE} 2026-01-01 1 0 4 0 1 10 "'
                if valide
                else "true"
            )
        chemin = self.tmp / "faux_gpg"
        chemin.write_text(FAUX_GPG.format(cle=cle, verify=verify))
        chemin.chmod(0o755)
        return str(chemin)

    def telecharger(self, zip_=None, sommes=None):
        zip_ = self.zip if zip_ is None else zip_
        sommes = self.sommes if sommes is None else sommes

        def f(url):
            self.pris.append(url)
            if url.endswith(".zip"):
                return zip_
            if url.endswith("SHA256SUMS"):
                return sommes
            return b"binaire"

        return f


class TestInstaller(_Base):
    def test_tout_bon(self):
        res = outil.installer_zip(
            self.conf,
            dest=self.dest,
            telecharger=self.telecharger(),
            gpg=self.gpg(),
        )
        self.assertTrue(res.ok, res.message)
        cible = self.dest / "tofu"
        self.assertEqual(stat.S_IMODE(cible.stat().st_mode), 0o755)
        self.assertEqual(os.listdir(self.dest), ["tofu"])
        self.assertTrue(
            self.pris[0].startswith(
                "https://github.com/opentofu/opentofu/releases/download/"
                f"v{VERSION}/"
            )
        )

    def test_somme_fausse(self):
        mauvaise = f"{'0' * 64}  {self.noms['zip']}\n".encode()
        res = outil.installer_zip(
            self.conf,
            dest=self.dest,
            telecharger=self.telecharger(sommes=mauvaise),
            gpg=self.gpg(),
        )
        self.assertFalse(res.ok)
        self.assertFalse((self.dest / "tofu").exists())

    def test_somme_absente(self):
        res = outil.installer_zip(
            self.conf,
            dest=self.dest,
            telecharger=self.telecharger(sommes=b"abc  autre.zip\n"),
            gpg=self.gpg(),
        )
        self.assertFalse(res.ok)
        self.assertFalse((self.dest / "tofu").exists())

    def test_signature_refusee_ne_telecharge_pas_le_zip(self):
        res = outil.installer_zip(
            self.conf,
            dest=self.dest,
            telecharger=self.telecharger(),
            gpg=self.gpg(valide=False),
        )
        self.assertFalse(res.ok)
        self.assertFalse(any(u.endswith(".zip") for u in self.pris))
        self.assertFalse((self.dest / "tofu").exists())

    def test_empreinte_de_cle_differente(self):
        res = outil.installer_zip(
            self.conf,
            dest=self.dest,
            telecharger=self.telecharger(),
            gpg=self.gpg(cle="F" * 40),
        )
        self.assertFalse(res.ok)
        self.assertFalse((self.dest / "tofu").exists())

    def test_version_installee_differente(self):
        self.conf["version"] = "1.0.0"
        noms = outil.noms_assets("1.0.0", outil.arch_tofu() or "amd64")
        sommes = f"{self.somme}  {noms['zip']}\n".encode()
        res = outil.installer_zip(
            self.conf,
            dest=self.dest,
            telecharger=self.telecharger(sommes=sommes),
            gpg=self.gpg(),
        )
        self.assertFalse(res.ok)
        self.assertFalse((self.dest / "tofu").exists())

    def test_telechargement_en_echec(self):
        def f(url):
            raise OSError("réseau")

        res = outil.installer_zip(
            self.conf, dest=self.dest, telecharger=f, gpg=self.gpg()
        )
        self.assertFalse(res.ok)
        self.assertFalse((self.dest / "tofu").exists())

    def test_dossier_temporaire_retire(self):
        avant = set(os.listdir(tempfile.gettempdir()))
        outil.installer_zip(
            self.conf,
            dest=self.dest,
            telecharger=self.telecharger(),
            gpg=self.gpg(valide=False),
        )
        apres = set(os.listdir(tempfile.gettempdir()))
        self.assertEqual(apres - avant, set())


class TestDurcissement(_Base):
    def installer(self, **kw):
        return outil.installer_zip(
            self.conf,
            dest=self.dest,
            telecharger=kw.pop("telecharger", None) or self.telecharger(),
            gpg=kw.pop("gpg", None) or self.gpg(),
        )

    def ancien(self):
        self.dest.mkdir()
        (self.dest / "tofu").write_bytes(b"ancien")
        return self.dest / "tofu"

    def test_version_differente_garde_l_ancien(self):
        ancien = self.ancien()
        self.conf["version"] = "1.0.0"
        noms = outil.noms_assets("1.0.0", outil.arch_tofu() or "amd64")
        sommes = f"{self.somme}  {noms['zip']}\n".encode()
        res = self.installer(telecharger=self.telecharger(sommes=sommes))
        self.assertFalse(res.ok)
        self.assertEqual(ancien.read_bytes(), b"ancien")
        self.assertEqual(os.listdir(self.dest), ["tofu"])

    def test_copie_en_echec_garde_l_ancien(self):
        ancien = self.ancien()
        with mock.patch.object(
            outil.shutil, "copyfile", side_effect=OSError("plein")
        ):
            res = self.installer()
        self.assertFalse(res.ok)
        self.assertEqual(ancien.read_bytes(), b"ancien")
        self.assertEqual(os.listdir(self.dest), ["tofu"])

    def test_remplace_l_ancien_quand_tout_est_bon(self):
        ancien = self.ancien()
        self.assertTrue(self.installer().ok)
        self.assertNotEqual(ancien.read_bytes(), b"ancien")
        self.assertEqual(os.listdir(self.dest), ["tofu"])

    def valid(self, ligne):
        return self.gpg(verify=f"echo '{ligne}'")

    def test_empreinte_primaire_en_dernier_champ(self):
        autre = "F" * 40
        champs = f"[GNUPG:] VALIDSIG {autre} d 1 0 4 0 1 10 00 {EMPREINTE}"
        self.assertTrue(self.installer(gpg=self.valid(champs)).ok)

    def test_empreinte_signataire_en_deuxieme_champ(self):
        autre = "F" * 40
        champs = f"[GNUPG:] VALIDSIG {EMPREINTE} d 1 0 4 0 1 10 00 {autre}"
        self.assertTrue(self.installer(gpg=self.valid(champs)).ok)

    def test_autre_cle_refusee(self):
        autre = "F" * 40
        champs = f"[GNUPG:] VALIDSIG {autre} d 1 0 4 0 1 10 00 {autre}"
        self.assertFalse(self.installer(gpg=self.valid(champs)).ok)

    def test_statuts_refuses_malgre_validsig(self):
        for statut in ("EXPKEYSIG", "REVKEYSIG", "EXPSIG", "BADSIG"):
            verify = (
                f"echo '[GNUPG:] {statut} AB name'; "
                f"echo '[GNUPG:] VALIDSIG {EMPREINTE} d 1 0 4 0 1 10 00 x'"
            )
            with self.subTest(statut=statut):
                res = self.installer(gpg=self.gpg(verify=verify))
                self.assertFalse(res.ok)
                self.assertFalse((self.dest / "tofu").exists())

    def zip_avec(self, nom):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(nom, FAUX_TOFU.format(version=VERSION))
        contenu = buf.getvalue()
        somme = hashlib.sha256(contenu).hexdigest()
        sommes = f"{somme}  {self.noms['zip']}\n".encode()
        return self.telecharger(zip_=contenu, sommes=sommes)

    def test_tofu_seulement_en_sous_dossier(self):
        res = self.installer(telecharger=self.zip_avec("sous/tofu"))
        self.assertFalse(res.ok)
        self.assertFalse(self.dest.exists() and os.listdir(self.dest))

    def test_aucun_membre_tofu(self):
        res = self.installer(telecharger=self.zip_avec("LICENSE"))
        self.assertFalse(res.ok)
        self.assertFalse(self.dest.exists() and os.listdir(self.dest))


class TestTrouver(unittest.TestCase):
    def test_version_tofu(self):
        with tempfile.TemporaryDirectory() as d:
            b = Path(d) / "tofu"
            b.write_text(FAUX_TOFU.format(version="1.2.3"))
            b.chmod(0o755)
            self.assertEqual(outil.version_tofu(str(b)), "1.2.3")
            self.assertEqual(outil.version_tofu(str(Path(d) / "absent")), "")


if __name__ == "__main__":
    unittest.main()
