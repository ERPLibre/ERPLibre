#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lecture de la sortie d'une sonde et classement d'un hôte
(script/erp_common/detect).

Aucune sonde ne tourne : les sorties sont écrites à la main. Ce qui se
garde :
- seule la ligne d'en-tête de l'ERP reçu fait un rapport ; ce qui la
  précède est ignoré ;
- un refus d'authentification, une clé d'hôte inconnue, un réseau
  injoignable et une sonde muette sont quatre réponses différentes ;
- la sonde part sur stdin, en un aller-retour ;
- le rapport reste sous private/<erp>/inventory/, en 0600 dans un dossier
  0700, quel que soit le nom d'hôte.
Chaque test qui dépend de l'ERP tourne pour deux noms.
"""

import datetime
import json
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.erp_common import detect  # noqa: E402

# Deux ERP : un réel et un nom inventé, pour prouver que rien n'est écrit
# en dur. Chacun avec l'en-tête de sa sonde et ses champs d'installation.
ERPS = (
    ("dolibarr", "DOLIBARR", ("path", "version", "conf")),
    ("acme", "ACME", ("path", "version", "site")),
)


class TestParse(unittest.TestCase):
    def test_noise_before_the_header_is_ignored(self):
        for _erp, entete, champs in ERPS:
            with self.subTest(entete=entete):
                texte = f"Welcome to a host\n{entete}_HOST=x\n{entete}\tno\n"
                rapport = detect.parse_probe(entete, champs, texte)
                self.assertEqual(rapport["status"], "no")

    def test_no_header_is_no_report(self):
        for _erp, entete, champs in ERPS:
            with self.subTest(entete=entete):
                self.assertIsNone(
                    detect.parse_probe(entete, champs, "bash: sh: not found\n")
                )
                self.assertIsNone(detect.parse_probe(entete, champs, None))

    def test_another_erp_header_is_no_report(self):
        self.assertIsNone(
            detect.parse_probe("ACME", ("path",), "DOLIBARR\tyes\n")
        )

    def test_installs_take_the_erp_fields_and_containers_the_common_ones(
        self,
    ):
        for _erp, entete, champs in ERPS:
            with self.subTest(entete=entete):
                texte = (
                    f"{entete}\tyes\n"
                    "INSTALL\t/srv/erp\t1.2\n"
                    "AUTRE\tignoré\n"
                    "CONTAINER\tpodman\terp-web\timage:1\tUp\n"
                )
                rapport = detect.parse_probe(entete, champs, texte)
                self.assertEqual(rapport["status"], "yes")
                # Une ligne courte se complète de chaînes vides.
                self.assertEqual(
                    rapport["installs"],
                    [dict(zip(champs, ("/srv/erp", "1.2", "")))],
                )
                self.assertEqual(
                    rapport["containers"],
                    [
                        {
                            "engine": "podman",
                            "name": "erp-web",
                            "image": "image:1",
                            "state": "Up",
                        }
                    ],
                )


class TestSsh(unittest.TestCase):
    def test_each_failure_keeps_its_kind(self):
        for _erp, entete, _champs in ERPS:
            cas = (
                (0, f"{entete}\tno\n", "ok"),
                (255, "user@h: Permission denied (publickey).", "auth"),
                (
                    255,
                    "ssh: Could not resolve hostname h: Name or service",
                    "net",
                ),
                (
                    255,
                    "ssh: connect to host h port 22: Connection timed out",
                    "net",
                ),
                (
                    255,
                    "ssh: connect to host h port 22: Connection refused",
                    "net",
                ),
                (255, "Host key verification failed.", "hostkey"),
                (0, "sh: 1: syntax error", "error"),
            )
            for code, sortie, attendu in cas:
                with self.subTest(entete=entete, sortie=sortie):
                    self.assertEqual(
                        detect.classify(entete, code, sortie), attendu
                    )

    def test_every_state_has_a_label(self):
        self.assertEqual(
            set(detect.STATE_LABELS),
            {"ok", "auth", "hostkey", "net", "error"},
        )

    def test_the_probe_goes_by_stdin_in_one_round_trip(self):
        argv = detect.remote_argv({"target": "hote-a"}, ["/var/www"])
        self.assertEqual(argv[0], "ssh")
        self.assertIn("BatchMode=yes", argv)
        self.assertEqual(argv[-2], "hote-a")
        self.assertEqual(argv[-1], "sh -s -- 7 /var/www")


class TestRunProbe(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.sonde = Path(tmp.name) / "sonde.sh"
        self.sonde.write_text("printf 'ACME\\tno\\n'\n")

    def test_the_probe_is_sent_on_stdin(self):
        code, sortie = detect.run_probe(str(self.sonde), ["sh", "-s"])
        self.assertEqual(code, 0)
        self.assertEqual(sortie.strip(), "ACME\tno")

    def test_a_command_that_does_not_start_is_255(self):
        code, _sortie = detect.run_probe(
            str(self.sonde), ["/chemin/inexistant/sh"]
        )
        self.assertEqual(code, 255)


class TestSave(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)

    def test_a_host_name_cannot_leave_the_inventory(self):
        for erp, _entete, _champs in ERPS:
            with self.subTest(erp=erp):
                detect.save(erp, str(self.racine), "../../x", "ok", None)
                fichiers = list(
                    (self.racine / "private" / erp / "inventory").iterdir()
                )
                self.assertEqual([f.name for f in fichiers], [".._.._x.json"])

    def test_the_report_is_private_to_the_account(self):
        quand = datetime.datetime(2001, 2, 3, 4, 5, 6)
        for erp, _entete, _champs in ERPS:
            with self.subTest(erp=erp):
                chemin = Path(
                    detect.save(
                        erp,
                        str(self.racine),
                        "hote-a",
                        "auth",
                        None,
                        now=quand,
                    )
                )
                self.assertEqual(
                    chemin.parent,
                    self.racine / detect.inventory_dir(erp),
                )
                self.assertEqual(chemin.stat().st_mode & 0o777, 0o600)
                self.assertEqual(chemin.parent.stat().st_mode & 0o777, 0o700)
                self.assertEqual(
                    json.loads(chemin.read_text()),
                    {
                        "host": "hote-a",
                        "state": "auth",
                        "date": "2001-02-03T04:05:06",
                        "report": None,
                    },
                )


if __name__ == "__main__":
    unittest.main()
