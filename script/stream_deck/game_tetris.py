#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Tetris.

Pieces fall from right to left. On SD+: game plays on touchscreen
with dials for controls. Otherwise: buttons are the grid.
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
    from StreamDeck.Devices.StreamDeck import DialEventType
    from StreamDeck.ImageHelpers import PILHelper
    from StreamDeck.Transport.Transport import TransportError
except ImportError as e:
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

PIECES = {
    "I": [(0, 0), (1, 0), (2, 0), (3, 0)],
    "O": [(0, 0), (1, 0), (0, 1), (1, 1)],
    "T": [(0, 0), (1, 0), (2, 0), (1, 1)],
    "L": [(0, 0), (1, 0), (2, 0), (2, 1)],
    "J": [(0, 0), (1, 0), (2, 0), (0, 1)],
    "S": [(1, 0), (2, 0), (0, 1), (1, 1)],
    "Z": [(0, 0), (1, 0), (1, 1), (2, 1)],
}
PIECE_COLORS = {
    "I": (0, 220, 220),
    "O": (220, 220, 0),
    "T": (160, 0, 220),
    "L": (220, 140, 0),
    "J": (0, 80, 220),
    "S": (0, 220, 0),
    "Z": (220, 0, 0),
}
COLOR_EMPTY = (20, 20, 30)
COLOR_FROZEN = (100, 100, 120)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_GRID_BG = (30, 30, 40)

TICK_SPEED = 0.5
CELL_SIZE = 10  # For touchscreen mode


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 18 if len(text) <= 3 else 12
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
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    try:
        with deck:
            w = deck.TOUCHSCREEN_PIXEL_WIDTH or deck.SCREEN_PIXEL_WIDTH or 800
            h = deck.TOUCHSCREEN_PIXEL_HEIGHT or deck.SCREEN_PIXEL_HEIGHT or 100
            if deck.DECK_TOUCH:
                deck.set_touchscreen_image(buf.getvalue(), 0, 0, w, h)
            else:
                deck.set_screen_image(buf.getvalue())
    except (TransportError, AttributeError):
        pass


class Tetris:
    def __init__(self, deck, use_screen=False):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.btn_cols = cols
        self.btn_rows = rows
        self.use_screen = use_screen
        self.lock = threading.Lock()
        self.running = True

        if use_screen:
            self.sw = deck.TOUCHSCREEN_PIXEL_WIDTH or deck.SCREEN_PIXEL_WIDTH or 800
            self.sh = deck.TOUCHSCREEN_PIXEL_HEIGHT or deck.SCREEN_PIXEL_HEIGHT or 100
            # Grid sized to fit touchscreen: right to left
            self.rows = self.sh // CELL_SIZE
            self.cols = self.sw // CELL_SIZE
        else:
            self.cols = cols
            self.rows = rows
            self.sw = 0
            self.sh = 0

        self.grid = {}
        self.piece = None
        self.piece_type = None
        self.piece_pos = (0, 0)
        self.score = 0
        self.game_active = False
        self.game_over = False

    def reset(self):
        self.grid = {}
        self.score = 0
        self.game_over = False
        self.game_active = True
        self._new_piece()

    def _new_piece(self):
        self.piece_type = random.choice(list(PIECES.keys()))
        self.piece = PIECES[self.piece_type][:]
        # Ensure piece fits within grid at spawn
        max_dx = max(dx for dx, dy in self.piece)
        max_dy = max(dy for dy, dx in self.piece)
        spawn_x = self.cols - 1 - max_dx
        spawn_y = max(0, min(self.rows // 2 - 1, self.rows - 1 - max_dy))
        self.piece_pos = (spawn_x, spawn_y)
        if self._collides(self.piece_pos):
            self.game_over = True

    def _get_cells(self, pos=None):
        px, py = pos or self.piece_pos
        return [(px + dx, py + dy) for dx, dy in self.piece]

    def _collides(self, pos):
        for x, y in self._get_cells(pos):
            if x < 0 or x >= self.cols or y < 0 or y >= self.rows:
                return True
            if (x, y) in self.grid:
                return True
        return False

    def _freeze(self):
        color = PIECE_COLORS.get(self.piece_type, COLOR_FROZEN)
        for x, y in self._get_cells():
            self.grid[(x, y)] = color
        self._clear_columns()
        self._new_piece()

    def _clear_columns(self):
        """Clear full columns (pieces fall left, clear left columns)."""
        cleared = 0
        c = 0
        while c < self.cols:
            if all((c, r) in self.grid for r in range(self.rows)):
                cleared += 1
                for r in range(self.rows):
                    del self.grid[(c, r)]
                new_grid = {}
                for (gc, gr), color in self.grid.items():
                    if gc > c:
                        new_grid[(gc - 1, gr)] = color
                    else:
                        new_grid[(gc, gr)] = color
                self.grid = new_grid
            else:
                c += 1
        self.score += cleared * 10

    def tick(self):
        if not self.game_active or self.game_over:
            return
        new_pos = (self.piece_pos[0] - 1, self.piece_pos[1])
        if self._collides(new_pos):
            self._freeze()
        else:
            self.piece_pos = new_pos

    def _rotate(self):
        rotated = [(-dy, dx) for dx, dy in self.piece]
        min_x = min(x for x, y in rotated)
        min_y = min(y for x, y in rotated)
        new_piece = [(x - min_x, y - min_y) for x, y in rotated]
        old_piece = self.piece
        self.piece = new_piece
        if self._collides(self.piece_pos):
            self.piece = old_piece

    def move_up(self):
        new_pos = (self.piece_pos[0], self.piece_pos[1] - 1)
        if not self._collides(new_pos):
            self.piece_pos = new_pos

    def move_down(self):
        new_pos = (self.piece_pos[0], self.piece_pos[1] + 1)
        if not self._collides(new_pos):
            self.piece_pos = new_pos

    def hard_drop(self):
        while not self._collides((self.piece_pos[0] - 1, self.piece_pos[1])):
            self.piece_pos = (self.piece_pos[0] - 1, self.piece_pos[1])
        self._freeze()

    def handle_key(self, key):
        if self.game_over or not self.game_active:
            self.reset()
            return

        if self.use_screen:
            # Buttons: top-left=rotate, top-right=drop, bottom=up/down
            row = key // self.btn_cols
            col = key % self.btn_cols
            if row == 0 and col == 0:
                self._rotate()
            elif row == 0 and col == self.btn_cols - 1:
                self.hard_drop()
            elif col < self.btn_cols // 2:
                self.move_up()
            else:
                self.move_down()
        else:
            row = key // self.btn_cols
            if row == 0:
                self._rotate()
            elif row == self.btn_rows - 1:
                self.hard_drop()
            elif row < self.btn_rows // 2:
                self.move_up()
            else:
                self.move_down()

    def handle_dial(self, dial, event, value):
        if not self.game_active or self.game_over:
            if event == DialEventType.PUSH and value:
                self.reset()
            return
        if event == DialEventType.TURN:
            if dial == 0:
                # Move up/down
                if value < 0:
                    self.move_up()
                else:
                    self.move_down()
            elif dial == 1:
                self._rotate()
        elif event == DialEventType.PUSH and value:
            if dial == 0 or dial == 1:
                self._rotate()
            elif dial >= 2:
                self.hard_drop()

    def render(self):
        self._render_keys()
        if self.use_screen:
            self._render_screen()

    def _render_keys(self):
        mid_c = self.btn_cols // 2
        last_r = self.btn_rows - 1

        if self.use_screen:
            # Control buttons only
            for key in range(self.btn_cols * self.btn_rows):
                r = key // self.btn_cols
                c = key % self.btn_cols

                if not self.game_active:
                    if (c, r) == (mid_c, 0):
                        set_key(self.deck, key, COLOR_TITLE, "TETR")
                    elif (c, r) == (mid_c, last_r):
                        set_key(self.deck, key, COLOR_TITLE, "START")
                    else:
                        set_key(self.deck, key, COLOR_EMPTY, "")
                elif self.game_over:
                    if (c, r) == (mid_c, 0):
                        set_key(self.deck, key, (200, 0, 0), f"S:{self.score}")
                    elif (c, r) == (mid_c, last_r):
                        set_key(self.deck, key, COLOR_TITLE, "AGAIN")
                    else:
                        set_key(self.deck, key, COLOR_EMPTY, "")
                else:
                    if r == 0 and c == 0:
                        set_key(self.deck, key, (100, 0, 200), "ROT")
                    elif r == 0 and c == self.btn_cols - 1:
                        set_key(self.deck, key, (200, 100, 0), "DROP")
                    elif r == 0 and c == mid_c:
                        set_key(self.deck, key, COLOR_SCORE, str(self.score))
                    elif r == last_r and c < mid_c:
                        set_key(self.deck, key, (0, 80, 120), "UP")
                    elif r == last_r and c >= mid_c:
                        set_key(self.deck, key, (0, 120, 80), "DOWN")
                    else:
                        pc = PIECE_COLORS.get(self.piece_type, (100, 100, 100))
                        set_key(self.deck, key, (pc[0] // 4, pc[1] // 4, pc[2] // 4), "")
            return

        # Button grid mode (no touchscreen)
        active_cells = set(self._get_cells()) if self.piece and not self.game_over else set()
        piece_color = PIECE_COLORS.get(self.piece_type, (200, 200, 200))

        if not self.game_active:
            for key in range(self.btn_cols * self.btn_rows):
                r = key // self.btn_cols
                c = key % self.btn_cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_TITLE, "TETR")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        if self.game_over:
            for key in range(self.btn_cols * self.btn_rows):
                r = key // self.btn_cols
                c = key % self.btn_cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, (200, 0, 0), f"S:{self.score}")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        for key in range(self.btn_cols * self.btn_rows):
            r = key // self.btn_cols
            c = key % self.btn_cols
            if (c, r) in active_cells:
                set_key(self.deck, key, piece_color, "")
            elif (c, r) in self.grid:
                set_key(self.deck, key, self.grid[(c, r)], "")
            elif key == 0:
                set_key(self.deck, key, COLOR_SCORE, str(self.score))
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_screen(self):
        w, h = self.sw, self.sh
        img = Image.new("RGB", (w, h), (10, 10, 15))
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.load_default(size=14)
        except TypeError:
            font = ImageFont.load_default()

        if not self.game_active and not self.game_over:
            draw.text((w // 2 - 30, h // 2 - 7), "TETRIS", fill=(0, 220, 220), font=font)
            set_screen(self.deck, img)
            return

        cs = CELL_SIZE
        active_cells = set(self._get_cells()) if self.piece and not self.game_over else set()
        piece_color = PIECE_COLORS.get(self.piece_type, (200, 200, 200))

        # Draw grid
        for (gx, gy), color in self.grid.items():
            x = gx * cs
            y = gy * cs
            draw.rectangle([x + 1, y + 1, x + cs - 1, y + cs - 1], fill=color)

        # Draw active piece
        for cx, cy in active_cells:
            x = cx * cs
            y = cy * cs
            draw.rectangle([x + 1, y + 1, x + cs - 1, y + cs - 1], fill=piece_color)

        # Draw ghost (drop preview)
        ghost_pos = self.piece_pos
        while not self._collides((ghost_pos[0] - 1, ghost_pos[1])):
            ghost_pos = (ghost_pos[0] - 1, ghost_pos[1])
        if ghost_pos != self.piece_pos:
            for dx, dy in self.piece:
                gx, gy = ghost_pos[0] + dx, ghost_pos[1] + dy
                x = gx * cs
                y = gy * cs
                draw.rectangle(
                    [x + 2, y + 2, x + cs - 2, y + cs - 2],
                    outline=(piece_color[0] // 3, piece_color[1] // 3, piece_color[2] // 3),
                )

        # Grid lines
        for gx in range(0, w, cs):
            draw.line([(gx, 0), (gx, h)], fill=(25, 25, 35))
        for gy in range(0, h, cs):
            draw.line([(0, gy), (w, gy)], fill=(25, 25, 35))

        # Score
        draw.text((w - 50, 2), f"S:{self.score}", fill=(200, 200, 200), font=font)

        if self.game_over:
            draw.text((w // 2 - 25, h // 2 - 7), "GAME OVER", fill=(255, 0, 0), font=font)

        set_screen(self.deck, img)

    def game_loop(self):
        while self.running and self.deck.is_open():
            with self.lock:
                self.tick()
                self.render()
            time.sleep(TICK_SPEED)


def main():
    streamdecks = DeviceManager().enumerate()
    deck = next((d for d in streamdecks if d.is_visual()), None)
    if not deck:
        print("No visual Stream Deck found.")
        sys.exit(1)
    deck.open()
    deck.reset()
    deck.set_brightness(80)

    has_screen = deck.DIAL_COUNT and deck.DIAL_COUNT > 0
    use_screen = has_screen

    rows, cols = deck.key_layout()
    if use_screen:
        sw = deck.TOUCHSCREEN_PIXEL_WIDTH or deck.SCREEN_PIXEL_WIDTH or 800
        sh = deck.TOUCHSCREEN_PIXEL_HEIGHT or deck.SCREEN_PIXEL_HEIGHT or 100
        grid_cols = sw // CELL_SIZE
        grid_rows = sh // CELL_SIZE
        print(f"Tetris on {deck.deck_type()} TOUCHSCREEN ({grid_cols}x{grid_rows})")
        print("Dial 1=move up/down, Dial 2=rotate, Dial 3-4=drop")
        print("Buttons: TL=rotate, TR=drop, bottom=up/down")
    else:
        print(f"Tetris on {deck.deck_type()} ({cols}x{rows})")
        print("Top row=rotate. Bottom=drop. Middle=move up/down.")

    game = Tetris(deck, use_screen=use_screen)
    game.render()

    def key_cb(d, k, s):
        if not s:
            return
        with game.lock:
            game.handle_key(k)

    deck.set_key_callback(key_cb)

    if has_screen:
        def dial_cb(d, dial, evt, val):
            with game.lock:
                game.handle_dial(dial, evt, val)
        deck.set_dial_callback(dial_cb)

    t = threading.Thread(target=game.game_loop, daemon=True)
    t.start()
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
        print(f"\nScore: {game.score}")


if __name__ == "__main__":
    main()
