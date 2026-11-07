#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le contrôle et la conversion d'un SVG par le noyau, sans le client :
API en octets, codes de refus, mode strict d'une source non fiable,
convertisseurs sûrs et bornes du processus fils.

N'importe que la bibliothèque standard et `erplibre_mail_core` : tourne
aussi sous le Python du venv d'Odoo. Les convertisseurs sont factices
(exécutables Python dans un `PATH` temporaire) : aucun vrai convertisseur
n'est lancé.
"""

import builtins
import gzip
import io
import json
import os
import resource
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE / "script" / "lib" / "erplibre_mail_core") not in sys.path:
    sys.path.insert(0, str(RACINE / "script" / "lib" / "erplibre_mail_core"))

from erplibre_mail_core.i18n import t, using_lang  # noqa: E402
from erplibre_mail_core.rules import svg  # noqa: E402
from erplibre_mail_core.rules.model import RuleError  # noqa: E402

DESSIN = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="100">'
    '<circle cx="50" cy="50" r="40" fill="red"/></svg>'
)
W3C_11 = (
    '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"'
    ' "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'
)
W3C_10 = (
    '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.0//EN"'
    ' "http://www.w3.org/TR/2001/REC-SVG-20010904/DTD/svg10.dtd">\n'
)
PNG_DATA = "data:image/png;base64,iVBORw0KGgo="
# La vraie sonde, avant que les tests ne la remplacent.
REAL_PROBE = svg._cairosvg_available


def dessin(corps: str = "", entete: str = "", **attrs) -> bytes:
    """Un SVG de 300 × 100 dont la racine reçoit `attrs` et le corps
    `corps`, précédé de `entete`."""
    valeurs = {"width": "300", "height": "100", **attrs}
    texte = " ".join(f'{k}="{v}"' for k, v in valeurs.items())
    return (
        f'{entete}<svg xmlns="http://www.w3.org/2000/svg"'
        f' xmlns:xlink="http://www.w3.org/1999/xlink" {texte}>{corps}</svg>'
    ).encode()


# Faux convertisseur : écrit ses arguments et ses plafonds dans
# `FAKE_SVG_LOG`, puis écrit un PNG dont l'`IHDR` porte `FAKE_SVG_SIZE`
# (« LxH ») dans le fichier de sortie qu'il trouve dans ses arguments.
FAKE_CONVERTER = """\
import json, os, resource, struct, sys, time, zlib

argv = sys.argv[1:]
limits = [resource.getrlimit(resource.RLIMIT_AS)[0],
          resource.getrlimit(resource.RLIMIT_FSIZE)[0],
          resource.getrlimit(resource.RLIMIT_CPU)[0]]
with open(os.environ["FAKE_SVG_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"name": os.path.basename(sys.argv[0]),
                          "argv": argv, "limits": limits}) + "\\n")
if "--output" in argv:
    out = argv[argv.index("--output") + 1]
else:
    out = argv[-1]

def chunk(kind, data):
    body = kind + data
    return (struct.pack(">I", len(data)) + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

width, height = (int(v) for v in os.environ.get("FAKE_SVG_SIZE", "1x1").split("x"))
png = (b"\\x89PNG\\r\\n\\x1a\\n"
       + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(b"\\x00\\x00"))
       + chunk(b"IEND", b""))
mode = os.environ.get("FAKE_SVG_MODE", "ok")
if mode == "sleep":
    time.sleep(30)
with open(out, "wb") as handle:
    if mode == "big":
        handle.write(png + b"\\x00" * int(os.environ["FAKE_SVG_BIG"]))
    else:
        handle.write(png)
"""


class SvgCase(unittest.TestCase):
    """Un `PATH` temporaire pour les faux convertisseurs, cairosvg tenu
    pour absent, la langue du noyau fixée au français."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "convert.log"
        self.sentinelle = self.root / "secret" / "sentinelle.txt"
        self.sentinelle.parent.mkdir()
        self.sentinelle.write_text("SECRET-SENTINELLE")
        patches = (
            mock.patch.dict(
                os.environ,
                {
                    "PATH": str(self.bin),
                    "FAKE_SVG_LOG": str(self.log),
                    "FAKE_SVG_MODE": "ok",
                },
            ),
            mock.patch.object(svg, "_cairosvg_available", return_value=False),
            using_lang("fr"),
        )
        for patch in patches:
            patch.__enter__()
            self.addCleanup(patch.__exit__, None, None, None)

    def fake(self, *names: str) -> None:
        for name in names:
            path = self.bin / name
            path.write_text(f"#!{sys.executable}\n{FAKE_CONVERTER}")
            path.chmod(0o755)

    def calls(self) -> list:
        if not self.log.exists():
            return []
        return [
            json.loads(line)
            for line in self.log.read_text().splitlines()
            if line
        ]

    def refused(self, data: bytes, code: str, name="dessin.svg", **kw):
        with self.assertRaises(svg.SvgError) as caught:
            svg.check_svg(data, name, **kw)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        return caught.exception


class Isolation:
    """Contexte qui fait lever toute création de processus et toute
    connexion, et note chaque chemin ouvert."""

    def __init__(self):
        self.opened = []
        self._patches = []

    def __enter__(self):
        def interdit(*args, **kw):
            raise AssertionError(f"appel interdit : {args[:1]}")

        real_open = builtins.open
        real_os_open = os.open

        def note_open(file, *args, **kw):
            if isinstance(file, (str, bytes, os.PathLike)):
                self.opened.append(os.fsdecode(file))
            return real_open(file, *args, **kw)

        def note_os_open(path, *args, **kw):
            self.opened.append(os.fsdecode(path))
            return real_os_open(path, *args, **kw)

        self._patches = [
            mock.patch.object(subprocess, "Popen", side_effect=interdit),
            mock.patch.object(socket.socket, "connect", interdit),
            mock.patch.object(socket, "create_connection", interdit),
            mock.patch.object(builtins, "open", note_open),
            mock.patch.object(io, "open", note_open),
            mock.patch.object(os, "open", note_os_open),
            mock.patch.dict(svg._cairosvg_probe, clear=True),
        ]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self._patches):
            patch.stop()
        return False


class TestCheck(SvgCase):
    def test_check_svg_returns_the_decompressed_bytes(self):
        """Une source en gzip rend ses octets décompressés, qu'elle se
        nomme `.svgz` ou `.svg`."""
        packed = gzip.compress(DESSIN.encode())
        for name in ("dessin.svgz", "dessin.svg"):
            with self.subTest(name=name):
                self.assertEqual(svg.check_svg(packed, name), DESSIN.encode())
        self.assertEqual(
            svg.check_svg(DESSIN.encode(), "a.svg"), DESSIN.encode()
        )

    def test_each_refusal_has_its_code(self):
        """`source_size` avant et après décompression, `invalid` sans
        racine ou pour un `.svgz` en clair, `external`."""
        grand = DESSIN.encode() + b" " * 2000
        self.refused(grand, "source_size", max_bytes=1000)
        self.refused(gzip.compress(grand), "source_size", max_bytes=1000)
        self.refused(b"<html><body/></html>", "invalid")
        self.refused(DESSIN.encode(), "invalid", name="dessin.svgz")
        self.refused(b"\x1f\x8bpas du gzip", "invalid")
        self.refused(
            dessin('<image href="http://example.org/x.png"/>'), "external"
        )

    def test_read_svg_keeps_its_messages(self):
        """`read_svg` lève une `SvgError`, sous-classe de `RuleError`,
        aux textes des clés `mail_rules_err_*` d'avant."""
        self.assertTrue(issubclass(svg.SvgError, RuleError))
        cas = {
            "absent.svg": (None, "mail_rules_err_image_missing", "missing"),
            "page.svg": (b"<html/>", "mail_rules_err_svg_invalid", "invalid"),
            "lien.svg": (
                dessin('<use href="autre.svg#a"/>'),
                "mail_rules_err_svg_external",
                "external",
            ),
        }
        for name, (contenu, cle, code) in cas.items():
            with self.subTest(name=name):
                path = self.root / name
                if contenu is not None:
                    path.write_bytes(contenu)
                with self.assertRaises(RuleError) as caught:
                    svg.read_svg(path)
                self.assertEqual(str(caught.exception), f"{t(cle)} {name}")
                self.assertEqual(caught.exception.code, code)
        with mock.patch.object(svg, "MAX_SVG_BYTES", 50):
            path = self.root / "lourd.svg"
            path.write_bytes(DESSIN.encode())
            with self.assertRaises(svg.SvgError) as caught:
                svg.read_svg(path)
        self.assertEqual(caught.exception.code, "source_size")
        self.assertEqual(
            str(caught.exception),
            f"{t('mail_rules_err_image_size')} lourd.svg",
        )


class TestStrict(SvgCase):
    def test_strict_refuses_scripts(self):
        """`<script>`, `<svg:script>`, `<SCRIPT >` : refusés en strict,
        acceptés hors strict."""
        for corps in (
            "<script>alert(1)</script>",
            "<svg:script>alert(1)</svg:script>",
            "<SCRIPT >alert(1)</SCRIPT>",
        ):
            with self.subTest(corps=corps):
                data = dessin(corps)
                self.refused(data, "unsafe", strict=True)
                self.assertEqual(svg.check_svg(data, "a.svg"), data)

    def test_strict_refuses_event_handlers(self):
        """`onload=` et `ONCLICK =` : refusés ; `xon=` et `data-on=` ne
        sont pas des événements."""
        for attrs in ({"onload": "f()"}, {"ONCLICK ": "f()"}):
            with self.subTest(attrs=attrs):
                self.refused(dessin(**attrs), "unsafe", strict=True)
        data = dessin('<rect xon="1" data-on="x" width="1" height="1"/>')
        self.assertEqual(svg.check_svg(data, "a.svg", strict=True), data)

    def test_strict_refuses_animation_and_embedded_documents(self):
        """`set`, `animate`, `animateMotion`, `foreignObject`, `iframe`,
        `object` : refusés en strict."""
        for corps in (
            '<set attributeName="fill" to="red"/>',
            '<animate attributeName="r" to="4"/>',
            '<animateMotion path="M0 0"/>',
            "<foreignObject><p>x</p></foreignObject>",
            "<iframe/>",
            "<object/>",
        ):
            with self.subTest(corps=corps):
                self.refused(dessin(corps), "unsafe", strict=True)

    def test_strict_refuses_entities_and_internal_subsets(self):
        """Entités imbriquées et DOCTYPE à sous-ensemble refusés ; les
        DOCTYPE W3C 1.0 et 1.1 sans sous-ensemble restent acceptés."""
        rires = (
            '<!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa">'
            '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
            '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>\n'
        )
        self.refused(
            dessin("<text>&c;</text>", entete=rires), "unsafe", strict=True
        )
        self.refused(
            dessin(entete="<!DOCTYPE svg [ ]>\n"), "unsafe", strict=True
        )
        # Une déclaration hors de tout DOCTYPE est refusée pour elle-même.
        self.refused(dessin('<!ENTITY a "aaaa">'), "unsafe", strict=True)
        for entete in (W3C_10, W3C_11):
            data = dessin(entete=entete)
            self.assertEqual(svg.check_svg(data, "a.svg", strict=True), data)

    def test_strict_refuses_nested_data(self):
        """Un `data:` d'image ou de SVG est refusé en strict (`embedded`,
        texte propre), le premier accepté hors strict ; `metadata: x`
        n'est pas un `data:`."""
        png = dessin(f'<image href="{PNG_DATA}"/>')
        imbrique = dessin('<image href="data:image/svg+xml;base64,PHN2Zy8+"/>')
        for data in (png, imbrique):
            erreur = self.refused(data, "embedded", strict=True)
            self.assertEqual(
                str(erreur), f"{t('mail_rules_err_svg_embedded')} dessin.svg"
            )
        self.assertEqual(svg.check_svg(png, "a.svg"), png)
        texte = dessin("<desc>metadata: x</desc>")
        self.assertEqual(svg.check_svg(texte, "a.svg", strict=True), texte)

    def test_an_external_entity_is_refused_without_reading_it(self):
        """Une entité `SYSTEM` vers un fichier : `external`, aucun
        processus, aucune connexion, le fichier jamais ouvert."""
        entete = (
            f'<!DOCTYPE svg [<!ENTITY x SYSTEM "file://{self.sentinelle}">]>\n'
        )
        data = dessin("<text>&x;</text>", entete=entete)
        self.fake("rsvg-convert")
        for strict in (False, True):
            with self.subTest(strict=strict), Isolation() as spy:
                with self.assertRaises(svg.SvgError) as caught:
                    svg.svg_bytes_to_png(
                        data, "piege.svg", strict=strict, safe=True
                    )
                self.assertEqual(caught.exception.code, "external")
                self.assertNotIn(str(self.sentinelle), spy.opened)
        self.assertEqual(self.calls(), [])

    def test_strict_refuses_a_degenerate_ratio(self):
        """1 × 100000000 : `pixels` en strict sans convertisseur lancé,
        passé au convertisseur hors strict ; 101,5 × 10000 : accepté,
        largeur 48 en strict (partie entière), 49 hors strict."""
        self.fake("rsvg-convert")
        bombe = dessin(width="1", height="100000000")
        with Isolation():
            with self.assertRaises(svg.SvgError) as caught:
                svg.svg_bytes_to_png(bombe, "bombe.svg", strict=True)
        self.assertEqual(caught.exception.code, "pixels")
        self.assertEqual(self.calls(), [])
        svg.svg_bytes_to_png(bombe, "bombe.svg", strict=False)
        self.assertEqual(len(self.calls()), 1)
        etroit = dessin(width="101.5", height="10000")
        for strict, largeur in ((True, "48"), (False, "49")):
            with self.subTest(strict=strict):
                svg.svg_bytes_to_png(etroit, "etroit.svg", strict=strict)
                argv = self.calls()[-1]["argv"]
                self.assertEqual(argv[argv.index("--width") + 1], largeur)

    def test_strict_refuses_hidden_encodings_and_dtd_declarations(self):
        """En strict : UTF-7 (déclaration courte ou allongée d'espaces
        au-delà de 1 Kio), déclaration XML de plus de 1 Kio, UTF-16, BOM UTF-16,
        octet NUL, `ATTLIST`,
        `ELEMENT`, `NOTATION`, DOCTYPE à `>` entre guillemets suivi d'un
        sous-ensemble, DOCTYPE `SYSTEM` : refusés sans processus ni
        lecture ; UTF-8 et US-ASCII acceptés ; hors strict, l'`ATTLIST`
        passe."""
        cible = f"file://{self.sentinelle}"
        attlist = f'<!DOCTYPE svg [<!ATTLIST image href CDATA "{cible}">]>\n'
        unsafe = {
            "utf-7": dessin(
                "+ADw-script+AD4-alert(1)+ADw-/script+AD4-",
                entete='<?xml version="1.0" encoding="UTF-7"?>\n',
            ),
            "utf-7-padded": dessin(
                "+ADw-script+AD4-alert(1)+ADw-/script+AD4-",
                entete='<?xml version="1.0"'
                + " " * 1100
                + 'encoding="UTF-7"?>\n',
            ),
            "utf-7-padded-newlines": dessin(
                "+ADw-script+AD4-alert(1)+ADw-/script+AD4-",
                entete='<?xml version="1.0"'
                + "\n" * 3000
                + ' encoding="UTF-7"?>\n',
            ),
            "decl-too-long": dessin(
                entete='<?xml version="1.0"' + " " * 1100 + "?>\n"
            ),
            "utf-16-decl": dessin(
                entete='<?xml version="1.0" encoding="UTF-16"?>\n'
            ),
            "nul": dessin("<desc>a\x00b</desc>"),
            "attlist": dessin('<image width="1" height="1"/>', entete=attlist),
            "attlist-bare": dessin(
                f'<!ATTLIST image href CDATA "{cible}"><image width="1"/>'
            ),
            "element": dessin(entete="<!DOCTYPE svg [<!ELEMENT svg ANY>]>\n"),
            "notation": dessin(
                entete='<!DOCTYPE svg [<!NOTATION n SYSTEM "x">]>\n'
            ),
            "doctype-system": dessin(
                entete=f'<!DOCTYPE svg SYSTEM "{cible}">\n'
            ),
        }
        self.fake("rsvg-convert")
        for nom, data in unsafe.items():
            with self.subTest(nom=nom), Isolation() as spy:
                with self.assertRaises(svg.SvgError) as caught:
                    svg.svg_bytes_to_png(
                        data, "piege.svg", strict=True, safe=True
                    )
                self.assertEqual(caught.exception.code, "unsafe")
                self.assertNotIn(str(self.sentinelle), spy.opened)
        # Refusés, quel qu'en soit le code : la racine ne se lit pas après
        # une marque UTF-16, ni après un DOCTYPE fermé par un `>` entre
        # guillemets.
        refuses = (
            "\ufeff".encode("utf-16-le") + DESSIN.encode("utf-16-le"),
            dessin(entete='<!DOCTYPE svg PUBLIC "a>b" [ <!-- x --> ]>\n'),
        )
        for data in refuses:
            with Isolation(), self.assertRaises(svg.SvgError):
                svg.svg_bytes_to_png(data, "piege.svg", strict=True, safe=True)
        self.assertEqual(self.calls(), [])
        for codage in ("utf-8", "US-ASCII"):
            data = dessin(
                entete=f'<?xml version="1.0" encoding="{codage}"?>\n'
            )
            self.assertEqual(svg.check_svg(data, "a.svg", strict=True), data)
        # Une déclaration qui ne se ferme pas cache ce qui la suit.
        self.assertTrue(
            svg.hidden_encoding(b'<?xml version="1.0" ' + DESSIN.encode())
        )
        # Une déclaration sans codage et un `?>` lointain dans le corps
        # n'ont rien d'un codage caché.
        for data in (
            dessin(entete='<?xml version="1.0"?>\n'),
            dessin("<desc>" + "x" * 4000 + "?></desc>"),
        ):
            self.assertEqual(svg.check_svg(data, "a.svg", strict=True), data)
        self.assertEqual(
            svg.check_svg(unsafe["attlist"], "a.svg"), unsafe["attlist"]
        )

    def test_strict_scans_are_linear(self):
        """1 Mio de `<a`, `on`, `<!` ou `<!DOCTYPE` sans fin : moins d'une
        seconde chacun."""
        for motif in ("<a", " on", "<!", "<!DOCTYPE "):
            with self.subTest(motif=motif):
                data = dessin("<desc>" + motif * (1024 * 1024 // len(motif)))
                debut = time.monotonic()
                try:
                    svg.check_svg(data, "a.svg", strict=True)
                except svg.SvgError:
                    pass
                self.assertLess(time.monotonic() - debut, 1.0)

    def test_looks_like_svg(self):
        """Vrai pour du gzip, un prologue suivi de `<svg>`, un préfixe
        `svg:` ; faux pour un PNG, du HTML, du texte."""
        for data in (
            gzip.compress(b"x"),
            b'<?xml version="1.0"?>\n<!-- x -->\n' + DESSIN.encode(),
            b'<svg:svg xmlns:svg="http://www.w3.org/2000/svg"/>',
        ):
            self.assertTrue(svg.looks_like_svg(data))
        for data in (b"\x89PNG\r\n\x1a\n", b"<html><svg/></html>", b"bonjour"):
            self.assertFalse(svg.looks_like_svg(data))


class TestConversion(SvgCase):
    def test_conversion_passes_the_given_bounds(self):
        """Les plafonds donnés arrivent au convertisseur ; sans
        `cpu_seconds`, la limite de CPU est celle du parent."""
        self.fake("rsvg-convert")
        svg.svg_bytes_to_png(
            DESSIN.encode(),
            "a.svg",
            memory_bytes=300 * 1024 * 1024,
            file_bytes=5 * 1024 * 1024,
            cpu_seconds=7,
            timeout=15,
        )
        self.assertEqual(
            self.calls()[-1]["limits"], [300 * 1024 * 1024, 5 * 1024 * 1024, 7]
        )
        svg.svg_bytes_to_png(DESSIN.encode(), "a.svg", strict=False)
        parent = resource.getrlimit(resource.RLIMIT_CPU)[0]
        self.assertEqual(
            self.calls()[-1]["limits"],
            [svg.CONVERT_MEMORY_BYTES, svg.CONVERT_FILE_BYTES, parent],
        )

    def test_strict_refuses_a_png_too_large_in_pixels(self):
        """Un PNG produit de 1200 × 5000 ou 1200 × 4802 : `pixels` ;
        1200 × 4801 : accepté ; hors strict, rien n'est contrôlé."""
        self.fake("rsvg-convert")
        for taille, code in (
            ("1200x5000", "pixels"),
            ("1200x4802", "pixels"),
            ("1201x10", "pixels"),
            ("1200x4801", None),
        ):
            with self.subTest(taille=taille):
                with mock.patch.dict(os.environ, {"FAKE_SVG_SIZE": taille}):
                    if code is None:
                        self.assertTrue(
                            svg.is_png(
                                svg.svg_bytes_to_png(DESSIN.encode(), "a.svg")
                            )
                        )
                        continue
                    with self.assertRaises(svg.SvgError) as caught:
                        svg.svg_bytes_to_png(DESSIN.encode(), "a.svg")
                    self.assertEqual(caught.exception.code, code)
                    svg.svg_bytes_to_png(
                        DESSIN.encode(), "a.svg", strict=False
                    )

    def test_an_unwritable_temp_folder_has_the_failed_code(self):
        """Un dossier temporaire où rien ne s'écrit (plein ou interdit) :
        `failed`, sans processus ni `OSError` brute."""
        self.fake("rsvg-convert")
        ferme = self.root / "ferme"
        ferme.mkdir()
        ferme.chmod(0o500)
        self.addCleanup(ferme.chmod, 0o700)
        if os.access(ferme, os.W_OK):
            self.skipTest("dossier en lecture seule inscriptible (root)")
        with mock.patch.object(tempfile, "tempdir", str(ferme)):
            with self.assertRaises(svg.SvgError) as caught:
                svg.svg_bytes_to_png(DESSIN.encode(), "a.svg")
        self.assertEqual(caught.exception.code, "failed")
        self.assertEqual(self.calls(), [])
        plein = OSError(28, "No space left on device")
        real_open = builtins.open

        def disque_plein(file, mode="r", *args, **kw):
            if "w" in mode and str(file).endswith(svg._SOURCE_NAME):
                raise plein
            return real_open(file, mode, *args, **kw)

        with mock.patch.object(builtins, "open", disque_plein):
            with self.assertRaises(svg.SvgError) as caught:
                svg.svg_bytes_to_png(DESSIN.encode(), "a.svg")
        self.assertEqual(caught.exception.code, "failed")
        self.assertEqual(self.calls(), [])

    def test_the_output_size_has_its_code(self):
        """Un PNG produit au-delà de `max_png_bytes` : `size`."""
        self.fake("rsvg-convert")
        with mock.patch.dict(
            os.environ, {"FAKE_SVG_MODE": "big", "FAKE_SVG_BIG": "5000"}
        ):
            with self.assertRaises(svg.SvgError) as caught:
                svg.svg_bytes_to_png(
                    DESSIN.encode(), "a.svg", max_png_bytes=1000
                )
        self.assertEqual(caught.exception.code, "size")

    def test_safe_converters_never_offer_inkscape_nor_magick(self):
        """Avec rsvg-convert, inkscape et magick : rsvg-convert seul ;
        cairosvg présent : d'abord ; sans les deux : rien."""
        self.fake("rsvg-convert", "inkscape", "magick")
        self.assertEqual(
            [c.name for c in svg.safe_converters()], ["rsvg-convert"]
        )
        with mock.patch.object(svg, "_cairosvg_available", return_value=True):
            self.assertEqual(
                [c.name for c in svg.safe_converters()],
                ["cairosvg", "rsvg-convert"],
            )
        (self.bin / "rsvg-convert").unlink()
        self.assertEqual(svg.safe_converters(), [])

    def test_no_converter_has_its_code(self):
        """Aucun convertisseur sûr : `no_converter`."""
        self.fake("inkscape")
        with self.assertRaises(svg.SvgError) as caught:
            svg.svg_bytes_to_png(DESSIN.encode(), "a.svg", safe=True)
        self.assertEqual(caught.exception.code, "no_converter")

    def test_a_timeout_has_the_failed_code(self):
        """Un convertisseur qui dort au-delà du délai : `failed`, son
        groupe tué."""
        self.fake("rsvg-convert")
        with mock.patch.dict(os.environ, {"FAKE_SVG_MODE": "sleep"}):
            debut = time.monotonic()
            with self.assertRaises(svg.SvgError) as caught:
                svg.svg_bytes_to_png(DESSIN.encode(), "a.svg", timeout=1)
        self.assertEqual(caught.exception.code, "failed")
        self.assertLess(time.monotonic() - debut, 10)

    def test_the_converters_are_resolved_after_the_check(self):
        """Un refus ne lance aucun processus, sonde de cairosvg comprise ;
        une sonde qui dépasse son délai rend faux sans être gardée, un
        échec franc l'est."""
        with (
            mock.patch.object(svg, "_cairosvg_available", REAL_PROBE),
            mock.patch.dict(svg._cairosvg_probe, clear=True),
        ):
            with mock.patch.object(
                subprocess, "Popen", side_effect=AssertionError
            ):
                with self.assertRaises(svg.SvgError) as caught:
                    svg.svg_bytes_to_png(
                        dessin("<script/>"), "a.svg", safe=True, strict=True
                    )
            self.assertEqual(caught.exception.code, "unsafe")
            self.assertEqual(svg._cairosvg_probe, {})
            delai = subprocess.TimeoutExpired("python", 10)
            with mock.patch.object(svg, "_run", side_effect=delai):
                self.assertFalse(svg._cairosvg_available())
            self.assertEqual(svg._cairosvg_probe, {})
            with mock.patch.object(svg, "_run", return_value=0):
                self.assertTrue(svg._cairosvg_available())
            svg._cairosvg_probe.clear()
            with mock.patch.object(svg, "_run", return_value=1):
                self.assertFalse(svg._cairosvg_available())
            with mock.patch.object(svg, "_run", return_value=0):
                self.assertFalse(svg._cairosvg_available())


if __name__ == "__main__":
    unittest.main()
