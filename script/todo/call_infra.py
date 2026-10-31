#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Infrastructure d'appel (coturn, ntfy) : sonde d'un hôte, plan
d'installation, script d'installation, état de l'hôte.

Fonctions pures, stdlib seule (plus `ntfy_mobile`, stdlib seule aussi) :
le menu de `todo.py` les appelle, les scripts `sh` qu'elles construisent
sont exécutés en root par `ntfy_mobile.LocalHost` ou `SshHost`, et leur
sortie est relue par des lignes `@@NOM valeur`.

Déroulé :

1. `probe_script()` imprime ce que l'hôte porte ; `parse_probe()` en fait
   un `HostFacts`. La sonde n'écrit rien.
2. `plan_install(facts, answers, now)` refuse (`Refusal`, clé i18n et
   valeurs) ou rend un `InstallPlan` : services adoptés, diffs des fichiers
   remplacés, état à écrire, « rien à changer ».
3. `install_script(plan, stamp, check_password)` rend le script qui sauve
   les configurations adoptées, lance les installateurs et n'écrit l'état
   qu'une fois chaque service vu actif.

L'état (`STATE_PATH`, root 0600) est le seul registre de ce que l'outil a
fait sur l'hôte ; il ne porte aucun secret. Avant de toucher à un service,
le script dépose dans `PENDING_DIR` ce que l'hôte avait AVANT (paquet déjà
là ou non, configuration adoptée et sa copie) : une installation coupée
avant l'écriture de l'état laisse cette fiche, que la sonde suivante lit, et
la relance consigne l'origine vraie au lieu de celle d'un hôte à moitié
installé.
"""

import base64
import binascii
import copy
import dataclasses
import datetime
import gzip
import hashlib
import ipaddress
import json
import os
import re
import shlex
import ssl
import subprocess
import tempfile

from script.todo import ntfy_mobile as nm

STATE_PATH = "/etc/erplibre-call/state.json"
STATE_VERSION = 1
CALL_DIR = "/etc/erplibre-call"
PENDING_DIR = "/etc/erplibre-call/pending"

# Première ligne de toute configuration écrite par l'outil, la même que
# celle d'install_coturn.sh : une configuration qui ne la porte pas est
# étrangère, donc adoptée.
MARKER = "# erplibre-call: managed"

SERVICES = ("coturn", "ntfy")
TLS_MODES = ("none", "supplied")
SUPPORTED = "Debian, Ubuntu, Arch Linux"
FIREWALLS = ("ufw", "nftables", "none", "unknown")

COTURN_UNITS = {"debian": "coturn", "arch": "turnserver"}
COTURN_CONFIGS = {
    "debian": "/etc/turnserver.conf",
    "arch": "/etc/turnserver/turnserver.conf",
}
COTURN_TLS_DIR = "/etc/erplibre-call/tls"
COTURN_DB = "/var/lib/erplibre-call/turndb"

NTFY_UNIT = "ntfy"
NTFY_CONFIG = nm.DEFAULT_CONFIG
# Le compte « ntfy » doit lire la clé : elle ne peut pas vivre dans
# COTURN_TLS_DIR, réservé au groupe de coturn.
NTFY_TLS_DIR = "/etc/ntfy/tls"
NTFY_AUTH_FILE = "/var/lib/ntfy/user.db"
NTFY_HTTP_PORT = 8080
NTFY_HTTPS_PORT = 8443

# Nom du processus qui tient les ports d'un service (colonne de `ss -p`).
PROCESSES = {"coturn": "turnserver", "ntfy": "ntfy"}

_REPO = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
INSTALLERS = {
    "coturn": os.path.join(_REPO, "script", "install", "install_coturn.sh"),
    "ntfy": os.path.join(_REPO, "script", "install", "install_ntfy.sh"),
}

_DEBIAN_IDS = {"debian", "ubuntu", "linuxmint", "pop", "raspbian"}
_ARCH_IDS = {"arch", "manjaro", "endeavouros", "artix", "garuda"}
_MARKER_LINE = re.compile(r"@@([A-Z_]+)(?: (.*))?$")
# Les mêmes bornes qu'install_coturn.sh : le nom public devient le realm,
# écrit dans turnserver.conf et dans une requête SQL.
_NAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.:-]*[A-Za-z0-9])?$")
_EXTERNAL_IP = re.compile(r"^[0-9A-Fa-f:./]+$")
_STAMP = re.compile(r"^[A-Za-z0-9_-]+$")


class Refusal(Exception):
    """Refus avant toute installation : `key` est une clé i18n, `values`
    les champs de son message (`t(key).format(**values)`)."""

    def __init__(self, key, **values):
        super().__init__(key)
        self.key = key
        self.values = values


@dataclasses.dataclass(frozen=True)
class HostFacts:
    """Ce que la sonde a lu sur l'hôte.

    `coturn` et `ntfy` valent None quand ni unité ni configuration ni fiche
    en attente n'existe, sinon un dict : `unit`, `unit_found` (l'unité
    existe, donc le paquet est là), `active` (état systemd), `config`,
    `config_text` (vide sans fichier), `managed` (première ligne MARKER),
    `pending` (fiche laissée par une installation interrompue, ou None).
    """

    family: str | None
    os_id: str
    os_version: str
    systemd: bool
    hostname: str
    addresses: tuple[str, ...]
    busy_ports: tuple[tuple[str, int, str], ...]
    coturn: dict | None
    ntfy: dict | None
    firewall: str
    state: dict | None


@dataclasses.dataclass(frozen=True)
class Answers:
    """Les réponses de l'utilisateur. `ntfy_port` None : 8080 en http,
    8443 avec un certificat fourni."""

    services: frozenset[str]
    tls: str
    cert_pem: str | None
    key_pem: str | None
    public_name: str
    turn_port: int = 3478
    turns_port: int = 5349
    min_port: int = 49152
    max_port: int = 49252
    ntfy_port: int | None = None
    external_ip: str | None = None


@dataclasses.dataclass(frozen=True)
class InstallPlan:
    """`adopt` : services dont la configuration étrangère sera sauvée puis
    remplacée ; `diffs` : (chemin, diff unifié) de chaque configuration en
    place qui change ; `new_state` : l'état à écrire, sans les chemins des
    copies, qui dépendent du tampon (voir `written_state`) ; `configs` :
    {service: texte voulu} des configurations que le script écrit lui-même
    (ntfy ; celle de coturn est écrite par son installateur)."""

    answers: Answers
    adopt: tuple[str, ...]
    diffs: tuple[tuple[str, str], ...]
    nothing_to_do: bool
    new_state: dict
    configs: dict = dataclasses.field(default_factory=dict)


# --- Sonde ------------------------------------------------------------------

# `ss -Hlntup` : colonne 1 le protocole, 5 l'adresse locale (le port suit le
# dernier « : »), et `users:(("nom",...` le processus, « ? » sans lui.
_SS_AWK = (
    '{ a = $5; sub(/.*:/, "", a); p = "?";'
    ' if (match($0, /users:\\(\\("[^"]*"/))'
    " p = substr($0, RSTART + 9, RLENGTH - 10);"
    ' print "@@PORT " $1 " " a " " p }'
)
_ADDR_AWK = '{ sub(/\\/.*/, "", $4); print "@@ADDR " $4 }'
_EXEC_CONF_SED = (
    "s/^ExecStart=.*[[:space:]](-c|--conf-file)[[:space:]=]+"
    "([^[:space:]]+).*/\\2/p"
)


def probe_script(root=""):
    """Script `sh` en lecture seule qui imprime les faits de l'hôte.

    `root` préfixe chaque chemin lu ; vide sur un vrai hôte, un dossier
    temporaire dans les tests. Lignes : `@@OS <id> <version> <id_like>`,
    `@@SYSTEMD yes|no`, `@@HOSTNAME`, `@@ADDR` par adresse globale,
    `@@PORT <proto> <port> <processus>` par port en écoute, `@@COTURN
    <unité> <état> <config de l'unité>` et `@@NTFY <unité> <état> <config>`
    (« - » pour absent), `@@FILE <chemin> <base64>` par configuration
    présente, `@@PENDING <service> <base64>`, `@@FIREWALL`, `@@STATE
    <base64>`, puis `@@END` : sans lui, la sortie est tronquée.
    """
    files = " ".join(
        [
            COTURN_CONFIGS["debian"],
            COTURN_CONFIGS["arch"],
            '"$CC"',
            NTFY_CONFIG,
        ]
    )
    return "\n".join(
        [
            f"R={shlex.quote(root)}",
            # Une invite de sudo sans fin de ligne ne colle pas à la
            # première ligne de faits.
            "echo",
            'if [ -r "$R/etc/os-release" ]; then',
            '  echo "@@OS $(. "$R/etc/os-release"; printf "%s %s %s"'
            ' "${ID:-unknown}" "${VERSION_ID:-${BUILD_ID:--}}"'
            ' "${ID_LIKE:-}")"',
            "else",
            '  echo "@@OS unknown -"',
            "fi",
            'if [ -d "$R/run/systemd/system" ]; then echo "@@SYSTEMD yes";'
            ' else echo "@@SYSTEMD no"; fi',
            'echo "@@HOSTNAME $(uname -n)"',
            "if command -v ip >/dev/null 2>&1; then",
            "  ip -o addr show scope global 2>/dev/null"
            f" | awk {shlex.quote(_ADDR_AWK)}",
            "fi",
            "if command -v ss >/dev/null 2>&1; then",
            f"  ss -Hlntup 2>/dev/null | awk {shlex.quote(_SS_AWK)}",
            "fi",
            'unit_conf() { systemctl cat "$1" 2>/dev/null'
            f" | sed -n -E {shlex.quote(_EXEC_CONF_SED)} | tail -n 1; }}",
            "CU=-; CA=-; CC=-",
            "for u in coturn turnserver; do",
            '  if systemctl cat "$u" >/dev/null 2>&1; then CU=$u; break; fi',
            "done",
            'if [ "$CU" != - ]; then',
            '  CA=$(systemctl is-active "$CU" 2>/dev/null)',
            '  CC=$(unit_conf "$CU")',
            "fi",
            'echo "@@COTURN $CU ${CA:--} ${CC:--}"',
            "NU=-; NA=-",
            f"if systemctl cat {NTFY_UNIT} >/dev/null 2>&1; then",
            f"  NU={NTFY_UNIT}; NA=$(systemctl is-active {NTFY_UNIT}"
            " 2>/dev/null)",
            "fi",
            f'echo "@@NTFY $NU ${{NA:--}} {NTFY_CONFIG}"',
            f"for f in {files}; do",
            '  if [ "$f" != - ] && [ -f "$R$f" ]; then',
            '    echo "@@FILE $f $(base64 -w0 < "$R$f")"',
            "  fi",
            "done",
            "for s in " + " ".join(SERVICES) + "; do",
            f'  f="$R{PENDING_DIR}/$s.json"',
            '  if [ -f "$f" ]; then'
            ' echo "@@PENDING $s $(base64 -w0 < "$f")"; fi',
            "done",
            # Un pare-feu que l'outil ne sait pas compléter sans risque
            # (firewalld, iptables seul en DROP) se dit « unknown ».
            "FW=none",
            "if command -v ufw >/dev/null 2>&1"
            " && ufw status 2>/dev/null | grep -q '^Status: active'; then",
            "  FW=ufw",
            "elif systemctl is-active --quiet firewalld 2>/dev/null; then",
            "  FW=unknown",
            "elif command -v nft >/dev/null 2>&1 && nft list ruleset"
            " 2>/dev/null | grep -q 'hook input.*policy drop'; then",
            "  FW=nftables",
            "elif command -v iptables >/dev/null 2>&1 && iptables -S INPUT"
            " 2>/dev/null | grep -q '^-P INPUT DROP'; then",
            "  FW=unknown",
            "fi",
            'echo "@@FIREWALL $FW"',
            f'S="$R{STATE_PATH}"',
            'if [ -f "$S" ]; then echo "@@STATE $(base64 -w0 < "$S")"; fi',
            'echo "@@END"',
            "",
        ]
    )


def marker_lines(output):
    """[(NOM, valeur)] des lignes `@@NOM valeur`, dans l'ordre, répétitions
    comprises. Le nom admet `_` (`@@ADMIN_PASSWORD`), un retour chariot de
    `ssh -t` est retiré."""
    found = []
    for line in output.splitlines():
        match = _MARKER_LINE.match(line.rstrip("\r"))
        if match:
            found.append((match.group(1), match.group(2) or ""))
    return found


def os_family(os_id, id_like=""):
    """« debian », « arch » ou None, d'après ID et ID_LIKE d'os-release ;
    les mêmes listes qu'install_coturn.sh."""
    if os_id in _DEBIAN_IDS:
        return "debian"
    if os_id in _ARCH_IDS:
        return "arch"
    like = id_like.split()
    if "debian" in like or "ubuntu" in like:
        return "debian"
    if "arch" in like:
        return "arch"
    return None


def _decode(value):
    """Texte d'un base64 ; None quand il ne se décode pas."""
    try:
        return base64.b64decode(value.strip(), validate=True).decode(
            "utf-8", "replace"
        )
    except (binascii.Error, ValueError):
        return None


def _decode_json(value):
    text = _decode(value)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def is_managed(text):
    return text.split("\n", 1)[0].rstrip("\r") == MARKER


def is_foreign(text):
    """Vrai pour un fichier non vide sans MARKER en tête : la règle
    d'install_coturn.sh (`config_is_foreign`)."""
    return bool(text) and not is_managed(text)


def _service_facts(marker, default_unit, default_config, files, pending):
    unit, active, config = (marker + ["-", "-", "-"])[:3]
    unit_found = unit != "-"
    path = config if config != "-" else default_config
    text = files.get(path)
    if not unit_found and text is None and pending is None:
        return None
    return {
        "unit": unit if unit_found else default_unit,
        "unit_found": unit_found,
        "active": active if unit_found and active != "-" else "inactive",
        "config": path,
        "config_text": text or "",
        "managed": is_managed(text or ""),
        "pending": pending,
    }


def parse_probe(output):
    """`HostFacts` de la sortie de `probe_script`.

    Refusal `call_infra_probe_incomplete` sans `@@END` : une sortie
    tronquée (sudo refusé, connexion coupée) ne passe pas pour un hôte vide.
    """
    os_id, os_version, id_like = "unknown", "", ""
    systemd, hostname, firewall, state = False, "", "unknown", None
    addresses, ports, files, pending = [], [], {}, {}
    coturn_marker, ntfy_marker, complete = [], [], False
    for name, value in marker_lines(output):
        if name == "OS":
            parts = value.split()
            os_id = parts[0] if parts else "unknown"
            version = parts[1] if len(parts) > 1 else "-"
            os_version = "" if version == "-" else version
            id_like = " ".join(parts[2:])
        elif name == "SYSTEMD":
            systemd = value.strip() == "yes"
        elif name == "HOSTNAME":
            hostname = value.strip()
        elif name == "ADDR":
            address = value.strip()
            if address and address not in addresses:
                addresses.append(address)
        elif name == "PORT":
            parts = value.split(None, 2)
            if len(parts) == 3 and parts[1].isdigit():
                entry = (parts[0], int(parts[1]), parts[2].strip())
                if entry not in ports:
                    ports.append(entry)
        elif name == "COTURN":
            coturn_marker = value.split(None, 2)
        elif name == "NTFY":
            ntfy_marker = value.split(None, 2)
        elif name == "FILE":
            path, _, encoded = value.rpartition(" ")
            text = _decode(encoded)
            if path and text is not None:
                files[path] = text
        elif name == "PENDING":
            svc, _, encoded = value.partition(" ")
            record = _decode_json(encoded)
            if svc in SERVICES and record is not None:
                pending[svc] = record
        elif name == "FIREWALL":
            kind = value.strip()
            firewall = kind if kind in FIREWALLS else "unknown"
        elif name == "STATE":
            state = _decode_json(value)
        elif name == "END":
            complete = True
    if not complete:
        raise Refusal("call_infra_probe_incomplete")
    family = os_family(os_id, id_like)
    coturn = _service_facts(
        coturn_marker,
        COTURN_UNITS.get(family, COTURN_UNITS["debian"]),
        COTURN_CONFIGS.get(family, COTURN_CONFIGS["debian"]),
        files,
        pending.get("coturn"),
    )
    ntfy = _service_facts(
        ntfy_marker, NTFY_UNIT, NTFY_CONFIG, files, pending.get("ntfy")
    )
    return HostFacts(
        family=family,
        os_id=os_id,
        os_version=os_version,
        systemd=systemd,
        hostname=hostname,
        addresses=tuple(addresses),
        busy_ports=tuple(ports),
        coturn=coturn,
        ntfy=ntfy,
        firewall=firewall,
        state=state,
    )


# --- Configurations ---------------------------------------------------------


def ntfy_port(answers):
    """Port public de ntfy : `answers.ntfy_port`, sinon 8080 en http et
    8443 avec un certificat."""
    if answers.ntfy_port is not None:
        return answers.ntfy_port
    return NTFY_HTTPS_PORT if answers.tls == "supplied" else NTFY_HTTP_PORT


def ntfy_http_port(answers):
    """Port http de ntfy. Avec un certificat, http n'écoute que sur
    127.0.0.1 (la sonde de santé d'`inspect_script` le lit) : 8080, ou
    8081 quand https a pris 8080."""
    if answers.tls != "supplied":
        return ntfy_port(answers)
    return (
        NTFY_HTTP_PORT + 1
        if ntfy_port(answers) == NTFY_HTTP_PORT
        else (NTFY_HTTP_PORT)
    )


def _url_host(name):
    try:
        if ipaddress.ip_address(name).version == 6:
            return f"[{name}]"
    except ValueError:
        pass
    return name


def ntfy_base_url(answers):
    scheme = "https" if answers.tls == "supplied" else "http"
    return f"{scheme}://{_url_host(answers.public_name)}:{ntfy_port(answers)}"


def coturn_config(answers):
    """Le `turnserver.conf` qu'`install_coturn.sh` (`write_config`) écrit
    pour ces réponses, au caractère près : il sert au diff montré avant
    d'adopter et à reconnaître une configuration déjà à jour."""
    lines = [
        MARKER,
        "# Comptes dans userdb, pas ici. Ecrit par install_coturn.sh.",
        f"listening-port={answers.turn_port}",
    ]
    if answers.tls == "supplied":
        lines += [
            f"tls-listening-port={answers.turns_port}",
            f"cert={COTURN_TLS_DIR}/turn.crt",
            f"pkey={COTURN_TLS_DIR}/turn.key",
        ]
    else:
        lines += ["no-tls", "no-dtls"]
    lines += [
        f"min-port={answers.min_port}",
        f"max-port={answers.max_port}",
        "fingerprint",
        "lt-cred-mech",
        f"realm={answers.public_name}",
        f"userdb={COTURN_DB}",
        "no-cli",
        "no-multicast-peers",
    ]
    if answers.external_ip:
        lines.append(f"external-ip={answers.external_ip}")
    lines += [
        "syslog",
        "no-rfc5780",
        "no-stun-backward-compatibility",
        "response-origin-only-with-rfc5780",
    ]
    return "\n".join(lines) + "\n"


# Base d'un `server.yml` neuf, sur le modèle de celui d'install_ntfy.sh ;
# `ntfy_config` y pose ensuite les clés que l'outil gère.
_NTFY_TEMPLATE = f"""{MARKER}
# NTFY Server configuration
# Documentation: https://ntfy.sh/docs/config/

base-url: ""
listen-http: ""

cache-file: "/var/cache/ntfy/cache.db"
cache-duration: "12h"

log-level: info

attachment-cache-dir: "/var/cache/ntfy/attachments"
attachment-total-size-limit: "5G"
attachment-file-size-limit: "15M"
attachment-expiry-duration: "3h"

auth-file: "{NTFY_AUTH_FILE}"
auth-default-access: "deny-all"
"""


def _drop_key(text, key):
    """Retire les lignes actives de `key` ; les autres restent à l'octet
    près."""
    pattern = re.compile(rf"{re.escape(key)}\s*:")
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not pattern.match(line)
    )


def _has_live_line(text):
    return any(
        line.strip() and not line.lstrip().startswith("#")
        for line in text.splitlines()
    )


def ntfy_config(answers, existing=None):
    """Le `server.yml` voulu, à partir de celui en place (`existing`).

    Un fichier qui porte des réglages est édité par `_set_key` : ses autres
    lignes, dont les hôtes exemptés et le contrôle d'accès choisi, restent
    telles quelles. Sans fichier, ou avec un fichier fait de commentaires
    seulement, la base est `_NTFY_TEMPLATE`. Clés posées : MARKER en tête,
    `base-url`, `listen-http`, et avec un certificat `listen-https`,
    `cert-file`, `key-file` (retirées en http). `auth-file` et
    `auth-default-access: deny-all` sont ajoutées seulement si elles
    manquent : avec elles, install_ntfy.sh garde le fichier tel quel.
    Appliquée à son propre résultat, elle le rend inchangé.
    """
    text = (
        existing if existing and _has_live_line(existing) else (_NTFY_TEMPLATE)
    )
    if not is_managed(text):
        text = MARKER + "\n" + text
    text = nm._set_key(text, "base-url", ntfy_base_url(answers), True)
    if answers.tls == "supplied":
        http = f"127.0.0.1:{ntfy_http_port(answers)}"
        text = nm._set_key(text, "listen-http", http, True)
        text = nm._set_key(
            text, "listen-https", f":{ntfy_port(answers)}", True
        )
        text = nm._set_key(text, "cert-file", f"{NTFY_TLS_DIR}/ntfy.crt", True)
        text = nm._set_key(text, "key-file", f"{NTFY_TLS_DIR}/ntfy.key", True)
    else:
        text = nm._set_key(text, "listen-http", f":{ntfy_port(answers)}", True)
        for key in ("listen-https", "cert-file", "key-file"):
            text = _drop_key(text, key)
    keys = nm.read_yml_keys(text)
    if not keys.get("auth-file"):
        text = nm._set_key(text, "auth-file", NTFY_AUTH_FILE, True)
    if "auth-default-access" not in keys:
        text = nm._set_key(text, "auth-default-access", "deny-all", True)
    return text


# --- Contrôles --------------------------------------------------------------


def _check_answers(answers):
    """ValueError pour une réponse hors contrat (erreur de l'appelant) ;
    Refusal `call_infra_bad_value` pour une valeur que l'installateur
    refuserait après avoir commencé."""
    if not answers.services or not answers.services <= set(SERVICES):
        raise ValueError(f"services: {sorted(answers.services)}")
    if answers.tls not in TLS_MODES:
        raise ValueError(f"tls: {answers.tls}")
    if answers.tls == "supplied" and not (
        answers.cert_pem and answers.key_pem
    ):
        raise ValueError("tls supplied without certificate and key")
    if not _NAME.match(answers.public_name or ""):
        raise Refusal(
            "call_infra_bad_value",
            name="public_name",
            value=answers.public_name,
        )
    ports = {
        "turn_port": answers.turn_port,
        "turns_port": answers.turns_port,
        "min_port": answers.min_port,
        "max_port": answers.max_port,
        "ntfy_port": ntfy_port(answers),
    }
    for name, port in ports.items():
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise Refusal("call_infra_bad_value", name=name, value=port)
    if answers.min_port > answers.max_port:
        raise Refusal(
            "call_infra_bad_value",
            name="min_port",
            value=f"{answers.min_port}-{answers.max_port}",
        )
    if answers.external_ip and not _EXTERNAL_IP.match(answers.external_ip):
        raise Refusal(
            "call_infra_bad_value",
            name="external_ip",
            value=answers.external_ip,
        )
    seen = {}
    for proto, port, svc in needed_ports(answers):
        if (proto, port) in seen:
            raise Refusal(
                "call_infra_bad_value", name="ports", value=f"{port}/{proto}"
            )
        seen[(proto, port)] = svc


def needed_ports(answers):
    """[(proto, port, service)] que les services choisis vont écouter. La
    plage des relais n'y est pas : coturn passe un port pris, et `ss` y
    liste aussi les sockets clients éphémères."""
    ports = []
    if "coturn" in answers.services:
        ports += [
            ("udp", answers.turn_port, "coturn"),
            ("tcp", answers.turn_port, "coturn"),
        ]
        if answers.tls == "supplied":
            ports.append(("tcp", answers.turns_port, "coturn"))
    if "ntfy" in answers.services:
        ports.append(("tcp", ntfy_port(answers), "ntfy"))
        if answers.tls == "supplied":
            ports.append(("tcp", ntfy_http_port(answers), "ntfy"))
    return ports


def _check_ports(facts, answers):
    for proto, port, svc in needed_ports(answers):
        for busy_proto, busy_port, process in facts.busy_ports:
            if (busy_proto, busy_port) == (proto, port) and (
                process != PROCESSES[svc]
            ):
                raise Refusal(
                    "call_infra_port_busy",
                    proto=proto,
                    port=port,
                    process=process,
                )


def _certificate_facts(cert_pem):
    """(fin de validité en datetime UTC, noms DNS, adresses IP, sujet) du
    premier certificat de `cert_pem`, lus par la commande openssl."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cert.pem")
        with open(path, "w") as handle:
            handle.write(cert_pem)
        try:
            done = subprocess.run(
                [
                    "openssl",
                    "x509",
                    "-noout",
                    "-enddate",
                    "-ext",
                    "subjectAltName",
                    "-subject",
                    "-in",
                    path,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            reason = getattr(exc, "stderr", None) or str(exc)
            raise Refusal(
                "call_infra_cert_unreadable", reason=reason.strip()
            ) from None
    not_after, subject, dns, ips = None, "", [], []
    lines = done.stdout.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("notAfter="):
            seconds = ssl.cert_time_to_seconds(line.split("=", 1)[1].strip())
            not_after = datetime.datetime.fromtimestamp(
                seconds, datetime.timezone.utc
            )
        elif line.startswith("subject="):
            subject = line.split("=", 1)[1].strip()
        elif "Subject Alternative Name" in line and index + 1 < len(lines):
            for entry in lines[index + 1].split(","):
                kind, _, value = entry.strip().partition(":")
                if kind == "DNS":
                    dns.append(value.strip())
                elif kind == "IP Address":
                    ips.append(value.strip())
    if not_after is None:
        raise Refusal("call_infra_cert_unreadable", reason="notAfter")
    return not_after, dns, ips, subject


def _key_matches(cert_pem, key_pem):
    """Vrai quand la clé va avec le certificat : `load_cert_chain` les
    rapproche. Une clé chiffrée reçoit un mot de passe vide et échoue,
    sans invite au terminal ; coturn et ntfy ne pourraient pas la lire."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with tempfile.TemporaryDirectory() as tmp:
        cert = os.path.join(tmp, "cert.pem")
        key = os.path.join(tmp, "key.pem")
        with open(cert, "w") as handle:
            handle.write(cert_pem)
        with open(key, "w") as handle:
            handle.write(key_pem)
        try:
            context.load_cert_chain(cert, key, password=lambda: b"")
        except ssl.SSLError:
            return False
    return True


def _name_covered(name, dns, ips):
    """Une adresse se cherche parmi les IP du certificat ; un nom parmi ses
    noms DNS, `*.domaine` couvrant une seule étiquette. Le CN seul ne
    compte pas : les clients actuels l'ignorent."""
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        address = None
    if address is not None:
        for value in ips:
            try:
                if ipaddress.ip_address(value) == address:
                    return True
            except ValueError:
                continue
        return False
    wanted = name.lower().rstrip(".")
    for pattern in dns:
        pattern = pattern.lower().rstrip(".")
        if pattern == wanted:
            return True
        if (
            pattern.startswith("*.")
            and "." in wanted
            and wanted.split(".", 1)[1] == pattern[2:]
        ):
            return True
    return False


def _check_certificate(answers, now):
    not_after, dns, ips, subject = _certificate_facts(answers.cert_pem)
    if not _key_matches(answers.cert_pem, answers.key_pem):
        raise Refusal("call_infra_cert_key_mismatch")
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    if not_after <= now:
        raise Refusal(
            "call_infra_cert_expired", date=not_after.strftime("%Y-%m-%d")
        )
    if not _name_covered(answers.public_name, dns, ips):
        names = [f"DNS:{d}" for d in dns] + [f"IP:{i}" for i in ips]
        raise Refusal(
            "call_infra_cert_name_missing",
            name=answers.public_name,
            names=", ".join(names) or subject,
        )


# --- Plan -------------------------------------------------------------------


def _settings(svc, answers, cert_sha):
    """Ce qu'un service a reçu ; deux plans aux mêmes réglages ne changent
    rien à ce service."""
    if svc == "coturn":
        return {
            "tls": answers.tls,
            "public_name": answers.public_name,
            "turn_port": answers.turn_port,
            "turns_port": answers.turns_port,
            "min_port": answers.min_port,
            "max_port": answers.max_port,
            "external_ip": answers.external_ip or None,
            "cert_sha256": cert_sha,
        }
    return {
        "tls": answers.tls,
        "public_name": answers.public_name,
        "port": ntfy_port(answers),
        "http_port": ntfy_http_port(answers),
        "base_url": ntfy_base_url(answers),
        "cert_sha256": cert_sha,
    }


def _origin(current, prior_record):
    """Ce que l'hôte avait avant l'outil : du dernier état écrit, sinon de la
    fiche d'une installation interrompue, sinon de la sonde. `backup` vaut
    None pour une adoption de ce passage ; `written_state` le complète."""
    for source in (prior_record, (current or {}).get("pending")):
        if isinstance(source, dict) and "installed_by_tool" in source:
            return {
                "installed_by_tool": bool(source.get("installed_by_tool")),
                "adopted": bool(source.get("adopted")),
                "backup": source.get("backup"),
            }
    return {
        "installed_by_tool": not (current and current.get("unit_found")),
        "adopted": bool(current) and is_foreign(current["config_text"]),
        "backup": None,
    }


def plan_install(facts, answers, now):
    """Plan d'installation, ou Refusal avant que rien ne soit touché.

    Refus, dans l'ordre : système (`call_infra_unsupported_os`,
    `call_infra_no_systemd`), état d'une autre version
    (`call_infra_state_version`), réponses (`call_infra_bad_value`), port
    tenu par un autre processus que le service réinstallé
    (`call_infra_port_busy`), certificat fourni illisible, d'une autre clé,
    expiré ou sans le nom public (`call_infra_cert_unreadable`,
    `call_infra_cert_key_mismatch`, `call_infra_cert_expired`,
    `call_infra_cert_name_missing`).

    `nothing_to_do` : chaque service choisi est consigné avec les mêmes
    réglages, son unité est active et sa configuration sur l'hôte est déjà
    celle voulue. Les services consignés et non choisis restent dans
    l'état tels quels, comme toute clé inconnue de l'état (pare-feu...).
    """
    if facts.family is None:
        raise Refusal(
            "call_infra_unsupported_os",
            os=facts.os_id or "?",
            supported=SUPPORTED,
        )
    if not facts.systemd:
        raise Refusal("call_infra_no_systemd")
    prior = facts.state if isinstance(facts.state, dict) else {}
    if prior and prior.get("version") != STATE_VERSION:
        raise Refusal(
            "call_infra_state_version",
            found=prior.get("version"),
            expected=STATE_VERSION,
        )
    _check_answers(answers)
    _check_ports(facts, answers)
    cert_sha = None
    if answers.tls == "supplied":
        _check_certificate(answers, now)
        cert_sha = hashlib.sha256(answers.cert_pem.encode()).hexdigest()

    prior_services = prior.get("services")
    if not isinstance(prior_services, dict):
        prior_services = {}
    services = copy.deepcopy(prior_services)
    adopt, diffs, configs, unchanged = [], [], {}, bool(prior)
    for svc in SERVICES:
        if svc not in answers.services:
            continue
        current = facts.coturn if svc == "coturn" else facts.ntfy
        if svc == "coturn":
            unit = COTURN_UNITS[facts.family]
            config = COTURN_CONFIGS[facts.family]
            if current:
                unit, config = current["unit"], current["config"]
            desired = coturn_config(answers)
            tls_files = [
                f"{COTURN_TLS_DIR}/turn.crt",
                f"{COTURN_TLS_DIR}/turn.key",
            ]
        else:
            unit, config = NTFY_UNIT, NTFY_CONFIG
            desired = ntfy_config(
                answers, current["config_text"] if current else None
            )
            tls_files = [
                f"{NTFY_TLS_DIR}/ntfy.crt",
                f"{NTFY_TLS_DIR}/ntfy.key",
            ]
            configs[svc] = desired
        old_text = current["config_text"] if current else ""
        if current and is_foreign(old_text):
            adopt.append(svc)
        if old_text and old_text != desired:
            diffs.append((config, nm.unified_diff(old_text, desired, config)))
        prior_record = prior_services.get(svc)
        settings = _settings(svc, answers, cert_sha)
        unchanged = unchanged and (
            isinstance(prior_record, dict)
            and prior_record.get("settings") == settings
            and bool(current)
            and current.get("active") == "active"
            and old_text == desired
        )
        record = {"unit": unit, "config": config}
        record.update(_origin(current, prior_record))
        record["settings"] = settings
        record["tls_files"] = tls_files if answers.tls == "supplied" else []
        services[svc] = record

    stamp_now = now.isoformat(timespec="seconds")
    new_state = copy.deepcopy(prior)
    new_state.update(
        {
            "version": STATE_VERSION,
            "method": "packages",
            "mode": "development",
            "created_at": prior.get("created_at") or stamp_now,
            "updated_at": stamp_now,
            "services": services,
        }
    )
    return InstallPlan(
        answers=answers,
        adopt=tuple(adopt),
        diffs=tuple(diffs),
        nothing_to_do=unchanged,
        new_state=new_state,
        configs=configs,
    )


def written_state(plan, stamp):
    """L'état tel que `install_script` l'écrit : `new_state` où chaque
    adoption de ce passage reçoit sa copie `<config>.bak-<stamp>`."""
    state = copy.deepcopy(plan.new_state)
    for svc in plan.adopt:
        record = state["services"][svc]
        if record.get("adopted") and not record.get("backup"):
            record["backup"] = f"{record['config']}.bak-{stamp}"
    return state


def state_answers(state):
    """Les réponses d'un état écrit, pour préremplir une relance ; None
    pour un état absent, d'une autre version ou sans service. Le
    certificat et la clé n'y sont pas : l'état ne garde que l'empreinte."""
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        return None
    services = state.get("services")
    if not isinstance(services, dict):
        return None
    names = [s for s in SERVICES if isinstance(services.get(s), dict)]
    if not names:
        return None
    coturn, ntfy = (
        (services[s].get("settings") or {}) if s in names else {}
        for s in SERVICES
    )
    first = coturn or ntfy
    try:
        return Answers(
            services=frozenset(names),
            tls=first.get("tls", "none"),
            cert_pem=None,
            key_pem=None,
            public_name=first.get("public_name", ""),
            turn_port=int(coturn.get("turn_port", 3478)),
            turns_port=int(coturn.get("turns_port", 5349)),
            min_port=int(coturn.get("min_port", 49152)),
            max_port=int(coturn.get("max_port", 49252)),
            ntfy_port=int(ntfy["port"]) if ntfy.get("port") else None,
            external_ip=coturn.get("external_ip") or None,
        )
    except (TypeError, ValueError):
        return None


# --- Script d'installation --------------------------------------------------


def _b64(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.b64encode(data).decode("ascii")


def _host(path):
    """Chemin de l'hôte pour le script : préfixé de `$R`, entre guillemets."""
    return '"$R"' + shlex.quote(path)


def _installer_payload(svc):
    """Installateur lu sur le disque, compressé (mtime 0 : même texte, même
    charge) puis en base64 : le script entier tient dans un argument."""
    with open(INSTALLERS[svc], "rb") as handle:
        return _b64(gzip.compress(handle.read(), mtime=0))


def _decode_to(payload, target, gunzip=False):
    """Ligne `sh` qui écrit le base64 `payload` dans `target` (déjà cité
    pour le shell). `printf` est intégré au shell : la charge ne passe dans
    l'argv d'aucun programme."""
    unzip = " | gzip -dc" if gunzip else ""
    return f"printf %s {shlex.quote(payload)} | base64 -d{unzip} > {target}"


def _export(variables, raw=None):
    """Lignes d'un sous-shell qui exportent `variables` (valeurs citées)
    et `raw` (expressions du shell, résolues sur l'hôte)."""
    lines = [
        f"  {name}={shlex.quote(str(value))}"
        for name, value in variables.items()
    ]
    lines += [f"  {name}={value}" for name, value in (raw or {}).items()]
    lines.append("  export " + " ".join([*variables, *(raw or {})]))
    return lines


def _place(payload, path, mode, group=None):
    """Écrit un fichier de l'hôte par `.new` puis renommage, droits posés
    avant le renommage : le fichier n'existe jamais avec d'autres droits."""
    new, final = _host(path + ".new"), _host(path)
    owner = f" && chown root:{group} {new}" if group else ""
    return (
        _decode_to(payload, new) + owner + f" && chmod {mode} {new}"
        f" && mv -f {new} {final}"
    )


def _coturn_block(plan, check_password):
    answers = plan.answers
    lines = [
        "# coturn",
        _decode_to(
            _installer_payload("coturn"), '"$D/install_coturn.sh"', gunzip=True
        )
        + " || fail payload-coturn",
    ]
    variables = {
        "TURN_REALM": answers.public_name,
        "TURN_PORT": answers.turn_port,
        "TURN_TLS_PORT": answers.turns_port,
        "TURN_MIN_PORT": answers.min_port,
        "TURN_MAX_PORT": answers.max_port,
    }
    raw = {}
    if answers.external_ip:
        variables["TURN_EXTERNAL_IP"] = answers.external_ip
    if answers.tls == "supplied":
        # L'installateur copie ces fichiers dans COTURN_TLS_DIR ; ici ils ne
        # vivent que dans le dossier de travail, effacé en sortie.
        lines += [
            _decode_to(_b64(answers.cert_pem), '"$D/turn.crt"')
            + " || fail cert-coturn",
            _decode_to(_b64(answers.key_pem), '"$D/turn.key"')
            + " || fail cert-coturn",
        ]
        raw = {
            "TURN_CERT_FILE": '"$D/turn.crt"',
            "TURN_KEY_FILE": '"$D/turn.key"',
        }
    if "coturn" in plan.adopt:
        variables["TURN_GARDER_CONFIG"] = "1"
    # Le mot de passe passe du base64 à une variable du shell, puis à
    # l'environnement de l'installateur, qui le retire aussitôt du sien.
    raw["TURN_CHECK_PASSWORD"] = (
        f"$(printf %s {shlex.quote(_b64(check_password))} | base64 -d)"
    )
    lines += ["(", "  umask 022"] + _export(variables, raw)
    lines += ['  exec bash "$D/install_coturn.sh"', ")", "RC_coturn=$?"]
    return lines


def _ntfy_block(plan):
    answers = plan.answers
    config = _host(NTFY_CONFIG)
    new = _host(NTFY_CONFIG + ".erplibre-new")
    lines = [
        "# ntfy",
        _decode_to(
            _installer_payload("ntfy"), '"$D/install_ntfy.sh"', gunzip=True
        )
        + " || fail payload-ntfy",
    ]
    variables = {
        "NTFY_PORT": ntfy_http_port(answers),
        "NTFY_BASE_URL": ntfy_base_url(answers),
        "NTFY_NON_INTERACTIVE": 1,
    }
    if answers.tls == "supplied":
        tls_dir = _host(NTFY_TLS_DIR)
        # Le groupe « ntfy » doit exister avant le paquet pour que la clé
        # lui soit lisible : le compte est créé comme install_ntfy.sh le
        # crée, et le paquet garde un compte déjà là.
        lines += [
            "id ntfy >/dev/null 2>&1 || useradd --system --no-create-home"
            " --shell /usr/sbin/nologin ntfy || fail ntfy-user",
            f"mkdir -p {tls_dir} && chown root:ntfy {tls_dir}"
            f" && chmod 0750 {tls_dir} || fail ntfy-tls",
            _place(_b64(answers.cert_pem), f"{NTFY_TLS_DIR}/ntfy.crt", "0644")
            + " || fail ntfy-tls",
            _place(
                _b64(answers.key_pem),
                f"{NTFY_TLS_DIR}/ntfy.key",
                "0640",
                group="ntfy",
            )
            + " || fail ntfy-tls",
        ]
        variables["NTFY_HTTPS_PORT"] = ntfy_port(answers)
        variables["NTFY_CERT_FILE"] = f"{NTFY_TLS_DIR}/ntfy.crt"
        variables["NTFY_KEY_FILE"] = f"{NTFY_TLS_DIR}/ntfy.key"
    else:
        # Comme install_coturn.sh : sans certificat, l'ancienne copie part,
        # et l'état ne consigne plus aucun fichier TLS pour ntfy.
        lines.append(
            f"rm -f {_host(NTFY_TLS_DIR + '/ntfy.crt')}"
            f" {_host(NTFY_TLS_DIR + '/ntfy.key')} || fail ntfy-tls"
        )
    # La configuration voulue est en place AVANT l'installateur : elle
    # déclare son contrôle d'accès, install_ntfy.sh la garde telle quelle.
    # Un fichier en place garde son propriétaire et ses droits.
    lines += [
        f"mkdir -p {_host(os.path.dirname(NTFY_CONFIG))} || fail ntfy-config",
        _decode_to(_b64(plan.configs["ntfy"]), new) + " || fail ntfy-config",
        f"if [ -f {config} ]; then",
        f"  chown --reference={config} {new}"
        f" && chmod --reference={config} {new} || fail ntfy-config",
        "else",
        f"  chmod 0644 {new} || fail ntfy-config",
        "fi",
        f"mv -f {new} {config} || fail ntfy-config",
        "(",
        "  umask 022",
    ]
    lines += _export(variables)
    lines += ['  exec bash "$D/install_ntfy.sh"', ")", "RC_ntfy=$?"]
    return lines


def install_script(plan, stamp, check_password, root=""):
    """Script `sh` d'installation, lancé en root sur l'hôte.

    Ordre : fiche de l'origine de chaque service dans `PENDING_DIR` (gardée
    si elle existe déjà), copie `cp -p <config> <config>.bak-<stamp>` de chaque
    configuration adoptée, installateurs décodés du base64 et lancés avec
    leurs variables (umask 022 : ce qu'ils écrivent doit rester lisible des
    comptes de service), une ligne `@@ACTIVE <service> <état>` par service,
    et SEULEMENT si chaque installateur a réussi et chaque unité est
    active : l'état écrit en `.new` (0600) puis renommé, et les fiches
    retirées. Dernière ligne : `@@SAVED yes`, ou `@@SAVED no` et un code non
    nul. Une coupure en cours de route laisse l'ancien état (ou aucun) et
    les fiches : la relance repart de là.

    `check_password` (le compte de contrôle de coturn), le certificat et la
    clé ne figurent qu'en base64 dans le texte. `root` préfixe chaque
    chemin de l'hôte (tests).
    """
    if not _STAMP.match(stamp or ""):
        raise ValueError(f"stamp: {stamp!r}")
    services = [s for s in SERVICES if s in plan.answers.services]
    if "coturn" in services and not check_password:
        raise ValueError("check_password is required for coturn")
    state = written_state(plan, stamp)
    lines = [
        "set -u",
        f"R={shlex.quote(root)}",
        f'CALL="$R"{shlex.quote(CALL_DIR)}',
        f'STATE="$R"{shlex.quote(STATE_PATH)}',
        f'PENDING="$R"{shlex.quote(PENDING_DIR)}',
        "umask 077",
        'fail() { echo "@@FAILED $1"; echo "@@SAVED no"; exit 1; }',
        "D=$(mktemp -d) || fail workdir",
        "trap 'rm -rf \"$D\"' EXIT",
        "trap 'exit 129' HUP INT TERM",
        # Le dossier reste traversable : coturn y lit son certificat.
        'mkdir -p "$PENDING" && chmod 0755 "$CALL" && chmod 0700 "$PENDING"'
        " || fail pending",
    ]
    for svc in services:
        record = state["services"][svc]
        origin = {
            k: record[k]
            for k in ("installed_by_tool", "adopted", "backup", "config")
        }
        pending = f'"$PENDING/{svc}.json"'
        lines += [
            f"if [ ! -e {pending} ]; then",
            "  "
            + _decode_to(_b64(json.dumps(origin)), f'"$PENDING/{svc}.new"')
            + f' && mv -f "$PENDING/{svc}.new" {pending} || fail pending',
            "fi",
        ]
        if svc in plan.adopt:
            backup = f"{record['config']}.bak-{stamp}"
            lines.append(
                f"cp -p {_host(record['config'])} {_host(backup)}"
                f" || fail backup-{svc}"
            )
    for svc in services:
        if svc == "coturn":
            lines += _coturn_block(plan, check_password)
        else:
            lines += _ntfy_block(plan)
    lines.append("OK=1")
    for svc in services:
        unit = shlex.quote(state["services"][svc]["unit"])
        lines += [
            f'[ "$RC_{svc}" = 0 ] || OK=0',
            f"A=$(systemctl is-active {unit} 2>/dev/null)",
            f'echo "@@ACTIVE {svc} ${{A:-unknown}}"',
            '[ "$A" = active ] || OK=0',
        ]
    lines += [
        'if [ "$OK" = 1 ]; then',
        "  "
        + _decode_to(
            _b64(json.dumps(state, indent=2, sort_keys=True)), '"$STATE.new"'
        )
        + " || fail state",
        '  chown root:root "$STATE.new"; chmod 0600 "$STATE.new"',
        '  mv -f "$STATE.new" "$STATE" || fail state',
    ]
    lines += [f'  rm -f "$PENDING/{svc}.json"' for svc in services]
    lines += [
        '  echo "@@SAVED yes"',
        "else",
        '  echo "@@SAVED no"',
        "  exit 1",
        "fi",
        "",
    ]
    return "\n".join(lines)
