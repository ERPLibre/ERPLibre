#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Emplacements du hub web de TODO, un jeu par checkout.

Deux checkouts d'ERPLibre sur le même compte ont chacun leur hub : l'empreinte
du chemin réel de la racine sépare leurs sockets, états et journaux. Un lien
symbolique vers un checkout donne la même empreinte que le checkout lui-même.

- `runtime_dir` : ce qui meurt avec la session de l'utilisateur (socket de
  contrôle, verrou, état, fichier de redirection), sous `$XDG_RUNTIME_DIR` ;
- `data_dir` : ce qui survit (journal du serveur, `tasks_dir` et ses
  journaux de tâches), sous `~/.erplibre`.

Chaque répertoire est créé ou resserré en 0700 à chaque appel, et le journal
en 0600 : un autre compte local ne lit ni un code de connexion ni un journal.
Module pur : ni tornado ni réseau, importé par le serveur et le lanceur.
"""

import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

APP = "erplibre-todo-web"

# sun_path d'AF_UNIX, NUL final compris : 104 octets sous macOS, 108 sous
# Linux.
MAX_SOCK_PATH = 103 if sys.platform == "darwin" else 107
# Un fichier temporaire de `write_private` ne vit que le temps d'une
# écriture : plus vieux que ceci, son écrivain est mort avant de l'installer.
ORPHAN_SECONDS = 60.0


def checkout_id(root) -> str:
    """Empreinte courte et stable du chemin réel de `root`."""
    real = os.path.realpath(root)
    return hashlib.sha256(os.fsencode(real)).hexdigest()[:12]


def private_dir(path: Path) -> Path:
    """`path`, créé au besoin, en 0700."""
    # mkdir(mode=) passe par l'umask et laisse un répertoire existant tel
    # quel : chmod fixe le mode dans les deux cas.
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def data_dir(root) -> Path:
    """`~/.erplibre/todo_web/<empreinte>/`, en 0700."""
    web = Path.home() / ".erplibre" / "todo_web"
    private_dir(web)
    return private_dir(web / checkout_id(root))


def tasks_dir(root) -> Path:
    """`data_dir(root)/tasks/`, en 0700 : les journaux de tâches."""
    return private_dir(data_dir(root) / "tasks")


def runtime_dir(root) -> Path:
    """`$XDG_RUNTIME_DIR/erplibre-todo-web/<empreinte>/`, en 0700.

    Repli sur `data_dir(root)/run` quand `XDG_RUNTIME_DIR` est absent ou non
    inscriptible (session sans systemd-logind, `su` sans login).
    """
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base and os.path.isdir(base) and os.access(base, os.W_OK | os.X_OK):
        parent = private_dir(Path(base) / APP)
        return private_dir(parent / checkout_id(root))
    return private_dir(data_dir(root) / "run")


def ctl_path(root) -> Path:
    """Socket de contrôle ; `ValueError` si le chemin dépasse AF_UNIX."""
    path = runtime_dir(root) / "ctl.sock"
    size = len(os.fsencode(path))
    if size > MAX_SOCK_PATH:
        raise ValueError(
            f"control socket path is {size} bytes, AF_UNIX allows"
            f" {MAX_SOCK_PATH}: {path}"
        )
    return path


def lock_path(root) -> Path:
    """Verrou que le hub tient de son démarrage à son arrêt."""
    return runtime_dir(root) / "hub.lock"


def state_path(root) -> Path:
    """`state.json` du hub : pid, port, racine, heure de départ."""
    return runtime_dir(root) / "state.json"


def redirect_path(root) -> Path:
    """Page locale qui mène le navigateur au lien de connexion."""
    return runtime_dir(root) / "redirect.html"


def log_path(root) -> Path:
    """Journal du serveur."""
    return data_dir(root) / "server.log"


def open_log(root) -> int:
    """Descripteur en ajout sur le journal, créé ou resserré en 0600."""
    fd = os.open(log_path(root), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.fchmod(fd, 0o600)
    return fd


def write_private(path: Path, text: str) -> None:
    """Écrit `text` dans `path` en 0600, remplacé d'un coup.

    Chaque appel crée son propre fichier temporaire, au nom unique, à côté de
    `path` ; il est resserré avant d'être rempli, puis `os.replace`
    l'installe. Deux écrivains simultanés ne partagent donc aucun fichier :
    le dernier remplacement gagne, entier. Un lecteur voit l'ancien contenu
    ou le nouveau, jamais un fichier à moitié écrit ni lisible par un autre
    compte. Sur un échec, le fichier temporaire est retiré avant que
    l'`OSError` remonte.
    """
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def remove_orphans(directory: Path, age=ORPHAN_SECONDS) -> int:
    """Retire de `directory` chaque `*.tmp` modifié il y a plus de `age`
    secondes, le fichier temporaire d'un `write_private` interrompu, et rend
    leur nombre. Un plus récent reste : son écrivain peut vivre encore."""
    removed = 0
    for path in Path(directory).glob("*.tmp"):
        try:
            if time.time() - path.lstat().st_mtime > age:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed
