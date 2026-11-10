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


def _oui(reponse):
    """« Défaut non » : seule une réponse explicite accepte, FR ou EN."""
    return reponse.strip().lower() in ("y", "yes", "o", "oui")


def _non(reponse):
    """« Défaut oui » : seule une réponse explicite refuse, FR ou EN.

    « non » compte : comparer à « n » seul ferait de « non » un oui.
    """
    return reponse.strip().lower() in ("n", "no", "non")


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

    def _list_databases(self) -> list | None:
        """Les bases que PostgreSQL expose, ou None quand il n'y en a pas.

        Le code de retour de « db list » est vérifié AVANT de construire le
        menu. Sans cette vérification, un PostgreSQL injoignable ne se distingue
        pas d'une base absente : la sortie et l'erreur sont fusionnées dans le
        même flux (`stderr=STDOUT`, execute.py), donc les lignes de la trace
        d'appel deviendraient les entrées du menu, et « Traceback (most recent
        call last): » un nom de base rendu à l'appelant.
        """
        cmd_server = "./odoo_bin.sh db list"
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
            return None

        databases = [a.strip() for a in output if a.strip()]
        if not databases:
            print(f"ℹ️  {t('No database on this PostgreSQL server.')}")
            return None
        return databases

    def select_database(self) -> str | bool:
        """Faire choisir UNE base parmi celles que PostgreSQL expose."""
        databases = self._list_databases()
        if not databases:
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

    def select_databases(self) -> list:
        """Faire choisir UNE OU PLUSIEURS bases, par leurs numéros.

        Les numéros se séparent par des espaces (une virgule est tolérée).
        Rend les noms dans l'ordre tapé, sans doublon, ou une liste vide pour
        « 0 ». Une réponse qui contient un seul numéro invalide est refusée
        en entier et redemandée : effacer « ce qui était valide » d'une
        saisie fautive détruirait une base que l'on n'a peut-être pas visée.
        """
        databases = self._list_databases()
        if not databases:
            return []

        choices = [{"prompt_description": a} for a in databases]
        help_info = (
            self._fill_help_info(choices)
            + t("Numbers separated by spaces, e.g. 1 3 4")
            + "\n"
        )
        valid_choices = {str(a + 1) for a in range(len(databases))}

        while True:
            answer = click.prompt(help_info)
            print()
            numbers = answer.replace(",", " ").split()
            if numbers == ["0"]:
                return []
            invalid = [n for n in numbers if n not in valid_choices]
            if not numbers or invalid:
                print(
                    f"{t('Invalid choice:')} {' '.join(invalid or [answer])}"
                )
                continue
            selected = []
            for number in numbers:
                name = databases[int(number) - 1]
                if name not in selected:
                    selected.append(name)
            return selected

    def _confirm_drop(self, message: str) -> bool:
        """Ask for an explicit 'oui'/'yes' confirmation, default is no."""
        print(f"⚠️  {message}")
        answer = (
            input(t("Type 'oui' to confirm (default: no): ")).strip().lower()
        )
        return answer in ("oui", "yes")

    def drop_database(self) -> None:
        print(f"⚠️  {t('Erase databases — irreversible operation!')}")
        choices = [
            {
                "prompt_description": t(
                    "Erase ALL databases (make db_drop_all)"
                )
            },
            {"prompt_description": t("Erase one or more databases")},
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
                self._drop_selected_databases()
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

    def _drop_selected_databases(self) -> None:
        """Effacer les bases choisies, après UNE confirmation qui les nomme.

        Toutes sont nommées avant la question : on confirme ce qu'on lit.
        Un échec n'arrête pas les suivantes — chaque base est indépendante —
        et le bilan dit lesquelles restent.
        """
        names = self.select_databases()
        if not names:
            print(t("No database selected."))
            return
        if len(names) == 1:
            message = t(
                "You are about to erase the database '{database}'."
                " This cannot be undone."
            ).format(database=names[0])
        else:
            message = t(
                "You are about to erase {count} databases."
                " This cannot be undone:"
            ).format(count=len(names))
            message += "".join(f"\n   - {name}" for name in names)
        if not self._confirm_drop(message):
            print(t("Database deletion cancelled."))
            return
        failed = []
        for name in names:
            status, _output = self._execute.exec_command_live(
                f"./odoo_bin.sh db drop {name}",
                return_status_and_output=True,
                source_erplibre=False,
                single_source_erplibre=True,
            )
            if status:
                failed.append(name)
        erased = [name for name in names if name not in failed]
        if erased:
            print(f"✅ {t('Erased:')} {', '.join(erased)}")
        if failed:
            print(f"❌ {t('Not erased:')} {', '.join(failed)}")

    def restore_from_database(self, show_remote_list: bool = True) -> None:
        path_image_db = os.path.join(os.getcwd(), "image_db")
        print(f"[1] {t('By file name, from image_db')}")
        print(f"[] {t('Browse image_db')} {path_image_db}")
        status = input(f"\U0001f4ac {t('Select: ')}")
        if status == "1":
            file_name = self._ask_image_db_file_name(path_image_db)
        else:
            file_name = self.open_file_image_db()
        if not file_name:
            print(t("No backup selected, nothing restored."))
            return

        default_database_name = file_name.replace(" ", "_")
        if default_database_name.endswith(".zip"):
            default_database_name = default_database_name[:-4]

        database_name = input(
            f"\U0001f4ac {t('Database name (default=')}"
            f"{default_database_name}) : "
        )
        if not database_name:
            database_name = default_database_name

        for commande in self._restore_commands(file_name, database_name):
            status, _output_lines = self._execute.exec_command_live(
                commande,
                return_status_and_output=True,
                single_source_erplibre=True,
                source_erplibre=False,
            )
            if status:
                # Chaque étape suppose la précédente faite : mettre à jour
                # ou neutraliser une base mal restaurée ne fait qu'empiler
                # une seconde erreur sur la première.
                print(f"❌ {t('Step failed, the next ones are skipped:')}")
                print(f"   {commande}")
                return

    @staticmethod
    def _ask_image_db_file_name(path_image_db):
        """Une sauvegarde de `path_image_db` par son nom ; "" pour renoncer.

        db_restore.py lit « --image » dans image_db/, avec ou sans « .zip » :
        le nom rendu est celui du fichier, tel que le dossier le porte. Un
        nom absent est redemandé, avant toute question sur la base.
        """
        while True:
            nom = input(
                "\U0001f4ac "
                + t("Backup file name in image_db (empty to cancel): ")
            ).strip()
            if not nom:
                return ""
            for candidat in (nom, f"{nom}.zip"):
                if os.path.isfile(os.path.join(path_image_db, candidat)):
                    return candidat
            print(f"❌ {t('No such file in image_db:')} {nom}")

    def _restore_commands(self, file_name, database_name):
        """Poser toutes les questions, puis rendre les commandes, dans l'ordre.

        Les questions viennent AVANT la première commande : la restauration
        et les mises à jour durent, et l'on peut s'éloigner une fois la
        dernière réponse donnée.

        La neutralisation a deux temps, comme dans todo_upgrade.py. Odoo
        neutralise pendant le chargement (« --neutralize » de db_restore) ;
        update_prod_to_dev.sh installe ensuite les modules de
        développement (compte test/test, courriel et sauvegardes coupés).
        La mise à jour « avant » se place entre les deux : ces modules
        s'installent alors sur des modules déjà au niveau du code.

        « --neutralize » n'est passé qu'à partir d'Odoo 16 : avant,
        `odoo_db_legacy.py` refuse l'option et la restauration échoue dès
        la première commande. update_prod_to_dev.sh reste alors le seul
        temps de la neutralisation, et le suffixe « _neutralize » est gardé.
        """
        from script.database import db_duplicate

        cache = _oui(
            input(
                "\U0001f4ac "
                + t(
                    "Keep a _cache_ copy, not neutralized, to speed up the"
                    " next restore of this image (y/N, default: N)? "
                )
            )
        )
        neutraliser = not _non(
            input(
                "\U0001f4ac "
                + t("Neutralize the database (Y/n, default: Y)? ")
            )
        )
        if neutraliser:
            avant = _oui(
                input(
                    "\U0001f4ac "
                    + t(
                        "Update all addons before neutralizing"
                        " (y/N, default: N)? "
                    )
                )
            )
            apres = _oui(
                input(
                    "\U0001f4ac "
                    + t(
                        "Update all addons after neutralizing"
                        " (y/N, default: N)? "
                    )
                )
            )
            database_name += "_neutralize"
        else:
            avant = False
            apres = _oui(
                input(
                    "\U0001f4ac " + t("Update all addons (y/N, default: N)? ")
                )
            )

        restore = (
            f"python3 ./script/database/db_restore.py -d {database_name} "
        )
        if neutraliser and db_duplicate.supporte_neutralisation():
            restore += "--neutralize "
        if not cache:
            restore += "--ignore_cache "
        restore += f"--image {file_name}"
        update_all = f"./script/addons/update_addons_all.sh {database_name}"

        commandes = [restore]
        if avant:
            commandes.append(update_all)
        if neutraliser:
            commandes.append(
                f"./script/addons/update_prod_to_dev.sh {database_name}"
            )
        if apres:
            commandes.append(update_all)
        return commandes

    def duplicate_database(self) -> None:
        """Copier une base, et proposer de la neutraliser.

        On passe par `db_duplicate.py`, donc par Odoo, et non par un
        `CREATE DATABASE … TEMPLATE` : lui seul coupe les connexions
        ouvertes sur la source, régénère le `database.uuid`, copie le
        filestore et sait neutraliser pour de bon.

        La neutralisation est proposée par DÉFAUT. Une copie non
        neutralisée d'une base de production garde ses crons actifs, se
        replie sur le `smtp_server` de la configuration quand elle n'a
        aucun serveur de courriel, et garde ses clés de paiement vivantes.
        Le défaut à « oui » est le seul qui protège celui qui appuie sur
        Entrée.
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
            f"python3 ./script/database/db_duplicate.py -s {source} -d {cible}"
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

        cmd = f"./odoo_bin.sh db dump {database_name} --image {backup_name}"
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
        # The script already said why it failed, and wrote no file.
        if status:
            return status, output_path, database_name
        try:
            with zipfile.ZipFile(output_path, "r") as zip_ref:
                zip_ref.getinfo("manifest.json")
            _logger.info(
                f"Backup file '{output_path}' is complete and validated."
            )
        except Exception as e:
            _logger.error(e)
            _logger.error(
                f"Failed to read manifest.json from backup file '{output_path}'."
            )
            status = 1
        return status, output_path, database_name
