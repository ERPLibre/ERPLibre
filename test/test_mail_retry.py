#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""script/odoo/mail_retry.py : liste en lecture seule, masquage, causes,
sélection, renvoi par le shell d'Odoo.

Aucune commande réelle n'est lancée : `FauxSysteme` répond à systemctl,
rend un JSON fabriqué à la requête psql et une sortie fabriquée au shell
d'Odoo ; chaque appel est noté avec son environnement. Données inventées :
unité `erplibre_demo.service`, compte `demo`, base `base_essai`, adresses
sous example.org et example.net.
"""

import ast
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import types
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.odoo import mail_retry as mr  # noqa: E402

UNITE = "erplibre_demo.service"
T0 = 1772366400
R452 = (
    "Mail Delivery Failed\nMail delivery failed via SMTP server 'None'.\n"
    "SMTPDataError: (452, b'4.4.5 Maximum number of messages per session"
    " exceeded')"
)
R452_FR = (
    "Échec de l'envoi\nÉchec de l'envoi de l'e-mail via le serveur SMTP"
    " 'None'.\nSMTPDataError: (452, b'4.4.5 Maximum number of messages per"
    " session exceeded')"
)
R550 = (
    "Mail Delivery Failed\nMail delivery failed via SMTP server 'None'.\n"
    "SMTPDataError: (550, b'You are not allowed to send emails as"
    ' "a@example.org" (header From) while using "b@example.org" as'
    " envelope sender')"
)


def echec(mid, decalage, sujet, destinataires, raison, type_echec=None):
    return {
        "id": mid,
        "date": T0 + decalage,
        "subject": sujet,
        "recipients": destinataires,
        "reason": raison,
        "failure_type": type_echec,
    }


ECHECS = [
    echec(7171, -86400 * 20, "Invitation", "x@example.net", R550),
    echec(7404, 0, "Bienvenue", "jean.dupont@example.org", R452),
    echec(7405, 60, "Bienvenue", "marie@example.org", R452_FR),
    echec(
        7406,
        120,
        "Votre inscription",
        "alex@example.org, sam@example.org",
        R452,
    ),
    echec(7500, 180, "Rappel", "", ""),
]


class FauxSysteme(mr.Systeme):
    def __init__(self, wd):
        super().__init__(interactif=False, demander=self._demander)
        self.wd = wd
        self.appels = []
        self.requetes = []
        self.shells = []
        self.euid_valeur = 0
        self.courant = "root"
        self.donnees = {
            "version": "18.0.1.3",
            "batch_size": None,
            "counts": {"sent": 120, "exception": 5},
            "failures": [dict(e) for e in ECHECS],
        }
        self.psql = None
        self.reponse_shell = None
        self.code_shell = 0
        self.reponses = []
        self.questions = []
        self.odoo_bin = True

    def _demander(self, question):
        self.questions.append(question)
        if not self.reponses:
            raise EOFError
        reponse = self.reponses.pop(0)
        if isinstance(reponse, BaseException):
            raise reponse
        return reponse

    def euid(self):
        return self.euid_valeur

    def utilisateur_courant(self):
        return self.courant

    def lanceur(self, argv, timeout=60):
        self.appels.append(list(argv))
        if argv[:2] == ["systemctl", "show"]:
            return 0, (
                "LoadState=loaded\nActiveState=active\nUser=demo\n"
                f"WorkingDirectory={self.wd}\n"
                "ExecStart={ path=/bin/bash ; argv[]=/bin/bash"
                f" {self.wd}/run.sh ; ignore_errors=no }}\n"
                "Environment=LANG=C.UTF-8\n"
            )
        return 1, "commande inattendue"

    def requete(self, argv, env, delai=0):
        self.requetes.append({"argv": list(argv), "env": env})
        if self.psql is not None:
            return self.psql
        return 0, json.dumps(self.donnees) + "\n", ""

    def shell_odoo(self, argv, cwd, source, delai):
        self.shells.append(
            {"argv": list(argv), "cwd": cwd, "source": source, "delai": delai}
        )
        if self.reponse_shell is not None:
            return self.reponse_shell
        ids = ast.literal_eval(source.split("\n", 1)[0].split("=", 1)[1])
        bilan = {
            "requested": ids,
            "requeued": ids,
            "skipped": [],
            "method": "action_retry",
        }
        sortie = "\n".join(
            ["bruit d'Odoo", mr.DEBUT_JSON, json.dumps(bilan), mr.FIN_JSON]
        )
        return self.code_shell, sortie, "journal d'Odoo\n"

    def existe(self, chemin):
        return self.odoo_bin


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.bac = os.path.realpath(d.name)
        self.wd = os.path.join(self.bac, "odoo")
        os.makedirs(self.wd)
        with open(os.path.join(self.wd, "run.sh"), "w") as f:
            f.write("#!/bin/bash\n")
        with open(os.path.join(self.wd, "config.conf"), "w") as f:
            f.write(
                "[options]\ndb_name = base_essai\ndb_password = secret-demo\n"
            )
        self.systeme = FauxSysteme(self.wd)

    def lancer(self, *options):
        argv = ["--service", UNITE] + list(options)
        flux, erreurs = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(erreurs):
            code = mr.main(argv, self.systeme, None, flux)
        self.sortie, self.erreurs = flux.getvalue(), erreurs.getvalue()
        return code

    def ids_envoyes(self):
        (shell,) = self.systeme.shells
        return ast.literal_eval(
            shell["source"].split("\n", 1)[0].split("=", 1)[1]
        )


class TestListe(Base):
    def test_r1_lecture_seule_sous_le_compte(self):
        self.assertEqual(self.lancer(), mr.CODE_RESTE, self.erreurs)
        (requete,) = self.systeme.requetes
        argv, env = requete["argv"], requete["env"]
        self.assertEqual(argv[:4], ["runuser", "-u", "demo", "--"])
        self.assertIn(
            "default_transaction_read_only=on", env.get("PGOPTIONS", "")
        )
        self.assertNotIn("PGOPTIONS", " ".join(argv))
        self.assertEqual(env.get("PGPASSWORD"), "secret-demo")
        self.assertNotIn("secret-demo", " ".join(argv))
        sql = argv[-1]
        self.assertIn("(now() AT TIME ZONE 'UTC') - interval '30 days'", sql)
        for mot in ("UPDATE ", "INSERT ", "DELETE "):
            self.assertNotIn(mot, sql.upper())
        self.assertEqual(self.systeme.shells, [])
        self.lancer("--days", "7")
        self.assertIn(
            "interval '7 days'", self.systeme.requetes[-1]["argv"][-1]
        )

    def test_r1_aucun_echec(self):
        self.systeme.donnees["failures"] = None
        self.assertEqual(self.lancer(), mr.CODE_OK)
        self.assertIn(
            mr.t("No failed mail in the last {days} day(s).").format(days=30),
            self.sortie,
        )

    def test_r2_masquage(self):
        self.assertEqual(
            mr.masquer("jean.dupont@example.org"), "j***@example.org"
        )
        masque = mr.masquer('"Jean Dupont" <jean@example.org>')
        self.assertEqual(masque, "J*** <j***@example.org>")
        self.assertEqual(
            mr.masquer("a@example.org, b@example.net; c@example.org"),
            "a***@example.org, b***@example.net, c***@example.org",
        )
        self.assertEqual(mr.masquer(""), "")
        self.lancer()
        self.assertNotIn("jean.dupont", self.sortie)
        self.assertIn("j***@example.org", self.sortie)
        self.assertIn(mr.t("(no recipient recorded)"), self.sortie)
        self.lancer("--details")
        self.assertIn("jean.dupont@example.org", self.sortie)

    def test_r3_causes(self):
        self.lancer()
        lignes = self.sortie.splitlines()

        def ligne_de(mid):
            rang = next(
                i for i, ligne in enumerate(lignes) if f"#{mid} " in ligne
            )
            return lignes[rang + 1]

        self.assertIn(mr.t("transient"), ligne_de(7404))
        self.assertIn(mr.t("PERMANENT"), ligne_de(7171))
        self.assertIn(mr.t("unknown cause"), ligne_de(7500))
        self.assertNotIn(mr.t("transient"), ligne_de(7500))
        self.assertNotIn(mr.t("PERMANENT"), ligne_de(7500))
        self.assertEqual(
            ligne_de(7405).split("—", 1)[1], ligne_de(7404).split("—", 1)[1]
        )

    def test_r3_type_d_echec(self):
        self.systeme.donnees["failures"] = [
            echec(1, 0, "S", "x@example.org", "", "mail_email_invalid"),
            echec(2, 0, "S", "y@example.org", R452, None),
        ]
        code, donnees = self.json()
        self.assertEqual(code, 1)
        par_id = {f["id"]: f for f in donnees["failures"]}
        self.assertEqual(par_id[1]["class"], "invalid_address")
        self.assertTrue(par_id[1]["permanent"])
        self.assertEqual(par_id[2]["class"], "rate_limit")

    def test_r4_avertissements(self):
        self.lancer()
        self.assertIn("[ATTN]", self.sortie)
        # Odoo 18 lu dans `base` : le réglage nomme le filtre « De ».
        self.assertIn("from_filter", self.sortie)
        douze = [
            echec(8000 + i, i, "S", "x@example.org", R452) for i in range(12)
        ]
        for valeur, attendu in ((None, True), ("10", False), ("500", True)):
            with self.subTest(valeur=valeur):
                self.systeme.donnees["failures"] = douze
                self.systeme.donnees["batch_size"] = valeur
                self.lancer()
                present = "mail.session.batch.size" in self.sortie
                self.assertEqual(present, attendu)
                if valeur == "500":
                    self.assertIn("500", self.sortie)

    def json(self, *options):
        code = self.lancer("--json", *options)
        donnees = json.loads(self.sortie)
        self.assertEqual(donnees["exit_code"], code)
        return code, donnees

    def test_r13_json(self):
        code, donnees = self.json()
        self.assertEqual(
            list(donnees),
            [
                "database",
                "days",
                "failures",
                "counts",
                "batch_size",
                "resend",
                "exit_code",
            ],
        )
        self.assertEqual(code, 1)
        self.assertIsNone(donnees["resend"])
        self.assertNotIn("jean.dupont", self.sortie)
        self.assertEqual(
            list(donnees["failures"][0]),
            [
                "id",
                "date",
                "subject",
                "recipients",
                "cause",
                "class",
                "permanent",
            ],
        )
        _code, donnees = self.json("--details")
        self.assertIn("jean.dupont@example.org", self.sortie)


class TestCauseMasquee(Base):
    """La raison d'un refus de destinataire nomme l'adresse : sans
    `--details`, elle ne sort ni au texte ni en JSON."""

    REFUS_554 = (
        "SMTPRecipientsRefused: {'marie.curie@example.org': (554,"
        " b'5.7.0 policy')}"
    )
    REFUS_550 = (
        "SMTPRecipientsRefused: {'jean.dupont@example.org': (550,"
        " b'5.1.1 <jean.dupont@example.org>: user unknown')}"
    )

    def setUp(self):
        super().setUp()
        self.systeme.donnees["failures"] = [
            echec(1, 0, "S", "marie.curie@example.org", self.REFUS_554),
            echec(2, 60, "S", "jean.dupont@example.org", self.REFUS_550),
        ]

    def test_texte_et_json_sans_details(self):
        self.assertEqual(self.lancer(), mr.CODE_RESTE)
        for nom in ("marie.curie", "jean.dupont"):
            self.assertNotIn(nom, self.sortie)
        self.assertIn("{'m***@example.org': (554", self.sortie)
        self.assertEqual(self.sortie.count("{'m***@example.org'"), 2)
        self.lancer("--json")
        for nom in ("marie.curie", "jean.dupont"):
            self.assertNotIn(nom, self.sortie)
        donnees = json.loads(self.sortie)
        par_id = {f["id"]: f for f in donnees["failures"]}
        self.assertIn("m***@example.org", par_id[1]["cause"])
        self.assertIn("j***@example.org", par_id[2]["cause"])

    def test_details_montre_tout(self):
        self.lancer("--details")
        self.assertIn("{'marie.curie@example.org': (554", self.sortie)
        self.lancer("--json", "--details")
        donnees = json.loads(self.sortie)
        self.assertIn(
            "marie.curie@example.org", donnees["failures"][0]["cause"]
        )
        self.assertIn(
            "jean.dupont@example.org", donnees["failures"][1]["cause"]
        )

    def test_masquer_texte(self):
        self.assertEqual(
            mr.masquer_texte("a jean@example.org, <b@example.net> fin"),
            "a j***@example.org, <b***@example.net> fin",
        )
        self.assertEqual(mr.masquer_texte(""), "")


class TestSelection(Base):
    def test_r5_tous(self):
        self.assertEqual(self.lancer("--resend", "all", "--yes"), mr.CODE_OK)
        self.assertEqual(self.ids_envoyes(), [7171, 7404, 7405, 7406, 7500])

    def test_r5_les_plus_anciens(self):
        self.lancer("--resend", "oldest", "2", "--yes")
        self.assertEqual(self.ids_envoyes(), [7171, 7404])

    def test_r5_ids(self):
        self.assertEqual(
            self.lancer("--resend", "ids", "7405,7406", "--yes"), mr.CODE_OK
        )
        self.assertEqual(self.ids_envoyes(), [7405, 7406])

    def test_r5_id_absent_de_la_liste(self):
        self.assertEqual(
            self.lancer("--resend", "ids", "99999", "--yes"), mr.CODE_RESTE
        )
        self.assertEqual(self.systeme.shells, [])
        self.assertIn("#99999", self.sortie)
        self.assertEqual(
            self.lancer("--resend", "ids", "7404,99999", "--yes"),
            mr.CODE_RESTE,
        )
        self.assertEqual(self.ids_envoyes(), [7404])

    def test_r5_ids_invalides(self):
        for valeur in (["ids", "x,1"], ["oldest", "0"], ["toutes"]):
            with self.subTest(valeur=valeur):
                with self.assertRaises(SystemExit) as fin:
                    self.lancer("--resend", *valeur)
                self.assertEqual(fin.exception.code, 2)

    def test_r6_sans_yes_hors_terminal(self):
        self.assertEqual(self.lancer("--resend", "all"), mr.CODE_RESTE)
        self.assertEqual(self.systeme.shells, [])
        self.assertIn("--yes", self.sortie)
        self.assertEqual(self.lancer("--yes"), mr.CODE_RESTE)
        self.assertEqual(self.systeme.shells, [])

    def test_r7_menu(self):
        self.systeme.interactif = True
        for reponses, attendus in (
            (["a"], [7171, 7404, 7405, 7406, 7500]),
            (["o", "3"], [7171, 7404, 7405]),
            (["i", "7404, 7406"], [7404, 7406]),
        ):
            with self.subTest(reponses=reponses):
                self.systeme.shells = []
                self.systeme.reponses = list(reponses)
                self.lancer()
                self.assertEqual(self.ids_envoyes(), attendus)
        for reponses in (
            [""],
            ["n"],
            [],
            [KeyboardInterrupt()],
            ["o", "0"],
            ["o", "-2"],
            ["i", "x"],
        ):
            with self.subTest(reponses=reponses):
                self.systeme.shells = []
                self.systeme.reponses = list(reponses)
                self.assertEqual(self.lancer(), mr.CODE_RESTE)
                self.assertEqual(self.systeme.shells, [])
                self.assertIn(mr.t("No mail resent."), self.sortie)

    def test_confirmation_de_resend_au_terminal(self):
        self.systeme.interactif = True
        question = mr.t("Resend {count} mail(s)? [y/N] ").format(count=5)
        for reponses in (["n"], [""], []):
            with self.subTest(reponses=reponses):
                self.systeme.shells, self.systeme.questions = [], []
                self.systeme.reponses = list(reponses)
                self.assertEqual(self.lancer("--resend", "all"), mr.CODE_RESTE)
                self.assertEqual(self.systeme.shells, [])
                self.assertEqual(self.systeme.questions, [question])
                self.assertIn(mr.t("No mail resent."), self.sortie)
        self.systeme.questions = []
        self.systeme.reponses = ["y"]
        self.assertEqual(self.lancer("--resend", "oldest", "2"), mr.CODE_OK)
        self.assertEqual(self.ids_envoyes(), [7171, 7404])
        self.assertEqual(
            self.systeme.questions,
            [mr.t("Resend {count} mail(s)? [y/N] ").format(count=2)],
        )

    def test_json_au_terminal_ne_demande_rien(self):
        self.systeme.interactif = True
        for options in ([], ["--resend", "all"]):
            with self.subTest(options=options):
                self.systeme.reponses = ["a"]
                self.systeme.questions = []
                self.assertEqual(self.lancer("--json", *options), 1)
                self.assertEqual(self.systeme.questions, [])
                self.assertEqual(self.systeme.shells, [])
                json.loads(self.sortie)

    def test_list_et_resend_s_excluent(self):
        with self.assertRaises(SystemExit) as fin:
            self.lancer("--list", "--resend", "all")
        self.assertEqual(fin.exception.code, 2)

    def test_list_ne_demande_rien(self):
        self.systeme.interactif = True
        self.systeme.reponses = ["a"]
        self.assertEqual(self.lancer("--list"), mr.CODE_RESTE)
        self.assertEqual(self.systeme.shells, [])

    def test_r8_simulation(self):
        self.assertEqual(
            self.lancer("--dry-run", "--resend", "all", "--yes"), mr.CODE_RESTE
        )
        self.assertEqual(self.systeme.shells, [])
        self.assertIn("runuser -u demo -- env", self.sortie)
        self.assertIn("bash ./odoo_bin.sh shell -c", self.sortie)
        self.assertIn("action_retry", self.sortie)
        self.assertIn("IDS = [7171, 7404, 7405, 7406, 7500]", self.sortie)


class TestRenvoi(Base):
    def test_r9_commande_et_script(self):
        self.lancer("--resend", "ids", "7404", "--yes")
        (shell,) = self.systeme.shells
        argv = shell["argv"]
        self.assertEqual(argv[:5], ["runuser", "-u", "demo", "--", "env"])
        conf = os.path.join(self.wd, "config.conf")
        self.assertIn(f"ODOO_RC={conf}", argv)
        self.assertIn("LANG=C.UTF-8", argv)
        self.assertTrue(any(a.startswith("HOME=") for a in argv))
        fin = argv[argv.index("bash") :]
        self.assertEqual(
            fin,
            [
                "bash",
                "./odoo_bin.sh",
                "shell",
                "-c",
                conf,
                "-d",
                "base_essai",
                "--no-http",
            ],
        )
        self.assertEqual(shell["cwd"], self.wd)
        source = shell["source"]
        self.assertTrue(source.startswith("IDS = [7404]\n"))
        for morceau in (
            "action_retry",
            "write({'state': 'outgoing'})",
            ".filtered(lambda m: m.state == 'exception')",
            "exists()",
            "env.cr.commit()",
        ):
            self.assertIn(morceau, source)
        self.assertNotIn("UPDATE", source.upper().replace("UPDATE_", ""))
        for requete in self.systeme.requetes:
            self.assertNotIn("UPDATE ", requete["argv"][-1].upper())

    def bilan(self, donnees, code=0, stderr=""):
        sortie = "\n".join([mr.DEBUT_JSON, json.dumps(donnees), mr.FIN_JSON])
        self.systeme.reponse_shell = (code, sortie, stderr)

    def test_r10_une_partie_ignoree(self):
        self.bilan(
            {"requeued": [7171, 7405], "skipped": [7404], "method": "write"}
        )
        code = self.lancer("--resend", "ids", "7171,7404,7405", "--yes")
        self.assertEqual(code, mr.CODE_RESTE)
        self.assertIn("#7171, #7405", self.sortie)
        self.assertIn("#7404", self.sortie)

    def test_r13_json_du_renvoi(self):
        code = self.lancer("--json", "--resend", "ids", "7404,99999", "--yes")
        renvoi = json.loads(self.sortie)["resend"]
        self.assertEqual(code, mr.CODE_RESTE)
        self.assertEqual(
            renvoi,
            {
                "requested": [7404],
                "requeued": [7404],
                "skipped": [],
                "not_listed": [99999],
                "method": "action_retry",
                "dry_run": False,
            },
        )
        self.systeme.shells = []
        self.lancer("--json", "--dry-run", "--resend", "oldest", "2", "--yes")
        renvoi = json.loads(self.sortie)["resend"]
        self.assertEqual(self.systeme.shells, [])
        self.assertTrue(renvoi["dry_run"])
        self.assertEqual(renvoi["requested"], [7171, 7404])
        self.assertEqual(renvoi["requeued"], [])

    def test_ordre_de_la_liste(self):
        """`oldest N` prend les N premiers : l'ordre vient de la requête."""
        self.lancer("--list")
        sql = self.systeme.requetes[0]["argv"][-1]
        self.assertIn("json_agg(f ORDER BY f.date, f.id)", sql)

    def test_r10_tous_remis(self):
        self.assertEqual(self.lancer("--resend", "all", "--yes"), mr.CODE_OK)
        self.assertIn("Mail: Email Queue Manager", self.sortie)

    def test_r10_sans_sentinelle_ou_delai(self):
        self.systeme.reponse_shell = (1, "pas de JSON", "Traceback\nboom\n")
        self.assertEqual(
            self.lancer("--resend", "all", "--yes"), mr.CODE_REFUS
        )
        self.assertIn("boom", self.sortie)
        self.systeme.shells = []
        self.systeme.reponse_shell = (124, "", "timeout")
        self.assertEqual(
            self.lancer("--resend", "all", "--yes"), mr.CODE_REFUS
        )
        # Une validation a pu précéder l'arrêt : le message le dit.
        self.assertIn(
            mr.t(
                "The Odoo shell exceeded {seconds} s and was stopped: whether"
                " the mails were requeued is unknown; list them again."
            ).format(seconds=mr.DELAI_SHELL),
            self.sortie,
        )

    def test_r10_odoo_bin_absent(self):
        self.systeme.odoo_bin = False
        self.assertEqual(
            self.lancer("--resend", "all", "--yes"), mr.CODE_REFUS
        )
        self.assertEqual(self.systeme.requetes, [])
        self.assertIn("odoo_bin.sh", self.erreurs)

    def test_r11_droits(self):
        self.systeme.euid_valeur = 1000
        self.systeme.courant = "autre"
        self.assertEqual(self.lancer(), mr.CODE_REFUS)
        self.assertIn("sudo", self.erreurs)
        self.assertEqual(self.systeme.requetes, [])
        self.assertEqual(self.lancer("--dry-run"), mr.CODE_OK)
        self.assertIn("psql", self.sortie)
        self.assertEqual(self.systeme.requetes, [])
        self.systeme.courant = "demo"
        self.lancer("--resend", "all", "--yes")
        self.assertEqual(self.systeme.requetes[-1]["argv"][0], "psql")
        self.assertEqual(self.systeme.shells[-1]["argv"][0], "env")

    def test_r11_psql_en_echec(self):
        self.systeme.psql = (2, "", 'database "base_essai" does not exist')
        self.assertEqual(self.lancer(), mr.CODE_REFUS)
        self.assertIn("does not exist", self.erreurs)

    def test_r12_base_invalide(self):
        for base in ("-x", "a" * 64, "a;b"):
            with self.subTest(base=base):
                with self.assertRaises(SystemExit) as fin:
                    self.lancer("--db", base)
                self.assertEqual(fin.exception.code, 2)


class FauxCourriels:
    """Un jeu d'enregistrements `mail.mail` réduit à ce que lit le script
    du shell : `etats` est partagé {id: état}, un id absent est un
    courriel supprimé."""

    def __init__(self, etats, ids=()):
        self.etats = etats
        self.ids = list(ids)

    def _avec(self, ids):
        return type(self)(self.etats, ids)

    def sudo(self):
        return self

    def browse(self, ids):
        return self._avec(ids)

    def exists(self):
        return self._avec([i for i in self.ids if i in self.etats])

    def filtered(self, test):
        return self._avec(
            [
                i
                for i in self.ids
                if test(types.SimpleNamespace(state=self.etats[i]))
            ]
        )

    def write(self, valeurs):
        for i in self.ids:
            self.etats[i] = valeurs["state"]


class FauxCourrielsRetry(FauxCourriels):
    def action_retry(self):
        for i in self.ids:
            self.etats[i] = "outgoing"


class FauxCourrielsRetryPartiel(FauxCourriels):
    """`action_retry` qui laisse le courriel 3 en échec : le bilan ne
    doit compter que ce qui est réellement passé à `outgoing`."""

    def action_retry(self):
        for i in self.ids:
            if i != 3:
                self.etats[i] = "outgoing"


class TestScriptDuShell(unittest.TestCase):
    """Le script donné à `odoo shell`, exécuté sur un faux `env`."""

    def executer(self, classe):
        etats = {1: "exception", 2: "sent", 3: "exception"}
        valides = []

        class Env(dict):
            cr = types.SimpleNamespace(commit=lambda: valides.append(1))

        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            exec(
                mr.script_renvoi([1, 2, 3, 99]),
                {"env": Env({"mail.mail": classe(etats)})},
            )
        self.assertEqual(valides, [1])
        return mr.lire_bilan(sortie.getvalue()), etats

    def test_avec_action_retry(self):
        bilan, etats = self.executer(FauxCourrielsRetry)
        self.assertEqual(bilan["method"], "action_retry")
        self.assertEqual(bilan["requeued"], [1, 3])
        self.assertEqual(bilan["skipped"], [2, 99])
        self.assertEqual(bilan["requested"], [1, 2, 3, 99])
        self.assertEqual(etats, {1: "outgoing", 2: "sent", 3: "outgoing"})

    def test_bilan_lu_apres_la_remise(self):
        bilan, etats = self.executer(FauxCourrielsRetryPartiel)
        self.assertEqual(bilan["requeued"], [1])
        self.assertEqual(bilan["skipped"], [2, 3, 99])
        self.assertEqual(etats[3], "exception")

    def test_sans_action_retry(self):
        bilan, etats = self.executer(FauxCourriels)
        self.assertEqual(bilan["method"], "write")
        self.assertEqual(bilan["requeued"], [1, 3])
        self.assertEqual(bilan["skipped"], [2, 99])
        self.assertEqual(etats[2], "sent")


class TestShellReel(unittest.TestCase):
    """`Systeme.shell_odoo` sur de vrais processus : au délai dépassé, le
    petit-enfant (le python d'Odoo derrière runuser et bash) meurt aussi
    et ne valide rien."""

    def test_delai_tue_le_groupe(self):
        with tempfile.TemporaryDirectory() as dossier:
            marque = os.path.join(dossier, "valide")
            petit_enfant = (
                "import sys, time; sys.stdin.read(); time.sleep(1.0);"
                f" open({marque!r}, 'w').write('commit')"
            )
            enfant = (
                "import subprocess, sys;"
                f" subprocess.run([sys.executable, '-c', {petit_enfant!r}])"
            )
            systeme = mr.Systeme(interactif=False)
            debut = time.monotonic()
            code, sortie, erreurs = systeme.shell_odoo(
                [sys.executable, "-c", enfant], dossier, "IDS = [1]\n", 0.3
            )
            self.assertEqual((code, sortie, erreurs), (124, "", "timeout"))
            self.assertLess(time.monotonic() - debut, 1.0)
            time.sleep(1.2)
            self.assertFalse(os.path.exists(marque))

    def test_reponse_normale(self):
        systeme = mr.Systeme(interactif=False)
        code, sortie, _erreurs = systeme.shell_odoo(
            [sys.executable, "-c", "import sys; print(sys.stdin.read())"],
            None,
            "bonjour",
            10,
        )
        self.assertEqual((code, sortie.strip()), (0, "bonjour"))
        code, _sortie, _erreurs = systeme.shell_odoo(
            ["/chemin/absent/odoo_bin"], None, "", 10
        )
        self.assertEqual(code, 127)


class TestInterruptionEtImprevu(Base):
    def test_ctrl_c_rend_130(self):
        def interrompre(*_a, **_k):
            raise KeyboardInterrupt

        self.systeme.requete = interrompre
        self.assertEqual(self.lancer(), mr.CODE_INTERROMPU)

    def test_erreur_imprevue_rend_2(self):
        self.systeme.donnees["failures"] = [{"id": "pas un nombre"}]
        self.assertEqual(self.lancer(), mr.CODE_REFUS)
        self.assertIn("pas un nombre", self.erreurs)
        self.assertEqual(self.lancer("--json"), mr.CODE_REFUS)
        self.assertEqual(json.loads(self.sortie), {"exit_code": 2})


class TestPython37(unittest.TestCase):
    def test_r14_syntaxe(self):
        racine = os.path.join(os.path.dirname(__file__), "..")
        chemin = os.path.join(racine, "script", "odoo", "mail_retry.py")
        with open(chemin, encoding="utf-8") as f:
            source = f.read()
        ast.parse(source, feature_version=(3, 7))
        # Odoo 12 tourne sous Python 3.7 ; le script du shell se lit aussi
        # en 3.6, sans rien qui dépende de l'interpréteur de l'instance.
        ast.parse(mr.script_renvoi([1, 2]), feature_version=(3, 6))


if __name__ == "__main__":
    unittest.main()
