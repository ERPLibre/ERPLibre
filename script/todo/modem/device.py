"""Acces au modem : ModemManager pour l'etat, AT pour ce qu'il ne dit pas.

ModemManager tient les ports AT en permanence. Deux consequences qui
gouvernent tout ce fichier : on lui demande l'etat plutot que d'ouvrir un
port, et toute commande AT exige de l'ecarter le temps de la poser — donc
sudo, donc un geste explicite et jamais implicite.
"""
import getpass
import grp
import os
import re
import shlex
import shutil
import subprocess
import sys

#: Port que la regle udev soustrait a ModemManager. Quand il existe, tout le
#: reste de ce fichier devient inutile : on l'ouvre directement.
PORT_RESERVE = "/dev/erplibre-modem-at"

#: Le port du modem est en 0660 root:dialout.
GROUPE_PORT = "dialout"

#: Ports AT du modem, dans l'ordre ou on les essaie a defaut du port reserve.
PORTS_AT = ("/dev/ttyUSB2", "/dev/ttyUSB3")

#: Au-dela, on considere que le modem ne repondra pas.
DELAI_AT = 15


def groupe_absent_du_processus():
    """Rend True si l'utilisateur a le groupe du port mais pas ce processus.

    La liste des groupes se fige a l'ouverture de session : ajouter
    l'utilisateur a « dialout » ne touche pas les processus deja lances, qui
    gardent la liste heritee. L'ouverture echoue alors sur « permission
    denied » alors qu'« id » montre le bon groupe — il lit /etc/group, pas le
    processus.
    """
    try:
        entree = grp.getgrnam(GROUPE_PORT)
    except KeyError:
        return False
    if entree.gr_gid in os.getgroups() or entree.gr_gid == os.getgid():
        return False
    return getpass.getuser() in entree.gr_mem


def avec_groupe(args):
    """Rend la commande, relancee par « sg » si le groupe manque au processus.

    Evite d'exiger une reouverture de session apres l'ajout au groupe. « sg »
    prend la commande entiere dans un seul argument, d'ou le shlex.join.
    """
    if groupe_absent_du_processus() and shutil.which("sg"):
        return ["sg", GROUPE_PORT, "-c", shlex.join(args)]
    return args


def port_reserve():
    """Rend le port soustrait a ModemManager, ou None s'il n'est pas pose."""
    return PORT_RESERVE if os.path.exists(PORT_RESERVE) else None


def mmcli_present():
    return shutil.which("mmcli") is not None


def _run(args, timeout=20):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return 1, str(e)


def liste_modems():
    """Chemins des modems vus par ModemManager."""
    if not mmcli_present():
        return []
    code, sortie = _run(["mmcli", "-L"])
    if code != 0:
        return []
    return re.findall(r"/org/freedesktop/ModemManager1/Modem/(\d+)", sortie)


def premier_modem():
    modems = liste_modems()
    return modems[0] if modems else None


def etat(index):
    """Etat lisible du modem : modele, SIM, reseau, signal.

    On renvoie un dictionnaire plutot que du texte : l'appelant decide de la
    presentation, et un test peut verifier une valeur sans analyser un
    affichage.
    """
    code, sortie = _run(["mmcli", "-m", str(index)])
    if code != 0:
        return {}
    champs = {
        "modele": r"model:\s*(.+)",
        "firmware": r"firmware revision:\s*(\S+)",
        "imei": r"equipment id:\s*(\S+)",
        "etat": r"^\s*\|\s*state:\s*(\S+)",
        "signal": r"signal quality:\s*(\d+)%",
        "operateur": r"operator name:\s*(.+)",
        "numero": r"own:\s*(\S+)",
        "technologie": r"access tech:\s*(\S+)",
    }
    res = {}
    for cle, motif in champs.items():
        m = re.search(motif, sortie, re.M)
        if m:
            res[cle] = m.group(1).strip()
    return res


def commande_at(commandes, port=None):
    """Pose des commandes AT. Renvoie (ok, texte).

    Deux voies, et la premiere est de loin preferable :

    - le port reserve par la regle udev, ouvert directement, sans sudo et
      sans toucher a ModemManager ;
    - a defaut, un port que ModemManager tient : il faut alors l'arreter le
      temps de poser les commandes, donc sudo. On le relance dans tous les
      cas, erreur comprise — le laisser arrete couperait la connexion de
      donnees sans que personne comprenne pourquoi, et le modem disparait des
      listes le temps qu'il resonde.
    """
    cible = port or port_reserve() or PORTS_AT[0]
    if cible == PORT_RESERVE:
        # Voie directe : la regle udev a deja ecarte ModemManager de ce port.
        # Ni sudo ni arret de service, donc ni coupure de la connexion de
        # donnees ni modem absent des listes pendant qu'il resond.
        aide = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "at_direct.py")
        args = avec_groupe([sys.executable, aide, cible] + list(commandes))
        code, sortie = _run(args, timeout=DELAI_AT + 10)
        return code == 0, sortie.replace("\r", "")
    sequence = "; ".join(
        'printf "%s\\r\\n" {} >&3; sleep 1'.format(_shq(c)) for c in commandes
    )
    script = (
        "systemctl stop ModemManager; sleep 2; "
        f"stty -F {cible} 115200 raw -echo; "
        f"exec 3<>{cible}; {sequence}; "
        "timeout 3 cat <&3; "
        "systemctl start ModemManager"
    )
    # `sudo -v` D'ABORD, sans capturer : il herite du terminal et peut donc
    # demander le mot de passe. L'appel suivant capture la sortie, ce qui
    # prive sudo de terminal — avec `-n` seul, il ne demandait jamais rien et
    # echouait donc systematiquement, y compris dans le terminal de
    # l'utilisatrice.
    try:
        subprocess.run(["sudo", "-v"], timeout=120)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    code, sortie = _run(["sudo", "-n", "sh", "-c", script], timeout=DELAI_AT + 20)
    if "mot de passe" in sortie or "a password is required" in sortie.lower():
        return False, (
            "sudo n'a pas pu obtenir les droits. Relancez la commande, ou"
            " posez une regle sudo pour systemctl et stty."
        )
    return code == 0, sortie.replace("\r", "")


def _shq(texte):
    """Guillemets surs pour un shell. On n'utilise pas shlex : la chaine part
    dans un `sh -c` deja imbrique, et les regles d'echappement s'y empilent."""
    return "'" + str(texte).replace("'", "'\\''") + "'"
