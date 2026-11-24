#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Chaque bureau de la matrice s'installe-t-il et s'ouvre-t-il à distance ?

Une VM par couple (saveur, distribution, version) de
TODO._QEMU_DESKTOP_RELEASES — toute la table par défaut, soit environ
soixante-dix machines et quatre heures à quatre en parallèle. Chacune est
déployée, reçoit son bureau, REDÉMARRE, puis est jugée depuis l'hôte. Il vit
dans « long_test/ » et non dans « test/ » : il crée de vraies VM.

CE QU'IL ENVOIE EST CE QUE LE MENU ENVOIE

La commande de déploiement sort de TODO._qemu_build_deploy_parts, la
commande distante de TODO._qemu_erplibre_remote_cmd (le chemin « bureau
seul » du menu), le mot de passe en clair de GNOME de vm_login_push_cmd. Un
test qui composerait les siennes prouverait SON chemin, pas celui du produit.
Seul ajout : « --no-git-identity », une VM de test n'ayant pas à porter
l'identité git de l'hôte. Le fuseau et la locale sont ceux que reçoit une
VM du formulaire du menu : le fuseau de l'hôte par _qemu_host_timezone, la
locale par défaut de deploy_qemu.py, que le formulaire ne fixe pas.

APRÈS UN REDÉMARRAGE, ET DEPUIS L'HÔTE

Ce qui doit tenir au démarrage — gestionnaire d'affichage, ouverture
automatique, verrou, serveur distant — se juge sur une VM qui vient de
démarrer, et l'accès distant se juge depuis l'hôte, pare-feu de la VM
compris. Le client RDP tourne dans un conteneur podman (Xvfb + FreeRDP 3),
construit depuis qemu_desktops_client/Containerfile ; les serveurs RFB sont
joints par qemu_desktops_image.

CE QUI EST JUGÉ, ET CE QUI NE L'EST PAS

* le déploiement, cloud-final, le code de retour de l'installation et ses
  « ⚠ » — le rc 4 de nixos-rebuild, qui annonce un dbus-broker non rechargé
  à chaud, est excusé pour cette seule cause ;
* le redémarrage (ssh revenu, adresse inchangée — une adresse qui change
  fait échouer la VM), le gestionnaire d'affichage actif, les unités en
  échec hors EXCUSES_UNITES — toute autre unité en échec fait échouer la
  VM —, les sessions
  du seat0 (ouverture automatique et LockedHint pour KRdp, hyprlock pour
  wayvnc), le port qui écoute et celui que /etc/motd annonce ;
* la console QEMU, capturée telle que l'utilisateur la voit : ses teintes
  sont notées, pas jugées ;
* l'accès distant : xrdp et KRdp par une VRAIE connexion — bon mot de passe
  accepté sans échec PAM au journal, mauvais refusé avec un échec PAM, image
  jugée à ses teintes ; GNOME Remote Desktop par « /auth-only » sauf quand
  xrdp le sert (son repli), qui n'a pas de NLA et accepterait tout mot de
  passe à ce niveau ; wayvnc et TigerVNC par VeNCrypt, l'image du bon mot
  de passe jugée à ses teintes comme celle de RDP ; pour KRdp sur
  Fedora et EL, quatre échecs puis le bon mot de passe, que pam_faillock ne
  doit pas bloquer.

Le processus de session se cherche dans une liste « ps » jugée sur l'hôte,
par le nom de l'exécutable : un « pgrep -f » lancé par ssh se trouve
lui-même dans la ligne de commande du shell qui le porte.

  ./long_test/qemu_desktops.py                          # toute la matrice
  ./long_test/qemu_desktops.py --dry-run                # le plan seul
  ./long_test/qemu_desktops.py --saveurs plasma --distros fedora,rocky
  ./long_test/qemu_desktops.py --parallele 2 --garder   # VM gardées
  ./long_test/qemu_desktops.py --bilan DOSSIER          # tableau relu
  ./long_test/qemu_desktops.py --detruire               # défaire
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "long_test"))

import qemu_desktops_image as image  # noqa: E402
from descente import CACHE_CA, capacite_hote, cle_publique, dire  # noqa: E402

OUTIL = "qemu_desktops"
SCRIPT = "qemu_desktops.py"
PREFIXE = "ldesk"
URI = "qemu:///system"

# Le compte que le déploiement crée, et son mot de passe. Les deux valent
# pour le client RDP du conteneur, qui se connecte sous ce compte.
COMPTE = "erplibre"
MOT_DE_PASSE = "erplibre"
MAUVAIS_MOT_DE_PASSE = "pas-le-mot-de-passe"

# Le plancher de RAM d'un bureau (QEMU_DESKTOP_MIN_RAM_MB) ; le catalogue
# l'emporte s'il demande davantage.
MEMOIRE_MO = 4096
VCPUS = 4
PARALLELE = 4

# Ce que l'hôte garde pour lui et pour le surcoût de QEMU au-delà de la
# mémoire nominale des VM : sans cette marge, des VM dont la somme égale la
# mémoire disponible la consomment toute.
MARGE_HOTE_MO = 4096

# Ce que l'installation d'un bureau écrit dans le qcow2, en ordre de
# grandeur : sert à prévenir quand l'hôte ne peut pas garder les VM.
DISQUE_ECRIT_GO = 12

IMAGE_CLIENT = "erplibre-rdpclient"
DOSSIER_CLIENT = os.path.join(RACINE, "long_test", "qemu_desktops_client")
# L'étiquette de l'image client qui porte l'empreinte du Containerfile dont
# elle sort : une image construite d'un autre Containerfile se reconstruit.
ETIQUETTE_CLIENT = "erplibre.containerfile"
DOSSIER = os.path.expanduser("~/.erplibre/longtest")

# Sous ce nombre de teintes, l'image RDP ou VNC est un écran noir, uni, ou la
# seule boîte de connexion d'xrdp (1 à 16 teintes) ; un bureau rendu, même
# sombre, en compte des centaines. L'écran de hyprlock servi par wayvnc est
# un fond uni, curseur compris, de 1 à quelques dizaines de teintes : il ne se
# juge pas à ce seuil (_raisons_vnc).
TEINTES_MIN = 32

# Unités en échec qui ne disent rien du bureau. mcelog lit les erreurs
# machine d'un processeur physique, qu'une VM n'expose pas : il échoue au
# démarrage tant que le déploiement ne le masque pas, et ne peut plus
# échouer une fois masqué. Une entrée se retire quand sa cause disparaît.
EXCUSES_UNITES = {
    "mcelog.service": "sans objet dans une VM (pas d'erreurs machine)",
}

# Écarts attendus d'une combinaison : la clé de raison du verdict qu'ils
# excusent, et pourquoi. Le verdict les montre en note au lieu d'échouer.
ATTENDUS = {
    ("opensuse", "16.0", "i3"): {
        "image": "Leap 16 n'a pas i3status : l'écran i3 n'a pas de barre,"
        " donc presque aucune teinte",
    },
}

# Les distributions où KRdp passe par pam_faillock : quatre échecs ne
# doivent pas bloquer le bon mot de passe qui suit.
DISTROS_FAILLOCK = ("fedora", "almalinux", "rocky")

# L'exécutable qui VIT pendant une session X : x_session peut n'être qu'un
# lanceur (startxfce4 passe la main à xfce4-session).
PROCESSUS_SESSION = {
    "xfce": ("xfce4-session",),
    "cinnamon": ("cinnamon-session", "cinnamon-session-binary"),
    "i3": ("i3",),
    "plasma": ("plasmashell",),
    "gnome": ("gnome-shell",),
}

# Marques d'un refus de mot de passe au journal de l'invité. Pas
# « auth.*fail » : les agents polkit (« authentication-agent-1 … Failed to
# register ») le déclenchent sans qu'aucun mot de passe soit en jeu.
MOTIF_ECHEC_PAM = re.compile(
    r"pam_unix\([^)]*:auth\): authentication failure|AUTHFAIL:"
    r"|pam_authenticate fail|op=PAM:authentication .*res=failed"
    r"|LOGON_FAILURE|Invalid username or password",
    re.I,
)

DELAIS = {
    "deploiement": 1800,
    "ip": 600,
    "ssh": 600,
    "cloud_final": 1900,
    "installation": 7200,
    "reboot_ssh": 300,
    "commande": 180,
}

# Après le retour de ssh, ce que le démarrage graphique prend encore :
# ouverture automatique, verrou, serveur distant.
STABILISATION = 75
# Plasma éteint un écran verrouillé au bout d'une minute ; KRdp se juge
# au-delà, l'écran éteint étant le cas que son réveil doit couvrir.
ATTENTE_KRDP = 60

SONDE_INVITE = """
echo "== dm"
systemctl show -p Id --value display-manager.service
systemctl is-active display-manager.service
echo "== failed"
systemctl --failed --no-legend --plain
echo "== sessions"
for s in $(loginctl list-sessions --no-legend | awk '{print $1}'); do
  echo "$s $(loginctl show-session "$s" -p Name -p Type -p Class -p Seat \
    -p State -p LockedHint -p Service | tr '\\n' ' ')"
done
echo "== ps"
ps -eo user:32=,args=
echo "== listen"
sudo ss -ltnpH
echo "== motd"
cat /etc/motd 2>/dev/null
"""

_VERROU_JOURNAL = threading.Lock()
_VERROU_RAPPORT = threading.Lock()


# --------------------------------------------------------------------------
# Fonctions pures : matrice, lecture des sorties, verdict, bilan
# --------------------------------------------------------------------------


def liste_option(valeur):
    """« a,b , c » -> ["a", "b", "c"] ; vide -> []."""
    return [v.strip() for v in (valeur or "").split(",") if v.strip()]


def matrice(releases, saveurs=(), distros=(), versions=()):
    """[(distro, version, saveur)] de la table `releases`, triée.

    `releases` a la forme de _QEMU_DESKTOP_RELEASES : {saveur: {distro:
    (versions)}}. Chaque filtre vide laisse tout passer. Un nom absent de la
    table lève ValueError : le refus tombe avant qu'aucune machine ne soit
    créée, et non après des heures sur une matrice vide."""
    connues = {
        "saveur": set(releases),
        "distribution": {d for t in releases.values() for d in t},
        "version": {
            v for t in releases.values() for vs in t.values() for v in vs
        },
    }
    for genre, demandes in (
        ("saveur", saveurs),
        ("distribution", distros),
        ("version", versions),
    ):
        inconnues = sorted(set(demandes) - connues[genre])
        if inconnues:
            raise ValueError(
                f"{genre} inconnue : {', '.join(inconnues)} (connues :"
                f" {', '.join(sorted(connues[genre]))})"
            )
    choix = [
        (d, v, s)
        for s, table in releases.items()
        if not saveurs or s in saveurs
        for d, vs in table.items()
        if not distros or d in distros
        for v in vs
        if not versions or v in versions
    ]
    return sorted(choix)


def nom_vm(prefixe, distro, version, saveur):
    """Nom de domaine ET d'hôte de la VM : minuscules, chiffres, tirets.

    Il porte la combinaison entière : « virsh list » suffit à savoir ce que
    chaque machine éprouve, et deux combinaisons n'ont jamais le même nom."""
    brut = f"{prefixe}-{distro}-{version}-{saveur}".lower()
    return re.sub(r"[^a-z0-9-]", "", brut.replace(".", ""))


def parallele_conseille(ram_mo, memoire_vm=MEMOIRE_MO, marge=MARGE_HOTE_MO):
    """Nombre de VM que la RAM disponible porte à la fois, marge de l'hôte
    déduite ; au moins une."""
    return max(1, (ram_mo - marge) // memoire_vm)


def lire_resultat(texte):
    """{clé: valeur} d'un fichier « clé=valeur » ; la dernière l'emporte."""
    res = {}
    for ligne in texte.splitlines():
        if "=" in ligne:
            cle, valeur = ligne.split("=", 1)
            res[cle.strip()] = valeur.strip()
    return res


def sections(texte):
    """{nom: [lignes]} d'une sortie découpée par des lignes « == nom »."""
    res, courante = {}, None
    for ligne in texte.splitlines():
        if ligne.startswith("== "):
            courante = ligne[3:].strip()
            res[courante] = []
        elif courante is not None:
            res[courante].append(ligne)
    return res


def sessions(lignes):
    """[{id, Name, Class, Seat, …}] des lignes « ID Clé=Valeur … »."""
    res = []
    for ligne in lignes:
        champs = ligne.split()
        if not champs:
            continue
        s = {"id": champs[0]}
        for champ in champs[1:]:
            if "=" in champ:
                cle, valeur = champ.split("=", 1)
                s[cle] = valeur
        res.append(s)
    return res


def ouverture_auto(liste, compte=COMPTE):
    """La session graphique du compte sur seat0, ou None."""
    for s in liste:
        if (
            s.get("Seat") == "seat0"
            and s.get("Class") == "user"
            and s.get("Name") == compte
        ):
            return s
    return None


def ecoutes(lignes):
    """{port: {processus}} des lignes de « ss -ltnp »."""
    res = {}
    for ligne in lignes:
        champs = ligne.split()
        if len(champs) < 4 or champs[0] != "LISTEN":
            continue
        port = champs[3].rsplit(":", 1)[-1]
        if not port.isdigit():
            continue
        procs = set(re.findall(r'"([^"]+)"', ligne))
        res.setdefault(int(port), set()).update(procs)
    return res


def unites_en_echec(lignes):
    """Noms des unités de « systemctl --failed --no-legend --plain »."""
    return [
        ligne.split()[0]
        for ligne in lignes
        if ligne.strip() and not ligne.lstrip().startswith("●")
    ]


def executable(args):
    """Nom de l'exécutable d'une ligne de commande, tel qu'on le cherche.

    Le premier mot seulement, sans chemin, sans le point de tête ni le
    suffixe « -wrapped » des enveloppes de NixOS. Ni les arguments ni le
    reste de la ligne ne comptent : c'est ce qui empêche un shell qui
    porte le nom cherché dans sa ligne de commande d'être pris pour lui."""
    mots = args.split()
    if not mots:
        return ""
    nom = os.path.basename(mots[0]).rstrip(":")
    if nom.startswith("."):
        nom = nom[1:]
    if nom.endswith("-wrapped"):
        nom = nom[: -len("-wrapped")]
    return nom


def processus_present(lignes_ps, noms, utilisateur=None):
    """Un processus de `noms` tourne-t-il (sous `utilisateur`, si donné) ?

    `lignes_ps` : sortie de « ps -eo user:32=,args= »."""
    for ligne in lignes_ps:
        champs = ligne.split(None, 1)
        if len(champs) < 2:
            continue
        if utilisateur and champs[0] != utilisateur:
            continue
        if executable(champs[1]) in noms:
            return True
    return False


def avertissements(texte, gestionnaire):
    """(⚠ comptés, ⚠ excusés) du journal d'installation.

    Sur NixOS, « nixos-rebuild switch » rend 4 quand dbus-broker, qui
    remplace dbus-daemon, ne peut être rechargé à chaud ; l'installation
    l'annonce par un ⚠ voulu puis vérifie le système. Ces ⚠-là sont excusés,
    et seulement quand le journal porte cette cause."""
    lignes = [ligne for ligne in texte.splitlines() if "⚠" in ligne]
    excuses = 0
    if (
        gestionnaire == "nix"
        and "Failed to reload dbus-broker.service" in texte
    ):
        excuses = sum(1 for ligne in lignes if "nixos-rebuild" in ligne)
    return len(lignes) - excuses, excuses


def echecs_pam(texte):
    """Nombre de lignes du journal qui disent un mot de passe refusé."""
    return sum(
        1 for ligne in texte.splitlines() if MOTIF_ECHEC_PAM.search(ligne)
    )


def lire_teintes(valeur):
    """« colours=N nonblack=P » -> N, ou None."""
    m = re.search(r"colours=(\d+)", valeur or "")
    return int(m.group(1)) if m else None


def _entier(valeur, defaut=0):
    try:
        return int(str(valeur).split()[0])
    except (ValueError, IndexError):
        return defaut


def _raisons_communes(r):
    raisons = []
    for etape in ("deploy", "install"):
        if etape in r and _entier(r[etape], 1) != 0:
            raisons.append((etape, f"{etape}={r[etape]}"))
    if _entier(r.get("deploy"), 1) == 0 and not r.get("ip"):
        raisons.append(("ip", "aucune adresse"))
    if r.get("cloud_final") not in (None, "active"):
        raisons.append(("cloud_final", f"cloud-final={r['cloud_final']}"))
    if r.get("vm_password") not in (None, "ok"):
        raisons.append(("vm_password", "mot de passe non déposé dans la VM"))
    if _entier(r.get("install_warn", "0")):
        raisons.append(("warn", f"⚠x{r['install_warn']}"))
    if r.get("reboot_ssh") not in (None, "ok"):
        raisons.append(("reboot", "ssh absent après le redémarrage"))
    # Une adresse qui change au redémarrage est un défaut en soi : l'entrée
    # ~/.ssh/config que le menu écrit porte celle du premier démarrage.
    if r.get("ip_after") and r.get("ip") and r["ip_after"] != r["ip"]:
        raisons.append(
            ("ip_change", f"adresse changée : {r['ip']} -> {r['ip_after']}")
        )
    if "dm" in r and r["dm"].split()[-1:] != ["active"]:
        raisons.append(("dm", f"dm={r['dm']}"))
    # Strict : toute unité en échec qu'EXCUSES_UNITES ne nomme pas fait
    # échouer la VM, qu'elle touche au bureau ou non.
    echecs = [u for u in liste_option(r.get("failed_units")) if u]
    reelles = [u for u in echecs if u not in EXCUSES_UNITES]
    if reelles:
        raisons.append(("failed", "unités en échec : " + ", ".join(reelles)))
    if r.get("port_listen") not in (None, "ok"):
        raisons.append(("port", f"port {r['port_listen']}"))
    if r.get("motd_port") not in (None, "ok"):
        raisons.append(("motd", f"motd={r['motd_port']}"))
    if "console_shot" in r and not r["console_shot"].startswith("saved"):
        raisons.append(("console", f"console={r['console_shot']}"))
    return raisons


def _raisons_sessions(r, genre):
    raisons = []
    if genre in ("krdp", "wayvnc"):
        if r.get("autologin") != "yes":
            raisons.append(("autologin", "pas d'ouverture automatique"))
        if genre == "krdp" and r.get("locked") != "yes":
            raisons.append(("locked", "session non verrouillée"))
        if genre == "wayvnc" and r.get("hyprlock") != "running":
            raisons.append(("hyprlock", "hyprlock absent"))
    return raisons


def _raisons_rdp(r):
    """Connexion RDP réelle (xrdp, KRdp) : bon, mauvais, image."""
    raisons = []
    bon = r.get("rdp_good", "")
    if "alive=1" not in bon or _entier(r.get("rdp_good_pam", "1"), 1):
        raisons.append(
            (
                "rdp_good",
                f"rdp_good={bon or '-'} pam={r.get('rdp_good_pam', '-')}",
            )
        )
    if not _entier(r.get("rdp_bad_pam", "0")):
        raisons.append(
            (
                "rdp_bad",
                "mauvais mot de passe sans échec PAM"
                f" ({r.get('rdp_bad', '-')})",
            )
        )
    n = lire_teintes(r.get("rdp_good_img"))
    if n is None or n < TEINTES_MIN:
        raisons.append(
            ("image", f"image RDP plate ({r.get('rdp_good_img', 'absente')})")
        )
    return raisons


def _raisons_vnc(r, juger_image=True):
    """VeNCrypt (wayvnc, TigerVNC) : bon, mauvais, image.

    L'image du bon mot de passe se juge à ses teintes, comme celle de RDP,
    quand `juger_image` : TigerVNC sert un bureau X rendu. wayvnc sert
    l'écran de hyprlock, un fond uni que les teintes ne distinguent pas d'un
    écran vide ; seule la capture réussie compte. Une image ne se juge que
    capturée, la capture manquée étant déjà une raison."""
    raisons = []
    if not r.get("vnc_good", "").startswith("saved"):
        raisons.append(("vnc_good", f"vnc_good={r.get('vnc_good', '-')}"))
    elif juger_image:
        n = lire_teintes(r.get("vnc_good_img"))
        if n is None or n < TEINTES_MIN:
            raisons.append(
                (
                    "image",
                    f"image VNC plate ({r.get('vnc_good_img', 'absente')})",
                )
            )
    if not r.get("vnc_bad", "").startswith("AUTH-FAIL"):
        raisons.append(("vnc_bad", f"vnc_bad={r.get('vnc_bad', '-')}"))
    return raisons


def _raisons_distantes(r, genre):
    raisons = []
    if genre == "grd":
        if r.get("rdp_good") != "rc=0":
            raisons.append(("rdp_good", f"rdp_good={r.get('rdp_good', '-')}"))
        if r.get("rdp_bad", "rc=0") == "rc=0":
            raisons.append(("rdp_bad", "mauvais mot de passe accepté"))
    elif genre == "krdp":
        raisons += _raisons_rdp(r)
        if "faillock_good_after" in r and (
            "alive=1" not in r["faillock_good_after"]
        ):
            raisons.append(
                (
                    "faillock",
                    f"bloqué après 4 échecs : {r['faillock_good_after']}",
                )
            )
    elif genre == "xrdp":
        raisons += _raisons_rdp(r)
    elif genre == "tigervnc":
        if r.get("vnc_unit") != "active":
            raisons.append(("vnc_unit", f"vncserver@:1={r.get('vnc_unit')}"))
        raisons += _raisons_vnc(r)
    elif genre == "wayvnc":
        raisons += _raisons_vnc(r, juger_image=False)
    if genre in ("xrdp", "tigervnc") and r.get("xsess") != "running":
        raisons.append(("xsess", f"session X={r.get('xsess', '-')}"))
    return raisons


def verdict(r):
    """(raisons, notes) d'un résultat de VM ; aucune raison = vert.

    Chaque raison est une chaîne lisible ; ATTENDUS déplace en note celles
    que la combinaison excuse, EXCUSES_UNITES les unités sans objet."""
    if not r:
        return ["non commencée"], []
    raisons, notes = [], []
    if r.get("done") != "1":
        raisons.append(("inacheve", f"interrompu ({r.get('etape', '?')})"))
    raisons += _raisons_communes(r)
    if r.get("abandon"):
        # Les contrôles qui suivent n'ont pas eu lieu : les compter comme
        # échoués noierait la cause sous leurs absences.
        raisons.append(("abandon", f"abandon : {r['abandon']}"))
    elif r.get("done") == "1":
        genre = r.get("access") or r.get("kind", "")
        raisons += _raisons_sessions(r, r.get("kind", ""))
        raisons += _raisons_distantes(r, genre)
    combo = (r.get("distro"), r.get("version"), r.get("flavour"))
    excuses = ATTENDUS.get(combo, {})
    gardees = []
    for cle, texte in raisons:
        if cle in excuses:
            notes.append(f"attendu : {texte} — {excuses[cle]}")
        else:
            gardees.append(texte)
    for u in liste_option(r.get("failed_units")):
        if u in EXCUSES_UNITES:
            notes.append(f"{u} excusé : {EXCUSES_UNITES[u]}")
    if _entier(r.get("install_warn_nix_rc4", "0")):
        notes.append(
            f"⚠ nixos-rebuild rc 4 excusé x{r['install_warn_nix_rc4']}"
        )
    return gardees, notes


def acces_effectif(genre, gestionnaire, ports):
    """Le serveur qui sert vraiment l'accès distant de la VM.

    `genre` : grd, x11, krdp, wayvnc ou console ; `ports` : {port:
    {processus}} lus dans la VM. x11 se sert par TigerVNC sous pacman, par
    xrdp ailleurs. grd passe à xrdp quand xrdp tient le 3389 : c'est le
    repli de GNOME sans mode système de grdctl, qui se juge comme xrdp."""
    if genre == "grd" and "xrdp" in ports.get(3389, set()):
        return "xrdp"
    if genre == "x11":
        return "tigervnc" if gestionnaire == "pacman" else "xrdp"
    return genre


def ligne_bilan(nom, r):
    raisons, notes = verdict(r)
    etat = "OK" if not raisons else "FAIL " + "; ".join(raisons)
    genre = r.get("access") or r.get("kind", "?")
    install = r.get("install", "-")
    ligne = f"{nom:36} {genre:8} inst={install:9} {etat}"
    if notes:
        ligne += "  [" + "; ".join(notes) + "]"
    return ligne, not raisons


def bilan(resultats):
    """(lignes, nombre de verts) de {nom: résultat}, trié par nom."""
    lignes, verts = [], 0
    for nom in sorted(resultats):
        ligne, ok = ligne_bilan(nom, resultats[nom])
        lignes.append(ligne)
        verts += ok
    lignes.append(f"{verts}/{len(resultats)} OK")
    return lignes, verts


def lire_dossier(dossier):
    """{nom: résultat} des sous-dossiers de `dossier` qui ont un result.txt."""
    res = {}
    for nom in sorted(os.listdir(dossier)):
        chemin = os.path.join(dossier, nom, "result.txt")
        if os.path.isfile(chemin):
            with open(chemin, encoding="utf-8") as fh:
                res[nom] = lire_resultat(fh.read())
    return res


# --------------------------------------------------------------------------
# Le plan : ce que le menu enverrait, VM par VM
# --------------------------------------------------------------------------


def charger_todo():
    sys.argv = [sys.argv[0]]
    from script.todo.todo import TODO

    return TODO.__new__(TODO)


def regional(todo, deploy):
    """(fuseau, locale) d'une VM déployée par le formulaire du menu.

    Le fuseau est celui de l'hôte, lu par la méthode même du menu. La locale
    est le défaut de « --locale » de deploy_qemu.py : le formulaire n'en
    passe aucune. Les deux paraissent dans la commande, si bien qu'un plan
    rejoué depuis un autre hôte produit les mêmes VM."""
    return (
        todo._qemu_host_timezone(),
        deploy.build_parser().get_default("locale"),
    )


def fiche(todo, deploy, combo, prefixe, empreinte, fuseau_locale=None):
    """Tout ce qu'une VM demande, tiré du code du menu.

    `deploy` : le module script.qemu.deploy_qemu (catalogue, familles,
    versions de KRdp) ; `empreinte` : SHA-512 crypt du mot de passe ;
    `fuseau_locale` : le couple de regional(), calculé ici s'il manque."""
    distro, version, saveur = combo
    fuseau, locale = fuseau_locale or regional(todo, deploy)
    genre = todo._qemu_remote_kind(saveur, distro, version)
    port = (todo._qemu_remote_port(genre, distro) or ("", ""))[0]
    _code, _osinfo, ram, disque = deploy.DISTROS[distro][0][version]
    nom = nom_vm(prefixe, distro, version, saveur)
    avec_ca = os.path.isfile(CACHE_CA)
    argv = todo._qemu_build_deploy_parts(
        distro,
        version,
        "amd64",
        nom,
        max(MEMOIRE_MO, ram),
        VCPUS,
        disque,
        cle_publique(),
        None,
        False,
        timezone=fuseau,
        locale=locale,
        desktop=saveur,
        cache_ca=CACHE_CA if avec_ca else "",
        cache_bypass=not avec_ca,
        user=COMPTE,
        password_hash=empreinte,
    )
    if argv[:1] != ["sudo"]:
        raise RuntimeError(f"commande de déploiement inattendue : {argv[:2]}")
    return {
        "nom": nom,
        "distro": distro,
        "version": version,
        "saveur": saveur,
        "genre": genre,
        "port": port,
        "fuseau": fuseau,
        "locale": locale,
        "gestionnaire": deploy.DISTRO_PKG[distro],
        # NLA de KRdp avant 6.8 ne trouve pas le compte (« Could not find
        # user in SAM database ») : le client passe en TLS.
        "securite": (
            "/sec:tls" if (distro, version) in deploy.KRDP_BEFORE_6_8 else "-"
        ),
        "faillock": genre == "krdp" and distro in DISTROS_FAILLOCK,
        "processus": PROCESSUS_SESSION.get(saveur, ()),
        "mot_de_passe_dans_vm": todo._qemu_vm_login_file_needed(saveur, False),
        # « sudo -n » : sans ticket valide, sudo échoue au lieu de poser une
        # question que personne ne verrait derrière quatre VM en parallèle.
        "deploiement": ["sudo", "-n"] + argv[1:] + ["--no-git-identity"],
        "distante": todo._qemu_erplibre_remote_cmd(
            None, desktop=saveur, distro=distro, version=version
        ),
    }


def empreinte_mot_de_passe(mot_de_passe):
    """SHA-512 crypt par openssl, le clair passant par l'entrée standard."""
    fini = subprocess.run(
        ["openssl", "passwd", "-6", "-stdin"],
        input=mot_de_passe + "\n",
        capture_output=True,
        text=True,
        timeout=30,
    )
    if fini.returncode:
        raise RuntimeError(f"openssl passwd : {fini.stderr.strip()}")
    return fini.stdout.strip()


# --------------------------------------------------------------------------
# Le banc : une VM, ses étapes, son résultat
# --------------------------------------------------------------------------


class Abandon(Exception):
    """Une étape sans laquelle la suite ne peut rien juger."""


def ssh_argv(ip):
    return [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=15",
        f"{COMPTE}@{ip}",
    ]


def lancer(argv, delai, entree=None, sortie=None, env=None):
    """(code, texte) d'une commande locale ; 124 quand le délai expire.

    `sortie` : fichier qui reçoit stdout et stderr, le texte rendu étant
    alors vide. Sans `entree`, l'entrée standard est /dev/null : quatre ssh
    en parallèle liraient sinon le terminal de l'opérateur."""
    stdin = {} if entree is not None else {"stdin": subprocess.DEVNULL}
    try:
        if sortie:
            with open(sortie, "a", encoding="utf-8") as fh:
                fini = subprocess.run(
                    argv,
                    input=entree,
                    stdout=fh,
                    **stdin,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=delai,
                    env=env,
                )
            return fini.returncode, ""
        fini = subprocess.run(
            argv,
            input=entree,
            **stdin,
            capture_output=True,
            text=True,
            timeout=delai,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return 124, f"délai de {delai} s dépassé"
    except OSError as err:
        return 127, str(err)
    return fini.returncode, (fini.stdout or "") + (fini.stderr or "")


def uuid_de(nom):
    code, sortie = lancer(["virsh", "-c", URI, "domuuid", nom], 30)
    return sortie.strip() if code == 0 else ""


def domaines(prefixe):
    """Domaines libvirt dont le nom commence par « prefixe- »."""
    code, sortie = lancer(["virsh", "-c", URI, "list", "--all", "--name"], 30)
    if code:
        return []
    return [
        n.strip()
        for n in sortie.splitlines()
        if n.strip().startswith(prefixe + "-")
    ]


def detruire_vm(nom, attendu=""):
    """Arrête et efface le domaine `nom`, disques compris. Rend un état.

    `attendu` : l'UUID noté à la création. S'il diffère, la machine n'est
    pas celle que ce test a créée et rien n'est touché :
    « --remove-all-storage » efface un disque pour de bon."""
    vu = uuid_de(nom)
    if not vu:
        return "absent"
    if attendu and vu != attendu:
        return f"UUID {vu} au lieu de {attendu} : rien touché"
    lancer(["virsh", "-c", URI, "destroy", nom], 120)
    code, sortie = lancer(
        [
            "virsh",
            "-c",
            URI,
            "undefine",
            nom,
            "--nvram",
            "--remove-all-storage",
        ],
        300,
    )
    return "yes" if code == 0 else f"échec : {sortie.strip()[:160]}"


class Essai:
    """Une VM de la matrice, du déploiement à la destruction."""

    def __init__(self, f, dossier, contexte):
        self.f = f
        self.nom = f["nom"]
        self.dossier = os.path.join(dossier, self.nom)
        self.ctx = contexte
        self.r = {}
        self.ip = ""
        os.makedirs(self.dossier, exist_ok=True)
        self.fichier = os.path.join(self.dossier, "result.txt")
        open(self.fichier, "w", encoding="utf-8").close()

    # -- écriture --------------------------------------------------------

    def noter(self, cle, valeur):
        valeur = " ".join(str(valeur).split())
        self.r[cle] = valeur
        with open(self.fichier, "a", encoding="utf-8") as fh:
            fh.write(f"{cle}={valeur}\n")

    def dire(self, message):
        with _VERROU_JOURNAL:
            dire(f"{self.nom} : {message}", self.ctx["journal"])

    def chemin(self, nom):
        return os.path.join(self.dossier, nom)

    def arreter_si_demande(self):
        if self.ctx["arret"].is_set():
            raise Abandon("arrêt demandé")

    # -- invité ----------------------------------------------------------

    def ssh(
        self, commande, delai=DELAIS["commande"], entree=None, sortie=None
    ):
        return lancer(
            ssh_argv(self.ip) + [commande], delai, entree=entree, sortie=sortie
        )

    def attendre_ssh(self, delai):
        fin = time.time() + delai
        while time.time() < fin:
            self.arreter_si_demande()
            if self.ssh("true", 30)[0] == 0:
                return True
            time.sleep(5)
        return False

    def heure_invite(self):
        code, sortie = self.ssh("date +%s", 30)
        return sortie.strip() if code == 0 else str(int(time.time()))

    def journal_depuis(self, depuis, etiquette):
        """Le journal de l'invité depuis `depuis` ; rend ses échecs PAM."""
        _c, texte = self.ssh(
            f"sudo journalctl --since @{depuis} --no-pager -o short", 120
        )
        with open(self.chemin(f"journal_{etiquette}.txt"), "w") as fh:
            fh.write(texte)
        return echecs_pam(texte)

    def liste_ps(self):
        _c, texte = self.ssh("ps -eo user:32=,args=", 60)
        return texte.splitlines()

    # -- étapes ----------------------------------------------------------

    def mener(self):
        debut = time.time()
        f = self.f
        for cle, valeur in (
            ("vm", self.nom),
            ("distro", f["distro"]),
            ("version", f["version"]),
            ("flavour", f["saveur"]),
            ("kind", f["genre"]),
            ("port", f["port"]),
            ("mgr", f["gestionnaire"]),
            ("timezone", f["fuseau"]),
            ("locale", f["locale"]),
        ):
            self.noter(cle, valeur)
        try:
            self.deployer()
            self.preparer()
            self.installer()
            self.redemarrer()
            self.sonder()
            self.console()
            self.acces_distant()
        except Abandon as err:
            self.noter("abandon", err)
            self.dire(f"✗ abandon : {err}")
        # Toute autre exception reste celle de CET essai : elle est notée et
        # les autres VM continuent.
        except Exception as err:  # noqa: BLE001
            self.noter("abandon", f"{type(err).__name__}: {err}")
            self.dire(f"✗ {type(err).__name__} : {err}")
        finally:
            self.clore(debut)
        return self.r

    def etape(self, nom):
        self.arreter_si_demande()
        self.noter("etape", nom)
        self.dire(nom)

    def deployer(self):
        self.etape("déploiement")
        t0 = time.time()
        code, _ = lancer(
            self.f["deploiement"],
            DELAIS["deploiement"],
            sortie=self.chemin("deploy.log"),
        )
        self.noter("deploy", f"{code} {int(time.time() - t0)}s")
        # L'UUID, même après un échec : un domaine à moitié créé doit
        # rester défaisable par « --detruire ».
        uuid = uuid_de(self.nom)
        if uuid:
            self.noter("uuid", uuid)
            self.ctx["noter_uuid"](self.nom, uuid)
        if code:
            raise Abandon(f"déploiement rc={code}")
        self.ip = self.ctx["todo"]._qemu_vm_ip(self.nom, DELAIS["ip"]) or ""
        self.noter("ip", self.ip)
        if not self.ip:
            raise Abandon("aucune adresse")

    def preparer(self):
        self.etape("cloud-final")
        if not self.attendre_ssh(DELAIS["ssh"]):
            raise Abandon("ssh muet après le déploiement")
        # cloud-final porte l'autorité du cache, les variables et le sudoers :
        # sa fin, et non le seul « cloud-init status », dit la VM prête.
        _c, sortie = self.ssh(
            "n=0; while true; do s=$(systemctl show -p ActiveState --value"
            ' cloud-final.service); [ "$s" = active ] || [ "$s" = failed ]'
            " && break; n=$((n+1)); [ $n -ge 600 ] && break; sleep 3; done;"
            " echo $s",
            DELAIS["cloud_final"],
        )
        self.noter("cloud_final", (sortie.strip().splitlines() or ["?"])[-1])
        if self.f["mot_de_passe_dans_vm"]:
            self.deposer_mot_de_passe()

    def deposer_mot_de_passe(self):
        """Le clair du compte dans l'invité, par la commande du menu."""
        from script.todo.qemu_install_monitor import (
            VM_LOGIN_ENV,
            vm_login_push_cmd,
        )

        env = dict(os.environ, **{VM_LOGIN_ENV: MOT_DE_PASSE})
        code, sortie = lancer(
            [
                "bash",
                "-c",
                vm_login_push_cmd(shlex.quote(f"{COMPTE}@{self.ip}")),
            ],
            120,
            env=env,
        )
        self.noter(
            "vm_password", "ok" if code == 0 and "⚠" not in sortie else "FAIL"
        )

    def installer(self):
        self.etape("installation du bureau")
        t0 = time.time()
        journal = self.chemin("install.log")
        code, _ = self.ssh(
            self.f["distante"], DELAIS["installation"], sortie=journal
        )
        self.noter("install", f"{code} {int(time.time() - t0)}s")
        with open(journal, encoding="utf-8", errors="replace") as fh:
            comptes, excuses = avertissements(
                fh.read(), self.f["gestionnaire"]
            )
        if excuses:
            self.noter("install_warn_nix_rc4", excuses)
        self.noter("install_warn", comptes)

    def boot_id(self):
        code, sortie = self.ssh("cat /proc/sys/kernel/random/boot_id", 30)
        return sortie.strip() if code == 0 else ""

    def attendre_redemarrage(self, avant):
        """Vrai quand ssh répond avec un identifiant de démarrage NEUF : un
        ssh qui répond encore avant l'arrêt n'est pas un retour."""
        fin = time.time() + DELAIS["reboot_ssh"]
        while time.time() < fin:
            self.arreter_si_demande()
            courant = self.boot_id()
            if courant and courant != avant:
                return True
            time.sleep(5)
        return False

    def redemarrer(self):
        self.etape("redémarrage")
        avant = self.boot_id()
        self.ssh("sudo systemctl reboot", 30)
        time.sleep(25)
        revenu = self.attendre_redemarrage(avant)
        if not revenu:
            # L'adresse a pu changer au redémarrage : le bail se relit, et
            # le changement se note — il est un défaut en soi.
            nouvelle = self.ctx["todo"]._qemu_vm_ip(self.nom, 120) or ""
            if nouvelle and nouvelle != self.ip:
                self.ip = nouvelle
                revenu = self.attendre_redemarrage(avant)
        self.noter("reboot_ssh", "ok" if revenu else "FAIL")
        self.noter("ip_after", self.ip)
        if not revenu:
            self.console()
            raise Abandon("ssh absent après le redémarrage")
        time.sleep(STABILISATION)

    def sonder(self):
        self.etape("sonde de l'invité")
        _c, texte = self.ssh("bash -s", 180, entree=SONDE_INVITE)
        with open(self.chemin("guest.txt"), "w", encoding="utf-8") as fh:
            fh.write(texte)
        s = sections(texte)
        self.noter("dm", " ".join(s.get("dm", [])))
        self.noter(
            "failed_units", ",".join(unites_en_echec(s.get("failed", [])))
        )
        liste = sessions(s.get("sessions", []))
        self.noter(
            "seat0",
            "; ".join(
                f"{x.get('Name')}/{x.get('Class')}/{x.get('Type')}"
                f"/locked={x.get('LockedHint')}"
                for x in liste
                if x.get("Seat") == "seat0"
            ),
        )
        auto = ouverture_auto(liste)
        self.noter("autologin", "yes" if auto else "no")
        self.noter("locked", (auto or {}).get("LockedHint", "-"))
        ps = s.get("ps", [])
        self.noter(
            "hyprlock",
            (
                "running"
                if processus_present(ps, ("hyprlock",), COMPTE)
                else "ABSENT"
            ),
        )
        ports = ecoutes(s.get("listen", []))
        self.noter("listen", ",".join(str(p) for p in sorted(ports)))
        self.juger_ports(ports, "\n".join(s.get("motd", [])))
        acces = acces_effectif(self.f["genre"], self.f["gestionnaire"], ports)
        self.noter("access", acces)

    def juger_ports(self, ports, motd):
        attendu = self.f["port"]
        if attendu:
            self.noter(
                "port_listen",
                "ok" if int(attendu) in ports else f"{attendu} fermé",
            )
            self.noter(
                "motd_port",
                "ok" if str(attendu) in motd else f"MISSING-{attendu}",
            )
        else:
            annonce = re.search(r"\b(3389|590[01])\b", motd)
            self.noter(
                "motd_port",
                f"UNEXPECTED-{annonce.group(1)}" if annonce else "ok",
            )

    def console(self):
        """La console QEMU, telle que l'utilisateur la voit."""
        if "console_shot" in self.r:
            return
        code, sortie = lancer(["virsh", "-c", URI, "vncdisplay", self.nom], 30)
        m = re.search(
            r":(\d+)\s*$",
            sortie.strip().splitlines()[0] if sortie.strip() else "",
        )
        if code or not m:
            self.noter("console_shot", f"ERROR vncdisplay rc={code}")
            return
        png = self.chemin("console.png")
        etat = image.capture_rfb(
            "127.0.0.1", 5900 + int(m.group(1)), png, reveil=True
        )
        self.noter("console_shot", etat)
        if etat.startswith("saved"):
            self.noter("console_img", image.stat_png(png))

    # -- accès distant ---------------------------------------------------

    def client(self, etiquette, mode, attente=35):
        """Ligne de commande du conteneur client RDP (voir rdp.sh)."""
        argv = [
            "podman",
            "run",
            "--rm",
            "--network",
            "host",
            "--security-opt",
            "label=disable",
            "-v",
            f"{self.ctx['mots_de_passe']}:/pw:ro",
            "-v",
            f"{self.dossier}:/out",
            "-v",
            f"{os.path.join(DOSSIER_CLIENT, 'rdp.sh')}:/rdp.sh:ro",
            IMAGE_CLIENT,
            "sh",
            "/rdp.sh",
            etiquette,
            self.ip,
            str(self.f["port"] or 3389),
            self.f["securite"],
            mode,
            str(attente),
        ]
        return argv

    def rdp(self, etiquette, mode, attente=35):
        code, sortie = lancer(
            self.client(etiquette, mode, attente), attente + 120
        )
        lignes = sortie.strip().splitlines()
        return lignes[-1] if lignes else f"podman rc={code}"

    def acces_distant(self):
        acces = self.r.get("access", "console")
        self.etape(f"accès distant ({acces})")
        if acces == "grd":
            self.noter("rdp_good", self.rdp("good", "auth"))
            self.noter("rdp_bad", self.rdp("bad", "auth"))
        elif acces == "xrdp":
            self.xrdp()
        elif acces == "krdp":
            self.krdp()
        elif acces == "tigervnc":
            self.noter(
                "vnc_unit",
                self.ssh("systemctl is-active vncserver@:1", 30)[1].strip(),
            )
            self.vnc(5901)
            noms = self.f["processus"]
            self.noter(
                "xsess",
                (
                    "running"
                    if processus_present(self.liste_ps(), noms, COMPTE)
                    else "ABSENT"
                ),
            )
        elif acces == "wayvnc":
            self.vnc(5900)
        self.images()

    def vnc(self, port):
        for etiquette, mdp in (
            ("bad", MAUVAIS_MOT_DE_PASSE),
            ("good", MOT_DE_PASSE),
        ):
            etat = image.capture_rfb(
                self.ip, port, self.chemin(f"vnc_{etiquette}.png"), COMPTE, mdp
            )
            self.noter(f"vnc_{etiquette}", etat)
        if self.r.get("vnc_good", "").startswith("saved"):
            self.noter(
                "vnc_good_img", image.stat_png(self.chemin("vnc_good.png"))
            )

    def rdp_juge(self, etiquette, attente):
        """Connexion réelle, puis les échecs PAM qu'elle a laissés au
        journal ; le délai de trois secondes laisse le journal s'écrire."""
        depuis = self.heure_invite()
        self.noter(f"rdp_{etiquette}", self.rdp(etiquette, "conn", attente))
        time.sleep(3)
        self.noter(
            f"rdp_{etiquette}_pam", self.journal_depuis(depuis, etiquette)
        )

    def xrdp(self):
        self.rdp_juge("bad", 25)
        # La session X d'xrdp naît de la connexion : le processus se cherche
        # PENDANT qu'elle est ouverte.
        depuis = self.heure_invite()
        resultat = {}
        fil = threading.Thread(
            target=lambda: resultat.update(etat=self.rdp("good", "conn", 45))
        )
        fil.start()
        time.sleep(35)
        present = processus_present(
            self.liste_ps(), self.f["processus"], COMPTE
        )
        fil.join()
        self.noter("xsess", "running" if present else "ABSENT")
        self.noter("rdp_good", resultat.get("etat", "-"))
        self.noter("rdp_good_pam", self.journal_depuis(depuis, "good"))

    def krdp(self):
        time.sleep(ATTENTE_KRDP)
        self.rdp_juge("bad", 25)
        self.rdp_juge("good", 35)
        if not self.f["faillock"]:
            return
        for i in range(1, 5):
            self.rdp(f"bad{i}", "conn", 15)
        depuis = self.heure_invite()
        self.noter("faillock_good_after", self.rdp("good_after", "conn", 30))
        self.noter(
            "faillock_good_after_pam", self.journal_depuis(depuis, "after")
        )
        _c, sortie = self.ssh(f"sudo faillock --user {COMPTE}", 60)
        lignes = [x for x in sortie.splitlines() if re.search(r" (V|I)$", x)]
        self.noter("faillock_rows", len(lignes))
        self.ssh(f"sudo faillock --user {COMPTE} --reset", 60)

    def images(self):
        for nom in sorted(os.listdir(self.dossier)):
            if not nom.endswith(".xwd"):
                continue
            xwd = self.chemin(nom)
            try:
                image.xwd_vers_png(xwd, xwd[:-4] + ".png")
                os.remove(xwd)
            except (OSError, ValueError) as err:
                self.dire(f"⚠ {nom} illisible : {err}")
        png = self.chemin("rdp_good.png")
        if os.path.isfile(png):
            self.noter("rdp_good_img", image.stat_png(png))

    def clore(self, debut):
        self.noter("total", f"{int(time.time() - debut)}s")
        if self.ctx["garder"]:
            self.noter("destroyed", "no (--garder)")
        else:
            self.noter(
                "destroyed", detruire_vm(self.nom, self.r.get("uuid", ""))
            )
        self.noter("done", 1)
        raisons, _notes = verdict(self.r)
        self.dire("✓ OK" if not raisons else "✗ " + "; ".join(raisons))


# --------------------------------------------------------------------------
# Une course : préalables, plan, exécution, bilan
# --------------------------------------------------------------------------


def autres_courses():
    """PID des AUTRES processus qui exécutent ce script.

    Par le nom de fichier d'un argument, lu dans /proc : un « pgrep -f »
    trouverait aussi le shell qui le lance, et un fichier de tests dont le
    nom finit comme celui-ci n'est pas une course."""
    moi, vivants = os.getpid(), []
    for entree in os.listdir("/proc"):
        if not entree.isdigit() or int(entree) == moi:
            continue
        try:
            with open(f"/proc/{entree}/cmdline", "rb") as fh:
                args = fh.read().split(b"\0")
        except OSError:
            continue
        if any(os.path.basename(a) == SCRIPT.encode() for a in args):
            vivants.append(int(entree))
    return vivants


def horodatage():
    return time.strftime("%Y%m%d-%H%M%S")


def avertir_ressources(parallele, nombre, garder, journal):
    """Prévient quand l'hôte ne porte pas le plan ; ne refuse rien.

    La RAM DISPONIBLE compte déjà les autres VM qui tournent. Des VM dont la
    mémoire nominale égale celle de l'hôte le mettent en manque : le noyau
    tue alors une VM au hasard, et son essai échoue sans rapport avec le
    bureau."""
    _coeurs, ram, disque = capacite_hote()
    conseil = parallele_conseille(ram)
    dire(
        f"  hôte : {ram} Mo de RAM disponibles, {disque} Go de disque libres"
        f" — {conseil} VM de {MEMOIRE_MO} Mo à la fois",
        journal,
    )
    if parallele > conseil:
        dire(
            f"  ⚠ --parallele {parallele} dépasse ce que la RAM porte"
            f" ({conseil}) : risque de manque de mémoire sur l'hôte",
            journal,
        )
    gardees = nombre if garder else parallele
    if disque and disque < gardees * DISQUE_ECRIT_GO:
        dire(
            f"  ⚠ {gardees} VM à {DISQUE_ECRIT_GO} Go écrits chacune"
            f" dépassent les {disque} Go libres",
            journal,
        )


def afficher_plan(fiches, journal):
    for f in fiches:
        argv = [
            "'<empreinte>'" if a.startswith("$6$") else shlex.quote(a)
            for a in f["deploiement"]
        ]
        dire(
            f"  {f['nom']}  {f['genre'] or 'console'}"
            f" port={f['port'] or '-'} tls={f['securite']}"
            f" faillock={'oui' if f['faillock'] else 'non'}",
            journal,
        )
        dire("      " + " ".join(argv), journal)
        dire(
            f"      commande distante du menu : {len(f['distante'])}"
            " caractères"
            + (", mot de passe déposé" if f["mot_de_passe_dans_vm"] else ""),
            journal,
        )


def empreinte_containerfile():
    """SHA-256 du Containerfile du client, tel qu'il est sur le disque."""
    with open(os.path.join(DOSSIER_CLIENT, "Containerfile"), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def commande_construction(empreinte, reconstruire):
    """argv de « podman build » de l'image client.

    L'image porte l'empreinte de son Containerfile en étiquette. Reconstruire
    passe « --no-cache » : sans lui, podman reprend la couche de
    « pacman -Syu » déjà construite et la reconstruction ne change rien."""
    argv = ["podman", "build"]
    if reconstruire:
        argv.append("--no-cache")
    return argv + [
        "--label",
        f"{ETIQUETTE_CLIENT}={empreinte}",
        "-t",
        IMAGE_CLIENT,
        "-f",
        os.path.join(DOSSIER_CLIENT, "Containerfile"),
        DOSSIER_CLIENT,
    ]


def preparer_client(reconstruire, journal):
    """L'image du client RDP, prête à servir. Rend un booléen.

    Gardée quand son étiquette porte l'empreinte du Containerfile actuel ;
    construite quand elle manque, quand elle sort d'un autre Containerfile
    (une autre image de base, d'autres paquets), ou sur `reconstruire`."""
    empreinte = empreinte_containerfile()
    if not reconstruire:
        code, sortie = lancer(
            [
                "podman",
                "image",
                "inspect",
                "--format",
                f'{{{{index .Labels "{ETIQUETTE_CLIENT}"}}}}',
                IMAGE_CLIENT,
            ],
            60,
        )
        if code == 0 and sortie.strip() == empreinte:
            return True
        if code == 0:
            dire(
                f"  l'image {IMAGE_CLIENT} sort d'un autre Containerfile",
                journal,
            )
    dire(f"  construction de l'image {IMAGE_CLIENT}", journal)
    code, sortie = lancer(commande_construction(empreinte, reconstruire), 1800)
    if code:
        dire(f"  ✗ podman build : {sortie.strip()[-300:]}", journal)
    return code == 0


def prealables(fiches, prefixe, args, journal):
    """Ce qui doit être vrai AVANT de créer la moindre VM. Rend un booléen.

    Chaque manque est dit avec son remède : découvrir au bout d'une heure
    qu'une commande manquait coûte la matrice entière."""
    manques = []
    autres = autres_courses()
    if autres:
        manques.append(f"une course tourne déjà ({autres})")
    for outil in ("virsh", "podman", "openssl", "ssh", "sudo"):
        if lancer(["which", outil], 10)[0]:
            manques.append(f"{outil} introuvable")
    if not cle_publique():
        manques.append("aucune clé ~/.ssh/id_ed25519.pub ni id_rsa.pub")
    if lancer(["virsh", "-c", URI, "list", "--name"], 30)[0]:
        manques.append(f"libvirt muet sur {URI} (groupe libvirt ?)")
    vivants = set(domaines(prefixe)) & {f["nom"] for f in fiches}
    if vivants:
        manques.append(
            f"{len(vivants)} VM du plan existent déjà"
            f" ({', '.join(sorted(vivants)[:3])} …) : --detruire d'abord"
        )
    for m in manques:
        dire(f"  ✗ {m}", journal)
    if manques:
        return False
    if not preparer_client(args.reconstruire_client, journal):
        return False
    # Un seul mot de passe sudo, au début : les déploiements partent ensuite
    # en « sudo -n », et un fil entretient le ticket.
    if subprocess.run(["sudo", "-v"]).returncode:
        dire("  ✗ sudo refusé", journal)
        return False
    return True


def entretenir_sudo(arret):
    while not arret.wait(240):
        subprocess.run(["sudo", "-n", "-v"], capture_output=True)


def ecrire_mots_de_passe(dossier):
    """Les deux mots de passe dans des fichiers 0600, montés dans le
    conteneur : ils ne paraissent sur aucune ligne de commande."""
    pw = os.path.join(dossier, "pw")
    os.makedirs(pw, mode=0o700, exist_ok=True)
    for nom, valeur in (("good", MOT_DE_PASSE), ("bad", MAUVAIS_MOT_DE_PASSE)):
        chemin = os.path.join(pw, nom)
        fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(valeur + "\n")
    return pw


def courir(fiches, args, journal, stamp):
    dossier = os.path.join(DOSSIER, f"{OUTIL}-{stamp}")
    os.makedirs(dossier, exist_ok=True)
    chemin_rapport = os.path.join(DOSSIER, f"{OUTIL}-{stamp}.json")
    rapport = {
        "outil": OUTIL,
        "pid": os.getpid(),
        "dossier": dossier,
        "prefixe": args.prefixe,
        "parallele": args.parallele,
        "garder": args.garder,
        "plan": [f["nom"] for f in fiches],
        "vms": {},
    }

    def ecrire():
        with open(chemin_rapport, "w", encoding="utf-8") as fh:
            json.dump(rapport, fh, indent=2)

    def noter_uuid(nom, uuid):
        with _VERROU_RAPPORT:
            rapport["vms"][nom] = uuid
            ecrire()

    ecrire()
    dire(f"  résultats : {dossier}", journal)
    arret = threading.Event()
    threading.Thread(
        target=entretenir_sudo, args=(arret,), daemon=True
    ).start()
    contexte = {
        "journal": journal,
        "arret": arret,
        "garder": args.garder,
        "todo": charger_todo(),
        "noter_uuid": noter_uuid,
        "mots_de_passe": ecrire_mots_de_passe(dossier),
    }
    resultats = {}
    pool = ThreadPoolExecutor(max_workers=args.parallele)
    futurs = {
        # L'essai naît dans son fil : une VM jamais commencée n'a ni dossier
        # ni résultat, et le bilan d'une course interrompue ne la confond pas
        # avec une VM échouée.
        pool.submit(lambda f=f: Essai(f, dossier, contexte).mener()): f["nom"]
        for f in fiches
    }
    try:
        for futur, nom in futurs.items():
            resultats[nom] = futur.result()
    except KeyboardInterrupt:
        dire("  arrêt demandé : les essais en cours se closent", journal)
        arret.set()
        pool.shutdown(wait=True, cancel_futures=True)
        resultats = lire_dossier(dossier)
    finally:
        arret.set()
        pool.shutdown(wait=True)
    for f in fiches:
        resultats.setdefault(f["nom"], {})
    lignes, verts = bilan(resultats)
    with open(os.path.join(dossier, "bilan.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lignes) + "\n")
    for ligne in lignes:
        dire(ligne, journal)
    return 0 if verts == len(fiches) else 1


# --------------------------------------------------------------------------
# Défaire
# --------------------------------------------------------------------------


def machines_nommees():
    """{nom: uuid} de tous les rapports de ce test, UUID connu gagnant."""
    machines = {}
    try:
        fichiers = sorted(
            f
            for f in os.listdir(DOSSIER)
            if f.startswith(OUTIL + "-") and f.endswith(".json")
        )
    except OSError:
        return machines
    for nom in fichiers:
        try:
            with open(os.path.join(DOSSIER, nom), encoding="utf-8") as fh:
                vms = json.load(fh).get("vms") or {}
        except (OSError, ValueError):
            continue
        for vm, uuid in vms.items():
            if uuid or vm not in machines:
                machines[vm] = uuid
    return machines


def detruire(prefixe, journal, dry_run=False):
    """Défait les VM du préfixe et celles que les rapports nomment.

    Les rapports donnent l'UUID noté à la création, vérifié avant d'effacer ;
    le préfixe ramasse TOUT domaine « <prefixe>-* », qu'un rapport le nomme
    ou non : ce sont les restes d'une course tuée avant d'avoir écrit le
    sien. D'où la liste affichée d'abord, et la règle de --prefixe qui en
    écarte les préfixes courts. Rien ne part tant qu'une course tourne, ni
    sans « OUI » tapé."""
    autres = autres_courses()
    if autres:
        dire(
            f"  ⛔ une course tourne ({autres}) : rien ne sera détruit.",
            journal,
        )
        return 1
    nommees = machines_nommees()
    vivantes = set(domaines(prefixe))
    cibles = sorted(vivantes | {n for n in nommees if uuid_de(n)})
    if not cibles:
        dire("  rien à défaire.", journal)
        return 0
    for nom in cibles:
        source = "rapport + UUID" if nommees.get(nom) else "préfixe"
        dire(f"    {nom}  ({source})", journal)
    if dry_run:
        dire("  --dry-run : rien ne sera détruit.", journal)
        return 0
    if (
        input(f"\n  Détruire ces {len(cibles)} VM ? (tapez OUI) : ").strip()
        != "OUI"
    ):
        dire("  annulé.", journal)
        return 1
    echecs = 0
    for nom in cibles:
        etat = detruire_vm(nom, nommees.get(nom, ""))
        dire(f"    {nom} : {etat}", journal)
        echecs += etat not in ("yes", "absent")
    return 1 if echecs else 0


# --------------------------------------------------------------------------


def analyser(argv):
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--dry-run", action="store_true", help="le plan seul")
    parseur.add_argument(
        "--detruire",
        action="store_true",
        help="défaire les VM du préfixe et celles des rapports",
    )
    parseur.add_argument(
        "--saveurs",
        default="",
        help="saveurs retenues, séparées par des virgules",
    )
    parseur.add_argument(
        "--distros", default="", help="distributions retenues (virgules)"
    )
    parseur.add_argument(
        "--versions", default="", help="versions retenues (virgules)"
    )
    parseur.add_argument(
        "--parallele",
        type=int,
        default=PARALLELE,
        help=f"VM menées à la fois (défaut {PARALLELE},"
        f" {MEMOIRE_MO} Mo chacune)",
    )
    parseur.add_argument(
        "--garder", action="store_true", help="garder les VM après leur essai"
    )
    parseur.add_argument(
        "--prefixe", default=PREFIXE, help=f"préfixe des VM (défaut {PREFIXE})"
    )
    parseur.add_argument(
        "--reconstruire-client",
        action="store_true",
        help=f"reconstruire l'image {IMAGE_CLIENT} sans cache",
    )
    parseur.add_argument(
        "--bilan",
        default="",
        help="réafficher le tableau d'un dossier de résultats",
    )
    args = parseur.parse_args(argv)
    if args.parallele < 1:
        parseur.error("--parallele vaut au moins 1")
    if not re.fullmatch(r"[a-z][a-z0-9]{2,15}", args.prefixe):
        # Un préfixe court ou vide ferait ramasser par « --detruire » des
        # machines qui ne sont pas les siennes.
        parseur.error("--prefixe : 3 à 16 minuscules ou chiffres")
    return parseur, args


def main(argv=None):
    parseur, args = analyser(sys.argv[1:] if argv is None else argv)
    os.makedirs(DOSSIER, exist_ok=True)
    stamp = horodatage()
    journal = os.path.join(DOSSIER, f"{OUTIL}-{stamp}.log")
    if args.bilan:
        lignes, verts = bilan(lire_dossier(args.bilan))
        print("\n".join(lignes))
        return 0 if verts == len(lignes) - 1 else 1
    if args.detruire:
        return detruire(args.prefixe, journal, args.dry_run)
    todo = charger_todo()
    try:
        combos = matrice(
            todo._QEMU_DESKTOP_RELEASES,
            liste_option(args.saveurs),
            liste_option(args.distros),
            liste_option(args.versions),
        )
    except ValueError as err:
        parseur.error(str(err))
    if not combos:
        parseur.error("aucune combinaison ne passe ces filtres")
    from script.qemu import deploy_qemu

    empreinte = (
        "$6$<empreinte>"
        if args.dry_run
        else empreinte_mot_de_passe(MOT_DE_PASSE)
    )
    fuseau_locale = regional(todo, deploy_qemu)
    fiches = [
        fiche(todo, deploy_qemu, c, args.prefixe, empreinte, fuseau_locale)
        for c in combos
    ]
    dire(f"  journal : {journal}", journal)
    dire(f"  {len(fiches)} VM, {args.parallele} à la fois", journal)
    dire(f"  fuseau {fuseau_locale[0]}, locale {fuseau_locale[1]}", journal)
    avertir_ressources(args.parallele, len(fiches), args.garder, journal)
    afficher_plan(fiches, journal)
    if args.dry_run:
        dire("  --dry-run : rien ne sera créé.", journal)
        return 0
    if not prealables(fiches, args.prefixe, args, journal):
        return 2
    return courir(fiches, args, journal, stamp)


if __name__ == "__main__":
    sys.exit(main())
