#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Breakout game.

Rotated 90°: left columns = bricks, rightmost column = paddle, ball
bounces horizontally. Press right column buttons to move paddle up/down.
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
COLOR_GAMEOVER = (180, 0, 0)

BRICK_COLORS = [
    (220, 40, 40),
    (220, 140, 0),
    (0, 180, 0),
    (0, 100, 220),
    (160, 0, 160),
]

TICK_SPEED = 0.6


class Breakout:
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
        self.won = False
        self.score = 0
        self.high_score = 0
        # Brick columns = ~half the grid, leave room for ball + paddle
        self.brick_cols = max(1, (self.cols - 1) // 2)
        self.bricks = set()
        self.paddle_row = rows // 2
        self.ball_col = 0
        self.ball_row = 0
        self.ball_dx = 1
        self.ball_dy = 1

    def reset(self):
        self.bricks = set()
        for c in range(self.brick_cols):
            for r in range(self.rows):
                self.bricks.add((c, r))

        self.paddle_row = self.rows // 2
        self.ball_col = self.cols - 2
        self.ball_row = self.rows // 2
        self.ball_dx = -1
        self.ball_dy = random.choice([-1, 1])
        self.score = 0
        self.game_over = False
        self.won = False
        self.game_active = True

    def tick(self):
        if not self.game_active or self.game_over:
            return

        new_col = self.ball_col + self.ball_dx
        new_row = self.ball_row + self.ball_dy

        # Wall bounce (top/bottom)
        if new_row < 0:
            new_row = 0
            self.ball_dy = 1
        elif new_row >= self.rows:
            new_row = self.rows - 1
            self.ball_dy = -1

        # Left wall bounce
        if new_col < 0:
            new_col = 0
            self.ball_dx = 1

        # Paddle bounce (right column)
        last_col = self.cols - 1
        if new_col >= last_col:
            if new_row == self.paddle_row:
                new_col = last_col - 1
                self.ball_dx = -1
            elif (
                new_row == self.paddle_row - 1
                or new_row == self.paddle_row + 1
            ):
                new_col = last_col - 1
                self.ball_dx = -1
                if new_row < self.paddle_row:
                    self.ball_dy = -1
                else:
                    self.ball_dy = 1
            else:
                # Miss — game over
                self.game_over = True
                if self.score > self.high_score:
                    self.high_score = self.score
                return

        # Brick collision
        if (new_col, new_row) in self.bricks:
            self.bricks.discard((new_col, new_row))
            self.score += 1
            self.ball_dx = -self.ball_dx
            new_col = self.ball_col

            if not self.bricks:
                self.won = True
                self.game_over = True
                if self.score > self.high_score:
                    self.high_score = self.score
                return

        self.ball_col = new_col
        self.ball_row = new_row

    def handle_key(self, key):
        if self.game_over or not self.game_active:
            self.reset()
            self.render()
            return

        col = key % self.cols
        row = key // self.cols

        # Right column = move paddle directly
        last_col = self.cols - 1
        if col == last_col:
            self.paddle_row = row
        elif row < self.paddle_row:
            self.paddle_row = max(0, self.paddle_row - 1)
        elif row > self.paddle_row:
            self.paddle_row = min(self.rows - 1, self.paddle_row + 1)

    def render(self):
        mid_c = self.cols // 2
        mid_r = self.rows // 2
        last_c = self.cols - 1
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_TITLE, "BREAK")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.high_score:
                    self._set_key(key, COLOR_SCORE, f"HI:{self.high_score}")
                elif c < self.brick_cols:
                    self._set_key(
                        key,
                        BRICK_COLORS[c % len(BRICK_COLORS)],
                        ""
                    )
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            return

        if self.game_over:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    color = COLOR_WIN if self.won else COLOR_GAMEOVER
                    text = "WIN!" if self.won else "OVER"
                    self._set_key(key, color, text)
                elif (c, r) == (mid_c, mid_r):
                    self._set_key(key, COLOR_SCORE, f"S:{self.score}")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "AGAIN")
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            return

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols

            if c == self.ball_col and r == self.ball_row:
                self._set_key(key, COLOR_BALL, "")
            elif c == last_c and r == self.paddle_row:
                self._set_key(key, COLOR_PADDLE, "||")
            elif (c, r) in self.bricks:
                self._set_key(
                    key,
                    BRICK_COLORS[c % len(BRICK_COLORS)],
                    ""
                )
            elif c == last_c and r == 0:
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
            font_size = 22 if len(text) <= 3 else 14
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
    if not streamdecks:
        print("No Stream Deck found.")
        sys.exit(1)

    deck = None
    for d in streamdecks:
        if d.is_visual():
            deck = d
            break

    if deck is None:
        print("No visual Stream Deck found.")
        sys.exit(1)

    deck.open()
    deck.reset()
    deck.set_brightness(80)

    rows, cols = deck.key_layout()
    print(f"Breakout on {deck.deck_type()} ({cols}x{rows})")
    print("Right column = paddle. Press to move! Ctrl+C to quit.")

    game = Breakout(deck)
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
