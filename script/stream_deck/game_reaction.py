#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Reaction time game for Elgato Stream Deck (adapts to any layout).

A random button lights up — hit it as fast as you can!
Best of 5 rounds, tracks best time.
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

COLOR_EMPTY = (20, 20, 30)
COLOR_WAIT = (180, 120, 0)
COLOR_GO = (0, 220, 0)
COLOR_HIT = (0, 180, 220)
COLOR_EARLY = (220, 0, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)

ROUNDS = 5


class ReactionGame:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.running = True
        self.game_active = False
        self.round = 0
        self.times = []
        self.best_avg = 0
        self.target_key = -1
        self.go_time = 0
        self.waiting = False
        self.show_result = False
        self.early = False
        self._wait_thread = None

    def reset(self):
        self.round = 0
        self.times = []
        self.game_active = True
        self.early = False
        self.show_result = False
        self._next_round()

    def _next_round(self):
        """Start next round after a delay."""
        self.round += 1
        self.waiting = True
        self.target_key = -1
        self.show_result = False
        self.early = False

        # Show "get ready" on all keys
        for k in range(self.total_keys):
            self._set_key(k, COLOR_WAIT, f"R{self.round}" if k == 0 else "")

        self._wait_thread = threading.Thread(
            target=self._wait_and_show, daemon=True
        )
        self._wait_thread.start()

    def _wait_and_show(self):
        """Wait random time then light up target."""
        delay = random.uniform(1.5, 4.0)
        start = time.monotonic()

        while time.monotonic() - start < delay:
            if not self.running or not self.game_active:
                return
            if self.early:
                return
            time.sleep(0.05)

        if self.early or not self.game_active:
            return

        with self.lock:
            self.target_key = random.randint(0, self.total_keys - 1)
            self.go_time = time.monotonic()
            self.waiting = False

            for k in range(self.total_keys):
                if k == self.target_key:
                    self._set_key(k, COLOR_GO, "GO!")
                else:
                    self._set_key(k, COLOR_EMPTY, "")

    def handle_key(self, key):
        if not self.game_active:
            self.reset()
            return

        if self.show_result:
            if self.round >= ROUNDS:
                # Game over, restart
                self.game_active = False
                self._render_final()
                return
            self._next_round()
            return

        if self.waiting:
            # Pressed too early
            self.early = True
            self.waiting = False
            for k in range(self.total_keys):
                self._set_key(k, COLOR_EARLY, "EARLY" if k == self.total_keys // 2 else "")
            self.show_result = True
            self.times.append(9.999)
            return

        if self.target_key >= 0:
            reaction = time.monotonic() - self.go_time
            self.times.append(reaction)

            ms = int(reaction * 1000)
            mid = self.total_keys // 2
            for k in range(self.total_keys):
                if k == key:
                    self._set_key(k, COLOR_HIT, f"{ms}ms")
                elif k == mid and key != mid:
                    self._set_key(k, COLOR_SCORE, f"R{self.round}/{ROUNDS}")
                else:
                    self._set_key(k, COLOR_EMPTY, "")

            self.target_key = -1
            self.show_result = True

    def _render_final(self):
        """Show final results."""
        valid = [t for t in self.times if t < 9]
        avg = sum(valid) / len(valid) if valid else 0
        avg_ms = int(avg * 1000)
        best = min(valid) if valid else 0
        best_ms = int(best * 1000)

        if self.best_avg == 0 or (avg > 0 and avg < self.best_avg):
            self.best_avg = avg

        mid_c = self.cols // 2
        last_r = self.rows - 1

        for k in range(self.total_keys):
            r = k // self.cols
            c = k % self.cols
            if (c, r) == (mid_c, 0):
                self._set_key(k, COLOR_HIT, f"AVG")
            elif (c, r) == (mid_c + 1, 0) if self.cols > 3 else False:
                self._set_key(k, COLOR_HIT, f"{avg_ms}ms")
            elif (c, r) == (mid_c, 1) if self.rows > 2 else False:
                self._set_key(k, COLOR_SCORE, f"BST:{best_ms}")
            elif (c, r) == (mid_c, last_r):
                self._set_key(k, COLOR_TITLE, "AGAIN")
            else:
                self._set_key(k, COLOR_EMPTY, "")

    def render_title(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        for k in range(self.total_keys):
            r = k // self.cols
            c = k % self.cols
            if (c, r) == (mid_c, 0):
                self._set_key(k, COLOR_GO, "REACT")
            elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                self._set_key(k, COLOR_TITLE, "PRESS")
            elif (c, r) == (0, last_r) and self.best_avg > 0:
                self._set_key(
                    k, COLOR_SCORE,
                    f"{int(self.best_avg * 1000)}ms"
                )
            else:
                self._set_key(k, COLOR_EMPTY, "")

    def _set_key(self, key, color, text=""):
        fmt = self.deck.key_image_format()
        w, h = fmt["size"]
        img = Image.new("RGB", (w, h), color)
        if text:
            draw = ImageDraw.Draw(img)
            font_size = 18 if len(text) <= 5 else 12
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
    print(f"Reaction Time on {deck.deck_type()} ({cols}x{rows})")
    print(f"Best of {ROUNDS} rounds. Hit the green button! Ctrl+C to quit.")

    game = ReactionGame(deck)
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
        if game.best_avg > 0:
            print(f"\nBest avg: {int(game.best_avg * 1000)}ms")


if __name__ == "__main__":
    main()
