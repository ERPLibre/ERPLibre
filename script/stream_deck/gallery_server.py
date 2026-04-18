#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Local web server for the Stream Deck game gallery.

Serves index.html and handles /launch/<game_id> requests
to start games in a terminal. Kills previous game terminal
before opening a new one.

Usage: python3 gallery_server.py
Then open http://localhost:8042
"""

import http.server
import json
import os
import signal
import subprocess
import sys
import webbrowser

PORT = 8042
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ERPLIBRE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

# Track the current game process
_current_game_proc = None


def _kill_current_game():
    """Kill the currently running game terminal if any."""
    global _current_game_proc
    if _current_game_proc is not None:
        try:
            # Send SIGTERM to the process group (terminal + children)
            pgid = os.getpgid(_current_game_proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        try:
            _current_game_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                pgid = os.getpgid(_current_game_proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
        _current_game_proc = None


class GameHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SCRIPT_DIR, **kwargs)

    def do_GET(self):
        if self.path.startswith("/launch/"):
            game_id = self.path.split("/launch/")[1].strip("/")
            self._launch_game(game_id)
            return
        if self.path == "/stop":
            self._stop_game()
            return
        if self.path == "/api/saves":
            self._list_saves()
            return
        if self.path.startswith("/api/saves/delete/"):
            filename = self.path.split("/api/saves/delete/")[1].strip("/")
            self._delete_save(filename)
            return
        if self.path.startswith("/api/saves/clear-game/"):
            game_id = self.path.split("/api/saves/clear-game/")[1].strip("/")
            self._clear_game_saves(game_id)
            return
        if self.path == "/api/saves/clear-all":
            self._clear_all_saves()
            return
        super().do_GET()

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _list_saves(self):
        """List all saved files in save/ directory."""
        save_dir = os.path.join(SCRIPT_DIR, "save")
        files = []
        if os.path.isdir(save_dir):
            for f in sorted(os.listdir(save_dir)):
                if f.startswith("."):
                    continue
                path = os.path.join(save_dir, f)
                size = os.path.getsize(path)
                mtime = os.path.getmtime(path)
                ftype = "json" if f.endswith(".json") else "wav" if f.endswith(".wav") else "other"
                game = "djscratch" if "djscratch" in f or f.startswith("rec_") or f.startswith("sample_") or f.startswith("_mic") else "unknown"
                files.append({
                    "name": f,
                    "size": size,
                    "mtime": mtime,
                    "type": ftype,
                    "game": game,
                })
        total_size = sum(f["size"] for f in files)
        self._json_response({
            "files": files,
            "count": len(files),
            "total_size": total_size,
        })

    def _delete_save(self, filename):
        """Delete a specific save file."""
        save_dir = os.path.join(SCRIPT_DIR, "save")
        path = os.path.join(save_dir, os.path.basename(filename))
        if os.path.isfile(path) and not filename.startswith("."):
            os.remove(path)
            print(f"Deleted: {path}")
            self._json_response({"ok": True, "deleted": filename})
        else:
            self._json_response({"error": "File not found"}, 404)

    def _match_game(self, filename, game_id):
        """Check if a save file belongs to a game."""
        patterns = {
            "djscratch": [
                "djscratch", "rec_", "sample_", "_mic",
            ],
        }
        pats = patterns.get(game_id, [game_id])
        for p in pats:
            if p in filename:
                return True
        return False

    def _clear_game_saves(self, game_id):
        """Delete all save files for a specific game."""
        save_dir = os.path.join(SCRIPT_DIR, "save")
        count = 0
        if os.path.isdir(save_dir):
            for f in os.listdir(save_dir):
                if f.startswith("."):
                    continue
                if self._match_game(f, game_id):
                    path = os.path.join(save_dir, f)
                    if os.path.isfile(path):
                        os.remove(path)
                        count += 1
        print(f"Cleared {count} files for game: {game_id}")
        self._json_response({"ok": True, "deleted_count": count, "game": game_id})

    def _clear_all_saves(self):
        """Delete all save files."""
        save_dir = os.path.join(SCRIPT_DIR, "save")
        count = 0
        if os.path.isdir(save_dir):
            for f in os.listdir(save_dir):
                if f.startswith("."):
                    continue
                path = os.path.join(save_dir, f)
                if os.path.isfile(path):
                    os.remove(path)
                    count += 1
        print(f"Cleared {count} save files")
        self._json_response({"ok": True, "deleted_count": count})

    def _stop_game(self):
        """Stop the current game."""
        _kill_current_game()
        self._json_response({"ok": True})

    def _launch_game(self, game_id):
        global _current_game_proc

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

        # Kill previous game first
        _kill_current_game()

        print(f"Launching game: {game_id}")
        try:
            # --wait keeps gnome-terminal process alive until window closes
            _current_game_proc = subprocess.Popen(
                [
                    "gnome-terminal",
                    "--wait",
                    "--",
                    "bash",
                    "-c",
                    f"cd {ERPLIBRE_DIR} && python3 {game_file}; "
                    f'echo ""; echo "Game ended. Press enter to close..."; read',
                ],
                preexec_fn=os.setsid,
            )
            status = {"ok": True, "game": game_id}
        except FileNotFoundError:
            try:
                _current_game_proc = subprocess.Popen(
                    [
                        "xterm",
                        "-e",
                        f"cd {ERPLIBRE_DIR} && python3 {game_file}; "
                        f'echo "Game ended."; read',
                    ],
                    preexec_fn=os.setsid,
                )
                status = {"ok": True, "game": game_id}
            except FileNotFoundError:
                status = {
                    "error": "No terminal found (tried gnome-terminal, xterm)"
                }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(status).encode())

    def log_message(self, format, *args):
        if "/launch/" in str(args) or "/stop" in str(args):
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
        _kill_current_game()
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
