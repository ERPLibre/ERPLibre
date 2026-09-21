#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import datetime
import getpass
import logging
import os
import shlex

from script.database import (
    backup_ship,
    backup_verify,
    backup_witness,
    db_restore,
    drill_guard,
)
from script.remote import appliance_ssh, deploy_target
from script.todo.todo_i18n import t

_logger = logging.getLogger(__name__)

try:
    import click

    from script.todo import todo_file_browser
except Exception:
    click = None
    todo_file_browser = None


class DatabaseManager:
    def __init__(self, execute, fill_help_info, image_name=None) -> None:
        self._execute = execute
        self._fill_help_info = fill_help_info
        # CE QUE db_restore ATTEND, composé par le menu qui sait déjà le
        # faire : un NOM sous image_db/, jamais un chemin. Injecté comme
        # `fill_help_info`, parce que le composeur pose une question quand
        # le fichier vient d'ailleurs — et qu'un écran pose les questions.
        # Le repli ne sait que dépouiller, ce qui suffit à un appelant qui
        # ne parcourt rien.
        self._image_name = image_name or self._bare_image_name
        self._dir_path: str | None = None

    @staticmethod
    def _bare_image_name(zip_path: str) -> str:
        """Le nom d'une image, sans son répertoire ni son « .zip »."""
        nom = os.path.basename(zip_path or "")
        return nom[:-4] if nom.endswith(".zip") else nom

    def _on_dir_selected(self, path: str) -> None:
        self._dir_path = path

    def _list_databases(self) -> tuple[bool, list]:
        """(a-t-on pu lire, les bases). DEUX réponses, jamais confondues.

        Zéro base EST une réponse ; une liste illisible n'en est pas une.
        Les rendre par une seule valeur fausse laisse un appelant qui
        détruit conclure « il n'y a rien à écraser » d'un PostgreSQL muet.

        Le code de retour est vérifié : la sortie et l'erreur sont fusionnées
        dans le même flux (`stderr=STDOUT`, execute.py), donc sans lui les
        lignes d'une trace d'appel deviennent des noms de base.
        """
        status, output = self._execute.exec_command_live(
            "./odoo_bin.sh db --list",
            return_status_and_output=True,
            quiet=True,
            source_erplibre=False,
            single_source_erplibre=True,
        )
        if status:
            print(
                f"\u274c {t('Cannot list the databases (exit code): ')}"
                f"{status}"
            )
            print(f"   {t('Is PostgreSQL running?')}")
            for line in output[-5:]:
                print(f"   {line}")
            return False, []
        return True, [a.strip() for a in output if a.strip()]

    def _may_destroy(self, database_name: str) -> bool:
        """Le feu vert avant d'écraser une base. Faux arrête tout.

        LE POINT DE PASSAGE de l'étage interactif. Restaurer DÉTRUIT la
        base cible, dont le nom est du texte libre : la collision était
        imprimée et jamais questionnée.

        Trois réponses, et la troisième est la seule qui demande quelque
        chose. Une base absente n'a rien à protéger. Une base d'exercice —
        drapeau de neutralisation ou compte d'essai — passe, et la ligne
        le DIT : muette, elle ne distingue plus une base reconnue d'une
        base que rien n'a lue. Tout le reste fait retaper le nom, parce que
        recopier oblige à regarder ce qu'on détruit là où « o » se tape par
        réflexe.

        L'étage LOT n'en veut pas : une base fraîchement restaurée n'a ni
        drapeau ni compte d'essai, donc elle se lit réelle, et la garde y
        refuserait les dizaines de cibles make qui recyclent leurs noms.
        """
        lisible, bases = self._list_databases()
        if not lisible:
            # Ne pas savoir n'est pas savoir qu'il n'y a rien.
            print(f"\u274c {t('Nothing is destroyed without reading first.')}")
            return False
        if database_name not in bases:
            return True
        if drill_guard.is_drill_database(database_name):
            print(
                f"\u2139\ufe0f  {t('Drill database: destroying it is safe.')}"
            )
            return True
        print(
            f"\u26a0\ufe0f  {t('This database will be ERASED: ')}"
            f"{database_name}"
        )
        retape = input(
            f"\U0001f4ac {t('Retype its name to confirm: ')}"
        ).strip()
        if retape != database_name:
            print(t("Database deletion cancelled."))
            return False
        return True

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
        lisible, databases = self._list_databases()
        if not lisible:
            return False

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
        # LA MÊME PORTE QUE LA RESTAURATION, et pour la même raison : un
        # « oui » se tape par réflexe, recopier un nom oblige à regarder.
        #
        # L'ÉTAGE LOT était plus sûr que l'unité, ce qui est à rebours :
        # « db_drop_all » consulte le garde d'exercice et REFUSE ce qui ne
        # se prouve pas jetable, pendant qu'effacer UNE base partait sur un
        # « oui ». C'est pourtant le geste le plus destructeur du menu.
        if not self._may_destroy(database_name):
            return
        self._execute.exec_command_live(
            f"./odoo_bin.sh db --drop --database {database_name}",
            source_erplibre=False,
            single_source_erplibre=True,
        )

    def _ask_image_name(self) -> str:
        """Le nom d'image à restaurer, ou "" si on renonce.

        UN SEUL PRODUCTEUR pour les deux branches. « [1] » promettait un
        nom de fichier et n'en demandait aucun — elle visait donc toujours
        image_db/1.zip. Le navigateur, lui, rendait un basename portant
        « .zip », là où `image_path` en rajoute un.

        Le zip est cherché AVANT de bâtir la moindre commande : son absence
        se découvrait sur la machine, après le lancement.
        """
        path_image_db = os.path.join(os.getcwd(), "image_db")
        print("[1] By filename from image_db")
        print(f"[] Browser image_db {path_image_db}")
        if input("\U0001f4ac Select : ") == "1":
            nom = input(f"\U0001f4ac {t('Image name (no .zip): ')}").strip()
        else:
            self.open_file_image_db()
            nom = self._image_name(self._dir_path or "")
        if not nom:
            print(t("Cancelled."))
            return ""
        chemin = db_restore.image_path(nom)
        if not os.path.isfile(chemin):
            print(f"\u274c {t('Image not found: ')}{chemin}")
            return ""
        return nom

    def restore_from_database(self, show_remote_list: bool = True) -> None:
        """Restaure une image dans une base, et LIT ce qu'elle lance.

        Le code de retour était capturé puis écrasé par la question
        suivante : une seule variable portait le choix de menu, deux
        réponses oui/non et trois codes de sortie. La chaîne continuait
        donc sur une base que la restauration venait d'échouer à créer,
        et proposait d'y mettre à jour tous les modules.

        Les deux noms sont CITÉS : ils traversent un f-string exécuté par
        bash, où un point-virgule tapé au clavier ouvre une commande.
        """
        file_name = self._ask_image_name()
        if not file_name:
            return

        default_database_name = file_name.replace(" ", "_")
        database_name = input(
            f"\U0001f4ac {t('Database name (default=')}"
            f"{default_database_name}) : "
        ).strip()
        if not database_name:
            database_name = default_database_name

        neutralise = (
            input(f"\U0001f4ac {t('Neutralize the database (Y/n)? ')}")
            .strip()
            .lower()
        )
        more_arg = ""
        if neutralise != "n":
            more_arg = "--neutralize "
            database_name += "_neutralize"

        if not self._may_destroy(database_name):
            return

        status, _ = self._execute.exec_command_live(
            f"python3 ./script/database/db_restore.py "
            f"-d {shlex.quote(database_name)} "
            f"{more_arg}--ignore_cache --image {shlex.quote(file_name)}",
            return_status_and_output=True,
            single_source_erplibre=True,
            source_erplibre=False,
        )
        if status:
            print(f"\u274c {t('The restore failed.')}")
            return
        # SUR LE DRAPEAU, et non sur `status` : l'un dit qu'on a demandé la
        # neutralisation, l'autre si la commande d'avant a réussi.
        if more_arg:
            status, _ = self._execute.exec_command_live(
                f"./script/addons/update_prod_to_dev.sh "
                f"{shlex.quote(database_name)}",
                return_status_and_output=True,
                single_source_erplibre=True,
                source_erplibre=False,
            )
            if status:
                print(
                    f"\u26a0  {t('update_prod_to_dev did not finish: do not')}"
                    f" {t('count on the test/test account.')}"
                )
                return
        answer = (
            input(
                f"\U0001f4ac {t('Would you like to update all addons (y/N)? ')}"
            )
            .strip()
            .lower()
        )
        if answer == "y":
            self._execute.exec_command_live(
                f"./script/addons/update_addons_all.sh "
                f"{shlex.quote(database_name)}",
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

        La neutralisation est proposée par DÉFAUT. Une copie qui ne l'est
        pas garde les tâches planifiées actives, aucun serveur de courriel
        — donc le repli sur le `smtp_server` de la configuration — et les
        clés de paiement vivantes : elle envoie et encaisse pour de vrai.
        Le défaut à « oui » est le seul qui protège celui qui appuie sur
        Entrée.
        """
        source = self.select_database()
        if not source:
            return
        # LA NEUTRALISATION SE DEMANDE D'ABORD, parce qu'elle décide de ce
        # que le nom a le droit d'annoncer. Posée après, elle laissait
        # « <source>_neutralize » comme défaut à qui allait la décliner :
        # taper Entrée puis « n » rendait une base au nom rassurant qui
        # garde ses tâches planifiées, son repli SMTP et ses clés de
        # paiement vivantes.
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
        defaut = f"{source}_neutralize" if neutraliser else f"{source}_copy"
        cible = input(
            f"\U0001f4ac {t('Name of the copy (default=')}{defaut}) : "
        ).strip()
        cible = cible or defaut
        # UN NOM CHOISI À LA MAIN N'EST PAS REFUSÉ, mais s'il annonce une
        # neutralisation qui n'a pas lieu, le taire laisse la base mentir à
        # qui la relira dans six mois — et le nom ne trompe pas que l'œil :
        # le test de fumée en tirait son verdict avant de s'authentifier.
        if not neutraliser and "neutralize" in cible.lower():
            print(f"⚠️  {t('This name says neutralized, and it is not.')}")

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

    # Le répertoire des images du dépôt. Nommé ici parce que deux
    # méthodes le cherchent, et qu'une seconde composition diverge le jour
    # où il change de nom.
    IMAGE_DIR = "image_db"

    @classmethod
    def backup_archive(cls, backup_name, exists=os.path.isfile) -> str:
        """Le chemin de l'archive produite, ou "" si on ne la trouve pas.

        "" NE VEUT PAS DIRE « absente », et les confondre ferait annoncer
        une sauvegarde manquante là où elle est peut-être parfaite. Le nom
        est résolu par `odoo-bin`, dont le code ne vit pas dans ce dépôt :
        ne pas trouver le fichier dit qu'on ne sait pas où il est.

        DEUX FORMES SONT CHERCHÉES parce que deux ont cours : l'option
        `--restore_image` est documentée « nom sans .zip », et l'écran
        propose un nom qui porte déjà le sien. Chercher les deux vaut
        mieux que parier sur celle qui a résolu.

        `exists` est injectable : la décision se vérifie sans poser un
        fichier sur le disque.
        """
        for candidat in (backup_name, f"{backup_name}.zip"):
            chemin = os.path.join(cls.IMAGE_DIR, candidat)
            if exists(chemin):
                return chemin
        return ""

    @staticmethod
    def verify_and_witness(path: str, label: str = ""):
        """Relit la sauvegarde, DIT jusqu'où, et fait survivre le constat.

        Un vérificateur ne dit que ce qu'il voit à l'instant où on le
        lance, et personne ne le relance avant d'en avoir besoin. Le
        témoin est ce qui permet de répondre « la dernière fois qu'on a
        regardé, c'était il y a trois semaines » — une réponse que ni le
        fichier ni le vérificateur ne portent. Il était écrit, éprouvé, et
        appelé par personne.

        Le constat est un PLUS : ne pas pouvoir l'écrire ne doit pas
        emporter une sauvegarde qui, elle, est faite. D'où le refus
        DIT plutôt que levé.
        """
        if not path:
            print(
                "ℹ️  "
                f"{t('Archive not found where expected; not verified: ')}"
                f"{label}"
            )
            return None
        constat = backup_verify.verify(path)
        if constat.verdict == backup_verify.SOUND:
            _logger.info(f"'{path}' : {', '.join(constat.checks)}.")
        else:
            _logger.error(
                f"'{path}' : {constat.verdict}"
                f" ({', '.join(constat.checks) or t('nothing checked')})."
            )
        try:
            backup_witness.record(constat)
        except Exception as souci:  # noqa: BLE001 - un constat, pas le sujet
            print(f"ℹ️  {t('Finding not recorded: ')}{souci}")
        return constat

    def _backup_ship(self, constat, path, name) -> None:
        """Dépose la sauvegarde chez la cible, ou DIT qu'il n'y en a pas.

        LE CROCHET ÉTAIT PLANTÉ, ET VIDE. « backup-target » est dans le
        socle des destinations de sortie, avec son port et sa raison — « la
        cible des sauvegardes, l'ouvrir en sortie est ce qui permet de
        sauvegarder sans monter le disque de la machine sur l'hôte » — et
        rien ne le remplissait : le pare-feu d'une machine confinée ouvrait
        cette porte sur le vide.

        Une archive qui n'a pas passé les contrôles ICI ne part pas : en
        déposer ailleurs une qu'on sait abîmée remplirait la cible de
        copies inutilisables, et ferait croire à une sauvegarde.
        """
        if not constat or constat.verdict != backup_verify.SOUND:
            return
        cibles = [
            cible
            for cible in deploy_target.load_all()
            if cible.get("kind") == deploy_target.KIND_BACKUP
        ]
        if not cibles:
            # UNE FOIS, et en nommant où la créer. Se taire ferait qu'une
            # sauvegarde qui ne part nulle part ne se distingue plus d'une
            # sauvegarde qui part.
            print(f"\u2139\ufe0f  {t('No backup target is configured.')}")
            print(f"   {t('Create one in:')} {t('Deployment targets')}")
            return
        cible = deploy_target.with_defaults(cibles[0])
        depot = backup_ship.ship(
            cible,
            deploy_target.fiche(cible),
            path,
            name,
            run=appliance_ssh.run,
        )
        marque = "✅" if depot.verdict == backup_ship.SHIPPED else "⚠️"
        print(f"{marque}  {cible['name']} : {depot.verdict} {depot.detail}")

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
        status, _output_lines = self._execute.exec_command_live(
            cmd,
            return_status_and_output=True,
            single_source_erplibre=True,
            source_erplibre=False,
        )
        # LE CODE DE RETOUR ÉTAIT JETÉ. Une sauvegarde qui échoue rendait
        # donc exactement le même écran qu'une sauvegarde réussie, et
        # relire une archive qui n'a pas été écrite dirait « absente »
        # pour la mauvaise raison.
        if status:
            print(
                f"❌ {t('The backup command failed; nothing was verified: ')}"
                f"{backup_name}"
            )
            return
        archive = self.backup_archive(backup_name)
        constat = self.verify_and_witness(archive, backup_name)
        # ET AILLEURS. Une sauvegarde qui ne vit que sur la machine qui l'a
        # produite n'en est pas une : le 3-2-1 reste à une copie, un
        # support, zéro hors-site tant que rien ne la déplace.
        self._backup_ship(constat, archive, backup_name)

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
        # LE FICHIER QUI VIENT D'ÊTRE ÉCRIT, et non celui du défaut : quand
        # l'opérateur choisit un autre chemin, la relecture portait sur une
        # sauvegarde d'avant — ou sur rien — et l'écran annonçait quand même
        # « validée ».
        #
        # Et le manifeste ne prouve rien : il manque légitimement aux
        # sauvegardes produites ailleurs, tandis que le dump, lui, est la
        # seule pièce indispensable. Le contrôle dit désormais JUSQU'OÙ il
        # est allé, ce qui n'est pas la même chose que « validée ».
        self.verify_and_witness(output_path, output_path)
        return status, output_path, database_name
