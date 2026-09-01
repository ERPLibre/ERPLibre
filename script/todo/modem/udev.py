"""Regle udev qui reserve un port AT du modem a ERPLibre.

ModemManager tient les deux ports AT du Quectel. Sans cette regle, chaque
commande AT exige de l'arreter — ce qui coupe la connexion de donnees et
demande sudo. Intenable pour un service qui appelle regulierement.

On reserve le port SECONDAIRE et on lui laisse le primaire : il continue
donc de fournir l'etat de la SIM, l'operateur, le signal et les SMS.
"""
import os
import shlex
import subprocess

NOM = "99-erplibre-modem.rules"
CIBLE = "/etc/udev/rules.d/" + NOM
LIEN = "/dev/erplibre-modem-at"


def source():
    return os.path.realpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "..", "config", NOM)
    )


def posee():
    return os.path.isfile(CIBLE)


def a_jour():
    """La regle posee correspond-elle a la source du depot ?

    On compare le CONTENU : une regle posee il y a des mois peut differer de
    celle du depot, et un ecart silencieux est pire qu'une absence.
    """
    if not posee():
        return False
    try:
        with open(source(), encoding="utf-8") as a, open(CIBLE, encoding="utf-8") as b:
            return a.read() == b.read()
    except OSError:
        return False


def port_reserve():
    """Le lien stable existe-t-il, et vers quoi pointe-t-il ?"""
    if not os.path.islink(LIEN):
        return None
    try:
        return os.path.realpath(LIEN)
    except OSError:
        return None


def poser():
    """Copie la regle et la recharge. Demande sudo."""
    src = source()
    if not os.path.isfile(src):
        return False, "regle introuvable dans le depot : " + src
    try:
        subprocess.run(["sudo", "-v"], timeout=120)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    # shlex.quote et non le repr de Python : ce dernier produit des
    # guillemets simples qui fonctionnent souvent, mais qui ne sont pas un
    # echappement shell — un chemin contenant une apostrophe casserait la
    # commande, silencieusement.
    # Le redemarrage de ModemManager n'est pas un supplement : il est
    # NECESSAIRE. Mesure sur cet appareil — poser la regle et declencher udev
    # applique bien ID_MM_PORT_IGNORE au port, mais ModemManager continue
    # d'afficher « ttyUSB3 (at) » et de le tenir. Il lit ces proprietes quand
    # il sonde un appareil, pas a chaud ; un port deja reclame le reste
    # jusqu'a ce qu'il resonde.
    script = (
        f"install -m 0644 {shlex.quote(src)} {shlex.quote(CIBLE)} && "
        "udevadm control --reload-rules && "
        "udevadm trigger --subsystem-match=tty --subsystem-match=sound && "
        "systemctl restart ModemManager"
    )
    try:
        r = subprocess.run(["sudo", "-n", "sh", "-c", script],
                           capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)
    if r.returncode != 0:
        return False, (r.stdout or "") + (r.stderr or "")
    return True, (
        "Regle posee, udev recharge, ModemManager redemarre. Le port"
        " /dev/erplibre-modem-at est desormais reserve : plus besoin"
        " d'arreter ModemManager pour parler au modem."
    )


def retirer():
    try:
        subprocess.run(["sudo", "-v"], timeout=120)
        r = subprocess.run(
            ["sudo", "-n", "sh", "-c",
             f"rm -f {shlex.quote(CIBLE)} && udevadm control --reload-rules"
             " && udevadm trigger --subsystem-match=tty"],
            capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return False, str(e)
    return r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def port_libre():
    """Le port reserve est-il REELLEMENT ouvrable ?

    Distinct de `port_reserve()`, qui ne dit que l'existence du lien. Mesure
    sur cet appareil : la regle peut etre posee, la propriete appliquee, le
    lien present — et ModemManager tenir encore le port parce qu'il l'avait
    reclame avant. Une regle « posee » n'est donc pas une preuve ; l'ouvrir
    en est une.
    """
    chemin = LIEN if os.path.islink(LIEN) else None
    if not chemin:
        return False, "lien absent"
    try:
        fd = os.open(chemin, os.O_RDWR | os.O_NONBLOCK)
    except PermissionError:
        return False, "droits insuffisants (groupe dialout ?)"
    except OSError as e:
        return False, str(e)
    os.close(fd)
    return True, "port ouvrable"
