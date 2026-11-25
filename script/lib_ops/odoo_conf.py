# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Valider un fichier de configuration d'Odoo comme Odoo le lit, sans le
démarrer.

Odoo n'a pas de commande qui vérifie seulement son fichier : une erreur se
découvre au démarrage, c'est-à-dire après un `systemctl stop`. Ce module
relit le fichier avec les règles d'Odoo 12 à 18 (`odoo/tools/config.py`) :

- `configparser.RawConfigParser` STRICT : une clé donnée deux fois dans une
  section, une section répétée, une ligne hors de toute section ou une
  ligne sans `=` ni `:` font refuser tout le fichier, et Odoo ne démarre
  pas. Seule une ligne qui COMMENCE par `#` ou `;` est un commentaire :
  ce qui suit une valeur reste DANS la valeur ;
- puis la conversion des options typées par optparse : `True`/`False`
  (casse exacte) deviennent des booléens, toute autre valeur d'une option
  entière, décimale ou à choix (`log_level`, `db_sslmode`) passe par le
  convertisseur d'optparse, et une valeur refusée arrête Odoo (« invalid
  integer value », « invalid choice ») ;
- un commentaire après la valeur d'une clé de connexion ou d'écoute
  (`db_host`, `http_interface`…) : Odoo démarre, mais passe la valeur
  telle quelle à PostgreSQL ou au socket et ne peut pas servir ;
- les limites de mémoire, en OCTETS : une valeur écrite en Mo ne laisse
  aucune mémoire au serveur ; la limite douce au-dessus de la dure ; une
  limite douce sous ce qu'occupe un worker au repos ; les limites du
  processus gevent laissées à celles des workers.

`verifier_texte` est pur (texte, version, ressources de la machine) ;
`verifier` lit le fichier et laisse remonter OSError, que l'appelant
traduit en refus. Chaque `Constat` porte un niveau : `error` quand Odoo
refuse le fichier ou ne peut pas servir avec lui, `warning` quand il
démarre en lisant mal une valeur ou avec ses valeurs par défaut, `info`
pour un conseil. Les valeurs des clés qui ressemblent à un secret ne sont
jamais citées, ni le compte et le mot de passe d'une adresse
`schéma://compte:mot@hôte`, quelle que soit la clé.

`conseiller` donne les conseils de workers et de mémoire d'après le nombre
de processeurs et la mémoire de la machine (règles du guide de déploiement
d'Odoo : au plus (2 × CPU) + 1 workers ; un worker léger compte 150 Mo,
un lourd 1 Gio, 80 % / 20 %), et `plan_memoire` les limites par processus
qui tiennent dans la mémoire.

Ce module ne traduit rien : les messages sont des modèles anglais marqués
par `N_()`, que l'outil traduit par sa propre fonction `t`.

Bibliothèque standard seulement, sans syntaxe postérieure à Python 3.7.
"""

from __future__ import annotations

import collections
import configparser
import optparse
import os
import re

ERREUR = "error"
AVERTISSEMENT = "warning"
INFO = "info"
NIVEAUX = (ERREUR, AVERTISSEMENT, INFO)

VERSION_MIN = 12
VERSION_MAX = 18

MO = 1024 * 1024

# Sous ce nombre, une limite de mémoire est presque à coup sûr écrite en
# Mo plutôt qu'en octets : 100 000 octets ne suffisent à aucun processus.
OCTETS_MINIMUM = 100000

# Valeurs par défaut d'Odoo quand la configuration ne pose rien.
DEFAUTS_ODOO = {
    "workers": 0,
    "max_cron_threads": 2,
    "limit_memory_soft": 2048 * MO,
    "limit_memory_hard": 2560 * MO,
}

# Mémoire virtuelle d'un worker au-delà de sa mémoire résidente
# (bibliothèques, réservations), en Mo.
SURCOUT_VIRTUEL_MO = 400
# Mémoire virtuelle d'un worker d'Odoo 16 à 18 au repos, en Mo.
WORKER_AU_REPOS_MO = 700
# limit_memory_soft n'est jamais conseillé sous ce plancher, ni sous
# 1,5 × un worker au repos.
PLANCHER_SOUPLE_MO = 1024
# limit_memory_hard sous lequel plus de mémoire est conseillée : environ
# 1100 Mo de mémoire réelle, ce que prennent un gros rapport, un export ou
# un import.
DURE_CONFORT_MO = 1536
# Limites conseillées du processus gevent : celles des workers par défaut.
GEVENT_SOUPLE_MO = 2048
GEVENT_DURE_MO = 2560

# Options typées d'Odoo lues dans le fichier, présentes de la 12 à la 18.
ENTIERS_COMMUNS = frozenset(
    [
        "http_port",
        "db_port",
        "smtp_port",
        "db_maxconn",
        "workers",
        "max_cron_threads",
        "limit_memory_soft",
        "limit_memory_hard",
        "limit_time_cpu",
        "limit_time_real",
        "limit_time_real_cron",
        "limit_request",
        "osv_memory_count_limit",
    ]
)

# Options typées présentes sur une plage de versions seulement :
# {clé: (type optparse, première version, dernière version)}.
TYPEES_PAR_VERSION = {
    "longpolling_port": ("int", 12, 16),
    "gevent_port": ("int", 16, 18),
    "db_replica_port": ("int", 18, 18),
    "db_maxconn_gevent": ("int", 18, 18),
    "limit_memory_soft_gevent": ("int", 18, 18),
    "limit_memory_hard_gevent": ("int", 18, 18),
    "limit_time_worker_cron": ("int", 18, 18),
    "osv_memory_age_limit": ("float", 12, 17),
    "transient_age_limit": ("float", 14, 18),
    "log_level": ("choice", 12, 18),
    "db_sslmode": ("choice", 12, 18),
}

# Les valeurs admises des options à choix, listes d'Odoo 18
# (`odoo/tools/config.py`) ; optparse refuse toute autre valeur, casse
# comprise.
CHOIX = {
    "log_level": (
        "info",
        "debug_rpc",
        "warn",
        "test",
        "critical",
        "runbot",
        "debug_sql",
        "error",
        "debug",
        "debug_rpc_answer",
        "notset",
    ),
    "db_sslmode": (
        "disable",
        "allow",
        "prefer",
        "require",
        "verify-ca",
        "verify-full",
    ),
}

# Clés texte qu'Odoo passe telles quelles à PostgreSQL ou à `bind` : un
# commentaire gardé dans la valeur empêche de se connecter ou d'écouter.
# `db_password` n'en est pas : un mot de passe peut contenir « # » après
# une espace, et le fichier serait refusé à tort.
CONNEXION = frozenset(
    ["db_host", "db_user", "db_name", "db_replica_host", "http_interface"]
)

# Anciens noms qu'Odoo lit sous le nouveau (`outdated_options_map` de
# `config.load`) : la valeur prend le type du nouveau nom.
ANCIENS_NOMS = {
    "xmlrpc_port": "http_port",
    "xmlrpc_interface": "http_interface",
    "xmlrpc": "http_enable",
}

# Valeurs que `config.load` change en booléens avant toute conversion.
BOOLEENS = ("True", "true", "False", "false")

# Clé dont la valeur n'est jamais citée dans un message.
RE_SECRET = re.compile(r"pass|pwd|secret|token|key|credential|auth|dsn")

# Le compte et le mot de passe d'une adresse (`//compte:mot@`), masqués
# dans toute valeur citée.
RE_COMPTE_URL = re.compile(r"//[^/@\s]*@")

# Un commentaire après une valeur : `#` ou `;` précédé d'une espace.
RE_COMMENTAIRE = re.compile(r"\s[#;]")

RE_VERSION = re.compile(r"\s*(\d+)")
RE_VERSION_CHEMIN = re.compile(r"odoo(1[2-8])\.0")

# Erreurs de structure : configparser refuse le fichier entier.
STRUCTURE = frozenset(
    ["outside", "syntax", "duplicate", "duplicate_section", "syntax_other"]
)


def N_(texte):
    """Marque un modèle de message à traduire par l'outil appelant."""
    return texte


MESSAGES = {
    "no_options": N_(
        "No [options] section: Odoo reads none of these settings and"
        " starts with its defaults."
    ),
    "outside": N_(
        "Line outside any section: configparser refuses the whole file and"
        " Odoo does not start."
    ),
    "syntax": N_(
        "Line without '=' or ':': configparser refuses the whole file and"
        " Odoo does not start."
    ),
    "syntax_other": N_(
        "Refused by configparser ({error}): Odoo does not start."
    ),
    "duplicate": N_(
        "Key given twice (first on line {first}): configparser refuses the"
        " whole file and Odoo does not start."
    ),
    "duplicate_section": N_(
        "Section [{section}] given twice (first on line {first}):"
        " configparser refuses the whole file and Odoo does not start."
    ),
    "inline_typed": N_(
        "Comment after the value: Odoo keeps it in the value ({value}),"
        " refuses it as a number and does not start. Write '{key} ="
        " {clean}' and put the comment on its own line."
    ),
    "inline_choice": N_(
        "Comment after the value: Odoo keeps it in the value ({value}),"
        " refuses it as none of {choices} and does not start. Write '{key} ="
        " {clean}' and put the comment on its own line."
    ),
    "inline_connection": N_(
        "Comment after the value: Odoo keeps it in the value ({value}) and"
        " passes it as is to PostgreSQL or to the listening socket: the"
        " instance cannot connect or listen. Write '{key} = {clean}' and put"
        " the comment on its own line."
    ),
    "inline_text": N_(
        "Comment after the value: Odoo keeps it in the value ({value})."
        " Write '{key} = {clean}' and put the comment on its own line."
    ),
    "int": N_(
        "Integer expected, read {value}: Odoo does not start (invalid"
        " integer value)."
    ),
    "float": N_(
        "Number expected, read {value}: Odoo does not start (invalid"
        " floating-point value)."
    ),
    "choice": N_(
        "One of {choices} expected, read {value}: Odoo does not start"
        " (invalid choice)."
    ),
    "bytes": N_(
        "The value is in bytes: {value} bytes leave Odoo no memory and it"
        " cannot serve (meant {value} MB? {bytes})."
    ),
    "soft_hard": N_(
        "limit_memory_soft ({soft} MB) is above limit_memory_hard ({hard}"
        " MB): the hard limit comes first, a request ends in MemoryError"
        " instead of a recycled worker."
    ),
    "soft_low": N_(
        "limit_memory_soft is {soft} MB: under {floor} MB of virtual memory,"
        " workers are recycled very often, or as soon as they start."
    ),
    "gevent_unset": N_(
        "Not set: the gevent process (bus, live chat) takes the limit of the"
        " workers; suggested: limit_memory_soft_gevent = {soft} and"
        " limit_memory_hard_gevent = {hard}."
    ),
    "old_name": N_("Old name, read by Odoo as {new}."),
    "old_name_conflict": N_(
        "{key} and {new} are both set to different values: Odoo keeps the"
        " one written last ({kept})."
    ),
    "longpolling_ignored": N_(
        "No longer read from Odoo 17: the bus listens on gevent_port ({port})."
    ),
    "longpolling_alias": N_(
        "Deprecated alias of gevent_port in Odoo 16: rename it gevent_port."
    ),
    "version_unknown": N_(
        "Odoo version unknown: only the types common to Odoo 12 to 18 are"
        " checked."
    ),
    "workers0": N_(
        "workers = 0: one threaded process serves every request; with"
        " {cpus} CPU and {memory} MB, about {suggested} workers suit a"
        " production server."
    ),
    "too_many": N_(
        "{workers} workers for {cpus} CPU: at most {best} ((2 x CPU) + 1)."
    ),
    "few": N_(
        "{workers} workers for {cpus} CPU and {memory} MB: up to"
        " {suggested} would fit."
    ),
    "memory_need": N_(
        "{workers} workers and {cron} cron threads need about {need} MB of"
        " RAM; this machine has {memory} MB."
    ),
    "memory_short": N_(
        "{processes} processes do not fit in {memory} MB with"
        " limit_memory_soft of at least {floor} MB: at most {max_workers}"
        " workers, or {ram_needed} MB of memory."
    ),
    "limits": N_(
        "For {workers} workers on {memory} MB, suggested: limit_memory_soft"
        " = {soft_bytes} ({soft} MB), limit_memory_hard = {hard_bytes}"
        " ({hard} MB)."
    ),
}

# Gabarits d'une ligne de constat : avec numéro de ligne et clé, avec l'un
# des deux, ou le message seul.
LIGNE_ET_CLE = N_("line {line}, {key}: {message}")
LIGNE_SEULE = N_("line {line}: {message}")
CLE_SEULE = N_("{key}: {message}")


class Constat:
    """Un constat sur le fichier : `niveau` (ERREUR, AVERTISSEMENT, INFO),
    `ligne` (0 quand il vise le fichier entier), `cle`, `code` stable (clé
    de MESSAGES et du JSON) et les `valeurs` du modèle."""

    def __init__(self, niveau, ligne, cle, code, **valeurs):
        self.niveau = niveau
        self.ligne = ligne
        self.cle = cle
        self.code = code
        self.valeurs = valeurs

    def message(self, t=None):
        modele = MESSAGES[self.code]
        texte = t(modele) if t else modele
        try:
            return texte.format(**self.valeurs)
        except (KeyError, IndexError, ValueError):
            # Une traduction qui nomme une valeur absente rend le modèle
            # brut plutôt que de faire tomber le rapport.
            return texte

    def decrire(self, t=None):
        """« line 12, workers: … », « line 12: … », « workers: … » ou le
        message seul."""
        message = self.message(t)
        if self.ligne and self.cle:
            modele = LIGNE_ET_CLE
        elif self.ligne:
            modele = LIGNE_SEULE
        elif self.cle:
            modele = CLE_SEULE
        else:
            return message
        modele = t(modele) if t else modele
        return modele.format(line=self.ligne, key=self.cle, message=message)

    def json(self):
        return {
            "level": self.niveau,
            "line": self.ligne or None,
            "key": self.cle or None,
            "code": self.code,
            "message": self.message(),
        }

    def __repr__(self):
        return "Constat({!r}, {!r}, {!r}, {!r})".format(
            self.niveau, self.ligne, self.cle, self.code
        )


class Verification:
    """Le résultat d'une validation : `constats` triés (erreurs, puis
    avertissements, puis informations, par ligne), `valeurs` de la section
    [options] telles qu'Odoo les lit, `version` (majeure, ou None)."""

    def __init__(self, chemin, version, constats, valeurs):
        self.chemin = chemin
        self.version = version
        rang = {niveau: i for i, niveau in enumerate(NIVEAUX)}
        self.constats = sorted(
            constats, key=lambda c: (rang[c.niveau], c.ligne)
        )
        self.valeurs = valeurs

    def de_niveau(self, niveau):
        return [c for c in self.constats if c.niveau == niveau]

    def erreurs(self):
        return self.de_niveau(ERREUR)

    def avertissements(self):
        return self.de_niveau(AVERTISSEMENT)

    def infos(self):
        return self.de_niveau(INFO)

    @property
    def refuse(self):
        """True quand Odoo refuserait le fichier ou ne pourrait pas servir
        avec lui."""
        return bool(self.erreurs())

    def compter(self):
        return {niveau: len(self.de_niveau(niveau)) for niveau in NIVEAUX}

    def json(self):
        return {
            "path": self.chemin,
            "odoo_version": self.version,
            "findings": [c.json() for c in self.constats],
            "summary": self.compter(),
        }


# --- Versions ---------------------------------------------------------------


def version_majeure(texte):
    """La version majeure d'Odoo lue dans `texte` (« 18.0 », « 16 »), ou
    None hors de 12 à 18."""
    if isinstance(texte, int):
        nombre = texte
    else:
        trouve = RE_VERSION.match(str(texte or ""))
        if trouve is None:
            return None
        nombre = int(trouve.group(1))
    return nombre if VERSION_MIN <= nombre <= VERSION_MAX else None


def version_du_dossier(dossier):
    """La version du fichier `.odoo-version` d'un checkout ERPLibre, ou
    None."""
    if not dossier:
        return None
    try:
        with open(
            os.path.join(dossier, ".odoo-version"), encoding="utf-8"
        ) as fichier:
            return version_majeure(fichier.read(16))
    except (OSError, UnicodeDecodeError):
        return None


def version_instance(dossier, argv=()):
    """La version d'une instance : le `.odoo-version` de son dossier de
    travail, sinon un chemin `odooNN.0` de sa ligne de commande ; None."""
    version = version_du_dossier(dossier)
    if version:
        return version
    for argument in argv or ():
        trouve = RE_VERSION_CHEMIN.search(str(argument))
        if trouve:
            return int(trouve.group(1))
    return None


def types_options(version):
    """{clé: type optparse} des options typées qu'Odoo `version` lit dans
    son fichier ; avec `version` None, celles des sept versions. Les
    valeurs admises d'un type « choice » sont dans CHOIX."""
    types = dict.fromkeys(ENTIERS_COMMUNS, "int")
    for cle, (genre, premiere, derniere) in TYPEES_PAR_VERSION.items():
        if version is None:
            if premiere == VERSION_MIN and derniere == VERSION_MAX:
                types[cle] = genre
        elif premiere <= version <= derniere:
            types[cle] = genre
    return types


def convertir(genre, valeur, choix=()):
    """La valeur convertie par optparse, comme le fait Odoo, ou None si
    optparse la refuse. `choix` donne les valeurs admises d'un type
    « choice »."""
    if genre == "choice":
        option = optparse.Option("--valeur", type=genre, choices=list(choix))
    else:
        option = optparse.Option("--valeur", type=genre)
    try:
        return optparse.Option.TYPE_CHECKER[genre](option, "valeur", valeur)
    except optparse.OptionValueError:
        return None


# --- Ressources de la machine -------------------------------------------


def ressources_hote(meminfo="/proc/meminfo"):
    """(processeurs, mémoire totale en Mo) de la machine courante ; None
    pour ce qui ne se lit pas. Les processeurs sont ceux que ce processus
    peut utiliser ; les limites d'un cgroup ne sont pas lues."""
    try:
        cpus = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cpus = os.cpu_count()
    memoire = None
    try:
        with open(meminfo, encoding="ascii", errors="replace") as fichier:
            for ligne in fichier:
                if ligne.startswith("MemTotal:"):
                    memoire = int(ligne.split()[1]) // 1024
                    break
    except (OSError, ValueError, IndexError):
        memoire = None
    return cpus or None, memoire or None


# --- Lecture ----------------------------------------------------------------

Entree = collections.namedtuple("Entree", "ligne section cle valeur")


def _masquer(texte):
    """`texte` sans le compte ni le mot de passe d'une adresse."""
    return RE_COMPTE_URL.sub("//***@", texte)


def _citer(cle, valeur):
    """La valeur entre apostrophes, coupée à 80 caractères ; masquée pour
    une clé de secret, sans compte ni mot de passe d'adresse sinon."""
    if RE_SECRET.search(cle or ""):
        return "'***'"
    texte = _masquer(str(valeur).replace("\n", " "))
    if len(texte) > 80:
        texte = texte[:77] + "..."
    return "'" + texte + "'"


def parcourir(texte):
    """(entrées, constats de structure) : chaque option de chaque section
    avec sa ligne et la première ligne de sa valeur, dans l'ordre du
    fichier.

    Suit l'algorithme de `configparser.RawConfigParser._read`, avec ses
    expressions régulières : une ligne plus indentée que la clé qui la
    précède continue sa valeur, une ligne vide ou de commentaire ne coupe
    pas une valeur. Toutes les clés répétées sont relevées, là où
    configparser s'arrête à la première ; une ligne hors section arrête la
    lecture, comme lui."""
    sectcre = configparser.RawConfigParser.SECTCRE
    optcre = configparser.RawConfigParser.OPTCRE
    nonspacecre = configparser.RawConfigParser.NONSPACECRE
    entrees, constats = [], []
    sections, options = {}, {}
    section = None
    option = None
    niveau = 0
    for numero, ligne in enumerate(texte.splitlines(), 1):
        valeur = ligne.strip()
        if not valeur or valeur.startswith(("#", ";")):
            continue
        premier = nonspacecre.search(ligne)
        indentation = premier.start() if premier else 0
        if section is not None and option and indentation > niveau:
            continue
        niveau = indentation
        trouve = sectcre.match(valeur)
        if trouve:
            section = trouve.group("header")
            option = None
            if section in sections and section != "DEFAULT":
                constats.append(
                    Constat(
                        ERREUR,
                        numero,
                        "",
                        "duplicate_section",
                        section=section,
                        first=sections[section],
                    )
                )
            sections.setdefault(section, numero)
            continue
        if section is None:
            constats.append(Constat(ERREUR, numero, "", "outside"))
            break
        trouve = optcre.match(valeur)
        if not trouve or not trouve.group("option").rstrip():
            constats.append(Constat(ERREUR, numero, "", "syntax"))
            if trouve:
                option = ""
            continue
        option = trouve.group("option").rstrip().lower()
        if (section, option) in options:
            constats.append(
                Constat(
                    ERREUR,
                    numero,
                    option,
                    "duplicate",
                    first=options[(section, option)],
                )
            )
        else:
            options[(section, option)] = numero
        entrees.append(
            Entree(
                numero, section, option, (trouve.group("value") or "").strip()
            )
        )
    return entrees, constats


def _valeurs_options(texte):
    """La section [options] telle que configparser la rend (défauts de
    [DEFAULT] compris, dernière valeur d'une clé répétée), et si elle
    existe."""
    parser = configparser.RawConfigParser(strict=False)
    try:
        parser.read_string(texte)
    except configparser.Error:
        pass
    if not parser.has_section("options"):
        return {}, False
    valeurs = {}
    for cle, valeur in parser.items("options"):
        if isinstance(valeur, list):
            valeur = "\n".join(valeur)
        valeurs[cle] = valeur if valeur is not None else ""
    return valeurs, True


def _erreur_configparser(texte, constats):
    """Un constat `syntax_other` quand configparser strict refuse le texte
    sans qu'aucune erreur de structure ne l'ait déjà dit."""
    try:
        configparser.RawConfigParser().read_string(texte)
    except configparser.Error as err:
        if any(c.code in STRUCTURE for c in constats):
            return None
        premiere = (str(err).splitlines() or [type(err).__name__])[0]
        return Constat(
            ERREUR,
            getattr(err, "lineno", 0) or 0,
            "",
            "syntax_other",
            error=premiere[:200],
        )
    return None


# --- Vérification -----------------------------------------------------------


def _lignes_des_options(entrees):
    """{clé: dernière ligne} des options de [options] et de [DEFAULT]."""
    lignes = {}
    for entree in entrees:
        if entree.section in ("options", "DEFAULT"):
            lignes[entree.cle] = entree.ligne
    return lignes


def _types(valeurs, lignes, version):
    """Les constats de type et de commentaire après une valeur."""
    constats = []
    types = types_options(version)
    for cle, valeur in valeurs.items():
        ligne = lignes.get(cle, 0)
        nom = ANCIENS_NOMS.get(cle, cle)
        genre = types.get(nom)
        choix = CHOIX.get(nom, ())
        commentaire = RE_COMMENTAIRE.search(valeur)
        propre = valeur[: commentaire.start()].strip() if commentaire else ""
        propre = "***" if RE_SECRET.search(cle) else _masquer(propre)
        if valeur in BOOLEENS:
            continue
        if genre and convertir(genre, valeur, choix) is None:
            if commentaire:
                constats.append(
                    Constat(
                        ERREUR,
                        ligne,
                        cle,
                        "inline_choice" if choix else "inline_typed",
                        value=_citer(cle, valeur),
                        key=cle,
                        clean=propre,
                        choices=", ".join(choix),
                    )
                )
            else:
                constats.append(
                    Constat(
                        ERREUR,
                        ligne,
                        cle,
                        genre,
                        value=_citer(cle, valeur),
                        choices=", ".join(choix),
                    )
                )
        elif commentaire:
            constats.append(
                Constat(
                    ERREUR if nom in CONNEXION else AVERTISSEMENT,
                    ligne,
                    cle,
                    "inline_connection" if nom in CONNEXION else "inline_text",
                    value=_citer(cle, valeur),
                    key=cle,
                    clean=propre,
                )
            )
    return constats


def _entier(valeurs, cle):
    """La valeur entière de `cle` comme Odoo la convertit, ou None (absente,
    booléen, refusée)."""
    valeur = valeurs.get(cle)
    if valeur is None or valeur in BOOLEENS:
        return None
    return convertir("int", valeur)


def _noms(valeurs, lignes, version):
    """Anciens noms, et `longpolling_port` selon la version."""
    constats = []
    for ancien, nouveau in ANCIENS_NOMS.items():
        if ancien not in valeurs:
            continue
        if nouveau in valeurs and valeurs[nouveau] != valeurs[ancien]:
            garde = (
                ancien
                if lignes.get(ancien, 0) > lignes.get(nouveau, 0)
                else nouveau
            )
            constats.append(
                Constat(
                    AVERTISSEMENT,
                    lignes.get(ancien, 0),
                    ancien,
                    "old_name_conflict",
                    key=ancien,
                    new=nouveau,
                    kept=garde,
                )
            )
        else:
            constats.append(
                Constat(
                    INFO,
                    lignes.get(ancien, 0),
                    ancien,
                    "old_name",
                    new=nouveau,
                )
            )
    if "longpolling_port" in valeurs and version:
        ligne = lignes.get("longpolling_port", 0)
        if version >= 17:
            port = valeurs.get("gevent_port") or "8072"
            constats.append(
                Constat(
                    AVERTISSEMENT,
                    ligne,
                    "longpolling_port",
                    "longpolling_ignored",
                    port=port,
                )
            )
        elif version == 16:
            constats.append(
                Constat(INFO, ligne, "longpolling_port", "longpolling_alias")
            )
    return constats


def _memoire(valeurs, lignes, version):
    """Unités, limite douce et dure, limites du processus gevent."""
    constats = []
    types = types_options(version)
    for cle in (
        "limit_memory_soft",
        "limit_memory_hard",
        "limit_memory_soft_gevent",
        "limit_memory_hard_gevent",
    ):
        if types.get(cle) != "int":
            continue
        nombre = _entier(valeurs, cle)
        if nombre is not None and 0 < nombre < OCTETS_MINIMUM:
            constats.append(
                Constat(
                    ERREUR,
                    lignes.get(cle, 0),
                    cle,
                    "bytes",
                    value=nombre,
                    bytes=nombre * MO,
                )
            )
    souple = _entier(valeurs, "limit_memory_soft")
    dure = _entier(valeurs, "limit_memory_hard")
    workers = _entier(valeurs, "workers") or 0
    if (
        souple
        and dure
        and souple > dure
        and souple >= OCTETS_MINIMUM
        and dure >= OCTETS_MINIMUM
    ):
        constats.append(
            Constat(
                AVERTISSEMENT,
                lignes.get("limit_memory_soft", 0),
                "limit_memory_soft",
                "soft_hard",
                soft=souple // MO,
                hard=dure // MO,
            )
        )
    recent = version is None or version >= 16
    if (
        recent
        and workers > 0
        and souple
        and OCTETS_MINIMUM <= souple < PLANCHER_SOUPLE_MO * MO
    ):
        constats.append(
            Constat(
                AVERTISSEMENT,
                lignes.get("limit_memory_soft", 0),
                "limit_memory_soft",
                "soft_low",
                soft=souple // MO,
                floor=PLANCHER_SOUPLE_MO,
            )
        )
    if workers > 0 and types.get("limit_memory_soft_gevent") == "int":
        absentes = [
            cle
            for cle in ("limit_memory_soft_gevent", "limit_memory_hard_gevent")
            if str(valeurs.get(cle, "")).strip() in ("", "False", "false")
        ]
        if absentes:
            constats.append(
                Constat(
                    INFO,
                    lignes.get(absentes[0], 0),
                    ", ".join(absentes),
                    "gevent_unset",
                    soft=GEVENT_SOUPLE_MO * MO,
                    hard=GEVENT_DURE_MO * MO,
                )
            )
    return constats


PlanMemoire = collections.namedtuple(
    "PlanMemoire",
    "dure souple budget reserve trop plancher max_workers ram_necessaire",
)


def memoire_necessaire(besoin_mo, total_mo, autres_mo=None):
    """La plus petite mémoire (Mo, par pas de 1 Gio) dont la part laissée à
    Odoo par `plan_memoire` tient `besoin_mo` ; `total_mo` quand elle le
    tient déjà."""
    taille = max(total_mo, 1024)
    while (
        taille
        - max(int(taille * 0.15), autres_mo or 0)
        - max(512, taille // 10)
        < besoin_mo
        and taille < 1048576
    ):
        taille += 1024
    return taille


def plan_memoire(total_mo, workers, cron, autres_mo=None):
    """Les limites de mémoire des processus d'Odoo pour `total_mo` Mo.

    La mémoire réelle se partage : une réserve pour ce qui tourne hors
    d'Odoo (au moins 15 %, ou `autres_mo`), une marge de 10 % (au moins
    512 Mo), le reste divisé entre workers + cron + 1 processus gevent. Les
    limites sont en mémoire VIRTUELLE : part réelle + SURCOUT_VIRTUEL_MO.
    limit_memory_soft ne descend jamais sous max(PLANCHER_SOUPLE_MO, 1,5 ×
    un worker au repos) ; quand la mémoire ne le permet pas, `trop` est
    vrai et `max_workers` donne le plus grand nombre qui tient."""
    processus = max(1, workers + cron + 1)
    reserve = max(int(total_mo * 0.15), autres_mo or 0)
    budget = max(0, total_mo - reserve - max(512, total_mo // 10))
    dure = budget // processus + SURCOUT_VIRTUEL_MO
    souple = dure * 85 // 100
    plancher = max(PLANCHER_SOUPLE_MO, WORKER_AU_REPOS_MO * 3 // 2)
    trop = souple < plancher
    if trop:
        souple = plancher
        dure = max(dure, plancher * 6 // 5)
    max_workers = max(
        1, budget // max(1, dure - SURCOUT_VIRTUEL_MO) - cron - 1
    )
    if dure < DURE_CONFORT_MO:
        necessaire = memoire_necessaire(
            processus * max(0, DURE_CONFORT_MO - SURCOUT_VIRTUEL_MO),
            total_mo,
            autres_mo,
        )
    else:
        necessaire = total_mo
    return PlanMemoire(
        dure, souple, budget, reserve, trop, plancher, max_workers, necessaire
    )


def conseiller(valeurs, cpus, memoire_mo, lignes=None):
    """Les conseils de workers et de mémoire pour `cpus` processeurs et
    `memoire_mo` Mo ; [] quand l'un des deux manque."""
    if not cpus or not memoire_mo:
        return []
    lignes = lignes or {}
    ligne = lignes.get("workers", 0)
    constats = []
    workers = _entier(valeurs, "workers")
    workers = DEFAUTS_ODOO["workers"] if workers is None else workers
    cron = _entier(valeurs, "max_cron_threads")
    cron = DEFAUTS_ODOO["max_cron_threads"] if cron is None else cron
    meilleur = 2 * cpus + 1
    borne = (
        plan_memoire(memoire_mo, 1, cron).budget
        // (DURE_CONFORT_MO - SURCOUT_VIRTUEL_MO)
        - cron
        - 1
    )
    conseille = max(1, min(meilleur, borne))
    if workers <= 0:
        constats.append(
            Constat(
                INFO,
                ligne,
                "workers",
                "workers0",
                cpus=cpus,
                memory=memoire_mo,
                suggested=conseille,
            )
        )
        return constats
    if workers > meilleur:
        constats.append(
            Constat(
                AVERTISSEMENT,
                ligne,
                "workers",
                "too_many",
                workers=workers,
                cpus=cpus,
                best=meilleur,
            )
        )
    elif workers < cpus and conseille > workers:
        constats.append(
            Constat(
                INFO,
                ligne,
                "workers",
                "few",
                workers=workers,
                cpus=cpus,
                memory=memoire_mo,
                suggested=conseille,
            )
        )
    besoin = round(workers * (0.8 * 150 + 0.2 * 1024) + cron * 150)
    if besoin > 0.8 * memoire_mo:
        constats.append(
            Constat(
                AVERTISSEMENT,
                ligne,
                "workers",
                "memory_need",
                workers=workers,
                cron=cron,
                need=besoin,
                memory=memoire_mo,
            )
        )
    plan = plan_memoire(memoire_mo, workers, cron)
    processus = workers + cron + 1
    if plan.trop:
        constats.append(
            Constat(
                AVERTISSEMENT,
                ligne,
                "workers",
                "memory_short",
                processes=processus,
                memory=memoire_mo,
                floor=plan.plancher,
                max_workers=plan.max_workers,
                ram_needed=plan.ram_necessaire,
            )
        )
        return constats
    dure = _entier(valeurs, "limit_memory_hard")
    dure_mo = (dure or DEFAUTS_ODOO["limit_memory_hard"]) // MO
    if (dure_mo - SURCOUT_VIRTUEL_MO) * processus > plan.budget:
        constats.append(
            Constat(
                INFO,
                lignes.get("limit_memory_hard", 0),
                "limit_memory_hard",
                "limits",
                workers=workers,
                memory=memoire_mo,
                soft=plan.souple,
                soft_bytes=plan.souple * MO,
                hard=plan.dure,
                hard_bytes=plan.dure * MO,
            )
        )
    return constats


def verifier_texte(texte, version=None, cpus=None, memoire_mo=None, chemin=""):
    """La `Verification` du contenu `texte` d'un fichier de configuration,
    pour Odoo `version` (majeure, ou None : les types communs aux sept
    versions) ; avec `cpus` et `memoire_mo`, les conseils de workers et de
    mémoire s'y ajoutent."""
    version = version_majeure(version) if version is not None else None
    entrees, constats = parcourir(texte)
    autre = _erreur_configparser(texte, constats)
    if autre is not None:
        constats.append(autre)
    valeurs, avec_options = _valeurs_options(texte)
    if not avec_options and not any(c.code == "outside" for c in constats):
        constats.append(Constat(AVERTISSEMENT, 0, "", "no_options"))
    lignes = _lignes_des_options(entrees)
    if version is None:
        constats.append(Constat(INFO, 0, "", "version_unknown"))
    constats += _types(valeurs, lignes, version)
    constats += _noms(valeurs, lignes, version)
    constats += _memoire(valeurs, lignes, version)
    if avec_options:
        constats += conseiller(valeurs, cpus, memoire_mo, lignes)
    return Verification(chemin, version, constats, valeurs)


def lire(chemin):
    """Le texte du fichier, décodé en UTF-8 (octets invalides remplacés).
    OSError remonte : l'appelant dit pourquoi il ne peut pas lire."""
    with open(chemin, "rb") as fichier:
        return fichier.read().decode("utf-8", "replace")


def verifier(chemin, version=None, cpus=None, memoire_mo=None):
    """`verifier_texte` sur le fichier `chemin`. OSError remonte."""
    return verifier_texte(lire(chemin), version, cpus, memoire_mo, chemin)
