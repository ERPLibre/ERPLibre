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
import subprocess
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

                def publication_interrompue(self, d):
                    return False

                def publish(self, src, d):
                    publies.append((src.read_bytes(), d))

            with redirect_stdout(io.StringIO()):
                DQ.download_image(
                    [url], dest, False, timeout=10, depot=FauxDepot()
                )
            self.assertEqual([(contenu, dest)], publies)
            self.assertFalse(dest.exists(), "le cache a été écrit en direct")
            self.assertFalse(etape.exists(), "le fichier d'étape est resté")


class LAperçuNeDemandeRien(unittest.TestCase):
    """--dry-run ne lance aucun sudo, même quand la socket refuse
    l'utilisateur : l'aperçu du menu tourne en utilisateur, et une invite de
    mot de passe y serait une question posée par une commande qui ne doit
    rien toucher."""

    def _sudo_lances(self, *extra):
        vus = []

        def faux(argv, *a, **k):
            vus.append(list(argv))
            return subprocess.CompletedProcess(argv, 1, "", "")

        argv = [
            "deploy_qemu.py",
            "--distro",
            "debian",
            "--version",
            "13",
            "--name",
            "vm-apercu",
            "--password",
            "x",
            "--dry-run",
            *extra,
        ]
        DQ._POOLS.clear()
        DQ.libvirt_sudo_reset()
        self.addCleanup(DQ._POOLS.clear)
        self.addCleanup(DQ.libvirt_sudo_reset)
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(DQ, "libvirt_ready", return_value=False),
            mock.patch.object(DQ, "terminal_present", return_value=True),
            mock.patch.object(DQ.os, "geteuid", return_value=1000),
            mock.patch.object(DQ.subprocess, "run", faux),
            redirect_stdout(io.StringIO()),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            DQ.main()
        return [v for v in vus if v[:1] == ["sudo"]]

    def test_a_cloud_image_preview_runs_no_sudo(self):
        self.assertEqual([], self._sudo_lances())

    def test_an_installer_preview_runs_no_sudo(self):
        """La voie s390x lit le réseau pour choisir une adresse fixe."""
        self.assertEqual([], self._sudo_lances("--arch", "s390x"))


class UnePublicationInterrompue(unittest.TestCase):
    """vol-create réserve le volume sous son nom FINAL avant que vol-upload
    ne le remplisse. Un envoi coupé ne doit jamais laisser derrière lui un
    fichier que le passage suivant prendrait pour une image complète."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        patch = mock.patch.dict(
            DQ.os.environ, {"XDG_CACHE_HOME": str(self.tmp / "xdg")}
        )
        patch.start()
        self.addCleanup(patch.stop)
        DQ._POOLS_RAFRAICHIS.clear()
        self.lances = []
        self.echoue = set()

    def _faux_run(self, cmd, *a, check=False, **k):
        self.lances.append(list(cmd))
        verbe = next((v for v in cmd if v.startswith("vol-")), "")
        code = 1 if verbe in self.echoue else 0
        if verbe == "vol-create" and not code:
            # libvirtd réserve le fichier sous son nom final.
            self.dest.parent.mkdir(parents=True, exist_ok=True)
            self.dest.write_bytes(b"\0" * 64)
        if code and check:
            raise subprocess.CalledProcessError(code, cmd)
        return subprocess.CompletedProcess(cmd, code, "", None)

    def _publier(self, dest):
        self.dest = dest
        runner = DQ.Runner(use_sudo=True, dry_run=False, libvirt_sudo=False)
        src = self.tmp / "img.part"
        src.write_bytes(b"QFI\xfb" + b"x" * 64)
        with (
            mock.patch.object(DQ, "_inscriptible", return_value=False),
            mock.patch.object(DQ, "pool_for_dir", return_value="iso"),
            mock.patch.object(DQ.subprocess, "run", self._faux_run),
            redirect_stdout(io.StringIO()),
        ):
            depot = DQ.Depot(dest.parent, runner)
            with self.assertRaises(SystemExit):
                depot.publish(src, dest)
        return depot

    def verbes(self):
        return [
            next((v for v in c if v.startswith(("vol-", "pool-"))), c[0])
            for c in self.lances
        ]

    def test_a_failed_upload_deletes_the_reserved_volume(self):
        self.echoue = {"vol-upload"}
        dest = self.tmp / "pool" / "img.qcow2"
        depot = self._publier(dest)
        self.assertEqual(
            ["pool-refresh", "vol-create", "vol-upload", "vol-delete"],
            self.verbes(),
        )
        self.assertFalse(depot.publication_interrompue(dest))

    def test_a_volume_left_behind_is_known_as_interrupted(self):
        """Ni le retrait ni un SIGKILL ne passent : le témoin, posé chez
        l'utilisateur avant vol-create, reste et désigne le volume."""
        self.echoue = {"vol-upload", "vol-delete"}
        dest = self.tmp / "pool" / "img.qcow2"
        depot = self._publier(dest)
        self.assertTrue(dest.exists())
        self.assertTrue(depot.publication_interrompue(dest))

    def test_the_next_download_replaces_an_interrupted_image(self):
        import http.server

        contenu = b"QFI\xfb" + b"y" * 100

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
        dest = self.tmp / "pool" / "img.qcow2"
        dest.parent.mkdir()
        dest.write_bytes(b"\0" * 64)
        gestes = []

        class FauxDepot:
            mode = "volume"

            def staging(self, d):
                return DQ.staging_dir() / (d.name + ".part")

            def publication_interrompue(self, d):
                return True

            def delete(self, d):
                gestes.append("delete")
                d.unlink()

            def publish(self, src, d):
                gestes.append(("publish", src.read_bytes()))

        with redirect_stdout(io.StringIO()) as sortie:
            DQ.download_image([url], dest, False, timeout=10, depot=FauxDepot())
        self.assertEqual(["delete", ("publish", contenu)], gestes)
        self.assertNotIn("déjà présente", sortie.getvalue())

    def test_a_failed_publication_drops_the_staging_file(self):
        """Le fichier d'étape pèse la taille de l'image : il ne reste pas
        après un échec, que le passage suivant retéléchargera de zéro."""
        import http.server

        class Poignee(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "8")
                self.end_headers()
                self.wfile.write(b"QFI\xfbabcd")

        httpd = http.server.HTTPServer(("127.0.0.1", 0), Poignee)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        url = f"http://127.0.0.1:{httpd.server_address[1]}/img.qcow2"
        etape = self.tmp / "moi" / "img.qcow2.part"

        class FauxDepot:
            mode = "volume"

            def staging(self, d):
                return etape

            def publication_interrompue(self, d):
                return False

            def publish(self, src, d):
                sys.exit("vol-upload coupé")

        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            DQ.download_image(
                [url], self.tmp / "pool" / "img.qcow2", False, depot=FauxDepot()
            )
        self.assertFalse(etape.exists())

    def test_the_manual_resume_hint_needs_no_root_outside_direct(self):
        """En voie volume, le cache n'est pas inscriptible : l'indice vise un
        fichier de l'utilisateur, passé ensuite en argument, jamais
        « sudo curl » dans le répertoire du pool."""

        class FauxDepot:
            mode = "volume"

            def staging(self, d):
                return DQ.staging_dir() / (d.name + ".part")

            def publication_interrompue(self, d):
                return False

        dest = self.tmp / "pool" / "img.qcow2"
        with (
            redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit) as fin,
        ):
            DQ.download_image(
                ["http://127.0.0.1:9/img.qcow2"],
                dest,
                False,
                timeout=2,
                depot=FauxDepot(),
            )
        message = str(fin.exception.code)
        self.assertNotIn("sudo", message)
        self.assertIn(str(DQ.staging_dir() / "img.qcow2"), message)


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
