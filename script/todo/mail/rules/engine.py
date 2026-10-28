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

Une règle `forward` relaie le message au lieu d'y répondre. Ses octets
complets ne sont lus (BODY.PEEK[], qui ne marque pas lu) que lorsqu'elle a
décidé d'envoyer, une fois par message pour toutes les règles, et jamais
au-delà de `FORWARD_MAX_BYTES`. Un transfert part à ses destinations en
Cci interne ; une redirection (`smtp_send.RawOutgoing`) part à une
enveloppe explicite qui survit à la file, n'est pas classée dans Envoyés
et n'entre pas dans `auto_sent` : son Message-ID est celui de l'original.

Fils : chaque échange IMAP passe sous `verrou` (le `_sync_lock` du TUI),
pris échange par échange ; le moteur n'appelle jamais l'interface. Le
journal applicatif ne reçoit ni adresse, ni sujet, ni texte d'une erreur
SMTP : seulement compte, règle, file, code de raison et code SMTP.
"""

from __future__ import annotations

import collections
import contextlib
import dataclasses
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from script.todo.mail.rules import filter as rules_filter
from script.todo.mail.rules import guards, markup, storage
from script.todo.mail.rules import model as rules_model
from script.todo.mail.rules import report as rules_report
from script.todo.mail.rules.filter import (
    BODY_TEXT_MAX,
    BodyUnavailable,
    normalize_address,
)
from script.todo.mail.rules.lock import LOCK_WAIT_S, file_lock
from script.todo.mail.rules.model import (
    EXECUTABLE_KINDS,
    FORWARD_MAX_BYTES,
    Armed,
    RuleError,
    TemplateError,
    message_view,
)
from script.todo.mail.rules.regex_worker import RegexTimeout
from script.todo.mail.rules.storage import EngineState
from script.todo.mail.smtp_send import (
    RawOutgoing,
    SmtpError,
    smtp_address,
)
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
# Rapports de statistiques envoyés au plus par règle sur 24 heures
# glissantes ; au-delà, la demande est ignorée, sans file ni retenue.
STATS_DAILY_MAX = 20
# Entrées de file au plus par règle `forward` au-delà desquelles un envoi
# que les plafonds retiendraient est écarté SANS télécharger le message :
# chaque transfert retenu garde une copie entière de l'original (jusqu'à
# `FORWARD_MAX_BYTES`), là où une réponse retenue pèse quelques Kio.
FORWARD_CAP_HELD_MAX = 20
DAY_S = 86400

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


def other_account_addresses(account, all_accounts=None) -> frozenset:
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


def hold_reason(
    store,
    rule,
    *,
    now: int,
    hold_until: int,
    sends_this_pass: int,
    max_per_pass: int,
    max_per_hour: int,
) -> str | None:
    """Le code qui retiendrait (ou écarterait) un envoi décidé, ou None.

    Lecture seule. Dans l'ordre : `stats_cap` (règle `stats` qui a déjà
    `STATS_DAILY_MAX` envois sur 24 heures : la demande est écartée), puis
    les retenues `pass_cap`, `hour_cap`, `cache_rebuilt` (avant
    `hold_until`) et `hold_first` (moins de `rule.hold_first` envois
    approuvés sous l'empreinte actuelle de la règle).
    """
    if (
        rule.action.kind == "stats"
        and store.rule_log_rule_sends(rule.id, now - DAY_S) >= STATS_DAILY_MAX
    ):
        return "stats_cap"
    if sends_this_pass >= max_per_pass:
        return "pass_cap"
    if store.rule_log_recent_sends(now - HOUR_S) >= max_per_hour:
        return "hour_cap"
    if now < hold_until:
        return "cache_rebuilt"
    if (
        store.rule_log_sent_count(rule.id, rule.fingerprint())
        < rule.hold_first
    ):
        return "hold_first"
    return None


def make_body_loader(
    session, folder: str, uid: int, verrou=None
) -> Callable[[], str]:
    """Un chargeur de corps paresseux et mémorisé pour un message.

    Hors ligne : `BodyUnavailable(online=False)`. En ligne, le FETCH
    (BODY.PEEK, qui ne marque pas lu) passe sous `verrou` ; son échec est
    mémorisé, et chaque appel suivant lève `BodyUnavailable(online=True)`.
    Le texte rendu est tronqué à `BODY_TEXT_MAX`.
    """
    garde = verrou if verrou is not None else contextlib.nullcontext()
    memo = {}

    def load() -> str:
        if "text" in memo:
            return memo["text"]
        if "error" in memo:
            raise BodyUnavailable(online=True)
        if not session.online:
            raise BodyUnavailable(online=False)
        from script.todo.mail.tui_text import extract_body

        try:
            with garde:
                raw = session.avec_lien(
                    lambda _t: session.syncer.fetch_body(folder, uid)
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


class MessageTooBig(Exception):
    """Le message dépasse `FORWARD_MAX_BYTES` ; `size` en octets."""

    def __init__(self, size: int) -> None:
        super().__init__(size)
        self.size = int(size)


def make_raw_loader(
    session,
    folder: str,
    uid: int,
    verrou=None,
    *,
    size: int = 0,
    max_bytes: int = FORWARD_MAX_BYTES,
) -> Callable[[], bytes]:
    """Un chargeur paresseux et mémorisé des OCTETS complets d'un message.

    `size` (RFC822.SIZE, 0 si inconnue) plus grand que `max_bytes` lève
    `MessageTooBig(size)` sans aucun échange. Hors ligne :
    `BodyUnavailable(online=False)`, rien n'est mémorisé. En ligne,
    `session.syncer.fetch_body` (le cache d'abord, sinon BODY.PEEK[], qui ne
    marque pas lu, puis écriture dans le cache) passe sous `verrou` par
    `session.avec_lien` : un chargeur de corps du même message lit ensuite
    le cache, sans second FETCH. Son échec est mémorisé, et chaque appel
    suivant lève `BodyUnavailable(online=True)`. Des octets reçus plus longs
    que `max_bytes` lèvent `MessageTooBig(len)`, mémorisé aussi.
    """
    garde = verrou if verrou is not None else contextlib.nullcontext()
    memo = {}

    def load() -> bytes:
        if "raw" in memo:
            return memo["raw"]
        if "too_big" in memo:
            raise MessageTooBig(memo["too_big"])
        if "error" in memo:
            raise BodyUnavailable(online=True)
        if size and size > max_bytes:
            memo["too_big"] = size
            raise MessageTooBig(size)
        if not session.online:
            raise BodyUnavailable(online=False)
        try:
            with garde:
                raw = session.avec_lien(
                    lambda _t: session.syncer.fetch_body(folder, uid)
                )
            if raw is None:
                raise ConnectionError("no link")
            raw = bytes(raw)
        except Exception as exc:
            memo["error"] = type(exc).__name__
            raise BodyUnavailable(online=True) from exc
        if len(raw) > max_bytes:
            memo["too_big"] = len(raw)
            raise MessageTooBig(len(raw))
        memo["raw"] = raw
        return raw

    return load


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

    `redirect` rend un `smtp_send.RawOutgoing` (octets d'origine sous un
    bloc `Resent-*`, enveloppe = `targets`) ; `intro`, `reply_to` et
    `subject_prefix` y sont ignorés. `attachment` et `inline` rendent un
    `EmailMessage` adressé à `targets` en Cci interne. Lève `SmtpError`
    sur une destination refusée ou des octets illisibles.
    """
    from script.todo.mail import smtp_send

    if opts.mode == "redirect":
        return smtp_send.build_redirect(
            account, raw, targets, date=date, msgid=msgid
        )
    build = (
        smtp_send.build_forward_attached
        if opts.mode == "attachment"
        else smtp_send.build_forward_inline
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
    from email.utils import getaddresses

    first = (view.extra.get("reply-to") or "").split("\n", 1)[0]
    kept: list[str] = []
    for _name, address in getaddresses([first]):
        try:
            form = smtp_address(address.strip())
        except SmtpError:
            continue
        norm = normalize_address(form)
        if norm in own or norm in others:
            continue
        if all(normalize_address(k) != norm for k in kept):
            kept.append(form)
    if kept:
        return ", ".join(kept)
    try:
        return smtp_address(rules_filter.sole_address(view.frm, raw=True))
    except SmtpError:
        return ""


def _first_msgid(value: str) -> str:
    """Le premier identifiant d'un en-tête d'enfilage, ou « »."""
    from script.todo.mail.smtp_send import _msgid_tokens

    tokens = _msgid_tokens(value)
    return tokens[0] if tokens else ""


def _own_send_check(store, view, forward_ids) -> Callable[[], bool]:
    """Le contrôle `GuardContext.is_own_send` d'un message : son
    Message-ID est l'un de nos envois de règle, quel qu'en soit le type,
    ou le premier identifiant de son `In-Reply-To` est un envoi d'une
    règle de `forward_ids`."""

    def check() -> bool:
        if store.is_rule_send(view.msgid):
            return True
        return store.is_rule_send(
            _first_msgid(view.in_reply_to), rule_ids=forward_ids
        )

    return check


def _forward_ids(rules) -> frozenset:
    """Les identifiants des règles `forward` de `rules`, actives ou non :
    les envois d'une règle désactivée restent les nôtres."""
    return frozenset(r.id for r in rules if r.action.kind == "forward")


def fetch_inbox_header(session, uid: int, *, uidvalidity: int, verrou=None):
    """Les en-têtes complets d'un message d'INBOX (`HeaderInfo`, en-têtes
    supplémentaires compris), ou None hors ligne, sans boîte de réception
    en cache, pour un message absent ou un échec. Ne lève jamais.

    `uid` vient du cache, valable sous `uidvalidity` : si le serveur
    annonce une autre UIDVALIDITY, la boîte a été renumérotée, ce numéro
    peut désigner un autre message, et rien n'est relu (None).
    """
    try:
        if not session.online:
            return None
        inbox = find_inbox(session.store)
        if inbox is None:
            return None

        def fetch(transport):
            if transport.select(inbox).uidvalidity != uidvalidity:
                _logger.info("essai : UIDVALIDITY changée, en-têtes non relus")
                return []
            return transport.fetch_headers([uid])

        garde = verrou if verrou is not None else contextlib.nullcontext()
        with garde:
            headers = session.avec_lien(fetch)
        for header in headers or ():
            if header.uid == uid:
                return header
    except Exception as exc:
        _logger.error("essai : en-têtes illisibles (%s)", type(exc).__name__)
    return None


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
        # Réglages du rapport, lus sous verrou seulement si une règle
        # `stats` est active ; la partie boîte et la table des demandeurs
        # sont calculées au premier rapport de la passe, puis gardées.
        self.report = storage.ReportSettings()
        self._mailbox = None
        self._requesters = None

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
        self.forward_ids = _forward_ids(rules)
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
        if any(r.action.kind == "stats" for r in self.actives):
            try:
                self.report = storage.load_report(name, base)
            except RuleError as exc:
                # Des réglages illisibles ne concernent que les rapports :
                # les règles `stats` sont écartées de cette passe, les
                # autres continuent.
                text = f"{t('mail_stats_report_invalid')} {exc}"
                self.result.warn(text)
                self.result.errors.append(text)
                self.actives = [
                    r for r in self.actives if r.action.kind != "stats"
                ]
                if not self.actives:
                    self.result.status = "no_rules"
                    return

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
        self.others = other_account_addresses(self.account, self.all_accounts)
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
        # Paresseux : rien n'est lu tant qu'aucune règle `forward` ne
        # décide d'envoyer, puis une seule fois pour toutes.
        raw = make_raw_loader(
            self.session, self.inbox, view.uid, self.verrou, size=view.size
        )
        for rule in self.actives:
            try:
                stop = self._apply(rule, view, msg_key, loader, raw)
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
        """Le chargeur de corps du message, partagé entre les règles
        (`make_body_loader`)."""
        return make_body_loader(self.session, self.inbox, uid, self.verrou)

    def _context(self, rule, msg_key, view) -> guards.GuardContext:
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
            auth_serv_id=self.report.auth_serv_id,
            is_own_send=_own_send_check(store, view, self.forward_ids),
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

    def _apply(self, rule, view, msg_key, loader, raw=None) -> bool:
        """Une règle sur un message. Rend vrai pour « arrêter ici ».

        `raw` est le chargeur des octets complets du message
        (`make_raw_loader`), partagé entre les règles ; seule une règle
        `forward` qui va envoyer l'appelle.
        """
        try:
            d = guards.decide(
                rule, view, self._context(rule, msg_key, view), loader
            )
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
        except RegexTimeout:
            raise
        except RuleError as exc:
            # Options illisibles, lues après le filtre : il a apparié, et
            # « arrêter ici » vaut comme pour un échec de construction.
            self._fail(rule, view, msg_key, "build_error", exc)
            return rule.stop_after
        if d.reason == guards.SEND:
            try:
                self._send(rule, view, msg_key, d, raw)
            except _Hole:
                raise
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

    def _daily_mailbox(self, now: int):
        """La partie boîte du rapport du jour : relue de l'instantané s'il
        correspond au jour local et aux réglages, sinon calculée puis
        écrite. Toutes les demandes d'un même jour voient ainsi les mêmes
        chiffres.

        L'écriture de l'instantané est facultative : un échec (disque
        plein, dossier en lecture seule) laisse un avertissement à la
        passe et rend quand même les chiffres calculés.
        """
        key = rules_report.snapshot_key(self.report, now)
        mailbox = rules_report.mailbox_from_dict(
            storage.load_report_snapshot(self.name, self.base), key
        )
        if mailbox is None:
            mailbox = rules_report.collect_mailbox(
                self.store, self.report, now=now
            )
            try:
                storage.save_report_snapshot(
                    self.name,
                    rules_report.mailbox_to_dict(mailbox, key),
                    base=self.base,
                    lock_held=True,
                )
            except (OSError, RuleError) as exc:
                _logger.error(
                    "règles %s : instantané du rapport non écrit (%s)",
                    self.name,
                    type(exc).__name__,
                )
                self.result.warn(t("mail_stats_snapshot_unsaved"))
        return mailbox

    def _report_data(self, d, now: int):
        """Les données du rapport pour le demandeur de la décision `d`.

        La partie boîte et la table des demandeurs sont lues une fois par
        passe ; une panne du cache ou de l'instantané lève, et `_apply` la
        journalise `build_error`.
        """
        if self._mailbox is None:
            self._mailbox = self._daily_mailbox(now)
        if self._requesters is None:
            self._requesters = rules_report.requester_index(
                self.store, self.report, now=now
            )
        return rules_report.ReportData(
            self._mailbox,
            rules_report.collect_requester(
                self.store,
                self.report,
                now=now,
                sender=d.sender,
                index=self._requesters,
            ),
            self.report.lang,
        )

    def _render(self, rule, view, msg_key, d, now: int):
        """(sujet, rendu) de la réponse, ou None après avoir journalisé
        l'échec : faute de gabarit en `build_error`, image en `media`."""
        from script.todo.mail import smtp_send

        data = None
        if rule.action.kind == "stats":
            data = self._report_data(d, now)
        try:
            if data is not None:
                subject = rules_report.render_subject(
                    view.subject, rule.action.subject, data
                )
                rendered = rules_report.render_stats_reply(
                    rule.action, self._media(rule), self.domain, data
                )
            else:
                subject = smtp_send.auto_reply_subject(
                    view.subject, rule.action.subject
                )
                rendered = markup.render_reply(
                    rule.action, self._media(rule), self.domain
                )
        except TemplateError as exc:
            # Avant `RuleError`, dont elle est une sous-classe.
            self._fail(rule, view, msg_key, "build_error", exc)
            self.result.warn(str(exc))
            return None
        except RuleError as exc:
            if self._claim(rule, view, msg_key, d, "failed", "media"):
                self.result.failed += 1
            self.result.warn(str(exc))
            _logger.error("règles %s : règle %s, media", self.name, rule.id)
            return None
        return subject, rendered

    def _send(self, rule, view, msg_key, d, raw_loader=None) -> None:
        """Construit le message (réponse ou redirection), puis le confie à
        `_dispatch`. Rien ne part si la construction a déjà journalisé un
        échec ou un écart."""
        if rule.action.kind == "forward":
            msg = self._build_forward(rule, view, msg_key, d, raw_loader)
        else:
            msg = self._build_reply(rule, view, msg_key, d)
        if msg is not None:
            self._dispatch(rule, view, msg_key, d, msg)

    def _build_reply(self, rule, view, msg_key, d):
        """La réponse rendue, ou None après avoir journalisé l'échec."""
        from script.todo.mail import smtp_send

        built = self._render(rule, view, msg_key, d, self.now())
        if built is None:
            return None
        subject, rendered = built
        return smtp_send.build_auto_reply(
            self.account,
            d.target_addr,
            subject,
            rendered.text,
            in_reply_to=view.msgid,
            references=view.references,
            html=rendered.html,
            inline_images=rendered.inline,
            attachment_parts=rendered.attachments,
        )

    def _build_forward(self, rule, view, msg_key, d, raw_loader):
        """Le transfert ou la redirection, ou None après avoir journalisé.

        Plafond atteint alors que la règle a déjà `FORWARD_CAP_HELD_MAX`
        entrées en file : `skipped/pass_cap` ou `skipped/hour_cap`, sans
        FETCH. Octets indisponibles hors ligne : `_Hole`, le message sera
        repris. FETCH en échec : `failed/body_unavailable`. Message plus
        gros que `FORWARD_MAX_BYTES` une fois lu : `skipped/too_big`. Une
        `SmtpError` de construction traverse jusqu'à `_apply`
        (`build_error`).
        """
        opts = rules_model.forward_options(rule.action)
        if self._forward_cap_full(rule, view, msg_key, d):
            return None
        try:
            if raw_loader is None:
                raise BodyUnavailable(online=True)
            raw = raw_loader()
        except BodyUnavailable as exc:
            if not exc.online:
                raise _Hole() from exc
            if self._claim(
                rule, view, msg_key, d, "failed", "body_unavailable"
            ):
                self.result.failed += 1
            _logger.error(
                "règles %s : règle %s, body_unavailable", self.name, rule.id
            )
            return None
        except MessageTooBig:
            if self._claim(rule, view, msg_key, d, "skipped", "too_big"):
                self.result.skipped["too_big"] += 1
            _logger.info("règles %s : règle %s, too_big", self.name, rule.id)
            return None
        return forward_message(
            self.account,
            opts,
            raw,
            list(d.targets),
            intro=rule.action.body,
            reply_to=forward_reply_to(view, self.own, self.others),
        )

    def _forward_cap_full(self, rule, view, msg_key, d) -> bool:
        """Vrai, après avoir journalisé l'écart, quand un plafond
        retiendrait ce transfert et que la règle a déjà
        `FORWARD_CAP_HELD_MAX` entrées en file. Appelé avant le
        téléchargement : au-delà de la borne, aucun octet n'est lu."""
        hold = hold_reason(
            self.store,
            rule,
            now=self.now(),
            hold_until=self.state.hold_until,
            sends_this_pass=self.sends_this_pass,
            max_per_pass=self.max_per_pass,
            max_per_hour=self.max_per_hour,
        )
        if hold not in ("pass_cap", "hour_cap"):
            return False
        if self.store.outbox_rule_count(rule.id) < FORWARD_CAP_HELD_MAX:
            return False
        if self._claim(rule, view, msg_key, d, "skipped", hold):
            self.result.skipped[hold] += 1
        self.result.warn(t("mail_rules_cap_warning"))
        _logger.info("règles %s : règle %s, %s", self.name, rule.id, hold)
        return True

    def _dispatch(self, rule, view, msg_key, d, msg) -> None:
        """Réserve le message au journal, puis choisit sa sortie : écarté
        (plafond quotidien d'un rapport), retenu, file ou envoi direct.

        Le Message-ID d'un message construit par nous entre dans
        `auto_sent` avant l'envoi ; celui d'une redirection est celui de
        l'original et n'y entre pas.
        """
        store, now = self.store, self.now()
        if not self._claim(rule, view, msg_key, d, "pending", None):
            # Un autre processus a réservé ce message pour cette règle.
            self.result.skipped["duplicate"] += 1
            return
        if not isinstance(msg, RawOutgoing):
            store.mark_auto_sent(msg["Message-ID"] or "", rule.id, now)

        hold = hold_reason(
            store,
            rule,
            now=now,
            hold_until=self.state.hold_until,
            sends_this_pass=self.sends_this_pass,
            max_per_pass=self.max_per_pass,
            max_per_hour=self.max_per_hour,
        )
        if hold == "stats_cap":
            # Ni file ni retenue : une demande libérée plus tard partirait
            # avec des chiffres périmés.
            store.rule_log_set_outcome(rule.id, msg_key, "skipped", hold)
            self.result.skipped[hold] += 1
            _logger.info("règles %s : règle %s, stats_cap", self.name, rule.id)
            return
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
        """Met le message en file ET avance le journal, en une transaction.

        Une redirection y garde son enveloppe dans les destinataires de
        l'entrée (`auto_redirect`) ; un transfert (`auto_forward`) et une
        réponse (`auto_reply`) portent la leur dans leurs en-têtes.
        """
        from script.todo.mail.smtp_send import recipients

        if isinstance(msg, RawOutgoing):
            to_text, subject = ", ".join(msg.envelope), msg.subject
            kind = "auto_redirect"
        else:
            to_text, subject = ", ".join(recipients(msg)), msg["Subject"]
            kind = (
                "auto_forward"
                if rule.action.kind == "forward"
                else "auto_reply"
            )
        queue_id = self.store.queue_auto(
            msg.as_bytes(),
            to_text,
            subject or "",
            kind=kind,
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


# -- Essai d'une règle -------------------------------------------------


@dataclass
class ForwardPreview:
    """Ce qu'une règle `forward` enverrait pour un message.

    `mode` : celui des options. `targets` / `removed` : comme
    `guards.Decision`, calculés quel que soit le verdict. `size` : octets
    du message (RFC822.SIZE, sinon longueur lue ; 0 inconnue). `outgoing` :
    le message construit (`EmailMessage` ou `smtp_send.RawOutgoing`),
    adressé aux destinations retenues, ou à l'adresse du compte quand
    aucune n'est retenue (`preview_self`). `reply_to` : le `Reply-To` d'un
    transfert (`forward_reply_to`). `raw` : les octets lus, gardés pour
    `send_trial`. `error` : pourquoi rien n'a été construit (« » sinon).
    """

    mode: str
    targets: tuple = ()
    removed: tuple = ()
    size: int = 0
    outgoing: object | None = None
    preview_self: bool = False
    reply_to: str = ""
    raw: bytes | None = field(default=None, repr=False)
    error: str = ""


@dataclass
class Simulation:
    """Ce qu'une règle ferait d'un message, calculé par `simulate`.

    `filter_lines` explique chaque nœud du filtre (`filter.ExplainLine`) ;
    `matched` est le verdict de sa racine (None : corps indisponible).
    `reason` est le verdict RÉEL des garde-fous (`guards.SEND` ou un code,
    `body_unavailable` compris), `reason_if_new` celui d'un message neuf
    reçu à l'instant, règle armée et jamais journalisée. `target` est
    l'adresse telle qu'elle partirait (« » s'il n'y en a pas). `rendered`
    est la réponse rendue (`markup.RenderedReply`), None si rien n'a pu
    l'être, et `error` dit alors pourquoi. `auth_serv_id` est l'identifiant
    lu du premier `Authentication-Results` (« » : aucun) ; `authenticated`
    le verdict de `guards.stats_authenticated` pour une règle `stats`,
    None sinon. `hold` est le code de `hold_reason` quand le verdict réel
    est d'envoyer ; `auth_serv_unset` est vrai pour une règle `stats` dont
    les réglages n'exigent aucun identifiant de serveur. `forward` est
    l'aperçu d'une règle `forward` (`ForwardPreview`), qui n'a jamais de
    `rendered`. `kind` est le type de l'action de la règle essayée.
    `sendable` dit si l'essai peut être envoyé à soi-même.
    """

    rule_enabled: bool
    executable: bool
    filter_lines: list
    matched: bool | None
    reason: str
    reason_if_new: str
    target: str
    subject: str
    rendered: object | None
    error: str
    headers_complete: bool
    auth_serv_id: str
    authenticated: bool | None
    hold: str = ""
    auth_serv_unset: bool = False
    forward: ForwardPreview | None = None
    kind: str = ""

    @property
    def sendable(self) -> bool:
        """Vrai si `send_trial` a de quoi envoyer : une réponse rendue, ou
        les octets d'un message à relayer sans erreur de construction."""
        if self.rendered is not None:
            return True
        preview = self.forward
        return (
            preview is not None
            and preview.raw is not None
            and not preview.error
        )


def simulate(
    session,
    rule,
    header,
    *,
    uidvalidity: int,
    body_loader=None,
    headers_complete: bool = True,
    all_accounts=None,
    rules_base=None,
    report_settings=None,
    now: Callable[[], float] = time.time,
    raw_loader=None,
) -> Simulation:
    """Ce que la règle ferait de ce message, sans rien écrire ni envoyer.

    Ni journal, ni `state.json`, ni `rules.json`, ni `auto_sent`, ni
    instantané du rapport ne sont écrits, et le verrou du compte n'est pas
    pris. `header` est un `HeaderInfo` (en-têtes complets) ou une ligne du
    cache (`headers_complete` faux). `report_settings` remplace les
    réglages du rapport lus du disque. `raw_loader` rend les octets
    complets du message (`make_raw_loader`) pour l'aperçu d'une règle
    `forward` ; None, l'aperçu dit que le message est indisponible. Ne lève
    jamais : une exception devient `error`.
    """
    sim = Simulation(
        rule_enabled=bool(rule.enabled),
        executable=rule.action.kind in EXECUTABLE_KINDS,
        filter_lines=[],
        matched=None,
        reason="",
        reason_if_new="",
        target="",
        subject="",
        rendered=None,
        error="",
        headers_complete=headers_complete,
        auth_serv_id="",
        authenticated=None,
        kind=rule.action.kind,
    )
    try:
        _simulate(
            sim,
            session,
            rule,
            header,
            uidvalidity=int(uidvalidity),
            body_loader=body_loader,
            all_accounts=all_accounts,
            rules_base=rules_base,
            report_settings=report_settings,
            instant=int(now()),
            raw_loader=raw_loader,
        )
    except Exception as exc:
        sim.rendered = None
        if not sim.error:
            sim.error = str(exc) or type(exc).__name__
    return sim


def _simulate(
    sim: Simulation,
    session,
    rule,
    header,
    *,
    uidvalidity: int,
    body_loader,
    all_accounts,
    rules_base,
    report_settings,
    instant: int,
    raw_loader=None,
) -> None:
    """Remplit `sim` ; voir `simulate`."""
    from script.todo.mail import smtp_send

    store, account = session.store, session.account
    name = getattr(account, "name", "") or ""
    base = rules_base if rules_base is not None else storage.base_of(store)
    if base is None:
        sim.error = t("mail_rules_ephemeral")
        return
    is_stats = rule.action.kind == "stats"
    view = message_view(header, uidvalidity)
    msg_key = store.message_key(view.msgid, uidvalidity, view.uid)
    settings = report_settings
    if settings is None:
        settings = storage.ReportSettings()
        if is_stats:
            try:
                settings = storage.load_report(name, base)
            except RuleError as exc:
                sim.error = str(exc)
    sim.auth_serv_id = guards.authserv_id(view)
    if is_stats:
        sim.authenticated = guards.stats_authenticated(
            view, settings.auth_serv_id
        )
        sim.auth_serv_unset = not settings.auth_serv_id
    sender, _target, target_addr = guards.response_addresses(rule, view)
    sim.target = target_addr

    # Un seul chargement du corps pour l'explication et les deux verdicts.
    loader = rules_filter._BodyOnce(body_loader)
    sim.filter_lines = rules_filter.explain(rule.filter, view, loader)
    sim.matched = sim.filter_lines[0].result if sim.filter_lines else None

    def last_send_at(from_norm, target_norm):
        return store.rule_log_last_send(
            rule.id,
            store.address_hash(from_norm),
            store.address_hash(target_norm) or None,
        )

    ctx = guards.GuardContext(
        now=instant,
        own_addresses=account_addresses(account),
        other_account_addresses=other_account_addresses(account, all_accounts),
        is_logged=lambda: store.rule_log_seen(rule.id, msg_key),
        last_send_at=last_send_at,
        auth_serv_id=settings.auth_serv_id,
        is_own_send=_own_send_check(
            store, view, _trial_forward_ids(name, base, rule)
        ),
    )
    try:
        sim.reason = guards.decide(rule, view, ctx, loader).reason
    except BodyUnavailable:
        sim.reason = "body_unavailable"
    # Le même message reçu à l'instant, par une règle armée avant lui et
    # qui ne l'a jamais vu ; la limite par expéditeur reste celle du journal.
    try:
        sim.reason_if_new = guards.decide(
            dataclasses.replace(rule, armed=Armed(uidvalidity, 0, 0)),
            dataclasses.replace(view, internaldate=instant),
            dataclasses.replace(ctx, is_logged=lambda: False),
            loader,
        ).reason
    except BodyUnavailable:
        sim.reason_if_new = "body_unavailable"

    if sim.reason == guards.SEND:
        try:
            caps = storage.load_caps(name, base)
        except RuleError:
            caps = storage.Caps()
        try:
            hold_until = storage.load_state(name, base).hold_until
        except RuleError:
            hold_until = 0
        sim.hold = (
            hold_reason(
                store,
                rule,
                now=instant,
                hold_until=hold_until,
                sends_this_pass=0,
                max_per_pass=caps.per_pass,
                max_per_hour=caps.per_hour,
            )
            or ""
        )

    if not sim.executable:
        sim.error = t("mail_rules_trial_kind")
        return
    if sim.error:
        return
    if rule.action.kind == "forward":
        try:
            opts = rules_model.forward_options(rule.action)
        except RuleError as exc:
            sim.error = str(exc)
            return
        sim.forward = _forward_preview(
            account, rule, opts, view, ctx, raw_loader
        )
        return
    domain = (getattr(account, "email", "") or "").rpartition("@")[2]
    try:
        media = {
            ref.file: storage.read_media(name, ref, base=base)
            for ref in rule.action.images
        }
        if is_stats:
            # L'instantané du jour s'il existe, sinon un calcul non écrit.
            mailbox = rules_report.mailbox_from_dict(
                storage.load_report_snapshot(name, base),
                rules_report.snapshot_key(settings, instant),
            )
            data = rules_report.build_data(
                store, settings, now=instant, sender=sender, mailbox=mailbox
            )
            subject = rules_report.render_subject(
                view.subject, rule.action.subject, data
            )
            rendered = rules_report.render_stats_reply(
                rule.action, media, domain, data
            )
        else:
            subject = smtp_send.auto_reply_subject(
                view.subject, rule.action.subject
            )
            rendered = markup.render_reply(rule.action, media, domain)
    except RuleError as exc:
        sim.error = str(exc)
        return
    sim.subject, sim.rendered = subject, rendered


def _trial_forward_ids(name: str, base, rule) -> frozenset:
    """Les règles `forward` du compte, plus la règle essayée si elle en est
    une et n'est pas encore enregistrée ; un fichier illisible n'en donne
    que celle-ci."""
    try:
        rules = list(storage.load(name, base))
    except RuleError:
        rules = []
    return _forward_ids(rules + [rule])


def _forward_preview(account, rule, opts, view, ctx, raw_loader):
    """L'aperçu d'une règle `forward` pour un message (`ForwardPreview`).

    Rien n'est lu au-delà de `FORWARD_MAX_BYTES` ; sans destination
    retenue, le message est construit adressé au compte lui-même.
    """
    preview = ForwardPreview(mode=opts.mode)
    preview.targets, preview.removed = guards.forward_targets(rule, view, ctx)
    preview.size = view.size
    preview.reply_to = forward_reply_to(
        view, ctx.own_addresses, ctx.other_account_addresses
    )
    if view.size > FORWARD_MAX_BYTES:
        preview.error = t("mail_rules_reason_too_big")
        return preview
    if raw_loader is None:
        preview.error = t("mail_rules_reason_body_unavailable")
        return preview
    try:
        raw = raw_loader()
    except BodyUnavailable:
        preview.error = t("mail_rules_reason_body_unavailable")
        return preview
    except MessageTooBig as exc:
        preview.size = exc.size
        preview.error = t("mail_rules_reason_too_big")
        return preview
    preview.raw = raw
    preview.size = preview.size or len(raw)
    preview.preview_self = not preview.targets
    try:
        preview.outgoing = forward_message(
            account,
            opts,
            raw,
            list(preview.targets) or [account.email],
            intro=rule.action.body,
            reply_to=preview.reply_to,
        )
    except SmtpError as exc:
        preview.error = str(exc)
    return preview


def send_trial(
    session,
    rule,
    sim: Simulation,
    *,
    verrou=None,
    deliver_fn=None,
    now: Callable[[], float] = time.time,
) -> str:
    """Envoie la réponse simulée à l'adresse du compte ; rend le statut de
    `deliver`.

    Le sujet porte le préfixe d'essai ; ni `In-Reply-To` ni `References` :
    l'essai n'entre pas dans le fil d'un tiers. Le Message-ID est inscrit
    dans `auto_sent` AVANT l'envoi, ce qui garde la copie classée dans
    Envoyés et sa réception dans INBOX hors des statistiques. Rien au
    journal des règles, aucun plafond ni limite, aucune file : hors ligne,
    `RuleError`. Une réponse non rendue lève `RuleError` ; les autres
    exceptions de `deliver` traversent.

    Règle `forward` : les octets lus par l'essai repartent vers le compte
    SEULEMENT. Un transfert garde le `Reply-To` de l'aperçu, prend le
    préfixe d'essai et entre dans `auto_sent` ; une redirection part
    inchangée sous son bloc `Resent-*`, sans rien dans `auto_sent` (son
    Message-ID est celui de l'original), et sera écartée au retour
    (`resent_loop`).
    """
    from script.todo.mail import smtp_send
    from script.todo.mail.tui import DeliverOffline

    account = session.account
    prefix = t("mail_rules_trial_subject_prefix")
    if rule.action.kind == "forward":
        preview = sim.forward
        if preview is None or preview.raw is None or preview.error:
            raise RuleError(t("mail_rules_trial_unavailable"))
        try:
            msg = forward_message(
                account,
                rules_model.forward_options(rule.action),
                preview.raw,
                [account.email],
                intro=rule.action.body,
                reply_to=preview.reply_to,
                subject_prefix=prefix,
            )
        except SmtpError as exc:
            raise RuleError(str(exc)) from exc
    else:
        rendered = sim.rendered
        if rendered is None:
            raise RuleError(t("mail_rules_trial_unavailable"))
        msg = smtp_send.build_auto_reply(
            account,
            account.email,
            f"{prefix} {sim.subject}",
            rendered.text,
            html=rendered.html,
            inline_images=rendered.inline,
            attachment_parts=rendered.attachments,
        )
    if not isinstance(msg, RawOutgoing):
        session.store.mark_auto_sent(
            msg["Message-ID"] or "", rule.id, int(now())
        )
    if deliver_fn is None:
        # Importé à l'appel : un remplacement de `tui.deliver` s'applique.
        from script.todo.mail.tui import deliver as deliver_fn
    try:
        return deliver_fn(session, msg, verrou=verrou, queue_offline=False)
    except DeliverOffline as exc:
        raise RuleError(t("mail_rules_trial_offline")) from exc
