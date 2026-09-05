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


class TestPasDeCaseTrompeuse(unittest.TestCase):
    """La case a été RETIRÉE, et c'est le correctif.

    L'interception est transparente et couvre tout le pont : une VM ne peut
    pas s'y soustraire. Décocher n'omettait que l'AUTORITÉ, si bien que la VM
    était détournée quand même et échouait sur « self-signed certificate in
    certificate chain » à chaque téléchargement HTTPS. Une case qui fabrique
    une machine cassée vaut moins que pas de case du tout.
    """

    def test_aucune_case_dans_les_deux_ecrans(self):
        for ecran in (QEMU_FORM, PROXMOX_FORM):
            self.assertNotIn(
                "f_cache",
                ecran.read_text(encoding="utf-8"),
                f"{ecran.name} offre une case qui casserait la VM décochée",
            )

    def test_lautorite_suit_le_service_et_non_une_case(self):
        src = QEMU_DEPLOY.read_text(encoding="utf-8")
        self.assertIn("_qemu_cache_active()", src)
        self.assertNotIn(
            'spec.get("use_cache")',
            src,
            "l'autorité dépend encore d'un choix qui ne peut pas être tenu",
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

    def parts(self, spec, ca="", actif=True):
        # « TODO.__new__ » sans __init__ : l'idiome des tests du dépôt, qui
        # donne toutes les méthodes du menu sans ouvrir d'écran.
        todo = TODO.__new__(TODO)
        # Ni l'autorité ni le service ne sont ceux de la machine de test : la
        # détection est remplacée, le reste du chemin reste intact.
        todo._qemu_cache_ca_path = lambda: ca
        todo._qemu_cache_active = lambda: actif and bool(ca)
        return todo._qemu_deploy_parts_for(self.vm(), spec, dry_run=True)

    def test_service_arrete_aucun_drapeau(self):
        """Sans interception, l'autorité n'a rien à faire dans la VM."""
        parts = self.parts({"install": None}, ca="/tmp/ca.crt", actif=False)
        self.assertNotIn("--cache-ca", parts)

    def test_service_actif_le_drapeau_et_le_chemin(self):
        """Le service tourne : la VM SERA détournée, donc elle doit approuver
        l'autorité, quoi qu'on ait coché."""
        parts = self.parts({"install": None}, ca="/tmp/essai-ca.crt")
        self.assertIn("--cache-ca", parts)
        self.assertEqual(
            parts[parts.index("--cache-ca") + 1],
            "/tmp/essai-ca.crt",
            "le chemin de l'autorité ne suit pas le drapeau",
        )

    def test_cache_disparu_entre_temps(self):
        """Le chemin est relu à CHAQUE commande : un cache désinstallé entre
        le formulaire et le déploiement ne doit pas faire approuver une
        autorité qui n'existe plus."""
        parts = self.parts({"install": None}, ca="")
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
