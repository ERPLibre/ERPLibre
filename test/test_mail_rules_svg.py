#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import gzip
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

from script.todo.mail.rules import storage, svg
from script.todo.mail.rules.model import MAX_IMAGE_BYTES, RuleError

WIDE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="2400" height="600">'
    '<rect width="2400" height="600" fill="#08c"/></svg>'
)
SMALL = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<!-- dessin d'essai -->\n"
    '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"'
    ' "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'
    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="100">'
    '<circle cx="50" cy="50" r="40" fill="red"/></svg>'
)
NO_SIZE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<path d="M0 0h24v24H0z"/></svg>'
)

# Faux convertisseur : écrit ses arguments dans `FAKE_SVG_LOG`, puis agit
# selon `FAKE_SVG_MODE` sur le fichier de sortie qu'il trouve dans ses
# arguments, quelle que soit la syntaxe du convertisseur imité.
FAKE_CONVERTER = """\
import json, os, resource, struct, sys, time, zlib

argv = sys.argv[1:]
limits = [resource.getrlimit(resource.RLIMIT_AS)[0],
          resource.getrlimit(resource.RLIMIT_FSIZE)[0]]
with open(os.environ["FAKE_SVG_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"name": os.path.basename(sys.argv[0]),
                          "argv": argv, "limits": limits}) + "\\n")
if "--output" in argv:
    out = argv[argv.index("--output") + 1]
else:
    flags = [a for a in argv if a.startswith("--export-filename=")]
    out = flags[0].split("=", 1)[1] if flags else argv[-1]
    out = out[4:] if out.startswith("png:") else out

def chunk(kind, data):
    body = kind + data
    return (struct.pack(">I", len(data)) + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

png = (b"\\x89PNG\\r\\n\\x1a\\n"
       + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(b"\\x00\\x00"))
       + chunk(b"IEND", b""))
mode = os.environ.get("FAKE_SVG_MODE", "ok")
if mode == "fail":
    sys.exit(3)
if mode == "sleep":
    time.sleep(30)
if mode == "silent":
    sys.exit(0)
with open(out, "wb") as handle:
    if mode == "garbage":
        handle.write(b"pas une image")
    elif mode == "empty":
        pass
    elif mode == "big":
        handle.write(png + b"\\x00" * int(os.environ["FAKE_SVG_BIG"]))
    else:
        handle.write(png)
"""

# Faux module `cairosvg`, même contrat que le faux exécutable.
FAKE_CAIROSVG = """\
import json, os, shutil

def svg2png(url, write_to, output_width):
    with open(os.environ["FAKE_SVG_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps({"name": "cairosvg", "argv": [url, write_to,
                                                  output_width]}) + "\\n")
    shutil.copyfile(os.environ["FAKE_SVG_PNG"], write_to)
"""


# Faux module `cairosvg` qui s'installe sans sa bibliothèque système.
BROKEN_CAIROSVG = 'raise OSError("bibliothèque cairo introuvable")\n'


def tiny_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        crc = zlib.crc32(body) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + body + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00"))
        + chunk(b"IEND", b"")
    )


class SvgCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.src = root / "src"
        self.bin = root / "bin"
        self.base = root / "mail"
        self.src.mkdir()
        self.bin.mkdir()
        self.log = root / "convert.log"
        self.env = mock.patch.dict(
            os.environ,
            {
                "PATH": str(self.bin),
                "FAKE_SVG_LOG": str(self.log),
                "FAKE_SVG_MODE": "ok",
            },
        )
        self.env.start()
        self.cairo = mock.patch.object(
            svg, "_cairosvg_available", return_value=False
        )
        self.cairo.start()

    def tearDown(self):
        self.cairo.stop()
        self.env.stop()
        self._tmp.cleanup()

    def fake(self, *names: str) -> None:
        for name in names:
            path = self.bin / name
            path.write_text(f"#!{sys.executable}\n{FAKE_CONVERTER}")
            path.chmod(0o755)

    def write(self, name: str, content) -> Path:
        path = self.src / name
        if isinstance(content, str):
            content = content.encode("utf-8")
        path.write_bytes(content)
        return path

    def calls(self) -> list:
        if not self.log.exists():
            return []
        return [
            json.loads(line)
            for line in self.log.read_text().split("\n")
            if line
        ]


class TestDetection(SvgCase):
    def test_svg_names(self):
        for name in ("logo.svg", "LOGO.SVG", "dessin.svgz", "a.b.Svg"):
            with self.subTest(name=name):
                self.assertTrue(svg.is_svg_name(name))
        for name in ("logo.png", "svg", "logo.svg.png", ".svg"):
            with self.subTest(name=name):
                self.assertFalse(svg.is_svg_name(name))

    def test_png_name_replaces_the_extension(self):
        self.assertEqual(svg.png_name("logo.svg"), "logo.png")
        self.assertEqual(svg.png_name("Dessin.SVGZ"), "Dessin.png")

    def test_prolog_and_namespace_prefix_are_accepted(self):
        self.assertIn(b"<circle", svg.read_svg(self.write("a.svg", SMALL)))
        prefixed = (
            '<svg:svg xmlns:svg="http://www.w3.org/2000/svg" width="10">'
            "</svg:svg>"
        )
        attrs = svg.svg_root_attrs(prefixed)
        self.assertEqual(attrs["width"], "10")

    def test_a_dot_svg_that_is_not_svg_is_refused(self):
        for content in (
            "<html><body>pas un dessin</body></html>",
            "texte libre <svg>",
            "<svgx width='1'/>",
            b"\x89PNG\r\n\x1a\n",
        ):
            with self.subTest(content=content):
                path = self.write("faux.svg", content)
                with self.assertRaises(RuleError) as caught:
                    svg.read_svg(path)
                self.assertIn("faux.svg", str(caught.exception))

    def test_svgz_is_decompressed(self):
        path = self.write("dessin.svgz", gzip.compress(SMALL.encode()))
        self.assertIn(b"<circle", svg.read_svg(path))

    def test_svgz_that_is_not_gzip_is_refused(self):
        with self.assertRaises(RuleError):
            svg.read_svg(self.write("dessin.svgz", SMALL))

    def test_decompressed_size_is_bounded(self):
        bomb = gzip.compress(SMALL.encode() + b" " * 5000)
        path = self.write("bombe.svgz", bomb)
        with mock.patch.object(svg, "MAX_SVG_BYTES", 2000):
            with self.assertRaises(RuleError):
                svg.read_svg(path)

    def test_missing_source(self):
        with self.assertRaises(RuleError):
            svg.read_svg(self.src / "absent.svg")

    def test_doctype_internal_subset_is_skipped(self):
        text = (
            '<!DOCTYPE svg [ <!ENTITY marque "a>b"> ]>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="5"/>'
        )
        self.assertEqual(svg.svg_root_attrs(text)["width"], "5")
        self.assertIsNone(svg.svg_root_attrs("<!DOCTYPE svg [ <svg/>"))
        self.assertIsNone(svg.svg_root_attrs("<?xml <svg/>"))


class TestLinearParsing(SvgCase):
    """Une source malformée se refuse en un temps linéaire : aucune
    expression ne revient en arrière de façon combinatoire."""

    def assertFast(self, started: float) -> None:
        self.assertLess(time.monotonic() - started, 1.0)

    def test_unclosed_doctype_with_brackets(self):
        for size in (26, 300):
            with self.subTest(size=size):
                path = self.write("x.svg", "<!DOCTYPE " + "[]" * size)
                started = time.monotonic()
                with self.assertRaises(RuleError):
                    svg.read_svg(path)
                self.assertFast(started)

    def test_long_length_and_attribute_name(self):
        digits = "1" * 30000
        cases = (
            f'<svg width="{digits}x" height="1{" " * 30000}x">',
            "<svg " + "a" * 60000 + ">",
            '<svg href="#a"' + " href" * 12000 + ">",
        )
        for text in cases:
            started = time.monotonic()
            attrs = svg.svg_root_attrs(text)
            self.assertEqual(svg.target_width(attrs), 600)
            self.assertFast(started)

    def test_reference_scan_is_linear(self):
        size = 1024 * 1024
        cases = (
            "a." * (size // 2),
            "<!ENTITY " * (size // 9),
            "href" + " " * size,
            'href="#a" ' * (size // 10),
        )
        for text in cases:
            started = time.monotonic()
            self.assertFalse(svg.external_reference(text))
            self.assertFast(started)


class TestWidth(unittest.TestCase):
    def width(self, **attrs) -> int:
        return svg.target_width(attrs)

    def test_intrinsic_width(self):
        self.assertEqual(self.width(width="300", height="100"), 300)
        self.assertEqual(self.width(width="300px"), 300)
        self.assertEqual(self.width(width="2in"), 192)
        self.assertEqual(self.width(width="72pt"), 96)

    def test_wide_image_is_reduced_to_the_maximum(self):
        self.assertEqual(self.width(width="2400", height="600"), 1200)
        self.assertEqual(self.width(width="5000"), 1200)

    def test_no_absolute_size_gives_the_default(self):
        self.assertEqual(self.width(), 600)
        self.assertEqual(self.width(viewBox="0 0 24 24"), 600)
        self.assertEqual(self.width(width="100%", height="50%"), 600)
        self.assertEqual(self.width(width="0"), 600)

    def test_height_and_viewbox_give_the_width(self):
        self.assertEqual(self.width(height="100", viewBox="0 0 400 200"), 200)

    def test_very_tall_image_reduces_its_width(self):
        width = self.width(width="1000", height="100000")
        self.assertEqual(width, 48)
        self.assertEqual(self.width(viewBox="0,0,10,1000"), 48)

    def test_non_finite_sizes_give_the_default(self):
        cases = (
            {"height": "10", "viewBox": "0 0 nan 1"},
            {"height": "10", "viewBox": "0 0 1 nan"},
            {"height": "10", "viewBox": "0 0 inf 1"},
            {"height": "10", "viewBox": "0 0 -inf 1"},
            {"width": "1e999"},
            {"width": "1e999", "height": "1e999"},
            {"height": "1e300", "viewBox": "0 0 1e300 1e-300"},
        )
        for attrs in cases:
            with self.subTest(attrs=attrs):
                self.assertEqual(svg.target_width(attrs), 600)

    def test_density_reaches_the_target_width(self):
        self.assertEqual(svg.target_density({"width": "2400"}, 1200), 48)
        self.assertEqual(svg.target_density({"width": "1in"}, 96), 96)
        self.assertIsNone(svg.target_density({"viewBox": "0 0 9 9"}, 600))


class TestConversion(SvgCase):
    def test_png_is_returned_and_width_is_passed(self):
        self.fake("rsvg-convert")
        data = svg.svg_to_png(self.write("large.svg", WIDE))
        self.assertTrue(svg.is_png(data))
        (call,) = self.calls()
        self.assertEqual(call["name"], "rsvg-convert")
        argv = call["argv"]
        self.assertEqual(argv[argv.index("--width") + 1], "1200")
        self.assertIn("--keep-aspect-ratio", argv)

    def test_svg_without_size_is_converted_at_the_default_width(self):
        self.fake("rsvg-convert")
        svg.svg_to_png(self.write("icone.svg", NO_SIZE))
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--width") + 1], "600")

    def test_svgz_reaches_the_converter_decompressed(self):
        self.fake("rsvg-convert")
        path = self.write("dessin.svgz", gzip.compress(SMALL.encode()))
        svg.svg_to_png(path)
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--width") + 1], "300")
        self.assertTrue(argv[-1].endswith(".svg"))

    def test_converter_order(self):
        cases = (
            (("inkscape", "rsvg-convert", "magick"), "rsvg-convert"),
            (("inkscape", "magick", "convert"), "inkscape"),
            (("magick", "convert"), "magick"),
            (("convert",), "convert"),
        )
        for names, expected in cases:
            with self.subTest(names=names):
                for old in self.bin.iterdir():
                    old.unlink()
                self.fake(*names)
                found = svg.available_converters()
                self.assertEqual(found[0].name, expected)

    def test_magick_is_capped_and_rasterized_at_the_target_width(self):
        self.fake("magick")
        svg.svg_to_png(self.write("large.svg", WIDE))
        argv = self.calls()[0]["argv"]
        source = next(a for a in argv if a.startswith("svg:"))
        before = argv[: argv.index(source)]
        self.assertEqual(before[before.index("-density") + 1], "48")
        for resource in ("memory", "map", "disk", "area"):
            self.assertIn(resource, before)
        self.assertEqual(argv[argv.index("-resize") + 1], "1200x")
        svg.svg_to_png(self.write("icone.svg", NO_SIZE))
        self.assertNotIn("-density", self.calls()[1]["argv"])

    def test_converter_runs_under_resource_limits(self):
        self.fake("rsvg-convert")
        svg.svg_to_png(self.write("a.svg", SMALL))
        self.assertEqual(
            self.calls()[0]["limits"],
            [svg.CONVERT_MEMORY_BYTES, svg.CONVERT_FILE_BYTES],
        )

    def test_converter_writing_too_much_is_stopped(self):
        self.fake("rsvg-convert")
        os.environ["FAKE_SVG_MODE"] = "big"
        os.environ["FAKE_SVG_BIG"] = "50000"
        with mock.patch.object(svg, "CONVERT_FILE_BYTES", 4096):
            with self.assertRaises(RuleError) as caught:
                svg.svg_to_png(self.write("a.svg", SMALL))
        self.assertIn("rsvg-convert", str(caught.exception))

    def test_cairosvg_comes_before_inkscape(self):
        self.fake("inkscape")
        with mock.patch.object(svg, "_cairosvg_available", return_value=True):
            names = [c.name for c in svg.available_converters()]
        self.assertEqual(names, ["cairosvg", "inkscape"])

    def test_each_converter_writes_where_it_is_told(self):
        for name in ("inkscape", "magick", "convert"):
            with self.subTest(name=name):
                for old in self.bin.iterdir():
                    old.unlink()
                self.fake(name)
                data = svg.svg_to_png(self.write("a.svg", SMALL))
                self.assertTrue(svg.is_png(data))
                self.assertTrue(
                    any("300" in arg for arg in self.calls()[-1]["argv"])
                )

    def test_cairosvg_runs_in_a_child_process(self):
        module = Path(self._tmp.name) / "module"
        module.mkdir()
        (module / "cairosvg.py").write_text(FAKE_CAIROSVG)
        png = self.write("modele.png", tiny_png())
        pythonpath = os.pathsep.join(
            [str(module), os.environ.get("PYTHONPATH", "")]
        )
        with mock.patch.dict(
            os.environ,
            {"PYTHONPATH": pythonpath, "FAKE_SVG_PNG": str(png)},
        ):
            with mock.patch.object(
                svg, "_cairosvg_available", return_value=True
            ):
                data = svg.svg_to_png(self.write("a.svg", WIDE))
        self.assertEqual(data, tiny_png())
        (call,) = self.calls()
        self.assertEqual(call["name"], "cairosvg")
        self.assertEqual(call["argv"][2], 1200)

    def test_injected_converters_replace_the_search(self):
        self.fake("rsvg-convert")
        exe = str(self.bin / "rsvg-convert")
        fake = svg.Converter("essai", svg._inkscape_argv(exe))
        svg.svg_to_png(self.write("a.svg", SMALL), converters=[fake])
        argv = self.calls()[0]["argv"]
        self.assertIn("--export-width=300", argv)

    def test_no_converter_says_what_to_install(self):
        with self.assertRaises(RuleError) as caught:
            svg.svg_to_png(self.write("a.svg", SMALL))
        self.assertIn("librsvg2-bin", str(caught.exception))

    def test_external_references_are_refused_before_any_conversion(self):
        self.fake("magick")
        bodies = (
            '<image href="file:///racine/secret.png"/>',
            '<image xlink:href="text:/racine/secret.txt"/>',
            "<image XLINK:HREF = ' https://example.org/a.png'/>",
            '<use href="autre.svg#forme"/>',
            "<rect style=\"fill:url( 'file:///racine/motif.png')\"/>",
            "<style>@import 'https://example.net/a.css';</style>",
            '<a href="https://example.com/">lien</a>',
        )
        for body in bodies:
            with self.subTest(body=body):
                path = self.write("ref.svg", f"<svg>{body}</svg>")
                with self.assertRaises(RuleError) as caught:
                    svg.svg_to_png(path)
                self.assertIn("ref.svg", str(caught.exception))
        entities = (
            '<!DOCTYPE svg [<!ENTITY f SYSTEM "file:///racine/a">]>',
            '<!DOCTYPE svg [<!ENTITY % p PUBLIC "-//X//Y" "y.dtd">]>',
        )
        for prolog in entities:
            with self.subTest(prolog=prolog):
                path = self.write("ent.svg", f"{prolog}<svg>&f;</svg>")
                with self.assertRaises(RuleError):
                    svg.svg_to_png(path)
        self.assertEqual(self.calls(), [])

    def test_internal_references_are_accepted(self):
        text = (
            '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"'
            ' "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd"'
            ' [<!ENTITY couleur "#08c">]>'
            '<svg xmlns="http://www.w3.org/2000/svg"'
            ' xmlns:xlink="http://www.w3.org/1999/xlink" width="40">'
            '<defs><linearGradient id="g"/></defs>'
            '<rect fill="url(#g)" style="stroke: url( \'#g\')"/>'
            '<use xlink:href="#g"/>'
            '<image href=" data:image/png;base64,iVBORw0KGgo="/></svg>'
        )
        self.assertFalse(svg.external_reference(text))
        self.fake("rsvg-convert")
        self.assertTrue(svg.is_png(svg.svg_to_png(self.write("a.svg", text))))

    def test_non_finite_size_is_converted_at_the_default_width(self):
        self.fake("rsvg-convert")
        text = '<svg height="10" viewBox="0 0 nan 1"/>'
        svg.svg_to_png(self.write("a.svg", text))
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--width") + 1], "600")

    def test_not_svg_is_refused_before_any_conversion(self):
        self.fake("rsvg-convert")
        with self.assertRaises(RuleError):
            svg.svg_to_png(self.write("faux.svg", "<html/>"))
        self.assertEqual(self.calls(), [])

    def test_failures_are_refused_without_the_full_path(self):
        self.fake("rsvg-convert")
        for mode in ("fail", "garbage", "empty", "silent"):
            with self.subTest(mode=mode):
                os.environ["FAKE_SVG_MODE"] = mode
                with self.assertRaises(RuleError) as caught:
                    svg.svg_to_png(self.write("a.svg", SMALL))
                message = str(caught.exception)
                self.assertIn("a.svg", message)
                self.assertIn("rsvg-convert", message)
                self.assertNotIn(str(self.src), message)
                self.assertNotIn(self._tmp.name, message)

    def test_timeout_kills_the_converter(self):
        self.fake("rsvg-convert")
        os.environ["FAKE_SVG_MODE"] = "sleep"
        start = time.monotonic()
        with self.assertRaises(RuleError) as caught:
            svg.svg_to_png(self.write("a.svg", SMALL), timeout=0.5)
        self.assertLess(time.monotonic() - start, 10)
        self.assertIn("0.5 s", str(caught.exception))

    def test_png_too_large_is_refused(self):
        self.fake("rsvg-convert")
        os.environ["FAKE_SVG_MODE"] = "big"
        os.environ["FAKE_SVG_BIG"] = str(MAX_IMAGE_BYTES)
        with self.assertRaises(RuleError) as caught:
            svg.svg_to_png(self.write("a.svg", SMALL))
        self.assertIn("a.svg", str(caught.exception))

    def test_is_png(self):
        self.assertTrue(svg.is_png(tiny_png()))
        self.assertFalse(svg.is_png(b""))
        self.assertFalse(svg.is_png(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32))


class TestCairosvgProbe(unittest.TestCase):
    """La sonde importe cairosvg dans un processus fils : un module
    installé dont l'import échoue ne compte pas comme présent."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.module = root / "module"
        self.module.mkdir()
        (root / "bin").mkdir()
        patches = (
            mock.patch.dict(svg._cairosvg_probe, clear=True),
            mock.patch.dict(
                os.environ,
                {"PATH": str(root / "bin"), "PYTHONPATH": str(self.module)},
            ),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self._tmp.cleanup)
        self.bin = root / "bin"

    def test_importable_module_is_available(self):
        (self.module / "cairosvg.py").write_text("")
        self.assertTrue(svg._cairosvg_available())

    def test_module_that_fails_to_import_is_skipped(self):
        (self.module / "cairosvg.py").write_text(BROKEN_CAIROSVG)
        path = self.bin / "inkscape"
        path.write_text(f"#!{sys.executable}\n{FAKE_CONVERTER}")
        path.chmod(0o755)
        self.assertFalse(svg._cairosvg_available())
        names = [c.name for c in svg.available_converters()]
        self.assertEqual(names, ["inkscape"])

    def test_result_is_kept(self):
        (self.module / "cairosvg.py").write_text("")
        self.assertTrue(svg._cairosvg_available())
        (self.module / "cairosvg.py").write_text(BROKEN_CAIROSVG)
        self.assertTrue(svg._cairosvg_available())


class TestImportMedia(SvgCase):
    def test_svg_is_stored_as_png_only(self):
        self.fake("rsvg-convert")
        ref = storage.import_media(
            "perso", self.write("logo.svg", SMALL), base=self.base
        )
        self.assertEqual(ref.file, "logo.png")
        self.assertEqual(ref.mime, "image/png")
        self.assertEqual(ref.sha256, hashlib.sha256(tiny_png()).hexdigest())
        folder = storage.media_dir("perso", self.base)
        self.assertEqual(os.listdir(folder), ["logo.png"])
        self.assertEqual(
            storage.read_media("perso", ref, base=self.base), tiny_png()
        )

    def test_svgz_is_stored_as_png(self):
        self.fake("rsvg-convert")
        path = self.write("dessin.SVGZ", gzip.compress(SMALL.encode()))
        ref = storage.import_media("perso", path, base=self.base)
        self.assertEqual(ref.file, "dessin.png")

    def test_refused_svg_stores_nothing(self):
        with self.assertRaises(RuleError):
            storage.import_media(
                "perso", self.write("logo.svg", SMALL), base=self.base
            )
        self.fake("rsvg-convert")
        with self.assertRaises(RuleError):
            storage.import_media(
                "perso", self.write("faux.svg", "<p/>"), base=self.base
            )
        folder = storage.media_dir("perso", self.base)
        self.assertEqual(os.listdir(folder), [])


@unittest.skipIf(shutil.which("rsvg-convert") is None, "rsvg-convert absent")
class TestRealRsvg(unittest.TestCase):
    def test_real_conversion(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "large.svg"
            path.write_text(WIDE)
            data = svg.svg_to_png(path)
        self.assertTrue(svg.is_png(data))
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((width, height), (1200, 300))


if __name__ == "__main__":
    unittest.main()
