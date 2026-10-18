# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce qu'on peut savoir d'une instance Odoo sans la démarrer.

À partir de la ligne de commande d'une unité (son ExecStart), de son
dossier de travail et de son fichier de configuration, ce module dit :

- quel fichier de configuration Odoo lira (`trouver_config`) ;
- quelle base viser (`trouver_base`) ;
- sur quelle adresse le serveur écoute (`adresse_http`) ;
- quels dossiers forment l'addons_path, et quels modules y répondent à
  des motifs (`chemins_addons`, `developper_modules`) ;
- quels processus Odoo tournent sur une base (`processus_odoo`) ;
- quelles lignes d'un journal sont des erreurs (`lignes_erreur`) ;
- où vit le filestore d'une base (`data_dir`, `filestore`) ;
- si une sauvegarde au format zip d'Odoo est complète
  (`verifier_sauvegarde`) et quels membres en extraire
  (`membres_a_extraire`).

La ligne de commande l'emporte toujours sur la configuration, comme dans
Odoo : une option passée à odoo-bin écrase la valeur du fichier.

Aucune fonction n'écrit quoi que ce soit. Celles qui lisent le système de
fichiers reçoivent leurs chemins ; `processus_odoo` reçoit la racine de
/proc, qu'un test remplace par un dossier fabriqué.

Bibliothèque standard seulement.
"""

from __future__ import annotations

import configparser
import fnmatch
import json
import os
import re
import zipfile
import zlib

PORT_PAR_DEFAUT = 8069
HOTE_LOCAL = "127.0.0.1"
CONFIG_SYSTEME = "/etc/odoo/odoo.conf"

# Motif de module admis : un nom technique Odoo, avec * et ? pour les
# jokers. Rien qu'un shell ou une option interpréterait.
RE_MOTIF_MODULE = re.compile(r"[a-z0-9_*?]+")

# Une ligne de journal Odoo de niveau ERROR ou CRITICAL :
# « AAAA-MM-JJ hh:mm:ss,mmm PID ERROR base logger: message ».
# L'ancrage sur le format évite de compter un « ERROR » cité au milieu
# d'un message INFO.
RE_LIGNE_ERREUR = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)? \d+ (ERROR|CRITICAL) "
)

# Noms de fichier qui désignent un lanceur d'Odoo dans une ligne de
# commande.
LANCEURS_ODOO = ("odoo-bin", "odoo_bin.sh", "odoo", "run.sh")

# Valeurs de configuration qui veulent dire « non renseigné ».
VIDES = ("", "false", "none")

# Lecture de la partie ajoutée d'un journal : au plus ce volume, pris à
# la fin. Une mise à jour bavarde écrit des mégaoctets, et les erreurs
# qui comptent sont dans ce qu'elle vient d'écrire.
LECTURE_MAX = 8 * 1024 * 1024


class ErreurDetection(Exception):
    """Ce qui manque pour agir. Rien n'a été arrêté ni écrit."""


def valeur_argv(argv, courtes=(), longues=()):
    """La dernière valeur d'une option dans `argv`, ou None.

    Accepte `-d base`, `-dbase`, `--database base` et `--database=base`,
    les quatre formes que l'analyseur d'Odoo (optparse) reconnaît. La
    dernière occurrence l'emporte, comme chez lui.
    """
    trouve = None
    for index, argument in enumerate(argv):
        if argument in courtes or argument in longues:
            if index + 1 < len(argv):
                trouve = argv[index + 1]
            continue
        for longue in longues:
            if argument.startswith(longue + "="):
                trouve = argument.split("=", 1)[1]
        for courte in courtes:
            if argument.startswith(courte) and len(argument) > len(courte):
                trouve = argument[len(courte) :]
    return trouve


def lance_run_sh(argv):
    """True si la ligne de commande passe par le run.sh d'ERPLibre."""
    return any(os.path.basename(a) == "run.sh" for a in argv)


def _absolu(chemin, dossier):
    if not chemin:
        return chemin
    chemin = os.path.expanduser(chemin)
    if os.path.isabs(chemin):
        return chemin
    return os.path.normpath(os.path.join(dossier, chemin))


def trouver_config(
    argv,
    dossier,
    env_unite=None,
    explicite=None,
    existe=os.path.isfile,
):
    """Le fichier de configuration que l'instance lit : (chemin, origine).

    Ordre : `explicite` (doit exister) ; `-c`/`--config` de la ligne de
    commande ; si elle passe par run.sh, `dossier/config.conf` puis
    /etc/odoo/odoo.conf — l'ordre de run.sh lui-même ; sinon ODOO_RC de
    l'environnement de l'unité, `dossier/config.conf`, /etc/odoo/odoo.conf.
    Un chemin relatif se lit depuis `dossier`.

    `origine` nomme la source retenue ("--odoo-conf", "argv", "run.sh",
    "ODOO_RC", "workdir", "system"). ErreurDetection si rien n'existe.
    """
    if explicite:
        chemin = _absolu(explicite, os.getcwd())
        if not existe(chemin):
            raise ErreurDetection(chemin)
        return chemin, "--odoo-conf"
    depuis_argv = valeur_argv(argv, ("-c",), ("--config",))
    if depuis_argv:
        return _absolu(depuis_argv, dossier), "argv"
    local = os.path.join(dossier, "config.conf") if dossier else ""
    if lance_run_sh(argv):
        candidats = ((local, "run.sh"), (CONFIG_SYSTEME, "run.sh"))
    else:
        rc = (env_unite or {}).get("ODOO_RC", "")
        candidats = (
            (_absolu(rc, dossier), "ODOO_RC"),
            (local, "workdir"),
            (CONFIG_SYSTEME, "system"),
        )
    for chemin, origine in candidats:
        if chemin and existe(chemin):
            return chemin, origine
    raise ErreurDetection("config")


def lire_config(chemin):
    """La section [options] du fichier, en dict.

    {} si le fichier n'existe pas ou n'a pas de section [options].
    PermissionError remonte : un fichier présent mais illisible n'est pas
    un fichier vide, et l'appelant doit le dire.
    """
    if not chemin or not os.path.isfile(chemin):
        return {}
    with open(chemin, encoding="utf-8", errors="replace") as fichier:
        texte = fichier.read()
    parser = configparser.RawConfigParser(strict=False)
    try:
        parser.read_string(texte)
    except configparser.Error:
        return {}
    if not parser.has_section("options"):
        return {}
    return dict(parser.items("options"))


def _renseigne(valeur):
    valeur = str(valeur if valeur is not None else "").strip()
    return "" if valeur.lower() in VIDES else valeur


def trouver_base(explicite, argv, config):
    """La base à viser : (nom, origine) ou (None, None).

    Ordre : `explicite` ; `-d`/`--database` de la ligne de commande ;
    `db_name` de la configuration, sauf vide, False ou liste à virgules
    (Odoo y accepte plusieurs bases, ce qui ne désigne pas UNE base).
    """
    if explicite:
        return explicite, "--db"
    depuis_argv = valeur_argv(argv, ("-d",), ("--database",))
    if depuis_argv:
        return depuis_argv, "argv"
    db_name = _renseigne(config.get("db_name"))
    if db_name and "," not in db_name:
        return db_name, "db_name"
    return None, None


def adresse_http(argv, config):
    """(hôte, port) où l'instance écoute, tels qu'un client local les joint.

    Port : `-p`/`--http-port`/`--xmlrpc-port` de la ligne de commande,
    puis `http_port`, puis `xmlrpc_port` (le nom qu'écrit
    generate_config.sh, alias du premier), puis 8069. Interface : même
    ordre. Une interface vide ou « toutes » (0.0.0.0, ::) se joint par
    127.0.0.1.
    """
    port = valeur_argv(argv, ("-p",), ("--http-port", "--xmlrpc-port"))
    if not (port and port.isdigit()):
        port = _renseigne(config.get("http_port")) or _renseigne(
            config.get("xmlrpc_port")
        )
    port = int(port) if port and port.isdigit() else PORT_PAR_DEFAUT

    hote = valeur_argv(argv, (), ("--http-interface", "--xmlrpc-interface"))
    if not hote:
        hote = _renseigne(config.get("http_interface")) or _renseigne(
            config.get("xmlrpc_interface")
        )
    if not hote or hote in ("0.0.0.0", "::"):
        hote = HOTE_LOCAL
    return hote, port


def fichier_journal(argv, config, dossier):
    """Le fichier où Odoo écrit son journal, ou None s'il écrit sur stderr.

    `--logfile` de la ligne de commande, puis `logfile` de la
    configuration ; un chemin relatif se lit depuis `dossier`.
    """
    valeur = valeur_argv(argv, (), ("--logfile",))
    if not valeur:
        valeur = _renseigne(config.get("logfile"))
    return _absolu(valeur, dossier) if valeur else None


def chemins_addons(config, dossier):
    """Les dossiers de l'addons_path qui existent, dans l'ordre.

    Un chemin relatif se lit depuis `dossier`, le dossier de travail de
    l'unité, comme Odoo le lit depuis le sien.
    """
    chemins = []
    for brut in str(config.get("addons_path", "") or "").split(","):
        brut = brut.strip()
        if not brut:
            continue
        chemin = _absolu(brut, dossier)
        if os.path.isdir(chemin) and chemin not in chemins:
            chemins.append(chemin)
    return chemins


def motif_valide(motif):
    """True si `motif` est un nom technique, jokers * et ? permis."""
    return bool(motif) and RE_MOTIF_MODULE.fullmatch(motif) is not None


def _est_module(dossier):
    return os.path.isfile(os.path.join(dossier, "__manifest__.py"))


def developper_modules(motifs, chemins):
    """Développe les motifs sur les dossiers : (modules, absents, vides).

    Seul compte un dossier qui porte un `__manifest__.py`. L'ordre suit
    les motifs, puis l'addons_path, puis l'ordre alphabétique ; un module
    n'apparaît qu'une fois.

    `absents` : les noms EXACTS (sans joker) introuvables. `vides` : les
    motifs à jokers qui ne désignent rien.
    """
    modules, absents, vides = [], [], []
    for motif in motifs:
        joker = any(c in motif for c in "*?")
        trouves = []
        for chemin in chemins:
            if not joker:
                if _est_module(os.path.join(chemin, motif)):
                    trouves.append(motif)
                continue
            try:
                noms = sorted(os.listdir(chemin))
            except OSError:
                continue
            for nom in fnmatch.filter(noms, motif):
                if _est_module(os.path.join(chemin, nom)):
                    trouves.append(nom)
        if not trouves:
            (vides if joker else absents).append(motif)
        for nom in trouves:
            if nom not in modules:
                modules.append(nom)
    return modules, absents, vides


def lister_processus(racine="/proc"):
    """[(pid, argv)] des processus visibles sous `racine`.

    Un processus qui disparaît pendant la lecture, ou dont la ligne de
    commande est illisible, est simplement absent de la liste.
    """
    processus = []
    try:
        entrees = os.listdir(racine)
    except OSError:
        return processus
    for entree in entrees:
        if not entree.isdigit():
            continue
        try:
            with open(os.path.join(racine, entree, "cmdline"), "rb") as f:
                brut = f.read()
        except OSError:
            continue
        argv = [
            morceau.decode("utf-8", "replace")
            for morceau in brut.split(b"\0")
            if morceau
        ]
        if argv:
            processus.append((int(entree), argv))
    return processus


def processus_odoo(base, processus, exclus=()):
    """Les processus de `processus` qui lancent Odoo sur `base`.

    Un processus compte s'il nomme un lanceur d'Odoo (odoo-bin,
    odoo_bin.sh, odoo, run.sh) ET la même base par `-d`/`--database`. Une
    instance d'une autre base n'est pas une gêne. `exclus` : pids à
    ignorer (le processus courant, son parent).
    """
    trouves = []
    for pid, argv in processus:
        if pid in exclus:
            continue
        if not any(os.path.basename(a) in LANCEURS_ODOO for a in argv):
            continue
        if valeur_argv(argv, ("-d",), ("--database",)) == base:
            trouves.append((pid, argv))
    return trouves


def lignes_erreur(texte, ignorer=()):
    """Les lignes ERROR/CRITICAL au format Odoo, moins celles qu'un des
    motifs compilés de `ignorer` reconnaît."""
    lignes = []
    for ligne in (texte or "").splitlines():
        if not RE_LIGNE_ERREUR.match(ligne):
            continue
        if any(motif.search(ligne) for motif in ignorer):
            continue
        lignes.append(ligne)
    return lignes


def taille(chemin):
    """La taille du fichier en octets, 0 s'il n'existe pas."""
    try:
        return os.path.getsize(chemin) if chemin else 0
    except OSError:
        return 0


def lire_ajout(chemin, depuis):
    """Ce qui a été écrit dans `chemin` après l'octet `depuis`.

    Un fichier devenu plus court a été renouvelé (rotation) : il est lu
    depuis le début. Au plus `LECTURE_MAX` octets, pris à la fin. Rend ""
    si le fichier est absent ou illisible.
    """
    if not chemin:
        return ""
    try:
        with open(chemin, "rb") as fichier:
            fichier.seek(0, os.SEEK_END)
            fin = fichier.tell()
            debut = depuis if 0 <= depuis <= fin else 0
            debut = max(debut, fin - LECTURE_MAX)
            fichier.seek(debut)
            return fichier.read().decode("utf-8", "replace")
    except OSError:
        return ""


# Dossier de données d'Odoo quand le compte n'a pas de dossier personnel :
# le repli d'appdirs que reprend `odoo.tools.config`.
DATA_DIR_SANS_HOME = "/var/lib/odoo"

# La dernière ligne utile d'un dump au format texte. pg_dump récent écrit
# encore `\unrestrict <clé>` après elle : on la cherche dans la fin du
# fichier, pas sur sa dernière ligne.
FIN_DE_DUMP = b"PostgreSQL database dump complete"
TAILLE_FIN = 4096
BLOC = 1024 * 1024


def data_dir(argv, config, home, dossier, env_unite=None, existe=None):
    """Le dossier de données qu'Odoo utilise : (chemin, origine).

    Ordre d'Odoo : `-D`/`--data-dir` de la ligne de commande ; `data_dir`
    de la configuration ; sinon appdirs `user_data_dir("Odoo")`, qui suit
    `XDG_DATA_HOME` de l'environnement de l'unité, puis
    `<home>/.local/share/Odoo` ; `/var/lib/odoo` quand `home` n'existe pas.
    `~` se développe avec `home`, le dossier personnel du COMPTE de l'unité
    et non de celui qui lance l'outil ; un chemin relatif se lit depuis
    `dossier`, le dossier de travail de l'unité.

    `origine` vaut "argv", "data_dir", "XDG_DATA_HOME", "home" ou "default".
    `existe` (os.path.isdir par défaut) teste le dossier personnel.
    """
    existe = existe or os.path.isdir

    def resoudre(valeur):
        if valeur == "~" or valeur.startswith("~/"):
            valeur = (home or "") + valeur[1:]
        if os.path.isabs(valeur):
            return os.path.normpath(valeur)
        return os.path.normpath(os.path.join(dossier or "/", valeur))

    depuis_argv = valeur_argv(argv, ("-D",), ("--data-dir",))
    if depuis_argv:
        return resoudre(depuis_argv), "argv"
    valeur = _renseigne(config.get("data_dir"))
    if valeur:
        return resoudre(valeur), "data_dir"
    xdg = _renseigne((env_unite or {}).get("XDG_DATA_HOME"))
    if xdg and os.path.isabs(xdg):
        return os.path.join(xdg, "Odoo"), "XDG_DATA_HOME"
    if home and existe(home):
        return os.path.join(home, ".local", "share", "Odoo"), "home"
    return DATA_DIR_SANS_HOME, "default"


def filestore(dossier_donnees, base):
    """Le filestore de `base` : `<data_dir>/filestore/<base>`."""
    return os.path.join(dossier_donnees, "filestore", base)


def _lire_membre(archive, nom, fin=0):
    """Lit le membre `nom` en entier — le CRC est vérifié en fin de
    lecture, BadZipFile s'il ne correspond pas — et rend ses `fin`
    derniers octets."""
    queue = b""
    with archive.open(nom) as membre:
        while True:
            bloc = membre.read(BLOC)
            if not bloc:
                break
            if fin:
                queue = (queue + bloc)[-fin:]
    return queue


def verifier_sauvegarde(chemin):
    """Relit une sauvegarde Odoo au format zip : (ok, problèmes).

    Chaque membre est relu en entier, ce qui vérifie son CRC (l'équivalent
    de `testzip`). `dump.sql` doit se terminer par la marque de fin de
    pg_dump, et `manifest.json` être un objet JSON : sans eux, il n'y a
    rien à restaurer, et `ok` est False. Un filestore absent n'est qu'un
    problème signalé (une base sans pièce jointe n'en a pas), `ok` reste
    True. `chemin` peut être un chemin ou un fichier ouvert.
    """
    try:
        with zipfile.ZipFile(chemin) as archive:
            noms = archive.namelist()
            problemes = [
                n for n in ("dump.sql", "manifest.json") if n not in noms
            ]
            if problemes:
                return False, problemes
            for nom in noms:
                if nom == "dump.sql":
                    queue = _lire_membre(archive, nom, TAILLE_FIN)
                    if FIN_DE_DUMP not in queue:
                        problemes.append("dump.sql incomplete")
                elif nom == "manifest.json":
                    try:
                        manifeste = json.loads(archive.read(nom).decode())
                    except ValueError:
                        manifeste = None
                    if not isinstance(manifeste, dict):
                        problemes.append("manifest.json unreadable")
                else:
                    _lire_membre(archive, nom)
    except (
        OSError,
        zipfile.BadZipFile,
        zlib.error,
        EOFError,
        RuntimeError,
    ):
        return False, ["unreadable"]
    if problemes:
        return False, problemes
    if not any(n.startswith("filestore/") for n in noms):
        return True, ["filestore"]
    return True, []


def membre_dangereux(nom):
    """True si le nom de membre sortirait du dossier d'extraction : chemin
    absolu, composant `..`, barre oblique inverse (séparateur sous
    Windows), octet nul."""
    if not nom or "\\" in nom or "\0" in nom or nom.startswith("/"):
        return True
    return ".." in nom.split("/")


def membres_a_extraire(noms):
    """(à extraire, dangereux) : `dump.sql` et les fichiers de
    `filestore/`, les seuls membres qu'Odoo extrait d'une sauvegarde ; et
    les noms qui sortiraient du dossier d'extraction. Les autres membres
    (manifest.json compris) ne sont pas extraits."""
    dangereux = [nom for nom in noms if membre_dangereux(nom)]
    extraire = [
        nom
        for nom in noms
        if nom not in dangereux
        and (
            nom == "dump.sql"
            or (nom.startswith("filestore/") and not nom.endswith("/"))
        )
    ]
    return extraire, dangereux
