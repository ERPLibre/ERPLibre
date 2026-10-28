#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les entrées de menu du client courriel.

Ce module est le SEUL point de contact entre le paquet `mail` et le CLI :
`todo.py` importe `prompt_execute_mail` et rien d'autre. Le sens de la
dépendance est volontaire — `mail` ne doit jamais importer `todo`.
"""

from __future__ import annotations

import getpass
import logging
import os
import shutil
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import click

from script.todo import todo_prefs
from script.todo.mail import account_setup
from script.todo.mail import accounts as mail_accounts
from script.todo.mail.accounts import PRESETS, AccountError
from script.todo.mail.secrets import SecretError, SecretStore
from script.todo.mail.store import Store, StoreError, resolve_mode
from script.todo.todo_i18n import t

CACHE_MODES = ("clear", "encrypted", "ephemeral")

# Chemin proposé par défaut pour un kdbx nouvellement créé — voir
# `account_setup.py`, la seule source de vérité, aussi utilisée par le TUI.
_DEFAULT_KDBX_PATH = account_setup.DEFAULT_KDBX_PATH

# `True` une fois `_configure_mail_logging` passée : évite d'empiler un
# second `FileHandler` si l'utilisateur rouvre le menu courriel plusieurs
# fois dans le même processus `todo`.
_LOG_CONFIGURED = False


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
    # Sur le logger PARENT de tout le paquet (`script.todo.mail`, préfixe
    # commun de `script.todo.mail.tui`, `script.todo.mail.imap_sync`, ...) :
    # un seul gestionnaire couvre tous les modules, sans qu'aucun d'eux
    # n'ait à en connaître l'existence.
    logger = logging.getLogger("script.todo.mail")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # `todo.py` appelle `logging.basicConfig()` à l'IMPORT (ligne 68), ce qui
    # pose un `StreamHandler` sur le logger RACINE. `propagate` vaut `True`
    # par défaut : sans cette ligne, chaque `_logger.exception(...)` du
    # paquet remonterait AUSSI jusqu'à ce gestionnaire — donc sur le
    # terminal que Textual possède pendant tout le TUI, silencieusement. La
    # fuite se voit aussi hors du TUI : sous `unittest`, les lignes du paquet
    # se mêlent à la sortie pointillée dès qu'un test importe `todo` avant
    # les tests courriel dans le même processus.
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
    _configure_mail_logging()
    while True:
        help_info = f"""{todo._menu_header()}
[1] {t("mail_open_tui")}
[2] {t("mail_accounts_menu")}
[3] {t("mail_sync_now")}
[4] {t("mail_cache_menu")}
[5] {t("mail_stats_menu")}
[6] {t("mail_rules_menu")}
[0] {t("Back")}"""
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
        else:
            print(t("Command not found !"))


# Lignes du journal des règles imprimées par le menu, les plus récentes.
RULES_MENU_LOG_LINES = 50


def prompt_mail_rules(todo, *, base=None) -> None:
    """Menu [6] : lister, activer, déplacer, supprimer les règles d'un
    compte, lire leur journal, régler le rapport de statistiques et
    essayer une règle sur un message, sans ouvrir le TUI.

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
        Store(account, mode=resolve_mode(account), base=base)
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
[0] {t("Back")}"""
        status = click.prompt(help_info)
        print()
        if status == "0":
            return
        try:
            if status == "1":
                _list_rules(account.name, rules_base)
            elif status in ("2", "3", "4"):
                _change_rule(account.name, rules_base, status)
            elif status == "5":
                _show_rules_log(todo, account, rules_base, base)
            elif status == "6":
                _report_settings(todo, account, rules_base, base)
            elif status == "7":
                _trial(todo, account, rules_base, base)
            else:
                print(t("Command not found !"))
        except RuleError as exc:
            # `RulesBusy` comprise : une passe tient le verrou du compte.
            print(exc)


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

    from script.todo.mail.rules import storage
    from script.todo.mail.rules.model import RuleError

    try:
        noms = {
            rule.id: rule.name or rule.id
            for rule in storage.load(account.name, base=base_rules)
        }
    except RuleError:
        noms = {}
    mode = resolve_mode(account)
    magasin = Store(
        account,
        mode=mode,
        secrets=secret_store_for(todo) if mode != "clear" else None,
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
        raison = ligne["reason"]
        texte = t(f"mail_rules_outcome_{ligne['outcome']}")
        if raison:
            texte += f" ({t(f'mail_rules_reason_{raison}')})"
        nom = noms.get(ligne["rule_id"], ligne["rule_id"])
        print(
            f"  {quand}  {_printable(nom)}  {texte}"
            f"  {_printable(ligne['sender'])}  {_printable(ligne['subject'])}"
        )


def _open_store(todo, account, base=None) -> Store:
    """Le cache du compte, ouvert ; le coffre n'est demandé que pour un
    cache chiffré."""
    mode = resolve_mode(account)
    magasin = Store(
        account,
        mode=mode,
        secrets=secret_store_for(todo) if mode != "clear" else None,
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
            magasin, reglages, now=int(time.time()), sender=None
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
    from script.todo.mail.store import Store, resolve_mode

    comptes = _load_accounts()
    if not comptes:
        print(t("mail_no_account"))
        return
    coffre = None
    for compte in comptes:
        mode = resolve_mode(compte)
        if mode != "clear" and coffre is None:
            coffre = secret_store_for(todo)
        print(f"\n=== {compte.name} ===")
        magasin = Store(
            compte,
            mode=mode,
            secrets=coffre if mode != "clear" else None,
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
        open_sessions,
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
            return f"{session.account.name} : {session.error}", None
        lignes = []
        # La file part AVANT la relecture, comme dans le TUI : une commande
        # qui promet de synchroniser doit envoyer ce qui attend, sinon un
        # message écrit hors ligne dort jusqu'à la prochaine ouverture du
        # client — le seul endroit d'où la file partait.
        try:
            partis, _, echoues = flush_outbox(session)
            if partis or echoues:
                ligne = (
                    f"{session.account.name} :"
                    f" {t('mail_outbox_flushed')} {partis}"
                )
                if echoues:
                    ligne += f" — {t('mail_outbox_failed')} {echoues}"
                lignes.append(ligne)
        except Exception as exc:
            lignes.append(f"{session.account.name} : {exc}")
        try:
            report = session.sync()
        except Exception as exc:
            lignes.append(f"{session.account.name} : {exc}")
            return "\n".join(lignes), None
        lignes.append(
            f"{session.account.name} : {report.new_messages}"
            f" {t('mail_new_messages')}"
        )
        lignes += [f"  {e}" for e in report.errors]
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
[0] {t("Back")}"""
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
    while True:
        current = todo_prefs.get("mail_cache_mode", "clear")
        help_info = f"""{todo._menu_header()}
[1] {t("mail_cache_default_mode")} ({current})
[2] {t("mail_cache_account_mode")}
[3] {t("mail_cache_size_purge")}
[0] {t("Back")}"""
        status = click.prompt(help_info)
        print()
        if status == "0":
            return
        if status == "1":
            mode = input(t("mail_ask_mode")).strip()
            if mode in CACHE_MODES:
                todo_prefs.set("mail_cache_mode", mode)
            else:
                print(t("Command not found !"))
        elif status == "2":
            account, accounts = _pick_account()
            if account is None:
                continue
            mode = input(t("mail_ask_mode")).strip()
            account.cache_mode = mode if mode in CACHE_MODES else None
            mail_accounts.save(accounts)
        elif status == "3":
            _cache_size_and_purge(todo)
        else:
            print(t("Command not found !"))


def _cache_size_and_purge(todo) -> None:
    accounts = _load_accounts()
    if not accounts:
        print(t("mail_no_account"))
        return
    for row in cache_summary(accounts):
        print(f"  {row['name']} — {row['mode']} — {row['size'] // 1024} ko")
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
