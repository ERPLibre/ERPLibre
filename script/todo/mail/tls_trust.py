#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le geste humain qui épingle un certificat refusé, partagé par le TUI et
le menu.

`question` compose le texte de la confirmation (compte, point d'accès,
raison, empreinte en forme d'`openssl`, mise en garde propre à la raison) ;
le mot à taper est `mail_tls_trust_word`. `pin` écrit l'épingle dans
`accounts.json` et la recopie sur le compte en mémoire. Le service sans
interface n'importe pas ce module : il n'épingle jamais.
"""

from __future__ import annotations

from pathlib import Path

from script.todo.mail import _core_path  # noqa: F401

# isort: split
from erplibre_mail_core import tls

from script.todo.todo_i18n import t


def question(account_name: str, exc) -> str:
    """Le texte de la confirmation d'un refus `exc`
    (`TlsCertificateError`), avec, selon la raison, une mise en garde."""
    champs = {
        "account": account_name,
        "endpoint": exc.endpoint,
        "protocol": exc.protocol.upper(),
        "reason": tls.reason_text(exc.reason),
        "fp": tls.format_fingerprint(exc.fingerprint),
        "pinned": tls.format_fingerprint(exc.pinned),
    }
    cle = (
        "mail_tls_question_changed"
        if exc.reason == "changed"
        else "mail_tls_question_refused"
    )
    texte = t(cle).format(**champs)
    if exc.reason == "hostname":
        noms = tuple(getattr(exc, "names", ()) or ())
        ajout = (
            t("mail_tls_question_names").format(names=", ".join(noms))
            if noms
            else t("mail_tls_question_names_unknown")
        )
    elif exc.reason == "validity":
        ajout = t("mail_tls_question_validity")
    elif exc.reason == "nonconforming":
        ajout = t("mail_tls_question_nonconforming")
    else:
        ajout = ""
    return f"{texte}\n\n{ajout}" if ajout else texte


def status_text(account_name: str, exc) -> str:
    """L'annonce d'un refus en tête de la barre d'état du TUI."""
    return t("mail_tls_status").format(
        account=account_name, endpoint=exc.endpoint
    )


def pin(account, exc, path: Path | None = None) -> None:
    """Épingle l'empreinte présentée par `exc` pour `account` et le point
    d'accès du refus, puis recopie les épingles relues sur `account`.

    `ValueError` si l'empreinte n'a pas pu être lue ; `AccountError` et
    `OSError` de l'écriture traversent.
    """
    from script.todo.mail import accounts

    if not exc.pinnable:
        raise ValueError(t("mail_tls_fingerprint_unreadable"))
    relu = accounts.pin_certificate(
        account.name, exc.host, exc.port, exc.fingerprint, path
    )
    account.tls_pins = dict(relu.tls_pins)


def unpin(account_name: str, key: str, path: Path | None = None) -> None:
    """Retire l'épingle `key` du compte `account_name`."""
    from script.todo.mail import accounts

    accounts.unpin_certificate(account_name, key, path)
