<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Claude session-state hook
<!-- [fr] -->
# Hook d'état de session Claude
<!-- [end] -->

<!-- [en] -->
The Stream Deck Tiler GNOME extension shows a count badge on the
**Pencil** indicator with the number of running Claude sessions and
flags whichever ones are waiting for the user (yellow = `Stop`, red =
`Notification`). The badge data comes from JSON files written by a
small Claude Code hook.
<!-- [fr] -->
L'extension GNOME Stream Deck Tiler affiche un badge sur l'indicateur
**Crayon** avec le nombre de sessions Claude en cours et signale celles
qui attendent l'utilisateur (jaune = `Stop`, rouge = `Notification`).
Le badge lit des fichiers JSON écrits par un petit hook Claude Code.
<!-- [end] -->

<!-- [en] -->
## Install
<!-- [fr] -->
## Installation
<!-- [end] -->

<!-- [en] -->
1. The hook script lives at
   `script/stream_deck/gnome-extension/hooks/streamdeck-tiler-hook.py`.
   It is already executable and only needs Python 3.
2. Wire it into Claude Code by adding the matchers below to
   `~/.claude/settings.json` (merge with any existing `hooks` block).
<!-- [fr] -->
1. Le script du hook est dans
   `script/stream_deck/gnome-extension/hooks/streamdeck-tiler-hook.py`.
   Il est déjà exécutable et ne dépend que de Python 3.
2. Branche-le dans Claude Code en ajoutant les matchers ci-dessous à
   `~/.claude/settings.json` (fusionne avec ton bloc `hooks` existant).
<!-- [end] -->

<!-- [common] -->
```json
{
  "hooks": {
    "SessionStart": [
      {"hooks": [{"type": "command", "command": "/ABS/PATH/streamdeck-tiler-hook.py"}]}
    ],
    "UserPromptSubmit": [
      {"hooks": [{"type": "command", "command": "/ABS/PATH/streamdeck-tiler-hook.py"}]}
    ],
    "Stop": [
      {"hooks": [{"type": "command", "command": "/ABS/PATH/streamdeck-tiler-hook.py"}]}
    ],
    "Notification": [
      {"hooks": [{"type": "command", "command": "/ABS/PATH/streamdeck-tiler-hook.py"}]}
    ],
    "SessionEnd": [
      {"hooks": [{"type": "command", "command": "/ABS/PATH/streamdeck-tiler-hook.py"}]}
    ]
  }
}
```
<!-- [end] -->

<!-- [en] -->
Replace `/ABS/PATH/` with the absolute path of the script on your
machine. The hook receives the standard JSON payload on stdin and
writes one file per session under
`$XDG_STATE_HOME/streamdeck-tiler/claude/{session_id}.json` (or
`~/.local/state/streamdeck-tiler/claude/` if `XDG_STATE_HOME` is unset).
The extension watches that directory with `Gio.FileMonitor` so updates
appear in the panel within a fraction of a second.
<!-- [fr] -->
Remplace `/ABS/PATH/` par le chemin absolu du script sur ta machine.
Le hook reçoit le payload JSON standard sur stdin et écrit un fichier
par session dans
`$XDG_STATE_HOME/streamdeck-tiler/claude/{session_id}.json` (ou
`~/.local/state/streamdeck-tiler/claude/` si `XDG_STATE_HOME` n'est pas
défini). L'extension surveille ce dossier avec `Gio.FileMonitor`, donc
les changements apparaissent dans la barre en moins d'une seconde.
<!-- [end] -->

<!-- [en] -->
## Status mapping
<!-- [fr] -->
## Correspondance des statuts
<!-- [end] -->

<!-- [common] -->
| Hook event       | File status              |
|------------------|--------------------------|
| `SessionStart`   | `active`                 |
| `UserPromptSubmit` | `active`               |
| `Stop`           | `awaiting_stop`          |
| `Notification`   | `awaiting_notification`  |
| `SessionEnd`     | (file deleted)           |
<!-- [end] -->

<!-- [en] -->
The hook also walks `/proc` to find the parent `claude` PID and stores
it in the file. The extension checks `/proc/<pid>` periodically and
removes stale files when the process is gone (e.g. crash, kill -9).
<!-- [fr] -->
Le hook parcourt aussi `/proc` pour retrouver le PID `claude` parent
et l'enregistre dans le fichier. L'extension vérifie `/proc/<pid>`
périodiquement et nettoie les fichiers obsolètes quand le processus
n'existe plus (ex.\ crash, kill -9).
<!-- [end] -->
