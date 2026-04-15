#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Color Match (Memory) for Elgato Stream Deck (1P or 2P race).

1 deck: flip two cards, find pairs.
2 decks: same board, each player flips on their own deck. First to
find all pairs wins! Cards matched by either player disappear for both.
"""

import os
import random
import sys
import threading
import time

try:
    from PIL import Image, ImageDraw, ImageFont
    from StreamDeck.DeviceManager import DeviceManager
    from StreamDeck.ImageHelpers import PILHelper
    from StreamDeck.Transport.Transport import TransportError
except ImportError as e:
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

CARD_COLORS = [
    (220, 40, 40), (0, 180, 0), (0, 80, 220), (220, 180, 0),
    (180, 0, 180), (0, 180, 180), (220, 100, 0), (100, 220, 0),
    (255, 100, 100), (100, 255, 100), (100, 100, 255), (255, 200, 0),
    (200, 0, 100), (0, 200, 100), (100, 0, 200), (200, 100, 0),
]
COLOR_HIDDEN = (50, 50, 65)
COLOR_EMPTY = (20, 20, 30)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)
COLOR_LOSE = (200, 0, 0)


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 22 if len(text) <= 3 else 14
        try:
            font = ImageFont.load_default(size=fs)
        except TypeError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((w - tw) // 2 + 1, (h - th) // 2 + 1), text, fill=(0, 0, 0), font=font)
        draw.text(((w - tw) // 2, (h - th) // 2), text, fill=(255, 255, 255), font=font)
    native = PILHelper.to_native_key_format(deck, img)
    try:
        with deck:
            deck.set_key_image(key, native)
    except TransportError:
        pass


class ColorMatch:
    def __init__(self, decks):
        self.decks = decks
        self.num_players = len(decks)
        rows, cols = decks[0].key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.num_pairs = self.total_keys // 2
        self.lock = threading.Lock()
        self.cards = []
        self.matched = set()
        self.scores = [0, 0]
        # Per-player flip state
        self.first = [None, None]
        self.second = [None, None]
        self._showing = [False, False]
        self.game_active = False
        self.won = False
        self.winner = -1

    def reset(self):
        colors = list(range(self.num_pairs)) * 2
        random.shuffle(colors)
        self.cards = colors[:self.total_keys]
        if self.total_keys % 2 == 1:
            self.cards.append(-1)
            self.matched = {self.total_keys - 1}
        else:
            self.matched = set()
        self.scores = [0, 0]
        self.first = [None, None]
        self.second = [None, None]
        self._showing = [False, False]
        self.won = False
        self.winner = -1
        self.game_active = True

    def handle_key(self, key, deck_index=0):
        if self.won or not self.game_active:
            self.reset()
            self.render_all()
            return

        p = 0 if self.num_players == 1 else deck_index
        if self._showing[p]:
            return
        if key >= len(self.cards) or key in self.matched:
            return

        if self.first[p] is None:
            self.first[p] = key
            self.render_all()
        elif self.second[p] is None and key != self.first[p]:
            self.second[p] = key
            self.render_all()

            if self.cards[self.first[p]] == self.cards[self.second[p]]:
                self.matched.add(self.first[p])
                self.matched.add(self.second[p])
                self.scores[p] += 1
                self.first[p] = None
                self.second[p] = None
                if len(self.matched) >= len(self.cards):
                    self.won = True
                    if self.num_players == 2:
                        if self.scores[0] > self.scores[1]:
                            self.winner = 0
                        elif self.scores[1] > self.scores[0]:
                            self.winner = 1
                        else:
                            self.winner = -1
                    else:
                        self.winner = 0
                self.render_all()
            else:
                self._showing[p] = True
                threading.Thread(
                    target=self._hide_pair, args=(p,), daemon=True
                ).start()

    def _hide_pair(self, p):
        time.sleep(0.8)
        with self.lock:
            self.first[p] = None
            self.second[p] = None
            self._showing[p] = False
            self.render_all()

    def render_all(self):
        for i, deck in enumerate(self.decks):
            self._render(deck, i)

    def _render(self, deck, deck_index):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        p = 0 if self.num_players == 1 else deck_index

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, key, COLOR_TITLE, "MATCH")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0) and self.num_players == 2:
                    set_key(deck, key, COLOR_SCORE, f"P{deck_index + 1}")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "START")
                else:
                    idx = key % len(CARD_COLORS)
                    rc, g, b = CARD_COLORS[idx]
                    set_key(deck, key, (rc // 4, g // 4, b // 4), "")
            return

        if self.won:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    if self.num_players == 2:
                        if self.winner == deck_index:
                            set_key(deck, key, COLOR_WIN, "WIN!")
                        elif self.winner < 0:
                            set_key(deck, key, COLOR_SCORE, "DRAW")
                        else:
                            set_key(deck, key, COLOR_LOSE, "LOSE")
                    else:
                        set_key(deck, key, COLOR_WIN, "WIN!")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    set_key(deck, key, COLOR_SCORE, f"{self.scores[0]}-{self.scores[1]}" if self.num_players == 2 else f"{self.scores[0]}p")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(deck, key, COLOR_WIN, "")
            return

        my_revealed = set()
        if self.first[p] is not None:
            my_revealed.add(self.first[p])
        if self.second[p] is not None:
            my_revealed.add(self.second[p])

        for key in range(self.total_keys):
            if key >= len(self.cards):
                set_key(deck, key, COLOR_EMPTY, "")
            elif key in self.matched:
                ci = self.cards[key] % len(CARD_COLORS)
                rc, g, b = CARD_COLORS[ci]
                set_key(deck, key, (rc // 3, g // 3, b // 3), "")
            elif key in my_revealed:
                ci = self.cards[key] % len(CARD_COLORS)
                set_key(deck, key, CARD_COLORS[ci], "")
            else:
                set_key(deck, key, COLOR_HIDDEN, "?")


def main():
    streamdecks = DeviceManager().enumerate()
    visual = [d for d in streamdecks if d.is_visual()]
    if not visual:
        print("No visual Stream Deck found.")
        sys.exit(1)

    for d in visual:
        d.open()
        d.reset()
        d.set_brightness(80)

    decks = visual[:2] if len(visual) >= 2 else visual[:1]

    if len(decks) == 2:
        print("2-PLAYER COLOR MATCH! Same board, find pairs. Most pairs wins!")
    else:
        print(f"Color Match on {decks[0].deck_type()}")

    print("Flip two cards, find pairs! Ctrl+C to quit.")

    game = ColorMatch(decks)
    game.render_all()

    for i, deck in enumerate(decks):
        def make_cb(idx):
            def cb(deck, key, state):
                if not state:
                    return
                with game.lock:
                    game.handle_key(key, deck_index=idx)
            return cb
        deck.set_key_callback(make_cb(i))

    try:
        while all(d.is_open() for d in decks):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for d in decks:
            try:
                with d:
                    d.reset()
                    d.close()
            except Exception:
                pass
        print(f"\nScores: P1={game.scores[0]} P2={game.scores[1]}")


if __name__ == "__main__":
    main()
