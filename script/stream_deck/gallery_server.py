#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Local web server for the Stream Deck game gallery.

Serves index.html and handles /launch/<game_id> requests
to start games in a terminal.

Usage: python3 gallery_server.py
Then open http://localhost:8042
"""

import http.server
import json
import os
import subprocess
import sys
import webbrowser

PORT = 8042
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ERPLIBRE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))


class GameHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SCRIPT_DIR, **kwargs)

    def do_GET(self):
        if self.path.startswith("/launch/"):
            game_id = self.path.split("/launch/")[1].strip("/")
            self._launch_game(game_id)
            return
        super().do_GET()

    def _launch_game(self, game_id):
        game_file = os.path.join(SCRIPT_DIR, f"game_{game_id}.py")
        if not os.path.isfile(game_file):
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": f"Game not found: {game_id}"}).encode()
            )
            return

        print(f"Launching game: {game_id}")
        try:
            subprocess.Popen(
                [
                    "gnome-terminal",
                    "--",
                    "bash",
                    "-c",
                    f"cd {ERPLIBRE_DIR} && python3 {game_file}; "
                    f'echo ""; echo "Game ended. Press enter to close..."; read',
                ],
            )
            status = {"ok": True, "game": game_id}
        except FileNotFoundError:
            # Fallback: try xterm or just run in background
            try:
                subprocess.Popen(
                    [
                        "xterm",
                        "-e",
                        f"cd {ERPLIBRE_DIR} && python3 {game_file}; "
                        f'echo "Game ended."; read',
                    ],
                )
                status = {"ok": True, "game": game_id}
            except FileNotFoundError:
                status = {
                    "error": "No terminal emulator found (tried gnome-terminal, xterm)"
                }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(status).encode())

    def log_message(self, format, *args):
        if "/launch/" in str(args):
            super().log_message(format, *args)


def main():
    handler = GameHandler
    with http.server.HTTPServer(("", PORT), handler) as httpd:
        url = f"http://localhost:{PORT}"
        print(f"Stream Deck Game Gallery: {url}")
        print("Press Ctrl+C to stop.")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
