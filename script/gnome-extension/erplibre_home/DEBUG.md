# Debug guide

When the extension misbehaves, walk through this list before opening
an issue. It maps the most common symptoms to the log file or D-Bus
probe that will surface the root cause.

## Log files

| Path | Source |
| --- | --- |
| `journalctl --user --user-unit gnome-shell-wayland.service -f` | Live stderr from the GJS code (every `console.log(...)` lands here). Filter with `grep ERPLibreHome`. |
| `~/.local/state/erplibre-home/log.jsonl` | JSONL append-only log written by `lib/log.js` (subprocess errors, mpv launches, hook failures). The Activity log page in prefs reads the last 200 lines. |
| `~/.local/state/erplibre-home/claude/*.json` | One file per Claude session, written by `hooks/erplibre-home-hook.py`. `cat` them to see the timestamps the indicator drives off. |
| `~/.local/state/erplibre-home/mpv/*.json` | One file per running mpv launched from the deck. Removed automatically when the player exits. |
| Stream Deck driver: stderr of `script/stream_deck/erplibre_controller.py` | Open the Activity Monitor page in prefs, or run the controller from a terminal to see button-press errors. |

## D-Bus introspection

```
gdbus introspect --session \
    --dest org.gnome.Shell \
    --object-path /org/gnome/Shell/Extensions/ERPLibreHome
```

Read-only probes that never break state:

```
# Dump the indexed Claude sessions.
gdbus call --session \
    --dest org.gnome.Shell \
    --object-path /org/gnome/Shell/Extensions/ERPLibreHome \
    --method org.gnome.Shell.Extensions.ERPLibreHome.DebugClaudeIndex

# List configured paths / instances / media / windows.
gdbus call --session \
    --dest org.gnome.Shell \
    --object-path /org/gnome/Shell/Extensions/ERPLibreHome \
    --method org.gnome.Shell.Extensions.ERPLibreHome.ListPaths
gdbus call --session \
    --dest org.gnome.Shell \
    --object-path /org/gnome/Shell/Extensions/ERPLibreHome \
    --method org.gnome.Shell.Extensions.ERPLibreHome.ListWindows
```

Force a hot reload after editing source:

```
gdbus call --session \
    --dest org.gnome.Shell \
    --object-path /org/gnome/Shell/Extensions/ERPLibreHome \
    --method org.gnome.Shell.Extensions.ERPLibreHome.HotReload
```

## Common issues

### Pencil badge stays grey, never goes green / yellow / red
- **Hooks not installed**: run `make claude_install_hooks` then restart
  Claude. Verify with `cat ~/.claude/settings.json | jq .hooks`.
- **State files never appear**: check `ls -la ~/.local/state/erplibre-home/claude/` after a Claude turn. If empty, the hook is failing — run it manually with the env it gets from Claude.
- **`enable-claude-state-watch` is off**: re-enable in prefs.

### Click on a session row focuses the wrong terminal
- The hook captures the Mutter window id at SessionStart. Re-save it
  with the `Set window…` row inside the same session. If `gnome-shell`
  was restarted between SessionStart and your click, the saved id is
  stale; Set window again.

### `Could not send Enter — see script/stream_deck/INSTALL.md`
- Wayland blocks the `wtype` virtual keyboard. The extension uses a
  Clutter virtual device internally, reached through
  `defaultSeat()` in `lib/shell-compat.js`; if it still fails, the
  Shell may have changed that API again — open an issue with the
  journalctl excerpt around the failure.

### VLC / mpv won't open a YouTube URL
- `mpv` needs `yt-dlp` on PATH with
  `--script-opts=ytdl_hook-ytdl_path=yt-dlp` (already wired).
- `vlc` runs through a bash wrapper that resolves the URL via
  `yt-dlp -g`. If the wrapper fails, run it manually:
  `yt-dlp -g 'https://...'` and check the resolution.

### Top-bar indicator missing after install
- `gnome-extensions list --enabled` should include
  `erplibre-home@technolibre.ca`. If not:
  `make erplibre_home_enable_extension`.
- Wayland only loads new ES modules after a session log out / log in.
  Use the nested dev shell (`make erplibre_home_dev_nested`) for
  fast iteration.

### Top-bar indicator labels stuck in English
- Locales aren't compiled. `make erplibre_home_install_extension`
  recompiles them with `msgfmt --check`, as every install does;
  `make erplibre_home_compile_locale` compiles them alone, under the
  system `python3`.
- `LANG` does not start with `fr` / your target language; verify with
  `echo $LANG`.

### HotReload pollutes git with metadata.json edits
- Each HotReload mutates the symlinked metadata.json to give the
  reload UUID a unique name. Reset before commit:
  `git checkout -- script/gnome-extension/erplibre_home/metadata.json`.

### Stream Deck device not detected
- `lsusb` should list the Elgato vendor (0fd9). If yes but the
  controller fails, check `~/.local/state/erplibre-home/log.jsonl`
  for `usb` errors. udev permissions are the usual culprit; reinstall
  the udev rule from `script/stream_deck/INSTALL.md`.

### Tiling mode locks on the corner-pick grid
- Fixed: TILE auto-cancels after 5 s of inactivity. If your timeout
  feels off, override `TILING_IDLE_TIMEOUT_SEC` in `game_tiler.py`.

## Reset to a clean state

```
# Clear Claude session state files.
rm -rf ~/.local/state/erplibre-home/claude/

# Clear the activity log.
truncate -s 0 ~/.local/state/erplibre-home/log.jsonl

# Reset GSettings to defaults (will lose the catalogues).
dconf reset -f /org/gnome/shell/extensions/erplibre-home/

# Force a full reload.
make erplibre_home_uninstall_extension
make erplibre_home_install_extension
make erplibre_home_enable_extension
```

## When all else fails

Open an issue with:
- `journalctl --user --user-unit gnome-shell-wayland.service -n 200 | grep ERPLibreHome`
- `gdbus call --session --dest org.gnome.Shell ... DebugClaudeIndex`
- The contents of one
  `~/.local/state/erplibre-home/claude/*.json` if Claude badges
  misbehave.
- `gnome-extensions info erplibre-home@technolibre.ca`.
