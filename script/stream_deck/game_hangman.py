#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Hangman.

Each button = a letter. Press to guess. 6 wrong guesses = game over.
Word shown on touchscreen (SD+) or top row buttons.
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

WORDS = [
    "PYTHON", "LINUX", "ODOO", "CODE", "GAME", "DECK", "STREAM",
    "PIXEL", "BYTE", "DATA", "CLOUD", "STACK", "QUERY", "DEBUG",
    "FLASK", "REACT", "RUST", "SWIFT", "JAVA", "RUBY", "PERL",
]
COLOR_EMPTY = (40, 40, 50)
COLOR_CORRECT = (0, 160, 0)
COLOR_WRONG = (160, 0, 0)
COLOR_UNUSED = (60, 60, 80)
COLOR_TITLE = (0, 80, 160)
COLOR_WIN = (0, 200, 60)
MAX_WRONG = 6


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 22 if len(text) <= 1 else (16 if len(text) <= 3 else 11)
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


class Hangman:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.word = ""
        self.guessed = set()
        self.wrong = 0
        self.game_active = False
        self.won = False
        self.game_over = False
        self.wins = 0
        # Map keys to letters
        self.letters = []
        self._assign_letters()

    def _assign_letters(self):
        alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        self.letters = {}
        for i, ch in enumerate(alpha):
            if i < self.total_keys:
                self.letters[i] = ch

    def reset(self):
        self.word = random.choice(WORDS)
        self.guessed = set()
        self.wrong = 0
        self.won = False
        self.game_over = False
        self.game_active = True

    def handle_key(self, key):
        if self.game_over or not self.game_active:
            self.reset()
            self.render()
            return

        if key not in self.letters:
            return
        letter = self.letters[key]
        if letter in self.guessed:
            return

        self.guessed.add(letter)
        if letter not in self.word:
            self.wrong += 1
            if self.wrong >= MAX_WRONG:
                self.game_over = True
        elif all(c in self.guessed for c in self.word):
            self.won = True
            self.game_over = True
            self.wins += 1

        self.render()

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_TITLE, "HANG")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.wins:
                    set_key(self.deck, key, (40, 40, 80), f"W:{self.wins}")
                elif key in self.letters:
                    set_key(self.deck, key, COLOR_UNUSED, self.letters[key])
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        # Build display word
        display = " ".join(c if c in self.guessed else "_" for c in self.word)

        if self.game_over:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_WIN if self.won else COLOR_WRONG, "WIN!" if self.won else self.word)
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        for key in range(self.total_keys):
            if key not in self.letters:
                if key == 0:
                    set_key(self.deck, key, (40, 40, 80), f"{MAX_WRONG - self.wrong}")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
                continue

            letter = self.letters[key]
            if letter in self.guessed:
                if letter in self.word:
                    set_key(self.deck, key, COLOR_CORRECT, letter)
                else:
                    set_key(self.deck, key, COLOR_WRONG, letter)
            else:
                set_key(self.deck, key, COLOR_UNUSED, letter)

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
    print(f"Hangman on {deck.deck_type()}")
    print(f"Each button = a letter. {MAX_WRONG} wrong = game over.")
    game = Hangman(deck)
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
        print(f"\nWins: {game.wins}")


if __name__ == "__main__":
    main()
