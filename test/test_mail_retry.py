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
import re
import sys
import tempfile
import time
import types
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from profil_isole import profil_isole  # noqa: E402

from script.lib_ops import profil  # noqa: E402
from script.odoo import mail_retry as mr  # noqa: E402


def setUpModule():
    # Les profils de production de ce module vivent dans un dossier
    # temporaire ; le vrai `private/production` reste intouché.
    profil_isole()


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
R421 = (
    "Mail Delivery Failed\nMail delivery failed via SMTP server 'None'.\n"
    "SMTPDataError: (421, b'4.7.0 Try again later')"
)
R503 = (
    "Mail Delivery Failed\nMail delivery failed via SMTP server 'None'.\n"
    "SMTPSenderRefused: (503, b'5.5.1 Multiple MAIL commands not allowed',"
    " 'admin@example.org')"
)
R550 = (
    "Mail Delivery Failed\nMail delivery failed via SMTP server 'None'.\n"
    "SMTPDataError: (550, b'You are not allowed to send emails as"
    ' "a@example.org" (header From) while using "b@example.org" as'
    " envelope sender')"
)


AVERTISSEMENT_SESSION = (
    "{count} mail(s) refused by the per-session message limit of the SMTP"
    " server; largest recipient group: {recipients};"
    " mail.session.batch.size: {value}. One session carries up to that many"
    " mails (1000 when unset) and one message per recipient of each: the"
    " server counts the sum. Before any resend, lower"
    " mail.session.batch.size so that it times the largest group stays under"
    " the limit, or raise the server limit when one mail's group alone"
    " exceeds it: a resend before that fails again and may deliver twice to"
    " the first recipients."
)
AVERTISSEMENT_LOT = (
    "{count} mails and mail.session.batch.size is {value}: a server limit of"
    " messages per connection may refuse part of the resend; set it to 10 or"
    " 20 first."
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
        # L'argv[] de l'ExecStart de l'unité ; `{wd}` est le dossier de
        # travail.
        self.execstart = "/bin/bash {wd}/run.sh"

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
                "ExecStart={ path=/bin/bash ; argv[]="
                + self.execstart.format(wd=self.wd)
                + " ; ignore_errors=no }\n"
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

        self.assertIn(mr.t("PERMANENT"), ligne_de(7404))
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
        self.assertEqual(par_id[2]["class"], "session_limit")
        self.assertTrue(par_id[2]["permanent"])
        self.systeme.donnees["failures"] = [
            echec(3, 0, "S", "y@example.org", R421, None),
        ]
        self.lancer()
        self.assertIn(mr.t("transient"), self.sortie)

    def test_r4_avertissements(self):
        self.lancer()
        self.assertIn("[ATTN]", self.sortie)
        # Odoo 18 lu dans `base` : le réglage nomme le filtre « De ».
        self.assertIn("from_filter", self.sortie)
        douze = [
            echec(8000 + i, i, "S", "x@example.org", R421) for i in range(12)
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

    def avertissement_de_session(self):
        marque = mr.t(AVERTISSEMENT_SESSION).split("{count}")[1]
        marque = marque.split("{recipients}")[0]
        lignes = [
            ligne
            for ligne in self.sortie.splitlines()
            if "[ATTN]" in ligne and marque in ligne
        ]
        return lignes[0] if lignes else ""

    def avertissement_de_lot_present(self):
        return mr.t(AVERTISSEMENT_LOT).split("{value}")[1] in self.sortie

    def test_r4_limite_de_session_quel_que_soit_le_lot(self):
        """Un refus par la limite de messages par session avertit avant
        tout renvoi, même avec un mail.session.batch.size bas et peu de
        courriels, et nomme la valeur du lot : une session porte un lot
        de courriels, un message par destinataire de chacun. Le plus
        grand groupe est donné."""
        for valeur, montree in (
            (None, mr.t("unset")),
            ("5", "5"),
            ("500", "500"),
        ):
            with self.subTest(valeur=valeur):
                self.systeme.donnees["batch_size"] = valeur
                self.lancer()
                self.assertIn(
                    mr.t(AVERTISSEMENT_SESSION).format(
                        count=3, recipients=2, value=montree
                    ),
                    self.avertissement_de_session(),
                )
                self.assertFalse(self.avertissement_de_lot_present())

    def test_r4_limite_de_session_et_lot_trop_grand(self):
        """Plus de SEUIL_LOT refus par la limite de session avec un lot
        absent ou trop grand : l'avertissement du lot paraît à côté de
        celui de la session, car un lot plus petit réduit la somme des
        destinataires d'une session ; un lot sûr le fait taire."""
        self.systeme.donnees["failures"] = [
            echec(8000 + i, i, "S", "x@example.org", R452)
            for i in range(mr.SEUIL_LOT + 2)
        ]
        for valeur, attendu in ((None, True), ("500", True), ("10", False)):
            with self.subTest(valeur=valeur):
                self.systeme.donnees["batch_size"] = valeur
                self.lancer()
                self.assertIn(
                    mr.t(AVERTISSEMENT_SESSION).format(
                        count=mr.SEUIL_LOT + 2,
                        recipients=1,
                        value=valeur or mr.t("unset"),
                    ),
                    self.avertissement_de_session(),
                )
                self.assertEqual(self.avertissement_de_lot_present(), attendu)

    def test_r4_groupe_coupe_par_la_requete(self):
        """La requête coupe les destinataires à 300 caractères : le groupe
        se dit alors « au moins N ». Le 503 qui suit le 452 compte avec
        lui."""
        adresses = ", ".join(f"dest{i:03d}@example.org" for i in range(40))
        self.systeme.donnees["failures"] = [
            echec(1, 0, "Lettre", adresses[:300], R452),
            echec(2, 1, "Lettre", "a@example.org", R503),
        ]
        self.systeme.donnees["batch_size"] = "10"
        self.lancer()
        nombre = len(mr.RE_ADRESSE.findall(adresses[:300]))
        self.assertGreater(nombre, 10)
        self.assertIn(
            mr.t(AVERTISSEMENT_SESSION).format(
                count=2,
                recipients=mr.t("at least {count}").format(count=nombre),
                value="10",
            ),
            self.avertissement_de_session(),
        )
        echecs = [mr.Echec(e) for e in self.systeme.donnees["failures"]]
        self.assertEqual(echecs[0].nombre_destinataires(), (nombre, True))
        self.assertEqual(echecs[1].nombre_destinataires(), (1, False))
        self.assertIn("300", mr.requete_liste(30))

    def test_r4_une_liste_coupee_garde_le_au_moins(self):
        """Une liste coupée dit « au moins » même quand une liste entière
        compte plus d'adresses lisibles : la coupée en cache peut-être
        bien davantage."""
        longues = ", ".join(
            f"destinataire.long.{i:03d}@example.org" for i in range(40)
        )
        coupee = longues[:300]
        lues = len(mr.RE_ADRESSE.findall(coupee))
        entiere = ", ".join(f"d{i}@example.org" for i in range(lues + 1))
        self.assertLess(len(entiere), 300)
        self.systeme.donnees["failures"] = [
            echec(1, 0, "Lettre", coupee, R452),
            echec(2, 1, "Lettre", entiere, R452),
        ]
        self.systeme.donnees["batch_size"] = "10"
        self.lancer()
        self.assertIn(
            mr.t(AVERTISSEMENT_SESSION).format(
                count=2,
                recipients=mr.t("at least {count}").format(count=lues + 1),
                value="10",
            ),
            self.avertissement_de_session(),
        )

    def test_r4_groupe_inconnu(self):
        self.systeme.donnees["failures"] = [echec(1, 0, "S", "", R452)]
        self.lancer()
        self.assertIn(mr.t("unknown"), self.avertissement_de_session())

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
        # Le shell passe par l'interpréteur de l'unité et par le
        # odoo_bin.sh que lance run.sh.
        fin = argv[argv.index("/bin/bash") :]
        self.assertEqual(
            fin,
            [
                "/bin/bash",
                "./odoo_bin.sh",
                "shell",
                "-c",
                conf,
                "-d",
                "base_essai",
                "--no-http",
                "--workers=0",
                "--max-cron-threads=0",
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

    def test_les_options_de_l_unite_suivent_le_shell(self):
        """Défaut d'un shell qui perd l'`--addons-path` de l'unité : les
        modules du shell ne seraient plus ceux du serveur. Les options de
        run.sh propres à ERPLibre sont retirées, la base de l'unité
        aussi."""
        self.systeme.execstart = (
            "/bin/bash {wd}/run.sh --auto-erplibre"
            " --addons-path=/srv/exemple/addons -d autre_db"
        )
        self.lancer("--resend", "ids", "7404", "--yes")
        (shell,) = self.systeme.shells
        argv = shell["argv"]
        fin = argv[argv.index("./odoo_bin.sh") :]
        self.assertEqual(
            fin[:3],
            ["./odoo_bin.sh", "shell", "--addons-path=/srv/exemple/addons"],
        )
        self.assertNotIn("--auto-erplibre", argv)
        # La base de l'unité, retirée de ses options, revient une seule
        # fois, après `-c`.
        self.assertEqual(argv.count("-d"), 1)
        self.assertEqual(argv[argv.index("-d") + 1], "autre_db")

    def test_odoo_bin_direct_et_son_fichier_verifie(self):
        self.systeme.execstart = (
            "/srv/exemple/venv/bin/python /srv/exemple/odoo/odoo-bin"
            " --addons-path=/srv/exemple/addons"
        )
        self.lancer("--resend", "ids", "7404", "--yes")
        (shell,) = self.systeme.shells
        argv = shell["argv"]
        fin = argv[argv.index("/srv/exemple/venv/bin/python") :]
        self.assertEqual(
            fin[:4],
            [
                "/srv/exemple/venv/bin/python",
                "/srv/exemple/odoo/odoo-bin",
                "shell",
                "--addons-path=/srv/exemple/addons",
            ],
        )

    def test_sans_lanceur_la_liste_reste_le_renvoi_refuse(self):
        self.systeme.execstart = "/bin/sh -c 'cd /srv/exemple && ./run.sh'"
        conf = os.path.join(self.wd, "config.conf")
        self.assertEqual(
            self.lancer("--list", "--odoo-conf", conf), mr.CODE_RESTE
        )
        self.assertEqual(
            self.lancer("--resend", "all", "--yes", "--odoo-conf", conf),
            mr.CODE_REFUS,
        )
        self.assertEqual(self.systeme.shells, [])
        self.assertIn("ExecStart", self.erreurs)

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


def champ_base(base, origine):
    """Le motif de la seule ligne du champ Database qui porte `base
    (origine)`, ancré : la ligne de détail `--db base (profile)` ne le
    satisfait pas."""
    return re.compile(
        r"^  "
        + re.escape(mr.t("Database"))
        + r" +"
        + re.escape(f"{base} ({origine})")
        + r"$",
        re.M,
    )


class TestProfil(Base):
    """Le profil JSON de l'instance (groupe `mail_retry`, alias
    `instance.db`) : valeurs appliquées et montrées, la ligne de commande
    gagne, les options exclues ne s'y persistent pas."""

    DOC = {
        "version": 1,
        "service": UNITE,
        "instance": {"db": "exemple_db"},
        "mail_retry": {"days": 14, "timeout": 120},
    }

    def ecrire_profil(self, doc=None, groupe=None):
        doc = json.loads(json.dumps(self.DOC if doc is None else doc))
        if groupe is not None:
            doc["mail_retry"].update(groupe)
        chemin = os.path.join(profil.RACINE_PROFILS, f"{UNITE}.json")
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        os.chmod(chemin, 0o644)
        self.addCleanup(os.remove, chemin)
        return chemin

    def ligne(self, option, valeur):
        return mr.t("{option} {value} (profile)").format(
            option=option, value=valeur
        )

    def test_construire_parseur_sans_analyse(self):
        parser = mr.construire_parseur()
        dests = {action.dest for action in parser._actions}
        self.assertTrue({"days", "timeout", "verbose", "db"} <= dests)
        self.assertNotIn("profile", dests)
        args = parser.parse_args(["--list", "--resend", "all"])
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as fin:
                mr.valider(parser, args)
        self.assertEqual(fin.exception.code, 2)

    def test_valeurs_appliquees_et_montrees(self):
        self.ecrire_profil()
        args = mr.analyser(["--service", UNITE])
        self.assertEqual((args.days, args.timeout), (14, 120))
        self.assertEqual(args.db, "exemple_db")
        self.assertEqual(args.profil.origine("days"), "profil")
        self.assertEqual(args.profil.origine("verbose"), "defaut")
        self.lancer("--list")
        self.assertIn(
            "interval '14 days'", self.systeme.requetes[-1]["argv"][-1]
        )
        self.assertIn(self.ligne("--days", 14), self.sortie)
        self.assertEqual(
            self.lancer("--dry-run", "--resend", "all", "--yes"),
            mr.CODE_RESTE,
            self.erreurs,
        )
        # `--resend` renvoie ce que liste `--days` : la fenêtre du profil
        # est écartée, le défaut s'applique.
        self.assertIn(
            f"interval '{mr.JOURS_PAR_DEFAUT} days'",
            self.systeme.requetes[-1]["argv"][-1],
        )
        self.assertNotIn(self.ligne("--days", 14), self.sortie)
        self.assertIn(
            mr.t("{option} from the profile ignored: {reason}").format(
                option="--days",
                reason=mr.t(
                    "--resend selects from the list: give --days explicitly"
                ),
            ),
            self.sortie,
        )
        self.assertIn(mr.t("Profile"), self.sortie)
        for option, valeur in (
            ("--timeout", 120),
            ("--db", "exemple_db"),
        ):
            self.assertIn(self.ligne(option, valeur), self.sortie)
        # En simulation, les valeurs du profil précèdent les commandes.
        self.assertLess(
            self.sortie.index(self.ligne("--timeout", 120)),
            self.sortie.index("(simulation)"),
        )
        self.assertEqual(self.systeme.shells, [])

    def test_champ_base_dit_son_origine(self):
        """Le champ Database dit « profile » pour une base du profil, et
        `--db` pour une base tapée ; la ligne de détail du profil ne
        suffit pas à le satisfaire."""
        self.ecrire_profil()
        self.lancer("--list")
        self.assertRegex(
            self.sortie, champ_base("exemple_db", mr.t("profile"))
        )
        self.lancer("--list", "--db", "base_essai")
        self.assertRegex(self.sortie, champ_base("base_essai", "--db"))

    def test_delai_du_profil_pour_le_shell(self):
        self.ecrire_profil()
        self.assertEqual(
            self.lancer("--resend", "ids", "7404", "--yes"), mr.CODE_OK
        )
        self.assertEqual(self.systeme.shells[-1]["delai"], 120)

    def test_la_ligne_de_commande_gagne(self):
        self.ecrire_profil()
        args = mr.analyser(["--service", UNITE, "--days", "7"])
        self.assertEqual((args.days, args.timeout), (7, 120))
        self.assertEqual(args.profil.origine("days"), "cli")
        self.lancer("--days", "7", "--db", "base_essai")
        self.assertIn(
            "interval '7 days'", self.systeme.requetes[-1]["argv"][-1]
        )
        self.assertNotIn(self.ligne("--days", 14), self.sortie)
        self.assertIn(
            mr.t("{option}: the command line wins over the profile").format(
                option="--days"
            ),
            self.sortie,
        )
        self.assertIn("base_essai", self.sortie)

    def test_no_profile_et_profile_unset(self):
        self.ecrire_profil()
        args = mr.analyser(["--service", UNITE, "--no-profile"])
        self.assertFalse(args.profil.actif)
        self.assertEqual((args.days, args.timeout), (30, mr.DELAI_SHELL))
        self.assertIsNone(args.db)
        self.lancer("--no-profile")
        self.assertNotIn(mr.t("Profile"), self.sortie)
        self.assertIn(
            "interval '30 days'", self.systeme.requetes[-1]["argv"][-1]
        )
        args = mr.analyser(["--service", UNITE, "--profile-unset", "days"])
        self.assertEqual((args.days, args.timeout), (30, 120))

    def test_options_exclues_jamais_appliquees(self):
        # Vie privée, objet, sécurité, mode, format : aucune ne s'applique
        # depuis le profil, chacune est écartée avec un ATTN.
        exclues = {
            "details": True,
            "resend": ["all"],
            "yes": True,
            "list": True,
            "dry_run": True,
            "json": True,
            "user": "autre",
        }
        self.ecrire_profil(groupe=exclues)
        args = mr.analyser(["--service", UNITE])
        self.assertFalse(args.details or args.yes or args.list)
        self.assertFalse(args.dry_run or args.json)
        self.assertIsNone(args.resend)
        self.assertIsNone(args.user)
        self.assertEqual(
            sorted(e.dest for e in args.profil.ecartees), sorted(exclues)
        )
        self.assertNotIn("details", args.profil.valeurs)
        # `yes` du profil ne confirme pas un `--resend` tapé.
        self.assertEqual(self.lancer("--resend", "all"), mr.CODE_RESTE)
        self.assertEqual(self.systeme.shells, [])
        self.assertNotIn("jean.dupont", self.sortie)
        self.assertIn(
            mr.t("{key} is not a profile setting ({reason}), ignored").format(
                key="mail_retry.details",
                reason=mr.t(profil.RAISONS["vie_privee"]),
            ),
            self.sortie,
        )

    def test_cle_inconnue_et_alias_dans_son_groupe(self):
        self.ecrire_profil(groupe={"db": "autre_db", "jours": 3})
        args = mr.analyser(["--service", UNITE])
        self.assertEqual(args.db, "exemple_db")
        self.assertEqual(
            args.profil.inconnues, ["mail_retry.db", "mail_retry.jours"]
        )
        self.lancer()
        for cle in ("mail_retry.db", "mail_retry.jours"):
            self.assertIn(
                mr.t("unknown key {key}, ignored").format(key=cle),
                self.sortie,
            )

    def test_valeur_invalide_refusee_en_code_2(self):
        chemin = self.ecrire_profil(groupe={"days": 0})
        erreurs = io.StringIO()
        with contextlib.redirect_stderr(erreurs):
            with self.assertRaises(SystemExit) as fin:
                mr.main(
                    ["--service", UNITE], self.systeme, None, io.StringIO()
                )
        self.assertEqual(fin.exception.code, 2)
        self.assertIn(chemin, erreurs.getvalue())
        self.assertIn("mail_retry.days", erreurs.getvalue())
        self.assertEqual(self.systeme.requetes, [])

    def test_profile_explicite_nomme_le_service(self):
        chemin = self.ecrire_profil()
        flux, erreurs = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(erreurs):
            code = mr.main(["--profile", chemin], self.systeme, None, flux)
        self.assertEqual(code, mr.CODE_RESTE, erreurs.getvalue())
        show = [
            a for a in self.systeme.appels if a[:2] == ["systemctl", "show"]
        ]
        self.assertTrue(show)
        self.assertTrue(all(UNITE in a for a in show))
        self.assertIn(
            "interval '14 days'", self.systeme.requetes[-1]["argv"][-1]
        )

    def test_json_porte_le_profil_et_avertit_sur_stderr(self):
        chemin = self.ecrire_profil(groupe={"details": True})
        code = self.lancer("--json")
        donnees = json.loads(self.sortie)
        self.assertEqual(donnees["exit_code"], code)
        self.assertEqual(list(donnees)[-2:], ["profile", "exit_code"])
        self.assertEqual(donnees["profile"]["path"], chemin)
        self.assertEqual(
            donnees["profile"]["values"],
            {"--days": 14, "--timeout": 120, "--db": "exemple_db"},
        )
        self.assertEqual(
            [i["key"] for i in donnees["profile"]["ignored"]],
            ["mail_retry.details"],
        )
        self.assertNotIn("jean.dupont", self.sortie)
        self.assertIn("[ATTN]", self.erreurs)
        self.assertIn("mail_retry.details", self.erreurs)

    def test_json_sans_liste_porte_le_profil(self):
        self.ecrire_profil()
        self.systeme.psql = (2, "", "connexion refusée")
        code = self.lancer("--json")
        self.assertEqual(code, mr.CODE_REFUS)
        donnees = json.loads(self.sortie)
        self.assertEqual(list(donnees), ["profile", "exit_code"])

    def test_json_sans_profil_sans_cle(self):
        _code = self.lancer("--json")
        self.assertNotIn("profile", json.loads(self.sortie))


class TestPython36(unittest.TestCase):
    def test_r14_script_du_shell(self):
        """Le script envoyé au shell d'Odoo se lit en 3.6, sans rien qui
        dépende de l'interpréteur de l'instance. Le fichier lui-même est
        couvert par test/test_ops_py37.py."""
        ast.parse(mr.script_renvoi([1, 2]), feature_version=(3, 6))


if __name__ == "__main__":
    unittest.main()
