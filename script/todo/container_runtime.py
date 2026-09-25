#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Docker et Podman derrière une seule interface.

Les deux moteurs répondent aux mêmes sous-commandes — « images », « ps »,
« network ls » — mais ne se posent pas de la même façon : Docker parle à un
démon par une socket que root possède, Podman s'exécute sans démon sous le
compte de l'appelant. Ce fichier rend des FAITS et n'affiche rien : quel
binaire est là, quelle version, si le moteur répond sans sudo, et sinon
pourquoi.

Le « pourquoi » est l'essentiel. « permission denied » sur la socket a trois
causes que rien ne distingue à l'œil : le service est à l'arrêt, le compte
n'est pas dans le groupe, ou il y est depuis une session ouverte AVANT
l'ajout — un groupe n'entre en vigueur qu'à l'ouverture de session suivante,
et c'est la cause qu'on soupçonne en dernier.

Appartenir au groupe « docker » équivaut à être root : la socket accepte de
monter n'importe quel chemin de l'hôte dans un conteneur privilégié. Le fait
est rendu ici pour que l'appelant le DISE, jamais pour qu'il le taise.
"""

import os
import shutil
import subprocess

MOTEURS = ("docker", "podman")

# Le groupe dont l'appartenance ouvre la socket du démon Docker.
GROUPE_DOCKER = "docker"

# Les sockets que le client Docker essaie, dans l'ordre. La variable
# DOCKER_HOST l'emporte sur les deux : un moteur distant ou rootless s'annonce
# par elle, et une socket locale absente ne prouve alors rien.
SOCKETS_DOCKER = (
    "/var/run/docker.sock",
    "/run/docker.sock",
)

# Les commandes de composition, dans l'ordre de préférence. Le greffon v2
# (« docker compose ») et le binaire v1 (« docker-compose ») coexistent selon
# les distributions ; Podman délègue à podman-compose, qu'il faut parfois
# appeler directement.
COMPOSE = {
    "docker": (["docker", "compose"], ["docker-compose"]),
    "podman": (["podman", "compose"], ["podman-compose"]),
}


def lancer(cmd, timeout=10):
    """Lance `cmd` et rend (code, sortie). Ne lève jamais.

    La sortie mêle stdout et stderr : c'est le message d'erreur du moteur qui
    porte le diagnostic, et il part sur stderr. Un binaire absent ou un moteur
    qui ne rend pas la main dans le délai valent un code non nul, comme un
    refus — l'appelant n'a qu'un cas à traiter.
    """
    try:
        fin = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        return fin.returncode, fin.stdout or ""
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except OSError as err:
        return 127, str(err)


def binaire(moteur):
    """Le chemin du binaire du moteur, ou None."""
    return shutil.which(moteur)


def version(moteur, lanceur=lancer):
    """La version du CLIENT, ou None. Le client répond sans démon."""
    code, sortie = lanceur([moteur, "--version"])
    if code != 0:
        return None
    return sortie.strip() or None


def repond(moteur, sudo=False, docker_host=None, lanceur=lancer):
    """(True, "") si le moteur répond, sinon (False, sa plainte).

    « info » est la seule sous-commande qui exige le démon ET les droits :
    « --version » réussit sur une machine où rien ne tourne.

    `docker_host` vise une autre socket que celle du défaut, par un préfixe
    « env » plutôt que par l'environnement du processus : la commande reste
    une liste que l'appelant peut afficher telle quelle, et c'est celle qu'il
    devra reproduire.
    """
    cmd = []
    if sudo:
        cmd += ["sudo", "-n"]
    if docker_host:
        cmd += ["env", f"DOCKER_HOST={docker_host}"]
    code, sortie = lanceur(cmd + [moteur, "info"])
    if code == 0:
        return True, ""
    return False, sortie.strip()


def dans_le_groupe(groupe=GROUPE_DOCKER):
    """Le compte courant appartient-il au groupe, DANS CETTE SESSION ?

    os.getgroups() rend les groupes de la session, et non ceux du fichier
    /etc/group : c'est exactement la distinction qui compte. Un compte ajouté
    au groupe il y a dix minutes n'y est pas encore ici, et c'est ce qui rend
    le refus incompréhensible.
    """
    try:
        import grp

        gid = grp.getgrnam(groupe).gr_gid
    except (KeyError, ImportError):
        return False
    return gid in os.getgroups()


def declare_dans_le_groupe(groupe=GROUPE_DOCKER):
    """Le compte est-il inscrit au groupe dans /etc/group ?

    Vrai dès l'ajout, là où `dans_le_groupe` reste faux jusqu'à la prochaine
    ouverture de session : l'écart entre les deux EST le diagnostic.
    """
    try:
        import grp
        import pwd

        membres = set(grp.getgrnam(groupe).gr_mem)
    except (KeyError, ImportError):
        return False
    try:
        compte = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return False
    return compte in membres


def socket_docker():
    """La socket que le client Docker atteindra, ou None."""
    hote = os.environ.get("DOCKER_HOST")
    if hote:
        return hote
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    candidates = list(SOCKETS_DOCKER)
    if runtime:
        # La socket du mode rootless, sous le répertoire de session.
        candidates.insert(0, os.path.join(runtime, "docker.sock"))
    for chemin in candidates:
        if os.path.exists(chemin):
            return chemin
    return None


def noyau_sans_modules():
    """L'arbre de modules du noyau EN COURS a-t-il disparu ?

    Mettre le noyau à jour remplace /lib/modules/<version> par celui de la
    nouvelle : le noyau qui tourne garde les modules DÉJÀ chargés et ne peut
    plus en charger aucun. Docker sans privilège meurt alors en posant ses
    règles iptables, sur « Extension addrtype revision 0 not supported,
    missing kernel module? » — un message qui n'accuse ni Docker, ni
    l'installation, ni le mode sans privilège. Le redémarrage est la seule
    issue, et c'est ce qu'il faut dire.

    Podman peut continuer de répondre dans cet état : netavark passe par
    nf_tables, généralement déjà chargé. Les deux moteurs ne tombent donc pas
    ensemble, ce qui égare encore un peu plus.
    """
    return not os.path.isdir("/lib/modules/" + os.uname().release)


def socket_rootless():
    """La socket d'un démon par compte, ou None.

    Elle vit sous le répertoire de session, là où le client Docker ne regarde
    PAS : sans DOCKER_HOST, il s'adresse à la socket du démon de root. Un mode
    sans privilège parfaitement installé paraît alors mort.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        return None
    chemin = os.path.join(runtime, "docker.sock")
    return chemin if os.path.exists(chemin) else None


def service_actif(unite, lanceur=lancer):
    """True/False si systemd répond, None là où il n'y a pas systemd."""
    if not shutil.which("systemctl"):
        return None
    code, sortie = lanceur(["systemctl", "is-active", unite])
    if sortie.strip() in ("", "unknown"):
        return None
    return code == 0


def rootless(moteur, lanceur=lancer):
    """Le moteur tourne-t-il sans privilège ? None si indéterminable.

    Podman sans root est le cas ordinaire ; Docker ne l'est qu'installé
    exprès. « info » nomme lui-même le mode, c'est donc lui qu'on interroge
    plutôt que de déduire du compte courant.
    """
    code, sortie = lanceur([moteur, "info"])
    if code != 0:
        return None
    for ligne in sortie.lower().splitlines():
        nu = ligne.strip()
        if nu.startswith("rootless:"):
            # Podman le rend en champ : « rootless: true ».
            return nu.split(":", 1)[1].strip() in ("true", "yes")
        if nu == "rootless":
            # Docker le liste sous « Security Options », sans valeur : sa
            # PRÉSENCE est la réponse. Chercher « true » sur cette ligne
            # rendrait « en root » un démon qui n'y est pas.
            return True
    return os.getuid() != 0 and moteur == "podman"


def compose(moteur, lanceur=lancer):
    """La commande de composition du moteur, en liste, ou None."""
    for cmd in COMPOSE.get(moteur, ()):
        if not shutil.which(cmd[0]):
            continue
        code, _ = lanceur(cmd + ["version"])
        if code == 0:
            return cmd
    return None


def _raison(moteur, plainte, lanceur=lancer):
    """Pourquoi le moteur ne répond pas, en un CODE et non en une phrase.

    La plainte du moteur dit QUOI ; l'état du système dit POURQUOI, et c'est
    cela que l'opérateur ne peut pas deviner. Le code laisse la phrase à
    l'affichage, qui sait dans quelle langue il parle — une phrase rendue ici
    serait dans celle de qui l'a écrite.
    """
    bas = plainte.lower()
    if "permission denied" in bas or "permission refusée" in bas:
        if moteur == "docker":
            if declare_dans_le_groupe() and not dans_le_groupe():
                return "groupe_hors_session"
            if not declare_dans_le_groupe():
                return "groupe_absent"
        return "droits_socket"
    if "cannot connect" in bas or "is the docker daemon running" in bas:
        # Le noyau d'abord : il explique un démon qui refuse de naître alors
        # que tout le reste est en place, et rien d'autre ne l'explique.
        if noyau_sans_modules():
            return "noyau_perime"
        actif = service_actif(f"{moteur}.service", lanceur=lanceur)
        if actif is False:
            return "service_arrete"
        if actif is None:
            return "systemd_ignore"
        return "socket_muette"
    if "timeout" in bas:
        return "delai"
    return ""


def etat(moteur, lanceur=lancer):
    """Tout ce qu'on sait du moteur, en un dictionnaire.

    `sans_sudo` est le seul champ qui décide d'un usage : les autres
    expliquent. `avec_sudo` n'est interrogé que s'il le faut, « sudo -n »
    ne posant jamais de question de mot de passe.
    """
    chemin = binaire(moteur)
    fiche = {
        "moteur": moteur,
        "binaire": chemin,
        "version": None,
        "sans_sudo": False,
        "avec_sudo": False,
        "raison": "",
        "rootless": None,
        "compose": None,
        "service": None,
        "socket": None,
        "docker_host": None,
    }
    if not chemin:
        return fiche
    fiche["version"] = version(moteur, lanceur=lanceur)
    fiche["service"] = service_actif(f"{moteur}.service", lanceur=lanceur)
    if moteur == "docker":
        fiche["socket"] = socket_docker()
    ok, plainte = repond(moteur, lanceur=lanceur)

    # La socket d'un démon par compte n'est pas celle du défaut : un mode sans
    # privilège installé et vivant paraît mort tant que DOCKER_HOST ne la
    # nomme pas. On l'essaie AVANT de conclure au refus, et on rend la valeur
    # à poser dans l'environnement.
    if not ok and moteur == "docker" and not os.environ.get("DOCKER_HOST"):
        socket = socket_rootless()
        if socket:
            hote = f"unix://{socket}"
            ok, plainte = repond(moteur, docker_host=hote, lanceur=lanceur)
            if ok:
                fiche["docker_host"] = hote

    fiche["sans_sudo"] = ok
    if ok:
        fiche["rootless"] = rootless(moteur, lanceur=lanceur)
        fiche["compose"] = compose(moteur, lanceur=lanceur)
        return fiche
    fiche["raison"] = _raison(moteur, plainte, lanceur=lanceur)
    fiche["avec_sudo"] = repond(moteur, sudo=True, lanceur=lanceur)[0]
    return fiche


def etats(lanceur=lancer):
    """Les fiches des deux moteurs, Docker d'abord."""
    return [etat(m, lanceur=lanceur) for m in MOTEURS]


def utilisable(fiche):
    """Le moteur répond-il, d'une façon ou d'une autre ?"""
    return bool(fiche["sans_sudo"] or fiche["avec_sudo"])


def moteur_par_defaut(fiches):
    """Le moteur à proposer, ou None si aucun ne répond.

    Celui qui répond SANS sudo d'abord : un menu qui réclame un mot de passe
    à chaque liste d'images ne se laisse pas utiliser.
    """
    for fiche in fiches:
        if fiche["sans_sudo"]:
            return fiche["moteur"]
    for fiche in fiches:
        if fiche["avec_sudo"]:
            return fiche["moteur"]
    return None


def commande(fiche, args):
    """La commande complète à lancer pour ce moteur, préfixée si nécessaire.

    Le préfixe sudo n'est posé que là où il est la SEULE voie : le décider ici
    évite que chaque écran refasse le test à sa façon.
    """
    prefixe = [] if fiche["sans_sudo"] else ["sudo"]
    hote = fiche.get("docker_host")
    if hote:
        prefixe += ["env", f"DOCKER_HOST={hote}"]
    return prefixe + [fiche["moteur"]] + list(args)
