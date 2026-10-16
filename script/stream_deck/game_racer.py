#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Top-Down Racer.

Road scrolls from right to left. Dodge obstacles! Press top/bottom
rows to change lane. Speed increases over time. How far can you go?
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

GAME_META = {
    "name": "Top-Down Racer",
    "category": "race",
    "multiplayer": False,
    "sdplus": False,
    "description": "Dodge obstacles on a scrolling road! Speed increases.",
    "icon": "racer"
}

COLOR_ROAD = (40, 40, 50)
COLOR_CAR = (0, 200, 255)
COLOR_OBSTACLE = (220, 40, 40)
COLOR_PASSED = (60, 60, 70)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)
COLOR_DEAD = (200, 0, 0)

BASE_SPEED = 0.4
MIN_SPEED = 0.15


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 20 if len(text) <= 3 else 12
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


class Racer:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.running = True
        self.car_row = rows // 2
        self.car_col = 1
        self.obstacles = {}
        self.score = 0
        self.high_score = 0
        self.game_active = False
        self.game_over = False

    def reset(self):
        self.car_row = self.rows // 2
        self.obstacles = {}
        self.score = 0
        self.game_over = False
        self.game_active = True

    def tick(self):
        if not self.game_active or self.game_over:
            return

        # Scroll obstacles left
        new_obs = {}
        for (c, r), kind in self.obstacles.items():
            if c - 1 >= 0:
                new_obs[(c - 1, r)] = kind
        self.obstacles = new_obs

        # Spawn new obstacle on right edge
        if random.random() < 0.4:
            r = random.randint(0, self.rows - 1)
            if (self.cols - 1, r) not in self.obstacles:
                self.obstacles[(self.cols - 1, r)] = "block"

        # Check collision
        if (self.car_col, self.car_row) in self.obstacles:
            self.game_over = True
            if self.score > self.high_score:
                self.high_score = self.score
        else:
            self.score += 1

    def get_speed(self):
        return max(MIN_SPEED, BASE_SPEED - self.score * 0.003)

    def handle_key(self, key):
        if self.game_over or not self.game_active:
            self.reset()
            return

        row = key // self.cols
        if row < self.car_row:
            self.car_row = max(0, self.car_row - 1)
        elif row > self.car_row:
            self.car_row = min(self.rows - 1, self.car_row + 1)

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_CAR, "RACE")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.high_score:
                    set_key(self.deck, key, COLOR_SCORE, f"HI:{self.high_score}")
                else:
                    set_key(self.deck, key, COLOR_ROAD, "")
            return

        if self.game_over:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_DEAD, f"S:{self.score}")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "AGAIN")
                elif (c, r) == (0, 0):
                    set_key(self.deck, key, COLOR_SCORE, f"HI:{self.high_score}")
                else:
                    set_key(self.deck, key, COLOR_ROAD, "")
            return

        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            if c == self.car_col and r == self.car_row:
                set_key(self.deck, key, COLOR_CAR, ">")
            elif (c, r) in self.obstacles:
                set_key(self.deck, key, COLOR_OBSTACLE, "")
            elif c == self.cols - 1 and r == 0:
                set_key(self.deck, key, COLOR_SCORE, str(self.score))
            else:
                set_key(self.deck, key, COLOR_ROAD, "")

    def game_loop(self):
        while self.running and self.deck.is_open():
            with self.lock:
                self.tick()
                self.render()
            time.sleep(self.get_speed())


def main():
    streamdecks = DeviceManager().enumerate()
    deck = next((d for d in streamdecks if d.is_visual()), None)
    if not deck:
        print("No visual Stream Deck found.")
        sys.exit(1)
    deck.open()
    deck.reset()
    deck.set_brightness(80)
    print(f"Top-Down Racer on {deck.deck_type()}")
    print("Press top/bottom to dodge! Speed increases.")
    game = Racer(deck)
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
        print(f"\nScore: {game.score} | High: {game.high_score}")



if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
