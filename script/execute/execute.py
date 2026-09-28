#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

# Annotations différées : la migration charge ce module sous le Python
# d'Odoo 12 — 3.7 — où « dict | None » et « tuple[str, str] » n'existent
# pas encore. Sans ceci, l'annotation est ÉVALUÉE au chargement et la
# migration meurt sur un TypeError avant d'avoir rien fait.
from __future__ import annotations

import codecs
import datetime
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import termios
import threading
import time

try:
    import humanize
except ModuleNotFoundError:
    humanize = None

VENV_ERPLIBRE = ".venv.erplibre"

# Une commande construite ailleurs peut porter un secret en clair : todo.py et
# kdbx_manager.py y mettent « --default_password_auth '<mot de passe KeePass>' ».
# Cette commande est affichée avant et après l'exécution, et journalisée en
# erreur : le secret finissait donc dans le terminal, dans les journaux et dans
# toute sortie CI qui les capture.
#
# Ce filtre reste le dernier rempart, pas le premier : un secret n'a rien à
# faire sur argv, que /proc/<pid>/cmdline expose à tout utilisateur de la
# machine et qu'aucun caviardage n'atteint. db_restore.py est passé à
# MASTER_PWD dans l'environnement pour cette raison.
#
# On caviarde la VALEUR, jamais le nom de l'option : la commande reste lisible et
# reproductible, il ne manque que ce qui ne doit pas être lu. Une option ne
# commence ni juste après un caractère de mot ni après un tiret, et n'est lue
# que si un blanc ou un « = » la suit : sans ces bornes, une longue suite de
# tirets, ou un mot qui répète « token », fait essayer chaque départ ou chaque
# occurrence jusqu'au bout du mot, en un temps au carré de sa longueur.
#
# La valeur est lue comme le shell la lit : des segments collés, entre
# apostrophes, entre guillemets ou nus, jusqu'au premier blanc hors
# guillemets — `shlex.quote` écrit « it's » en « 'it'"'"'s ». Chaque segment
# se reconnaît à son premier caractère, sans retour en arrière ; un
# guillemet jamais refermé emporte le reste du mot (`\S*`).
_VALUE = r"(?=\S)(?:'[^']*'|\"[^\"]*\"|[^\s'\"])*\S*"
_SECRET_OPTION = re.compile(
    r"(?P<opt>(?<![\w-])--?(?=[\w-]*[\s=])[\w-]*"
    r"(?:password|passwd|pwd|secret|token|api[-_]?key)[\w-]*"
    r"(?:\s+|=))"
    rf"(?P<val>{_VALUE})",
    re.IGNORECASE,
)
# Une variable dont le nom porte le mot d'un secret, ou « _PWD »
# (MASTER_PWD) ; PWD et OLDPWD, des répertoires, restent. Le nom n'est lu que
# suivi de « = » et du début d'une valeur, pour la même raison de temps : un
# nom qui répète le mot d'un secret sans valeur derrière son « = » ferait
# relire sa fin depuis chacune de ses occurrences.
_SECRET_ENV = re.compile(
    r"(?P<var>\b(?=\w*=\S)\w*"
    r"(?:PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|_PWD)\w*=)"
    rf"(?P<val>{_VALUE})"
)
# Un jeton porté par un en-tête n'a ni nom d'option ni nom de variable : il
# suit le mot « Bearer », et les deux règles ci-dessus passent à côté. Le
# schéma est nommé par la RFC 7235 et se compare sans casse, la valeur allant
# jusqu'à la fin de la ligne — un jeton ne porte pas d'espace.
_SECRET_HEADER = re.compile(
    r"(?P<schema>\bAuthorization:\s*(?:Bearer|Basic)\s+)(?P<val>\S+)",
    re.IGNORECASE,
)
# Une URL porte ses identifiants dans l'« userinfo » (RFC 3986 §3.2.1) :
# « scheme://utilisateur:secret@hôte », que git, libpq et curl acceptent. On
# masque ce qui suit le deux-points jusqu'au DERNIER @ avant l'hôte (glouton) :
# un mot de passe tapé avec un « @ » non encodé (la RFC l'interdit, ça arrive
# quand même) reste ainsi caché en entier plutôt qu'à moitié. Il ne franchit
# jamais un espace ni un « / ». Il s'arrête d'abord avant « ? », « # », une
# virgule ou un guillemet, qui finissent l'autorité ou l'URL : un « @ » plus
# loin sur la ligne n'est pas celui de l'hôte, qui reste le vrai. Sans « @ »
# avant eux, il va jusqu'au dernier « @ », et un mot de passe qui en porte un
# reste caché en entier. Un port (« hôte:8069/ ») n'est jamais suivi d'un @ et
# reste. Le schéma est borné (32 caractères, RFC 3986 §3.1 l'autorise
# largement) pour qu'une ligne sans « :// » ne fasse pas remonter un temps de
# retour en arrière proportionnel à sa longueur.
_SECRET_URL_PASSWORD = re.compile(
    r"(?P<head>\b[a-z][a-z0-9+.-]{0,31}://[^\s/:@]*:)"
    r"(?P<val>[^\s/?#\"',]+(?=@)|[^\s/]+(?=@))",
    re.IGNORECASE,
)
# Un jeton peut aussi tenir lieu de nom d'utilisateur, sans deux-points, ou
# être SUIVI d'un mot de passe (GitHub : « <jeton>:x-oauth-basic@hôte »). Le
# lookahead accepte donc un « :quelquechose » optionnel avant l'@ ; sans lui,
# la règle du mot de passe ci-dessus masque déjà ce second segment (il ne
# reste que « :***@ ») et celle-ci ne voit alors plus jamais l'@ juste après
# le jeton, qui passe en clair. Un jeton se reconnaît à son préfixe (GitHub,
# GitLab) ou à défaut à sa longueur : 32 caractères opaques et plus. Un nom
# ordinaire (« git@ », « alice@ ») reste.
_SECRET_URL_TOKEN = re.compile(
    r"(?P<head>\b[a-z][a-z0-9+.-]{0,31}://)"
    r"(?P<val>(?:gh[pousr]_|github_pat_|glpat-)[\w-]+|[\w-]{32,})"
    r"(?=(?::[^\s/@]*)?@)",
    re.IGNORECASE,
)
# Les motifs de `redact_secrets` dans l'ordre où ils s'appliquent, chacun
# avec son remplacement : le groupe qui précède la valeur, puis la marque.
# Seule la valeur (`val`) disparaît. Une fonction plutôt qu'un gabarit
# (« \g<opt> ») : sans correspondance, elle ne coûte rien à `sub`, qui
# chercherait le gabarit compilé à chaque appel.
_DISPLAY_MASKS = (
    (_SECRET_OPTION, lambda m: m.group("opt") + "'***'"),
    (_SECRET_ENV, lambda m: m.group("var") + "'***'"),
    (_SECRET_HEADER, lambda m: m.group("schema") + "'***'"),
    (_SECRET_URL_PASSWORD, lambda m: m.group("head") + "***"),
    (_SECRET_URL_TOKEN, lambda m: m.group("head") + "***"),
)


def redact_secrets(text):
    """Remplace la valeur des options, variables, en-têtes et identifiants
    d'URL de secret.

    Appliqué à CHAQUE affichage d'une commande. Filtrer au point d'affichage
    plutôt qu'à la construction est ce qui rend la garantie tenable : il n'y a
    qu'une poignée de sorties ici, alors que les commandes se construisent
    partout dans le dépôt.
    """
    if not text:
        return text
    for pattern, mask in _DISPLAY_MASKS:
        text = pattern.sub(mask, text)
    return text


def redact_secrets_by_line(text) -> list:
    """Les lignes de `redact_secrets(text)`, chacune en paire avec le
    nombre de lignes de `text` qu'elle couvre, dans l'ordre : leur somme
    est ce nombre de lignes. Une valeur entre guillemets qui porte des fins
    de ligne les emporte avec elle, et les lignes qu'elle couvrait n'en
    font plus qu'une.

    Chaque motif se lit deux fois, par finditer pour compter les fins de
    ligne de ses valeurs, puis par sub : les deux trouvent les mêmes
    correspondances. Chaque fin de ligne se compte une fois par motif, et
    chaque ligne se joint une fois : le temps reste linéaire. Une valeur
    ne porte de fin de ligne qu'entre guillemets (`_VALUE`) : un texte
    d'une ligne, ou sans guillemet, ne se lit qu'une fois, par
    `redact_secrets`, et un texte sans mot de `_TRIGGERS`, qu'aucun motif
    ne masque, pas du tout."""
    if not holds_secret_trigger(text):
        return [(line, 1) for line in text.split("\n")]
    if "\n" not in text or ("'" not in text and '"' not in text):
        return [(line, 1) for line in redact_secrets(text).split("\n")]
    spans = [1] * (text.count("\n") + 1)
    for pattern, mask in _DISPLAY_MASKS:
        # `line` : ligne de `text` où commence la valeur ; `done` : lignes
        # déjà rendues à `joined`, dont la dernière peut se joindre encore.
        joined, done, line, at = [], 0, 0, 0
        for match in pattern.finditer(text):
            start, end = match.span("val")
            lost = text.count("\n", start, end)
            if not lost:
                continue
            line += text.count("\n", at, start)
            at = end
            if line < done:
                joined[-1] += sum(spans[done : line + lost + 1])
            else:
                joined += spans[done:line]
                joined.append(sum(spans[line : line + lost + 1]))
            line += lost
            done = line + 1
        spans = joined + spans[done:]
        text = pattern.sub(mask, text)
    return list(zip(text.split("\n"), spans))


# Une ligne de sortie qui imprime un mot de passe le fait sans nom d'option ni
# de variable : « Password: … », « password=… », « passwd … », « mot de
# passe : … », ou par une clé de configuration (« admin_passwd = … »,
# « POSTGRES_PASSWORD: … ») ou de JSON (« "password": … »). Deux formes font
# masquer tout le reste de la ligne, sans casse :
# - le mot seul, ou au bout d'un nom joint par « _ », un guillemet
#   éventuel, puis sur la même ligne un deux-points, un signe égal, un point
#   d'interrogation ou des blancs (l'espace insécable comprise) ;
# - une clé suivie de « : », « = » ou « ? », un guillemet éventuel entre
#   les deux : un nom fait de lettres, de chiffres, de « _ » et de « - »
#   qui porte password, passwd, passphrase, api_key (apikey, api-key),
#   token ou secret n'importe où : au début, derrière un « _ » ou un « - »,
#   collé à un préfixe (PGPASSWORD, pgpassword) ou en camelCase
#   (accessToken, clientSecret), suivi de n'importe quel suffixe collé
#   (new_password1, password_confirm). Sans ce séparateur, « tokenizer
#   output » ou « passwords rotate » restent.
# Une invite qui attend encore sa réponse (« Password: ») n'a rien à masquer.
#
# Une clé se lit à partir du début de son nom seulement, jamais derrière un
# caractère de mot ou un tiret. Son lookahead vérifie, avant que le mot de
# secret s'y cherche, qu'un nom d'au moins un caractère est suivi du
# séparateur et du début de la valeur : sans cet ordre, un nom qui répète
# « PASSWORD » ou fait de mots liés par des tirets ferait relire sa fin
# depuis chaque occurrence ; sans ce premier caractère, chaque blanc d'une
# longue suite commencerait un nom vide et relirait les blancs qui le
# suivent. Les deux coûteraient un temps au carré de la longueur.
# Aucun quantificateur possessif : ce module se charge aussi sous le Python
# d'Odoo 12.
_PASSWORD_WORD = (
    r"(?<![^\W_])(?:password|passwd|mot de passe)\b[\"']?"
    r"(?:[^\S\n]*[:=?][^\S\n]*|[^\S\n]+)"
)


def _secret_key(value):
    """Motif d'une clé, la seconde forme ci-dessus, dont le lookahead exige
    derrière le séparateur le début de valeur `value`."""
    return (
        r"(?<![\w-])(?=[\w-]+[\"']?[^\S\n]*[:=?][^\S\n]*" + value + ")"
        r"[\w-]*(?:password|passwd|passphrase|api[-_]?key|token|secret)"
        r"[\w-]*[\"']?[^\S\n]*[:=?][^\S\n]*"
    )


_PASSWORD_LINE = re.compile(
    r"(?P<head>" + _PASSWORD_WORD + "|" + _secret_key(r"\S") + ")"
    r"(?P<val>\S.*)",
    re.IGNORECASE,
)


def _head(match) -> str:
    """Remplacement de `_PASSWORD_LINE` : le mot ou la clé, puis « *** » à
    la place du reste de la ligne."""
    return match.group("head") + "***"


# Mots sans lesquels aucun motif de `redact_for_storage` ne masque rien,
# cherchés dans la ligne passée par `_fold`, comme ceux de SECRET_WORDS :
# « ſ » y devient « s », comme sous la comparaison sans casse des motifs, et
# un point combinant (U+0307) glissé dans un mot, que `_fold` retire, ne
# l'y cache pas. Chaque mot de SECRET_WORDS en contient un.
_TRIGGERS = ("pass", "pwd", "secret", "token", "key", "auth", "bearer", "://")
# Mots dont la présence masque le reste de leur ligne sur disque, où qu'ils
# tombent : sans casse (casefold) et sans borne de mot, collés au mot qui
# les précède (« Loadingpasswd ») comme seuls. Ni « pass », ni « pwd », ni
# « auth » seuls : « Tests passed », la commande pwd et « author » y
# perdraient leur fin.
SECRET_WORDS = (
    "password",
    "passwd",
    "passphrase",
    "mot de passe",
    "secret",
    "token",
    "apikey",
    "api_key",
    "api-key",
    "api key",
    "authorization",
    "bearer",
)
# Ce qui remplace la fin d'une ligne derrière son premier mot guetté, ou la
# ligne entière.
TAINT_MASK = "***"


def _fold(text) -> str:
    """`text` passé par casefold, le « ı » sans point rendu « i » et le
    point que casefold ajoute à « İ » retiré : un mot de SECRET_WORDS s'y
    trouve comme les motifs, sans casse, le trouvent."""
    return text.casefold().replace("ı", "i").replace("\u0307", "")


def _first_secret_word(folded) -> int:
    """Fin du premier mot de SECRET_WORDS dans `folded` (`_fold`), ou -1.
    Chaque mot se cherche une fois, et, dès qu'un mot est trouvé,
    seulement dans ce qui le précède."""
    start, end = -1, -1
    for word in SECRET_WORDS:
        stop = len(folded) if start < 0 else start + len(word) - 1
        at = folded.find(word, 0, stop)
        if at >= 0:
            start, end = at, at + len(word)
    return end


def holds_secret_word(text) -> bool:
    """Vrai si `text` porte un mot de SECRET_WORDS, sans casse."""
    return bool(text) and _first_secret_word(_fold(text)) >= 0


def _taint(line, masked) -> str:
    """Ce qu'une ligne garde sur disque : `line` jusqu'à la fin de son
    premier mot de SECRET_WORDS, suivie de « *** » si quelque chose le
    suivait ; sans aucun mot, `masked`, ce que les motifs en ont fait.

    Le mot finit en `end` dans `_fold(line)`, et la coupure suit
    `line[:end]` : `_fold` pliant chaque caractère seul, `_fold(line[:end])`
    commence `_fold(line)`, et le mot y finit exactement s'il compte `end`
    caractères. Sinon (un « ß » devant le mot, plié en « ss »), la coupure
    tomberait ailleurs que derrière le mot, et la ligne part entière :
    TAINT_MASK. La longueur de la ligne entière ne le dit pas : des points
    combinants que `_fold` retire derrière le mot rendent ce qu'un « ß »
    ajoute devant. TAINT_MASK aussi quand un motif a remplacé quelque
    chose avant la fin du mot (un mot dans la valeur d'un identifiant
    d'URL ou de MASTER_PWD=, qu'un motif cache déjà)."""
    end = _first_secret_word(_fold(line))
    if end < 0:
        return masked
    if len(_fold(line[:end])) != end or masked[:end] != line[:end]:
        return TAINT_MASK
    if end == len(line):
        return line
    return line[:end] + " " + TAINT_MASK


def redact_for_storage(text):
    """`redact_secrets(text)`, puis, sur chaque ligne qui imprime un mot de
    passe (`_PASSWORD_LINE`), ce qui suit le mot remplacé par « *** » ; puis
    chaque ligne qui porte un mot de SECRET_WORDS coupée après le premier
    (`_taint`).

    Pour ce que le hub garde sur disque, jamais pour l'affichage : à
    l'écran, « No password needed » se lit en entier ; dans un journal, il
    devient « No password *** », et un mot de passe imprimé n'y reste pas,
    quelle que soit la forme de son étiquette. Le mot se cherche dans la
    ligne telle que `text` la porte, les motifs attrapant seuls ce qu'aucun
    mot ne nomme (un identifiant d'URL, MASTER_PWD=). Une valeur entre
    guillemets que les motifs masquent d'une ligne à l'autre joint ces
    lignes en une (`redact_secrets_by_line`) : TAINT_MASK si l'une d'elles
    portait un mot de SECRET_WORDS, que la marque « '***' » peut avoir
    emporté avec la valeur ; sinon, la ligne masquée. Un texte sans aucun
    mot de `_TRIGGERS` est rendu tel quel sans essayer de motif, et une
    ligne seule, sans rien à joindre, sans compter ses lignes : le hub
    passe chaque ligne de sortie d'une session dans sa boucle, que les
    autres sessions attendent.
    """
    if not text:
        return text
    folded = _fold(text)
    if not any(word in folded for word in _TRIGGERS):
        return text
    if "\n" not in text:
        return _taint(text, _PASSWORD_LINE.sub(_head, redact_secrets(text)))
    joined = redact_secrets_by_line(text)
    masked = _PASSWORD_LINE.sub(
        _head, "\n".join(line for line, _ in joined)
    ).split("\n")
    lines, at, stored = text.split("\n"), 0, []
    for (_, count), line in zip(joined, masked):
        raw, at = lines[at : at + count], at + count
        if count == 1:
            stored.append(_taint(raw[0], line))
        elif any(holds_secret_word(part) for part in raw):
            stored.append(TAINT_MASK)
        else:
            stored.append(line)
    return "\n".join(stored)


def holds_secret_trigger(text) -> bool:
    """Vrai si `text` porte un mot de `_TRIGGERS`.

    Pour un appelant qui doit couper un texte avant sa fin de ligne (un
    tampon trop grand pour attendre le `\\n`) : `redact_for_storage` ne
    masque qu'une ligne entière, jamais un texte auquel il en manque un
    bout, et une valeur (`_PASSWORD_LINE` va jusqu'à la fin de ligne, une
    valeur entre guillemets peut porter un blanc) coupée au milieu ne se
    reconnaît plus dans aucun des deux morceaux. Vrai ici retarde la
    coupure jusqu'à ce que la ligne se termine réellement. Le texte passe
    une fois par `_fold`, pas une fois par mot.
    """
    if not text:
        return False
    folded = _fold(text)
    return any(word in folded for word in _TRIGGERS)


new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)


logging.basicConfig(
    format=(
        "%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d]"
        " %(message)s"
    ),
    datefmt="%Y-%m-%d:%H:%M:%S",
    level=logging.INFO,
)
_logger = logging.getLogger(__name__)


def _set_foreground(fd, pgid):
    """Donne le terminal `fd` au groupe de processus `pgid`.

    Hors du premier plan, tcsetpgrp envoie SIGTTOU à l'appelant, ce qui
    l'arrête ; bloqué le temps de l'appel dans ce thread, le signal n'est
    pas émis et l'appel aboutit (POSIX).
    """
    old = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTTOU})
    try:
        os.tcsetpgrp(fd, pgid)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old)


def _translate(key):
    """`key` traduite par `script.todo.todo_i18n`, importé au premier
    besoin : les scripts qui chargent ce module sans jamais interrompre de
    commande n'en paient pas l'import. Un import qui échoue rend `key`."""
    try:
        from script.todo.todo_i18n import t
    except Exception:
        return key
    return t(key)


class _CtrlC:
    """Gestionnaire de SIGINT d'une commande lancée sans contrôle de
    tâches, posé par `catch` avant son lancement et retiré par `release`
    après sa fin : il compte les Ctrl+C (`count`) au lieu de lever
    KeyboardInterrupt.

    La commande partage le groupe de l'appelant, et le terminal lui envoie
    déjà SIGINT : le premier Ctrl+C ne fait rien de plus. Le deuxième
    envoie SIGTERM à `process`, les suivants SIGKILL, à lui seul et jamais
    au groupe, qui est aussi celui de l'appelant ; avant que `process` ne
    soit connu, un Ctrl+C n'est que compté. Aucun ne lève dans la boucle
    qui lit la sortie de la commande, où une exception perdrait ou
    doublerait un morceau de cette sortie, sauf un seul (`raised`) : le
    troisième, ou le premier qui le suit une fois `process` connu, pendant
    la lecture de la sortie ou l'attente de la commande (`raisable`). Un
    descendant qui ignore SIGINT et SIGTERM garde le tube ouvert après la
    mort de la commande, et la lecture n'attendrait plus que lui ; un
    `kill` refusé laisse l'attente sans fin, même une fois le tube fermé.

    Une commande interrompue finie sans qu'un KeyboardInterrupt ne
    s'échappe (`raised` faux), `release` laisse SIGINT à ce gestionnaire
    et ouvre un délai de grâce (`ended`) : un Ctrl+C dans les `GRACE`
    secondes qui suivent est perdu. Sans lui, le Ctrl+C répété pendant que
    la commande meurt tombe à la question suivante et quitte l'appelant.
    Le délai se lit à l'arrivée du Ctrl+C, sans fil ni minuterie : le
    premier qui le dépasse rend SIGINT au gestionnaire par défaut et lève
    KeyboardInterrupt comme lui, et la commande suivante pose son propre
    compteur à sa place (`catch`). D'ici là, `signal.getsignal` rend ce
    gestionnaire : asyncio.run, qui ne pose le sien qu'à la place du
    gestionnaire par défaut, le laisse lever KeyboardInterrupt.
    """

    # Secondes, depuis la fin d'une commande interrompue, où un Ctrl+C est
    # perdu.
    GRACE = 1.0

    def __init__(self):
        self.caught = False
        self.process = None
        self.count = 0
        self.raisable = True
        self.raised = False
        self.tty_attrs = None
        self.ended = None

    def catch(self):
        """Se pose en gestionnaire de SIGINT, dans le fil principal et à la
        place du gestionnaire par défaut, ou du compteur d'une commande
        interrompue avant elle (`ended`), seulement : ailleurs, SIGINT est
        ignoré ou tenu par un autre (la boucle d'asyncio), qui le garde, et
        `signal.signal` lève hors du fil principal. Retient les modes du
        terminal de l'entrée standard, que `restore` remet."""
        main = threading.current_thread() is threading.main_thread()
        held = signal.getsignal(signal.SIGINT)
        free = held is signal.default_int_handler or (
            isinstance(held, _CtrlC) and held.ended is not None
        )
        if not (main and free):
            return
        signal.signal(signal.SIGINT, self)
        self.caught = True
        try:
            if sys.stdin.isatty():
                self.tty_attrs = termios.tcgetattr(sys.stdin.fileno())
        except (AttributeError, OSError, ValueError, termios.error):
            pass  # pas d'entrée standard, ou pas un terminal

    def release(self):
        """Rend SIGINT au gestionnaire par défaut, si `catch` l'avait pris ;
        `caught` reste vrai. Après une commande interrompue dont aucun
        KeyboardInterrupt ne s'échappe, garde SIGINT et ouvre le délai de
        grâce."""
        if not self.caught:
            return
        if self.count and not self.raised:
            self.ended = time.monotonic()
        else:
            signal.signal(signal.SIGINT, signal.default_int_handler)

    def restore(self):
        """Après une commande interrompue, remet les modes du terminal que
        `catch` a retenus (une commande tuée ne défait ni son `stty -echo`
        ni son mode brut), puis jette ce qu'on a tapé pendant qu'elle
        s'arrêtait : la question suivante ne le lit pas."""
        try:
            if sys.stdin.isatty():
                fd = sys.stdin.fileno()
                if self.tty_attrs:
                    termios.tcsetattr(fd, termios.TCSANOW, self.tty_attrs)
                termios.tcflush(fd, termios.TCIFLUSH)
        except (AttributeError, OSError, ValueError, termios.error):
            pass  # pas d'entrée standard, ou pas un terminal

    def __call__(self, signum, frame):
        if self.ended is not None:
            if time.monotonic() - self.ended < self.GRACE:
                return
            signal.signal(signal.SIGINT, signal.default_int_handler)
            return signal.default_int_handler(signum, frame)
        self.count += 1
        if self.process is None:
            return
        try:
            if self.count == 2:
                self.process.terminate()
            elif self.count >= 3:
                self.process.kill()
        except OSError:
            pass  # un processus d'un autre compte : le terminal l'a atteint
        if self.count >= 3 and self.raisable and not self.raised:
            self.raised = True
            raise KeyboardInterrupt


class Execute:
    # Contrôle de tâches, posé par le worker d'une session web et jamais par
    # le CLI. Vrai, une commande a son propre groupe de processus, au
    # premier plan du terminal de contrôle le temps qu'elle tourne : l'octet
    # Ctrl+C écrit sur ce terminal n'interrompt qu'elle (code -2), et le
    # processus qui l'a lancée continue. Faux, la commande partage le groupe
    # de l'appelant, et Ctrl+C les atteint tous deux. Une commande tuée
    # par un signal laisse le terminal vidé de ce qu'elle n'a pas lu. Sans
    # shell pour la reprendre, Ctrl+Z n'y suspend jamais rien : le terminal
    # de contrôle refuse de produire SIGTSTP.
    job_control = False
    # Posé par le CLI de TODO (todo.py lancé comme script), jamais par le
    # worker d'une session web ni par un script qui importe ce module. Vrai
    # et sans contrôle de tâches, Ctrl+C pendant une commande n'arrête
    # qu'elle (`_CtrlC`), et l'appelant continue ; un Ctrl+C répété dans
    # la seconde qui suit sa fin est perdu. Faux, Ctrl+C lève
    # KeyboardInterrupt chez l'appelant, qui s'arrête avec la commande : un
    # script que TODO lance meurt de son Ctrl+C, et la chaîne `&&` qui le
    # porte s'arrête avec lui.
    ctrl_c_stops_command = False
    # Vrai quand Ctrl+C a interrompu la dernière commande lancée sous
    # `_CtrlC`, faux quand elle a fini d'elle-même. Sous
    # `ctrl_c_stops_command`, chaque appel d'`exec_command_live` le remet
    # d'abord à faux, même celui qui rend la main sans rien lancer ; sans
    # ce drapeau, rien ne l'écrit. Écrit sur la classe, il vaut pour le
    # processus, quelle que soit l'instance qui a lancé la commande.
    # L'appelant le lit juste après son appel : une boucle qui lance une
    # commande par élément, et qu'un échec fait passer à l'élément suivant,
    # s'arrête là.
    interrupted = False
    # Crochet posé par le worker d'une session web et par le mode
    # enregistrement, jamais par le CLI : reçoit `run_start` (la commande
    # caviardée) avant le lancement et `run_end` (code, durée) à la fin.
    # Attribut de classe, il doit être une méthode liée ou une fonction
    # intégrée (`list.append` d'une liste) : une fonction simple recevrait
    # l'instance d'Execute en premier argument.
    events = None

    def __init__(self) -> None:
        self.cmd_source_erplibre: str = ""
        self.cmd_source_default: str = ""
        exec_path_gnome_terminal = shutil.which("gnome-terminal")
        if exec_path_gnome_terminal:
            self.cmd_source_erplibre = (
                f"gnome-terminal -- bash -c 'source"
                f" ./{VENV_ERPLIBRE}/bin/activate;%s'"
            )
            self.cmd_source_default = "gnome-terminal -- bash -c '%s'"
        else:
            exec_path_tell = shutil.which("osascript")
            if exec_path_tell:
                self.cmd_source_erplibre = (
                    "osascript -e 'tell application \"Terminal\"'"
                )
                self.cmd_source_erplibre += " -e 'tell application \"System Events\" to keystroke \"t\" using {command down}' -e 'delay 0.1' -e 'do script \""
                self.cmd_source_erplibre += f"cd {os.getcwd()}; source ./{VENV_ERPLIBRE}/bin/activate; %s\" in front window'"
                self.cmd_source_erplibre += " -e 'end tell'"
            else:
                self.cmd_source_erplibre = (
                    f"source ./{VENV_ERPLIBRE}/bin/activate;%s"
                )

    def exec_command_live(
        self,
        command: str,
        source_erplibre: bool = True,
        quiet: bool = False,
        single_source_erplibre: bool = False,
        new_window: bool = False,
        single_source_odoo: bool = False,
        source_odoo: str = "",
        new_env: dict | None = None,
        return_status_and_command: bool = False,
        return_status_and_output: bool = False,
        return_status_and_output_and_command: bool = False,
    ) -> (
        int
        | tuple[int, str]
        | tuple[int, list[str]]
        | tuple[int, str, list[str]]
    ):
        """
        Execute a command and display its output live.

        Args:
            command (str): The command to execute.
        """

        if self.ctrl_c_stops_command:
            Execute.interrupted = False
        my_env = os.environ.copy()
        if new_env:
            my_env.update(new_env)

        process_start_time = time.time()
        exit_code = None
        if source_erplibre:
            # command = f"source ./{VENV_ERPLIBRE}/bin/activate && " + command
            # cmd = (
            #     f"gnome-terminal --tab -- bash -c 'source"
            #     f" ./{VENV_ERPLIBRE}/bin/activate;{command}'"
            # )
            command = self.cmd_source_erplibre % command
            # os.system(f"./script/terminal/open_terminal.sh {command}")
        elif single_source_erplibre:
            command = f"source ./{VENV_ERPLIBRE}/bin/activate && %s" % command
        elif single_source_odoo:
            if not source_odoo and os.path.exists("./.erplibre-version"):
                with open("./.erplibre-version") as f:
                    source_odoo = f.read()
            if not source_odoo:
                _logger.error(
                    "You cannot execute Odoo command if no version is"
                    f" installed. Command : {redact_secrets(command)}"
                )
                # Return the SAME shape the caller asked for. A bare int here
                # made callers doing « status, cmd = exec_command_live(...) »
                # crash with ValueError instead of seeing the failure.
                if return_status_and_output_and_command:
                    return 1, command, []
                if return_status_and_command:
                    return 1, command
                if return_status_and_output:
                    return 1, []
                return 1
            command = f"source ./.venv.{source_odoo}/bin/activate && {command}"
        if new_window and self.cmd_source_default:
            command = self.cmd_source_default % command

        if not quiet:
            print("🏠 ⬇ Execute command :\n")
            print(redact_secrets(command))
        output_lines = []
        # Annoncée avant d'ouvrir le terminal : un échec ou une interruption
        # à l'ouverture a sa fin (`finally`), et aucun descripteur ouvert
        # ne précède le `try` qui le ferme.
        self._event({"t": "run_start", "cmd": redact_secrets(command)})
        tty = None
        ctrl_c = _CtrlC()

        try:
            tty = self._job_control_tty()
            if self.ctrl_c_stops_command and not self.job_control:
                ctrl_c.catch()
            process = subprocess.Popen(
                command,
                shell=True,
                executable="/bin/bash",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                # Octets bruts, SANS tampon. « readline » attendait le saut de
                # ligne pour rendre la main : une invite qui n'en porte pas —
                # « Continuer ? [o/N] » — restait donc invisible jusqu'à ce que
                # la réponse soit déjà tapée. La question s'affichait APRÈS la
                # réponse, et l'on répondait à l'aveugle.
                bufsize=0,
                env=my_env,
                **({"process_group": 0} if tty is not None else {}),
            )
            ctrl_c.process = process
            if tty is not None:
                try:
                    _set_foreground(tty, process.pid)
                    # Lancée hors du premier plan, la commande a pu lire le
                    # terminal avant de le recevoir : SIGTTIN l'a alors
                    # arrêtée.
                    os.killpg(process.pid, signal.SIGCONT)
                except OSError:
                    # Sans le premier plan, personne ne suivrait la commande.
                    # SIGKILL : arrêtée par SIGTTIN, elle garderait SIGTERM
                    # en attente.
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    raise

            sink = getattr(self, "log_sink", None)
            # Le tube porte des octets, et une lecture peut couper un caractère
            # accentué ou un emoji en deux. Le décodeur incrémental garde le
            # morceau incomplet en attente au lieu de rendre un « ? ».
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            fd = process.stdout.fileno()
            # « pending » est la ligne en cours, pas encore terminée ; « shown »
            # compte ce qui en a déjà été envoyé au terminal, pour ne jamais
            # afficher deux fois le même morceau d'invite quand la ligne finit
            # par se terminer.
            pending = ""
            shown = 0

            def retenir(ligne):
                """Journaliser et retenir une ligne complète, caviardée."""
                nonlocal sink
                # La sortie du sous-processus passe par le MÊME filtre que la
                # commande : un outil qui réaffiche ses propres arguments
                # (« set -x », une trace, odoo_bin.sh) y remettrait le secret
                # que l'affichage de la commande venait d'écarter.
                clean = redact_secrets(ligne)
                if sink:
                    # Chaque ligne passe DÉJÀ ici : c'est le seul endroit où
                    # journaliser sans rien changer à ce que le terminal
                    # montre. Une erreur d'écriture ne doit jamais faire
                    # échouer la commande qu'on est en train de suivre.
                    try:
                        sink.write(clean)
                    except Exception:
                        sink = None
                if (
                    return_status_and_output
                    or return_status_and_output_and_command
                ):
                    # Remove last \n char
                    output_lines.append(
                        clean.removesuffix("\r\n")
                        .removesuffix("\n")
                        .removesuffix("\r")
                    )

            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                pending += decoder.decode(chunk)
                while True:
                    coupe = pending.find("\n")
                    if coupe < 0:
                        break
                    ligne = pending[: coupe + 1]
                    pending = pending[coupe + 1 :]
                    if not quiet:
                        print(redact_secrets(ligne[shown:]), end="")
                    shown = 0
                    retenir(ligne)
                if not quiet:
                    if len(pending) > shown:
                        # Le reliquat sans saut de ligne EST l'invite : la
                        # montrer tout de suite, avant que la commande ne se
                        # bloque sur la lecture de la réponse.
                        print(redact_secrets(pending[shown:]), end="")
                        shown = len(pending)
                    # Sans vidage explicite, cette invite resterait dans le
                    # tampon de Python : second endroit où la question se
                    # perdait, la sortie n'étant vidée qu'au saut de ligne.
                    sys.stdout.flush()

            ctrl_c.raisable = False
            pending += decoder.decode(b"", True)
            if pending:
                if not quiet:
                    print(redact_secrets(pending[shown:]), end="")
                    sys.stdout.flush()
                retenir(pending)

            # Tube fermé, un `kill` refusé laisserait cette attente sans
            # fin : un Ctrl+C en lève comme de la lecture.
            ctrl_c.raisable = True
            process.wait()
            ctrl_c.raisable = False
            exit_code = process.returncode
            if process.returncode != 0 and not quiet:
                print(f"Command returned error code: {process.returncode}")

        # An exception MUST report a failure. exit_code stays None otherwise,
        # and None is falsy: callers testing « if not status: » would mark the
        # step as done, and « if status and wait_at_error » would skip the error
        # prompt. A crashed command was therefore recorded as a success.
        except FileNotFoundError:
            exit_code = 1
            if not quiet:
                print(f"Error: Command '{redact_secrets(command)}' not found.")
        except Exception as e:
            ctrl_c.raisable = False
            exit_code = 1
            if not quiet:
                print(f"An error occurred: {redact_secrets(str(e))}")
        except KeyboardInterrupt:
            # Levé une fois par `_CtrlC` (`raised`), pendant la lecture ou
            # l'attente : la commande est tuée, et le tube qu'un descendant
            # garde ouvert n'est plus lu. Un Ctrl+C de plus pendant
            # l'attente lève encore et sort d'ici, comme sans `_CtrlC` : un
            # `kill` refusé la laisserait sans fin.
            if not ctrl_c.raised:
                raise
            ctrl_c.raised = False
            process.stdout.close()
            exit_code = process.wait()
        finally:
            ctrl_c.raisable = False
            if tty is not None:
                try:
                    _set_foreground(tty, os.getpgrp())
                    # Comme Ctrl+C au terminal, une commande tuée par un
                    # signal ne laisse pas ce qu'on lui a tapé répondre à la
                    # question suivante.
                    if exit_code is not None and exit_code < 0:
                        termios.tcflush(tty, termios.TCIFLUSH)
                except OSError:
                    pass  # terminal raccroché : plus rien à reprendre
                finally:
                    os.close(tty)
            try:
                if ctrl_c.count and exit_code == 0:
                    # Une commande qui rattrape Ctrl+C et rend 0 n'a pas
                    # fini son travail : l'appelant y lit un échec.
                    exit_code = -signal.SIGINT
                # Une commande annoncée a toujours sa fin, même quand
                # KeyboardInterrupt s'échappe (sans `_CtrlC`, ou par son
                # Ctrl+C de trop) : `rc` vaut alors None.
                secs = round(time.time() - process_start_time, 3)
                self._event({"t": "run_end", "rc": exit_code, "secs": secs})
            finally:
                # Rendu, ou gardé pour le délai de grâce, en dernier : un
                # Ctrl+C tombé dans ce `finally` n'est que compté, et
                # `run_end` part. Le bloc de `tty`, hors de ce `try`, ne
                # tourne jamais sous `_CtrlC`.
                ctrl_c.release()
        if ctrl_c.caught:
            Execute.interrupted = bool(ctrl_c.count)
        if ctrl_c.count:
            # Comme sous contrôle de tâches, rien de ce qu'on a tapé à la
            # commande ne répond à la question suivante.
            ctrl_c.restore()
            if not quiet:
                print(_translate("Command interrupted (Ctrl+C)."))
        process_end_time = time.time()
        duration_sec = process_end_time - process_start_time
        if humanize:
            duration_delta = datetime.timedelta(seconds=duration_sec)
            human_time = humanize.precisedelta(duration_delta)
            if not quiet:
                print(f"🏠 ⬆ Executed ({human_time}) :\n")
        else:
            if not quiet:
                print(f"🏠 ⬆ Executed ({duration_sec:.2f} sec.) :\n")
        if not quiet:
            print(redact_secrets(command))
            print()
        if return_status_and_output_and_command:
            return exit_code, command, output_lines
        if return_status_and_command:
            return exit_code, command
        if return_status_and_output:
            return exit_code, output_lines
        return exit_code

    def _event(self, message):
        """Donne `message` au crochet `events`, s'il est posé ; une erreur
        du crochet ne touche jamais la commande."""
        if self.events is None:
            return
        try:
            self.events(message)
        except Exception:
            pass

    def _job_control_tty(self):
        """Descripteur du terminal de contrôle, ouvert pour une commande
        lancée avec le contrôle de tâches ; None sans `job_control`, hors du
        fil principal (deux fils se disputeraient le premier plan) ou sans
        terminal de contrôle, et la commande tourne alors comme au CLI.
        VSUSP y est désactivé (comme `stty susp undef`) : sans shell pour
        reprendre une tâche suspendue, Ctrl+Z resterait bloqué en position
        arrêtée (état T) jusqu'à raccrocher la session entière."""
        main = threading.current_thread() is threading.main_thread()
        if not self.job_control or not main:
            return None
        try:
            tty = os.open("/dev/tty", os.O_RDWR)
        except OSError:
            return None
        try:
            attrs = termios.tcgetattr(tty)
            attrs[6][termios.VSUSP] = os.fpathconf(tty, "PC_VDISABLE")
            termios.tcsetattr(tty, termios.TCSANOW, attrs)
        except (OSError, termios.error):
            pass  # pas un terminal (tests) : rien à désactiver
        return tty
