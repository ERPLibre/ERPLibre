#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Piano (SD+ dials + touchscreen).

Bottom row buttons = piano keys (white). Dials shift octave and volume.
Touchscreen shows keyboard and current note. Visual-only (no audio).
"""

import io
import os
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

NOTES = ["C", "D", "E", "F", "G", "A", "B"]
NOTE_COLORS = {
    "C": (255, 80, 80), "D": (255, 160, 0), "E": (255, 255, 0),
    "F": (0, 200, 0), "G": (0, 160, 255), "A": (100, 0, 255), "B": (200, 0, 200),
}
COLOR_EMPTY = (20, 20, 30)
COLOR_KEY_WHITE = (220, 220, 220)
COLOR_KEY_PRESSED = (100, 200, 255)
COLOR_TITLE = (0, 80, 160)


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 20 if len(text) <= 2 else 14
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


class Piano:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.octave = 4
        self.last_note = ""
        self.last_press_time = 0
        self.pressed = set()
        self.sw = deck.TOUCHSCREEN_PIXEL_WIDTH or deck.SCREEN_PIXEL_WIDTH or 800
        self.sh = deck.TOUCHSCREEN_PIXEL_HEIGHT or deck.SCREEN_PIXEL_HEIGHT or 100

    def handle_dial(self, dial, event, value):
        if event == DialEventType.TURN:
            if dial == 0:
                self.octave = max(1, min(8, self.octave + value))
        self.render()

    def handle_key(self, key, state):
        col = key % self.cols
        row = key // self.cols
        last_r = self.rows - 1

        if row == last_r and col < len(NOTES):
            if state:
                note = NOTES[col]
                self.last_note = f"{note}{self.octave}"
                self.last_press_time = time.monotonic()
                self.pressed.add(col)
            else:
                self.pressed.discard(col)
        self.render()

    def render(self):
        self._render_keys()
        self._render_screen()

    def _render_keys(self):
        last_r = self.rows - 1
        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            if r == last_r and c < len(NOTES):
                note = NOTES[c]
                if c in self.pressed:
                    set_key(self.deck, key, NOTE_COLORS[note], note)
                else:
                    set_key(self.deck, key, COLOR_KEY_WHITE, note)
            elif r == 0 and c == 0:
                set_key(self.deck, key, COLOR_TITLE, f"O:{self.octave}")
            elif r == 0 and c == self.cols - 1 and self.last_note:
                set_key(self.deck, key, NOTE_COLORS.get(self.last_note[0], COLOR_TITLE), self.last_note)
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_screen(self):
        img = Image.new("RGB", (self.sw, self.sh), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default(size=16)
            font_big = ImageFont.load_default(size=28)
        except TypeError:
            font = ImageFont.load_default()
            font_big = font

        # Draw piano keys on touchscreen
        key_w = self.sw // 7
        for i, note in enumerate(NOTES):
            x = i * key_w
            color = NOTE_COLORS[note] if i in self.pressed else (180, 180, 180)
            draw.rectangle([x + 1, 5, x + key_w - 1, self.sh - 5], fill=color, outline=(60, 60, 60))
            draw.text((x + key_w // 2 - 5, self.sh - 20), note, fill=(0, 0, 0), font=font)

        if self.last_note:
            elapsed = time.monotonic() - self.last_press_time
            if elapsed < 2.0:
                draw.text((self.sw // 2 - 20, 2), self.last_note, fill=(255, 255, 255), font=font_big)

        set_screen(self.deck, img)


def main():
    streamdecks = DeviceManager().enumerate()
    deck = next((d for d in streamdecks if d.is_visual() and d.DIAL_COUNT and d.DIAL_COUNT > 0), None)
    if not deck:
        deck = next((d for d in streamdecks if d.is_visual()), None)
    if not deck:
        print("No visual Stream Deck found.")
        sys.exit(1)
    deck.open()
    deck.reset()
    deck.set_brightness(80)
    print(f"Piano on {deck.deck_type()}")
    print("Bottom row = keys. Dial 1 = octave.")
    game = Piano(deck)
    game.render()

    def key_cb(d, k, s):
        with game.lock:
            game.handle_key(k, s)

    deck.set_key_callback(key_cb)
    if deck.DIAL_COUNT and deck.DIAL_COUNT > 0:
        deck.set_dial_callback(lambda d, dial, evt, val: (game.lock.acquire(), game.handle_dial(dial, evt, val), game.lock.release()))
    try:
        while deck.is_open():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        with deck:
            deck.reset()
            deck.close()


if __name__ == "__main__":
    main()
