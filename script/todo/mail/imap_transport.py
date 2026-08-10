#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La seule couche qui parle vraiment IMAP.

Choix qui explique tout le reste du fichier : on ne décode PAS `ENVELOPE`.
`BODY.PEEK[HEADER.FIELDS (...)]` rend des en-têtes RFC822 bruts, que le module
`email` de la stdlib sait déjà lire — encodages, mots encodés, dates comprises.
Analyser `ENVELOPE` à la main coûterait cent lignes de plus, toutes fausses
sur un cas limite ou l'autre.

`BODY.PEEK` et non `BODY` : lire un message dans le TUI ne doit pas le marquer
lu sur le serveur à l'insu de l'utilisateur.
"""
from __future__ import annotations

import email
import email.utils
import re
from email.header import decode_header
from email.parser import BytesHeaderParser

from script.todo.mail.charset import decode_bytes
from script.todo.mail.imap_sync import FolderInfo, HeaderInfo, SelectInfo
from script.todo.todo_i18n import t

HEADER_FIELDS = "FROM TO SUBJECT DATE MESSAGE-ID"

SPECIAL_USE = {
    "\\Sent": "sent",
    "\\Drafts": "drafts",
    "\\Trash": "trash",
    "\\Junk": "junk",
    "\\Archive": "archive",
    "\\All": "archive",
}

_UID_RE = re.compile(rb"UID\s+(\d+)")
_SIZE_RE = re.compile(rb"RFC822\.SIZE\s+(\d+)")
_FLAGS_RE = re.compile(rb"FLAGS\s+\(([^)]*)\)")
_LIST_RE = re.compile(rb'^\(([^)]*)\)\s+("[^"]*"|NIL)\s+(.*)$')


class ImapError(Exception):
    """Le serveur a refusé, ou a répondu quelque chose d'inattendu."""


def decode_header_value(raw: str | None) -> str:
    """Un en-tête RFC 2047 rendu en texte lisible, sans jamais lever."""
    if not raw:
        return ""
    try:
        parts = decode_header(raw)
    except Exception:
        # `raw` vient du serveur : un en-tête mal formé ne doit jamais faire
        # tomber l'affichage d'un message.
        return str(raw)
    out = []
    for value, charset in parts:
        if isinstance(value, bytes):
            out.append(decode_bytes(value, charset))
        else:
            out.append(value)
    return "".join(out).strip()


def decode_mailbox(name: str) -> str:
    """Nom de boîte en UTF-7 modifié (RFC 3501) rendu lisible.

    Sur entrée invalide on rend le nom d'origine : un affichage imparfait vaut
    mieux qu'un dossier qu'on n'arrive plus à sélectionner.
    """
    if "&" not in name:
        return name
    try:
        out = []
        for chunk in name.split("&"):
            if not out:
                out.append(chunk)
                continue
            encoded, sep, rest = chunk.partition("-")
            if not sep:
                raise ValueError(t("mail_err_unterminated_ampersand"))
            if encoded == "":
                out.append("&" + rest)
            else:
                pad = "=" * (-len(encoded) % 4)
                decoded = (encoded.replace(",", "/") + pad).encode("ascii")
                import base64

                out.append(
                    base64.b64decode(decoded).decode("utf-16-be") + rest
                )
        return "".join(out)
    except Exception:
        # Nom de boîte mal formé : on garde l'original plutôt que de perdre
        # l'accès au dossier pour une simple erreur d'affichage.
        return name


def parse_list_line(line: bytes) -> FolderInfo:
    """Une ligne de réponse LIST → nom, nom affichable, rôle."""
    match = _LIST_RE.match(line.strip())
    if not match:
        raw_name = line.decode("utf-8", "replace").strip().strip('"')
        return FolderInfo(name=raw_name, display=decode_mailbox(raw_name))
    flags = match.group(1).decode("ascii", "replace").split()
    name = match.group(3).decode("utf-8", "replace").strip().strip('"')
    role = next((SPECIAL_USE[f] for f in flags if f in SPECIAL_USE), None)
    if role is None and name.upper() == "INBOX":
        role = "inbox"
    bas = {f.lower() for f in flags}
    return FolderInfo(
        name=name,
        display=decode_mailbox(name),
        role=role,
        selectable=not (bas & {"\\noselect", "\\nonexistent"}),
    )


def parse_fetch_headers(data: list) -> list[HeaderInfo]:
    """Réponse FETCH d'en-têtes → une liste de `HeaderInfo`."""
    parser = BytesHeaderParser()
    out = []
    for index, item in enumerate(data):
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        prefix, raw_headers = item[0], item[1]
        # Les attributs peuvent SUIVRE le littéral au lieu de le précéder :
        # RFC 3501 n'impose aucun ordre, et `imaplib` rend alors la fin de la
        # ligne dans l'entrée suivante, hors du tuple. Ne lire que le préfixe
        # ferait disparaître le message SANS erreur — et comme le moteur
        # avance `last_uid` derrière, il ne serait jamais réessayé.
        trailer = b""
        if index + 1 < len(data) and isinstance(
            data[index + 1], (bytes, bytearray)
        ):
            trailer = bytes(data[index + 1])
        meta = bytes(prefix) + b" " + trailer
        uid_match = _UID_RE.search(meta)
        if not uid_match:
            continue
        size_match = _SIZE_RE.search(meta)
        flags_match = _FLAGS_RE.search(meta)
        msg = parser.parsebytes(raw_headers)
        date_raw = msg.get("Date")
        try:
            # `str()` d'abord : un `Date:` porteur d'octets 8 bits bruts —
            # vu en boîte réelle — fait renvoyer un `Header` et non une
            # chaîne, et `parsedate_to_datetime` y lève un AttributeError
            # que ce `except` ne rattrapait pas. Une seule date illisible
            # emportait alors la synchro du dossier ENTIER.
            stamp = (
                int(
                    email.utils.parsedate_to_datetime(
                        str(date_raw)
                    ).timestamp()
                )
                if date_raw
                else 0
            )
        except (TypeError, ValueError, AttributeError, OverflowError):
            # Une date est une commodité d'affichage : aucune valeur
            # d'en-tête ne justifie de perdre le message.
            stamp = 0
        out.append(
            HeaderInfo(
                uid=int(uid_match.group(1)),
                date=stamp,
                size=int(size_match.group(1)) if size_match else 0,
                flags=(
                    flags_match.group(1).decode("ascii", "replace")
                    if flags_match
                    else ""
                ),
                msgid=(msg.get("Message-ID") or "").strip(),
                frm=decode_header_value(msg.get("From")),
                to=decode_header_value(msg.get("To")),
                subject=decode_header_value(msg.get("Subject")),
            )
        )
    return out


class ImaplibTransport:
    """`ImapTransport` réalisé sur `imaplib`. Le client est injecté : les tests
    passent un double, la production passe une connexion TLS."""

    def __init__(self, client) -> None:
        self.client = client

    @staticmethod
    def _ok(result, label: str):
        status, data = result
        if status != "OK":
            raise ImapError(
                f"{label} {t('mail_err_server_replied')} {status} ({data!r})"
            )
        return data

    def list_folders(self) -> list[FolderInfo]:
        data = self._ok(self.client.list(), "LIST")
        return [parse_list_line(line) for line in data if line]

    def select(self, folder: str) -> SelectInfo:
        data = self._ok(self.client.select(f'"{folder}"'), f"SELECT {folder}")
        exists = int(data[0]) if data and data[0] else 0
        return SelectInfo(
            uidvalidity=int(
                self._first(self.client.response("UIDVALIDITY")) or 0
            ),
            uidnext=int(self._first(self.client.response("UIDNEXT")) or 0),
            exists=exists,
        )

    @staticmethod
    def _first(response) -> bytes | None:
        _, data = response
        return data[0] if data and data[0] else None

    def search_uids(self, since_uid: int) -> list[int]:
        data = self._ok(
            self.client.uid("SEARCH", None, f"UID {since_uid}:*"), "SEARCH"
        )
        raw = (data[0] or b"").split()
        # `UID n:*` rend toujours au moins un UID, même inférieur à n quand la
        # boîte est plus courte : on refiltre côté client.
        return [int(u) for u in raw if int(u) >= since_uid]

    def fetch_headers(self, uids: list[int]) -> list[HeaderInfo]:
        if not uids:
            return []
        spec = f"(UID FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})])"
        data = self._ok(
            self.client.uid("FETCH", ",".join(str(u) for u in uids), spec),
            "FETCH HEADERS",
        )
        return parse_fetch_headers(data)

    def fetch_flags(self, uids: list[int]) -> list[tuple[int, str]]:
        if not uids:
            return []
        data = self._ok(
            self.client.uid(
                "FETCH", ",".join(str(u) for u in uids), "(UID FLAGS)"
            ),
            "FETCH FLAGS",
        )
        out = []
        for line in data:
            raw = line[0] if isinstance(line, tuple) else line
            if not isinstance(raw, (bytes, bytearray)):
                continue
            uid_match = _UID_RE.search(raw)
            flags_match = _FLAGS_RE.search(raw)
            if uid_match:
                out.append(
                    (
                        int(uid_match.group(1)),
                        (
                            flags_match.group(1).decode("ascii", "replace")
                            if flags_match
                            else ""
                        ),
                    )
                )
        return out

    def fetch_body(self, uid: int) -> bytes:
        data = self._ok(
            self.client.uid("FETCH", str(uid), "(BODY.PEEK[])"), "FETCH BODY"
        )
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                return item[1]
        raise ImapError(f"{t('mail_err_no_body_for_uid')} {uid}")

    def store_flags(self, uid: int, add: list[str], remove: list[str]) -> None:
        if add:
            self._ok(
                self.client.uid(
                    "STORE", str(uid), "+FLAGS", f"({' '.join(add)})"
                ),
                "STORE +FLAGS",
            )
        if remove:
            self._ok(
                self.client.uid(
                    "STORE", str(uid), "-FLAGS", f"({' '.join(remove)})"
                ),
                "STORE -FLAGS",
            )

    def append(self, folder: str, raw: bytes, flags: list[str]) -> None:
        self._ok(
            self.client.append(
                f'"{folder}"', f"({' '.join(flags)})", None, raw
            ),
            f"APPEND {folder}",
        )

    def logout(self) -> None:
        """Fermer proprement est souhaitable, pas indispensable : on n'échoue
        jamais sur la sortie."""
        try:
            self.client.logout()
        except Exception:
            # Best-effort : la connexion peut déjà être fermée par le serveur.
            pass


def connect(account, password: str) -> ImaplibTransport:
    """Ouvre une connexion TLS et se connecte. Lève `ImapError` sur refus."""
    import imaplib

    conf = account.imap
    try:
        if conf.security == "ssl":
            client = imaplib.IMAP4_SSL(conf.host, conf.port, timeout=30)
        else:
            client = imaplib.IMAP4(conf.host, conf.port, timeout=30)
            if conf.security == "starttls":
                client.starttls()
        client.login(conf.user, password)
    except UnicodeEncodeError as exc:
        # `imaplib` encode la commande LOGIN en ASCII : un mot de passe
        # accentué n'atteint même pas le serveur. Ce cas sort AVANT le
        # rattrapage général, dont le préfixe dit « refusée » — or personne
        # n'a rien refusé, et l'ancien message « ordinal not in range(128) »
        # accusait le serveur d'un refus qu'il n'a jamais prononcé.
        raise ImapError(t("mail_err_password_not_ascii")) from exc
    except Exception as exc:
        # Toute panne réseau ou d'authentification devient une seule erreur
        # de haut niveau, pour un message utile à l'utilisateur.
        raise ImapError(
            f"{t('mail_err_imap_connection_prefix')} {conf.host}"
            f" {t('mail_err_connection_refused_suffix')} {exc}"
        ) from exc
    return ImaplibTransport(client)
