#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Sessions du hub web de TODO : un PTY et un worker par session.

Le worker (`python -m script.todo.web.worker`, argv fixe, cwd à la racine
du checkout) tourne dans une session Unix neuve, fd 0-2 sur l'esclave d'un
PTY dont la taille est posée avant le lancement. Une socketpair sert de
canal : le hub y écrit la ligne `hello` (la langue), le worker ses
événements, une ligne JSON chacun ; l'extrémité du worker lui arrive par
`pass_fds`, son numéro dans TODO_WEB_FD. Rien d'un client n'atteint argv.

La sortie du maître s'accumule dans un anneau de RING_SIZE octets, repérés
par un décalage absolu. Sans client, la lecture continue : une commande
n'attend jamais un onglet fermé. Avec un client, elle s'arrête le temps de
lui envoyer ce qui lui manque, CHUNK octets au plus par envoi : un client
lent ralentit la commande, comme un terminal.

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
# Vues que le worker peut faire ouvrir à la page.
VIEWS = ("telemetry",)


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


class Session:
    """Un worker sur son PTY, l'anneau de sa sortie et au plus un client.

    `on_end(session)` est appelé une fois, le worker terminé. `argv`
    remplace le worker dans les tests ; le hub ne le passe jamais.
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
        self.flushing = None
        self.closing = False
        self.killing = None  # l'arrêt que `_watch` lance pendant une relance
        self.code = None
        self.ended = asyncio.Event()
        self.tasks = set()

    async def start(self):
        """Lance le worker ; OSError si le PTY ou le processus manquent. Un
        `close` venu pendant le lancement l'arrête dès qu'il est lancé."""
        await self._spawn()
        self._task(self._watch())
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
        self._reading(True)
        reader, self.channel = await asyncio.open_connection(
            sock=hub_end, limit=CHUNK
        )
        hello = {"t": "hello", "lang": self.lang}
        self.channel.write(json.dumps(hello).encode() + b"\n")
        self._task(self._listen(reader))

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
            if self.client is not None:
                self._flush()
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
        return self.sent, (after or 0) < self.ring.start, previous

    def detach(self, client):
        """Détache `client` s'il est encore celui de la session."""
        if self.client is client:
            self.client = None
            self.quiet_since = time.monotonic()

    def write(self, data: bytes) -> bool:
        """Envoie `data` au terminal, dans l'ordre ; faux, et rien n'est
        gardé, si INPUT_LIMIT octets en attente seraient dépassés."""
        if len(self.inbox) + len(data) > INPUT_LIMIT:
            return False
        if self.master is not None:
            self.inbox += data
            self._write_inbox()
        return True

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
        """Vide l'entrée du terminal (TCIFLUSH) par l'esclave, rouvert sous
        son nom sans en devenir le terminal de contrôle : vider par le
        maître viderait la sortie. Un esclave disparu n'a rien à vider."""
        try:
            fd = os.open(self.tty, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError:
            return
        try:
            termios.tcflush(fd, termios.TCIFLUSH)
        except (OSError, termios.error):
            pass
        finally:
            os.close(fd)

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
        """Relaie au client les `open_view` d'une vue de VIEWS ; toute autre
        ligne du worker est ignorée, une ligne trop longue clôt l'écoute."""
        while True:
            try:
                line = await reader.readline()
            except (ValueError, ConnectionError):
                return
            if not line:
                return
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if (
                isinstance(message, dict)
                and message.get("t") == "open_view"
                and message.get("view") in VIEWS
                and self.client is not None
            ):
                self.client.event({"t": "open_view", "view": message["view"]})

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
