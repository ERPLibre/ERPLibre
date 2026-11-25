#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""script/database/odoo_backup.py : sauvegarde, état, restauration, copie.

Aucune commande réelle n'est lancée : `FauxSysteme` remplace systemctl
(`lanceur`), psql/createdb/dropdb/rsync (`requete`), pg_dump (`flux`) et
le chargement d'un dump (`alimenter`), l'espace disque et la propriété
des fichiers. Il tient l'ensemble des bases du serveur comme le ferait
PostgreSQL : createdb en ajoute une, dropdb la retire. Les fichiers
(configuration, filestore, sauvegardes, état) vivent dans un dossier
temporaire ; une création hors de ce dossier lève. `sous_le_compte`
appelle la fonction sur place et note l'appel : le changement d'identité
réel est éprouvé à part (`TestSousLeCompte`).

Données inventées : base `demo_db`, compte `demo`, unité
`erplibre_demo.service`, copie vers `backup.example.org`.

Les profils de production se lisent d'un dossier temporaire : `setUpModule`
arme la couture `profil.RACINE_PROFILS` par `profil_isole()`, et tout accès
au vrai `private/production` fait échouer le module.
"""

import contextlib
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from profil_isole import profil_isole  # noqa: E402

from script.database import odoo_backup as ob  # noqa: E402
from script.lib_ops import (  # noqa: E402
    lock,
    postgres,
    profil,
    report,
    retention,
)

DUMP = b"-- dump\nCREATE TABLE x ();\n-- PostgreSQL database dump complete\n"
FAITS = {
    "base": "18.0.1.3",
    "modules": {"base": "18.0.1.3", "web": "18.0.1.0"},
    "server_version_num": 160004,
    "size": 1000,
    "stored_attachments": 3,
}
CONTROLE = {
    "tables": 120,
    "base": "installed",
    "modules": ["base", "web"],
    "stored_files": 3,
}
COPIE = "backup@backup.example.org:/srv/backups"
RE_NOM = re.compile(r"^demo_db_\d{4}-\d{2}-\d{2}_\d{2}h\d{2}m\d{2}s\.zip$")
# 2031-03-10 03:00:00, heure locale.
HORLOGE = datetime.datetime(2031, 3, 10, 3, 0, 0).timestamp()


def setUpModule():
    profil_isole()


def ecrire(chemin, texte=""):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    mode = "wb" if isinstance(texte, bytes) else "w"
    with open(chemin, mode) as f:
        f.write(texte)
    return chemin


def outil(argv):
    """Le nom de l'outil lancé, préfixe runuser retiré."""
    if argv[:1] == ["runuser"]:
        argv = argv[argv.index("--") + 1 :]
    return os.path.basename(argv[0]), argv


class FauxSysteme(ob.Systeme):
    """Un systemd, un PostgreSQL et un rsync de théâtre."""

    def __init__(self, bac, verrous):
        super().__init__(dossier_verrou=verrous)
        self.bac = bac
        self.appels = []
        self.vu = {}
        self.euid_valeur = 0
        self.courant = "root"
        self.horloge = HORLOGE
        self.proprietes = {
            "LoadState": "loaded",
            "ActiveState": "active",
            "User": "demo",
            "WorkingDirectory": os.path.join(bac, "odoo"),
            "ExecStart": (
                "{ path=/bin/bash ; argv[]=/bin/bash "
                + os.path.join(bac, "odoo", "run.sh")
                + " -d demo_db ; ignore_errors=no }"
            ),
            "Environment": "",
        }
        self.faits = json.loads(json.dumps(FAITS))
        self.controle = dict(CONTROLE)
        self.bases = {"postgres", "demo_db"}
        self.dump_contenu = DUMP
        self.dump_issue = (0, "", False)
        self.chargement = (0, ["SET", "COMMENT"], False)
        self.createdb_code = 0
        self.dropdb_code = 0
        self.rsync_code = 0
        # Crons actifs des modules de sauvegarde d'Odoo : un nombre (ceux de
        # `db.backup`) ou {modèle: nombre} ; None : la requête échoue.
        self.auto_backup = 0
        # Configurations de chaque modèle ({modèle: nombre}), 1 par défaut.
        self.auto_backup_config = {}
        # Propriétés d'autres unités pour `systemctl show` ; None : systemctl
        # en échec.
        self.unites = {}
        # Le contenu du dossier source à chaque copie rsync.
        self.source_copie = []
        # Le dossier distant de la base : les noms que la copie y dépose,
        # que `--list-only` liste et que l'élagage retire.
        self.distants = []
        # Les noms visés par chaque élagage, et les codes de la liste et de
        # l'élagage.
        self.elagages = []
        self.liste_code = 0
        self.elagage_code = 0
        self.libre = 10**12
        self.espace_erreur = None
        self.chowns = []
        self.non_inscriptibles = set()
        self.lever_dans_flux = None
        self.verrou_pendant_flux = None
        # `SHOW data_directory` : sous le compte de l'unité, puis sous le
        # compte système du serveur ; (code, sortie) de chacun.
        self.dossier_pg = os.path.join(bac, "pgdata")
        self.reponse_dossier_compte = (0, self.dossier_pg + "\n")
        self.reponse_dossier_postgres = (0, self.dossier_pg + "\n")
        # Espace libre propre à un chemin ; sinon `libre`.
        self.libre_par_lieu = {}
        self.sous_compte = []

    def _dans_le_bac(self, chemin):
        if not os.path.abspath(chemin).startswith(self.bac + os.sep):
            raise AssertionError(f"écriture hors du test : {chemin}")

    def lanceur(self, argv, timeout=60):
        self.appels.append(("systemctl", list(argv)))
        if argv[:2] == ["systemctl", "show"]:
            noms = [argv[i + 1] for i, a in enumerate(argv) if a == "-p"]
            if argv[-1] in self.unites:
                props = self.unites[argv[-1]]
                if props is None:
                    return 1, "Failed to connect to bus"
                return 0, "".join(f"{n}={props.get(n, '')}\n" for n in noms)
            if argv[-1] != "erplibre_demo.service":
                return 0, "LoadState=not-found\n"
            return 0, "".join(
                f"{n}={self.proprietes.get(n, '')}\n" for n in noms
            )
        return 1, "inattendu"

    def euid(self):
        return self.euid_valeur

    def utilisateur_courant(self):
        return self.courant

    def home(self, utilisateur):
        return os.path.join(self.bac, "home_" + utilisateur)

    def maintenant(self):
        return self.horloge

    def inscriptible(self, dossier, utilisateur):
        return dossier not in self.non_inscriptibles

    def chown(self, chemin, utilisateur):
        self.chowns.append((chemin, utilisateur))

    def fchown(self, fd, utilisateur):
        self.chowns.append((os.readlink(f"/proc/self/fd/{fd}"), utilisateur))

    def uid(self, utilisateur):
        return os.getuid()

    def sous_le_compte(self, utilisateur, fonction, *arguments):
        self.appels.append(("sous_le_compte", [utilisateur, fonction]))
        self.sous_compte.append((utilisateur, fonction.__name__))
        return fonction(*arguments)

    def creer_dossier(self, dossier, utilisateur, mode=0o750):
        self._dans_le_bac(dossier)
        self.appels.append(("mkdir", [dossier, utilisateur]))
        os.mkdir(dossier, mode)
        os.chmod(dossier, mode)
        self.chowns.append((dossier, utilisateur))

    def mkdir(self, dossier, mode):
        self._dans_le_bac(dossier)
        self.appels.append(("mkdir", [dossier]))
        os.mkdir(dossier, mode)
        os.chmod(dossier, mode)

    def espace_libre(self, chemin):
        if self.espace_erreur is not None:
            raise self.espace_erreur
        return self.libre_par_lieu.get(chemin, self.libre)

    def requete(self, argv, env, delai=60):
        nom, nu = outil(argv)
        self.appels.append((nom, list(argv)))
        self.vu.setdefault(nom, []).append({"argv": list(argv), "env": env})
        if nom == "psql":
            sql = nu[-1]
            if sql == postgres.REQUETE_FAITS:
                return 0, json.dumps(self.faits) + "\n", ""
            if sql == postgres.REQUETE_AUTO_BACKUP:
                if self.auto_backup is None:
                    return 1, "", "relation ir_cron missing"
                crons = self.auto_backup
                if isinstance(crons, int):
                    crons = {"db.backup": crons} if crons else None
                donnees = {"auto_backup_crons": crons}
                return 0, json.dumps(donnees) + "\n", ""
            for (
                modele,
                requete,
            ) in postgres.REQUETES_CONFIG_AUTO_BACKUP.items():
                if sql == requete:
                    donnees = {
                        "configured": self.auto_backup_config.get(modele, 1)
                    }
                    return 0, json.dumps(donnees) + "\n", ""
            if sql == postgres.REQUETE_BASES:
                return 0, "\n".join(sorted(self.bases)) + "\n", ""
            if sql == postgres.REQUETE_CONTROLE:
                if self.controle is None:
                    return 2, "", "psql: error: relation missing"
                return 0, json.dumps(self.controle) + "\n", ""
            if sql == postgres.REQUETE_DOSSIER:
                compte = argv[2] if argv[:1] == ["runuser"] else self.courant
                if compte == postgres.COMPTE_SYSTEME:
                    code, sortie = self.reponse_dossier_postgres
                else:
                    code, sortie = self.reponse_dossier_compte
                return code, sortie, "" if code == 0 else "permission denied"
        if nom == "createdb":
            if self.createdb_code:
                return self.createdb_code, "", "createdb: error: exists"
            self.bases.add(nu[-1])
            return 0, "", ""
        if nom == "dropdb":
            if self.dropdb_code:
                return self.dropdb_code, "", "dropdb: error"
            self.bases.discard(nu[-1])
            return 0, "", ""
        if nom == "rsync":
            return self._rsync(argv, nu)
        return 1, "", "commande inattendue"

    def _rsync(self, argv, nu):
        if "--list-only" in argv:
            if self.liste_code:
                return self.liste_code, "", "rsync: connection unexpectedly"
            lignes = ["drwxr-xr-x          4,096 2031/03/10 03:00:00 ."]
            lignes += [
                f"-rw-r--r--          1,234 2031/03/10 03:00:00 {n}"
                for n in sorted(self.distants)
            ]
            return 0, "\n".join(lignes) + "\n", ""
        if "--existing" in argv:
            vises = [
                a[len("--include=/") :]
                for a in argv
                if a.startswith("--include=/")
            ]
            self.elagages.append(vises)
            if self.elagage_code:
                return self.elagage_code, "", "rsync: connection unexpectedly"
            self.distants = [n for n in self.distants if n not in vises]
            return 0, "", ""
        source = sorted(os.listdir(nu[-2]))
        self.source_copie.append(source)
        if self.rsync_code:
            return self.rsync_code, "", "rsync: connection unexpectedly"
        noms = set(self.distants)
        noms |= {n for n in source if n.startswith("demo_db_")}
        self.distants = sorted(noms)
        return 0, "", ""

    def flux(self, argv, env, recevoir, delai):
        nom, _nu = outil(argv)
        self.appels.append((nom, list(argv)))
        self.vu["pg_dump"] = {"argv": list(argv), "env": env, "delai": delai}
        sonde = lock.Verrou("erplibre-db-demo_db", self.dossier_verrou)
        try:
            sonde.acquerir()
        except lock.VerrouPris:
            self.verrou_pendant_flux = True
        else:
            self.verrou_pendant_flux = False
            sonde.relacher()
        recevoir(self.dump_contenu)
        if self.lever_dans_flux is not None:
            raise self.lever_dans_flux
        return self.dump_issue

    def alimenter(self, argv, env, morceaux, delai):
        nom, _nu = outil(argv)
        self.appels.append(("charger", list(argv)))
        self.vu["charger"] = {
            "argv": list(argv),
            "env": env,
            "contenu": b"".join(morceaux),
        }
        return self.chargement


class Base(unittest.TestCase):
    def assertMinuteriesSeulement(self, appels):
        """Sous `--status`, rien n'est détecté ni lancé hors de la lecture
        des minuteries."""
        self.assertTrue(appels)
        self.assertEqual(
            [a for a in appels if not lecture_de_minuterie(a)], []
        )

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.bac = os.path.realpath(d.name)
        self.wd = os.path.join(self.bac, "odoo")
        ecrire(os.path.join(self.wd, "run.sh"), "#!/bin/bash\n")
        self.data = os.path.join(self.bac, "data")
        self.conf = ecrire(
            os.path.join(self.wd, "config.conf"),
            f"[options]\ndata_dir = {self.data}\ndb_password = secret-demo\n",
        )
        self.filestore = os.path.join(self.data, "filestore", "demo_db")
        for nom in ("f0", "f1", "f2"):
            ecrire(os.path.join(self.filestore, "ab", nom), "piece " + nom)
        self.dest = os.path.join(self.bac, "sauvegardes")
        self.etat = os.path.join(self.bac, "etat")
        os.makedirs(self.dest)
        os.makedirs(self.etat)
        self.dossier = os.path.join(self.dest, "demo_db")
        verrous = os.path.join(self.bac, "verrous")
        os.makedirs(verrous)
        self.verrous = verrous
        self.systeme = FauxSysteme(self.bac, verrous)
        os.makedirs(self.systeme.dossier_pg)

    def lancer(self, *options, systeme=None):
        argv = ["--service", "erplibre_demo", "--dest", self.dest]
        argv += ["--state-dir", self.etat] + list(options)
        sortie, erreurs = io.StringIO(), io.StringIO()
        rapport = report.Rapport(flux=sortie, erreurs=erreurs, couleur=False)
        with (
            contextlib.redirect_stdout(sortie),
            contextlib.redirect_stderr(erreurs),
        ):
            code = ob.main(argv, systeme or self.systeme, rapport)
        self.sortie, self.erreurs = sortie.getvalue(), erreurs.getvalue()
        return code

    def noms(self):
        return (
            sorted(os.listdir(self.dossier))
            if os.path.isdir(self.dossier)
            else []
        )

    def zips(self):
        return [n for n in self.noms() if n.endswith(".zip")]

    def outils(self):
        return [nom for nom, _argv in self.systeme.appels]

    def etat_base(self):
        with open(os.path.join(self.etat, "demo_db", "state.json")) as f:
            return json.load(f)

    def fabriquer(self, moment, modules=None, membres=None, sidecar=True):
        """Une sauvegarde de demo_db au nom de l'outil, avec son sidecar."""
        os.makedirs(self.dossier, exist_ok=True)
        nom = retention.nom_sauvegarde("demo_db", moment)
        chemin = os.path.join(self.dossier, nom)
        manifeste = {
            "odoo_dump": "1",
            "db_name": "demo_db",
            "major_version": "18.0",
            "version": "18.0",
            "modules": modules if modules is not None else FAITS["modules"],
        }
        with zipfile.ZipFile(chemin, "w") as z:
            z.writestr("dump.sql", DUMP)
            z.writestr("manifest.json", json.dumps(manifeste))
            for membre, contenu in (
                membres
                if membres is not None
                else [("filestore/ab/f0", "a"), ("filestore/ab/f1", "b")]
            ):
                z.writestr(membre, contenu)
        if sidecar:
            somme = hashlib.sha256(open(chemin, "rb").read()).hexdigest()
            ecrire(chemin + ".sha256", f"{somme}  {nom}\n")
        return chemin


def lecture_de_minuterie(appel):
    """True si `appel` est un `systemctl show` d'une unité de sauvegarde
    planifiée : la seule commande que `--status` lance."""
    nom, argv = appel
    return (
        nom == "systemctl"
        and argv[:2] == ["systemctl", "show"]
        and argv[-1].startswith("erplibre-backup-")
    )


class TestSauvegarde(Base):
    def test_b1_contenu_nom_et_modes(self):
        self.systeme.faits["modules"]["sans_version"] = None
        self.assertEqual(self.lancer(), ob.CODE_OK, self.sortie + self.erreurs)
        zips = self.zips()
        self.assertEqual(len(zips), 1)
        self.assertTrue(RE_NOM.match(zips[0]), zips)
        chemin = os.path.join(self.dossier, zips[0])
        with zipfile.ZipFile(chemin) as z:
            self.assertEqual(
                z.namelist(),
                [
                    "dump.sql",
                    "manifest.json",
                    "filestore/ab/f0",
                    "filestore/ab/f1",
                    "filestore/ab/f2",
                ],
            )
            self.assertEqual(z.read("dump.sql"), DUMP)
            manifeste = json.loads(z.read("manifest.json"))
        self.assertEqual(
            manifeste,
            {
                "odoo_dump": "1",
                "db_name": "demo_db",
                "version": "18.0",
                "major_version": "18.0",
                "version_info": [18, 0, 0, "final", 0, ""],
                "pg_version": "16.0",
                "modules": {
                    "base": "18.0.1.3",
                    "web": "18.0.1.0",
                    "sans_version": None,
                },
            },
        )
        with open(chemin + ".sha256") as f:
            somme, nom = f.read().split()
        self.assertEqual(nom, zips[0])
        self.assertEqual(
            somme, hashlib.sha256(open(chemin, "rb").read()).hexdigest()
        )
        self.assertEqual(os.stat(chemin).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(chemin + ".sha256").st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.dossier).st_mode & 0o777, 0o700)
        etat = self.etat_base()
        self.assertEqual(etat["last_success"]["file"], chemin)
        self.assertEqual(etat["last_success"]["sha256"], somme)
        self.assertEqual(
            os.stat(os.path.join(self.etat, "demo_db", "state.json")).st_mode
            & 0o777,
            0o644,
        )

    def test_b2_version_pg_d_un_ancien_serveur(self):
        self.systeme.faits["server_version_num"] = 90624
        self.assertEqual(self.lancer(), ob.CODE_OK)
        with zipfile.ZipFile(os.path.join(self.dossier, self.zips()[0])) as z:
            self.assertEqual(
                json.loads(z.read("manifest.json"))["pg_version"], "9.6"
            )

    def _etat_ancien(self):
        os.makedirs(os.path.join(self.etat, "demo_db"))
        ecrire(
            os.path.join(self.etat, "demo_db", "state.json"),
            json.dumps({"last_success": {"time": 1, "file": "x.zip"}}),
        )

    def test_b3_pg_dump_en_echec(self):
        self._etat_ancien()
        self.systeme.dump_issue = (
            1,
            "pg_dump: error: connexion refusée",
            False,
        )
        self.assertEqual(self.lancer(), ob.CODE_ECHEC)
        self.assertIn("connexion refusée", self.sortie)
        self.assertEqual(self.noms(), [])
        etat = self.etat_base()
        self.assertEqual(etat["last_success"], {"time": 1, "file": "x.zip"})
        self.assertIn("connexion refusée", etat["last_failure"]["message"])

    def test_b3_dump_sans_marque_de_fin(self):
        self.systeme.dump_contenu = b"-- coupe\n"
        self.assertEqual(self.lancer(), ob.CODE_ECHEC)
        self.assertEqual(self.noms(), [])

    def test_b3_zip_qui_ne_se_relit_pas(self):
        with mock.patch.object(
            ob.odoo_instance,
            "verifier_sauvegarde",
            return_value=(False, ["unreadable"]),
        ):
            self.assertEqual(self.lancer(), ob.CODE_ECHEC)
        self.assertEqual(self.noms(), [])

    def test_b4_filestore_absent(self):
        import shutil

        shutil.rmtree(self.filestore)
        self.systeme.faits["stored_attachments"] = 0
        self.assertEqual(self.lancer(), ob.CODE_OK, self.sortie)
        self.assertIn("[ATTN]", self.sortie)
        os.remove(os.path.join(self.dossier, self.zips()[0]))
        self.systeme.faits["stored_attachments"] = 5
        self.systeme.appels.clear()
        self.assertEqual(self.lancer(), ob.CODE_ECHEC)
        self.assertNotIn("pg_dump", self.outils())
        self.assertEqual(self.zips(), [])
        self.assertIn(self.filestore, self.sortie)

    def test_b5_lien_symbolique_ecarte(self):
        cible = ecrire(os.path.join(self.bac, "secret.txt"), "secret")
        os.symlink(cible, os.path.join(self.filestore, "ab", "lien"))
        os.symlink(self.bac, os.path.join(self.filestore, "dossier_lien"))
        self.assertEqual(self.lancer(), ob.CODE_OK, self.sortie)
        with zipfile.ZipFile(os.path.join(self.dossier, self.zips()[0])) as z:
            noms = z.namelist()
        self.assertNotIn("filestore/ab/lien", noms)
        self.assertFalse(any("dossier_lien" in n for n in noms))
        self.assertIn("filestore/ab/lien", self.sortie)
        self.assertIn("[ATTN]", self.sortie)

    def test_b6_espace_insuffisant_avant_pg_dump(self):
        self.systeme.libre = 100
        self.assertEqual(self.lancer(), ob.CODE_REFUS)
        self.assertNotIn("pg_dump", self.outils())
        self.assertEqual(self.noms(), [])
        self.systeme.libre = 10**12
        self.systeme.espace_erreur = OSError(5, "statvfs impossible")
        self.assertEqual(self.lancer(), ob.CODE_REFUS)
        self.assertNotIn("pg_dump", self.outils())

    def test_b7_sous_root_runuser_et_secret_hors_argv(self):
        pgbin = os.path.join(self.bac, "pgbin")
        ecrire(os.path.join(pgbin, "pg_dump"), "")
        with open(self.conf, "a") as f:
            f.write(f"pg_path = {pgbin}\n")
        self.systeme.verbeux = True
        self.assertEqual(self.lancer(), ob.CODE_OK, self.sortie)
        vu = self.systeme.vu["pg_dump"]
        self.assertEqual(
            vu["argv"],
            [
                "runuser",
                "-u",
                "demo",
                "--",
                os.path.join(pgbin, "pg_dump"),
                "--no-owner",
                "demo_db",
            ],
        )
        self.assertEqual(vu["env"]["PGPASSWORD"], "secret-demo")
        self.assertEqual(vu["env"]["HOME"], self.systeme.home("demo"))
        self.assertNotIn("PGOPTIONS", vu["env"])
        requete = self.systeme.vu["psql"][0]
        self.assertEqual(requete["argv"][:4], ["runuser", "-u", "demo", "--"])
        self.assertIn(
            "default_transaction_read_only=on", requete["env"]["PGOPTIONS"]
        )
        for texte in (self.sortie, self.erreurs, " ".join(vu["argv"])):
            self.assertNotIn("secret-demo", texte)

    def test_b8_sous_le_compte_de_l_unite(self):
        self.systeme.euid_valeur = 1000
        self.systeme.courant = "demo"
        os.makedirs(self.dossier)
        os.makedirs(os.path.join(self.etat, "demo_db"))
        self.assertEqual(self.lancer(), ob.CODE_OK, self.sortie + self.erreurs)
        self.assertEqual(self.systeme.vu["pg_dump"]["argv"][0], "pg_dump")
        self.assertEqual(self.systeme.chowns, [])

    def test_b8_un_autre_compte_est_refuse_sauf_simulation(self):
        self.systeme.euid_valeur = 1000
        self.systeme.courant = "autre"
        self.assertEqual(self.lancer(), ob.CODE_REFUS)
        self.assertIn("demo", self.erreurs)
        self.assertEqual(self.lancer("--dry-run"), ob.CODE_OK, self.erreurs)
        self.assertIn(ob.t("unknown (requires sudo)"), self.sortie)
        self.assertIn(
            "runuser -u demo -- pg_dump --no-owner demo_db", self.sortie
        )
        self.assertIn("PGPASSWORD=***", self.sortie)
        self.assertNotIn("secret-demo", self.sortie)
        self.assertFalse(os.path.exists(self.dossier))
        self.assertEqual([n for n in self.outils() if n != "systemctl"], [])

    def test_simulation_sous_root_ne_cree_rien(self):
        self.assertEqual(
            self.lancer("--dry-run", "--copy-to", COPIE), ob.CODE_OK
        )
        self.assertIn("mkdir -m 0700 -- " + self.dossier, self.sortie)
        self.assertIn("rsync -a --partial", self.sortie)
        self.assertFalse(os.path.exists(self.dossier))
        self.assertNotIn("pg_dump", self.outils())

    def test_b9_verrou_pris(self):
        with lock.Verrou("erplibre-db-demo_db", self.verrous):
            self.assertEqual(self.lancer(), ob.CODE_VERROU)
        self.assertNotIn("pg_dump", self.outils())

    def test_b9_sauvegarder_sous_le_verrou_de_l_appelant(self):
        self.assertEqual(self.lancer(), ob.CODE_OK)
        self.assertIs(self.systeme.verrou_pendant_flux, True)

    def test_b10_interruption_retire_le_partiel_et_relache(self):
        for erreur in (KeyboardInterrupt(), ob.Interruption(signal.SIGTERM)):
            with self.subTest(erreur=type(erreur).__name__):
                self.systeme.lever_dans_flux = erreur
                self.assertEqual(self.lancer(), ob.CODE_INTERROMPU)
                self.assertEqual(self.zips(), [])
                self.assertFalse(
                    any(n.endswith(".partial") for n in self.noms())
                )
                with lock.Verrou("erplibre-db-demo_db", self.verrous):
                    pass

    def test_b11_sous_root_tout_est_donne_au_compte(self):
        self.assertEqual(self.lancer(), ob.CODE_OK)
        donnes = {
            os.path.basename(c) for c, u in self.systeme.chowns if u == "demo"
        }
        nom = self.zips()[0]
        self.assertIn("demo_db", donnes)
        self.assertIn(nom + ".partial", donnes)
        self.assertTrue(any(n.startswith("." + nom) for n in donnes))
        self.assertTrue(any(n.startswith(".state.") for n in donnes))
        # Le dossier commun reste à root.
        self.assertNotIn("sauvegardes", donnes)

    def test_b12_noms_refuses(self):
        for valeur in ("-x", "d" * 64, "a;b"):
            with self.subTest(valeur=valeur):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        ob.analyser(["--db", valeur])
                self.assertEqual(ctx.exception.code, 2)

    def test_partiel_oublie_retire_sous_le_verrou(self):
        oublie = ecrire(
            os.path.join(
                self.dossier, "demo_db_2031-03-01_03h00m00s.zip.partial"
            )
        )
        etranger = ecrire(os.path.join(self.dossier, "autre.zip.partial"))
        self.assertEqual(self.lancer(), ob.CODE_OK)
        self.assertFalse(os.path.exists(oublie))
        self.assertTrue(os.path.exists(etranger))

    def test_pas_une_base_odoo(self):
        self.systeme.faits = {"base": None, "server_version_num": 160004}
        self.assertEqual(self.lancer(), ob.CODE_ECHEC)
        self.assertNotIn("pg_dump", self.outils())


class TestFluxReel(Base):
    """La sauvegarde complète avec le vrai `flux` : un faux pg_dump,
    exécutable trouvé par `pg_path`, écrit son dump sur stdout."""

    def test_sauvegarde_par_un_vrai_processus(self):
        pgbin = os.path.join(self.bac, "pgbin")
        faux = ecrire(
            os.path.join(pgbin, "pg_dump"),
            "#!" + sys.executable + "\n"
            "import sys\n"
            "assert sys.argv[1:] == ['--no-owner', 'demo_db'], sys.argv\n"
            "sys.stdout.write('-- x\\n' * 200000)\n"
            "sys.stdout.write('-- PostgreSQL database dump complete\\n')\n",
        )
        os.chmod(faux, 0o755)
        with open(self.conf, "a") as f:
            f.write(f"pg_path = {pgbin}\n")
        self.systeme.euid_valeur = 1000
        self.systeme.courant = "demo"
        self.systeme.flux = lambda *a: ob.Systeme.flux(self.systeme, *a)
        self.assertEqual(self.lancer(), ob.CODE_OK, self.sortie + self.erreurs)
        with zipfile.ZipFile(os.path.join(self.dossier, self.zips()[0])) as z:
            dump = z.read("dump.sql")
        self.assertTrue(dump.endswith(b"dump complete\n"))
        self.assertEqual(len(dump), 5 * 200000 + 37)


class TestRetentionApresSauvegarde(Base):
    def test_seuls_nos_noms_sont_supprimes_avec_leur_empreinte(self):
        anciens = [
            self.fabriquer(datetime.datetime(2030, 1, d, 3)) for d in (1, 2)
        ]
        etrangers = [
            ecrire(os.path.join(self.dossier, n))
            for n in (
                "notes.zip",
                "demo_db_bar_2030-01-01_03h00m00s.zip",
                "orphelin.zip.sha256",
            )
        ]
        code = self.lancer(
            "--keep-daily",
            "1",
            "--keep-weekly",
            "0",
            "--keep-monthly",
            "0",
            "--keep-recent-days",
            "0",
        )
        self.assertEqual(code, ob.CODE_OK, self.sortie)
        for chemin in anciens:
            self.assertFalse(os.path.exists(chemin))
            self.assertFalse(os.path.exists(chemin + ".sha256"))
        for chemin in etrangers:
            self.assertTrue(os.path.exists(chemin))
        self.assertEqual(len(self.zips()), 3)


class TestCopie(Base):
    def test_c1_commande_rsync(self):
        self.assertEqual(
            self.lancer("--copy-to", COPIE), ob.CODE_OK, self.sortie
        )
        motif = "/demo_db_" + retention.GLOB_HORODATAGE + ".zip"
        self.assertEqual(
            self.systeme.vu["rsync"][0]["argv"],
            [
                "runuser",
                "-u",
                "demo",
                "--",
                "rsync",
                "-a",
                "--partial-dir=.rsync-partial",
                "--delay-updates",
                "--include=" + motif,
                "--include=" + motif + ".sha256",
                "--exclude=*",
                "-e",
                "ssh -o BatchMode=yes -o ConnectTimeout=20",
                self.dossier + "/",
                "backup@backup.example.org:/srv/backups/demo_db/",
            ],
        )
        self.assertTrue(self.etat_base()["last_copy"]["ok"])

    def test_c2_echec_de_la_copie(self):
        ancien = self.fabriquer(datetime.datetime(2030, 1, 1, 3))
        self.systeme.rsync_code = 23
        code = self.lancer(
            "--copy-to",
            COPIE,
            "--keep-daily",
            "1",
            "--keep-weekly",
            "0",
            "--keep-monthly",
            "0",
            "--keep-recent-days",
            "0",
        )
        self.assertEqual(code, ob.CODE_ECHEC)
        self.assertEqual(len(self.zips()), 1)
        etat = self.etat_base()
        self.assertIn("last_success", etat)
        self.assertFalse(etat["last_copy"]["ok"])
        self.assertIn("23", etat["last_copy"]["message"])
        # La rétention a tourné quand même.
        self.assertFalse(os.path.exists(ancien))

    def test_c3_destination_refusee(self):
        for valeur in ("-e touch /tmp/x", "rien", "hote:relatif"):
            with self.subTest(valeur=valeur):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        ob.analyser(["--copy-to", valeur])
                self.assertEqual(ctx.exception.code, 2)
        self.assertTrue(ob.copie_valide("/mnt/copie"))

    def test_c4_sans_copie_pas_de_rsync(self):
        self.assertEqual(self.lancer(), ob.CODE_OK)
        self.assertNotIn("rsync", self.outils())


class TestCopieApresRetention(Base):
    """BKP-01, BKP-17-V : copie après la rétention, rattrapage, élagage."""

    GARDE_UNE = (
        "--keep-daily",
        "1",
        "--keep-weekly",
        "0",
        "--keep-monthly",
        "0",
        "--keep-recent-days",
        "0",
    )

    def test_apres_la_retention_tout_le_dossier(self):
        ancien = self.fabriquer(datetime.datetime(2030, 1, 1, 3))
        code = self.lancer("--copy-to", COPIE, *self.GARDE_UNE)
        self.assertEqual(code, ob.CODE_OK, self.sortie)
        ordre = self.outils()
        self.assertGreater(ordre.index("rsync"), ordre.index("pg_dump"))
        # La rétention a déjà retiré l'ancienne : rsync ne la voit plus.
        (source,) = self.systeme.source_copie
        self.assertNotIn(os.path.basename(ancien), source)
        self.assertEqual(len([n for n in source if n.endswith(".zip")]), 1)

    def test_rattrape_une_copie_manquee(self):
        """Le dossier entier part : une archive dont la copie a échoué à
        un passage est renvoyée au suivant."""
        manquee = self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.assertEqual(self.lancer("--copy-to", COPIE), ob.CODE_OK)
        (source,) = self.systeme.source_copie
        self.assertIn(os.path.basename(manquee), source)
        argv = self.systeme.vu["rsync"][0]["argv"]
        self.assertEqual(argv[-2], self.dossier + "/")
        self.assertNotIn("--partial", argv)
        self.assertNotIn("--delete", argv)

    GARDE_DEUX = (
        "--keep-daily",
        "2",
        "--keep-weekly",
        "0",
        "--keep-monthly",
        "0",
        "--keep-recent-days",
        "0",
    )

    @staticmethod
    def nom(*moment):
        return retention.nom_sauvegarde("demo_db", datetime.datetime(*moment))

    def poser_distants(self, *noms):
        self.systeme.distants = sorted(
            [n for n in noms] + [n + ".sha256" for n in noms] + ["notes.txt"]
        )

    def elaguer(self, *options):
        return self.lancer("--copy-to", COPIE, "--copy-prune", *options)

    def test_elagage_suit_la_retention_distante(self):
        """La rétention juge les archives listées à la destination : deux
        jours gardés, les deux plus anciennes partent, chacune avec son
        empreinte, dans un rsync qui ne supprime qu'elles."""
        fev = [self.nom(2031, 2, j, 3) for j in (1, 2, 3)]
        self.poser_distants(*fev)
        code = self.elaguer(*self.GARDE_DEUX)
        self.assertEqual(code, ob.CODE_OK, self.sortie)
        self.assertEqual(
            self.systeme.elagages,
            [[fev[0], fev[0] + ".sha256", fev[1], fev[1] + ".sha256"]],
        )
        copie, liste, elagage = [a["argv"] for a in self.systeme.vu["rsync"]]
        self.assertNotIn("--delete", copie)
        self.assertIn("--list-only", liste)
        for drapeau in ("--delete", "--existing", "--ignore-existing"):
            self.assertIn(drapeau, elagage)
        self.assertIn("--max-delete=4", elagage)
        self.assertNotIn("--delete-excluded", elagage)
        self.assertLess(
            elagage.index("--include=/" + fev[0]), elagage.index("--exclude=*")
        )
        self.assertIn(fev[2], self.systeme.distants)
        self.assertIn("notes.txt", self.systeme.distants)
        self.assertTrue(self.etat_base()["last_copy"]["ok"])

    def test_dossier_local_reconstruit_ne_vide_pas_la_destination(self):
        """Une seule archive locale, trois anciennes à la destination que
        la rétention par défaut garde : rien n'est supprimé."""
        fev = [self.nom(2031, 2, j, 3) for j in (1, 2, 3)]
        self.poser_distants(*fev)
        self.assertEqual(self.elaguer(), ob.CODE_OK, self.sortie)
        self.assertEqual(self.systeme.elagages, [])
        for nom in fev:
            self.assertIn(nom, self.systeme.distants)
        self.assertTrue(self.etat_base()["last_copy"]["ok"])

    def test_archive_locale_jamais_supprimee_a_distance(self):
        """Une archive plus récente du même jour, venue d'ailleurs, ferait
        retirer la locale par la rétention distante : elle reste."""
        locale = os.path.basename(
            self.fabriquer(datetime.datetime(2031, 3, 9, 2))
        )
        self.poser_distants(self.nom(2031, 3, 9, 5))
        self.assertEqual(self.elaguer(*self.GARDE_DEUX), ob.CODE_OK)
        self.assertEqual(self.systeme.elagages, [])
        self.assertIn(locale, self.systeme.distants)

    def test_borne_atteinte_est_un_avertissement(self):
        anciens = [self.nom(2031, 1, j, 3) for j in range(1, 6)]
        self.poser_distants(*anciens)
        code = self.elaguer(*self.GARDE_UNE, "--copy-prune-max", "2")
        self.assertEqual(code, ob.CODE_OK, self.sortie)
        (vises,) = self.systeme.elagages
        self.assertEqual(
            vises,
            [
                anciens[0],
                anciens[0] + ".sha256",
                anciens[1],
                anciens[1] + ".sha256",
            ],
        )
        self.assertIn("[ATTN]", self.sortie)
        self.assertIn("--copy-prune-max", self.sortie)
        self.assertFalse(self.etat_base()["last_copy"]["ok"])

    def test_liste_ou_elagage_en_echec_est_un_avertissement(self):
        self.poser_distants(self.nom(2031, 1, 1, 3))
        for attribut in ("liste_code", "elagage_code"):
            with self.subTest(attribut=attribut):
                setattr(self.systeme, attribut, 12)
                self.systeme.horloge += 3600
                code = self.elaguer(*self.GARDE_UNE)
                setattr(self.systeme, attribut, 0)
                self.assertEqual(code, ob.CODE_OK, self.sortie)
                self.assertIn("[ATTN]", self.sortie)
                etat = self.etat_base()["last_copy"]
                self.assertFalse(etat["ok"])
                self.assertIn("12", etat["message"])

    def test_code_25_sans_elagage_reste_un_echec(self):
        self.systeme.rsync_code = 25
        self.assertEqual(self.lancer("--copy-to", COPIE), ob.CODE_ECHEC)

    def test_nom_hors_outil_refuse_a_l_elagage(self):
        with self.assertRaises(ValueError):
            ob.argv_elagage_copie(self.cible(), COPIE, ["notes.zip"])

    def test_noms_listes(self):
        sortie = (
            "drwxr-xr-x          4,096 2031/03/10 03:00:00 .\n"
            "-rw-r--r--          1,234 2031/03/10 03:00:00 a.zip\n"
            "lrwxrwxrwx              5 2031/03/10 03:00:00 l -> a.zip\n"
        )
        self.assertEqual(ob.noms_listes(sortie), ["a.zip"])

    def cible(self):
        return ob.Cible(
            base="demo_db",
            dossier=self.dossier,
            etat_dir=self.etat,
            dossier_etat=os.path.join(self.etat, "demo_db"),
            home=os.path.join(self.bac, "home_demo"),
        )

    def test_dossier_local_vide_n_elague_rien(self):
        os.makedirs(self.dossier)
        os.makedirs(os.path.join(self.etat, "demo_db"))
        ecrire(os.path.join(self.dossier, "notes.zip"))
        rapport = report.Rapport(
            flux=io.StringIO(), erreurs=io.StringIO(), couleur=False
        )
        self.assertFalse(
            ob.copier(self.cible(), self.systeme, rapport, COPIE, True)
        )
        self.assertNotIn("rsync", self.outils())
        self.assertFalse(self.etat_base()["last_copy"]["ok"])

    def test_dossier_local_illisible_n_elague_rien(self):
        os.makedirs(os.path.join(self.etat, "demo_db"))
        rapport = report.Rapport(
            flux=io.StringIO(), erreurs=io.StringIO(), couleur=False
        )
        # Le dossier de la base n'existe pas : listdir lève.
        self.assertFalse(
            ob.copier(self.cible(), self.systeme, rapport, COPIE, True)
        )
        self.assertNotIn("rsync", self.outils())

    def test_simulation_montre_la_commande(self):
        code = self.lancer("--copy-to", COPIE, "--copy-prune", "--dry-run")
        self.assertEqual(code, ob.CODE_OK, self.sortie)
        self.assertIn("--partial-dir=.rsync-partial", self.sortie)
        self.assertIn("rsync --list-only", self.sortie)
        self.assertIn(
            ob.t(
                "then delete there the backups this retention does not keep,"
                " except those kept locally, at most {count} per run"
            ).format(count=20),
            self.sortie,
        )
        self.assertNotIn("--delete", self.sortie)
        self.assertNotIn("rsync", self.outils())

    def test_borne_nulle_refusee(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                ob.analyser(["--copy-prune-max", "0"])
        self.assertEqual(ctx.exception.code, 2)

    def test_nom_de_base_invalide(self):
        cible = self.cible()
        cible.base = "demo;id"
        with self.assertRaises(ValueError):
            ob.argv_copie(cible, COPIE)


class TestAutoBackup(Base):
    """Les crons `auto_backup` actifs : signalés et notés pour --status."""

    def test_signale_et_note(self):
        self.systeme.auto_backup = 2
        self.assertEqual(self.lancer(), ob.CODE_OK, self.sortie)
        self.assertIn("[ATTN]", self.sortie)
        self.assertIn("auto_backup", self.sortie)
        self.assertEqual(self.etat_base()["auto_backup_crons"]["count"], 2)

    def test_aucun_cron(self):
        self.assertEqual(self.lancer(), ob.CODE_OK)
        self.assertNotIn("auto_backup", self.sortie)
        self.assertEqual(self.etat_base()["auto_backup_crons"]["count"], 0)

    def test_cron_sans_configuration_ne_compte_pas(self):
        """auto_backup installe sa tâche active : sans enregistrement
        `db.backup`, elle ne sauvegarde rien."""
        self.systeme.auto_backup = 1
        self.systeme.auto_backup_config = {"db.backup": 0}
        self.assertEqual(self.lancer(), ob.CODE_OK)
        self.assertNotIn("[ATTN]", self.sortie)
        self.assertEqual(self.etat_base()["auto_backup_crons"]["count"], 0)

    def test_auto_database_backup(self):
        self.systeme.auto_backup = {"db.backup.configure": 3, "db.backup": 1}
        self.systeme.auto_backup_config = {"db.backup": 0}
        self.assertEqual(self.lancer(), ob.CODE_OK)
        self.assertIn(ob._message_auto_backup("demo_db", 3), self.sortie)
        self.assertEqual(self.etat_base()["auto_backup_crons"]["count"], 3)

    def test_requete_en_echec_ne_note_rien(self):
        self.systeme.auto_backup = None
        self.assertEqual(self.lancer(), ob.CODE_OK)
        self.assertNotIn("auto_backup_crons", self.etat_base())

    def test_simulation_signale_sans_noter(self):
        self.systeme.auto_backup = 1
        self.assertEqual(self.lancer("--dry-run"), ob.CODE_OK)
        self.assertIn("auto_backup", self.sortie)
        self.assertFalse(os.path.exists(os.path.join(self.etat, "demo_db")))


class TestEtat(Base):
    def ecrire_etat(self, base, donnees):
        return ecrire(
            os.path.join(self.etat, base, "state.json"), json.dumps(donnees)
        )

    def statut(self, *options):
        sortie, erreurs = io.StringIO(), io.StringIO()
        rapport = report.Rapport(flux=sortie, erreurs=erreurs, couleur=False)
        code = ob.main(
            ["--status", "--state-dir", self.etat] + list(options),
            self.systeme,
            rapport,
        )
        self.sortie, self.erreurs = sortie.getvalue(), erreurs.getvalue()
        return code

    def test_s1_ages(self):
        fichier = ecrire(os.path.join(self.dossier, "demo_db_x.zip"))
        for heures, attendu in ((25, ob.CODE_OK), (27, ob.CODE_ECHEC)):
            with self.subTest(heures=heures):
                self.ecrire_etat(
                    "demo_db",
                    {
                        "last_success": {
                            "time": HORLOGE - heures * 3600,
                            "file": fichier,
                            "size": 10,
                        }
                    },
                )
                self.assertEqual(self.statut(), attendu, self.sortie)
        os.remove(fichier)
        self.ecrire_etat(
            "demo_db",
            {"last_success": {"time": HORLOGE - 3600, "file": fichier}},
        )
        self.assertEqual(self.statut(), ob.CODE_OK)
        self.assertIn("[ATTN]", self.sortie)

    def test_s1_aucun_etat(self):
        self.assertEqual(self.statut(), ob.CODE_ECHEC)
        self.assertIn("[FAIL]", self.sortie)
        self.ecrire_etat("demo_db", {"last_failure": {"time": HORLOGE}})
        self.assertEqual(self.statut(), ob.CODE_ECHEC)

    def test_s2_echec_plus_recent(self):
        self.ecrire_etat(
            "demo_db",
            {
                "last_success": {"time": HORLOGE - 7200, "file": "/x"},
                "last_failure": {"time": HORLOGE - 60, "message": "boom"},
                "last_copy": {"time": HORLOGE, "ok": False, "message": "r23"},
            },
        )
        self.assertEqual(self.statut(), ob.CODE_OK)
        self.assertIn("boom", self.sortie)
        self.assertIn("r23", self.sortie)

    def test_s3_plusieurs_bases_et_filtre(self):
        self.ecrire_etat("demo_db", {"last_success": {"time": HORLOGE}})
        self.ecrire_etat(
            "autre_db", {"last_success": {"time": HORLOGE - 10**6}}
        )
        self.assertEqual(self.statut(), ob.CODE_ECHEC)
        self.assertIn("demo_db", self.sortie)
        self.assertIn("autre_db", self.sortie)
        self.assertEqual(self.statut("--db", "demo_db"), ob.CODE_OK)
        self.assertNotIn("autre_db", self.sortie)
        self.assertEqual(self.statut("--max-age", "1000"), ob.CODE_OK)

    def test_s4_ecriture_atomique(self):
        os.makedirs(os.path.join(self.etat, "demo_db"))
        cible = ob.Cible(
            base="demo_db",
            etat_dir=self.etat,
            dossier_etat=os.path.join(self.etat, "demo_db"),
        )
        ob.ecrire_etat(cible, self.systeme, {"last_success": {"time": 5}})
        with mock.patch.object(ob.os, "fchmod", side_effect=OSError(5, "x")):
            with self.assertRaises(OSError):
                ob.ecrire_etat(cible, self.systeme, {"last_failure": {}})
        self.assertEqual(
            os.listdir(os.path.join(self.etat, "demo_db")), ["state.json"]
        )
        self.assertEqual(self.etat_base()["last_success"], {"time": 5})

    def test_dossier_illisible(self):
        with mock.patch.object(ob.os, "listdir", side_effect=PermissionError):
            self.assertEqual(self.statut(), ob.CODE_REFUS)
        self.assertIn("sudo", self.erreurs)


MINUTERIE = "erplibre-backup-demo_db.timer"
SERVICE_SAUVEGARDE = "erplibre-backup-demo_db.service"


class TestEtatComplet(TestEtat):
    """BKP-02, 03, 04, 05, 14 et les crons auto_backup sous --status."""

    def setUp(self):
        super().setUp()
        self.fichier = self.fabriquer(datetime.datetime(2031, 3, 10, 2))
        self.precedent = self.fabriquer(datetime.datetime(2031, 3, 9, 2))
        self.etat_demo = {
            "last_success": {"time": HORLOGE - 3600, "file": self.fichier},
            "last_restore_test": {
                "time": HORLOGE - 86400,
                "ok": True,
                "file": self.fichier,
            },
        }

    def poser_minuterie(self, execstart_argv=None, active="active"):
        argv = execstart_argv
        if argv is None:
            argv = [
                os.path.join(self.wd, "run.sh"),
                os.path.join(self.wd, "config.conf"),
                "--copy-to",
                COPIE,
            ]
        self.systeme.unites[MINUTERIE] = {
            "LoadState": "loaded",
            "ActiveState": active,
        }
        self.systeme.unites[SERVICE_SAUVEGARDE] = {
            "ExecStart": "{ path=x ; argv[]=" + " ".join(argv) + " ; }"
        }

    def test_archives_comptees(self):
        self.ecrire_etat("demo_db", self.etat_demo)
        self.poser_minuterie()
        self.assertEqual(self.statut(), ob.CODE_OK, self.sortie)
        self.assertIn(ob.t("Backups kept"), self.sortie)
        # La taille des seuls zips, empreintes exclues.
        octets = sum(
            os.path.getsize(p) for p in (self.fichier, self.precedent)
        )
        self.assertIn(
            ob.t("{count} in {path} ({size})").format(
                count=2, path=self.dossier, size=ob.humain(octets)
            ),
            self.sortie,
        )
        self.assertNotIn("[ATTN]", self.sortie)

    def test_dossier_des_archives_illisible(self):
        self.ecrire_etat("demo_db", self.etat_demo)
        self.poser_minuterie()
        reel = os.listdir

        def lister(chemin):
            if chemin == self.dossier:
                raise PermissionError(13, "refusé")
            return reel(chemin)

        with mock.patch.object(ob.os, "listdir", side_effect=lister):
            self.assertEqual(self.statut(), ob.CODE_OK)
        self.assertIn("[ATTN]", self.sortie)
        self.assertIn("sudo", self.sortie)

    def test_minuterie_absente(self):
        self.ecrire_etat("demo_db", self.etat_demo)
        self.assertEqual(self.statut(), ob.CODE_OK)
        self.assertIn(
            ob.t(
                "{database}: no scheduled backup ({timer} is not installed)."
            ).format(database="demo_db", timer=MINUTERIE),
            self.sortie,
        )

    def test_minuterie_inactive_et_sans_copie(self):
        self.ecrire_etat("demo_db", self.etat_demo)
        self.poser_minuterie(
            [os.path.join(self.wd, "run.sh")], active="inactive"
        )
        self.assertEqual(self.statut(), ob.CODE_OK)
        self.assertIn(
            ob.t("{database}: {timer} is {state}, not active.").format(
                database="demo_db", timer=MINUTERIE, state="inactive"
            ),
            self.sortie,
        )
        self.assertIn("--copy-to", self.sortie)

    def test_programme_disparu(self):
        self.ecrire_etat("demo_db", self.etat_demo)
        self.poser_minuterie(["/srv/ancien/python", "outil.py", "--copy-to"])
        self.assertEqual(self.statut(), ob.CODE_ECHEC)
        self.assertIn("/srv/ancien/python", self.sortie)

    def test_programme_hors_de_portee_du_compte(self):
        """Un ExecStart sous un dossier personnel fermé (EACCES) n'est pas
        « disparu » : --status sans sudo ne le juge pas."""
        self.ecrire_etat("demo_db", self.etat_demo)
        self.poser_minuterie()
        reel = os.stat

        def examiner(chemin, *a, **k):
            if chemin == os.path.join(self.wd, "run.sh"):
                raise PermissionError(13, "refusé")
            return reel(chemin, *a, **k)

        with mock.patch.object(ob.os, "stat", side_effect=examiner):
            self.assertEqual(self.statut(), ob.CODE_OK, self.sortie)
        self.assertNotIn("[FAIL]", self.sortie)
        self.assertIn(os.path.join(self.wd, "run.sh"), self.sortie)

    def test_systemctl_muet(self):
        self.ecrire_etat("demo_db", self.etat_demo)
        self.systeme.unites[MINUTERIE] = None
        self.assertEqual(self.statut(), ob.CODE_OK)
        self.assertNotIn("[FAIL]", self.sortie)

    def test_seuil_du_calendrier_tant_que_la_minuterie_existe(self):
        donnees = dict(self.etat_demo)
        donnees["last_success"] = {
            "time": HORLOGE - 10 * 3600,
            "file": self.fichier,
        }
        donnees[ob.CLE_SEUIL] = 9
        self.ecrire_etat("demo_db", donnees)
        self.poser_minuterie()
        self.assertEqual(self.statut(), ob.CODE_ECHEC, self.sortie)
        # --max-age l'emporte.
        self.assertEqual(self.statut("--max-age", "12"), ob.CODE_OK)
        # Minuterie retirée : le seuil noté ne vaut plus, 26 h par défaut.
        self.systeme.unites.clear()
        self.assertEqual(self.statut(), ob.CODE_OK, self.sortie)

    def test_essai_de_restauration(self):
        self.poser_minuterie()
        cas = (
            ({"time": HORLOGE - 86400, "ok": True}, ob.CODE_OK, False),
            ({"time": HORLOGE - 9 * 86400, "ok": True}, ob.CODE_OK, True),
            (None, ob.CODE_OK, True),
            (
                {"time": HORLOGE - 3600, "ok": False, "message": "boum"},
                ob.CODE_ECHEC,
                False,
            ),
        )
        for essai, code, attn in cas:
            with self.subTest(essai=essai):
                donnees = dict(self.etat_demo)
                donnees.pop("last_restore_test")
                if essai is not None:
                    donnees["last_restore_test"] = essai
                self.ecrire_etat("demo_db", donnees)
                self.assertEqual(self.statut(), code, self.sortie)
                self.assertEqual("[ATTN]" in self.sortie, attn, self.sortie)
                self.assertEqual(
                    "--test-restore --db demo_db" in self.sortie,
                    code != ob.CODE_OK or attn,
                )
        self.assertIn("boum", self.sortie)

    def test_age_max_de_l_essai(self):
        """`--max-restore-age` déplace l'avertissement d'un essai réussi
        mais ancien, sans jamais faire échouer --status."""
        self.poser_minuterie()
        donnees = dict(self.etat_demo)
        donnees["last_restore_test"] = {
            "time": HORLOGE - 9 * 86400,
            "ok": True,
        }
        self.ecrire_etat("demo_db", donnees)
        self.assertEqual(self.statut(), ob.CODE_OK, self.sortie)
        self.assertIn("--test-restore --db demo_db", self.sortie)
        self.assertEqual(self.statut("--max-restore-age", "10"), ob.CODE_OK)
        self.assertNotIn("[ATTN]", self.sortie)
        self.assertNotIn("--test-restore --db demo_db", self.sortie)
        self.assertEqual(self.statut("--max-restore-age", "8"), ob.CODE_OK)
        self.assertIn("[ATTN]", self.sortie)

    def test_fuseau_affiche(self):
        self.ecrire_etat("demo_db", self.etat_demo)
        self.poser_minuterie()
        self.statut()
        self.assertIn(ob.horodatage(HORLOGE - 3600), self.sortie)
        self.assertRegex(ob.horodatage(HORLOGE), r" [+-]\d{4}")

    def test_crons_auto_backup_notes(self):
        donnees = dict(self.etat_demo)
        donnees["auto_backup_crons"] = {"time": HORLOGE, "count": 1}
        self.ecrire_etat("demo_db", donnees)
        self.poser_minuterie()
        self.assertEqual(self.statut(), ob.CODE_OK)
        self.assertIn("auto_backup", self.sortie)
        self.assertIn("[ATTN]", self.sortie)

    def test_en_tete_de_la_sauvegarde_porte_le_fuseau(self):
        self.lancer("--dry-run")
        self.assertIn(ob.horodatage(HORLOGE), self.sortie)


class TestRestaurationEssai(Base):
    def essai(self, *options):
        return self.lancer("--test-restore", *options)

    def test_t1_chemin_heureux(self):
        self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.assertEqual(self.essai(), ob.CODE_OK, self.sortie + self.erreurs)
        ordre = [
            n for n in self.outils() if n in ("createdb", "charger", "dropdb")
        ]
        self.assertEqual(ordre, ["createdb", "charger", "dropdb"])
        temporaire = "demo_db_restoretest_20310310030000"
        for nom, argv in self.systeme.appels:
            if nom in ("createdb", "dropdb"):
                self.assertEqual(argv[-1], temporaire)
                self.assertEqual(argv[-2], "--")
            if nom == "charger":
                self.assertEqual(argv[argv.index("-d") + 1], temporaire)
        self.assertEqual(self.systeme.vu["charger"]["contenu"], DUMP)
        self.assertEqual(self.systeme.bases, {"postgres", "demo_db"})
        self.assertFalse(
            any(n.startswith(".restoretest-") for n in self.noms())
        )
        self.assertEqual(
            self.systeme.sous_compte, [("demo", "essayer_filestore")]
        )

    def test_t2_nom_deja_pris(self):
        self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.systeme.bases.add("demo_db_restoretest_20310310030000")
        self.assertEqual(self.essai(), ob.CODE_ECHEC)
        self.assertNotIn("createdb", self.outils())
        self.assertNotIn("dropdb", self.outils())
        self.systeme.bases.discard("demo_db_restoretest_20310310030000")
        self.systeme.createdb_code = 1
        self.assertEqual(self.essai(), ob.CODE_ECHEC)
        self.assertIn("CREATEDB", self.sortie)
        self.assertNotIn("dropdb", self.outils())

    def test_t3_erreur_sql_grave(self):
        self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.systeme.chargement = (
            0,
            [
                "psql:<stdin>:3: ERROR:  must be owner of extension plpgsql",
                'psql:<stdin>:9: ERROR:  relation "x" already exists',
            ],
            False,
        )
        self.assertEqual(self.essai(), ob.CODE_ECHEC)
        self.assertIn("dropdb", self.outils())
        self.assertIn('relation "x"', self.sortie)

    def test_t3_erreur_benigne_seule(self):
        self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.systeme.chargement = (
            0,
            ["psql:<stdin>:3: ERROR:  must be owner of extension plpgsql"],
            False,
        )
        self.assertEqual(self.essai(), ob.CODE_OK, self.sortie)

    def test_t4_modules_differents(self):
        self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.systeme.controle["modules"] = ["base"]
        self.assertEqual(self.essai(), ob.CODE_ECHEC)
        self.assertIn("web", self.sortie)
        self.assertIn("dropdb", self.outils())

    def test_t5_nom_long(self):
        """Le nom temporaire passé à createdb ET à dropdb est raccourci à
        63 octets, horodatage entier : PostgreSQL tronquerait sinon en
        silence, et le contrôle « nom déjà pris » viserait un autre nom."""
        base = "d" * 60
        self.systeme.proprietes["ExecStart"] = self.systeme.proprietes[
            "ExecStart"
        ].replace("demo_db", base)
        dossier = os.path.join(self.dest, base)
        os.makedirs(dossier)
        nom = base + "_2031-03-09_03h00m00s.zip"
        with zipfile.ZipFile(os.path.join(dossier, nom), "w") as z:
            z.writestr("dump.sql", DUMP)
            z.writestr(
                "manifest.json",
                json.dumps({"db_name": base, "modules": FAITS["modules"]}),
            )
        self.assertEqual(self.essai(), ob.CODE_OK, self.sortie)
        temporaire = postgres.nom_temporaire(base, "20310310030000")
        self.assertEqual(len(temporaire.encode()), 63)
        self.assertTrue(temporaire.endswith("_restoretest_20310310030000"))
        vus = {
            nom: [a[-1] for n, a in self.systeme.appels if n == nom]
            for nom in ("createdb", "dropdb")
        }
        self.assertEqual(
            vus, {"createdb": [temporaire], "dropdb": [temporaire]}
        )

    def test_t6_empreinte(self):
        chemin = self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        ecrire(chemin + ".sha256", "0" * 64 + "  x.zip\n")
        self.assertEqual(self.essai(), ob.CODE_ECHEC)
        self.assertNotIn("createdb", self.outils())
        os.remove(chemin + ".sha256")
        self.assertEqual(self.essai(), ob.CODE_OK)
        self.assertIn("[ATTN]", self.sortie)

    def test_t7_le_plus_recent_par_le_nom_et_file(self):
        ancien = self.fabriquer(
            datetime.datetime(2031, 3, 1, 3), modules={"base": "1"}
        )
        recent = self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        os.utime(recent, (1, 1))
        self.assertEqual(self.essai(), ob.CODE_OK, self.sortie)
        self.assertIn(recent, self.sortie)
        self.assertEqual(self.essai("--file", ancien), ob.CODE_ECHEC)
        self.assertIn(ancien, self.sortie)

    def test_aucune_sauvegarde(self):
        self.assertEqual(self.essai(), ob.CODE_ECHEC)
        self.assertNotIn("createdb", self.outils())


class TestEssaiNote(Base):
    """BKP-02 : l'issue de --test-restore dans l'état, jamais en
    simulation ; M08 : les marqueurs checklist/ ne sont pas des pièces
    jointes."""

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.etat, "demo_db"))

    def test_reussite_notee(self):
        chemin = self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.systeme.controle["stored_files"] = 2
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_OK)
        essai = self.etat_base()["last_restore_test"]
        self.assertEqual(
            essai,
            {"time": int(HORLOGE), "ok": True, "file": chemin, "message": ""},
        )

    def test_echec_note_avec_son_message(self):
        self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.systeme.controle["tables"] = 0
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_ECHEC)
        essai = self.etat_base()["last_restore_test"]
        self.assertFalse(essai["ok"])
        self.assertEqual(
            essai["message"], ob.t("The restored database has no table.")
        )

    def test_fichier_hors_de_la_chaine_non_note(self):
        """Un essai sur un fichier qui n'est pas une sauvegarde de la base
        dans son dossier ne compte pas pour --status."""
        chemin = self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        ailleurs = os.path.join(self.bac, "rangees")
        os.makedirs(ailleurs)
        copie = os.path.join(ailleurs, os.path.basename(chemin))
        shutil.copy(chemin, copie)
        renomme = os.path.join(self.dossier, "demo_db_ancienne.zip")
        shutil.copy(chemin, renomme)
        for fichier in (copie, renomme):
            with self.subTest(fichier=fichier):
                code = self.lancer("--test-restore", "--file", fichier)
                self.assertEqual(code, ob.CODE_OK, self.sortie)
                self.assertFalse(
                    os.path.exists(
                        os.path.join(self.etat, "demo_db", "state.json")
                    )
                )
                self.assertIn(
                    ob.t(
                        "{path} is not a backup of {database} in {folder}:"
                        " --status does not count this test restore."
                    ).format(
                        path=fichier, database="demo_db", folder=self.dossier
                    ),
                    self.sortie,
                )
        self.assertEqual(self.lancer("--test-restore", "--file", chemin), 0)
        self.assertEqual(self.etat_base()["last_restore_test"]["file"], chemin)

    def test_simulation_ne_note_rien(self):
        self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.assertEqual(self.lancer("--test-restore", "--dry-run"), 0)
        self.assertFalse(
            os.path.exists(os.path.join(self.etat, "demo_db", "state.json"))
        )

    def test_marqueurs_et_piece_manquante(self):
        """Deux pièces référencées, une seule dans l'archive, plus deux
        marqueurs : le manque se voit malgré les marqueurs."""
        self.fabriquer(
            datetime.datetime(2031, 3, 9, 3),
            membres=[
                ("filestore/ab/f0", "a"),
                ("filestore/checklist/ab/f0", ""),
                ("filestore/checklist/ab/f1", ""),
            ],
        )
        self.systeme.controle["stored_files"] = 2
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_OK)
        self.assertIn(
            ob.t(
                "The database references {expected} stored files, the"
                " backup holds {count}."
            ).format(expected=2, count=1),
            self.sortie,
        )

    def test_marqueurs_seuls_sans_manque(self):
        self.fabriquer(
            datetime.datetime(2031, 3, 9, 3),
            membres=[
                ("filestore/ab/f0", "a"),
                ("filestore/ab/f1", "b"),
                ("filestore/checklist/ab/f1", ""),
            ],
        )
        self.systeme.controle["stored_files"] = 2
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_OK)
        self.assertNotIn("[ATTN]", self.sortie)
        self.assertTrue(ob.est_marqueur_gc("filestore/checklist/ab/f1"))
        self.assertFalse(ob.est_marqueur_gc("filestore/ab/checklist"))


def fabriquer_tar_xz(chemin, membres, liens=(), sidecar=True):
    """Un `.tar.xz` comme l'outil antérieur : dump.sql, manifest.json et
    filestore/ à la racine, dossiers compris ; `liens` ajoute des liens
    symboliques (nom, cible)."""
    import tarfile

    manifeste = {
        "odoo_dump": "1",
        "db_name": "demo_db",
        "major_version": "18.0",
        "version": "18.0",
        "modules": FAITS["modules"],
    }
    with tarfile.open(chemin, "w:xz") as tar:

        def ajouter(nom, contenu):
            donnees = contenu.encode() if isinstance(contenu, str) else contenu
            info = tarfile.TarInfo(nom)
            info.size = len(donnees)
            tar.addfile(info, io.BytesIO(donnees))

        ajouter("dump.sql", DUMP)
        ajouter("manifest.json", json.dumps(manifeste))
        for dossier in ("filestore", "filestore/ab"):
            info = tarfile.TarInfo(dossier)
            info.type = tarfile.DIRTYPE
            tar.addfile(info)
        for nom, contenu in membres:
            ajouter(nom, contenu)
        for nom, cible in liens:
            info = tarfile.TarInfo(nom)
            info.type = tarfile.SYMTYPE
            info.linkname = cible
            tar.addfile(info)
    if sidecar:
        somme = hashlib.sha256(open(chemin, "rb").read()).hexdigest()
        ecrire(chemin + ".sha256", f"{somme}  {os.path.basename(chemin)}\n")
    return chemin


class TestAncienTarXz(Base):
    """D12 : un .tar.xz de l'outil antérieur se restaure par --file, avec
    les mêmes contrôles que le zip."""

    def setUp(self):
        super().setUp()
        self.ancien = os.path.join(
            self.bac, "anciennes", "demo_db_2031-03-09_030000.tar.xz"
        )
        os.makedirs(os.path.dirname(self.ancien))

    def test_essai(self):
        fabriquer_tar_xz(
            self.ancien, [("filestore/ab/f0", "a"), ("filestore/ab/f1", "b")]
        )
        self.systeme.controle["stored_files"] = 2
        code = self.lancer("--test-restore", "--file", self.ancien)
        self.assertEqual(code, ob.CODE_OK, self.sortie + self.erreurs)
        self.assertEqual(self.systeme.vu["charger"]["contenu"], DUMP)
        self.assertIn(ob.t("Checksum verified."), self.sortie)
        self.assertNotIn("[ATTN]", self.sortie)

    def test_restauration_dans_une_nouvelle_base(self):
        fabriquer_tar_xz(self.ancien, [("./filestore/ab/f0", "a")])
        code = self.lancer(
            "--restore", "--file", self.ancien, "--into", "copie_db"
        )
        self.assertEqual(code, ob.CODE_OK, self.sortie + self.erreurs)
        fs = os.path.join(self.data, "filestore", "copie_db")
        self.assertEqual(open(os.path.join(fs, "ab", "f0")).read(), "a")
        self.assertIn("copie_db", self.systeme.bases)

    def test_base_existante_refusee(self):
        fabriquer_tar_xz(self.ancien, [("filestore/ab/f0", "a")])
        code = self.lancer(
            "--restore", "--file", self.ancien, "--into", "demo_db"
        )
        self.assertEqual(code, ob.CODE_REFUS)
        self.assertNotIn("createdb", self.outils())

    def test_chemins_et_liens_refuses(self):
        cas = (
            ([("../../etc/x", "x")], ()),
            ([("/abs", "x")], ()),
            ([("filestore/ab/f0", "a")], [("filestore/ab/l", "/etc/passwd")]),
            ([("filestore/ab/f0", "a"), ("filestore/ab/f0", "b")], ()),
        )
        for membres, liens in cas:
            with self.subTest(membres=membres, liens=liens):
                if os.path.exists(self.ancien):
                    os.remove(self.ancien)
                fabriquer_tar_xz(self.ancien, membres, liens)
                code = self.lancer(
                    "--restore", "--file", self.ancien, "--into", "copie_db"
                )
                self.assertEqual(code, ob.CODE_REFUS, self.sortie)
                self.assertNotIn("createdb", self.outils())
        self.assertEqual(
            os.listdir(os.path.join(self.data, "filestore")), ["demo_db"]
        )

    def test_empreinte_fausse(self):
        fabriquer_tar_xz(self.ancien, [("filestore/ab/f0", "a")])
        ecrire(self.ancien + ".sha256", "0" * 64 + "  x\n")
        code = self.lancer("--test-restore", "--file", self.ancien)
        self.assertEqual(code, ob.CODE_ECHEC)
        self.assertNotIn("createdb", self.outils())

    def test_tronque(self):
        fabriquer_tar_xz(
            self.ancien, [("filestore/ab/f0", "a" * 5000)], sidecar=False
        )
        with open(self.ancien, "r+b") as f:
            f.truncate(os.path.getsize(self.ancien) // 2)
        code = self.lancer("--test-restore", "--file", self.ancien)
        self.assertEqual(code, ob.CODE_ECHEC, self.sortie)
        self.assertNotIn("createdb", self.outils())


class TestRestauration(Base):
    def restaurer(self, fichier, nouvelle="copie_db", *options):
        return self.lancer(
            "--restore", "--file", fichier, "--into", nouvelle, *options
        )

    def test_x1_base_ou_filestore_existants(self):
        chemin = self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.systeme.bases.add("copie_db")
        self.assertEqual(self.restaurer(chemin), ob.CODE_REFUS)
        self.assertNotIn("createdb", self.outils())
        self.systeme.bases.discard("copie_db")
        os.makedirs(os.path.join(self.data, "filestore", "copie_db"))
        self.assertEqual(self.restaurer(chemin), ob.CODE_REFUS)
        self.assertNotIn("createdb", self.outils())

    def test_x2_chemins_dangereux(self):
        for membre in ("../../etc/x", "/abs", "a\\..\\b"):
            with self.subTest(membre=membre):
                chemin = self.fabriquer(
                    datetime.datetime(2031, 3, 9, 3),
                    membres=[("filestore/ab/f0", "a"), (membre, "x")],
                )
                self.assertEqual(self.restaurer(chemin), ob.CODE_REFUS)
                self.assertNotIn("createdb", self.outils())

    def test_x3_echec_apres_createdb(self):
        autre = os.path.join(self.data, "filestore", "autre_db")
        ecrire(os.path.join(autre, "f"), "x")
        chemin = self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.systeme.chargement = (3, ["psql: error: boom"], False)
        self.assertEqual(self.restaurer(chemin), ob.CODE_ECHEC)
        self.assertIn("dropdb", self.outils())
        self.assertNotIn("copie_db", self.systeme.bases)
        fs = os.path.join(self.data, "filestore")
        self.assertEqual(sorted(os.listdir(fs)), ["autre_db", "demo_db"])
        self.assertTrue(os.path.exists(os.path.join(autre, "f")))

    def test_x3_echec_pendant_le_filestore(self):
        chemin = self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        with mock.patch.object(
            ob, "extraire_filestore", side_effect=OSError(28, "disque plein")
        ):
            self.assertEqual(self.restaurer(chemin), ob.CODE_ECHEC)
        self.assertNotIn("copie_db", self.systeme.bases)
        fs = os.path.join(self.data, "filestore")
        self.assertEqual(os.listdir(fs), ["demo_db"])

    def test_x4_reussite(self):
        chemin = self.fabriquer(
            datetime.datetime(2031, 3, 9, 3),
            membres=[("filestore/ab/f0", "a"), ("autre.txt", "ignoré")],
        )
        self.assertEqual(
            self.restaurer(chemin), ob.CODE_OK, self.sortie + self.erreurs
        )
        fs = os.path.join(self.data, "filestore", "copie_db")
        self.assertEqual(open(os.path.join(fs, "ab", "f0")).read(), "a")
        self.assertFalse(os.path.exists(os.path.join(fs, "..", "autre.txt")))
        # Sous root, le filestore se place SOUS LE COMPTE de l'unité : root
        # n'y crée ni ne donne rien lui-même.
        self.assertEqual(
            self.systeme.sous_compte, [("demo", "placer_filestore")]
        )
        racine_fs = os.path.join(self.data, "filestore")
        self.assertEqual(
            [c for c, _u in self.systeme.chowns if c.startswith(racine_fs)],
            [],
        )
        self.assertIn("neutralize", self.sortie)
        self.assertIn("database.uuid", self.sortie)
        self.assertIn("copie_db", self.systeme.bases)

    def test_x4_rappel_manuel_avant_16(self):
        chemin = self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        with zipfile.ZipFile(chemin) as z:
            contenu = {n: z.read(n) for n in z.namelist()}
        manifeste = json.loads(contenu["manifest.json"])
        manifeste["major_version"] = "15.0"
        contenu["manifest.json"] = json.dumps(manifeste)
        with zipfile.ZipFile(chemin, "w") as z:
            for nom, valeur in contenu.items():
                z.writestr(nom, valeur)
        os.remove(chemin + ".sha256")
        self.assertEqual(self.restaurer(chemin), ob.CODE_OK, self.sortie)
        self.assertNotIn("odoo-bin neutralize", self.sortie)

    def test_x5_espace_pour_le_filestore(self):
        chemin = self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.systeme.libre = 1
        self.assertEqual(self.restaurer(chemin), ob.CODE_REFUS)
        self.assertNotIn("createdb", self.outils())

    def test_simulation(self):
        chemin = self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.assertEqual(
            self.restaurer(chemin, "copie_db", "--dry-run"), ob.CODE_OK
        )
        self.assertNotIn("createdb", self.outils())
        self.assertIn("createdb -w -E UTF8", self.sortie)

    def test_options_exigees(self):
        for argv in (
            ["--restore"],
            ["--restore", "--file", "x.zip"],
            ["--into", "x"],
            ["--file", "x.zip"],
        ):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        ob.analyser(argv)


class TestEssaiControles(Base):
    """Les contrôles de la base restaurée : chacun fait échouer l'essai, et
    la base temporaire est supprimée quand même."""

    TEMPORAIRE = "demo_db_restoretest_20310310030000"

    def echoue_et_nettoie(self, attendu):
        self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_ECHEC)
        self.assertIn(attendu, self.sortie)
        dropdb = [a[-1] for n, a in self.systeme.appels if n == "dropdb"]
        self.assertEqual(dropdb, [self.TEMPORAIRE])
        self.assertEqual(self.systeme.bases, {"postgres", "demo_db"})

    def test_aucune_table(self):
        self.systeme.controle["tables"] = 0
        self.echoue_et_nettoie(ob.t("The restored database has no table."))

    def test_base_non_installee(self):
        self.systeme.controle["base"] = "to upgrade"
        self.echoue_et_nettoie(
            ob.t("The base module is not installed in the restored database.")
        )

    def test_controle_illisible(self):
        self.systeme.controle = None
        self.echoue_et_nettoie("relation missing")

    def test_dropdb_en_echec_fait_echouer_l_essai(self):
        self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.systeme.dropdb_code = 1
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_ECHEC)
        self.assertIn(
            ob.t("Test restore passed: the backup is restorable."), self.sortie
        )
        self.assertIn(
            "runuser -u demo -- dropdb -w -- " + self.TEMPORAIRE, self.sortie
        )
        self.assertIn(self.TEMPORAIRE, self.systeme.bases)


class TestEspacePostgres(Base):
    """La place de la base restaurée dans le dossier de données de
    PostgreSQL : vérifiée avant createdb, ou refus sans --force-space."""

    def setUp(self):
        super().setUp()
        self.fabriquer(datetime.datetime(2031, 3, 9, 3))

    def test_espace_insuffisant_avant_createdb(self):
        self.systeme.libre_par_lieu[self.systeme.dossier_pg] = 10
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_ECHEC)
        self.assertIn(self.systeme.dossier_pg, self.sortie)
        self.assertNotIn("createdb", self.outils())

    def test_estimation_par_la_base_source(self):
        """La base source est sur ce serveur : sa taille l'emporte sur le
        double du dump quand elle est plus grande."""
        self.systeme.faits["size"] = 10**6
        self.systeme.libre_par_lieu[self.systeme.dossier_pg] = 10**6
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_ECHEC)
        self.assertNotIn("createdb", self.outils())
        self.systeme.libre_par_lieu[self.systeme.dossier_pg] = int(
            10**6 * ob.MARGE
        )
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_OK)

    def test_estimation_par_le_dump(self):
        attendu = int(len(DUMP) * ob.FACTEUR_DUMP * ob.MARGE)
        self.systeme.faits["size"] = 0
        self.systeme.libre_par_lieu[self.systeme.dossier_pg] = attendu - 1
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_ECHEC)
        self.systeme.libre_par_lieu[self.systeme.dossier_pg] = attendu
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_OK)

    def test_repli_sur_le_compte_du_serveur(self):
        self.systeme.reponse_dossier_compte = (1, "")
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_OK)
        requetes = [
            v
            for v in self.systeme.vu["psql"]
            if v["argv"][:3] == ["runuser", "-u", "postgres"]
        ]
        self.assertEqual(len(requetes), 1)
        self.assertEqual(requetes[0]["argv"][-1], postgres.REQUETE_DOSSIER)
        for cle in ("PGPASSWORD", "PGUSER", "PGHOST"):
            self.assertNotIn(cle, requetes[0]["env"])

    def test_inconnu_refuse_sauf_force_space(self):
        self.systeme.reponse_dossier_compte = (1, "")
        self.systeme.reponse_dossier_postgres = (2, "")
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_ECHEC)
        self.assertIn("--force-space", self.sortie)
        self.assertNotIn("createdb", self.outils())
        self.assertEqual(
            self.lancer("--test-restore", "--force-space"), ob.CODE_OK
        )
        self.assertIn("[ATTN]", self.sortie)

    def test_hote_distant_inconnu(self):
        with open(self.conf, "a") as f:
            f.write("db_host = db.example.org\n")
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_ECHEC)
        self.assertNotIn(
            postgres.REQUETE_DOSSIER,
            [v["argv"][-1] for v in self.systeme.vu["psql"]],
        )
        self.assertNotIn("createdb", self.outils())

    def test_restauration_refusee_et_simulation_seulement_signalee(self):
        chemin = os.path.join(self.dossier, self.zips()[0])
        self.systeme.reponse_dossier_compte = (1, "")
        self.systeme.reponse_dossier_postgres = (2, "")
        argv = ("--restore", "--file", chemin, "--into", "copie_db")
        self.assertEqual(self.lancer(*argv), ob.CODE_REFUS)
        self.assertNotIn("createdb", self.outils())
        self.assertEqual(self.lancer(*argv, "--dry-run"), ob.CODE_OK)
        self.assertIn("[ATTN]", self.sortie)


class TestEnvironnementDesOutils(Base):
    """Ce que reçoit chaque outil : jamais PGOPTIONS (lecture seule) hors
    des requêtes de lecture, le mot de passe par l'environnement seul."""

    def test_chargement_creation_et_suppression(self):
        self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_OK)
        vus = [self.systeme.vu["charger"]]
        vus += self.systeme.vu["createdb"] + self.systeme.vu["dropdb"]
        for vu in vus:
            with self.subTest(argv=vu["argv"][4]):
                self.assertNotIn("PGOPTIONS", vu["env"])
                self.assertEqual(vu["env"]["PGPASSWORD"], "secret-demo")
                self.assertNotIn("secret-demo", " ".join(vu["argv"]))

    def test_rsync_avec_le_home_du_compte(self):
        self.assertEqual(self.lancer("--copy-to", COPIE), ob.CODE_OK)
        env = self.systeme.vu["rsync"][0]["env"]
        self.assertEqual(env["HOME"], self.systeme.home("demo"))


class TestEstimationEspace(Base):
    """L'espace exigé avant pg_dump : (taille de la base + filestore) ×
    MARGE. Chaque terme compte."""

    def besoin(self):
        octets, _nombre = self.systeme.taille_dossier(self.filestore)
        self.assertGreater(octets, 0)
        return FAITS["size"], octets

    def test_le_filestore_compte(self):
        """Assez pour la base seule, marge comprise ; pas avec le
        filestore."""
        taille, octets = self.besoin()
        self.systeme.libre = int(taille * ob.MARGE) + 1
        self.assertLess(self.systeme.libre, (taille + octets) * ob.MARGE)
        self.assertEqual(self.lancer(), ob.CODE_REFUS)
        self.assertNotIn("pg_dump", self.outils())

    def test_la_marge_compte(self):
        taille, octets = self.besoin()
        self.systeme.libre = taille + octets
        self.assertEqual(self.lancer(), ob.CODE_REFUS)
        self.assertNotIn("pg_dump", self.outils())

    def test_juste_assez(self):
        taille, octets = self.besoin()
        self.systeme.libre = int((taille + octets) * ob.MARGE)
        self.assertEqual(self.lancer(), ob.CODE_OK, self.sortie)


class TestEchecsDeLaSauvegarde(Base):
    def test_fichier_final_deja_present(self):
        os.makedirs(self.dossier)
        nom = retention.nom_sauvegarde(
            "demo_db", datetime.datetime.fromtimestamp(HORLOGE)
        )
        ancien = ecrire(os.path.join(self.dossier, nom), "ancien")
        self.assertEqual(self.lancer(), ob.CODE_ECHEC)
        with open(ancien) as f:
            self.assertEqual(f.read(), "ancien")
        self.assertNotIn("pg_dump", self.outils())

    def test_empreinte_impossible_a_ecrire(self):
        with mock.patch.object(
            ob, "_ecrire_sidecar", side_effect=OSError(28, "disque plein")
        ):
            self.assertEqual(self.lancer(), ob.CODE_ECHEC)
        self.assertEqual(len(self.zips()), 1)

    def test_etat_impossible_a_ecrire(self):
        with mock.patch.object(
            ob, "ecrire_etat", side_effect=OSError(28, "disque plein")
        ):
            self.assertEqual(self.lancer(), ob.CODE_ECHEC)
        self.assertEqual(len(self.zips()), 1)

    def test_echec_sans_copie_ni_retention(self):
        ancien = self.fabriquer(datetime.datetime(2030, 1, 1, 3))
        self.systeme.dump_issue = (1, "pg_dump: error", False)
        code = self.lancer(
            "--copy-to",
            COPIE,
            "--keep-daily",
            "0",
            "--keep-weekly",
            "0",
            "--keep-monthly",
            "0",
            "--keep-recent-days",
            "0",
        )
        self.assertEqual(code, ob.CODE_ECHEC)
        self.assertNotIn("rsync", self.outils())
        self.assertTrue(os.path.exists(ancien))


class TestDossiersCommuns(Base):
    """Les dossiers --dest et --state-dir absents : créés par root, ils
    restent à root (0755) ; le dossier de la base est au compte."""

    def test_crees_sous_root(self):
        self.dest = os.path.join(self.bac, "neuf", "a", "sauvegardes")
        self.etat = os.path.join(self.bac, "neuf", "b", "etat")
        self.dossier = os.path.join(self.dest, "demo_db")
        self.assertEqual(self.lancer(), ob.CODE_OK, self.sortie + self.erreurs)
        donnes = {c for c, u in self.systeme.chowns if u == "demo"}
        for commun in (self.dest, self.etat, os.path.dirname(self.dest)):
            with self.subTest(dossier=commun):
                self.assertEqual(os.stat(commun).st_mode & 0o777, 0o755)
                self.assertNotIn(commun, donnes)
        self.assertIn(self.dossier, donnes)
        self.assertEqual(os.stat(self.dossier).st_mode & 0o777, 0o700)
        etat_base = os.path.join(self.etat, "demo_db")
        self.assertIn(etat_base, donnes)
        self.assertEqual(os.stat(etat_base).st_mode & 0o777, 0o755)

    def _parent_en_lecture_seule(self):
        if os.geteuid() == 0:
            self.skipTest("root écrit partout")
        parent = os.path.join(self.bac, "lecture_seule")
        os.mkdir(parent)
        os.chmod(parent, 0o555)
        self.addCleanup(os.chmod, parent, 0o755)
        self.dest = os.path.join(parent, "sauvegardes")
        self.dossier = os.path.join(self.dest, "demo_db")
        self.systeme.euid_valeur = 1000
        self.systeme.courant = "demo"

    def test_hors_root_refuse_mais_simulation_prevoit_sudo(self):
        self._parent_en_lecture_seule()
        self.assertEqual(self.lancer(), ob.CODE_REFUS)
        self.assertIn(self.dest, self.erreurs)
        self.assertIn("sudo", self.erreurs)
        # Refusé à la détection : aucune création n'est tentée.
        self.assertNotIn("mkdir", self.outils())
        self.assertEqual(self.lancer("--dry-run"), ob.CODE_OK, self.erreurs)
        self.assertIn("sudo mkdir -m 0755 -- " + self.dest, self.sortie)
        self.assertIn(
            "sudo mkdir -m 0700 -- "
            + self.dossier
            + " && sudo chown demo: -- "
            + self.dossier,
            self.sortie,
        )
        self.assertFalse(os.path.exists(self.dest))


class TestDossierDeBaseEnLien(Base):
    """`<dest>/<base>` ou `<state-dir>/<base>` en lien symbolique : refus
    (code 2) avant toute commande, aucun fichier écrit dans la cible du
    lien ; `--status` ne lit pas l'état derrière le lien. Le dossier
    commun (`--dest`) en lien reste admis : il est choisi par
    l'opérateur."""

    def lien(self, chemin):
        cible = os.path.join(self.bac, "ailleurs", os.path.basename(chemin))
        os.makedirs(cible)
        os.symlink(cible, chemin)
        return cible

    @staticmethod
    def message(chemin):
        return ob.t("{path} is a symbolic link: refused.").format(path=chemin)

    def verifier_refus(self, lien, cible, *options):
        self.assertEqual(self.lancer(*options), ob.CODE_REFUS, self.sortie)
        self.assertIn(self.message(lien), self.erreurs)
        # Seule la lecture de l'unité a eu lieu : ni psql, ni pg_dump.
        self.assertEqual(
            [nom for nom in self.outils() if nom != "systemctl"], []
        )
        self.assertEqual(os.listdir(cible), [])

    def test_dossier_des_sauvegardes(self):
        cible = self.lien(self.dossier)
        self.verifier_refus(self.dossier, cible)

    def test_dossier_d_etat(self):
        etat_base = os.path.join(self.etat, "demo_db")
        cible = self.lien(etat_base)
        self.verifier_refus(etat_base, cible)

    def test_simulation_refuse_aussi(self):
        cible = self.lien(self.dossier)
        self.verifier_refus(self.dossier, cible, "--dry-run")

    def test_essai_de_restauration(self):
        cible = self.lien(self.dossier)
        self.verifier_refus(self.dossier, cible, "--test-restore")

    def test_status_ne_lit_pas_l_etat_derriere_le_lien(self):
        etat_base = os.path.join(self.etat, "demo_db")
        cible = self.lien(etat_base)
        ecrire(
            os.path.join(cible, "state.json"),
            json.dumps({"last_success": {"time": HORLOGE}}),
        )
        sortie, erreurs = io.StringIO(), io.StringIO()
        rapport = report.Rapport(flux=sortie, erreurs=erreurs, couleur=False)
        with mock.patch.object(
            ob, "lire_etat", side_effect=AssertionError("lu")
        ):
            for options in (["--db", "demo_db"], []):
                with self.subTest(options=options):
                    code = ob.main(
                        ["--status", "--state-dir", self.etat] + options,
                        self.systeme,
                        rapport,
                    )
                    self.assertEqual(code, ob.CODE_REFUS)
        self.assertIn(self.message(etat_base), erreurs.getvalue())

    def test_dest_commun_en_lien_admis(self):
        vrai = os.path.join(self.bac, "vrai_dest")
        os.makedirs(vrai)
        self.dest = os.path.join(self.bac, "dest_lien")
        os.symlink(vrai, self.dest)
        self.dossier = os.path.join(self.dest, "demo_db")
        self.assertEqual(self.lancer(), ob.CODE_OK, self.sortie + self.erreurs)
        self.assertEqual(len(self.zips()), 1)


class TestVerrouIndisponible(Base):
    """Le dossier du verrou partagé absent : refus propre (code 2), sans
    trace d'exception."""

    def setUp(self):
        super().setUp()
        self.systeme.dossier_verrou = os.path.join(self.bac, "absent")

    def test_sauvegarde(self):
        self.assertEqual(self.lancer(), ob.CODE_REFUS)
        self.assertIn("absent", self.erreurs)
        self.assertNotIn("pg_dump", self.outils())

    def test_restauration(self):
        chemin = self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        self.assertEqual(
            self.lancer("--restore", "--file", chemin, "--into", "copie_db"),
            ob.CODE_REFUS,
        )
        self.assertNotIn("createdb", self.outils())


class TestDescripteurs(Base):
    """Root écrit et lit dans des dossiers que le compte de l'unité
    possède : mode, propriétaire et lecture visent l'inode ouvert, jamais
    un lien que le compte aurait posé à la place d'un nom."""

    def piege_mkstemp(self, victime):
        """Un mkstemp qui, une fois le fichier créé, met à sa place un
        lien vers `victime` — ce que le compte ferait entre la fermeture et
        un chmod par chemin."""
        vrai = tempfile.mkstemp

        def mkstemp(*args, **kwargs):
            fd, chemin = vrai(*args, **kwargs)
            os.remove(chemin)
            os.symlink(victime, chemin)
            return fd, chemin

        return mock.patch.object(ob.tempfile, "mkstemp", mkstemp)

    def cible(self):
        os.makedirs(os.path.join(self.etat, "demo_db"), exist_ok=True)
        return ob.Cible(
            base="demo_db",
            utilisateur="demo",
            root=True,
            etat_dir=self.etat,
            dossier_etat=os.path.join(self.etat, "demo_db"),
        )

    def test_etat_le_mode_ne_suit_pas_un_lien(self):
        victime = ecrire(os.path.join(self.bac, "victime"), "intact")
        os.chmod(victime, 0o600)
        with self.piege_mkstemp(victime):
            ob.ecrire_etat(self.cible(), self.systeme, {"x": 1})
        self.assertEqual(os.stat(victime).st_mode & 0o777, 0o600)
        with open(victime) as f:
            self.assertEqual(f.read(), "intact")

    def test_empreinte_le_mode_ne_suit_pas_un_lien(self):
        victime = ecrire(os.path.join(self.bac, "victime"), "intact")
        os.chmod(victime, 0o644)
        os.makedirs(self.dossier)
        final = os.path.join(self.dossier, "demo_db_x.zip")
        with self.piege_mkstemp(victime):
            ob._ecrire_sidecar(final, "0" * 64, self.cible(), self.systeme)
        self.assertEqual(os.stat(victime).st_mode & 0o777, 0o644)

    def test_etat_existant_qui_est_un_lien_n_est_pas_lu(self):
        secret = ecrire(
            os.path.join(self.bac, "secret.json"), '{"secret": "x"}'
        )
        cible = self.cible()
        os.symlink(secret, ob.chemin_etat(self.etat, "demo_db"))
        ob.ecrire_etat(cible, self.systeme, {"last_success": {"time": 5}})
        self.assertNotIn("secret", self.etat_base())

    def test_etat_d_un_autre_proprietaire_ou_special(self):
        chemin = ecrire(os.path.join(self.bac, "e.json"), '{"a": 1}')
        self.assertEqual(ob.lire_etat(chemin), {"a": 1})
        self.assertEqual(ob.lire_etat(chemin, {os.getuid() + 1}), {})
        tube = os.path.join(self.bac, "tube")
        os.mkfifo(tube)
        self.assertEqual(ob.lire_etat(tube), {})

    def test_empreinte_qui_est_un_lien_refuse_l_archive(self):
        chemin = self.fabriquer(datetime.datetime(2031, 3, 9, 3))
        vraie = ecrire(os.path.join(self.bac, "vraie"), "")
        with open(chemin + ".sha256") as f:
            ecrire(vraie, f.read())
        os.remove(chemin + ".sha256")
        os.symlink(vraie, chemin + ".sha256")
        self.assertEqual(ob.lire_sidecar(chemin), "")
        self.assertEqual(self.lancer("--test-restore"), ob.CODE_ECHEC)
        self.assertNotIn("createdb", self.outils())

    def test_filestore_sous_dossier_remplace_pendant_la_lecture(self):
        """Un sous-dossier remplacé par un lien APRÈS la lecture de son
        parent n'est pas suivi : rien du dossier visé n'entre."""
        secret = os.path.join(self.bac, "secret")
        ecrire(os.path.join(secret, "shadow"), "hash")
        ecrire(os.path.join(self.filestore, "zz", "f"), "x")
        vrai = os.fwalk

        def fwalk(*args, **kwargs):
            for numero, element in enumerate(vrai(*args, **kwargs)):
                yield element
                if numero == 0:
                    zz = os.path.join(self.filestore, "zz")
                    os.rename(zz, zz + "_avant")
                    os.symlink(secret, zz)

        with mock.patch.object(ob.os, "fwalk", fwalk):
            self.assertEqual(self.lancer(), ob.CODE_OK, self.sortie)
        with zipfile.ZipFile(os.path.join(self.dossier, self.zips()[0])) as z:
            noms = z.namelist()
        self.assertNotIn("filestore/zz/shadow", noms)
        self.assertIn("filestore/ab/f0", noms)

    def test_filestore_d_un_autre_compte_refuse(self):
        self.systeme.uid = lambda utilisateur: os.getuid() + 1
        self.assertEqual(self.lancer(), ob.CODE_ECHEC)
        self.assertEqual(self.zips(), [])
        self.assertIn(self.filestore, self.sortie)


def retention_affichee(daily, weekly, monthly, recent):
    """La ligne de rétention de la simulation, dans la langue courante."""
    return ob.t(
        "retention: {daily} daily, {weekly} weekly, {monthly} monthly,"
        " everything from the last {recent} day(s)"
    ).format(daily=daily, weekly=weekly, monthly=monthly, recent=recent)


class FauxSystemeDevine(FauxSysteme):
    """Le même théâtre, où `systemctl list-units` connaît l'unité de
    démonstration, seule active : elle se devine sans `--service`."""

    def lanceur(self, argv, timeout=60):
        if argv[:2] == ["systemctl", "list-units"]:
            self.appels.append(("systemctl", list(argv)))
            return 0, "erplibre_demo.service loaded active running Odoo\n"
        return super().lanceur(argv, timeout)


def champ_base(base, origine):
    """Le motif de la seule ligne du champ Database qui porte `base
    (origine)`, ancré au début et à la fin de la ligne."""
    return re.compile(
        r"^  "
        + re.escape(ob.t("Database"))
        + r" +"
        + re.escape(f"{base} ({origine})")
        + r"$",
        re.M,
    )


class TestProfil(Base):
    """Le groupe `backup` du profil de l'instance : valeurs appliquées et
    affichées, la ligne de commande qui gagne, les options exclues, les
    règles du profil, `--status`, `--no-profile` et `--profile-unset`."""

    SERVICE = "erplibre_demo.service"

    def profil(self, groupes, dossier=None):
        """Écrit un profil (version 1) dans `dossier`, par défaut celui
        des profils du module, et rend son chemin ; il est retiré à la fin
        du test."""
        doc = {"version": 1, "service": self.SERVICE}
        doc.update(groupes)
        chemin = os.path.join(
            dossier or profil.racine_profils(), self.SERVICE + ".json"
        )
        ecrire(chemin, json.dumps(doc))
        os.chmod(chemin, 0o644)
        self.addCleanup(os.remove, chemin)
        return chemin

    def analyser(self, argv):
        """`ob.analyser(argv)` ; un refus rend son code de sortie."""
        erreurs = io.StringIO()
        with contextlib.redirect_stderr(erreurs):
            try:
                return ob.analyser(argv)
            except SystemExit as err:
                self.erreurs = erreurs.getvalue()
                return err.code

    def test_valeurs_appliquees_et_affichees_avant_la_simulation(self):
        self.profil(
            {
                "instance": {"db": "demo_db"},
                "backup": {
                    "keep_daily": 10,
                    "keep_monthly": 3,
                    "copy_to": COPIE,
                },
            }
        )
        self.assertEqual(self.lancer("--dry-run"), ob.CODE_OK, self.sortie)
        self.assertIn(
            retention_affichee(10, ob.GARDE_HEBDO, 3, ob.GARDE_RECENTS),
            self.sortie,
        )
        self.assertIn("rsync -a --partial", self.sortie)
        self.assertIn(COPIE, self.sortie)
        chemin = os.path.join(profil.racine_profils(), self.SERVICE + ".json")
        self.assertIn(chemin, self.sortie)
        for ligne in ("--keep-daily 10", "--keep-monthly 3", "--db demo_db"):
            self.assertIn(ligne, self.sortie)
        # Les valeurs du profil précèdent les commandes simulées.
        self.assertLess(
            self.sortie.index("--keep-daily 10"),
            self.sortie.index("(simulation)"),
        )
        self.assertNotIn("[ATTN]", self.sortie)
        # Le champ Database lui-même, ancré : la ligne de détail
        # `--db demo_db (profile)` ne le satisfait pas.
        self.assertRegex(self.sortie, champ_base("demo_db", ob.t("profile")))
        self.assertEqual(
            self.lancer("--dry-run", "--db", "demo_db"),
            ob.CODE_OK,
            self.sortie,
        )
        self.assertRegex(self.sortie, champ_base("demo_db", "--db"))

    def test_origine_des_valeurs(self):
        chemin = self.profil(
            {"backup": {"keep_daily": 10, "dest": "/srv/sauvegardes"}}
        )
        args = self.analyser(
            ["--service", "erplibre_demo", "--keep-weekly", "2"]
        )
        self.assertEqual(args.profil.chemin, chemin)
        self.assertEqual(args.keep_daily, 10)
        self.assertEqual(args.dest, "/srv/sauvegardes")
        self.assertEqual(args.keep_weekly, 2)
        self.assertEqual(args.profil.origine("keep_daily"), "profil")
        self.assertEqual(args.profil.origine("keep_weekly"), "cli")
        self.assertEqual(args.profil.origine("keep_monthly"), "defaut")
        self.assertEqual(args.keep_monthly, ob.GARDE_MENSUEL)

    def test_la_ligne_de_commande_gagne(self):
        self.profil({"backup": {"keep_daily": 10, "copy_to": COPIE}})
        self.assertEqual(
            self.lancer("--dry-run", "--keep-daily", "3"), ob.CODE_OK
        )
        self.assertIn(
            retention_affichee(
                3, ob.GARDE_HEBDO, ob.GARDE_MENSUEL, ob.GARDE_RECENTS
            ),
            self.sortie,
        )
        self.assertNotIn("--keep-daily 10", self.sortie)
        self.assertIn("[ATTN]", self.sortie)
        args = self.analyser(
            ["--service", "erplibre_demo", "--keep-daily", "3"]
        )
        self.assertEqual(args.keep_daily, 3)
        self.assertEqual(
            [e.dest for e in args.profil.ecartees], ["keep_daily"]
        )
        self.assertEqual(args.copy_to, COPIE)

    def test_zero_refuse_dans_le_profil_accepte_sur_la_cli(self):
        self.profil({"backup": {"keep_daily": 0}})
        self.assertEqual(self.analyser(["--service", "erplibre_demo"]), 2)
        self.assertIn("backup.keep_daily", self.erreurs)
        args = self.analyser(
            ["--service", "erplibre_demo", "--keep-daily", "0"]
        )
        self.assertEqual(args.keep_daily, 0)

    def test_regles_du_profil(self):
        for groupe, cle in (
            ({"max_age": 200}, "backup.max_age"),
            ({"dest": "sauvegardes"}, "backup.dest"),
            ({"state_dir": "etat"}, "backup.state_dir"),
            ({"copy_to": "pas une copie"}, "backup.copy_to"),
            ({"keep_daily": "dix"}, "backup.keep_daily"),
        ):
            with self.subTest(cle=cle):
                chemin = self.profil({"backup": groupe})
                self.assertEqual(
                    self.analyser(["--service", "erplibre_demo"]), 2
                )
                self.assertIn(cle, self.erreurs)
                os.remove(chemin)
                self._cleanups.pop()

    def test_options_exclues_ignorees(self):
        self.profil(
            {
                "backup": {
                    "status": True,
                    "test_restore": True,
                    "force_space": True,
                    "file": "/srv/x.zip",
                    "into": "autre_db",
                    "dry_run": True,
                    "user": "root",
                    "service": "odoo-exemple.service",
                    "couleur": "rouge",
                },
                "update_module": {"timeout": 5},
            }
        )
        args = self.analyser(["--service", "erplibre_demo"])
        self.assertFalse(args.status or args.test_restore or args.restore)
        self.assertFalse(args.force_space or args.dry_run)
        self.assertIsNone(args.file)
        self.assertIsNone(args.into)
        self.assertIsNone(args.user)
        self.assertEqual(args.service, self.SERVICE)
        self.assertEqual(args.profil.valeurs, {})
        self.assertEqual(
            sorted(e.dest for e in args.profil.ecartees),
            sorted(
                [
                    "status",
                    "test_restore",
                    "force_space",
                    "file",
                    "into",
                    "dry_run",
                    "user",
                    "service",
                ]
            ),
        )
        # Une clé inconnue du groupe est signalée ; le groupe d'un autre
        # outil est ignoré sans message.
        self.assertEqual(args.profil.inconnues, ["backup.couleur"])
        # Le mode par défaut reste la sauvegarde, en simulation ici.
        self.assertEqual(self.lancer("--dry-run"), ob.CODE_OK)
        self.assertEqual(self.sortie.count("[ATTN]"), 9, self.sortie)
        self.assertEqual(self.outils().count("pg_dump"), 0)

    def test_valider_apres_le_profil(self):
        """`valider` voit les valeurs posées par le profil : il est appelé
        après la pose, jamais avant."""
        self.profil({"backup": {"keep_daily": 10}})
        vues = []
        valider = ob.valider

        def espion(parser, args):
            vues.append(args.keep_daily)
            return valider(parser, args)

        with mock.patch.object(ob, "valider", espion):
            args = self.analyser(["--service", "erplibre_demo"])
        self.assertEqual(args.keep_daily, 10)
        self.assertEqual(vues, [10])

    def test_file_et_into_jamais_du_profil(self):
        # `file` et `into` ne viennent jamais du profil : --restore les
        # exige toujours sur la ligne de commande.
        self.profil({"backup": {"file": "/srv/x.zip", "into": "autre_db"}})
        self.assertEqual(
            self.analyser(["--service", "erplibre_demo", "--restore"]), 2
        )
        self.assertEqual(
            self.analyser(["--service", "erplibre_demo", "--into", "x"]), 2
        )

    def test_status_liste_toutes_les_bases_malgre_db(self):
        self.profil(
            {"instance": {"db": "demo_db"}, "backup": {"max_age": 100}}
        )
        for base in ("demo_db", "autre_db"):
            ecrire(
                os.path.join(self.etat, base, "state.json"),
                json.dumps({"last_success": {"time": HORLOGE - 50 * 3600}}),
            )
        sortie, erreurs = io.StringIO(), io.StringIO()
        rapport = report.Rapport(flux=sortie, erreurs=erreurs, couleur=False)
        code = ob.main(
            [
                "--status",
                "--service",
                "erplibre_demo",
                "--state-dir",
                self.etat,
            ],
            self.systeme,
            rapport,
        )
        self.sortie = sortie.getvalue()
        # max_age (100 h) vient du profil : 50 h restent dans la borne.
        self.assertEqual(code, ob.CODE_OK, self.sortie)
        self.assertIn("demo_db", self.sortie)
        self.assertIn("autre_db", self.sortie)
        self.assertIn("--max-age 100", self.sortie)
        self.assertIn("[ATTN]", self.sortie)
        self.assertMinuteriesSeulement(self.systeme.appels)

    def test_status_avec_profile_explicite(self):
        chemin = self.profil({"backup": {"state_dir": self.etat}})
        ecrire(
            os.path.join(self.etat, "demo_db", "state.json"),
            json.dumps({"last_success": {"time": HORLOGE - 3600}}),
        )
        args = self.analyser(["--status", "--profile", chemin])
        self.assertEqual(args.state_dir, self.etat)
        # Sous --status, le service du profil n'est pas posé.
        self.assertIsNone(args.service)
        rapport = report.Rapport(
            flux=io.StringIO(), erreurs=io.StringIO(), couleur=False
        )
        code = ob.main(
            ["--status", "--profile", chemin], self.systeme, rapport
        )
        self.assertEqual(code, ob.CODE_OK)
        self.assertMinuteriesSeulement(self.systeme.appels)

    def test_profile_explicite_pose_le_service(self):
        ailleurs = os.path.join(self.bac, "ailleurs")
        os.makedirs(ailleurs)
        chemin = self.profil({}, dossier=ailleurs)
        args = self.analyser(["--profile", chemin, "--dry-run"])
        self.assertEqual(args.service, self.SERVICE)
        self.assertEqual(args.profil.origine("service"), "profil")

    def test_no_profile(self):
        self.profil({"backup": {"keep_daily": 10}})
        self.assertEqual(self.lancer("--dry-run", "--no-profile"), ob.CODE_OK)
        self.assertIn(
            retention_affichee(
                ob.GARDE_QUOTIDIEN,
                ob.GARDE_HEBDO,
                ob.GARDE_MENSUEL,
                ob.GARDE_RECENTS,
            ),
            self.sortie,
        )
        self.assertNotIn("--keep-daily 10", self.sortie)
        args = self.analyser(["--service", "erplibre_demo", "--no-profile"])
        self.assertFalse(args.profil.actif)
        self.assertEqual(args.keep_daily, ob.GARDE_QUOTIDIEN)

    def test_profile_unset(self):
        self.profil({"backup": {"keep_daily": 10, "keep_weekly": 2}})
        args = self.analyser(
            ["--service", "erplibre_demo", "--profile-unset", "keep-daily"]
        )
        self.assertEqual(args.keep_daily, ob.GARDE_QUOTIDIEN)
        self.assertEqual(args.keep_weekly, 2)
        self.assertEqual(
            self.analyser(
                ["--service", "erplibre_demo", "--profile-unset", "file"]
            ),
            2,
        )

    def test_profil_absent_et_requis(self):
        args = self.analyser(["--service", "erplibre_demo"])
        self.assertFalse(args.profil.actif)
        self.assertEqual(args.keep_daily, ob.GARDE_QUOTIDIEN)
        self.assertEqual(
            self.analyser(
                ["--service", "erplibre_demo", "--profile-required"]
            ),
            2,
        )

    def test_analyser_seul_ne_devine_jamais(self):
        self.profil({"backup": {"keep_daily": 10}})
        with mock.patch.object(
            profil.systemd, "deviner_unite", side_effect=AssertionError
        ):
            args = self.analyser(["--dry-run"])
        self.assertFalse(args.profil.actif)

    def test_unite_devinee_une_seule_fois(self):
        self.profil({"backup": {"keep_daily": 10}})
        systeme = FauxSystemeDevine(self.bac, self.verrous)
        os.makedirs(systeme.dossier_pg, exist_ok=True)
        sortie, erreurs = io.StringIO(), io.StringIO()
        rapport = report.Rapport(flux=sortie, erreurs=erreurs, couleur=False)
        code = ob.main(
            ["--dest", self.dest, "--state-dir", self.etat, "--dry-run"],
            systeme,
            rapport,
        )
        self.assertEqual(code, ob.CODE_OK, sortie.getvalue())
        self.assertIn("--keep-daily 10", sortie.getvalue())
        listes = [
            argv
            for nom, argv in systeme.appels
            if nom == "systemctl" and argv[1] == "list-units"
        ]
        self.assertEqual(len(listes), 1)


class TestSousLeCompte(unittest.TestCase):
    """`SystemeBase.sous_le_compte` sous un root simulé : le vrai fork et
    le vrai tube, `devenir` remplacé (changer d'uid exige root)."""

    class Enfant(ob.Systeme):
        def __init__(self):
            super().__init__()
            self.devenu = None
            self.lever = None

        def euid(self):
            return 0

        def devenir(self, utilisateur):
            if self.lever is not None:
                raise self.lever
            self.devenu = utilisateur

    def test_valeur_rendue_par_un_autre_processus_apres_devenir(self):
        systeme = self.Enfant()
        valeur = systeme.sous_le_compte(
            "demo", lambda: [os.getpid(), systeme.devenu]
        )
        self.assertNotEqual(valeur[0], os.getpid())
        self.assertEqual(valeur[1], "demo")
        self.assertIsNone(systeme.devenu)

    def test_erreur_de_la_fonction(self):
        def echoue():
            raise OSError(13, "refus planté")

        with self.assertRaises(OSError) as ctx:
            self.Enfant().sous_le_compte("demo", echoue)
        self.assertIsInstance(ctx.exception, ob.service.EchecSousCompte)
        self.assertIn("refus planté", str(ctx.exception))

    def test_devenir_en_echec_ne_lance_pas_la_fonction(self):
        systeme = self.Enfant()
        systeme.lever = PermissionError(1, "setuid refusé")
        lu, ecrit = os.pipe()
        self.addCleanup(os.close, lu)

        def temoin():
            os.write(ecrit, b"x")

        with self.assertRaises(ob.service.EchecSousCompte):
            systeme.sous_le_compte("demo", temoin)
        os.close(ecrit)
        self.assertEqual(os.read(lu, 1), b"")

    def test_hors_root_appel_direct(self):
        systeme = ob.Systeme()
        if systeme.euid() == 0:
            self.skipTest("lancé sous root")
        self.assertEqual(
            systeme.sous_le_compte("demo", os.getpid), os.getpid()
        )

    def test_devenir_groupes_groupe_puis_uid(self):
        ordre = mock.Mock()
        compte = mock.Mock(pw_uid=4321, pw_gid=8765)
        with (
            mock.patch.object(ob.service.pwd, "getpwnam", return_value=compte),
            mock.patch.object(
                ob.service.os, "getgrouplist", return_value=[8765, 99]
            ),
            mock.patch.object(ob.service.os, "setgroups", ordre.setgroups),
            mock.patch.object(ob.service.os, "setgid", ordre.setgid),
            mock.patch.object(ob.service.os, "setuid", ordre.setuid),
        ):
            ob.Systeme().devenir("demo")
        self.assertEqual(
            ordre.mock_calls,
            [
                mock.call.setgroups([8765, 99]),
                mock.call.setgid(8765),
                mock.call.setuid(4321),
            ],
        )


class TestSystemeReel(unittest.TestCase):
    """Le vrai `flux` et le vrai `alimenter`, sur des python qui écrivent
    et lisent : ni pg_dump ni psql."""

    def test_flux_passe_la_sortie_et_borne_stderr(self):
        blocs = []
        code, erreur, tue = ob.Systeme().flux(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.write('a' * 300000);"
                " sys.stderr.write('e' * 200000); raise SystemExit(3)",
            ],
            os.environ.copy(),
            blocs.append,
            30,
        )
        self.assertEqual((code, tue), (3, False))
        self.assertEqual(len(b"".join(blocs)), 300000)
        self.assertLessEqual(len(erreur), ob.LIMITE_ERREUR)

    def test_flux_hors_delai(self):
        code, _erreur, tue = ob.Systeme().flux(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            os.environ.copy(),
            lambda b: None,
            0.5,
        )
        self.assertTrue(tue)

    def test_alimenter(self):
        code, lignes, tue = ob.Systeme().alimenter(
            [
                sys.executable,
                "-c",
                "import sys; d = sys.stdin.buffer.read();"
                " sys.stderr.write('ERROR: %d\\n' % len(d))",
            ],
            os.environ.copy(),
            iter([b"x" * 100000, b"y" * 100000]),
            30,
        )
        self.assertEqual((code, tue), (0, False))
        self.assertEqual(lignes, ["ERROR: 200000"])


if __name__ == "__main__":
    unittest.main()
