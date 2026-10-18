#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""script/odoo/update_module.py : ordre des étapes, filet, détection.

Le programme arrête et démarre un service : aucun de ces tests ne doit
atteindre un vrai systemctl. `FauxSysteme` remplace chaque effet de bord
de `Systeme` — systemctl, journalctl, port, /proc, horloge, processus
longs — et tient l'état du service comme le ferait systemd : `stop` le
rend inactif, `start` actif, et ActiveState suit. Chaque appel est noté
dans `appels`, ce qui permet de vérifier l'ordre arrêt < sauvegarde <
odoo < démarrage. `start` avance l'horloge : une époque lue après lui se
distingue d'une époque lue avant.

La sauvegarde est celle d'odoo_backup, appelée en fonction : `requete`
répond à la requête des faits de la base, `flux` joue pg_dump en écrivant
un dump inventé, `espace_libre` rend l'espace demandé. Aucun psql ni
pg_dump réel n'est lancé : une commande non prévue rend un code d'erreur.

Seule la classe `TestLancerLong` lance de vrais processus : des python
qui dorment, ignorent TERM ou lancent un petit-enfant, pour éprouver le
délai, l'interruption et l'arrêt du groupe. `TestSignauxReels` pose les
vrais gestionnaires de signaux, sans processus.
"""

import contextlib
import errno
import io
import json
import os
import re
import signal
import sys
import tempfile
import threading
import time
import tokenize
import unittest
import zipfile
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.lib_ops import lock, report, service  # noqa: E402
from script.odoo import update_module as um  # noqa: E402

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

LIGNE_ERREUR = (
    "2026-01-31 12:00:00,123 4242 ERROR demo_db odoo.modules.loading:"
    " Failed to load module"
)
LIGNE_AVERTISSEMENT = (
    "2026-01-31 12:00:00,123 4242 WARNING demo_db odoo.models: attention"
)
TRACE_KEYERROR = (
    LIGNE_ERREUR + "\nTraceback (most recent call last):\n"
    '  File "/srv/odoo/odoo/modules/loading.py", line 1, in load\n'
    "KeyError: 'x'\n"
)
TRACE_VALUEERROR = (
    "2026-01-31 12:00:01,000 4242 ERROR demo_db odoo.modules.registry:"
    " Failed to load registry\nTraceback (most recent call last):\n"
    '  File "/srv/odoo/odoo/modules/registry.py", line 2, in new\n'
    "ValueError: y\n"
)
DUMP = b"-- dump\n-- PostgreSQL database dump complete\n"
FAITS = {
    "base": "18.0.1.3",
    "modules": {"base": "18.0.1.3", "my_module_a": "18.0.1.0"},
    "server_version_num": 160004,
    "size": 1000,
    "stored_attachments": 1,
}
RE_SAUVEGARDE = re.compile(
    r"demo_db_\d{4}-\d{2}-\d{2}_\d{2}h\d{2}m\d{2}s\.zip"
)


class FauxSysteme(um.Systeme):
    """Un systemd et un Odoo de théâtre. Voir l'en-tête du fichier."""

    def __init__(self, wd, dossier_verrou):
        super().__init__(interactif=False, dossier_verrou=dossier_verrou)
        self.wd = wd
        self.appels = []
        self.etat = "active"
        self.unite = "erplibre_demo.service"
        self.proprietes = {
            "LoadState": "loaded",
            "ActiveState": "active",
            "User": "demo",
            "WorkingDirectory": wd,
            "ExecStart": (
                "{ path=/bin/bash ; argv[]=/bin/bash "
                + os.path.join(wd, "run.sh")
                + " -d demo_db ; ignore_errors=no ; pid=0 }"
            ),
            "Environment": "",
        }
        self.liste_unites = ""
        self.workdirs = {}
        self.horloge = 1800000000.0
        self.euid_valeur = 0
        self.port_apres_arret = False
        self.ecoute_apres_demarrage = True
        self.arret_sans_effet = False
        self.arret_code = 0
        self.etat_apres_arret = "inactive"
        # Réponses servies, une par lecture, à `systemctl show -p
        # ActiveState` avant l'état réel : (code, sortie).
        self.reponses_etat = []
        self.demarrage_code = 0
        self.logfile_au_demarrage = ""
        # Dossiers où `inscriptible` répond non ; tous les autres, oui.
        self.non_inscriptibles = set()
        self.verrou_tenu = None
        self.sonde = True
        self.processus_liste = []
        self.journal_texte = ""
        self.epoque_journal = None
        self.horloge_au_demarrage = None
        self.odoo_issue = um.Issue(0, False, False)
        self.odoo_sortie = "fin\n"
        self.odoo_logfile = None
        self.odoo_ajout_logfile = ""
        # pg_dump joué par `flux` : ce qu'il écrit, puis (code, stderr, tué).
        self.dump_contenu = DUMP
        self.dump_issue = (0, "", False)
        self.faits = dict(FAITS)
        self.libre = 10**12
        self.chowns = []
        self.verrou_pendant_sauvegarde = None
        self.lever = {}
        # Levées APRÈS que l'étape a écrit son fichier.
        self.lever_apres = {}
        self.vu = {}

    def _lever(self, etape):
        erreur = self.lever.get(etape)
        if erreur is not None:
            raise erreur

    def lanceur(self, argv, timeout=60):
        self.appels.append(" ".join(argv))
        if argv[:2] == ["systemctl", "show"]:
            unite = argv[-1]
            noms = [argv[i + 1] for i, a in enumerate(argv) if a == "-p"]
            if noms == ["ActiveState"] and self.reponses_etat:
                return self.reponses_etat.pop(0)
            if unite == self.unite:
                props = dict(self.proprietes, ActiveState=self.etat)
            elif unite in self.workdirs:
                props = {
                    "LoadState": "loaded",
                    "WorkingDirectory": self.workdirs[unite],
                }
            else:
                props = {"LoadState": "not-found"}
            return 0, "".join(f"{n}={props.get(n, '')}\n" for n in noms)
        if argv[:2] == ["systemctl", "list-units"]:
            return 0, self.liste_unites
        if argv[:2] == ["systemctl", "is-active"]:
            return (0 if self.etat == "active" else 3), self.etat + "\n"
        if argv[:2] == ["systemctl", "stop"]:
            if not self.arret_sans_effet:
                self.etat = self.etat_apres_arret
            self._lever("stop")
            return self.arret_code, ""
        if argv[:2] == ["systemctl", "start"]:
            self.horloge += 10
            self.horloge_au_demarrage = self.horloge
            if self.demarrage_code:
                return self.demarrage_code, "Job failed"
            self.etat = "active"
            if self.odoo_logfile and self.logfile_au_demarrage:
                with open(self.odoo_logfile, "a") as f:
                    f.write(self.logfile_au_demarrage)
            return 0, ""
        return 1, "commande inattendue"

    def journal(self, unite, epoque):
        self.appels.append("journalctl")
        self.epoque_journal = epoque
        return self.journal_texte

    def euid(self):
        return self.euid_valeur

    def utilisateur_courant(self):
        return "demo"

    def home(self, utilisateur):
        return os.path.join(self.wd, "home_" + utilisateur)

    def port_ecoute(self, hote, port):
        self.appels.append(f"port {hote}:{port}")
        self._lever("port")
        if self.etat == "active":
            return self.horloge_au_demarrage is None or (
                self.ecoute_apres_demarrage
            )
        return self.port_apres_arret

    def processus(self):
        self._lever("processus")
        return self.processus_liste

    def pids_exclus(self):
        return ()

    def maintenant(self):
        return self.horloge

    def dormir(self, secondes):
        self.horloge += secondes

    def sonder(self, cible, delai):
        self.appels.append(f"sonde {cible}")
        return self.sonde

    def inscriptible(self, dossier, utilisateur):
        return dossier not in self.non_inscriptibles

    def _dans_le_bac(self, chemin):
        """Garde : rien ne se crée hors du dossier temporaire du test."""
        bac = os.path.dirname(self.wd)
        if not os.path.abspath(chemin).startswith(bac + os.sep):
            raise AssertionError(f"création hors du test : {chemin}")

    def creer_dossier(self, dossier, utilisateur, mode=0o750):
        self.appels.append(f"mkdir {dossier} {utilisateur}")
        self._dans_le_bac(dossier)
        self._lever("mkdir")
        os.mkdir(dossier, mode)

    def mkdir(self, dossier, mode):
        self.appels.append(f"mkdir {dossier}")
        self._dans_le_bac(dossier)
        self._lever("mkdir")
        os.mkdir(dossier, mode)

    def chown(self, chemin, utilisateur):
        self.chowns.append((os.path.basename(chemin), utilisateur))

    def fchown(self, fd, utilisateur):
        chemin = os.readlink(f"/proc/self/fd/{fd}")
        self.chowns.append((os.path.basename(chemin), utilisateur))

    def uid(self, utilisateur):
        return os.getuid()

    def espace_libre(self, chemin):
        return self.libre

    def requete(self, argv, env, delai=60):
        self.appels.append("requete " + " ".join(argv))
        self.vu["requete"] = {"argv": list(argv), "env": dict(env)}
        psql = any(os.path.basename(a) == "psql" for a in argv)
        if psql and "json_build_object" in argv[-1]:
            return 0, json.dumps(self.faits) + "\n", ""
        return 1, "", "commande inattendue"

    def flux(self, argv, env, recevoir, delai):
        self.appels.append(f"backup {' '.join(argv)}")
        self.vu["backup"] = {
            "argv": list(argv),
            "env": dict(env),
            "etat": self.etat,
            "delai": delai,
        }
        sonde = lock.Verrou("erplibre-db-demo_db", self.dossier_verrou)
        try:
            sonde.acquerir()
        except lock.VerrouPris:
            self.verrou_pendant_sauvegarde = True
        else:
            self.verrou_pendant_sauvegarde = False
            sonde.relacher()
        self._lever("backup")
        recevoir(self.dump_contenu)
        erreur = self.lever_apres.get("backup")
        if erreur is not None:
            raise erreur
        return self.dump_issue

    def proteger_signaux(self):
        return lambda: None

    def ignorer_interruptions(self):
        return lambda: None

    def lancer_long(self, argv, cwd, env, journal, delai):
        nature = "odoo"
        self.appels.append(f"{nature} {' '.join(argv)}")
        self.vu[nature] = {
            "argv": list(argv),
            "cwd": cwd,
            "etat": self.etat,
            "delai": delai,
        }
        self._lever(nature)
        sonde = lock.Verrou("erplibre-db-demo_db", self.dossier_verrou)
        try:
            sonde.acquerir()
        except lock.VerrouPris:
            self.verrou_tenu = True
        else:
            self.verrou_tenu = False
            sonde.relacher()
        with open(journal, "a") as f:
            f.write(self.odoo_sortie)
        if self.odoo_logfile:
            with open(self.odoo_logfile, "a") as f:
                f.write(self.odoo_ajout_logfile)
        return self.odoo_issue


def ecrire(chemin, texte=""):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w") as f:
        f.write(texte)
    return chemin


class Base(unittest.TestCase):
    """Un checkout fabriqué : run.sh, config.conf, addons, un filestore ;
    les dossiers de sauvegarde et d'état dans le dossier temporaire."""

    CONFIG = (
        "[options]\naddons_path = addons,custom\nxmlrpc_port = 10000\n"
        "data_dir = data\n"
    )

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.tmp = d.name
        self.wd = os.path.join(self.tmp, "odoo")
        ecrire(os.path.join(self.wd, "run.sh"), "#!/bin/bash\n")
        self.filestore = os.path.join(self.wd, "data", "filestore", "demo_db")
        ecrire(os.path.join(self.filestore, "ab", "f0"), "piece jointe")
        self.dest = os.path.join(self.tmp, "sauvegardes")
        self.etat = os.path.join(self.tmp, "etat")
        os.makedirs(self.dest)
        os.makedirs(self.etat)
        # Les valeurs par défaut des options visent /var : chaque appel de
        # main, même sans --backup-dest, reste dans le dossier temporaire.
        # Elles visent d'AUTRES dossiers que ceux que `lancer` passe : une
        # option perdue en route écrirait là, et se verrait.
        self.dest_defaut = os.path.join(self.tmp, "dest_par_defaut")
        self.etat_defaut = os.path.join(self.tmp, "etat_par_defaut")
        for nom, valeur in (
            ("DEST_PAR_DEFAUT", self.dest_defaut),
            ("ETAT_PAR_DEFAUT", self.etat_defaut),
        ):
            rustine = mock.patch.object(um.odoo_backup, nom, valeur)
            rustine.start()
            self.addCleanup(rustine.stop)
        self.dossier = os.path.join(self.dest, "demo_db")
        self.conf = ecrire(os.path.join(self.wd, "config.conf"), self.CONFIG)
        for nom in ("my_module_a", "my_module_b", "other_module"):
            ecrire(
                os.path.join(self.wd, "custom", nom, "__manifest__.py"), "{}"
            )
        ecrire(
            os.path.join(self.wd, "custom", "my_module_nomanifest", "readme")
        )
        ecrire(
            os.path.join(self.wd, "addons", "base", "__manifest__.py"), "{}"
        )
        self.journaux = os.path.join(self.tmp, "journaux")
        self.verrous = os.path.join(self.tmp, "verrous")
        os.makedirs(self.verrous)
        self.systeme = FauxSysteme(self.wd, self.verrous)

    def lancer(self, *options, systeme=None):
        argv = ["--module", "my_module_*", "--log-dir", self.journaux]
        argv += ["--backup-dest", self.dest, "--state-dir", self.etat]
        argv += list(options)
        if "--service" not in options:
            argv += ["--service", "erplibre_demo"]
        sortie, erreurs = io.StringIO(), io.StringIO()
        rapport = report.Rapport(flux=sortie, erreurs=erreurs, couleur=False)
        with (
            contextlib.redirect_stdout(sortie),
            contextlib.redirect_stderr(erreurs),
        ):
            code = um.main(argv, systeme or self.systeme, rapport)
        self.sortie, self.erreurs = sortie.getvalue(), erreurs.getvalue()
        return code

    def rang(self, debut):
        """Le rang du premier appel qui commence par `debut`."""
        for i, appel in enumerate(self.systeme.appels):
            if appel.startswith(debut):
                return i
        self.fail(f"aucun appel « {debut} » dans {self.systeme.appels}")

    def a_appele(self, debut):
        return any(a.startswith(debut) for a in self.systeme.appels)

    def fichiers_de_sauvegarde(self):
        """Les fichiers du dossier de la base, sidecars et provisoires
        compris ; [] s'il n'existe pas."""
        if not os.path.isdir(self.dossier):
            return []
        return sorted(os.listdir(self.dossier))


class TestOrdreEtReussite(Base):
    def test_arret_sauvegarde_odoo_demarrage(self):
        self.assertEqual(self.lancer(), um.CODE_OK, self.sortie)
        stop = self.rang("systemctl stop")
        self.assertLess(stop, self.rang("backup "))
        self.assertLess(self.rang("backup "), self.rang("odoo "))
        self.assertLess(self.rang("odoo "), self.rang("systemctl start"))
        self.assertLess(self.rang("systemctl start"), self.rang("sonde "))
        self.assertLess(self.rang("sonde "), self.rang("journalctl"))
        self.assertEqual(self.systeme.vu["odoo"]["etat"], "inactive")
        self.assertEqual(self.systeme.vu["backup"]["etat"], "inactive")
        self.assertEqual(self.systeme.vu["odoo"]["cwd"], self.wd)
        self.assertEqual(self.systeme.etat, "active")

    def test_la_commande_odoo(self):
        self.lancer()
        argv = self.systeme.vu["odoo"]["argv"]
        debut = argv.index("/bin/bash")
        self.assertEqual(
            argv[:debut], ["env", "HOME=" + self.systeme.home("demo")]
        )
        self.assertEqual(
            argv[debut:],
            [
                "/bin/bash",
                os.path.join(self.wd, "run.sh"),
                "-c",
                self.conf,
                "-d",
                "demo_db",
                "-u",
                "my_module_a,my_module_b",
                "--stop-after-init",
                "--no-http",
                "--workers=0",
                "--max-cron-threads=0",
            ],
        )
        self.assertEqual(self.systeme.vu["odoo"]["delai"], 1800)

    def test_la_commande_de_sauvegarde(self):
        self.assertEqual(self.lancer(), um.CODE_OK, self.sortie)
        # Même compte : pg_dump directement, sans runuser ni odoo_bin.sh.
        self.assertEqual(
            self.systeme.vu["backup"]["argv"],
            ["pg_dump", "--no-owner", "demo_db"],
        )
        self.assertEqual(self.systeme.vu["backup"]["delai"], 1800)
        noms = self.fichiers_de_sauvegarde()
        self.assertEqual(len(noms), 2, noms)
        self.assertTrue(RE_SAUVEGARDE.fullmatch(noms[0]), noms)
        self.assertEqual(noms[1], noms[0] + ".sha256")
        with zipfile.ZipFile(os.path.join(self.dossier, noms[0])) as z:
            self.assertEqual(
                z.namelist(), ["dump.sql", "manifest.json", "filestore/ab/f0"]
            )
        with open(os.path.join(self.etat, "demo_db", "state.json")) as f:
            etat = json.load(f)
        self.assertEqual(
            etat["last_success"]["file"], os.path.join(self.dossier, noms[0])
        )
        # Sous root, tout ce qui est créé est donné au compte de l'unité.
        self.assertIn((noms[0] + ".partial", "demo"), self.systeme.chowns)

    def test_la_sauvegarde_court_sous_le_verrou_deja_tenu(self):
        self.assertEqual(self.lancer(), um.CODE_OK, self.sortie)
        self.assertIs(self.systeme.verrou_pendant_sauvegarde, True)

    def test_odoo_conf_vaut_pour_la_sauvegarde_et_la_mise_a_jour(self):
        autre = ecrire(
            os.path.join(self.tmp, "autre.conf"),
            self.CONFIG.replace(
                "data_dir = data", "data_dir = " + self.wd + "/data"
            )
            + "db_password = secret-demo\n",
        )
        self.assertEqual(self.lancer("--odoo-conf", autre), um.CODE_OK)
        vu = self.systeme.vu["backup"]
        self.assertEqual(vu["env"]["PGPASSWORD"], "secret-demo")
        self.assertNotIn("secret-demo", " ".join(vu["argv"]))
        self.assertNotIn("secret-demo", self.sortie)
        argv = self.systeme.vu["odoo"]["argv"]
        # Le dernier -c est celui qu'Odoo retient.
        dernier = len(argv) - 1 - argv[::-1].index("-c")
        self.assertEqual(argv[dernier + 1], autre)

    def test_le_verrou_est_tenu_pendant_la_mise_a_jour(self):
        self.assertEqual(self.lancer(), um.CODE_OK)
        self.assertIs(self.systeme.verrou_tenu, True)

    def test_port_lu_dans_xmlrpc_port(self):
        self.lancer()
        self.assertIn(
            "sonde http://127.0.0.1:10000/web/login?db=demo_db",
            self.systeme.appels,
        )

    def test_journal_ecrit_dans_le_dossier_demande(self):
        self.lancer()
        noms = os.listdir(self.journaux)
        self.assertEqual(len(noms), 1)
        self.assertTrue(
            re.fullmatch(r"update-demo_db-\d{8}-\d{6}\.log", noms[0])
        )

    def test_sortie_lisible_numerotee(self):
        self.lancer()
        for etape in ("[1/5]", "[2/5]", "[3/5]", "[4/5]", "[5/5]"):
            self.assertIn(etape, self.sortie)
        self.assertNotIn("\x1b[", self.sortie)

    def test_sans_sauvegarde(self):
        self.assertEqual(self.lancer("--no-backup"), um.CODE_OK)
        self.assertFalse(self.a_appele("backup "))
        self.assertIn("[4/4]", self.sortie)

    def test_un_compte_different_passe_par_runuser(self):
        self.systeme.proprietes["User"] = "svc"
        self.lancer()
        argv = self.systeme.vu["odoo"]["argv"]
        self.assertEqual(argv[:5], ["runuser", "-u", "svc", "--", "env"])
        self.assertIn("HOME=" + self.systeme.home("svc"), argv)

    def test_environnement_de_l_unite_et_nix_ld(self):
        self.systeme.proprietes["Environment"] = (
            "NIX_LD_LIBRARY_PATH=/nix/lib LD_LIBRARY_PATH=/usr/lib"
        )
        self.lancer()
        argv = self.systeme.vu["odoo"]["argv"]
        self.assertIn("NIX_LD_LIBRARY_PATH=/nix/lib", argv)
        self.assertIn("LD_LIBRARY_PATH=/nix/lib:/usr/lib", argv)


class TestEchecsDeLaMiseAJour(Base):
    def test_code_non_nul(self):
        self.systeme.odoo_issue = um.Issue(3, False, False)
        self.assertEqual(self.lancer(), um.CODE_ECHEC)
        self.assertIn("3", self.sortie)
        self.assertLess(self.rang("odoo "), self.rang("systemctl start"))
        self.assertEqual(self.systeme.etat, "active")

    def test_ligne_error_dans_la_sortie(self):
        self.systeme.odoo_sortie = LIGNE_ERREUR + "\n"
        self.assertEqual(self.lancer(), um.CODE_ECHEC)
        self.assertIn("Failed to load module", self.sortie)
        self.assertTrue(self.a_appele("systemctl start"))

    def test_warning_ne_fait_pas_echouer(self):
        self.systeme.odoo_sortie = LIGNE_AVERTISSEMENT + "\n"
        self.assertEqual(self.lancer(), um.CODE_OK)

    def test_ignore_error(self):
        self.systeme.odoo_sortie = LIGNE_ERREUR + "\n"
        self.assertEqual(
            self.lancer("--ignore-error", "Failed to load"), um.CODE_OK
        )

    def test_delai_depasse(self):
        self.systeme.odoo_issue = um.Issue(-15, True, False)
        self.assertEqual(self.lancer("--timeout", "5"), um.CODE_ECHEC)
        self.assertEqual(self.systeme.vu["odoo"]["delai"], 5)
        self.assertTrue(self.a_appele("systemctl start"))

    def logfile_configure(self):
        """Un logfile posé dans la configuration, déjà porteur d'une
        ancienne erreur ; la sortie d'Odoo elle-même reste propre."""
        logfile = ecrire(
            os.path.join(self.wd, "odoo.log"), LIGNE_ERREUR + "\n"
        )
        with open(self.conf, "a") as f:
            f.write("logfile = odoo.log\n")
        self.systeme.odoo_logfile = logfile
        return logfile

    def test_logfile_configure_l_ancienne_erreur_ne_compte_pas(self):
        self.logfile_configure()
        self.assertEqual(self.lancer(), um.CODE_OK, self.sortie)
        self.assertTrue(self.a_appele("odoo "))

    def test_logfile_configure_erreur_ajoutee_pendant_la_mise_a_jour(self):
        self.logfile_configure()
        self.systeme.odoo_ajout_logfile = LIGNE_ERREUR + "\n"
        self.assertEqual(self.lancer(), um.CODE_ECHEC, self.sortie)
        self.assertTrue(self.a_appele("odoo "))
        self.assertIn(
            um.t(
                "{count} ERROR/CRITICAL record(s) in {groups} group(s) during"
                " the update."
            ).format(count=1, groups=1),
            self.sortie,
        )
        self.assertTrue(self.a_appele("systemctl start"))

    def test_u1_traces_groupees(self):
        """Deux traces identiques et une autre : un échec, deux groupes,
        le plus nombreux d'abord."""
        self.systeme.odoo_sortie = (
            TRACE_KEYERROR + TRACE_KEYERROR + TRACE_VALUEERROR
        )
        self.assertEqual(self.lancer(), um.CODE_ECHEC, self.sortie)
        self.assertIn(
            um.t(
                "{count} ERROR/CRITICAL record(s) in {groups} group(s) during"
                " the update."
            ).format(count=3, groups=2),
            self.sortie,
        )
        self.assertIn("[2x] KeyError: 'x' (odoo.modules.loading)", self.sortie)
        self.assertLess(
            self.sortie.index("[2x] KeyError"),
            self.sortie.index("[1x] ValueError"),
        )
        self.assertTrue(self.a_appele("systemctl start"))

    def test_u3_ignore_error_retire_tout_l_enregistrement(self):
        self.systeme.odoo_sortie = TRACE_KEYERROR
        self.assertEqual(
            self.lancer("--ignore-error", "Failed to load"), um.CODE_OK
        )
        # Le titre de la trace compte aussi.
        self.assertEqual(self.lancer("--ignore-error", "KeyError"), um.CODE_OK)
        # Le bruit connu de log_check n'est pas écarté ici.
        self.systeme.odoo_sortie = (
            "2026-01-31 12:00:00,123 4242 ERROR demo_db"
            " odoo.addons.web.controllers.binary: .map should have been"
            " generated through debug assets, (version 0a1b2c3 most likely"
            " outdated)\n"
        )
        self.assertEqual(self.lancer(), um.CODE_ECHEC)


class TestFilet(Base):
    """Après l'arrêt, chaque chemin relance le service qui tournait."""

    def verifier_relance(self, code_attendu, *options):
        self.assertEqual(self.lancer(*options), code_attendu, self.sortie)
        self.assertLess(
            self.rang("systemctl stop"), self.rang("systemctl start")
        )
        self.assertEqual(self.systeme.etat, "active")

    def test_exception_a_chaque_etape(self):
        for etape in ("stop", "port", "processus", "backup", "odoo"):
            with self.subTest(etape=etape):
                self.systeme = FauxSysteme(self.wd, self.verrous)
                self.systeme.lever[etape] = RuntimeError("panne " + etape)
                self.verifier_relance(um.CODE_ECHEC)
                self.assertIn("panne " + etape, self.sortie)

    def test_ctrl_c_pendant_la_sauvegarde(self):
        self.systeme.lever["backup"] = KeyboardInterrupt()
        self.verifier_relance(um.CODE_INTERROMPU)
        self.assertFalse(self.a_appele("odoo "))

    def test_sigterm_pendant_la_mise_a_jour(self):
        self.systeme.lever["odoo"] = um.Interruption(signal.SIGTERM)
        self.verifier_relance(um.CODE_INTERROMPU)

    def test_interruption_confirmee_pendant_la_mise_a_jour(self):
        self.systeme.odoo_issue = um.Issue(-15, False, True)
        self.verifier_relance(um.CODE_INTERROMPU)
        self.assertLess(self.rang("odoo "), self.rang("systemctl start"))

    def test_sauvegarde_en_echec_rien_n_est_mis_a_jour(self):
        self.systeme.dump_issue = (
            1,
            "pg_dump: error: connexion refusée",
            False,
        )
        self.verifier_relance(um.CODE_ECHEC)
        self.assertFalse(self.a_appele("odoo "))
        self.assertIn("connexion refusée", self.sortie)
        # Le zip tronqué est retiré.
        self.assertEqual(self.fichiers_de_sauvegarde(), [])

    def test_pg_dump_hors_delai(self):
        self.systeme.dump_issue = (-9, "", True)
        self.verifier_relance(um.CODE_ECHEC, "--timeout", "5")
        self.assertEqual(self.systeme.vu["backup"]["delai"], 5)
        self.assertFalse(self.a_appele("odoo "))

    def test_sauvegarde_incomplete(self):
        self.systeme.dump_contenu = b"-- dump coupe\n"
        self.verifier_relance(um.CODE_ECHEC)
        self.assertFalse(self.a_appele("odoo "))
        self.assertEqual(self.fichiers_de_sauvegarde(), [])

    def test_sauvegarde_tronquee_puis_exception(self):
        for erreur, code in (
            (um.Interruption(signal.SIGTERM), um.CODE_INTERROMPU),
            (RuntimeError("panne"), um.CODE_ECHEC),
            (KeyboardInterrupt(), um.CODE_INTERROMPU),
        ):
            with self.subTest(erreur=type(erreur).__name__):
                self.systeme = FauxSysteme(self.wd, self.verrous)
                self.systeme.lever_apres["backup"] = erreur
                self.verifier_relance(code)
                self.assertFalse(self.a_appele("odoo "))
                self.assertEqual(self.fichiers_de_sauvegarde(), [])

    def test_sortie_qui_casse_apres_l_arret(self):
        """Terminal raccroché après l'arrêt : chaque écriture rend EIO, le
        service repart quand même — sur une fin normale comme sur une
        interruption."""
        systeme = self.systeme

        class Raccroche(io.StringIO):
            def write(self, texte):
                if systeme.etat != "active":
                    raise OSError(errno.EIO, "Input/output error")
                return super().write(texte)

        for lever in (None, um.Interruption(signal.SIGHUP)):
            with self.subTest(lever=type(lever).__name__):
                systeme = self.systeme = FauxSysteme(self.wd, self.verrous)
                if lever is not None:
                    systeme.lever["odoo"] = lever
                rapport = report.Rapport(
                    flux=Raccroche(), erreurs=Raccroche(), couleur=False
                )
                um.main(
                    [
                        "--module",
                        "my_module_*",
                        "--service",
                        "erplibre_demo",
                        "--log-dir",
                        self.journaux,
                        "--no-backup",
                    ],
                    systeme,
                    rapport,
                )
                self.assertTrue(self.a_appele("systemctl start"))
                self.assertEqual(systeme.etat, "active")

    def test_start_part_avant_toute_ecriture_du_rapport(self):
        systeme = self.systeme

        class Trace(report.Rapport):
            def etape(self, titre):
                systeme.appels.append("rapport " + titre)
                return super().etape(titre)

        um.main(
            [
                "--module",
                "my_module_*",
                "--service",
                "erplibre_demo",
                "--log-dir",
                self.journaux,
            ],
            systeme,
            Trace(flux=io.StringIO(), erreurs=io.StringIO()),
        )
        demarrage = um.t("Starting {unit}").format(unit=systeme.unite)
        self.assertLess(
            self.rang("systemctl start"), self.rang("rapport " + demarrage)
        )

    def test_etat_inconnu_avant_l_arret_rien_n_est_arrete(self):
        self.systeme.reponses_etat = [(124, "timeout")]
        self.assertEqual(self.lancer(), um.CODE_REFUS)
        self.assertFalse(self.a_appele("systemctl stop"))
        self.assertIn("erplibre_demo.service", self.erreurs)

    def test_etat_transitoire_avant_l_arret_compte_pour_actif(self):
        for valeur in ("activating", "reloading", "deactivating"):
            with self.subTest(etat=valeur):
                self.systeme = FauxSysteme(self.wd, self.verrous)
                self.systeme.reponses_etat = [(0, f"ActiveState={valeur}\n")]
                self.verifier_relance(um.CODE_OK, "--no-backup")

    def test_stop_en_echec(self):
        self.systeme.arret_code = 1
        self.verifier_relance(um.CODE_ECHEC)
        self.assertFalse(self.a_appele("backup "))
        self.assertFalse(self.a_appele("odoo "))

    def test_encore_deactivating_apres_le_stop(self):
        self.systeme.etat_apres_arret = "deactivating"
        self.verifier_relance(um.CODE_ECHEC)
        self.assertIn("deactivating", self.sortie)
        self.assertFalse(self.a_appele("backup "))
        self.assertFalse(self.a_appele("odoo "))

    def test_sauvegarde_sans_filestore_est_un_avertissement(self):
        import shutil

        shutil.rmtree(self.filestore)
        self.systeme.faits["stored_attachments"] = 0
        self.verifier_relance(um.CODE_OK)
        self.assertIn("[ATTN]", self.sortie)

    def test_service_inactif_avant_reste_arrete(self):
        self.systeme.etat = "inactive"
        self.assertEqual(self.lancer(), um.CODE_OK, self.sortie)
        self.assertFalse(self.a_appele("systemctl start"))
        self.assertIn("[ATTN]", self.sortie)

    def test_arret_sans_effet(self):
        self.systeme.arret_sans_effet = True
        self.assertEqual(self.lancer(), um.CODE_ECHEC)
        self.assertFalse(self.a_appele("odoo "))
        self.assertFalse(self.a_appele("systemctl start"))


class TestOdooHorsDuService(Base):
    def test_meme_base_refuse_puis_relance(self):
        self.systeme.processus_liste = [
            (4242, ["python3", "./odoo-bin", "-c", "c.conf", "-d", "demo_db"])
        ]
        self.assertEqual(self.lancer(), um.CODE_ECHEC)
        self.assertFalse(self.a_appele("odoo "))
        self.assertFalse(self.a_appele("backup "))
        self.assertLess(
            self.rang("systemctl stop"), self.rang("systemctl start")
        )

    def test_force_continue(self):
        self.systeme.processus_liste = [
            (4242, ["python3", "./odoo-bin", "-d", "demo_db"])
        ]
        self.assertEqual(self.lancer("--force"), um.CODE_OK)
        self.assertIn("--force", self.sortie)

    def test_autre_base_n_est_pas_une_gene(self):
        self.systeme.processus_liste = [
            (4242, ["python3", "./odoo-bin", "-d", "autre_db"])
        ]
        self.assertEqual(self.lancer(), um.CODE_OK)

    def test_port_qui_repond_encore(self):
        self.systeme.port_apres_arret = True
        self.assertEqual(self.lancer(), um.CODE_ECHEC)
        self.assertFalse(self.a_appele("odoo "))
        self.assertTrue(self.a_appele("systemctl start"))


class TestRedemarrage(Base):
    def test_start_en_echec(self):
        self.systeme.demarrage_code = 1
        self.assertEqual(self.lancer(), um.CODE_ECHEC)
        self.assertIn("journalctl -u erplibre_demo.service", self.sortie)

    def test_actif_mais_n_ecoute_pas(self):
        self.systeme.ecoute_apres_demarrage = False
        self.assertEqual(self.lancer("--start-wait", "6"), um.CODE_ECHEC)
        self.assertIn("10000", self.sortie)
        self.assertFalse(self.a_appele("sonde "))

    def test_pas_de_reponse_http(self):
        self.systeme.sonde = False
        self.assertEqual(self.lancer(), um.CODE_ECHEC)

    def test_erreur_au_journal_apres_demarrage(self):
        self.systeme.journal_texte = LIGNE_ERREUR + "\n"
        self.assertEqual(self.lancer(), um.CODE_ECHEC)
        self.assertIn("Failed to load module", self.sortie)

    def test_l_epoque_est_prise_avant_start(self):
        # Le faux `start` avance l'horloge : une époque lue après lui est
        # plus grande que `horloge_au_demarrage` - 10, et plus petite
        # seulement si elle est lue avant.
        self.lancer()
        self.assertIsNotNone(self.systeme.epoque_journal)
        self.assertLess(
            self.systeme.epoque_journal, self.systeme.horloge_au_demarrage
        )

    def test_erreur_au_logfile_apres_demarrage(self):
        logfile = ecrire(os.path.join(self.wd, "odoo.log"))
        with open(self.conf, "a") as f:
            f.write("logfile = odoo.log\n")
        self.systeme.odoo_logfile = logfile
        self.systeme.logfile_au_demarrage = LIGNE_ERREUR + "\n"
        self.assertEqual(self.lancer(), um.CODE_ECHEC, self.sortie)
        self.assertIn(
            um.t(
                "{count} ERROR/CRITICAL record(s) in {groups} group(s) since"
                " the start."
            ).format(count=1, groups=1),
            self.sortie,
        )

    def test_u2_journal_apres_demarrage_groupe(self):
        """`journalctl -o cat` : les lignes de la trace, sans préfixe,
        restent avec leur en-tête ; le service reste lancé."""
        self.systeme.journal_texte = TRACE_KEYERROR * 2
        self.assertEqual(self.lancer(), um.CODE_ECHEC, self.sortie)
        self.assertIn("[2x] KeyError: 'x'", self.sortie)
        self.assertNotIn("[1x] Traceback", self.sortie)
        self.assertEqual(self.systeme.etat, "active")


class TestVerrouRootSimulation(Base):
    def test_verrou_pris_rend_75_sans_rien_arreter(self):
        with lock.Verrou("erplibre-db-demo_db", self.verrous):
            self.assertEqual(self.lancer(), um.CODE_VERROU)
        self.assertFalse(self.a_appele("systemctl stop"))
        self.assertIn("demo_db", self.erreurs)

    def test_dossier_du_verrou_absent_refuse_sans_rien_arreter(self):
        self.systeme.dossier_verrou = os.path.join(self.tmp, "absent")
        self.assertEqual(self.lancer(), um.CODE_REFUS)
        self.assertIn("absent", self.erreurs)
        self.assertFalse(self.a_appele("systemctl stop"))

    def test_le_verrou_de_la_base_est_partage_et_strict(self):
        verrou = um.Systeme(
            interactif=False, dossier_verrou=self.verrous
        ).verrou("demo_db")
        self.assertTrue(verrou.strict)
        self.assertEqual(
            verrou.chemin,
            os.path.join(self.verrous, "erplibre-db-demo_db.lock"),
        )

    def test_root_exige(self):
        self.systeme.euid_valeur = 1000
        self.assertEqual(self.lancer(), um.CODE_REFUS)
        self.assertFalse(self.a_appele("systemctl stop"))

    def test_simulation_ne_touche_rien(self):
        self.systeme.euid_valeur = 1000
        with lock.Verrou("erplibre-db-demo_db", self.verrous):
            self.assertEqual(self.lancer("--dry-run"), um.CODE_OK)
        for interdit in (
            "systemctl stop",
            "systemctl start",
            "odoo ",
            "backup ",
        ):
            self.assertFalse(self.a_appele(interdit), interdit)
        self.assertFalse(os.path.exists(self.journaux))
        self.assertFalse(os.path.exists(self.dossier))
        self.assertIn(
            "(simulation) systemctl stop -- erplibre_demo.service", self.sortie
        )
        self.assertIn("--stop-after-init", self.sortie)
        self.assertIn("pg_dump --no-owner demo_db", self.sortie)
        self.assertNotIn("odoo_bin.sh", self.sortie)

    def test_simulation_affiche_les_commandes_executees(self):
        self.systeme.proprietes["User"] = "svc"
        self.assertEqual(self.lancer("--dry-run"), um.CODE_OK)
        simulation = self.sortie
        self.assertEqual(self.lancer(), um.CODE_OK, self.sortie)
        for nature in ("backup", "odoo"):
            with self.subTest(nature=nature):
                argv = self.systeme.vu[nature]["argv"]
                self.assertEqual(argv[:3], ["runuser", "-u", "svc"])
                self.assertIn(um.joindre(argv), simulation)


class TestDetection(Base):
    LIGNES = (
        "erplibre_demo.service loaded active running demo\n"
        "nginx.service loaded active running web\n"
    )

    def test_unite_devinee_par_le_dossier_de_travail(self):
        self.systeme.liste_unites = (
            "erplibre_demo.service loaded active running demo\n"
            "erplibre_autre.service loaded active running autre\n"
        )
        self.systeme.workdirs = {"erplibre_autre.service": "/srv/autre"}
        args = um.analyser(["--module", "base", "--dry-run"])
        with contextlib.redirect_stdout(io.StringIO()):
            plan = um.detecter(args, self.systeme, racine=self.wd)
        self.assertEqual(plan.unite, "erplibre_demo.service")
        self.assertEqual(plan.origine_unite, "workdir")

    def test_unites_ambigues_refusees(self):
        self.systeme.liste_unites = (
            "erplibre_x.service loaded active running x\n"
            "odoo.service loaded active running y\n"
        )
        args = um.analyser(["--module", "base"])
        with self.assertRaises(um.Refus) as ctx:
            um.detecter(args, self.systeme, racine="/srv/ailleurs")
        self.assertIn("odoo.service", str(ctx.exception))
        self.assertFalse(self.a_appele("systemctl stop"))

    def test_service_explicite_l_emporte(self):
        self.systeme.liste_unites = self.LIGNES
        self.lancer("--dry-run")
        self.assertFalse(self.a_appele("systemctl list-units"))

    def test_service_introuvable(self):
        self.assertEqual(self.lancer("--service", "absent"), um.CODE_REFUS)
        self.assertIn("absent.service", self.erreurs)
        self.assertFalse(self.a_appele("systemctl stop"))

    def test_base_explicite_puis_unite_puis_db_name(self):
        # Sans sauvegarde : le filestore inventé est celui de demo_db.
        self.lancer("--db", "my_db", "--dry-run", "--no-backup")
        self.assertIn("-d my_db", self.sortie)
        self.systeme.proprietes["ExecStart"] = (
            "{ path=/bin/bash ; argv[]=/bin/bash "
            + os.path.join(self.wd, "run.sh")
            + " ; ignore_errors=no }"
        )
        with open(self.conf, "a") as f:
            f.write("db_name = conf_db\n")
        self.lancer("--dry-run", "--no-backup")
        self.assertIn("conf_db (db_name)", self.sortie)

    def test_base_introuvable(self):
        self.systeme.proprietes["ExecStart"] = (
            "{ path=/bin/bash ; argv[]=/bin/bash "
            + os.path.join(self.wd, "run.sh")
            + " ; ignore_errors=no }"
        )
        with open(self.conf, "a") as f:
            f.write("db_name = False\n")
        self.assertEqual(self.lancer(), um.CODE_REFUS)
        self.assertIn("--db", self.erreurs)
        self.assertFalse(self.a_appele("systemctl stop"))

    def test_port_de_l_unite_l_emporte(self):
        self.systeme.proprietes["ExecStart"] = (
            "{ path=/bin/bash ; argv[]=/bin/bash "
            + os.path.join(self.wd, "run.sh")
            + " -d demo_db -p 8090 ; ignore_errors=no }"
        )
        self.lancer("--dry-run")
        self.assertIn("127.0.0.1:8090", self.sortie)

    def test_modules(self):
        self.assertEqual(self.lancer("--module", "zzz"), um.CODE_REFUS)
        self.assertIn("zzz", self.erreurs)
        self.systeme.appels.clear()
        self.assertEqual(
            um.main(
                [
                    "--module",
                    "zzz_*",
                    "--service",
                    "erplibre_demo",
                    "--dry-run",
                ],
                self.systeme,
                report.Rapport(flux=io.StringIO(), erreurs=io.StringIO()),
            ),
            um.CODE_REFUS,
        )

    def test_all(self):
        self.systeme.appels.clear()
        sortie = io.StringIO()
        code = um.main(
            ["--module", "all", "--service", "erplibre_demo", "--dry-run"],
            self.systeme,
            report.Rapport(flux=sortie, erreurs=io.StringIO()),
        )
        self.assertEqual(code, um.CODE_OK)
        self.assertIn("-u all ", sortie.getvalue())

    def test_motifs_refuses_par_l_analyseur(self):
        for valeur in ("my_module_*; rm -rf /", "My", "all,base", ""):
            with self.subTest(valeur=valeur):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        um.analyser(["--module", valeur])
                self.assertEqual(ctx.exception.code, 2)

    def test_options_numeriques_refusees(self):
        for option in (
            ["--timeout", "0"],
            ["--start-wait", "a[$(id)]"],
            ["--timeout"],
        ):
            with self.subTest(option=option):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        um.analyser(["--module", "base"] + option)
                self.assertEqual(ctx.exception.code, 2)

    def test_dossier_de_la_base_simule_sans_rien_creer(self):
        self.assertEqual(self.lancer("--dry-run"), um.CODE_OK, self.erreurs)
        self.assertIn(
            "(simulation) mkdir -m 0700 -- "
            + self.dossier
            + " && chown demo: --",
            self.sortie,
        )
        self.assertLess(
            self.sortie.index("mkdir"), self.sortie.index("systemctl stop")
        )
        self.assertFalse(os.path.exists(self.dossier))
        self.assertFalse(self.a_appele("mkdir"))

    def test_dossiers_crees_avant_l_arret_au_compte_de_l_unite(self):
        self.systeme.proprietes["User"] = "svc"
        self.assertEqual(self.lancer(), um.CODE_OK, self.erreurs)
        self.assertLess(
            self.rang(f"mkdir {self.dossier} svc"), self.rang("systemctl stop")
        )
        etat_base = os.path.join(self.etat, "demo_db")
        self.assertLess(
            self.rang(f"mkdir {etat_base} svc"), self.rang("systemctl stop")
        )
        self.assertEqual(len(self.fichiers_de_sauvegarde()), 2)

    def test_dossier_non_inscriptible_refuse_avant_l_arret(self):
        os.mkdir(self.dossier)
        self.systeme.non_inscriptibles.add(self.dossier)
        self.assertEqual(self.lancer(), um.CODE_REFUS)
        self.assertIn(self.dossier, self.erreurs)
        self.assertIn("--no-backup", self.erreurs)
        self.assertFalse(self.a_appele("systemctl stop"))
        self.assertEqual(self.lancer("--no-backup", "--dry-run"), um.CODE_OK)

    def test_creation_en_echec_rien_arrete(self):
        self.systeme.lever["mkdir"] = PermissionError(errno.EACCES, "refus")
        self.assertEqual(self.lancer(), um.CODE_REFUS)
        self.assertIn(self.dossier, self.erreurs)
        self.assertFalse(self.a_appele("systemctl stop"))
        self.assertEqual(self.systeme.etat, "active")

    def test_espace_insuffisant_refuse_avant_l_arret(self):
        self.systeme.libre = 10
        self.assertEqual(self.lancer(), um.CODE_REFUS)
        self.assertIn("--no-backup", self.erreurs)
        self.assertFalse(self.a_appele("systemctl stop"))
        self.assertFalse(self.a_appele("backup "))

    def test_filestore_absent_avec_pieces_jointes_stockees(self):
        import shutil

        shutil.rmtree(self.filestore)
        self.assertEqual(self.lancer(), um.CODE_REFUS)
        self.assertIn(self.filestore, self.erreurs)
        self.assertFalse(self.a_appele("systemctl stop"))

    def test_base_illisible_refuse_avant_l_arret(self):
        self.systeme.faits = {"base": None}
        self.assertEqual(self.lancer(), um.CODE_REFUS)
        self.assertFalse(self.a_appele("systemctl stop"))

    def test_dossiers_passes_et_non_les_valeurs_par_defaut(self):
        self.assertEqual(self.lancer(), um.CODE_OK, self.erreurs)
        zips = [n for n in self.fichiers_de_sauvegarde() if n.endswith(".zip")]
        self.assertEqual(len(zips), 1)
        self.assertTrue(
            os.path.isfile(os.path.join(self.etat, "demo_db", "state.json"))
        )
        for defaut in (self.dest_defaut, self.etat_defaut):
            self.assertFalse(os.path.exists(defaut), defaut)

    def test_simulation_sans_root_prevoit_les_dossiers_sous_sudo(self):
        if os.geteuid() == 0:
            self.skipTest("root écrit partout")
        parent = os.path.join(self.tmp, "lecture_seule")
        os.mkdir(parent)
        os.chmod(parent, 0o555)
        self.addCleanup(os.chmod, parent, 0o755)
        dest = os.path.join(parent, "sauvegardes")
        self.systeme.euid_valeur = 1000
        self.assertEqual(
            self.lancer("--dry-run", "--backup-dest", dest),
            um.CODE_OK,
            self.erreurs,
        )
        self.assertIn("sudo mkdir -m 0755 -- " + dest, self.sortie)
        self.assertIn(
            "sudo chown demo: -- " + os.path.join(dest, "demo_db"),
            self.sortie,
        )
        self.assertFalse(os.path.exists(dest))

    def test_list_db_n_empeche_plus_la_sauvegarde(self):
        with open(self.conf, "a") as f:
            f.write("list_db = False\n")
        self.assertEqual(self.lancer(), um.CODE_OK, self.erreurs)
        self.assertTrue(self.a_appele("backup "))

    def test_simulation_par_un_autre_compte_estimation_inconnue(self):
        self.systeme.euid_valeur = 1000
        self.systeme.proprietes["User"] = "svc"
        self.assertEqual(self.lancer("--dry-run"), um.CODE_OK, self.erreurs)
        self.assertIn(um.t("unknown (requires sudo)"), self.sortie)
        self.assertFalse(self.a_appele("requete "))


class TestLancerLong(unittest.TestCase):
    """Le vrai lanceur, sur un python qui dort : délai et interruption."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.journal = os.path.join(d.name, "j.log")
        self.cwd = d.name

    def argv(self, code):
        return [sys.executable, "-c", code]

    def test_code_et_sortie(self):
        s = um.Systeme(interactif=False)
        issue = s.lancer_long(
            self.argv("import os; print(os.getcwd()); raise SystemExit(3)"),
            self.cwd,
            os.environ.copy(),
            self.journal,
            30,
        )
        self.assertEqual(issue, um.Issue(3, False, False))
        with open(self.journal) as f:
            self.assertEqual(f.read().strip(), os.path.realpath(self.cwd))

    def test_delai_depasse_tue_le_groupe(self):
        s = um.Systeme(interactif=False, grace=1)
        issue = s.lancer_long(
            self.argv("import time; time.sleep(60)"),
            self.cwd,
            os.environ.copy(),
            self.journal,
            0.5,
        )
        self.assertTrue(issue.tue)
        self.assertIsNotNone(issue.code)

    def test_ctrl_c_confirme_attend_la_fin(self):
        questions = []

        def oui():
            questions.append(1)
            return True

        s = um.Systeme(interactif=True, grace=5, demander=oui)
        minuterie = threading.Timer(
            0.5, lambda: os.kill(os.getpid(), signal.SIGINT)
        )
        minuterie.start()
        self.addCleanup(minuterie.cancel)
        issue = s.lancer_long(
            self.argv("import time; time.sleep(60)"),
            self.cwd,
            os.environ.copy(),
            self.journal,
            30,
        )
        self.assertEqual(questions, [1])
        self.assertTrue(issue.interrompu)
        # Rendu seulement une fois le processus terminé : il a un code.
        self.assertIsNotNone(issue.code)

    def test_ctrl_c_non_reprend_puis_oui_interrompt(self):
        pid_fichier = os.path.join(self.cwd, "pid")
        questions = []

        def repondre():
            # Le processus tourne encore à chaque question : « non » l'a
            # laissé continuer.
            with open(pid_fichier) as f:
                os.kill(int(f.read()), 0)
            questions.append(1)
            if len(questions) == 1:
                threading.Timer(
                    0.3, lambda: os.kill(os.getpid(), signal.SIGINT)
                ).start()
                return False
            return True

        s = um.Systeme(interactif=True, grace=5, demander=repondre)
        minuterie = threading.Timer(
            0.8, lambda: os.kill(os.getpid(), signal.SIGINT)
        )
        minuterie.start()
        self.addCleanup(minuterie.cancel)
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            issue = s.lancer_long(
                self.argv(
                    "import os, time\n"
                    f"open({pid_fichier!r}, 'w').write(str(os.getpid()))\n"
                    "time.sleep(60)"
                ),
                self.cwd,
                os.environ.copy(),
                self.journal,
                30,
            )
        self.assertEqual(questions, [1, 1])
        self.assertIn(um.t("Resuming."), sortie.getvalue())
        self.assertTrue(issue.interrompu)

    def test_ctrl_c_sans_terminal_interrompt_sans_demander(self):
        questions = []
        s = um.Systeme(
            interactif=False,
            grace=5,
            demander=lambda: questions.append(1) or False,
        )
        minuterie = threading.Timer(
            0.5, lambda: os.kill(os.getpid(), signal.SIGINT)
        )
        minuterie.start()
        self.addCleanup(minuterie.cancel)
        issue = s.lancer_long(
            self.argv("import time; time.sleep(60)"),
            self.cwd,
            os.environ.copy(),
            self.journal,
            30,
        )
        self.assertEqual(questions, [])
        self.assertTrue(issue.interrompu)

    def test_term_ignore_puis_kill_apres_la_grace(self):
        s = um.Systeme(interactif=False, grace=1)
        depart = time.monotonic()
        issue = s.lancer_long(
            self.argv(
                "import signal, time\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "time.sleep(60)"
            ),
            self.cwd,
            os.environ.copy(),
            self.journal,
            0.5,
        )
        self.assertTrue(issue.tue)
        self.assertEqual(issue.code, -signal.SIGKILL)
        self.assertGreaterEqual(time.monotonic() - depart, 1.4)

    def test_le_groupe_entier_est_arrete(self):
        pid_fichier = os.path.join(self.cwd, "petit_enfant")
        s = um.Systeme(interactif=False, grace=1)
        s.lancer_long(
            self.argv(
                "import subprocess, sys, time\n"
                "p = subprocess.Popen([sys.executable, '-c',"
                " 'import time; time.sleep(60)'])\n"
                f"open({pid_fichier!r}, 'w').write(str(p.pid))\n"
                "time.sleep(60)"
            ),
            self.cwd,
            os.environ.copy(),
            self.journal,
            1.5,
        )
        with open(pid_fichier) as f:
            petit_enfant = int(f.read())
        self.assertTrue(attendre_disparition(petit_enfant, 5))

    def test_propre_session(self):
        s = um.Systeme(interactif=False)
        issue = s.lancer_long(
            self.argv(
                "import os; print(os.getpid(), os.getpgid(0), os.getsid(0))"
            ),
            self.cwd,
            os.environ.copy(),
            self.journal,
            30,
        )
        self.assertEqual(issue.code, 0)
        with open(self.journal) as f:
            pid, pgid, sid = (int(v) for v in f.read().split())
        # Meneur de sa session et de son groupe : un Ctrl-C du terminal,
        # envoyé au groupe de premier plan, ne l'atteint pas.
        self.assertEqual((pgid, sid), (pid, pid))
        self.assertNotEqual(pgid, os.getpgrp())


def attendre_disparition(pid, delai):
    """True si `pid` n'existe plus, ou n'est plus qu'un zombie, avant
    `delai` secondes."""
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        try:
            with open(f"/proc/{pid}/stat") as f:
                if f.read().rsplit(")", 1)[1].split()[0] == "Z":
                    return True
        except FileNotFoundError:
            return True
        time.sleep(0.1)
    return False


class TestSignauxReels(Base):
    """Les vrais gestionnaires de signaux de `Systeme`, dans ce processus.

    Chaque test remet les gestionnaires d'origine, quoi qu'il arrive.
    """

    SIGNAUX = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)

    def setUp(self):
        super().setUp()
        origine = {n: signal.getsignal(n) for n in self.SIGNAUX}

        def remettre():
            for numero, gestionnaire in origine.items():
                signal.signal(numero, gestionnaire)

        self.addCleanup(remettre)
        self.origine = origine

    @staticmethod
    def laisser_passer():
        # Le gestionnaire Python s'exécute entre deux instructions.
        for _ in range(1000):
            pass

    def test_sigterm_devient_interruption(self):
        s = um.Systeme()
        restaurer = s.proteger_signaux()
        try:
            with self.assertRaises(um.Interruption):
                os.kill(os.getpid(), signal.SIGTERM)
                self.laisser_passer()
        finally:
            restaurer()
        self.assertIs(
            signal.getsignal(signal.SIGTERM), self.origine[signal.SIGTERM]
        )

    def test_ctrl_c_arme_leve_keyboardinterrupt(self):
        s = um.Systeme()
        restaurer = s.proteger_signaux()
        try:
            with self.assertRaises(KeyboardInterrupt):
                os.kill(os.getpid(), signal.SIGINT)
                self.laisser_passer()
        finally:
            restaurer()

    def test_desarme_ne_leve_plus(self):
        s = um.Systeme()
        restaurer = s.proteger_signaux()
        try:
            s.arme = False
            for numero in self.SIGNAUX:
                os.kill(os.getpid(), numero)
                self.laisser_passer()
        finally:
            restaurer()

    def test_ignorer_interruptions_puis_restaurer(self):
        s = um.Systeme()
        restaurer = s.ignorer_interruptions()
        try:
            for numero in self.SIGNAUX:
                self.assertIs(signal.getsignal(numero), signal.SIG_IGN)
        finally:
            restaurer()
        for numero in self.SIGNAUX:
            self.assertIs(signal.getsignal(numero), self.origine[numero])

    def test_signal_au_debut_du_finally_ne_saute_pas_la_relance(self):
        """Un SIGTERM traité au tout début du `finally`, avant la pose des
        SIG_IGN, sur une mise à jour réussie : le désarmement l'ignore."""

        class Tardif(FauxSysteme):
            proteger_signaux = um.Systeme.proteger_signaux

            def ignorer_interruptions(self):
                os.kill(os.getpid(), signal.SIGTERM)
                TestSignauxReels.laisser_passer()
                return um.Systeme.ignorer_interruptions(self)

        systeme = self.systeme = Tardif(self.wd, self.verrous)
        self.assertEqual(self.lancer("--no-backup"), um.CODE_OK, self.sortie)
        self.assertEqual(systeme.etat, "active")

    def test_signaux_pendant_la_relance_ne_l_empechent_pas(self):
        """Gestionnaires réels : SIGTERM pendant `-u` interrompt, puis
        SIGTERM et SIGHUP pendant `systemctl start` n'empêchent rien."""

        class Signaux(FauxSysteme):
            proteger_signaux = um.Systeme.proteger_signaux
            ignorer_interruptions = um.Systeme.ignorer_interruptions

            def lanceur(self, argv, timeout=60):
                if argv[:2] == ["systemctl", "start"]:
                    for numero in (signal.SIGTERM, signal.SIGHUP):
                        os.kill(os.getpid(), numero)
                        TestSignauxReels.laisser_passer()
                return super().lanceur(argv, timeout)

            def lancer_long(self, argv, cwd, env, journal, delai):
                super().lancer_long(argv, cwd, env, journal, delai)
                os.kill(os.getpid(), signal.SIGTERM)
                TestSignauxReels.laisser_passer()
                return um.Issue(0, False, False)

        systeme = self.systeme = Signaux(self.wd, self.verrous)
        code = self.lancer("--no-backup")
        self.assertEqual(code, um.CODE_INTERROMPU, self.sortie)
        self.assertEqual(systeme.etat, "active")
        self.assertIn(
            "systemctl start -- erplibre_demo.service", systeme.appels
        )
        for numero in self.SIGNAUX:
            self.assertIs(signal.getsignal(numero), self.origine[numero])


class TestDossierDeBaseEnLien(Base):
    """`<backup-dest>/<base>` ou `<state-dir>/<base>` en lien symbolique :
    refus avant tout arrêt, rien écrit au bout du lien. update_module
    passe par `odoo_backup.dossiers_a_creer`, pas par `detecter`."""

    def verifier(self, dossier):
        cible = os.path.join(self.tmp, "cible_du_lien")
        os.makedirs(cible)
        os.symlink(cible, dossier)
        self.assertEqual(self.lancer(), um.CODE_REFUS, self.sortie)
        self.assertIn(
            um.t("{path} is a symbolic link: refused.").format(path=dossier),
            self.erreurs + self.sortie,
        )
        self.assertFalse(self.a_appele("systemctl stop"))
        self.assertFalse(self.a_appele("backup "))
        self.assertFalse(self.a_appele("odoo "))
        self.assertEqual(os.listdir(cible), [])

    def test_dossier_des_sauvegardes(self):
        self.verifier(os.path.join(self.dest, "demo_db"))

    def test_dossier_d_etat(self):
        self.verifier(os.path.join(self.etat, "demo_db"))


class TestGroupesMontres(unittest.TestCase):
    def test_limite(self):
        texte = "\n".join(
            f"2026-03-01 11:00:00,000 7 ERROR demo_db odoo.x: panne {chr(97 + i)}"
            for i in range(12)
        )
        args = mock.Mock(ignore_error=[])
        analyse = um.erreurs_du_journal(texte, args)
        flux = io.StringIO()
        um.montrer_groupes(
            report.Rapport(flux=flux, couleur=False), analyse, 10
        )
        self.assertEqual(flux.getvalue().count("[1x] odoo.x: panne"), 10)


class TestDossierInscriptible(unittest.TestCase):
    """Le droit d'écrire d'un AUTRE compte, lu sur le mode du dossier.

    Éprouvé avec le compte courant, le seul dont le test connaît les
    droits."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dossier = os.path.join(d.name, "image_db")
        os.mkdir(self.dossier)
        import pwd

        self.compte = pwd.getpwuid(os.getuid()).pw_name

    def test_proprietaire_avec_ecriture(self):
        os.chmod(self.dossier, 0o700)
        self.assertTrue(um.dossier_inscriptible(self.dossier, self.compte))

    def test_proprietaire_sans_ecriture(self):
        if os.getuid() == 0:
            self.skipTest("root écrit partout")
        os.chmod(self.dossier, 0o555)
        self.addCleanup(os.chmod, self.dossier, 0o700)
        self.assertFalse(um.dossier_inscriptible(self.dossier, self.compte))

    def test_absent_ou_compte_inconnu(self):
        self.assertFalse(
            um.dossier_inscriptible(
                os.path.join(self.dossier, "absent"), self.compte
            )
        )
        self.assertFalse(
            um.dossier_inscriptible(self.dossier, "compte_inexistant_demo")
        )


class TestCreerDossier(unittest.TestCase):
    """`Systeme.creer_dossier` : mkdir, puis chown à l'uid et au groupe
    principal du compte. chown et passwd sont simulés : le test ne
    demande pas root et ne vise aucun compte réel."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dossier = os.path.join(d.name, "image_db")
        self.compte = mock.Mock(pw_uid=4321, pw_gid=8765)

    def test_mkdir_puis_chown_au_compte(self):
        with (
            mock.patch.object(
                service.pwd, "getpwnam", return_value=self.compte
            ),
            mock.patch.object(service.os, "fchown") as fchown,
        ):
            um.Systeme(interactif=False).creer_dossier(
                self.dossier, "svc", 0o700
            )
        self.assertTrue(os.path.isdir(self.dossier))
        self.assertEqual(os.stat(self.dossier).st_mode & 0o777, 0o700)
        self.assertEqual(fchown.call_count, 1)
        self.assertEqual(fchown.call_args[0][1:], (4321, 8765))

    def remplacer_apres_mkdir(self, par):
        """Un os.mkdir qui, le dossier créé, met `par(chemin)` à sa place —
        ce que le compte propriétaire du parent ferait avant le chown."""
        vrai = os.mkdir

        def mkdir(chemin, mode=0o777):
            vrai(chemin, mode)
            os.rmdir(chemin)
            par(chemin)

        return mock.patch.object(service.os, "mkdir", mkdir)

    def test_nom_remplace_par_un_lien(self):
        victime = os.path.join(os.path.dirname(self.dossier), "victime")
        os.mkdir(victime)
        os.chmod(victime, 0o755)
        for appel in (
            lambda s: s.creer_dossier(self.dossier, "svc", 0o700),
            lambda s: s.mkdir(self.dossier, 0o700),
        ):
            with self.subTest(appel=appel):
                with (
                    mock.patch.object(
                        service.pwd, "getpwnam", return_value=self.compte
                    ),
                    mock.patch.object(service.os, "fchown") as fchown,
                    self.remplacer_apres_mkdir(
                        lambda c: os.symlink(victime, c)
                    ),
                ):
                    with self.assertRaises(OSError):
                        appel(um.Systeme(interactif=False))
                fchown.assert_not_called()
                self.assertEqual(os.stat(victime).st_mode & 0o777, 0o755)
                os.remove(self.dossier)

    def test_nom_remplace_par_le_dossier_d_un_autre_compte(self):
        with (
            mock.patch.object(
                service.pwd, "getpwnam", return_value=self.compte
            ),
            mock.patch.object(service.os, "fchown") as fchown,
            mock.patch.object(
                service.os, "geteuid", return_value=os.geteuid() + 1
            ),
        ):
            with self.assertRaises(OSError):
                um.Systeme(interactif=False).creer_dossier(self.dossier, "svc")
        fchown.assert_not_called()
        self.assertFalse(os.path.exists(self.dossier))

    def test_chown_en_echec_retire_le_dossier(self):
        with (
            mock.patch.object(
                service.pwd, "getpwnam", return_value=self.compte
            ),
            mock.patch.object(
                service.os, "fchown", side_effect=PermissionError("refus")
            ),
        ):
            with self.assertRaises(PermissionError):
                um.Systeme(interactif=False).creer_dossier(self.dossier, "svc")
        self.assertFalse(os.path.exists(self.dossier))

    def test_compte_inconnu_ne_cree_rien(self):
        with mock.patch.object(
            service.pwd, "getpwnam", side_effect=KeyError("x")
        ):
            with self.assertRaises(KeyError):
                um.Systeme(interactif=False).creer_dossier(self.dossier, "svc")
        self.assertFalse(os.path.exists(self.dossier))


class TestSansOptionBase(unittest.TestCase):
    """La base de l'unité retirée de sa ligne de commande, le reste
    recopié tel quel."""

    def test_toutes_les_formes(self):
        for options in (
            ["-d", "unit_db"],
            ["--database", "unit_db"],
            ["--database=unit_db"],
            ["-dunit_db"],
            ["-d", "a_db", "--database=b_db", "-dc_db"],
        ):
            with self.subTest(options=options):
                argv = ["/bin/bash", "run.sh", "-p", "8090"]
                argv += options + ["--log-level=info"]
                self.assertEqual(
                    um.sans_option_base(argv),
                    ["/bin/bash", "run.sh", "-p", "8090", "--log-level=info"],
                )

    def test_le_programme_et_les_autres_options_intacts(self):
        argv = ["-dprog", "-c", "x.conf", "--db-filter=^a$", "--dev=all"]
        self.assertEqual(um.sans_option_base(argv), argv)


class TestUneSeuleBase(Base):
    def test_un_seul_d_quelle_que_soit_la_forme_de_l_unite(self):
        for options in (
            "-d unit_db",
            "--database unit_db",
            "--database=unit_db",
            "-dunit_db",
        ):
            with self.subTest(options=options):
                self.systeme.proprietes["ExecStart"] = (
                    "{ path=/bin/bash ; argv[]=/bin/bash "
                    + os.path.join(self.wd, "run.sh")
                    + f" {options} -p 8090 ; ignore_errors=no }}"
                )
                self.assertEqual(
                    self.lancer("--db", "demo_db", "--no-backup"), um.CODE_OK
                )
                argv = self.systeme.vu["odoo"]["argv"]
                bases = [
                    a
                    for a in argv
                    if a in ("-d", "--database")
                    or a.startswith(("--database=", "-dunit"))
                ]
                self.assertEqual(bases, ["-d"])
                self.assertEqual(argv[argv.index("-d") + 1], "demo_db")
                self.assertIn("8090", argv)


def imbrications_pep701(source):
    """Positions des chaînes imbriquées dans une f-string avec le même
    guillemet — légal seulement depuis Python 3.12 (PEP 701)."""
    fautes = []
    pile = []
    debut_f = getattr(tokenize, "FSTRING_START", None)
    fin_f = getattr(tokenize, "FSTRING_END", None)
    if debut_f is None:
        return fautes
    for jeton in tokenize.generate_tokens(io.StringIO(source).readline):
        if jeton.type in (debut_f, tokenize.STRING):
            guillemet = jeton.string.lstrip("rRbBuUfF")
            if pile and any(guillemet.startswith(g) for g in pile):
                fautes.append(jeton.start)
            if jeton.type == debut_f:
                pile.append(guillemet)
        elif jeton.type == fin_f:
            pile.pop()
    return fautes


class TestPythonAncien(unittest.TestCase):
    """Le programme se lance aussi par le python3 d'un serveur : rien
    au-delà de Python 3.7."""

    FICHIERS = [
        os.path.join(RACINE, "script", "odoo", "update_module.py"),
        os.path.join(RACINE, "script", "lib_ops", "systemd.py"),
        os.path.join(RACINE, "script", "lib_ops", "odoo_instance.py"),
        os.path.join(RACINE, "script", "lib_ops", "lock.py"),
        os.path.join(RACINE, "script", "lib_ops", "report.py"),
        os.path.join(RACINE, "script", "lib_ops", "service.py"),
        os.path.join(RACINE, "script", "lib_ops", "postgres.py"),
        os.path.join(RACINE, "script", "lib_ops", "retention.py"),
        os.path.join(RACINE, "script", "database", "odoo_backup.py"),
        os.path.join(RACINE, "script", "systemd", "install_backup_timer.py"),
        os.path.join(RACINE, "script", "odoo", "log_check.py"),
        os.path.join(RACINE, "script", "odoo", "mail_retry.py"),
        os.path.join(RACINE, "script", "lib_ops", "journal.py"),
        os.path.join(RACINE, "script", "lib_ops", "mail_diagnostic.py"),
    ]

    # API absentes de Python 3.7 : la syntaxe passe le garde, l'appel
    # échoue à l'exécution.
    API_RECENTES = (
        "shlex.join",
        ".removeprefix(",
        ".removesuffix(",
        "fromisocalendar",
        "dirs_exist_ok",
        "math.dist(",
        "functools.cache(",
    )

    def lire(self, chemin):
        with open(chemin, encoding="utf-8") as f:
            return f.read()

    def test_syntaxe_37(self):
        import ast

        for chemin in self.FICHIERS:
            with self.subTest(fichier=os.path.basename(chemin)):
                ast.parse(self.lire(chemin), feature_version=(3, 7))

    def test_le_garde_37_voit_un_morse(self):
        import ast

        with self.assertRaises(SyntaxError):
            ast.parse("(x := 1)", feature_version=(3, 7))

    def test_aucune_imbrication_pep701(self):
        for chemin in self.FICHIERS:
            with self.subTest(fichier=os.path.basename(chemin)):
                self.assertEqual(imbrications_pep701(self.lire(chemin)), [])

    def test_le_garde_pep701_voit_une_imbrication(self):
        if not hasattr(tokenize, "FSTRING_START"):
            self.skipTest("tokenizer antérieur à 3.12")
        self.assertTrue(imbrications_pep701('x = f"{d["k"]}"\n'))
        self.assertEqual(imbrications_pep701("x = f\"{d['k']}\"\n"), [])
        self.assertEqual(imbrications_pep701('x = f"""{d["k"]}"""\n'), [])

    def test_aucune_api_posterieure_a_37(self):
        for chemin in self.FICHIERS:
            with self.subTest(fichier=os.path.basename(chemin)):
                source = self.lire(chemin)
                for api in self.API_RECENTES:
                    self.assertNotIn(api, source)

    def test_annotations_differees(self):
        for chemin in self.FICHIERS:
            with self.subTest(fichier=os.path.basename(chemin)):
                self.assertIn(
                    "from __future__ import annotations", self.lire(chemin)
                )

    def test_executable(self):
        for chemin in (
            self.FICHIERS[0],
            os.path.join(RACINE, "script", "database", "odoo_backup.py"),
            os.path.join(
                RACINE, "script", "systemd", "install_backup_timer.py"
            ),
            os.path.join(RACINE, "script", "odoo", "log_check.py"),
            os.path.join(RACINE, "script", "odoo", "mail_retry.py"),
        ):
            with self.subTest(fichier=os.path.basename(chemin)):
                self.assertTrue(os.access(chemin, os.X_OK))
                with open(chemin, "rb") as f:
                    self.assertEqual(f.read(2), b"#!")


if __name__ == "__main__":
    unittest.main()
