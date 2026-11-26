#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Une forge Forgejo dans une VM QEMU locale, prête à recevoir des pushes.

`deployer` mène les étapes dans l'ordre et s'arrête à la première qui
échoue : la VM (script/qemu/deploy_qemu.py, sous sudo), l'attente de SSH,
le code de CE checkout déposé par un bundle git (la VM ne joint jamais
GitHub pour le code), .venv.erplibre seul — pas d'Odoo —, puis
l'installateur Forgejo du dépôt avec push-to-create, inscriptions fermées,
dépôts privés par défaut et push de clone superficiel accepté. Il amorce
enfin la forge par son API : un jeton créé avec le mot de passe
administrateur et la clé SSH publique déposée sur ce compte.

Le mot de passe administrateur est tiré au hasard et passé par l'entrée
standard : il n'apparaît ni dans une ligne de commande ni dans le journal.
L'appelant décide de le ranger ou de le montrer.

Chaque étape finie appelle `etape(nom, ok, detail)`, qui rend `ok` ;
les commandes lancées et leur sortie vont au `journal`.

Le minuteur des miroirs (`forge_sync`) s'installe à part, sur une forge
déjà prête, par `installer_synchro` ; `ecrire_config_synchro`,
`lancer_passe` et `lire_etat_synchro` le pilotent par SSH, `sudo -n` sur
l'hôte, sans jamais lui envoyer de secret.
"""

import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import time

RACINE = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from script.git import forgejo_client as fc  # noqa: E402

UTILISATEUR = "erplibre"
DISTRO, VERSION = "ubuntu", "24.04"
VCPUS = 4
MEMOIRE_MO = 4096
DISQUE_GO = 60
PORT_HTTP = 3000
PORT_SSH = 2222

DELAI_CREATION = 1800
DELAI_SSH = 900
DELAI_CODE = 900
DELAI_INSTALL = 3600

# La VM est neuve et jetable : sa clé d'hôte n'est connue nulle part, et
# une VM recréée à la même adresse en porte une autre. Ces options ne
# servent qu'aux commandes d'installation ; le push passe par
# `enregistrer_cle_hote`.
OPTIONS_SSH = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "LogLevel=ERROR",
]
ETAPES = ("vm", "ssh", "cloud-init", "code", "venv", "forgejo", "api")

# Un hôte de forge déjà connu (pas une VM créée par cette session) : sa clé
# d'hôte se vérifie, une clé nouvelle s'accepte et se retient.
OPTIONS_SSH_CONNU = [
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "StrictHostKeyChecking=accept-new",
    "-o",
    "LogLevel=ERROR",
]

# Le minuteur des miroirs (`forge_sync`) : les fichiers copiés depuis CE
# checkout, le dossier qui les reçoit dans le compte distant, le script
# installé, et le délai d'une passe (TimeoutStartSec de l'unité, plus une
# marge).
SYNCHRO_FICHIERS = (
    "script/forgejo/forge_sync.py",
    "script/forgejo/install_forge_sync.sh",
)
SYNCHRO_DOSSIER = ".erplibre-forge-sync"
SYNCHRO_SCRIPT = "/usr/local/lib/erplibre-forge-sync/forge_sync.py"
DELAI_PASSE = 7200 + 300
DELAI_SYNCHRO = 600


def cle_publique():
    """Le chemin de la clé publique SSH de l'utilisateur, ou ""."""
    for nom in ("id_ed25519.pub", "id_rsa.pub"):
        chemin = os.path.expanduser(f"~/.ssh/{nom}")
        if os.path.exists(chemin):
            return chemin
    return ""


def argv_creation(nom, cle_pub, cache=()):
    """La ligne de deploy_qemu.py, sans « sudo ». `cache` porte les
    drapeaux du cache de téléchargement de l'hôte (« --cache-ca … » ou
    « --cache-bypass »), que l'appelant choisit."""
    argv = [
        os.path.join(RACINE, ".venv.erplibre/bin/python"),
        os.path.join(RACINE, "script/qemu/deploy_qemu.py"),
        "--distro",
        DISTRO,
        "--version",
        VERSION,
        "--name",
        nom,
        "--vcpus",
        str(VCPUS),
        "--memory",
        str(MEMOIRE_MO),
        "--disk-size",
        f"{DISQUE_GO}G",
        "--no-upgrade",
    ]
    if cle_pub:
        argv += ["--ssh-key", cle_pub]
    return argv + list(cache)


def commande_forgejo(admin, preambule="true"):
    """La commande distante qui installe Forgejo depuis le checkout de la
    VM, avec le compte administrateur `admin`. Le mot de passe arrive par
    l'entrée standard, lu AVANT `preambule` : une commande du préambule qui
    lirait l'entrée standard ne peut plus le consommer."""
    reglages = {
        "FORGEJO_ADMIN_USER": admin,
        "FORGEJO_HTTP_PORT": str(PORT_HTTP),
        "FORGEJO_SSH_PORT": str(PORT_SSH),
        "FORGEJO_PUSH_CREATE": "1",
        "FORGEJO_DISABLE_REGISTRATION": "1",
        "FORGEJO_DEFAULT_PRIVATE": "1",
        "FORGEJO_SHALLOW_PUSH": "1",
    }
    exports = " ".join(f"{k}={shlex.quote(v)}" for k, v in reglages.items())
    return (
        "IFS= read -r FORGEJO_ADMIN_PASSWORD && export FORGEJO_ADMIN_PASSWORD"
        f" && {{ {preambule}; }} </dev/null"
        f" && cd ~/git/erplibre && env {exports}"
        " ./script/forgejo/install_forgejo.sh"
    )


def urls(ip):
    """(URL web, base SSH des dépôts) de la forge à l'adresse `ip`."""
    return f"http://{ip}:{PORT_HTTP}", f"ssh://git@{ip}:{PORT_SSH}"


def _lancer(argv, journal, delai, entree=None):
    """Lance `argv`, sortie au journal. Rend le code, ou None si la
    commande n'a pas abouti dans son délai."""
    try:
        with open(journal, "a", encoding="utf-8") as fh:
            fh.write("── " + " ".join(shlex.quote(a) for a in argv) + "\n")
            fh.flush()
            fini = subprocess.run(
                argv,
                input=entree,
                text=True,
                stdin=None if entree is not None else subprocess.DEVNULL,
                stdout=fh,
                stderr=subprocess.STDOUT,
                timeout=delai,
            )
    except (OSError, subprocess.SubprocessError) as souci:
        with open(journal, "a", encoding="utf-8") as fh:
            fh.write(f"✗ {souci}\n")
        return None
    return fini.returncode


def ssh(cible, commande, journal, delai, entree=None, options=None):
    """Lance `commande` dans la VM, sortie au journal. Rend le code, ou
    None si elle n'a pas abouti dans son délai. `options` remplace
    `OPTIONS_SSH` (None)."""
    options = OPTIONS_SSH if options is None else options
    return _lancer(["ssh", *options, cible, commande], journal, delai, entree)


def ssh_sortie(cible, commande, delai, options=None, entree=None):
    """(code, sortie standard) de `commande` sur `cible`, rien au journal ;
    code None quand elle n'a pas abouti dans son délai."""
    options = OPTIONS_SSH if options is None else options
    try:
        fini = subprocess.run(
            ["ssh", *options, cible, commande],
            input=entree,
            stdin=None if entree is not None else subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=delai,
        )
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return fini.returncode, fini.stdout


def installer_synchro(
    cible, journal, compte, options=None, calendrier="hourly"
):
    """Installe ou met à niveau le minuteur des miroirs sur `cible` : les
    `SYNCHRO_FICHIERS` de CE checkout copiés dans ~/`SYNCHRO_DOSSIER`,
    puis `install_forge_sync.sh` avec le compte `compte`, qui reçoit le
    jeton créé sur l'hôte. Rejouer met à niveau le script de l'hôte. Rend
    vrai quand tout a abouti ; un compte invalide rend faux sans rien
    lancer."""
    if not fc.nom_organisation_valide(compte or "") or not re.match(
        r"^[-A-Za-z0-9 :*/,.~]+$", calendrier or ""
    ):
        return False
    options = OPTIONS_SSH if options is None else options
    commande = (
        f"env FORGE_SYNC_ACCOUNT={shlex.quote(compte)}"
        f" FORGE_SYNC_CALENDAR={shlex.quote(calendrier)}"
        f" bash ~/{SYNCHRO_DOSSIER}/install_forge_sync.sh"
    )
    for argv in (
        ["ssh", *options, cible, f"mkdir -p ~/{SYNCHRO_DOSSIER}"],
        [
            "scp",
            *options,
            *(os.path.join(RACINE, f) for f in SYNCHRO_FICHIERS),
            f"{cible}:{SYNCHRO_DOSSIER}/",
        ],
        ["ssh", *options, cible, commande],
    ):
        if _lancer(argv, journal, DELAI_SYNCHRO) != 0:
            return False
    return True


def ecrire_config_synchro(cible, config, journal, options=None):
    """Fusionne `config` (`forge_mirror.config_synchro`) dans celle du
    minuteur de `cible`, par « sudo -n » : le JSON passe par l'entrée
    standard, jamais par la ligne de commande. Rend vrai si elle est
    acceptée."""
    return (
        ssh(
            cible,
            f"sudo -n /usr/bin/python3 -I {SYNCHRO_SCRIPT} configurer",
            journal,
            DELAI_SYNCHRO,
            json.dumps(config),
            options,
        )
        == 0
    )


_PAIRE = re.compile(r"^[A-Za-z0-9][-.\w]{0,39}/[-.\w]{1,100}$", re.ASCII)


def retirer_paires_synchro(cible, depots, journal, options=None):
    """Retire de la configuration du minuteur de `cible` les paires des
    dépôts de travail `depots` (« propriétaire/dépôt »), par « sudo -n ».
    Un hôte sans le script du minuteur n'a aucune paire : la commande
    réussit sans rien lancer. Rend vrai quand elle aboutit ; un nom qui
    n'a pas la forme d'un dépôt rend faux sans rien lancer."""
    depots = list(depots)
    if not depots or not all(
        isinstance(d, str) and _PAIRE.match(d) for d in depots
    ):
        return not depots
    noms = " ".join(shlex.quote(d) for d in depots)
    return (
        ssh(
            cible,
            f"test ! -e {SYNCHRO_SCRIPT} || sudo -n /usr/bin/python3 -I"
            f" {SYNCHRO_SCRIPT} retirer {noms}",
            journal,
            DELAI_SYNCHRO,
            "",
            options,
        )
        == 0
    )


def lancer_passe(cible, journal, options=None):
    """Lance une passe du minuteur sur `cible` et l'attend. Rend le code
    de « systemctl start », ou None hors délai. systemd rend 0 sans rien
    lancer quand une condition de l'unité manque (pas de configuration ou
    de jeton) : l'appelant compare le « debut » de l'état avant et
    après."""
    return ssh(
        cible,
        "sudo -n systemctl start erplibre-forge-sync.service",
        journal,
        DELAI_PASSE,
        "",
        options,
    )


def lire_etat_synchro(cible, options=None):
    """L'état du minuteur de `cible` (« forge_sync.py etat », en JSON
    décodé), ou None : minuteur absent, sudo refusé, délai dépassé ou
    sortie illisible."""
    code, sortie = ssh_sortie(
        cible,
        f"sudo -n /usr/bin/python3 -I {SYNCHRO_SCRIPT} etat",
        DELAI_SYNCHRO,
        options,
    )
    if code != 0:
        return None
    try:
        etat = json.loads(sortie)
    except ValueError:
        return None
    return etat if isinstance(etat, dict) else None


def attendre_ssh(cible, delai=DELAI_SSH, pause=5):
    """Vrai dès qu'une commande aboutit en ssh : le port s'ouvre avant que
    cloud-init ait posé le compte."""
    fin = time.time() + delai
    while time.time() < fin:
        try:
            fini = subprocess.run(
                ["ssh", *OPTIONS_SSH, cible, "true"],
                capture_output=True,
                timeout=30,
            )
            if fini.returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(pause)
    return False


def uuid_libvirt(nom):
    """L'UUID du domaine libvirt `nom`, ou "". C'est lui qui identifie la
    machine : un nom se réutilise.

    virsh passe par `qemu_privilege.virsh_argv` : sans sudo quand libvirt
    est joignable, sinon par un sudo qui ne demande rien — un ticket expiré
    pendant une longue création rend "" au lieu d'une invite muette."""
    from script.todo import qemu_privilege

    with qemu_privilege.sudo_non_interactif():
        argv = qemu_privilege.virsh_argv("domuuid", nom)
    try:
        res = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return "" if res.returncode else res.stdout.strip()


def git_hote(*args, delai=600):
    """(code, sortie) de git sur le checkout de l'hôte."""
    fini = subprocess.run(
        ["git", "-C", RACINE, *args],
        capture_output=True,
        text=True,
        timeout=delai,
    )
    return fini.returncode, fini.stdout.strip()


def deposer_code(cible, dossier, journal, exerces=()):
    """Le bundle de HEAD copié dans la VM et cloné dans ~/git/erplibre,
    puis les fichiers `exerces` de l'arbre de travail par-dessus (chemins
    relatifs à la racine) : le code qu'on veut voir tourner, commité ou
    non. Rend vrai quand tout a abouti."""
    code, head = git_hote("rev-parse", "HEAD")
    bundle = os.path.join(dossier, "erplibre.bundle")
    os.makedirs(dossier, exist_ok=True)
    if code or git_hote("bundle", "create", bundle, "HEAD")[0]:
        return False
    for argv in (
        [
            "ssh",
            *OPTIONS_SSH,
            cible,
            "command -v git >/dev/null || sudo DEBIAN_FRONTEND=noninteractive"
            " apt-get -o DPkg::Lock::Timeout=600 install -y git",
        ],
        ["scp", *OPTIONS_SSH, bundle, f"{cible}:erplibre.bundle"],
        [
            "ssh",
            *OPTIONS_SSH,
            cible,
            "test -e ~/git/erplibre || { mkdir -p ~/git && git -c"
            " advice.detachedHead=false clone -q ~/erplibre.bundle"
            f" ~/git/erplibre && git -C ~/git/erplibre checkout -q {head}; }}",
        ],
        *(
            [
                "scp",
                *OPTIONS_SSH,
                os.path.join(RACINE, f),
                f"{cible}:git/erplibre/{f}",
            ]
            for f in exerces
        ),
    ):
        if _lancer(argv, journal, DELAI_CODE) != 0:
            return False
    return True


def amorcer(web, admin, mot_de_passe, cle_pub, nom_jeton):
    """(client, jeton, version) de la forge neuve : un jeton aux portées
    de `forgejo_client.PORTEES` créé avec le mot de passe administrateur,
    puis la clé publique `cle_pub` déposée sur ce compte. Lève
    `ErreurForgejo` ou OSError."""
    amorce = fc.ClientForgejo(web, identifiants=(admin, mot_de_passe))
    jeton = amorce.creer_jeton(nom_jeton, fc.PORTEES)
    client = fc.ClientForgejo(web, jeton_api=jeton)
    version = client.version()
    if cle_pub:
        with open(cle_pub, encoding="utf-8") as fh:
            client.ajouter_cle_ssh(nom_jeton, fh.read())
    return client, jeton, version


def enregistrer_cle_hote(ip, port=PORT_SSH, connus=None):
    """Remplace dans `connus` (~/.ssh/known_hosts par défaut) la clé
    d'hôte de « [ip]:port » par celle que la forge présente maintenant.

    git pousse par l'ssh de l'utilisateur, qui demanderait sur le terminal
    d'accepter une clé inconnue — une invite par push parallèle — et
    refuserait celle d'une VM recréée à la même adresse. La forge vient
    d'être créée par ce processus : sa clé est la bonne. Rend vrai quand
    une clé a été écrite."""
    connus = connus or os.path.expanduser("~/.ssh/known_hosts")
    hote = f"[{ip}]:{port}"
    try:
        lues = subprocess.run(
            ["ssh-keyscan", "-T", "15", "-p", str(port), ip],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    cles = [
        ligne
        for ligne in lues.splitlines()
        if ligne.strip() and not ligne.startswith("#")
    ]
    if not cles:
        return False
    try:
        subprocess.run(
            ["ssh-keygen", "-R", hote, "-f", connus],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    os.makedirs(os.path.dirname(connus), mode=0o700, exist_ok=True)
    with open(connus, "a", encoding="utf-8") as fh:
        for ligne in cles:
            fh.write(ligne + "\n")
    return True


def deployer(
    nom,
    admin,
    journal,
    dossier,
    adresse_de,
    venv_cmd,
    etape,
    cache=(),
    exerces=(),
    cle_pub=None,
    preambule="true",
):
    """Crée la VM `nom` et y installe une forge amorcée. Rend un dict
    (« nom », « uuid », « ip », « web », « base_ssh », « admin »,
    « mot_de_passe », « jeton », « version », « client ») ou, à la première
    étape échouée, None — la VM créée reste alors en place et
    `etape("vm", …)` a reçu son nom.

    `adresse_de(nom)` rend l'IPv4 de la VM, `venv_cmd` est la commande qui
    pose .venv.erplibre depuis la racine du checkout de la VM, `cache` les
    drapeaux du cache de téléchargement de l'hôte (`argv_creation`).

    `preambule` est le fragment shell qui attend la fin de cloud-init et
    exporte l'autorité du cache (`QemuInstallMixin._qemu_cloud_init_wait`).
    SSH répond pendant le premier démarrage, avant que cloud-init ait posé
    cette autorité : un téléchargement lancé alors échoue sur « self-signed
    certificate in certificate chain ». Il tourne seul dans l'étape
    « cloud-init », puis en tête de l'installation du venv et de celle de
    Forgejo, dont la session doit porter ses exports."""
    # Le fragment se termine souvent par « ; » : collé devant « ; cd … »,
    # il ferait un « ;; » que bash refuse.
    preambule = preambule.strip().rstrip(";").strip() or "true"
    cle_pub = cle_publique() if cle_pub is None else cle_pub
    if not cle_pub:
        etape("vm", False, "no public key in ~/.ssh")
        return None
    if uuid_libvirt(nom):
        etape("vm", False, f"{nom} already exists")
        return None
    code = _lancer(
        ["sudo", *argv_creation(nom, cle_pub, cache)], journal, DELAI_CREATION
    )
    # deploy_qemu rend 0 quand la VM est créée ; l'UUID n'est qu'une
    # trace, illisible quand le ticket sudo a expiré pendant la création.
    uuid = uuid_libvirt(nom)
    if not etape("vm", code == 0, nom):
        return None
    ip = adresse_de(nom) or ""
    cible = f"{UTILISATEUR}@{ip}"
    if not etape("ssh", bool(ip) and attendre_ssh(cible), ip):
        return None
    if not etape(
        "cloud-init", ssh(cible, preambule, journal, DELAI_INSTALL, "") == 0
    ):
        return None
    if not etape("code", deposer_code(cible, dossier, journal, exerces)):
        return None
    venv = f"{preambule}; cd ~/git/erplibre && {venv_cmd}"
    if not etape("venv", ssh(cible, venv, journal, DELAI_INSTALL, "") == 0):
        return None
    mot_de_passe = secrets.token_urlsafe(24)
    code = ssh(
        cible,
        commande_forgejo(admin, preambule),
        journal,
        DELAI_INSTALL,
        mot_de_passe + "\n",
    )
    if not etape("forgejo", code == 0):
        return None
    web, base_ssh = urls(ip)
    try:
        client, jeton, version = amorcer(
            web,
            admin,
            mot_de_passe,
            cle_pub,
            f"{nom}-{time.strftime('%Y%m%d-%H%M%S')}",
        )
    except (fc.ErreurForgejo, OSError) as exc:
        etape("api", False, str(exc))
        return None
    etape("api", True, f"Forgejo {version}")
    return {
        "nom": nom,
        "uuid": uuid,
        "ip": ip,
        "web": web,
        "base_ssh": base_ssh,
        "admin": admin,
        "mot_de_passe": mot_de_passe,
        "jeton": jeton,
        "version": version,
        "client": client,
    }
