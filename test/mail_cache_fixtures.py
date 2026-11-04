#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Aides partagées des tests du mode du cache et de sa conversion.

Hors de la suite (aucun `test_` dans le nom) : `FauxCoffre`, un coffre en
mémoire qui compte ses écritures ; `remplir`, un jeu complet de données ;
`instantane`, le contenu descellé d'un cache, comparable entre deux modes ;
`rendre_v4`, une file ramenée à sa forme d'avant `sealed_error`.

Adresses : uniquement les trois de `example.org` déjà présentes dans le
dépôt.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

COMPTE = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
DENIS = "denis.tri@example.org"


class FauxCoffre:
    """Un coffre `get`/`set`/`update` en mémoire, éventuellement adossé à
    un fichier JSON (pour un sous-processus qui doit relire la même clé).

    `writes` compte les écritures, `gets` les lectures : un refus qui ne
    doit rien tirer ni écrire au coffre se vérifie par eux."""

    def __init__(self, path: Path | None = None, values: dict | None = None):
        self.path = Path(path) if path is not None else None
        self.values = dict(values or {})
        if self.path is not None and self.path.exists():
            self.values.update(json.loads(self.path.read_text()))
        self.writes = 0
        self.gets = 0

    def _save(self) -> None:
        if self.path is not None:
            self.path.write_text(json.dumps(self.values))

    def get(self, ref):
        self.gets += 1
        if self.path is not None and self.path.exists():
            self.values = json.loads(self.path.read_text())
        return self.values.get(ref)

    def set(self, ref, value) -> None:
        self.writes += 1
        self.values[ref] = value
        self._save()

    def delete(self, ref) -> None:
        if self.values.pop(ref, None) is not None:
            self.writes += 1
            self._save()

    def update(self, ref, change):
        current = self.values.get(ref)
        nouveau = change(current)
        if nouveau != current:
            self.writes += 1
            self.values[ref] = nouveau
            self._save()
        return nouveau


def rendre_v4(store) -> None:
    """Ramène la file à sa forme v4 : `sealed_error` retirée, `last_error`
    en clair ajoutée (comme `test_mail_outbox`). Le `Store` reste ouvert."""
    db = store._db()
    db.executescript(
        """
        ALTER TABLE outbox DROP COLUMN sealed_error;
        ALTER TABLE outbox ADD COLUMN last_error TEXT;
        """
    )
    db.execute("UPDATE outbox SET last_error = 'refus'")
    db.commit()


def remplir(store, now: int = 1_790_000_000) -> dict:
    """Un jeu complet dans un `Store` ouvert, rendu en dictionnaire de
    repères.

    INBOX (UIDVALIDITY 7) et Envoyés (UIDVALIDITY 9) ; trois messages : un
    `\\Seen \\Answered`, un sans Message-ID, une réponse d'Envoyés qui cite
    le premier (`In-Reply-To`, `References`) ; deux corps ; une entrée de
    file manuelle et une `auto_forward` de nouvel essai réservée ; deux
    lignes de journal réclamées comme le moteur (préimage, cible), une
    ligne ancienne SANS préimage dont le message est en cache, une ligne
    SANS préimage dont le message n'est pas en cache ; deux `auto_sent` ;
    `cache_epoch()` tirée."""
    from script.todo.mail.store import MessageMeta

    inbox = store.upsert_folder("INBOX", "Boîte", "inbox", uidvalidity=7)
    envoyes = store.upsert_folder("Sent", "Envoyés", "sent", uidvalidity=9)
    m1 = MessageMeta(
        uid=1,
        date=now - 7200,
        size=120,
        flags="\\Seen \\Answered",
        msgid="<question-1@example.org>",
        frm=f"Carole <{CAROLE}>",
        to=COMPTE,
        subject="Question sur la facture",
        snippet="Bonjour, une question sur la facture",
        received_at=now - 7100,
    )
    m2 = MessageMeta(
        uid=2,
        date=now - 3600,
        size=80,
        flags="",
        msgid="",
        frm=DENIS,
        to=COMPTE,
        subject="Sans identifiant",
        snippet="Un message sans Message-ID",
    )
    reponse = MessageMeta(
        uid=5,
        date=now - 3000,
        size=90,
        flags="\\Seen",
        msgid="<reponse-1@example.org>",
        frm=COMPTE,
        to=CAROLE,
        subject="Re: Question sur la facture",
        snippet="Voici la réponse",
        in_reply_to="<question-1@example.org>",
        references="<question-1@example.org> <absent@example.org>",
    )
    store.upsert_messages(inbox, [m1, m2])
    store.upsert_messages(envoyes, [reponse])
    store.write_body("INBOX", 1, b"Corps de la question sur la facture")
    store.write_body("Sent", 5, b"Corps de la reponse")
    manuel = store.queue_message(
        b"From: x\r\nTo: y\r\n\r\nmanuel", DENIS, "Envoi manuel", held=True
    )
    cle1 = store.message_key(m1.msgid, 7, 1)
    cle2 = store.message_key("", 7, 2)
    auto = store.queue_message(
        b"From: x\r\n\r\ntransfert",
        CAROLE,
        "Transfert",
        kind="auto_forward",
        rule_id="regle-a",
        source_key=cle1,
        expires_at=now + 86400,
    )
    store._db().execute(
        "UPDATE outbox SET claimed_at = ?, attempts = 1, retry = 1"
        " WHERE id = ?",
        (now - 10, auto),
    )
    store._db().commit()
    store.rule_log_claim(
        "regle-a",
        cle1,
        outcome="queued",
        at=now - 7000,
        sender_hash=store.address_hash(CAROLE),
        target_hash=store.address_hash(CAROLE),
        fingerprint="empreinte-a",
        sender=CAROLE,
        subject="Question sur la facture",
        queue_id=auto,
        msg_ref=store.message_ref(m1.msgid, 7, 1),
        target=CAROLE,
    )
    store.rule_log_claim(
        "regle-b",
        cle2,
        outcome="sent",
        at=now - 3500,
        sender_hash=store.address_hash(DENIS),
        target_hash=store.address_hash(CAROLE),
        fingerprint="empreinte-b",
        sender=DENIS,
        subject="Sans identifiant",
        msg_ref=store.message_ref("", 7, 2),
        target=CAROLE,
    )
    # Une ligne écrite avant les préimages, dont le message est en cache.
    store.rule_log_claim(
        "regle-c",
        cle1,
        outcome="skipped",
        reason="cap",
        at=now - 6000,
        sender_hash=store.address_hash(CAROLE),
        target_hash=store.address_hash(CAROLE),
        sender=CAROLE,
        subject="Question sur la facture",
    )
    # Une ligne sans préimage dont le message a quitté le cache.
    perdu = store.message_key("<parti@example.org>", 7, 40)
    store.rule_log_claim(
        "regle-a",
        perdu,
        outcome="sent",
        at=now - 1800,
        sender_hash=store.address_hash(DENIS),
        target_hash=store.address_hash(DENIS),
        fingerprint="empreinte-a",
        sender=DENIS,
        subject="Message parti",
    )
    store.mark_auto_sent("<envoi-regle@example.org>", "regle-a", now - 1700)
    store.mark_auto_sent_many([("<auto-tiers@example.org>", "", now - 1600)])
    epoque = store.cache_epoch()
    return {
        "inbox": inbox,
        "envoyes": envoyes,
        "cle1": cle1,
        "cle2": cle2,
        "perdu": perdu,
        "manuel": manuel,
        "auto": auto,
        "epoque": epoque,
        "now": now,
    }


# Les préimages des empreintes : une conversion peut les compléter quand
# elle les retrouve, elles ne font donc pas partie de ce qui doit rester
# identique.
PREIMAGES = {("rule_log", "sealed_msg_ref"), ("auto_sent", "sealed_msgid")}


def _ligne_descellee(store, table: str, row) -> dict:
    from script.todo.mail.store import HASHED_COLUMNS, SEALED_COLUMNS

    scellees = SEALED_COLUMNS.get(table, ())
    empreintes = HASHED_COLUMNS.get(table, ())
    sortie = {}
    for cle in row.keys():
        if cle in empreintes or (table, cle) in PREIMAGES:
            continue
        valeur = row[cle]
        if cle in scellees:
            valeur = (
                None if valeur is None else store._crypto.open(bytes(valeur))
            )
        sortie[cle] = valeur
    return sortie


def instantane(store) -> dict:
    """Toutes les lignes descellées, par table et par `id` (`meta` par
    clé, sans les clés liées au mode et au sel), sans les colonnes
    d'empreinte ni leurs préimages, plus les corps descellés par
    (dossier, uid)."""
    db = store._db()
    sortie = {}
    for table in ("folders", "messages", "outbox", "rule_log"):
        sortie[table] = [
            _ligne_descellee(store, table, row)
            for row in db.execute(f"SELECT * FROM {table} ORDER BY id")
        ]
    sortie["auto_sent"] = sorted(
        (
            _ligne_descellee(store, "auto_sent", row)
            for row in db.execute("SELECT * FROM auto_sent")
        ),
        key=lambda r: (r["at"], r["rule_id"] or ""),
    )
    sortie["meta"] = {
        row[0]: row[1]
        for row in db.execute("SELECT key, value FROM meta")
        if row[0] not in ("cache_mode", "cache_epoch_check")
    }
    corps = {}
    for uid, dossier in db.execute(
        "SELECT m.uid, f.name FROM messages m JOIN folders f"
        " ON f.id = m.folder_id ORDER BY m.id"
    ):
        corps[(dossier, uid)] = store.read_body(dossier, uid)
    sortie["corps"] = corps
    return sortie


def fichiers(racine: Path) -> dict:
    """{chemin relatif: octets} de tout fichier sous `racine`."""
    sortie = {}
    for dossier, _sous, noms in os.walk(racine):
        for nom in noms:
            chemin = Path(dossier) / nom
            if chemin.is_symlink():
                continue
            sortie[str(chemin.relative_to(racine))] = chemin.read_bytes()
    return sortie
