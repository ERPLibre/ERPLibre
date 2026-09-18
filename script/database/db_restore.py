#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import configparser
import getpass
import logging
import os
import shutil
import subprocess
import struct
import sys
import tempfile
import uuid
import zipfile
from subprocess import check_output

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.execute.execute import redact_secrets

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


def probe_name():
    """Un nom de base qui ne peut appartenir à personne.

    La sonde DEMANDE une suppression : si le nom désignait une vraie
    base et que le mot de passe était bon, on la perdrait. Un uuid4 rend
    la collision impossible en pratique, et le préfixe dit d'où il vient
    à qui le verrait passer dans un journal.
    """
    return f"el_probe_{uuid.uuid4().hex}"


def probe_master_password(arg_base, mot):
    """(accepté, sortie) — éprouver le mot de passe pour de vrai.

    `--list` ne lit JAMAIS le mot de passe : mesuré,
    `MASTER_PWD="ceci_est_faux" odoo-bin db --list` sort en 0. La sonde
    d'avant acceptait donc le premier mot saisi, juste ou faux, et la
    boucle des dix essais ne servait à rien — le refus n'arrivait qu'au
    `--restore`, une fois la base déjà supprimée.

    Seule l'action `drop` consulte le mot de passe, et elle le fait
    AVANT de regarder la base : `check_super` d'abord, `db_exists`
    ensuite. Sur un nom qui n'existe pas, elle ne touche donc rien et
    répond quand même. Mesuré sur la machine d'essai : mauvais mot de
    passe → code 1 et `AccessDenied` dans la trace ; bon mot de passe →
    code 0, silence, et les huit bases toujours là.

    Le secret passe par l'environnement, jamais par argv :
    /proc/<pid>/cmdline est lisible par tout utilisateur de la machine.
    """
    env = os.environ.copy()
    env["MASTER_PWD"] = mot
    done = subprocess.run(
        f"{arg_base} --drop --database {probe_name()}".split(" "),
        capture_output=True,
        text=True,
        env=env,
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
        accepte, sortie = probe_master_password(arg_base, mot)
        if accepte:
            return mot
        if not password_refused(sortie):
            # Autre chose est cassé : le dire, et ne pas noyer la panne
            # sous dix invites de mot de passe.
            _logger.error(redact_secrets(sortie.strip()[-1500:]))
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


def verify_loaded(database):
    """Une base restaurée porte-t-elle vraiment ses tables ?

    LE SILENCE QUE CE CONTRÔLE ROMPT. Odoo restaure en lançant « psql »
    avec sa sortie JETÉE (« stdout=DEVNULL, stderr=STDOUT »), et « psql »
    rend ZÉRO même quand chaque instruction a échoué — sans
    « ON_ERROR_STOP », une erreur SQL n'est pas un code de retour. Une
    restauration peut donc s'annoncer réussie et laisser une base VIDE.

    Le coût de ce silence n'est pas la base vide, c'est ce qui vient
    après : le clone recopie le vide sans rien dire, puis la première
    commande qui ouvre la copie échoue sur « Database not initialized » —
    un message qui accuse la copie, à trois étapes de la cause.

    Odoo crée d'ailleurs la base AVANT d'extraire : une extraction qui
    échoue laisse elle aussi une base vide derrière elle, que la prochaine
    tentative prendra pour un cache valide.

    Le contrôle est délibérément grossier — l'existence d'une table du
    noyau d'Odoo. Compter les modules ou comparer des chiffres demanderait
    de savoir à quoi ressemble CETTE base ; « elle a des tables » suffit à
    séparer une restauration d'un silence.
    """
    sql = (
        "select count(*) from information_schema.tables"
        " where table_schema = 'public' and table_name = 'ir_module_module'"
    )
    try:
        out = check_output(
            ["psql", "-tAqd", database, "-c", sql], stderr=subprocess.DEVNULL
        ).decode()
    except Exception as erreur:  # noqa: BLE001
        raise SystemExit(
            f"❌ {database} : impossible de vérifier la restauration"
            f" ({erreur})"
        ) from erreur
    if out.strip() != "1":
        raise SystemExit(
            f"❌ {database} a été créée mais elle est VIDE : « psql » a rendu"
            " zéro sans charger le dump. Relancez après avoir regardé la"
            " place disponible ET le quota du dossier temporaire."
        )
    _logger.info(f"## {database} porte bien ses tables ##")


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



def espace_utilisable(chemin):
    """La place qu'on peut VRAIMENT écrire là, quota compris.

    « shutil.disk_usage » rend la place du SYSTÈME DE FICHIERS. Un quota
    par utilisateur est plus bas et ne s'y voit pas : une écriture échoue
    alors sur « Disk quota exceeded » là où « df » annonçait des
    gigaoctets libres. C'est le cas exact d'un « /tmp » en tmpfs monté
    avec « usrquota ».

    LE QUOTA SE LIT PAR « quotactl_fd » ET PAR LUI SEUL sur un système de
    fichiers sans périphérique bloc : l'ancien « quotactl » exige un
    « /dev/... » et rend « Block device required » sur un tmpfs. Les
    outils « quota » ne sont pas toujours installés, et leur absence ne
    dit rien sur la présence d'un quota — celui qui a coûté une soirée
    était posé, actif, et invisible.

    Sans quota, ou si l'appel n'est pas disponible, la place du système de
    fichiers est rendue telle quelle : le pire cas est alors celui d'avant,
    pas un refus de fonctionner.
    """
    libre = shutil.disk_usage(chemin).free
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        buf = ctypes.create_string_buffer(120)
        fd = os.open(chemin, os.O_RDONLY | os.O_DIRECTORY)
        try:
            # 443 = quotactl_fd ; 0x800007 = Q_GETQUOTA ; 0 = USRQUOTA
            code = libc.syscall(443, fd, (0x800007 << 8) | 0, os.getuid(), buf)
        finally:
            os.close(fd)
        if code != 0:
            return libre
        dur, _doux, utilise = struct.unpack("<3Q", buf.raw[:24])
        if not dur:
            return libre
        # La limite est en blocs de 1 Kio, l'usage courant en octets.
        reste = dur * 1024 - utilise
        return max(0, min(libre, reste))
    except Exception:
        return libre


def restore_env(image):
    """L'environnement d'une restauration, dont un temporaire qui TIENT.

    ODOO EXTRAIT DANS UN DOSSIER TEMPORAIRE, pas dans la base : il y écrit
    « dump.sql » ET le filestore entier avant de charger quoi que ce soit.
    Sur une machine où « /tmp » est un tmpfs — quelques gigaoctets de RAM,
    souvent avec un quota par utilisateur —, une image de production n'y
    tient pas, et l'extraction s'arrête sur « Disk quota exceeded » ou sur
    « No space left ». Le message ne nomme ni le tmpfs ni la taille
    manquante : il dit seulement que l'écriture a échoué.

    La place NÉCESSAIRE est lue dans l'archive, décompressée, plutôt
    qu'estimée depuis la taille du zip : un taux de compression varie du
    simple au décuple selon qu'une base porte surtout du texte ou surtout
    des pièces jointes déjà compressées.

    Quand le dossier temporaire par défaut suffit, il est laissé tel quel —
    il est plus rapide, étant en mémoire. Sinon « TMPDIR » désigne un
    dossier voisin du répertoire de données, donc sur le disque qui
    accueillera de toute façon le filestore restauré.
    """
    chemin = os.path.join("image_db", f"{image}.zip")
    if not os.path.exists(chemin):
        return None
    with zipfile.ZipFile(chemin) as archive:
        besoin = sum(
            info.file_size
            for info in archive.infolist()
            if info.filename == "dump.sql"
            or info.filename.startswith("filestore/")
        )
    defaut = tempfile.gettempdir()
    libre = espace_utilisable(defaut)
    # Une marge d'un dixième : l'extraction n'est pas seule à écrire là.
    if libre > besoin * 1.1:
        return None
    repli = os.path.join(os.path.expanduser("~"), ".cache", "erplibre_restore")
    os.makedirs(repli, exist_ok=True)
    _logger.info(
        "## %s demande %.1f Go décompressés, %s n'en laisse écrire que"
        " %.1f (quota compris) : extraction dans %s ##",
        image,
        besoin / 1073741824,
        defaut,
        libre / 1073741824,
        repli,
    )
    env = dict(os.environ)
    env["TMPDIR"] = repli
    return env


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
        print(
            redact_secrets(
                check_output(
                    arg.split(" "), env=restore_env(config.image)
                ).decode()
            )
        )
        verify_loaded(cache_database)
        verify_filestore(cache_database, config.image)

    if config.ignore_cache:
        _logger.info(
            f"## Restoring {config.image} to database {config.database} ##"
        )
        arg = (
            f"{arg_base} --restore --restore_image"
            f" {config.image} --database {config.database}"
        )
        # Ce chemin EXTRAIT, donc il a le même besoin que le cache. Le
        # clone, lui, ne décompresse rien : lui passer cet environnement
        # ferait journaliser une extraction qui n'a pas lieu.
        env = restore_env(config.image)
    else:
        _logger.info(
            f"## Clone cache {cache_database} to database {config.database} ##"
        )
        arg = (
            f"{arg_base} --clone --from_database"
            f" {cache_database} --database {config.database}"
        )
        env = None
    if config.neutralize:
        arg += " --neutralize"
    # Le secret ne traverse plus argv (il est dans MASTER_PWD), mais la
    # commande peut porter d'autres options sensibles : on filtre quand
    # même, le coût est nul et la garantie ne dépend alors d'aucun appelant.
    print(redact_secrets(arg))
    print(redact_secrets(check_output(arg.split(" "), env=env).decode()))
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
            # Dans l'ENVIRONNEMENT, pas dans arg_base : tous les appels
            # suivants sont des enfants de ce processus et en héritent,
            # sans que le secret traverse jamais argv.
            os.environ["MASTER_PWD"] = master_password
        else:
            _logger.info("No master password needed... Continue")

    # Get list of database
    lst_db, lst_db_cache = get_list_db_cache(arg_base)

    if config.clean_cache:
        for db in lst_db_cache:
            _logger.info(f"## Delete {db} ##")
            arg = f"{arg_base} --drop --database {db}"
            out = redact_secrets(check_output(arg.split(" ")).decode())
            print(out)
        lst_db, lst_db_cache = get_list_db_cache(arg_base)

    if config.database:
        cache_database = f"_cache_{config.image}"
        # Drop db
        if config.database in lst_db:
            _logger.info(f"## Drop {config.database} ##")
            arg = f"{arg_base} --drop --database {config.database}"
            out = redact_secrets(check_output(arg.split(" ")).decode())
            print(out)
        if config.only_drop:
            return
        restore_or_clone(config, arg_base, cache_database, lst_db_cache)

    if not config.clean_cache and not config.database:
        print("Nothing to do.")


if __name__ == "__main__":
    main()
