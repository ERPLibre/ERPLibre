#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un vrai serveur HTTP jetable, qui se fait passer pour un serveur LLM.

Pourquoi un vrai serveur plutôt qu'un double de `requests` ou du client
`openai` : un double ne rend que ce qu'on avait imaginé en l'écrivant. Or tout
ce qui casse une reconnaissance vient du TRANSPORT, pas de l'analyse — une
page d'administration de routeur qui rend du HTML là où on attendait du JSON,
un 503 pendant le chargement d'un modèle, un défi 401, une connexion coupée en
plein corps, un corps qui ne finit pas.

L'intérêt n'est donc pas de servir poliment : c'est de POUVOIR MAL SE
CONDUIRE. Ajouter une méchanceté doit rester une petite addition — une
sous-classe de `Fault` — jamais un second serveur.

Le serveur se lie à 127.0.0.1 sur le port 0 : le système choisit, donc rien
n'entre en collision avec ce qui écoute déjà, et rien ne quitte la machine.

`FIXTURES` porte les corps de référence par famille de serveur. Les tests PURS
de reconnaissance et les tests de transport lisent les MÊMES octets : sans
cela, l'analyse serait vérifiée contre une idée du protocole et le transport
contre une autre, et l'écart ne se verrait qu'en production.

Les valeurs y sont inventées — versions, noms de modèles, empreintes de
compilation. Un relevé pris sur une machine réelle figerait dans le dépôt le
nom d'un modèle et d'un hôte que personne n'a choisi d'y mettre.
"""
from __future__ import annotations

import http.server
import json
import threading

HOST = "127.0.0.1"

# Corps de référence par famille. Chemin -> (statut, octets). Un chemin absent
# de la table rend 404 : c'est ce qui distingue les familles entre elles, et
# c'est donc une donnée du test autant que les corps eux-mêmes.
#
# LocalAI porte l'API d'Ollama EN ENTIER, jusqu'à la chaîne « Ollama is
# running » sur la racine. Les deux tables se ressemblent exprès : leur seule
# différence est `/readyz`, que LocalAI sert et qu'Ollama ignore, plus la
# version figée que LocalAI rend là où Ollama rend un vrai numéro. Une échelle
# de reconnaissance qui interroge Ollama avant d'écarter LocalAI se trompe sur
# toutes les machines LocalAI, et ces deux tables sont ce qui le prouve.
FIXTURES: dict[str, dict[str, tuple[int, bytes]]] = {
    "ollama": {
        "/": (200, b"Ollama is running"),
        "/api/version": (200, b'{"version":"0.6.2"}'),
        "/api/tags": (
            200,
            json.dumps(
                {
                    "models": [
                        {
                            "name": "petit-modele:7b",
                            "details": {"parameter_size": "7.2B"},
                        }
                    ]
                }
            ).encode(),
        ),
        "/v1/models": (
            200,
            b'{"object":"list","data":[{"id":"petit-modele:7b"}]}',
        ),
    },
    "localai": {
        "/readyz": (200, b""),
        "/healthz": (200, b""),
        "/": (200, b"Ollama is running"),
        # Le littéral figé : LocalAI annonce toujours cette version-là, quelle
        # que soit la sienne. Un vrai Ollama rend le numéro qu'il porte.
        "/api/version": (200, b'{"version":"0.9.0"}'),
        "/api/tags": (200, b'{"models":[{"name":"un-modele"}]}'),
        "/v1/models": (200, b'{"object":"list","data":[{"id":"un-modele"}]}'),
    },
    "localai_starting": {
        "/readyz": (
            503,
            b'{"status":"starting","reason":"startup preload in progress"}',
        ),
        "/healthz": (200, b""),
    },
    "llamacpp": {
        "/props": (
            200,
            json.dumps(
                {
                    "build_info": "b9999-0000000",
                    "chat_template_caps": {"supports_tools": True},
                    "modalities": {"vision": False},
                    "total_slots": 1,
                }
            ).encode(),
        ),
        "/health": (200, b'{"status":"ok"}'),
        "/v1/models": (
            200,
            json.dumps(
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "un-modele.gguf",
                            "owned_by": "llamacpp",
                            "meta": {
                                "n_ctx_train": 32768,
                                "n_params": 7000000000,
                            },
                        }
                    ],
                }
            ).encode(),
        ),
    },
    "llamacpp_loading": {
        "/health": (
            503,
            b'{"error":{"code":503,"message":"Loading model",'
            b'"type":"unavailable_error"}}',
        ),
    },
    "vllm": {
        # Le chemin est « /version », et c'est tout le propos :
        # « /api/version » appartient à Ollama et à LocalAI.
        "/version": (200, b'{"version":"0.0.0"}'),
        "/health": (200, b""),
        "/v1/models": (200, b'{"object":"list","data":[{"id":"un-modele"}]}'),
    },
    "lmstudio": {
        "/api/v0/models": (
            200,
            json.dumps(
                {
                    "data": [
                        {
                            "id": "un-modele",
                            "type": "llm",
                            "compatibility_type": "gguf",
                            "quantization": "Q4_K_M",
                            "state": "loaded",
                            "max_context_length": 8192,
                        }
                    ]
                }
            ).encode(),
        ),
        "/v1/models": (200, b'{"object":"list","data":[{"id":"un-modele"}]}'),
    },
    "koboldcpp": {
        "/api/extra/version": (200, b'{"result":"KoboldCpp","version":"0.0"}'),
        "/v1/models": (200, b'{"object":"list","data":[{"id":"un-modele"}]}'),
    },
    "jan": {
        "/openapi.json": (
            200,
            b'{"info":{"title":"Jan API Server Endpoints"}}',
        ),
        "/v1/models": (200, b'{"object":"list","data":[{"id":"un-modele"}]}'),
    },
    "open_webui": {
        "/api/config": (
            200,
            b'{"name":"Open WebUI","version":"0.0.0",'
            b'"deployment_id":"0000"}',
        ),
        "/api/version": (200, b'{"version":"0.0.0"}'),
    },
    "textgen_webui": {
        "/v1/internal/model/info": (200, b'{"model_name":"un-modele"}'),
        "/v1/models": (200, b'{"object":"list","data":[{"id":"un-modele"}]}'),
    },
    "tabbyapi": {
        # Un 401 est un ACCORD de reconnaissance : TabbyAPI exige une clé par
        # défaut. Ce n'est jamais une invitation à en saisir une.
        "/v1/model": (401, b'{"detail":"Invalid API key"}'),
        "/v1/template/list": (401, b'{"detail":"Invalid API key"}'),
    },
    "gpt4all": {
        # Aucun point de terminaison propre : GPT4All ne s'atteint que par
        # élimination, sur son port, quand rien d'autre n'a répondu.
        "/v1/models": (200, b'{"object":"list","data":[{"id":"un-modele"}]}'),
    },
    "routeur": {
        # Une page d'administration sur 8080 répond volontiers, en HTML, à
        # n'importe quel chemin. Elle ne nomme aucun serveur LLM.
        "/props": (200, b"<html><body>Administration</body></html>"),
        "/readyz": (200, b"<html><body>Administration</body></html>"),
        "/v1/models": (200, b"<html><body>Administration</body></html>"),
    },
}


class Fault:
    """Une méchanceté à servir à la place d'une réponse polie."""


class Cut(Fault):
    """Coupe la connexion après avoir annoncé un corps plus long.

    Le client doit rendre la main sur un corps tronqué plutôt que de lever :
    un serveur qui redémarre coupe exactement ainsi.
    """

    def __init__(self, partial: bytes = b'{"build_in', announced: int = 4096):
        self.partial = partial
        self.announced = announced


class Huge(Fault):
    """Annonce et sert un corps immense, pour prouver le plafond de lecture.

    La reconnaissance ne lit que quelques ko : sans plafond, un serveur mal
    configuré ferait tenir tout son catalogue en mémoire du menu.
    """

    def __init__(self, size: int = 8 * 1024 * 1024):
        self.size = size


class Silent(Fault):
    """Accepte la socket et ne répond jamais, pour prouver le délai.

    C'est le cas que « le port est ouvert » ne suffit pas à écarter : un
    écouteur bloqué accepte la connexion et laisse le client attendre.
    """

    def __init__(self, seconds: float = 30.0):
        self.seconds = seconds


class _Handler(http.server.BaseHTTPRequestHandler):
    # Le journal par défaut écrit sur stderr à chaque requête et noierait la
    # sortie de la suite.
    def log_message(self, fmt, *args):
        pass

    def _serve(self, method):
        server = self.server
        server.seen.append((method, self.path, dict(self.headers.items())))
        route = server.routes.get(self.path)
        if route is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if isinstance(route, Silent):
            # Ne rien écrire du tout : le client doit expirer de lui-même.
            import time

            time.sleep(route.seconds)
            return
        if isinstance(route, Cut):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(route.announced))
            self.end_headers()
            self.wfile.write(route.partial)
            self.close_connection = True
            return
        if isinstance(route, Huge):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(route.size))
            self.end_headers()
            bloc = b"x" * 65536
            reste = route.size
            try:
                while reste > 0:
                    n = min(reste, len(bloc))
                    self.wfile.write(bloc[:n])
                    reste -= n
            except (BrokenPipeError, ConnectionResetError):
                # Le client a fermé au plafond : c'est le comportement voulu,
                # pas une panne du serveur.
                pass
            return
        status, body = route
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "text/html" if body[:1] == b"<" else "application/json",
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        self._serve("GET")

    def do_POST(self):
        self._serve("POST")

    def do_HEAD(self):
        self._serve("HEAD")


class FakeLLM:
    """Un serveur d'une famille donnée, ou d'une table de chemins sur mesure.

    S'utilise comme gestionnaire de contexte ; `url` donne la racine à passer
    au client. Le port est choisi par le système, donc deux serveurs peuvent
    tourner en même temps sans se marcher dessus.

    `seen` porte (méthode, chemin, en-têtes) de chaque requête reçue : c'est
    ce qui permet d'affirmer qu'une découverte n'émet que des GET et n'envoie
    aucune autorisation.
    """

    def __init__(self, famille=None, *, routes=None):
        table = dict(FIXTURES[famille]) if famille else {}
        if routes:
            table.update(routes)
        self._httpd = http.server.ThreadingHTTPServer((HOST, 0), _Handler)
        self._httpd.routes = table
        self._httpd.seen = []
        self._httpd.daemon_threads = True
        # `serve_forever` sonde la demande d'arrêt à cet intervalle, et
        # `shutdown()` attend donc jusqu'à un intervalle entier. Le défaut de
        # 0,5 s se paie une fois par serveur : un fichier qui en ouvre vingt
        # passerait dix secondes à les fermer, pour une suite qui doit rester
        # de l'ordre de la seconde.
        self._fil = threading.Thread(
            target=self._httpd.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )

    def __enter__(self):
        self._fil.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._fil.join(timeout=5)
        return False

    @property
    def host(self) -> str:
        return HOST

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}"

    @property
    def seen(self) -> list:
        """(méthode, chemin, en-têtes) de chaque requête reçue."""
        return self._httpd.seen


def port_ferme() -> int:
    """Un port sur lequel personne n'écoute.

    Ouvrir puis refermer une socket rend un numéro que le système vient
    d'attribuer : personne d'autre ne l'a pris entre-temps, et une connexion
    y sera refusée tout de suite plutôt que d'expirer.
    """
    import socket

    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]
