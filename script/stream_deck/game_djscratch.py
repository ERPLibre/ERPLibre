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
    def __init__(self, deck, sampler_deck=None):
        self.deck = deck
        self.sampler_deck = sampler_deck
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
        # Sampler state (deck 2)
        self.record_mode = False
        self.waiting_assign = -1  # key on sampler waiting for note
        self.sampler_map = {}  # key -> (style, freq) tuple
        self.sampler_playing = set()
        if sampler_deck:
            sr, sc = sampler_deck.key_layout()
            self.sampler_cols = sc
            self.sampler_rows = sr
            self.sampler_total = sc * sr
        else:
            self.sampler_cols = 0
            self.sampler_rows = 0
            self.sampler_total = 0

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

    def handle_key(self, key, state, deck_index=0):
        if deck_index == 1:
            self._handle_sampler_key(key, state)
            return

        col = key % self.cols
        row = key // self.cols
        last_r = self.rows - 1

        if row == last_r and col < 4:
            # If sampler is waiting for a note assignment, assign it
            if self.waiting_assign >= 0 and state:
                self.sampler_map[self.waiting_assign] = (
                    self.styles[col],
                    self.freqs[col],
                )
                print(
                    f"Assigned channel {col} "
                    f"({STYLES[self.styles[col]]} {int(self.freqs[col])}Hz) "
                    f"to sampler key {self.waiting_assign}"
                )
                self.waiting_assign = -1
                self._render_sampler()
                return

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
        self._play_sound(style, freq)

    def _play_sound(self, style, freq):
        """Generate and play a specific tone."""
        samples = generate_tone(style, freq)
        wav_data = samples_to_wav(samples)
        play_wav_bytes(wav_data)

    def _handle_sampler_key(self, key, state):
        """Handle key press on the sampler (deck 2)."""
        if not state:
            self.sampler_playing.discard(key)
            self._render_sampler()
            return

        # Button 0 = toggle record mode
        if key == 0:
            if self.record_mode:
                self.record_mode = False
                self.waiting_assign = -1
                print("Record mode OFF")
            else:
                self.record_mode = True
                self.waiting_assign = -1
                print("Record mode ON - press a sampler button to assign")
            self._render_sampler()
            return

        if self.record_mode:
            # Select this button for assignment
            self.waiting_assign = key
            print(
                f"Sampler key {key} selected - now press a sound button "
                f"(0-3) on deck 1 to assign"
            )
            self._render_sampler()
        else:
            # Play assigned sound
            if key in self.sampler_map:
                style, freq = self.sampler_map[key]
                self.sampler_playing.add(key)
                self._render_sampler()
                threading.Thread(
                    target=self._play_sampler_sound,
                    args=(key, style, freq),
                    daemon=True,
                ).start()

    def _play_sampler_sound(self, key, style, freq):
        """Play a sampler sound and update display."""
        self._play_sound(style, freq)
        self.sampler_playing.discard(key)
        self._render_sampler()

    def _render_sampler(self):
        """Render the sampler deck (deck 2)."""
        if not self.sampler_deck:
            return
        deck = self.sampler_deck
        for key in range(self.sampler_total):
            r = key // self.sampler_cols
            c = key % self.sampler_cols

            if key == 0:
                # Record button
                if self.record_mode:
                    set_key(deck, key, (220, 0, 0), "REC")
                else:
                    set_key(deck, key, (80, 0, 0), "REC")
            elif key == self.waiting_assign:
                # Waiting for note assignment - blink
                set_key(deck, key, (220, 180, 0), "?")
            elif key in self.sampler_map:
                style, freq = self.sampler_map[key]
                color = STYLE_COLORS[style]
                if key in self.sampler_playing:
                    # Playing - full brightness
                    set_key(deck, key, color, f"{int(freq)}")
                else:
                    # Assigned - dim
                    dim = (color[0] // 3, color[1] // 3, color[2] // 3)
                    set_key(
                        deck, key, dim,
                        STYLES[style][:3],
                    )
            else:
                if self.record_mode:
                    set_key(deck, key, (30, 30, 40), "+")
                else:
                    set_key(deck, key, (20, 20, 30), "")

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
    visual = [d for d in streamdecks if d.is_visual()]

    # Find SD+ (with dials) as main deck
    main_deck = next(
        (d for d in visual if d.DIAL_COUNT and d.DIAL_COUNT > 0), None
    )
    if not main_deck:
        print("No Stream Deck + found.")
        sys.exit(1)

    # Find second deck as sampler (any visual deck)
    sampler_deck = None
    for d in visual:
        if d is not main_deck:
            sampler_deck = d
            break

    for d in visual:
        d.open()
        d.reset()
        d.set_brightness(80)

    print(f"DJ Scratch on {main_deck.deck_type()}")
    print("Turn dials to scratch + change frequency.")
    print("Click dial to change waveform (Sine/Square/Saw/Noise).")
    print("Press bottom buttons 0-3 to PLAY the tone!")

    if sampler_deck:
        sr, sc = sampler_deck.key_layout()
        print(f"\nSAMPLER: {sampler_deck.deck_type()} ({sc}x{sr})")
        print("  Button 0 = toggle RECORD mode")
        print("  Record mode: press sampler button, then press sound 0-3")
        print("  Play mode: press assigned button to play sound")

    game = DJScratch(main_deck, sampler_deck=sampler_deck)
    game.render()
    if sampler_deck:
        game._render_sampler()

    def dial_cb(d, dial, evt, val):
        with game.lock:
            game.handle_dial(dial, evt, val)

    def key_cb(d, k, s):
        with game.lock:
            game.handle_key(k, s, deck_index=0)

    main_deck.set_dial_callback(dial_cb)
    main_deck.set_key_callback(key_cb)

    if sampler_deck:
        def sampler_key_cb(d, k, s):
            with game.lock:
                game.handle_key(k, s, deck_index=1)
        sampler_deck.set_key_callback(sampler_key_cb)

    t = threading.Thread(target=game.loop, daemon=True)
    t.start()

    all_decks = [main_deck] + ([sampler_deck] if sampler_deck else [])
    try:
        while all(d.is_open() for d in all_decks):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        game.running = False
        for d in all_decks:
            try:
                with d:
                    d.reset()
                    d.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
