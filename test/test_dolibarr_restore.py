#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Restaurer une sauvegarde sur une instance inscrite : ce qui écrase.

Les archives sont de vraies archives ; le système simulé enregistre les
commandes et ce qu'elles reçoivent sur stdin. Ce qui se garde :
- rien ne s'écrase sans le nom de l'instance retapé en entier ;
- une sauvegarde de sûreté de l'état courant précède tout, et son échec
  arrête tout ;
- une sauvegarde plus récente que le code de l'instance est refusée ;
- la clé d'instance de la sauvegarde suit ses données : sans elle, les
  valeurs chiffrées en base deviennent illisibles ;
- une archive qui sortirait de son dossier à l'extraction est refusée.
"""

import contextlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import backup, restore  # noqa: E402

CLE_SAUVEE = "CleDeLaSauvegarde1"
CLE_ACTUELLE = "CleDeLInstance2"


def conf(cle):
    return f"<?php\n$dolibarr_main_db_name='dolibarr_erp';\n$dolibarr_main_instance_unique_id='{cle}';\n"


def membre_tar(fichiers):
    tampon = io.BytesIO()
    with tarfile.open(fileobj=tampon, mode="w") as tar:
        for nom, texte in fichiers.items():
            donnees = texte.encode()
            info = tarfile.TarInfo(nom)
            info.size = len(donnees)
            tar.addfile(info, io.BytesIO(donnees))
    return tampon.getvalue()


def archive(chemin, version="24.0.1", cle=CLE_SAUVEE, extra=None):
    membres = {
        "manifest.json": json.dumps(
            {"instance": "erp", "version": version, "db": "mariadb"}
        ).encode(),
        "db.sql": b"CREATE TABLE llx_const (x int);\n",
        "documents.tar": membre_tar({"./facture/F1.pdf": "pdf"}),
        "conf.php": conf(cle).encode(),
        "custom.tar": membre_tar({"./monmodule/mod.php": "<?php\n"}),
    }
    membres.update(extra or {})
    with tarfile.open(chemin, "w:gz") as tar:
        for nom, donnees in membres.items():
            info = tarfile.TarInfo(nom)
            info.size = len(donnees)
            tar.addfile(info, io.BytesIO(donnees))
    return chemin


class Systeme:
    def __init__(self):
        self.appels = []  # (argv, env, stdin octets)
        self.echec = set()

    def run(self, argv, env=None, stdin_path=None):
        recu = Path(stdin_path).read_bytes() if stdin_path else b""
        self.appels.append((list(argv), dict(env or {}), recu))
        if any(mot in " ".join(argv) for mot in self.echec):
            return 1, "ERROR"
        return 0, ""

    def run_to_file(self, argv, path, env=None):
        Path(path).write_bytes(b"")
        return 0, ""

    def engine(self, moteur):
        return {
            "moteur": moteur,
            "sans_sudo": True,
            "avec_sudo": False,
            "rootless": True,
            "docker_host": None,
        }

    def http_get(self, url, host):
        return "<title>Login @ 24.0.1</title>"


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        self.etat = self.racine / "etat" / "erp"
        self.checkout = self.racine / "dolibarr"
        htdocs = self.checkout / "htdocs"
        (htdocs / "conf").mkdir(parents=True)
        self.conf = htdocs / "conf" / "conf.php"
        self.conf.write_text(conf(CLE_ACTUELLE))
        self.conf.chmod(0o600)
        (htdocs / "custom" / "ancien").mkdir(parents=True)
        self.documents = self.etat / "documents"
        (self.documents / "vieux").mkdir(parents=True)
        (self.documents / "vieux" / "a.txt").write_text("vieux")
        (self.etat / "secrets.env").write_text("DB_PASSWORD=Mdp1\n")
        self.entree = {
            "mode": "dev",
            "runtime": "native",
            "db": "mariadb",
            "db_name": "dolibarr_erp",
            "code_root": str(self.checkout),
            "data_root": str(self.documents),
            "state_dir": str(self.etat),
            "version": "24.0.1",
            "secrets": f"file:{self.etat}/secrets.env",
        }
        self.sys = Systeme()
        self.archive = archive(self.racine / "erp-20260901-000000.tar.gz")

    def restaurer(self, confirme="erp", entree=None):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = restore.restore(
                "erp",
                entree or self.entree,
                str(self.archive),
                confirme,
                self.sys,
                str(self.racine),
                "20260927-090000",
            )
        return code, sortie.getvalue()

    def commandes(self):
        return [" ".join(a) for a, _e, _s in self.sys.appels]


class TestGardeFous(Banc):
    def test_nothing_happens_without_the_name_retyped(self):
        for mauvais in ("", "er", "ERP", "erp "):
            with self.subTest(mauvais=mauvais):
                code, _s = self.restaurer(confirme=mauvais)
                self.assertEqual(code, 2)
        self.assertEqual(self.sys.appels, [])
        self.assertTrue((self.documents / "vieux" / "a.txt").exists())

    def test_a_safety_backup_comes_first_and_its_failure_stops_all(self):
        with mock.patch.object(backup, "create", return_value=None) as create:
            code, _s = self.restaurer()
        self.assertEqual(code, 1)
        self.assertEqual(create.call_args[0][4], "pre-restore-20260927-090000")
        self.assertEqual(self.sys.appels, [])
        self.assertTrue((self.documents / "vieux" / "a.txt").exists())

    def test_a_backup_newer_than_the_code_is_refused(self):
        self.archive = archive(self.racine / "neuf.tar.gz", version="25.0.0")
        code, _s = self.restaurer()
        self.assertEqual(code, 1)
        self.assertEqual(self.sys.appels, [])

    def test_an_archive_that_is_not_a_backup_is_refused(self):
        chemin = self.racine / "autre.tar.gz"
        with tarfile.open(chemin, "w:gz") as tar:
            info = tarfile.TarInfo("README.md")
            info.size = 2
            tar.addfile(info, io.BytesIO(b"hi"))
        self.archive = chemin
        code, sortie = self.restaurer()
        self.assertEqual(code, 1)
        self.assertIn(restore.t("Not a Dolibarr backup: %s") % chemin, sortie)
        self.assertEqual(self.sys.appels, [])
        self.assertTrue((self.documents / "vieux" / "a.txt").exists())

    def test_a_member_that_is_a_link_is_refused(self):
        # Chargé plus loin, un db.sql qui serait un lien lirait sa cible.
        chemin = self.racine / "lien.tar.gz"
        with tarfile.open(archive(self.racine / "base.tar.gz")) as source:
            membres = {m.name: source.extractfile(m).read() for m in source}
        with tarfile.open(chemin, "w:gz") as tar:
            for nom, donnees in membres.items():
                if nom == "db.sql":
                    info = tarfile.TarInfo(nom)
                    info.type = tarfile.SYMTYPE
                    info.linkname = "/etc/hostname"
                    tar.addfile(info)
                    continue
                info = tarfile.TarInfo(nom)
                info.size = len(donnees)
                tar.addfile(info, io.BytesIO(donnees))
        self.archive = chemin
        code, _s = self.restaurer()
        self.assertEqual(code, 1)
        self.assertEqual(self.sys.appels, [])

    def test_an_archive_that_escapes_its_folder_is_refused(self):
        piege = membre_tar({"../../evade.txt": "x"})
        self.archive = archive(
            self.racine / "piege.tar.gz", extra={"documents.tar": piege}
        )
        code, _s = self.restaurer()
        self.assertEqual(code, 1)
        self.assertFalse((self.racine / "evade.txt").exists())
        self.assertFalse((self.etat / "evade.txt").exists())


class TestNatifDev(Banc):
    def test_the_database_is_recreated_then_loaded(self):
        code, sortie = self.restaurer()
        self.assertEqual(code, 0, sortie)
        cmds = self.commandes()
        reset = next(i for i, c in enumerate(cmds) if "DROP DATABASE" in c)
        charge = next(
            i
            for i, (a, _e, s) in enumerate(self.sys.appels)
            if b"CREATE TABLE" in s
        )
        self.assertLess(reset, charge)
        self.assertIn("utf8_unicode_ci", cmds[reset])
        for argv, env, _s in self.sys.appels:
            self.assertNotIn("Mdp1", " ".join(argv))
            self.assertEqual(env.get("MYSQL_PWD"), "Mdp1")

    def test_documents_and_custom_are_replaced(self):
        self.restaurer()
        self.assertFalse((self.documents / "vieux").exists())
        self.assertEqual(
            (self.documents / "facture" / "F1.pdf").read_text(), "pdf"
        )
        custom = self.checkout / "htdocs" / "custom"
        self.assertFalse((custom / "ancien").exists())
        self.assertTrue((custom / "monmodule" / "mod.php").exists())

    def test_the_backup_key_follows_its_data(self):
        self.restaurer()
        texte = self.conf.read_text()
        self.assertIn(CLE_SAUVEE, texte)
        self.assertNotIn(CLE_ACTUELLE, texte)
        self.assertIn("$dolibarr_main_db_name='dolibarr_erp';", texte)
        self.assertEqual(self.conf.stat().st_mode & 0o777, 0o600)

    def test_a_failed_load_names_the_safety_backup(self):
        self.sys.echec.add("mariadb -u dolibarr_erp dolibarr_erp")
        code, sortie = self.restaurer()
        self.assertEqual(code, 1)
        self.assertIn("pre-restore-20260927-090000", sortie)


class TestProduction(Banc):
    def setUp(self):
        super().setUp()
        self.entree.update(
            mode="prod",
            user="dolibarr_erp",
            cron_timer="erplibre-dolibarr-cron-erp.timer",
            state_dir="/var/lib/erplibre-dolibarr/erp",
            data_root="/var/lib/erplibre-dolibarr/erp/documents",
            code_root="/opt/erplibre-dolibarr/erp",
        )
        self.sys.conf_prod = conf(CLE_ACTUELLE)

    def lire(self, system, path):
        if path.endswith("cron.env"):
            return "CRON_KEY=CleCronInstance\n"
        return conf(CLE_ACTUELLE)

    def test_the_instance_cron_key_is_applied_again(self):
        # Clonée, la base porte la clé cron de la source : la minuterie de
        # l'instance enverrait la sienne, refusée à chaque passage.
        with mock.patch.object(restore, "_sudo_read", self.lire):
            code, sortie = self.restaurer()
        self.assertEqual(code, 0, sortie)
        argv, _env, recu = next(
            (a, e, r)
            for a, e, r in self.sys.appels
            if a[:4] == ["sudo", "-u", "dolibarr_erp", "php"]
        )
        self.assertIn("CRON_KEY", " ".join(argv))
        self.assertNotIn("CleCronInstance", " ".join(argv))
        self.assertEqual(recu, b"CleCronInstance\n")

    def test_production_restores_through_sudo_with_the_timer_stopped(self):
        with mock.patch.object(restore, "_sudo_read", self.lire):
            code, sortie = self.restaurer()
        self.assertEqual(code, 0, sortie)
        cmds = self.commandes()
        arret = cmds.index(
            "sudo systemctl stop erplibre-dolibarr-cron-erp.timer"
        )
        depart = cmds.index(
            "sudo systemctl start erplibre-dolibarr-cron-erp.timer"
        )
        self.assertLess(arret, depart)
        doc = "/var/lib/erplibre-dolibarr/erp/documents"
        self.assertIn(f"sudo find {doc} -mindepth 1 -delete", cmds)
        self.assertIn(f"sudo chown -R dolibarr_erp:dolibarr_erp {doc}", cmds)
        ecrit = next(
            s
            for a, _e, s in self.sys.appels
            if a[:2] == ["sudo", "install"] and a[-1].endswith("conf.php")
        )
        self.assertIn(CLE_SAUVEE.encode(), ecrit)
        installe = next(
            a
            for a, _e, _s in self.sys.appels
            if a[:2] == ["sudo", "install"] and a[-1].endswith("conf.php")
        )
        self.assertEqual(
            installe[2:8], ["-m", "440", "-o", "root", "-g", "dolibarr_erp"]
        )


class TestConteneur(Banc):
    def setUp(self):
        super().setUp()
        secrets = self.etat / "secrets"
        secrets.mkdir()
        (secrets / "instance_id").write_text(CLE_ACTUELLE + "\n")
        self.noms = [
            f"erplibre-dolibarr-erp-{r}" for r in ("db", "web", "cron")
        ]
        self.entree = {
            "mode": "dev",
            "runtime": "container",
            "engine": "podman",
            "db": "mariadb",
            "containers": self.noms,
            "custom_dir": str(self.etat / "custom"),
            "state_dir": str(self.etat),
            "port": 8081,
            "url": "http://127.0.0.1:8081",
            "admin_login": "admin",
            "image": "docker.io/dolibarr/dolibarr:24.0.0",
            "version": "24.0.1",
        }
        (self.etat / "custom" / "ancien").mkdir(parents=True)

    def test_the_containers_are_recreated_with_the_backup_key(self):
        code, sortie = self.restaurer()
        self.assertEqual(code, 0, sortie)
        self.assertEqual(
            (self.etat / "secrets" / "instance_id").read_text().strip(),
            CLE_SAUVEE,
        )
        cmds = self.commandes()
        charge = next(
            i
            for i, (a, _e, s) in enumerate(self.sys.appels)
            if b"CREATE TABLE" in s
        )
        self.assertIn("exec -i erplibre-dolibarr-erp-db", cmds[charge])
        suppression = cmds.index(
            "podman rm -f erplibre-dolibarr-erp-web erplibre-dolibarr-erp-cron"
        )
        relance = [i for i, c in enumerate(cmds) if c.startswith("podman run")]
        self.assertTrue(relance and min(relance) > suppression)
        cle = next(
            i
            for i, c in enumerate(cmds)
            if "exec erplibre-dolibarr-erp-web php" in c and "CRON_KEY" in c
        )
        self.assertGreater(cle, min(relance))
        self.assertIn("/run/secrets/cron_key", cmds[cle])
        self.assertTrue(
            (self.etat / "custom" / "monmodule" / "mod.php").exists()
        )
        self.assertFalse((self.etat / "custom" / "ancien").exists())


class SansFiltre:
    """Python avant 3.11.4 (Debian 12 livre 3.11.2) n'a pas le filtre
    « data » de tarfile : la même vérification se fait à la main."""

    def setUp(self):
        super().setUp()
        origine = tarfile.TarFile.extractall

        def extractall_3_11_2(tar, path=".", members=None, **kw):
            if "filter" in kw:
                raise TypeError(
                    "extractall() got an unexpected keyword 'filter'"
                )
            # 3.11.2 extrait sans aucun filtre ; 3.14 filtre d'office.
            return origine(tar, path, members, filter="fully_trusted")

        patches = [
            mock.patch.object(
                tarfile.TarFile, "extractall", extractall_3_11_2
            ),
            mock.patch.object(restore, "_HAS_FILTER", False, create=True),
        ]
        if hasattr(tarfile, "data_filter"):
            patches.append(mock.patch.object(tarfile, "data_filter", None))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class TestGardeFousSansFiltre(SansFiltre, TestGardeFous):
    def test_a_link_out_of_the_folder_is_refused(self):
        tampon = io.BytesIO()
        with tarfile.open(fileobj=tampon, mode="w") as tar:
            lien = tarfile.TarInfo("./sortie")
            lien.type = tarfile.SYMTYPE
            lien.linkname = "../../../etc"
            tar.addfile(lien)
        self.archive = archive(
            self.racine / "lien.tar.gz",
            extra={"documents.tar": tampon.getvalue()},
        )
        code, _s = self.restaurer()
        self.assertEqual(code, 1)
        self.assertEqual(self.sys.appels, [])

    def test_a_device_or_fifo_is_refused(self):
        tampon = io.BytesIO()
        with tarfile.open(fileobj=tampon, mode="w") as tar:
            fifo = tarfile.TarInfo("./tube")
            fifo.type = tarfile.FIFOTYPE
            tar.addfile(fifo)
        self.archive = archive(
            self.racine / "fifo.tar.gz",
            extra={"documents.tar": tampon.getvalue()},
        )
        code, _s = self.restaurer()
        self.assertEqual(code, 1)
        self.assertEqual(self.sys.appels, [])


class TestNatifDevSansFiltre(SansFiltre, TestNatifDev):
    pass


if __name__ == "__main__":
    unittest.main()
