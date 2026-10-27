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

# Les attributs d'un dossier qui n'est qu'une VUE sur d'autres, chez un
# serveur qui range par étiquettes : les messages « suivis » et « importants »
# se trouvent TOUS dans le dossier `\\All` du même compte. Les synchroniser
# rapporte les mêmes messages une fois de plus chacun.
#
# `\\All` n'y est PAS, et c'est le point délicat : archiver un message revient
# à lui retirer l'étiquette de la boîte de réception, et il ne vit alors plus
# que là. Le sauter rendrait toute l'archive invisible.
VUES_REDONDANTES = ("\\Flagged", "\\Important")

_logger = logging.getLogger(__name__)


@dataclass
class FolderInfo:
    name: str
    display: str = ""
    role: str | None = None
    # `\Noselect` / `\NonExistent` : un NIVEAU de la hiérarchie, pas une
    # boîte. Un fournisseur qui préfixe ses dossiers expose ce préfixe ainsi,
    # simple parent des dossiers qu'il porte. Le SELECTionner répond NO —
    # c'est normal, et le serveur le dit d'avance dans les drapeaux de LIST.
    selectable: bool = True
    # Les drapeaux de la ligne LIST, tels quels. `role` n'en retient que le
    # rôle standard ; un serveur en annonce d'autres, et c'est ce qui permet
    # de reconnaître un dossier qui n'est qu'une VUE sur d'autres.
    attributes: tuple[str, ...] = ()


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
    # Fils de discussion (v2). Bruts : le hachage appartient au cache, seul
    # détenteur du sel.
    in_reply_to: str = ""
    references: str = ""
    # v6 — tous avec défaut : un double de test qui ne les connaît pas
    # construit encore un `HeaderInfo` valide.
    cc: str = ""
    # L'INTERNALDATE du serveur, en secondes UTC ; 0 si inconnue. C'est la
    # date de RÉCEPTION, que l'expéditeur ne choisit pas, contrairement à
    # l'en-tête `Date`.
    internaldate: int = 0
    # Les en-têtes de `imap_transport.EXTRA_HEADERS` présents, clés en
    # minuscules. Plusieurs occurrences sont jointes par "\n" dans l'ordre
    # du message — la première est la plus haute, celle que le dernier MTA
    # a ajoutée — et chacune est dépliée : "\n" n'y sert que de
    # séparateur. Gardés en mémoire seulement, jamais dans le cache.
    extra: dict = field(default_factory=dict)


# Le plafond des en-têtes d'INBOX qu'un rapport transporte. Une première
# synchronisation, ou une UIDVALIDITY changée, rend toute la boîte « neuve » :
# sans plafond, le rapport garderait en mémoire des dizaines de milliers
# d'en-têtes que personne ne traitera.
INBOX_REPORT_MAX = 500


@dataclass
class SyncReport:
    folders: int = 0
    new_messages: int = 0
    purged: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    # Le nom IMAP de la boîte de réception vue par la passe, "" sinon.
    inbox_folder: str = ""
    # Les `HeaderInfo` des UID nouveaux d'INBOX, UID croissants, au plus
    # `INBOX_REPORT_MAX` : les plus hauts sont gardés.
    inbox: list = field(default_factory=list)
    # Vrai quand des UID nouveaux d'INBOX ont été écartés par le plafond.
    inbox_truncated: bool = False


def is_inbox(folder: FolderInfo) -> bool:
    """Vrai pour la boîte de réception : par son rôle, ou par son nom.

    Le nom compte aussi parce qu'un `FolderInfo` peut arriver sans rôle —
    celui que fabrique `sync_one`, ou celui d'un transport qui ne lit pas
    les attributs de LIST. RFC 3501 rend « INBOX » insensible à la casse.
    """
    return folder.role == "inbox" or (folder.name or "").upper() == "INBOX"


def _garder_les_plus_hauts(report: SyncReport) -> None:
    """Trie `report.inbox` par UID et le ramène à `INBOX_REPORT_MAX`.

    Appelée après chaque lot plutôt qu'en fin de dossier seulement : la
    mémoire reste bornée pendant la passe, pour le même résultat.
    """
    report.inbox.sort(key=lambda h: h.uid)
    if len(report.inbox) > INBOX_REPORT_MAX:
        del report.inbox[: len(report.inbox) - INBOX_REPORT_MAX]
        report.inbox_truncated = True


def _meta(h) -> MessageMeta:
    """Un `HeaderInfo` → la ligne de cache correspondante.

    `getattr` pour `internaldate` : un transport de test peut rendre un
    objet qui ne porte que les champs d'avant la v6.
    """
    return MessageMeta(
        uid=h.uid,
        date=h.date,
        size=h.size,
        flags=h.flags,
        msgid=h.msgid,
        frm=h.frm,
        to=h.to,
        subject=h.subject,
        snippet="",
        in_reply_to=h.in_reply_to,
        references=h.references,
        received_at=getattr(h, "internaldate", 0) or 0,
    )


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

    def __init__(
        self,
        store,
        transport: ImapTransport,
        open_transport=None,
        parallele: int = 1,
    ) -> None:
        self.store = store
        self.transport = transport
        # Fabrique un lien SUPPLÉMENTAIRE vers le même compte, sans
        # argument. Sans elle, la passe reste sur le seul lien ouvert : un
        # `imaplib` n'a qu'un dossier sélectionné à la fois, donc deux
        # dossiers ne peuvent pas avancer ensemble dessus.
        self.open_transport = open_transport
        # Le nombre de liens qu'un compte a le droit d'ouvrir en même
        # temps. Les fournisseurs les plafonnent — quelques dizaines chez
        # les plus grands, moins chez les petits — et dépasser ne rend pas
        # une erreur claire : le serveur refuse la connexion suivante.
        self.parallele = max(1, int(parallele or 1))

    def sync(self, progress=None) -> SyncReport:
        """Une passe sur tous les dossiers du compte.

        `progress(dossier, faits, total)` est appelé depuis PLUSIEURS fils
        dès qu'un second lien sert : ce qu'on lui passe doit supporter
        d'être appelé de front.
        """
        lots = self._lots(self._a_synchroniser())
        if len(lots) == 1:
            return self._sync_lot(lots[0], progress)
        return self._sync_parallele(lots, progress)

    def _a_synchroniser(self) -> list:
        """Les dossiers du compte, moins ceux qui ne redisent que d'autres.

        Chez un serveur qui range par ÉTIQUETTES, un message n'est détenu
        qu'une fois et les dossiers en sont des vues : rapporter « suivis »
        et « importants » ramène des messages que le dossier `\\All` du
        même compte contient déjà, sous un autre UID. Trois courriels portant
        sept étiquettes occupent sept lignes de cache.

        Écartés seulement quand le serveur ANNONCE ranger ainsi : ailleurs
        un dossier peut porter `\\Flagged` et contenir des messages qui ne
        sont nulle part d'autre.

        L'annonce se demande par `getattr` : un transport réduit — ceux que
        montent les tests, qui n'implémentent que ce que leur cas exige —
        n'a pas à porter cette méthode pour être synchronisable.
        """
        dossiers = self.transport.list_folders()
        etiquettes = getattr(self.transport, "range_par_etiquettes", None)
        if etiquettes is None or not etiquettes():
            return dossiers
        return [
            d
            for d in dossiers
            if not set(getattr(d, "attributes", ())) & set(VUES_REDONDANTES)
        ]

    def _lots(self, dossiers: list) -> list:
        """Répartit les dossiers entre les liens disponibles.

        En TOURNIQUET, pas en tranches contiguës : le LIST rend les
        dossiers groupés par hiérarchie, et les gros se suivent — une
        découpe en tranches donnerait un lot qui dure et des lots déjà
        finis.
        """
        combien = min(self.parallele, len(dossiers))
        if combien <= 1 or self.open_transport is None:
            return [list(dossiers)]
        lots = [[] for _ in range(combien)]
        for rang, dossier in enumerate(dossiers):
            lots[rang % combien].append(dossier)
        return lots

    def _sync_lot(self, dossiers: list, progress) -> SyncReport:
        report = SyncReport()
        for folder in dossiers:
            try:
                self._sync_folder(folder, report, progress)
            except Exception as exc:
                # Un dossier qui refuse ne doit pas priver l'utilisateur des autres.
                _logger.exception("sync du dossier %r a échoué", folder.name)
                report.errors.append(f"{folder.name} : {exc}")
            report.folders += 1
        return report

    def _sync_parallele(self, lots: list, progress) -> SyncReport:
        """Un lot par lien, le premier sur le lien déjà ouvert.

        Les liens supplémentaires sont FERMÉS à la sortie, quoi qu'il
        arrive : un compte qui en laisserait derrière lui à chaque passe
        atteindrait la limite du fournisseur en quelques minutes, et le
        suivant se verrait refuser.

        Le cache, lui, n'a pas besoin d'être protégé ici : ses méthodes
        prennent déjà son verrou.
        """
        from concurrent.futures import ThreadPoolExecutor

        travaux = [(self, list(lots[0]))]
        auxiliaires = []
        for lot in lots[1:]:
            try:
                transport = self.open_transport()
            except Exception as exc:
                # Le fournisseur refuse un lien de plus, ou le secret a
                # expiré : le lot revient au lien déjà ouvert plutôt que
                # de ne pas être synchronisé du tout.
                _logger.info("lien supplémentaire refusé : %s", exc)
                travaux[0][1].extend(lot)
                continue
            auxiliaires.append(transport)
            travaux.append((Syncer(self.store, transport), lot))
        try:
            with ThreadPoolExecutor(max_workers=len(travaux)) as pool:
                futurs = [
                    pool.submit(syncer._sync_lot, lot, progress)
                    for syncer, lot in travaux
                ]
                rapports = [futur.result() for futur in futurs]
        finally:
            for transport in auxiliaires:
                try:
                    transport.logout()
                except Exception:
                    # Le lien est fermé de toute façon à la fin du
                    # processus ; échouer ici ferait perdre une passe qui a
                    # réussi.
                    _logger.exception("fermeture d'un lien supplémentaire")
        return self._fusion(rapports)

    @staticmethod
    def _fusion(rapports: list) -> SyncReport:
        """Un seul rapport pour l'appelant : il n'a pas à savoir combien de
        liens ont servi."""
        total = SyncReport()
        for rapport in rapports:
            total.folders += rapport.folders
            total.new_messages += rapport.new_messages
            total.purged.extend(rapport.purged)
            total.errors.extend(rapport.errors)
            # Une seule boîte de réception par compte, donc un seul lot la
            # porte : concaténer ne mélange rien.
            total.inbox.extend(rapport.inbox)
            if not total.inbox_folder:
                total.inbox_folder = rapport.inbox_folder
            total.inbox_truncated = (
                total.inbox_truncated or rapport.inbox_truncated
            )
        return total

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

        `report.inbox` reste vide même pour INBOX : ce qu'une relecture
        ciblée découvre n'est pas une arrivée que la passe complète aurait
        annoncée.
        """
        report = SyncReport()
        try:
            self._sync_folder(
                FolderInfo(name=folder_name), report, None, rapporter=False
            )
        except Exception as exc:
            _logger.exception(
                "sync ciblée du dossier %r a échoué", folder_name
            )
            report.errors.append(f"{folder_name} : {exc}")
        report.folders = 1
        return report

    def _sync_folder(
        self,
        folder: FolderInfo,
        report: SyncReport,
        progress,
        rapporter: bool = True,
    ) -> None:
        """Une passe sur un dossier.

        Quand `rapporter` est vrai et que le dossier est la boîte de
        réception, les en-têtes des UID nouveaux vont AUSSI dans
        `report.inbox` : c'est ce que lisent les règles de courriel entrant,
        sans refaire de FETCH.
        """
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
        boite = rapporter and is_inbox(folder)
        if boite:
            report.inbox_folder = folder.name
        done = 0
        for batch in _chunks(uids, self.BATCH):
            headers = self.transport.fetch_headers(batch)
            self.store.upsert_messages(fid, [_meta(h) for h in headers])
            if boite:
                report.inbox.extend(headers)
                _garder_les_plus_hauts(report)
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

    def fetch_uids(self, folder_name: str, uids: list[int]) -> int:
        """Télécharge les en-têtes des UID que le cache n'a pas. Rend leur
        nombre.

        Sert la recherche côté serveur : ce que le serveur trouve doit
        ENTRER dans le cache, sinon la question suivante repartirait sur le
        réseau et le résultat disparaîtrait avec la connexion.

        Le dossier est sélectionné d'abord : un FETCH sans SELECT porte sur
        le dossier précédent, ou sur rien.

        N'alimente aucun `SyncReport` : un message retrouvé par recherche
        n'est pas une arrivée.
        """
        if not uids:
            return 0
        fid = self.store.upsert_folder(folder_name)
        manquants = self.store.missing_uids(fid, uids)
        if not manquants:
            return 0
        self.transport.select(folder_name)
        ajoutes = 0
        for batch in _chunks(manquants, self.BATCH):
            headers = self.transport.fetch_headers(batch)
            self.store.upsert_messages(fid, [_meta(h) for h in headers])
            ajoutes += len(headers)
        return ajoutes

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
