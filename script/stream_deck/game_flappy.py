#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Flappy Bird.

Bird on left column, obstacles scroll from right. Press any key to flap up.
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

COLOR_EMPTY = (100, 180, 255)
COLOR_BIRD = (255, 220, 0)
COLOR_PIPE = (0, 140, 0)
COLOR_GROUND = (80, 60, 40)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_GAMEOVER = (180, 0, 0)

TICK_SPEED = 0.45
GRAVITY_TICK = 2


class Flappy:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.running = True
        self.game_active = False
        self.game_over = False
        self.bird_row = rows // 2
        self.pipes = []
        self.score = 0
        self.high_score = 0
        self.tick_count = 0

    def reset(self):
        self.bird_row = self.rows // 2
        self.pipes = []
        self.score = 0
        self.game_over = False
        self.game_active = True
        self.tick_count = 0
        # Spawn first pipe
        self._spawn_pipe()

    def _spawn_pipe(self):
        gap_row = random.randint(0, self.rows - 1)
        self.pipes.append({"col": self.cols - 1, "gap": gap_row})

    def tick(self):
        if not self.game_active or self.game_over:
            return

        self.tick_count += 1

        # Gravity
        if self.tick_count % GRAVITY_TICK == 0:
            self.bird_row = min(self.rows - 1, self.bird_row + 1)

        # Move pipes left
        for pipe in self.pipes:
            pipe["col"] -= 1

        # Remove off-screen pipes
        old_len = len(self.pipes)
        self.pipes = [p for p in self.pipes if p["col"] >= 0]
        self.score += old_len - len(self.pipes)

        # Spawn new pipe
        if not self.pipes or self.pipes[-1]["col"] < self.cols - 2:
            if random.random() < 0.4:
                self._spawn_pipe()

        # Collision check
        bird_col = 1
        for pipe in self.pipes:
            if pipe["col"] == bird_col:
                if self.bird_row != pipe["gap"]:
                    self.game_over = True
                    if self.score > self.high_score:
                        self.high_score = self.score
                    return

    def handle_key(self, key):
        if self.game_over or not self.game_active:
            self.reset()
            return
        # Flap up
        self.bird_row = max(0, self.bird_row - 1)

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        bird_col = 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_BIRD, "FLAP")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.high_score:
                    self._set_key(key, COLOR_SCORE, f"HI:{self.high_score}")
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            return

        if self.game_over:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_GAMEOVER, f"S:{self.score}")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "AGAIN")
                elif (c, r) == (0, 0):
                    self._set_key(key, COLOR_SCORE, f"HI:{self.high_score}")
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            return

        pipe_map = {}
        for pipe in self.pipes:
            for r in range(self.rows):
                if r != pipe["gap"]:
                    pipe_map[(pipe["col"], r)] = True

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols

            if c == bird_col and r == self.bird_row:
                self._set_key(key, COLOR_BIRD, "")
            elif (c, r) in pipe_map:
                self._set_key(key, COLOR_PIPE, "")
            elif c == 0 and r == 0:
                self._set_key(key, COLOR_SCORE, str(self.score))
            else:
                self._set_key(key, COLOR_EMPTY, "")

    def game_loop(self):
        while self.running and self.deck.is_open():
            with self.lock:
                self.tick()
                self.render()
            time.sleep(TICK_SPEED)

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
    print(f"Flappy on {deck.deck_type()} ({cols}x{rows})")
    print("Press any key to flap! Ctrl+C to quit.")

    game = Flappy(deck)
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
