#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les entrées de menu du client courriel.

Ce module est le SEUL point de contact entre le paquet `mail` et le CLI :
`todo.py` importe `prompt_execute_mail` et rien d'autre. Le sens de la
dépendance est volontaire — `mail` ne doit jamais importer `todo`.
"""

from __future__ import annotations

import contextlib
import getpass
import logging
import os
import resource
import sys
import unicodedata
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import click

from script.todo import todo_prefs
from script.todo.mail import account_setup
from script.todo.mail import accounts as mail_accounts
from script.todo.mail.accounts import PRESETS, AccountError
from script.todo.mail.secrets import SecretError, SecretStore
from script.todo.mail.store import (
    CONVERT_STATE_NAME,
    PERSISTENT_MODES,
    PROBE_UNKNOWN,
    CacheBusy,
    CacheKeyMissing,
    CacheModeMismatch,
    Store,
    StoreError,
    cache_ctl_dir,
    cache_exclusive,
    cache_root,
    default_base,
    epoch_salted_clear,
    has_clear_residue,
    inscribed_mode,
    mode_request,
    probe_connection,
    resolve_mode,
    shown_mode,
)
from script.todo.todo_couleur import retour
from script.todo.todo_i18n import t

CACHE_MODES = ("clear", "encrypted", "ephemeral")

_logger = logging.getLogger(__name__)

# Chemin proposé par défaut pour un kdbx nouvellement créé — voir
# `account_setup.py`, la seule source de vérité, aussi utilisée par le TUI.
_DEFAULT_KDBX_PATH = account_setup.DEFAULT_KDBX_PATH

# `True` une fois `_configure_mail_logging` passée : évite d'empiler un
# second `FileHandler` si l'utilisateur rouvre le menu courriel plusieurs
# fois dans le même processus `todo`.
_LOG_CONFIGURED = False

# Les loggers racines du client courriel : le paquet `script.todo.mail`
# et le noyau qu'il importe.
MAIL_LOGGERS = ("script.todo.mail", "erplibre_mail_core")


def _printable(text) -> str:
    """`text` sans caractère de contrôle ni de format, ESC compris.

    Sujets et libellés arrivent décodés RFC 2047 : un « =1B » encodé y
    devient une vraie séquence d'échappement, que le terminal exécuterait
    (presse-papiers, curseur, lignes réécrites). Un blanc de contrôle
    (tabulation, saut de ligne) devient une espace ; le reste disparaît.
    """
    return "".join(
        (" " if char.isspace() else "")
        if unicodedata.category(char) in ("Cc", "Cf")
        else char
        for char in str(text or "")
    )


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
    # Sur les deux loggers RACINES de `MAIL_LOGGERS` (`script.todo.mail`,
    # préfixe commun de `script.todo.mail.tui`, `script.todo.mail.imap_sync`,
    # ... ; `erplibre_mail_core`, celui de `erplibre_mail_core.smtp`, ...) :
    # un seul gestionnaire couvre tous les modules, sans qu'aucun d'eux
    # n'ait à en connaître l'existence.
    for nom in MAIL_LOGGERS:
        logger = logging.getLogger(nom)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        # `todo.py` appelle `logging.basicConfig()` à l'IMPORT, ce qui pose
        # un `StreamHandler` sur le logger RACINE. `propagate` vaut `True`
        # par défaut : sans cette ligne, chaque `_logger.exception(...)` du
        # paquet remonterait AUSSI jusqu'à ce gestionnaire — donc sur le
        # terminal que Textual possède pendant tout le TUI, silencieusement.
        # La fuite se voit aussi hors du TUI : sous `unittest`, les lignes
        # du paquet se mêlent à la sortie pointillée dès qu'un test importe
        # `todo` avant les tests courriel dans le même processus.
        logger.propagate = False
    _LOG_CONFIGURED = True


def secret_store_for(todo) -> SecretStore:
    """Le coffre du CLI : son kdbx s'il en a un, sinon le trousseau système."""
    manager = getattr(todo, "kdbx_manager", None)
    return SecretStore(kdbx_manager=manager, use_keyring=True)


def cache_summary(accounts, base=None, prefs_get=None) -> list[dict]:
    """Nom, mode effectif, mode inscrit et taille sur disque, pour l'écran
    de cache.

    `inscribed` est le mode inscrit dans le cache persistant (None sans
    cache) ; `refused` dit qu'une ouverture serait refusée : le mode
    demandé est persistant et le cache en inscrit un autre (illisible
    exclu : l'ouverture tranche alors sous son verrou)."""
    rows = []
    for account in accounts:
        mode = resolve_mode(account, prefs_get, base=base)
        inscrit = inscribed_mode(account, base)
        refused = (
            mode in PERSISTENT_MODES
            and inscrit not in (None, PROBE_UNKNOWN)
            and inscrit != mode
        )
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
        rows.append(
            {
                "name": account.name,
                "mode": mode,
                "size": size,
                "inscribed": inscrit,
                "refused": refused,
            }
        )
    return rows


def _load_accounts():
    try:
        return mail_accounts.load()
    except AccountError as exc:
        print(exc)
        return []


def prompt_execute_mail(todo) -> None:
    _configure_mail_logging()
    while True:
        help_info = f"""{todo._menu_header()}
[1] {t("mail_open_tui")}
[2] {t("mail_accounts_menu")}
[3] {t("mail_sync_now")}
[4] {t("mail_cache_menu")}
[5] {t("mail_stats_menu")}
[6] {t("mail_rules_menu")}
[7] {t("mail_rules_menu_service")}
{retour(t('Back'))}"""
        status = click.prompt(help_info)
        print()
        if status == "0":
            return
        if status == "1":
            _open_tui(todo)
        elif status == "2":
            prompt_mail_accounts(todo)
        elif status == "3":
            _sync_now(todo)
        elif status == "4":
            prompt_mail_cache(todo)
        elif status == "5":
            _show_stats(todo)
        elif status == "6":
            prompt_mail_rules(todo)
        elif status == "7":
            # Hors du choix d'un compte : le service est commun à tous, et
            # reste à désinstaller quand il n'y a plus de compte ou que
            # tous ont un cache éphémère.
            _service_menu(todo)
        else:
            print(t("Command not found !"))


# Lignes du journal des règles imprimées par le menu, les plus récentes.
RULES_MENU_LOG_LINES = 50


def prompt_mail_rules(todo, *, base=None) -> None:
    """Menu [6] : lister, activer, déplacer, supprimer les règles d'un
    compte, lire leur journal, régler le rapport de statistiques et
    essayer une règle sur un message, sans ouvrir le TUI. L'entrée [8]
    gère le service sans interface, commun à tous les comptes, comme
    l'entrée [7] de `prompt_execute_mail`.

    La création et l'édition passent par le TUI (touche `e`) : un arbre
    de filtre ne se saisit pas ligne à ligne. La base des règles vient du
    cache du compte (`storage.base_of`) ; un cache éphémère n'a pas de
    règles, et le menu le dit sans rien toucher. Activer une règle depuis
    le menu ne l'arme pas : le moteur l'arme à sa passe suivante, et elle
    ne voit que ce qui arrive après.
    """
    from script.todo.mail.rules import storage
    from script.todo.mail.rules.model import RuleError

    account, _ = _pick_account("mail_rules_menu_pick_account")
    if account is None:
        return
    rules_base = storage.base_of(
        Store(account, mode=resolve_mode(account, base=base), base=base)
    )
    if rules_base is None:
        print(t("mail_rules_ephemeral"))
        return
    print(t("mail_rules_menu_edit_in_tui"))
    while True:
        help_info = f"""{todo._menu_header()}
[1] {t("mail_rules_menu_list")}
[2] {t("mail_rules_menu_toggle")}
[3] {t("mail_rules_menu_move")}
[4] {t("mail_rules_menu_delete")}
[5] {t("mail_rules_menu_journal")}
[6] {t("mail_rules_menu_report")}
[7] {t("mail_rules_menu_trial")}
[8] {t("mail_rules_menu_service")}
{retour(t('Back'))}"""
        status = click.prompt(help_info)
        print()
        if status == "0":
            return
        try:
            if status == "1":
                _list_rules(account.name, rules_base)
                _print_claim_mode(account.name, rules_base)
            elif status in ("2", "3", "4"):
                _change_rule(account.name, rules_base, status)
            elif status == "5":
                _show_rules_log(todo, account, rules_base, base)
            elif status == "6":
                _report_settings(todo, account, rules_base, base)
            elif status == "7":
                _trial(todo, account, rules_base, base)
            elif status == "8":
                _service_menu(todo)
            else:
                print(t("Command not found !"))
        except RuleError as exc:
            # `RulesBusy` comprise : une passe tient le verrou du compte.
            print(exc)


# Réponses qui valent « oui » aux questions (o/N) du service.
_YES = ("o", "oui", "y", "yes")
# Réponses qui gardent le credential à la désinstallation (O/n).
_NO = ("n", "non", "no")


def _ask_yes(key: str) -> bool:
    """Pose la question `key` ; vrai seulement sur une réponse de `_YES`
    (le défaut est non)."""
    return input(f"{t(key)} ").strip().lower() in _YES


def _ask_text_yes(question: str) -> bool:
    """Pose `question` suivie de (o/N) ; vrai seulement sur une réponse de
    `_YES`."""
    return (
        input(f"{question} {t('mail_menu_yes_no')} ").strip().lower() in _YES
    )


def _ask_typed_word(question: str, mot: str | None = None) -> bool:
    """Confirmation d'un risque : imprime `question`, puis demande de
    taper le mot affiché ; vrai seulement si la saisie, blancs retirés,
    l'égale sans tenir compte de la casse. Ni `o` ni une réponse vide ne
    suffisent. Sans `mot`, celui d'un risque de double envoi."""
    if mot is None:
        mot = t("mail_confirm_risk_word")
    print(question)
    saisie = input(f"{t('mail_confirm_risk_ask')} {mot} : ").strip().lower()
    return bool(saisie) and saisie == mot.strip().lower()


def _service_menu(
    todo,
    *,
    run=None,
    getpass_fn=None,
    isatty=lambda: sys.stdin.isatty(),
) -> None:
    """Entrée [8] du menu [6] : installer, alimenter, lancer ou retirer le
    service systemd des règles, commun à tous les comptes.

    `run` (signature de `subprocess.run`) est transmis à chaque appel
    système ; None vaut `subprocess.run`, résolu à l'appel. Le mot de
    passe maître n'est ni imprimé, ni passé à `click.prompt`.
    """
    from script.todo.mail import service

    comptes = _load_accounts()
    while True:
        print(
            service.status_text(
                service.status(
                    run=run, config_file=getattr(todo, "config_file", None)
                )
            )
        )
        for ligne in _claim_lines(comptes) + _held_lines(default_base()):
            print(ligne)
        help_info = f"""{todo._menu_header()}
[1] {t("mail_service_menu_install")}
[2] {t("mail_service_menu_credential")}
[3] {t("mail_service_menu_start")}
[4] {t("mail_service_menu_uninstall")}
[5] {t("mail_service_menu_held_release")}
[6] {t("mail_service_menu_claim_release")}
{retour(t('Back'))}"""
        status = click.prompt(help_info)
        print()
        if status == "0":
            return
        if status == "1":
            _service_install(todo, run)
        elif status == "2":
            _service_credential(
                todo, run=run, getpass_fn=getpass_fn, isatty=isatty
            )
        elif status == "3":
            code, sortie = service.start_now(run=run)
            if code == 0:
                print(t("mail_service_started"))
            else:
                print(f"{t('mail_service_install_failed')} {sortie}")
        elif status == "4":
            _service_uninstall(run)
        elif status == "5":
            _service_held(todo)
        elif status == "6":
            _service_claims(todo)
        else:
            print(t("Command not found !"))


def _service_stores(todo, base):
    """Les comptes actifs dont le cache peut porter des règles, chacun
    avec une fonction qui ouvre son cache (coffre seulement s'il est
    chiffré) ; un cache éphémère n'a pas de règles et n'est pas rendu."""
    comptes = []
    for account in _load_accounts():
        if not getattr(account, "enabled", True):
            continue
        if resolve_mode(account, base=base) == "ephemeral":
            continue

        def ouvrir(account=account):
            magasin = Store(
                account,
                secrets=secret_store_for(todo)
                if _needs_vault(account, base)
                else None,
                base=base,
            )
            magasin.open()
            return magasin

        comptes.append((account, ouvrir))
    return comptes


def _choose(nombre: int) -> int | None:
    """Le numéro choisi dans une liste de `nombre` lignes, None pour
    revenir ou pour un numéro hors liste (dit à l'écran)."""
    choix = str(click.prompt(t("mail_service_pick"), default="0")).strip()
    if choix == "0":
        return None
    if not choix.isdigit() or not 1 <= int(choix) <= nombre:
        print(t("Command not found !"))
        return None
    return int(choix)


def _service_held(todo, *, open_session_fn=None, base=None) -> None:
    """[5] du menu du service : relire et relâcher les envois automatiques
    retenus de tous les comptes, depuis une machine sans écran.

    La liste est lue en direct, caches ouverts puis refermés ; l'entrée
    choisie est montrée (aperçu), puis relâchée après un « oui » par
    `release.release_held`, qui revendique son message sur le serveur. Un
    relâchement qui demande confirmation pose sa question de risque (mot à
    taper), au plus deux fois : un verdict qui change entre-temps pose la
    sienne. Aucune panne ne fait sortir du menu.
    """
    try:
        _service_held_work(todo, open_session_fn=open_session_fn, base=base)
    except Exception as exc:
        _logger.exception("menu du service : envois retenus")
        print(f"{t('mail_rules_error')} {type(exc).__name__}")


def _service_held_work(todo, *, open_session_fn, base) -> None:
    import time

    from script.todo.mail import tui
    from script.todo.mail.rules import release
    from script.todo.mail.store import OUTBOX_AUTO_KINDS

    maintenant = int(time.time())
    lignes = []
    for account, ouvrir in _service_stores(todo, base):
        try:
            magasin = ouvrir()
        except Exception as exc:
            print(
                f"  {_printable(account.name)} : {t('mail_rules_error')} {exc}"
            )
            continue
        try:
            for e in magasin.outbox():
                if not e["held"] or e["kind"] not in OUTBOX_AUTO_KINDS:
                    continue
                if e["expires_at"] and e["expires_at"] < maintenant:
                    continue
                etat = (
                    magasin.rule_log_state(e["rule_id"], e["source_key"])
                    if e["rule_id"]
                    else None
                )
                lignes.append((account, e, (etat or {}).get("reason") or ""))
        finally:
            magasin.close()
    if not lignes:
        print(t("mail_service_held_none"))
        return
    for n, (account, e, raison) in enumerate(lignes, start=1):
        texte_raison = t("mail_rules_reason_" + raison) if raison else ""
        echeance = (
            f"{t('mail_outbox_expires')} {tui.format_epoch(e['expires_at'])}"
            if e["expires_at"]
            else ""
        )
        print(
            f"[{n}] {_printable(account.name)} — {_printable(e['subject'])}"
            f" — {_printable(e['to'])} — {texte_raison} — {echeance}"
        )
    choix = _choose(len(lignes))
    if choix is None:
        return
    account, entree, _raison = lignes[choix - 1]
    session = (open_session_fn or tui.open_session)(
        account,
        secret_store_for(todo),
        base=base,
        config_get=_config_get(todo),
    )
    try:
        if session.store is None:
            print(f"  {_printable(account.name)} : {session.error}")
            return
        brut = session.store.queued_raw(entree["id"])
        if brut is None:
            print(t("mail_outbox_release_gone"))
            return
        texte, en_ligne, jointes = tui.outbox_entry_preview(brut)
        print(t("mail_outbox_preview"))
        for ligne in texte:
            print(f"  {_printable(ligne)}")
        for nom in en_ligne:
            print(f"  {_printable(nom)} — {t('mail_rules_image_inline')}")
        for nom in jointes:
            print(f"  {_printable(nom)} — {t('mail_rules_image_attached')}")
        if not _ask_text_yes(t("mail_service_held_release_ask")):
            return
        res = release.release_held(session, entree["id"], entree=entree)
        for _ in range(2):
            if res.status != "confirm":
                break
            if not _ask_typed_word(res.question):
                print(t("mail_outbox_release_declined"))
                return
            res = release.release_held(
                session, entree["id"], entree=entree, force=res.verdict
            )
        if res.status == "confirm":
            print(t("mail_outbox_release_declined"))
            return
        print(_printable(res.text))
    finally:
        session.close()


def _service_claims(todo, *, base=None) -> None:
    """[6] du menu du service : libérer à la main un message dont la
    revendication est incertaine ou en échec, depuis une machine sans
    écran. Liste les lignes libérables de tous les comptes ; pour la
    ligne choisie, dit le refus que le geste opposerait
    (`release.release_claim_refusal`), sinon pose la question propre à
    l'issue (mot à taper), puis libère par `release.release_claim`.
    Aucune panne ne fait sortir du menu."""
    try:
        _service_claims_work(todo, base=base)
    except Exception as exc:
        _logger.exception("menu du service : revendications")
        print(f"{t('mail_rules_error')} {type(exc).__name__}")


def _service_claims_work(todo, *, base) -> None:
    import time

    from script.todo.mail.rules import engine, release, storage
    from script.todo.mail.rules.model import RuleError

    lignes = []
    for account, ouvrir in _service_stores(todo, base):
        try:
            magasin = ouvrir()
        except Exception as exc:
            print(
                f"  {_printable(account.name)} : {t('mail_rules_error')} {exc}"
            )
            continue
        try:
            try:
                noms = {
                    r.id: r.name or r.id
                    for r in storage.load(
                        account.name, storage.base_of(magasin)
                    )
                }
            except RuleError:
                noms = {}
            inbox = engine.find_inbox(magasin)
            etat = magasin.folder_state(inbox) if inbox else None
            repli = {}
            if etat and etat.get("uidvalidity"):
                repli = {
                    "inbox_folder_id": etat["id"],
                    "inbox_uidvalidity": etat["uidvalidity"],
                }
            for ligne in magasin.rule_log_releasable(50, **repli):
                lignes.append((account, ouvrir, noms, ligne))
        finally:
            magasin.close()
    if not lignes:
        print(t("mail_service_claims_none"))
        return
    for n, (account, _ouvrir, noms, ligne) in enumerate(lignes, start=1):
        quand = time.strftime("%Y-%m-%d %H:%M", time.localtime(ligne["at"]))
        regle = noms.get(ligne["rule_id"], ligne["rule_id"])
        issue = t(f"mail_rules_outcome_{ligne['outcome']}")
        print(
            f"[{n}] {_printable(account.name)} — {quand} — {_printable(regle)}"
            f" — {issue} ({engine.log_reason_text(ligne)})"
            f" — {_printable(ligne['sender'])} — {_printable(ligne['subject'])}"
        )
    choix = _choose(len(lignes))
    if choix is None:
        return
    account, ouvrir, _noms, ligne = lignes[choix - 1]
    magasin = ouvrir()
    try:
        refus = release.release_claim_refusal(
            magasin, ligne["rule_id"], ligne["msg_key"]
        )
        if refus is not None:
            print(_printable(refus))
            return
        raison = (
            "uncertain" if ligne["reason"] == "claim_uncertain" else "failed"
        )
        if not _ask_typed_word(t("mail_rules_release_confirm_" + raison)):
            print(t("mail_rules_release_declined"))
            return
        _ok, texte = release.release_claim(
            magasin, account.name, ligne["rule_id"], ligne["msg_key"]
        )
    finally:
        magasin.close()
    print(_printable(texte))


def _print_claim_mode(account_name: str, rules_base) -> None:
    """Imprime le mode de revendication du serveur du compte, tel que la
    dernière passe l'a inscrit dans l'état du moteur."""
    from script.todo.mail.rules import engine, storage

    print(
        engine.claim_mode_text(
            storage.load_claim_mode(account_name, rules_base)
        )
    )


def _claim_lines(accounts) -> list[str]:
    """Une ligne par compte dont le serveur ne permet qu'une revendication
    non atomique, ou aucune ; rien pour un mode atomique ou inconnu. Lu
    dans l'état du moteur de chaque compte, sous la base par défaut."""
    from script.todo.mail.rules import engine, storage

    lignes = []
    for account in accounts:
        mode = storage.load_claim_mode(account.name)
        if mode in ("plain", "none"):
            lignes.append(
                f"  {_printable(account.name)} : {engine.claim_mode_text(mode)}"
            )
    return lignes


def _held_lines(base) -> list[str]:
    """Une ligne par compte dont la dernière passe du service a laissé des
    envois automatiques retenus, comptés à cette passe (`.service_state.
    json`) : compter en direct ouvrirait chaque cache, donc le coffre d'un
    cache chiffré, à chaque tour du menu. Ils ne sont pas revendiqués, et
    se relâchent par [5] ou par `o`, depuis n'importe quelle machine qui
    les retient."""
    from script.todo.mail.rules import run as rules_run

    lignes = []
    for nom, entree in sorted(rules_run.load_state(base).items()):
        nombre = entree.get("held", 0)
        if (
            isinstance(nombre, int)
            and not isinstance(nombre, bool)
            and nombre > 0
        ):
            lignes.append(
                f"  {_printable(nom)} : {t('mail_service_menu_held')} {nombre}"
            )
    return lignes


def _service_install(todo, run) -> None:
    """[8] › [1] : installe ou met à jour les unités, puis avertit
    (un poste par compte, code du dépôt tel quel, credential, linger).

    L'avertissement du credential manque quand le credential existe, et
    quand la configuration porte un `kdbx.password` non vide : le service
    ouvre alors le coffre sans credential.
    """
    from script.todo.mail import credential, service

    ici = service.repo_root()
    installe = service.installed_repo(run=run)
    if installe and os.path.realpath(installe) != os.path.realpath(ici):
        print(t("mail_service_other_repo"))
        print(f"  {_printable(installe)}")
        print(f"  {_printable(ici)}")
        if not _ask_yes("mail_service_other_repo_ask"):
            print(t("mail_service_creds_cancelled"))
            return
    intervalle = click.prompt(
        t("mail_service_ask_interval"),
        type=click.IntRange(service.INTERVAL_MIN, service.INTERVAL_MAX),
        default=service.installed_interval(run=run)
        or service.INTERVAL_DEFAULT_MIN,
    )
    try:
        service.install(intervalle, run=run)
    except service.ServiceError as exc:
        print(exc)
        return
    print(f"{t('mail_service_installed')} {intervalle} min")
    print(t("mail_service_one_host_warning"))
    print(t("mail_service_dev_checkout_warning"))
    print(t("mail_service_journal_hint"))
    if (
        not _configured_kdbx_password(todo)
        and service.accounts_need_credential(_load_accounts())
        and not credential.credential_path(run=run).exists()
    ):
        print(t("mail_service_needs_credential"))
    if service.linger_enabled(run=run) is False:
        print(t("mail_service_linger_off"))
        if _ask_yes("mail_service_linger_ask"):
            if service.enable_linger(run=run):
                print(t("mail_service_linger_on"))
            else:
                print(t("mail_service_linger_failed"))
                print(t("mail_service_linger_hint"))


def _configured_kdbx(todo) -> str:
    """Le `kdbx.path` de la configuration, "" s'il manque."""
    config = getattr(todo, "config_file", None)
    if config is None:
        return ""
    try:
        valeur = config.get_config_value(["kdbx", "path"])
    except Exception:
        # `get_config_value` lève `TypeError` sur une clé absente.
        return ""
    return valeur if isinstance(valeur, str) else ""


def _configured_kdbx_password(todo) -> bool:
    """Vrai si la configuration porte un `kdbx` avec un chemin et un
    `kdbx.password` non vide : le repli du service sans credential
    (`service.config_kdbx_password`)."""
    from script.todo.mail import service

    return service.config_kdbx_password(getattr(todo, "config_file", None))


def _service_credential(todo, *, run, getpass_fn, isatty) -> None:
    """[8] › [2] : chiffre le mot de passe maître du kdbx pour le service.

    Refuse sans kdbx, sans `systemd-creds --user`, sans terminal (getpass
    lirait le mot de passe EN ÉCHO) et sur tout autre « oui » que
    `_YES` à l'avertissement de portée. Pendant la saisie et le
    chiffrement, la limite DOUCE des fichiers core est à 0 : un plantage
    ne laisse pas le mot de passe sur le disque. Elle est rendue ensuite,
    les outils que le menu lance après n'en héritent pas.
    """
    from script.todo.mail import credential

    kdbx_path = _configured_kdbx(todo)
    if not kdbx_path:
        print(t("mail_service_creds_no_kdbx"))
        return
    if not credential.user_scope_supported(run=run):
        print(t("mail_service_creds_unsupported"))
        print(t("mail_service_creds_unsupported_hint"))
        return
    if not isatty():
        print(t("mail_service_creds_no_tty"))
        return
    print(t("mail_service_creds_scope_warning"))
    if not _ask_yes("mail_service_creds_scope_ask"):
        print(t("mail_service_creds_cancelled"))
        return
    lire = getpass_fn if getpass_fn is not None else getpass.getpass
    soft, hard = resource.getrlimit(resource.RLIMIT_CORE)
    resource.setrlimit(resource.RLIMIT_CORE, (0, hard))
    try:
        _encrypt_for_service(kdbx_path, run=run, lire=lire)
    finally:
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(resource.RLIMIT_CORE, (soft, hard))


def _encrypt_for_service(kdbx_path: str, *, run, lire) -> None:
    from script.todo.mail import credential

    password = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                password = lire(t("mail_service_creds_ask"))
            except getpass.GetPassWarning:
                print(t("mail_service_creds_no_tty"))
                return
        if not password:
            print(t("mail_service_creds_cancelled"))
            return
        dest = credential.setup_credential(
            password,
            kdbx_path=kdbx_path,
            dest=credential.credential_path(run=run),
            run=run,
        )
    except EOFError:
        print(t("mail_service_creds_cancelled"))
        return
    except credential.CredentialError as exc:
        print(exc)
        return
    except OSError as exc:
        # `setup_credential` rend déjà en `CredentialError` toute panne de
        # `systemd-creds` : un OSError vient de l'écriture du credstore,
        # après un chiffrement réussi. Le nom du type suffit, le texte de
        # l'exception nommerait le chemin du dossier personnel.
        print(f"{t('mail_service_creds_write_failed')} {type(exc).__name__}")
        return
    finally:
        password = None
    print(f"{t('mail_service_creds_written')} {dest}")


def _service_uninstall(run) -> None:
    """[8] › [4] : retire les unités et, sauf refus explicite, le
    credential ; propose ensuite de retirer un linger actif.

    Rien d'installé ni de credential : le menu le dit sans rien demander.
    La question du credential n'est posée que s'il existe.
    """
    from script.todo.mail import service

    unites, cred = service.installed_parts(run=run)
    if not unites and not cred:
        print(t("mail_service_not_installed"))
        return
    if not _ask_yes("mail_service_uninstall_ask"):
        print(t("mail_service_creds_cancelled"))
        return
    retirer = False
    if cred:
        garder = input(f"{t('mail_service_creds_delete_ask')} ")
        retirer = garder.strip().lower() not in _NO
    try:
        fait = service.uninstall(remove_credential=retirer, run=run)
    except service.ServiceError as exc:
        print(exc)
        return
    if not fait:
        print(t("mail_service_not_installed"))
        return
    print(t("mail_service_uninstalled"))
    if service.linger_enabled(run=run) is True:
        if _ask_yes("mail_service_linger_disable_ask"):
            if service.disable_linger(run=run):
                print(t("mail_service_linger_disabled"))
            else:
                print(t("mail_service_linger_failed"))


def _list_rules(account_name: str, rules_base) -> list:
    """Imprime les règles dans l'ordre d'application ; les rend.

    Sous le filtre d'une règle forward, une ligne donne son mode et ses
    destinations.
    """
    from script.todo.mail.rules import storage
    from script.todo.mail.tui import rule_filter_summary, rule_forward_summary

    rules = storage.load(account_name, base=rules_base)
    if not rules:
        print(t("mail_rules_none"))
    for rang, rule in enumerate(rules, start=1):
        actif = "☑" if rule.enabled else "☐"
        arret = f" — {t('mail_rules_col_stop')}" if rule.stop_after else ""
        print(
            f"  [{rang}] {actif} {_printable(rule.name or rule.id)}"
            f" — {t(f'mail_rules_kind_{rule.action.kind}')}{arret}"
        )
        print(f"        {_printable(rule_filter_summary(rule.filter))}")
        if rule.action.kind == "forward":
            print(f"        → {_printable(rule_forward_summary(rule))}")
    return rules


def _change_rule(account_name: str, rules_base, choice: str) -> None:
    """[2] bascule l'activation, [3] déplace, [4] supprime (confirmée)."""
    from script.todo.mail.rules import storage

    rules = _list_rules(account_name, rules_base)
    if not rules:
        return
    numero = str(click.prompt(t("mail_rules_menu_pick_rule"))).strip()
    try:
        index = int(numero) - 1
    except ValueError:
        index = -1
    if not 0 <= index < len(rules):
        print(t("mail_rules_menu_unknown_rule"))
        return
    rule = rules[index]
    if choice == "2":
        storage.set_enabled(
            account_name,
            rule.id,
            not rule.enabled,
            armed=None,
            base=rules_base,
        )
    elif choice == "3":
        sens = str(click.prompt(t("mail_rules_menu_direction"))).strip()
        if sens not in ("1", "2"):
            print(t("Command not found !"))
            return
        storage.move_rule(
            account_name, rule.id, -1 if sens == "1" else 1, base=rules_base
        )
    else:
        print(f"{t('mail_rules_delete_confirm')} {rule.name or rule.id}")
        reponse = str(click.prompt(t("mail_rules_menu_confirm")))
        if reponse.strip().lower() not in ("o", "y"):
            return
        storage.delete_rule(account_name, rule.id, base=rules_base)
    _list_rules(account_name, rules_base)


def _show_rules_log(todo, account, base_rules, base=None) -> None:
    """Le journal des règles du compte, les lignes les plus récentes.

    Le coffre n'est ouvert que si le cache est chiffré, comme pour les
    statistiques : un cache en clair se lit sans saisie de mot de passe.
    """
    import time

    from script.todo.mail.rules import engine, storage
    from script.todo.mail.rules.model import RuleError

    try:
        noms = {
            rule.id: rule.name or rule.id
            for rule in storage.load(account.name, base=base_rules)
        }
    except RuleError:
        noms = {}
    magasin = Store(
        account,
        secrets=secret_store_for(todo)
        if _needs_vault(account, base)
        else None,
        base=base,
    )
    try:
        magasin.open()
        lignes = magasin.rule_log_entries(None, RULES_MENU_LOG_LINES)
    except Exception as exc:
        print(f"  {t('mail_rules_error')} {exc}")
        return
    finally:
        try:
            magasin.close()
        except Exception:
            pass
    if not lignes:
        print(t("mail_rules_log_empty"))
    for ligne in lignes:
        quand = time.strftime("%Y-%m-%d %H:%M", time.localtime(ligne["at"]))
        raison = engine.log_reason_text(ligne)
        texte = t(f"mail_rules_outcome_{ligne['outcome']}")
        if raison:
            texte += f" ({raison})"
        nom = noms.get(ligne["rule_id"], ligne["rule_id"])
        print(
            f"  {quand}  {_printable(nom)}  {texte}"
            f"  {_printable(ligne['sender'])}  {_printable(ligne['subject'])}"
        )


def _needs_vault(account, base=None) -> bool:
    """Vrai si l'ouverture du cache du compte peut demander une clé : son
    mode résolu n'est pas `clear`, ou son cache ne se lit pas (l'ouverture
    tranche alors sous son verrou, et peut le trouver chiffré)."""
    return (
        resolve_mode(account, base=base) != "clear"
        or inscribed_mode(account, base) == PROBE_UNKNOWN
    )


def _open_store(todo, account, base=None) -> Store:
    """Le cache du compte, ouvert ; le coffre n'est demandé que pour un
    cache chiffré. Le `Store` ne reçoit pas de mode : une reprise de
    conversion faite par sa propre ouverture, ou une inscription lue sous
    son verrou, décident alors à sa place quand le compte ne demande
    rien."""
    magasin = Store(
        account,
        secrets=secret_store_for(todo)
        if _needs_vault(account, base)
        else None,
        base=base,
    )
    magasin.open()
    return magasin


def _report_settings(todo, account, rules_base, base=None) -> None:
    """[6] Les paramètres du rapport : chaque champ demandé, valeur
    actuelle par défaut, puis l'aperçu texte du bloc « {{rapport}} »
    sans demandeur. Une valeur refusée est imprimée et rien n'est écrit.
    """
    import dataclasses
    import time

    from erplibre_mail_core.zone import local_zone

    from script.todo.mail.rules import report, storage
    from script.todo.mail.rules.model import FORMATS, RuleError

    try:
        actuels = storage.load_report(account.name, base=rules_base)
    except RuleError as exc:
        print(exc)
        actuels = storage.ReportSettings()
    print(f"{t('mail_stats_report_tz')} {time.strftime('%Z (UTC%z)')}")
    saisie = {}
    # « - » tient la place d'une chaîne vide : `click.prompt` rend la
    # valeur par défaut sur une saisie vide, qui ne pourrait donc jamais
    # effacer un identifiant ou une langue déjà réglés.
    for champ, cle, choix in (
        ("days", "mail_stats_report_days", ""),
        ("weeks", "mail_stats_report_weeks", ""),
        ("delay_window_days", "mail_stats_report_window", ""),
        ("format", "mail_stats_report_format", "/".join(FORMATS)),
        ("lang", "mail_stats_report_lang", "-/fr/en"),
        ("auth_serv_id", "mail_stats_report_auth_serv", "-"),
    ):
        actuel = getattr(actuels, champ)
        invite = f"{t(cle)} ({choix})" if choix else t(cle)
        valeur = str(
            click.prompt(invite, default="-" if actuel == "" else actuel)
        ).strip()
        if isinstance(actuel, str) and valeur == "-":
            valeur = ""
        if isinstance(actuel, int):
            try:
                valeur = int(valeur)
            except ValueError:
                # Laissé en texte : `report_from_dict` le refuse en
                # nommant le champ.
                pass
        saisie[champ] = valeur
    try:
        reglages = storage.report_from_dict(
            {**dataclasses.asdict(actuels), **saisie}
        )
        storage.save_report(account.name, reglages, base=rules_base)
    except RuleError as exc:
        print(exc)
        return
    print(t("mail_stats_report_saved"))
    if not reglages.auth_serv_id:
        print(t("mail_stats_report_auth_serv_unset"))
    try:
        magasin = _open_store(todo, account, base)
    except Exception as exc:
        print(f"  {t('mail_stats_error')} {exc}")
        return
    try:
        donnees = report.build_data(
            magasin,
            reglages,
            now=int(time.time()),
            sender=None,
            tz=local_zone(),
        )
        texte = report.values(donnees)["rapport"][0]
    except Exception as exc:
        print(f"  {t('mail_stats_error')} {exc}")
        return
    finally:
        try:
            magasin.close()
        except Exception:
            pass
    print()
    for ligne in texte.splitlines():
        print(_printable(ligne))


# Messages récents de la boîte de réception proposés par l'essai du menu.
TRIAL_MENU_MESSAGES = 20


def _trial(todo, account, rules_base, base=None) -> None:
    """[7] Essai d'une règle sur un message récent de la boîte de
    réception : ce que la règle en ferait, puis, sur « o », un envoi
    d'essai (réponse, transfert ou redirection) à l'adresse du compte
    seulement.

    La session s'ouvre comme celle du TUI (en ligne si possible : en-têtes
    complets) et se ferme toujours. Tout ce qui vient d'un message passe
    par `_printable`.
    """
    import time

    from script.todo.mail import tui
    from script.todo.mail.rules import engine

    rules = _list_rules(account.name, rules_base)
    if not rules:
        return
    numero = str(click.prompt(t("mail_rules_menu_pick_rule"))).strip()
    try:
        index = int(numero) - 1
    except ValueError:
        index = -1
    if not 0 <= index < len(rules):
        print(t("mail_rules_menu_unknown_rule"))
        return
    rule = rules[index]
    session = tui.open_session(
        account,
        secret_store_for(todo),
        base=base,
        config_get=_config_get(todo),
    )
    try:
        store = session.store
        if store is None:
            print(f"{t('mail_rules_no_cache')} {session.error}".strip())
            return
        inbox = engine.find_inbox(store)
        etat = store.folder_state(inbox) if inbox else None
        if not etat or not etat.get("uidvalidity"):
            print(t("mail_rules_no_inbox"))
            return
        metas = store.list_messages(etat["id"], limit=TRIAL_MENU_MESSAGES)
        if not metas:
            print(t("mail_rules_trial_none"))
            return
        for rang, meta in enumerate(metas, start=1):
            quand = time.strftime(
                "%Y-%m-%d %H:%M",
                time.localtime(
                    getattr(meta, "received_at", 0) or meta.date or 0
                ),
            )
            print(
                f"  [{rang}] {quand}  {_printable(meta.frm)}"
                f"  {_printable(meta.subject)}"
            )
        choix = str(
            click.prompt(t("mail_rules_menu_trial_pick_message"))
        ).strip()
        try:
            rang = int(choix) - 1
        except ValueError:
            rang = -1
        if not 0 <= rang < len(metas):
            print(t("Command not found !"))
            return
        sim = tui.trial_simulation(
            session,
            rule,
            metas[rang],
            folder=inbox,
            uidvalidity=int(etat["uidvalidity"]),
            rules_base=rules_base,
        )
        print()
        for ligne, _style in tui.rule_trial_lines(sim):
            print(_printable(ligne))
        if not sim.sendable:
            return
        reponse = str(click.prompt(t("mail_rules_menu_trial_send_ask")))
        if reponse.strip().lower() not in ("o", "y"):
            return
        try:
            statut = engine.send_trial(session, rule, sim)
        except Exception as exc:
            print(exc)
            if _is_tls_refusal(exc):
                print(f"  {t('mail_tls_menu_hint')}")
            return
        print(f"{t('mail_rules_trial_sent')} {_printable(statut)}")
    finally:
        session.close()


def _show_stats(todo, *, base=None) -> None:
    """Les statistiques de chaque compte, en texte, sans ouvrir le TUI.

    Rien ne part sur le réseau : la commande répond hors ligne, et un compte
    dont le cache est illisible est signalé sans empêcher les autres.

    Le coffre n'est ouvert que pour les comptes dont le cache est CHIFFRÉ,
    et une seule fois pour tous : un cache scellé ne se lit pas sans sa clé,
    tandis qu'un parc en clair ne doit pas payer une saisie de mot de passe
    pour afficher des chiffres qu'il rend sans elle.
    """
    from script.todo.mail import stats

    comptes = _load_accounts()
    if not comptes:
        print(t("mail_no_account"))
        return
    coffre = None
    for compte in comptes:
        besoin = _needs_vault(compte, base)
        if besoin and coffre is None:
            coffre = secret_store_for(todo)
        print(f"\n=== {compte.name} ===")
        magasin = Store(
            compte,
            secrets=coffre if besoin else None,
            base=base,
        )
        try:
            magasin.open()
            rapport = stats.build_report(magasin)
        except Exception as exc:
            print(f"  {t('mail_stats_error')} {exc}")
            continue
        finally:
            try:
                magasin.close()
            except Exception:
                pass
        print(
            f"  {t('mail_stats_total')} {rapport.total}"
            f"   {t('mail_stats_unseen')} {rapport.unseen}"
            f" ({rapport.unseen_share:.0%})"
        )
        for etiquette, nombre, barre in rapport.volume[-14:]:
            print(f"  {etiquette}  {nombre:>5}  {barre}")
        print(f"  {t('mail_stats_senders')}")
        for adresse, nombre in rapport.senders[:5]:
            print(f"    {nombre:>5}  {_printable(adresse)}")
        if rapport.reply_count:
            print(
                f"  {t('mail_stats_reply')} "
                f"{stats.humain(rapport.reply_median)}"
                f" ({rapport.reply_count})"
            )
        else:
            print(f"  {t('mail_stats_reply_none')}")


def _open_tui(todo) -> None:
    from script.todo.mail.tui import open_sessions, run_tui

    accounts = _load_accounts()
    secrets = secret_store_for(todo)
    sessions = open_sessions(accounts, secrets, config_get=_config_get(todo))
    try:
        # Un TUI sans aucun compte n'est plus une impasse : `config_file` et
        # `secrets` lui permettent d'en créer un depuis l'écran d'ajout.
        run_tui(
            sessions=sessions,
            config_file=todo.config_file,
            secret_store=secrets,
        )
    finally:
        for session in sessions:
            session.close()


def _config_get(todo):
    """L'accès en lecture à la configuration TODO, ou rien.

    Les réglages OAuth de celui qui déploie y vivent. Un `todo` sans
    fichier de configuration — les tests en passent — retombe sur les
    variables d'environnement plutôt que de lever.
    """
    config = getattr(todo, "config_file", None)
    lire = getattr(config, "get_config_value", None)
    return lire if callable(lire) else None


def _sync_now(todo) -> None:
    from script.todo.mail.tui import (
        SYNC_PARALLELE,
        flush_outbox,
        held_auto_counts,
        held_auto_text,
        open_sessions,
        outbox_status_text,
    )

    accounts = _load_accounts()
    if not accounts:
        print(t("mail_no_account"))
        return
    sessions = open_sessions(
        accounts,
        secret_store_for(todo),
        config_get=_config_get(todo),
    )

    def une(session) -> tuple:
        """Une passe pour un compte : (texte, rapport ou None). Ne lève
        jamais : un compte qui échoue ne doit pas emporter ceux qui avancent
        avec lui."""
        if not session.online:
            texte = f"{session.account.name} : {session.error}"
            if getattr(session, "error_kind", "") == "tls":
                texte += f"\n  {t('mail_tls_menu_hint')}"
            return texte, None
        lignes = []
        # La file part AVANT la relecture, comme dans le TUI : une commande
        # qui promet de synchroniser doit envoyer ce qui attend, sinon un
        # message écrit hors ligne dort jusqu'à la prochaine ouverture du
        # client — le seul endroit d'où la file partait.
        try:
            # L'objet rendu est gardé : ses attributs comptent les départs
            # partiels ; un double qui rend un triplet nu n'en porte pas.
            r = flush_outbox(session)
            partis, _, echoues = r
            if partis or echoues:
                lignes.append(
                    f"{session.account.name} : {outbox_status_text(r)}"
                )
            refus = getattr(r, "tls_error", None)
            if refus is not None:
                lignes.append(f"{session.account.name} : {refus}")
                lignes.append(f"  {t('mail_tls_menu_hint')}")
        except Exception as exc:
            lignes.append(f"{session.account.name} : {exc}")
        try:
            report = session.sync()
        except Exception as exc:
            lignes.append(f"{session.account.name} : {exc}")
            if _is_tls_refusal(exc):
                lignes.append(f"  {t('mail_tls_menu_hint')}")
            return "\n".join(lignes), None
        lignes.append(
            f"{session.account.name} : {report.new_messages}"
            f" {t('mail_new_messages')}"
        )
        lignes += [f"  {e}" for e in report.errors]
        refus = getattr(report, "tls_error", None)
        if refus is not None:
            lignes.append(f"{session.account.name} : {refus}")
            lignes.append(f"  {t('mail_tls_menu_hint')}")
        if report.purged:
            lignes.append(
                f"  {t('mail_folders_resynced')} {', '.join(report.purged)}"
            )
        return "\n".join(lignes), report

    try:
        # Chaque compte a son socket et son cache verrouillé : les faire
        # avancer ensemble transforme une attente réseau en série en une
        # seule attente. Le rendu reste groupé PAR COMPTE — un entrelacement
        # de lignes venues de plusieurs comptes serait illisible.
        # Chaque bilan s'imprime dès que lui et ceux qui le précèdent sont
        # prêts : un compte injoignable ne masque pas les autres jusqu'à
        # l'échéance de sa connexion. Les règles passent après le pool.
        vivantes = list(sessions)
        rapports = []

        def imprimer(resultats) -> None:
            for session, (texte, rapport) in zip(
                vivantes, resultats, strict=True
            ):
                print(texte)
                rapports.append((session, rapport))

        if len(vivantes) <= 1:
            imprimer(une(session) for session in vivantes)
        else:
            with ThreadPoolExecutor(
                max_workers=min(SYNC_PARALLELE, len(vivantes))
            ) as pool:
                imprimer(pool.map(une, vivantes))
        _run_rules(rapports, accounts)
        # Après les règles, qui viennent peut-être d'en retenir : un envoi
        # automatique retenu ne part qu'une fois relâché dans le client.
        for nom, nombre in held_auto_counts(vivantes):
            print(
                f"{nom} : {held_auto_text(nombre)}"
                f" — {t('mail_outbox_held_auto_menu_hint')}"
            )
    finally:
        for session in sessions:
            session.close()


def _run_rules(paires, accounts) -> None:
    """Une passe des règles par compte synchronisé, en série, après le pool.

    Aucun autre fil n'utilise alors les liens : pas de verrou. La ligne de
    bilan suit la même règle de mutisme que dans le TUI ; un compte sans
    règle active n'imprime rien.
    """
    from script.todo.mail.rules import engine

    for session, rapport in paires:
        if rapport is None:
            continue
        bilan = engine.run_pass(
            session, report=rapport, all_accounts=accounts, verrou=None
        )
        ligne = engine.summary_line([bilan])
        if ligne:
            print(ligne)
        if bilan.active_rules:
            for erreur in bilan.errors:
                print(f"  {_printable(erreur)}")


def prompt_mail_accounts(todo) -> None:
    while True:
        help_info = f"""{todo._menu_header()}
[1] {t("mail_account_list")}
[2] {t("mail_account_add")}
[3] {t("mail_account_delete")}
[4] {t("mail_account_template")}
[5] {t("mail_account_test")}
[6] {t("mail_account_token")}
[7] {t("mail_account_signature")}
[8] {t("mail_account_tls_pins")}
{retour(t('Back'))}"""
        status = click.prompt(help_info)
        print()
        if status == "0":
            return
        if status == "1":
            _list_accounts()
        elif status == "2":
            _add_account(todo)
        elif status == "3":
            _delete_account(todo)
        elif status == "4":
            _write_template()
        elif status == "5":
            _test_account(todo)
        elif status == "6":
            _set_oauth_token(todo)
        elif status == "7":
            _set_signature()
        elif status == "8":
            _tls_pins_menu()
        else:
            print(t("Command not found !"))


def _list_accounts() -> None:
    accounts = _load_accounts()
    if not accounts:
        print(t("mail_no_account"))
        return
    for account in accounts:
        mark = "" if account.enabled else " (désactivé)"
        print(
            f"  {account.name}{mark} — {account.email}"
            f" — {account.imap.host} / {account.smtp.host}"
        )


def _ensure_kdbx(todo) -> bool:
    """Vrai si un kdbx est utilisable pour la suite de `_add_account`.

    Si `kdbx.path` est déjà configuré, ne pose aucune question — c'est le
    cas courant après la première utilisation. Sinon, offre les deux choix
    promis par la conception : créer un nouveau `.kdbx` ou en choisir un
    existant.
    """
    if todo.config_file.get_config_value(["kdbx", "path"]):
        return True

    print(t("mail_kdbx_none_configured"))
    print(f"  [1] {t('mail_kdbx_menu_create')}")
    print(f"  [2] {t('mail_kdbx_menu_choose')}")
    print(f"  [0] {t('mail_kdbx_menu_cancel')}")
    choice = input(t("mail_kdbx_ask_choice")).strip()
    if choice == "1":
        return _create_kdbx_interactive(todo)
    if choice == "2":
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

    keys = list(PRESETS)
    for index, key in enumerate(keys, start=1):
        print(f"  [{index}] {PRESETS[key]['label']}")
    choice = input(t("mail_ask_preset")).strip()
    try:
        preset_key = keys[int(choice) - 1]
    except (ValueError, IndexError):
        preset_key = "generic"

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
    # La note, elle, se dit TOUJOURS : c'est le seul endroit où un
    # fournisseur explique ce qu'il attend, et celui qui n'accepte plus de
    # mot de passe du tout est justement celui qu'il faut prévenir.
    print(f"  {t(PRESETS[preset_key]['note_key'])}")

    account.auth = _demander_authentification(preset_key)
    if account.auth == "oauth":
        secret = _obtenir_jeton(todo, account)
        if not secret:
            print(t("mail_nothing_written"))
            return
    else:
        secret = getpass.getpass(
            t("mail_ask_app_password" if attendu_app else "mail_ask_password")
        )
    existing = [a for a in _load_accounts() if a.name != account.name]
    try:
        account_setup.save_new_account(
            store, existing + [account], account, secret
        )
    except (SecretError, AccountError, OSError) as exc:
        # Une exception qui remonte ici tuerait le menu ; `save_new_account`
        # a déjà annulé l'écriture du secret si la sauvegarde a échoué.
        print(exc)
        return
    print(t("mail_account_saved"))


def _demander_authentification(preset_key: str) -> str:
    """« login » ou « oauth », selon ce que le fournisseur accepte encore.

    La question n'est posée que lorsqu'il y a un CHOIX. Un fournisseur sans
    OAuth ne doit pas se voir proposer une voie qui n'existe pas ; un
    fournisseur qui n'accepte plus de mot de passe ne doit pas se voir
    proposer une impasse.
    """
    preset = PRESETS.get(preset_key, {})
    if not preset.get("oauth"):
        return "login"
    if not preset.get("app_password"):
        print(t("mail_oauth_only_here"))
        return "oauth"
    print(f"  [1] {t('mail_auth_choice_password')}")
    print(f"  [2] {t('mail_auth_choice_oauth')}")
    return (
        "oauth" if input(t("mail_ask_auth_kind")).strip() == "2" else "login"
    )


def _set_oauth_token(todo) -> None:
    """Remplace le jeton de rafraîchissement d'un compte.

    Un jeton révoqué — le propriétaire a retiré l'autorisation, ou le
    fournisseur l'a expirée — se remplace sans refaire le compte. Une saisie
    vide n'écrit RIEN : effacer le jeton en place couperait la
    synchronisation d'un compte qui marchait.
    """
    account, _ = _pick_account()
    if account is None:
        return
    if getattr(account, "auth", "login") != "oauth":
        print(t("mail_account_is_not_oauth"))
        return
    jeton = _obtenir_jeton(todo, account)
    if not jeton:
        print(t("mail_nothing_written"))
        return
    try:
        secret_store_for(todo).set(account.refresh_token_ref(), jeton)
    except SecretError as exc:
        print(exc)
        return
    print(t("mail_token_saved"))


def _set_signature() -> None:
    """Change la signature d'un compte, lue ligne à ligne.

    Une signature tient rarement sur une ligne : la saisie s'arrête à une
    ligne VIDE plutôt qu'au premier retour, ce qui permet d'en écrire
    plusieurs. La signature en place est affichée d'abord — la remplacer à
    l'aveugle ferait perdre celle qu'on avait.

    Une saisie vide EFFACE, et c'est voulu : sans quoi une signature posée
    par erreur ne se retirerait qu'en éditant le fichier à la main. Le
    menu le dit avant de lire.
    """
    account, accounts = _pick_account()
    if account is None:
        return
    actuelle = getattr(account, "signature", "") or ""
    if actuelle:
        print(t("mail_signature_current"))
        print(actuelle)
    print(t("mail_signature_prompt"))
    lignes = []
    while True:
        try:
            ligne = input()
        except EOFError:
            break
        if not ligne.strip():
            break
        lignes.append(ligne)
    account.signature = "\n".join(lignes)
    try:
        mail_accounts.save(accounts)
    except AccountError as exc:
        print(exc)
        return
    print(
        t("mail_signature_cleared")
        if not account.signature
        else t("mail_signature_saved")
    )


def _obtenir_jeton(todo, account) -> str:
    """Le jeton de rafraîchissement : par le navigateur, ou collé.

    Le parcours d'autorisation n'est proposé que lorsqu'un identifiant
    client est configuré — sans lui, la page du fournisseur répondrait
    « invalid_client », et l'utilisateur chercherait la panne chez lui.
    Rend la chaîne vide quand rien n'a été obtenu ; l'appelant n'écrit
    alors rien plutôt que d'effacer le jeton en place.
    """
    from script.todo.mail import oauth

    try:
        identifiant = oauth.settings_for(account, _config_get(todo))[
            "client_id"
        ]
    except oauth.OAuthError:
        identifiant = ""

    if identifiant:
        print(f"  [1] {t('mail_oauth_choice_browser')}")
        print(f"  [2] {t('mail_oauth_choice_paste')}")
        if input(t("mail_ask_oauth_way")).strip() != "2":
            print(t("mail_oauth_opening_browser"))
            try:
                return oauth.authorize(
                    account, config_get=_config_get(todo)
                ).refresh_token
            except oauth.OAuthError as exc:
                print(exc)
                return ""
    return getpass.getpass(t("mail_ask_refresh_token"))


def _pick_account(prompt_key="mail_ask_account"):
    accounts = _load_accounts()
    if not accounts:
        print(t("mail_no_account"))
        return None, []
    for index, account in enumerate(accounts, start=1):
        print(f"  [{index}] {account.name}")
    choice = input(t(prompt_key)).strip()
    try:
        return accounts[int(choice) - 1], accounts
    except (ValueError, IndexError):
        return None, accounts


def _delete_account(todo, *, base=None) -> None:
    """Retire le compte de la configuration. Son cache reste sur le
    disque ; une ancienne copie laissée par une conversion interrompue est
    effacée, sous le verrou exclusif s'il s'obtient."""
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
    _finish_pending_conversion(account.name, base)
    print(t("mail_account_deleted"))


def _finish_pending_conversion(nom: str, base=None) -> None:
    """`cache_convert.recover` sous l'exclusif, s'il s'obtient et que le
    dossier de contrôle du compte existe ; une erreur est consignée, jamais
    levée."""
    from script.todo.mail import cache_convert

    try:
        if not os.path.lexists(cache_ctl_dir(nom, base, create=False)):
            return
        with cache_exclusive(nom, base) as tenu:
            if tenu:
                cache_convert.recover(nom, base)
    except (StoreError, OSError) as exc:
        _logger.warning(
            "reprise de conversion de %s impossible : %s", nom, exc
        )


def _write_template() -> None:
    try:
        path = mail_accounts.write_template()
    except AccountError as exc:
        print(exc)
        return
    print(f"{t('mail_template_written')} {path}")


def _looks_like_auth_failure(cause) -> bool:
    """Le serveur a-t-il RÉPONDU, ou n'est-il rien revenu ?

    La question n'est pas « le message ressemble-t-il à un refus » : la
    première version cherchait « invalid credentials » et compagnie, et a
    manqué le cas le plus clair qui soit — Gmail répond
    « [ALERT] Application-specific password required » une fois la double
    authentification active, sans employer aucun de ces mots. Une liste de
    libellés attendus est toujours en retard sur les serveurs réels.

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
    if _looks_like_auth_failure(cause):
        if attendu_app:
            print(t("mail_app_password_note"))
        if preset.get("note_key"):
            print(f"  {t(preset['note_key'])}")
    # L'invite elle-même nomme ce qu'on attend. « Mot de passe : » invitait
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
            # invite à ressaisir, pas un plantage du menu. Un certificat
            # refusé arrête tout : le mot de passe n'est pas parti, le
            # serveur n'en a rien refusé.
            print(f"{t('mail_connection_failed')} {exc}")
            if _is_tls_refusal(exc):
                print(f"  {t('mail_tls_menu_hint')}")
                return False
            continue
        transport.logout()
        store.set(account.secret_ref, password)
        print(t("mail_connection_ok"))
        return True
    return False


def _is_tls_refusal(exc) -> bool:
    """Vrai si `exc` est un certificat refusé (`TlsCertificateError`)."""
    from script.todo.mail.tui import is_tls_refusal

    return is_tls_refusal(exc)


def _offer_pin(account, exc, *, path=None) -> bool:
    """Propose d'épingler l'empreinte d'un certificat refusé, par un mot à
    taper ; vrai si l'épingle est écrite."""
    from script.todo.mail import tls_trust

    if not exc.pinnable:
        print(t("mail_tls_pin_unavailable").format(endpoint=exc.endpoint))
        return False
    print()
    if not _ask_typed_word(
        tls_trust.question(account.name, exc),
        mot=t("mail_tls_trust_word"),
    ):
        print(t("mail_tls_pin_declined").format(endpoint=exc.endpoint))
        return False
    try:
        tls_trust.pin(account, exc, path)
    except (AccountError, OSError, ValueError) as err:
        print(f"{t('mail_tls_pin_failed')} {err}")
        return False
    print(
        t("mail_tls_pinned_done").format(
            account=account.name, endpoint=exc.endpoint
        )
    )
    return True


def _with_pin_offer(account, essai, *, path=None):
    """`essai()`, et sur un certificat refusé : le message, l'offre
    d'épinglage et, épinglé, un second essai, sans nouvelle offre. Toute
    autre exception traverse ; un refus TLS final rend None."""
    try:
        return essai()
    except Exception as exc:
        if not _is_tls_refusal(exc):
            raise
        print(f"{t('mail_connection_failed')} {exc}")
        if not _offer_pin(account, exc, path=path):
            return None
    try:
        return essai()
    except Exception as exc:
        if not _is_tls_refusal(exc):
            raise
        print(f"{t('mail_connection_failed')} {exc}")
        return None


def _test_account(
    todo, *, imap_connect=None, smtp_connect=None, accounts_path=None
) -> None:
    """Teste la connexion IMAP d'un compte (connexion, LIST, sortie), puis,
    si elle aboutit, sa connexion SMTP. Un certificat refusé affiche son
    empreinte et propose de l'épingler ; il ne redemande jamais le mot de
    passe."""
    if imap_connect is None:
        from script.todo.mail.imap_transport import connect as imap_connect
    if smtp_connect is None:
        from script.todo.mail.smtp_send import connect as smtp_connect

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

    def essai_imap():
        transport = imap_connect(account, password)
        try:
            return transport.list_folders()
        finally:
            transport.logout()

    try:
        folders = _with_pin_offer(account, essai_imap, path=accounts_path)
    except Exception as exc:
        # Connexion refusée, mot de passe expiré, ou LIST qui échoue : dans
        # tous les cas, offrir de resaisir le mot de passe plutôt que de
        # faire tomber le menu.
        print(f"{t('mail_connection_failed')} {exc}")
        if not retry_password(
            todo, account, cause=exc, connect_fn=imap_connect
        ):
            return
        try:
            password = secret_store_for(todo).get(account.secret_ref)
        except SecretError:
            return
        folders = ()
    else:
        if folders is None:
            return
        print(f"{t('mail_connection_ok')} {len(folders)}")

    def essai_smtp():
        smtp_connect(account, password).quit()
        return True

    try:
        fait = _with_pin_offer(account, essai_smtp, path=accounts_path)
    except Exception as exc:
        print(f"{t('mail_connection_smtp_failed')} {exc}")
        return
    if fait:
        print(t("mail_connection_smtp_ok"))


def _tls_pins_menu(path=None) -> None:
    """Liste les empreintes épinglées de tous les comptes et en retire
    une après confirmation : retirer rend la vérification normale au point
    d'accès, ce qui ne fait que resserrer la politique."""
    from script.todo.mail import tls_trust
    from script.todo.mail.smtp_send import tls

    try:
        lignes = mail_accounts.pinned_certificates(mail_accounts.load(path))
    except AccountError as exc:
        print(exc)
        return
    if not lignes:
        print(t("mail_tls_pins_none"))
        return
    for rang, (nom, cle, empreinte) in enumerate(lignes, start=1):
        print(
            f"  [{rang}] {_printable(nom)} — {cle} — SHA-256"
            f" {tls.format_fingerprint(empreinte)}"
        )
    choix = input(t("mail_tls_ask_unpin")).strip()
    if not choix.isdigit() or not 1 <= int(choix) <= len(lignes):
        return
    nom, cle, _ = lignes[int(choix) - 1]
    if not _ask_text_yes(
        t("mail_tls_unpin_question").format(
            account=_printable(nom), endpoint=cle
        )
    ):
        return
    try:
        tls_trust.unpin(nom, cle, path)
    except (AccountError, OSError) as exc:
        print(f"{t('mail_tls_pin_failed')} {exc}")
        return
    print(t("mail_tls_unpinned").format(endpoint=cle))


def prompt_mail_cache(todo, *, base=None) -> None:
    """Menu [4] : défaut général du mode, mode d'un compte, taille et
    purge, conversion d'un cache d'un mode à l'autre. `base` est la base
    des caches (`default_base()` sans elle)."""
    while True:
        current = todo_prefs.get("mail_cache_mode", "clear")
        help_info = f"""{todo._menu_header()}
[1] {t("mail_cache_default_mode")} ({current})
[2] {t("mail_cache_account_mode")}
[3] {t("mail_cache_size_purge")}
[4] {t("mail_cache_convert")}
{retour(t('Back'))}"""
        status = click.prompt(help_info)
        print()
        if status == "0":
            return
        if status == "1":
            mode = input(t("mail_ask_mode")).strip()
            if mode in CACHE_MODES:
                _reconcile_default(todo, mode, base=base)
            else:
                print(t("Command not found !"))
        elif status == "2":
            account, accounts = _pick_account()
            if account is None:
                continue
            mode = input(t("mail_ask_mode")).strip()
            _account_mode_entry(
                todo,
                account,
                accounts,
                mode if mode in CACHE_MODES else None,
                base=base,
            )
        elif status == "3":
            _cache_size_and_purge(todo, base=base)
        elif status == "4":
            _convert_entry(todo, base=base)
        else:
            print(t("Command not found !"))


class _NoAccountMode:
    """Un compte sans mode propre : `mode_request` n'y lit que la
    préférence générale."""

    cache_mode = None


def _general_request(prefs_get=None) -> str | None:
    """La préférence générale si elle est lisible et valide, sinon None."""
    return mode_request(_NoAccountMode(), prefs_get)


def _settle_account_mode(account, accounts, target, prefs_get=None) -> None:
    """Le réglage du compte une fois son cache converti en `target`.

    Une demande `ephemeral` n'est jamais touchée ; un mode propre différent
    de la cible devient la cible ; un compte qui hérite d'une préférence
    lisible différente de la cible est épinglé sur la cible ; sinon rien.
    `accounts` est enregistré si le compte change ; l'erreur d'écriture
    (`AccountError`, `OSError`) remonte, et `convert_cache` la rend par
    `mode_saved`."""
    if mode_request(account, prefs_get) == "ephemeral":
        return
    if account.cache_mode is not None:
        if account.cache_mode == target:
            return
    else:
        general = _general_request(prefs_get)
        if general is None or general == target:
            return
    account.cache_mode = target
    mail_accounts.save(accounts)


def _offer_conversion(
    todo, account, source, target, *, on_committed, base=None
) -> bool:
    """Demande confirmation (`mail_cache_convert_confirm_<target>` : vers
    `clear`, la question avertit que sujets, adresses, corps et index
    deviennent lisibles sur le disque), puis convertit. Rend vrai si le
    cache est désormais en `target`."""
    question = t(f"mail_cache_convert_confirm_{target}").format(
        account=account.name, source=source, target=target
    )
    if input(question).strip().lower() not in _YES:
        return False
    return _run_conversion(
        todo, account, target, on_committed=on_committed, base=base
    )


def _run_conversion(todo, account, target, *, on_committed, base=None) -> bool:
    """`convert_cache` avec le coffre du CLI, une progression sur une
    ligne, la question des pertes de reconnaissance et `on_committed`,
    puis le résumé. Rend vrai si le cache est désormais en `target`.

    Ne lève jamais : sur toute exception, Ctrl-C compris, la cible est
    atteinte quand `ConvertError.committed` le dit (l'état sur le disque
    a passé le point de non-retour, rescellement compris) ; une autre
    exception relit le mode inscrit, qui ne tranche que si la cible
    diffère de la source. Atteinte, `on_committed` est rappelé (il est
    idempotent) et le message dit que l'effacement de l'ancienne copie
    s'achève à la prochaine ouverture ; sinon le cache est resté dans sa
    source."""
    from script.todo.mail import cache_convert

    nom = account.name
    source = inscribed_mode(account, base)

    def progression(etape, fait, total):
        texte = t(f"mail_cache_convert_progress_{etape}").format(
            done=fait, total=total
        )
        print(f"\r{texte}", end="\n" if fait >= total else "", flush=True)

    def pertes(journal, envois):
        question = t("mail_cache_convert_losses_confirm").format(
            journal=journal, auto_sent=envois
        )
        return input(question).strip().lower() in _YES

    try:
        resultat = cache_convert.convert_cache(
            account,
            target,
            secrets=secret_store_for(todo),
            base=base,
            progress=progression,
            confirm_losses=pertes,
            on_committed=on_committed,
        )
    except (Exception, KeyboardInterrupt) as exc:
        print()
        if isinstance(exc, cache_convert.ConvertError):
            atteint = exc.committed
        else:
            try:
                atteint = (
                    source != target
                    and inscribed_mode(account, base) == target
                )
            except Exception:
                atteint = False
        if atteint:
            try:
                on_committed(target)
            except Exception as erreur:
                _logger.error(
                    "mode du compte %s non enregistré : %s", nom, erreur
                )
                print(
                    t("mail_cache_convert_mode_unsaved").format(target=target)
                )
            print(
                t("mail_cache_convert_incomplete").format(
                    account=nom, target=target
                )
            )
            return True
        if isinstance(exc, cache_convert.ConvertError) and exc.reason != (
            "incomplete"
        ):
            print(exc)
        else:
            print(
                t("mail_cache_convert_cancelled").format(
                    account=nom, source=source
                )
            )
        return False
    print(
        t("mail_cache_converted").format(
            account=nom,
            target=target,
            messages=resultat.messages,
            bodies=resultat.bodies,
            journal=resultat.rule_log,
        )
    )
    if resultat.legacy_keys or resultat.legacy_auto_sent:
        print(
            t("mail_cache_convert_legacy").format(
                journal=resultat.legacy_keys,
                auto_sent=resultat.legacy_auto_sent,
            )
        )
    if not resultat.mode_saved:
        print(t("mail_cache_convert_mode_unsaved").format(target=target))
    return True


def _has_clear_residue(account, base=None) -> bool:
    """Vrai si le cache persistant du compte garde des restes clairs."""
    racine = cache_root(account, "clear", base)
    try:
        with probe_connection(racine / "cache.db") as conn:
            return conn is not None and has_clear_residue(conn, racine)
    except Exception:
        return False


def _needs_reseal(account, base=None) -> bool:
    """Vrai si le cache persistant du compte a son journal des règles salé
    en clair (`epoch_salted_clear`) : en `encrypted`, il ne s'ouvre
    qu'après un rescellement."""
    racine = cache_root(account, "clear", base)
    try:
        with probe_connection(racine / "cache.db") as conn:
            return conn is not None and epoch_salted_clear(conn)
    except Exception:
        return False


def _convert_entry(todo, *, base=None) -> None:
    """[4] : convertit le cache d'un compte dans l'autre mode persistant.

    Un compte qui demande `ephemeral` (lui-même ou par la préférence dont
    il hérite) n'est pas converti ; un compte sans cache, dont le cache ne
    se lit pas ou porte un mode inconnu, non plus. Un cache `encrypted`
    qui garde des restes clairs se voit d'abord proposer un rescellement
    en entier ; refusé, la question habituelle (vers `clear`) suit."""
    account, accounts = _pick_account()
    if account is None:
        return
    nom = account.name
    if mode_request(account) == "ephemeral":
        print(t("mail_cache_convert_ephemeral").format(account=nom))
        return
    inscrit = inscribed_mode(account, base)
    if inscrit is None:
        print(t("mail_cache_convert_no_cache").format(account=nom))
        return
    if inscrit == PROBE_UNKNOWN:
        print(t("mail_cache_unreadable").format(account=nom))
        return
    if inscrit not in PERSISTENT_MODES:
        print(
            t("mail_err_cache_mode_invalid").format(
                account=nom, inscribed=shown_mode(inscrit)
            )
        )
        return

    def regle(cible):
        _settle_account_mode(account, accounts, cible)

    if inscrit == "encrypted" and _has_clear_residue(account, base):
        question = t("mail_cache_reseal_confirm").format(account=nom)
        if input(question).strip().lower() in _YES:
            _run_conversion(
                todo, account, "encrypted", on_committed=regle, base=base
            )
            return
    cible = "clear" if inscrit == "encrypted" else "encrypted"
    _offer_conversion(
        todo, account, inscrit, cible, on_committed=regle, base=base
    )


def _account_mode_entry(
    todo, account, accounts, nouveau, *, base=None
) -> None:
    """[2] : le mode propre d'un compte (`nouveau`, None pour hériter).

    Si la demande qui en résulte (le mode saisi, sinon la préférence
    lisible) est persistante et diffère du mode inscrit dans un cache
    existant, la conversion est proposée ; le mode saisi n'est enregistré
    que si elle aboutit (par `on_committed`). Refusée ou annulée avant
    l'échange : rien n'est enregistré. `encrypted` sur un cache chiffré au
    journal salé en clair, qui ne s'ouvrirait pas, propose de même le
    rescellement. `ephemeral` sur un compte qui a un cache s'enregistre et
    dit que ce cache reste sur le disque."""
    demande = nouveau or _general_request()
    inscrit = inscribed_mode(account, base)

    def enregistre(_cible=None):
        account.cache_mode = nouveau
        mail_accounts.save(accounts)

    if (
        demande in PERSISTENT_MODES
        and inscrit in PERSISTENT_MODES
        and demande != inscrit
    ):
        if not _offer_conversion(
            todo, account, inscrit, demande, on_committed=enregistre, base=base
        ):
            print(t("mail_cache_account_mode_unchanged"))
        return
    if (
        demande == "encrypted"
        and inscrit == "encrypted"
        and _needs_reseal(account, base)
    ):
        question = t("mail_cache_reseal_confirm").format(account=account.name)
        if input(question).strip().lower() not in _YES or not _run_conversion(
            todo, account, "encrypted", on_committed=enregistre, base=base
        ):
            print(t("mail_cache_account_mode_unchanged"))
        return
    enregistre()
    if nouveau == "ephemeral" and inscrit is not None:
        montre = (
            t("mail_cache_mode_unreadable")
            if inscrit == PROBE_UNKNOWN
            else shown_mode(inscrit)
        )
        print(
            t("mail_cache_ephemeral_keeps_disk").format(
                account=account.name, mode=montre
            )
        )


def _reconcile_default(todo, mode, *, base=None) -> None:
    """[1] : le défaut général passe à `mode` sans laisser aucun compte
    refusé.

    Les comptes qui en héritent (`cache_mode` nul) et dont le cache inscrit
    un autre mode persistant sont, dans CET ordre : épinglés sur leur mode
    inscrit (un seul enregistrement ; s'il échoue, la préférence n'est pas
    écrite), puis la préférence est écrite, puis la conversion est
    proposée compte par compte ; une conversion aboutie les désépingle. Un
    Ctrl-C ou une erreur à n'importe quel moment laisse donc chaque compte
    ouvrable. `ephemeral` n'épingle rien : il dit seulement que les caches
    restent sur le disque."""
    accounts = _load_accounts()
    inscrits = {}
    for account in accounts:
        if account.cache_mode is None:
            inscrit = inscribed_mode(account, base)
            if inscrit in PERSISTENT_MODES and inscrit != mode:
                inscrits[account.name] = inscrit
    concernes = [a for a in accounts if a.name in inscrits]
    if mode == "ephemeral":
        todo_prefs.set("mail_cache_mode", mode)
        for account in concernes:
            print(
                t("mail_cache_ephemeral_keeps_disk").format(
                    account=account.name, mode=inscrits[account.name]
                )
            )
        return
    if concernes:
        for account in concernes:
            account.cache_mode = inscrits[account.name]
        try:
            mail_accounts.save(accounts)
        except (AccountError, OSError) as exc:
            for account in concernes:
                account.cache_mode = None
            print(exc)
            return
    todo_prefs.set("mail_cache_mode", mode)
    epingles = {a.name for a in concernes}
    try:
        for account in concernes:

            def desepingle(_cible, account=account):
                account.cache_mode = None
                try:
                    mail_accounts.save(accounts)
                except BaseException:
                    account.cache_mode = inscrits[account.name]
                    raise
                epingles.discard(account.name)

            _offer_conversion(
                todo,
                account,
                inscrits[account.name],
                mode,
                on_committed=desepingle,
                base=base,
            )
    finally:
        for account in concernes:
            if account.name in epingles:
                print(
                    t("mail_cache_default_pinned").format(
                        account=account.name, mode=inscrits[account.name]
                    )
                )


def _cache_size_and_purge(todo, *, base=None) -> None:
    """[3] : la taille de chaque cache, puis la purge d'un compte.

    Une ligne signale un compte dont le réglage contredit le cache. La
    purge ouvre le cache dans le mode qu'il inscrit et garde `meta`, le
    journal des règles et la file ; elle n'efface jamais rien sur un refus
    de mode ni pendant une conversion. Un cache illisible est effacé en
    entier, sous le verrou exclusif ; un cache de mode inconnu, ou chiffré
    sans sa clé, seulement après une seconde question."""
    accounts = _load_accounts()
    if not accounts:
        print(t("mail_no_account"))
        return
    for row in cache_summary(accounts, base=base):
        ko = row["size"] // 1024
        if row["refused"]:
            refus = t("mail_cache_summary_refused").format(
                requested=row["mode"], inscribed=shown_mode(row["inscribed"])
            )
            print(f"  {row['name']} — {refus} — {ko} ko")
        else:
            print(f"  {row['name']} — {row['mode']} — {ko} ko")
    account, _ = _pick_account()
    if account is None:
        return
    if input(t("mail_purge_confirm")).strip().lower() not in ("o", "y"):
        return
    _purge(todo, account, base)


def _purge(todo, account, base=None) -> None:
    nom = account.name
    _finish_pending_conversion(nom, base)
    inscrit = inscribed_mode(account, base)
    if inscrit == PROBE_UNKNOWN:
        _erase_cache(account, base)
        return
    if inscrit is not None and inscrit not in PERSISTENT_MODES:
        question = t("mail_cache_purge_invalid_confirm").format(
            account=nom, inscribed=shown_mode(inscrit)
        )
        if input(question).strip().lower() in _YES:
            _erase_cache(account, base)
        return
    mode = inscrit or resolve_mode(account, base=base)
    store = Store(
        account,
        mode=mode,
        secrets=secret_store_for(todo) if mode != "clear" else None,
        base=base,
    )
    try:
        store.open()
    except CacheKeyMissing as exc:
        print(exc)
        question = t("mail_cache_purge_no_key_confirm").format(account=nom)
        if input(question).strip().lower() in _YES:
            _erase_cache(account, base)
        return
    except (CacheBusy, CacheModeMismatch) as exc:
        print(exc)
        return
    except StoreError as exc:
        # Le cache est illisible : on ne peut pas le vider par SQL, mais
        # c'est exactement le cas où l'utilisateur a besoin qu'il
        # disparaisse.
        print(exc)
        _erase_cache(account, base)
        return
    try:
        store.purge_all()
    finally:
        store.close()
    print(t("mail_purged"))


def _erase_cache(account, base=None) -> None:
    """Efface entièrement le cache persistant du compte, sous le verrou
    exclusif puis le verrou d'écriture SQLite de sa base (`hold_writers` :
    un processus qui y écrit sans prendre le verrou d'usage refuse
    l'effacement) : la racine, les copies d'une conversion et son état.
    Effacer la seule racine laisserait une reprise faire renaître une copie
    que l'utilisateur vient de purger. La base illisible peut porter du
    clair, d'où l'effacement sûr."""
    from script.todo.mail.cache_convert import hold_writers, secure_erase

    nom = account.name
    base = Path(base) if base is not None else default_base()
    occupe = t("mail_cache_convert_busy_open").format(account=nom)
    with cache_exclusive(nom, base) as tenu:
        if not tenu:
            print(occupe)
            return
        with hold_writers(base / nom / "cache.db") as libre:
            if not libre:
                print(occupe)
                return
            ctl = cache_ctl_dir(nom, base)
            for chemin in (
                base / nom,
                ctl / "old",
                ctl / "new",
                ctl / CONVERT_STATE_NAME,
            ):
                secure_erase(chemin)
    print(t("mail_purged"))
