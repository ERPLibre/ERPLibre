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

    def test_a_remote_entry_without_a_name_is_still_addressable(self):
        """Ce qui adresse n'est pas le même des deux côtés : le VMID suffit
        à commander, et l'absence de nom la laisse seulement DÉSARMÉE. La
        refuser ferait passer pour locale une VM qui ne l'est pas."""
        handle = V.handle_of({"pve": {"vmid": 101, "target": "hote"}})
        self.assertIsNotNone(handle)
        self.assertEqual(V.PVE, handle.backend)
        self.assertEqual("101", handle.key)
        self.assertFalse(V.is_armed(handle))
        self.assertTrue(V.is_hosted(handle))

    def test_a_remote_entry_with_neither_name_nor_vmid_designates_nothing(
        self,
    ):
        self.assertIsNone(V.handle_of({"pve": {"target": "hote"}}))

    def test_a_local_entry_without_a_name_still_designates_nothing(self):
        """virsh l'appelle par son nom : sans lui, il n'y a rien à viser."""
        self.assertIsNone(V.handle_of({"uuid": "abc-123", "ip": "192.0.2.10"}))

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
        from script.vm import verbs

        handle = V.handle_of(DISTANTE)
        garde = verbs.identity_guard(handle)
        self.assertIn(handle.key, garde)
        self.assertIn(handle.proof, garde)

    def test_the_local_guard_checks_what_the_handle_says(self):
        from script.vm import verbs

        handle = V.handle_of(LOCALE)
        commande = verbs.delete_command(handle, with_disks=False)
        self.assertIn(handle.key, commande)
        self.assertIn(handle.proof, commande)

    def test_an_unarmed_local_entry_produces_no_guard(self):
        """C'est le désarmement documenté, et il doit rester visible."""
        from script.vm import verbs

        handle = V.handle_of({"name": "essai"})
        self.assertFalse(V.is_armed(handle))
        self.assertNotIn(
            "REFUS", verbs.delete_command(handle, with_disks=False)
        )


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


class TestLesFabriquesRemplissentTout(unittest.TestCase):
    """Un seul endroit compose une fiche, et il la compose ENTIÈRE.

    Chaque appelant qui la composait lui-même le faisait par position. Un
    champ ajouté au milieu les décalait tous en silence : l'hôte se
    retrouvait dans l'adresse, et la commande partait vers une cible vide
    sans que rien ne le dise. Ces épreuves nomment chaque champ.
    """

    def test_the_remote_factory_fills_every_field(self):
        handle = V.pve_handle(
            {"vmid": 101, "target": "hote.exemple", "addr": "198.51.100.7"},
            "essai",
        )
        self.assertEqual(V.PVE, handle.backend)
        self.assertEqual("essai", handle.name)
        self.assertEqual("101", handle.key)
        self.assertEqual("essai", handle.proof)
        self.assertEqual("198.51.100.7", handle.address)
        self.assertEqual("hote.exemple", handle.host["target"])

    def test_the_local_factory_fills_every_field(self):
        handle = V.libvirt_handle("essai", uuid="abc-123", ip="192.0.2.10")
        self.assertEqual(V.LIBVIRT, handle.backend)
        self.assertEqual("essai", handle.name)
        self.assertEqual("essai", handle.key)
        self.assertEqual("abc-123", handle.proof)
        self.assertEqual("192.0.2.10", handle.address)
        self.assertEqual({}, dict(handle.host))

    def test_the_factories_and_the_reader_agree(self):
        """Deux chemins vers la même fiche finiraient par diverger."""
        self.assertEqual(
            V.handle_of(DISTANTE), V.pve_handle(DISTANTE["pve"], "essai")
        )
        self.assertEqual(
            V.handle_of(LOCALE),
            V.libvirt_handle("essai", uuid="abc-123", ip="192.0.2.10"),
        )

    def test_a_bare_factory_call_leaves_no_field_undefined(self):
        """Une fiche minimale doit rester utilisable, pas à moitié faite."""
        for handle in (V.pve_handle({}), V.libvirt_handle("essai")):
            with self.subTest(backend=handle.backend):
                self.assertIsInstance(handle.address, str)
                self.assertIsInstance(handle.proof, str)
                self.assertIsInstance(dict(handle.host), dict)


class TestQuiSaitRelireLAdresse(unittest.TestCase):
    """Ré-résoudre par l'hyperviseur local ne vaut que pour ses propres VM.

    Ailleurs, virsh trouve le domaine homonyme d'ICI et l'installation part
    sur la mauvaise machine — sans rien dire, puisque le domaine trouvé
    répond très bien.
    """

    def test_a_local_vm_is_resolved_locally(self):
        self.assertTrue(V.resolves_locally(V.handle_of(LOCALE)))

    def test_a_remote_vm_is_not(self):
        self.assertFalse(V.resolves_locally(V.handle_of(DISTANTE)))

    def test_an_absence_is_not_resolved_either(self):
        self.assertFalse(V.resolves_locally(None))

    def test_it_answers_for_every_backend_of_the_vocabulary(self):
        """Un backend neuf doit décider, pas hériter du silence."""
        for nom in V.BACKENDS:
            with self.subTest(backend=nom):
                handle = V.handle_of(LOCALE)._replace(backend=nom)
                self.assertIsInstance(V.resolves_locally(handle), bool)


class TestQuiPorteLaMachine(unittest.TestCase):
    """Le fait dont découlent les autres : ses commandes passent par
    quelqu'un d'autre, et son service ne se sonde pas d'ici."""

    def test_a_remote_vm_is_hosted(self):
        self.assertTrue(V.is_hosted(V.handle_of(DISTANTE)))

    def test_a_local_vm_is_not(self):
        self.assertFalse(V.is_hosted(V.handle_of(LOCALE)))

    def test_an_absence_is_not_hosted(self):
        self.assertFalse(V.is_hosted(None))

    def test_the_two_hypervisors_answer_inversely(self):
        """C'est cette coïncidence qui rendait la confusion possible."""
        for entree in (LOCALE, DISTANTE):
            handle = V.handle_of(entree)
            with self.subTest(backend=handle.backend):
                self.assertNotEqual(
                    V.is_hosted(handle), V.resolves_locally(handle)
                )

    def test_a_third_backend_answers_no_to_both(self):
        """LE cas qui prouve que ce sont deux questions distinctes. Une
        instance Lima n'est portée par personne — donc rien ne teste son
        service pour nous — ET virsh ne la connaît pas — donc son adresse
        ne se relit pas d'ici. Un prédicat unique aurait fait prendre l'un
        pour l'autre, en silence."""
        handle = V.lima_handle("essai")
        self.assertFalse(V.is_hosted(handle))
        self.assertFalse(V.resolves_locally(handle))


class TestRegrouperParMachinePorteuse(unittest.TestCase):
    """UN relevé par hôte, et non par VM.

    Chaque aller-retour coûte une poignée de main ssh ; un hôte rapporte
    toutes ses VM d'un coup. Interroger VM par VM multiplierait ce coût par
    leur nombre, sur le chemin qui se rejoue à chaque tour du suivi.
    """

    def fiches(self, *entrees):
        return [V.handle_of(entree) for entree in entrees]

    def test_two_vms_of_one_host_share_a_group(self):
        groupes = V.group_by_host(
            self.fiches(
                {"name": "a", "pve": {"vmid": 1, "target": "h1"}},
                {"name": "b", "pve": {"vmid": 2, "target": "h1"}},
            )
        )
        self.assertEqual(1, len(groupes))
        self.assertEqual(["a", "b"], [f.name for f in groupes[("h1", "")]])

    def test_two_hosts_are_two_groups(self):
        groupes = V.group_by_host(
            self.fiches(
                {"name": "a", "pve": {"vmid": 1, "target": "h1"}},
                {"name": "b", "pve": {"vmid": 2, "target": "h2"}},
            )
        )
        self.assertEqual(2, len(groupes))

    def test_two_accounts_on_one_machine_are_two_connections(self):
        """Les fondre ferait jouer la commande sous le mauvais compte."""
        groupes = V.group_by_host(
            self.fiches(
                {"name": "a", "pve": {"vmid": 1, "target": "h1"}},
                {
                    "name": "b",
                    "pve": {"vmid": 2, "target": "h1", "sudo": "sudo "},
                },
            )
        )
        self.assertEqual([("h1", ""), ("h1", "sudo ")], sorted(groupes))

    def test_a_local_vm_belongs_to_no_host(self):
        """Il n'y a personne à qui la demander."""
        groupes = V.group_by_host(
            self.fiches(
                {"name": "a", "ip": "192.0.2.10"},
                {"name": "b", "pve": {"vmid": 2, "target": "h1"}},
            )
        )
        self.assertEqual([("h1", "")], list(groupes))

    def test_an_absence_in_the_list_is_skipped(self):
        """`handle_of` rend None sur une entrée illisible : la laisser
        passer ferait tomber le relevé de tout le parc."""
        self.assertEqual({}, V.group_by_host([None]))

    def test_nothing_gives_nothing(self):
        self.assertEqual({}, V.group_by_host([]))
        self.assertEqual({}, V.group_by_host(None))

    def test_the_order_of_encounter_is_kept(self):
        """Le rang décide de l'ordre des appels, donc de ce qui s'affiche
        en premier quand un hôte est lent."""
        groupes = V.group_by_host(
            self.fiches(
                {"name": "a", "pve": {"vmid": 1, "target": "h2"}},
                {"name": "b", "pve": {"vmid": 2, "target": "h1"}},
            )
        )
        self.assertEqual([("h2", ""), ("h1", "")], list(groupes))


if __name__ == "__main__":
    unittest.main()
