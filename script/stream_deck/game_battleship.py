#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Battleship — 1P solo or 2P.

1 deck: solo vs hidden ships.
2 decks: each player's deck shows their attack grid. Ships are placed
automatically. Players alternate turns. Game starts as soon as both
decks are connected.
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

COLOR_WATER = (0, 40, 80)
COLOR_SHIP = (0, 80, 60)
COLOR_HIT = (220, 40, 40)
COLOR_MISS = (50, 50, 70)
COLOR_SUNK = (160, 0, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)
COLOR_LOSE = (180, 0, 0)
COLOR_YOUR_TURN = (0, 120, 60)
COLOR_WAIT = (60, 60, 60)
COLOR_MY_SHIP = (0, 100, 80)
COLOR_MY_HIT = (180, 0, 0)


def place_ships(cols, rows, exclude_col=None):
    """Place ships scaled to grid size, return set of key indices."""
    play_cols = cols if exclude_col is None else cols - 1
    total = play_cols * rows
    if total <= 6:
        sizes = [2]
    elif total <= 10:
        sizes = [3, 2]
    elif total <= 15:
        sizes = [3, 2, 2]
    elif total <= 20:
        sizes = [4, 3, 2]
    else:
        sizes = [4, 3, 3, 2]

    ships = set()
    ship_groups = []
    for size in sizes:
        for _ in range(200):
            horizontal = random.choice([True, False])
            if horizontal:
                c = random.randint(0, play_cols - size)
                r = random.randint(0, rows - 1)
                cells = [(c + i, r) for i in range(size)]
            else:
                c = random.randint(0, play_cols - 1)
                r = random.randint(0, rows - size)
                cells = [(c, r + i) for i in range(size)]

            keys = {rr * cols + cc for cc, rr in cells}
            if not keys & ships:
                ships |= keys
                ship_groups.append(keys)
                break

    return ships, ship_groups


def set_key_image(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        font_size = 22 if len(text) <= 2 else (16 if len(text) <= 4 else 11)
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


class PlayerBoard:
    """One player's state."""

    def __init__(self, cols, rows, exclude_col=None):
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.ships, self.ship_groups = place_ships(
            cols, rows, exclude_col=exclude_col)
        self.hits_received = set()
        self.misses_received = set()
        self.attacks_hit = set()
        self.attacks_miss = set()
        self.sunk_ships = set()

    def receive_attack(self, key):
        """Return 'hit', 'miss', or 'sunk'."""
        if key in self.hits_received or key in self.misses_received:
            return None  # Already attacked here

        if key in self.ships:
            self.hits_received.add(key)
            # Check if a ship is fully sunk
            for group in self.ship_groups:
                if key in group and group.issubset(self.hits_received):
                    self.sunk_ships |= group
                    return "sunk"
            return "hit"
        self.misses_received.add(key)
        return "miss"

    def all_sunk(self):
        return self.hits_received == self.ships


class BattleshipMulti:
    """Battleship game supporting 1 or 2 decks."""

    def __init__(self, decks):
        self.decks = decks
        self.num_players = len(decks)
        self.lock = threading.Lock()

        rows, cols = decks[0].key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows

        self.boards = []
        self.current_player = 0  # 0 or 1
        self.game_active = False
        self.winner = None  # 0, 1, or None
        self.scores = [0, 0]
        self._cooldown_until = 0

    def reset(self):
        if self.num_players == 2:
            # Exclude last column (UI: GO/WAIT, score)
            self.boards = [
                PlayerBoard(self.cols, self.rows,
                            exclude_col=self.cols - 1),
                PlayerBoard(self.cols, self.rows,
                            exclude_col=self.cols - 1),
            ]
        else:
            self.boards = [PlayerBoard(self.cols, self.rows)]

        self.current_player = 0
        self.winner = None
        self.game_active = True
        self._cooldown_until = 0

    def handle_key(self, key, deck_index=0):
        now = time.monotonic()

        if self.winner is not None:
            if now < self._cooldown_until:
                return
            self.reset()
            self.render_all()
            return

        if not self.game_active:
            self.reset()
            self.render_all()
            return

        if self.num_players == 2:
            self._handle_2p(key, deck_index)
        else:
            self._handle_solo(key)

    def _handle_solo(self, key):
        board = self.boards[0]
        if key in board.hits_received or key in board.attacks_miss:
            return

        result = board.receive_attack(key)
        if result is None:
            return

        if result in ("hit", "sunk"):
            board.attacks_hit.add(key)
        else:
            board.attacks_miss.add(key)

        if board.all_sunk():
            self.winner = 0
            self.scores[0] += 1
            self._cooldown_until = time.monotonic() + 3.0

        self.render_all()

    def _handle_2p(self, key, deck_index):
        # Only current player can act
        if deck_index != self.current_player:
            return

        # Attack opponent's board
        opponent = 1 - self.current_player
        target_board = self.boards[opponent]
        my_board = self.boards[self.current_player]

        result = target_board.receive_attack(key)
        if result is None:
            return

        if result in ("hit", "sunk"):
            my_board.attacks_hit.add(key)
        else:
            my_board.attacks_miss.add(key)
            # Miss = switch turns
            self.current_player = opponent

        if target_board.all_sunk():
            self.winner = deck_index
            self.scores[deck_index] += 1
            self._cooldown_until = time.monotonic() + 3.0

        self.render_all()

    def render_all(self):
        for i, deck in enumerate(self.decks):
            self._render_deck(deck, i)

    def _render_deck(self, deck, deck_index):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active and self.winner is None:
            # Title screen
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    self._set(deck, key, COLOR_TITLE, "SHIPS")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                    if self.num_players == 2:
                        label = f"P{deck_index + 1}"
                        self._set(deck, key, COLOR_YOUR_TURN, label)
                    else:
                        self._set(deck, key, COLOR_WATER, "~")
                elif (c, r) == (mid_c, last_r):
                    self._set(deck, key, COLOR_TITLE, "START")
                elif (c, r) == (0, last_r) and sum(self.scores) > 0:
                    self._set(
                        deck, key, COLOR_SCORE,
                        f"{self.scores[0]}-{self.scores[1]}"
                    )
                else:
                    self._set(deck, key, COLOR_WATER, "~")
            return

        if self.winner is not None:
            self._render_gameover(deck, deck_index)
            return

        if self.num_players == 2:
            self._render_2p(deck, deck_index)
        else:
            self._render_solo(deck)

    def _render_solo(self, deck):
        board = self.boards[0]
        for key in range(self.total_keys):
            if key in board.sunk_ships:
                self._set(deck, key, COLOR_SUNK, "S")
            elif key in board.attacks_hit:
                self._set(deck, key, COLOR_HIT, "X")
            elif key in board.attacks_miss:
                self._set(deck, key, COLOR_MISS, "o")
            elif key == 0:
                shots = len(board.attacks_hit) + len(board.attacks_miss)
                self._set(deck, key, COLOR_SCORE, f"{shots}")
            else:
                self._set(deck, key, COLOR_WATER, "~")

    def _render_2p(self, deck, deck_index):
        my_board = self.boards[deck_index]
        is_my_turn = self.current_player == deck_index
        last_c = self.cols - 1

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols

            # Right column: show my own ships (defense view)
            if c == last_c:
                if r == 0:
                    # Turn indicator
                    if is_my_turn:
                        self._set(deck, key, COLOR_YOUR_TURN, "GO!")
                    else:
                        self._set(deck, key, COLOR_WAIT, "WAIT")
                elif r == self.rows - 1:
                    hits = len(my_board.attacks_hit)
                    self._set(deck, key, COLOR_SCORE, f"H:{hits}")
                else:
                    self._set(deck, key, COLOR_SCORE, "")
                continue

            # Main area: attack grid (what I see of opponent)
            if key in my_board.sunk_ships:
                # Opponent hit my sunk ship — not shown here
                pass

            if key in my_board.attacks_hit:
                self._set(deck, key, COLOR_HIT, "X")
            elif key in my_board.attacks_miss:
                self._set(deck, key, COLOR_MISS, "o")
            else:
                if is_my_turn:
                    self._set(deck, key, COLOR_WATER, "~")
                else:
                    self._set(deck, key, COLOR_WAIT, "")

    def _render_gameover(self, deck, deck_index):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        now = time.monotonic()
        remaining = max(0, self._cooldown_until - now)
        can_restart = remaining <= 0

        i_won = (self.winner == deck_index) or (
            self.num_players == 1 and self.winner == 0
        )

        # Show opponent's ships (reveal)
        if self.num_players == 2:
            opponent = 1 - deck_index
            opponent_ships = self.boards[opponent].ships
        else:
            opponent_ships = self.boards[0].ships

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols

            if (c, r) == (mid_c, 0):
                color = COLOR_WIN if i_won else COLOR_LOSE
                text = "WIN!" if i_won else "LOST"
                self._set(deck, key, color, text)
            elif (c, r) == (mid_c, last_r):
                if can_restart:
                    self._set(deck, key, COLOR_TITLE, "AGAIN")
                else:
                    self._set(deck, key, COLOR_WAIT, f"{remaining:.0f}s")
            elif (c, r) == (0, last_r):
                self._set(
                    deck, key, COLOR_SCORE,
                    f"{self.scores[0]}-{self.scores[1]}"
                )
            elif key in opponent_ships:
                self._set(deck, key, COLOR_SHIP, "S")
            else:
                self._set(deck, key, COLOR_WATER, "")

    def _set(self, deck, key, color, text=""):
        set_key_image(deck, key, color, text)

    def game_loop(self):
        """Tick loop for rendering cooldown countdown."""
        while all(d.is_open() for d in self.decks):
            if self.winner is not None:
                with self.lock:
                    self.render_all()
            time.sleep(0.5)


def main():
    streamdecks = DeviceManager().enumerate()
    visual_decks = [d for d in streamdecks if d.is_visual()]

    if not visual_decks:
        print("No visual Stream Deck found.")
        sys.exit(1)

    for d in visual_decks:
        d.open()
        d.reset()
        d.set_brightness(80)

    if len(visual_decks) >= 2:
        decks = visual_decks[:2]
        print(f"2-PLAYER BATTLESHIP!")
        print(f"  P1: {decks[0].deck_type()} ({decks[0].get_serial_number()})")
        print(f"  P2: {decks[1].deck_type()} ({decks[1].get_serial_number()})")
        print("Ships placed. Hit = keep turn. Miss = switch. Sink all to win!")
    else:
        decks = visual_decks[:1]
        rows, cols = decks[0].key_layout()
        print(f"SOLO Battleship on {decks[0].deck_type()} ({cols}x{rows})")
        print("Find all ships! Ctrl+C to quit.")

    game = BattleshipMulti(decks)

    # Auto-start: place ships and go
    game.reset()
    game.render_all()

    for i, deck in enumerate(decks):
        def make_callback(idx):
            def callback(deck, key, state):
                if not state:
                    return
                with game.lock:
                    game.handle_key(key, deck_index=idx)
            return callback
        deck.set_key_callback(make_callback(i))

    # Background thread for cooldown rendering
    render_thread = threading.Thread(target=game.game_loop, daemon=True)
    render_thread.start()

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
        print(f"\nScore: P1={game.scores[0]} P2={game.scores[1]}")


if __name__ == "__main__":
    main()
