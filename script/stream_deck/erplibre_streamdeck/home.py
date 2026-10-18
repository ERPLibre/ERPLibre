# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The home screen: home buttons, fixtures, and the dashboard.

Home buttons take row 0 in their order, left to right; on a deck of
three rows or more the overflow takes row 1 from column 0 until it is
full; the rest get no key. Fixtures are then placed in their order,
skipping keys already taken. The dashboard is every other key from row
1 on, in reading order, filled by the tile providers in their order.
A render stores which item each dashboard key shows, and a tap reads
that: it opens what the key showed. A face whose paint raises leaves
its key empty."""

from dataclasses import dataclass, field

from erplibre_streamdeck.plugin import KeyFace
from erplibre_streamdeck.ui import colors, i18n

EMPTY = KeyFace(colors.EMPTY, "")


@dataclass
class Allocation:
    home_keys: dict = field(default_factory=dict)
    buttons: dict = field(default_factory=dict)
    fixtures: dict = field(default_factory=dict)
    pool: list = field(default_factory=list)


def _validated_place(fx, geo, home_keys):
    """fx.place's keys as a list of ints, or raise."""
    keys = list(fx.place(geo, home_keys))
    if not all(isinstance(k, int) for k in keys):
        raise TypeError("place must return a list of int keys")
    return keys


def allocate(geo, plugins, guard=None):
    """Lay out `plugins` on `geo`. With `guard` (kernel.guard's
    signature) a fixture whose place raises is skipped."""
    alloc = Allocation()
    with_button = sorted(
        (lp for lp in plugins if lp.plugin.home_button is not None),
        key=lambda lp: (lp.plugin.home_button.order, lp.id),
    )
    for i, lp in enumerate(with_button):
        alloc.home_keys[lp.id] = i if i < geo.cols else -1
    if geo.rows >= 3:
        nxt, end = geo.cols, geo.cols * 2
        for lp in with_button:
            if alloc.home_keys[lp.id] >= 0:
                continue
            if nxt >= end:
                break
            alloc.home_keys[lp.id] = nxt
            nxt += 1
    for lp in with_button:
        key = alloc.home_keys[lp.id]
        if key >= 0:
            alloc.buttons[key] = (lp.id, lp.plugin.home_button)
    taken = set(alloc.buttons)
    fixtures = sorted(
        (
            (fx.order, lp.id, fx)
            for lp in plugins
            for fx in lp.plugin.fixtures
        ),
        key=lambda t: (t[0], t[1]),
    )
    for _, pid, fx in fixtures:
        args = (fx, geo, dict(alloc.home_keys))
        if guard is None:
            keys = _validated_place(*args)
        else:
            ok, keys = guard(pid, "fixture place", _validated_place, *args)
            if not ok:
                continue
        for index, key in enumerate(keys):
            if 0 <= key < geo.total_keys and key not in taken:
                alloc.fixtures[key] = (pid, fx, index)
                taken.add(key)
    alloc.pool = [
        k for k in range(geo.cols, geo.total_keys) if k not in taken
    ]
    return alloc


class Home:
    def __init__(self, geo, plugins, guard=None):
        self.geo = geo
        alloc = allocate(geo, plugins, guard)
        self.home_keys = alloc.home_keys
        self.buttons = alloc.buttons
        self.fixtures = alloc.fixtures
        self.pool = alloc.pool
        self.providers = sorted(
            (
                (tp.order, lp.id, tp)
                for lp in plugins
                for tp in lp.plugin.tiles
            ),
            key=lambda t: (t[0], t[1]),
        )
        self.tile_map = {}

    def _fill(self, kernel):
        """items() of every provider, every render, even with no free
        key: a provider may prune its own state there."""
        tile_map = {}
        cursor = 0
        for _, pid, tp in self.providers:
            ok, items = kernel.guard(
                pid, "tiles", lambda tp=tp, pid=pid: list(
                    tp.items(kernel.ctx(pid))
                ),
            )
            for item in items if ok else []:
                if cursor >= len(self.pool):
                    break
                tile_map[self.pool[cursor]] = (pid, tp, item)
                cursor += 1
        self.tile_map = tile_map

    def _face(self, kernel, key):
        """(owner plugin id, face) of `key`; "kernel" owns the faces it
        draws itself (NO EXT, empty)."""
        if key in self.buttons:
            pid, button = self.buttons[key]
            ok, face = kernel.guard(
                pid, f"home face {key}", button.face, kernel.ctx(pid)
            )
        elif key in self.fixtures:
            pid, fx, index = self.fixtures[key]
            ok, face = kernel.guard(
                pid, f"fixture face {key}", fx.face, kernel.ctx(pid), key,
                index
            )
        elif key in self.tile_map:
            pid, tp, item = self.tile_map[key]
            ok, face = kernel.guard(
                pid, f"tile face {key}", tp.face, kernel.ctx(pid), item
            )
        elif key == 0 and not kernel.dbus_ok:
            return "kernel", KeyFace(colors.ERR, i18n.t("NO\nEXT"))
        else:
            return "kernel", EMPTY
        return pid, (face if ok and isinstance(face, KeyFace) else EMPTY)

    def render(self, kernel):
        self._fill(kernel)
        for key in range(self.geo.total_keys):
            pid, face = self._face(kernel, key)
            # One journal entry per key: a provider whose faces fail on
            # one key and paint on the next is not logged every render.
            ok, _ = kernel.guard(
                pid, f"key {key} paint", kernel.paint, key, face
            )
            if not ok:
                kernel.paint(key, EMPTY)

    def owner(self, key):
        """The plugin id of the button, fixture or last-render tile at
        `key`; None for a key no plugin shows."""
        for table in (self.buttons, self.fixtures, self.tile_map):
            if key in table:
                return table[key][0]
        return None

    def press(self, kernel, key):
        """The press of what `key` showed; the callee renders. A press
        that raises flashes ERR."""
        if key in self.buttons:
            pid, button = self.buttons[key]
            call = (pid, "home press", button.press, kernel.ctx(pid))
        elif key in self.fixtures:
            pid, fx, index = self.fixtures[key]
            call = (pid, "fixture press", fx.press, kernel.ctx(pid), key,
                    index)
        elif key in self.tile_map:
            pid, tp, item = self.tile_map[key]
            call = (pid, "tile press", tp.press, kernel.ctx(pid), item)
        else:
            return
        ok, _ = kernel.guard(*call)
        if not ok:
            kernel.set_flash(False)
            kernel.render()
