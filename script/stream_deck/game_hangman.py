#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Hangman.

Each button = a letter. Press to guess. 6 wrong guesses = game over.
Word shown on touchscreen (SD+) or top row buttons.
"""

import argparse
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
    "name": "Hangman",
    "category": "word",
    "multiplayer": False,
    "sdplus": False,
    "description": "Guess the word, one letter at a time. 6 wrong = over.",
    "icon": "hangman"
}

WORDS_FR = [
    "MAISON", "SOLEIL", "LIVRE", "ARBRE", "CHIEN", "FLEUR",
    "ECOLE", "JARDIN", "NUAGE", "VILLE", "TERRE", "POMME",
    "ROUGE", "BLANC", "TABLE", "CHAISE", "PORTE", "LAMPE",
    "PLAGE", "FORET", "LUNDI", "NUIT", "TEMPS", "REINE",
    "AVION", "MONDE", "PIANO", "BRISE", "NEIGE", "TIGRE",
    "OCEAN", "SUCRE", "PERLE", "COEUR", "LAINE", "GESTE",
]
WORDS_EN = [
    "PYTHON", "LINUX", "ODOO", "CODE", "GAME", "DECK", "STREAM",
    "PIXEL", "BYTE", "DATA", "CLOUD", "STACK", "QUERY", "DEBUG",
    "FLASK", "REACT", "RUST", "SWIFT", "JAVA", "RUBY", "PEARL",
    "HOUSE", "TABLE", "CHAIR", "LIGHT", "BEACH", "TIGER", "SUGAR",
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
        draw.text(((w - tw) // 2 + 1, (h - th) // 2 + 1), text,
                  fill=(0, 0, 0), font=font)
        draw.text(((w - tw) // 2, (h - th) // 2), text,
                  fill=(255, 255, 255), font=font)
    native = PILHelper.to_native_key_format(deck, img)
    try:
        with deck:
            deck.set_key_image(key, native)
    except TransportError:
        pass


def set_key_hangman(deck, key, wrong):
    """Draw hangman figure based on wrong guess count (0-6)."""
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), (30, 30, 40))
    draw = ImageDraw.Draw(img)
    # Gallows
    gx, gy = w // 4, h - 10
    draw.line([(gx - 15, gy), (gx + 15, gy)], fill=(150, 150, 150), width=2)
    draw.line([(gx, gy), (gx, 8)], fill=(150, 150, 150), width=2)
    draw.line([(gx, 8), (w // 2 + 5, 8)], fill=(150, 150, 150), width=2)
    draw.line([(w // 2 + 5, 8), (w // 2 + 5, 18)],
              fill=(150, 150, 150), width=2)
    cx = w // 2 + 5  # center of body
    color = (255, 255, 255)
    # 1: head
    if wrong >= 1:
        draw.ellipse([cx - 7, 18, cx + 7, 32], outline=color, width=2)
    # 2: body
    if wrong >= 2:
        draw.line([(cx, 32), (cx, 55)], fill=color, width=2)
    # 3: left arm
    if wrong >= 3:
        draw.line([(cx, 38), (cx - 12, 48)], fill=color, width=2)
    # 4: right arm
    if wrong >= 4:
        draw.line([(cx, 38), (cx + 12, 48)], fill=color, width=2)
    # 5: left leg
    if wrong >= 5:
        draw.line([(cx, 55), (cx - 10, 68)], fill=color, width=2)
    # 6: right leg
    if wrong >= 6:
        draw.line([(cx, 55), (cx + 10, 68)], fill=color, width=2)
    native = PILHelper.to_native_key_format(deck, img)
    try:
        with deck:
            deck.set_key_image(key, native)
    except TransportError:
        pass


class Hangman:
    def __init__(self, deck, words=None):
        self.deck = deck
        self.words = words or WORDS_FR
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
        # Extra keys after letters: 5 word slots + 1 hangman
        self.word_keys = []
        self.hangman_key = -1
        extra_start = len(alpha)
        remaining = self.total_keys - extra_start
        if remaining >= 6:
            self.word_keys = list(range(extra_start, extra_start + 5))
            self.hangman_key = extra_start + 5
        elif remaining >= 1:
            self.word_keys = list(range(extra_start,
                                        extra_start + remaining - 1))
            self.hangman_key = extra_start + remaining - 1

    def reset(self):
        self.word = random.choice(self.words)
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

    def _get_word_chunks(self, word=None):
        """Split word display into chunks for the word keys."""
        if word is None:
            display = "".join(
                c if c in self.guessed else "_" for c in self.word
            )
        else:
            display = word
        n = len(self.word_keys)
        if n == 0:
            return []
        # Even distribution: spread letters across all keys
        wlen = len(display)
        chunks = []
        for i in range(n):
            start = i * wlen // n
            end = (i + 1) * wlen // n
            chunks.append(display[start:end])
        return chunks

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
                    set_key(self.deck, key, (40, 40, 80),
                            f"W:{self.wins}")
                elif key in self.letters:
                    set_key(self.deck, key, COLOR_UNUSED,
                            self.letters[key])
                elif key in self.word_keys:
                    set_key(self.deck, key, COLOR_EMPTY, "")
                elif key == self.hangman_key:
                    set_key_hangman(self.deck, key, 0)
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        if self.game_over:
            # Show full word on word keys
            chunks = self._get_word_chunks(self.word)
            for i, wk in enumerate(self.word_keys):
                chunk = chunks[i] if i < len(chunks) else ""
                color = COLOR_WIN if self.won else COLOR_WRONG
                set_key(self.deck, wk, color, chunk)
            if self.hangman_key >= 0:
                set_key_hangman(self.deck, self.hangman_key, self.wrong)
            for key in range(self.total_keys):
                if key in self.word_keys or key == self.hangman_key:
                    continue
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "AGAIN")
                elif key in self.letters:
                    letter = self.letters[key]
                    if letter in self.word:
                        set_key(self.deck, key, COLOR_CORRECT, letter)
                    elif letter in self.guessed:
                        set_key(self.deck, key, COLOR_WRONG, letter)
                    else:
                        set_key(self.deck, key, (30, 30, 40), letter)
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        # Active game
        chunks = self._get_word_chunks()
        for i, wk in enumerate(self.word_keys):
            chunk = chunks[i] if i < len(chunks) else ""
            set_key(self.deck, wk, (0, 50, 80), chunk)

        if self.hangman_key >= 0:
            set_key_hangman(self.deck, self.hangman_key, self.wrong)

        for key in range(self.total_keys):
            if key in self.word_keys or key == self.hangman_key:
                continue
            if key not in self.letters:
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
    parser = argparse.ArgumentParser(description="Hangman on Stream Deck")
    parser.add_argument(
        "-l", "--lang", choices=["fr", "en"], default="fr",
        help="Language for words (default: fr)",
    )
    args = parser.parse_args()
    words = WORDS_FR if args.lang == "fr" else WORDS_EN

    streamdecks = DeviceManager().enumerate()
    deck = next((d for d in streamdecks if d.is_visual()), None)
    if not deck:
        print("No visual Stream Deck found.")
        sys.exit(1)
    deck.open()
    deck.reset()
    deck.set_brightness(80)
    lang_label = "Français" if args.lang == "fr" else "English"
    print(f"Hangman on {deck.deck_type()} ({lang_label})")
    print(f"Each button = a letter. {MAX_WRONG} wrong = game over.")
    game = Hangman(deck, words=words)
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
