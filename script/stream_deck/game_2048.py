#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""2048 game.

Corner buttons = directions. Merge tiles to reach 2048!
Top-left=Up, Top-right=Right, Bottom-left=Left, Bottom-right=Down.
"""

import os
import random
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
    "name": "2048",
    "category": "puzzle",
    "multiplayer": False,
    "sdplus": False,
    "description": "Merge tiles to reach 2048! Corner buttons = directions.",
    "icon": "n2048"
}

COLOR_EMPTY = (40, 40, 50)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_GAMEOVER = (180, 0, 0)

TILE_COLORS = {
    0: (40, 40, 50),
    2: (238, 228, 218),
    4: (237, 224, 200),
    8: (242, 177, 121),
    16: (245, 149, 99),
    32: (246, 124, 95),
    64: (246, 94, 59),
    128: (237, 207, 114),
    256: (237, 204, 97),
    512: (237, 200, 80),
    1024: (237, 197, 63),
    2048: (237, 194, 46),
}
TILE_TEXT_DARK = (119, 110, 101)
TILE_TEXT_LIGHT = (255, 255, 255)


class Game2048:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        # Game grid uses inner area (exclude border for controls on small decks)
        self.grid_cols = cols
        self.grid_rows = rows
        self.lock = threading.Lock()
        self.grid = []
        self.game_active = False
        self.game_over = False
        self.score = 0
        self.high_score = 0
        # Direction keys: corners
        self.key_up = 0
        self.key_right = cols - 1
        self.key_left = (rows - 1) * cols
        self.key_down = rows * cols - 1

    def reset(self):
        self.grid = [
            [0] * self.grid_cols for _ in range(self.grid_rows)
        ]
        self.score = 0
        self.game_over = False
        self.game_active = True
        self._spawn()
        self._spawn()

    def _spawn(self):
        empty = [
            (c, r)
            for r in range(self.grid_rows)
            for c in range(self.grid_cols)
            if self.grid[r][c] == 0
        ]
        if empty:
            c, r = random.choice(empty)
            self.grid[r][c] = 4 if random.random() < 0.1 else 2

    def _slide_row(self, row):
        """Slide and merge a single row to the left."""
        tiles = [x for x in row if x != 0]
        merged = []
        skip = False
        for i in range(len(tiles)):
            if skip:
                skip = False
                continue
            if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
                merged.append(tiles[i] * 2)
                self.score += tiles[i] * 2
                skip = True
            else:
                merged.append(tiles[i])
        return merged + [0] * (len(row) - len(merged))

    def move(self, direction):
        if self.game_over:
            return False

        old = [row[:] for row in self.grid]

        if direction == "left":
            for r in range(self.grid_rows):
                self.grid[r] = self._slide_row(self.grid[r])
        elif direction == "right":
            for r in range(self.grid_rows):
                self.grid[r] = self._slide_row(self.grid[r][::-1])[::-1]
        elif direction == "up":
            for c in range(self.grid_cols):
                col = [self.grid[r][c] for r in range(self.grid_rows)]
                col = self._slide_row(col)
                for r in range(self.grid_rows):
                    self.grid[r][c] = col[r]
        elif direction == "down":
            for c in range(self.grid_cols):
                col = [self.grid[r][c] for r in range(self.grid_rows)]
                col = self._slide_row(col[::-1])[::-1]
                for r in range(self.grid_rows):
                    self.grid[r][c] = col[r]

        changed = self.grid != old
        if changed:
            self._spawn()
            if self.score > self.high_score:
                self.high_score = self.score
            if not self._has_moves():
                self.game_over = True
        return changed

    def _has_moves(self):
        for r in range(self.grid_rows):
            for c in range(self.grid_cols):
                if self.grid[r][c] == 0:
                    return True
                if c + 1 < self.grid_cols and self.grid[r][c] == self.grid[r][c + 1]:
                    return True
                if r + 1 < self.grid_rows and self.grid[r][c] == self.grid[r + 1][c]:
                    return True
        return False

    def handle_key(self, key):
        if not self.game_active or self.game_over:
            self.reset()
            self.render()
            return

        if key == self.key_up:
            self.move("up")
        elif key == self.key_down:
            self.move("down")
        elif key == self.key_left:
            self.move("left")
        elif key == self.key_right:
            self.move("right")
        else:
            row = key // self.cols
            col = key % self.cols
            if col < self.cols // 2:
                self.move("left")
            else:
                self.move("right")

        self.render()

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_TITLE, "2048")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.high_score:
                    self._set_key(key, COLOR_SCORE, f"HI:{self.high_score}")
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            return

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols

            if self.game_over:
                val = self.grid[r][c] if r < self.grid_rows and c < self.grid_cols else 0
                if (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "AGAIN")
                elif val > 0:
                    self._set_tile(key, val)
                else:
                    self._set_key(key, COLOR_GAMEOVER, f"S:{self.score}")
            else:
                val = self.grid[r][c] if r < self.grid_rows and c < self.grid_cols else 0
                self._set_tile(key, val)

    def _set_tile(self, key, val):
        color = TILE_COLORS.get(val, TILE_COLORS.get(2048))
        if val == 0:
            self._set_key(key, color, "")
        else:
            text_color = TILE_TEXT_DARK if val <= 4 else TILE_TEXT_LIGHT
            self._set_key(key, color, str(val), text_color=text_color)

    def _set_key(self, key, color, text="", text_color=(255, 255, 255)):
        fmt = self.deck.key_image_format()
        w, h = fmt["size"]
        img = Image.new("RGB", (w, h), color)
        if text:
            draw = ImageDraw.Draw(img)
            font_size = 18 if len(text) <= 4 else 12
            try:
                font = ImageFont.load_default(size=font_size)
            except TypeError:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx, ty = (w - tw) // 2, (h - th) // 2
            draw.text((tx + 1, ty + 1), text, fill=(0, 0, 0), font=font)
            draw.text((tx, ty), text, fill=text_color, font=font)
        native = PILHelper.to_native_key_format(self.deck, img)
        try:
            with self.deck:
                self.deck.set_key_image(key, native)
        except TransportError:
            pass

    def key_callback(self, deck, key, state):
        if not state:
            return
        with self.lock:
            self.handle_key(key)


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
    print(f"2048 on {deck.deck_type()} ({cols}x{rows})")
    print("Corners=directions. TL=Up TR=Right BL=Left BR=Down")

    game = Game2048(deck)
    game.render()
    deck.set_key_callback(game.key_callback)

    try:
        while deck.is_open():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        with deck:
            deck.reset()
            deck.close()
        print(f"\nScore: {game.score} | High: {game.high_score}")



if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
