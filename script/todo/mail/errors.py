#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La famille d'une panne d'ouverture ou de synchronisation d'un compte.

Le service sans interface rend un code de sortie par famille et n'écrit au
journal que ce qui ne peut rien révéler : le nom de la classe de
l'exception et, s'il existe, le code de réponse IMAP entre crochets. Le
texte d'une erreur de serveur peut rappeler l'identifiant de connexion ;
il reste dans `~/.erplibre/mail.log`.

Les modules du paquet s'importent DANS les fonctions : `tui.open_session`
classe ses pannes par ici, et ce module ne doit tirer ni le TUI ni les
transports à son import.
"""

from __future__ import annotations

import re

KINDS = ("vault", "auth", "network", "busy", "cache", "config", "other")

# Profondeur de la chaîne `__cause__`/`__context__` parcourue : assez pour
# une panne de socket enveloppée deux ou trois fois, et une borne contre une
# chaîne qui boucle.
CAUSE_DEPTH = 5

# Le code de réponse IMAP (RFC 5530), seul fragment du texte d'une panne
# recopié au journal.
_RESPONSE_CODE_RE = re.compile(r"\[([A-Z][A-Z0-9-]*)\]")


def _chain(exc: BaseException) -> list:
    """`exc` puis ses causes, au plus `CAUSE_DEPTH` en tout, sans doublon."""
    vues = []
    courant = exc
    while courant is not None and len(vues) < CAUSE_DEPTH:
        if any(courant is deja for deja in vues):
            break
        vues.append(courant)
        courant = courant.__cause__ or courant.__context__
    return vues


def _cause_is(exc: BaseException, types) -> bool:
    """Vrai si une CAUSE de `exc` (pas `exc` elle-même) est de `types`."""
    return any(isinstance(cause, types) for cause in _chain(exc)[1:])


def _busy_text(exc: BaseException) -> bool:
    texte = str(exc).lower()
    return "locked" in texte or "busy" in texte


def classify(exc: BaseException) -> str:
    """La famille d'une panne d'ouverture ou de synchronisation.

    Rend l'un de `KINDS`. Le premier test qui répond gagne : coffre, refus
    du secret, jeton OAuth, réponse IMAP, socket, base occupée, cache,
    configuration, puis `other`.
    """
    import imaplib
    import sqlite3

    from script.todo.mail import imap_transport, oauth, smtp_send
    from script.todo.mail.accounts import AccountError
    from script.todo.mail.secrets import SecretError
    from script.todo.mail.store import StoreError

    vault_types = (SecretError,)
    try:
        from script.todo import kdbx_write
    except ImportError:
        kdbx_write = None
    busy_vault = getattr(kdbx_write, "KdbxBusy", None)
    if isinstance(busy_vault, type):
        vault_types += (busy_vault,)

    lien_mort = (OSError, imaplib.IMAP4.abort)
    if isinstance(exc, vault_types):
        return "vault"
    if isinstance(
        exc,
        (
            imap_transport.ImapAuthError,
            smtp_send.SmtpAuthError,
            oauth.RefreshRefused,
        ),
    ):
        return "auth"
    if isinstance(exc, oauth.OAuthError):
        return "network" if _cause_is(exc, OSError) else "auth"
    if isinstance(exc, imap_transport.ImapError):
        if _cause_is(exc, lien_mort):
            return "network"
        if _cause_is(exc, (imaplib.IMAP4.error, UnicodeEncodeError)):
            return "auth"
        return "other"
    if isinstance(exc, lien_mort):
        return "network"
    if any(
        isinstance(maillon, sqlite3.OperationalError) and _busy_text(maillon)
        for maillon in _chain(exc)
    ):
        return "busy"
    if isinstance(exc, (StoreError, sqlite3.Error)):
        return "cache"
    if isinstance(exc, AccountError):
        return "config"
    return "other"


def journal_detail(exc: BaseException) -> str:
    """Ce qu'une panne laisse voir au journal : le nom de sa classe et,
    s'il existe, le code de réponse IMAP entre crochets ; jamais son texte.

    Le code est le premier `[MOT]` trouvé dans le texte de l'exception ou
    de ses causes (`[AUTHENTICATIONFAILED]`, `[UNAVAILABLE]`).
    """
    if exc is None:
        return ""
    detail = type(exc).__name__
    for maillon in _chain(exc):
        trouve = _RESPONSE_CODE_RE.search(str(maillon))
        if trouve:
            return f"{detail} [{trouve.group(1)}]"
    return detail
