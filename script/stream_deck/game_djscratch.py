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

STYLES = ["Sine", "Square", "Saw", "Noise", "Mic"]
STYLE_COLORS = [
    (0, 200, 255), (255, 100, 0), (0, 255, 100), (255, 0, 200), (255, 40, 80),
]
BASE_FREQS = [261.63, 329.63, 392.00, 523.25]  # C4, E4, G4, C5
SAMPLE_RATE = 22050
DURATION = 0.3
VOLUME = 0.5
DIAL_MODES = ["freq", "vol", "pitch", "ring", "tremolo"]
MODE_COLORS = {
    "freq": (0, 60, 120),
    "vol": (120, 60, 0),
    "pitch": (0, 120, 60),
    "ring": (120, 0, 120),
    "tremolo": (60, 120, 0),
}
MODE_LABELS = {
    "freq": "FREQ",
    "vol": "VOL",
    "pitch": "PTCH",
    "ring": "RING",
    "tremolo": "TREM",
}


def generate_tone(style, freq, volume_db=0.0, duration=DURATION, rate=SAMPLE_RATE):
    """Generate raw PCM samples for a tone with volume in dB."""
    n_samples = int(rate * duration)
    linear_vol = min(32.0, 10 ** (volume_db / 20.0)) * VOLUME
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
        self.volumes_db = [0.0, 0.0, 0.0, 0.0]  # dB (-40 to +30)
        self.pitch_ratios = [1.0, 1.0, 1.0, 1.0]  # pitch multiplier
        self.ring_freqs = [0.0, 0.0, 0.0, 0.0]  # ring mod Hz (0=off)
        self.tremolo_rates = [0.0, 0.0, 0.0, 0.0]  # tremolo Hz (0=off)
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
        else:
            self.sampler_cols = 0
            self.sampler_rows = 0
            self.sampler_total = 0
            self.key_rec = 0
            self.key_mic = 0
            self.key_sam = -1
            self.key_rst = -1

    def _db_to_linear(self, db):
        """Convert dB to linear volume (0.0 to ~2.0)."""
        return 10 ** (db / 20.0)

    def handle_dial(self, dial, event, value):
        if dial >= 4:
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
        elif event == DialEventType.PUSH and value:
            self.styles[dial] = (self.styles[dial] + 1) % len(STYLES)

    def handle_key(self, key, state, deck_index=0):
        if deck_index == 1:
            self._handle_sampler_key(key, state)
            return

        col = key % self.cols
        row = key // self.cols
        last_r = self.rows - 1

        # Top row = cycle mode per channel (independent)
        if row == 0 and col < 4 and state:
            cur = self.dial_modes[col]
            idx = DIAL_MODES.index(cur)
            self.dial_modes[col] = DIAL_MODES[(idx + 1) % len(DIAL_MODES)]
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
        """Apply ALL effects in chain: pitch → ring → tremolo → volume."""
        n = len(samples)
        vol_db = params.get("vol_db", 0.0)
        pitch = params.get("pitch", 1.0)
        ring_freq = params.get("ring", 0)
        trem_rate = params.get("tremolo", 0)
        linear_vol = min(32.0, 10 ** (vol_db / 20.0))

        # 1. Pitch shift (resample)
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

        result = []
        for i in range(len(samples)):
            val = float(samples[i])
            t = i / SAMPLE_RATE

            # 2. Ring modulation
            if ring_freq > 0:
                val *= math.sin(2 * math.pi * ring_freq * t)

            # 3. Tremolo
            if trem_rate > 0:
                val *= 0.5 + 0.5 * math.sin(2 * math.pi * trem_rate * t)

            # 4. Volume
            val *= linear_vol

            result.append(int(val))

        return [max(-32767, min(32767, s)) for s in result]

    def _play_sound(self, style, freq, volume_db=0.0):
        """Generate and play a specific tone."""
        samples = generate_tone(style, freq, volume_db=volume_db)
        wav_data = samples_to_wav(samples)
        play_wav_bytes(wav_data)

    def _is_control_key(self, key):
        """Check if key is REC, MIC, SAM or RST control."""
        return key in (self.key_rec, self.key_mic, self.key_sam, self.key_rst)

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

    def _reset_all_effects(self):
        """Reset all channel effects to default values."""
        self.freqs = list(BASE_FREQS)
        self.volumes_db = [0.0, 0.0, 0.0, 0.0]
        self.pitch_ratios = [1.0, 1.0, 1.0, 1.0]
        self.ring_freqs = [200.0, 200.0, 200.0, 200.0]
        self.tremolo_rates = [5.0, 5.0, 5.0, 5.0]
        self.dial_modes = ["freq", "freq", "freq", "freq"]
        print("All effects reset to defaults")

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
            print(
                f"MIC recording started: {self.mic_wav_path} "
                f"(vol={self.mic_rec_volume_db:+.0f}dB)"
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

            # RST button (row 3, col 0) = reset all effects
            if key == self.key_rst and self.key_rst >= 0:
                set_key(deck, key, (60, 60, 60), "RST")
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

            # Top row: mode indicator per channel (independent)
            if r == 0 and c < 4:
                mode = self.dial_modes[c]
                color = MODE_COLORS.get(mode, (60, 60, 60))
                label = MODE_LABELS.get(mode, mode)
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
