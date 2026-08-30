#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import datetime
import getpass
import logging
import os
import zipfile

from script.todo.todo_i18n import t

_logger = logging.getLogger(__name__)

try:
    import click

    from script.todo import todo_file_browser
except Exception:
    click = None
    todo_file_browser = None


class DatabaseManager:
    def __init__(self, execute, fill_help_info) -> None:
        self._execute = execute
        self._fill_help_info = fill_help_info
        self._dir_path: str | None = None

    def _on_dir_selected(self, path: str) -> None:
        self._dir_path = path

    def select_database(self) -> str | bool:
        """Faire choisir une base parmi celles que PostgreSQL expose.

        Le code de retour de « db --list » est vérifié AVANT de construire le
        menu. Sans cette vérification, un PostgreSQL injoignable ne se distingue
        pas d'une base absente : la sortie et l'erreur sont fusionnées dans le
        même flux (`stderr=STDOUT`, execute.py), donc les lignes de la trace
        d'appel devenaient les entrées du menu. « Traceback (most recent call
        last): » s'affichait comme la base [1], et la choisir renvoyait cette
        ligne comme nom de base à l'appelant, qui la passait à sa commande.
        """
        cmd_server = "./odoo_bin.sh db --list"
        status, output = self._execute.exec_command_live(
            cmd_server,
            return_status_and_output=True,
            quiet=True,
            source_erplibre=False,
            single_source_erplibre=True,
        )
        if status:
            print(f"❌ {t('Cannot list the databases (exit code): ')}{status}")
            print(f"   {t('Is PostgreSQL running?')}")
            for line in output[-5:]:
                print(f"   {line}")
            return False

        databases = [a.strip() for a in output if a.strip()]
        if not databases:
            print(f"ℹ️  {t('No database on this PostgreSQL server.')}")
            return False

        choices = [{"prompt_description": a} for a in databases]
        help_info = self._fill_help_info(choices)
        valid_choices = [str(a + 1) for a in range(len(databases))]

        while True:
            answer = click.prompt(help_info)
            print()
            if answer == "0":
                return False
            elif answer in valid_choices:
                database_name = databases[int(answer) - 1]
                print(database_name)
                return database_name
            else:
                print(t("Command not found !"))

    def _confirm_drop(self, message: str) -> bool:
        """Ask for an explicit 'oui'/'yes' confirmation, default is no."""
        print(f"⚠️  {message}")
        answer = (
            input(t("Type 'oui' to confirm (default: no): ")).strip().lower()
        )
        return answer in ("oui", "yes")

    def drop_database(self) -> None:
        print(f"⚠️  {t('Erase a database — irreversible operation!')}")
        choices = [
            {
                "prompt_description": t(
                    "Erase ALL databases (make db_drop_all)"
                )
            },
            {"prompt_description": t("Erase a single database")},
        ]
        help_info = self._fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return
            elif status == "1":
                self._drop_all_databases()
                return
            elif status == "2":
                self._drop_single_database()
                return
            else:
                print(t("Command not found !"))

    def _drop_all_databases(self) -> None:
        if not self._confirm_drop(
            t("You are about to erase ALL databases. This cannot be undone.")
        ):
            print(t("Database deletion cancelled."))
            return
        self._execute.exec_command_live(
            "make db_drop_all",
            source_erplibre=False,
            single_source_erplibre=True,
        )

    def _drop_single_database(self) -> None:
        database_name = self.select_database()
        if not database_name:
            print(t("No database selected."))
            return
        message = t(
            "You are about to erase the database '{database}'."
            " This cannot be undone."
        ).format(database=database_name)
        if not self._confirm_drop(message):
            print(t("Database deletion cancelled."))
            return
        self._execute.exec_command_live(
            f"./odoo_bin.sh db --drop --database {database_name}",
            source_erplibre=False,
            single_source_erplibre=True,
        )

    def restore_from_database(self, show_remote_list: bool = True) -> None:
        path_image_db = os.path.join(os.getcwd(), "image_db")
        print("[1] By filename from image_db")
        print(f"[] Browser image_db {path_image_db}")
        status = input("\U0001f4ac Select : ")
        if status == "1":
            file_name = status
        else:
            file_name = self.open_file_image_db()

        default_database_name = file_name.replace(" ", "_")
        if default_database_name.endswith(".zip"):
            default_database_name = default_database_name[:-4]

        database_name = input(
            f"\U0001f4ac Database name (default={default_database_name}) : "
        )
        if not database_name:
            database_name = default_database_name

        status = (
            input("\U0001f4ac Would you like to neutralize database (n/N)? ")
            .strip()
            .lower()
        )
        is_neutralize = False
        more_arg = ""
        if status != "n":
            more_arg = "--neutralize "
            is_neutralize = True
            database_name += "_neutralize"
        status, output_lines = self._execute.exec_command_live(
            f"python3 ./script/database/db_restore.py -d {database_name} "
            f"{more_arg}--ignore_cache --image {file_name}",
            return_status_and_output=True,
            single_source_erplibre=True,
            source_erplibre=False,
        )
        if is_neutralize:
            status, output_lines = self._execute.exec_command_live(
                f"./script/addons/update_prod_to_dev.sh {database_name}",
                return_status_and_output=True,
                single_source_erplibre=True,
                source_erplibre=False,
            )
        status = (
            input("\U0001f4ac Would you like to update all addons (y/Y)? ")
            .strip()
            .lower()
        )
        if status == "y":
            status, output_lines = self._execute.exec_command_live(
                f"./script/addons/update_addons_all.sh {database_name}",
                return_status_and_output=True,
                single_source_erplibre=True,
                source_erplibre=False,
            )

    def duplicate_database(self) -> None:
        """Copier une base, et proposer de la neutraliser.

        On passe par `db_duplicate.py`, donc par Odoo, et non par un
        `CREATE DATABASE … TEMPLATE` : lui seul coupe les connexions
        ouvertes sur la source, régénère le `database.uuid`, copie le
        filestore et sait neutraliser pour de bon.

        La neutralisation est proposée par DÉFAUT. Mesuré sur trois
        migrations de suite : la copie gardait 33 crons actifs, aucun
        serveur de courriel — donc le repli sur `smtp_server` de la
        configuration — et une clé de paiement vivante. Le défaut à
        « oui » est le seul qui protège celui qui appuie sur Entrée.
        """
        source = self.select_database()
        if not source:
            return
        defaut = f"{source}_neutralize"
        cible = input(
            f"\U0001f4ac {t('Name of the copy (default=')}{defaut}) : "
        ).strip()
        cible = cible or defaut

        reponse = (
            input(f"\U0001f4ac {t('Neutralize the copy (Y/n)? ')}")
            .strip()
            .lower()
        )
        neutraliser = reponse != "n"
        if not neutraliser:
            print(
                f"⚠️  {t('The copy will keep its scheduled actions, its')}"
                f" {t('outgoing mail and its payment providers.')}"
            )

        commande = (
            f"python3 ./script/database/db_duplicate.py"
            f" -s {source} -d {cible}"
        )
        if neutraliser:
            commande += " --neutralize"
        status, _ = self._execute.exec_command_live(
            commande,
            return_status_and_output=True,
            single_source_erplibre=True,
            source_erplibre=False,
        )
        if status:
            print(f"❌ {t('The duplication failed.')}")
            return
        # RELIRE plutôt que croire : c'est le contrôle qui manquait aux
        # trois modules maison, dont aucun ne posait le drapeau.
        if neutraliser:
            self._report_neutralize(cible)

    @staticmethod
    def _report_neutralize(database: str) -> None:
        """Dire ce que la neutralisation a réellement pris."""
        try:
            from script.analyse import monitoring

            print()
            print(
                monitoring.neutralize_report(
                    monitoring.neutralize_state(database), colour=True
                )
            )
        except Exception as exc:  # noqa: BLE001 - un rapport, pas le sujet
            print(f"ℹ️  {t('Cannot read the copy back: ')}{exc}")

    def create_backup_from_database(
        self, show_remote_list: bool = True
    ) -> None:
        database_name = self.select_database()
        backup_name = input(
            "\U0001f4ac Backup name (default = name+date.zip) : "
        )
        if not backup_name:
            backup_name = (
                database_name
                + "_"
                + datetime.datetime.now().strftime("%Y-%m-%d_%Hh%Mm%Ss")
                + ".zip"
            )

        if not backup_name.endswith(".zip"):
            backup_name = backup_name + ".zip"

        print(backup_name)

        cmd = (
            f"./odoo_bin.sh db --backup --database {database_name}"
            f" --restore_image {backup_name}"
        )
        status, output_lines = self._execute.exec_command_live(
            cmd,
            return_status_and_output=True,
            single_source_erplibre=True,
            source_erplibre=False,
        )

    def open_file_image_db(self) -> str:
        self._dir_path = ""
        path_image_db = os.path.join(os.getcwd(), "image_db")

        file_browser = todo_file_browser.FileBrowser(
            path_image_db, self._on_dir_selected
        )
        file_browser.run_main_frame()
        file_name = os.path.basename(self._dir_path)
        print(file_name)
        return file_name

    def select_backup_path(self, start=None) -> str | None:
        """Faire choisir une sauvegarde .zip, au parcours ou au chemin tapé.

        Les deux, parce que ni l'un ni l'autre ne suffit : le parcours part
        d'`image_db/` et n'aide pas si la sauvegarde vient d'ailleurs ; le
        chemin tapé oblige à le connaître. Le parcours d'abord, et une saisie
        directe si l'on en sort sans rien choisir.
        """
        directory = start or os.path.join(os.getcwd(), "image_db")
        if todo_file_browser is not None and os.path.isdir(directory):
            self._dir_path = ""
            browser = todo_file_browser.FileBrowser(
                directory, self._on_dir_selected
            )
            browser.run_main_frame()
            if self._dir_path and os.path.isfile(self._dir_path):
                print(self._dir_path)
                return self._dir_path
        answer = input(
            t("Path to the backup .zip (empty to cancel): ")
        ).strip()
        if not answer:
            return None
        path = os.path.expanduser(answer)
        if not os.path.isfile(path):
            print(f"❌ {t('No such file: ')}{path}")
            return None
        return path

    def download_database_backup_cli(
        self, show_remote_list: bool = True
    ) -> tuple[int, str, str]:
        database_domain = input("Domain Odoo (ex. https://mondomain.com) : ")
        if show_remote_list:
            status, output_lines = self._execute.exec_command_live(
                f"python3 ./script/database/list_remote.py --raw"
                f" --odoo-url {database_domain}",
                return_status_and_output=True,
                single_source_erplibre=True,
                source_erplibre=False,
            )
            if len(output_lines) > 1:
                for index, output in enumerate(output_lines):
                    print(f"{index + 1} - {output}")
                database_name = input("Select id of database :").strip()
            elif len(output_lines) == 1:
                database_name = output_lines[0].strip()
            else:
                database_name = input(
                    "Cannot read remote database, Database name :\n"
                )
        else:
            database_name = input("Database name :\n")

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%Hh%Mm%Ss")
        default_output_path = f"./image_db/{database_name}_{timestamp}.zip"
        output_path = input(
            f"Output path (default: {default_output_path}) : "
        ).strip()
        if not output_path:
            output_path = default_output_path

        master_password = getpass.getpass(prompt="Master password : ")

        cmd = "script/database/download_remote.sh --quiet"
        my_env = os.environ.copy()
        my_env["MASTER_PWD"] = master_password
        my_env["DATABASE_NAME"] = database_name
        my_env["OUTPUT_FILE_PATH"] = output_path
        my_env["ODOO_URL"] = database_domain
        status, cmd_executed = self._execute.exec_command_live(
            cmd,
            source_erplibre=False,
            return_status_and_command=True,
            new_env=my_env,
        )
        try:
            with zipfile.ZipFile(default_output_path, "r") as zip_ref:
                manifest_file_1 = zip_ref.open("manifest.json")
            _logger.info(
                f"Log file '{default_output_path}' is complete"
                " and validated."
            )
        except Exception as e:
            _logger.error(e)
            _logger.error(
                "Failed to read manifest.json from backup file"
                f" '{default_output_path}'."
            )
        return status, output_path, database_name
