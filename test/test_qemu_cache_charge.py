#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce que le test long télécharge, et sur quel système.

Trois axes désormais : l'essai (cache, contre-épreuve, témoin), la charge
(un lot de paquets ou l'installation réelle) et la distribution. Chacun a sa
façon de se tromper en silence.

La charge doit être IDENTIQUE d'une VM à l'autre, sans quoi la comparaison ne
compare rien. Elle doit aussi correspondre à la famille de la distribution :
un nom de paquet d'une autre famille fait échouer l'installation loin de sa
cause, après le déploiement d'une machine entière.

Et le catalogue des systèmes n'est PAS recopié : il vient du déploiement. Une
seconde table proposerait un système que le déploiement ne sait pas installer,
ce que l'on ne découvrirait qu'en le lançant.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))


def charger():
    chemin = RACINE / "long_test" / "qemu_cache.py"
    spec = importlib.util.spec_from_file_location("qemu_cache_long", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


QC = charger()


class TestLeCatalogueVientDuDeploiement(unittest.TestCase):
    def test_aucun_systeme_inconnu_du_deploiement(self):
        from script.qemu.deploy_qemu import DISTROS

        for d in QC.systemes_mesurables():
            self.assertIn(
                d, DISTROS, f"« {d} » n'est pas au catalogue du déploiement"
            )

    def test_chaque_systeme_a_une_famille_servie(self):
        """Proposer un système dont on ne sait pas installer les paquets, c'est
        déployer une VM entière pour échouer à la dernière étape."""
        for d in QC.systemes_mesurables():
            self.assertIn(
                QC.famille_de(d),
                QC.PAQUETS_MINIMUM,
                f"« {d} » n'a pas de lot de paquets",
            )

    def test_proxmox_est_ecarte(self):
        """Un hyperviseur : on n'y installe ni ERPLibre ni un lot de
        développement, et le déploiement lui impose déjà son profil."""
        self.assertNotIn("proxmox", QC.systemes_mesurables())

    def test_les_quatre_familles_sont_couvertes(self):
        self.assertEqual(
            set(QC.PAQUETS_MINIMUM), {"pacman", "apt", "dnf", "zypper"}
        )


class TestLaCharge(unittest.TestCase):
    def test_chaque_famille_rend_une_commande(self):
        for d in sorted(QC.systemes_mesurables()):
            self.assertTrue(
                QC.commande_de_charge(d, "minimum"),
                f"aucune charge minimale pour « {d} »",
            )

    def test_un_systeme_hors_catalogue_ne_rend_rien(self):
        """Rendre une commande vide plutôt qu'une commande fausse : le test
        s'arrête en le disant, au lieu de lancer un shell vide dans la VM."""
        self.assertEqual(QC.commande_de_charge("haiku", "minimum"), "")

    def test_la_charge_reelle_contient_la_minimale(self):
        """Elles partagent leur début, ce qui rend leurs mesures comparables
        sur cette portion — et « make » n'existe pas avant que git l'ait
        cloné."""
        for d in sorted(QC.systemes_mesurables()):
            minimum = QC.commande_de_charge(d, "minimum")
            reelle = QC.commande_de_charge(d, "erplibre")
            self.assertTrue(
                reelle.startswith(minimum),
                f"« {d} » : la charge réelle ne part pas de la minimale",
            )

    def test_la_charge_reelle_clone_puis_installe(self):
        cmd = QC.commande_de_charge("arch", "erplibre")
        self.assertIn("git clone", cmd)
        self.assertIn("install_odoo_18", cmd)
        self.assertLess(
            cmd.index("git clone"),
            cmd.index("install_odoo_18"),
            "la cible make est lancée avant que le dépôt existe",
        )

    def test_chaque_charge_a_son_delai(self):
        """Un délai unique ferait échouer la courte ou laisserait la longue
        pendre : ERPLibre se compte en heures, le lot en minutes."""
        self.assertEqual(set(QC.DELAI_CHARGE), {"minimum", "erplibre"})
        self.assertGreater(
            QC.DELAI_CHARGE["erplibre"], QC.DELAI_CHARGE["minimum"]
        )

    def test_le_plan_a_blanc_montre_la_commande_exacte(self):
        """Un plan qui montre autre chose que ce qui sera lancé n'est pas un
        plan."""
        from unittest import mock

        with mock.patch.object(QC, "dire") as dit:
            QC.poser_les_paquets(
                "10.0.0.1",
                None,
                dry_run=True,
                distro="debian",
                charge="erplibre",
            )
        annonce = " ".join(str(a) for c in dit.call_args_list for a in c.args)
        self.assertIn(QC.commande_de_charge("debian", "erplibre"), annonce)


class TestLesOptions(unittest.TestCase):
    def test_la_version_vide_vient_du_catalogue(self):
        from script.qemu.deploy_qemu import DISTROS

        for d in sorted(QC.systemes_mesurables()):
            defaut = DISTROS[d][1]
            self.assertTrue(
                defaut, f"« {d} » n'a pas de version par défaut au catalogue"
            )


if __name__ == "__main__":
    unittest.main()
