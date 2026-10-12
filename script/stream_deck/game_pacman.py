#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Pac-Man with SD+ touchscreen support.

Standard deck: button grid, press to steer.
SD+: game on touchscreen, dials to steer, dial press to start.
"""

import io
import random
import sys
import threading
import time

try:
    from PIL import Image, ImageDraw, ImageFont
    from StreamDeck.DeviceManager import DeviceManager
    from StreamDeck.Devices.StreamDeck import DialEventType
    from StreamDeck.ImageHelpers import PILHelper
    from StreamDeck.Transport.Transport import TransportError
except ImportError as e:
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

GAME_META = {
    "name": "Pac-Man",
    "category": "arcade",
    "multiplayer": False,
    "sdplus": True,
    "description": "Eat dots, power pellets, eat ghosts! SD+ touchscreen.",
    "icon": "pacman"
}

COLOR_EMPTY = (0, 0, 20)
COLOR_PAC = (255, 255, 0)
COLOR_GHOST = (255, 0, 0)
COLOR_GHOST2 = (255, 100, 200)
COLOR_DOT = (40, 40, 60)
COLOR_WALL = (0, 0, 80)
COLOR_EATEN = (0, 0, 10)
COLOR_TITLE = (0, 80, 160)
COLOR_WIN = (0, 200, 60)
COLOR_DEAD = (200, 0, 0)
COLOR_SCORE = (40, 40, 80)
COLOR_POWER = (255, 180, 255)
COLOR_VULN = (60, 60, 255)

POWER_DURATION = 50  # ticks of vulnerability
GHOST_FROZEN_TICKS = 83  # ~10s at 0.12s/tick

TICK_SPEED_BUTTONS = 0.5
TICK_SPEED_SCREEN = 0.12


def set_key(deck, key, color, text=""):
    fmt = deck.key_image_format()
    w, h = fmt["size"]
    img = Image.new("RGB", (w, h), color)
    if text:
        draw = ImageDraw.Draw(img)
        fs = 22 if len(text) <= 1 else 14 if len(text) <= 4 else 11
        try:
            font = ImageFont.load_default(size=fs)
        except TypeError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((w - tw) // 2 + 1, (h - th) // 2 + 1), text,
                  fill=(0, 0, 0), font=font)
        draw.text(((w - tw) // 2, (h - th) // 2), text,
                  fill=(255, 255, 255), font=font)
    native = PILHelper.to_native_key_format(deck, img)
    try:
        with deck:
            deck.set_key_image(key, native)
    except TransportError:
        pass


def set_screen(deck, img):
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="JPEG")
    img_bytes = img_bytes.getvalue()
    try:
        with deck:
            w = (deck.TOUCHSCREEN_PIXEL_WIDTH
                 or deck.SCREEN_PIXEL_WIDTH or 800)
            h = (deck.TOUCHSCREEN_PIXEL_HEIGHT
                 or deck.SCREEN_PIXEL_HEIGHT or 100)
            if deck.DECK_TOUCH:
                deck.set_touchscreen_image(img_bytes, 0, 0, w, h)
            else:
                deck.set_screen_image(img_bytes)
    except (TransportError, AttributeError):
        pass


class PacMan:
    def __init__(self, deck):
        self.deck = deck
        rows, cols = deck.key_layout()
        self.btn_cols = cols
        self.btn_rows = rows
        self.lock = threading.Lock()
        self.running = True

        self.is_sdplus = bool(
            getattr(deck, "DIAL_COUNT", 0) and deck.DIAL_COUNT > 0
        )

        if self.is_sdplus:
            self.screen_w = (
                deck.TOUCHSCREEN_PIXEL_WIDTH
                or deck.SCREEN_PIXEL_WIDTH or 800
            )
            self.screen_h = (
                deck.TOUCHSCREEN_PIXEL_HEIGHT
                or deck.SCREEN_PIXEL_HEIGHT or 100
            )
            # Grid on touchscreen: cell_size ~16-20px
            self.cell = 16
            self.cols = self.screen_w // self.cell
            self.rows = self.screen_h // self.cell
        else:
            self.cols = cols
            self.rows = rows

        self.pac = (0, 0)
        self.ghosts = []
        self.ghost_spawns = []
        self.ghost_frozen = []  # ticks remaining frozen at spawn
        self.dots = set()
        self.power_pellets = set()
        self.walls = set()
        self.score = 0
        self.high_score = 0
        self.game_active = False
        self.game_over = False
        self.won = False
        self.direction = (1, 0)
        self.next_dir = (1, 0)
        self.tick_count = 0
        self.vuln_timer = 0  # ticks remaining for vulnerability

    def reset(self):
        self.pac = (1, self.rows - 2)
        num_ghosts = 2 if self.is_sdplus else 1
        self.ghosts = []
        self.ghost_spawns = []
        self.ghost_frozen = []
        for i in range(num_ghosts):
            pos = (self.cols - 2 - i, 1)
            self.ghosts.append(pos)
            self.ghost_spawns.append(pos)
            self.ghost_frozen.append(0)
        self.dots = set()
        self.power_pellets = set()
        self.walls = set()
        self.score = 0
        self.game_over = False
        self.won = False
        self.direction = (1, 0)
        self.next_dir = (1, 0)
        self.tick_count = 0
        self.vuln_timer = 0
        self.game_active = True
        # Build maze
        for r in range(self.rows):
            for c in range(self.cols):
                pos = (c, r)
                if pos == self.pac or pos in self.ghosts:
                    continue
                if r == 0 or r == self.rows - 1 or c == 0 or c == self.cols - 1:
                    self.walls.add(pos)
                elif random.random() < 0.12:
                    self.walls.add(pos)
                else:
                    self.dots.add(pos)
        # Ensure all open cells are reachable from pac-man
        self._ensure_connected()
        # Place 5 power pellets at equal distance across the map
        all_dots = sorted(self.dots)
        if len(all_dots) >= 5:
            step = len(all_dots) // 6
            for i in range(1, 6):
                pellet = all_dots[i * step]
                self.dots.discard(pellet)
                self.power_pellets.add(pellet)

    def _flood_fill(self, start):
        """Return set of all cells reachable from start."""
        visited = set()
        queue = [start]
        while queue:
            pos = queue.pop()
            if pos in visited:
                continue
            visited.add(pos)
            c, r = pos
            for dc, dr in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                nc, nr = c + dc, r + dr
                npos = (nc, nr)
                if (0 <= nc < self.cols and 0 <= nr < self.rows
                        and npos not in self.walls and npos not in visited):
                    queue.append(npos)
        return visited

    def _ensure_connected(self):
        """Remove walls to connect all open cells to pac-man."""
        reachable = self._flood_fill(self.pac)
        # Find all open cells (dots + pac + ghosts)
        all_open = self.dots | {self.pac} | set(self.ghosts)
        unreachable = all_open - reachable
        if not unreachable:
            return
        # For each unreachable cell, carve a path toward reachable area
        for target in list(unreachable):
            if target in reachable:
                continue
            # BFS from target through walls toward reachable area
            visited = set()
            queue = [(target, [])]
            found = False
            while queue and not found:
                pos, path = queue.pop(0)
                if pos in visited:
                    continue
                visited.add(pos)
                c, r = pos
                for dc, dr in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                    nc, nr = c + dc, r + dr
                    npos = (nc, nr)
                    if not (0 <= nc < self.cols and 0 <= nr < self.rows):
                        continue
                    if npos in visited:
                        continue
                    # Don't break border walls
                    if (nr == 0 or nr == self.rows - 1
                            or nc == 0 or nc == self.cols - 1):
                        continue
                    if npos in reachable:
                        # Found path — remove walls along it
                        for wp in path:
                            if wp in self.walls:
                                self.walls.discard(wp)
                                self.dots.add(wp)
                        found = True
                        break
                    new_path = path + ([npos] if npos in self.walls else [])
                    queue.append((npos, new_path))
            # Refresh reachable set after carving
            reachable = self._flood_fill(self.pac)

    def tick(self):
        if not self.game_active or self.game_over:
            return
        self.tick_count += 1

        # Vulnerability timer
        if self.vuln_timer > 0:
            self.vuln_timer -= 1

        # Frozen ghost timers
        for gi in range(len(self.ghost_frozen)):
            if self.ghost_frozen[gi] > 0:
                self.ghost_frozen[gi] -= 1

        # Try next_dir first, fall back to current direction
        dx, dy = self.next_dir
        nx = (self.pac[0] + dx) % self.cols
        ny = (self.pac[1] + dy) % self.rows
        if (nx, ny) not in self.walls:
            self.direction = self.next_dir
            self.pac = (nx, ny)
        else:
            dx, dy = self.direction
            nx = (self.pac[0] + dx) % self.cols
            ny = (self.pac[1] + dy) % self.rows
            if (nx, ny) not in self.walls:
                self.pac = (nx, ny)

        # Eat dot
        if self.pac in self.dots:
            self.dots.discard(self.pac)
            self.score += 1

        # Eat power pellet
        if self.pac in self.power_pellets:
            self.power_pellets.discard(self.pac)
            self.score += 5
            self.vuln_timer = POWER_DURATION

        # Ghost movement (every 2 ticks, skip frozen ghosts)
        if self.tick_count % 2 == 0:
            for gi in range(len(self.ghosts)):
                if self.ghost_frozen[gi] > 0:
                    continue
                gx, gy = self.ghosts[gi]
                best = None
                best_dist = float("inf")
                dirs = [(0, -1), (0, 1), (-1, 0), (1, 0)]
                random.shuffle(dirs)
                for ddx, ddy in dirs:
                    ngx = (gx + ddx) % self.cols
                    ngy = (gy + ddy) % self.rows
                    if (ngx, ngy) in self.walls:
                        continue
                    dist = abs(ngx - self.pac[0]) + abs(ngy - self.pac[1])
                    if self.vuln_timer > 0:
                        # Flee from pac-man when vulnerable
                        if dist > best_dist or best is None:
                            best_dist = dist
                            best = (ngx, ngy)
                    else:
                        if dist < best_dist:
                            best_dist = dist
                            best = (ngx, ngy)
                if best:
                    self.ghosts[gi] = best

        # Check pac-ghost collision
        for gi in range(len(self.ghosts)):
            if self.ghost_frozen[gi] > 0:
                continue
            if self.pac == self.ghosts[gi]:
                if self.vuln_timer > 0:
                    # Eat ghost — send to spawn, freeze
                    self.ghosts[gi] = self.ghost_spawns[gi]
                    self.ghost_frozen[gi] = GHOST_FROZEN_TICKS
                    self.score += 10
                else:
                    self.game_over = True
                    if self.score > self.high_score:
                        self.high_score = self.score
                    return

        # Win check: all dots AND power pellets eaten
        if not self.dots and not self.power_pellets:
            self.won = True
            self.game_over = True
            if self.score > self.high_score:
                self.high_score = self.score

    # ── INPUT ─────────────────────────────────────

    def handle_key(self, key):
        if self.game_over or not self.game_active:
            self.reset()
            self.render()
            return

        if self.is_sdplus:
            if key == 1:
                self.next_dir = (0, -1)   # up (button 2)
            elif key == 4:
                self.next_dir = (-1, 0)   # left (button 5)
            elif key == 5:
                self.next_dir = (0, 1)    # down (button 6)
            elif key == 6:
                self.next_dir = (1, 0)    # right (button 7)
        else:
            col = key % self.cols
            row = key // self.cols
            px, py = self.pac
            dx = col - px
            dy = row - py
            if abs(dx) >= abs(dy):
                self.next_dir = (1 if dx > 0 else -1, 0)
            else:
                self.next_dir = (0, 1 if dy > 0 else -1)

    def handle_dial(self, dial, event, value):
        if not self.is_sdplus:
            return
        if event == DialEventType.PUSH and value:
            if self.game_over or not self.game_active:
                self.reset()
                self.render()
            return
        if event == DialEventType.TURN:
            if not self.game_active or self.game_over:
                return
            # Dial 0-1: vertical, dial 2-3: horizontal
            if dial <= 1:
                self.next_dir = (0, 1 if value > 0 else -1)
            else:
                self.next_dir = (1 if value > 0 else -1, 0)

    # ── RENDER ────────────────────────────────────

    def render(self):
        if self.is_sdplus:
            self._render_screen()
            self._render_keys_sdplus()
        else:
            self._render_buttons()

    def _render_screen(self):
        sw, sh = self.screen_w, self.screen_h
        cs = self.cell
        img = Image.new("RGB", (sw, sh), (0, 0, 10))
        draw = ImageDraw.Draw(img)

        if not self.game_active:
            try:
                font = ImageFont.load_default(size=20)
                sfont = ImageFont.load_default(size=14)
            except TypeError:
                font = sfont = ImageFont.load_default()
            draw.text((sw // 2 - 50, 10), "PAC-MAN",
                      fill=COLOR_PAC, font=font)
            draw.text((sw // 2 - 60, 50), "Press dial to start",
                      fill=(150, 150, 200), font=sfont)
            if self.high_score:
                draw.text((sw // 2 - 40, 75),
                          f"HI: {self.high_score}",
                          fill=(200, 200, 100), font=sfont)
            set_screen(self.deck, img)
            return

        if self.game_over:
            try:
                font = ImageFont.load_default(size=22)
                sfont = ImageFont.load_default(size=14)
            except TypeError:
                font = sfont = ImageFont.load_default()
            if self.won:
                draw.text((sw // 2 - 30, 15), "WIN!",
                          fill=COLOR_WIN, font=font)
            else:
                draw.text((sw // 2 - 30, 15), "DEAD",
                          fill=COLOR_DEAD, font=font)
            draw.text((sw // 2 - 40, 55),
                      f"Score: {self.score}",
                      fill=(255, 255, 255), font=sfont)
            draw.text((sw // 2 - 50, 75), "Press dial to retry",
                      fill=(150, 150, 200), font=sfont)
            set_screen(self.deck, img)
            return

        # Draw walls
        for (c, r) in self.walls:
            x, y = c * cs, r * cs
            draw.rectangle([x, y, x + cs - 1, y + cs - 1],
                           fill=COLOR_WALL)

        # Draw dots
        for (c, r) in self.dots:
            x, y = c * cs + cs // 2, r * cs + cs // 2
            draw.ellipse([x - 2, y - 2, x + 2, y + 2],
                         fill=(200, 200, 255))

        # Draw power pellets (larger, pulsing)
        pulse = 4 if self.tick_count % 4 < 2 else 3
        for (c, r) in self.power_pellets:
            x, y = c * cs + cs // 2, r * cs + cs // 2
            draw.ellipse([x - pulse, y - pulse, x + pulse, y + pulse],
                         fill=COLOR_POWER)

        # Draw ghosts
        ghost_colors = [COLOR_GHOST, COLOR_GHOST2]
        for gi, (gc, gr) in enumerate(self.ghosts):
            if self.ghost_frozen[gi] > 0:
                # Frozen at spawn: dim, small
                gx, gy = gc * cs + cs // 4, gr * cs + cs // 4
                draw.ellipse([gx, gy, gx + cs // 2, gy + cs // 2],
                             fill=(40, 40, 60))
                continue
            gx, gy = gc * cs, gr * cs
            if self.vuln_timer > 0:
                # Vulnerable: blue, flashing near end
                if self.vuln_timer < 15 and self.tick_count % 2 == 0:
                    color = (255, 255, 255)
                else:
                    color = COLOR_VULN
            else:
                color = ghost_colors[gi % len(ghost_colors)]
            # Ghost body (rounded top, flat bottom)
            draw.rectangle([gx + 2, gy + cs // 3, gx + cs - 2,
                            gy + cs - 1], fill=color)
            draw.ellipse([gx + 2, gy + 1, gx + cs - 2,
                          gy + cs * 2 // 3], fill=color)
            # Eyes
            ew = cs // 5
            draw.ellipse([gx + cs // 3 - ew, gy + cs // 3 - ew,
                          gx + cs // 3 + ew, gy + cs // 3 + ew],
                         fill=(255, 255, 255))
            draw.ellipse([gx + cs * 2 // 3 - ew, gy + cs // 3 - ew,
                          gx + cs * 2 // 3 + ew, gy + cs // 3 + ew],
                         fill=(255, 255, 255))

        # Draw pac-man
        pc, pr = self.pac
        px, py = pc * cs + cs // 2, pr * cs + cs // 2
        rad = cs // 2 - 1
        # Mouth direction
        dx, dy = self.direction
        mouth_open = (self.tick_count % 2 == 0)
        if mouth_open:
            # Draw pac with mouth (pie shape)
            if dx == 1:
                start, end = 30, 330
            elif dx == -1:
                start, end = 210, 150
            elif dy == -1:
                start, end = 120, 60
            else:
                start, end = 300, 240
            draw.pieslice([px - rad, py - rad, px + rad, py + rad],
                          start, end, fill=COLOR_PAC)
        else:
            draw.ellipse([px - rad, py - rad, px + rad, py + rad],
                         fill=COLOR_PAC)

        # Score overlay
        try:
            sfont = ImageFont.load_default(size=12)
        except TypeError:
            sfont = ImageFont.load_default()
        draw.text((sw - 50, 2), f"{self.score}",
                  fill=(255, 255, 255), font=sfont)
        # Dots remaining
        draw.text((sw - 50, sh - 14), f"{len(self.dots)}",
                  fill=(150, 150, 200), font=sfont)

        set_screen(self.deck, img)

    def _render_keys_sdplus(self):
        total = self.btn_cols * self.btn_rows
        labels = {
            1: "UP", 4: "LEFT", 5: "DOWN", 6: "RGHT",
        }
        for key in range(total):
            if key in labels:
                set_key(self.deck, key, (40, 40, 80), labels[key])
            elif key == 0:
                set_key(self.deck, key, COLOR_SCORE,
                        f"S:{self.score}")
            elif key == 7:
                set_key(self.deck, key, COLOR_SCORE,
                        f"{len(self.dots)}")
            else:
                set_key(self.deck, key, COLOR_EMPTY, "")

    def _render_buttons(self):
        mid_c = self.cols // 2
        last_r = self.rows - 1

        if not self.game_active:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    set_key(self.deck, key, COLOR_PAC, "PAC")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "START")
                else:
                    set_key(self.deck, key, COLOR_DOT, ".")
            return

        if self.game_over:
            for key in range(self.cols * self.rows):
                r = key // self.cols
                c = key % self.cols
                if (c, r) == (mid_c, 0):
                    color = COLOR_WIN if self.won else COLOR_DEAD
                    text = "WIN!" if self.won else "DEAD"
                    set_key(self.deck, key, color, text)
                elif (c, r) == (mid_c, last_r // 2 if last_r > 1 else 1):
                    set_key(self.deck, key, COLOR_SCORE,
                            f"S:{self.score}")
                elif (c, r) == (mid_c, last_r):
                    set_key(self.deck, key, COLOR_TITLE, "AGAIN")
                else:
                    set_key(self.deck, key, COLOR_EMPTY, "")
            return

        # Build ghost position set with index
        ghost_map = {}
        for gi, gpos in enumerate(self.ghosts):
            if self.ghost_frozen[gi] <= 0:
                ghost_map[gpos] = gi

        for key in range(self.cols * self.rows):
            r = key // self.cols
            c = key % self.cols
            pos = (c, r)
            if pos == self.pac:
                set_key(self.deck, key, COLOR_PAC, "C")
            elif pos in ghost_map:
                if self.vuln_timer > 0:
                    color = COLOR_VULN
                    if self.vuln_timer < 15 and self.tick_count % 2 == 0:
                        color = (255, 255, 255)
                    set_key(self.deck, key, color, "G")
                else:
                    set_key(self.deck, key, COLOR_GHOST, "G")
            elif pos in self.walls:
                set_key(self.deck, key, COLOR_WALL, "")
            elif pos in self.power_pellets:
                set_key(self.deck, key, COLOR_POWER, "O")
            elif pos in self.dots:
                set_key(self.deck, key, COLOR_DOT, ".")
            elif key == self.cols * self.rows - 1:
                set_key(self.deck, key, COLOR_SCORE, str(self.score))
            else:
                set_key(self.deck, key, COLOR_EATEN, "")

    # ── GAME LOOP ─────────────────────────────────

    def game_loop(self):
        speed = TICK_SPEED_SCREEN if self.is_sdplus else TICK_SPEED_BUTTONS
        while self.running and self.deck.is_open():
            with self.lock:
                self.tick()
                self.render()
            time.sleep(speed)


def main():
    streamdecks = DeviceManager().enumerate()
    if not streamdecks:
        print("No Stream Deck found.")
        sys.exit(1)

    # Prefer SD+
    deck = None
    for d in streamdecks:
        if d.is_visual():
            if getattr(d, "DIAL_COUNT", 0) and d.DIAL_COUNT > 0:
                deck = d
                break
    if deck is None:
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

    is_sdplus = bool(
        getattr(deck, "DIAL_COUNT", 0) and deck.DIAL_COUNT > 0
    )
    rows, cols = deck.key_layout()
    print(f"Pac-Man on {deck.deck_type()} ({cols}x{rows})")
    if is_sdplus:
        print("SD+ mode: turn dials to steer, press dial to start")
        print("Dials 0-1 = up/down, dials 2-3 = left/right")
    else:
        print("Press buttons to steer. Eat dots, avoid ghost!")

    game = PacMan(deck)
    game.render()

    def key_cb(d, k, s):
        if not s:
            return
        with game.lock:
            game.handle_key(k)

    deck.set_key_callback(key_cb)

    if is_sdplus:
        def dial_cb(d, dial, evt, val):
            with game.lock:
                game.handle_dial(dial, evt, val)
        deck.set_dial_callback(dial_cb)

    t = threading.Thread(target=game.game_loop, daemon=True)
    t.start()

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
        print(f"\nScore: {game.score} | High: {game.high_score}")



if len(sys.argv) > 1 and sys.argv[1] == "--meta":
    import json as _json
    print(_json.dumps(GAME_META))
    sys.exit(0)


if __name__ == "__main__":
    main()
