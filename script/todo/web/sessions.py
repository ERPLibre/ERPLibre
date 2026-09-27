#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Sessions du hub web de TODO : un PTY et un worker par session.

Le worker (`python -m script.todo.web.worker`, argv fixe, cwd à la racine
du checkout) tourne dans une session Unix neuve, fd 0-2 sur l'esclave d'un
PTY dont la taille est posée avant le lancement. Une socketpair sert de
canal (`protocol`) : le hub y écrit la ligne `hello` (la langue) puis les
réponses du client, le worker ses questions et ses événements, que le hub
relaie au client ; l'extrémité du worker lui arrive par `pass_fds`, son
numéro dans TODO_WEB_FD. Rien d'un client n'atteint argv.

La sortie du maître s'accumule dans un anneau de RING_SIZE octets, repérés
par un décalage absolu. Sans client, la lecture continue : une commande
n'attend jamais un onglet fermé. Avec un client, elle s'arrête le temps de
lui envoyer ce qui lui manque, CHUNK octets au plus par envoi : un client
lent ralentit la commande, comme un terminal.

Chaque session suit son terminal (`ttywatch.TtyWatch`) : après la sortie,
et toutes les PROBE_SECONDS tant qu'un client est attaché, le client
reçoit `tty_state` quand l'état change. `gate` relit le terminal et ne
laisse passer une frappe que si quelqu'un la lit, ou si un lecteur vu à
l'instant relit dans les HOLD_SECONDS qui suivent ; ce qu'un lecteur n'a
pas pris est jeté dès que la sonde voit l'écho se couper en mode
canonique. En mode canonique, devant un lecteur connu, un collage part une
ligne à la fois, la suivante quand la précédente a été lue (`held`), une
sonde plus tard : une cinquantaine de lignes par seconde avec un client
(PROBE_GAP). Jamais pendant une question du worker (`asking`) : chaque
message du worker jette ce qui en reste, comme le worker vide son entrée à
chaque question. La suite d'un collage ne nourrit donc que le programme
qui lit hors question : un programme qui coupe l'écho et lit aussitôt,
sans vider l'entrée, ne la reçoit jamais comme secret, ni une question du
worker comme réponse. Devant un lecteur qu'aucune sonde ne sait trancher
(`ttywatch` : programme setuid, /proc inutilisable), rien ne dirait quand
livrer la ligne suivante : le collage part entier, et le worker, qui vide
son entrée avant et après chaque question, n'en prend qu'une ligne. Ce que
`held` jette est dit au client par `dropped`, ou au suivant quand il n'y
en a pas (`unreported`).

Un client offre `send(octets)`, attendable, rendu quand les octets ont
quitté le hub ; `event(message)`, un dict envoyé en texte ; `close(code,
raison)`. Module sans tornado ; les enfants du worker se lisent dans /proc.
"""

import asyncio
import fcntl
import json
import os
import pty
import signal
import socket
import struct
import sys
import termios
import time

from script.todo.web import protocol, ttywatch

RING_SIZE = 4 * 1024 * 1024
CHUNK = 64 * 1024
# Frappes et collages qui attendent que le worker lise son terminal ; au-delà,
# `write` refuse.
INPUT_LIMIT = 256 * 1024
MAX_SESSIONS = 3
IDLE_SECONDS = 15 * 60
REAP_SECONDS = 3.0
# Code de sortie par lequel le worker demande un worker neuf ; au-delà de
# RESTART_LIMIT relances en RESTART_WINDOW secondes, la session finit.
RESTART = 75
RESTART_LIMIT = 3
RESTART_WINDOW = 60.0
WORKER = ("-m", "script.todo.web.worker")
# Sonde du terminal : toutes les PROBE_SECONDS tant qu'un client est
# attaché, et après la sortie, PROBE_GAP secondes après la précédente au
# plus tôt (dix fois son coût si c'est plus, PROBE_SECONDS au plus), pour
# qu'un flot de sortie ne relise pas /proc à chaque morceau.
PROBE_SECONDS = 0.2
PROBE_GAP = 0.02
# Une frappe qui trouve sans lecteur un terminal où une sonde en a vu un
# depuis moins de READER_RECENT secondes attend HOLD_SECONDS au plus qu'il
# relise : voir `gate`.
READER_RECENT = 0.1
HOLD_SECONDS = 0.03


class Ring:
    """Derniers `size` octets d'un flux ; `start` et `end` sont les
    décalages absolus du premier octet gardé et de l'octet suivant le
    dernier."""

    def __init__(self, size=RING_SIZE):
        self.size = size
        self.data = bytearray()
        self.start = 0

    @property
    def end(self) -> int:
        return self.start + len(self.data)

    def append(self, chunk: bytes) -> None:
        self.data += chunk
        extra = len(self.data) - self.size
        if extra > 0:
            # Retirer la tête d'un bytearray ne recopie pas le reste.
            del self.data[:extra]
            self.start += extra

    def read(self, offset: int, limit: int) -> tuple:
        """`(décalage, octets)` : au plus `limit` octets à partir de
        `offset`, ramené entre `start` et `end`."""
        offset = min(max(offset, self.start), self.end)
        at = offset - self.start
        return offset, bytes(self.data[at : at + limit])


def _set_size(fd, cols, rows):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _killpg(groups, sig):
    for pgid in groups:
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def _alive(groups) -> bool:
    """Vrai si l'un des groupes de processus a encore un membre."""
    for pgid in groups:
        try:
            os.killpg(pgid, 0)
            return True
        except ProcessLookupError:
            continue
        except PermissionError:
            return True
    return False


def _in_group(cpid, pgid) -> bool:
    """Vrai si l'enfant `cpid` est vivant (pas zombie) et dans le groupe de
    processus `pgid` du worker ; faux pour un zombie non attendu (Popen
    jamais réattendu) ou pour un enfant reparti dans une session neuve
    (start_new_session, `setsid`), qu'un octet Ctrl+C au terminal
    n'atteint pas.

    Lu dans /proc/<cpid>/stat : l'état (champ 3) et le groupe (champ 5),
    après la dernière parenthèse fermante du nom du processus, qui peut
    lui-même contenir espaces et parenthèses.
    """
    try:
        with open(f"/proc/{cpid}/stat", "rb") as f:
            stat = f.read()
    except OSError:
        return False
    fields = stat.rsplit(b")", 1)[-1].split()
    if len(fields) < 3:
        return False
    state, pgrp = fields[0], fields[2]
    return state != b"Z" and pgrp.isdigit() and int(pgrp) == pgid


def _has_children(pid) -> bool:
    """Vrai si le processus `pid` a, dans son propre groupe, un enfant
    vivant, d'après les fichiers `children` de /proc ; faux sans eux (hors
    Linux, ou noyau sans CONFIG_PROC_CHILDREN). Un zombie ou un enfant
    reparti dans une session neuve ne compte pas : voir `_in_group`."""
    try:
        threads = os.listdir(f"/proc/{pid}/task")
    except OSError:
        return False
    children = set()
    for tid in threads:
        try:
            with open(f"/proc/{pid}/task/{tid}/children", "rb") as f:
                children.update(f.read().split())
        except OSError:
            continue
    return any(_in_group(cpid.decode(), pid) for cpid in children)


def _exited(pid) -> bool:
    """Vrai si l'enfant `pid` a fini, attendu ou non : WNOWAIT le laisse
    attendable par qui l'attend (asyncio)."""
    try:
        found = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except ChildProcessError:
        return True  # déjà attendu
    return found is not None


def _first_line(data) -> tuple:
    """`(première ligne, reste)` : jusqu'au premier CR ou LF compris, CR
    LF comptant pour un ; `(data, b"")` sans fin de ligne."""
    ends = [at for at in (data.find(b"\r"), data.find(b"\n")) if at >= 0]
    if not ends:
        return data, b""
    end = min(ends) + 1
    if data[end - 1 : end + 1] == b"\r\n":
        end += 1
    return data[:end], data[end:]


def _secret(state) -> bool:
    """Écho coupé en mode canonique : une invite de mot de passe."""
    return not state.echo and state.canon


def _open(state) -> bool:
    """Vrai si une frappe peut aller au terminal sans filtre : quelqu'un
    la lit, un programme tient l'écran alternatif, ou on ne sait pas."""
    return state.altscreen or state.reader is not False


def _by_line(state) -> bool:
    """Vrai si un collage part une ligne à la fois : mode canonique, hors
    écran alternatif, devant un lecteur connu ; faux sans état lu."""
    return (
        state is not None
        and state.canon
        and not state.altscreen
        and state.reader is not None
    )


class Session:
    """Un worker sur son PTY, l'anneau de sa sortie et au plus un client.

    `on_end(session)` est appelé une fois, le worker terminé. `argv`
    remplace le worker dans les tests ; le hub ne le passe jamais. Sans
    langue (`lang` None), la session est un worker de réserve : lancé, il
    attend son `hello`, que `adopt` envoie en lui donnant son identité.
    """

    def __init__(self, sid, root, lang, cols, rows, argv=None, on_end=None):
        self.id = sid
        self.root = root
        self.lang = lang
        self.cols, self.rows = cols, rows
        self.argv = list(argv or (sys.executable, *WORKER))
        self.on_end = on_end
        self.ring = Ring()
        self.client = None
        self.sent = 0  # décalage du prochain octet dû au client
        self.quiet_since = time.monotonic()
        self.master = None
        self.tty = None  # nom de l'esclave du PTY
        self.eof = False
        self.proc = None
        self.channel = None
        self.inbox = bytearray()
        self.held = bytearray()  # lignes d'un collage, jusqu'à leur lecteur
        self.unreported = 0  # octets jetés sans client, dus au suivant
        self.flushing = None
        self.closing = False
        self.killing = None  # l'arrêt que `_watch` lance pendant une relance
        self.code = None
        self.ended = asyncio.Event()
        self.tasks = set()
        self.watch = None  # TtyWatch du PTY courant
        self.state = None  # dernier TtyState lu
        self.shown = None  # dernier tty_state envoyé au client
        self.probe_timer = None
        self.probed_at = 0.0
        self.read_at = float("-inf")  # dernière sonde qui a vu un lecteur
        self.gap = PROBE_GAP  # délai minimal entre deux sondes
        self.asking = None  # question du worker qui attend sa réponse

    async def start(self):
        """Lance le worker ; OSError si le PTY ou le processus manquent. Un
        `close` venu pendant le lancement l'arrête dès qu'il est lancé."""
        await self._spawn()
        self._task(self._watch())
        self._task(self._tick())
        if self.closing:
            await self.close()

    async def _spawn(self):
        master, slave = pty.openpty()
        hub_end, worker_end = socket.socketpair()
        try:
            # `interrupt` rouvre l'esclave par ce nom pour vider son entrée.
            tty = os.ttyname(slave)
            # Avant le lancement : un PTY de 0×0 casse Textual.
            _set_size(master, self.cols, self.rows)
            os.set_blocking(master, False)
            fd = worker_end.fileno()
            env = dict(os.environ, TODO_WEB_FD=str(fd), TERM="xterm-256color")
            # Elles priment sur la taille du terminal pour bien des outils.
            env.pop("COLUMNS", None)
            env.pop("LINES", None)
            self.proc = await asyncio.create_subprocess_exec(
                *self.argv,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                pass_fds=(fd,),
                start_new_session=True,
                cwd=self.root,
                env=env,
            )
        except BaseException:
            os.close(master)
            hub_end.close()
            raise
        finally:
            os.close(slave)
            worker_end.close()
        self.master, self.tty, self.eof = master, tty, False
        self.asking = None
        try:
            self.watch = ttywatch.TtyWatch(master, self.proc.pid)
        except OSError:
            self.watch = None  # sans suivi, tout passe, comme sans TtyWatch
        self.state = None
        self._reading(True)
        reader, self.channel = await asyncio.open_connection(
            sock=hub_end, limit=protocol.LINE_LIMIT
        )
        if self.lang is not None:
            self._greet()
        self._task(self._listen(reader))

    def _greet(self):
        hello = {"t": "hello", "lang": self.lang}
        self.channel.write(json.dumps(hello).encode() + b"\n")

    @property
    def ready(self) -> bool:
        """Vrai pour un worker lancé, vivant, qu'aucune fermeture ne vise.
        Un worker fini ne l'est pas, même avant qu'asyncio ne l'attende et
        ne pose `returncode` (`_exited`), ni après la fin de la session
        (`ended`)."""
        return (
            self.channel is not None
            and not self.closing
            and not self.ended.is_set()
            and self.proc.returncode is None
            and not _exited(self.proc.pid)
        )

    def adopt(self, sid, lang, cols, rows, on_end):
        """Fait d'un worker de réserve la session `sid` : sa taille d'abord,
        puis `hello` dans la langue du client."""
        self.id, self.lang, self.on_end = sid, lang, on_end
        self.resize(cols, rows)
        self._greet()

    def _task(self, coro):
        task = asyncio.ensure_future(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def _reading(self, on):
        if self.master is None:
            return
        loop = asyncio.get_running_loop()
        if on and not self.eof:
            loop.add_reader(self.master, self._on_output)
        else:
            loop.remove_reader(self.master)

    def _read_master(self) -> bytes:
        """Ce que le maître tient déjà, CHUNK octets au plus. EIO (plus
        aucun esclave ouvert) ou une fin de fichier posent `eof`."""
        parts, size = [], 0
        while size < CHUNK:
            try:
                data = os.read(self.master, CHUNK - size)
            except BlockingIOError:
                break
            except OSError:
                data = b""
            if not data:
                self.eof = True
                break
            parts.append(data)
            size += len(data)
        return b"".join(parts)

    def _on_output(self):
        data = self._read_master()
        if data:
            self.ring.append(data)
            if self.watch is not None:
                self.watch.feed(data)
            if self.client is not None:
                self._flush()
                self._probe_soon()
        if self.eof:
            self._reading(False)

    def _flush(self):
        """Envoie au client ce qui lui manque ; la lecture attend la fin."""
        if self.flushing is None:
            self._reading(False)
            self.flushing = self._task(self._send_backlog())

    async def _send_backlog(self):
        try:
            while self.client is not None and self.sent < self.ring.end:
                client = self.client
                offset, data = self.ring.read(self.sent, CHUNK)
                self.sent = offset + len(data)
                try:
                    await client.send(data)
                except Exception:
                    self.detach(client)
        finally:
            self.flushing = None
            self._reading(True)

    def attach(self, client, after=None) -> tuple:
        """Attache `client` à la place du précédent ; le rejeu part aussitôt.

        Rend `(décalage, tronqué, précédent)` : le décalage du premier
        octet rejoué (`after`, ou le début de l'anneau sans `after`) ; vrai
        si l'anneau a déjà perdu des octets d'avant `after` (0 sans
        `after`) ; le client remplacé, ou None.
        """
        previous, self.client = self.client, client
        wanted = self.ring.start if after is None else after
        self.sent, _ = self.ring.read(wanted, 0)
        self._flush()
        # Le nouveau client reçoit l'état du terminal, même inchangé.
        self.shown = None
        self._probe_soon()
        return self.sent, (after or 0) < self.ring.start, previous

    def detach(self, client):
        """Détache `client` s'il est encore celui de la session."""
        if self.client is client:
            self.client = None
            self.quiet_since = time.monotonic()

    def write(self, data: bytes, lines=False) -> bool:
        """Envoie `data` au terminal, dans l'ordre ; faux, et `data` n'est
        pas gardé, si INPUT_LIMIT octets en attente seraient dépassés.

        Avec `lines`, en mode canonique hors écran alternatif, devant un
        lecteur connu (d'après la dernière sonde), seule la première ligne
        part ; la suite attend dans `held`, derrière ce qu'il retient déjà,
        que `_probe` libère une ligne à la fois hors d'une question du
        worker, et que chaque message du worker jette. Devant un lecteur
        inconnu, `data` part entier : aucune sonde ne libérerait la suite.
        Ce que `held` retenait alors est jeté (`_drop_held`), faute de quoi
        chaque frappe s'y ajouterait sans fin."""
        state = self.state
        if lines and state is not None and state.reader is None:
            self._drop_held()
        waiting = len(self.inbox) + len(self.held)
        if waiting + len(data) > INPUT_LIMIT:
            return False
        if self.master is None:
            return True
        if lines and self.held:
            self.held += data
            return True
        if lines and _by_line(state):
            data, rest = _first_line(data)
            self.held += rest
        self.inbox += data
        self._write_inbox()
        return True

    def _drop_held(self):
        """Jette ce que `held` retient ; le client l'apprend par `dropped`,
        et sans client, le suivant (`unreported`)."""
        if not self.held:
            return
        lost = len(self.held)
        self.held.clear()
        if self.client is None:
            self.unreported += lost
        else:
            self.client.event({"t": "dropped", "bytes": lost})

    def _write_inbox(self):
        loop = asyncio.get_running_loop()
        while self.inbox and self.master is not None:
            try:
                written = os.write(self.master, self.inbox)
            except BlockingIOError:
                loop.add_writer(self.master, self._write_inbox)
                return
            except OSError:
                self.inbox.clear()
                break
            del self.inbox[:written]
        if self.master is not None:
            loop.remove_writer(self.master)

    async def gate(self, data: bytes) -> bytes:
        """Ce que `data`, une frappe ou un collage, peut porter au terminal.

        Le terminal est relu à chaque appel : l'état gardé peut dater
        d'avant la dernière invite, ou d'un lecteur parti depuis. Tout
        passe quand `_open` le permet ; sinon, les seuls caractères de
        signal de `data` (Ctrl+C, Ctrl+\\, Ctrl+Z), que le noyau change en
        signal sans lecteur.

        Un lecteur qui traite la frappe précédente calcule, hors de tout
        appel de lecture, et la sonde ne le voit plus. Quand une sonde en
        a vu un depuis moins de READER_RECENT secondes, `data` attend donc
        qu'il relise, HOLD_SECONDS au plus, sans bloquer la boucle : le
        terminal est relu tous les dixièmes de `gap`, 2 ms pour une sonde
        bon marché. Une invite de secret, déjà là ou venue pendant
        l'attente, fait jeter `data` : une frappe d'avance ne devient pas
        le secret.
        """
        if self.watch is None or self.master is None:
            return data
        self._probe()
        signals = bytes(b for b in data if b in self.state.signals)
        if signals:
            # Comme au terminal, Ctrl+C jette ce qui attend d'être lu.
            self._drop_held()
        if _open(self.state):
            return data
        if signals == data or _secret(self.state):
            return signals
        if self.probed_at - self.read_at > READER_RECENT:
            return signals
        watch, deadline = self.watch, self.probed_at + HOLD_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(self.gap / 10)
            if self.watch is not watch or self.master is None:
                break  # relancée ou finie : un autre terminal
            self._probe()
            if _secret(self.state):
                break
            if _open(self.state):
                return data
        return signals

    def asks_secret(self) -> bool:
        """Vrai si le terminal, relu, attend un secret : écho coupé en mode
        canonique. Faux sans suivi du terminal."""
        if self.watch is None or self.master is None:
            return False
        self._probe()
        return _secret(self.state)

    def _probe_soon(self):
        """Relit le terminal bientôt, `gap` après la lecture précédente au
        plus tôt."""
        if self.probe_timer is None:
            delay = self.probed_at + self.gap - time.monotonic()
            loop = asyncio.get_running_loop()
            self.probe_timer = loop.call_later(max(0.0, delay), self._probe)

    def _probe(self):
        """Relit l'état du terminal ; le client reçoit `tty_state` quand il
        change. Quand l'écho se coupe en mode canonique, une invite de
        secret, ce qui attend d'être lu est jeté, dans le hub comme dans
        le PTY : une frappe d'avance ne devient pas le secret, sauf lue
        avant cette sonde. `gap` suit le coût de la lecture : un arbre de
        processus large la rend plus chère."""
        if self.probe_timer is not None:
            self.probe_timer.cancel()
            self.probe_timer = None
        if self.watch is None or self.master is None:
            return
        self.probed_at = time.monotonic()
        before, self.state = self.state, self.watch.probe()
        if self.state.reader:
            self.read_at = self.probed_at
        cost = time.monotonic() - self.probed_at
        self.gap = min(PROBE_SECONDS, max(PROBE_GAP, 10 * cost))
        if _secret(self.state) and not (
            before is not None and _secret(before)
        ):
            self.inbox.clear()
            self._drop_held()
            asyncio.get_running_loop().remove_writer(self.master)
            self._drop_input()
        elif (
            self.held
            and self.asking is None
            and self.state.reader is True
            and not _secret(self.state)
        ):
            # `_open` laisse aussi passer un lecteur inconnu (setuid : sudo,
            # su), qu'aucune sonde ne voit jamais bloqué en lecture : lui
            # livrer une ligne tenue la ferait passer pour un secret dès que
            # le programme coupe l'écho sans vider son entrée. Devant lui,
            # `held` attend donc un lecteur connu, ou ce qui le jette : un
            # message du worker, Ctrl+C, Arrêter, la frappe suivante, ou
            # `_tick` quand aucun client n'est là pour frapper.
            self._release()
        event = {
            "t": "tty_state",
            "echo": self.state.echo,
            "canon": self.state.canon,
            "reader": self.state.reader,
            "altscreen": self.state.altscreen,
        }
        if self.client is not None and event != self.shown:
            self.shown = event
            self.client.event(event)

    def _release(self):
        """Écrit la ligne suivante de `held` une fois la précédente lue :
        rien n'attend plus, ni dans le hub, ni dans l'esclave."""
        if self.inbox or self._queued():
            return
        line, rest = _first_line(bytes(self.held))
        self.held = bytearray(rest)
        self.inbox += line
        self._write_inbox()

    def _on_slave(self, action, failed=None):
        """`action(fd)` sur l'esclave, rouvert sous son nom sans en devenir
        le terminal de contrôle, puis refermé ; `failed` s'il a disparu ou
        si l'appel échoue."""
        try:
            fd = os.open(self.tty, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError:
            return failed
        try:
            return action(fd)
        except (OSError, termios.error):
            return failed
        finally:
            os.close(fd)

    def _queued(self) -> int:
        """Octets que l'esclave tient, prêts à lire (FIONREAD) ; 0 s'il a
        disparu."""

        def fionread(fd):
            size = bytearray(4)
            fcntl.ioctl(fd, termios.FIONREAD, size)
            return int.from_bytes(size, sys.byteorder)

        return self._on_slave(fionread, 0)

    async def _tick(self):
        """Relit le terminal toutes les PROBE_SECONDS jusqu'à la fin de la
        session, quand un client est attaché ou qu'un collage attend. Sans
        client, un collage qu'un lecteur inconnu retient ne sera plus
        libéré : il est jeté (`_drop_held`) au lieu d'être relu sans fin."""
        while True:
            try:
                await asyncio.wait_for(self.ended.wait(), PROBE_SECONDS)
                return
            except TimeoutError:
                if self.client is not None or self.held:
                    self._probe()
                if self.client is None and self.held:
                    if self.state is not None and self.state.reader is None:
                        self._drop_held()

    def interrupt(self) -> bool:
        """Arrête ce que le worker a lancé ; faux, et rien ne change, s'il
        n'a rien lancé : Arrêter ne quitte jamais TODO.

        Les frappes en attente sont jetées d'abord, celles que le hub garde
        comme celles que le terminal tient déjà, comme Ctrl+C les vide au
        terminal : une commande qui rattrape SIGINT et rend un code ne les
        laisse pas plus répondre à la question suivante qu'une commande
        tuée. Une commande au premier plan reçoit ensuite SIGINT, envoyé à
        son groupe, puis SIGCONT : arrêtée par SIGTSTP, elle garderait
        SIGINT en attente. Un enfant dans le groupe du worker reçoit
        l'octet Ctrl+C, que le noyau change en SIGINT pour tout le groupe :
        le worker revient au menu principal, comme au CLI. L'entrée vidée
        d'abord garde l'octet à portée du noyau, qu'il n'atteint pas
        derrière 4 Kio de lignes non lues.
        """
        if self.master is None or self.proc.returncode is not None:
            return False
        pgrp = self._foreground()
        command = pgrp > 0 and pgrp != self.proc.pid
        if not command and not _has_children(self.proc.pid):
            return False
        self.inbox.clear()
        self._drop_held()
        asyncio.get_running_loop().remove_writer(self.master)
        self._drop_input()
        if command:
            _killpg([pgrp], signal.SIGINT)
            _killpg([pgrp], signal.SIGCONT)
            return True
        try:
            os.write(self.master, b"\x03")
        except OSError:
            return False
        return True

    def _drop_input(self):
        """Vide l'entrée du terminal (TCIFLUSH) par l'esclave (`_on_slave`) :
        vider par le maître viderait la sortie. Un esclave disparu n'a rien
        à vider."""
        self._on_slave(lambda fd: termios.tcflush(fd, termios.TCIFLUSH))

    def resize(self, cols, rows):
        """Nouvelle taille ; le noyau prévient le premier plan (SIGWINCH)."""
        self.cols, self.rows = cols, rows
        if self.master is not None:
            _set_size(self.master, cols, rows)

    def _foreground(self) -> int:
        """Groupe au premier plan du terminal ; 0 sans terminal de contrôle."""
        try:
            return os.tcgetpgrp(self.master)
        except (OSError, TypeError):
            return 0

    @property
    def running(self) -> bool:
        """Vrai quand une commande tient le premier plan : un autre groupe
        que celui du worker."""
        if self.proc is None or self.proc.returncode is not None:
            return False
        pgrp = self._foreground()
        return pgrp > 0 and pgrp != self.proc.pid

    @property
    def busy(self) -> bool:
        """Vrai quand le worker a lancé quelque chose : une commande au
        premier plan, ou un enfant dans son propre groupe (subprocess,
        os.system). Un calcul en Python pur, sans enfant, n'y paraît pas."""
        if self.proc is None or self.proc.returncode is not None:
            return False
        return self.running or _has_children(self.proc.pid)

    def idle(self, now) -> float:
        """Secondes depuis que la session n'a plus ni client ni rien en
        cours (`busy`) ; un appel qui voit l'un ou l'autre remet le compte
        à zéro."""
        if self.client is not None or self.busy:
            self.quiet_since = now
        return now - self.quiet_since

    async def _listen(self, reader):
        """Relaie au client chaque message que `protocol.from_worker`
        admet, et ignore toute autre ligne, trop longue comprise : l'écoute
        ne finit qu'avec le canal. `asking` garde la dernière question
        jusqu'à la réponse de la page ou au message suivant du worker,
        `answered` à la fin de chaque question."""
        while True:
            try:
                line = await reader.readline()
            except ValueError:
                continue  # plus de LINE_LIMIT octets, que readline a jetés
            except ConnectionError:
                return
            if not line:
                return
            message = protocol.from_worker(line)
            if message is None:
                continue
            asked = message["t"] in protocol.QUESTIONS
            self.asking = message if asked else None
            # Chaque message est une borne : ce qui reste d'un collage ne
            # passe pas d'une question, ou d'une commande, à la suivante.
            self._drop_held()
            if self.client is not None:
                self.client.event(message)

    def answer(self, message) -> bool:
        """Porte au worker `answer` ou `cancel` du client pour la question
        ouverte ; faux, et rien ne part, pour un autre `qid`, une valeur
        refusée par `protocol.reply_line`, ou sans worker. La valeur n'est
        gardée ni journalisée nulle part."""
        asking = self.asking["qid"] if self.asking is not None else None
        line = protocol.reply_line(message, asking)
        if line is None or self.channel is None:
            return False
        self.channel.write(line)
        self.asking = None
        self._drop_held()
        return True

    def _hangup(self):
        """Ferme le maître, puis le canal : le noyau raccroche l'esclave,
        SIGHUP au worker s'il vit encore."""
        if self.master is not None:
            loop = asyncio.get_running_loop()
            loop.remove_reader(self.master)
            loop.remove_writer(self.master)
            os.close(self.master)
            self.master = None
        self.inbox.clear()
        self._drop_held()
        if self.channel is not None:
            self.channel.close()
            self.channel = None

    async def _watch(self):
        """Suit le worker : RESTART relance un worker neuf sur un PTY neuf,
        sous le même identifiant et avec le même anneau, RESTART_LIMIT fois
        au plus en RESTART_WINDOW secondes ; toute autre fin, ou une fin
        demandée par `close`, termine la session."""
        restarts = []
        try:
            while True:
                code = await self.proc.wait()
                # Ce que le worker a écrit avant de finir et qui attend.
                while self.master is not None and not self.eof:
                    data = self._read_master()
                    if not data:
                        break
                    self.ring.append(data)
                self._hangup()
                now = time.monotonic()
                restarts = [t for t in restarts if now - t < RESTART_WINDOW]
                if code != RESTART or self.closing:
                    break
                if len(restarts) >= RESTART_LIMIT:
                    break
                restarts.append(now)
                try:
                    await self._spawn()
                except OSError:
                    break
                if self.closing:
                    # `close` est venu pendant la relance : même arrêt, que
                    # `close` attend.
                    self.killing = self._task(self._kill())
        finally:
            # Même sur une erreur imprévue : `close` n'attend pas en vain.
            self.code = self.proc.returncode
            self.ended.set()
            if self.on_end is not None:
                self.on_end(self)
        if self.client is not None:
            # La fin de la sortie d'abord, puis `bye`, au client d'alors.
            self._flush()
            if self.flushing is not None:
                await self.flushing
        if self.client is not None:
            self.client.event({"t": "bye", "code": self.code})
            self.client.close(1000, "session ended")

    async def close(self):
        """Termine la session et rend quand le worker n'est plus, et que
        plus rien ne reste de ses groupes ou que SIGKILL les a vidés ; y
        compris quand l'arrêt est celui que `_watch` lance sur le worker
        d'une relance."""
        self.closing = True
        if self.proc is None:
            return  # pas encore lancé : `start` voit `closing`
        if self.proc.returncode is None:
            await self._kill()
        await self.ended.wait()
        if self.killing is not None:
            await self.killing

    async def _kill(self):
        """Ferme le maître (SIGHUP au worker) et envoie SIGHUP aux groupes
        du worker et de la commande au premier plan ; SIGKILL à ce qui en
        reste après REAP_SECONDS, même quand le worker a fini : une
        commande qui ignore SIGHUP ne survit pas."""
        groups = {self.proc.pid, self._foreground()} - {0}
        self._hangup()
        _killpg(groups, signal.SIGHUP)
        deadline = time.monotonic() + REAP_SECONDS
        try:
            await asyncio.wait_for(
                asyncio.shield(self.ended.wait()), REAP_SECONDS
            )
        except TimeoutError:
            pass
        while _alive(groups) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if _alive(groups):
            _killpg(groups, signal.SIGKILL)
