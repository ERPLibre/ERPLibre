#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le cloud-init des VM créées SUR un hôte Proxmox.

Deux corrections que seule une VM réelle pouvait dicter, mesurées sur un
Proxmox 9 :

**Le user-data est celui du DÉPÔT**, écrit comme extrait et donné par
« --cicustom user= ». « --ciuser » et « --sshkeys » s'en remettent au compte
par DÉFAUT de l'image : celle de NixOS en déclare un autre — « nixos » — et
les ignorait. La VM démarrait avec ce compte-là, sans la clé, donc
injoignable. Le user-data du dépôt porte un bloc « users: » explicite, avec le
nom, le shell et le sudo — le même que le chemin qemu envoie, et déjà éprouvé.

**Le lecteur cloud-init est sur le bus SCSI**, contrairement à ce que la
documentation de Proxmox montre. Une image bâtie pour virtio seul n'a pas de
pilote ATA et ne VOIT pas un lecteur IDE : /sys/block sans « sr0 »,
/dev/disk/by-label sans « cidata », et cloud-init qui passe aux sources
réseau faute de trouver la locale. Le même lecteur en scsi1 apparaît.

Éprouvé de bout en bout, séquence régénérée sans retouche : NixOS rend
« erplibre@… shell=/bin/sh sudo-ok », Debian 13 « shell=/bin/bash sudo-ok ».
"""

import sys
import unittest
from pathlib import Path

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]

from script.proxmox import proxmox_deploy as pve  # noqa: E402

SPEC = {
    "name": "essai",
    "storage": "local",
    "bridge": "vmbr0",
    "memory": 2048,
    "vcpus": 2,
    "disk": "20G",
    "image": "image.qcow2",
    "user": "erplibre",
    "start": True,
    "ipconfig": "ip=dhcp",
}
UD = "#cloud-config\nhostname: essai\nusers:\n  - name: erplibre\n"


class LeLecteurCloudInit(unittest.TestCase):
    def test_it_sits_on_the_scsi_bus(self):
        """Une image bâtie pour virtio seul ne voit pas un lecteur IDE, et
        cloud-init passe alors aux sources réseau : la VM démarre sans compte
        ni clé. Le contrôleur virtio-scsi est déjà là pour le disque."""
        joint = " ".join(pve.create_cmds(100, SPEC))
        self.assertIn("--scsi1 local:cloudinit", joint)
        self.assertNotIn("--ide2", joint)

    def test_the_boot_order_still_names_the_system_disk(self):
        """Le lecteur cloud-init n'est pas amorçable : sans « boot order »,
        Proxmox laisse le disque importé hors de la liste."""
        ligne = [c for c in pve.create_cmds(100, SPEC) if "--scsi1" in c][0]
        self.assertIn("--boot order=scsi0", ligne)
        self.assertIn("--bootdisk scsi0", ligne)


class LNomDeLExtrait(unittest.TestCase):
    def test_it_is_carried_by_the_vmid(self):
        """Deux VM peuvent porter le même NOM sur deux nœuds, jamais le même
        VMID sur un cluster. Un extrait écrasé par un homonyme donnerait à
        une VM le compte d'une autre."""
        self.assertEqual("erplibre-9030.yml", pve.snippet_name(9030))
        self.assertNotEqual(pve.snippet_name(100), pve.snippet_name(101))

    def test_it_ends_in_yml(self):
        """Proxmox lit l'extrait comme du YAML ; l'extension est ce qui le
        distingue d'un hook ou d'un fichier de sauvegarde dans le dossier."""
        self.assertTrue(pve.snippet_name(1).endswith(".yml"))


class LEcritureDeLExtrait(unittest.TestCase):
    def test_the_path_is_asked_of_proxmox(self):
        """Un stockage « dir » range ses extraits sous son propre répertoire :
        supposer /var/lib/vz marcherait pour « local » et pour lui seul."""
        cmd = pve.snippet_write_cmd("autre", "x.yml", "a: b\n")
        self.assertIn("pvesm path", cmd)
        self.assertIn("autre:snippets/x.yml", cmd)

    def test_the_directory_is_created(self):
        """Un stockage neuf n'a pas encore son dossier d'extraits."""
        self.assertIn("mkdir -p", pve.snippet_write_cmd("local", "x", "y"))

    def test_printf_and_not_echo(self):
        """echo interprète les séquences d'échappement sur certains shells :
        un « \\n » dans un mot de passe haché serait corrompu en silence."""
        cmd = pve.snippet_write_cmd("local", "x", "a: b\n")
        self.assertIn("printf '%s'", cmd)
        self.assertNotIn("echo ", cmd)

    def test_the_content_is_quoted_whole(self):
        """Un YAML porte des deux-points, des espaces et des retours à la
        ligne : non cité, il se disperse en arguments."""
        cmd = pve.snippet_write_cmd("local", "x", "a: b\nc: 'd'\n")
        self.assertIn("a: b", cmd)
        self.assertIn("c: ", cmd)


class LaSequenceAvecUserData(unittest.TestCase):
    def _cmds(self):
        return pve.create_cmds(100, dict(SPEC, user_data=UD))

    def test_the_repository_user_data_is_given_to_the_vm(self):
        joint = " ".join(self._cmds())
        self.assertIn("--cicustom user=local:snippets/erplibre-100.yml", joint)

    def test_the_default_user_keys_are_dropped(self):
        """Les laisser ferait deux autorités sur le même compte."""
        joint = " ".join(self._cmds())
        self.assertNotIn("--ciuser", joint)
        self.assertNotIn("--sshkeys", joint)

    def test_the_network_stays_with_proxmox(self):
        """« --cicustom user= » ne remplace que la moitié utilisateur : le
        réseau vient toujours d'ipconfig0, et sans lui la VM est muette."""
        self.assertIn("--ipconfig0 ip=dhcp", " ".join(self._cmds()))

    def test_the_snippet_is_written_before_it_is_referenced(self):
        """Proxmox lit l'extrait quand il fabrique l'ISO : référencer un
        fichier absent laisse la VM sans user-data du tout."""
        cmds = self._cmds()
        i_ecrit = next(i for i, c in enumerate(cmds) if "pvesm path" in c)
        i_ref = next(i for i, c in enumerate(cmds) if "--cicustom" in c)
        self.assertLess(i_ecrit, i_ref)

    def test_everything_comes_before_the_start(self):
        cmds = self._cmds()
        i_start = next(i for i, c in enumerate(cmds) if c == "qm start 100")
        for marque in ("pvesm path", "--cicustom"):
            with self.subTest(marque=marque):
                i = next(i for i, c in enumerate(cmds) if marque in c)
                self.assertLess(i, i_start)


class LaFormeDAvantEstGardee(unittest.TestCase):
    """Sans user-data, la séquence reste celle d'avant : `create_cmds` sert
    aussi aux tests longs, qui n'en fabriquent pas."""

    def test_the_old_keys_come_back(self):
        cmds = pve.create_cmds(100, dict(SPEC, sshkey_path="/root/k.pub"))
        ci = [c for c in cmds if "--ciuser" in c][0]
        self.assertIn("--ciuser erplibre", ci)
        self.assertIn("--sshkeys /root/k.pub", ci)
        self.assertNotIn("--cicustom", " ".join(cmds))

    def test_no_snippet_is_written(self):
        joint = " ".join(pve.create_cmds(100, SPEC))
        self.assertNotIn("pvesm path", joint)


class LeMenuFabriqueLeUserData(unittest.TestCase):
    SRC = (RACINE / "script/todo/proxmox_menu.py").read_text(encoding="utf-8")

    def test_it_comes_from_the_repository_builder(self):
        """Un user-data écrit à la main dans le menu divergerait de celui du
        chemin qemu, et c'est celui-là qui est éprouvé."""
        self.assertIn("mod.build_cloud_config(", self.SRC)
        self.assertIn("def _pve_user_data", self.SRC)

    # Ce qui EXÉCUTE sur l'hôte. Une fonction qui compose des commandes sans
    # jamais en appeler un ne crée rien : c'est un aperçu, et il n'a pas de VM
    # à rendre joignable.
    EXECUTANTS = ("_pve_show", "_pve_ssh")

    def test_every_creation_path_goes_through_it(self):
        """CHAQUE VOIE QUI CRÉE pose le user-data — et non « deux endroits le
        posent ». Compter les occurrences liait la garde à la FORME du
        fichier : ramener deux descriptions jumelles à un seul composeur la
        faisait rougir alors qu'elle tient MIEUX, un site de moins étant un
        site de moins à oublier. L'aperçu se distingue par ce qu'il fait —
        il n'atteint aucun exécutant — et non par son nom.
        """
        import ast

        arbre = ast.parse(self.SRC)
        pose = set()
        cree = set()
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.FunctionDef):
                continue
            corps = ast.get_source_segment(self.SRC, noeud)
            if '"user_data"' in corps:
                pose.add(noeud.name)
            if "pve.create_cmds(" in corps and any(
                x in corps for x in self.EXECUTANTS
            ):
                cree.add(noeud.name)
        self.assertTrue(pose, "personne ne pose de user-data")
        self.assertEqual(set(), cree - pose, sorted(cree - pose))

    def test_a_creation_path_is_actually_seen(self):
        """Contrôle du banc : zéro voie de création rendrait l'épreuve
        ci-dessus verte sans rien tenir."""
        import ast

        arbre = ast.parse(self.SRC)
        composeurs = [
            n.name
            for n in ast.walk(arbre)
            if isinstance(n, ast.FunctionDef)
            and '"user_data"' in ast.get_source_segment(self.SRC, n)
            and "pve.create_cmds(" in ast.get_source_segment(self.SRC, n)
        ]
        self.assertEqual(["_pve_vm_commands"], composeurs)

    def test_an_unreadable_key_falls_back_instead_of_locking_out(self):
        """Un user-data sans clé donnerait une VM sans aucun moyen d'entrer :
        mieux vaut la forme d'avant, qui pose au moins un compte."""
        i = self.SRC.index("def _pve_user_data")
        corps = self.SRC[i : i + 1600]
        self.assertIn("SSH key unreadable:", corps)
        self.assertIn('return ""', corps)


if __name__ == "__main__":
    unittest.main()
