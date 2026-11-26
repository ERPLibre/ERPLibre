#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Coffre OpenTofu : secrets d'un parc, environnement de tofu, masquage."""

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ["todo.py"]
from script.opentofu import coffre as cf  # noqa: E402

JETON = "tofu@pve!parc-a=SECRET-123"


class TestCoffre(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.racine = Path(self._tmp.name)
        self._cache = tempfile.TemporaryDirectory()
        self.addCleanup(self._cache.cleanup)
        ancien = cf.CACHE_PLUGINS
        cf.CACHE_PLUGINS = Path(self._cache.name) / "plugins"
        self.addCleanup(setattr, cf, "CACHE_PLUGINS", ancien)

    def test_lire_absent(self):
        self.assertEqual(cf.lire("parc-a", self.racine), {})

    def test_ecrire_0600_et_relecture(self):
        cf.ecrire("parc-a", {"jeton": JETON}, self.racine)
        chemin = self.racine / "parc-a" / "secrets.json"
        self.assertEqual(stat.S_IMODE(chemin.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(chemin.parent.stat().st_mode), 0o700)
        self.assertEqual(cf.lire("parc-a", self.racine)["jeton"], JETON)

    def test_ecrire_remplace_tout(self):
        cf.ecrire("parc-a", {"jeton": JETON}, self.racine)
        cf.ecrire("parc-a", {"phrase_etat": "x" * 20}, self.racine)
        self.assertEqual(cf.lire("parc-a", self.racine), {"phrase_etat": "x" * 20})

    def test_phrase_stable(self):
        a = cf.phrase_etat("parc-a", self.racine)
        b = cf.phrase_etat("parc-a", self.racine)
        self.assertEqual(a, b)
        self.assertGreaterEqual(len(a), 16)
        self.assertEqual(cf.lire("parc-a", self.racine)["phrase_etat"], a)

    def test_phrase_conserve_le_jeton(self):
        cf.ecrire("parc-a", {"jeton": JETON}, self.racine)
        cf.phrase_etat("parc-a", self.racine)
        self.assertEqual(cf.lire("parc-a", self.racine)["jeton"], JETON)

    def test_environnement(self):
        cf.ecrire("parc-a", {"jeton": JETON}, self.racine)
        base = {"PATH": "/doublure/bin"}
        env = cf.environnement("parc-a", base, self.racine)
        self.assertEqual(env["PROXMOX_VE_API_TOKEN"], JETON)
        self.assertEqual(env["PATH"], "/doublure/bin")
        self.assertEqual(env["TF_IN_AUTOMATION"], "1")
        self.assertEqual(env["TF_INPUT"], "0")
        phrase = cf.lire("parc-a", self.racine)["phrase_etat"]
        self.assertIn(phrase, env["TF_ENCRYPTION"])
        self.assertTrue(Path(env["TF_PLUGIN_CACHE_DIR"]).is_dir())
        self.assertEqual(base, {"PATH": "/doublure/bin"})

    def test_environnement_sans_jeton(self):
        env = cf.environnement("parc-a", {}, self.racine)
        self.assertNotIn("PROXMOX_VE_API_TOKEN", env)
        self.assertIn("TF_ENCRYPTION", env)

    def test_environnement_retire_un_jeton_ambiant(self):
        base = {"PROXMOX_VE_API_TOKEN": "tofu@pve!autre=AMBIANT"}
        env = cf.environnement("parc-a", base, self.racine)
        self.assertNotIn("PROXMOX_VE_API_TOKEN", env)
        self.assertIn("PROXMOX_VE_API_TOKEN", base)
        cf.ecrire("parc-a", {"jeton": JETON}, self.racine)
        env = cf.environnement("parc-a", base, self.racine)
        self.assertEqual(env["PROXMOX_VE_API_TOKEN"], JETON)

    def test_environnement_retire_les_traces_tofu(self):
        base = {
            "TF_LOG": "TRACE",
            "TF_LOG_PATH": "/tmp/trace.log",
            "TF_LOG_CORE": "TRACE",
            "TF_LOG_PROVIDER": "TRACE",
            "PATH": "/doublure/bin",
        }
        env = cf.environnement("parc-a", base, self.racine)
        for nom in ("TF_LOG", "TF_LOG_PATH", "TF_LOG_CORE", "TF_LOG_PROVIDER"):
            self.assertNotIn(nom, env)
        self.assertEqual(env["PATH"], "/doublure/bin")
        self.assertIn("TF_LOG", base)

    def test_environnement_retire_tout_proxmox_ve_herite(self):
        base = {
            "PROXMOX_VE_ENDPOINT": "https://autre.invalid:8006/",
            "PROXMOX_VE_INSECURE": "false",
            "PROXMOX_VE_SSH_USERNAME": "autre",
            "PROXMOX_VE_API_TOKEN": "tofu@pve!autre=AMBIANT",
            "PATH": "/doublure/bin",
        }
        cf.ecrire("parc-a", {"jeton": JETON}, self.racine)
        env = cf.environnement("parc-a", base, self.racine)
        herites = sorted(k for k in env if k.startswith("PROXMOX_VE_"))
        self.assertEqual(herites, ["PROXMOX_VE_API_TOKEN"])
        self.assertEqual(env["PROXMOX_VE_API_TOKEN"], JETON)
        self.assertIn("PROXMOX_VE_SSH_USERNAME", base)

    def test_phrase_jamais_creee_a_cote_d_un_etat(self):
        """Une phrase neuve ne déchiffre pas un état chiffré par la perdue."""
        etat = self.racine / "parc-a" / ".tofu" / "terraform.tfstate"
        etat.parent.mkdir(parents=True)
        etat.write_text("{}")
        with self.assertRaises(ValueError) as e:
            cf.phrase_etat("parc-a", self.racine)
        self.assertIn("README", str(e.exception))
        self.assertEqual(cf.lire("parc-a", self.racine), {})
        cf.ecrire("parc-a", {"phrase_etat": "p" * 20}, self.racine)
        self.assertEqual(cf.phrase_etat("parc-a", self.racine), "p" * 20)

    def test_environnement_ne_touche_pas_os_environ(self):
        avant = dict(os.environ)
        cf.environnement("parc-a", None, self.racine)
        self.assertEqual(dict(os.environ), avant)

    def test_tf_encryption(self):
        hcl = cf.tf_encryption("p" * 20)
        for morceau in (
            'key_provider "pbkdf2" "main"',
            'method "aes_gcm" "main"',
            "keys = key_provider.pbkdf2.main",
            "method = method.aes_gcm.main",
            "enforced = true",
        ):
            self.assertIn(morceau, hcl)
        self.assertIn("state {", hcl)
        self.assertIn("plan {", hcl)

    def test_tf_encryption_echappe(self):
        hcl = cf.tf_encryption('a"b\\c' + "x" * 20)
        self.assertIn('passphrase = "a\\"b\\\\c', hcl)

    def test_tf_encryption_phrase_courte(self):
        with self.assertRaises(ValueError):
            cf.tf_encryption("court")

    def test_masquer(self):
        ligne = "Authorization: PVEAPIToken=tofu@pve!a=SECRET"
        out = cf.masquer(ligne, {"jeton": "tofu@pve!a=SECRET"})
        self.assertNotIn("SECRET", out)
        self.assertIn("***", out)

    def test_masquer_partie_secrete_seule(self):
        out = cf.masquer("x SECRET-123 y", {"jeton": JETON})
        self.assertNotIn("SECRET-123", out)

    def test_masquer_phrase_et_vide(self):
        out = cf.masquer("p=" + "q" * 20, {"phrase_etat": "q" * 20, "z": ""})
        self.assertNotIn("q" * 20, out)
        self.assertEqual(cf.masquer("abc", {"z": ""}), "abc")

    def test_masquer_plus_long_d_abord(self):
        out = cf.masquer("aaaa-bbbb", {"a": "aaaa", "b": "aaaa-bbbb"})
        self.assertEqual(out, "***")

    def test_conf(self):
        conf = cf.charger_conf()
        for cle in (
            "version",
            "required_version",
            "gpg_fingerprint",
            "cle_gpg_url",
            "providers",
        ):
            self.assertIn(cle, conf)
        self.assertIn("bpg/proxmox", conf["providers"])

    def test_conf_cle_manquante(self):
        chemin = self.racine / "c.json"
        chemin.write_text(json.dumps({"version": "1"}))
        with self.assertRaises(ValueError) as e:
            cf.charger_conf(chemin)
        self.assertIn("required_version", str(e.exception))


if __name__ == "__main__":
    unittest.main()
