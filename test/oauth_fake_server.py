#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un point de jeton OAuth jetable, sur 127.0.0.1.

Le rafraîchissement d'un jeton est un échange HTTP, et c'est la seule
partie d'OAuth que le client exécute tout seul, sans personne devant
l'écran. Elle doit donc se tester — et la contrainte du dépôt interdit
d'aller la tester chez le fournisseur.

Ce que ce serveur sert n'est PAS un fournisseur conforme : c'est ce qu'un
fournisseur répond quand tout va bien, et surtout ce qu'il répond quand
tout va mal. Les pannes sont ce qui compte : un jeton de rafraîchissement
révoqué, un corps illisible, une passerelle en vrac, une connexion coupée
au milieu. Chacune a son mode de défaillance côté client, et aucune ne
doit ressembler aux autres.

Le port est choisi par le système : deux serveurs peuvent tourner en même
temps, et aucun test n'occupe un port fixe que la machine utilise peut-être
déjà.
"""
from __future__ import annotations

import http.server
import json
import threading
import urllib.parse

HOST = "127.0.0.1"

# Ce que le faux fournisseur rend quand il est content. Inventé de bout en
# bout : aucun jeton réel ne doit jamais entrer dans un fichier du dépôt.
ACCESS_TOKEN = "jeton-d-acces-neuf"
REFRESH_TOKEN = "jeton-de-rafraichissement"


class Fault:
    """Une panne à servir à la place d'une réponse polie."""


class Revoked(Fault):
    """`invalid_grant` : le jeton de rafraîchissement ne vaut plus rien.

    Le cas qu'il faut distinguer de tous les autres : aucun nouvel essai ne
    le réparera, il faut refaire autoriser le compte par son propriétaire.
    Un client qui le confond avec une panne réseau réessaie pour toujours.
    """

    def __init__(
        self, description: str = "Token has been expired or revoked."
    ):
        self.description = description


class Malformed(Fault):
    """Répond 200 avec un corps qui n'est pas du JSON.

    Une passerelle d'entreprise qui intercale une page d'erreur répond
    exactement ainsi : le code dit oui, le corps ne se lit pas.
    """

    def __init__(self, body: bytes = b"<html>portail captif</html>"):
        self.body = body


class ServerError(Fault):
    """Un 5xx, la panne passagère qu'un nouvel essai peut réparer."""

    def __init__(self, code: int = 503):
        self.code = code


class Cut(Fault):
    """Annonce un corps puis coupe la connexion au milieu."""

    def __init__(self, partial: bytes = b'{"access_to', announced: int = 512):
        self.partial = partial
        self.announced = announced


class _Handler(http.server.BaseHTTPRequestHandler):
    # Le journal par défaut écrit sur stderr à chaque requête et noierait
    # la sortie de la suite.
    def log_message(self, fmt, *args):
        pass

    def do_POST(self):  # noqa: N802 - nom imposé par http.server
        longueur = int(self.headers.get("Content-Length") or 0)
        brut = self.rfile.read(longueur).decode("utf-8", "replace")
        champs = dict(urllib.parse.parse_qsl(brut))
        self.server.seen.append((self.path, champs))

        panne = self.server.fault
        if isinstance(panne, Cut):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(panne.announced))
            self.end_headers()
            self.wfile.write(panne.partial)
            self.wfile.flush()
            self.close_connection = True
            return
        if isinstance(panne, ServerError):
            self._json(panne.code, {"error": "temporarily_unavailable"})
            return
        if isinstance(panne, Malformed):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(panne.body)))
            self.end_headers()
            self.wfile.write(panne.body)
            return
        if isinstance(panne, Revoked):
            self._json(
                400,
                {
                    "error": "invalid_grant",
                    "error_description": panne.description,
                },
            )
            return

        if champs.get("grant_type") == "refresh_token":
            self._json(
                200,
                {
                    "access_token": ACCESS_TOKEN,
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
            return
        if champs.get("grant_type") == "authorization_code":
            self._json(
                200,
                {
                    "access_token": ACCESS_TOKEN,
                    "refresh_token": REFRESH_TOKEN,
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
            return
        self._json(400, {"error": "unsupported_grant_type"})

    def _json(self, code: int, charge: dict) -> None:
        corps = json.dumps(charge).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)


class FakeTokenEndpoint:
    """Le point `/token` d'un fournisseur, en gestionnaire de contexte.

        with FakeTokenEndpoint() as serveur:
            jeu = oauth.refresh(..., token_url=serveur.url)

    `fail(...)` remplace la réponse polie par une panne, et `seen` porte
    les champs reçus : c'est ce qui permet d'affirmer qu'un rafraîchissement
    envoie bien le jeton attendu, et JAMAIS le mot de passe du compte.
    """

    def __init__(self, port: int = 0):
        self._httpd = http.server.ThreadingHTTPServer((HOST, port), _Handler)
        self._httpd.seen = []
        self._httpd.fault = None
        self._httpd.daemon_threads = True
        # Le défaut de `serve_forever` sonde l'arrêt toutes les 0,5 s, que
        # `shutdown()` attend en entier. Un fichier de tests qui ouvre vingt
        # serveurs y passerait dix secondes.
        self._fil = threading.Thread(
            target=self._httpd.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )

    def __enter__(self) -> "FakeTokenEndpoint":
        self._fil.start()
        return self

    def __exit__(self, *exc) -> bool:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._fil.join(timeout=5)
        return False

    def fail(self, fault: Fault | None) -> "FakeTokenEndpoint":
        self._httpd.fault = fault
        return self

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self._httpd.server_address[1]}/token"

    @property
    def seen(self) -> list:
        """(chemin, champs du formulaire) de chaque requête reçue."""
        return self._httpd.seen
