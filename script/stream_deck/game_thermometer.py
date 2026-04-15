#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Thermometer guessing game (SD+ dials + touchscreen).

A secret temperature is hidden. Turn dial to adjust your guess.
Touchscreen shows thermometer with hot/cold gradient. Click to submit.
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
COLOR_WIN = (0, 200, 60)


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


class Thermometer:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.target = 0
        self.guess = 50
        self.attempts = 0
        self.game_active = False
        self.won = False
        self.best = 0
        self.sw = deck.TOUCHSCREEN_PIXEL_WIDTH or deck.SCREEN_PIXEL_WIDTH or 800
        self.sh = deck.TOUCHSCREEN_PIXEL_HEIGHT or deck.SCREEN_PIXEL_HEIGHT or 100

    def reset(self):
        self.target = random.randint(-20, 45)
        self.guess = 20
        self.attempts = 0
        self.won = False
        self.game_active = True

    def handle_dial(self, dial, event, value):
        if not self.game_active:
            self.reset()
            self.render()
            return
        if self.won:
            self.reset()
            self.render()
            return
        if event == DialEventType.TURN:
            self.guess = max(-30, min(50, self.guess + value))
        elif event == DialEventType.PUSH and value:
            self.attempts += 1
            if self.guess == self.target:
                self.won = True
                if self.best == 0 or self.attempts < self.best:
                    self.best = self.attempts
        self.render()

    def handle_key(self, key, state):
        if not state:
            return
        if self.won or not self.game_active:
            self.reset()
            self.render()

    def render(self):
        self._render_keys()
        self._render_screen()

    def _render_keys(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            if not self.game_active:
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_TITLE, "TEMP")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            elif self.won:
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_WIN, f"{self.target}C")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, (40, 40, 80), f"{self.attempts}try")
                else:
                    set_key(self.deck, key, COLOR_WIN, "")
            else:
                diff = abs(self.guess - self.target)
                if (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, (40, 40, 80), f"{self.guess}C")
                elif (c, r) == (0, 0):
                    set_key(self.deck, key, (40, 40, 80), f"#{self.attempts}")
                elif (c, r) == (mid_c, 0):
                    if diff == 0:
                        set_key(self.deck, key, (0, 255, 0), "=")
                    elif diff <= 2:
                        set_key(self.deck, key, (255, 50, 0), "HOT!")
                    elif diff <= 5:
                        set_key(self.deck, key, (255, 150, 0), "WARM")
                    elif diff <= 15:
                        set_key(self.deck, key, (0, 150, 200), "COOL")
                    else:
                        set_key(self.deck, key, (0, 60, 200), "COLD")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_screen(self):
        w, h = self.sw, self.sh
        img = Image.new("RGB", (w, h), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default(size=20)
            font_sm = ImageFont.load_default(size=14)
        except TypeError:
            font = ImageFont.load_default()
            font_sm = font

        if not self.game_active:
            draw.text((w // 2 - 70, h // 2 - 10), "THERMOMETER", fill=(200, 200, 200), font=font)
        elif self.won:
            draw.text((w // 2 - 40, h // 2 - 10), f"{self.target}°C!", fill=(0, 255, 0), font=font)
        else:
            # Draw thermometer bar
            margin = 40
            bar_w = w - margin * 2
            min_t, max_t = -30, 50
            range_t = max_t - min_t

            # Gradient bar
            for x in range(bar_w):
                pct = x / bar_w
                r = int(255 * pct)
                b = int(255 * (1 - pct))
                draw.line([(margin + x, 30), (margin + x, 60)], fill=(r, 0, b))

            # Guess marker
            g_pct = (self.guess - min_t) / range_t
            gx = margin + int(bar_w * g_pct)
            draw.polygon([(gx, 25), (gx - 5, 15), (gx + 5, 15)], fill=(255, 255, 255))
            draw.text((gx - 10, 2), f"{self.guess}°", fill=(255, 255, 255), font=font_sm)

            # Hint
            diff = abs(self.guess - self.target)
            arrow = ">" if self.guess < self.target else "<" if self.guess > self.target else "="
            draw.text((margin, 65), f"Guess: {self.guess}°C {arrow}", fill=(200, 200, 200), font=font_sm)
            draw.text((w - margin - 80, 65), f"Try #{self.attempts}", fill=(150, 150, 150), font=font_sm)

        set_screen(self.deck, img)


def main():
    streamdecks = DeviceManager().enumerate()
    deck = next((d for d in streamdecks if d.is_visual() and d.DIAL_COUNT and d.DIAL_COUNT > 0), None)
    if not deck:
        print("No Stream Deck + found.")
        sys.exit(1)
    deck.open()
    deck.reset()
    deck.set_brightness(80)
    print(f"Thermometer on {deck.deck_type()}")
    print("Turn dial to guess temperature. Click to submit.")
    game = Thermometer(deck)
    game.render()
    deck.set_dial_callback(lambda d, dial, evt, val: (game.lock.acquire(), game.handle_dial(dial, evt, val), game.lock.release()))
    deck.set_key_callback(lambda d, k, s: (game.lock.acquire(), game.handle_key(k, s), game.lock.release()) if s else None)
    try:
        while deck.is_open():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        with deck:
            deck.reset()
            deck.close()
        print(f"\nBest: {game.best} attempts")


if __name__ == "__main__":
    main()
