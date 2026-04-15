#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Tetris for Elgato Stream Deck (adapts to any layout, rotated 90).

Pieces fall from right to left. Press top row to rotate, bottom row to
drop. Press middle rows to move piece up/down.
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

PIECES = {
    "I": [(0, 0), (1, 0), (2, 0), (3, 0)],
    "O": [(0, 0), (1, 0), (0, 1), (1, 1)],
    "T": [(0, 0), (1, 0), (2, 0), (1, 1)],
    "L": [(0, 0), (1, 0), (2, 0), (2, 1)],
    "S": [(1, 0), (2, 0), (0, 1), (1, 1)],
}
PIECE_COLORS = {
    "I": (0, 220, 220),
    "O": (220, 220, 0),
    "T": (160, 0, 220),
    "L": (220, 140, 0),
    "S": (0, 220, 0),
}
COLOR_EMPTY = (20, 20, 30)
COLOR_FROZEN = (100, 100, 120)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)

TICK_SPEED = 0.6


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 18 if len(text) <= 3 else 12
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


class Tetris:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.running = True
        self.grid = {}
        self.piece = None
        self.piece_type = None
        self.piece_pos = (0, 0)
        self.score = 0
        self.game_active = False
        self.game_over = False

    def reset(self):
        self.grid = {}
        self.score = 0
        self.game_over = False
        self.game_active = True
        self._new_piece()

    def _new_piece(self):
        self.piece_type = random.choice(list(PIECES.keys()))
        self.piece = PIECES[self.piece_type][:]
        self.piece_pos = (self.cols - 2, self.rows // 2 - 1)
        if self._collides(self.piece_pos):
            self.game_over = True

    def _get_cells(self, pos=None):
        px, py = pos or self.piece_pos
        return [(px + dx, py + dy) for dx, dy in self.piece]

    def _collides(self, pos):
        for x, y in self._get_cells(pos):
            if x < 0 or x >= self.cols or y < 0 or y >= self.rows:
                return True
            if (x, y) in self.grid:
                return True
        return False

    def _freeze(self):
        color = PIECE_COLORS.get(self.piece_type, COLOR_FROZEN)
        for x, y in self._get_cells():
            self.grid[(x, y)] = color
        self._clear_columns()
        self._new_piece()

    def _clear_columns(self):
        """Clear full columns (rotated tetris: columns instead of rows)."""
        cleared = 0
        c = 0
        while c < self.cols:
            if all((c, r) in self.grid for r in range(self.rows)):
                cleared += 1
                for r in range(self.rows):
                    del self.grid[(c, r)]
                # Shift all columns right of this one to the left... wait, in our rotated version
                # pieces fall left, so we shift columns to the right
                new_grid = {}
                for (gc, gr), color in self.grid.items():
                    if gc > c:
                        new_grid[(gc - 1, gr)] = color
                    else:
                        new_grid[(gc, gr)] = color
                self.grid = new_grid
            else:
                c += 1
        self.score += cleared * 10

    def tick(self):
        if not self.game_active or self.game_over:
            return
        new_pos = (self.piece_pos[0] - 1, self.piece_pos[1])
        if self._collides(new_pos):
            self._freeze()
        else:
            self.piece_pos = new_pos

    def _rotate(self):
        rotated = [(-dy, dx) for dx, dy in self.piece]
        min_x = min(x for x, y in rotated)
        min_y = min(y for x, y in rotated)
        self.piece = [(x - min_x, y - min_y) for x, y in rotated]
        if self._collides(self.piece_pos):
            self.piece = PIECES[self.piece_type][:]

    def handle_key(self, key):
        if self.game_over or not self.game_active:
            self.reset()
            return

        col = key % self.cols
        row = key // self.cols

        if row == 0:
            self._rotate()
        elif row == self.rows - 1:
            # Hard drop left
            while not self._collides((self.piece_pos[0] - 1, self.piece_pos[1])):
                self.piece_pos = (self.piece_pos[0] - 1, self.piece_pos[1])
            self._freeze()
        else:
            # Move up/down
            if row < self.rows // 2:
                new_pos = (self.piece_pos[0], self.piece_pos[1] - 1)
            else:
                new_pos = (self.piece_pos[0], self.piece_pos[1] + 1)
            if not self._collides(new_pos):
                self.piece_pos = new_pos

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        active_cells = set(self._get_cells()) if self.piece and not self.game_over else set()
        piece_color = PIECE_COLORS.get(self.piece_type, (200, 200, 200))

        if not self.game_active:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_TITLE, "TETR")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        if self.game_over:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, (200, 0, 0), f"S:{self.score}")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            if (c, r) in active_cells:
                set_key(self.deck, key, piece_color, "")
            elif (c, r) in self.grid:
                set_key(self.deck, key, self.grid[(c, r)], "")
            elif key == 0:
                set_key(self.deck, key, COLOR_SCORE, str(self.score))
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def game_loop(self):
        while self.running and self.deck.is_open():
            with self.lock:
                self.tick()
                self.render()
            time.sleep(TICK_SPEED)


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
    print(f"Tetris on {deck.deck_type()} ({cols}x{rows})")
    print("Top row=rotate. Bottom=drop. Middle=move up/down.")
    game = Tetris(deck)
    game.render()
    deck.set_key_callback(lambda d, k, s: (s and game.lock.acquire(), s and game.handle_key(k), s and game.lock.release()) if s else None)
    t = threading.Thread(target=game.game_loop, daemon=True)
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
        print(f"\nScore: {game.score}")


if __name__ == "__main__":
    main()
