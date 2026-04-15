#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Maze Runner for Elgato Stream Deck (adapts to any layout).

Navigate the maze from top-left to bottom-right. Press adjacent
buttons to move. Maze is randomly generated each game.
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

COLOR_WALL = (40, 40, 50)
COLOR_PATH = (80, 80, 100)
COLOR_PLAYER = (0, 200, 255)
COLOR_EXIT = (0, 220, 60)
COLOR_VISITED = (50, 60, 80)
COLOR_TITLE = (0, 80, 160)
COLOR_WIN = (0, 200, 60)


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 20 if len(text) <= 2 else 14
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


class MazeRunner:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.walls = set()
        self.player = (0, 0)
        self.exit_pos = (cols - 1, rows - 1)
        self.visited = set()
        self.moves = 0
        self.game_active = False
        self.won = False
        self.best = 0

    def reset(self):
        self._generate_maze()
        self.player = (0, 0)
        self.visited = {(0, 0)}
        self.moves = 0
        self.won = False
        self.game_active = True

    def _generate_maze(self):
        """Generate maze using randomized DFS. ~40% walls, guaranteed path."""
        self.walls = set()
        # Start with all walls
        for r in range(self.rows):
            for c in range(self.cols):
                self.walls.add((c, r))
        # Carve path using DFS
        stack = [(0, 0)]
        carved = {(0, 0)}
        self.walls.discard((0, 0))
        while stack:
            cx, cy = stack[-1]
            neighbors = []
            for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < self.cols and 0 <= ny < self.rows and (nx, ny) not in carved:
                    neighbors.append((nx, ny))
            if neighbors:
                nx, ny = random.choice(neighbors)
                carved.add((nx, ny))
                self.walls.discard((nx, ny))
                stack.append((nx, ny))
            else:
                stack.pop()
        # Ensure exit is open
        self.walls.discard(self.exit_pos)
        # Add some extra open cells for multiple paths
        extra = max(1, (self.cols * self.rows) // 5)
        wall_list = list(self.walls)
        random.shuffle(wall_list)
        for pos in wall_list[:extra]:
            self.walls.discard(pos)

    def handle_key(self, key):
        if self.won or not self.game_active:
            self.reset()
            self.render()
            return

        col = key % self.cols
        row = key // self.cols
        px, py = self.player

        # Must be adjacent
        if abs(col - px) + abs(row - py) != 1:
            return
        if (col, row) in self.walls:
            return

        self.player = (col, row)
        self.visited.add((col, row))
        self.moves += 1

        if self.player == self.exit_pos:
            self.won = True
            if self.best == 0 or self.moves < self.best:
                self.best = self.moves

        self.render()

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_TITLE, "MAZE")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.best:
                    set_key(self.deck, key, (40, 40, 80), f"B:{self.best}")
                else:
                    set_key(self.deck, key, COLOR_WALL if random.random() > 0.5 else COLOR_PATH, "")
            return

        if self.won:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_WIN, "WIN!")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "AGAIN")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    set_key(self.deck, key, (40, 40, 80), f"{self.moves}mv")
                else:
                    set_key(self.deck, key, COLOR_WIN, "")
            return

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols
            pos = (c, r)
            if pos == self.player:
                set_key(self.deck, key, COLOR_PLAYER, "@")
            elif pos == self.exit_pos:
                set_key(self.deck, key, COLOR_EXIT, "END")
            elif pos in self.walls:
                set_key(self.deck, key, COLOR_WALL, "")
            elif pos in self.visited:
                set_key(self.deck, key, COLOR_VISITED, "")
            else:
                set_key(self.deck, key, COLOR_PATH, "")

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
    print(f"Maze Runner on {deck.deck_type()} ({cols}x{rows})")
    print("Navigate from top-left to bottom-right!")
    game = MazeRunner(deck)
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
        print(f"\nMoves: {game.moves} | Best: {game.best}")


if __name__ == "__main__":
    main()
