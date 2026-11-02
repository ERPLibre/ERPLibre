#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""coturn et ntfy s'installent-ils, se vérifient-ils et se désinstallent-ils
sur de vraies machines Debian et Arch ?

Une VM par système et par scénario, l'une après l'autre :
`long-call-infra-debian` (Debian 13) et `long-call-infra-arch` (Arch, image
du jour). Il vit dans long_test/
et non dans test/ : il crée de vraies machines et y installe des paquets.

CE QU'IL ENVOIE : LES BRIQUES DU MENU

Chaque étape est celle du menu « Infrastructure d'appel » de todo.py, sans
ses questions : les `Answers` sont écrites ici, et la suite passe par
`script/todo/call_infra.py` — sonde, plan, script d'installation, pare-feu,
écriture de l'état, vérification, désinstallation. Un test qui installerait
par ses propres soins prouverait son chemin, pas celui du produit. Chaque
étape du produit part dans sa propre session ssh, comme le menu lance
chaque script par un appel à part.

LE VERDICT EST L'ÉTAT DE LA MACHINE

Les allocations TURN réelles et la santé de ntfy sont lues depuis cette
machine par `check_local`, comme le menu le fait ; la désinstallation est
jugée sur ce qui reste sur l'hôte (unité, dossier de l'outil, règles du
pare-feu, configuration remise) et sur les ports vus d'ici.

CINQ SCÉNARIOS

Le développement (`dev`) : sur Debian, ufw y est activé (ssh d'abord), ntfy
y est d'abord posé à l'ancienne par install_ntfy.sh avec un compte de
téléphone, puis l'outil installe les deux services avec un certificat d'une
autorité locale (local_cert) et ouvre ses ports. Arch couvre le chemin http
sans pare-feu, après la préparation pacman du menu.

La production (`prod`), sur chaque système : les deux services derrière un
nginx que l'outil installe (sur Arch, sa ligne include adoptée dans
nginx.conf), un certificat fourni d'une autorité inventée pour
`ntfy.call.exemple.test`, `turn.call.exemple.test` et l'adresse de la VM,
le pare-feu accepté. Puis le crochet de déploiement du produit, lancé à la
main avec RENEWED_LINEAGE sur une fausse lignée (voir `crochets`), une
relance qui ne change rien et la désinstallation, données comprises.

Les serveurs Odoo (`odoo`), sur Debian seulement : coturn et ntfy de
développement avec un certificat fourni, puis trois bases d'un Odoo 18 de
cette machine (le harnais de `mobile_sync_odoo.py`) branchées et débranchées
par les briques de « Ajouter » et « Retirer un serveur Odoo » : compte fixe
sans le module, bascule de coturn en mode secret avec `erplibre_turn`,
second Odoo sans redémarrage, rotation et sa grâce, retrait d'un Odoo qui
laisse l'autre allouer, refus de l'autre mode. Chaque allocation part de
cette machine sous les identifiants qu'Odoo remet à un utilisateur ou à un
invité (`check_through_odoo`). Les bases `call_infra_odoo_*` entrent au
rapport avant d'exister et partent à la fin de la course, ou par
`--detruire`.

Les conteneurs (`conteneur`), sur Debian seulement : une course par moteur
(`--moteur docker|podman|podman-rootless`, les trois par défaut), chacune
sur sa VM neuve. Le moteur absent est proposé par le menu et accepté ;
coturn et ntfy de développement tournent en conteneurs sous le compte que
l'état consigne, un Odoo inventé fait basculer coturn en mode secret (une
seule recréation), le crochet signale le conteneur, la VM redémarre et les
conteneurs reviennent, la relance ne change rien, la désinstallation
emporte moteur, images, comptes et fichier compose. La course `podman`
ajoute, sur la même VM, coturn seul en production sur 443.

La migration (`migration`), sur Debian seulement : paquets, un Odoo 18 de
cette machine branché avec `erplibre_turn` et un téléphone, puis passage
aux conteneurs Podman en root sans rien rebrancher, puis retour aux
paquets quand ntfy le permet. Une image refusée par la limite du registre
(Docker Hub) donne le verdict `limite-registre`, distinct d'un échec.

Chaque course part d'une VM neuve, au même nom : celles d'un système
tournent l'une après l'autre.

  ./long_test/call_infra.py                  # Debian puis Arch, chaque scénario
  ./long_test/call_infra.py --distro arch    # un seul système
  ./long_test/call_infra.py --scenario prod  # un seul scénario
  ./long_test/call_infra.py --scenario odoo  # les serveurs Odoo, Debian
  ./long_test/call_infra.py --scenario conteneur --moteur docker
  ./long_test/call_infra.py --scenario migration   # paquets ↔ conteneurs
  ./long_test/call_infra.py --dry-run        # le plan, rien de créé
  ./long_test/call_infra.py --garder --scenario dev   # garder les VM
  ./long_test/call_infra.py --detruire       # défaire la dernière course
"""

import argparse
import base64
import binascii
import dataclasses
import datetime
import hashlib
import json
import os
import re
import secrets
import shlex
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "long_test"))

import descente  # noqa: E402
from descente import (  # noqa: E402
    Descente,
    Famille,
    capacite_hote,
    cle_publique,
    dernier_rapport,
    descente_vivante,
    detruire,
    detruire_etage1,
    dire,
    drapeaux_cache,
    retirer_alias,
)
import mobile_sync_odoo as mso  # noqa: E402
from script.reverse_proxy import local_cert  # noqa: E402
from script.todo import call_infra as ci  # noqa: E402
from script.todo import call_infra_container as cc  # noqa: E402
from script.todo import call_infra_menu as cim  # noqa: E402
from script.todo import ntfy_mobile as nm  # noqa: E402
from script.todo import odoo_link as ol  # noqa: E402
from script.todo import turn_client  # noqa: E402

OUTIL = "call_infra"
NOM_BASE = "long-call-infra"
# L'utilisateur que deploy_qemu.py crée, avec un sudo sans mot de passe.
UTILISATEUR = "erplibre"

# Le système et la version de deploy_qemu.py, dans l'ordre de la course.
DISTROS = {"debian": "13", "arch": "latest"}

# Le gabarit d'une VM : le minimum du catalogue pour ces deux images. Les
# deux services tiennent dans 2 Gio.
VCPUS = 2
MEMOIRE_MO = 2048
DISQUE_GO = 20
# Ce qu'une course écrit dans le disque creux de la VM, mise à jour
# complète d'Arch comprise : une estimation, comparée à l'espace libre de
# l'hôte, pas aux 20 Go virtuels.
DISQUE_ECRIT_GO = 6
MARGE_RAM_MO = 1024
MARGE_DISQUE_GO = 4

DELAI_CREATION = 1800
DELAI_SSH = 600
# Attente de cloud-init, préparation pacman (mise à jour complète), pose
# d'ufw : un index de paquets à rafraîchir et des téléchargements.
DELAI_PREPARATION = 1800
DELAI_INSTALL = 1800
DELAI_SCRIPT = 300
DELAI_PORT = 3

# Les lignes de sortie qui portent un secret : le mot de passe de
# l'administrateur de ntfy, et les clés et secrets de coturn que lit la
# vérification. Ce sont celles que le menu masque à l'écran ; ici elles sont
# masquées au journal.
SECRETS = (cim.ADMIN_PASSWORD_LINE, *cim.CHECK_HIDDEN)
# Un jeton d'accès de ntfy, que `ntfy token add` imprime au milieu d'une
# ligne : il ouvre les sujets du téléphone tant que la VM vit.
JETON = re.compile(r"tk_[A-Za-z0-9]+")

SCENARIOS_NOMS = ("dev", "prod", "odoo", "conteneur", "migration")

# Les moteurs d'une course `conteneur` : (moteur, rootless) des `Answers`,
# dans l'ordre où leurs courses tournent par défaut.
MOTEURS = {
    "docker": ("docker", False),
    "podman": ("podman", False),
    "podman-rootless": ("podman", True),
}
# Le moteur de la migration : Podman en root.
MOTEUR_MIGRATION = "podman"

# Le verdict d'une course arrêtée par la limite de tirage du registre
# (`@@PULL_FAILED <service> rate-limit`) : ni vert ni échec, la course est
# à relancer plus tard. Il fait sortir le test par 2.
LIMITE_REGISTRE = "limite-registre"
MESSAGE_LIMITE = "limite du registre, réessayer plus tard"

# Les lignes de `check_local` qui doivent être vertes, par scénario et par
# système. En production, `private-denied` est la permission refusée vers
# une adresse privée ; `firewall` n'est requis que là où ufw est actif.
_PROD_CONTROLES = (
    "turn-udp",
    "turn-tcp",
    "turn-tls",
    "private-denied",
    "ntfy-health",
    "cert-expiry",
    "cert-issuer",
)
CONTROLES = {
    "dev": {
        "debian": (
            "turn-udp",
            "turn-tcp",
            "turn-tls",
            "ntfy-health",
            "firewall",
            "service-coturn",
            "service-ntfy",
        ),
        "arch": (
            "turn-udp",
            "turn-tcp",
            "ntfy-health",
            "service-coturn",
            "service-ntfy",
        ),
    },
    "prod": {
        "debian": (
            *_PROD_CONTROLES,
            "firewall",
            "service-coturn",
            "service-ntfy",
        ),
        "arch": (*_PROD_CONTROLES, "service-coturn", "service-ntfy"),
    },
    # En mode secret, les lignes turn-* allouent sous le secret de contrôle,
    # odoo-1 et odoo-2 sous le secret de chacun des deux Odoo branchés.
    "odoo": {
        "debian": (
            "turn-udp",
            "turn-tcp",
            "turn-tls",
            "ntfy-health",
            "firewall",
            "service-coturn",
            "service-ntfy",
            "odoo-1",
            "odoo-2",
        ),
    },
    # Les deux services de développement en conteneurs : les lignes
    # `service-*` lisent l'état du conteneur et l'uid sous lequel il tourne.
    "conteneur": {
        "debian": (
            "turn-udp",
            "turn-tcp",
            "turn-tls",
            "ntfy-health",
            "firewall",
            "service-coturn",
            "service-ntfy",
        ),
    },
    # odoo-1 : l'Odoo du harnais, sous son propre secret.
    "migration": {
        "debian": (
            "turn-udp",
            "turn-tcp",
            "turn-tls",
            "ntfy-health",
            "firewall",
            "service-coturn",
            "service-ntfy",
            "odoo-1",
        ),
    },
}
# coturn seul en production dans un conteneur, TURN sur TLS en 443 : sans
# ntfy ni nginx.
CONTROLES_PROD_COTURN = (
    "turn-udp",
    "turn-tcp",
    "turn-tls",
    "private-denied",
    "cert-expiry",
    "cert-issuer",
    "firewall",
    "service-coturn",
)

# Les étapes de la production après la préparation du système.
_PROD_ETAPES = (
    "certificats",
    "installation",
    "nginx-installe",
    "verification",
    "crochet-fourni",
    "crochet-lignee",
    "crochet-retour",
    "crochet-remise",
    "verification-apres-crochet",
    "rien-a-changer",
    "desinstallation",
    "etat-apres-desinstallation",
    "ports-fermes",
    "desinstallation-vide",
)

# Les étapes des serveurs Odoo après la préparation du système : A sans le
# module, B et C avec, sur le même coturn (voir `scenario_odoo`).
_ODOO_ETAPES = (
    "odoo-harnais",
    "installation",
    "a-fixe",
    "a-par-odoo",
    "a-retire",
    "a-revoque",
    "b-module",
    "b-bascule",
    "b-utilisateur",
    "b-invite",
    "c-module",
    "c-sans-redemarrage",
    "b-et-c",
    "verification-secret",
    "b-rotation",
    "b-grace",
    "c-retire",
    "b-reste",
    "c-revoque",
    "a-refuse",
    "b-retire",
    "desinstallation",
    "bases-supprimees",
)

# La production d'une course `conteneur` (podman) : coturn seul, sur la
# même VM, après la désinstallation du développement.
_CONTENEUR_PROD_ETAPES = (
    "prod-installation",
    "prod-443-non-root",
    "prod-verification",
    "prod-desinstallation",
    "prod-etat-apres-desinstallation",
    "prod-ports-fermes",
)


def _conteneur_etapes(melange=False, production=False):
    """Les étapes d'une course `conteneur` : le développement des deux
    services, le rejeu du mélange en information quand `melange` (avant la
    bascule en mode secret, sur coturn en comptes fixes), la production de
    coturn seul quand `production`."""
    return (
        "vm",
        "ssh",
        "cloud-init",
        "ufw-actif",
        "moteur-propose",
        "installation",
        "moteur-installe",
        "verification",
        "proprietaires",
        *(("melange (information)",) if melange else ()),
        "odoo-secret",
        "odoo-second",
        "relais-prive",
        "crochet-fourni",
        "crochet-lignee",
        "crochet-retour",
        "crochet-remise",
        "redemarrage",
        "verification-apres-redemarrage",
        "rien-a-changer",
        "relance-up",
        "desinstallation",
        "etat-apres-desinstallation",
        "ports-fermes",
        "desinstallation-vide",
        *(_CONTENEUR_PROD_ETAPES if production else ()),
    )


# Les étapes de la migration après la préparation du système.
_MIGRATION_ETAPES = (
    "odoo-harnais",
    "installation",
    "telephone-seme",
    "odoo-branche",
    "odoo-relaie",
    "migration-conteneurs",
    "secrets-identiques",
    "verification-conteneurs",
    "odoo-relaie-conteneurs",
    "telephone-garde",
    "retour-paquets",
    "odoo-relaie-retour",
    "odoo-retire",
    "desinstallation",
    "bases-supprimees",
)

# Les étapes, dans l'ordre, pour le plan et le rapport.
ETAPES = {
    "dev": {
        "debian": (
            "vm",
            "ssh",
            "cloud-init",
            "ufw-actif",
            "ntfy-ancien",
            "telephone-ancien",
            "installation",
            "ntfy-adopte",
            "verification",
            "telephone-garde",
            "rien-a-changer",
            "melange (information)",
            "desinstallation",
            "etat-apres-desinstallation",
            "ports-fermes",
            "desinstallation-vide",
        ),
        "arch": (
            "vm",
            "ssh",
            "cloud-init",
            "pacman",
            "installation",
            "verification",
            "desinstallation",
            "ports-fermes",
            "desinstallation-vide",
        ),
    },
    "prod": {
        "debian": ("vm", "ssh", "cloud-init", "ufw-actif", *_PROD_ETAPES),
        "arch": ("vm", "ssh", "cloud-init", "pacman", *_PROD_ETAPES),
    },
    "odoo": {
        "debian": ("vm", "ssh", "cloud-init", "ufw-actif", *_ODOO_ETAPES),
    },
    "conteneur": {
        "debian": {
            "docker": _conteneur_etapes(melange=True),
            "podman": _conteneur_etapes(production=True),
            "podman-rootless": _conteneur_etapes(),
        },
    },
    "migration": {
        "debian": ("vm", "ssh", "cloud-init", "ufw-actif", *_MIGRATION_ETAPES),
    },
}


def etapes_de(scenario, distro, variante=None):
    """Les étapes d'une course, dans l'ordre : celles du scénario sur ce
    système, ou celles de sa variante (le moteur d'une course `conteneur`)
    quand le scénario en a par variante."""
    etapes = ETAPES[scenario][distro]
    return etapes[variante] if isinstance(etapes, dict) else etapes


# Le domaine inventé de la production : ses noms ne se résolvent nulle
# part, les clients joignent la VM par son adresse et vérifient le nom.
DOMAINE = "call.exemple.test"
# La disposition de nginx que chaque système reçoit quand l'outil
# l'installe.
DISPOSITION_NGINX = {"debian": "debian", "arch": "arch-include"}
# Attente de la relecture du certificat par coturn après SIGUSR2.
DELAI_SERIE = 15
# La copie de l'état le temps du crochet sur la lignée (voir `crochets`),
# et le témoin d'un /etc/letsencrypt né de ce test.
ETAT_GARDE = ci.STATE_PATH + ".longtest"
TEMOIN_LE = "/etc/letsencrypt/.erplibre-longtest"

# Le libellé du téléphone semé avant l'adoption, et le compte REST du
# rejeu de la base partagée (secret et comptes long terme).
LIBELLE_TELEPHONE = "longtest"
UTILISATEUR_REST = "longtest"

# Les trois bases du scénario des serveurs Odoo, une par lettre :
# `call_infra_odoo_<course>_<lettre>`, jamais un nom de mobile_sync, que son
# propre balayage supprime.
LETTRES_ODOO = ("a", "b", "c")
PREFIXE_BASE_ODOO = "call_infra_odoo_"
_BASE_ODOO = re.compile(r"^call_infra_odoo_[0-9]+_[0-9]+_[abc]$")
# Les comptes que le gabarit Odoo 18 de mobile_sync_odoo crée : son
# administrateur (base sans démonstration) et l'utilisateur interne du chat.
ADMIN_ODOO = ("admin", "admin")
UTILISATEUR_ODOO = ("chat_user", "chat_user")
# Le canal public créé dans la base B pour son lien d'invitation.
CANAL_INVITES = "call infra invites"
# Les sortes d'URL de TURN qu'Odoo remet : sans le module, les deux lignes
# `turn:` du compte fixe ; avec lui, `turns:` en plus (certificat fourni).
ICE_FIXE = ("turn-udp", "turn-tcp")
ICE_SECRET = ("turn-udp", "turn-tcp", "turns")
# Attente de l'arrêt d'un serveur Odoo orphelin avant SIGKILL.
DELAI_ARRET_ODOO = 10

OPTIONS_SSH = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    # Une session morte (VM figée, réseau coupé) se détecte en deux
    # minutes au lieu d'attendre le délai entier de l'étape.
    "-o",
    "ServerAliveInterval=15",
    "-o",
    "ServerAliveCountMax=8",
]


def nom_vm(distro):
    """Le domaine libvirt, qui sert aussi d'alias ssh. Fixe : une VM
    gardée par `--garder` fait refuser la course suivante jusqu'au
    `--detruire`, plutôt que d'empiler une seconde VM."""
    return f"{NOM_BASE}-{distro}"


def argv_creation(distro, nom, cle_pub="", drapeaux=()):
    """La ligne de deploy_qemu.py, sans sudo : la CLI écrit disque et seed
    par l'API des volumes de libvirt."""
    argv = [
        os.path.join(RACINE, ".venv.erplibre/bin/python"),
        os.path.join(RACINE, "script/qemu/deploy_qemu.py"),
        "--distro",
        distro,
        "--version",
        DISTROS[distro],
        "--name",
        nom,
        "--vcpus",
        str(VCPUS),
        "--memory",
        str(MEMOIRE_MO),
        "--disk-size",
        f"{DISQUE_GO}G",
    ]
    if cle_pub:
        argv += ["--ssh-key", cle_pub]
    return argv + list(drapeaux)


def masquer(texte):
    """`texte` où chaque ligne qui commence par un des SECRETS devient
    « <préfixe> *** », et chaque jeton de ntfy (JETON) « tk_*** ». Le reste
    passe tel quel."""
    lignes = []
    for ligne in texte.splitlines(keepends=True):
        nu = ligne.rstrip("\r\n")
        prefixe = next((p for p in SECRETS if nu.startswith(p)), None)
        if prefixe is None:
            lignes.append(JETON.sub("tk_***", ligne))
        else:
            fin = ligne[len(nu) :]
            lignes.append(f"{prefixe} ***{fin}")
    return "".join(lignes)


def commande_distante(root=True, utilisateur=None, env=None, shell="sh"):
    """La commande que ssh fait lancer à l'hôte.

    Le script arrive par l'entrée standard, et le shell lancé (« sh -c »,
    sous sudo) le lit par « eval "$(cat)" » : la substitution se fait
    AVANT que la redirection « </dev/null » ne s'applique, si bien que les
    commandes du script (apt, pacman) ne lisent jamais la suite du script.
    Le corps reste une variable de ce shell : il ne passe ni par l'argv
    local de ssh, ni par le journal, ni par l'argv de sudo ou du shell sur
    l'hôte, où tout compte le lirait dans /proc.
    `root` : sous « sudo -n », qui échoue au lieu d'attendre un mot de
    passe ; `utilisateur` : sous ce compte. `env` : variables posées par
    « env », sans secret (elles se lisent dans la liste des processus).
    """
    parties = []
    if root or utilisateur:
        parties += ["sudo", "-n"]
        if utilisateur:
            parties += ["-u", shlex.quote(utilisateur)]
    if env:
        parties.append("env")
        parties += [f"{k}={shlex.quote(str(v))}" for k, v in env.items()]
    parties += [shell, "-c", shlex.quote('eval "$(cat)" </dev/null')]
    return " ".join(parties)


def ssh_base(cible):
    return ["ssh"] + OPTIONS_SSH + [cible]


def _ajouter(log, texte):
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(texte if texte.endswith("\n") else texte + "\n")


def distant(cible, script, log, delai, **options):
    """Lance `script` sur `cible` (options de `commande_distante`). Rend
    (code, sortie), ou (None, "") quand ssh n'a pas abouti dans `delai`.

    La sortie rendue est entière, pour que les lignes `@@` se relisent ;
    celle du journal passe par `masquer`."""
    argv = ssh_base(cible) + [commande_distante(**options)]
    try:
        fini = subprocess.run(
            argv,
            input=script,
            capture_output=True,
            text=True,
            timeout=delai,
        )
    except (OSError, subprocess.SubprocessError) as souci:
        _ajouter(log, f"✗ ssh {cible} interrompu : {souci}")
        return None, ""
    sortie = (fini.stdout or "") + (fini.stderr or "")
    _ajouter(log, masquer(sortie))
    _ajouter(log, f"── code {fini.returncode}")
    return fini.returncode, sortie


def verdict_controle(lignes, requis):
    """(vert, problèmes) des `CheckLine` de `check_local`.

    Vert quand chaque nom de `requis` est présent et vaut True, et
    qu'aucune autre ligne ne vaut False ; une ligne non requise à None
    (« rien à vérifier ») ne compte pas. `problèmes` : les noms en défaut,
    requis manquants compris, dans l'ordre de `requis` puis des lignes."""
    vues = {ligne.name: ligne.ok for ligne in lignes}
    problemes = [nom for nom in requis if vues.get(nom) is not True]
    problemes += [
        ligne.name
        for ligne in lignes
        if ligne.name not in requis and ligne.ok is False
    ]
    return not problemes, problemes


def resultat_melange(rest_ok, controle_ok):
    """Le rejeu d'un secret REST ajouté à la base de coturn, où vit déjà le
    compte de contrôle : « melange-ok » quand l'allocation REST et celle du
    compte de contrôle réussissent toutes deux, « melange-refuse » sinon.
    C'est une information sur le paquet, pas un échec de la course."""
    return "melange-ok" if rest_ok and controle_ok else "melange-refuse"


def reponses(ip, cert_pem=None, key_pem=None):
    """Les `Answers` de la course : les deux services, l'adresse de la VM
    comme nom public, et le certificat fourni quand il y en a un."""
    return ci.Answers(
        services=frozenset(ci.SERVICES),
        tls="supplied" if cert_pem else "none",
        cert_pem=cert_pem,
        key_pem=key_pem,
        public_name=ip,
    )


def reponses_prod(ip, cert_pem, key_pem, facts=None, resolve=None):
    """Les `Answers` de production que le menu bâtit pour cette course :
    les deux services sous DOMAINE avec ses noms par défaut, le certificat
    fourni, la plage des relais et le port local de ntfy proposés par le
    menu, ni interface web ni 443 pour coturn.

    Avec `facts` (la sonde), les deux réponses qui en dépendent sont
    celles du menu : nginx « existing » quand la sonde le voit, sinon
    « install » ; l'adresse publique d'après `ci.external_ip_for` sur le
    nom de TURN — aucune quand il pointe vers l'hôte, l'adresse résolue
    derrière un NAT, et celle de la VM, que l'opérateur taperait, quand le
    nom ne se résout pas. `resolve` : forme de `socket.getaddrinfo`."""
    ntfy, turn = ci.default_names(DOMAINE)
    nginx, publique = "install", None
    if facts is not None:
        present, _sur_80 = _todo()._call_infra_nginx_facts(facts)
        nginx = "existing" if present else "install"
        adresse, raison = ci.external_ip_for(
            turn, facts.addresses, resolve=resolve or socket.getaddrinfo
        )
        publique = {"local": None, "nat": adresse}.get(raison, ip)
    return ci.Answers(
        services=frozenset(ci.SERVICES),
        tls="supplied",
        cert_pem=cert_pem,
        key_pem=key_pem,
        public_name=DOMAINE,
        min_port=ci.PROD_MIN_PORT,
        max_port=ci.PROD_MAX_PORT,
        ntfy_port=ci.NTFY_HTTP_PORT,
        external_ip=publique,
        mode="production",
        ntfy_name=ntfy,
        turn_name=turn,
        nginx=nginx,
    )


def methode_du_menu(answers, facts, methode, moteur=None, vu=None):
    """`answers` sous la méthode `methode`, comme les bâtit
    `_call_infra_ask_install_method` : en conteneurs, `moteur` (une clé de
    MOTEURS) donne moteur et rootless, et les paquets qui manquent à l'hôte
    (`engine_offer`) sont proposés puis acceptés ; `vu["offre"]` les reçoit.
    `method_refusal` passe ensuite, et son refus est levé, sauf celui d'un
    port (`cim.PORT_REFUSAL`) que le menu laisse à `plan_install`."""
    engine, rootless, offre = None, False, ()
    if methode == "container":
        engine, rootless = MOTEURS[moteur]
        offre = ci.engine_offer(facts, engine, rootless)
    if vu is not None:
        vu["offre"] = offre
    answers = dataclasses.replace(
        answers,
        method=methode,
        engine=engine,
        rootless=rootless,
        install_engine=bool(offre),
    )
    refus = ci.method_refusal(facts, answers)
    if refus is not None and refus.key != cim.PORT_REFUSAL:
        raise refus
    return answers


def reponses_prod_coturn(ip, cert_pem, key_pem, facts=None, resolve=None):
    """Les `Answers` de production du menu pour coturn seul : celles de
    `reponses_prod` sans ntfy, donc sans nginx ni port local de ntfy, et
    TURN sur TLS en 443, que le menu propose sur un hôte sans nginx où 443
    est libre."""
    answers = reponses_prod(ip, cert_pem, key_pem, facts, resolve)
    return dataclasses.replace(
        answers,
        services=frozenset({"coturn"}),
        ntfy_port=None,
        ntfy_name=None,
        nginx=None,
        turns_443=True,
    )


def noms_certificat(ip):
    """Les noms du certificat inventé : ceux que le plan exige
    (`ci.certificate_names`), puis l'adresse de la VM, par où les clients
    la joignent."""
    return [*ci.certificate_names(reponses_prod(ip, None, None)), ip]


def paire(chemins):
    """(certificat, clé) en texte, d'après les chemins de
    `local_cert.issue`."""
    textes = []
    for role in ("server_crt", "server_key"):
        with open(chemins[role], encoding="utf-8") as fh:
            textes.append(fh.read())
    return tuple(textes)


def _tlv(octets, debut):
    """(étiquette, début du contenu, fin) de l'élément DER qui commence en
    `debut` ; la longueur longue (premier octet ≥ 0x80) est lue."""
    etiquette, longueur = octets[debut], octets[debut + 1]
    pos = debut + 2
    if longueur & 0x80:
        taille = longueur & 0x7F
        if not taille or pos + taille > len(octets):
            raise IndexError("longueur DER illisible")
        longueur = int.from_bytes(octets[pos : pos + taille], "big")
        pos += taille
    if pos + longueur > len(octets):
        raise IndexError("élément DER tronqué")
    return etiquette, pos, pos + longueur


def serie_der(der):
    """Le numéro de série d'un certificat X.509 en DER, None s'il est
    illisible. Certificate ::= SEQUENCE { tbsCertificate SEQUENCE {
    [0] version OPTIONAL, serialNumber INTEGER, ... }, ... }."""
    try:
        _e, certificat, _f = _tlv(der, 0)
        _e, tbs, _f = _tlv(der, certificat)
        etiquette, contenu, fin = _tlv(der, tbs)
        if etiquette == 0xA0:
            etiquette, contenu, fin = _tlv(der, fin)
    except (IndexError, TypeError):
        return None
    if etiquette != 0x02 or fin == contenu:
        return None
    return int.from_bytes(der[contenu:fin], "big", signed=True)


_PEM = re.compile(
    r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.S
)


def serie_pem(pem):
    """Le numéro de série du premier certificat de `pem`, None sans
    certificat lisible."""
    trouve = _PEM.search(pem or "")
    if trouve is None:
        return None
    try:
        return serie_der(ssl.PEM_cert_to_DER_cert(trouve.group(0)))
    except ValueError:
        return None


def certificat_vu(adresse, port, nom, delai=DELAI_PORT):
    """Le certificat (DER) que sert `adresse`:`port` sous le nom `nom`,
    None sans poignée de main. Rien n'est vérifié : la question est QUEL
    certificat est servi, la vérification est celle de `check_local`."""
    contexte = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    contexte.check_hostname = False
    contexte.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((adresse, port), timeout=delai) as brut:
            with contexte.wrap_socket(brut, server_hostname=nom) as tls:
                return tls.getpeercert(binary_form=True)
    except (OSError, ssl.SSLError):
        return None


def attendre_certificat(vu, adresse, port, nom, pem, attente):
    """Le certificat servi, relu chaque seconde pendant `attente` secondes
    au plus tant qu'il n'a pas le numéro de série de `pem` : coturn relit
    sa paire après SIGUSR2, pas à l'instant du signal."""
    voulu = serie_pem(pem)
    fin = time.time() + attente
    while True:
        der = vu(adresse, port, nom)
        if serie_der(der) == voulu or time.time() >= fin:
            return der
        time.sleep(1)


def attendus_crochet(etape, unite, nginx=True):
    """(requis, interdits) : les valeurs `@@HOOK` d'une passe du crochet.

    `crochet-fourni` (l'état dit « certificat fourni ») : coturn n'est pas
    touché, nginx est rechargé. `crochet-lignee` et `crochet-retour`
    (l'état dit « Let's Encrypt ») : la paire copiée, SIGUSR2 à `unite`
    (l'unité systemd, ou le nom du conteneur de coturn), l'empreinte
    coturn.applied réécrite, nginx rechargé. Sans `nginx` (un hôte de
    développement), le rechargement n'est pas requis. Une valeur
    s'accorde à un motif égal ou suivi d'une espace."""
    recharge = ("nginx-reloaded",) if nginx else ()
    if etape == "crochet-fourni":
        return (
            ("coturn-skip not-letsencrypt", *recharge),
            ("copied", "signal", "failed", "refused"),
        )
    return (
        ("copied", f"signal {unite}", "applied", *recharge),
        ("applied-stale", "failed", "refused"),
    )


def _accorde(valeurs, motif):
    return any(v == motif or v.startswith(motif + " ") for v in valeurs)


def _hex(serie):
    return None if serie is None else f"{serie:X}"


def verdict_crochet(code, sortie, requis, interdits, pids, vus):
    """(ok, détail) d'une passe du crochet.

    Vert quand le crochet sort à 0, que chaque motif de `requis` est parmi
    ses `@@HOOK` et aucun de `interdits`, que `pids` (MainPID de coturn
    avant, après) désigne le même processus vivant, et que chaque entrée
    de `vus` ({nom: (pem attendu, DER servi)}) sert le numéro de série du
    certificat attendu, les deux lus des certificats eux-mêmes."""
    valeurs = [v.strip() for n, v in ci.marker_lines(sortie) if n == "HOOK"]
    manque = [m for m in requis if not _accorde(valeurs, m)]
    en_trop = [m for m in interdits if _accorde(valeurs, m)]
    avant, apres = (str(p).strip() for p in pids)
    meme = avant.isdigit() and avant != "0" and avant == apres
    series, servis = {}, True
    for nom, (pem, der) in vus.items():
        attendue, vue = serie_pem(pem), serie_der(der)
        series[nom] = {"attendue": _hex(attendue), "vue": _hex(vue)}
        servis = servis and attendue is not None and attendue == vue
    ok = code == 0 and not manque and not en_trop and meme and servis
    return ok, {
        "crochet": valeurs,
        "manque": manque,
        "en_trop": en_trop,
        "pid": [avant, apres],
        "series": series,
    }


def _sonde(cible, log, executer):
    """`HostFacts` de l'hôte, ou None (sortie illisible, ssh perdu)."""
    code, sortie = executer(cible, ci.probe_script(), log, DELAI_SCRIPT)
    if code is None:
        return None
    try:
        return ci.parse_probe(sortie)
    except ci.Refusal as refus:
        _ajouter(log, f"✗ sonde : {refus.key} {refus.values}")
        return None


def _pare_feu(cible, facts, answers, precedent, log, executer):
    """`state["firewall"]` après l'étape du pare-feu du menu, avec son
    « oui » : les règles sont ajoutées quand le pare-feu actif en montre un
    aperçu. Celles de `precedent` (la fiche de l'état) et celles qu'un
    passage a posées sans pouvoir les consigner (`facts.firewall_pending`)
    restent. None quand le script du pare-feu échoue."""
    kind = facts.firewall
    regles = ci.firewall_rules(answers)
    chaine = facts.nft_chains[0] if len(facts.nft_chains) == 1 else None
    pending = facts.firewall_pending
    if not ci.firewall_preview(kind, regles, chaine):
        return ci.firewall_record(kind, "", precedent, pending)
    code, sortie = executer(
        cible, ci.firewall_script(kind, regles, "allow"), log, DELAI_SCRIPT
    )
    if code != 0:
        return None
    return ci.firewall_record(kind, sortie, precedent, pending)


def _ecrire_etat(cible, etat, log, executer):
    """Vrai quand `state_write_script` a écrit `etat` (`@@SAVED yes`)."""
    code, sortie = executer(
        cible, ci.state_write_script(etat), log, DELAI_SCRIPT
    )
    sauve = [v.strip() for n, v in ci.marker_lines(sortie) if n == "SAVED"]
    return code == 0 and sauve[-1:] == ["yes"]


def installer(cible, answers, log, executer=distant, maintenant=None):
    """Le chemin du menu, de la sonde à l'état écrit.

    `answers` : les `Answers`, ou une fonction qui les bâtit de la sonde
    (`HostFacts`), comme le menu pose ses questions après elle ; elle lève
    `ci.Refusal` pour un refus que le menu dit avant la suite (étape
    « methode »).

    Rend {"ok", "etape", "refus", "limite", "rien_a_faire", "adoptes",
    "etat", "answers", "plan", "migration"} : `etape` nomme ce qui a
    échoué (sonde, methode, plan, install, pare-feu, etat), `refus` la clé
    d'un refus de la méthode ou du plan, `limite` vrai quand une image n'a
    pas été tirée sous la limite du registre (`limite_registre`),
    `adoptes` les services dont la configuration étrangère a été sauvée,
    `etat` l'état écrit sur l'hôte (None quand rien n'a été écrit),
    `answers` celles du plan, `plan` le `InstallPlan`, `migration` la
    dernière valeur `@@MIGRATION` du script (« done », « rolled-back »...).
    Une relance où les services sont à jour passe encore par le pare-feu
    tant qu'une règle manque à l'état (`firewall_missing`), comme le
    menu."""
    res = {
        "ok": False,
        "etape": "sonde",
        "refus": None,
        "limite": False,
        "rien_a_faire": False,
        "adoptes": (),
        "etat": None,
        "answers": None if callable(answers) else answers,
        "plan": None,
        "migration": None,
    }
    facts = _sonde(cible, log, executer)
    if facts is None:
        return res
    if callable(answers):
        res["etape"] = "methode"
        try:
            answers = answers(facts)
        except ci.Refusal as refus:
            res["refus"] = refus.key
            _ajouter(log, f"✗ méthode : {refus.key} {refus.values}")
            return res
        res["answers"] = answers
    res["etape"] = "plan"
    try:
        plan = ci.plan_install(
            facts,
            answers,
            maintenant or datetime.datetime.now(datetime.timezone.utc),
        )
    except ci.Refusal as refus:
        res["refus"] = refus.key
        _ajouter(log, f"✗ plan : {refus.key} {refus.values}")
        return res
    res["adoptes"] = plan.adopt
    res["plan"] = plan
    record = None
    if plan.nothing_to_do:
        _ajouter(log, "✓ rien à changer")
        res["rien_a_faire"] = True
        if not ci.firewall_missing(facts, answers):
            res.update(ok=True, etape="")
            return res
        etat = facts.state
    else:
        # Comme le menu : le défi HTTP-01 passe pendant l'installation, le
        # port 80 doit déjà passer le pare-feu.
        if ci.firewall_before_install(answers):
            res["etape"] = "pare-feu"
            prior = facts.state if isinstance(facts.state, dict) else {}
            record = _pare_feu(
                cible, facts, answers, prior.get("firewall"), log, executer
            )
            if record is None:
                return res
        res["etape"] = "install"
        stamp = time.strftime("%Y%m%d-%H%M%S")
        code, sortie = executer(
            cible, ci.install_script(plan, stamp), log, DELAI_INSTALL
        )
        sauve = [v.strip() for n, v in ci.marker_lines(sortie) if n == "SAVED"]
        migrations = [
            v.strip() for n, v in ci.marker_lines(sortie) if n == "MIGRATION"
        ]
        res["migration"] = (migrations or [None])[-1]
        if code != 0 or sauve[-1:] != ["yes"]:
            res["limite"] = limite_registre(sortie)
            return res
        etat = ci.installed_state(plan, stamp, sortie)
    if record is None:
        res["etape"] = "pare-feu"
        record = _pare_feu(
            cible, facts, answers, etat.get("firewall"), log, executer
        )
        if record is None:
            return res
    etat = ci.with_firewall(etat, record)
    res["etape"] = "etat"
    if not _ecrire_etat(cible, etat, log, executer):
        return res
    res.update(ok=True, etape="", etat=etat)
    return res


def verifier(cible, adresse, cafile, log, executer=distant):
    """(lignes `CheckLine`, faits lus) de la vérification du menu, depuis
    cette machine ; ([], None) quand l'hôte n'a pas répondu. La clé du
    compte de contrôle reste dans les faits, jamais au journal."""
    code, sortie = executer(cible, ci.check_remote_script(), log, DELAI_SCRIPT)
    if code is None:
        return [], None
    try:
        lus = ci.parse_check_remote(sortie)
    except ci.Refusal as refus:
        _ajouter(log, f"✗ vérification : {refus.key}")
        return [], None
    lignes = ci.check_local(lus, adresse, cafile)
    for ligne in lignes:
        _ajouter(
            log,
            f"{cim.SYMBOLS.get(ligne.ok, '?')} {ligne.name} : {ligne.detail}"
            f" {ligne.values}",
        )
    return lignes, lus


def limite_registre(sortie):
    """Vrai quand une ligne `@@PULL_FAILED <service> rate-limit` dit qu'une
    image n'a pas été tirée sous la limite du registre : le script s'est
    arrêté avant d'arrêter aucun service et sans écrire d'état, la course
    est à relancer."""
    return any(
        nom == "PULL_FAILED" and valeur.split()[-1:] == ["rate-limit"]
        for nom, valeur in ci.marker_lines(sortie)
    )


def desinstaller(cible, remove_data, log, executer=distant, moteur=False):
    """La désinstallation du menu. Rend « fait » (`@@DONE yes`), « rien »
    (pas d'état, `@@NOTHING`) ou « echec ». `moteur` : le oui à la
    question des ajouts de l'outil pour les conteneurs (paquets du moteur,
    comptes, unité de redémarrage, session permanente)."""
    facts = _sonde(cible, log, executer)
    if facts is None:
        return "echec"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    # Les règles qu'un passage a posées sans pouvoir les consigner partent
    # avec les autres.
    etat = ci.merge_pending_firewall(facts.state, facts.firewall_pending)
    etat = etat if isinstance(etat, dict) else None
    try:
        script = ci.uninstall_script(
            etat, remove_data, stamp, remove_engine=moteur
        )
    except ci.Refusal as refus:
        _ajouter(log, f"✗ désinstallation : {refus.key} {refus.values}")
        return "echec"
    code, sortie = executer(cible, script, log, DELAI_INSTALL)
    noms = dict(ci.marker_lines(sortie))
    if etat is None:
        return "rien" if code == 0 and "NOTHING" in noms else "echec"
    fait = [v.strip() for n, v in ci.marker_lines(sortie) if n == "DONE"]
    return "fait" if code == 0 and fait[-1:] == ["yes"] else "echec"


def port_tcp_ouvert(adresse, port, delai=DELAI_PORT):
    """Vrai quand une connexion TCP aboutit ; un refus ou un silence (un
    pare-feu qui jette) valent fermé."""
    try:
        with socket.create_connection((adresse, port), timeout=delai):
            return True
    except OSError:
        return False


def ports_fermes(adresse, tcp, udp):
    """{« <port>/<proto> »: fermé} vus d'ici. En udp, une requête STUN
    Binding sans réponse vaut fermé : un port udp ne refuse rien."""
    vus = {f"{p}/tcp": not port_tcp_ouvert(adresse, p) for p in tcp}
    for port in udp:
        reponse = turn_client.binding(adresse, port, "udp", timeout=DELAI_PORT)
        vus[f"{port}/udp"] = reponse is None
    return vus


# --- Machines -----------------------------------------------------------


def _todo():
    sys.argv = ["todo.py"]
    from script.todo.todo import TODO

    return TODO.__new__(TODO)


def creer_vm(nom, distro, journal, dry_run):
    """La VM, par la CLI du dépôt. Rend (nom, uuid, ok).

    Un nom que libvirt définit déjà n'est pas à cette course : refus, et
    (None, "", False). Une création qui échoue après avoir défini le
    domaine rend son nom et son UUID avec ok faux, pour qu'elle entre au
    rapport et reste défaisable."""
    argv = argv_creation(
        distro, nom, cle_publique(creer=not dry_run), drapeaux_cache()
    )
    if dry_run:
        dire("      " + " ".join(shlex.quote(a) for a in argv), journal)
        return nom, "", True
    if Descente.uuid_libvirt(nom):
        dire(
            f"      ✗ {nom} existe déjà, elle n'est pas à cette course :"
            " --detruire d'abord",
            journal,
        )
        return None, "", False
    ok = False
    try:
        fini = subprocess.run(argv, timeout=DELAI_CREATION)
        ok = fini.returncode == 0
    except (OSError, subprocess.SubprocessError) as souci:
        dire(f"      ✗ la création de {nom} s'est arrêtée : {souci}", journal)
    if not ok:
        dire(f"      ✗ la création de {nom} a échoué", journal)
    uuid = Descente.uuid_libvirt(nom)
    if not ok and not uuid:
        return None, "", False
    return nom, uuid, ok


def adresse_de(nom, journal):
    """L'adresse de la VM, et l'entrée ~/.ssh/config qui la nomme : la CLI
    n'écrit pas cette entrée, sans laquelle « ssh <nom> » ne résout rien."""
    todo = _todo()
    ip = todo._qemu_vm_ip(nom, timeout=DELAI_SSH)
    if not ip:
        dire(f"      ✗ {nom} créée mais sans adresse", journal)
        return ""
    pub = cle_publique()
    prive = pub[:-4] if pub else None
    todo._write_ssh_config_entry([nom], UTILISATEUR, ip, identity_file=prive)
    dire(f"      {nom} : {ip}", journal)
    return ip


def attendre_ssh(cible, journal, delai=DELAI_SSH):
    """Vrai dès qu'une commande aboutit en ssh : le port s'ouvre avant que
    cloud-init n'ait posé le compte."""
    fin = time.time() + delai
    while time.time() < fin:
        try:
            fini = subprocess.run(
                ssh_base(cible) + ["true"],
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            time.sleep(5)
            continue
        if fini.returncode == 0:
            return True
        time.sleep(5)
    dire(f"      ✗ {cible} jamais joignable en {delai} s", journal)
    return False


def plan_tient(journal, nombre=1):
    """L'hôte peut-il porter `nombre` VM debout ensemble ? Le dire avant
    d'en créer une. Chaque VM compte sa mémoire et son disque écrit ; les
    marges ne comptent qu'une fois, pour l'hôte."""
    coeurs, ram, disque = capacite_hote()
    dire(
        f"  machine locale : {coeurs} cœurs, {ram} Mo disponibles,"
        f" {disque} Go de disque",
        journal,
    )
    ram_voulue = nombre * MEMOIRE_MO + MARGE_RAM_MO
    disque_voulu = nombre * DISQUE_ECRIT_GO + MARGE_DISQUE_GO
    manque = []
    if ram < ram_voulue:
        manque.append(f"RAM (il en faut {ram_voulue} Mo pour {nombre} VM)")
    if disque < disque_voulu:
        manque.append(
            f"disque (il en faut {disque_voulu} Go libres pour {nombre} VM ;"
            f" chaque disque virtuel fait {DISQUE_GO} Go, creux)"
        )
    if manque:
        dire(f"  ✗ pas assez de {' ni de '.join(manque)}", journal)
        return False
    return True


# --- Scénarios ----------------------------------------------------------

# Pose ufw, autorise ssh AVANT d'activer, puis active : le pare-feu actif
# est ce que l'outil doit compléter sans jamais l'activer lui-même.
SCRIPT_UFW = "\n".join(
    [
        "set -e",
        "export DEBIAN_FRONTEND=noninteractive",
        "apt-get -o DPkg::Lock::Timeout=600 update -qq",
        "apt-get -o DPkg::Lock::Timeout=600 install -y -qq ufw",
        "ufw allow 22/tcp",
        "ufw --force enable",
        "ufw status | grep -q '^Status: active' && echo '@@UFW active'",
        "",
    ]
)

# Ce qui doit rester, ou non, après la désinstallation sur Debian : unité
# coturn, dossier de l'outil, règles ufw de l'outil, empreinte du
# server.yml remis, état de ntfy (adopté, donc gardé).
SCRIPT_APRES = "\n".join(
    [
        "for u in " + " ".join(ci.COTURN_UNITS.values()) + "; do",
        '  if systemctl cat "$u" >/dev/null 2>&1; then echo "@@UNIT $u"; fi',
        "done",
        f"if [ -e {ci.CALL_DIR} ]; then echo '@@CALL_DIR present'; fi",
        f"N=$(ufw show added 2>/dev/null | grep -c {ci.FIREWALL_COMMENT})",
        'echo "@@UFW_RULES ${N:-0}"',
        f'echo "@@YML_SHA $(sha256sum < {ci.NTFY_CONFIG} | cut -d" " -f1)"',
        f'echo "@@NTFY $(systemctl is-active {ci.NTFY_UNIT} 2>/dev/null)"',
        "echo @@END",
        "",
    ]
)


def script_secret(realm, secret, etat=None):
    """Ajoute `secret` à la base de coturn par « turnadmin -s », sous le
    compte du service (la base lui appartient). Le secret passe en argument
    de turnadmin, lisible le temps de la commande : il naît pour ce rejeu,
    sur une VM jetable, et ne sert nulle part ailleurs.

    Avec `etat` en conteneurs, turnadmin est celui de l'image, lancé dans
    le conteneur de coturn sous l'uid:gid que l'état consigne : l'hôte n'a
    pas de turnadmin, et la base est montée au même chemin."""
    if isinstance(etat, dict) and etat.get("method") == "container":
        fiche = etat["services"]["coturn"]
        return "\n".join(
            [
                _eng(etat),
                f"eng exec -u {int(fiche['uid'])}:{int(fiche['gid'])}"
                f" {cc.CONTAINERS['coturn']} turnadmin -s"
                f" {shlex.quote(secret)} -r {shlex.quote(realm)}"
                f" -b {ci.COTURN_DB} >/dev/null 2>&1",
                'echo "@@SECRET_RC $?"',
                "",
            ]
        )
    return "\n".join(
        [
            "U=",
            "for u in " + " ".join(ci.COTURN_UNITS.values()) + "; do",
            '  if systemctl cat "$u" >/dev/null 2>&1; then',
            '    U=$(systemctl show -p User --value "$u"); break',
            "  fi",
            "done",
            f'runuser -u "${{U:-turnserver}}" -- turnadmin -s'
            f" {shlex.quote(secret)} -r {shlex.quote(realm)}"
            f" -b {ci.COTURN_DB} >/dev/null 2>&1",
            'echo "@@SECRET_RC $?"',
            "",
        ]
    )


def _b64(texte):
    return base64.b64encode(texte.encode("utf-8")).decode("ascii")


def script_lignee(cert_pem, key_pem):
    """Pose (`cert_pem`, `key_pem`) en fausse lignée certbot LINEAGE_DIR :
    fullchain.pem et cert.pem portent le certificat, privkey.pem (0600) la
    clé ; ce que certbot y laisse après un renouvellement. Les deux
    voyagent en base64 dans le corps, qui ne passe par aucun argv
    (`commande_distante`). Un
    /etc/letsencrypt absent reçoit TEMOIN_LE, que `script_remise` lit pour
    l'emporter en entier."""
    lignee = ci.LINEAGE_DIR
    return "\n".join(
        [
            "set -e",
            "if [ ! -e /etc/letsencrypt ]; then",
            "  install -d -m 0755 /etc/letsencrypt",
            f"  : > {TEMOIN_LE}",
            "fi",
            f"install -d -m 0700 {lignee}",
            "umask 077",
            f"echo {_b64(cert_pem)} | base64 -d > {lignee}/fullchain.pem",
            f"cp {lignee}/fullchain.pem {lignee}/cert.pem",
            f"echo {_b64(key_pem)} | base64 -d > {lignee}/privkey.pem",
            "echo '@@LINEAGE placed'",
            "",
        ]
    )


def script_pid(unite):
    """Imprime `@@PID <MainPID>` de `unite` (0 quand elle ne tourne
    pas)."""
    return (
        f'echo "@@PID $(systemctl show -p MainPID --value'
        f' {shlex.quote(unite)} 2>/dev/null)"\n'
    )


def _eng(etat):
    """La fonction `sh` « eng » : le moteur du bloc `container` de `etat`
    (`cc.engine_argv`), précédé en rootless du préfixe qui le lance sous
    le compte rootless dans sa session. ValueError pour un bloc altéré."""
    return f'eng() {{ {shlex.join(cc.engine_argv(etat["container"]))} "$@"; }}'


def script_conteneurs(etat, attente=0):
    """Imprime, pour chaque service de `etat` en conteneurs, `@@CSTATE
    <service> <état> <pid> <user> <démarré>` d'après `inspect` (« - » et 0
    pour ce qui ne se lit pas ; la date de démarrage, qui porte des espaces
    sous Podman, en dernier). Avec `attente`, chaque conteneur est relu
    chaque seconde, `attente` secondes au plus, tant qu'il ne tourne
    pas."""
    lignes = [_eng(etat)]
    for svc in ci.SERVICES:
        if not isinstance(etat["services"].get(svc), dict):
            continue
        nom = cc.CONTAINERS[svc]
        lignes += [
            "i=0",
            "while :; do",
            f"  S=$(eng inspect -f '{{{{.State.Status}}}}' {nom} 2>/dev/null)",
            '  [ "$S" = running ] && break',
            f'  i=$((i + 1)); [ "$i" -ge {int(attente)} ] && break',
            "  sleep 1",
            "done",
            f"P=$(eng inspect -f '{{{{.State.Pid}}}}' {nom} 2>/dev/null)",
            f"U=$(eng inspect -f '{{{{.Config.User}}}}' {nom} 2>/dev/null)",
            f"T=$(eng inspect -f '{{{{.State.StartedAt}}}}' {nom}"
            " 2>/dev/null)",
            f'echo "@@CSTATE {svc} ${{S:--}} ${{P:-0}} ${{U:--}} $T"',
        ]
    return "\n".join(lignes + [""])


def etats_conteneurs(sortie):
    """{service: {"etat", "pid", "user", "demarre"}} des lignes `@@CSTATE`
    de `script_conteneurs`."""
    lus = {}
    for nom, valeur in ci.marker_lines(sortie):
        mots = valeur.split(" ", 4)
        if nom != "CSTATE" or len(mots) < 4:
            continue
        lus[mots[0]] = {
            "etat": mots[1],
            "pid": mots[2],
            "user": mots[3],
            "demarre": mots[4].strip() if len(mots) > 4 else "",
        }
    return lus


def script_proprietaires():
    """Imprime `@@OWNER <service> <compte> <uid>` de la base de coturn et
    de celle des comptes de ntfy, d'après `stat` ; « UNKNOWN » pour un uid
    qu'aucun compte de l'hôte ne porte, celui d'un uid subordonné d'un
    espace de noms."""
    lignes = []
    for svc, chemin in (("coturn", ci.COTURN_DB), ("ntfy", ci.NTFY_AUTH_FILE)):
        lignes.append(
            f"if [ -e {chemin} ]; then"
            f" echo \"@@OWNER {svc} $(stat -c '%U %u' {chemin})\"; fi"
        )
    return "\n".join(lignes + [""])


def verdict_proprietaires(etat, sortie):
    """(ok, détail) : chaque base appartient au compte et à l'uid que
    `etat` consigne pour son service ; un uid sans nom (subordonné) ne
    passe pas."""
    lus = {}
    for nom, valeur in ci.marker_lines(sortie):
        mots = valeur.split()
        if nom == "OWNER" and len(mots) == 3:
            lus[mots[0]] = (mots[1], mots[2])
    detail = {}
    for svc, fiche in etat["services"].items():
        voulu = (str(fiche.get("account")), str(fiche.get("uid")))
        detail[svc] = {"vu": list(lus.get(svc, ())), "voulu": list(voulu)}
        detail[f"{svc}-ok"] = lus.get(svc) == voulu
    return all(v for k, v in detail.items() if k.endswith("-ok")), detail


# Le redémarrage de la VM : programmé par systemd-run quelques secondes
# plus tard, pour que la session ssh qui le demande se ferme d'abord, et
# l'identifiant de démarrage du noyau, qui change à chaque démarrage.
SCRIPT_DEMARRAGE = 'echo "@@BOOT $(cat /proc/sys/kernel/random/boot_id)"\n'
SCRIPT_REDEMARRER = "\n".join(
    [
        "systemd-run --on-active=5 --timer-property=AccuracySec=1s"
        " systemctl reboot >/dev/null 2>&1 && echo '@@REBOOT scheduled'",
        "",
    ]
)
# Attente après la programmation du redémarrage, avant de guetter ssh :
# ssh répondrait encore depuis l'ancien démarrage.
DELAI_REDEMARRAGE = 30
# Attente des conteneurs après le redémarrage : le moteur, l'unité de
# redémarrage ou la session permanente du compte rootless les relancent.
DELAI_CONTENEURS = 180


def script_auto(etat):
    """Imprime ce qui relance les conteneurs au démarrage : `@@AUTO
    <unité> <is-enabled>` de docker.service (Docker), de
    podman-restart.service en root (Podman), ou de celui du compte
    rootless dans sa session, avec `@@LINGER <oui|non>` pour sa session
    permanente."""
    bloc = etat["container"]
    if bloc["engine"] == "docker":
        unite = "docker.service"
        return (
            f'echo "@@AUTO {unite} $(systemctl is-enabled {unite}'
            ' 2>/dev/null)"\n'
        )
    if not bloc["rootless"]:
        unite = "podman-restart.service"
        return (
            f'echo "@@AUTO {unite} $(systemctl is-enabled {unite}'
            ' 2>/dev/null)"\n'
        )
    prefixe = shlex.join(cc.rootless_prefix(bloc["account"], bloc["uid"]))
    lien = f"/var/lib/systemd/linger/{bloc['account']}"
    return "\n".join(
        [
            f'echo "@@AUTO user $({prefixe} systemctl --user is-enabled'
            ' podman-restart.service 2>/dev/null)"',
            f"if [ -e {lien} ]; then echo '@@LINGER oui';"
            " else echo '@@LINGER non'; fi",
            "",
        ]
    )


def verdict_redemarrage(avant, apres, etats, auto):
    """(ok, détail) d'un redémarrage : l'identifiant de démarrage a changé,
    chaque conteneur de `etats` tourne de nouveau, l'unité de `auto`
    (sortie de `script_auto`) est activée et, en rootless, la session
    permanente est posée."""
    lus = dict(ci.marker_lines(auto))
    unite = lus.get("AUTO", "").split()
    detail = {
        "redemarre": bool(avant) and bool(apres) and avant != apres,
        "conteneurs": bool(etats)
        and all(e["etat"] == "running" for e in etats.values()),
        "unite-activee": unite[-1:] == ["enabled"],
        "session-permanente": lus.get("LINGER", "oui").strip() == "oui",
    }
    return all(detail.values()), dict(detail, etats=etats, auto=unite)


def script_port_bas(port):
    """Imprime `@@LISTEN <processus> <uid>` de chaque processus qui écoute
    `port` en TCP, d'après `ss` et `ps`."""
    return "\n".join(
        [
            f"for P in $(ss -Hltnp 'sport = :{int(port)}' 2>/dev/null"
            " | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u); do",
            '  echo "@@LISTEN $(ps -o comm= -p "$P") $(ps -o uid= -p "$P"'
            ' | tr -d " ")"',
            "done",
            "echo @@END",
            "",
        ]
    )


def verdict_port_bas(sortie):
    """(ok, détail) : turnserver écoute, et aucun processus qui écoute ce
    port ne tourne en root."""
    vus = [
        valeur.split()
        for nom, valeur in ci.marker_lines(sortie)
        if nom == "LISTEN" and len(valeur.split()) == 2
    ]
    ok = (
        any(comm.startswith("turnserver") for comm, _uid in vus)
        and all(uid.isdigit() and uid != "0" for _comm, uid in vus)
        and "END" in dict(ci.marker_lines(sortie))
    )
    return ok, {"ecoute": vus}


def script_apres_conteneur(paquets):
    """Ce qui reste sur l'hôte après la désinstallation en conteneurs, en
    lignes `@@` : `CONTAINER <nom>` et `IMAGE <référence>` vus par chaque
    moteur présent (Docker, Podman en root), `IMAGE_FILE <dépôt>` pour une
    image coturn ou ntfy encore dans le stockage d'un moteur retiré,
    `VOLUME <chemin>` pour chaque volume de ces stockages, `COMPOSE
    present`, `ACCOUNT <compte>` des comptes que l'outil crée, `HOME
    present` (le dossier du compte rootless), `LINGER present`, `PKG
    <paquet> <statut>` de chaque paquet de `paquets` (dpkg), `CALL_DIR
    present`, `UFW_RULES <n>`, puis `END`."""
    depots = "coturn/coturn\\|binwiederhier/ntfy"
    comptes = " ".join(
        sorted({cc.COTURN_ACCOUNTS[1], cc.ROOTLESS_ACCOUNT, cc.NTFY_ACCOUNT})
    )
    return "\n".join(
        [
            "if command -v docker >/dev/null 2>&1; then",
            "  docker ps -a --format '{{.Names}}' 2>/dev/null"
            " | grep '^erplibre-call' | sed 's/^/@@CONTAINER /'",
            "  docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null"
            f" | grep '{depots}' | sed 's/^/@@IMAGE /'",
            "fi",
            "if command -v podman >/dev/null 2>&1; then",
            "  podman ps -a --format '{{.Names}}' 2>/dev/null"
            " | grep '^erplibre-call' | sed 's/^/@@CONTAINER /'",
            "  podman images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null"
            f" | grep '{depots}' | sed 's/^/@@IMAGE /'",
            "fi",
            "for F in /var/lib/docker/image/*/repositories.json"
            " /var/lib/containers/storage/*-images/images.json; do",
            f'  [ -f "$F" ] && grep -o \'{depots}\' "$F" | sort -u'
            " | sed 's/^/@@IMAGE_FILE /'",
            "done",
            "for V in /var/lib/docker/volumes/*/"
            " /var/lib/containers/storage/volumes/*/; do",
            '  [ -d "$V" ] && echo "@@VOLUME $V"',
            "done",
            f"if [ -e {cc.COMPOSE_FILE} ]; then echo '@@COMPOSE present'; fi",
            f"for A in {comptes}; do",
            '  getent passwd "$A" >/dev/null 2>&1 && echo "@@ACCOUNT $A"',
            "done",
            f"if [ -e {cc.ROOTLESS_HOME} ]; then echo '@@HOME present'; fi",
            f"if [ -e /var/lib/systemd/linger/{cc.ROOTLESS_ACCOUNT} ]; then",
            "  echo '@@LINGER present'",
            "fi",
            *[
                f"dpkg-query -W -f='@@PKG ${{Package}} ${{db:Status-Abbrev}}\\n'"
                f" {shlex.quote(p)} 2>/dev/null || true"
                for p in paquets
            ],
            f"if [ -e {ci.CALL_DIR} ]; then echo '@@CALL_DIR present'; fi",
            "N=0",
            "if command -v ufw >/dev/null 2>&1; then",
            f"  N=$(ufw show added 2>/dev/null | grep -c {ci.FIREWALL_COMMENT})",
            "fi",
            'echo "@@UFW_RULES ${N:-0}"',
            "echo @@END",
            "",
        ]
    )


def verdict_apres_conteneur(code, sortie):
    """(ok, détail) de l'hôte après la désinstallation en conteneurs, moteur
    compris, d'après `script_apres_conteneur` : ni conteneur, ni image, ni
    volume, ni fichier compose, ni compte de l'outil ni son dossier ni sa
    session permanente, chaque paquet du moteur purgé (statut « u » ou
    « p », ni installé ni gardé avec sa configuration), ni dossier de
    l'outil ni règle ufw de l'outil.
    """
    lus = _traces(sortie)
    paquets = [v.split() for v in lus.get("PKG", [])]
    detail = {
        "sans-conteneur": "CONTAINER" not in lus,
        "sans-image": "IMAGE" not in lus and "IMAGE_FILE" not in lus,
        "sans-volume": "VOLUME" not in lus,
        "sans-compose": "COMPOSE" not in lus,
        "sans-compte": "ACCOUNT" not in lus
        and "HOME" not in lus
        and "LINGER" not in lus,
        "sans-paquet-moteur": all(
            p[-1][:1] in ("u", "p") for p in paquets if len(p) > 1
        ),
        "sans-dossier-outil": "CALL_DIR" not in lus,
        "sans-regle-ufw": lus.get("UFW_RULES", [""])[-1] == "0",
    }
    restes = {k: lus[k] for k in ("CONTAINER", "IMAGE", "ACCOUNT") if k in lus}
    return code == 0 and "END" in lus and all(detail.values()), dict(
        detail, restes=restes
    )


def script_etat_lignee():
    """Copie l'état en ETAT_GARDE (mode et propriétaire gardés), puis y
    inscrit coturn sous un certificat Let's Encrypt : la fiche qu'une
    installation Let's Encrypt écrit, et la seule sous laquelle le crochet
    copie la lignée vers coturn. Imprime `@@STAGED letsencrypt`."""
    return "\n".join(
        [
            "set -e",
            f"cp -p {ci.STATE_PATH} {ETAT_GARDE}",
            f"python3 -I - {ci.STATE_PATH} <<'EOF'",
            "import json",
            "import sys",
            "with open(sys.argv[1], encoding='utf-8') as fh:",
            "    etat = json.load(fh)",
            "etat['services']['coturn']['settings']['tls'] = 'letsencrypt'",
            "with open(sys.argv[1], 'w', encoding='utf-8') as fh:",
            "    json.dump(etat, fh)",
            "EOF",
            "echo '@@STAGED letsencrypt'",
            "",
        ]
    )


def script_remise():
    """Défait ce que les passes du crochet ont posé : l'état remis depuis
    ETAT_GARDE quand la copie existe, la fausse lignée retirée, et
    /etc/letsencrypt entier quand TEMOIN_LE dit qu'il est né de ce test.
    Imprime `@@RESTORED yes`."""
    return "\n".join(
        [
            "set -e",
            f"if [ -e {ETAT_GARDE} ]; then mv -f {ETAT_GARDE} {ci.STATE_PATH};"
            " fi",
            f"if [ -e {TEMOIN_LE} ]; then rm -rf /etc/letsencrypt;"
            f" else rm -rf {ci.LINEAGE_DIR}; fi",
            "echo '@@RESTORED yes'",
            "",
        ]
    )


def _sites_nginx():
    """Chaque chemin où l'outil peut poser son site ou son lien, toutes
    dispositions confondues."""
    chemins = []
    for disposition in ci.NGINX_LAYOUTS:
        site, lien, _inc = ci._nginx_paths(disposition)
        chemins += [c for c in (site, lien) if c and c not in chemins]
    return chemins


def script_traces():
    """Ce que l'outil laisse sur l'hôte, en lignes `@@` : `NGINX_FILE
    <chemin>` (site ou lien de l'outil), `INCLUDE present` (sa ligne dans
    nginx.conf), `HOOK present` (le crochet en HOOK_PATH), `LINEAGE
    present` (la fausse lignée), `CALL_DIR present`, `ACME present`,
    `PKG <paquet> <statut>` (nginx et nginx-common d'après dpkg, nginx
    d'après pacman), `NGINX_BIN present`, `UNIT <unité coturn>`,
    `UFW_RULES <n>` (règles ufw de l'outil), puis `END`."""
    return "\n".join(
        [
            "for p in " + " ".join(_sites_nginx()) + "; do",
            '  if [ -e "$p" ] || [ -L "$p" ]; then echo "@@NGINX_FILE $p"; fi',
            "done",
            f"if grep -qs '{ci.NGINX_INCLUDE_DIR}' {ci.NGINX_CONF}; then",
            "  echo '@@INCLUDE present'",
            "fi",
            f"if [ -e {ci.HOOK_PATH} ]; then echo '@@HOOK present'; fi",
            f"if [ -e {ci.LINEAGE_DIR} ]; then echo '@@LINEAGE present'; fi",
            f"if [ -e {ci.CALL_DIR} ]; then echo '@@CALL_DIR present'; fi",
            f"if [ -e {ci.ACME_ROOT} ]; then echo '@@ACME present'; fi",
            "if command -v dpkg-query >/dev/null 2>&1; then",
            "  dpkg-query -W -f='@@PKG ${Package} ${db:Status-Abbrev}\\n'"
            " nginx nginx-common 2>/dev/null || true",
            "fi",
            "if command -v pacman >/dev/null 2>&1"
            " && pacman -Qq nginx >/dev/null 2>&1; then",
            "  echo '@@PKG nginx ii'",
            "fi",
            "if command -v nginx >/dev/null 2>&1; then",
            "  echo '@@NGINX_BIN present'",
            "fi",
            "for u in " + " ".join(ci.COTURN_UNITS.values()) + "; do",
            '  if systemctl cat "$u" >/dev/null 2>&1; then echo "@@UNIT $u"; fi',
            "done",
            "N=0",
            "if command -v ufw >/dev/null 2>&1; then",
            f"  N=$(ufw show added 2>/dev/null | grep -c {ci.FIREWALL_COMMENT})",
            "fi",
            'echo "@@UFW_RULES ${N:-0}"',
            "echo @@END",
            "",
        ]
    )


def _traces(sortie):
    """{nom: [valeurs]} des lignes `@@` de `script_traces`."""
    lus = {}
    for nom, valeur in ci.marker_lines(sortie):
        lus.setdefault(nom, []).append(valeur.strip())
    return lus


def verdict_nginx(etat, sortie, distro):
    """(ok, détail) : nginx installé par l'outil, dans la disposition
    DISPOSITION_NGINX du système, avec sur l'hôte (`sortie` de
    `script_traces`) le site et le lien que l'état consigne, et la ligne
    include de nginx.conf quand l'état en consigne une."""
    fiche = (etat or {}).get("nginx")
    fiche = fiche if isinstance(fiche, dict) else {}
    lus = _traces(sortie)
    fichiers = set(lus.get("NGINX_FILE", []))
    voulus = [c for c in (fiche.get("site"), fiche.get("link")) if c]
    detail = {
        "installe-par-l-outil": fiche.get("installed_by_tool") is True,
        "disposition": fiche.get("layout") == DISPOSITION_NGINX.get(distro),
        "site-et-lien": bool(voulus) and all(c in fichiers for c in voulus),
        "ligne-include": bool(fiche.get("include")) == ("INCLUDE" in lus),
    }
    return "END" in lus and all(detail.values()), detail


def verdict_apres_prod(code, sortie, distro):
    """(ok, détail) de l'hôte après la désinstallation de production,
    d'après `sortie` de `script_traces` : ni site, lien ou ligne include
    de nginx, ni crochet ni fausse lignée, ni dossier de l'outil ni dossier
    ACME, nginx purgé (aucun paquet installé ni fichiers de configuration
    restants, aucun binaire), plus d'unité coturn, et sur Debian plus de
    règle ufw de l'outil."""
    lus = _traces(sortie)
    paquets = [v.split() for v in lus.get("PKG", [])]
    detail = {
        "sans-site-nginx": "NGINX_FILE" not in lus,
        "sans-ligne-include": "INCLUDE" not in lus,
        "sans-crochet": "HOOK" not in lus and "LINEAGE" not in lus,
        "sans-dossier-outil": "CALL_DIR" not in lus,
        "sans-dossier-acme": "ACME" not in lus,
        "nginx-purge": "NGINX_BIN" not in lus
        and all(p[-1][:1] in ("u", "p") for p in paquets if len(p) > 1),
        "sans-unite-coturn": "UNIT" not in lus,
    }
    if distro == "debian":
        detail["sans-regle-ufw"] = lus.get("UFW_RULES", [""])[-1] == "0"
    return code == 0 and "END" in lus and all(detail.values()), detail


class Scenario:
    """Les étapes d'un système dans un scénario, et leur journal. `etapes`
    : {nom: bool}, dans l'ordre où elles ont tourné ; `details` : ce qui
    éclaire un verdict (lignes de vérification, ports, rejeu du mélange,
    passes du crochet). `course` : la `Course` dont le rapport reçoit ce
    que le scénario crée hors de la VM (les bases Odoo), None sans elle.
    `variante` : le moteur d'une course `conteneur`, None sinon. `limite` :
    l'étape arrêtée par la limite du registre (`limite_registre`), None
    sans elle."""

    def __init__(
        self,
        distro,
        log,
        journal,
        scenario="dev",
        course=None,
        variante=None,
    ):
        self.distro = distro
        self.scenario = scenario
        self.variante = variante
        self.log = log
        self.journal = journal
        self.course = course
        self.etapes = {}
        self.details = {}
        self.limite = None

    def noter(self, nom, ok, detail=None):
        self.etapes[nom] = bool(ok)
        if detail is not None:
            self.details[nom] = detail
        marque = "✓" if ok else "✗"
        dire(f"      {marque} {nom}", self.journal)
        _ajouter(self.log, f"══ {marque} {nom} {detail if detail else ''}")
        return bool(ok)

    def limite_atteinte(self, nom, detail=None):
        """L'étape `nom` n'a pas pu tirer une image sous la limite du
        registre : ni réussie ni en échec, elle arrête la course, dont le
        verdict devient LIMITE_REGISTRE quand rien n'a échoué avant."""
        self.limite = nom
        if detail is not None:
            self.details[nom] = detail
        dire(f"      ⏳ {nom} : {MESSAGE_LIMITE}", self.journal)
        _ajouter(self.log, f"══ ⏳ {nom} {LIMITE_REGISTRE}")

    def ligne(self):
        echecs = [n for n, ok in self.etapes.items() if not ok]
        if echecs:
            verdict = f"ECHEC({echecs[0]})"
        elif self.limite:
            verdict = LIMITE_REGISTRE
        else:
            verdict = "OK"
        return {
            "distro": self.distro,
            "scenario": self.scenario,
            "variante": self.variante,
            "version": DISTROS[self.distro],
            "verdict": verdict,
            "etapes": self.etapes,
            "details": self.details,
            "journal": os.path.basename(self.log),
        }


def _texte_b64(valeur):
    """Le texte d'une valeur base64 de `inspect_script`, "" si illisible."""
    try:
        return base64.b64decode(valeur.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return ""


def _lignes_en_dict(lignes):
    return [
        {
            "name": li.name,
            "ok": li.ok,
            "detail": li.detail,
            "values": li.values,
        }
        for li in lignes
    ]


def _verification(sc, cible, ip, cafile, nom="verification", requis=None):
    """La vérification du menu notée `nom` : vert quand chaque ligne de
    `requis` (CONTROLES du scénario par défaut) est verte et qu'aucune
    autre n'est en échec."""
    lignes, lus = verifier(cible, ip, cafile, sc.log)
    if requis is None:
        requis = CONTROLES[sc.scenario][sc.distro]
    vert, problemes = verdict_controle(lignes, requis)
    sc.noter(
        nom,
        vert,
        {"problemes": problemes, "lignes": _lignes_en_dict(lignes)},
    )
    return lignes, lus


def _telephones(cible, log, proprietaire, etat=None):
    """Les comptes de téléphone que liste la CLI du ntfy de `etat`
    (`ci.ntfy_cli`) : le binaire de l'hôte sous `proprietaire` par paquets
    ou sans état, celle du conteneur en conteneurs."""
    cli = ci.ntfy_cli(etat, proprietaire)
    code, sortie = distant(
        cible,
        nm.list_script(ci.NTFY_CONFIG, cli.prefix),
        log,
        DELAI_SCRIPT,
        root=cli.sudo_user is None,
        utilisateur=cli.sudo_user,
    )
    return nm.phone_users(sortie) if code == 0 else []


def _preparer(sc, cible, distro):
    """Attente de cloud-init, puis la préparation propre au système : la
    préparation pacman du menu sur Arch, ufw actif sur Debian."""
    todo = _todo()
    code, _s = distant(
        cible,
        todo._qemu_cloud_init_wait(),
        sc.log,
        DELAI_PREPARATION,
        root=False,
        shell="bash",
    )
    if not sc.noter("cloud-init", code == 0):
        return False
    if distro == "arch":
        code, _s = distant(
            cible,
            todo._qemu_pacman_prepare_cmd(),
            sc.log,
            DELAI_PREPARATION,
            root=False,
            shell="bash",
        )
        return sc.noter("pacman", code == 0)
    code, sortie = distant(cible, SCRIPT_UFW, sc.log, DELAI_PREPARATION)
    return sc.noter("ufw-actif", code == 0 and "@@UFW active" in sortie)


def _semer_ntfy(sc, cible, ip):
    """ntfy posé à l'ancienne : install_ntfy.sh lancé seul, sans l'outil,
    donc une configuration sans marque, puis un compte de téléphone par
    `access_script`. Rend (empreinte du server.yml, propriétaire de la
    base, téléphone) ou None."""
    with open(ci.INSTALLERS["ntfy"], encoding="utf-8") as fh:
        installateur = fh.read()
    code, sortie = distant(
        cible,
        installateur,
        sc.log,
        DELAI_INSTALL,
        shell="bash",
        env={
            "NTFY_PORT": ci.NTFY_HTTP_PORT,
            "NTFY_BASE_URL": f"http://{ip}:{ci.NTFY_HTTP_PORT}",
            "NTFY_NON_INTERACTIVE": 1,
        },
    )
    actif = dict(ci.marker_lines(sortie)).get("ACTIVE", "")
    code, sortie = distant(
        cible, nm.inspect_script(ci.NTFY_CONFIG), sc.log, DELAI_SCRIPT
    )
    faits = nm.parse_markers(sortie)
    texte = _texte_b64(faits.get("YML", ""))
    if not sc.noter(
        "ntfy-ancien",
        code == 0 and actif.strip() == "ntfy active" and ci.is_foreign(texte),
    ):
        return None
    # Le compte qui possède la base des comptes, sous lequel le menu lance
    # la CLI de ntfy ; « ? » quand `stat` n'a rien lu.
    proprietaire = faits.get("OWNER", "").strip()
    if proprietaire in ("", "?"):
        proprietaire = "ntfy"
    telephone = nm.phone_user(LIBELLE_TELEPHONE)
    code, sortie = distant(
        cible,
        nm.access_script(ci.NTFY_CONFIG, telephone, nm.random_prefix()),
        sc.log,
        DELAI_SCRIPT,
        utilisateur=proprietaire,
    )
    if not sc.noter(
        "telephone-ancien", code == 0 and bool(nm.parse_token(sortie))
    ):
        return None
    empreinte = hashlib.sha256(texte.encode("utf-8")).hexdigest()
    return empreinte, proprietaire, telephone


def _melange(sc, cible, ip, cafile, answers, etat=None):
    """Le rejeu de la base partagée sur le vrai coturn : un secret REST
    ajouté par turnadmin à côté du compte de contrôle, puis une allocation
    de chaque sorte. Noté en information : il ne pèse pas sur le
    verdict. `etat` en conteneurs : turnadmin de l'image
    (`script_secret`)."""
    secret = secrets.token_hex(16)
    code, sortie = distant(cible, script_secret(ip, secret, etat), sc.log, 120)
    ajoute = dict(ci.marker_lines(sortie)).get("SECRET_RC", "").strip()
    user, password = turn_client.rest_credentials(
        secret, UTILISATEUR_REST, int(time.time()) + 3600
    )
    rest = turn_client.allocate(
        ip,
        answers.turn_port,
        "udp",
        user,
        turn_client.long_term_key(user, ip, password),
        timeout=5,
    )
    lignes, _lus = verifier(cible, ip, cafile, sc.log)
    controle = any(li.name == "turn-udp" and li.ok for li in lignes)
    detail = {
        "resultat": resultat_melange(rest.ok, controle),
        "turnadmin": ajoute or "?",
        "rest": "ok" if rest.ok else rest.error,
        "compte_controle": controle,
    }
    sc.details["melange"] = detail
    dire(f"      ℹ {detail['resultat']} {detail}", sc.journal)
    _ajouter(sc.log, f"══ ℹ melange {detail}")


def scenario_debian(sc, cible, ip, dossier):
    if not _preparer(sc, cible, "debian"):
        return
    seme = _semer_ntfy(sc, cible, ip)
    if seme is None:
        return
    empreinte, proprietaire, telephone = seme
    tls = local_cert.issue(os.path.join(dossier, "tls"), [ip])
    with open(tls["server_crt"], encoding="utf-8") as fh:
        cert = fh.read()
    with open(tls["server_key"], encoding="utf-8") as fh:
        cle = fh.read()
    answers = reponses(ip, cert, cle)
    res = installer(cible, answers, sc.log)
    if not sc.noter("installation", res["ok"], res["etape"] or None):
        return
    sc.noter("ntfy-adopte", "ntfy" in res["adoptes"])
    cafile = tls["ca_crt"]
    _verification(sc, cible, ip, cafile)
    sc.noter(
        "telephone-garde",
        telephone in _telephones(cible, sc.log, proprietaire),
    )
    again = installer(cible, answers, sc.log)
    sc.noter("rien-a-changer", again["ok"] and again["rien_a_faire"])
    _melange(sc, cible, ip, cafile, answers)
    sc.noter("desinstallation", desinstaller(cible, True, sc.log) == "fait")
    code, sortie = distant(cible, SCRIPT_APRES, sc.log, DELAI_SCRIPT)
    lus = dict(ci.marker_lines(sortie))
    unites = [v for n, v in ci.marker_lines(sortie) if n == "UNIT"]
    apres = {
        "sans-unite-coturn": not any(
            u.strip() in ci.COTURN_UNITS.values() for u in unites
        ),
        "sans-dossier-outil": "CALL_DIR" not in lus,
        "sans-regle-ufw": lus.get("UFW_RULES", "").strip() == "0",
        "server-yml-remis": lus.get("YML_SHA", "").strip() == empreinte,
        "ntfy-adopte-actif": lus.get("NTFY", "").strip() == "active",
        "telephone-toujours-la": telephone
        in _telephones(cible, sc.log, proprietaire),
    }
    sc.noter(
        "etat-apres-desinstallation",
        code == 0 and "END" in lus and all(apres.values()),
        apres,
    )
    ports = ports_fermes(
        ip,
        tcp=(answers.turn_port, answers.turns_port, ci.ntfy_port(answers)),
        udp=(answers.turn_port,),
    )
    sc.noter("ports-fermes", all(ports.values()), ports)
    sc.noter(
        "desinstallation-vide", desinstaller(cible, True, sc.log) == "rien"
    )


def scenario_arch(sc, cible, ip, dossier):
    if not _preparer(sc, cible, "arch"):
        return
    answers = reponses(ip)
    res = installer(cible, answers, sc.log)
    if not sc.noter("installation", res["ok"], res["etape"] or None):
        return
    _verification(sc, cible, ip, None)
    sc.noter("desinstallation", desinstaller(cible, True, sc.log) == "fait")
    ports = ports_fermes(
        ip,
        tcp=(answers.turn_port, ci.ntfy_port(answers)),
        udp=(answers.turn_port,),
    )
    sc.noter("ports-fermes", all(ports.values()), ports)
    sc.noter(
        "desinstallation-vide", desinstaller(cible, True, sc.log) == "rien"
    )


def _pid(cible, unite, log, executer):
    code, sortie = executer(cible, script_pid(unite), log, DELAI_SCRIPT)
    valeurs = [v for n, v in ci.marker_lines(sortie) if n == "PID"]
    return valeurs[-1].strip() if code == 0 and valeurs else ""


def crochet(
    sc,
    cible,
    ip,
    answers,
    unite,
    etape,
    lignee,
    attendu_turn,
    executer=distant,
    vu=None,
    attente=None,
    lire_pid=None,
    nginx=True,
):
    """Une passe du crochet de déploiement, notée `etape`.

    `lignee` (certificat, clé) est posée en fausse lignée LINEAGE_DIR, puis
    le texte du crochet du produit (`ci.deploy_hook_text`) part en root avec
    RENEWED_LINEAGE, comme certbot le lance après un renouvellement. Le
    verdict (`verdict_crochet`) lit le MainPID de `unite` avant et après,
    le certificat que coturn sert sur son port TLS sous le nom de TURN
    (attendu : `attendu_turn`, relu `attente` secondes au plus) et celui
    que nginx sert sur 443 sous le nom de ntfy (attendu : le certificat
    fourni des réponses, que son site lit). `vu` (forme de
    `certificat_vu`) et `attente` (DELAI_SERIE) sont lus à l'appel.

    `lire_pid()` rend le PID de coturn à la place du MainPID de `unite` :
    celui du conteneur, pour un coturn en conteneur. Sans `nginx`, ni son
    rechargement ni son certificat ne sont jugés."""
    vu = vu or certificat_vu
    attente = DELAI_SERIE if attente is None else attente
    if lire_pid is None:

        def lire_pid():
            return _pid(cible, unite, sc.log, executer)

    avant = lire_pid()
    code, sortie = executer(
        cible, script_lignee(*lignee), sc.log, DELAI_SCRIPT
    )
    pose = code == 0 and ("LINEAGE", "placed") in ci.marker_lines(sortie)
    code, sortie = executer(
        cible,
        ci.deploy_hook_text(),
        sc.log,
        DELAI_SCRIPT,
        shell="bash",
        env={"RENEWED_LINEAGE": ci.LINEAGE_DIR},
    )
    apres = lire_pid()
    servi_turn = attendre_certificat(
        vu,
        ip,
        ci.coturn_tls_port(answers),
        ci.turn_host(answers),
        attendu_turn,
        attente,
    )
    servis = {"turn-tls": (attendu_turn, servi_turn)}
    if nginx:
        servi_nginx = vu(ip, ci.HTTPS_PORT, ci.ntfy_host(answers))
        servis["nginx"] = (answers.cert_pem, servi_nginx)
    requis, interdits = attendus_crochet(etape, unite, nginx)
    ok, detail = verdict_crochet(
        code, sortie, requis, interdits, (avant, apres), servis
    )
    detail["lignee"] = pose
    return sc.noter(etape, pose and ok, detail)


def crochets(
    sc,
    cible,
    ip,
    answers,
    unite,
    premier,
    second,
    executer=distant,
    vu=None,
    attente=None,
    lire_pid=None,
    nginx=True,
):
    """Le crochet de déploiement lancé à la main, en trois passes, puis la
    remise de l'hôte. `lire_pid` et `nginx` vont à chaque passe
    (`crochet`).

    L'installation de production de cette course prend le certificat
    `premier`, FOURNI : aucune autorité ACME ne joint une VM sous un nom
    inventé. `second` est un nouveau certificat de la même autorité, d'un
    autre numéro de série, posé en fausse lignée comme après un
    renouvellement.

    1. `crochet-fourni` : sous l'état écrit (certificat fourni), le crochet
       ne touche pas coturn et recharge nginx ; coturn et nginx servent
       toujours `premier`.
    2. `crochet-lignee` : l'état inscrit coturn sous Let's Encrypt
       (`script_etat_lignee`) ; le crochet copie la lignée, envoie SIGUSR2
       sans redémarrer coturn (même MainPID) et coturn sert `second`.
       nginx sert toujours `premier` : son site lit le certificat fourni,
       pas la lignée.
    3. `crochet-retour` : `premier` reposé en lignée, le même chemin rend
       à coturn sa paire d'origine et son empreinte coturn.applied.
    4. `crochet-remise` : l'état d'origine remis et la fausse lignée
       retirée, même quand une passe a échoué, pour que la relance et la
       désinstallation jugent l'hôte de l'installation."""

    def passe(etape, lignee, attendu_turn):
        crochet(
            sc,
            cible,
            ip,
            answers,
            unite,
            etape,
            lignee,
            attendu_turn,
            executer=executer,
            vu=vu,
            attente=attente,
            lire_pid=lire_pid,
            nginx=nginx,
        )

    try:
        passe("crochet-fourni", second, premier[0])
        code, sortie = executer(
            cible, script_etat_lignee(), sc.log, DELAI_SCRIPT
        )
        if code != 0 or ("STAGED", "letsencrypt") not in ci.marker_lines(
            sortie
        ):
            sc.noter("crochet-lignee", False, "etat")
            return
        passe("crochet-lignee", second, second[0])
        passe("crochet-retour", premier, premier[0])
    finally:
        code, sortie = executer(cible, script_remise(), sc.log, DELAI_SCRIPT)
        sc.noter(
            "crochet-remise",
            code == 0 and ("RESTORED", "yes") in ci.marker_lines(sortie),
        )


def scenario_prod(sc, cible, ip, dossier):
    if not _preparer(sc, cible, sc.distro):
        return
    tls = os.path.join(dossier, f"tls-prod-{sc.distro}")
    noms = noms_certificat(ip)
    chemins = local_cert.issue(tls, noms)
    premier = paire(chemins)
    second = paire(local_cert.issue(tls, noms))
    series = [_hex(serie_pem(premier[0])), _hex(serie_pem(second[0]))]
    if not sc.noter(
        "certificats", None not in series and series[0] != series[1], series
    ):
        return
    cafile = chemins["ca_crt"]

    def reponses_de(facts):
        return reponses_prod(ip, *premier, facts)

    res = installer(cible, reponses_de, sc.log)
    if not sc.noter("installation", res["ok"], res["etape"] or None):
        return
    answers, etat = res["answers"], res["etat"]
    code, sortie = distant(cible, script_traces(), sc.log, DELAI_SCRIPT)
    ok, detail = verdict_nginx(etat, sortie, sc.distro)
    sc.noter("nginx-installe", code == 0 and ok, detail)
    _verification(sc, cible, ip, cafile)
    unite = etat["services"]["coturn"]["unit"]
    crochets(sc, cible, ip, answers, unite, premier, second)
    _verification(sc, cible, ip, cafile, nom="verification-apres-crochet")
    again = installer(cible, reponses_de, sc.log)
    sc.noter("rien-a-changer", again["ok"] and again["rien_a_faire"])
    sc.noter("desinstallation", desinstaller(cible, True, sc.log) == "fait")
    code, sortie = distant(cible, script_traces(), sc.log, DELAI_SCRIPT)
    ok, apres = verdict_apres_prod(code, sortie, sc.distro)
    sc.noter("etat-apres-desinstallation", ok, apres)
    ports = ports_fermes(
        ip,
        tcp=(
            ci.HTTP_PORT,
            ci.HTTPS_PORT,
            answers.turn_port,
            ci.coturn_tls_port(answers),
        ),
        udp=(answers.turn_port,),
    )
    sc.noter("ports-fermes", all(ports.values()), ports)
    sc.noter(
        "desinstallation-vide", desinstaller(cible, True, sc.log) == "rien"
    )


# --- Serveurs Odoo ------------------------------------------------------


def noms_bases(identifiant):
    """{lettre: base} des trois bases d'une course : `call_infra_odoo_
    <identifiant>_<lettre>`. ValueError pour un identifiant qui ne donne pas
    un nom de la forme `_BASE_ODOO` (63 octets au plus, la borne de
    PostgreSQL)."""
    bases = {}
    for lettre in LETTRES_ODOO:
        nom = f"{PREFIXE_BASE_ODOO}{identifiant}_{lettre}"
        if not _BASE_ODOO.match(nom) or len(nom) > mso.LONGUEUR_NOM_MAX:
            raise ValueError(f"nom de base invalide : {nom!r}")
        bases[lettre] = nom
    return bases


def identifiant_de(course):
    """`<pid>_<horodatage>` de la course, ou d'ici et maintenant sans
    elle."""
    return getattr(course, "identifiant", None) or (
        f"{os.getpid()}_{time.strftime('%Y%m%d%H%M%S')}"
    )


def identifiant_migration(course):
    """L'identifiant des bases de la migration : celui de la course suivi
    d'un 0, pour que sa base ne prenne jamais le nom d'une base du scénario
    `odoo` de la même course ; il garde la forme de `_BASE_ODOO`, que
    `--detruire` supprime."""
    return identifiant_de(course) + "0"


def sorte_url(url):
    """« turn-udp », « turn-tcp », « turns » ou le schéma d'une URL ICE ;
    `turn:` sans transport est UDP, comme `check_through_odoo` l'alloue."""
    schema = url.split(":", 1)[0].lower()
    if schema != "turn":
        return schema
    return "turn-tcp" if "transport=tcp" in url.lower() else "turn-udp"


def verdict_ice(lignes, attendus, refuse=False):
    """(ok, détail) des lignes de `check_through_odoo`.

    Les sortes d'URL des lignes (`sorte_url`) doivent être exactement
    `attendus`. Accepté : chaque ligne est verte. Refusé (`refuse`) :
    chaque ligne est en échec sous un 401 de coturn, ses identifiants
    inconnus ; une panne (délai, connexion) ne prouve pas la révocation."""
    sortes = {}
    for ligne in lignes:
        sorte = sorte_url(str(ligne.values.get("url", "")))
        sortes.setdefault(sorte, []).append(ligne)

    def bonne(ligne):
        if not refuse:
            return ligne.ok is True
        erreur = str(ligne.values.get("error") or "")
        return ligne.ok is False and erreur.startswith("401")

    detail = {
        "manque": [s for s in attendus if s not in sortes],
        "en_trop": sorted(set(sortes) - set(attendus)),
        "en_defaut": [li.name for li in lignes if not bonne(li)],
        "lignes": _lignes_en_dict(lignes),
    }
    ok = bool(lignes) and not any(
        detail[k] for k in ("manque", "en_trop", "en_defaut")
    )
    return ok, detail


def adresse_vers(ip):
    """L'adresse de cette machine que la VM `ip` voit : la source que le
    noyau choisit pour la joindre (connect UDP, aucun paquet envoyé). ""
    quand `ip` n'est pas joignable ou pas une adresse."""
    famille = socket.AF_INET6 if ":" in ip else socket.AF_INET
    try:
        with socket.socket(famille, socket.SOCK_DGRAM) as prise:
            prise.connect((ip, 9))
            return prise.getsockname()[0]
    except (OSError, UnicodeError):
        return ""


def exempt_du_menu(url, tapee):
    """L'adresse que le menu exempte des limites de ntfy pour l'Odoo `url`
    quand l'opérateur tape `tapee` : sa proposition, `external_ip_for` sur
    le nom de l'URL sans adresse d'hôte (Odoo n'est pas joint par
    odoo-bin shell sur l'hôte de coturn), tombe quand ntfy ne peut pas
    l'exempter — la boucle locale d'un Odoo du harnais —, et ce qui est
    tapé l'emporte. None quand il ne reste rien."""
    nom = urllib.parse.urlsplit(ol.normalize_url(url)).hostname or ""
    propose, _raison = ci.external_ip_for(nom, (), resolve=cim._resolve)
    if propose and not _todo()._call_infra_exempt_ok(propose):
        propose = None
    return tapee or propose or None


def mode_conf(facts):
    """« secret » (`use-auth-secret`) ou « fixed » (`lt-cred-mech`) d'après
    la configuration de coturn que la sonde a lue ; None sans elle, ou
    quand elle porte les deux."""
    texte = ((facts and facts.coturn) or {}).get("config_text") or ""
    lignes = {ligne.strip() for ligne in texte.splitlines()}
    secret, fixe = "use-auth-secret" in lignes, "lt-cred-mech" in lignes
    if secret == fixe:
        return None
    return "secret" if secret else "fixed"


def exempts(facts):
    """Les hôtes exemptés des limites de ntfy dans le `server.yml` que la
    sonde a lu ; [] sans lui."""
    texte = ((facts and facts.ntfy) or {}).get("config_text") or ""
    valeur = nm.read_yml_keys(texte).get(nm.EXEMPT_HOSTS_KEY, "")
    return [h.strip() for h in valeur.split(",") if h.strip()]


def _refus(res, cle, log, quoi):
    res["refus"] = cle
    _ajouter(log, f"✗ {quoi} : {cle}")
    return res


def _cle_refus(refus):
    """La clé d'un refus, suivie après « / » de celle de sa cause quand
    c'est une erreur d'Odoo, comme le menu affiche les deux."""
    cause = refus.__cause__
    if isinstance(cause, ol.OdooError):
        return f"{refus.key}/{cause.key}"
    return refus.key


def ajouter_odoo(
    cible,
    lien,
    url,
    base,
    installer_module,
    exempt,
    log,
    executer=distant,
    maintenant=None,
):
    """Le chemin du menu « Ajouter un serveur Odoo », sans ses questions.

    Sonde de l'hôte de coturn, faits de la base par `lien` (version,
    connexion et droits vérifiés avant toute écriture), choix du module
    (`installer_module` : le oui à « Installer erplibre_turn ? », lu
    seulement quand le module est installable), mode de coturn, plan, puis
    `apply_odoo_add` dont chaque script part par `executer`. `exempt` :
    l'adresse que l'opérateur retient pour ntfy.

    Rend {"ok", "etape", "refus", "plan", "etat"} : `etape` nomme ce qui a
    échoué (sonde, coturn, odoo, plan, ajout), `refus` la clé du refus
    (`_cle_refus`), `etat` l'état écrit."""
    res = {"ok": False, "etape": "sonde", "refus": None, "plan": None}
    res["etat"] = None
    facts = _sonde(cible, log, executer)
    if facts is None:
        return res
    res["etape"] = "coturn"
    answers = ci.state_answers(facts.state)
    if answers is None or "coturn" not in answers.services:
        return _refus(res, "call_infra_odoo_no_coturn", log, "ajout")
    res["etape"] = "odoo"
    try:
        odoo = lien.facts()
    except ol.OdooError as erreur:
        return _refus(res, erreur.key, log, "ajout")
    res["etape"] = "plan"
    todo = _todo()
    sorte = todo._call_infra_module_kind(odoo)
    installer_aussi = sorte == "installable" and bool(installer_module)
    try:
        ci.turn_mode_for(facts.state, sorte == "installed" or installer_aussi)
        plan = ci.plan_odoo_add(
            facts.state,
            odoo,
            url,
            base,
            installer_aussi,
            exempt,
            ntfy_text=todo._call_infra_ntfy_text(facts),
        )
    except ci.Refusal as refus:
        return _refus(res, refus.key, log, "ajout")
    res.update(plan=plan, etape="ajout")
    try:
        etat = ci.apply_odoo_add(
            lambda script: executer(cible, script, log, DELAI_INSTALL),
            lien,
            plan,
            maintenant or datetime.datetime.now(datetime.timezone.utc),
        )
    except ci.Refusal as refus:
        return _refus(res, _cle_refus(refus), log, "ajout")
    except ol.OdooError as erreur:
        return _refus(res, erreur.key, log, "ajout")
    res.update(ok=True, etape="", etat=etat)
    return res


def retirer_odoo(cible, lien, cle, log, executer=distant, maintenant=None):
    """Le chemin du menu « Retirer un serveur Odoo » : sonde, puis
    `apply_odoo_remove` (Odoo nettoyé par `lien`, puis l'identifiant
    révoqué sur coturn par `executer`). Odoo joignable ici : jamais de
    révocation « quand même ».

    Rend {"ok", "etape", "refus", "etat"}, comme `ajouter_odoo` ; une clé
    que l'état ne consigne pas est le refus « absent »."""
    res = {"ok": False, "etape": "sonde", "refus": None, "etat": None}
    facts = _sonde(cible, log, executer)
    if facts is None:
        return res
    res["etape"] = "retrait"
    try:
        etat = ci.apply_odoo_remove(
            lambda script: executer(cible, script, log, DELAI_INSTALL),
            lien,
            facts.state,
            cle,
            now=maintenant or datetime.datetime.now(datetime.timezone.utc),
            ntfy_text=_todo()._call_infra_ntfy_text(facts),
        )
    except ci.Refusal as refus:
        return _refus(res, _cle_refus(refus), log, "retrait")
    except ValueError:
        return _refus(res, "absent", log, "retrait")
    res.update(ok=True, etape="", etat=etat)
    return res


def allouer(ice, etat, cafile):
    """Les lignes de `check_through_odoo` pour la liste ICE `ice`, sous le
    realm et le nom de TURN du coturn de `etat`, comme « Vérifier par
    Odoo » du menu : une allocation réelle depuis cette machine par URL de
    TURN."""
    answers = ci.state_answers(etat)
    if answers is None:
        return [ci.CheckLine("odoo-ice", False, "call_infra_odoo_no_coturn")]
    return ci.check_through_odoo(
        ice,
        answers.public_name,
        None,
        cafile,
        turn_host=ci.turn_host(answers),
    )


def par_odoo(harnais, lettre, etat, cafile, invitation=None):
    """(liste ICE, lignes) de « Vérifier par Odoo » sur la base `lettre` :
    l'utilisateur UTILISATEUR_ODOO entre dans un appel
    (`WebApi.join_call_ice`), ou un invité par le lien `invitation`
    (`join_call_ice_guest`), puis chaque URL de TURN remise s'alloue
    (`allouer`). Un refus d'Odoo rend ([], une ligne `odoo-ice` en échec
    sous sa clé). La liste garde les identifiants remis : elle ne va
    jamais au journal."""
    api = harnais.lien(lettre, *UTILISATEUR_ODOO)
    try:
        if invitation is None:
            ice = api.join_call_ice(*UTILISATEUR_ODOO)
        else:
            ice = api.join_call_ice_guest(invitation)
    except ol.OdooError as erreur:
        return [], [ci.CheckLine("odoo-ice", False, erreur.key)]
    return ice, allouer(ice, etat, cafile)


def lien_invitation(lien):
    """Le lien d'invitation d'un canal public créé dans la base de `lien`
    (compte administrateur) : `<URL>/chat/<id>/<uuid>`, celui qu'Odoo
    montre sous « Inviter ». Sans groupe (`group_public_id` faux), le canal
    laisse entrer un invité. `WebApi` n'a pas de méthode publique pour
    créer un enregistrement quelconque : son appel JSON-RPC (`_execute`)
    sert ici."""
    ident = lien._execute(
        "discuss.channel",
        "create",
        [
            {
                "name": CANAL_INVITES,
                "channel_type": "channel",
                "group_public_id": False,
            }
        ],
    )
    (fiche,) = lien._execute(
        "discuss.channel", "read", [[ident]], {"fields": ["uuid"]}
    )
    return f"{lien.url}/chat/{ident}/{fiche['uuid']}"


def bases_restantes(noms):
    """Celles de `noms` que PostgreSQL connaît encore ou dont le filestore
    reste ; toutes quand psql ne répond pas, rien n'étant prouvé."""
    try:
        vues = set(
            mso.psql(
                "SELECT datname FROM pg_database"
                f" WHERE datname LIKE '{PREFIXE_BASE_ODOO}%'"
            ).split()
        )
    except (RuntimeError, OSError):
        return list(noms)
    filestore = mso.CACHE / "data" / "filestore"
    return [n for n in noms if n in vues or (filestore / n).exists()]


class Harnais:
    """Les Odoo 18 d'un scénario, sur cette machine : un par lettre de
    `lettres`, les trois du scénario `odoo` par défaut.

    Le gabarit Odoo 18 de `mobile_sync_odoo` (construit une fois, gardé),
    copié en une base `noms_bases` par lettre, puis un serveur par base
    sur des ports libres de 127.0.0.1, sans worker ni cron, filtré sur sa
    base, son dossier dans celui de la course (`odoo-<lettre>`). Le chemin
    d'addons
    de la 18 porte `ERPLibre_erplibre_addons`, donc `erplibre_turn` :
    installable, non installé. Chaque base entre au rapport (`course`)
    AVANT d'exister : une course tuée laisse de quoi la supprimer
    (`defaire_odoo`)."""

    def __init__(
        self,
        dossier,
        identifiant,
        course=None,
        journal=None,
        lettres=LETTRES_ODOO,
    ):
        self.dossier = dossier
        self.bases = {
            lettre: base
            for lettre, base in noms_bases(identifiant).items()
            if lettre in lettres
        }
        self.course = course
        self.journal = journal
        self.serveurs = {}
        self.inscrites = []

    def preparer(self):
        """(ok, détail) : les trois serveurs debout ({lettre: url}), ou la
        raison d'un échec."""
        try:
            version = mso.versions_installees(demandees=(18,))[18]
            mso.construire_gabarit(
                version, journal=lambda m: dire(f"      {m}", self.journal)
            )
            for lettre, base in self.bases.items():
                self.inscrites.append(base)
                if self.course is not None:
                    self.course.noter_base(base)
                mso.copier_gabarit(version, base)
                dossier = Path(self.dossier) / f"odoo-{lettre}"
                dossier.mkdir(parents=True, exist_ok=True)
                self.serveurs[lettre] = mso.demarrer_serveur(
                    version, base, dossier
                )
        except (
            mso.PrerequisManquant,
            RuntimeError,
            OSError,
            ValueError,
            subprocess.SubprocessError,
        ) as souci:
            return False, str(souci)[-500:]
        return True, {lettre: s.url for lettre, s in self.serveurs.items()}

    def url(self, lettre):
        return self.serveurs[lettre].url

    def lien(self, lettre, login=ADMIN_ODOO[0], mot_de_passe=ADMIN_ODOO[1]):
        """Le `ol.WebApi` de la base `lettre`, sous l'administrateur par
        défaut : un lien neuf à chaque action, comme le menu qui redemande
        les identifiants."""
        return ol.WebApi(
            self.url(lettre), self.bases[lettre], login, mot_de_passe
        )

    def defaire(self):
        """Serveurs arrêtés, bases inscrites supprimées avec leur
        filestore. Rend celles qui restent ; aucune, et le rapport les
        oublie."""
        for serveur in self.serveurs.values():
            mso.arreter_serveur(serveur)
        for base in self.inscrites:
            mso.supprimer_base(base)
        restantes = bases_restantes(self.inscrites) if self.inscrites else []
        if not restantes and self.course is not None:
            self.course.oublier_odoo()
        return restantes


def est_serveur_de(ligne, course):
    """Vrai quand la ligne de commande `ligne` (`mso.commande_de`, argv
    séparés par des espaces) est celle d'un serveur Odoo du harnais de la
    course `course` : un argv qui finit par `odoo-bin`, suivi plus loin de
    `-c` et d'un fichier de configuration sous `<course>/odoo-`. Le même
    chemin dans une autre commande (un éditeur, `tail`) n'en fait pas un."""
    marque = os.path.join(course, "odoo-")
    argv = ligne.split()
    for i, mot in enumerate(argv):
        if mot.endswith("odoo-bin"):
            suite = argv[i + 1 :]
            return any(
                a == "-c" and b.startswith(marque)
                for a, b in zip(suite, suite[1:])
            )
    return False


def serveurs_de(course, proc="/proc", lire=None):
    """Les pid des serveurs Odoo du harnais de la course dont `course` est
    le dossier (`est_serveur_de`). `lire(pid)` rend la ligne de commande
    (`mso.commande_de`)."""
    lire = lire or mso.commande_de
    try:
        entrees = os.listdir(proc)
    except OSError:
        return []
    return sorted(
        int(e)
        for e in entrees
        if e.isdigit()
        and int(e) != os.getpid()
        and est_serveur_de(lire(int(e)), course)
    )


def arreter_serveurs(
    pids, course, tuer=os.kill, lire=None, delai=DELAI_ARRET_ODOO
):
    """SIGTERM à chaque pid, puis SIGKILL à ceux qui sont encore, après
    `delai` secondes, un serveur du harnais de `course`
    (`est_serveur_de`) : un pid repris entre-temps par un autre programme
    ne reçoit rien."""
    lire = lire or mso.commande_de

    def encore(pid):
        return est_serveur_de(lire(pid), course)

    vivants = []
    for pid in pids:
        try:
            tuer(pid, signal.SIGTERM)
            vivants.append(pid)
        except ProcessLookupError:
            continue
    fin = time.monotonic() + delai
    while vivants and time.monotonic() < fin:
        time.sleep(0.2)
        vivants = [pid for pid in vivants if encore(pid)]
    for pid in [p for p in vivants if encore(p)]:
        try:
            tuer(pid, signal.SIGKILL)
        except ProcessLookupError:
            continue


def defaire_odoo(journal, dry_run, dossier=None):
    """Ce qu'une course du scénario `odoo` n'a pas pu défaire (tuée,
    coupée), avant les VM de `detruire` : pour chaque rapport de ce test,
    ni à blanc ni d'une course vivante, qui nomme encore des bases, ses
    serveurs Odoo arrêtés (`serveurs_de`), ses bases supprimées avec leur
    filestore, puis le rapport réécrit avec celles qui restent. Seul un nom
    de la forme `_BASE_ODOO` est supprimé. Rend le nombre de bases visées ;
    `dry_run` les nomme sans rien toucher."""
    dossier = dossier or os.path.expanduser("~/.erplibre/longtest")
    try:
        fichiers = sorted(
            f
            for f in os.listdir(dossier)
            if f.startswith(NOM_BASE) and f.endswith(".json")
        )
    except OSError:
        return 0
    total = 0
    for nom in fichiers:
        chemin = os.path.join(dossier, nom)
        try:
            with open(chemin, encoding="utf-8") as fh:
                rapport = json.load(fh)
        except (OSError, ValueError):
            continue
        if (
            not isinstance(rapport, dict)
            or rapport.get("outil") != OUTIL
            or rapport.get("dry_run")
            or descente_vivante(rapport.get("pid"))
        ):
            continue
        bloc = (
            rapport.get("odoo")
            if isinstance(rapport.get("odoo"), dict)
            else {}
        )
        bases = [
            b
            for b in bloc.get("bases") or []
            if isinstance(b, str) and _BASE_ODOO.match(b)
        ]
        if not bases:
            continue
        course = chemin[: -len(".json")]
        pids = serveurs_de(course)
        dire(
            f"  {nom} : {len(pids)} serveur(s) Odoo, bases {', '.join(bases)}",
            journal,
        )
        total += len(bases)
        if dry_run:
            continue
        arreter_serveurs(pids, course)
        for base in bases:
            mso.supprimer_base(base)
        restantes = bases_restantes(bases)
        rapport["odoo"] = {"bases": restantes}
        with open(chemin, "w", encoding="utf-8") as fh:
            json.dump(rapport, fh, indent=2)
        if restantes:
            dire(f"  ✗ bases restantes : {', '.join(restantes)}", journal)
    if dry_run and total:
        dire("  --dry-run : aucune base supprimée.", journal)
    return total


def detruire_bases(journal, dry_run):
    """`--detruire` quand aucun rapport ne nomme de VM : les serveurs et
    bases Odoo que des rapports nomment encore (`defaire_odoo`), sous les
    garde-fous du défaire partagé. Rien tant qu'une descente tourne
    (`descente.autre_descente`) ; puis la liste ; avec `dry_run`, rien de
    plus ; sinon la suppression, seulement après « tapez OUI ». Rend 1
    quand une descente tourne ou que la confirmation est refusée, 0
    sinon."""
    autres = descente.autre_descente()
    if autres:
        dire(
            f"  ⛔ une descente tourne ({', '.join(map(str, autres))}) :"
            " rien ne sera détruit.",
            journal,
        )
        dire("  Attendre qu'elle finisse, ou l'arrêter d'abord.", journal)
        return 1
    if not defaire_odoo(journal, True):
        dire("  aucun rapport de descente : rien à défaire.", journal)
        return 0
    if dry_run:
        return 0
    reponse = input("\n  Supprimer ces bases ? (tapez OUI) : ").strip()
    if reponse != "OUI":
        dire("  annulé.", journal)
        return 1
    defaire_odoo(journal, False)
    return 0


def _faits_odoo(lien):
    """`OdooFacts` de la base, None quand elle ne répond pas."""
    try:
        return lien.facts()
    except ol.OdooError:
        return None


def _lignes_outil(odoo, cle):
    """Les lignes `mail.ice.server` que l'outil a écrites dans la base de
    `cle` (son nom `ol.owned_username`)."""
    url, _, base = cle.rpartition("|")
    nom = ol.owned_username(url, base)
    return [r for r in (odoo.rows if odoo else ()) if r.get("username") == nom]


def _fiche(etat, cle):
    fiche = ((etat or {}).get("odoos") or {}).get(cle)
    return fiche if isinstance(fiche, dict) else {}


def _empreinte(etat, cle):
    """L'empreinte du secret de la base `cle` que l'état consigne."""
    return (_fiche(etat, cle).get("credential") or {}).get("value_sha256")


def _exempt_present(facts, exempt, present):
    """Vrai quand `server.yml` porte `exempt` (`present`) ou ne le porte
    pas ; toujours vrai sans adresse exemptée dans cette course."""
    return exempt is None or (exempt in exempts(facts)) == present


def _pid_valide(pid):
    return pid.isdigit() and pid != "0"


class _Odoo:
    """Ce que les phases du scénario partagent : la VM (alias et adresse),
    le harnais, le certificat, l'adresse exemptée, l'unité de coturn, le
    MainPID après la bascule et les listes ICE remises."""

    def __init__(self, sc, cible, ip, harnais, cafile, exempt, unite):
        self.sc = sc
        self.cible = cible
        self.ip = ip
        self.harnais = harnais
        self.cafile = cafile
        self.exempt = exempt
        self.unite = unite
        self.pid = ""
        self.remis = {}

    def cle(self, lettre):
        return ol.odoo_key(
            self.harnais.url(lettre), self.harnais.bases[lettre]
        )

    def ajouter(self, lettre, module):
        return ajouter_odoo(
            self.cible,
            self.harnais.lien(lettre),
            self.harnais.url(lettre),
            self.harnais.bases[lettre],
            module,
            self.exempt,
            self.sc.log,
        )

    def retirer(self, lettre):
        return retirer_odoo(
            self.cible,
            self.harnais.lien(lettre),
            self.cle(lettre),
            self.sc.log,
        )

    def sonde(self):
        return _sonde(self.cible, self.sc.log, distant)

    def pid_coturn(self):
        return _pid(self.cible, self.unite, self.sc.log, distant)

    def par_odoo(self, lettre, etat, invitation=None):
        return par_odoo(self.harnais, lettre, etat, self.cafile, invitation)

    def noter_ice(self, nom, lignes, attendus, refuse=False, **en_plus):
        ok, detail = verdict_ice(lignes, attendus, refuse)
        detail.update(en_plus)
        return self.sc.noter(nom, ok and all(en_plus.values()), detail)


def _phase_a(o):
    """A sans le module (installable, son installation refusée) : compte
    fixe, trois lignes, coturn en `lt-cred-mech` ; ses deux URL `turn:`
    s'allouent sous les identifiants qu'Odoo remet. Puis A retiré : lignes
    parties, compte révoqué (les identifiants remis avant → 401)."""
    cle = o.cle("a")
    res = o.ajouter("a", False)
    facts = o.sonde()
    etat = facts.state if facts else {}
    odoo = _faits_odoo(o.harnais.lien("a"))
    detail = {
        "ajout": res["ok"],
        "refus": res["refus"],
        "compte-fixe": (_fiche(etat, cle).get("credential") or {}).get("kind")
        == "user",
        "mode": etat.get("turn_mode") == "fixed",
        "lt-cred-mech": mode_conf(facts) == "fixed",
        "trois-lignes": len(_lignes_outil(odoo, cle)) == 3,
        "exempt": _exempt_present(facts, o.exempt, True),
    }
    o.sc.noter(
        "a-fixe", all(v for k, v in detail.items() if k != "refus"), detail
    )
    ice, lignes = o.par_odoo("a", etat)
    o.remis["a"] = ice
    o.noter_ice("a-par-odoo", lignes, ICE_FIXE)
    res = o.retirer("a")
    facts = o.sonde()
    etat = facts.state if facts else {}
    odoo = _faits_odoo(o.harnais.lien("a"))
    detail = {
        "retrait": res["ok"],
        "hors-etat": cle not in ((etat or {}).get("odoos") or {}),
        "sans-lignes": odoo is not None and not _lignes_outil(odoo, cle),
        "exempt-retire": _exempt_present(facts, o.exempt, False),
    }
    o.sc.noter("a-retire", all(detail.values()), detail)
    o.noter_ice(
        "a-revoque", allouer(o.remis["a"], etat, o.cafile), ICE_FIXE, True
    )


def _noter_module(o, nom, lettre, res, facts):
    """L'ajout d'une base avec le module : installé par l'outil, ses
    paramètres posés, aucune ligne de l'outil, une fiche en secret et
    l'adresse exemptée dans `server.yml`."""
    cle = o.cle(lettre)
    etat = facts.state if facts else {}
    odoo = _faits_odoo(o.harnais.lien(lettre))
    params = odoo.params if odoo else {}
    detail = {
        "ajout": res["ok"],
        "refus": res["refus"],
        "module-installe": bool(odoo) and odoo.module_state == "installed",
        "parametres": ol.PARAM_URLS in params and ol.PARAM_SECRET in params,
        "sans-lignes": odoo is not None and not _lignes_outil(odoo, cle),
        "secret": (_fiche(etat, cle).get("credential") or {}).get("kind")
        == "secret",
        "exempt": _exempt_present(facts, o.exempt, True),
    }
    return o.sc.noter(
        nom, all(v for k, v in detail.items() if k != "refus"), detail
    )


def _phase_b(o):
    """B avec le module, que l'outil installe : coturn bascule en mode
    secret, redémarré une fois (MainPID changé) ; un utilisateur et un
    invité entré par un lien d'invitation allouent `turn:` et `turns:`."""
    avant = o.pid_coturn()
    res = o.ajouter("b", True)
    facts = o.sonde()
    _noter_module(o, "b-module", "b", res, facts)
    etat = facts.state if facts else {}
    o.pid = o.pid_coturn()
    detail = {
        "mode": etat.get("turn_mode") == "secret",
        "secret-de-controle": bool(etat.get("check_secret_sha256")),
        "use-auth-secret": mode_conf(facts) == "secret",
        "redemarre": _pid_valide(avant)
        and _pid_valide(o.pid)
        and avant != o.pid,
        "pid": [avant, o.pid],
    }
    o.sc.noter(
        "b-bascule", all(v for k, v in detail.items() if k != "pid"), detail
    )
    ice, lignes = o.par_odoo("b", etat)
    o.remis["b"] = ice
    o.noter_ice("b-utilisateur", lignes, ICE_SECRET)
    try:
        invitation = lien_invitation(o.harnais.lien("b"))
    except ol.OdooError as erreur:
        o.sc.noter("b-invite", False, {"invitation": erreur.key})
        return
    _ice, lignes = o.par_odoo("b", etat, invitation)
    o.noter_ice("b-invite", lignes, ICE_SECRET)


def _phase_c(o):
    """C avec le module sur le même coturn : aucun redémarrage (MainPID
    inchangé), B et C allouent chacun sous son secret ; puis la
    vérification du menu, ses lignes turn-* sous le secret de contrôle et
    odoo-1, odoo-2 sous celui de chaque Odoo."""
    res = o.ajouter("c", True)
    facts = o.sonde()
    _noter_module(o, "c-module", "c", res, facts)
    etat = facts.state if facts else {}
    pid = o.pid_coturn()
    o.sc.noter(
        "c-sans-redemarrage",
        _pid_valide(pid) and pid == o.pid,
        {"pid": [o.pid, pid]},
    )
    _ice_b, lignes_b = o.par_odoo("b", etat)
    o.remis["c"], lignes_c = o.par_odoo("c", etat)
    ok_b, detail_b = verdict_ice(lignes_b, ICE_SECRET)
    ok_c, detail_c = verdict_ice(lignes_c, ICE_SECRET)
    o.sc.noter("b-et-c", ok_b and ok_c, {"b": detail_b, "c": detail_c})


def _phase_rotation(o):
    """B ajouté de nouveau : un secret neuf, l'ancien gardé une durée de
    vie (`retired`), coturn jamais redémarré ; B alloue sous ses
    identifiants neufs, et ceux remis avant la rotation allouent encore."""
    cle = o.cle("b")
    avant = o.sonde()
    ancien = _empreinte(avant.state if avant else {}, cle)
    res = o.ajouter("b", True)
    facts = o.sonde()
    etat = facts.state if facts else {}
    neuf = _empreinte(etat, cle)
    gardes = [
        r.get("value_sha256") for r in _fiche(etat, cle).get("retired") or []
    ]
    pid = o.pid_coturn()
    _ice, lignes = o.par_odoo("b", etat)
    o.noter_ice(
        "b-rotation",
        lignes,
        ICE_SECRET,
        ajout=res["ok"],
        secret_neuf=bool(neuf) and neuf != ancien,
        ancien_garde=bool(ancien) and ancien in gardes,
        sans_redemarrage=_pid_valide(pid) and pid == o.pid,
    )
    o.noter_ice("b-grace", allouer(o.remis["b"], etat, o.cafile), ICE_SECRET)


def _phase_retrait_c(o):
    """C retiré : B alloue toujours (son secret reste dans `turn_secret`),
    C est révoqué sans grâce (ses identifiants → 401, son secret absent de
    la base de coturn), l'adresse exemptée que B partage reste."""
    cle_b, cle_c = o.cle("b"), o.cle("c")
    avant = o.sonde()
    secret_c = _empreinte(avant.state if avant else {}, cle_c)
    res = o.retirer("c")
    facts = o.sonde()
    etat = facts.state if facts else {}
    odoo = _faits_odoo(o.harnais.lien("c"))
    pid = o.pid_coturn()
    detail = {
        "retrait": res["ok"],
        "hors-etat": cle_c not in (etat.get("odoos") or {}),
        "sans-parametres": odoo is not None
        and ol.PARAM_SECRET not in odoo.params
        and ol.PARAM_URLS not in odoo.params,
        "exempt-garde": _exempt_present(facts, o.exempt, True),
        "sans-redemarrage": _pid_valide(pid) and pid == o.pid,
    }
    o.sc.noter("c-retire", all(detail.values()), detail)
    _ice, lignes = o.par_odoo("b", etat)
    o.noter_ice("b-reste", lignes, ICE_SECRET)
    _lignes, lus = verifier(o.cible, o.ip, o.cafile, o.sc.log)
    realm = getattr(ci.state_answers(etat), "public_name", None)
    presents = {
        hashlib.sha256(v.encode("utf-8")).hexdigest()
        for r, v in (lus or {}).get("turn_secrets") or []
        if r == realm
    }
    o.noter_ice(
        "c-revoque",
        allouer(o.remis["c"], etat, o.cafile),
        ICE_SECRET,
        True,
        secret_c_parti=bool(secret_c) and secret_c not in presents,
        secret_b_garde=_empreinte(etat, cle_b) in presents,
    )


def _phase_fin(o):
    """A sans le module de nouveau, B branché en mode secret : refusé pour
    le mode, rien n'a changé sur l'hôte. Puis B retiré (le module reste
    installé), la désinstallation, données comprises."""
    avant = o.sonde()
    res = o.ajouter("a", False)
    apres = o.sonde()
    odoo = _faits_odoo(o.harnais.lien("a"))
    detail = {
        "refus": res["refus"] == "call_infra_turn_mode_mismatch",
        "etat-inchange": bool(avant)
        and bool(apres)
        and avant.state == apres.state,
        "sans-lignes": odoo is not None
        and not _lignes_outil(odoo, o.cle("a")),
    }
    o.sc.noter("a-refuse", all(detail.values()), detail)
    res = o.retirer("b")
    facts = o.sonde()
    etat = facts.state if facts else {}
    odoo = _faits_odoo(o.harnais.lien("b"))
    detail = {
        "retrait": res["ok"],
        "aucun-odoo": not (etat.get("odoos") or {}),
        "module-garde": bool(odoo) and odoo.module_state == "installed",
        "sans-parametres": odoo is not None
        and ol.PARAM_SECRET not in odoo.params
        and ol.PARAM_URLS not in odoo.params,
        "exempt-retire": _exempt_present(facts, o.exempt, False),
    }
    o.sc.noter("b-retire", all(detail.values()), detail)
    o.sc.noter(
        "desinstallation", desinstaller(o.cible, True, o.sc.log) == "fait"
    )


def _parcours_odoo(sc, cible, ip, dossier, harnais):
    """coturn et ntfy de développement avec un certificat fourni pour
    l'adresse de la VM, puis les phases de `scenario_odoo`."""
    tls = local_cert.issue(os.path.join(dossier, "tls-odoo"), [ip])
    answers = reponses(ip, *paire(tls))
    res = installer(cible, answers, sc.log)
    if not sc.noter("installation", res["ok"], res["etape"] or None):
        return
    # La VM joint cette machine par son adresse sur le réseau de libvirt :
    # l'adresse que l'opérateur tape, la proposition du menu (la boucle
    # locale d'un Odoo du harnais) tombant.
    exempt = exempt_du_menu(harnais.url("a"), adresse_vers(ip))
    unite = res["etat"]["services"]["coturn"]["unit"]
    o = _Odoo(sc, cible, ip, harnais, tls["ca_crt"], exempt, unite)
    _phase_a(o)
    _phase_b(o)
    _phase_c(o)
    _verification(sc, cible, ip, o.cafile, nom="verification-secret")
    _phase_rotation(o)
    _phase_retrait_c(o)
    _phase_fin(o)


def scenario_odoo(sc, cible, ip, dossier):
    """Plusieurs serveurs Odoo sur un coturn, de bout en bout.

    1. A sans le module : mode fixe, trois lignes, `turn:` UDP et TCP
       alloués sous ce qu'Odoo remet ;
    2. A retiré : lignes parties, compte révoqué (401) ;
    3. B, le module installé par l'outil : coturn bascule en secret une
       fois, un utilisateur et un invité allouent `turn:` et `turns:` ;
    4. C sur le même coturn : aucun redémarrage, B et C allouent ;
    5. rotation de B : identifiants neufs, les anciens allouent encore ;
    6. C retiré : B alloue toujours, le secret de C a disparu ;
    7. A sans le module de nouveau : refusé pour le mode ;
    8. B retiré, désinstallation ; les bases du harnais supprimées dans
       tous les cas, même après un échec."""
    if not _preparer(sc, cible, "debian"):
        return
    harnais = Harnais(
        dossier, identifiant_de(sc.course), sc.course, sc.journal
    )
    try:
        ok, detail = harnais.preparer()
        if sc.noter("odoo-harnais", ok, detail):
            _parcours_odoo(sc, cible, ip, dossier, harnais)
    finally:
        restantes = harnais.defaire()
        sc.noter(
            "bases-supprimees",
            not restantes,
            {"restantes": restantes} if restantes else None,
        )


# --- Conteneurs ---------------------------------------------------------

# Les deux serveurs Odoo inventés de la course `conteneur` : aucun Odoo ne
# répond à ces adresses, seul le côté coturn de l'ajout est joué.
ODOO_INVENTES = (
    ("https://odoo-un.exemple.test", "base_un"),
    ("https://odoo-deux.exemple.test", "base_deux"),
)


def _etats(cible, etat, log, attente=0):
    """`etats_conteneurs` lus sur l'hôte, {} quand l'hôte n'a pas
    répondu."""
    code, sortie = distant(
        cible,
        script_conteneurs(etat, attente),
        log,
        DELAI_SCRIPT + 2 * attente,
    )
    return etats_conteneurs(sortie) if code == 0 else {}


def _pid_conteneur(cible, etat, log):
    """Le PID du conteneur de coturn vu de l'hôte, "" sans lui."""
    return _etats(cible, etat, log).get("coturn", {}).get("pid", "")


def odoo_invente(sc, cible, answers, etat, url, base, nom, bascule):
    """Le côté coturn de « Ajouter un serveur Odoo » pour la base inventée
    (`url`, `base`), noté `nom` ; rend (état écrit, ou `etat` quand rien
    ne s'est écrit ; secret posé).

    `odoo_add_script` pose un secret neuf dans la base de coturn, puis
    l'état de `odoo_added_state` est écrit, comme `apply_odoo_add` le fait
    après Odoo. Vert quand l'ajout et l'état sont écrits, qu'une
    allocation REST sous ce secret aboutit depuis cette machine vers le nom
    public (l'adresse de la VM en développement), et que le
    conteneur de coturn a été recréé une fois (`@@RECREATE 1`, date de
    démarrage changée) quand `bascule` (de comptes fixes au mode secret),
    pas du tout sinon (même date de démarrage)."""
    cle = ol.odoo_key(url, base)
    maintenant = datetime.datetime.now(datetime.timezone.utc)
    valeur = secrets.token_urlsafe(32)
    controle = secrets.token_urlsafe(32)
    avant = _etats(cible, etat, sc.log).get("coturn", {})
    code, sortie = distant(
        cible,
        ci.odoo_add_script(
            etat,
            cle,
            "secret",
            valeur,
            None,
            None,
            maintenant,
            check_secret=controle,
        ),
        sc.log,
        DELAI_INSTALL,
    )
    ajoute = code == 0 and ci.odoo_result(sortie)["ok"]
    recree = ("RECREATE", "1") in ci.marker_lines(sortie)
    final = ci.odoo_added_state(
        etat,
        cle,
        "secret",
        valeur,
        None,
        None,
        maintenant,
        check_secret=controle,
    )
    ecrit = False
    if ajoute:
        code, sortie = distant(
            cible,
            ci.state_write_script(final, pending_taken=False),
            sc.log,
            DELAI_SCRIPT,
        )
        ecrit = (
            code == 0 and dict(ci.marker_lines(sortie)).get("SAVED") == "yes"
        )
    apres = _etats(cible, etat, sc.log).get("coturn", {})
    user, password = turn_client.rest_credentials(
        valeur, UTILISATEUR_REST, int(time.time()) + 3600
    )
    rest = turn_client.allocate(
        answers.public_name,
        answers.turn_port,
        "udp",
        user,
        turn_client.long_term_key(user, answers.public_name, password),
        timeout=5,
    )
    debuts = [avant.get("demarre", ""), apres.get("demarre", "")]
    detail = {
        "ajout": ajoute,
        "etat": ecrit,
        "recree": recree,
        "demarre": debuts,
        "en-marche": apres.get("etat") == "running",
        "rest": "ok" if rest.ok else rest.error,
    }
    attendu = verdict_recreation(bascule, recree, debuts)
    ok = ajoute and ecrit and rest.ok and detail["en-marche"] and attendu
    sc.noter(nom, ok, detail)
    return (final if ecrit else etat), valeur


def verdict_recreation(bascule, recree, debuts):
    """Vert quand le conteneur de coturn a été recréé comme `bascule` le
    veut : recréé (`recree`, la ligne `@@RECREATE 1`) et deux dates de
    démarrage lues, différentes, pour une bascule ; ni l'un ni l'autre
    sinon, la même date lue avant et après. Le marqueur seul ne prouve
    rien : seule la date dit que le conteneur a vraiment redémarré."""
    meme = all(debuts) and debuts[0] == debuts[1]
    if bascule:
        return bool(recree and all(debuts) and not meme)
    return bool(not recree and meme)


def relais_prive(sc, answers, secret):
    """Une permission vers PRIVATE_PROBE_PEER, une adresse privée, depuis
    une allocation REST sous `secret` : le développement laisse coturn
    relayer vers le réseau local (aucune ligne `denied-peer-ip`), ce que
    les plages refusées par défaut de coturn 4.18 ne doivent pas
    défaire."""
    user, password = turn_client.rest_credentials(
        secret, UTILISATEUR_REST, int(time.time()) + 3600
    )
    resultat = turn_client.permission(
        answers.public_name,
        answers.turn_port,
        "udp",
        user,
        turn_client.long_term_key(user, answers.public_name, password),
        ci.PRIVATE_PROBE_PEER,
        timeout=5,
    )
    return sc.noter(
        "relais-prive",
        resultat.ok,
        {
            "pair": ci.PRIVATE_PROBE_PEER,
            "resultat": "ok" if resultat.ok else resultat.error,
        },
    )


def redemarrage(sc, cible, etat):
    """La VM redémarrée (`SCRIPT_REDEMARRER`), puis jugée par
    `verdict_redemarrage` : nouveau démarrage, conteneurs relancés par
    l'unité que l'installation a activée (et, en rootless, la session
    permanente du compte)."""
    code, sortie = distant(cible, SCRIPT_DEMARRAGE, sc.log, DELAI_SCRIPT)
    avant = dict(ci.marker_lines(sortie)).get("BOOT", "").strip()
    code, sortie = distant(cible, SCRIPT_REDEMARRER, sc.log, DELAI_SCRIPT)
    programme = ("REBOOT", "scheduled") in ci.marker_lines(sortie)
    time.sleep(DELAI_REDEMARRAGE)
    joignable = attendre_ssh(cible, sc.journal)
    code, sortie = distant(cible, SCRIPT_DEMARRAGE, sc.log, DELAI_SCRIPT)
    apres = dict(ci.marker_lines(sortie)).get("BOOT", "").strip()
    etats = _etats(cible, etat, sc.log, DELAI_CONTENEURS)
    code, auto = distant(cible, script_auto(etat), sc.log, DELAI_SCRIPT)
    ok, detail = verdict_redemarrage(avant, apres, etats, auto)
    detail.update(programme=programme, joignable=joignable)
    return sc.noter("redemarrage", programme and joignable and ok, detail)


def desinstallation_conteneur(sc, cible, ip, answers, etat, prefixe=""):
    """La désinstallation du menu, données et ajouts pour le moteur
    compris (le oui aux deux questions), puis l'hôte jugé par
    `verdict_apres_conteneur` et les ports de `answers` vus d'ici. Les
    étapes portent `prefixe` (« prod- » pour la production)."""
    sc.noter(
        f"{prefixe}desinstallation",
        desinstaller(cible, True, sc.log, moteur=True) == "fait",
    )
    paquets = etat["container"].get("engine_packages_added") or []
    code, sortie = distant(
        cible, script_apres_conteneur(paquets), sc.log, DELAI_SCRIPT
    )
    ok, detail = verdict_apres_conteneur(code, sortie)
    sc.noter(f"{prefixe}etat-apres-desinstallation", ok, detail)
    tcp = [answers.turn_port]
    if ci.has_tls(answers):
        tcp.append(ci.coturn_tls_port(answers))
    if "ntfy" in answers.services:
        tcp.append(ci.ntfy_port(answers))
    ports = ports_fermes(ip, tcp=tuple(tcp), udp=(answers.turn_port,))
    sc.noter(f"{prefixe}ports-fermes", all(ports.values()), ports)


def production_conteneur(sc, cible, ip, dossier):
    """coturn seul en production dans un conteneur Podman en root, après
    le développement, sur la même VM : un certificat fourni d'une autorité
    inventée, TURN sur TLS en 443. Le moteur, retiré par la désinstallation
    du développement, est proposé de nouveau. 443 doit être tenu par
    turnserver sous un uid non root ; la vérification de production (relais
    refusé vers une adresse privée compris), puis la désinstallation."""
    chemins = local_cert.issue(
        os.path.join(dossier, f"tls-prod-{sc.variante}"), noms_certificat(ip)
    )
    certificat = paire(chemins)

    def reponses_de(facts):
        base = reponses_prod_coturn(ip, *certificat, facts)
        return methode_du_menu(base, facts, "container", sc.variante)

    res = installer(cible, reponses_de, sc.log)
    if res["limite"]:
        sc.limite_atteinte("prod-installation")
        return
    if not sc.noter("prod-installation", res["ok"], res["etape"] or None):
        return
    answers, etat = res["answers"], res["etat"]
    code, sortie = distant(
        cible,
        script_port_bas(ci.coturn_tls_port(answers)),
        sc.log,
        DELAI_SCRIPT,
    )
    ok, detail = verdict_port_bas(sortie)
    sc.noter("prod-443-non-root", code == 0 and ok, detail)
    _verification(
        sc,
        cible,
        ip,
        chemins["ca_crt"],
        nom="prod-verification",
        requis=CONTROLES_PROD_COTURN,
    )
    desinstallation_conteneur(sc, cible, ip, answers, etat, prefixe="prod-")


def scenario_conteneur(sc, cible, ip, dossier):
    """coturn et ntfy de développement en conteneurs, sous le moteur de la
    course (`sc.variante`, une clé de MOTEURS), sur une Debian neuve.

    1. le moteur absent : le menu propose ses paquets (`engine_offer`),
       accepté ; l'installation les consigne dans l'état
       (`@@ENGINE_PACKAGE`) ;
    2. la vérification du menu (allocations TURN udp, tcp et TLS, santé de
       ntfy, conteneurs sous l'uid de l'état), puis chaque base appartient
       au compte de l'état, jamais à un uid subordonné ;
    3. Docker : le rejeu du mélange en information, coturn encore en
       comptes fixes ;
    4. un premier Odoo inventé fait basculer coturn en mode secret : une
       recréation, une allocation sous son secret ; un second ne recrée
       rien ; sous le premier secret, le relais vers une adresse privée est
       accordé, comme le développement le veut ;
    5. le crochet lancé à la main : SIGUSR2 au conteneur, même PID, le
       nouveau certificat servi ;
    6. la VM redémarrée : les conteneurs reviennent ;
    7. la relance ne change rien ; la désinstallation emporte tout, moteur
       compris, et ferme les ports ;
    8. Podman en root : coturn seul en production sur 443
       (`production_conteneur`)."""
    if not _preparer(sc, cible, "debian"):
        return
    moteur = sc.variante
    dossier_tls = os.path.join(dossier, f"tls-{moteur}")
    tls = local_cert.issue(dossier_tls, [ip])
    premier = paire(tls)
    second = paire(local_cert.issue(dossier_tls, [ip]))
    cafile = tls["ca_crt"]
    base = reponses(ip, *premier)
    vu = {}

    def reponses_de(facts):
        return methode_du_menu(base, facts, "container", moteur, vu)

    res = installer(cible, reponses_de, sc.log)
    offre = list(vu.get("offre", ()))
    sc.noter("moteur-propose", bool(offre), {"paquets": offre})
    if res["limite"]:
        sc.limite_atteinte("installation")
        return
    if not sc.noter("installation", res["ok"], res["etape"] or None):
        return
    answers, etat = res["answers"], res["etat"]
    ajoutes = etat["container"].get("engine_packages_added") or []
    sc.noter(
        "moteur-installe",
        verdict_moteur_installe(offre, ajoutes),
        {"proposes": offre, "consignes": ajoutes},
    )
    _verification(sc, cible, ip, cafile)
    code, sortie = distant(cible, script_proprietaires(), sc.log, DELAI_SCRIPT)
    ok, detail = verdict_proprietaires(etat, sortie)
    sc.noter("proprietaires", code == 0 and ok, detail)
    if moteur == "docker":
        _melange(sc, cible, ip, cafile, answers, etat)
    poses = []
    for (url, nom_base), (etape, bascule) in zip(
        ODOO_INVENTES, (("odoo-secret", True), ("odoo-second", False))
    ):
        etat, secret = odoo_invente(
            sc, cible, answers, etat, url, nom_base, etape, bascule
        )
        poses.append(secret)
    relais_prive(sc, answers, poses[0])
    crochets(
        sc,
        cible,
        ip,
        answers,
        cc.CONTAINERS["coturn"],
        premier,
        second,
        executer=distant,
        lire_pid=lambda: _pid_conteneur(cible, etat, sc.log),
        nginx=False,
    )
    redemarrage(sc, cible, etat)
    _verification(sc, cible, ip, cafile, nom="verification-apres-redemarrage")
    again = installer(cible, reponses_de, sc.log)
    sc.noter("rien-a-changer", again["ok"] and again["rien_a_faire"])
    relance_up(sc, cible, etat, reponses_de)
    desinstallation_conteneur(sc, cible, ip, answers, etat)
    sc.noter(
        "desinstallation-vide", desinstaller(cible, True, sc.log) == "rien"
    )
    if moteur == "podman":
        production_conteneur(sc, cible, ip, dossier)


# --- Migration ----------------------------------------------------------


def verdict_relance_up(arret, res, apres):
    """Vert quand le conteneur de ntfy a été arrêté (`arret`, le code du
    script), que la relance qui suit a tourné (`res`, le résultat
    d'`installer`, pas « rien à changer » : le conteneur arrêté demande un
    passage) et que ntfy tourne de nouveau (`apres`, son état lu)."""
    return bool(
        arret == 0
        and res["ok"]
        and not res["rien_a_faire"]
        and apres.get("etat") == "running"
    )


def relance_up(sc, cible, etat, reponses_de):
    """Le conteneur de ntfy arrêté par le moteur de l'état, puis
    l'installation relancée avec les mêmes réponses : le script passe par
    `up -d` sur des conteneurs déjà là, ce que podman-compose traduit par
    `podman run`, refusé pour un nom pris, puis `podman start`. ntfy doit
    tourner de nouveau."""
    arret = f"{_eng(etat)}\neng stop {cc.CONTAINERS['ntfy']}"
    code, _sortie = distant(cible, arret, sc.log, DELAI_SCRIPT)
    res = installer(cible, reponses_de, sc.log)
    apres = _etats(cible, etat, sc.log, attente=10).get("ntfy", {})
    sc.noter(
        "relance-up",
        verdict_relance_up(code, res, apres),
        {
            "arret": code,
            "installation": res["etape"] or res["ok"],
            "rien-a-faire": res["rien_a_faire"],
            "ntfy": apres.get("etat"),
        },
    )


def verdict_moteur_installe(offre, ajoutes):
    """Vert quand des paquets du moteur ont été proposés et que chacun est
    consigné dans l'état (`engine_packages_added`) : la désinstallation ne
    retire que ceux-là."""
    return bool(offre) and set(offre) <= set(ajoutes)


def verdict_secrets(avant, apres):
    """Vert quand des lignes `turn_secret` ont été lues avant la migration
    et que les mêmes le sont après : deux lectures vides ne prouvent rien."""
    return bool(avant) and avant == apres


def verdict_telephone(telephone, telephones):
    """Vert quand le téléphone inscrit avant la migration figure dans la
    liste des comptes de ntfy lue après."""
    return telephone is not None and telephone in (telephones or ())


def verdict_retour(ancien, res):
    """Vert pour le retour aux paquets : refusé par
    `call_infra_ntfy_downgrade` quand l'hôte porte un ntfy plus ancien que
    l'image (`ancien`), migré (`to_packages`, `@@MIGRATION done`) sinon.
    `res` : le résultat d'`installer`."""
    if ancien:
        return not res["ok"] and res["refus"] == "call_infra_ntfy_downgrade"
    plan = res["plan"]
    return bool(
        res["ok"]
        and plan is not None
        and plan.migration == "to_packages"
        and res["migration"] == "done"
    )


def secrets_turn(lus):
    """Les empreintes sha256 des lignes `turn_secret` (realm, secret) que
    la vérification a lues : la base se compare sans qu'aucun secret ne
    quitte la mémoire."""
    return {
        hashlib.sha256(f"{r}\0{v}".encode("utf-8")).hexdigest()
        for r, v in (lus or {}).get("turn_secrets") or []
    }


def _proprietaire_ntfy(cible, log):
    """Le compte qui possède la base des comptes de ntfy, d'après
    `inspect_script` ; « ntfy » quand rien ne se lit."""
    code, sortie = distant(
        cible, nm.inspect_script(ci.NTFY_CONFIG), log, DELAI_SCRIPT
    )
    proprietaire = nm.parse_markers(sortie).get("OWNER", "").strip()
    return "ntfy" if code != 0 or proprietaire in ("", "?") else proprietaire


def semer_telephone(sc, cible, etat, proprietaire):
    """Un compte de téléphone ouvert par `access_script`, sous la CLI du
    ntfy de `etat` (`ci.ntfy_cli`) ; rend son nom, None en échec."""
    cli = ci.ntfy_cli(etat, proprietaire)
    telephone = nm.phone_user(LIBELLE_TELEPHONE)
    code, sortie = distant(
        cible,
        nm.access_script(
            ci.NTFY_CONFIG, telephone, nm.random_prefix(), cli=cli.prefix
        ),
        sc.log,
        DELAI_SCRIPT,
        root=cli.sudo_user is None,
        utilisateur=cli.sudo_user,
    )
    ok = code == 0 and bool(nm.parse_token(sortie))
    return telephone if sc.noter("telephone-seme", ok) else None


def _noter_ice(sc, nom, harnais, etat, cafile):
    _ice, lignes = par_odoo(harnais, "a", etat, cafile)
    ok, detail = verdict_ice(lignes, ICE_SECRET)
    return sc.noter(nom, ok, detail)


def _parcours_migration(sc, cible, ip, dossier, harnais):
    """Les étapes de `scenario_migration` une fois le harnais debout."""
    tls = local_cert.issue(os.path.join(dossier, "tls-migration"), [ip])
    base = reponses(ip, *paire(tls))
    cafile = tls["ca_crt"]
    res = installer(cible, base, sc.log)
    if not sc.noter("installation", res["ok"], res["etape"] or None):
        return
    etat = res["etat"]
    proprietaire = _proprietaire_ntfy(cible, sc.log)
    telephone = semer_telephone(sc, cible, etat, proprietaire)
    exempt = exempt_du_menu(harnais.url("a"), adresse_vers(ip))
    ajout = ajouter_odoo(
        cible,
        harnais.lien("a"),
        harnais.url("a"),
        harnais.bases["a"],
        True,
        exempt,
        sc.log,
    )
    etat = ajout["etat"] or etat
    if not sc.noter(
        "odoo-branche",
        ajout["ok"] and etat.get("turn_mode") == "secret",
        {"refus": ajout["refus"]},
    ):
        return
    _noter_ice(sc, "odoo-relaie", harnais, etat, cafile)
    _lignes, lus = verifier(cible, ip, cafile, sc.log)
    avant = secrets_turn(lus)

    vu = {}
    res = installer(
        cible,
        lambda facts: methode_du_menu(
            base, facts, "container", MOTEUR_MIGRATION, vu
        ),
        sc.log,
    )
    if res["limite"]:
        sc.limite_atteinte("migration-conteneurs")
        return
    plan = res["plan"]
    detail = {
        "etape": res["etape"],
        "refus": res["refus"],
        "migration": res["migration"],
        "sens": plan.migration if plan else None,
        "odoo_readd": list(plan.odoo_readd) if plan else None,
        "paquets": list(vu.get("offre", ())),
    }
    if not sc.noter(
        "migration-conteneurs",
        res["ok"]
        and plan.migration == "to_container"
        and res["migration"] == "done"
        and plan.odoo_readd == (),
        detail,
    ):
        return
    etat = res["etat"]
    lignes, lus = verifier(cible, ip, cafile, sc.log)
    apres = secrets_turn(lus)
    sc.noter(
        "secrets-identiques",
        verdict_secrets(avant, apres),
        {"avant": len(avant), "apres": len(apres)},
    )
    vert, problemes = verdict_controle(
        lignes, CONTROLES[sc.scenario][sc.distro]
    )
    sc.noter(
        "verification-conteneurs",
        vert,
        {"problemes": problemes, "lignes": _lignes_en_dict(lignes)},
    )
    _noter_ice(sc, "odoo-relaie-conteneurs", harnais, etat, cafile)
    sc.noter(
        "telephone-garde",
        verdict_telephone(
            telephone, _telephones(cible, sc.log, proprietaire, etat)
        ),
    )

    facts = _sonde(cible, sc.log, distant)
    hote = facts.engines.ntfy_host_version if facts and facts.engines else None
    ancien = bool(hote) and cc.version_older(hote, cc.IMAGE_VERSIONS["ntfy"])
    res = installer(
        cible, lambda f: methode_du_menu(base, f, "packages"), sc.log
    )
    sc.noter(
        "retour-paquets",
        verdict_retour(ancien, res),
        {
            "ntfy-hote": hote,
            "plus-ancien": ancien,
            "refus": res["refus"],
            "migration": res["migration"],
        },
    )
    if res["ok"]:
        etat = res["etat"]
    _noter_ice(sc, "odoo-relaie-retour", harnais, etat, cafile)
    retrait = retirer_odoo(
        cible,
        harnais.lien("a"),
        ol.odoo_key(harnais.url("a"), harnais.bases["a"]),
        sc.log,
    )
    sc.noter("odoo-retire", retrait["ok"], {"refus": retrait["refus"]})
    sc.noter(
        "desinstallation",
        desinstaller(cible, True, sc.log, moteur=True) == "fait",
    )


def scenario_migration(sc, cible, ip, dossier):
    """Paquets ↔ conteneurs avec un Odoo branché, sur une Debian neuve.

    1. coturn et ntfy de développement par paquets, un certificat fourni ;
       un téléphone ; un Odoo 18 de cette machine (une base,
       `identifiant_migration`) branché avec `erplibre_turn`, qui relaie ;
    2. passage aux conteneurs Podman en root : aucun Odoo à rebrancher
       (`odoo_readd` vide), les lignes `turn_secret` identiques, la
       vérification verte, l'Odoo relaie encore par sa propre liste ICE, le
       téléphone toujours listé par la CLI du conteneur ;
    3. retour aux paquets : fait quand l'hôte n'a pas de ntfy plus ancien
       que l'image, sinon refusé (`call_infra_ntfy_downgrade`) ; l'Odoo
       relaie toujours ;
    4. l'Odoo retiré, la désinstallation ; la base supprimée dans tous les
       cas, même après un échec."""
    if not _preparer(sc, cible, "debian"):
        return
    harnais = Harnais(
        dossier,
        identifiant_migration(sc.course),
        sc.course,
        sc.journal,
        lettres=("a",),
    )
    try:
        ok, detail = harnais.preparer()
        if sc.noter("odoo-harnais", ok, detail):
            _parcours_migration(sc, cible, ip, dossier, harnais)
    finally:
        restantes = harnais.defaire()
        sc.noter(
            "bases-supprimees",
            not restantes,
            {"restantes": restantes} if restantes else None,
        )


SCENARIOS = {
    "dev": {"debian": scenario_debian, "arch": scenario_arch},
    "prod": {"debian": scenario_prod, "arch": scenario_prod},
    "odoo": {"debian": scenario_odoo},
    "conteneur": {"debian": scenario_conteneur},
    "migration": {"debian": scenario_migration},
}


# --- Course -------------------------------------------------------------


class Course:
    """Le rapport, réécrit à chaque changement. Sa forme est le CONTRAT du
    défaire partagé (descente.py) : « outil » filtre les rapports, « pid »
    empêche de détruire sous une course vivante, « etages » porte une
    entrée de niveau 1 par VM encore debout. « systemes » est à ce test, et
    « odoo » aussi : les bases du harnais encore à supprimer
    (`defaire_odoo`). `identifiant` (`<pid>_<horodatage>`) nomme ces
    bases."""

    def __init__(self, dry_run, journal):
        self.journal = journal
        self.dossier = journal[:-4]
        self.chemin = self.dossier + ("-dryrun.json" if dry_run else ".json")
        self.identifiant = f"{os.getpid()}_{time.strftime('%Y%m%d%H%M%S')}"
        self.rapport = {
            "outil": OUTIL,
            "dry_run": dry_run,
            "pid": os.getpid(),
            "etages": [],
            "systemes": [],
        }

    def ecrire(self):
        with open(self.chemin, "w", encoding="utf-8") as fh:
            json.dump(self.rapport, fh, indent=2)

    def inscrire(self, etage):
        """Écrit l'étage AVANT la suite : une course qui meurt laisse de
        quoi défaire sa VM."""
        self.rapport["etages"].append(etage)
        self.ecrire()

    def retirer(self, etage):
        self.rapport["etages"].remove(etage)
        self.ecrire()

    def noter(self, ligne):
        self.rapport["systemes"].append(ligne)
        self.ecrire()

    def noter_base(self, base):
        """Écrit la base AVANT sa création, comme `inscrire` une VM."""
        bloc = self.rapport.setdefault("odoo", {"bases": []})
        bloc["bases"].append(base)
        self.ecrire()

    def oublier_odoo(self):
        """Les bases supprimées : plus rien à défaire hors des VM."""
        self.rapport["odoo"] = {"bases": []}
        self.ecrire()


def libelle(scenario, variante=None):
    """« scénario » ou « scénario variante », pour l'écran ; « scénario-
    variante » sert au nom du journal."""
    return f"{scenario} {variante}" if variante else scenario


def mener_un(course, distro, scenario, variante=None):
    """Un système dans un scénario (et sa variante, le moteur d'une course
    `conteneur`), de sa VM à son verdict ; la VM reste au rapport."""
    suffixe = f"-{variante}" if variante else ""
    log = os.path.join(course.dossier, f"{scenario}{suffixe}-{distro}.log")
    sc = Scenario(
        distro, log, course.journal, scenario, course=course, variante=variante
    )
    nom = nom_vm(distro)
    dire(
        f"  ── {distro} {DISTROS[distro]} ({libelle(scenario, variante)})"
        f" : {nom}",
        course.journal,
    )
    nom, uuid, ok = creer_vm(nom, distro, course.journal, False)
    if nom:
        course.inscrire(
            {"niveau": 1, "nom": nom, "uuid": uuid, "alias": nom, "cree": True}
        )
    if not sc.noter("vm", ok):
        return sc.ligne()
    ip = adresse_de(nom, course.journal)
    if not sc.noter("ssh", bool(ip) and attendre_ssh(nom, course.journal)):
        return sc.ligne()
    try:
        SCENARIOS[scenario][distro](sc, nom, ip, course.dossier)
    except Exception as souci:  # noqa: BLE001 - un système, pas la course
        sc.noter("exception", False, repr(souci))
    return sc.ligne()


def defaire_vm(course):
    """Détruit les VM encore au rapport ; rend vrai quand il n'en reste
    aucune. Jamais detruire() en cours de course : il demande « OUI »."""
    for etage in list(course.rapport["etages"]):
        if detruire_etage1(
            course.journal, etage["nom"], attendu=etage["uuid"] or None
        ):
            retirer_alias({"etages": [etage]}, course.journal, NOM_BASE)
            course.retirer(etage)
    return not course.rapport["etages"]


def mener(argv):
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument(
        "--distro", choices=(*DISTROS, "tous"), default="tous"
    )
    parseur.add_argument(
        "--scenario", choices=(*SCENARIOS_NOMS, "tous"), default="tous"
    )
    parseur.add_argument(
        "--moteur",
        choices=(*MOTEURS, "tous"),
        default="tous",
        help="le moteur des courses conteneur (les trois par défaut)",
    )
    parseur.add_argument("--dry-run", action="store_true")
    parseur.add_argument(
        "--garder", action="store_true", help="garder chaque VM"
    )
    parseur.add_argument("--detruire", action="store_true")
    args = parseur.parse_args(argv)

    journal = os.path.expanduser(
        f"~/.erplibre/longtest/{NOM_BASE}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    )
    os.makedirs(os.path.dirname(journal), exist_ok=True)

    # `detruire_une` défait une VM IMBRIQUÉE chez son parent ; ce test n'en
    # crée aucune, le défaire partagé ne l'appelle donc jamais. Elle le dit
    # plutôt que d'être None.
    def pas_d_imbrique(parent_alias, identite, nom, log=None):
        dire(f"      ✗ {nom} : ce test ne crée pas de VM imbriquée", log)
        return False

    if args.detruire:
        # Les bases et serveurs Odoo ne vivent pas dans les VM et le défaire
        # partagé ne les connaît pas : il les confie à `avant`, sous ses
        # garde-fous (aucune descente en cours, la confirmation), avant la
        # première VM. Sans rapport qui nomme une VM, le défaire partagé
        # s'arrête avant `avant` : `detruire_bases` reprend alors ces
        # garde-fous pour les bases seules.
        if not dernier_rapport(OUTIL, NOM_BASE):
            return detruire_bases(journal, args.dry_run)
        famille = Famille(OUTIL, NOM_BASE, pas_d_imbrique)
        return detruire(
            famille,
            journal,
            dry_run=args.dry_run,
            avant=lambda a_blanc: defaire_odoo(journal, a_blanc),
        )

    systemes = list(DISTROS) if args.distro == "tous" else [args.distro]
    scenarios = (
        list(SCENARIOS_NOMS) if args.scenario == "tous" else [args.scenario]
    )
    if args.moteur != "tous" and "conteneur" not in scenarios:
        dire(
            f"  ✗ --moteur ne sert qu'au scénario conteneur, pas à"
            f" --scenario {args.scenario}",
            journal,
        )
        return 1
    moteurs = list(MOTEURS) if args.moteur == "tous" else [args.moteur]
    # Les scénarios d'un système, l'un après l'autre, chacun sur sa VM ;
    # seulement ceux qui tournent sur ce système (odoo, conteneur,
    # migration : Debian), et une course par moteur pour `conteneur`.
    courses = [
        (d, s, v)
        for d in systemes
        for s in scenarios
        if d in SCENARIOS[s]
        for v in (moteurs if s == "conteneur" else [None])
    ]
    if not courses:
        dire(
            f"  ✗ --scenario {args.scenario} ne tourne pas sur"
            f" {args.distro} : seulement sur"
            f" {', '.join(SCENARIOS[args.scenario])}",
            journal,
        )
        return 1
    # Les courses d'un système prennent le même nom de VM : la première
    # gardée ferait refuser la suivante.
    par_systeme = [d for d, _s, _v in courses]
    if args.garder and len(par_systeme) != len(set(par_systeme)):
        dire(
            "  ✗ --garder garde une VM par système : choisir --scenario dev,"
            " --scenario prod, --scenario odoo, --scenario migration, ou"
            " --scenario conteneur avec un --moteur",
            journal,
        )
        return 1
    course = Course(args.dry_run, journal)
    dire(f"  journal : {journal}", journal)
    if args.dry_run:
        dire("  --dry-run : rien ne sera créé.", journal)
        for distro, scenario, variante in courses:
            dire(
                f"  ── {distro} {DISTROS[distro]}"
                f" ({libelle(scenario, variante)})",
                journal,
            )
            creer_vm(nom_vm(distro), distro, journal, True)
            dire(
                "      étapes : "
                + ", ".join(etapes_de(scenario, distro, variante)),
                journal,
            )
            if scenario == "odoo":
                bases = noms_bases(course.identifiant).values()
                dire(f"      bases : {', '.join(bases)}", journal)
            if scenario == "migration":
                base = noms_bases(identifiant_migration(course))["a"]
                dire(f"      bases : {base}", journal)
        course.ecrire()
        dire(f"  rapport : {course.chemin}", journal)
        return 0

    # `--garder` laisse chaque VM debout jusqu'à la fin de la course : la
    # place se compte pour toutes. Sans lui, une VM est défaite avant la
    # suivante, et une survivante arrête la course plus bas.
    if not plan_tient(journal, len(courses) if args.garder else 1):
        return 1
    os.makedirs(course.dossier, exist_ok=True)
    course.ecrire()
    dire(f"  rapport : {course.chemin}", journal)
    for distro, scenario, variante in courses:
        ligne = mener_un(course, distro, scenario, variante)
        course.noter(ligne)
        verdict = ligne["verdict"]
        marque = {"OK": "✅", LIMITE_REGISTRE: "⏳"}.get(verdict, "❌")
        suite = f" — {MESSAGE_LIMITE}" if verdict == LIMITE_REGISTRE else ""
        dire(
            f"  {marque} {distro} ({libelle(scenario, variante)}) :"
            f" {verdict}{suite}",
            journal,
        )
        if args.garder:
            continue
        # Une VM encore en vie arrête la course : sans `--garder`,
        # plan_tient n'a compté la place que d'une seule.
        if not defaire_vm(course):
            dire(
                "  ✗ VM toujours en vie : la course s'arrête,"
                " --detruire la défait",
                journal,
            )
            break
    if course.rapport["etages"]:
        dire(
            f"  {len(course.rapport['etages'])} VM gardée(s) :"
            " --detruire les défait",
            journal,
        )
    return bilan(course.rapport["systemes"], len(courses), journal)


def bilan(vus, attendues, journal):
    """Le code de sortie de la course : 0 quand les `attendues` courses
    ont toutes tourné et sont vertes ; 2 quand celles qui ne le sont pas
    ont toutes été arrêtées par la limite du registre (à relancer plus
    tard) ; 1 sinon, une course manquante comprise."""
    verdicts = [ligne["verdict"] for ligne in vus]
    if len(verdicts) == attendues and all(v == "OK" for v in verdicts):
        dire("  ✅ infrastructure d'appel", journal)
        return 0
    if len(verdicts) == attendues and all(
        v in ("OK", LIMITE_REGISTRE) for v in verdicts
    ):
        dire(f"  ⏳ infrastructure d'appel : {MESSAGE_LIMITE}", journal)
        return 2
    dire("  ❌ infrastructure d'appel", journal)
    return 1


if __name__ == "__main__":
    sys.exit(mener(sys.argv[1:]))
