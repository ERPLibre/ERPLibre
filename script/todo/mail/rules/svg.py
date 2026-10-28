#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Conversion en PNG d'une image SVG ajoutée à une règle.

Un SVG n'est jamais stocké ni envoyé : les clients courriel courants ne
l'affichent pas en ligne, et il peut porter du script. `svg_to_png` le
rastérise une fois, à l'ajout, et rend les octets d'un PNG que
`storage.import_media` range comme n'importe quelle autre image.

Le fichier est reconnu par son extension (`.svg`, `.svgz`) ET par son
contenu : une racine `<svg>` après le prologue XML, décompressée d'abord
si elle est en gzip. Le texte n'est lu que par expressions régulières et
`str.find`, jamais par un analyseur XML : ni entité ni ressource externe
ne s'y résout. Aucune de ces lectures ne revient en arrière plus d'une
fois sur un caractère : leur durée reste linéaire dans la taille du
fichier, que seul `MAX_SVG_BYTES` borne avant le convertisseur.

Un SVG qui renvoie à une ressource externe est refusé : un attribut `href`
ou une fonction CSS `url()` dont la valeur n'est ni une ancre `#…` ni un
`data:`, un `@import`, une entité `SYSTEM` ou `PUBLIC`. Inkscape et
ImageMagick suivent un `file://` ou un pseudo-protocole et en recopient le
contenu dans le PNG, que la règle envoie ensuite à des tiers.

La conversion passe par le premier convertisseur de
`available_converters()`, lancé par `subprocess` avec une liste
d'arguments, dans un dossier temporaire qui ne contient que la source.
Elle est bornée en durée par `CONVERT_TIMEOUT_S`, et par `setrlimit` en
mémoire adressable (`CONVERT_MEMORY_BYTES`) et en taille de fichier écrit
(`CONVERT_FILE_BYTES`). ImageMagick reçoit en plus ses propres plafonds
(`-limit`) et une densité qui le fait rastériser d'emblée à la largeur
visée plutôt qu'à la taille déclarée. Le message d'une erreur ne cite que
le nom de base du fichier, jamais son chemin.
"""

from __future__ import annotations

import gzip
import io
import math
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from script.todo.mail.rules.model import MAX_IMAGE_BYTES, RuleError
from script.todo.todo_i18n import t

SVG_SUFFIXES = (".svg", ".svgz")
# Taille maximale de la source, compressée comme décompressée : un .svgz
# de quelques kilo-octets peut se décompresser en gigaoctets.
MAX_SVG_BYTES = 4 * 1024 * 1024
MAX_WIDTH_PX = 1200
# Largeur d'un SVG qui ne donne pas la sienne en unité absolue.
DEFAULT_WIDTH_PX = 600
# Hauteur maximale du PNG quand les proportions sont connues : une image
# très étroite et très haute réduit sa largeur plutôt que d'allouer des
# centaines de mégapixels.
MAX_HEIGHT_PX = 4800
CONVERT_TIMEOUT_S = 20
# Plafonds posés au convertisseur par `setrlimit` : espace d'adressage
# (Inkscape en réserve beaucoup sans l'utiliser) et taille de tout fichier
# qu'il écrit (le PNG final ne dépasse pas `MAX_IMAGE_BYTES`).
CONVERT_MEMORY_BYTES = 4 * 1024 * 1024 * 1024
CONVERT_FILE_BYTES = 64 * 1024 * 1024
INSTALL_HINT = "sudo apt install librsvg2-bin"

_GZIP_MAGIC = b"\x1f\x8b"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Partie du texte où la racine doit apparaître.
_HEAD_CHARS = 64 * 1024
_SOURCE_NAME = "source.svg"
_OUTPUT_NAME = "image.png"
# Densité à laquelle un SVG se rastérise à sa taille déclarée.
_SVG_DPI = 96
_CAIROSVG_PROBE_TIMEOUT_S = 10
# Caractères lus après `href=` ou `url(` pour reconnaître une valeur
# interne ; au-delà, la valeur est tenue pour externe.
_REFERENCE_LOOKAHEAD = 256

_SPACE_RE = re.compile(r"\s*")
_DOCTYPE_STOP_RE = re.compile(r"[\[>]")
# La racine `<svg …>`, préfixe d'espace de noms admis ; un `>` entre
# guillemets ne ferme pas la balise.
_ROOT_RE = re.compile(
    r"<(?:[A-Za-z_][\w.-]*:)?svg(?=[\s/>])"
    r"(?P<attrs>(?:[^>\"']|\"[^\"]*\"|'[^']*')*)>"
)
# Le nom ne commence qu'en limite de nom : sans le lookbehind, chaque
# position d'un long mot sans `=` relancerait un parcours jusqu'à sa fin.
_ATTR_RE = re.compile(
    r"""(?<![\w.:-])([A-Za-z_:][\w.:-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')"""
)
# Les alternatives du nombre et les blancs qui entourent l'unité ne se
# chevauchent pas : une longue suite de chiffres ou de blancs ne se
# découpe que d'une façon.
_LENGTH_RE = re.compile(
    r"\s*((?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
    r"\s*(?:(px|pt|pc|mm|cm|in)\s*)?\Z"
)
# Points d'entrée d'une référence : un attribut `href` (préfixe d'espace
# de noms admis, en limite de nom), `url(`, `@import`, une entité.
_REFERENCE_RE = re.compile(
    r"(?<![\w.:-])(?:[A-Za-z_][\w.-]*:)?href\s*=|url\(|@import|<!ENTITY\s",
    re.IGNORECASE,
)
# Suite d'une déclaration `<!ENTITY` qui la rend externe ; entité de
# paramètre (`%`) comprise.
_EXTERNAL_ENTITY_RE = re.compile(
    r"\s*(?:%\s+)?[^\s>]+\s+(?:SYSTEM|PUBLIC)(?![\w.:-])"
)
# Pixels CSS par unité absolue (96 px au pouce).
_UNIT_PX = {
    None: 1.0,
    "px": 1.0,
    "pt": 96 / 72,
    "pc": 16.0,
    "mm": 96 / 25.4,
    "cm": 96 / 2.54,
    "in": 96.0,
}

# Lancé dans un processus séparé : le délai s'applique à cairosvg comme
# aux exécutables, et `unsafe` reste à faux (aucun fichier externe).
_CAIROSVG_CODE = (
    "import sys, cairosvg; cairosvg.svg2png(url=sys.argv[1],"
    " write_to=sys.argv[2], output_width=int(sys.argv[3]))"
)

# Tremplin lancé par `python -I -c` : abaisse les plafonds de ressources
# (jamais au-dessus du plafond dur hérité), puis se remplace par le
# convertisseur. Il tient lieu de `preexec_fn`, que `subprocess` déconseille
# dans un processus qui a des fils d'exécution, comme l'interface.
_LIMITS_CODE = """\
import os, resource, sys
for kind, value in ((resource.RLIMIT_AS, int(sys.argv[1])),
                    (resource.RLIMIT_FSIZE, int(sys.argv[2]))):
    hard = resource.getrlimit(kind)[1]
    if hard != resource.RLIM_INFINITY:
        value = min(value, hard)
    try:
        resource.setrlimit(kind, (value, value))
    except (ValueError, OSError):
        pass
os.execv(sys.argv[3], sys.argv[3:])
"""

# Plafonds internes d'ImageMagick, en octets et en pixels : au-delà, il
# refuse l'image au lieu de déborder sur le disque.
_MAGICK_LIMITS = (
    "-limit",
    "memory",
    str(256 * 1024 * 1024),
    "-limit",
    "map",
    str(512 * 1024 * 1024),
    "-limit",
    "disk",
    str(256 * 1024 * 1024),
    "-limit",
    "area",
    str(64 * 1024 * 1024),
)

ArgvBuilder = Callable[..., list]


@dataclass(frozen=True)
class Converter:
    """Un convertisseur : son nom affiché et la fonction qui rend la liste
    d'arguments rastérisant `source` en `output` à la largeur `width`.

    Le quatrième argument, `density`, est la densité (points par pouce) à
    laquelle la largeur déclarée du dessin devient `width`, ou None si le
    dessin n'en déclare pas ; seul ImageMagick s'en sert.
    """

    name: str
    argv: ArgvBuilder


def _rsvg_argv(exe: str) -> ArgvBuilder:
    return lambda source, output, width, density=None: [
        exe,
        "--width",
        str(width),
        "--keep-aspect-ratio",
        "--format",
        "png",
        "--output",
        output,
        source,
    ]


def _cairosvg_argv(
    source: str, output: str, width: int, density: float | None = None
) -> list:
    return [sys.executable, "-c", _CAIROSVG_CODE, source, output, str(width)]


def _inkscape_argv(exe: str) -> ArgvBuilder:
    return lambda source, output, width, density=None: [
        exe,
        "--export-type=png",
        f"--export-filename={output}",
        f"--export-width={width}",
        source,
    ]


def _magick_argv(exe: str) -> ArgvBuilder:
    # Les préfixes `svg:` et `png:` imposent le format : ni le nom ni le
    # contenu ne choisissent un autre décodeur. Les options `-limit` et
    # `-density` précèdent la lecture de la source, qu'elles gouvernent ;
    # `-resize` ajuste ensuite la largeur exacte.
    def argv(source, output, width, density=None):
        scale = ["-density", f"{density:.6g}"] if density else []
        return [
            exe,
            *_MAGICK_LIMITS,
            "-background",
            "none",
            *scale,
            f"svg:{source}",
            "-resize",
            f"{width}x",
            f"png:{output}",
        ]

    return argv


# Résultat de la sonde de cairosvg, par interpréteur et `PYTHONPATH`.
_cairosvg_probe: dict = {}


def _cairosvg_available() -> bool:
    """Vrai si `import cairosvg` réussit dans un processus fils lancé
    comme la conversion : même interpréteur, même environnement.

    Installé ne suffit pas : sans la bibliothèque cairo du système,
    l'import lève une `OSError`, et cairosvg, choisi avant Inkscape et
    ImageMagick, ferait échouer toute conversion. Le résultat est gardé
    pour la durée du processus.
    """
    key = (sys.executable, os.environ.get("PYTHONPATH"))
    if key not in _cairosvg_probe:
        argv = [sys.executable, "-c", "import cairosvg"]
        try:
            with tempfile.TemporaryDirectory(prefix="todo-svg-") as folder:
                code = _run(argv, folder, _CAIROSVG_PROBE_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired):
            code = None
        _cairosvg_probe[key] = code == 0
    return _cairosvg_probe[key]


def available_converters() -> list:
    """Les convertisseurs présents, dans l'ordre de préférence :
    rsvg-convert, cairosvg, inkscape, puis ImageMagick (`magick`, ou
    `convert` de sa version 6). Les exécutables se cherchent dans le
    `PATH` courant."""
    found = []
    exe = shutil.which("rsvg-convert")
    if exe:
        found.append(Converter("rsvg-convert", _rsvg_argv(exe)))
    if _cairosvg_available():
        found.append(Converter("cairosvg", _cairosvg_argv))
    exe = shutil.which("inkscape")
    if exe:
        found.append(Converter("inkscape", _inkscape_argv(exe)))
    for name in ("magick", "convert"):
        exe = shutil.which(name)
        if exe:
            found.append(Converter(name, _magick_argv(exe)))
            break
    return found


def is_svg_name(name: str) -> bool:
    """Vrai si le nom porte une extension SVG, sans égard à la casse."""
    return Path(name).suffix.lower() in SVG_SUFFIXES


def png_name(name: str) -> str:
    """Le nom de base du fichier, extension remplacée par `.png`."""
    return Path(name).stem + ".png"


def _invalid(name: str) -> RuleError:
    return RuleError(f"{t('mail_rules_err_svg_invalid')} {name}")


def read_svg(src: Path) -> bytes:
    """Les octets d'un fichier SVG, décompressés s'il est en gzip.

    Les octets, et non un texte décodé : le convertisseur lit l'encodage
    que déclare le prologue.

    `RuleError` si le fichier manque, dépasse `MAX_SVG_BYTES` avant ou
    après décompression, se dit `.svgz` sans être en gzip, n'a pas
    `<svg>` pour racine, ou renvoie à une ressource externe.
    """
    src = Path(src)
    try:
        with open(src, "rb") as handle:
            data = handle.read(MAX_SVG_BYTES + 1)
    except OSError as exc:
        raise RuleError(
            f"{t('mail_rules_err_image_missing')} {src.name}"
        ) from exc
    if len(data) > MAX_SVG_BYTES:
        raise RuleError(f"{t('mail_rules_err_image_size')} {src.name}")
    if data.startswith(_GZIP_MAGIC):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as unzipped:
                data = unzipped.read(MAX_SVG_BYTES + 1)
        except (OSError, EOFError, zlib.error) as exc:
            raise _invalid(src.name) from exc
        if len(data) > MAX_SVG_BYTES:
            raise RuleError(f"{t('mail_rules_err_image_size')} {src.name}")
    elif src.suffix.lower() == ".svgz":
        raise _invalid(src.name)
    if svg_root_attrs(_head_text(data)) is None:
        raise _invalid(src.name)
    if external_reference(data.decode("utf-8", errors="replace")):
        raise RuleError(f"{t('mail_rules_err_svg_external')} {src.name}")
    return data


def _head_text(data: bytes) -> str:
    """Le début du fichier en texte, assez pour y lire la racine."""
    return data[: _HEAD_CHARS * 4].decode("utf-8-sig", errors="replace")


def _doctype_end(text: str, pos: int) -> int:
    """L'indice du `>` qui ferme un DOCTYPE dont le mot-clé finit en
    `pos`, ou -1 s'il n'est pas fermé. Un `[` ouvre un sous-ensemble
    interne que ferme le premier `]` ; un `>` qu'il contient ne ferme pas
    le DOCTYPE."""
    while True:
        stop = _DOCTYPE_STOP_RE.search(text, pos)
        if stop is None:
            return -1
        if stop.group() == ">":
            return stop.start()
        close = text.find("]", stop.end())
        if close < 0:
            return -1
        pos = close + 1


def prolog_end(text: str) -> int:
    """La position qui suit le prologue XML : blancs, déclaration et
    instructions de traitement, commentaires, DOCTYPE avec ou sans
    sous-ensemble interne.

    Un parcours par `str.find` où chaque pas avance : la durée reste
    linéaire même sur un prologue malformé. Une construction non fermée
    arrête le prologue avant elle.
    """
    pos = 0
    while True:
        pos = _SPACE_RE.match(text, pos).end()
        if text.startswith("<?", pos):
            end, close = text.find("?>", pos + 2), 2
        elif text.startswith("<!--", pos):
            end, close = text.find("-->", pos + 4), 3
        elif text[pos : pos + 9].upper() == "<!DOCTYPE":
            end, close = _doctype_end(text, pos + 9), 1
        else:
            return pos
        if end < 0:
            return pos
        pos = end + close


def svg_root_attrs(text: str) -> dict | None:
    """Les attributs de la racine `<svg>`, ou None si la racine, après le
    prologue, n'est pas un élément `svg`."""
    head = text[:_HEAD_CHARS]
    root = _ROOT_RE.match(head, prolog_end(head))
    if root is None:
        return None
    return {
        name: first if first is not None else second
        for name, first, second in _ATTR_RE.findall(root.group("attrs"))
    }


def external_reference(text: str) -> bool:
    """Vrai si le texte d'un SVG renvoie à une ressource externe : un
    attribut `href` ou une fonction `url()` dont la valeur n'est ni une
    ancre `#…` ni un `data:`, un `@import`, une entité `SYSTEM` ou
    `PUBLIC`.

    La règle est large : un lien `<a href>` ou un `url(` cité dans un
    texte suffit aussi. Une valeur qu'un convertisseur ne peut de toute
    façon pas résoudre dans son dossier temporaire ne perd rien à être
    refusée avec un message clair.
    """
    for match in _REFERENCE_RE.finditer(text):
        token = match.group().lower()
        if token == "@import":
            return True
        if token.startswith("<!entity"):
            if _EXTERNAL_ENTITY_RE.match(text, match.end()):
                return True
            continue
        value = text[match.end() : match.end() + _REFERENCE_LOOKAHEAD]
        value = value.lstrip().lstrip("\"'").lstrip().lower()
        if not value.startswith(("#", "data:")):
            return True
    return False


def _positive(value: float | None) -> float | None:
    """La valeur si elle est finie et strictement positive, sinon None :
    `float()` accepte `nan`, `inf` et `1e999`."""
    if value is None or not math.isfinite(value) or value <= 0:
        return None
    return value


def _length_px(value: str | None) -> float | None:
    """Une longueur SVG en pixels ; None si absente, nulle, hors des
    flottants finis ou relative (`%`, `em`)."""
    if value is None:
        return None
    match = _LENGTH_RE.match(value)
    if match is None:
        return None
    return _positive(float(match.group(1)) * _UNIT_PX[match.group(2)])


def _ratio(width: float | None, height: float | None) -> float | None:
    """Largeur sur hauteur, ou None si l'une manque ou si le quotient
    n'est pas un flottant fini strictement positif."""
    if width is None or height is None:
        return None
    return _positive(width / height)


def _viewbox_ratio(value: str | None) -> float | None:
    """Largeur sur hauteur du `viewBox`, ou None s'il est invalide."""
    if value is None:
        return None
    parts = re.split(r"[\s,]+", value.strip())
    if len(parts) != 4:
        return None
    try:
        width, height = float(parts[2]), float(parts[3])
    except ValueError:
        return None
    return _ratio(_positive(width), _positive(height))


def _size(attrs: dict) -> tuple:
    """La largeur intrinsèque en pixels et les proportions, chacune None
    si le dessin ne la donne pas.

    La largeur est `width`, sinon `height` multiplié par les proportions ;
    les proportions viennent de `width`/`height`, sinon du `viewBox`.
    """
    width = _length_px(attrs.get("width"))
    height = _length_px(attrs.get("height"))
    ratio = _ratio(width, height) or _viewbox_ratio(attrs.get("viewBox"))
    if width is None and height is not None and ratio:
        width = _positive(height * ratio)
    return width, ratio


def target_width(attrs: dict) -> int:
    """La largeur du PNG, en pixels.

    La largeur intrinsèque, sinon `DEFAULT_WIDTH_PX`, ramenée à
    `MAX_WIDTH_PX` au plus, et réduite encore si la hauteur dépasserait
    `MAX_HEIGHT_PX`.
    """
    width, ratio = _size(attrs)
    width = min(width or DEFAULT_WIDTH_PX, MAX_WIDTH_PX)
    if ratio:
        width = min(width, MAX_HEIGHT_PX * ratio)
    return max(1, round(width))


def target_density(attrs: dict, width: int) -> float | None:
    """La densité, en points par pouce, à laquelle la largeur intrinsèque
    du dessin devient `width` ; None si le dessin n'en donne pas."""
    intrinsic = _size(attrs)[0]
    if intrinsic is None:
        return None
    return _positive(_SVG_DPI * width / intrinsic)


def is_png(data: bytes) -> bool:
    """Signature PNG suivie d'un en-tête `IHDR` aux dimensions non
    nulles."""
    if len(data) < 24 or not data.startswith(_PNG_SIGNATURE):
        return False
    if data[12:16] != b"IHDR":
        return False
    width, height = struct.unpack(">II", data[16:24])
    return width > 0 and height > 0


def _limited(argv: list) -> list:
    """`argv` précédé du tremplin qui lui pose `CONVERT_MEMORY_BYTES` et
    `CONVERT_FILE_BYTES` avant de s'y substituer."""
    return [
        sys.executable,
        "-I",
        "-c",
        _LIMITS_CODE,
        str(CONVERT_MEMORY_BYTES),
        str(CONVERT_FILE_BYTES),
        *argv,
    ]


def _run(argv: list, cwd: str, timeout: float) -> int:
    """Lance `argv` sans shell ; rend son code de sortie.

    Au-delà de `timeout`, tout le groupe de processus est tué (un
    convertisseur peut lancer ses propres fils) et `TimeoutExpired`
    remonte.
    """
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise


def svg_to_png(
    src: Path,
    *,
    converters: list | None = None,
    timeout: float = CONVERT_TIMEOUT_S,
) -> bytes:
    """Les octets du PNG rastérisé depuis le SVG `src`.

    `converters` remplace `available_converters()` ; seul le premier
    sert. `RuleError` quand aucun convertisseur n'est présent (le message
    dit quoi installer), quand `read_svg` refuse la source, quand la
    conversion échoue, dépasse le délai ou rend autre chose qu'un PNG, et
    quand le PNG dépasse `MAX_IMAGE_BYTES`.
    """
    src = Path(src)
    data = read_svg(src)
    if converters is None:
        converters = available_converters()
    if not converters:
        raise RuleError(
            f"{t('mail_rules_err_svg_no_converter')} {INSTALL_HINT}"
        )
    converter = converters[0]
    attrs = svg_root_attrs(_head_text(data))
    width = target_width(attrs)
    density = target_density(attrs, width)

    def failed(detail: str) -> RuleError:
        return RuleError(
            f"{t('mail_rules_err_svg_failed')} {src.name} ({detail})"
        )

    with tempfile.TemporaryDirectory(prefix="todo-svg-") as folder:
        source = os.path.join(folder, _SOURCE_NAME)
        output = os.path.join(folder, _OUTPUT_NAME)
        with open(source, "wb") as handle:
            handle.write(data)
        try:
            argv = converter.argv(source, output, width, density)
            code = _run(_limited(argv), folder, timeout)
        except subprocess.TimeoutExpired as exc:
            raise failed(f"{converter.name}, > {timeout:g} s") from exc
        except OSError as exc:
            raise failed(converter.name) from exc
        if code != 0:
            raise failed(f"{converter.name}, {code}")
        try:
            with open(output, "rb") as handle:
                png = handle.read(MAX_IMAGE_BYTES + 1)
        except OSError as exc:
            raise failed(converter.name) from exc
    if len(png) > MAX_IMAGE_BYTES:
        raise RuleError(f"{t('mail_rules_err_image_size')} {src.name}")
    if not is_png(png):
        raise failed(converter.name)
    return png
