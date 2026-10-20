
# ERPLibre Stream Deck

Suite of tools and games for the Elgato Stream Deck, integrated into the ERPLibre project.

All scripts auto-adapt to any Stream Deck model (Mini, Original, MK.2, XL, Plus, Neo) via `deck.key_layout()`.

## Prerequisites


```bash
# System dependencies / Dépendances système
sudo apt install -y libudev-dev libusb-1.0-0-dev libhidapi-libusb0

# udev rules (non-root access) / Règles udev (accès non-root)
sudo tee /etc/udev/rules.d/70-streamdeck.rules << 'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger

# Python dependencies / Dépendances Python
pip install -r script/stream_deck/requirements.txt
```


## Utility scripts

### erplibre_controller.py

Main Stream Deck controller for ERPLibre. Handles physical buttons with assigned actions:

| Button | Action |
|--------|--------|
| 0 | Launch `todo.py` (interactive ERPLibre CLI) |
| 1 | Brightness + |
| 2 | Brightness - |
| 3 | Launch `keyboard_talk.py` (keyboard automation) |
| 4 | Reset Stream Deck |
| 5 | Cycle display mode: Animation -> Big image -> Webcam |

Supports the Stream Deck Plus (touchscreen, dials), USB hotplug detection (pyudev), and GIF animations.


```bash
make streamdeck
```


### keyboard_talk.py

Keyboard automation script. Uses `wmctrl` to target a terminal window, then sends an automated key sequence via the `keyboard` library.

### GNOME Shell extension

The `script/gnome-extension/erplibre_home/` directory ships a six-indicator panel button (controller,
pencil, film, ERPLibre, network, device) plus the tiling D-Bus interface used by
the Python helpers. See [`../gnome-extension/erplibre_home/README.md`](../gnome-extension/erplibre_home/README.md).


## Deck program

`script/stream_deck/erplibre_streamdeck/` is the deck program of ERPLibre Home (`DECK_PROGRAM=tiler`, `make streamdeck_erplibre`). It is a package run as a directory: a small kernel owns the deck, the lock, the flash, the home screen and the key dispatch, and every feature is a plugin.


```bash
python script/stream_deck/erplibre_streamdeck
python script/stream_deck/erplibre_streamdeck --list-plugins
python script/stream_deck/erplibre_streamdeck --help
```


`--list-plugins` prints what the loader finds (one line per plugin: `active`, `off`, `replaced by user` or `refused` with its reason; `unreadable` for a plugin directory it cannot list) without opening the deck or taking its lock. `-h` and `--help` print the usage, the settings file and the exit codes (2: deck lock held or bad option, 3: no Stream Deck with a screen, 143: SIGTERM), then exit 0; any other argument prints the usage on stderr and exits 2. Neither takes the lock nor needs the Stream Deck library. Layout of the package:


```
erplibre_streamdeck/
├── __main__.py   # entry point, --help, --list-plugins / point d'entrée
├── app.py        # build(): settings, plugins, kernel / assemblage
├── kernel.py     # deck, lock, flash, loop, dispatch / noyau
├── home.py       # home screen: buttons, fixtures, tiles / accueil
├── loader.py     # discovery of the plugins / découverte
├── plugin.py     # Plugin, Page, HomeButton, Fixture, TileProvider
├── context.py    # Context, the one object a plugin receives
├── paths.py, settings.py, dbus.py
├── ui/           # rendering, colours, i18n / rendu, couleurs, i18n
└── plugins/      # a11y, bluetooth, claude_sessions, dev_reload,
                  # layouts, mpv_sessions, sound, tiling, timers,
                  # todo_terminals, translate
```


### Turning plugins off

The setting `DECK_PLUGINS_OFF` in `streamdeck.conf` is a comma-separated list of plugin ids that are not imported. Set it from TODO › Stream Deck › Plugins on/off, or by hand. A plugin that raises on import, has no `PLUGIN`, declares another `api` than `PLUGIN_API`, takes a page id already taken, or fails in `setup` is refused and the others keep running; the journal names the plugin and the reason.


```
DECK_PLUGINS_OFF=bluetooth,translate
```


### Writing a plugin

A plugin is one `.py` file. Its id is its file stem (`[a-z][a-z0-9_]*`; files starting with `_` are skipped) and it exposes `PLUGIN = Plugin(api=PLUGIN_API, ...)`. Every callable receives a `Context` (`ctx`) and runs with the kernel lock held. This plugin adds a home button and one page with a back key:


```python
from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Page, Plugin,
)


def _keys(geo):
    return {"back": 0} if geo.cols >= 2 else None


def _render(ctx):
    for key in range(ctx.geo.total_keys):
        ctx.set_key(key, (20, 20, 30))
    ctx.set_key(0, (60, 60, 60), ctx.t("BACK"))


def _handle(ctx, key):
    if key == 0:
        ctx.home()


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[Page("hello", _keys, _render, _handle)],
    home_button=HomeButton(
        90,
        face=lambda ctx: KeyFace((30, 90, 60), "HELLO"),
        press=lambda ctx: ctx.goto("hello"),
    ),
)
```


A `Plugin` also takes `fixtures` (keys placed on the home screen), `tiles` (dashboard tiles), `home_tick`, `setup(ctx)` and `shutdown(ctx)`; `plugin.py` documents each. `shutdown` runs with the lock held (without it when a key press still holds it after 5 s): it must not take `ctx.locked()` nor wait for a thread that does. A thread a plugin starts takes the lock with `with ctx.locked():`.

A plugin of the user goes in `$XDG_CONFIG_HOME/erplibre-home/deck-plugins/` (`~/.config/erplibre-home/deck-plugins/` when unset), and replaces a plugin of the repository with the same id. **Trust:** user plugins run inside the deck service with the user's rights, like a shell profile; put there only code you wrote or read.


#### Slow actions, polls and settings

A callable runs with the lock held, so it must not wait on a process. `ctx.run_blocking(work, then=None)` runs `work()` in a thread, without the lock, and returns `True`:

- `work` takes no argument and touches only what it captured before the call, plus `ctx.dbus` and `ctx.log`; never `ctx` itself.
- The pressed key shows "…" while the job runs and the rest of the deck stays usable.
- On the next loop pass, under the lock, the kernel calls `then(ctx, result, error)` (`error` is the exception `work` raised, or `None`). `then` renders itself, like a handler. Without `then`, the kernel flashes OK when `error` is `None` and the result is truthy, ERR otherwise, and renders.
- A plugin has one job at a time: `run_blocking` while one runs returns `False` and flashes ERR. A press that would reach a busy plugin flashes ERR without calling it; key 0 of its page (BACK on most pages) goes home instead. Its polls and ticks wait.
- A job that raises is journaled once, with its traceback, before `then` runs.

`Plugin.polls` is a list of `Poll(period, active, read, store)`. A render reads `ctx.state()` and starts no process; a poll fills that state:

- `active(ctx)` (lock held) says whether the data is needed now, for example because the plugin's page shows.
- `read()` (no lock) runs the processes and returns the data. It never touches `ctx`; a failing `read` keeps the previous data.
- A `read` that writes its own failures wraps its pass in `with repeat_log.watch() as log:`, where `repeat_log = RepeatLog(write, what)` is created once with the module: `log(msg)` records a failure, written once while it repeats on every pass, again when it changes, and `what: recovered` is written on the first pass without failure. A pass that comes more than `RepeatLog.FORGET_SEC` (10 s) after the last one, the poll having been inactive, starts afresh: its failures are written again.
- `store(ctx, data)` (lock held) keeps the data in `ctx.state()` and returns `True` to ask for one render.

`ctx.setting(name, default=None)` reads a deck setting given to the kernel at start (`session_refresh_sec`, from `DECK_SESSION_REFRESH_SEC`), or `default`. A render may run before the first poll ends: set the state in `setup(ctx)`. This plugin runs a job on a key press and shows a counter that a poll refreshes:


```python
import subprocess

from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Page, Plugin, Poll,
)


def _setup(ctx):
    ctx.state().lines = 0


def _keys(geo):
    return {"back": 0, "run": 1} if geo.total_keys > 1 else None


def _render(ctx):
    for key in range(ctx.geo.total_keys):
        ctx.set_key(key, (20, 20, 30))
    ctx.set_key(0, (60, 60, 60), ctx.t("BACK"))
    ctx.set_key(1, (30, 90, 60), f"RUN\n{ctx.state().lines}")


def _work():
    # no ctx, no lock / ni ctx, ni verrou
    done = subprocess.run(["uptime"], capture_output=True, timeout=5)
    return done.returncode == 0


def _then(ctx, result, error):
    ctx.flash(error is None and result)
    ctx.render()


def _handle(ctx, key):
    if key == 0:
        ctx.home()
    elif key == 1:
        ctx.run_blocking(_work, _then)


def _read():
    done = subprocess.run(["uptime"], capture_output=True, timeout=5)
    return len(done.stdout.splitlines())


def _store(ctx, lines):
    changed = ctx.state().lines != lines
    ctx.state().lines = lines
    return changed


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[Page("hello", _keys, _render, _handle)],
    home_button=HomeButton(
        90,
        face=lambda ctx: KeyFace((30, 90, 60), "HELLO"),
        press=lambda ctx: ctx.goto("hello"),
    ),
    polls=[Poll(2.0, lambda ctx: ctx.page == "hello", _read, _store)],
    setup=_setup,
)
```


## Games

19 games playable directly on the Stream Deck. 11 support 2-player mode with two Stream Decks (auto-detection).

### Arcade

#### Snake

Classic. The snake grows by eating food. Speed increases with score. Wrap-around at edges.

- **Controls**: press any button to turn the snake toward that direction
- **2 players**: two snakes (green/blue) on the same grid. Collision with the other = death


```bash
make streamdeck_snake
```


#### Breakout

Brick breaker rotated 90 degrees. Bricks on the left, paddle on the right, ball bounces horizontally.

- **Controls**: press the right column to place the paddle, or anywhere to move it


```bash
make streamdeck_breakout
```


#### Flappy Bird

The bird moves left to right, obstacles (pipes) scroll. Gravity pulls the bird downward.

- **Controls**: press any button to rise one cell


```bash
make streamdeck_flappy
```


#### Pong

Classic Pong rotated 90 degrees. Left paddle vs right paddle. First to 5 points wins.

- **1 player**: left column = you, right = AI
- **2 players**: each deck controls a paddle, press to place it at that line


```bash
make streamdeck_pong
```


#### Bomberman

Move your character, drop bombs, destroy walls. Don't blow yourself up!

- **Controls**: press adjacent to move, press your position to drop a bomb (3s delay)
- **2 players**: P1 (blue) and P2 (orange) on the same grid. Last alive wins


```bash
make streamdeck_bomberman
```


### Reflex

#### Whack-a-Mole

Moles appear randomly for 30 seconds. Whack them! Speed increases with score. 3 second cooldown at end of game to view score.

- **2 players**: same moles on both decks, separate scores. Highest wins


```bash
make streamdeck_whackamole
```


#### Reaction Time

A green button lights up after a random delay. Tap it as fast as possible! 5 rounds, time in milliseconds.

- **2 players**: same target, the fastest wins each round. Average compared at the end


```bash
make streamdeck_reaction
```


### Memory

#### Simon Says

The deck plays a light sequence. Reproduce it in order. The sequence grows with each turn.

- **2 players**: same sequence on both decks. First one to make a mistake loses


```bash
make streamdeck_simon
```


#### Color Match

Memory pair game. Flip two cards: if they are the same color, they stay revealed. Find all pairs.

- **2 players**: same board, each flips on their deck. Player with most pairs wins


```bash
make streamdeck_colormatch
```


### Puzzle

#### Minesweeper

Classic Minesweeper with flag animation (yellow progressive bar on long-press).

- **Controls**: short press = reveal, long press (0.6s) = place/remove flag, press a number = chord (reveal neighbors if flags are correct)
- **2 players (VS Mine Hunter)**: rules reversed! Find mines to score. Mine = +1 + keep your turn. Safe cell = opponent's turn. Flood-fill on empty cells. Player with most mines found wins
- **Parameters**: `-m N` to change mine count, `-v` to display parameters


```bash
make streamdeck_minesweeper           # auto (25% solo, 35% VS)
./script/stream_deck/games/game_minesweeper.py -m 6      # 6 mines
./script/stream_deck/games/game_minesweeper.py -v         # show params / afficher paramètres
```


#### Lights Out

Press a button to toggle it and its 4 neighbors. Turn off all lights to win.

- **2 players (coop)**: shared grid! Both players act on the same board


```bash
make streamdeck_lightsout
```


#### 2048

Merge tiles of equal value to reach 2048. Distinct colors per value.

- **Controls**: corners = directions (top-left=up, top-right=right, bottom-left=left, bottom-right=down). Or press the left/right half to go in that direction


```bash
make streamdeck_2048
```


#### Taquin (Sliding Puzzle)

Numbered tiles to put back in order (1->N) by sliding them toward the empty cell. N = number of buttons - 1.

- **Controls**: press a tile adjacent to the empty cell to move it


```bash
make streamdeck_taquin
```


#### Sokoban

Push boxes (B) onto targets (X). All boxes on targets = victory.

- **Controls**: press adjacent to move. If a box is in front, it gets pushed


```bash
make streamdeck_sokoban
```


#### Flood Fill

The grid has random colors. Pick a color in the bottom row to flood-fill from the top-left corner. Fill the whole grid in a limited number of moves.

- **2 players**: same starting grid, each plays independently. First to fill wins


```bash
make streamdeck_floodfill
```


### Strategy / Deduction

#### Battleship

Naval battle. Ships are hidden. Shoot to find them.

- **1 player**: solo grid, find all ships
- **2 players**: each deck = private attack grid. Hit = keep your turn. Miss = opponent's turn. Sunken ships in dark red. Ships revealed at end of game


```bash
make streamdeck_battleship
```


#### Mastermind

Guess the secret color code. Bottom row = your guess (press to cycle colors). Top-right = submit. Feedback after each guess: E = exact (right color, right place), P = partial (right color, wrong place).


```bash
make streamdeck_mastermind
```


#### Tic-Tac-Toe

Classic noughts and crosses on a 3x3 grid centered on the deck.

- **1 player**: hot seat, players alternate on the same deck
- **2 players**: each deck = one player (X or O). Only the active player's deck accepts input. The other displays "WAIT"


```bash
make streamdeck_tictactoe
```


#### Wordle

Guess a 5-letter word. Bottom row = letters (press to cycle A-Z). Last button = submit. Green = right letter right place, yellow = right letter wrong place, gray = absent. 6 attempts.


```bash
make streamdeck_wordle
```


#### Checkers

Simplified checkers. Select a piece then press the destination. Diagonal moves. Jump to capture.

- **2 players**: red vs blue, each on their own deck


```bash
make streamdeck_checkers
```


#### Reversi / Othello

Place pieces to flip the opponent's. Most pieces at the end wins.

- **1 player**: vs AI (simple strategy)
- **2 players**: black vs white


```bash
make streamdeck_reversi
```


### Arcade (continued)

#### Pac-Man

Eat all the dots. Avoid the ghost! Press to change direction. The ghost chases you.


```bash
make streamdeck_pacman
```


#### Space Invaders

The aliens descend. You are on the bottom row. Press your position to shoot, press adjacent to move.


```bash
make streamdeck_spaceinvaders
```


#### Frogger

Cross the road. Cars scroll by. Hop from cell to cell to reach the top!


```bash
make streamdeck_frogger
```


#### Tetris

Pieces fall right to left (rotated 90 degrees). Top row = rotate, bottom = drop, middle = move.


```bash
make streamdeck_tetris
```


#### Tower Defense

Enemies cross the middle row. Place towers above/below to take them out. Survive 5 waves!


```bash
make streamdeck_towerdefense
```


### Word / Guess

#### Hangman

Each button = a letter. Press to guess. 6 mistakes = game over.


```bash
make streamdeck_hangman
```


#### Number Guess

Guess a number 1-100. Buttons display values. Colors = hot/cold. Fewer attempts = better score.


```bash
make streamdeck_numberguess
```


#### Rock Paper Scissors

3 buttons: rock, paper, scissors. Best of 5.

- **2 players**: simultaneous choice, reveal!


```bash
make streamdeck_rps
```


### Puzzle (continued)

#### Sudoku 3x3

Simplified 3x3 grid centered on the deck. Press to cycle digits. No repetitions in rows/columns.


```bash
make streamdeck_sudoku
```


#### Maze Runner

Randomly generated maze. Navigate from top-left corner to bottom-right. Press adjacent cells to move.


```bash
make streamdeck_maze
```


### Simulation

#### Game of Life

Conway's cellular automaton. Cells live or die based on their neighbors. Wrap-around at edges.

- **Controls**: press to toggle a cell. Top-left = play/pause. Top-right = randomize. Bottom-right = clear


```bash
make streamdeck_life
```


#### Langton's Ant

Cellular automaton: an ant moves on the grid. On white -> turn right + black. On black -> turn left + white. Emerging patterns!


```bash
make streamdeck_langton
```


### Stream Deck + (dials + touchscreen)

#### Safe Cracker

Turn the 4 dials to guess a 4-digit combination. Hot/cold bars on the touchscreen. Click = lock.


```bash
make streamdeck_safecracker
```


#### Slot Machine

Click a dial to spin all reels. Click each dial to stop its reel. 3 identical = jackpot!


```bash
make streamdeck_slots
```


#### Color Mixer

3 dials = Red, Green, Blue. Mix to match the target color displayed on the touchscreen. Dial 4 = submit.


```bash
make streamdeck_colormixer
```


#### Pong+

Pong on the 800x100px touchscreen! Dial = paddle. Ball bounces. 2 Stream Deck+ = 2 players!


```bash
make streamdeck_pong
```


#### DJ Scratch

Turn the dials to scratch vinyl. Animated waveforms on the touchscreen. Click = change style (sine/square/saw/noise).


```bash
make streamdeck_djscratch
```


#### Fishing

Click dial = cast. When the fish bites (touchscreen flash), turn to reel in! Too fast = the line breaks.


```bash
make streamdeck_fishing
```


#### Piano

Bottom row = piano keys (C D E F G A B). Dial 1 = change octave. Colors per note on the touchscreen.


```bash
make streamdeck_piano
```


#### Thermometer

Turn the dial to guess the secret temperature. Thermometer bar on the touchscreen with hot/cold gradient.


```bash
make streamdeck_thermometer
```


## Game roundup (42 titles)

| Game | Command | Type | Multi |
|-----|----------|------|-------|
| Snake | `make streamdeck_snake` | Arcade | 2P VS |
| Breakout | `make streamdeck_breakout` | Arcade | - |
| Flappy Bird | `make streamdeck_flappy` | Arcade | - |
| Pong | `make streamdeck_pong` | Arcade / SD+ | 2P VS |
| Bomberman | `make streamdeck_bomberman` | Arcade | 2P VS |
| Pac-Man | `make streamdeck_pacman` | Arcade | - |
| Space Invaders | `make streamdeck_spaceinvaders` | Arcade | - |
| Frogger | `make streamdeck_frogger` | Arcade | - |
| Tetris | `make streamdeck_tetris` | Arcade | - |
| Tower Defense | `make streamdeck_towerdefense` | Arcade | - |
| Whack-a-Mole | `make streamdeck_whackamole` | Reflex | 2P VS |
| Reaction Time | `make streamdeck_reaction` | Reflex | 2P VS |
| Simon Says | `make streamdeck_simon` | Memory | 2P VS |
| Color Match | `make streamdeck_colormatch` | Memory | 2P VS |
| Minesweeper | `make streamdeck_minesweeper` | Puzzle | 2P VS |
| Lights Out | `make streamdeck_lightsout` | Puzzle | 2P Coop |
| 2048 | `make streamdeck_2048` | Puzzle | - |
| Taquin | `make streamdeck_taquin` | Puzzle | - |
| Sokoban | `make streamdeck_sokoban` | Puzzle | - |
| Flood Fill | `make streamdeck_floodfill` | Puzzle | 2P VS |
| Sudoku 3x3 | `make streamdeck_sudoku` | Puzzle | - |
| Maze Runner | `make streamdeck_maze` | Puzzle | - |
| Battleship | `make streamdeck_battleship` | Strategy | 2P VS |
| Mastermind | `make streamdeck_mastermind` | Deduction | - |
| Tic-Tac-Toe | `make streamdeck_tictactoe` | Strategy | 2P VS |
| Connect 4 | `make streamdeck_connect4` | Strategy | 2P VS |
| Checkers | `make streamdeck_checkers` | Strategy | 2P VS |
| Reversi | `make streamdeck_reversi` | Strategy | 2P VS |
| Wordle | `make streamdeck_wordle` | Word | - |
| Hangman | `make streamdeck_hangman` | Word | - |
| Number Guess | `make streamdeck_numberguess` | Guess | - |
| Rock Paper Scissors | `make streamdeck_rps` | Quick | 2P VS |
| Game of Life | `make streamdeck_life` | Simulation | - |
| Langton's Ant | `make streamdeck_langton` | Simulation | - |
| Safe Cracker | `make streamdeck_safecracker` | SD+ Puzzle | - |
| Slot Machine | `make streamdeck_slots` | SD+ Arcade | - |
| Color Mixer | `make streamdeck_colormixer` | SD+ Puzzle | - |
| DJ Scratch | `make streamdeck_djscratch` | SD+ Music | - |
| Fishing | `make streamdeck_fishing` | SD+ Arcade | - |
| Piano | `make streamdeck_piano` | SD+ Music | - |
| Thermometer | `make streamdeck_thermometer` | SD+ Guess | - |

## Files


```
script/stream_deck/
├── README.md                  # English / Anglais
├── README.fr.md               # French / Français
├── INSTALL.md                 # Dependency install guide / Guide d'installation
├── plan.md                    # StreamController integration plan / Plan d'intégration
├── requirements.txt           # Python dependencies / Dépendances Python
├── Assets/                    # Controller images and fonts / Images et polices
├── erplibre_controller.py     # Main ERPLibre controller / Contrôleur principal
├── erplibre_streamdeck/       # Deck program package (plugins) / Paquet du deck
├── keyboard_talk.py           # Keyboard automation / Automatisation clavier
└── games/                     # Games, gallery, saves / Jeux, galerie, sauvegardes
    ├── game_*.py              # 45 games / 45 jeux
    ├── gallery_server.py      # Game gallery / Galerie des jeux
    ├── index.html             # Gallery page / Page de la galerie
    └── save/                  # Game saves / Sauvegardes des jeux
```

The GNOME Shell extension lives in `script/gnome-extension/erplibre_home/`. /
L'extension GNOME Shell vit dans `script/gnome-extension/erplibre_home/`.


## License

AGPL-3.0 — [TechnoLibre](http://www.technolibre.ca)
