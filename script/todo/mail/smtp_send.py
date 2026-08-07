#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Construire un message et le remettre à un serveur SMTP.

`EmailMessage` fait le gros du travail : encodage des en-têtes accentués,
choix du transfert, structure multipart. On se contente de décider QUOI mettre
dedans — et surtout de ne pas mettre le Cci dans les en-têtes, où il cesserait
d'être caché tout en restant destinataire d'enveloppe.

`date` et `msgid` sont injectables pour que les tests soient déterministes ;
en production on laisse la stdlib les produire.
"""
from __future__ import annotations

import mimetypes
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid
from pathlib import Path
from typing import Protocol

from script.todo.mail.charset import decode_bytes
from script.todo.todo_i18n import t

MAX_QUOTE_LINES = 200


class SmtpError(Exception):
    """Message impossible à construire, ou serveur qui refuse."""


def _as_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _addresses(*header_values) -> list[str]:
    pairs = getaddresses([v for v in header_values if v])
    return [addr for _, addr in pairs if addr]


def build_message(
    account,
    to,
    subject: str,
    body: str,
    *,
    cc=None,
    bcc=None,
    attachments=None,
    in_reply_to: str | None = None,
    references: str | None = None,
    date: str | None = None,
    msgid: str | None = None,
) -> EmailMessage:
    to_list = _as_list(to)
    cc_list = _as_list(cc)
    bcc_list = _as_list(bcc)
    if not (to_list or cc_list or bcc_list):
        raise SmtpError(t("mail_err_message_needs_recipient"))

    msg = EmailMessage()
    msg["From"] = account.from_header()
    if to_list:
        msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = subject
    msg["Date"] = date or formatdate(localtime=True)
    msg["Message-ID"] = msgid or make_msgid(
        domain=account.email.split("@")[-1]
    )
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(body)

    # Le Cci ne va PAS dans les en-têtes : il ne vit que dans l'enveloppe
    # SMTP, que `recipients()` reconstitue.
    if bcc_list:
        msg["X-ERPLibre-Bcc"] = ", ".join(bcc_list)

    for path in attachments or []:
        _attach_file(msg, Path(path))
    return msg


def _attach_file(msg: EmailMessage, path: Path) -> None:
    if not path.is_file():
        raise SmtpError(f"{t('mail_err_attachment_missing')} {path}")
    guessed, _ = mimetypes.guess_type(path.name)
    maintype, _, subtype = (guessed or "application/octet-stream").partition(
        "/"
    )
    msg.add_attachment(
        path.read_bytes(),
        maintype=maintype,
        subtype=subtype or "octet-stream",
        filename=path.name,
    )


def _plain_text(message) -> str:
    """Le texte d'un message, quel que soit son emballage."""
    if isinstance(message, EmailMessage):
        part = message.get_body(("plain",))
        if part is not None:
            return part.get_content()
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True) or b""
                # `decode_bytes` (voir sa docstring) : un charset mal
                # étiqueté ne doit pas faire tomber la réponse ou le
                # transfert.
                return decode_bytes(payload, part.get_content_charset())
        return ""
    payload = message.get_payload(decode=True)
    if payload is None:
        return str(message.get_payload())
    return decode_bytes(payload, message.get_content_charset())


def _quote(text: str) -> str:
    lines = text.splitlines()[:MAX_QUOTE_LINES]
    return "\n".join(f"> {line}" for line in lines)


def build_reply(
    account,
    message,
    body: str,
    *,
    reply_all: bool = False,
    date: str | None = None,
    msgid: str | None = None,
) -> EmailMessage:
    subject = message.get("Subject", "")
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    to = [message.get("Reply-To") or message.get("From", "")]
    cc = []
    if reply_all:
        mine = account.email.lower()
        others = [
            addr
            for addr in _addresses(message.get("To"), message.get("Cc"))
            if addr.lower() != mine
        ]
        already = {a.lower() for a in _addresses(*to)}
        cc = [a for a in others if a.lower() not in already]

    parent_id = (message.get("Message-ID") or "").strip()
    references = " ".join(
        part
        for part in [(message.get("References") or "").strip(), parent_id]
        if part
    )

    return build_message(
        account,
        to,
        subject,
        f"{body}\n\n{_quote(_plain_text(message))}\n",
        cc=cc,
        in_reply_to=parent_id or None,
        references=references or None,
        date=date,
        msgid=msgid,
    )


def build_forward(
    account,
    message,
    to,
    body: str,
    *,
    date: str | None = None,
    msgid: str | None = None,
) -> EmailMessage:
    subject = message.get("Subject", "")
    if not subject.lower().startswith("fwd:"):
        subject = f"Fwd: {subject}"
    msg = build_message(account, to, subject, body, date=date, msgid=msgid)
    forwarded = message
    if not isinstance(forwarded, EmailMessage):
        import email

        forwarded = email.message_from_bytes(
            message.as_bytes(), _class=EmailMessage
        )
    # `add_attachment` dispatche vers `set_message_content` pour un `Message` :
    # ce gestionnaire n'accepte pas `maintype` (toujours "message" pour lui),
    # seulement `subtype` — le passer lève `TypeError` à chaque appel.
    msg.add_attachment(forwarded, subtype="rfc822")
    return msg


def recipients(msg) -> list[str]:
    """Les destinataires d'enveloppe : To, Cc et le Cci gardé à part."""
    seen, out = set(), []
    for addr in _addresses(
        msg.get("To"), msg.get("Cc"), msg.get("X-ERPLibre-Bcc")
    ):
        low = addr.lower()
        if low not in seen:
            seen.add(low)
            out.append(addr)
    return out


class SmtpTransport(Protocol):
    def send_message(
        self, msg, from_addr: str, to_addrs: list[str]
    ) -> None: ...

    def quit(self) -> None: ...


class SmtplibTransport:
    def __init__(self, client) -> None:
        self.client = client

    def send_message(self, msg, from_addr: str, to_addrs: list[str]) -> None:
        self.client.send_message(msg, from_addr=from_addr, to_addrs=to_addrs)

    def quit(self) -> None:
        try:
            self.client.quit()
        except Exception:
            # Best-effort : la connexion peut déjà être fermée par le serveur.
            pass


def connect(account, password: str) -> SmtplibTransport:
    import smtplib

    conf = account.smtp
    try:
        if conf.security == "ssl":
            client = smtplib.SMTP_SSL(conf.host, conf.port, timeout=30)
        else:
            client = smtplib.SMTP(conf.host, conf.port, timeout=30)
            if conf.security == "starttls":
                client.starttls()
        client.login(conf.user, password)
    except Exception as exc:
        # Toute panne réseau ou d'authentification devient une seule erreur
        # de haut niveau, pour un message utile à l'utilisateur.
        raise SmtpError(
            f"{t('mail_err_smtp_connection_prefix')} {conf.host}"
            f" {t('mail_err_connection_refused_suffix')} {exc}"
        ) from exc
    return SmtplibTransport(client)


def send(account, msg, transport: SmtpTransport) -> list[str]:
    """Remet le message. Rend les destinataires servis, lève `SmtpError` sinon."""
    to_addrs = recipients(msg)
    if not to_addrs:
        raise SmtpError(t("mail_err_no_recipient_nothing_sent"))
    outgoing = without_bcc(msg)
    try:
        transport.send_message(outgoing, account.email, to_addrs)
    except Exception as exc:
        # Le serveur peut refuser pour mille raisons (auth, quota,
        # destinataire rejeté) : une seule erreur de haut niveau, avec le
        # texte du serveur conservé pour l'utilisateur.
        raise SmtpError(f"{t('mail_err_send_refused')} {exc}") from exc
    return to_addrs


def without_bcc(msg):
    """Une copie sans le porte-Cci interne.

    PUBLIQUE à dessein : `send()` n'est pas le seul chemin par lequel le
    message quitte la machine. La copie déposée dans le dossier Envoyés part
    par IMAP, et si elle gardait `X-ERPLibre-Bcc` le Cci serait lisible sur le
    serveur — la même fuite, par une autre porte.
    """
    if msg.get("X-ERPLibre-Bcc") is None:
        return msg
    import copy

    clone = copy.deepcopy(msg)
    del clone["X-ERPLibre-Bcc"]
    return clone
