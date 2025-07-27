import http.server
import http.client
import socketserver
import threading
import urllib.parse
import gzip
import io

# --- Configuration du proxy ---
# Adresse IP et ports de ton serveur Odoo
ODOO_HOST = '127.0.0.1'
ODOO_PORT_WEB = 8069
ODOO_PORT_CHAT = 8072

# Le port sur lequel ton mini-proxy va écouter
PROXY_PORT = 8080

# Les chemins d'URL qui doivent être redirigés vers le port de chat (8072)
CHAT_PATHS = ['/websocket']


# --- Fin de la configuration ---

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    # Les types de compression à gérer (pour la partie gzip)
    GZIP_TYPES = [
        'text/css', 'text/less', 'text/plain', 'text/xml', 'application/xml',
        'application/json', 'application/javascript', 'application/pdf',
        'image/jpeg', 'image/png'
    ]

    def _get_target_port(self):
        """Détermine le port de destination en fonction de l'URL de la requête."""
        path = self.path.split('?')[0]  # On ignore les paramètres d'URL pour la comparaison
        print(path)
        if any(path.startswith(p) for p in CHAT_PATHS):
            print("mathben")
            return ODOO_PORT_CHAT
        return ODOO_PORT_WEB

    def _handle_proxy(self):
        """Gère la redirection de la requête vers Odoo."""
        target_port = self._get_target_port()

        # Ouvre la connexion HTTP vers Odoo
        conn = http.client.HTTPConnection(ODOO_HOST, target_port, timeout=720)

        try:
            # On prépare les en-têtes de la requête.
            headers = dict(self.headers)

            # Ajout des en-têtes importants pour qu'Odoo fonctionne en mode proxy
            headers['X-Forwarded-Host'] = self.headers.get('Host', '')
            headers['X-Forwarded-For'] = self.headers.get('X-Forwarded-For', '') + (
                ', ' + self.client_address[0] if self.client_address else '')
            headers['X-Forwarded-Proto'] = 'http'  # Simplifié, car ce script ne gère pas le HTTPS
            headers['X-Real-IP'] = self.client_address[0] if self.client_address else ''

            # Gère les en-têtes pour les websockets
            if 'Upgrade' in headers and headers['Upgrade'] == 'websocket':
                headers['Connection'] = 'upgrade'

            # Lit le corps de la requête s'il y en a un
            content_length = int(headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            # Envoie la requête à Odoo
            conn.request(self.command, self.path, body=body, headers=headers)

            # Récupère la réponse d'Odoo
            response = conn.getresponse()

            # --- Traitement de la réponse ---
            # Gère la compression si l'en-tête gzip est présent
            content_encoding = response.getheader('Content-Encoding', '')
            if 'gzip' in content_encoding:
                # Ouvre le flux pour décompresser la réponse
                compressed_file = gzip.GzipFile(fileobj=io.BytesIO(response.read()))
                response_body = compressed_file.read()
                # Supprime l'en-tête de compression pour éviter les erreurs
                response.headers.pop('Content-Encoding', None)
                # Met à jour la taille du contenu
                response.headers['Content-Length'] = str(len(response_body))
            else:
                response_body = response.read()

            # Envoie les en-têtes de la réponse au client
            self.send_response(response.status)
            for header, value in response.getheaders():
                self.send_header(header, value)
            self.end_headers()

            # Envoie le corps de la réponse au client
            self.wfile.write(response_body)

        except Exception as e:
            print(f"Erreur de proxy : {e}")
            self.send_error(500, f"Erreur de proxy : {e}")
        finally:
            conn.close()

    def do_GET(self):
        self._handle_proxy()

    def do_POST(self):
        self._handle_proxy()

    def do_PUT(self):
        self._handle_proxy()

    def do_DELETE(self):
        self._handle_proxy()

    def do_HEAD(self):
        self._handle_proxy()


class ThreadedTCPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    pass


def start_proxy_server():
    server_address = (ODOO_HOST, PROXY_PORT)
    with ThreadedTCPServer(server_address, ProxyHandler) as httpd:
        print(f"Démarrage du mini-proxy Python sur le port {PROXY_PORT}...")
        print(
            f"Redirection des requêtes Odoo vers {ODOO_HOST}:{ODOO_PORT_WEB} et {ODOO_HOST}:{ODOO_PORT_CHAT} pour les chemins spéciaux.")
        httpd.serve_forever()


if __name__ == "__main__":
    start_proxy_server()
