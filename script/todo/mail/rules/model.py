#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le modèle d'une règle : filtre, action, limites, et sa forme JSON.

Une règle se lit d'un fichier que l'utilisateur peut éditer à la main, et
qu'une version plus récente du client peut avoir écrit. La lecture est donc
stricte sur la STRUCTURE (un type inattendu lève `RuleError`, jamais une
valeur devinée) et prêteuse sur le reste : une clé inconnue de règle est
gardée dans `Rule.extra`, une clé inconnue d'action dans `Action.options`,
et les deux se réécrivent telles quelles. Une version de fichier plus
récente que `SCHEMA_VERSION` est refusée sans rien écrire.

La validation SÉMANTIQUE (`validate`) est séparée de la lecture : un
fichier dont une règle est fautive reste lisible, donc réparable depuis
l'écran des règles. Le filtre revérifie les expressions régulières au
moment de les compiler (voir `regex_fault`).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import types
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from script.todo.mail.smtp_send import SmtpError, smtp_address
from script.todo.todo_i18n import t

SCHEMA_VERSION = 1
FIELDS = ("from", "to_cc", "subject", "body")
ADDRESS_FIELDS = ("from", "to_cc")
OPS = ("glob", "contains")
MODES = ("substring_ci", "case_sensitive", "exact", "word", "regex")
GROUP_OPS = ("all", "any", "not")
ACTION_KINDS = ("reply", "forward", "stats")
# Les types que le moteur exécute ; un type hors de cette liste se charge
# et s'affiche, mais le moteur l'ignore.
EXECUTABLE_KINDS = ("reply", "stats", "forward")
FORMATS = ("markdown", "html", "text")
IMAGE_MIMES = ("image/png", "image/jpeg", "image/gif", "image/webp")
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGES_TOTAL_BYTES = 5 * 1024 * 1024
MAX_DEPTH = 8
MAX_NODES = 64
MAX_VALUE_LEN = 500
MAX_REGEX_LEN = 200
# Longueur maximale du texte soumis à une expression régulière.
REGEX_TEXT_MAX = 10_000
OUTCOMES = (
    "pending",
    "sent",
    "queued",
    "held",
    "skipped",
    "failed",
    "expired",
)
THROTTLE_MINUTES_MAX = 525_600
MAX_AGE_HOURS_MAX = 720
HOLD_FIRST_MAX = 10
# Limite par défaut de chaque type d'action : une réponse personnelle ne
# repart pas avant une semaine, un rapport avant un jour, et une
# redirection n'est pas limitée.
KIND_DEFAULTS = {
    "reply": {"throttle_enabled": True, "throttle_minutes": 10080},
    "stats": {"throttle_enabled": True, "throttle_minutes": 1440},
    "forward": {"throttle_enabled": False, "throttle_minutes": 10080},
}
# Modes d'une redirection : transfert dans le corps, transfert en pièce
# jointe, ou remise des octets d'origine à une enveloppe explicite.
FORWARD_MODES = ("inline", "attachment", "redirect")
FORWARD_MAX_TARGETS = 10
FORWARD_INTRO_MAX = 2000
# Taille maximale, en octets, d'un message transféré ou redirigé.
FORWARD_MAX_BYTES = 25 * 1024 * 1024
# Clés propres à une action `forward` dans `Action.options` ; une action
# d'un autre type les perd à l'enregistrement (`clean_action`).
FORWARD_OPTION_KEYS = ("targets", "mode", "skip_lists")

# Variables du gabarit d'une réponse à statistiques. Un BLOC est un
# paragraphe entier (titre, tableau, phrases) ; un SCALAIRE est une valeur
# courte, la seule forme admise dans le sujet.
STATS_BLOCK_VARIABLES = ("rapport", "rapport_jours", "rapport_semaines")
STATS_SCALAR_VARIABLES = (
    "recus_total",
    "lus_total",
    "repondus_total",
    "delai_moyen",
    "delai_moyen_boite",
    "demandeur_recus",
    "demandeur_repondus",
    "jours",
    "semaines",
    "fenetre_jours",
    "periode_debut",
    "periode_fin",
    "date_rapport",
)
STATS_VARIABLES = STATS_BLOCK_VARIABLES + STATS_SCALAR_VARIABLES
# « {{nom}} » ; le nom est comparé sans ses blancs de bord, casse comprise.
# Un « {{ » sans « }} » n'est pas une variable et reste du texte.
TEMPLATE_VAR_RE = re.compile(r"\{\{([^{}]*)\}\}")
# Une variable de bloc à l'intérieur d'une balise HTML, attribut compris :
# un tableau n'a pas de sens dans `title="…"`.
BLOCK_IN_TAG_RE = re.compile(
    r"<[^>]*\{\{\s*(?:rapport|rapport_jours|rapport_semaines)\s*\}\}"
)

# Quantificateurs qui répètent sans borne ou par intervalle ; « ? » n'en
# est pas un ici : il ne répète pas.
_QUANTIFIERS = frozenset("+*{")

# Clés de règle et d'action que le modèle connaît ; le reste est conservé.
_RULE_KEYS = frozenset(
    {
        "id",
        "name",
        "enabled",
        "order",
        "stop_after",
        "filter",
        "action",
        "throttle_enabled",
        "throttle_minutes",
        "max_age_hours",
        "hold_first",
        "armed",
    }
)
_ACTION_KEYS = frozenset(
    {"kind", "format", "subject", "body", "images", "options"}
)


class RuleError(Exception):
    """Règle, fichier ou image refusés ; le message est déjà traduit."""


class RulesBusy(RuleError):
    """Le verrou des règles du compte n'a pas été obtenu à temps."""


class TemplateError(RuleError):
    """Une faute de gabarit (variable inconnue, bloc mal placé), distincte
    d'une faute d'image : le moteur la journalise `build_error`."""


@dataclass
class Condition:
    field: str
    value: str
    op: str = "contains"
    mode: str = "substring_ci"


@dataclass
class Group:
    op: str = "all"
    # list[Condition | Group]
    children: list = field(default_factory=list)


@dataclass
class MediaRef:
    """Une image de la réponse, copiée dans le dossier des médias.

    `file` est un nom de base sans séparateur ; `sha256` l'empreinte
    hexadécimale du contenu, revérifiée à chaque lecture ; `mime` l'un de
    `IMAGE_MIMES`.
    """

    file: str
    sha256: str
    mime: str


@dataclass
class Action:
    kind: str = "reply"
    format: str = "markdown"
    # Gabarit du sujet ; « {subject} » y désigne le sujet reçu, et une
    # règle `stats` y admet aussi les variables scalaires « {{nom}} ».
    subject: str = ""
    body: str = ""
    # list[MediaRef]
    images: list = field(default_factory=list)
    # Clés propres aux autres types d'action, conservées telles quelles.
    options: dict = field(default_factory=dict)


@dataclass
class Armed:
    """Point d'armement d'une règle dans la boîte de réception.

    La règle n'agit que sur un message de même `uidvalidity`, d'UID au
    moins `uidnext`, et reçu après `at` (époque) : rien de ce qui précède
    son activation.
    """

    uidvalidity: int
    uidnext: int
    at: int


@dataclass
class Rule:
    id: str
    name: str
    enabled: bool = True
    order: int = 0
    stop_after: bool = False
    filter: Group = field(default_factory=Group)
    action: Action = field(default_factory=Action)
    throttle_enabled: bool = True
    throttle_minutes: int = 10080
    max_age_hours: int = 48
    hold_first: int = 1
    armed: Armed | None = None
    # Clés inconnues du fichier, réécrites telles quelles.
    extra: dict = field(default_factory=dict)

    def fingerprint(self) -> str:
        """Empreinte de ce que la règle teste et de ce qu'elle envoie.

        Entrent le filtre, le type, le format, le sujet, le corps, les
        images (avec leur `sha256` : une image remplacée sous le même nom
        change l'empreinte) et les options. N'entrent ni le nom, ni
        l'activation, ni l'ordre, ni les limites, ni l'armement : ils ne
        changent pas le message qui part, donc ne remettent pas à zéro le
        compteur des envois retenus.
        """
        canon = json.dumps(
            {
                "filter": node_to_dict(self.filter),
                "action": _action_core(self.action),
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]

    def tests_body(self) -> bool:
        """Vrai si une condition du filtre porte sur le corps du message.

        Le moteur s'en sert pour savoir s'il peut avoir à télécharger un
        corps ; le filtre, lui, ne le télécharge qu'à la première condition
        `body` effectivement évaluée.
        """
        return any(
            isinstance(node, Condition) and node.field == "body"
            for node in _walk(self.filter)
        )

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "order": self.order,
            "stop_after": self.stop_after,
            "filter": node_to_dict(self.filter),
            "action": _action_to_dict(self.action),
            "throttle_enabled": self.throttle_enabled,
            "throttle_minutes": self.throttle_minutes,
            "max_age_hours": self.max_age_hours,
            "hold_first": self.hold_first,
            "armed": _armed_to_dict(self.armed),
        }
        for key, value in self.extra.items():
            data.setdefault(key, value)
        return data

    @classmethod
    def from_dict(cls, d: dict) -> Rule:
        """Relit une règle ; un type inattendu lève `RuleError`.

        Un `id` absent est refusé plutôt que régénéré : le journal des
        envois est indexé par `id`, et un identifiant neuf à chaque lecture
        ferait répondre deux fois au même message.
        """
        if not isinstance(d, dict):
            raise _bad_json(type(d).__name__)
        rule_id = _typed(d, "id", str, None)
        if not rule_id or not rule_id.strip():
            raise _bad_json("id")
        root = d.get("filter")
        tree = Group() if root is None else node_from_dict(root)
        if not isinstance(tree, Group):
            raise _bad_json("filter")
        return cls(
            id=rule_id,
            name=_typed(d, "name", str, ""),
            enabled=_typed(d, "enabled", bool, True),
            order=_typed(d, "order", int, 0),
            stop_after=_typed(d, "stop_after", bool, False),
            filter=tree,
            action=_action_from_dict(d.get("action")),
            throttle_enabled=_typed(d, "throttle_enabled", bool, True),
            throttle_minutes=_typed(d, "throttle_minutes", int, 10080),
            max_age_hours=_typed(d, "max_age_hours", int, 48),
            hold_first=_typed(d, "hold_first", int, 1),
            armed=_armed_from_dict(d.get("armed")),
            extra={k: v for k, v in d.items() if k not in _RULE_KEYS},
        )


@dataclass(frozen=True)
class MessageView:
    """Ce que le filtre et les garde-fous voient d'un message.

    `internaldate` est la date de réception du serveur (0 = inconnue).
    `extra` porte les en-têtes supplémentaires, clés en minuscules,
    plusieurs occurrences jointes par « \\n » dans l'ordre du message.
    `size` est la taille annoncée par le serveur (RFC822.SIZE), en octets ;
    0 si elle est inconnue.
    """

    uid: int
    uidvalidity: int
    internaldate: int
    msgid: str
    frm: str
    to: str
    cc: str
    subject: str
    in_reply_to: str = ""
    references: str = ""
    extra: Mapping[str, str] = field(default_factory=dict)
    size: int = 0


def message_view(header, uidvalidity: int) -> MessageView:
    """Vue d'un en-tête de synchronisation OU d'une ligne du cache.

    Lecture par `getattr` : une ligne du cache n'a ni Cc ni en-têtes
    supplémentaires, et porte sa date de réception sous `received_at` et
    non `internaldate`. Les champs absents prennent une chaîne vide, un
    dictionnaire vide ou 0 ; une taille illisible vaut 0 (inconnue).
    """
    extra = getattr(header, "extra", None) or {}
    internaldate = getattr(header, "internaldate", 0) or getattr(
        header, "received_at", 0
    )
    return MessageView(
        uid=int(header.uid),
        uidvalidity=int(uidvalidity),
        internaldate=int(internaldate or 0),
        msgid=getattr(header, "msgid", "") or "",
        frm=getattr(header, "frm", "") or "",
        to=getattr(header, "to", "") or "",
        cc=getattr(header, "cc", "") or "",
        subject=getattr(header, "subject", "") or "",
        in_reply_to=getattr(header, "in_reply_to", "") or "",
        references=getattr(header, "references", "") or "",
        extra=types.MappingProxyType(
            {str(k).lower(): str(v) for k, v in extra.items()}
        ),
        size=_size_of(header),
    )


def _size_of(header) -> int:
    """La taille portée par `header`, entier positif, ou 0."""
    try:
        size = int(getattr(header, "size", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return max(size, 0)


def new_rule(kind: str = "reply", name: str = "") -> Rule:
    """Règle neuve, désarmée, d'identifiant neuf, aux limites de son type."""
    defaults = KIND_DEFAULTS.get(kind)
    if defaults is None:
        raise _fault(t("mail_rules_err_kind"), repr(kind))
    action = Action(kind=kind)
    if kind == "stats":
        action.body = t("mail_stats_default_body")
        action.format = "markdown"
    elif kind == "forward":
        action.format = "text"
        action.options = forward_defaults()
    return Rule(
        id=uuid.uuid4().hex[:12],
        name=name,
        action=action,
        throttle_enabled=defaults["throttle_enabled"],
        throttle_minutes=defaults["throttle_minutes"],
    )


# -- Arbre du filtre ---------------------------------------------------


def node_to_dict(node) -> dict:
    if isinstance(node, Group):
        return {
            "type": "group",
            "op": node.op,
            "children": [node_to_dict(child) for child in node.children],
        }
    return {
        "type": "condition",
        "field": node.field,
        "op": node.op,
        "value": node.value,
        "mode": node.mode,
    }


def node_from_dict(d: dict, depth: int = 0):
    """Relit un nœud ; la profondeur est bornée dès la lecture.

    La borne protège la récursion elle-même : un fichier édité à la main
    qui imbrique mille groupes est refusé avant de saturer la pile.
    """
    if depth > MAX_DEPTH:
        raise _fault(t("mail_rules_err_too_deep"))
    if not isinstance(d, dict):
        raise _bad_json(type(d).__name__)
    kind = d.get("type")
    if kind == "group":
        children = d.get("children", [])
        if not isinstance(children, list):
            raise _bad_json("children")
        return Group(
            op=_typed(d, "op", str, "all"),
            children=[node_from_dict(c, depth + 1) for c in children],
        )
    if kind == "condition":
        return Condition(
            field=_typed(d, "field", str, None),
            value=_typed(d, "value", str, None),
            op=_typed(d, "op", str, "contains"),
            mode=_typed(d, "mode", str, "substring_ci"),
        )
    raise _bad_json(repr(kind))


def regex_fault(pattern: str) -> str | None:
    """Ce qui interdit `pattern` comme expression régulière, ou None.

    Rend un détail lisible : l'erreur de compilation, la longueur
    dépassée, ou le fragment qui imbrique deux quantificateurs.
    """
    if len(pattern) > MAX_REGEX_LEN:
        return f"> {MAX_REGEX_LEN}"
    try:
        re.compile(pattern)
    except re.error as exc:
        return str(exc)
    nested = nested_quantifier(pattern)
    if nested is not None:
        return repr(nested)
    return None


def nested_quantifier(pattern: str) -> str | None:
    """Le premier groupe quantifié qui contient un quantificateur, ou None.

    « (a+)+ », « (a*)* », « ((a+))+ », « ((a)+)+ », « (?:(?:a+))* » sont
    rendus : `re` n'a pas de délai, et le retour arrière catastrophique
    d'un tel motif sur un sujet écrit par un tiers bloquerait une passe qui
    tient le verrou du compte. Un groupe hérite du quantificateur de
    n'importe quel sous-groupe, à toute profondeur. Une alternance simple
    comme « (x|y)+ » passe. Les caractères échappés (« \\( », « \\+ ») et
    le contenu d'une classe « […] » ne comptent ni comme parenthèse ni comme
    quantificateur ; les blancs entre « ) » et le quantificateur sont
    sautés (mode verbeux « (?x) »).
    """
    stack: list[list] = []  # [début du groupe, contient un quantificateur]
    index, size = 0, len(pattern)
    while index < size:
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            index = _class_end(pattern, index)
            continue
        if char == "(":
            stack.append([index, False])
        elif char == ")" and stack:
            start, inner = stack.pop()
            after = index + 1
            while after < size and pattern[after].isspace():
                after += 1
            repeated = after < size and pattern[after] in _QUANTIFIERS
            if inner and repeated:
                return pattern[start : after + 1]
            if stack and (inner or repeated):
                stack[-1][1] = True
        elif (char in _QUANTIFIERS or char == "}") and stack:
            stack[-1][1] = True
        index += 1
    return None


def _class_end(pattern: str, index: int) -> int:
    """L'indice qui suit la classe « […] » ouverte à `index`.

    Un « ] » en tête de classe (après un « ^ » éventuel) est littéral.
    """
    index += 1
    if index < len(pattern) and pattern[index] == "^":
        index += 1
    if index < len(pattern) and pattern[index] == "]":
        index += 1
    while index < len(pattern) and pattern[index] != "]":
        if pattern[index] == "\\":
            index += 1
        index += 1
    return index + 1


def validate_node(node, depth: int = 0) -> None:
    """Refuse la première faute d'une condition ou d'un sous-arbre.

    Sert à l'éditeur de condition, qui valide un nœud seul avant de le
    rendre, et à `validate` pour le filtre entier.
    """
    if _validate_node(node, depth) > MAX_NODES:
        raise _fault(t("mail_rules_err_too_deep"))


def _validate_node(node, depth: int) -> int:
    """Valide `node` et rend le nombre de nœuds de son sous-arbre."""
    if depth > MAX_DEPTH:
        raise _fault(t("mail_rules_err_too_deep"))
    if isinstance(node, Group):
        if node.op not in GROUP_OPS:
            raise _fault(t("mail_rules_err_op"), repr(node.op))
        if node.op == "not" and len(node.children) != 1:
            raise _fault(t("mail_rules_err_not_one_child"))
        count = 1
        for child in node.children:
            count += _validate_node(child, depth + 1)
            if count > MAX_NODES:
                raise _fault(t("mail_rules_err_too_deep"))
        return count
    if not isinstance(node, Condition):
        raise _fault(t("mail_rules_err_field"), type(node).__name__)
    _validate_condition(node)
    return 1


def _validate_condition(cond: Condition) -> None:
    if cond.field not in FIELDS:
        raise _fault(t("mail_rules_err_field"), repr(cond.field))
    if cond.op not in OPS:
        raise _fault(t("mail_rules_err_op"), repr(cond.op))
    if cond.mode not in MODES:
        raise _fault(t("mail_rules_err_mode"), repr(cond.mode))
    if cond.op == "glob" and cond.field not in ADDRESS_FIELDS:
        raise _fault(t("mail_rules_err_glob_field"))
    if not isinstance(cond.value, str) or not cond.value.strip():
        raise _fault(t("mail_rules_err_empty_value"))
    if len(cond.value) > MAX_VALUE_LEN:
        raise _fault(t("mail_rules_err_value_too_long"))
    # Le mode est ignoré par un motif glob : seule une condition
    # « contient » compile une expression régulière.
    if cond.op == "contains" and cond.mode == "regex":
        detail = regex_fault(cond.value)
        if detail is not None:
            raise _fault(t("mail_rules_err_regex"), detail)


def validate(rule: Rule) -> None:
    """Refuse la première faute de la règle, par `RuleError` traduite.

    La limite en minutes est vérifiée même case décochée : la valeur est
    gardée pour le jour où la case est recochée. La retenue des premiers
    envois ne se désactive pas : `hold_first` vaut au moins 1.
    """
    if not isinstance(rule.filter, Group):
        raise _fault(t("mail_rules_err_field"), "filter")
    validate_node(rule.filter)
    if not _int_between(rule.throttle_minutes, 1, THROTTLE_MINUTES_MAX):
        raise _fault(t("mail_rules_err_minutes"))
    if not _int_between(rule.max_age_hours, 1, MAX_AGE_HOURS_MAX):
        raise _fault(t("mail_rules_err_max_age"))
    if not _int_between(rule.hold_first, 1, HOLD_FIRST_MAX):
        raise _fault(t("mail_rules_err_hold_first"))
    action = rule.action
    if action.kind not in ACTION_KINDS:
        raise _fault(t("mail_rules_err_kind"), repr(action.kind))
    if action.format not in FORMATS:
        raise _fault(t("mail_rules_err_format"), repr(action.format))
    for ref in action.images:
        if ref.mime not in IMAGE_MIMES:
            raise _fault(t("mail_rules_err_image_type"), str(ref.mime))
        if not is_safe_media_name(ref.file):
            raise _fault(t("mail_rules_err_image_missing"), repr(ref.file))
    if action.kind == "forward":
        _validate_forward(action)
    fault = template_fault(action)
    if fault is not None:
        raise TemplateError(fault)


# -- Action « forward » ------------------------------------------------


@dataclass(frozen=True)
class ForwardOptions:
    """Les options d'une action `forward`, relues et contrôlées.

    `targets` : formes d'envoi (`smtp_send.smtp_address`), sans doublon,
    dans l'ordre du fichier. `mode` : l'un de `FORWARD_MODES`.
    `skip_lists` : vrai si les garde-fous « listes et robots » d'une
    réponse s'appliquent aussi à la redirection.
    """

    targets: tuple[str, ...]
    mode: str
    skip_lists: bool


def forward_defaults() -> dict:
    """Les options d'une action `forward` neuve : aucune destination,
    transfert dans le corps, listes et robots transférés."""
    return {"targets": [], "mode": "inline", "skip_lists": False}


def forward_options(action: Action) -> ForwardOptions:
    """Relit les options d'une action `forward`.

    Une clé absente prend la valeur de `forward_defaults()`. Lève
    `RuleError` (préfixée « Règle invalide : ») pour un type faux
    (`options.targets` qui n'est pas une liste de chaînes, `options.mode`
    qui n'est pas une chaîne, `options.skip_lists` qui n'est pas un
    booléen), un mode hors de `FORWARD_MODES`, ou une adresse que
    `smtp_address` refuse. Les destinations sont rendues en forme d'envoi
    et dédoublonnées sans égard à la casse ; leur nombre n'est PAS
    contrôlé ici (`validate` le fait).
    """
    options = action.options if isinstance(action.options, dict) else {}
    defaults = forward_defaults()
    targets = options.get("targets", defaults["targets"])
    if not isinstance(targets, list) or not all(
        isinstance(item, str) for item in targets
    ):
        raise _fault("options.targets")
    mode = options.get("mode", defaults["mode"])
    if not isinstance(mode, str):
        raise _fault("options.mode")
    skip_lists = options.get("skip_lists", defaults["skip_lists"])
    if not isinstance(skip_lists, bool):
        raise _fault("options.skip_lists")
    if mode not in FORWARD_MODES:
        raise _fault(t("mail_rules_err_fwd_mode"), repr(mode))
    forms: list[str] = []
    seen: set[str] = set()
    for target in targets:
        try:
            form = smtp_address(target)
        except SmtpError:
            raise _fault(
                t("mail_rules_err_fwd_address"), repr(target)
            ) from None
        if form.lower() not in seen:
            seen.add(form.lower())
            forms.append(form)
    return ForwardOptions(tuple(forms), mode, skip_lists)


def clean_action(action: Action) -> Action:
    """Une copie de `action` débarrassée de ce que son type ignore.

    Une action `forward` perd ses images, son sujet et prend le format
    `text` (l'intro est du texte brut) ; une action d'un autre type perd
    les clés de `FORWARD_OPTION_KEYS` de ses options. Les autres options
    sont gardées telles quelles.
    """
    options = dict(action.options)
    if action.kind == "forward":
        return dataclasses.replace(
            action, format="text", subject="", images=[], options=options
        )
    for key in FORWARD_OPTION_KEYS:
        options.pop(key, None)
    return dataclasses.replace(
        action, images=list(action.images), options=options
    )


def _validate_forward(action: Action) -> None:
    """Refuse la première faute d'une action `forward` : options, aucune
    destination, trop de destinations, une image, une intro trop longue."""
    options = forward_options(action)
    if not options.targets:
        raise _fault(t("mail_rules_err_fwd_no_target"))
    if len(options.targets) > FORWARD_MAX_TARGETS:
        raise _fault(
            t("mail_rules_err_fwd_too_many"), str(FORWARD_MAX_TARGETS)
        )
    if action.images:
        raise _fault(t("mail_rules_err_fwd_images"))
    if len(action.body or "") > FORWARD_INTRO_MAX:
        raise _fault(
            t("mail_rules_err_fwd_intro_too_long"), str(FORWARD_INTRO_MAX)
        )


def template_names(text: str) -> list[str]:
    """Les noms cités par « {{…}} », sans leurs blancs de bord, sans
    doublon, dans l'ordre du texte."""
    names: list[str] = []
    for match in TEMPLATE_VAR_RE.finditer(text or ""):
        name = match.group(1).strip()
        if name not in names:
            names.append(name)
    return names


def template_fault(action: Action) -> str | None:
    """Le texte d'erreur traduit (préfixé « Règle invalide : ») d'un
    gabarit fautif, ou None.

    Règle `stats` : le corps d'abord (nom inconnu, bloc dans une balise
    d'un corps HTML), puis le sujet (bloc, puis nom inconnu). Règle
    `reply` : seul un nom de variable de rapport est refusé, tout autre
    « {{…}} » y est du texte. Autre type : None.
    """
    if action.kind == "stats":
        for name in template_names(action.body):
            if name not in STATS_VARIABLES:
                return _fault_text(
                    t("mail_rules_err_template_var"), "{{" + name + "}}"
                )
        if action.format == "html":
            match = BLOCK_IN_TAG_RE.search(action.body or "")
            if match is not None:
                return _fault_text(
                    t("mail_rules_err_template_block_tag"),
                    "{{" + _block_name(match.group(0)) + "}}",
                )
        for name in template_names(action.subject):
            if name in STATS_BLOCK_VARIABLES:
                return _fault_text(
                    t("mail_rules_err_template_block_subject"),
                    "{{" + name + "}}",
                )
            if name not in STATS_VARIABLES:
                return _fault_text(
                    t("mail_rules_err_template_var"), "{{" + name + "}}"
                )
        return None
    if action.kind == "reply":
        for text in (action.body, action.subject):
            for name in template_names(text):
                if name in STATS_VARIABLES:
                    return _fault_text(
                        t("mail_rules_err_template_reply_var"),
                        "{{" + name + "}}",
                    )
    return None


def _block_name(fragment: str) -> str:
    """Le nom de la variable de bloc qui termine `fragment`."""
    return template_names(fragment)[-1]


def is_safe_media_name(name) -> bool:
    """Vrai pour un nom de base qui reste DANS le dossier des médias.

    Refuse le vide, tout séparateur, « .. » et un nom qui commence par un
    point : joint au dossier des médias, un tel nom en sortirait ou
    viserait un fichier caché.
    """
    return (
        isinstance(name, str)
        and bool(name)
        and "/" not in name
        and "\\" not in name
        and "\0" not in name
        and ".." not in name
        and not name.startswith(".")
    )


# -- Fichier entier ----------------------------------------------------


def rules_to_dict(account_name: str, rules: list[Rule]) -> dict:
    return {
        "version": SCHEMA_VERSION,
        "account": account_name,
        "rules": [rule.to_dict() for rule in rules],
    }


def rules_from_dict(data: dict) -> list[Rule]:
    """Relit le fichier entier ; une version future lève `RuleError`.

    Une version absente vaut 1. Deux règles de même `id` sont refusées :
    elles partageraient leur journal, donc leur limite et leur retenue.
    """
    if not isinstance(data, dict):
        raise _bad_json(type(data).__name__)
    version = data.get("version", SCHEMA_VERSION)
    if not isinstance(version, int) or isinstance(version, bool):
        raise _bad_json("version")
    if version > SCHEMA_VERSION:
        raise RuleError(f"{t('mail_rules_err_future_version')} {version}")
    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        raise _bad_json("rules")
    rules = [Rule.from_dict(item) for item in raw_rules]
    seen = set()
    for rule in rules:
        if rule.id in seen:
            raise RuleError(f"{t('mail_rules_err_invalid')} {rule.id!r}")
        seen.add(rule.id)
    return rules


# -- Aides privées -----------------------------------------------------


def _fault_text(message: str, detail: str = "") -> str:
    """Le texte préfixé de « Règle invalide : », détail facultatif."""
    text = f"{t('mail_rules_err_invalid')} {message}"
    return f"{text} {detail}" if detail else text


def _fault(message: str, detail: str = "") -> RuleError:
    """`RuleError` préfixée de « Règle invalide : », détail facultatif."""
    return RuleError(_fault_text(message, detail))


def _bad_json(detail: str) -> RuleError:
    return RuleError(f"{t('mail_rules_err_bad_json')} {detail}")


def _typed(d: dict, key: str, kind: type, default):
    """`d[key]` s'il est du type `kind`, `default` s'il manque.

    Un `default` None rend la clé obligatoire. Un booléen n'est pas
    accepté comme entier : `True` lu comme 1 minute passerait la
    validation sans que personne ne l'ait voulu.
    """
    if key not in d:
        if default is None:
            raise _bad_json(key)
        return default
    value = d[key]
    if kind is int and isinstance(value, bool):
        raise _bad_json(key)
    if not isinstance(value, kind):
        raise _bad_json(key)
    return value


def _int_between(value, low: int, high: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and low <= value <= high
    )


def _walk(node):
    yield node
    if isinstance(node, Group):
        for child in node.children:
            yield from _walk(child)


def _image_to_dict(ref: MediaRef) -> dict:
    return {"file": ref.file, "sha256": ref.sha256, "mime": ref.mime}


def _action_core(action: Action) -> dict:
    return {
        "kind": action.kind,
        "format": action.format,
        "subject": action.subject,
        "body": action.body,
        "images": [_image_to_dict(ref) for ref in action.images],
        "options": dict(action.options),
    }


def _action_to_dict(action: Action) -> dict:
    return _action_core(action)


def _action_from_dict(d) -> Action:
    if d is None:
        return Action()
    if not isinstance(d, dict):
        raise _bad_json("action")
    images = d.get("images", [])
    if not isinstance(images, list):
        raise _bad_json("images")
    options = d.get("options", {})
    if not isinstance(options, dict):
        raise _bad_json("options")
    options = dict(options)
    for key, value in d.items():
        if key not in _ACTION_KEYS:
            options.setdefault(key, value)
    return Action(
        kind=_typed(d, "kind", str, "reply"),
        format=_typed(d, "format", str, "markdown"),
        subject=_typed(d, "subject", str, ""),
        body=_typed(d, "body", str, ""),
        images=[_image_from_dict(item) for item in images],
        options=options,
    )


def _image_from_dict(d) -> MediaRef:
    if not isinstance(d, dict):
        raise _bad_json("images")
    return MediaRef(
        file=_typed(d, "file", str, None),
        sha256=_typed(d, "sha256", str, None),
        mime=_typed(d, "mime", str, None),
    )


def _armed_to_dict(armed: Armed | None):
    if armed is None:
        return None
    return {
        "uidvalidity": armed.uidvalidity,
        "uidnext": armed.uidnext,
        "at": armed.at,
    }


def _armed_from_dict(d) -> Armed | None:
    if d is None:
        return None
    if not isinstance(d, dict):
        raise _bad_json("armed")
    return Armed(
        uidvalidity=_typed(d, "uidvalidity", int, None),
        uidnext=_typed(d, "uidnext", int, None),
        at=_typed(d, "at", int, None),
    )
