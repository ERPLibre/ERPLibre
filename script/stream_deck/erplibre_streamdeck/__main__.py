#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""ERPLibre Stream Deck — the deck program of ERPLibre Home.

Run as a directory: python script/stream_deck/erplibre_streamdeck. It is
the erplibre-home-streamdeck user service (DECK_PROGRAM=tiler) and
`make streamdeck_erplibre`. --list-plugins prints what the loader finds,
and --catalog what a keymap.json layout may name, as JSON (see
keymap.catalog); neither opens the deck nor takes its lock. -h and --help
print the usage and exit 0; any other argument prints it on stderr and
exits 2. Neither takes the lock nor imports app, which imports the Stream
Deck library.

Python puts this directory first on sys.path; it is replaced by its
parent, script/stream_deck/, where the package, deck_lock and
translator live."""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [
    p for p in sys.path if os.path.abspath(p or os.curdir) != _HERE
]
sys.path.insert(0, os.path.dirname(_HERE))

import deck_lock  # noqa: E402

EPILOG = """\
Settings: $XDG_CONFIG_HOME/erplibre-home/streamdeck.conf (default
~/.config/erplibre-home/streamdeck.conf), read through
script/install/erplibre_home_settings.sh: DECK_PLUGINS_OFF,
DECK_SESSION_REFRESH_SEC.

Home keys: ~/.config/erplibre-home/keymap.json, written by the GNOME
extension: the home layout of each deck model, read at start. Without
it, or for a model it does not name, the automatic layout.

Exit codes:
  0    the program ended, or --help / --list-plugins / --catalog
  1    an unexpected error, its traceback on stderr
  %(busy)d    another program holds the deck lock, or a bad option
  %(no_deck)d    no Stream Deck with a screen is plugged in
  143  stopped by SIGTERM, after the deck is reset
The service does not restart on %(busy)d or %(no_deck)d.
""" % {
    "busy": deck_lock.BUSY_EXIT,
    "no_deck": deck_lock.NO_DECK_EXIT,
}


def parser():
    """The command line; argparse exits 0 on -h and 2 on any other
    argument it does not know, before main() or list_plugins() runs."""
    p = argparse.ArgumentParser(
        prog="python script/stream_deck/erplibre_streamdeck",
        description=(
            "ERPLibre Stream Deck, the deck program of ERPLibre Home.\n"
            "Without an option, it takes the deck lock and runs the deck."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    only = p.add_mutually_exclusive_group()
    only.add_argument(
        "--list-plugins",
        action="store_true",
        help=(
            "print what the plugin loader finds, without opening the"
            " deck or taking its lock"
        ),
    )
    only.add_argument(
        "--catalog",
        action="store_true",
        help=(
            "print as JSON the actions, icons and deck models a"
            " keymap.json layout may name, without opening the deck or"
            " taking its lock"
        ),
    )
    return p


def main():
    deck_lock.acquire_or_exit("tiler")
    deck_lock.exit_on_sigterm()
    from erplibre_streamdeck import app

    app.main()


def list_plugins():
    from erplibre_streamdeck import app, loader

    _, report = loader.load(off=app.read_deck_settings()["plugins_off"])
    for line in report.lines():
        print(line)
    return 0


def catalog():
    """Every plugin present, off ones included: a layout may name a
    plugin this workstation turns off, and the deck leaves its key
    empty. A plugin printing at import goes to stderr, not into the
    JSON."""
    import contextlib
    import json

    from erplibre_streamdeck import keymap, loader

    with contextlib.redirect_stdout(sys.stderr):
        plugins, _ = loader.load()
        data = keymap.catalog(plugins)
    print(json.dumps(data, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    args = parser().parse_args()
    if args.list_plugins:
        sys.exit(list_plugins())
    if args.catalog:
        sys.exit(catalog())
    main()
