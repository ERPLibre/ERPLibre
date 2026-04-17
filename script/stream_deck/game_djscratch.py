#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""DJ Scratch (SD+ dials + touchscreen).

Turn dials to scratch virtual vinyl. Speed and direction shown on
touchscreen as waveform. Click dial to switch track style. Buttons
play tones matching the waveform. Press button 0-3 to hear the sound!
"""

import io
import math
import os
import random
import struct
import subprocess
import sys
import threading
import time
import wave

try:
    from PIL import Image, ImageDraw, ImageFont
    from StreamDeck.DeviceManager import DeviceManager
    from StreamDeck.Devices.StreamDeck import DialEventType
    from StreamDeck.ImageHelpers import PILHelper
    from StreamDeck.Transport.Transport import TransportError
except ImportError as e:
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

STYLES = ["Sine", "Square", "Saw", "Noise"]
STYLE_COLORS = [(0, 200, 255), (255, 100, 0), (0, 255, 100), (255, 0, 200)]
BASE_FREQS = [261.63, 329.63, 392.00, 523.25]  # C4, E4, G4, C5
SAMPLE_RATE = 22050
DURATION = 0.3
VOLUME = 0.5


def generate_tone(style, freq, duration=DURATION, rate=SAMPLE_RATE):
    """Generate raw PCM samples for a tone."""
    n_samples = int(rate * duration)
    samples = []
    for i in range(n_samples):
        t = i / rate
        if style == 0:  # Sine
            val = math.sin(2 * math.pi * freq * t)
        elif style == 1:  # Square
            val = 1.0 if math.sin(2 * math.pi * freq * t) > 0 else -1.0
        elif style == 2:  # Saw
            val = 2.0 * (freq * t % 1.0) - 1.0
        else:  # Noise
            val = random.uniform(-1, 1)
        # Envelope (fade in/out)
        env = 1.0
        fade = int(n_samples * 0.1)
        if i < fade:
            env = i / fade
        elif i > n_samples - fade:
            env = (n_samples - i) / fade
        samples.append(int(val * env * VOLUME * 32767))
    return samples


def samples_to_wav(samples, rate=SAMPLE_RATE):
    """Convert samples to WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(
            struct.pack(f"<{len(samples)}h", *samples)
        )
    return buf.getvalue()


def play_wav_bytes(wav_bytes):
    """Play WAV bytes directly on laptop speaker via aplay or pw-play."""
    for cmd in [
        ["aplay", "-q", "-"],
        ["pw-play", "-"],
        ["paplay", "--raw", "--format=s16le", "--rate=22050", "--channels=1"],
    ]:
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc.communicate(input=wav_bytes)
            return True
        except FileNotFoundError:
            continue
    return False


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


class DJScratch:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.running = True
        self.num_dials = min(deck.DIAL_COUNT or 4, 4)
        self.speeds = [0.0] * 4
        self.styles = [0, 1, 2, 3]
        self.phase = [0.0] * 4
        self.freqs = list(BASE_FREQS)
        self.playing = [False] * 4
        self.sw = deck.TOUCHSCREEN_PIXEL_WIDTH or deck.SCREEN_PIXEL_WIDTH or 800
        self.sh = deck.TOUCHSCREEN_PIXEL_HEIGHT or deck.SCREEN_PIXEL_HEIGHT or 100

    def handle_dial(self, dial, event, value):
        if dial >= 4:
            return
        if event == DialEventType.TURN:
            self.speeds[dial] = value * 2.0
            # Adjust frequency with dial turn
            self.freqs[dial] = max(
                80, min(2000, self.freqs[dial] + value * 20)
            )
        elif event == DialEventType.PUSH and value:
            self.styles[dial] = (self.styles[dial] + 1) % len(STYLES)

    def handle_key(self, key, state):
        col = key % self.cols
        row = key // self.cols
        last_r = self.rows - 1

        if row == last_r and col < 4:
            if state:
                self.playing[col] = True
                # Play tone in background thread
                threading.Thread(
                    target=self._play_tone,
                    args=(col,),
                    daemon=True,
                ).start()
            else:
                self.playing[col] = False

    def _play_tone(self, channel):
        """Generate and play a tone for the given channel."""
        style = self.styles[channel]
        freq = self.freqs[channel]
        samples = generate_tone(style, freq)
        wav_data = samples_to_wav(samples)
        play_wav_bytes(wav_data)

    def _wave(self, style, x, phase):
        t = x * 0.05 + phase
        if style == 0:
            return math.sin(t)
        elif style == 1:
            return 1.0 if math.sin(t) > 0 else -1.0
        elif style == 2:
            return (t % (2 * math.pi)) / math.pi - 1.0
        else:
            return random.uniform(-1, 1)

    def tick(self):
        for i in range(4):
            self.phase[i] += self.speeds[i] * 0.3
            self.speeds[i] *= 0.95

    def render(self):
        self._render_keys()
        self._render_screen()

    def _render_keys(self):
        last_r = self.rows - 1
        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            if r == last_r and c < 4:
                style = self.styles[c]
                freq_hz = int(self.freqs[c])
                if self.playing[c]:
                    color = STYLE_COLORS[style]
                    text = f"{freq_hz}"
                else:
                    bright = min(255, int(abs(self.speeds[c]) * 30))
                    color = tuple(
                        min(255, v * max(40, bright) // 255)
                        for v in STYLE_COLORS[style]
                    )
                    text = STYLES[style][:3]
                set_key(self.deck, key, color, text)
            elif r == 0 and c < 4:
                freq_hz = int(self.freqs[c])
                set_key(self.deck, key, (40, 40, 80), f"{freq_hz}")
            else:
                set_key(self.deck, key, (20, 20, 30), "")

    def _render_screen(self):
        img = Image.new("RGB", (self.sw, self.sh), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        section = self.sw // 4
        mid_y = self.sh // 2
        for d in range(4):
            x_off = d * section
            color = STYLE_COLORS[self.styles[d]]
            if self.playing[d]:
                color = (
                    min(255, color[0] + 60),
                    min(255, color[1] + 60),
                    min(255, color[2] + 60),
                )
            amp = min(mid_y - 5, int(abs(self.speeds[d]) * 5) + 10)
            if self.playing[d]:
                amp = mid_y - 5
            prev_y = mid_y
            for x in range(section - 4):
                val = self._wave(self.styles[d], x, self.phase[d])
                y = mid_y - int(val * amp)
                y = max(2, min(self.sh - 2, y))
                draw.line(
                    [(x_off + x, prev_y), (x_off + x + 1, y)],
                    fill=color,
                    width=2 if self.playing[d] else 1,
                )
                prev_y = y
            if d < 3:
                draw.line(
                    [(x_off + section - 2, 0), (x_off + section - 2, self.sh)],
                    fill=(40, 40, 40),
                )

            # Frequency label
            try:
                font_sm = ImageFont.load_default(size=10)
            except TypeError:
                font_sm = ImageFont.load_default()
            draw.text(
                (x_off + 3, 2),
                f"{int(self.freqs[d])}Hz",
                fill=(150, 150, 150),
                font=font_sm,
            )

        set_screen(self.deck, img)

    def loop(self):
        while self.running and self.deck.is_open():
            with self.lock:
                self.tick()
                self.render()
            time.sleep(0.05)


def main():
    streamdecks = DeviceManager().enumerate()
    deck = next(
        (
            d
            for d in streamdecks
            if d.is_visual() and d.DIAL_COUNT and d.DIAL_COUNT > 0
        ),
        None,
    )
    if not deck:
        print("No Stream Deck + found.")
        sys.exit(1)
    deck.open()
    deck.reset()
    deck.set_brightness(80)
    print(f"DJ Scratch on {deck.deck_type()}")
    print("Turn dials to scratch + change frequency.")
    print("Click dial to change waveform (Sine/Square/Saw/Noise).")
    print("Press bottom buttons 0-3 to PLAY the tone!")

    game = DJScratch(deck)
    game.render()

    def dial_cb(d, dial, evt, val):
        with game.lock:
            game.handle_dial(dial, evt, val)

    def key_cb(d, k, s):
        with game.lock:
            game.handle_key(k, s)

    deck.set_dial_callback(dial_cb)
    deck.set_key_callback(key_cb)

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


if __name__ == "__main__":
    main()
