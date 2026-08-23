#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import configparser
import getpass
import logging
import os
import shutil
import sys
import subprocess
from subprocess import check_output

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
DESCRIPTION
    Restore database, use cache to clone to improve speed.

SUGGESTION
    ./script/database/db_restore.py -d test
""",
        epilog="""\
""",
    )
    # parser.add_argument('-d', '--dir', dest="dir", default="./",
    #                     help="Path of repo to change remote, including submodule.")
    parser.add_argument("-d", "--database", help="Database to manipulate.")
    parser.add_argument(
        "--image",
        help=(
            "Image name to restore, from directory image_db, filename without"
            " '.zip'. Example, use odoo12.0_base to use image"
            " odoo12.0_base.zip. Default value is odoo12.0_base"
        ),
    )
    parser.add_argument(
        "--clean_cache",
        action="store_true",
        help="Delete all database cache to clone, begin by _cache_.",
    )
    parser.add_argument(
        "--ignore_cache",
        action="store_true",
        help="Ignore creating _cache_ when restoring.",
    )
    parser.add_argument(
        "--only_drop",
        action="store_true",
        help="Will only drop database if exist.",
    )
    parser.add_argument(
        "--neutralize",
        action="store_true",
        help="Will disable all cron.",
    )
    args = parser.parse_args()
    return args


def get_master_password():
    try:
        # _logger.info("You have 5 seconds to add master password...")
        pa = getpass.getpass(prompt="\nEnter master password... ")
        return pa
    except getpass.GetPassWarning:
        _logger.error("Password echoed, danger!")


# Assez pour une faute de frappe répétée, pas assez pour qu'une boucle
# oubliée tourne toute la nuit devant une invite que personne ne lit.
MAX_ESSAIS_MOT_DE_PASSE = 10


def password_refused(sortie):
    """Odoo a-t-il refusé le mot de passe maître, ou autre chose ?

    La distinction porte tout. Reposer la question sur n'importe quel
    échec cacherait la vraie panne derrière dix invites, et l'on
    chercherait un mot de passe alors que la base est cassée.

    Odoo lève `AccessDenied` — la classe apparaît dans la trace, et son
    message traduit peut varier. On reconnaît donc la CLASSE.
    """
    return "AccessDenied" in (sortie or "")


def probe_master_password(arg_base):
    """(accepté, sortie) — éprouver le mot de passe sur `--list`.

    La commande la plus inoffensive : elle ne touche à rien et rend le
    même refus qu'une restauration. Valider ici évite d'échouer à
    mi-parcours, une fois la base déjà supprimée.
    """
    done = subprocess.run(
        f"{arg_base} --list".split(" "),
        capture_output=True,
        text=True,
    )
    return done.returncode == 0, (done.stdout or "") + (done.stderr or "")


def ask_master_password(arg_base, essais=MAX_ESSAIS_MOT_DE_PASSE):
    """Le mot de passe maître, redemandé tant qu'Odoo le refuse.

    None si l'on renonce — invite vide, essais épuisés, ou panne qui
    n'a rien à voir avec le mot de passe.

    Une faute de frappe arrêtait la migration net, sur une trace
    `CalledProcessError` que rien n'attrapait. Après une heure de
    paliers, c'est cher payé pour une lettre.
    """
    for tour in range(1, essais + 1):
        mot = get_master_password()
        if not mot:
            return None
        candidat = f"{arg_base} --master_password={mot}"
        accepte, sortie = probe_master_password(candidat)
        if accepte:
            return mot
        if not password_refused(sortie):
            # Autre chose est cassé : le dire, et ne pas noyer la panne
            # sous dix invites de mot de passe.
            _logger.error(sortie.strip()[-1500:])
            return None
        restants = essais - tour
        if restants:
            _logger.warning(
                f"Master password refused, {restants} attempt(s) left."
            )
    _logger.error("Master password refused too many times.")
    return None


def get_list_db_cache(arg_base):
    arg = f"{arg_base} --list"
    out = check_output(arg.split(" ")).decode()
    lst_db = out.strip().split("\n")
    lst_db_cache = [a for a in lst_db if a.startswith("_cache_")]
    return lst_db, lst_db_cache


def verify_filestore(database, image):
    """Contrôler qu'une restauration a bien posé ses fichiers.

    Une seule fois, à la restauration d'origine. Après un clone il n'y a
    rien à vérifier : `copytree` recopie la source telle quelle, défauts
    compris — le contrôle appartient à ce qui a créé le défaut, pas à ce
    qui l'a dupliqué.

    Le contrôle n'interrompt pas : la base est restaurée et utilisable,
    c'est la DISPOSITION des fichiers qui est suspecte. Refuser ici
    casserait des chaînes qui marchent, pour un défaut qui se répare
    d'une commande.
    """
    chemin = os.path.join("image_db", f"{image}.zip")
    if not os.path.isfile(chemin):
        return
    try:
        from script.analyse import check_filestore
    except Exception:  # pragma: no cover - l'outil d'analyse est optionnel
        return
    rapport = check_filestore.verify_restore(database, chemin)
    for ligne in check_filestore.render_verify(rapport):
        print(ligne)
    if rapport.get("nested"):
        offer_tidy(check_filestore, rapport)


def offer_tidy(check_filestore, rapport):
    """Proposer de ranger TOUT DE SUITE, là où le défaut naît.

    C'est le seul endroit qui vaille. Le nichage se produit une fois, à
    la restauration, puis le clone le recopie tel quel : mesuré, les six
    bases de la chaîne portaient les mêmes 1168 fichiers. Ranger ici,
    c'est ranger une fois ; ranger plus tard, c'est six fois.

    Rien ne se fait sans réponse humaine, et rien du tout hors d'un
    terminal : ce script tourne aussi sans personne devant, et une
    question posée à un `stdin` fermé arrêterait la migration.
    """
    if not sys.stdin.isatty():
        return
    remonter, doublons = check_filestore.tidy_nested_plan(rapport)
    if not remonter and not doublons:
        return
    print(f"   {len(remonter)} à remonter, {len(doublons)} doublons purs")
    try:
        reponse = input("💬 Ranger maintenant ? (y/N) : ").strip().lower()
    except EOFError:
        return
    if reponse not in ("y", "yes", "o"):
        return
    for source, cible in remonter:
        os.makedirs(os.path.dirname(cible), exist_ok=True)
        shutil.move(source, cible)
    for source, _cible in doublons:
        os.remove(source)
    shutil.rmtree(check_filestore.nested_dir(rapport), ignore_errors=True)
    print(f"✅ {len(remonter)} remontés, {len(doublons)} doublons supprimés.")


def restore_or_clone(config, arg_base, cache_database, lst_db_cache):
    """Restaurer depuis l'image, ou cloner le cache déjà restauré.

    Le contrôle du filestore ne suit QUE les vraies restaurations. Le
    clone recopie sa source telle quelle : contrôler le miroir dirait
    deux fois la même chose, et la seconde au mauvais endroit.
    """
    if cache_database not in lst_db_cache and not config.ignore_cache:
        _logger.info(
            f"## Create cache {cache_database} from image {config.image} ##"
        )
        arg = (
            f"{arg_base} --restore"
            f" --restore_image {config.image} --database {cache_database}"
        )
        print(check_output(arg.split(" ")).decode())
        verify_filestore(cache_database, config.image)

    if config.ignore_cache:
        _logger.info(
            f"## Restoring {config.image} to database {config.database} ##"
        )
        arg = (
            f"{arg_base} --restore --restore_image"
            f" {config.image} --database {config.database}"
        )
    else:
        _logger.info(
            f"## Clone cache {cache_database} to database"
            f" {config.database} ##"
        )
        arg = (
            f"{arg_base} --clone --from_database"
            f" {cache_database} --database {config.database}"
        )
    if config.neutralize:
        arg += " --neutralize"
    print(arg)
    print(check_output(arg.split(" ")).decode())
    if config.ignore_cache:
        verify_filestore(config.database, config.image)


def main():
    config = get_config()

    arg_base = "./odoo_bin.sh db"

    if not config.image:
        with open(".odoo-version", "r") as f:
            odoo_version = f.readline()
            config.image = f"odoo{odoo_version}_base"

    # check if it needs master password from config file
    has_config_file = True
    config_path = "./config.conf"
    if not os.path.isfile(config_path):
        config_path = "/etc/odoo/odoo.conf"
        if not os.path.isfile(config_path):
            has_config_file = False
    if has_config_file:
        config_parser = configparser.ConfigParser()
        config_parser.read(config_path)

        has_admin_password = config_parser.get("options", "admin_passwd")
        if has_admin_password and has_admin_password != "admin":
            master_password = ask_master_password(arg_base)
            if not master_password:
                _logger.error("Missing master password, cancel transaction.")
                sys.exit(1)
            arg_base += f" --master_password={master_password}"
        else:
            _logger.info("No master password needed... Continue")

    # Get list of database
    lst_db, lst_db_cache = get_list_db_cache(arg_base)

    if config.clean_cache:
        for db in lst_db_cache:
            _logger.info(f"## Delete {db} ##")
            arg = f"{arg_base} --drop --database {db}"
            out = check_output(arg.split(" ")).decode()
            print(out)
        lst_db, lst_db_cache = get_list_db_cache(arg_base)

    if config.database:
        cache_database = f"_cache_{config.image}"
        # Drop db
        if config.database in lst_db:
            _logger.info(f"## Drop {config.database} ##")
            arg = f"{arg_base} --drop --database {config.database}"
            out = check_output(arg.split(" ")).decode()
            print(out)
        if config.only_drop:
            return
        restore_or_clone(config, arg_base, cache_database, lst_db_cache)

    if not config.clean_cache and not config.database:
        print("Nothing to do.")


if __name__ == "__main__":
    main()
