#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le moteur de synchronisation, séparé de ce qui parle vraiment IMAP.

`Syncer` ne connaît qu'un PROTOCOLE (`ImapTransport`). C'est ce qui permet de
l'exercer entièrement contre un serveur en mémoire, sans réseau ni compte, et
c'est ce qui garde le décodage verbeux d'`imaplib` dans son propre fichier.

Une passe est incrémentale par construction : on demande les UID strictement
supérieurs au dernier connu. Le seul cas qui force une reprise à zéro est le
changement d'UIDVALIDITY — le serveur annonce alors que ses UID ne veulent
plus rien dire, et garder l'ancien cache produirait des messages faux.

Les corps ne descendent JAMAIS pendant une passe : une boîte de 20 000
messages doit se synchroniser en secondes, pas en gigaoctets.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

from script.todo.mail.charset import decode_bytes
from script.todo.mail.store import MessageMeta

SNIPPET_LEN = 200

_logger = logging.getLogger(__name__)


@dataclass
class FolderInfo:
    name: str
    display: str = ""
    role: str | None = None
    # `\Noselect` / `\NonExistent` : un NIVEAU de la hiérarchie, pas une
    # boîte. Gmail expose « [Gmail] » ainsi, simple parent de « [Gmail]/Sent
    # Mail » et consorts. Le SELECTionner répond NO — c'est normal, et le
    # serveur le dit d'avance dans les drapeaux de LIST.
    selectable: bool = True


@dataclass
class SelectInfo:
    uidvalidity: int
    uidnext: int
    exists: int


@dataclass
class HeaderInfo:
    uid: int
    date: int
    size: int
    flags: str
    msgid: str
    frm: str
    to: str
    subject: str


@dataclass
class SyncReport:
    folders: int = 0
    new_messages: int = 0
    purged: list = field(default_factory=list)
    errors: list = field(default_factory=list)


class ImapTransport(Protocol):
    """Ce dont le moteur a besoin. `imap_transport.ImaplibTransport` l'implémente."""

    def list_folders(self) -> list[FolderInfo]: ...

    def select(self, folder: str) -> SelectInfo: ...

    def search_uids(self, since_uid: int) -> list[int]: ...

    def fetch_headers(self, uids: list[int]) -> list[HeaderInfo]: ...

    def fetch_flags(self, uids: list[int]) -> list[tuple[int, str]]: ...

    def fetch_body(self, uid: int) -> bytes: ...

    def store_flags(
        self, uid: int, add: list[str], remove: list[str]
    ) -> None: ...

    def append(self, folder: str, raw: bytes, flags: list[str]) -> None: ...

    def logout(self) -> None: ...


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def snippet_from_raw(raw: bytes, length: int = SNIPPET_LEN) -> str:
    """Les premiers mots du corps, pour la colonne d'aperçu de la liste."""
    import email

    try:
        msg = email.message_from_bytes(raw)
    except Exception:
        return ""
    part = msg
    if msg.is_multipart():
        part = next(
            (p for p in msg.walk() if p.get_content_type() == "text/plain"),
            None,
        )
        if part is None:
            return ""
    try:
        payload = part.get_payload(decode=True) or b""
    except Exception:
        return ""
    # `decode_bytes` (voir sa docstring) : un charset mal étiqueté ne doit
    # pas faire tomber l'ouverture de la boîte.
    text = decode_bytes(payload, part.get_content_charset())
    return " ".join(text.split())[:length]


class Syncer:
    """Une passe de synchronisation, et le téléchargement d'un corps à la demande."""

    BATCH = 200
    FLAG_REFRESH = 500

    def __init__(self, store, transport: ImapTransport) -> None:
        self.store = store
        self.transport = transport

    def sync(self, progress=None) -> SyncReport:
        report = SyncReport()
        for folder in self.transport.list_folders():
            try:
                self._sync_folder(folder, report, progress)
            except Exception as exc:
                # Un dossier qui refuse ne doit pas priver l'utilisateur des autres.
                _logger.exception("sync du dossier %r a échoué", folder.name)
                report.errors.append(f"{folder.name} : {exc}")
            report.folders += 1
        return report

    def sync_one(self, folder_name: str) -> SyncReport:
        """Une passe limitée à `folder_name`, par son nom seul.

        Sert à `deliver()` (`tui.py`) juste après un APPEND réussi dans
        Envoyés, pour que le message parti apparaisse sans attendre la
        prochaine passe complète (design, ligne 308) — sans fabriquer de
        ligne locale : c'est le serveur qui attribue l'UID, en inventer un
        entrerait en collision avec un futur message réel. Ne connaissant
        que le nom, on passe un `FolderInfo` sans `display`/`role` ; le
        COALESCE de `store.upsert_folder` garde ceux déjà appris d'un LIST
        complet.

        Ne lève jamais, à l'image de `sync()` par dossier : cette sync est
        un confort, pas une garantie — un envoi déjà réussi ne doit jamais
        se lire comme un échec parce que cette relecture a raté.
        """
        report = SyncReport()
        try:
            self._sync_folder(FolderInfo(name=folder_name), report, None)
        except Exception as exc:
            _logger.exception(
                "sync ciblée du dossier %r a échoué", folder_name
            )
            report.errors.append(f"{folder_name} : {exc}")
        report.folders = 1
        return report

    def _sync_folder(
        self, folder: FolderInfo, report: SyncReport, progress
    ) -> None:
        fid = self.store.upsert_folder(
            folder.name, folder.display, folder.role
        )
        if not folder.selectable:
            # Enregistré ci-dessus pour rester dans l'arbre — c'est un
            # niveau de hiérarchie visible — mais on ne va pas plus loin :
            # le SELECT répondrait NO, et cette erreur salissait CHAQUE
            # synchronisation Gmail sans rien signaler d'anormal. Un
            # journal qui crie sur du normal fait rater ce qui ne l'est pas.
            return
        info = self.transport.select(folder.name)
        state = self.store.folder_state(folder.name) or {}

        known_validity = state.get("uidvalidity")
        if known_validity is not None and known_validity != info.uidvalidity:
            self.store.purge_folder(folder.name)
            report.purged.append(folder.name)
            state = self.store.folder_state(folder.name) or {}

        self.store.set_folder_state(
            folder.name, uidvalidity=info.uidvalidity, uidnext=info.uidnext
        )

        last_uid = state.get("last_uid") or 0
        uids = self.transport.search_uids(last_uid + 1)
        done = 0
        for batch in _chunks(uids, self.BATCH):
            headers = self.transport.fetch_headers(batch)
            self.store.upsert_messages(
                fid,
                [
                    MessageMeta(
                        uid=h.uid,
                        date=h.date,
                        size=h.size,
                        flags=h.flags,
                        msgid=h.msgid,
                        frm=h.frm,
                        to=h.to,
                        subject=h.subject,
                        snippet="",
                    )
                    for h in headers
                ],
            )
            report.new_messages += len(headers)
            done += len(batch)
            if progress:
                progress(folder.name, done, len(uids))
        if uids:
            self.store.set_folder_state(folder.name, last_uid=max(uids))

        # Les drapeaux des messages déjà connus changent sans que l'UID bouge :
        # un « lu » ailleurs ne serait jamais vu sans cette relecture.
        known = self.store.known_uids(fid, self.FLAG_REFRESH)
        if known:
            for uid, flags in self.transport.fetch_flags(known):
                self.store.update_flags(fid, uid, flags)

        self.store.set_folder_state(
            folder.name,
            total=info.exists,
            unseen=self.store.count_unseen(fid),
            synced_at=int(time.time()),
        )

    def fetch_body(self, folder_name: str, uid: int) -> bytes:
        """Le corps, du cache s'il y est, du serveur sinon."""
        cached = self.store.read_body(folder_name, uid)
        if cached is not None:
            return cached
        self.transport.select(folder_name)
        raw = self.transport.fetch_body(uid)
        self.store.write_body(folder_name, uid, raw)
        state = self.store.folder_state(folder_name)
        if state:
            self.store.set_snippet(state["id"], uid, snippet_from_raw(raw))
        return raw
