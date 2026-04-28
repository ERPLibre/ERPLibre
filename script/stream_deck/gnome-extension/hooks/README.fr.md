
# Hook d'état de session Claude
L'extension GNOME Stream Deck Tiler affiche un badge sur l'indicateur
**Crayon** avec le nombre de sessions Claude en cours et signale celles
qui attendent l'utilisateur (jaune = `Stop`, rouge = `Notification`).
Le badge lit des fichiers JSON écrits par un petit hook Claude Code.
## Installation
1. Le script du hook est dans
   `script/stream_deck/gnome-extension/hooks/streamdeck-tiler-hook.py`.
   Il est déjà exécutable et ne dépend que de Python 3.
2. Branche-le dans Claude Code en ajoutant les matchers ci-dessous à
   `~/.claude/settings.json` (fusionne avec ton bloc `hooks` existant).
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
Remplace `/ABS/PATH/` par le chemin absolu du script sur ta machine.
Le hook reçoit le payload JSON standard sur stdin et écrit un fichier
par session dans
`$XDG_STATE_HOME/streamdeck-tiler/claude/{session_id}.json` (ou
`~/.local/state/streamdeck-tiler/claude/` si `XDG_STATE_HOME` n'est pas
défini). L'extension surveille ce dossier avec `Gio.FileMonitor`, donc
les changements apparaissent dans la barre en moins d'une seconde.
## Correspondance des statuts
| Hook event       | File status              |
|------------------|--------------------------|
| `SessionStart`   | `active`                 |
| `UserPromptSubmit` | `active`               |
| `Stop`           | `awaiting_stop`          |
| `Notification`   | `awaiting_notification`  |
| `SessionEnd`     | (file deleted)           |
Le hook parcourt aussi `/proc` pour retrouver le PID `claude` parent
et l'enregistre dans le fichier. L'extension vérifie `/proc/<pid>`
périodiquement et nettoie les fichiers obsolètes quand le processus
n'existe plus (ex.\ crash, kill -9).