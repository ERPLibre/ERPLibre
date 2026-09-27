#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Protocole `todo.v1` sur le canal d'une session : une ligne JSON par
message entre le worker (fd 3) et le hub.

Du hub au worker : `hello`, puis `answer {qid, value}` et `cancel {qid}`.
Du worker au hub (FROM_WORKER) : `menu` et `ask`, les questions, chacune
avec son `qid`, et `answered {qid}` à la fin de chacune, quelle qu'en soit
l'issue, avec `key` pour l'entrée choisie d'un menu et `end` (`timeout`,
`cancel`) pour une question finie sans réponse ; `notice`, `run_start`,
`run_end`, `open_view`. Le hub relaie ces messages à la page tels quels.

Une ligne du worker tient toujours dans LINE_LIMIT octets, ce que le hub
lit d'un coup : `encode` coupe au besoin le texte d'une question (il en
garde la fin, où est l'invite), ses libellés et ses entrées. Une réponse
de la page est un texte d'une ligne d'au plus ANSWER_LIMIT caractères,
sans caractère de contrôle. Module pur : ni tornado ni TODO.
"""

import json

LINE_LIMIT = 1024 * 1024
TEXT_LIMIT = 16 * 1024
LABEL_LIMIT = 200
ITEM_LIMIT = 200
# Caractères d'une réponse de la page (`reply_line` compte des caractères,
# non des octets) : l'ordre d'une ligne du terminal en mode canonique, 4095
# octets et son saut de ligne ; la page n'en dit pas plus que le clavier.
ANSWER_LIMIT = 4096
QUESTIONS = ("menu", "ask")
# Messages du worker qui portent le `qid` d'une question.
WITH_QID = ("menu", "ask", "answered")
FROM_WORKER = (*WITH_QID, "notice", "run_start", "run_end", "open_view")
# Vues que le worker peut faire ouvrir à la page.
VIEWS = ("telemetry",)


def _dump(message) -> bytes:
    """La ligne UTF-8 de `message` ; un demi-substitut isolé, comme en
    porte un nom de fichier non UTF-8 lu sous surrogateescape, y devient
    « ? » au lieu de lever UnicodeEncodeError."""
    line = json.dumps(message, ensure_ascii=False)
    return line.encode(errors="replace") + b"\n"


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


def from_worker(line):
    """Le message d'une ligne du worker que le hub relaie ; None pour une
    ligne illisible, un type hors FROM_WORKER, un message de WITH_QID sans
    `qid`, ou une vue hors VIEWS."""
    message = _load(line)
    if message is None or message.get("t") not in FROM_WORKER:
        return None
    if message["t"] in WITH_QID and not _qid(message.get("qid")):
        return None
    if message["t"] == "open_view" and message.get("view") not in VIEWS:
        return None
    return message


def _printable(value) -> bool:
    """Vrai pour un texte sans caractère de contrôle (C0, DEL, C1) ni
    demi-substitut UTF-16 isolé : rien qui, écrit dans le terminal par la
    transcription, déplace le curseur ou lance une séquence d'échappement,
    et rien que `_dump` changerait en « ? », une réponse autre que celle
    tapée."""
    return not any(
        ord(c) < 0x20 or 0x7F <= ord(c) < 0xA0 or 0xD800 <= ord(c) < 0xE000
        for c in value
    )


def reply_line(message, asking):
    """La ligne qui porte au worker la réponse de la page, `answer` ou
    `cancel`, à la question ouverte `asking` (son qid, ou None) ; None pour
    un autre qid, ou une valeur qui n'est pas un texte d'une ligne d'au plus
    ANSWER_LIMIT caractères, sans caractère de contrôle."""
    qid = message.get("qid")
    if asking is None or not _qid(qid) or qid != asking:
        return None
    if message.get("t") == "cancel":
        return _dump({"t": "cancel", "qid": qid})
    value = message.get("value")
    if message.get("t") != "answer" or not isinstance(value, str):
        return None
    if len(value) > ANSWER_LIMIT or not _printable(value):
        return None
    return _dump({"t": "answer", "qid": qid, "value": value})


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
