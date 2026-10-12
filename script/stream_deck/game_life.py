#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Conway's Game of Life.

Press buttons to toggle cells. Press top-left to play/pause.
Press top-right to randomize. Press bottom-right to clear.
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

GAME_META = {
    "name": "Game of Life",
    "category": "sim",
    "multiplayer": False,
    "sdplus": False,
    "description": "Conway's Game of Life. Toggle cells, play/pause.",
    "icon": "life"
}

COLOR_ALIVE = (0, 220, 80)
COLOR_DEAD = (20, 20, 30)
COLOR_PLAY = (0, 160, 0)
COLOR_PAUSE = (200, 160, 0)
COLOR_RANDOM = (0, 80, 200)
COLOR_CLEAR = (160, 0, 0)

TICK_SPEED = 0.5


class GameOfLife:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.grid = [False] * self.total_keys
        self.playing = False
        self.running = True
        self.generation = 0

    def _neighbors(self, key):
        c = key % self.cols
        r = key // self.cols
        count = 0
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if dc == 0 and dr == 0:
                    continue
                nc = (c + dc) % self.cols
                nr = (r + dr) % self.rows
                if self.grid[nr * self.cols + nc]:
                    count += 1
        return count

    def tick(self):
        if not self.playing:
            return
        new_grid = [False] * self.total_keys
        for k in range(self.total_keys):
            n = self._neighbors(k)
            if self.grid[k]:
                new_grid[k] = n in (2, 3)
            else:
                new_grid[k] = n == 3
        self.grid = new_grid
        self.generation += 1

    def handle_key(self, key):
        # Control keys
        if key == 0:
            self.playing = not self.playing
        elif key == self.cols - 1:
            self.playing = False
            for k in range(self.total_keys):
                self.grid[k] = random.random() < 0.4
            self.generation = 0
        elif key == self.total_keys - 1:
            self.playing = False
            self.grid = [False] * self.total_keys
            self.generation = 0
        else:
            self.grid[key] = not self.grid[key]

    def render(self):
        for key in range(self.total_keys):
            if key == 0:
                if self.playing:
                    self._set_key(key, COLOR_PAUSE, "||")
                else:
                    self._set_key(key, COLOR_PLAY, ">")
            elif key == self.cols - 1:
                self._set_key(key, COLOR_RANDOM, "RND")
            elif key == self.total_keys - 1:
                self._set_key(key, COLOR_CLEAR, "CLR")
            elif key == self.total_keys - self.cols:
                self._set_key(
                    key,
                    COLOR_ALIVE if self.grid[key] else COLOR_DEAD,
                    f"G{self.generation}" if self.generation else ""
                )
            elif self.grid[key]:
                self._set_key(key, COLOR_ALIVE, "")
            else:
                self._set_key(key, COLOR_DEAD, "")

    def game_loop(self):
        while self.running and self.deck.is_open():
            with self.lock:
                self.tick()
                self.render()
            time.sleep(TICK_SPEED)

    def _set_key(self, key, color, text=""):
        fmt = self.deck.key_image_format()
        w, h = fmt["size"]
        img = Image.new("RGB", (w, h), color)
        if text:
            draw = ImageDraw.Draw(img)
            font_size = 20 if len(text) <= 3 else 12
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
            self.render()


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
    print(f"Game of Life on {deck.deck_type()} ({cols}x{rows})")
    print("TL=Play/Pause TR=Random BR=Clear. Toggle cells!")

    game = GameOfLife(deck)
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
        print(f"\nGenerations: {game.generation}")



if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
