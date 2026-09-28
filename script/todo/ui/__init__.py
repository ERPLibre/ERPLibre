# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Façade du port d'interaction : `from script.todo import ui`, puis
`ui.ask(...)`, `ui.confirm(...)`, `ui.run(...)`.

Chaque appel résout le port lié au contexte courant (`ContextVar`) : celui
de `bind`, le temps d'un bloc `with`, ou d'`attach`, jusqu'à `detach` ;
sans lien, le terminal (`TERMINAL`). Un fil d'exécution neuf part sans
lien, sauf si `sys.flags.thread_inherit_context` est vrai (le défaut d'un
Python sans GIL) : il hérite alors du lien de celui qui le lance. Deux
fils gardent chacun le leur. Les signatures et ce que rend chaque
question sont ceux de `port.BasePort`.
"""

import contextlib
import contextvars

from script.todo.ui.port import TerminalPort, shell

TERMINAL = TerminalPort()
_BOUND = contextvars.ContextVar("todo_ui_port")


def current():
    """Le port lié au contexte courant, ou TERMINAL."""
    return _BOUND.get(TERMINAL)


@contextlib.contextmanager
def bind(port):
    """Lie `port` le temps du bloc ; le lien précédent revient ensuite."""
    token = _BOUND.set(port)
    try:
        yield port
    finally:
        _BOUND.reset(token)


def attach(port):
    """Lie `port` jusqu'à `detach(jeton)`, dans le même contexte."""
    return _BOUND.set(port)


def detach(token) -> None:
    _BOUND.reset(token)


def menu(view) -> str:
    return current().menu(view)


def ask(text, default=None, kind="text", timeout=None) -> str:
    return current().ask(text, default, kind, timeout)


def secret(text) -> str:
    return current().secret(text)


def confirm(text, default=False, typed=None) -> bool:
    return current().confirm(text, default, typed)


def choose(text, options, multi=False):
    return current().choose(text, options, multi)


def pick_path(start, directory=False):
    """Le chemin d'un fichier, ou d'un répertoire, choisi à partir de
    `start` ; None si l'utilisateur renonce."""
    return current().pick_path(start, directory)


def notice(text, level="info") -> None:
    current().notice(text, level)


def run(cmd, **opts) -> int:
    """Lance `cmd`, une str ou une t-string dont chaque valeur est citée
    (`shell`), par le port lié ; rend son code de sortie."""
    return current().run(shell(cmd), **opts)


def open_view(view) -> bool:
    return current().open_view(view)
