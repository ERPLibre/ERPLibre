#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Color Mixer for Elgato Stream Deck + (dials + touchscreen).

3 dials = Red, Green, Blue. Mix to match the target color!
Touchscreen shows your color vs target. Click dial 4 to submit.
"""

import io
import math
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


class ColorMixer:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.target = (0, 0, 0)
        self.current = [128, 128, 128]  # R, G, B
        self.game_active = False
        self.won = False
        self.score = 0
        self.round = 0
        self.best_score = 0
        self.screen_w = deck.TOUCHSCREEN_PIXEL_WIDTH or deck.SCREEN_PIXEL_WIDTH or 800
        self.screen_h = deck.TOUCHSCREEN_PIXEL_HEIGHT or deck.SCREEN_PIXEL_HEIGHT or 100
        self.tolerance = 20

    def reset(self):
        self.target = (
            random.randint(4, 47) * 5,
            random.randint(4, 47) * 5,
            random.randint(4, 47) * 5,
        )
        self.current = [125, 125, 125]
        self.won = False
        self.round += 1
        self.game_active = True

    def _color_distance(self):
        return math.sqrt(
            sum((a - b) ** 2 for a, b in zip(self.current, self.target))
        )

    def _match_pct(self):
        max_dist = math.sqrt(3 * 255 ** 2)
        dist = self._color_distance()
        return max(0, (1 - dist / max_dist) * 100)

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
            if dial < 3:
                # R=0, G=1, B=2
                self.current[dial] = max(0, min(255, self.current[dial] + value * 5))
                self.render()
        elif event == DialEventType.PUSH and value:
            if dial == 3:
                # Submit
                dist = self._color_distance()
                if dist <= self.tolerance:
                    self.won = True
                    self.score += 1
                    if self.score > self.best_score:
                        self.best_score = self.score
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
                    set_key(self.deck, key, COLOR_TITLE, "COLOR")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        for key in range(self.cols * self.rows):
            r_pos = key // self.cols
            c = key % self.cols

            if r_pos == 0:
                # Target color
                set_key(self.deck, key, self.target, "TGT" if c == 0 else "")
            elif r_pos == last_r and c < 3:
                # Current R/G/B values
                labels = ["R", "G", "B"]
                val = self.current[c]
                component_color = [0, 0, 0]
                component_color[c] = val
                set_key(self.deck, key, tuple(component_color), f"{labels[c]}:{val}")
            elif r_pos == last_r and c == 3:
                # Submit button
                pct = self._match_pct()
                if self.won:
                    set_key(self.deck, key, COLOR_WIN, "OK!")
                else:
                    set_key(self.deck, key, (40, 40, 80), f"{pct:.0f}%")
            elif r_pos == last_r and c == self.cols - 1:
                set_key(self.deck, key, (40, 40, 80), f"S:{self.score}")
            else:
                # Current mixed color
                set_key(self.deck, key, tuple(self.current), "")

    def _render_screen(self):
        w, h = self.screen_w, self.screen_h
        img = Image.new("RGB", (w, h), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.load_default(size=20)
            font_sm = ImageFont.load_default(size=14)
        except TypeError:
            font = ImageFont.load_default()
            font_sm = font

        if not self.game_active:
            draw.text((w // 2 - 60, h // 2 - 10), "COLOR MIXER", fill=(200, 200, 200), font=font)
            set_screen(self.deck, img)
            return

        # Left half: target color
        draw.rectangle([0, 0, w // 2 - 2, h], fill=self.target)
        draw.text((5, 2), "TARGET", fill=(255, 255, 255), font=font_sm)

        # Right half: current color
        draw.rectangle([w // 2 + 2, 0, w, h], fill=tuple(self.current))
        draw.text((w // 2 + 5, 2), "YOURS", fill=(255, 255, 255), font=font_sm)

        # Separator
        draw.line([(w // 2, 0), (w // 2, h)], fill=(255, 255, 255), width=2)

        # Match percentage
        pct = self._match_pct()
        pct_text = f"{pct:.0f}% match"
        if self.won:
            pct_text = "PERFECT!"
        draw.text((w // 2 - 40, h - 18), pct_text, fill=(255, 255, 255), font=font_sm)

        # RGB values
        r, g, b = self.current
        draw.text((w // 2 + 5, h - 18), f"R:{r} G:{g} B:{b}", fill=(200, 200, 200), font=font_sm)

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

    print(f"Color Mixer on {deck.deck_type()}")
    print("Dial 1=Red, 2=Green, 3=Blue. Dial 4=Submit.")
    print("Match the target color! Ctrl+C to quit.")

    game = ColorMixer(deck)
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
        print(f"\nScore: {game.score} | Best: {game.best_score}")


if __name__ == "__main__":
    main()
