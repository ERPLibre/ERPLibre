#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Installation hors ligne sur l'ISO live : le paquet de la partition de
données de la clé (LABEL=ERPLIBRE_DATA) remplace le réseau.

Le paquet, à la racine de la partition :

  manifest.json   ce qui suit, avec l'empreinte des petites pièces
  repo/           dépôt pacman : <dépôt>/os/<arch>/<dépôt>.db + paquets
  store/          magasin du mandataire Go (script/qemu_cache), miroirs
                  git compris sous store/git/
  bin/            le mandataire, compilé statique
  ca/             l'autorité propre au paquet (ca.crt, ca.key)

Mise en service (start) :

- l'horloge du live est avancée à la création du paquet si elle est en
  retard (clock_floor) : l'autorité et les signatures de l'instantané
  seraient sinon « pas encore valides » ;
- le trousseau pacman est initialisé : pacman-init (releng) attend
  time-sync.target, que systemd-time-wait-sync ne rend jamais sans
  réseau ; sans trousseau, pacman refuse chaque signature de paquet.
  L'attente de l'heure est donc levée, comme archinstall --skip-ntp le
  fait pour lui-même ;
- la partition est montée en LECTURE SEULE (ro, nodev, nosuid, noexec) ;
- le mandataire et l'autorité sont copiés sur /run, empreintes vérifiées,
  et le mandataire tourne en mode --hors-ligne sur 127.0.0.1, sous un UID
  sans compte (PROXY_UID) : il sert le magasin et le dépôt pacman local
  pour tout miroir Arch, n'écrit rien et ne joint jamais l'amont ;
- dnsmasq répond FAKE_ADDR à tout nom, et systemd-resolved l'interroge
  seul ; FAKE_ADDR est posée sur une interface factice (DUMMY_LINK) qui
  porte aussi une route par défaut. Sans route, connect() échoue
  (ENETUNREACH) avant d'atteindre la règle nft, et systemd-resolved, qui
  ne voit alors aucun lien routable, répond « Network is down » au lieu
  d'interroger son serveur ;
- nft détourne la sortie TCP 80/443 de tout processus, sauf le
  mandataire, vers ses ports ; l'IPv6 vers 80/443 est refusée pour que
  les clients retombent aussitôt sur l'IPv4 détournée ;
- l'autorité est approuvée par le live (ancre + trust extract-compat) ;
- la liste de miroirs du live reçoit un serveur si elle n'en a aucun :
  pacstrap la recopie dans la cible, qui garde ainsi un vrai miroir ;
- un essai demande la base « core » par tout le chemin, puis le
  trousseau du live est mis à jour depuis le dépôt du paquet s'il y est
  plus récent (keyring_argvs) : il remplace la synchronisation WKD
  qu'archinstall --skip-wkd saute.

Le chroot d'archinstall partage le réseau du live : nft, le DNS et le
mandataire le servent aussi. La confiance DANS la cible est l'affaire de
l'étape ERPLibre (erplibre-stage.sh), qui la retire à la fin ;
clean_target() régénère ensuite le faisceau de la cible et y cherche
l'autorité elle-même, pas seulement son ancre.

Mode enregistrement (manifeste « mode »: « record ») : la fabrique du
paquet (offline_payload.py, sur l'hôte) branche une partition de données
qui ne porte que son manifeste et le certificat de son autorité, et fait
tourner le mandataire SUR L'HÔTE, joint par la passerelle du réseau de la
VM. Le live garde son vrai réseau et son DNS ; nft envoie (dnat) la sortie
80/443 vers ce mandataire, qui remplit le magasin du futur paquet en
joignant l'amont. L'autorité est approuvée et retirée comme hors ligne :
l'installation de référence suit ainsi le même chemin que celle qu'elle
prépare, et tire donc les mêmes fichiers.

Chaque geste de start() a son inverse, noté dans STATE_FILE au moment où
il réussit : stop() défait exactement ce qui a été fait, même après un
start() interrompu, et un échec de start() défait tout avant de rendre la
main.

Bibliothèque standard seulement. Les constructeurs (règles nft,
configuration DNS, liste de miroirs, plans, argv, validation du
manifeste, index des bases pacman) sont purs ; l'exécution prend un
`run` injecté.
"""

import base64
import binascii
import datetime
import hashlib
import http.client
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

DATA_LABEL = "ERPLIBRE_DATA"
MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA = 1
ARCH = "x86_64"
# Valeur de « mode » d'un manifeste d'enregistrement ; absent, le paquet
# sert hors ligne.
MODE_RECORD = "record"

RUN_DIR = "/run/erplibre-offline"
STATE_NAME = "state.json"
DATA_DIRNAME = "data"
PROXY_NAME = "erplibre_go_qemu_cache"

# UID du mandataire, porté par le compte système PROXY_USER que le live
# crée au démarrage (usr/lib/sysusers.d/erplibre-offline.conf) : systemd
# refuse un User= numérique sans compte. La règle nft l'exempte du
# détournement ; il est pris sous 61184, où commencent les UID dynamiques
# de systemd, et au-dessus de 60000, la limite des comptes ordinaires de
# login.defs.
PROXY_UID = 60917
PROXY_USER = "erplibre-offline"
HTTP_PORT = 8898
TLS_PORT = 8899
LISTEN_ADDR = "127.0.0.1"
DNS_ADDR = "127.0.0.1"
# Plage réservée aux mesures de banc (RFC 2544), jamais routée sur
# Internet : une adresse qui ne peut rien désigner d'autre que ce live.
FAKE_ADDR = "198.18.0.1"
FAKE_PREFIX = 24
DUMMY_LINK = "erplibre-off"
# Métrique haute : une vraie route par défaut, s'il y en a une, passe
# avant celle de l'interface factice.
DUMMY_METRIC = 4000

PROXY_UNIT = "erplibre-offline-proxy"
DNS_UNIT = "erplibre-offline-dns"
NFT_TABLE = "erplibre_offline"
NFT_FAMILY = "inet"

ANCHOR_NAME = "erplibre-offline.crt"
ANCHOR_DIR = "/etc/ca-certificates/trust-source/anchors"
SYSTEM_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
# Les faisceaux que trust extract-compat écrit dans la cible, relatifs à
# sa racine : PEM, OpenSSL, Java et un fichier par autorité (cadir).
# /etc/ssl/certs n'en porte que des liens, qui ne sont pas suivis : un
# lien absolu, lu depuis le live, désignerait le faisceau du live.
TARGET_BUNDLE_DIRS = ("etc/ca-certificates/extracted", "etc/ssl/certs")
TARGET_TRUST = "usr/bin/trust"
RESOLVED_DROPIN = "/run/systemd/resolved.conf.d/erplibre-offline.conf"
MIRRORLIST = "/etc/pacman.d/mirrorlist"
# Le miroir de l'archive officielle, qui redirige vers un miroir proche :
# en ligne il sert la cible ; hors ligne, le mandataire répond à sa place.
FALLBACK_SERVER = "https://geo.mirror.pkgbuild.com/$repo/os/$arch"
MIRRORLIST_MARK = (
    "# Ajouté par l'installation hors ligne d'ERPLibre : le live n'avait "
    "aucun serveur actif."
)
# npmrc global de la cible : seul réglage que « sudo npm install -g »
# lit, sudo vidant l'environnement. Le paquet npm d'Arch le place en
# /etc/npmrc (globalconfig de son npmrc intégré), et non sous le préfixe
# /usr : un fichier /usr/etc/npmrc n'est lu par personne.
NPMRC = "etc/npmrc"
NPMRC_MARK = "# erplibre-offline"

# Les pièces que tout manifeste porte. Celles qui ont un sha256 sont
# vérifiées à chaque mise en service (petites) ; repo et store sont
# vérifiés par pacman (empreinte et signature de chaque paquet dans la
# base) et par le magasin (taille de chaque corps).
REQUIRED_PARTS = ("proxy", "ca_cert", "ca_key", "repo", "store")
HASHED_PARTS = ("proxy", "ca_cert", "ca_key")
# Un manifeste d'enregistrement ne porte que l'autorité : le mandataire,
# sa clé et le magasin restent sur l'hôte.
RECORD_PARTS = ("ca_cert",)
# Attente du mandataire de l'hôte et du DNS en mode enregistrement : le
# live démarre avant que son DHCP ait répondu.
UPSTREAM_TIMEOUT_S = 180
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
# Clé de erplibre.* : l'empreinte de la commande du profil enregistré.
COMMAND_KEY = "profile_command_sha256"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

# Paquets qu'archinstall 4.5 ajoute de lui-même à une installation GNOME
# (installer.__packages__, profils Desktop et GNOME, greeter, réseau
# NetworkManager, pipewire) : le contrôle d'avant l'effacement les
# cherche dans le dépôt avec ceux de la configuration. Le pilote
# graphique, les micrologiciels son selon le matériel et les dépendances
# ne sont pas contrôlés : la fermeture du paquet les couvre.
ARCHINSTALL_IMPLICIT = (
    "base",
    "sudo",
    "linux-firmware",
    "mkinitcpio",
    "networkmanager",
    "gdm",
    "gnome",
    "gnome-tweaks",
    "nano",
    "vim",
    "openssh",
    "htop",
    "wget",
    "smartmontools",
    "xdg-utils",
    "pipewire",
    "pipewire-alsa",
    "pipewire-jack",
    "pipewire-pulse",
    "gst-plugin-pipewire",
    "libpulse",
    "wireplumber",
)
UCODE = {"intel": "intel-ucode", "amd": "amd-ucode"}

PROBE_TIMEOUT_S = 15
# « ro » seul rejoue encore un journal ext4 en attente, ce qui écrit sur
# la clé : « noload » ne le lit pas. L'image du paquet est faite sans
# journal (^has_journal) ; l'option garde la lecture seule vraie pour une
# partition refaite à la main.
MOUNT_OPTIONS = "ro,noload,nodev,nosuid,noexec"
# Le paquet du trousseau d'Arch : le live le met à jour depuis le dépôt du
# paquet hors ligne avant pacstrap.
KEYRING_PACKAGE = "archlinux-keyring"
CREATED_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class OfflineError(Exception):
    """Un refus de la mise en service : `code` le nomme, `details` le
    précise."""

    def __init__(self, code, **details):
        super().__init__(code)
        self.code = code
        self.details = details


# Manifeste (pur)


def _safe_rel(path):
    """Vrai pour un chemin relatif qui reste sous la racine du paquet."""
    if not isinstance(path, str) or not path or path.startswith("/"):
        return False
    return ".." not in path.split("/")


def is_record(doc):
    """Vrai pour un manifeste d'enregistrement (voir MODE_RECORD)."""
    return isinstance(doc, dict) and doc.get("mode") == MODE_RECORD


def check_manifest(doc):
    """Les erreurs de forme du manifeste, [] s'il est valide. Chaque
    erreur est « clé : raison ».

    Un manifeste d'enregistrement n'a ni commit (le clone n'a pas encore
    eu lieu), ni version d'archinstall, ni instantané Arch : ce sont des
    résultats de l'enregistrement. Il porte à la place « record » :
    l'adresse IPv4 du mandataire de l'hôte et ses deux ports."""
    if not isinstance(doc, dict):
        return ["manifest: not an object"]
    erreurs = []
    record = is_record(doc)
    if doc.get("mode") is not None and not record:
        erreurs.append(f"mode: {MODE_RECORD} or absent expected")
    if doc.get("schema") != MANIFEST_SCHEMA:
        erreurs.append(f"schema: {MANIFEST_SCHEMA} expected")
    textes = (
        ("erplibre_profile",)
        if record
        else (
            "erplibre_profile",
            "archinstall_version",
        )
    )
    for cle in textes:
        if not isinstance(doc.get(cle), str) or not doc.get(cle):
            erreurs.append(f"{cle}: text required")
    for cle in ("created",) if record else ("created", "arch_snapshot"):
        if not isinstance(doc.get(cle), str) or not DATE_RE.match(
            doc.get(cle) or ""
        ):
            erreurs.append(f"{cle}: date required")
    if doc.get("arch") != ARCH:
        erreurs.append(f"arch: {ARCH} expected")
    source = doc.get("erplibre")
    if not isinstance(source, dict):
        erreurs.append("erplibre: object required")
    else:
        for cle in ("git_url", "branch"):
            if not isinstance(source.get(cle), str) or not source.get(cle):
                erreurs.append(f"erplibre.{cle}: text required")
        if not record and not COMMIT_RE.match(str(source.get("commit") or "")):
            erreurs.append("erplibre.commit: 40 hex digits required")
        empreinte = source.get(COMMAND_KEY)
        if empreinte is not None and not SHA256_RE.match(str(empreinte)):
            erreurs.append(f"erplibre.{COMMAND_KEY}: sha256 required")
    if record:
        erreurs += _record_errors(doc.get("record"))
    parts = doc.get("parts")
    if not isinstance(parts, dict):
        erreurs.append("parts: object required")
        return erreurs
    for nom in RECORD_PARTS if record else REQUIRED_PARTS:
        if nom not in parts:
            erreurs.append(f"parts.{nom}: missing")
    for nom, part in parts.items():
        if not isinstance(part, dict) or not _safe_rel(part.get("path")):
            erreurs.append(f"parts.{nom}.path: relative path required")
            continue
        if nom in HASHED_PARTS and not SHA256_RE.match(
            str(part.get("sha256") or "")
        ):
            erreurs.append(f"parts.{nom}.sha256: required")
    return erreurs


def _record_errors(record):
    """Les erreurs de la section « record » d'un manifeste
    d'enregistrement : une IPv4 qui n'est ni la boucle locale ni
    « non précisée », deux ports TCP."""
    if not isinstance(record, dict):
        return ["record: object required"]
    erreurs = []
    try:
        adresse = ipaddress.IPv4Address(str(record.get("proxy") or ""))
        if adresse.is_loopback or adresse.is_unspecified:
            erreurs.append("record.proxy: not a host address")
    except ValueError:
        erreurs.append("record.proxy: IPv4 address required")
    for cle in ("http_port", "tls_port"):
        port = record.get(cle)
        if not isinstance(port, int) or isinstance(port, bool):
            erreurs.append(f"record.{cle}: port required")
        elif not 0 < port < 65536:
            erreurs.append(f"record.{cle}: port required")
    return erreurs


def manifest_label(doc):
    """« <profil>, <date> » : ce que l'écran montre du paquet."""
    date = str(doc.get("created") or "")[:10]
    if is_record(doc):
        return f"{doc.get('erplibre_profile')}, {date}, {MODE_RECORD}"
    return f"{doc.get('erplibre_profile')}, {date}"


def command_sha256(command):
    """L'empreinte de la commande d'un profil ERPLibre, telle que le
    manifeste la porte (erplibre.profile_command_sha256)."""
    return hashlib.sha256((command or "").encode("utf-8")).hexdigest()


def match_profile(doc, profile, archinstall_version=None, command=None):
    """(ok, raison, mises en garde) : le paquet sert-il ce profil ?

    Un paquet ne sert que le profil ERPLibre qu'il a enregistré : un
    autre profil tire d'autres dépôts et d'autres roues. Une autre
    version d'archinstall n'est qu'une mise en garde : elle peut demander
    des paquets que l'installation de référence n'a pas tirés, et le
    contrôle des paquets d'avant l'effacement le dira.

    `command`, la commande du profil sur l'ISO qui installe, est comparée
    à l'empreinte enregistrée : une autre commande tire des fichiers que
    le magasin ne tient pas, et l'étape échouerait APRÈS l'effacement.
    Un manifeste sans empreinte n'en donne qu'une mise en garde."""
    if doc.get("erplibre_profile") != profile:
        return False, "profile-mismatch", []
    alertes = []
    if command is not None and not is_record(doc):
        enregistree = (doc.get("erplibre") or {}).get(COMMAND_KEY)
        if enregistree is None:
            alertes.append("profile-command-unrecorded")
        elif enregistree != command_sha256(command):
            return False, "profile-command-mismatch", []
    # Un manifeste d'enregistrement n'a pas de version : c'est le live
    # qui enregistre qui la fixe.
    enregistre = doc.get("archinstall_version")
    if (
        archinstall_version
        and enregistre
        and _major_minor(archinstall_version) != _major_minor(enregistre)
    ):
        alertes.append("archinstall-mismatch")
    return True, None, alertes


def _major_minor(version):
    """(majeur, mineur) d'une version « 4.5.1 » : les correctifs d'une
    même version d'archinstall installent les mêmes paquets."""
    morceaux = re.findall(r"\d+", str(version or ""))[:2]
    return tuple(int(m) for m in morceaux)


def data_devices(lsblk):
    """Les chemins des partitions LABEL=DATA_LABEL d'un « lsblk -J -o
    PATH,LABEL,FSTYPE » : un seul est attendu."""
    trouves = []

    def parcourir(noeuds):
        for n in noeuds or []:
            if n.get("label") == DATA_LABEL and n.get("fstype") == "ext4":
                trouves.append(n.get("path"))
            parcourir(n.get("children"))

    parcourir((lsblk or {}).get("blockdevices"))
    return trouves


# Constructeurs (purs)


def nft_ruleset(uid=PROXY_UID, http_port=HTTP_PORT, tls_port=TLS_PORT):
    """Le texte pour « nft -f » : remplace la table entière, d'un coup.

    La sortie du mandataire (son UID) n'est pas détournée : en mode
    enregistrement, il joint l'amont réel, et le détourner le ferait
    boucler sur lui-même. La boucle locale ne l'est pas non plus. Le
    détournement vise l'IPv4 seule, le mandataire n'écoutant que sur
    127.0.0.1 ; l'IPv6 vers 80/443 reçoit un refus immédiat, et le client
    passe à l'IPv4 au lieu d'attendre."""
    t = f"{NFT_FAMILY} {NFT_TABLE}"
    return (
        f"table {t}\n"
        f"delete table {t}\n"
        f"table {t} {{\n"
        "\tchain sortie_nat {\n"
        "\t\ttype nat hook output priority dstnat; policy accept;\n"
        f"\t\tmeta skuid {uid} return\n"
        "\t\tip daddr 127.0.0.0/8 return\n"
        f"\t\tmeta nfproto ipv4 tcp dport 80 redirect to :{http_port}\n"
        f"\t\tmeta nfproto ipv4 tcp dport 443 redirect to :{tls_port}\n"
        "\t}\n"
        "\tchain sortie_filtre {\n"
        "\t\ttype filter hook output priority filter; policy accept;\n"
        f"\t\tmeta skuid {uid} return\n"
        "\t\tmeta nfproto ipv6 tcp dport { 80, 443 } "
        "reject with tcp reset\n"
        "\t}\n"
        "}\n"
    )


def nft_record_ruleset(proxy, http_port, tls_port):
    """Le texte pour « nft -f » du mode enregistrement : la sortie TCP
    80/443 de tout processus part (dnat) vers le mandataire de l'hôte,
    sauf ce qui vise déjà la boucle locale ou le mandataire lui-même. La
    même table que hors ligne, pour que stop() la retire de la même façon.
    L'IPv6 vers 80/443 est refusée pour la même raison : le mandataire
    n'est joint qu'en IPv4."""
    t = f"{NFT_FAMILY} {NFT_TABLE}"
    return (
        f"table {t}\n"
        f"delete table {t}\n"
        f"table {t} {{\n"
        "\tchain sortie_nat {\n"
        "\t\ttype nat hook output priority dstnat; policy accept;\n"
        "\t\tip daddr 127.0.0.0/8 return\n"
        f"\t\tip daddr {proxy} return\n"
        "\t\tmeta nfproto ipv4 tcp dport 80 "
        f"dnat ip to {proxy}:{http_port}\n"
        "\t\tmeta nfproto ipv4 tcp dport 443 "
        f"dnat ip to {proxy}:{tls_port}\n"
        "\t}\n"
        "\tchain sortie_filtre {\n"
        "\t\ttype filter hook output priority filter; policy accept;\n"
        "\t\tmeta nfproto ipv6 tcp dport { 80, 443 } "
        "reject with tcp reset\n"
        "\t}\n"
        "}\n"
    )


def nft_delete_argv():
    return ["nft", "delete", "table", NFT_FAMILY, NFT_TABLE]


def resolved_dropin(dns_addr=DNS_ADDR):
    """Le fragment systemd-resolved : tout nom part vers dnsmasq, sans
    cache (une réponse d'avant la mise en service ne doit pas rester),
    sans DNSSEC (les réponses sont inventées) ni résolution multicast.
    Son nom le classe après celui de releng (archiso.conf), qu'il
    remplace donc pour MulticastDNS."""
    return (
        "# Installation hors ligne d'ERPLibre : retiré par "
        "« erplibre-offline stop ».\n"
        "[Resolve]\n"
        f"DNS={dns_addr}\n"
        "Domains=~.\n"
        "DNSSEC=no\n"
        "DNSOverTLS=no\n"
        "LLMNR=no\n"
        "MulticastDNS=no\n"
        "Cache=no\n"
    )


def dnsmasq_argv(fake=FAKE_ADDR, listen=DNS_ADDR):
    """dnsmasq qui répond `fake` à tout nom (A) et rien en AAAA, sur
    `listen`:53 seulement, sans lire ni resolv.conf ni /etc/hosts."""
    return [
        "dnsmasq",
        "--keep-in-foreground",
        "--conf-file=/dev/null",
        "--no-resolv",
        "--no-hosts",
        "--no-poll",
        "--bind-interfaces",
        f"--listen-address={listen}",
        "--port=53",
        f"--address=/#/{fake}",
        # nobody existe sur tout live ; dnsmasq s'y rabat après avoir
        # ouvert le port 53.
        "--user=nobody",
        "--group=nobody",
    ]


def proxy_argv(binary, data, ca_dir, log_dir, lang="fr"):
    """Le mandataire en mode hors ligne sur le paquet monté en `data`."""
    store = os.path.join(data, "store")
    return [
        binary,
        "--hors-ligne",
        "--ecoute",
        LISTEN_ADDR,
        "--http-port",
        str(HTTP_PORT),
        "--tls-port",
        str(TLS_PORT),
        "--cache-dir",
        store,
        "--git-mirror-dir",
        os.path.join(store, "git"),
        "--depot-pacman",
        os.path.join(data, "repo"),
        "--ca-dir",
        ca_dir,
        "--access-log",
        os.path.join(log_dir, "access.jsonl"),
        "--lang",
        lang,
    ]


def systemd_run_argv(unit, argv, properties=()):
    """Un service transitoire `unit` qui lance `argv`."""
    out = [
        "systemd-run",
        f"--unit={unit}",
        "--service-type=exec",
        "--collect",
        "--quiet",
    ]
    for prop in properties:
        out += ["-p", prop]
    return out + ["--", *argv]


def proxy_properties(log_dir, uid=PROXY_UID):
    """Le mandataire sans privilège : son UID, aucune capacité, système
    en lecture seule sauf son journal."""
    return (
        f"User={uid}",
        f"Group={uid}",
        "NoNewPrivileges=yes",
        "CapabilityBoundingSet=",
        "PrivateTmp=yes",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        f"ReadWritePaths={log_dir}",
    )


def mirrorlist_with_server(text, server=FALLBACK_SERVER):
    """(texte, changé) : `text` tel quel s'il porte un « Server = » actif,
    sinon un serveur ajouté en tête. Le mandataire sert tout miroir Arch
    hors ligne ; pacstrap recopie la liste dans la cible, qui garde donc
    un miroir réel."""
    for ligne in (text or "").splitlines():
        if re.match(r"^\s*Server\s*=", ligne):
            return text, False
    return f"{MIRRORLIST_MARK}\nServer = {server}\n\n{text or ''}", True


def stage_env(anchor=None):
    """Les variables que l'étape ERPLibre passe à la commande du profil
    hors ligne, toutes pointées sur le faisceau système (qui contient
    l'ancre après trust extract-compat) : pip, requests (Poetry), Python
    (ssl), uv, Node. git et pacman lisent déjà le faisceau système.
    Gardé en accord avec el_offline_env de erplibre-stage.sh, que
    test_iso_offline compare."""
    return {
        "SSL_CERT_FILE": SYSTEM_BUNDLE,
        "REQUESTS_CA_BUNDLE": SYSTEM_BUNDLE,
        "PIP_CERT": SYSTEM_BUNDLE,
        "CURL_CA_BUNDLE": SYSTEM_BUNDLE,
        "NODE_EXTRA_CA_CERTS": SYSTEM_BUNDLE,
        "UV_NATIVE_TLS": "1",
        "NPM_CONFIG_AUDIT": "false",
        "NPM_CONFIG_FUND": "false",
        "NPM_CONFIG_UPDATE_NOTIFIER": "false",
    }


def stage_prelude(manifest, ca_pem):
    """Les variables hors ligne du prélude de l'étape ERPLibre : la source
    git est celle que le paquet a enregistrée (son miroir ne tient
    qu'elle), et l'autorité voyage en base64 sur une seule ligne, que la
    copie de relance de l'étape retire avec les autres EL_OFFLINE*."""
    source = manifest.get("erplibre") or {}
    if isinstance(ca_pem, str):
        ca_pem = ca_pem.encode("ascii")
    return [
        ("EL_OFFLINE", "1"),
        ("EL_OFFLINE_CA_B64", base64.b64encode(ca_pem).decode("ascii")),
        ("EL_GIT_URL", source.get("git_url", "")),
        ("EL_GIT_BRANCH", source.get("branch", "")),
    ]


def required_packages(config, cpu_vendor=None):
    """Les noms que le dépôt du paquet doit servir pour cette
    configuration archinstall : ses paquets, ses noyaux, ceux
    qu'archinstall ajoute (ARCHINSTALL_IMPLICIT), le microcode du
    processeur et le chargeur d'amorçage. Sans doublon, dans l'ordre."""
    noms = list(ARCHINSTALL_IMPLICIT)
    noms += config.get("kernels") or ["linux"]
    noms += config.get("packages") or []
    if cpu_vendor in UCODE:
        noms.append(UCODE[cpu_vendor])
    chargeur = (config.get("bootloader_config") or {}).get("bootloader")
    if chargeur == "Grub":
        noms.append("grub")
    noms.append("efibootmgr")
    vus, out = set(), []
    for n in noms:
        if n and n not in vus:
            vus.add(n)
            out.append(n)
    return out


# Bases pacman (pur sur des fichiers)


def _desc_fields(texte):
    champs, cle = {}, None
    for ligne in texte.splitlines():
        if ligne.startswith("%") and ligne.endswith("%"):
            cle = ligne.strip("%")
            champs[cle] = []
        elif ligne and cle:
            champs[cle].append(ligne)
    return champs


def _bare(nom):
    return re.split(r"[<>=]", nom, maxsplit=1)[0]


def read_db(path):
    """{"packages": {nom: fichier}, "provides": {nom: [paquets]},
    "groups": {groupe: [paquets]}, "signed": {noms}} d'une base pacman
    (tar, toute compression que tarfile lit). « signed » : les paquets
    dont la base porte la signature (%PGPSIG%) ; pour les autres, pacman
    télécharge « <fichier>.sig » à côté du paquet."""
    index = {"packages": {}, "provides": {}, "groups": {}, "signed": set()}
    with tarfile.open(path, "r:*") as tar:
        for membre in tar:
            if not membre.isfile() or not membre.name.endswith("/desc"):
                continue
            champs = _desc_fields(
                tar.extractfile(membre).read().decode("utf-8", "replace")
            )
            nom = (champs.get("NAME") or [None])[0]
            fichier = (champs.get("FILENAME") or [None])[0]
            if not nom or not fichier:
                continue
            index["packages"][nom] = fichier
            if champs.get("PGPSIG"):
                index["signed"].add(nom)
            for p in champs.get("PROVIDES") or []:
                index["provides"].setdefault(_bare(p), []).append(nom)
            for g in champs.get("GROUPS") or []:
                index["groups"].setdefault(g, []).append(nom)
    return index


def merge_indexes(indexes):
    """Les index de plusieurs bases, dans l'ordre de pacman.conf (core
    avant extra) : le premier dépôt qui a un nom l'emporte."""
    out = {"packages": {}, "provides": {}, "groups": {}, "repo": {}}
    for depot, index in indexes:
        for nom, fichier in index["packages"].items():
            if nom not in out["packages"]:
                out["packages"][nom] = fichier
                out["repo"][nom] = depot
        for cle in ("provides", "groups"):
            for nom, paquets in index[cle].items():
                out[cle].setdefault(nom, []).extend(paquets)
    return out


def missing_packages(names, index, exists):
    """[(nom, raison)] des noms que le dépôt ne sert pas : « unknown »
    (ni paquet, ni fourni, ni groupe), « file-missing » (la base le
    nomme, son fichier manque). `exists(depot, fichier)` dit si le
    fichier est dans le dépôt."""
    manquants = []

    def present(paquet):
        return exists(index["repo"][paquet], index["packages"][paquet])

    for nom in names:
        nu = _bare(nom)
        if nu in index["packages"]:
            candidats = [nu]
        elif nu in index["provides"]:
            candidats = index["provides"][nu]
        elif nu in index["groups"]:
            membres = index["groups"][nu]
            absents = [m for m in membres if not present(m)]
            if absents:
                manquants.append((nom, "file-missing"))
            continue
        else:
            manquants.append((nom, "unknown"))
            continue
        if not any(present(c) for c in candidats):
            manquants.append((nom, "file-missing"))
    return manquants


# Cible (pur)


# « TRUSTED CERTIFICATE » : le faisceau OpenSSL de p11-kit, dont le
# base64 porte le DER suivi des attributs de confiance.
PEM_CERT_RE = re.compile(
    rb"-----BEGIN (?:TRUSTED )?CERTIFICATE-----(.+?)"
    rb"-----END (?:TRUSTED )?CERTIFICATE-----",
    re.S,
)


def pem_ders(data):
    """Les contenus décodés des blocs « CERTIFICATE » et « TRUSTED
    CERTIFICATE » de `data` (octets ou texte) : le DER, suivi des
    attributs de confiance pour le second. Un bloc dont le base64 ne se
    décode pas est ignoré."""
    if isinstance(data, str):
        data = data.encode("ascii", "replace")
    ders = []
    for corps in PEM_CERT_RE.findall(data or b""):
        try:
            ders.append(
                base64.b64decode(b"".join(corps.split()), validate=True)
            )
        except (binascii.Error, ValueError):
            continue
    return ders


def bundle_hits(target, ca_der, dirs=TARGET_BUNDLE_DIRS):
    """Les fichiers des faisceaux de la cible montée en `target` qui
    contiennent le certificat `ca_der`, chemins relatifs à `target`,
    triés. Un fichier en contient le DER brut (Java) ou un bloc PEM qui le
    contient (PEM, OpenSSL, cadir). Les liens symboliques ne sont pas
    suivis : lus depuis le live, ils peuvent désigner le live."""
    trouves = []
    if not ca_der:
        return trouves
    for rel in dirs:
        racine = os.path.join(target, rel)
        for dossier, _sous, fichiers in os.walk(racine):
            for nom in fichiers:
                chemin = os.path.join(dossier, nom)
                if os.path.islink(chemin) or not os.path.isfile(chemin):
                    continue
                try:
                    with open(chemin, "rb") as fh:
                        data = fh.read()
                except OSError:
                    continue
                if ca_der in data or any(
                    ca_der in bloc for bloc in pem_ders(data)
                ):
                    trouves.append(os.path.relpath(chemin, target))
    return sorted(set(trouves))


def target_residues(target, exists=os.path.exists, read=None, ca_pem=None):
    """Ce que l'installation hors ligne aurait laissé dans la cible
    montée en `target` : l'ancre de l'autorité, le npmrc global de
    l'étape et, si `ca_pem` est donné, l'autorité encore présente dans
    un faisceau extrait (« bundle ») — ce qui arrive quand l'ancre est
    effacée mais que trust extract-compat n'a pas pu réécrire le
    faisceau (disque plein, étape tuée entre les deux). [] si la cible
    est propre."""
    read = read or _read_text
    restes = []
    if exists(os.path.join(target, ANCHOR_DIR.lstrip("/"), ANCHOR_NAME)):
        restes.append("anchor")
    npmrc = os.path.join(target, NPMRC)
    if exists(npmrc) and NPMRC_MARK in read(npmrc):
        restes.append("npmrc")
    ders = pem_ders(ca_pem) if ca_pem else []
    if ders and bundle_hits(target, ders[0]):
        restes.append("bundle")
    return restes


def target_cleanup_steps(target, residues, regenerate=False):
    """Les gestes qui retirent `residues` de la cible : fichiers effacés,
    puis le faisceau régénéré DANS la cible. `regenerate` le régénère
    même sans reste connu : seule la régénération retire l'autorité d'un
    faisceau dont l'ancre est déjà partie."""
    etapes = []
    if "anchor" in residues:
        etapes.append(
            {
                "kind": "remove",
                "path": os.path.join(
                    target, ANCHOR_DIR.lstrip("/"), ANCHOR_NAME
                ),
            }
        )
    if "npmrc" in residues:
        etapes.append({"kind": "remove", "path": os.path.join(target, NPMRC)})
    if regenerate or "anchor" in residues or "bundle" in residues:
        etapes.append(
            {
                "kind": "run",
                "argv": ["arch-chroot", target, "trust", "extract-compat"],
            }
        )
    return etapes


# Plan de mise en service (pur)


def paths_for(run_dir=RUN_DIR):
    return {
        "run": run_dir,
        "state": os.path.join(run_dir, STATE_NAME),
        "data": os.path.join(run_dir, DATA_DIRNAME),
        "bin": os.path.join(run_dir, "bin"),
        "ca": os.path.join(run_dir, "ca"),
        "log": os.path.join(run_dir, "log"),
        "nft": os.path.join(run_dir, "ruleset.nft"),
        "mirrorlist_backup": os.path.join(run_dir, "mirrorlist.orig"),
        "anchor": os.path.join(ANCHOR_DIR, ANCHOR_NAME),
        "resolved": RESOLVED_DROPIN,
        "mirrorlist": MIRRORLIST,
    }


def _trust_steps(paths, ca_part):
    """Liste de miroirs du live, puis l'autorité `ca_part` (pièce du
    manifeste) approuvée par le live : communs aux deux modes."""
    return [
        {
            "id": "mirrorlist",
            "kind": "mirrorlist",
            "path": paths["mirrorlist"],
            "backup": paths["mirrorlist_backup"],
            "undo": {
                "kind": "restore",
                "path": paths["mirrorlist"],
                "backup": paths["mirrorlist_backup"],
            },
        },
        {
            "id": "anchor",
            "kind": "install",
            "src": os.path.join(paths["data"], ca_part["path"]),
            "dest": paths["anchor"],
            "mode": 0o644,
            "uid": 0,
            "sha256": ca_part["sha256"],
            "undo": {
                "kind": "remove",
                "path": paths["anchor"],
                "after": ["trust", "extract-compat"],
            },
        },
        {
            "id": "trust",
            "kind": "run",
            "argv": ["trust", "extract-compat"],
            "undo": None,
        },
    ]


def start_plan(paths, manifest, lang="fr"):
    """Les gestes de la mise en service, dans l'ordre, chacun avec son
    inverse (« undo », None quand rien n'est à défaire). Le paquet est
    déjà monté sur paths["data"].

    Formes : {"id", "kind": "run", "argv"} ; {"id", "kind": "install",
    "src", "dest", "mode", "uid"} (copie) ; {"id", "kind": "write",
    "path", "text"} ; {"id", "kind": "mirrorlist"} ; {"id", "kind":
    "wait_ports"} ; {"id", "kind": "selftest"} ; {"id", "kind": "clock",
    "not_before"} ; {"id", "kind": "keyring_update"}. Un inverse est {"kind":
    "run", "argv"}, {"kind": "remove", "path"} ou {"kind": "restore",
    "path", "backup"} ; son « after », un argv, se lance une fois
    l'inverse fait.

    Un fichier et la commande qui le lit ne font qu'un inverse : effacer
    l'ancre PUIS régénérer le faisceau, effacer le fragment de
    systemd-resolved PUIS le redémarrer. Deux inverses, pris en ordre
    inverse, relanceraient d'abord la commande, fichier encore présent :
    l'autorité resterait approuvée, le DNS resterait détourné."""
    parts = manifest["parts"]
    data = paths["data"]
    binaire = os.path.join(paths["bin"], PROXY_NAME)
    restart_resolved = ["systemctl", "restart", "systemd-resolved.service"]
    return [
        {
            "id": "account",
            "kind": "run",
            "argv": ["getent", "passwd", str(PROXY_UID)],
            "undo": None,
        },
        {
            "id": "clock",
            "kind": "clock",
            "not_before": clock_floor(manifest),
            "undo": None,
        },
        {
            "id": "time-wait",
            "kind": "run",
            "argv": ["systemctl", "stop", "systemd-time-wait-sync.service"],
            "undo": None,
        },
        {
            "id": "keyring",
            "kind": "run",
            "argv": ["systemctl", "start", "pacman-init.service"],
            "undo": None,
        },
        {
            "id": "proxy-binary",
            "kind": "install",
            "src": os.path.join(data, parts["proxy"]["path"]),
            "dest": binaire,
            "mode": 0o755,
            "uid": 0,
            "sha256": parts["proxy"]["sha256"],
            "undo": {"kind": "remove", "path": paths["bin"]},
        },
        {
            "id": "ca-cert",
            "kind": "install",
            "src": os.path.join(data, parts["ca_cert"]["path"]),
            "dest": os.path.join(paths["ca"], "ca.crt"),
            "mode": 0o644,
            "uid": PROXY_UID,
            "sha256": parts["ca_cert"]["sha256"],
            "undo": {"kind": "remove", "path": paths["ca"]},
        },
        {
            "id": "ca-key",
            "kind": "install",
            "src": os.path.join(data, parts["ca_key"]["path"]),
            "dest": os.path.join(paths["ca"], "ca.key"),
            "mode": 0o600,
            "uid": PROXY_UID,
            "sha256": parts["ca_key"]["sha256"],
            "undo": None,
        },
        {
            "id": "log-dir",
            "kind": "mkdir",
            "path": paths["log"],
            "uid": PROXY_UID,
            "undo": {"kind": "remove", "path": paths["log"]},
        },
        *_trust_steps(paths, parts["ca_cert"]),
        {
            "id": "fake-link",
            "kind": "run",
            "argv": ["ip", "link", "add", DUMMY_LINK, "type", "dummy"],
            "undo": {
                "kind": "run",
                "argv": ["ip", "link", "del", DUMMY_LINK],
            },
        },
        {
            "id": "fake-address",
            "kind": "run",
            "argv": [
                "ip",
                "address",
                "add",
                f"{FAKE_ADDR}/{FAKE_PREFIX}",
                "dev",
                DUMMY_LINK,
            ],
            "undo": None,
        },
        {
            "id": "fake-up",
            "kind": "run",
            "argv": ["ip", "link", "set", DUMMY_LINK, "up"],
            "undo": None,
        },
        {
            "id": "fake-route",
            "kind": "run",
            "argv": [
                "ip",
                "route",
                "add",
                "default",
                "dev",
                DUMMY_LINK,
                "metric",
                str(DUMMY_METRIC),
            ],
            "undo": None,
        },
        {
            "id": "proxy",
            "kind": "run",
            "argv": systemd_run_argv(
                PROXY_UNIT,
                proxy_argv(binaire, data, paths["ca"], paths["log"], lang),
                proxy_properties(paths["log"]),
            ),
            "undo": {
                "kind": "run",
                "argv": ["systemctl", "stop", f"{PROXY_UNIT}.service"],
            },
        },
        {"id": "proxy-ready", "kind": "wait_ports", "undo": None},
        {
            "id": "dns",
            "kind": "run",
            "argv": systemd_run_argv(DNS_UNIT, dnsmasq_argv()),
            "undo": {
                "kind": "run",
                "argv": ["systemctl", "stop", f"{DNS_UNIT}.service"],
            },
        },
        {
            "id": "resolved-dropin",
            "kind": "write",
            "path": paths["resolved"],
            "text": resolved_dropin(),
            "undo": {
                "kind": "remove",
                "path": paths["resolved"],
                "after": restart_resolved,
            },
        },
        {
            "id": "resolved",
            "kind": "run",
            "argv": restart_resolved,
            "undo": None,
        },
        {
            "id": "nft-rules",
            "kind": "write",
            "path": paths["nft"],
            "text": nft_ruleset(),
            "undo": {"kind": "remove", "path": paths["nft"]},
        },
        {
            "id": "nft",
            "kind": "run",
            "argv": ["nft", "-f", paths["nft"]],
            "undo": {"kind": "run", "argv": nft_delete_argv()},
        },
        {"id": "selftest", "kind": "selftest", "undo": None},
        {"id": "keyring-update", "kind": "keyring_update", "undo": None},
    ]


def clock_floor(manifest):
    """L'heure (secondes epoch, UTC) sous laquelle l'horloge du live ne
    doit pas rester : la création du paquet (« created »), ou None si
    elle ne se lit pas. L'autorité du paquet et les signatures de son
    instantané Arch sont antérieures ; une horloge en retard (horloge
    matérielle tenue à l'heure locale, pile morte) les ferait refuser
    comme « pas encore valides ». Sans réseau, rien d'autre ne la
    corrige : l'attente de NTP est levée."""
    texte = str(manifest.get("created") or "")
    for forme, longueur in ((CREATED_FORMAT, 20), ("%Y-%m-%d", 10)):
        try:
            moment = datetime.datetime.strptime(texte[:longueur], forme)
        except ValueError:
            continue
        return int(moment.replace(tzinfo=datetime.timezone.utc).timestamp())
    return None


def clock_argv(floor, now):
    """L'argv qui avance l'horloge du live à `floor`, ou None si `now`
    n'est pas en retard. L'horloge n'est jamais reculée."""
    if floor is None or now >= floor:
        return None
    return ["date", "-u", "-s", f"@{int(floor)}"]


def keyring_argvs():
    """(synchronisation, contrôle, mise à jour) du trousseau du live
    depuis le dépôt du paquet, au travers du mandataire.

    En ligne, archinstall attend archlinux-keyring-wkd-sync, qui
    rafraîchit les clés des empaqueteurs ; --skip-wkd le saute. Hors
    ligne, pacstrap vérifierait donc chaque paquet contre le trousseau
    figé à la construction de l'ISO : une clé ajoutée ou prolongée depuis
    ferait refuser un paquet de l'instantané, APRÈS l'effacement. Le
    paquet archlinux-keyring de l'instantané, vérifié par le trousseau
    actuel, le remplace (son script d'installation relance pacman-key
    --populate). Le contrôle (pacman -Qu) rend 0 seulement s'il est plus
    récent que celui du live : un trousseau plus ancien n'est jamais
    installé à la place."""
    return (
        ["pacman", "-Sy", "--noconfirm"],
        ["pacman", "-Qu", KEYRING_PACKAGE],
        ["pacman", "-S", "--noconfirm", KEYRING_PACKAGE],
    )


def record_plan(paths, manifest):
    """Les gestes du mode enregistrement, mêmes formes et mêmes inverses
    que start_plan() : trousseau, autorité approuvée par le live, liste de
    miroirs, nft vers le mandataire de l'hôte, puis l'essai de bout en
    bout. Ni compte, ni mandataire local, ni DNS factice : le live garde
    son réseau. « wait_upstream » attend que le mandataire réponde et que
    le DNS résolve, le DHCP du live pouvant être encore en cours."""
    parts = manifest["parts"]
    record = manifest["record"]
    data = paths["data"]
    etapes = [
        {
            "id": "time-wait",
            "kind": "run",
            "argv": ["systemctl", "stop", "systemd-time-wait-sync.service"],
            "undo": None,
        },
        {
            "id": "keyring",
            "kind": "run",
            "argv": ["systemctl", "start", "pacman-init.service"],
            "undo": None,
        },
        {
            "id": "upstream",
            "kind": "wait_upstream",
            "host": record["proxy"],
            "port": record["http_port"],
            "undo": None,
        },
        {
            "id": "ca-cert",
            "kind": "install",
            "src": os.path.join(data, parts["ca_cert"]["path"]),
            "dest": os.path.join(paths["ca"], "ca.crt"),
            "mode": 0o644,
            "uid": 0,
            "sha256": parts["ca_cert"]["sha256"],
            "undo": {"kind": "remove", "path": paths["ca"]},
        },
    ]
    etapes += _trust_steps(paths, parts["ca_cert"])
    etapes += [
        {
            "id": "nft-rules",
            "kind": "write",
            "path": paths["nft"],
            "text": nft_record_ruleset(
                record["proxy"], record["http_port"], record["tls_port"]
            ),
            "undo": {"kind": "remove", "path": paths["nft"]},
        },
        {
            "id": "nft",
            "kind": "run",
            "argv": ["nft", "-f", paths["nft"]],
            "undo": {"kind": "run", "argv": nft_delete_argv()},
        },
        {"id": "selftest", "kind": "selftest", "undo": None},
    ]
    return etapes


def plan_for(paths, manifest, lang="fr"):
    """Le plan de mise en service qui convient au manifeste."""
    if is_record(manifest):
        return record_plan(paths, manifest)
    return start_plan(paths, manifest, lang)


def selftest_url(server=FALLBACK_SERVER):
    """L'URL que l'essai final demande : la base « core » au travers de
    tout le chemin (DNS, détournement, autorité, mandataire, dépôt)."""
    return server.replace("$repo", "core").replace("$arch", ARCH) + "/core.db"


# Exécution (impur)


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for bloc in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def load_state(paths=None):
    paths = paths or paths_for()
    try:
        with open(paths["state"], encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _save_state(paths, state):
    os.makedirs(paths["run"], mode=0o755, exist_ok=True)
    tmp = paths["state"] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, paths["state"])


def _run_ok(run, argv, log):
    log("$ " + " ".join(argv))
    try:
        res = run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except OSError as exc:
        log(f"cannot run {argv[0]}: {exc}")
        return False
    sortie = res.stdout or b""
    if isinstance(sortie, bytes):
        sortie = sortie.decode("utf-8", "replace")
    for ligne in sortie.splitlines():
        log(f"  {ligne}")
    return res.returncode == 0


def _lsblk(run):
    try:
        res = run(
            ["lsblk", "-J", "-o", "PATH,LABEL,FSTYPE"],
            capture_output=True,
            text=True,
            check=False,
        )
        return json.loads(res.stdout or "{}")
    except (OSError, ValueError):
        return {}


def _mounted(path):
    """Vrai si `path` est un point de montage."""
    return os.path.ismount(path)


def probe(paths=None, run=subprocess.run, log=lambda _m: None):
    """{"found", "ok", "reason", "device", "manifest", "errors",
    "active"} : la partition de données existe-t-elle, et son manifeste
    est-il valide ? Monte la partition en lecture seule si elle ne l'est
    pas déjà (et le note dans l'état, pour que stop() la démonte)."""
    paths = paths or paths_for()
    etat = load_state(paths) or {}
    out = {
        "found": False,
        "ok": False,
        "reason": None,
        "device": None,
        "manifest": None,
        "errors": [],
        "active": bool(etat.get("active")),
    }
    data = paths["data"]
    if not _mounted(data):
        appareils = data_devices(_lsblk(run))
        if not appareils:
            out["reason"] = "no-data-partition"
            return out
        if len(appareils) > 1:
            out.update(found=True, reason="ambiguous", errors=appareils)
            return out
        os.makedirs(data, exist_ok=True)
        if not _run_ok(
            run,
            [
                "mount",
                "-t",
                "ext4",
                "-o",
                MOUNT_OPTIONS,
                appareils[0],
                data,
            ],
            log,
        ):
            out.update(found=True, reason="mount-failed", device=appareils[0])
            return out
        etat.update(device=appareils[0], mounted=True)
        etat.setdefault("undo", [])
        _save_state(paths, etat)
    out["found"] = True
    out["device"] = etat.get("device")
    try:
        with open(os.path.join(data, MANIFEST_NAME), encoding="utf-8") as fh:
            manifeste = json.load(fh)
    except (OSError, ValueError) as exc:
        out.update(reason="manifest-unreadable", errors=[str(exc)])
        return out
    erreurs = check_manifest(manifeste)
    out["manifest"] = manifeste
    if erreurs:
        out.update(reason="manifest-invalid", errors=erreurs)
        return out
    out["ok"] = True
    return out


def _install(step):
    attendu = step.get("sha256")
    if attendu and sha256_file(step["src"]) != attendu:
        raise OfflineError("checksum", path=step["src"])
    dossier = os.path.dirname(step["dest"])
    os.makedirs(dossier, mode=0o755, exist_ok=True)
    if step.get("uid"):
        os.chown(dossier, step["uid"], step["uid"])
        os.chmod(dossier, 0o700)
    tmp = step["dest"] + ".tmp"
    shutil.copyfile(step["src"], tmp)
    os.chmod(tmp, step["mode"])
    if step.get("uid"):
        os.chown(tmp, step["uid"], step["uid"])
    os.replace(tmp, step["dest"])


def _mirrorlist(step):
    texte = _read_text(step["path"])
    nouveau, change = mirrorlist_with_server(texte)
    os.makedirs(os.path.dirname(step["backup"]), exist_ok=True)
    shutil.copyfile(step["path"], step["backup"])
    if change:
        with open(step["path"], "w", encoding="utf-8") as fh:
            fh.write(nouveau)


def _wait_ports(attente_s=PROBE_TIMEOUT_S, sleep=time.sleep):
    for _i in range(attente_s * 4):
        prets = 0
        for port in (HTTP_PORT, TLS_PORT):
            try:
                with socket.create_connection((LISTEN_ADDR, port), timeout=1):
                    prets += 1
            except OSError:
                pass
        if prets == 2:
            return True
        sleep(0.25)
    return False


def _wait_upstream(host, port, attente_s=UPSTREAM_TIMEOUT_S, sleep=time.sleep):
    """Vrai quand le mandataire de l'hôte accepte une connexion ET que le
    nom de l'essai final se résout, avant `attente_s` secondes."""
    nom = selftest_url().split("/")[2]
    for _i in range(attente_s):
        try:
            with socket.create_connection((host, port), timeout=2):
                pass
            socket.getaddrinfo(nom, 443, socket.AF_INET)
            return True
        except OSError:
            sleep(1)
    return False


def _selftest(sleep=time.sleep):
    """La base « core » demandée comme pacman le ferait, au travers du
    DNS, de nft, de l'autorité et du mandataire. systemd-resolved vient
    de redémarrer : quelques essais lui laissent le temps."""
    url = selftest_url()
    derniere = None
    for _i in range(PROBE_TIMEOUT_S):
        try:
            req = urllib.request.Request(url, method="HEAD")
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=5, context=ctx) as rep:
                if rep.status == 200:
                    return True, None
                derniere = f"HTTP {rep.status}"
        except (
            urllib.error.URLError,
            OSError,
            http.client.HTTPException,
        ) as exc:
            # HTTPException (réponse mal formée, corps tronqué) n'est pas
            # une OSError : non prise ici, elle sortirait de start() sans
            # que rien ne soit défait.
            derniere = str(exc) or type(exc).__name__
        sleep(1)
    return False, derniere


def _keyring_update(run, log):
    """Met le trousseau du live à jour depuis le paquet (keyring_argvs) ;
    OfflineError avant tout effacement si pacman refuse."""
    sync, controle, maj = keyring_argvs()
    if not _run_ok(run, sync, log):
        raise OfflineError("keyring-update-failed", step="sync")
    if not _run_ok(run, controle, log):
        log(f"offline: {KEYRING_PACKAGE} of the live is up to date")
        return
    if not _run_ok(run, maj, log):
        raise OfflineError("keyring-update-failed", step="install")


def undo_step(undo, run=subprocess.run, log=print):
    """Défait un geste ; un échec est dit, jamais levé."""
    sorte = undo.get("kind")
    try:
        if sorte == "run":
            _run_ok(run, undo["argv"], log)
        elif sorte == "remove":
            chemin = undo["path"]
            log(f"rm {chemin}")
            if os.path.isdir(chemin) and not os.path.islink(chemin):
                shutil.rmtree(chemin, ignore_errors=True)
            elif os.path.lexists(chemin):
                os.unlink(chemin)
        elif sorte == "restore":
            log(f"restore {undo['path']}")
            if os.path.exists(undo["backup"]):
                shutil.copyfile(undo["backup"], undo["path"])
                os.unlink(undo["backup"])
    except OSError as exc:
        log(f"undo failed: {exc}")
    if undo.get("after"):
        _run_ok(run, undo["after"], log)


def execute_plan(paths, plan, state, run=subprocess.run, log=print):
    """Lance `plan` ; chaque inverse est noté dans l'état dès que son geste
    a réussi. Lève OfflineError au premier échec."""
    for step in plan:
        sorte = step["kind"]
        log(f"offline: {step['id']}")
        if sorte == "run":
            if not _run_ok(run, step["argv"], log):
                raise OfflineError("step-failed", step=step["id"])
        elif sorte == "install":
            _install(step)
        elif sorte == "mkdir":
            os.makedirs(step["path"], mode=0o755, exist_ok=True)
            os.chown(step["path"], step["uid"], step["uid"])
        elif sorte == "write":
            os.makedirs(os.path.dirname(step["path"]), exist_ok=True)
            with open(step["path"], "w", encoding="utf-8") as fh:
                fh.write(step["text"])
        elif sorte == "mirrorlist":
            _mirrorlist(step)
        elif sorte == "wait_ports":
            if not _wait_ports():
                raise OfflineError("proxy-not-listening")
        elif sorte == "wait_upstream":
            if not _wait_upstream(step["host"], step["port"]):
                raise OfflineError("upstream-unreachable", host=step["host"])
        elif sorte == "selftest":
            ok, cause = _selftest()
            if not ok:
                raise OfflineError("selftest-failed", cause=cause)
        elif sorte == "clock":
            argv = clock_argv(step["not_before"], time.time())
            if argv:
                log("offline: clock is behind the payload, moved forward")
                if not _run_ok(run, argv, log):
                    raise OfflineError("step-failed", step=step["id"])
        elif sorte == "keyring_update":
            _keyring_update(run, log)
        if step.get("undo"):
            state["undo"].append(step["undo"])
            _save_state(paths, state)


def start(profile, paths=None, run=subprocess.run, log=print, lang="fr"):
    """Met le mode hors ligne en service pour le profil ERPLibre
    `profile` ; rend l'état (dont le manifeste). Déjà actif pour ce
    profil : rien n'est refait. OfflineError sur refus ou échec, et tout
    ce qui avait été fait est alors défait."""
    paths = paths or paths_for()
    sonde = probe(paths, run, log)
    if not sonde["ok"]:
        raise OfflineError(sonde["reason"], errors=sonde["errors"])
    manifeste = sonde["manifest"]
    ok, raison, alertes = match_profile(manifeste, profile)
    if not ok:
        raise OfflineError(
            raison,
            payload=manifeste.get("erplibre_profile"),
            wanted=profile,
        )
    etat = load_state(paths) or {}
    if etat.get("active"):
        return etat
    etat.setdefault("undo", [])
    etat.update(manifest=manifeste, profile=profile, warnings=alertes)
    _save_state(paths, etat)
    try:
        execute_plan(paths, plan_for(paths, manifeste, lang), etat, run, log)
    except BaseException as exc:
        # Toute sortie, Ctrl-C et exception inattendue comprises, défait
        # ce qui a été fait : nft, DNS factice et ancre laissés sur le
        # live casseraient une nouvelle tentative en ligne.
        log(f"offline: start failed: {exc!r}")
        stop(paths, run, log, keep_mount=True)
        if isinstance(exc, OfflineError) or not isinstance(exc, Exception):
            raise
        raise OfflineError("step-failed", error=str(exc)) from exc
    etat["active"] = True
    _save_state(paths, etat)
    return etat


def stop(paths=None, run=subprocess.run, log=print, keep_mount=False):
    """Défait, en ordre inverse, chaque geste noté par start(), puis
    démonte le paquet (sauf `keep_mount`). Sans état, ne fait rien."""
    paths = paths or paths_for()
    etat = load_state(paths)
    if etat is None:
        return
    while etat.get("undo"):
        undo_step(etat["undo"].pop(), run, log)
        _save_state(paths, etat)
    etat["active"] = False
    if keep_mount:
        _save_state(paths, etat)
        return
    if etat.get("mounted") and _mounted(paths["data"]):
        _run_ok(run, ["umount", paths["data"]], log)
    try:
        os.unlink(paths["state"])
    except OSError:
        pass


def clean_target(target, run=subprocess.run, log=print, ca_pem=None):
    """Retire de la cible ce que l'installation hors ligne y aurait
    laissé, puis la contrôle de nouveau ; rend (restes trouvés, restes
    après nettoyage), deux listes vides pour une cible propre.

    Avec `ca_pem`, le faisceau est TOUJOURS régénéré (si la cible a
    trust), puis fouillé pour l'autorité : une ancre effacée ne prouve
    pas que le faisceau l'a oubliée. Un reste après nettoyage veut dire
    que la cible approuve encore l'autorité du paquet : l'installation
    est à déclarer en échec."""
    restes = target_residues(target, ca_pem=ca_pem)
    regenerer = bool(ca_pem) and os.path.exists(
        os.path.join(target, TARGET_TRUST)
    )
    for etape in target_cleanup_steps(target, restes, regenerer):
        undo_step(etape, run, log)
    return restes, target_residues(target, ca_pem=ca_pem)


def ca_pem(paths=None):
    """Le certificat de l'autorité du paquet actif, ou None."""
    paths = paths or paths_for()
    texte = _read_text(os.path.join(paths["ca"], "ca.crt"))
    return texte or None


def repo_index(data, manifest):
    """L'index fusionné des bases du dépôt du paquet monté en `data`."""
    repo = os.path.join(data, manifest["parts"]["repo"]["path"])
    indexes = []
    for depot in ("core", "extra", "multilib"):
        base = os.path.join(repo, depot, "os", ARCH, f"{depot}.db")
        if os.path.exists(base):
            indexes.append((depot, read_db(base)))
    return merge_indexes(indexes), repo


def check_packages(names, data, manifest):
    """[(nom, raison)] des paquets que le dépôt du paquet monté en `data`
    ne sert pas. Lecture seule : sert aussi à l'essai à blanc."""
    index, repo = repo_index(data, manifest)

    def existe(depot, fichier):
        return os.path.exists(os.path.join(repo, depot, "os", ARCH, fichier))

    return missing_packages(names, index, existe)


# Ligne de commande


def _parser():
    import argparse

    parser = argparse.ArgumentParser(
        description="ERPLibre offline install: the data partition of the "
        "key replaces the network."
    )
    sous = parser.add_subparsers(dest="action", required=True)
    sous.add_parser("probe", help="find and read the payload (JSON)")
    demarrer = sous.add_parser("start", help="serve the payload offline")
    demarrer.add_argument("--profile", required=True)
    demarrer.add_argument("--lang", default="fr")
    sous.add_parser("stop", help="undo everything start did, unmount")
    sous.add_parser("status", help="state (JSON)")
    nettoyer = sous.add_parser(
        "clean-target", help="remove offline residues from a target"
    )
    nettoyer.add_argument("target")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if os.geteuid() != 0 and args.action != "status":
        print("root is required", file=sys.stderr)
        return 2
    if args.action == "probe":
        print(json.dumps(probe(log=print), indent=2, ensure_ascii=False))
        return 0
    if args.action == "status":
        print(json.dumps(load_state() or {}, indent=2, ensure_ascii=False))
        return 0
    if args.action == "stop":
        stop()
        return 0
    if args.action == "clean-target":
        restes, encore = clean_target(args.target, ca_pem=ca_pem())
        print(", ".join(restes) if restes else "clean")
        if encore:
            print(f"still present: {', '.join(encore)}", file=sys.stderr)
            return 1
        return 0
    try:
        etat = start(args.profile, lang=args.lang)
    except OfflineError as exc:
        print(f"offline refused: {exc.code} {exc.details}", file=sys.stderr)
        return 1
    print(f"offline: active ({manifest_label(etat['manifest'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
