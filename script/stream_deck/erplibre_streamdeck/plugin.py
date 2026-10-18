# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""What a deck plugin declares.

A plugin module exposes PLUGIN = Plugin(api=PLUGIN_API, ...). Its id is
its file name; the loader sets it. Every callable receives a Context,
and is called with the kernel lock held, except threads the plugin
starts itself (they take ctx.locked())."""

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
class Plugin:
    api: int
    pages: list = field(default_factory=list)
    home_button: HomeButton | None = None
    fixtures: list = field(default_factory=list)
    tiles: list = field(default_factory=list)
    home_tick: Callable | None = None
    home_period: float = 0.0
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
