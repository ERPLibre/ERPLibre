#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu Proxmox : les ssh d'une sélection de VM partent en même temps.

Deux boucles du menu envoient un ssh par VM vers le même hôte : le changement
d'état (« qm start/shutdown/stop ») et la recherche des adresses pour
~/.ssh/config. Ces tests gardent trois choses :

- Le chevauchement : une threading.Barrier ne s'ouvre que si tous les appels
  sont en vol en même temps ; une boucle en série la casse au bout du délai.
- L'ordre : la sortie suit la sélection, même quand le premier appel finit
  le dernier.
- La série de ce qui doit l'être : l'écriture de ~/.ssh/config, une entrée
  après l'autre, dans l'ordre des VM.
"""

import contextlib
import io
import sys
import threading
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.proxmox import proxmox_deploy as pve  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

HOTE = {"target": "root@hyperviseur.invalid", "jump": "", "sudo": ""}
VMS = [
    {"vmid": "101", "name": "alpha", "status": "running"},
    {"vmid": "102", "name": "beta", "status": "running"},
    {"vmid": "103", "name": "gamma", "status": "running"},
]


def _todo():
    todo = TODO.__new__(TODO)
    todo._pve_host_cache = HOTE
    # Sans moteur Set-OPS : la garde de coexistence a ses propres épreuves,
    # et lirait sinon le plan du moteur installé sur la station.
    todo._pve_devis = lambda: (False, None)
    return todo


def _croise():
    """Rend attendre(vmid) : bloque jusqu'à ce que les trois appels soient en
    vol, puis fait finir 101 APRÈS 103, pour que l'ordre d'achèvement soit
    l'inverse de la sélection."""
    barriere = threading.Barrier(len(VMS), timeout=5)
    dernier_fini = threading.Event()

    def attendre(vmid):
        barriere.wait()
        if vmid == "101":
            dernier_fini.wait(5)
        elif vmid == "103":
            dernier_fini.set()

    return attendre


class TestChangementDEtat(unittest.TestCase):
    def lancer(self, faux_run):
        todo = _todo()
        sortie = io.StringIO()
        with (
            mock.patch.object(pve, "run", side_effect=faux_run),
            mock.patch("builtins.input", side_effect=["all", "2", "y"]),
            contextlib.redirect_stdout(sortie),
        ):
            todo._pve_change_state(list(VMS))
        return sortie.getvalue()

    def test_les_arrets_se_chevauchent_et_s_affichent_dans_l_ordre(self):
        attendre = _croise()

        def faux_run(host, remote, timeout=120):
            if remote == "qm list":
                return 0, ""
            vmid = remote.split()[-1]
            attendre(vmid)
            return 0, f"sortie-{vmid}"

        texte = self.lancer(faux_run)
        positions = [
            texte.index(m)
            for m in (
                "qm shutdown 101",
                "qm shutdown 103",
                "sortie-101",
                "✓ alpha",
                "sortie-102",
                "✓ beta",
                "sortie-103",
                "✓ gamma",
            )
        ]
        self.assertEqual(sorted(positions), positions)

    def test_une_vm_en_echec_n_empeche_pas_les_autres(self):
        attendre = _croise()

        def faux_run(host, remote, timeout=120):
            if remote == "qm list":
                return 0, ""
            vmid = remote.split()[-1]
            attendre(vmid)
            return (255, "refus") if vmid == "102" else (0, "")

        texte = self.lancer(faux_run)
        self.assertIn("✓ alpha", texte)
        self.assertIn("✗ beta", texte)
        self.assertIn("✓ gamma", texte)
        self.assertLess(texte.index("refus"), texte.index("✗ beta"))
        self.assertEqual(1, texte.count("255"))

    def test_sans_hote_rien_ne_part(self):
        todo = TODO.__new__(TODO)
        todo._pve_host_cache = None
        todo._pve_devis = lambda: (False, None)
        with (
            mock.patch.object(todo, "_pve_host", return_value=None),
            mock.patch.object(pve, "run") as run,
            mock.patch("builtins.input", side_effect=["all", "2", "y"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._pve_change_state(list(VMS))
        run.assert_not_called()


class TestConfigurationSsh(unittest.TestCase):
    def test_les_adresses_se_cherchent_ensemble_et_s_ecrivent_en_ordre(self):
        attendre = _croise()
        todo = _todo()

        def faux_guest_ip(vmid, attente=120):
            attendre(vmid)
            return "" if vmid == "102" else f"192.0.2.{vmid[-1]}"

        ecrits = []
        todo._pve_vms = lambda: list(VMS)
        todo._pve_guest_ip = faux_guest_ip
        todo._ssh_private_key = lambda cle: cle
        todo._qemu_default_ssh_key = lambda: "~/.ssh/cle"
        todo._qemu_list_domains = lambda: []
        todo._pve_alias_names = lambda nom, *a: ([nom], "")
        todo._pve_alias_perime = lambda *a: []
        todo._write_ssh_config_entry = lambda noms, user, ip, **k: (
            ecrits.append((noms[0], ip))
        )
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            todo._pve_ssh_config()
        self.assertEqual(
            [("alpha", "192.0.2.1"), ("gamma", "192.0.2.3")], ecrits
        )
        texte = sortie.getvalue()
        self.assertLess(texte.index("ssh alpha"), texte.index("⚠ beta"))
        self.assertLess(texte.index("⚠ beta"), texte.index("ssh gamma"))


if __name__ == "__main__":
    unittest.main()
