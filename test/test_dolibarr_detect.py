#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Trouver les installations Dolibarr d'une machine, locale ou par SSH.

La sonde est un script POSIX sh exécuté pour de vrai ici, sur un arbre
inventé ; un faux `podman` en tête du PATH répond pour les conteneurs. Ce
qui se garde :
- une installation se reconnaît à master.inc.php, filefunc.inc.php et
  main.inc.php réunis ; sa version se lit dans version.inc.php, ou dans
  filefunc.inc.php pour les versions d'avant ;
- de conf.php, seules des clés nommées sortent : jamais le mot de passe ;
- « rien trouvé » et « rien trouvé mais des dossiers illisibles » sont deux
  réponses différentes, comme un refus d'authentification et un réseau
  injoignable.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import detect  # noqa: E402

SONDE = RACINE / "script" / "dolibarr" / "detect_probe.sh"
MOT_DE_PASSE = "Invente4Test"

CONF = f"""<?php
$dolibarr_main_url_root='https://erp.example.org';
$dolibarr_main_document_root='/srv/erp/htdocs';
$dolibarr_main_data_root='/srv/erp/documents';
$dolibarr_main_db_host='localhost';
$dolibarr_main_db_port='3306';
$dolibarr_main_db_name='dolibarr_erp';
$dolibarr_main_db_type='mysqli';
$dolibarr_main_db_user='dolibarr_erp';
$dolibarr_main_db_pass='{MOT_DE_PASSE}';
"""


def installation(racine, version_inc=None, filefunc="<?php\n", conf=None):
    htdocs = Path(racine)
    (htdocs / "conf").mkdir(parents=True)
    for nom in ("master.inc.php", "main.inc.php"):
        (htdocs / nom).write_text("<?php\n")
    (htdocs / "filefunc.inc.php").write_text(filefunc)
    if version_inc:
        (htdocs / "version.inc.php").write_text(version_inc)
    if conf is not None:
        (htdocs / "conf" / "conf.php").write_text(conf)
    return htdocs


class Sonde(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        self.bin = self.racine / "bin"
        self.bin.mkdir()
        self.faux_podman("")

    def faux_podman(self, sortie):
        script = self.bin / "podman"
        script.write_text(f"#!/bin/sh\nprintf '{sortie}'\n")
        script.chmod(0o755)

    def sonder(self, *racines):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "LC_ALL": "C"}
        r = subprocess.run(
            ["sh", str(SONDE), "7", *[str(x) for x in racines]],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout


class TestInstallations(Sonde):
    def setUp(self):
        super().setUp()
        self.www = self.racine / "www"
        installation(
            self.www / "erp" / "htdocs",
            version_inc=(
                "<?php\ndefine('DOL_MAJOR_VERSION', '24');\n"
                "define('DOL_MINOR_VERSION', '0.1');\n"
            ),
            conf=CONF,
        )
        installation(
            self.racine / "opt" / "ancien" / "htdocs",
            filefunc="<?php\ndefine('DOL_VERSION', '18.0.5');\n",
        )
        # Un master.inc.php seul n'est pas Dolibarr.
        autre = self.www / "autre"
        autre.mkdir(parents=True)
        (autre / "master.inc.php").write_text("<?php\n")

    def test_each_installation_with_its_version_and_database(self):
        rapport = detect.parse_probe(
            self.sonder(self.www, self.racine / "opt")
        )
        self.assertEqual(rapport["status"], "yes")
        par_chemin = {i["path"]: i for i in rapport["installs"]}
        self.assertEqual(
            set(par_chemin),
            {
                str(self.www / "erp" / "htdocs"),
                str(self.racine / "opt" / "ancien" / "htdocs"),
            },
        )
        erp = par_chemin[str(self.www / "erp" / "htdocs")]
        self.assertEqual(erp["version"], "24.0.1")
        self.assertEqual(erp["conf"], "readable")
        self.assertEqual(erp["db_type"], "mysqli")
        self.assertEqual(erp["db_host"], "localhost")
        self.assertEqual(erp["db_name"], "dolibarr_erp")
        self.assertEqual(erp["url"], "https://erp.example.org")
        self.assertEqual(erp["data_root"], "/srv/erp/documents")
        ancien = par_chemin[str(self.racine / "opt" / "ancien" / "htdocs")]
        self.assertEqual(ancien["version"], "18.0.5")
        self.assertEqual(ancien["conf"], "absent")

    def test_the_password_never_leaves_the_machine(self):
        self.assertNotIn(MOT_DE_PASSE, self.sonder(self.www))

    def test_an_unreadable_conf_is_said_not_guessed(self):
        conf = self.www / "erp" / "htdocs" / "conf" / "conf.php"
        conf.chmod(0)
        self.addCleanup(conf.chmod, 0o644)
        rapport = detect.parse_probe(self.sonder(self.www))
        erp = rapport["installs"][0]
        self.assertEqual(erp["conf"], "unreadable")
        self.assertEqual(erp["db_name"], "")


class TestReponses(Sonde):
    def test_nothing_found_is_no(self):
        vide = self.racine / "vide"
        vide.mkdir()
        self.assertEqual(detect.parse_probe(self.sonder(vide))["status"], "no")

    def test_nothing_found_behind_a_locked_directory_is_denied(self):
        ferme = self.racine / "ferme"
        (ferme / "dedans").mkdir(parents=True)
        ferme.chmod(0)
        self.addCleanup(ferme.chmod, 0o755)
        rapport = detect.parse_probe(self.sonder(ferme))
        self.assertEqual(rapport["status"], "denied")

    def test_a_dolibarr_container_is_listed(self):
        self.faux_podman(
            "erplibre-dolibarr-erp-web|docker.io/dolibarr/dolibarr:24.0.0"
            "|Up 3 minutes\\nautre|docker.io/library/nginx:stable|Up 1 hour\\n"
        )
        vide = self.racine / "vide"
        vide.mkdir()
        rapport = detect.parse_probe(self.sonder(vide))
        self.assertEqual(rapport["status"], "yes")
        self.assertEqual(
            rapport["containers"],
            [
                {
                    "engine": "podman",
                    "name": "erplibre-dolibarr-erp-web",
                    "image": "docker.io/dolibarr/dolibarr:24.0.0",
                    "state": "Up 3 minutes",
                }
            ],
        )


class TestSsh(unittest.TestCase):
    def test_each_failure_keeps_its_kind(self):
        cas = (
            (0, "DOLIBARR\tno\n", "ok"),
            (255, "user@h: Permission denied (publickey).", "auth"),
            (255, "ssh: Could not resolve hostname h: Name or service", "net"),
            (
                255,
                "ssh: connect to host h port 22: Connection timed out",
                "net",
            ),
            (255, "ssh: connect to host h port 22: Connection refused", "net"),
            (255, "Host key verification failed.", "hostkey"),
            (0, "sh: 1: syntax error", "error"),
        )
        for code, sortie, attendu in cas:
            with self.subTest(sortie=sortie):
                self.assertEqual(detect.classify(code, sortie), attendu)

    def test_the_probe_goes_by_stdin_in_one_round_trip(self):
        argv = detect.remote_argv({"target": "hote-a"}, ["/var/www"])
        self.assertEqual(argv[0], "ssh")
        self.assertIn("BatchMode=yes", argv)
        self.assertEqual(argv[-2], "hote-a")
        self.assertEqual(argv[-1], "sh -s -- 7 /var/www")


class TestParse(unittest.TestCase):
    def test_noise_before_the_header_is_ignored(self):
        texte = "Welcome to a host\nDOLIBARR_HOST=x\nDOLIBARR\tno\n"
        self.assertEqual(detect.parse_probe(texte)["status"], "no")

    def test_no_header_is_no_report(self):
        self.assertIsNone(detect.parse_probe("bash: sh: not found\n"))


class TestCommande(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        self.reponses = {}
        self.appels = []

    def sonde(self, argv):
        self.appels.append(argv)
        cible = "local" if argv[0] == "sh" else argv[-2]
        return self.reponses[cible]

    def lancer(self, *argv):
        import contextlib
        import io

        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = detect.main(
                list(argv), root=str(self.racine), probe=self.sonde
            )
        return code, sortie.getvalue()

    def rapport(self, hote):
        chemin = (
            self.racine / "private" / "dolibarr" / "inventory" / f"{hote}.json"
        )
        import json

        return chemin, json.loads(chemin.read_text())

    def test_each_host_gets_its_state_and_a_private_report(self):
        self.reponses = {
            "local": (0, "DOLIBARR\tyes\nINSTALL\t/srv/erp/htdocs\t24.0.1\n"),
            "hote-a": (255, "user@hote-a: Permission denied (publickey)."),
        }
        code, sortie = self.lancer("--local", "--ssh", "hote-a")
        self.assertEqual(code, 1)
        self.assertIn("/srv/erp/htdocs", sortie)
        self.assertIn(detect.t(detect._STATE_LABELS["auth"]), sortie)
        chemin, data = self.rapport("local")
        self.assertEqual(data["state"], "ok")
        self.assertEqual(data["report"]["installs"][0]["version"], "24.0.1")
        self.assertEqual(chemin.stat().st_mode & 0o777, 0o600)
        self.assertEqual(chemin.parent.stat().st_mode & 0o777, 0o700)
        _chemin, data = self.rapport("hote-a")
        self.assertEqual(data["state"], "auth")
        self.assertIsNone(data["report"])

    def test_every_host_reached_is_success(self):
        self.reponses = {"local": (0, "DOLIBARR\tno\n")}
        code, _sortie = self.lancer("--local")
        self.assertEqual(code, 0)

    def test_a_host_name_cannot_leave_the_inventory(self):
        self.reponses = {"../../x": (0, "DOLIBARR\tno\n")}
        self.lancer("--ssh", "../../x")
        fichiers = list(
            (self.racine / "private" / "dolibarr" / "inventory").iterdir()
        )
        self.assertEqual([f.name for f in fichiers], [".._.._x.json"])

    def test_nothing_to_probe_says_so(self):
        code, _sortie = self.lancer()
        self.assertEqual(code, 2)
        self.assertEqual(self.appels, [])


if __name__ == "__main__":
    unittest.main()
