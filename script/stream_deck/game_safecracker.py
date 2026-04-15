#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Safe Cracker for Elgato Stream Deck + (dials + touchscreen).

Turn the 4 dials to find the secret 4-digit combination.
Each dial = one digit (0-9). Touchscreen shows hot/cold feedback.
Press a dial to lock it. Lock all 4 correctly to win!
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
    from StreamDeck.Devices.StreamDeck import DialEventType, TouchscreenEventType
    from StreamDeck.ImageHelpers import PILHelper
    from StreamDeck.Transport.Transport import TransportError
except ImportError as e:
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

COLOR_LOCKED = (0, 180, 0)
COLOR_UNLOCKED = (60, 60, 80)
COLOR_TITLE = (0, 80, 160)
COLOR_WIN = (0, 220, 60)
COLOR_EMPTY = (20, 20, 30)


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 22 if len(text) <= 2 else (16 if len(text) <= 4 else 12)
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
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="JPEG")
    img_bytes = img_bytes.getvalue()
    try:
        with deck:
            w = deck.TOUCHSCREEN_PIXEL_WIDTH or deck.SCREEN_PIXEL_WIDTH or 800
            h = deck.TOUCHSCREEN_PIXEL_HEIGHT or deck.SCREEN_PIXEL_HEIGHT or 100
            if deck.DECK_TOUCH:
                deck.set_touchscreen_image(img_bytes, 0, 0, w, h)
            else:
                deck.set_screen_image(img_bytes)
    except (TransportError, AttributeError):
        pass


class SafeCracker:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.secret = [0, 0, 0, 0]
        self.guess = [0, 0, 0, 0]
        self.locked = [False, False, False, False]
        self.num_dials = min(deck.DIAL_COUNT, 4) if deck.DIAL_COUNT else 4
        self.game_active = False
        self.won = False
        self.attempts = 0
        self.best = 0
        self.screen_w = deck.TOUCHSCREEN_PIXEL_WIDTH or deck.SCREEN_PIXEL_WIDTH or 800
        self.screen_h = deck.TOUCHSCREEN_PIXEL_HEIGHT or deck.SCREEN_PIXEL_HEIGHT or 100

    def reset(self):
        self.secret = [random.randint(0, 9) for _ in range(4)]
        self.guess = [0, 0, 0, 0]
        self.locked = [False, False, False, False]
        self.won = False
        self.attempts = 0
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

        if dial >= 4:
            return

        if event == DialEventType.TURN:
            if not self.locked[dial]:
                self.guess[dial] = (self.guess[dial] + value) % 10
        elif event == DialEventType.PUSH and value:
            if not self.locked[dial]:
                # Lock this dial
                self.locked[dial] = True
                self.attempts += 1
                # Check if correct
                if self.guess[dial] != self.secret[dial]:
                    # Wrong! Unlock all
                    self.locked = [False, False, False, False]
                elif all(self.locked):
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

        if not self.game_active:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_TITLE, "SAFE")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and self.best:
                    set_key(self.deck, key, (40, 40, 80), f"B:{self.best}")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        if self.won:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_WIN, "OPEN")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, (40, 40, 80), f"{self.attempts}try")
                else:
                    set_key(self.deck, key, COLOR_WIN, "")
            return

        # Show dial values on bottom row keys (aligned with dials)
        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            if r == last_r and c < 4:
                val = str(self.guess[c])
                if self.locked[c]:
                    set_key(self.deck, key, COLOR_LOCKED, val)
                else:
                    set_key(self.deck, key, COLOR_UNLOCKED, val)
            elif r == 0 and c < 4:
                # Hint: distance indicator
                diff = abs(self.guess[c] - self.secret[c])
                if diff == 0:
                    set_key(self.deck, key, (0, 200, 0), "=")
                elif diff <= 1:
                    set_key(self.deck, key, (255, 80, 0), "HOT")
                elif diff <= 3:
                    set_key(self.deck, key, (200, 200, 0), "WARM")
                else:
                    set_key(self.deck, key, (0, 100, 200), "COLD")
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_screen(self):
        w, h = self.screen_w, self.screen_h
        img = Image.new("RGB", (w, h), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.load_default(size=24)
            font_sm = ImageFont.load_default(size=16)
        except TypeError:
            font = ImageFont.load_default()
            font_sm = font

        if not self.game_active:
            draw.text((w // 2 - 80, h // 2 - 12), "SAFE CRACKER", fill=(200, 200, 200), font=font)
            set_screen(self.deck, img)
            return

        if self.won:
            draw.text((w // 2 - 50, h // 2 - 12), "CRACKED!", fill=(0, 255, 0), font=font)
            set_screen(self.deck, img)
            return

        # Draw 4 dial sections with bars
        section_w = w // 4
        for i in range(4):
            x = i * section_w
            diff = abs(self.guess[i] - self.secret[i])
            max_diff = 9

            # Temperature bar (inverted: closer = more filled)
            fill_pct = 1.0 - (diff / max_diff)
            bar_h = int(h * 0.6 * fill_pct)
            bar_y = h - bar_h - 5

            # Color gradient: cold(blue) -> warm(yellow) -> hot(red)
            if diff == 0:
                bar_color = (0, 255, 0)
            elif diff <= 1:
                bar_color = (255, 80, 0)
            elif diff <= 3:
                bar_color = (220, 200, 0)
            else:
                bar_color = (0, 80, 200)

            draw.rectangle(
                [x + 10, bar_y, x + section_w - 10, h - 5],
                fill=bar_color,
            )

            # Digit text
            digit = str(self.guess[i])
            bbox = draw.textbbox((0, 0), digit, font=font)
            tw = bbox[2] - bbox[0]
            draw.text((x + (section_w - tw) // 2, 2), digit, fill=(255, 255, 255), font=font)

            if self.locked[i]:
                draw.text((x + 10, h - 18), "LOCK", fill=(0, 255, 0), font=font_sm)

        set_screen(self.deck, img)


def main():
    streamdecks = DeviceManager().enumerate()
    deck = None
    for d in streamdecks:
        if d.is_visual() and d.DIAL_COUNT and d.DIAL_COUNT > 0:
            deck = d
            break

    if not deck:
        print("No Stream Deck + found (need dials).")
        sys.exit(1)

    deck.open()
    deck.reset()
    deck.set_brightness(80)

    print(f"Safe Cracker on {deck.deck_type()}")
    print("Turn dials to guess 4 digits. Click dial to lock.")
    print("Wrong lock = all unlock. Ctrl+C to quit.")

    game = SafeCracker(deck)
    game.render()

    def dial_cb(d, dial, event, value):
        with game.lock:
            game.handle_dial(dial, event, value)

    def key_cb(d, key, state):
        with game.lock:
            game.handle_key(key, state)

    deck.set_dial_callback(dial_cb)
    deck.set_key_callback(key_cb)

    try:
        while deck.is_open():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        with deck:
            deck.reset()
            deck.close()
        print(f"\nAttempts: {game.attempts} | Best: {game.best}")


if __name__ == "__main__":
    main()
