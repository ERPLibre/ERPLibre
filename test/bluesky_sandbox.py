#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un serveur jetable qui parle comme un dépôt de données personnel.

Le second réseau du paquet, et il ne ressemble pas au premier. Ce qui change,
et que ce bac à sable existe pour éprouver :

L'authentification est une SESSION. Un mot de passe d'application ouvre une
session qui rend deux jetons — un d'accès, court, et un de rafraîchissement,
durable. Le premier expire en cours de route, et le serveur le dit par un
nom d'erreur précis qu'un client doit reconnaître pour rafraîchir au lieu de
redemander le mot de passe.

La suite d'une page est un CURSEUR dans le corps de la réponse, non un
en-tête `Link`. Le cache n'en sait rien : il garde un curseur opaque, et
c'est ce qui lui permet de servir les deux réseaux sans les distinguer.

Publier s'y fait en ÉCRIVANT UN ENREGISTREMENT à une adresse qu'on choisit.
Il n'y a pas de clé d'idempotence à passer : c'est l'adresse qui tient ce
rôle, puisque réécrire la même remplace au lieu d'ajouter.

Les pannes viennent de `social_sandbox` : elles ne dépendent pas du réseau
qu'on simule, et les recopier ferait deux jeux à corriger.
"""

from __future__ import annotations

import http.server
import json
import threading
import urllib.parse

from social_sandbox import EnVrac, Fault, Illisible, Refuse, TropVite

HOST = "127.0.0.1"

# Inventés de bout en bout : aucun secret réel n'entre dans un fichier du
# dépôt, même de test.
MOT_DE_PASSE = "mot-de-passe-d-application"
JETON_ACCES = "jeton-d-acces-du-bac"
JETON_REPRISE = "jeton-de-reprise-du-bac"
DID = "did:plc:exemple1234567890"


# L'alphabet TRIÉ dont le service tire ses adresses d'enregistrement : il
# range un dépôt par adresse, donc l'ordre des caractères doit suivre l'ordre
# du temps. Ce n'est PAS l'alphabet base32 courant, où « 2 » précède « a ».
ALPHABET_TID = "234567abcdefghijklmnopqrstuvwxyz"


def tid_valide(rkey: str) -> bool:
    """Vrai si `rkey` a la forme que le service exige d'une adresse.

    Treize caractères de l'alphabet trié, le premier dans sa première
    moitié — le bit de poids fort d'un identifiant est toujours nul. Un
    service courant refuse tout le reste par un 400, et un bac à sable qui
    accepterait n'importe quoi laisserait passer un client incapable de
    publier.
    """
    return (
        len(rkey) == 13
        and all(c in ALPHABET_TID for c in rkey)
        and rkey[0] in ALPHABET_TID[:16]
    )


def _ref_valide(ref) -> bool:
    """Une référence forte porte une adresse ET une empreinte de contenu.

    L'une sans l'autre ne désigne pas un billet : l'adresse dit où, et
    l'empreinte dit quelle version. Le lexique les exige toutes deux.
    """
    return (
        isinstance(ref, dict) and bool(ref.get("uri")) and bool(ref.get("cid"))
    )


class JetonExpire(Fault):
    """Le jeton d'accès a vécu. Le serveur le NOMME.

    C'est le seul refus qui se répare sans rien redemander à la personne :
    le jeton de rafraîchissement en obtient un neuf. Le confondre avec un
    mot de passe refusé ferait redemander un secret qui est bon.
    """


def billet(
    rkey: str,
    texte: str = "Bonjour le fil.",
    *,
    quand: str = "2026-09-18T14:22:31.000Z",
    auteur: str = "ana.exemple",
    nom: str = "Ana",
    did: str = "did:plc:ana000000000000",
    repond_a: str = "",
    racine: dict | None = None,
    partage_par: str = "",
    images: list | None = None,
) -> dict:
    """Une entrée de fil dans la forme que rend le service.

    `partage_par` produit un PARTAGE : le billet est celui d'autrui, et ce
    qui dit qui l'a repris vit à côté du billet, non dedans.
    """
    enregistrement = {
        "text": texte,
        "createdAt": quand,
        "$type": "app.bsky.feed.post",
    }
    if repond_a:
        # Les deux références, chacune complète : c'est ce que le lexique
        # exige, et ce qu'un client doit savoir relire pour répondre à son
        # tour sans casser le fil.
        parent = {"uri": repond_a, "cid": f"bafyreiparent{rkey}"}
        enregistrement["reply"] = {
            "root": racine or parent,
            "parent": parent,
        }
    entree = {
        "post": {
            "uri": f"at://{did}/app.bsky.feed.post/{rkey}",
            "cid": f"bafyrei{rkey}",
            "author": {"did": did, "handle": auteur, "displayName": nom},
            "record": enregistrement,
        }
    }
    if images:
        entree["post"]["embed"] = {
            "$type": "app.bsky.embed.images#view",
            "images": images,
        }
    if partage_par:
        entree["reason"] = {
            "$type": "app.bsky.feed.defs#reasonRepost",
            "by": {"handle": partage_par, "displayName": partage_par},
        }
    return entree


def image(url: str = "https://i.exemple/1.png", alt: str = "") -> dict:
    return {"fullsize": url, "alt": alt}


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        """Muet : la sortie d'un test n'est pas un journal d'accès."""

    @property
    def bac(self) -> "BlueskySandbox":
        return self.server.bac

    # -- Routage --------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - imposé par la stdlib
        chemin = urllib.parse.urlparse(self.path)
        self.bac.demandes.append(self.path)
        panne = self.bac._panne_pour(chemin.path)
        if panne is not None:
            self._servir_panne(panne)
            return
        if chemin.path == "/xrpc/app.bsky.feed.getTimeline":
            if not self._jeton_bon():
                return
            self._fil(urllib.parse.parse_qs(chemin.query))
            return
        self._json(404, {"error": "MethodNotImplemented"})

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
        if panne is not None:
            self._servir_panne(panne)
            return
        if chemin.path == "/xrpc/com.atproto.server.createSession":
            self._ouvrir_session(charge)
            return
        if chemin.path == "/xrpc/com.atproto.server.refreshSession":
            self._rafraichir()
            return
        if chemin.path == "/xrpc/com.atproto.repo.putRecord":
            if not self._jeton_bon():
                return
            self._ecrire(charge)
            return
        self._json(404, {"error": "MethodNotImplemented"})

    # -- Session --------------------------------------------------------

    def _ouvrir_session(self, charge: dict) -> None:
        if charge.get("password") != self.bac.mot_de_passe:
            self._json(
                401,
                {
                    "error": "AuthenticationRequired",
                    "message": "Invalid identifier or password",
                },
            )
            return
        self.bac.sessions += 1
        self._json(
            200,
            {
                "did": self.bac.did,
                "handle": charge.get("identifier", ""),
                "accessJwt": self.bac.jeton_acces,
                "refreshJwt": self.bac.jeton_reprise,
            },
        )

    def _rafraichir(self) -> None:
        """Le jeton de RAFRAÎCHISSEMENT s'y présente, pas celui d'accès."""
        if self.headers.get("Authorization") != (
            f"Bearer {self.bac.jeton_reprise}"
        ):
            self._json(401, {"error": "AuthenticationRequired"})
            return
        self.bac.rafraichissements += 1
        self.bac.jeton_acces = f"{self.bac.jeton_acces}-neuf"
        self.bac.expire = False
        self._json(
            200,
            {
                "did": self.bac.did,
                "accessJwt": self.bac.jeton_acces,
                "refreshJwt": self.bac.jeton_reprise,
            },
        )

    def _jeton_bon(self) -> bool:
        attendu = f"Bearer {self.bac.jeton_acces}"
        if self.bac.expire:
            # Nommé : c'est ce nom qui distingue « rafraîchis » de
            # « redemande le mot de passe ».
            self._json(400, {"error": "ExpiredToken"})
            return False
        if self.headers.get("Authorization") != attendu:
            self._json(401, {"error": "AuthenticationRequired"})
            return False
        return True

    # -- Contenu --------------------------------------------------------

    def _fil(self, params: dict) -> None:
        entrees = list(self.bac.fil)
        curseur = (params.get("cursor") or [None])[0]
        if curseur is not None:
            depuis = self.bac.curseurs.get(curseur)
            entrees = entrees[depuis:] if depuis is not None else []
        limite = int((params.get("limit") or ["50"])[0])
        page = entrees[:limite]
        reponse = {"feed": page}
        if len(entrees) > limite:
            rang = len(self.bac.fil) - len(entrees) + limite
            suivant = f"c-{rang}"
            self.bac.curseurs[suivant] = rang
            # Le curseur est dans le CORPS, pas dans un en-tête.
            reponse["cursor"] = suivant
        self._json(200, reponse)

    def _ecrire(self, charge: dict) -> None:
        """Écrit un enregistrement à l'adresse demandée.

        Réécrire la MÊME adresse remplace au lieu d'ajouter : c'est ce qui
        tient lieu de clé d'idempotence ici.
        """
        rkey = charge.get("rkey") or ""
        enregistrement = charge.get("record") or {}
        if not tid_valide(rkey):
            # Le service valide la FORME de l'adresse avant tout le reste :
            # la collection déclare le type attendu, et une adresse d'une
            # autre forme est refusée sans que l'enregistrement soit lu.
            self._json(
                400,
                {
                    "error": "InvalidRecordError",
                    "message": f"Invalid rkey: {rkey!r}",
                },
            )
            return
        reponse = enregistrement.get("reply")
        if reponse is not None:
            # Une réponse nomme DEUX billets : celui auquel elle répond et
            # la racine du fil. Les deux par référence forte. Il manquait
            # la racine, et l'empreinte des deux.
            manque = [
                champ
                for champ in ("root", "parent")
                if not _ref_valide((reponse or {}).get(champ))
            ]
            if manque:
                self._json(
                    400,
                    {
                        "error": "InvalidRequest",
                        "message": (
                            "Invalid app.bsky.feed.post record: reply"
                            f' must have the property "{manque[0]}"'
                        ),
                    },
                )
                return
        texte = enregistrement.get("text", "")
        if not texte.strip():
            self._json(
                400,
                {"error": "InvalidRequest", "message": "Record text is empty"},
            )
            return
        if len(texte) > self.bac.limite_caracteres:
            self._json(
                400,
                {
                    "error": "InvalidRequest",
                    "message": "Record text too long",
                },
            )
            return
        uri = f"at://{self.bac.did}/app.bsky.feed.post/{rkey}"
        self.bac.ecrits[uri] = enregistrement
        self._json(200, {"uri": uri, "cid": f"bafyrei{rkey}"})

    # -- Pannes et sortie ------------------------------------------------

    def _servir_panne(self, panne: Fault) -> None:
        if isinstance(panne, JetonExpire):
            self._json(400, {"error": "ExpiredToken"})
        elif isinstance(panne, Refuse):
            self._json(401, {"error": "AuthenticationRequired"})
        elif isinstance(panne, TropVite):
            self._json(
                429,
                {"error": "RateLimitExceeded"},
                {"RateLimit-Reset": str(panne.reprise)},
            )
        elif isinstance(panne, Illisible):
            self._brut(200, b"<html>passerelle</html>", "text/html")
        else:
            self._json(500, {"error": "InternalServerError"})

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


class BlueskySandbox:
    """Un dépôt de données personnel jetable, sur un port éphémère."""

    def __init__(self, mot_de_passe: str = MOT_DE_PASSE):
        self.mot_de_passe = mot_de_passe
        self.jeton_acces = JETON_ACCES
        self.jeton_reprise = JETON_REPRISE
        self.did = DID
        # Vrai quand le jeton d'accès est périmé : toute demande
        # authentifiée répond alors `ExpiredToken`, jusqu'au
        # rafraîchissement.
        self.expire = False
        self.limite_caracteres = 300
        self.fil: list = []
        self.ecrits: dict = {}
        self.curseurs: dict = {}
        self.faults: list = []
        self.demandes: list = []
        self.sessions = 0
        self.rafraichissements = 0
        self.port = 0
        self._httpd = None

    # -- déclaration du contenu -----------------------------------------

    def publier(self, *entrees) -> "BlueskySandbox":
        """Ajoute des entrées, la plus RÉCENTE d'abord."""
        self.fil.extend(entrees)
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

    def start(self) -> "BlueskySandbox":
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
    "BlueskySandbox",
    "EnVrac",
    "Illisible",
    "JetonExpire",
    "MOT_DE_PASSE",
    "Refuse",
    "TropVite",
    "billet",
    "image",
]
