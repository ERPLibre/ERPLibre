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
    """Le plan se dimensionne DEPUIS LE BAS, et c'est une correction.

    De haut en bas, chaque étage recevait ce que son parent pouvait céder.
    Mesuré sur une descente réelle : l'étage 4 se retrouvait avec 44 Go de RAM
    et deux vCPU sur un hôte qui en avait deux — cent pour cent de
    surengagement, à chaque étage. Son installation dépassait deux heures et
    demie contre treize minutes pour l'étage 3, et l'extrapolation donnait cinq
    ANS pour le dixième.

    Le plus profond reçoit donc ce qu'un Proxmox de test demande, et chaque
    parent ajoute son propre surcoût — un vCPU, deux gibioctets, dix
    gigaoctets. Rien de plus."""

    # La machine réelle sur laquelle l'algorithme a été réglé.
    HOTE = dict(cpu_hote=28, ram_dispo_mo=58000, disque_libre_go=165)

    def test_ten_levels_fit_on_this_machine(self):
        plan = nesting.nesting_plan(10, **self.HOTE)
        self.assertEqual(plan["atteignable"], 10)
        self.assertEqual(plan["arret"], "")

    def test_the_deepest_level_gets_exactly_the_target(self):
        """C'est de là qu'on part : ce qu'un Proxmox de test demande, pas ce
        qui reste."""
        plan = nesting.nesting_plan(10, **self.HOTE)
        fond = plan["niveaux"][-1]
        self.assertEqual(fond["ram"], nesting.PVE_RAM_CIBLE_MO)
        self.assertEqual(fond["disque"], nesting.PVE_DISQUE_CIBLE_GO)
        self.assertEqual(fond["vcpu"], nesting.VCPU_IMBRIQUE)

    def test_each_parent_adds_exactly_its_own_overhead(self):
        # Ni plus ni moins : un parent plus large que nécessaire ralentit tout
        # ce qu'il héberge, un parent trop juste ne le fait pas tourner. Vaut
        # pour la mémoire et le disque — le processeur, lui, ne croît pas avec
        # la profondeur, voir test_no_nested_level_is_ever_wide.
        niveaux = nesting.nesting_plan(8, **self.HOTE)["niveaux"]
        for parent, enfant in zip(niveaux, niveaux[1:]):
            self.assertEqual(parent["ram"] - enfant["ram"], nesting.PVE_RAM_MO)
            self.assertEqual(
                parent["disque"] - enfant["disque"], nesting.PVE_DISQUE_GO
            )

    def test_no_nested_level_is_ever_wide(self):
        """MESURÉ, deux fois : au quatrième étage un invité large GÈLE.

        Douze vCPU d'abord, sur un parent qui en avait deux : on avait imputé
        le gel au surengagement. Puis huit vCPU sur un parent qui en avait
        NEUF, charge 1,47, aucun surengagement — 32 Mio lus en 106 minutes,
        même RIP à trois relevés espacés de cinq minutes. C'est le nombre de
        vCPU de l'invité imbriqué, et rien d'autre.

        Une version de ce module donnait un vCPU de plus à chaque parent, ce
        qui rendait l'étage 4 large de huit : exactement le cas gelé. Aucun
        étage imbriqué ne doit dépasser VCPU_INTERMEDIAIRE, à AUCUNE
        profondeur demandée."""
        for profondeur in range(1, 13):
            niveaux = nesting.nesting_plan(profondeur, **self.HOTE)["niveaux"]
            for n in niveaux[1:]:
                self.assertLessEqual(
                    n["vcpu"],
                    nesting.VCPU_INTERMEDIAIRE,
                    f"profondeur {profondeur}, étage {n['niveau']}",
                )

    def test_the_three_widths_are_where_they_belong(self):
        """Le coût d'un vCPU dépend de la PROFONDEUR de l'étage, pas d'une
        largeur absolue.

        Mesuré : le troisième vCPU ne coûte rien aux étages 2 et 3 — ssh en
        37 s et 93 s, comme à deux vCPU — et coûte 4 h 20 au quatrième, contre
        1 664 s à deux. Un seul vCPU de plus, l'amorçage ×9,4."""
        niveaux = nesting.nesting_plan(6, **self.HOTE)["niveaux"]
        largeurs = {n["niveau"]: n["vcpu"] for n in niveaux}
        # Le métal : aucun risque de gel, onze vCPU y ont démarré en 42 s.
        self.assertEqual(largeurs[1], nesting.VCPU_METAL)
        # Peu profonds : le troisième vCPU est gratuit, et il enlève le
        # surengagement là où l'installation s'effondrait.
        for niveau in range(2, nesting.SEUIL_ETROIT):
            self.assertEqual(
                largeurs[niveau], nesting.VCPU_INTERMEDIAIRE, f"étage {niveau}"
            )
        # À partir du seuil : le strict minimum, sans exception.
        for niveau in range(nesting.SEUIL_ETROIT, 7):
            self.assertEqual(
                largeurs[niveau], nesting.VCPU_IMBRIQUE, f"étage {niveau}"
            )

    def test_the_level_above_the_threshold_keeps_its_headroom(self):
        """C'est le seul endroit de la descente où le surengagement disparaît,
        et c'est celui qui compte : l'étage 4 est le premier dont
        l'installation s'effondrait, faute d'un parent plus large que lui.

        Les deux combinaisons mesurées étaient (parent 2, enfant 2) — démarre
        en 1 664 s puis l'installation ne finit pas — et (parent 3, enfant 3) —
        démarre en 15 608 s. Celle-ci est (parent 3, enfant 2)."""
        niveaux = nesting.nesting_plan(6, **self.HOTE)["niveaux"]
        largeurs = {n["niveau"]: n["vcpu"] for n in niveaux}
        parent = largeurs[nesting.SEUIL_ETROIT - 1]
        enfant = largeurs[nesting.SEUIL_ETROIT]
        self.assertGreater(parent, enfant)

    def test_a_single_level_descent_runs_on_metal(self):
        niveaux = nesting.nesting_plan(1, **self.HOTE)["niveaux"]
        self.assertEqual(len(niveaux), 1)
        self.assertEqual(niveaux[0]["vcpu"], nesting.VCPU_METAL)

    def test_a_parent_is_never_narrower_than_its_child(self):
        """Deux vCPU hébergeant deux vCPU, c'est cent pour cent de
        surengagement — et l'hyperviseur à servir en plus. Mesuré : une VM
        démarrée au quatrième étage a lu DEUX KILO-OCTETS en onze minutes,
        affamée par l'installation qui tournait à côté. L'installation de
        l'étage 4 dépassait alors 2 h 50 contre 793 s pour l'étage 3.

        « Jamais plus étroit », et non « toujours plus large » : deux étages
        imbriqués voisins ont la même largeur, ce que le gel du quatrième
        étage impose. C'est le PLUS PROFOND qui descend à deux."""
        for coeurs in (6, 8, 12, 28):
            with self.subTest(coeurs=coeurs):
                niveaux = nesting.nesting_plan(
                    6,
                    cpu_hote=coeurs,
                    ram_dispo_mo=64000,
                    disque_libre_go=400,
                )["niveaux"]
                for parent, enfant in zip(niveaux, niveaux[1:]):
                    self.assertGreaterEqual(parent["vcpu"], enfant["vcpu"])
                    self.assertGreater(parent["ram"], enfant["ram"])
                    self.assertGreater(parent["disque"], enfant["disque"])

    def test_the_cpu_only_ever_refuses_outright(self):
        """Le processeur ne borne plus une profondeur INTERMÉDIAIRE : les
        étages imbriqués gardent une largeur fixe, seul le premier compte sur
        le métal. Ou la machine peut le porter, ou elle ne peut rien.

        Une version d'avant faisait croître la demande avec la profondeur —
        onze vCPU pour dix étages — et bornait donc à trois étages sur huit
        cœurs. Elle rendait aussi le quatrième étage large de huit, ce qui le
        gelait : la borne cachait un défaut."""
        large = nesting.nesting_plan(
            10, cpu_hote=8, ram_dispo_mo=64000, disque_libre_go=400
        )
        self.assertEqual(large["atteignable"], 10)
        self.assertEqual(large["arret"], "")
        # Trop petite pour le premier étage : zéro, et le dire.
        for coeurs in (1, 2, 4):
            with self.subTest(coeurs=coeurs):
                petite = nesting.nesting_plan(
                    10,
                    cpu_hote=coeurs,
                    ram_dispo_mo=64000,
                    disque_libre_go=400,
                )
                self.assertEqual(petite["atteignable"], 0)
                self.assertEqual(petite["arret"], "vcpu")
        # Et le premier étage laisse à l'hôte ce qui lui est réservé.
        self.assertLessEqual(
            large["niveaux"][0]["vcpu"], 8 - nesting.HOTE_RESERVE_VCPU
        )

    def test_the_named_resource_is_the_one_that_really_binds(self):
        """La version d'avant prenait la première d'une chaîne figée
        ram > disque > vcpu, évaluée à la profondeur DEMANDÉE. Sur deux cœurs
        et 20 Go elle annonçait « manque de ram » quand le processeur bornait à
        zéro étage : l'opérateur doublait la mémoire et n'y gagnait rien."""
        for cpu, ram, disque, attendu in (
            (2, 20000, 5000, "vcpu"),
            (2, 200000, 100, "vcpu"),
            (4, 16384, 200, "vcpu"),
            (28, 12288, 500, "ram"),
            (28, 200000, 60, "disque"),
        ):
            with self.subTest(cpu=cpu, ram=ram, disque=disque):
                plan = nesting.nesting_plan(10, cpu, ram, disque)
                self.assertEqual(plan["arret"], attendu)
                # Et c'est bien le plus BAS des trois plafonds.
                self.assertEqual(
                    plan["plafonds"][attendu], min(plan["plafonds"].values())
                )
                self.assertEqual(
                    plan["atteignable"], min(10, *plan["plafonds"].values())
                )

    def test_doubling_the_named_resource_gains_a_level(self):
        """L'épreuve utile du diagnostic : ce qu'il nomme, ajouté, PAIE."""
        base = dict(cpu_hote=28, ram_dispo_mo=12288, disque_libre_go=500)
        avant = nesting.nesting_plan(10, **base)
        self.assertEqual(avant["arret"], "ram")
        apres = nesting.nesting_plan(
            10, **{**base, "ram_dispo_mo": base["ram_dispo_mo"] * 2}
        )
        self.assertGreater(apres["atteignable"], avant["atteignable"])

    def test_a_huge_depth_costs_nothing(self):
        # Le balayage décroissant tournait autant de tours que la profondeur
        # demandée pour rendre exactement le même plan.
        plan = nesting.nesting_plan(10**6, 28, 58000, 165)
        self.assertEqual(plan["atteignable"], min(plan["plafonds"].values()))
        self.assertEqual(len(plan["niveaux"]), plan["atteignable"])

    def test_running_out_of_ram_is_named(self):
        plan = nesting.nesting_plan(
            10, cpu_hote=28, ram_dispo_mo=12288, disque_libre_go=500
        )
        self.assertEqual(plan["arret"], "ram")
        self.assertLess(plan["atteignable"], 10)
        for n in plan["niveaux"]:
            self.assertGreaterEqual(n["ram"], nesting.RAM_MIN_MO)

    def test_running_out_of_disk_is_named(self):
        plan = nesting.nesting_plan(
            10, cpu_hote=28, ram_dispo_mo=200000, disque_libre_go=60
        )
        self.assertEqual(plan["arret"], "disque")
        for n in plan["niveaux"]:
            self.assertGreaterEqual(n["disque"], nesting.DISQUE_MIN_GO)

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
        self.assertTrue(plan["arret"])

    def test_a_plan_is_never_promised_beyond_what_fits(self):
        # Mieux vaut annoncer six étages et en réussir six que d'en promettre
        # dix et mourir au septième sans savoir pourquoi.
        for profondeur in range(-2, 13):
            plan = nesting.nesting_plan(profondeur, **self.HOTE)
            self.assertEqual(len(plan["niveaux"]), plan["atteignable"])
            self.assertLessEqual(plan["atteignable"], max(0, profondeur))


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
