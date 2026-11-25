#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""script/systemd/install_backup_timer.py : unités écrites, refus, retrait.

Tout chemin écrit passe sous `--root`, un dossier temporaire. systemctl,
systemd-analyze, systemd-tmpfiles et `runuser … test` sont joués par
`FauxSysteme.lanceur`, qui note chaque appel ; passwd et group sont
remplacés. Aucun systemctl réel n'est lancé,
aucun fichier n'est écrit sous /etc.

Les profils de production se lisent dans un dossier temporaire
(`profil_isole`) : le vrai `private/production` n'est jamais touché.

Données inventées : base `demo_db`, compte `demo`, unité
`erplibre_demo.service`.
"""

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from unittest import mock  # noqa: E402

from script.lib_ops import report  # noqa: E402
from script.systemd import install_backup_timer as ibt  # noqa: E402

PROFILS = None


def de_profil(option, valeur):
    """La ligne qui montre une valeur venue du profil, dans la langue
    courante."""
    return ibt.t("{option} {value} (profile)").format(
        option=option, value=valeur
    )


def champ_base(base, origine):
    """Le motif de la seule ligne du champ Database qui porte `base
    (origine)`, ancré au début et à la fin de la ligne."""
    return re.compile(
        r"^  "
        + re.escape(ibt.t("Database"))
        + r" +"
        + re.escape(f"{base} ({origine})")
        + r"$",
        re.M,
    )


def setUpModule():
    global PROFILS
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from profil_isole import profil_isole

    PROFILS = profil_isole()


def ecrire(chemin, texte=""):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w") as f:
        f.write(texte)
    return chemin


class FauxSysteme(ibt.Systeme):
    def __init__(self, bac, racine):
        super().__init__(racine=racine)
        self.bac = bac
        self.appels = []
        self.euid_valeur = 0
        self.calendrier_code = 0
        self.chowns = []
        self.non_inscriptibles = set()
        # Code de `systemctl <verbe>` ; 0 sinon.
        self.codes_systemctl = {}
        self.tmpfiles_code = 0
        # Chemins que le compte ne peut pas lire ni exécuter (`runuser …
        # test`).
        self.inaccessibles = set()
        # Sortie de `systemctl list-units` ; None : réponse par défaut.
        self.liste_unites = None
        self.wd = os.path.join(bac, "odoo")
        self.proprietes = {
            "LoadState": "loaded",
            "User": "demo",
            "WorkingDirectory": self.wd,
            "ExecStart": (
                "{ path=/bin/bash ; argv[]=/bin/bash "
                + os.path.join(self.wd, "run.sh")
                + " -d demo_db ; ignore_errors=no }"
            ),
            "Environment": "",
        }

    def lanceur(self, argv, timeout=60):
        self.appels.append(" ".join(argv))
        if argv[:2] == ["systemctl", "list-units"] and self.liste_unites:
            return 0, self.liste_unites
        if argv[:2] == ["systemctl", "show"]:
            noms = [argv[i + 1] for i, a in enumerate(argv) if a == "-p"]
            if argv[-1] != "erplibre_demo.service":
                return 0, "LoadState=not-found\n"
            return 0, "".join(
                f"{n}={self.proprietes.get(n, '')}\n" for n in noms
            )
        if argv[:2] == ["systemd-analyze", "calendar"]:
            return self.calendrier_code, ""
        if argv[0] == "systemd-tmpfiles":
            return self.tmpfiles_code, "" if not self.tmpfiles_code else "err"
        if argv[0] == "runuser" and argv[4] == "test":
            return (1 if argv[-1] in self.inaccessibles else 0), ""
        if argv[0] == "systemctl":
            return self.codes_systemctl.get(argv[1], 0), "échec simulé"
        return 1, "inattendu"

    def euid(self):
        return self.euid_valeur

    def utilisateur_courant(self):
        return "root"

    def home(self, utilisateur):
        return os.path.join(self.bac, "home_" + utilisateur)

    def groupe(self, utilisateur):
        return utilisateur

    def inscriptible(self, dossier, utilisateur):
        return dossier not in self.non_inscriptibles

    def _dans_le_bac(self, chemin):
        if not os.path.abspath(chemin).startswith(self.bac + os.sep):
            raise AssertionError(f"écriture hors du test : {chemin}")

    def creer_dossier(self, dossier, utilisateur, mode=0o750):
        self._dans_le_bac(dossier)
        os.mkdir(dossier, mode)
        os.chmod(dossier, mode)
        self.chowns.append((dossier, utilisateur))

    def mkdir(self, dossier, mode):
        self._dans_le_bac(dossier)
        os.mkdir(dossier, mode)
        os.chmod(dossier, mode)


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.bac = os.path.realpath(d.name)
        self.racine = os.path.join(self.bac, "racine")
        self.unites = os.path.join(self.racine, "etc", "systemd", "system")
        os.makedirs(self.unites)
        self.systeme = FauxSysteme(self.bac, self.racine)
        wd = self.systeme.wd
        ecrire(os.path.join(wd, "run.sh"), "#!/bin/bash\n")
        ecrire(os.path.join(wd, "config.conf"), "[options]\n")
        ecrire(os.path.join(wd, ibt.OUTIL), "")
        ecrire(os.path.join(wd, ".venv.erplibre", "bin", "python"), "")
        self.service = os.path.join(
            self.unites, "erplibre-backup-demo_db.service"
        )
        self.minuterie = os.path.join(
            self.unites, "erplibre-backup-demo_db.timer"
        )
        self.tmpfiles = os.path.join(
            self.racine, "etc", "tmpfiles.d", "erplibre-backup-demo_db.conf"
        )
        self.dest = "/srv/sauve garde%x$y"
        self.etat = "/srv/etat"

    def lancer(self, *options):
        argv = ["--service", "erplibre_demo", "--root", self.racine]
        argv += ["--dest", self.dest, "--state-dir", self.etat] + list(options)
        sortie, erreurs = io.StringIO(), io.StringIO()
        rapport = report.Rapport(flux=sortie, erreurs=erreurs, couleur=False)
        with (
            contextlib.redirect_stdout(sortie),
            contextlib.redirect_stderr(erreurs),
        ):
            code = ibt.main(argv, self.systeme, rapport)
        self.sortie, self.erreurs = sortie.getvalue(), erreurs.getvalue()
        return code

    def a_appele(self, debut):
        return any(a.startswith(debut) for a in self.systeme.appels)

    def lire(self, chemin):
        with open(chemin) as f:
            return f.read()


class TestInstallation(Base):
    def test_i1_simulation_n_ecrit_rien(self):
        self.assertEqual(self.lancer("--dry-run"), ibt.CODE_OK, self.erreurs)
        self.assertEqual(os.listdir(self.unites), [])
        self.assertIn("[Timer]", self.sortie)
        self.assertIn("[Service]", self.sortie)
        self.assertIn(ibt.MARQUE, self.sortie)
        for interdit in ("systemctl daemon-reload", "systemctl enable"):
            self.assertFalse(self.a_appele(interdit), interdit)
        self.assertFalse(os.path.exists(os.path.join(self.racine, "srv")))

    def test_simulation_sans_root(self):
        self.systeme.euid_valeur = 1000
        self.assertEqual(self.lancer("--dry-run"), ibt.CODE_OK)

    def test_i2_installation(self):
        self.assertEqual(
            self.lancer(), ibt.CODE_OK, self.erreurs + self.sortie
        )
        service = self.lire(self.service)
        minuterie = self.lire(self.minuterie)
        for texte in (service, minuterie):
            self.assertEqual(texte.splitlines()[0], ibt.MARQUE)
        self.assertIn("\nUser=demo\n", service)
        self.assertIn("\nGroup=demo\n", service)
        self.assertIn("\nType=oneshot\n", service)
        execstart = [
            ligne
            for ligne in service.splitlines()
            if ligne.startswith("ExecStart=")
        ][0]
        wd = self.systeme.wd
        self.assertTrue(
            execstart.startswith(
                "ExecStart="
                + os.path.join(wd, ".venv.erplibre", "bin", "python")
                + " "
                + os.path.join(wd, ibt.OUTIL)
                + " --service erplibre_demo.service --db demo_db"
            ),
            execstart,
        )
        self.assertIn('--dest "/srv/sauve garde%%x$$y"', execstart)
        self.assertIn("--state-dir /srv/etat", execstart)
        self.assertIn("--keep-daily 7", execstart)
        self.assertIn("\nOnCalendar=*-*-* 03:00:00\n", minuterie)
        self.assertIn("\nRandomizedDelaySec=30min\n", minuterie)
        self.assertIn("\nPersistent=true\n", minuterie)
        self.assertIn("\nUnit=erplibre-backup-demo_db.service\n", minuterie)
        self.assertEqual(os.stat(self.service).st_mode & 0o777, 0o644)
        appels = self.systeme.appels
        recharge = appels.index("systemctl daemon-reload")
        active = appels.index(
            "systemctl enable --now erplibre-backup-demo_db.timer"
        )
        self.assertLess(recharge, active)
        donnes = [c for c, u in self.systeme.chowns if u == "demo"]
        self.assertEqual(
            sorted(donnes),
            sorted(
                [
                    os.path.join(self.racine, "srv", "etat", "demo_db"),
                    os.path.join(
                        self.racine, "srv", "sauve garde%x$y", "demo_db"
                    ),
                ]
            ),
        )
        mode = os.stat(
            os.path.join(self.racine, "srv", "sauve garde%x$y", "demo_db")
        ).st_mode
        self.assertEqual(mode & 0o777, 0o700)

    def test_reinstaller_remplace_une_unite_marquee(self):
        self.assertEqual(self.lancer(), ibt.CODE_OK)
        self.assertEqual(
            self.lancer(
                "--on-calendar",
                "*-*-* 04:30:00",
                "--copy-to",
                "backup@backup.example.org:/srv/backups",
            ),
            ibt.CODE_OK,
            self.erreurs,
        )
        self.assertIn("04:30:00", self.lire(self.minuterie))
        self.assertIn(
            "--copy-to backup@backup.example.org:/srv/backups",
            self.lire(self.service),
        )

    def test_i3_unite_etrangere_refusee(self):
        ecrire(self.minuterie, "[Timer]\nOnCalendar=daily\n")
        self.assertEqual(self.lancer(), ibt.CODE_REFUS)
        self.assertEqual(
            self.lire(self.minuterie), "[Timer]\nOnCalendar=daily\n"
        )
        self.assertFalse(os.path.exists(self.service))
        self.assertFalse(self.a_appele("systemctl daemon-reload"))
        self.assertEqual(self.lancer("--uninstall"), ibt.CODE_REFUS)
        self.assertTrue(os.path.exists(self.minuterie))
        self.assertFalse(self.a_appele("systemctl disable"))

    def test_i4_retrait(self):
        self.assertEqual(self.lancer(), ibt.CODE_OK)
        sauvegardes = os.path.join(
            self.racine, "srv", "sauve garde%x$y", "demo_db"
        )
        ecrire(os.path.join(sauvegardes, "demo_db_2031-03-01_03h00m00s.zip"))
        self.systeme.appels.clear()
        self.assertEqual(self.lancer("--uninstall"), ibt.CODE_OK, self.erreurs)
        self.assertEqual(
            [
                a
                for a in self.systeme.appels
                if a.startswith("systemctl ")
                and not a.startswith("systemctl show")
            ],
            [
                "systemctl disable --now erplibre-backup-demo_db.timer",
                "systemctl stop erplibre-backup-demo_db.service",
                "systemctl daemon-reload",
            ],
        )
        self.assertEqual(os.listdir(self.unites), [])
        self.assertEqual(len(os.listdir(sauvegardes)), 1)
        self.assertEqual(self.lancer("--uninstall"), ibt.CODE_OK)

    def test_retrait_par_la_base_seule(self):
        self.assertEqual(self.lancer(), ibt.CODE_OK)
        self.systeme.appels.clear()
        argv = ["--uninstall", "--db", "demo_db", "--root", self.racine]
        rapport = report.Rapport(flux=io.StringIO(), erreurs=io.StringIO())
        self.assertEqual(ibt.main(argv, self.systeme, rapport), ibt.CODE_OK)
        self.assertFalse(self.a_appele("systemctl show"))
        self.assertEqual(os.listdir(self.unites), [])

    def test_i5_root_exige_et_calendrier_refuse(self):
        self.systeme.euid_valeur = 1000
        self.assertEqual(self.lancer(), ibt.CODE_REFUS)
        self.systeme.euid_valeur = 0
        self.systeme.calendrier_code = 1
        self.assertEqual(
            self.lancer("--on-calendar", "jamais"), ibt.CODE_REFUS
        )
        self.assertEqual(os.listdir(self.unites), [])
        self.systeme.calendrier_code = 0
        # Une forme invalide est refusée par le type argparse, code 2.
        for options in (
            ("--on-calendar", "daily\nExecStartPre=/bin/x"),
            ("--randomized-delay", "1h;x"),
        ):
            with self.subTest(options=options):
                with self.assertRaises(SystemExit) as refus:
                    self.lancer(*options)
                self.assertEqual(refus.exception.code, ibt.CODE_REFUS)
        self.assertEqual(os.listdir(self.unites), [])

    def test_dossier_existant_non_inscriptible(self):
        propre = os.path.join(self.racine, "srv", "etat", "demo_db")
        os.makedirs(propre)
        self.systeme.non_inscriptibles.add(propre)
        self.assertEqual(self.lancer(), ibt.CODE_REFUS)
        self.assertEqual(os.listdir(self.unites), [])

    def test_i6_ancienne_minuterie(self):
        ecrire(os.path.join(self.unites, "odoo-backup.timer"), "[Timer]\n")
        self.assertEqual(self.lancer("--dry-run"), ibt.CODE_OK)
        self.assertIn("odoo-backup.timer", self.sortie)
        self.assertIn("[ATTN]", self.sortie)

    def test_checkout_de_repli(self):
        os.remove(os.path.join(self.systeme.wd, ibt.OUTIL))
        self.assertEqual(self.lancer("--dry-run"), ibt.CODE_OK)
        self.assertIn(os.path.join(ibt.RACINE, ibt.OUTIL), self.sortie)
        self.assertIn("[ATTN]", self.sortie)


class TestUniteComplete(Base):
    """Chaque ligne du service qui le fait marcher est vérifiée."""

    def execstart(self):
        service = self.lire(self.service)
        ligne = [
            ligne
            for ligne in service.splitlines()
            if ligne.startswith("ExecStart=")
        ][0]
        return ligne[len("ExecStart=") :]

    def test_execstart_complet_et_dossier_de_travail(self):
        self.assertEqual(self.lancer(), ibt.CODE_OK, self.erreurs)
        wd = self.systeme.wd
        self.assertEqual(
            self.execstart(),
            " ".join(
                [
                    os.path.join(wd, ".venv.erplibre", "bin", "python"),
                    os.path.join(wd, ibt.OUTIL),
                    "--service erplibre_demo.service --db demo_db",
                    "--odoo-conf",
                    os.path.join(wd, "config.conf"),
                    "--user demo",
                    '--dest "/srv/sauve garde%%x$$y"',
                    "--state-dir /srv/etat",
                    "--keep-daily 7 --keep-weekly 4 --keep-monthly 12",
                    "--keep-recent-days 2",
                ]
            ),
        )
        self.assertIn(f"\nWorkingDirectory={wd}\n", self.lire(self.service))
        etat = os.path.join(self.racine, "srv", "etat", "demo_db")
        self.assertEqual(os.stat(etat).st_mode & 0o777, 0o755)
        commun = os.path.join(self.racine, "srv", "etat")
        self.assertEqual(os.stat(commun).st_mode & 0o777, 0o755)

    def test_outil_qui_lit_le_profil_recoit_no_profile(self):
        """Un outil qui applique le profil reçoit `--no-profile` en fin
        d'ExecStart : toutes les valeurs y sont écrites, la sauvegarde
        planifiée ne découvre aucun profil par `--service`. Un outil
        antérieur (le faux outil vide) ne le reçoit pas."""
        self.assertEqual(self.lancer(), ibt.CODE_OK, self.erreurs)
        self.assertNotIn("--no-profile", self.execstart())
        ecrire(
            os.path.join(self.systeme.wd, ibt.OUTIL),
            "args = profil.analyser(parser, argv)\n",
        )
        self.assertEqual(self.lancer(), ibt.CODE_OK, self.erreurs)
        self.assertTrue(
            self.execstart().endswith(" --keep-recent-days 2 --no-profile"),
            self.execstart(),
        )
        # L'outil réel de ce checkout applique le profil.
        self.assertTrue(ibt.outil_lit_le_profil(ibt.RACINE))
        self.assertFalse(
            ibt.outil_lit_le_profil(os.path.join(self.bac, "absent"))
        )

    def test_sans_venv_python_du_systeme(self):
        os.remove(
            os.path.join(self.systeme.wd, ".venv.erplibre", "bin", "python")
        )
        repli = os.path.join(self.bac, "repli")
        os.makedirs(repli)
        with mock.patch.object(ibt, "RACINE", repli):
            self.assertEqual(self.lancer(), ibt.CODE_OK, self.erreurs)
        self.assertTrue(
            self.execstart().startswith(
                ibt.PYTHON_SYSTEME
                + " "
                + os.path.join(self.systeme.wd, ibt.OUTIL)
                + " "
            ),
            self.execstart(),
        )


class TestEchecsDeSystemctl(Base):
    def test_daemon_reload_en_echec(self):
        self.systeme.codes_systemctl["daemon-reload"] = 1
        self.assertEqual(self.lancer(), ibt.CODE_ECHEC)
        self.assertTrue(os.path.exists(self.service))
        self.assertTrue(os.path.exists(self.minuterie))
        self.assertFalse(self.a_appele("systemctl enable"))

    def test_enable_en_echec(self):
        self.systeme.codes_systemctl["enable"] = 1
        self.assertEqual(self.lancer(), ibt.CODE_ECHEC)
        self.assertTrue(os.path.exists(self.service))
        self.assertIn("échec simulé", self.sortie)

    def test_retrait_disable_en_echec_retire_quand_meme(self):
        self.assertEqual(self.lancer(), ibt.CODE_OK)
        self.systeme.codes_systemctl["disable"] = 1
        self.systeme.appels.clear()
        self.assertEqual(self.lancer("--uninstall"), ibt.CODE_ECHEC)
        self.assertEqual(os.listdir(self.unites), [])
        self.assertFalse(os.path.exists(self.tmpfiles))
        self.assertTrue(self.a_appele("systemctl daemon-reload"))


class TestVerrouEtAcces(Base):
    """Le fichier du verrou partagé, créé par tmpfiles.d, et l'accès du
    compte à ce que le service lancera."""

    def test_tmpfiles_ecrit_puis_cree(self):
        self.assertEqual(self.lancer(), ibt.CODE_OK, self.erreurs)
        lignes = self.lire(self.tmpfiles).splitlines()
        self.assertEqual(
            lignes,
            [
                ibt.MARQUE,
                "f /run/lock/erplibre-db-demo_db.lock 0644 root root -",
            ],
        )
        appels = self.systeme.appels
        creation = appels.index(
            f"systemd-tmpfiles --create -- {self.tmpfiles}"
        )
        self.assertLess(creation, appels.index("systemctl daemon-reload"))

    def test_tmpfiles_en_echec(self):
        self.systeme.tmpfiles_code = 1
        self.assertEqual(self.lancer(), ibt.CODE_ECHEC)
        self.assertFalse(self.a_appele("systemctl enable"))

    def test_tmpfiles_etranger_refuse(self):
        ecrire(self.tmpfiles, "f /run/lock/autre 0644 root root -\n")
        self.assertEqual(self.lancer(), ibt.CODE_REFUS)
        self.assertEqual(os.listdir(self.unites), [])
        self.assertEqual(self.lancer("--uninstall"), ibt.CODE_REFUS)
        self.assertTrue(os.path.exists(self.tmpfiles))

    def test_simulation_montre_tmpfiles(self):
        self.assertEqual(self.lancer("--dry-run"), ibt.CODE_OK)
        self.assertIn("erplibre-db-demo_db.lock 0644 root root", self.sortie)
        self.assertIn("systemd-tmpfiles --create", self.sortie)
        self.assertFalse(os.path.exists(self.tmpfiles))

    def test_acces_verifie_sous_le_compte(self):
        self.assertEqual(self.lancer(), ibt.CODE_OK, self.erreurs)
        wd = self.systeme.wd
        for attendu in (
            "runuser -u demo -- test -x "
            + os.path.join(wd, ".venv.erplibre", "bin", "python"),
            "runuser -u demo -- test -r " + os.path.join(wd, ibt.OUTIL),
            "runuser -u demo -- test -r " + os.path.join(wd, "config.conf"),
        ):
            self.assertIn(attendu, self.systeme.appels)

    def test_acces_refuse_rien_n_est_ecrit(self):
        for chemin in (
            os.path.join(self.systeme.wd, ".venv.erplibre", "bin", "python"),
            os.path.join(self.systeme.wd, ibt.OUTIL),
            os.path.join(self.systeme.wd, "config.conf"),
        ):
            with self.subTest(chemin=chemin):
                self.systeme.inaccessibles = {chemin}
                self.assertEqual(self.lancer(), ibt.CODE_REFUS)
                self.assertIn(chemin, self.erreurs)
                self.assertEqual(os.listdir(self.unites), [])
                self.assertFalse(
                    os.path.exists(os.path.join(self.racine, "srv"))
                )

    def test_simulation_sans_root_ne_verifie_pas_l_acces(self):
        self.systeme.euid_valeur = 1000
        self.assertEqual(self.lancer("--dry-run"), ibt.CODE_OK)
        self.assertFalse(self.a_appele("runuser"))
        self.assertIn("[ATTN]", self.sortie)


class TestTypes(unittest.TestCase):
    """Types argparse de `--on-calendar` et `--randomized-delay`."""

    def test_calendrier(self):
        for valeur in ("*-*-* 03:00:00", "daily", "Mon..Fri 02:30"):
            self.assertEqual(ibt.type_calendrier(valeur), valeur)
        for valeur in ("", "daily;x", "daily\nExecStartPre=/bin/x", "$x"):
            with self.subTest(valeur=valeur):
                with self.assertRaises(ibt.argparse.ArgumentTypeError) as err:
                    ibt.type_calendrier(valeur)
                self.assertNotIn("\n", str(err.exception))

    def test_delai(self):
        for valeur in ("30min", "1h 30min", "0", "90"):
            self.assertEqual(ibt.type_delai(valeur), valeur)
        for valeur in ("", "1h;x", "min", "5m\n"):
            with self.subTest(valeur=valeur):
                with self.assertRaises(ibt.argparse.ArgumentTypeError):
                    ibt.type_delai(valeur)

    def test_defauts_acceptes(self):
        args = ibt.analyser(["--dry-run", "--no-profile"])
        self.assertEqual(args.on_calendar, ibt.CALENDRIER)
        self.assertEqual(args.randomized_delay, ibt.DELAI_ALEATOIRE)


class TestProfil(Base):
    """Profil de production `erplibre_demo.service.json`, trouvé par
    `--service` dans le dossier temporaire des profils, ou nommé par
    `--profile`."""

    def setUp(self):
        super().setUp()
        self.profil = os.path.join(PROFILS, "erplibre_demo.service.json")
        self.addCleanup(self._retirer)

    def _retirer(self):
        if os.path.lexists(self.profil):
            os.remove(self.profil)

    def poser(self, **groupes):
        doc = {"version": 1, "service": "erplibre_demo.service"}
        doc.update(groupes)
        with open(self.profil, "w", encoding="utf-8") as fichier:
            json.dump(doc, fichier)
        os.chmod(self.profil, 0o644)
        return self.profil

    def refus(self, *argv):
        """Le code de sortie et stderr d'une analyse refusée."""
        erreurs = io.StringIO()
        with contextlib.redirect_stderr(erreurs):
            with self.assertRaises(SystemExit) as sortie:
                ibt.analyser(list(argv))
        return sortie.exception.code, erreurs.getvalue()

    def test_valeurs_du_profil_appliquees_et_affichees(self):
        self.poser(
            backup={
                "keep_daily": 10,
                "copy_to": "sauvegarde@backup.example.org:/srv/hors-site",
            },
            backup_timer={
                "on_calendar": "*-*-* 02:30:00",
                "randomized_delay": "10min",
            },
        )
        self.assertEqual(self.lancer("--dry-run"), ibt.CODE_OK, self.erreurs)
        self.assertIn(self.profil, self.sortie)
        for ligne in (
            de_profil("--keep-daily", "10"),
            de_profil("--on-calendar", "*-*-* 02:30:00"),
            de_profil("--randomized-delay", "10min"),
            de_profil(
                "--copy-to", "sauvegarde@backup.example.org:/srv/hors-site"
            ),
            "OnCalendar=*-*-* 02:30:00",
            "RandomizedDelaySec=10min",
            "--keep-daily 10 --keep-weekly 4",
            "--copy-to sauvegarde@backup.example.org:/srv/hors-site",
        ):
            self.assertIn(ligne, self.sortie)
        # Les valeurs du profil précèdent les unités et les commandes.
        self.assertLess(
            self.sortie.index(de_profil("--keep-daily", "10")),
            self.sortie.index("[Timer]"),
        )
        self.assertEqual(os.listdir(self.unites), [])

    def test_installation_ecrit_les_valeurs_du_profil(self):
        self.poser(
            backup={"keep_weekly": 8},
            backup_timer={"on_calendar": "*-*-* 01:15:00"},
        )
        self.assertEqual(self.lancer(), ibt.CODE_OK, self.erreurs)
        self.assertIn("--keep-weekly 8", self.lire(self.service))
        self.assertIn(
            "\nOnCalendar=*-*-* 01:15:00\n", self.lire(self.minuterie)
        )

    def test_la_ligne_de_commande_gagne(self):
        self.poser(
            backup={"keep_daily": 10, "dest": "/srv/profil"},
            backup_timer={"on_calendar": "*-*-* 02:30:00"},
        )
        self.assertEqual(
            self.lancer("--dry-run", "--keep-daily", "3"),
            ibt.CODE_OK,
            self.erreurs,
        )
        self.assertIn("--keep-daily 3 --keep-weekly", self.sortie)
        self.assertNotIn("--keep-daily 10", self.sortie)
        self.assertNotIn("/srv/profil", self.sortie.replace(self.profil, ""))
        self.assertIn(
            de_profil("--on-calendar", "*-*-* 02:30:00"), self.sortie
        )
        self.assertIn(
            ibt.t("{option}: the command line wins over the profile").format(
                option="--keep-daily"
            ),
            self.sortie,
        )
        args = ibt.analyser(
            ["--service", "erplibre_demo", "--keep-daily", "3"]
        )
        self.assertEqual(args.keep_daily, 3)
        self.assertEqual(args.profil.origine("keep_daily"), "cli")
        self.assertEqual(args.profil.origine("on_calendar"), "profil")
        self.assertEqual(args.profil.origine("keep_weekly"), "defaut")

    def test_options_exclues_ignorees(self):
        self.poser(
            backup_timer={
                "uninstall": True,
                "dry_run": True,
                "root": "/srv/ailleurs",
                "user": "autre",
                "service": "odoo-exemple.service",
                "keep_daily": 10,
                "db": "exemple_db",
            }
        )
        args = ibt.analyser(["--service", "erplibre_demo"])
        self.assertFalse(args.uninstall)
        self.assertFalse(args.dry_run)
        self.assertEqual(args.root, "/")
        self.assertIsNone(args.user)
        self.assertEqual(args.service, "erplibre_demo.service")
        # Une `dest` aliasée n'est pas une clé de son propre groupe.
        self.assertEqual(args.keep_daily, 7)
        self.assertIsNone(args.db)
        self.assertEqual(
            sorted(e.dest for e in args.profil.ecartees),
            ["dry_run", "root", "service", "uninstall", "user"],
        )
        self.assertEqual(
            sorted(args.profil.inconnues),
            ["backup_timer.db", "backup_timer.keep_daily"],
        )
        self.assertEqual(self.lancer("--dry-run"), ibt.CODE_OK, self.erreurs)
        self.assertIn(
            ibt.t("unknown key {key}, ignored").format(key="backup_timer.db"),
            self.sortie,
        )
        self.assertIn("[ATTN]", self.sortie)
        self.assertFalse(self.a_appele("systemctl disable"))

    def test_base_du_profil(self):
        self.poser(instance={"db": "demo_db"})
        self.assertEqual(self.lancer("--dry-run"), ibt.CODE_OK, self.erreurs)
        # Le champ Database lui-même, ancré : la ligne de détail
        # `--db demo_db (profile)` ne le satisfait pas.
        self.assertRegex(self.sortie, champ_base("demo_db", ibt.t("profile")))
        self.assertIn(de_profil("--db", "demo_db"), self.sortie)
        self.assertEqual(
            self.lancer("--dry-run", "--db", "demo_db"),
            ibt.CODE_OK,
            self.erreurs,
        )
        self.assertRegex(self.sortie, champ_base("demo_db", "--db"))

    def test_sans_profil(self):
        self.poser(backup={"keep_daily": 10})
        self.assertEqual(
            self.lancer("--dry-run", "--no-profile"), ibt.CODE_OK, self.erreurs
        )
        self.assertNotIn(self.profil, self.sortie)
        self.assertNotIn(de_profil("--keep-daily", "10"), self.sortie)
        self.assertIn("--keep-daily 7", self.sortie)
        args = ibt.analyser(["--service", "erplibre_demo", "--no-profile"])
        self.assertFalse(args.profil.actif)
        self.assertEqual(args.profil.origine("keep_daily"), "defaut")

    def test_profile_unset(self):
        self.poser(backup={"keep_daily": 10, "keep_weekly": 8})
        args = ibt.analyser(
            ["--service", "erplibre_demo", "--profile-unset", "keep-daily"]
        )
        self.assertEqual(args.keep_daily, 7)
        self.assertEqual(args.keep_weekly, 8)

    def test_profil_explicite_nomme_le_service(self):
        # Le nom du fichier est celui du service qu'il porte.
        ailleurs = os.path.join(
            self.bac, "ailleurs", "erplibre_demo.service.json"
        )
        os.makedirs(os.path.dirname(ailleurs))
        with open(ailleurs, "w", encoding="utf-8") as fichier:
            json.dump(
                {
                    "version": 1,
                    "service": "erplibre_demo.service",
                    "backup": {"dest": "/srv/profil", "keep_daily": 5},
                },
                fichier,
            )
        argv = ["--profile", ailleurs, "--root", self.racine, "--dry-run"]
        rapport = report.Rapport(
            flux=io.StringIO(), erreurs=io.StringIO(), couleur=False
        )
        with contextlib.redirect_stdout(rapport.flux):
            code = ibt.main(argv, self.systeme, rapport)
        sortie = rapport.flux.getvalue()
        self.assertEqual(code, ibt.CODE_OK, sortie)
        self.assertIn("--service erplibre_demo.service --db demo_db", sortie)
        self.assertIn("--dest /srv/profil", sortie)
        self.assertIn("--keep-daily 5 --keep-weekly", sortie)
        self.assertFalse(self.a_appele("systemctl list-units"))

    def test_unite_devinee_une_seule_fois(self):
        self.systeme.liste_unites = (
            "erplibre_demo.service loaded active running Odoo\n"
        )
        self.poser(backup={"keep_daily": 6})
        argv = ["--root", self.racine, "--dry-run"]
        rapport = report.Rapport(
            flux=io.StringIO(), erreurs=io.StringIO(), couleur=False
        )
        with contextlib.redirect_stdout(rapport.flux):
            code = ibt.main(argv, self.systeme, rapport)
        sortie = rapport.flux.getvalue()
        self.assertEqual(code, ibt.CODE_OK, sortie)
        self.assertIn(de_profil("--keep-daily", "6"), sortie)
        listes = [
            a
            for a in self.systeme.appels
            if a.startswith("systemctl list-units")
        ]
        self.assertEqual(len(listes), 1)

    def test_analyser_seul_ne_devine_jamais(self):
        self.systeme.liste_unites = (
            "erplibre_demo.service loaded active running Odoo\n"
        )
        self.poser(backup={"keep_daily": 6})
        args = ibt.analyser(["--dry-run"])
        self.assertFalse(args.profil.actif)
        self.assertEqual(self.systeme.appels, [])

    def test_valeurs_invalides_du_profil_refusees(self):
        for groupes, cle in (
            ({"backup_timer": {"on_calendar": "daily;x"}}, "on_calendar"),
            (
                {"backup_timer": {"randomized_delay": "1h;x"}},
                "randomized_delay",
            ),
            (
                {"backup_timer": {"on_calendar": "daily\nExecStartPre=x"}},
                "on_calendar",
            ),
            ({"backup": {"dest": "relatif"}}, "dest"),
            ({"backup": {"keep_daily": 0}}, "keep_daily"),
            ({"backup": {"keep_daily": "sept"}}, "keep_daily"),
        ):
            with self.subTest(cle=cle, groupes=groupes):
                self.poser(**groupes)
                code, erreurs = self.refus("--service", "erplibre_demo")
                self.assertEqual(code, ibt.CODE_REFUS)
                self.assertIn(self.profil, erreurs)
                self.assertIn(cle, erreurs)
                self.assertNotIn("ExecStartPre", erreurs)

    def test_cli_valide_malgre_un_profil_en_conflit(self):
        # La ligne de commande remplace la valeur : le profil n'est même
        # pas converti pour elle.
        self.poser(backup={"keep_daily": 0})
        args = ibt.analyser(
            ["--service", "erplibre_demo", "--keep-daily", "0"]
        )
        self.assertEqual(args.keep_daily, 0)

    def test_retrait_par_la_base_du_profil(self):
        self.assertEqual(self.lancer(), ibt.CODE_OK, self.erreurs)
        self.poser(instance={"db": "demo_db"})
        self.systeme.appels.clear()
        self.assertEqual(
            self.lancer("--uninstall", "--profile", self.profil),
            ibt.CODE_OK,
            self.erreurs,
        )
        self.assertEqual(os.listdir(self.unites), [])
        self.assertIn(de_profil("--db", "demo_db"), self.sortie)


class TestCitation(unittest.TestCase):
    def test_citer(self):
        self.assertEqual(ibt.citer("simple"), "simple")
        self.assertEqual(ibt.citer("a%b$c"), "a%%b$$c")
        self.assertEqual(ibt.citer("deux mots"), '"deux mots"')
        self.assertEqual(ibt.citer('a"b'), '"a\\"b"')
        self.assertEqual(ibt.citer("a\\b"), '"a\\\\b"')
        self.assertEqual(ibt.citer(";"), '";"')
        self.assertEqual(ibt.citer(""), '""')
        with self.assertRaises(ValueError):
            ibt.citer("a\nb")


if __name__ == "__main__":
    unittest.main()
