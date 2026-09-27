#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Protocole `todo.v1` sur le canal d'une session : une ligne JSON par
message entre le worker (fd 3) et le hub.

Du hub au worker : `hello`, puis `answer {qid, value}` et `cancel {qid}`.
Du worker au hub : `menu` et `ask`, les questions, chacune avec son
`qid`, et `answered {qid}` à la fin de chacune, quelle qu'en soit
l'issue ; `notice`, `run_start`, `run_end`, `open_view`.

Une ligne du worker tient toujours dans LINE_LIMIT octets, ce que le hub
lit d'un coup : `encode` coupe au besoin le texte d'une question (il en
garde la fin, où est l'invite), ses libellés et ses entrées. Module
pur : ni tornado ni TODO.
"""

import json

LINE_LIMIT = 1024 * 1024
TEXT_LIMIT = 16 * 1024
LABEL_LIMIT = 200
ITEM_LIMIT = 200


def _dump(message) -> bytes:
    return json.dumps(message, ensure_ascii=False).encode() + b"\n"


def _clip(value):
    """`value` dont chaque chaîne garde ses LABEL_LIMIT premiers
    caractères et chaque liste ses ITEM_LIMIT premiers éléments."""
    if isinstance(value, str):
        return value[:LABEL_LIMIT]
    if isinstance(value, list):
        return [_clip(item) for item in value[:ITEM_LIMIT]]
    if isinstance(value, dict):
        return {key: _clip(item) for key, item in value.items()}
    return value


def encode(message) -> bytes:
    """La ligne de `message`, au plus LINE_LIMIT octets : au-delà, `text`
    garde ses TEXT_LIMIT derniers caractères et tout le reste passe par
    `_clip`. Un caractère de contrôle s'écrit en six octets (`\\u0001`) :
    si c'est encore trop, `items`, `crumbs` et `sections` se vident, et le
    texte, invite comprise, reste."""
    line = _dump(message)
    if len(line) <= LINE_LIMIT:
        return line
    small = _clip({key: v for key, v in message.items() if key != "text"})
    if "text" in message:
        small["text"] = str(message["text"])[-TEXT_LIMIT:]
    line = _dump(small)
    if len(line) <= LINE_LIMIT:
        return line
    for key in ("items", "crumbs", "sections"):
        if key in small:
            small[key] = []
    return _dump(small)


def _qid(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _load(line):
    try:
        message = json.loads(line)
    except ValueError:
        return None
    return message if isinstance(message, dict) else None


def reply(line):
    """La réponse `answer` ou `cancel` d'une ligne du hub, telle que le
    worker l'attend ; None pour toute autre ligne."""
    message = _load(line)
    if message is None or not _qid(message.get("qid")):
        return None
    if message.get("t") == "cancel":
        return message
    if message.get("t") == "answer" and isinstance(message.get("value"), str):
        return message
    return None
