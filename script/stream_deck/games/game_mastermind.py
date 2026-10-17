#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Mastermind.

Bottom row = your guess slots (cycle colors by pressing).
Top-right = submit guess. Feedback shown on remaining keys.
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
    "name": "Mastermind",
    "category": "strategy",
    "multiplayer": False,
    "sdplus": False,
    "description": "Guess the secret color code. Feedback after each try.",
    "icon": "master"
}

COLORS = [
    (220, 40, 40),    # Red
    (0, 180, 0),      # Green
    (0, 80, 220),     # Blue
    (220, 180, 0),    # Yellow
    (180, 0, 180),    # Purple
    (0, 180, 180),    # Cyan
]
COLOR_EMPTY = (20, 20, 30)
COLOR_TITLE = (0, 80, 160)
COLOR_SUBMIT = (0, 160, 0)
COLOR_WIN = (0, 200, 60)
COLOR_LOSE = (180, 0, 0)
COLOR_EXACT = (255, 255, 255)  # Right color, right place
COLOR_PARTIAL = (200, 160, 0)  # Right color, wrong place
COLOR_MISS = (60, 60, 60)       # Wrong


class Mastermind:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.code_len = min(cols, 4)
        self.max_guesses = rows - 1
        self.secret = []
        self.guesses = []
        self.feedbacks = []
        self.current_guess = []
        self.game_active = False
        self.won = False
        self.lost = False
        self.games_won = 0
        self.games_played = 0

    def reset(self):
        self.secret = [random.randint(0, len(COLORS) - 1) for _ in range(self.code_len)]
        self.guesses = []
        self.feedbacks = []
        self.current_guess = [0] * self.code_len
        self.won = False
        self.lost = False
        self.game_active = True

    def _check_guess(self, guess):
        exact = 0
        partial = 0
        secret_remaining = []
        guess_remaining = []
        for i in range(self.code_len):
            if guess[i] == self.secret[i]:
                exact += 1
            else:
                secret_remaining.append(self.secret[i])
                guess_remaining.append(guess[i])
        for g in guess_remaining:
            if g in secret_remaining:
                partial += 1
                secret_remaining.remove(g)
        return exact, partial

    def handle_key(self, key):
        if self.won or self.lost or not self.game_active:
            self.reset()
            self.render()
            return

        col = key % self.cols
        row = key // self.cols
        last_r = self.rows - 1

        # Bottom row = guess slots
        if row == last_r and col < self.code_len:
            self.current_guess[col] = (self.current_guess[col] + 1) % len(COLORS)
            self.render()
            return

        # Submit button (top-right)
        if key == self.cols - 1:
            guess = self.current_guess[:]
            exact, partial = self._check_guess(guess)
            self.guesses.append(guess)
            self.feedbacks.append((exact, partial))

            if exact == self.code_len:
                self.won = True
                self.games_won += 1
                self.games_played += 1
            elif len(self.guesses) >= self.max_guesses:
                self.lost = True
                self.games_played += 1

            self.current_guess = [0] * self.code_len
            self.render()

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_TITLE, "MIND")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.games_played:
                    self._set_key(key, (40, 40, 80), f"W:{self.games_won}")
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            return

        # Render grid
        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols

            if self.won or self.lost:
                # Show secret on top row
                if r == 0 and c < self.code_len:
                    self._set_key(key, COLORS[self.secret[c]], "")
                elif (c, r) == (mid_c, last_r):
                    color = COLOR_WIN if self.won else COLOR_LOSE
                    text = "WIN!" if self.won else "LOST"
                    self._set_key(key, color, text)
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                    self._set_key(key, (40, 40, 80), f"{len(self.guesses)}try")
                else:
                    self._set_key(key, COLOR_EMPTY, "")
                continue

            # Submit button
            if key == self.cols - 1:
                self._set_key(key, COLOR_SUBMIT, "GO")
                continue

            # Current guess (bottom row)
            if r == last_r and c < self.code_len:
                self._set_key(key, COLORS[self.current_guess[c]], "")
                continue

            # Previous guesses and feedback
            guess_idx = r
            if guess_idx < len(self.guesses):
                if c < self.code_len:
                    self._set_key(key, COLORS[self.guesses[guess_idx][c]], "")
                elif c == self.code_len:
                    exact, partial = self.feedbacks[guess_idx]
                    self._set_key(
                        key, COLOR_EXACT if exact else COLOR_MISS,
                        f"{exact}E{partial}P"
                    )
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            else:
                self._set_key(key, COLOR_EMPTY, "")

    def _set_key(self, key, color, text=""):
        fmt = self.deck.key_image_format()
        w, h = fmt["size"]
        img = Image.new("RGB", (w, h), color)
        if text:
            draw = ImageDraw.Draw(img)
            font_size = 16 if len(text) <= 4 else 10
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
    print(f"Mastermind on {deck.deck_type()} ({cols}x{rows})")
    print("Bottom row=guess, TR=submit. Ctrl+C to quit.")

    game = Mastermind(deck)
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
        print(f"\nWon: {game.games_won}/{game.games_played}")



if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
