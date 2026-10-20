# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Start of the deck program: find the deck, build the kernel, run.

build() is what a test drives: the style restored from settings.json,
the plugins loaded, the kernel made, without the lock file, the signal
handler or the loop thread.

main() outlives its deck. When the library closes a deck that vanished,
the plugins are shut down, DeviceManager is polled every
REPLUG_POLL_SEC, and the first visual deck that answers gets a new
kernel built with the same settings. The process, and the deck lock its
caller took, stay for the whole wait; a SIGTERM or a Ctrl-C ends it."""

import subprocess
import sys
import threading
import time

try:
    from StreamDeck.DeviceManager import DeviceManager
    from StreamDeck.Transport.Transport import TransportError
except ImportError as e:
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

import deck_lock

from erplibre_streamdeck import loader, paths
from erplibre_streamdeck import settings as settings_mod
from erplibre_streamdeck.kernel import Kernel
from erplibre_streamdeck.ui import render

# How long the shutdown waits for the kernel lock. A key callback holds
# it across a blocking plugin call (a dialog may wait minutes); past
# this delay the plugins are shut down without it, so the deck is reset
# before systemd's stop timeout kills the service.
SHUTDOWN_LOCK_SEC = 5.0
# While no deck is plugged in, DeviceManager is asked this often.
REPLUG_POLL_SEC = 2.0
# How often main() checks that its deck is still open.
OPEN_POLL_SEC = 0.5
BRIGHTNESS = 80


def _journal(msg):
    print(f"[erplibre-home] {msg}", file=sys.stderr, flush=True)


DECK_SETTING_DEFAULTS = {"plugins_off": [], "session_refresh_sec": 1.0}

# One bash call: the plugin ids, one "off=<id>" line each, then one
# "refresh=<seconds>" line, both validated by the settings library.
_READ_SCRIPT = (
    '. "$0" && deck_plugins_off | sed \'s/^/off=/\' '
    '&& echo "refresh=$(deck_session_refresh_sec)"'
)


def read_deck_settings():
    """The deck's settings from streamdeck.conf, read by the settings
    library the installer and the service use: {"plugins_off": [ids],
    "session_refresh_sec": float}. The defaults come back, with one
    journal line carrying the library's stderr, when the library cannot
    be read: bash missing, too slow, or failing."""
    try:
        done = subprocess.run(
            ["bash", "-c", _READ_SCRIPT, str(paths.SETTINGS_LIB)],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _journal(f"deck settings unreadable: {exc}")
        return dict(DECK_SETTING_DEFAULTS, plugins_off=[])
    if done.returncode != 0:
        _journal(
            f"deck settings unreadable: exit {done.returncode}: "
            f"{done.stderr.strip()}"
        )
        return dict(DECK_SETTING_DEFAULTS, plugins_off=[])
    result = dict(DECK_SETTING_DEFAULTS, plugins_off=[])
    for line in done.stdout.splitlines():
        if line.startswith("off=") and line[4:]:
            result["plugins_off"].append(line[4:])
        elif line.startswith("refresh="):
            try:
                result["session_refresh_sec"] = float(line[8:])
            except ValueError:
                _journal(f"deck settings: bad refresh line {line!r}")
    return result


def build(deck, *, plugins_off=(), user_dir=None, settings=None):
    render.STYLE.restore(settings_mod.load())
    plugins, report = loader.load(off=plugins_off, user_dir=user_dir)
    for entry in report.entries:
        if entry[1] != "active":
            _journal(f"plugin {loader.Report.line(*entry)}")
    kernel = Kernel(deck, plugins, settings)
    for pid, reason in kernel.refused:
        _journal(f"plugin {pid}: refused: {reason}")
    return kernel


def _shutdown_plugins(kernel):
    """Shut the plugins down under the kernel lock, or without it after
    SHUTDOWN_LOCK_SEC (one journal line)."""
    kernel.running = False
    locked = kernel.lock.acquire(timeout=SHUTDOWN_LOCK_SEC)
    if not locked:
        _journal(
            f"kernel lock still held after {SHUTDOWN_LOCK_SEC:g} s: "
            "shutting the plugins down without it"
        )
    try:
        kernel.shutdown()
    finally:
        if locked:
            kernel.lock.release()


def _shutdown(kernel, deck):
    """Shut the plugins down, then reset and close the deck whatever the
    shutdown raises. Either may be None: no kernel built yet, or no deck
    held. A deck that vanished cannot be reset: the library's
    TransportError is one journal line, not a traceback."""
    try:
        if kernel is not None:
            _shutdown_plugins(kernel)
    finally:
        if deck is not None:
            try:
                with deck:
                    deck.reset()
                    deck.close()
            except TransportError as exc:
                _journal(f"Stream Deck not reset: {exc}")


def _first_visual():
    """The first visual deck DeviceManager lists, not opened; None when
    there is none."""
    decks = DeviceManager().enumerate()
    return next((d for d in decks if d.is_visual()), None)


def _open(deck):
    deck.open()
    deck.reset()
    deck.set_brightness(BRIGHTNESS)


def _wait_for_deck():
    """Poll every REPLUG_POLL_SEC until a visual deck opens; return it
    opened, reset and lit. A deck that fails to open, still settling
    after its plug, is closed and tried again at the next poll."""
    _journal("Stream Deck unplugged, waiting for it to come back")
    while True:
        time.sleep(REPLUG_POLL_SEC)
        deck = _first_visual()
        if deck is None:
            continue
        try:
            _open(deck)
        except TransportError:
            deck.close()
            continue
        return deck


def _run(deck, deck_settings):
    """Build a kernel on an opened deck, render it, bind the key
    callback and start the loop thread; return the kernel."""
    kernel = build(
        deck,
        plugins_off=deck_settings["plugins_off"],
        settings={
            "session_refresh_sec": deck_settings["session_refresh_sec"]
        },
    )
    kernel.guard("kernel", "first render", kernel.render)
    deck.set_key_callback(kernel.on_key)
    threading.Thread(target=kernel.loop, daemon=True).start()
    return kernel


def main():
    deck = _first_visual()
    if not deck:
        print("No visual Stream Deck found.")
        sys.exit(deck_lock.NO_DECK_EXIT)

    # From the first open on, `deck` is the deck to reset and `kernel`
    # the plugins to shut down, None for what is not there: a SIGTERM
    # while a kernel builds still resets the deck already lit. While no
    # deck is plugged in, both are None: the plugins are already shut
    # down and there is no deck to reset.
    kernel = None
    try:
        _open(deck)
        rows, cols = deck.key_layout()
        print(f"Window Tiler on {deck.deck_type()} ({cols}x{rows})")

        deck_settings = read_deck_settings()
        kernel = _run(deck, deck_settings)
        if kernel.dbus_ok:
            print("D-Bus tiler extension detected!")
        else:
            print("WARNING: erplibre-home extension not found.",
                  file=sys.stderr, flush=True)
            print("Install: re-login to GNOME to activate the extension.")
        print("Press TILE to enter tiling mode (first corner, second corner).")
        print("Press TIMER to list and toggle tracker timers.")

        while True:
            while deck.is_open():
                time.sleep(OPEN_POLL_SEC)
            gone, kernel, deck = kernel, None, None
            _shutdown_plugins(gone)
            deck = _wait_for_deck()
            kernel = _run(deck, deck_settings)
            rows, cols = deck.key_layout()
            _journal(f"Stream Deck back: {deck.deck_type()} ({cols}x{rows})")
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown(kernel, deck)
