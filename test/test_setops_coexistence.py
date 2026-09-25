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
from script.todo.todo_i18n import t  # noqa: E402

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


class TestCeQuiNaPasDeMaitre(unittest.TestCase):
    """Deux pools sur un VMID, ou un VMID impossible : refuser, pas choisir.

    Écraser la première revendication ferait nommer le mauvais dépôt à
    l'écran de refus, et ferait accuser la VM légitime du premier pool
    d'occuper un VMID « prévu » pour le second.
    """

    DOUBLE = (
        '{"pools": ['
        '{"pool": "OPS-Fictif-Alfa", "membres":'
        ' [{"nom": "alfa-01", "vmid": 100910101}]},'
        '{"pool": "OPS-Fictif-Bravo", "membres":'
        ' [{"nom": "bravo-01", "vmid": 100910101}]}]}'
    )

    def test_two_pools_claiming_one_vmid_have_no_master(self):
        self.assertIsNone(C.lit_devis(self.DOUBLE))

    def test_the_same_vmid_twice_in_one_pool_is_refused_too(self):
        """Le moteur porte ce contrôle dans son « --verifier », qui rend
        AVANT d'imprimer le JSON : la lecture d'ici ne le voit jamais."""
        self.assertIsNone(
            C.lit_devis(
                '{"pools": [{"pool": "p", "membres":'
                ' [{"nom": "a", "vmid": 7}, {"nom": "b", "vmid": 7}]}]}'
            )
        )

    def test_a_vmid_that_cannot_exist_is_refused(self):
        """-1 est la sentinelle que l'appelant fabrique pour « VMID
        illisible » : la laisser entrer ferait rendre GERE à un inconnu."""
        for vmid in (0, -1, -5):
            with self.subTest(vmid=vmid):
                self.assertIsNone(
                    C.lit_devis(
                        '{"pools": [{"pool": "p", "membres":'
                        ' [{"nom": "x", "vmid": %d}]}]}' % vmid
                    )
                )

    def test_a_plain_plan_is_still_read(self):
        """Contrôle positif : refuser tout passerait les trois refus."""
        self.assertIsNotNone(C.lit_devis(DEVIS))


class TestLeGenomeDuSite(unittest.TestCase):
    """Les machines du site — cache, forge, AC, noms, dépôt, gabarit doré —
    ne dérivent d'aucun index, et le devis ne nomme leur pool que si un
    underlay est monté. Leur marqueur doit donc valoir sans lui."""

    def test_the_site_pool_is_a_master_even_when_the_plan_ignores_it(self):
        devis = C.lit_devis(DEVIS)
        self.assertNotIn(C.POOL_SITE, devis.pools)
        self.assertEqual(
            (C.GERE, C.POOL_SITE),
            C.etat(invite(9000, "gabarit-dore", C.POOL_SITE), devis),
        )

    def test_a_golden_template_vmid_derives_from_nothing(self):
        """Son VMID n'a pas la forme dérivée : sans le pool, rien ne le
        rattrape et le geste destructeur partirait."""
        self.assertFalse(C.vmid_derive(9000))

    def test_without_a_plan_the_site_pool_is_still_unknown(self):
        """Le raccourci ne contourne pas le « fermé par défaut » : sans
        devis, on ne sait rien de personne."""
        self.assertEqual(
            (C.INCONNU, ""), C.etat(invite(9000, "x", C.POOL_SITE), None)
        )


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

    def test_a_foreign_homonym_on_a_declared_vmid_still_collides(self):
        """L'homonymie est VOULUE : le même nom court désigne la même
        fonction chez deux locataires. Un nom qui concorde ne prouve donc
        rien dès que l'occupant porte un pool — et le rattrapage large
        avalait ici le constat le plus cher."""
        vus = C.collisions(
            [invite(DECLARE, "infra-pki-01", "Prod.Ancien")], self.devis
        )
        self.assertEqual(1, len(vus), vus)
        self.assertEqual("Prod.Ancien", vus[0].pool_occupant)

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


class CasDeChoisisseur(unittest.TestCase):
    """Le choisisseur de VM du menu Proxmox, la grappe et le plan POSÉS.

    Rien n'est lancé : `_pve_maitrise` est remplacé par un relevé, et tout
    sous-processus ferait échouer l'épreuve. C'est ce qui permet d'éprouver
    des états qu'on ne peut pas provoquer sur ce poste.
    """

    LISTE = [
        {"vmid": DECLARE, "name": "infra-pki-01", "status": "running"},
        {"vmid": 142, "name": "ma-vm-fictive", "status": "running"},
    ]

    def setUp(self):
        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        self.todo = TODO.__new__(TODO)
        self.todo._pve_vms = lambda: list(self.LISTE)
        self.armer(C.lit_devis(DEVIS), (invite(DECLARE, "infra-pki-01"),))

    def armer(self, devis, invites, armee=True):
        self.todo._pve_maitrise = lambda: (armee, devis, invites)

    def choisir(self, saisies, **kw):
        """Tape `saisies` au choisisseur ; rend (choix, écran)."""
        import builtins
        import io as _io
        from contextlib import redirect_stdout

        file = list(saisies)
        vrai = builtins.input
        builtins.input = lambda *_a, **_k: file.pop(0) if file else ""
        vu = _io.StringIO()
        try:
            with redirect_stdout(vu):
                choix = self.todo._pve_pick_vm(**kw)
        finally:
            builtins.input = vrai
        return choix, vu.getvalue()


class TestLeChoisisseurGarde(CasDeChoisisseur):
    def test_a_read_only_gesture_touches_a_managed_guest(self):
        """Ouvrir une console sur une VM du moteur ne casse rien : la
        gradation existe pour que la garde reste crédible."""
        choix, _vu = self.choisir(["1"], garde=C.AUCUNE)
        self.assertEqual(DECLARE, choix["vmid"])

    def test_a_destructive_gesture_is_refused_and_names_the_master(self):
        choix, vu = self.choisir(["1"], garde=C.REFUS)
        self.assertIsNone(choix)
        self.assertIn(POOL, vu)

    def test_a_modifying_gesture_goes_on_once_the_name_is_retyped(self):
        choix, _vu = self.choisir(["1", "infra-pki-01"], garde=C.RETAPER)
        self.assertEqual(DECLARE, choix["vmid"])

    def test_a_wrong_retype_stops_the_modifying_gesture(self):
        choix, _vu = self.choisir(["1", "pas-le-bon-nom"], garde=C.RETAPER)
        self.assertIsNone(choix)

    def test_a_free_guest_is_never_in_the_way(self):
        for garde in (C.AUCUNE, C.RETAPER, C.REFUS):
            with self.subTest(garde=garde):
                choix, _vu = self.choisir(["2"], garde=garde)
                self.assertEqual(142, choix["vmid"])

    def test_the_default_is_the_strictest(self):
        """Un geste qui ne se déclare pas hérite du refus, jamais du
        silence : c'est ce qui rattrape celui qu'on ajoutera sans y penser.
        """
        choix, _vu = self.choisir(["1"])
        self.assertIsNone(choix)

    def test_only_the_managed_ones_are_dropped_from_a_multiple_pick(self):
        """Un invité du moteur ne doit pas fermer le geste sur ses voisins,
        sans quoi l'opérateur retire la garde pour avancer."""
        choix, _vu = self.choisir(["1 2"], multiple=True, garde=C.REFUS)
        self.assertEqual([142], [v["vmid"] for v in choix])

    def test_an_unreadable_cluster_refuses_even_a_free_looking_guest(self):
        """Sans preuve d'appartenance, aucun geste : c'est le même parti que
        « ne libérer que ce qui se prouve orphelin »."""
        self.armer(C.lit_devis(DEVIS), None)
        choix, vu = self.choisir(["2"], garde=C.REFUS)
        self.assertIsNone(choix)
        self.assertIn(t("ownership could not be read"), vu)

    def test_an_unreadable_plan_refuses_too(self):
        self.armer(None, (invite(142, "ma-vm-fictive"),))
        choix, _vu = self.choisir(["2"], garde=C.REFUS)
        self.assertIsNone(choix)

    def test_without_the_engine_the_guard_does_not_arm(self):
        """Sans Set-OPS sur le poste, aucun objet n'a d'autre maître :
        refuser serait refuser pour personne, et fermerait le menu Proxmox
        de tous ceux qui n'utilisent pas le moteur."""
        self.armer(None, None, armee=False)
        choix, _vu = self.choisir(["1"], garde=C.REFUS)
        self.assertEqual(DECLARE, choix["vmid"])


class TestChaqueGesteTraverseLaGarde(unittest.TestCase):
    """Tout geste qui bâtit une commande depuis une VM passe par la garde.

    LA PROPRIÉTÉ, PAS L'ORTHOGRAPHE. Chercher le littéral
    « self._pve_pick_vm( » laissait invisible tout geste qui choisit ses VM
    autrement — et il y en avait un, avec sa propre sélection « all », qui
    coupait le courant d'un invité de flotte sans que rien ne le dise.

    On balaie donc les méthodes qui LISENT un vmid ET envoient une commande,
    et on exige que chacune traverse l'une des trois portes : le choisisseur
    avec sa sévérité, le filtre de coexistence, ou la lecture des réserves
    pour les gestes qui raisonnent sur des VMID plutôt que sur des VM.
    """

    SOURCE = os.path.join(
        os.path.dirname(__file__), "..", "script", "todo", "proxmox_menu.py"
    )
    PORTES = ("_pve_permis(", "_pve_reserves(", "garde=")

    def gestes(self):
        """{nom: source} des méthodes qui bâtissent une commande sur un
        vmid."""
        import ast

        with open(self.SOURCE, encoding="utf-8") as fichier:
            texte = fichier.read()
        trouves = {}
        for noeud in ast.walk(ast.parse(texte)):
            if not isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            corps = ast.get_source_segment(texte, noeud) or ""
            lit = '["vmid"]' in corps or '.get("vmid")' in corps
            if lit and "self._pve_show(" in corps:
                trouves[noeud.name] = corps
        return trouves

    def test_the_scan_found_the_gestures(self):
        """Un balayage qui ne trouve rien passerait l'épreuve suivante sans
        avoir regardé quoi que ce soit."""
        self.assertGreaterEqual(len(self.gestes()), 4)

    def test_every_such_gesture_goes_through_one_of_the_doors(self):
        muets = [
            nom
            for nom, corps in self.gestes().items()
            if not any(porte in corps for porte in self.PORTES)
        ]
        self.assertEqual(
            [],
            muets,
            "ces gestes bâtissent une commande sur une VM sans passer par"
            " la garde de coexistence",
        )

    def test_every_severity_named_is_one_of_the_closed_vocabulary(self):
        import re

        nommees = [
            nom
            for corps in self.gestes().values()
            for nom in re.findall(r"garde=coexistence\.(\w+)", corps)
        ]
        self.assertTrue(nommees)
        for nom in nommees:
            with self.subTest(garde=nom):
                self.assertIn(getattr(C, nom, None), C.GARDES)


class TestLeCourantCoupeEstLePlusStrict(CasDeChoisisseur):
    """« stop » coupe le courant : il ne se rattrape pas en retapant un nom,
    contrairement à « start » et « shutdown ». Le palier se MESURE en jouant
    le geste, pas en lisant comment il est écrit."""

    def severite(self, choix_du_verbe):
        """La sévérité que `_pve_change_state` demande pour ce verbe."""
        import builtins
        import io as _io
        from contextlib import redirect_stdout

        vues = []
        self.todo._pve_vms = lambda: [
            {"vmid": 142, "name": "ma-vm-fictive", "status": "running"}
        ]
        self.todo._pve_permis = lambda choisis, garde: vues.append(garde) or []
        saisies = iter(["1", choix_du_verbe])
        vrai = builtins.input
        builtins.input = lambda *_a, **_k: next(saisies, "")
        try:
            with redirect_stdout(_io.StringIO()):
                self.todo._pve_change_state()
        finally:
            builtins.input = vrai
        self.assertEqual(1, len(vues), vues)
        return vues[0]

    def test_pulling_the_plug_is_refused(self):
        self.assertEqual(C.REFUS, self.severite("3"))

    def test_starting_and_shutting_down_ask_for_the_name(self):
        for choix, geste in (("1", "start"), ("2", "shutdown")):
            with self.subTest(geste=geste):
                self.assertEqual(C.RETAPER, self.severite(choix))


class TestLEcranDeCollision(CasDeChoisisseur):
    """L'écran qui annonce les deux heures : ce qu'il dit, et quand."""

    def ecran(self):
        import io as _io
        from contextlib import redirect_stdout

        vu = _io.StringIO()
        with redirect_stdout(vu):
            self.todo._pve_collisions()
        return vu.getvalue()

    def test_a_collision_names_both_sides_and_the_remedy(self):
        """Nommer le seul VMID ne suffit pas : il faut dire ce que le plan y
        prévoyait ET ce qui l'occupe, sinon on cherche laquelle déplacer."""
        self.armer(
            C.lit_devis(DEVIS),
            (invite(AUTRE_DECLARE, "vieille-fictive", "Prod.Ancien"),),
        )
        vu = self.ecran()
        self.assertIn(str(AUTRE_DECLARE), vu)
        self.assertIn("backup-01", vu)
        self.assertIn("vieille-fictive", vu)
        self.assertIn(t("Change the fleet index and regenerate:"), vu)
        self.assertIn(t("Budget about two hours."), vu)

    def test_no_collision_says_how_many_were_checked(self):
        """« Aucune collision » sans portée se lit comme un contrôle qui
        n'a rien regardé."""
        self.armer(
            C.lit_devis(DEVIS), (invite(DECLARE, "infra-pki-01", POOL),)
        )
        vu = self.ecran()
        self.assertIn("2", vu)
        self.assertNotIn(t("Budget about two hours."), vu)

    def test_an_unreadable_side_gives_no_verdict_and_names_which(self):
        """Dire « aucune collision » sur un côté illisible rassurerait à
        tort, et c'est le verdict le plus cher à se tromper."""
        self.armer(C.lit_devis(DEVIS), None)
        vu = self.ecran()
        self.assertIn(t("the cluster VM list"), vu)
        self.assertNotIn(t("Budget about two hours."), vu)
        self.armer(None, (invite(142),))
        self.assertIn(t("the plan"), self.ecran())

    def test_without_the_engine_the_screen_says_there_is_nothing_to_compare(
        self,
    ):
        self.armer(None, None, armee=False)
        self.assertIn(
            t("Set-OPS is not set up here; nothing to compare."), self.ecran()
        )


class TestLeDeploiementDefensif(CasDeChoisisseur):
    """Créer une VM sur un VMID que le plan réclame coûte des heures."""

    def test_an_unreadable_plan_creates_nothing(self):
        """Choisir un VMID à l'aveugle est un PARI sur ce que la flotte ne
        réclamera pas ; perdu, il ne se répare pas en renommant."""
        import io as _io
        from contextlib import redirect_stdout

        self.todo._pve_reserves = lambda: (True, None)
        vu = _io.StringIO()
        with redirect_stdout(vu):
            self.todo._pve_dire_plan_illisible()
        self.assertIn(t("Nothing is created."), vu.getvalue())

    def test_the_reservations_come_from_the_plan(self):
        self.todo._pve_devis = lambda: (True, C.lit_devis(DEVIS))
        armee, reserves = self.todo._pve_reserves()
        self.assertTrue(armee)
        self.assertEqual({DECLARE, AUTRE_DECLARE}, set(reserves))

    def test_without_the_engine_nothing_is_reserved(self):
        self.todo._pve_devis = lambda: (False, None)
        self.assertEqual((False, frozenset()), self.todo._pve_reserves())

    def test_an_unreadable_plan_reserves_the_unknown_and_not_nothing(self):
        """« Rien de réservé » et « réserve inconnue » mènent à deux gestes
        opposés : créer, ou refuser."""
        self.todo._pve_devis = lambda: (True, None)
        self.assertEqual((True, None), self.todo._pve_reserves())


if __name__ == "__main__":
    unittest.main()
