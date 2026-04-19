#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Pong — 1P vs AI or 2P with SD+ touchscreen support.

SD+ (default if connected): game on touchscreen, dials move paddles,
touch to position paddle, SPD+/SPD- buttons.
Standard deck: button grid, press to move paddle.
2 decks: each player controls their paddle on their own deck.
"""

import io
import random
import sys
import threading
import time

try:
    from PIL import Image, ImageDraw, ImageFont
    from StreamDeck.DeviceManager import DeviceManager
    from StreamDeck.Devices.StreamDeck import DialEventType
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

WINNING_SCORE = 5
TICK_SPEED_BUTTONS = 0.4
TICK_SPEED_SCREEN = 0.03
PADDLE_H = 30
PADDLE_W = 6
BALL_SIZE = 8
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


def set_screen(deck, img):
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="JPEG")
    img_bytes = img_bytes.getvalue()
    try:
        with deck:
            w = (deck.TOUCHSCREEN_PIXEL_WIDTH
                 or deck.SCREEN_PIXEL_WIDTH or 800)
            h = (deck.TOUCHSCREEN_PIXEL_HEIGHT
                 or deck.SCREEN_PIXEL_HEIGHT or 100)
            if deck.DECK_TOUCH:
                deck.set_touchscreen_image(img_bytes, 0, 0, w, h)
            else:
                deck.set_screen_image(img_bytes)
    except (TransportError, AttributeError):
        pass


class Pong:
    def __init__(self, decks, is_sdplus=False):
        self.decks = decks
        self.num_players = len(decks)
        self.deck = decks[0]
        rows, cols = self.deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.running = True
        self.is_sdplus = is_sdplus
        self.game_active = False
        self.game_over = False
        self.p1_score = 0
        self.p2_score = 0
        self.ball_speed = 3

        if self.is_sdplus:
            self.screen_w = (
                self.deck.TOUCHSCREEN_PIXEL_WIDTH
                or self.deck.SCREEN_PIXEL_WIDTH or 800
            )
            self.screen_h = (
                self.deck.TOUCHSCREEN_PIXEL_HEIGHT
                or self.deck.SCREEN_PIXEL_HEIGHT or 100
            )
            self.p1_y = self.screen_h // 2
            self.p2_y = self.screen_h // 2
            self.ball_x = self.screen_w // 2
            self.ball_y = self.screen_h // 2
            self.ball_dx = 3
            self.ball_dy = 2
        else:
            self.p1_row = rows // 2
            self.p2_row = rows // 2
            self.ball_col = cols // 2
            self.ball_row = rows // 2
            self.ball_dx = 1
            self.ball_dy = random.choice([-1, 1])

    def reset(self):
        self.p1_score = 0
        self.p2_score = 0
        self.game_over = False
        self.game_active = True
        if self.is_sdplus:
            self.p1_y = self.screen_h // 2
            self.p2_y = self.screen_h // 2
        else:
            self.p1_row = self.rows // 2
            self.p2_row = self.rows // 2
        self._reset_ball()

    def _reset_ball(self):
        if self.is_sdplus:
            self.ball_x = self.screen_w // 2
            self.ball_y = self.screen_h // 2
            s = self.ball_speed
            self.ball_dx = random.choice([-s, s])
            self.ball_dy = random.choice([-(s - 1) or -1, (s - 1) or 1])
        else:
            self.ball_col = self.cols // 2
            self.ball_row = self.rows // 2
            self.ball_dx = random.choice([-1, 1])
            self.ball_dy = random.choice([-1, 1])

    # ── SD+ TICK ──────────────────────────────────

    def _tick_sdplus(self):
        if not self.game_active or self.game_over:
            return
        # AI
        if self.num_players == 1:
            if self.ball_y < self.p2_y - 3:
                self.p2_y = max(PADDLE_H // 2, self.p2_y - 2)
            elif self.ball_y > self.p2_y + 3:
                self.p2_y = min(self.screen_h - PADDLE_H // 2, self.p2_y + 2)

        self.ball_x += self.ball_dx
        self.ball_y += self.ball_dy

        # Top/bottom
        if self.ball_y <= BALL_SIZE // 2:
            self.ball_y = BALL_SIZE // 2
            self.ball_dy = abs(self.ball_dy)
        elif self.ball_y >= self.screen_h - BALL_SIZE // 2:
            self.ball_y = self.screen_h - BALL_SIZE // 2
            self.ball_dy = -abs(self.ball_dy)

        # Left paddle (P1)
        if self.ball_x <= PADDLE_W + BALL_SIZE // 2:
            if abs(self.ball_y - self.p1_y) <= PADDLE_H // 2:
                self.ball_x = PADDLE_W + BALL_SIZE // 2
                self.ball_dx = abs(self.ball_dx)
                offset = (self.ball_y - self.p1_y) / (PADDLE_H // 2)
                self.ball_dy = int(offset * 4)
            elif self.ball_x <= 0:
                self.p2_score += 1
                if self.p2_score >= WINNING_SCORE:
                    self.game_over = True
                self._reset_ball()

        # Right paddle (P2)
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

    # ── BUTTON TICK ───────────────────────────────

    def _tick_buttons(self):
        if not self.game_active or self.game_over:
            return
        # AI
        if self.num_players == 1:
            if self.ball_row < self.p2_row:
                self.p2_row = max(0, self.p2_row - 1)
            elif self.ball_row > self.p2_row:
                self.p2_row = min(self.rows - 1, self.p2_row + 1)

        nc = self.ball_col + self.ball_dx
        nr = self.ball_row + self.ball_dy

        if nr < 0:
            nr = 0
            self.ball_dy = 1
        elif nr >= self.rows:
            nr = self.rows - 1
            self.ball_dy = -1

        last_col = self.cols - 1
        if nc <= 0:
            if abs(nr - self.p1_row) <= 0:
                nc = 1
                self.ball_dx = 1
            else:
                self.p2_score += 1
                if self.p2_score >= WINNING_SCORE:
                    self.game_over = True
                self._reset_ball()
                return

        if nc >= last_col:
            if abs(nr - self.p2_row) <= 0:
                nc = last_col - 1
                self.ball_dx = -1
            else:
                self.p1_score += 1
                if self.p1_score >= WINNING_SCORE:
                    self.game_over = True
                self._reset_ball()
                return

        self.ball_col = nc
        self.ball_row = nr

    # ── INPUT ─────────────────────────────────────

    def handle_key(self, key, deck_index=0):
        if self.game_over or not self.game_active:
            self.reset()
            return

        if self.is_sdplus:
            col = key % self.cols
            row = key // self.cols
            last_r = self.rows - 1
            if col == 0 and row == 0:
                self.ball_speed = min(8, self.ball_speed + 1)
                if self.ball_dx != 0:
                    sign_x = 1 if self.ball_dx > 0 else -1
                    self.ball_dx = sign_x * self.ball_speed
            elif col == self.cols - 1 and row == last_r:
                self.ball_speed = max(1, self.ball_speed - 1)
                if self.ball_dx != 0:
                    sign_x = 1 if self.ball_dx > 0 else -1
                    self.ball_dx = sign_x * self.ball_speed
        else:
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

    def handle_dial(self, dial, event, value, deck_index=0):
        if not self.is_sdplus:
            return
        if event == DialEventType.PUSH and value:
            if self.game_over or not self.game_active:
                self.reset()
            return
        if event == DialEventType.TURN:
            if not self.game_active or self.game_over:
                return
            half = PADDLE_H // 2
            if self.num_players == 2:
                if deck_index == 0:
                    self.p1_y = max(half, min(
                        self.screen_h - half,
                        self.p1_y + value * PADDLE_SPEED))
                else:
                    self.p2_y = max(half, min(
                        self.screen_h - half,
                        self.p2_y + value * PADDLE_SPEED))
            else:
                if dial <= 1:
                    self.p1_y = max(half, min(
                        self.screen_h - half,
                        self.p1_y + value * PADDLE_SPEED))

    def handle_touch(self, evt_type, value, deck_index=0):
        if not self.is_sdplus or not self.game_active:
            return
        y = value.get("y", self.screen_h // 2)
        half = PADDLE_H // 2
        y = max(half, min(self.screen_h - half, y))
        if self.num_players == 2:
            if deck_index == 0:
                self.p1_y = y
            else:
                self.p2_y = y
        else:
            self.p1_y = y

    # ── RENDER ────────────────────────────────────

    def render(self):
        if self.is_sdplus:
            self._render_screen()
            self._render_keys_sdplus()
        else:
            self._render_buttons()

    def _render_screen(self):
        w, h = self.screen_w, self.screen_h
        img = Image.new("RGB", (w, h), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        if not self.game_active and not self.game_over:
            try:
                font = ImageFont.load_default(size=24)
            except TypeError:
                font = ImageFont.load_default()
            draw.text((w // 2 - 40, h // 2 - 12), "PONG",
                      fill=COLOR_BALL, font=font)
            for deck in self.decks:
                set_screen(deck, img)
            return

        # Center line
        for y in range(0, h, 8):
            draw.rectangle([w // 2 - 1, y, w // 2 + 1, y + 4],
                           fill=(40, 40, 40))

        # Paddles
        draw.rectangle(
            [2, self.p1_y - PADDLE_H // 2,
             2 + PADDLE_W, self.p1_y + PADDLE_H // 2],
            fill=COLOR_PADDLE,
        )
        draw.rectangle(
            [w - 2 - PADDLE_W, self.p2_y - PADDLE_H // 2,
             w - 2, self.p2_y + PADDLE_H // 2],
            fill=COLOR_PADDLE,
        )

        # Ball
        bx, by = int(self.ball_x), int(self.ball_y)
        draw.ellipse(
            [bx - BALL_SIZE // 2, by - BALL_SIZE // 2,
             bx + BALL_SIZE // 2, by + BALL_SIZE // 2],
            fill=COLOR_BALL,
        )

        # Score
        try:
            font = ImageFont.load_default(size=14)
        except TypeError:
            font = ImageFont.load_default()
        draw.text((w // 2 - 20, 2),
                  f"{self.p1_score} - {self.p2_score}",
                  fill=(100, 100, 100), font=font)

        if self.game_over:
            try:
                font_big = ImageFont.load_default(size=24)
            except TypeError:
                font_big = font
            winner = "P1 WINS!" if self.p1_score >= WINNING_SCORE else "P2 WINS!"
            draw.text((w // 2 - 40, h // 2 - 12), winner,
                      fill=COLOR_BALL, font=font_big)

        for deck in self.decks:
            set_screen(deck, img)

    def _render_keys_sdplus(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        for i, deck in enumerate(self.decks):
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if not self.game_active and not self.game_over:
                    if (c, r) == (mid_c, 0):
                        set_key(deck, key, COLOR_TITLE, "PONG")
                    elif (c, r) == (mid_c, last_r):
                        set_key(deck, key, COLOR_TITLE, "START")
                    elif self.num_players == 2 and (c, r) == (0, 0):
                        set_key(deck, key, COLOR_SCORE, f"P{i + 1}")
                    else:
                        set_key(deck, key, COLOR_EMPTY, "")
                elif self.game_over:
                    p1_won = self.p1_score >= WINNING_SCORE
                    if self.num_players == 2:
                        i_won = (i == 0 and p1_won) or (i == 1 and not p1_won)
                    else:
                        i_won = p1_won
                    if (c, r) == (mid_c, 0):
                        set_key(deck, key,
                                COLOR_WIN if i_won else COLOR_LOSE,
                                "WIN!" if i_won else "LOSE")
                    elif (c, r) == (mid_c, last_r):
                        set_key(deck, key, COLOR_TITLE, "AGAIN")
                    elif (c, r) == (0, 0):
                        set_key(deck, key, COLOR_SCORE,
                                f"{self.p1_score}-{self.p2_score}")
                    else:
                        set_key(deck, key, COLOR_EMPTY, "")
                else:
                    if (c, r) == (mid_c, 0):
                        set_key(deck, key, COLOR_SCORE,
                                f"{self.p1_score}-{self.p2_score}")
                    elif (c, r) == (0, 0):
                        set_key(deck, key, (0, 100, 0), "SPD+")
                    elif (c, r) == (self.cols - 1, last_r):
                        set_key(deck, key, (100, 0, 0), "SPD-")
                    elif (c, r) == (self.cols - 1, 0):
                        set_key(deck, key, COLOR_SCORE,
                                f"x{self.ball_speed}")
                    else:
                        set_key(deck, key, COLOR_EMPTY, "")

    def _render_buttons(self):
        mid_c = self.cols // 2
        last_c = self.cols - 1
        last_r = self.rows - 1

        for i, deck in enumerate(self.decks):
            if not self.game_active:
                for key in range(self.total_keys):
                    r = key // self.cols
                    c = key % self.cols
                    if (c, r) == (mid_c, 0):
                        set_key(deck, key, COLOR_TITLE, "PONG")
                    elif (c, r) == (mid_c, last_r):
                        set_key(deck, key, COLOR_TITLE, "START")
                    elif self.num_players == 2 and (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                        set_key(deck, key, COLOR_PADDLE, f"P{i + 1}")
                    else:
                        set_key(deck, key, COLOR_EMPTY, "")
                continue

            if self.game_over:
                p1_won = self.p1_score >= WINNING_SCORE
                if self.num_players == 2:
                    i_won = (i == 0 and p1_won) or (i == 1 and not p1_won)
                else:
                    i_won = p1_won
                for key in range(self.total_keys):
                    r = key // self.cols
                    c = key % self.cols
                    if (c, r) == (mid_c, 0):
                        set_key(deck, key,
                                COLOR_WIN if i_won else COLOR_LOSE,
                                "WIN!" if i_won else "LOSE")
                    elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                        set_key(deck, key, COLOR_SCORE,
                                f"{self.p1_score}-{self.p2_score}")
                    elif (c, r) == (mid_c, last_r):
                        set_key(deck, key, COLOR_TITLE, "AGAIN")
                    else:
                        set_key(deck, key, COLOR_EMPTY, "")
                continue

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
                    set_key(deck, key, COLOR_SCORE,
                            f"{self.p1_score}-{self.p2_score}")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")

    # ── GAME LOOP ─────────────────────────────────

    def game_loop(self):
        tick_fn = self._tick_sdplus if self.is_sdplus else self._tick_buttons
        speed = TICK_SPEED_SCREEN if self.is_sdplus else TICK_SPEED_BUTTONS
        while self.running:
            with self.lock:
                tick_fn()
                self.render()
            time.sleep(speed)


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

    # Prefer SD+ decks
    plus_decks = [
        d for d in visual
        if getattr(d, "DIAL_COUNT", 0) and d.DIAL_COUNT > 0
    ]
    is_sdplus = len(plus_decks) > 0

    if is_sdplus:
        decks = plus_decks[:2] if len(plus_decks) >= 2 else plus_decks[:1]
    else:
        decks = visual[:2] if len(visual) >= 2 else visual[:1]

    if len(decks) == 2:
        if is_sdplus:
            print("2-PLAYER PONG! Dials + touchscreen.")
        else:
            print("2-PLAYER PONG! Each deck = one paddle.")
    else:
        mode = "SD+ (dial + touchscreen)" if is_sdplus else decks[0].deck_type()
        print(f"Pong vs AI on {mode}")

    print(f"First to {WINNING_SCORE}! Ctrl+C to quit.")

    game = Pong(decks, is_sdplus=is_sdplus)
    game.render()

    for i, deck in enumerate(decks):
        def make_key_cb(idx):
            def cb(d, k, s):
                if not s:
                    return
                with game.lock:
                    game.handle_key(k, deck_index=idx)
            return cb
        deck.set_key_callback(make_key_cb(i))

        if is_sdplus:
            def make_dial_cb(idx):
                def cb(d, dial, evt, val):
                    with game.lock:
                        game.handle_dial(dial, evt, val, deck_index=idx)
                return cb
            deck.set_dial_callback(make_dial_cb(i))

            if getattr(deck, "DECK_TOUCH", False):
                def make_touch_cb(idx):
                    def cb(d, evt_type, value):
                        with game.lock:
                            game.handle_touch(evt_type, value,
                                              deck_index=idx)
                    return cb
                deck.set_touchscreen_callback(make_touch_cb(i))

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
