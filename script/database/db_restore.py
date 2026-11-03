#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import configparser
import fcntl
import getpass
import logging
import mmap
import os
import posixpath
import re
import shlex
import shutil
import struct
import subprocess
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

    `list` ne lit JAMAIS le mot de passe : `odoo_bin.sh db list` sort
    en 0 avec un mot de passe faux. Une sonde par `list` accepterait
    donc n'importe quel mot, et le refus n'arriverait qu'au `load`,
    une fois la base déjà supprimée.

    Seule l'action `drop` consulte le mot de passe, et elle le fait
    AVANT de regarder la base : `check_super` d'abord, l'existence
    ensuite. Avec `--if-exists`, sur un nom qui n'existe pas, elle ne
    touche donc rien et répond quand même : mauvais mot de passe → code 1
    et `AccessDenied` dans la sortie ; bon mot de passe → code 0, sans
    rien supprimer.

    Le secret passe par l'environnement, jamais par argv :
    /proc/<pid>/cmdline est lisible par tout utilisateur de la machine.
    """
    env = os.environ.copy()
    env["MASTER_PWD"] = mot
    done = subprocess.run(
        f"{arg_base} drop --if-exists {probe_name()}".split(" "),
        capture_output=True,
        text=True,
        env=env,
    )
    return done.returncode == 0, (done.stdout or "") + (done.stderr or "")


def ask_master_password(arg_base, essais=MAX_ESSAIS_MOT_DE_PASSE):
    """Le mot de passe maître, redemandé tant qu'Odoo le refuse.

    None si l'on renonce — invite vide, essais épuisés, ou panne qui
    n'a rien à voir avec le mot de passe.

    Sans cette boucle, une faute de frappe arrête la migration net, sur
    une trace `CalledProcessError` que rien n'attrape, parfois après une
    heure de paliers.
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
    arg = f"{arg_base} list"
    out = check_output(arg.split(" ")).decode()
    lst_db = out.strip().split("\n")
    lst_db_cache = [a for a in lst_db if a.startswith("_cache_")]
    return lst_db, lst_db_cache


def chemin_config():
    """Le fichier de configuration qu'« odoo_bin.sh » fait lire à Odoo.

    Même ordre que « odoo_rc_resolve » (« script/lib_odoo_rc.sh ») : un
    « ODOO_RC » posé l'emporte, puis « ./config.conf », puis
    « /etc/odoo/odoo.conf ». None quand aucun n'existe.
    """
    if os.environ.get("ODOO_RC"):
        candidats = [os.environ["ODOO_RC"]]
    else:
        candidats = ["./config.conf", "/etc/odoo/odoo.conf"]
    for candidat in candidats:
        if os.path.isfile(candidat):
            return candidat
    return None


def environnement_pg(database):
    """L'environnement qui connecte « psql » à `database` comme Odoo.

    Reprend « exec_pg_environ » d'Odoo : « db_host », « db_port »,
    « db_user » et « db_password » de la configuration deviennent
    PGHOST, PGPORT, PGUSER et PGPASSWORD quand ils portent une valeur —
    Odoo écrit « False » pour une option laissée vide. Sans eux, « psql »
    prend les valeurs par défaut de libpq : un autre serveur, ou un autre
    rôle, que celui où Odoo vient de restaurer.

    La base passe par PGDATABASE et non par « -d » : libpq lit un « -d »
    qui contient « = » comme une chaîne de connexion entière, alors que
    PGDATABASE reste un nom.
    """
    env = dict(os.environ)
    chemin = chemin_config()
    if chemin:
        lecteur = configparser.RawConfigParser()
        try:
            lecteur.read(chemin)
        except configparser.Error:
            lecteur = None
        for option, variable in (
            ("db_host", "PGHOST"),
            ("db_port", "PGPORT"),
            ("db_user", "PGUSER"),
            ("db_password", "PGPASSWORD"),
        ):
            valeur = ""
            if lecteur is not None:
                valeur = lecteur.get("options", option, fallback="").strip()
            if valeur and valeur != "False":
                env[variable] = valeur
    env["PGDATABASE"] = database
    return env


def interroger(database, sql, **variables):
    """La réponse de « psql » à `sql` sur `database`, ou None sans réponse.

    `sql` passe par l'entrée standard : « psql » n'interpole ses variables
    (« :'nom' ») que là, jamais dans un « -c ». Une valeur venue d'un nom
    de base passe ainsi en variable, citée par « psql », et jamais collée
    dans la requête. « -w » interdit toute invite de mot de passe : sans
    terminal, une invite bloquerait le script ; « -X » écarte le
    « ~/.psqlrc » de qui lance, dont la sortie fausserait la réponse.
    """
    commande = ["psql", "-XtAqw", "-v", "ON_ERROR_STOP=1"]
    for nom, valeur in variables.items():
        commande += ["-v", f"{nom}={valeur}"]
    try:
        out = check_output(
            commande,
            input=sql.encode(),
            env=environnement_pg(database),
            stderr=subprocess.DEVNULL,
        )
    except Exception as erreur:  # noqa: BLE001
        _logger.error(f"{database} : « psql » ne répond pas ({erreur})")
        return None
    return out.decode().strip()


def est_chargee(database):
    """Une base porte-t-elle vraiment ses tables ? True, False, ou None.

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
    échoue, ou qu'on interrompt, laisse elle aussi une base vide derrière
    elle. Le même contrôle sert donc deux fois — après une restauration,
    et avant de cloner un cache qu'un passage précédent a pu laisser vide.

    Le contrôle est délibérément grossier — l'existence d'une table du
    noyau d'Odoo. Compter les modules ou comparer des chiffres demanderait
    de savoir à quoi ressemble CETTE base ; « elle a des tables » suffit à
    séparer une restauration d'un silence. « to_regclass » la trouve quels
    que soient les droits du rôle connecté, là où « information_schema »
    ne montre que les tables sur lesquelles il a un privilège.

    None quand « psql » ne répond pas : l'état est alors INCONNU, et aucun
    appelant ne le prend pour un vide — on ne supprime pas une base sur
    une question restée sans réponse.
    """
    reponse = interroger(
        database, "select to_regclass('public.ir_module_module') is not null"
    )
    if reponse is None:
        return None
    return reponse == "t"


def base_existe(database):
    """La base existe-t-elle dans PostgreSQL ? True, False, ou None.

    Lu dans « pg_database », que tout rôle peut lire, et non dans la liste
    d'Odoo : celle-ci ne montre que les bases du rôle d'Odoo, et sa
    commande « drop » peut sortir en zéro sans rien faire sur un nom
    qu'elle ne liste pas. Seul ce contrôle dit si une base a vraiment disparu.

    None quand « psql » ne répond pas.
    """
    reponse = interroger(
        "postgres",
        "select count(*) from pg_database where datname = :'nom'",
        nom=database,
    )
    if reponse is None:
        return None
    return reponse == "1"


def chemin_image(image):
    """Le chemin de l'archive de `image`, construit comme Odoo le construit.

    « cli/db.py » n'ajoute « .zip » que si le nom ne le porte pas déjà :
    « --image x » et « --image x.zip » désignent la même archive. Ce qui
    lit l'archive ici doit suivre la même règle, sinon il cherche
    « x.zip.zip » et conclut à une image absente qu'Odoo, lui, restaure.
    """
    nom = image if image.endswith(".zip") else f"{image}.zip"
    return os.path.join("image_db", nom)


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
    chemin = chemin_image(image)
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
    la restauration, puis le clone le recopie tel quel : chaque base d'une
    chaîne de clones porte les mêmes fichiers nichés. Ranger ici, c'est
    ranger une fois ; ranger plus tard, c'est autant de fois qu'il y a de
    copies.

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


GIO = 1073741824

# La page d'un tmpfs : chaque fichier y occupe un nombre ENTIER de pages,
# et c'est ce nombre que le quota compte — un fichier d'un octet en coûte
# une page entière, 4 Kio sur x86-64. Un filestore fait de centaines de
# milliers de petites pièces jointes pèse ainsi en tmpfs bien plus que la
# somme de ses tailles.
PAGE = mmap.PAGESIZE

# Ce que coûte en mémoire noyau une entrée d'un tmpfs, fichier ou dossier :
# son inode et sa dentrée, de l'ordre d'un kilooctet. Le quota ne le compte
# pas — un dossier ou un fichier vide n'y pèse rien —, la mémoire vive si.
# Le compter dans le besoin sert la décision mémoire, et donne au quota une
# marge qui grandit avec le nombre de fichiers.
SURCOUT_ENTREE = 1024

# La marge au-dessus du besoin calculé. D'autres processus écrivent dans le
# même temporaire pendant l'extraction, sans qu'on puisse le prévoir : une
# marge proportionnelle seule est trop mince pour une petite image, une
# marge fixe seule trop mince pour une grande. Les deux s'additionnent.
MARGE_PROPORTION = 0.25
MARGE_FIXE = 256 * 1048576

# Au-delà de ce besoin, une extraction quitte un temporaire en mémoire
# même quand elle y tiendrait — voir « raison_d_extraire_ailleurs ».
SEUIL_TMPFS = GIO
FRACTION_MEMOIRE = 4

# Les systèmes de fichiers dont les pages SONT de la mémoire vive.
FS_EN_MEMOIRE = ("tmpfs", "ramfs")


def quota_restant(chemin):
    """Les octets que le quota de l'utilisateur laisse écrire là, ou None.

    « shutil.disk_usage » rend la place du SYSTÈME DE FICHIERS. Un quota
    par utilisateur est plus bas et ne s'y voit pas : une écriture échoue
    alors sur « Disk quota exceeded » là où « df » annonçait des
    gigaoctets libres. C'est le cas exact d'un « /tmp » en tmpfs monté
    avec « usrquota ».

    LE QUOTA SE LIT PAR « quotactl_fd » ET PAR LUI SEUL sur un système de
    fichiers sans périphérique bloc : l'ancien « quotactl » exige un
    « /dev/... » et rend « Block device required » sur un tmpfs. Les
    outils « quota » ne sont pas toujours installés, et leur absence ne
    dit rien sur la présence d'un quota : il peut être posé, actif, et
    invisible à qui ne l'interroge pas par cet appel.

    None sans quota, ou si l'appel n'est pas disponible : l'appelant s'en
    tient alors à la place du système de fichiers, ce qui ne refuse rien.
    """
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
            return None
        # « struct if_dqblk » du noyau : trois u64 en tête, dans l'ordre
        # d'octets de la machine.
        dur, _doux, utilise = struct.unpack("=3Q", buf.raw[:24])
        if not dur:
            return None
        # La limite est en blocs de 1 Kio, l'usage courant en octets.
        return max(0, dur * 1024 - utilise)
    except Exception:
        return None


def espace_utilisable(chemin):
    """La place qu'on peut VRAIMENT écrire là, quota compris."""
    libre = shutil.disk_usage(chemin).free
    quota = quota_restant(chemin)
    return libre if quota is None else min(libre, quota)


def inodes_libres(chemin):
    """Les entrées qu'on peut encore créer là, ou None si rien ne les borne.

    Un tmpfs a un nombre d'inodes fixé au montage (« nr_inodes ») : un
    filestore d'un million de fichiers l'épuise, et l'extraction s'arrête
    sur « No space left on device » alors que la place en octets suffit.
    Un système de fichiers qui alloue ses inodes à la demande annonce
    zéro inode au total ; il n'y a alors rien à compter.
    """
    try:
        etat = os.statvfs(chemin)
    except OSError:
        return None
    if not etat.f_files:
        return None
    return etat.f_favail


def type_systeme_fichiers(chemin, mounts="/proc/mounts"):
    """Le type du système de fichiers qui porte `chemin`, ou None.

    Le point de montage retenu est le plus long qui préfixe le chemin réel ;
    à longueur égale, le dernier listé, car un montage posé par-dessus un
    autre au même endroit le masque. « /proc/mounts » écrit l'espace et
    quelques autres caractères en octal (« \\040 ») : ils sont décodés.
    """
    try:
        with open(mounts) as fichier:
            lignes = fichier.read().splitlines()
    except OSError:
        return None
    reel = os.path.realpath(chemin)
    meilleur, trouve = None, None
    for ligne in lignes:
        champs = ligne.split()
        if len(champs) < 3:
            continue
        point = re.sub(
            r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), champs[1]
        )
        dedans = point == "/" or reel == point or reel.startswith(point + "/")
        if dedans and (meilleur is None or len(point) >= len(meilleur)):
            meilleur, trouve = point, champs[2]
    return trouve


def memoire_disponible(meminfo="/proc/meminfo"):
    """« MemAvailable » en octets, ou None si le noyau ne la donne pas."""
    try:
        with open(meminfo) as fichier:
            for ligne in fichier:
                if ligne.startswith("MemAvailable:"):
                    return int(ligne.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def membres_extraits(chemin_zip):
    """(nom, taille décompressée) de ce qu'Odoo extrait d'une image.

    Le filtre est celui de « restore_db » : « dump.sql » et ce qui est sous
    « filestore/ », rien d'autre — le manifeste n'est jamais écrit.
    """
    with zipfile.ZipFile(chemin_zip) as archive:
        return [
            (info.filename, info.file_size)
            for info in archive.infolist()
            if info.filename == "dump.sql"
            or info.filename.startswith("filestore/")
        ]


def besoin_extraction(membres, page=PAGE, surcout=SURCOUT_ENTREE):
    """(octets, entrées) que coûte l'extraction de `membres` sur un tmpfs.

    `membres` : couples (nom, taille décompressée), noms d'archive à « / ».
    Chaque fichier compte en pages entières ; chaque fichier ET chaque
    dossier ajoute `surcout`. Les dossiers sont déduits des chemins : une
    archive zip ne liste pas toujours les siens, et l'extraction les crée
    quand même.

    La somme brute des tailles sous-estime : un filestore est surtout fait
    de petites pièces jointes, dont chacune occupe au moins une page.
    """
    octets = 0
    fichiers = 0
    dossiers = set()
    for nom, taille in membres:
        if nom.endswith("/"):
            dossiers.add(nom.rstrip("/"))
            continue
        fichiers += 1
        octets += -(-taille // page) * page
        parent = posixpath.dirname(nom)
        while parent:
            dossiers.add(parent)
            parent = posixpath.dirname(parent)
    entrees = fichiers + len(dossiers)
    return octets + entrees * surcout, entrees


def avec_marge(besoin):
    """Le besoin, augmenté de la marge proportionnelle et de la fixe."""
    return int(besoin * (1 + MARGE_PROPORTION)) + MARGE_FIXE


def seuil_tmpfs(memoire):
    """Le besoin au-delà duquel une extraction quitte un tmpfs.

    Le plus bas de « SEUIL_TMPFS » et d'une fraction de la mémoire
    disponible : sur une petite machine, le quart de ce qui reste libre
    est atteint bien avant un gigaoctet.
    """
    if not memoire:
        return SEUIL_TMPFS
    return min(SEUIL_TMPFS, memoire // FRACTION_MEMOIRE)


def raison_d_extraire_ailleurs(
    besoin, entrees, fstype, memoire, libre_fs, quota, inodes
):
    """(code, explication) si le temporaire par défaut ne convient pas.

    None quand il convient. Les codes, dans l'ordre où ils sont éprouvés :

    « tmpfs » — le temporaire est en mémoire vive et le besoin dépasse
    « seuil_tmpfs ». Ce choix ne dépend pas de la place libre : un tmpfs
    EST de la RAM. Pendant que l'extraction l'occupe, PostgreSQL charge le
    dump et remplit son cache, Odoo construit son registre ; sans swap,
    rien ne peut être évincé, et ce qui manque se paie en processus tués
    par le noyau plutôt qu'en un message. Sur disque, l'extraction ne
    coûte qu'une écriture séquentielle, lue une fois par « psql » : pour
    une grosse image, le gain du tmpfs ne vaut pas ce risque. Une petite
    image, comme une image de base, y reste, et profite de sa vitesse.

    « quota » — le quota de l'utilisateur, plus bas que la place libre,
    ne laisse pas écrire le besoin augmenté de sa marge.

    « place » — le système de fichiers lui-même n'a pas cette place.

    « inodes » — le nombre d'entrées à créer dépasse celles qui restent.
    """
    if fstype in FS_EN_MEMOIRE and besoin > seuil_tmpfs(memoire):
        return (
            "tmpfs",
            f"{fstype} en mémoire vive, {besoin / GIO:.2f} Gio à extraire"
            f" au-delà du seuil de {seuil_tmpfs(memoire) / GIO:.2f} Gio",
        )
    voulu = avec_marge(besoin)
    if quota is not None and quota < libre_fs and quota < voulu:
        return (
            "quota",
            f"le quota n'y laisse écrire que {quota / GIO:.2f} Gio pour"
            f" {voulu / GIO:.2f} Gio marge comprise",
        )
    if libre_fs < voulu:
        return (
            "place",
            f"{libre_fs / GIO:.2f} Gio libres pour {voulu / GIO:.2f} Gio"
            " marge comprise",
        )
    if inodes is not None and inodes < entrees + entrees // 10 + 1000:
        return (
            "inodes",
            f"{inodes} inodes libres pour {entrees} fichiers et dossiers",
        )
    return None


def dossier_travail():
    """Le dossier de ce script dans le répertoire personnel, sur disque.

    Il reçoit l'extraction quand le temporaire par défaut ne convient pas,
    et les verrous qui ordonnent les passages simultanés. Il est par
    utilisateur et non par dépôt : deux dépôts du même utilisateur parlent
    souvent au même serveur PostgreSQL, et donc aux mêmes caches.

    « erplibre_restore » dans le cache de l'utilisateur :
    « $XDG_CACHE_HOME », « ~/.cache » à défaut.
    """
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    return os.path.join(cache, "erplibre_restore")


class Verrou:
    """Un verrou « flock » par nom de base, que tous les passages partagent.

    LA LISTE DES BASES NE VAUT QUE SOUS CE VERROU. « echec_restauration »
    supprime une base que la liste ne montrait pas avant la restauration,
    et « cache_utilisable » un cache qu'elle montre sans tables. Deux
    passages simultanés sur la même image cassent ces deux lectures : un
    passage lit la liste pendant qu'un autre crée le cache, puis supprime
    un cache en cours de chargement qu'il prend pour le sien ou pour un
    reste. Le verrou fait de la liste un état que personne ne change
    entre la lecture et l'action.

    Deux modes, par « prendre » :

    - partagé, pour lire la liste et cloner : des clones simultanés d'un
      même cache ne se gênent pas ;
    - exclusif, pour supprimer ou restaurer : il attend la fin de tout
      clone en cours, et aucun clone ne commence avant sa fin.

    Passer d'un mode à l'autre RELÂCHE d'abord le verrou (« flock » ne
    convertit pas atomiquement) : ce qui a été lu avant se relit après.
    Le verrou tombe à la fermeture du fichier, y compris quand le
    processus meurt — un passage tué ne bloque pas les suivants.

    Le verrou ne protège que des passages de ce script. Une base créée au
    même nom par un autre outil, entre la liste et la restauration, reste
    hors de sa portée.
    """

    def __init__(self, database):
        dossier = os.path.join(dossier_travail(), "verrous")
        os.makedirs(dossier, exist_ok=True)
        self.database = database
        self.chemin = os.path.join(
            dossier, database.replace(os.sep, "_") + ".lock"
        )
        self.fichier = None

    def __enter__(self):
        self.fichier = open(self.chemin, "a")
        return self

    def __exit__(self, *_exc):
        self.fichier.close()

    def prendre(self, exclusif):
        """Prendre le verrou dans ce mode ; dire qu'on attend, s'il le faut."""
        mode = fcntl.LOCK_EX if exclusif else fcntl.LOCK_SH
        try:
            fcntl.flock(self.fichier, mode | fcntl.LOCK_NB)
        except BlockingIOError:
            _logger.info(
                f"## {self.database} : un autre passage la restaure ou la"
                " clone, attente ##"
            )
            fcntl.flock(self.fichier, mode)


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
    des pièces jointes déjà compressées. Elle est comptée comme un tmpfs
    la compte — voir « besoin_extraction ».

    Quand le dossier temporaire par défaut convient, il est laissé tel
    quel. Sinon — « raison_d_extraire_ailleurs » dit pourquoi, et le
    journal le répète — « TMPDIR » désigne « dossier_travail », sur le
    disque de l'utilisateur, hors mémoire vive — sauf s'il n'a ni la place
    voulue ni autant de place que le défaut, qui reste alors, avec un
    avertissement. Le déplacement final du
    filestore vers le répertoire de données n'y est un simple renommage
    que si les deux partagent un système de fichiers ; sinon c'est une
    copie, plus lente, sans autre conséquence.

    None aussi quand l'archive est absente ou illisible, avec un
    avertissement : c'est à la restauration de dire l'erreur, avec son
    propre message, pas à ce calcul de l'empêcher.
    """
    chemin = chemin_image(image)
    if not os.path.exists(chemin):
        _logger.warning(
            f"## {chemin} introuvable : extraction laissée dans"
            f" {tempfile.gettempdir()}, sans contrôle de place ##"
        )
        return None
    try:
        besoin, entrees = besoin_extraction(membres_extraits(chemin))
    except (zipfile.BadZipFile, OSError) as erreur:
        _logger.warning(f"## {chemin} illisible comme zip ({erreur}) ##")
        return None
    defaut = tempfile.gettempdir()
    raison = raison_d_extraire_ailleurs(
        besoin,
        entrees,
        type_systeme_fichiers(defaut),
        memoire_disponible(),
        shutil.disk_usage(defaut).free,
        quota_restant(defaut),
        inodes_libres(defaut),
    )
    if raison is None:
        return None
    repli = dossier_travail()
    os.makedirs(repli, exist_ok=True)
    code, explication = raison
    voulu = avec_marge(besoin)
    place_repli = espace_utilisable(repli)
    # Un repli trop petit n'est pris que s'il a au moins la place du
    # défaut : sinon l'extraction y échouerait plus tôt encore. Les inodes
    # font exception, la place en octets ne dit rien de leur manque.
    if (
        place_repli < voulu
        and code != "inodes"
        and place_repli < espace_utilisable(defaut)
    ):
        _logger.warning(
            f"## {image} : {defaut} ne convient pas ({code}) — {explication}."
            f" {repli} n'a que {place_repli / GIO:.2f} Gio pour"
            f" {voulu / GIO:.2f} voulus, moins que {defaut} : l'extraction"
            f" reste dans {defaut}, sans garantie d'y tenir ##"
        )
        return None
    _logger.info(
        f"## {image} : {defaut} écarté ({code}) — {explication}."
        f" Extraction dans {repli} ##"
    )
    if place_repli < voulu:
        _logger.warning(
            f"## {repli} n'a pas non plus {voulu / GIO:.2f} Gio"
            " libres : l'extraction risque d'y échouer aussi ##"
        )
    env = dict(os.environ)
    env["TMPDIR"] = repli
    return env


def drop_database(arg_base, database):
    """Supprimer une base par « odoo_bin.sh db drop », sortie filtrée.

    Pour une base que la liste d'Odoo vient de montrer : un échec y est
    inattendu, et lève « CalledProcessError » au lieu d'être rapporté.
    """
    arg = f"{arg_base} drop {database}"
    print(redact_secrets(check_output(arg.split(" ")).decode()))


def bases_existantes(arg_base):
    """Les bases que la commande « db » d'Odoo liste en ce moment."""
    return get_list_db_cache(arg_base)[0]


def supprimer_base(arg_base, database):
    """Supprimer `database` et son filestore ; True si la commande réussit.

    Par la commande « db drop » d'Odoo et non par « dropdb » : elle
    retire aussi le filestore, que PostgreSQL ne connaît pas. « --if-exists »
    lui fait accepter un nom qui n'existe pas sans rien faire : l'appelant
    peut ne pas savoir si la base a été créée.

    Elle sort aussi en zéro sans rien faire sur une base qu'Odoo ne liste
    pas, par exemple celle d'un autre rôle : True dit que la commande a
    réussi, pas que la base a disparu — « base_existe » le dit.
    """
    fait = subprocess.run(
        f"{arg_base} drop --if-exists {database}".split(" "),
        capture_output=True,
        text=True,
    )
    if fait.returncode != 0:
        sortie = (fait.stdout or "") + (fait.stderr or "")
        _logger.error(redact_secrets(sortie.strip()[-1500:]))
    return fait.returncode == 0


# Ce qu'écrit l'OSError d'une écriture refusée : ENOSPC (errno 28), puis
# EDQUOT (errno 122).
MANQUE_DE_PLACE = ("No space left on device", "Disk quota exceeded")

# Les cadres de trace qui situent une écriture dans l'extraction du zip.
# « restore_db » d'Odoo extrait l'image dans un TemporaryDirectory, puis
# déplace le filestore vers le data_dir par « shutil.move », qui copie
# quand les deux sont sur des disques différents. Le même ENOSPC peut donc
# venir de l'une ou de l'autre écriture, et seule la première dépend de
# TMPDIR. L'OSError d'un « write » ne nomme aucun fichier : la pile est ce
# qui les départage.
CADRES_EXTRACTION = (" in extractall", " in _extract_member")


class RepereManqueDePlace:
    """Lit une sortie ligne à ligne ; `vu` dit si l'EXTRACTION a manqué de
    place.

    Une ligne de MANQUE_DE_PLACE ne compte que si la trace en cours —
    depuis son dernier « Traceback (most recent call last) » — passe par
    un cadre de CADRES_EXTRACTION. Un manque de place sans trace, ou levé
    ailleurs, laisse `vu` à False : le conseil général reste alors, qui
    ne prétend pas savoir quel disque est plein.
    """

    def __init__(self):
        self.vu = False
        self.dans_extraction = False

    def lire(self, ligne):
        if "Traceback (most recent call last)" in ligne:
            self.dans_extraction = False
        elif ligne.lstrip().startswith("File ") and ligne.rstrip().endswith(
            CADRES_EXTRACTION
        ):
            self.dans_extraction = True
        elif self.dans_extraction and any(
            motif in ligne for motif in MANQUE_DE_PLACE
        ):
            self.vu = True


def charger(args, env):
    """Lancer `args`, afficher sa sortie au fil de l'eau ; rendre (code,
    manque_de_place).

    La sortie d'erreur est fusionnée dans la sortie standard et relue ligne
    à ligne : Odoo y écrit son journal et la trace d'un échec, qui doivent
    rester visibles pendant une restauration longue. Chaque ligne passe par
    « redact_secrets » avant d'être affichée. `manque_de_place` dit si
    l'extraction de l'image a manqué de place, au sens de
    « RepereManqueDePlace » : c'est ce qui permet à « echec_restauration »
    de nommer le dossier où relancer.

    Toute exception levée pendant la lecture, KeyboardInterrupt compris,
    tue l'enfant et attend sa fin avant de remonter. « Popen » employé
    comme contexte ne le fait pas : sur KeyboardInterrupt, il attend un
    quart de seconde puis rend la main, et Odoo resterait connecté à la
    base que l'appelant va supprimer.
    """
    repere = RepereManqueDePlace()
    with subprocess.Popen(
        args,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    ) as processus:
        try:
            for ligne in processus.stdout:
                print(redact_secrets(ligne), end="", flush=True)
                repere.lire(ligne)
        except BaseException:
            processus.kill()
            processus.wait()
            raise
    return processus.returncode, repere.vu


def conseil_tmpdir(temporaire):
    """Les lignes qui disent où relancer quand l'extraction a manqué de
    place dans `temporaire`.

    La commande proposée est celle de ce lancement, « sys.argv » filtré par
    « redact_secrets », précédée de « TMPDIR= » : Python lit TMPDIR pour
    choisir son temporaire, et « restore_env » part de ce choix. Le dossier
    proposé est « dossier_travail », avec sa place mesurée quota compris,
    sauf si c'est lui qui vient de manquer de place : il faut alors un
    autre disque, que seul l'opérateur connaît.
    """
    repli = dossier_travail()
    commande = redact_secrets(shlex.join(sys.argv))
    if os.path.realpath(temporaire) == os.path.realpath(repli):
        return [
            f"   L'extraction a manqué de place dans {temporaire}, le dossier"
            " de repli. Relancez avec un dossier sur un disque qui a la"
            " place :",
            f"     TMPDIR=<dossier> {commande}",
        ]
    os.makedirs(repli, exist_ok=True)
    libre = espace_utilisable(repli) / GIO
    maison = os.path.expanduser("~")
    # « ~ » est développé par le shell dans une affectation « TMPDIR=~/… ».
    if repli.startswith(maison + os.sep):
        repli = "~" + repli[len(maison) :]
    lignes = [
        f"   L'extraction a manqué de place dans {temporaire}. {repli} a"
        f" {libre:.1f} Gio libres, quota compris. Relancez avec :",
        f"     TMPDIR={repli} {commande}",
    ]
    if os.environ.get("MAKELEVEL"):
        lignes.append(
            f"   ou, devant la même cible : TMPDIR={repli} make <cible>"
        )
    return lignes


def echec_restauration(
    arg_base, image, database, existait, env, cause, manque_de_place=False
):
    """Défaire ce que la restauration a créé, puis sortir en le disant.

    Odoo crée la base AVANT d'extraire : un échec d'extraction ou de
    chargement la laisse vide, et un cache vide serait cloné tel quel au
    passage suivant. Elle est donc supprimée — mais SEULEMENT si elle
    n'existait pas avant ce passage (`existait`, lu sous le verrou juste
    avant la restauration). Une base qui existait déjà n'a pas été créée
    ici, quel que soit son état, et n'est jamais touchée.

    Ce qui reste se lit dans PostgreSQL (« base_existe ») et non dans la
    liste d'Odoo, qui peut taire une base : le message dit l'état réel —
    rien n'a été créé, la base est supprimée, ou elle est encore là avec
    la commande qui la supprime.

    `manque_de_place`, rendu par « charger », remplace le conseil général
    par la commande exacte à relancer, avec son TMPDIR.

    Ne rend pas : lève SystemExit avec un message qui dit ce qui reste et
    quoi faire.
    """
    temporaire = (env or {}).get("TMPDIR") or tempfile.gettempdir()
    lignes = [
        f"❌ La restauration de {image} dans {database} a échoué : {cause}."
    ]
    a_supprimer = f"   Avant de relancer : ./odoo_bin.sh db drop {database}"
    if existait:
        lignes.append(
            f"   {database} existait avant ce passage : elle est laissée"
            " telle quelle."
        )
    elif base_existe(database) is False:
        lignes.append(
            f"   Odoo s'est arrêté avant de créer {database} : rien ne reste"
            " à nettoyer."
        )
    else:
        supprimer_base(arg_base, database)
        restante = base_existe(database)
        if restante is False:
            lignes.append(
                f"   La base {database}, laissée par l'échec, est supprimée"
                " avec son filestore : rien ne reste à nettoyer."
            )
        elif restante:
            lignes.append(f"   La base {database} existe encore.")
            lignes.append(a_supprimer)
        else:
            lignes.append(
                f"   Impossible de vérifier que {database} a disparu."
            )
            lignes.append(a_supprimer)
    if manque_de_place:
        lignes.extend(conseil_tmpdir(temporaire))
    else:
        lignes.append(
            "   Si la trace parle de « Disk quota exceeded » ou de « No space"
            f" left », l'extraction se faisait dans {temporaire} : regardez"
            " la place libre ET le quota de ce dossier, ou désignez un"
            " dossier sur disque par TMPDIR=<dossier> devant la même"
            " commande. Sinon la trace nomme la cause. Corrigez-la, puis"
            " relancez la même commande."
        )
    raise SystemExit("\n".join(lignes))


def restaurer(arg_base, image, database, neutralize=False):
    """Restaurer `image` dans `database`, puis vérifier qu'elle est chargée.

    L'appelant tient le verrou EXCLUSIF de `database` : la liste lue ici
    pour `existait` vaut alors jusqu'à la fin de la restauration.

    Tout échec — code non nul, interruption au clavier, base restée vide —
    passe par « echec_restauration », qui supprime la base si ce passage
    l'a créée. L'état INCONNU (« psql » muet) n'arrête rien et ne supprime
    rien : Odoo a rendu zéro, la base est peut-être bonne, et rien ne
    prouve le contraire — un avertissement le dit.
    """
    existait = database in bases_existantes(arg_base)
    # Ce chemin EXTRAIT, donc lui seul a besoin d'un temporaire qui tienne.
    # Le clone ne décompresse rien : lui passer cet environnement ferait
    # journaliser une extraction qui n'a pas lieu.
    env = restore_env(image)
    arg = f"{arg_base} load {database} --image {image}"
    if neutralize:
        arg += " --neutralize"
    # Le secret ne traverse plus argv (il est dans MASTER_PWD), mais la
    # commande peut porter d'autres options sensibles : on filtre quand
    # même, le coût est nul et la garantie ne dépend alors d'aucun appelant.
    print(redact_secrets(arg), flush=True)
    try:
        code, manque_de_place = charger(arg.split(" "), env)
    except KeyboardInterrupt:
        echec_restauration(
            arg_base, image, database, existait, env, "interrompue"
        )
    if code:
        echec_restauration(
            arg_base,
            image,
            database,
            existait,
            env,
            f"Odoo a rendu le code {code}",
            manque_de_place=manque_de_place,
        )
    chargee = est_chargee(database)
    if chargee is None:
        _logger.warning(
            f"## {database} : restauration non vérifiée, « psql » ne répond"
            " pas ; la base est laissée telle qu'Odoo l'a rendue ##"
        )
        return
    if not chargee:
        echec_restauration(
            arg_base,
            image,
            database,
            existait,
            env,
            "« psql » a rendu zéro sans charger le dump, la base est VIDE",
        )
    _logger.info(f"## {database} porte bien ses tables ##")


def cache_utilisable(arg_base, cache_database):
    """Le cache existant peut-il être cloné ? Sinon il est supprimé.

    Une restauration arrêtée là où ce script ne peut pas la défaire —
    processus tué, machine éteinte — laisse un cache sans tables : le
    cloner recopierait le vide. Un cache porte le préfixe « _cache_ » que
    ce script seul donne, et se recrée depuis son image : le supprimer ne
    perd rien. L'appelant tient le verrou EXCLUSIF du cache : aucun autre
    passage n'est alors en train de le charger.

    True quand il est chargé, ou quand « psql » ne répond pas — l'état
    inconnu n'est pas un vide, et l'on ne supprime pas sur un doute.
    False quand il a été supprimé et doit être recréé.
    """
    if est_chargee(cache_database) is not False:
        return True
    _logger.warning(
        f"## Cache {cache_database} sans tables : supprimé, puis recréé"
        " depuis son image ##"
    )
    if not supprimer_base(arg_base, cache_database):
        raise SystemExit(
            f"❌ Le cache vide {cache_database} n'a pas pu être supprimé."
            f" Avant de relancer : ./odoo_bin.sh db drop {cache_database}"
        )
    return False


def restore_or_clone(config, arg_base, cache_database):
    """Restaurer depuis l'image, ou cloner le cache déjà restauré.

    Sous « Verrou » : la liste des caches se relit une fois le verrou
    tenu, jamais celle d'avant. En partagé d'abord, pour le cas courant
    d'un cache prêt, que plusieurs passages clonent en même temps ; en
    exclusif seulement pour le supprimer ou le restaurer.

    Le contrôle du filestore ne suit QUE les vraies restaurations. Le
    clone recopie sa source telle quelle : contrôler le miroir dirait
    deux fois la même chose, et la seconde au mauvais endroit.
    """
    if config.ignore_cache:
        _logger.info(
            f"## Restoring {config.image} to database {config.database} ##"
        )
        with Verrou(config.database) as verrou:
            verrou.prendre(exclusif=True)
            restaurer(
                arg_base,
                config.image,
                config.database,
                neutralize=config.neutralize,
            )
            verify_filestore(config.database, config.image)
        return

    with Verrou(cache_database) as verrou:
        verrou.prendre(exclusif=False)
        lst_db_cache = get_list_db_cache(arg_base)[1]
        pret = (
            cache_database in lst_db_cache
            and est_chargee(cache_database) is not False
        )
        if not pret:
            verrou.prendre(exclusif=True)
            lst_db_cache = get_list_db_cache(arg_base)[1]
            if cache_database not in lst_db_cache or not cache_utilisable(
                arg_base, cache_database
            ):
                _logger.info(
                    f"## Create cache {cache_database} from image"
                    f" {config.image} ##"
                )
                restaurer(arg_base, config.image, cache_database)
                verify_filestore(cache_database, config.image)
            verrou.prendre(exclusif=False)

        _logger.info(
            f"## Clone cache {cache_database} to database {config.database} ##"
        )
        arg = f"{arg_base} duplicate {cache_database} {config.database}"
        if config.neutralize:
            arg += " --neutralize"
        print(redact_secrets(arg))
        print(redact_secrets(check_output(arg.split(" ")).decode()))


def main():
    config = get_config()

    arg_base = "./odoo_bin.sh db"

    if not config.image:
        with open(".odoo-version", "r") as f:
            odoo_version = f.readline()
            config.image = f"odoo{odoo_version}_base"

    # check if it needs master password from config file
    config_path = chemin_config()
    if config_path:
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
            drop_database(arg_base, db)
        lst_db, lst_db_cache = get_list_db_cache(arg_base)

    if config.database:
        cache_database = f"_cache_{config.image}"
        # Drop db
        if config.database in lst_db:
            _logger.info(f"## Drop {config.database} ##")
            drop_database(arg_base, config.database)
        if config.only_drop:
            return
        restore_or_clone(config, arg_base, cache_database)

    if not config.clean_cache and not config.database:
        print("Nothing to do.")


if __name__ == "__main__":
    main()
