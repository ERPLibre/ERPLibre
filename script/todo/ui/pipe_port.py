#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Port du worker d'une session web : chaque question part sur le canal du
hub, une ligne `todo.v1`, et la réponse vient du canal ou du terminal.

Une question (`menu`, `ask`) reçoit un `qid`. Le port écrit son texte dans
le terminal, comme `input`, l'envoie sur le canal, puis attend la première
de deux réponses :
- sur le canal, `answer` ou `cancel` au même `qid`, une ligne d'un autre
  `qid` étant ignorée ; annuler lève EOFError, comme Ctrl+D ;
- dans le terminal, une ligne tapée ; Ctrl+D sur une ligne vide lève
  EOFError, et Ctrl+C KeyboardInterrupt, comme `input`.
À un compte à rebours, Ctrl+D comme `cancel` vaut Entrée, comme dans
`auto_ask.ask` : la question rend "", dont l'appelant fait son défaut.
Le terminal répond donc à toute question (`fallback: pty`), et le canal
fermé, il répond seul. Les `qid` partent d'une base propre au processus :
une réponse tardive faite au worker d'avant une relance ne répond pas au
suivant.

L'entrée du terminal est vidée (`tcflush(TCIFLUSH)`) avant et après chaque
question, puis `answered {qid}` part, quelle qu'en soit l'issue : ce que
le terminal tient quand la question commence n'y répond pas, ce qui reste
quand elle finit ne répond pas à la suivante, et le hub jette à ces bornes
la suite d'un collage qu'il retient. Pour un menu répondu par l'une de ses
entrées, `answered` en porte la clé (`key`), d'où que vienne la réponse :
le hub y ouvre une tâche du journal. Pour une question finie sans réponse,
il porte `end` : `timeout` à l'échéance, `cancel` sur une exception
(annulée par la page, Ctrl+D, Ctrl+C). Un secret se pose écho coupé, comme
`getpass` ; le hub y voit l'invite d'un mot de passe. Après une réponse
venue du canal, le terminal en montre la transcription sur la ligne de la
question : l'entrée choisie d'un menu, sinon la valeur ; un secret y
laisse MASK, quel que soit son chemin.
"""

import os
import select
import sys
import termios
import time

from script.todo.todo_i18n import t
from script.todo.ui import port
from script.todo.web import protocol

MASK = "•••"


def transcript(message, value) -> str:
    """Ce qu'une réponse du canal laisse dans le terminal : « 1 → libellé »
    pour une entrée de menu ou une option d'un choix, sinon la valeur."""
    for item in (*message.get("items", ()), *message.get("options", ())):
        if item["key"] == value.strip():
            return f"{value} → {item['label']}"
    return value


def _flush_input(fd):
    """Jette ce que le terminal `fd` tient en entrée ; rien hors terminal."""
    try:
        termios.tcflush(fd, termios.TCIFLUSH)
    except (termios.error, OSError):
        pass


def _echo_off(fd):
    """Coupe l'écho de `fd`, entrée vidée, comme `getpass` ; rend les
    réglages à remettre, ou None hors terminal ou quand le terminal
    refuse, raccroché : rien n'a changé."""
    try:
        saved = termios.tcgetattr(fd)
    except (termios.error, OSError):
        return None
    quiet = list(saved)
    quiet[3] &= ~termios.ECHO
    try:
        termios.tcsetattr(fd, termios.TCSAFLUSH, quiet)
    except (termios.error, OSError):
        return None
    return saved


def _restore(fd, saved):
    """Remet les réglages `saved` de `_echo_off` ; rien sans eux, ni
    quand le terminal a raccroché."""
    if saved is None:
        return
    try:
        termios.tcsetattr(fd, termios.TCSAFLUSH, saved)
    except (termios.error, OSError):
        pass


class PipePort(port.BasePort):
    """Le port d'une session : `channel`, le descripteur du canal ; `tty`,
    celui du terminal ; `out`, où écrire (sys.stdout au moment de
    l'écriture, par défaut)."""

    def __init__(self, channel, tty=0, out=None):
        self.channel = channel
        self.tty = tty
        self.out = out
        self.qid = os.getpid() * 1000
        self.pending = b""  # reste du canal, sans saut de ligne
        self.typed = b""  # ligne tapée, pas encore finie

    def _write(self, text):
        out = self.out or sys.stdout
        out.write(text)
        out.flush()

    def send(self, message) -> None:
        """Écrit `message` sur le canal ; un canal fermé ne sert plus."""
        if self.channel is None:
            return
        data = protocol.encode(message)
        try:
            while data:
                data = data[os.write(self.channel, data) :]
        except OSError:
            self.channel = None

    def event(self, message) -> None:
        """Crochet `Execute.events` : `run_start` et `run_end` au hub."""
        self.send(message)

    def notice(self, text, level="info") -> None:
        self._write(f"{text}\n")
        self.send({"t": "notice", "text": text, "level": level})

    def open_view(self, view) -> bool:
        self.send({"t": "open_view", "view": view})
        return self.channel is not None

    def run(self, cmd, **opts) -> int:
        return port.TerminalPort().run(cmd, **opts)

    def menu(self, view) -> str:
        return self._question(dict(view))

    def ask(self, text, default=None, kind="text", timeout=None) -> str:
        return self._question(port.question(kind, text, default, timeout))

    def _question(self, message) -> str:
        self.qid += 1
        message["qid"] = qid = self.qid
        kind, timeout = message.get("kind"), message.get("timeout_s")
        text = message["text"]
        if kind == "countdown":
            text = f"⏱{timeout:g}s {text}"
        _flush_input(self.tty)
        self.typed = b""
        # L'écho se coupe avant l'invite, comme dans getpass : ce qui est
        # tapé dès qu'elle paraît ne s'affiche jamais.
        saved = _echo_off(self.tty) if kind == "secret" else None
        answered = {"t": "answered", "qid": qid}
        try:
            self._write(text)
            self.send(message)
            source, value = self._wait(qid, timeout, kind == "countdown")
            keys = [item["key"] for item in message.get("items", ())]
            if value is not None and value.strip() in keys:
                answered["key"] = value.strip()
            if source is None:
                answered["end"] = "timeout"
        except BaseException:
            answered["end"] = "cancel"
            raise
        finally:
            _restore(self.tty, saved)
            _flush_input(self.tty)
            self.send(answered)
        if source is None:
            default = message.get("default") or ""
            detail = f" ({default})" if default else ""
            self._write(f" ⏱ → {t('Enter')}{detail}\n")
            return default
        if kind == "secret":
            self._write(MASK + "\n")
        elif source == "channel":
            self._write(transcript(message, value) + "\n")
        return value

    def _wait(self, qid, timeout, eof_is_enter=False) -> tuple:
        """`(source, valeur)` de la première réponse, `source` valant
        `channel` ou `terminal` ; `(None, None)` à l'échéance. Avec
        `eof_is_enter`, Ctrl+D rend `("terminal", "")` et `cancel`
        `("channel", "")` au lieu de lever."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            fds = [self.tty]
            if self.channel is not None:
                fds.append(self.channel)
            left = None
            if deadline is not None:
                left = max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select(fds, [], [], left)
            if not ready and deadline is not None:
                if time.monotonic() >= deadline:
                    return None, None
            if self.channel in ready:
                try:
                    value = self._from_channel(qid)
                except EOFError:
                    if not eof_is_enter:
                        raise
                    value = ""
                if value is not None:
                    return "channel", value
            if self.tty in ready:
                try:
                    value = self._from_terminal()
                except EOFError:
                    if not eof_is_enter:
                        raise
                    value = ""
                if value is not None:
                    return "terminal", value

    def _from_channel(self, qid):
        """La réponse du canal à `qid`, ou None ; EOFError pour `cancel`."""
        try:
            data = os.read(self.channel, 65536)
        except OSError:
            data = b""
        if not data:
            self.channel = None  # le hub est parti : le terminal seul
            return None
        *lines, self.pending = (self.pending + data).split(b"\n")
        for line in lines:
            reply = protocol.reply(line)
            if reply is None or reply["qid"] != qid:
                continue
            if reply["t"] == "cancel":
                raise EOFError("question cancelled")
            return reply["value"]
        return None

    def _from_terminal(self):
        """La ligne tapée, une fois finie, ou None ; EOFError à Ctrl+D sur
        une ligne vide, ou si le terminal a raccroché."""
        try:
            data = os.read(self.tty, 4096)
        except OSError:
            data = b""
        if not data and not self.typed:
            raise EOFError("end of the terminal input")
        self.typed += data
        if data and not self.typed.endswith(b"\n"):
            return None
        line, self.typed = self.typed.removesuffix(b"\n"), b""
        return line.decode(errors="replace")
