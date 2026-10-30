#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les unités systemd UTILISATEUR qui lancent les règles sans le client.

`erplibre-mail-rules.service` (oneshot, sans section `[Install]`) lance
`python -m script.todo.mail.rules.run --quiet` depuis le dépôt qui l'a
installé ; `erplibre-mail-rules.timer` le relance toutes les N minutes.
Seule la minuterie est activée.

Les fichiers vivent dans `<config du gestionnaire>/systemd/user/`, le
dossier de configuration étant celui du GESTIONNAIRE systemd de
l'utilisateur (`credential.manager_config_home`), et non celui du shell.
Installer et mettre à jour suivent la même suite : écrire les deux
fichiers, `daemon-reload`, `enable` puis `restart` de la minuterie ; le
`restart` applique un nouvel intervalle, qui ne se lit que dans le
fichier de la minuterie.

Chaque fonction qui lance un programme prend `run` (signature de
`subprocess.run`), résolu à l'appel : un test qui remplace
`subprocess.run` intercepte aussi l'appel qu'il aurait oublié de doubler.
Rien ici ne demande de mot de passe : `loginctl` reçoit
`--no-ask-password`, et aucun argument ne porte de secret.
"""

from __future__ import annotations

import contextlib
import getpass
import json
import os
import re
import subprocess
import tempfile
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from script.todo.mail import credential
from script.todo.todo_i18n import t

UNIT = "erplibre-mail-rules"
SERVICE = f"{UNIT}.service"
TIMER = f"{UNIT}.timer"
INTERVAL_DEFAULT_MIN = 5
INTERVAL_MIN, INTERVAL_MAX = 1, 1440
SYSTEMCTL_TIMEOUT_S = 15
STATUS_TIMEOUT_S = 3
# Codes de sortie qui ont un libellé : ceux de la commande, puis ceux que
# systemd rend avant elle (dossier de travail, exécutable, credential).
EXIT_LABELS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 200, 203, 243)
VENV_CONF = Path("conf") / "python-erplibre-venv"
VENV_DEFAULT = ".venv.erplibre"
# Longueur gardée d'une sortie de systemctl dans un message.
OUTPUT_MAX = 200

_HEADER = (
    "# Written by ERPLibre TODO, Mail > Rules > Service;"
    " rewritten on update.\n"
)
_SERVICE_TEMPLATE = (
    _HEADER
    + """[Unit]
Description=ERPLibre mail rules, one pass for every account

[Service]
Type=oneshot
WorkingDirectory={wd}
ExecStart={py} -m script.todo.mail.rules.run --quiet
Environment=PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
LoadCredentialEncrypted=erplibre-mail-kdbx
SuccessExitStatus=6
TimeoutStartSec=10min
SyslogIdentifier=erplibre-mail-rules
UMask=0077
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
LimitCORE=0
NoNewPrivileges=yes
RestrictSUIDSGID=yes
RestrictRealtime=yes
RestrictNamespaces=yes
LockPersonality=yes
SystemCallArchitectures=native
"""
)
_TIMER_TEMPLATE = (
    _HEADER
    + """[Unit]
Description=ERPLibre mail rules every {n} min

[Timer]
OnStartupSec=2min
OnUnitActiveSec={n}min
RandomizedDelaySec=30s
AccuracySec=30s

[Install]
WantedBy=timers.target
"""
)
_INTERVAL_RE = re.compile(r"^OnUnitActiveSec=(\d+)min$", re.MULTILINE)


class ServiceError(Exception):
    """Une installation, mise à jour ou désinstallation refusée. Message
    pour l'humain, déjà traduit."""


@dataclass
class ServiceStatus:
    """L'état du service, lu sur le disque puis auprès de systemctl."""

    # Un fichier d'unité OU le lien `timers.target.wants` présent.
    installed: bool = False
    # Contenu installé identique au rendu courant.
    up_to_date: bool = False
    # `UnitFileState` de la minuterie vaut « enabled ».
    enabled: bool = False
    # `ActiveState` de la minuterie vaut « active ».
    active: bool = False
    # Relu dans la minuterie installée.
    interval_min: int | None = None
    # Prochaine passe, en secondes depuis l'époque, approximative.
    next_run: int | None = None
    # `ExecMainExitTimestamp` du service.
    last_run: int | None = None
    # `ExecMainStatus`, posé seulement si `last_run` est lisible.
    last_exit: int | None = None
    # Fichier du credential présent.
    credential: bool = False
    # `WorkingDirectory=` installé, `%%` rendu en `%`.
    repo: str = ""
    # Dépôt installé, ou son python, introuvable.
    repo_missing: bool = False
    # systemctl injoignable ou en échec : sa sortie, sur une ligne.
    error: str = ""


def _runner(run: Callable | None) -> Callable:
    return run if run is not None else subprocess.run


def repo_root() -> Path:
    """La racine du dépôt qui porte ce fichier, chemin réel."""
    return Path(__file__).resolve().parents[3]


def venv_python(repo: Path) -> Path:
    """L'interpréteur du venv d'outillage du dépôt `repo`.

    Le nom du venv se lit dans `conf/python-erplibre-venv` (premier mot),
    `.venv.erplibre` à défaut. Le chemin n'est pas résolu : un python de
    venv est un lien, et c'est par lui que le venv se reconnaît.
    """
    repo = Path(repo)
    try:
        mots = (repo / VENV_CONF).read_text(encoding="utf-8").split()
    except (OSError, UnicodeDecodeError):
        mots = []
    nom = mots[0] if mots else VENV_DEFAULT
    return repo / nom / "bin" / "python"


def unit_dir(*, run: Callable | None = None) -> Path:
    """Le dossier des unités du gestionnaire systemd de l'utilisateur."""
    return credential.manager_config_home(run=run) / "systemd" / "user"


def wants_link(*, run: Callable | None = None) -> Path:
    """Le lien que `enable` pose pour la minuterie."""
    return _wants_link(unit_dir(run=run))


def _wants_link(directory: Path) -> Path:
    return directory / "timers.target.wants" / TIMER


def _clean(text) -> str:
    """Une sortie de programme sur une ligne, `OUTPUT_MAX` caractères au
    plus, sans caractère de contrôle."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    propre = "".join(
        " " if unicodedata.category(char) == "Cc" else char
        for char in str(text or "")
    )
    return " ".join(propre.split())[:OUTPUT_MAX]


def _systemctl(
    run: Callable | None, *args: str, timeout: float = SYSTEMCTL_TIMEOUT_S
) -> tuple[int, str]:
    """`systemctl --user <args>` ; rend (code, sortie nettoyée). Un délai
    dépassé ou un programme absent rend un code -1 et le nom de
    l'exception."""
    try:
        result = _runner(run)(
            ["systemctl", "--user", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, type(exc).__name__
    sortie = _clean(
        f"{getattr(result, 'stderr', '') or ''}"
        f" {getattr(result, 'stdout', '') or ''}"
    )
    return getattr(result, "returncode", 1), sortie


def user_bus_ok(*, run: Callable | None = None) -> bool:
    """Vrai si le gestionnaire systemd de l'utilisateur répond."""
    code, _ = _systemctl(run, "show-environment", timeout=STATUS_TIMEOUT_S)
    return code == 0


def _read(path: Path) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _directive(text: str | None, name: str) -> str | None:
    """La valeur de la première ligne `name=` de `text`, ou None."""
    for ligne in (text or "").splitlines():
        if ligne.startswith(f"{name}="):
            return ligne[len(name) + 1 :]
    return None


def _installed_repo_in(directory: Path) -> str:
    valeur = _directive(_read(directory / SERVICE), "WorkingDirectory")
    return valeur.replace("%%", "%") if valeur else ""


def installed_repo(*, run: Callable | None = None) -> str:
    """Le `WorkingDirectory=` du service installé (`%%` rendu en `%`) ;
    "" si le fichier manque."""
    return _installed_repo_in(unit_dir(run=run))


def escape_specifiers(text: str) -> str:
    """`text` où chaque `%` est doublé : systemd n'y voit plus de
    spécificateur."""
    return str(text).replace("%", "%%")


def quote_exec_arg(text: str) -> str:
    """`text` comme PREMIER mot d'`ExecStart=`, l'exécutable : entre
    guillemets, la barre oblique inverse et le guillemet échappés, `%`
    doublé (pas de spécificateur). `$` reste simple : systemd ne développe
    aucune variable dans le chemin de l'exécutable, et `$$` y resterait
    tel quel, nommant un fichier qui n'existe pas."""
    corps = (
        str(text).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    )
    return f'"{corps}"'


def _unquote_exec_arg(text: str) -> str:
    """Le premier argument d'une ligne `ExecStart=` écrite par
    `quote_exec_arg`, rendu en clair ; "" s'il n'en a pas la forme."""
    if not text.startswith('"'):
        return ""
    sortie = []
    rang = 1
    while rang < len(text):
        char = text[rang]
        if char == "\\" and rang + 1 < len(text):
            sortie.append(text[rang + 1])
            rang += 2
            continue
        if char == '"':
            return "".join(sortie).replace("%%", "%")
        sortie.append(char)
        rang += 1
    return ""


def check_unit_path(path) -> str:
    """`path` en texte s'il peut figurer dans une unité, sinon
    `ServiceError`.

    Refusés : un chemin relatif ; un caractère de contrôle (saut de ligne
    compris) ; une barre oblique inverse, qui en fin de valeur prolonge la
    ligne sur la suivante et que systemd refuse dans un exécutable comme
    le guillemet ; un blanc en tête ou en fin, que systemd retire de la
    valeur.
    """
    texte = os.fspath(path) if path is not None else ""
    if isinstance(texte, bytes):
        texte = texte.decode("utf-8", "replace")
    if (
        not texte
        or not os.path.isabs(texte)
        or texte != texte.strip()
        or "\\" in texte
        or '"' in texte
        or any(unicodedata.category(char) == "Cc" for char in texte)
    ):
        raise ServiceError(f"{t('mail_service_path_refused')} {texte!r}")
    return texte


def render_service(repo: Path, python: Path) -> str:
    """Le texte exact de `erplibre-mail-rules.service`."""
    return _SERVICE_TEMPLATE.format(
        wd=escape_specifiers(check_unit_path(repo)),
        py=quote_exec_arg(check_unit_path(python)),
    )


def render_timer(interval_min: int) -> str:
    """Le texte exact de `erplibre-mail-rules.timer` ; un intervalle qui
    n'est pas un entier de 1 à 1440 (booléen compris) lève
    `ServiceError`."""
    if (
        type(interval_min) is not int
        or not INTERVAL_MIN <= interval_min <= INTERVAL_MAX
    ):
        raise ServiceError(t("mail_service_interval_refused"))
    return _TIMER_TEMPLATE.format(n=interval_min)


def _interval_in(directory: Path) -> int | None:
    trouve = _INTERVAL_RE.search(_read(directory / TIMER) or "")
    return int(trouve.group(1)) if trouve else None


def installed_interval(*, run: Callable | None = None) -> int | None:
    """L'intervalle relu dans la minuterie installée, ou None."""
    return _interval_in(unit_dir(run=run))


def _write_unit(path: Path, text: str) -> None:
    """Écrit `text` dans `path` d'un coup, en 0644 ; le temporaire du
    même dossier est retiré sur toute exception."""
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def install(
    interval_min: int,
    *,
    repo=None,
    python=None,
    run: Callable | None = None,
) -> None:
    """Installe ou met à jour les deux unités, puis recharge, active et
    relance la minuterie.

    Rien n'est écrit si le python du venv manque ou si un texte ne se
    rend pas. Un `daemon-reload` refusé retire les fichiers que cet appel
    a créés ; ceux qui existaient restent, déjà réécrits, et le message
    le dit (`mail_service_reload_failed_update`) au lieu de « rien n'est
    installé ».
    """
    repo = Path(repo) if repo is not None else repo_root()
    python = Path(python) if python is not None else venv_python(repo)
    if not (python.is_file() and os.access(python, os.X_OK)):
        raise ServiceError(f"{t('mail_service_no_venv')} {python}")
    textes = (
        (SERVICE, render_service(repo, python)),
        (TIMER, render_timer(interval_min)),
    )
    directory = unit_dir(run=run)
    nouveaux = []
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for nom, texte in textes:
            chemin = directory / nom
            if not chemin.exists():
                nouveaux.append(chemin)
            _write_unit(chemin, texte)
    except OSError as exc:
        _remove(nouveaux)
        raise ServiceError(
            f"{t('mail_service_install_failed')} {_clean(exc)}"
        ) from None
    code, sortie = _systemctl(run, "daemon-reload")
    if code != 0:
        _remove(nouveaux)
        cle = (
            "mail_service_no_systemd"
            if len(nouveaux) == len(textes)
            else "mail_service_reload_failed_update"
        )
        raise ServiceError(f"{t(cle)} {sortie}".strip())
    for action in ("enable", "restart"):
        code, sortie = _systemctl(run, action, TIMER)
        if code != 0:
            raise ServiceError(
                f"{t('mail_service_install_failed')} {sortie}".strip()
            )


def _remove(paths) -> None:
    for chemin in paths:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(chemin)


def _parts_in(config: Path) -> tuple[list, Path, Path]:
    """Les deux fichiers d'unité, le lien de la minuterie et le
    credential, sous le dossier de configuration `config` du
    gestionnaire."""
    directory = config / "systemd" / "user"
    fichiers = [directory / SERVICE, directory / TIMER]
    cred = config / credential.CREDSTORE_NAME / credential.CREDENTIAL_ID
    return fichiers, _wants_link(directory), cred


def installed_parts(*, run: Callable | None = None) -> tuple[bool, bool]:
    """(unités présentes, credential présent), lus sur le disque sans
    rien demander à systemctl hors du dossier du gestionnaire."""
    fichiers, lien, cred = _parts_in(credential.manager_config_home(run=run))
    unites = any(f.exists() for f in fichiers) or lien.is_symlink()
    return unites, cred.exists()


def uninstall(
    *, remove_credential: bool = True, run: Callable | None = None
) -> bool:
    """Arrête, désactive et retire les unités ; retire aussi le credential
    sauf `remove_credential=False`. Rend False si rien n'était là.

    Sans gestionnaire joignable, les unités présentes ne sont pas
    touchées (le credential non plus) : `ServiceError`
    (`mail_service_no_systemd_uninstall`, rien n'est retiré). Un
    `daemon-reload` refusé APRÈS le retrait des fichiers lève
    `mail_service_reload_failed_removed`. Le linger n'est pas touché ici.
    """
    fichiers, lien, cred = _parts_in(credential.manager_config_home(run=run))
    unites = any(f.exists() for f in fichiers) or lien.is_symlink()
    retirer_cred = remove_credential and cred.exists()
    if not unites and not retirer_cred:
        return False
    if unites:
        if not user_bus_ok(run=run):
            raise ServiceError(t("mail_service_no_systemd_uninstall"))
        _systemctl(run, "disable", "--now", TIMER)
        _systemctl(run, "stop", SERVICE)
        try:
            _remove(fichiers)
            if lien.is_symlink():
                _remove([lien])
        except OSError as exc:
            raise ServiceError(_clean(exc)) from None
        code, sortie = _systemctl(run, "daemon-reload")
        if code != 0:
            raise ServiceError(
                f"{t('mail_service_reload_failed_removed')} {sortie}".strip()
            )
        _systemctl(run, "reset-failed", SERVICE)
    if remove_credential:
        try:
            credential.remove_credential(cred)
        except OSError as exc:
            raise ServiceError(_clean(exc)) from None
    return True


def start_now(*, run: Callable | None = None) -> tuple[int, str]:
    """Lance une passe sans l'attendre ; rend (code, sortie)."""
    return _systemctl(run, "start", "--no-block", SERVICE)


def _show(
    run: Callable | None, unit: str, props, timeout: float
) -> tuple[dict, str]:
    """Les propriétés `props` de `unit` ({clé: valeur}) et la sortie
    d'erreur ("" si l'appel a réussi)."""
    args = ["show", "--timestamp=unix"]
    for prop in props:
        args += ["-p", prop]
    try:
        result = _runner(run)(
            ["systemctl", "--user", *args, unit],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {}, type(exc).__name__
    if getattr(result, "returncode", 1) != 0:
        return {}, _clean(getattr(result, "stderr", "")) or "systemctl"
    valeurs = {}
    for ligne in str(result.stdout or "").splitlines():
        cle, sep, valeur = ligne.partition("=")
        if sep:
            valeurs[cle.strip()] = valeur.strip()
    return valeurs, ""


def _epoch(value) -> int | None:
    """`@<entier>` (`--timestamp=unix`) en secondes ; None si vide, `n/a`
    ou autre chose."""
    trouve = re.fullmatch(r"@(\d+)", str(value or "").strip())
    return int(trouve.group(1)) if trouve else None


def _next_from_list_timers(run: Callable | None, timeout: float):
    """Le champ `next` (µs, temps réel) de la minuterie dans
    `list-timers --output=json`, en secondes ; None si la sortie n'est
    pas du JSON ou n'a pas de valeur utile."""
    try:
        result = _runner(run)(
            [
                "systemctl",
                "--user",
                "list-timers",
                "--all",
                "--output=json",
                TIMER,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    try:
        entrees = json.loads(result.stdout or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(entrees, list):
        return None
    for entree in entrees:
        if not isinstance(entree, dict) or entree.get("unit") != TIMER:
            continue
        valeur = entree.get("next")
        if type(valeur) is int and valeur > 0:
            return valeur // 1_000_000
    return None


def _installed_python(directory: Path) -> str:
    ligne = _directive(_read(directory / SERVICE), "ExecStart") or ""
    return _unquote_exec_arg(ligne)


def status(
    *, run: Callable | None = None, timeout: float = STATUS_TIMEOUT_S
) -> ServiceStatus:
    """L'état du service ; une panne de systemctl ne lève pas.

    Fichiers, intervalle, dépôt et credential se lisent sur le disque ;
    systemctl n'est interrogé que si quelque chose est installé, chaque
    appel borné à `timeout`. Un appel `show` en échec remplit `error` ;
    les autres champs gardent ce qui a été lu.
    """
    st = ServiceStatus()
    config = credential.manager_config_home(run=run)
    directory = config / "systemd" / "user"
    st.credential = (
        config / credential.CREDSTORE_NAME / credential.CREDENTIAL_ID
    ).exists()
    st.installed = (
        (directory / SERVICE).exists()
        or (directory / TIMER).exists()
        or _wants_link(directory).is_symlink()
    )
    if not st.installed:
        return st
    st.interval_min = _interval_in(directory)
    st.repo = _installed_repo_in(directory)
    python = _installed_python(directory)
    st.repo_missing = bool(
        (st.repo and not os.path.isdir(st.repo))
        or (python and not os.path.exists(python))
    )
    try:
        st.up_to_date = (
            bool(st.repo)
            and _read(directory / SERVICE)
            == render_service(Path(st.repo), venv_python(Path(st.repo)))
            and _read(directory / TIMER) == render_timer(st.interval_min)
        )
    except ServiceError:
        st.up_to_date = False

    minuterie, erreur = _show(
        run,
        TIMER,
        ("LoadState", "ActiveState", "UnitFileState", "LastTriggerUSec"),
        timeout,
    )
    st.enabled = minuterie.get("UnitFileState") == "enabled"
    st.active = minuterie.get("ActiveState") == "active"
    st.next_run = _next_from_list_timers(run, timeout)
    if st.next_run is None and st.active and st.interval_min:
        dernier = _epoch(minuterie.get("LastTriggerUSec"))
        if dernier is not None:
            st.next_run = dernier + 60 * st.interval_min
    unite, erreur_service = _show(
        run,
        SERVICE,
        ("Result", "ExecMainStatus", "ExecMainExitTimestamp"),
        timeout,
    )
    st.last_run = _epoch(unite.get("ExecMainExitTimestamp"))
    if st.last_run is not None:
        with contextlib.suppress(TypeError, ValueError):
            st.last_exit = int(unite.get("ExecMainStatus", ""))
    st.error = erreur or erreur_service
    return st


def _exit_label(code: int) -> str:
    if code in EXIT_LABELS:
        return t(f"mail_service_exit_{code}")
    return str(code)


def status_text(st: ServiceStatus) -> str:
    """L'état en une ligne, partagée par le menu et le TUI ; elle ne
    nomme aucun chemin."""
    parts = []
    if st.error:
        parts.append(t("mail_service_status_unknown"))
    elif not st.installed:
        parts.append(t("mail_service_status_not_installed"))
    elif not st.active:
        parts.append(t("mail_service_status_installed_off"))
    else:
        parts.append(
            t("mail_service_status_active").format(
                n=st.interval_min if st.interval_min is not None else "?"
            )
        )
        if st.next_run is not None:
            heure = time.strftime("%H:%M", time.localtime(st.next_run))
            parts.append(f"{t('mail_service_status_next')} {heure}")
    if st.installed and st.last_exit is not None:
        parts.append(
            f"{t('mail_service_status_last_exit')} {_exit_label(st.last_exit)}"
        )
    if st.installed and st.repo:
        if os.path.realpath(st.repo) != os.path.realpath(repo_root()):
            parts.append(t("mail_service_status_other_repo"))
    if st.repo_missing:
        parts.append(t("mail_service_status_repo_missing"))
    if st.installed and not st.up_to_date:
        parts.append(t("mail_service_status_outdated"))
    parts.append(
        t("mail_service_status_credential_yes")
        if st.credential
        else t("mail_service_status_credential_no")
    )
    return f"{t('mail_service_status_title')} {', '.join(parts)}"


def _loginctl(run: Callable | None, *args: str):
    try:
        return _runner(run)(
            ["loginctl", *args],
            capture_output=True,
            text=True,
            timeout=SYSTEMCTL_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def linger_enabled(
    user: str | None = None, *, run: Callable | None = None
) -> bool | None:
    """Vrai si le linger est actif pour `user` (l'utilisateur courant par
    défaut), faux s'il ne l'est pas, None si loginctl ne le dit pas."""
    user = user or getpass.getuser()
    result = _loginctl(run, "show-user", user, "-p", "Linger", "--value")
    if result is None or getattr(result, "returncode", 1) != 0:
        return None
    valeur = str(result.stdout or "").strip()
    return {"yes": True, "no": False}.get(valeur)


def _set_linger(action: str, user: str | None, run: Callable | None):
    user = user or getpass.getuser()
    result = _loginctl(run, "--no-ask-password", action, user)
    return result is not None and getattr(result, "returncode", 1) == 0


def enable_linger(
    user: str | None = None, *, run: Callable | None = None
) -> bool:
    """Active le linger sans jamais demander de mot de passe ; rend le
    succès."""
    return _set_linger("enable-linger", user, run)


def disable_linger(
    user: str | None = None, *, run: Callable | None = None
) -> bool:
    """Retire le linger sans jamais demander de mot de passe ; rend le
    succès."""
    return _set_linger("disable-linger", user, run)


def accounts_need_credential(accounts, base=None) -> bool:
    """Vrai si un compte que la passe traite ouvre le kdbx : actif, hors
    cache éphémère, avec une règle active exécutable dans `base` (le
    dossier des règles, celui du cache par défaut), et dont le secret ou
    la clé du cache chiffré vit dans le kdbx. Des règles illisibles ne
    comptent pas : la passe s'arrête sur elles sans ouvrir le coffre."""
    from script.todo.mail.rules.model import RuleError
    from script.todo.mail.rules.run import kdbx_refs, needs_pass
    from script.todo.mail.store import default_base, resolve_mode

    base = default_base() if base is None else base

    def traite(account) -> bool:
        try:
            return needs_pass(account, base)
        except RuleError:
            return False

    return any(
        account.enabled
        and resolve_mode(account) != "ephemeral"
        and any(kdbx_refs(account))
        and traite(account)
        for account in accounts or ()
    )
