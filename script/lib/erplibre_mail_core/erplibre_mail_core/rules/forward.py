# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le transfert d'un message reçu, commun au client et au module Odoo : le
message qui part selon le mode, le `Reply-To` d'un transfert, le premier
identifiant d'un en-tête d'enfilage.
"""

from __future__ import annotations

from email.utils import getaddresses

from erplibre_mail_core import smtp
from erplibre_mail_core.rules.filter import normalize_address, sender_address


def forward_message(
    account,
    opts,
    raw: bytes,
    targets,
    *,
    intro: str = "",
    reply_to: str = "",
    subject_prefix: str = "",
    date: str | None = None,
    msgid: str | None = None,
):
    """Le message d'une règle `forward` selon `opts.mode` (une
    `model.ForwardOptions`).

    `redirect` rend un `smtp.RawOutgoing` (octets d'origine sous un bloc
    `Resent-*`, enveloppe = `targets`) ; `intro`, `reply_to` et
    `subject_prefix` y sont ignorés. `attachment` et `inline` rendent un
    `EmailMessage` adressé à `targets` en Cci interne. Lève `SmtpError`
    sur une destination refusée ou des octets illisibles.
    """
    if opts.mode == "redirect":
        return smtp.build_redirect(
            account, raw, targets, date=date, msgid=msgid
        )
    build = (
        smtp.build_forward_attached
        if opts.mode == "attachment"
        else smtp.build_forward_inline
    )
    return build(
        account,
        raw,
        targets,
        intro=intro,
        reply_to=reply_to,
        subject_prefix=subject_prefix,
        date=date,
        msgid=msgid,
    )


def forward_reply_to(view, own, others) -> str:
    """Le `Reply-To` d'un transfert, en forme d'envoi.

    Les adresses de la PREMIÈRE occurrence de `Reply-To` de l'original,
    chacune passée par `smtp_address` (refusée : ignorée), moins celles de
    `own` et de `others` (adresses normalisées), sans doublon, jointes par
    « , ». S'il n'en reste aucune, l'adresse de From ; « » si elle n'est
    pas admise non plus. Une notification `noreply` dont le `Reply-To`
    désigne le demandeur reste ainsi joignable par la destination qui
    répond.
    """
    first = (view.extra.get("reply-to") or "").split("\n", 1)[0]
    kept: list[str] = []
    for _name, address in getaddresses([first]):
        try:
            form = smtp.smtp_address(address.strip())
        except smtp.SmtpError:
            continue
        norm = normalize_address(form)
        if norm in own or norm in others:
            continue
        if all(normalize_address(k) != norm for k in kept):
            kept.append(form)
    if kept:
        return ", ".join(kept)
    try:
        return smtp.smtp_address(sender_address(view, raw=True))
    except smtp.SmtpError:
        return ""


def first_msgid(value: str) -> str:
    """Le premier identifiant d'un en-tête d'enfilage, ou « »."""
    tokens = smtp._msgid_tokens(value)
    return tokens[0] if tokens else ""
