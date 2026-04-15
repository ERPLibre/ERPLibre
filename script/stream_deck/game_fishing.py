#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Fishing game (SD+ dials + touchscreen).

Click dial to cast. When fish bites (touchscreen flash), turn dial to
reel in! Too fast = line snaps. Too slow = fish escapes. Buttons show
catch count and fish type.
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

FISH = [("Trout", 1), ("Bass", 2), ("Salmon", 3), ("Tuna", 5), ("Shark", 10)]
STATE_IDLE = "idle"
STATE_CAST = "cast"
STATE_BITE = "bite"
STATE_REEL = "reel"
STATE_CAUGHT = "caught"
STATE_LOST = "lost"


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 16 if len(text) <= 4 else 11
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


class Fishing:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.running = True
        self.state = STATE_IDLE
        self.score = 0
        self.catches = 0
        self.current_fish = None
        self.reel_progress = 0
        self.reel_target = 0
        self.tension = 0
        self.bite_timer = 0
        self.result_timer = 0
        self.sw = deck.TOUCHSCREEN_PIXEL_WIDTH or deck.SCREEN_PIXEL_WIDTH or 800
        self.sh = deck.TOUCHSCREEN_PIXEL_HEIGHT or deck.SCREEN_PIXEL_HEIGHT or 100

    def handle_dial(self, dial, event, value):
        if event == DialEventType.PUSH and value:
            if self.state == STATE_IDLE:
                self.state = STATE_CAST
                self.bite_timer = time.monotonic() + random.uniform(1.5, 4.0)
                self.current_fish = random.choice(FISH)
                self.reel_progress = 0
                self.reel_target = 20 + self.current_fish[1] * 5
                self.tension = 0
            elif self.state in (STATE_CAUGHT, STATE_LOST):
                self.state = STATE_IDLE
        elif event == DialEventType.TURN and self.state == STATE_REEL:
            reel = abs(value)
            self.reel_progress += reel
            self.tension += reel * 2
            if self.tension > 20:
                self.state = STATE_LOST
                self.result_timer = time.monotonic() + 2.0

    def tick(self):
        now = time.monotonic()
        if self.state == STATE_CAST:
            if now >= self.bite_timer:
                self.state = STATE_BITE
                self.bite_timer = now + 2.0
        elif self.state == STATE_BITE:
            if now >= self.bite_timer:
                self.state = STATE_LOST
                self.result_timer = now + 2.0
        elif self.state == STATE_REEL:
            self.tension = max(0, self.tension - 1)
            if self.reel_progress >= self.reel_target:
                self.state = STATE_CAUGHT
                self.score += self.current_fish[1]
                self.catches += 1
                self.result_timer = now + 2.0
        elif self.state in (STATE_CAUGHT, STATE_LOST):
            if now >= self.result_timer:
                self.state = STATE_IDLE

    def handle_touch(self, evt_type, value):
        if self.state == STATE_BITE:
            self.state = STATE_REEL
            self.tension = 0

    def render(self):
        self._render_keys()
        self._render_screen()

    def _render_keys(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            if (c, r) == (0, 0):
                set_key(self.deck, key, (40, 40, 80), f"S:{self.score}")
            elif (c, r) == (self.cols - 1, 0):
                set_key(self.deck, key, (40, 40, 80), f"C:{self.catches}")
            elif (c, r) == (mid_c, 0) and self.current_fish and self.state in (STATE_REEL, STATE_CAUGHT):
                set_key(self.deck, key, (0, 120, 60), self.current_fish[0][:4])
            elif (c, r) == (mid_c, last_r):
                states = {STATE_IDLE: "CAST", STATE_CAST: "...", STATE_BITE: "BITE!", STATE_REEL: "REEL", STATE_CAUGHT: "GOT!", STATE_LOST: "LOST"}
                colors = {STATE_IDLE: (0, 80, 160), STATE_CAST: (60, 60, 60), STATE_BITE: (255, 200, 0), STATE_REEL: (0, 160, 0), STATE_CAUGHT: (0, 200, 60), STATE_LOST: (200, 0, 0)}
                set_key(self.deck, key, colors.get(self.state, (40, 40, 80)), states.get(self.state, ""))
            else:
                set_key(self.deck, key, (0, 30, 60), "")

    def _render_screen(self):
        img = Image.new("RGB", (self.sw, self.sh), (0, 40, 80))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default(size=20)
            font_sm = ImageFont.load_default(size=14)
        except TypeError:
            font = ImageFont.load_default()
            font_sm = font

        # Water waves
        for x in range(0, self.sw, 3):
            y = self.sh - 10 + int(5 * math.sin(x * 0.03 + time.monotonic() * 2))
            draw.line([(x, y), (x + 2, y)], fill=(0, 60, 120))

        if self.state == STATE_IDLE:
            draw.text((self.sw // 2 - 60, self.sh // 2 - 10), "Click to cast!", fill=(200, 200, 200), font=font)
        elif self.state == STATE_CAST:
            draw.text((self.sw // 2 - 40, self.sh // 2 - 10), "Waiting...", fill=(150, 150, 150), font=font)
            # Bobber
            bx = self.sw // 2
            draw.ellipse([bx - 5, 20, bx + 5, 30], fill=(255, 0, 0))
        elif self.state == STATE_BITE:
            draw.text((self.sw // 2 - 80, self.sh // 2 - 10), "FISH! TAP SCREEN!", fill=(255, 255, 0), font=font)
        elif self.state == STATE_REEL:
            pct = min(1.0, self.reel_progress / max(1, self.reel_target))
            bar_w = int((self.sw - 40) * pct)
            draw.rectangle([20, 10, 20 + bar_w, 30], fill=(0, 200, 60))
            draw.rectangle([20, 10, self.sw - 20, 30], outline=(100, 100, 100))
            # Tension bar
            t_pct = min(1.0, self.tension / 20)
            t_color = (int(255 * t_pct), int(255 * (1 - t_pct)), 0)
            draw.rectangle([20, 40, 20 + int((self.sw - 40) * t_pct), 55], fill=t_color)
            draw.text((20, 60), "Tension", fill=(200, 200, 200), font=font_sm)
            draw.text((self.sw - 80, 60), self.current_fish[0] if self.current_fish else "", fill=(200, 200, 200), font=font_sm)
        elif self.state == STATE_CAUGHT:
            name = self.current_fish[0] if self.current_fish else "Fish"
            pts = self.current_fish[1] if self.current_fish else 0
            draw.text((self.sw // 2 - 60, self.sh // 2 - 10), f"Caught {name}! +{pts}", fill=(0, 255, 0), font=font)
        elif self.state == STATE_LOST:
            draw.text((self.sw // 2 - 40, self.sh // 2 - 10), "Got away!", fill=(255, 0, 0), font=font)

        set_screen(self.deck, img)

    def loop(self):
        while self.running and self.deck.is_open():
            with self.lock:
                self.tick()
                self.render()
            time.sleep(0.1)


import math


def main():
    streamdecks = DeviceManager().enumerate()
    deck = next((d for d in streamdecks if d.is_visual() and d.DIAL_COUNT and d.DIAL_COUNT > 0), None)
    if not deck:
        print("No Stream Deck + found.")
        sys.exit(1)
    deck.open()
    deck.reset()
    deck.set_brightness(80)
    print(f"Fishing on {deck.deck_type()}")
    print("Click dial=cast. Tap screen when fish bites. Turn dial to reel.")
    game = Fishing(deck)
    game.render()

    def dial_cb(d, dial, evt, val):
        with game.lock:
            game.handle_dial(dial, evt, val)

    def touch_cb(d, evt, val):
        with game.lock:
            game.handle_touch(evt, val)

    deck.set_dial_callback(dial_cb)
    if deck.DECK_TOUCH:
        deck.set_touchscreen_callback(touch_cb)
    deck.set_key_callback(lambda d, k, s: None)
    t = threading.Thread(target=game.loop, daemon=True)
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
        print(f"\nCatches: {game.catches} | Score: {game.score}")


if __name__ == "__main__":
    main()
