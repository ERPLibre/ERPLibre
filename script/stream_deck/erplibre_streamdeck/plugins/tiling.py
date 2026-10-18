# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Tiling: pick two corners on the deck grid, the focused window is
tiled to that box by the extension's TileWindow method."""

import time

from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Page, Plugin,
)
from erplibre_streamdeck.ui import colors

# A half-started selection drops back home after this much inactivity.
TILING_IDLE_TIMEOUT_SEC = 5.0


def _setup(ctx):
    st = ctx.state()
    st.corner1 = None
    st.last_touch = 0.0


def _tile_via_dbus(dbus, log, grid_cols, grid_rows, c1, r1, c2, r2):
    """Ask the extension to tile the focused window onto the box
    (c1, r1)-(c2, r2) of a grid_cols x grid_rows grid. Runs outside the
    lock: only `dbus` and `log`."""
    try:
        r = dbus.call(
            "TileWindow", grid_cols, grid_rows, c1, r1, c2, r2, timeout=3
        )
        if r.true:
            return True
        log(f"Tiler dbus: {r.stdout} {r.stderr}")
        return False
    except Exception as e:
        log(f"Tiler dbus error: {e}")
        return False


def _render(ctx):
    corner1 = ctx.state().corner1
    cols = ctx.geo.cols
    for key in range(ctx.geo.total_keys):
        r = key // cols
        c = key % cols
        if (c, r) == corner1:
            ctx.set_key(key, colors.SELECTED, "1")
        else:
            ctx.set_key(key, colors.GRID, f"{c},{r}")


def _handle(ctx, key):
    st = ctx.state()
    # Bump the inactivity timer so the auto-cancel does not fire while
    # the user is actively picking corners.
    st.last_touch = time.monotonic()
    cols = ctx.geo.cols
    col = key % cols
    row = key // cols
    if st.corner1 is None:
        st.corner1 = (col, row)
        ctx.render()
        return
    rows = ctx.geo.rows
    c1 = min(st.corner1[0], col)
    r1 = min(st.corner1[1], row)
    c2 = max(st.corner1[0], col)
    r2 = max(st.corner1[1], row)
    # The selection ends with this press: the idle timeout has nothing
    # left to cancel once the job hands its result back.
    st.last_touch = 0.0
    st.corner1 = None
    dbus, log = ctx.dbus, ctx.log

    def done(ctx, ok, error):
        if ok and error is None:
            ctx.flash(True)
        else:
            ctx.flash(
                False,
                f"TileWindow({cols}x{rows} "
                f"{c1},{r1}-{c2},{r2}) failed via D-Bus",
            )
        ctx.home()

    ctx.run_blocking(
        lambda: _tile_via_dbus(dbus, log, cols, rows, c1, r1, c2, r2),
        done,
    )


def _tick(ctx, now):
    """Idle too long while picking corners: drop back home without
    touching the focused window. The delay runs from the last press,
    so the tick runs every pass."""
    st = ctx.state()
    if (
        st.last_touch > 0
        and now - st.last_touch >= TILING_IDLE_TIMEOUT_SEC
    ):
        st.corner1 = None
        st.last_touch = 0.0
        ctx.home()


def _press(ctx):
    st = ctx.state()
    st.corner1 = None
    st.last_touch = time.monotonic()
    ctx.goto("tiling")


PLUGIN = Plugin(
    api=PLUGIN_API,
    setup=_setup,
    pages=[
        Page("tiling", lambda geo: {}, _render, _handle, _tick, 0.0)
    ],
    home_button=HomeButton(
        10,
        face=lambda ctx: KeyFace(
            colors.TITLE, ctx.t("TILE"), icon="tile"
        ),
        press=_press,
    ),
)
