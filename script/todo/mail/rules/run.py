#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une passe des règles du courrier entrant, sans interface.

    python -m script.todo.mail.rules.run [--compte NOM] [--quiet]

Pour chaque compte qui a une règle active : synchronisation d'INBOX et du
dossier Envoyés, vidange de la file d'envoi, puis `engine.run_pass`. Les
comptes sont traités en série ; personne n'attend la fin de la passe.

Rien n'est demandé : ni terminal, ni fenêtre, ni Textual. Le coffre
s'ouvre avec le mot de passe maître que systemd dépose dans
`$CREDENTIALS_DIRECTORY` (voir `credential`), sinon avec `kdbx.password`
de la configuration ; à défaut, la passe s'arrête sur une ligne « coffre
verrouillé ». Le trousseau système n'est lu que s'il répond sans rien
demander (`secrets.keyring_headless_problem`) : jamais déverrouillé,
jamais créé.

La sortie standard est le journal du service : une ligne par compte, sans
adresse, sujet, secret ni texte d'erreur de serveur ou de règle — ces
textes vont dans `~/.erplibre/mail.log`. Le code de sortie dit la famille
de la panne la plus grave (`EXIT_PRIORITY`).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TextIO

# En tête de module : `config_file` appelle `logging.basicConfig(INFO)` à
# son import, et `main` abaisse ensuite le logger racine à WARNING. Importé
# plus tard, ce `basicConfig` passerait après et ne changerait rien au
# niveau, mais l'ordre resterait fragile.
from script.config.config_file import ConfigFile
from script.todo.mail import accounts as mail_accounts
from script.todo.mail import credential, errors
from script.todo.mail.account_setup import secret_ref_for
from script.todo.mail.imap_sync import is_inbox
from script.todo.mail.rules import engine, storage
from script.todo.mail.rules.lock import file_lock
from script.todo.mail.rules.model import EXECUTABLE_KINDS, RuleError
from script.todo.mail.store import default_base, resolve_mode
from script.todo.todo_i18n import t

# Nom explicite : lancé par `-m`, `__name__` vaut "__main__", hors du
# paquet dont `mail.log` reçoit les journaux.
_logger = logging.getLogger("script.todo.mail.rules.run")

EXIT_OK, EXIT_FAILURE, EXIT_USAGE = 0, 1, 2
EXIT_VAULT, EXIT_NETWORK, EXIT_RULE = 3, 4, 5
EXIT_BUSY, EXIT_AUTH, EXIT_CONFIG = 6, 7, 8
# Plusieurs comptes : le premier code présent dans cet ordre est rendu. Ce
# qui demande une intervention humaine passe devant ce qui se répare seul.
EXIT_PRIORITY = (1, 8, 3, 7, 5, 4, 6, 0)
EXIT_BY_KIND = {
    "vault": EXIT_VAULT,
    "auth": EXIT_AUTH,
    "network": EXIT_NETWORK,
    "busy": EXIT_BUSY,
    "cache": EXIT_CONFIG,
    "config": EXIT_CONFIG,
    "other": EXIT_FAILURE,
}
# Familles dont une panne qui se répète à l'identique n'est écrite qu'une
# fois avec `--quiet` : elles durent sans intervention (portable hors
# ligne, client ouvert qui tient le compte).
REPEAT_SILENT_KINDS = ("network", "busy")

# Attente du verrou d'un compte tenu par le client ou le menu, en secondes.
SERVICE_LOCK_WAIT_S = 5.0
# Verrou de la passe entière, sous la base du cache. Le point initial ne
# peut désigner aucun compte : un nom de compte ne commence jamais par un
# point.
SERVICE_LOCK_NAME = ".service.lock"
STATE_NAME = ".service_state.json"
LINE_MAX = 300
ADDRESS_MASK = "<…>"
_ADDRESS_RE = re.compile(r"[^\s<>\"'(),;:\[\]]+@[^\s<>\"'(),;:\[\]]+")


def _no_core() -> None:
    """Interdit le fichier core : le processus tient le mot de passe
    maître et les secrets des comptes en mémoire."""
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, OSError, ValueError):
        _logger.info("limite du fichier core non posée")


@dataclass
class ServiceDeps:
    """Ce que la commande prend de son environnement ; les tests le
    remplacent pièce à pièce."""

    # None : `ConfigFile()` du dépôt.
    config_file: object | None = None
    env: Mapping[str, str] = field(default_factory=lambda: os.environ)
    # None : `sys.stdout`.
    out: TextIO | None = None
    now: Callable[[], float] = time.time
    lock_wait: float = SERVICE_LOCK_WAIT_S
    # Connexion IMAP ; None : `imap_transport.connect`.
    connect_fn: Callable | None = None
    configure_logging: bool = True
    use_keyring: bool = True
    limit_core: Callable[[], None] = _no_core


def repo_root() -> Path:
    """La racine du dépôt qui porte ce fichier."""
    return Path(__file__).resolve().parents[4]


def parse_args(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m script.todo.mail.rules.run",
        description=t("mail_service_cli_description"),
    )
    parser.add_argument(
        "--compte",
        "--account",
        dest="account",
        metavar=t("mail_service_cli_account_metavar"),
        help=t("mail_service_cli_account_help"),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help=t("mail_service_cli_quiet_help"),
    )
    return parser.parse_args(argv)


def worst_exit(codes) -> int:
    """Le code à rendre pour plusieurs comptes, selon `EXIT_PRIORITY`."""
    codes = set(codes)
    for code in EXIT_PRIORITY:
        if code in codes:
            return code
    autres = sorted(c for c in codes if c)
    return autres[0] if autres else EXIT_OK


def redact(text) -> str:
    """Une ligne prête pour le journal : sans caractère de contrôle, toute
    adresse remplacée par `ADDRESS_MASK`, coupée à `LINE_MAX` caractères."""
    from script.todo.mail.menu import _printable

    ligne = _ADDRESS_RE.sub(ADDRESS_MASK, _printable(text))
    if len(ligne) > LINE_MAX:
        ligne = ligne[: LINE_MAX - 1] + "…"
    return ligne


def service_folder_for(account) -> Callable:
    """Le prédicat des dossiers que synchronise le service : la boîte de
    réception, et Envoyés par son rôle `sent` ou par le nom réglé sur le
    compte (même définition que `Store.activity_folders`)."""
    sent = getattr(account, "sent_folder", "") or ""

    def retenu(folder) -> bool:
        return (
            is_inbox(folder)
            or folder.role == "sent"
            or bool(sent and folder.name == sent)
        )

    return retenu


def _vault_refs(account) -> list:
    """Les références de coffre dont l'ouverture du compte a besoin : son
    secret de connexion, et la clé de son cache s'il est chiffré."""
    refs = [secret_ref_for(account)]
    if resolve_mode(account) == "encrypted":
        refs.append(account.cache_key_ref())
    return [ref or "" for ref in refs]


def kdbx_refs(account) -> list:
    """Les références `kdbx:` dont l'ouverture du compte a besoin."""
    return [ref for ref in _vault_refs(account) if ref.startswith("kdbx:")]


def keyring_refs(account) -> list:
    """Les références `keyring:` dont l'ouverture du compte a besoin."""
    return [ref for ref in _vault_refs(account) if ref.startswith("keyring:")]


def load_state(base) -> dict:
    """Le dernier état écrit par une passe, {} s'il manque ou est
    illisible : `{compte: {"held": n, "fail": "<famille>:<code>"}}`."""
    try:
        data = json.loads((Path(base) / STATE_NAME).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        nom: valeur
        for nom, valeur in data.items()
        if isinstance(nom, str) and isinstance(valeur, dict)
    }


def save_state(base, state) -> None:
    """Écrit l'état en 0600, d'un coup ; un échec est journalisé, jamais
    levé : l'état ne sert qu'à taire les répétitions."""
    path = Path(base) / STATE_NAME
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(
            dir=path.parent, prefix=f"{STATE_NAME}.", suffix=".tmp"
        )
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(state, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        tmp = None
    except (OSError, TypeError, ValueError) as exc:
        _logger.info("état du service non écrit (%s)", type(exc).__name__)
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _emit(out, text) -> None:
    print(redact(text), file=out, flush=True)


def _config_reader(config_file) -> Callable:
    """`config_file.get_config_value`, qui rend None au lieu de lever."""

    def lire(keys):
        try:
            return config_file.get_config_value(keys)
        except Exception:
            return None

    return lire


# Avertissements du moteur à texte fixe, sans donnée : ils vont tels quels
# dans la sortie. Tout autre avertissement porte le texte d'une exception
# de règle (gabarit, image absente, réglages du rapport).
_FIXED_WARNING_KEYS = (
    "mail_rules_cache_rebuilt",
    "mail_rules_catchup_warning",
    "mail_stats_snapshot_unsaved",
    "mail_rules_cap_warning",
)


def _journal_safe(bilan, nom: str):
    """`bilan` dont les avertissements libres sont remplacés par un seul
    élément fixe qui les compte ; leur texte va dans `mail.log`. Les
    avertissements à texte fixe restent."""
    fixes = {t(cle) for cle in _FIXED_WARNING_KEYS}
    libres = [texte for texte in bilan.warnings if texte not in fixes]
    if not libres:
        return bilan
    for texte in libres:
        _logger.info("%s : règles : avertissement : %s", nom, texte)
    gardes = [texte for texte in bilan.warnings if texte in fixes]
    gardes.append(f"{t('mail_service_rule_warnings')} {len(libres)}")
    return replace(bilan, warnings=gardes)


def needs_pass(account, base) -> bool:
    """Vrai si le compte a une règle active exécutable. Lit `rules.json`
    sans verrou ni écriture ; `RuleError` traverse."""
    if not storage.rules_exist(account.name, base):
        return False
    return any(
        rule.enabled and rule.action.kind in EXECUTABLE_KINDS
        for rule in storage.load(account.name, base)
    )


def main(
    argv: list[str] | None = None, *, deps: ServiceDeps | None = None
) -> int:
    """Une passe sur les comptes ; rend le code de sortie, ne lève jamais.

    Une exception imprévue donne une ligne qui ne nomme que son type, la
    trace complète dans `mail.log`, et `EXIT_FAILURE`. Le `SystemExit`
    d'`argparse` rend son code : 2 pour un argument refusé, 0 pour
    `--help`.
    """
    deps = deps or ServiceDeps()
    out = deps.out or sys.stdout
    try:
        return _main(argv, deps, out)
    except SystemExit as exc:
        if exc.code is None:
            return EXIT_OK
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    except Exception as exc:
        _logger.exception("passe du service en échec")
        _emit(out, f"{t('mail_service_unexpected')} {type(exc).__name__}")
        return EXIT_FAILURE


def _main(argv, deps: ServiceDeps, out) -> int:
    deps.limit_core()
    # `ConfigFile`, `todo_i18n` et le chemin par défaut du kdbx sont
    # relatifs à la racine du dépôt.
    os.chdir(repo_root())
    if deps.configure_logging:
        from script.todo.mail.menu import _configure_mail_logging

        _configure_mail_logging()
        logging.getLogger().setLevel(logging.WARNING)
    args = parse_args(argv)
    base = default_base()
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    with file_lock(base / SERVICE_LOCK_NAME, wait=0) as held:
        if not held:
            _emit(out, t("mail_service_already_running"))
            return EXIT_BUSY
        return _locked_main(args, deps, out, base)


def _locked_main(args, deps: ServiceDeps, out, base: Path) -> int:
    quiet = args.quiet
    try:
        tous = mail_accounts.load()
    except mail_accounts.AccountError as exc:
        _logger.info("comptes illisibles : %s", exc)
        _emit(
            out,
            f"{t('mail_service_accounts_unreadable')}"
            f" {errors.journal_detail(exc)}",
        )
        return EXIT_CONFIG
    if not tous:
        if not quiet:
            _emit(out, t("mail_service_no_account"))
        return EXIT_OK
    candidats = list(tous)
    if args.account is not None:
        candidats = [a for a in tous if a.name == args.account]
        if not candidats:
            _emit(out, f"{t('mail_service_unknown_account')} {args.account}")
            return EXIT_USAGE

    codes = []
    a_traiter = []
    for account in candidats:
        nom = account.name
        if not account.enabled:
            if not quiet or args.account is not None:
                _emit(out, f"{nom} : {t('mail_service_account_disabled')}")
            continue
        if resolve_mode(account) == "ephemeral":
            _emit(out, f"{nom} : {t('mail_service_account_ephemeral')}")
            continue
        try:
            besoin = needs_pass(account, base)
        except RuleError as exc:
            # Le texte d'une `RuleError` peut citer une valeur de règle,
            # tirée d'un sujet ou d'une adresse : journal seulement.
            _logger.info("%s : règles illisibles : %s", nom, exc)
            _emit(out, f"{nom} : {t('mail_service_rules_unreadable')}")
            codes.append(EXIT_RULE)
            continue
        if besoin:
            a_traiter.append(account)

    if not a_traiter:
        if not quiet:
            _emit(out, t("mail_service_no_active_rules"))
        return worst_exit(codes)

    from script.todo.kdbx_manager import KdbxManager
    from script.todo.mail import secrets as mail_secrets
    from script.todo.mail.secrets import SecretStore

    config_file = deps.config_file
    if config_file is None:
        config_file = ConfigFile()
    if deps.configure_logging:
        logging.getLogger().setLevel(logging.WARNING)
    maitre = credential.read_master_password(deps.env)
    manager = KdbxManager(config_file, password=maitre, interactive=False)
    secrets = SecretStore(kdbx_manager=manager, use_keyring=deps.use_keyring)
    if any(kdbx_refs(account) for account in a_traiter):
        if manager.get_kdbx() is None:
            raison = manager.last_error or "unreadable"
            cle = "mail_service_vault_" + raison
            if raison == "no_password" and not deps.env.get(
                "CREDENTIALS_DIRECTORY"
            ):
                # Hors de l'unité, systemd ne dépose pas le credential :
                # le refaire ne changerait rien.
                cle = "mail_service_vault_no_password_by_hand"
            elif raison == "wrong_password" and maitre is None:
                # Sans credential lu, le mot de passe refusé est
                # `kdbx.password` : refaire le credential n'y change rien.
                cle = "mail_service_vault_wrong_password_config"
            _emit(out, f"{t('mail_service_vault_locked')} {t(cle)}")
            return worst_exit(codes + [EXIT_VAULT])
    if deps.use_keyring and any(keyring_refs(a) for a in a_traiter):
        # Sondé d'avance, puis avant chaque lecture : le trousseau peut se
        # verrouiller entre-temps, et le service ne le déverrouille jamais.
        probleme = mail_secrets.keyring_headless_problem(deps.env)
        if probleme:
            _emit(
                out,
                f"{t('mail_service_vault_locked')} {t(probleme)}",
            )
            return worst_exit(codes + [EXIT_VAULT])
        secrets.keyring_guard = lambda: mail_secrets.keyring_headless_problem(
            deps.env
        )

    config_get = _config_reader(config_file)
    state = load_state(base)
    for account in a_traiter:
        ligne, code = _process(
            account,
            secrets=secrets,
            all_accounts=tous,
            state=state,
            deps=deps,
            quiet=quiet,
            config_get=config_get,
        )
        if ligne is not None:
            _emit(out, ligne)
        codes.append(code)
    save_state(base, state)
    return worst_exit(codes)


def _process(
    account, *, secrets, all_accounts, state, deps, quiet, config_get=None
) -> tuple:
    """Une passe pour un compte : (ligne ou None, code de sortie).

    Ouverture, vidange de la file, synchronisation d'INBOX et d'Envoyés,
    règles, puis le décompte des envois retenus. `state[nom]` reçoit le
    nombre retenu et la signature de la panne du compte. Avec `quiet`, la
    ligne n'est rendue que si elle apprend quelque chose : un élément
    autre qu'un état qui dure, un nombre retenu qui change, ou une panne
    qui n'est pas la répétition de la précédente.
    """
    from script.todo.mail.tui import (
        flush_outbox,
        held_auto_counts,
        held_auto_text,
        open_session,
    )

    nom = account.name
    precedent = state.get(nom) or {}
    entree = {"held": precedent.get("held", 0), "fail": ""}
    state[nom] = entree

    def taire(fail, kind) -> bool:
        return (
            quiet
            and kind in REPEAT_SILENT_KINDS
            and fail == precedent.get("fail")
        )

    def panne(kind, exc, texte):
        kind = kind if kind in EXIT_BY_KIND else "other"
        code = EXIT_BY_KIND[kind]
        fail = f"{kind}:{code}"
        entree["fail"] = fail
        _logger.info("%s : %s", nom, texte)
        if taire(fail, kind):
            return None, code
        detail = errors.journal_detail(exc) if exc is not None else ""
        return (
            f"{nom} : {t('mail_service_kind_' + kind)} {detail}".rstrip(),
            code,
        )

    session = None
    try:
        session = open_session(
            account,
            secrets,
            connect_fn=deps.connect_fn,
            config_get=config_get,
        )
        if session.store is None or not session.online:
            return panne(
                session.error_kind or "other",
                getattr(session, "exc", None),
                session.error,
            )

        elements = []
        # Éléments qui décrivent un état qui dure : avec `quiet`, ils ne
        # suffisent pas à écrire la ligne quand la panne se répète.
        durables = []
        code = EXIT_OK
        fail, kind_fail = "", ""

        try:
            partis, _, echoues = flush_outbox(session, now=deps.now)
        except Exception as exc:
            _logger.info("%s : file en échec : %s", nom, exc)
            elements.append(t("mail_service_outbox_error"))
        else:
            if partis:
                elements.append(f"{t('mail_outbox_flushed')} {partis}")
            if echoues:
                elements.append(f"{t('mail_outbox_failed')} {echoues}")

        try:
            report = session.sync(only=service_folder_for(account))
        except Exception as exc:
            return panne(errors.classify(exc), exc, str(exc))
        if report.errors:
            element = f"{t('mail_service_folder_errors')} {len(report.errors)}"
            elements.append(element)
            durables.append(element)
            code = worst_exit([code, EXIT_NETWORK])
            fail, kind_fail = f"network:{EXIT_NETWORK}", "network"

        bilan = engine.run_pass(
            session,
            report=report,
            all_accounts=all_accounts,
            verrou=None,
            now=deps.now,
            lock_wait=deps.lock_wait,
        )
        if bilan.status == "locked":
            element = t("mail_service_busy")
            elements.append(element)
            durables.append(element)
            code = worst_exit([code, EXIT_BUSY])
            if not fail:
                fail, kind_fail = f"busy:{EXIT_BUSY}", "busy"
        elif bilan.status == "error":
            elements.append(t("mail_service_rule_error"))
            code = worst_exit([code, EXIT_RULE])
            fail, kind_fail = f"rule:{EXIT_RULE}", "rule"
        if t("mail_rules_error") in bilan.warnings:
            # Le moteur ne lève cet avertissement que pour un rattrapage
            # d'en-têtes en échec : ses messages restent des trous, repris
            # à la passe suivante. Le texte du TUI renvoie à sa touche
            # « l » ; le journal reçoit le sien, et le code d'une panne
            # de lien comme un dossier en erreur.
            bilan = replace(
                bilan,
                warnings=[
                    w for w in bilan.warnings if w != t("mail_rules_error")
                ],
            )
            element = t("mail_service_catchup_failed")
            elements.append(element)
            durables.append(element)
            code = worst_exit([code, EXIT_NETWORK])
            if not fail:
                fail, kind_fail = f"network:{EXIT_NETWORK}", "network"
        bilan_items = engine.summary_items(
            _journal_safe(bilan, nom), with_status=False
        )
        elements.extend(bilan_items)
        if bilan.status == "locked":
            # Le verrou n'a pas été pris : les compteurs à zéro ne disent
            # rien de plus que « déjà en cours ».
            durables.extend(bilan_items)
        for erreur in bilan.errors:
            _logger.info("%s : règles : %s", nom, erreur)

        retenus = sum(
            nombre for _, nombre in held_auto_counts([session], now=deps.now())
        )
        if retenus:
            element = held_auto_text(retenus) + " (o)"
            elements.append(element)
            durables.append(element)
        held_change = retenus != precedent.get("held", 0)
        entree["held"] = retenus
        entree["fail"] = fail

        ligne = f"{nom} : " + " · ".join(
            [f"{report.new_messages} {t('mail_new_messages')}"] + elements
        )
        if not quiet:
            return ligne, code
        nouveau = [e for e in elements if e not in durables]
        panne_neuve = bool(fail) and not taire(fail, kind_fail)
        if nouveau or held_change or panne_neuve:
            return ligne, code
        return None, code
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    sys.exit(main())
