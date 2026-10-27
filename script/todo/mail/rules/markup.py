#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Rendu du corps d'une réponse automatique : texte, HTML et images.

Trois formats par règle. `markdown` : la source se lit telle quelle en
texte, et se convertit en HTML. `html` : écrit à la main, sa version texte
en est tirée. `text` : pas de HTML, et toutes les images partent en pièces
jointes. Dans les deux formats HTML, une image que le corps référence par
son nom (`![x](logo.png)` ou `<img src="logo.png">`) part EN LIGNE, citée
par `cid:` ; une image listée mais non référencée part en pièce jointe :
aucune image de la règle n'est perdue.

Le Markdown ne laisse passer AUCUN HTML brut : le corps est écrit par
l'utilisateur, mais une balise copiée-collée d'ailleurs partirait sous son
nom vers des tiers.
"""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass

from script.todo.mail import tui_text
from script.todo.mail.rules.model import (
    MAX_IMAGES_TOTAL_BYTES,
    Action,
    RuleError,
)
from script.todo.mail.smtp_send import AttachmentPart, InlineImage
from script.todo.todo_i18n import t

_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
# `src` comme attribut entier : « data-src » ne correspond pas.
_SRC_RE = re.compile(
    r"""((?<![\w-])src\s*=\s*)(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE
)
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")


@dataclass
class RenderedReply:
    text: str
    html: str | None
    # list[smtp_send.InlineImage]
    inline: list
    # list[smtp_send.AttachmentPart]
    attachments: list


def _fallback_html(source: str) -> str:
    """HTML minimal sans bibliothèque : paragraphes et sauts de ligne.

    Tout le texte est échappé : le repli ne produit jamais d'HTML brut.
    """
    paragraphs = []
    for block in _PARAGRAPH_SPLIT_RE.split(source.strip()):
        if not block.strip():
            continue
        lines = [html_module.escape(line) for line in block.splitlines()]
        paragraphs.append("<p>" + "<br>\n".join(lines) + "</p>")
    return "\n".join(paragraphs) + ("\n" if paragraphs else "")


def markdown_to_html(source: str) -> str:
    """Markdown CommonMark avec tableaux, HTML brut échappé.

    `markdown_it` accompagne Textual ; s'il manque, le repli rend des
    paragraphes échappés plutôt que d'échouer.
    """
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        return _fallback_html(source)
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    return parser.render(source)


def html_to_text(html: str) -> str:
    """Version texte d'un HTML ; délègue à `tui_text.html_to_text`."""
    return tui_text.html_to_text(html)


def wrap_html_document(fragment: str) -> str:
    """Document HTML complet, déclaré UTF-8, autour d'un fragment.

    Un HTML qui porte déjà sa balise `<html` (sans égard à la casse) est
    rendu tel quel.
    """
    if "<html" in fragment.lower():
        return fragment
    return (
        "<!DOCTYPE html>\n"
        '<html><head><meta charset="utf-8"></head><body>\n'
        f"{fragment}\n"
        "</body></html>\n"
    )


def _src_value(match: re.Match) -> str:
    value = match.group(2) if match.group(2) is not None else match.group(3)
    return html_module.unescape(value)


def image_refs(html: str) -> set[str]:
    """Les valeurs `src` des balises `<img>` du document."""
    refs = set()
    for tag in _IMG_TAG_RE.finditer(html):
        for src in _SRC_RE.finditer(tag.group(0)):
            refs.add(_src_value(src))
    return refs


def rewrite_image_refs(
    html: str, cid_by_name: dict[str, str]
) -> tuple[str, set[str]]:
    """Remplace `src="<nom>"` par `src="cid:<cid>"` pour chaque nom connu.

    Rend le HTML réécrit et l'ensemble des noms effectivement cités ; un
    `src` qui ne nomme aucun média est laissé tel quel.
    """
    used: set[str] = set()

    def rewrite_src(match: re.Match) -> str:
        name = _src_value(match)
        cid = cid_by_name.get(name)
        if cid is None:
            return match.group(0)
        used.add(name)
        return f'{match.group(1)}"cid:{html_module.escape(cid)}"'

    def rewrite_tag(match: re.Match) -> str:
        return _SRC_RE.sub(rewrite_src, match.group(0))

    return _IMG_TAG_RE.sub(rewrite_tag, html), used


def content_id(sha256: str, domain: str) -> str:
    """Content-ID d'une image, sans chevrons, stable pour un même contenu.

    Un domaine vide prend « localhost » : un Content-ID exige une partie
    droite.
    """
    return f"img-{sha256[:16]}@{domain or 'localhost'}"


def _parts(ref, media: dict[str, bytes]) -> tuple[bytes, str, str]:
    data = media.get(ref.file)
    if data is None:
        raise RuleError(f"{t('mail_rules_err_image_missing')} {ref.file}")
    maintype, _, subtype = ref.mime.partition("/")
    return data, maintype or "image", subtype or "octet-stream"


def render_reply(
    action: Action, media: dict[str, bytes], domain: str
) -> RenderedReply:
    """Texte, HTML et images d'une réponse, selon `action.format`.

    `media` associe le nom stocké de chaque image à ses octets ; une image
    de la règle absente de `media` lève `RuleError`, comme des images qui
    pèsent ensemble plus de `MAX_IMAGES_TOTAL_BYTES`. `domain` est le
    domaine du compte, partie droite des Content-ID.
    """
    images = []
    seen_names = set()
    for ref in action.images:
        if ref.file in seen_names:
            continue
        seen_names.add(ref.file)
        images.append((ref, *_parts(ref, media)))
    total = sum(len(data) for _ref, data, *_rest in images)
    if total > MAX_IMAGES_TOTAL_BYTES:
        raise RuleError(
            f"{t('mail_rules_err_image_size')} > {MAX_IMAGES_TOTAL_BYTES}"
        )

    if action.format == "text":
        attachments = [
            AttachmentPart(data, maintype, subtype, ref.file)
            for ref, data, maintype, subtype in images
        ]
        return RenderedReply(action.body, None, [], attachments)

    if action.format == "markdown":
        fragment = markdown_to_html(action.body)
        text = action.body
    elif action.format == "html":
        fragment = action.body
        text = html_to_text(action.body)
    else:
        raise RuleError(f"{t('mail_rules_err_format')} {action.format!r}")

    cid_by_name = {
        ref.file: content_id(ref.sha256, domain) for ref, *_ in images
    }
    rewritten, used = rewrite_image_refs(fragment, cid_by_name)
    inline, attachments, cids = [], [], set()
    for ref, data, maintype, subtype in images:
        if ref.file not in used:
            attachments.append(
                AttachmentPart(data, maintype, subtype, ref.file)
            )
            continue
        cid = cid_by_name[ref.file]
        # Deux noms au même contenu partagent un Content-ID : une seule
        # partie suffit, deux parties de même Content-ID seraient ambiguës.
        if cid in cids:
            continue
        cids.add(cid)
        inline.append(InlineImage(cid, data, maintype, subtype, ref.file))
    return RenderedReply(
        text, wrap_html_document(rewritten), inline, attachments
    )
