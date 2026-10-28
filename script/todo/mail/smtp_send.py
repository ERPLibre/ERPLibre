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

import email
import email.errors
import email.policy
import html
import logging
import mimetypes
import re
import unicodedata
from dataclasses import dataclass
from email.message import EmailMessage, MIMEPart
from email.parser import BytesHeaderParser
from email.utils import formatdate, getaddresses, make_msgid
from pathlib import Path
from typing import Protocol

from script.todo.mail.charset import decode_bytes
from script.todo.todo_i18n import t

MAX_QUOTE_LINES = 200

_logger = logging.getLogger(__name__)


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

    def send_raw(
        self, raw: bytes, from_addr: str, to_addrs: list[str]
    ) -> None: ...

    def quit(self) -> None: ...


class SmtplibTransport:
    def __init__(self, client) -> None:
        self.client = client

    def send_message(self, msg, from_addr: str, to_addrs: list[str]) -> None:
        self.client.send_message(msg, from_addr=from_addr, to_addrs=to_addrs)

    def send_raw(
        self, raw: bytes, from_addr: str, to_addrs: list[str]
    ) -> None:
        """Remet `raw` octet pour octet par `sendmail`, après `to_crlf`.

        Jamais `send_message`, qui re-sérialise le message (en-têtes
        repliés, signature DKIM cassée) et lève `ValueError` sur un message
        qui porte deux `Resent-Date`. `smtplib` ne normalise pas les fins
        de ligne d'octets : `to_crlf` les rend toutes CRLF, sans quoi un
        CR nu échapperait au doublement des points en début de ligne.
        `BODY=8BITMIME` n'est demandé que si les octets en ont un ≥ 0x80
        et que le serveur l'annonce ; SMTPUTF8 ne l'est jamais.
        """
        data = to_crlf(raw)
        options = []
        if not data.isascii():
            self.client.ehlo_or_helo_if_needed()
            if self.client.has_extn("8bitmime"):
                options = ["BODY=8BITMIME"]
        self.client.sendmail(from_addr, to_addrs, data, mail_options=options)

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
    """Remet le message. Rend les destinataires servis, lève `SmtpError` sinon.

    Un `RawOutgoing` part par `transport.send_raw` à son enveloppe telle
    quelle : elle ne passe jamais par `recipients()`, et ses octets ne
    sont pas relus. Tout autre message part par `send_message` aux
    destinataires de `recipients()`, sans le Cci interne.
    """
    raw = isinstance(msg, RawOutgoing)
    to_addrs = list(msg.envelope) if raw else recipients(msg)
    if not to_addrs:
        raise SmtpError(t("mail_err_no_recipient_nothing_sent"))
    try:
        if raw:
            transport.send_raw(msg.raw, account.email, to_addrs)
        else:
            transport.send_message(without_bcc(msg), account.email, to_addrs)
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


# -- Transfert et redirection d'un message reçu ------------------------------

# Préfixe du sujet d'un transfert ; comparé sans casse.
FORWARD_SUBJECT_PREFIX = "Fwd:"
# Champs retirés des octets d'une redirection et de l'original joint d'un
# transfert : le Cci (d'origine ou d'une redirection antérieure) resterait
# sinon lisible par les destinations, `X-ERPLibre-Bcc` est le Cci interne
# que `recipients()` change en destinataire d'enveloppe, et Return-Path est
# reposé par le serveur de remise final.
REDIRECT_DROPPED_FIELDS = frozenset(
    {"bcc", "resent-bcc", "return-path", "x-erplibre-bcc"}
)
# Destinataire visible d'un transfert : un groupe vide ; les destinations
# vont dans le Cci interne.
UNDISCLOSED_RECIPIENTS = "undisclosed-recipients:;"
# Types dont on ne modifie pas le texte, où qu'ils soient dans le message :
# la signature doit rester vérifiable, le transfert part donc en pièce
# jointe.
_SEALED_TYPES = frozenset(
    {
        "multipart/signed",
        "multipart/encrypted",
        "application/pkcs7-mime",
        "application/x-pkcs7-mime",
    }
)
# Marque d'un texte signé ou chiffré par PGP en ligne : le recoder
# casserait la signature.
_INLINE_PGP = "-----BEGIN PGP "
# Exceptions d'une modification ou d'une sérialisation qui font replier un
# transfert dans le corps sur un transfert en pièce jointe.
_INLINE_FAILURES = (
    LookupError,
    UnicodeError,
    ValueError,
    TypeError,
    AttributeError,
    email.errors.MessageError,
)

# Partie locale admise : dot-atom (RFC 5322), ASCII seul.
_ATEXT = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
_LOCAL_RE = re.compile(rf"{_ATEXT}(?:\.{_ATEXT})*")
_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_LOCAL_MAX = 64
_DOMAIN_MAX = 253
_ADDRESS_MAX = 254
_BODY_TAG_RE = re.compile(r"<body\b[^>]*>", re.IGNORECASE)
_EOL_RE = re.compile(rb"\r\n|\r|\n")
# Caractères que le codec `idna` (IDNA 2003) transforme là où IDNA 2008
# les encode : « ß » et « ẞ » deviennent « ss », « ς » devient « σ »,
# ZWNJ et ZWJ disparaissent. Le domaine converti en serait un autre.
_IDNA_DEVIATIONS = frozenset("\u00df\u1e9e\u03c2\u200c\u200d")
_FOLD_RE = re.compile(r"(?:\r\n|\r|\n)[ \t]*")


def smtp_address(text: str) -> str:
    """La forme d'envoi d'une adresse saisie : partie locale telle quelle,
    domaine IDNA (ACE) en minuscules, ASCII seul.

    Admis : une partie locale dot-atom ASCII d'au plus 64 caractères, puis
    un domaine (Unicode accepté) que le codec `idna` convertit et sait
    relire, d'au moins deux labels `[a-z0-9]` (tiret intérieur admis),
    d'au plus 253 caractères, dont le dernier label n'est pas entièrement
    numérique ; l'adresse entière fait au plus 254 caractères. Refusés par
    `SmtpError` (`mail_rules_err_fwd_address` suivi du repr de `text`) :
    partie locale entre guillemets ou non ASCII (SMTPUTF8 n'est pas pris
    en charge), littéral IP, blanc, virgule, chevrons, `xn--` invalide,
    domaine qui porte un caractère que IDNA 2003 et IDNA 2008 convertissent
    différemment (« ß », « ς », ZWNJ, ZWJ) : l'adresse envoyée ne serait
    pas celle saisie.
    """
    erreur = SmtpError(f"{t('mail_rules_err_fwd_address')} {text!r}")
    if not isinstance(text, str):
        raise erreur
    local, arobase, domaine = text.rpartition("@")
    if not arobase or len(local) > _LOCAL_MAX:
        raise erreur
    if not _LOCAL_RE.fullmatch(local):
        raise erreur
    if _IDNA_DEVIATIONS.intersection(unicodedata.normalize("NFC", domaine)):
        raise erreur
    try:
        ace = domaine.encode("idna").decode("ascii").lower()
        ace.encode("ascii").decode("idna")
    except (UnicodeError, ValueError):
        raise erreur from None
    labels = ace.split(".")
    if (
        len(ace) > _DOMAIN_MAX
        or len(labels) < 2
        or not all(_LABEL_RE.fullmatch(label) for label in labels)
        or labels[-1].isdigit()
    ):
        raise erreur
    adresse = f"{local}@{ace}"
    if len(adresse) > _ADDRESS_MAX:
        raise erreur
    return adresse


def parse_envelope(text: str) -> tuple[str, ...]:
    """Les adresses d'une enveloppe stockée « a, b », dans leur ordre.

    Coupe sur « , », ignore les morceaux vides, passe chaque adresse par
    `smtp_address` (qui lève `SmtpError` sur une adresse refusée) et
    dédoublonne sans égard à la casse. Aucune adresse : `SmtpError`
    (`mail_err_no_recipient_nothing_sent`).
    """
    morceaux = [m.strip() for m in (text or "").split(",")]
    adresses = _unique_targets(m for m in morceaux if m)
    if not adresses:
        raise SmtpError(t("mail_err_no_recipient_nothing_sent"))
    return tuple(adresses)


def _unique_targets(addresses) -> list[str]:
    """Les formes d'envoi de `addresses`, sans doublon (casse ignorée)."""
    vues, sortie = set(), []
    for adresse in addresses:
        forme = smtp_address(adresse)
        if forme.lower() not in vues:
            vues.add(forme.lower())
            sortie.append(forme)
    return sortie


def _target_list(to) -> list[str]:
    """Les destinations d'un transfert ou d'une redirection, en forme
    d'envoi et sans doublon ; aucune : `SmtpError`."""
    cibles = _unique_targets(_as_list(to))
    if not cibles:
        raise SmtpError(t("mail_err_message_needs_recipient"))
    return cibles


@dataclass(frozen=True)
class RawOutgoing:
    """Un message remis octet pour octet à une enveloppe explicite.

    `envelope` porte les destinataires SMTP (forme d'envoi) ; aucun en-tête
    du message ne les complète. `subject` est le sujet décodé, pour la file
    et l'écran.
    """

    raw: bytes
    envelope: tuple[str, ...]
    subject: str = ""

    def as_bytes(self) -> bytes:
        return self.raw


def _clean_text(value) -> str:
    """`value` décodé RFC 2047, sur une ligne : chaque caractère de
    contrôle (catégorie Cc, tabulation comprise) ou de format (Cf) devient
    une espace, puis les blancs se réduisent à une espace."""
    from script.todo.mail.imap_transport import decode_header_value

    texte = decode_header_value(str(value or ""))
    texte = "".join(
        " " if unicodedata.category(c) in ("Cc", "Cf") else c for c in texte
    )
    return " ".join(texte.split())


def forward_subject(original_subject: str, prefix: str = "") -> str:
    """Le sujet d'un transfert, sur une ligne.

    Le sujet d'origine est décodé et nettoyé (`_clean_text` : aucun
    caractère de contrôle ne survit, même encodé), puis préfixé de
    `FORWARD_SUBJECT_PREFIX` s'il ne commence pas déjà par lui (casse
    ignorée). `prefix` non vide (essai) précède le tout, séparé d'une
    espace.
    """
    sujet = _clean_text(original_subject)
    if not sujet.lower().startswith(FORWARD_SUBJECT_PREFIX.lower()):
        sujet = f"{FORWARD_SUBJECT_PREFIX} {sujet}".rstrip()
    prefix = " ".join((prefix or "").split())
    return f"{prefix} {sujet}" if prefix else sujet


def _header_value(message, name: str) -> str:
    """La première valeur de `name` dans `message`, ou "" ; un en-tête que
    la bibliothèque ne sait pas analyser compte comme absent."""
    try:
        valeur = message.get(name)
    except _INLINE_FAILURES:
        return ""
    return "" if valeur is None else str(valeur)


def forwarded_fields(original) -> list[tuple[str, str]]:
    """Le bloc d'en-têtes d'origine : [(libellé traduit, valeur)].

    De, Date, À, Cc (omis si vide) et Sujet, dans cet ordre, libellés dans
    la langue de l'interface. Valeurs décodées RFC 2047, dépliées,
    nettoyées par `_clean_text`. `original` est un `EmailMessage`
    (`policy.default`) ou un `Message` compat32.
    """
    champs = []
    for cle, nom in (
        ("mail_rules_fwd_from", "From"),
        ("mail_rules_fwd_date", "Date"),
        ("mail_rules_fwd_to", "To"),
        ("mail_rules_fwd_cc", "Cc"),
        ("mail_rules_fwd_subject", "Subject"),
    ):
        valeur = _clean_text(_header_value(original, nom))
        if nom == "Cc" and not valeur:
            continue
        champs.append((t(cle), valeur))
    return champs


def forward_text_block(intro: str, fields) -> str:
    """Le texte placé en tête d'un transfert.

    L'intro, si elle n'est pas blanche (sans ses blancs de fin, suivie
    d'une ligne vide), puis la ligne séparatrice, une ligne « libellé
    valeur » par champ et une ligne vide.
    """
    lignes = []
    intro = (intro or "").replace("\r\n", "\n").replace("\r", "\n")
    if intro.strip():
        lignes += [intro.rstrip(), ""]
    lignes.append(t("mail_rules_fwd_separator"))
    lignes += [f"{libelle} {valeur}" for libelle, valeur in fields]
    lignes.append("")
    return "\n".join(lignes) + "\n"


def forward_html_block(intro: str, fields) -> str:
    """Le même bloc en HTML : un `<div>` qui porte l'intro (échappée, un
    `<br>` par saut de ligne) dans un `<p>`, puis un `<p>` du séparateur
    et des champs, un par ligne, valeurs échappées."""
    intro = (intro or "").replace("\r\n", "\n").replace("\r", "\n")
    morceaux = ["<div>"]
    if intro.strip():
        morceaux.append(
            "<p>" + html.escape(intro.rstrip()).replace("\n", "<br>") + "</p>"
        )
    lignes = [html.escape(t("mail_rules_fwd_separator"))] + [
        f"{html.escape(libelle)} {html.escape(valeur)}"
        for libelle, valeur in fields
    ]
    morceaux.append("<p>" + "<br>".join(lignes) + "</p>")
    morceaux.append("</div>")
    return "".join(morceaux)


def _with_html_block(document: str, block: str) -> str:
    """`document` avec `block` inséré juste après la première balise
    `<body…>`, ou en tête faute de balise."""
    trouve = _BODY_TAG_RE.search(document)
    if trouve is None:
        return block + document
    return document[: trouve.end()] + block + document[trouve.end() :]


def strip_header_fields(raw: bytes, names) -> bytes:
    """`raw` sans les champs d'en-tête dont le nom est dans `names`.

    Les noms se comparent en minuscules, espaces avant « : » ignorées ; un
    champ retiré part avec ses lignes de suite (qui commencent par un
    blanc). Seule la section d'en-têtes, jusqu'à la première ligne vide
    (`\r\n` ou `\n`), est lue : le corps est rendu tel quel, même s'il
    contient « Bcc: ». Sans ligne vide, tout `raw` est la section
    d'en-têtes. Aucun autre octet ne change ; le parcours est linéaire.
    Seul LF coupe une ligne : un CR nu ne sépare rien, d'où un passage
    préalable par `to_crlf` pour des octets qui seront envoyés.
    """
    retires = {str(n).lower() for n in names}
    sortie = []
    debut = 0
    retirer = False
    taille = len(raw)
    while debut < taille:
        fin = raw.find(b"\n", debut)
        fin = taille if fin < 0 else fin + 1
        ligne = raw[debut:fin]
        if ligne in (b"\n", b"\r\n"):
            sortie.append(raw[debut:])
            break
        if ligne[:1] in (b" ", b"\t"):
            if not retirer:
                sortie.append(ligne)
        else:
            nom, deux_points, _ = ligne.partition(b":")
            retirer = bool(deux_points) and (
                nom.strip().decode("latin-1").lower() in retires
            )
            if not retirer:
                sortie.append(ligne)
        debut = fin
    return b"".join(sortie)


def to_crlf(raw: bytes) -> bytes:
    """`raw` dont chaque fin de ligne (CRLF, CR nu, LF nu) devient CRLF.

    Idempotent. Après lui, il ne reste ni CR ni LF nu : `smtplib` ne
    normalise pas des octets, et ne double un point de début de ligne
    qu'après un LF.
    """
    return _EOL_RE.sub(b"\r\n", raw)


def original_x_loops(src) -> list[str]:
    """Les valeurs des `X-Loop` de la racine de `src`, dans leur ordre.

    Les valeurs sont lues telles que reçues (`raw_items`), puis dépliées :
    une fin de ligne et les blancs qui la suivent deviennent une espace.
    Une valeur vide, qui garde un caractère de contrôle autre que la
    tabulation, un saut de ligne Unicode ou un octet non UTF-8 est
    laissée : elle ne pourrait pas être reposée telle quelle.
    """
    sortie = []
    for nom, valeur in src.raw_items():
        if nom.lower() != "x-loop":
            continue
        texte = _FOLD_RE.sub(" ", str(valeur)).strip()
        if not texte or _has_line_break(texte):
            continue
        try:
            # Un octet non UTF-8 de l'en-tête reçu survit en substitut
            # (surrogate), que l'en-tête reposé ne saurait pas encoder.
            texte.encode("utf-8")
        except UnicodeError:
            continue
        if any(unicodedata.category(c) == "Cc" and c != "\t" for c in texte):
            continue
        sortie.append(texte)
    return sortie


def _forward_headers(account) -> dict[str, str]:
    # X-Loop part à part : il peut se répéter, `headers=` refuse un nom
    # répété.
    return {
        "Auto-Submitted": AUTO_SUBMITTED_GENERATED,
        "X-Auto-Response-Suppress": "All",
    }


def _check_reply_to(reply_to: str) -> None:
    if reply_to and _has_line_break(str(reply_to)):
        raise SmtpError(t("mail_err_header_newline"))


def _check_raw(raw: bytes) -> None:
    """Refuse par `SmtpError` (`mail_rules_err_fwd_unreadable`) des octets
    vides ou sans aucune ligne d'en-tête lisible."""
    if not raw:
        raise SmtpError(t("mail_rules_err_fwd_unreadable"))
    try:
        entetes = BytesHeaderParser().parsebytes(raw)
    except Exception:
        entetes = None
    if entetes is None or not entetes.keys():
        raise SmtpError(t("mail_rules_err_fwd_unreadable"))


def _serialized(msg) -> EmailMessage:
    """`msg`, une fois `as_bytes()` réussi ; un échec devient une erreur de
    construction (`mail_rules_err_fwd_unreadable`), jamais un envoi raté
    puis réessayé."""
    try:
        msg.as_bytes()
    except Exception as exc:
        raise SmtpError(t("mail_rules_err_fwd_unreadable")) from exc
    return msg


class _InlineFallback(Exception):
    """Le message ne se transfère pas dans le corps ; le texte nomme la
    raison, sans rien du contenu."""


def build_forward_inline(
    account,
    raw: bytes,
    to,
    *,
    intro: str = "",
    reply_to: str = "",
    subject_prefix: str = "",
    date: str | None = None,
    msgid: str | None = None,
) -> EmailMessage:
    """Transfert de `raw` dans le corps, à `to` en Cci interne.

    La structure MIME d'origine (alternatives, images liées, pièces
    jointes) est gardée ; seules la première partie `text/plain` et la
    première `text/html` que rend `get_body` reçoivent en tête l'intro et
    le bloc d'en-têtes d'origine (en HTML : juste après `<body…>`). Le
    message analysé est modifié SUR PLACE : une racine à une seule partie
    recopiée dans un message neuf perdrait l'association à son charset.

    Les en-têtes de la racine sont tous remplacés : From du compte, `To:
    undisclosed-recipients:;`, sujet `forward_subject`, Date et Message-ID
    neufs, `Reply-To` s'il est donné, `Auto-Submitted: auto-generated`,
    `X-Auto-Response-Suppress: All`, les `X-Loop` d'origine puis le nôtre,
    les destinations dans `X-ERPLibre-Bcc` ; seuls les `Content-*` et
    `MIME-Version` de la racine sont reposés tels quels. Ni `In-Reply-To`
    ni `References` : un transfert n'est pas une réponse.

    Repli sur `build_forward_attached`, journalisé sans contenu : une
    partie signée ou chiffrée n'importe où dans le message, du PGP en
    ligne, ni texte ni HTML, ou une modification ou une sérialisation qui
    échoue. Lève `SmtpError` sur une destination refusée ou absente, un
    `reply_to` qui porte un saut de ligne, ou des octets illisibles.
    """
    cibles = _target_list(to)
    _check_reply_to(reply_to)
    _check_raw(raw)
    options = dict(
        intro=intro,
        reply_to=reply_to,
        subject_prefix=subject_prefix,
        date=date,
        msgid=msgid,
    )
    try:
        return _inline_message(account, raw, cibles, **options)
    except _InlineFallback as exc:
        raison = str(exc)
    except _INLINE_FAILURES as exc:
        raison = type(exc).__name__
    _logger.info("transfert : repli en pièce jointe (%s)", raison)
    return build_forward_attached(account, raw, cibles, **options)


def _inline_message(
    account, raw, cibles, *, intro, reply_to, subject_prefix, date, msgid
):
    """Le transfert dans le corps. Lève `_InlineFallback` pour un message
    qui ne s'y prête pas, ou l'une des `_INLINE_FAILURES` si la
    modification ou la sérialisation échoue."""
    src = email.message_from_bytes(
        raw, _class=EmailMessage, policy=email.policy.default
    )
    if any(p.get_content_type() in _SEALED_TYPES for p in src.walk()):
        raise _InlineFallback("sealed")
    texte = src.get_body(("plain",))
    page = src.get_body(("html",))
    if texte is None and page is None:
        raise _InlineFallback("no_text")
    champs = forwarded_fields(src)
    boucles = original_x_loops(src)
    sujet = _header_value(src, "Subject")
    contenus = {}
    for partie in (texte, page):
        if partie is not None:
            contenus[id(partie)] = decode_bytes(
                partie.get_payload(decode=True) or b"",
                partie.get_content_charset(),
            )
    if any(_INLINE_PGP in c for c in contenus.values()):
        raise _InlineFallback("inline_pgp")
    if texte is not None:
        _set_text(
            src,
            texte,
            forward_text_block(intro, champs) + contenus[id(texte)],
            "plain",
        )
    if page is not None:
        _set_text(
            src,
            page,
            _with_html_block(
                contenus[id(page)], forward_html_block(intro, champs)
            ),
            "html",
        )
    gardes = [
        (nom, valeur)
        for nom, valeur in src.raw_items()
        if nom.lower().startswith("content-") or nom.lower() == "mime-version"
    ]
    for nom in set(src.keys()):
        del src[nom]
    src["From"] = account.from_header()
    src["To"] = UNDISCLOSED_RECIPIENTS
    src["Subject"] = forward_subject(sujet, subject_prefix)
    src["Date"] = date or formatdate(localtime=True)
    src["Message-ID"] = msgid or make_msgid(
        domain=account.email.split("@")[-1]
    )
    if reply_to:
        src["Reply-To"] = reply_to
    for nom, valeur in _forward_headers(account).items():
        src[nom] = valeur
    for boucle in boucles:
        src["X-Loop"] = boucle
    src["X-Loop"] = f"{X_LOOP_MARKER} {account.email}"
    src["X-ERPLibre-Bcc"] = ", ".join(cibles)
    for nom, valeur in gardes:
        src.set_raw(nom, valeur)
    if not any(nom.lower() == "mime-version" for nom, _ in gardes):
        src["MIME-Version"] = "1.0"
    src.as_bytes()
    return src


def _set_text(src, partie, contenu: str, subtype: str) -> None:
    """Remplace le contenu de `partie` par `contenu` en UTF-8.

    Une sous-partie passe par `MIMEPart.set_content`, qui ne lui ajoute
    pas de `MIME-Version` ; la racine par sa propre méthode.
    """
    if partie is src:
        src.set_content(contenu, subtype=subtype, charset="utf-8")
    else:
        MIMEPart.set_content(partie, contenu, subtype=subtype, charset="utf-8")


def build_forward_attached(
    account,
    raw: bytes,
    to,
    *,
    intro: str = "",
    reply_to: str = "",
    subject_prefix: str = "",
    date: str | None = None,
    msgid: str | None = None,
) -> EmailMessage:
    """Transfert de `raw` en pièce jointe `message/rfc822`, à `to` en Cci
    interne.

    Un message neuf : texte = intro + bloc d'en-têtes d'origine, mêmes
    en-têtes que `build_forward_inline`, puis l'original joint sous le nom
    `message.eml`. L'original joint est lu sur les octets privés des champs
    de `REDIRECT_DROPPED_FIELDS`, retirés après passage en CRLF : aucun Cci
    ne se lit dans la pièce jointe.
    Ses en-têtes longs peuvent être repliés par le générateur. Lève
    `SmtpError` sur une destination refusée ou absente, un `reply_to` qui
    porte un saut de ligne, ou des octets illisibles.
    """
    cibles = _target_list(to)
    _check_reply_to(reply_to)
    _check_raw(raw)
    try:
        inner = email.message_from_bytes(
            strip_header_fields(to_crlf(raw), REDIRECT_DROPPED_FIELDS),
            _class=EmailMessage,
        )
        champs = forwarded_fields(inner)
        boucles = original_x_loops(inner)
        sujet = _header_value(inner, "Subject")
    except _INLINE_FAILURES as exc:
        raise SmtpError(t("mail_rules_err_fwd_unreadable")) from exc
    msg = build_message(
        account,
        [],
        forward_subject(sujet, subject_prefix),
        forward_text_block(intro, champs),
        bcc=cibles,
        reply_to=reply_to or None,
        headers=_forward_headers(account),
        date=date,
        msgid=msgid,
    )
    msg["To"] = UNDISCLOSED_RECIPIENTS
    for boucle in boucles:
        msg["X-Loop"] = boucle
    msg["X-Loop"] = f"{X_LOOP_MARKER} {account.email}"
    try:
        # Sans `maintype` : voir le commentaire de `build_forward`.
        msg.add_attachment(inner, subtype="rfc822", filename="message.eml")
    except _INLINE_FAILURES as exc:
        raise SmtpError(t("mail_rules_err_fwd_unreadable")) from exc
    return _serialized(msg)


def build_redirect(
    account,
    raw: bytes,
    to,
    *,
    date: str | None = None,
    msgid: str | None = None,
) -> RawOutgoing:
    """Vraie redirection de `raw` à l'enveloppe `to`.

    Sortie : un bloc de trois champs `Resent-From` (le compte),
    `Resent-Date`, `Resent-Message-ID`, dans cet ordre, puis les octets
    d'origine passés en CRLF (`to_crlf`), dont seuls les champs de
    `REDIRECT_DROPPED_FIELDS` sont ensuite retirés : un CR nu coupe donc
    les lignes pour le retrait comme pour le serveur qui les reçoit.
    Aucun autre octet ne change : ni sujet, ni `X-Loop`, ni
    `Auto-Submitted`, ni corps. Un bloc `Resent-*` déjà présent reste sous
    le nôtre. Pas de `Resent-To` : il montrerait
    la liste des destinations à chacune. Le sujet rendu est celui
    d'origine, décodé et nettoyé, pour la file et l'écran.

    Lève `SmtpError` sur une destination refusée ou absente, et sur des
    octets vides ou sans ligne d'en-tête lisible.
    """
    cibles = _target_list(to)
    _check_raw(raw)
    bloc = EmailMessage(policy=email.policy.SMTP)
    bloc["Resent-From"] = account.from_header()
    bloc["Resent-Date"] = date or formatdate(localtime=True)
    bloc["Resent-Message-ID"] = msgid or make_msgid(
        domain=account.email.split("@")[-1]
    )
    entete = bloc.as_bytes()
    if entete.endswith(b"\r\n\r\n"):
        entete = entete[:-2]
    sujet = BytesHeaderParser().parsebytes(raw).get("Subject", "")
    return RawOutgoing(
        entete + strip_header_fields(to_crlf(raw), REDIRECT_DROPPED_FIELDS),
        tuple(cibles),
        _clean_text(sujet),
    )
