#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La case « cache » du formulaire QEMU, et ce qu'elle change à la commande.

Trois propriétés, chacune pour une panne :

  1. la case n'est offerte que si l'hôte porte l'autorité du cache — une case
     sans effet possible est une question à laquelle rien ne répond ;
  2. le drapeau `--cache-ca` n'apparaît QUE si elle est cochée, et le chemin
     est relu à chaque commande : désinstaller le cache entre deux
     déploiements ne doit pas laisser une VM approuver une autorité disparue ;
  3. le chemin de l'autorité est le MÊME que celui où l'installateur la pose.
     Les deux séparés, la case s'offrirait sans que la VM reçoive quoi que ce
     soit — et rien ne le dirait.

L'écran Proxmox n'a pas cette case, et c'est voulu : sa VM naît sur un hôte
distant, que le cache local ne sert pas.
"""

import re
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

QEMU_FORM = RACINE / "script" / "todo" / "qemu_deploy_form.py"
PROXMOX_FORM = RACINE / "script" / "todo" / "proxmox_deploy_form.py"
QEMU_DEPLOY = RACINE / "script" / "todo" / "qemu_deploy.py"
INSTALLATEUR = RACINE / "script" / "install" / "install_qemu_cache.sh"

from script.todo.qemu_deploy import QemuDeployMixin  # noqa: E402
from script.todo.todo import TODO  # noqa: E402


class TestOffreDeLaCase(unittest.TestCase):
    def setUp(self):
        self.source = QEMU_FORM.read_text(encoding="utf-8")

    def test_case_conditionnee_a_lautorite(self):
        self.assertRegex(
            self.source,
            r'if ctx\.get\("cache_ca"\):\s*\n\s*yield Checkbox\(',
            "la case s'affiche sans vérifier que l'hôte a un cache",
        )

    def test_defaut_suit_letat_du_service(self):
        self.assertIn('value=bool(ctx.get("cache_active"))', self.source)

    def test_lecture_gardee_du_widget(self):
        """La case n'existe pas sur un hôte sans cache : la lire sans garde
        casserait l'écran au moment de valider."""
        self.assertIn(
            'getattr(self._widget("#f_cache"), "value", False)', self.source
        )

    def test_ecran_proxmox_epargne(self):
        """Une VM Proxmox naît ailleurs : le cache local ne peut pas la
        servir, et lui offrir la case promettrait un gain inexistant."""
        self.assertNotIn(
            "f_cache",
            PROXMOX_FORM.read_text(encoding="utf-8"),
            "l'écran Proxmox offre une case que son hôte distant ignore",
        )


class TestCommandeProduite(unittest.TestCase):
    """Le drapeau passe par le POINT DE PASSAGE UNIQUE des deux interfaces."""

    def vm(self):
        return {
            "distro": "arch",
            "version": "latest",
            "arch": "amd64",
            "name": "essai",
            "ram": 4096,
            "vcpus": 2,
            "disk": "20G",
        }

    def parts(self, spec, ca=""):
        # « TODO.__new__ » sans __init__ : l'idiome des tests du dépôt, qui
        # donne toutes les méthodes du menu sans ouvrir d'écran.
        todo = TODO.__new__(TODO)
        # L'autorité n'est pas celle de la machine de test : la détection est
        # remplacée, ce qui laisse le reste du chemin intact.
        todo._qemu_cache_ca_path = lambda: ca
        return todo._qemu_deploy_parts_for(self.vm(), spec, dry_run=True)

    def test_sans_la_case_aucun_drapeau(self):
        parts = self.parts({"install": None}, ca="/tmp/ca.crt")
        self.assertNotIn("--cache-ca", parts)

    def test_avec_la_case_le_drapeau_et_le_chemin(self):
        parts = self.parts(
            {"install": None, "use_cache": True}, ca="/tmp/essai-ca.crt"
        )
        self.assertIn("--cache-ca", parts)
        self.assertEqual(
            parts[parts.index("--cache-ca") + 1],
            "/tmp/essai-ca.crt",
            "le chemin de l'autorité ne suit pas le drapeau",
        )

    def test_case_cochee_mais_cache_disparu(self):
        """Le chemin est relu à CHAQUE commande : un cache désinstallé entre
        le formulaire et le déploiement ne doit pas faire approuver une
        autorité qui n'existe plus."""
        parts = self.parts({"install": None, "use_cache": True}, ca="")
        self.assertNotIn("--cache-ca", parts)


class TestAccordAvecLInstallateur(unittest.TestCase):
    def test_meme_chemin_dautorite(self):
        """`EL_CA_DIR` du script et `QEMU_CACHE_CA` du menu doivent désigner
        le même fichier."""
        texte = INSTALLATEUR.read_text(encoding="utf-8")
        m = re.search(r'EL_CA_DIR="\$\{EL_CA_DIR:-([^}]+)\}"', texte)
        self.assertIsNotNone(m, "EL_CA_DIR introuvable dans l'installateur")
        attendu = f"{m.group(1)}/ca.crt"
        self.assertEqual(
            QemuDeployMixin.QEMU_CACHE_CA,
            attendu,
            "le menu cherche l'autorité là où l'installateur ne la pose pas",
        )

    def test_meme_nom_de_service(self):
        texte = INSTALLATEUR.read_text(encoding="utf-8")
        m = re.search(r"UNIT=\"/etc/systemd/system/([^\"]+)\"", texte)
        self.assertIsNotNone(m, "le nom de l'unité est introuvable")
        self.assertEqual(
            QemuDeployMixin.QEMU_CACHE_SERVICE,
            m.group(1),
            "le menu interroge un service que l'installateur ne pose pas",
        )


class TestDetectionHote(unittest.TestCase):
    def test_pas_dautorite_pas_de_chemin(self):
        class Absent(QemuDeployMixin):
            QEMU_CACHE_CA = "/inexistant/ca.crt"

        self.assertEqual(Absent._qemu_cache_ca_path(), "")
        self.assertFalse(
            Absent._qemu_cache_active(),
            "un service est déclaré actif alors qu'aucune autorité n'existe",
        )


if __name__ == "__main__":
    unittest.main()
