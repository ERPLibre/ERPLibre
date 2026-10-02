#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un serveur jetable qui parle comme l'API de partage d'un réseau pro.

Le troisième réseau du paquet, et le seul qui ne propose aucune garantie
contre le double envoi. Le premier accepte une clé d'idempotence, le second une adresse
d'enregistrement à réécrire ; celui-ci n'a qu'un garde-fou anti-spam, qui
refuse une répétition identique à l'octet pendant quelques minutes — il
expire, et un caractère changé le contourne, donc il ne garantit pas le
rejeu. Il donne tout de même le seul signal qui LÈVE un doute : son refus
nomme le billet déjà en ligne.

Ce bac à sable rend les deux situations reproductibles : `PerdueApres`
publie PUIS perd la réponse, et le renvoi qui suit se heurte au garde-fou.
`anti_doublon = False` le désarme, ce qui tient lieu de son expiration et
redonne le cas où deux demandes identiques font deux publications.

Il ne sert AUCUN fil, et c'est voulu : récupérer celui d'un membre demande
une autorisation qui ne s'obtient pas en libre-service. Un bac à sable qui en
servirait un ferait écrire un client contre une API qu'il ne pourra jamais
appeler.
"""

from __future__ import annotations

import http.server
import json
import threading
import time
import urllib.parse

from social_sandbox import (
    EnVrac,
    Fault,
    Illisible,
    PerdueApres,
    Refuse,
    TropVite,
)

HOST = "127.0.0.1"

# Inventé de bout en bout.
JETON = "jeton-du-bac-pro"
MEMBRE = "abcd1234"


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        """Muet : la sortie d'un test n'est pas un journal d'accès."""

    @property
    def bac(self) -> "LinkedInSandbox":
        return self.server.bac

    def _autorise(self) -> bool:
        if self.headers.get("Authorization") != f"Bearer {self.bac.jeton}":
            self._json(401, {"message": "Invalid access token"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802 - imposé par la stdlib
        chemin = urllib.parse.urlparse(self.path)
        self.bac.demandes.append(self.path)
        panne = self.bac._panne_pour(chemin.path)
        if panne is not None:
            self._servir_panne(panne)
            return
        if not self._autorise():
            return
        if chemin.path == "/v2/userinfo":
            self._json(200, {"sub": self.bac.membre, "name": self.bac.nom})
            return
        # Aucune route de fil : ce réseau n'en sert pas au client.
        self._json(403, {"message": "Not enough permissions to access"})

    def do_POST(self) -> None:  # noqa: N802 - imposé par la stdlib
        chemin = urllib.parse.urlparse(self.path)
        self.bac.demandes.append(self.path)
        longueur = int(self.headers.get("Content-Length") or 0)
        brut = self.rfile.read(longueur) if longueur else b"{}"
        try:
            charge = json.loads(brut.decode("utf-8", "replace"))
        except ValueError:
            charge = {}
        panne = self.bac._panne_pour(chemin.path)
        if panne is not None and not isinstance(panne, PerdueApres):
            self._servir_panne(panne)
            return
        if not self._autorise():
            return
        if chemin.path != "/v2/ugcPosts":
            self._json(404, {"message": "Resource not found"})
            return
        texte = _commentaire(charge)
        if not texte.strip():
            self._json(422, {"message": "Commentary cannot be empty"})
            return
        if len(texte) > self.bac.limite_caracteres:
            self._json(422, {"message": "Commentary is too long"})
            return
        if self.bac.anti_doublon:
            for ancien, _, deja in self.bac.publies:
                if ancien == texte:
                    # LE REFUS TEL QUE LE SERVICE L'ÉCRIT : un 422 dont le
                    # message nomme le billet déjà posé. C'est le seul
                    # signal qui prouve qu'un envoi dont la réponse s'est
                    # perdue a bien abouti.
                    message = "Duplicate post detected"
                    if self.bac.doublon_nomme:
                        message += f": {deja}"
                    self._json(422, {"message": message, "status": 422})
                    return
        urn = f"urn:li:share:{7000 + len(self.bac.publies)}"
        self.bac.publies.append((texte, charge, urn))
        if panne is not None:
            # Publié ; c'est la réponse qui se perd.
            self._servir_panne(EnVrac())
            return
        # CE QUE LE SERVICE RÉPOND VRAIMENT : 201, AUCUN CORPS, et
        # l'identifiant dans un en-tête — en casse mixte, comme sa
        # documentation l'écrit. Inventer un corps `{"id": …}` ferait passer
        # au vert un client incapable de lire une vraie réponse.
        self._brut(201, b"", "application/json", {"X-RestLi-Id": urn})

    def _servir_panne(self, panne: Fault) -> None:
        if isinstance(panne, Refuse):
            self._json(401, {"message": "Invalid access token"})
        elif isinstance(panne, TropVite):
            self._json(
                429,
                {"message": "Throttled"},
                # UN DÉLAI, parce que c'est ce que `Retry-After` porte :
                # des secondes à compter de maintenant, et non le moment
                # lui-même. Les deux autres services nomment le moment.
                {"Retry-After": str(max(0, int(panne.reprise - time.time())))},
            )
        elif isinstance(panne, Illisible):
            self._brut(200, b"<html>passerelle</html>", "text/html")
        else:
            self._json(500, {"message": "Internal error"})

    def _json(self, code: int, charge, entetes: dict | None = None) -> None:
        self._brut(
            code, json.dumps(charge).encode(), "application/json", entetes
        )

    def _brut(
        self,
        code: int,
        corps: bytes,
        genre: str,
        entetes: dict | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", genre)
        self.send_header("Content-Length", str(len(corps)))
        for nom, valeur in (entetes or {}).items():
            self.send_header(nom, valeur)
        self.end_headers()
        self.wfile.write(corps)


def _commentaire(charge: dict) -> str:
    """Le texte, au fond des trois niveaux où l'API le range."""
    contenu = (charge.get("specificContent") or {}).get(
        "com.linkedin.ugc.ShareContent"
    ) or {}
    return str((contenu.get("shareCommentary") or {}).get("text") or "")


class LinkedInSandbox:
    """Une API de partage jetable, sur un port éphémère."""

    def __init__(self, jeton: str = JETON):
        self.jeton = jeton
        self.membre = MEMBRE
        self.nom = "Moi"
        self.limite_caracteres = 3000
        # Le garde-fou anti-spam du service, actif comme chez lui. Le
        # désarmer tient lieu de son expiration.
        self.anti_doublon = True
        # Le refus nomme-t-il le billet déjà posé ? Chez le service, pas
        # toujours : un doublon sans adresse reste un doublon, et le client
        # doit le dire sans prétendre savoir où regarder.
        self.doublon_nomme = True
        self.publies: list = []
        self.faults: list = []
        self.demandes: list = []
        self.port = 0
        self._httpd = None

    def fail(self, fault: Fault) -> Fault:
        self.faults.append(fault)
        return fault

    def _panne_pour(self, chemin: str):
        for panne in list(self.faults):
            if panne.concerne(chemin):
                self.faults.remove(panne)
                return panne
        return None

    @property
    def base_url(self) -> str:
        return f"http://{HOST}:{self.port}"

    def start(self) -> "LinkedInSandbox":
        self._httpd = http.server.ThreadingHTTPServer((HOST, 0), _Handler)
        self._httpd.bac = self
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None


__all__ = [
    "JETON",
    "EnVrac",
    "Illisible",
    "LinkedInSandbox",
    "PerdueApres",
    "Refuse",
    "TropVite",
]
