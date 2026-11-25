#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Archive de sauvegarde d'une instance (script/erp_common/archive).

Un système simulé rend la sortie des commandes ; l'archive, elle, est
vraiment écrite et relue. Ce qui se garde :
- l'archive porte les membres du plan et manifest.json ; elle est 0600
  dans un dossier 0700, même un dossier qui existait plus ouvert ;
- un membre qui échoue ne laisse ni archive, ni morceau ;
- exposed signale le dossier de travail même quand git ignore l'archive ;
  sans l'outillage TODO, le doute refuse ;
- les archives se classent par date, quel que soit le préfixe, sous
  private/<erp>/backups/ ;
- à la lecture, un membre qui sortirait du dossier d'extraction est
  refusé avant toute écriture, avec ou sans le filtre « data » de tarfile.
Chaque test qui dépend du nom de l'ERP tourne pour deux noms.
"""

import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.erp_common import archive  # noqa: E402

# Deux noms : celui d'un ERP réel et un nom inventé, pour prouver que rien
# n'est écrit en dur.
ERPS = ("dolibarr", "acme")
STAMP = "20260927-081500"


class Systeme:
    """Commandes simulées : la sortie de argv[0] va dans le fichier demandé."""

    def __init__(self):
        self.appels = []  # (argv, env)
        self.sorties = {"dump": b"CREATE TABLE t (x int);\n"}
        self.echec = set()

    def run_to_file(self, argv, path, env=None):
        self.appels.append((list(argv), dict(env or {})))
        if argv[0] in self.echec:
            return 1, "dump: Got error: 1045"
        with open(path, "wb") as f:
            f.write(self.sorties.get(argv[0], b""))
        return 0, ""


def flux_tar(fichiers, types=None):
    """Octets d'un tar : {nom: texte}, et {nom: (type, cible)} pour les
    membres sans contenu (lien, tube)."""
    tampon = io.BytesIO()
    with tarfile.open(fileobj=tampon, mode="w") as tar:
        for nom, texte in fichiers.items():
            donnees = texte.encode()
            info = tarfile.TarInfo(nom)
            info.size = len(donnees)
            tar.addfile(info, io.BytesIO(donnees))
        for nom, (genre, cible) in (types or {}).items():
            info = tarfile.TarInfo(nom)
            info.type = genre
            info.linkname = cible
            tar.addfile(info)
    return tampon.getvalue()


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        self.sys = Systeme()
        self.site = self.racine / "site.cfg"
        self.site.write_text("cle=inventee\n")

    def plan(self):
        return [
            ("db.sql", ["dump", "--base", "erp"], {"PW": "MotInvente7"}),
            ("site.cfg", str(self.site), None),
        ]

    def ecrire(self, dest, plan=None):
        with mock.patch("builtins.print"):
            return archive.write(
                str(dest),
                "erp",
                STAMP,
                plan or self.plan,
                {"instance": "erp", "date": STAMP},
                self.sys,
            )


class TestEcriture(Banc):
    def test_the_archive_holds_the_plan_members_and_the_manifest(self):
        dest = self.racine / "sauvegardes"
        chemin = self.ecrire(dest)
        self.assertEqual(chemin, str(dest / f"erp-{STAMP}.tar.gz"))
        with tarfile.open(chemin) as tar:
            noms = set(tar.getnames())
            manifeste = json.load(tar.extractfile("manifest.json"))
            site = tar.extractfile("site.cfg").read().decode()
            base = tar.extractfile("db.sql").read()
        self.assertEqual(noms, {"manifest.json", "db.sql", "site.cfg"})
        self.assertEqual(manifeste, {"instance": "erp", "date": STAMP})
        self.assertEqual(site, "cle=inventee\n")
        self.assertIn(b"CREATE TABLE", base)
        self.assertEqual(self.sys.appels[0][1], {"PW": "MotInvente7"})

    def test_a_loose_backup_directory_is_closed(self):
        dest = self.racine / "sauvegardes"
        dest.mkdir()
        dest.chmod(0o755)
        self.ecrire(dest)
        self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o700)

    def test_the_archive_is_private(self):
        dest = self.racine / "sauvegardes"
        chemin = Path(self.ecrire(dest))
        self.assertEqual(stat.S_IMODE(chemin.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o700)

    def test_a_failed_dump_leaves_nothing(self):
        self.sys.echec.add("dump")
        dest = self.racine / "sauvegardes"
        self.assertIsNone(self.ecrire(dest))
        self.assertEqual(list(dest.iterdir()) if dest.exists() else [], [])

    def test_a_missing_file_to_copy_leaves_nothing(self):
        self.site.unlink()
        dest = self.racine / "sauvegardes"
        self.assertIsNone(self.ecrire(dest))
        self.assertEqual(list(dest.iterdir()), [])

    def test_the_plan_is_asked_once_the_folder_exists(self):
        dest = self.racine / "sauvegardes"
        vu = []

        def plan():
            vu.append(dest.is_dir())
            return self.plan()

        self.ecrire(dest, plan)
        self.assertEqual(vu, [True])


class TestGit(Banc):
    """Une archive porte la base et ses secrets : jamais là où git la
    commiterait."""

    def depot(self, ignore=""):
        depot = self.racine / "depot"
        depot.mkdir()
        subprocess.run(["git", "init", "-q", str(depot)], check=True)
        (depot / ".gitignore").write_text(ignore)
        return depot

    def test_ignoring_the_archive_alone_leaves_the_work_folder_exposed(self):
        dest = self.depot("*.tar.gz\n*.part\n")
        for membre in ("conf.php", "site.cfg"):
            with self.subTest(membre=membre):
                refuses = archive.exposed(str(dest), "erp", STAMP, membre)
                self.assertEqual([Path(p).name for p in refuses], [membre])

    def test_a_folder_git_ignores_exposes_nothing(self):
        dest = self.depot("/sauvegardes/\n") / "sauvegardes"
        self.assertEqual(
            archive.exposed(str(dest), "erp", STAMP, "site.cfg"), []
        )

    def test_without_the_todo_tooling_the_doubt_refuses(self):
        with mock.patch.dict(sys.modules, {"script.todo.seal_menu": None}):
            self.assertTrue(archive.committable(str(self.racine / "x")))


class TestOrdre(Banc):
    def test_the_backups_folder_follows_the_erp_name(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                self.assertEqual(
                    archive.backups_dir(erp),
                    os.path.join("private", erp, "backups"),
                )

    def test_newest_first_by_date_whatever_the_prefix(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                dossier = self.racine / "private" / erp / "backups" / "erp"
                dossier.mkdir(parents=True)
                for nom in (
                    "erp-pre-upgrade-20260927-092405.tar.gz",
                    "erp-pre-restore-20260927-092326.tar.gz",
                    "erp-20260927-093025.tar.gz",
                    "erp-20260927-092308.tar.gz",
                    "notes.txt",
                ):
                    (dossier / nom).write_bytes(b"x")
                noms = [
                    Path(p).name
                    for p in archive.archives(erp, str(self.racine), "erp")
                ]
                self.assertEqual(
                    noms,
                    [
                        "erp-20260927-093025.tar.gz",
                        "erp-pre-upgrade-20260927-092405.tar.gz",
                        "erp-pre-restore-20260927-092326.tar.gz",
                        "erp-20260927-092308.tar.gz",
                    ],
                )

    def test_saved_instances_are_those_with_a_backup_folder(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                racine = str(self.racine / erp)
                self.assertEqual(archive.saved_instances(erp, racine), [])
                self.assertEqual(archive.archives(erp, racine, "erp"), [])
                for nom in ("zeta", "alpha"):
                    os.makedirs(
                        os.path.join(racine, archive.backups_dir(erp), nom)
                    )
                self.assertEqual(
                    archive.saved_instances(erp, racine), ["alpha", "zeta"]
                )


class TestLecture(Banc):
    MEMBRES = {"manifest.json", "db.sql", "files.tar"}

    def archive(self, extra=None):
        membres = {
            "manifest.json": json.dumps({"instance": "erp"}).encode(),
            "db.sql": b"CREATE TABLE t (x int);\n",
            "files.tar": flux_tar({"./a/b.txt": "b"}),
        }
        membres.update(extra or {})
        chemin = self.racine / "archive.tar.gz"
        with tarfile.open(chemin, "w:gz") as tar:
            for nom, donnees in membres.items():
                info = tarfile.TarInfo(nom)
                info.size = len(donnees)
                tar.addfile(info, io.BytesIO(donnees))
        return chemin

    def lire(self, chemin):
        work = self.racine / "work"
        work.mkdir(exist_ok=True)
        return archive.read_archive(
            str(chemin),
            str(work),
            self.MEMBRES,
            ("files.tar",),
            "Not a backup of this ERP: %s",
        )

    def test_a_backup_is_extracted_and_its_manifest_returned(self):
        manifeste = self.lire(self.archive())
        self.assertEqual(manifeste, {"instance": "erp"})
        self.assertTrue((self.racine / "work" / "db.sql").exists())

    def test_an_archive_with_other_members_is_refused(self):
        chemin = self.archive(extra={"README.md": b"hi"})
        with self.assertRaises(archive.ArchiveError) as ctx:
            self.lire(chemin)
        self.assertIn(str(chemin), str(ctx.exception))
        self.assertFalse((self.racine / "work" / "db.sql").exists())

    def test_a_nested_tar_that_escapes_its_folder_is_refused(self):
        piege = flux_tar({"../../evade.txt": "x"})
        with self.assertRaises(archive.ArchiveError):
            self.lire(self.archive(extra={"files.tar": piege}))
        self.assertFalse((self.racine / "evade.txt").exists())

    def test_a_link_out_of_the_folder_is_refused(self):
        lien = flux_tar({}, {"./sortie": (tarfile.SYMTYPE, "../../../etc")})
        with self.assertRaises(archive.ArchiveError):
            self.lire(self.archive(extra={"files.tar": lien}))

    def test_a_device_or_fifo_is_refused(self):
        tube = flux_tar({}, {"./tube": (tarfile.FIFOTYPE, "")})
        with self.assertRaises(archive.ArchiveError):
            self.lire(self.archive(extra={"files.tar": tube}))

    def test_a_member_that_is_a_link_is_refused(self):
        chemin = self.racine / "lien.tar.gz"
        with tarfile.open(chemin, "w:gz") as tar:
            for nom in ("manifest.json", "files.tar"):
                donnees = b"{}" if nom == "manifest.json" else flux_tar({})
                info = tarfile.TarInfo(nom)
                info.size = len(donnees)
                tar.addfile(info, io.BytesIO(donnees))
            info = tarfile.TarInfo("db.sql")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/hostname"
            tar.addfile(info)
        with self.assertRaises(archive.ArchiveError):
            self.lire(chemin)
        self.assertFalse((self.racine / "work" / "db.sql").exists())


class TestMembre(unittest.TestCase):
    """check_member, la vérification faite à la main sans filtre « data »."""

    def membre(self, nom, genre=tarfile.REGTYPE, cible=""):
        info = tarfile.TarInfo(nom)
        info.type = genre
        info.linkname = cible
        return info

    def test_members_inside_the_folder_pass(self):
        for info in (
            self.membre("./a/b.txt"),
            self.membre("a", tarfile.DIRTYPE),
            self.membre("a/lien", tarfile.SYMTYPE, "../b.txt"),
            self.membre("a/dur", tarfile.LNKTYPE, "a/b.txt"),
        ):
            with self.subTest(nom=info.name):
                archive.check_member(info)

    def test_members_leaving_the_folder_are_refused(self):
        for info in (
            self.membre("/etc/passwd"),
            self.membre("a/../../b"),
            self.membre("a/lien", tarfile.SYMTYPE, "/etc"),
            self.membre("a/lien", tarfile.SYMTYPE, "../../etc"),
            self.membre("dur", tarfile.LNKTYPE, "../x"),
            self.membre("tube", tarfile.FIFOTYPE),
            self.membre("disque", tarfile.BLKTYPE),
        ):
            with self.subTest(nom=info.name, type=info.type):
                with self.assertRaises(tarfile.TarError):
                    archive.check_member(info)


class SansFiltre:
    """Python avant 3.11.4 n'a pas le filtre « data » de tarfile : la même
    vérification se fait à la main, par check_member."""

    def setUp(self):
        super().setUp()
        origine = tarfile.TarFile.extractall

        def extractall_sans_filtre(tar, path=".", members=None, **kw):
            if "filter" in kw:
                raise TypeError(
                    "extractall() got an unexpected keyword 'filter'"
                )
            # Sans filtre, rien n'est retenu ; 3.14 filtre d'office.
            return origine(tar, path, members, filter="fully_trusted")

        patches = [
            mock.patch.object(
                tarfile.TarFile, "extractall", extractall_sans_filtre
            ),
        ]
        if hasattr(tarfile, "data_filter"):
            patches.append(mock.patch.object(tarfile, "data_filter", None))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_the_filter_is_seen_as_absent(self):
        self.assertFalse(archive.has_filter())


class TestLectureSansFiltre(SansFiltre, TestLecture):
    pass


if __name__ == "__main__":
    unittest.main()
