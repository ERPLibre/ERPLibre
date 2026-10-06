"""Regle udev qui reserve un port AT du modem a ERPLibre.

ModemManager tient les deux ports AT du modem. Sans cette regle, chaque
commande AT exige de l'arreter — ce qui coupe la connexion de donnees et
demande sudo. Intenable pour un service qui appelle regulierement.

On reserve le port SECONDAIRE et on lui laisse le primaire : il continue
donc de fournir l'etat de la SIM, l'operateur, le signal et les SMS.

Le port se designe par ce que ModemManager en dit, non par un numero
d'interface USB : la composition des ports change d'une carte a l'autre.
Toute carte que ModemManager reconnait et qui expose deux ports AT est donc
candidate, a condition que son vendeur figure dans la regle.
"""
import glob
import os
import shlex
import subprocess

NOM = "99-erplibre-modem.rules"
CIBLE = "/etc/udev/rules.d/" + NOM
LIEN = "/dev/erplibre-modem-at"

#: Vendeurs USB dont ERPLibre reclame un port AT. ModemManager designe
#: LEQUEL ; cette liste dit seulement DE QUI, pour qu'un second modem sur le
#: meme hote garde les siens. Elle suit la regle du depot — les deux se
#: lisent ensemble, et `vendeur_borne()` dit si elles divergent.
VENDEURS = ("2c7c", "1e0e")

#: Ports serie derriere lesquels un modem se presente.
GABARITS_PORTS = ("/dev/ttyUSB*", "/dev/ttyACM*")


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


def _proprietes(chemin):
    """Rend les proprietes udev d'un peripherique, ou un dict vide."""
    try:
        r = subprocess.run(["udevadm", "info", "-q", "property", "-n", chemin],
                           capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {}
    if r.returncode != 0:
        return {}
    props = {}
    for ligne in r.stdout.splitlines():
        cle, _, valeur = ligne.partition("=")
        if cle:
            props[cle] = valeur
    return props


def ports_at():
    """Rend les ports AT que ModemManager reconnait, avec leur role.

    Chaque entree porte le peripherique, « primaire » ou « secondaire », et
    l'identifiant du vendeur. La liste est vide quand aucun modem n'est
    branche ou qu'aucune regle de ModemManager ne reconnait celui-ci — un
    modem inconnu de lui expose des ports serie dont rien ne dit le role.
    """
    roles = (("ID_MM_PORT_TYPE_AT_PRIMARY", "primaire"),
             ("ID_MM_PORT_TYPE_AT_SECONDARY", "secondaire"))
    trouves = []
    for gabarit in GABARITS_PORTS:
        for chemin in sorted(glob.glob(gabarit)):
            props = _proprietes(chemin)
            for cle, role in roles:
                if props.get(cle) == "1":
                    trouves.append({
                        "port": chemin,
                        "role": role,
                        "vendeur": props.get("ID_VENDOR_ID", ""),
                    })
    return trouves


def vendeur_borne(vendeur):
    """Le vendeur figure-t-il dans la liste que la regle accepte ?"""
    return vendeur.lower() in VENDEURS


def cause_absence_lien():
    """Pourquoi le lien reserve manque. Rend None quand il est la.

    Un lien absent a quatre causes distinctes, et confondre la carte a port
    AT unique avec la regle non posee envoie chercher au mauvais endroit.
    """
    if port_reserve():
        return None
    ports = ports_at()
    if not ports:
        return (
            "aucun port AT : le modem n'est pas branche, ou ModemManager"
            " ne reconnait pas cette carte."
        )
    secondaires = [p for p in ports if p["role"] == "secondaire"]
    if not secondaires:
        return (
            "cette carte n'expose qu'UN port AT (%s). ERPLibre ne le prend"
            " pas : ModemManager perdrait l'etat du modem." % ports[0]["port"]
        )
    inconnus = [p for p in secondaires if not vendeur_borne(p["vendeur"])]
    if len(inconnus) == len(secondaires):
        return (
            "vendeur %s absent de la regle. Elle borne sa portee a une liste"
            " pour ne pas reclamer le port d'un second modem ; ajouter cet"
            " identifiant a ATTRS{idVendor} suffit." % (inconnus[0]["vendeur"] or "inconnu")
        )
    if not posee():
        return "la regle n'est pas posee."
    return (
        "un port AT secondaire existe et la regle est posee : recharger"
        " udev, le lien se cree au prochain evenement."
    )


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
