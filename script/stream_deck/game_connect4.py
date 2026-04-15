#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Connect 4 for Elgato Stream Deck (1P vs AI or 2P with two decks).

Press top row to drop piece in that column. Get 4 in a row to win!
Rotated: columns = rows of deck.
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

COLOR_EMPTY = (0, 0, 80)
COLOR_P1 = (220, 40, 40)
COLOR_P2 = (220, 220, 0)
COLOR_WIN = (0, 200, 60)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_BOARD = (0, 0, 50)


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 22 if len(text) <= 2 else 14
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


class Connect4:
    def __init__(self, decks):
        self.decks = decks
        self.num_players = len(decks)
        rows, cols = decks[0].key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.board = [[0] * self.rows for _ in range(self.cols)]
        self.current = 1
        self.game_active = False
        self.game_over = False
        self.winner = 0
        self.win_cells = []
        self.scores = [0, 0]

    def reset(self):
        self.board = [[0] * self.rows for _ in range(self.cols)]
        self.current = 1
        self.game_over = False
        self.winner = 0
        self.win_cells = []
        self.game_active = True

    def _drop(self, col):
        for r in range(self.rows - 1, -1, -1):
            if self.board[col][r] == 0:
                self.board[col][r] = self.current
                return (col, r)
        return None

    def _check_win(self):
        for c in range(self.cols):
            for r in range(self.rows):
                if self.board[c][r] == 0:
                    continue
                p = self.board[c][r]
                for dc, dr in [(1, 0), (0, 1), (1, 1), (1, -1)]:
                    cells = [(c, r)]
                    for i in range(1, 4):
                        nc, nr = c + dc * i, r + dr * i
                        if 0 <= nc < self.cols and 0 <= nr < self.rows and self.board[nc][nr] == p:
                            cells.append((nc, nr))
                        else:
                            break
                    if len(cells) == 4:
                        self.winner = p
                        self.win_cells = cells
                        self.game_over = True
                        self.scores[p - 1] += 1
                        return
        if all(self.board[c][0] != 0 for c in range(self.cols)):
            self.game_over = True

    def _ai_move(self):
        # Simple AI: check for winning move, then block, then random
        for col in range(self.cols):
            for r in range(self.rows - 1, -1, -1):
                if self.board[col][r] == 0:
                    self.board[col][r] = 2
                    self._check_win()
                    if self.winner == 2:
                        self.board[col][r] = 0
                        self.winner = 0
                        self.game_over = False
                        self.win_cells = []
                        return col
                    self.board[col][r] = 0
                    self.winner = 0
                    self.game_over = False
                    self.win_cells = []
                    break
        for col in range(self.cols):
            for r in range(self.rows - 1, -1, -1):
                if self.board[col][r] == 0:
                    self.board[col][r] = 1
                    self._check_win()
                    if self.winner == 1:
                        self.board[col][r] = 0
                        self.winner = 0
                        self.game_over = False
                        self.win_cells = []
                        return col
                    self.board[col][r] = 0
                    self.winner = 0
                    self.game_over = False
                    self.win_cells = []
                    break
        avail = [c for c in range(self.cols) if self.board[c][0] == 0]
        return random.choice(avail) if avail else 0

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
        result = self._drop(col)
        if result is None:
            return

        self._check_win()
        if not self.game_over:
            self.current = 3 - self.current
            if self.num_players == 1 and self.current == 2:
                ai_col = self._ai_move()
                self._drop(ai_col)
                self._check_win()
                if not self.game_over:
                    self.current = 1

        self.render_all()

    def render_all(self):
        for i, deck in enumerate(self.decks):
            self._render(deck, i)

    def _render(self, deck, deck_index):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, key, COLOR_TITLE, "C4")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "START")
                elif self.num_players == 2 and (c, r) == (0, 0):
                    set_key(deck, key, COLOR_P1 if deck_index == 0 else COLOR_P2, f"P{deck_index + 1}")
                else:
                    set_key(deck, key, COLOR_BOARD, "")
            return

        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            val = self.board[c][r]

            if self.game_over and (c, r) in self.win_cells:
                set_key(deck, key, COLOR_WIN, "")
            elif val == 1:
                set_key(deck, key, COLOR_P1, "")
            elif val == 2:
                set_key(deck, key, COLOR_P2, "")
            elif self.game_over and (c, r) == (mid_c, last_r):
                set_key(deck, key, COLOR_TITLE, "AGAIN")
            else:
                set_key(deck, key, COLOR_BOARD, "")


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
        print("2-PLAYER Connect 4! Red vs Yellow.")
    else:
        print(f"Connect 4 vs AI on {decks[0].deck_type()}")
    print("Press any column to drop your piece!")
    game = Connect4(decks)
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
        print(f"\nScores: P1={game.scores[0]} P2={game.scores[1]}")


if __name__ == "__main__":
    main()
