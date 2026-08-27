#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Combien d'étages de Proxmox tiennent, et avec quelles ressources.

L'écran de déploiement lisait la capacité de l'HÔTE et l'offrait en entier.
Sur un troisième étage à 14 cœurs et 9 Go de libre, il a proposé 12 vCPU et
9 Go à une VM qui n'a jamais démarré : même RIP à trois relevés deux minutes
d'écart, pas un octet lu de plus. Le nombre n'était pas absurde pour la
machine ; il l'était pour sa profondeur.
"""

import sys
import unittest

sys.argv = ["todo.py"]
from script.proxmox import nesting  # noqa: E402


class TestLePlanDesEtages(unittest.TestCase):
    """Deux ressources s'épuisent en descendant, et le plan doit le dire
    AVANT de créer quoi que ce soit."""

    # La machine réelle sur laquelle l'algorithme a été réglé.
    HOTE = dict(cpu_hote=28, ram_dispo_mo=29549, disque_libre_go=139)

    def test_ten_levels_fit_on_this_machine(self):
        plan = nesting.nesting_plan(10, **self.HOTE)
        self.assertEqual(plan["atteignable"], 10)
        self.assertEqual(plan["arret"], "")

    def test_every_level_shrinks(self):
        # Le disque de l'enfant vit DANS celui du parent, qui doit aussi
        # contenir son propre système : rien ne peut rester constant.
        niveaux = nesting.nesting_plan(6, **self.HOTE)["niveaux"]
        for precedent, suivant in zip(niveaux, niveaux[1:]):
            self.assertLess(suivant["ram"], precedent["ram"])
            self.assertLess(suivant["disque"], precedent["disque"])

    def test_the_first_level_may_be_wide_the_others_not(self):
        """12 vCPU au quatrième étage ont GELÉ le noyau invité en tout début
        de démarrage ; les mêmes 2 vCPU avançaient. Amener douze processeurs
        en ligne demande autant d'allers-retours à travers la pile."""
        niveaux = nesting.nesting_plan(4, **self.HOTE)["niveaux"]
        # STRICTEMENT plus grand. « > VCPU_IMBRIQUE - 1 » était satisfait par
        # la valeur imbriquée elle-même : remplacer tout le calcul du premier
        # étage par VCPU_IMBRIQUE laissait les tests verts, donc cpu_hote
        # n'était couvert par rien.
        self.assertGreater(niveaux[0]["vcpu"], nesting.VCPU_IMBRIQUE)
        for n in niveaux[1:]:
            self.assertEqual(n["vcpu"], nesting.VCPU_IMBRIQUE)

    def test_a_parent_is_never_narrower_than_its_child(self):
        """Sur un hôte de quatre cœurs, « // 4 » donnait UN vCPU au premier
        étage — l'hyperviseur — alors que son invité en recevait deux."""
        for coeurs in (2, 4, 8, 12, 28):
            with self.subTest(coeurs=coeurs):
                niveaux = nesting.nesting_plan(
                    3,
                    cpu_hote=coeurs,
                    ram_dispo_mo=32768,
                    disque_libre_go=300,
                )["niveaux"]
                self.assertGreaterEqual(
                    niveaux[0]["vcpu"], niveaux[1]["vcpu"], f"{coeurs} cœurs"
                )

    def test_running_out_of_ram_is_named(self):
        plan = nesting.nesting_plan(
            10, cpu_hote=8, ram_dispo_mo=12288, disque_libre_go=500
        )
        self.assertEqual(plan["arret"], "ram")
        self.assertLess(plan["atteignable"], 10)
        # Aucun étage sous le plancher : un Proxmox sous 2 Go ne démarre pas
        # ses démons.
        for n in plan["niveaux"]:
            self.assertGreaterEqual(n["ram"], nesting.RAM_MIN_MO)

    def test_running_out_of_disk_is_named(self):
        plan = nesting.nesting_plan(
            10, cpu_hote=8, ram_dispo_mo=200000, disque_libre_go=60
        )
        self.assertEqual(plan["arret"], "disque")
        for n in plan["niveaux"]:
            self.assertGreaterEqual(n["disque"], nesting.DISQUE_MIN_GO)

    def test_the_host_keeps_a_share_not_just_a_floor(self):
        """Quatre gigaoctets sur une machine de soixante, c'est 6 % laissés à
        l'hôte : le jour où les invités touchent vraiment leur mémoire, c'est
        lui qui part en swap — et la mesure serait celle du swap, pas de
        l'imbrication."""
        for dispo in (60000, 260000):
            with self.subTest(dispo=dispo):
                plan = nesting.nesting_plan(
                    1, cpu_hote=28, ram_dispo_mo=dispo, disque_libre_go=500
                )
                reserve = dispo - plan["niveaux"][0]["ram"]
                self.assertGreater(reserve, nesting.HOTE_RESERVE_RAM_MO)
                self.assertGreaterEqual(
                    reserve, dispo // nesting.HOTE_RESERVE_PART
                )

    def test_a_small_host_keeps_the_floor(self):
        # Sur une petite machine, la part serait dérisoire : le plancher tient.
        plan = nesting.nesting_plan(
            1, cpu_hote=4, ram_dispo_mo=16384, disque_libre_go=200
        )
        self.assertEqual(
            16384 - plan["niveaux"][0]["ram"], nesting.HOTE_RESERVE_RAM_MO
        )

    def test_a_depth_of_zero_asks_for_nothing(self):
        for profondeur in (0, -1, -7):
            with self.subTest(profondeur=profondeur):
                plan = nesting.nesting_plan(profondeur, **self.HOTE)
                self.assertEqual(plan["niveaux"], [])
                self.assertEqual(plan["atteignable"], 0)

    def test_a_machine_too_small_for_even_one_level(self):
        plan = nesting.nesting_plan(
            3, cpu_hote=2, ram_dispo_mo=4096, disque_libre_go=200
        )
        self.assertEqual(plan["atteignable"], 0)
        self.assertEqual(plan["niveaux"], [])
        self.assertEqual(plan["arret"], "ram")

    def test_a_plan_is_never_promised_beyond_what_fits(self):
        # Mieux vaut annoncer six étages et en réussir six que d'en promettre
        # dix et mourir au septième sans savoir pourquoi.
        # Depuis 0 et depuis les négatifs : « max(1, …) » forçait un tour,
        # donc « --depth 0 » rendait un plan d'UN étage et créait une VM.
        for profondeur in range(-2, 13):
            plan = nesting.nesting_plan(profondeur, **self.HOTE)
            self.assertEqual(len(plan["niveaux"]), plan["atteignable"])
            # « max(0, …) » : une demande négative ne peut pas donner un
            # nombre d'étages négatif, elle donne zéro.
            self.assertLessEqual(plan["atteignable"], max(0, profondeur))


class TestLaProfondeurDUnHote(unittest.TestCase):
    """Comptée depuis la chaîne de rebonds : c'est la seule mesure dont on
    dispose de l'extérieur, et elle est exacte pour les hôtes que nous avons
    nous-mêmes déployés — c'est nous qui écrivons ces entrées."""

    def test_no_jump_is_the_first_level(self):
        self.assertEqual(nesting.depth_from_jumps(0), 1)

    def test_each_jump_adds_a_level(self):
        for sauts, attendu in ((1, 2), (2, 3), (3, 4), (9, 10)):
            self.assertEqual(nesting.depth_from_jumps(sauts), attendu)


class TestCompterLesRebonds(unittest.TestCase):
    """La profondeur se lit dans ~/.ssh/config : un ProxyJump par étage.

    Hermétique — une configuration synthétique. La vraie a été nettoyée entre
    deux mesures, et un test qui dépend de la machine qui le lance ne prouve
    rien le lendemain."""

    CONFIG = """
Host niveau1
    HostName 192.168.1.10

Host niveau2
    HostName 10.10.10.150
    ProxyJump niveau1

Host niveau3
    HostName 10.10.20.150
    ProxyJump niveau2

Host niveau4
    HostName 10.10.10.150
    ProxyJump niveau3

Host boucle-a
    ProxyJump boucle-b

Host boucle-b
    ProxyJump boucle-a
"""

    def setUp(self):
        import os
        import tempfile

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        self.maison = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.maison, ".ssh"))
        with open(
            os.path.join(self.maison, ".ssh/config"), "w", encoding="utf-8"
        ) as fh:
            fh.write(self.CONFIG)
        self._vrai = os.environ.get("HOME")
        os.environ["HOME"] = self.maison
        self.TODO = TODO

    def tearDown(self):
        import os
        import shutil

        if self._vrai is not None:
            os.environ["HOME"] = self._vrai
        shutil.rmtree(self.maison, ignore_errors=True)

    def test_each_level_is_counted(self):
        for nom, attendu in (
            ("niveau1", 1),
            ("niveau2", 2),
            ("niveau3", 3),
            ("niveau4", 4),
        ):
            with self.subTest(hote=nom):
                sauts = self.TODO._ssh_jump_depth(nom)
                self.assertEqual(nesting.depth_from_jumps(sauts), attendu)

    def test_an_unknown_host_is_the_first_level(self):
        self.assertEqual(self.TODO._ssh_jump_depth("jamais-vu"), 0)

    def test_a_loop_does_not_spin_forever(self):
        # A rebondit par B qui rebondit par A : sans garde, le parcours ne
        # s'arrête jamais.
        self.assertLessEqual(self.TODO._ssh_jump_depth("boucle-a"), 2)


class TestBornerCeQueLEcranOffre(unittest.TestCase):
    def test_the_first_two_levels_are_left_alone(self):
        # L'imbrication à deux niveaux est documentée par les fabricants : on
        # n'a rien à corriger là.
        for profondeur in (1, 2):
            self.assertEqual(
                nesting.capped_for_depth(profondeur, 12, 9216),
                (12, 9216, ""),
            )

    def test_beyond_that_the_vcpu_is_capped_and_said(self):
        vcpu, ram, raison = nesting.capped_for_depth(3, 12, 9216)
        self.assertEqual(vcpu, nesting.VCPU_IMBRIQUE)
        self.assertTrue(raison)
        self.assertIn("12", raison)

    def test_the_ram_is_never_touched(self):
        """La même VM gelait au MÊME octet avec 9 Go et avec 2 Go : la
        mémoire n'est pas le levier. La rogner ne gagnerait rien et priverait
        l'étage suivant."""
        for profondeur in (1, 3, 8):
            _v, ram, _r = nesting.capped_for_depth(profondeur, 12, 9216)
            self.assertEqual(ram, 9216)

    def test_a_modest_request_is_not_reported_as_capped(self):
        # Rien n'a bougé : ne rien dire. Un avertissement à chaque
        # déploiement finit par ne plus être lu.
        self.assertEqual(nesting.capped_for_depth(5, 2, 4096), (2, 4096, ""))
        self.assertEqual(nesting.capped_for_depth(5, 1, 4096), (1, 4096, ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
