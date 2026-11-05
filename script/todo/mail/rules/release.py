#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les deux gestes de l'utilisateur qui lèvent une décision du moteur.

- Relâcher une entrée retenue (`release_held`) : une réponse automatique
  retenue ne revendique pas son message ; c'est son relâchement qui le
  revendique sur le serveur, depuis n'importe quelle machine qui la
  retient, avant de l'envoyer. Un message déjà revendiqué ailleurs fait
  retirer l'entrée ; une revendication incertaine, un message introuvable
  ou une boîte renumérotée demandent une confirmation ; hors ligne, le
  relâchement est refusé et l'entrée reste retenue.
- Libérer à la main un message dont la revendication n'a pas pu être
  établie (`release_claim`) : la ligne du journal passe
  `skipped/released`, et la passe suivante en ligne réévalue le message.

Les deux tiennent le verrou du compte, celui de la passe : aucune passe
ne croise le geste, aucune règle ne change pendant ses contrôles, et
l'intention de revendication qu'il relit n'est jamais celle d'une passe
vivante de cette machine. Aucun ne lève pour un refus attendu : le texte
rendu dit pourquoi. Une panne du cache traverse.
"""

from __future__ import annotations

import contextlib
import logging
import time
from dataclasses import dataclass

from script.todo.mail.rules import engine, storage
from script.todo.mail.rules.lock import file_lock
from script.todo.mail.rules.model import RuleError
from script.todo.mail.store import OUTBOX_AUTO_KINDS, RELEASE_SEND_MARGIN_S
from script.todo.todo_i18n import t

_logger = logging.getLogger(__name__)

# Attente du verrou du compte, en secondes, pour un geste de libération :
# celle des écrans de règles.
RELEASE_LOCK_WAIT_S = storage.UI_LOCK_WAIT_S
# Les verdicts d'une revendication au relâchement qui demandent une
# confirmation avant d'envoyer sans revendication établie.
CONFIRM_VERDICTS = ("uncertain", "gone", "renumbered")


@dataclass(frozen=True)
class HeldRelease:
    """L'issue d'un relâchement.

    `status` : `released` (relâchée, envoi tenté ; `text` dit ce qu'il en
    est), `dropped` (entrée retirée sans envoi : message déjà revendiqué
    ailleurs, ou entrée qui ne pouvait plus partir — échéance, règle
    modifiée ou désactivée, déjà partie), `gone` (l'entrée n'était plus en
    file ; `text` dit ce qu'il en est advenu), `confirm` (rien n'a
    changé ; `question` est à poser, puis le relâchement à rappeler avec
    `force=verdict`) ou `refused` (rien n'a changé ; `text` dit
    pourquoi)."""

    status: str
    text: str = ""
    question: str = ""
    verdict: str = ""


def _origin_to_claim(store, entree) -> tuple[int, int] | None:
    """L'origine du message à revendiquer pour une entrée retenue : None
    pour une entrée manuelle, un nouvel essai (son départ a déjà été
    revendiqué), une entrée sans règle, ou une ligne sans origine (écrite
    avant que le journal ne la porte, et revendiquée à la décision)."""
    if (
        entree.get("kind") not in OUTBOX_AUTO_KINDS
        or entree.get("retry")
        or not entree.get("rule_id")
    ):
        return None
    return store.rule_log_origin(entree["rule_id"], entree.get("source_key"))


def release_held(
    session,
    queue_id: int,
    *,
    verrou=None,
    force: str | None = None,
    entree=None,
    rules_base=None,
    send_fn=None,
    connect_fn=None,
    now=None,
    lock_wait: float = RELEASE_LOCK_WAIT_S,
) -> HeldRelease:
    """Relâche l'entrée retenue `queue_id` : revendique d'abord son message
    sur le serveur, sous le verrou du compte, puis lève la retenue et
    l'envoie (`tui.send_released`), verrou du compte rendu.

    `entree` est la lecture de l'entrée faite par l'appelant, qui dit ce
    qu'il est advenu d'une entrée sortie de la file entre-temps. `force`
    est le verdict que l'utilisateur a confirmé (`uncertain`, `gone`,
    `renumbered`) : la revendication est refaite, et seul ce même verdict
    envoie ; un autre verdict à confirmer repose sa propre question. `now`
    est l'horloge des contrôles de départ et de la vidange.

    L'ordre revendication, levée de la retenue, envoi porte la reprise
    après un plantage : retenue et revendiquée, l'entrée part au
    relâchement suivant sans échange ; relâchée, à la vidange suivante.
    Une entrée sans revendication à faire (manuelle, nouvel essai, ligne
    sans origine, cache sans règles) se relâche sans verrou ni échange.
    Peut attendre `verrou` : fil de travail seulement.
    """
    from script.todo.mail.tui import _released_gone_text, send_released

    store = session.store

    def envoyer(e):
        return send_released(
            session,
            queue_id,
            verrou=verrou,
            send_fn=send_fn,
            connect_fn=connect_fn,
            entree=e,
            now=now,
        )

    actuelle = store.queued_entry(queue_id)
    if actuelle is None:
        return HeldRelease("gone", _released_gone_text(store, entree))
    if not actuelle["held"]:
        return HeldRelease("released", envoyer(actuelle))
    base = rules_base if rules_base is not None else storage.base_of(store)
    origine = _origin_to_claim(store, actuelle) if base is not None else None
    if origine is None:
        store.set_held(queue_id, False)
        return HeldRelease("released", envoyer(actuelle))

    nom = session.account.name
    with file_lock(storage.lock_path(nom, base), wait=lock_wait) as tenu:
        if not tenu:
            return HeldRelease("refused", t("mail_rules_busy"))
        ancienne, actuelle = actuelle, store.queued_entry(queue_id)
        if actuelle is None:
            return HeldRelease(
                "gone", _released_gone_text(store, entree or ancienne)
            )
        if actuelle["held"]:
            issue = _release_locked(
                session, actuelle, origine, base, force, verrou, now
            )
            if issue is not None:
                return issue
    return HeldRelease("released", envoyer(actuelle))


def _release_locked(
    session, entree, origine, base, force, verrou, now
) -> HeldRelease | None:
    """Sous le verrou du compte : contrôles de départ, revendication, puis
    levée de la retenue. Rend l'issue d'un relâchement qui n'envoie pas,
    ou None quand l'entrée est relâchée et doit partir."""
    from script.todo.mail.tui import (
        _auto_closure,
        _close_auto_entry,
        _flush_rules,
        _released_gone_text,
    )

    store, nom = session.store, session.account.name
    queue_id = entree["id"]
    horloge = now or time.time
    regles, lisibles = _flush_rules(session, base)
    if not lisibles:
        return HeldRelease("refused", t("mail_outbox_release_no_rules"))
    instant = int(horloge())
    fermeture = _auto_closure(store, entree, regles, instant)
    if fermeture is not None:
        # L'entrée ne partirait pas : revendiquer poserait le mot-clé sans
        # réponse, et l'autre machine retirerait la sienne.
        if not store.outbox_claim(queue_id, instant):
            return HeldRelease("refused", t("mail_outbox_release_busy"))
        _close_auto_entry(store, entree, fermeture, nom)
        _logger.info(
            "règles %s : file %s close au relâchement, %s",
            nom,
            queue_id,
            fermeture,
        )
        return HeldRelease("dropped", _released_gone_text(store, entree))

    verdict = _release_claim(session, store, origine, verrou, nom, base)
    _logger.info(
        "règles %s : file %s, revendication au relâchement, %s",
        nom,
        queue_id,
        verdict,
    )
    if verdict == "claimed_elsewhere":
        if store.outbox_drop_claimed(
            queue_id, entree["rule_id"], entree["source_key"]
        ):
            return HeldRelease(
                "dropped", t("mail_outbox_release_claimed_elsewhere")
            )
        return HeldRelease("refused", t("mail_outbox_release_busy"))
    if verdict == "failed":
        return HeldRelease("refused", t("mail_outbox_release_claim_failed"))
    if verdict == "offline":
        return HeldRelease("refused", t("mail_outbox_release_needs_server"))
    if verdict in CONFIRM_VERDICTS:
        if force != verdict:
            return HeldRelease(
                "confirm",
                question=t("mail_outbox_release_confirm_" + verdict),
                verdict=verdict,
            )
        if verdict == "uncertain":
            store.rule_claim_affirm(origine[0], origine[1], "owned")
        _logger.info(
            "règles %s : file %s relâchée sans revendication établie (%s)",
            nom,
            queue_id,
            verdict,
        )
    store.outbox_unhold_claimed(
        queue_id, expires_floor=int(horloge()) + RELEASE_SEND_MARGIN_S
    )
    return None


def _release_claim(session, store, origine, verrou, nom, base) -> str:
    """La revendication du message d'une entrée retenue, sous le verrou du
    compte : `owned`, `unclaimed`, `claimed_elsewhere`, `uncertain`,
    `gone`, `renumbered`, `failed` ou `offline`.

    L'état local d'abord, sans réseau : un message déjà réglé sur cette
    machine (revendiqué, libéré à la main, serveur sans revendication,
    revendiqué ailleurs) n'a pas besoin du serveur. Hors ligne, seul un
    serveur connu sans revendication relâche comme avant. En ligne, sonde
    puis STORE (`engine.claim_exchange`) sous `verrou`, et le mode du
    serveur est inscrit dans l'état du moteur comme par une passe. Aucun
    échec n'est compté : ce compte est celui des passes.
    """
    uidv, uid = origine
    local = store.rule_claim_state(uidv, uid)
    if local in ("owned", "released"):
        return "owned"
    if local == "unclaimed":
        return "unclaimed"
    if local == "lost":
        return "claimed_elsewhere"
    if not session.online:
        if storage.load_claim_mode(nom, base) == "none":
            return "unclaimed"
        return "offline"
    inbox = engine.find_inbox(store)
    etat = store.folder_state(inbox) if inbox else None
    if not etat or not etat.get("uidvalidity"):
        return "gone"
    if etat["uidvalidity"] != uidv:
        return "renumbered"
    garde = verrou if verrou is not None else contextlib.nullcontext()
    try:
        with garde:
            res = session.avec_lien(
                lambda transport: engine.claim_exchange(
                    transport, store, inbox, uidv, uid
                )
            )
    except engine._STORE_FAILURES:
        raise
    except Exception as exc:
        _logger.error(
            "règles %s : revendication UID %s au relâchement en échec (%s)",
            nom,
            uid,
            type(exc).__name__,
        )
        return "failed"
    if res is None:
        return "offline"
    issue, mode = res
    _logger.info(
        "règles %s : revendication UID %s au relâchement, %s, mode %s",
        nom,
        uid,
        issue,
        mode or "-",
    )
    if issue == "renumbered":
        return "renumbered"
    _note_claim_mode(
        nom,
        base,
        mode,
        impose=issue in ("stored", "refused") or mode == "none",
    )
    if issue == "stored":
        return "owned"
    if issue == "present":
        store.rule_claim_set(uidv, uid, "lost", mode=mode)
        return "claimed_elsewhere"
    if issue == "uncertain":
        return "uncertain"
    if issue == "gone":
        store.rule_claim_drop_intent(uidv, uid)
        return "gone"
    if issue == "refused":
        store.rule_claim_set(uidv, uid, "unclaimed", mode="none")
        return "unclaimed"
    if issue in ("unsupported", "silent"):
        return "unclaimed"
    return "failed"


def _note_claim_mode(nom, base, mode: str, *, impose: bool) -> None:
    """Inscrit dans `state.json` le mode de revendication lu au
    relâchement, avec la règle de la passe (`engine.claim_mode_after`),
    verrou du compte tenu par l'appelant. Sans cela, un compte dont toutes
    les réponses sont retenues ne l'apprendrait jamais. Un état illisible
    n'est pas réécrit."""
    try:
        etat = storage.load_state(nom, base)
    except RuleError:
        _logger.error("règles %s : état illisible, mode non inscrit", nom)
        return
    nouveau = engine.claim_mode_after(etat.claim_mode, mode, impose=impose)
    if nouveau == etat.claim_mode:
        return
    etat.claim_mode = nouveau
    storage.save_state(nom, etat, base=base, lock_held=True)


def _inbox_state(store) -> dict | None:
    """INBOX en cache et son UIDVALIDITY, aux noms de
    `store.rule_log_release` ; None sans INBOX ou sans UIDVALIDITY."""
    inbox = engine.find_inbox(store)
    etat = store.folder_state(inbox) if inbox else None
    if not etat or not etat.get("uidvalidity"):
        return None
    return {
        "inbox_folder_id": etat["id"],
        "inbox_uidvalidity": etat["uidvalidity"],
    }


def release_claim_refusal(store, rule_id: str, msg_key: str) -> str | None:
    """Le texte du refus que `release_claim` opposerait à la ligne
    (`rule_id`, `msg_key`), None quand elle la libérerait. Lu sans verrou
    ni écriture, avant la question de risque : un geste voué au refus ne
    demande pas d'accepter un double envoi. `release_claim` refait les
    mêmes contrôles sous le verrou du compte."""
    inbox = _inbox_state(store)
    if inbox is None:
        return t("mail_rules_release_no_inbox")
    refus = store.rule_log_release_check(rule_id, msg_key, **inbox)
    return None if refus is None else t(f"mail_rules_release_{refus}")


def release_claim(
    store,
    account_name: str,
    rule_id: str,
    msg_key: str,
    *,
    rules_base=None,
    lock_wait: float = RELEASE_LOCK_WAIT_S,
) -> tuple[bool, str]:
    """Libère à la main le message de la ligne (`rule_id`, `msg_key`) dont
    la revendication est incertaine ou en échec ; rend `(libéré, texte)`.

    La confirmation, qui dit le risque de double envoi, est à la charge de
    l'appelant, avant l'appel. Rien n'est échangé avec le serveur : le
    message est réévalué à la prochaine passe en ligne. Refus, sans rien
    écrire : cache sans règles, verrou du compte tenu, INBOX absente du
    cache, et les refus de `store.rule_log_release`.
    """
    base = rules_base if rules_base is not None else storage.base_of(store)
    if base is None:
        return False, t("mail_rules_ephemeral")
    with file_lock(
        storage.lock_path(account_name, base), wait=lock_wait
    ) as tenu:
        if not tenu:
            return False, t("mail_rules_busy")
        inbox = _inbox_state(store)
        if inbox is None:
            return False, t("mail_rules_release_no_inbox")
        res = store.rule_log_release(rule_id, msg_key, **inbox)
    _logger.info(
        "règles %s : règle %s, message libéré à la main (%s)",
        account_name,
        rule_id,
        res,
    )
    if res == "released":
        return True, t("mail_rules_release_done")
    return False, t(f"mail_rules_release_{res}")
