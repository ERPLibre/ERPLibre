#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Simon Says — 1P or 2P.

1 deck: classic Simon — memorize and repeat the sequence.
2 decks: same sequence on both. First to make a mistake loses.
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
    "name": "Simon Says",
    "category": "memory",
    "multiplayer": True,
    "sdplus": False,
    "description": "Memorize and repeat the light sequence! 1P or 2P.",
    "icon": "simon"
}

COLORS = [
    (220, 0, 0), (0, 180, 0), (0, 80, 220), (220, 180, 0),
    (180, 0, 180), (0, 180, 180), (220, 100, 0), (100, 220, 0),
]
COLOR_EMPTY = (20, 20, 30)
COLOR_DIM = (40, 40, 50)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_FAIL = (180, 0, 0)
COLOR_WIN = (0, 200, 60)

SHOW_TIME = 0.5
PAUSE_TIME = 0.2

STATE_IDLE = "idle"
STATE_SHOWING = "showing"
STATE_INPUT = "input"
STATE_GAMEOVER = "gameover"


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 20 if len(text) <= 4 else 14
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


class SimonGame:
    def __init__(self, decks):
        self.decks = decks
        self.num_players = len(decks)
        rows, cols = decks[0].key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.running = True
        self.state = STATE_IDLE
        self.sequence = []
        # Per-player input tracking
        self.input_pos = [0, 0]
        self.player_alive = [True, True]
        self.score = 0
        self.high_score = 0
        self.loser = -1  # deck_index of loser
        self.key_colors = {}
        self._assign_colors()

    def _assign_colors(self):
        for k in range(self.total_keys):
            self.key_colors[k] = COLORS[k % len(COLORS)]

    def reset(self):
        self.sequence = []
        self.input_pos = [0, 0]
        self.player_alive = [True, True]
        self.score = 0
        self.loser = -1
        self.state = STATE_SHOWING
        self._add_to_sequence()

    def _add_to_sequence(self):
        self.sequence.append(random.randint(0, self.total_keys - 1))
        self.input_pos = [0, 0]
        if self.num_players == 2:
            self.player_alive = [True, True]
        threading.Thread(target=self._show_sequence, daemon=True).start()

    def _show_sequence(self):
        with self.lock:
            self.state = STATE_SHOWING
            for deck in self.decks:
                self._render_dim(deck)

        time.sleep(0.5)

        for key in self.sequence:
            if not self.running:
                return
            for deck in self.decks:
                set_key(deck, key, self.key_colors[key], "")
            time.sleep(SHOW_TIME)
            for deck in self.decks:
                set_key(deck, key, COLOR_DIM, "")
            time.sleep(PAUSE_TIME)

        with self.lock:
            self.state = STATE_INPUT
            for i, deck in enumerate(self.decks):
                self._render_ready(deck, i)

    def handle_key(self, key, deck_index=0):
        if self.state in (STATE_IDLE, STATE_GAMEOVER):
            self.reset()
            return

        if self.state != STATE_INPUT:
            return

        if self.num_players == 2:
            self._handle_2p(key, deck_index)
        else:
            self._handle_solo(key)

    def _handle_solo(self, key):
        expected = self.sequence[self.input_pos[0]]
        if key == expected:
            set_key(self.decks[0], key, self.key_colors[key], "")
            self.input_pos[0] += 1
            if self.input_pos[0] >= len(self.sequence):
                self.score = len(self.sequence)
                if self.score > self.high_score:
                    self.high_score = self.score
                threading.Thread(target=self._success, daemon=True).start()
        else:
            self.score = len(self.sequence) - 1
            if self.score > self.high_score:
                self.high_score = self.score
            self.state = STATE_GAMEOVER
            self._render_gameover_all()

    def _handle_2p(self, key, deck_index):
        if not self.player_alive[deck_index]:
            return

        expected = self.sequence[self.input_pos[deck_index]]
        if key == expected:
            set_key(self.decks[deck_index], key, self.key_colors[key], "")
            self.input_pos[deck_index] += 1
            if self.input_pos[deck_index] >= len(self.sequence):
                # This player finished the round
                # Check if other player also finished or still going
                other = 1 - deck_index
                if self.input_pos[other] >= len(self.sequence) or not self.player_alive[other]:
                    self.score = len(self.sequence)
                    if self.score > self.high_score:
                        self.high_score = self.score
                    threading.Thread(target=self._success, daemon=True).start()
        else:
            # Wrong — this player loses
            self.player_alive[deck_index] = False
            self.loser = deck_index
            self.score = len(self.sequence) - 1
            if self.score > self.high_score:
                self.high_score = self.score
            self.state = STATE_GAMEOVER
            self._render_gameover_all()

    def _success(self):
        with self.lock:
            for deck in self.decks:
                for k in range(self.total_keys):
                    set_key(deck, k, (0, 100, 0), "")
        time.sleep(0.3)
        with self.lock:
            self._add_to_sequence()

    def _render_dim(self, deck):
        mid_c = self.cols // 2
        for k in range(self.total_keys):
            r = k // self.cols
            c = k % self.cols
            if (c, r) == (mid_c, 0):
                set_key(deck, k, COLOR_SCORE, f"LV{len(self.sequence)}")
            else:
                set_key(deck, k, COLOR_DIM, "")

    def _render_ready(self, deck, deck_index):
        for k in range(self.total_keys):
            rc, g, b = self.key_colors[k]
            set_key(deck, k, (rc // 3, g // 3, b // 3), "")

    def _render_gameover_all(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        for i, deck in enumerate(self.decks):
            for k in range(self.total_keys):
                r = k // self.cols
                c = k % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, k, COLOR_FAIL, f"LV{self.score}")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, k, COLOR_TITLE, "AGAIN")
                elif (c, r) == (0, last_r):
                    set_key(deck, k, COLOR_SCORE, f"HI:{self.high_score}")
                elif self.num_players == 2 and (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    if self.loser == i:
                        set_key(deck, k, COLOR_FAIL, "LOST")
                    else:
                        set_key(deck, k, COLOR_WIN, "WIN!")
                else:
                    set_key(deck, k, COLOR_EMPTY, "")

    def render_title(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        for i, deck in enumerate(self.decks):
            for k in range(self.total_keys):
                r = k // self.cols
                c = k % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, k, COLOR_TITLE, "SIMON")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                    if self.num_players == 2:
                        set_key(deck, k, COLOR_SCORE, f"P{i + 1}")
                    else:
                        set_key(deck, k, COLOR_TITLE, "PRESS")
                elif (c, r) == (0, last_r) and self.high_score:
                    set_key(deck, k, COLOR_SCORE, f"HI:{self.high_score}")
                else:
                    rc, g, b = self.key_colors[k]
                    set_key(deck, k, (rc // 5, g // 5, b // 5), "")


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
        print(f"2-PLAYER SIMON! Same sequence, first mistake loses.")
    else:
        print(f"Simon Says on {decks[0].deck_type()}")

    print("Watch the sequence, repeat it! Ctrl+C to quit.")

    game = SimonGame(decks)
    game.render_title()

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
        game.running = False
        for d in decks:
            try:
                with d:
                    d.reset()
                    d.close()
            except Exception:
                pass
        print(f"\nScore: {game.score} | High: {game.high_score}")



if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
