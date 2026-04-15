#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Battleship (solo) for Elgato Stream Deck (adapts to any layout).

Ships are hidden. Press buttons to fire. Find all ships!
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

COLOR_WATER = (0, 40, 80)
COLOR_HIT = (220, 40, 40)
COLOR_MISS = (60, 60, 80)
COLOR_SUNK = (160, 0, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)


class Battleship:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.ships = set()
        self.hits = set()
        self.misses = set()
        self.shots = 0
        self.game_active = False
        self.won = False
        self.best_shots = 0
        self.games_won = 0

    def reset(self):
        self.ships = set()
        self.hits = set()
        self.misses = set()
        self.shots = 0
        self.won = False
        self.game_active = True
        self._place_ships()

    def _place_ships(self):
        """Place ships scaled to grid size."""
        total = self.total_keys
        if total <= 6:
            sizes = [2]
        elif total <= 10:
            sizes = [3, 2]
        elif total <= 15:
            sizes = [3, 2, 2]
        elif total <= 20:
            sizes = [4, 3, 2]
        else:
            sizes = [4, 3, 3, 2]

        for size in sizes:
            placed = False
            for _ in range(100):
                horizontal = random.choice([True, False])
                if horizontal:
                    c = random.randint(0, self.cols - size)
                    r = random.randint(0, self.rows - 1)
                    cells = [(c + i, r) for i in range(size)]
                else:
                    c = random.randint(0, self.cols - 1)
                    r = random.randint(0, self.rows - size)
                    cells = [(c, r + i) for i in range(size)]

                keys = [rr * self.cols + cc for cc, rr in cells]
                if not any(k in self.ships for k in keys):
                    self.ships.update(keys)
                    placed = True
                    break

    def handle_key(self, key):
        if self.won or not self.game_active:
            self.reset()
            self.render()
            return

        if key in self.hits or key in self.misses:
            return

        self.shots += 1
        if key in self.ships:
            self.hits.add(key)
            if self.hits == self.ships:
                self.won = True
                self.games_won += 1
                if self.best_shots == 0 or self.shots < self.best_shots:
                    self.best_shots = self.shots
        else:
            self.misses.add(key)

        self.render()

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_TITLE, "SHIPS")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.best_shots:
                    self._set_key(key, COLOR_SCORE, f"B:{self.best_shots}")
                else:
                    self._set_key(key, COLOR_WATER, "~")
            return

        if self.won:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_WIN, "WIN!")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    self._set_key(key, COLOR_SCORE, f"{self.shots}sh")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "AGAIN")
                elif key in self.ships:
                    self._set_key(key, COLOR_HIT, "")
                else:
                    self._set_key(key, COLOR_WIN, "")
            return

        for key in range(self.total_keys):
            if key in self.hits:
                self._set_key(key, COLOR_HIT, "X")
            elif key in self.misses:
                self._set_key(key, COLOR_MISS, "o")
            elif key == 0:
                self._set_key(key, COLOR_SCORE, f"{self.shots}")
            else:
                self._set_key(key, COLOR_WATER, "~")

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
    print(f"Battleship on {deck.deck_type()} ({cols}x{rows})")
    print("Fire at will! Find all ships. Ctrl+C to quit.")

    game = Battleship(deck)
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
        print(f"\nWon: {game.games_won} | Best: {game.best_shots} shots")


if __name__ == "__main__":
    main()
