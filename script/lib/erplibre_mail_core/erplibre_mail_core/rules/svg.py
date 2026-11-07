#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Contrôle d'une image SVG et conversion en PNG.

Un SVG n'est jamais stocké ni envoyé : les clients courriel courants ne
l'affichent pas en ligne, et il peut porter du script. Il se rastérise une
fois, à l'ajout, en un PNG rangé comme n'importe quelle autre image.

L'API travaille sur des OCTETS : `check_svg` contrôle une source,
`convert_checked` rastérise une source contrôlée, et `svg_bytes_to_png`
enchaîne les deux. `read_svg` et `svg_to_png` en sont les enveloppes pour
un chemin de fichier, celles du client courriel.

Le fichier est reconnu par son extension (`.svg`, `.svgz`) ET par son
contenu : une racine `<svg>` après le prologue XML, décompressée d'abord
si elle est en gzip. Le texte n'est lu que par expressions régulières et
`str.find`, jamais par un analyseur XML : ni entité ni ressource externe
ne s'y résout. Aucune de ces lectures ne revient en arrière plus d'une
fois sur un caractère : leur durée reste linéaire dans la taille du
fichier, que seul `MAX_SVG_BYTES` (ou la borne de l'appelant) limite avant
le convertisseur.

Deux modes. Le mode ordinaire, celui d'un poste dont l'utilisateur écrit
ses propres règles, refuse un SVG qui renvoie à une ressource externe : un
attribut `href` ou une fonction CSS `url()` dont la valeur n'est ni une
ancre `#…` ni un `data:` d'image matricielle ou de police, un attribut
`absref`, un `@import`, une entité `SYSTEM` ou `PUBLIC`. Inkscape et
ImageMagick suivent un `file://` ou un pseudo-protocole et en recopient le
contenu dans le PNG, que la règle envoie ensuite à des tiers ; Inkscape lit
aussi le chemin de `sodipodi:absref`, et tous deux affichent un SVG imbriqué
en `data:` sans que ses propres références soient examinées.

Le mode `strict`, celui d'une source non fiable, refuse en plus tout ce
qu'un PNG fixe n'utilise pas : script, attribut d'événement, animation,
document imbriqué, toute déclaration de DTD (entité interne comprise), tout
DOCTYPE autre que ceux du W3C, tout codage que les expressions ne lisent
pas comme le convertisseur, toute valeur `data:`, et des proportions qui
feraient exploser la hauteur du PNG ; il revérifie les dimensions du PNG
produit.

La conversion passe par le premier convertisseur de la liste, lancé par
`subprocess` avec une liste d'arguments, dans un dossier temporaire qui ne
contient que la source. Elle est bornée en durée par un délai, et par
`setrlimit` en mémoire adressable, en taille de fichier écrit et, sur
demande, en temps CPU ; ce dernier plafond arrête aussi un fils resté seul
quand le processus qui l'attendait disparaît. `available_converters()`
propose tous les convertisseurs présents ; `safe_converters()` ne propose
que ceux qui ne chargent rien hors des `data:` ou de leur dossier (cairosvg,
rsvg-convert), jamais Inkscape ni ImageMagick. ImageMagick reçoit en plus
ses propres plafonds (`-limit`) et une densité qui le fait rastériser
d'emblée à la largeur visée plutôt qu'à la taille déclarée. Le message
d'une erreur ne cite que le nom de base du fichier, jamais son chemin.
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

from erplibre_mail_core.i18n import t
from erplibre_mail_core.rules.model import MAX_IMAGE_BYTES, RuleError

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
# Points d'entrée d'une référence : un attribut `href` ou `absref`
# (préfixe d'espace de noms admis, en limite de nom), `url(`, `@import`,
# une entité. `sodipodi:absref` est un chemin absolu qu'Inkscape charge
# quand `href` manque ou ne se résout pas : sa valeur passe le même
# contrôle que celle d'un `href`.
_REFERENCE_RE = re.compile(
    r"(?<![\w.:-])(?:[A-Za-z_][\w.-]*:)?(?:href|absref)\s*=|url\(|@import"
    r"|<!ENTITY\s",
    re.IGNORECASE,
)
# Valeurs `data:` admises : une image matricielle ou une police, qui ne
# renvoient à rien. Un document imbriqué (`image/svg+xml`, `text/html`…)
# porterait ses propres références, que rien n'examine ; un `data:` sans
# type ne dit pas ce qu'il contient.
_SAFE_DATA_RE = re.compile(
    r"data:\s*(?:image/(?:png|jpeg|jpg|gif|webp)|font/[\w.+-]+)\s*[;,]"
)
# Suite d'une déclaration `<!ENTITY` qui la rend externe ; entité de
# paramètre (`%`) comprise.
_EXTERNAL_ENTITY_RE = re.compile(
    r"\s*(?:%\s+)?[^\s>]+\s+(?:SYSTEM|PUBLIC)(?![\w.:-])"
)
# Éléments et constructions qu'un PNG fixe n'utilise pas et qu'une source
# non fiable n'apporte que pour nuire.
_UNSAFE_ELEMENT_RE = re.compile(
    r"<(?:[A-Za-z_][\w.-]*:)?(?:script|foreignobject|iframe|embed|object"
    r"|audio|video|handler|listener|set|animate\w*)(?=[\s/>])",
    re.IGNORECASE,
)
_EVENT_ATTR_RE = re.compile(r"(?<![\w.:-])on[a-z]+\s*=", re.IGNORECASE)
# Déclarations de DTD : une entité (bombe d'expansion), une valeur par
# défaut d'attribut (un `href` sans `=`), un élément, une notation.
_DECLARATION_RE = re.compile(
    r"<!(?:ENTITY|ATTLIST|ELEMENT|NOTATION)\s", re.IGNORECASE
)
_DOCTYPE_RE = re.compile(r"<!DOCTYPE", re.IGNORECASE)
# Les seuls DOCTYPE admis en mode strict, à l'espacement près : ceux du
# W3C pour SVG 1.0 et 1.1, sans sous-ensemble interne.
_W3C_DOCTYPE_RE = re.compile(
    r'<!DOCTYPE\s+svg\s+PUBLIC\s+"-//W3C//DTD SVG 1\.(?:0//EN|1//EN'
    r'|1 Basic//EN|1 Tiny//EN)"'
    r'\s+"http://www\.w3\.org/(?:TR/2001/REC-SVG-20010904/DTD/svg10\.dtd'
    r'|Graphics/SVG/1\.1/DTD/svg11(?:-basic|-tiny)?\.dtd)"\s*>'
)
# Le début d'une déclaration XML, et le codage qu'elle déclare.
_XML_DECL_RE = re.compile(rb"<\?xml(?=[\s?])", re.IGNORECASE)
_ENCODING_RE = re.compile(
    r"""\bencoding\s*=\s*["']([^"']*)["']""", re.IGNORECASE
)
_STRICT_ENCODINGS = frozenset({"utf-8", "utf8", "us-ascii", "ascii"})
# Marques d'ordre d'octets d'un codage sur plusieurs octets : UTF-32
# d'abord, dont la marque petit-boutiste commence par celle d'UTF-16.
_WIDE_BOMS = (
    b"\x00\x00\xfe\xff",
    b"\xff\xfe\x00\x00",
    b"\xfe\xff",
    b"\xff\xfe",
)
# Longueur au-delà de laquelle une déclaration XML est refusée en strict :
# l'espacement qu'elle admet entre ses attributs y repousserait
# `encoding=` aussi loin qu'on veut.
_XML_DECL_MAX_BYTES = 1024
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
# dans un processus qui a des fils d'exécution, comme l'interface. Un temps
# CPU nul ne pose aucun plafond de CPU ; sinon le plafond souple est ce
# temps, le dur une seconde de plus.
_LIMITS_CODE = """\
import os, resource, sys
cpu = int(sys.argv[3])
limits = [(resource.RLIMIT_AS, int(sys.argv[1]), int(sys.argv[1])),
          (resource.RLIMIT_FSIZE, int(sys.argv[2]), int(sys.argv[2]))]
if cpu > 0:
    limits.append((resource.RLIMIT_CPU, cpu, cpu + 1))
for kind, soft, hard_wanted in limits:
    hard = resource.getrlimit(kind)[1]
    if hard != resource.RLIM_INFINITY:
        soft, hard_wanted = min(soft, hard), min(hard_wanted, hard)
    try:
        resource.setrlimit(kind, (soft, hard_wanted))
    except (ValueError, OSError):
        pass
os.execv(sys.argv[4], sys.argv[4:])
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


class SvgError(RuleError):
    """Refus d'un SVG ou de sa conversion ; `code` dit lequel : `missing`,
    `source_size`, `invalid`, `external`, `embedded`, `unsafe`, `pixels`,
    `no_converter`, `failed`, `size`. Le texte reste celui de `RuleError`.
    """

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


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
    l'import lève une `OSError`, et cairosvg ferait échouer toute
    conversion. Un résultat franc (import réussi, code non nul, `OSError`)
    est gardé pour la durée du processus ; une sonde qui dépasse son délai
    rend faux sans être gardée, pour qu'une charge passagère ne prive pas
    le processus de convertisseur jusqu'à son redémarrage.
    """
    key = (sys.executable, os.environ.get("PYTHONPATH"))
    if key not in _cairosvg_probe:
        argv = [sys.executable, "-c", "import cairosvg"]
        try:
            with tempfile.TemporaryDirectory(prefix="todo-svg-") as folder:
                code = _run(argv, folder, _CAIROSVG_PROBE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return False
        except OSError:
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


def safe_converters() -> list:
    """Les convertisseurs présents qui ne suivent aucune référence hors de
    leur dossier : cairosvg (sondé comme pour `available_converters`),
    puis rsvg-convert du `PATH` courant ; jamais Inkscape ni ImageMagick.

    cairosvg analyse par `defusedxml` (entités et références externes
    interdites) et ne charge que des `data:`."""
    found = []
    if _cairosvg_available():
        found.append(Converter("cairosvg", _cairosvg_argv))
    exe = shutil.which("rsvg-convert")
    if exe:
        found.append(Converter("rsvg-convert", _rsvg_argv(exe)))
    return found


def is_svg_name(name: str) -> bool:
    """Vrai si le nom porte une extension SVG, sans égard à la casse."""
    return Path(name).suffix.lower() in SVG_SUFFIXES


def png_name(name: str) -> str:
    """Le nom de base du fichier, extension remplacée par `.png`."""
    return Path(name).stem + ".png"


def _error(key: str, name: str, code: str) -> SvgError:
    return SvgError(f"{t(key)} {name}", code)


def looks_like_svg(data: bytes) -> bool:
    """Vrai pour des octets en gzip, ou dont le texte a `<svg>` pour racine
    après le prologue : ce que `check_svg` examine comme un SVG."""
    if data.startswith(_GZIP_MAGIC):
        return True
    return svg_root_attrs(_head_text(data)) is not None


def hidden_encoding(data: bytes) -> bool:
    """Vrai si les octets ne se lisent pas comme UTF-8 ou ASCII par les
    expressions ET par le convertisseur : marque d'ordre d'octets autre
    qu'UTF-8 (UTF-16, UTF-32), octet NUL, déclaration XML sans `?>` ou de
    plus de `_XML_DECL_MAX_BYTES` octets, ou déclaration `encoding=` hors
    `_STRICT_ENCODINGS`. UTF-7 ou UTF-16 cachent `<!ENTITY`, `<script` ou
    `href=` aux expressions, pas à l'analyseur du convertisseur.

    La déclaration se lit en entier, de `<?xml` à son `?>`, où qu'elle
    soit dans les octets : un codage écrit après un long espacement reste
    vu. Deux recherches linéaires, aucune fenêtre fixe."""
    if data.startswith(_WIDE_BOMS) or b"\x00" in data:
        return True
    start = _XML_DECL_RE.search(data)
    if start is None:
        return False
    end = data.find(b"?>", start.start())
    if end < 0 or end - start.start() > _XML_DECL_MAX_BYTES:
        return True
    declaration = data[start.start() : end].decode("utf-8", errors="replace")
    declared = _ENCODING_RE.search(declaration)
    if declared is None:
        return False
    return declared.group(1).strip().lower() not in _STRICT_ENCODINGS


def unsafe_construct(text: str) -> bool:
    """Vrai si le texte porte un élément de `_UNSAFE_ELEMENT_RE`, un
    attribut d'événement `on…=`, une déclaration de `_DECLARATION_RE`, ou
    un `<!DOCTYPE` qui n'est pas un DOCTYPE W3C exact.

    Le DOCTYPE se compare à sa position par `_W3C_DOCTYPE_RE.match` : un
    `>` entre guillemets, un sous-ensemble ou un identifiant `SYSTEM` ne
    passent pas. Expressions linéaires : le lookahead ne lit qu'un
    caractère, et le DOCTYPE W3C est un motif fixe sans répétition
    imbriquée."""
    if _UNSAFE_ELEMENT_RE.search(text) or _EVENT_ATTR_RE.search(text):
        return True
    if _DECLARATION_RE.search(text):
        return True
    for doctype in _DOCTYPE_RE.finditer(text):
        if not _W3C_DOCTYPE_RE.match(text, doctype.start()):
            return True
    return False


def _reference_value(text: str, end: int) -> str:
    """Le début de la valeur d'une référence qui commence en `end`, sans
    blancs ni guillemet d'ouverture, en minuscules."""
    value = text[end : end + _REFERENCE_LOOKAHEAD]
    return value.lstrip().lstrip("\"'").lstrip().lower()


def embedded_data(text: str) -> bool:
    """Vrai si une valeur de `href`, `absref` ou `url()` (mêmes points
    d'entrée et même lecture que `external_reference`) commence par
    `data:` : une image ou un document intégrés. Un `data:` dans un texte
    ordinaire (`metadata: …`) n'en est pas un."""
    for match in _REFERENCE_RE.finditer(text):
        token = match.group().lower()
        if token == "@import" or token.startswith("<!entity"):
            continue
        if _reference_value(text, match.end()).startswith("data:"):
            return True
    return False


def _invalid(name: str) -> SvgError:
    return _error("mail_rules_err_svg_invalid", name, "invalid")


def check_svg(
    data: bytes,
    name: str,
    *,
    strict: bool = False,
    max_bytes: int | None = None,
) -> bytes:
    """Les octets du SVG `data`, décompressés s'ils sont en gzip ; `name`
    (nom de base) ne sert qu'aux messages et à reconnaître `.svgz`.

    Les octets, et non un texte décodé : le convertisseur lit le codage
    que déclare le prologue.

    Refuse (`SvgError`) dans cet ordre : plus de `max_bytes`
    (`MAX_SVG_BYTES` lu à l'appel par défaut) avant ou après décompression
    (`source_size`), gzip illisible ou `.svgz` sans gzip, racine qui n'est
    pas `<svg>` (`invalid`), référence externe (`external`) ; en mode
    `strict`, en plus, dans cet ordre : codage caché (`unsafe`),
    construction de `unsafe_construct` (`unsafe`), valeur `data:` intégrée
    (`embedded`), proportions qui donneraient une hauteur de plus de
    `MAX_HEIGHT_PX` à la largeur visée (`pixels`). En mode strict, une
    valeur `data:` n'est pas une référence externe : elle reçoit son
    propre refus.
    """
    limit = MAX_SVG_BYTES if max_bytes is None else max_bytes
    if len(data) > limit:
        raise _error("mail_rules_err_image_size", name, "source_size")
    if data.startswith(_GZIP_MAGIC):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as unzipped:
                data = unzipped.read(limit + 1)
        except (OSError, EOFError, zlib.error) as exc:
            raise _invalid(name) from exc
        if len(data) > limit:
            raise _error("mail_rules_err_image_size", name, "source_size")
    elif Path(name).suffix.lower() == ".svgz":
        raise _invalid(name)
    head = _head_text(data)
    attrs = svg_root_attrs(head)
    if attrs is None:
        raise _invalid(name)
    text = data.decode("utf-8", errors="replace")
    if external_reference(text, allow_data=strict):
        raise _error("mail_rules_err_svg_external", name, "external")
    if not strict:
        return data
    if hidden_encoding(data) or unsafe_construct(text):
        raise _error("mail_rules_err_svg_unsafe", name, "unsafe")
    if embedded_data(text):
        raise _error("mail_rules_err_svg_embedded", name, "embedded")
    ratio = _size(attrs)[1]
    if ratio and target_width(attrs, strict=True) / ratio > MAX_HEIGHT_PX:
        raise _error("mail_rules_err_image_pixels", name, "pixels")
    return data


def read_svg(src: Path) -> bytes:
    """Les octets d'un fichier SVG, décompressés s'il est en gzip.

    `SvgError` si le fichier manque, dépasse `MAX_SVG_BYTES` avant ou
    après décompression, se dit `.svgz` sans être en gzip, n'a pas
    `<svg>` pour racine, ou renvoie à une ressource externe (contrôle de
    `check_svg`, mode ordinaire).
    """
    src = Path(src)
    try:
        with open(src, "rb") as handle:
            data = handle.read(MAX_SVG_BYTES + 1)
    except OSError as exc:
        raise _error(
            "mail_rules_err_image_missing", src.name, "missing"
        ) from exc
    if len(data) > MAX_SVG_BYTES:
        raise _error("mail_rules_err_image_size", src.name, "source_size")
    return check_svg(data, src.name)


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


def external_reference(text: str, *, allow_data: bool = False) -> bool:
    """Vrai si le texte d'un SVG renvoie à une ressource externe : un
    attribut `href` ou une fonction `url()` dont la valeur n'est ni une
    ancre `#…` ni un `data:` d'image matricielle ou de police
    (`_SAFE_DATA_RE`), un attribut `absref` de même, un `@import`, une
    entité `SYSTEM` ou `PUBLIC`. Avec `allow_data`, toute valeur `data:`
    est laissée à un autre contrôle (`embedded_data`).

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
        value = _reference_value(text, match.end())
        if value.startswith("#"):
            continue
        if allow_data and value.startswith("data:"):
            continue
        if not _SAFE_DATA_RE.match(value):
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


def target_width(attrs: dict, *, strict: bool = False) -> int:
    """La largeur du PNG, en pixels.

    La largeur intrinsèque, sinon `DEFAULT_WIDTH_PX`, ramenée à
    `MAX_WIDTH_PX` au plus, et réduite encore si la hauteur dépasserait
    `MAX_HEIGHT_PX`. En mode `strict`, cette dernière borne est la partie
    entière de `MAX_HEIGHT_PX` fois les proportions, et non son arrondi :
    l'arrondi vers le haut d'un dessin étroit ferait dépasser la hauteur.
    Au moins 1 : un dessin dégénéré garde une largeur, que le contrôle des
    proportions refuse.
    """
    width, ratio = _size(attrs)
    width = min(width or DEFAULT_WIDTH_PX, MAX_WIDTH_PX)
    if ratio:
        bound = MAX_HEIGHT_PX * ratio
        width = min(width, math.floor(bound) if strict else bound)
    return max(1, round(width))


def target_density(attrs: dict, width: int) -> float | None:
    """La densité, en points par pouce, à laquelle la largeur intrinsèque
    du dessin devient `width` ; None si le dessin n'en donne pas."""
    intrinsic = _size(attrs)[0]
    if intrinsic is None:
        return None
    return _positive(_SVG_DPI * width / intrinsic)


def _png_size(data: bytes) -> tuple | None:
    """Largeur et hauteur lues dans l'en-tête `IHDR` d'un PNG, ou None si
    les octets n'ont pas la signature PNG suivie d'un `IHDR`."""
    if len(data) < 24 or not data.startswith(_PNG_SIGNATURE):
        return None
    if data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def is_png(data: bytes) -> bool:
    """Signature PNG suivie d'un en-tête `IHDR` aux dimensions non
    nulles."""
    size = _png_size(data)
    return size is not None and size[0] > 0 and size[1] > 0


def _limited(
    argv: list,
    memory_bytes: int | None = None,
    file_bytes: int | None = None,
    cpu_seconds: int | None = None,
) -> list:
    """`argv` précédé du tremplin qui lui pose ses plafonds avant de s'y
    substituer : `memory_bytes` (`CONVERT_MEMORY_BYTES` lu à l'appel par
    défaut), `file_bytes` (`CONVERT_FILE_BYTES` de même) et, s'il est
    donné, `cpu_seconds` ; sans lui, le plafond de CPU hérité reste."""
    if memory_bytes is None:
        memory_bytes = CONVERT_MEMORY_BYTES
    if file_bytes is None:
        file_bytes = CONVERT_FILE_BYTES
    return [
        sys.executable,
        "-I",
        "-c",
        _LIMITS_CODE,
        str(memory_bytes),
        str(file_bytes),
        str(cpu_seconds or 0),
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


def convert_checked(
    data: bytes,
    name: str,
    *,
    converters: list | None = None,
    safe: bool = False,
    timeout: float | None = None,
    cpu_seconds: int | None = None,
    memory_bytes: int | None = None,
    file_bytes: int | None = None,
    max_png_bytes: int | None = None,
    strict: bool = False,
) -> bytes:
    """Le PNG rastérisé depuis `data`, une source déjà passée par
    `check_svg`.

    `converters` None : `safe_converters()` si `safe`, sinon
    `available_converters()`, résolus ICI, après le contrôle de la source
    par l'appelant : un refus ne lance aucun processus, sonde comprise.
    Seul le premier convertisseur sert. Les autres `None` prennent la
    constante du module lue à l'appel (`CONVERT_TIMEOUT_S`,
    `CONVERT_MEMORY_BYTES`, `CONVERT_FILE_BYTES`, `MAX_IMAGE_BYTES`) ;
    `cpu_seconds` None ne pose aucun plafond de temps CPU.

    `SvgError` : aucun convertisseur (`no_converter`, le message dit quoi
    installer), conversion en échec, délai dépassé, sortie illisible ou
    qui n'est pas un PNG (`failed`), PNG de plus de `max_png_bytes`
    (`size`) ; en mode `strict`, PNG plus large que `MAX_WIDTH_PX` ou plus
    haut que `MAX_HEIGHT_PX + 1` (`pixels` ; le pixel de plus absorbe
    l'arrondi du convertisseur).
    """
    if converters is None:
        converters = safe_converters() if safe else available_converters()
    if not converters:
        raise SvgError(
            f"{t('mail_rules_err_svg_no_converter')} {INSTALL_HINT}",
            "no_converter",
        )
    if timeout is None:
        timeout = CONVERT_TIMEOUT_S
    if max_png_bytes is None:
        max_png_bytes = MAX_IMAGE_BYTES
    converter = converters[0]
    attrs = svg_root_attrs(_head_text(data)) or {}
    width = target_width(attrs, strict=strict)
    density = target_density(attrs, width)

    def failed(detail: str) -> SvgError:
        return SvgError(
            f"{t('mail_rules_err_svg_failed')} {name} ({detail})", "failed"
        )

    # Le dossier temporaire, la source écrite, le processus et la sortie
    # lue : toute `OSError` (dossier plein ou interdit en écriture compris)
    # devient le refus `failed`.
    try:
        with tempfile.TemporaryDirectory(prefix="todo-svg-") as folder:
            source = os.path.join(folder, _SOURCE_NAME)
            output = os.path.join(folder, _OUTPUT_NAME)
            with open(source, "wb") as handle:
                handle.write(data)
            argv = converter.argv(source, output, width, density)
            limited = _limited(argv, memory_bytes, file_bytes, cpu_seconds)
            try:
                code = _run(limited, folder, timeout)
            except subprocess.TimeoutExpired as exc:
                raise failed(f"{converter.name}, > {timeout:g} s") from exc
            if code != 0:
                raise failed(f"{converter.name}, {code}")
            with open(output, "rb") as handle:
                png = handle.read(max_png_bytes + 1)
    except OSError as exc:
        raise failed(converter.name) from exc
    if len(png) > max_png_bytes:
        raise _error("mail_rules_err_image_size", name, "size")
    if not is_png(png):
        raise failed(converter.name)
    if strict:
        png_width, png_height = _png_size(png)
        if png_width > MAX_WIDTH_PX or png_height > MAX_HEIGHT_PX + 1:
            raise _error("mail_rules_err_image_pixels", name, "pixels")
    return png


def svg_bytes_to_png(
    raw: bytes,
    name: str,
    *,
    strict: bool = True,
    max_source_bytes: int | None = None,
    **convert,
) -> bytes:
    """Le PNG d'une source SVG en octets : `check_svg` puis
    `convert_checked`, aux mêmes `strict` et `name`. La source est
    contrôlée AVANT que `convert_checked` ne résolve les convertisseurs ;
    `convert` porte les autres arguments de `convert_checked`."""
    data = check_svg(raw, name, strict=strict, max_bytes=max_source_bytes)
    return convert_checked(data, name, strict=strict, **convert)


def svg_to_png(
    src: Path,
    *,
    converters: list | None = None,
    timeout: float = CONVERT_TIMEOUT_S,
) -> bytes:
    """Les octets du PNG rastérisé depuis le SVG `src` (mode ordinaire).

    `converters` remplace `available_converters()` ; seul le premier
    sert. `SvgError` quand `read_svg` refuse la source, puis aux cas de
    `convert_checked`, PNG de plus de `MAX_IMAGE_BYTES` compris.
    """
    src = Path(src)
    data = read_svg(src)
    return convert_checked(
        data, src.name, converters=converters, timeout=timeout
    )
