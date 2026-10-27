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
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid
from pathlib import Path
from typing import Protocol

from script.todo.mail.charset import decode_bytes
from script.todo.todo_i18n import t

MAX_QUOTE_LINES = 200


class SmtpAuthError(Exception):
    """Le serveur a REFUSÉ le secret. Distinct d'une panne réseau.

    Même raison qu'`ImapAuthError` : un refus se rattrape en rafraîchissant
    le jeton, une panne réseau se réessaie plus tard.
    """


class SmtpError(Exception):
    """Message impossible à construire, ou serveur qui refuse.

    `code` porte le code de réponse SMTP quand le serveur en a rendu un
    (voir `smtp_code`), `None` sinon : erreur de construction, panne réseau.
    """

    def __init__(self, message: str = "", code: int | None = None):
        super().__init__(message)
        self.code = code

    @property
    def permanent(self) -> bool:
        """Vrai pour un refus 5xx, qu'un nouvel essai ne changerait pas.

        Un code 4xx ou absent est transitoire : le message se réessaie.
        """
        return self.code is not None and 500 <= self.code < 600


# Code SMTP en tête du texte d'une exception qui n'en porte pas en attribut
# (un double de test, ou une couche qui ne garde que le message du serveur).
_LEADING_CODE = re.compile(r"^\s*([245]\d\d)\b")


def smtp_code(exc: BaseException) -> int | None:
    """Le code de réponse SMTP que porte `exc`, ou `None`.

    `SMTPRecipientsRefused` rend le PLUS PETIT code de ses destinataires :
    le refus n'est permanent que si TOUS les destinataires le sont, et un
    seul 4xx suffit à justifier un nouvel essai. `SMTPResponseException`
    (et ses dérivées : `SMTPDataError`, `SMTPSenderRefused`…) rend
    `smtp_code`. À défaut, un code en tête de `str(exc)` est retenu.
    """
    import smtplib

    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = [
            entry[0]
            for entry in (exc.recipients or {}).values()
            if isinstance(entry, tuple) and entry and isinstance(entry[0], int)
        ]
        return min(codes) if codes else None
    if isinstance(exc, smtplib.SMTPResponseException):
        if isinstance(exc.smtp_code, int):
            return exc.smtp_code
    match = _LEADING_CODE.match(str(exc))
    return int(match.group(1)) if match else None


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
    html: str | None = None,
    inline_images: list[InlineImage] | None = None,
    attachment_parts: list[AttachmentPart] | None = None,
    reply_to: str | None = None,
    headers: dict[str, str] | None = None,
) -> EmailMessage:
    """Un message prêt à partir.

    Structure MIME : `text/plain` seul ; avec `html`, une
    `multipart/alternative` (texte puis HTML) ; avec `inline_images`, le HTML
    devient une `multipart/related` qui porte les images citées par `cid:` ;
    toute pièce jointe (`attachment_parts` en octets, puis `attachments` en
    chemins) enveloppe le tout dans une `multipart/mixed`.

    `headers` ajoute des en-têtes libres : ceux de `FORBIDDEN_EXTRA_HEADERS`,
    tout `Content-*`, un nom répété et tout saut de ligne (dans `headers`
    comme dans `reply_to`) sont refusés par `SmtpError`, avant toute
    construction.
    """
    to_list = _as_list(to)
    cc_list = _as_list(cc)
    bcc_list = _as_list(bcc)
    if not (to_list or cc_list or bcc_list):
        raise SmtpError(t("mail_err_message_needs_recipient"))
    if inline_images and not html:
        raise SmtpError(t("mail_err_inline_needs_html"))
    if reply_to and _has_line_break(str(reply_to)):
        raise SmtpError(t("mail_err_header_newline"))
    extra = _checked_headers(headers, reply_to=bool(reply_to))

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
    if reply_to:
        msg["Reply-To"] = reply_to
    for name, value in extra:
        msg[name] = value
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
        if inline_images:
            # `add_related` transforme la partie HTML elle-même en
            # `multipart/related` : les images restent à côté du HTML qui
            # les cite, et non à côté du texte brut.
            html_part = msg.get_body(("html",))
            for image in inline_images:
                html_part.add_related(
                    image.data,
                    image.maintype,
                    image.subtype,
                    cid=f"<{image.cid}>",
                    filename=image.filename,
                    disposition="inline",
                )

    # Le Cci ne va PAS dans les en-têtes : il ne vit que dans l'enveloppe
    # SMTP, que `recipients()` reconstitue.
    if bcc_list:
        msg["X-ERPLibre-Bcc"] = ", ".join(bcc_list)

    for part in attachment_parts or []:
        msg.add_attachment(
            part.data,
            maintype=part.maintype,
            subtype=part.subtype,
            filename=part.filename,
        )
    for path in attachments or []:
        _attach_file(msg, Path(path))
    return msg


# Caractères que `str.splitlines` traite comme une fin de ligne. La
# bibliothèque `email` découpe les valeurs d'en-tête avec `splitlines` et
# lève `ValueError` dès qu'il y a plus d'une ligne : tester « \r » et « \n »
# seuls laisserait passer « \x0b », « \x85 » ou « \u2028 ».
_LINE_BREAKS = "\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"


def _has_line_break(text: str) -> bool:
    return any(c in text for c in _LINE_BREAKS)


def _checked_headers(headers, reply_to: bool = False) -> list[tuple[str, str]]:
    """Les en-têtes libres de `build_message`, validés, dans leur ordre.

    Refuse par `SmtpError` un saut de ligne (au sens de `_LINE_BREAKS`)
    dans un nom ou une valeur : il injecterait un en-tête de plus. Refuse
    par `mail_err_header_forbidden` suivi du nom :
    - un nom réservé par `FORBIDDEN_EXTRA_HEADERS` (comparé en minuscules) ;
    - tout nom en `Content-*` : `set_content` efface ces en-têtes de la
      racine, ils disparaîtraient sans erreur ;
    - `Reply-To` quand `reply_to` est vrai, et un nom présent deux fois
      sans égard à la casse : un en-tête unique posé deux fois fait lever
      `ValueError` à la bibliothèque `email` ;
    - un nom hors des caractères qu'admet un nom de champ (ASCII
      imprimable sans « : ») : « To: x » comme nom produirait une ligne
      lue comme un `To`.
    """
    out = []
    seen = {"reply-to"} if reply_to else set()
    for name, value in (headers or {}).items():
        name, value = str(name), str(value)
        if _has_line_break(name) or _has_line_break(value):
            raise SmtpError(t("mail_err_header_newline"))
        lower = name.lower()
        if (
            not name
            or lower in FORBIDDEN_EXTRA_HEADERS
            or lower.startswith("content-")
            or lower in seen
            or any(not 33 <= ord(c) <= 126 or c == ":" for c in name)
        ):
            raise SmtpError(f"{t('mail_err_header_forbidden')} {name}")
        seen.add(lower)
        out.append((name, value))
    return out


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


def connect(account, secret: str) -> SmtplibTransport:
    """`secret` est un mot de passe ou un jeton, selon `account.auth`."""
    import smtplib

    conf = account.smtp
    try:
        if conf.security == "ssl":
            client = smtplib.SMTP_SSL(conf.host, conf.port, timeout=30)
        else:
            client = smtplib.SMTP(conf.host, conf.port, timeout=30)
            if conf.security == "starttls":
                client.starttls()
        if getattr(account, "auth", "login") == "oauth":
            import base64

            from script.todo.mail.imap_transport import xoauth2_chain

            # `ehlo()` explicite : `login()` le fait pour nous, `docmd` non.
            # Sans lui, le serveur n'a pas encore annoncé ses mécanismes et
            # refuse la commande sans dire pourquoi.
            client.ehlo()
            jeton = base64.b64encode(xoauth2_chain(conf.user, secret)).decode()
            code, reponse = client.docmd("AUTH", f"XOAUTH2 {jeton}")
            if code != 235:
                raise SmtpAuthError(
                    f"{t('mail_err_token_refused')} {conf.host} :"
                    f" {code} {reponse!r}"
                )
        else:
            client.login(conf.user, secret)
    except SmtpAuthError:
        raise
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
        # texte du serveur conservé pour l'utilisateur, et son code pour
        # distinguer un refus permanent d'un échec à réessayer.
        raise SmtpError(
            f"{t('mail_err_send_refused')} {exc}", code=smtp_code(exc)
        ) from exc
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


# -- Contrats de la réponse automatique -------------------------------------
# Types et constantes partagés par la construction des messages et le moteur
# de règles. `build_message` et `build_auto_reply` les consomment.


@dataclass(frozen=True)
class InlineImage:
    """Image affichée DANS le corps HTML, référencée par `cid:`.

    `cid` est sans chevrons : la construction pose l'en-tête `Content-ID`
    sous la forme `<cid>`, et le HTML la cite en `cid:<valeur>` sans eux.
    `maintype` vaut toujours « image » ; `subtype` est l'un de « png »,
    « jpeg », « gif », « webp ».
    """

    cid: str
    data: bytes
    maintype: str
    subtype: str
    filename: str


@dataclass(frozen=True)
class AttachmentPart:
    """Pièce jointe fournie en octets, et non par un chemin sur le disque.

    Le moteur de règles lit lui-même ses images (contrôle d'empreinte) : il
    passe les octets plutôt qu'un chemin que `build_message` relirait.
    """

    data: bytes
    maintype: str
    subtype: str
    filename: str


# En-têtes que `headers=` ne peut ni poser ni remplacer : ils portent
# l'adressage, l'enfilage ou la structure MIME, que `build_message` construit
# lui-même. Comparés en minuscules.
FORBIDDEN_EXTRA_HEADERS = frozenset(
    h.lower()
    for h in (
        "From",
        "To",
        "Cc",
        "Bcc",
        "Subject",
        "Date",
        "Message-ID",
        "In-Reply-To",
        "References",
        "X-ERPLibre-Bcc",
        "Content-Type",
        "MIME-Version",
        "Content-Transfer-Encoding",
        "Content-Disposition",
    )
)
# Valeurs d'`Auto-Submitted` (RFC 3834) : une réponse à un message reçu, ou
# un message engendré sans message déclencheur.
AUTO_SUBMITTED_REPLIED = "auto-replied"
AUTO_SUBMITTED_GENERATED = "auto-generated"
# Marqueur posé dans `X-Loop` de chaque envoi automatique ; un message reçu
# qui le porte n'obtient jamais de réponse automatique.
X_LOOP_MARKER = "erplibre-rules"
# Préfixe du sujet d'une réponse automatique sans gabarit.
AUTO_SUBJECT_PREFIX = "Auto:"


def auto_reply_subject(original_subject: str, template: str = "") -> str:
    """Le sujet d'une réponse automatique, sur une seule ligne.

    Sans gabarit, ou avec un gabarit fait de blancs seulement :
    `AUTO_SUBJECT_PREFIX` suivi du sujet reçu, sans doubler
    un préfixe déjà présent (comparé sans casse). Avec gabarit : la SEULE
    variable `{subject}` y est remplacée par `str.replace`, jamais
    `str.format` — le sujet vient d'un tiers, et ses accolades restent du
    texte. Les retours à la ligne et blancs répétés se réduisent à une
    espace.
    """
    subject = " ".join((original_subject or "").split())
    if template and template.strip():
        result = template.replace("{subject}", subject)
    elif subject.lower().startswith(AUTO_SUBJECT_PREFIX.lower()):
        result = subject
    else:
        result = f"{AUTO_SUBJECT_PREFIX} {subject}"
    return " ".join(result.split())


def build_auto_reply(
    account,
    to: str,
    subject: str,
    body: str,
    *,
    in_reply_to: str = "",
    references: str = "",
    html: str | None = None,
    inline_images: list[InlineImage] | None = None,
    attachment_parts: list[AttachmentPart] | None = None,
    auto_submitted: str = AUTO_SUBMITTED_REPLIED,
    date: str | None = None,
    msgid: str | None = None,
) -> EmailMessage:
    """Une réponse automatique à un message reçu, conforme à la RFC 3834.

    Porte `Auto-Submitted`, `X-Auto-Response-Suppress: All` et `X-Loop`
    (`X_LOOP_MARKER` suivi de l'adresse du compte), que les répondeurs
    respectueux lisent pour ne pas répondre à leur tour. Ne cite JAMAIS le
    message d'origine : son texte, écrit par un tiers, ne repart pas vers
    une adresse que rien n'a vérifiée.

    `in_reply_to`, `references` et `subject` viennent d'un tiers et sont
    DÉPLIÉS d'abord : un en-tête plié garde son CRLF, et `EmailMessage`
    lève `ValueError` sur une valeur qui en contient. Des deux premiers, seuls
    restent les identifiants que retient `_msgid_tokens`. `subject` est pris
    tel quel par ailleurs (l'appelant passe `auto_reply_subject(...)`). `to`
    est l'adresse telle que reçue, jamais sa forme IDNA normalisée, que
    `smtplib` refuse sans SMTPUTF8 ; vide, il fait lever `SmtpError` comme
    un message sans destinataire.
    """
    irt = " ".join(_msgid_tokens(in_reply_to))
    refs = " ".join(_msgid_tokens(references) + ([irt] if irt else []))
    return build_message(
        account,
        [to] if (to or "").strip() else [],
        " ".join((subject or "").split()),
        body,
        in_reply_to=irt or None,
        references=refs or None,
        date=date,
        msgid=msgid,
        html=html,
        inline_images=inline_images,
        attachment_parts=attachment_parts,
        headers={
            "Auto-Submitted": auto_submitted,
            "X-Auto-Response-Suppress": "All",
            "X-Loop": f"{X_LOOP_MARKER} {account.email}",
        },
    )


# Longueur au-delà de laquelle un identifiant de message est écarté : une
# ligne d'en-tête ne dépasse pas 998 caractères (RFC 5322), et le pliage ne
# coupe pas à l'intérieur d'un identifiant.
MAX_MSGID_LEN = 900


def _msgid_tokens(value: str) -> list[str]:
    """Les identifiants de `value` qu'un en-tête d'enfilage peut porter.

    Découpe sur les blancs (ce qui déplie un en-tête plié) et ne garde que
    les jetons en ASCII imprimable d'au plus `MAX_MSGID_LEN` caractères :
    un caractère non ASCII dans `In-Reply-To` ou `References` fait échouer
    `as_bytes()` bien après la construction, et un jeton trop long produit
    une ligne que le serveur peut refuser.
    """
    return [
        tok
        for tok in (value or "").split()
        if len(tok) <= MAX_MSGID_LEN and all(33 <= ord(c) <= 126 for c in tok)
    ]
