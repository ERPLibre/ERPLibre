#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""script/odoo/log_check.py : sources, fenêtres, état, droits, rapport.

Aucun journalctl ni systemctl réel n'est lancé : `FauxSysteme` répond à
systemctl depuis une table et rend une sortie de journalctl fabriquée,
ligne à ligne, avec le code et le stderr demandés. L'état vit dans un
dossier temporaire. Données inventées : unité `erplibre_demo.service`,
base `base_essai`, adresses sous example.org.
"""

import contextlib
import datetime
import io
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.odoo import log_check as lc  # noqa: E402

UNITE = "erplibre_demo.service"
# 2026-03-01 12:00:00, heure locale.
HORLOGE = datetime.datetime(2026, 3, 1, 12, 0, 0).timestamp()
CURSEUR = "s=0123abcd;i=2a;b=ef01;m=99;t=5f;x=77"


def ligne_journal(odoo, heure="2026-03-01T11:00:00+0000"):
    return f"{heure} hote odoo-bin[4242]: {odoo}"


def entete(niveau, message, logger="odoo.http", heure="11:00:00"):
    return (
        f"2026-03-01 {heure},000 4242 {niveau} base_essai {logger}: {message}"
    )


INFO = entete("INFO", "HTTP service running")
ERREUR = entete(
    "ERROR", "Failed to load module x_demo", "odoo.modules.loading"
)
TRACE = [
    entete("ERROR", "Exception during request handling"),
    "Traceback (most recent call last):",
    '  File "/srv/odoo/odoo/http.py", line 10, in dispatch',
    "    raise KeyError('x')",
    "KeyError: 'x'",
]


def courriel(mid, classe, detail):
    return [
        entete(
            "ERROR",
            f"failed sending mail (id: {mid}) due to Mail Delivery Failed",
            "odoo.addons.mail.models.mail_mail",
        ),
        "Traceback (most recent call last):",
        '  File "/srv/odoo/odoo/addons/base/models/ir_mail_server.py",'
        " line 769, in send_email",
        f"smtplib.{classe}: {detail}",
        "",
        "During handling of the above exception, another exception occurred:",
        "",
        "Traceback (most recent call last):",
        "odoo.addons.base.models.ir_mail_server.MailDeliveryException:"
        f" ('Mail Delivery Failed', \"Mail delivery failed via SMTP server"
        f" 'None'.\\n{classe}: {detail}\")",
    ]


class FauxSysteme(lc.Systeme):
    def __init__(self, wd):
        super().__init__()
        self.wd = wd
        self.appels = []
        self.sortie = []
        self.code = 0
        self.stderr = ""
        self.tue = False
        self.unites = [(UNITE, True)]
        self.options_execstart = ""

    def maintenant(self):
        return HORLOGE

    def lanceur(self, argv, timeout=60):
        self.appels.append(list(argv))
        if argv[:2] == ["systemctl", "list-units"]:
            return 0, "".join(
                f"{nom} loaded {'active' if actif else 'inactive'} running x\n"
                for nom, actif in self.unites
            )
        if argv[:2] == ["systemctl", "show"]:
            return 0, (
                "LoadState=loaded\nActiveState=active\nUser=demo\n"
                f"WorkingDirectory={self.wd}\n"
                "ExecStart={ path=/bin/bash ; argv[]=/bin/bash"
                f" {self.wd}/run.sh{self.options_execstart} ;"
                " ignore_errors=no }\n"
                "Environment=\n"
            )
        return 1, "commande inattendue"

    def lire_journal(self, argv, recevoir, delai):
        self.appels.append(list(argv))
        for ligne in self.sortie:
            recevoir(ligne)
        return self.code, self.stderr, self.tue


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.bac = os.path.realpath(d.name)
        self.wd = os.path.join(self.bac, "odoo")
        os.makedirs(self.wd)
        with open(os.path.join(self.wd, "run.sh"), "w") as f:
            f.write("#!/bin/bash\n")
        self.conf = os.path.join(self.wd, "config.conf")
        with open(self.conf, "w") as f:
            f.write("[options]\ndb_name = base_essai\n")
        self.etat = os.path.join(self.bac, "etat")
        self.systeme = FauxSysteme(self.wd)

    def journal(self, lignes, curseur=CURSEUR):
        self.systeme.sortie = [ligne_journal(x) for x in lignes]
        if curseur:
            self.systeme.sortie.append(f"-- cursor: {curseur}")

    def lancer(self, *options, service=True):
        argv = (["--service", UNITE] if service else []) + [
            "--state-dir",
            self.etat,
        ]
        argv += list(options)
        flux, erreurs = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(erreurs):
            code = lc.main(argv, self.systeme, flux)
        self.sortie, self.erreurs = flux.getvalue(), erreurs.getvalue()
        return code

    def json(self, *options, **kw):
        code = self.lancer("--json", *options, **kw)
        donnees = json.loads(self.sortie)
        self.assertEqual(donnees["exit_code"], code)
        return code, donnees

    def journalctl(self):
        return [a for a in self.systeme.appels if a[0] == "journalctl"]

    def fichier_etat(self):
        return os.path.join(self.etat, UNITE + ".json")


class TestRapport(Base):
    def test_c1_rien_que_de_l_info(self):
        self.journal([INFO, INFO])
        self.assertEqual(self.lancer(), lc.CODE_RIEN, self.erreurs)
        self.assertIn(lc.t("Nothing to review."), self.sortie)
        code, donnees = self.json()
        self.assertEqual((code, donnees["to_review"]), (0, 0))
        self.assertEqual(donnees["records"], 2)

    def test_c2_trace_et_erreur(self):
        self.journal([INFO] + TRACE + [ERREUR])
        self.assertEqual(self.lancer(), lc.CODE_A_REVOIR)
        self.assertIn("[1x] KeyError: 'x'", self.sortie)
        self.assertIn("Failed to load module x_demo", self.sortie)
        self.assertIn("[1] ", self.sortie)
        self.assertIn("[2] ", self.sortie)
        _code, donnees = self.json()
        self.assertEqual(donnees["to_review"], 2)
        self.assertEqual(donnees["tracebacks"][0]["headline"], "KeyError: 'x'")
        self.assertEqual(
            donnees["errors"][0]["key"],
            "odoo.modules.loading: Failed to load module x_demo",
        )

    def test_c11_section_courriel(self):
        lignes = []
        for i in range(5):
            lignes += courriel(
                7404 + i,
                "SMTPDataError",
                "(452, b'4.4.5 Maximum number of messages per session"
                " exceeded')",
            )
        for i in range(4):
            lignes += courriel(
                7409 + i,
                "SMTPSenderRefused",
                "(503, b'5.5.1 Multiple MAIL commands not allowed',"
                " 'admin@example.org')",
            )
        lignes += courriel(
            7413,
            "SMTPDataError",
            "(550, b'You are not allowed to send emails as"
            ' \\"a@example.org\\" (header From) while using'
            ' \\"b@example.org\\" as envelope sender\')',
        )
        for i in range(7):
            lignes += courriel(
                7500 + i,
                "SMTPDataError",
                "(452, b'4.4.5 Maximum number of messages per session"
                " exceeded')",
            )
        lignes += courriel(
            7600,
            "SMTPAuthenticationError",
            "(535, b'5.7.8 Username and Password not accepted')",
        )
        self.journal(lignes)
        self.assertEqual(self.lancer(), lc.CODE_A_REVOIR)
        self.assertIn(
            "[12x] " + lc.t(lc.mail_diagnostic.PAR_ID["rate_limit"].libelle),
            self.sortie,
        )
        self.assertIn(lc.t("PERMANENT"), self.sortie)
        self.assertIn(lc.t("transient"), self.sortie)
        self.assertIn("+2", self.sortie)
        self.assertIn("mail_retry.py", self.sortie)
        self.assertIn("mail.session.batch.size", self.sortie)
        _code, donnees = self.json()
        par_classe = {m["class"]: m for m in donnees["mail"]}
        self.assertEqual(
            {c: m["count"] for c, m in par_classe.items()},
            {"rate_limit": 12, "cascade_503": 4, "sender": 1, "auth": 1},
        )
        ids = par_classe["rate_limit"]["mail_ids"]
        self.assertEqual(ids, sorted(ids))
        self.assertTrue(par_classe["auth"]["permanent"])
        self.assertFalse(par_classe["rate_limit"]["permanent"])
        # Chaque échec reste une trace : compté une fois à revoir.
        self.assertEqual(donnees["to_review"], 18)
        self.assertEqual(sum(g["count"] for g in donnees["tracebacks"]), 18)

    def test_c12_ignore(self):
        bruit = entete("ERROR", "boom", "odoo.addons.web.controllers.main")
        self.journal([bruit])
        self.assertEqual(
            self.lancer("--ignore", r"odoo\.addons\.web\.controllers"),
            lc.CODE_RIEN,
        )
        self.assertIn("--ignore", self.sortie)
        with self.assertRaises(SystemExit) as fin:
            self.lancer("--ignore", "(")
        self.assertEqual(fin.exception.code, 2)

    def test_c13_json_seul_sur_stdout(self):
        self.journal(TRACE)
        code, donnees = self.json("--last", "2")
        self.assertEqual(code, 1)
        self.assertEqual(
            list(donnees),
            [
                "version",
                "source",
                "window",
                "records",
                "to_review",
                "tracebacks",
                "errors",
                "sql",
                "mail",
                "ignored",
                "by_hour",
                "state",
                "exit_code",
            ],
        )
        self.assertEqual(donnees["source"]["unit"], UNITE)
        self.assertEqual(donnees["window"]["mode"], "last-hours")

    def test_bruit_connu_compte_a_part(self):
        self.journal(
            [
                entete(
                    "ERROR",
                    ".map should have been generated through debug assets,"
                    " (version 0a1b2c3 most likely outdated)",
                    "odoo.addons.web.controllers.binary",
                )
            ]
        )
        self.assertEqual(self.lancer(), lc.CODE_RIEN)
        self.assertIn(lc.t(lc.LIBELLES_BRUIT["sourcemap"]), self.sortie)


class TestDroitsEtEchecs(Base):
    def test_c3_journalctl_en_echec(self):
        self.systeme.code = 1
        self.systeme.stderr = "Unit erplibre_demo.service not found."
        self.assertEqual(self.lancer("--since-last"), lc.CODE_REFUS)
        self.assertIn("not found", self.erreurs)
        self.assertFalse(os.path.exists(self.fichier_etat()))

    def test_c4_compte_sans_droit_de_lecture(self):
        self.systeme.stderr = (
            "Hint: You are currently not seeing messages from other users"
            " and the system.\n"
        )
        self.assertEqual(self.lancer("--since-last"), lc.CODE_REFUS)
        self.assertIn("systemd-journal", self.erreurs)
        self.assertIn("sudo", self.erreurs)
        self.assertFalse(os.path.exists(self.fichier_etat()))
        code, donnees = self.json("--since-last")
        self.assertEqual(code, 2)
        self.assertIn("error", donnees)

    def test_c4_sous_le_compte_de_l_unite(self):
        """Le compte de l'unité voit les messages de l'unité malgré
        l'avertissement : la lecture est admise si elle rend quelque
        chose, refusée si elle est vide."""
        self.systeme.stderr = (
            "Hint: You are currently not seeing messages from other users"
            " and the system.\n"
        )
        with mock.patch.object(
            self.systeme, "utilisateur_courant", return_value="demo"
        ):
            self.journal(TRACE)
            self.assertEqual(self.lancer("--since-last"), lc.CODE_A_REVOIR)
            self.assertTrue(os.path.exists(self.fichier_etat()))
            self.journal([], curseur=None)
            self.assertEqual(self.lancer("--last", "1"), lc.CODE_REFUS)

    def test_journalctl_absent_ou_trop_long(self):
        self.systeme.code, self.systeme.stderr = 127, "No such file"
        self.assertEqual(self.lancer(), lc.CODE_REFUS)
        self.systeme.code, self.systeme.tue = 0, True
        self.assertEqual(self.lancer(), lc.CODE_REFUS)
        self.assertIn("--timeout", self.erreurs)

    def test_c14_unite_ambigue_et_options_exclusives(self):
        self.systeme.unites = [
            ("erplibre_a.service", True),
            ("erplibre_b.service", True),
        ]
        self.assertEqual(self.lancer(service=False), lc.CODE_REFUS)
        self.assertIn("erplibre_a.service", self.erreurs)
        self.assertIn("erplibre_b.service", self.erreurs)
        with self.assertRaises(SystemExit) as fin:
            self.lancer("--file", "/tmp/x.log")
        self.assertEqual(fin.exception.code, 2)


class TestIncremental(Base):
    def test_c5_premiere_lecture_puis_reprise(self):
        self.journal([INFO])
        self.assertEqual(self.lancer("--since-last"), lc.CODE_RIEN)
        (argv,) = self.journalctl()
        self.assertIn("--since", argv)
        self.assertEqual(
            argv[argv.index("--since") + 1], f"@{int(HORLOGE - 24 * 3600)}"
        )
        self.assertIn("--show-cursor", argv)
        self.assertIn(lc.t("First run: last 24 h."), self.sortie)
        with open(self.fichier_etat()) as f:
            etat = json.load(f)
        self.assertEqual(etat["cursor"], CURSEUR)
        self.assertEqual(etat["unit"], UNITE)
        self.assertEqual(os.listdir(self.etat), [UNITE + ".json"])
        self.journal([INFO], curseur="s=suivant")
        self.lancer("--since-last")
        argv = self.journalctl()[-1]
        self.assertEqual(argv[argv.index("--after-cursor") + 1], CURSEUR)
        self.assertNotIn("--since", argv)
        with open(self.fichier_etat()) as f:
            self.assertEqual(json.load(f)["cursor"], "s=suivant")

    def test_c5_sans_nouvelle_entree_le_curseur_reste(self):
        self.journal([INFO])
        self.lancer("--since-last")
        self.journal([], curseur=None)
        self.lancer("--since-last")
        with open(self.fichier_etat()) as f:
            self.assertEqual(json.load(f)["cursor"], CURSEUR)

    def test_c5_etat_en_lien_symbolique(self):
        os.makedirs(self.etat)
        ailleurs = os.path.join(self.bac, "ailleurs.json")
        with open(ailleurs, "w") as f:
            json.dump({"cursor": "s=piege"}, f)
        os.symlink(ailleurs, self.fichier_etat())
        self.journal(TRACE)
        code, donnees = self.json("--since-last")
        self.assertEqual(code, lc.CODE_A_REVOIR)
        self.assertFalse(donnees["state"]["saved"])
        self.assertIn(self.fichier_etat(), donnees["state"]["reason"])
        self.assertNotIn("--after-cursor", self.journalctl()[-1])
        with open(ailleurs) as f:
            self.assertEqual(json.load(f), {"cursor": "s=piege"})
        self.lancer("--since-last")
        self.assertIn(
            lc.t("Position not saved: {reason}").split("{")[0], self.sortie
        )

    def test_c6_dossier_d_etat_non_inscriptible(self):
        if os.geteuid() == 0:
            self.skipTest("root écrit partout")
        os.makedirs(self.etat)
        os.chmod(self.etat, stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(os.chmod, self.etat, 0o755)
        self.journal(TRACE)
        self.assertEqual(self.lancer("--since-last"), lc.CODE_A_REVOIR)
        self.assertIn("KeyError", self.sortie)
        self.assertIn(
            lc.t("Position not saved: {reason}").split("{")[0], self.sortie
        )
        self.journal([INFO])
        self.assertEqual(self.lancer("--since-last"), lc.CODE_RIEN)

    def test_c7_fenetres(self):
        os.makedirs(self.etat)
        with open(self.fichier_etat(), "w") as f:
            json.dump({"unit": UNITE, "cursor": CURSEUR}, f)
        avant = os.stat(self.fichier_etat()).st_mtime_ns
        self.journal([INFO])
        self.lancer("--last", "6")
        argv = self.journalctl()[-1]
        self.assertEqual(
            argv[argv.index("--since") + 1], f"@{int(HORLOGE - 6 * 3600)}"
        )
        self.assertNotIn("--after-cursor", argv)
        self.assertEqual(os.stat(self.fichier_etat()).st_mtime_ns, avant)
        self.lancer(
            "--since", "2026-03-01 08:00", "--until", "2026-03-01 12:00"
        )
        argv = self.journalctl()[-1]
        debut = int(time.mktime((2026, 3, 1, 8, 0, 0, 0, 0, -1)))
        fin = int(time.mktime((2026, 3, 1, 12, 0, 0, 0, 0, -1)))
        self.assertEqual(argv[argv.index("--since") + 1], f"@{debut}")
        self.assertEqual(argv[argv.index("--until") + 1], f"@{fin}")
        self.assertEqual(self.lancer("--since", "hier"), lc.CODE_REFUS)
        with self.assertRaises(SystemExit):
            self.lancer("--until", "2026-03-01")

    def test_sans_fenetre_les_dernieres_24_h(self):
        self.journal([INFO])
        self.lancer()
        argv = self.journalctl()[-1]
        self.assertEqual(
            argv[argv.index("--since") + 1], f"@{int(HORLOGE - 24 * 3600)}"
        )
        self.assertFalse(os.path.exists(self.etat))


class TestFichier(Base):
    def heure(self, delta_heures):
        """Une heure d'en-tête Odoo (UTC) à `delta_heures` de l'horloge."""
        moment = datetime.datetime.fromtimestamp(
            HORLOGE + delta_heures * 3600, datetime.timezone.utc
        )
        return moment.strftime("%Y-%m-%d %H:%M:%S")

    def ligne(self, delta, niveau="ERROR", message="boom"):
        return f"{self.heure(delta)},000 7 {niveau} base_essai odoo.http: {message}\n"

    def test_c8_fichier_incremental(self):
        journal_odoo = os.path.join(self.bac, "odoo.log")
        with open(journal_odoo, "w") as f:
            f.write(self.ligne(-48, message="trop vieux"))
            f.write(self.ligne(-1, message="récent"))
        code, donnees = self.json(
            "--file", journal_odoo, "--since-last", service=False
        )
        self.assertEqual(code, 1)
        self.assertEqual(donnees["to_review"], 1)
        self.assertIn("récent", donnees["errors"][0]["key"])
        self.assertEqual(self.journalctl(), [])
        (nom,) = os.listdir(self.etat)
        with open(os.path.join(self.etat, nom)) as f:
            etat = json.load(f)
        self.assertEqual(etat["offset"], os.path.getsize(journal_odoo))
        self.assertEqual(etat["inode"], os.stat(journal_odoo).st_ino)
        with open(journal_odoo, "a") as f:
            f.write(self.ligne(0, message="nouveau"))
            f.write(self.ligne(0, "INFO", "sans fin de ligne").rstrip("\n"))
        code, donnees = self.json(
            "--file", journal_odoo, "--since-last", service=False
        )
        self.assertEqual(donnees["to_review"], 1)
        self.assertIn("nouveau", donnees["errors"][0]["key"])
        self.assertEqual(donnees["records"], 1)
        # Remplacé par un fichier PLUS LONG que l'offset retenu, sous un
        # autre inode (les deux existent au moment du renommage) : seul
        # l'inode dit la rotation. Relu depuis le début, et dit.
        neuf = journal_odoo + ".neuf"
        with open(neuf, "w") as f:
            f.write(self.ligne(0, message="après rotation"))
            for i in range(20):
                f.write(self.ligne(0, "INFO", f"remplissage {i}"))
        self.assertGreater(
            os.path.getsize(neuf), os.path.getsize(journal_odoo)
        )
        os.replace(neuf, journal_odoo)
        self.lancer("--file", journal_odoo, "--since-last", service=False)
        self.assertIn("après rotation", self.sortie)
        self.assertIn(
            lc.t(
                "{path} was rotated or truncated: read from the start."
            ).format(path=journal_odoo),
            self.sortie,
        )

    def test_c8_etat_d_un_autre_chemin(self):
        """Un état qui nomme un autre fichier ne donne pas son offset :
        lecture des dernières 24 h."""
        journal_odoo = os.path.join(self.bac, "odoo.log")
        with open(journal_odoo, "w") as f:
            f.write(self.ligne(-48, message="trop vieux"))
            f.write(self.ligne(-1, message="récent"))
        self.lancer("--file", journal_odoo, "--since-last", service=False)
        (nom,) = os.listdir(self.etat)
        chemin = os.path.join(self.etat, nom)
        with open(chemin) as f:
            etat = json.load(f)
        etat["path"] = os.path.join(self.bac, "autre.log")
        with open(chemin, "w") as f:
            json.dump(etat, f)
        code, donnees = self.json(
            "--file", journal_odoo, "--since-last", service=False
        )
        self.assertEqual((code, donnees["records"]), (1, 1))
        self.assertIn("récent", donnees["errors"][0]["key"])
        self.assertEqual(
            donnees["source"]["notes"], [lc.t("First run: last 24 h.")]
        )

    def test_c8_fichier_illisible(self):
        self.assertEqual(
            self.lancer(
                "--file", os.path.join(self.bac, "absent.log"), service=False
            ),
            lc.CODE_REFUS,
        )

    def test_c9_logfile_de_la_configuration(self):
        journal_odoo = os.path.join(self.wd, "odoo.log")
        with open(journal_odoo, "w") as f:
            f.write(self.ligne(-1))
        with open(self.conf, "a") as f:
            f.write("logfile = odoo.log\n")
        code, donnees = self.json(service=False)
        self.assertEqual(code, 1)
        self.assertEqual(donnees["source"]["kind"], "file")
        self.assertEqual(donnees["source"]["path"], journal_odoo)
        self.assertEqual(donnees["source"]["unit"], UNITE)
        self.assertEqual(self.journalctl(), [])

    def test_c10_matrice_horaire(self):
        self.journal(TRACE)
        self.assertEqual(self.lancer("--by-hour", "--days", "3"), 1)
        argv = self.journalctl()[-1]
        self.assertEqual(
            argv[argv.index("--since") + 1], f"@{int(HORLOGE - 3 * 86400)}"
        )
        self.assertNotIn("--after-cursor", argv)
        self.assertIn("[6] ", self.sortie)
        self.assertIn("█", self.sortie)
        self.assertFalse(os.path.exists(self.etat))
        for jours in ("0", "4000"):
            with self.subTest(jours=jours):
                with self.assertRaises(SystemExit) as fin:
                    self.lancer("--by-hour", "--days", jours)
                self.assertEqual(fin.exception.code, 2)


class TestConfigurationIllisible(Base):
    """Sans configuration lisible, un `logfile` qu'elle poserait laisse le
    journal sans ligne d'Odoo : « rien à revoir » serait faux."""

    def refuser_config(self):
        rustine = mock.patch.object(
            lc.service,
            "detecter_config",
            side_effect=lc.Refus(
                "Cannot read {path}: run with sudo.", path=self.conf
            ),
        )
        rustine.start()
        self.addCleanup(rustine.stop)

    def test_journal_sans_odoo_refuse(self):
        self.refuser_config()
        self.systeme.sortie = [
            "2026-03-01T11:00:00+0000 hote systemd[1]: Started demo."
        ]
        self.assertEqual(self.lancer("--last", "24"), lc.CODE_REFUS)
        self.assertIn(self.conf, self.erreurs)
        self.assertIn("sudo", self.erreurs)
        self.assertNotIn(lc.t("Nothing to review."), self.sortie)
        code, donnees = self.json("--since-last")
        self.assertEqual(code, lc.CODE_REFUS)
        self.assertIn("logfile", donnees["error"])
        self.assertFalse(os.path.exists(self.fichier_etat()))

    def test_journal_avec_odoo_lu_et_note_en_json(self):
        self.refuser_config()
        self.journal(TRACE)
        code, donnees = self.json()
        self.assertEqual(code, lc.CODE_A_REVOIR)
        self.assertEqual(donnees["source"]["kind"], "journal")
        (note,) = donnees["source"]["notes"]
        self.assertIn(self.conf, note)

    def test_logfile_d_execstart(self):
        self.refuser_config()
        journal_odoo = os.path.join(self.bac, "odoo.log")
        with open(journal_odoo, "w") as f:
            f.write(entete("ERROR", "boom", heure="11:30:00") + "\n")
        self.systeme.options_execstart = f" --logfile={journal_odoo}"
        code, donnees = self.json("--since", "2026-03-01")
        self.assertEqual(code, lc.CODE_A_REVOIR)
        self.assertEqual(donnees["source"]["kind"], "file")
        self.assertEqual(donnees["source"]["path"], journal_odoo)
        self.assertEqual(self.journalctl(), [])


class TestEtatAbime(Base):
    def test_valeurs_illisibles_valent_une_premiere_lecture(self):
        os.makedirs(self.etat)
        for etat in (
            {"unit": UNITE, "updated": "hier"},
            {"unit": UNITE, "updated": None, "cursor": 12},
            {"unit": UNITE, "updated": -5},
        ):
            with self.subTest(etat=etat):
                with open(self.fichier_etat(), "w") as f:
                    json.dump(etat, f)
                self.journal([INFO])
                self.assertEqual(self.lancer("--since-last"), lc.CODE_RIEN)
                argv = self.journalctl()[-1]
                self.assertEqual(
                    argv[argv.index("--since") + 1],
                    f"@{int(HORLOGE - 24 * 3600)}",
                )
                self.assertNotIn("--after-cursor", argv)

    def test_reprise_depuis_updated_sans_curseur(self):
        os.makedirs(self.etat)
        moment = int(HORLOGE - 3 * 3600)
        with open(self.fichier_etat(), "w") as f:
            json.dump({"unit": UNITE, "updated": moment}, f)
        self.journal([INFO])
        self.lancer("--since-last")
        argv = self.journalctl()[-1]
        self.assertEqual(argv[argv.index("--since") + 1], f"@{moment}")
        self.assertNotIn(lc.t("First run: last 24 h."), self.sortie)

    def test_offset_illisible_dans_un_fichier(self):
        journal_odoo = os.path.join(self.bac, "odoo.log")
        with open(journal_odoo, "w") as f:
            f.write(entete("ERROR", "boom", heure="11:30:00") + "\n")
        self.lancer("--file", journal_odoo, "--since-last", service=False)
        (nom,) = os.listdir(self.etat)
        chemin = os.path.join(self.etat, nom)
        for offset, inode in (("x", None), (None, "y"), (-1, 0)):
            with self.subTest(offset=offset, inode=inode):
                with open(chemin) as f:
                    etat = json.load(f)
                etat.update(offset=offset, inode=inode)
                with open(chemin, "w") as f:
                    json.dump(etat, f)
                code = self.lancer(
                    "--file", journal_odoo, "--since-last", service=False
                )
                self.assertIn(code, (lc.CODE_RIEN, lc.CODE_A_REVOIR))


class TestImprevus(Base):
    def test_date_impossible_ne_fait_pas_echouer(self):
        journal_odoo = os.path.join(self.bac, "odoo.log")
        with open(journal_odoo, "w") as f:
            f.write(entete("ERROR", "boom", heure="11:30:00") + "\n")
            f.write("2026-02-30 03:00:00,123 4242 INFO db odoo.y: date\n")
        code, donnees = self.json(
            "--file", journal_odoo, "--since", "2026-01-01", service=False
        )
        self.assertEqual(code, lc.CODE_A_REVOIR)
        self.assertEqual(donnees["records"], 1)
        self.assertEqual(len(donnees["errors"][0]["sample"]), 2)

    def test_erreur_imprevue_rend_2(self):
        def casser(*_a, **_k):
            raise RuntimeError("panne inventée")

        self.systeme.lire_journal = casser
        self.assertEqual(self.lancer(), lc.CODE_REFUS)
        self.assertIn("panne inventée", self.erreurs)
        code, donnees = self.json()
        self.assertEqual(code, lc.CODE_REFUS)
        self.assertIn("panne inventée", donnees["error"])

    def test_ctrl_c_rend_130(self):
        def interrompre(*_a, **_k):
            raise KeyboardInterrupt

        self.systeme.lire_journal = interrompre
        self.assertEqual(self.lancer(), lc.CODE_INTERROMPU)


class TestFenetreDuFichier(Base):
    def setUp(self):
        super().setUp()
        self.journal_odoo = os.path.join(self.bac, "odoo.log")
        with open(self.journal_odoo, "w") as f:
            for delta in (-5, -1, 1):
                moment = datetime.datetime.fromtimestamp(
                    HORLOGE + delta * 3600, datetime.timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S")
                f.write(
                    f"{moment},000 7 ERROR base_essai odoo.http: à {delta} h\n"
                )

    def test_last(self):
        code, donnees = self.json(
            "--file", self.journal_odoo, "--last", "2", service=False
        )
        self.assertEqual((code, donnees["records"]), (1, 2))
        cles = sorted(e["key"] for e in donnees["errors"])
        self.assertTrue(all("-5" not in c for c in cles), cles)

    def test_since_until_borne_exclue(self):
        debut = datetime.datetime.fromtimestamp(HORLOGE - 2 * 3600)
        fin = datetime.datetime.fromtimestamp(HORLOGE + 1 * 3600)
        code, donnees = self.json(
            "--file",
            self.journal_odoo,
            "--since",
            debut.strftime("%Y-%m-%d %H:%M"),
            "--until",
            fin.strftime("%Y-%m-%d %H:%M"),
            service=False,
        )
        # L'enregistrement à +1 h tombe SUR la borne de fin : exclu.
        self.assertEqual((code, donnees["records"]), (1, 1))
        self.assertIn("N h", donnees["errors"][0]["key"])


class TestAffichage(Base):
    def test_top_et_groupes_en_plus(self):
        self.journal(
            [entete("ERROR", f"panne {chr(97 + i)}") for i in range(17)]
        )
        self.lancer()
        self.assertEqual(self.sortie.count("[1x] odoo.http: panne"), 15)
        self.assertIn(
            lc.t("+{count} more group(s) (--top).").format(count=2),
            self.sortie,
        )
        self.lancer("--top", "3")
        self.assertEqual(self.sortie.count("[1x] odoo.http: panne"), 3)

    def test_trace_complete(self):
        cadres = []
        for i in range(30):
            cadres += [f'  File "/srv/m{i}.py", line {i}, in f', "    f()"]
        self.journal(
            [entete("ERROR", "boom"), "Traceback (most recent call last):"]
            + cadres
            + ["ValueError: fin"]
        )
        self.lancer()
        self.assertNotIn("m29.py", self.sortie)
        self.lancer("--full-trace")
        self.assertIn("m29.py", self.sortie)
        self.assertIn("| ValueError: fin", self.sortie)

    def test_niveaux_et_courriels(self):
        self.journal(
            [
                entete("CRITICAL", "Failed to initialize database"),
                entete(
                    "WARNING",
                    "Mail delivery failed via SMTP server 'None'."
                    " SMTPAuthenticationError: (535, b'5.7.8 refused')",
                    "odoo.addons.base.models.ir_mail_server",
                ),
                entete(
                    "ERROR",
                    "Exception while processing mail with ID 42:"
                    " SMTPServerDisconnected: Connection unexpectedly closed",
                    "odoo.addons.mail.models.mail_mail",
                ),
            ]
        )
        code, donnees = self.json()
        self.assertEqual(code, 1)
        # CRITICAL et ERROR à revoir ; le WARNING de courriel, classé, non.
        self.assertEqual(donnees["to_review"], 2)
        par_classe = {m["class"]: m for m in donnees["mail"]}
        self.assertIn("auth", par_classe)
        self.assertTrue(
            any(42 in m["mail_ids"] for m in donnees["mail"]), donnees["mail"]
        )

    def test_trace_sql_marquee(self):
        self.journal(
            [
                entete("ERROR", "Exception during request handling"),
                "Traceback (most recent call last):",
                '  File "/srv/odoo/odoo/sql_db.py", line 1, in execute',
                "psycopg2.errors.UniqueViolation: duplicate key value",
            ]
            + TRACE
        )
        _code, donnees = self.json()
        par_titre = {g["headline"]: g["sql"] for g in donnees["tracebacks"]}
        self.assertTrue(
            par_titre["psycopg2.errors.UniqueViolation: duplicate key value"]
        )
        self.assertFalse(par_titre["KeyError: 'x'"])


class TestLectureSeule(Base):
    def test_c16_seulement_systemctl_et_journalctl(self):
        self.journal(TRACE)
        self.lancer("--since-last", service=False)
        for argv in self.systeme.appels:
            with self.subTest(argv=argv):
                self.assertIn(argv[0], ("systemctl", "journalctl"))
                if argv[0] == "systemctl":
                    self.assertIn(argv[1], ("show", "list-units"))
        self.assertEqual(os.listdir(self.etat), [UNITE + ".json"])

    def test_morceleur_coupe_une_ligne_demesuree(self):
        lignes = []
        decoupe = lc.Morceleur(lignes.append)
        decoupe(b"a\n" + b"x" * 70000)
        decoupe(b"y" * 70000 + b"\nb\nfin")
        decoupe.finir()
        self.assertEqual(lignes[0], "a")
        self.assertEqual(len(lignes[1]), lc.journal.LIGNE_MAX)
        self.assertEqual(lignes[2:], ["b", "fin"])


class TestPython37(unittest.TestCase):
    """C15 : rien au-delà de Python 3.7 dans l'outil et ses bibliothèques."""

    def test_syntaxe(self):
        import ast

        racine = os.path.join(os.path.dirname(__file__), "..")
        for chemin in (
            "script/odoo/log_check.py",
            "script/lib_ops/journal.py",
            "script/lib_ops/mail_diagnostic.py",
        ):
            with self.subTest(fichier=chemin):
                with open(os.path.join(racine, chemin), encoding="utf-8") as f:
                    source = f.read()
                ast.parse(source, feature_version=(3, 7))
                self.assertNotIn("shlex.join", source)
                self.assertNotIn("fromisoformat", source)


if __name__ == "__main__":
    unittest.main()
