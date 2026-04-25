#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Vertical Pinball — keep the ball alive, hit bumpers, beat your score.

Rotate the deck 90° so its longer axis is vertical: the column index
becomes the gravity axis and the row index becomes the horizontal axis.

Layout (rotated view):
- Left column (col=0): top wall + bumpers
- Middle column: staggered bumpers + a kicker
- Right column (col=cols-1): flippers — top half = LEFT, bottom half = RIGHT,
  with a center drain on odd row counts
- Ball spawns just above the right column; press any flipper to launch.
"""

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
    "name": "Pinball",
    "category": "arcade",
    "multiplayer": False,
    "sdplus": False,
    "description": (
        "Vertical pinball (rotate deck 90°): flip the ball, hit bumpers."
    ),
    "icon": "pinball",
}

TICK = 0.05
GRAVITY = 0.025
MAX_V = 0.55
BUMPER_BOOST = 0.05
WALL_DAMP = 0.92
FLIPPER_TICKS = 6
FLASH_TICKS = 4
# ball_x is along the col axis (gravity); ball_y is along the row axis.
LAUNCH_VX = -0.65   # upward in rotated view (decreasing col)
LAUNCH_VY = -0.30   # lateral kick (toward decreasing row)
INITIAL_LIVES = 3

COLOR_BG = (8, 8, 24)
COLOR_BALL = (255, 220, 0)
COLOR_BALL_HIGHLIGHT = (255, 255, 200)
COLOR_BUMPER = (220, 30, 30)
COLOR_BUMPER_HIT = (255, 220, 60)
COLOR_KICKER = (180, 0, 200)
COLOR_KICKER_HIT = (255, 100, 255)
COLOR_FLIPPER = (60, 60, 90)
COLOR_FLIPPER_ACTIVE = (255, 130, 0)
COLOR_DRAIN = (40, 0, 0)
COLOR_TITLE = (0, 100, 220)
COLOR_TITLE_ACCENT = (220, 80, 0)
COLOR_GAMEOVER = (180, 0, 0)
COLOR_LIVES = (200, 60, 100)
COLOR_SCORE = (40, 80, 60)
COLOR_HI = (140, 110, 0)


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
        tx, ty = (w - tw) // 2, (h - th) // 2
        draw.text((tx + 1, ty + 1), text, fill=(0, 0, 0), font=font)
        draw.text((tx, ty), text, fill=(255, 255, 255), font=font)
    native = PILHelper.to_native_key_format(deck, img)
    try:
        with deck:
            deck.set_key_image(key, native)
    except TransportError:
        pass


def _draw_ball_cell(deck, key, bg_color, ball_x, ball_y, cell_c, cell_r):
    """Render a key with the ball drawn at its sub-cell offset.
    `ball_x` is the col-axis position; `ball_y` is the row-axis position.
    `cell_c` and `cell_r` are the integer cell indices being drawn."""
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), bg_color)
    draw = ImageDraw.Draw(img)
    fx = max(-0.5, min(0.5, ball_x - cell_c))
    fy = max(-0.5, min(0.5, ball_y - cell_r))
    cx = (0.5 + fx) * w
    cy = (0.5 + fy) * h
    radius = max(4, int(min(w, h) * 0.30))
    glow = max(radius + 3, int(radius * 1.6))
    glow_color = tuple(min(255, c + 50) for c in COLOR_BALL)
    draw.ellipse(
        (cx - glow, cy - glow, cx + glow, cy + glow),
        fill=tuple(
            min(255, c // 4 + b // 4)
            for c, b in zip(glow_color, bg_color)
        ),
    )
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=COLOR_BALL,
    )
    hl = max(2, radius // 2)
    draw.ellipse(
        (cx - hl, cy - hl, cx - hl // 2, cy - hl // 2),
        fill=COLOR_BALL_HIGHLIGHT,
    )
    native = PILHelper.to_native_key_format(deck, img)
    try:
        with deck:
            deck.set_key_image(key, native)
    except TransportError:
        pass


class Pinball:
    """Pinball state. Rotated semantics:
    - ball_x ∈ [0, cols-1] = col-axis position = vertical (gravity) axis.
      Ball "falls" toward higher col indices; col=0 is the top of the table.
    - ball_y ∈ [0, rows-1] = row-axis position = horizontal axis.
    - Drain when ball_x exceeds cols (off the right edge of the deck,
      which is the bottom of the rotated table).
    """

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
        self.score = 0
        self.high_score = 0
        self.lives = INITIAL_LIVES
        self.ball_x = 0.0  # col axis (gravity)
        self.ball_y = 0.0  # row axis (horizontal)
        self.ball_vx = 0.0
        self.ball_vy = 0.0
        self.ball_waiting = True
        self.flipper_left_ticks = 0
        self.flipper_right_ticks = 0
        self.bumper_flash = {}
        self.bumpers, self.kickers = self._build_obstacles()
        self.hud_cells = self._hud_cells()

    # ── LAYOUT ───────────────────────────────────────────────

    def _build_obstacles(self):
        """Bumpers in the upper part of the rotated table (low col index)."""
        bumpers = set()
        kickers = set()
        if self.cols < 2 or self.rows < 2:
            return bumpers, kickers
        # Top of table = first physical column; interior rows are bumpers.
        for r in range(1, self.rows - 1):
            bumpers.add((0, r))
        if self.cols >= 3:
            mid_c = self.cols // 2
            for r in range(0, self.rows):
                if r == self.rows // 2:
                    continue
                if (r % 2) == (mid_c % 2):
                    bumpers.add((mid_c, r))
            if self.cols >= 4 and self.rows >= 3:
                kickers.add((max(1, mid_c - 1), self.rows // 2))
        return bumpers, kickers

    def _hud_cells(self):
        """HUD lives at top corners of the rotated table (col=0)."""
        cells = {}
        if self.cols >= 2:
            cells[(0, 0)] = "score"
            cells[(0, self.rows - 1)] = "lives"
        return cells

    # ── STATE ────────────────────────────────────────────────

    def reset(self):
        self.score = 0
        self.lives = INITIAL_LIVES
        self.game_active = True
        self.game_over = False
        self.bumper_flash = {}
        self._spawn_ball()

    def _spawn_ball(self):
        # Spawn just above the bottom-right flipper of the rotated table.
        self.ball_x = float(max(0, self.cols - 2))
        self.ball_y = float(self.rows - 1)
        self.ball_vx = 0.0
        self.ball_vy = 0.0
        self.ball_waiting = True
        self.flipper_left_ticks = 0
        self.flipper_right_ticks = 0

    def _launch(self):
        if not self.ball_waiting:
            return
        self.ball_waiting = False
        self.ball_vx = LAUNCH_VX                                     # upward
        self.ball_vy = LAUNCH_VY + random.uniform(-0.05, 0.05)       # lateral

    # ── INPUT ────────────────────────────────────────────────

    def handle_key(self, key):
        if self.game_over:
            self.reset()
            return
        if not self.game_active:
            self.reset()
            return
        col = key % self.cols
        row = key // self.cols
        if col == self.cols - 1:
            # Last physical column = bottom row of rotated table.
            # Top half = LEFT flipper, bottom half = RIGHT flipper.
            if row < self.rows / 2:
                self.flipper_left_ticks = FLIPPER_TICKS
            else:
                self.flipper_right_ticks = FLIPPER_TICKS
            if self.ball_waiting:
                self._launch()

    # ── PHYSICS ──────────────────────────────────────────────

    def _decay_counters(self):
        if self.flipper_left_ticks > 0:
            self.flipper_left_ticks -= 1
        if self.flipper_right_ticks > 0:
            self.flipper_right_ticks -= 1
        for k in list(self.bumper_flash.keys()):
            self.bumper_flash[k] -= 1
            if self.bumper_flash[k] <= 0:
                del self.bumper_flash[k]

    def _clamp_velocity(self):
        self.ball_vx = max(-MAX_V, min(MAX_V, self.ball_vx))
        self.ball_vy = max(-MAX_V, min(MAX_V, self.ball_vy))

    def _hit_bumper(self, cell, n_x):
        """Bumper bounces along the gravity axis (ball_x). `cell` is
        a (col, row) tuple. Returns the new ball_x."""
        if cell in self.kickers:
            self.score += 25
            self.bumper_flash[cell] = FLASH_TICKS
            self.ball_vx = -abs(self.ball_vx) - BUMPER_BOOST * 4
            self.ball_vy += random.uniform(-0.25, 0.25)
            return float(cell[0]) + 0.6
        if cell in self.bumpers:
            self.score += 10
            self.bumper_flash[cell] = FLASH_TICKS
            self.ball_vx = -abs(self.ball_vx) - BUMPER_BOOST
            self.ball_vy += random.uniform(-0.20, 0.20)
            return float(cell[0]) + 0.6
        return n_x

    def _try_flippers(self, n_x, n_y):
        if n_x < self.cols - 1:
            return n_x, n_y, False
        row_int = int(round(max(0, min(self.rows - 1, n_y))))
        in_left = row_int < self.rows / 2
        in_right = row_int >= self.rows / 2
        used = False
        if in_left and self.flipper_left_ticks > 0:
            used = True
            self.ball_vx = -0.85
            offset = row_int / max(1, (self.rows / 2 - 1))
            self.ball_vy = -0.45 + offset * 0.6
        elif in_right and self.flipper_right_ticks > 0:
            used = True
            self.ball_vx = -0.85
            offset = (self.rows - 1 - row_int) / max(1, (self.rows / 2 - 1))
            self.ball_vy = 0.45 - offset * 0.6
        if used:
            n_x = float(self.cols - 1) - 0.5
        return n_x, n_y, used

    def tick(self):
        if not self.game_active or self.game_over:
            self._decay_counters()
            return
        self._decay_counters()
        if self.ball_waiting:
            return
        self.ball_vx += GRAVITY  # gravity along col axis
        self._clamp_velocity()
        nx = self.ball_x + self.ball_vx
        ny = self.ball_y + self.ball_vy
        # Side walls: row-axis extremes.
        if ny < 0:
            ny = -ny
            self.ball_vy = -self.ball_vy * WALL_DAMP
        elif ny > self.rows - 1:
            ny = 2 * (self.rows - 1) - ny
            self.ball_vy = -self.ball_vy * WALL_DAMP
        # Top wall: col=0.
        if nx < 0:
            nx = -nx
            self.ball_vx = -self.ball_vx * WALL_DAMP
        # Bumpers / kickers (cell stored as (col, row)).
        cell = (
            int(round(max(0, min(self.cols - 1, nx)))),
            int(round(max(0, min(self.rows - 1, ny)))),
        )
        nx = self._hit_bumper(cell, nx)
        # Flippers
        nx, ny, _ = self._try_flippers(nx, ny)
        # Drain off the rotated bottom (col >= cols).
        if nx >= self.cols:
            self.lives -= 1
            if self.lives <= 0:
                self.game_over = True
                if self.score > self.high_score:
                    self.high_score = self.score
                self.game_active = False
            else:
                self._spawn_ball()
            return
        self.ball_x = nx
        self.ball_y = ny

    # ── RENDER ───────────────────────────────────────────────

    def render(self):
        if self.game_over:
            self._render_gameover()
            return
        if not self.game_active:
            self._render_title()
            return
        self._render_play()

    def _render_play(self):
        ball_cell = (
            int(round(max(0, min(self.cols - 1, self.ball_x)))),
            int(round(max(0, min(self.rows - 1, self.ball_y)))),
        )
        for r in range(self.rows):
            for c in range(self.cols):
                key = r * self.cols + c
                pos = (c, r)
                # Right column = bottom of rotated table = flippers + drain.
                if c == self.cols - 1:
                    if r < self.rows / 2:
                        active = self.flipper_left_ticks > 0
                        side = "L"
                    else:
                        active = self.flipper_right_ticks > 0
                        side = "R"
                    base = COLOR_FLIPPER_ACTIVE if active else COLOR_FLIPPER
                    is_drain = (
                        r == self.rows // 2 and self.rows % 2 == 1
                        and self.rows >= 3
                    )
                    if is_drain and not active:
                        base = COLOR_DRAIN
                    if pos == ball_cell:
                        _draw_ball_cell(
                            self.deck, key, base,
                            self.ball_x, self.ball_y, c, r,
                        )
                    else:
                        label = "" if is_drain else side
                        set_key(self.deck, key, base, label)
                    continue
                # Bumper
                if pos in self.bumpers:
                    flashing = pos in self.bumper_flash
                    color = COLOR_BUMPER_HIT if flashing else COLOR_BUMPER
                    if pos == ball_cell:
                        _draw_ball_cell(
                            self.deck, key, color,
                            self.ball_x, self.ball_y, c, r,
                        )
                    else:
                        set_key(self.deck, key, color, "*")
                    continue
                # Kicker
                if pos in self.kickers:
                    flashing = pos in self.bumper_flash
                    color = COLOR_KICKER_HIT if flashing else COLOR_KICKER
                    if pos == ball_cell:
                        _draw_ball_cell(
                            self.deck, key, color,
                            self.ball_x, self.ball_y, c, r,
                        )
                    else:
                        set_key(self.deck, key, color, "K")
                    continue
                # HUD slots
                hud_role = self.hud_cells.get(pos)
                if hud_role and pos != ball_cell:
                    if hud_role == "score":
                        set_key(self.deck, key, COLOR_SCORE, str(self.score))
                    else:
                        set_key(self.deck, key, COLOR_LIVES, f"L{self.lives}")
                    continue
                # Empty playfield
                if pos == ball_cell:
                    _draw_ball_cell(
                        self.deck, key, COLOR_BG,
                        self.ball_x, self.ball_y, c, r,
                    )
                else:
                    set_key(self.deck, key, COLOR_BG, "")

    def _render_title(self):
        mid_c = self.cols // 2
        mid_r = self.rows // 2
        for r in range(self.rows):
            for c in range(self.cols):
                key = r * self.cols + c
                pos = (c, r)
                # Title labels read top-to-bottom in the rotated view:
                # col=0 (top) = "PIN", middle = "BALL", col=cols-1 = "PUSH".
                if pos == (0, mid_r):
                    set_key(self.deck, key, COLOR_BUMPER, "PIN")
                elif self.rows >= 3 and pos == (0, max(0, mid_r - 1)):
                    set_key(self.deck, key, COLOR_TITLE_ACCENT, "*")
                elif self.rows >= 3 and pos == (
                    0, min(self.rows - 1, mid_r + 1)
                ):
                    set_key(self.deck, key, COLOR_TITLE_ACCENT, "*")
                elif self.cols >= 3 and pos == (mid_c, mid_r):
                    set_key(self.deck, key, COLOR_TITLE, "BALL")
                elif pos == (self.cols - 1, 0):
                    set_key(self.deck, key, COLOR_FLIPPER, "L")
                elif pos == (self.cols - 1, self.rows - 1):
                    set_key(self.deck, key, COLOR_FLIPPER, "R")
                elif pos == (self.cols - 1, mid_r):
                    set_key(self.deck, key, COLOR_TITLE, "PUSH")
                else:
                    set_key(self.deck, key, COLOR_BG, "")

    def _render_gameover(self):
        mid_c = self.cols // 2
        mid_r = self.rows // 2
        for r in range(self.rows):
            for c in range(self.cols):
                key = r * self.cols + c
                pos = (c, r)
                if pos == (0, mid_r):
                    set_key(self.deck, key, COLOR_GAMEOVER, "OVER")
                elif pos == (0, 0):
                    set_key(self.deck, key, COLOR_HI, "HI")
                elif pos == (0, self.rows - 1):
                    set_key(self.deck, key, COLOR_HI, str(self.high_score))
                elif self.cols >= 3 and pos == (mid_c, mid_r):
                    set_key(self.deck, key, COLOR_TITLE, str(self.score))
                elif pos == (self.cols - 1, mid_r):
                    set_key(self.deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(self.deck, key, COLOR_BG, "")

    # ── LOOP ─────────────────────────────────────────────────

    def game_loop(self):
        while self.running and self.deck.is_open():
            with self.lock:
                self.tick()
                self.render()
            time.sleep(TICK)


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
    print(f"Pinball on {deck.deck_type()} ({cols}x{rows})")
    print("Rotate the deck 90°: long axis vertical, USB cable to the side.")
    print(
        "Right column (rotated bottom): top half = LEFT flipper, "
        "bottom half = RIGHT flipper."
    )
    print("First flipper press launches the ball. Ctrl+C to quit.")
    game = Pinball(deck)
    game.render()

    def key_cb(d, k, s):
        if not s:
            return
        with game.lock:
            game.handle_key(k)

    deck.set_key_callback(key_cb)
    game_thread = threading.Thread(target=game.game_loop, daemon=True)
    game_thread.start()
    try:
        while deck.is_open():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        game.running = False
        try:
            with deck:
                deck.reset()
                deck.close()
        except Exception:
            pass
        print(f"\nScore: {game.score} | High: {game.high_score}")


if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
