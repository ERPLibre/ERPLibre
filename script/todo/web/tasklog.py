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
d'une ligne réécrite par retour chariot (barre de progression) reste la
dernière version ; elle passe entière par `redact_for_storage`, puis
s'écrit par morceaux de LINE_LIMIT caractères. Une ligne sans fin passé
PARTIAL_LIMIT caractères s'écrit en deux, mais seulement là où chaque
moitié se masque seule comme la ligne entière l'aurait été (`_cut`) ; faute
d'une telle coupure, elle attend son `\n`, ou le plafond CAP. Au-delà de CAP
octets bruts, seuls les TAIL derniers restent, écrits à la clôture derrière
l'événement `omitted {bytes}` ; la ligne que coupe le plafond et celle que
la fin retenue commence au milieu partent entières : un secret coupé ne s'y
reconnaîtrait plus.

Un événement suit la sortie qui le précède. Le début d'une ligne inachevée
s'écrit devant lui, une fois par ligne, s'il ne porte aucun mot guetté
(`Lines.flush`), et la suite de la ligne se masque derrière ce début ;
sinon la ligne reste entière et s'écrit après l'événement. Au-delà de CAP,
un événement attend la clôture et y prend sa place entre les lignes de la
fin retenue ; celui dont la sortie qui suit est omise s'écrit aussitôt,
devant `omitted`, comme le plus ancien quand ceux qui attendent passent
LATER octets.

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
# CSI, puis OSC et chaînes DCS, SOS, PM, APC, puis toute autre séquence.
ANSI = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|[\]PX^_][^\x07\x1b]*(?:\x07|\x1b\\)?"
    r"|[ -/]*[0-~])"
)
# Contrôles C0 hors tabulation et saut de ligne, DEL et C1.
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
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


def clean(line) -> str:
    """Ce que montre `line`, décodée et sans son saut de ligne : sans
    séquence ANSI ni caractère de contrôle, et d'une ligne réécrite par
    retour chariot, la dernière version qui montre quelque chose ; une
    version faite de seuls contrôles (une sonnerie) n'en efface pas une."""
    parts = [CONTROL.sub("", part) for part in ANSI.sub("", line).split("\r")]
    versions = [part for part in parts if part]
    return versions[-1] if versions else ""


def _redact(text, shown=False) -> str:
    """`redact_for_storage(text)` ; avec `shown`, `redact_secrets(text)`, le
    masque de l'affichage, qui garde une commande entière."""
    # Importé au premier appel, pas au chargement : execute.py pose
    # logging.basicConfig à son import, sans effet une fois le journal du
    # hub en place.
    from script.execute import execute

    if shown:
        return execute.redact_secrets(text)
    return execute.redact_for_storage(text)


def _redact_command(cmd) -> str:
    """Le masque de l'affichage (`redact_secrets`), qui garde une commande
    lisible, puis celui du stockage, qui rattrape ce qu'il guette seul
    (« password= » sans option ni « -- ») sans retoucher une valeur que le
    premier a déjà réduite à « '***' » (`keep_masked`). Pour `run_start.cmd`
    seulement : une ligne de sortie brute n'a jamais cette valeur à
    préserver, `_redact` seul lui suffit."""
    # Même import différé que _redact, même raison.
    from script.execute import execute

    return execute.redact_for_storage(
        execute.redact_secrets(cmd), keep_masked=True
    )


def _at_risk(text) -> bool:
    # Même import différé que _redact, même raison.
    from script.execute.execute import holds_secret_trigger

    return holds_secret_trigger(text)


def _cut(line, lead="") -> tuple:
    """`(écrit, gardé)`, les deux moitiés de `line`, une ligne sans fin,
    telles que chacune se masque seule comme la ligne entière l'aurait
    été : `écrit` part aussitôt, `gardé` attend la suite. `(None, line)` si
    aucune coupure n'est sûre. `lead`, le début de la ligne déjà écrit
    devant un événement (`Lines.flush`), se lit comme s'il la précédait
    encore.

    Aucune ne l'est si `line` porte déjà un mot que `redact_for_storage`
    guette, brut ou une fois retirés, comme le fait `clean`, les séquences
    ANSI et les contrôles qui peuvent en séparer les deux moitiés : la
    valeur qui le suit peut continuer plus loin (un mot de passe imprimé va
    jusqu'à la fin de la ligne, une valeur entre guillemets peut porter un
    blanc). Sinon, tout mot guetté à venir, sans blanc, tombe après le
    dernier blanc de `line` ; or chaque motif de `redact_for_storage`
    commence dans le mot où tombe son mot guetté, sauf « mot de passe », qui
    commence deux mots plus tôt. La coupure se place donc au troisième blanc
    depuis la fin, `gardé` reprenant les deux mots complets devant le mot
    en cours ; sans ces trois blancs, aucune coupure."""
    plain = CONTROL.sub("", ANSI.sub("", line))
    if _at_risk(lead + line) or _at_risk(lead + plain):
        return None, line
    cut = len(line)
    for _ in range(3):
        cut = line.rfind(" ", 0, cut)
        if cut < 0:
            return None, line
    return line[: cut + 1], line[cut + 1 :]


class Lines:
    """Découpe un flux d'octets en lignes nettoyées et entières ; la
    dernière, sans fin, attend la suite en morceaux non joints (`pieces`)
    tant qu'aucun n'apporte de saut de ligne ni de retour chariot : les
    rejoindre et les relire à chaque envoi coûterait, pour une ligne qui
    grossit sans jamais se terminer, un temps total au carré de sa
    longueur. Ils ne se joignent (`partial`) que passé PARTIAL_LIMIT
    caractères, pour chercher où couper (`_cut`) ; une coupure refusée tient
    la ligne (`held`) jusqu'à sa coupure réelle suivante, sans chercher de
    nouveau à chaque morceau reçu. Une barre de progression qui ne finit pas
    sa ligne n'y garde que sa dernière version.

    `flush` rend le début de la ligne en cours, qu'un événement suit ; il
    reste dans `lead` jusqu'à ce que la ligne finisse, et `feed` vide
    `lead` dès qu'il rend une ligne : sa première en est la suite. Une
    ligne n'a qu'un `lead` : il ne grandit pas d'un événement à l'autre, et
    rien ne se relit en entier à chacun."""

    def __init__(self):
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.pieces = []  # morceaux de la ligne en cours, pas encore joints
        self.length = 0  # somme de leurs longueurs, sans les joindre
        self.held = False  # `_cut` l'a refusée : attend \n, ou le CAP
        self.pending_cr = False  # elle finit par un \r pas encore tranché
        self.lead = ""  # début de la ligne en cours, déjà rendu par `flush`

    @property
    def partial(self) -> str:
        """La ligne en cours, jointe. À n'appeler qu'à une coupure réelle,
        jamais à chaque morceau reçu : `feed` s'en charge lui-même."""
        if len(self.pieces) != 1:
            self.pieces = ["".join(self.pieces)]
        return self.pieces[0] if self.pieces else ""

    def _keep(self, rest, held=False):
        """Ce qui reste ouvert après une coupure : `rest` seul, en attente
        d'un morceau neuf pour continuer, ou rien si la ligne est partie ;
        `held` si `_cut` vient de refuser de le couper."""
        self.pieces = [rest] if rest else []
        self.length = len(rest)
        self.pending_cr = rest.endswith("\r")
        self.held = held

    def flush(self) -> str:
        """Le début de la ligne en cours, nettoyé, à écrire devant un
        événement, gardé dans `lead` ; "" si rien n'en paraît, si la ligne
        a déjà son `lead`, ou si elle porte un mot guetté : elle reste
        alors entière, sa valeur pouvant continuer plus loin. Sans mot
        guetté, le masque de la ligne entière ne touche que la suite
        (`TaskLog._outs`)."""
        if not self.pieces or self.held or self.lead:
            return ""
        line = self.partial
        if _at_risk(line) or _at_risk(CONTROL.sub("", ANSI.sub("", line))):
            return ""
        shown = clean(line)
        if not shown.strip():
            return ""
        self.lead = shown
        self._keep("")
        return shown

    def feed(self, data, final=False) -> list:
        lines = self._split(data, final)
        if lines:
            self.lead = ""
        return lines

    def _split(self, data, final) -> list:
        added = self.decoder.decode(data, final)
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
            shown, rest = _cut(self.partial, self.lead)
            self._keep(rest, held=shown is None)
            return [] if shown is None else [clean(shown)]
        text = self.partial + added
        *done, rest = text.split("\n")
        cut = rest.rfind("\r", 0, len(rest) - 1)
        if cut > 0:
            rest = rest[cut:]
        held = False
        if final:
            if rest:
                done.append(rest)
                rest = ""
        elif len(rest) > PARTIAL_LIMIT:
            shown, rest = _cut(rest, self.lead)
            held = shown is None
            if not held:
                done.append(shown)
        self._keep(rest, held)
        return [clean(line) for line in done]


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
    l'écho de la réponse qui a lancé la tâche."""

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
        if self.tail is None:
            head = data[: CAP - self.raw]
            self.raw += len(head)
            self._feed(head)
            if head:
                self.fresh = head.endswith(b"\n")
            if len(data) == len(head):
                return
            # La ligne que le plafond coupe ne s'écrit pas.
            if not self.fresh:
                self.omitted += len(self.lines.partial.encode())
                self.clipped = True
            self.lines = Lines()
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
        if self.tail is None:
            self._write([*self._flush(), *self._blanks(), self._event(data)])
            return
        self.later.append((self.past, data))
        self.later_size += len(_line(data))
        while self.later_size > LATER and self.later:
            self._release_one()

    def _event(self, data) -> bytes:
        return self._record("event", data)

    def _release_one(self):
        """Écrit le plus ancien événement retenu au-delà de CAP."""
        data = self.later.pop(0)[1]
        self.later_size -= len(_line(data))
        self._write([*self._blanks(), self._event(data)])

    def _feed(self, data, final=False):
        lead = self.lines.lead
        self._write_lines(self.lines.feed(data, final), lead)

    def _flush(self) -> list:
        """Les enregistrements du début de la ligne inachevée, écrit devant
        un événement (`Lines.flush`) ; rien en tête de tâche pour l'écho de
        la réponse, qui attend sa fin pour être écarté."""
        if self.first and clean(self.lines.partial).strip() in self.skip:
            return []
        shown = self.lines.flush()
        if not shown:
            return []
        self.first = False
        return [*self._blanks(), *self._outs(shown)]

    def _write_lines(self, lines, lead=""):
        """Écrit `lines` ; la première continue `lead`, le début déjà écrit
        de sa ligne : vide, elle n'en était que la fin."""
        records = []
        for line in lines:
            prefix, lead = lead, ""
            text = line.strip()
            if prefix and not text:
                continue
            if self.first and (not text or text in self.skip):
                continue
            if not text:
                self.blanks += 1
                continue
            self.first = False
            records += self._blanks()
            records += self._outs(line, prefix)
        self._write(records)

    def _outs(self, line, prefix="") -> list:
        """Les enregistrements de `line`, masquée entière, puis coupée : un
        secret à cheval sur deux morceaux se reconnaît encore. Derrière
        `prefix`, le début de sa ligne déjà écrit, le masque relit la ligne
        entière et n'en rend que la suite : `prefix` ne porte aucun mot
        guetté (`Lines.flush`), et chaque motif de `redact_for_storage` ne
        remplace que ce qui suit le sien."""
        shown = _redact(prefix + line)[len(prefix) :]
        return [
            self._record("out", shown[at : at + LINE_LIMIT])
            for at in range(0, len(shown), LINE_LIMIT)
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
            self.event({"t": "omitted", "bytes": self.omitted})
        at = 0
        for offset, data in later:
            upto = max(at, offset - start)
            self._feed(bytes(tail[at:upto]))
            at = upto
            self.event(data)
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
        secret, rien que son genre, jamais sa valeur."""
        qid = message.get("qid")
        ask = self.asks.get(qid)
        if ask is None:
            return
        if ask.get("kind") == "secret":
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
        # plus.
        text = _redact(str(message.get("text") or ""))[-TEXT_LIMIT:]
        if kind == "ask":
            self.asks[message.get("qid")] = message
            self._event(
                {"t": "ask", "kind": message.get("kind"), "text": text}
            )
        elif kind == "notice":
            level = message.get("level")
            self._event({"t": "notice", "level": level, "text": text})
        elif kind == "run_start":
            # Les deux masques (_redact_command) : celui de l'affichage
            # garde la commande lisible, celui du stockage rattrape un mot
            # de passe imprimé sans option ni tiret (« password= »), que le
            # premier ne guette pas seul.
            cmd = _redact_command(str(message.get("cmd") or ""))
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
        déjà dans la sortie ; par la page, sa valeur, ou MASK quand le
        masque de stockage toucherait la ligne de l'invite qu'elle
        complète."""
        if end in ("cancel", "timeout"):
            return {"t": end}
        if given is not None and given.get("t") == "cancel":
            return {"t": "cancel"}
        if ask.get("kind") == "secret":
            return {"t": "answer", "value": MASK}
        if given is None:
            return {"t": "answered"}
        value = str(given.get("value"))
        line = str(ask.get("text") or "").rsplit("\n", 1)[-1] + value
        return {
            "t": "answer",
            "value": value if _redact(line) == line else MASK,
        }

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
