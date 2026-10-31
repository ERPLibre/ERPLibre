#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Créer une VM sans root : le disque, le seed et le cache par l'API des
volumes de libvirt.

Le pool par défaut (/var/lib/libvirt/images) et son cache d'images
appartiennent à root. Le groupe libvirt n'y donne aucun droit d'écriture,
mais il ouvre la socket qemu:///system, et libvirtd, qui tourne en root,
écrit pour l'appelant : vol-create-from, vol-upload, vol-delete.

Ce que ces tests gardent :

- la voie se choisit par répertoire : direct s'il est inscriptible, volume
  s'il est la cible d'un pool, root sinon — et sudo n'apparaît que dans la
  dernière ;
- en voie volume, rien n'écrit directement dans le répertoire : ni cp, ni
  qemu-img, ni Python ;
- le volume d'une image déclare le format de son CONTENU, et il est lisible
  par tous (0644) : sans le mode, il naît 0600 et la somme ne se lit plus ;
- les virsh visent qemu:///system explicitement : implicite, un utilisateur
  interroge qemu:///session, où la VM n'existe pas.
"""

import io
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.qemu import deploy_qemu as DQ  # noqa: E402


def lignes(sortie: str) -> list[str]:
    """Les commandes affichées par un Runner à blanc, sans leur marque."""
    return [
        ligne.split("[dry-run] ", 1)[1]
        for ligne in sortie.splitlines()
        if "[dry-run] " in ligne
    ]


class AvecDepot(unittest.TestCase):
    """Un Runner à blanc et un Depot dont la voie est imposée."""

    def setUp(self):
        DQ._POOLS_RAFRAICHIS.clear()
        self.runner = DQ.Runner(
            use_sudo=True, dry_run=True, libvirt_sudo=False
        )
        patch = mock.patch.object(DQ, "terminal_present", return_value=True)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(DQ, "sudo_facts", return_value=[])
        patch.start()
        self.addCleanup(patch.stop)

    def depot(self, directory, inscriptible, pool=""):
        with (
            mock.patch.object(DQ, "_inscriptible", return_value=inscriptible),
            mock.patch.object(DQ, "pool_for_dir", return_value=pool),
            redirect_stdout(io.StringIO()),
        ):
            return DQ.Depot(Path(directory), self.runner)

    def jouer(self, geste, pool_source=""):
        """Rend les commandes affichées pendant `geste()`."""
        with (
            mock.patch.object(DQ, "pool_for_dir", return_value=pool_source),
            redirect_stdout(io.StringIO()) as sortie,
        ):
            geste()
        return lignes(sortie.getvalue())


class LaVoieSeChoisitParRepertoire(AvecDepot):
    def test_a_writable_directory_is_written_directly(self):
        self.assertEqual("direct", self.depot("/x", True, "iso").mode)

    def test_a_pool_target_goes_through_volumes(self):
        depot = self.depot("/var/lib/libvirt/images/iso", False, "iso")
        self.assertEqual(("volume", "iso"), (depot.mode, depot.pool))

    def test_neither_falls_back_on_root(self):
        self.assertEqual("root", self.depot("/opt/ferme", False).mode)

    def test_the_pool_is_refreshed_once(self):
        """Un fichier posé hors libvirt n'est un volume qu'après relecture ;
        la relire à chaque Depot encombrerait le journal."""
        sortie = io.StringIO()
        with (
            mock.patch.object(DQ, "_inscriptible", return_value=False),
            mock.patch.object(DQ, "pool_for_dir", return_value="iso"),
            redirect_stdout(sortie),
        ):
            DQ.Depot(Path("/a"), self.runner)
            DQ.Depot(Path("/a"), self.runner)
        vues = [c for c in lignes(sortie.getvalue()) if "pool-refresh" in c]
        self.assertEqual([f"virsh -c {DQ.LIBVIRT_URI} pool-refresh iso"], vues)

    def test_staging_lives_with_the_user_outside_the_direct_path(self):
        dest = Path("/var/lib/libvirt/images/iso/img.qcow2")
        volume = self.depot(dest.parent, False, "iso")
        self.assertEqual(
            DQ.staging_dir() / "img.qcow2.part", volume.staging(dest)
        )
        direct = self.depot(dest.parent, True)
        self.assertEqual(dest.parent / "img.qcow2.part", direct.staging(dest))


class LaPublication(AvecDepot):
    def test_a_volume_is_created_then_uploaded_without_sudo(self):
        depot = self.depot("/p/iso", False, "iso")
        with tempfile.NamedTemporaryFile(suffix=".iso") as src:
            vues = self.jouer(
                lambda: depot.publish(Path(src.name), Path("/p/iso/s.iso"))
            )
        self.assertEqual(2, len(vues), vues)
        self.assertTrue(
            vues[0].startswith(f"virsh -c {DQ.LIBVIRT_URI} vol-create iso ")
        )
        self.assertEqual(
            f"virsh -c {DQ.LIBVIRT_URI} vol-upload --pool iso s.iso {src.name}",
            vues[1],
        )
        self.assertFalse(any("sudo" in c for c in vues), vues)

    def test_root_mode_installs_with_sudo_and_nothing_else(self):
        depot = self.depot("/opt/ferme", False)
        vues = self.jouer(
            lambda: depot.publish(Path("/t/a"), Path("/opt/ferme/a"))
        )
        self.assertEqual(["sudo install -D -m 0644 /t/a /opt/ferme/a"], vues)

    def test_direct_mode_installs_without_sudo(self):
        depot = self.depot("/home/u/img", True)
        vues = self.jouer(
            lambda: depot.publish(Path("/t/a"), Path("/home/u/img/a"))
        )
        self.assertEqual(["install -D -m 0644 /t/a /home/u/img/a"], vues)

    def test_a_volume_declares_its_content_format_and_0644(self):
        """vol-create-from convertit selon le format DÉCLARÉ : un qcow2
        déclaré raw donnerait un disque illisible. Et sans le mode, le volume
        naît 0600, illisible pour la somme qui suit."""
        with tempfile.TemporaryDirectory() as tmp:
            qcow = Path(tmp) / "a.qcow2"
            qcow.write_bytes(b"QFI\xfb" + b"\0" * 60)
            brut = Path(tmp) / "b.iso"
            brut.write_bytes(b"CD001")
            self.assertEqual("qcow2", DQ.image_format(qcow))
            self.assertEqual("raw", DQ.image_format(brut))
        xml = DQ.volume_xml("a.qcow2", "64", "qcow2", mode="0644")
        self.assertIn("<format type='qcow2'/>", xml)
        self.assertIn("<mode>0644</mode>", xml)
        self.assertIn("<capacity unit='bytes'>64</capacity>", xml)
        self.assertIn(
            "<capacity unit='G'>8</capacity>",
            DQ.volume_xml("d", "8G", "qcow2"),
        )

    def test_a_volume_name_is_escaped_in_the_xml(self):
        self.assertIn("<name>a&amp;b</name>", DQ.volume_xml("a&b", "1", "raw"))

    def test_an_existing_volume_is_deleted_through_libvirt(self):
        depot = self.depot("/p/iso", False, "iso")
        with mock.patch.object(Path, "exists", return_value=True):
            vues = self.jouer(lambda: depot.delete(Path("/p/iso/v.iso")))
        self.assertEqual(
            [f"virsh -c {DQ.LIBVIRT_URI} vol-delete --pool iso v.iso"], vues
        )


class LeDisqueDeTravail(AvecDepot):
    def test_from_a_cached_volume_libvirt_copies_then_resizes(self):
        """vol-create-from n'applique pas la capacité de l'XML : sans le
        vol-resize, la VM garderait la taille de l'image."""
        depot = self.depot("/p/images", False, "default")
        vues = self.jouer(
            lambda: DQ.prepare_disk(
                Path("/p/images/iso/base.qcow2"),
                Path("/p/images/vm.qcow2"),
                "8G",
                self.runner,
                False,
                depot=depot,
            ),
            pool_source="iso",
        )
        self.assertTrue(
            vues[-2].startswith(
                f"virsh -c {DQ.LIBVIRT_URI} vol-create-from default "
            ),
            vues,
        )
        self.assertTrue(vues[-2].endswith("--inputpool iso base.qcow2"), vues)
        self.assertEqual(
            f"virsh -c {DQ.LIBVIRT_URI} vol-resize --pool default vm.qcow2 8G",
            vues[-1],
        )
        self.assertFalse(any("sudo" in c or "qemu-img" in c for c in vues))

    def test_an_image_outside_any_pool_is_prepared_by_the_user(self):
        """Convertie et agrandie chez l'utilisateur, puis téléversée : rien
        n'écrit dans le pool sans passer par libvirt."""
        depot = self.depot("/p/images", False, "default")
        vues = self.jouer(
            lambda: DQ.prepare_disk(
                Path("/home/u/base.qcow2"),
                Path("/p/images/vm.qcow2"),
                "8G",
                self.runner,
                False,
                depot=depot,
            ),
        )
        etape = DQ.staging_dir() / "vm.qcow2.part"
        self.assertIn(f"qemu-img resize {etape} 8G", vues)
        self.assertTrue(
            any("vol-upload --pool default vm.qcow2" in c for c in vues)
        )
        self.assertFalse(any("sudo" in c for c in vues), vues)

    def test_root_mode_keeps_qemu_img_under_sudo(self):
        depot = self.depot("/opt/ferme", False)
        vues = self.jouer(
            lambda: DQ.prepare_disk(
                Path("/x/base.qcow2"),
                Path("/opt/ferme/vm.qcow2"),
                "8G",
                self.runner,
                False,
                depot=depot,
            )
        )
        self.assertTrue(all(c.startswith("sudo qemu-img") for c in vues), vues)

    def test_a_blank_disk_is_a_volume_too(self):
        depot = self.depot("/p/images", False, "default")
        vues = self.jouer(
            lambda: DQ.create_blank_disk(
                Path("/p/images/vm.qcow2"),
                "8G",
                self.runner,
                False,
                depot=depot,
            )
        )
        self.assertEqual(
            [
                f"virsh -c {DQ.LIBVIRT_URI} vol-create-as default vm.qcow2 8G"
                " --format qcow2"
            ],
            vues,
        )


class LeSeed(AvecDepot):
    def test_the_seed_is_built_by_the_user_then_uploaded(self):
        depot = self.depot("/p/iso", False, "iso")
        with mock.patch.object(DQ.shutil, "which", return_value="/x"):
            vues = self.jouer(
                lambda: DQ.build_seed(
                    "#cloud-config\n",
                    "vm",
                    Path("/p/iso/vm-seed.iso"),
                    self.runner,
                    None,
                    depot=depot,
                )
            )
        self.assertTrue(
            any(c.startswith("cloud-localds ") for c in vues), vues
        )
        self.assertTrue(
            any("vol-upload --pool iso vm-seed.iso" in c for c in vues)
        )
        self.assertFalse(
            any(c.startswith(("cp ", "sudo")) for c in vues), vues
        )


class LeCacheDImages(unittest.TestCase):
    """Le téléchargement se fait chez l'utilisateur, la publication par le
    Depot — jamais d'écriture directe dans le cache partagé."""

    def test_a_volume_depot_receives_the_finished_download(self):
        import http.server

        contenu = b"QFI\xfb" + b"x" * 5000

        class Poignee(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(contenu)))
                self.end_headers()
                self.wfile.write(contenu)

        httpd = http.server.HTTPServer(("127.0.0.1", 0), Poignee)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        url = f"http://127.0.0.1:{httpd.server_address[1]}/img.qcow2"

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "cache" / "img.qcow2"
            etape = Path(tmp) / "moi" / "img.qcow2.part"
            publies = []

            class FauxDepot:
                mode = "volume"

                def staging(self, d):
                    return etape

                def publish(self, src, d):
                    publies.append((src.read_bytes(), d))

            with redirect_stdout(io.StringIO()):
                DQ.download_image(
                    [url], dest, False, timeout=10, depot=FauxDepot()
                )
            self.assertEqual([(contenu, dest)], publies)
            self.assertFalse(dest.exists(), "le cache a été écrit en direct")
            self.assertFalse(etape.exists(), "le fichier d'étape est resté")


class LAdresse(unittest.TestCase):
    def test_wait_for_ip_names_the_system_uri(self):
        vus = []

        def run(argv, **kw):
            vus.append(argv)
            return mock.Mock(stdout="")

        with (
            mock.patch.object(DQ.subprocess, "run", run),
            mock.patch.object(DQ.time, "sleep", lambda s: None),
            mock.patch.object(DQ.time, "time", side_effect=[0, 0, 99]),
        ):
            DQ.wait_for_ip("vm", False, 5)
        self.assertEqual(
            [
                "virsh",
                "-c",
                DQ.LIBVIRT_URI,
                "domifaddr",
                "vm",
                "--source",
                "lease",
            ],
            vus[0],
        )


class LeVerrou(unittest.TestCase):
    def test_the_lock_lives_with_the_user_and_is_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(DQ.os.environ, {"XDG_CACHE_HOME": tmp}):
                with DQ.verrou_image(Path("/c/img.qcow2"), False):
                    verrou = Path(tmp) / "erplibre/qemu-staging/img.qcow2.lock"
                    self.assertTrue(verrou.exists())
                # Relâché : le reprendre ne bloque pas.
                with DQ.verrou_image(Path("/c/img.qcow2"), False):
                    pass

    def test_a_dry_run_takes_no_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(DQ.os.environ, {"XDG_CACHE_HOME": tmp}):
                with DQ.verrou_image(Path("/c/img.qcow2"), True):
                    pass
            self.assertEqual([], list(Path(tmp).iterdir()))


if __name__ == "__main__":
    unittest.main()
