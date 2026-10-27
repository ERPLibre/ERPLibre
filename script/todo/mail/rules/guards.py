#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Garde-fous d'une réponse automatique : fonction de décision ordonnée.

`decide` passe les contrôles de `REASONS` dans l'ordre et s'arrête au
premier qui s'applique ; aucun ne s'applique, la décision est `SEND`. Les
fonctions sont pures : le journal et la limite d'envoi se consultent par
les callables de `GuardContext`, jamais par un accès direct au cache.

Chaque en-tête supplémentaire peut paraître plusieurs fois dans un
message ; CHAQUE occurrence est testée à part (« bulk » puis « list » ne
forment pas le jeton « bulk list »). Pour `Return-Path` et
`Authentication-Results`, seule la PREMIÈRE occurrence compte : c'est la
plus haute, ajoutée par le serveur de remise ; une seconde a pu être
glissée dans le message par l'expéditeur.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from script.todo.mail.rules import filter as rules_filter
from script.todo.mail.rules.filter import (
    addr_specs,
    normalize_address,
    sole_address,
)
from script.todo.mail.rules.model import MessageView, Rule
from script.todo.mail.smtp_send import X_LOOP_MARKER
from script.todo.mail.tui_text import fold

SILENT_REASONS = frozenset({"not_armed", "duplicate", "no_match"})
# Ordre d'évaluation : le premier code qui s'applique l'emporte.
REASONS = (
    "not_armed",
    "duplicate",
    "too_old",
    "bad_date",
    "no_match",
    "auto_submitted",
    "precedence",
    "list",
    "auto_response_suppress",
    "x_loop",
    "spam",
    "null_sender",
    "no_target",
    "robot_sender",
    "self",
    "other_account",
    "not_addressed",
    "auth_fail",
    "throttled",
)
# Codes posés par le moteur et la vidange de la file ; le moteur n'en
# journalise aucun autre.
ENGINE_REASONS = (
    "pass_cap",
    "hour_cap",
    "hold_first",
    "cache_rebuilt",
    "offline",
    "smtp_transient",
    "smtp_permanent",
    "rule_disabled",
    "rule_changed",
    "expired",
    "attempts_exhausted",
    "media",
    "build_error",
    "body_unavailable",
    "regex_timeout",
)
SEND = "send"
# Avance tolérée d'une date de réception sur l'horloge locale, en secondes.
FUTURE_SKEW_S = 600
BULK_PRECEDENCE = frozenset({"bulk", "list", "junk", "auto_reply"})
SUPPRESS_TOKENS = frozenset({"all", "oof", "autoreply"})
ROBOT_LOCALPARTS = re.compile(
    r"^(mailer-daemon|postmaster|no[-_.]?reply|do[-_.]?not[-_.]?reply|"
    r"bounces?([-+].*)?|.*[-+]bounces?)$",
    re.I,
)

# « clé=valeur » d'un résultat ; le regard arrière limite les essais au
# début d'un mot, pour un temps linéaire sur un en-tête choisi par un tiers.
_PROPERTY_RE = re.compile(r"(?<![a-z0-9_.-])([a-z0-9_.-]+)\s*=\s*(\S+)")


@dataclass
class GuardContext:
    """Ce que les garde-fous consultent hors du message.

    `own_addresses` et `other_account_addresses` sont normalisées.
    `is_logged()` dit si le journal a déjà une ligne pour (règle, message).
    `last_send_at(from_norm, target_norm)` rend l'époque du dernier envoi
    de CETTE règle vers cet expéditeur OU cette cible, ou None.
    """

    now: int
    own_addresses: frozenset
    other_account_addresses: frozenset
    is_logged: Callable[[], bool]
    last_send_at: Callable[[str, str], int | None]


@dataclass(frozen=True)
class Decision:
    """Résultat de `decide`.

    `reason` est un code de `REASONS` ou `SEND`. `matched` dit si le filtre
    a été évalué vrai (« arrêter ici » en dépend). `sender` est l'adresse
    de From normalisée, « » si From n'en porte pas une seule sans
    ambiguïté ; `target` l'adresse de réponse normalisée, pour les
    comparaisons ; `target_addr` la même telle que reçue, pour l'envoi
    SMTP. `logged` est faux pour `SILENT_REASONS` et
    vrai pour tout autre code, `SEND` compris : un envoi est journalisé.
    """

    reason: str
    matched: bool
    sender: str
    target: str
    target_addr: str
    logged: bool


def header_values(view: MessageView, name: str) -> list[str]:
    """Les occurrences non vides d'un en-tête supplémentaire, dans l'ordre."""
    raw = view.extra.get(name.lower(), "")
    return [value.strip() for value in raw.split("\n") if value.strip()]


def _first_occurrence(view: MessageView, name: str) -> str | None:
    """La première occurrence, même vide ; None si l'en-tête est absent."""
    raw = view.extra.get(name.lower())
    if raw is None:
        return None
    return raw.split("\n", 1)[0].strip()


def reply_target(view: MessageView, *, raw: bool = False) -> str:
    """L'adresse à qui répondre : Return-Path, sinon From, jamais Reply-To.

    Return-Path présent : l'addr-spec de sa première occurrence, ou « »
    si elle est vide ou « <> ». Absent : l'adresse de From si elle est
    unique et sans ambiguïté (`filter.sole_address`), sinon « ». `raw`
    rend la forme reçue (pour l'envoi), sinon la forme normalisée.
    """
    first = _first_occurrence(view, "Return-Path")
    if first is None:
        return sole_address(view.frm, raw=raw)
    specs = addr_specs(first, raw=raw)
    return specs[0] if specs else ""


def stats_target(view: MessageView) -> str:
    """L'addr-spec normalisée de From s'il en porte une seule, sinon « ».

    Une adresse que le libellé contredit compte comme ambiguë
    (`filter.sole_address`).
    """
    return sole_address(view.frm)


def _strip_comments(text: str) -> str:
    """`text` dont chaque commentaire RFC 5322 « (…) » devient un blanc.

    Les commentaires imbriqués partent avec leur parent, en un seul
    parcours : « spf=pass (… dkim=fail …) » ne dit rien de DKIM. Une
    parenthèse ouvrante jamais refermée reste, avec ce qui la suit : le
    texte reste analysé, et un résultat « fail » qu'il porte compte.
    """
    out: list[str] = []
    opened: list[int] = []
    for char in text:
        if char == "(":
            opened.append(len(out))
            out.append(char)
        elif char == ")" and opened:
            del out[opened.pop() :]
            out.append(" ")
        else:
            out.append(char)
    return "".join(out)


def _auth_results(view: MessageView) -> list[tuple[str, str, dict]]:
    """Les résultats du PREMIER `Authentication-Results`.

    Chaque élément est (méthode, résultat, propriétés), en minuscules ;
    l'identifiant du serveur, qui précède le premier « ; », est ignoré.
    """
    first = _first_occurrence(view, "Authentication-Results")
    if not first:
        return []
    text = _strip_comments(first.lower())
    results = []
    for segment in text.split(";"):
        pairs = _PROPERTY_RE.findall(segment)
        if not pairs:
            continue
        method, result = pairs[0]
        if "." in method:
            continue
        props = {key: value.strip('"') for key, value in pairs[1:]}
        results.append((method, result.strip('"'), props))
    return results


def _auth_fails(view: MessageView) -> bool:
    results = _auth_results(view)
    verdicts = {(method, result) for method, result, _props in results}
    if ("dmarc", "fail") in verdicts:
        return True
    return ("spf", "fail") in verdicts and ("dkim", "pass") not in verdicts


def _domain_of(value: str) -> str:
    return normalize_address(value.rpartition("@")[2])


def _aligned(candidate: str, domain: str) -> bool:
    return candidate == domain or candidate.endswith("." + domain)


def authentication_passes(view: MessageView, domain: str) -> bool:
    """Vrai si le premier `Authentication-Results` authentifie `domain`.

    `domain` doit être celui de `stats_target(view)`. Puis, au choix :
    `dmarc=pass` avec `header.from` égal à `domain` ; `dkim=pass` avec
    `header.d` aligné (égal, ou sous-domaine) ; `spf=pass` avec
    `smtp.mailfrom` aligné. Les en-têtes suivants sont ignorés : ils
    peuvent venir de l'expéditeur.
    """
    target = stats_target(view)
    domain = _domain_of(domain or "")
    if not target or not domain or _domain_of(target) != domain:
        return False
    for method, result, props in _auth_results(view):
        if result != "pass":
            continue
        if method == "dmarc":
            if _domain_of(props.get("header.from", "")) == domain:
                return True
        elif method == "dkim":
            if _aligned(_domain_of(props.get("header.d", "")), domain):
                return True
        elif method == "spf":
            mailfrom = _domain_of(props.get("smtp.mailfrom", ""))
            if _aligned(mailfrom, domain):
                return True
    return False


def _localpart(address: str) -> str:
    return address.rpartition("@")[0]


def _check_headers(view: MessageView) -> str | None:
    """Contrôles 6 à 11 : en-têtes qui signalent un envoi automatique."""
    for value in header_values(view, "Auto-Submitted"):
        if fold(value.split(";", 1)[0]).strip() != "no":
            return "auto_submitted"
    for value in header_values(view, "Precedence"):
        if fold(value) in BULK_PRECEDENCE:
            return "precedence"
    if "list-id" in view.extra or "list-unsubscribe" in view.extra:
        return "list"
    for value in header_values(view, "X-Auto-Response-Suppress"):
        tokens = {fold(token).strip() for token in value.split(",")}
        if tokens & SUPPRESS_TOKENS:
            return "auto_response_suppress"
    marker = X_LOOP_MARKER.lower()
    for value in header_values(view, "X-Loop"):
        if marker in value.lower():
            return "x_loop"
    for value in header_values(view, "X-Spam-Flag"):
        if fold(value) == "yes":
            return "spam"
    return None


def _check_addresses(
    view: MessageView, ctx: GuardContext, sender: str, target: str
) -> str | None:
    """Contrôles 12 à 17 : à qui la réponse partirait.

    Un From non vide dont aucune adresse sûre ne se tire (illisible,
    plusieurs boîtes, libellé qui porte une autre adresse) donne
    `no_target` même si Return-Path fournit une cible : sous un NON, un
    From illisible ne vaut aucune valeur et rendrait vraie une condition
    écrite pour l'exclure, et les contrôles 14 à 16 ne verraient pas
    l'expéditeur.
    """
    return_path = _first_occurrence(view, "Return-Path")
    if return_path is not None and not addr_specs(return_path):
        return "null_sender"
    if not target or (view.frm.strip() and not sender):
        return "no_target"
    people = [address for address in (target, sender) if address]
    if any(ROBOT_LOCALPARTS.match(_localpart(a)) for a in people):
        return "robot_sender"
    if any(address in ctx.own_addresses for address in people):
        return "self"
    if any(address in ctx.other_account_addresses for address in people):
        return "other_account"
    recipients = addr_specs(view.to) + addr_specs(view.cc)
    if not any(address in ctx.own_addresses for address in recipients):
        return "not_addressed"
    return None


def _not_armed(rule: Rule, view: MessageView) -> bool:
    armed = rule.armed
    return (
        armed is None
        or view.uidvalidity != armed.uidvalidity
        or view.uid < armed.uidnext
        or 0 < view.internaldate < armed.at
    )


def _throttled(rule: Rule, ctx: GuardContext, sender: str, target: str):
    if not rule.throttle_enabled:
        return False
    last = ctx.last_send_at(sender, target)
    return last is not None and ctx.now - last < rule.throttle_minutes * 60


def decide(
    rule: Rule,
    view: MessageView,
    ctx: GuardContext,
    body_loader: Callable[[], str] | None,
) -> Decision:
    """Le premier garde-fou qui s'applique, ou `SEND`.

    L'âge se mesure sur la date de réception du serveur, jamais sur
    l'en-tête Date que l'expéditeur choisit ; une date inconnue est trop
    vieille. `filter.BodyUnavailable` traverse : le moteur décide si le
    message devient un trou ou un échec.
    """
    sender_addr = sole_address(view.frm, raw=True)
    sender = normalize_address(sender_addr) if sender_addr else ""
    if _first_occurrence(view, "Return-Path") is None:
        # Même cible que `reply_target`, sans relire From une seconde fois.
        target, target_addr = sender, sender_addr
    else:
        target = reply_target(view)
        target_addr = reply_target(view, raw=True)

    def verdict(reason: str, matched: bool) -> Decision:
        return Decision(
            reason=reason,
            matched=matched,
            sender=sender,
            target=target,
            target_addr=target_addr,
            logged=reason not in SILENT_REASONS,
        )

    if _not_armed(rule, view):
        return verdict("not_armed", False)
    if ctx.is_logged():
        return verdict("duplicate", False)
    age = ctx.now - view.internaldate
    if view.internaldate == 0 or age > rule.max_age_hours * 3600:
        return verdict("too_old", False)
    if view.internaldate > ctx.now + FUTURE_SKEW_S:
        return verdict("bad_date", False)
    if not rules_filter.evaluate(rule.filter, view, body_loader):
        return verdict("no_match", False)
    reason = _check_headers(view) or _check_addresses(
        view, ctx, sender, target
    )
    if reason is None and _auth_fails(view):
        reason = "auth_fail"
    if reason is None and _throttled(rule, ctx, sender, target):
        reason = "throttled"
    return verdict(reason or SEND, True)
