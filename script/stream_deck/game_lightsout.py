#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Lights Out puzzle — 1P or 2P coop.

1 deck: toggle lights + neighbors, turn all off.
2 decks: shared grid! Both players see and toggle the same board.
Actions from either deck affect the shared state. Cooperative!
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


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 20 if len(text) <= 4 else 12
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


class LightsOut:
    def __init__(self, decks):
        self.decks = decks
        self.num_players = len(decks)
        rows, cols = decks[0].key_layout()
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

    def _toggle(self, key):
        col = key % self.cols
        row = key // self.cols
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
            k = r * self.cols + c
            if 0 <= k < self.total_keys:
                self.grid[k] = not self.grid[k]

    def reset(self):
        self.grid = [False] * self.total_keys
        self.moves = 0
        self.won = False
        self.game_active = True
        for _ in range(random.randint(MIN_SCRAMBLE, MAX_SCRAMBLE)):
            self._toggle(random.randint(0, self.total_keys - 1))
        if not any(self.grid):
            self._toggle(random.randint(0, self.total_keys - 1))
        self.moves = 0

    def handle_key(self, key, deck_index=0):
        if self.won or not self.game_active:
            self.reset()
            self.render_all()
            return
        self._toggle(key)
        self.moves += 1
        if not any(self.grid):
            self.won = True
            self.games_won += 1
            if self.best_moves == 0 or self.moves < self.best_moves:
                self.best_moves = self.moves
        self.render_all()

    def render_all(self):
        for deck in self.decks:
            self._render(deck)

    def _render(self, deck):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, key, COLOR_ON, "LIGHT")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.best_moves > 0:
                    set_key(deck, key, COLOR_SCORE, f"B:{self.best_moves}")
                elif self.num_players == 2 and (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                    set_key(deck, key, COLOR_TITLE, "COOP")
                else:
                    set_key(deck, key, COLOR_ON if random.random() > 0.5 else COLOR_OFF, "")
            return

        if self.won:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, key, COLOR_WIN, "WIN!")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    set_key(deck, key, COLOR_SCORE, f"{self.moves}mv")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(deck, key, COLOR_WIN, "")
            return

        for key in range(self.total_keys):
            if self.grid[key]:
                set_key(deck, key, COLOR_ON, "")
            else:
                set_key(deck, key, COLOR_OFF, "")
        set_key(deck, 0, COLOR_SCORE if not self.grid[0] else COLOR_ON, str(self.moves))


def main():
    streamdecks = DeviceManager().enumerate()
    visual = [d for d in streamdecks if d.is_visual()]
    if not visual:
        print("No visual Stream Deck found.")
        sys.exit(1)

    for d in visual:
        d.open()
        d.reset()
        d.set_brightness(80)

    decks = visual[:2] if len(visual) >= 2 else visual[:1]

    if len(decks) == 2:
        print("2-PLAYER LIGHTS OUT (COOP)! Shared board, work together!")
    else:
        print(f"Lights Out on {decks[0].deck_type()}")

    print("Toggle lights + neighbors. Turn all off! Ctrl+C to quit.")

    game = LightsOut(decks)
    game.render_all()

    for i, deck in enumerate(decks):
        def make_cb(idx):
            def cb(deck, key, state):
                if not state:
                    return
                with game.lock:
                    game.handle_key(key, deck_index=idx)
            return cb
        deck.set_key_callback(make_cb(i))

    try:
        while all(d.is_open() for d in decks):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for d in decks:
            try:
                with d:
                    d.reset()
                    d.close()
            except Exception:
                pass
        print(f"\nGames won: {game.games_won} | Best: {game.best_moves}")


if __name__ == "__main__":
    main()
