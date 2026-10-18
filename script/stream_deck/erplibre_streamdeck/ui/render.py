# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Painting one key, and the display style every key follows.

set_key reads STYLE at each call: a change of font scale or labels shows
on the next paint. The font is looked up on first use."""

import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
    from StreamDeck.ImageHelpers import PILHelper
    from StreamDeck.Transport.Transport import TransportError
except ImportError as e:
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

from erplibre_streamdeck.ui import colors, icons

FONT_SCALE_MIN = 0.6
FONT_SCALE_MAX = 2.5
FONT_SCALE_STEP = 0.1
FONT_SCALE_DEFAULT = 1.0


class Style:
    """Font scale and label visibility of every key."""

    def __init__(self):
        self.font_scale = FONT_SCALE_DEFAULT
        self.show_labels = False

    def restore(self, data):
        """Take font_scale (clamped) and show_labels from a settings
        dict; a value that is not a number gives the default."""
        try:
            val = float(data.get("font_scale", FONT_SCALE_DEFAULT))
            self.font_scale = max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, val))
        except (ValueError, TypeError):
            self.font_scale = FONT_SCALE_DEFAULT
        self.show_labels = bool(data.get("show_labels", False))

    def set_font_scale(self, scale, settings):
        """Clamp and keep the scale; settings.json stores it rounded to
        two places, the value in memory stays exact."""
        self.font_scale = max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, scale))
        data = settings.load()
        data["font_scale"] = round(self.font_scale, 2)
        settings.save(data)

    def toggle_labels(self, settings):
        self.show_labels = not self.show_labels
        data = settings.load()
        data["show_labels"] = self.show_labels
        settings.save(data)


STYLE = Style()

# Pillow's `load_default()` returns a tiny Latin-1 bitmap that
# renders missing glyphs as boxes — French accents, Spotify's "▶"
# etc. all break visually. Cache one TrueType font that ships on
# Debian / Fedora / Arch (DejaVu) and fall back to PIL's default
# only when it is genuinely missing.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)
_FONT_PATH = None


def _font_path():
    """The first font of _FONT_CANDIDATES present on this host, looked
    up once; None when none is installed."""
    global _FONT_PATH
    if _FONT_PATH is None:
        for candidate in _FONT_CANDIDATES:
            if os.path.isfile(candidate):
                _FONT_PATH = candidate
                break
    return _FONT_PATH


def load_label_font(fs):
    """Return a font sized `fs` with broad Unicode coverage."""
    path = _font_path()
    if path:
        try:
            return ImageFont.truetype(path, fs)
        except (OSError, IOError):
            pass
    try:
        return ImageFont.load_default(size=fs)
    except TypeError:
        return ImageFont.load_default()


def set_key(deck, key, color, text="", icon=None, extra_draw=None):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    draw = ImageDraw.Draw(img)
    if icon and icon in icons.ICONS:
        icons.ICONS[icon](draw, w, h)
    if extra_draw:
        try:
            extra_draw(draw, w, h)
        except Exception as e:
            print(f"extra_draw failed: {e}", file=sys.stderr, flush=True)
    if text and (icon is None or STYLE.show_labels):
        base_fs = 20 if len(text) <= 2 else 14 if len(text) <= 4 else 11
        fs = max(6, int(round(base_fs * STYLE.font_scale)))
        font = load_label_font(fs)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            ((w - tw) // 2 + 1, (h - th) // 2 + 1),
            text, fill=(0, 0, 0), font=font,
        )
        draw.text(
            ((w - tw) // 2, (h - th) // 2),
            text, fill=(255, 255, 255), font=font,
        )
    native = PILHelper.to_native_key_format(deck, img)
    try:
        with deck:
            deck.set_key_image(key, native)
    except TransportError:
        pass


def too_small(ctx):
    """The page a deck too small for it shows: BACK on key 0, the
    warning in the middle key, the rest empty."""
    total = ctx.geo.total_keys
    for key in range(total):
        if key == 0:
            ctx.set_key(key, colors.BACK, ctx.t("BACK"))
        elif key == total // 2:
            ctx.set_key(key, colors.ERR, ctx.t("DECK\nTOO\nSMALL"))
        else:
            ctx.set_key(key, colors.EMPTY, "")
