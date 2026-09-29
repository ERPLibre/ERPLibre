#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une instance jetable qui parle comme un serveur de microblogue, sur 127.0.0.1.

Aucun test ne touche le réseau : le serveur est démarré ici même, sur un
port que le système choisit, et meurt avec le test. C'est la même contrainte
que pour le bac à sable IMAP, pour la même raison — un test qui appelle une
vraie instance échoue quand elle est lente, change de version, ou demande
qu'on lui ouvre un compte.

Ce qu'il sert n'est pas une instance conforme : c'est ce qu'une instance
répond quand tout va bien, et SURTOUT ce qu'elle répond quand tout va mal.
Les pannes sont ce qui compte, et chacune a son mode de défaillance côté
client : un jeton refusé se répare en en redemandant un, une limite de débit
s'attend, une passerelle en vrac se réessaie. Les confondre ferait
redemander un jeton valide à chaque hoquet du réseau.

La PAGINATION est ici parce qu'elle se trompe facilement : l'instance rend
la suite dans un en-tête `Link`, pas dans le corps. Prendre plutôt
l'identifiant du dernier billet reçu paraît marcher et saute des billets dès
qu'un trou apparaît dans la suite.
"""

from __future__ import annotations

import http.server
import json
import threading
import urllib.parse

HOST = "127.0.0.1"

# Inventé de bout en bout : aucun jeton réel n'entre dans un fichier du
# dépôt, même de test.
JETON = "jeton-du-bac-a-sable"


class Fault:
    """Une panne à servir à la place d'une réponse polie."""

    def __init__(self, sur: str = "", apres: int = 0):
        # `sur` borne la panne à un chemin ; vide, elle vaut pour tous.
        self.sur = sur
        # Nombre d'appels à laisser passer avant de frapper : une panne au
        # PREMIER appel ne prouve rien sur une reprise en cours de route.
        self.apres = apres

    def concerne(self, chemin: str) -> bool:
        if self.sur and self.sur not in chemin:
            return False
        if self.apres > 0:
            self.apres -= 1
            return False
        return True


class Refuse(Fault):
    """401 : le jeton ne vaut plus rien.

    Le cas à distinguer de tous les autres — aucun nouvel essai ne le
    répare, il faut refaire autoriser le compte.
    """


class TropVite(Fault):
    """429 : trop de demandes. S'attend, ne se réessaie pas tout de suite.

    L'en-tête dit QUAND reprendre ; un client qui l'ignore se fait couper
    plus longtemps à chaque tour.
    """

    def __init__(self, sur: str = "", apres: int = 0, reprise: int = 42):
        super().__init__(sur, apres)
        self.reprise = reprise


class EnVrac(Fault):
    """500 : l'instance a un souci. Se réessaie plus tard."""


class PerdueApres(Fault):
    """La demande est TRAITÉE, puis la réponse se perd.

    La panne qui compte pour une publication : le billet est bel et bien
    posé, mais le client ne l'apprend jamais. Sans clé d'idempotence, sa
    reprise en pose un second ; avec elle, l'instance rend le premier.
    """


class Illisible(Fault):
    """200, mais le corps n'est pas du JSON.

    Vu quand une passerelle intercale une page d'erreur en HTML sous un code
    de succès ; le client doit le dire plutôt que de planter sur un décodage.
    """


def statut(
    ident: str,
    texte: str = "Bonjour le fil.",
    *,
    quand: str = "2026-09-18T14:22:31.000Z",
    auteur: str = "ana",
    nom: str = "Ana",
    repond_a: str | None = None,
    partage: dict | None = None,
    pieces: list | None = None,
    hote: str = "instance.exemple",
) -> dict:
    """Un billet dans la forme que rend l'API.

    `content` est du HTML : c'est ce que l'instance sert, et le client doit
    en tirer du texte. `partage` est le billet d'autrui repris tel quel —
    sa présence change qui est l'auteur de ce qu'on lit.
    """
    return {
        "id": ident,
        "created_at": quand,
        "in_reply_to_id": repond_a,
        "uri": f"https://{hote}/users/{auteur}/statuses/{ident}",
        "url": f"https://{hote}/@{auteur}/{ident}",
        "content": f"<p>{texte}</p>",
        "account": {
            "acct": auteur,
            "display_name": nom,
            "url": f"https://{hote}/@{auteur}",
        },
        "media_attachments": pieces or [],
        "reblog": partage,
    }


def piece(
    url: str = "https://i.exemple/1.png",
    genre: str = "image",
    description: str = "",
) -> dict:
    return {"url": url, "type": genre, "description": description}


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        """Muet : la sortie d'un test n'est pas un journal d'accès."""

    @property
    def bac(self) -> "SocialSandbox":
        return self.server.bac

    def do_GET(self) -> None:  # noqa: N802 - imposé par la stdlib
        chemin = urllib.parse.urlparse(self.path)
        self.bac.demandes.append(self.path)
        panne = self.bac._panne_pour(chemin.path)
        if panne is not None:
            self._servir_panne(panne)
            return
        if self.headers.get("Authorization") != f"Bearer {self.bac.jeton}":
            self._json(401, {"error": "The access token is invalid"})
            return
        if chemin.path == "/api/v1/accounts/verify_credentials":
            self._json(200, self.bac.identite)
            return
        if chemin.path == "/api/v1/timelines/home":
            self._fil(urllib.parse.parse_qs(chemin.query))
            return
        if chemin.path == "/api/v1/instance":
            self._json(
                200,
                {
                    "configuration": {
                        "statuses": {
                            "max_characters": self.bac.limite_caracteres
                        }
                    }
                },
            )
            return
        self._json(404, {"error": "Record not found"})

    def do_POST(self) -> None:  # noqa: N802 - imposé par la stdlib
        chemin = urllib.parse.urlparse(self.path)
        self.bac.demandes.append(self.path)
        longueur = int(self.headers.get("Content-Length") or 0)
        corps = self.rfile.read(longueur) if longueur else b""
        panne = self.bac._panne_pour(chemin.path)
        if panne is not None and not isinstance(panne, PerdueApres):
            self._servir_panne(panne)
            return
        if self.headers.get("Authorization") != f"Bearer {self.bac.jeton}":
            self._json(401, {"error": "The access token is invalid"})
            return
        if chemin.path != "/api/v1/statuses":
            self._json(404, {"error": "Record not found"})
            return
        champs = {
            k: v[0]
            for k, v in urllib.parse.parse_qs(
                corps.decode("utf-8", "replace")
            ).items()
        }
        cle = self.headers.get("Idempotency-Key") or ""
        # Même clé, même billet : l'instance rend celui déjà posé sans en
        # créer un second. C'est ce qui rend une reprise sûre.
        if cle:
            deja = next(
                (b for b, k in self.bac.publies if k == cle and k), None
            )
            if deja is not None:
                self._json(200, deja)
                return
        texte = champs.get("status", "")
        if not texte.strip():
            self._json(
                422, {"error": "Validation failed: Text can't be blank"}
            )
            return
        if len(texte) > self.bac.limite_caracteres:
            self._json(
                422,
                {"error": "Validation failed: Text character limit exceeded"},
            )
            return
        billet = statut(
            str(1000 + len(self.bac.publies)),
            texte,
            auteur=self.bac.identite["acct"],
            nom=self.bac.identite["display_name"],
            repond_a=champs.get("in_reply_to_id") or None,
        )
        billet["visibility"] = champs.get("visibility", "public")
        self.bac.publies.append((billet, cle))
        if panne is not None:
            # Le billet est POSÉ ; c'est la réponse qui se perd.
            self._servir_panne(EnVrac())
            return
        self._json(200, billet)

    def _fil(self, params: dict) -> None:
        """Rend une page du fil, et la suite dans un en-tête `Link`.

        `max_id` demande ce qui précède un billet déjà vu : c'est ainsi
        qu'on remonte le fil, du plus récent vers le plus ancien.
        """
        billets = list(self.bac.fil)
        depuis = 0
        if self.bac.pagination == "jeton":
            # Un continuateur opaque : un rang, signé d'un préfixe que le
            # client ne saurait pas inventer.
            jeton = (params.get("suite") or [None])[0]
            if jeton and jeton.startswith("k-"):
                depuis = int(jeton[2:])
        else:
            max_id = (params.get("max_id") or [None])[0]
            if max_id is not None:
                idents = [b["id"] for b in billets]
                if max_id in idents:
                    depuis = idents.index(max_id) + 1
        billets = billets[depuis:]
        limite = int((params.get("limit") or ["40"])[0])
        page = billets[:limite]
        entetes = {}
        if len(billets) > limite and page:
            base = f"http://{HOST}:{self.bac.port}/api/v1/timelines/home"
            if self.bac.pagination == "jeton":
                suivant = f"{base}?suite=k-{depuis + limite}"
            else:
                suivant = f"{base}?max_id={page[-1]['id']}"
            entetes["Link"] = f'<{suivant}>; rel="next"'
        self._json(200, page, entetes)

    def _servir_panne(self, panne: Fault) -> None:
        if isinstance(panne, Refuse):
            self._json(401, {"error": "The access token is invalid"})
        elif isinstance(panne, TropVite):
            self._json(
                429,
                {"error": "Too many requests"},
                {"X-RateLimit-Reset": str(panne.reprise)},
            )
        elif isinstance(panne, Illisible):
            self._brut(200, b"<html>passerelle</html>", "text/html")
        else:
            self._json(500, {"error": "Something went wrong"})

    def _json(self, code: int, charge, entetes: dict | None = None) -> None:
        self._brut(
            code,
            json.dumps(charge).encode(),
            "application/json",
            entetes,
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


class SocialSandbox:
    """Une instance jetable. `start()` puis `stop()`, ou via `MailSandboxCase`.

    Le port est choisi par le système : deux bacs tournent en même temps, et
    aucun test n'occupe un port fixe que la machine emploie peut-être déjà.
    """

    def __init__(self, jeton: str = JETON, pagination: str = "max_id"):
        self.jeton = jeton
        # Comment l'instance nomme la suite dans son en-tête `Link`.
        # « max_id » est la forme la plus répandue ; « jeton » est celle
        # d'une instance qui y met un CONTINUATEUR opaque, que le client
        # n'a aucun moyen de reconstruire. Les deux existent, et la seconde
        # est ce qui interdit de deviner l'URL de la page suivante.
        self.pagination = pagination
        self.fil: list = []
        self.faults: list = []
        self.demandes: list = []
        # Ce que l'instance annonce comme longueur maximale d'un billet. La
        # valeur par défaut du logiciel ; une instance la change, et c'est
        # pourquoi un client la DEMANDE au lieu de la supposer.
        self.limite_caracteres = 500
        self.publies: list = []
        self.identite = {
            "acct": "moi",
            "display_name": "Moi",
            "url": "https://instance.exemple/@moi",
        }
        self.port = 0
        self._httpd = None
        self._fil_serveur = None

    # -- déclaration du contenu -----------------------------------------

    def publier(self, *billets) -> "SocialSandbox":
        """Ajoute des billets, le plus RÉCENT d'abord — l'ordre de l'API."""
        self.fil.extend(billets)
        return self

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

    # -- cycle de vie ---------------------------------------------------

    def start(self) -> "SocialSandbox":
        self._httpd = http.server.ThreadingHTTPServer((HOST, 0), _Handler)
        self._httpd.bac = self
        self.port = self._httpd.server_address[1]
        self._fil_serveur = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )
        self._fil_serveur.start()
        return self

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
