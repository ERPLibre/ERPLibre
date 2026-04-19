#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Breakout game with SD+ touchscreen support.

Standard deck: buttons control paddle, bricks on left, paddle on right.
SD+: game renders on touchscreen (800x100), dial moves paddle, buttons
for start/speed. Items drop from broken bricks (50% chance).
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

GAME_META = {
    "name": "Breakout",
    "category": "arcade",
    "multiplayer": False,
    "sdplus": True,
    "description": "Break bricks! SD+ touchscreen, items, multi-ball, ammo.",
    "icon": "breakout"
}

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

# Item types and their colors
ITEM_LIFE = "life"       # +1 vie
ITEM_MULTIBALL = "multi"  # +1 balle
ITEM_SLOW = "slow"       # ralentir balles
ITEM_DESTROY = "destroy"  # détruire bloc au hasard
ITEM_AMMO = "ammo"       # +3 munitions

ITEM_COLORS = {
    ITEM_LIFE: (255, 80, 180),     # pink
    ITEM_MULTIBALL: (0, 255, 255),  # cyan
    ITEM_SLOW: (100, 200, 255),    # light blue
    ITEM_DESTROY: (255, 60, 60),   # red
    ITEM_AMMO: (255, 180, 0),      # orange
}
ITEM_LABELS = {
    ITEM_LIFE: "+V",
    ITEM_MULTIBALL: "+B",
    ITEM_SLOW: "SL",
    ITEM_DESTROY: "X!",
    ITEM_AMMO: "+A",
}
ITEM_TYPES = [ITEM_LIFE, ITEM_MULTIBALL, ITEM_SLOW, ITEM_DESTROY, ITEM_AMMO]

TICK_SPEED = 0.08
TICK_SPEED_BUTTONS = 0.6


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
        self.ball_speed = 5
        self.ball_waiting = True
        self.bullets = []
        self.ammo = 5
        self.max_ammo = 10
        self.lives = 1
        self.items = []  # falling items: [x, y, type] or [col, row, type]

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
            self.brick_zone_w = self.screen_w * 3 // 4
            self.brick_cols = 30
            self.brick_rows = 4
            self.brick_w = self.brick_zone_w // self.brick_cols
            self.brick_h = self.screen_h // self.brick_rows
            self.paddle_x = self.screen_w - 15
            self.paddle_h = 25
            self.paddle_y = self.screen_h // 2
            self.ball_r = 4
            self.bricks = set()
            # Multiple balls: list of [x, y, dx, dy]
            self.balls = []
        else:
            self.brick_cols_grid = max(1, self.cols - 2)
            self.bricks = set()
            self.paddle_row = rows // 2
            # Multiple balls: list of [col, row, dx, dy]
            self.balls = []

    def reset(self):
        self.score = 0
        self.game_over = False
        self.won = False
        self.game_active = True
        self.ball_waiting = True
        self.ball_speed = 5
        self.bullets = []
        self.ammo = self.max_ammo
        self.lives = 1
        self.items = []

        if self.is_sdplus:
            self.bricks = set()
            for c in range(self.brick_cols):
                for r in range(self.brick_rows):
                    self.bricks.add((c, r))
            self.paddle_y = self.screen_h // 2
            self.balls = [[
                float(self.paddle_x - self.ball_r - 2),
                float(self.paddle_y), 0.0, 0.0,
            ]]
        else:
            self.bricks = set()
            for c in range(self.brick_cols_grid):
                for r in range(self.rows):
                    self.bricks.add((c, r))
            self.paddle_row = self.rows // 2
            self.balls = [[self.cols - 2, self.paddle_row, 0, 0]]

    def _launch_ball(self):
        if not self.ball_waiting:
            return
        self.ball_waiting = False
        if self.is_sdplus:
            s = self.ball_speed
            for b in self.balls:
                b[2] = float(-s)
                b[3] = float(random.choice([-1, 1]) * (s * 0.6))
        else:
            for b in self.balls:
                b[2] = -1
                b[3] = random.choice([-1, 1])

    def _fire(self):
        if self.ammo <= 0 or not self.game_active or self.game_over:
            return
        self.ammo -= 1
        if self.is_sdplus:
            self.bullets.append([float(self.paddle_x - 5),
                                 float(self.paddle_y)])
        else:
            self.bullets.append([self.cols - 2, self.paddle_row])

    # ── ITEMS ─────────────────────────────────────

    def _maybe_spawn_item(self, x, y):
        """50% chance to spawn an item at brick position."""
        if random.random() < 0.5:
            item_type = random.choice(ITEM_TYPES)
            self.items.append([float(x), float(y), item_type])

    def _maybe_spawn_item_grid(self, col, row):
        """50% chance to spawn item (button grid)."""
        if random.random() < 0.5:
            item_type = random.choice(ITEM_TYPES)
            self.items.append([col, row, item_type])

    def _apply_item(self, item_type):
        """Apply collected item effect."""
        if item_type == ITEM_LIFE:
            self.lives += 1
        elif item_type == ITEM_MULTIBALL:
            self._add_extra_ball()
        elif item_type == ITEM_SLOW:
            self.ball_speed = max(2, self.ball_speed - 3)
            # Slow all current balls
            for b in self.balls:
                if b[2] != 0:
                    sign_x = -1 if b[2] < 0 else 1
                    b[2] = float(sign_x * self.ball_speed)
        elif item_type == ITEM_DESTROY:
            if self.bricks:
                brick = random.choice(list(self.bricks))
                self.bricks.discard(brick)
                self.score += 1
                if not self.bricks:
                    self._check_win()
        elif item_type == ITEM_AMMO:
            self.ammo = min(self.max_ammo, self.ammo + 3)

    def _add_extra_ball(self):
        """Add a new ball from paddle position."""
        if self.is_sdplus:
            s = self.ball_speed
            self.balls.append([
                float(self.paddle_x - self.ball_r - 2),
                float(self.paddle_y),
                float(-s),
                float(random.choice([-1, 1]) * (s * 0.6)),
            ])
        else:
            self.balls.append([
                self.cols - 2, self.paddle_row,
                -1, random.choice([-1, 1]),
            ])

    def _check_win(self):
        if not self.bricks:
            self.won = True
            self.game_over = True
            if self.score > self.high_score:
                self.high_score = self.score

    def _lose_ball(self):
        """Called when all balls are lost."""
        self.lives -= 1
        if self.lives <= 0:
            self.game_over = True
            if self.score > self.high_score:
                self.high_score = self.score
        else:
            # Respawn a ball on paddle
            self.ball_waiting = True
            if self.is_sdplus:
                self.balls = [[
                    float(self.paddle_x - self.ball_r - 2),
                    float(self.paddle_y), 0.0, 0.0,
                ]]
            else:
                self.balls = [[
                    self.cols - 2, self.paddle_row, 0, 0,
                ]]

    # ── BULLETS ───────────────────────────────────

    def _tick_bullets_sdplus(self):
        bullet_speed = 6.0
        alive = []
        for bx, by in self.bullets:
            bx -= bullet_speed
            if bx < 0:
                continue
            if bx < self.brick_zone_w:
                bc = int(bx / self.brick_w)
                br = int(by / self.brick_h)
                bc = max(0, min(bc, self.brick_cols - 1))
                br = max(0, min(br, self.brick_rows - 1))
                if (bc, br) in self.bricks:
                    self.bricks.discard((bc, br))
                    self.score += 1
                    cx = bc * self.brick_w + self.brick_w // 2
                    cy = br * self.brick_h + self.brick_h // 2
                    self._maybe_spawn_item(cx, cy)
                    self._check_win()
                    continue
            alive.append([bx, by])
        self.bullets = alive

    def _tick_bullets_grid(self):
        alive = []
        for bc, br in self.bullets:
            bc -= 1
            if bc < 0:
                continue
            if (bc, br) in self.bricks:
                self.bricks.discard((bc, br))
                self.score += 1
                self._maybe_spawn_item_grid(bc, br)
                self._check_win()
                continue
            alive.append([bc, br])
        self.bullets = alive

    # ── ITEMS TICK ────────────────────────────────

    def _tick_items_sdplus(self):
        """Move items rightward toward paddle."""
        item_speed = 2.5
        alive = []
        half_p = self.paddle_h // 2
        for ix, iy, itype in self.items:
            ix += item_speed
            # Check paddle catch
            if ix >= self.paddle_x - 5:
                if abs(iy - self.paddle_y) <= half_p + 6:
                    self._apply_item(itype)
                    continue  # caught
                if ix > self.screen_w:
                    continue  # missed, off screen
            alive.append([ix, iy, itype])
        self.items = alive

    def _tick_items_grid(self):
        """Move items rightward toward paddle (button grid)."""
        alive = []
        for ic, ir, itype in self.items:
            ic += 1
            last_col = self.cols - 1
            if ic >= last_col:
                if abs(ir - self.paddle_row) <= 1:
                    self._apply_item(itype)
                    continue  # caught
                if ic > last_col:
                    continue  # missed
            alive.append([ic, ir, itype])
        self.items = alive

    # ── SD+ TICK ──────────────────────────────────

    def tick_sdplus(self):
        if not self.game_active or self.game_over:
            return
        if self.ball_waiting:
            self.balls[0][0] = float(self.paddle_x - self.ball_r - 2)
            self.balls[0][1] = float(self.paddle_y)
            self._tick_items_sdplus()
            return

        self._tick_bullets_sdplus()
        self._tick_items_sdplus()
        if self.game_over:
            return

        lost_balls = []
        for i, ball in enumerate(self.balls):
            bx, by, bdx, bdy = ball
            nx = bx + bdx
            ny = by + bdy

            # Top/bottom walls
            if ny - self.ball_r < 0:
                ny = float(self.ball_r)
                bdy = abs(bdy)
            elif ny + self.ball_r >= self.screen_h:
                ny = float(self.screen_h - self.ball_r - 1)
                bdy = -abs(bdy)

            # Left wall
            if nx - self.ball_r < 0:
                nx = float(self.ball_r)
                bdx = abs(bdx)

            # Paddle
            if nx + self.ball_r >= self.paddle_x:
                half_p = self.paddle_h // 2
                if abs(ny - self.paddle_y) <= half_p + self.ball_r:
                    nx = float(self.paddle_x - self.ball_r - 1)
                    self.ball_speed = min(12, self.ball_speed + 1)
                    bdx = float(-self.ball_speed)
                    offset = (ny - self.paddle_y) / half_p
                    bdy = offset * self.ball_speed
                    self.ammo = min(self.max_ammo, self.ammo + 1)
                else:
                    lost_balls.append(i)
                    continue

            # Brick collision
            if nx < self.brick_zone_w + self.ball_r:
                hit = False
                for ox in range(-self.ball_r, self.ball_r + 1, self.ball_r):
                    for oy in range(-self.ball_r, self.ball_r + 1,
                                    self.ball_r):
                        px = nx + ox
                        py = ny + oy
                        if px < 0 or py < 0:
                            continue
                        bc = int(px / self.brick_w)
                        br = int(py / self.brick_h)
                        if (0 <= bc < self.brick_cols
                                and 0 <= br < self.brick_rows):
                            if (bc, br) in self.bricks:
                                self.bricks.discard((bc, br))
                                self.score += 1
                                cx = bc * self.brick_w + self.brick_w // 2
                                cy = br * self.brick_h + self.brick_h // 2
                                self._maybe_spawn_item(cx, cy)
                                hit = True
                if hit:
                    bdx = abs(bdx)
                    self._check_win()
                    if self.game_over:
                        return

            ball[0] = nx
            ball[1] = ny
            ball[2] = bdx
            ball[3] = bdy

        # Remove lost balls (reverse order)
        for i in sorted(lost_balls, reverse=True):
            self.balls.pop(i)

        if not self.balls:
            self._lose_ball()

    # ── BUTTON GRID TICK ──────────────────────────

    def tick_buttons(self):
        if not self.game_active or self.game_over:
            return
        if self.ball_waiting:
            self.balls[0][0] = self.cols - 2
            self.balls[0][1] = self.paddle_row
            self._tick_items_grid()
            return

        self._tick_bullets_grid()
        self._tick_items_grid()
        if self.game_over:
            return

        lost_balls = []
        for i, ball in enumerate(self.balls):
            bc, br, bdx, bdy = ball
            nc = bc + bdx
            nr = br + bdy

            if nr < 0:
                nr = 0
                bdy = 1
            elif nr >= self.rows:
                nr = self.rows - 1
                bdy = -1

            if nc < 0:
                nc = 0
                bdx = 1

            last_col = self.cols - 1
            if nc >= last_col:
                if abs(nr - self.paddle_row) <= 1:
                    nc = last_col - 1
                    bdx = -1
                    if nr < self.paddle_row:
                        bdy = -1
                    elif nr > self.paddle_row:
                        bdy = 1
                    self.ball_speed = min(12, self.ball_speed + 1)
                    self.ammo = min(self.max_ammo, self.ammo + 1)
                else:
                    lost_balls.append(i)
                    continue

            # Brick collision
            hit = False
            for dc in range(0, 2):
                for dr in [-1, 0, 1]:
                    cc = nc - dc
                    cr = nr + dr
                    if (cc, cr) in self.bricks:
                        self.bricks.discard((cc, cr))
                        self.score += 1
                        self._maybe_spawn_item_grid(cc, cr)
                        hit = True
            if hit:
                bdx = -bdx
                nc = bc
                self._check_win()
                if self.game_over:
                    return

            ball[0] = nc
            ball[1] = nr
            ball[2] = bdx
            ball[3] = bdy

        for i in sorted(lost_balls, reverse=True):
            self.balls.pop(i)

        if not self.balls:
            self._lose_ball()

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
                self.ball_speed = min(12, self.ball_speed + 1)
            elif col == 2:
                if self.ball_waiting:
                    self._launch_ball()
                else:
                    self._fire()
        else:
            col = key % self.cols
            row = key // self.cols
            last_col = self.cols - 1
            if col == last_col:
                if self.ball_waiting:
                    self._launch_ball()
                elif row == self.paddle_row:
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
            elif self.ball_waiting:
                self._launch_ball()
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
        sw, sh = self.screen_w, self.screen_h
        img = Image.new("RGB", (sw, sh), (10, 10, 20))
        draw = ImageDraw.Draw(img)

        if not self.game_active:
            try:
                font = ImageFont.load_default(size=20)
                sfont = ImageFont.load_default(size=14)
            except TypeError:
                font = sfont = ImageFont.load_default()
            draw.text((sw // 2 - 60, 10), "BREAKOUT",
                      fill=(255, 255, 255), font=font)
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
                draw.text((sw // 2 - 30, 15), "WIN!",
                          fill=(0, 255, 100), font=font)
            else:
                draw.text((sw // 2 - 45, 15), "GAME OVER",
                          fill=(255, 60, 60), font=font)
            draw.text((sw // 2 - 40, 55), f"Score: {self.score}",
                      fill=(255, 255, 255), font=sfont)
            draw.text((sw // 2 - 50, 75), "Press dial to retry",
                      fill=(150, 150, 200), font=sfont)
            set_screen(self.deck, img)
            return

        # Bricks
        for (bc, br) in self.bricks:
            x1 = bc * self.brick_w + 1
            y1 = br * self.brick_h + 1
            x2 = x1 + self.brick_w - 2
            y2 = y1 + self.brick_h - 2
            color = BRICK_COLORS[br % len(BRICK_COLORS)]
            draw.rectangle([x1, y1, x2, y2], fill=color)

        # Items
        for ix, iy, itype in self.items:
            c = ITEM_COLORS.get(itype, (255, 255, 255))
            draw.rectangle([int(ix) - 4, int(iy) - 4,
                            int(ix) + 4, int(iy) + 4], fill=c)

        # Paddle
        half_p = self.paddle_h // 2
        px = self.paddle_x
        draw.rectangle(
            [px, self.paddle_y - half_p, px + 10,
             self.paddle_y + half_p],
            fill=COLOR_PADDLE,
        )

        # Bullets
        for bx, by in self.bullets:
            draw.rectangle([int(bx) - 3, int(by) - 1,
                            int(bx) + 3, int(by) + 1],
                           fill=COLOR_BULLET)

        # Balls
        r = self.ball_r
        for ball in self.balls:
            bx, by = int(ball[0]), int(ball[1])
            draw.ellipse([bx - r, by - r, bx + r, by + r],
                         fill=COLOR_BALL)

        # Ammo dots
        for a in range(min(self.ammo, 10)):
            ay = self.paddle_y - half_p - 5 - a * 6
            draw.ellipse([px + 2, ay - 2, px + 6, ay + 2],
                         fill=COLOR_BULLET)

        # Lives dots (below paddle)
        for v in range(self.lives):
            vy = self.paddle_y + half_p + 5 + v * 6
            draw.ellipse([px + 2, vy - 2, px + 6, vy + 2],
                         fill=ITEM_COLORS[ITEM_LIFE])

        # Score + lives text
        try:
            sfont = ImageFont.load_default(size=12)
        except TypeError:
            sfont = ImageFont.load_default()
        draw.text((sw - 60, 2),
                  f"{self.score} V:{self.lives}",
                  fill=(200, 200, 200), font=sfont)

        set_screen(self.deck, img)

    def _render_keys_sdplus(self):
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
                if self.ball_waiting:
                    set_key(self.deck, key, COLOR_BALL, "GO!")
                elif self.ammo > 0:
                    set_key(self.deck, key, COLOR_BULLET,
                            f"F:{self.ammo}")
                else:
                    set_key(self.deck, key, (40, 20, 0), "F:0")
            elif c == 3:
                set_key(self.deck, key, ITEM_COLORS[ITEM_LIFE],
                        f"V:{self.lives}")
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_buttons(self):
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
                    set_key(self.deck, key,
                            BRICK_COLORS[c % len(BRICK_COLORS)], "")
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

        # Build lookup sets for fast rendering
        ball_pos = set()
        for b in self.balls:
            ball_pos.add((int(b[0]), int(b[1])))
        bullet_pos = set()
        for blt in self.bullets:
            bullet_pos.add((int(blt[0]), int(blt[1])))
        item_map = {}
        for ic, ir, itype in self.items:
            item_map[(int(ic), int(ir))] = itype

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols

            if (c, r) in ball_pos:
                set_key(self.deck, key, COLOR_BALL, "")
            elif (c, r) in bullet_pos:
                set_key(self.deck, key, COLOR_BULLET, ">")
            elif (c, r) in item_map:
                itype = item_map[(c, r)]
                set_key(self.deck, key,
                        ITEM_COLORS.get(itype, (255, 255, 255)),
                        ITEM_LABELS.get(itype, "?"))
            elif c == last_c and r == self.paddle_row:
                label = f"V{self.lives}"
                set_key(self.deck, key, COLOR_PADDLE, label)
            elif (c, r) in self.bricks:
                set_key(self.deck, key,
                        BRICK_COLORS[c % len(BRICK_COLORS)], "")
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
        print("Items drop from bricks — catch them with paddle!")
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



if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
