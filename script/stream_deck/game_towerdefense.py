#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Tower Defense for Elgato Stream Deck (adapts to any layout).

Enemies walk left to right across the middle row. Place towers on other
rows to shoot them. Press to place/upgrade tower. Survive all waves!
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

COLOR_EMPTY = (20, 30, 20)
COLOR_PATH = (60, 50, 40)
COLOR_TOWER = (0, 120, 200)
COLOR_TOWER2 = (200, 120, 0)
COLOR_ENEMY = (220, 40, 40)
COLOR_BULLET = (255, 255, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)
COLOR_LOSE = (200, 0, 0)

TICK_SPEED = 0.5
WAVES = 5
ENEMIES_PER_WAVE = 3


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


class TowerDefense:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.running = True
        self.path_row = rows // 2
        self.towers = {}
        self.enemies = []
        self.score = 0
        self.lives = 3
        self.wave = 0
        self.spawn_timer = 0
        self.enemies_spawned = 0
        self.game_active = False
        self.game_over = False
        self.won = False

    def reset(self):
        self.towers = {}
        self.enemies = []
        self.score = 0
        self.lives = 3
        self.wave = 1
        self.spawn_timer = 0
        self.enemies_spawned = 0
        self.game_over = False
        self.won = False
        self.game_active = True

    def tick(self):
        if not self.game_active or self.game_over:
            return

        # Spawn enemies
        if self.enemies_spawned < ENEMIES_PER_WAVE + self.wave:
            self.spawn_timer += 1
            if self.spawn_timer >= 3:
                hp = 1 + self.wave // 2
                self.enemies.append({"col": 0, "hp": hp})
                self.enemies_spawned += 1
                self.spawn_timer = 0

        # Move enemies
        for e in self.enemies:
            e["col"] += 1

        # Tower shooting
        for (tc, tr), level in list(self.towers.items()):
            for e in self.enemies:
                if e["col"] == tc and e["hp"] > 0:
                    e["hp"] -= level
                    break
                if abs(e["col"] - tc) <= 1 and e["hp"] > 0:
                    e["hp"] -= level
                    break

        # Remove dead enemies
        killed = [e for e in self.enemies if e["hp"] <= 0]
        self.score += len(killed)
        self.enemies = [e for e in self.enemies if e["hp"] > 0]

        # Check escaped enemies
        escaped = [e for e in self.enemies if e["col"] >= self.cols]
        self.lives -= len(escaped)
        self.enemies = [e for e in self.enemies if e["col"] < self.cols]

        if self.lives <= 0:
            self.game_over = True
        elif not self.enemies and self.enemies_spawned >= ENEMIES_PER_WAVE + self.wave:
            if self.wave >= WAVES:
                self.won = True
                self.game_over = True
            else:
                self.wave += 1
                self.enemies_spawned = 0

    def handle_key(self, key):
        if self.game_over or not self.game_active:
            self.reset()
            return

        col = key % self.cols
        row = key // self.cols

        if row == self.path_row:
            return

        pos = (col, row)
        if pos in self.towers:
            self.towers[pos] = min(3, self.towers[pos] + 1)
        else:
            self.towers[pos] = 1

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        enemy_cols = {e["col"] for e in self.enemies}

        if not self.game_active:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_TITLE, "TOWER")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                elif r == self.path_row:
                    set_key(self.deck, key, COLOR_PATH, "")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        if self.game_over:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_WIN if self.won else COLOR_LOSE, "WIN!" if self.won else "OVER")
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

            if r == self.path_row:
                if c in enemy_cols:
                    set_key(self.deck, key, COLOR_ENEMY, "E")
                else:
                    set_key(self.deck, key, COLOR_PATH, "")
            elif pos in self.towers:
                lvl = self.towers[pos]
                color = COLOR_TOWER2 if lvl >= 2 else COLOR_TOWER
                set_key(self.deck, key, color, f"T{lvl}")
            elif key == 0:
                set_key(self.deck, key, COLOR_SCORE, f"W{self.wave}")
            elif key == self.cols - 1:
                set_key(self.deck, key, COLOR_SCORE, f"L:{self.lives}")
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

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
    print(f"Tower Defense on {deck.deck_type()}")
    print("Enemies cross middle row. Press above/below to place towers!")
    game = TowerDefense(deck)
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
        print(f"\nScore: {game.score} | Wave: {game.wave}")


if __name__ == "__main__":
    main()
