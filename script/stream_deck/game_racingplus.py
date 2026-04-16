#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Racing+ (SD+ dials + touchscreen).

Side-scrolling race on touchscreen! Dial = steer up/down. Obstacles
scroll from right to left. Avoid walls and obstacles. Speed increases.
"""

import io
import os
import random
import sys
import threading
import time

try:
    from PIL import Image, ImageDraw, ImageFont
    from StreamDeck.DeviceManager import DeviceManager
    from StreamDeck.Devices.StreamDeck import DialEventType
    from StreamDeck.ImageHelpers import PILHelper
    from StreamDeck.Transport.Transport import TransportError
except ImportError as e:
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

COLOR_EMPTY = (20, 20, 30)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)


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


def set_screen(deck, img):
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    try:
        with deck:
            w = deck.TOUCHSCREEN_PIXEL_WIDTH or deck.SCREEN_PIXEL_WIDTH or 800
            h = deck.TOUCHSCREEN_PIXEL_HEIGHT or deck.SCREEN_PIXEL_HEIGHT or 100
            if deck.DECK_TOUCH:
                deck.set_touchscreen_image(buf.getvalue(), 0, 0, w, h)
            else:
                deck.set_screen_image(buf.getvalue())
    except (TransportError, AttributeError):
        pass


class RacingPlus:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.running = True
        self.sw = deck.TOUCHSCREEN_PIXEL_WIDTH or deck.SCREEN_PIXEL_WIDTH or 800
        self.sh = deck.TOUCHSCREEN_PIXEL_HEIGHT or deck.SCREEN_PIXEL_HEIGHT or 100
        self.car_y = self.sh // 2
        self.obstacles = []
        self.score = 0
        self.high_score = 0
        self.game_active = False
        self.game_over = False
        self.steer = 0
        self.road_offset = 0

    def reset(self):
        self.car_y = self.sh // 2
        self.obstacles = []
        self.score = 0
        self.game_over = False
        self.game_active = True
        self.steer = 0
        self.road_offset = 0

    def handle_dial(self, dial, event, value):
        if not self.game_active or self.game_over:
            if event == DialEventType.PUSH and value:
                self.reset()
            return
        if event == DialEventType.TURN:
            self.steer = value * 8

    def handle_key(self, key, state):
        if not state:
            return
        if self.game_over or not self.game_active:
            self.reset()

    def tick(self):
        if not self.game_active or self.game_over:
            return

        # Steering (up/down)
        self.car_y += self.steer
        self.car_y = max(10, min(self.sh - 10, self.car_y))
        self.steer = int(self.steer * 0.7)

        # Road boundaries (narrowing, top/bottom walls)
        road_height = max(40, self.sh - 10 - self.score // 5)
        road_center = self.sh // 2
        top_wall = road_center - road_height // 2
        bottom_wall = road_center + road_height // 2

        # Wall collision
        if self.car_y < top_wall + 6 or self.car_y > bottom_wall - 6:
            self.game_over = True
            if self.score > self.high_score:
                self.high_score = self.score
            return

        # Move obstacles left
        speed = 4 + self.score // 40
        self.obstacles = [
            (ox - speed, oy) for ox, oy in self.obstacles
        ]

        # Check obstacle collision (near car on left side)
        car_x = 30
        for ox, oy in self.obstacles:
            if abs(ox - car_x) < 12 and abs(oy - self.car_y) < 10:
                self.game_over = True
                if self.score > self.high_score:
                    self.high_score = self.score
                return

        # Remove off-screen obstacles
        self.obstacles = [
            (ox, oy) for ox, oy in self.obstacles if ox > -10
        ]

        # Spawn new obstacle on right
        if random.random() < 0.08 + self.score * 0.001:
            oy = random.randint(top_wall + 10, bottom_wall - 10)
            self.obstacles.append((self.sw + 10, oy))

        self.road_offset += speed
        self.score += 1

    def render(self):
        self._render_keys()
        self._render_screen()

    def _render_keys(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            if not self.game_active and not self.game_over:
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_TITLE, "RACE+")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.high_score:
                    set_key(self.deck, key, COLOR_SCORE, f"HI:{self.high_score}")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            elif self.game_over:
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, (200, 0, 0), f"S:{self.score}")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            else:
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_SCORE, str(self.score))
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_screen(self):
        w, h = self.sw, self.sh
        img = Image.new("RGB", (w, h), (30, 80, 30))
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.load_default(size=16)
        except TypeError:
            font = ImageFont.load_default()

        if not self.game_active and not self.game_over:
            draw.text((w // 2 - 40, h // 2 - 8), "RACING+", fill=(255, 255, 0), font=font)
            set_screen(self.deck, img)
            return

        # Road (horizontal)
        road_height = max(40, h - 10 - self.score // 5)
        road_center = h // 2
        top = road_center - road_height // 2
        bottom = road_center + road_height // 2

        draw.rectangle([0, top, w, bottom], fill=(60, 60, 70))

        # Road markings (horizontal dashes scrolling left)
        for x in range(0, w, 30):
            xx = (x - self.road_offset * 2) % w
            draw.rectangle([xx, h // 2 - 1, xx + 15, h // 2 + 1], fill=(200, 200, 200))

        # Top/bottom walls
        draw.rectangle([0, top - 3, w, top], fill=(200, 200, 200))
        draw.rectangle([0, bottom, w, bottom + 3], fill=(200, 200, 200))

        # Obstacles
        for ox, oy in self.obstacles:
            ix = int(ox)
            iy = int(oy)
            if -10 <= ix <= w + 10:
                draw.rectangle([ix - 6, iy - 6, ix + 6, iy + 6], fill=(220, 40, 40))

        # Car (on left side)
        cy = int(self.car_y)
        draw.rectangle([20, cy - 5, 38, cy + 5], fill=(0, 200, 255))
        draw.rectangle([22, cy - 3, 36, cy + 3], fill=(0, 150, 200))
        # Nose
        draw.polygon([(38, cy - 4), (44, cy), (38, cy + 4)], fill=(0, 200, 255))

        if self.game_over:
            draw.text((w // 2 - 30, h // 2 - 8), "CRASH!", fill=(255, 0, 0), font=font)

        set_screen(self.deck, img)

    def game_loop(self):
        while self.running and self.deck.is_open():
            with self.lock:
                self.tick()
                self.render()
            time.sleep(0.05)


def main():
    streamdecks = DeviceManager().enumerate()
    deck = next((d for d in streamdecks if d.is_visual() and d.DIAL_COUNT and d.DIAL_COUNT > 0), None)
    if not deck:
        print("No Stream Deck + found (need dials + touchscreen).")
        sys.exit(1)
    deck.open()
    deck.reset()
    deck.set_brightness(80)
    print(f"Racing+ on {deck.deck_type()}")
    print("Turn dial to steer up/down. Avoid walls and obstacles!")
    game = RacingPlus(deck)
    game.render()
    deck.set_dial_callback(lambda d, dial, evt, val: (game.lock.acquire(), game.handle_dial(dial, evt, val), game.lock.release()))
    deck.set_key_callback(lambda d, k, s: (game.lock.acquire(), game.handle_key(k, s), game.lock.release()) if s else None)
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
        print(f"\nScore: {game.score} | High: {game.high_score}")


if __name__ == "__main__":
    main()
