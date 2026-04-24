#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Window Tiler — tile windows via Stream Deck.

Press TILE to enter tiling mode. Grid appears on the deck.
Press first corner, then second corner. The focused window is
tiled to that region via D-Bus (streamdeck-tiler gnome extension).

Press TIMER to list timers from the tracker@aliakseiz.github.com
extension and start/stop them.
"""

import json
import subprocess
import sys
import threading
import time

try:
    from PIL import Image, ImageDraw, ImageFont
    from StreamDeck.DeviceManager import DeviceManager
    from StreamDeck.ImageHelpers import PILHelper
    from StreamDeck.Transport.Transport import TransportError
except ImportError as e:
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

GAME_META = {
    "name": "Window Tiler",
    "category": "sim",
    "multiplayer": False,
    "sdplus": False,
    "description": "Tile windows on a grid. Pick two corners to place.",
    "icon": "tiler"
}

COLOR_EMPTY = (20, 20, 30)
COLOR_GRID = (40, 60, 100)
COLOR_SELECTED = (0, 180, 255)
COLOR_PREVIEW = (0, 120, 60)
COLOR_TITLE = (0, 80, 160)
COLOR_TIMER_TITLE = (120, 60, 0)
COLOR_TIMER_RUNNING = (0, 160, 40)
COLOR_TIMER_PAUSED = (50, 70, 110)
COLOR_BACK = (60, 60, 60)
COLOR_REFRESH = (80, 80, 110)
COLOR_NEW = (140, 80, 160)
COLOR_ACTIVE = (255, 200, 0)
COLOR_OK = (0, 200, 60)
COLOR_ERR = (200, 0, 0)

MODE_IDLE = "idle"
MODE_TILING = "tiling"
MODE_TIMER_LIST = "timer_list"

DBUS_DEST = "org.gnome.Shell"
DBUS_PATH = "/org/gnome/Shell/Extensions/StreamDeckTiler"
DBUS_IFACE = "org.gnome.Shell.Extensions.StreamDeckTiler"


def _tile_via_dbus(grid_cols, grid_rows, c1, r1, c2, r2):
    """Call the GNOME extension to tile the focused window."""
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
                "--method", f"{DBUS_IFACE}.TileWindow",
                str(grid_cols), str(grid_rows),
                str(c1), str(r1), str(c2), str(r2),
            ],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and "true" in result.stdout.lower():
            return True
        print(f"Tiler dbus: {result.stdout} {result.stderr}")
        return False
    except Exception as e:
        print(f"Tiler dbus error: {e}")
        return False


def _check_dbus_available():
    """Check if the streamdeck-tiler extension is available."""
    try:
        result = subprocess.run(
            [
                "gdbus", "introspect", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
            ],
            capture_output=True, text=True, timeout=3,
        )
        return "TileWindow" in result.stdout
    except Exception:
        return False


def _parse_gdbus_string_tuple(output):
    """Extract the string from gdbus output of form ('...',).

    GVariant single-quoted strings only need to escape backslash and
    single quote. Double quotes (from JSON content) pass through.
    """
    s = output.strip()
    if not (s.startswith("('") and s.endswith("',)")):
        return None
    inner = s[2:-3]
    # Unescape \\ and \' — placeholder avoids double substitution
    return (
        inner.replace("\\\\", "\x00")
        .replace("\\'", "'")
        .replace("\x00", "\\")
    )


def _list_tracker_timers():
    """Call the extension to list tracker timers. Returns list of dicts."""
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
                "--method", f"{DBUS_IFACE}.ListTrackerTimers",
            ],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            print(f"Timer list dbus: {result.stderr}")
            return []
        payload = _parse_gdbus_string_tuple(result.stdout)
        if not payload:
            return []
        return json.loads(payload)
    except Exception as e:
        print(f"Timer list error: {e}")
        return []


def _toggle_tracker_timer(timer_id):
    """Call the extension to toggle a tracker timer by id."""
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
                "--method", f"{DBUS_IFACE}.ToggleTrackerTimer",
                timer_id,
            ],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and "true" in result.stdout.lower():
            return True
        print(f"Timer toggle dbus: {result.stdout} {result.stderr}")
        return False
    except Exception as e:
        print(f"Timer toggle error: {e}")
        return False


def _add_tracker_timer():
    """Call the extension to add a new tracker timer and open edit mode.

    Returns the new timer id on success, empty string on failure.
    """
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", DBUS_DEST,
                "--object-path", DBUS_PATH,
                "--method", f"{DBUS_IFACE}.AddTrackerTimer",
            ],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            print(f"Timer add dbus: {result.stderr}")
            return ""
        payload = _parse_gdbus_string_tuple(result.stdout)
        return payload or ""
    except Exception as e:
        print(f"Timer add error: {e}")
        return ""


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 20 if len(text) <= 2 else 14 if len(text) <= 4 else 11
        try:
            font = ImageFont.load_default(size=fs)
        except TypeError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            ((w - tw) // 2 + 1, (h - th) // 2 + 1),
            text, fill=(0, 0, 0), font=font,
        )
        draw.text(
            ((w - tw) // 2, (h - th) // 2),
            text, fill=(255, 255, 255), font=font,
        )
    native = PILHelper.to_native_key_format(deck, img)
    try:
        with deck:
            deck.set_key_image(key, native)
    except TransportError:
        pass


class Tiler:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.running = True
        # Grid = full deck (each button = one grid cell)
        self.grid_cols = cols
        self.grid_rows = rows
        # State
        self.mode = MODE_IDLE
        self.corner1 = None  # (col, row)
        self.corner2 = None
        self.last_result = None  # "ok" or "err"
        self.result_time = 0
        self.dbus_ok = _check_dbus_available()
        # Timer state
        self.timers = []  # list of dicts from _list_tracker_timers
        # Map: key index -> timer id (for timer list mode)
        self.timer_key_map = {}
        # Idle entry points
        self._compute_idle_buttons()

    def _compute_idle_buttons(self):
        """Pick keys for the TILE and TIMER entry buttons."""
        mid_c = self.cols // 2
        mid_r = self.rows // 2
        if self.cols >= 2:
            tile_pos = (max(mid_c - 1, 0), mid_r)
            timer_pos = (mid_c, mid_r)
        elif self.rows >= 2:
            tile_pos = (0, mid_r)
            timer_pos = (0, min(mid_r + 1, self.rows - 1))
            if tile_pos == timer_pos:
                tile_pos = (0, max(mid_r - 1, 0))
        else:
            tile_pos = (0, 0)
            timer_pos = (0, 0)  # single-key deck: TILE only
        self.tile_key = tile_pos[1] * self.cols + tile_pos[0]
        self.timer_key = timer_pos[1] * self.cols + timer_pos[0]

    # ---------- Key handling ----------

    def handle_key(self, key, state):
        if not state:
            return

        # Block input during result flash
        if self.last_result and time.monotonic() - self.result_time < 1.5:
            return

        if self.mode == MODE_IDLE:
            self._handle_idle_key(key)
        elif self.mode == MODE_TILING:
            self._handle_tiling_key(key)
        elif self.mode == MODE_TIMER_LIST:
            self._handle_timer_list_key(key)

    def _handle_idle_key(self, key):
        if key == self.timer_key and self.timer_key != self.tile_key:
            self._enter_timer_mode()
        elif key == self.tile_key:
            self.mode = MODE_TILING
            self.corner1 = None
            self.corner2 = None
            self.last_result = None
            self.render()
        else:
            # Legacy behavior: any key also enters tiling mode
            self.mode = MODE_TILING
            self.corner1 = None
            self.corner2 = None
            self.last_result = None
            self.render()

    def _handle_tiling_key(self, key):
        col = key % self.cols
        row = key // self.cols
        if self.corner1 is None:
            self.corner1 = (col, row)
            self.render()
            return
        self.corner2 = (col, row)
        c1 = min(self.corner1[0], self.corner2[0])
        r1 = min(self.corner1[1], self.corner2[1])
        c2 = max(self.corner1[0], self.corner2[0])
        r2 = max(self.corner1[1], self.corner2[1])
        ok = _tile_via_dbus(
            self.grid_cols, self.grid_rows, c1, r1, c2, r2
        )
        self.last_result = "ok" if ok else "err"
        self.result_time = time.monotonic()
        self.mode = MODE_IDLE
        self.corner1 = None
        self.corner2 = None
        self.render()

    def _handle_timer_list_key(self, key):
        # Layout: 0 = BACK, total-2 = NEW, total-1 = REFRESH
        if key == 0:
            self.mode = MODE_IDLE
            self.render()
            return
        if key == self.total_keys - 1:
            self._refresh_timers()
            self.render()
            return
        if key == self.total_keys - 2:
            new_id = _add_tracker_timer()
            if new_id:
                self._refresh_timers()
                self.render()
            else:
                self.last_result = "err"
                self.result_time = time.monotonic()
                self.render()
            return
        timer_id = self.timer_key_map.get(key)
        if not timer_id:
            return
        ok = _toggle_tracker_timer(timer_id)
        if ok:
            self._refresh_timers()
            self.render()
        else:
            self.last_result = "err"
            self.result_time = time.monotonic()
            self.render()

    def _enter_timer_mode(self):
        self.mode = MODE_TIMER_LIST
        self._refresh_timers()
        self.render()

    def _refresh_timers(self):
        self.timers = _list_tracker_timers()
        self.timer_key_map = {}
        # Keys for timers: 1 .. total-3 (skip BACK=0, NEW=total-2, REFRESH=last)
        usable = list(range(1, self.total_keys - 2))
        for idx, timer in enumerate(self.timers):
            if idx >= len(usable):
                break
            self.timer_key_map[usable[idx]] = timer.get("id")

    # ---------- Rendering ----------

    def render(self):
        # Result flash
        if self.last_result:
            elapsed = time.monotonic() - self.result_time
            if elapsed < 1.5:
                color = COLOR_OK if self.last_result == "ok" else COLOR_ERR
                label = "OK!" if self.last_result == "ok" else "ERR"
                for key in range(self.total_keys):
                    set_key(self.deck, key, color, label)
                return
            self.last_result = None

        if self.mode == MODE_IDLE:
            self._render_idle()
        elif self.mode == MODE_TILING:
            self._render_tiling()
        elif self.mode == MODE_TIMER_LIST:
            self._render_timer_list()

    def _render_idle(self):
        for key in range(self.total_keys):
            if key == self.tile_key:
                set_key(self.deck, key, COLOR_TITLE, "TILE")
            elif key == self.timer_key and self.timer_key != self.tile_key:
                set_key(self.deck, key, COLOR_TIMER_TITLE, "TIMER")
            elif key == 0 and not self.dbus_ok:
                set_key(self.deck, key, COLOR_ERR, "NO\nEXT")
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_tiling(self):
        preview = set()
        if self.corner1:
            preview.add(self.corner1)
        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols
            if (c, r) == self.corner1:
                set_key(self.deck, key, COLOR_SELECTED, "1")
            elif (c, r) in preview:
                set_key(self.deck, key, COLOR_PREVIEW, "")
            else:
                label = f"{c},{r}"
                set_key(self.deck, key, COLOR_GRID, label)

    def _render_timer_list(self):
        for key in range(self.total_keys):
            if key == 0:
                set_key(self.deck, key, COLOR_BACK, "BACK")
                continue
            if key == self.total_keys - 1:
                set_key(self.deck, key, COLOR_REFRESH, "RFSH")
                continue
            if key == self.total_keys - 2:
                set_key(self.deck, key, COLOR_NEW, "NEW")
                continue
            timer_id = self.timer_key_map.get(key)
            if not timer_id:
                # Empty slot — show hint if no timers exist at all
                if not self.timers and key == 1:
                    set_key(self.deck, key, COLOR_EMPTY, "NO\nTIMERS")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
                continue
            timer = next(
                (t for t in self.timers if t.get("id") == timer_id), None
            )
            if not timer:
                set_key(self.deck, key, COLOR_EMPTY, "")
                continue
            color = (
                COLOR_TIMER_RUNNING if timer.get("running")
                else COLOR_TIMER_PAUSED
            )
            label = _label_for_timer(timer)
            set_key(self.deck, key, color, label)

    def loop(self):
        """Refresh loop: clear result flash + refresh timer list."""
        last_timer_refresh = 0
        while self.running and self.deck.is_open():
            now = time.monotonic()
            with self.lock:
                if self.last_result:
                    elapsed = now - self.result_time
                    if elapsed >= 1.5:
                        self.render()
                elif self.mode == MODE_TIMER_LIST:
                    # Auto-refresh every 2s to update elapsed time labels
                    if now - last_timer_refresh >= 2.0:
                        self._refresh_timers()
                        self.render()
                        last_timer_refresh = now
            time.sleep(0.3)


def _label_for_timer(timer):
    """Build a short 2-line label: first word of name + mm:ss."""
    name = timer.get("name") or "?"
    first = name.split()[0] if name.split() else name
    if len(first) > 6:
        first = first[:6]
    elapsed = int(timer.get("elapsed") or 0)
    mm = elapsed // 60
    ss = elapsed % 60
    return f"{first}\n{mm:02d}:{ss:02d}"


def main():
    streamdecks = DeviceManager().enumerate()
    deck = next((d for d in streamdecks if d.is_visual()), None)
    if not deck:
        print("No visual Stream Deck found.")
        sys.exit(1)
    deck.open()
    deck.reset()
    deck.set_brightness(80)

    rows, cols = deck.key_layout()
    print(f"Window Tiler on {deck.deck_type()} ({cols}x{rows})")

    dbus_ok = _check_dbus_available()
    if dbus_ok:
        print("D-Bus tiler extension detected!")
    else:
        print("WARNING: streamdeck-tiler extension not found.")
        print("Install: re-login to GNOME to activate the extension.")

    print("Press TILE to enter tiling mode (first corner, second corner).")
    print("Press TIMER to list and toggle tracker timers.")

    game = Tiler(deck)
    game.render()

    def key_cb(d, k, s):
        with game.lock:
            game.handle_key(k, s)

    deck.set_key_callback(key_cb)

    t = threading.Thread(target=game.loop, daemon=True)
    t.start()

    try:
        while deck.is_open():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        game.running = False
        with deck:
            deck.reset()
            deck.close()


if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
