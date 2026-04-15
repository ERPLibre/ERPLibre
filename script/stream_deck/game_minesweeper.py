#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Minesweeper game for Elgato Stream Deck (adapts to any layout).

Controls:
  - Short press: reveal cell
  - Long press (hold >0.6s): toggle flag
  - Press revealed number: chord (reveal neighbors if flags match)
"""

import math
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

LONG_PRESS_TIME = 0.6

# Colors
COLOR_HIDDEN = (60, 60, 80)
COLOR_HIDDEN_HOVER = (80, 80, 100)
COLOR_FLAG = (220, 180, 0)
COLOR_MINE = (220, 0, 0)
COLOR_MINE_HIT = (255, 0, 0)
COLOR_REVEALED = (30, 30, 40)
COLOR_EMPTY_REVEALED = (20, 20, 30)
COLOR_WIN = (0, 180, 60)
COLOR_TITLE = (0, 80, 160)

# Number colors (1-8)
NUM_COLORS = {
    0: (60, 60, 70),
    1: (80, 80, 255),
    2: (0, 180, 0),
    3: (255, 50, 50),
    4: (0, 0, 180),
    5: (180, 0, 0),
    6: (0, 180, 180),
    7: (100, 0, 100),
    8: (128, 128, 128),
}


def calc_num_mines(cols, rows):
    """Scale mine count to grid size (~25% density)."""
    total = cols * rows
    return max(1, round(total * 0.25))


class Minesweeper:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.num_mines = calc_num_mines(cols, rows)
        self.lock = threading.Lock()
        self.running = True
        self.game_active = False
        self.first_click = True
        self.mines = set()
        self.revealed = set()
        self.flags = set()
        self.counts = {}
        self.game_over = False
        self.won = False
        self.games_won = 0
        self.games_played = 0
        # Long press tracking
        self._key_down_time = {}

    def key_to_pos(self, key):
        return key % self.cols, key // self.cols

    def pos_to_key(self, col, row):
        if 0 <= col < self.cols and 0 <= row < self.rows:
            return row * self.cols + col
        return -1

    def neighbors(self, col, row):
        """Return list of valid neighbor (col, row)."""
        result = []
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if dc == 0 and dr == 0:
                    continue
                nc, nr = col + dc, row + dr
                if 0 <= nc < self.cols and 0 <= nr < self.rows:
                    result.append((nc, nr))
        return result

    def reset(self):
        """Reset to new game (mines placed on first click)."""
        self.mines = set()
        self.revealed = set()
        self.flags = set()
        self.counts = {}
        self.game_over = False
        self.won = False
        self.first_click = True
        self.game_active = True

    def _place_mines(self, safe_col, safe_row):
        """Place mines avoiding the first clicked cell and its neighbors."""
        safe = set(self.neighbors(safe_col, safe_row))
        safe.add((safe_col, safe_row))

        candidates = []
        for r in range(self.rows):
            for c in range(self.cols):
                if (c, r) not in safe:
                    candidates.append((c, r))

        num = min(self.num_mines, len(candidates))
        self.mines = set(random.sample(candidates, num))
        self._calc_counts()

    def _calc_counts(self):
        """Calculate neighbor mine counts for each cell."""
        self.counts = {}
        for r in range(self.rows):
            for c in range(self.cols):
                if (c, r) in self.mines:
                    self.counts[(c, r)] = -1
                else:
                    count = sum(
                        1 for nc, nr in self.neighbors(c, r)
                        if (nc, nr) in self.mines
                    )
                    self.counts[(c, r)] = count

    def reveal(self, col, row):
        """Reveal a cell. Flood-fill if count is 0."""
        if (col, row) in self.revealed or (col, row) in self.flags:
            return
        if self.game_over:
            return

        if self.first_click:
            self._place_mines(col, row)
            self.first_click = False

        if (col, row) in self.mines:
            self.game_over = True
            self.won = False
            self.games_played += 1
            # Reveal all mines
            self.revealed.update(self.mines)
            return

        # Flood fill
        stack = [(col, row)]
        while stack:
            c, r = stack.pop()
            if (c, r) in self.revealed:
                continue
            self.revealed.add((c, r))
            self.flags.discard((c, r))
            if self.counts.get((c, r), 0) == 0:
                for nc, nr in self.neighbors(c, r):
                    if (nc, nr) not in self.revealed:
                        stack.append((nc, nr))

        self._check_win()

    def chord(self, col, row):
        """Chord: if flagged neighbors match count, reveal remaining."""
        if (col, row) not in self.revealed:
            return
        count = self.counts.get((col, row), 0)
        if count <= 0:
            return

        nbrs = self.neighbors(col, row)
        flag_count = sum(1 for nc, nr in nbrs if (nc, nr) in self.flags)

        if flag_count == count:
            for nc, nr in nbrs:
                if (nc, nr) not in self.flags and (nc, nr) not in self.revealed:
                    self.reveal(nc, nr)

    def toggle_flag(self, col, row):
        """Toggle flag on a hidden cell."""
        if (col, row) in self.revealed or self.game_over:
            return
        if (col, row) in self.flags:
            self.flags.discard((col, row))
        else:
            self.flags.add((col, row))

    def _check_win(self):
        """Check if all non-mine cells are revealed."""
        non_mines = self.total_keys - len(self.mines)
        if len(self.revealed) == non_mines:
            self.won = True
            self.game_over = True
            self.games_won += 1
            self.games_played += 1

    def handle_key_down(self, key):
        """Track key press time for long-press detection."""
        self._key_down_time[key] = time.monotonic()

    def handle_key_up(self, key):
        """Handle key release — short press = reveal, long press = flag."""
        down_time = self._key_down_time.pop(key, None)
        if down_time is None:
            return

        if self.game_over or not self.game_active:
            self.reset()
            return

        col, row = self.key_to_pos(key)
        elapsed = time.monotonic() - down_time

        if elapsed >= LONG_PRESS_TIME:
            # Long press → flag
            self.toggle_flag(col, row)
        elif (col, row) in self.revealed:
            # Press on revealed number → chord
            self.chord(col, row)
        else:
            # Short press → reveal
            self.reveal(col, row)

    def render(self):
        """Render entire board to deck."""
        for r in range(self.rows):
            for c in range(self.cols):
                key = self.pos_to_key(c, r)
                pos = (c, r)
                self._render_cell(key, pos)

    def _render_cell(self, key, pos):
        """Render a single cell."""
        c, r = pos
        mid_c = self.cols // 2
        last_r = self.rows - 1
        last_c = self.cols - 1

        if not self.game_active:
            # Title screen
            if pos == (mid_c - 1, 0):
                self._set_key(key, COLOR_MINE, "MINE")
            elif pos == (mid_c, 0):
                self._set_key(key, COLOR_MINE, "SWEEP")
            elif pos == (mid_c, last_r // 2 if last_r > 1 else 0):
                self._set_key(key, COLOR_TITLE, "PRESS")
            elif pos == (mid_c, last_r):
                self._set_key(key, COLOR_TITLE, "START")
            elif pos == (0, last_r):
                self._set_key(
                    key, COLOR_REVEALED,
                    f"W:{self.games_won}" if self.games_played > 0 else ""
                )
            elif pos == (last_c, last_r):
                self._set_key(key, COLOR_REVEALED, f"{self.num_mines}M")
            else:
                self._set_key(key, COLOR_HIDDEN, "")
            return

        if self.game_over and self.won:
            if pos in self.mines:
                self._set_key(key, COLOR_WIN, "F")
            elif pos in self.revealed:
                count = self.counts.get(pos, 0)
                color = NUM_COLORS.get(count, COLOR_REVEALED)
                self._set_key(key, color, str(count) if count > 0 else "")
            else:
                self._set_key(key, COLOR_WIN, "WIN")
            return

        if self.game_over and not self.won:
            if pos in self.mines:
                self._set_key(key, COLOR_MINE_HIT, "*")
            elif pos in self.flags:
                # Wrong flag
                self._set_key(key, (180, 100, 0), "X")
            elif pos in self.revealed:
                count = self.counts.get(pos, 0)
                color = NUM_COLORS.get(count, COLOR_REVEALED)
                self._set_key(key, color, str(count) if count > 0 else "")
            else:
                self._set_key(key, COLOR_REVEALED, "")
            return

        # Normal play
        if pos in self.flags:
            self._set_key(key, COLOR_FLAG, "F")
        elif pos in self.revealed:
            count = self.counts.get(pos, 0)
            color = NUM_COLORS.get(count, COLOR_REVEALED)
            self._set_key(key, color, str(count) if count > 0 else "")
        else:
            self._set_key(key, COLOR_HIDDEN, "?")

    def _set_key(self, key, color, text=""):
        """Render a single key with color and text."""
        fmt = self.deck.key_image_format()
        w, h = fmt["size"]

        img = Image.new("RGB", (w, h), color)

        if text:
            draw = ImageDraw.Draw(img)
            font_size = 22 if len(text) <= 2 else 14
            try:
                font = ImageFont.load_default(size=font_size)
            except TypeError:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            tx = (w - tw) // 2
            ty = (h - th) // 2

            # Shadow for readability
            draw.text((tx + 1, ty + 1), text, fill=(0, 0, 0), font=font)
            draw.text((tx, ty), text, fill=(255, 255, 255), font=font)

        native = PILHelper.to_native_key_format(self.deck, img)
        try:
            with self.deck:
                self.deck.set_key_image(key, native)
        except TransportError:
            pass

    def key_callback(self, deck, key, state):
        """Stream Deck key callback."""
        with self.lock:
            if state:
                self.handle_key_down(key)
            else:
                self.handle_key_up(key)
                self.render()


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
    num_mines = calc_num_mines(cols, rows)
    print(f"Minesweeper on {deck.deck_type()}")
    print(f"Grid: {cols}x{rows}, {num_mines} mines")
    print("Short press = reveal | Long press = flag")
    print("Press number = chord (auto-reveal if flags match)")
    print("Ctrl+C to quit.")

    game = Minesweeper(deck)
    game.render()

    deck.set_key_callback(game.key_callback)

    try:
        while deck.is_open():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        with deck:
            deck.reset()
            deck.close()
        print(f"\nGames: {game.games_played} | Won: {game.games_won}")


if __name__ == "__main__":
    main()
