#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le type réel et les dimensions d'une image, lus par le noyau dans ses
octets : PNG, JPEG (variantes), GIF, WebP, contenus qui n'en sont pas,
bornes de taille et de dimensions, parcours bornés.

N'importe que la bibliothèque standard et `erplibre_mail_core` : tourne
aussi sous le Python du venv d'Odoo. Les images sont fabriquées ici.
"""

import struct
import sys
import time
import unittest
import zlib
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE / "script" / "lib" / "erplibre_mail_core") not in sys.path:
    sys.path.insert(0, str(RACINE / "script" / "lib" / "erplibre_mail_core"))

from erplibre_mail_core.i18n import t, using_lang  # noqa: E402
from erplibre_mail_core.rules import media  # noqa: E402

RASTER = ("image/png", "image/jpeg", "image/gif")


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + body + struct.pack(">I", crc)


def png_bytes(width=1, height=1, extra_text=b"") -> bytes:
    """Un PNG valide en niveaux de gris ; `extra_text` remplit un bloc
    `tEXt`."""
    row = b"\x00" + b"\x00" * width
    data = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(
            b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
        )
        + _chunk(b"IDAT", zlib.compress(row * min(height, 1)))
    )
    if extra_text:
        data += _chunk(b"tEXt", b"Comment\x00" + extra_text)
    return data + _chunk(b"IEND", b"")


def jpeg_bytes(width=2, height=3, app=b"\xe0", progressive=False) -> bytes:
    """Un JPEG d'en-têtes : SOI, APPn, DQT minimal, SOF0 ou SOF2, SOS,
    EOI."""
    sof = b"\xc2" if progressive else b"\xc0"
    return (
        b"\xff\xd8"
        + b"\xff"
        + app
        + struct.pack(">H", 6)
        + b"ABCD"
        + b"\xff\xdb"
        + struct.pack(">H", 67)
        + b"\x00"
        + bytes(64)
        + b"\xff"
        + sof
        + struct.pack(">HBHHB", 11, 8, height, width, 1)
        + b"\x01\x11\x00"
        + b"\xff\xda"
        + struct.pack(">H", 8)
        + b"\x01\x01\x00\x00\x3f\x00"
        + b"\x00\x00"
        + b"\xff\xd9"
    )


def gif_frame(left=0, top=0, width=1, height=1) -> bytes:
    return (
        b"\x2c"
        + struct.pack("<HHHH", left, top, width, height)
        + b"\x00"
        + b"\x02\x02\x44\x01\x00"
    )


def gif_bytes(width=1, height=1, version=b"GIF89a", frames=None) -> bytes:
    """Un GIF : écran logique, table globale de deux couleurs, une image
    d'un pixel (ou `frames`), `;`."""
    head = version + struct.pack("<HHBBB", width, height, 0x80, 0, 0)
    table = b"\x00\x00\x00\xff\xff\xff"
    body = gif_frame() if frames is None else frames
    return head + table + body + b";"


def webp_bytes(kind=b"VP8X", width=5, height=7) -> bytes:
    """Un WebP d'en-têtes : `VP8X`, `VP8L` ou `VP8 `."""
    if kind == b"VP8X":
        payload = (
            b"\x00\x00\x00\x00"
            + (width - 1).to_bytes(3, "little")
            + (height - 1).to_bytes(3, "little")
        )
    elif kind == b"VP8L":
        bits = (width - 1) | ((height - 1) << 14)
        payload = b"\x2f" + bits.to_bytes(4, "little") + b"\x00"
    else:
        payload = (
            b"\x00\x00\x00"
            + b"\x9d\x01\x2a"
            + struct.pack("<HH", width, height)
            + b"\x00\x00"
        )
    chunk = kind + struct.pack("<I", len(payload)) + payload
    return b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk


class MediaCase(unittest.TestCase):
    def setUp(self):
        patch = using_lang("fr")
        patch.__enter__()
        self.addCleanup(patch.__exit__, None, None, None)

    def sniffed(self, data, mime, width, height):
        info = media.sniff_image(data)
        self.assertIsNotNone(info)
        self.assertEqual(
            (info.mime, info.width, info.height), (mime, width, height)
        )


class TestSniff(MediaCase):
    def test_png_is_sniffed_with_its_size(self):
        """Un PNG rend son type et les dimensions de son `IHDR`."""
        self.sniffed(png_bytes(17, 4), "image/png", 17, 4)

    def test_jpeg_variants_are_sniffed(self):
        """APP0, APP1, APP14 (`FFEE`), progressif, et des octets `FF` de
        remplissage entre deux segments."""
        for app in (b"\xe0", b"\xe1", b"\xee"):
            with self.subTest(app=app):
                self.sniffed(jpeg_bytes(30, 20, app=app), "image/jpeg", 30, 20)
        self.sniffed(jpeg_bytes(9, 8, progressive=True), "image/jpeg", 9, 8)
        rempli = jpeg_bytes(6, 5)
        rempli = rempli[:2] + b"\xff\xff" + rempli[2:]
        self.sniffed(rempli, "image/jpeg", 6, 5)

    def test_gif_and_webp_are_sniffed(self):
        """GIF87a et GIF89a ; WebP `VP8X`, `VP8L` et `VP8 `."""
        for version in (b"GIF87a", b"GIF89a"):
            self.sniffed(gif_bytes(3, 2, version), "image/gif", 3, 2)
        for kind in (b"VP8X", b"VP8L", b"VP8 "):
            with self.subTest(kind=kind):
                self.sniffed(webp_bytes(kind, 5, 7), "image/webp", 5, 7)

    def test_content_that_is_not_an_image_is_refused(self):
        """HTML, SVG, PNG tronqué, `IHDR` nul, JPEG sans SOF, JPEG coupé
        en plein SOF, octet qui n'est pas `FF` à la place d'un marqueur,
        octets vides : None, jamais d'exception."""
        jpeg = jpeg_bytes(4, 4)
        sof = jpeg.index(b"\xff\xc0")
        sans_sof = jpeg[:sof] + jpeg[jpeg.index(b"\xff\xda") :]
        cas = [
            b"<html><body>bonjour</body></html>",
            b'<svg xmlns="http://www.w3.org/2000/svg"/>',
            png_bytes()[:20],
            png_bytes(0, 0),
            sans_sof,
            jpeg[:sof] + b"\x00" + jpeg[sof + 1 :],
            b"",
        ]
        cas += [jpeg[: sof + n] for n in range(1, 9)]
        for data in cas:
            with self.subTest(data=data[:40]):
                self.assertIsNone(media.sniff_image(data))


class TestCheck(MediaCase):
    def test_check_raster_codes(self):
        """`type`, `size`, `pixels` (côté de 8001, surface de 4001 ×
        4001)."""
        cas = [
            (b"<html/>", {}, "type", "mail_rules_err_image_type"),
            (
                png_bytes(extra_text=b"x" * 500),
                {"max_bytes": 100},
                "size",
                "mail_rules_err_image_size",
            ),
            (png_bytes(8001, 1), {}, "pixels", "mail_rules_err_image_pixels"),
            (
                png_bytes(4001, 4001),
                {},
                "pixels",
                "mail_rules_err_image_pixels",
            ),
        ]
        for data, kw, code, cle in cas:
            with self.subTest(code=code, kw=kw):
                with self.assertRaises(media.ImageError) as caught:
                    media.check_raster(data, "logo.png", **kw)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(str(caught.exception), f"{t(cle)} logo.png")
        info = media.check_raster(png_bytes(8000, 2), "logo.png")
        self.assertEqual((info.width, info.height), (8000, 2))

    def test_check_raster_restricts_the_types(self):
        """WebP refusé (`type`) quand seuls PNG, JPEG et GIF sont admis."""
        media.check_raster(webp_bytes(), "a.webp")
        with self.assertRaises(media.ImageError) as caught:
            media.check_raster(webp_bytes(), "a.webp", mimes=RASTER)
        self.assertEqual(caught.exception.code, "type")


class TestBounded(MediaCase):
    def test_the_jpeg_scan_is_bounded(self):
        """200 000 segments de 4 octets sans SOF : None en moins d'une
        seconde."""
        data = b"\xff\xd8" + b"\xff\xe1\x00\x02" * 200_000
        debut = time.monotonic()
        self.assertIsNone(media.sniff_image(data))
        self.assertLess(time.monotonic() - debut, 1.0)

    def test_gif_frames_are_bounded(self):
        """L'étendue d'une image compte ; plus de 500 images, un GIF sans
        `;` : None ; deux images : accepté ; 100 000 extensions vides :
        rapide."""
        large = gif_bytes(10, 10, frames=gif_frame(width=9000, height=10))
        self.sniffed(large, "image/gif", 9000, 10)
        with self.assertRaises(media.ImageError) as caught:
            media.check_raster(large, "anime.gif")
        self.assertEqual(caught.exception.code, "pixels")
        trop = gif_bytes(1, 1, frames=gif_frame() * 501)
        self.assertIsNone(media.sniff_image(trop))
        self.assertIsNone(media.sniff_image(gif_bytes(1, 1)[:-1]))
        deux = gif_bytes(4, 4, frames=gif_frame() + gif_frame(1, 1, 2, 2))
        self.sniffed(deux, "image/gif", 4, 4)
        self.assertIsNone(media.sniff_image(gif_bytes(1, 1, frames=b"")))
        extensions = gif_bytes(
            1, 1, frames=b"\x21\xfe\x00" * 100_000 + gif_frame()
        )
        debut = time.monotonic()
        media.sniff_image(extensions)
        self.assertLess(time.monotonic() - debut, 1.0)


if __name__ == "__main__":
    unittest.main()
