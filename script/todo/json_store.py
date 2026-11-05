#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Fichiers JSON par utilisateur que plusieurs processus TODO écrivent.

Un terminal TODO et les workers de l'interface web lisent et écrivent les mêmes
fichiers de ~/.erplibre. Deux garanties :

- une lecture voit toujours un fichier entier : l'écriture passe par un fichier
  temporaire du même répertoire, puis `os.replace`, atomique sur un même
  système de fichiers ;
- une lecture-modification-écriture (`update`) ne perd pas la modification
  d'un autre processus : elle tient un verrou exclusif `flock` du début à la
  fin.

Le verrou porte sur un fichier voisin `<nom>.lock`, jamais sur le fichier de
données : `os.replace` en change l'inode, et un verrou posé sur l'ancien ne
protégerait plus rien.

`default` est une fabrique (`dict`, `lambda: {"paths": {}}`) : chaque appel
rend un objet neuf, qu'un appelant peut modifier sans toucher au suivant. Un
fichier absent ou illisible (JSON invalide) rend le défaut ; les erreurs
d'écriture (`OSError`) remontent à l'appelant, qui décide s'il est
best-effort.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable


@contextlib.contextmanager
def _locked(path: Path):
    """Tient le verrou EXCLUSIF de `path` pendant le bloc.

    Un seul mode : aucun appelant d'ici ne lit sans écrire ensuite, un verrou
    partagé n'aurait donc jamais fait qu'ajouter un paramètre sans usage.
    """
    lock_path = path.with_name(path.name + ".lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        # Fermer le descripteur relâche le verrou.
        os.close(fd)


def _read_unlocked(path: Path, default: Callable[[], Any]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default()


def _write_unlocked(path: Path, data: Any) -> None:
    # mkstemp crée le fichier en 0600 : ces fichiers n'appartiennent qu'à
    # l'utilisateur.
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            # Pousse les données sur le disque AVANT le replace : sans ça,
            # une coupure de courant peut faire réapparaître le fichier
            # renommé vide (le contenu restait dans le cache du noyau), et la
            # prochaine écriture repart alors du défaut au lieu du contenu
            # perdu.
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read(path: Path, default: Callable[[], Any]) -> Any:
    """Contenu de `path`, ou `default()` s'il est absent ou illisible.

    Sans verrou : `os.replace` garantit déjà qu'un lecteur voit un fichier
    entier, et une lecture reste possible dans un répertoire où le fichier de
    verrou ne peut pas être créé.
    """
    return _read_unlocked(path, default)


def write(path: Path, data: Any) -> None:
    """Remplace tout le contenu de `path` par `data`.

    Résout `path` en son chemin réel avant d'écrire : `os.replace` remplace
    l'inode qu'on lui donne, et si `path` est un lien symbolique (un magasin
    tenu sous dotfiles, par exemple), le remplacer directement le changerait
    en fichier ordinaire. Écrire sur la cible garde le lien intact.
    """
    path = Path(os.path.realpath(path))
    with _locked(path):
        _write_unlocked(path, data)


def update(
    path: Path, fn: Callable[[Any], Any], default: Callable[[], Any]
) -> Any:
    """Écrit `fn(contenu actuel)` sous verrou exclusif et le renvoie.

    `fn` ne doit JAMAIS appeler `write()` ou `update()` sur ce MÊME magasin :
    le verrou est un flock, qui bloque entre deux descriptions de fichier
    ouvertes même à l'intérieur d'un seul processus, et l'appel imbriqué
    resterait bloqué indéfiniment.

    Même résolution de lien symbolique que `write()`.
    """
    path = Path(os.path.realpath(path))
    with _locked(path):
        new = fn(_read_unlocked(path, default))
        _write_unlocked(path, new)
        return new
