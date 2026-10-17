#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Rock Paper Scissors — 1P vs AI or 2P.

Press Rock, Paper, or Scissors button. Best of 5 rounds.
2 decks: simultaneous reveal — both choose, then show result!
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
    "name": "Rock Paper Scissors",
    "category": "reflex",
    "multiplayer": True,
    "sdplus": False,
    "description": "Rock Paper Scissors! Best of 5. 1P or 2P.",
    "icon": "rps"
}

CHOICES = ["ROCK", "PAPER", "SCIS"]
CHOICE_COLORS = [(120, 120, 120), (200, 200, 200), (200, 50, 50)]
COLOR_EMPTY = (20, 20, 30)
COLOR_WIN = (0, 200, 60)
COLOR_LOSE = (200, 0, 0)
COLOR_DRAW = (120, 120, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)

ROUNDS = 5


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 16 if len(text) <= 4 else 11
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


def beats(a, b):
    return (a == 0 and b == 2) or (a == 1 and b == 0) or (a == 2 and b == 1)


class RPS:
    def __init__(self, decks):
        self.decks = decks
        self.num_players = len(decks)
        rows, cols = decks[0].key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.p1_choice = -1
        self.p2_choice = -1
        self.p1_score = 0
        self.p2_score = 0
        self.round = 0
        self.game_active = False
        self.show_result = False
        self.result_time = 0

    def reset(self):
        self.p1_choice = -1
        self.p2_choice = -1
        self.p1_score = 0
        self.p2_score = 0
        self.round = 0
        self.show_result = False
        self.game_active = True
        self._next_round()

    def _next_round(self):
        self.round += 1
        self.p1_choice = -1
        self.p2_choice = -1
        self.show_result = False

    def handle_key(self, key, deck_index=0):
        if not self.game_active or self.round > ROUNDS:
            self.reset()
            self.render_all()
            return

        if self.show_result:
            now = time.monotonic()
            if now - self.result_time < 2.0:
                return
            if self.round >= ROUNDS:
                self.game_active = False
                self.render_all()
                return
            self._next_round()
            self.render_all()
            return

        col = key % self.cols
        last_r = self.rows - 1

        # Bottom row = choices (first 3 buttons)
        row = key // self.cols
        if row == last_r and col < 3:
            choice = col
        else:
            return

        if self.num_players == 2:
            if deck_index == 0:
                self.p1_choice = choice
            else:
                self.p2_choice = choice
        else:
            self.p1_choice = choice
            self.p2_choice = random.randint(0, 2)

        if self.p1_choice >= 0 and self.p2_choice >= 0:
            if beats(self.p1_choice, self.p2_choice):
                self.p1_score += 1
            elif beats(self.p2_choice, self.p1_choice):
                self.p2_score += 1
            self.show_result = True
            self.result_time = time.monotonic()

        self.render_all()

    def render_all(self):
        for i, deck in enumerate(self.decks):
            self._render(deck, i)

    def _render(self, deck, di):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active and self.round == 0:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, key, COLOR_TITLE, "RPS")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "START")
                elif r == last_r and c < 3:
                    set_key(deck, key, CHOICE_COLORS[c], CHOICES[c])
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            return

        if not self.game_active:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    if self.p1_score > self.p2_score:
                        i_won = di == 0
                    elif self.p2_score > self.p1_score:
                        i_won = di == 1
                    else:
                        i_won = None
                    if i_won is None:
                        set_key(deck, key, COLOR_DRAW, "DRAW")
                    elif (self.num_players == 1 and i_won) or (self.num_players == 2 and i_won):
                        set_key(deck, key, COLOR_WIN, "WIN!")
                    else:
                        set_key(deck, key, COLOR_LOSE, "LOSE")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    set_key(deck, key, COLOR_SCORE, f"{self.p1_score}-{self.p2_score}")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            return

        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            if r == last_r and c < 3:
                my_choice = self.p1_choice if di == 0 else self.p2_choice
                if my_choice == c:
                    set_key(deck, key, CHOICE_COLORS[c], CHOICES[c])
                else:
                    set_key(deck, key, (40, 40, 50), CHOICES[c])
            elif (c, r) == (mid_c, 0):
                if self.show_result:
                    opp = self.p2_choice if di == 0 else self.p1_choice
                    set_key(deck, key, CHOICE_COLORS[opp], CHOICES[opp])
                else:
                    set_key(deck, key, COLOR_SCORE, f"R{self.round}")
            elif (c, r) == (0, 0):
                set_key(deck, key, COLOR_SCORE, f"{self.p1_score}-{self.p2_score}")
            elif self.show_result and (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                my = self.p1_choice if di == 0 else self.p2_choice
                opp = self.p2_choice if di == 0 else self.p1_choice
                if beats(my, opp):
                    set_key(deck, key, COLOR_WIN, "WIN")
                elif beats(opp, my):
                    set_key(deck, key, COLOR_LOSE, "LOSE")
                else:
                    set_key(deck, key, COLOR_DRAW, "TIE")
            else:
                set_key(deck, key, COLOR_EMPTY, "")


def main():
    streamdecks = DeviceManager().enumerate()
    visual = [d for d in streamdecks if d.is_visual()]
    if not visual:
        print("No visual Stream Deck found.")
        sys.exit(1)
    for d in visual:
        d.open()
        d.reset()
        d.set_brightness(80)
    decks = visual[:2] if len(visual) >= 2 else visual[:1]
    if len(decks) == 2:
        print("2-PLAYER Rock Paper Scissors! Simultaneous reveal!")
    else:
        print("Rock Paper Scissors vs AI!")
    print(f"Best of {ROUNDS}. Bottom 3 buttons = Rock/Paper/Scissors.")
    game = RPS(decks)
    game.render_all()
    for i, deck in enumerate(decks):
        def make_cb(idx):
            def cb(d, k, s):
                if not s:
                    return
                with game.lock:
                    game.handle_key(k, idx)
            return cb
        deck.set_key_callback(make_cb(i))
    try:
        while all(d.is_open() for d in decks):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for d in decks:
            try:
                with d:
                    d.reset()
                    d.close()
            except Exception:
                pass
        print(f"\nScore: {game.p1_score}-{game.p2_score}")



if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
