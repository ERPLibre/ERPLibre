#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Verrou exclusif d'un fichier, entre processus ET dans un même processus.

`fcntl.flock` est attaché à la DESCRIPTION de fichier ouverte, et non au
processus : deux `os.open` du même chemin dans le même processus
s'excluent aussi. C'est ce qui sépare deux passes du TUI (minuterie et
rafraîchissement manuel) et l'éditeur de règles du moteur, en plus du TUI,
du menu et du service entre eux.

Le verrou est consultatif : seul le code qui le prend en est protégé.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import time
from collections.abc import Iterator
from pathlib import Path

LOCK_WAIT_S = 30.0


@contextlib.contextmanager
def file_lock(
    path: Path, *, wait: float = LOCK_WAIT_S, poll: float = 0.2
) -> Iterator[bool]:
    """Tente le verrou pendant au plus `wait` secondes ; rend s'il est tenu.

    Le fichier est créé en 0600 s'il manque ; son dossier doit exister. Un
    lien symbolique est refusé (`OSError`) : le verrou ne suit pas un
    chemin qu'un tiers aurait posé. Le bloc s'exécute que le verrou soit
    obtenu ou non : c'est à l'appelant de lire la valeur rendue. Le verrou
    est relâché et le descripteur fermé en sortie, exception comprise.
    """
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    held = False
    try:
        deadline = time.monotonic() + max(wait, 0.0)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(poll, remaining))
        yield held
    finally:
        if held:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
