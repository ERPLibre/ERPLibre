#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Worker d'une session web : le vrai TODO, sur le PTY de la session.

Lancé par le hub (`python -m script.todo.web.worker`, argv fixe, cwd à la
racine du checkout, fd 0-2 sur l'esclave du PTY, le canal annoncé par
TODO_WEB_FD). L'ordre compte :

1. SIGINT retrouve le gestionnaire de Python, SIGHUP, SIGTERM et SIGQUIT
   leur action par défaut, même hérités ignorés (un hub lancé en
   arrière-plan par un shell sans contrôle de tâches, ou par nohup), et le
   PTY devient le terminal de contrôle : /dev/tty, sudo et l'octet Ctrl+C
   s'y comportent comme dans un terminal ;
2. le canal passe sur le fd 3, non hérité par les commandes ; TODO_WEB_FD
   et TODO_WEB_PID le disent à TODO. La ligne `hello` y donne la langue,
   fixée pour ce seul processus, y compris si le menu Configuration la
   change ensuite : env_var.sh n'est jamais écrit ;
3. urwid est importé avant TODO : il lie sys.stdout en argument par
   défaut à son import ;
4. todo.py est importé en mode script, sous le nom `todo` : importé comme
   paquet, il pose ENABLE_CRASH et laisse todo_upgrade non lié ;
5. TODO ne demande pas la langue ; chaque Execute lance ses commandes dans
   ce terminal, avec le contrôle de tâches ; `restart_script` termine le
   worker avec RESTART, et le hub en relance un neuf.

Puis `serve` fait tourner TODO jusqu'à Quitter.
"""

import fcntl
import json
import os
import signal
import sys
import termios
import traceback
from pathlib import Path

from script.todo import todo_i18n
from script.todo.web.sessions import RESTART

TODO_DIR = Path(__file__).resolve().parent.parent
CHANNEL_FD = 3
CRASHED = 70
BAD_HELLO = 76
CRASH_LIMIT = 3
TRACE_TAIL = 8
HELLO_LIMIT = 64 * 1024
# Signaux rendus à leur action par défaut, SIGINT à part.
SIGNALS = (signal.SIGHUP, signal.SIGTERM, signal.SIGQUIT)


def restore_signals():
    """Une disposition ignorée s'hérite par exec : le worker et ses
    commandes reçoivent ces signaux comme tout programme d'un terminal."""
    for sig in SIGNALS:
        signal.signal(sig, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.default_int_handler)


def open_channel() -> int:
    """Place le canal de TODO_WEB_FD sur CHANNEL_FD, non hérité, et le note
    avec le pid de ce processus : un TODO lancé depuis une commande hérite
    des variables, jamais du descripteur."""
    fd = int(os.environ["TODO_WEB_FD"])
    if fd != CHANNEL_FD:
        os.dup2(fd, CHANNEL_FD, inheritable=False)
        os.close(fd)
    os.set_inheritable(CHANNEL_FD, False)
    os.environ["TODO_WEB_FD"] = str(CHANNEL_FD)
    os.environ["TODO_WEB_PID"] = str(os.getpid())
    return CHANNEL_FD


def read_hello(fd) -> dict:
    """La ligne JSON `hello` du hub ; ValueError si le canal se ferme
    avant, si elle dépasse HELLO_LIMIT octets ou n'est pas un `hello`."""
    data = b""
    while not data.endswith(b"\n"):
        chunk = os.read(fd, 4096)
        data += chunk
        if not chunk or len(data) > HELLO_LIMIT:
            raise ValueError("no hello on the channel")
    hello = json.loads(data)
    if not isinstance(hello, dict) or hello.get("t") != "hello":
        raise ValueError("no hello on the channel")
    return hello


def use_web_lang(todo_module):
    """Empêche `_ask_language` de redemander la langue et détourne
    `set_lang` du menu Configuration vers `todo_i18n.use_lang` : l'une
    comme l'autre ne durent que ce processus, jamais persistées dans
    env_var.sh ni visibles du TODO du terminal."""
    todo_module.lang_is_configured = lambda: True
    todo_module.set_lang = todo_i18n.use_lang


def run_inline(execute_module, venv):
    """Chaque Execute créé ensuite lance ses commandes dans ce terminal,
    jamais dans gnome-terminal ni par osascript, avec le contrôle de
    tâches ; celui de TODO comme celui de TodoUpgrade."""
    original = execute_module.Execute.__init__

    def __init__(self):
        original(self)
        self.cmd_source_erplibre = f"source ./{venv}/bin/activate;%s"
        self.cmd_source_default = ""

    execute_module.Execute.__init__ = __init__
    execute_module.Execute.job_control = True


def track_crumbs(todo_class):
    """Enveloppe `_menu_header` ; rend `where()`, le fil d'Ariane du
    dernier menu affiché (la première ligne de son en-tête), ou None."""
    last = [None]
    original = todo_class._menu_header

    def _menu_header(self, *args, **kwargs):
        header = original(self, *args, **kwargs)
        last[0] = header.split("\n", 1)[0]
        return header

    todo_class._menu_header = _menu_header
    return lambda: last[0]


def restart(last_error):
    """Remplace `TODO.restart_script` : le hub relance un worker neuf."""
    print(todo_i18n.t("Reboot TODO ..."))
    raise SystemExit(RESTART)


def exit_code(code) -> int:
    """Code de sortie d'un SystemExit, comme Python le rend : None vaut 0,
    un texte s'affiche et vaut 1."""
    if code is None or isinstance(code, int):
        return code or 0
    print(code)
    return 1


def serve(todo_obj, interrupts, where) -> int:
    """Fait tourner `todo_obj.run()` et rend le code de sortie du worker.

    Quitter rend 0, SystemExit son code. `interrupts` (Ctrl+C, Ctrl+D,
    Abort de click) ramènent au menu principal, comme une exception, dont
    la fin de la trace s'affiche ; la troisième de suite au même fil
    d'Ariane, `where()`, rend CRASHED.
    """
    crashes, last = 0, None
    while True:
        try:
            todo_obj.run()
            return 0
        except SystemExit as exc:
            return exit_code(exc.code)
        except interrupts:
            print()
            crashes = 0
        except Exception:
            lines = traceback.format_exc().splitlines()
            print("\n".join(lines[-TRACE_TAIL:]))
            here = where()
            crashes = crashes + 1 if here == last else 1
            last = here
            if crashes >= CRASH_LIMIT:
                return CRASHED


def main() -> int:
    restore_signals()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    try:
        todo_i18n.use_lang(read_hello(open_channel()).get("lang"))
    except ValueError as exc:
        print(f"todo web worker: {exc}", file=sys.stderr)
        return BAD_HELLO
    # urwid lie sys.stdout en argument par défaut à son import : avant TODO.
    import click
    import urwid  # noqa: F401

    sys.path.insert(0, os.fspath(TODO_DIR))
    import todo

    if todo.ENABLE_CRASH:
        print(todo.CRASH_E)
        return CRASHED
    use_web_lang(todo)
    run_inline(todo.execute, todo.VENV_ERPLIBRE)
    where = track_crumbs(todo.TODO)
    todo_obj = todo.TODO()
    todo_obj.restart_script = restart
    interrupts = (KeyboardInterrupt, EOFError, click.exceptions.Abort)
    return serve(todo_obj, interrupts, where)


if __name__ == "__main__":
    sys.exit(main())
