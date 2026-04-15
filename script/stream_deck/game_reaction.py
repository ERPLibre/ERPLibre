#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Reaction Time — 1P or 2P.

1 deck: 5 rounds, hit the green button ASAP.
2 decks: same target appears on both, fastest press wins each round.
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

COLOR_EMPTY = (20, 20, 30)
COLOR_WAIT = (180, 120, 0)
COLOR_GO = (0, 220, 0)
COLOR_HIT = (0, 180, 220)
COLOR_EARLY = (220, 0, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)
COLOR_LOSE = (200, 0, 0)

ROUNDS = 5


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 18 if len(text) <= 5 else 12
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


class ReactionGame:
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
        self.round = 0
        self.p1_times = []
        self.p2_times = []
        self.p1_wins = 0
        self.p2_wins = 0
        self.target_key = -1
        self.go_time = 0
        self.waiting = False
        self.show_result = False
        self.early = [False, False]
        self.round_winner = -1

    def reset(self):
        self.round = 0
        self.p1_times = []
        self.p2_times = []
        self.game_active = True
        self.early = [False, False]
        self.show_result = False
        self.round_winner = -1
        self._next_round()

    def _next_round(self):
        self.round += 1
        self.waiting = True
        self.target_key = -1
        self.show_result = False
        self.early = [False, False]
        self.round_winner = -1

        for deck in self.decks:
            for k in range(self.total_keys):
                set_key(deck, k, COLOR_WAIT, f"R{self.round}" if k == 0 else "")

        threading.Thread(target=self._wait_and_show, daemon=True).start()

    def _wait_and_show(self):
        delay = random.uniform(1.5, 4.0)
        start = time.monotonic()
        while time.monotonic() - start < delay:
            if not self.running or not self.game_active or any(self.early):
                return
            time.sleep(0.05)

        if any(self.early) or not self.game_active:
            return

        with self.lock:
            self.target_key = random.randint(0, self.total_keys - 1)
            self.go_time = time.monotonic()
            self.waiting = False

            for deck in self.decks:
                for k in range(self.total_keys):
                    if k == self.target_key:
                        set_key(deck, k, COLOR_GO, "GO!")
                    else:
                        set_key(deck, k, COLOR_EMPTY, "")

    def handle_key(self, key, deck_index=0):
        if not self.game_active:
            self.reset()
            return

        if self.show_result:
            if self.round >= ROUNDS:
                self.game_active = False
                self._render_final()
                return
            self._next_round()
            return

        if self.waiting:
            self.early[deck_index] = True
            self.waiting = False
            for deck in self.decks:
                mid = self.total_keys // 2
                for k in range(self.total_keys):
                    if k == mid:
                        set_key(deck, k, COLOR_EARLY, f"P{deck_index + 1}" if self.num_players == 2 else "EARLY")
                    else:
                        set_key(deck, k, COLOR_EARLY, "")
            self.show_result = True
            self.p1_times.append(9.999)
            if self.num_players == 2:
                self.p2_times.append(9.999)
            return

        if self.target_key >= 0 and self.round_winner < 0:
            reaction = time.monotonic() - self.go_time
            ms = int(reaction * 1000)

            if self.num_players == 2:
                if deck_index == 0:
                    self.p1_times.append(reaction)
                    self.p2_times.append(9.999)
                else:
                    self.p2_times.append(reaction)
                    self.p1_times.append(9.999)
                self.round_winner = deck_index

                for i, deck in enumerate(self.decks):
                    mid = self.total_keys // 2
                    for k in range(self.total_keys):
                        if i == deck_index and k == key:
                            set_key(deck, k, COLOR_HIT, f"{ms}ms")
                        elif k == mid:
                            if i == deck_index:
                                set_key(deck, k, COLOR_WIN, "WIN!")
                            else:
                                set_key(deck, k, COLOR_LOSE, "SLOW")
                        else:
                            set_key(deck, k, COLOR_EMPTY, "")
            else:
                self.p1_times.append(reaction)
                for k in range(self.total_keys):
                    if k == key:
                        set_key(self.decks[0], k, COLOR_HIT, f"{ms}ms")
                    else:
                        set_key(self.decks[0], k, COLOR_EMPTY, "")

            self.target_key = -1
            self.show_result = True

    def _render_final(self):
        p1_valid = [t for t in self.p1_times if t < 9]
        p2_valid = [t for t in self.p2_times if t < 9]
        p1_avg = int((sum(p1_valid) / len(p1_valid)) * 1000) if p1_valid else 9999
        p2_avg = int((sum(p2_valid) / len(p2_valid)) * 1000) if p2_valid else 9999

        mid_c = self.cols // 2
        last_r = self.rows - 1

        for i, deck in enumerate(self.decks):
            for k in range(self.total_keys):
                r = k // self.cols
                c = k % self.cols
                if (c, r) == (mid_c, 0):
                    if self.num_players == 2:
                        my_avg = p1_avg if i == 0 else p2_avg
                        set_key(deck, k, COLOR_HIT, f"{my_avg}ms")
                    else:
                        set_key(deck, k, COLOR_HIT, f"{p1_avg}ms")
                elif self.num_players == 2 and (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    i_won = (i == 0 and p1_avg <= p2_avg) or (i == 1 and p2_avg < p1_avg)
                    set_key(deck, k, COLOR_WIN if i_won else COLOR_LOSE, "WIN!" if i_won else "LOSE")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, k, COLOR_TITLE, "AGAIN")
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
                    set_key(deck, k, COLOR_GO, "REACT")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                    if self.num_players == 2:
                        set_key(deck, k, COLOR_SCORE, f"P{i + 1}")
                    else:
                        set_key(deck, k, COLOR_TITLE, "PRESS")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, k, COLOR_TITLE, "START")
                else:
                    set_key(deck, k, COLOR_EMPTY, "")


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
        print(f"2-PLAYER REACTION! Same target, fastest press wins each round.")
    else:
        print(f"Reaction Time on {decks[0].deck_type()}")

    print(f"Best of {ROUNDS} rounds. Hit the green button! Ctrl+C to quit.")

    game = ReactionGame(decks)
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


if __name__ == "__main__":
    main()
