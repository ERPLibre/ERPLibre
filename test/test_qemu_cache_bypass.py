#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Soustraire UNE VM au cache : l'exception par adresse MAC.

Le détournement est transparent et vaut pour tout le pont. Une VM ne peut pas
s'y soustraire de l'intérieur, et lui retirer l'autorité ne la dispense de
rien : elle est interceptée quand même et échoue sur un certificat qu'elle ne
reconnaît pas. L'exception se pose donc sur l'HÔTE, et elle a besoin d'un
identifiant que la VM porte de façon stable.

D'où ce que ces tests tiennent. L'adresse MAC est choisie AVANT la création :
la lire après laisserait la fenêtre où cloud-init télécharge déjà. Une MAC
posée à la main l'emporte sur le tirage. Et l'exception l'emporte sur
l'autorité, qu'il serait absurde de faire approuver à une VM qui ne
rencontrera jamais le cache.
"""

import argparse
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from script.qemu import deploy_qemu  # noqa: E402


class FauxRunner:
    """Retient les commandes. Rend ce qu'on lui a dit de rendre."""

    def __init__(self, reponses=None):
        self.commandes = []
        self.reponses = reponses or {}
        self.use_sudo = True
        self.dry_run = False

    def run(self, cmd, *, privileged=False, check=True, capture=False):
        self.commandes.append(list(cmd))
        for motif, reponse in self.reponses.items():
            if motif in " ".join(cmd):
                return reponse
        return (0, "") if capture else None


def args_neufs(**kw):
    base = dict(
        name="vm-essai",
        network="network=default,model=virtio",
        cache_bypass=True,
        cache_ca="",
        distro="arch",
        dry_run=False,
    )
    base.update(kw)
    return argparse.Namespace(**base)


class TestLaMACChoisie(unittest.TestCase):
    def test_une_mac_deja_demandee_lemporte(self):
        """Une MAC posée à la main sert une réservation DHCP : la remplacer
        casserait ce que l'appelant a réglé ailleurs."""
        reseau = "network=default,model=virtio,mac=52:54:00:de:ad:be"
        self.assertEqual(
            deploy_qemu.mac_du_network(reseau), "52:54:00:de:ad:be"
        )
        self.assertEqual(
            deploy_qemu.network_avec_mac(reseau, "52:54:00:11:11:11"), reseau
        )

    def test_sans_mac_elle_est_ajoutee(self):
        reseau = deploy_qemu.network_avec_mac(
            "network=default,model=virtio", "52:54:00:11:22:33"
        )
        self.assertEqual(
            reseau, "network=default,model=virtio,mac=52:54:00:11:22:33"
        )
        self.assertEqual(
            deploy_qemu.mac_du_network(reseau), "52:54:00:11:22:33"
        )

    def test_la_mac_tiree_porte_le_prefixe_qemu(self):
        mac = deploy_qemu.mac_neuve(set())
        self.assertTrue(
            mac.startswith(deploy_qemu.MAC_PREFIXE),
            f"{mac} n'est pas une adresse QEMU",
        )
        self.assertEqual(len(mac.split(":")), 6)

    def test_une_mac_prise_nest_pas_retiree(self):
        """Libvirt refuse un doublon, mais à la création — après le
        téléchargement de l'image. Le refus doit venir avant."""
        prises = set()
        for _ in range(30):
            mac = deploy_qemu.mac_neuve(prises)
            self.assertNotIn(mac, prises)
            prises.add(mac)


class TestLExceptionEstPoseeAvant(unittest.TestCase):
    def test_la_mac_entre_dans_le_reseau_avant_la_creation(self):
        args = args_neufs()
        runner = FauxRunner({"is-active": (0, "")})
        with mock.patch.object(
            deploy_qemu.os.path, "isfile", return_value=True
        ), mock.patch.object(
            deploy_qemu.shutil, "which", return_value="/usr/bin/nft"
        ), mock.patch.object(
            deploy_qemu, "macs_deja_prises", return_value=set()
        ):
            mac = deploy_qemu.cache_bypass_apply(args, runner)
        self.assertTrue(mac, "aucune MAC retenue")
        self.assertIn(f"mac={mac}", args.network)
        pose = [c for c in runner.commandes if "--bypass-add" in " ".join(c)]
        self.assertTrue(pose, "l'exception n'a pas été posée")
        self.assertIn("nft -f -", " ".join(pose[0]))

    def test_sans_cache_installe_rien_nest_pose(self):
        """Exiger un cache pour pouvoir s'en passer n'aurait aucun sens :
        sans lui, rien n'intercepte."""
        args = args_neufs()
        runner = FauxRunner()
        with mock.patch.object(
            deploy_qemu.os.path, "isfile", return_value=False
        ):
            self.assertEqual(deploy_qemu.cache_bypass_apply(args, runner), "")
        self.assertEqual(runner.commandes, [])
        self.assertNotIn("mac=", args.network)

    def test_service_arrete_rien_nest_pose(self):
        args = args_neufs()
        runner = FauxRunner({"is-active": (3, "")})
        with mock.patch.object(
            deploy_qemu.os.path, "isfile", return_value=True
        ):
            self.assertEqual(deploy_qemu.cache_bypass_apply(args, runner), "")
        self.assertNotIn("mac=", args.network)

    def test_sans_la_demande_rien_ne_bouge(self):
        args = args_neufs(cache_bypass=False)
        runner = FauxRunner()
        self.assertEqual(deploy_qemu.cache_bypass_apply(args, runner), "")
        self.assertEqual(runner.commandes, [])

    def test_sans_nft_le_service_est_repose(self):
        """iptables n'a pas d'ensemble nommé : l'exception n'entre qu'en
        reposant la chaîne, et seul un redémarrage la repose."""
        args = args_neufs()
        runner = FauxRunner({"is-active": (0, "")})
        with mock.patch.object(
            deploy_qemu.os.path, "isfile", return_value=True
        ), mock.patch.object(
            deploy_qemu.shutil, "which", return_value=None
        ), mock.patch.object(
            deploy_qemu, "macs_deja_prises", return_value=set()
        ):
            deploy_qemu.cache_bypass_apply(args, runner)
        dit = [" ".join(c) for c in runner.commandes]
        self.assertTrue(
            any("systemctl" in c and "restart" in c for c in dit),
            f"le service n'est pas reposé : {dit}",
        )


class TestLExceptionLemporteSurLAutorite(unittest.TestCase):
    def test_pas_dautorite_dans_une_vm_exceptee(self):
        """Elle ne rencontrera jamais le cache : poser cette signature dans
        son magasin n'aurait aucun objet."""
        args = args_neufs(cache_ca="/var/lib/erplibre_go_qemu_cache/ca.crt")
        self.assertEqual(deploy_qemu.cache_files(args), [])

    def test_la_ligne_de_commande_ne_porte_pas_les_deux(self):
        from script.todo.qemu_deploy import QemuDeployMixin

        parts = QemuDeployMixin._qemu_build_deploy_parts(
            mock.MagicMock(_qemu_script_path=lambda: "deploy_qemu.py"),
            "arch",
            "latest",
            "x86_64",
            "vm",
            4096,
            2,
            "20G",
            "",
            "master",
            True,
            cache_ca="/var/lib/erplibre_go_qemu_cache/ca.crt",
            cache_bypass=True,
        )
        self.assertIn("--cache-bypass", parts)
        self.assertNotIn("--cache-ca", parts)

    def test_sans_exception_lautorite_passe(self):
        """Le cas courant : la VM approuve l'autorité et traverse le cache."""
        from script.todo.qemu_deploy import QemuDeployMixin

        parts = QemuDeployMixin._qemu_build_deploy_parts(
            mock.MagicMock(_qemu_script_path=lambda: "deploy_qemu.py"),
            "arch",
            "latest",
            "x86_64",
            "vm",
            4096,
            2,
            "20G",
            "",
            "master",
            True,
            cache_ca="/var/lib/erplibre_go_qemu_cache/ca.crt",
        )
        self.assertIn("--cache-ca", parts)
        self.assertNotIn("--cache-bypass", parts)


class TestLeMenageDesExceptions(unittest.TestCase):
    """Une exception qui survit à sa VM est le danger de cette liste.

    L'adresse MAC est libérée par la destruction et se réattribue : l'entrée
    restée derrière soustrairait au cache une machine neuve que personne n'a
    exceptée. Ni la VM ni le cache ne le diraient — la VM télécharge
    normalement, le journal du cache reste seulement muet à son sujet.
    """

    def test_une_vm_disparue_rend_son_entree_orpheline(self):
        from script.todo.qemu_cache_menu import QemuCacheMenuMixin as M

        entrees = [
            ("52:54:00:00:00:01", "vm-vivante"),
            ("52:54:00:00:00:02", "vm-detruite"),
        ]
        with mock.patch.object(
            M, "_cache_domaines", return_value={"vm-vivante"}
        ):
            orphelines = M._cache_bypass_orphelines(entrees)
        self.assertEqual(orphelines, [("52:54:00:00:00:02", "vm-detruite")])

    def test_une_entree_sans_nom_nest_jamais_orpheline(self):
        """Posée à la main : rien ne dit à quelle VM elle se rapporte, et la
        retirer d'office déferait le travail de quelqu'un."""
        from script.todo.qemu_cache_menu import QemuCacheMenuMixin as M

        with mock.patch.object(M, "_cache_domaines", return_value=set()):
            self.assertEqual(
                M._cache_bypass_orphelines([("52:54:00:00:00:03", "")]), []
            )

    def test_le_menage_retire_du_fichier_et_du_noyau(self):
        """Les deux : le fichier est ce que le service reposera, l'ensemble
        est ce qui s'applique en ce moment."""
        from script.todo import qemu_cache_menu as menu

        execute = mock.MagicMock()
        with mock.patch.object(
            menu.os.path, "isfile", return_value=True
        ), mock.patch.object(
            menu.QemuCacheMenuMixin,
            "_cache_bypass_orphelines",
            return_value=[("52:54:00:00:00:04", "partie")],
        ):
            self.assertEqual(menu.bypass_menage(execute), 1)
        cmd = execute.exec_command_live.call_args.args[0]
        self.assertIn("--bypass-del 52:54:00:00:00:04", cmd)
        self.assertIn("nft -f -", cmd)

    def test_sans_cache_pose_le_menage_ne_fait_rien(self):
        from script.todo import qemu_cache_menu as menu

        execute = mock.MagicMock()
        with mock.patch.object(menu.os.path, "isfile", return_value=False):
            self.assertEqual(menu.bypass_menage(execute), 0)
        execute.exec_command_live.assert_not_called()

    def test_la_liste_est_lue_du_binaire(self):
        """Lui seul normalise une adresse et saute une ligne fautive : une
        seconde lecture écrite ici dériverait de la sienne."""
        from script.todo.qemu_cache_menu import QemuCacheMenuMixin as M

        sortie = "52:54:00:aa:bb:cc vm-une\n52:54:00:11:22:33\n\n"
        with mock.patch.object(
            M, "_cache_lire", return_value=sortie
        ), mock.patch("os.path.isfile", return_value=True):
            self.assertEqual(
                M._cache_bypass_lire(),
                [("52:54:00:aa:bb:cc", "vm-une"), ("52:54:00:11:22:33", "")],
            )


class TestLaSuppressionFaitLeMenage(unittest.TestCase):
    def test_la_suppression_de_vm_appelle_le_menage(self):
        """Le seul endroit qui SAIT que la VM vient de disparaître."""
        src = (RACINE / "script" / "todo" / "qemu_manage.py").read_text(
            encoding="utf-8"
        )
        bloc = src[src.index("def _qemu_delete_vm(") :]
        bloc = bloc[: bloc.index("\n    def ")]
        self.assertIn("bypass_menage(self.execute)", bloc)


if __name__ == "__main__":
    unittest.main()
