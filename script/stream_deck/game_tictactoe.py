#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Tic-Tac-Toe.

Single deck: 2 players alternate turns on same deck.
Multi deck: each player has their own deck, plays are mirrored.

Grid uses center 3x3 of the deck. Remaining keys show status.
"""

import os
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

COLOR_EMPTY = (20, 20, 25)
COLOR_BOARD = (60, 70, 90)
COLOR_X = (220, 50, 50)
COLOR_O = (50, 100, 220)
COLOR_X_WIN = (255, 80, 80)
COLOR_O_WIN = (80, 130, 255)
COLOR_DRAW = (120, 120, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_TURN_X = (160, 30, 30)
COLOR_TURN_O = (30, 60, 160)
COLOR_INACTIVE = (30, 30, 30)

WINNING_LINES = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),  # rows
    (0, 3, 6), (1, 4, 7), (2, 5, 8),  # cols
    (0, 4, 8), (2, 4, 6),             # diags
]


class TicTacToe:
    def __init__(self, decks):
        """decks: list of 1 or 2 Stream Deck devices."""
        self.decks = decks
        self.num_players = len(decks)
        self.lock = threading.Lock()

        # Use first deck for layout reference
        rows, cols = decks[0].key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows

        # 3x3 grid offset (centered on deck)
        self.grid_offset_c = (cols - 3) // 2
        self.grid_offset_r = (rows - 3) // 2

        # Game state
        self.board = [" "] * 9  # " ", "X", "O"
        self.current_player = "X"  # X goes first
        self.game_active = False
        self.winner = None  # "X", "O", "draw", None
        self.winning_cells = []
        self.score_x = 0
        self.score_o = 0

    def _grid_to_board(self, col, row):
        """Convert deck (col, row) to board index 0-8, or -1."""
        gc = col - self.grid_offset_c
        gr = row - self.grid_offset_r
        if 0 <= gc < 3 and 0 <= gr < 3:
            return gr * 3 + gc
        return -1

    def _board_to_grid(self, idx):
        """Convert board index 0-8 to deck (col, row)."""
        gc = idx % 3
        gr = idx // 3
        return gc + self.grid_offset_c, gr + self.grid_offset_r

    def reset(self):
        self.board = [" "] * 9
        self.current_player = "X"
        self.winner = None
        self.winning_cells = []
        self.game_active = True

    def _check_winner(self):
        for a, b, c in WINNING_LINES:
            if self.board[a] == self.board[b] == self.board[c] != " ":
                self.winner = self.board[a]
                self.winning_cells = [a, b, c]
                if self.winner == "X":
                    self.score_x += 1
                else:
                    self.score_o += 1
                return
        if " " not in self.board:
            self.winner = "draw"

    def handle_key(self, key, deck_index=0):
        """Handle key press from a specific deck."""
        if self.winner is not None or not self.game_active:
            self.reset()
            self.render_all()
            return

        # In multi-deck mode, only the current player's deck accepts input
        if self.num_players == 2:
            expected_deck = 0 if self.current_player == "X" else 1
            if deck_index != expected_deck:
                return

        col = key % self.cols
        row = key // self.cols
        board_idx = self._grid_to_board(col, row)

        if board_idx < 0 or self.board[board_idx] != " ":
            return

        self.board[board_idx] = self.current_player
        self._check_winner()

        if self.winner is None:
            self.current_player = "O" if self.current_player == "X" else "X"

        self.render_all()

    def render_all(self):
        """Render to all decks."""
        for i, deck in enumerate(self.decks):
            self._render_deck(deck, i)

    def _render_deck(self, deck, deck_index):
        """Render game state on a specific deck."""
        is_my_turn = True
        my_symbol = None

        if self.num_players == 2:
            my_symbol = "X" if deck_index == 0 else "O"
            is_my_turn = self.current_player == my_symbol

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols
            board_idx = self._grid_to_board(c, r)

            if not self.game_active:
                self._render_title(deck, key, c, r, deck_index)
                continue

            if board_idx >= 0:
                self._render_cell(deck, key, board_idx, is_my_turn)
            else:
                self._render_status(
                    deck, key, c, r, deck_index, is_my_turn
                )

    def _render_title(self, deck, key, c, r, deck_index):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if (c, r) == (mid_c, 0):
            self._set_key(deck, key, COLOR_TITLE, "TIC")
        elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
            if self.num_players == 2:
                label = "X" if deck_index == 0 else "O"
                color = COLOR_X if deck_index == 0 else COLOR_O
                self._set_key(deck, key, color, f"P:{label}")
            else:
                self._set_key(deck, key, COLOR_TITLE, "TAC")
        elif (c, r) == (mid_c, last_r):
            self._set_key(deck, key, COLOR_TITLE, "START")
        elif (c, r) == (0, 0):
            self._set_key(
                deck, key, COLOR_X,
                f"X:{self.score_x}" if self.score_x else ""
            )
        elif (c, r) == (self.cols - 1, 0):
            self._set_key(
                deck, key, COLOR_O,
                f"O:{self.score_o}" if self.score_o else ""
            )
        else:
            self._set_key(deck, key, COLOR_EMPTY, "")

    def _render_cell(self, deck, key, board_idx, is_my_turn):
        val = self.board[board_idx]

        if self.winner == "draw":
            color = COLOR_DRAW
            text = val if val != " " else ""
        elif self.winner and board_idx in self.winning_cells:
            color = COLOR_X_WIN if self.winner == "X" else COLOR_O_WIN
            text = val
        elif self.winner:
            color = COLOR_BOARD
            text = val if val != " " else ""
        elif val == "X":
            color = COLOR_X
            text = "X"
        elif val == "O":
            color = COLOR_O
            text = "O"
        else:
            # Empty cell — dim if not your turn (multi-deck)
            if self.num_players == 2 and not is_my_turn:
                color = COLOR_INACTIVE
            else:
                color = COLOR_BOARD
            text = ""

        self._set_key(deck, key, color, text)

    def _render_status(self, deck, key, c, r, deck_index, is_my_turn):
        last_r = self.rows - 1

        if self.winner:
            if c == 0 and r == 0:
                if self.winner == "draw":
                    self._set_key(deck, key, COLOR_DRAW, "DRAW")
                else:
                    color = COLOR_X_WIN if self.winner == "X" else COLOR_O_WIN
                    self._set_key(deck, key, color, f"{self.winner}!")
            elif c == self.cols - 1 and r == last_r:
                self._set_key(deck, key, COLOR_TITLE, "AGAIN")
            elif c == 0 and r == last_r:
                self._set_key(
                    deck, key, COLOR_SCORE,
                    f"{self.score_x}-{self.score_o}"
                )
            else:
                self._set_key(deck, key, COLOR_EMPTY, "")
        else:
            # Show whose turn
            if c == 0 and r == 0:
                turn_color = (
                    COLOR_TURN_X if self.current_player == "X"
                    else COLOR_TURN_O
                )
                self._set_key(
                    deck, key, turn_color, self.current_player
                )
            elif c == 0 and r == last_r:
                self._set_key(
                    deck, key, COLOR_SCORE,
                    f"{self.score_x}-{self.score_o}"
                )
            elif self.num_players == 2 and c == self.cols - 1 and r == 0:
                if is_my_turn:
                    self._set_key(deck, key, COLOR_TURN_X if deck_index == 0 else COLOR_TURN_O, "YOU")
                else:
                    self._set_key(deck, key, COLOR_INACTIVE, "WAIT")
            else:
                self._set_key(deck, key, COLOR_EMPTY, "")

    def _set_key(self, deck, key, color, text=""):
        fmt = deck.key_image_format()
        w, h = fmt["size"]
        img = Image.new("RGB", (w, h), color)
        if text:
            draw = ImageDraw.Draw(img)
            font_size = 28 if len(text) <= 1 else (18 if len(text) <= 4 else 12)
            try:
                font = ImageFont.load_default(size=font_size)
            except TypeError:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx, ty = (w - tw) // 2, (h - th) // 2
            draw.text((tx + 1, ty + 1), text, fill=(0, 0, 0), font=font)
            draw.text((tx, ty), text, fill=(255, 255, 255), font=font)
        native = PILHelper.to_native_key_format(deck, img)
        try:
            with deck:
                deck.set_key_image(key, native)
        except TransportError:
            pass


def main():
    streamdecks = DeviceManager().enumerate()
    visual_decks = [d for d in streamdecks if d.is_visual()]

    if not visual_decks:
        print("No visual Stream Deck found.")
        sys.exit(1)

    # Open all visual decks
    for d in visual_decks:
        d.open()
        d.reset()
        d.set_brightness(80)

    if len(visual_decks) >= 2:
        decks = visual_decks[:2]
        print(f"2-PLAYER MODE: {decks[0].deck_type()} vs {decks[1].deck_type()}")
        print(f"Deck 1 = X ({decks[0].get_serial_number()})")
        print(f"Deck 2 = O ({decks[1].get_serial_number()})")
    else:
        decks = visual_decks[:1]
        rows, cols = decks[0].key_layout()
        print(f"1-PLAYER MODE (hot seat) on {decks[0].deck_type()} ({cols}x{rows})")
        print("Players alternate turns on same deck.")

    game = TicTacToe(decks)
    game.render_all()

    # Register callbacks for each deck
    for i, deck in enumerate(decks):
        deck_index = i

        def make_callback(idx):
            def callback(deck, key, state):
                if not state:
                    return
                with game.lock:
                    game.handle_key(key, deck_index=idx)
            return callback

        deck.set_key_callback(make_callback(i))

    print("3x3 grid centered on deck. Ctrl+C to quit.")

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
        print(f"\nScore: X={game.score_x} O={game.score_o}")


if __name__ == "__main__":
    main()
