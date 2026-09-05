#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'identité d'une VM : ce qui l'adresse, ce qui le prouve.

Toute une famille de bugs vient d'une confusion unique — le nom qu'on lit
n'est pas la clé qui commande. Ces épreuves tiennent la séparation, et
surtout le fait qu'elle est DIFFÉRENTE d'un backend à l'autre : c'est
précisément pour ça qu'on ne peut pas la deviner au cas par cas.

Rien ici ne touche à une machine : une identité est une donnée.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script import vm as V  # noqa: E402

LOCALE = {"name": "essai", "ip": "192.0.2.10", "uuid": "abc-123"}
DISTANTE = {
    "name": "essai",
    "pve": {"vmid": 101, "target": "hote.exemple", "addr": "198.51.100.7"},
}


class TestCeQuiAdresseEtCeQuiPromet(unittest.TestCase):
    def test_a_local_vm_is_addressed_by_name_and_proved_by_uuid(self):
        """C'est virsh qui impose le nom ; l'UUID naît avec le domaine."""
        handle = V.handle_of(LOCALE)
        self.assertEqual(V.LIBVIRT, handle.backend)
        self.assertEqual("essai", handle.key)
        self.assertEqual("abc-123", handle.proof)

    def test_a_proxmox_vm_is_addressed_by_vmid_and_proved_by_name(self):
        """Un VMID libéré est RÉATTRIBUÉ : effacer « le 101 » d'un manifeste
        de mars, c'est effacer ce qui porte le 101 aujourd'hui."""
        handle = V.handle_of(DISTANTE)
        self.assertEqual(V.PVE, handle.backend)
        self.assertEqual("101", handle.key)
        self.assertEqual("essai", handle.proof)

    def test_the_pairing_is_not_the_same_on_both(self):
        """LE fait qui justifie le modèle : deviner au cas par cas revient
        à se tromper une fois sur deux."""
        locale = V.handle_of(LOCALE)
        distante = V.handle_of(DISTANTE)
        self.assertTrue(V.addresses_by_name(locale))
        self.assertFalse(V.addresses_by_name(distante))

    def test_the_host_travels_with_a_remote_handle(self):
        """Un verbe doit savoir qu'il passe par quelqu'un d'autre."""
        self.assertEqual("hote.exemple", V.handle_of(DISTANTE).host["target"])
        self.assertEqual({}, dict(V.handle_of(LOCALE).host))

    def test_every_backend_is_in_the_closed_vocabulary(self):
        self.assertTrue(V.BACKENDS)
        for entree in (LOCALE, DISTANTE):
            with self.subTest(entree=entree.get("name")):
                self.assertIn(V.handle_of(entree).backend, V.BACKENDS)


class TestQuandLIdentiteManque(unittest.TestCase):
    def test_an_entry_without_a_name_designates_nothing(self):
        """Rendre une identité vide commanderait au hasard."""
        self.assertIsNone(V.handle_of({}))
        self.assertIsNone(V.handle_of(None))
        self.assertIsNone(V.handle_of({"uuid": "abc-123"}))

    def test_a_local_entry_without_a_uuid_is_unarmed(self):
        """Une preuve vide DÉSARME au lieu de bloquer — mieux vaut la
        prudence d'avant que refuser toute opération sur un poste où on n'a
        pas pu la relever. Mais l'appelant doit pouvoir le dire."""
        handle = V.handle_of({"name": "essai"})
        self.assertFalse(V.is_armed(handle))
        self.assertTrue(V.is_armed(V.handle_of(LOCALE)))

    def test_a_remote_entry_is_armed_by_its_own_name(self):
        """Contrôle positif : la preuve n'est pas toujours un champ à part."""
        self.assertTrue(V.is_armed(V.handle_of(DISTANTE)))

    def test_a_missing_vmid_reads_as_zero_and_not_as_a_crash(self):
        handle = V.handle_of({"name": "essai", "pve": {"target": "h"}})
        self.assertEqual("0", handle.key)


class TestDeuxHomonymesNeSontPasUneMachine(unittest.TestCase):
    """L'écran qui les confondrait est celui qui a ouvert la mauvaise."""

    def test_the_same_name_on_two_backends_is_two_machines(self):
        self.assertFalse(
            V.same_machine(V.handle_of(LOCALE), V.handle_of(DISTANTE))
        )

    def test_the_same_vmid_on_two_hosts_is_two_machines(self):
        ailleurs = dict(
            DISTANTE, pve=dict(DISTANTE["pve"], target="autre.exemple")
        )
        self.assertFalse(
            V.same_machine(V.handle_of(DISTANTE), V.handle_of(ailleurs))
        )

    def test_the_same_name_with_another_key_is_another_machine(self):
        """LE cas que la preuve existe pour attraper : un manifeste de mars
        nomme le 101, et « essai » porte le 102 aujourd'hui. Même backend,
        même hôte, même nom — et deux machines."""
        ancien = V.handle_of(DISTANTE)
        actuel = V.handle_of(
            dict(DISTANTE, pve=dict(DISTANTE["pve"], vmid=102))
        )
        self.assertEqual(ancien.name, actuel.name)
        self.assertEqual(ancien.host["target"], actuel.host["target"])
        self.assertFalse(V.same_machine(ancien, actuel))

    def test_a_handle_is_the_same_machine_as_itself(self):
        """Contrôle positif : tout distinguer ne prouverait rien."""
        for entree in (LOCALE, DISTANTE):
            with self.subTest(entree=entree.get("name")):
                self.assertTrue(
                    V.same_machine(V.handle_of(entree), V.handle_of(entree))
                )

    def test_nothing_is_the_same_machine_as_an_absence(self):
        self.assertFalse(V.same_machine(V.handle_of(LOCALE), None))
        self.assertFalse(V.same_machine(None, None))


class TestLeModeleDitCeQueLesGardesFontDeja(unittest.TestCase):
    """Le modèle doit décrire le code EXISTANT, pas un code parallèle.

    Sans ces deux épreuves, il serait une invention élégante à côté de la
    plaque, et le dé-silotage la découvrirait un verbe trop tard.
    """

    def test_the_proxmox_guard_checks_what_the_handle_says(self):
        from script.todo.qemu_install_monitor import pve_identity_guard

        handle = V.handle_of(DISTANTE)
        garde = pve_identity_guard(int(handle.key), handle.proof)
        self.assertIn(handle.key, garde)
        self.assertIn(handle.proof, garde)

    def test_the_local_guard_checks_what_the_handle_says(self):
        from script.todo.qemu_install_monitor import delete_vm_cmd

        handle = V.handle_of(LOCALE)
        commande = delete_vm_cmd(handle.name, False, uuid=handle.proof)
        self.assertIn(handle.key, commande)
        self.assertIn(handle.proof, commande)

    def test_an_unarmed_local_entry_produces_no_guard(self):
        """C'est le désarmement documenté, et il doit rester visible."""
        from script.todo.qemu_install_monitor import delete_vm_cmd

        handle = V.handle_of({"name": "essai"})
        self.assertFalse(V.is_armed(handle))
        self.assertNotIn("REFUS", delete_vm_cmd(handle.name, False, uuid=""))


class TestLaFicheDHoteNeSePartagePas(unittest.TestCase):
    def test_the_default_host_cannot_be_filled_for_everyone(self):
        """Un dictionnaire nu par défaut serait partagé par toutes les
        fiches qui l'omettent, et l'une d'elles finirait par le remplir
        pour les autres."""
        handle = V.VmHandle("libvirt", "essai", "essai", "abc")
        with self.assertRaises(TypeError):
            handle.host["target"] = "ailleurs"
        self.assertEqual({}, dict(V.VmHandle("libvirt", "a", "a", "b").host))


class TestIlNeCommandeRien(unittest.TestCase):
    def test_the_module_neither_runs_nor_prints(self):
        import ast

        chemin = os.path.join(RACINE, "script", "vm", "backend.py")
        with open(chemin, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        noms = [
            noeud.func.id
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
        ]
        self.assertTrue(noms, "aucun appel lu : rien n'est prouvé")
        for interdit in ("print", "input", "run", "exec"):
            self.assertNotIn(interdit, noms)


if __name__ == "__main__":
    unittest.main()
