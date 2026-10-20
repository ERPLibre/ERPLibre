# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""What a deck plugin declares.

A plugin module exposes PLUGIN = Plugin(api=PLUGIN_API, ...). Its id is
its file name; the loader sets it. Every callable receives a Context,
and is called with the kernel lock held, except Poll.read (no Context,
no lock) and threads the plugin starts itself (they take
ctx.locked())."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

PLUGIN_API = 1


@dataclass(frozen=True)
class Geometry:
    cols: int
    rows: int
    total_keys: int


@dataclass(frozen=True)
class KeyFace:
    color: tuple
    text: str = ""
    icon: str | None = None
    extra_draw: Callable | None = None


@dataclass
class Page:
    """A deck page. `keys(geo)` names the page's key indexes, once per
    start, or None when the deck is too small; pass keys=None when the
    page computes its keys itself. `tick(ctx, now)` runs every `period`
    seconds while the page shows (0.0: every loop pass)."""

    id: str
    keys: Callable[[Geometry], Any] | None
    render: Callable
    handle: Callable
    tick: Callable | None = None
    period: float = 0.0


@dataclass
class HomeButton:
    """A key on the home rows; `order` places it (lower first)."""

    order: int
    face: Callable
    press: Callable


@dataclass
class Fixture:
    """Keys a plugin places itself on the home screen.
    `place(geo, home_keys)` returns the keys, given each plugin's home
    button key (-1 when it has none); face(ctx, key, index) returns a
    KeyFace or None (painted empty); press(ctx, key, index)."""

    order: int
    place: Callable
    face: Callable
    press: Callable


@dataclass
class TileProvider:
    """Dashboard tiles: items(ctx) once per home render, face(ctx, item),
    press(ctx, item) with the item the key showed."""

    order: int
    items: Callable
    face: Callable
    press: Callable


@dataclass
class Poll:
    """Data a render needs, read away from the lock. active(ctx) says,
    under the lock, whether it is needed now; read() runs in the loop
    thread without the lock and must not touch a Context; store(ctx,
    data) keeps it, under the lock, and returns True when what the deck
    shows changed."""

    period: float
    active: Callable
    read: Callable
    store: Callable


class RepeatLog:
    """The journal of a Poll.read, which fails the same way on every
    pass while its cause lasts (an absent D-Bus method, a missing
    tool).

    `with repeat_log.watch() as log:` wraps one pass; log(msg) records
    a failure of that pass, as one line. When the block ends, the
    failures are written through write(line) if they differ from the
    previous pass's, and nothing is written while they repeat. The
    first pass without failure after one writes `<what>: recovered`.
    A block that raises leaves the state as it was: the kernel
    journals the exception itself."""

    def __init__(self, write, what):
        self._write = write
        self._what = what
        # The failures of the last pass, None after a clean pass.
        self._failing = None

    @contextmanager
    def watch(self):
        failures = []
        yield lambda msg: failures.append(" ".join(str(msg).split()))
        if failures:
            if tuple(failures) != self._failing:
                for line in failures:
                    self._write(line)
            self._failing = tuple(failures)
        elif self._failing is not None:
            self._failing = None
            self._write(f"{self._what}: recovered")


@dataclass
class Plugin:
    api: int
    pages: list = field(default_factory=list)
    home_button: HomeButton | None = None
    fixtures: list = field(default_factory=list)
    tiles: list = field(default_factory=list)
    home_tick: Callable | None = None
    home_period: float = 0.0
    # Polls each have their own `period` stamp; a busy plugin's are
    # skipped (see Poll).
    polls: list = field(default_factory=list)
    setup: Callable | None = None
    # shutdown(ctx) runs with the kernel lock held, like every other
    # callable, or without it when a key callback still holds it after
    # app.SHUTDOWN_LOCK_SEC. It must not take ctx.locked() nor wait for
    # a thread that does: the lock is not reentrant, and the deck is
    # reset only once every shutdown has returned. It may terminate
    # processes and signal threads to stop.
    shutdown: Callable | None = None


@dataclass
class LoadedPlugin:
    id: str
    plugin: Plugin
    origin: str  # "repo" or "user"
    path: Path
