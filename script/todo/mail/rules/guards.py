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
    "unauthenticated",
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
    "stats_cap",
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

# Une chaîne entre guillemets (RFC 5322), barre oblique inverse comprise.
_QUOTED = r'"(?:[^"\\]|\\[\s\S])*"'
# « clé=valeur » d'un résultat, la valeur étant un jeton, une chaîne entre
# guillemets ou un mélange des deux (« "a;b"@domaine »). Une chaîne
# entre guillemets isolée est consommée par la première branche, sans
# groupe : aucune clé n'est lue à l'intérieur. Le regard arrière limite les
# essais au début d'un mot, pour un temps linéaire sur un en-tête choisi
# par un tiers.
_PROPERTY_RE = re.compile(
    rf"{_QUOTED}|(?<![a-z0-9_.-])([a-z0-9_.-]+)\s*=\s*"
    rf'((?:{_QUOTED}|[^\s";])+)'
)


@dataclass
class GuardContext:
    """Ce que les garde-fous consultent hors du message.

    `own_addresses` et `other_account_addresses` sont normalisées.
    `is_logged()` dit si le journal a déjà une ligne pour (règle, message).
    `last_send_at(from_norm, target_norm)` rend l'époque du dernier envoi
    de CETTE règle vers cet expéditeur OU cette cible, ou None.
    `auth_serv_id`, s'il n'est pas vide, est l'identifiant de serveur
    qu'une règle `stats` exige du premier `Authentication-Results`.
    """

    now: int
    own_addresses: frozenset
    other_account_addresses: frozenset
    is_logged: Callable[[], bool]
    last_send_at: Callable[[str, str], int | None]
    auth_serv_id: str = ""


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
    texte reste analysé, et un résultat « fail » qu'il porte compte. Une
    parenthèse entre guillemets est un caractère ordinaire, un guillemet
    dans un commentaire aussi ; « \\ » protège le caractère qui suit dans
    l'un comme dans l'autre.
    """
    out: list[str] = []
    opened: list[int] = []
    quoted = False
    escaped = False
    for char in text:
        if escaped:
            escaped = False
            out.append(char)
        elif char == "\\" and (quoted or opened):
            escaped = True
            out.append(char)
        elif quoted:
            quoted = char != '"'
            out.append(char)
        elif char == "(":
            opened.append(len(out))
            out.append(char)
        elif char == ")" and opened:
            del out[opened.pop() :]
            out.append(" ")
        else:
            quoted = char == '"' and not opened
            out.append(char)
    return "".join(out)


def _split_resinfo(text: str) -> list[str] | None:
    """`text` coupé à chaque « ; » hors d'une chaîne entre guillemets.

    Rend None quand une chaîne entre guillemets reste ouverte : le texte
    n'a alors aucune découpe sûre.
    """
    parts: list[str] = []
    start = 0
    quoted = False
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
        elif quoted:
            if char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == ";":
            parts.append(text[start:index])
            start = index + 1
    if quoted:
        return None
    parts.append(text[start:])
    return parts


def _unquote(value: str) -> str:
    """`value` sans ses guillemets ni ses barres d'échappement :
    « "a;b"@domaine » devient « a;b@domaine »."""
    out: list[str] = []
    quoted = False
    escaped = False
    for char in value:
        if escaped:
            escaped = False
            out.append(char)
        elif quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        else:
            out.append(char)
    return "".join(out)


def _auth_results(view: MessageView) -> list[tuple[str, str, dict]] | None:
    """Les résultats du PREMIER `Authentication-Results`.

    Chaque élément est (méthode, résultat, propriétés), en minuscules ;
    l'identifiant du serveur, qui précède le premier « ; », est ignoré.
    Le découpage respecte les chaînes entre guillemets : une adresse
    d'enveloppe « "a;spf=pass …"@domaine » reste UNE valeur, celle de la
    propriété qui la porte, sans guillemets. Une propriété répétée garde
    sa première valeur : ce que l'expéditeur glisse dans une valeur vient
    après la clé écrite par le serveur. Rend None quand une chaîne entre
    guillemets reste ouverte : l'en-tête est alors illisible.
    """
    first = _first_occurrence(view, "Authentication-Results")
    if not first:
        return []
    segments = _split_resinfo(_strip_comments(first.lower()))
    if segments is None:
        return None
    results = []
    for segment in segments:
        pairs = [
            (match.group(1), _unquote(match.group(2)))
            for match in _PROPERTY_RE.finditer(segment)
            if match.group(1) is not None
        ]
        if not pairs:
            continue
        method, result = pairs[0]
        if "." in method:
            continue
        props: dict = {}
        for key, value in pairs[1:]:
            props.setdefault(key, value)
        results.append((method, result, props))
    return results


def _auth_fails(view: MessageView) -> bool:
    """Vrai si le premier `Authentication-Results` rapporte un échec, ou
    s'il est illisible (chaîne entre guillemets jamais refermée)."""
    results = _auth_results(view)
    if results is None:
        return True
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
    peuvent venir de l'expéditeur ; un en-tête illisible n'authentifie
    rien.
    """
    target = stats_target(view)
    domain = _domain_of(domain or "")
    if not target or not domain or _domain_of(target) != domain:
        return False
    for method, result, props in _auth_results(view) or ():
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


def authserv_id(view: MessageView) -> str:
    """L'identifiant du serveur du PREMIER `Authentication-Results`.

    C'est le texte qui précède le premier « ; », commentaires et jeton de
    version retirés, en minuscules. Rend « » sans en-tête, et « » quand ce
    texte porte un « = » : l'en-tête s'ouvre alors sur un résultat
    (« spf=pass … »), sans identifiant.
    """
    first = _first_occurrence(view, "Authentication-Results")
    if not first:
        return ""
    head = _strip_comments(first.split(";", 1)[0]).lower()
    if "=" in head:
        return ""
    tokens = head.split()
    return tokens[0] if tokens else ""


def stats_authenticated(view: MessageView, auth_serv_id: str = "") -> bool:
    """Vrai si le From d'une demande de rapport est authentifié.

    From doit porter une seule adresse sans ambiguïté ; si `auth_serv_id`
    est réglé, l'identifiant du premier `Authentication-Results` doit lui
    être égal sans égard à la casse ; puis `authentication_passes` doit
    authentifier le domaine du From. L'identifiant ne protège que si le
    serveur de réception retire les en-têtes entrants qui portent le sien :
    sinon l'expéditeur peut l'écrire lui-même.
    """
    sender = stats_target(view)
    if not sender:
        return False
    wanted = (auth_serv_id or "").strip().lower()
    if wanted and authserv_id(view) != wanted:
        return False
    return authentication_passes(view, sender.rpartition("@")[2])


def response_addresses(rule: Rule, view: MessageView) -> tuple[str, str, str]:
    """(expéditeur normalisé, cible normalisée, cible sous sa forme reçue).

    Règle `stats` : la cible est l'adresse de From, que l'authentification
    vérifie et à laquelle se rapporte le délai du demandeur. Autre règle :
    Return-Path, sinon From, jamais Reply-To. N'évalue ni le filtre ni les
    garde-fous.
    """
    sender_addr = sole_address(view.frm, raw=True)
    sender = normalize_address(sender_addr) if sender_addr else ""
    if rule.action.kind == "stats":
        return sender, sender, sender_addr
    if _first_occurrence(view, "Return-Path") is None:
        # Même cible que `reply_target`, sans relire From une seconde fois.
        return sender, sender, sender_addr
    return sender, reply_target(view), reply_target(view, raw=True)


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
    view: MessageView,
    ctx: GuardContext,
    sender: str,
    target: str,
    extra: tuple = (),
) -> str | None:
    """Contrôles 12 à 17 : à qui la réponse partirait.

    Un From non vide dont aucune adresse sûre ne se tire (illisible,
    plusieurs boîtes, libellé qui porte une autre adresse) donne
    `no_target` même si Return-Path fournit une cible : sous un NON, un
    From illisible ne vaut aucune valeur et rendrait vraie une condition
    écrite pour l'exclure, et les contrôles 14 à 16 ne verraient pas
    l'expéditeur. Les adresses de `extra` passent aussi les contrôles 14
    à 16 (robot, nous-mêmes, autre compte), sans être une cible.
    """
    return_path = _first_occurrence(view, "Return-Path")
    if return_path is not None and not addr_specs(return_path):
        return "null_sender"
    if not target or (view.frm.strip() and not sender):
        return "no_target"
    people = [address for address in (target, sender, *extra) if address]
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

    Une règle `stats` répond à From ; son Return-Path, s'il porte une
    adresse, passe tout de même les contrôles de robot, de nous-mêmes et
    d'autre compte. Elle exige en plus un expéditeur authentifié
    (`stats_authenticated`), contrôlé après `auth_fail`.
    """
    sender, target, target_addr = response_addresses(rule, view)
    is_stats = rule.action.kind == "stats"
    extra = ()
    if is_stats:
        envelope = reply_target(view)
        if _first_occurrence(view, "Return-Path") is not None and envelope:
            extra = (envelope,)

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
        view, ctx, sender, target, extra
    )
    if reason is None and _auth_fails(view):
        reason = "auth_fail"
    if (
        reason is None
        and is_stats
        and not stats_authenticated(view, ctx.auth_serv_id)
    ):
        reason = "unauthenticated"
    if reason is None and _throttled(rule, ctx, sender, target):
        reason = "throttled"
    return verdict(reason or SEND, True)
