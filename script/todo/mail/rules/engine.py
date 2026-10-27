#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une passe des règles sur la boîte de réception d'un compte.

`run_pass` assemble le reste du paquet : il relit les règles sous le verrou
du compte, arme celles qui ne le sont pas, prend les messages arrivés
depuis le curseur, passe chacun aux garde-fous puis, si la décision est
d'envoyer, construit la réponse et choisit sa sortie : envoi direct, file
(hors ligne, refus temporaire) ou retenue (plafonds, premier envoi, cache
recréé).

Garanties :
- au plus une réponse par (règle, message) : la ligne du journal est écrite
  AVANT tout envoi, et `UNIQUE(rule_id, msg_key)` la réserve entre
  processus ;
- le curseur (`state.json`, hors du cache) n'avance que sur un message vu
  jusqu'au bout par toutes les règles actives ; un message qu'on n'a pas pu
  évaluer (hors ligne, FETCH en échec) reste un TROU et se réévalue à la
  passe suivante ;
- un message dont le traitement lève est journalisé en échec et ne bloque
  ni le curseur ni les messages suivants.

Fils : chaque échange IMAP passe sous `verrou` (le `_sync_lock` du TUI),
pris échange par échange ; le moteur n'appelle jamais l'interface. Le
journal applicatif ne reçoit ni adresse, ni sujet, ni texte d'une erreur
SMTP : seulement compte, règle, file, code de raison et code SMTP.
"""

from __future__ import annotations

import collections
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from script.todo.mail.rules import guards, markup, storage
from script.todo.mail.rules.filter import (
    BODY_TEXT_MAX,
    BodyUnavailable,
    normalize_address,
)
from script.todo.mail.rules.lock import LOCK_WAIT_S, file_lock
from script.todo.mail.rules.model import (
    EXECUTABLE_KINDS,
    Armed,
    RuleError,
    message_view,
)
from script.todo.mail.rules.regex_worker import RegexTimeout
from script.todo.mail.rules.storage import EngineState
from script.todo.todo_i18n import t

_logger = logging.getLogger(__name__)

MAX_AUTO_PER_PASS = storage.DEFAULT_CAP_PER_PASS
MAX_AUTO_PER_HOUR = storage.DEFAULT_CAP_PER_HOUR
HOUR_S = 3600
# Durée de vie d'une réponse automatique en file : passé ce délai, elle
# répond à un message trop ancien pour qu'on l'envoie encore.
OUTBOX_AUTO_TTL_S = 24 * 3600
# UID rattrapés au plus par passe quand le rapport de synchronisation ne
# les porte pas ; les plus anciens au-delà sont abandonnés.
CATCHUP_MAX = 200
# Taille des lots du FETCH de rattrapage, celle de `Syncer.BATCH`.
CATCHUP_BATCH = 200

STATUSES = (
    "ok",
    "no_rules",
    "ephemeral",
    "locked",
    "no_inbox",
    "offline",
    "rearmed",
    "error",
)
# Statuts qui ne disent rien à l'utilisateur quand la passe n'a rien fait.
_QUIET_STATUSES = frozenset({"ok", "no_rules", "ephemeral", "no_inbox"})
_STATUS_KEYS = {
    "locked": "mail_rules_locked",
    "rearmed": "mail_rules_rearmed",
    "offline": "mail_rules_offline",
    "error": "mail_rules_error",
    "no_inbox": "mail_rules_no_inbox",
}


class EngineSession(Protocol):
    """Ce que le moteur demande d'une session ; `tui.Session` le satisfait."""

    account: Any
    store: Any
    syncer: Any | None

    @property
    def online(self) -> bool: ...

    def avec_lien(self, action, progress=None): ...

    def current_secret(self) -> str: ...


@dataclass
class EngineReport:
    """Le bilan d'une passe pour un compte.

    `status` est l'un de `STATUSES`. `active_rules` compte les règles
    actives exécutables relues sous verrou ; à 0, le rendu reste muet.
    `warnings` porte des textes traduits ; `errors` des codes et textes
    sans adresse ni sujet.
    """

    account: str
    status: str = "ok"
    active_rules: int = 0
    sent: int = 0
    queued: int = 0
    held: int = 0
    failed: int = 0
    skipped: collections.Counter = field(default_factory=collections.Counter)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def warn(self, text: str) -> None:
        """Ajoute un avertissement, une seule fois par texte."""
        if text not in self.warnings:
            self.warnings.append(text)


def find_inbox(store) -> str | None:
    """Le nom de la boîte de réception en cache : par rôle, sinon par nom."""
    folders = store.folders()
    for folder in folders:
        if folder.get("role") == "inbox":
            return folder["name"]
    for folder in folders:
        if (folder.get("name") or "").upper() == "INBOX":
            return folder["name"]
    return None


def smtp_failure_is_permanent(exc: BaseException) -> bool:
    """Vrai pour un refus 5xx, qu'un nouvel essai ne changerait pas.

    `SmtpError.permanent` d'abord ; à défaut, le code SMTP lu dans
    l'exception (`smtp_send.smtp_code`). Panne réseau ou code inconnu :
    transitoire.
    """
    permanent = getattr(exc, "permanent", None)
    if isinstance(permanent, bool):
        return permanent
    from script.todo.mail.smtp_send import smtp_code

    code = smtp_code(exc)
    return code is not None and 500 <= code < 600


def account_addresses(account) -> frozenset:
    """Les adresses d'un compte, normalisées : courriel et identifiants
    IMAP et SMTP qui portent un « @ »."""
    values = (
        getattr(account, "email", ""),
        getattr(getattr(account, "imap", None), "user", ""),
        getattr(getattr(account, "smtp", None), "user", ""),
    )
    return frozenset(
        normalize_address(v) for v in values if v and "@" in str(v)
    )


def _other_addresses(account, all_accounts) -> frozenset:
    """Les adresses des AUTRES comptes configurés, moins les nôtres.

    `all_accounts=None` lit `accounts.json` ; illisible, aucune.
    """
    if all_accounts is None:
        from script.todo.mail import accounts as mail_accounts

        try:
            all_accounts = mail_accounts.load()
        except mail_accounts.AccountError:
            all_accounts = ()
    own = account_addresses(account)
    others = set()
    for other in all_accounts or ():
        if getattr(other, "name", None) == getattr(account, "name", None):
            continue
        others |= account_addresses(other)
    return frozenset(others - own)


def summary_line(reports) -> str:
    """La ligne de bilan de plusieurs comptes ; « » si tous sont muets.

    Un compte est muet sans règle active, ou quand son statut est neutre
    et que la passe n'a rien envoyé, mis en file, retenu ni fait échouer,
    sans avertissement.
    """
    parts = []
    for report in reports:
        if report.active_rules == 0:
            continue
        busy = report.sent or report.queued or report.held or report.failed
        if (
            report.status in _QUIET_STATUSES
            and not busy
            and not report.warnings
        ):
            continue
        items = [f"{t('mail_rules_status_sent')} {report.sent}"]
        if report.held:
            items.append(f"{t('mail_rules_status_held')} {report.held}")
        if report.queued:
            items.append(f"{t('mail_rules_status_queued')} {report.queued}")
        if report.failed:
            items.append(f"{t('mail_rules_status_failed')} {report.failed}")
        status_key = _STATUS_KEYS.get(report.status)
        if status_key:
            items.append(t(status_key))
        items.extend(report.warnings)
        parts.append(f"{report.account} : " + ", ".join(items))
    return " · ".join(parts)


class _Hole(Exception):
    """Le message ne peut pas être évalué maintenant : il reste un trou."""


def run_pass(
    session: EngineSession,
    *,
    report=None,
    all_accounts=None,
    verrou=None,
    rules_base: Path | None = None,
    now: Callable[[], float] = time.time,
    deliver_fn=None,
    max_per_pass: int | None = None,
    max_per_hour: int | None = None,
    lock_wait: float = LOCK_WAIT_S,
) -> EngineReport:
    """Une passe des règles pour le compte de `session`. Ne lève jamais.

    `report` est le `SyncReport` de la synchronisation qui précède : ses
    en-têtes d'INBOX évitent un FETCH ; None (mode sans interface), tout
    vient du curseur et d'un FETCH de rattrapage. `verrou` protège chaque
    échange IMAP. `rules_base` vaut par défaut `storage.base_of(store)`.
    `max_per_pass` et `max_per_hour` remplacent les plafonds de
    `rules.json` ; `lock_wait` est l'attente du verrou du compte, en
    secondes. Une exception imprévue donne `status="error"`.
    """
    account = getattr(session, "account", None)
    name = getattr(account, "name", "") or ""
    result = EngineReport(account=name)
    try:
        _Pass(
            session,
            result,
            sync_report=report,
            all_accounts=all_accounts,
            verrou=verrou,
            rules_base=rules_base,
            now=now,
            deliver_fn=deliver_fn,
            max_per_pass=max_per_pass,
            max_per_hour=max_per_hour,
            lock_wait=lock_wait,
        ).run()
    except RuleError as exc:
        result.status = "error"
        result.errors.append(str(exc))
        _logger.error("règles %s : fichier refusé (RuleError)", name)
    except Exception as exc:
        result.status = "error"
        result.errors.append(f"{t('mail_rules_error')} {type(exc).__name__}")
        _logger.error(
            "règles %s : passe en échec (%s)", name, type(exc).__name__
        )
    return result


class _Pass:
    """L'état d'une passe des règles sur un compte."""

    def __init__(
        self,
        session,
        result: EngineReport,
        *,
        sync_report,
        all_accounts,
        verrou,
        rules_base,
        now,
        deliver_fn,
        max_per_pass,
        max_per_hour,
        lock_wait,
    ) -> None:
        self.session = session
        self.result = result
        self.sync_report = sync_report
        self.all_accounts = all_accounts
        self.garde = verrou if verrou is not None else contextlib.nullcontext()
        self.verrou = verrou
        self.rules_base = rules_base
        self.clock = now
        self.deliver_fn = deliver_fn
        self.max_per_pass = max_per_pass
        self.max_per_hour = max_per_hour
        self.lock_wait = lock_wait
        self.account = session.account
        self.name = result.account
        self.store = getattr(session, "store", None)
        self.sends_this_pass = 0
        self.media_cache: dict = {}
        # Vrai après le premier refus transitoire de la passe : les
        # réponses suivantes vont en file sans retenter le serveur, chaque
        # tentative pouvant attendre le délai de connexion verrou tenu.
        self.smtp_down = False

    # -- déroulé -------------------------------------------------------

    def now(self) -> int:
        return int(self.clock())

    def run(self) -> None:
        store = self.store
        if store is None:
            self.result.status = "no_rules"
            return
        if getattr(store, "mode", None) == "ephemeral":
            self.result.status = "ephemeral"
            return
        base = self.rules_base
        if base is None:
            base = storage.base_of(store)
        if base is None:
            self.result.status = "ephemeral"
            return
        self.base = base
        # Pré-contrôle sans verrou ni écriture : un compte sans règle
        # active ne crée ni verrou ni état.
        if not storage.rules_exist(self.name, base):
            self.result.status = "no_rules"
            return
        try:
            actives = self._actives(storage.load(self.name, base))
        except RuleError:
            # Un fichier présent mais illisible coupe les réponses : le
            # bilan doit le dire, ce que `summary_line` tait à 0 règle.
            self.result.active_rules = 1
            raise
        if not actives:
            self.result.status = "no_rules"
            return
        # Compté avant le verrou : une passe `locked` est rendue au bilan.
        self.result.active_rules = len(actives)
        lock = storage.lock_path(self.name, base)
        with file_lock(lock, wait=self.lock_wait) as held:
            if not held:
                self.result.status = "locked"
                return
            self._locked_pass()

    @staticmethod
    def _actives(rules) -> list:
        return [
            r for r in rules if r.enabled and r.action.kind in EXECUTABLE_KINDS
        ]

    def _locked_pass(self) -> None:
        store, name, base = self.store, self.name, self.base
        # Relues SOUS verrou : une règle désactivée ou modifiée depuis le
        # pré-contrôle n'agit pas avec l'ancienne version.
        rules = storage.load(name, base)
        self.actives = self._actives(rules)
        self.result.active_rules = len(self.actives)
        if not self.actives:
            self.result.status = "no_rules"
            return
        caps = storage.load_caps(name, base)
        if self.max_per_pass is None:
            self.max_per_pass = caps.per_pass
        if self.max_per_hour is None:
            self.max_per_hour = caps.per_hour

        inbox = find_inbox(store)
        fstate = store.folder_state(inbox) if inbox else None
        if not fstate or not fstate.get("uidvalidity"):
            self.result.status = "no_inbox"
            return
        self.inbox = inbox
        fid = fstate["id"]
        last_uid = fstate.get("last_uid") or 0
        uidv = fstate["uidvalidity"]
        uidnext = fstate.get("uidnext") or (last_uid + 1)
        self.uidv = uidv
        now = self.now()

        st = storage.load_state(name, base)
        epoch = store.cache_epoch()
        if st.uidvalidity and st.uidvalidity != uidv:
            # Boîte renumérotée : tout y semble neuf. Les règles repartent
            # de l'UIDNEXT courant, et rien de ce qui est là n'est évalué.
            armed = Armed(uidv, uidnext, now)
            storage.set_armed(
                name,
                {r.id: armed for r in rules if r.enabled},
                base=base,
                lock_held=True,
            )
            st = EngineState(uidv, last_uid, epoch, st.hold_until, [])
            storage.save_state(name, st, base=base, lock_held=True)
            self.result.status = "rearmed"
            return
        if st.cache_epoch and st.cache_epoch != epoch:
            # Cache recréé : le journal qui porte la limite d'envoi par
            # règle et par expéditeur est perdu. Tout envoi est retenu le
            # temps de la plus longue limite active.
            window = max(
                (
                    r.throttle_minutes * 60
                    for r in self.actives
                    if r.throttle_enabled
                ),
                default=0,
            )
            st.hold_until = now + window
            self.result.warn(t("mail_rules_cache_rebuilt"))
        st.cache_epoch = epoch
        to_arm = {
            r.id: Armed(uidv, uidnext, now)
            for r in self.actives
            if r.armed is None or r.armed.uidvalidity != uidv
        }
        if to_arm:
            storage.set_armed(name, to_arm, base=base, lock_held=True)
            for rule in self.actives:
                if rule.id in to_arm:
                    rule.armed = to_arm[rule.id]
        floor = min(r.armed.uidnext for r in self.actives) - 1
        cursor = max(st.cursor, floor) if st.cursor else floor
        st.cursor = cursor
        st.uidvalidity = uidv
        st.done = sorted(u for u in set(st.done) if u > cursor)
        self.state = st
        storage.save_state(name, st, base=base, lock_held=True)

        self.own = account_addresses(self.account)
        self.others = _other_addresses(self.account, self.all_accounts)
        self.domain = (getattr(self.account, "email", "") or "").rpartition(
            "@"
        )[2]
        self._walk(store.uids_between(fid, cursor, last_uid))

    def _walk(self, uids: list) -> None:
        """Évalue les candidats, UID croissants, en avançant le curseur."""
        known = {}
        if getattr(self.sync_report, "inbox_folder", "") == self.inbox:
            known = {h.uid: h for h in getattr(self.sync_report, "inbox", [])}
        # Déjà vus jusqu'au bout au-dessus d'un trou : jamais réévalués.
        # Une seconde évaluation lirait « duplicate » (non apparié) pour
        # une règle déjà appliquée, et « arrêter ici » n'arrêterait plus.
        treated, holes = set(self.state.done) & set(uids), set()
        missing = [u for u in uids if u not in known and u not in treated]
        if missing:
            if not self.session.online:
                holes.update(missing)
                self.result.status = "offline"
            else:
                if len(missing) > CATCHUP_MAX:
                    overflow = missing[:-CATCHUP_MAX]
                    missing = missing[-CATCHUP_MAX:]
                    treated.update(overflow)
                    self.result.skipped["catchup_overflow"] += len(overflow)
                    self.result.warn(t("mail_rules_catchup_warning"))
                self._catch_up(missing, known, treated, holes)

        self._index = 0
        self._uids = uids
        self._treated = treated
        self._saved = (self.state.cursor or 0, list(self.state.done))
        for uid in uids:
            if uid in treated or uid in holes:
                continue
            header = known.get(uid)
            if header is None:
                holes.add(uid)
                continue
            try:
                self._message(header)
            except _Hole:
                holes.add(uid)
                if self.result.status == "ok":
                    self.result.status = "offline"
                continue
            treated.add(uid)
            self._advance()
        self._advance(force=True)

    def _advance(self, force: bool = False) -> None:
        """Porte le curseur au plus haut UID précédé de traités seulement.

        Les traités restés au-dessus du curseur (un trou les précède) vont
        dans `state.done`, que la passe suivante saute. L'état n'est
        réécrit que s'il change, ou si `force`.
        """
        while (
            self._index < len(self._uids)
            and self._uids[self._index] in self._treated
        ):
            uid = self._uids[self._index]
            self._index += 1
            if uid > (self.state.cursor or 0):
                self.state.cursor = uid
        cursor = self.state.cursor or 0
        done = sorted(u for u in self._treated if u > cursor)
        moved = (cursor, done) != self._saved
        self.state.done = done
        if moved or force:
            self._saved = (cursor, done)
            storage.save_state(
                self.name, self.state, base=self.base, lock_held=True
            )

    def _catch_up(self, missing, known, treated, holes) -> None:
        """FETCH des en-têtes absents du rapport, sous verrou, par lots.

        Un UID demandé et non rendu (expurgé côté serveur) est traité ;
        un lot dont le FETCH lève reste en trous.
        """
        inbox = self.inbox
        for start in range(0, len(missing), CATCHUP_BATCH):
            batch = missing[start : start + CATCHUP_BATCH]

            def fetch(transport, batch=batch):
                transport.select(inbox)
                return transport.fetch_headers(batch)

            try:
                with self.garde:
                    headers = self.session.avec_lien(fetch)
                if headers is None:
                    raise ConnectionError("no link")
            except Exception as exc:
                holes.update(batch)
                self.result.errors.append(
                    f"{t('mail_rules_error')} catchup {type(exc).__name__}"
                )
                # Au bilan aussi : sans envoi, la passe y serait muette.
                self.result.warn(t("mail_rules_error"))
                _logger.error(
                    "règles %s : rattrapage en échec (%s)",
                    self.name,
                    type(exc).__name__,
                )
                continue
            got = {h.uid: h for h in headers}
            for uid in batch:
                if uid in got:
                    known[uid] = got[uid]
                else:
                    treated.add(uid)
                    self.result.skipped["gone"] += 1

    # -- un message ----------------------------------------------------

    def _message(self, header) -> None:
        """Toutes les règles actives sur un message ; `_Hole` s'il manque
        le corps hors ligne.

        Un en-tête que la vue ne sait pas lire est compté en échec et
        passé : sans clé de message, il ne peut pas être journalisé, et le
        garder bloquerait le curseur à chaque passe.
        """
        try:
            view = message_view(header, self.uidv)
            msg_key = self.store.message_key(view.msgid, self.uidv, view.uid)
        except Exception as exc:
            self.result.failed += 1
            _logger.error(
                "règles %s : en-tête illisible, build_error (%s)",
                self.name,
                type(exc).__name__,
            )
            return
        loader = self._body_loader(view.uid)
        for rule in self.actives:
            try:
                stop = self._apply(rule, view, msg_key, loader)
            except _Hole:
                raise
            except RegexTimeout as exc:
                # Verdict du filtre inconnu : la règle a peut-être apparié,
                # donc « arrêter ici » vaut, comme pour un envoi en échec.
                self._fail(rule, view, msg_key, "regex_timeout", exc)
                if rule.stop_after:
                    break
                continue
            except Exception as exc:
                self._fail(rule, view, msg_key, "build_error", exc)
                continue
            if stop:
                break

    def _body_loader(self, uid: int):
        """Un chargeur de corps paresseux, mémorisé et partagé entre règles.

        Hors ligne : `BodyUnavailable(online=False)`. En ligne, le FETCH
        (BODY.PEEK, qui ne marque pas lu) passe sous verrou ; son échec est
        mémorisé, et chaque appel suivant lève `BodyUnavailable(online=True)`.
        """
        memo = {}

        def load() -> str:
            if "text" in memo:
                return memo["text"]
            if "error" in memo:
                raise BodyUnavailable(online=True)
            if not self.session.online:
                raise BodyUnavailable(online=False)
            from script.todo.mail.tui_text import extract_body

            inbox = self.inbox
            try:
                with self.garde:
                    raw = self.session.avec_lien(
                        lambda _t: self.session.syncer.fetch_body(inbox, uid)
                    )
                if raw is None:
                    raise ConnectionError("no link")
                text = extract_body(raw)[0][:BODY_TEXT_MAX]
            except Exception as exc:
                memo["error"] = type(exc).__name__
                raise BodyUnavailable(online=True) from exc
            memo["text"] = text
            return text

        return load

    def _context(self, rule, msg_key) -> guards.GuardContext:
        store = self.store

        def last_send_at(sender, target):
            return store.rule_log_last_send(
                rule.id,
                store.address_hash(sender),
                store.address_hash(target) or None,
            )

        return guards.GuardContext(
            now=self.now(),
            own_addresses=self.own,
            other_account_addresses=self.others,
            is_logged=lambda: store.rule_log_seen(rule.id, msg_key),
            last_send_at=last_send_at,
        )

    def _claim(self, rule, view, msg_key, d, outcome, reason) -> bool:
        store = self.store
        sender = d.sender if d is not None else ""
        target = d.target if d is not None else ""
        return store.rule_log_claim(
            rule.id,
            msg_key,
            outcome=outcome,
            reason=reason,
            at=self.now(),
            sender=sender or view.frm,
            subject=view.subject,
            received_at=view.internaldate,
            sender_hash=store.address_hash(sender) or None,
            target_hash=store.address_hash(target) or None,
            fingerprint=rule.fingerprint(),
        )

    def _apply(self, rule, view, msg_key, loader) -> bool:
        """Une règle sur un message. Rend vrai pour « arrêter ici »."""
        try:
            d = guards.decide(rule, view, self._context(rule, msg_key), loader)
        except BodyUnavailable as exc:
            if not exc.online:
                raise _Hole() from exc
            if self._claim(
                rule, view, msg_key, None, "failed", "body_unavailable"
            ):
                self.result.failed += 1
            _logger.error(
                "règles %s : règle %s, body_unavailable", self.name, rule.id
            )
            return False
        if d.reason == guards.SEND:
            try:
                self._send(rule, view, msg_key, d)
            except Exception as exc:
                # Le filtre a apparié : « arrêter ici » vaut même quand la
                # réponse n'a pas pu être construite.
                self._fail(rule, view, msg_key, "build_error", exc)
        elif d.logged:
            if self._claim(rule, view, msg_key, d, "skipped", d.reason):
                self.result.skipped[d.reason] += 1
        return d.matched and rule.stop_after

    def _fail(self, rule, view, msg_key, code, exc) -> None:
        """Journalise un échec (règle, message) sans jamais lever."""
        _logger.error(
            "règles %s : règle %s, %s (%s)",
            self.name,
            rule.id,
            code,
            type(exc).__name__,
        )
        try:
            if not self._claim(rule, view, msg_key, None, "failed", code):
                self.store.rule_log_set_outcome(
                    rule.id, msg_key, "failed", code
                )
            self.result.failed += 1
            self.result.errors.append(
                f"{rule.name or rule.id} : {t('mail_rules_reason_' + code)}"
            )
        except Exception as again:
            _logger.error(
                "règles %s : journal en échec (%s)",
                self.name,
                type(again).__name__,
            )

    def _media(self, rule) -> dict:
        """Les octets des images de la règle, lus une fois par passe."""
        cached = self.media_cache.get(rule.id)
        if cached is None:
            try:
                cached = {
                    ref.file: storage.read_media(
                        self.name, ref, base=self.base
                    )
                    for ref in rule.action.images
                }
            except RuleError as exc:
                cached = exc
            self.media_cache[rule.id] = cached
        if isinstance(cached, RuleError):
            raise cached
        return cached

    def _send(self, rule, view, msg_key, d) -> None:
        """Construit la réponse, la réserve au journal, puis choisit sa
        sortie : retenue, file ou envoi direct."""
        from script.todo.mail import smtp_send

        store, now = self.store, self.now()
        try:
            rendered = markup.render_reply(
                rule.action, self._media(rule), self.domain
            )
        except RuleError as exc:
            if self._claim(rule, view, msg_key, d, "failed", "media"):
                self.result.failed += 1
            self.result.warn(str(exc))
            _logger.error("règles %s : règle %s, media", self.name, rule.id)
            return
        msg = smtp_send.build_auto_reply(
            self.account,
            d.target_addr,
            smtp_send.auto_reply_subject(view.subject, rule.action.subject),
            rendered.text,
            in_reply_to=view.msgid,
            references=view.references,
            html=rendered.html,
            inline_images=rendered.inline,
            attachment_parts=rendered.attachments,
        )
        fingerprint = rule.fingerprint()
        if not self._claim(rule, view, msg_key, d, "pending", None):
            # Un autre processus a réservé ce message pour cette règle.
            self.result.skipped["duplicate"] += 1
            return
        store.mark_auto_sent(msg["Message-ID"] or "", rule.id, now)

        hold = None
        if self.sends_this_pass >= self.max_per_pass:
            hold = "pass_cap"
        elif store.rule_log_recent_sends(now - HOUR_S) >= self.max_per_hour:
            hold = "hour_cap"
        elif now < self.state.hold_until:
            hold = "cache_rebuilt"
        elif store.rule_log_sent_count(rule.id, fingerprint) < rule.hold_first:
            hold = "hold_first"
        if hold is not None:
            if hold in ("pass_cap", "hour_cap"):
                self.result.warn(t("mail_rules_cap_warning"))
            else:
                self.sends_this_pass += 1
            self._queue(rule, msg_key, msg, now, "held", hold)
            return
        if not self.session.online:
            self.sends_this_pass += 1
            self._queue(rule, msg_key, msg, now, "queued", "offline")
            return
        if self.smtp_down:
            self.sends_this_pass += 1
            self._queue(rule, msg_key, msg, now, "queued", "smtp_transient")
            return

        from script.todo.mail.tui import DeliverOffline

        deliver_fn = self.deliver_fn
        if deliver_fn is None:
            from script.todo.mail.tui import deliver as deliver_fn
        try:
            # Sans `queue_offline=False`, une session tombée hors ligne
            # depuis le contrôle ci-dessus mettrait la réponse en file comme
            # un envoi manuel, hors de l'échéance et des contrôles de règle.
            deliver_fn(
                self.session, msg, verrou=self.verrou, queue_offline=False
            )
        except DeliverOffline:
            self.sends_this_pass += 1
            self._queue(rule, msg_key, msg, now, "queued", "offline")
            return
        except Exception as exc:
            code = getattr(exc, "code", None)
            if smtp_failure_is_permanent(exc):
                store.rule_log_set_outcome(
                    rule.id, msg_key, "failed", "smtp_permanent"
                )
                self.result.failed += 1
                self.result.errors.append(
                    f"{rule.name or rule.id} :"
                    f" {t('mail_rules_reason_smtp_permanent')}"
                )
                _logger.error(
                    "règles %s : règle %s, smtp_permanent, code %s",
                    self.name,
                    rule.id,
                    code,
                )
                return
            _logger.error(
                "règles %s : règle %s, smtp_transient, code %s (%s)",
                self.name,
                rule.id,
                code,
                type(exc).__name__,
            )
            self.smtp_down = True
            self.sends_this_pass += 1
            self._queue(rule, msg_key, msg, now, "queued", "smtp_transient")
            return
        store.rule_log_set_outcome(rule.id, msg_key, "sent")
        self.sends_this_pass += 1
        self.result.sent += 1
        _logger.info("règles %s : règle %s, sent", self.name, rule.id)

    def _queue(self, rule, msg_key, msg, now, outcome, reason) -> None:
        """Met la réponse en file ET avance le journal, en une transaction."""
        from script.todo.mail.smtp_send import recipients

        queue_id = self.store.queue_auto(
            msg.as_bytes(),
            ", ".join(recipients(msg)),
            msg["Subject"] or "",
            held=outcome == "held",
            rule_id=rule.id,
            source_key=msg_key,
            expires_at=int(now) + OUTBOX_AUTO_TTL_S,
            outcome=outcome,
            reason=reason,
        )
        if outcome == "held":
            self.result.held += 1
        else:
            self.result.queued += 1
        _logger.info(
            "règles %s : règle %s, file %s, %s/%s",
            self.name,
            rule.id,
            queue_id,
            outcome,
            reason,
        )
