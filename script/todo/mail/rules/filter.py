#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Évaluation de l'arbre de conditions d'une règle sur un message.

Une condition est vraie si UNE des valeurs du champ convient : De et À/Cc
rendent une valeur par adresse, Sujet et Corps une seule. Les champs
d'adresse ne rendent que l'addr-spec : le libellé affiché (« Patron
<x@…> ») est choisi par l'expéditeur, donc usurpable, et n'est jamais
comparé.

Le corps est TRI-ÉTAT : connu, ou inconnu. Il n'est jamais « vide » par
défaut, car sous un NON une condition fausse deviendrait vraie et
déclencherait un envoi sans que le corps ait été lu. Un corps inconnu
lève donc `BodyUnavailable` hors d'`evaluate`, jamais convertie en faux.
"""

from __future__ import annotations

import email.utils
import fnmatch
import functools
import re
from collections.abc import Callable

from script.todo.mail.rules.model import (
    REGEX_TEXT_MAX,
    Condition,
    Group,
    MessageView,
    RuleError,
    regex_fault,
)
from script.todo.mail.rules.regex_worker import search_any
from script.todo.mail.tui_text import fold
from script.todo.todo_i18n import t

# Longueur maximale du corps soumis aux conditions `body`.
BODY_TEXT_MAX = 200_000


class BodyUnavailable(Exception):
    """Le corps du message est inconnu au moment où une condition le lit.

    Levée par un chargeur de corps qui ne peut pas le rendre (hors ligne,
    FETCH en échec, message disparu), ou par `evaluate` quand aucun
    chargeur n'est fourni. `online` dit si le lien était établi : vrai, le
    corps a été demandé et refusé (échec à journaliser) ; faux, il n'a pas
    pu l'être (message à réévaluer plus tard).
    """

    def __init__(self, *args, online: bool = False) -> None:
        super().__init__(*args)
        self.online = online


def _normalize_domain(domain: str) -> str:
    """Chaque label « xn-- » décodé IDNA ; un échec le laisse tel quel."""
    labels = []
    for label in domain.split("."):
        if label.startswith("xn--"):
            try:
                label = label.encode("ascii").decode("idna").lower()
            except (UnicodeError, ValueError):
                pass
        labels.append(label)
    return ".".join(labels)


def normalize_address(addr: str) -> str:
    """Forme de COMPARAISON d'une adresse : sans blancs, en minuscules,
    domaine IDNA décodé.

    Sert aux comparaisons et aux empreintes seulement, jamais à l'envoi :
    `smtplib` refuserait un domaine non ASCII sans SMTPUTF8.
    """
    text = (addr or "").strip().lower()
    if "@" not in text:
        return text
    local, _, domain = text.rpartition("@")
    return f"{local}@{_normalize_domain(domain)}"


def normalize_pattern(pattern: str) -> str:
    """Le même traitement que `normalize_address`, jokers conservés.

    Un label qui porte un joker n'est pas un « xn-- » valide : son
    décodage échoue et il reste tel quel.
    """
    return normalize_address(pattern)


# Caractère qu'aucune addr-spec ne porte hors d'une partie locale entre
# guillemets : l'analyseur rend parfois un fragment de libellé (« <x@…> »
# avec son chevron) comme adresse quand le libellé est mal formé.
_GARBLED_ADDR_RE = re.compile(r'[\s<>(),;:"\[\]]')
# Tout ce qui ressemble à une adresse dans un en-tête, libellé compris.
# La recherche n'essaie que le DÉBUT d'un fragment : sans le regard
# arrière, chaque position d'une longue suite sans « @ » relirait la suite
# jusqu'au bout, en temps quadratique sur un en-tête choisi par un tiers.
_ADDRESS_LIKE_RE = re.compile(
    r'(?<![^\s<>(),;:"\[\]])[^\s<>(),;:"\[\]]+@[^\s<>(),;:"\[\]]+'
)


def addr_specs(header_value: str, *, raw: bool = False) -> list[str]:
    """Les addr-spec (contenant « @ ») d'un en-tête d'adresses.

    Normalisées par `normalize_address`, ou seulement débarrassées des
    blancs si `raw` est vrai. Le libellé n'est jamais rendu. Un fragment
    qui porte un blanc, un chevron ou un séparateur n'est pas une adresse
    et n'est pas rendu non plus.
    """
    out = []
    for _name, addr in email.utils.getaddresses([header_value or ""]):
        addr = addr.strip()
        if "@" not in addr or _GARBLED_ADDR_RE.search(addr):
            continue
        out.append(addr if raw else normalize_address(addr))
    return out


def sole_address(header_value: str, *, raw: bool = False) -> str:
    """L'unique adresse d'un en-tête d'une seule boîte (From), ou « ».

    Rend « » si l'en-tête porte zéro ou plusieurs addr-spec, ou si son
    libellé contient une AUTRE adresse que l'addr-spec. Les en-têtes
    arrivent décodés RFC 2047 : un libellé encodé qui cache « @ » et « , »
    devient, une fois décodé, une seconde adresse que l'expéditeur a
    choisie, ou un en-tête que l'analyseur ne lit plus. Une adresse ambiguë
    n'est ni une cible de réponse ni une clé de limite.
    """
    specs = addr_specs(header_value, raw=raw)
    if len(specs) != 1:
        return ""
    spec = specs[0]
    wanted = normalize_address(spec)
    for token in _ADDRESS_LIKE_RE.findall(header_value or ""):
        if normalize_address(token) != wanted:
            return ""
    return spec


def field_values(
    view: MessageView, field: str, body: Callable[[], str]
) -> list[str]:
    """Les valeurs d'un champ ; `body` n'est appelé que pour « body »."""
    if field == "from":
        return addr_specs(view.frm)
    if field == "to_cc":
        return addr_specs(view.to) + addr_specs(view.cc)
    if field == "subject":
        return [view.subject]
    if field == "body":
        return [body()]
    raise RuleError(f"{t('mail_rules_err_field')} {field!r}")


@functools.lru_cache(maxsize=256)
def _compiled(pattern: str) -> re.Pattern:
    """Compile une expression régulière déjà admise par `validate`.

    Le contrôle est refait ici : un fichier de règles édité à la main n'est
    pas passé par l'éditeur, et un motif à quantificateurs imbriqués
    bloquerait la passe. Un motif refusé lève `RuleError`.
    """
    detail = regex_fault(pattern)
    if detail is not None:
        raise RuleError(f"{t('mail_rules_err_regex')} {detail}")
    return re.compile(pattern)


def _squash(text: str) -> str:
    return " ".join(fold(text).split())


def _match_one(cond: Condition, value: str) -> bool:
    if cond.op == "glob":
        return fnmatch.fnmatchcase(
            normalize_address(value), normalize_pattern(cond.value)
        )
    if cond.op != "contains":
        raise RuleError(f"{t('mail_rules_err_op')} {cond.op!r}")
    mode = cond.mode
    if mode == "substring_ci":
        return fold(cond.value) in fold(value)
    if mode == "case_sensitive":
        return cond.value in value
    if mode == "exact":
        return _squash(value) == _squash(cond.value)
    if mode == "word":
        motif = r"(?<!\w)" + re.escape(fold(cond.value)) + r"(?!\w)"
        return re.search(motif, fold(value)) is not None
    if mode == "regex":
        return _regex_search(cond.value, [value])
    raise RuleError(f"{t('mail_rules_err_mode')} {mode!r}")


def match_condition(cond: Condition, values: list[str]) -> bool:
    """Vrai si au moins une des `values` satisfait la condition.

    `glob` compare l'adresse normalisée au motif normalisé, toujours sans
    casse, et ignore `mode`. `contains` suit `mode` : sous-chaîne sans casse
    ni accents (défaut), sensible à la casse, égalité aux blancs près, mot
    entier, ou expression régulière sans drapeau (« (?i) » s'écrit dans le
    motif) sur les `REGEX_TEXT_MAX` premiers caractères.
    """
    if cond.op == "contains" and cond.mode == "regex":
        return _regex_search(cond.value, values)
    return any(_match_one(cond, value) for value in values)


def _regex_search(pattern: str, values: list[str]) -> bool:
    """`re.search` de `pattern` sur les valeurs, sous un seul budget.

    Le motif est d'abord contrôlé (`_compiled`), puis cherché hors du
    processus (`regex_worker.search_any`) : un dépassement lève
    `RegexTimeout`, jamais un faux.
    """
    _compiled(pattern)
    return search_any(pattern, [value[:REGEX_TEXT_MAX] for value in values])


class _BodyOnce:
    """Chargeur de corps appelé au plus une fois, échec compris.

    Un chargeur qui lève ne sera pas rappelé : un second FETCH ne rendrait
    pas un corps que le premier n'a pas obtenu, et coûterait un aller-retour
    au serveur par condition.
    """

    def __init__(self, loader: Callable[[], str] | None) -> None:
        self._loader = loader
        self._done = False
        self._text = ""
        self._error: BodyUnavailable | None = None

    def __call__(self) -> str:
        if not self._done:
            self._done = True
            self._load()
        if self._error is not None:
            raise self._error
        return self._text

    def _load(self) -> None:
        if self._loader is None:
            self._error = BodyUnavailable()
            return
        try:
            text = self._loader()
        except BodyUnavailable as exc:
            self._error = exc
        except Exception as exc:
            # Large : quelle que soit la panne du chargeur, le corps reste
            # inconnu, et ce n'est jamais un corps vide.
            error = BodyUnavailable(str(exc), online=True)
            error.__cause__ = exc
            self._error = error
        else:
            self._text = (text or "")[:BODY_TEXT_MAX]


def _evaluate(node, view: MessageView, body: _BodyOnce) -> bool:
    if isinstance(node, Condition):
        return match_condition(node, field_values(view, node.field, body))
    if not isinstance(node, Group):
        raise RuleError(f"{t('mail_rules_err_field')} {type(node).__name__}")
    if node.op == "all":
        return all(_evaluate(child, view, body) for child in node.children)
    if node.op == "any":
        return any(_evaluate(child, view, body) for child in node.children)
    if node.op == "not":
        if len(node.children) != 1:
            raise RuleError(t("mail_rules_err_not_one_child"))
        return not _evaluate(node.children[0], view, body)
    raise RuleError(f"{t('mail_rules_err_op')} {node.op!r}")


def evaluate(
    node, view: MessageView, body_loader: Callable[[], str] | None
) -> bool:
    """Évalue l'arbre de gauche à droite, avec court-circuit.

    Un `all` sans enfant est vrai (« tous les messages »), un `any` sans
    enfant est faux, un `not` nie son unique enfant. `body_loader` n'est
    appelé qu'à la PREMIÈRE condition `body` effectivement atteinte, puis
    son résultat (ou son échec) est réutilisé ; le texte est tronqué à
    `BODY_TEXT_MAX`. Une condition `body` atteinte sans corps connu lève
    `BodyUnavailable`.
    """
    return _evaluate(node, view, _BodyOnce(body_loader))
