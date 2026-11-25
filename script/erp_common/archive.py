# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Archive de sauvegarde d'une instance : écriture atomique, lecture sûre.

Une archive <instance>-<AAAAMMJJ-HHMMSS>.tar.gz porte manifest.json et les
membres que l'ERP déclare. Elle porte aussi les données d'un client et le
mot de passe de la base : 0600 dans un dossier 0700, jamais là où git
pourrait la commiter, et un morceau qui échoue ne laisse ni archive ni
fichier partiel.

Par défaut, les archives de l'ERP `erp` vivent sous
private/<erp>/backups/<instance>/, dossier qu'une règle de
private/.gitignore propre à chaque ERP exclut du dépôt versionné.

À la lecture, un membre qui sortirait du dossier d'extraction (chemin
absolu, « .. », lien vers l'extérieur, type autre que fichier, dossier ou
lien) est refusé avant toute écriture.
"""

import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile

from script.erp_common.steps import t

MARIADB_DUMP = [
    "mariadb-dump",
    "--single-transaction",
    "--routines",
    "--triggers",
    "--no-tablespaces",
]
PG_DUMP = ["pg_dump", "--no-owner", "--no-privileges"]

# Date d'une archive, en fin de nom : elle trie les archives quel que soit
# le préfixe (pre-upgrade, pre-restore) placé avant.
_STAMP = re.compile(r"(\d{8}-\d{6})\.tar\.gz$")

# Types de membres que l'extraction manuelle accepte.
_SAFE_TYPES = (
    tarfile.REGTYPE,
    tarfile.AREGTYPE,
    tarfile.DIRTYPE,
    tarfile.SYMTYPE,
    tarfile.LNKTYPE,
)


class ArchiveError(Exception):
    """L'archive ne se lit pas, ou pas sans risque ; le message dit
    pourquoi."""


class System:
    """Commandes et moteur de conteneurs réels ; les tests en passent un
    factice.

    run_to_file et run rendent (code, sortie texte) ; 127 quand la
    commande ne se lance pas. `env` s'ajoute à l'environnement courant.
    """

    def run_to_file(self, argv, path, env=None):
        full = dict(os.environ, **env) if env else None
        with open(path, "wb") as out:
            try:
                r = subprocess.run(
                    argv, stdout=out, stderr=subprocess.PIPE, env=full
                )
            except OSError as e:
                return 127, str(e)
        return r.returncode, r.stderr.decode("utf-8", "replace")

    def run(self, argv, env=None, stdin_path=None):
        full = dict(os.environ, **env) if env else None
        stdin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
        try:
            r = subprocess.run(
                argv, stdin=stdin, capture_output=True, env=full
            )
        except OSError as e:
            return 127, str(e)
        finally:
            if stdin_path:
                stdin.close()
        out = (r.stdout or b"") + (r.stderr or b"")
        return r.returncode, out.decode("utf-8", "replace")

    def engine(self, moteur):
        from script.todo import container_runtime

        return container_runtime.etat(moteur)


def backups_dir(erp):
    """Dossier des sauvegardes de `erp`, relatif à la racine du dépôt."""
    return os.path.join("private", erp, "backups")


def private_dir(path):
    """Crée `path` au besoin et le ferme en 0700, même s'il existait."""
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def committable(path):
    """Vrai quand git pourrait commiter un fichier à `path` : la question
    de seal_menu.chemin_commitable, posée au dépôt qui contient le dossier.
    Si l'outillage TODO ne se charge pas, le doute refuse."""
    try:
        from script.todo.seal_menu import chemin_commitable
    except ImportError:
        return True
    return chemin_commitable(path)


def exposed(dest, name, stamp, member):
    """Les chemins que write écrirait dans `dest` et que git pourrait
    commiter : l'archive, son morceau .part, et `member` dans le dossier
    de travail, où les membres sont en clair."""
    final = os.path.join(dest, f"{name}-{stamp}.tar.gz")
    work = os.path.join(dest, ".partial-x", member)
    return [p for p in (final, final + ".part", work) if committable(p)]


def write(dest, name, stamp, plan, manifest, system):
    """Écrit l'archive <name>-<stamp>.tar.gz dans `dest` ; rend son chemin,
    ou None quand un membre échoue.

    `plan` est appelé sans argument une fois le dossier de travail créé et
    rend [(membre, argv, env)] : argv est une commande dont la sortie
    devient le membre, ou un chemin (str) copié tel quel. `manifest` est
    écrit en manifest.json. Les membres se préparent dans un dossier
    .partial-* de `dest`, l'archive dans un .part en 0600, renommé par
    os.replace : aucun chemin final ne désigne une archive incomplète. Le
    dossier de travail et le .part partent dans tous les cas.

    Ne vérifie pas `dest` : l'appelant refuse d'abord ce que exposed
    signale.
    """
    private_dir(dest)
    work = tempfile.mkdtemp(prefix=".partial-", dir=dest)
    try:
        for member, argv, env in plan():
            target = os.path.join(work, member)
            if isinstance(argv, str):
                try:
                    shutil.copyfile(argv, target)
                    code, err = 0, ""
                except OSError as e:
                    code, err = 1, str(e)
            else:
                code, err = system.run_to_file(argv, target, env)
            if code:
                print(t("Cannot save %s:") % member)
                print(err.strip()[-2000:])
                return None
        with open(
            os.path.join(work, "manifest.json"), "w", encoding="utf-8"
        ) as f:
            f.write(json.dumps(manifest, indent=4, sort_keys=True) + "\n")
        final = os.path.join(dest, f"{name}-{stamp}.tar.gz")
        partial = final + ".part"
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with (
            os.fdopen(fd, "wb") as raw,
            tarfile.open(fileobj=raw, mode="w:gz") as tar,
        ):
            for member in sorted(os.listdir(work)):
                tar.add(os.path.join(work, member), arcname=member)
        os.replace(partial, final)
        return final
    finally:
        shutil.rmtree(work, ignore_errors=True)
        partial = os.path.join(dest, f"{name}-{stamp}.tar.gz.part")
        if os.path.exists(partial):
            os.remove(partial)


def archives(erp, root, name):
    """Les archives de l'instance `name` de `erp`, la plus récente d'abord :
    par leur date, que le préfixe pre-upgrade ou pre-restore ne doit pas
    déplacer. [] sans dossier."""
    directory = os.path.join(root, backups_dir(erp), name)
    try:
        found = [f for f in os.listdir(directory) if _STAMP.search(f)]
    except OSError:
        return []
    found.sort(key=lambda f: _STAMP.search(f).group(1), reverse=True)
    return [os.path.join(directory, f) for f in found]


def saved_instances(erp, root):
    """Les instances de `erp` qui ont un dossier de sauvegardes, retirées
    comprises, triées."""
    try:
        return sorted(os.listdir(os.path.join(root, backups_dir(erp))))
    except OSError:
        return []


def has_filter():
    """Vrai si tarfile a le filtre « data » (Python 3.11.4 et suivants) ;
    sans lui, chaque membre se vérifie par check_member. Lu à chaque appel,
    pas figé à l'import."""
    return getattr(tarfile, "data_filter", None) is not None


def check_member(member):
    """Lève si `member` sortirait du dossier d'extraction : chemin absolu,
    « .. », lien vers l'extérieur, ou type autre que fichier, dossier, lien."""
    if member.type not in _SAFE_TYPES:
        raise tarfile.TarError(f"{member.name}: unexpected type")
    parts = member.name.split("/")
    if member.name.startswith("/") or ".." in parts:
        raise tarfile.TarError(f"{member.name}: outside the folder")
    if member.issym() or member.islnk():
        target = member.linkname
        base = os.path.dirname(member.name) if member.issym() else ""
        resolved = os.path.normpath(os.path.join(base, target))
        if target.startswith("/") or resolved.split("/")[0] == "..":
            raise tarfile.TarError(f"{member.name}: link outside the folder")


def extract(tar, directory):
    """Extrait le tar ouvert `tar` dans `directory` ; lève tarfile.TarError
    avant toute écriture si un membre en sortirait."""
    if has_filter():
        tar.extractall(directory, filter="data")
        return
    for member in tar.getmembers():
        check_member(member)
    tar.extractall(directory)


def check_tar(path):
    """Refuse (ArchiveError) un tar dont un membre sortirait du dossier
    d'extraction, ou qui ne se lit pas ; n'extrait rien."""
    try:
        with tarfile.open(path) as tar:
            for member in tar.getmembers():
                if has_filter():
                    tarfile.data_filter(member, "/nonexistent-dest")
                else:
                    check_member(member)
    except (tarfile.TarError, OSError) as e:
        raise ArchiveError(t("Unsafe or unreadable archive: %s") % e)


def read_archive(path, work, members, nested, foreign):
    """Extrait l'archive `path` dans `work` et rend son manifest.json lu.

    L'archive doit porter exactement les noms de `members`, sinon
    ArchiveError avec le message `foreign` (clé de traduction, %s reçoit
    `path`). Chaque membre de `nested` est un tar dont le contenu se
    vérifie à son tour, sans être extrait. Un membre qui sortirait de son
    dossier lève ArchiveError.
    """
    try:
        with tarfile.open(path) as tar:
            names = set(tar.getnames())
            if names != set(members):
                raise ArchiveError(t(foreign) % path)
            extract(tar, work)
    except (tarfile.TarError, OSError) as e:
        raise ArchiveError(t("Unsafe or unreadable archive: %s") % e)
    for member in nested:
        check_tar(os.path.join(work, member))
    with open(os.path.join(work, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)
