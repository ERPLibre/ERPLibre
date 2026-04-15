#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Sokoban.

Push boxes onto targets. Press adjacent buttons to move.
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

COLOR_EMPTY = (40, 40, 50)
COLOR_PLAYER = (0, 180, 255)
COLOR_BOX = (180, 120, 40)
COLOR_TARGET = (220, 0, 0)
COLOR_BOX_ON_TARGET = (0, 200, 60)
COLOR_WALL = (80, 80, 80)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)


class Sokoban:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.player = (0, 0)
        self.boxes = set()
        self.targets = set()
        self.walls = set()
        self.moves = 0
        self.game_active = False
        self.won = False
        self.level = 0
        self.best_moves = 0

    def reset(self):
        self.moves = 0
        self.won = False
        self.game_active = True
        self._generate_level()

    def _generate_level(self):
        """Generate a simple solvable level."""
        self.walls = set()
        self.boxes = set()
        self.targets = set()

        # Number of boxes scales with grid
        num_boxes = max(1, min(3, (self.total_keys - 4) // 5))

        # Player starts at center
        self.player = (self.cols // 2, self.rows // 2)

        # Place boxes and targets randomly
        available = [
            (c, r)
            for r in range(self.rows)
            for c in range(self.cols)
            if (c, r) != self.player
        ]
        random.shuffle(available)

        for i in range(num_boxes):
            if len(available) < 2:
                break
            box = available.pop()
            target = available.pop()
            self.boxes.add(box)
            self.targets.add(target)

        self.level += 1

    def handle_key(self, key):
        if self.won or not self.game_active:
            self.reset()
            self.render()
            return

        col = key % self.cols
        row = key // self.cols
        px, py = self.player

        # Calculate direction from player to pressed key
        dx = col - px
        dy = row - py

        # Only allow adjacent moves
        if abs(dx) + abs(dy) != 1:
            if abs(dx) >= abs(dy):
                dx = 1 if dx > 0 else -1
                dy = 0
            else:
                dy = 1 if dy > 0 else -1
                dx = 0

        nx, ny = px + dx, py + dy

        # Bounds check
        if not (0 <= nx < self.cols and 0 <= ny < self.rows):
            return

        # Wall check
        if (nx, ny) in self.walls:
            return

        # Box push
        if (nx, ny) in self.boxes:
            bx, by = nx + dx, ny + dy
            if not (0 <= bx < self.cols and 0 <= by < self.rows):
                return
            if (bx, by) in self.walls or (bx, by) in self.boxes:
                return
            self.boxes.discard((nx, ny))
            self.boxes.add((bx, by))

        self.player = (nx, ny)
        self.moves += 1

        # Check win
        if self.targets and self.boxes == self.targets:
            self.won = True
            if self.best_moves == 0 or self.moves < self.best_moves:
                self.best_moves = self.moves

        self.render()

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_BOX, "SOKO")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.best_moves:
                    self._set_key(key, COLOR_SCORE, f"B:{self.best_moves}")
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            return

        if self.won:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_WIN, "WIN!")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    self._set_key(key, COLOR_SCORE, f"{self.moves}mv")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "NEXT")
                else:
                    self._set_key(key, COLOR_WIN, "")
            return

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols
            pos = (c, r)

            if pos == self.player:
                self._set_key(key, COLOR_PLAYER, "@")
            elif pos in self.boxes and pos in self.targets:
                self._set_key(key, COLOR_BOX_ON_TARGET, "OK")
            elif pos in self.boxes:
                self._set_key(key, COLOR_BOX, "B")
            elif pos in self.targets:
                self._set_key(key, COLOR_TARGET, "X")
            elif pos in self.walls:
                self._set_key(key, COLOR_WALL, "#")
            elif key == 0:
                self._set_key(key, COLOR_SCORE, f"{self.moves}")
            else:
                self._set_key(key, COLOR_EMPTY, "")

    def _set_key(self, key, color, text=""):
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
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx, ty = (w - tw) // 2, (h - th) // 2
            draw.text((tx + 1, ty + 1), text, fill=(0, 0, 0), font=font)
            draw.text((tx, ty), text, fill=(255, 255, 255), font=font)
        native = PILHelper.to_native_key_format(self.deck, img)
        try:
            with self.deck:
                self.deck.set_key_image(key, native)
        except TransportError:
            pass

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
    print(f"Sokoban on {deck.deck_type()} ({cols}x{rows})")
    print("Push boxes (B) onto targets (X). Ctrl+C to quit.")

    game = Sokoban(deck)
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
        print(f"\nMoves: {game.moves} | Best: {game.best_moves}")


if __name__ == "__main__":
    main()
