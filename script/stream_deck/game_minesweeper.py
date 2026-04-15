#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Minesweeper — 1P classic or 2P VS.

1 deck: classic minesweeper. Avoid mines, reveal all safe cells.
  - Short press = reveal, long press = flag, press number = chord.

2 decks: VS MINE HUNTER! Same hidden minefield on both decks.
  - Goal: FIND mines! Click a mine = +1 point, keep your turn.
  - Click a safe cell = turn passes to opponent.
  - Player with most mines found wins!
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
COLOR_FLAG = (220, 180, 0)
COLOR_MINE = (220, 0, 0)
COLOR_MINE_HIT = (255, 0, 0)
COLOR_REVEALED = (30, 30, 40)
COLOR_WIN = (0, 180, 60)
COLOR_LOSE = (200, 0, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_P1 = (0, 180, 100)
COLOR_P2 = (100, 0, 220)
COLOR_YOUR_TURN = (0, 120, 60)
COLOR_WAIT = (60, 60, 60)
COLOR_FOUND_MINE = (255, 160, 0)
COLOR_SAFE_MISS = (80, 80, 100)
COLOR_DRAW = (120, 120, 0)

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


def calc_num_mines(cols, rows, multiplayer=False):
    """Scale mine count to grid size."""
    total = cols * rows
    if multiplayer:
        # More mines in VS mode for more action (~35%)
        return max(2, round(total * 0.35))
    return max(1, round(total * 0.25))


def set_key_image(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        font_size = 22 if len(text) <= 2 else (16 if len(text) <= 4 else 11)
        try:
            font = ImageFont.load_default(size=font_size)
        except TypeError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (w - tw) // 2
        ty = (h - th) // 2
        draw.text((tx + 1, ty + 1), text, fill=(0, 0, 0), font=font)
        draw.text((tx, ty), text, fill=(255, 255, 255), font=font)
    native = PILHelper.to_native_key_format(deck, img)
    try:
        with deck:
            deck.set_key_image(key, native)
    except TransportError:
        pass


def hold_animation(deck, key, stop_event):
    """Animate button fill during long press (solo mode only)."""
    STEPS = 12
    step_time = LONG_PRESS_TIME / STEPS
    fmt = deck.key_image_format()
    w, h = fmt["size"]

    for i in range(STEPS):
        if stop_event.is_set():
            return
        time.sleep(step_time)
        if stop_event.is_set():
            return

        progress = (i + 1) / STEPS
        img = Image.new("RGB", (w, h), COLOR_HIDDEN)
        draw = ImageDraw.Draw(img)
        fill_h = int(h * progress)
        bar_color = (int(220 * progress), int(180 * progress), 0)
        draw.rectangle([0, h - fill_h, w, h], fill=bar_color)

        try:
            font = ImageFont.load_default(size=22)
        except TypeError:
            font = ImageFont.load_default()
        text = "F" if progress > 0.7 else "?"
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
            return

    if not stop_event.is_set():
        for color in (COLOR_FLAG, COLOR_HIDDEN, COLOR_FLAG):
            if stop_event.is_set():
                return
            img = Image.new("RGB", (w, h), color)
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.load_default(size=22)
            except TypeError:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), "F", font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx, ty = (w - tw) // 2, (h - th) // 2
            draw.text((tx + 1, ty + 1), "F", fill=(0, 0, 0), font=font)
            draw.text((tx, ty), "F", fill=(255, 255, 255), font=font)
            native = PILHelper.to_native_key_format(deck, img)
            try:
                with deck:
                    deck.set_key_image(key, native)
            except TransportError:
                return
            time.sleep(0.12)


# ──────────────────────────────────────────────────────────────
# SOLO (classic minesweeper)
# ──────────────────────────────────────────────────────────────

class MinesweeperSolo:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.num_mines = calc_num_mines(cols, rows)
        self.lock = threading.Lock()
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
        self._key_down_time = {}
        self._hold_threads = {}
        self._hold_reached = set()

    def key_to_pos(self, key):
        return key % self.cols, key // self.cols

    def pos_to_key(self, col, row):
        if 0 <= col < self.cols and 0 <= row < self.rows:
            return row * self.cols + col
        return -1

    def neighbors(self, col, row):
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
        self.mines = set()
        self.revealed = set()
        self.flags = set()
        self.counts = {}
        self.game_over = False
        self.won = False
        self.first_click = True
        self.game_active = True

    def _place_mines(self, safe_col, safe_row):
        safe = set(self.neighbors(safe_col, safe_row))
        safe.add((safe_col, safe_row))
        candidates = [
            (c, r) for r in range(self.rows) for c in range(self.cols)
            if (c, r) not in safe
        ]
        num = min(self.num_mines, len(candidates))
        self.mines = set(random.sample(candidates, num))
        self._calc_counts()

    def _calc_counts(self):
        self.counts = {}
        for r in range(self.rows):
            for c in range(self.cols):
                if (c, r) in self.mines:
                    self.counts[(c, r)] = -1
                else:
                    self.counts[(c, r)] = sum(
                        1 for nc, nr in self.neighbors(c, r)
                        if (nc, nr) in self.mines
                    )

    def reveal(self, col, row):
        if (col, row) in self.revealed or (col, row) in self.flags or self.game_over:
            return
        if self.first_click:
            self._place_mines(col, row)
            self.first_click = False
        if (col, row) in self.mines:
            self.game_over = True
            self.won = False
            self.games_played += 1
            self.revealed.update(self.mines)
            return
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
        non_mines = self.total_keys - len(self.mines)
        if len(self.revealed) == non_mines:
            self.won = True
            self.game_over = True
            self.games_won += 1
            self.games_played += 1

    def chord(self, col, row):
        if (col, row) not in self.revealed:
            return
        count = self.counts.get((col, row), 0)
        if count <= 0:
            return
        nbrs = self.neighbors(col, row)
        if sum(1 for nc, nr in nbrs if (nc, nr) in self.flags) == count:
            for nc, nr in nbrs:
                if (nc, nr) not in self.flags and (nc, nr) not in self.revealed:
                    self.reveal(nc, nr)

    def toggle_flag(self, col, row):
        if not self.game_active or self.game_over or self.first_click:
            return
        if (col, row) in self.revealed:
            return
        if (col, row) in self.flags:
            self.flags.discard((col, row))
        else:
            self.flags.add((col, row))

    def handle_key_down(self, key):
        self._key_down_time[key] = time.monotonic()
        self._hold_reached.discard(key)
        col, row = self.key_to_pos(key)
        if (
            self.game_active and not self.game_over
            and not self.first_click
            and (col, row) not in self.revealed
        ):
            stop_event = threading.Event()
            self._hold_threads[key] = stop_event
            threading.Thread(
                target=hold_animation,
                args=(self.deck, key, stop_event),
                daemon=True,
            ).start()

    def handle_key_up(self, key):
        stop_event = self._hold_threads.pop(key, None)
        if stop_event is not None:
            stop_event.set()
        down_time = self._key_down_time.pop(key, None)
        if down_time is None:
            return
        if self.game_over or not self.game_active:
            self.reset()
            return
        col, row = self.key_to_pos(key)
        reached = key in self._hold_reached
        self._hold_reached.discard(key)
        elapsed = time.monotonic() - down_time
        if reached or elapsed >= LONG_PRESS_TIME:
            self.toggle_flag(col, row)
        elif (col, row) in self.revealed:
            self.chord(col, row)
        else:
            self.reveal(col, row)

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        last_c = self.cols - 1
        for r in range(self.rows):
            for c in range(self.cols):
                key = self.pos_to_key(c, r)
                pos = (c, r)
                if not self.game_active:
                    if pos == (mid_c - 1, 0):
                        set_key_image(self.deck, key, COLOR_MINE, "MINE")
                    elif pos == (mid_c, 0):
                        set_key_image(self.deck, key, COLOR_MINE, "SWEEP")
                    elif pos == (mid_c, last_r // 2 if last_r > 1 else 0):
                        set_key_image(self.deck, key, COLOR_TITLE, "PRESS")
                    elif pos == (mid_c, last_r):
                        set_key_image(self.deck, key, COLOR_TITLE, "START")
                    elif pos == (0, last_r) and self.games_played > 0:
                        set_key_image(self.deck, key, COLOR_REVEALED, f"W:{self.games_won}")
                    elif pos == (last_c, last_r):
                        set_key_image(self.deck, key, COLOR_REVEALED, f"{self.num_mines}M")
                    else:
                        set_key_image(self.deck, key, COLOR_HIDDEN, "")
                elif self.game_over and self.won:
                    if pos in self.mines:
                        set_key_image(self.deck, key, COLOR_WIN, "F")
                    elif pos in self.revealed:
                        count = self.counts.get(pos, 0)
                        color = NUM_COLORS.get(count, COLOR_REVEALED)
                        set_key_image(self.deck, key, color, str(count) if count > 0 else "")
                    else:
                        set_key_image(self.deck, key, COLOR_WIN, "WIN")
                elif self.game_over:
                    if pos in self.mines:
                        set_key_image(self.deck, key, COLOR_MINE_HIT, "*")
                    elif pos in self.flags:
                        set_key_image(self.deck, key, (180, 100, 0), "X")
                    elif pos in self.revealed:
                        count = self.counts.get(pos, 0)
                        color = NUM_COLORS.get(count, COLOR_REVEALED)
                        set_key_image(self.deck, key, color, str(count) if count > 0 else "")
                    else:
                        set_key_image(self.deck, key, COLOR_REVEALED, "")
                elif pos in self.flags:
                    set_key_image(self.deck, key, COLOR_FLAG, "F")
                elif pos in self.revealed:
                    count = self.counts.get(pos, 0)
                    color = NUM_COLORS.get(count, COLOR_REVEALED)
                    set_key_image(self.deck, key, color, str(count) if count > 0 else "")
                else:
                    set_key_image(self.deck, key, COLOR_HIDDEN, "?")

    def key_callback(self, deck, key, state):
        with self.lock:
            if state:
                self.handle_key_down(key)
            else:
                self.handle_key_up(key)
                self.render()


# ──────────────────────────────────────────────────────────────
# VS (mine hunter — find bombs to score!)
# ──────────────────────────────────────────────────────────────

class MinesweeperVS:
    """2-player VS: find mines to score. Safe cell = pass turn."""

    def __init__(self, decks):
        self.decks = decks
        rows, cols = decks[0].key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.num_mines = calc_num_mines(cols, rows, multiplayer=True)
        self.lock = threading.Lock()
        self.mines = set()
        self.clicked = set()
        self.found_by = {}  # key -> player_index who found it
        self.scores = [0, 0]
        self.current_player = 0
        self.game_active = False
        self.game_over = False
        self.winner = -1
        self._cooldown_until = 0

    def neighbors(self, col, row):
        result = []
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if dc == 0 and dr == 0:
                    continue
                nc, nr = col + dc, row + dr
                if 0 <= nc < self.cols and 0 <= nr < self.rows:
                    result.append((nc, nr))
        return result

    def _calc_counts(self):
        self.counts = {}
        for r in range(self.rows):
            for c in range(self.cols):
                if (c, r) in self.mines:
                    self.counts[(c, r)] = -1
                else:
                    self.counts[(c, r)] = sum(
                        1 for nc, nr in self.neighbors(c, r)
                        if (nc, nr) in self.mines
                    )

    def _flood_reveal(self, col, row):
        """Flood-fill reveal from (col, row), stop at numbered cells."""
        stack = [(col, row)]
        while stack:
            c, r = stack.pop()
            if (c, r) in self.clicked:
                continue
            if (c, r) in self.mines:
                continue
            self.clicked.add((c, r))
            if self.counts.get((c, r), 0) == 0:
                for nc, nr in self.neighbors(c, r):
                    if (nc, nr) not in self.clicked:
                        stack.append((nc, nr))

    def reset(self):
        # Place mines randomly (no safe-first-click in VS)
        all_cells = [(c, r) for r in range(self.rows) for c in range(self.cols)]
        self.mines = set(random.sample(all_cells, min(self.num_mines, len(all_cells))))
        self._calc_counts()
        self.clicked = set()
        self.found_by = {}
        self.scores = [0, 0]
        self.current_player = 0
        self.game_over = False
        self.winner = -1
        self.game_active = True
        self._cooldown_until = 0

    def handle_key(self, key, deck_index):
        now = time.monotonic()

        if self.game_over:
            if now < self._cooldown_until:
                return
            self.reset()
            self.render_all()
            return

        if not self.game_active:
            self.reset()
            self.render_all()
            return

        # Only current player can click
        if deck_index != self.current_player:
            return

        col = key % self.cols
        row = key // self.cols
        pos = (col, row)

        if pos in self.clicked:
            return

        if pos in self.mines:
            # Found a mine! Score + keep turn
            self.clicked.add(pos)
            self.found_by[pos] = deck_index
            self.scores[deck_index] += 1

            # Check if all mines found
            if len(self.found_by) >= len(self.mines):
                self.game_over = True
                self._cooldown_until = now + 3.0
                if self.scores[0] > self.scores[1]:
                    self.winner = 0
                elif self.scores[1] > self.scores[0]:
                    self.winner = 1
                else:
                    self.winner = -1
        else:
            # Safe cell — flood fill then pass turn
            self._flood_reveal(col, row)
            self.current_player = 1 - self.current_player

        self.render_all()

    def render_all(self):
        for i, deck in enumerate(self.decks):
            self._render(deck, i)

    def _render(self, deck, deck_index):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        is_my_turn = self.current_player == deck_index

        if not self.game_active and not self.game_over:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key_image(deck, key, COLOR_MINE, "HUNT")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                    color = COLOR_P1 if deck_index == 0 else COLOR_P2
                    set_key_image(deck, key, color, f"P{deck_index + 1}")
                elif (c, r) == (mid_c, last_r):
                    set_key_image(deck, key, COLOR_TITLE, "START")
                elif (c, r) == (self.cols - 1, last_r):
                    set_key_image(deck, key, COLOR_SCORE, f"{self.num_mines}M")
                else:
                    set_key_image(deck, key, COLOR_HIDDEN, "")
            return

        if self.game_over:
            now = time.monotonic()
            remaining = max(0, self._cooldown_until - now)
            can_restart = remaining <= 0

            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                pos = (c, r)

                if (c, r) == (mid_c, 0):
                    set_key_image(deck, key, COLOR_SCORE, f"{self.scores[0]}-{self.scores[1]}")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    if self.winner == deck_index:
                        set_key_image(deck, key, COLOR_WIN, "WIN!")
                    elif self.winner < 0:
                        set_key_image(deck, key, COLOR_DRAW, "DRAW")
                    else:
                        set_key_image(deck, key, COLOR_LOSE, "LOSE")
                elif (c, r) == (mid_c, last_r):
                    if can_restart:
                        set_key_image(deck, key, COLOR_TITLE, "AGAIN")
                    else:
                        set_key_image(deck, key, COLOR_WAIT, f"{remaining:.0f}s")
                elif pos in self.found_by:
                    finder = self.found_by[pos]
                    color = COLOR_P1 if finder == 0 else COLOR_P2
                    set_key_image(deck, key, color, "*")
                elif pos in self.mines:
                    # Unfound mine
                    set_key_image(deck, key, COLOR_MINE, "*")
                elif pos in self.clicked:
                    count = self.counts.get(pos, 0)
                    color = NUM_COLORS.get(count, COLOR_SAFE_MISS)
                    set_key_image(deck, key, color, str(count) if count > 0 else "")
                else:
                    set_key_image(deck, key, COLOR_HIDDEN, "")
            return

        # Normal play — all cells are playable, no corner info
        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols
            pos = (c, r)

            if pos in self.found_by:
                finder = self.found_by[pos]
                color = COLOR_P1 if finder == 0 else COLOR_P2
                set_key_image(deck, key, color, "*")
            elif pos in self.clicked:
                count = self.counts.get(pos, 0)
                color = NUM_COLORS.get(count, COLOR_SAFE_MISS)
                set_key_image(deck, key, color, str(count) if count > 0 else "")
            else:
                if is_my_turn:
                    set_key_image(deck, key, COLOR_HIDDEN, "?")
                else:
                    set_key_image(deck, key, COLOR_WAIT, "")


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def parse_args():
    import argparse
    parser = argparse.ArgumentParser(
        description="Minesweeper —",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s                  # auto-detect mode, default mines
  %(prog)s -m 6             # 6 mines
  %(prog)s -v               # show game parameters and exit
  %(prog)s -m 3 -v          # show parameters with 3 mines
""",
    )
    parser.add_argument(
        "-m", "--mines",
        type=int,
        default=None,
        help="number of mines (default: auto ~25%% solo, ~35%% VS)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="show game parameters and exit",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    streamdecks = DeviceManager().enumerate()
    visual = [d for d in streamdecks if d.is_visual()]

    if not visual:
        print("No visual Stream Deck found.")
        sys.exit(1)

    # Try to open decks; for -v we handle failure gracefully
    opened = []
    for d in visual:
        try:
            d.open()
            d.reset()
            d.set_brightness(80)
            opened.append(d)
        except TransportError:
            if not args.verbose:
                print(f"Error opening {d.id()}. Check udev rules.")

    if not opened and not args.verbose:
        print("Could not open any Stream Deck.")
        sys.exit(1)

    is_multi = len(opened) >= 2
    decks = opened[:2] if is_multi else opened[:1]

    if decks:
        rows, cols = decks[0].key_layout()
    else:
        # Fallback for -v without accessible deck
        rows, cols = 3, 5
    total = cols * rows

    # Calculate mine count
    if args.mines is not None:
        num_mines = max(1, min(args.mines, total - 1))
    else:
        num_mines = calc_num_mines(cols, rows, multiplayer=is_multi)

    if args.verbose:
        print("=== Minesweeper Parameters ===")
        print(f"  Mode:          {'VS Mine Hunter (2P)' if is_multi else 'Classic (1P)'}")
        print(f"  Deck(s):       {', '.join(d.deck_type() for d in decks)}")
        print(f"  Grid:          {cols}x{rows} ({total} cells)")
        print(f"  Mines:         {num_mines} ({num_mines / total * 100:.0f}% density)")
        print(f"  Safe cells:    {total - num_mines}")
        if not is_multi:
            print(f"  Long press:    {LONG_PRESS_TIME}s (flag threshold)")
        print(f"  Default mines: {calc_num_mines(cols, rows, multiplayer=is_multi)} (auto)")
        print(f"  Min mines:     1")
        print(f"  Max mines:     {total - 1}")
        if not decks:
            print(f"  (deck not accessible, using default 5x3 layout)")
        for d in decks:
            try:
                with d:
                    d.reset()
                    d.close()
            except Exception:
                pass
        sys.exit(0)

    if is_multi:
        print(f"2-PLAYER MINE HUNTER!")
        print(f"  P1: {decks[0].deck_type()} | P2: {decks[1].deck_type()}")
        print(f"  Grid: {cols}x{rows}, {num_mines} mines")
        print("  Find mines = +1 + keep turn. Safe cell = pass.")
        print("  Most mines found wins!")

        game = MinesweeperVS(decks)
        game.num_mines = num_mines
        game.reset()
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

        # Render loop for cooldown
        def render_loop():
            while all(d.is_open() for d in decks):
                if game.game_over:
                    with game.lock:
                        game.render_all()
                time.sleep(0.5)

        threading.Thread(target=render_loop, daemon=True).start()

        try:
            while all(d.is_open() for d in decks):
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            for d in decks:
                try:
                    with d:
                        d.reset()
                        d.close()
                except Exception:
                    pass
            print(f"\nScore: P1={game.scores[0]} P2={game.scores[1]}")

    else:
        deck = decks[0]
        print(f"Minesweeper on {deck.deck_type()}")
        print(f"Grid: {cols}x{rows}, {num_mines} mines")
        print("Short press = reveal | Long press = flag")
        print("Press number = chord. Ctrl+C to quit.")

        game = MinesweeperSolo(deck)
        game.num_mines = num_mines
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
