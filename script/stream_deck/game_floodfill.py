#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Flood Fill puzzle for Elgato Stream Deck (adapts to any layout).

The grid has random colors. Press a color button in the bottom row
to flood-fill from top-left. Fill the entire board in limited moves!
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

PALETTE = [
    (220, 40, 40),
    (0, 180, 0),
    (0, 80, 220),
    (220, 180, 0),
    (180, 0, 180),
    (0, 180, 180),
]
COLOR_EMPTY = (20, 20, 30)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)
COLOR_LOSE = (180, 0, 0)


class FloodFill:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        # Game area = all rows except bottom (color picker)
        self.game_rows = rows - 1
        self.num_colors = min(len(PALETTE), cols)
        self.max_moves = self.game_rows * self.cols
        self.grid = []
        self.moves = 0
        self.game_active = False
        self.won = False
        self.lost = False
        self.best_moves = 0

    def reset(self):
        total_cells = self.game_rows * self.cols
        self.max_moves = total_cells + self.num_colors
        self.grid = [
            random.randint(0, self.num_colors - 1)
            for _ in range(total_cells)
        ]
        self.moves = 0
        self.won = False
        self.lost = False
        self.game_active = True

    def _flood(self, new_color):
        """Flood fill from top-left with new color."""
        old_color = self.grid[0]
        if old_color == new_color:
            return

        stack = [0]
        visited = set()
        while stack:
            idx = stack.pop()
            if idx in visited:
                continue
            if self.grid[idx] != old_color:
                continue
            visited.add(idx)
            self.grid[idx] = new_color

            c = idx % self.cols
            r = idx // self.cols
            if c > 0:
                stack.append(idx - 1)
            if c < self.cols - 1:
                stack.append(idx + 1)
            if r > 0:
                stack.append(idx - self.cols)
            if r < self.game_rows - 1:
                stack.append(idx + self.cols)

        self.moves += 1

        # Check win
        if all(self.grid[i] == self.grid[0] for i in range(len(self.grid))):
            self.won = True
            if self.best_moves == 0 or self.moves < self.best_moves:
                self.best_moves = self.moves
        elif self.moves >= self.max_moves:
            self.lost = True

    def handle_key(self, key):
        if self.won or self.lost or not self.game_active:
            self.reset()
            self.render()
            return

        row = key // self.cols
        col = key % self.cols

        # Bottom row = color picker
        if row == self.rows - 1 and col < self.num_colors:
            self._flood(col)
        # Click on grid = pick that color
        elif row < self.game_rows:
            idx = row * self.cols + col
            if idx < len(self.grid):
                self._flood(self.grid[idx])

        self.render()

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_TITLE, "FLOOD")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.best_moves:
                    self._set_key(key, COLOR_SCORE, f"B:{self.best_moves}")
                elif r == last_r and c < self.num_colors:
                    self._set_key(key, PALETTE[c], "")
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            return

        if self.won:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_WIN, "WIN!")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "AGAIN")
                else:
                    self._set_key(key, COLOR_WIN, f"{self.moves}")
            return

        if self.lost:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_LOSE, "LOST")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "AGAIN")
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            return

        # Game grid
        for r in range(self.game_rows):
            for c in range(self.cols):
                key = r * self.cols + c
                idx = r * self.cols + c
                if idx < len(self.grid):
                    color_idx = self.grid[idx]
                    self._set_key(key, PALETTE[color_idx], "")

        # Bottom row: color picker + moves
        for c in range(self.cols):
            key = last_r * self.cols + c
            if c < self.num_colors:
                self._set_key(key, PALETTE[c], "")
            elif c == self.cols - 1:
                remaining = self.max_moves - self.moves
                self._set_key(key, COLOR_SCORE, f"{remaining}")
            else:
                self._set_key(key, COLOR_EMPTY, "")

    def _set_key(self, key, color, text=""):
        fmt = self.deck.key_image_format()
        w, h = fmt["size"]
        img = Image.new("RGB", (w, h), color)
        if text:
            draw = ImageDraw.Draw(img)
            font_size = 20 if len(text) <= 4 else 12
            try:
                font = ImageFont.load_default(size=font_size)
            except TypeError:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx, ty = (w - tw) // 2, (h - th) // 2
            draw.text((tx + 1, ty + 1), text, fill=(0, 0, 0), font=font)
            draw.text((tx, ty), text, fill=(255, 255, 255), font=font)
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
    print(f"Flood Fill on {deck.deck_type()} ({cols}x{rows})")
    print("Pick colors from bottom row. Fill entire board! Ctrl+C to quit.")

    game = FloodFill(deck)
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
        print(f"\nMoves: {game.moves} | Best: {game.best_moves}")


if __name__ == "__main__":
    main()
