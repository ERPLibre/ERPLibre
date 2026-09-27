#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Environnement temporaire commun aux tests du hub web de TODO.

Module d'aide et non fichier de tests : son nom ne commence pas par
« test_ », le lanceur de tests ne le ramasse donc pas. Chaque fichier de
tests tourne comme script, avec test/ dans sys.path : `import todo_web_env`
le trouve.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch


def short_tmp() -> str:
    """Base des répertoires temporaires : celle du système si elle tient en
    40 octets, /tmp sinon. Le chemin de ctl.sock y ajoute 56 octets, et
    AF_UNIX n'en accepte que 103 à 107."""
    base = tempfile.gettempdir()
    return base if len(os.fsencode(base)) <= 40 else "/tmp"


def private_env(add_cleanup) -> Path:
    """HOME et XDG_RUNTIME_DIR temporaires, sans affichage ; rend leur base.

    `<base>/home` et `<base>/run` (0700) existent ; DISPLAY et
    WAYLAND_DISPLAY sont retirés, aucun navigateur n'est donc appelé.
    `add_cleanup` : addCleanup d'un test ou addClassCleanup d'une classe ;
    le nettoyage rend l'environnement d'origine et retire la base.
    """
    tmp = tempfile.TemporaryDirectory(dir=short_tmp())
    add_cleanup(tmp.cleanup)
    base = Path(tmp.name)
    (base / "home").mkdir()
    (base / "run").mkdir(mode=0o700)
    patcher = patch.dict(
        os.environ,
        {"HOME": str(base / "home"), "XDG_RUNTIME_DIR": str(base / "run")},
    )
    patcher.start()
    add_cleanup(patcher.stop)
    os.environ.pop("DISPLAY", None)
    os.environ.pop("WAYLAND_DISPLAY", None)
    return base
