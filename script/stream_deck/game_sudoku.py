#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Sudoku 3x3.

Simplified Sudoku on a 3x3 grid. Fill numbers 1-9 with no repeats
in rows/columns. Press a cell to cycle its number.
Uses center 3x3 of the deck.
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
    "name": "Sudoku 3x3",
    "category": "puzzle",
    "multiplayer": False,
    "sdplus": False,
    "description": "Fill the 3x3 grid. No repeats in rows/columns!",
    "icon": "sudoku"
}

COLOR_FIXED = (60, 80, 120)
COLOR_EDITABLE = (80, 80, 100)
COLOR_ERROR = (160, 40, 40)
COLOR_CORRECT = (0, 140, 60)
COLOR_EMPTY = (20, 20, 30)
COLOR_TITLE = (0, 80, 160)
COLOR_WIN = (0, 200, 60)
NUM_COLORS = {
    1: (80, 80, 255), 2: (0, 180, 0), 3: (255, 50, 50),
    4: (200, 180, 0), 5: (180, 0, 180), 6: (0, 180, 180),
    7: (255, 140, 0), 8: (100, 200, 0), 9: (200, 100, 200),
}


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 26 if len(text) <= 1 else 16
        try:
            font = ImageFont.load_default(size=fs)
        except TypeError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((w - tw) // 2 + 1, (h - th) // 2 + 1), text, fill=(0, 0, 0), font=font)
        draw.text(((w - tw) // 2, (h - th) // 2), text, fill=(255, 255, 255), font=font)
    native = PILHelper.to_native_key_format(deck, img)
    try:
        with deck:
            deck.set_key_image(key, native)
    except TransportError:
        pass


class Sudoku3:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.off_c = (cols - 3) // 2
        self.off_r = (rows - 3) // 2
        self.grid = [[0] * 3 for _ in range(3)]
        self.fixed = [[False] * 3 for _ in range(3)]
        self.game_active = False
        self.won = False
        self.wins = 0

    def reset(self):
        # Generate a valid 3x3 latin square then remove some
        nums = list(range(1, 4)) * 3
        # Simple valid 3x3
        base = [[1, 2, 3], [2, 3, 1], [3, 1, 2]]
        # Shuffle rows and cols
        perm = list(range(3))
        random.shuffle(perm)
        shuffled = [base[perm[r]] for r in range(3)]
        cperm = list(range(3))
        random.shuffle(cperm)
        self.grid = [[shuffled[r][cperm[c]] for c in range(3)] for r in range(3)]
        self.fixed = [[True] * 3 for _ in range(3)]
        # Remove 4-5 cells
        cells = [(r, c) for r in range(3) for c in range(3)]
        random.shuffle(cells)
        for r, c in cells[:random.randint(4, 5)]:
            self.grid[r][c] = 0
            self.fixed[r][c] = False
        self.won = False
        self.game_active = True

    def _grid_to_key(self, gr, gc):
        return (self.off_r + gr) * self.cols + (self.off_c + gc)

    def _key_to_grid(self, key):
        c = key % self.cols - self.off_c
        r = key // self.cols - self.off_r
        if 0 <= c < 3 and 0 <= r < 3:
            return r, c
        return -1, -1

    def _check_valid(self):
        for r in range(3):
            vals = [self.grid[r][c] for c in range(3) if self.grid[r][c] > 0]
            if len(vals) != len(set(vals)):
                return False
        for c in range(3):
            vals = [self.grid[r][c] for r in range(3) if self.grid[r][c] > 0]
            if len(vals) != len(set(vals)):
                return False
        return True

    def _check_win(self):
        if any(self.grid[r][c] == 0 for r in range(3) for c in range(3)):
            return False
        return self._check_valid()

    def handle_key(self, key):
        if self.won or not self.game_active:
            self.reset()
            self.render()
            return

        gr, gc = self._key_to_grid(key)
        if gr < 0 or self.fixed[gr][gc]:
            return

        self.grid[gr][gc] = (self.grid[gr][gc] % 3) + 1

        if self._check_win():
            self.won = True
            self.wins += 1

        self.render()

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_TITLE, "SUDO")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            gr, gc = self._key_to_grid(key)

            if gr >= 0:
                val = self.grid[gr][gc]
                if self.won:
                    set_key(self.deck, key, COLOR_WIN, str(val))
                elif val == 0:
                    set_key(self.deck, key, COLOR_EDITABLE, "")
                elif self.fixed[gr][gc]:
                    set_key(self.deck, key, NUM_COLORS.get(val, COLOR_FIXED), str(val))
                else:
                    set_key(self.deck, key, NUM_COLORS.get(val, COLOR_EDITABLE), str(val))
            elif self.won and (c, r) == (mid_c, last_r):
                set_key(self.deck, key, COLOR_TITLE, "AGAIN")
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

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
    print(f"Sudoku 3x3 on {deck.deck_type()}")
    print("Press cells to cycle numbers. No repeats in rows/cols!")
    game = Sudoku3(deck)
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
        print(f"\nWins: {game.wins}")



if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
