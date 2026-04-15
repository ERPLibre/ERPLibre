#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Bomberman for Elgato Stream Deck (adapts to any layout).

Move by pressing adjacent buttons. Double-press your position to
place a bomb. Destroy all walls to win. Don't get caught in the blast!
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

COLOR_EMPTY = (40, 60, 40)
COLOR_PLAYER = (0, 180, 255)
COLOR_WALL = (120, 80, 40)
COLOR_BOMB = (60, 60, 60)
COLOR_EXPLOSION = (255, 100, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)
COLOR_DEAD = (180, 0, 0)

BOMB_TIMER = 3.0
EXPLOSION_DURATION = 0.5


class Bomberman:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.running = True
        self.player = (0, 0)
        self.walls = set()
        self.bombs = {}
        self.explosions = {}
        self.game_active = False
        self.game_over = False
        self.won = False
        self.score = 0
        self.high_score = 0

    def reset(self):
        self.player = (0, self.rows - 1)
        self.walls = set()
        self.bombs = {}
        self.explosions = {}
        self.game_over = False
        self.won = False
        self.score = 0
        self.game_active = True

        # Place walls randomly (~40% of grid, avoid player)
        for r in range(self.rows):
            for c in range(self.cols):
                if (c, r) == self.player:
                    continue
                # Keep neighbors of player clear
                px, py = self.player
                if abs(c - px) + abs(r - py) <= 1:
                    continue
                if random.random() < 0.4:
                    self.walls.add((c, r))

    def handle_key(self, key):
        if self.game_over or not self.game_active:
            self.reset()
            return

        col = key % self.cols
        row = key // self.cols
        px, py = self.player

        # Press own position = place bomb
        if (col, row) == self.player:
            if self.player not in self.bombs:
                self.bombs[self.player] = time.monotonic()
            return

        # Calculate direction
        dx = col - px
        dy = row - py
        if abs(dx) >= abs(dy):
            dx = 1 if dx > 0 else -1
            dy = 0
        else:
            dy = 1 if dy > 0 else -1
            dx = 0

        nx, ny = px + dx, py + dy
        if 0 <= nx < self.cols and 0 <= ny < self.rows:
            if (nx, ny) not in self.walls and (nx, ny) not in self.bombs:
                self.player = (nx, ny)

    def tick(self):
        if not self.game_active or self.game_over:
            return

        now = time.monotonic()

        # Check bomb timers
        exploded = []
        for pos, placed_time in list(self.bombs.items()):
            if now - placed_time >= BOMB_TIMER:
                exploded.append(pos)

        for pos in exploded:
            del self.bombs[pos]
            self._explode(pos, now)

        # Clear old explosions
        expired = [
            pos for pos, t in self.explosions.items()
            if now - t > EXPLOSION_DURATION
        ]
        for pos in expired:
            del self.explosions[pos]

        # Check if player caught in explosion
        if self.player in self.explosions:
            self.game_over = True
            if self.score > self.high_score:
                self.high_score = self.score

        # Check win
        if not self.walls and not self.bombs and self.game_active:
            self.won = True
            self.game_over = True
            if self.score > self.high_score:
                self.high_score = self.score

    def _explode(self, pos, now):
        """Create explosion at pos and in 4 directions."""
        cx, cy = pos
        self.explosions[pos] = now

        for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < self.cols and 0 <= ny < self.rows:
                self.explosions[(nx, ny)] = now
                if (nx, ny) in self.walls:
                    self.walls.discard((nx, ny))
                    self.score += 1

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        now = time.monotonic()

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set_key(key, COLOR_EXPLOSION, "BOMB")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.high_score:
                    self._set_key(key, COLOR_SCORE, f"HI:{self.high_score}")
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            return

        if self.game_over:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    color = COLOR_WIN if self.won else COLOR_DEAD
                    text = "WIN!" if self.won else "DEAD"
                    self._set_key(key, color, text)
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    self._set_key(key, COLOR_SCORE, f"S:{self.score}")
                elif (c, r) == (mid_c, last_r):
                    self._set_key(key, COLOR_TITLE, "AGAIN")
                else:
                    self._set_key(key, COLOR_EMPTY, "")
            return

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols
            pos = (c, r)

            if pos in self.explosions:
                self._set_key(key, COLOR_EXPLOSION, "")
            elif pos == self.player:
                self._set_key(key, COLOR_PLAYER, "@")
            elif pos in self.bombs:
                remaining = max(0, BOMB_TIMER - (now - self.bombs[pos]))
                self._set_key(key, COLOR_BOMB, f"{remaining:.0f}")
            elif pos in self.walls:
                self._set_key(key, COLOR_WALL, "#")
            elif key == self.total_keys - 1:
                self._set_key(key, COLOR_SCORE, str(self.score))
            else:
                self._set_key(key, COLOR_EMPTY, "")

    def game_loop(self):
        while self.running and self.deck.is_open():
            with self.lock:
                self.tick()
                self.render()
            time.sleep(0.2)

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
    print(f"Bomberman on {deck.deck_type()} ({cols}x{rows})")
    print("Move=press adjacent. Double-press=bomb. Ctrl+C to quit.")

    game = Bomberman(deck)
    game.render()
    deck.set_key_callback(game.key_callback)

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
