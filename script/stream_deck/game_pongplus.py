#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Pong+ (SD+ touchscreen + dial paddles).

Ball bounces on the 800x100 touchscreen. Dial 1 = left paddle,
Dial 4 = right paddle (or AI). 2 Stream Deck+ = 2 players!
"""

import io
import os
import random
import sys
import threading
import time

try:
    from PIL import Image, ImageDraw, ImageFont
    from StreamDeck.DeviceManager import DeviceManager
    from StreamDeck.Devices.StreamDeck import DialEventType, TouchscreenEventType
    from StreamDeck.ImageHelpers import PILHelper
    from StreamDeck.Transport.Transport import TransportError
except ImportError as e:
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

TICK_SPEED = 0.03
PADDLE_H = 30
PADDLE_W = 6
BALL_SIZE = 8
WINNING_SCORE = 5
PADDLE_SPEED = 8


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


def set_screen(deck, img):
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="JPEG")
    img_bytes = img_bytes.getvalue()
    try:
        with deck:
            w = deck.TOUCHSCREEN_PIXEL_WIDTH or deck.SCREEN_PIXEL_WIDTH or 800
            h = deck.TOUCHSCREEN_PIXEL_HEIGHT or deck.SCREEN_PIXEL_HEIGHT or 100
            if deck.DECK_TOUCH:
                deck.set_touchscreen_image(img_bytes, 0, 0, w, h)
            else:
                deck.set_screen_image(img_bytes)
    except (TransportError, AttributeError):
        pass


class PongPlus:
    def __init__(self, decks):
        self.decks = decks
        self.num_players = len(decks)
        self.deck = decks[0]
        rows, cols = self.deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.running = True
        self.screen_w = self.deck.TOUCHSCREEN_PIXEL_WIDTH or self.deck.SCREEN_PIXEL_WIDTH or 800
        self.screen_h = self.deck.TOUCHSCREEN_PIXEL_HEIGHT or self.deck.SCREEN_PIXEL_HEIGHT or 100

        # Game state
        self.p1_y = self.screen_h // 2
        self.p2_y = self.screen_h // 2
        self.ball_x = self.screen_w // 2
        self.ball_y = self.screen_h // 2
        self.ball_dx = 3
        self.ball_dy = 2
        self.p1_score = 0
        self.p2_score = 0
        self.game_active = False
        self.game_over = False
        self.ball_speed = 3  # base speed (1-8)

    def reset(self):
        self.p1_y = self.screen_h // 2
        self.p2_y = self.screen_h // 2
        self._reset_ball()
        self.p1_score = 0
        self.p2_score = 0
        self.game_over = False
        self.game_active = True

    def _reset_ball(self):
        self.ball_x = self.screen_w // 2
        self.ball_y = self.screen_h // 2
        s = self.ball_speed
        self.ball_dx = random.choice([-s, s])
        self.ball_dy = random.choice([-(s - 1) or -1, (s - 1) or 1])

    def handle_dial(self, dial, event, value, deck_index=0):
        if not self.game_active or self.game_over:
            if event == DialEventType.PUSH and value:
                self.reset()
            return

        if event == DialEventType.TURN:
            if self.num_players == 2:
                if deck_index == 0:
                    self.p1_y = max(PADDLE_H // 2, min(self.screen_h - PADDLE_H // 2, self.p1_y + value * PADDLE_SPEED))
                else:
                    self.p2_y = max(PADDLE_H // 2, min(self.screen_h - PADDLE_H // 2, self.p2_y + value * PADDLE_SPEED))
            else:
                # Solo: dial 0 = P1, dial 3 = not used (AI)
                if dial == 0 or dial == 1:
                    self.p1_y = max(PADDLE_H // 2, min(self.screen_h - PADDLE_H // 2, self.p1_y + value * PADDLE_SPEED))

    def handle_touch(self, evt_type, value, deck_index=0):
        if not self.game_active:
            return
        # Touch to move paddle to y position
        y = value.get("y", self.screen_h // 2)
        if self.num_players == 2:
            if deck_index == 0:
                self.p1_y = max(PADDLE_H // 2, min(self.screen_h - PADDLE_H // 2, y))
            else:
                self.p2_y = max(PADDLE_H // 2, min(self.screen_h - PADDLE_H // 2, y))
        else:
            self.p1_y = max(PADDLE_H // 2, min(self.screen_h - PADDLE_H // 2, y))

    def tick(self):
        if not self.game_active or self.game_over:
            return

        # AI for P2 in solo
        if self.num_players == 1:
            if self.ball_y < self.p2_y - 3:
                self.p2_y = max(PADDLE_H // 2, self.p2_y - 2)
            elif self.ball_y > self.p2_y + 3:
                self.p2_y = min(self.screen_h - PADDLE_H // 2, self.p2_y + 2)

        self.ball_x += self.ball_dx
        self.ball_y += self.ball_dy

        # Top/bottom bounce
        if self.ball_y <= BALL_SIZE // 2:
            self.ball_y = BALL_SIZE // 2
            self.ball_dy = abs(self.ball_dy)
        elif self.ball_y >= self.screen_h - BALL_SIZE // 2:
            self.ball_y = self.screen_h - BALL_SIZE // 2
            self.ball_dy = -abs(self.ball_dy)

        # Left paddle
        if self.ball_x <= PADDLE_W + BALL_SIZE // 2:
            if abs(self.ball_y - self.p1_y) <= PADDLE_H // 2:
                self.ball_x = PADDLE_W + BALL_SIZE // 2
                self.ball_dx = abs(self.ball_dx)
                # Angle based on hit position
                offset = (self.ball_y - self.p1_y) / (PADDLE_H // 2)
                self.ball_dy = int(offset * 4)
            elif self.ball_x <= 0:
                self.p2_score += 1
                if self.p2_score >= WINNING_SCORE:
                    self.game_over = True
                self._reset_ball()

        # Right paddle
        if self.ball_x >= self.screen_w - PADDLE_W - BALL_SIZE // 2:
            if abs(self.ball_y - self.p2_y) <= PADDLE_H // 2:
                self.ball_x = self.screen_w - PADDLE_W - BALL_SIZE // 2
                self.ball_dx = -abs(self.ball_dx)
                offset = (self.ball_y - self.p2_y) / (PADDLE_H // 2)
                self.ball_dy = int(offset * 4)
            elif self.ball_x >= self.screen_w:
                self.p1_score += 1
                if self.p1_score >= WINNING_SCORE:
                    self.game_over = True
                self._reset_ball()

    def render(self):
        self._render_keys()
        self._render_screen()

    def _render_keys(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        for i, deck in enumerate(self.decks):
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols

                if not self.game_active and not self.game_over:
                    if (c, r) == (mid_c, 0):
                        set_key(deck, key, (0, 80, 160), "PONG+")
                    elif (c, r) == (mid_c, last_r):
                        set_key(deck, key, (0, 80, 160), "START")
                    elif self.num_players == 2 and (c, r) == (0, 0):
                        set_key(deck, key, (40, 40, 80), f"P{i + 1}")
                    else:
                        set_key(deck, key, (20, 20, 30), "")
                elif self.game_over:
                    p1_won = self.p1_score >= WINNING_SCORE
                    if self.num_players == 2:
                        i_won = (i == 0 and p1_won) or (i == 1 and not p1_won)
                    else:
                        i_won = p1_won
                    if (c, r) == (mid_c, 0):
                        set_key(deck, key, (0, 200, 60) if i_won else (200, 0, 0), "WIN!" if i_won else "LOSE")
                    elif (c, r) == (mid_c, last_r):
                        set_key(deck, key, (0, 80, 160), "AGAIN")
                    elif (c, r) == (0, 0):
                        set_key(deck, key, (40, 40, 80), f"{self.p1_score}-{self.p2_score}")
                    else:
                        set_key(deck, key, (20, 20, 30), "")
                else:
                    if (c, r) == (mid_c, 0):
                        set_key(deck, key, (40, 40, 80), f"{self.p1_score}-{self.p2_score}")
                    elif (c, r) == (0, 0):
                        set_key(deck, key, (0, 100, 0), "SPD+")
                    elif (c, r) == (self.cols - 1, last_r):
                        set_key(deck, key, (100, 0, 0), "SPD-")
                    elif (c, r) == (self.cols - 1, 0):
                        set_key(deck, key, (40, 40, 80), f"x{self.ball_speed}")
                    else:
                        set_key(deck, key, (20, 20, 30), "")

    def _render_screen(self):
        w, h = self.screen_w, self.screen_h
        img = Image.new("RGB", (w, h), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        if not self.game_active and not self.game_over:
            try:
                font = ImageFont.load_default(size=24)
            except TypeError:
                font = ImageFont.load_default()
            draw.text((w // 2 - 50, h // 2 - 12), "PONG+", fill=(255, 255, 0), font=font)
            for deck in self.decks:
                set_screen(deck, img)
            return

        # Center line
        for y in range(0, h, 8):
            draw.rectangle([w // 2 - 1, y, w // 2 + 1, y + 4], fill=(40, 40, 40))

        # Left paddle (P1)
        draw.rectangle(
            [2, self.p1_y - PADDLE_H // 2, 2 + PADDLE_W, self.p1_y + PADDLE_H // 2],
            fill=(200, 200, 200),
        )

        # Right paddle (P2)
        draw.rectangle(
            [w - 2 - PADDLE_W, self.p2_y - PADDLE_H // 2, w - 2, self.p2_y + PADDLE_H // 2],
            fill=(200, 200, 200),
        )

        # Ball
        bx, by = int(self.ball_x), int(self.ball_y)
        draw.ellipse(
            [bx - BALL_SIZE // 2, by - BALL_SIZE // 2, bx + BALL_SIZE // 2, by + BALL_SIZE // 2],
            fill=(255, 255, 0),
        )

        # Score
        try:
            font = ImageFont.load_default(size=14)
        except TypeError:
            font = ImageFont.load_default()
        draw.text((w // 2 - 20, 2), f"{self.p1_score} - {self.p2_score}", fill=(100, 100, 100), font=font)

        if self.game_over:
            try:
                font_big = ImageFont.load_default(size=24)
            except TypeError:
                font_big = font
            winner = "P1 WINS!" if self.p1_score >= WINNING_SCORE else "P2 WINS!"
            draw.text((w // 2 - 40, h // 2 - 12), winner, fill=(255, 255, 0), font=font_big)

        for deck in self.decks:
            set_screen(deck, img)

    def game_loop(self):
        while self.running:
            with self.lock:
                self.tick()
                self.render()
            time.sleep(TICK_SPEED)


def main():
    streamdecks = DeviceManager().enumerate()
    plus_decks = [
        d for d in streamdecks
        if d.is_visual() and d.DIAL_COUNT and d.DIAL_COUNT > 0
    ]

    if not plus_decks:
        print("No Stream Deck + found (need dials + touchscreen).")
        sys.exit(1)

    for d in plus_decks:
        d.open()
        d.reset()
        d.set_brightness(80)

    decks = plus_decks[:2] if len(plus_decks) >= 2 else plus_decks[:1]

    if len(decks) == 2:
        print(f"2-PLAYER PONG+! Each deck = one paddle (use dial or touch).")
    else:
        print(f"Pong+ on {decks[0].deck_type()} (dial 1 = paddle, AI on right)")

    print(f"First to {WINNING_SCORE}! Ctrl+C to quit.")

    game = PongPlus(decks)
    game.render()

    for i, deck in enumerate(decks):
        def make_dial_cb(idx):
            def cb(d, dial, event, value):
                with game.lock:
                    game.handle_dial(dial, event, value, deck_index=idx)
            return cb

        def make_touch_cb(idx):
            def cb(d, evt_type, value):
                with game.lock:
                    game.handle_touch(evt_type, value, deck_index=idx)
            return cb

        def make_key_cb(idx):
            def cb(d, key, state):
                if not state:
                    return
                with game.lock:
                    if game.game_over or not game.game_active:
                        game.reset()
                        return
                    row = key // game.cols
                    col = key % game.cols
                    last_r = game.rows - 1
                    # SPD+ (top-left)
                    if col == 0 and row == 0:
                        game.ball_speed = min(8, game.ball_speed + 1)
                        # Scale current ball velocity
                        if game.ball_dx != 0:
                            sign_x = 1 if game.ball_dx > 0 else -1
                            game.ball_dx = sign_x * game.ball_speed
                    # SPD- (bottom-right)
                    elif col == game.cols - 1 and row == last_r:
                        game.ball_speed = max(1, game.ball_speed - 1)
                        if game.ball_dx != 0:
                            sign_x = 1 if game.ball_dx > 0 else -1
                            game.ball_dx = sign_x * game.ball_speed
            return cb

        deck.set_dial_callback(make_dial_cb(i))
        if deck.DECK_TOUCH:
            deck.set_touchscreen_callback(make_touch_cb(i))
        deck.set_key_callback(make_key_cb(i))

    game_thread = threading.Thread(target=game.game_loop, daemon=True)
    game_thread.start()

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
