# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Command line shared by the Stream Deck games.

A game builds its parser here and parses sys.argv before its PIL and
Stream Deck imports: -h and --help print the usage and exit 0, an unknown
argument prints it on stderr and exits 2, and neither imports the Stream
Deck library nor opens the deck. --meta is only accepted here; the game
answers it itself once GAME_META is defined, with that JSON on stdout,
which is what the gallery reads. Only the standard library is imported.

The name does not match game_*.py: the gallery and the TODO menu list
every game_*.py file as a game."""

import argparse

EPILOG = """\
Without an option, the game opens the Stream Deck and plays. The gallery
and the TODO menu run it after handing the deck over from the ERPLibre
Home service, and give it back when the game ends."""


def parser(doc):
    """The parser of a game described by `doc`, its module docstring: -h,
    --help and --meta. A game with options of its own adds them to it."""
    p = argparse.ArgumentParser(
        description=doc,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    p.add_argument(
        "--meta",
        action="store_true",
        help="print the game's gallery metadata as JSON and exit",
    )
    return p
