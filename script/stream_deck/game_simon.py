#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Simon Says memory game for Elgato Stream Deck (adapts to any layout)."""

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

COLORS = [
    (220, 0, 0),
    (0, 180, 0),
    (0, 80, 220),
    (220, 180, 0),
    (180, 0, 180),
    (0, 180, 180),
    (220, 100, 0),
    (100, 220, 0),
]
COLOR_EMPTY = (20, 20, 30)
COLOR_DIM = (40, 40, 50)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_FAIL = (180, 0, 0)

SHOW_TIME = 0.5
PAUSE_TIME = 0.2

STATE_IDLE = "idle"
STATE_SHOWING = "showing"
STATE_INPUT = "input"
STATE_GAMEOVER = "gameover"


class SimonGame:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.running = True
        self.state = STATE_IDLE
        self.sequence = []
        self.input_pos = 0
        self.score = 0
        self.high_score = 0
        self.key_colors = {}
        self._assign_colors()

    def _assign_colors(self):
        """Assign a color to each key."""
        for k in range(self.total_keys):
            self.key_colors[k] = COLORS[k % len(COLORS)]

    def reset(self):
        self.sequence = []
        self.input_pos = 0
        self.score = 0
        self.state = STATE_SHOWING
        self._add_to_sequence()

    def _add_to_sequence(self):
        """Add one random key to the sequence and show it."""
        self.sequence.append(random.randint(0, self.total_keys - 1))
        self.input_pos = 0
        threading.Thread(
            target=self._show_sequence, daemon=True
        ).start()

    def _show_sequence(self):
        """Flash the sequence on the deck."""
        with self.lock:
            self.state = STATE_SHOWING
            self._render_all_dim()

        time.sleep(0.5)

        for key in self.sequence:
            if not self.running:
                return
            with self.lock:
                self._set_key(key, self.key_colors[key], "")
            time.sleep(SHOW_TIME)
            with self.lock:
                self._set_key(key, COLOR_DIM, "")
            time.sleep(PAUSE_TIME)

        with self.lock:
            self.state = STATE_INPUT
            self._render_all_ready()

    def handle_key(self, key):
        if self.state == STATE_IDLE or self.state == STATE_GAMEOVER:
            self.reset()
            return

        if self.state != STATE_INPUT:
            return

        expected = self.sequence[self.input_pos]
        if key == expected:
            self._set_key(key, self.key_colors[key], "")
            self.input_pos += 1

            if self.input_pos >= len(self.sequence):
                self.score = len(self.sequence)
                if self.score > self.high_score:
                    self.high_score = self.score
                # Show success flash
                threading.Thread(
                    target=self._success_flash, daemon=True
                ).start()
        else:
            # Wrong key — game over
            self.score = len(self.sequence) - 1
            if self.score > self.high_score:
                self.high_score = self.score
            self.state = STATE_GAMEOVER
            self._render_gameover()

    def _success_flash(self):
        """Brief green flash then add next."""
        with self.lock:
            for k in range(self.total_keys):
                self._set_key(k, (0, 100, 0), "")
        time.sleep(0.3)
        with self.lock:
            self._add_to_sequence()

    def _render_all_dim(self):
        mid_c = self.cols // 2
        for k in range(self.total_keys):
            r = k // self.cols
            c = k % self.cols
            if (c, r) == (mid_c, 0):
                self._set_key(k, COLOR_SCORE, f"LV{len(self.sequence)}")
            else:
                self._set_key(k, COLOR_DIM, "")

    def _render_all_ready(self):
        for k in range(self.total_keys):
            r, g, b = self.key_colors[k]
            dim = (r // 3, g // 3, b // 3)
            self._set_key(k, dim, "")

    def _render_gameover(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        for k in range(self.total_keys):
            r = k // self.cols
            c = k % self.cols
            if (c, r) == (mid_c, 0):
                self._set_key(k, COLOR_FAIL, f"LV{self.score}")
            elif (c, r) == (mid_c, last_r):
                self._set_key(k, COLOR_TITLE, "AGAIN")
            elif (c, r) == (0, last_r):
                self._set_key(k, COLOR_SCORE, f"HI:{self.high_score}")
            else:
                self._set_key(k, COLOR_FAIL if k == self.sequence[self.input_pos] else COLOR_EMPTY, "")

    def render_title(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        for k in range(self.total_keys):
            r = k // self.cols
            c = k % self.cols
            if (c, r) == (mid_c, 0):
                self._set_key(k, COLOR_TITLE, "SIMON")
            elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                self._set_key(k, COLOR_TITLE, "PRESS")
            elif (c, r) == (0, last_r):
                self._set_key(
                    k, COLOR_SCORE,
                    f"HI:{self.high_score}" if self.high_score else ""
                )
            else:
                r_c, g_c, b_c = self.key_colors[k]
                self._set_key(k, (r_c // 5, g_c // 5, b_c // 5), "")

    def _set_key(self, key, color, text=""):
        fmt = self.deck.key_image_format()
        w, h = fmt["size"]
        img = Image.new("RGB", (w, h), color)
        if text:
            draw = ImageDraw.Draw(img)
            font_size = 20 if len(text) <= 4 else 14
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
    print(f"Simon Says on {deck.deck_type()} ({cols}x{rows})")
    print("Watch the sequence, repeat it! Ctrl+C to quit.")

    game = SimonGame(deck)
    game.render_title()
    deck.set_key_callback(game.key_callback)

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
        print(f"\nScore: {game.score} | High: {game.high_score}")


if __name__ == "__main__":
    main()
