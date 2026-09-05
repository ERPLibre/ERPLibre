#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Tout ce que le TUI calcule avant d'afficher.

Ces fonctions sont volontairement hors de `tui.py` : elles n'ont besoin
d'aucun widget, donc elles se testent en une ligne. Le fichier de l'application
n'a plus qu'à composer des cadres et à appeler ces fonctions.

Un courriel arrive rarement dans la forme qu'on espère : corps vide, HTML seul,
charset menteur, pièce jointe sans nom. Aucune de ces fonctions ne lève ; au
pire elles rendent une chaîne vide. Un message illisible doit s'afficher mal,
pas faire tomber la boîte de réception.
"""
from __future__ import annotations

import datetime
import email
import email.policy
import html as html_module
import re
import unicodedata
from dataclasses import dataclass

from script.todo.mail.charset import decode_bytes

_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL
)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_RE = re.compile(
    r"</(p|div|tr|li|h[1-6]|table|blockquote)>", re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")
_BLANKS_RE = re.compile(r"\n{3,}")


@dataclass
class Attachment:
    filename: str
    content_type: str
    size: int
    index: int


def html_to_text(html: str) -> str:
    """Du HTML rendu lisible, sans dépendance externe.

    Ce n'est pas un moteur de rendu : on veut lire un courriel, pas afficher
    une page. Scripts et styles disparaissent, les blocs deviennent des sauts
    de ligne, le reste est du texte.
    """
    if not html:
        return ""
    text = _SCRIPT_STYLE_RE.sub("", html)
    text = _BR_RE.sub("\n", text)
    text = _BLOCK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html_module.unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    return _BLANKS_RE.sub("\n\n", "\n".join(lines)).strip()


def _decode_part(part) -> str:
    try:
        payload = part.get_payload(decode=True)
    except Exception:
        # Broad except: parsing can fail in many ways; see module docstring.
        return ""
    if payload is None:
        return ""
    # `decode_bytes` (see its docstring): an unrecognised charset name must
    # not bring down the whole message display.
    return decode_bytes(payload, part.get_content_charset())


def extract_body(raw: bytes) -> tuple[str, list[Attachment]]:
    """Le texte affichable d'un message, et la liste de ses pièces jointes."""
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception:
        # Broad except: see module docstring.
        return raw.decode("utf-8", "replace"), []

    plain, html, attachments = "", "", []
    index = 0
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() == "multipart":
            continue
        disposition = (part.get_content_disposition() or "").lower()
        ctype = part.get_content_type()
        if disposition == "attachment" or (
            disposition == "inline" and not ctype.startswith("text/")
        ):
            try:
                payload = part.get_payload(decode=True) or b""
            except Exception:
                # Broad except: see module docstring.
                payload = b""
            attachments.append(
                Attachment(
                    filename=part.get_filename()
                    or f"piece-jointe-{index + 1}",
                    content_type=ctype,
                    size=len(payload),
                    index=index,
                )
            )
            index += 1
            continue
        if ctype == "text/plain" and not plain:
            plain = _decode_part(part)
        elif ctype == "text/html" and not html:
            html = _decode_part(part)

    if plain:
        return plain, attachments
    if html:
        return html_to_text(html), attachments
    return "", attachments


def short_addr(value: str) -> str:
    """« Alice Tremblay <a@example.com> » → « Alice Tremblay ». Sinon l'adresse."""
    if not value:
        return ""
    from email.utils import getaddresses

    pairs = getaddresses([value])
    if not pairs:
        return value.strip()
    name, addr = pairs[0]
    return (name or addr).strip()


def truncate(text: str, width: int) -> str:
    """Coupé à `width` caractères au plus, ellipse comprise."""
    text = text or ""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def format_date(epoch: int, now: int) -> str:
    """Aujourd'hui → l'heure. Cette année → jour-mois. Avant → la date pleine."""
    if not epoch:
        return ""
    try:
        stamp = datetime.datetime.fromtimestamp(epoch)
        today = datetime.datetime.fromtimestamp(now)
    except (OSError, OverflowError, ValueError):
        # `fromtimestamp` lève hors de la plage représentable — OSError ou
        # OverflowError selon l'ampleur. Une date aberrante vient d'un
        # en-tête, donc d'une source non fiable : elle doit s'afficher vide,
        # pas faire tomber la liste des messages.
        return ""
    if stamp.date() == today.date():
        return stamp.strftime("%H:%M")
    if stamp.year == today.year:
        return stamp.strftime("%m-%d")
    return stamp.strftime("%Y-%m-%d")


def format_date_full(epoch: int) -> str:
    """La date pleine, jour et heure, lisible sans le contexte de la liste.

    `format_date` est compact À DESSEIN pour la colonne de la liste ;
    l'aperçu d'un message veut savoir QUAND il a été envoyé, sans avoir à
    deviner l'année à partir de la date du jour. Même garde que
    `format_date` : un en-tête vient d'une source non fiable, une date
    aberrante doit rendre une chaîne vide, jamais lever.
    """
    if not epoch:
        return ""
    try:
        stamp = datetime.datetime.fromtimestamp(epoch)
    except (OSError, OverflowError, ValueError):
        # Voir `format_date` : `fromtimestamp` lève hors de la plage
        # représentable — OSError ou OverflowError selon l'ampleur.
        return ""
    return stamp.strftime("%Y-%m-%d %H:%M")


def format_size(size: int) -> str:
    size = size or 0
    if size < 1024:
        return f"{size} o"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} ko"
    return f"{size / (1024 * 1024):.1f} Mo"


def is_unread(flags: str | None) -> bool:
    return "\\seen" not in (flags or "").lower()


def _fold(text: str) -> str:
    """Sans accents ni casse : « revise » doit trouver « révisé »."""
    stripped = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in stripped if not unicodedata.combining(c)).lower()


def filter_messages(metas: list, query: str) -> list:
    """Filtre incrémental sur ce que le cache contient déjà.

    Volontairement local : la recherche côté serveur est une fonction de la
    phase 3, celle-ci doit répondre à chaque frappe sans réseau.
    """
    if not query:
        return list(metas)
    needle = _fold(query)
    return [
        m
        for m in metas
        if needle in _fold(f"{m.subject} {m.frm} {m.to} {m.snippet}")
    ]
