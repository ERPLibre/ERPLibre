#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Journaux des tâches des sessions web, gardés RETENTION_DAYS jours.

Sous `paths.tasks_dir(root)`, un répertoire par jour (`AAAA-MM-JJ`, date
locale du début de la tâche) tient :

- `<id>.log`, une tâche ouverte : du NDJSON, un enregistrement `{n, t, s,
  d}` par ligne, `n` compté depuis 1, `t` en secondes depuis le début, `s`
  valant `out` (`d` : une ligne de sortie) ou `event` (`d` : un dict dont
  `t` nomme le genre ; le premier, `task_start`, porte la tâche) ;
- `<id>.log.zst`, une tâche close : le même contenu, compressé par
  `compression.zstd`, le `.log` retiré ensuite ;
- `index.jsonl` : une ligne par tâche close, ajoutée en fin de fichier
  (`O_APPEND`), derrière un saut de ligne si la précédente est restée
  tronquée : `{id, session, crumbs, entry, key, start, end, state,
  commands, lines}`.

Répertoires 0700, fichiers 0600. Le fichier d'une tâche naît avec son
premier enregistrement : une tâche dont rien n'est gardé n'en laisse aucun.

La sortie arrive en octets bruts du PTY. Chaque ligne est décodée en UTF-8
(`replace`), débarrassée des séquences ANSI et des caractères de contrôle ;
d'une ligne réécrite par retour chariot (barre de progression), retour du
curseur en colonne 1 ou effacement de la ligne, reste la dernière version
(`clean`). Un mot de `execute.SECRET_WORDS`, cherché sans casse et sans
borne de mot dans chaque version, marque la ligne : la version gardée ne
garde rien après son premier mot guetté, et une version remplacée qui en
portait un — une valeur écrite seule par-dessus son étiquette — la fait
écrire entière en `***` (`_stored`). La version gardée passe entière par
`redact_for_storage`, qui porte cette règle, puis s'écrit par morceaux de
LINE_LIMIT caractères. Une ligne sans fin passé PARTIAL_LIMIT caractères
s'écrit en deux, mais seulement à un blanc hors séquence ANSI, là où
chaque moitié se masque seule comme la ligne entière l'aurait été, et
jamais quand elle porte déjà un mot guetté (`_cut`) ; faute d'une telle
coupure, elle attend son `\n`, ou le plafond CAP. Au-delà de CAP octets
bruts, seuls les TAIL derniers restent, écrits à la clôture derrière
l'événement `omitted {bytes}` ; la ligne que coupe le plafond et celle que
la fin retenue commence au milieu partent entières : un secret coupé ne
s'y reconnaîtrait plus.

Un événement suit la sortie qui le précède. Le début d'une ligne inachevée
s'écrit devant lui, une fois par ligne, si aucune de ses versions, même
retirée, ne porte de mot guetté et qu'il ne finit pas dans une séquence
ANSI que la suite peut encore achever (`Lines.flush`) ; sinon la ligne
reste entière et s'écrit après l'événement. La suite d'un début écrit se
masque seule, puis derrière lui (`_stored`) : elle se relit seule, dans un
enregistrement à elle, et peut réécrire la ligne plutôt que la continuer.
Le texte d'une question ou d'un avis et une commande se masquent ligne à
ligne de la même façon ; des lignes qu'une valeur entre guillemets joint
partent entières si l'une portait un mot guetté (`_redact`). Une question
dont une ligne, pas seulement la dernière, porte un mot guetté ne garde
pas sa réponse : ni l'événement de sa fin, ni la sortie, où chaque ligne
qui finit entre la question et sa fin, puis la première qui finit après,
s'écrit TAINT_MASK (HIDE, SHOW). Au-delà de CAP, un événement attend la
clôture et y prend sa place entre les lignes de la fin retenue ; celui
dont la sortie qui suit est omise s'écrit aussitôt, devant `omitted`,
comme le plus ancien quand ceux qui attendent passent LATER octets.

`purge` retire des jours entiers ; d'un jour qui tient un `.log` pas encore
à l'index, seul ce `.log` reste. Un `.log` que rien n'a clos — son hub tué,
ou le journal abandonné après une erreur d'écriture — attend le démarrage
suivant du hub, où `recover` le clôt (état `interrupted`).

`Recorder` borne les tâches d'une session par les messages de son worker
et leur donne sa sortie. Module sans tornado.
"""

import codecs
import datetime
import functools
import json
import logging
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from compression import zstd

from script.todo.web import paths

log = logging.getLogger(__name__)

RETENTION_DAYS = 30
CAP = 64 * 1024 * 1024
TAIL = 1024 * 1024
# Au-delà de CAP, octets d'événements (JSON) qui attendent au plus leur
# place dans la fin retenue ; au-delà, le plus ancien s'écrit aussitôt.
LATER = 1024 * 1024
# Caractères d'un enregistrement de sortie ; une ligne plus longue, masquée
# entière, s'écrit en plusieurs.
LINE_LIMIT = 16 * 1024
# Une ligne sans fin s'écrit, masquée, passé ce nombre de caractères, là où
# `_cut` le permet ; la suite commence une ligne neuve.
PARTIAL_LIMIT = 1024 * 1024
TASK_ID = re.compile(r"([0-9]{4})([0-9]{2})([0-9]{2})-[0-9]{6}-[0-9a-f]{6}")
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# CSI, puis OSC et chaînes DCS, SOS, PM, APC, puis toute autre séquence :
# un octet final, derrière des intermédiaires ou seul, mais seul jamais
# « [ » ni l'introducteur d'une chaîne, qui ouvrent une séquence plus
# longue : une CSI sans octet final n'est pas retirée, son ESC seul part
# avec les contrôles. Une chaîne sans terminateur court jusqu'au prochain
# ESC ou jusqu'à la fin de la ligne, que le terminal cache aussi.
# Quantificateurs possessifs, ici comme dans UNFINISHED et REWRITE : les
# classes qui se suivent sont disjointes, et aucun retour en arrière ne
# trouverait d'autre correspondance ; sans eux, une longue suite de
# paramètres sans octet final se relit depuis chacun. Ce module ne se
# charge que sous le Python de l'outillage (`compression.zstd`).
ANSI = re.compile(
    r"\x1b(?:\[[0-?]*+[ -/]*+[@-~]|[\]PX^_][^\x07\x1b]*+(?:\x07|\x1b\\)?"
    r"|[ -/]++[0-~]|[0-OQ-WYZ\\`-~])"
)
# Fin d'un texte qui s'arrête dans une séquence que la suite peut encore
# achever : ESC seul (celui d'un ST compris) ou suivi d'intermédiaires, CSI
# sans octet final, chaîne sans terminateur. Aucune branche ne porte d'ESC
# après le premier : seul le dernier ESC d'un texte peut en commencer une,
# et `_unfinished` n'essaie que lui.
UNFINISHED = re.compile(
    r"\x1b(?:[ -/]*+|\[[0-?]*+[ -/]*+|[\]PX^_][^\x07\x1b]*+)\Z"
)
# Séquences qui réécrivent la ligne comme un retour chariot : le curseur en
# colonne 1 (CSI G, 0G, 1G), la ligne effacée jusqu'au curseur ou entière
# (CSI 1K, 2K). CSI K n'efface que ce qui suit le curseur, rien de ce qui
# est gardé ; en colonne 1, il suit une réécriture qui a déjà tout pris.
REWRITE = re.compile(r"\x1b\[0*+(?:1?G|[12]K)")
# Contrôles C0 hors tabulation, saut de ligne et retour chariot, qui sépare
# les versions d'une ligne ; DEL et C1. Table de `str.translate`, qui les
# retire en un passage, sans une correspondance par contrôle isolé.
CONTROL = dict.fromkeys(
    [*range(0x09), 0x0B, 0x0C, *range(0x0E, 0x20), *range(0x7F, 0xA0)]
)
# Début d'un enregistrement tel que `_line` l'écrit : son numéro et son genre
# se lisent sans décoder le reste de la ligne.
HEAD = re.compile(r'\{"n": ([0-9]{1,18}), "t": [^,]*, "s": "(out|event)", ')
# Sortie d'une tâche retenue avant d'être écrite, HOLD_SECONDS et HOLD octets
# au plus, avec les événements venus entre ses octets : le texte du menu qui
# la clôt, que le hub lit parfois avant le message du menu, s'y retrouve et
# s'en retire. MATCH : longueur du début de ce texte cherché ; SLACK : octets
# tolérés après lui, l'écho d'une frappe.
HOLD = 64 * 1024
HOLD_SECONDS = 0.5
MATCH = 4096
SLACK = 32
# Sans le texte de son menu dans la sortie, une tâche se clôt ce nombre de
# secondes après le message du menu.
SETTLE_SECONDS = 2.0
# Caractères gardés du texte d'une question ou d'un avis.
TEXT_LIMIT = 4096
MASK = "•••"
# Marques que `Recorder` retient parmi les événements, à leur place dans la
# sortie, autour de la réponse d'une question qui ne se garde pas
# (`_hides`) : HIDE derrière la question, SHOW derrière sa fin. `TaskLog`
# les rend à `Lines` (`hide`, `show`), sans les écrire.
HIDE = {"t": "hide"}
SHOW = {"t": "show"}


def new_id(now) -> str:
    """Identifiant d'une tâche commencée à `now` (time.time()) :
    `AAAAMMJJ-HHMMSS-<6 hex>`, en heure locale."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    return f"{stamp}-{secrets.token_hex(3)}"


def day_of(task_id) -> str:
    """`AAAA-MM-JJ`, le répertoire du jour de `task_id` ; ValueError pour
    tout identifiant hors TASK_ID : aucun chemin ne se construit sans lui."""
    match = TASK_ID.fullmatch(task_id)
    if match is None:
        raise ValueError(f"invalid task id: {task_id!r}")
    return "-".join(match.groups())


def _execute():
    """Le module execute, importé au premier appel, pas au chargement :
    execute.py pose logging.basicConfig à son import, sans effet une fois
    le journal du hub en place."""
    from script.execute import execute

    return execute


def _screen(line) -> str:
    """Ce que montre `line`, version par version : sans séquence ANSI ni
    contrôle, chaque version séparée de la suivante par un « \\r », qu'y
    met un retour chariot ou une séquence REWRITE.

    Aucune fonction n'est rappelée par séquence : chaque REWRITE devient
    « \\x07\\r » avant qu'ANSI retire le reste. L'ESC d'une REWRITE
    n'appartient à aucune séquence qui la précède, et ANSI y trouve une
    séquence de même étendue : le découpage du reste de la ligne n'en
    change pas, sauf pour une chaîne OSC restée ouverte devant elle, que
    cet ESC terminait et que le BEL termine de même. Le BEL, un contrôle,
    part avec les autres."""
    return ANSI.sub("", REWRITE.sub("\x07\r", line)).translate(CONTROL)


def _versions(line) -> tuple:
    """`(avant, réécrite, montrée)` de `line` : sa dernière version qui
    montre quelque chose (`_screen`), les versions qui la précèdent,
    séparées par « \\r », et vrai si elle en suit au moins une. Une version
    faite de seuls contrôles (une sonnerie) n'en efface pas une."""
    before, rewrite, shown = _screen(line).rstrip("\r").rpartition("\r")
    return before, bool(rewrite), shown


def clean(line) -> str:
    """Ce que montre `line`, décodée et sans son saut de ligne : sans
    séquence ANSI ni caractère de contrôle, et d'une ligne réécrite, par
    un retour chariot ou une séquence REWRITE, la dernière version qui
    montre quelque chose. Cette version se lit seule : le texte qu'elle
    remplace ne se colle pas devant elle."""
    return _versions(line)[2]


def _stored(line, lead="", tainted=False) -> tuple:
    """`(montrée, gardée)` de `line`, une ligne ou le morceau d'une ligne :
    `clean(line)`, et ce qui s'en écrit sur disque. `lead`, le début de la
    ligne déjà écrit devant un événement, précède la première version de
    `line` ; `tainted` dit qu'une version déjà retirée de la ligne
    (`Lines`) portait un mot de SECRET_WORDS.

    Une version montrée qui en remplace une qui portait un tel mot — une
    valeur écrite seule par-dessus son étiquette — part entière :
    TAINT_MASK, comme sous `tainted`. Sinon `redact_for_storage` la masque,
    rien ne restant après son premier mot guetté. Derrière `lead`, une
    version qui le continue se masque seule, puis derrière lui, dont le
    masque ne rend que la suite : seule, pour un déplacement du curseur
    qu'aucune REWRITE ne dit ; derrière lui, pour un mot que l'événement a
    coupé. `lead` ne porte aucun mot de `_TRIGGERS` (`Lines.flush`), et
    aucun masque ne remplace rien avant la fin de son propre mot : il en
    ressort inchangé."""
    execute = _execute()
    before, rewritten, shown = _versions(line)
    if not shown:
        return shown, ""
    if tainted or (rewritten and execute.holds_secret_word(lead + before)):
        return shown, execute.TAINT_MASK
    stored = execute.redact_for_storage(shown)
    if lead and not rewritten:
        both = execute.redact_for_storage(lead + stored)
        stored = both[len(lead) :]
        if not both.startswith(lead):
            stored = execute.TAINT_MASK
    return shown, stored


def _secret(text, lead="") -> bool:
    """Vrai si `text` porte un mot de SECRET_WORDS : nettoyé (`_screen`),
    derrière `lead` dont il continue le début, ou brut. Nettoyé, pour un
    mot qu'une séquence coupe ; brut, pour un mot qu'une séquence mange
    (l'octet final d'une CSI), ou pour une chaîne OSC qu'un retour chariot
    coupe, dont le début, séparé du reste, ne se nettoie plus comme dans
    la ligne entière."""
    execute = _execute()
    return execute.holds_secret_word(
        lead + _screen(text)
    ) or execute.holds_secret_word(text)


def _unfinished(text) -> int:
    """Position de la séquence que `text` laisse inachevée à sa fin
    (UNFINISHED), ou -1. Aucune branche d'UNFINISHED ne porte d'ESC après
    le sien : seul le dernier ESC de `text` peut en commencer une."""
    at = text.rfind("\x1b")
    return at if at >= 0 and UNFINISHED.match(text, at) else -1


def _redact(text) -> str:
    """Ce qu'un texte d'événement ou une commande garde sur disque : chaque
    ligne masquée comme une ligne de sortie (`_stored`).

    Le masque de l'affichage lit le texte entier (`redact_secrets_by_line`),
    où une valeur peut finir sur une autre ligne que son nom : entre
    guillemets, elle joint les lignes qu'elle couvre ; derrière une option
    en fin de ligne, elle est la ligne suivante. Une ligne qu'il laisse
    telle quelle, ou masque comme la ligne brute seule, se lit brute : son
    propre masque (`_stored`) en cache au moins autant. Les autres partent
    entières, TAINT_MASK, si l'une de leurs lignes brutes porte un mot de
    SECRET_WORDS (`_secret`), que la marque « '***' » ou une séquence
    ouverte plus tôt peut cacher dans la ligne masquée ; sinon, elles se
    lisent masquées."""
    execute = _execute()
    lines, at, stored = text.split("\n"), 0, []
    for masked, count in execute.redact_secrets_by_line(text):
        raw, at = lines[at : at + count], at + count
        if count == 1 and (
            masked == raw[0] or execute.redact_secrets(raw[0]) == masked
        ):
            stored.append(_stored(raw[0])[1])
        elif any(_secret(line) for line in raw):
            stored.append(execute.TAINT_MASK)
        else:
            stored.append(_stored(masked)[1])
    return "\n".join(stored)


def _at_risk(text) -> bool:
    return _execute().holds_secret_trigger(text)


def _hides(ask) -> bool:
    """Vrai si la réponse à `ask`, une question qui n'est pas un secret, ne
    se garde pas : une ligne de son texte, et pas seulement la dernière,
    porte un mot de SECRET_WORDS (`_secret`)."""
    return ask.get("kind") != "secret" and _secret(str(ask.get("text") or ""))


def _cut(line, lead="", tainted=False) -> tuple:
    """`(écrit, gardé)`, les deux moitiés de `line`, une ligne sans fin,
    telles que chacune se masque seule comme la ligne entière l'aurait
    été : `écrit` part aussitôt, `gardé` attend la suite. `(None, line)` si
    aucune coupure n'est sûre. `lead`, le début de la ligne déjà écrit
    devant un événement (`Lines.flush`), se lit comme s'il la précédait
    encore ; `tainted`, une version retirée de la ligne portait un mot de
    SECRET_WORDS, et rien d'elle ne s'écrira que TAINT_MASK.

    Aucune ne l'est sous `tainted`, ni si `line` porte déjà un mot que
    `redact_for_storage` guette, brut ou nettoyé (`_screen`) de ce qui peut
    en séparer les deux moitiés : la valeur qui le suit peut continuer plus
    loin (un mot de passe imprimé va jusqu'à la fin de la ligne, une valeur
    entre guillemets peut porter un blanc). Sinon, un mot guetté que la
    suite achèvera commence après le troisième blanc depuis la fin de
    `line` : « mot de passe », le seul à porter deux blancs, commence au
    plus deux mots avant le mot en cours, et chaque motif de
    `redact_for_storage` commence dans le mot où tombe son mot guetté. La
    coupure s'y place, `gardé` reprenant les deux mots complets devant le
    mot en cours ; sans ces trois blancs, aucune coupure.

    Les deux moitiés se rendent nettoyées (`_screen`), leurs versions
    séparées par « \\r » : le texte d'un titre OSC ou un octet
    intermédiaire en est retiré, un blanc qui y reste est hors de toute
    séquence ANSI, et chaque moitié se relit comme dans la ligne entière.
    Seule reste brute, au bout de `gardé`, la séquence que la suite peut
    encore achever (UNFINISHED), où aucune coupure ne tombe."""
    if tainted or _at_risk(lead + line):
        return None, line
    end = _unfinished(line)
    screen = _screen(line if end < 0 else line[:end])
    if _at_risk(lead + screen.replace("\r", "")):
        return None, line
    cut = len(screen)
    for _ in range(3):
        cut = screen.rfind(" ", 0, cut)
        if cut < 0:
            return None, line
    rest = screen[cut + 1 :] + ("" if end < 0 else line[end:])
    return screen[: cut + 1], rest


class Lines:
    """Découpe un flux d'octets en lignes entières, rendues en paires
    `(montrée, gardée)` (`_stored`) ; la dernière, sans fin, attend la
    suite en morceaux non joints (`pieces`) tant qu'aucun n'apporte de
    saut de ligne ni de retour chariot : les rejoindre et les relire à
    chaque envoi coûterait, pour une ligne qui grossit sans jamais se
    terminer, un temps total au carré de sa longueur. Ils ne se joignent
    (`partial`) que passé PARTIAL_LIMIT caractères, pour chercher où couper
    (`_cut`) ; une coupure refusée tient la ligne (`held`) jusqu'à sa
    coupure réelle suivante, sans chercher de nouveau à chaque morceau
    reçu. Une barre de progression qui ne finit pas sa ligne n'y garde que
    sa dernière version ; si une version ainsi retirée portait un mot de
    SECRET_WORDS, la ligne en reste marquée (`tainted`) jusqu'à sa fin, et
    rien d'elle ne s'écrit que TAINT_MASK.

    `flush` rend le début de la ligne en cours, qu'un événement suit ; il
    reste dans `lead` jusqu'à ce que la ligne finisse, et `feed` vide
    `lead` dès qu'il rend une ligne : sa première en est la suite. Une
    ligne n'a qu'un `lead` : il ne grandit pas d'un événement à l'autre, et
    rien ne se relit en entier à chacun. Un refus de `flush` se retient de
    même : une ligne marquée, qui porte un mot guetté, qu'un morceau ajouté
    ne retire pas, ou qui finit dans une séquence inachevée (`risky`) reste
    refusée, sans relecture, jusqu'à ce que `_keep` la remplace ; refusée,
    elle ne fait que s'écrire entière après l'événement. Une ligne qui ne
    montre rien, ou que l'écho écarté (`bare`), ne se relit qu'une fois
    grandie.

    Entre `hide` et `show`, puis jusqu'à la première fin de ligne après
    `show`, chaque ligne est marquée comme la ligne en cours l'est par une
    version retirée : rien n'en reste que TAINT_MASK. `hiding` et
    `tainted` donnent à une Lines neuve (au-delà de CAP) ce que `hide` et
    `show` ont posé sur la précédente."""

    def __init__(self, hiding=False, tainted=False):
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.pieces = []  # morceaux de la ligne en cours, pas encore joints
        self.length = 0  # somme de leurs longueurs, sans les joindre
        self.held = False  # `_cut` l'a refusée : attend \n, ou le CAP
        self.pending_cr = False  # elle finit par un \r pas encore tranché
        self.lead = ""  # début de la ligne en cours, déjà rendu par `flush`
        self.tainted = tainted  # marquée : version retirée guettée, `hide`
        self.risky = False  # refusée par `flush` (mot guetté, séquence)
        self.bare = -1  # `length` quand `flush` n'y a rien lu à montrer
        self.hiding = hiding  # `hide` sans `show` : chaque ligne marquée

    def hide(self):
        """Marque la ligne en cours et chaque ligne qui la suit, jusqu'à
        `show`."""
        self.hiding = self.tainted = True

    def show(self):
        """Fin de `hide` : la ligne en cours, ou, sans ligne en cours, la
        prochaine, reste marquée jusqu'à sa fin ; les suivantes ne le sont
        plus. La réponse d'une question s'écrit sur la ligne en cours, ou
        sur la prochaine quand elle ne paraît qu'après : transcription
        d'une réponse de la page, que le port écrit après `answered`, ou
        écho d'un collage au terminal, que le hub peut lire après lui."""
        self.hiding = False

    @property
    def partial(self) -> str:
        """La ligne en cours, jointe. À n'appeler qu'à une coupure réelle,
        jamais à chaque morceau reçu : `feed` s'en charge lui-même."""
        if len(self.pieces) != 1:
            self.pieces = ["".join(self.pieces)]
        return self.pieces[0] if self.pieces else ""

    def _keep(self, rest, held=False, tainted=False):
        """Ce qui reste ouvert après une coupure : `rest` seul, en attente
        d'un morceau neuf pour continuer, ou rien si la ligne est partie ;
        `held` si `_cut` vient de refuser de le couper, `tainted` si la
        ligne qu'il continue est marquée."""
        self.pieces = [rest] if rest else []
        self.length = len(rest)
        self.pending_cr = rest.endswith("\r")
        self.held = held
        self.tainted = tainted
        self.risky = False
        self.bare = -1

    def flush(self, skip=()) -> str:
        """Le début de la ligne en cours, nettoyé, à écrire devant un
        événement, gardé dans `lead` ; "" si rien n'en paraît ou s'il est
        dans `skip`, si la ligne a déjà son `lead`, si elle est marquée ou
        porte un mot guetté, sa valeur pouvant continuer plus loin, ou si
        elle finit dans une séquence inachevée (UNFINISHED), dont la suite,
        lue seule, montrerait le reste collé au texte qui la suit : elle
        reste alors entière. Un refus ne relit pas la ligne avant qu'elle
        change (`risky`, `bare`)."""
        if not self.pieces or self.held or self.lead or self.risky:
            return ""
        if self.length == self.bare:
            return ""
        line = self.partial
        if self.tainted or _unfinished(line) >= 0 or _at_risk(line):
            self.risky = True
            return ""
        screen = _screen(line)
        if _at_risk(screen.replace("\r", "")):
            self.risky = True
            return ""
        shown = screen.rstrip("\r").rpartition("\r")[2]
        if not shown.strip() or shown.strip() in skip:
            self.bare = self.length
            return ""
        self.lead = shown
        self._keep("")
        return shown

    def feed(self, data, final=False) -> list:
        """Les paires `(montrée, gardée)` des lignes que `data` finit, ou
        coupe passé PARTIAL_LIMIT ; avec `final`, la dernière aussi."""
        lines = self._split(data, final)
        if lines:
            self.lead = ""
        return lines

    def _split(self, data, final) -> list:
        added = self.decoder.decode(data, final)
        lead, tainted = self.lead, self.tainted
        if (
            not final
            and not self.pending_cr
            and "\n" not in added
            and "\r" not in added
        ):
            # Rien à trancher dans ce morceau, et rien en attente d'un
            # tranchage reporté : l'ajouter suffit, sans retoucher ce qui
            # précède déjà.
            self.pieces.append(added)
            self.length += len(added)
            if self.held or self.length <= PARTIAL_LIMIT:
                return []
            shown, rest = _cut(self.partial, lead, tainted)
            self._keep(rest, shown is None, tainted)
            return [] if shown is None else [_stored(shown, lead)]
        text = self.partial + added
        *done, rest = text.split("\n")
        lines = []
        if done:
            # La ligne en cours finit ; ce qui suit en commence une neuve.
            lines.append(_stored(done[0], lead, tainted))
            lines += [_stored(line, tainted=self.hiding) for line in done[1:]]
            lead, tainted = "", self.hiding
        cut = rest.rfind("\r", 0, len(rest) - 1)
        if cut > 0:
            tainted = tainted or _secret(rest[:cut], lead)
            rest = rest[cut:]
        held = False
        if final:
            if rest:
                lines.append(_stored(rest, lead, tainted))
                rest = ""
        elif len(rest) > PARTIAL_LIMIT:
            shown, rest = _cut(rest, lead, tainted)
            held = shown is None
            if not held:
                lines.append(_stored(shown, lead))
        self._keep(rest, held, tainted)
        return lines


class Summary:
    """Ce que l'index dit d'une tâche, tenu enregistrement par
    enregistrement : ses commandes et son nombre de lignes."""

    def __init__(self):
        self.commands = []
        self.count = 0

    def note(self, kind, data):
        if kind == "out":
            self.count += 1
        elif not isinstance(data, dict):
            return
        elif data.get("t") == "run_start":
            command = {"cmd": data.get("cmd"), "rc": None, "secs": None}
            self.commands.append(command)
        elif data.get("t") == "run_end" and self.commands:
            self.commands[-1].update(rc=data.get("rc"), secs=data.get("secs"))

    def entry(self, info, state, end) -> dict:
        keys = ("id", "session", "crumbs", "entry", "key", "start")
        return {
            **{key: info.get(key) for key in keys},
            "end": round(end, 3),
            "state": state,
            "commands": self.commands,
            "lines": self.count,
        }


def _line(record) -> bytes:
    return json.dumps(record, ensure_ascii=False).encode() + b"\n"


class TaskLog:
    """Le journal d'une tâche ouverte. `info` : `id`, `session`, `crumbs`,
    `entry` (le libellé choisi), `key`, `start` (time.time()) ; il devient
    l'événement `task_start`. Les lignes vides en tête et en fin de tâche ne
    sont pas gardées, ni, en tête, une ligne dont le texte est dans `skip` :
    l'écho de la réponse qui a lancé la tâche. Une fois close, elle ignore
    sortie et événements : aucun `.log` n'en renaît."""

    def __init__(self, base, info, skip=()):
        self.info = {"t": "task_start", **info}
        self.path = Path(base) / day_of(info["id"]) / f"{info['id']}.log"
        self.skip = set(skip)
        self.first = True
        self.blanks = 0  # lignes vides, écrites devant ce qui les suit
        self.fd = None
        self.n = 1  # task_start
        self.raw = 0
        self.fresh = True  # le dernier octet gardé finit une ligne
        self.tail = None  # au-delà de CAP : la fin, TAIL octets au plus
        self.past = 0  # octets reçus au-delà de CAP
        self.later = []  # au-delà de CAP : (self.past, événement) retenus
        self.later_size = 0  # octets JSON de ces événements
        self.clipped = False  # la fin retenue commence dans une ligne
        self.omitted = 0
        self.lines = Lines()
        self.summary = Summary()
        self.closed = False
        self.entry = None  # rendue par la première clôture

    def output(self, data):
        """Octets du PTY : les lignes finies sont écrites aussitôt."""
        if self.closed:
            return
        if self.tail is None:
            head = data[: CAP - self.raw]
            self.raw += len(head)
            self._feed(head)
            if head:
                self.fresh = head.endswith(b"\n")
            if len(data) == len(head):
                return
            # La ligne que le plafond coupe ne s'écrit pas. HIDE et SHOW
            # valent encore dans la fin retenue : cachée si elle l'était,
            # et, sans ligne coupée, sa première ligne marquée si celle qui
            # allait commencer l'était (celle que `show` laisse marquée).
            old = self.lines
            if not self.fresh:
                self.omitted += len(old.partial.encode())
                self.clipped = True
            tainted = old.tainted if self.fresh else old.hiding
            self.lines = Lines(old.hiding, tainted)
            self.tail, data = bytearray(), data[len(head) :]
        self.tail += data
        self.past += len(data)
        extra = len(self.tail) - TAIL
        if extra > 0:
            del self.tail[:extra]
            self.omitted += extra
            self.clipped = True
            # La sortie qui suit ces événements est omise : ils ne
            # prendront place entre aucune ligne de la fin retenue.
            start = self.past - len(self.tail)
            while self.later and self.later[0][0] < start:
                self._release_one()

    def event(self, data):
        """Un événement, dict dont `t` nomme le genre, écrit aussitôt
        derrière le début de la ligne inachevée qui le précède (`_flush`) ;
        au-delà de CAP, retenu jusqu'à la clôture (`later`)."""
        if self.closed:
            return
        if self.tail is None:
            self._put(data)
            return
        self.later.append((self.past, data))
        self.later_size += len(_line(data))
        while self.later_size > LATER and self.later:
            self._release_one()

    def _put(self, data):
        """Écrit l'événement `data` aussitôt, derrière le début de la ligne
        inachevée qui le précède ; une marque (`_mark`) ne s'écrit pas."""
        if not self._mark(data):
            self._write([*self._flush(), *self._blanks(), self._event(data)])

    def _event(self, data) -> bytes:
        return self._record("event", data)

    def _release_one(self):
        """Écrit le plus ancien événement retenu au-delà de CAP. Poussé par
        LATER quand la fin retenue tient encore de la sortie venue avant
        lui, il sort avant sa place : une marque SHOW n'en a alors plus, et
        la fin retenue reste cachée plutôt que de montrer des lignes venues
        avant elle."""
        offset, data = self.later.pop(0)
        self.later_size -= len(_line(data))
        early = offset >= self.past - len(self.tail)
        if not self._mark(data, early):
            self._write([*self._blanks(), self._event(data)])

    def _mark(self, data, early=False) -> bool:
        """Vrai si `data` est une marque de `Recorder`, rendue à `Lines`
        plutôt qu'écrite : HIDE (`hide`), ou SHOW (`show`), que `early`
        fait oublier."""
        if data is HIDE:
            self.lines.hide()
        elif data is SHOW:
            if not early:
                self.lines.show()
        else:
            return False
        return True

    def _feed(self, data, final=False):
        continued = bool(self.lines.lead)
        self._write_lines(self.lines.feed(data, final), continued)

    def _flush(self) -> list:
        """Les enregistrements du début de la ligne inachevée, écrit devant
        un événement (`Lines.flush`) ; rien en tête de tâche pour l'écho de
        la réponse, qui attend sa fin pour être écarté. Sans mot de
        `_TRIGGERS`, ce début n'a rien que `redact_for_storage` masquerait :
        il s'écrit tel quel."""
        shown = self.lines.flush(self.skip if self.first else ())
        if not shown:
            return []
        self.first = False
        return [*self._blanks(), *self._outs(shown)]

    def _write_lines(self, lines, continued=False):
        """Écrit `lines`, des paires `(montrée, gardée)` (`Lines.feed`) ; la
        première, si `continued`, suit le début déjà écrit de sa ligne :
        vide, elle n'en était que la fin."""
        records = []
        for at, (shown, stored) in enumerate(lines):
            text = shown.strip()
            if continued and not at and not text:
                continue
            if self.first and (not text or text in self.skip):
                continue
            if not text:
                self.blanks += 1
                continue
            self.first = False
            records += self._blanks()
            records += self._outs(stored)
        self._write(records)

    def _outs(self, text) -> list:
        """Les enregistrements de `text`, déjà masqué entier, en morceaux
        de LINE_LIMIT caractères : un secret à cheval sur deux morceaux
        s'est reconnu avant la coupure."""
        return [
            self._record("out", text[at : at + LINE_LIMIT])
            for at in range(0, len(text), LINE_LIMIT)
        ]

    def _blanks(self) -> list:
        """Les lignes vides retenues, écrites devant ce qui les suit."""
        count, self.blanks = self.blanks, 0
        return [self._record("out", "") for _ in range(count)]

    def _record(self, kind, data) -> bytes:
        self.n += 1
        self.summary.note(kind, data)
        spent = round(time.time() - self.info["start"], 3)
        return _line({"n": self.n, "t": spent, "s": kind, "d": data})

    def _write(self, records):
        if not records:
            return
        if self.fd is None:
            paths.private_dir(self.path.parent)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND
            self.fd = os.open(self.path, flags, 0o600)
            os.fchmod(self.fd, 0o600)
            start = {"n": 1, "t": 0.0, "s": "event", "d": self.info}
            records = [_line(start), *records]
        data = b"".join(records)
        while data:
            data = data[os.write(self.fd, data) :]

    def abandon(self):
        """Ferme le journal sans le clore : `recover` le reprendra."""
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def close(self, state, end=None):
        """Clôt la tâche dans l'état `state` et rend son entrée d'index ;
        None, sans aucun fichier, si rien n'en a été gardé. Un second appel
        ne fait rien et rend ce qu'a rendu le premier (None s'il a
        échoué)."""
        if self.closed:
            return self.entry
        self.closed = True
        tail, self.tail = self.tail, None
        later, self.later = self.later, []
        start = self.past - len(tail or b"")
        if tail is not None and self.clipped:
            # Jusqu'à son premier saut de ligne, la fin retenue achève une
            # ligne dont le début est omis : elle part aussi.
            cut = tail.find(b"\n") + 1 or len(tail)
            self.omitted += cut
            del tail[:cut]
            start += cut
        if self.omitted:
            self._put({"t": "omitted", "bytes": self.omitted})
        at = 0
        for offset, data in later:
            upto = max(at, offset - start)
            self._feed(bytes(tail[at:upto]))
            at = upto
            self._put(data)
        self._feed(bytes(tail[at:] if tail else b""), final=True)
        if self.fd is None:
            return None
        self.abandon()
        entry = self.summary.entry(self.info, state, end or time.time())
        _seal(self.path, entry)
        self.entry = entry
        return entry


def _seal(path, entry):
    """Compresse `path` en `<id>.log.zst`, ajoute `entry` à l'index du jour,
    sur une ligne à elle, puis retire `path`."""
    packed = path.with_name(path.name + ".zst")
    tmp = path.with_name(path.name + ".zst.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with (
            open(fd, "wb") as raw,
            zstd.ZstdFile(raw, "wb") as out,
            open(path, "rb") as src,
        ):
            shutil.copyfileobj(src, out)
        os.replace(tmp, packed)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    index = os.open(
        path.parent / "index.jsonl",
        os.O_RDWR | os.O_CREAT | os.O_APPEND,
        0o600,
    )
    try:
        os.fchmod(index, 0o600)
        line = _line(entry)
        size = os.fstat(index).st_size
        if size and os.pread(index, 1, size - 1) != b"\n":
            line = b"\n" + line  # une ligne tronquée ne mange pas celle-ci
        while line:
            line = line[os.write(index, line) :]
    finally:
        os.close(index)
    path.unlink()


def _records(handle, start=1):
    """Enregistrements d'un journal ouvert en texte, du numéro `start` au
    dernier ; ceux d'avant ne sont pas décodés. Une ligne illisible, ou
    qu'un écrivain n'a pas finie, est sautée."""
    for line in handle:
        head = HEAD.match(line)
        if head is None or int(head[1]) < start:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            yield record


def _days(base) -> list:
    """Répertoires de jour sous `base`, ni lien ni autre nom, du plus
    ancien au plus récent."""
    try:
        found = [
            path
            for path in Path(base).iterdir()
            if DAY.fullmatch(path.name)
            and path.is_dir()
            and not path.is_symlink()
        ]
    except OSError:
        return []
    return sorted(found)


def _index(day) -> list:
    """Entrées de l'index de `day`, dans l'ordre du fichier."""
    try:
        text = (day / "index.jsonl").read_text("utf-8", errors="replace")
    except OSError:
        return []
    found = []
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and TASK_ID.fullmatch(str(entry.get("id"))):
            found.append(entry)
    return found


def entries(base, limit=50, before=None) -> list:
    """Au plus `limit` entrées d'index, les plus récentes d'abord
    (identifiant décroissant), toutes avant l'identifiant `before`."""
    found = []
    last = day_of(before) if before is not None else None
    for day in reversed(_days(base)):
        if last is not None and day.name > last:
            continue
        rows = [e for e in _index(day) if before is None or e["id"] < before]
        found += sorted(rows, key=lambda entry: entry["id"], reverse=True)
        if len(found) >= limit:
            break
    return found[:limit]


def _open(day, task_id):
    """`(fichier texte, ouverte)` du journal de `task_id`, ou None. Le
    `.log.zst` d'abord, puis le `.log`, puis encore le `.log.zst` : une
    tâche close entre deux essais se retrouve."""
    packed, live = day / f"{task_id}.log.zst", day / f"{task_id}.log"
    for path in (packed, live, packed):
        try:
            if path is live:
                return open(live, encoding="utf-8", errors="replace"), True
            text = zstd.open(packed, "rt", encoding="utf-8", errors="replace")
            return text, False
        except FileNotFoundError:
            continue
    return None


def read(base, task_id, start=1, limit=500):
    """`{lines, next, eof, state}` de la tâche `task_id` : au plus `limit`
    enregistrements dont le numéro vaut au moins `start` ; `next`, le
    numéro à demander ensuite ; `eof`, vrai si rien ne suit encore ;
    `state`, celui de l'index, `open` pendant la tâche. None si elle
    n'existe pas."""
    day = Path(base) / day_of(task_id)
    found = _open(day, task_id)
    if found is None:
        return None
    handle, live = found
    lines = []
    try:
        with handle:
            for record in _records(handle, start):
                lines.append(record)
                if len(lines) > limit:
                    break
    except (OSError, EOFError, zstd.ZstdError):
        pass  # un journal abîmé se lit jusqu'à l'abîme
    state = "open"
    if not live:
        states = {e["id"]: e.get("state") for e in _index(day)}
        state = states.get(task_id, "done")
    shown = lines[:limit]
    return {
        "lines": shown,
        "next": shown[-1]["n"] + 1 if shown else start,
        "eof": len(lines) <= limit,
        "state": state,
    }


def _summarize(path):
    """`(info, Summary)` du `.log` `path` : une ligne de sortie ne compte
    que pour le nombre de lignes, seul un événement est décodé ; une ligne
    que son écrivain n'a pas finie est sautée."""
    info, summary = {}, Summary()
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            head = HEAD.match(line)
            if head is None or not line.endswith("\n"):
                continue
            if head[2] == "out":
                summary.note("out", None)
                continue
            try:
                data = json.loads(line).get("d")
            except ValueError:
                continue
            if head[1] == "1" and isinstance(data, dict):
                info = data
            else:
                summary.note("event", data)
    return info, summary


def recover(base) -> int:
    """Clôt chaque tâche restée ouverte sous `base` — son hub tué, ou son
    journal abandonné après une erreur d'écriture — dans l'état
    `interrupted`, fin à la dernière écriture de son journal, et rend le
    nombre de tâches ainsi scellées. Un `.log` déjà à l'index n'est que
    retiré, sans compter. Une erreur du système de fichiers (disque plein)
    laisse ce `.log` au démarrage suivant, dit dans le journal, et passe à
    la tâche suivante. Le hub l'appelle au démarrage, verrou tenu."""
    count = 0
    for day in _days(base):
        indexed = {entry["id"] for entry in _index(day)}
        for path in sorted(day.glob("*.log")):
            task_id = path.name.removesuffix(".log")
            if not TASK_ID.fullmatch(task_id):
                continue
            try:
                if task_id in indexed:
                    path.unlink()  # scellé, puis tué avant de le retirer
                    continue
                info, summary = _summarize(path)
                end = path.stat().st_mtime
                info = {**info, "id": task_id}
                _seal(path, summary.entry(info, "interrupted", end))
            except OSError as exc:
                log.warning("task %s left open: %s", task_id, exc)
                continue
            count += 1
    return count


def expiry(today=None) -> datetime.date:
    """Le plus ancien jour gardé : RETENTION_DAYS jours avant `today`."""
    today = today or datetime.date.today()
    return today - datetime.timedelta(days=RETENTION_DAYS)


def purge(base, before=None) -> int:
    """Retire chaque jour antérieur à la date `before` (tous, sans elle), et
    rend le nombre de tâches closes retirées avec lui. D'un jour qui tient
    un `.log` pas encore à l'index, seul ce `.log` reste : sa tâche, close
    plus tard, y écrit un index neuf. Le hub l'appelle dans sa boucle, où
    il scelle aussi : aucune clôture ne passe au milieu."""
    removed = 0
    for day in _days(base):
        if before is not None and day.name >= before.isoformat():
            continue
        indexed = {entry["id"] for entry in _index(day)}
        for path in day.glob("*.log"):
            if path.name.removesuffix(".log") in indexed:
                path.unlink()  # scellé, puis tué avant de le retirer
        packed = list(day.glob("*.log.zst"))
        removed += len(packed)
        if not any(day.glob("*.log")):
            shutil.rmtree(day)
            continue
        for path in [*packed, *day.glob("*.zst.tmp"), day / "index.jsonl"]:
            path.unlink(missing_ok=True)
    return removed


def _safe(method):
    """Une erreur du journal abandonne la tâche ouverte, jamais la session :
    le journal du hub la dit."""

    @functools.wraps(method)
    def guarded(self, *args):
        try:
            return method(self, *args)
        except Exception:
            log.exception("task log of session %s dropped", self.session)
            self._drop()

    return guarded


class Recorder:
    """Les tâches d'une session, bornées par les messages de son worker.

    Le hub appelle :
    - `worker(message)`, pour chaque message du worker qu'il relaie. Un
      `menu` est gardé ; `answered` qui porte la `key` d'une de ses entrées
      ouvre une tâche (fil d'Ariane du menu, libellé de l'entrée) ; le
      `menu` suivant la clôt (`done`) quand son texte paraît à la fin de la
      sortie, qui s'en retire, ou sans lui SETTLE_SECONDS plus tard.
      Pendant la tâche, `ask`, `notice`, `run_start`, `run_end` et la fin
      d'une question en sont des événements ;
    - `page(message)`, pour une réponse de la page portée au worker ;
    - `output(data)`, pour les octets du PTY : hors tâche, rien n'est
      gardé ;
    - `end()`, quand la session finit : `session-ended`.

    `later(délai, fonction, *args)`, le `call_later` de la boucle du hub,
    planifie `flush`, qui écrit la sortie retenue depuis HOLD_SECONDS, et
    `settle(task_id)`, qui clôt la tâche `waiting` dont le texte du menu
    n'a pas paru ; sans lui, rien ne se planifie.

    Une tâche sans événement que clôt un menu plus ou moins profond du même
    fil d'Ariane n'est qu'un passage d'un menu à l'autre : rien n'en est
    gardé.
    """

    def __init__(self, base, session, later=None):
        self.base = Path(base)
        self.session = session
        self.later = later
        self.timer = None  # `flush` planifié
        self.menu = None  # dernier menu du worker, jusqu'à sa réponse
        self.task = None  # TaskLog de la tâche ouverte
        self._reset()

    def _reset(self):
        self.held = []  # (reçus à, octets) et événements (dict) retenus
        self.size = 0  # octets retenus, HOLD au plus hors clôture
        self.quiet = True  # aucun événement dans la tâche
        self.closing = None  # le menu qui clôt la tâche, s'il est venu
        self.expected = b""  # début de son texte, tel que le PTY le montre
        self.rest = 0  # octets de ce texte au-delà de `expected`
        self.asks = {}  # qid -> question posée pendant la tâche
        self.given = {}  # qid -> réponse de la page à cette question

    @property
    def waiting(self):
        """Identifiant de la tâche qui attend le texte de son menu, ou
        None."""
        if self.task is None or self.closing is None:
            return None
        return self.task.info["id"]

    @_safe
    def worker(self, message):
        kind = message.get("t")
        if kind == "menu":
            self.menu = message
            if self.task is not None and self.closing is None:
                self.closing = message
                text = str(message.get("text") or "").replace("\n", "\r\n")
                shown = text.encode()
                self.expected = shown[:MATCH]
                self.rest = len(shown) - len(self.expected)
                if not self._cut():
                    self._later(SETTLE_SECONDS, self.settle, self.waiting)
        elif kind == "answered":
            self._answered(message)
        elif self.task is not None:
            self._note(message)

    @_safe
    def page(self, message):
        """Retient la réponse de la page à une question de la tâche ; d'un
        secret, ou d'une question dont la réponse ne se garde pas
        (`_hides`), rien que son genre, jamais sa valeur."""
        qid = message.get("qid")
        ask = self.asks.get(qid)
        if ask is None:
            return
        if ask.get("kind") == "secret" or _hides(ask):
            message = {"t": message.get("t")}
        self.given[qid] = message

    @_safe
    def output(self, data):
        if self.task is None or not data:
            return
        self.held.append((time.monotonic(), bytearray(data)))
        self.size += len(data)
        if not self._cut():
            self._release(HOLD, self._aged())
            self._plan_flush()

    @_safe
    def flush(self):
        """Écrit la sortie retenue depuis HOLD_SECONDS, sauf pendant
        l'attente du texte d'un menu ; replanifié tant qu'il en reste."""
        self.timer = None
        if self.task is not None:
            self._release(HOLD, self._aged())
            self._plan_flush()

    @_safe
    def settle(self, task_id):
        if task_id is not None and self.waiting == task_id:
            self._close("done")

    @_safe
    def end(self):
        self._close("done" if self.closing else "session-ended")

    def _later(self, delay, callback, *args):
        if self.later is not None:
            return self.later(delay, callback, *args)
        return None

    def _aged(self):
        """Instant (time.monotonic()) jusqu'auquel la sortie retenue
        s'écrit ; None pendant l'attente du texte d'un menu."""
        if self.closing is not None:
            return None
        return time.monotonic() - HOLD_SECONDS

    def _plan_flush(self):
        if self.timer is None and self.size:
            self.timer = self._later(HOLD_SECONDS, self.flush)

    def _cut(self) -> bool:
        """Clôt la tâche si le texte de son menu finit la sortie retenue,
        à SLACK octets près : les octets retenus depuis ce texte partent,
        les événements venus après lui restent, écrits à la suite ; faux
        sinon. Le worker attend dès qu'il a écrit ce texte : plus haut dans
        la sortie, ce n'est qu'une ligne qui lui ressemble."""
        if self.closing is None or not self.expected:
            return False
        data = b"".join(i[1] for i in self.held if not isinstance(i, dict))
        at = data.rfind(self.expected)
        after = len(data) - at - len(self.expected)
        if at < 0 or after > self.rest + SLACK:
            return False
        kept, following, offset = [], [], 0
        for item in self.held:
            if isinstance(item, dict):
                (kept if offset <= at else following).append(item)
                continue
            stamp, chunk = item
            if offset < at:
                kept.append((stamp, chunk[: at - offset]))
            offset += len(chunk)
        self.held = kept + following
        self._close("done")
        return True

    def _release(self, keep, aged=None):
        """Écrit les plus anciens éléments retenus, dans l'ordre, jusqu'à
        n'en garder que `keep` octets, aucun reçu jusqu'à `aged`."""
        while self.held:
            item = self.held[0]
            if isinstance(item, dict):
                self.task.event(self.held.pop(0))
                continue
            stamp, data = item
            if self.size > keep:
                size = min(len(data), self.size - keep)
            elif aged is not None and stamp <= aged:
                size = len(data)
            else:
                break
            self.task.output(bytes(data[:size]))
            del data[:size]
            self.size -= size
            if not data:
                self.held.pop(0)

    def _answered(self, message):
        qid = message.get("qid")
        if self.menu is not None and qid == self.menu.get("qid"):
            menu, self.menu = self.menu, None
            self._close("done")
            self._open(menu, message.get("key"))
        elif self.task is not None and qid in self.asks:
            ask, given = self.asks.pop(qid), self.given.pop(qid, None)
            self._event(self._answer(ask, given, message.get("end")))
            if _hides(ask):
                self.held.append(SHOW)

    def _open(self, menu, key):
        labels = {
            item.get("key"): str(item.get("label"))
            for item in menu.get("items") or ()
            if isinstance(item, dict)
        }
        if not isinstance(key, str) or key not in labels:
            return
        now = time.time()
        info = {
            "id": new_id(now),
            "session": self.session,
            "crumbs": [str(crumb) for crumb in menu.get("crumbs") or ()],
            "entry": labels[key],
            "key": key,
            "start": round(now, 3),
        }
        # L'écho de la réponse tapée, ou sa transcription (pipe_port).
        self.task = TaskLog(
            self.base, info, skip=(key, f"{key} → {labels[key]}")
        )

    def _note(self, message):
        kind = message.get("t")
        # Masqué entier, puis coupé : coupé d'abord, un « Password: »
        # perdrait son début, et la valeur qui le suit ne se reconnaîtrait
        # plus. Une commande se masque de même : rien ne reste après un mot
        # guetté, ni sur disque, ni dans l'index.
        text = _redact(str(message.get("text") or ""))[-TEXT_LIMIT:]
        if kind == "ask":
            self.asks[message.get("qid")] = message
            self._event(
                {"t": "ask", "kind": message.get("kind"), "text": text}
            )
            if _hides(message):
                self.held.append(HIDE)
        elif kind == "notice":
            level = message.get("level")
            self._event({"t": "notice", "level": level, "text": text})
        elif kind == "run_start":
            cmd = _redact(str(message.get("cmd") or ""))
            self._event({"t": "run_start", "cmd": cmd})
        elif kind == "run_end":
            rc, secs = message.get("rc"), message.get("secs")
            self._event({"t": "run_end", "rc": rc, "secs": secs})

    def _answer(self, ask, given, end=None) -> dict:
        """L'événement de la fin de `ask`, secret compris : `cancel`
        annulée par la page, ou quand le worker la dit finie sans réponse
        (`end`, `cancel` ou `timeout`, dans `answered`), `timeout` à son
        échéance. Répondue : un secret, `answer` MASK, d'où que vienne la
        réponse ; au terminal, `answered`, sans valeur, que l'écho montre
        déjà dans la sortie, où HIDE et SHOW la cachent sous `_hides` ; par
        la page, sa valeur, ou MASK quand une
        ligne du texte de la question porte un mot guetté (`_hides`), ou
        quand le masque de stockage toucherait la ligne de l'invite qu'elle
        complète (`_stored`)."""
        if end in ("cancel", "timeout"):
            return {"t": end}
        if given is not None and given.get("t") == "cancel":
            return {"t": "cancel"}
        if ask.get("kind") == "secret":
            return {"t": "answer", "value": MASK}
        if given is None:
            return {"t": "answered"}
        if _hides(ask):
            return {"t": "answer", "value": MASK}
        value = str(given.get("value"))
        line = str(ask.get("text") or "").rsplit("\n", 1)[-1] + value
        shown, stored = _stored(line)
        return {"t": "answer", "value": value if stored == shown else MASK}

    def _event(self, data):
        """Retient l'événement à sa place dans la sortie."""
        self.held.append(data)
        self.quiet = False

    def _close(self, state):
        """Clôt la tâche ouverte dans l'état `state`, sa sortie retenue
        écrite ; d'un passage d'un menu à l'autre, rien ne reste."""
        task = self.task
        if task is not None and not self._moved(task):
            self._release(0)
            task.close(state)
        self.task = None
        self._reset()

    def _moved(self, task) -> bool:
        """Vrai si `task` n'est qu'un passage : ni événement ni rien
        d'écrit, et le menu qui la clôt est plus ou moins profond sur le
        même fil d'Ariane (un sous-menu, un retour)."""
        closing = self.closing or {}
        crumbs = [str(crumb) for crumb in closing.get("crumbs") or ()]
        old = task.info["crumbs"]
        if not crumbs or crumbs == old or not self.quiet:
            return False
        if task.fd is not None:
            return False
        return crumbs[: len(old)] == old or old[: len(crumbs)] == crumbs

    def _drop(self):
        task, self.task = self.task, None
        self._reset()
        if task is not None:
            try:
                task.abandon()
            except OSError:
                pass
