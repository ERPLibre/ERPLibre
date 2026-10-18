#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Production : opérer une instance servie par systemd sur ce poste.

Ce mixin ne fait que poser les questions et lancer les outils qui portent
toute la logique : `script/odoo/update_module.py` (mise à jour),
`script/database/odoo_backup.py` (sauvegarde, état, restauration d'essai,
restauration dans une nouvelle base),
`script/systemd/install_backup_timer.py` (sauvegarde planifiée),
`script/odoo/log_check.py` (journal d'Odoo) et `script/odoo/mail_retry.py`
(courriels en échec d'envoi). Le menu n'en duplique rien : ce qui se fait
depuis ici se fait aussi bien en ligne de commande.

Tout ce qui écrit passe par deux temps :

1. la simulation (`--dry-run`), lancée sous le compte courant, montre ce
   qui a été détecté et les commandes exactes ;
2. après confirmation seulement, l'exécution réelle sous `sudo`, par
   `subprocess.run` SANS capture : le terminal reste celui du programme,
   ce qui permet à sudo de demander son mot de passe et au programme de
   poser sa question quand on l'interrompt par Ctrl-C.

Une simulation qui refuse (code non nul) arrête là : il n'y a rien à
confirmer. L'état des sauvegardes, le journal d'Odoo et la liste des
courriels en échec, qui n'écrivent rien dans l'instance, se lancent
directement, sans confirmation ni sudo ; quand le compte courant ne peut
pas les lire (code 2), la même commande sous sudo est proposée.

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
# Le dossier d'état par défaut de log_check.py.
ETAT_LOG_CHECK = "/var/lib/erplibre-logcheck"


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
            else:
                print(t("Command not found !"))

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


def _inscriptible(dossier):
    """True si le compte courant peut écrire dans `dossier`, ou le créer
    dans son parent existant le plus proche."""
    while dossier and not os.path.exists(dossier):
        parent = os.path.dirname(dossier)
        if parent == dossier:
            break
        dossier = parent
    return os.access(dossier, os.W_OK)
