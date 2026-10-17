#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Whack-a-Mole — 1P or 2P VS.

1 deck: solo, hit moles for 30s.
2 decks: moles appear on BOTH decks simultaneously. Each player
whacks on their own deck. Separate scores. Highest wins!
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
    "name": "Whack-a-Mole",
    "category": "reflex",
    "multiplayer": True,
    "sdplus": False,
    "description": "Hit moles before they vanish! 30s. 1P or 2P VS.",
    "icon": "mole"
}

COLOR_EMPTY = (20, 20, 30)
COLOR_MOLE = (180, 120, 40)
COLOR_HIT = (0, 220, 0)
COLOR_MISS = (220, 0, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)
COLOR_LOSE = (200, 0, 0)

GAME_DURATION = 30
BASE_MOLE_TIME = 1.2
MIN_MOLE_TIME = 0.4


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 22 if len(text) <= 3 else 14
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


class WhackAMole:
    def __init__(self, decks):
        self.decks = decks
        self.num_players = len(decks)
        rows, cols = decks[0].key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.running = True
        self.game_active = False
        self.game_over = False
        self.game_over_time = 0
        self.scores = [0, 0]
        self.moles = set()
        self.time_left = 0
        self._flash = {}
        self._cooldown = 3.0

    def reset(self):
        self.scores = [0, 0]
        self.time_left = GAME_DURATION
        self.moles = set()
        self._flash = {}
        self.game_over = False
        self.game_active = True

    def game_loop(self):
        while self.running and all(d.is_open() for d in self.decks):
            if not self.game_active:
                time.sleep(0.2)
                continue

            with self.lock:
                max_score = max(self.scores)
                max_moles = 1 + max_score // 5
                if len(self.moles) < max_moles:
                    empty = [
                        k for k in range(self.total_keys)
                        if k not in self.moles and k not in self._flash
                    ]
                    if empty:
                        self.moles.add(random.choice(empty))

                self.time_left -= 0.1
                if self.time_left <= 0:
                    self.game_active = False
                    self.game_over = True
                    self.game_over_time = time.monotonic()
                    self.moles.clear()

                now = time.monotonic()
                expired = [k for k, t in self._flash.items() if now - t > 0.3]
                for k in expired:
                    del self._flash[k]

                mole_time = max(MIN_MOLE_TIME, BASE_MOLE_TIME - max_score * 0.05)
                if self.moles and random.random() < 0.1 / mole_time:
                    lost = random.choice(list(self.moles))
                    self.moles.discard(lost)

                self.render_all()

            time.sleep(0.1)

    def handle_key(self, key, deck_index=0):
        if self.game_over:
            elapsed = time.monotonic() - self.game_over_time
            if elapsed < self._cooldown:
                return
            self.game_over = False
            self.reset()
            self.render_all()
            return

        if not self.game_active:
            self.reset()
            self.render_all()
            return

        if key in self.moles:
            self.moles.discard(key)
            self.scores[deck_index] += 1
            self._flash[key] = time.monotonic()

    def render_all(self):
        for i, deck in enumerate(self.decks):
            self._render(deck, i)

    def _render(self, deck, deck_index):
        now = time.monotonic()
        mid_c = self.cols // 2
        last_r = self.rows - 1

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols

            if self.game_over:
                elapsed = now - self.game_over_time
                remaining = max(0, self._cooldown - elapsed)
                can_restart = remaining <= 0

                if (c, r) == (mid_c, 0):
                    my_s = self.scores[deck_index]
                    set_key(deck, key, COLOR_SCORE, f"S:{my_s}")
                elif (c, r) == (mid_c, last_r):
                    if can_restart:
                        set_key(deck, key, COLOR_TITLE, "AGAIN")
                    else:
                        set_key(deck, key, COLOR_EMPTY, f"{remaining:.0f}s")
                elif self.num_players == 2 and (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    if self.scores[deck_index] > self.scores[1 - deck_index]:
                        set_key(deck, key, COLOR_WIN, "WIN!")
                    elif self.scores[deck_index] < self.scores[1 - deck_index]:
                        set_key(deck, key, COLOR_LOSE, "LOSE")
                    else:
                        set_key(deck, key, COLOR_SCORE, "DRAW")
                elif (c, r) == (0, 0):
                    set_key(deck, key, COLOR_SCORE, f"{self.scores[0]}-{self.scores[1]}" if self.num_players == 2 else "")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            elif not self.game_active:
                if (c, r) == (mid_c, 0):
                    set_key(deck, key, COLOR_MOLE, "WHACK")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                    if self.num_players == 2:
                        set_key(deck, key, COLOR_SCORE, f"P{deck_index + 1}")
                    else:
                        set_key(deck, key, COLOR_TITLE, "PRESS")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "START")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            elif key in self._flash:
                set_key(deck, key, COLOR_HIT, "+1")
            elif key in self.moles:
                set_key(deck, key, COLOR_MOLE, "M")
            elif key == 0:
                set_key(deck, key, COLOR_SCORE, str(self.scores[deck_index]))
            elif key == self.total_keys - 1:
                set_key(deck, key, COLOR_SCORE, f"{int(self.time_left)}s")
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
        print(f"2-PLAYER WHACK-A-MOLE! Same moles, separate scores. Highest wins!")
    else:
        print(f"Whack-a-Mole on {decks[0].deck_type()}")

    print(f"Duration: {GAME_DURATION}s. Ctrl+C to quit.")

    game = WhackAMole(decks)
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

    t = threading.Thread(target=game.game_loop, daemon=True)
    t.start()

    try:
        while all(d.is_open() for d in decks):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        game.running = False
        for d in decks:
            try:
                with d:
                    d.reset()
                    d.close()
            except Exception:
                pass
        print(f"\nScores: P1={game.scores[0]} P2={game.scores[1]}")



if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
