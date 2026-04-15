#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Color Match (Memory) game for Elgato Stream Deck (adapts to any layout).

Flip two cards. If they match, they stay revealed. Find all pairs!
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

CARD_COLORS = [
    (220, 40, 40), (0, 180, 0), (0, 80, 220), (220, 180, 0),
    (180, 0, 180), (0, 180, 180), (220, 100, 0), (100, 220, 0),
    (255, 100, 100), (100, 255, 100), (100, 100, 255), (255, 200, 0),
    (200, 0, 100), (0, 200, 100), (100, 0, 200), (200, 100, 0),
]
COLOR_HIDDEN = (50, 50, 65)
COLOR_EMPTY = (20, 20, 30)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)


class ColorMatch:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        # Need even number of cards
        self.num_pairs = self.total_keys // 2
        self.lock = threading.Lock()
        self.cards = []
        self.revealed = set()
        self.matched = set()
        self.first = None
        self.second = None
        self.moves = 0
        self.game_active = False
        self.won = False
        self.best_moves = 0
        self._showing_pair = False

    def reset(self):
        colors = list(range(self.num_pairs)) * 2
        random.shuffle(colors)
        self.cards = colors[: self.total_keys]
        # If odd total, last card is wild (auto-matched)
        if self.total_keys % 2 == 1:
            self.cards.append(-1)
            self.matched.add(self.total_keys - 1)
        else:
            self.matched = set()
        self.revealed = set()
        self.first = None
        self.second = None
        self.moves = 0
        self.won = False
        self.game_active = True
        self._showing_pair = False

    def handle_key(self, key):
        if self.won or not self.game_active:
            self.reset()
            self.render()
            return

        if self._showing_pair:
            return

        if key >= len(self.cards):
            return
        if key in self.matched:
            return

        if self.first is None:
            self.first = key
            self.revealed.add(key)
            self.render()
        elif self.second is None and key != self.first:
            self.second = key
            self.revealed.add(key)
            self.moves += 1
            self.render()

            # Check match
            if self.cards[self.first] == self.cards[self.second]:
                self.matched.add(self.first)
                self.matched.add(self.second)
                self.first = None
                self.second = None
                if len(self.matched) >= len(self.cards):
                    self.won = True
                    if self.best_moves == 0 or self.moves < self.best_moves:
                        self.best_moves = self.moves
                self.render()
            else:
                self._showing_pair = True
                threading.Thread(
                    target=self._hide_pair, daemon=True
                ).start()

    def _hide_pair(self):
        time.sleep(0.8)
        with self.lock:
            if self.first is not None:
                self.revealed.discard(self.first)
            if self.second is not None:
                self.revealed.discard(self.second)
            self.first = None
            self.second = None
            self._showing_pair = False
            self.render()

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_TITLE, "MATCH")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.best_moves:
                    self._set_key(key, COLOR_SCORE, f"B:{self.best_moves}")
                else:
                    idx = key % len(CARD_COLORS)
                    r_c, g, b = CARD_COLORS[idx]
                    self._set_key(key, (r_c // 4, g // 4, b // 4), "")
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
            if key >= len(self.cards):
                self._set_key(key, COLOR_EMPTY, "")
            elif key in self.matched:
                color_idx = self.cards[key] % len(CARD_COLORS)
                r, g, b = CARD_COLORS[color_idx]
                self._set_key(key, (r // 3, g // 3, b // 3), "")
            elif key in self.revealed:
                color_idx = self.cards[key] % len(CARD_COLORS)
                self._set_key(key, CARD_COLORS[color_idx], "")
            else:
                self._set_key(key, COLOR_HIDDEN, "?")

    def _set_key(self, key, color, text=""):
        fmt = self.deck.key_image_format()
        w, h = fmt["size"]
        img = Image.new("RGB", (w, h), color)
        if text:
            draw = ImageDraw.Draw(img)
            font_size = 22 if len(text) <= 3 else 14
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
    print(f"Color Match on {deck.deck_type()} ({cols}x{rows})")
    print("Flip two cards, find pairs! Ctrl+C to quit.")

    game = ColorMatch(deck)
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
