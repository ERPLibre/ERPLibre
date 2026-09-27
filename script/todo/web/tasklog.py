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
PARTIAL_LIMIT caractères s'écrit de même, sauf si elle porte encore un mot
que `redact_for_storage` guette (`holds_secret_trigger`) : sans cette fin
de ligne, une valeur qui continue plus loin (un mot de passe imprimé va
jusqu'à la fin de la ligne, une valeur entre guillemets peut porter un
blanc) ne se coupe pas à l'aveugle, elle attend le prochain `\n`. La coupure
recule aussi jusqu'au dernier blanc reçu : un mot encore en cours, pile à la
frontière entre deux morceaux du PTY, ne se scinde donc jamais, qu'il porte
ou non un mot guetté ; sans aucun blanc, la ligne grossit comme une ligne
guettée, jusqu'à son `\n` ou jusqu'au plafond CAP. Un morceau reçu sans
saut de ligne ni retour chariot s'ajoute tel quel à la ligne en cours, sans
la relire : ce qu'elle porte déjà ne coûte qu'une fois, à sa coupure réelle,
jamais à chaque envoi. Au-delà de CAP octets bruts, seuls les TAIL derniers
restent, écrits à la clôture derrière l'événement `omitted {bytes}` ; la
ligne que coupe le plafond et celle que la fin retenue commence au milieu
partent entières : un secret coupé ne s'y reconnaîtrait plus.

`purge` retire des jours entiers ; d'un jour qui tient un `.log` pas encore
à l'index, seul ce `.log` reste. Un `.log` que rien n'a clos — son hub tué,
ou le journal abandonné après une erreur d'écriture — attend le démarrage
suivant du hub, où `recover` le clôt (état `interrupted`). Module sans
tornado.
"""

import codecs
import datetime
import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from compression import zstd

from script.todo.web import paths

RETENTION_DAYS = 30
CAP = 64 * 1024 * 1024
TAIL = 1024 * 1024
# Caractères d'un enregistrement de sortie ; une ligne plus longue, masquée
# entière, s'écrit en plusieurs.
LINE_LIMIT = 16 * 1024
# Une ligne sans fin s'écrit, masquée, passé ce nombre de caractères ; la
# suite commence une ligne neuve. Tant qu'elle porte un mot que
# redact_for_storage guette, elle attend son \n plutôt que de se couper là.
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
    retour chariot, la dernière version non vide."""
    versions = [part for part in ANSI.sub("", line).split("\r") if part]
    return CONTROL.sub("", versions[-1]) if versions else ""


def _redact(text) -> str:
    # Importé à la première ligne gardée, pas au chargement : execute.py
    # pose logging.basicConfig à son import, sans effet une fois le journal
    # du hub en place.
    from script.execute.execute import redact_for_storage

    return redact_for_storage(text)


def _at_risk(text) -> bool:
    # Même import différé que _redact, même raison.
    from script.execute.execute import holds_secret_trigger

    return holds_secret_trigger(text)


def _cut_at_space(line) -> tuple:
    """`(devant, après)` du dernier blanc de `line`, lui-même dans `devant` ;
    `(None, line)` si `line` n'en porte aucun. Le mot en cours à la fin de
    `line` — celui qu'une coupure pile à la frontière entre deux morceaux du
    PTY aurait pu couper en deux, guetté ou non — reste ainsi entier dans
    l'une des deux moitiés, jamais partagé entre les deux."""
    cut = line.rfind(" ")
    return (None, line) if cut < 0 else (line[: cut + 1], line[cut + 1 :])


class Lines:
    """Découpe un flux d'octets en lignes nettoyées et entières ; la
    dernière, sans fin, attend la suite en morceaux non joints (`pieces`)
    tant qu'aucun n'apporte de saut de ligne ni de retour chariot : les
    rejoindre et les relire à chaque envoi coûterait un temps proportionnel
    à leur longueur déjà accumulée — un temps total proportionnel au carré
    de celle-ci pour une ligne qui grossit sans jamais se terminer. Ils ne
    se joignent (`partial`) qu'à une coupure réelle, au dernier blanc reçu
    avant PARTIAL_LIMIT caractères : jamais au milieu d'un mot, secret ou
    non — un mot que `redact_for_storage` guette et qui tomberait pile à la
    frontière entre deux morceaux du PTY reste ainsi entier d'un côté ou de
    l'autre, reconnaissable. Sans aucun blanc à trouver, ou tant que la
    ligne porte déjà un mot guetté, la coupure attend plutôt son `\\n` — sans
    quoi elle laisserait une valeur à cheval sur deux morceaux, qu'aucun des
    deux ne reconnaîtrait plus (une valeur entre guillemets peut porter un
    blanc, qui n'est alors plus une frontière sûre) ; `stuck` évite de
    rechercher ce blanc à nouveau à chaque morceau reçu tant qu'aucun n'est
    apparu, une recherche aussi coûteuse que la ligne déjà accumulée. Une
    barre de progression qui ne finit pas sa ligne n'y garde que sa
    dernière version."""

    def __init__(self):
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.pieces = []  # morceaux de la ligne en cours, pas encore joints
        self.length = 0  # somme de leurs longueurs, sans les joindre
        self.tainted = False  # la ligne en cours porte un mot guetté
        self.stuck = False  # déjà cherché un blanc où couper, sans en trouver
        self.pending_cr = False  # elle finit par un \r pas encore tranché

    @property
    def partial(self) -> str:
        """La ligne en cours, jointe. À n'appeler qu'à une coupure réelle,
        jamais à chaque morceau reçu : `feed` s'en charge lui-même."""
        if len(self.pieces) != 1:
            self.pieces = ["".join(self.pieces)]
        return self.pieces[0] if self.pieces else ""

    def _keep(self, rest):
        """Ce qui reste ouvert après une coupure : `rest` seul, en attente
        d'un morceau neuf pour continuer, ou rien si la ligne est partie."""
        self.pieces = [rest] if rest else []
        self.length = len(rest)
        self.pending_cr = rest.endswith("\r")
        self.stuck = False

    def feed(self, data, final=False) -> list:
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
            self.tainted = self.tainted or _at_risk(added)
            if (
                self.length > PARTIAL_LIMIT
                and not self.tainted
                and not self.stuck
            ):
                shown, rest = _cut_at_space(self.partial)
                if shown is None:
                    self.stuck = True  # aucun blanc : attend \n, ou le CAP
                    return []
                self._keep(rest)
                return [clean(shown)]
            return []
        text = self.partial + added
        *done, rest = text.split("\n")
        if done:
            # Une fin de ligne referme tout ce qui précède : seule la suite,
            # venue après elle, peut encore porter une valeur.
            self.tainted = _at_risk(rest)
        else:
            self.tainted = self.tainted or _at_risk(added)
        cut = rest.rfind("\r", 0, len(rest) - 1)
        if cut > 0:
            rest = rest[cut:]
            self.tainted = _at_risk(rest)
        if final:
            if rest:
                done.append(rest)
                rest = ""
                self.tainted = False
        elif not self.tainted and len(rest) > PARTIAL_LIMIT:
            shown, rest = _cut_at_space(rest)
            if shown is not None:
                done.append(shown)
        self._keep(rest)
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
        self.clipped = False  # la fin retenue commence dans une ligne
        self.omitted = 0
        self.lines = Lines()
        self.summary = Summary()

    def output(self, data):
        """Octets du PTY : les lignes finies sont écrites aussitôt."""
        if self.tail is None:
            head = data[: CAP - self.raw]
            self.raw += len(head)
            self._write_lines(self.lines.feed(head))
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
        extra = len(self.tail) - TAIL
        if extra > 0:
            del self.tail[:extra]
            self.omitted += extra
            self.clipped = True

    def event(self, data):
        """Un événement, dict dont `t` nomme le genre, écrit aussitôt."""
        self._write([*self._blanks(), self._record("event", data)])

    def _write_lines(self, lines):
        records = []
        for line in lines:
            text = line.strip()
            if self.first and (not text or text in self.skip):
                continue
            if not text:
                self.blanks += 1
                continue
            self.first = False
            records += self._blanks()
            # Masquée entière, puis coupée : un secret à cheval sur deux
            # morceaux se reconnaît encore.
            shown = _redact(line)
            for at in range(0, len(shown), LINE_LIMIT):
                piece = shown[at : at + LINE_LIMIT]
                records.append(self._record("out", piece))
        self._write(records)

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
        None, sans aucun fichier, si rien n'en a été gardé."""
        tail, self.tail = self.tail, None
        if tail is not None and self.clipped:
            # Jusqu'à son premier saut de ligne, la fin retenue achève une
            # ligne dont le début est omis : elle part aussi.
            cut = tail.find(b"\n") + 1 or len(tail)
            self.omitted += cut
            del tail[:cut]
        if self.omitted:
            self.event({"t": "omitted", "bytes": self.omitted})
        self._write_lines(self.lines.feed(bytes(tail or b""), final=True))
        if self.fd is None:
            return None
        self.abandon()
        entry = self.summary.entry(self.info, state, end or time.time())
        _seal(self.path, entry)
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
    `interrupted`, fin à la dernière écriture de son journal. Rend leur
    nombre. Le hub l'appelle au démarrage, verrou tenu."""
    count = 0
    for day in _days(base):
        indexed = {entry["id"] for entry in _index(day)}
        for path in sorted(day.glob("*.log")):
            task_id = path.name.removesuffix(".log")
            if not TASK_ID.fullmatch(task_id):
                continue
            count += 1
            if task_id in indexed:
                path.unlink()  # scellé, puis tué avant de le retirer
                continue
            info, summary = _summarize(path)
            end = path.stat().st_mtime
            entry = summary.entry({**info, "id": task_id}, "interrupted", end)
            _seal(path, entry)
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
