#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Langton's Ant for Elgato Stream Deck (adapts to any layout).

Cellular automaton: an ant moves on a grid. On white, turn right and
flip to black. On black, turn left and flip to white. Press play/pause.
Emergent patterns appear after ~10000 steps!
"""

import os
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

COLOR_WHITE = (200, 200, 200)
COLOR_BLACK = (20, 20, 30)
COLOR_ANT = (255, 0, 0)
COLOR_PLAY = (0, 160, 0)
COLOR_PAUSE = (200, 160, 0)
COLOR_SCORE = (40, 40, 80)

DIRS = [(0, -1), (1, 0), (0, 1), (-1, 0)]  # Up, Right, Down, Left


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 16 if len(text) <= 3 else 11
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


class LangtonAnt:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.running = True
        self.playing = False
        self.black_cells = set()
        self.ant_x = cols // 2
        self.ant_y = rows // 2
        self.ant_dir = 0  # Index into DIRS
        self.steps = 0

    def tick(self):
        if not self.playing:
            return
        pos = (self.ant_x, self.ant_y)
        if pos in self.black_cells:
            # On black: turn left, flip to white
            self.ant_dir = (self.ant_dir - 1) % 4
            self.black_cells.discard(pos)
        else:
            # On white: turn right, flip to black
            self.ant_dir = (self.ant_dir + 1) % 4
            self.black_cells.add(pos)

        dx, dy = DIRS[self.ant_dir]
        self.ant_x = (self.ant_x + dx) % self.cols
        self.ant_y = (self.ant_y + dy) % self.rows
        self.steps += 1

    def handle_key(self, key):
        if key == 0:
            self.playing = not self.playing
        elif key == self.cols - 1:
            self.black_cells = set()
            self.ant_x = self.cols // 2
            self.ant_y = self.rows // 2
            self.ant_dir = 0
            self.steps = 0
            self.playing = False

    def render(self):
        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            if key == 0:
                if self.playing:
                    set_key(self.deck, key, COLOR_PAUSE, "||")
                else:
                    set_key(self.deck, key, COLOR_PLAY, ">")
            elif key == self.cols - 1:
                set_key(self.deck, key, (160, 0, 0), "CLR")
            elif key == self.cols * self.rows - self.cols:
                set_key(self.deck, key, COLOR_SCORE, str(self.steps))
            elif c == self.ant_x and r == self.ant_y:
                set_key(self.deck, key, COLOR_ANT, "")
            elif (c, r) in self.black_cells:
                set_key(self.deck, key, COLOR_BLACK, "")
            else:
                set_key(self.deck, key, COLOR_WHITE, "")

    def loop(self):
        while self.running and self.deck.is_open():
            with self.lock:
                self.tick()
                self.render()
            time.sleep(0.1)


def main():
    streamdecks = DeviceManager().enumerate()
    deck = next((d for d in streamdecks if d.is_visual()), None)
    if not deck:
        print("No visual Stream Deck found.")
        sys.exit(1)
    deck.open()
    deck.reset()
    deck.set_brightness(80)
    print(f"Langton's Ant on {deck.deck_type()}")
    print("TL=Play/Pause TR=Clear. Watch the ant!")
    game = LangtonAnt(deck)
    game.render()
    deck.set_key_callback(lambda d, k, s: (game.lock.acquire(), game.handle_key(k), game.lock.release()) if s else None)
    t = threading.Thread(target=game.loop, daemon=True)
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
        print(f"\nSteps: {game.steps}")


if __name__ == "__main__":
    main()
