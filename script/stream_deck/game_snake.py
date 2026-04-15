#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Snake game for Elgato Stream Deck (adapts to any layout)."""

import io
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

# Colors (RGBA)
COLOR_EMPTY = (20, 20, 30)
COLOR_SNAKE = (0, 180, 0)
COLOR_HEAD = (0, 255, 80)
COLOR_FOOD = (255, 30, 30)
COLOR_GAMEOVER = (180, 0, 0)
COLOR_SCORE = (40, 40, 80)
COLOR_WALL = (60, 60, 60)
COLOR_READY = (0, 80, 160)
COLOR_WIN = (255, 215, 0)

# Directions
UP = (0, -1)
DOWN = (0, 1)
LEFT = (-1, 0)
RIGHT = (1, 0)

# Game speed (seconds per tick, decreases with score)
BASE_SPEED = 0.5
MIN_SPEED = 0.15


class SnakeGame:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.cols = cols
        self.rows = rows
        self.total_keys = cols * rows
        self.lock = threading.Lock()
        self.running = True
        self.game_active = False
        self.snake = []
        self.food = None
        self.direction = RIGHT
        self.score = 0
        self.high_score = 0
        self.game_over = False

    def key_to_pos(self, key):
        """Convert key index to (col, row)."""
        return key % self.cols, key // self.cols

    def pos_to_key(self, col, row):
        """Convert (col, row) to key index."""
        if 0 <= col < self.cols and 0 <= row < self.rows:
            return row * self.cols + col
        return -1

    def reset(self):
        """Reset game state."""
        center = (self.cols // 2, self.rows // 2)
        self.snake = [center]
        self.direction = RIGHT
        self.score = 0
        self.game_over = False
        self.game_active = True
        self._spawn_food()

    def _spawn_food(self):
        """Place food on a random empty cell."""
        empty = []
        for r in range(self.rows):
            for c in range(self.cols):
                if (c, r) not in self.snake:
                    empty.append((c, r))
        if empty:
            self.food = random.choice(empty)
        else:
            # Win condition — snake fills entire grid
            self.food = None
            self.game_over = True

    def tick(self):
        """Advance game by one step."""
        if not self.game_active or self.game_over:
            return

        head_x, head_y = self.snake[0]
        dx, dy = self.direction
        new_head = (head_x + dx, head_y + dy)

        # Wall collision — wrap around
        nx, ny = new_head
        nx = nx % self.cols
        ny = ny % self.rows
        new_head = (nx, ny)

        # Self collision
        if new_head in self.snake:
            self.game_over = True
            if self.score > self.high_score:
                self.high_score = self.score
            return

        self.snake.insert(0, new_head)

        # Food collision
        if new_head == self.food:
            self.score += 1
            self._spawn_food()
        else:
            self.snake.pop()

    def get_speed(self):
        """Current tick speed — faster as score increases."""
        speed = BASE_SPEED - (self.score * 0.03)
        return max(speed, MIN_SPEED)

    def handle_key(self, key):
        """Handle key press."""
        if self.game_over or not self.game_active:
            # Any key restarts
            self.reset()
            return

        col, row = self.key_to_pos(key)
        head_x, head_y = self.snake[0]

        # Calculate direction toward pressed key
        dx = col - head_x
        dy = row - head_y

        # Normalize to single step, prefer axis with larger delta
        if abs(dx) >= abs(dy):
            if dx > 0:
                new_dir = RIGHT
            elif dx < 0:
                new_dir = LEFT
            elif dy > 0:
                new_dir = DOWN
            else:
                new_dir = UP
        else:
            if dy > 0:
                new_dir = DOWN
            elif dy < 0:
                new_dir = UP
            elif dx > 0:
                new_dir = RIGHT
            else:
                new_dir = LEFT

        # Prevent 180 degree turn (instant death)
        cur_dx, cur_dy = self.direction
        if (new_dir[0] + cur_dx, new_dir[1] + cur_dy) != (0, 0):
            self.direction = new_dir

    def render(self):
        """Render game state to deck."""
        mid_c = self.cols // 2
        last_r = self.rows - 1
        for r in range(self.rows):
            for c in range(self.cols):
                key = self.pos_to_key(c, r)
                pos = (c, r)

                if self.game_over and self.game_active:
                    if pos in self.snake:
                        color = COLOR_GAMEOVER
                        text = ""
                    elif pos == (mid_c, 0):
                        color = COLOR_SCORE
                        text = "GAME"
                    elif pos == (mid_c, last_r // 2 if last_r > 1 else 1):
                        color = COLOR_SCORE
                        text = f"{self.score}"
                    elif pos == (mid_c, last_r):
                        color = COLOR_SCORE
                        text = "OVER"
                    else:
                        color = COLOR_EMPTY
                        text = ""
                elif not self.game_active:
                    # Title screen
                    if pos == (mid_c - 1, 0):
                        color = COLOR_HEAD
                        text = "SNAKE"
                    elif pos == (mid_c, last_r // 2 if last_r > 1 else 0):
                        color = COLOR_READY
                        text = "PRESS"
                    elif pos == (mid_c + 1, last_r):
                        color = COLOR_READY
                        text = "START"
                    elif pos == (0, last_r):
                        color = COLOR_SCORE
                        text = f"HI:{self.high_score}"
                    else:
                        color = COLOR_EMPTY
                        text = ""
                elif pos == self.snake[0]:
                    color = COLOR_HEAD
                    text = str(self.score) if self.score > 0 else ""
                elif pos in self.snake:
                    color = COLOR_SNAKE
                    text = ""
                elif pos == self.food:
                    color = COLOR_FOOD
                    text = ""
                else:
                    color = COLOR_EMPTY
                    text = ""

                self._set_key(key, color, text)

    def _set_key(self, key, color, text=""):
        """Render a single key with color and optional text."""
        fmt = self.deck.key_image_format()
        w, h = fmt["size"]

        img = Image.new("RGB", (w, h), color)

        if text:
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.load_default(size=16)
            except TypeError:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            tx = (w - tw) // 2
            ty = (h - th) // 2
            draw.text((tx, ty), text, fill=(255, 255, 255), font=font)

        native = PILHelper.to_native_key_format(self.deck, img)
        try:
            with self.deck:
                self.deck.set_key_image(key, native)
        except TransportError:
            pass

    def game_loop(self):
        """Main game loop running in a thread."""
        while self.running and self.deck.is_open():
            with self.lock:
                self.tick()
                self.render()
            time.sleep(self.get_speed())

    def key_callback(self, deck, key, state):
        """Stream Deck key callback."""
        if not state:
            return
        with self.lock:
            self.handle_key(key)
            self.render()


def main():
    streamdecks = DeviceManager().enumerate()
    if not streamdecks:
        print("No Stream Deck found.")
        sys.exit(1)

    deck = None
    for d in streamdecks:
        if d.is_visual():
            deck = d
            break

    if deck is None:
        print("No visual Stream Deck found.")
        sys.exit(1)

    deck.open()
    deck.reset()
    deck.set_brightness(80)

    rows, cols = deck.key_layout()
    print(f"Playing Snake on {deck.deck_type()}")
    print(f"Grid: {cols}x{rows} ({deck.key_count()} keys)")
    print("Press any button to start. Ctrl+C to quit.")

    game = SnakeGame(deck)
    game.render()

    deck.set_key_callback(game.key_callback)

    game_thread = threading.Thread(target=game.game_loop, daemon=True)
    game_thread.start()

    try:
        while deck.is_open():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        game.running = False
        with deck:
            deck.reset()
            deck.close()
        print(f"\nFinal score: {game.score} | High score: {game.high_score}")


if __name__ == "__main__":
    main()
