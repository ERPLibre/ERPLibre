#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les entrées de menu du client courriel.

Ce module est le SEUL point de contact entre le paquet `mail` et le CLI :
`todo.py` importe `prompt_execute_mail` et rien d'autre. Le sens de la
dépendance est volontaire — `mail` ne doit jamais importer `todo`. Les
menus du courriel sont déclarés dans `script/todo/menus/assistant.py`, et
s'ouvrent sur `MailMenus`, qui porte leurs actions.
"""

from __future__ import annotations

import getpass
import logging
import os
import shutil
from pathlib import Path

from script.todo import todo_prefs, ui
from script.todo.mail import account_setup
from script.todo.mail import accounts as mail_accounts
from script.todo.mail.accounts import PRESETS, AccountError
from script.todo.mail.secrets import SecretError, SecretStore
from script.todo.mail.store import Store, StoreError, resolve_mode
from script.todo.menus import assistant as menus_assistant
from script.todo.todo_i18n import t
from script.todo.ui.navigator import navigate

CACHE_MODES = ("clear", "encrypted", "ephemeral")

# Chemin proposé par défaut pour un kdbx nouvellement créé — voir
# `account_setup.py`, la seule source de vérité, aussi utilisée par le TUI.
_DEFAULT_KDBX_PATH = account_setup.DEFAULT_KDBX_PATH

# `True` une fois `_configure_mail_logging` passée : évite d'empiler un
# second `FileHandler` si l'utilisateur rouvre le menu courriel plusieurs
# fois dans le même processus `todo`.
_LOG_CONFIGURED = False


def mail_log_path() -> Path:
    """Le chemin du journal du paquet `mail` — SOURCE UNIQUE, pour que
    `_configure_mail_logging` (ci-dessous) et `tui.LogScreen` (touche `l`,
    qui affiche sa fin) ne puissent jamais en dériver deux formules
    différentes."""
    return Path(os.path.expanduser("~/.erplibre")) / "mail.log"


def _configure_mail_logging() -> None:
    """Branche le journal du paquet `mail` sur `mail_log_path()`.

    Les modules du paquet (`imap_sync.py`, `tui.py`, ...) ne font
    qu'appeler `_logger.exception(...)` : brancher un GESTIONNAIRE est le
    travail de L'APPLICATION, pas d'une bibliothèque — c'est pourquoi cette
    fonction vit ici, au seul point d'entrée du paquet (voir le docstring du
    module), et jamais dans `mail/*.py`. Jamais vers la console non plus :
    Textual possède le terminal pendant tout le TUI, et une ligne de log qui
    s'y mêlerait corromprait l'affichage.
    """
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED:
        return
    log_path = mail_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    # Sur le logger PARENT de tout le paquet (`script.todo.mail`, préfixe
    # commun de `script.todo.mail.tui`, `script.todo.mail.imap_sync`, ...) :
    # un seul gestionnaire couvre tous les modules, sans qu'aucun d'eux
    # n'ait à en connaître l'existence.
    logger = logging.getLogger("script.todo.mail")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # `todo.py` appelle `logging.basicConfig()` à l'IMPORT, ce qui pose un
    # `StreamHandler` sur le logger RACINE. `propagate` vaut `True` par
    # défaut : sans cette ligne, chaque `_logger.exception(...)` du paquet
    # remonterait AUSSI jusqu'à ce gestionnaire — donc sur le terminal que
    # Textual possède pendant tout le TUI, silencieusement.
    logger.propagate = False
    _LOG_CONFIGURED = True


def secret_store_for(todo) -> SecretStore:
    """Le coffre du CLI : son kdbx s'il en a un, sinon le trousseau système."""
    manager = getattr(todo, "kdbx_manager", None)
    return SecretStore(kdbx_manager=manager, use_keyring=True)


def cache_summary(accounts, base=None, prefs_get=None) -> list[dict]:
    """Nom, mode effectif et taille sur disque, pour l'écran de cache."""
    rows = []
    for account in accounts:
        mode = resolve_mode(account, prefs_get)
        size = 0
        try:
            root = Store(account, mode=mode, base=base).root
            if root.is_dir():
                size = sum(
                    p.stat().st_size for p in root.rglob("*") if p.is_file()
                )
        except Exception:
            # Un cache absent, un lien symbolique refusé ou un disque
            # inaccessible ne doivent pas empêcher d'afficher les AUTRES
            # comptes : la taille retombe simplement à zéro pour celui-ci.
            size = 0
        rows.append({"name": account.name, "mode": mode, "size": size})
    return rows


def _load_accounts():
    try:
        return mail_accounts.load()
    except AccountError as exc:
        print(exc)
        return []


def prompt_execute_mail(todo) -> None:
    """Le menu du courriel (MAIL, `menus/assistant.py`), sous le fil
    d'Ariane du menu de `todo` qui l'ouvre : le client, les comptes, une
    synchronisation, le cache. Branche d'abord le journal du paquet. Rend
    None sur [0]."""
    _configure_mail_logging()
    return navigate(MailMenus(todo), menus_assistant.MAIL)


def _open_tui(todo) -> None:
    from script.todo.mail.tui import open_sessions, run_tui

    accounts = _load_accounts()
    secrets = secret_store_for(todo)
    sessions = open_sessions(accounts, secrets)
    try:
        # Un TUI sans aucun compte n'est pas une impasse : `config_file` et
        # `secrets` lui permettent d'en créer un depuis l'écran d'ajout.
        run_tui(
            sessions=sessions,
            config_file=todo.config_file,
            secret_store=secrets,
        )
    finally:
        for session in sessions:
            session.close()


def _sync_now(todo) -> None:
    from script.todo.mail.tui import open_sessions

    accounts = _load_accounts()
    if not accounts:
        print(t("mail_no_account"))
        return
    sessions = open_sessions(accounts, secret_store_for(todo))
    try:
        for session in sessions:
            if not session.online:
                print(f"{session.account.name} : {session.error}")
                continue
            report = session.sync()
            print(
                f"{session.account.name} : {report.new_messages}"
                f" {t('mail_new_messages')}"
            )
            for error in report.errors:
                print(f"  {error}")
            if report.purged:
                print(
                    f"  {t('mail_folders_resynced')}"
                    f" {', '.join(report.purged)}"
                )
    finally:
        for session in sessions:
            session.close()


def prompt_mail_accounts(todo) -> None:
    """Les comptes (MAIL_ACCOUNTS, `menus/assistant.py`) : les lister, en
    ajouter, en supprimer, écrire un modèle, en tester un. Rend None sur
    [0]."""
    return navigate(MailMenus(todo), menus_assistant.MAIL_ACCOUNTS)


def _list_accounts() -> None:
    accounts = _load_accounts()
    if not accounts:
        print(t("mail_no_account"))
        return
    for account in accounts:
        mark = "" if account.enabled else f" ({t('disabled')})"
        print(
            f"  {account.name}{mark} — {account.email}"
            f" — {account.imap.host} / {account.smtp.host}"
        )


def _ensure_kdbx(todo) -> bool:
    """Vrai si un kdbx est utilisable pour la suite de `_add_account`.

    Si `kdbx.path` est déjà configuré, ne pose aucune question — c'est le
    cas courant après la première utilisation. Sinon, offre deux choix :
    créer un nouveau `.kdbx` ou en choisir un existant ; [0] n'en fait
    rien.
    """
    if todo.config_file.get_config_value(["kdbx", "path"]):
        return True

    choice = ui.choose(
        t("mail_kdbx_none_configured"),
        range(2),
        labels=[t("mail_kdbx_menu_create"), t("mail_kdbx_menu_choose")],
    )
    if choice == 0:
        return _create_kdbx_interactive(todo)
    if choice == 1:
        return _choose_kdbx_interactive(todo)
    return False


def _create_kdbx_interactive(todo) -> bool:
    prompt = f"{t('mail_kdbx_ask_path_new')} [{_DEFAULT_KDBX_PATH}]: "
    path = input(prompt).strip() or _DEFAULT_KDBX_PATH

    password = getpass.getpass(t("mail_kdbx_ask_password"))
    confirm = getpass.getpass(t("mail_kdbx_ask_password_confirm"))
    if password != confirm:
        print(t("mail_kdbx_password_mismatch"))
        return False

    try:
        account_setup.create_vault(todo.config_file, path, password)
    except SecretError as exc:
        print(exc)
        return False

    print(f"{t('mail_kdbx_created')} {path}")
    return True


def _choose_kdbx_interactive(todo) -> bool:
    path = input(t("mail_kdbx_ask_path_existing")).strip()
    try:
        account_setup.use_existing_vault(todo.config_file, path)
    except SecretError:
        print(f"{t('mail_kdbx_path_not_found')} {path}")
        return False

    print(f"{t('mail_kdbx_path_recorded')} {path}")
    return True


def _add_account(todo) -> None:
    if not _ensure_kdbx(todo):
        return

    store = secret_store_for(todo)
    if not store.available_backends():
        print(t("mail_no_vault"))
        return

    name = input(t("mail_ask_name")).strip()
    email_addr = input(t("mail_ask_email")).strip()
    display = input(t("mail_ask_display_name")).strip()

    # Un fournisseur se choisit par son numéro ou par son libellé ; une
    # réponse vide prend le générique, qui demande les serveurs ; [0]
    # renonce au compte.
    keys = list(PRESETS)
    labels = [PRESETS[key]["label"] for key in keys]
    rank = ui.choose(
        t("mail_ask_preset").strip(),
        range(len(keys)),
        default=keys.index("generic"),
        labels=labels,
        names={label: rank for rank, label in enumerate(labels)},
    )
    if rank is None:
        return
    preset_key = keys[rank]

    vault = "kdbx" if "kdbx" in store.available_backends() else "keyring"
    try:
        account = mail_accounts.account_from_preset(
            name, email_addr, preset_key, display_name=display, vault=vault
        )
    except AccountError as exc:
        print(exc)
        return

    if preset_key == "generic":
        account.imap.host = input(t("mail_ask_imap_host")).strip()
        account.smtp.host = input(t("mail_ask_smtp_host")).strip()
    attendu_app = bool(PRESETS[preset_key]["app_password"])
    if attendu_app:
        print(t("mail_app_password_note"))
        print(f"  {t(PRESETS[preset_key]['note_key'])}")

    password = getpass.getpass(
        t("mail_ask_app_password" if attendu_app else "mail_ask_password")
    )
    existing = [a for a in _load_accounts() if a.name != account.name]
    try:
        account_setup.save_new_account(
            store, existing + [account], account, password
        )
    except (SecretError, AccountError, OSError) as exc:
        # Une exception qui remonte ici tuerait le menu ; `save_new_account`
        # a déjà annulé l'écriture du secret si la sauvegarde a échoué.
        print(exc)
        return
    print(t("mail_account_saved"))


def _pick_account():
    """(le compte choisi, ou None, et tous les comptes) : un compte se
    choisit par son numéro tel que la liste l'écrit ou par son nom, sous
    les règles de `ui.choose` ; None pour [0] ou une réponse vide."""
    accounts = _load_accounts()
    if not accounts:
        print(t("mail_no_account"))
        return None, []
    names = [account.name for account in accounts]
    name = ui.choose(t("mail_ask_account").strip(), names)
    return (None if name is None else accounts[names.index(name)]), accounts


def _delete_account(todo) -> None:
    account, accounts = _pick_account()
    if account is None:
        return
    try:
        secret_store_for(todo).delete(account.secret_ref)
    except SecretError:
        # Le secret peut avoir déjà disparu : ce n'est pas une raison de
        # garder le compte dans la configuration.
        pass
    mail_accounts.save([a for a in accounts if a.name != account.name])
    print(t("mail_account_deleted"))


def _write_template() -> None:
    try:
        path = mail_accounts.write_template()
    except AccountError as exc:
        print(exc)
        return
    print(f"{t('mail_template_written')} {path}")


def _looks_like_auth_failure(cause) -> bool:
    """Le serveur a-t-il RÉPONDU, ou n'est-il rien revenu ?

    La question n'est pas « le message ressemble-t-il à un refus » : une
    liste de libellés attendus est toujours en retard sur les serveurs
    réels. Gmail répond « [ALERT] Application-specific password required »
    une fois la double authentification active, sans « invalid
    credentials » ni aucun mot d'un refus.

    On teste donc l'inverse, qui est structurel : `imaplib` lève
    `IMAP4.error` quand le SERVEUR a parlé, et un `OSError` (délai,
    coupure, DNS) quand rien n'est revenu. Seul ce second cas fait taire la
    note. Une cause inconnue l'affiche : c'est un conseil, pas un verdict —
    le donner à tort coûte une ligne, le taire à tort coûte la panne.
    """
    if cause is None:
        return True
    origine = getattr(cause, "__cause__", None)
    if isinstance(origine, OSError):
        return False
    # Sans exception d'origine (une chaîne, un test), on retombe sur les
    # formulations qui disent explicitement que rien n'est revenu.
    bas = str(cause).lower()
    return not any(
        muet in bas
        for muet in ("timed out", "timeout", "unreachable", "not known")
    )


def retry_password(
    todo, account, attempts: int = 3, connect_fn=None, cause=None
) -> bool:
    """Redemande le mot de passe jusqu'à ce qu'il passe. Vrai si le coffre a
    été mis à jour.

    L'écriture n'a lieu QU'APRÈS une connexion réussie : remplacer un mot de
    passe valide par une faute de frappe serait pire que l'échec initial.
    """
    if connect_fn is None:
        from script.todo.mail.imap_transport import connect as connect_fn

    store = secret_store_for(todo)
    # C'est ICI que la note sert, pas seulement à l'ajout du compte : on
    # vient de se faire refuser et on redemande un mot de passe. Gmail,
    # Outlook et iCloud répondent « Invalid credentials » au mot de passe
    # habituel exactement comme à une faute de frappe — sans cette ligne,
    # l'invite pousse à retaper le même, et à se le faire refuser autant de
    # fois qu'on le redemande.
    preset = PRESETS.get(account.preset, {})
    attendu_app = bool(preset.get("app_password"))
    if attendu_app and _looks_like_auth_failure(cause):
        print(t("mail_app_password_note"))
        print(f"  {t(preset['note_key'])}")
    # L'invite elle-même nomme ce qu'on attend. « Mot de passe : » inviterait
    # à saisir CELUI DU COMPTE, que ces fournisseurs refusent — la note
    # au-dessus se lit une fois, l'invite se relit à chaque tentative.
    invite = t("mail_ask_app_password" if attendu_app else "mail_ask_password")
    for _ in range(attempts):
        password = getpass.getpass(invite)
        if not password:
            return False
        try:
            transport = connect_fn(account, password)
        except Exception as exc:
            # `connect_fn` peut lever `ImapError` ou n'importe quelle erreur
            # réseau brute (`OSError`, ...) : les deux méritent la même
            # invite à ressaisir, pas un plantage du menu.
            print(f"{t('mail_connection_failed')} {exc}")
            continue
        transport.logout()
        store.set(account.secret_ref, password)
        print(t("mail_connection_ok"))
        return True
    return False


def _test_account(todo) -> None:
    from script.todo.mail.imap_transport import connect

    account, _ = _pick_account()
    if account is None:
        return
    # Le coffre peut refuser de s'ouvrir — mauvais mot de passe KeePass,
    # fichier absent, coffre non configuré. C'est un renoncement de
    # l'utilisateur ou une erreur qu'il peut corriger, pas de quoi faire
    # tomber le CLI : on le dit et on revient au menu.
    try:
        password = secret_store_for(todo).get(account.secret_ref)
    except SecretError as exc:
        print(f"{t('mail_connection_failed')} {exc}")
        return
    if not password:
        print(t("mail_no_password_stored"))
        return
    try:
        transport = connect(account, password)
        folders = transport.list_folders()
        transport.logout()
    except Exception as exc:
        # Connexion refusée, mot de passe expiré, ou LIST qui échoue : dans
        # tous les cas, offrir de resaisir le mot de passe plutôt que de
        # faire tomber le menu.
        print(f"{t('mail_connection_failed')} {exc}")
        retry_password(todo, account, cause=exc)
        return
    print(f"{t('mail_connection_ok')} {len(folders)}")


def prompt_mail_cache(todo) -> None:
    """Le cache (MAIL_CACHE, `menus/assistant.py`) : le mode par défaut,
    celui d'un compte, la taille et la purge. Redessiné à chaque tour, le
    mode par défaut relu. Rend None sur [0]."""
    return navigate(MailMenus(todo), menus_assistant.MAIL_CACHE)


def _cache_mode() -> str:
    """Le mode de cache par défaut, que Cache montre entre parenthèses."""
    return todo_prefs.get("mail_cache_mode", "clear")


def _set_cache_mode() -> None:
    """Demande le mode de cache par défaut, par son numéro ou son nom, et
    le retient ; [0] le laisse tel quel."""
    mode = ui.choose(t("mail_cache_default_mode"), CACHE_MODES)
    if mode is not None:
        todo_prefs.set("mail_cache_mode", mode)


def _set_account_cache_mode() -> None:
    """Demande un compte, puis son mode de cache, par son numéro ou son
    nom, ou le mode par défaut, la dernière entrée ; [0] laisse le compte
    tel quel."""
    account, accounts = _pick_account()
    if account is None:
        return
    mode = ui.choose(
        t("mail_cache_account_mode"),
        [*CACHE_MODES, ""],
        labels=[*CACHE_MODES, t("mail_cache_default_mode")],
        names=dict(zip(CACHE_MODES, CACHE_MODES)),
    )
    if mode is None:
        return
    account.cache_mode = mode or None
    mail_accounts.save(accounts)


def _cache_size_and_purge(todo) -> None:
    accounts = _load_accounts()
    if not accounts:
        print(t("mail_no_account"))
        return
    for row in cache_summary(accounts):
        size = f"{row['size'] // 1024} {t('mail_size_kb')}"
        print(f"  {row['name']} — {row['mode']} — {size}")
    account, _ = _pick_account()
    if account is None:
        return
    if input(t("mail_purge_confirm")).strip().lower() not in ("o", "y"):
        return
    store = Store(account, secrets=secret_store_for(todo))
    try:
        store.open()
    except StoreError as exc:
        # Le cache est illisible : on ne peut pas le vider par SQL, mais c'est
        # exactement le cas où l'utilisateur a besoin qu'il disparaisse.
        print(exc)
        shutil.rmtree(store.root, ignore_errors=True)
        print(t("mail_purged"))
        return
    try:
        store.purge_all()
    finally:
        store.close()
    print(t("mail_purged"))


class MailMenus:
    """L'objet sur lequel s'ouvrent les menus du courriel : chaque action
    qu'ils nomment est la fonction de ce module de même nom, qui le reçoit
    à la place du TODO qu'il enveloppe ; tout autre attribut,
    `fill_help_info` compris, est celui de ce TODO. Les menus se dessinent
    ainsi sous le fil d'Ariane du menu de TODO qui les ouvre, sans segment
    propre, et leur clé de télémétrie est la sienne."""

    def __init__(self, todo):
        self.todo = todo.todo if isinstance(todo, MailMenus) else todo

    def __getattr__(self, name):
        return getattr(self.todo, name)

    prompt_mail_accounts = prompt_mail_accounts
    prompt_mail_cache = prompt_mail_cache
    _open_tui = _open_tui
    _sync_now = _sync_now
    _add_account = _add_account
    _delete_account = _delete_account
    _test_account = _test_account
    _cache_size_and_purge = _cache_size_and_purge
    _list_accounts = staticmethod(_list_accounts)
    _write_template = staticmethod(_write_template)
    _cache_mode = staticmethod(_cache_mode)
    _set_cache_mode = staticmethod(_set_cache_mode)
    _set_account_cache_mode = staticmethod(_set_account_cache_mode)
