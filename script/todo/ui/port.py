#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Port d'interaction de TODO : ce qu'une interface sait faire pour poser
les questions de TODO, et deux ports qui le font.

Un port répond à `menu(view)`, `ask(text, default, kind, timeout)`,
`secret(text)`, `confirm(text, default, typed)`, `choose(text, options,
multi, default, labels, letters, names)`, `pick_path(start, directory)`,
`notice(text, level)`, `run(cmd, **opts)` et `open_view(view)`. `menu`
et `ask` sont les deux primitives : elles montrent leur texte tel quel
et rendent la ligne répondue, sans son saut de ligne. Une ligne vide
rend "" et laisse le défaut à l'appelant, comme `input` ; seul le compte
à rebours (`kind="countdown"`) rend `default` à l'échéance. `menu` pose
un message déjà fait : un `menu`, ou l'`ask` que construisent `choose`
et `pick_path`. `BasePort` en déduit les autres questions.

Chaque question est aussi un message `todo.v1` (`question`, `menu_view`) :
`speak`, un libellé court pour la voix ; `requires`, les capacités qu'un
client doit annoncer pour y répondre sans le terminal ; `fallback`,
toujours `pty` : le terminal de la session répond à toute question.

`TerminalPort` appelle `input` et `getpass` du processus au moment de la
question, ou, sous la capture, les fonctions d'origine qu'elle garde dans
ORIGINAL ; `ScriptedPort` répond depuis une liste et garde ses
événements. Ce module n'importe aucune bibliothèque d'interface à son
chargement : auto_ask, Execute et le navigateur urwid le sont à l'appel.
"""

import builtins
import getpass
import os
import re
import shlex
from string.templatelib import Interpolation, Template

from script.todo.todo_i18n import t

# Capacités sans lesquelles un client ne répond pas à une question de ce
# genre ; `pty`, le terminal, répond à toutes.
REQUIRES = {
    "text": ["free_text"],
    "secret": ["secret"],
    "confirm": [],
    "typed": ["typed"],
    "countdown": [],
    "choose": [],
    "path": ["free_text"],
}
FALLBACK = "pty"
SPEAK_LIMIT = 80
YES = ("y", "yes", "o", "oui")
NO = ("n", "no", "non")
# Les mots qui, dans un choix multiple, prennent toutes les options.
ALL_WORDS = ("tout", "all", "*")
# Une plage de numéros tels qu'une liste les écrit, et ce qui sépare les
# réponses d'un choix multiple.
_RANGE = re.compile(r"([1-9][0-9]*)-([1-9][0-9]*)")
_SEPARATORS = re.compile(r"[\s,]+")
# Décor en tête de ligne (emoji, puces) et ponctuation d'invite en fin.
_SPEAK_HEAD = re.compile(r"^[^\w«\"'(\[]+")
_SPEAK_TAIL = re.compile(r"[\s:]+$")
_CONVERT = {None: lambda value: value, "r": repr, "s": str, "a": ascii}

# Fonctions d'origine que la capture remplace : `legacy.install` y range
# `input`, `getpass`, `auto_ask.ask` et `FileBrowser.run_main_frame` avant
# de poser ses crochets, et TerminalPort les y prend d'abord, jamais les
# crochets. Hors capture, il appelle celles du processus, qu'un test peut
# doubler.
ORIGINAL = {}


def speak(text) -> str:
    """La dernière ligne de `text` qui porte un mot, sans décor en tête ni
    ponctuation d'invite en fin, SPEAK_LIMIT caractères au plus."""
    for line in reversed(str(text).splitlines()):
        line = _SPEAK_TAIL.sub("", _SPEAK_HEAD.sub("", line.strip()))
        if re.search(r"\w", line):
            return line[:SPEAK_LIMIT]
    return ""


def question(kind, text, default=None, timeout=None, **fields) -> dict:
    """Message `ask` d'une question de genre `kind` (une clé de REQUIRES) ;
    `timeout_s` pour un compte à rebours ; `fields` s'y ajoutent, ou
    remplacent `speak`. Une confirmation se répond par `y` ou `n`, que
    `_is_yes` et `_is_no` de TODO lisent déjà."""
    message = {
        "t": "ask",
        "kind": kind,
        "text": text,
        "default": default,
        "speak": speak(text),
        "requires": list(REQUIRES[kind]),
        "fallback": FALLBACK,
    }
    if timeout is not None:
        message["timeout_s"] = timeout
    message.update(fields)
    return message


def path_question(start, directory=False) -> dict:
    """Message `ask` de genre `path` : le chemin d'un fichier, ou avec
    `directory` d'un répertoire, à choisir à partir du répertoire `start`,
    absolu. Le message porte `start` et `directory` pour la page ; son
    texte, pour le terminal, nomme `start`, d'où part un chemin relatif
    tapé, et dit qu'une ligne vide renonce."""
    if directory:
        invite = t("Directory path (empty to cancel): ")
    else:
        invite = t("File path (empty to cancel): ")
    return question(
        "path", f"📂 {start}\n{invite}", start=start, directory=bool(directory)
    )


def choice_question(
    text, labels, multi=False, default=None, names=None, letters=None
) -> dict:
    """Message `ask` de genre `choose` : chaque libellé de `labels` sous
    son numéro, à partir de 1, puis chaque action de `letters` ({lettre:
    libellé}), puis [0] Retour. `default`, la clé qu'une réponse vide
    choisit, marque la première ligne de son entrée ; `names` ({nom:
    clé}) porte les options qu'un nom exact choisit. `text` montre la
    question, `prompt` la même, sans ses entrées, pour la page ;
    l'invite d'un choix multiple dit les réponses qu'il lit."""
    entries = [(str(n), label) for n, label in enumerate(labels, 1)]
    options = []
    for key, label in [*entries, *(letters or {}).items()]:
        if key == default:
            head, cut, rest = str(label).partition("\n")
            label = f"{head} {t('(default)')}{cut}{rest}"
        options.append(
            {"key": key, "label": str(label), "speak": speak(label)}
        )
    options.append({"key": "0", "label": t("Back"), "speak": speak(t("Back"))})
    invite = t("Several: 1 3, 2-5 or all; empty for none: ") if multi else ": "
    lines = [text, *(f"[{o['key']}] {o['label']}" for o in options)]
    return question(
        "choose",
        "\n".join(lines) + "\n" + invite,
        default,
        options=options,
        multi=bool(multi),
        names=dict(names or {}),
        prompt=text,
        speak=speak(text),
    )


def chosen_keys(message, answer):
    """Les clés que nomme `answer` à la question `message` d'un choix
    (`choice_question`) : un numéro tel que la liste l'écrit, jamais
    « 01 », « +1 » ni « ١ » ; une lettre d'action, sans casse, seule dans
    sa réponse ; le nom exact d'une option. « 0 » rend ["0"], le retour.
    Une réponse vide rend le défaut d'un choix simple, ["0"] sans lui, et
    [] pour un choix multiple : jamais toutes les options. Un choix
    multiple lit aussi les plages « 2-5 », dont chaque borne est un numéro
    affiché, et `ALL_WORDS`, séparés de virgules ou d'espaces, et rend ses
    clés dans l'ordre de la liste, sans doublon ; un nom qui porte une
    espace ou une virgule y est coupé en morceaux, et son option ne s'y
    choisit que par son numéro. None pour une réponse qui ne se lit pas
    ainsi, qui mêle une lettre à une autre réponse, ou dont un morceau se
    lit de deux façons : le nom d'une option qui est le numéro d'une
    autre, une lettre ou un mot de `ALL_WORDS`. Une lettre d'action qui
    est aussi le nom d'une option, tapée telle que la liste l'écrit, est
    donc invalide, et cette option ne se choisit que par son numéro."""
    typed = answer.strip()
    keys = [option["key"] for option in message["options"]]
    numbers = [key for key in keys if key.isdecimal() and key != "0"]
    letters = [key for key in keys if not key.isdecimal()]
    names = message.get("names") or {}
    multi = message["multi"]
    if not typed:
        return [] if multi else [message.get("default") or "0"]
    if typed == "0":
        return ["0"]
    picked = set()
    for token in filter(None, _SEPARATORS.split(typed) if multi else [typed]):
        span = _RANGE.fullmatch(token) if multi else None
        readings = [{names[token]}] if token in names else []
        if token in numbers or token.lower() in letters:
            readings.append({token.lower()})
        if multi and token.lower() in ALL_WORDS:
            readings.append(set(numbers))
        bounds = span and span[1] in numbers and span[2] in numbers
        if bounds and int(span[1]) <= int(span[2]):
            first, last = int(span[1]), int(span[2])
            readings.append({str(n) for n in range(first, last + 1)})
        if not readings or any(r != readings[0] for r in readings):
            return None
        picked |= readings[0]
    if len(picked) > 1 and picked & set(letters):
        return None
    return [key for key in keys if key in picked]


def menu_view(
    text,
    items,
    crumbs=(),
    sections=(),
    source="text",
    printed=False,
    notes=(),
) -> dict:
    """Message `menu` : `text` s'affiche tel quel, `items` sont des dict
    `key`, `label`, `section` (None hors section) ; chacun reçoit son
    `speak`. `source` dit qui l'a produit : `fill_help_info` ou `text`
    (un écran lu). `printed` : vrai quand le terminal montre, au-dessus du
    menu, ce que TODO a écrit depuis la dernière réponse ; `notes` : les
    lignes de `text` que les entrées ne disent pas (une ligne d'état)."""
    return {
        "t": "menu",
        "text": text,
        "crumbs": list(crumbs),
        "sections": list(sections),
        "items": [dict(item, speak=speak(item["label"])) for item in items],
        "source": source,
        "printed": bool(printed),
        "notes": list(notes),
        "speak": speak(crumbs[-1] if crumbs else text),
        "requires": [],
        "fallback": FALLBACK,
    }


def shell(cmd) -> str:
    """La commande shell de `cmd`. Une str passe telle quelle ; dans une
    t-string (`Template`), chaque valeur interpolée, convertie (`!r`, `!s`,
    `!a`) et formatée comme dans une f-string, passe par `shlex.quote` :
    elle reste un seul mot, espaces et `;` compris. TypeError sinon.
    Jamais de guillemets autour de `{…}` : la citation est faite ici, et
    `t"echo '{x}'"` la refermerait, rendant `x` à plusieurs mots."""
    if isinstance(cmd, str):
        return cmd
    if not isinstance(cmd, Template):
        raise TypeError(f"a command is a str or a t-string, not {cmd!r}")
    words = []
    for part in cmd:
        if isinstance(part, Interpolation):
            value = _CONVERT[part.conversion](part.value)
            words.append(shlex.quote(format(value, part.format_spec)))
        else:
            words.append(part)
    return "".join(words)


class BasePort:
    """Les questions que chaque port déduit de ses primitives `menu` et
    `ask`."""

    def secret(self, text) -> str:
        return self.ask(text, kind="secret")

    def confirm(self, text, default=False, typed=None) -> bool:
        """Vrai pour oui. Avec `typed`, vrai seulement si la réponse est ce
        texte exact : la question, un `ask` de genre `typed` posé par
        `menu`, le porte (`expected`) pour qu'une page n'active sa réponse
        qu'à l'égalité, et c'est ici qu'elle se vérifie. Une page n'y offre
        donc aucun « non » : son Annuler lève EOFError (Abort sous click),
        comme Ctrl+D, et l'appelant prend l'une et l'autre pour non. Sans
        `typed`, redemande jusqu'à oui, non ou Entrée (le défaut)."""
        if typed is not None:
            message = question("typed", text, expected=typed)
            return self.menu(message).strip() == typed
        hint = "[Y/n]" if default else "[y/N]"
        while True:
            answer = self.ask(
                f"{text} {hint}: ", "y" if default else "n", "confirm"
            )
            answer = answer.strip().lower()
            if answer in YES:
                return True
            if answer in NO:
                return False
            if not answer:
                return default

    def choose(
        self,
        text,
        options,
        multi=False,
        default=None,
        labels=None,
        letters=None,
        names=None,
    ):
        """L'option choisie, ou avec `multi` la liste de celles choisies,
        dans l'ordre de `options` ; None pour [0] Retour, Ctrl+D (EOFError)
        ou, sans `default`, une réponse vide d'un choix simple, et [] pour
        celle d'un choix multiple. Chaque option se montre par son libellé
        de `labels`, `str(option)` sans eux, et se choisit par son numéro,
        ou par un nom de `names` ({nom affiché: option}) ; sans `labels`,
        une option qui est une chaîne est aussi son nom. `default`, une
        option d'un choix simple, est ce que prend une réponse vide ; une
        action de `letters` ({lettre: libellé}), tapée seule, rend sa lettre,
        en choix multiple comme en choix simple. Une lettre qui est aussi le
        nom d'une option se lit de deux façons : tapée telle que la liste
        l'écrit, elle est invalide, et cette option ne se choisit que par son
        numéro. Dans un choix multiple, un nom qui porte une espace ou une
        virgule ne se tape pas, coupé par les séparateurs : son option s'y
        choisit par son numéro. Une réponse invalide le dit (`notice`) et la
        question revient. Les règles sont celles de `chosen_keys` ; la
        question, un `ask` de genre `choose` (`choice_question`), posé par
        `menu`. ValueError, avant de demander, pour un défaut dans un choix
        multiple, une lettre hors de a à z, un libellé de plus ou de moins que
        d'options, un défaut ou un nom hors des options."""
        options = list(options)
        if labels is None:
            labels = [str(option) for option in options]
            strings = [option for option in options if isinstance(option, str)]
            names = {**dict(zip(strings, strings)), **(names or {})}
        if multi and default is not None:
            raise ValueError("a multiple choice has no default")
        if len(labels) != len(options) or not all(
            re.fullmatch("[a-z]+", letter) for letter in letters or ()
        ):
            raise ValueError("one label per option, letters from a to z")
        shown = {
            name: str(options.index(option) + 1)
            for name, option in (names or {}).items()
        }
        key = None if default is None else str(options.index(default) + 1)
        message = choice_question(text, labels, multi, key, shown, letters)
        while True:
            try:
                answer = self.menu(message)
            except EOFError:
                return None
            keys = chosen_keys(message, answer)
            if keys is None:
                self.notice(
                    f"{t('Invalid choice: ')}{answer.strip()}", "error"
                )
            elif keys == ["0"]:
                return None
            elif keys and not keys[0].isdecimal():
                return keys[0]
            elif multi:
                return [options[int(key) - 1] for key in keys]
            else:
                return options[int(keys[0]) - 1]

    def pick_path(self, start, directory=False):
        """Le chemin absolu d'un fichier, ou avec `directory` d'un
        répertoire, choisi à partir du répertoire `start` ; None quand
        l'utilisateur renonce : Annuler (EOFError, comme Ctrl+D) ou une
        réponse blanche. La question est un `ask` de genre `path`
        (`path_question`), posé par `menu`. Un chemin relatif part de
        `start`, `~` du répertoire de l'utilisateur. La réponse se lit
        telle quelle, puis sans les blancs de ses bouts : un nom qui finit
        vraiment par une espace se choisit, et des blancs tapés autour d'un
        chemin ne le font pas refuser. Un chemin qui n'existe pas, ou d'un
        autre genre, se dit par `notice`, et la question revient sur lui
        s'il est un répertoire, sinon sur le plus proche répertoire existant
        qui le contient (`_folder`), d'où part alors un chemin relatif : le
        sélecteur de la page y rouvre, là où l'utilisateur était. Le refus
        et la reprise suivent la réponse telle quelle si elle existe, sinon
        la réponse sans ses blancs."""
        start = os.path.abspath(start)
        while True:
            try:
                answer = self.menu(path_question(start, directory))
            except EOFError:
                return None
            if not answer.strip():
                return None
            variants = [
                os.path.abspath(os.path.join(start, os.path.expanduser(text)))
                for text in dict.fromkeys((answer, answer.strip()))
            ]
            for path in variants:
                if os.path.isdir(path) if directory else os.path.isfile(path):
                    return path
            path = next(filter(os.path.exists, variants), variants[-1])
            if os.path.exists(path):
                wrong = ("Not a file: ", "Not a directory: ")
            else:
                wrong = ("No such file: ", "No such directory: ")
            self.notice(f"{t(wrong[bool(directory)])}{path}", "error")
            start = path if os.path.isdir(path) else _folder(path)


def _folder(path) -> str:
    """Le plus proche répertoire existant qui contient `path`, un chemin
    absolu ; « / » au plus haut."""
    folder = os.path.dirname(path)
    while not os.path.isdir(folder):
        folder = os.path.dirname(folder)
    return folder


class TerminalPort(BasePort):
    """Le terminal, comme au CLI : `input`, `getpass` et le compte à
    rebours d'auto_ask d'origine, `print`, `Execute.exec_command_live`."""

    def menu(self, view) -> str:
        """Les lignes du texte de `view` s'impriment, sauf la dernière,
        l'invite, seule passée à `input` : un double d'`input` qui
        n'écrit pas son invite laisse l'écran à la sortie."""
        screen, cut, invite = view["text"].rpartition("\n")
        if cut:
            print(screen)
        return ORIGINAL.get("input", builtins.input)(invite)

    def ask(self, text, default=None, kind="text", timeout=None) -> str:
        if kind == "secret":
            return ORIGINAL.get("getpass", getpass.getpass)(text)
        if kind == "countdown":
            from script.todo import auto_ask

            countdown = ORIGINAL.get("auto_ask.ask", auto_ask.ask)
            return countdown(text, default or "", timeout)
        return ORIGINAL.get("input", builtins.input)(text)

    def pick_path(self, start, directory=False):
        """Le navigateur urwid de TODO, plein écran, par sa boucle
        d'origine : le chemin choisi, ou None pour `q`."""
        from script.todo import todo_file_browser

        browser = todo_file_browser.FileBrowser
        run = ORIGINAL.get(
            "FileBrowser.run_main_frame", browser.run_main_frame
        )
        chosen = []
        run(browser(start, chosen.append, open_dir=directory))
        return chosen[-1] if chosen else None

    def notice(self, text, level="info") -> None:
        print(text)

    def run(self, cmd, **opts) -> int:
        from script.execute import execute

        return execute.Execute().exec_command_live(cmd, **opts)

    def open_view(self, view) -> bool:
        """Aucune page n'est ouverte depuis un terminal : faux."""
        return False


class ScriptedPort(BasePort):
    """Répond depuis `answers`, dans l'ordre, et garde chaque message dans
    `events`. Une réponse qui est une exception est levée ; sans réponse,
    EOFError, comme `input` en fin de fichier. `run` rend les `codes` dans
    l'ordre, puis 0."""

    def __init__(self, answers=(), codes=()):
        self.answers = list(answers)
        self.codes = list(codes)
        self.events = []

    def _answer(self, message) -> str:
        self.events.append(message)
        if not self.answers:
            raise EOFError("no scripted answer left")
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def menu(self, view) -> str:
        return self._answer(view)

    def ask(self, text, default=None, kind="text", timeout=None) -> str:
        return self._answer(question(kind, text, default, timeout))

    def notice(self, text, level="info") -> None:
        self.events.append({"t": "notice", "text": text, "level": level})

    def run(self, cmd, **opts) -> int:
        self.events.append({"t": "run", "cmd": cmd, "opts": opts})
        return self.codes.pop(0) if self.codes else 0

    def open_view(self, view) -> bool:
        self.events.append({"t": "open_view", "view": view})
        return True
