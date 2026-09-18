#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Modem du CLI TODO.

Rassemble ce qui touche au modem USB cellulaire : son état, ses SMS, ses
appels, et la mise en place d'Asterisk qui s'en sert comme ligne.

L'état est relu à chaque tour de boucle plutôt que mis en cache : une SIM
retirée, un modem débranché ou un service arrêté ailleurs apparaissent sans
qu'on ait à quitter le menu.
"""
from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys

import click

from script.todo.modem import asterisk as ast_mod
from script.todo.modem import audio as audio_mod
from script.todo.modem import calls as calls_mod
from script.todo.modem import device as device_mod
from script.todo.modem import diagnostic as diag_mod
from script.todo.modem import messaging as sms_mod
from script.todo.modem import messagerie_vocale as mv_mod
from script.todo.modem import repondeur as rep_mod
from script.todo.modem import sipgo as sipgo_mod
from script.todo.modem import udev as udev_mod

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


def _bandeau():
    """Une ligne d'état, relue à chaque affichage."""
    index = device_mod.premier_modem()
    if index is None:
        return "  " + t("modem_absent")
    e = device_mod.etat(index)
    voix_ok, voix_motif = calls_mod.voix_disponible()
    port = udev_mod.port_reserve()
    reserve = (
        t("modem_port_reserved") + " " + os.path.basename(port)
        if port
        else t("modem_port_shared")
    )
    return (
        f"  {e.get('modele', '?')} — {e.get('firmware', '?')}\n"
        f"  {t('modem_line')}: {e.get('numero', '?')}"
        f"  |  {e.get('operateur', '?')} {e.get('technologie', '')}"
        f"  |  {t('modem_signal')}: {e.get('signal', '?')}%\n"
        # Le motif et non un simple oui/non : « carte detectee » sur une
        # carte qu'un serveur audio tient ouverte est vrai et inutile.
        f"  {t('modem_voice')}: "
        + (t("modem_voice_ok") if voix_ok else voix_motif.split(".")[0])
        + f"  |  {t('modem_at_port')}: {reserve}\n"
        + f"  {t('modem_voicemail')}: {_etat_messagerie()}\n"
        # Ces deux etats vivaient a cote de leurs entrees, qui sont passees
        # dans des sous-menus. Ils restent ici : savoir d'un coup d'oeil que
        # le repondeur est eteint evite d'attendre en vain un message.
        + f"  {t('modem_answering_short')}: {_etat_repondeur()}"
        + f"  |  {t('modem_audio_rule_short')}: {_etat_regle_audio()}"
    )


def _etat_messagerie() -> str:
    """Le drapeau de la boite vocale de l'operateur, en une ligne.

    La source est toujours dite : une lecture de la SIM est fraiche, un etat
    laisse par le service a un age, et un etat trop vieux ne se presente pas
    comme courant.
    """
    lecture = mv_mod.lire()
    etat = lecture["etat"]
    if etat == mv_mod.ATTENTE:
        texte = t("modem_voicemail_waiting")
    elif etat == mv_mod.VIDE:
        texte = t("modem_voicemail_empty")
    else:
        return t("modem_voicemail_unknown") + (
            " — " + lecture["detail"] if lecture["detail"] else "")
    if lecture["source"] == "service":
        texte += " (" + t("modem_voicemail_from_service") % mv_mod.age_lisible(
            lecture["age"]) + ")"
        if lecture["perime"]:
            texte += " — " + t("modem_voicemail_stale")
    return texte


def _bandeau_voip():
    """Les deux technologies côte à côte : on voit ce qui est en place."""
    if ast_mod.installe():
        lignes = ast_mod.lignes_configurees()
        ast = (
            (
                t("asterisk_running")
                if ast_mod.actif()
                else t("asterisk_stopped")
            )
            + " — "
            + (", ".join(lignes) or "—")
        )
    else:
        ast = t("voip_not_installed")

    if sipgo_mod.installe():
        c = sipgo_mod.config()
        sip = (
            t("voip_configured") + " — " + (c.get("VOIP_TRUNK") or "?")
            if sipgo_mod.configure()
            else t("voip_no_trunk")
        )
    else:
        sip = t("voip_not_installed")

    return f"  Asterisk         : {ast}\n" f"  erplibre_sip_go  : {sip}"


def prompt_execute_modem(todo) -> None:
    """Le menu Modem : ce qu'on ouvre souvent devant, le reste range.

    Le clavier reste seul au premier ecran : c'est le seul outil qu'on ouvre
    pour SE SERVIR du modem plutot que pour le regler. Les reglages systeme,
    qui se posent une fois a l'installation, tiennent dans un sous-menu.
    """
    while True:
        help_info = f"""{todo._menu_header()}
{_bandeau()}
{_bandeau_voip()}

[1] {t("modem_dialer")}
[2] {t("modem_menu_state")}
[3] {t("modem_menu_calls")}
[4] {t("modem_menu_sms")}
[5] {t("modem_answering")}
[6] {t("modem_menu_audio")}
[7] {t("modem_menu_voip")}
[0] {t("Back")}"""
        status = click.prompt(help_info)
        print()
        if status == "0":
            return
        elif status == "1":
            _clavier(todo)
        elif status == "2":
            _sous_menu_etat()
        elif status == "3":
            _sous_menu_appels(todo)
        elif status == "4":
            _sous_menu_sms(todo)
        elif status == "5":
            _repondeur(todo)
        elif status == "6":
            _sous_menu_audio()
        elif status == "7":
            _sous_menu_voip(todo)
        else:
            print(t("Command not found !"))


def _sous_menu(titre, entrees):
    """Affiche un sous-menu et appelle ce qui est choisi.

    `entrees` est une suite de (libelle, action). La numerotation se deduit de
    l'ordre : une entree ajoutee au milieu ne peut pas se retrouver branchee
    sur l'action d'une autre, ce qu'une chaine de conditions ecrite a la main
    finit toujours par produire.
    """
    while True:
        lignes = [f"  {titre}", ""]
        for numero, (libelle, _action) in enumerate(entrees, start=1):
            lignes.append(f"[{numero}] {libelle}")
        lignes.append(f"[0] {t('Back')}")
        choix = click.prompt("\n".join(lignes))
        print()
        if choix == "0":
            return
        if choix.isdigit() and 1 <= int(choix) <= len(entrees):
            entrees[int(choix) - 1][1]()
        else:
            print(t("Command not found !"))


def _sous_menu_etat():
    _sous_menu(t("modem_menu_state"), (
        (t("modem_status"), _etat_detaille),
        (t("modem_diag"), _diagnostic),
    ))


def _sous_menu_appels(todo):
    _sous_menu(t("modem_menu_calls"), (
        (t("modem_call"), _appeler),
        (t("modem_hangup"), _raccrocher),
        (t("modem_calls_list"), _lister_appels),
        (t("voip_call"), lambda: _appel_voip(todo)),
    ))


def _sous_menu_sms(todo):
    _sous_menu(t("modem_menu_sms"), (
        (t("modem_sms_send"), _envoyer_sms),
        (t("modem_sms_list"), _lister_sms),
        (t("modem_gateway_agent"), lambda: _passerelle(todo)),
    ))


def _sous_menu_audio():
    """Les essais a cote des reglages qu'ils eprouvent.

    Sonder le chemin audio et essayer le combine servent a regler le son :
    ils sont plus utiles ici qu'entre une regle udev et une passerelle SMS.
    """
    _sous_menu(t("modem_menu_audio"), (
        (t("modem_probe_audio"), _sonder_audio),
        (t("modem_audio_try"), _essai_combine),
        (t("modem_uac_toggle"), _basculer_uac),
        (t("modem_audio_rule") + " — " + _etat_regle_audio(), _regle_audio),
        (t("modem_udev"), _regle_udev),
    ))


def _sous_menu_voip(todo):
    _sous_menu(t("modem_menu_voip"), (
        (t("voip_install"), lambda: _installer_voip(todo)),
        (t("voip_status"), _etat_voip),
    ))


def _index_ou_plainte():
    index = device_mod.premier_modem()
    if index is None:
        print("  " + t("modem_absent"))
    return index


def _etat_detaille():
    index = _index_ou_plainte()
    if index is None:
        return
    for cle, valeur in device_mod.etat(index).items():
        print(f"  {cle:14} {valeur}")


def _diagnostic():
    print("  " + t("modem_diag_warn"))
    if not click.confirm("  " + t("modem_continue"), default=False):
        return
    brut, conclusions = diag_mod.sonder()
    print()
    for ligne in conclusions:
        print("  → " + ligne)
    print()
    print("  " + t("modem_raw") + " :")
    for ligne in brut.splitlines():
        if ligne.strip():
            print("    " + ligne.strip())


def _clavier(todo=None):
    """Ouvre le clavier, avec le code de la messagerie s'il est atteignable.

    Le code n'est lu QUE si le coffre est deja ouvert : demander son mot de
    passe pour ouvrir un clavier de composition serait hors de propos, et
    l'interface plein ecran ne peut pas le demander elle-meme. Sans lui, la
    recuperation se refuse en le disant ; le reste du clavier fonctionne.
    """
    index = _index_ou_plainte()
    if index is None:
        return
    from script.todo.modem import tui as tui_mod

    code = ""
    manager = getattr(todo, "kdbx_manager", None)
    if todo is not None and (manager is None or getattr(manager, "_kdbx", None)):
        from script.todo.modem import code_messagerie as code_mod

        try:
            code = code_mod.lire(code_mod.coffre(todo)) or ""
        except Exception:
            # Coffre absent, ferme ou illisible : le clavier s'ouvre quand
            # meme, et la recuperation dira ce qui manque.
            code = ""
    if not tui_mod.lancer(index, code_messagerie=code):
        print("  " + t("modem_tui_missing"))


def _appeler():
    """Composer depuis le menu, avec la même confirmation que la TUI."""
    index = _index_ou_plainte()
    if index is None:
        return
    voix_ok, motif = calls_mod.voix_disponible()
    if not voix_ok:
        print("  ⚠  " + motif)
    brut = input("  " + t("modem_number") + " : ").strip()
    norm = calls_mod.numero_valide(brut)
    if not norm:
        print("  " + t("modem_number_invalid"))
        return
    # La confirmation répète le numéro NORMALISÉ : c'est lui qui partira, pas
    # la suite de chiffres telle qu'elle a été tapée.
    if not click.confirm(
        f"  {t('modem_call_confirm')} +{norm} ?", default=False
    ):
        return
    ok, sortie = calls_mod.appeler(norm)
    print("  " + ("✔ " if ok else "✖ ") + (sortie or "").strip()[:300])


def _raccrocher():
    ok, sortie = calls_mod.raccrocher()
    print("  " + ("✔ " if ok else "✖ ") + (sortie or "").strip()[:200])


def _lister_appels():
    appels = calls_mod.appels_en_cours()
    if not appels:
        print("  " + t("modem_no_call"))
        return
    for a in appels:
        sens = t("modem_out") if a["sortant"] else t("modem_in")
        print(
            f"  {a['index']}  {sens:9} {a['numero']:16} "
            f"{calls_mod.libelle_etat(a['etat'])}"
        )


def _envoyer_sms():
    index = _index_ou_plainte()
    if index is None:
        return
    numero = input("  " + t("modem_number") + " : ").strip()
    if not calls_mod.numero_valide(numero):
        print("  " + t("modem_number_invalid"))
        return
    texte = input("  " + t("modem_sms_text") + " : ").strip()
    if not texte:
        return
    ok, sortie = sms_mod.envoyer(index, numero, texte)
    print("  " + ("✔ " if ok else "✖ ") + (sortie or "").strip()[:200])


def _lister_sms():
    index = _index_ou_plainte()
    if index is None:
        return
    messages = sms_mod.lister(index)
    if not messages:
        print("  " + t("modem_no_sms"))
        return
    for ident, sens in messages[:20]:
        d = sms_mod.lire(ident)
        print(
            f"  {sens:9} {d.get('numero', '?'):16} "
            f"{(d.get('texte') or '')[:60]}"
        )


def _etat_repondeur() -> str:
    """Une ligne d'etat : allume ou non, apres combien, et combien attendent.

    Le compte des messages est dans le libelle du menu plutot que derriere une
    entree : un repondeur ne sert que si l'on sait, sans chercher, qu'il y a
    quelque chose a ecouter.
    """
    reglages = rep_mod.lire()
    attente = len(rep_mod.lister())
    if not reglages.get("actif"):
        etat = "eteint"
    else:
        etat = "%s sonneries" % rep_mod.borner_sonneries(
            reglages.get("sonneries")
        )
    if attente:
        return "%s, %s message(s)" % (etat, attente)
    return etat


def _repondeur(todo=None):
    while True:
        reglages = rep_mod.lire()
        annonce = reglages.get("annonce") or "aucune"
        help_info = f"""  {t("modem_ans_menu")} — {_etat_repondeur()}
  annonce : {annonce}

[1] {t("modem_ans_list")}
[2] {t("modem_ans_greeting")}
[3] {t("modem_ans_greeting_play")}
[4] {t("modem_ans_rings")}
[5] {t("modem_ans_toggle")}
[6] {t("modem_ans_pin")} — {_etat_code_messagerie(todo)}
[7] {t("modem_ans_fetch")}
[0] {t("Back")}"""
        choix = click.prompt(help_info)
        print()
        if choix == "0":
            return
        elif choix == "1":
            _repondeur_messages()
        elif choix == "2":
            _repondeur_enregistrer_annonce()
        elif choix == "3":
            _repondeur_jouer_annonce()
        elif choix == "4":
            _repondeur_sonneries()
        elif choix == "5":
            _repondeur_basculer()
        elif choix == "6":
            _repondeur_code(todo)
        elif choix == "7":
            _repondeur_recuperer(todo)
        else:
            print(t("Command not found !"))


def _etat_code_messagerie(todo) -> str:
    """« defini » ou « non defini », et JAMAIS le code lui-meme.

    Ouvrir le kdbx peut demander son mot de passe : on ne le fait pas pour un
    simple affichage, seulement quand le coffre est deja ouvert.
    """
    from script.todo.modem import code_messagerie as code_mod

    manager = getattr(todo, "kdbx_manager", None)
    if manager is not None and not getattr(manager, "_kdbx", None):
        return t("modem_ans_pin_locked")
    try:
        store = code_mod.coffre(todo)
    except Exception:
        return t("modem_ans_pin_unset")
    return t("modem_ans_pin_set") if code_mod.est_defini(store) else t(
        "modem_ans_pin_unset")


def _repondeur_code(todo):
    """Saisir, remplacer ou effacer le code de la boite vocale.

    Saisi deux fois, sans echo : une faute de frappe ne se voit pas a l'ecran,
    et un code faux ferait echouer chaque recuperation sans dire pourquoi.
    """
    import getpass

    from script.todo.mail.secrets import SecretError
    from script.todo.modem import code_messagerie as code_mod

    print("  " + t("modem_ans_pin_why"))
    print(f"  [1] {t('modem_ans_pin_enter')}")
    print(f"  [2] {t('modem_ans_pin_delete')}")
    print(f"  [0] {t('Back')}")
    choix = input("  > ").strip()
    try:
        if choix == "1" and todo is not None and not code_mod.kdbx_configure(todo):
            # Meme parcours que le courriel : proposer de creer ou de choisir
            # un fichier KeePass. Refuse, le trousseau systeme prend le relais
            # s'il chiffre — sinon rien n'est enregistre.
            from script.todo.mail.menu import _ensure_kdbx

            _ensure_kdbx(todo)
        store = code_mod.coffre(todo)
        if choix == "1":
            code = getpass.getpass("  " + t("modem_ans_pin_ask"))
            if not code:
                return
            if getpass.getpass("  " + t("modem_ans_pin_confirm")) != code:
                print("  " + t("modem_ans_pin_mismatch"))
                return
            ref = code_mod.enregistrer(store, code)
            print("  " + t("modem_ans_pin_saved") % (
                "KeePass" if ref.startswith("kdbx:") else t("modem_ans_pin_keyring")))
        elif choix == "2":
            code_mod.effacer(store)
            print("  " + t("modem_ans_pin_deleted"))
    except code_mod.CodeInvalide as exc:
        print("  " + str(exc))
    except SecretError as exc:
        print("  " + str(exc))


def _repondeur_recuperer(todo):
    """Appeler la messagerie de l'operateur et jouer une recette.

    Pour l'instant, le seul mode est le REPERAGE : code, `1`, puis ecoute sans
    rien effacer. Il mesure ou finit un message et combien dure le silence du
    menu qui suit, ce qu'il faut connaitre avant de confier le `7` — qui
    efface pour de bon — a une machine.
    """
    import os

    from script.todo.mail.secrets import SecretError
    from script.todo.modem import code_messagerie as code_mod
    from script.todo.modem import recuperation as rec_mod

    if not device_mod.port_reserve():
        print("  " + t("modem_ans_fetch_no_port"))
        return
    numero, raison = mv_mod.numero_messagerie()
    if not numero:
        print("  " + raison)
        return
    try:
        code = code_mod.lire(code_mod.coffre(todo))
    except SecretError as exc:
        print("  " + str(exc))
        return
    if not code:
        print("  " + t("modem_ans_fetch_no_code"))
        return
    binaire = os.path.expanduser("~/.local/bin/erplibre-sip-go")
    if not os.path.exists(binaire):
        print("  " + t("modem_ans_fetch_no_binary") % binaire)
        return

    # Le risque AVANT le choix, et non seulement a la confirmation : c'est
    # la limite de l'automatisation, et elle decide de l'option a prendre.
    silence = rec_mod.silence_avant_effacement_s(
        rec_mod.charger_recette("recuperer_un_message"))
    if silence is not None:
        print("  ⚠ " + t("modem_ans_fetch_silence_risk") % (
            str(silence).replace(".", ","), str(silence).replace(".", ",")))
        print()
    print(f"  [1] {t('modem_ans_fetch_one')}")
    print(f"  [2] {t('modem_ans_fetch_survey')}")
    print(f"  [0] {t('Back')}")
    choix = input("  > ").strip()
    if choix not in ("1", "2"):
        return
    recette = "recuperer_un_message" if choix == "1" else "reperage_code_ecoute"
    if choix == "1":
        if mv_mod.lire()["etat"] != mv_mod.ATTENTE:
            print("  " + t("modem_ans_fetch_no_flag"))
            if not click.confirm("  " + t("modem_continue"), default=False):
                return
        print("  " + t("modem_ans_fetch_delete_warn"))
        if not click.confirm("  " + t("modem_continue"), default=False):
            return
    else:
        print("  " + t("modem_ans_fetch_reperage"))
        if not click.confirm("  " + t("modem_continue"), default=True):
            return
    print("  " + t("modem_ans_fetch_running"))
    bilan, wav = rec_mod.jouer(recette, numero, code, binaire, device_mod.PORT_RESERVE)
    del code
    for ligne in rec_mod.resume(bilan):
        print("  " + ligne)
    if wav and os.path.exists(wav):
        print("  " + t("modem_ans_fetch_file") % wav)
    if choix == "1" and wav:
        message = rec_mod.extraire_message(
            wav, bilan, os.path.join(rec_mod.racine(), rec_mod.DOSSIER_RELATIF, "messages"))
        if message:
            print("  " + t("modem_ans_fetch_message") % message)
        elif "garde" in (bilan.get("erreur") or ""):
            print("  " + t("modem_ans_fetch_empty"))
        else:
            print("  " + t("modem_ans_fetch_no_cut"))


def _repondeur_messages():
    """Deux repondeurs, deux facons d'ecouter : on choisit d'abord lequel.

    Le repondeur ERPLibre garde des fichiers, qui se listent et se jouent. La
    boite de l'operateur ne garde rien ici : elle s'ecoute en l'appelant. Les
    montrer cote a cote, chacun avec son etat, dit ou regarder avant d'ouvrir.
    """
    nombre = len(rep_mod.lister())
    print(f"  [1] {t('modem_ans_erplibre')} — "
          + (t("modem_ans_count") % nombre if nombre else t("modem_ans_none")))
    print(f"  [2] {t('modem_ans_operator')} — {_etat_messagerie()}")
    from script.todo.modem import recuperation as rec_mod

    recuperes = rec_mod.lister_messages()
    print(f"  [3] {t('modem_ans_fetched')} — "
          + (t("modem_ans_count") % len(recuperes) if recuperes
             else t("modem_ans_none")))
    print(f"  [0] {t('Back')}")
    choix = input("  > ").strip()
    if choix == "1":
        _repondeur_messages_erplibre()
    elif choix == "2":
        _repondeur_messagerie_operateur()
    elif choix == "3":
        _repondeur_messages_recuperes(recuperes)


def _repondeur_messages_recuperes(messages):
    """Ecouter les messages deja recuperes, puis proposer de les effacer.

    Ceux-ci sont DEJA effaces chez l'operateur : le fichier local en est la
    seule copie, avec l'enregistrement complet de l'appel qui le contient.
    L'effacement est donc propose apres l'ecoute, une fois qu'on sait si le
    message servait.
    """
    from script.todo.modem import recuperation as rec_mod

    if not messages:
        print("  " + t("modem_ans_none"))
        return
    for index, message in enumerate(messages, start=1):
        print("  [%d] %s  %s s" % (
            index,
            (message.get("recupere_le") or "")[:19].replace("T", " "),
            message.get("duree_secondes") or "?"))
    print()
    choix = input("  " + t("modem_ans_play") + " > ").strip()
    if not choix.isdigit() or not 1 <= int(choix) <= len(messages):
        return
    message = messages[int(choix) - 1]
    succes, plainte = rep_mod.jouer(message.get("fichier") or "")
    if not succes:
        print("  " + plainte)
        return
    if input("  " + t("modem_ans_delete") + " > ").strip().lower() in ("o", "y"):
        rec_mod.effacer_message(message)
        print("  " + t("modem_ans_deleted"))
        print("  " + t("modem_ans_full_kept") % (message.get("enregistrement_complet") or "?"))


def _repondeur_messagerie_operateur():
    """Ouvre le clavier sur le numero de la messagerie, sans l'appeler.

    L'appel reste un geste : l'utilisateur voit le numero avant de composer.
    Une fois en ligne, les touches du clavier partent en tonalites, ce qui
    permet de donner le mot de passe et de naviguer dans la messagerie.
    """
    index = _index_ou_plainte()
    if index is None:
        return
    numero, raison = mv_mod.numero_messagerie()
    if not numero:
        print("  " + raison)
        return
    print("  " + t("modem_ans_operator_how") % numero)
    from script.todo.modem import tui as tui_mod

    if not tui_mod.lancer(index, numero_initial=numero):
        print("  " + t("modem_tui_missing"))


def _repondeur_messages_erplibre():
    """Liste, ecoute, puis propose d'effacer ce qu'on vient d'entendre.

    L'effacement est propose APRES l'ecoute et non a cote : c'est le moment ou
    l'on sait si le message servait, et le seul ou le choix est eclaire.
    """
    messages = rep_mod.lister()
    if not messages:
        print("  " + t("modem_ans_none"))
        return
    for index, message in enumerate(messages, start=1):
        print(
            "  [%d] %s  %s  %ss"
            % (
                index,
                (message.get("debut") or "")[:19],
                (message.get("numero") or "inconnu"),
                message.get("duree_secondes") or 0,
            )
        )
    print()
    choix = input("  " + t("modem_ans_play") + " > ").strip()
    if not choix.isdigit() or not 1 <= int(choix) <= len(messages):
        return
    message = messages[int(choix) - 1]
    succes, plainte = rep_mod.jouer(message.get("fichier") or "")
    if not succes:
        print("  " + plainte)
        return
    if input("  " + t("modem_ans_delete") + " > ").strip().lower() in (
        "o",
        "y",
    ):
        rep_mod.effacer(message)
        print("  " + t("modem_ans_deleted"))


def _repondeur_enregistrer_annonce():
    secondes = input("  " + t("modem_ans_seconds") + " [20] > ").strip()
    try:
        secondes = max(3, min(60, int(secondes)))
    except ValueError:
        secondes = 20
    print("  " + t("modem_ans_recording") % secondes)
    succes, resultat = rep_mod.enregistrer_annonce(secondes)
    if not succes:
        print("  " + resultat)
        return
    rep_mod.regler(annonce=resultat)
    print("  " + t("modem_ans_recorded") % resultat)
    print("  " + t("modem_ans_restart"))


def _repondeur_jouer_annonce():
    annonce = rep_mod.lire().get("annonce") or ""
    succes, plainte = rep_mod.jouer(annonce)
    if not succes:
        print("  " + plainte)


def _repondeur_sonneries():
    print("  " + t("modem_ans_rings_why"))
    saisie = input("  " + t("modem_ans_rings_ask") + " > ").strip()
    if not saisie:
        return
    sonneries = rep_mod.borner_sonneries(saisie)
    rep_mod.regler(sonneries=sonneries)
    print("  %s : %s" % (t("modem_ans_rings"), sonneries))
    print("  " + t("modem_ans_restart"))


def _repondeur_basculer():
    reglages = rep_mod.lire()
    rep_mod.regler(actif=not reglages.get("actif"))
    print("  %s : %s" % (t("modem_ans_menu"), _etat_repondeur()))
    print("  " + t("modem_ans_restart"))


def _choisir_technologie():
    """Demande laquelle des deux voies utiliser.

    On pose la question plutôt que de choisir : les deux ont des coûts
    opposés, et c'est une décision d'exploitation, pas un détail technique.
    """
    print()
    print("  [1] erplibre_sip_go — " + t("voip_go_pitch"))
    print("  [2] Asterisk        — " + t("voip_ast_pitch"))
    print("  [0] " + t("Back"))
    return input("  > ").strip()


def _installer_voip(todo):
    choix = _choisir_technologie()
    if choix == "1":
        _installer_sipgo(todo)
    elif choix == "2":
        todo._deploy_asterisk_server()


def _installer_sipgo(todo):
    script = sipgo_mod.chemin_script()
    if not os.path.isfile(script):
        print("  " + t("voip_script_missing") + " " + script)
        return
    print("  " + t("voip_go_install_note"))
    todo.execute.exec_command_live(f"bash {script}", source_erplibre=False)


def _etat_voip():
    print("  Asterisk")
    if not ast_mod.installe():
        print("    " + t("voip_not_installed"))
    else:
        print(
            "    "
            + (
                t("asterisk_running")
                if ast_mod.actif()
                else t("asterisk_stopped")
            )
        )
        print(
            "    "
            + t("asterisk_lines")
            + " : "
            + (", ".join(ast_mod.lignes_configurees()) or "—")
        )
    print()
    print("  erplibre_sip_go")
    if not sipgo_mod.installe():
        print("    " + t("voip_not_installed"))
        return
    print("    " + t("voip_binary") + " : " + (sipgo_mod.binaire() or "?"))
    chemin = sipgo_mod.fichier_env()
    print("    " + t("voip_config") + " : " + (chemin or "—"))
    c = sipgo_mod.config()
    print("    " + t("voip_trunk") + " : " + (c.get("VOIP_TRUNK") or "—"))
    print("    " + t("voip_user") + " : " + (c.get("VOIP_USER") or "—"))
    # On dit si le secret est posé, jamais sa valeur : un secret qui traverse
    # une couche d'affichage finit par s'afficher.
    print(
        "    "
        + t("voip_secret")
        + " : "
        + ("✔" if c.get("mot_de_passe_pose") else "✖")
    )


#: Delai laisse au binaire pour raccrocher avant qu'on l'abatte.
DELAI_ARRET = 8


def _passerelle(todo):
    """Enchaine la demonstration de passerelle SMS, sur le modem de ce poste.

    Les six memes etapes que « TODO › Assistant › SMS », jouees d'affilee et
    arretees au premier echec. Pas un menu : arriver ici veut dire qu'on veut
    la chaine, pas la choisir. Ce qui suppose de reprendre une etape seule, ou
    de changer le numero d'essai, se fait dans l'Assistant, sur le meme etat.

    Le materiel est impose a l'entree, sans le demander : qui arrive par le
    menu du modem a deja choisi. Si la demonstration etait posee sur le
    telephone, la fiche passerelle est a refaire, et `poser_materiel` le dit.

    Le tableau est affiche avant ET apres : avant pour voir d'ou l'on part —
    la demonstration se reprend souvent a mi-chemin — apres pour voir ou elle
    s'est arretee, ce que le defilement des etapes ne montre plus.
    """
    from script.todo.sms import menu as sms_menu
    from script.todo.sms import spec as sms_spec
    from script.todo.sms import steps as sms_steps

    etat = sms_spec.load()
    if sms_menu.poser_materiel(etat, "modem"):
        print("  ⚠️  " + t("sms_materiel_changed"))
    print()
    print(sms_steps.render(etat))
    print()
    sms_menu.enchainer(todo, etat)
    print()
    print(sms_steps.render(etat))


def _lancer_interruptible(args):
    """Lance la commande en lui CONFIANT le terminal, et la tue a la fin.

    Deux besoins qui se contredisent en apparence.

    Le premier : pouvoir la tuer entierement. Le lanceur ordinaire garde
    l'interruption pour lui, le binaire survit, la ligne reste ouverte donc
    facturee, et il retient le port AT et la carte son — l'appel suivant
    echoue alors sans que rien n'explique pourquoi.

    Le second : le binaire pilote l'appel au clavier. Or un processus place
    dans une nouvelle SESSION perd le terminal de controle et ne peut plus
    y lire une seule touche. On lui donne donc un nouveau GROUPE dans la
    meme session, puis le premier plan : il recoit alors les frappes ET les
    signaux du terminal, et « os.killpg » atteint toujours tout le monde.

    Rendre le premier plan est OBLIGATOIRE, y compris apres une erreur :
    un terminal dont le groupe de premier plan a disparu se fige.
    """
    interactif = sys.stdin.isatty()
    proc = subprocess.Popen(
        args,
        preexec_fn=os.setpgrp if interactif else None,
        start_new_session=not interactif,
    )
    fd = sys.stdin.fileno()
    # Ceder le terminal arrete l'ecrivain par SIGTTOU : on l'ignore le temps
    # de la manoeuvre, dans les deux sens.
    ancien_ttou = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    groupe_a_nous = os.getpgrp() if interactif else None
    try:
        if interactif:
            try:
                os.tcsetpgrp(fd, os.getpgid(proc.pid))
            except OSError:
                # Sans premier plan, le binaire tourne quand meme ; il perd
                # seulement ses commandes au clavier.
                pass
        try:
            proc.wait()
            return
        except KeyboardInterrupt:
            pass
        _abattre(proc)
        print()
        print("  " + t("modem_call_interrupted"))
    finally:
        if interactif and groupe_a_nous is not None:
            try:
                os.tcsetpgrp(fd, groupe_a_nous)
            except OSError:
                pass
        signal.signal(signal.SIGTTOU, ancien_ttou)


def _abattre(proc):
    """Interrompt le groupe du processus, puis l'abat s'il s'attarde.

    On passe par SIGINT et on laisse du temps : le binaire sait raccrocher
    et refermer le canal voix, ce qu'un SIGKILL immediat empecherait.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)
    except OSError:
        proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=DELAI_ARRET)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except OSError:
        proc.kill()
    try:
        proc.wait(timeout=DELAI_ARRET)
    except subprocess.TimeoutExpired:
        pass


def _choisir_annonce():
    """Propose les annonces livrées, ou un chemin, ou aucune."""
    sons = sipgo_mod.sons_fournis()
    print()
    for i, chemin in enumerate(sons, 1):
        print(f"  [{i}] {os.path.basename(chemin)}")
    print(f"  [{len(sons) + 1}] " + t("voip_announce_other"))
    print("  [0] " + t("voip_announce_none"))
    choix = input("  > ").strip()
    if choix == "0" or not choix:
        return None
    if choix.isdigit() and 1 <= int(choix) <= len(sons):
        return sons[int(choix) - 1]
    chemin = input("  " + t("voip_announce") + " : ").strip()
    if chemin and not os.path.isfile(chemin):
        print("  " + t("voip_announce_missing"))
        return None
    return chemin or None


def _appel_voip(todo):
    if not sipgo_mod.installe():
        print("  " + t("voip_not_installed"))
        return
    # Le transport MODEM n'a besoin d'aucun trunk : il passe par la carte
    # SIM. On vérifie donc la carte son, pas la configuration SIP.
    voix_ok, motif = calls_mod.voix_disponible()
    if not voix_ok:
        print("  ⚠  " + motif)
        if not click.confirm("  " + t("modem_continue"), default=False):
            return

    brut = input("  " + t("modem_number") + " : ").strip()
    norm = calls_mod.numero_valide(brut)
    if not norm:
        print("  " + t("modem_number_invalid"))
        return

    annonce = _choisir_annonce()
    combine = click.confirm("  " + t("voip_handset_ask"), default=False)
    micro = False
    if combine:
        # L'écho n'est pas traité : le dire AVANT, pas quand le correspondant
        # s'entend revenir et croit à une panne.
        print("  ⚠  " + t("voip_handset_echo"))
        micro = click.confirm("  " + t("voip_mic_ask"), default=False)

    args = sipgo_mod.commande_appel(norm, annonce, combine, micro=micro)
    # On MONTRE la commande avant de la lancer : c'est le dernier moment où
    # l'on peut se raviser, et l'appel part vers une personne réelle.
    print()
    # shlex.join et non " ".join : « sg » reçoit la commande entière dans un
    # seul argument -c, qu'un shell redécouperait sans les guillemets.
    ligne = shlex.join(args)
    print("  " + t("Will execute:") + " " + ligne)
    if not click.confirm(
        f"  {t('modem_call_confirm')} +{norm} ?", default=False
    ):
        return

    if combine:
        # En mode combiné l'appel dure : il faut la sortie en direct et
        # pouvoir raccrocher par Ctrl-C. Capturer la sortie la retiendrait
        # jusqu'à la fin, donc jusqu'à ce qu'on ait déjà raccroché.
        print("  " + t("voip_handset_hint"))
        _lancer_interruptible(args)
        return

    code, sortie, journal = sipgo_mod.appeler(norm, annonce)
    if journal.strip():
        for ligne in journal.strip().splitlines()[-8:]:
            print("    " + ligne)
    print()
    for ligne in (sortie or "").strip().splitlines():
        print("  " + ligne)
    print("  " + (t("voip_call_ok") if code == 0 else t("voip_call_fail")))


def _etat_regle_audio():
    return (
        t("modem_audio_set") if audio_mod.posee() else t("modem_audio_unset")
    )


def _essai_combine():
    """Ouvre le combine sans appeler, pour verifier micro et touches."""
    if not sipgo_mod.installe():
        print("  " + t("voip_not_installed"))
        return
    voix_ok, motif = calls_mod.voix_disponible()
    if not voix_ok:
        print("  ⚠  " + motif)
        if not click.confirm("  " + t("modem_continue"), default=False):
            return
    print("  " + t("modem_audio_try_intro"))
    print()
    micro = click.confirm("  " + t("voip_mic_ask"), default=False)
    print("  " + t("voip_handset_hint"))
    _lancer_interruptible(sipgo_mod.commande_essai_audio(micro))


def _regle_audio():
    """Pose ou retire la regle qui laisse la carte du modem au modem.

    Un interrupteur, donc l'etat AVANT la question et la consequence DANS la
    question : une entree qui affiche « regle posee » puis demande « retirer
    ? » se lit comme une confirmation de ce qui vient d'etre affiche, et se
    bascule par megarde.
    """
    posee = audio_mod.posee()
    print(
        "  "
        + t("modem_audio_state")
        + " : "
        + (t("modem_audio_set") if posee else t("modem_audio_unset"))
    )
    idx, _nom = calls_mod.carte_son()
    if idx is not None:
        libre, motif = audio_mod.carte_libre(f"hw:{idx},0")
        print("  " + ("✔ " if libre else "✖ ") + motif)
    print()
    if posee:
        print("  ⚠  " + t("modem_audio_rule_ask_off_warn"))
        question = t("modem_audio_rule_ask_off")
    else:
        question = t("modem_audio_rule_ask_on")
    # Defaut a « non » dans les deux sens : ni poser ni retirer ne doit
    # arriver par une frappe distraite.
    if not click.confirm("  " + question, default=False):
        print("  " + t("modem_audio_unchanged"))
        return
    ok, message = audio_mod.retirer() if posee else audio_mod.poser()
    print("  " + ("✔ " if ok else "✖ ") + message)


def _sonder_audio():
    """Mesure le chemin audio d'un mode PCM, dans les deux sens.

    Les deux sens ne se constatent pas pareil. La DESCENTE se mesure : ce que
    la carte capture est ce que le modem recoit du reseau. La MONTEE ne se
    mesure pas depuis cette machine, seule l'oreille au bout du fil en
    temoigne — d'ou l'annonce jouee et la question posee apres coup.
    """
    if not sipgo_mod.installe():
        print("  " + t("voip_not_installed"))
        return
    print("  " + t("modem_probe_intro"))
    print()
    brut = input("  " + t("modem_number") + " : ").strip()
    norm = calls_mod.numero_valide(brut)
    if not norm:
        print("  " + t("modem_number_invalid"))
        return

    courant = sipgo_mod.mode_pcm()
    saisi = input("  " + t("modem_probe_mode") % courant + " : ").strip()
    mode = int(saisi) if saisi.isdigit() and 0 <= int(saisi) <= 2 else courant
    annonce = _choisir_annonce()

    args = sipgo_mod.commande_sonde(norm, mode, annonce)
    print()
    print("  " + t("Will execute:") + " " + shlex.join(args))
    if not click.confirm(
        f"  {t('modem_call_confirm')} +{norm} ?", default=False
    ):
        return

    code, sortie, journal = sipgo_mod.sonder(norm, mode, annonce)
    for ligne in (journal or "").strip().splitlines()[-12:]:
        print("    " + ligne)
    print()
    try:
        res = json.loads(sortie or "{}")
    except json.JSONDecodeError:
        print("  " + (sortie or "").strip())
        return
    if not res.get("decroche"):
        print("  " + t("voip_call_fail") + " : " + (res.get("erreur") or ""))
        return
    if not res.get("voix_usb_ouverte"):
        # Sans le pont, la mesure ne dit rien du mode : elle dit seulement
        # qu'on n'a pas reussi a le poser.
        print("  " + t("modem_probe_no_bridge") % mode)
        return

    mesures = res.get("sonde_audio") or []
    descente = mesures[0] if mesures else {}
    if descente.get("erreur"):
        print(f"    ✖ {t('modem_probe_down')} : {descente['erreur']}")
    else:
        marque = "✔" if descente.get("vivant") else "·"
        print(
            f"    {marque} {t('modem_probe_down')} : rms"
            f" {descente.get('rms', 0):.1f}"
        )

    # La montee ne se mesure pas ici : on la demande.
    if annonce:
        montee = click.confirm("  " + t("modem_probe_heard"), default=False)
    else:
        montee = False
    if descente.get("vivant") or montee:
        sipgo_mod.poser_mode_pcm(mode)
        print()
        print("  " + t("modem_probe_result") % mode)
        return
    print()
    print("  " + t("modem_probe_none_mode") % mode)


def _basculer_uac():
    """Active ou éteint la carte son USB du modem.

    C'est une ÉCRITURE dans la configuration du modem, suivie d'un
    redémarrage : il quitte le bus USB et y revient. On demande donc une
    confirmation qui dit ce qui va se passer, et on annonce la coupure de la
    connexion de données — le modem est peut-être la seule liaison réseau de
    la machine.
    """
    params = diag_mod.lire_usbcfg()
    if not params:
        print("  " + t("modem_uac_unreadable"))
        return
    if len(params) < 7:
        print("  " + t("modem_uac_absent") % len(params))
        return
    actif = diag_mod.uac_actif(params)
    print(
        "  "
        + t("modem_uac_state")
        + " : "
        + (t("modem_uac_on") if actif else t("modem_uac_off"))
    )
    print("  " + t("modem_uac_warn"))
    cible = not actif
    question = t("modem_uac_enable") if cible else t("modem_uac_disable")
    if not click.confirm("  " + question, default=False):
        return
    ok, message = diag_mod.activer_uac(cible)
    print("  " + ("✔ " if ok else "✖ ") + message)
    if ok and cible:
        print("  " + t("modem_uac_next"))


def _regle_udev():
    """Pose ou retire la règle qui réserve un port AT.

    Sans elle, chaque commande AT exige d'arrêter ModemManager — ce qui coupe
    la connexion de données et demande sudo à chaque fois. Tenable pour un
    diagnostic ponctuel, intenable pour un service qui appelle.
    """
    print("  " + t("modem_udev_file") + " : " + udev_mod.CIBLE)
    if not udev_mod.posee():
        etat = t("modem_udev_absent")
    elif udev_mod.a_jour():
        etat = t("modem_udev_ok")
    else:
        # Une règle posée il y a des mois peut différer de celle du dépôt, et
        # un écart silencieux est pire qu'une absence.
        etat = t("modem_udev_stale")
    print("  " + t("modem_udev_state") + " : " + etat)
    port = udev_mod.port_reserve()
    print(
        "  "
        + t("modem_at_port")
        + " : "
        + (os.path.basename(port) if port else t("modem_port_shared"))
    )
    # Une regle posee n'est pas une preuve : on OUVRE le port pour le savoir.
    libre, motif = udev_mod.port_libre()
    print(
        "  "
        + t("modem_port_open")
        + " : "
        + (("✔ " if libre else "✖ ") + motif)
    )
    print()
    print("  [1] " + t("modem_udev_install"))
    print("  [2] " + t("modem_udev_remove"))
    print("  [0] " + t("Back"))
    choix = input("  > ").strip()
    if choix == "1":
        ok, message = udev_mod.poser()
        print("  " + ("✔ " if ok else "✖ ") + message.strip()[:300])
    elif choix == "2":
        ok, message = udev_mod.retirer()
        print(
            "  "
            + ("✔ " if ok else "✖ ")
            + (message.strip()[:200] or t("modem_udev_removed"))
        )
