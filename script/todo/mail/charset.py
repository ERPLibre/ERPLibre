#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Décoder des octets dont le nom de charset vient du serveur, sans jamais lever.

Un charset annoncé par un en-tête (`Content-Type`, un mot encodé RFC 2047)
peut être n'importe quelle chaîne — y compris une étiquette que Python ne
reconnaît pas, comme `unknown-8bit`, que certains MTA posent sur un en-tête
8 bits mal formé. `bytes.decode(charset, errors="replace")` lève quand même
`LookupError` dans ce cas : la RECHERCHE du codec échoue AVANT que `errors`
ne soit consulté — `errors="replace"` ne protège donc de rien ici.

Cette fonction a été réinventée quatre fois dans ce paquet
(`imap_transport.decode_header_value`, `imap_sync.snippet_from_raw`,
`smtp_send._plain_text`, `tui_text._decode_part`) avant d'être extraite ici :
un charset non fiable ne doit jamais faire tomber l'affichage ou la
synchronisation d'un message entier.
"""
from __future__ import annotations


def decode_bytes(payload: bytes, charset: str | None) -> str:
    """`payload` décodé avec `charset`, replié sur UTF-8 si `charset` est
    absent ou inconnu de Python."""
    try:
        return payload.decode(charset or "utf-8", "replace")
    except LookupError:
        return payload.decode("utf-8", "replace")
