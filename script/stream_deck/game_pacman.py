#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Pac-Man.

Eat all dots. Avoid ghosts! Press adjacent buttons to move.
Ghost chases you every other tick.
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

COLOR_EMPTY = (0, 0, 20)
COLOR_PAC = (255, 255, 0)
COLOR_GHOST = (255, 0, 0)
COLOR_DOT = (40, 40, 60)
COLOR_WALL = (0, 0, 80)
COLOR_EATEN = (0, 0, 10)
COLOR_TITLE = (0, 80, 160)
COLOR_WIN = (0, 200, 60)
COLOR_DEAD = (200, 0, 0)
COLOR_SCORE = (40, 40, 80)

TICK_SPEED = 0.5


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 22 if len(text) <= 1 else 14
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


class PacMan:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.running = True
        self.pac = (0, 0)
        self.ghost = (0, 0)
        self.dots = set()
        self.walls = set()
        self.score = 0
        self.game_active = False
        self.game_over = False
        self.won = False
        self.direction = (1, 0)
        self.tick_count = 0

    def reset(self):
        self.pac = (0, self.rows - 1)
        self.ghost = (self.cols - 1, 0)
        self.dots = set()
        self.walls = set()
        self.score = 0
        self.game_over = False
        self.won = False
        self.direction = (1, 0)
        self.tick_count = 0
        self.game_active = True
        # Fill dots, add some walls
        for r in range(self.rows):
            for c in range(self.cols):
                pos = (c, r)
                if pos == self.pac or pos == self.ghost:
                    continue
                if random.random() < 0.15:
                    self.walls.add(pos)
                else:
                    self.dots.add(pos)

    def tick(self):
        if not self.game_active or self.game_over:
            return
        self.tick_count += 1

        # Move pac
        dx, dy = self.direction
        nx = (self.pac[0] + dx) % self.cols
        ny = (self.pac[1] + dy) % self.rows
        if (nx, ny) not in self.walls:
            self.pac = (nx, ny)
            if self.pac in self.dots:
                self.dots.discard(self.pac)
                self.score += 1

        # Ghost chases every 2 ticks
        if self.tick_count % 2 == 0:
            gx, gy = self.ghost
            best = None
            best_dist = float("inf")
            for ddx, ddy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                ngx = (gx + ddx) % self.cols
                ngy = (gy + ddy) % self.rows
                if (ngx, ngy) in self.walls:
                    continue
                dist = abs(ngx - self.pac[0]) + abs(ngy - self.pac[1])
                if dist < best_dist:
                    best_dist = dist
                    best = (ngx, ngy)
            if best:
                self.ghost = best

        if self.pac == self.ghost:
            self.game_over = True
        elif not self.dots:
            self.won = True
            self.game_over = True

    def handle_key(self, key):
        if self.game_over or not self.game_active:
            self.reset()
            return

        col = key % self.cols
        row = key // self.cols
        px, py = self.pac
        dx = col - px
        dy = row - py
        if abs(dx) >= abs(dy):
            self.direction = (1 if dx > 0 else -1, 0)
        else:
            self.direction = (0, 1 if dy > 0 else -1)

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_PAC, "PAC")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                else:
                    set_key(self.deck, key, COLOR_DOT, ".")
            return

        if self.game_over:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_WIN if self.won else COLOR_DEAD, "WIN!" if self.won else "DEAD")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    set_key(self.deck, key, COLOR_SCORE, f"S:{self.score}")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            pos = (c, r)
            if pos == self.pac:
                set_key(self.deck, key, COLOR_PAC, "C")
            elif pos == self.ghost:
                set_key(self.deck, key, COLOR_GHOST, "G")
            elif pos in self.walls:
                set_key(self.deck, key, COLOR_WALL, "")
            elif pos in self.dots:
                set_key(self.deck, key, COLOR_DOT, ".")
            elif key == self.cols * self.rows - 1:
                set_key(self.deck, key, COLOR_SCORE, str(self.score))
            else:
                set_key(self.deck, key, COLOR_EATEN, "")

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
    print(f"Pac-Man on {deck.deck_type()}")
    print("Eat dots, avoid ghost! Press to steer.")
    game = PacMan(deck)
    game.render()
    deck.set_key_callback(lambda d, k, s: (game.lock.acquire(), game.handle_key(k), game.lock.release()) if s else None)
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
