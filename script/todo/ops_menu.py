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

La racine nomme l'instance visée et son profil, puis ouvre un sous-menu
par thème ; les réglages vivent dans `ops_settings.py`. Chaque commande
est construite par `_ops_commande` : `--service` quand l'outil vise une
unité, `--profile <chemin absolu>` quand le profil existe, puis les
arguments du geste. todo ne développe pas le profil : l'outil l'applique
et la simulation montre les valeurs qui en viennent.

Tout ce qui écrit passe par deux temps :

1. la simulation (`--dry-run`), lancée sous le compte courant, montre ce
   qui a été détecté et les commandes exactes ;
2. après confirmation seulement, l'exécution réelle sous `sudo`, par
   `todo_journal.lancer_au_terminal` : le terminal reste celui du
   programme, ce qui permet à sudo de demander son mot de passe et au
   programme de poser sa question quand on l'interrompt par Ctrl-C ; la
   commande et son code vont au journal de session. L'exécution réelle
   porte `--profile-sha256` : l'outil refuse un profil modifié depuis la
   simulation.

Une simulation qui refuse (code non nul) arrête là : il n'y a rien à
confirmer. L'état des sauvegardes, le journal d'Odoo, la liste des
courriels en échec, la santé de l'instance locale et le préchauffage, qui
n'écrivent rien dans l'instance, se lancent directement, sans
confirmation ni sudo ; quand le compte courant ne peut pas lire ce qu'il
faut (code 2), la même commande sous sudo est proposée. La santé d'une
URL publique ne lit rien sur ce poste : son code 2 est une URL refusée, et
sudo n'est jamais proposé.

Un secret du profil (référence KeePass) arrive à l'outil par le chemin
d'un fichier 0600 d'un tmpfs, jamais par sa valeur : le bloc
`fichiers_secrets` englobe toutes les tentatives d'un geste, reprise sous
sudo comprise, et retire le fichier à sa sortie.

L'audit de performance se lance sans sudo ni capture, avec un délai égal
à la durée demandée plus une marge ; le menu Proxmox réutilise les mêmes
méthodes pour l'envoyer à l'hôte retenu par ssh, le fichier sur stdin.

`log_check --since-last` retient sa position dans un dossier de root : le
menu propose sudo d'avance quand ce dossier n'est pas inscriptible, sinon
chaque lecture repartirait des dernières 24 h. Le renvoi des courriels
passe par sudo SANS capture : le menu de sélection de `mail_retry` a
besoin du terminal.
"""

import contextlib
import datetime
import os
import shlex
import subprocess
import sys

import click

from script.execute import execute as execution
from script.lib_ops import credentials, profil, systemd
from script.todo import ops_settings, todo_journal
from script.todo.system_menu import affichable, entier
from script.todo.todo_i18n import t

# Le dossier d'état par défaut de log_check.py, quand le profil n'en donne
# pas.
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
# Durée de l'audit sans profil ni saisie, celle de host_perf_audit.py.
DUREE_AUDIT_S = 60
# Au-delà de la durée mesurée : les commandes lancées une fois (zpool, zfs,
# smartctl, chacune bornée à 20 s) et le rapport.
MARGE_AUDIT_S = 300
# Après un Ctrl-C, le temps laissé à l'audit local pour écrire son rapport.
ATTENTE_RAPPORT_S = 60

# Les `dest` dont la valeur venue du profil est rappelée dans la question
# d'un geste qui écrit : elles décident de ce qui est supprimé, copié
# ailleurs ou tu.
A_RAPPELER = (
    "keep_daily",
    "keep_weekly",
    "keep_monthly",
    "keep_recent_days",
    "copy_to",
    "ignore_error",
)


def joindre(argv):
    return " ".join(shlex.quote(a) for a in argv)


def _option_valeur(argv, option):
    """La valeur qui suit `option` dans `argv`, ou None."""
    if option in argv[:-1]:
        return argv[argv.index(option) + 1]
    return None


def _empreinte(commande):
    """Le sha256 du profil que `commande` passe par `--profile`, ou ""."""
    chemin = _option_valeur(commande, "--profile")
    return profil.empreinte_fichier(chemin) if chemin else ""


def _a_des_secrets(groupe):
    return any(g == groupe for g, _cle in profil.SECRETS)


class OpsMenuMixin:
    """Menu Production. Voir l'en-tête du fichier pour sa frontière."""

    # -- Menus -----------------------------------------------------------

    def prompt_execute_production(self):
        # Un todo tué au milieu d'un geste a pu laisser un fichier de
        # secret : retiré sans message.
        ops_settings.purger_secrets_restants()
        while True:
            print(self._ops_entete())
            choices = [
                {"section": t("Instance")},
                {
                    "prompt_description": t(
                        "Choose the instance - {service}"
                    ).format(service=self._ops_service() or "—")
                },
                {"section": t("Operate")},
                {"prompt_description": t("Update - modules of the instance")},
                {"prompt_description": t("Backups - now, status, restore")},
                {
                    "prompt_description": t(
                        "Journal and mail - Odoo errors, failed outgoing mail"
                    )
                },
                {"prompt_description": t("Health and warm-up")},
                {
                    "prompt_description": t(
                        "Host audit - performance, read-only"
                    )
                },
                {"section": t("Configure")},
                {"prompt_description": t("systemd timers")},
                {
                    "prompt_description": t(
                        "Settings - every option of every tool"
                    )
                },
            ]
            status = click.prompt(self.fill_help_info(choices))
            print()
            if status == "0":
                return False
            elif status == "1":
                self._ops_choisir_instance()
            elif status == "2":
                self._ops_menu_update()
            elif status == "3":
                self._ops_menu_backups()
            elif status == "4":
                self._ops_menu_journal_mail()
            elif status == "5":
                self._ops_menu_health()
            elif status == "6":
                self._ops_menu_host_audit()
            elif status == "7":
                self._ops_menu_timers()
            elif status == "8":
                self._ops_menu_settings()
            else:
                print(t("Command not found !"))

    def _ops_menu_update(self):
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
            else:
                print(t("Command not found !"))

    def _ops_menu_backups(self):
        choices = [
            {"section": t("Now")},
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
            {"section": t("Restore")},
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
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._ops_backup_now()
            elif status == "2":
                self._ops_backup_status()
            elif status == "3":
                self._ops_test_restore()
            elif status == "4":
                self._ops_restore_new_database()
            else:
                print(t("Command not found !"))

    def _ops_menu_journal_mail(self):
        choices = [
            {"section": t("Odoo journal")},
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
            {"section": t("Outgoing mail")},
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
                self._ops_log_since_last()
            elif status == "2":
                self._ops_log_last_hours()
            elif status == "3":
                self._ops_log_hourly()
            elif status == "4":
                self._ops_mail_list()
            elif status == "5":
                self._ops_mail_retry()
            else:
                print(t("Command not found !"))

    def _ops_menu_health(self):
        choices = [
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
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._ops_health_local()
            elif status == "2":
                self._ops_health_url()
            elif status == "3":
                self._ops_warmup_deep()
            else:
                print(t("Command not found !"))

    def _ops_menu_host_audit(self):
        choices = [
            {
                "prompt_description": t(
                    "Host performance audit of this machine - read-only"
                )
            },
            {
                "prompt_description": t(
                    "Audit settings of this machine - duration, interval,"
                    " guests"
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
                self._ops_perf_audit()
            elif status == "2":
                self._ops_settings_host_local()
            else:
                print(t("Command not found !"))

    def _ops_menu_timers(self):
        choices = [
            {
                "prompt_description": t(
                    "Timers of this instance - read-only, credentials"
                )
            },
            {
                "prompt_description": t(
                    "Install or update the scheduled backup - simulate,"
                    " confirm, then run with sudo"
                )
            },
            {
                "prompt_description": t(
                    "Remove the scheduled backup - backups are kept"
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
                self._ops_timers_status()
            elif status == "2":
                self._ops_backup_timer_install()
            elif status == "3":
                self._ops_backup_timer_remove()
            else:
                print(t("Command not found !"))

    def _ops_menu_settings(self):
        choices = [
            {
                "section": t("Profile of {service}").format(
                    service=self._ops_service() or "—"
                )
            },
            {"prompt_description": t("Edit the settings")},
            {
                "prompt_description": t(
                    "Show the profile - value, default, origin, excluded"
                    " options"
                )
            },
            {
                "prompt_description": t(
                    "Check the profile with this checkout's tools"
                )
            },
            {"prompt_description": t("Secrets in KeePass")},
            {"prompt_description": t("Delete the profile")},
            {"section": t("This host")},
            {
                "prompt_description": t(
                    "Host audit settings - this machine or the Proxmox host"
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
                self._ops_settings_edit()
            elif status == "2":
                self._ops_settings_show()
            elif status == "3":
                self._ops_settings_check()
            elif status == "4":
                self._ops_settings_secrets()
            elif status == "5":
                self._ops_settings_delete()
            elif status == "6":
                self._ops_settings_host()
            else:
                print(t("Command not found !"))

    # -- Lancements ------------------------------------------------------

    def _ops_afficher_profil(self, groupe):
        """Imprime « Profile: --keep-daily 10, … » quand le profil donne
        des valeurs à l'outil `groupe`."""
        ligne = self._ops_ligne_profil(groupe)
        if ligne:
            print(f"  {ligne}")

    def _ops_secrets(self, groupe, args, forme="option"):
        """`_ops_fichiers_secrets` pour un outil qui déclare des secrets ;
        un bloc vide sinon, sans lire le profil une seconde fois."""
        if _a_des_secrets(groupe):
            return self._ops_fichiers_secrets(groupe, args, forme=forme)
        return contextlib.nullcontext(ops_settings.SecretsFournis())

    def _ops_simuler(self, commande):
        """Lance `commande --dry-run` par `exec_command_live`, annoncée une
        seule fois ici ; rend son code."""
        simulation = joindre(commande + ["--dry-run"])
        print(f"\n{t('Will execute:')} {simulation}")
        return self.execute.exec_command_live(
            simulation, source_erplibre=False, announce=False
        )

    @staticmethod
    def _ops_au_terminal(argv):
        """Lance `argv` par `todo_journal.lancer_au_terminal`, sans
        capture ; rend son code, ou None quand il ne démarre pas."""
        print(f"\n{t('Will execute:')} {joindre(argv)}")
        try:
            return todo_journal.lancer_au_terminal(argv).returncode
        except (OSError, subprocess.SubprocessError) as err:
            print(f"  ✗ {t('Could not start it:')} {err}")
            return None

    def _ops_defaut(self, groupe, dest):
        """Le défaut de l'option `dest` de l'outil `groupe`."""
        parser = ops_settings.construire_parseurs((groupe,))[groupe]
        for action in parser._actions:
            if action.dest == dest:
                return action.default
        return None

    def _ops_question(self, groupe, question, args):
        """La question d'un geste qui écrit, précédée du service et de la
        base visés, des valeurs du profil qui décident de ce qui est
        supprimé, copié ou tu (un motif `ignore_error` par ligne), et d'un
        avertissement quand l'unité fait tourner un autre checkout."""
        service = self._ops_service()
        base = _option_valeur(args, "--db") or self._ops_valeur(groupe, "db")
        lignes = [
            t("Instance: {service} · database: {database}").format(
                service=affichable(service or "—"),
                database=affichable(base) if base else t("(detected)"),
            )
        ]
        lu = self._ops_document()
        doc = lu.doc if lu else {}
        parser = ops_settings.construire_parseurs((groupe,))[groupe]
        tapees = ops_settings.presents_de(parser, args)
        for champ in profil.champs(parser, groupe) + profil.alias(
            parser, groupe
        ):
            dest = champ.action.dest
            if dest not in A_RAPPELER or dest in tapees:
                continue
            brut = (doc.get(champ.groupe) or {}).get(champ.cle)
            if brut is None:
                continue
            for valeur in brut if isinstance(brut, list) else [brut]:
                lignes.append(
                    f"  {champ.option} {ops_settings.formater(valeur)}"
                    f" ({t('profile')})"
                )
        alerte = self._ops_alerte_checkout(service)
        if alerte:
            lignes.append(alerte)
        lignes.append(question)
        return "\n".join(lignes)

    def _ops_lancer(
        self, groupe, args, question, simulation_seule=False, forme="option"
    ):
        """Simulation (`--dry-run`), confirmation, puis exécution réelle
        sous sudo par `lancer_au_terminal`, avec `--profile-sha256` quand
        un profil est lu. Rend True si l'exécution réelle a été lancée.
        Les valeurs saisies sont transmises telles quelles : l'outil les
        valide et refuse avant d'agir. Les secrets du profil passent par
        un fichier temporaire, sous la forme `forme` de
        `fichiers_secrets`."""
        commande = self._ops_commande(groupe, args)
        # L'empreinte est prise avant la simulation : un profil modifié
        # ensuite fait refuser l'exécution réelle.
        empreinte = _empreinte(commande)
        self._ops_afficher_profil(groupe)
        if self._ops_simuler(commande) != 0:
            print(f"  ✗ {t('The simulation refused: nothing was done.')}")
            return False
        if simulation_seule:
            return False
        if forme == "credential" and not self._ops_controle_credentials(
            groupe
        ):
            return False
        if not click.confirm(self._ops_question(groupe, question, args)):
            return False
        with self._ops_secrets(groupe, args, forme=forme) as fournis:
            if fournis.abandon:
                return False
            reelle = ["sudo"] + commande + fournis.argv
            if empreinte:
                reelle += ["--profile-sha256", empreinte]
            code = self._ops_au_terminal(reelle)
        if code not in (0, None):
            print(f"  ✗ {t('The command ended with code')} {code}")
        return True

    def _ops_controle_credentials(self, groupe, lanceur=None):
        """Avant d'installer une unité qui reçoit un secret du profil : la
        version de systemd, lue sans sudo. Refus avant 247 ; avant 250 ou
        sans `systemd-creds`, le secret serait rangé en clair et la
        question l'annonce (défaut non). Rend True pour continuer ; True
        aussi quand le profil ne donne aucun secret à `groupe`."""
        lu = self._ops_document()
        doc = lu.doc if lu else {}
        a_fournir = [
            nom
            for (g, cle), nom in profil.SECRETS.items()
            if g == groupe
            and isinstance(ops_settings.valeur_du_groupe(doc, g, cle), dict)
        ]
        if not a_fournir:
            return True
        try:
            stockage = credentials.choisir_stockage(
                *credentials.detecter(lanceur or systemd.lancer)
            )
        except credentials.ErreurCredential as err:
            print(f"  ✗ {err.message(t)}")
            return False
        if stockage.chiffre:
            return True
        return click.confirm(
            t(
                "systemd {version} cannot encrypt credentials: {names} would"
                " be stored in clear, readable by root only. Continue?"
            ).format(version=stockage.version, names=", ".join(a_fournir)),
            default=False,
        )

    def _ops_lire(self, groupe, args, sudo_d_avance=False):
        """Lance un outil qui ne fait que lire, sans sudo, par
        `exec_command_live`. Code 2 (lecture refusée au compte courant) :
        la commande sous sudo est montrée, puis lancée sur accord par
        `lancer_au_terminal`. `sudo_d_avance` : lancer directement sous
        sudo. Le bloc des secrets englobe les deux tentatives."""
        commande = self._ops_commande(groupe, args)
        self._ops_afficher_profil(groupe)
        with self._ops_secrets(groupe, args) as fournis:
            if fournis.abandon:
                return
            commande = commande + fournis.argv
            if sudo_d_avance:
                code = self._ops_au_terminal(["sudo"] + commande)
                if code not in (0, 1, None):
                    print(f"  ✗ {t('The command ended with code')} {code}")
                return
            print(f"\n{t('Will execute:')} {joindre(commande)}")
            status = self.execute.exec_command_live(
                joindre(commande), source_erplibre=False, announce=False
            )
            if status != 2:
                return
            print(
                f"  ✗ {t('Not readable by this account; with sudo:')}"
                f" sudo {joindre(commande)}"
            )
            if click.confirm(t("Run it with sudo?")):
                self._ops_au_terminal(["sudo"] + commande)

    def _ops_nombre(self, question, defaut):
        """Un entier ≥ 1 saisi en chiffres ASCII, `defaut` sur une réponse
        vide ; None sur une réponse invalide (message affiché)."""
        texte = input(question).strip()
        if not texte:
            return defaut
        nombre = entier(texte)
        if nombre is None or nombre < 1:
            print(t("Cancelled: expected a whole number >= 1."))
            return None
        return nombre

    def _ops_base(self, groupe):
        """`--db BASE`, ou rien : l'outil prend alors la base du profil,
        sinon celle qu'il détecte."""
        du_profil = self._ops_valeur(groupe, "db")
        if du_profil:
            question = t("Database (empty = {database} from the profile): ")
            question = question.format(database=affichable(du_profil))
        else:
            question = t("Database (empty = detect from the service): ")
        base = input(question).strip()
        return ["--db", base] if base else []

    # -- Mise à jour -----------------------------------------------------

    def _ops_update_arguments(self):
        """Les arguments d'update_module.py tirés des réponses, ou None.

        Modules exigés ; base vide = celle du profil ou celle que le
        programme détecte ; sauvegarde par défaut. Les valeurs sont
        transmises telles quelles : update_module.py les valide et refuse
        avant d'arrêter quoi que ce soit.
        """
        modules = input(
            t("Modules to update (commas, * and ? patterns, or all): ")
        ).strip()
        if not modules:
            print(t("Cancelled: no module given."))
            return None
        base = self._ops_base("update_module")
        sauvegarde = self._is_yes_default_yes(
            input(t("Back up the database before the update? [Y/n] "))
        )
        args = ["--module", modules] + base
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
        self._ops_lancer(
            "update_module",
            args,
            t("Run this update for real? The service stops meanwhile."),
            simulation_seule=simulation_seule,
        )

    # -- Sauvegardes -----------------------------------------------------

    def _ops_backup_now(self):
        self._ops_lancer(
            "backup", self._ops_base("backup"), t("Run this backup now?")
        )

    def _ops_backup_status(self):
        """L'état se lit sans root : fichiers d'état lisibles par tous.
        Illisible (code 2), la commande sous sudo est montrée puis lancée
        sur accord, comme pour toute lecture (`_ops_lire`)."""
        self._ops_lire("backup", ["--status"])

    def _ops_test_restore(self):
        self._ops_lancer(
            "backup",
            ["--test-restore"] + self._ops_base("backup"),
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
            "backup",
            ["--restore", "--file", fichier, "--into", nouvelle],
            t("Restore into the new database {database}?").format(
                database=nouvelle
            ),
        )

    # -- Minuteries ------------------------------------------------------

    def _ops_timers_status(self):
        """Les minuteries `erplibre-*` et, pour chaque unité installée, le
        stockage de ses credentials ; un avertissement pour un credential
        rangé en clair (systemd 247 à 249). Lecture seule, sans sudo."""
        commande = ["systemctl", "list-timers", "--all", "erplibre-*"]
        print(f"\n{t('Will execute:')} {joindre(commande)}")
        self.execute.exec_command_live(
            joindre(commande), source_erplibre=False, announce=False
        )
        chemin = self._ops_chemin_profil()
        citent = set(profil.unites_citant(chemin)) if chemin else set()
        for unite, lignes in _credentials_des_unites():
            marque = f" ({t('uses this profile')})" if unite in citent else ""
            print(f"\n  {affichable(unite)}{marque}")
            for directive, nom, _chemin in lignes:
                if directive == "LoadCredentialEncrypted":
                    print(f"    {affichable(nom)} : {t('encrypted')}")
                else:
                    print(
                        f"    ⚠ [ATTN] {affichable(nom)} : "
                        + t("stored in clear, readable by root only")
                    )

    def _ops_backup_timer_install(self):
        """Installe ou met à jour la sauvegarde planifiée ; la question
        annonce le calendrier réel (profil ou défaut de l'outil)."""
        calendrier = self._ops_valeur(
            "backup_timer", "on_calendar"
        ) or self._ops_defaut("backup_timer", "on_calendar")
        self._ops_lancer(
            "backup_timer",
            self._ops_base("backup_timer"),
            t("Install or update the scheduled backup ({calendar})?").format(
                calendar=affichable(calendrier)
            ),
            forme="credential",
        )

    def _ops_backup_timer_remove(self):
        self._ops_lancer(
            "backup_timer",
            ["--uninstall"] + self._ops_base("backup_timer"),
            t("Remove the scheduled backup? Backups are kept."),
        )

    # -- Journal et courriels --------------------------------------------

    def _ops_log_since_last(self):
        """La position se garde dans le dossier d'état du profil, sinon
        dans celui de l'outil : sans droit d'écriture, sudo est proposé
        d'avance (refusé, la lecture se fait quand même, sans retenir la
        position)."""
        etat = self._ops_valeur("log_check", "state_dir") or ETAT_LOG_CHECK
        sudo = False
        if os.geteuid() != 0 and not _inscriptible(etat):
            sudo = click.confirm(
                t(
                    "The position is kept in {path}, writable by root only:"
                    " run with sudo?"
                ).format(path=affichable(etat)),
                default=True,
            )
        self._ops_lire("log_check", ["--since-last"], sudo_d_avance=sudo)

    def _ops_log_last_hours(self):
        heures = self._ops_nombre(t("Number of hours [24]: "), 24)
        if heures is not None:
            self._ops_lire("log_check", ["--last", str(heures)])

    def _ops_log_hourly(self):
        """Le nombre de jours du profil sert de défaut : une réponse vide
        le laisse à l'outil, qui le lit lui-même."""
        du_profil = self._ops_valeur("log_check", "days")
        # 0 dit « réponse vide » : un nombre saisi vaut au moins 1.
        jours = self._ops_nombre(
            t("Number of days [{days}]: ").format(
                days=affichable(du_profil or 7)
            ),
            0,
        )
        if jours is None:
            return
        if not jours and du_profil is None:
            jours = 7
        args = ["--by-hour"]
        if jours:
            args += ["--days", str(jours)]
        self._ops_lire("log_check", args)

    def _ops_mail_list(self):
        self._ops_lire("mail_retry", ["--list"] + self._ops_base("mail_retry"))

    def _ops_mail_retry(self):
        """Le renvoi : sudo sans capture, après accord ; la sélection se
        fait dans le menu de mail_retry.py, qui a le terminal."""
        args = self._ops_base("mail_retry")
        if not click.confirm(
            t(
                "Open the failed mail list with sudo to choose which ones to"
                " resend?"
            )
        ):
            return
        commande = self._ops_commande("mail_retry", args)
        self._ops_afficher_profil("mail_retry")
        code = self._ops_au_terminal(["sudo"] + commande)
        if code not in (0, 1, None):
            print(f"  ✗ {t('The command ended with code')} {code}")

    # -- Santé et préchauffage -------------------------------------------

    def _ops_health_local(self):
        """L'instance seule : les URL publiques du profil sont écartées."""
        self._ops_lire("health_check", ["--local", "--profile-unset", "url"])

    def _ops_health_url(self):
        """Les URL du profil, sur accord, sinon une URL validée ici par la
        règle de health_check.py (schéma http ou https, aucun
        identifiant), dont le `--url` remplace la liste du profil ; le
        domaine de courriel est facultatif. Aucun `--service` ni sudo :
        rien n'est lu sur ce poste."""
        from script.odoo import health_check

        urls = self._ops_valeur("health_check", "url")
        args = []
        if not (
            isinstance(urls, list)
            and urls
            and click.confirm(
                t("Use the profile URLs ({urls})?").format(
                    urls=ops_settings.formater(urls)
                ),
                default=True,
            )
        ):
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
        commande = self._ops_commande("health_check", args)
        self._ops_afficher_profil("health_check")
        print(f"\n{t('Will execute:')} {joindre(commande)}")
        self.execute.exec_command_live(
            joindre(commande), source_erplibre=False, announce=False
        )

    def _ops_warmup_deep(self):
        self._ops_lire("warmup", ["--deep", "--local"])

    # -- Audit de performance --------------------------------------------

    def _ops_perf_duree(self, defaut=None):
        """La durée saisie, validée par la règle de host_perf_audit.py
        (1 s à 7 jours), en secondes ; `defaut` (valeur du profil) ou
        DUREE_AUDIT_S sur une réponse vide ; None si refusée. Rend
        `(secondes, saisie)` : `saisie` est faux quand la réponse était
        vide. Seul ce nombre est transmis : rien de ce qui est tapé
        n'atteint un shell distant."""
        from script.proxmox import host_perf_audit

        if defaut is None:
            defaut = DUREE_AUDIT_S
        texte = input(
            t("Audit duration (90, 30s, 10m, 2h; default {default}): ").format(
                default=affichable(defaut)
            )
        ).strip()
        try:
            return host_perf_audit.duree_valide(texte or str(defaut)), bool(
                texte
            )
        except ValueError:
            print(
                t(
                    "Cancelled: duration refused (1 second to 7 days, e.g."
                    " 90, 10m, 1h30m)."
                )
            )
            return None, False

    @staticmethod
    def _ops_profil_hote(slug):
        """Le document du profil d'hôte `slug`, ou {} (absent ou refusé,
        un avertissement le dit)."""
        try:
            return ops_settings.lire_hote(slug)
        except profil.ErreurProfil as err:
            print(
                "  ⚠ [ATTN] "
                + t("Profile {path}: {error}").format(
                    path=ops_settings.chemin_hote(slug), error=err.message(t)
                )
            )
            return {}

    def _ops_perf_audit(self, runner=None):
        """L'audit de performance de CE poste, avec son profil d'hôte
        `local` : la durée du profil sert de défaut, et une durée tapée
        l'emporte sur lui."""
        doc = self._ops_profil_hote("local")
        defaut = (doc.get(ops_settings.GROUPE_HOTE) or {}).get("duration")
        secondes, saisie = self._ops_perf_duree(defaut)
        if secondes is None:
            return
        args = []
        if saisie or defaut is None:
            args = ["--duration", str(secondes)]
        conseil = t(
            "SMART health and some ZFS details need root; for a complete"
            " report:"
        )
        print(f"  {conseil} sudo {joindre([sys.executable, HOST_PERF_AUDIT])}")
        argv = self._ops_commande(ops_settings.GROUPE_HOTE, args)
        argv[1] = HOST_PERF_AUDIT
        self._ops_afficher_profil(ops_settings.GROUPE_HOTE)
        self._ops_perf_lancer(argv, secondes, runner=runner)

    def _ops_perf_lancer(self, argv, secondes, runner=None, distant=False):
        """Affiche puis lance `argv` sans capture, avec un délai de
        `secondes` + MARGE_AUDIT_S ; `distant` envoie le fichier de l'audit
        sur son stdin. La commande puis son code vont au journal de
        session. Rend le code de sortie, ou None (délai, Ctrl-C,
        lancement impossible). `runner(argv, stdin=, timeout=)` est
        remplacé par les tests."""
        runner = runner or lancer_en_direct
        affichee = joindre(argv)
        if distant:
            affichee += " < " + HOST_PERF_AUDIT_RELATIF
        print(f"\n{t('Will execute:')} {affichee}")
        heure = f"{datetime.datetime.now():%H:%M:%S}"
        execution._journaliser(
            f"\n[{heure}] $ {execution.redact_secrets(affichee)}"
            f"  ({t('output on the terminal')})\n"
        )
        delai = secondes + MARGE_AUDIT_S
        code = None
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
        finally:
            execution._journaliser(f"[code {'—' if code is None else code}]\n")
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


def _credentials_des_unites(dossier=None):
    """[(unité, [(directive, nom, chemin)])] des unités `erplibre-*` de
    `dossier` (`profil.DOSSIER_UNITES`) qui chargent un credential. Lecture
    sans sudo : une unité illisible est sautée."""
    dossier = dossier or profil.DOSSIER_UNITES
    try:
        noms = sorted(os.listdir(dossier))
    except OSError:
        return []
    trouvees = []
    for nom in noms:
        if not profil.RE_UNITE_ERPLIBRE.fullmatch(nom):
            continue
        try:
            with open(os.path.join(dossier, nom), encoding="utf-8") as f:
                lignes = credentials.lignes_citees(f.read())
        except (OSError, UnicodeDecodeError):
            continue
        if lignes:
            trouvees.append((nom, lignes))
    return trouvees


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
