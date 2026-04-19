#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""DJ Scratch (SD+ dials + touchscreen).

Turn dials to scratch virtual vinyl. Speed and direction shown on
touchscreen as waveform. Click dial to switch track style. Buttons
play tones matching the waveform. Press button 0-3 to hear the sound!
"""

import io
import json
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

STYLES = [
    "Sine", "Square", "Saw", "Noise", "Mic",      # 0-4: basic
    "Piano", "Guitar", "Drum",                      # 5-7: existing
    "Trumpet", "Trombone", "Violin", "Organ",       # 8-11: brass/strings
    "Flute", "Bass", "Cello", "Harmonica",          # 12-15: more instruments
]
STYLE_COLORS = [
    (0, 200, 255),    # 0  Sine - cyan
    (255, 100, 0),    # 1  Square - orange
    (0, 255, 100),    # 2  Saw - green
    (255, 0, 200),    # 3  Noise - pink
    (255, 40, 80),    # 4  Mic - red
    (255, 255, 100),  # 5  Piano - yellow
    (180, 120, 60),   # 6  Guitar - brown
    (200, 80, 200),   # 7  Drum - purple
    (220, 180, 0),    # 8  Trumpet - gold
    (180, 140, 0),    # 9  Trombone - dark gold
    (160, 80, 40),    # 10 Violin - wood
    (100, 100, 200),  # 11 Organ - blue-grey
    (200, 220, 255),  # 12 Flute - light blue
    (80, 40, 120),    # 13 Bass - deep purple
    (140, 60, 40),    # 14 Cello - dark wood
    (120, 200, 120),  # 15 Harmonica - mint
]
BASE_FREQS = [261.63, 329.63, 392.00, 523.25]  # C4, E4, G4, C5
SAMPLE_RATE = 22050
DURATION = 0.3
VOLUME = 0.5
DIAL_MODES = [
    "freq", "vol", "pitch", "ring", "tremolo",
    "reverb", "echo", "bitcrush", "distort", "stutter", "reverse",
]
MODE_COLORS = {
    "freq": (0, 60, 120),
    "vol": (120, 60, 0),
    "pitch": (0, 120, 60),
    "ring": (120, 0, 120),
    "tremolo": (60, 120, 0),
    "reverb": (60, 60, 120),
    "echo": (0, 100, 100),
    "bitcrush": (100, 50, 0),
    "distort": (120, 20, 20),
    "stutter": (80, 0, 80),
    "reverse": (40, 80, 40),
}
MODE_LABELS = {
    "freq": "FREQ",
    "vol": "VOL",
    "pitch": "PTCH",
    "ring": "RING",
    "tremolo": "TREM",
    "reverb": "VERB",
    "echo": "ECHO",
    "bitcrush": "CRSH",
    "distort": "DIST",
    "stutter": "STUT",
    "reverse": "REV",
}
# Available dial modes per style (index matches STYLES list)
# Synths: freq + vol only. Mic/samples: all effects. Instruments: freq + vol + echo/reverb.
STYLE_MODES = {
    0: ["freq", "vol"],                                    # Sine
    1: ["freq", "vol"],                                    # Square
    2: ["freq", "vol"],                                    # Saw
    3: ["vol"],                                            # Noise (no freq)
    4: ["vol", "pitch", "ring", "tremolo", "reverb",       # Mic
        "echo", "bitcrush", "distort", "stutter", "reverse"],
    5: ["freq", "vol", "reverb", "echo"],                  # Piano
    6: ["freq", "vol", "reverb", "echo", "distort"],       # Guitar
    7: ["freq", "vol", "reverb", "echo", "bitcrush"],      # Drum
    8: ["freq", "vol", "reverb", "echo"],                  # Trumpet
    9: ["freq", "vol", "reverb", "echo"],                  # Trombone
    10: ["freq", "vol", "reverb", "echo", "tremolo"],      # Violin
    11: ["freq", "vol", "reverb", "echo", "tremolo"],      # Organ
    12: ["freq", "vol", "reverb", "echo"],                 # Flute
    13: ["freq", "vol", "reverb", "echo", "distort"],      # Bass
    14: ["freq", "vol", "reverb", "echo", "tremolo"],      # Cello
    15: ["freq", "vol", "reverb", "echo"],                 # Harmonica
}


def _adsr(i, n, rate, attack=0.01, decay=0.1, sustain=0.7, release=0.05):
    """ADSR envelope generator. Times in seconds."""
    t = i / rate
    dur = n / rate
    a_end = attack
    d_end = attack + decay
    r_start = dur - release
    if t < a_end:
        return t / attack if attack > 0 else 1.0
    elif t < d_end:
        return 1.0 - (1.0 - sustain) * (t - a_end) / decay
    elif t < r_start:
        return sustain
    else:
        return sustain * max(0, (dur - t) / release)


def _formant_filter(val, freq, formant_freqs, formant_bw, t):
    """Simple formant resonance by boosting near formant frequencies."""
    boost = 0.0
    for ff, bw in zip(formant_freqs, formant_bw):
        # Resonance peak
        dist = abs(freq - ff) / bw
        if dist < 3:
            boost += math.exp(-0.5 * dist * dist) * 0.3
    return val * (1.0 + boost)


def _generate_trumpet(freq, duration, rate):
    """Trumpet: FM synthesis + formants + ADSR + vibrato."""
    n = int(rate * duration)
    samples = []
    # Brass formants around 1200Hz and 2500Hz
    for i in range(n):
        t = i / rate
        env = _adsr(i, n, rate, attack=0.03, decay=0.05, sustain=0.85, release=0.04)
        # Vibrato (delayed onset)
        vib = 0
        if t > 0.05:
            vib = 3 * math.sin(2 * math.pi * 5.5 * t) * min(1, (t - 0.05) / 0.1)
        f = freq + vib
        # FM synthesis: carrier + modulator
        mod_idx = 2.0 * env  # modulation index decreases with envelope
        mod = math.sin(2 * math.pi * f * t)
        carrier = math.sin(2 * math.pi * f * t + mod_idx * mod)
        # Add harmonics
        val = carrier * 0.6
        for h in range(2, 9):
            hf = f * h
            if hf > rate / 2:
                break
            h_env = env * (0.8 ** h)
            val += h_env * 0.3 * math.sin(2 * math.pi * hf * t)
        val *= env
        # Formant coloring
        val = _formant_filter(val, freq, [1200, 2500], [300, 400], t)
        samples.append(val)
    peak = max(abs(s) for s in samples) or 1
    return [s / peak for s in samples]


def _generate_trombone(freq, duration, rate):
    """Trombone: warm FM + slow attack + lower formants."""
    n = int(rate * duration)
    samples = []
    for i in range(n):
        t = i / rate
        env = _adsr(i, n, rate, attack=0.06, decay=0.08, sustain=0.8, release=0.05)
        vib = 2 * math.sin(2 * math.pi * 4 * t) * min(1, t / 0.15)
        f = freq + vib
        # FM with lower mod ratio for warmth
        mod = math.sin(2 * math.pi * f * 0.5 * t)
        carrier = math.sin(2 * math.pi * f * t + 1.5 * env * mod)
        val = carrier * 0.7
        for h in range(2, 7):
            hf = f * h
            if hf > rate / 2:
                break
            val += (0.7 ** h) * env * 0.25 * math.sin(2 * math.pi * hf * t)
        val *= env
        val = _formant_filter(val, freq, [600, 1800], [250, 350], t)
        samples.append(val)
    peak = max(abs(s) for s in samples) or 1
    return [s / peak for s in samples]


def _generate_violin(freq, duration, rate):
    """Violin: warm bowed string with wood body filtering."""
    n = int(rate * duration)
    samples = []
    phase = 0.0
    # Simple IIR low-pass state for body warmth
    lp_state = 0.0
    # Cutoff adapts to pitch — higher notes brighter but still warm
    lp_alpha = min(0.9, 2800.0 / rate)
    for i in range(n):
        t = i / rate
        # Slow, expressive bow attack — violin bow takes time to grip
        env = _adsr(i, n, rate, attack=0.12, decay=0.06, sustain=0.85,
                     release=0.12)
        # Vibrato: delayed, slow onset, gentle ~5 Hz
        vib_onset = min(1.0, max(0.0, (t - 0.15) / 0.1))
        vib = (0.004 * freq * vib_onset
               * math.sin(2 * math.pi * 5.0 * t
                          + 0.3 * math.sin(2 * math.pi * 0.6 * t)))
        f = freq + vib
        phase += f / rate
        # Bowed sawtooth with steep rolloff (1/h^1.4) — wood body
        # absorbs upper harmonics much more than brass bell
        val = 0.0
        for h in range(1, 14):
            hf = f * h
            if hf > rate * 0.42:
                break
            # 1/h^1.4 = warmer than sawtooth, even harmonics boosted
            # (opposite of trumpet which boosts odd)
            amp = 1.0 / (h ** 1.4)
            if h % 2 == 0:
                amp *= 1.15  # even harmonics stronger = warm
            # Gradual harmonic build — bow engages string slowly
            h_onset = min(1.0, t / (0.03 + h * 0.012))
            val += amp * h_onset * math.sin(2 * math.pi * h * phase)
        # Gentle bow pressure variation (NOT scratch/buzz)
        flutter = 1.0 + 0.015 * math.sin(2 * math.pi * 2.8 * t)
        val *= flutter
        # Low-pass filter: simulates violin body + bridge damping
        # This is the key difference from trumpet — kills brightness
        lp_state += lp_alpha * (val - lp_state)
        val = lp_state
        # Subtle body warmth: very gentle random variation
        val += random.uniform(-1, 1) * 0.008 * env
        val *= env
        samples.append(val)
    peak = max(abs(s) for s in samples) or 1
    return [s / peak for s in samples]


def _generate_organ(freq, duration, rate):
    """Organ: Hammond drawbar simulation with rotary Leslie effect."""
    n = int(rate * duration)
    # Hammond drawbar settings (feet: 16,5⅓,8,4,2⅔,2,1⅗,1⅓,1)
    drawbars = [
        (0.5, 0.6),   # 16'  sub-octave
        (1.5, 0.4),   # 5⅓' quint
        (1.0, 1.0),   # 8'   fundamental
        (2.0, 0.8),   # 4'
        (3.0, 0.5),   # 2⅔'
        (4.0, 0.7),   # 2'
        (5.0, 0.3),   # 1⅗'
        (6.0, 0.4),   # 1⅓'
        (8.0, 0.2),   # 1'
    ]
    samples = []
    for i in range(n):
        t = i / rate
        env = _adsr(i, n, rate, attack=0.005, decay=0.01, sustain=1.0, release=0.02)
        val = 0
        for mult, amp in drawbars:
            hf = freq * mult
            if hf > rate / 2:
                continue
            val += amp * math.sin(2 * math.pi * hf * t)
        # Leslie rotary speaker effect (AM + slight FM)
        leslie_rate = 6.0
        leslie_am = 0.15 * math.sin(2 * math.pi * leslie_rate * t)
        leslie_fm = 0.5 * math.sin(2 * math.pi * leslie_rate * t + 1.5)
        val *= (1.0 + leslie_am) * env
        samples.append(val)
    peak = max(abs(s) for s in samples) or 1
    return [s / peak for s in samples]


def _generate_flute(freq, duration, rate):
    """Flute: breathy air noise + nearly pure tone + overblowing."""
    n = int(rate * duration)
    samples = []
    for i in range(n):
        t = i / rate
        env = _adsr(i, n, rate, attack=0.03, decay=0.02, sustain=0.85, release=0.04)
        # Delayed vibrato
        vib = 2 * math.sin(2 * math.pi * 5 * t) * min(1, max(0, (t - 0.08) / 0.1))
        f = freq + vib
        # Nearly pure sine with tiny 2nd harmonic
        val = math.sin(2 * math.pi * f * t)
        val += 0.08 * math.sin(2 * math.pi * f * 2 * t)
        val += 0.02 * math.sin(2 * math.pi * f * 3 * t)
        val *= env
        # Breathy noise (filtered, stronger at attack)
        breath_env = 0.04 + 0.12 * math.exp(-8.0 * t)
        breath = random.uniform(-1, 1) * breath_env
        # Filter breath to be near the playing frequency
        val += breath * 0.3
        samples.append(val)
    peak = max(abs(s) for s in samples) or 1
    return [s / peak for s in samples]


def _generate_bass(freq, duration, rate):
    """Electric bass: pluck transient + deep fundamental + string buzz."""
    n = int(rate * duration)
    # Karplus-Strong base for realistic pluck
    delay_len = max(2, int(rate / freq))
    buf = [random.uniform(-1, 1) for _ in range(delay_len)]
    ks_samples = []
    idx = 0
    for i in range(n):
        val = buf[idx]
        next_idx = (idx + 1) % delay_len
        # Heavier damping for bass (lower cutoff)
        buf[idx] = (buf[idx] + buf[next_idx]) * 0.499
        idx = next_idx
        ks_samples.append(val)
    samples = []
    for i in range(n):
        t = i / rate
        env = _adsr(i, n, rate, attack=0.002, decay=0.15, sustain=0.4, release=0.08)
        # Strong fundamental sine for body
        body = math.sin(2 * math.pi * freq * t) * 0.6
        # Pluck from KS
        pluck = ks_samples[i] * 0.4 * math.exp(-3.0 * t)
        # Transient click
        click = random.uniform(-1, 1) * math.exp(-80.0 * t) * 0.3
        val = (body + pluck + click) * env
        samples.append(val)
    peak = max(abs(s) for s in samples) or 1
    return [s / peak for s in samples]


def _generate_cello(freq, duration, rate):
    """Cello: bowed string lower register, warm + rich."""
    n = int(rate * duration)
    samples = []
    for i in range(n):
        t = i / rate
        env = _adsr(i, n, rate, attack=0.06, decay=0.03, sustain=0.9, release=0.08)
        # Slow vibrato
        vib = 3 * math.sin(2 * math.pi * 4.5 * t) * min(1, t / 0.15)
        f = freq + vib
        # Rich bowed harmonics with slight inharmonicity
        val = 0
        for h in range(1, 10):
            hf = f * h * (1.0 + 0.0003 * h * h)  # slight inharmonicity
            if hf > rate / 2:
                break
            amp = (0.7 ** h) * (1.15 if h % 2 == 1 else 0.85)
            h_att = min(1, t / (0.03 + h * 0.008))
            val += amp * h_att * math.sin(2 * math.pi * hf * t)
        # Bow scratch texture
        val += random.uniform(-1, 1) * 0.015 * env
        val *= env
        samples.append(val)
    peak = max(abs(s) for s in samples) or 1
    return [s / peak for s in samples]


def _generate_harmonica(freq, duration, rate):
    """Harmonica: reed vibration + air column resonance + natural tremolo."""
    n = int(rate * duration)
    samples = []
    for i in range(n):
        t = i / rate
        env = _adsr(i, n, rate, attack=0.02, decay=0.03, sustain=0.8, release=0.03)
        f = freq
        # Reed vibration: strong odd harmonics (like clarinet)
        val = 0
        for h in range(1, 10):
            hf = f * h
            if hf > rate / 2:
                break
            # Odd harmonics much stronger
            if h % 2 == 1:
                amp = 0.7 ** ((h - 1) / 2)
            else:
                amp = 0.15 * (0.7 ** (h / 2))
            val += amp * math.sin(2 * math.pi * hf * t)
        # Natural tremolo from breathing
        trem = 0.7 + 0.3 * math.sin(2 * math.pi * 7 * t + 0.5 * math.sin(2 * math.pi * 0.3 * t))
        # Air noise
        air = random.uniform(-1, 1) * 0.03
        val = (val * trem + air) * env
        samples.append(val)
    peak = max(abs(s) for s in samples) or 1
    return [s / peak for s in samples]


def _generate_piano(freq, duration, rate):
    """Piano synthesis: harmonics with exponential decay per partial."""
    n_samples = int(rate * duration)
    # Piano has strong fundamental + decaying harmonics
    harmonics = [
        (1.0, 1.0, 3.0),    # fundamental, amplitude, decay rate
        (2.0, 0.5, 4.0),    # 2nd harmonic
        (3.0, 0.25, 5.0),   # 3rd
        (4.0, 0.15, 6.0),   # 4th
        (5.0, 0.08, 7.0),   # 5th
        (6.0, 0.04, 8.0),   # 6th
    ]
    samples = []
    for i in range(n_samples):
        t = i / rate
        val = 0.0
        for harm_mult, amp, decay in harmonics:
            h_freq = freq * harm_mult
            if h_freq > rate / 2:
                continue  # skip above Nyquist
            env = math.exp(-decay * t)
            val += amp * env * math.sin(2 * math.pi * h_freq * t)
        # Normalize
        samples.append(val / 2.0)
    return samples


def _generate_guitar(freq, duration, rate):
    """Karplus-Strong plucked string synthesis."""
    n_samples = int(rate * duration)
    # Initialize delay line with noise
    delay_len = max(2, int(rate / freq))
    buf = [random.uniform(-1, 1) for _ in range(delay_len)]
    samples = []
    idx = 0
    for i in range(n_samples):
        val = buf[idx]
        # Average with next sample (low-pass filter = string damping)
        next_idx = (idx + 1) % delay_len
        buf[idx] = (buf[idx] + buf[next_idx]) * 0.498
        idx = next_idx
        # Decay envelope
        decay = math.exp(-2.0 * i / n_samples)
        samples.append(val * decay)
    return samples


def _generate_drum(freq, duration, rate):
    """Drum synthesis: noise burst with pitch envelope."""
    n_samples = int(rate * duration)
    samples = []
    for i in range(n_samples):
        t = i / rate
        progress = i / n_samples
        # Pitch drops quickly from freq to freq/4
        current_freq = freq * (1.0 - progress * 0.75)
        # Mix sine (body) + noise (attack)
        body = math.sin(2 * math.pi * current_freq * t)
        noise = random.uniform(-1, 1)
        # Noise fades fast, body fades slower
        noise_env = math.exp(-20.0 * progress)
        body_env = math.exp(-5.0 * progress)
        val = body * body_env * 0.7 + noise * noise_env * 0.3
        samples.append(val)
    return samples


def generate_tone(style, freq, volume_db=0.0, duration=DURATION, rate=SAMPLE_RATE):
    """Generate raw PCM samples for a tone with volume in dB."""
    n_samples = int(rate * duration)
    linear_vol = min(32.0, 10 ** (volume_db / 20.0)) * VOLUME

    # Instruments with custom synthesis
    if style == 5:  # Piano
        raw = _generate_piano(freq, duration, rate)
        return [
            max(-32767, min(32767, int(s * linear_vol * 32767)))
            for s in raw
        ]
    elif style == 6:  # Guitar
        raw = _generate_guitar(freq, duration, rate)
        return [
            max(-32767, min(32767, int(s * linear_vol * 32767)))
            for s in raw
        ]
    elif style == 7:  # Drum
        raw = _generate_drum(freq, duration, rate)
        return [
            max(-32767, min(32767, int(s * linear_vol * 32767)))
            for s in raw
        ]

    # Instruments 8-15
    generators = {
        8: _generate_trumpet,
        9: _generate_trombone,
        10: _generate_violin,
        11: _generate_organ,
        12: _generate_flute,
        13: _generate_bass,
        14: _generate_cello,
        15: _generate_harmonica,
    }
    if style in generators:
        raw = generators[style](freq, duration, rate)
        return [
            max(-32767, min(32767, int(s * linear_vol * 32767)))
            for s in raw
        ]

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
        sample = int(val * env * linear_vol * 32767)
        sample = max(-32767, min(32767, sample))
        samples.append(sample)
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
    def __init__(self, deck, sampler_deck=None, extra_decks=None):
        self.deck = deck
        self.sampler_deck = sampler_deck
        self.extra_decks = extra_decks or []
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
        self.volumes_db = [0.0, 0.0, 0.0, 0.0]  # dB (-40 to +30)
        self.pitch_ratios = [1.0, 1.0, 1.0, 1.0]  # pitch multiplier
        self.ring_freqs = [0.0, 0.0, 0.0, 0.0]  # ring mod Hz (0=off)
        self.tremolo_rates = [0.0, 0.0, 0.0, 0.0]  # tremolo Hz (0=off)
        self.reverb_amt = [0.0, 0.0, 0.0, 0.0]  # 0-100 (0=off)
        self.echo_delay = [0.0, 0.0, 0.0, 0.0]  # ms (0=off)
        self.bitcrush_bits = [16.0, 16.0, 16.0, 16.0]  # bits (16=off, lower=more crush)
        self.distort_amt = [0.0, 0.0, 0.0, 0.0]  # 0-100 (0=off)
        self.stutter_rate = [0.0, 0.0, 0.0, 0.0]  # Hz (0=off)
        self.reverse_on = [0, 0, 0, 0]  # 0=off, 1=on
        # Per-channel dial mode (independent)
        self.dial_modes = ["freq", "freq", "freq", "freq"]
        self.playing = [False] * 4
        self.sw = deck.TOUCHSCREEN_PIXEL_WIDTH or deck.SCREEN_PIXEL_WIDTH or 800
        self.sh = deck.TOUCHSCREEN_PIXEL_HEIGHT or deck.SCREEN_PIXEL_HEIGHT or 100
        # Sampler state (deck 2)
        self.record_mode = False
        self.waiting_assign = -1  # key on sampler waiting for note
        self.sampler_map = {}  # key -> (style, freq) or "wav:path" tuple
        self.sampler_playing = set()
        self.mic_recording = False
        self.mic_process = None
        self.mic_start_time = 0
        # Sample recording (SAM button)
        self.sam_recording = False
        self.sam_process = None
        self.sam_start_time = 0
        # Per-channel sample WAV (used by Mic style on deck 1)
        self.channel_samples = {}  # channel_idx -> wav_path
        self.save_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "save"
        )
        os.makedirs(self.save_dir, exist_ok=True)
        if sampler_deck:
            sr, sc = sampler_deck.key_layout()
            self.sampler_cols = sc
            self.sampler_rows = sr
            self.sampler_total = sc * sr
            # Layout col 0: row 0 = REC, row 1 = MIC, row 2 = SAM
            self.key_rec = 0
            self.key_mic = self.sampler_cols
            self.key_sam = self.sampler_cols * 2 if sr > 2 else -1
            self.key_rst = self.sampler_cols * 3 if sr > 3 else -1
            # Row 3 extra buttons (col 1-5)
            r3 = self.sampler_cols * 3
            self.key_loop = r3 + 1 if sr > 3 and sc > 1 else -1
            self.key_seq = r3 + 2 if sr > 3 and sc > 2 else -1
            self.key_met = r3 + 3 if sr > 3 and sc > 3 else -1
            self.key_mix = r3 + 4 if sr > 3 and sc > 4 else -1
            self.key_exp = r3 + 5 if sr > 3 and sc > 5 else -1
        else:
            self.sampler_cols = 0
            self.sampler_rows = 0
            self.sampler_total = 0
            self.key_rec = 0
            self.key_mic = 0
            self.key_sam = -1
            self.key_rst = -1
            self.key_loop = -1
            self.key_seq = -1
            self.key_met = -1
            self.key_mix = -1
            self.key_exp = -1
        # Extra decks: pure sampler extension (no control buttons)
        # Virtual key = sampler_total + cumulative offset + physical key
        self.extra_deck_info = []  # (deck, offset, rows, cols, total)
        offset = self.sampler_total
        for ed in self.extra_decks:
            er, ec = ed.key_layout()
            et = er * ec
            self.extra_deck_info.append((ed, offset, er, ec, et))
            offset += et
        self.sampler_total_all = offset  # total keys across all samplers
        # Looper state
        self.loop_state = "off"  # off, rec, play, overdub
        self.loop_buffer = []
        self.loop_thread = None
        # Sequencer state
        self.seq_on = False
        self.seq_bpm = 120
        self.seq_steps = 8
        self.seq_pattern = [[] for _ in range(8)]  # step -> list of channel indices
        self.seq_pos = 0
        self.seq_thread = None
        # Metronome state
        self.metro_on = False
        self.metro_bpm = 120
        self.metro_thread = None
        # Export state
        self.exporting = False
        self.export_buffer = []
        self.export_start = 0

    def _db_to_linear(self, db):
        """Convert dB to linear volume (0.0 to ~2.0)."""
        return 10 ** (db / 20.0)

    def handle_dial(self, dial, event, value):
        if dial >= 4:
            return
        # Dial 3 controls BPM when metronome or sequencer active
        if dial == 3 and event == DialEventType.TURN:
            if self.metro_on:
                self.metro_bpm = max(40, min(300, self.metro_bpm + value * 2))
                self.seq_bpm = self.metro_bpm
                return
            elif self.seq_on:
                self.seq_bpm = max(40, min(300, self.seq_bpm + value * 2))
                self.metro_bpm = self.seq_bpm
                return
        if event == DialEventType.TURN:
            self.speeds[dial] = value * 2.0
            mode = self.dial_modes[dial]
            if mode == "freq":
                self.freqs[dial] = max(
                    80, min(2000, self.freqs[dial] + value * 20)
                )
            elif mode == "vol":
                self.volumes_db[dial] = max(
                    -40, min(30, self.volumes_db[dial] + value)
                )
            elif mode == "pitch":
                self.pitch_ratios[dial] = max(
                    0.25, min(4.0, self.pitch_ratios[dial] + value * 0.1)
                )
            elif mode == "ring":
                self.ring_freqs[dial] = max(
                    0, min(2000, self.ring_freqs[dial] + value * 10)
                )
            elif mode == "tremolo":
                self.tremolo_rates[dial] = max(
                    0, min(50, self.tremolo_rates[dial] + value)
                )
            elif mode == "reverb":
                self.reverb_amt[dial] = max(
                    0, min(100, self.reverb_amt[dial] + value * 5)
                )
            elif mode == "echo":
                self.echo_delay[dial] = max(
                    0, min(500, self.echo_delay[dial] + value * 10)
                )
            elif mode == "bitcrush":
                self.bitcrush_bits[dial] = max(
                    1, min(16, self.bitcrush_bits[dial] + value)
                )
            elif mode == "distort":
                self.distort_amt[dial] = max(
                    0, min(100, self.distort_amt[dial] + value * 5)
                )
            elif mode == "stutter":
                self.stutter_rate[dial] = max(
                    0, min(30, self.stutter_rate[dial] + value)
                )
            elif mode == "reverse":
                self.reverse_on[dial] = 1 - self.reverse_on[dial]
        elif event == DialEventType.PUSH and value:
            self.styles[dial] = (self.styles[dial] + 1) % len(STYLES)
            # Reset dial mode to first available for new style
            new_style = self.styles[dial]
            avail = STYLE_MODES.get(new_style, DIAL_MODES)
            if self.dial_modes[dial] not in avail:
                self.dial_modes[dial] = avail[0]

    def handle_key(self, key, state, deck_index=0):
        if deck_index == 1:
            self._handle_sampler_key(key, state)
            return
        if deck_index >= 2:
            # Extra deck — find offset
            ei = deck_index - 2
            if ei < len(self.extra_deck_info):
                offset = self.extra_deck_info[ei][1]
                self._handle_extra_key(key, state, offset)
            return

        col = key % self.cols
        row = key // self.cols
        last_r = self.rows - 1

        # Top row = cycle mode per channel (filtered by style)
        if row == 0 and col < 4 and state:
            style = self.styles[col]
            avail = STYLE_MODES.get(style, DIAL_MODES)
            cur = self.dial_modes[col]
            if cur in avail:
                idx = avail.index(cur)
                self.dial_modes[col] = avail[(idx + 1) % len(avail)]
            else:
                self.dial_modes[col] = avail[0]
            return

        # Bottom row = sound buttons
        if row == last_r and col < 4:
            # If sampler is waiting for a note assignment, assign with volume
            if self.waiting_assign >= 0 and state:
                self.sampler_map[self.waiting_assign] = (
                    self.styles[col],
                    self.freqs[col],
                    self.volumes_db[col],
                )
                print(
                    f"Assigned channel {col} "
                    f"({STYLES[self.styles[col]]} {int(self.freqs[col])}Hz "
                    f"{self.volumes_db[col]:+.0f}dB) "
                    f"to sampler key {self.waiting_assign}"
                )
                self.waiting_assign = -1
                self._render_sampler()
                return

            if state:
                self.playing[col] = True
                threading.Thread(
                    target=self._play_tone,
                    args=(col,),
                    daemon=True,
                ).start()
            else:
                self.playing[col] = False

    def _get_channel_params(self, channel):
        """Get all params for a channel."""
        return {
            "style": self.styles[channel],
            "freq": self.freqs[channel],
            "vol_db": self.volumes_db[channel],
            "pitch": self.pitch_ratios[channel],
            "ring": self.ring_freqs[channel],
            "tremolo": self.tremolo_rates[channel],
            "reverb": self.reverb_amt[channel],
            "echo": self.echo_delay[channel],
            "bitcrush": self.bitcrush_bits[channel],
            "distort": self.distort_amt[channel],
            "stutter": self.stutter_rate[channel],
            "reverse": self.reverse_on[channel],
            "mode": self.dial_modes[channel],
        }

    def _play_tone(self, channel):
        """Generate and play a tone for the given channel."""
        p = self._get_channel_params(channel)
        if p["style"] == 4:  # Mic passthrough with all effects
            self._play_mic_passthrough_full(p)
        else:
            self._play_sound(p["style"], p["freq"], p["vol_db"])

    def _play_mic_passthrough_full(self, params):
        """Play sample or mic with ALL effects applied."""
        mic_ch = self._find_mic_channel()

        # Use pre-recorded sample if available
        source_path = None
        if mic_ch >= 0 and mic_ch in self.channel_samples:
            p = self.channel_samples[mic_ch]
            if os.path.isfile(p):
                source_path = p

        if not source_path:
            # Capture live from mic
            source_path = os.path.join(self.save_dir, "_mic_live.wav")
            try:
                proc = subprocess.Popen(
                    [
                        "arecord", "-f", "S16_LE", "-r", str(SAMPLE_RATE),
                        "-c", "1", "-d", str(int(DURATION * 2)),
                        "-q", source_path,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                proc.wait()
            except FileNotFoundError:
                return

        if not os.path.isfile(source_path):
            return

        try:
            with wave.open(source_path, "rb") as wf:
                raw = wf.readframes(wf.getnframes())
                n = wf.getnframes()
            samples = list(struct.unpack(f"<{n}h", raw))
            samples = self._apply_effects_chain(samples, params)
            wav_data = samples_to_wav(samples)
            play_wav_bytes(wav_data)
        except Exception:
            self._play_wav_file(source_path)

    def _play_mic_passthrough(self, volume_db=0.0, freq=261.63, mode="freq"):
        """Play sample (if exists) or capture mic, with effects applied."""
        mic_ch = self._find_mic_channel()

        # Use pre-recorded sample if available
        if mic_ch >= 0 and mic_ch in self.channel_samples:
            sample_path = self.channel_samples[mic_ch]
            if os.path.isfile(sample_path):
                try:
                    with wave.open(sample_path, "rb") as wf:
                        raw = wf.readframes(wf.getnframes())
                        n = wf.getnframes()
                    samples = list(struct.unpack(f"<{n}h", raw))
                    samples = self._apply_effects(
                        samples, volume_db, freq, mode
                    )
                    wav_data = samples_to_wav(samples)
                    play_wav_bytes(wav_data)
                    return
                except Exception:
                    pass

        # Fallback: capture live from mic
        tmp_path = os.path.join(self.save_dir, "_mic_passthrough.wav")
        try:
            proc = subprocess.Popen(
                [
                    "arecord", "-f", "S16_LE", "-r", str(SAMPLE_RATE),
                    "-c", "1", "-d", str(int(DURATION * 2)),
                    "-q", tmp_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc.wait()
        except FileNotFoundError:
            return

        if not os.path.isfile(tmp_path):
            return

        try:
            with wave.open(tmp_path, "rb") as wf:
                raw = wf.readframes(wf.getnframes())
                n = wf.getnframes()
            samples = list(struct.unpack(f"<{n}h", raw))
            samples = self._apply_effects(samples, volume_db, freq, mode)
            wav_data = samples_to_wav(samples)
            play_wav_bytes(wav_data)
        except Exception:
            self._play_wav_file(tmp_path)

    def _apply_effects(self, samples, volume_db, freq, mode):
        """Legacy: apply single effect. Delegates to full chain."""
        params = {
            "vol_db": volume_db,
            "pitch": freq / BASE_FREQS[0] if mode == "pitch" else 1.0,
            "ring": freq if mode == "ring" else 0,
            "tremolo": max(1, freq / 10) if mode == "tremolo" else 0,
        }
        return self._apply_effects_chain(samples, params)

    def _apply_effects_chain(self, samples, params):
        """Apply ALL effects in chain."""
        n = len(samples)
        if n == 0:
            return samples

        vol_db = params.get("vol_db", 0.0)
        pitch = params.get("pitch", 1.0)
        ring_freq = params.get("ring", 0)
        trem_rate = params.get("tremolo", 0)
        reverb = params.get("reverb", 0)
        echo_ms = params.get("echo", 0)
        crush_bits = params.get("bitcrush", 16)
        distort = params.get("distort", 0)
        stutter_hz = params.get("stutter", 0)
        do_reverse = params.get("reverse", 0)
        linear_vol = min(32.0, 10 ** (vol_db / 20.0))

        # 1. Reverse
        if do_reverse:
            samples = samples[::-1]

        # 2. Pitch shift (resample)
        if abs(pitch - 1.0) > 0.05:
            ratio = max(0.25, min(4.0, pitch))
            new_len = int(n / ratio)
            pitched = []
            for i in range(new_len):
                src = i * ratio
                idx = int(src)
                if idx >= n - 1:
                    break
                frac = src - idx
                val = samples[idx] * (1 - frac) + samples[idx + 1] * frac
                pitched.append(int(val))
            while len(pitched) < n:
                pitched.append(0)
            samples = pitched[:n]
            n = len(samples)

        # 3. Stutter (loop micro-segments)
        if stutter_hz > 0:
            chunk = max(1, int(SAMPLE_RATE / stutter_hz))
            stuttered = []
            i = 0
            while len(stuttered) < n:
                seg = samples[i:i + chunk]
                if not seg:
                    break
                # Repeat the chunk to fill
                stuttered.extend(seg)
                i += chunk
            samples = stuttered[:n]

        # 4. Per-sample effects
        result = []
        for i in range(n):
            val = float(samples[i])
            t = i / SAMPLE_RATE

            # Ring modulation
            if ring_freq > 0:
                val *= math.sin(2 * math.pi * ring_freq * t)

            # Tremolo
            if trem_rate > 0:
                val *= 0.5 + 0.5 * math.sin(2 * math.pi * trem_rate * t)

            # Distortion (tanh soft clip)
            if distort > 0:
                gain = 1.0 + distort * 0.5
                val = math.tanh(val * gain / 32767.0) * 32767.0

            # Bitcrush (reduce bit depth)
            if crush_bits < 16:
                levels = max(2, 2 ** int(crush_bits))
                step = 65535.0 / levels
                val = int(val / step) * step

            # Volume
            val *= linear_vol
            result.append(int(val))

        # 5. Echo (mix delayed copy)
        if echo_ms > 0:
            delay_samples = int(echo_ms * SAMPLE_RATE / 1000)
            if delay_samples > 0 and delay_samples < n:
                decay = 0.5
                for reps in range(3):
                    offset = delay_samples * (reps + 1)
                    atten = decay ** (reps + 1)
                    for i in range(n):
                        src = i - offset
                        if 0 <= src < n:
                            result[i] += int(result[src] * atten)

        # 6. Reverb (simple comb filter)
        if reverb > 0:
            mix = reverb / 100.0
            delays = [int(d * SAMPLE_RATE / 1000) for d in [23, 37, 53, 71]]
            rev = [0.0] * n
            for d in delays:
                if d >= n:
                    continue
                decay = 0.3 * mix
                for i in range(d, n):
                    rev[i] += result[i - d] * decay
            for i in range(n):
                result[i] = int(result[i] * (1 - mix * 0.5) + rev[i])

        return [max(-32767, min(32767, s)) for s in result]

    def _play_sound(self, style, freq, volume_db=0.0):
        """Generate and play a specific tone."""
        samples = generate_tone(style, freq, volume_db=volume_db)
        wav_data = samples_to_wav(samples)
        play_wav_bytes(wav_data)

    def _is_control_key(self, key):
        """Check if key is a control button."""
        return key in (
            self.key_rec, self.key_mic, self.key_sam, self.key_rst,
            self.key_loop, self.key_seq, self.key_met, self.key_mix,
            self.key_exp,
        )

    def _handle_sampler_key(self, key, state):
        """Handle key press on the sampler (deck 2)."""
        if not state:
            self.sampler_playing.discard(key)
            self._render_sampler()
            return

        # Button REC (row 0, col 0) = toggle record mode
        if key == self.key_rec:
            if self.mic_recording:
                self._stop_mic()
            if self.record_mode:
                self.record_mode = False
                self.waiting_assign = -1
                print("Record mode OFF")
            else:
                self.record_mode = True
                self.waiting_assign = -1
                print("Record mode ON - press a button to assign")
            self._render_sampler()
            return

        # Button MIC (row 1, col 0) = mic record (only in record mode)
        if key == self.key_mic:
            if not self.record_mode:
                return
            if self.waiting_assign < 0:
                print("Select a button first, then press MIC")
                return
            if self.mic_recording:
                self._stop_mic()
            else:
                self._start_mic()
            self._render_sampler()
            return

        # Button SAM (row 2, col 0) = record a sample for Mic passthrough
        if key == self.key_sam and self.key_sam >= 0:
            if not self.record_mode:
                return
            if self.sam_recording:
                self._stop_sam()
            else:
                self._start_sam()
            self._render_sampler()
            return

        # Button RST (row 3, col 0) = reset all effects to defaults
        if key == self.key_rst and self.key_rst >= 0:
            self._reset_all_effects()
            self._render_sampler()
            return

        # LOOP button
        if key == self.key_loop and self.key_loop >= 0:
            self._toggle_looper()
            self._render_sampler()
            return

        # SEQ button
        if key == self.key_seq and self.key_seq >= 0:
            self._toggle_sequencer()
            self._render_sampler()
            return

        # MET button (metronome)
        if key == self.key_met and self.key_met >= 0:
            self._toggle_metronome()
            self._render_sampler()
            return

        # MIX button
        if key == self.key_mix and self.key_mix >= 0:
            threading.Thread(target=self._do_mixdown, daemon=True).start()
            self._render_sampler()
            return

        # EXP button (export)
        if key == self.key_exp and self.key_exp >= 0:
            self._toggle_export()
            self._render_sampler()
            return

        if self.record_mode:
            # Stop any active mic recording if switching target
            if self.mic_recording:
                self._stop_mic()
            # Select this button for assignment
            if self._is_control_key(key):
                return
            self.waiting_assign = key
            print(
                f"Sampler key {key} selected - press sound 0-3 on deck 1 "
                f"or MIC to record"
            )
            self._render_sampler()
        else:
            # Play assigned sound
            if key in self.sampler_map:
                mapping = self.sampler_map[key]
                self.sampler_playing.add(key)
                self._render_sampler()
                threading.Thread(
                    target=self._play_sampler_mapping,
                    args=(key, mapping),
                    daemon=True,
                ).start()

    def _handle_extra_key(self, key, state, deck_offset):
        """Handle key press on an extra deck (pure sampler extension)."""
        virtual_key = deck_offset + key
        if not state:
            self.sampler_playing.discard(virtual_key)
            self._render_extra_decks()
            return
        if self.record_mode:
            self.waiting_assign = virtual_key
            print(
                f"Extra sampler key {virtual_key} selected - "
                f"press sound 0-3 on deck 1 or MIC to record"
            )
            self._render_sampler()
            self._render_extra_decks()
        else:
            if virtual_key in self.sampler_map:
                mapping = self.sampler_map[virtual_key]
                self.sampler_playing.add(virtual_key)
                self._render_extra_decks()
                threading.Thread(
                    target=self._play_sampler_mapping,
                    args=(virtual_key, mapping),
                    daemon=True,
                ).start()

    def _render_extra_decks(self):
        """Render all extra decks (pure sampler buttons)."""
        for ed, offset, er, ec, et in self.extra_deck_info:
            for key in range(et):
                virtual_key = offset + key
                if virtual_key == self.waiting_assign:
                    set_key(ed, key, (220, 180, 0), "?")
                elif virtual_key in self.sampler_map:
                    mapping = self.sampler_map[virtual_key]
                    if virtual_key in self.sampler_playing:
                        color = (0, 220, 0)
                    else:
                        color = (0, 60, 120)
                    if mapping[0] == "wav":
                        dur_str = mapping[2] if len(mapping) > 2 else "?"
                        label = f"M{dur_str}"
                    else:
                        name = STYLES[mapping[0]] if mapping[0] < len(STYLES) else "?"
                        label = f"{name[:3]}"
                    set_key(ed, key, color, label)
                else:
                    set_key(ed, key, (15, 15, 25), f"{virtual_key}")

    def _reset_all_effects(self):
        """Reset all channel effects to default values."""
        self.freqs = list(BASE_FREQS)
        self.volumes_db = [0.0, 0.0, 0.0, 0.0]
        self.pitch_ratios = [1.0, 1.0, 1.0, 1.0]
        self.ring_freqs = [0.0, 0.0, 0.0, 0.0]
        self.tremolo_rates = [0.0, 0.0, 0.0, 0.0]
        self.reverb_amt = [0.0, 0.0, 0.0, 0.0]
        self.echo_delay = [0.0, 0.0, 0.0, 0.0]
        self.bitcrush_bits = [16.0, 16.0, 16.0, 16.0]
        self.distort_amt = [0.0, 0.0, 0.0, 0.0]
        self.stutter_rate = [0.0, 0.0, 0.0, 0.0]
        self.reverse_on = [0, 0, 0, 0]
        self.dial_modes = ["freq", "freq", "freq", "freq"]
        print("All effects reset to defaults")

    # ── LOOPER ─────────────────────────────────────

    def _toggle_looper(self):
        """Cycle looper: off → rec → play → overdub → off."""
        if self.loop_state == "off":
            self.loop_state = "rec"
            self.loop_buffer = []
            print("Looper: RECORDING")
            # Start capturing mic
            self._loop_rec_path = os.path.join(
                self.save_dir, "_loop_rec.wav"
            )
            try:
                self._loop_proc = subprocess.Popen(
                    [
                        "arecord", "-f", "S16_LE", "-r", str(SAMPLE_RATE),
                        "-c", "1", "-q", self._loop_rec_path,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                self.loop_state = "off"
        elif self.loop_state == "rec":
            # Stop recording, start playback loop
            if hasattr(self, "_loop_proc") and self._loop_proc:
                self._loop_proc.terminate()
                try:
                    self._loop_proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._loop_proc.kill()
            # Load recorded buffer
            try:
                with wave.open(self._loop_rec_path, "rb") as wf:
                    raw = wf.readframes(wf.getnframes())
                    n = wf.getnframes()
                self.loop_buffer = list(struct.unpack(f"<{n}h", raw))
            except Exception:
                self.loop_buffer = []
            if self.loop_buffer:
                self.loop_state = "play"
                print(f"Looper: PLAYING ({len(self.loop_buffer)} samples)")
                self._start_loop_playback()
            else:
                self.loop_state = "off"
        elif self.loop_state == "play":
            self.loop_state = "overdub"
            print("Looper: OVERDUB (recording on top)")
            # Start another mic capture for overdub
            self._loop_overdub_path = os.path.join(
                self.save_dir, "_loop_overdub.wav"
            )
            try:
                self._loop_od_proc = subprocess.Popen(
                    [
                        "arecord", "-f", "S16_LE", "-r", str(SAMPLE_RATE),
                        "-c", "1", "-q", self._loop_overdub_path,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                pass
        elif self.loop_state == "overdub":
            # Stop overdub, mix into loop buffer
            if hasattr(self, "_loop_od_proc") and self._loop_od_proc:
                self._loop_od_proc.terminate()
                try:
                    self._loop_od_proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._loop_od_proc.kill()
            try:
                with wave.open(self._loop_overdub_path, "rb") as wf:
                    raw = wf.readframes(wf.getnframes())
                    n = wf.getnframes()
                overdub = list(struct.unpack(f"<{n}h", raw))
                # Mix overdub into loop buffer
                for i in range(min(len(self.loop_buffer), len(overdub))):
                    self.loop_buffer[i] = max(
                        -32767,
                        min(32767, self.loop_buffer[i] + overdub[i]),
                    )
            except Exception:
                pass
            self.loop_state = "play"
            print("Looper: back to PLAY with overdub mixed")

    def _start_loop_playback(self):
        """Play loop buffer in a repeating thread."""
        if self.loop_thread and self.loop_thread.is_alive():
            return

        def _loop_play():
            while self.loop_state in ("play", "overdub") and self.running:
                if self.loop_buffer:
                    wav_data = samples_to_wav(self.loop_buffer)
                    play_wav_bytes(wav_data)
                else:
                    time.sleep(0.1)

        self.loop_thread = threading.Thread(target=_loop_play, daemon=True)
        self.loop_thread.start()

    def _stop_looper(self):
        """Stop looper completely."""
        self.loop_state = "off"
        self.loop_buffer = []
        for attr in ("_loop_proc", "_loop_od_proc"):
            proc = getattr(self, attr, None)
            if proc:
                try:
                    proc.terminate()
                except Exception:
                    pass

    # ── SEQUENCER ─────────────────────────────────

    def _toggle_sequencer(self):
        """Toggle step sequencer on/off."""
        if self.seq_on:
            self.seq_on = False
            print("Sequencer: OFF")
        else:
            self.seq_on = True
            self.seq_pos = 0
            # Build default pattern from sampler assignments
            self._build_seq_pattern()
            print(f"Sequencer: ON ({self.seq_bpm} BPM, {self.seq_steps} steps)")
            if not self.seq_thread or not self.seq_thread.is_alive():
                self.seq_thread = threading.Thread(
                    target=self._seq_loop, daemon=True
                )
                self.seq_thread.start()

    def _build_seq_pattern(self):
        """Auto-fill sequencer pattern from sampler button assignments."""
        self.seq_pattern = [[] for _ in range(self.seq_steps)]
        assigned_keys = sorted(self.sampler_map.keys())
        for step_idx, key in enumerate(assigned_keys):
            if step_idx < self.seq_steps:
                self.seq_pattern[step_idx].append(key)

    def _seq_loop(self):
        """Sequencer playback loop."""
        while self.seq_on and self.running:
            step_dur = 60.0 / self.seq_bpm
            step = self.seq_pattern[self.seq_pos % self.seq_steps]
            # Play all sounds in this step
            for key in step:
                if key in self.sampler_map:
                    mapping = self.sampler_map[key]
                    threading.Thread(
                        target=self._play_sampler_mapping,
                        args=(key, mapping),
                        daemon=True,
                    ).start()
            self.seq_pos = (self.seq_pos + 1) % self.seq_steps
            time.sleep(step_dur)

    # ── METRONOME ─────────────────────────────────

    def _toggle_metronome(self):
        """Toggle metronome click on/off."""
        if self.metro_on:
            self.metro_on = False
            print("Metronome: OFF")
        else:
            self.metro_on = True
            print(f"Metronome: ON ({self.metro_bpm} BPM)")
            if not self.metro_thread or not self.metro_thread.is_alive():
                self.metro_thread = threading.Thread(
                    target=self._metro_loop, daemon=True
                )
                self.metro_thread.start()

    def _metro_loop(self):
        """Metronome click loop."""
        while self.metro_on and self.running:
            beat_dur = 60.0 / self.metro_bpm
            # Generate a short click (high freq, very short)
            click_samples = generate_tone(
                1, 1000, volume_db=0, duration=0.02
            )
            wav_data = samples_to_wav(click_samples)
            play_wav_bytes(wav_data)
            time.sleep(beat_dur)

    # ── MIXDOWN ───────────────────────────────────

    def _do_mixdown(self):
        """Play all 4 channels simultaneously."""
        print("Mix: playing all channels...")
        threads = []
        for ch in range(4):
            t = threading.Thread(
                target=self._play_tone, args=(ch,), daemon=True
            )
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        print("Mix: done")

    # ── EXPORT ────────────────────────────────────

    def _toggle_export(self):
        """Toggle export recording."""
        if self.exporting:
            self._stop_export()
        else:
            self._start_export()

    def _start_export(self):
        """Start recording system audio output to WAV."""
        timestamp = int(time.time())
        self.export_path = os.path.join(
            self.save_dir, f"export_{timestamp}.wav"
        )
        try:
            # Record from default audio monitor (mic captures speaker)
            self._export_proc = subprocess.Popen(
                [
                    "arecord", "-f", "S16_LE", "-r", str(SAMPLE_RATE),
                    "-c", "1", "-q", self.export_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.exporting = True
            self.export_start = time.monotonic()
            print(f"Export: recording to {self.export_path}")
        except FileNotFoundError:
            print("Export: arecord not found")

    def _stop_export(self):
        """Stop export recording."""
        if hasattr(self, "_export_proc") and self._export_proc:
            self._export_proc.terminate()
            try:
                self._export_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._export_proc.kill()
        self.exporting = False
        duration = time.monotonic() - self.export_start
        print(f"Export: saved {duration:.1f}s to {self.export_path}")

    def save_state(self):
        """Save current DJ state to JSON."""
        state = {
            "styles": self.styles,
            "freqs": self.freqs,
            "volumes_db": self.volumes_db,
            "pitch_ratios": self.pitch_ratios,
            "ring_freqs": self.ring_freqs,
            "tremolo_rates": self.tremolo_rates,
            "reverb_amt": self.reverb_amt,
            "echo_delay": self.echo_delay,
            "bitcrush_bits": self.bitcrush_bits,
            "distort_amt": self.distort_amt,
            "stutter_rate": self.stutter_rate,
            "reverse_on": self.reverse_on,
            "dial_modes": self.dial_modes,
            "channel_samples": self.channel_samples,
            "sampler_map": {},
        }
        # Serialize sampler_map (tuples to lists)
        for k, v in self.sampler_map.items():
            if v[0] == "wav":
                state["sampler_map"][str(k)] = list(v)
            else:
                state["sampler_map"][str(k)] = list(v)
        save_path = os.path.join(self.save_dir, "djscratch_state.json")
        try:
            with open(save_path, "w") as f:
                json.dump(state, f, indent=2, default=str)
            print(f"State saved to {save_path}")
        except Exception as e:
            print(f"Save failed: {e}")

    def load_state(self):
        """Load DJ state from JSON if exists."""
        save_path = os.path.join(self.save_dir, "djscratch_state.json")
        if not os.path.isfile(save_path):
            return False
        try:
            with open(save_path) as f:
                state = json.load(f)
            self.styles = state.get("styles", self.styles)
            self.freqs = state.get("freqs", self.freqs)
            self.volumes_db = state.get("volumes_db", self.volumes_db)
            self.pitch_ratios = state.get("pitch_ratios", self.pitch_ratios)
            self.ring_freqs = state.get("ring_freqs", self.ring_freqs)
            self.tremolo_rates = state.get("tremolo_rates", self.tremolo_rates)
            self.reverb_amt = state.get("reverb_amt", self.reverb_amt)
            self.echo_delay = state.get("echo_delay", self.echo_delay)
            self.bitcrush_bits = state.get("bitcrush_bits", self.bitcrush_bits)
            self.distort_amt = state.get("distort_amt", self.distort_amt)
            self.stutter_rate = state.get("stutter_rate", self.stutter_rate)
            self.reverse_on = state.get("reverse_on", self.reverse_on)
            self.dial_modes = state.get("dial_modes", self.dial_modes)
            self.channel_samples = {
                int(k): v
                for k, v in state.get("channel_samples", {}).items()
            }
            # Restore sampler map
            self.sampler_map = {}
            for k, v in state.get("sampler_map", {}).items():
                if v and v[0] == "wav":
                    # Check WAV file still exists
                    if len(v) > 1 and os.path.isfile(v[1]):
                        self.sampler_map[int(k)] = tuple(v)
                elif v:
                    self.sampler_map[int(k)] = tuple(v)
            print(f"State loaded from {save_path}")
            return True
        except Exception as e:
            print(f"Load failed: {e}")
            return False

    def _find_mic_channel(self):
        """Find which channel is set to Mic style, or -1."""
        for i in range(4):
            if self.styles[i] == 4:
                return i
        return -1

    def _start_mic(self):
        """Start recording from microphone via arecord."""
        if self.waiting_assign < 0:
            return
        timestamp = int(time.time())
        self.mic_wav_path = os.path.join(
            self.save_dir, f"rec_{self.waiting_assign}_{timestamp}.wav"
        )
        # Capture ALL mic channel params at record start
        mic_ch = self._find_mic_channel()
        if mic_ch >= 0:
            self.mic_rec_params = self._get_channel_params(mic_ch)
        else:
            self.mic_rec_params = {
                "vol_db": 0.0, "pitch": 1.0, "ring": 0, "tremolo": 0,
            }
        try:
            self.mic_process = subprocess.Popen(
                [
                    "arecord",
                    "-f", "S16_LE",
                    "-r", str(SAMPLE_RATE),
                    "-c", "1",
                    "-q",
                    self.mic_wav_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.mic_recording = True
            self.mic_start_time = time.monotonic()
            vol = self.mic_rec_params.get("vol_db", 0)
            print(
                f"MIC recording started: {self.mic_wav_path} "
                f"(vol={vol:+.0f}dB)"
            )
        except FileNotFoundError:
            print("arecord not found - cannot record from mic")

    def _stop_mic(self):
        """Stop mic recording, apply volume, assign to button."""
        if not self.mic_recording or not self.mic_process:
            return
        self.mic_process.terminate()
        try:
            self.mic_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.mic_process.kill()
        self.mic_recording = False
        duration = time.monotonic() - self.mic_start_time
        self.mic_process = None

        if self.waiting_assign >= 0 and os.path.isfile(self.mic_wav_path):
            params = getattr(self, "mic_rec_params", {})

            # Apply ALL effects to recorded WAV
            try:
                with wave.open(self.mic_wav_path, "rb") as wf:
                    wp = wf.getparams()
                    raw = wf.readframes(wf.getnframes())
                    n = wf.getnframes()
                samples = list(struct.unpack(f"<{n}h", raw))
                samples = self._apply_effects_chain(samples, params)
                with wave.open(self.mic_wav_path, "wb") as wf:
                    wf.setparams(wp)
                    wf.writeframes(
                        struct.pack(f"<{len(samples)}h", *samples)
                    )
            except Exception as e:
                print(f"Effect apply failed: {e}")

            dur_str = f"{duration:.1f}s"
            # Build compact effect summary
            fx = []
            if abs(params.get("vol_db", 0)) > 0.5:
                fx.append(f"{params['vol_db']:+.0f}dB")
            if abs(params.get("pitch", 1.0) - 1.0) > 0.05:
                fx.append(f"x{params['pitch']:.1f}")
            if params.get("ring", 0) > 0:
                fx.append(f"R{int(params['ring'])}")
            if params.get("tremolo", 0) > 0:
                fx.append(f"T{int(params['tremolo'])}")
            fx_str = " ".join(fx) if fx else "0dB"

            self.sampler_map[self.waiting_assign] = (
                "wav", self.mic_wav_path, dur_str, params
            )
            print(
                f"MIC assigned to key {self.waiting_assign}: "
                f"{dur_str} [{fx_str}] ({self.mic_wav_path})"
            )
            self.waiting_assign = -1
        self._render_sampler()

    def _apply_effects_to_wav(self, path, volume_db, freq, mode):
        """Apply volume + effects to a WAV file in-place."""
        try:
            with wave.open(path, "rb") as wf:
                params = wf.getparams()
                raw = wf.readframes(wf.getnframes())
                n = wf.getnframes()
            samples = list(struct.unpack(f"<{n}h", raw))
            adjusted = self._apply_effects(samples, volume_db, freq, mode)
            with wave.open(path, "wb") as wf:
                wf.setparams(params)
                wf.writeframes(
                    struct.pack(f"<{len(adjusted)}h", *adjusted)
                )
        except Exception as e:
            print(f"Effect apply failed: {e}")

    def _start_sam(self):
        """Start recording a sample for Mic passthrough on deck 1."""
        mic_ch = self._find_mic_channel()
        if mic_ch < 0:
            print("Set a channel to Mic style first on deck 1")
            return
        timestamp = int(time.time())
        self.sam_wav_path = os.path.join(
            self.save_dir, f"sample_ch{mic_ch}_{timestamp}.wav"
        )
        self.sam_target_channel = mic_ch
        try:
            self.sam_process = subprocess.Popen(
                [
                    "arecord", "-f", "S16_LE", "-r", str(SAMPLE_RATE),
                    "-c", "1", "-q", self.sam_wav_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.sam_recording = True
            self.sam_start_time = time.monotonic()
            print(f"SAM recording for channel {mic_ch}: {self.sam_wav_path}")
        except FileNotFoundError:
            print("arecord not found")

    def _stop_sam(self):
        """Stop sample recording and assign to mic channel."""
        if not self.sam_recording or not self.sam_process:
            return
        self.sam_process.terminate()
        try:
            self.sam_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.sam_process.kill()
        self.sam_recording = False
        duration = time.monotonic() - self.sam_start_time
        self.sam_process = None
        ch = getattr(self, "sam_target_channel", -1)
        path = getattr(self, "sam_wav_path", "")
        if ch >= 0 and os.path.isfile(path):
            self.channel_samples[ch] = path
            print(
                f"Sample assigned to Mic channel {ch}: "
                f"{duration:.1f}s ({path})"
            )
        self._render_sampler()

    def _play_sampler_mapping(self, key, mapping):
        """Play a sampler mapping (tone or wav file)."""
        if mapping[0] == "wav":
            self._play_wav_file(mapping[1])
        else:
            style = mapping[0]
            freq = mapping[1]
            vol_db = mapping[2] if len(mapping) > 2 else 0.0
            self._play_sound(style, freq, vol_db)
        self.sampler_playing.discard(key)
        self._render_sampler()

    def _play_wav_file(self, path):
        """Play a WAV file directly on speaker."""
        if not os.path.isfile(path):
            return
        for cmd in [
            ["aplay", "-q", path],
            ["pw-play", path],
        ]:
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                proc.wait()
                return
            except FileNotFoundError:
                continue

    def _render_sampler(self):
        """Render the sampler deck (deck 2). Adapts to any layout."""
        if not self.sampler_deck:
            return
        deck = self.sampler_deck
        for key in range(self.sampler_total):
            r = key // self.sampler_cols
            c = key % self.sampler_cols

            # REC button (row 0, col 0)
            if key == self.key_rec:
                if self.record_mode:
                    set_key(deck, key, (220, 0, 0), "REC")
                else:
                    set_key(deck, key, (80, 0, 0), "REC")
                continue

            # MIC button (row 1, col 0) - only visible in record mode
            if key == self.key_mic:
                if self.record_mode:
                    if self.mic_recording:
                        elapsed = time.monotonic() - self.mic_start_time
                        set_key(deck, key, (255, 40, 40), f"{elapsed:.0f}s")
                    elif self.waiting_assign >= 0:
                        set_key(deck, key, (180, 0, 180), "MIC")
                    else:
                        set_key(deck, key, (60, 0, 60), "MIC")
                else:
                    set_key(deck, key, (20, 20, 30), "")
                continue

            # SAM button (row 2, col 0) - record sample for Mic channel
            if key == self.key_sam and self.key_sam >= 0:
                if self.record_mode:
                    if self.sam_recording:
                        elapsed = time.monotonic() - self.sam_start_time
                        set_key(deck, key, (255, 80, 0), f"{elapsed:.0f}s")
                    else:
                        mic_ch = self._find_mic_channel()
                        has_sample = mic_ch >= 0 and mic_ch in self.channel_samples
                        if has_sample:
                            set_key(deck, key, (100, 60, 0), "SAM*")
                        else:
                            set_key(deck, key, (80, 40, 0), "SAM")
                else:
                    set_key(deck, key, (20, 20, 30), "")
                continue

            # RST button (row 3, col 0)
            if key == self.key_rst and self.key_rst >= 0:
                set_key(deck, key, (60, 60, 60), "RST")
                continue

            # LOOP button
            if key == self.key_loop and self.key_loop >= 0:
                colors = {
                    "off": (40, 40, 40), "rec": (220, 0, 0),
                    "play": (0, 180, 0), "overdub": (220, 120, 0),
                }
                labels = {
                    "off": "LOOP", "rec": "REC.",
                    "play": "PLAY", "overdub": "ODUB",
                }
                set_key(deck, key, colors.get(self.loop_state, (40, 40, 40)),
                        labels.get(self.loop_state, "LOOP"))
                continue

            # SEQ button
            if key == self.key_seq and self.key_seq >= 0:
                if self.seq_on:
                    step = self.seq_pos % self.seq_steps
                    set_key(deck, key, (0, 120, 120), f"S:{step + 1}")
                else:
                    set_key(deck, key, (0, 50, 50), "SEQ")
                continue

            # MET button (metronome)
            if key == self.key_met and self.key_met >= 0:
                if self.metro_on:
                    set_key(deck, key, (180, 180, 0), f"{self.metro_bpm}")
                else:
                    set_key(deck, key, (60, 60, 0), "MET")
                continue

            # MIX button
            if key == self.key_mix and self.key_mix >= 0:
                set_key(deck, key, (80, 0, 120), "MIX")
                continue

            # EXP button
            if key == self.key_exp and self.key_exp >= 0:
                if self.exporting:
                    dur = time.monotonic() - self.export_start
                    set_key(deck, key, (220, 0, 0), f"{dur:.0f}s")
                else:
                    set_key(deck, key, (0, 60, 40), "EXP")
                continue

            # Waiting for assignment
            if key == self.waiting_assign:
                set_key(deck, key, (220, 180, 0), "?")
                continue

            # Assigned key
            if key in self.sampler_map:
                mapping = self.sampler_map[key]
                if mapping[0] == "wav":
                    # Mic recording: show dur + all effects
                    dur_str = mapping[2] if len(mapping) > 2 else "?"
                    params = mapping[3] if len(mapping) > 3 else {}
                    if isinstance(params, dict):
                        fx = []
                        v = params.get("vol_db", 0)
                        if abs(v) > 0.5:
                            fx.append(f"{v:+.0f}")
                        p = params.get("pitch", 1.0)
                        if abs(p - 1.0) > 0.05:
                            fx.append(f"x{p:.1f}")
                        r = params.get("ring", 0)
                        if r > 0:
                            fx.append(f"R{int(r)}")
                        t = params.get("tremolo", 0)
                        if t > 0:
                            fx.append(f"T{int(t)}")
                        fx_str = " ".join(fx) if fx else "0dB"
                    else:
                        fx_str = f"{params:+.0f}dB" if isinstance(params, (int, float)) else ""
                    label = f"{dur_str} {fx_str}"
                    if key in self.sampler_playing:
                        set_key(deck, key, (255, 40, 40), label)
                    else:
                        set_key(deck, key, (80, 20, 20), label)
                else:
                    # Tone (style, freq, vol_db)
                    style = mapping[0]
                    freq = mapping[1]
                    vol_db = mapping[2] if len(mapping) > 2 else 0.0
                    color = STYLE_COLORS[style]
                    if key in self.sampler_playing:
                        set_key(deck, key, color, f"{int(freq)}")
                    else:
                        dim = (color[0] // 3, color[1] // 3, color[2] // 3)
                        label = f"{STYLES[style][:2]}{vol_db:+.0f}"
                        set_key(deck, key, dim, label)
                continue

            # Empty slot
            if self.record_mode and not self._is_control_key(key):
                set_key(deck, key, (30, 30, 40), "+")
            else:
                set_key(deck, key, (20, 20, 30), "")
        # Also refresh extra decks
        self._render_extra_decks()

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

            # Top row: mode indicator per channel (filtered by style)
            if r == 0 and c < 4:
                mode = self.dial_modes[c]
                style = self.styles[c]
                avail = STYLE_MODES.get(style, DIAL_MODES)
                color = MODE_COLORS.get(mode, (60, 60, 60))
                label = MODE_LABELS.get(mode, mode)
                # Show position in available modes
                if len(avail) > 1:
                    pos = avail.index(mode) + 1 if mode in avail else 1
                    label = f"{label}{pos}/{len(avail)}"
                set_key(self.deck, key, color, label)
                continue

            # Bottom row: sound buttons (style + params on 2 lines)
            if r == last_r and c < 4:
                style = self.styles[c]
                freq_hz = int(self.freqs[c])
                vol_db = self.volumes_db[c]
                mode = self.dial_modes[c]
                style_name = STYLES[style][:3]

                if self.playing[c]:
                    color = STYLE_COLORS[style]
                else:
                    bright = min(255, int(abs(self.speeds[c]) * 30))
                    color = tuple(
                        min(255, v * max(40, bright) // 255)
                        for v in STYLE_COLORS[style]
                    )

                # Line 2: show value of the ACTIVE mode (dial controls this)
                pitch_r = self.pitch_ratios[c]
                ring_f = int(self.ring_freqs[c])
                trem_r = int(self.tremolo_rates[c])

                if mode == "vol":
                    line2 = f"{vol_db:+.0f}dB"
                elif mode == "pitch":
                    line2 = f"x{pitch_r:.1f}"
                elif mode == "ring":
                    line2 = f"R:{ring_f}Hz" if ring_f > 0 else "OFF"
                elif mode == "tremolo":
                    line2 = f"T:{trem_r}Hz" if trem_r > 0 else "OFF"
                elif mode == "reverb":
                    rv = int(self.reverb_amt[c])
                    line2 = f"RV:{rv}%" if rv > 0 else "OFF"
                elif mode == "echo":
                    ec = int(self.echo_delay[c])
                    line2 = f"EC:{ec}ms" if ec > 0 else "OFF"
                elif mode == "bitcrush":
                    bc = int(self.bitcrush_bits[c])
                    line2 = f"CR:{bc}bit" if bc < 16 else "OFF"
                elif mode == "distort":
                    dt = int(self.distort_amt[c])
                    line2 = f"DT:{dt}%" if dt > 0 else "OFF"
                elif mode == "stutter":
                    st = int(self.stutter_rate[c])
                    line2 = f"ST:{st}Hz" if st > 0 else "OFF"
                elif mode == "reverse":
                    line2 = "ON" if self.reverse_on[c] else "OFF"
                else:
                    line2 = f"{freq_hz}Hz"

                # Build compact summary of non-default effects
                fx_parts = []
                if abs(vol_db) > 0.5:
                    fx_parts.append(f"{vol_db:+.0f}")
                if abs(pitch_r - 1.0) > 0.05:
                    fx_parts.append(f"x{pitch_r:.1f}")
                if ring_f > 0:
                    fx_parts.append(f"R{ring_f}")
                if trem_r > 0:
                    fx_parts.append(f"T{trem_r}")
                if self.reverb_amt[c] > 0:
                    fx_parts.append("RV")
                if self.echo_delay[c] > 0:
                    fx_parts.append("EC")
                if self.bitcrush_bits[c] < 16:
                    fx_parts.append("CR")
                if self.distort_amt[c] > 0:
                    fx_parts.append("DT")
                if self.stutter_rate[c] > 0:
                    fx_parts.append("ST")
                if self.reverse_on[c]:
                    fx_parts.append("RV")
                fx_summary = " ".join(fx_parts)

                if fx_summary:
                    self._set_key_2lines(key, color, style_name, f"{line2} {fx_summary}")
                else:
                    self._set_key_2lines(key, color, style_name, line2)
                continue

            set_key(self.deck, key, (20, 20, 30), "")

    def _set_key_2lines(self, key, color, line1, line2):
        """Render a key with 2 lines of text."""
        fmt = self.deck.key_image_format()
        w, h = fmt["size"]
        img = Image.new("RGB", (w, h), color)
        draw = ImageDraw.Draw(img)
        try:
            font_top = ImageFont.load_default(size=14)
            font_bot = ImageFont.load_default(size=10)
        except TypeError:
            font_top = ImageFont.load_default()
            font_bot = font_top

        # Line 1 (top, bigger)
        bbox1 = draw.textbbox((0, 0), line1, font=font_top)
        tw1 = bbox1[2] - bbox1[0]
        tx1 = (w - tw1) // 2
        draw.text((tx1 + 1, h // 4 - 6), line1, fill=(0, 0, 0), font=font_top)
        draw.text((tx1, h // 4 - 7), line1, fill=(255, 255, 255), font=font_top)

        # Line 2 (bottom, smaller)
        bbox2 = draw.textbbox((0, 0), line2, font=font_bot)
        tw2 = bbox2[2] - bbox2[0]
        tx2 = (w - tw2) // 2
        draw.text((tx2 + 1, h * 3 // 4 - 6), line2, fill=(0, 0, 0), font=font_bot)
        draw.text((tx2, h * 3 // 4 - 7), line2, fill=(200, 200, 200), font=font_bot)

        native = PILHelper.to_native_key_format(self.deck, img)
        try:
            with self.deck:
                self.deck.set_key_image(key, native)
        except TransportError:
            pass

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

    # Find second deck as sampler, rest as extra sampler extensions
    sampler_deck = None
    extra_decks = []
    for d in visual:
        if d is not main_deck:
            if sampler_deck is None:
                sampler_deck = d
            else:
                extra_decks.append(d)

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

    for i, ed in enumerate(extra_decks):
        er, ec = ed.key_layout()
        print(f"\nEXTRA SAMPLER {i + 1}: {ed.deck_type()} ({ec}x{er})")
        print("  Extended memory bank — all buttons are sampler slots")

    game = DJScratch(main_deck, sampler_deck=sampler_deck,
                     extra_decks=extra_decks)
    if game.load_state():
        print("Previous session restored!")
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

    for i, ed in enumerate(extra_decks):
        di = i + 2  # deck_index 2, 3, 4...
        def make_extra_cb(deck_idx):
            def extra_key_cb(d, k, s):
                with game.lock:
                    game.handle_key(k, s, deck_index=deck_idx)
            return extra_key_cb
        ed.set_key_callback(make_extra_cb(di))

    t = threading.Thread(target=game.loop, daemon=True)
    t.start()

    # Initial render of extra decks
    game._render_extra_decks()

    all_decks = (
        [main_deck]
        + ([sampler_deck] if sampler_deck else [])
        + extra_decks
    )
    try:
        while all(d.is_open() for d in all_decks):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        game.running = False
        game.metro_on = False
        game.seq_on = False
        game._stop_looper()
        if game.exporting:
            game._stop_export()
        game.save_state()
        for d in all_decks:
            try:
                with d:
                    d.reset()
                    d.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
