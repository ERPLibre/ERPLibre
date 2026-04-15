#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Pong for Elgato Stream Deck (1P vs AI or 2P with two decks).

1 deck: left col = you, right col = AI.
2 decks: each player controls their paddle on their own deck.
Both decks show the same shared game field.
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
COLOR_PADDLE = (200, 200, 200)
COLOR_BALL = (255, 255, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)
COLOR_LOSE = (200, 0, 0)

TICK_SPEED = 0.4
WINNING_SCORE = 5


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 18 if len(text) <= 4 else 12
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


class Pong:
    def __init__(self, decks):
        self.decks = decks
        self.num_players = len(decks)
        rows, cols = decks[0].key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.running = True
        self.game_active = False
        self.game_over = False
        self.p1_row = rows // 2
        self.p2_row = rows // 2
        self.ball_col = cols // 2
        self.ball_row = rows // 2
        self.ball_dx = 1
        self.ball_dy = random.choice([-1, 1])
        self.p1_score = 0
        self.p2_score = 0

    def reset(self):
        self.p1_row = self.rows // 2
        self.p2_row = self.rows // 2
        self._reset_ball()
        self.p1_score = 0
        self.p2_score = 0
        self.game_over = False
        self.game_active = True

    def _reset_ball(self):
        self.ball_col = self.cols // 2
        self.ball_row = self.rows // 2
        self.ball_dx = random.choice([-1, 1])
        self.ball_dy = random.choice([-1, 1])

    def tick(self):
        if not self.game_active or self.game_over:
            return

        # AI for P2 in solo mode
        if self.num_players == 1:
            if self.ball_row < self.p2_row:
                self.p2_row = max(0, self.p2_row - 1)
            elif self.ball_row > self.p2_row:
                self.p2_row = min(self.rows - 1, self.p2_row + 1)

        new_col = self.ball_col + self.ball_dx
        new_row = self.ball_row + self.ball_dy

        if new_row < 0:
            new_row = 0
            self.ball_dy = 1
        elif new_row >= self.rows:
            new_row = self.rows - 1
            self.ball_dy = -1

        last_col = self.cols - 1

        # P1 paddle (col 0)
        if new_col <= 0:
            if abs(new_row - self.p1_row) <= 0:
                new_col = 1
                self.ball_dx = 1
            else:
                self.p2_score += 1
                if self.p2_score >= WINNING_SCORE:
                    self.game_over = True
                self._reset_ball()
                return

        # P2 paddle (last col)
        if new_col >= last_col:
            if abs(new_row - self.p2_row) <= 0:
                new_col = last_col - 1
                self.ball_dx = -1
            else:
                self.p1_score += 1
                if self.p1_score >= WINNING_SCORE:
                    self.game_over = True
                self._reset_ball()
                return

        self.ball_col = new_col
        self.ball_row = new_row

    def handle_key(self, key, deck_index=0):
        if self.game_over or not self.game_active:
            self.reset()
            return

        row = key // self.cols

        if self.num_players == 2:
            if deck_index == 0:
                self.p1_row = row
            else:
                self.p2_row = row
        else:
            col = key % self.cols
            if col == 0:
                self.p1_row = row
            elif row < self.p1_row:
                self.p1_row = max(0, self.p1_row - 1)
            elif row > self.p1_row:
                self.p1_row = min(self.rows - 1, self.p1_row + 1)

    def render_all(self):
        for i, deck in enumerate(self.decks):
            self._render(deck, i)

    def _render(self, deck, deck_index):
        mid_c = self.cols // 2
        last_c = self.cols - 1
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, key, COLOR_TITLE, "PONG")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "START")
                elif self.num_players == 2 and (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                    set_key(deck, key, COLOR_PADDLE, f"P{deck_index + 1}")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            return

        if self.game_over:
            p1_won = self.p1_score >= WINNING_SCORE
            if self.num_players == 2:
                i_won = (deck_index == 0 and p1_won) or (deck_index == 1 and not p1_won)
            else:
                i_won = p1_won
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, key, COLOR_WIN if i_won else COLOR_LOSE, "WIN!" if i_won else "LOSE")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    set_key(deck, key, COLOR_SCORE, f"{self.p1_score}-{self.p2_score}")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            return

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols
            if c == self.ball_col and r == self.ball_row:
                set_key(deck, key, COLOR_BALL, "")
            elif c == 0 and r == self.p1_row:
                set_key(deck, key, COLOR_PADDLE, "||")
            elif c == last_c and r == self.p2_row:
                set_key(deck, key, COLOR_PADDLE, "||")
            elif c == mid_c and r == 0:
                set_key(deck, key, COLOR_SCORE, f"{self.p1_score}-{self.p2_score}")
            else:
                set_key(deck, key, COLOR_EMPTY, "")

    def game_loop(self):
        while self.running and all(d.is_open() for d in self.decks):
            with self.lock:
                self.tick()
                self.render_all()
            time.sleep(TICK_SPEED)


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
    rows, cols = decks[0].key_layout()

    if len(decks) == 2:
        print(f"2-PLAYER PONG! P1={decks[0].deck_type()} P2={decks[1].deck_type()}")
        print(f"Each deck: press any key to move paddle to that row. First to {WINNING_SCORE}!")
    else:
        print(f"Pong vs AI on {decks[0].deck_type()} ({cols}x{rows})")
        print(f"Left col=you. First to {WINNING_SCORE}! Ctrl+C to quit.")

    game = Pong(decks)
    game.render_all()

    for i, deck in enumerate(decks):
        def make_cb(idx):
            def cb(deck, key, state):
                if not state:
                    return
                with game.lock:
                    game.handle_key(key, deck_index=idx)
            return cb
        deck.set_key_callback(make_cb(i))

    t = threading.Thread(target=game.game_loop, daemon=True)
    t.start()

    try:
        while all(d.is_open() for d in decks):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        game.running = False
        for d in decks:
            try:
                with d:
                    d.reset()
                    d.close()
            except Exception:
                pass
        print(f"\nScore: {game.p1_score}-{game.p2_score}")


if __name__ == "__main__":
    main()
