"""Dialogue AT sur un port que ModemManager ne tient pas.

Script AUTONOME, lance dans un processus separe et jamais importe : c'est ce
qui permet de le relancer sous « sg » quand le processus appelant n'a pas
encore le groupe du port. Il n'a donc aucun import du paquet.

Sur le port reserve par la regle udev, aucun sudo n'est requis et
ModemManager continue de tourner — la ou le prendre de force a
« systemctl stop » coupe la connexion de donnees et fait disparaitre le
modem des listes le temps qu'il resonde.

Usage : at_direct.py <port> <commande AT> [commande AT...]
"""
import fcntl
import os
import select
import sys
import termios
import time

#: Au-dela, le modem est considere muet sur cette commande.
DELAI_REPONSE = 5.0

#: Code de sortie quand un autre programme tient le port. Distinct de 1 pour
#: que l'appelant sache que le modem n'est PAS en cause.
CODE_PORT_TENU = 3

#: Marque ecrite sur la sortie d'erreur dans ce cas, lisible sans le code.
MARQUE_PORT_TENU = "PORT_TENU"

VITESSE = termios.B115200


def ouvrir(port):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    attr = termios.tcgetattr(fd)
    # Mode brut pose a la main : le modem parle en octets, et une discipline
    # de ligne transformerait les CR en LF et avalerait l'echo.
    attr[0] = attr[1] = attr[3] = 0
    attr[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attr[4] = attr[5] = VITESSE
    termios.tcsetattr(fd, termios.TCSANOW, attr)
    return fd


def poser(fd, commande, delai=DELAI_REPONSE):
    """Envoie une commande et rend la reponse brute.

    S'arrete des que le modem a conclu par OK ou ERROR plutot que d'attendre
    le delai entier : une sequence de commandes serait sinon aussi lente que
    la somme des delais.
    """
    termios.tcflush(fd, termios.TCIOFLUSH)
    os.write(fd, (commande + "\r").encode())
    fin, tampon = time.monotonic() + delai, b""
    while time.monotonic() < fin:
        if select.select([fd], [], [], 0.2)[0]:
            try:
                tampon += os.read(fd, 4096)
            except BlockingIOError:
                pass
            if b"OK" in tampon or b"ERROR" in tampon:
                break
    return tampon.decode("utf-8", "replace")


def main(argv):
    if len(argv) < 3:
        print("usage : at_direct.py <port> <commande AT>...", file=sys.stderr)
        return 2
    port, commandes = argv[1], argv[2:]
    try:
        fd = ouvrir(port)
    except OSError as e:
        print(f"{port} : {e}", file=sys.stderr)
        return 1
    # Le MEME verrou que le service erplibre-sip-go. Un port serie s'ouvre
    # autant de fois qu'on veut sans rien signaler : sans ce verrou, les
    # commandes posees ici s'entrelaceraient avec celles du service, et une
    # reponse partirait vers l'autre programme.
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        print(f"{MARQUE_PORT_TENU} : {port} est tenu par un autre programme"
              " (le service erplibre-sip-go ?)", file=sys.stderr)
        return CODE_PORT_TENU
    try:
        erreur = False
        for c in commandes:
            reponse = poser(fd, c)
            sys.stdout.write(reponse.replace("\r", ""))
            if "ERROR" in reponse:
                erreur = True
        return 1 if erreur else 0
    finally:
        os.close(fd)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
