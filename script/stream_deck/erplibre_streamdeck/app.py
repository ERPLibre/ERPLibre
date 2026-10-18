# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Start of the deck program: find the deck, build the kernel, run.

build() is what a test drives: the style restored from settings.json,
the plugins loaded, the kernel made, without the lock file, the signal
handler or the loop thread."""

import subprocess
import sys
import threading
import time

try:
    from StreamDeck.DeviceManager import DeviceManager
except ImportError as e:
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

import deck_lock

from erplibre_streamdeck import loader, paths, settings
from erplibre_streamdeck.kernel import Kernel
from erplibre_streamdeck.ui import render


def read_plugins_off():
    """DECK_PLUGINS_OFF from streamdeck.conf, read by the settings
    library the installer and the service use; [] when it cannot be
    read (one journal line)."""
    try:
        done = subprocess.run(
            ["bash", "-c", '. "$0" && deck_plugins_off',
             str(paths.SETTINGS_LIB)],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[erplibre-home] DECK_PLUGINS_OFF unreadable: {exc}",
              file=sys.stderr, flush=True)
        return []
    return [line for line in done.stdout.splitlines() if line]


def build(deck, *, plugins_off=(), user_dir=None):
    render.STYLE.restore(settings.load())
    plugins, report = loader.load(off=plugins_off, user_dir=user_dir)
    for pid, status, detail in report.entries:
        if status != "active":
            print(f"[erplibre-home] plugin {pid}: {status}: {detail}",
                  file=sys.stderr, flush=True)
    kernel = Kernel(deck, plugins)
    for pid, reason in kernel.refused:
        print(f"[erplibre-home] plugin {pid}: refused: {reason}",
              file=sys.stderr, flush=True)
    return kernel


def main():
    streamdecks = DeviceManager().enumerate()
    deck = next((d for d in streamdecks if d.is_visual()), None)
    if not deck:
        print("No visual Stream Deck found.")
        sys.exit(deck_lock.NO_DECK_EXIT)
    deck.open()
    deck.reset()
    deck.set_brightness(80)

    rows, cols = deck.key_layout()
    print(f"Window Tiler on {deck.deck_type()} ({cols}x{rows})")

    kernel = build(deck, plugins_off=read_plugins_off())
    if kernel.dbus_ok:
        print("D-Bus tiler extension detected!")
    else:
        print("WARNING: erplibre-home extension not found.",
              file=sys.stderr, flush=True)
        print("Install: re-login to GNOME to activate the extension.")
    print("Press TILE to enter tiling mode (first corner, second corner).")
    print("Press TIMER to list and toggle tracker timers.")

    kernel.guard("kernel", "first render", kernel.render)
    deck.set_key_callback(kernel.on_key)
    threading.Thread(target=kernel.loop, daemon=True).start()
    try:
        while deck.is_open():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        kernel.running = False
        with kernel.lock:
            kernel.shutdown()
        with deck:
            deck.reset()
            deck.close()
