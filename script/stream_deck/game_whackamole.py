#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Whack-a-Mole game for Elgato Stream Deck (adapts to any layout)."""

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

COLOR_EMPTY = (20, 20, 30)
COLOR_MOLE = (180, 120, 40)
COLOR_HIT = (0, 220, 0)
COLOR_MISS = (220, 0, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)

GAME_DURATION = 30
BASE_MOLE_TIME = 1.2
MIN_MOLE_TIME = 0.4


class WhackAMole:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.running = True
        self.game_active = False
        self.score = 0
        self.misses = 0
        self.high_score = 0
        self.moles = set()
        self.time_left = 0
        self._flash = {}

    def pos_to_key(self, col, row):
        if 0 <= col < self.cols and 0 <= row < self.rows:
            return row * self.cols + col
        return -1

    def reset(self):
        self.score = 0
        self.misses = 0
        self.time_left = GAME_DURATION
        self.moles = set()
        self._flash = {}
        self.game_active = True

    def game_loop(self):
        """Main loop: spawn moles, count down."""
        while self.running and self.deck.is_open():
            if not self.game_active:
                time.sleep(0.2)
                continue

            with self.lock:
                # Spawn moles
                max_moles = 1 + self.score // 5
                if len(self.moles) < max_moles:
                    empty = [
                        k for k in range(self.total_keys)
                        if k not in self.moles and k not in self._flash
                    ]
                    if empty:
                        self.moles.add(random.choice(empty))

                self.time_left -= 0.1
                if self.time_left <= 0:
                    self.game_active = False
                    if self.score > self.high_score:
                        self.high_score = self.score

                # Expire old flashes
                now = time.monotonic()
                expired = [
                    k for k, t in self._flash.items() if now - t > 0.3
                ]
                for k in expired:
                    del self._flash[k]

                # Random mole disappear (miss)
                mole_time = max(
                    MIN_MOLE_TIME,
                    BASE_MOLE_TIME - self.score * 0.05,
                )
                if self.moles and random.random() < 0.1 / mole_time:
                    lost = random.choice(list(self.moles))
                    self.moles.discard(lost)
                    self.misses += 1
                    self._flash[lost] = now

                self.render()

            time.sleep(0.1)

    def handle_key(self, key):
        if not self.game_active:
            self.reset()
            self.render()
            return

        if key in self.moles:
            self.moles.discard(key)
            self.score += 1
            self._flash[key] = time.monotonic()
        self.render()

    def render(self):
        now = time.monotonic()
        mid_c = self.cols // 2
        last_r = self.rows - 1

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols

            if not self.game_active and self.time_left <= 0 and (
                self.score > 0 or self.misses > 0
            ):
                # Game over screen
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_SCORE, f"S:{self.score}")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "AGAIN")
                elif (c, r) == (0, 0):
                    self._set_key(key, COLOR_SCORE, f"HI:{self.high_score}")
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            elif not self.game_active:
                # Title screen
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_MOLE, "WHACK")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                    self._set_key(key, COLOR_TITLE, "PRESS")
                elif (c, r) == (0, last_r):
                    self._set_key(
                        key, COLOR_SCORE,
                        f"HI:{self.high_score}" if self.high_score else ""
                    )
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            elif key in self._flash:
                flash_age = now - self._flash[key]
                if flash_age < 0.3:
                    self._set_key(key, COLOR_HIT, "+1")
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            elif key in self.moles:
                self._set_key(key, COLOR_MOLE, "M")
            elif key == 0:
                self._set_key(key, COLOR_SCORE, str(self.score))
            elif key == self.total_keys - 1:
                self._set_key(
                    key, COLOR_SCORE, f"{int(self.time_left)}s"
                )
            else:
                self._set_key(key, COLOR_EMPTY, "")

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
    print(f"Whack-a-Mole on {deck.deck_type()} ({cols}x{rows})")
    print(f"Duration: {GAME_DURATION}s. Hit the moles! Ctrl+C to quit.")

    game = WhackAMole(deck)
    game.render()
    deck.set_key_callback(game.key_callback)

    game_thread = threading.Thread(target=game.game_loop, daemon=True)
    game_thread.start()

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
