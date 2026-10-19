#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Production : opérer une instance servie par systemd sur ce poste.

Ce mixin ne fait que poser les questions et lancer les outils qui portent
toute la logique : `script/odoo/update_module.py` (mise à jour),
`script/database/odoo_backup.py` (sauvegarde, état, restauration d'essai,
restauration dans une nouvelle base),
`script/systemd/install_backup_timer.py` (sauvegarde planifiée),
`script/odoo/log_check.py` (journal d'Odoo), `script/odoo/mail_retry.py`
(courriels en échec d'envoi), `script/odoo/health_check.py` (santé de
l'instance ou d'une URL publique), `script/odoo/warmup_http.py --deep`
(préchauffage du cache) et `script/proxmox/host_perf_audit.py` (audit de
performance de ce poste, en lecture seule). Le menu n'en duplique rien :
ce qui se fait depuis ici se fait aussi bien en ligne de commande.

Tout ce qui écrit passe par deux temps :

1. la simulation (`--dry-run`), lancée sous le compte courant, montre ce
   qui a été détecté et les commandes exactes ;
2. après confirmation seulement, l'exécution réelle sous `sudo`, par
   `subprocess.run` SANS capture : le terminal reste celui du programme,
   ce qui permet à sudo de demander son mot de passe et au programme de
   poser sa question quand on l'interrompt par Ctrl-C.

Une simulation qui refuse (code non nul) arrête là : il n'y a rien à
confirmer. L'état des sauvegardes, le journal d'Odoo, la liste des
courriels en échec, la santé de l'instance locale et le préchauffage, qui
n'écrivent rien dans l'instance, se lancent directement, sans
confirmation ni sudo ; quand le compte courant ne peut pas lire ce qu'il
faut (code 2), la même commande sous sudo est proposée. La santé d'une
URL publique ne lit rien sur ce poste : son code 2 est une URL refusée, et
sudo n'est jamais proposé.

L'audit de performance se lance sans sudo ni capture, avec un délai égal
à la durée demandée plus une marge ; le menu Proxmox réutilise les mêmes
méthodes pour l'envoyer à l'hôte retenu par ssh, le fichier sur stdin.

`log_check --since-last` retient sa position dans un dossier de root : le
menu propose sudo d'avance quand ce dossier n'est pas inscriptible, sinon
chaque lecture repartirait des dernières 24 h. Le renvoi des courriels
passe par sudo SANS capture : le menu de sélection de `mail_retry` a
besoin du terminal.
"""

import os
import shlex
import subprocess
import sys

import click

from script.todo.todo_i18n import t

# Le programme lancé, relatif à la racine du dépôt (le dossier courant de
# todo.py).
UPDATE_MODULE = os.path.join("script", "odoo", "update_module.py")
ODOO_BACKUP = os.path.join("script", "database", "odoo_backup.py")
INSTALL_BACKUP_TIMER = os.path.join(
    "script", "systemd", "install_backup_timer.py"
)
LOG_CHECK = os.path.join("script", "odoo", "log_check.py")
MAIL_RETRY = os.path.join("script", "odoo", "mail_retry.py")
HEALTH_CHECK = os.path.join("script", "odoo", "health_check.py")
WARMUP_HTTP = os.path.join("script", "odoo", "warmup_http.py")
# Le dossier d'état par défaut de log_check.py.
ETAT_LOG_CHECK = "/var/lib/erplibre-logcheck"
# L'audit de performance, en chemin absolu : il est ouvert pour être envoyé
# sur le stdin de ssh, et lancé tel quel en local.
HOST_PERF_AUDIT_RELATIF = os.path.join(
    "script", "proxmox", "host_perf_audit.py"
)
HOST_PERF_AUDIT = os.path.join(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ),
    HOST_PERF_AUDIT_RELATIF,
)
# Au-delà de la durée mesurée : les commandes lancées une fois (zpool, zfs,
# smartctl, chacune bornée à 20 s) et le rapport.
MARGE_AUDIT_S = 300
# Après un Ctrl-C, le temps laissé à l'audit local pour écrire son rapport.
ATTENTE_RAPPORT_S = 60


def joindre(argv):
    return " ".join(shlex.quote(a) for a in argv)


class OpsMenuMixin:
    """Menu Production. Voir l'en-tête du fichier pour sa frontière."""

    def prompt_execute_production(self):
        print(
            f"🏭 {t('Production: an instance run by systemd on this host.')}"
        )
        choices = [
            {
                "prompt_description": t(
                    "Update modules - simulate, confirm, then run with sudo"
                )
            },
            {
                "prompt_description": t(
                    "Simulate only - show what an update would do"
                )
            },
            {
                "prompt_description": t(
                    "Verified backup now - simulate, confirm, then run with"
                    " sudo"
                )
            },
            {
                "prompt_description": t(
                    "Backup status - age of the last successful backup"
                )
            },
            {
                "prompt_description": t(
                    "Test restore of the latest backup - temporary database,"
                    " dropped afterwards"
                )
            },
            {
                "prompt_description": t(
                    "Restore a backup into a new database - simulate,"
                    " confirm, then run with sudo"
                )
            },
            {
                "prompt_description": t(
                    "Install / remove the scheduled backup - systemd timer,"
                    " with sudo"
                )
            },
            {
                "prompt_description": t(
                    "Odoo journal: errors since the last check - read-only"
                )
            },
            {
                "prompt_description": t(
                    "Odoo journal: errors of the last N hours - read-only"
                )
            },
            {
                "prompt_description": t(
                    "Odoo journal: hourly report - errors per hour over N days"
                )
            },
            {
                "prompt_description": t(
                    "Failed outgoing mail: list - read-only, addresses masked"
                )
            },
            {
                "prompt_description": t(
                    "Failed outgoing mail: retry - confirm, then choose with"
                    " sudo"
                )
            },
            {
                "prompt_description": t(
                    "Health check of this instance (local) - read-only"
                )
            },
            {
                "prompt_description": t(
                    "Health check of a public URL - TLS, redirect, database"
                    " manager, optional mail DNS"
                )
            },
            {
                "prompt_description": t(
                    "Warm up the cache (deep) - public pages and asset bundles"
                )
            },
            {
                "prompt_description": t(
                    "Host performance audit of this machine - read-only"
                )
            },
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._ops_update_modules()
            elif status == "2":
                self._ops_simulate_modules()
            elif status == "3":
                self._ops_backup_now()
            elif status == "4":
                self._ops_backup_status()
            elif status == "5":
                self._ops_test_restore()
            elif status == "6":
                self._ops_restore_new_database()
            elif status == "7":
                self._ops_backup_timer()
            elif status == "8":
                self._ops_log_since_last()
            elif status == "9":
                self._ops_log_last_hours()
            elif status == "10":
                self._ops_log_hourly()
            elif status == "11":
                self._ops_mail_list()
            elif status == "12":
                self._ops_mail_retry()
            elif not self._ops_production_sante(status):
                print(t("Command not found !"))

    def _ops_production_sante(self, status):
        """Les entrées 13 à 16 du menu (santé, préchauffage, audit de
        performance) ; False pour un autre choix. À part pour borner la
        taille du dispatch."""
        if status == "13":
            self._ops_health_local()
        elif status == "14":
            self._ops_health_url()
        elif status == "15":
            self._ops_warmup_deep()
        elif status == "16":
            self._ops_perf_audit()
        else:
            return False
        return True

    def _ops_update_arguments(self):
        """Les arguments d'update_module.py tirés des réponses, ou None.

        Modules exigés ; base vide = celle que le programme détecte ;
        sauvegarde par défaut. Les valeurs sont transmises telles quelles :
        update_module.py les valide et refuse avant d'arrêter quoi que ce
        soit.
        """
        modules = input(
            t("Modules to update (commas, * and ? patterns, or all): ")
        ).strip()
        if not modules:
            print(t("Cancelled: no module given."))
            return None
        base = input(t("Database (empty = detect from the service): ")).strip()
        sauvegarde = self._is_yes_default_yes(
            input(t("Back up the database before the update? [Y/n] "))
        )
        args = ["--module", modules]
        if base:
            args += ["--db", base]
        if not sauvegarde:
            args.append("--no-backup")
        return args

    def _ops_simulate_modules(self):
        """La simulation seule : jamais d'exécution réelle ni de sudo.

        Méthode distincte de `_ops_update_modules` pour que la table des
        méta-tests distingue les deux entrées par leur nom.
        """
        self._ops_update_modules(simulation_seule=True)

    def _ops_update_modules(self, simulation_seule=False):
        """Simulation, puis, sur confirmation, exécution réelle sous sudo."""
        args = self._ops_update_arguments()
        if args is None:
            return
        commande = [sys.executable, UPDATE_MODULE] + args
        simulation = " ".join(shlex.quote(a) for a in commande + ["--dry-run"])
        print(f"\n{t('Will execute:')} {simulation}")
        status = self.execute.exec_command_live(
            simulation, source_erplibre=False
        )
        if status != 0:
            print(f"  ✗ {t('The simulation refused: nothing was done.')}")
            return
        if simulation_seule:
            return
        if not click.confirm(
            t("Run this update for real? The service stops meanwhile.")
        ):
            return
        reelle = ["sudo"] + commande
        affichee = " ".join(shlex.quote(a) for a in reelle)
        print(f"\n{t('Will execute:')} {affichee}")
        fin = subprocess.run(reelle)
        if fin.returncode != 0:
            print(f"  ✗ {t('The update ended with code')} {fin.returncode}")

    def _ops_lancer(self, script, args, question):
        """Simulation (`--dry-run`), confirmation, puis exécution réelle
        sous sudo, sans capture. Rend True si l'exécution réelle a été
        lancée. Les valeurs saisies sont transmises telles quelles : l'outil
        les valide et refuse avant d'agir."""
        commande = [sys.executable, script] + args
        simulation = joindre(commande + ["--dry-run"])
        print(f"\n{t('Will execute:')} {simulation}")
        status = self.execute.exec_command_live(
            simulation, source_erplibre=False
        )
        if status != 0:
            print(f"  ✗ {t('The simulation refused: nothing was done.')}")
            return False
        if not click.confirm(question):
            return False
        reelle = ["sudo"] + commande
        print(f"\n{t('Will execute:')} {joindre(reelle)}")
        fin = subprocess.run(reelle)
        if fin.returncode != 0:
            print(f"  ✗ {t('The command ended with code')} {fin.returncode}")
        return True

    def _ops_base(self):
        """`--db BASE`, ou rien pour la base que l'outil détecte."""
        base = input(t("Database (empty = detect from the service): ")).strip()
        return ["--db", base] if base else []

    def _ops_backup_now(self):
        self._ops_lancer(
            ODOO_BACKUP,
            self._ops_base(),
            t("Run this backup now?"),
        )

    def _ops_backup_status(self):
        """L'état se lit sans root : fichiers d'état lisibles par tous.
        Illisible (code 2), la commande sous sudo est proposée."""
        commande = [sys.executable, ODOO_BACKUP, "--status"]
        print(f"\n{t('Will execute:')} {joindre(commande)}")
        status = self.execute.exec_command_live(
            joindre(commande), source_erplibre=False
        )
        if status == 2:
            print(
                f"  ✗ {t('The state is not readable; run it with sudo:')}"
                f" sudo {joindre(commande)}"
            )

    def _ops_test_restore(self):
        self._ops_lancer(
            ODOO_BACKUP,
            ["--test-restore"] + self._ops_base(),
            t(
                "Run this test restore? A temporary database is created,"
                " then dropped."
            ),
        )

    def _ops_restore_new_database(self):
        fichier = input(t("Backup file to restore (.zip): ")).strip()
        if not fichier:
            print(t("Cancelled: no file given."))
            return
        nouvelle = input(t("New database name (must not exist): ")).strip()
        if not nouvelle:
            print(t("Cancelled: no database given."))
            return
        self._ops_lancer(
            ODOO_BACKUP,
            ["--restore", "--file", fichier, "--into", nouvelle],
            t("Restore into the new database {database}?").format(
                database=nouvelle
            ),
        )

    def _ops_backup_timer(self):
        reponse = input(
            t("Install or remove the scheduled backup? [I/r] ")
        ).strip()
        retirer = reponse.lower() in ("r", "remove", "retirer")
        args = (["--uninstall"] if retirer else []) + self._ops_base()
        question = (
            t("Remove the scheduled backup? Backups are kept.")
            if retirer
            else t("Install the scheduled backup (daily at 03:00)?")
        )
        self._ops_lancer(INSTALL_BACKUP_TIMER, args, question)

    def _ops_lire(self, script, args, sudo_d_avance=False):
        """Lance un outil qui ne fait que lire, sans sudo, par
        `exec_command_live`. Code 2 (lecture refusée au compte courant) :
        la commande sous sudo est montrée, puis lancée sur accord, sans
        capture. `sudo_d_avance` : lancer directement sous sudo."""
        commande = [sys.executable, script] + args
        if sudo_d_avance:
            reelle = ["sudo"] + commande
            print(f"\n{t('Will execute:')} {joindre(reelle)}")
            fin = subprocess.run(reelle)
            if fin.returncode not in (0, 1):
                print(
                    f"  ✗ {t('The command ended with code')} {fin.returncode}"
                )
            return
        print(f"\n{t('Will execute:')} {joindre(commande)}")
        status = self.execute.exec_command_live(
            joindre(commande), source_erplibre=False
        )
        if status != 2:
            return
        print(
            f"  ✗ {t('Not readable by this account; with sudo:')}"
            f" sudo {joindre(commande)}"
        )
        if click.confirm(t("Run it with sudo?")):
            subprocess.run(["sudo"] + commande)

    def _ops_nombre(self, question, defaut):
        """Un entier ≥ 1 saisi, `defaut` sur une réponse vide ; None sur
        une réponse invalide (message affiché)."""
        texte = input(question).strip()
        if not texte:
            return defaut
        if not texte.isdigit() or int(texte) < 1:
            print(t("Cancelled: expected a whole number >= 1."))
            return None
        return int(texte)

    def _ops_log_since_last(self):
        """La position se garde dans un dossier de root : sans droit
        d'écriture, sudo est proposé d'avance (refusé, la lecture se fait
        quand même, sans retenir la position)."""
        sudo = False
        if os.geteuid() != 0 and not _inscriptible(ETAT_LOG_CHECK):
            sudo = click.confirm(
                t(
                    "The position is kept in {path}, writable by root only:"
                    " run with sudo?"
                ).format(path=ETAT_LOG_CHECK),
                default=True,
            )
        self._ops_lire(LOG_CHECK, ["--since-last"], sudo_d_avance=sudo)

    def _ops_log_last_hours(self):
        heures = self._ops_nombre(t("Number of hours [24]: "), 24)
        if heures is not None:
            self._ops_lire(LOG_CHECK, ["--last", str(heures)])

    def _ops_log_hourly(self):
        jours = self._ops_nombre(t("Number of days [7]: "), 7)
        if jours is not None:
            self._ops_lire(LOG_CHECK, ["--by-hour", "--days", str(jours)])

    def _ops_mail_list(self):
        self._ops_lire(MAIL_RETRY, ["--list"] + self._ops_base())

    def _ops_mail_retry(self):
        """Le renvoi : sudo sans capture, après accord ; la sélection se
        fait dans le menu de mail_retry.py, qui a le terminal."""
        args = self._ops_base()
        if not click.confirm(
            t(
                "Open the failed mail list with sudo to choose which ones to"
                " resend?"
            )
        ):
            return
        reelle = ["sudo", sys.executable, MAIL_RETRY] + args
        print(f"\n{t('Will execute:')} {joindre(reelle)}")
        fin = subprocess.run(reelle)
        if fin.returncode not in (0, 1):
            print(f"  ✗ {t('The command ended with code')} {fin.returncode}")

    def _ops_health_local(self):
        self._ops_lire(HEALTH_CHECK, ["--local"])

    def _ops_health_url(self):
        """L'URL est validée ici par la règle de health_check.py (schéma
        http ou https, aucun identifiant) ; le domaine de courriel est
        facultatif. Aucun sudo : rien n'est lu sur ce poste."""
        from script.odoo import health_check

        texte = input(t("Public URL (https://host): ")).strip()
        try:
            cible = health_check.normaliser_url(texte)
        except ValueError as err:
            print(
                t("Cancelled: invalid URL ({reason}).").format(
                    reason=t(str(err))
                )
            )
            return
        args = ["--url", cible.url]
        domaine = input(
            t("Sending mail domain to check (empty = none): ")
        ).strip()
        if domaine:
            if health_check.RE_DOMAINE.fullmatch(domaine) is None:
                print(t("Cancelled: invalid domain."))
                return
            args += ["--mail-domain", domaine]
        commande = [sys.executable, HEALTH_CHECK] + args
        print(f"\n{t('Will execute:')} {joindre(commande)}")
        self.execute.exec_command_live(
            joindre(commande), source_erplibre=False
        )

    def _ops_warmup_deep(self):
        self._ops_lire(WARMUP_HTTP, ["--deep", "--local"])

    def _ops_perf_duree(self):
        """La durée saisie, validée par la règle de host_perf_audit.py
        (1 s à 7 jours), en secondes ; None si refusée. Seul ce nombre est
        transmis : rien de ce qui est tapé n'atteint un shell distant."""
        from script.proxmox import host_perf_audit

        texte = input(
            t("Audit duration (90, 30s, 10m, 2h; default 60): ")
        ).strip()
        try:
            return host_perf_audit.duree_valide(texte or "60")
        except ValueError:
            print(
                t(
                    "Cancelled: duration refused (1 second to 7 days, e.g."
                    " 90, 10m, 1h30m)."
                )
            )
            return None

    def _ops_perf_audit(self):
        """L'audit de performance de CE poste."""
        secondes = self._ops_perf_duree()
        if secondes is not None:
            self._ops_perf_local(secondes)

    def _ops_perf_local(self, secondes, runner=None):
        """Lance l'audit ici, sans sudo : il dit lui-même ce qui manque
        sans root."""
        conseil = t(
            "SMART health and some ZFS details need root; for a complete"
            " report:"
        )
        print(f"  {conseil} sudo {joindre([sys.executable, HOST_PERF_AUDIT])}")
        argv = [sys.executable, HOST_PERF_AUDIT, "--duration", str(secondes)]
        self._ops_perf_lancer(argv, secondes, runner=runner)

    def _ops_perf_lancer(self, argv, secondes, runner=None, distant=False):
        """Affiche puis lance `argv` sans capture, avec un délai de
        `secondes` + MARGE_AUDIT_S ; `distant` envoie le fichier de l'audit
        sur son stdin. Rend le code de sortie, ou None (délai, Ctrl-C,
        lancement impossible). `runner(argv, stdin=, timeout=)` est
        remplacé par les tests."""
        runner = runner or lancer_en_direct
        affichee = joindre(argv)
        if distant:
            affichee += " < " + HOST_PERF_AUDIT_RELATIF
        print(f"\n{t('Will execute:')} {affichee}")
        delai = secondes + MARGE_AUDIT_S
        try:
            if distant:
                with open(HOST_PERF_AUDIT, "rb") as fichier:
                    code = runner(argv, stdin=fichier, timeout=delai)
            else:
                code = runner(argv, stdin=None, timeout=delai)
        except subprocess.TimeoutExpired:
            message = t("The audit did not finish in time and was stopped.")
            print(f"  ✗ {message}")
            return None
        except KeyboardInterrupt:
            if distant:
                message = t(
                    "The remote audit ended without its report: a local"
                    " Ctrl-C closes the connection. To stop early and still"
                    " get a report, run the script on the host itself."
                )
                print(f"  ✗ {message}")
            else:
                message = t(
                    "Interrupted: the report above covers the samples"
                    " already taken."
                )
                print(f"  {message}")
            return None
        except OSError as err:
            print(f"  ✗ {t('Could not start it:')} {err}")
            return None
        self._ops_perf_bilan(code, distant)
        return code

    @staticmethod
    def _ops_perf_bilan(code, distant):
        """Le message d'un code de sortie de l'audit ; rien pour 0."""
        if code == 0:
            return
        if distant and code == 127:
            print(f"  ✗ {t('python3 is missing on the Proxmox host.')}")
        elif distant and code == 255:
            print(f"  ✗ {t('The SSH connection failed (code 255).')}")
        elif code == 2:
            message = t(
                "The audit could not run (code 2): see the message above."
            )
            print(f"  ✗ {message}")
        else:
            print(f"  ✗ {t('The command ended with code')} {code}")


def lancer_en_direct(argv, stdin=None, timeout=None):
    """Lance `argv` SANS capture (la sortie s'affiche au fil de l'eau) et
    rend son code.

    Délai dépassé : TERM, puis KILL, et TimeoutExpired remonte. Ctrl-C :
    un programme local reçoit le même SIGINT (même groupe de processus) ;
    on lui laisse ATTENTE_RAPPORT_S pour écrire son rapport, puis
    KeyboardInterrupt remonte. Un second Ctrl-C l'arrête net.
    `subprocess.run` ne convient pas : sur Ctrl-C, il tue l'enfant après
    un quart de seconde, au milieu du rapport."""
    proc = subprocess.Popen(argv, stdin=stdin)
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _arreter(proc)
        raise
    except KeyboardInterrupt:
        try:
            proc.wait(timeout=ATTENTE_RAPPORT_S)
        except (KeyboardInterrupt, subprocess.TimeoutExpired):
            _arreter(proc)
        raise


def _arreter(proc):
    """TERM, puis KILL après 10 s."""
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _inscriptible(dossier):
    """True si le compte courant peut écrire dans `dossier`, ou le créer
    dans son parent existant le plus proche."""
    while dossier and not os.path.exists(dossier):
        parent = os.path.dirname(dossier)
        if parent == dossier:
            break
        dossier = parent
    return os.access(dossier, os.W_OK)
