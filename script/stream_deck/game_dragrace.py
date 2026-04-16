#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Drag Race.

Shift gears at the right RPM! Too early = slow, too late = redline.
Buttons light up as RPM rises. Press at the green zone to shift.
Best time wins! 2P: race side by side on two decks.
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
COLOR_LOW = (0, 80, 0)
COLOR_MID = (120, 180, 0)
COLOR_GREEN = (0, 220, 0)
COLOR_RED = (220, 0, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)
COLOR_LOSE = (200, 0, 0)
COLOR_GO = (255, 255, 0)

MAX_GEARS = 5
RPM_SPEED = 0.05


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 18 if len(text) <= 4 else 12
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


class DragRace:
    def __init__(self, decks):
        self.decks = decks
        self.num_players = len(decks)
        rows, cols = decks[0].key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.running = True
        self.game_active = False
        self.game_over = False
        # Per player state
        self.rpm = [0.0, 0.0]
        self.gear = [0, 0]
        self.speed = [0.0, 0.0]
        self.distance = [0.0, 0.0]
        self.penalty = [0.0, 0.0]
        self.finished = [False, False]
        self.finish_time = [0.0, 0.0]
        self.start_time = 0
        self.countdown = 0
        self.best_time = 0

    def reset(self):
        self.rpm = [0.0, 0.0]
        self.gear = [0, 0]
        self.speed = [0.0, 0.0]
        self.distance = [0.0, 0.0]
        self.penalty = [0.0, 0.0]
        self.finished = [False, False]
        self.finish_time = [0.0, 0.0]
        self.game_over = False
        self.game_active = True
        self.countdown = 3
        self.start_time = time.monotonic() + 3

    def tick(self):
        if not self.game_active:
            return

        now = time.monotonic()

        # Countdown
        if now < self.start_time:
            self.countdown = int(self.start_time - now) + 1
            return
        self.countdown = 0

        active = [0] if self.num_players == 1 else [0, 1]

        for p in active:
            if self.finished[p]:
                continue
            # RPM rises automatically
            self.rpm[p] = min(1.0, self.rpm[p] + 0.02 + self.gear[p] * 0.005)
            # Speed based on gear and RPM efficiency
            efficiency = 1.0 - abs(self.rpm[p] - 0.7) * 1.5
            efficiency = max(0.1, efficiency)
            self.speed[p] = (self.gear[p] + 1) * efficiency * 2 - self.penalty[p]
            self.speed[p] = max(0, self.speed[p])
            self.distance[p] += self.speed[p]
            self.penalty[p] *= 0.95

            # Auto-finish at 100m
            if self.distance[p] >= 100:
                self.finished[p] = True
                self.finish_time[p] = now - self.start_time

        if all(self.finished[p] for p in active):
            self.game_over = True
            best = min(self.finish_time[p] for p in active)
            if self.best_time == 0 or best < self.best_time:
                self.best_time = best

    def handle_key(self, key, deck_index=0):
        if self.game_over or not self.game_active:
            self.reset()
            return

        p = 0 if self.num_players == 1 else deck_index

        if self.countdown > 0:
            return

        if self.finished[p]:
            return

        # Shift gear
        if self.gear[p] < MAX_GEARS:
            # Penalty for bad timing
            if self.rpm[p] < 0.5:
                self.penalty[p] += 2  # Too early
            elif self.rpm[p] > 0.9:
                self.penalty[p] += 3  # Too late (redline)
            self.gear[p] += 1
            self.rpm[p] = 0.2

    def render_all(self):
        for i, deck in enumerate(self.decks):
            self._render(deck, i)

    def _render(self, deck, di):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        p = 0 if self.num_players == 1 else di

        if not self.game_active:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, key, COLOR_GO, "DRAG")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "START")
                elif self.num_players == 2 and (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                    set_key(deck, key, COLOR_SCORE, f"P{di + 1}")
                elif (c, r) == (0, last_r) and self.best_time > 0:
                    set_key(deck, key, COLOR_SCORE, f"{self.best_time:.1f}s")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            return

        if self.countdown > 0:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                    colors = {3: COLOR_RED, 2: COLOR_RED, 1: (220, 180, 0)}
                    set_key(deck, key, colors.get(self.countdown, COLOR_RED), str(self.countdown))
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            return

        if self.game_over:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    t_str = f"{self.finish_time[p]:.1f}s"
                    set_key(deck, key, COLOR_WIN, t_str)
                elif self.num_players == 2 and (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    other = 1 - di
                    if self.finish_time[p] <= self.finish_time[other]:
                        set_key(deck, key, COLOR_WIN, "WIN!")
                    else:
                        set_key(deck, key, COLOR_LOSE, "LOSE")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            return

        # RPM bar across bottom row
        rpm = self.rpm[p]
        rpm_cells = int(rpm * self.cols)

        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols

            if r == last_r:
                # RPM bar
                if c < rpm_cells:
                    if rpm > 0.9:
                        set_key(deck, key, COLOR_RED, "")
                    elif rpm > 0.6:
                        set_key(deck, key, COLOR_GREEN, "")
                    elif rpm > 0.3:
                        set_key(deck, key, COLOR_MID, "")
                    else:
                        set_key(deck, key, COLOR_LOW, "")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            elif r == 0 and c == 0:
                set_key(deck, key, COLOR_SCORE, f"G{self.gear[p]}")
            elif r == 0 and c == self.cols - 1:
                dist = int(self.distance[p])
                set_key(deck, key, COLOR_SCORE, f"{dist}m")
            elif r == 0 and c == mid_c:
                spd = int(self.speed[p] * 10)
                set_key(deck, key, COLOR_SCORE, f"{spd}km")
            else:
                # Distance progress bar on middle rows
                progress = min(1.0, self.distance[p] / 100)
                prog_cells = int(progress * self.cols)
                if c < prog_cells:
                    set_key(deck, key, COLOR_CAR if c == prog_cells - 1 else (60, 60, 80), "")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")

    def game_loop(self):
        while self.running and all(d.is_open() for d in self.decks):
            with self.lock:
                self.tick()
                self.render_all()
            time.sleep(RPM_SPEED)

COLOR_CAR = (0, 200, 255)


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
        print("2-PLAYER DRAG RACE! Shift at green RPM zone!")
    else:
        print(f"Drag Race on {decks[0].deck_type()}")
    print("Press any button to shift gear. Green zone = best timing!")
    game = DragRace(decks)
    game.render_all()
    for i, deck in enumerate(decks):
        def make_cb(idx):
            def cb(d, k, s):
                if not s:
                    return
                with game.lock:
                    game.handle_key(k, idx)
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
        print(f"\nBest time: {game.best_time:.1f}s")


if __name__ == "__main__":
    main()
