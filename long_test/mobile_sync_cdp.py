#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le WebView de l'app de test, par le protocole devtools de Chrome (CDP).

adb transfère un port local vers la socket devtools du processus de l'app
(webview_devtools_remote_<pid>) ; Cdp y évalue du JavaScript dans la page et
rend la valeur. Une exception de la page lève ErreurPage, avec son texte.

  python3 long_test/mobile_sync_cdp.py 9333 "document.title"
"""

import json
import sys
import time
import urllib.request

import websocket


class ErreurPage(RuntimeError):
    """Une évaluation que la page a refusée : son exception, en texte."""


class Cdp:
    """Une connexion à la page de l'app ; evaluer() attend les promesses."""

    def __init__(self, port, delai=120):
        pages = json.load(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=10)
        )
        page = next(p for p in pages if p["type"] == "page")
        # suppress_origin : le WebView refuse une connexion qui annonce une origine
        self.ws = websocket.create_connection(
            page["webSocketDebuggerUrl"], timeout=delai, suppress_origin=True
        )
        self.suivant = 0

    def envoyer(self, methode, params):
        """Une commande CDP, et sa réponse."""
        self.suivant += 1
        self.ws.send(
            json.dumps(
                {"id": self.suivant, "method": methode, "params": params}
            )
        )
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") != self.suivant:
                continue
            if "error" in message:
                raise ErreurPage(
                    f"{methode} : {message['error'].get('message')}"
                )
            return message["result"]

    def evaluer(self, expression):
        resultat = self.envoyer(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
        )
        if "exceptionDetails" in resultat:
            details = resultat["exceptionDetails"]
            texte = details.get("exception", {}).get(
                "description"
            ) or details.get("text")
            raise ErreurPage(texte)
        return resultat["result"].get("value")

    def toucher(self, selecteur, duree=0.05):
        """Un doigt posé au centre du premier élément de selecteur, levé
        après duree secondes (1,4 : un appui long). Les événements sont ceux
        d'un vrai toucher : un gestionnaire qui ignore un clic simulé les
        reçoit."""
        x, y = self.evaluer(
            f"(() => {{ const e = document.querySelector({json.dumps(selecteur)});"
            " if (!e) throw new Error('absent : ' + "
            + json.dumps(selecteur)
            + ");"
            " e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect();"
            " return [r.x + r.width / 2, r.y + r.height / 2]; })()"
        )
        point = [{"x": x, "y": y}]
        self.envoyer(
            "Input.dispatchTouchEvent",
            {"type": "touchStart", "touchPoints": point},
        )
        time.sleep(duree)
        self.envoyer(
            "Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []}
        )

    def taper(self, texte):
        """texte inséré à la position du curseur, comme un clavier l'écrit."""
        self.envoyer("Input.insertText", {"text": texte})

    def attendre(self, expression, delai=30, pas=0.3):
        """La première valeur vraie de expression, réévaluée tous les pas ;
        TimeoutError après delai secondes, avec la dernière valeur."""
        fin = time.monotonic() + delai
        valeur = None
        while time.monotonic() < fin:
            valeur = self.evaluer(expression)
            if valeur:
                return valeur
            time.sleep(pas)
        raise TimeoutError(
            f"{expression} : toujours {valeur!r} après {delai} s"
        )

    def fermer(self):
        self.ws.close()


if __name__ == "__main__":
    print(
        json.dumps(
            Cdp(int(sys.argv[1])).evaluer(sys.argv[2]),
            ensure_ascii=False,
            indent=1,
        )
    )
