#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Test harness of the Stream Deck deck program.

Installs stub `PIL`, `StreamDeck` and `translator` modules, loads the deck
program as the package `erplibre_streamdeck/` and drives it on a
`FakeDeck` with every outside effect replaced:

- `subprocess.run`, `subprocess.check_output` and `subprocess.Popen` answer
  from a `FakeProcesses` table and record each call as one effect line;
  a command the table does not know is recorded in `unknown` and gets
  return code 127, so nothing reaches the host;
- `shutil.which` answers from a set of command names;
- `time.monotonic`, `time.time` and `time.sleep` read and advance a
  `FakeClock`, so flashes, ticks and timeouts are exact;
- HOME, XDG_CONFIG_HOME and XDG_STATE_HOME point into a sandbox created
  once per process, BEFORE the deck program is loaded.

The patches are global (module attributes of `subprocess`, `shutil`,
`time`), so the program sees them as long as it calls
`subprocess.run(...)`, never a name copied by `from subprocess import`.

Without the `test_` prefix, the unit runner does not take this module for
a test file.
"""

import atexit
import contextlib
import importlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
DECK_DIR = ROOT / "script" / "stream_deck"
PACKAGE = DECK_DIR / "erplibre_streamdeck"
GOLDEN_DIR = ROOT / "test" / "fixtures" / "erplibre_streamdeck"
# STREAMDECK_GOLDEN=update-from-package makes check_golden write the
# goldens from the run instead of comparing.
GOLDEN_ENV = "STREAMDECK_GOLDEN"
GOLDEN_UPDATE = "update-from-package"
# The plugins of the repository: the goldens show the home screen with
# every one of them, so a missing plugin fails the scenarios.
REPO_PLUGINS = frozenset(
    {
        "a11y", "bluetooth", "claude_sessions", "dev_reload", "layouts",
        "mpv_sessions", "sound", "timers", "tiling", "todo_terminals",
        "translate",
    }
)

# (cols, rows) -> key side in pixels. key_layout() answers (rows, cols).
# 3x2 Mini, 4x2 Plus (the Neo has 96 px keys), 5x3 Original and MK.2,
# 8x4 XL.
GEOMETRIES = {(3, 2): 80, (4, 2): 120, (5, 3): 72, (8, 4): 96}

DBUS_DEST = "org.gnome.Shell"
DBUS_PATH = "/org/gnome/Shell/Extensions/ERPLibreHome"
DBUS_IFACE = "org.gnome.Shell.Extensions.ERPLibreHome"

SANDBOX = None
HOME = CONFIG = STATE = FAKE_REPO = None
_LANG = "en_US.UTF-8"


# ---------------------------------------------------------------- sandbox


def _sandbox():
    """Create the per-process sandbox and point the user directories at
    it. Idempotent; the sandbox is removed at exit."""
    global SANDBOX, HOME, CONFIG, STATE, FAKE_REPO
    if SANDBOX is not None:
        return
    SANDBOX = Path(tempfile.mkdtemp(prefix="streamdeck_sandbox."))
    atexit.register(shutil.rmtree, SANDBOX, True)
    HOME = SANDBOX / "home"
    CONFIG = HOME / ".config"
    STATE = HOME / ".local" / "state"
    FAKE_REPO = SANDBOX / "repo"
    os.environ.update(
        HOME=str(HOME),
        XDG_CONFIG_HOME=str(CONFIG),
        XDG_STATE_HOME=str(STATE),
        LANG=_LANG,
    )
    wipe()


def wipe():
    """Empty the user directories and rebuild the fake repository the
    TODO launcher and the streaming translator resolve their paths in."""
    for path in (HOME, FAKE_REPO, SANDBOX / "tmp"):
        shutil.rmtree(path, ignore_errors=True)
    for path in (
        SANDBOX / "tmp",
        CONFIG / "erplibre-home",
        STATE / "erplibre-home",
        FAKE_REPO / "script" / "todo",
        FAKE_REPO / "script" / "stream_deck",
        FAKE_REPO / ".venv.erplibre" / "bin",
    ):
        path.mkdir(parents=True, exist_ok=True)
    for name in (
        "script/todo/todo.py",
        "script/stream_deck/translator_stream.py",
        ".venv.erplibre/bin/activate",
    ):
        (FAKE_REPO / name).write_text("", encoding="utf-8")


def normalize(text):
    """Replace the run-dependent parts of an effect line or a path."""
    text = str(text)
    if SANDBOX is not None:
        text = text.replace(str(FAKE_REPO), "<REPO>")
        text = text.replace(str(SANDBOX), "<SANDBOX>")
    text = text.replace(sys.executable, "<PYTHON>")
    return re.sub(r"sttrec_\w+\.wav", "sttrec_<X>.wav", text)


# ------------------------------------------------------------------ stubs


class FakeFont:
    def __init__(self, size):
        self.size = size


class FakeImage:
    """What Image.new returns: the key colour and the draw operations."""

    def __init__(self, mode, size, color=0):
        self.mode, self.size, self.color = mode, tuple(size), color
        self.ops = []


def _round(value):
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, (list, tuple)):
        return [_round(v) for v in value]
    return value


def _round3(data):
    """Round the floats of a JSON document: clock sums are inexact."""
    if isinstance(data, float):
        return round(data, 3)
    if isinstance(data, list):
        return [_round3(v) for v in data]
    if isinstance(data, dict):
        return {k: _round3(v) for k, v in data.items()}
    return data


class FakeDraw:
    """ImageDraw.Draw: records every call as [name, args..., {kwargs}].
    Fonts are recorded by size; textbbox answers a box proportional to
    the text, enough for the centring arithmetic of set_key."""

    def __init__(self, image=None):
        self.ops = image.ops if image is not None else []

    def textbbox(self, xy, text, font=None, **kw):
        size = getattr(font, "size", 10)
        lines = str(text).split("\n")
        width = max(len(line) for line in lines) * size * 0.6
        return (0, 0, int(width), int(size * 1.2 * len(lines)))

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def record(*args, **kw):
            if isinstance(kw.get("font"), FakeFont):
                kw["font"] = kw["font"].size
            op = [name] + [_round(a) for a in args]
            if kw:
                op.append({k: _round(v) for k, v in sorted(kw.items())})
            self.ops.append(op)

        return record


class TransportError(Exception):
    pass


DEVICES = []  # what DeviceManager().enumerate() answers


def _module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _install_pil():
    image = _module("PIL.Image", new=FakeImage)
    draw = _module("PIL.ImageDraw", Draw=FakeDraw)
    font = _module(
        "PIL.ImageFont",
        truetype=lambda path, size, *a, **kw: FakeFont(size),
        load_default=lambda size=None: FakeFont(size or 10),
    )
    _module("PIL", Image=image, ImageDraw=draw, ImageFont=font)


def _install_streamdeck():
    class DeviceManager:
        def enumerate(self):
            return list(DEVICES)

    pilhelper = _module(
        "StreamDeck.ImageHelpers.PILHelper",
        to_native_key_format=lambda deck, image: image,
        create_image=lambda deck, background="black": FakeImage(
            "RGB", deck.key_image_format()["size"], background
        ),
    )
    helpers = _module("StreamDeck.ImageHelpers", PILHelper=pilhelper)
    devmgr = _module("StreamDeck.DeviceManager", DeviceManager=DeviceManager)
    transport_t = _module(
        "StreamDeck.Transport.Transport", TransportError=TransportError
    )
    transport = _module("StreamDeck.Transport", Transport=transport_t)
    _module(
        "StreamDeck",
        DeviceManager=devmgr,
        ImageHelpers=helpers,
        Transport=transport,
    )


class FakeBackend:
    """An STT or LLM backend: a name, and a fixed transcription."""

    def __init__(self, name, text="bonjour le monde"):
        self.name, self.text = name, text

    def transcribe(self, path):
        TRANSLATOR.calls.append(f"transcribe {self.name}")
        return self.text


class TranslatorScript:
    """The answers of the stub `translator` module, reset per test."""

    def __init__(self):
        self.stt = [FakeBackend("whisper.cpp"), FakeBackend("vosk")]
        self.outputs = ["type", "clip"]
        self.llm = [FakeBackend("ollama")]
        self.history = []
        self.vad = False
        self.timeout = 30
        self.record_ok = True
        self.on_silence = None  # what start_recording_vad was handed
        self.calls = []


TRANSLATOR = TranslatorScript()


def _install_translator():
    t = TRANSLATOR

    def log(name, *args):
        t.calls.append(normalize(" ".join([name] + [str(a) for a in args])))

    def start_recording(path, recorder=None):
        log("start_recording", path)
        return FakePopen(["arecord", path]) if t.record_ok else None

    def start_recording_vad(path, on_silence):
        log("start_recording_vad", path)
        t.on_silence = on_silence
        return FakePopen(["arecord", path]) if t.record_ok else None

    def output_text(text, method):
        log("output_text", repr(text), method)
        return True

    _module(
        "translator",
        OUTPUT_TYPE="type",
        OUTPUT_CLIP="clip",
        LLM_MODE_OFF="off",
        LLM_MODE_TRANSLATE="translate",
        LLM_MODE_CHAT="chat",
        LLM_MODES=["off", "translate", "chat"],
        detect_stt_backends=lambda: list(t.stt),
        detect_output_methods=lambda: list(t.outputs),
        detect_llm_backends=lambda: list(t.llm),
        load_history=lambda: list(t.history),
        clear_history=lambda: (log("clear_history"), t.history.clear()),
        output_text=output_text,
        vad_enabled=lambda: t.vad,
        start_recording=start_recording,
        start_recording_vad=start_recording_vad,
        stop_recording=lambda proc, timeout=3: log("stop_recording"),
        recording_timeout_seconds=lambda: t.timeout,
        llm_postprocess=lambda text, mode, backend: text,
        append_history=lambda text, **kw: log("append_history", repr(text)),
        stt_language=lambda: "fr",
        focused_window_class=lambda: "terminal",
    )


_INSTALLED = False


def install():
    """Sandbox first, then the stub modules, forced: the venv may hold
    the real Pillow, and a real one would make the run depend on fonts."""
    global _INSTALLED
    _sandbox()
    if _INSTALLED:
        return
    _install_pil()
    _install_streamdeck()
    _install_translator()
    if str(DECK_DIR) not in sys.path:
        sys.path.insert(0, str(DECK_DIR))
    _INSTALLED = True


def load_package():
    """The package's app module."""
    install()
    return importlib.import_module("erplibre_streamdeck.app")


# ------------------------------------------------------------- the world


class FakeClock:
    def __init__(self, monotonic=1000.0, wall=1_800_000_000.0):
        self.now, self.wall = monotonic, wall

    def monotonic(self):
        return self.now

    def time(self):
        return self.wall

    def sleep(self, seconds):
        self.advance(seconds)

    def advance(self, seconds):
        self.now += seconds
        self.wall += seconds


class FakePopen:
    def __init__(self, argv, **kw):
        self.args = list(argv)
        self.returncode = None
        self.pid = 4194304

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def gvariant_string(payload):
    """gdbus's printing of a ('s',) answer."""
    text = payload.replace("\\", "\\\\").replace("'", "\\'")
    return f"('{text}',)\n"


class FakeProcesses:
    """Answers commands by the longest matching prefix of their effect
    line. A gdbus line is "gdbus <Method> <args...>", once its
    destination, path and interface are checked; any other command is
    its shell-quoted argv."""

    def __init__(self):
        self.answers = {}
        self.calls = []
        self.unknown = []
        self.popens = []

    def answer(self, prefix, stdout="", returncode=0):
        self.answers[prefix] = (returncode, stdout)

    def line(self, argv):
        argv = [str(a) for a in argv]
        if argv[:1] != ["gdbus"]:
            return normalize(shlex.join(argv))
        ok = (
            argv[argv.index("--dest") + 1] == DBUS_DEST
            and argv[argv.index("--object-path") + 1] == DBUS_PATH
        )
        if "--method" in argv:
            at = argv.index("--method") + 1
            iface, _, method = argv[at].rpartition(".")
            ok = ok and iface == DBUS_IFACE
            words = [method] + argv[at + 1 :]
        else:
            words = [argv[1]]
        if not ok:
            self.unknown.append(shlex.join(argv))
        return normalize("gdbus " + shlex.join(words))

    def _lookup(self, line):
        self.calls.append(line)
        for prefix in sorted(self.answers, key=len, reverse=True):
            if line == prefix or line.startswith(prefix + " "):
                return self.answers[prefix]
        self.unknown.append(line)
        return 127, ""

    def run(self, argv, capture_output=False, text=False, **kw):
        code, out = self._lookup(self.line(argv))
        if not text:
            out = out.encode()
        empty = "" if text else b""
        return subprocess.CompletedProcess(argv, code, out, empty)

    def check_output(self, argv, **kw):
        code, out = self._lookup(self.line(argv))
        if code:
            raise subprocess.CalledProcessError(code, argv, out.encode())
        return out.encode()

    def popen(self, argv, **kw):
        words = [normalize(a) for a in argv]
        self.calls.append("popen " + json.dumps(words, ensure_ascii=False))
        proc = FakePopen(argv)
        self.popens.append(proc)
        return proc


class FakeDeck:
    """A visual deck of `cols` x `rows` keys. `screen` holds the last face
    painted on each key; `is_open` lets `polls` loop iterations through,
    calling `on_poll` before each."""

    def __init__(self, cols, rows, pixels=72):
        self.cols, self.rows, self.pixels = cols, rows, pixels
        self.screen = {}
        self.images = []
        self.polls = 0
        self.on_poll = None
        self.callback = None

    def key_layout(self):
        return (self.rows, self.cols)

    def key_count(self):
        return self.rows * self.cols

    def key_image_format(self):
        return {
            "size": (self.pixels, self.pixels),
            "format": "JPEG",
            "flip": (False, False),
            "rotation": 0,
        }

    def is_visual(self):
        return True

    def deck_type(self):
        return f"Fake {self.cols}x{self.rows}"

    def is_open(self):
        if self.polls <= 0:
            return False
        self.polls -= 1
        if self.on_poll is not None:
            self.on_poll()
        return True

    def set_key_image(self, key, image):
        self.images.append((key, image))

    def set_key_callback(self, callback):
        self.callback = callback

    def open(self):
        pass

    def reset(self):
        pass

    def close(self):
        pass

    def set_brightness(self, percent):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def rendering(self):
        return [self.screen.get(k) for k in range(self.key_count())]


def _hex(color):
    return "%02x%02x%02x" % tuple(color)


def recorder():
    """A drop-in `set_key(deck, key, color, text, icon, extra_draw)` that
    writes [colour, text, icon(, extra ops)] into deck.screen. It also
    takes a KeyFace in place of the colour."""

    def set_key(deck, key, color, text="", icon=None, extra_draw=None):
        if hasattr(color, "color"):
            face = color
            color, text = face.color, face.text
            icon, extra_draw = face.icon, face.extra_draw
        entry = [_hex(color), text, icon]
        if extra_draw is not None:
            draw = FakeDraw()
            side = deck.key_image_format()["size"]
            extra_draw(draw, side[0], side[1])
            entry.append(draw.ops)
        deck.screen[key] = entry

    return set_key


class FakeThread:
    """threading.Thread whose start() queues the target: the test runs
    it with Harness.run_threads(), outside any lock."""

    queue = []

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        FakeThread.queue.append(self)

    def join(self, timeout=None):
        pass


# ---------------------------------------------------------------- targets


class PackageTarget:
    """The package. Its names (app.build, kernel.page_id, kernel.pages,
    kernel.state, render.STYLE, i18n.LANG, paths.REPO_ROOT) are the seams
    this harness asks the package to keep, each read at call time."""

    kind = "package"
    # page id -> (plugin id, {seed name: state attribute})
    SEEDS = {
        "claude_session": ("claude_sessions", {"sid": "sid"}),
        "mpv_session": ("mpv_sessions", {"pid": "pid"}),
        "todo_session": ("todo_terminals", {"window_id": "window_id"}),
        "layout_delete_confirm": ("layouts", {"slot": "pending"}),
        "tiling": ("tiling", {"corner1": "corner1"}),
    }
    # page id -> (plugin id, function of the plugin module). goto calls
    # that function with the plugin's context in place of kernel.goto:
    # the timers plugin exposes enter(ctx), which reads the timers and
    # then calls ctx.goto, so a golden never shows a state the deck
    # cannot reach.
    ENTRIES = {"timer_list": ("timers", "enter")}

    def __init__(self):
        self.app_mod = load_package()
        self.render_mod = importlib.import_module(
            "erplibre_streamdeck.ui.render"
        )
        self.i18n = importlib.import_module("erplibre_streamdeck.ui.i18n")
        self.paths = importlib.import_module("erplibre_streamdeck.paths")
        self.kernel = None

    def patches(self, set_key):
        deck_dir = FAKE_REPO / "script" / "stream_deck"
        return [
            mock.patch.object(self.render_mod, "set_key", set_key),
            mock.patch.object(self.paths, "REPO_ROOT", FAKE_REPO),
            mock.patch.object(self.paths, "STREAM_DECK_DIR", deck_dir),
        ]

    def boot(self, deck, lang="en"):
        """build() loads the plugins and makes the kernel, without the
        lock file, the signal handler or the loop thread. plugins_off is
        given: the shell read of DECK_PLUGINS_OFF is a subprocess."""
        self.i18n.LANG = lang
        style = self.render_mod.STYLE
        style.font_scale = self.render_mod.FONT_SCALE_DEFAULT
        style.show_labels = False
        user_dir = CONFIG / "erplibre-home" / "deck-plugins"
        self.kernel = self.app_mod.build(
            deck, plugins_off=(), user_dir=user_dir
        )

    def complete(self):
        """Every repository plugin is loaded: the home screen can be
        compared with the goldens."""
        return REPO_PLUGINS <= {lp.id for lp in self.kernel.plugins}

    def has_page(self, page):
        return page == "idle" or page in self.kernel.pages

    def page(self):
        return self.kernel.page_id

    def render(self):
        self.kernel.render()

    def press(self, key, pressed=True):
        self.kernel.handle_key(key, pressed)

    def loop(self):
        self.kernel.loop()

    def goto(self, page, **seed):
        plugin, names = self.SEEDS.get(page, (None, {}))
        for name, value in seed.items():
            setattr(self.kernel.state(plugin), names[name], value)
        if page in self.ENTRIES:
            pid, name = self.ENTRIES[page]
            modname = f"erplibre_streamdeck.plugins.{pid}"
            module = importlib.import_module(modname)
            enter = getattr(module, name, None)
            if enter is not None:
                enter(self.kernel.ctx(pid))
                return
        self.kernel.goto(page)


# ----------------------------------------------------------------- driver


# A layout slot stamps its save with the wall clock, in HH:MM.
SAVED_AT = re.compile(r'"saved_at": "[^"]*"')
STATE_FILES = (
    "CONFIG/erplibre-home/settings.json",
    "CONFIG/erplibre-home/layouts.json",
    "STATE/erplibre-home/todo_terminals.json",
)


class Harness:
    """One scenario on one target at one geometry. Every step appends
    {do, page, screen, effects, files} to `steps`; effects are sorted,
    since the order of independent reads is not visible on the deck."""

    def __init__(self, target, cols, rows, lang="en"):
        install()
        wipe()
        self.target = target
        self.deck = FakeDeck(cols, rows, GEOMETRIES.get((cols, rows), 72))
        self.lang = lang
        self.clock = FakeClock()
        self.proc = FakeProcesses()
        self.which = {
            "bluetoothctl",
            "rfkill",
            "wpctl",
            "zenity",
            "script",
            "gnome-terminal",
        }
        self.journal = io.StringIO()
        self.steps = []
        TRANSLATOR.__init__()
        FakeThread.queue.clear()
        self._stack = contextlib.ExitStack()

    def __enter__(self):
        s = self._stack
        for p in self.target.patches(recorder()):
            s.enter_context(p)
        s.enter_context(mock.patch("subprocess.run", self.proc.run))
        s.enter_context(
            mock.patch("subprocess.check_output", self.proc.check_output)
        )
        s.enter_context(mock.patch("subprocess.Popen", self.proc.popen))
        s.enter_context(mock.patch("shutil.which", self._which))
        s.enter_context(mock.patch("time.monotonic", self.clock.monotonic))
        s.enter_context(mock.patch("time.time", self.clock.time))
        s.enter_context(mock.patch("time.sleep", self.clock.sleep))
        s.enter_context(mock.patch.object(threading, "Thread", FakeThread))
        # The recorder's wav files land in the sandbox, not in TMPDIR.
        tmp = str(SANDBOX / "tmp")
        s.enter_context(mock.patch.object(tempfile, "tempdir", tmp))
        s.enter_context(contextlib.redirect_stderr(self.journal))
        s.enter_context(contextlib.redirect_stdout(self.journal))
        return self

    def __exit__(self, *exc):
        self._stack.close()
        return False

    def _which(self, name, *args, **kw):
        return f"/usr/bin/{name}" if name in self.which else None

    def check_clean(self, test):
        """Every command the program ran had an answer in the table."""
        test.assertEqual([], self.proc.unknown, self.journal.getvalue())

    # -- inputs

    def write_json(self, where, data):
        path = self._path(where)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def _path(self, where):
        head, _, tail = where.partition("/")
        base = {"CONFIG": CONFIG, "STATE": STATE, "SANDBOX": SANDBOX}[head]
        return base / tail

    # -- steps

    def _step(self, do):
        files = {}
        for where in STATE_FILES:
            path = self._path(where)
            if path.exists():
                text = normalize(path.read_text(encoding="utf-8"))
                text = SAVED_AT.sub('"saved_at": "<T>"', text)
                files[where] = _round3(json.loads(text))
        effects = sorted(self.proc.calls + TRANSLATOR.calls)
        self.proc.calls.clear()
        TRANSLATOR.calls.clear()
        self.steps.append(
            {
                "do": do,
                "page": self.target.page(),
                "screen": self.deck.rendering(),
                "effects": effects,
                "files": files,
            }
        )

    def boot(self):
        self.target.boot(self.deck, self.lang)
        self.target.render()
        self._step("boot")
        return self

    def press(self, key):
        self.target.press(key, True)
        self.target.press(key, False)
        self._step(f"press {key}")

    def press_face(self, text):
        """Press the key whose face shows `text` (first in key order)."""
        for key, face in enumerate(self.deck.rendering()):
            if face and face[1] == text:
                return self.press(key)
        raise AssertionError(f"no key shows {text!r}")

    def wait(self, seconds):
        self.clock.advance(seconds)

    def loop(self, iterations=1, on_poll=None):
        """Run the deck loop for `iterations` passes of 0.3 s each."""
        self.deck.polls = iterations
        self.deck.on_poll = on_poll
        self.target.loop()
        self.deck.on_poll = None
        self._step(f"loop {iterations}")

    def goto(self, page, **seed):
        self.target.goto(page, **seed)
        self._step(f"goto {page}")

    def run_threads(self):
        while FakeThread.queue:
            job = FakeThread.queue.pop(0)
            job.target(*job.args, **job.kwargs)
        self._step("threads")


# ----------------------------------------------------------------- golden


def golden_path(name):
    return GOLDEN_DIR / f"{name}.json"


def check_golden(test, name, inputs, runs):
    """Compare `runs` ({"5x3": steps, ...}) to the golden `name`, or
    write it from the run when STREAMDECK_GOLDEN=update-from-package:
    a deliberate change of the deck's output rewrites the goldens it
    touches, and the diff of the JSON files is what gets reviewed."""
    path = golden_path(name)
    if os.environ.get(GOLDEN_ENV) == GOLDEN_UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"format": 1, "inputs": inputs, "geometries": runs}
        path.write_text(
            json.dumps(body, indent=1, ensure_ascii=False, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        return
    if not path.exists():
        test.fail(f"{path.name} missing")
    expected = json.loads(path.read_text(encoding="utf-8"))["geometries"]
    test.assertEqual(sorted(expected), sorted(runs))
    for geometry, steps in runs.items():
        want = expected[geometry]
        test.assertEqual(
            [s["do"] for s in want], [s["do"] for s in steps], geometry
        )
        for got, ref in zip(steps, want, strict=True):
            with test.subTest(geometry=geometry, step=ref["do"]):
                test.assertEqual(ref, got)
