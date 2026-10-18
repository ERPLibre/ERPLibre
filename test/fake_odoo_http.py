# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Un faux serveur HTTP d'Odoo, sur 127.0.0.1 et un port éphémère.

    with FauxOdoo({"/web/login": (200, {}, "<html>…")}) as serveur:
        rep = outil.ouvrir(serveur.url + "/web/login", 5)

`routes` associe un chemin à une réponse `(statut, entêtes, corps)`, ou à
une fonction qui reçoit la requête (`methode`, `chemin`, `entetes`,
`corps`) et rend ce triplet. Le chemin complet, requête comprise, est
cherché d'abord, puis le chemin seul ; sinon la réponse `defaut`.
`requetes` garde chaque requête reçue, dans l'ordre d'arrivée : c'est ce
qui permet d'affirmer qu'un outil n'envoie ni cookie de trop, ni en-tête
Authorization, ni requête vers un autre hôte.

Le serveur sert chaque requête dans son fil (ThreadingHTTPServer) : un
outil qui envoie plusieurs requêtes à la fois les voit arriver ensemble.
Aucun accès au réseau extérieur.
"""

import http.server
import threading
import types

HOTE = "127.0.0.1"


class _Gestionnaire(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _servir(self):
        taille = int(self.headers.get("Content-Length") or 0)
        corps = self.rfile.read(taille) if taille else b""
        requete = types.SimpleNamespace(
            methode=self.command,
            chemin=self.path,
            entetes={k.lower(): v for k, v in self.headers.items()},
            corps=corps,
        )
        serveur = self.server
        with serveur.verrou:
            serveur.requetes.append(requete)
        seul = self.path.split("?", 1)[0]
        reponse = serveur.routes.get(self.path, serveur.routes.get(seul))
        if reponse is None:
            reponse = serveur.defaut
        if callable(reponse):
            reponse = reponse(requete)
        statut, entetes, contenu = reponse
        if isinstance(contenu, str):
            contenu = contenu.encode("utf-8")
        try:
            self.send_response(statut)
            for nom, valeur in (entetes or {}).items():
                self.send_header(nom, valeur)
            self.send_header("Content-Length", str(len(contenu)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(contenu)
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = _servir
    do_POST = _servir
    do_HEAD = _servir


class FauxOdoo:
    """Le serveur, en gestionnaire de contexte. Voir l'en-tête."""

    def __init__(self, routes=None, defaut=(404, {}, "not found")):
        self._httpd = http.server.ThreadingHTTPServer((HOTE, 0), _Gestionnaire)
        self._httpd.daemon_threads = True
        self._httpd.routes = dict(routes or {})
        self._httpd.defaut = defaut
        self._httpd.requetes = []
        self._httpd.verrou = threading.Lock()
        # `shutdown()` attend la fin d'une période de sondage : 0,01 s au
        # lieu de 0,5 s par défaut.
        self._fil = threading.Thread(
            target=self._httpd.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )

    @property
    def port(self):
        return self._httpd.server_address[1]

    @property
    def url(self):
        return f"http://{HOTE}:{self.port}"

    @property
    def routes(self):
        return self._httpd.routes

    @property
    def requetes(self):
        with self._httpd.verrou:
            return list(self._httpd.requetes)

    def chemins(self):
        """Les chemins reçus, requête comprise, dans l'ordre."""
        return [r.chemin for r in self.requetes]

    def __enter__(self):
        self._fil.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._fil.join(timeout=5)
        return False
