#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le bac à sable servi par `mail_sandbox_serve.py` à un autre processus :
ses ports, son protocole JSON par lignes, et son arrêt à la fin de l'entrée
standard.

Le script tourne dans un processus fils, comme pour les tests d'un module
Odoo qui ne peut pas importer `twisted` ; le test lui parle avec `imaplib`
et `smtplib`, comme un vrai client.
"""

import base64
import imaplib
import json
import smtplib
import subprocess
import sys
import time
import unittest
from pathlib import Path

try:
    import aiosmtpd  # noqa: F401
    import twisted  # noqa: F401

    SANDBOX_MISSING = ""
except ImportError as exc:  # pragma: no cover - dépend de l'installation
    SANDBOX_MISSING = str(exc)

SCRIPT = Path(__file__).resolve().parent / "mail_sandbox_serve.py"
RAW = (
    b"From: carole.regle@example.org\r\n"
    b"To: boite.regles@example.org\r\n"
    b"Subject: Question\r\n"
    b"Message-ID: <q1@example.org>\r\n"
    b"\r\n"
    b"Bonjour\r\n"
)


class _Child:
    """Le script dans un processus fils, et une requête à la fois."""

    def __init__(self, *args: str) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-B", str(SCRIPT), *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self.ports = json.loads(self.proc.stdout.readline())

    def call(self, op: str, **params) -> dict:
        self.proc.stdin.write(json.dumps({"op": op, **params}) + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def raw_line(self, line: str) -> dict:
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc.stdout.close()


@unittest.skipIf(SANDBOX_MISSING, f"bac à sable absent : {SANDBOX_MISSING}")
class TestServe(unittest.TestCase):
    def child(self, *args: str) -> _Child:
        child = _Child(*args)
        self.addCleanup(child.close)
        return child

    def imap(self, child: _Child) -> imaplib.IMAP4:
        client = imaplib.IMAP4("127.0.0.1", child.ports["imap_port"])
        self.addCleanup(client.shutdown)
        client.login(child.ports["user"], child.ports["password"])
        client.select("INBOX")
        return client

    def deliver(self, child: _Child, raw: bytes = RAW) -> int:
        reponse = child.call(
            "deliver", raw=base64.b64encode(raw).decode("ascii")
        )
        self.assertTrue(reponse["ok"], reponse)
        return reponse["result"]["uid"]

    def test_the_first_line_gives_the_ports(self):
        """La première ligne donne deux ports d'écoute et les identifiants
        du bac à sable ; le serveur IMAP y répond."""
        child = self.child()
        self.assertEqual(child.ports["user"], "moi")
        self.assertEqual(child.ports["password"], "secret")
        self.assertNotEqual(child.ports["imap_port"], child.ports["smtp_port"])
        client = self.imap(child)
        self.assertEqual(client.state, "SELECTED")

    def test_deliver_then_flags(self):
        """Un message remis prend l'UID suivant et garde ses drapeaux."""
        child = self.child()
        uid = child.call(
            "deliver",
            raw=base64.b64encode(RAW).decode("ascii"),
            flags=["\\Flagged"],
        )["result"]["uid"]
        self.assertEqual(uid, 1)
        self.assertEqual(self.deliver(child), 2)
        reponse = child.call("flags", uid=1)
        self.assertEqual(
            reponse, {"ok": True, "result": {"flags": ["\\Flagged"]}}
        )

    def test_interfere_marks_before_the_store(self):
        """`interfere` pose le drapeau d'un autre client avant que le
        STORE du test ne soit servi."""
        child = self.child()
        uid = self.deliver(child)
        child.call("interfere", command="STORE", uid=uid, flags=["$Autre"])
        client = self.imap(child)
        typ, _ = client.uid("STORE", str(uid), "+FLAGS", "(\\Flagged)")
        self.assertEqual(typ, "OK")
        flags = child.call("flags", uid=uid)["result"]["flags"]
        self.assertIn("$Autre", flags)
        self.assertIn("\\Flagged", flags)

    def test_sent_returns_the_smtp_messages(self):
        """Ce que reçoit le SMTP revient avec son enveloppe et ses
        octets."""
        child = self.child("--smtp-auth")
        with smtplib.SMTP(
            "127.0.0.1", child.ports["smtp_port"], timeout=10
        ) as smtp:
            smtp.login(child.ports["user"], child.ports["password"])
            smtp.sendmail(
                "boite.regles@example.org", ["carole.regle@example.org"], RAW
            )
        messages = child.call("sent")["result"]["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["mail_from"], "boite.regles@example.org")
        self.assertEqual(messages[0]["rcpt_tos"], ["carole.regle@example.org"])
        self.assertIn(
            b"Subject: Question", base64.b64decode(messages[0]["data"])
        )

    def test_fetches_record_the_peek(self):
        """Chaque section servie est notée avec son `PEEK`."""
        child = self.child()
        uid = self.deliver(child)
        client = self.imap(child)
        client.uid("FETCH", str(uid), "(BODY.PEEK[])")
        client.uid("FETCH", str(uid), "(BODY[])")
        parts = child.call("fetches")["result"]["parts"]
        self.assertEqual(
            parts, [{"uid": uid, "peek": True}, {"uid": uid, "peek": False}]
        )

    def test_a_bad_request_keeps_the_server(self):
        """Une requête illisible ou inconnue est refusée, le serveur
        continue."""
        child = self.child()
        self.assertFalse(child.raw_line("pas du json")["ok"])
        reponse = child.call("inconnue")
        self.assertFalse(reponse["ok"])
        self.assertIn("ValueError", reponse["error"])
        self.assertEqual(self.deliver(child), 1)

    def test_interfere_can_expunge_before_the_fetch(self):
        """`interfere` avec `expunge` retire le message avant que le FETCH
        ne soit servi : la réponse ne porte plus son UID."""
        child = self.child()
        uid = self.deliver(child)
        child.call("interfere", command="FETCH", uid=uid, action="expunge")
        client = self.imap(child)
        typ, data = client.uid("FETCH", str(uid), "(UID FLAGS)")
        self.assertEqual(typ, "OK")
        self.assertFalse(
            [d for d in data if d and b"UID %d" % uid in bytes(d)], data
        )

    def test_fetch_refuse_answers_no_for_a_set_holding_the_uid(self):
        """`fetch_refuse` fait répondre NO à tout `UID FETCH` dont
        l'ensemble contient l'UID, et laisse servir les autres."""
        child = self.child()
        premier = self.deliver(child)
        refuse = self.deliver(child)
        child.call("fetch_refuse", uid=refuse)
        client = self.imap(child)
        for jeu in (str(refuse), f"{premier},{refuse}", f"{premier}:*"):
            typ, _data = client.uid("FETCH", jeu, "(UID FLAGS)")
            self.assertEqual(typ, "NO", jeu)
        typ, _data = client.uid("FETCH", str(premier), "(UID FLAGS)")
        self.assertEqual(typ, "OK")
        child.call("fetch_refuse", uid=refuse, refuse=False)
        typ, _data = client.uid("FETCH", str(refuse), "(UID FLAGS)")
        self.assertEqual(typ, "OK")

    def test_mail_refuse_answers_then_closes(self):
        """`mail_refuse` impose la réponse au prochain MAIL FROM et, avec
        `close`, ferme ensuite la connexion ; le suivant est servi."""
        child = self.child()
        child.call("mail_refuse", reply="421 4.7.0 try later", close=True)
        port = child.ports["smtp_port"]
        with smtplib.SMTP("127.0.0.1", port, timeout=10) as smtp:
            smtp.ehlo()
            code, _texte = smtp.mail("boite.regles@example.org")
            self.assertEqual(code, 421)
            with self.assertRaises(smtplib.SMTPServerDisconnected):
                smtp.rset()
        with smtplib.SMTP("127.0.0.1", port, timeout=10) as smtp:
            smtp.ehlo()
            self.assertEqual(smtp.mail("boite.regles@example.org")[0], 250)

    def test_data_refuse_answers_after_the_data(self):
        """`data_refuse` impose la réponse qui suit les données, et le
        message n'est pas gardé ; sans réponse imposée, il l'est."""
        child = self.child()
        child.call("data_refuse", reply="554 5.7.1 content rejected")
        port = child.ports["smtp_port"]
        with smtplib.SMTP("127.0.0.1", port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.mail("boite.regles@example.org")
            smtp.rcpt("carole.regle@example.org")
            self.assertEqual(smtp.data(RAW)[0], 554)
        self.assertEqual(child.call("sent")["result"]["messages"], [])
        child.call("data_refuse", reply="")
        with smtplib.SMTP("127.0.0.1", port, timeout=10) as smtp:
            smtp.sendmail(
                "boite.regles@example.org", ["carole.regle@example.org"], RAW
            )
        self.assertEqual(len(child.call("sent")["result"]["messages"]), 1)

    def test_end_of_stdin_stops_the_server(self):
        """La fin de l'entrée standard arrête les deux serveurs et le
        script sort avec le code 0."""
        import mail_sandbox

        child = self.child()
        ports = (child.ports["imap_port"], child.ports["smtp_port"])
        debut = time.monotonic()
        child.proc.stdin.close()
        self.assertEqual(child.proc.wait(10), 0)
        self.assertLess(time.monotonic() - debut, 10)
        for port in ports:
            self.assertTrue(mail_sandbox.port_is_closed(port), port)


if __name__ == "__main__":
    unittest.main()
