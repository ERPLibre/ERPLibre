#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Bomberman — 1P or 2P.

1 deck: destroy all walls. Don't blow yourself up.
2 decks: both players on same grid shown on both decks.
Press adjacent to move, press own position to place bomb.
Last one alive wins!
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

GAME_META = {
    "name": "Bomberman",
    "category": "arcade",
    "multiplayer": True,
    "sdplus": False,
    "description": "Place bombs, destroy walls, survive! 1P or 2P.",
    "icon": "bomberman"
}

COLOR_EMPTY = (40, 60, 40)
COLOR_P1 = (0, 180, 255)
COLOR_P2 = (255, 140, 0)
COLOR_WALL = (120, 80, 40)
COLOR_BOMB = (60, 60, 60)
COLOR_EXPLOSION = (255, 100, 0)
COLOR_TITLE = (0, 80, 160)
COLOR_SCORE = (40, 40, 80)
COLOR_WIN = (0, 200, 60)
COLOR_DEAD = (180, 0, 0)

BOMB_TIMER = 3.0
EXPLOSION_DURATION = 0.5


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


class Bomberman:
    def __init__(self, decks):
        self.decks = decks
        self.num_players = len(decks)
        rows, cols = decks[0].key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.running = True
        self.players = [(0, 0), (0, 0)]
        self.alive = [True, True]
        self.walls = set()
        self.bombs = {}
        self.explosions = {}
        self.game_active = False
        self.game_over = False
        self.winner = -1
        self.scores = [0, 0]

    def reset(self):
        self.players[0] = (0, self.rows - 1)
        if self.num_players == 2:
            self.players[1] = (self.cols - 1, 0)
        self.alive = [True, True]
        self.walls = set()
        self.bombs = {}
        self.explosions = {}
        self.game_over = False
        self.winner = -1
        self.game_active = True

        for r in range(self.rows):
            for c in range(self.cols):
                pos = (c, r)
                # Keep start corners clear
                if abs(c - 0) + abs(r - (self.rows - 1)) <= 1:
                    continue
                if self.num_players == 2 and abs(c - (self.cols - 1)) + abs(r - 0) <= 1:
                    continue
                if random.random() < 0.35:
                    self.walls.add(pos)

    def handle_key(self, key, deck_index=0):
        if self.game_over or not self.game_active:
            self.reset()
            return

        p = 0 if self.num_players == 1 else deck_index
        if not self.alive[p]:
            return

        col = key % self.cols
        row = key // self.cols
        px, py = self.players[p]

        if (col, row) == (px, py):
            if (px, py) not in self.bombs:
                self.bombs[(px, py)] = time.monotonic()
            return

        dx = col - px
        dy = row - py
        if abs(dx) >= abs(dy):
            dx = 1 if dx > 0 else -1
            dy = 0
        else:
            dy = 1 if dy > 0 else -1
            dx = 0

        nx, ny = px + dx, py + dy
        if 0 <= nx < self.cols and 0 <= ny < self.rows:
            if (nx, ny) not in self.walls and (nx, ny) not in self.bombs:
                # Don't walk into other player
                other = 1 - p
                if self.num_players == 1 or (nx, ny) != self.players[other]:
                    self.players[p] = (nx, ny)

    def tick(self):
        if not self.game_active or self.game_over:
            return

        now = time.monotonic()

        exploded = [pos for pos, t in self.bombs.items() if now - t >= BOMB_TIMER]
        for pos in exploded:
            del self.bombs[pos]
            self._explode(pos, now)

        expired = [pos for pos, t in self.explosions.items() if now - t > EXPLOSION_DURATION]
        for pos in expired:
            del self.explosions[pos]

        # Check players in explosions
        for p in range(self.num_players):
            if self.alive[p] and self.players[p] in self.explosions:
                self.alive[p] = False

        alive_count = sum(1 for i in range(self.num_players) if self.alive[i])

        if self.num_players == 2:
            if alive_count <= 1:
                self.game_over = True
                if self.alive[0] and not self.alive[1]:
                    self.winner = 0
                    self.scores[0] += 1
                elif self.alive[1] and not self.alive[0]:
                    self.winner = 1
                    self.scores[1] += 1
                else:
                    self.winner = -1
        else:
            if not self.alive[0]:
                self.game_over = True
                self.winner = -1
            elif not self.walls and not self.bombs:
                self.game_over = True
                self.winner = 0
                self.scores[0] += 1

    def _explode(self, pos, now):
        cx, cy = pos
        self.explosions[pos] = now
        for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < self.cols and 0 <= ny < self.rows:
                self.explosions[(nx, ny)] = now
                self.walls.discard((nx, ny))

    def render_all(self):
        for i, deck in enumerate(self.decks):
            self._render(deck, i)

    def _render(self, deck, deck_index):
        mid_c = self.cols // 2
        last_r = self.rows - 1
        now = time.monotonic()

        if not self.game_active:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, key, COLOR_EXPLOSION, "BOMB")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "START")
                elif self.num_players == 2 and (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                    set_key(deck, key, COLOR_P1 if deck_index == 0 else COLOR_P2, f"P{deck_index + 1}")
                elif (c, r) == (0, last_r) and sum(self.scores) > 0:
                    set_key(deck, key, COLOR_SCORE, f"{self.scores[0]}-{self.scores[1]}")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            return

        if self.game_over:
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
                            set_key(deck, key, COLOR_DEAD, "DEAD")
                    else:
                        set_key(deck, key, COLOR_WIN if self.winner == 0 else COLOR_DEAD, "WIN!" if self.winner == 0 else "DEAD")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            return

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols
            pos = (c, r)

            if pos in self.explosions:
                set_key(deck, key, COLOR_EXPLOSION, "")
            elif self.alive[0] and pos == self.players[0]:
                set_key(deck, key, COLOR_P1, "P1")
            elif self.num_players == 2 and self.alive[1] and pos == self.players[1]:
                set_key(deck, key, COLOR_P2, "P2")
            elif pos in self.bombs:
                remaining = max(0, BOMB_TIMER - (now - self.bombs[pos]))
                set_key(deck, key, COLOR_BOMB, f"{remaining:.0f}")
            elif pos in self.walls:
                set_key(deck, key, COLOR_WALL, "#")
            else:
                set_key(deck, key, COLOR_EMPTY, "")

    def game_loop(self):
        while self.running and all(d.is_open() for d in self.decks):
            with self.lock:
                self.tick()
                self.render_all()
            time.sleep(0.2)


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
        print("2-PLAYER BOMBERMAN! P1=blue P2=orange. Last alive wins!")
    else:
        print(f"Bomberman on {decks[0].deck_type()}")

    print("Move=press adjacent. Double-press=bomb. Ctrl+C to quit.")

    game = Bomberman(decks)
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

    t = threading.Thread(target=game.game_loop, daemon=True)
    t.start()

    try:
        while all(d.is_open() for d in decks):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        game.running = False
        for d in decks:
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
