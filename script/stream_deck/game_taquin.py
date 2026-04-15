#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Taquin (sliding puzzle).

Slide numbered tiles to order them. Press a tile adjacent to the empty
space to move it.
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

TILE_COLORS = [
    (70, 130, 180), (60, 179, 113), (218, 165, 32), (205, 92, 92),
    (147, 112, 219), (0, 139, 139), (210, 105, 30), (128, 128, 0),
    (199, 21, 133), (65, 105, 225), (34, 139, 34), (178, 34, 34),
    (72, 61, 139), (188, 143, 143), (85, 107, 47), (139, 69, 19),
    (100, 149, 237), (144, 238, 144), (240, 128, 128), (221, 160, 221),
    (127, 255, 212), (255, 182, 193), (173, 216, 230), (255, 218, 185),
    (152, 251, 152), (255, 160, 122), (176, 196, 222), (255, 228, 181),
    (230, 230, 250), (245, 222, 179), (216, 191, 216), (250, 235, 215),
]
COLOR_EMPTY = (20, 20, 30)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)


class Taquin:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.tiles = []
        self.empty = 0
        self.moves = 0
        self.game_active = False
        self.won = False
        self.best_moves = 0

    def reset(self):
        n = self.total_keys
        # Goal: [1, 2, ..., n-1, 0]
        self.tiles = list(range(1, n)) + [0]
        self.empty = n - 1
        self.moves = 0
        self.won = False
        self.game_active = True
        # Shuffle by making random valid moves (guarantees solvability)
        for _ in range(n * 20):
            neighbors = self._get_neighbors(self.empty)
            pick = random.choice(neighbors)
            self.tiles[self.empty], self.tiles[pick] = (
                self.tiles[pick], self.tiles[self.empty]
            )
            self.empty = pick
        self.moves = 0

    def _get_neighbors(self, pos):
        c = pos % self.cols
        r = pos // self.cols
        result = []
        if c > 0:
            result.append(pos - 1)
        if c < self.cols - 1:
            result.append(pos + 1)
        if r > 0:
            result.append(pos - self.cols)
        if r < self.rows - 1:
            result.append(pos + self.cols)
        return result

    def handle_key(self, key):
        if self.won or not self.game_active:
            self.reset()
            self.render()
            return

        if key in self._get_neighbors(self.empty):
            self.tiles[self.empty], self.tiles[key] = (
                self.tiles[key], self.tiles[self.empty]
            )
            self.empty = key
            self.moves += 1

            # Check win
            goal = list(range(1, self.total_keys)) + [0]
            if self.tiles == goal:
                self.won = True
                if self.best_moves == 0 or self.moves < self.best_moves:
                    self.best_moves = self.moves

        self.render()

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_TITLE, "SLIDE")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.best_moves:
                    self._set_key(key, COLOR_SCORE, f"B:{self.best_moves}")
                else:
                    color = TILE_COLORS[key % len(TILE_COLORS)]
                    self._set_key(key, color, str(key + 1))
            return

        if self.won:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_WIN, "WIN!")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    self._set_key(key, COLOR_SCORE, f"{self.moves}mv")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "AGAIN")
                else:
                    self._set_key(key, COLOR_WIN, "")
            return

        for key in range(self.total_keys):
            val = self.tiles[key]
            if val == 0:
                self._set_key(key, COLOR_EMPTY, "")
            else:
                color = TILE_COLORS[(val - 1) % len(TILE_COLORS)]
                self._set_key(key, color, str(val))

    def _set_key(self, key, color, text=""):
        fmt = self.deck.key_image_format()
        w, h = fmt["size"]
        img = Image.new("RGB", (w, h), color)
        if text:
            draw = ImageDraw.Draw(img)
            font_size = 22 if len(text) <= 2 else 14
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
    n = rows * cols
    print(f"Taquin ({n - 1}-puzzle) on {deck.deck_type()} ({cols}x{rows})")
    print("Slide tiles to order 1→{0}. Ctrl+C to quit.".format(n - 1))

    game = Taquin(deck)
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
