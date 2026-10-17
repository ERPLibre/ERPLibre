#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Wordle.

Guess a 5-letter word. Each button cycles through letters. Top row
shows your current guess. Press last button to submit. Colors show
green (correct), yellow (wrong place), grey (not in word).
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
    "name": "Wordle",
    "category": "word",
    "multiplayer": False,
    "sdplus": False,
    "description": "Guess a 5-letter word. Green/yellow/grey hints. 6 tries.",
    "icon": "wordle"
}

WORDS = [
    "CRANE", "SLATE", "TRACE", "RAISE", "STARE", "AUDIO", "RESIN",
    "CLOUD", "FRAME", "GLOBE", "PIXEL", "STACK", "DEBUG", "FLASK",
    "SWIFT", "REACT", "LIGHT", "STORM", "BRAIN", "CHORD", "DWARF",
    "GRAPE", "HAVEN", "JOKER", "KNIFE", "LEMON", "MANGO", "NOBLE",
]
WORD_LEN = 5
MAX_GUESSES = 6
COLOR_CORRECT = (0, 160, 0)
COLOR_PRESENT = (200, 180, 0)
COLOR_ABSENT = (60, 60, 70)
COLOR_EMPTY = (20, 20, 30)
COLOR_INPUT = (80, 80, 100)
COLOR_TITLE = (0, 80, 160)
COLOR_WIN = (0, 200, 60)
COLOR_LOSE = (200, 0, 0)


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 24 if len(text) <= 1 else (18 if len(text) <= 3 else 12)
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


class Wordle:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.word = ""
        self.current = [0] * WORD_LEN
        self.guesses = []
        self.results = []
        self.game_active = False
        self.won = False
        self.game_over = False
        self.wins = 0

    def reset(self):
        self.word = random.choice(WORDS)
        self.current = [0] * WORD_LEN
        self.guesses = []
        self.results = []
        self.won = False
        self.game_over = False
        self.game_active = True

    def _check(self, guess):
        result = [COLOR_ABSENT] * WORD_LEN
        word_chars = list(self.word)
        # Green pass
        for i in range(WORD_LEN):
            if guess[i] == self.word[i]:
                result[i] = COLOR_CORRECT
                word_chars[i] = None
        # Yellow pass
        for i in range(WORD_LEN):
            if result[i] != COLOR_CORRECT and guess[i] in word_chars:
                result[i] = COLOR_PRESENT
                word_chars[word_chars.index(guess[i])] = None
        return result

    def handle_key(self, key):
        if self.game_over or not self.game_active:
            self.reset()
            self.render()
            return

        col = key % self.cols
        row = key // self.cols
        last_r = self.rows - 1

        # Bottom row: first WORD_LEN buttons = letter cycling, last = submit
        if row == last_r:
            if col < WORD_LEN:
                self.current[col] = (self.current[col] + 1) % 26
            elif col == self.cols - 1:
                # Submit
                guess = "".join(chr(65 + c) for c in self.current)
                result = self._check(guess)
                self.guesses.append(guess)
                self.results.append(result)

                if guess == self.word:
                    self.won = True
                    self.game_over = True
                    self.wins += 1
                elif len(self.guesses) >= MAX_GUESSES:
                    self.game_over = True

                self.current = [0] * WORD_LEN

        self.render()

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_TITLE, "WORD")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.wins:
                    set_key(self.deck, key, (40, 40, 80), f"W:{self.wins}")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        if self.game_over:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_WIN if self.won else COLOR_LOSE, "WIN!" if self.won else self.word)
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "AGAIN")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    set_key(self.deck, key, (40, 40, 80), f"{len(self.guesses)}try")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        # Show previous guesses on upper rows
        for g_idx, (guess, result) in enumerate(zip(self.guesses, self.results)):
            if g_idx >= self.rows - 1:
                break
            for i in range(min(WORD_LEN, self.cols)):
                key = g_idx * self.cols + i
                set_key(self.deck, key, result[i], guess[i])
            for i in range(WORD_LEN, self.cols):
                key = g_idx * self.cols + i
                set_key(self.deck, key, COLOR_EMPTY, "")

        # Clear remaining rows (except bottom)
        for r in range(len(self.guesses), last_r):
            for c in range(self.cols):
                set_key(self.deck, r * self.cols + c, COLOR_EMPTY, "")

        # Bottom row: current guess letters + submit
        for c in range(self.cols):
            key = last_r * self.cols + c
            if c < WORD_LEN:
                letter = chr(65 + self.current[c])
                set_key(self.deck, key, COLOR_INPUT, letter)
            elif c == self.cols - 1:
                set_key(self.deck, key, COLOR_TITLE, "GO")
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

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
    print(f"Wordle on {deck.deck_type()}")
    print(f"Bottom row: press letter to cycle A-Z. Last button = submit.")
    print(f"Green=correct, Yellow=wrong place, Grey=absent. {MAX_GUESSES} tries.")
    game = Wordle(deck)
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



if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
