#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Slot Machine (SD+ dials + touchscreen).

Each dial = one reel. Turn to spin, click to stop.
Touchscreen shows spinning animation. Match symbols to win!
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

GAME_META = {
    "name": "Slot Machine",
    "category": "arcade",
    "multiplayer": False,
    "sdplus": True,
    "description": "Spin reels with dials, stop to match symbols!",
    "icon": "slots"
}

SYMBOLS = ["7", "BAR", "X", "O", "$", "#", "W"]
SYMBOL_COLORS = {
    "7": (255, 0, 0),
    "BAR": (200, 160, 0),
    "X": (0, 180, 0),
    "O": (0, 100, 220),
    "$": (0, 200, 60),
    "#": (180, 0, 180),
    "W": (255, 255, 0),
}
COLOR_SPINNING = (80, 80, 80)
COLOR_STOPPED = (40, 40, 50)
COLOR_WIN = (0, 200, 60)
COLOR_JACKPOT = (255, 215, 0)
COLOR_EMPTY = (20, 20, 30)
COLOR_TITLE = (0, 80, 160)


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


class SlotMachine:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.num_reels = min(deck.DIAL_COUNT or 4, 4)
        self.reels = [0] * self.num_reels
        self.spinning = [False] * self.num_reels
        self.stopped = [True] * self.num_reels
        self.credits = 100
        self.bet = 10
        self.game_active = False
        self.won = False
        self.win_amount = 0
        self.running = True
        self.screen_w = deck.TOUCHSCREEN_PIXEL_WIDTH or deck.SCREEN_PIXEL_WIDTH or 800
        self.screen_h = deck.TOUCHSCREEN_PIXEL_HEIGHT or deck.SCREEN_PIXEL_HEIGHT or 100

    def reset(self):
        self.reels = [0] * self.num_reels
        self.spinning = [False] * self.num_reels
        self.stopped = [True] * self.num_reels
        self.won = False
        self.win_amount = 0
        self.game_active = True

    def spin_all(self):
        """Start spinning all reels."""
        if self.credits < self.bet:
            return
        self.credits -= self.bet
        self.won = False
        self.win_amount = 0
        for i in range(self.num_reels):
            self.spinning[i] = True
            self.stopped[i] = False

    def handle_dial(self, dial, event, value):
        if dial >= self.num_reels:
            return

        if not self.game_active:
            self.reset()
            self.render()
            return

        if event == DialEventType.PUSH and value:
            if all(self.stopped):
                # All stopped — spin again
                self.spin_all()
            elif self.spinning[dial]:
                # Stop this reel
                self.spinning[dial] = False
                self.stopped[dial] = True
                # Check win when all stopped
                if all(self.stopped):
                    self._check_win()
        elif event == DialEventType.TURN and not self.spinning[dial] and all(self.stopped):
            # Adjust bet when idle
            self.bet = max(1, min(self.credits, self.bet + value))

        self.render()

    def handle_key(self, key, state):
        if not state:
            return
        if not self.game_active:
            self.reset()
        elif all(self.stopped):
            self.spin_all()
        self.render()

    def _check_win(self):
        symbols = [SYMBOLS[self.reels[i] % len(SYMBOLS)] for i in range(self.num_reels)]
        if len(set(symbols)) == 1:
            if symbols[0] == "7":
                self.win_amount = self.bet * 10
            elif symbols[0] == "$":
                self.win_amount = self.bet * 7
            else:
                self.win_amount = self.bet * 5
            self.won = True
        elif len(set(symbols)) == 2:
            self.win_amount = self.bet * 2
            self.won = True
        self.credits += self.win_amount

    def spin_loop(self):
        """Background thread to animate spinning reels."""
        while self.running and self.deck.is_open():
            with self.lock:
                changed = False
                for i in range(self.num_reels):
                    if self.spinning[i]:
                        self.reels[i] = (self.reels[i] + random.randint(1, 3)) % len(SYMBOLS)
                        changed = True
                if changed:
                    self.render()
            time.sleep(0.1)

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
                    set_key(self.deck, key, COLOR_TITLE, "SLOTS")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "SPIN")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols

            if r == last_r and c < self.num_reels:
                sym = SYMBOLS[self.reels[c] % len(SYMBOLS)]
                if self.spinning[c]:
                    set_key(self.deck, key, COLOR_SPINNING, sym)
                elif self.won and self.win_amount > 0:
                    set_key(self.deck, key, SYMBOL_COLORS.get(sym, COLOR_WIN), sym)
                else:
                    set_key(self.deck, key, SYMBOL_COLORS.get(sym, COLOR_STOPPED), sym)
            elif r == 0 and c == 0:
                set_key(self.deck, key, (40, 40, 80), f"${self.credits}")
            elif r == 0 and c == self.cols - 1:
                set_key(self.deck, key, (40, 40, 80), f"B:{self.bet}")
            elif r == 0 and c == mid_c and self.won:
                set_key(self.deck, key, COLOR_JACKPOT if self.win_amount >= self.bet * 5 else COLOR_WIN, f"+{self.win_amount}")
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_screen(self):
        w, h = self.screen_w, self.screen_h
        img = Image.new("RGB", (w, h), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.load_default(size=28)
            font_sm = ImageFont.load_default(size=16)
        except TypeError:
            font = ImageFont.load_default()
            font_sm = font

        if not self.game_active:
            draw.text((w // 2 - 80, h // 2 - 14), "SLOT MACHINE", fill=(255, 215, 0), font=font)
            set_screen(self.deck, img)
            return

        section_w = w // self.num_reels
        for i in range(self.num_reels):
            x = i * section_w
            sym = SYMBOLS[self.reels[i] % len(SYMBOLS)]
            color = SYMBOL_COLORS.get(sym, (200, 200, 200))

            if self.spinning[i]:
                # Spinning effect — multiple symbols blurred
                for offset in range(-2, 3):
                    idx = (self.reels[i] + offset) % len(SYMBOLS)
                    s = SYMBOLS[idx]
                    alpha = max(50, 255 - abs(offset) * 80)
                    y_off = h // 2 - 14 + offset * 20
                    if 0 <= y_off < h - 10:
                        c = tuple(min(255, v * alpha // 255) for v in color)
                        draw.text((x + section_w // 2 - 10, y_off), s, fill=c, font=font_sm)
            else:
                bbox = draw.textbbox((0, 0), sym, font=font)
                tw = bbox[2] - bbox[0]
                draw.text((x + (section_w - tw) // 2, h // 2 - 14), sym, fill=color, font=font)

            # Separator
            if i < self.num_reels - 1:
                draw.line([(x + section_w, 5), (x + section_w, h - 5)], fill=(80, 80, 80), width=2)

        if self.won and self.win_amount > 0:
            text = f"WIN +{self.win_amount}!" if self.win_amount < self.bet * 5 else "JACKPOT!"
            draw.text((w // 2 - 40, 2), text, fill=(255, 255, 0), font=font_sm)

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

    print(f"Slot Machine on {deck.deck_type()}")
    print("Click any dial to spin. Click spinning dial to stop.")
    print("Turn dial to adjust bet. Ctrl+C to quit.")

    game = SlotMachine(deck)
    game.render()

    def dial_cb(d, dial, event, value):
        with game.lock:
            game.handle_dial(dial, event, value)

    def key_cb(d, key, state):
        with game.lock:
            game.handle_key(key, state)

    deck.set_dial_callback(dial_cb)
    deck.set_key_callback(key_cb)

    spin_thread = threading.Thread(target=game.spin_loop, daemon=True)
    spin_thread.start()

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
        print(f"\nCredits: {game.credits}")



if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
