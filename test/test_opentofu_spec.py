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
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ["todo.py"]
from script.opentofu import moteur as mo  # noqa: E402
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

    def test_champ_absent_ou_mal_type_donne_une_erreur(self):
        """Chaque champ que le moteur lit est contrôlé : présence et type,
        jamais un KeyError ni un TypeError plus loin."""
        distros = {"debian": ({"13": "trixie"},)}
        cas = (
            (("cible", "insecure"), "oui"),
            (("compte", "user"), ""),
            (("compte", "user"), 7),
            (("compte", "ssh_key"), ""),
            (("compte", "ssh_key"), None),
            (("vms", 0, "arch"), ""),
            (("vms", 0, "arch"), 64),
            (("vms", 0, "demarrer"), "oui"),
            (("vms", 0, "installer_erplibre"), 1),
            (("vms", 0, "distro"), ["debian"]),
            (("vms", 0, "version"), {"13": 1}),
            (("vms", 0, "passerelle"), 1),
        )
        for chemin, valeur in cas:
            for retirer in (True, False):
                s = _spec()
                noeud = s
                for cle in chemin[:-1]:
                    noeud = noeud[cle]
                if retirer:
                    del noeud[chemin[-1]]
                else:
                    noeud[chemin[-1]] = valeur
                if retirer and chemin[-1] == "passerelle":
                    continue
                erreurs = sp.valider(s, distros)
                self.assertTrue(erreurs, (chemin, retirer, valeur))

    def test_compte_et_port_ssh_de_l_hote(self):
        s = _spec()
        for port in (None, 22, 2222):
            s["cible"]["ssh_port"] = port
            self.assertEqual(sp.valider(s), [], port)
        for port in ("22", 0, 70000, True):
            s["cible"]["ssh_port"] = port
            self.assertEqual(len(sp.valider(s)), 1, port)
        s["cible"].update(ssh_port=None, ssh_user=7)
        self.assertEqual(len(sp.valider(s)), 1)

    def test_vmid_en_double(self):
        s = _spec()
        s["vms"] = [
            dict(s["vms"][0], nom="a", vmid=120),
            dict(s["vms"][0], nom="b", vmid=120),
            dict(s["vms"][0], nom="c", vmid=None),
            dict(s["vms"][0], nom="d", vmid=None),
        ]
        erreurs = sp.valider(s)
        self.assertEqual(len(erreurs), 1)
        self.assertIn("120", erreurs[0])

    def test_moteur_connu_accepte_inconnu_refuse(self):
        s = _spec()
        s["moteur"] = "inexistant"
        self.assertEqual(len(sp.valider(s)), 1)
        with mock.patch.dict(mo._REGISTRE, {"autre": object}):
            s["moteur"] = "autre"
            self.assertEqual(sp.valider(s), [])

    def test_cle_ssh_jamais_vide_a_la_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(Path, "home", return_value=Path(tmp)):
                cle = sp.nouvelle_spec("parc-a", "h")["compte"]["ssh_key"]
                self.assertEqual(cle, "~/.ssh/id_ed25519.pub")
                (Path(tmp) / ".ssh").mkdir()
                (Path(tmp) / ".ssh" / "id_rsa.pub").write_text("x")
                cle = sp.nouvelle_spec("parc-a", "h")["compte"]["ssh_key"]
                self.assertEqual(cle, str(Path(tmp) / ".ssh" / "id_rsa.pub"))

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
