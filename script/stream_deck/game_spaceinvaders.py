#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Space Invaders.

Aliens advance from top. You're on the bottom row. Press your position
to shoot, press adjacent to move. Destroy all aliens to win!
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
COLOR_PLAYER = (0, 200, 255)
COLOR_ALIEN = (0, 220, 0)
COLOR_BULLET = (255, 255, 0)
COLOR_DEAD = (200, 0, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)

TICK_SPEED = 0.5


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


class SpaceInvaders:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.running = True
        self.player_col = cols // 2
        self.aliens = set()
        self.bullets = set()
        self.score = 0
        self.game_active = False
        self.game_over = False
        self.won = False
        self.alien_dir = 1
        self.tick_count = 0

    def reset(self):
        self.player_col = self.cols // 2
        self.aliens = set()
        self.bullets = set()
        self.score = 0
        self.game_over = False
        self.won = False
        self.alien_dir = 1
        self.tick_count = 0
        self.game_active = True
        alien_rows = max(1, self.rows - 2)
        for r in range(alien_rows):
            for c in range(self.cols):
                if random.random() < 0.6:
                    self.aliens.add((c, r))

    def tick(self):
        if not self.game_active or self.game_over:
            return
        self.tick_count += 1

        # Move bullets up
        new_bullets = set()
        for bc, br in self.bullets:
            if br > 0:
                new_bullets.add((bc, br - 1))
        self.bullets = new_bullets

        # Check bullet hits
        hit = self.bullets & self.aliens
        for h in hit:
            self.aliens.discard(h)
            self.bullets.discard(h)
            self.score += 1

        # Move aliens every 3 ticks
        if self.tick_count % 3 == 0:
            move_down = False
            for ac, ar in self.aliens:
                if (ac + self.alien_dir < 0) or (ac + self.alien_dir >= self.cols):
                    move_down = True
                    break
            if move_down:
                self.alien_dir = -self.alien_dir
                self.aliens = {(c, r + 1) for c, r in self.aliens}
            else:
                self.aliens = {(c + self.alien_dir, r) for c, r in self.aliens}

        # Check game over
        if any(r >= self.rows - 1 for _, r in self.aliens):
            self.game_over = True
        if not self.aliens:
            self.won = True
            self.game_over = True

    def handle_key(self, key):
        if self.game_over or not self.game_active:
            self.reset()
            return

        col = key % self.cols
        row = key // self.cols

        if row == self.rows - 1:
            if col == self.player_col:
                self.bullets.add((self.player_col, self.rows - 2))
            else:
                self.player_col = col

    def render(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_ALIEN, "INVD")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        if self.game_over:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_WIN if self.won else COLOR_DEAD, "WIN!" if self.won else "OVER")
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
            if r == last_r and c == self.player_col:
                set_key(self.deck, key, COLOR_PLAYER, "A")
            elif pos in self.aliens:
                set_key(self.deck, key, COLOR_ALIEN, "W")
            elif pos in self.bullets:
                set_key(self.deck, key, COLOR_BULLET, "|")
            elif key == self.cols * self.rows - 1:
                set_key(self.deck, key, COLOR_SCORE, str(self.score))
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
    print(f"Space Invaders on {deck.deck_type()}")
    print("Bottom row: press your pos to shoot, press adjacent to move.")
    game = SpaceInvaders(deck)
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
