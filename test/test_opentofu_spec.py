#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La spec d'un parc OpenTofu : schéma, validation, lecture et écriture."""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ["todo.py"]
from script.opentofu import spec as sp  # noqa: E402

DEPOT = Path(__file__).resolve().parent.parent


def _spec():
    return sp.nouvelle_spec("parc-a", "hote-x")


class TestSpec(unittest.TestCase):
    def test_nouvelle_spec_est_valide(self):
        self.assertEqual(sp.valider(_spec()), [])

    def test_nom_invalide(self):
        erreurs = sp.valider(sp.nouvelle_spec("Parc_A", "h"))
        self.assertTrue(any("Parc_A" in e for e in erreurs))

    def test_vm_en_double(self):
        s = _spec()
        s["vms"] = [dict(s["vms"][0], nom="a"), dict(s["vms"][0], nom="a")]
        self.assertEqual(len(sp.valider(s)), 1)

    def test_ip_fixe_sans_passerelle(self):
        s = _spec()
        s["vms"][0].update(ip="10.0.0.5/24", passerelle="")
        self.assertEqual(len(sp.valider(s)), 1)
        for ip, pas in (("auto", ""), ("dhcp", ""), ("10.0.0.5/24", "10.0.0.1")):
            s["vms"][0].update(ip=ip, passerelle=pas)
            self.assertEqual(sp.valider(s), [], ip)

    def test_disque_ram_vcpus(self):
        s = _spec()
        s["vms"][0].update(disque="20", ram=256, vcpus=0)
        self.assertEqual(len(sp.valider(s)), 3)

    def test_jump_refuse_en_v1(self):
        s = _spec()
        s["cible"]["hote"]["jump"] = "x"
        self.assertEqual(len(sp.valider(s)), 1)

    def test_distro_inconnue(self):
        distros = {"debian": ({"13": "trixie"},)}
        self.assertEqual(sp.valider(_spec(), distros), [])
        s = _spec()
        s["vms"][0]["distro"] = "plan9"
        self.assertEqual(len(sp.valider(s, distros)), 1)
        s["vms"][0].update(distro="debian", version="99")
        self.assertEqual(len(sp.valider(s, distros)), 1)

    def test_aller_retour(self):
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            s = _spec()
            chemin = sp.sauver(s, racine)
            self.assertEqual(sp.charger("parc-a", racine), s)
            self.assertEqual(stat.S_IMODE(os.stat(chemin).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(chemin.parent).st_mode), 0o700)
            self.assertEqual(sp.lister(racine), ["parc-a"])

    def test_json_abime(self):
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            sp.dossier_parc("parc-a", racine).mkdir(parents=True)
            (sp.dossier_parc("parc-a", racine) / "spec.json").write_text("{")
            with self.assertRaises(sp.SpecInvalide) as cm:
                sp.charger("parc-a", racine)
            self.assertTrue(cm.exception.erreurs)

    def test_nom_de_parc_refuse_dans_le_chemin(self):
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp) / "parcs"
            for nom in ("../x", "a/b", "", "Parc", ".", "a" * 32):
                with self.assertRaises(ValueError, msg=nom):
                    sp.dossier_parc(nom, racine)
            s = _spec()
            s["nom"] = "../evade"
            with self.assertRaises(ValueError):
                sp.sauver(s, racine)
            self.assertFalse((Path(tmp) / "evade").exists())
            with self.assertRaises(sp.SpecInvalide):
                sp.charger("../evade", racine)
            attendu = racine / "parc-a"
            self.assertEqual(sp.dossier_parc("parc-a", racine), attendu)

    def test_private_opentofu_ignore(self):
        for chemin in (
            "private/opentofu/x/spec.json",
            "private/opentofu/x/secrets.json",
            "private/opentofu/x/.tofu/terraform.tfstate",
        ):
            r = subprocess.run(["git", "check-ignore", "-q", chemin], cwd=DEPOT)
            self.assertEqual(r.returncode, 0, chemin)


if __name__ == "__main__":
    unittest.main()
