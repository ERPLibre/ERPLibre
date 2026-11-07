#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le bac à sable IMAP et SMTP de `mail_sandbox.py`, servi à un autre
processus et piloté par des lignes JSON.

Un processus qui ne peut pas importer `twisted` ni `aiosmtpd` — celui d'Odoo,
par exemple — lance ce script sous le Python de `.venv.erplibre` :

    .venv.erplibre/bin/python -B test/mail_sandbox_serve.py [--condstore]
        [--nomodseq] [--no-keywords] [--smtp-auth]

Le script démarre un `ImapSandbox` (boîte `INBOX`, UIDVALIDITY 42) et un
`SmtpSandbox` sur des ports éphémères de 127.0.0.1, écrit UNE ligne JSON
`{"imap_port", "smtp_port", "user", "password"}`, puis répond à une requête
JSON par ligne de l'entrée standard par une réponse JSON d'une ligne :
`{"ok": true, "result": …}` ou `{"ok": false, "error": "<Type>: <texte>"}`.
Une requête illisible ou d'opération inconnue reçoit `ok: false` et le
serveur continue. La fin de l'entrée standard, ou l'opération `stop`, arrête
les deux serveurs, et le script sort avec le code 0 : un parent tué ne
laisse pas de serveur orphelin.

Twisted ne pose pas `\\Seen` sur un `FETCH BODY[]` sans `.PEEK` : un
client qui oublie `PEEK` ne se voit donc pas aux drapeaux. Le script note,
dans SON processus seulement, chaque section `BODY…` servie, laquelle, et
si elle était demandée en `PEEK` (opération `fetches`) ; `mail_sandbox.py`
reste tel quel pour les tests qui l'importent.

Les refus au `RCPT TO` de `mail_sandbox.py` se posent par `rcpt_refuse`
(réponse complète, 4xx ou 5xx, par adresse), et `rcpt_attempts` rend chaque
adresse proposée au `RCPT TO`, acceptée ou refusée, dans l'ordre. Trois
refus que `mail_sandbox.py` ne sait pas produire s'ajoutent, dans ce
processus seulement : NO à tout `UID FETCH` dont l'ensemble contient un UID
donné (`fetch_refuse`), réponse imposée aux prochains `MAIL FROM`, suivie au
besoin de la fermeture de la connexion (`mail_refuse`), et réponse imposée
après les données de `DATA`, le message n'étant alors pas gardé
(`data_refuse`).

D'autres dossiers qu'`INBOX` se créent par `folder` (nom IMAP brut, en
UTF-7 modifié, attributs annoncés au LIST comme `\\Sent`, UIDVALIDITY et
premier UID ; pour un dossier qui existe déjà, des attributs donnés
remplacent les siens) ; `deliver`, `flags`, `mark` et `renumber` prennent
alors `folder`.
`fail` prend `times` : la panne ne frappe que ce nombre de fois. `selects`
rend chaque `SELECT` et `EXAMINE` reçu, dans l'ordre, avec le
dossier et vrai pour une sélection en écriture ; chaque partie de `fetches`
nomme le dossier sélectionné de la connexion qui l'a servie (« » sans
dossier).
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

ICI = Path(__file__).resolve().parent
# `mail_sandbox` s'importe par son dossier ; il importe à son tour
# `script.todo.mail`, que porte la racine du dépôt.
for chemin in (str(ICI.parent), str(ICI)):
    if chemin not in sys.path:
        sys.path.insert(0, chemin)

import mail_sandbox as sandbox  # noqa: E402

UIDVALIDITY = 42
INBOX = "INBOX"
# Les mois de l'INTERNALDATE, en anglais quelle que soit la locale :
# `strftime("%b")` suivrait celle du processus.
MOIS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def internal_date_now(now: float | None = None) -> str:
    """L'INTERNALDATE IMAP de `now` (maintenant par défaut), en UTC."""
    t = time.gmtime(time.time() if now is None else now)
    return (
        f"{t.tm_mday:02d}-{MOIS[t.tm_mon - 1]}-{t.tm_year:04d}"
        f" {t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d} +0000"
    )


def uid_set_hits(jeu: bytes, uids: set[int]) -> bool:
    """Vrai si l'ensemble d'UID IMAP `jeu` (`3`, `1,4`, `2:7`, `5:*`)
    contient l'un des `uids` ; `*` vaut l'infini. Un morceau illisible ne
    contient rien."""
    for morceau in jeu.split(b","):
        bas, _sep, haut = morceau.partition(b":")
        try:
            debut = float("inf") if bas == b"*" else int(bas)
            fin = (
                debut
                if not _sep
                else (float("inf") if haut == b"*" else int(haut))
            )
        except ValueError:
            continue
        debut, fin = min(debut, fin), max(debut, fin)
        if any(debut <= uid <= fin for uid in uids):
            return True
    return False


class Served:
    """Les deux serveurs, la boîte et le relevé des sections servies.

    Chaque action sur la boîte passe par le fil du réacteur
    (`blockingCallFromThread`) : c'est là que le serveur IMAP la lit.
    """

    def __init__(
        self,
        *,
        condstore: bool = False,
        nomodseq: bool = False,
        keywords: bool = True,
        smtp_auth: bool = False,
    ) -> None:
        self.imap = sandbox.ImapSandbox(condstore=condstore, nomodseq=nomodseq)
        self.inbox = self.imap.folder(INBOX, uidvalidity=UIDVALIDITY)
        self.inbox.keywords = keywords
        self.smtp = sandbox.SmtpSandbox(require_auth=smtp_auth)
        self.fetched: list[dict] = []
        self.selected: list[dict] = []
        self.fetch_refusals: set[int] = set()
        self.mail_refusal = {"reply": "", "close": False, "times": 0}
        self.data_reply = ""
        self._installe_releve()
        self._installe_selections()
        self._installe_refus_fetch()
        self._installe_refus_smtp()

    def _installe_releve(self) -> None:
        """Enveloppe `spew_body` du serveur pour noter `(uid, peek,
        section)` de chaque section servie, puis la servir comme avant.

        `section` vaut `header` (`HEADER`, `HEADER.FIELDS`…), `text`,
        `mime`, `full` (le message entier, `BODY[]`) ou `structure` (une
        partie numérotée) : Twisted passe ici pour toute section, en-têtes
        compris, et seul `full` dit qu'un message complet est parti."""
        servi = self.fetched
        origine = sandbox.SandboxIMAP4Server.spew_body

        def section(part) -> str:
            if getattr(part, "header", None):
                return "header"
            if getattr(part, "text", None):
                return "text"
            if getattr(part, "mime", None):
                return "mime"
            if getattr(part, "empty", False):
                return "full"
            return "structure"

        def spew_body(server, part, id, msg, _w=None, _f=None):
            boite = getattr(server, "mbox", None)
            servi.append(
                {
                    "uid": int(msg.getUID()),
                    "peek": bool(getattr(part, "peek", False)),
                    "section": section(part),
                    "folder": getattr(boite, "name", "") or "",
                }
            )
            return origine(server, part, id, msg, _w, _f)

        sandbox.SandboxIMAP4Server.spew_body = spew_body

    def _installe_selections(self) -> None:
        """Enveloppe `select` du compte IMAP de CETTE instance pour noter
        chaque `SELECT` (`rw` vrai) et `EXAMINE` (`rw` faux) : Twisted y
        passe pour les deux, avec le nom déjà décodé."""
        compte = self.imap.account
        notes = self.selected
        origine = compte.select

        def select(path, rw=True):
            notes.append({"folder": str(path), "rw": bool(rw)})
            return origine(path, rw)

        compte.select = select

    def _installe_refus_fetch(self) -> None:
        """Enveloppe `dispatchCommand` du serveur : un `UID FETCH` dont
        l'ensemble contient un UID de `fetch_refusals` reçoit NO, sans rien
        servir. Twisted y passe deux fois pour `UID FETCH` ; seul le passage
        interne (`FETCH`, `uid` vrai) est visé."""
        refus = self.fetch_refusals
        origine = sandbox.SandboxIMAP4Server.dispatchCommand

        def dispatchCommand(server, tag, cmd, rest, uid=None):
            if (
                refus
                and uid
                and cmd.upper() == b"FETCH"
                and uid_set_hits(rest.split(b" ", 1)[0], refus)
            ):
                server.sendNegativeResponse(
                    tag, b"Some messages could not be FETCHed"
                )
                return None
            return origine(server, tag, cmd, rest, uid)

        sandbox.SandboxIMAP4Server.dispatchCommand = dispatchCommand

    def _installe_refus_smtp(self) -> None:
        """Pose sur le gestionnaire SMTP les crochets `MAIL` et `DATA`.

        `aiosmtpd` relit les crochets du gestionnaire à chaque connexion :
        ils sont posés avant la première. Sans refus demandé, ils font ce
        que fait `aiosmtpd` sans crochet `MAIL`, et ce que fait le
        gestionnaire du bac à sable pour `DATA`.
        """
        handler = self.smtp.handler
        refus = self.mail_refusal
        served = self
        data_origine = handler.handle_DATA

        async def handle_MAIL(server, session, envelope, address, options):
            if refus["times"] > 0:
                refus["times"] -= 1
                if refus["close"]:
                    import asyncio

                    # Après l'écriture de la réponse, qui ne cède pas la
                    # main avant d'avoir écrit.
                    asyncio.get_running_loop().call_soon(
                        server.transport.close
                    )
                return refus["reply"]
            envelope.mail_from = address
            envelope.mail_options.extend(options)
            return "250 OK"

        async def handle_DATA(server, session, envelope):
            if served.data_reply:
                return served.data_reply
            return await data_origine(server, session, envelope)

        handler.handle_MAIL = handle_MAIL
        handler.handle_DATA = handle_DATA

    def start(self) -> dict:
        self.imap.start()
        self.smtp.start()
        return {
            "imap_port": self.imap.port,
            "smtp_port": self.smtp.port,
            "user": sandbox.USER,
            "password": sandbox.PASSWORD,
        }

    def stop(self) -> None:
        for serveur in (self.imap, self.smtp):
            try:
                serveur.stop()
            except Exception as exc:
                # L'arrêt de l'un ne doit pas empêcher celui de l'autre.
                print(f"stop: {type(exc).__name__}: {exc}", file=sys.stderr)

    def _reactor(self, fonction, *args, **kwargs):
        from twisted.internet.threads import blockingCallFromThread

        return blockingCallFromThread(
            sandbox.reactor_in_thread(), fonction, *args, **kwargs
        )

    @staticmethod
    def _decoded(name: str) -> str:
        """Le nom décodé d'un nom IMAP brut en UTF-7 modifié : celui sous
        lequel le compte range le dossier, et que LIST réencode."""
        return str(name).encode("ascii").decode("imap4-utf-7")

    def _box(self, folder: str = INBOX):
        """Le dossier de nom IMAP brut `folder` ; `KeyError` s'il
        n'existe pas."""
        compte = self.imap.account
        boite = compte.boxes.get(compte._key(self._decoded(folder)))
        if boite is None:
            raise KeyError(f"folder {folder}")
        return boite

    def _message(self, uid: int, folder: str = INBOX):
        message = self._box(folder).by_uid(int(uid))
        if message is None:
            raise KeyError(f"uid {uid}")
        return message

    # -- opérations -----------------------------------------------------

    def op_folder(
        self, name, attributes=(), uidvalidity=UIDVALIDITY, first_uid=1
    ) -> dict:
        nom = self._decoded(name)

        def creer():
            boite = self.imap.folder(
                nom, int(uidvalidity), tuple(attributes), int(first_uid)
            )
            if attributes:
                boite.attributs = tuple(attributes)

        self._reactor(creer)
        return {}

    def op_deliver(self, raw, flags=(), internal_date=None, folder=INBOX):
        octets = base64.b64decode(raw)
        date = (internal_date or internal_date_now()).encode("ascii")
        boite = self._box(folder)
        message = self._reactor(
            boite.deliver, octets, list(flags), internal_date=date
        )
        return {"uid": int(message.uid)}

    def op_flags(self, uid, folder=INBOX) -> dict:
        return {
            "flags": self._reactor(
                lambda: list(self._message(uid, folder).flags)
            )
        }

    def op_mark(self, uid, flags, folder=INBOX) -> dict:
        def marquer():
            message = self._box(folder).marquer_ailleurs(int(uid), *flags)
            return list(message.flags)

        return {"flags": self._reactor(marquer)}

    def op_selects(self) -> dict:
        return {"selects": self._reactor(lambda: list(self.selected))}

    def op_interfere(
        self, command, uid, flags=(), after=0, action="mark"
    ) -> dict:
        if action == "expunge":

            def agir():
                self.inbox.expurger(int(uid))

        elif action == "mark":

            def agir():
                self.inbox.marquer_ailleurs(int(uid), *flags)

        else:
            raise ValueError(f"action {action!r}")
        faute = sandbox.Interfere(
            str(command).encode("ascii"), after=int(after), action=agir
        )
        self._reactor(self.imap.fail, faute)
        return {}

    def op_fail(self, kind, command, after=0, times=0) -> dict:
        classes = {
            "drop": sandbox.DropConnection,
            "refuse": sandbox.RefuseCommand,
        }
        if kind not in classes:
            raise ValueError(f"kind {kind!r}")
        faute = classes[kind](str(command).encode("ascii"), after=int(after))
        if int(times) > 0:
            # La panne ne frappe que `times` fois, puis laisse passer.
            origine = faute.matches

            def matches(cmd, _origine=origine, _faute=faute):
                return _origine(cmd) and _faute.fired <= _faute.after + int(
                    times
                )

            faute.matches = matches
        self._reactor(self.imap.fail, faute)
        return {}

    def op_clear_faults(self) -> dict:
        self._reactor(self.imap.faults.clear)
        return {}

    def op_renumber(self, uidvalidity, folder=INBOX) -> dict:
        def renumeroter():
            self._box(folder).uidvalidity = int(uidvalidity)

        self._reactor(renumeroter)
        return {}

    def op_expunge(self, uid) -> dict:
        self._reactor(self.inbox.expurger, int(uid))
        return {}

    def op_sent(self) -> dict:
        return {
            "messages": [
                {
                    "mail_from": m.mail_from,
                    "rcpt_tos": list(m.rcpt_tos),
                    "data": base64.b64encode(m.content).decode("ascii"),
                }
                for m in list(self.smtp.messages)
            ]
        }

    def op_rcpt_refuse(self, address, reply="") -> dict:
        cle = str(address).lower()
        if reply:
            self.smtp.rcpt_refusals[cle] = str(reply)
        else:
            self.smtp.rcpt_refusals.pop(cle, None)
        return {}

    def op_rcpt_attempts(self) -> dict:
        return {"addresses": list(self.smtp.rcpt_attempts)}

    def op_fetch_refuse(self, uid, refuse=True) -> dict:
        def poser():
            if refuse:
                self.fetch_refusals.add(int(uid))
            else:
                self.fetch_refusals.discard(int(uid))

        self._reactor(poser)
        return {}

    def op_mail_refuse(self, reply="", close=False, times=1) -> dict:
        self.mail_refusal.update(
            {
                "reply": str(reply),
                "close": bool(close),
                "times": int(times) if reply else 0,
            }
        )
        return {}

    def op_data_refuse(self, reply="") -> dict:
        self.data_reply = str(reply)
        return {}

    def op_fetches(self) -> dict:
        return {"parts": self._reactor(lambda: list(self.fetched))}

    def op_stop(self) -> dict:
        return {}

    def handle(self, line: str) -> tuple[dict, bool]:
        """La réponse à une ligne de requête, et vrai si elle demande
        l'arrêt."""
        try:
            requete = json.loads(line)
            if not isinstance(requete, dict):
                raise ValueError("request is not an object")
            op = requete.pop("op", None)
            methode = getattr(self, f"op_{op}", None) if op else None
            if methode is None:
                raise ValueError(f"unknown op {op!r}")
            return {"ok": True, "result": methode(**requete)}, op == "stop"
        except Exception as exc:
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }, False


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--condstore", action="store_true")
    parser.add_argument("--nomodseq", action="store_true")
    parser.add_argument("--no-keywords", action="store_true")
    parser.add_argument("--smtp-auth", action="store_true")
    return parser.parse_args(argv)


def main(argv=None, stdin=None, stdout=None) -> int:
    """Sert jusqu'à la fin de `stdin` ou l'opération `stop` ; rend 0."""
    args = parse_args(argv)
    entree = stdin if stdin is not None else sys.stdin
    sortie = stdout if stdout is not None else sys.stdout
    # Toute écriture parasite d'une bibliothèque va à l'erreur standard :
    # la sortie standard ne porte que le protocole.
    sys.stdout = sys.stderr
    served = Served(
        condstore=args.condstore,
        nomodseq=args.nomodseq,
        keywords=not args.no_keywords,
        smtp_auth=args.smtp_auth,
    )

    def ecrire(objet) -> None:
        sortie.write(json.dumps(objet) + "\n")
        sortie.flush()

    try:
        ecrire(served.start())
        while True:
            line = entree.readline()
            if not line:
                break
            if not line.strip():
                continue
            reponse, fin = served.handle(line)
            ecrire(reponse)
            if fin:
                break
    finally:
        served.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
