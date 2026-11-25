# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Remplacer le code de modules, et le remettre : archive zip et git.

Deux façons dont le code d'une instance change, et pour chacune de quoi
revenir en arrière :

- l'archive zip (`--zip` d'update_module) : `inspecter_zip` la lit sans
  rien écrire et refuse tout membre qui sortirait du dossier d'extraction
  (chemin absolu, composant `..`, barre oblique inverse, lien symbolique,
  fichier spécial) ou qui ne vit pas dans un dossier de module à la
  racine de l'archive ; `copier_modules` écrit une copie tar.gz des
  dossiers que l'extraction remplace ; `extraire_zip` remplace chaque
  dossier de module EN ENTIER, si bien qu'un fichier retiré de l'archive
  ne reste pas sur le disque ; `remettre_modules` remet la copie et
  retire les modules que l'archive a ajoutés.
- git : `depots_git` trouve les dépôts qui portent l'addons_path sous le
  dossier de travail de l'unité, `tete` et `modifie` les lisent, et
  `argv_revenir` remet HEAD sur un commit noté (`checkout --detach` : les
  branches restent où elles sont).

Les fonctions qui écrivent (`copier_modules`, `extraire_zip`,
`remettre_modules`, `ecrire_reference`, `renommer`) sont faites pour
tourner sous le compte de l'unité (`SystemeBase.sous_le_compte`) : les
chemins s'y résolvent par leur nom avec les droits de ce compte, qui
possède les dossiers d'addons. Elles rendent des valeurs qui s'écrivent
en JSON. Les commandes git passent par un `lancer(argv) -> (code, stdout,
stderr)` fourni par l'appelant, qui les place sous ce même compte.

Ce module ne traduit rien : les refus sont des `service.Refus` dont le
modèle anglais est marqué par `N_()`.

Bibliothèque standard seulement, sans syntaxe postérieure à Python 3.7.
"""

from __future__ import annotations

import ast
import collections
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
import zipfile

from script.lib_ops import service

N_ = service.N_
Refus = service.Refus

# Un nom de dossier de module : un nom technique d'Odoo.
RE_NOM_MODULE = re.compile(r"[A-Za-z0-9_]+")
# Un commit noté : sha-1 ou sha-256 complet, jamais une référence.
RE_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
# Une lettre de lecteur Windows en tête de nom (`C:`).
RE_LECTEUR = re.compile(r"[A-Za-z]:")

MANIFESTE = "__manifest__.py"
# Le manifeste se lit pour sa version seulement : au-delà, il est ignoré.
TAILLE_MANIFESTE_MAX = 1024 * 1024
BLOC = 1024 * 1024
# Les dossiers de travail de l'extraction et de la remise, dans le dossier
# d'addons lui-même : les renommages y restent sur le même système de
# fichiers, donc atomiques.
PREFIXE_PROVISOIRE = ".erplibre-zip-"
# Aucun fichier extrait n'est inscriptible par le groupe ou les autres, ni
# setuid : seuls les bits de lecture et d'exécution de l'archive passent.
MASQUE_MODE = 0o755
MODE_FICHIER = 0o644
MODE_DOSSIER = 0o755
MODE_REFERENCE = 0o644
VERSION_REFERENCE = 1

# Les types de fichier qu'un membre de zip peut annoncer : 0 quand
# l'archive ne porte pas de mode (zip créé sous Windows).
TYPES_ADMIS = (0, stat.S_IFREG, stat.S_IFDIR)

# Ce qu'`inspecter_zip` établit : {module: version du manifeste} et le
# total des octets décompressés.
Inspection = collections.namedtuple("Inspection", "modules octets")


def _parties(nom):
    return nom.rstrip("/").split("/")


def membre_sur(info):
    """True si le membre `info` (ZipInfo) s'extrait sans sortir du dossier
    d'extraction : nom relatif sans `..`, sans composant vide, sans barre
    oblique inverse, octet nul ni lettre de lecteur ; ni lien symbolique
    ni fichier spécial."""
    nom = info.filename
    if (
        not nom
        or "\\" in nom
        or "\0" in nom
        or nom.startswith("/")
        or RE_LECTEUR.match(nom)
    ):
        return False
    parties = _parties(nom)
    if ".." in parties or "" in parties or "." in parties:
        return False
    return (info.external_attr >> 16) & 0o170000 in TYPES_ADMIS


def _version(archive, info):
    """La `version` du manifeste, ou "?" quand il ne se lit pas."""
    if info.file_size > TAILLE_MANIFESTE_MAX:
        return "?"
    try:
        donnees = ast.literal_eval(
            archive.read(info).decode("utf-8", "replace")
        )
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return "?"
    if not isinstance(donnees, dict):
        return "?"
    return str(donnees.get("version", "?"))


def inspecter_zip(chemin):
    """L'Inspection de l'archive `chemin`, sans rien écrire.

    Lève Refus quand l'archive ne se lit pas, quand un membre n'est pas
    sûr (`membre_sur`) ou porte le nom d'un autre, quand un fichier est à
    la racine de l'archive,
    quand un dossier de la racine n'est pas un module (nom technique et
    `__manifest__.py`), ou quand elle ne porte aucun module."""
    try:
        with zipfile.ZipFile(chemin) as archive:
            infos = archive.infolist()
            dangereux = sorted(i.filename for i in infos if not membre_sur(i))
            if dangereux:
                raise Refus(
                    N_(
                        "Archive {path} refused: unsafe member(s) (absolute"
                        " path, '..', symbolic link or special file): {names}"
                    ),
                    path=chemin,
                    names=", ".join(dangereux[:10]),
                )
            # Un nom en double ferait échouer l'extraction, Odoo déjà
            # arrêté : refusé ici.
            vus = collections.Counter(i.filename.rstrip("/") for i in infos)
            doubles = sorted(nom for nom, n in vus.items() if n > 1)
            if doubles:
                raise Refus(
                    N_(
                        "Archive {path} refused: member(s) named twice: {names}"
                    ),
                    path=chemin,
                    names=", ".join(doubles[:10]),
                )
            hors = sorted(
                i.filename
                for i in infos
                if len(_parties(i.filename)) == 1 and not i.is_dir()
            )
            if hors:
                raise Refus(
                    N_(
                        "Archive {path} refused: file(s) outside a module"
                        " folder: {names}"
                    ),
                    path=chemin,
                    names=", ".join(hors[:10]),
                )
            modules = {}
            for info in infos:
                parties = _parties(info.filename)
                if parties[1:] == [MANIFESTE] and not info.is_dir():
                    modules[parties[0]] = _version(archive, info)
            dossiers = {_parties(i.filename)[0] for i in infos}
            autres = sorted(
                d
                for d in dossiers
                if d not in modules or not RE_NOM_MODULE.fullmatch(d)
            )
            if autres:
                raise Refus(
                    N_(
                        "Archive {path} refused: folder(s) at its root that"
                        " are not modules (technical name and"
                        " __manifest__.py): {names}"
                    ),
                    path=chemin,
                    names=", ".join(autres[:10]),
                )
            if not modules:
                raise Refus(N_("Archive {path} holds no module."), path=chemin)
            octets = sum(i.file_size for i in infos)
    except (OSError, zipfile.BadZipFile, RuntimeError, EOFError) as err:
        raise Refus(
            N_("Cannot read the archive {path}: {error}"),
            path=chemin,
            error=err,
        )
    return Inspection(modules, octets)


def _retirer(chemin):
    """Retire `chemin` : un lien ou un fichier par unlink, un dossier en
    entier sans suivre les liens qu'il contient."""
    if os.path.islink(chemin) or not os.path.isdir(chemin):
        os.unlink(chemin)
    else:
        shutil.rmtree(chemin)


def _extraire_membre(archive, info, racine):
    """Écrit le membre `info` sous `racine`, un dossier neuf de cet appel :
    rien n'y existe que ce que l'extraction a créé. Un nom en double lève
    (O_EXCL)."""
    cible = os.path.join(racine, *_parties(info.filename))
    if info.is_dir():
        os.makedirs(cible, MODE_DOSSIER, exist_ok=True)
        return
    os.makedirs(os.path.dirname(cible), MODE_DOSSIER, exist_ok=True)
    mode = ((info.external_attr >> 16) & MASQUE_MODE) or MODE_FICHIER
    drapeaux = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(cible, drapeaux, mode | 0o400)
    with os.fdopen(fd, "wb") as sortie, archive.open(info) as entree:
        shutil.copyfileobj(entree, sortie, BLOC)


def _echanger(destination, neuf, ancien, modules):
    """Met chaque `neuf/<module>` à la place de `destination/<module>`,
    l'ancien rangé dans `ancien`. Un échec remet, au mieux, ce qui a déjà
    été échangé, puis lève. Rend les modules placés."""
    faits = []
    try:
        for nom in modules:
            cible = os.path.join(destination, nom)
            avait = os.path.lexists(cible)
            if avait:
                os.rename(cible, os.path.join(ancien, nom))
            try:
                os.rename(os.path.join(neuf, nom), cible)
            except BaseException:
                if avait:
                    os.rename(os.path.join(ancien, nom), cible)
                raise
            faits.append((nom, avait))
    except BaseException:
        for nom, avait in reversed(faits):
            cible = os.path.join(destination, nom)
            try:
                _retirer(cible)
                if avait:
                    os.rename(os.path.join(ancien, nom), cible)
            except OSError:
                pass
        raise
    return [nom for nom, _avait in faits]


def extraire_zip(chemin, destination, modules):
    """Remplace en entier le dossier de chaque module de `modules` dans
    `destination` par celui de l'archive `chemin` ; rend les modules
    placés. Sous le compte de l'unité.

    L'archive entière s'extrait d'abord dans un dossier provisoire de
    `destination` ; chaque membre y est revérifié (`membre_sur`) : une
    archive remplacée depuis l'inspection ne passe pas. Les dossiers ne
    sont échangés qu'ensuite, par renommage. Le provisoire, anciens
    dossiers compris, est retiré dans tous les cas : la copie de
    `copier_modules` est prise avant."""
    provisoire = tempfile.mkdtemp(prefix=PREFIXE_PROVISOIRE, dir=destination)
    try:
        neuf = os.path.join(provisoire, "new")
        ancien = os.path.join(provisoire, "old")
        os.mkdir(neuf, 0o700)
        os.mkdir(ancien, 0o700)
        with zipfile.ZipFile(chemin) as archive:
            for info in archive.infolist():
                parties = _parties(info.filename)
                if not membre_sur(info) or parties[0] not in modules:
                    raise ValueError(f"unexpected member: {info.filename}")
                _extraire_membre(archive, info, neuf)
        return _echanger(destination, neuf, ancien, modules)
    finally:
        shutil.rmtree(provisoire, ignore_errors=True)


def copier_modules(destination, modules, archive_tar):
    """Écrit dans `archive_tar` (qui ne doit pas exister, 0600) une copie
    tar.gz des modules de `modules` présents dans `destination` ; rend
    leurs noms. Un module en lien symbolique est copié comme lien. Sous
    le compte de l'unité ; un échec retire la copie partielle."""
    drapeaux = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(archive_tar, drapeaux, 0o600)
    sauves = []
    try:
        with os.fdopen(fd, "wb") as brut:
            with tarfile.open(fileobj=brut, mode="w:gz") as tar:
                for nom in modules:
                    chemin = os.path.join(destination, nom)
                    if not os.path.lexists(chemin):
                        continue
                    tar.add(
                        chemin,
                        arcname=nom,
                        recursive=not os.path.islink(chemin),
                    )
                    sauves.append(nom)
            brut.flush()
            os.fsync(brut.fileno())
    except BaseException:
        try:
            os.unlink(archive_tar)
        except OSError:
            pass
        raise
    return sauves


def _membres_de_la_copie(tar, sauves):
    """Les membres de la copie, chacun sous un dossier de `sauves`, sans
    chemin absolu ni `..` ; un lien dur vise un membre de la copie.
    ValueError sinon."""
    membres = []
    for membre in tar.getmembers():
        for nom in [membre.name] + (
            [membre.linkname] if membre.islnk() else []
        ):
            parties = nom.split("/")
            if (
                nom.startswith("/")
                or ".." in parties
                or parties[0] not in sauves
            ):
                raise ValueError(f"unexpected member: {membre.name}")
        if not (
            membre.isdir()
            or membre.isfile()
            or membre.issym()
            or membre.islnk()
        ):
            raise ValueError(f"unexpected member: {membre.name}")
        membres.append(membre)
    return membres


def remettre_modules(destination, modules, archive_tar, sauves):
    """Remet dans `destination` les modules `sauves` depuis la copie
    `archive_tar`, et retire ceux de `modules` qu'elle ne porte pas (que
    l'archive a ajoutés). Sous le compte de l'unité.

    La copie s'extrait d'abord dans un dossier provisoire de
    `destination` ; chaque module en place est ensuite retiré puis
    remplacé par renommage. Rend {"remis": [...], "retires": [...]}."""
    provisoire = tempfile.mkdtemp(prefix=PREFIXE_PROVISOIRE, dir=destination)
    try:
        neuf = os.path.join(provisoire, "new")
        os.mkdir(neuf, 0o700)
        if sauves:
            with tarfile.open(archive_tar, "r:gz") as tar:
                membres = _membres_de_la_copie(tar, sauves)
                options = {}
                if hasattr(tarfile, "tar_filter"):
                    options["filter"] = "tar"
                tar.extractall(neuf, members=membres, **options)
        retires = []
        for nom in modules:
            cible = os.path.join(destination, nom)
            if os.path.lexists(cible):
                _retirer(cible)
            if nom in sauves:
                os.rename(os.path.join(neuf, nom), cible)
            else:
                retires.append(nom)
        return {"remis": list(sauves), "retires": retires}
    finally:
        shutil.rmtree(provisoire, ignore_errors=True)


def renommer(ancien, nouveau):
    """Renomme `ancien` en `nouveau`, qui ne doit pas exister : un dossier
    vide à ce nom serait sinon remplacé en silence. Sous le compte de
    l'unité. Rend True."""
    if os.path.lexists(nouveau):
        raise FileExistsError(nouveau)
    os.rename(ancien, nouveau)
    return True


# --- git --------------------------------------------------------------------


def argv_git(depot, *arguments):
    return ["git", "-C", depot] + list(arguments)


def depots_git(chemins, racine, lancer):
    """Les dépôts git, par leur chemin réel, qui portent les dossiers de
    `chemins` : sous `racine` (le dossier de travail de l'unité), `racine`
    elle-même exclue — le checkout porte les outils, dont celui-ci.
    Triés, sans doublon. Un dossier hors d'un dépôt est ignoré."""
    base = os.path.realpath(racine)
    depots = []
    for chemin in chemins:
        code, sortie, _erreur = lancer(
            argv_git(chemin, "rev-parse", "--show-toplevel")
        )
        if code != 0 or not sortie.strip():
            continue
        haut = os.path.realpath(sortie.strip())
        if haut == base or not haut.startswith(base + os.sep):
            continue
        if haut not in depots:
            depots.append(haut)
    return sorted(depots)


def tete(depot, lancer):
    """Le sha de HEAD du dépôt, ou "" quand il ne se lit pas."""
    code, sortie, _erreur = lancer(
        argv_git(depot, "rev-parse", "--verify", "--quiet", "HEAD")
    )
    sha = sortie.strip()
    return sha if code == 0 and RE_SHA.fullmatch(sha) else ""


def modifie(depot, lancer):
    """True quand un fichier suivi du dépôt est modifié, ou quand l'état
    ne se lit pas : un `checkout` y échouerait ou emporterait la
    modification."""
    code, sortie, _erreur = lancer(
        argv_git(depot, "status", "--porcelain", "--untracked-files=no")
    )
    return code != 0 or bool(sortie.strip())


def commit_existe(depot, sha, lancer):
    """True quand `sha` est un commit présent dans le dépôt."""
    if not RE_SHA.fullmatch(sha or ""):
        return False
    code, _sortie, _erreur = lancer(
        argv_git(depot, "cat-file", "-e", sha + "^{commit}")
    )
    return code == 0


def argv_revenir(depot, sha):
    """La commande qui remet HEAD du dépôt sur `sha`, détaché : la branche
    où HEAD se trouvait garde ses commits."""
    return argv_git(depot, "checkout", "--detach", "--quiet", sha)


def depots_de_reference(donnees):
    """{dépôt: sha} d'une référence lue (`ecrire_reference`), ou {} quand
    elle n'a pas la forme attendue : version, chemins absolus, sha
    complets."""
    if not isinstance(donnees, dict):
        return {}
    if donnees.get("version") != VERSION_REFERENCE:
        return {}
    depots = donnees.get("repos")
    if not isinstance(depots, dict):
        return {}
    return {
        depot: sha
        for depot, sha in depots.items()
        if isinstance(depot, str)
        and os.path.isabs(depot)
        and isinstance(sha, str)
        and RE_SHA.fullmatch(sha)
    }


def empreinte_de_reference(donnees):
    """L'empreinte des modules de la base notée avec la référence
    (`postgres.REQUETE_EMPREINTE_MODULES`), ou "" quand elle manque : la
    référence ne vaut que pour la base dont les modules ont encore cette
    empreinte."""
    if not isinstance(donnees, dict):
        return ""
    empreinte = donnees.get("modules_stamp")
    return empreinte if isinstance(empreinte, str) else ""


def ecrire_reference(chemin, depots, epoque, empreinte):
    """Écrit la référence {dépôt: sha} notée à `epoque`, avec l'empreinte
    des modules de la base à cet instant, dans `chemin` : fichier
    temporaire du même dossier, puis renommage ; 0644. Sous le compte de
    l'unité. Rend True."""
    texte = json.dumps(
        {
            "version": VERSION_REFERENCE,
            "date": epoque,
            "repos": depots,
            "modules_stamp": empreinte,
        },
        indent=2,
        sort_keys=True,
    )
    fd, provisoire = tempfile.mkstemp(
        prefix=".git_heads.", suffix=".tmp", dir=os.path.dirname(chemin)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fichier:
            fichier.write(texte + "\n")
            fichier.flush()
            os.fchmod(fichier.fileno(), MODE_REFERENCE)
            os.fsync(fichier.fileno())
        os.replace(provisoire, chemin)
    except BaseException:
        try:
            os.unlink(provisoire)
        except OSError:
            pass
        raise
    return True
