#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Lights Out puzzle for Elgato Stream Deck (adapts to any layout).

Press a button to toggle it and its 4 neighbors. Turn all lights off to win.
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

COLOR_ON = (220, 200, 0)
COLOR_OFF = (20, 20, 30)
COLOR_WIN = (0, 200, 60)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)

MIN_SCRAMBLE = 5
MAX_SCRAMBLE = 15


class LightsOut:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.grid = [False] * self.total_keys
        self.moves = 0
        self.game_active = False
        self.won = False
        self.best_moves = 0
        self.games_won = 0

    def key_to_pos(self, key):
        return key % self.cols, key // self.cols

    def pos_to_key(self, col, row):
        if 0 <= col < self.cols and 0 <= row < self.rows:
            return row * self.cols + col
        return -1

    def reset(self):
        """Generate a solvable puzzle by applying random presses."""
        self.grid = [False] * self.total_keys
        self.moves = 0
        self.won = False
        self.game_active = True

        # Apply random presses to guarantee solvability
        num_presses = random.randint(MIN_SCRAMBLE, MAX_SCRAMBLE)
        for _ in range(num_presses):
            key = random.randint(0, self.total_keys - 1)
            self._toggle(key)

        # Ensure at least some lights are on
        if not any(self.grid):
            self._toggle(random.randint(0, self.total_keys - 1))

        self.moves = 0

    def _toggle(self, key):
        """Toggle key and its orthogonal neighbors."""
        col, row = self.key_to_pos(key)
        targets = [(col, row)]
        if col > 0:
            targets.append((col - 1, row))
        if col < self.cols - 1:
            targets.append((col + 1, row))
        if row > 0:
            targets.append((col, row - 1))
        if row < self.rows - 1:
            targets.append((col, row + 1))

        for c, r in targets:
            k = self.pos_to_key(c, r)
            if k >= 0:
                self.grid[k] = not self.grid[k]

    def handle_key(self, key):
        if self.won or not self.game_active:
            self.reset()
            self.render()
            return

        self._toggle(key)
        self.moves += 1

        if not any(self.grid):
            self.won = True
            self.games_won += 1
            if self.best_moves == 0 or self.moves < self.best_moves:
                self.best_moves = self.moves

        self.render()

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            # Title screen
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_ON, "LIGHT")
                elif (c, r) == (mid_c + 1, 0) if self.cols > 3 else False:
                    self._set_key(key, COLOR_OFF, "OUT")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.best_moves > 0:
                    self._set_key(key, COLOR_SCORE, f"B:{self.best_moves}")
                else:
                    on = random.random() > 0.5
                    self._set_key(
                        key, COLOR_ON if on else COLOR_OFF, ""
                    )
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

        # Normal play
        for key in range(self.total_keys):
            if self.grid[key]:
                self._set_key(key, COLOR_ON, "")
            else:
                self._set_key(key, COLOR_OFF, "")
        # Show move counter on key 0
        self._set_key(0, COLOR_SCORE if not self.grid[0] else COLOR_ON, str(self.moves))

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
    if not streamdecks:
        print("No Stream Deck found.")
        sys.exit(1)

    deck = None
    for d in streamdecks:
        if d.is_visual():
            deck = d
            break

    if deck is None:
        print("No visual Stream Deck found.")
        sys.exit(1)

    deck.open()
    deck.reset()
    deck.set_brightness(80)

    rows, cols = deck.key_layout()
    print(f"Lights Out on {deck.deck_type()} ({cols}x{rows})")
    print("Toggle lights + neighbors. Turn all off to win! Ctrl+C to quit.")

    game = LightsOut(deck)
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
        print(f"\nGames won: {game.games_won} | Best: {game.best_moves} moves")


if __name__ == "__main__":
    main()
