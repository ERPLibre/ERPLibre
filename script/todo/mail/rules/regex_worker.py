#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Recherche par expression régulière bornée dans le temps.

`re` n'a pas de délai, et ne s'interrompt pas hors du fil principal : un
motif à retour arrière exponentiel (« (a|a)+$ ») ou polynomial
(« .*x.*y », « a*a*b ») sur un sujet ou un corps écrit par un tiers
occuperait le fil des minutes, verrou du compte tenu. Aucune analyse
statique du motif ne les refuse tous sans refuser aussi des motifs
ordinaires.

La recherche s'exécute donc dans un processus fils, lancé au premier
appel et gardé pour les suivants. Une requête qui dépasse son budget tue
le fils et lève `RegexTimeout` ; le suivant est relancé à la requête
d'après. Un seul fil parle au fils à la fois.
"""

from __future__ import annotations

import atexit
import contextlib
import contextvars
import json
import os
import selectors
import subprocess
import sys
import threading
import time

from script.todo.mail.rules.model import RuleError
from script.todo.todo_i18n import t

# Budget d'une requête : toutes les valeurs d'une condition, en secondes.
REGEX_TIMEOUT_S = 1.0
# Délai accordé au démarrage du fils, hors budget de la requête.
START_TIMEOUT_S = 15.0

# Le fils : une requête JSON par ligne, [motif, [textes…]] ; il répond
# l'indice du premier texte trouvé, ou -1. JSON en ASCII : les
# substituts isolés d'un en-tête mal décodé traversent sans erreur.
_CHILD = r"""
import json, re, sys
cache = {}
sys.stdout.write("ready\n")
sys.stdout.flush()
for line in sys.stdin:
    pattern, texts = json.loads(line)
    rx = cache.get(pattern)
    if rx is None:
        if len(cache) >= 256:
            cache.clear()
        rx = cache[pattern] = re.compile(pattern)
    found = next(
        (i for i, text in enumerate(texts) if rx.search(text)), -1
    )
    sys.stdout.write(json.dumps(found) + "\n")
    sys.stdout.flush()
"""


class RegexTimeout(RuleError):
    """La recherche a dépassé son budget ; son verdict est inconnu."""


class _Worker:
    """Le processus fils et le verrou qui sérialise ses requêtes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._buffer = b""

    def search(self, pattern: str, texts: list[str], timeout: float) -> int:
        """L'indice du premier texte où `pattern` trouve, ou -1.

        Lève `RegexTimeout` au-delà de `timeout` secondes, `RuleError` si
        le fils ne démarre pas ou meurt en route.
        """
        request = (json.dumps([pattern, texts]) + "\n").encode("ascii")
        with self._lock:
            proc = self._started()
            try:
                proc.stdin.write(request)
                proc.stdin.flush()
                line = self._readline(proc, timeout)
                return int(json.loads(line))
            except RegexTimeout:
                self._stop()
                raise
            except (OSError, ValueError) as exc:
                self._stop()
                raise RuleError(
                    f"{t('mail_rules_err_regex')} {type(exc).__name__}"
                ) from exc

    def _started(self) -> subprocess.Popen:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        self._stop()
        try:
            proc = subprocess.Popen(
                [sys.executable, "-I", "-S", "-c", _CHILD],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError as exc:
            raise RuleError(
                f"{t('mail_rules_err_regex')} {type(exc).__name__}"
            ) from exc
        self._proc = proc
        try:
            if self._readline(proc, START_TIMEOUT_S) != b"ready":
                raise ValueError("handshake")
        except (RegexTimeout, OSError, ValueError) as exc:
            self._stop()
            raise RuleError(
                f"{t('mail_rules_err_regex')} {type(exc).__name__}"
            ) from exc
        return proc

    def _readline(self, proc: subprocess.Popen, timeout: float) -> bytes:
        """Une ligne du fils, sans son saut ; `RegexTimeout` au-delà du
        délai, `OSError` si le fils ferme sa sortie."""
        deadline = time.monotonic() + timeout
        fd = proc.stdout.fileno()
        with selectors.DefaultSelector() as selector:
            selector.register(fd, selectors.EVENT_READ)
            while b"\n" not in self._buffer:
                left = deadline - time.monotonic()
                if left <= 0 or not selector.select(left):
                    raise RegexTimeout(t("mail_rules_err_regex_timeout"))
                chunk = os.read(fd, 65536)
                if not chunk:
                    raise OSError("worker closed its output")
                self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        return line

    def _stop(self) -> None:
        """Tue le fils s'il vit ; la requête suivante en relance un."""
        proc, self._proc, self._buffer = self._proc, None, b""
        if proc is None:
            return
        try:
            proc.kill()
        except OSError:
            pass
        for stream in (proc.stdin, proc.stdout):
            try:
                stream.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    def close(self) -> None:
        with self._lock:
            self._stop()


_WORKER = _Worker()
atexit.register(_WORKER.close)
# Échéance commune posée par `time_budget`, en temps monotone, ou None.
_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "regex_deadline", default=None
)


@contextlib.contextmanager
def time_budget(seconds: float):
    """Borne le temps cumulé de toutes les recherches du bloc.

    Chaque recherche garde son propre budget, raccourci à ce qui reste ;
    une fois l'échéance passée, elle lève `RegexTimeout` sans rien lancer.
    Sert à un appelant qui évalue le même filtre sur beaucoup de messages
    dans le fil de l'interface.
    """
    token = _DEADLINE.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _DEADLINE.reset(token)


def search_any(
    pattern: str, texts: list[str], *, timeout: float = REGEX_TIMEOUT_S
) -> bool:
    """Vrai si `pattern` (`re.search`) trouve dans un des `texts`.

    Le budget couvre TOUTES les valeurs : une condition sur À/Cc qui porte
    cent adresses coûte au plus `timeout`, pas cent fois. Au-delà, lève
    `RegexTimeout`, jamais un faux : sous un NON, un faux deviendrait un
    vrai et déclencherait un envoi.
    """
    if not texts:
        return False
    deadline = _DEADLINE.get()
    if deadline is not None:
        timeout = min(timeout, deadline - time.monotonic())
        if timeout <= 0:
            raise RegexTimeout(t("mail_rules_err_regex_timeout"))
    return _WORKER.search(pattern, list(texts), timeout) >= 0
