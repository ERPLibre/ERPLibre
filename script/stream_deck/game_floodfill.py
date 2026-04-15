#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Flood Fill puzzle for Elgato Stream Deck (1P or 2P race).

1 deck: fill the board from top-left in limited moves.
2 decks: same starting board, each player plays independently.
First to fill wins!
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

PALETTE = [
    (220, 40, 40), (0, 180, 0), (0, 80, 220),
    (220, 180, 0), (180, 0, 180), (0, 180, 180),
]
COLOR_EMPTY = (20, 20, 30)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)
COLOR_LOSE = (180, 0, 0)


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 20 if len(text) <= 4 else 12
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


class FloodFill:
    def __init__(self, decks):
        self.decks = decks
        self.num_players = len(decks)
        rows, cols = decks[0].key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.game_rows = rows - 1
        self.num_colors = min(len(PALETTE), cols)
        self.lock = threading.Lock()
        # Per-player grids
        self.grids = [[], []]
        self.moves = [0, 0]
        self.max_moves = 0
        self.game_active = False
        self.winner = -1

    def reset(self):
        total_cells = self.game_rows * self.cols
        self.max_moves = total_cells + self.num_colors
        base_grid = [random.randint(0, self.num_colors - 1) for _ in range(total_cells)]
        self.grids[0] = base_grid[:]
        self.grids[1] = base_grid[:]
        self.moves = [0, 0]
        self.winner = -1
        self.game_active = True

    def _flood(self, grid, new_color):
        old_color = grid[0]
        if old_color == new_color:
            return
        cols = self.cols
        game_rows = self.game_rows
        stack = [0]
        visited = set()
        while stack:
            idx = stack.pop()
            if idx in visited or grid[idx] != old_color:
                continue
            visited.add(idx)
            grid[idx] = new_color
            c = idx % cols
            r = idx // cols
            if c > 0:
                stack.append(idx - 1)
            if c < cols - 1:
                stack.append(idx + 1)
            if r > 0:
                stack.append(idx - cols)
            if r < game_rows - 1:
                stack.append(idx + cols)

    def _is_filled(self, grid):
        return all(grid[i] == grid[0] for i in range(len(grid)))

    def handle_key(self, key, deck_index=0):
        if self.winner >= 0 or not self.game_active:
            self.reset()
            self.render_all()
            return

        p = 0 if self.num_players == 1 else deck_index
        row = key // self.cols
        col = key % self.cols

        if row == self.rows - 1 and col < self.num_colors:
            color = col
        elif row < self.game_rows:
            idx = row * self.cols + col
            if idx < len(self.grids[p]):
                color = self.grids[p][idx]
            else:
                return
        else:
            return

        self._flood(self.grids[p], color)
        self.moves[p] += 1

        if self._is_filled(self.grids[p]):
            self.winner = p
        elif self.moves[p] >= self.max_moves:
            if self.num_players == 1:
                self.winner = -2  # Lost
            # In 2P, other player can still play

        self.render_all()

    def render_all(self):
        for i, deck in enumerate(self.decks):
            self._render(deck, i)

    def _render(self, deck, deck_index):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        p = 0 if self.num_players == 1 else deck_index

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, key, COLOR_TITLE, "FLOOD")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "START")
                elif self.num_players == 2 and (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                    set_key(deck, key, COLOR_SCORE, f"P{deck_index + 1}")
                elif r == last_r and c < self.num_colors:
                    set_key(deck, key, PALETTE[c], "")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            return

        if self.winner >= 0 or self.winner == -2:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    if self.winner == -2:
                        set_key(deck, key, COLOR_LOSE, "LOST")
                    elif self.num_players == 2:
                        if self.winner == deck_index:
                            set_key(deck, key, COLOR_WIN, "WIN!")
                        else:
                            set_key(deck, key, COLOR_LOSE, "LOSE")
                    else:
                        set_key(deck, key, COLOR_WIN, f"{self.moves[0]}mv")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            return

        grid = self.grids[p]
        for r in range(self.game_rows):
            for c in range(self.cols):
                key = r * self.cols + c
                idx = r * self.cols + c
                if idx < len(grid):
                    set_key(deck, key, PALETTE[grid[idx]], "")

        for c in range(self.cols):
            key = last_r * self.cols + c
            if c < self.num_colors:
                set_key(deck, key, PALETTE[c], "")
            elif c == self.cols - 1:
                remaining = self.max_moves - self.moves[p]
                set_key(deck, key, COLOR_SCORE, f"{remaining}")
            else:
                set_key(deck, key, COLOR_EMPTY, "")


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

    decks = visual[:2] if len(visual) >= 2 else visual[:1]

    if len(decks) == 2:
        print("2-PLAYER FLOOD FILL! Same board, first to fill wins!")
    else:
        print(f"Flood Fill on {decks[0].deck_type()}")

    print("Pick colors from bottom row. Ctrl+C to quit.")

    game = FloodFill(decks)
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
        print(f"\nMoves: P1={game.moves[0]} P2={game.moves[1]}")


if __name__ == "__main__":
    main()
