#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Frogger for Elgato Stream Deck (adapts to any layout).

Frog starts at bottom. Cross lanes of traffic to reach the top!
Press adjacent buttons to hop. Cars scroll left/right.
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

COLOR_EMPTY = (40, 60, 40)
COLOR_FROG = (0, 220, 0)
COLOR_CAR = (200, 40, 40)
COLOR_SAFE = (60, 60, 100)
COLOR_GOAL = (0, 200, 60)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_DEAD = (200, 0, 0)

TICK_SPEED = 0.4


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 20 if len(text) <= 2 else 14
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


class Frogger:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.running = True
        self.frog = (cols // 2, rows - 1)
        self.cars = {}
        self.score = 0
        self.game_active = False
        self.game_over = False
        self.won = False

    def reset(self):
        self.frog = (self.cols // 2, self.rows - 1)
        self.cars = {}
        self.score = 0
        self.game_over = False
        self.won = False
        self.game_active = True
        # Create car lanes (all rows except first and last)
        for r in range(1, self.rows - 1):
            direction = 1 if r % 2 == 0 else -1
            num_cars = max(1, self.cols // 3)
            positions = random.sample(range(self.cols), min(num_cars, self.cols))
            self.cars[r] = {"dir": direction, "pos": set(positions)}

    def tick(self):
        if not self.game_active or self.game_over:
            return
        # Move cars
        for r, lane in self.cars.items():
            d = lane["dir"]
            lane["pos"] = {(c + d) % self.cols for c in lane["pos"]}
        # Check frog collision
        fx, fy = self.frog
        if fy in self.cars and fx in self.cars[fy]["pos"]:
            self.game_over = True

    def handle_key(self, key):
        if self.game_over or not self.game_active:
            self.reset()
            return

        col = key % self.cols
        row = key // self.rows if key // self.cols < self.rows else key // self.cols
        row = key // self.cols
        fx, fy = self.frog

        if abs(col - fx) + abs(row - fy) == 1:
            self.frog = (col, row)
            if row == 0:
                self.won = True
                self.game_over = True
                self.score += 1
            elif row in self.cars and col in self.cars[row]["pos"]:
                self.game_over = True

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_FROG, "FROG")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        if self.game_over:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_GOAL if self.won else COLOR_DEAD, "SAFE" if self.won else "SPLAT")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "AGAIN")
                elif (c, r) == (0, 0):
                    set_key(self.deck, key, COLOR_SCORE, f"S:{self.score}")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        car_set = set()
        for r, lane in self.cars.items():
            for c in lane["pos"]:
                car_set.add((c, r))

        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            if (c, r) == self.frog:
                set_key(self.deck, key, COLOR_FROG, "F")
            elif r == 0:
                set_key(self.deck, key, COLOR_GOAL, "")
            elif (c, r) in car_set:
                set_key(self.deck, key, COLOR_CAR, "")
            elif r == last_r:
                set_key(self.deck, key, COLOR_SAFE, "")
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def game_loop(self):
        while self.running and self.deck.is_open():
            with self.lock:
                self.tick()
                self.render()
            time.sleep(TICK_SPEED)


def main():
    streamdecks = DeviceManager().enumerate()
    deck = next((d for d in streamdecks if d.is_visual()), None)
    if not deck:
        print("No visual Stream Deck found.")
        sys.exit(1)
    deck.open()
    deck.reset()
    deck.set_brightness(80)
    print(f"Frogger on {deck.deck_type()}")
    print("Hop to the top! Avoid cars!")
    game = Frogger(deck)
    game.render()
    deck.set_key_callback(lambda d, k, s: (game.lock.acquire(), game.handle_key(k), game.lock.release()) if s else None)
    t = threading.Thread(target=game.game_loop, daemon=True)
    t.start()
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
        print(f"\nScore: {game.score}")


if __name__ == "__main__":
    main()
