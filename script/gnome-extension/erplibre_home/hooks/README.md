
# Claude session-state hook
The ERPLibre Home GNOME extension shows a count badge on the
**Pencil** indicator with the number of running Claude sessions and
flags whichever ones are waiting for the user (yellow = `Stop`, red =
`Notification`). The badge data comes from JSON files written by a
small Claude Code hook.
## Install
1. The hook script lives at
   `script/gnome-extension/erplibre_home/hooks/erplibre-home-hook.py`.
   It is already executable and only needs Python 3.
2. Wire it into Claude Code by adding the matchers below to
   `~/.claude/settings.json` (merge with any existing `hooks` block).
```json
{
  "hooks": {
    "SessionStart": [
      {"hooks": [{"type": "command", "command": "/ABS/PATH/erplibre-home-hook.py"}]}
    ],
    "UserPromptSubmit": [
      {"hooks": [{"type": "command", "command": "/ABS/PATH/erplibre-home-hook.py"}]}
    ],
    "Stop": [
      {"hooks": [{"type": "command", "command": "/ABS/PATH/erplibre-home-hook.py"}]}
    ],
    "Notification": [
      {"hooks": [{"type": "command", "command": "/ABS/PATH/erplibre-home-hook.py"}]}
    ],
    "SessionEnd": [
      {"hooks": [{"type": "command", "command": "/ABS/PATH/erplibre-home-hook.py"}]}
    ]
  }
}
```
Replace `/ABS/PATH/` with the absolute path of the script on your
machine. The hook receives the standard JSON payload on stdin and
writes one file per session under
`$XDG_STATE_HOME/erplibre-home/claude/{session_id}.json` (or
`~/.local/state/erplibre-home/claude/` if `XDG_STATE_HOME` is unset).
The extension watches that directory with `Gio.FileMonitor` so updates
appear in the panel within a fraction of a second.
## Status mapping
| Hook event       | File status              |
|------------------|--------------------------|
| `SessionStart`   | `active`                 |
| `UserPromptSubmit` | `active`               |
| `Stop`           | `awaiting_stop`          |
| `Notification`   | `awaiting_notification`  |
| `SessionEnd`     | (file deleted)           |
The hook also walks `/proc` to find the parent `claude` PID and stores
it in the file. The extension checks `/proc/<pid>` periodically and
removes stale files when the process is gone (e.g. crash, kill -9).