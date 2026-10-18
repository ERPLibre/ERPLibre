#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""ERPLibre Stream Deck — the deck program of ERPLibre Home.

Run as a directory: python script/stream_deck/erplibre_streamdeck. It is
the erplibre-home-streamdeck user service (DECK_PROGRAM=tiler) and
`make streamdeck_erplibre`. --list-plugins prints what the loader finds,
without opening the deck or taking its lock.

Python puts this directory first on sys.path; it is replaced by its
parent, script/stream_deck/, where the package, deck_lock and
translator live."""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [
    p for p in sys.path if os.path.abspath(p or os.curdir) != _HERE
]
sys.path.insert(0, os.path.dirname(_HERE))

import deck_lock  # noqa: E402

from erplibre_streamdeck import app, loader  # noqa: E402


def main():
    deck_lock.acquire_or_exit("tiler")
    deck_lock.exit_on_sigterm()
    app.main()


def list_plugins():
    _, report = loader.load(off=app.read_deck_settings()["plugins_off"])
    for line in report.lines():
        print(line)
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--list-plugins"]:
        sys.exit(list_plugins())
    main()
