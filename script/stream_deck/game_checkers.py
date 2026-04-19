#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Checkers (simplified) — 1P vs AI or 2P.

Simplified checkers on the full grid. Press a piece to select it, then
press destination to move. Diagonal moves only. Jump to capture.
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

COLOR_DARK = (60, 40, 20)
COLOR_LIGHT = (180, 150, 100)
COLOR_P1 = (220, 40, 40)
COLOR_P2 = (40, 40, 220)
COLOR_SELECT = (255, 255, 0)
COLOR_VALID = (0, 180, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_WIN = (0, 200, 60)
COLOR_LOSE = (200, 0, 0)


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 22 if len(text) <= 1 else 14
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


class Checkers:
    def __init__(self, decks):
        self.decks = decks
        self.num_players = len(decks)
        rows, cols = decks[0].key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.board = {}
        self.current = 1
        self.selected = None
        self._chain_active = False
        self.game_active = False
        self.game_over = False
        self.winner = 0

    def reset(self):
        self.board = {}
        # Place pieces on dark squares
        for r in range(self.rows):
            for c in range(self.cols):
                if (c + r) % 2 == 1:
                    if r == 0:
                        self.board[(c, r)] = 2
                    elif r == self.rows - 1:
                        self.board[(c, r)] = 1
        self.current = 1
        self.selected = None
        self._chain_active = False
        self.game_over = False
        self.winner = 0
        self.game_active = True

    def _get_moves(self, c, r):
        player = self.board.get((c, r), 0)
        if player == 0:
            return []
        moves = []
        fwd = [(-1, -1), (1, -1)] if player == 1 else [(-1, 1), (1, 1)]
        bwd = [(-1, 1), (1, 1)] if player == 1 else [(-1, -1), (1, -1)]
        # Forward: move or capture
        for dc, dr in fwd:
            nc, nr = c + dc, r + dr
            if 0 <= nc < self.cols and 0 <= nr < self.rows:
                if (nc, nr) not in self.board:
                    moves.append((nc, nr, None))
                elif self.board.get((nc, nr)) == 3 - player:
                    jc, jr = nc + dc, nr + dr
                    if 0 <= jc < self.cols and 0 <= jr < self.rows and (jc, jr) not in self.board:
                        moves.append((jc, jr, (nc, nr)))
        # Backward: capture only (no simple move)
        for dc, dr in bwd:
            nc, nr = c + dc, r + dr
            if 0 <= nc < self.cols and 0 <= nr < self.rows:
                if self.board.get((nc, nr)) == 3 - player:
                    jc, jr = nc + dc, nr + dr
                    if 0 <= jc < self.cols and 0 <= jr < self.rows and (jc, jr) not in self.board:
                        moves.append((jc, jr, (nc, nr)))
        return moves

    def _get_captures(self, c, r):
        """Get only capture moves from position (for chain jumps)."""
        player = self.board.get((c, r), 0)
        if player == 0:
            return []
        caps = []
        all_dirs = [(-1, -1), (1, -1), (-1, 1), (1, 1)]
        for dc, dr in all_dirs:
            nc, nr = c + dc, r + dr
            if 0 <= nc < self.cols and 0 <= nr < self.rows:
                if self.board.get((nc, nr)) == 3 - player:
                    jc, jr = nc + dc, nr + dr
                    if (0 <= jc < self.cols and 0 <= jr < self.rows
                            and (jc, jr) not in self.board):
                        caps.append((jc, jr, (nc, nr)))
        return caps

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

        if self.selected is None:
            if self.board.get((col, row)) == self.current:
                if self._get_moves(col, row):
                    self.selected = (col, row)
        else:
            # During a chain, only captures are allowed
            if self._chain_active:
                moves = self._get_captures(*self.selected)
            else:
                moves = self._get_moves(*self.selected)
            target = next(
                (m for m in moves if m[0] == col and m[1] == row), None
            )
            if target:
                tc, tr, captured = target
                self.board[(tc, tr)] = self.current
                del self.board[self.selected]
                if captured:
                    del self.board[captured]
                # Check chain capture
                if captured and self._get_captures(tc, tr):
                    self.selected = (tc, tr)
                    self._chain_active = True
                else:
                    self.selected = None
                    self._chain_active = False
                    self._end_turn()
            elif not self._chain_active and self.board.get((col, row)) == self.current:
                self.selected = (col, row) if self._get_moves(col, row) else None
            elif not self._chain_active:
                self.selected = None

        self.render_all()

    def _has_moves(self, player):
        """Check if a player has any legal move."""
        for (c, r), v in self.board.items():
            if v == player and self._get_moves(c, r):
                return True
        return False

    def _end_turn(self):
        """Check win/stalemate and switch player."""
        p1 = any(v == 1 for v in self.board.values())
        p2 = any(v == 2 for v in self.board.values())
        if not p2:
            self.winner = 1
            self.game_over = True
        elif not p1:
            self.winner = 2
            self.game_over = True
        else:
            self.current = 3 - self.current
            # No moves = lose
            if not self._has_moves(self.current):
                self.winner = 3 - self.current
                self.game_over = True
                return
            if not self.game_over and self.num_players == 1 and self.current == 2:
                self._ai_move()

    def _ai_move(self):
        pieces = [(c, r) for (c, r), v in self.board.items() if v == 2]
        random.shuffle(pieces)
        # Prefer captures
        best = None
        for c, r in pieces:
            caps = self._get_captures(c, r)
            if caps:
                best = (c, r, random.choice(caps))
                break
        if best is None:
            for c, r in pieces:
                moves = self._get_moves(c, r)
                if moves:
                    best = (c, r, random.choice(moves))
                    break
        if best:
            c, r, m = best
            self.board[(m[0], m[1])] = 2
            del self.board[(c, r)]
            if m[2]:
                del self.board[m[2]]
            # Chain captures
            pos = (m[0], m[1])
            while m[2]:
                caps = self._get_captures(*pos)
                if not caps:
                    break
                m = random.choice(caps)
                self.board[(m[0], m[1])] = 2
                del self.board[pos]
                if m[2]:
                    del self.board[m[2]]
                pos = (m[0], m[1])
        p1 = any(v == 1 for v in self.board.values())
        if not p1:
            self.winner = 2
            self.game_over = True
        else:
            self.current = 1

    def render_all(self):
        for i, deck in enumerate(self.decks):
            self._render(deck, i)

    def _render(self, deck, di):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        valid_targets = set()
        if self.selected:
            for m in self._get_moves(*self.selected):
                valid_targets.add((m[0], m[1]))

        if not self.game_active:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, key, COLOR_TITLE, "CHECK")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "START")
                else:
                    set_key(deck, key, COLOR_DARK if (c + r) % 2 == 1 else COLOR_LIGHT, "")
            return

        if self.game_over:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    i_won = (self.winner == 1 and di == 0) or (self.winner == 2 and di == 1)
                    if self.num_players == 1:
                        i_won = self.winner == 1
                    set_key(deck, key, COLOR_WIN if i_won else COLOR_LOSE, "WIN!" if i_won else "LOSE")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(deck, key, (20, 20, 30), "")
            return

        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            pos = (c, r)
            bg = COLOR_DARK if (c + r) % 2 == 1 else COLOR_LIGHT

            if pos == self.selected:
                set_key(deck, key, COLOR_SELECT, "O")
            elif pos in valid_targets:
                set_key(deck, key, COLOR_VALID, "")
            elif pos in self.board:
                color = COLOR_P1 if self.board[pos] == 1 else COLOR_P2
                set_key(deck, key, color, "O")
            else:
                set_key(deck, key, bg, "")


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
        print("2-PLAYER Checkers! Red vs Blue.")
    else:
        print(f"Checkers vs AI on {decks[0].deck_type()}")
    print("Select piece, then press destination. Diagonal only!")
    game = Checkers(decks)
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
