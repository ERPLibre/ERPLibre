#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Mode enregistrement : le TODO du terminal, qui se comporte comme au CLI
et écrit en plus chacun de ses événements `todo.v1` dans un fichier.

`make todo_record` le lance. La capture (`legacy.install`) y est liée à
un RecordingPort, posée après `import urwid` et avant tout import de
TODO, comme dans le worker : le terminal répond par les fonctions
d'origine de TerminalPort, et chaque événement s'ajoute, une ligne JSON,
à `~/.erplibre/todo_web/<empreinte>/record-<horodatage>-<pid>.jsonl`,
créé en 0600. Une question (`menu`, `ask`, avec son `qid`) est suivie de
`answer` (la ligne répondue, MASK pour un secret) ou de `cancel` (Ctrl+C,
Ctrl+D) ; viennent aussi `notice`, `run_start` et `run_end`. Chaque texte
écrit passe par `redact_secrets`, et un secret n'y laisse que MASK, défaut
compris ; TODO reçoit, lui, la réponse intacte. Le fichier montre ce que
la capture lit d'une vraie session. Le reste est celui de
`make todo` : les exceptions qui finissent TODO, le pied de page, la
relance de `restart_script`.
"""

import datetime
import json
import os
import sys
import time
from pathlib import Path

from script.execute.execute import redact_secrets
from script.todo.todo_i18n import t
from script.todo.ui import legacy, port
from script.todo.web import paths

ROOT = Path(__file__).resolve().parents[3]
TODO_DIR = ROOT / "script" / "todo"
MASK = "•••"


def open_record(root) -> tuple:
    """`(chemin, fichier texte)` d'un enregistrement neuf du checkout
    `root`, créé en 0600, jamais un fichier existant : TODO relancé par
    `restart_script` garde son pid, et dans la même seconde, le nom prend
    un suffixe (`-2`, `-3`…)."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    stem = f"record-{stamp}-{os.getpid()}"
    for number in range(1, 1000):
        suffix = f"-{number}" if number > 1 else ""
        path = paths.data_dir(root) / f"{stem}{suffix}.jsonl"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        return path, os.fdopen(fd, "w", encoding="utf-8")
    raise FileExistsError(path)


def _redacted(value):
    """`value` dont chaque chaîne, dans ses listes et ses dict, passe par
    `redact_secrets`."""
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, list):
        return [_redacted(item) for item in value]
    if isinstance(value, dict):
        return {key: _redacted(item) for key, item in value.items()}
    return value


class RecordingPort(port.TerminalPort):
    """Le terminal, comme TerminalPort, dont chaque événement s'écrit dans
    `sink`, une ligne JSON chacun, écrite aussitôt."""

    def __init__(self, sink):
        self.sink = sink
        self.qid = 0

    def event(self, message) -> None:
        """Écrit `message`, caviardé (`_redacted`) ; sert aussi de crochet
        `Execute.events`."""
        line = json.dumps(_redacted(message), ensure_ascii=False)
        self.sink.write(line + "\n")
        self.sink.flush()

    def _recorded(self, message, answer) -> str:
        self.qid += 1
        message["qid"] = qid = self.qid
        secret = message.get("kind") == "secret"
        if secret and message.get("default"):
            message["default"] = MASK
        self.event(message)
        try:
            value = answer()
        except (EOFError, KeyboardInterrupt):
            self.event({"t": "cancel", "qid": qid})
            raise
        self.event(
            {"t": "answer", "qid": qid, "value": MASK if secret else value}
        )
        return value

    def menu(self, view) -> str:
        return self._recorded(
            dict(view), lambda: super(RecordingPort, self).menu(view)
        )

    def ask(self, text, default=None, kind="text", timeout=None) -> str:
        message = port.question(kind, text, default, timeout)
        parent = super(RecordingPort, self)
        return self._recorded(
            message, lambda: parent.ask(text, default, kind, timeout)
        )

    def notice(self, text, level="info") -> None:
        super().notice(text, level)
        self.event({"t": "notice", "text": text, "level": level})

    def open_view(self, view) -> bool:
        self.event({"t": "open_view", "view": view})
        return False


def _elapsed(seconds) -> str:
    """Une durée comme le pied de page du CLI : par humanize s'il est
    installé, sinon en secondes."""
    try:
        import humanize
    except ImportError:
        return f"{seconds:.2f} sec."
    return humanize.precisedelta(datetime.timedelta(seconds=seconds))


def main() -> int:
    import click
    import urwid  # noqa: F401 - lie sys.stdout à son import, avant le Tee

    start = time.time()
    path, sink = open_record(ROOT)
    recording = RecordingPort(sink)
    uninstall = legacy.install(recording)
    # `restart_script` relance `python <sys.argv>` : sous `-m`, argv[0] est
    # le chemin de ce fichier, qui ne s'importe pas hors de son paquet.
    sys.argv = ["-m", "script.todo.ui.record", *sys.argv[1:]]
    try:
        sys.path.insert(0, os.fspath(TODO_DIR))
        import todo

        legacy.wrap_menus(todo.TODO)
        todo.execute.Execute.events = recording.event
        todo_obj = todo.TODO()
        if todo.ENABLE_CRASH:
            todo_obj.crash_diagnostic(todo.CRASH_E)
        todo_obj.run()
    except (KeyboardInterrupt, click.exceptions.Abort):
        print(t("Keyboard interrupt"))
    finally:
        uninstall()
        sink.close()
        elapsed = _elapsed(time.time() - start)
        print(f"\n{t('TODO execution time')} {elapsed}\n")
        print(f"{t('Events recorded in:')} {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
