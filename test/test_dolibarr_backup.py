#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Sauvegarder une instance Dolibarr : base, documents, conf.php, custom/.

Un système simulé rend le vidage de la base et les flux tar ; l'archive,
elle, est vraiment écrite et relue. Ce qui se garde :
- une sauvegarde porte la base, documents/, conf.php (sa clé d'instance
  chiffre des valeurs en base) et custom/, avec un manifeste ;
- l'archive est 0600 dans un dossier 0700 sous private/ : elle porte les
  données d'un client ;
- aucun mot de passe sur argv : il passe par l'environnement du vidage ;
- un vidage qui échoue ne laisse aucune archive, ni morceau.
"""

import contextlib
import io
import json
import stat
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import backup  # noqa: E402

MDP = "MotDePasseInvente9"


class Systeme:
    """Commandes simulées : chaque sortie va dans le fichier demandé."""

    def __init__(self):
        self.appels = []  # (argv, env)
        self.sorties = {}  # premier mot significatif -> octets
        self.echec = set()

    def run_to_file(self, argv, path, env=None):
        self.appels.append((list(argv), dict(env or {})))
        cle = next(
            (a for a in argv if a in self.sorties or a in self.echec), None
        )
        if cle in self.echec:
            return 1, "mysqldump: Got error: 1045"
        with open(path, "wb") as f:
            f.write(self.sorties.get(cle, b""))
        return 0, ""

    def engine(self, moteur):
        return {
            "moteur": moteur,
            "sans_sudo": True,
            "avec_sudo": False,
            "rootless": True,
            "docker_host": None,
        }


def flux_tar(fichiers):
    tampon = io.BytesIO()
    with tarfile.open(fileobj=tampon, mode="w") as tar:
        for nom, texte in fichiers.items():
            donnees = texte.encode()
            info = tarfile.TarInfo(nom)
            info.size = len(donnees)
            tar.addfile(info, io.BytesIO(donnees))
    return tampon.getvalue()


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        self.etat = self.racine / "etat" / "erp"
        self.checkout = self.racine / "dolibarr"
        (self.checkout / "htdocs" / "conf").mkdir(parents=True)
        (self.checkout / "htdocs" / "conf" / "conf.php").write_text(
            "<?php\n$dolibarr_main_instance_unique_id='cleinventee';\n"
        )
        (self.checkout / "htdocs" / "custom").mkdir()
        (self.etat / "documents").mkdir(parents=True)
        (self.etat / "secrets.env").write_text(f"DB_PASSWORD={MDP}\n")
        self.entree = {
            "mode": "dev",
            "runtime": "native",
            "db": "mariadb",
            "db_name": "dolibarr_erp",
            "code_root": str(self.checkout),
            "data_root": str(self.etat / "documents"),
            "state_dir": str(self.etat),
            "version": "24.0.1",
            "commit": "0" * 40,
            "secrets": f"file:{self.etat}/secrets.env",
        }
        self.sys = Systeme()
        self.sys.sorties = {
            "mariadb-dump": b"CREATE TABLE llx_const (x int);\n",
            "pg_dump": b"CREATE TABLE llx_const (x int);\n",
            "tar": flux_tar({"./facture/F1.pdf": "pdf"}),
        }
        self.ecrire_registre({"erp": self.entree})

    def ecrire_registre(self, instances):
        registre = self.racine / "private" / "dolibarr" / "instances.json"
        registre.parent.mkdir(parents=True, exist_ok=True)
        registre.write_text(json.dumps({"instances": instances}))

    def sauver(self, *argv):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = backup.main(
                ["create", "--instance", "erp", *argv],
                root=str(self.racine),
                system=self.sys,
                now=lambda: "20260927-081500",
            )
        return code, sortie.getvalue()

    def archive(self):
        dossier = self.racine / "private" / "dolibarr" / "backups" / "erp"
        return dossier / "erp-20260927-081500.tar.gz"


class TestContenu(Banc):
    def test_the_archive_holds_the_database_files_conf_and_manifest(self):
        code, sortie = self.sauver()
        self.assertEqual(code, 0, sortie)
        with tarfile.open(self.archive()) as tar:
            noms = set(tar.getnames())
            manifeste = json.load(tar.extractfile("manifest.json"))
            conf = tar.extractfile("conf.php").read().decode()
        self.assertEqual(
            noms,
            {
                "manifest.json",
                "db.sql",
                "documents.tar",
                "conf.php",
                "custom.tar",
            },
        )
        self.assertEqual(manifeste["instance"], "erp")
        self.assertEqual(manifeste["db"], "mariadb")
        self.assertEqual(manifeste["version"], "24.0.1")
        self.assertIn("cleinventee", conf)

    def test_a_loose_backup_directory_is_closed(self):
        dossier = self.archive().parent
        dossier.mkdir(parents=True)
        dossier.chmod(0o755)
        self.sauver()
        self.assertEqual(stat.S_IMODE(dossier.stat().st_mode), 0o700)

    def test_the_archive_is_private(self):
        self.sauver()
        self.assertEqual(stat.S_IMODE(self.archive().stat().st_mode), 0o600)
        self.assertEqual(
            stat.S_IMODE(self.archive().parent.stat().st_mode), 0o700
        )


class TestSecrets(Banc):
    def test_the_database_password_goes_by_the_environment(self):
        self.sauver()
        argv, env = next(
            (a, e) for a, e in self.sys.appels if "mariadb-dump" in a
        )
        self.assertNotIn(MDP, " ".join(argv))
        self.assertEqual(env.get("MYSQL_PWD"), MDP)
        self.assertIn("--single-transaction", argv)
        self.assertIn("dolibarr_erp", argv)

    def test_postgresql_uses_its_own_tool_and_variable(self):
        self.entree["db"] = "postgresql"
        self.ecrire_registre({"erp": self.entree})
        self.sauver()
        argv, env = next((a, e) for a, e in self.sys.appels if "pg_dump" in a)
        self.assertEqual(env.get("PGPASSWORD"), MDP)
        self.assertNotIn(MDP, " ".join(argv))


class TestEchec(Banc):
    def test_a_failed_dump_leaves_nothing(self):
        self.sys.echec.add("mariadb-dump")
        code, _sortie = self.sauver()
        self.assertEqual(code, 1)
        dossier = self.archive().parent
        self.assertEqual(
            list(dossier.iterdir()) if dossier.exists() else [], []
        )

    def test_an_unknown_instance_exits_2(self):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = backup.main(
                ["create", "--instance", "nope"],
                root=str(self.racine),
                system=self.sys,
            )
        self.assertEqual(code, 2)


class TestConteneur(Banc):
    def setUp(self):
        super().setUp()
        self.entree = {
            "mode": "dev",
            "runtime": "container",
            "engine": "podman",
            "db": "mariadb",
            "containers": [
                "erplibre-dolibarr-erp-db",
                "erplibre-dolibarr-erp-web",
                "erplibre-dolibarr-erp-cron",
            ],
            "custom_dir": str(self.etat / "custom"),
            "version": "24.0.0",
            "state_dir": str(self.etat),
        }
        (self.etat / "custom").mkdir()
        self.sys.sorties["cat"] = (
            b"<?php\n$dolibarr_main_instance_unique_id='x';\n"
        )
        self.ecrire_registre({"erp": self.entree})

    def test_the_engine_dumps_inside_the_database_container(self):
        code, sortie = self.sauver()
        self.assertEqual(code, 0, sortie)
        argv, env = next(
            (a, e) for a, e in self.sys.appels if "mariadb-dump" in " ".join(a)
        )
        self.assertEqual(
            argv[:3], ["podman", "exec", "erplibre-dolibarr-erp-db"]
        )
        # Le mot de passe est lu DANS le conteneur, depuis son secret.
        self.assertIn("/run/secrets/db_root_password", " ".join(argv))
        with tarfile.open(self.archive()) as tar:
            self.assertIn("documents.tar", tar.getnames())
            self.assertIn(
                "instance_unique_id",
                tar.extractfile("conf.php").read().decode(),
            )


class TestOrdre(Banc):
    def test_newest_first_by_date_whatever_the_prefix(self):
        dossier = self.racine / "private" / "dolibarr" / "backups" / "erp"
        dossier.mkdir(parents=True)
        for nom in (
            "erp-pre-upgrade-20260927-092405.tar.gz",
            "erp-pre-restore-20260927-092326.tar.gz",
            "erp-20260927-093025.tar.gz",
            "erp-20260927-092308.tar.gz",
        ):
            (dossier / nom).write_bytes(b"x")
        noms = [Path(p).name for p in backup.archives(str(self.racine), "erp")]
        self.assertEqual(
            noms,
            [
                "erp-20260927-093025.tar.gz",
                "erp-pre-upgrade-20260927-092405.tar.gz",
                "erp-pre-restore-20260927-092326.tar.gz",
                "erp-20260927-092308.tar.gz",
            ],
        )

    def test_the_backups_of_a_removed_instance_are_still_listed(self):
        dossier = self.racine / "private" / "dolibarr" / "backups" / "ancienne"
        dossier.mkdir(parents=True)
        (dossier / "ancienne-20260901-000000.tar.gz").write_bytes(b"x")
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            backup.main(["list"], root=str(self.racine))
        self.assertIn("ancienne-20260901-000000.tar.gz", sortie.getvalue())


class TestListe(Banc):
    def test_list_shows_the_archives_newest_first(self):
        dossier = self.racine / "private" / "dolibarr" / "backups" / "erp"
        dossier.mkdir(parents=True)
        for nom in (
            "erp-20260901-000000.tar.gz",
            "erp-20260927-081500.tar.gz",
        ):
            (dossier / nom).write_bytes(b"x")
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            backup.main(["list", "--instance", "erp"], root=str(self.racine))
        lignes = [x for x in sortie.getvalue().splitlines() if ".tar.gz" in x]
        self.assertIn("20260927", lignes[0])


if __name__ == "__main__":
    unittest.main()
