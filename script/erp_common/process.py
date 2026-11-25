# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Processus d'une instance de développement : pid, port, journaux, état.

Un démon d'instance écrit son pid dans un fichier. L'état de l'instance se
lit dans ses fichiers pid, en quatre valeurs : running (tous les démons
vivent), stopped (aucun), half running (une partie seulement) et unknown
(un fichier pid présent mais illisible, qui ne prouve ni vie ni mort).

System est le seul point qui lance, signale ou interroge ; les tests en
passent un factice qui répond aux mêmes méthodes.
"""

import os
import socket
import subprocess
import urllib.request

# Un fichier pid présent mais illisible : ni vivant ni mort, inconnu.
UNREADABLE = -1

STATES = ("running", "stopped", "half running", "unknown")

# État interne -> libellé affiché (clé i18n). Des libellés propres aux
# instances : « running » et « stopped » existent déjà, accordés aux VM.
STATE_LABELS = {
    "running": "serving",
    "stopped": "instance not running",
    "half running": "half running: one daemon is down",
    "unknown": "unknown: a pid file is unreadable",
}


def port_is_free(port):
    """Vrai si un serveur peut écouter sur 127.0.0.1:`port` maintenant.

    SO_REUSEADDR, comme nginx et Apache : les connexions qu'un status vient
    d'ouvrir restent en TIME_WAIT sur le port après l'arrêt, et un bind
    sans l'option le croirait pris. Un autre serveur en écoute le prend
    toujours.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


class System:
    """Processus, ports et HTTP réels ; les tests en passent un factice.

    spawn lance `argv` détaché (nouvelle session, stdin fermé, sortie et
    erreurs ajoutées à `log`) et rend son pid ; call rend (code, sortie
    texte) ; alive dit vrai pour un pid qui existe, même d'un autre compte ;
    http_get rend au plus 64 Kio de la page, ou "" si elle ne répond pas.
    """

    def spawn(self, argv, log, env=None):
        with open(log, "ab") as out:
            proc = subprocess.Popen(
                argv,
                env=dict(os.environ, **env) if env else None,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return proc.pid

    def call(self, argv):
        r = subprocess.run(argv, capture_output=True, text=True)
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    def alive(self, pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def kill(self, pid, sig):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass

    def port_free(self, port):
        return port_is_free(port)

    def http_get(self, url):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return r.read(65536).decode("utf-8", "replace")
        except OSError:
            return ""

    def engine(self, moteur):
        """La fiche du moteur, relue : sudo et socket peuvent avoir changé."""
        from script.todo import container_runtime

        return container_runtime.etat(moteur)


def read_pid(path):
    """Le pid du fichier, None s'il n'existe pas, UNREADABLE s'il ne se lit
    pas : une absence dit « arrêté », un fichier abîmé ne dit rien."""
    try:
        with open(path, encoding="utf-8", errors="strict") as f:
            text = f.read().strip()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        return UNREADABLE
    return int(text) if text.isdigit() else UNREADABLE


def live_pid(path, system):
    """Le pid du fichier s'il est vivant selon `system`, None s'il est
    absent ou mort, UNREADABLE si le fichier ne se lit pas."""
    pid = read_pid(path)
    if pid == UNREADABLE:
        return UNREADABLE
    return pid if pid and system.alive(pid) else None


def state(pids):
    """L'état d'une instance à partir de ses démons (au moins un), chacun
    un pid vivant, None ou UNREADABLE (voir live_pid) : une valeur de
    STATES."""
    if UNREADABLE in pids:
        return "unknown"
    if all(pids):
        return "running"
    if any(pids):
        return "half running"
    return "stopped"


def tail_file(path, lines):
    """Les `lines` dernières lignes du fichier, None s'il ne se lit pas."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-lines:]
    except OSError:
        return None
