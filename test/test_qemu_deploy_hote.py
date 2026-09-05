#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce qu'une VM reçoit de l'hôte : son nom d'hôte et son fuseau.

Deux réglages que cloud-init applique au premier démarrage, et qui échouent
tous les deux SANS arrêter le déploiement. La VM démarre, sshd répond, tout a
l'air d'aller — et l'on découvre après coup qu'elle porte le nom générique de
son image, ou qu'elle horodate en UTC pendant que le reste du dépôt est en
heure locale.

Le nom d'hôte n'accepte ni souligné ni point d'exclamation, là où un nom de
domaine libvirt les tolère : les deux ne se ressemblent qu'en général, et un
nom de VM lisible peut donc être un nom d'hôte invalide.

Le fuseau, lui, doit exister DANS L'INVITÉ. Un alias hérité peut vivre sur
l'hôte et manquer à la VM, plusieurs distributions récentes ayant relégué ces
alias à un paquet séparé.
"""

import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from script.qemu.deploy_qemu import (  # noqa: E402
    canonical_timezone,
    hostname_valide,
)


class TestNomDHote(unittest.TestCase):
    def test_le_souligne_devient_un_tiret(self):
        """Le nom des VM du test long en porte : « el-cache-ubuntu_2404-… »."""
        self.assertEqual(
            hostname_valide("el-cache-ubuntu_2404-erplibre_odoo_18-1"),
            "el-cache-ubuntu-2404-erplibre-odoo-18-1",
        )

    def test_un_nom_deja_valide_ne_bouge_pas(self):
        self.assertEqual(hostname_valide("erplibre-arch"), "erplibre-arch")

    def test_les_tirets_de_bord_tombent(self):
        """Un nom d'hôte ne peut ni commencer ni finir par un tiret."""
        self.assertEqual(hostname_valide("_vm_"), "vm")
        self.assertEqual(hostname_valide("--essai--"), "essai")

    def test_les_tirets_ne_sattroupent_pas(self):
        self.assertEqual(hostname_valide("a__.__b"), "a-b")

    def test_un_nom_vide_a_un_repli(self):
        """Rendre du vide ferait refuser le nom par l'invité, sans que rien
        d'autre qu'un avertissement ne le dise."""
        for entree in ("", "___", "..."):
            self.assertEqual(hostname_valide(entree), "vm")

    def test_le_nom_est_borne(self):
        """Une étiquette de nom d'hôte tient en 63 octets."""
        self.assertEqual(len(hostname_valide("x" * 200)), 63)


class TestFuseau(unittest.TestCase):
    def table(self, lignes):
        f = tempfile.NamedTemporaryFile(
            "w", suffix=".zi", delete=False, encoding="utf-8"
        )
        f.write("\n".join(lignes) + "\n")
        f.close()
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        return f.name

    def test_un_alias_herite_est_traduit(self):
        """Un fuseau que l'invité refuse fait marquer l'exécution de
        cloud-init en erreur, et la VM reste en UTC."""
        table = self.table(
            ["# commentaire", "L America/Toronto Canada/Eastern", "Z autre"]
        )
        self.assertEqual(
            canonical_timezone("Canada/Eastern", table), "America/Toronto"
        )

    def test_un_nom_canonique_ne_bouge_pas(self):
        table = self.table(["L America/Toronto Canada/Eastern"])
        self.assertEqual(
            canonical_timezone("America/Toronto", table), "America/Toronto"
        )

    def test_une_table_absente_rend_le_nom_tel_quel(self):
        """Un fuseau non traduit vaut mieux qu'un déploiement refusé."""
        self.assertEqual(
            canonical_timezone("Canada/Eastern", "/nexiste/pas.zi"),
            "Canada/Eastern",
        )

    def test_le_vide_reste_vide(self):
        self.assertEqual(canonical_timezone("", "/nexiste/pas.zi"), "")

    def test_seules_les_lignes_de_lien_comptent(self):
        """« Z » ouvre une zone, « R » une règle : les confondre traduirait un
        fuseau en n'importe quoi."""
        table = self.table(
            ["Z Canada/Eastern -5:00 Canada E%sT", "R Canada 1974 ma"]
        )
        self.assertEqual(
            canonical_timezone("Canada/Eastern", table), "Canada/Eastern"
        )


if __name__ == "__main__":
    unittest.main()
