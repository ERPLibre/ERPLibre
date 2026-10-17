#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Number Guess.

Guess a number 1-100. Buttons show ranges. Press to narrow down.
Hot/cold feedback. Fewer guesses = better score!
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
    "name": "Number Guess",
    "category": "word",
    "multiplayer": False,
    "sdplus": False,
    "description": "Guess 1-100 with hot/cold colors. Fewer tries = better!",
    "icon": "number"
}

COLOR_COLD = (0, 80, 200)
COLOR_COOL = (0, 160, 160)
COLOR_WARM = (200, 180, 0)
COLOR_HOT = (220, 80, 0)
COLOR_CORRECT = (0, 220, 60)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 18 if len(text) <= 3 else 12
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


class NumberGuess:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.target = 0
        self.low = 1
        self.high = 100
        self.guesses = 0
        self.game_active = False
        self.won = False
        self.best = 0

    def reset(self):
        self.target = random.randint(1, 100)
        self.low = 1
        self.high = 100
        self.guesses = 0
        self.won = False
        self.game_active = True

    def handle_key(self, key):
        if self.won or not self.game_active:
            self.reset()
            self.render()
            return

        # Map key to a value in current range
        range_size = self.high - self.low + 1
        if range_size <= 1:
            return

        # Distribute values across keys
        values = []
        step = max(1, range_size // self.total_keys)
        for i in range(self.total_keys):
            v = self.low + i * step
            if v <= self.high:
                values.append(v)
            else:
                values.append(self.high)

        if key >= len(values):
            return

        guess = values[key]
        self.guesses += 1

        if guess == self.target:
            self.won = True
            if self.best == 0 or self.guesses < self.best:
                self.best = self.guesses
        elif guess < self.target:
            self.low = guess + 1
        else:
            self.high = guess - 1

        self.render()

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_TITLE, "GUESS")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.best:
                    set_key(self.deck, key, COLOR_SCORE, f"B:{self.best}")
                else:
                    set_key(self.deck, key, (20, 20, 30), "")
            return

        if self.won:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_CORRECT, f"{self.target}!")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    set_key(self.deck, key, COLOR_SCORE, f"{self.guesses}try")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(self.deck, key, COLOR_CORRECT, "")
            return

        range_size = self.high - self.low + 1
        step = max(1, range_size // self.total_keys)

        for key in range(self.total_keys):
            v = self.low + key * step
            if v > self.high:
                v = self.high

            dist = abs(v - self.target)
            if dist <= 3:
                color = COLOR_HOT
            elif dist <= 10:
                color = COLOR_WARM
            elif dist <= 25:
                color = COLOR_COOL
            else:
                color = COLOR_COLD

            set_key(self.deck, key, color, str(v))

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
    print(f"Number Guess on {deck.deck_type()}")
    print("Guess 1-100. Colors = hot/cold. Fewer guesses = better!")
    game = NumberGuess(deck)
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
        print(f"\nBest: {game.best} guesses")



if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
