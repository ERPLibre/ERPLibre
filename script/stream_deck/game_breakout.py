#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Breakout game with SD+ touchscreen support.

Standard deck: buttons control paddle, bricks on left, paddle on right.
SD+: game renders on touchscreen (800x100), dial moves paddle, buttons
for start/speed. Rotated 90°: bricks left, paddle right.
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
COLOR_GAMEOVER = (180, 0, 0)
COLOR_BULLET = (255, 120, 0)

BRICK_COLORS = [
    (220, 40, 40),
    (220, 140, 0),
    (0, 180, 0),
    (0, 100, 220),
    (160, 0, 160),
    (220, 180, 0),
    (0, 180, 180),
    (200, 80, 120),
]

TICK_SPEED = 0.08  # SD+ touchscreen tick (faster = smoother)
TICK_SPEED_BUTTONS = 0.6  # Button-grid tick (slower, coarser)


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 22 if len(text) <= 3 else 14 if len(text) <= 5 else 11
        try:
            font = ImageFont.load_default(size=fs)
        except TypeError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            ((w - tw) // 2 + 1, (h - th) // 2 + 1),
            text, fill=(0, 0, 0), font=font,
        )
        draw.text(
            ((w - tw) // 2, (h - th) // 2),
            text, fill=(255, 255, 255), font=font,
        )
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
        self.ball_speed = 3
        self.bullets = []  # list of (x, y) for SD+ or (col, row) for grid
        self.ammo = 5
        self.max_ammo = 5

        # Detect SD+ (has dials + touchscreen)
        self.is_sdplus = bool(
            getattr(deck, "DIAL_COUNT", 0) and deck.DIAL_COUNT > 0
        )

        if self.is_sdplus:
            self.screen_w = (
                deck.TOUCHSCREEN_PIXEL_WIDTH
                or deck.SCREEN_PIXEL_WIDTH or 800
            )
            self.screen_h = (
                deck.TOUCHSCREEN_PIXEL_HEIGHT
                or deck.SCREEN_PIXEL_HEIGHT or 100
            )
            # Touchscreen game field — continuous coordinates
            self.brick_zone_w = self.screen_w * 2 // 5
            self.brick_cols = 12
            self.brick_rows = 8
            self.brick_w = self.brick_zone_w // self.brick_cols
            self.brick_h = self.screen_h // self.brick_rows
            self.paddle_x = self.screen_w - 15
            self.paddle_h = 25
            self.paddle_y = self.screen_h // 2
            self.ball_x = float(self.screen_w // 2)
            self.ball_y = float(self.screen_h // 2)
            self.ball_r = 4
            self.ball_dx = -3.0
            self.ball_dy = 2.0
            self.bricks = set()
        else:
            # Button grid mode
            self.brick_cols_grid = max(1, self.cols - 2)
            self.bricks = set()
            self.paddle_row = rows // 2
            self.ball_col = 0
            self.ball_row = 0
            self.ball_dx = 1
            self.ball_dy = 1

    def reset(self):
        self.score = 0
        self.game_over = False
        self.won = False
        self.game_active = True
        self.bullets = []
        self.ammo = self.max_ammo

        if self.is_sdplus:
            self.bricks = set()
            for c in range(self.brick_cols):
                for r in range(self.brick_rows):
                    self.bricks.add((c, r))
            self.paddle_y = self.screen_h // 2
            self.ball_x = float(self.screen_w * 2 // 3)
            self.ball_y = float(self.screen_h // 2)
            s = self.ball_speed
            self.ball_dx = float(-s)
            self.ball_dy = float(random.choice([-1, 1]) * (s - 1))
        else:
            self.bricks = set()
            for c in range(self.brick_cols_grid):
                for r in range(self.rows):
                    self.bricks.add((c, r))
            self.paddle_row = self.rows // 2
            self.ball_col = self.cols - 2
            self.ball_row = self.rows // 2
            self.ball_dx = -1
            self.ball_dy = random.choice([-1, 1])

    def _fire(self):
        """Fire a bullet from the paddle."""
        if self.ammo <= 0 or not self.game_active or self.game_over:
            return
        self.ammo -= 1
        if self.is_sdplus:
            self.bullets.append([float(self.paddle_x - 5),
                                 float(self.paddle_y)])
        else:
            self.bullets.append([self.cols - 2, self.paddle_row])

    def _tick_bullets_sdplus(self):
        """Move bullets left, check brick collision (SD+)."""
        bullet_speed = 6.0
        alive = []
        for bx, by in self.bullets:
            bx -= bullet_speed
            if bx < 0:
                continue
            # Check brick hit
            if bx < self.brick_zone_w:
                bc = int(bx / self.brick_w)
                br = int(by / self.brick_h)
                bc = max(0, min(bc, self.brick_cols - 1))
                br = max(0, min(br, self.brick_rows - 1))
                if (bc, br) in self.bricks:
                    self.bricks.discard((bc, br))
                    self.score += 1
                    if not self.bricks:
                        self.won = True
                        self.game_over = True
                        if self.score > self.high_score:
                            self.high_score = self.score
                    continue  # bullet consumed
            alive.append([bx, by])
        self.bullets = alive

    def _tick_bullets_grid(self):
        """Move bullets left, check brick collision (button grid)."""
        alive = []
        for bc, br in self.bullets:
            bc -= 1
            if bc < 0:
                continue
            if (bc, br) in self.bricks:
                self.bricks.discard((bc, br))
                self.score += 1
                if not self.bricks:
                    self.won = True
                    self.game_over = True
                    if self.score > self.high_score:
                        self.high_score = self.score
                continue  # bullet consumed
            alive.append([bc, br])
        self.bullets = alive

    # ── TOUCHSCREEN (SD+) TICK ────────────────────

    def tick_sdplus(self):
        if not self.game_active or self.game_over:
            return
        # Tick bullets
        self._tick_bullets_sdplus()
        if self.game_over:
            return

        nx = self.ball_x + self.ball_dx
        ny = self.ball_y + self.ball_dy

        # Top/bottom walls
        if ny - self.ball_r < 0:
            ny = float(self.ball_r)
            self.ball_dy = abs(self.ball_dy)
        elif ny + self.ball_r >= self.screen_h:
            ny = float(self.screen_h - self.ball_r - 1)
            self.ball_dy = -abs(self.ball_dy)

        # Left wall
        if nx - self.ball_r < 0:
            nx = float(self.ball_r)
            self.ball_dx = abs(self.ball_dx)

        # Paddle (right side)
        if nx + self.ball_r >= self.paddle_x:
            half_p = self.paddle_h // 2
            if abs(ny - self.paddle_y) <= half_p + self.ball_r:
                nx = float(self.paddle_x - self.ball_r - 1)
                self.ball_dx = -abs(self.ball_dx)
                offset = (ny - self.paddle_y) / half_p
                self.ball_dy = offset * self.ball_speed
                # Reload ammo on paddle hit
                self.ammo = min(self.max_ammo, self.ammo + 1)
            else:
                self.game_over = True
                if self.score > self.high_score:
                    self.high_score = self.score
                return

        # Brick collision
        if nx < self.brick_zone_w and self.ball_dx < 0:
            bc = int(nx / self.brick_w)
            br = int(ny / self.brick_h)
            bc = max(0, min(bc, self.brick_cols - 1))
            br = max(0, min(br, self.brick_rows - 1))
            if (bc, br) in self.bricks:
                self.bricks.discard((bc, br))
                self.score += 1
                self.ball_dx = abs(self.ball_dx)
                if not self.bricks:
                    self.won = True
                    self.game_over = True
                    if self.score > self.high_score:
                        self.high_score = self.score
                    return

        self.ball_x = nx
        self.ball_y = ny

    # ── BUTTON GRID TICK ──────────────────────────

    def tick_buttons(self):
        if not self.game_active or self.game_over:
            return
        # Tick bullets
        self._tick_bullets_grid()
        if self.game_over:
            return

        new_col = self.ball_col + self.ball_dx
        new_row = self.ball_row + self.ball_dy

        if new_row < 0:
            new_row = 0
            self.ball_dy = 1
        elif new_row >= self.rows:
            new_row = self.rows - 1
            self.ball_dy = -1

        if new_col < 0:
            new_col = 0
            self.ball_dx = 1

        last_col = self.cols - 1
        if new_col >= last_col:
            if abs(new_row - self.paddle_row) <= 1:
                new_col = last_col - 1
                self.ball_dx = -1
                if new_row < self.paddle_row:
                    self.ball_dy = -1
                elif new_row > self.paddle_row:
                    self.ball_dy = 1
                # Reload ammo on paddle hit
                self.ammo = min(self.max_ammo, self.ammo + 1)
            else:
                self.game_over = True
                if self.score > self.high_score:
                    self.high_score = self.score
                return

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

    # ── INPUT ─────────────────────────────────────

    def handle_key(self, key):
        if self.game_over or not self.game_active:
            self.reset()
            self.render()
            return

        if self.is_sdplus:
            col = key % self.cols
            if col == 0:
                self.ball_speed = max(1, self.ball_speed - 1)
            elif col == self.cols - 1:
                self.ball_speed = min(8, self.ball_speed + 1)
            elif col == 2:
                self._fire()
        else:
            col = key % self.cols
            row = key // self.cols
            last_col = self.cols - 1
            if col == last_col:
                # Pressing paddle position = fire
                if row == self.paddle_row:
                    self._fire()
                else:
                    self.paddle_row = row
            elif row < self.paddle_row:
                self.paddle_row = max(0, self.paddle_row - 1)
            elif row > self.paddle_row:
                self.paddle_row = min(self.rows - 1, self.paddle_row + 1)

    def handle_dial(self, dial, event, value):
        if not self.is_sdplus:
            return
        if event == DialEventType.PUSH and value:
            if self.game_over or not self.game_active:
                self.reset()
                self.render()
            else:
                self._fire()
            return
        if event == DialEventType.TURN:
            if not self.game_active or self.game_over:
                return
            half_p = self.paddle_h // 2
            self.paddle_y = max(
                half_p,
                min(self.screen_h - half_p, self.paddle_y + value * 4),
            )

    # ── RENDER ────────────────────────────────────

    def render(self):
        if self.is_sdplus:
            self._render_screen()
            self._render_keys_sdplus()
        else:
            self._render_buttons()

    def _render_screen(self):
        """Render game on SD+ touchscreen."""
        sw, sh = self.screen_w, self.screen_h
        img = Image.new("RGB", (sw, sh), (10, 10, 20))
        draw = ImageDraw.Draw(img)

        if not self.game_active:
            # Title screen
            try:
                font = ImageFont.load_default(size=20)
                sfont = ImageFont.load_default(size=14)
            except TypeError:
                font = sfont = ImageFont.load_default()
            draw.text((sw // 2 - 60, 10), "BREAKOUT", fill=(255, 255, 255),
                      font=font)
            draw.text((sw // 2 - 70, 50), "Press dial to start",
                      fill=(150, 150, 200), font=sfont)
            if self.high_score:
                draw.text((sw // 2 - 40, 75), f"HI: {self.high_score}",
                          fill=(200, 200, 100), font=sfont)
            set_screen(self.deck, img)
            return

        if self.game_over:
            try:
                font = ImageFont.load_default(size=22)
                sfont = ImageFont.load_default(size=14)
            except TypeError:
                font = sfont = ImageFont.load_default()
            if self.won:
                draw.text((sw // 2 - 30, 15), "WIN!", fill=(0, 255, 100),
                          font=font)
            else:
                draw.text((sw // 2 - 45, 15), "GAME OVER",
                          fill=(255, 60, 60), font=font)
            draw.text((sw // 2 - 40, 55), f"Score: {self.score}",
                      fill=(255, 255, 255), font=sfont)
            draw.text((sw // 2 - 50, 75), "Press dial to retry",
                      fill=(150, 150, 200), font=sfont)
            set_screen(self.deck, img)
            return

        # Draw bricks
        for (bc, br) in self.bricks:
            x1 = bc * self.brick_w + 1
            y1 = br * self.brick_h + 1
            x2 = x1 + self.brick_w - 2
            y2 = y1 + self.brick_h - 2
            color = BRICK_COLORS[br % len(BRICK_COLORS)]
            draw.rectangle([x1, y1, x2, y2], fill=color)

        # Draw paddle
        half_p = self.paddle_h // 2
        px = self.paddle_x
        draw.rectangle(
            [px, self.paddle_y - half_p, px + 10,
             self.paddle_y + half_p],
            fill=COLOR_PADDLE,
        )

        # Draw bullets
        for bx, by in self.bullets:
            ix, iy = int(bx), int(by)
            draw.rectangle([ix - 3, iy - 1, ix + 3, iy + 1],
                           fill=COLOR_BULLET)

        # Draw ball
        bx, by = int(self.ball_x), int(self.ball_y)
        r = self.ball_r
        draw.ellipse([bx - r, by - r, bx + r, by + r], fill=COLOR_BALL)

        # Ammo indicator (small dots near paddle)
        for a in range(self.ammo):
            ay = self.paddle_y - self.paddle_h // 2 - 5 - a * 6
            draw.ellipse([self.paddle_x + 2, ay - 2,
                          self.paddle_x + 6, ay + 2],
                         fill=COLOR_BULLET)

        # Score
        try:
            sfont = ImageFont.load_default(size=12)
        except TypeError:
            sfont = ImageFont.load_default()
        draw.text((sw - 45, 2), f"{self.score}", fill=(200, 200, 200),
                  font=sfont)

        set_screen(self.deck, img)

    def _render_keys_sdplus(self):
        """Render SD+ buttons (speed, fire, score info)."""
        for key in range(self.total_keys):
            c = key % self.cols
            if c == 0:
                set_key(self.deck, key, (60, 60, 100), "SPD-")
            elif c == self.cols - 1:
                set_key(self.deck, key, (60, 60, 100), "SPD+")
            elif c == 1:
                set_key(self.deck, key, COLOR_SCORE,
                        f"S:{self.score}")
            elif c == 2:
                # Fire button with ammo count
                if self.ammo > 0:
                    set_key(self.deck, key, COLOR_BULLET,
                            f"F:{self.ammo}")
                else:
                    set_key(self.deck, key, (40, 20, 0), "F:0")
            elif c == 3:
                set_key(self.deck, key, (40, 40, 60),
                        f"v{self.ball_speed}")
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_buttons(self):
        """Render on standard button grid (non-SD+)."""
        mid_c = self.cols // 2
        mid_r = self.rows // 2
        last_c = self.cols - 1
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_TITLE, "BREAK")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.high_score:
                    set_key(self.deck, key, COLOR_SCORE,
                            f"HI:{self.high_score}")
                elif c < self.brick_cols_grid:
                    set_key(
                        self.deck, key,
                        BRICK_COLORS[c % len(BRICK_COLORS)], "",
                    )
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        if self.game_over:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    color = COLOR_WIN if self.won else COLOR_GAMEOVER
                    text = "WIN!" if self.won else "OVER"
                    set_key(self.deck, key, color, text)
                elif (c, r) == (mid_c, mid_r):
                    set_key(self.deck, key, COLOR_SCORE,
                            f"S:{self.score}")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols
            bullet_here = any(
                int(bc) == c and int(br) == r for bc, br in self.bullets
            )
            if c == self.ball_col and r == self.ball_row:
                set_key(self.deck, key, COLOR_BALL, "")
            elif bullet_here:
                set_key(self.deck, key, COLOR_BULLET, ">")
            elif c == last_c and r == self.paddle_row:
                label = f"||{self.ammo}" if self.ammo > 0 else "||"
                set_key(self.deck, key, COLOR_PADDLE, label)
            elif (c, r) in self.bricks:
                set_key(
                    self.deck, key,
                    BRICK_COLORS[c % len(BRICK_COLORS)], "",
                )
            elif c == last_c and r == 0:
                set_key(self.deck, key, COLOR_SCORE, str(self.score))
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    # ── GAME LOOP ─────────────────────────────────

    def game_loop(self):
        tick_fn = self.tick_sdplus if self.is_sdplus else self.tick_buttons
        speed = TICK_SPEED if self.is_sdplus else TICK_SPEED_BUTTONS
        while self.running and self.deck.is_open():
            with self.lock:
                tick_fn()
                self.render()
            time.sleep(speed)


def main():
    streamdecks = DeviceManager().enumerate()
    if not streamdecks:
        print("No Stream Deck found.")
        sys.exit(1)

    deck = None
    # Prefer SD+ if available
    for d in streamdecks:
        if d.is_visual():
            if getattr(d, "DIAL_COUNT", 0) and d.DIAL_COUNT > 0:
                deck = d
                break
    if deck is None:
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
    is_sdplus = bool(
        getattr(deck, "DIAL_COUNT", 0) and deck.DIAL_COUNT > 0
    )
    print(f"Breakout on {deck.deck_type()} ({cols}x{rows})")
    if is_sdplus:
        print("SD+ mode: turn dial to move paddle, press dial to start")
        print("Buttons: SPD-/SPD+ to change ball speed")
    else:
        print("Right column = paddle. Press to move! Ctrl+C to quit.")

    game = Breakout(deck)
    game.render()

    def key_cb(d, k, s):
        if not s:
            return
        with game.lock:
            game.handle_key(k)

    deck.set_key_callback(key_cb)

    if is_sdplus:
        def dial_cb(d, dial, evt, val):
            with game.lock:
                game.handle_dial(dial, evt, val)
        deck.set_dial_callback(dial_cb)

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
