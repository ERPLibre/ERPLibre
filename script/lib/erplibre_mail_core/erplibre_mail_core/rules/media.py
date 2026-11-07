# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le type réel et les dimensions d'une image matricielle, lus dans ses
octets : PNG, JPEG, GIF, WebP.

Rien n'est décodé au-delà des en-têtes ; chaque lecteur avance d'au moins
un octet par pas et s'arrête à la fin des données : sa durée reste
linéaire dans leur taille, et une tranche trop courte rend None, jamais
une exception. L'extension d'un nom n'entre pas en jeu : un fichier
`logo.png` qui porte du HTML n'est pas une image.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from erplibre_mail_core.i18n import t
from erplibre_mail_core.rules.model import (
    IMAGE_MIMES,
    MAX_IMAGE_BYTES,
    RuleError,
)

# Côté et surface au plus d'une image : au-delà, l'aperçu dans un
# navigateur ou le client du destinataire décode une bombe de
# décompression.
MAX_SIDE_PX = 8000
MAX_PIXELS = 16_000_000
# Images d'un GIF au plus : chacune se décode dans le client.
MAX_GIF_FRAMES = 500

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Marqueurs JPEG de début d'image (SOF0 à SOF15) qui portent les
# dimensions ; C4 (table de Huffman), C8 (réservé) et CC (codage
# arithmétique) partagent la plage sans en être.
_JPEG_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
# Marqueurs JPEG sans longueur : redémarrage et `TEM`.
_JPEG_STANDALONE = frozenset(range(0xD0, 0xD8)) | {0x01}


@dataclass(frozen=True)
class ImageInfo:
    """Le type MIME et les dimensions, en pixels, d'une image."""

    mime: str
    width: int
    height: int


class ImageError(RuleError):
    """Refus d'une image matricielle ; `code` : `type`, `size`, `pixels`.
    Le texte reste celui de `RuleError`."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _png(data: bytes) -> ImageInfo | None:
    if len(data) < 24 or not data.startswith(_PNG_SIGNATURE):
        return None
    if data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return _info("image/png", width, height)


def _jpeg(data: bytes) -> ImageInfo | None:
    """Le premier segment SOF trouvé avant SOS (`DA`) ou EOI (`D9`).

    Chaque pas avance d'au moins deux octets ; un octet qui n'est pas
    `FF` là où un marqueur est attendu, une longueur de moins de 2 ou un
    SOF coupé rendent None."""
    if not data.startswith(b"\xff\xd8\xff"):
        return None
    size = len(data)
    pos = 2
    while pos + 4 <= size:
        if data[pos] != 0xFF:
            return None
        # Octets `FF` de remplissage entre deux segments.
        while pos + 1 < size and data[pos + 1] == 0xFF:
            pos += 1
        if pos + 4 > size:
            return None
        marker = data[pos + 1]
        if marker in _JPEG_STANDALONE:
            pos += 2
            continue
        if marker in (0xDA, 0xD9):
            return None
        if marker in _JPEG_SOF:
            if pos + 9 > size:
                return None
            height, width = struct.unpack(">HH", data[pos + 5 : pos + 9])
            return _info("image/jpeg", width, height)
        length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        if length < 2:
            return None
        pos += 2 + length
    return None


def _gif_sub_blocks(data: bytes, pos: int) -> int:
    """La position qui suit une suite de sous-blocs (longueur puis
    octets) terminée par un bloc de longueur nulle, ou -1 si les données
    finissent avant."""
    size = len(data)
    while pos < size:
        length = data[pos]
        pos += 1
        if length == 0:
            return pos
        pos += length
    return -1


def _gif(data: bytes) -> ImageInfo | None:
    """L'écran logique et chaque image jusqu'à la fin (`;`).

    Les dimensions sont les plus grandes de l'écran logique et de
    l'étendue de chaque image (gauche + largeur, haut + hauteur) : un
    client peut allouer l'une ou l'autre. Un GIF sans image, tronqué
    avant `;`, d'un bloc inconnu ou de plus de `MAX_GIF_FRAMES` images
    rend None."""
    if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    width, height = struct.unpack("<HH", data[6:10])
    flags = data[10]
    pos = 13
    if flags & 0x80:
        pos += 3 * (2 ** ((flags & 0x07) + 1))
    size = len(data)
    frames = 0
    while pos < size:
        block = data[pos]
        if block == 0x3B:
            if frames == 0:
                return None
            return _info("image/gif", width, height)
        if block == 0x21:
            if pos + 2 > size:
                return None
            pos = _gif_sub_blocks(data, pos + 2)
        elif block == 0x2C:
            frames += 1
            if frames > MAX_GIF_FRAMES or pos + 10 > size:
                return None
            left, top, frame_w, frame_h = struct.unpack(
                "<HHHH", data[pos + 1 : pos + 9]
            )
            width = max(width, left + frame_w)
            height = max(height, top + frame_h)
            local = data[pos + 9]
            pos += 10
            if local & 0x80:
                pos += 3 * (2 ** ((local & 0x07) + 1))
            # Octet de taille du code LZW, puis les données.
            pos = _gif_sub_blocks(data, pos + 1) if pos < size else -1
        else:
            return None
        if pos < 0:
            return None
    return None


def _webp(data: bytes) -> ImageInfo | None:
    if len(data) < 16 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    # Octets nécessaires à la lecture des dimensions de chaque variante.
    if len(data) < {b"VP8X": 30, b"VP8L": 25, b"VP8 ": 30}.get(chunk, 0):
        return None
    if chunk == b"VP8X":
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
    elif chunk == b"VP8L":
        if data[20] != 0x2F:
            return None
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
    elif chunk == b"VP8 ":
        if data[23:26] != b"\x9d\x01\x2a":
            return None
        width = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        height = struct.unpack("<H", data[28:30])[0] & 0x3FFF
    else:
        return None
    return _info("image/webp", width, height)


def _info(mime: str, width: int, height: int) -> ImageInfo | None:
    if width <= 0 or height <= 0:
        return None
    return ImageInfo(mime, width, height)


def sniff_image(data: bytes) -> ImageInfo | None:
    """Le type et les dimensions de l'image `data`, ou None si ses octets
    ne sont pas une image PNG (signature et `IHDR`), JPEG (`FFD8FF` et un
    segment SOF0–SOF15 hors C4, C8, CC, trouvé avant SOS), GIF (`GIF87a`
    ou `GIF89a`, écran logique et chaque image jusqu'au `;`) ou WebP
    (`RIFF…WEBP`, `VP8 `, `VP8L` ou `VP8X`) aux dimensions non nulles."""
    if not data:
        return None
    for reader in (_png, _jpeg, _gif, _webp):
        info = reader(data)
        if info is not None:
            return info
    return None


def check_raster(
    data: bytes,
    name: str,
    *,
    mimes: tuple = IMAGE_MIMES,
    max_bytes: int | None = None,
    max_side: int = MAX_SIDE_PX,
    max_pixels: int = MAX_PIXELS,
) -> ImageInfo:
    """`sniff_image(data)` contrôlé : type reconnu et dans `mimes`
    (`type`), au plus `max_bytes` octets (`MAX_IMAGE_BYTES` par défaut,
    `size`), côtés et surface bornés (`pixels`). `name` ne sert qu'aux
    messages."""
    info = sniff_image(data)
    if info is None or info.mime not in mimes:
        raise ImageError(f"{t('mail_rules_err_image_type')} {name}", "type")
    limit = MAX_IMAGE_BYTES if max_bytes is None else max_bytes
    if len(data) > limit:
        raise ImageError(f"{t('mail_rules_err_image_size')} {name}", "size")
    if (
        info.width > max_side
        or info.height > max_side
        or info.width * info.height > max_pixels
    ):
        raise ImageError(
            f"{t('mail_rules_err_image_pixels')} {name}", "pixels"
        )
    return info
