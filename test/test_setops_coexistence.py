#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un objet, un maître : ce que todo peut toucher sur une grappe partagée.

Deux erreurs, et elles ne coûtent pas la même chose. Refuser un geste sur une
VM dont todo est le maître agace ; laisser passer un geste sur une VM du
moteur détruit une machine que personne ne croyait en jeu. Et une collision
de VMID non vue coûte plus encore : on n'en sort pas en renommant, on change
l'INDEX de la flotte et on régénère.

D'où : forme inattendue → `INCONNU`, jamais un « libre » par défaut. Les
refus sont éprouvés un par un, et le contrôle positif — reconnaître une
grappe et un plan bien formés — vaut autant qu'eux.

Les noms d'écosystème, de pool et de VM sont inventés et n'existent nulle
part ailleurs dans le dépôt.
"""

import os
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.setops import coexistence as C  # noqa: E402

# La forme exacte que rend « make devis-proxmox-pools JSON=1 » : la recette
# écho la commande AVANT le document, et la lecture doit le supporter.
DEVIS = """python3 scripts/devis_proxmox_pools.py --json
{
  "pools": [
    {
      "pool": "OPS-Fictif-Dolomie",
      "tenant": "OPS-Fictif-Dolomie",
      "index": 7,
      "membres": [
        {"nom": "infra-pki-01", "vmid": 107103101, "etat": "actif"},
        {"nom": "backup-01", "vmid": 107905101, "etat": "planifie"}
      ],
      "sans_vmid": []
    }
  ]
}
"""

POOL = "OPS-Fictif-Dolomie"
DECLARE = 107103101
AUTRE_DECLARE = 107905101


def invite(vmid, nom="", pool=""):
    return C.Invite(vmid=vmid, nom=nom, noeud="noeud-fictif", pool=pool)


class TestLaLectureDuDevis(unittest.TestCase):
    def test_a_real_quote_is_read_through_the_echoed_command(self):
        """Le contrôle positif : sans lui, un lecteur qui refuse tout
        passerait chacun des refus éprouvés plus bas."""
        lu = C.lit_devis(DEVIS)
        self.assertEqual({POOL}, set(lu.pools))
        self.assertEqual(
            {
                DECLARE: (POOL, "infra-pki-01"),
                AUTRE_DECLARE: (POOL, "backup-01"),
            },
            lu.proprietaire,
        )

    def test_a_document_that_is_not_a_table_is_unknown(self):
        self.assertIsNone(C.lit_devis("[1, 2]"))
        self.assertIsNone(C.lit_devis("rien du tout"))
        self.assertIsNone(C.lit_devis(""))
        self.assertIsNone(C.lit_devis(None))

    def test_a_truncated_document_is_unknown(self):
        self.assertIsNone(C.lit_devis(DEVIS[: DEVIS.index("membres")]))

    def test_a_pool_without_a_name_is_unknown(self):
        """Un bloc sans nom de pool ne dit pas à qui ses VMID appartiennent :
        les garder nommerait un maître vide."""
        self.assertIsNone(
            C.lit_devis('{"pools": [{"pool": "  ", "membres": []}]}')
        )

    def test_a_member_whose_vmid_is_not_an_integer_is_unknown(self):
        """Une déclaration partielle ferait passer pour libre un VMID que le
        plan revendique — exactement le VMID qu'on ne doit pas reprendre."""
        self.assertIsNone(
            C.lit_devis(
                '{"pools": [{"pool": "p", "membres":'
                ' [{"nom": "x", "vmid": "107103101"}]}]}'
            )
        )

    def test_a_plan_that_declares_nothing_is_empty_and_not_unknown(self):
        """« Aucun écosystème découvert » et « forme illisible » sont
        deux nouvelles : la première laisse todo maître de tout."""
        lu = C.lit_devis('{"pools": []}')
        self.assertEqual(frozenset(), lu.pools)
        self.assertEqual({}, lu.proprietaire)


class TestLaFormeDuVmid(unittest.TestCase):
    """Neuf chiffres : VLAN sur quatre, hôte sur trois, rang sur deux."""

    def test_nine_digits_is_a_derived_shape(self):
        self.assertTrue(C.vmid_derive(107103101))

    def test_anything_shorter_is_not(self):
        for vmid in (142, 9999, 10710310):
            with self.subTest(vmid=vmid):
                self.assertFalse(C.vmid_derive(vmid))

    def test_what_is_not_a_whole_number_is_not_a_vmid(self):
        for vmid in (None, "107103101", True, -107103101, 1.0):
            with self.subTest(vmid=vmid):
                self.assertFalse(C.vmid_derive(vmid))


class TestLEtatDUnInvite(unittest.TestCase):
    def setUp(self):
        self.devis = C.lit_devis(DEVIS)

    def test_a_declared_vmid_names_the_pool_that_claims_it(self):
        self.assertEqual(
            (C.GERE, POOL), C.etat(invite(DECLARE, "infra-pki-01"), self.devis)
        )

    def test_an_expected_pool_names_itself(self):
        """Une VM du moteur qui n'est pas au plan — posée à la main dans son
        pool — reste une VM du moteur."""
        self.assertEqual(
            (C.GERE, POOL), C.etat(invite(500100100, "x", POOL), self.devis)
        )

    def test_a_derived_shape_accuses_nobody_but_is_not_free(self):
        """La forme seule ne prouve pas l'appartenance ; elle suffit à ne
        pas détruire sans demander."""
        self.assertEqual((C.DERIVE, ""), C.etat(invite(123456789), self.devis))

    def test_a_short_vmid_outside_every_pool_is_free(self):
        self.assertEqual(
            (C.LIBRE, ""), C.etat(invite(142, "ma-vm"), self.devis)
        )

    def test_the_old_world_pool_is_not_a_marker(self):
        """Une grappe de référence porte un pool nommé « Set-OPS » qui
        regroupe des VM ANTÉRIEURES au moteur. Le prendre pour un marqueur
        ferait refuser des gestes sur des machines dont todo est le maître.
        """
        self.assertEqual(
            (C.LIBRE, ""),
            C.etat(invite(142, "ancienne", C.POOL_ANCIEN), self.devis),
        )

    def test_without_a_plan_nothing_is_free(self):
        """Sans plan, « libre » ne se prouve pas : même un VMID court est
        inconnu, et l'appelant refuse."""
        self.assertEqual((C.INCONNU, ""), C.etat(invite(142), None))

    def test_without_a_guest_nothing_is_free_either(self):
        self.assertEqual((C.INCONNU, ""), C.etat(None, self.devis))


class TestLaCollisionDeVmid(unittest.TestCase):
    """LE constat qui coûte le plus cher : on n'en sort pas en renommant,
    on change l'index de la flotte et on régénère."""

    def setUp(self):
        self.devis = C.lit_devis(DEVIS)

    def test_a_legacy_vm_on_a_declared_vmid_collides(self):
        vus = C.collisions(
            [invite(AUTRE_DECLARE, "vieille-fictive", "Prod.Ancien")],
            self.devis,
        )
        self.assertEqual(1, len(vus))
        self.assertEqual(
            (AUTRE_DECLARE, POOL, "backup-01", "vieille-fictive"),
            (
                vus[0].vmid,
                vus[0].declare_par,
                vus[0].nom_declare,
                vus[0].occupe_par,
            ),
        )

    def test_the_fleet_vm_in_its_pool_does_not_collide_with_itself(self):
        self.assertEqual(
            (),
            C.collisions([invite(DECLARE, "infra-pki-01", POOL)], self.devis),
        )

    def test_the_fleet_vm_not_yet_poured_into_its_pool_is_recognised(self):
        """Posée mais pas encore versée dans son pool, elle passerait pour
        une étrangère si le pool décidait seul. Le nom la rattrape."""
        self.assertEqual(
            (), C.collisions([invite(DECLARE, "infra-pki-01")], self.devis)
        )

    def test_a_guest_outside_the_plan_never_collides(self):
        self.assertEqual((), C.collisions([invite(142, "ma-vm")], self.devis))

    def test_a_same_named_guest_on_an_undeclared_vmid_is_not_a_collision(self):
        """Le VMID décide : deux tenants portent volontairement le même nom
        court, c'est la preuve que la nomenclature est un gabarit."""
        self.assertEqual(
            (), C.collisions([invite(142, "infra-pki-01")], self.devis)
        )

    def test_either_side_unreadable_proves_nothing(self):
        """Une absence de collision lue sur un seul côté rassurerait à tort,
        et c'est le pire des verdicts pour un constat qui coûte deux heures.
        """
        self.assertIsNone(C.collisions(None, self.devis))
        self.assertIsNone(C.collisions([invite(DECLARE)], None))

    def test_several_collisions_come_back_in_a_stable_order(self):
        """Une liste qui change d'ordre d'un lancement à l'autre se relit
        mal, et ce rapport se relit deux fois plutôt qu'une."""
        grappe = [
            invite(AUTRE_DECLARE, "b-fictive", "Prod.Ancien"),
            invite(DECLARE, "a-fictive", "Prod.Ancien"),
        ]
        vus = C.collisions(grappe, self.devis)
        self.assertEqual([DECLARE, AUTRE_DECLARE], [c.vmid for c in vus])


class TestCeQuUnPlanReclame(unittest.TestCase):
    def setUp(self):
        self.devis = C.lit_devis(DEVIS)

    def test_a_declared_vmid_names_its_pool(self):
        self.assertEqual(POOL, C.vmid_revendique(DECLARE, self.devis))

    def test_an_undeclared_one_is_free_and_says_so(self):
        self.assertEqual("", C.vmid_revendique(142, self.devis))

    def test_without_a_plan_the_answer_is_unknown_not_free(self):
        """« Libre » et « lecture impossible » mènent à deux gestes
        opposés : créer, ou refuser."""
        self.assertIsNone(C.vmid_revendique(142, None))


if __name__ == "__main__":
    unittest.main()
