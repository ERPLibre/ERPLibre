#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Snake — 1P or 2P VS.

1 deck: classic snake.
2 decks: two snakes on same grid shown on both decks. Collision = death.
Press buttons to steer your snake toward that direction.
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

COLOR_EMPTY = (20, 20, 30)
COLOR_SNAKE1 = (0, 180, 0)
COLOR_HEAD1 = (0, 255, 80)
COLOR_SNAKE2 = (0, 80, 220)
COLOR_HEAD2 = (80, 160, 255)
COLOR_FOOD = (255, 30, 30)
COLOR_GAMEOVER = (180, 0, 0)
COLOR_SCORE = (40, 40, 80)
COLOR_READY = (0, 80, 160)
COLOR_WIN = (0, 200, 60)
COLOR_LOSE = (200, 0, 0)

UP = (0, -1)
DOWN = (0, 1)
LEFT = (-1, 0)
RIGHT = (1, 0)

BASE_SPEED = 0.5
MIN_SPEED = 0.15


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 18 if len(text) <= 4 else 12
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


class SnakeGame:
    def __init__(self, decks):
        self.decks = decks
        self.num_players = len(decks)
        rows, cols = decks[0].key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.running = True
        self.game_active = False
        self.game_over = False
        self.snakes = [[], []]
        self.directions = [RIGHT, LEFT]
        self.scores = [0, 0]
        self.food = None
        self.loser = -1

    def reset(self):
        mid_r = self.rows // 2
        self.snakes[0] = [(1, mid_r)]
        self.directions[0] = RIGHT
        self.scores = [0, 0]
        self.loser = -1
        self.game_over = False
        self.game_active = True

        if self.num_players == 2:
            self.snakes[1] = [(self.cols - 2, mid_r)]
            self.directions[1] = LEFT
        else:
            self.snakes[1] = []

        self._spawn_food()

    def _all_snake_cells(self):
        return set(self.snakes[0]) | set(self.snakes[1])

    def _spawn_food(self):
        occupied = self._all_snake_cells()
        empty = [
            (c, r) for r in range(self.rows) for c in range(self.cols)
            if (c, r) not in occupied
        ]
        self.food = random.choice(empty) if empty else None

    def tick(self):
        if not self.game_active or self.game_over:
            return

        active = [0] if self.num_players == 1 else [0, 1]

        new_heads = {}
        for p in active:
            hx, hy = self.snakes[p][0]
            dx, dy = self.directions[p]
            new_heads[p] = ((hx + dx) % self.cols, (hy + dy) % self.rows)

        # Check collisions
        for p in active:
            nh = new_heads[p]
            # Self collision
            if nh in self.snakes[p]:
                self.loser = p
                self.game_over = True
                return
            # Other snake collision
            other = 1 - p
            if other in active and nh in self.snakes[other]:
                self.loser = p
                self.game_over = True
                return

        # Head-on collision (both move to same cell)
        if self.num_players == 2 and new_heads[0] == new_heads[1]:
            self.loser = -1  # Draw
            self.game_over = True
            return

        # Move snakes
        for p in active:
            self.snakes[p].insert(0, new_heads[p])
            if new_heads[p] == self.food:
                self.scores[p] += 1
                self._spawn_food()
            else:
                self.snakes[p].pop()

    def get_speed(self):
        total = sum(self.scores)
        return max(MIN_SPEED, BASE_SPEED - total * 0.02)

    def handle_key(self, key, deck_index=0):
        if self.game_over or not self.game_active:
            self.reset()
            return

        p = 0 if self.num_players == 1 else deck_index
        col = key % self.cols
        row = key // self.cols
        hx, hy = self.snakes[p][0]

        dx = col - hx
        dy = row - hy
        if abs(dx) >= abs(dy):
            new_dir = RIGHT if dx > 0 else LEFT
        else:
            new_dir = DOWN if dy > 0 else UP

        cur = self.directions[p]
        if (new_dir[0] + cur[0], new_dir[1] + cur[1]) != (0, 0):
            self.directions[p] = new_dir

    def render_all(self):
        for i, deck in enumerate(self.decks):
            self._render(deck, i)

    def _render(self, deck, deck_index):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active and not self.game_over:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, key, COLOR_HEAD1 if deck_index == 0 else COLOR_HEAD2, "SNAKE")
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 0):
                    if self.num_players == 2:
                        set_key(deck, key, COLOR_SCORE, f"P{deck_index + 1}")
                    else:
                        set_key(deck, key, COLOR_READY, "PRESS")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_READY, "START")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            return

        if self.game_over:
            for key in range(self.total_keys):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(deck, key, COLOR_SCORE, f"{self.scores[0]}-{self.scores[1]}" if self.num_players == 2 else f"S:{self.scores[0]}")
                elif self.num_players == 2 and (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    if self.loser < 0:
                        set_key(deck, key, COLOR_SCORE, "DRAW")
                    elif self.loser == deck_index:
                        set_key(deck, key, COLOR_LOSE, "LOST")
                    else:
                        set_key(deck, key, COLOR_WIN, "WIN!")
                elif (c, r) == (mid_c, last_r):
                    set_key(deck, key, COLOR_READY, "AGAIN")
                else:
                    set_key(deck, key, COLOR_EMPTY, "")
            return

        for key in range(self.total_keys):
            r = key // self.cols
            c = key % self.cols
            pos = (c, r)

            if pos == self.food:
                set_key(deck, key, COLOR_FOOD, "")
            elif self.snakes[0] and pos == self.snakes[0][0]:
                set_key(deck, key, COLOR_HEAD1, str(self.scores[0]) if self.scores[0] else "")
            elif pos in self.snakes[0]:
                set_key(deck, key, COLOR_SNAKE1, "")
            elif self.num_players == 2 and self.snakes[1] and pos == self.snakes[1][0]:
                set_key(deck, key, COLOR_HEAD2, str(self.scores[1]) if self.scores[1] else "")
            elif self.num_players == 2 and pos in self.snakes[1]:
                set_key(deck, key, COLOR_SNAKE2, "")
            else:
                set_key(deck, key, COLOR_EMPTY, "")

    def game_loop(self):
        while self.running and all(d.is_open() for d in self.decks):
            with self.lock:
                self.tick()
                self.render_all()
            time.sleep(self.get_speed())


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
        print("2-PLAYER SNAKE! Green vs Blue. Collision = death!")
    else:
        print(f"Snake on {decks[0].deck_type()}")

    print("Press any button to steer. Ctrl+C to quit.")

    game = SnakeGame(decks)
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


if __name__ == "__main__":
    main()
