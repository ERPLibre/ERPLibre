# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le profil d'une instance : les réglages des outils de production.

Un profil est un fichier JSON, `private/production/<service>.json` du
checkout de l'outil, qui porte pour chaque outil les valeurs qu'il
recevrait sur sa ligne de commande. `analyser` l'applique à un parser
argparse : la ligne de commande gagne toujours, une valeur en conflit est
écartée avec un avertissement, et une ligne de commande valide ne devient
jamais invalide à cause d'un profil.

Le classement des options est explicite : chaque `dest` d'un outil est un
champ (`CHAMPS`), un alias vers le champ d'un autre groupe (`ALIAS`) ou une
exclusion justifiée (`EXCLUSIONS`). Seules les métadonnées (type, choices,
aide, défaut) se lisent dans le parser.

Le profil ne porte aucun secret : un champ secret n'admet qu'une
référence KeePass `{"kdbx": "<chemin>"}` ou le chemin absolu d'un fichier.
Dans une unité qui reçoit le credential du secret
(`$CREDENTIALS_DIRECTORY/<nom>`, voir `credentials.py`), ce fichier passe
avant la ligne de commande et le profil, et rend le secret effectif pour
ses dépendants, même quand le profil n'en porte qu'une référence KeePass.

`RACINE_PROFILS` est la seule couture vers le dossier des profils : `None`
vaut `<racine>/private/production`, et un test y met un dossier temporaire.

Ce module ne traduit rien : les messages sont des modèles anglais marqués
par `N_()`, que l'outil traduit par sa propre fonction `t`.

Bibliothèque standard seulement, sans syntaxe postérieure à Python 3.7.
"""

from __future__ import annotations

import argparse
import collections
import errno
import hashlib
import json
import os
import re
import stat
import sys
import tempfile

from script.lib_ops import credentials, systemd

VERSION = 1

# Taille maximale d'un profil lu : un profil réel tient en quelques Kio.
TAILLE_MAX = 256 * 1024

RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

# Dossier des profils ; `None` vaut `<racine>/private/production`.
RACINE_PROFILS = None

# Dossier où `unites_citant` cherche les unités installées.
DOSSIER_UNITES = "/etc/systemd/system"

RE_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")
RE_SHA256 = re.compile(r"[0-9a-f]{64}")
RE_UNITE_ERPLIBRE = re.compile(r"erplibre-[A-Za-z0-9@_.:-]*\.service")

# Clés de premier niveau qui ne sont pas des groupes.
CLES_DOCUMENT = ("version", "service", "host")

GROUPE_INSTANCE = "instance"
GROUPE_HOTE = "host_perf_audit"


def N_(texte):
    """Marque un modèle de message à traduire par l'outil appelant."""
    return texte


# --- Tables -----------------------------------------------------------------

# Champs (F) de chaque groupe, dans l'ordre du catalogue et de l'écriture.
CHAMPS = collections.OrderedDict(
    [
        (GROUPE_INSTANCE, ("db",)),
        (
            "update_module",
            (
                "timeout",
                "start_wait",
                "ignore_error",
                "log_dir",
                "log_keep_days",
                "warmup_deep",
                "verbose",
                "rollback",
                "pg_service",
            ),
        ),
        (
            "backup",
            (
                "dest",
                "state_dir",
                "keep_daily",
                "keep_weekly",
                "keep_monthly",
                "keep_recent_days",
                "copy_to",
                "max_age",
                "timeout",
                "verbose",
            ),
        ),
        ("backup_timer", ("on_calendar", "randomized_delay", "verbose")),
        (
            "log_check",
            (
                "namespace",
                "days",
                "ignore",
                "state_dir",
                "full_trace",
                "top",
                "timeout",
                "verbose",
            ),
        ),
        ("mail_retry", ("days", "timeout", "verbose")),
        (
            "health_check",
            ("url", "mail_domain", "dkim_selector", "timeout", "verbose"),
        ),
        (
            "warmup",
            (
                "timeout",
                "max_pages",
                "repeat",
                "login",
                "api_key_file",
                "models",
                "strict",
            ),
        ),
        ("odoo_conf", ("cpus", "memory_mb", "verbose")),
        (
            GROUPE_HOTE,
            ("duration", "interval", "no_guests", "top", "verbose"),
        ),
    ]
)

# Alias (A) : la `dest` d'un outil lit le champ d'un autre groupe. Une `dest`
# aliasée n'est jamais une clé de son propre groupe. Un alias vers un champ
# de SECRETS est secret lui aussi (`secrets_du_groupe`).
ALIAS = {
    "update_module": {
        "db": (GROUPE_INSTANCE, "db"),
        "backup_dest": ("backup", "dest"),
        "state_dir": ("backup", "state_dir"),
        "warmup_login": ("warmup", "login"),
        "warmup_key_file": ("warmup", "api_key_file"),
    },
    "backup": {"db": (GROUPE_INSTANCE, "db")},
    "backup_timer": {
        "db": (GROUPE_INSTANCE, "db"),
        "dest": ("backup", "dest"),
        "state_dir": ("backup", "state_dir"),
        "keep_daily": ("backup", "keep_daily"),
        "keep_weekly": ("backup", "keep_weekly"),
        "keep_monthly": ("backup", "keep_monthly"),
        "keep_recent_days": ("backup", "keep_recent_days"),
        "copy_to": ("backup", "copy_to"),
    },
    "mail_retry": {"db": (GROUPE_INSTANCE, "db")},
    "warmup": {"database": (GROUPE_INSTANCE, "db")},
}

# Raisons d'exclusion, affichées par « Afficher le profil ».
RAISONS = {
    "mode": N_("Chosen by the menu entry or the command line at each run"),
    "objet": N_(
        "The object of the action (modules, file, target database),"
        " asked each time"
    ),
    "securite": N_("Bypasses a safeguard: never persisted"),
    "vie_privee": N_("Shows personal data: asked at each run"),
    "format": N_("Output format set by the caller"),
    "identite": N_("Names the instance or is detected from it"),
    "defaut_runsh": N_(
        "Default mode of the warm-up, run by run.sh, never configured"
    ),
    "tests": N_("Test option"),
    "meta": N_("Profile option"),
    "secret_transmis": N_("Secret passed by todo, never written"),
    "aide": N_("Shows the help"),
}

# Exclusions communes à tous les outils : l'aide et les méta-options.
EXCLUSIONS_COMMUNES = {
    "help": "aide",
    "profile": "meta",
    "no_profile": "meta",
    "profile_unset": "meta",
    "profile_required": "meta",
    "profile_sha256": "meta",
}

# Exclusions (X) propres à chaque outil : {dest: code de RAISONS}.
EXCLUSIONS = {
    "update_module": {
        "modules": "objet",
        "service": "identite",
        "odoo_conf": "identite",
        "user": "identite",
        "no_backup": "securite",
        "force": "securite",
        "dry_run": "mode",
        # Remplace les traductions modifiées dans la base : choisi à
        # chaque mise à jour.
        "i18n_overwrite": "mode",
        "restart_only": "mode",
        "update_list": "mode",
        "remove_missing": "securite",
        "yes": "securite",
        # Coupe les sessions de toutes les bases du serveur.
        "restart_postgresql": "securite",
        # L'archive et son dossier : le code apporté par cette exécution.
        "zip": "objet",
        "addons_dir": "objet",
    },
    "backup": {
        "status": "mode",
        "test_restore": "mode",
        "restore": "mode",
        "file": "objet",
        "into": "objet",
        "service": "identite",
        "odoo_conf": "identite",
        "user": "identite",
        "force_space": "securite",
        "dry_run": "mode",
    },
    "backup_timer": {
        "uninstall": "mode",
        "service": "identite",
        "odoo_conf": "identite",
        "user": "identite",
        "root": "tests",
        "dry_run": "mode",
        "credential": "secret_transmis",
    },
    "log_check": {
        "service": "identite",
        "file": "objet",
        "since_last": "mode",
        "last": "mode",
        "since": "mode",
        "by_hour": "mode",
        "until": "objet",
        "json": "format",
    },
    "mail_retry": {
        "service": "identite",
        "odoo_conf": "identite",
        "user": "identite",
        "details": "vie_privee",
        "resend": "objet",
        "yes": "securite",
        "list": "mode",
        "dry_run": "mode",
        "json": "format",
    },
    "health_check": {"local": "mode", "service": "identite", "json": "format"},
    "warmup": {
        "config": "defaut_runsh",
        "log": "defaut_runsh",
        "quiet": "defaut_runsh",
        "odoo_args": "defaut_runsh",
        "deep": "mode",
        "local": "mode",
        "url": "objet",
        "service": "identite",
    },
    "odoo_conf": {
        "file": "objet",
        "service": "identite",
        "odoo_version": "identite",
        "json": "format",
    },
    GROUPE_HOTE: {"csv": "format", "json": "format", "root": "tests"},
}

# Champs secrets : {(groupe, clé): nom du credential et de l'entrée
# KeePass}. L'entrée porte la clé elle-même, pas un fichier.
SECRETS = {("warmup", "api_key_file"): "warmup.api_key"}

# Noms qui ressemblent à un secret sans en être un : {(groupe, dest):
# raison}. `--copy-to`, les URL et les domaines n'y figurent pas, leur nom
# ne correspond pas à `GARDE_SECRETS`.
NON_SECRETS = {}

# Toute `dest` qui correspond est dans SECRETS, NON_SECRETS ou exclue.
GARDE_SECRETS = re.compile(r"key|token|password|secret|credential")

# Toute `dest` qui correspond à un geste dangereux est exclue, ou dans
# ANODINS avec une raison.
GARDE_DANGER = re.compile(
    r"force|yes|^no_|apply|restart|uninstall|restore|resend|drop|delete"
    r"|remove|purge|zip|trim|preload|with_db|details"
)

ANODINS = {
    (GROUPE_HOTE, "no_guests"): N_("Narrows a read-only measurement"),
}

# Le dépendant (clé) n'est retenu que si sa dépendance (valeur) a une valeur
# effective : ligne de commande, ou valeur retenue du profil. `login` et
# `api_key_file` vont ensemble dans les deux sens : warmup refuse l'un sans
# l'autre, donc la moitié d'une paire sans son partenaire est écartée.
DEPENDANCES = {
    ("warmup", "login"): ("warmup", "api_key_file"),
    ("warmup", "api_key_file"): ("warmup", "login"),
    ("health_check", "dkim_selector"): ("health_check", "mail_domain"),
}

Conflit = collections.namedtuple("Conflit", "groupe dest presents raison")

# Une valeur du profil écartée dès que toutes les `dest` de `presents` sont
# sur la ligne de commande : l'outil refuserait la combinaison, ou la valeur
# changerait le sens du geste choisi.
CONFLITS = (
    Conflit(
        "log_check",
        "namespace",
        ("file",),
        N_("--namespace cannot be combined with --file"),
    ),
    Conflit("backup", "db", ("status",), N_("--status lists every database")),
    # `--resend` renvoie ce que liste `--days` : une fenêtre persistée
    # élargirait en silence un geste irréversible.
    Conflit(
        "mail_retry",
        "days",
        ("resend",),
        N_("--resend selects from the list: give --days explicitly"),
    ),
    # Le retour git ne suit qu'une mise à jour avec sauvegarde ; l'archive
    # apporte sa propre copie.
    Conflit(
        "update_module",
        "rollback",
        ("restart_only",),
        N_("--rollback goes with an update"),
    ),
    Conflit(
        "update_module",
        "rollback",
        ("update_list",),
        N_("--rollback goes with an update"),
    ),
    Conflit(
        "update_module",
        "rollback",
        ("remove_missing",),
        N_("--rollback goes with an update"),
    ),
    Conflit(
        "update_module",
        "rollback",
        ("zip",),
        N_("--zip brings its own copy of the code"),
    ),
    Conflit(
        "update_module",
        "rollback",
        ("no_backup",),
        N_("the rollback restores the database from the backup"),
    ),
)

# Champs qui exigent un chemin absolu dans le profil : sans `type`, l'outil
# les résout par `os.path.abspath`, donc contre un cwd qui change d'un
# lancement à l'autre.
CHEMINS = frozenset(
    [
        ("update_module", "log_dir"),
        ("backup", "dest"),
        ("backup", "state_dir"),
        ("log_check", "state_dir"),
        ("warmup", "api_key_file"),
    ]
)

# Bornes du profil, plus strictes que la ligne de commande : {(groupe,
# clé): (minimum, maximum)}, `None` sans borne. Une rétention à 0 ne garde
# que la plus récente : elle reste possible sur la ligne de commande.
BORNES = {
    ("backup", "keep_daily"): (1, None),
    ("backup", "max_age"): (None, 168),
}

# La rétention du profil seul (valeurs du profil retenues, défauts de
# l'outil pour les autres) garde au moins `minimum` sauvegardes.
BORNE_SOMME = (
    "backup",
    ("keep_daily", "keep_weekly", "keep_monthly", "keep_recent_days"),
    2,
)

# Champs de motifs d'expression régulière : un motif du profil qui trouve la
# chaîne vide ou une ligne générique masquerait toute erreur.
MOTIFS = frozenset(
    [("update_module", "ignore_error"), ("log_check", "ignore")]
)

# Lignes génériques : les en-têtes d'enregistrement et les titres de trace
# (ligne d'exception finale), les deux textes où `journal.Analyse` cherche
# un motif `--ignore`.
GENERIQUES = (
    "2026-01-01 00:00:00,000 4242 ERROR exemple_db odoo.x: y",
    "2026-01-01 00:00:00,000 4242 CRITICAL exemple_db odoo.x: y",
    "ValueError: y",
    "KeyError: 'y'",
    "psycopg2.errors.UniqueViolation: y",
)

# Champs fixés à l'installation d'une minuterie ; les autres sont lus par
# l'outil à chaque passage.
INSTALLATION = frozenset(
    [
        (GROUPE_INSTANCE, "db"),
        ("backup", "dest"),
        ("backup", "state_dir"),
        ("backup", "copy_to"),
        ("backup_timer", "on_calendar"),
        ("backup_timer", "randomized_delay"),
    ]
)


def _toujours(presents):
    return True


def _jamais(presents):
    return False


def _sans_status(presents):
    return "status" not in presents


def _sans_file(presents):
    return "file" not in presents


def _avec_local(presents):
    return "local" in presents


Outil = collections.namedtuple(
    "Outil", "groupe module entree argv_minimal avec_service"
)

# `argv_minimal` suffit pour valider un profil ; `avec_service(presents)`
# dit si l'outil, avec les `dest` présentes, vise une unité systemd.
OUTILS = (
    Outil(
        "update_module",
        "script.odoo.update_module",
        "analyser",
        ("--module", "all", "--dry-run"),
        _toujours,
    ),
    Outil(
        "backup",
        "script.database.odoo_backup",
        "analyser",
        ("--dry-run",),
        _sans_status,
    ),
    Outil(
        "backup_timer",
        "script.systemd.install_backup_timer",
        "analyser",
        ("--dry-run",),
        _toujours,
    ),
    Outil(
        "log_check",
        "script.odoo.log_check",
        "analyser",
        ("--since-last",),
        _sans_file,
    ),
    Outil(
        "mail_retry",
        "script.odoo.mail_retry",
        "analyser",
        ("--list",),
        _toujours,
    ),
    Outil(
        "health_check",
        "script.odoo.health_check",
        "analyser",
        ("--local",),
        _avec_local,
    ),
    Outil(
        "warmup",
        "script.odoo.warmup_http",
        "analyser_profond",
        ("--deep", "--local"),
        _avec_local,
    ),
    Outil(
        "odoo_conf",
        "script.odoo.odoo_conf_check",
        "analyser",
        (),
        _sans_file,
    ),
    Outil(
        GROUPE_HOTE,
        "script.proxmox.host_perf_audit",
        "lire_arguments",
        (),
        _jamais,
    ),
)


def secrets_du_groupe(groupe):
    """[(dest, (groupe du champ, clé), nom du credential)] des secrets que
    lit l'outil `groupe` : ses champs de SECRETS, puis ses alias vers un
    champ de SECRETS, dans l'ordre des tables."""
    resultat = [
        (cle, (groupe_secret, cle), nom)
        for (groupe_secret, cle), nom in SECRETS.items()
        if groupe_secret == groupe and cle in CHAMPS.get(groupe, ())
    ]
    for dest, cible in ALIAS.get(groupe, {}).items():
        if cible in SECRETS:
            resultat.append((dest, cible, SECRETS[cible]))
    return resultat


def outil(groupe):
    """L'`Outil` du groupe. KeyError s'il n'existe pas."""
    for candidat in OUTILS:
        if candidat.groupe == groupe:
            return candidat
    raise KeyError(groupe)


def exclusions(groupe):
    """{dest: code de raison} des exclusions du groupe, communes comprises."""
    resultat = dict(EXCLUSIONS_COMMUNES)
    resultat.update(EXCLUSIONS.get(groupe, {}))
    return resultat


def classer(groupe, dest):
    """ "F", "A", "X" ou None (option non classée)."""
    if dest in CHAMPS.get(groupe, ()):
        return "F"
    if dest in ALIAS.get(groupe, {}):
        return "A"
    if dest in exclusions(groupe):
        return "X"
    return None


def portee(groupe, cle):
    """ "installation" ou "direct" (voir `INSTALLATION`)."""
    return "installation" if (groupe, cle) in INSTALLATION else "direct"


# --- Erreurs ----------------------------------------------------------------


class ErreurProfil(Exception):
    """Un profil refusé : `modele` (anglais), ses `valeurs`, et la `cle`
    `groupe.cle` en cause quand il y en a une.

    `str()` rend le message anglais formé ; `message(t)` le rend traduit.
    Pour un champ secret, ni le modèle ni les valeurs ne citent la valeur.
    """

    def __init__(self, modele, cle=None, **valeurs):
        self.modele = modele
        self.cle = cle
        self.valeurs = valeurs
        super().__init__(modele.format(**valeurs) if valeurs else modele)

    def message(self, t=None):
        texte = t(self.modele) if t else self.modele
        return texte.format(**self.valeurs) if self.valeurs else texte


class ProfilIllisible(ErreurProfil):
    """Un profil que ce compte n'a pas le droit d'ouvrir (EACCES, EPERM)."""


# --- Catalogue --------------------------------------------------------------

Champ = collections.namedtuple(
    "Champ",
    "groupe cle dest option genre type choices defaut aide metavar secret"
    " depend_de portee action",
)

Kdbx = collections.namedtuple("Kdbx", "reference")


def genre(action):
    """`bool_vrai`, `bool_faux`, `valeur`, `liste_append` ou `liste_nargs`.

    ValueError pour une action qu'un profil ne sait pas porter (compteur,
    constante)."""
    if isinstance(action, argparse._StoreTrueAction):
        return "bool_vrai"
    if isinstance(action, argparse._StoreFalseAction):
        return "bool_faux"
    if isinstance(action, argparse._AppendAction):
        return "liste_append"
    if type(action) is argparse._StoreAction:
        if action.nargs in ("+", "*") or isinstance(action.nargs, int):
            return "liste_nargs"
        if action.nargs in (None, "?"):
            return "valeur"
    raise ValueError(action.dest)


def option(action):
    """La plus longue des `option_strings`, ou la `dest` d'un positionnel."""
    if not action.option_strings:
        return action.dest
    return max(action.option_strings, key=len)


def _actions(parser):
    """{dest: action} des actions du parser."""
    return {action.dest: action for action in parser._actions}


def _champ(action, groupe, cle):
    aide = action.help if action.help not in (None, argparse.SUPPRESS) else ""
    return Champ(
        groupe=groupe,
        cle=cle,
        dest=action.dest,
        option=option(action),
        genre=genre(action),
        type=action.type,
        choices=action.choices,
        defaut=action.default,
        aide=aide,
        metavar=action.metavar,
        secret=(groupe, cle) in SECRETS,
        depend_de=DEPENDANCES.get((groupe, cle)),
        portee=portee(groupe, cle),
        action=action,
    )


def champs(parser, groupe):
    """Les `Champ` des champs F du groupe, dans l'ordre de `CHAMPS`.

    Les métadonnées viennent du parser ; une `dest` de `CHAMPS` absente du
    parser est sautée (le méta-test la signale)."""
    actions = _actions(parser)
    return [
        _champ(actions[dest], groupe, dest)
        for dest in CHAMPS.get(groupe, ())
        if dest in actions
    ]


def alias(parser, groupe):
    """Les `Champ` des alias du groupe : `groupe`/`cle` nomment le champ
    cible, `dest`/`action` l'option de l'outil."""
    actions = _actions(parser)
    return [
        _champ(actions[dest], cible[0], cible[1])
        for dest, cible in ALIAS.get(groupe, {}).items()
        if dest in actions
    ]


def catalogue(parseurs):
    """{groupe: [Champ]} pour les parsers `parseurs` ({groupe: parser}),
    dans l'ordre de `CHAMPS`. `instance` prend les métadonnées du parser
    de `backup`."""
    resultat = collections.OrderedDict()
    for groupe in CHAMPS:
        source = "backup" if groupe == GROUPE_INSTANCE else groupe
        if source in parseurs:
            resultat[groupe] = champs(parseurs[source], groupe)
    return resultat


# --- Conversion -------------------------------------------------------------


def _scalaire(brut):
    return isinstance(brut, (str, int, float)) and not isinstance(brut, bool)


def _appeler_type(champ, texte):
    """`action.type(texte)` et `choices`, comme argparse. ErreurProfil."""
    fonction = champ.type
    cle = f"{champ.groupe}.{champ.cle}"
    if RE_CONTROLE.search(texte):
        raise ErreurProfil(N_("control character in a key or a value"), cle)
    try:
        converti = fonction(texte) if callable(fonction) else texte
    except argparse.ArgumentTypeError as err:
        if champ.secret:
            raise ErreurProfil(N_("invalid value (not shown)"), cle)
        # Message déjà traduit par l'outil : il sert de modèle tel quel.
        raise ErreurProfil(str(err), cle)
    except (TypeError, ValueError):
        if champ.secret:
            raise ErreurProfil(N_("invalid value (not shown)"), cle)
        raise ErreurProfil(N_("invalid value: {value}"), cle, value=texte)
    if champ.choices is not None and converti not in champ.choices:
        if champ.secret:
            raise ErreurProfil(N_("invalid value (not shown)"), cle)
        raise ErreurProfil(
            N_("invalid choice: {value} (choose from {choices})"),
            cle,
            value=texte,
            choices=", ".join(str(c) for c in champ.choices),
        )
    return converti


def _motif_trop_large(motif):
    if not hasattr(motif, "search"):
        motif = re.compile(motif)
    return motif.search("") is not None or any(
        motif.search(ligne) for ligne in GENERIQUES
    )


def _forme_secret(brut, cle):
    """Contrôle la forme d'un champ secret : `{"kdbx": <référence>}`, une
    seule clé, référence non vide sans caractère de contrôle, ou un chemin
    absolu (str). Rend `Kdbx(reference)` ou le chemin. Lève ErreurProfil
    sans citer la valeur. Partagé par la lecture (`convertir`) et
    l'écriture (`verifier_ecriture`)."""
    if isinstance(brut, dict):
        if (
            list(brut) == ["kdbx"]
            and isinstance(brut["kdbx"], str)
            and brut["kdbx"].strip()
            and not RE_CONTROLE.search(brut["kdbx"])
        ):
            return Kdbx(brut["kdbx"])
    elif isinstance(brut, str) and os.path.isabs(brut):
        return brut
    raise ErreurProfil(
        N_("a secret is a KeePass reference (kdbx) or an absolute file path"),
        cle,
    )


def convertir(champ, brut):
    """La valeur `brut` du profil convertie comme argparse le ferait, puis
    soumise aux règles du profil (`CHEMINS`, `BORNES`, `MOTIFS`, forme des
    secrets). Rend la valeur convertie, ou `Kdbx(reference)` pour un
    secret rangé dans KeePass. Lève ErreurProfil, dont le message ne cite
    jamais la valeur d'un champ secret."""
    cle = f"{champ.groupe}.{champ.cle}"
    if champ.secret and isinstance(_forme_secret(brut, cle), Kdbx):
        return Kdbx(brut["kdbx"])
    if champ.genre in ("bool_vrai", "bool_faux"):
        if not isinstance(brut, bool):
            raise ErreurProfil(N_("expected true or false"), cle)
        return brut if champ.genre == "bool_vrai" else not brut
    if champ.genre in ("liste_append", "liste_nargs"):
        if not isinstance(brut, list):
            raise ErreurProfil(N_("expected a list"), cle)
        if not all(_scalaire(element) for element in brut):
            raise ErreurProfil(N_("expected a string or a number"), cle)
        if champ.genre == "liste_nargs" and champ.action.nargs == "+":
            if not brut:
                raise ErreurProfil(N_("expected at least one value"), cle)
        converti = [_appeler_type(champ, str(element)) for element in brut]
        if (champ.groupe, champ.cle) in MOTIFS:
            for element in converti:
                if _motif_trop_large(element):
                    raise ErreurProfil(
                        N_("pattern too broad: it matches every log line"),
                        cle,
                    )
        return converti
    if not _scalaire(brut):
        raise ErreurProfil(N_("expected a string or a number"), cle)
    texte = str(brut)
    if (champ.groupe, champ.cle) in CHEMINS and not os.path.isabs(texte):
        raise ErreurProfil(
            N_("expected an absolute path: {value}"), cle, value=texte
        )
    converti = _appeler_type(champ, texte)
    borne = BORNES.get((champ.groupe, champ.cle))
    if borne is not None:
        minimum, maximum = borne
        if minimum is not None and converti < minimum:
            raise ErreurProfil(
                N_("expected {minimum} or more in a profile: {value}"),
                cle,
                minimum=minimum,
                value=texte,
            )
        if maximum is not None and converti > maximum:
            raise ErreurProfil(
                N_("expected {maximum} or less in a profile: {value}"),
                cle,
                maximum=maximum,
                value=texte,
            )
    return converti


def verifier_somme(doc_groupe, defauts):
    """Applique `BORNE_SOMME` au groupe `backup` d'un profil : la somme des
    `keep_*` du profil, défauts `defauts` ({clé: valeur}) pour les absentes,
    atteint le minimum. Sans aucun `keep_*` dans le profil, rien n'est
    vérifié. Une valeur non entière est laissée à `convertir`. Lève
    ErreurProfil."""
    groupe, cles, minimum = BORNE_SOMME
    if not any(cle in doc_groupe for cle in cles):
        return
    total = 0
    for cle in cles:
        valeur = doc_groupe.get(cle, defauts.get(cle))
        if isinstance(valeur, bool):
            return
        if isinstance(valeur, str):
            try:
                valeur = int(valeur)
            except ValueError:
                return
        if not isinstance(valeur, int):
            return
        total += valeur
    if total < minimum:
        raise ErreurProfil(
            N_(
                "the keep_* settings must keep at least {minimum} backups"
                " in all: {total}"
            ),
            f"{groupe}.keep_*",
            minimum=minimum,
            total=total,
        )


# --- Lecture, écriture ------------------------------------------------------

Lu = collections.namedtuple("Lu", "doc empreinte chemin")


def racine_profils(racine=None):
    """Le dossier des profils : `RACINE_PROFILS`, sinon
    `<racine>/private/production` (`racine` : le checkout de l'outil)."""
    if RACINE_PROFILS is not None:
        return RACINE_PROFILS
    return os.path.join(racine or RACINE, "private", "production")


def chemin_profil(service, racine=None):
    """`<racine des profils>/<service>.json`."""
    return os.path.join(racine_profils(racine), f"{service}.json")


def _uid_outil():
    """Le propriétaire des fichiers de ce checkout."""
    return os.stat(os.path.abspath(__file__)).st_uid


def _proprietaires_admis():
    """Sous root : root, le propriétaire du checkout, et l'appelant de
    sudo (`SUDO_UID`)."""
    admis = {0, _uid_outil()}
    sudo = os.environ.get("SUDO_UID", "")
    if sudo.isdigit():
        admis.add(int(sudo))
    return admis


def _sous(chemin, racine):
    """True si `chemin` (résolu) reste sous `racine`. Seul le parent de la
    racine est résolu : un dossier des profils remplacé par un lien sort de
    la racine."""
    racine = os.path.abspath(racine)
    base = os.path.join(
        os.path.realpath(os.path.dirname(racine)), os.path.basename(racine)
    )
    return os.path.realpath(chemin).startswith(base + os.sep)


def _sans_controle(valeur, cle=""):
    """Lève ErreurProfil sur un caractère de contrôle dans une clé, une
    chaîne ou un élément de liste ; `cle` nomme l'endroit, jamais la
    valeur."""
    if isinstance(valeur, str):
        if RE_CONTROLE.search(valeur):
            raise ErreurProfil(
                N_("control character in a key or a value"), cle or None
            )
    elif isinstance(valeur, dict):
        for nom, sous_valeur in valeur.items():
            ici = f"{cle}.{nom}" if cle else str(nom)
            if RE_CONTROLE.search(str(nom)):
                raise ErreurProfil(
                    N_("control character in a key or a value"), cle or None
                )
            _sans_controle(sous_valeur, ici)
    elif isinstance(valeur, list):
        for element in valeur:
            _sans_controle(element, cle)


def _constante(nom):
    raise ValueError(nom)


def lire(chemin, sous_racine=None):
    """Lit le profil `chemin` et rend `Lu(doc, empreinte, chemin)`.

    Refuse (ErreurProfil) : un lien symbolique en dernier composant
    (`O_NOFOLLOW`), un fichier non régulier ou inscriptible par tous, plus
    de `TAILLE_MAX` octets, autre chose qu'un objet JSON, un caractère de
    contrôle. Sous euid 0, refuse aussi un fichier ou un dossier
    inscriptible par son groupe, un propriétaire hors
    `_proprietaires_admis()`, et, avec `sous_racine` (profil découvert), un
    chemin résolu qui sort de `sous_racine`. `empreinte` est le sha256 des
    octets lus."""
    try:
        fd = os.open(chemin, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        raise ErreurProfil(N_("file not found"))
    except OSError as err:
        if os.path.islink(chemin):
            raise ErreurProfil(N_("symbolic link refused"))
        if err.errno in (errno.EACCES, errno.EPERM):
            raise ProfilIllisible(
                N_("cannot read: {error}"), error=err.strerror
            )
        raise ErreurProfil(N_("cannot read: {error}"), error=err.strerror)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ErreurProfil(N_("not a regular file"))
        if info.st_mode & stat.S_IWOTH:
            raise ErreurProfil(N_("writable by every account: refused"))
        if os.geteuid() == 0:
            if info.st_mode & stat.S_IWGRP:
                raise ErreurProfil(
                    N_("writable by its group: refused under root")
                )
            dossier = os.stat(os.path.dirname(os.path.abspath(chemin)))
            if dossier.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise ErreurProfil(
                    N_(
                        "its directory is writable by its group or by every"
                        " account: refused under root"
                    )
                )
            if info.st_uid not in _proprietaires_admis():
                raise ErreurProfil(
                    N_("owned by uid {uid}: refused under root"),
                    uid=info.st_uid,
                )
            if sous_racine is not None and not _sous(chemin, sous_racine):
                raise ErreurProfil(
                    N_("outside {root}: refused under root"), root=sous_racine
                )
        morceaux = []
        taille = 0
        while taille <= TAILLE_MAX:
            bloc = os.read(fd, 65536)
            if not bloc:
                break
            morceaux.append(bloc)
            taille += len(bloc)
    finally:
        os.close(fd)
    if taille > TAILLE_MAX:
        raise ErreurProfil(
            N_("larger than {size} KiB"), size=TAILLE_MAX // 1024
        )
    octets = b"".join(morceaux)
    try:
        texte = octets.decode("utf-8")
    except UnicodeDecodeError:
        raise ErreurProfil(N_("not UTF-8"))
    try:
        doc = json.loads(texte, parse_constant=_constante)
    except ValueError as err:
        raise ErreurProfil(N_("invalid JSON: {error}"), error=str(err))
    if not isinstance(doc, dict):
        raise ErreurProfil(N_("a JSON object is expected"))
    _sans_controle(doc)
    return Lu(doc, hashlib.sha256(octets).hexdigest(), chemin)


def valider_document(doc, chemin, hote=False):
    """Contrôles du document entier : `version` entière ≤ VERSION, chaque
    groupe connu est un objet, et `service` égal au nom du fichier sans
    `.json` (sauf profil d'hôte, `hote`). Lève ErreurProfil."""
    version = doc.get("version")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version < 1
    ):
        raise ErreurProfil(
            N_("invalid version: {version}"), "version", version=version
        )
    if version > VERSION:
        raise ErreurProfil(
            N_("profile written by a newer ERPLibre (version {version})"),
            "version",
            version=version,
        )
    for groupe in CHAMPS:
        if groupe in doc and not isinstance(doc[groupe], dict):
            raise ErreurProfil(N_("a group is a JSON object"), groupe)
    if hote:
        return
    service = doc.get("service")
    nom = os.path.basename(chemin)
    if nom.endswith(".json"):
        nom = nom[: -len(".json")]
    if not isinstance(service, str) or service != nom:
        raise ErreurProfil(
            N_("the service {service} does not match the file name"),
            "service",
            service=service,
        )
    try:
        systemd.nom_unite(service)
    except ValueError:
        raise ErreurProfil(
            N_("invalid service name: {name}"), "service", name=service
        )


def verifier_ecriture(doc):
    """Contrôle un document avant `ecrire` : version, `service` ou `host`,
    groupes et clés connus seulement (une `dest` aliasée n'est pas une clé
    de son propre groupe), valeurs JSON simples ou listes, forme des
    secrets, aucun caractère de contrôle. Les types fins se vérifient par
    `convertir`. Lève ErreurProfil."""
    if not isinstance(doc, dict):
        raise ErreurProfil(N_("a JSON object is expected"))
    _sans_controle(doc)
    if doc.get("version") != VERSION or isinstance(doc.get("version"), bool):
        raise ErreurProfil(
            N_("invalid version: {version}"),
            "version",
            version=doc.get("version"),
        )
    if not isinstance(doc.get("service", doc.get("host")), str):
        raise ErreurProfil(N_("the service is missing"), "service")
    for groupe, valeurs in doc.items():
        if groupe in CLES_DOCUMENT:
            continue
        if groupe not in CHAMPS:
            raise ErreurProfil(N_("unknown key"), groupe)
        if not isinstance(valeurs, dict):
            raise ErreurProfil(N_("a group is a JSON object"), groupe)
        for cle, brut in valeurs.items():
            ici = f"{groupe}.{cle}"
            if cle not in CHAMPS[groupe]:
                raise ErreurProfil(N_("unknown key"), ici)
            if (groupe, cle) in SECRETS:
                _forme_secret(brut, ici)
            elif isinstance(brut, list):
                if not all(_scalaire(element) for element in brut):
                    raise ErreurProfil(
                        N_("expected a string or a number"), ici
                    )
            elif not (_scalaire(brut) or isinstance(brut, bool)):
                raise ErreurProfil(N_("expected a string or a number"), ici)


def _ordonner(doc):
    """Le document avec ses clés dans l'ordre du catalogue."""
    resultat = collections.OrderedDict()
    for cle in CLES_DOCUMENT:
        if cle in doc:
            resultat[cle] = doc[cle]
    for groupe, cles in CHAMPS.items():
        if groupe in doc:
            resultat[groupe] = collections.OrderedDict(
                (cle, doc[groupe][cle]) for cle in cles if cle in doc[groupe]
            )
    return resultat


def empreinte_fichier(chemin):
    """Le sha256 du fichier, ou "" s'il n'existe pas."""
    try:
        with open(chemin, "rb") as fichier:
            return hashlib.sha256(fichier.read()).hexdigest()
    except FileNotFoundError:
        return ""


def _creer_dossiers(dossier):
    """Crée `dossier` et ses parents manquants, chacun en 0755 malgré
    l'umask : le compte d'une unité doit pouvoir traverser le chemin."""
    manquants = []
    courant = os.path.abspath(dossier)
    while not os.path.isdir(courant):
        manquants.append(courant)
        courant = os.path.dirname(courant)
    for chemin in reversed(manquants):
        try:
            os.mkdir(chemin, 0o755)
        except FileExistsError:
            continue
        os.chmod(chemin, 0o755)


def ecrire(chemin, doc, empreinte_attendue=None):
    """Écrit le profil `doc` dans `chemin`, de façon atomique ; rend
    l'empreinte du fichier écrit.

    Le document est contrôlé par `verifier_ecriture` et écrit dans l'ordre
    du catalogue. Un fichier temporaire du même dossier reçoit le JSON,
    est synchronisé, passe en 0644 puis remplace `chemin` ; le dossier est
    ensuite synchronisé. Un échec laisse l'ancien fichier intact.

    `empreinte_attendue` est le verrou optimiste : le sha256 lu à
    l'ouverture ("" pour un fichier qui n'existait pas). Un fichier changé
    entre-temps lève ErreurProfil et rien n'est écrit. `None` ne vérifie
    rien."""
    verifier_ecriture(doc)
    if empreinte_attendue is not None:
        if empreinte_fichier(chemin) != empreinte_attendue:
            raise ErreurProfil(N_("modified elsewhere: reload it"))
    dossier = os.path.dirname(os.path.abspath(chemin))
    _creer_dossiers(dossier)
    texte = json.dumps(_ordonner(doc), indent=2, ensure_ascii=False) + "\n"
    octets = texte.encode("utf-8")
    fd, temporaire = tempfile.mkstemp(
        prefix=".profil-", suffix=".tmp", dir=dossier
    )
    try:
        try:
            donnees = octets
            while donnees:
                donnees = donnees[os.write(fd, donnees) :]
            os.fsync(fd)
            os.fchmod(fd, 0o644)
        finally:
            os.close(fd)
        os.replace(temporaire, chemin)
    except BaseException:
        try:
            os.unlink(temporaire)
        except OSError:
            pass
        raise
    fd_dossier = os.open(dossier, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd_dossier)
    finally:
        os.close(fd_dossier)
    return hashlib.sha256(octets).hexdigest()


def unites_citant(chemin, dossier=None):
    """Les unités `erplibre-*.service` de `dossier` (`DOSSIER_UNITES`) dont
    le texte cite `chemin` comme un mot entier, triées. Lecture sans sudo :
    une unité illisible est sautée."""
    dossier = dossier or DOSSIER_UNITES
    motif = re.compile(
        r"(?<![^\s\"'=])"
        + re.escape(os.path.abspath(chemin))
        + r"(?![^\s\"'])"
    )
    try:
        noms = sorted(os.listdir(dossier))
    except OSError:
        return []
    trouvees = []
    for nom in noms:
        if not RE_UNITE_ERPLIBRE.fullmatch(nom):
            continue
        try:
            with open(os.path.join(dossier, nom), encoding="utf-8") as f:
                texte = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        if motif.search(texte):
            trouvees.append(nom)
    return trouvees


# --- Application à un parser ------------------------------------------------

META = (
    (
        "--profile",
        dict(
            dest="profile",
            metavar="FILE",
            help=N_(
                "Profile (JSON) of the instance; default:"
                " private/production/<service>.json of this checkout."
            ),
        ),
    ),
    (
        "--no-profile",
        dict(
            dest="no_profile",
            action="store_true",
            help=N_("Read no profile."),
        ),
    ),
    (
        "--profile-unset",
        dict(
            dest="profile_unset",
            action="append",
            metavar="NAME",
            help=N_(
                "Ignore this setting of the profile (e.g. keep-daily);"
                " repeatable."
            ),
        ),
    ),
    (
        "--profile-required",
        dict(
            dest="profile_required",
            action="store_true",
            help=N_("Fail (code 2) when no profile is found."),
        ),
    ),
    (
        "--profile-sha256",
        dict(
            dest="profile_sha256",
            metavar="HEX",
            help=N_(
                "Expected SHA-256 of the profile: refuse if it changed"
                " since the simulation."
            ),
        ),
    ),
)


def ajouter_meta(parser, t):
    """Ajoute au parser les méta-options absentes, aides traduites par
    `t`."""

    def sha256(valeur):
        valeur = valeur.strip().lower()
        if RE_SHA256.fullmatch(valeur) is None:
            raise argparse.ArgumentTypeError(
                t(N_("expected 64 hexadecimal characters"))
            )
        return valeur

    for nom, options in META:
        if nom in parser._option_string_actions:
            continue
        options = dict(options)
        options["help"] = t(options["help"])
        if nom == "--profile-sha256":
            options["type"] = sha256
        parser.add_argument(nom, **options)


class _EchecPrepasse(Exception):
    """La pré-passe a rencontré une erreur, l'aide ou une sortie."""


_ABSENT = object()


def _pre_passe(parser, argv):
    """`parse_known_args(argv)` silencieux, défauts suspendus : rend le
    namespace des seules options présentes, ou None si argparse aurait
    imprimé ou quitté (aide, erreur, `required` manquant). Le parser est
    rendu intact dans tous les cas."""
    defauts = [(action, action.default) for action in parser._actions]
    defauts_parser = parser._defaults
    remplaces = {
        nom: parser.__dict__.get(nom, _ABSENT)
        for nom in ("error", "exit", "_print_message")
    }

    def erreur(message):
        raise _EchecPrepasse(message)

    def sortie(status=0, message=None):
        raise _EchecPrepasse(message)

    def silence(message, file=None):
        return None

    try:
        for action, _defaut in defauts:
            action.default = argparse.SUPPRESS
        parser._defaults = {}
        parser.error = erreur
        parser.exit = sortie
        parser._print_message = silence
        try:
            namespace, _restes = parser.parse_known_args(argv)
        except (Exception, SystemExit):
            # Toute erreur se reproduit à la passe finale, qui l'imprime.
            return None
        return namespace
    finally:
        for action, defaut in defauts:
            action.default = defaut
        parser._defaults = defauts_parser
        for nom, valeur in remplaces.items():
            if valeur is _ABSENT:
                parser.__dict__.pop(nom, None)
            else:
                parser.__dict__[nom] = valeur


Valeur = collections.namedtuple("Valeur", "option brut converti cle")
Ecartee = collections.namedtuple(
    "Ecartee", "dest option cle raison modele valeurs"
)


class Application:
    """Ce qu'`analyser` a fait du profil, posé dans `args.profil`.

    `actif` est faux sans profil. `chemin`, `service`, `empreinte`
    (sha256), `unite_devinee` (`(nom, raison)` ou None), `valeurs`
    ({dest: Valeur}), `ecartees` ([Ecartee]), `inconnues` (clés
    `groupe.cle`), `presents` (les `dest` de la ligne de commande),
    `document` (le JSON lu, None sans profil), `credentials` ({dest:
    fichier} des secrets que l'unité reçoit en credential systemd).
    """

    def __init__(self, groupe):
        self.groupe = groupe
        self.actif = False
        self.chemin = None
        self.service = None
        self.empreinte = None
        self.unite_devinee = None
        self.valeurs = collections.OrderedDict()
        self.ecartees = []
        self.inconnues = []
        self.presents = frozenset()
        self.poses = set()
        self.secrets_kdbx = {}
        self.document = None
        self.credentials = {}

    def origine(self, dest):
        """ "systemd" (credential de l'unité, qui passe avant la ligne de
        commande), "cli", "profil" ou "defaut"."""
        if dest in self.credentials:
            return "systemd"
        if dest in self.presents:
            return "cli"
        if dest in self.valeurs or dest in self.poses:
            return "profil"
        return "defaut"

    def _ecarter(self, champ, raison, modele, **valeurs):
        """Note la valeur du champ `champ` écartée pour `raison`, avec
        le modèle de son avertissement."""
        valeurs.setdefault("option", champ.option)
        cle = f"{champ.groupe}.{champ.cle}"
        self.ecartees.append(
            Ecartee(champ.dest, champ.option, cle, raison, modele, valeurs)
        )

    def avertissements(self, t):
        """Les ATTN, traduits : une ligne par clé inconnue et par valeur
        écartée."""
        lignes = [
            t(N_("unknown key {key}, ignored")).format(key=cle)
            for cle in self.inconnues
        ]
        for ecartee in self.ecartees:
            valeurs = dict(ecartee.valeurs)
            if "reason" in valeurs:
                valeurs["reason"] = t(valeurs["reason"])
            lignes.append(t(ecartee.modele).format(**valeurs))
        return lignes

    def entete(self, t):
        """`{path} — {count} value(s)`."""
        return t(N_("{path} — {count} value(s)")).format(
            path=self.chemin, count=len(self.valeurs)
        )

    def details(self, t):
        """Une ligne par valeur retenue, une par élément d'une liste :
        `--keep-daily 10 (profile)`."""
        lignes = []
        for valeur in self.valeurs.values():
            if valeur.brut is True:
                lignes.append(
                    t(N_("{option} (profile)")).format(option=valeur.option)
                )
                continue
            elements = (
                valeur.brut if isinstance(valeur.brut, list) else [valeur.brut]
            )
            for element in elements:
                if isinstance(element, bool):
                    element = "true" if element else "false"
                lignes.append(
                    t(N_("{option} {value} (profile)")).format(
                        option=valeur.option, value=element
                    )
                )
        return lignes

    def json(self):
        """La clé `"profile"` d'une sortie JSON, ou None sans profil :
        `values` porte les valeurs brutes, par option."""
        if not self.actif:
            return None
        ignorees = [
            {"key": cle, "reason": "unknown"} for cle in self.inconnues
        ]
        ignorees += [
            {"key": e.cle, "option": e.option, "reason": e.raison}
            for e in self.ecartees
        ]
        return {
            "path": self.chemin,
            "values": {v.option: v.brut for v in self.valeurs.values()},
            "ignored": ignorees,
        }


def afficher(application, rapport, t):
    """En-tête `Profile`, une ligne par valeur et un ATTN par avertissement,
    sur un `report.Rapport`. Rien sans profil."""
    if not application.actif:
        return
    rapport.champ(t(N_("Profile")), application.entete(t))
    for ligne in application.details(t):
        rapport.detail(ligne)
    for ligne in application.avertissements(t):
        rapport.attn(ligne)


def origine_affichee(application, dest, detectee, t):
    """L'origine à montrer pour `dest` : « profile » traduit quand la valeur
    vient du profil, sinon `detectee` (l'origine que l'outil a trouvée,
    `--db` ou la configuration). `application` peut valoir None."""
    if application is not None and application.origine(dest) == "profil":
        return t(N_("profile"))
    return detectee


def _refuser(parser, t, chemin, err):
    """`parser.error` (code 2) avec le message traduit de `err`."""
    if err.cle:
        parser.error(
            t(N_("Profile {path}: {key}: {error}")).format(
                path=chemin, key=err.cle, error=err.message(t)
            )
        )
    parser.error(
        t(N_("Profile {path}: {error}")).format(
            path=chemin, error=err.message(t)
        )
    )


def _avertir_illisible(t, chemin, err):
    """L'ATTN d'un profil découvert illisible, sur stderr : il paraît avant
    tout rapport de l'outil, et dans le journal d'une unité."""
    print(
        "⚠ [ATTN] "
        + t(N_("Profile {path}: {error}; this account ignores it.")).format(
            path=chemin, error=err.message(t)
        ),
        file=sys.stderr,
        flush=True,
    )


def _normaliser_nom(nom):
    return nom.strip().lstrip("-").replace("-", "_")


def _trouver(ns_pre, presents, racine, lanceur, utilise_service, app):
    """Le profil à lire : (chemin, découvert), ou (None, False)."""
    explicite = getattr(ns_pre, "profile", None)
    if explicite:
        return os.path.abspath(explicite), False
    dossier = racine_profils(racine)
    if "service" in presents:
        try:
            nom = systemd.nom_unite(str(ns_pre.service))
        except ValueError:
            return None, False
    elif lanceur is not None and utilise_service(presents):
        try:
            app.unite_devinee = systemd.deviner_unite(racine, lanceur)
        except systemd.ErreurUnite:
            return None, False
        nom = app.unite_devinee[0]
    else:
        return None, False
    chemin = os.path.join(dossier, f"{nom}.json")
    if not os.path.lexists(chemin):
        return None, False
    return chemin, True


def analyser(
    parser,
    argv,
    groupe,
    t,
    racine,
    lanceur=None,
    utilise_service=None,
    connus=False,
):
    """Analyse `argv` par `parser` avec le profil du groupe `groupe`.

    Rend `(args, application)`, ou `(args, restes, application)` avec
    `connus` (`parse_known_args`). `args.profil` est l'`Application`.

    Une pré-passe silencieuse, défauts suspendus, trouve les `dest`
    présentes ; son échec (aide, erreur) saute le profil et laisse la
    passe finale imprimer une seule fois. Le profil vient de `--profile`,
    sinon de `<racine des profils>/<service>.json`, le service étant
    `--service` normalisé ou, avec un `lanceur` et
    `utilise_service(presents)`, l'unité devinée. Les valeurs retenues
    sont converties une seule fois et posées par `setattr` après la passe
    finale aux défauts normaux. Toute erreur du profil sort par
    `parser.error` (code 2).

    Un champ secret dont l'unité reçoit le credential (`credentials.fichier`)
    prend ce fichier en dernier, par-dessus la ligne de commande et le
    profil, avec ou sans profil."""
    ajouter_meta(parser, t)
    argv = list(sys.argv[1:] if argv is None else argv)
    if utilise_service is None:
        utilise_service = _toujours
    application = Application(groupe)
    secrets = _secrets_du_parser(parser, groupe)
    for dest, nom in secrets.items():
        fourni = credentials.disponible(nom)
        if fourni:
            application.credentials[dest] = fourni
    ns_pre = _pre_passe(parser, argv)
    if ns_pre is not None:
        _appliquer(
            parser,
            ns_pre,
            groupe,
            t,
            racine,
            lanceur,
            utilise_service,
            application,
        )
    restes = None
    if connus:
        args, restes = parser.parse_known_args(argv)
    else:
        args = parser.parse_args(argv)
    for dest, valeur in application.valeurs.items():
        setattr(args, dest, valeur.converti)
    for dest, nom in secrets.items():
        option = (
            getattr(args, dest, None) if dest in application.presents else None
        )
        du_profil = application.valeurs.get(dest)
        chemin, origine = credentials.fichier(
            nom, option, du_profil.converti if du_profil else None
        )
        if origine == "systemd":
            application.credentials[dest] = chemin
            setattr(args, dest, chemin)
        else:
            application.credentials.pop(dest, None)
    if "service" in application.poses:
        args.service = application.service
    args.profil = application
    if connus:
        return args, restes, application
    return args, application


def _secrets_du_parser(parser, groupe):
    """{dest: nom du credential} des secrets du groupe que le parser
    porte, alias compris (`secrets_du_groupe`)."""
    actions = _actions(parser)
    return collections.OrderedDict(
        (dest, nom)
        for dest, _cible, nom in secrets_du_groupe(groupe)
        if dest in actions
    )


def _appliquer(
    parser,
    ns_pre,
    groupe,
    t,
    racine,
    lanceur,
    utilise_service,
    app,
):
    """Étapes 3 à 8 : découverte, lecture, collecte, écartement,
    conversion, service. Remplit `app` ; refuse par `parser.error`."""
    presents = frozenset(vars(ns_pre))
    app.presents = presents
    actions = _actions(parser)
    propres = [
        _champ(actions[dest], groupe, dest)
        for dest in CHAMPS.get(groupe, ())
        if dest in actions
    ]
    aliases = alias(parser, groupe)
    par_dest = collections.OrderedDict((c.dest, c) for c in propres + aliases)
    par_cle = {(c.groupe, c.cle): c for c in par_dest.values()}

    retires = set()
    for nom in getattr(ns_pre, "profile_unset", None) or ():
        dest = _normaliser_nom(nom)
        if dest not in par_dest:
            parser.error(
                t(N_("unknown setting for --profile-unset: {name}")).format(
                    name=nom
                )
            )
        retires.add(dest)

    if getattr(ns_pre, "no_profile", False):
        return
    chemin, decouvert = _trouver(
        ns_pre, presents, racine, lanceur, utilise_service, app
    )
    if chemin is None:
        if getattr(ns_pre, "profile_required", False):
            parser.error(
                t(N_("No profile found, and --profile-required is given."))
            )
        return
    try:
        lu = lire(chemin, racine_profils(racine) if decouvert else None)
    except ProfilIllisible as err:
        # Un profil découvert que ce compte ne peut pas ouvrir (le compte
        # d'une unité, fichier d'un autre compte en 0600) vaut « pas de
        # profil » : une commande qui ne l'a pas nommé ne dépend pas de
        # lui. Nommé par --profile, ou exigé, il refuse.
        if not decouvert or getattr(ns_pre, "profile_required", False):
            _refuser(parser, t, chemin, err)
        _avertir_illisible(t, chemin, err)
        return
    except ErreurProfil as err:
        _refuser(parser, t, chemin, err)
    try:
        valider_document(lu.doc, chemin, hote=groupe == GROUPE_HOTE)
    except ErreurProfil as err:
        _refuser(parser, t, chemin, err)
    doc = lu.doc
    attendue = getattr(ns_pre, "profile_sha256", None)
    if attendue and attendue != lu.empreinte:
        _refuser(
            parser,
            t,
            chemin,
            ErreurProfil(N_("profile changed since the simulation")),
        )
    app.actif = True
    app.chemin = chemin
    app.empreinte = lu.empreinte
    app.document = doc
    # `valider_document` a vérifié que le nom se normalise : la
    # comparaison avec --service et la valeur posée portent sur l'unité
    # complète (`odoo-exemple` devient `odoo-exemple.service`).
    app.service = doc.get("service")
    if isinstance(app.service, str) and groupe != GROUPE_HOTE:
        app.service = systemd.nom_unite(app.service)

    if groupe != GROUPE_HOTE and "service" in actions:
        if "service" in presents:
            try:
                demande = systemd.nom_unite(str(ns_pre.service))
            except ValueError:
                demande = None
            if demande is not None and demande != app.service:
                _refuser(
                    parser,
                    t,
                    chemin,
                    ErreurProfil(
                        N_(
                            "--service {service} differs from the profile"
                            " service {profile}"
                        ),
                        service=demande,
                        profile=app.service,
                    ),
                )
        elif not decouvert and utilise_service(presents):
            app.poses.add("service")

    # Collecte : groupe de l'outil, `instance`, cibles des alias.
    candidats = []
    exclues = exclusions(groupe)
    for nom in doc:
        if nom not in CLES_DOCUMENT and nom not in CHAMPS:
            app.inconnues.append(nom)
    for cle, brut in (doc.get(groupe) or {}).items():
        if cle in CHAMPS.get(groupe, ()) and cle in par_dest:
            candidats.append((par_dest[cle], brut))
        elif cle in exclues:
            app.ecartees.append(
                Ecartee(
                    cle,
                    option(actions[cle]) if cle in actions else cle,
                    f"{groupe}.{cle}",
                    "exclue",
                    N_("{key} is not a profile setting ({reason}), ignored"),
                    {
                        "key": f"{groupe}.{cle}",
                        "reason": RAISONS[exclues[cle]],
                    },
                )
            )
        else:
            app.inconnues.append(f"{groupe}.{cle}")
    # Le profil d'hôte ne lit pas `instance`, groupe d'un autre outil : ses
    # clés n'y sont pas vérifiées, comme dans le lecteur interne de l'audit.
    if groupe not in (GROUPE_INSTANCE, GROUPE_HOTE):
        for cle in doc.get(GROUPE_INSTANCE) or {}:
            if cle not in CHAMPS[GROUPE_INSTANCE]:
                app.inconnues.append(f"{GROUPE_INSTANCE}.{cle}")
    for champ in aliases:
        cible = doc.get(champ.groupe) or {}
        if champ.cle in cible:
            candidats.append((champ, cible[champ.cle]))

    # Ordre du catalogue : champs du groupe, puis alias.
    rang = {dest: i for i, dest in enumerate(par_dest)}
    candidats.sort(key=lambda candidat: rang[candidat[0].dest])

    # Écartement par la ligne de commande et par les règles d'exclusion.
    exclusifs = [
        [a.dest for a in groupe_ex._group_actions]
        for groupe_ex in parser._mutually_exclusive_groups
    ]
    retenus = []
    for champ, brut in candidats:
        if champ.dest in presents:
            if champ.genre == "liste_append" and isinstance(brut, list):
                app._ecarter(
                    champ,
                    "cli",
                    N_(
                        "{count} value(s) of {option} from the profile"
                        " replaced by the command line"
                    ),
                    count=len(brut),
                )
            else:
                app._ecarter(
                    champ,
                    "cli",
                    N_("{option}: the command line wins over the profile"),
                )
            continue
        if champ.dest in retires:
            app._ecarter(
                champ, "unset", N_("{option}: removed by --profile-unset")
            )
            continue
        autre = None
        for membres in exclusifs:
            if champ.dest in membres:
                for membre in membres:
                    if membre != champ.dest and membre in presents:
                        autre = actions[membre]
                        break
            if autre is not None:
                break
        if autre is not None:
            app._ecarter(
                champ,
                "exclusif",
                N_(
                    "{option} from the profile ignored: {other} is on the"
                    " command line"
                ),
                other=option(autre),
            )
            continue
        conflit = None
        for regle in CONFLITS:
            if (
                regle.groupe == groupe
                and regle.dest == champ.dest
                and all(p in presents for p in regle.presents)
            ):
                conflit = regle
                break
        if conflit is not None:
            app._ecarter(
                champ,
                "conflit",
                N_("{option} from the profile ignored: {reason}"),
                reason=conflit.raison,
            )
            continue
        retenus.append((champ, brut))

    # Conversion et règles du profil. La somme des `keep_*` ne porte que
    # sur les valeurs du profil retenues, défauts de l'outil pour les
    # autres : une valeur remplacée par la ligne de commande ne s'applique
    # pas, elle ne peut donc pas faire refuser la commande.
    groupe_somme, cles_somme, _minimum = BORNE_SOMME
    gardees = {
        champ.cle: brut
        for champ, brut in retenus
        if champ.groupe == groupe_somme and champ.cle in cles_somme
    }
    if gardees:
        defauts = {
            cle: par_cle[(groupe_somme, cle)].defaut
            for cle in cles_somme
            if (groupe_somme, cle) in par_cle
        }
        try:
            verifier_somme(gardees, defauts)
        except ErreurProfil as err:
            _refuser(parser, t, chemin, err)
    convertis = collections.OrderedDict()
    for champ, brut in retenus:
        try:
            converti = convertir(champ, brut)
        except ErreurProfil as err:
            _refuser(parser, t, chemin, err)
        if champ.dest in app.credentials:
            # Le credential de l'unité remplace le secret du profil, quelle
            # que soit sa forme ; il est posé après la passe finale.
            if isinstance(converti, Kdbx):
                nom_secret = SECRETS[(champ.groupe, champ.cle)]
                app.secrets_kdbx[champ.dest] = (converti.reference, nom_secret)
            else:
                app._ecarter(
                    champ,
                    "systemd",
                    N_(
                        "{option}: the systemd credential wins over the profile"
                    ),
                )
            continue
        if isinstance(converti, Kdbx):
            # Un outil ne lit jamais KeePass : une référence n'a pas de
            # valeur ici, elle est écartée et ne compte pas comme effective
            # pour ses dépendants.
            nom_secret = SECRETS[(champ.groupe, champ.cle)]
            app.secrets_kdbx[champ.dest] = (converti.reference, nom_secret)
            app._ecarter(
                champ,
                "secret",
                N_(
                    "{option}: the secret is in KeePass, not reachable"
                    " here; ignored"
                ),
            )
            continue
        convertis[champ.dest] = (champ, brut, converti)

    # Dépendances, en point fixe : un dépendant sans dépendance effective
    # est écarté, ce qui peut rendre un autre dépendant non effectif.
    change = True
    while change:
        change = False
        for dest in list(convertis):
            champ = convertis[dest][0]
            dependance = DEPENDANCES.get((champ.groupe, champ.cle))
            if dependance is None or dependance not in par_cle:
                continue
            cible = par_cle[dependance]
            effective = (
                cible.dest in presents
                or cible.dest in convertis
                or cible.dest in app.credentials
            )
            if not effective:
                del convertis[dest]
                app._ecarter(
                    champ,
                    "dependance",
                    N_(
                        "{option} from the profile ignored: {dependency} is"
                        " not available here"
                    ),
                    dependency=cible.option,
                )
                change = True

    for dest, (champ, brut, converti) in convertis.items():
        app.valeurs[dest] = Valeur(
            champ.option, brut, converti, f"{champ.groupe}.{champ.cle}"
        )
