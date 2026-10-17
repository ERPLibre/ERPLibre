# ERPLibre Home: deck service and Stream Deck menu

**Status:** design, awaiting review.
**Builds on:** `2026-10-13-streamdeck-deployment-design.md` (implemented:
`install_erplibre_home.sh` with its base and `--stream-deck` levels, the
TODO entries, the QEMU tools, the long test).

## Goal

A Stream Deck is driven by one program at a time. The program a user wants
running by default is the **window tiler** (`script/stream_deck/game_tiler.py`):
it tiles windows through the ERPLibre Home extension, lists timers and Claude
sessions, and controls sound and Bluetooth. Games take the deck for a while
and give it back.

This design adds:

- a `systemd --user` service that runs the chosen deck program, optionally at
  login;
- the choices an install offers: which program, autostart, restart after a
  game, optional tools;
- the hand-over between the service and a game, so the two never fight over
  the deck;
- one **Stream Deck** submenu in TODO that gathers the games, both installs,
  the service, a status view and a diagnosis.

Success means: after `install_erplibre_home.sh --stream-deck --autostart`, a
login with a deck plugged in brings the tiler up on the deck; opening a game
from TODO or from the gallery stops the tiler, and closing the game brings it
back; TODO shows in one screen what is installed and what runs.

## Out of scope

- The base level gets no service: it runs no process of its own (the
  extension lives inside GNOME Shell). A base service comes when a base
  process exists.
- Starting the service when a deck is plugged in after login (a udev
  `SYSTEMD_USER_WANTS`). The service starts at login when a deck is present;
  hot-plug is a later addition.
- Splitting `game_tiler.py` into `stream_deck_game.py` and domain modules
  (the separate project B). The service names its program through a setting,
  so that rename changes one value.
- The QEMU menu's desktop path failing on Fedora 42/44 and on
  AlmaLinux/Rocky 10: a separate fix.

## Names

| Element | Value |
|---|---|
| Unit | `erplibre-home-streamdeck.service`, in `~/.config/systemd/user/` |
| Settings | `~/.config/erplibre-home/streamdeck.conf` (`$XDG_CONFIG_HOME` honoured) |
| Service entry point | `script/install/erplibre_home_deck.sh` |
| Hand-over helper | `script/install/erplibre_home_handover.sh` |
| Deck lock | `$XDG_RUNTIME_DIR/erplibre-home/deck.lock` |

## Settings file

Plain `KEY=value` lines, read by the entry point, the hand-over helper and
TODO; written by the installer and by TODO:

```
DECK_PROGRAM=tiler
RESTART_AFTER_GAME=yes
```

- `DECK_PROGRAM`: `tiler` (`script/stream_deck/game_tiler.py`, the default),
  `controller` (`script/stream_deck/erplibre_controller.py`), or `none`.
- `RESTART_AFTER_GAME`: `yes` (default) or `no`.
- A missing file or key means the default. An unknown value is a usage error
  of whoever wrote it; the entry point refuses it with one line and exit 1.

## The unit

Written by the installer at the Stream Deck level, with the absolute path of
the checkout the install runs from (so the service runs that checkout's code,
whichever checkout it is):

```
[Unit]
Description=ERPLibre Home Stream Deck program
PartOf=graphical-session.target
After=graphical-session.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=<checkout>
Environment=PYTHONUNBUFFERED=1
ExecCondition=<checkout>/script/install/erplibre_home_deck.sh --check
ExecStart=<checkout>/script/install/erplibre_home_deck.sh
Restart=on-failure
RestartSec=3
RestartPreventExitStatus=2 3
SuccessExitStatus=143
TimeoutStopSec=10

[Install]
WantedBy=graphical-session.target
```

- `<checkout>` is written with systemd's quoting so a path with spaces works.
  `$` is written as is: systemd expands variables only in the arguments of
  an `Exec*` line, and the checkout is only ever the executable's path or
  `WorkingDirectory`.
- `--check` exits 0 when a program is configured (`DECK_PROGRAM` is not
  `none`), `.venv.streamdeck/bin/python` exists and a deck is present (a USB
  device of vendor `0fd9` under `/sys/bus/usb/devices/*/idVendor`); otherwise
  non-zero, so systemd skips the start instead of looping on a program that
  exits at once without a deck.
- `ExecStart` `exec`s `.venv.streamdeck/bin/python <program>`; the program
  takes the deck lock itself (below). `flock` locks belong to an open file
  description, so the entry point must not take it too: the program's own
  attempt would then fail against its parent's descriptor.
- `Restart=on-failure` brings the program back after a crash; an unplugged
  deck makes the restart fail its `ExecCondition`, and the unit rests.
  Exit 2 (deck lock taken) and 3 (the tiler finds no visual deck, as with
  another Elgato device of vendor `0fd9`) are not restarted. Any other
  persistent failure ends in `failed` after five starts in 60 s; systemd's
  default limit (5 in 10 s) is never reached with `RestartSec=3`.
- On SIGTERM (`systemctl stop`) the tiler and the controller reset the
  deck and exit 143, which `SuccessExitStatus` counts as a clean stop.
  `TimeoutStopSec=10` bounds that stop: a program stuck in its cleanup is
  killed after 10 s instead of systemd's default 90 s, so a game's
  hand-over never waits long for the deck.

## Installer

New options, all at the Stream Deck level (with `--stream-deck`; given
without it they are a usage error, exit 1):

| Option | Effect |
|---|---|
| `--deck-program=tiler\|controller\|none` | written to `DECK_PROGRAM` (default `tiler`) |
| `--autostart` | `systemctl --user enable` the unit (default: not enabled) |
| `--no-restart-after-game` | `RESTART_AFTER_GAME=no` (default `yes`) |

`--with-extras` keeps its meaning (optional tools, base level).

- `--stream-deck` writes the settings file (keeping keys the options do not
  set), writes the unit, runs `systemctl --user daemon-reload`, and enables it
  only with `--autostart`. It never starts it: the program needs the
  extension loaded, which a fresh install gets at the next login.
- Without a user manager reachable (an install over ssh with no session), the
  unit file is written and `daemon-reload`/`enable` are run under the
  session-bus rule the installer already uses; a failure there is reported,
  not fatal, and the summary says to run `systemctl --user enable
  erplibre-home-streamdeck.service` after login.
- `--uninstall --stream-deck` and `--uninstall`: stop, disable and remove the
  unit, `daemon-reload`, remove the settings file.
- `--dry-run` prints the unit path, the settings it would write and whether
  it would enable the unit.
- Idempotent: a second identical run leaves the unit and settings untouched.

## Deck lock and hand-over

Two deck programs opened together fight over the same HID device. The lock
makes that visible instead of silent.

- `game_tiler.py` and `erplibre_controller.py` take
  `$XDG_RUNTIME_DIR/erplibre-home/deck.lock` with `fcntl.flock(…, LOCK_EX |
  LOCK_NB)` at start; when another process holds it, they print which
  program holds it (its PID, read from the lock file) and exit 2.
- `erplibre_home_handover.sh <command…>` runs a game:
  1. if `erplibre-home-streamdeck.service` is active, or `activating`
     while it waits to restart, stop it and remember;
  2. run the command in the foreground under the deck lock, held as `game`
     for the command's whole run by `python3 deck_lock.py game <command…>`,
     keeping its exit code;
  3. if it was active and `RESTART_AFTER_GAME=yes`, reset its start counter
     (`reset-failed`) and start it again;
  4. exit with the game's code.
- While a game runs, the service's own start (from the panel, TODO's
  Service menu or the command Diagnosis suggests) therefore fails cleanly
  with exit 2, and Status names `game` as the holder. The lock's file
  descriptor passes to the game (`pass_fds`) and to every process it
  starts without closing its descriptors: the deck stays taken while any
  of the game's processes runs, even once the wrapper is gone, so a child
  the game leaves behind keeps the deck. A deck program started as a game
  (the tiler is in the games list) holds the lock through the inherited
  descriptor; one started with its descriptors closed finds an ancestor
  holding the lock as `game`, runs under it, and takes the lock over when
  the game releases it.
- The lock's text is `<PID> <program> <start>`, where `<start>` is the
  holder's process start time (field 22 of `/proc/<PID>/stat`). The third
  field is optional: a text without it still parses, and keeps the older
  rules. The ancestor check above accepts the PID only when that ancestor's
  start time matches the text's: a deck program that outlives its wrapper
  leaves the text naming a dead PID, and an unrelated ancestor that reuses
  that PID is not taken for the game.
- SIGTERM or SIGINT sent to the wrapper reaches every descendant (a game
  under the gallery's bash loop is a grandchild), except, for SIGINT, the
  processes in the terminal's foreground that Ctrl-C already hit; the
  wrapper then waits for them all before it exits. Diagnosis advises to
  close the game first, and, as a last resort, `kill` on every process that
  holds the lock, since the wrapper the lock names may already be dead.
- Status and Diagnosis read the main lock only. When the PID the lock
  names no longer designates its writer (gone, or its start time differs),
  Status marks it "no longer running" and Diagnosis never offers `kill` on
  it: it offers the processes that hold the lock instead, or only "close
  it" / "close the game" when it finds none.
- TODO's games menu and the gallery's launcher (`gallery_server.py`, the bash
  line built by `_game_bash_cmd`) run each game through the helper. The
  gallery's restart loop ("r" + Enter) stays inside one hand-over, so the
  tiler comes back once, when the player leaves.
- Without the unit (base level, or a manual setup), the helper only runs the
  command.

## The Stream Deck submenu

`[17]` becomes one entry, **Stream Deck**, opening:

```
[1] Games
[2] Status
[3] Service: start / stop / restart / live log
[4] Deck program: tiler / controller / none
[5] Autostart: enable / disable
[6] Diagnosis
[7] Install ERPLibre Home (local)
[8] Install ERPLibre Home Stream Deck (local)
[9] Uninstall: Stream Deck level / everything
[10] Extension: reload / preferences
```

Entries `[18]` and `[19]` of `Execute` disappear; their two install methods
move under `[7]` and `[8]` unchanged in behaviour, with these questions for
`[8]` before it runs the installer (each answer becomes an option, and the
command is printed before it runs):

- deck program: tiler (default) / controller / none;
- autostart at login: no (default) / yes;
- restart the program after a game: yes (default) / no;
- optional tools (`--with-extras`): no (default) / yes.

- **Status** prints, one line each: the level installed (none / base /
  Stream Deck), the extension (`GetExtensionInfo` state and error), the
  indicators (the journal's `enabled` line and any `mount … failed`), the
  unit (installed, enabled, active, program from the settings), the deck
  lock holder, the decks plugged in (vendor `0fd9`, model when known), the
  udev rule, the venv.
- **Diagnosis** runs the same probes and, for each one that is not as
  expected, prints the command that fixes it (for example
  `make erplibre_home_streamdeck_install`, `systemctl --user enable …`,
  "log out and back in").
- **Service** and **Autostart** call `systemctl --user` and show its
  output; the live log is `journalctl --user -u
  erplibre-home-streamdeck.service -f` until Ctrl-C.
- **Deck program** rewrites `DECK_PROGRAM` and restarts the unit when it was
  active.
- **Extension** runs `make erplibre_home_reload` or `gnome-extensions prefs
  erplibre-home@technolibre.ca`.
- Every label and message has French and English keys in `todo_i18n.py`;
  `test/test_todo_menu.py` follows the new structure.

## Extension

The `device` indicator's "Start deck program" action starts the unit with
`systemctl --user start erplibre-home-streamdeck.service` when the unit file
exists, and keeps its current direct launch otherwise. Its "Restart deck"
action restarts the unit in the same case. A start that `ExecCondition`
skips exits 0, and with `Type=simple` a program that finds the deck busy or
no visual deck exits after `systemctl` returns. Both actions therefore read,
without blocking the shell, the unit's `ActiveState`, `SubState`, `Result`,
`ExecMainCode` and `ExecMainStatus` 1.5, 3, 5 and 8 s after the start. The
series stops at the first read where no program runs and the unit is not
deactivating; a program still running at 8 s counts as started, and so does
a program seen running whose unit then stops with `Result=success` (a
hand-over to a game, a restart click). The gaps never exceed `RestartSec=3`,
so a crash loop is seen in its restart wait. When no program runs, the
notice says why: the program holding the deck (from the lock's text), no
visual Stream Deck (exit 3), the line the entry point's `--check` prints for
a skipped start (`Result=exec-condition`) or, when it prints none, the unmet
start condition with its three causes, or the state and exit status of a
program that failed or waits for its restart (`SubState=auto-restart`, or
`auto-restart-queued` from systemd 254 on). The other indicators are
unchanged.

## Testing

- **Unit (fast, no VM, fakes on `PATH` and a temporary `HOME`):**
  - the generated unit text: absolute paths, quoting of a path with spaces,
    `ExecCondition`, `WantedBy`;
  - the installer options: settings written and kept, enable only with
    `--autostart`, usage errors without `--stream-deck`, dry-run lines,
    idempotence, both uninstalls remove unit and settings;
  - `erplibre_home_deck.sh --check` on each condition, and the program it
    `exec`s for each `DECK_PROGRAM`, with a fake venv python;
  - the lock: a second holder exits 2 and names the first; the text
    carries the holder's start time, and an ancestor reusing a dead
    wrapper's PID is not taken for the game;
  - the hand-over: stops and restarts an active fake unit, keeps a stopped
    one stopped, honours `RESTART_AFTER_GAME=no`, returns the game's code;
  - the submenu numbering, i18n keys, the install questions turning into
    options, the status and diagnosis lines from recorded probe outputs;
  - the extension's choice between the unit and the direct launch
    (`node --test`).
- **Long test:** stage 2 (`--stream-deck`) adds checks `service-unit` (the
  unit file exists and its `ExecStart` is under the VM's checkout) and
  `service-condition` (`systemctl --user start` leaves the unit inactive
  with its condition unmet, since a VM has no deck); stage 3 and 4 add
  `service-gone` (unit and settings removed). The long test passes
  `--deck-program=tiler --autostart` in stage 2 and checks `is-enabled`.

## Open risks

- `RESTART_AFTER_GAME` relies on the game process ending; a game left open
  in a terminal keeps the deck until the terminal closes.
- A program started by hand outside the service (for example
  `make streamdeck_tiler`) takes the lock first; the service then fails to
  start until it ends. The status view names the holder.
- A game started by `make streamdeck_<game>` skips the hand-over and takes
  no lock: it fights an active service over the deck.
- The installer, TODO and the extension honour the shell's
  `XDG_CONFIG_HOME`; the user manager and the service read their own
  environment. Set in the shell rc only, it makes the unit land where
  systemd does not look and the service read its default settings.
  `XDG_CONFIG_HOME` belongs in `~/.config/environment.d/`, which the
  session and the user manager share (INSTALL says so).
