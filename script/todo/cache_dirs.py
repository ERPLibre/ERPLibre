#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les dossiers privés d'un cache local, et le ménage des éphémères.

Un cache porte ce que la personne lit et écrit ; sa RACINE doit donc être à
elle seule, en 0700, et n'être ni un lien symbolique ni le dossier d'un
autre utilisateur. Ces vérifications ne dépendent pas de ce que le cache
contient, d'où ce module : le cache courriel et le cache social les
partagent au lieu d'en tenir chacun une copie, car une copie corrigée d'un
seul côté est une faille qui dort dans l'autre.

Ce qui reste propre à chaque cache et n'est PAS ici : son schéma, son
scellement, et le préfixe de ses dossiers éphémères — chaque cache balaie
les siens et ne touche pas à ceux du voisin.
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from script.todo.todo_i18n import t


def ephemeral_base() -> Path:
    """/dev/shm quand il est inscriptible, sinon le dossier temporaire."""
    shm = Path("/dev/shm")
    if shm.is_dir() and os.access(shm, os.W_OK):
        return shm
    import tempfile

    return Path(tempfile.gettempdir())


def assert_private_dir(path: Path, erreur: type) -> None:
    """Refuse un dossier qu'on ne possède pas, ou qui est un lien symbolique.

    `erreur` est la classe d'exception à lever : chaque cache a la sienne, et
    la remonter telle quelle laisse ses appelants attraper ce qu'ils
    attrapaient déjà.
    """
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise erreur(f"{path} {t('mail_err_symlink_refused')}")
    if info.st_uid != os.getuid():
        raise erreur(f"{path} {t('mail_err_owned_by_other_user')}")


def prepare_private_root(root: Path, *, ephemeral: bool, erreur: type) -> None:
    """Crée la racine, en 0700 à chaque niveau qui nous appartient.

    `mkdir(parents=True)` crée les dossiers intermédiaires SANS appliquer le
    mode — c'est documenté dans la stdlib. En éphémère la racine vit sous un
    dossier public en 1777, partagé avec tous les utilisateurs locaux : un
    dossier par PID laissé à l'umask y rendrait les noms de comptes lisibles
    par n'importe qui, et un dossier pré-créé par un tiers à un chemin
    devinable lui permettrait de glisser un lien symbolique sous les fichiers
    qu'on y écrira.
    """
    parent = root.parent
    if ephemeral:
        parent.parent.mkdir(parents=True, exist_ok=True)
        parent.mkdir(mode=0o700, exist_ok=True)
        assert_private_dir(parent, erreur)
    else:
        parent.mkdir(parents=True, exist_ok=True)
    os.chmod(parent, 0o700)
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)


def sweep_orphan_ephemeral(prefix: str, base: Path | None = None) -> int:
    """Efface les caches éphémères dont le processus n'existe plus.

    `atexit` et les gestionnaires de signaux couvrent les sorties normales ;
    un SIGKILL, lui, laisse un résidu. Ce balayage au démarrage est le filet.

    `prefix` borne le ménage aux dossiers d'UN cache : ils vivent tous dans
    le même dossier public, et balayer sans préfixe emporterait ceux du
    voisin.
    """
    base = Path(base) if base else ephemeral_base()
    removed = 0
    if not base.is_dir():
        return 0
    for path in base.glob(f"{prefix}*"):
        if not path.is_dir():
            continue
        raw_pid = path.name[len(prefix) :]
        if not raw_pid.isdigit():
            continue
        pid = int(raw_pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except PermissionError:
            # Le PID existe et appartient à quelqu'un d'autre : on n'y
            # touche pas.
            continue
    return removed
