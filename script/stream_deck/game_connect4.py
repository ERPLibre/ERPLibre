#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Connect 4 — choose AI or 2 players at start.

Supports 2P on same deck or on two decks if both connected.
Press top row to drop piece in that column. Get 4 in a row to win!
"""

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

GAME_META = {
    "name": "Connect 4",
    "category": "strategy",
    "multiplayer": True,
    "sdplus": False,
    "description": "Drop pieces, get 4 in a row! 1P vs AI or 2P.",
    "icon": "c4"
}

COLOR_EMPTY = (0, 0, 80)
COLOR_P1 = (220, 40, 40)
COLOR_P2 = (220, 220, 0)
COLOR_WIN = (0, 200, 60)
COLOR_TITLE = (0, 80, 160)
COLOR_BOARD = (0, 0, 50)
COLOR_AI = (80, 180, 255)
COLOR_2P = (180, 120, 255)
COLOR_2P_DUAL = (120, 255, 180)
COLOR_DIM = (30, 30, 50)


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 22 if len(text) <= 2 else 14 if len(text) <= 5 else 11
        try:
            font = ImageFont.load_default(size=fs)
        except TypeError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            ((w - tw) // 2 + 1, (h - th) // 2 + 1),
            text, fill=(0, 0, 0), font=font,
        )
        draw.text(
            ((w - tw) // 2, (h - th) // 2),
            text, fill=(255, 255, 255), font=font,
        )
    native = PILHelper.to_native_key_format(deck, img)
    try:
        with deck:
            deck.set_key_image(key, native)
    except TransportError:
        pass


# Game modes
MODE_AI = "ai"
MODE_2P_SAME = "2p_same"
MODE_2P_DUAL = "2p_dual"


class Connect4:
    def __init__(self, all_decks):
        self.all_decks = all_decks
        self.deck1 = all_decks[0]
        self.deck2 = all_decks[1] if len(all_decks) >= 2 else None
        rows, cols = self.deck1.key_layout()
        self.cols = cols
        self.rows = rows
        self.lock = threading.Lock()
        self.running = True
        # Menu state
        self.in_menu = True
        self.mode = None
        # Menu button positions
        mid_c = self.cols // 2
        mid_r = self.rows // 2
        self.btn_ai = (mid_c, mid_r - 1)
        self.btn_2p = (mid_c, mid_r)
        self.btn_2p_dual = (mid_c, mid_r + 1)
        # Game state
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
                        if (0 <= nc < self.cols and 0 <= nr < self.rows
                                and self.board[nc][nr] == p):
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
        # Check for winning move, then block, then center-biased random
        for player in [2, 1]:
            for col in range(self.cols):
                for r in range(self.rows - 1, -1, -1):
                    if self.board[col][r] == 0:
                        self.board[col][r] = player
                        self._check_win()
                        won = self.winner == player
                        self.board[col][r] = 0
                        self.winner = 0
                        self.game_over = False
                        self.win_cells = []
                        if won:
                            return col
                        break
        avail = [c for c in range(self.cols) if self.board[c][0] == 0]
        if not avail:
            return 0
        # Prefer center columns
        center = self.cols // 2
        avail.sort(key=lambda c: abs(c - center))
        # Pick from top 3 center-most with randomness
        top = avail[:max(1, len(avail) // 2)]
        return random.choice(top)

    # ── MENU ──────────────────────────────────────

    def render_menu(self):
        """Show mode selection on deck 1 (and waiting screen on deck 2)."""
        for key in range(self.cols * self.rows):
            c = key % self.cols
            r = key // self.cols
            if (c, r) == (self.cols // 2, 0):
                set_key(self.deck1, key, COLOR_TITLE, "C4")
            elif (c, r) == self.btn_ai:
                set_key(self.deck1, key, COLOR_AI, "vs AI")
            elif (c, r) == self.btn_2p:
                set_key(self.deck1, key, COLOR_2P, "2P")
            elif (c, r) == self.btn_2p_dual and self.deck2:
                set_key(self.deck1, key, COLOR_2P_DUAL, "2Px2")
            else:
                set_key(self.deck1, key, COLOR_DIM, "")
        if self.deck2:
            for key in range(self.cols * self.rows):
                c = key % self.cols
                r = key // self.cols
                if (c, r) == (self.cols // 2, self.rows // 2):
                    set_key(self.deck2, key, COLOR_TITLE, "C4")
                else:
                    set_key(self.deck2, key, COLOR_DIM, "")

    def handle_menu_key(self, key, deck_index):
        """Handle key press in menu."""
        if deck_index != 0:
            return
        c = key % self.cols
        r = key // self.cols
        if (c, r) == self.btn_ai:
            self.mode = MODE_AI
        elif (c, r) == self.btn_2p:
            self.mode = MODE_2P_SAME
        elif (c, r) == self.btn_2p_dual and self.deck2:
            self.mode = MODE_2P_DUAL
        else:
            return
        self.in_menu = False
        self.reset()
        print(f"Mode: {self.mode}")
        self.render_all()

    # ── GAME ──────────────────────────────────────

    def handle_key(self, key, deck_index=0):
        if self.in_menu:
            self.handle_menu_key(key, deck_index)
            return

        if self.game_over:
            # Any key → back to menu
            self.in_menu = True
            self.game_active = False
            self.render_menu()
            return

        if not self.game_active:
            self.reset()
            self.render_all()
            return

        # Enforce turn order
        if self.mode == MODE_2P_DUAL:
            expected = 0 if self.current == 1 else 1
            if deck_index != expected:
                return
        elif self.mode == MODE_AI:
            if deck_index != 0:
                return

        col = key % self.cols
        result = self._drop(col)
        if result is None:
            return

        self._check_win()
        if not self.game_over:
            self.current = 3 - self.current
            if self.mode == MODE_AI and self.current == 2:
                self.render_all()
                time.sleep(0.3)
                ai_col = self._ai_move()
                self._drop(ai_col)
                self._check_win()
                if not self.game_over:
                    self.current = 1

        self.render_all()

    def render_all(self):
        if self.mode == MODE_2P_DUAL and self.deck2:
            self._render(self.deck1, 0)
            self._render(self.deck2, 1)
        else:
            self._render(self.deck1, 0)
            if self.deck2:
                self._render_mirror(self.deck2)

    def _render(self, deck, deck_index):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if self.game_over:
            self._render_game_over(deck)
            return

        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            val = self.board[c][r]

            if val == 1:
                set_key(deck, key, COLOR_P1, "")
            elif val == 2:
                set_key(deck, key, COLOR_P2, "")
            elif r == 0 and c == mid_c:
                # Turn indicator
                color = COLOR_P1 if self.current == 1 else COLOR_P2
                label = f"P{self.current}"
                if self.mode == MODE_2P_DUAL:
                    is_my_turn = self.current == deck_index + 1
                    label = f"P{deck_index + 1}" if is_my_turn else ""
                    color = color if is_my_turn else COLOR_DIM
                set_key(deck, key, color, label)
            else:
                set_key(deck, key, COLOR_BOARD, "")

    def _render_game_over(self, deck):
        """Render game over screen with winner clearly visible."""
        mid_c = self.cols // 2
        mid_r = self.rows // 2
        w = self.winner
        if w:
            win_color = COLOR_P1 if w == 1 else COLOR_P2
        else:
            win_color = COLOR_TITLE

        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            val = self.board[c][r]

            # Winning 4 cells flash bright
            if (c, r) in self.win_cells:
                set_key(deck, key, COLOR_WIN, "WIN")
            # Winner banner row (middle row)
            elif r == mid_r:
                if c == mid_c - 1:
                    label = f"P{w}" if w else "TIE"
                    set_key(deck, key, win_color, label)
                elif c == mid_c:
                    label = "WIN!" if w else "DRAW"
                    set_key(deck, key, win_color, label)
                elif c == mid_c + 1:
                    set_key(
                        deck, key, COLOR_TITLE,
                        f"{self.scores[0]}-{self.scores[1]}",
                    )
                else:
                    # Dim the pieces
                    if val == 1:
                        set_key(deck, key, (80, 15, 15), "")
                    elif val == 2:
                        set_key(deck, key, (80, 80, 0), "")
                    else:
                        set_key(deck, key, COLOR_DIM, "")
            else:
                # Dim existing pieces, dark board
                if val == 1:
                    set_key(deck, key, (80, 15, 15), "")
                elif val == 2:
                    set_key(deck, key, (80, 80, 0), "")
                else:
                    set_key(deck, key, COLOR_DIM, "")

    def _render_mirror(self, deck):
        """Render board on deck2 as spectator (same view)."""
        if self.game_over:
            self._render_game_over(deck)
            return
        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            val = self.board[c][r]
            if val == 1:
                set_key(deck, key, COLOR_P1, "")
            elif val == 2:
                set_key(deck, key, COLOR_P2, "")
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

    all_decks = visual[:2] if len(visual) >= 2 else visual[:1]
    n = len(all_decks)
    print(f"Connect 4 — {n} deck(s) detected")
    print("Choose mode on Stream Deck buttons!")

    game = Connect4(all_decks)
    game.render_menu()

    for i, deck in enumerate(all_decks):
        def make_cb(idx):
            def cb(d, k, s):
                if not s:
                    return
                with game.lock:
                    game.handle_key(k, idx)
            return cb
        deck.set_key_callback(make_cb(i))

    try:
        while game.running and all(d.is_open() for d in all_decks):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for d in all_decks:
            try:
                with d:
                    d.reset()
                    d.close()
            except Exception:
                pass
        print(f"\nScores: P1={game.scores[0]} P2={game.scores[1]}")



if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
