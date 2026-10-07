"""Mise en place et etat d'Asterisk, vus depuis le CLI.

Le script d'installation vit dans script/install/install_asterisk.sh et
porte toute la logique. Ce module ne fait que l'appeler et lire l'etat :
dupliquer la configuration ici produirait deux verites qui divergeraient.
"""
import os
import shutil
import subprocess

CHEMIN_SECRETS = "/etc/erplibre/asterisk.env"


def _run(args, timeout=30):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return 1, str(e)


def installe():
    return shutil.which("asterisk") is not None


def actif():
    code, sortie = _run(["systemctl", "is-active", "asterisk"])
    return sortie.strip() == "active"


def chemin_script():
    return os.path.realpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "..", "install", "install_asterisk.sh")
    )


def lignes_configurees():
    """Noms des endpoints declares, lus dans pjsip.conf.

    On lit le fichier plutot que d'interroger Asterisk : ca fonctionne meme
    quand le service est arrete, ce qui est justement le moment ou l'on
    cherche a savoir ce qui est configure.
    """
    chemin = "/etc/asterisk/pjsip.conf"
    if not os.path.isfile(chemin):
        return []
    noms = []
    try:
        with open(chemin, encoding="utf-8", errors="ignore") as f:
            for ligne in f:
                s = ligne.strip()
                if s.startswith("[") and s.endswith("]"):
                    nom = s[1:-1]
                    if nom not in noms and nom != "transport-udp" \
                       and not nom.endswith("-auth"):
                        noms.append(nom)
    except OSError:
        return []
    return noms


def etat_endpoints():
    """Etat vu par Asterisk lui-meme. Vide si le service est arrete."""
    if not actif():
        return []
    code, sortie = _run(["sudo", "-n", "asterisk", "-rx", "pjsip show endpoints"])
    if code != 0:
        return []
    return [l for l in sortie.splitlines() if l.strip().startswith("Endpoint:")]


def secrets_poses():
    return os.path.isfile(CHEMIN_SECRETS)
