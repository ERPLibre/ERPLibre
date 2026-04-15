#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Reversi/Othello for Elgato Stream Deck (1P vs AI or 2P).

Place pieces to flip opponent's. Most pieces at end wins.
Uses the full grid as the board.
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

COLOR_EMPTY = (0, 80, 40)
COLOR_P1 = (20, 20, 20)
COLOR_P2 = (240, 240, 240)
COLOR_VALID = (0, 120, 60)
COLOR_TITLE = (0, 80, 160)
COLOR_WIN = (0, 200, 60)
COLOR_LOSE = (200, 0, 0)
COLOR_SCORE = (40, 40, 80)
DIRS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 18 if len(text) <= 3 else 12
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


class Reversi:
    def __init__(self, decks):
        self.decks = decks
        self.num_players = len(decks)
        rows, cols = decks[0].key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.board = {}
        self.current = 1
        self.game_active = False
        self.game_over = False
        self.scores = [0, 0]

    def reset(self):
        self.board = {}
        mc, mr = self.cols // 2, self.rows // 2
        if mc > 0 and mr > 0:
            self.board[(mc - 1, mr - 1)] = 1
            self.board[(mc, mr)] = 1
            self.board[(mc - 1, mr)] = 2
            self.board[(mc, mr - 1)] = 2
        self.current = 1
        self.game_over = False
        self.game_active = True

    def _get_flips(self, col, row, player):
        if (col, row) in self.board:
            return []
        opp = 3 - player
        all_flips = []
        for dc, dr in DIRS:
            flips = []
            c, r = col + dc, row + dr
            while 0 <= c < self.cols and 0 <= r < self.rows and self.board.get((c, r)) == opp:
                flips.append((c, r))
                c += dc
                r += dr
            if flips and 0 <= c < self.cols and 0 <= r < self.rows and self.board.get((c, r)) == player:
                all_flips.extend(flips)
        return all_flips

    def _valid_moves(self, player):
        moves = []
        for r in range(self.rows):
            for c in range(self.cols):
                if self._get_flips(c, r, player):
                    moves.append((c, r))
        return moves

    def handle_key(self, key, deck_index=0):
        if self.game_over or not self.game_active:
            self.reset()
            self.render_all()
            return

        if self.num_players == 2:
            expected = 0 if self.current == 1 else 1
            if deck_index != expected:
                return

        col = key % self.cols
        row = key // self.cols
        flips = self._get_flips(col, row, self.current)
        if not flips:
            return

        self.board[(col, row)] = self.current
        for fc, fr in flips:
            self.board[(fc, fr)] = self.current

        # Switch turn
        self.current = 3 - self.current
        if not self._valid_moves(self.current):
            self.current = 3 - self.current
            if not self._valid_moves(self.current):
                self.game_over = True
                p1 = sum(1 for v in self.board.values() if v == 1)
                p2 = sum(1 for v in self.board.values() if v == 2)
                if p1 > p2:
                    self.scores[0] += 1
                elif p2 > p1:
                    self.scores[1] += 1

        # AI move in solo
        if not self.game_over and self.num_players == 1 and self.current == 2:
            moves = self._valid_moves(2)
            if moves:
                best = max(moves, key=lambda m: len(self._get_flips(m[0], m[1], 2)))
                self.board[best] = 2
                for fc, fr in self._get_flips(best[0], best[1], 2):
                    self.board[(fc, fr)] = 2
                self.current = 1
                if not self._valid_moves(1):
                    self.current = 2

        self.render_all()

    def render_all(self):
        for i, deck in enumerate(self.decks):
            self._render(deck, i)

    def _render(self, deck, di):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        valid = set(self._valid_moves(self.current)) if self.game_active and not self.game_over else set()

        if not self.game_active:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, key, COLOR_TITLE, "FLIP")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "START")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            return

        p1_count = sum(1 for v in self.board.values() if v == 1)
        p2_count = sum(1 for v in self.board.values() if v == 2)

        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            pos = (c, r)

            if self.game_over and (c, r) == (mid_c, last_r):
                set_key(deck, key, COLOR_TITLE, "AGAIN")
            elif self.game_over and (c, r) == (mid_c, 0):
                if p1_count > p2_count:
                    won = di == 0 or self.num_players == 1
                else:
                    won = di == 1
                set_key(deck, key, COLOR_WIN if won else COLOR_LOSE, f"{p1_count}-{p2_count}")
            elif pos in self.board:
                set_key(deck, key, COLOR_P1 if self.board[pos] == 1 else COLOR_P2, "")
            elif pos in valid:
                set_key(deck, key, COLOR_VALID, "")
            else:
                set_key(deck, key, COLOR_EMPTY, "")


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
        print("2-PLAYER Reversi! Black vs White. Most pieces wins!")
    else:
        print(f"Reversi vs AI on {decks[0].deck_type()}")
    print("Place to flip opponent's pieces!")
    game = Reversi(decks)
    game.render_all()
    for i, deck in enumerate(decks):
        def make_cb(idx):
            def cb(d, k, s):
                if not s:
                    return
                with game.lock:
                    game.handle_key(k, idx)
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


if __name__ == "__main__":
    main()
