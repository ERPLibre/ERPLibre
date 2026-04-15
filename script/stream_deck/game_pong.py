#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Pong (1P vs AI) for Elgato Stream Deck (adapts to any layout, rotated 90°).

Left column = player paddle. Right column = AI paddle. Ball bounces.
Press left column buttons to move your paddle.
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


class Pong:
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
        self.player_row = rows // 2
        self.ai_row = rows // 2
        self.ball_col = cols // 2
        self.ball_row = rows // 2
        self.ball_dx = 1
        self.ball_dy = random.choice([-1, 1])
        self.player_score = 0
        self.ai_score = 0

    def reset(self):
        self.player_row = self.rows // 2
        self.ai_row = self.rows // 2
        self.ball_col = self.cols // 2
        self.ball_row = self.rows // 2
        self.ball_dx = random.choice([-1, 1])
        self.ball_dy = random.choice([-1, 1])
        self.player_score = 0
        self.ai_score = 0
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

        # AI moves toward ball
        if self.ball_row < self.ai_row:
            self.ai_row = max(0, self.ai_row - 1)
        elif self.ball_row > self.ai_row:
            self.ai_row = min(self.rows - 1, self.ai_row + 1)

        new_col = self.ball_col + self.ball_dx
        new_row = self.ball_row + self.ball_dy

        # Top/bottom bounce
        if new_row < 0:
            new_row = 0
            self.ball_dy = 1
        elif new_row >= self.rows:
            new_row = self.rows - 1
            self.ball_dy = -1

        last_col = self.cols - 1

        # Player paddle (col 0)
        if new_col <= 0:
            if new_row == self.player_row:
                new_col = 1
                self.ball_dx = 1
            else:
                self.ai_score += 1
                if self.ai_score >= WINNING_SCORE:
                    self.game_over = True
                self._reset_ball()
                return

        # AI paddle (last col)
        if new_col >= last_col:
            if new_row == self.ai_row:
                new_col = last_col - 1
                self.ball_dx = -1
            else:
                self.player_score += 1
                if self.player_score >= WINNING_SCORE:
                    self.game_over = True
                self._reset_ball()
                return

        self.ball_col = new_col
        self.ball_row = new_row

    def handle_key(self, key):
        if self.game_over or not self.game_active:
            self.reset()
            return

        col = key % self.cols
        row = key // self.cols

        if col == 0:
            self.player_row = row
        elif row < self.player_row:
            self.player_row = max(0, self.player_row - 1)
        elif row > self.player_row:
            self.player_row = min(self.rows - 1, self.player_row + 1)

    def render(self):
        mid_c = self.cols // 2
        last_c = self.cols - 1
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_TITLE, "PONG")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "START")
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            return

        if self.game_over:
            won = self.player_score >= WINNING_SCORE
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    color = COLOR_WIN if won else COLOR_LOSE
                    self._set_key(key, color, "WIN!" if won else "LOSE")
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
            elif c == 0 and r == self.player_row:
                self._set_key(key, COLOR_PADDLE, "||")
            elif c == last_c and r == self.ai_row:
                self._set_key(key, COLOR_PADDLE, "||")
            elif c == mid_c and r == 0:
                self._set_key(
                    key, COLOR_SCORE,
                    f"{self.player_score}-{self.ai_score}"
                )
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
            font_size = 18 if len(text) <= 4 else 12
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
    print(f"Pong on {deck.deck_type()} ({cols}x{rows})")
    print(f"Left col=you, right=AI. First to {WINNING_SCORE}! Ctrl+C to quit.")

    game = Pong(deck)
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
        print(f"\nScore: {game.player_score}-{game.ai_score}")


if __name__ == "__main__":
    main()
