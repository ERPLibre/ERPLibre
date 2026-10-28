#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le rapport de statistiques d'une réponse automatique : calcul et rendu.

Deux parties. La partie BOÎTE (`MailboxActivity`) décrit l'activité de la
boîte de réception : messages reçus, lus et répondus par jour clos et par
semaine ISO complète, et le délai moyen de réponse de la boîte. Elle ne
dépend pas du demandeur, se calcule une fois et peut être relue d'un
instantané (`mailbox_to_dict` / `mailbox_from_dict`). La partie DEMANDEUR
(`RequesterActivity`) ne porte que sur les messages dont le From est
l'adresse du demandeur.

Le rapport ne contient que des agrégats : aucune adresse, aucun sujet,
aucun texte d'un message reçu n'y entre. Aujourd'hui et la semaine en cours
n'y figurent jamais : une tranche ouverte dirait, message par message, ce
qui vient d'être lu.

Les jours et les semaines sont ceux du FUSEAU DU PROCESSUS (`time.localtime`,
variable `TZ`) ; un jour commence à minuit local, et dure 23 ou 25 heures
au changement d'heure. Le rangement se fait en Python et non en SQL : le
fuseau local et les semaines ISO n'y sont pas portables d'une version de
SQLite à l'autre.

Le gabarit du corps cite les variables par « {{nom}} ». Le rendu les
remplace d'abord par des jetons alphanumériques qu'aucun format ne
transforme, rend le corps par `markup.render_reply` (images et formats
inchangés), puis met la valeur TEXTE de chaque variable dans la version
texte et sa valeur HTML dans la version HTML.
"""

from __future__ import annotations

import bisect
import dataclasses
import datetime
import html
import re
import secrets
import time
from dataclasses import dataclass

from script.todo.mail.rules import markup
from script.todo.mail.rules.filter import normalize_address
from script.todo.mail.rules.model import (
    STATS_BLOCK_VARIABLES,
    TEMPLATE_VAR_RE,
    Action,
    TemplateError,
    template_fault,
)
from script.todo.mail.smtp_send import auto_reply_subject
from script.todo.todo_i18n import TRANSLATIONS, t

# Valeur affichée quand une grandeur est inconnue.
NO_VALUE = "—"
# En dessous de ce nombre de délais connus dans la fenêtre, le délai moyen
# de la boîte n'est pas donné : sur trois réponses, la moyenne dirait
# quand ces trois personnes ont reçu leur réponse.
REPORT_MIN_DELAYS = 5
REPORT_KEYS: tuple[str, ...] = (
    "mail_stats_report_days_title",
    "mail_stats_report_weeks_title",
    "mail_stats_report_col_day",
    "mail_stats_report_col_week",
    "mail_stats_report_col_week_start",
    "mail_stats_report_col_received",
    "mail_stats_report_col_seen",
    "mail_stats_report_col_answered",
    "mail_stats_report_total",
    "mail_stats_report_mailbox_delay",
    "mail_stats_report_mailbox_none",
    "mail_stats_report_mailbox_few",
    "mail_stats_report_requester_delay",
    "mail_stats_report_based_on",
    "mail_stats_report_requester_none",
    "mail_stats_report_generated",
    "mail_stats_report_local_time",
    "mail_stats_report_unit_day",
)
_DAY_S = 86400
_HTML_TABLE_OPEN = (
    '<table border="1" cellpadding="4" cellspacing="0"'
    ' style="border-collapse:collapse">'
)
_NUM_TD = '<td style="text-align:right">'
# Ouverture d'un paragraphe : « <p> » ou « <p attr…> », pas « <pre> ».
_P_OPEN_RE = re.compile(r"<p(?=[\s>])", re.IGNORECASE)
_P_CLOSE_RE = re.compile(r"</p\s*>", re.IGNORECASE)
_EMPTY_P_RE = re.compile(r"<p>\s*</p>", re.IGNORECASE)


@dataclass(frozen=True)
class Bucket:
    """Une tranche d'un tableau : un jour ou une semaine ISO.

    `label` vaut « AAAA-MM-JJ » ou « AAAA-Wss » ; `start` est l'époque du
    début local de la tranche ; `first_day` la date ISO locale de son
    premier jour (le lundi pour une semaine).
    """

    label: str
    start: int
    first_day: str
    received: int
    seen: int
    answered: int


@dataclass(frozen=True)
class MailboxActivity:
    """La partie boîte du rapport.

    `days` va du plus ancien jour au jour qui précède le calcul, `weeks`
    de la plus ancienne semaine à la dernière semaine complète. Les
    totaux portent sur les tranches par jour. `delay_mean` est la moyenne
    brute des délais des originaux reçus dans les `window_days` derniers
    jours clos (None si aucun), `delay_count` leur nombre. `period_start`
    est le début du premier jour, `period_end` le début d'aujourd'hui,
    borne exclue de toutes les tranches ; `generated_at` l'instant du
    calcul.
    """

    days: list
    weeks: list
    received_total: int
    seen_total: int
    answered_total: int
    delay_mean: int | None
    delay_count: int
    window_days: int
    period_start: int
    period_end: int
    generated_at: int


@dataclass(frozen=True)
class RequesterActivity:
    """La partie demandeur : ses messages reçus dans la fenêtre des
    délais, ceux qui sont répondus (délai connu ou non), et les délais
    connus."""

    received: int
    answered: int
    delays: list


@dataclass(frozen=True)
class ReportData:
    """Ce que rend un rapport. `requester` None : aperçu sans demandeur,
    sa ligne est omise. `lang` « » : langue de l'interface."""

    mailbox: MailboxActivity
    requester: RequesterActivity | None
    lang: str


# -- Calendrier local --------------------------------------------------


def _midnight(day: datetime.date) -> int:
    """L'époque du minuit local de `day` ; le drapeau d'heure d'été est
    laissé à `mktime` (-1), qui le déduit de la date."""
    return int(time.mktime((day.year, day.month, day.day, 0, 0, 0, 0, 0, -1)))


def _local_date(epoch: int) -> datetime.date:
    local = time.localtime(epoch)
    return datetime.date(local.tm_year, local.tm_mon, local.tm_mday)


def _today_start(now: int) -> int:
    """Le minuit local du jour de `now`."""
    return _midnight(_local_date(now))


def _current_monday(now: int) -> datetime.date:
    today = _local_date(now)
    return today - datetime.timedelta(days=today.weekday())


def day_starts(now: int, days: int) -> list[int]:
    """Les minuits locaux de `days` jours clos, du plus ancien au jour
    qui précède `now`."""
    today = _local_date(now)
    return [
        _midnight(today - datetime.timedelta(days=back))
        for back in range(days, 0, -1)
    ]


def week_starts(now: int, weeks: int) -> list[int]:
    """Les lundis 00:00 locaux de `weeks` semaines ISO complètes, la
    dernière étant celle qui précède la semaine courante ; 0 : []."""
    monday = _current_monday(now)
    return [
        _midnight(monday - datetime.timedelta(weeks=back))
        for back in range(max(0, weeks), 0, -1)
    ]


def _week_label(start: int) -> str:
    year, week, _weekday = _local_date(start).isocalendar()
    return f"{year}-W{week:02d}"


def _buckets(rows, starts: list[int], end: int, kind: str) -> list[Bucket]:
    """Range `rows` dans les tranches qui commencent à `starts` ; la
    dernière s'arrête à `end` (exclu). Une ligne hors de [starts[0], end)
    n'est comptée nulle part."""
    counts = [[0, 0, 0] for _start in starts]
    for row in rows:
        if not starts or row.received_at < starts[0] or row.received_at >= end:
            continue
        index = bisect.bisect_right(starts, row.received_at) - 1
        counts[index][0] += 1
        counts[index][1] += int(row.seen)
        counts[index][2] += int(row.answered)
    out = []
    for start, (received, seen, answered) in zip(starts, counts, strict=True):
        first_day = _local_date(start).isoformat()
        label = first_day if kind == "day" else _week_label(start)
        out.append(Bucket(label, start, first_day, received, seen, answered))
    return out


# -- Collecte ----------------------------------------------------------


def mean_delay(delays: list) -> int | None:
    """La moyenne arithmétique, en secondes entières par défaut ; [] :
    None."""
    if not delays:
        return None
    return sum(delays) // len(delays)


def round_delay(seconds: int) -> int:
    """Un délai arrondi au plus proche : à 5 min sous 1 h (au moins
    5 min), à 15 min sous 1 jour, à l'heure au-delà."""
    if seconds < 3600:
        return max(300, round(seconds / 300) * 300)
    if seconds < _DAY_S:
        return round(seconds / 900) * 900
    return round(seconds / 3600) * 3600


def collect_mailbox(store, settings, *, now: int) -> MailboxActivity:
    """La partie boîte du rapport, en une seule lecture du cache.

    Aucune colonne scellée n'est lue. Les délais sont ceux des originaux
    reçus depuis le début de la fenêtre des délais, qui en ont un.
    """
    now = int(now)
    days = day_starts(now, settings.days)
    weeks = week_starts(now, settings.weeks)
    window = day_starts(now, settings.delay_window_days)
    end = _today_start(now)
    since = min([days[0], window[0]] + weeks[:1])
    rows = store.stats_activity(since, end)
    day_buckets = _buckets(rows, days, end, "day")
    week_buckets = _buckets(
        rows, weeks, _midnight(_current_monday(now)), "week"
    )
    delays = [
        row.first_reply_at - row.received_at
        for row in rows
        if row.received_at >= window[0] and row.first_reply_at
    ]
    return MailboxActivity(
        days=day_buckets,
        weeks=week_buckets,
        received_total=sum(b.received for b in day_buckets),
        seen_total=sum(b.seen for b in day_buckets),
        answered_total=sum(b.answered for b in day_buckets),
        delay_mean=mean_delay(delays),
        delay_count=len(delays),
        window_days=settings.delay_window_days,
        period_start=days[0],
        period_end=end,
        generated_at=now,
    )


def requester_index(store, settings, *, now: int) -> dict[str, list]:
    """Les messages des `delay_window_days` derniers jours (jusqu'à
    `now` inclus), rangés par adresse normalisée de From ; un From
    ambigu n'est rangé nulle part."""
    now = int(now)
    rows = store.stats_activity(
        now - settings.delay_window_days * _DAY_S, now + 1, with_sender=True
    )
    index: dict[str, list] = {}
    for row in rows:
        if row.sender:
            index.setdefault(row.sender, []).append(row)
    return index


def collect_requester(
    store, settings, *, now: int, sender: str, index: dict | None = None
) -> RequesterActivity:
    """La partie demandeur pour `sender` ; `index` (de `requester_index`)
    évite de relire le cache pour chaque demandeur d'une même passe. Une
    adresse vide ne désigne personne : aucun message."""
    sender = normalize_address(sender or "")
    if not sender:
        return RequesterActivity(0, 0, [])
    if index is None:
        index = requester_index(store, settings, now=now)
    rows = index.get(sender, [])
    return RequesterActivity(
        received=len(rows),
        answered=sum(1 for row in rows if row.answered),
        delays=[
            row.first_reply_at - row.received_at
            for row in rows
            if row.first_reply_at
        ],
    )


def build_data(
    store,
    settings,
    *,
    now: int,
    sender: str | None,
    mailbox: MailboxActivity | None = None,
) -> ReportData:
    """Les données d'un rapport. `sender` None : sans demandeur ; « » :
    un demandeur dont le From est illisible, sans aucun message.
    `mailbox` fourni est pris tel quel, sinon calculé."""
    if mailbox is None:
        mailbox = collect_mailbox(store, settings, now=now)
    requester = None
    if sender is not None:
        requester = collect_requester(store, settings, now=now, sender=sender)
    return ReportData(mailbox, requester, settings.lang)


# -- Instantané --------------------------------------------------------


def snapshot_key(settings, now: int) -> dict:
    """Ce qui identifie un instantané : le jour local et les paramètres
    qui changent la partie boîte."""
    return {
        "day": _local_date(int(now)).isoformat(),
        "days": settings.days,
        "weeks": settings.weeks,
        "window_days": settings.delay_window_days,
    }


_BUCKET_TYPES = (str, int, str, int, int, int)
_MAILBOX_INTS = (
    "received_total",
    "seen_total",
    "answered_total",
    "delay_count",
    "window_days",
    "period_start",
    "period_end",
    "generated_at",
)


def mailbox_to_dict(mailbox: MailboxActivity, key: dict) -> dict:
    """La forme JSON d'une partie boîte : entiers, chaînes et None."""
    body = {
        name: getattr(mailbox, name)
        for name in _MAILBOX_INTS + ("delay_mean",)
    }
    body["days"] = [list(dataclasses.astuple(b)) for b in mailbox.days]
    body["weeks"] = [list(dataclasses.astuple(b)) for b in mailbox.weeks]
    return {"key": dict(key), "mailbox": body}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _bucket_list(raw) -> list | None:
    if not isinstance(raw, list):
        return None
    out = []
    for item in raw:
        if not isinstance(item, list) or len(item) != len(_BUCKET_TYPES):
            return None
        for value, kind in zip(item, _BUCKET_TYPES, strict=True):
            if kind is int and not _is_int(value):
                return None
            if kind is str and not isinstance(value, str):
                return None
        out.append(Bucket(*item))
    return out


def mailbox_from_dict(data, key: dict) -> MailboxActivity | None:
    """La partie boîte relue d'un instantané, ou None s'il n'est pas un
    dict, si sa clé diffère de `key`, ou si un champ manque ou n'a pas le
    bon type. Ne lève jamais."""
    if not isinstance(data, dict) or data.get("key") != key:
        return None
    body = data.get("mailbox")
    if not isinstance(body, dict):
        return None
    if not all(_is_int(body.get(name)) for name in _MAILBOX_INTS):
        return None
    if "delay_mean" not in body:
        return None
    mean = body["delay_mean"]
    if mean is not None and not _is_int(mean):
        return None
    days, weeks = (
        _bucket_list(body.get("days")),
        _bucket_list(body.get("weeks")),
    )
    if days is None or weeks is None:
        return None
    return MailboxActivity(
        days=days,
        weeks=weeks,
        delay_mean=mean,
        **{name: body[name] for name in _MAILBOX_INTS},
    )


# -- Libellés et valeurs -----------------------------------------------


def _label(key: str, lang: str) -> str:
    """Le libellé de `key` dans `lang`, ou dans la langue de l'interface
    si `lang` est vide."""
    if lang:
        return TRANSLATIONS[key][lang]
    return t(key)


def _with_n(key: str, lang: str, n: int) -> str:
    return _label(key, lang).replace("{n}", str(n))


def format_delay(seconds: int | None, lang: str = "") -> str:
    """Un délai lisible : « < 1 min », « 45 min », « 3 h », « 3 h 05 min »,
    « 2 j 4 h » ; None : `NO_VALUE`."""
    if seconds is None:
        return NO_VALUE
    seconds = int(seconds)
    if seconds < 60:
        return "< 1 min"
    if seconds < 3600:
        return f"{seconds // 60} min"
    if seconds < _DAY_S:
        hours, minutes = seconds // 3600, (seconds % 3600) // 60
        return f"{hours} h {minutes:02d} min" if minutes else f"{hours} h"
    days, hours = seconds // _DAY_S, (seconds % _DAY_S) // 3600
    unit = _label("mail_stats_report_unit_day", lang)
    return f"{days} {unit} {hours} h" if hours else f"{days} {unit}"


def _table_cells(buckets, kind: str, lang: str):
    """(en-têtes, lignes, ligne Total, nombre de colonnes de libellé)."""
    numbers = [
        _label("mail_stats_report_col_received", lang),
        _label("mail_stats_report_col_seen", lang),
        _label("mail_stats_report_col_answered", lang),
    ]
    totals = [
        str(sum(b.received for b in buckets)),
        str(sum(b.seen for b in buckets)),
        str(sum(b.answered for b in buckets)),
    ]
    total = _label("mail_stats_report_total", lang)
    if kind == "day":
        heads = [_label("mail_stats_report_col_day", lang)] + numbers
        rows = [
            [b.label, str(b.received), str(b.seen), str(b.answered)]
            for b in buckets
        ]
        return heads, rows, [total] + totals, 1
    heads = [
        _label("mail_stats_report_col_week", lang),
        _label("mail_stats_report_col_week_start", lang),
    ] + numbers
    rows = [
        [b.label, b.first_day, str(b.received), str(b.seen), str(b.answered)]
        for b in buckets
    ]
    return heads, rows, [total, ""] + totals, 2


def text_table(buckets, kind: str, lang: str) -> str:
    """Le tableau en texte : colonnes séparées de deux espaces, libellés
    à gauche, nombres à droite, ligne d'en-tête et ligne Total. Toutes
    les lignes ont la même largeur. `kind` vaut « day » ou « week »."""
    heads, rows, total, labels = _table_cells(buckets, kind, lang)
    lines = [heads] + rows + [total]
    widths = [
        max(len(line[col]) for line in lines) for col in range(len(heads))
    ]

    def fmt(line):
        cells = [
            cell.ljust(width) if col < labels else cell.rjust(width)
            for col, (cell, width) in enumerate(zip(line, widths, strict=True))
        ]
        return "  ".join(cells)

    return "\n".join(fmt(line) for line in lines)


def html_table(buckets, kind: str, lang: str) -> str:
    """Le tableau en HTML, chaque libellé échappé ; nombres alignés à
    droite, ligne Total en `<th>` (sur deux colonnes pour les semaines)."""
    heads, rows, total, labels = _table_cells(buckets, kind, lang)
    esc = html.escape
    out = [_HTML_TABLE_OPEN, "<thead><tr>"]
    out += [f"<th>{esc(head)}</th>" for head in heads]
    out += ["</tr></thead>", "<tbody>"]
    for row in rows:
        cells = [
            f"<td>{esc(cell)}</td>"
            if col < labels
            else f"{_NUM_TD}{esc(cell)}</td>"
            for col, cell in enumerate(row)
        ]
        out.append("<tr>" + "".join(cells) + "</tr>")
    span = f' colspan="{labels}"' if labels > 1 else ""
    numbers = "".join(f"{_NUM_TD}{esc(cell)}</td>" for cell in total[labels:])
    out.append(f"<tr><th{span}>{esc(total[0])}</th>{numbers}</tr>")
    out += ["</tbody>", "</table>"]
    return "\n".join(out)


def _report_date(mailbox: MailboxActivity) -> str:
    return time.strftime(
        "%Y-%m-%d %H:%M %z", time.localtime(mailbox.generated_at)
    )


def _utc_offset(mailbox: MailboxActivity) -> str:
    """« UTC±hh:mm » du fuseau local à l'instant du calcul."""
    offset = time.strftime("%z", time.localtime(mailbox.generated_at))
    if len(offset) == 5 and offset[0] in "+-":
        return f"UTC{offset[:3]}:{offset[3:]}"
    return f"UTC{offset}"


def _mailbox_delay_text(mailbox: MailboxActivity, lang: str) -> str:
    window = mailbox.window_days
    if mailbox.delay_count == 0:
        return _with_n("mail_stats_report_mailbox_none", lang, window)
    if mailbox.delay_count < REPORT_MIN_DELAYS:
        return _with_n("mail_stats_report_mailbox_few", lang, window)
    value = format_delay(round_delay(mailbox.delay_mean), lang)
    return (
        f"{_with_n('mail_stats_report_mailbox_delay', lang, window)} {value}"
    )


def _requester_text(data: ReportData) -> str:
    lang, window = data.lang, data.mailbox.window_days
    delays = data.requester.delays
    if not delays:
        return _with_n("mail_stats_report_requester_none", lang, window)
    head = _with_n("mail_stats_report_requester_delay", lang, window)
    value = format_delay(mean_delay(delays), lang)
    based = _with_n("mail_stats_report_based_on", lang, len(delays))
    return f"{head} {value} {based}"


def _section(buckets, kind: str, data: ReportData) -> tuple[str, str]:
    """(texte, HTML) d'un titre suivi de son tableau."""
    lang = data.lang
    if kind == "day":
        title = _with_n("mail_stats_report_days_title", lang, len(buckets))
    else:
        title = _with_n("mail_stats_report_weeks_title", lang, len(buckets))
    text = f"{title}\n\n{text_table(buckets, kind, lang)}"
    markup_html = (
        f"<p><strong>{html.escape(title)}</strong></p>\n"
        f"{html_table(buckets, kind, lang)}"
    )
    return text, markup_html


def _whole_report(data: ReportData, days, weeks) -> tuple[str, str]:
    """(texte, HTML) du bloc `rapport`."""
    lang, mailbox = data.lang, data.mailbox
    texts, htmls = [days[0]], [days[1]]
    if mailbox.weeks:
        texts.append(weeks[0])
        htmls.append(weeks[1])
    lines = [_mailbox_delay_text(mailbox, lang)]
    if data.requester is not None:
        lines.append(_requester_text(data))
    for line in lines:
        texts.append(line)
        htmls.append(f"<p>{html.escape(line)}</p>")
    generated = _label("mail_stats_report_generated", lang)
    generated = f"{generated} {_report_date(mailbox)}"
    zone = _label("mail_stats_report_local_time", lang).replace(
        "{tz}", _utc_offset(mailbox)
    )
    texts.append(f"{generated}\n{zone}")
    htmls.append(f"<p>{html.escape(generated)}<br>\n{html.escape(zone)}</p>")
    return "\n\n".join(texts), "\n".join(htmls)


def values(data: ReportData) -> dict[str, tuple[str, str]]:
    """Le texte et le HTML de chaque variable du gabarit."""
    mailbox, requester, lang = data.mailbox, data.requester, data.lang
    days = _section(mailbox.days, "day", data)
    weeks = (
        _section(mailbox.weeks, "week", data) if mailbox.weeks else ("", "")
    )
    mailbox_delay = NO_VALUE
    if mailbox.delay_count >= REPORT_MIN_DELAYS:
        mailbox_delay = format_delay(round_delay(mailbox.delay_mean), lang)
    if requester is None:
        own_delay = asked = answered = NO_VALUE
    else:
        own_delay = format_delay(mean_delay(requester.delays), lang)
        asked, answered = str(requester.received), str(requester.answered)
    first = mailbox.days[0].first_day if mailbox.days else NO_VALUE
    last = mailbox.days[-1].first_day if mailbox.days else NO_VALUE
    scalars = {
        "recus_total": str(mailbox.received_total),
        "lus_total": str(mailbox.seen_total),
        "repondus_total": str(mailbox.answered_total),
        "delai_moyen": own_delay,
        "delai_moyen_boite": mailbox_delay,
        "demandeur_recus": asked,
        "demandeur_repondus": answered,
        "jours": str(len(mailbox.days)),
        "semaines": str(len(mailbox.weeks)),
        "fenetre_jours": str(mailbox.window_days),
        "periode_debut": first,
        "periode_fin": last,
        "date_rapport": _report_date(mailbox),
    }
    out = {name: (text, html.escape(text)) for name, text in scalars.items()}
    out["rapport"] = _whole_report(data, days, weeks)
    out["rapport_jours"] = days
    out["rapport_semaines"] = weeks
    return out


# -- Rendu -------------------------------------------------------------


def _place_block(document: str, token: str, block: str) -> str:
    """Met `block` à la place de `token` sans jamais l'enfermer dans un
    paragraphe : un `<p>` qui ne contient que le jeton est remplacé en
    entier ; un jeton au milieu d'un `<p>` ouvert ferme ce paragraphe
    avant le bloc et en rouvre un après."""
    document = re.sub(
        rf"<p>\s*{token}\s*</p>", lambda _m: block, document, flags=re.I
    )

    def inside(match: re.Match) -> str:
        before = match.string[: match.start()]
        opened = [m.start() for m in _P_OPEN_RE.finditer(before)]
        closed = [m.start() for m in _P_CLOSE_RE.finditer(before)]
        if opened and (not closed or opened[-1] > closed[-1]):
            return f"</p>{block}<p>"
        return block

    return re.sub(token, inside, document)


def render_stats_reply(
    action: Action, media: dict, domain: str, data: ReportData
) -> markup.RenderedReply:
    """Texte, HTML et images d'une réponse à statistiques.

    Un gabarit fautif lève `TemplateError` ; une faute d'image lève la
    `RuleError` de `markup.render_reply`, telle quelle. Aucun texte du
    message reçu n'entre dans le rendu.
    """
    fault = template_fault(action)
    if fault is not None:
        raise TemplateError(fault)
    nonce = secrets.token_hex(4)
    tokens: dict[str, str] = {}

    def to_token(match: re.Match) -> str:
        name = match.group(1).strip()
        if name not in tokens:
            tokens[name] = f"ZSTATS{nonce}N{len(tokens)}Z"
        return tokens[name]

    body = TEMPLATE_VAR_RE.sub(to_token, action.body or "")
    rendered = markup.render_reply(
        dataclasses.replace(action, body=body), media, domain
    )
    vals = values(data)
    text = rendered.text
    for name, token in tokens.items():
        text = text.replace(token, vals[name][0])
    document = rendered.html
    if document is not None:
        for name, token in tokens.items():
            if name in STATS_BLOCK_VARIABLES:
                document = _place_block(document, token, vals[name][1])
        document = _EMPTY_P_RE.sub("", document)
        for name, token in tokens.items():
            if name not in STATS_BLOCK_VARIABLES:
                document = document.replace(token, vals[name][1])
    return markup.RenderedReply(
        text, document, list(rendered.inline), list(rendered.attachments)
    )


def render_subject(
    original_subject: str, template: str, data: ReportData
) -> str:
    """Le sujet d'une réponse à statistiques : variables scalaires
    remplacées par leur valeur texte, puis `auto_reply_subject` (qui
    traite « {subject} » et le préfixe « Auto: »). Un bloc ou un nom
    inconnu lève `TemplateError`."""
    fault = template_fault(Action(kind="stats", subject=template or ""))
    if fault is not None:
        raise TemplateError(fault)
    vals = values(data)
    substituted = TEMPLATE_VAR_RE.sub(
        lambda match: vals[match.group(1).strip()][0], template or ""
    )
    return auto_reply_subject(original_subject, substituted)
