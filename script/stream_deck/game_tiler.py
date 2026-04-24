#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Window Tiler — tile windows via Stream Deck.

Press a button to enter tiling mode. Grid appears on the deck.
Press first corner, then second corner. The focused window is
tiled to that region via D-Bus (streamdeck-tiler gnome extension).
"""

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
COLOR_ACTIVE = (255, 200, 0)
COLOR_OK = (0, 200, 60)
COLOR_ERR = (200, 0, 0)

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
        self.tiling = False
        self.corner1 = None  # (col, row)
        self.corner2 = None
        self.last_result = None  # "ok" or "err"
        self.result_time = 0
        self.dbus_ok = _check_dbus_available()

    def handle_key(self, key, state):
        if not state:
            return
        col = key % self.cols
        row = key // self.cols

        # Check for result display timeout
        if self.last_result and time.monotonic() - self.result_time < 1.5:
            return

        if not self.tiling:
            # Any key enters tiling mode
            self.tiling = True
            self.corner1 = None
            self.corner2 = None
            self.last_result = None
            self.render()
            return

        if self.corner1 is None:
            # First corner
            self.corner1 = (col, row)
            self.render()
        else:
            # Second corner — apply tiling
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
            self.tiling = False
            self.corner1 = None
            self.corner2 = None
            self.render()

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

        if not self.tiling:
            # Idle: show "TILE" button in center, rest dark
            mid_c = self.cols // 2
            mid_r = self.rows // 2
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, mid_r):
                    set_key(self.deck, key, COLOR_TITLE, "TILE")
                elif (c, r) == (mid_c, 0):
                    if not self.dbus_ok:
                        set_key(self.deck, key, COLOR_ERR, "NO\nEXT")
                    else:
                        set_key(self.deck, key, COLOR_EMPTY, "")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        # Tiling mode: show grid
        # Build preview region if corner1 is set
        preview = set()
        if self.corner1:
            # Show hover preview assuming corner2 could be any cell
            preview.add(self.corner1)

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols

            if (c, r) == self.corner1:
                set_key(self.deck, key, COLOR_SELECTED, "1")
            elif (c, r) in preview:
                set_key(self.deck, key, COLOR_PREVIEW, "")
            else:
                # Grid cell with coordinates
                label = f"{c},{r}"
                set_key(self.deck, key, COLOR_GRID, label)

    def loop(self):
        """Refresh loop for result timeout."""
        while self.running and self.deck.is_open():
            if self.last_result:
                elapsed = time.monotonic() - self.result_time
                if elapsed >= 1.5:
                    with self.lock:
                        self.render()
            time.sleep(0.3)


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

    print("Press any button to enter tiling mode.")
    print("Then press first corner, then second corner.")

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
