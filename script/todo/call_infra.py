#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Infrastructure d'appel (coturn, ntfy) : sonde d'un hôte, plan
d'installation, script d'installation, état de l'hôte, vérification et
désinstallation.

Fonctions pures, stdlib seule (plus `ntfy_mobile` et `turn_client`, stdlib
seule aussi) :
le menu de `todo.py` les appelle, les scripts `sh` qu'elles construisent
sont exécutés en root par `ntfy_mobile.LocalHost` ou `SshHost`, et leur
sortie est relue par des lignes `@@NOM valeur`.

Déroulé :

1. `probe_script()` imprime ce que l'hôte porte ; `parse_probe()` en fait
   un `HostFacts`. La sonde n'écrit rien.
2. `plan_install(facts, answers, now)` refuse (`Refusal`, clé i18n et
   valeurs) ou rend un `InstallPlan` : services adoptés, diffs des fichiers
   remplacés, état à écrire, « rien à changer ».
3. `install_script(plan, stamp)` rend le script qui sauve les
   configurations adoptées, lance les installateurs et n'écrit l'état
   qu'une fois chaque service vu actif.
4. `check_remote_script()` lit l'hôte sans rien écrire ; `check_local()`
   en tire le verdict depuis la machine qui lance `todo.py` : allocations
   TURN réelles, santé de ntfy, certificat, pare-feu, unités.
5. `uninstall_script(state, remove_data, stamp)` défait ce que l'état
   consigne et n'efface l'état qu'en dernier, une fois tout réussi.

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
import http.client
import ipaddress
import json
import os
import re
import shlex
import ssl
import subprocess
import tempfile

from script.todo import ntfy_mobile as nm
from script.todo import turn_client

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
# Le compte administrateur qu'install_ntfy.sh crée quand il manque ; il
# imprime alors `@@ADMIN_PASSWORD`, une seule fois.
NTFY_ADMIN_USER = "erplibre"

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
# Locale des scripts lancés sur l'hôte : ufw traduit ses messages
# (« Status: active », « Skipping »), que les scripts lisent en anglais.
# sudo garde LANG, LANGUAGE et LC_* de l'appelant, et ssh ne les transmet
# que si l'hôte les accepte ; gettext lit LANGUAGE avant LC_ALL.
_C_LOCALE = "LC_ALL=C; export LC_ALL; unset LANGUAGE"
# Réponse de `systemctl is-enabled` : enabled, disabled, static, masked...
_UNIT_STATE = re.compile(r"^[a-z-]+$")


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
    existe, donc le paquet est là), `active` (état systemd), `enabled`
    (réponse de `systemctl is-enabled`, None sans elle), `config`,
    `config_text` (vide sans fichier), `managed` (première ligne MARKER),
    `pending` (fiche laissée par une installation interrompue, ou None).

    `nft_chains` : (famille, table, chaîne) de chaque chaîne de base
    nftables accrochée à « input » en politique drop ; l'outil n'ajoute ses
    règles que quand il y en a exactement une.

    `firewall_pending` : ((ufw|nftables, Rule), ...) des règles que
    `firewall_script` a posées ou gardées et qu'aucun état écrit ne
    consigne encore (fiche `PENDING_DIR/firewall`).
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
    nft_chains: tuple[tuple[str, str, str], ...] = ()
    firewall_pending: tuple = ()


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
    place qui change, valeurs secrètes masquées (`redact_secrets`) ; `new_state` : l'état à écrire, sans les chemins des
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
# `nft list ruleset` : « table <famille> <nom> { » ouvre une table,
# « chain <nom> { » une chaîne ; la ligne « type ... hook input ... policy
# drop; » fait d'elle une chaîne de base qui rejette ce qu'elle n'accepte
# pas. Le pont (« bridge ») a aussi un crochet input, qui ne voit pas le
# trafic destiné à l'hôte : seuls ip, ip6 et inet comptent. Imprime
# « famille table chaîne », suivi d'un 4e champ « iptables » pour une
# chaîne « INPUT » en ip ou ip6 : c'est celle qu'iptables-nft crée, dans
# une table qu'iptables-persistent recharge en entier, ce qui effacerait
# une règle nft native.
_NFT_CHAINS_AWK = (
    '/^table / { f = $2; t = $3; c = "" }'
    " /^[ \\t]*chain / { c = $2 }"
    " /hook input/ && /policy drop/"
    ' { if (f == "ip" || f == "ip6" || f == "inet")'
    ' print f, t, c ((f != "inet" && c == "INPUT") ? " iptables" : "") }'
)
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
    (« - » pour absent), `@@ENABLED <service> <is-enabled>` par unité
    trouvée, `@@FILE <chemin> <base64>` par configuration
    présente, `@@PENDING <service> <base64>`, `@@FIREWALL`, `@@NFT_INPUT
    <famille> <table> <chaîne>` par chaîne input en drop (nftables
    seulement), `@@STATE <base64>`, `@@FIREWALL_PENDING <ufw|nftables>
    <proto> <port> <service>` par règle posée que l'état ne consigne pas
    encore, puis `@@END` : sans lui, la sortie est tronquée.
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
            _C_LOCALE,
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
            'if [ "$CU" != - ]; then',
            '  echo "@@ENABLED coturn $(systemctl is-enabled "$CU" 2>/dev/null)"',
            "fi",
            "NU=-; NA=-",
            f"if systemctl cat {NTFY_UNIT} >/dev/null 2>&1; then",
            f"  NU={NTFY_UNIT}; NA=$(systemctl is-active {NTFY_UNIT}"
            " 2>/dev/null)",
            "fi",
            f'echo "@@NTFY $NU ${{NA:--}} {NTFY_CONFIG}"',
            'if [ "$NU" != - ]; then',
            f'  echo "@@ENABLED ntfy $(systemctl is-enabled {NTFY_UNIT}'
            ' 2>/dev/null)"',
            "fi",
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
            # (firewalld, iptables en DROP, y compris par iptables-nft) se
            # dit « unknown ».
            "NI=",
            "command -v nft >/dev/null 2>&1 && NI=$(nft list ruleset"
            f" 2>/dev/null | awk {shlex.quote(_NFT_CHAINS_AWK)})",
            "FW=none",
            "if command -v ufw >/dev/null 2>&1"
            " && ufw status 2>/dev/null | grep -q '^Status: active'; then",
            "  FW=ufw",
            "elif systemctl is-active --quiet firewalld 2>/dev/null; then",
            "  FW=unknown",
            'elif [ -n "$NI" ]; then',
            '  if printf "%s\\n" "$NI" | awk \'$4 != "" { x = 1 }'
            " END { exit !x }'; then FW=unknown; else FW=nftables; fi",
            "elif command -v iptables >/dev/null 2>&1 && iptables -S INPUT"
            " 2>/dev/null | grep -q '^-P INPUT DROP'; then",
            "  FW=unknown",
            "fi",
            'echo "@@FIREWALL $FW"',
            'if [ "$FW" = nftables ]; then',
            '  printf "%s\\n" "$NI" | sed \'s/^/@@NFT_INPUT /\'',
            "fi",
            f'S="$R{STATE_PATH}"',
            'if [ -f "$S" ]; then echo "@@STATE $(base64 -w0 < "$S")"; fi',
            f'FP="$R{PENDING_DIR}/firewall"',
            'if [ -f "$FP" ]; then sed "s/^/@@FIREWALL_PENDING /" "$FP"; fi',
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


def _service_facts(
    marker, default_unit, default_config, files, pending, enabled=None
):
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
        "enabled": enabled if unit_found and enabled else None,
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
    addresses, ports, files, pending, chains = [], [], {}, {}, []
    firewall_pending = []
    coturn_marker, ntfy_marker, complete, enabled = [], [], False, {}
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
        elif name == "ENABLED":
            svc, _, current = value.partition(" ")
            if svc in SERVICES and _UNIT_STATE.match(current.strip()):
                enabled[svc] = current.strip()
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
        elif name == "NFT_INPUT":
            chain = tuple(value.split())
            if _valid_chain(chain) and chain not in chains:
                chains.append(chain)
        elif name == "STATE":
            state = _decode_json(value)
        elif name == "FIREWALL_PENDING":
            entry = _pending_rule(value)
            if entry is not None and entry not in firewall_pending:
                firewall_pending.append(entry)
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
        enabled.get("coturn"),
    )
    ntfy = _service_facts(
        ntfy_marker,
        NTFY_UNIT,
        NTFY_CONFIG,
        files,
        pending.get("ntfy"),
        enabled.get("ntfy"),
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
        nft_chains=tuple(chains),
        firewall_pending=tuple(firewall_pending),
    )


def _pending_rule(value):
    """(ufw|nftables, Rule) d'une ligne « kind proto port service » de la
    fiche du pare-feu, None hors format ou sur le port de ssh."""
    parts = value.split()
    if len(parts) != 4 or parts[0] not in ("ufw", "nftables"):
        return None
    found = Rule(*parts[1:])
    try:
        _check_rule(found)
    except ValueError:
        return None
    return parts[0], found


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
    pour ces réponses dans un plan de développement (TURN_ALLOW_PRIVATE=1,
    aucune ligne `denied-peer-ip`), au caractère près : il sert au diff
    montré avant d'adopter et à reconnaître une configuration déjà à
    jour."""
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


# Clés dont la valeur est un secret, dans turnserver.conf (`clé=valeur`,
# `clé valeur`) et server.yml (`clé: valeur`) : static-auth-secret,
# cli-password, pkey-pwd, smtp-sender-pass, web-push-private-key,
# upstream-access-token, et les connexions aux bases de coturn, qui portent
# un mot de passe. `user=<nom>:<mot de passe>` garde son nom ; les listes
# auth-users et auth-tokens de ntfy perdent chacun de leurs éléments, en
# tirets comme entre crochets, sur une ligne ou sur plusieurs. En dernier
# filet, toute empreinte bcrypt (`$2a$`, `$2b$`, `$2y$`) et tout jeton ntfy
# (`tk_…`) sont masqués où qu'ils soient, commentaires compris.
_SECRET_KEY = re.compile(
    r"secret|pass|pwd|token|private-key|^(psql|mysql|mongo|redis)-", re.I
)
_SECRET_LISTS = ("auth-users", "auth-tokens")
_CONF_LINE = re.compile(r"^(\s*)([A-Za-z0-9_.-]+)(\s*[:=]\s*|\s+)(.*)$")
_LIST_ITEM = re.compile(r"^(\s*-\s*)\S")
_BCRYPT = re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]+")
_NTFY_TOKEN = re.compile(r"\btk_[A-Za-z0-9]+")


def _redact_flow_item(body):
    """(ligne masquée, liste encore ouverte) pour une ligne d'une liste
    entre crochets ouverte plus haut ; « ] » la ferme."""
    stripped = body.strip()
    if stripped.startswith("]"):
        return body, False
    indent = body[: len(body) - len(body.lstrip())]
    closes = "]" in stripped
    return indent + ("***]" if closes else "***"), not closes


def redact_secrets(text):
    """`text` dont chaque valeur secrète devient « *** », guillemets gardés ;
    les autres lignes restent à l'octet près. Sert au diff montré à
    l'écran, jamais au fichier écrit."""
    lines, in_list, in_flow = [], False, False
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        end = line[len(body) :]
        if in_flow:
            body, in_flow = _redact_flow_item(body)
            lines.append(body + end)
            continue
        if in_list:
            item = _LIST_ITEM.match(body)
            if item:
                lines.append(item.group(1) + "***" + end)
                continue
            in_list = False
        match = _CONF_LINE.match(body)
        if match and not body.lstrip().startswith("#"):
            indent, key, sep, value = match.groups()
            bare = value.strip()
            secret = key in _SECRET_LISTS or _SECRET_KEY.search(key)
            if key in _SECRET_LISTS and not bare:
                in_list = True
            elif secret and bare.startswith("["):
                in_flow = not bare.endswith("]")
                shown = (
                    "[" if bare == "[" else "[***" + ("" if in_flow else "]")
                )
                body = f"{indent}{key}{sep}{shown}"
            elif key == "user" and ":" in bare:
                body = f"{indent}{key}{sep}{bare.split(':', 1)[0]}:***"
            elif secret and bare:
                quote = bare[0] if bare[0] in "\"'" else ""
                body = f"{indent}{key}{sep}{quote}***{quote}"
        body = _NTFY_TOKEN.sub("tk_***", _BCRYPT.sub("***", body))
        lines.append(body + end)
    return "".join(lines)


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
    firewall_rules(answers)
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
    None pour une adoption de ce passage ; `written_state` le complète.

    `was_active` (l'unité tournait) et `was_enabled` (sa réponse à
    `systemctl is-enabled`) disent ce que la désinstallation d'un service
    adopté remet : les installateurs activent et démarrent toujours
    l'unité. None quand l'unité n'existait pas, ou pour un état écrit
    avant que l'outil ne les consigne."""
    for source in (prior_record, (current or {}).get("pending")):
        if isinstance(source, dict) and "installed_by_tool" in source:
            was_active = source.get("was_active")
            was_enabled = source.get("was_enabled")
            # `admin_added` (voir `mark_admin_added`) ne vit que dans l'état.
            admin = (
                {"admin_added": True}
                if source.get("admin_added") is True
                else {}
            )
            return admin | {
                "installed_by_tool": bool(source.get("installed_by_tool")),
                "adopted": bool(source.get("adopted")),
                "backup": source.get("backup"),
                "was_active": (
                    was_active if isinstance(was_active, bool) else None
                ),
                "was_enabled": (
                    was_enabled
                    if isinstance(was_enabled, str)
                    and _UNIT_STATE.match(was_enabled)
                    else None
                ),
            }
    found = bool(current and current.get("unit_found"))
    return {
        "installed_by_tool": not found,
        "adopted": bool(current) and is_foreign(current["config_text"]),
        "backup": None,
        "was_active": current.get("active") == "active" if found else None,
        "was_enabled": current.get("enabled") if found else None,
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
            shown = (redact_secrets(old_text), redact_secrets(desired))
            diffs.append((config, nm.unified_diff(*shown, config)))
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


def _is_backup_of(config, backup):
    """Vrai pour une copie `<config>.bak-<tampon>` : le chemin vient de
    l'hôte et finit dans un script lancé en root."""
    return (
        isinstance(config, str)
        and isinstance(backup, str)
        and backup.startswith(config + ".bak-")
        and bool(_STAMP.match(backup[len(config) + 5 :]))
    )


def written_state(plan, stamp):
    """L'état tel que `install_script` l'écrit : `new_state` où chaque
    adoption de ce passage reçoit sa copie `<config>.bak-<stamp>`, sauf
    celle qu'une fiche ou un état précédent nomme déjà (un passage coupé) :
    `install_script` copie vers ce chemin-là, le même qui est consigné."""
    state = copy.deepcopy(plan.new_state)
    for svc in plan.adopt:
        record = state["services"][svc]
        if record.get("adopted") and not _is_backup_of(
            record["config"], record.get("backup")
        ):
            record["backup"] = f"{record['config']}.bak-{stamp}"
    return state


def mark_admin_added(state, output):
    """Copie de `state` dont le ntfy adopté porte `admin_added: true` quand
    `output`, celle du script d'installation, montre que l'installateur y a
    créé NTFY_ADMIN_USER (`@@ADMIN_PASSWORD`) : la base des comptes d'un ntfy
    adopté reste à la désinstallation, ce compte-là doit en partir.
    `state` tel quel sinon."""
    created = any(
        name == "ADMIN_PASSWORD" and value.strip()
        for name, value in marker_lines(output or "")
    )
    services = state.get("services") if isinstance(state, dict) else None
    record = services.get("ntfy") if isinstance(services, dict) else None
    if (
        not created
        or not isinstance(record, dict)
        or not record.get("adopted")
    ):
        return state
    marked = copy.deepcopy(state)
    marked["services"]["ntfy"]["admin_added"] = True
    return marked


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
    # Des réglages qui ne sont pas un dict (état abîmé) comptent pour
    # absents : les valeurs par défaut les remplacent.
    coturn, ntfy = (
        services[s].get("settings") if s in names else {} for s in SERVICES
    )
    coturn = coturn if isinstance(coturn, dict) else {}
    ntfy = ntfy if isinstance(ntfy, dict) else {}
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
    charge) puis en base64 : le script entier tient encore dans un argument
    de `sh -c`, la forme où le test long le passe."""
    with open(INSTALLERS[svc], "rb") as handle:
        return _b64(gzip.compress(handle.read(), mtime=0))


def _decode_to(payload, target, gunzip=False):
    """Ligne `sh` qui écrit le base64 `payload` dans `target` (déjà cité
    pour le shell). `printf` est intégré au shell : la charge ne passe dans
    l'argv d'aucun programme que le script lance. Le texte du script, lui,
    ne reste hors de tout argv que lancé depuis un fichier, comme le font
    `ntfy_mobile.LocalHost` et `SshHost` pour un script root."""
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


def _coturn_block(plan):
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
    # Un plan de développement relaie aussi vers les plages privées (réseau
    # local, boucle locale) : sans TURN_ALLOW_PRIVATE=1, l'installateur les
    # refuse, et la configuration écrite ne serait plus celle que
    # `coturn_config` décrit.
    if plan.new_state.get("mode") == "development":
        variables["TURN_ALLOW_PRIVATE"] = "1"
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
    # Sans TURN_CHECK_PASSWORD, install_coturn.sh tire le mot de passe du
    # compte de contrôle sur l'hôte et n'en garde que la clé, que la
    # vérification relit : aucun secret de ce compte ne part d'ici.
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
    # Le compte « ntfy » doit traverser le dossier pour lire server.yml ;
    # sans lui, ntfy démarre sur ses valeurs par défaut, sans contrôle
    # d'accès. Créé ici en 0755 malgré l'umask 077 du script ; un dossier
    # déjà là garde ses droits, et ni dpkg ni pacman ne les changent.
    lines.append(
        f"[ -d {_host(os.path.dirname(NTFY_CONFIG))} ]"
        f" || install -d -m 0755 {_host(os.path.dirname(NTFY_CONFIG))}"
        " || fail ntfy-config"
    )
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


def _state_write_lines(state):
    """Lignes `sh` qui écrivent `state` dans "$STATE" : `.new` en root
    0600 puis renommage, l'ancien état reste entier jusqu'au `mv`. Une
    fonction `fail` doit exister."""
    return [
        _decode_to(
            _b64(json.dumps(state, indent=2, sort_keys=True)), '"$STATE.new"'
        )
        + " || fail state",
        'chown root:root "$STATE.new"; chmod 0600 "$STATE.new"',
        'mv -f "$STATE.new" "$STATE" || fail state',
    ]


def install_script(plan, stamp, root=""):
    """Script `sh` d'installation, lancé en root sur l'hôte.

    Ordre : fiche de l'origine de chaque service dans `PENDING_DIR` (gardée
    si elle existe déjà), copie `cp -p` de chaque configuration adoptée
    vers le chemin que consigne `written_state` (quand ce fichier existe
    déjà, seule une configuration qui en diffère est copiée, sous
    `<config>.bak-<stamp>`), installateurs décodés du base64 et lancés avec
    leurs variables (umask 022 : ce qu'ils écrivent doit rester lisible des
    comptes de service), une ligne `@@ACTIVE <service> <état>` par service,
    et SEULEMENT si chaque installateur a réussi et chaque unité est
    active : l'état écrit en `.new` (0600) puis renommé, et les fiches
    retirées. Dernière ligne : `@@SAVED yes`, ou `@@SAVED no` et un code non
    nul. Une coupure en cours de route laisse l'ancien état (ou aucun) et
    les fiches : la relance repart de là.

    Le mot de passe du compte de contrôle de coturn n'y figure pas :
    l'installateur le tire sur l'hôte. Le certificat et la clé n'y
    figurent qu'en base64. `root` préfixe chaque chemin de l'hôte (tests).
    """
    if not _STAMP.match(stamp or ""):
        raise ValueError(f"stamp: {stamp!r}")
    services = [s for s in SERVICES if s in plan.answers.services]
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
            for k in (
                "installed_by_tool",
                "adopted",
                "backup",
                "config",
                "was_active",
                "was_enabled",
            )
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
            backup = record.get("backup")
            if not _is_backup_of(record["config"], backup):
                backup = f"{record['config']}.bak-{stamp}"
            # La copie consignée existe déjà quand un passage coupé l'a faite
            # : elle garde l'original. Une configuration étrangère qui en
            # diffère (refaite à la main depuis) est copiée à part, sous le
            # tampon de ce passage, plutôt que perdue.
            config, extra = record["config"], f"{record['config']}.bak-{stamp}"
            lines += [
                f"if [ ! -e {_host(backup)} ]; then",
                f"  cp -p {_host(config)} {_host(backup)} || fail backup-{svc}",
                f"elif ! cmp -s {_host(config)} {_host(backup)}; then",
                f"  cp -p {_host(config)} {_host(extra)} || fail backup-{svc}",
                "fi",
            ]
            # Une configuration de coturn sans paquet (installed_by_tool) :
            # pacman refuse un paquet dont un fichier existe déjà sans
            # propriétaire. Copiée, elle quitte sa place ; l'installateur
            # pose celle du paquet puis la remplace (TURN_GARDER_CONFIG=1).
            if svc == "coturn" and record["installed_by_tool"]:
                lines.append(f"rm -f {_host(config)} || fail backup-{svc}")
    for svc in services:
        if svc == "coturn":
            lines += _coturn_block(plan)
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
    lines.append('if [ "$OK" = 1 ]; then')
    lines += ["  " + line for line in _state_write_lines(state)]
    lines += [
        *[f'  rm -f "$PENDING/{svc}.json"' for svc in services],
        '  echo "@@SAVED yes"',
        "else",
        '  echo "@@SAVED no"',
        "  exit 1",
        "fi",
        "",
    ]
    return "\n".join(lines)


# --- Pare-feu ---------------------------------------------------------------

# Port de ssh : aucune règle ne le couvre, ni à l'ouverture ni au retrait ;
# retirer « 22/tcp » de ufw enlèverait la règle de l'administrateur.
SSH_PORT = 22
FIREWALL_COMMENT = "erplibre-call"
NFT_PERSIST_DIR = "/etc/nftables.d"
NFT_PERSIST_FILE = "/etc/nftables.d/erplibre-call.nft"
NFT_CONF = "/etc/nftables.conf"
FIREWALL_ACTIONS = ("allow", "delete")

_RULE_PORT = re.compile(r"^([0-9]{1,5})(?::([0-9]{1,5}))?$")
_NFT_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
# Inclusion qui charge NFT_PERSIST_FILE au démarrage : « * » ou « *.nft ».
_NFT_INCLUDE_ERE = (
    '^[[:space:]]*include[[:space:]]+"/etc/nftables\\.d/\\*(\\.nft)?"'
)
# `nft -a list ruleset` : chaque règle finit par « # handle <n> ». Imprime
# « famille table chaîne handle » des règles qui contiennent `m` (protocole,
# port, espace) et `k` (le commentaire de l'outil pour ce service).
_NFT_HANDLES_AWK = (
    "/^table / { f = $2; t = $3 }"
    " /^[ \\t]*chain / { c = $2 }"
    " index($0, m) && index($0, k) && match($0, /# handle [0-9]+$/)"
    " { print f, t, c, substr($0, RSTART + 9) }"
)


@dataclasses.dataclass(frozen=True)
class Rule:
    """Une ouverture : `proto` « tcp » ou « udp », `port` « 3478 » ou une
    plage « 49152:49252 », `service` celui qui l'écoute."""

    proto: str
    port: str
    service: str


def _port_bounds(port):
    """(bas, haut) de « 3478 » ou « 49152:49252 », None hors format."""
    match = _RULE_PORT.match(port if isinstance(port, str) else "")
    if not match:
        return None
    low = int(match.group(1))
    high = int(match.group(2) or low)
    if not 1 <= low <= high <= 65535:
        return None
    return low, high


def _covers_ssh(port):
    low, high = _port_bounds(port)
    return low <= SSH_PORT <= high


def _check_rule(rule):
    """ValueError pour une règle hors format ou qui couvre le port de ssh :
    les règles relues de l'état viennent de l'hôte et finissent dans un
    script lancé en root."""
    if (
        not isinstance(rule, Rule)
        or rule.proto not in ("tcp", "udp")
        or rule.service not in SERVICES
        or _port_bounds(rule.port) is None
    ):
        raise ValueError(f"firewall rule: {rule!r}")
    if _covers_ssh(rule.port):
        raise ValueError(f"firewall rule covers ssh: {rule!r}")


def _span(low, high):
    return str(low) if low == high else f"{low}:{high}"


def firewall_rules(answers):
    """Les ouvertures des services choisis : coturn TURN en udp et tcp,
    TURNS en tcp avec un certificat, la plage des relais en udp ; ntfy son
    port en tcp. Son port http interne, sur 127.0.0.1 avec un certificat,
    n'est pas ouvert. Refusal `call_infra_bad_value` pour une règle qui
    couvrirait le port de ssh."""
    rules = []
    if "coturn" in answers.services:
        turn = str(answers.turn_port)
        rules += [Rule("udp", turn, "coturn"), Rule("tcp", turn, "coturn")]
        if answers.tls == "supplied":
            rules.append(Rule("tcp", str(answers.turns_port), "coturn"))
        rules.append(
            Rule("udp", _span(answers.min_port, answers.max_port), "coturn")
        )
    if "ntfy" in answers.services:
        rules.append(Rule("tcp", str(ntfy_port(answers)), "ntfy"))
    for rule in rules:
        bounds = _port_bounds(rule.port)
        if bounds is None or bounds[0] <= SSH_PORT <= bounds[1]:
            raise Refusal(
                "call_infra_bad_value",
                name="port",
                value=f"{rule.port}/{rule.proto}",
            )
    return tuple(rules)


def rules_from_state(state):
    """Les règles consignées dans `state["firewall"]`, celles hors format
    ou sur le port de ssh écartées."""
    firewall = state.get("firewall") if isinstance(state, dict) else None
    entries = firewall.get("rules") if isinstance(firewall, dict) else None
    rules = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, list) or len(entry) != 3:
            continue
        rule = Rule(*entry)
        try:
            _check_rule(rule)
        except ValueError:
            continue
        if rule not in rules:
            rules.append(rule)
    return tuple(rules)


def _comment(rule):
    return f"{FIREWALL_COMMENT} {rule.service}"


def _ufw_spec(rule):
    return f"{rule.port}/{rule.proto}"


def _nft_match(rule):
    """« udp dport 3478 » : nft écrit une plage avec « - »."""
    return f"{rule.proto} dport {rule.port.replace(':', '-')}"


def _nft_rule(rule):
    return f'{_nft_match(rule)} accept comment "{_comment(rule)}"'


def _valid_chain(chain):
    return (
        isinstance(chain, tuple)
        and len(chain) == 3
        and chain[0] in ("ip", "ip6", "inet")
        and all(_NFT_NAME.match(part) for part in chain[1:])
    )


def _check_kind(kind, rules, action="allow"):
    if kind not in FIREWALLS:
        raise ValueError(f"firewall kind: {kind!r}")
    if action not in FIREWALL_ACTIONS:
        raise ValueError(f"firewall action: {action!r}")
    rules = tuple(rules)
    for rule in rules:
        _check_rule(rule)
    return rules


def firewall_preview(kind, rules, chain=None):
    """Les commandes montrées avant le oui, telles que le script les passe.

    ufw : `ufw allow <port>/<proto> comment 'erplibre-call <service>'`.
    nftables : `nft insert rule <famille> <table> <chaîne> ...` dans
    `chain`, la seule chaîne input en drop (`HostFacts.nft_chains`) ; sans
    elle, liste vide, comme pour « none » et « unknown » : rien ne sera
    ajouté.
    """
    rules = _check_kind(kind, rules)
    if kind == "ufw":
        return [
            f"ufw allow {_ufw_spec(r)} comment '{_comment(r)}'" for r in rules
        ]
    if kind == "nftables" and chain is not None and _valid_chain(chain):
        target = " ".join(chain)
        return [f"nft insert rule {target} {_nft_rule(r)}" for r in rules]
    return []


def firewall_notes(kind):
    """Clés i18n à montrer avec l'aperçu. Le pare-feu du fournisseur
    infonuagique, que la sonde ne voit pas, est rappelé pour tout `kind`."""
    if kind not in FIREWALLS:
        raise ValueError(f"firewall kind: {kind!r}")
    notes = []
    if kind == "none":
        notes.append("call_infra_firewall_none")
    elif kind == "unknown":
        notes.append("call_infra_firewall_unknown")
    notes.append("call_infra_cloud_firewall")
    return notes


def _marker(name, rule):
    return f"@@FIREWALL_{name} {rule.proto} {rule.port} {rule.service}"


def _rule_words(rule):
    return f"{rule.proto} {rule.port} {rule.service}"


def _record_lines(kind):
    """Fonction `rec <ADDED|KEPT> <proto> <port> <service>` d'un script
    d'ajout : imprime la ligne `@@FIREWALL_*` et inscrit la règle dans la
    fiche `PENDING_DIR/firewall`, dans le passage root même qui la pose.
    Un état écrit plus tard (`state_write_script`) la consigne et vide la
    fiche ; s'il échoue, la sonde suivante la relit. Une fiche qui ne
    s'écrit pas fait échouer le script."""
    return [
        f'FWP="$R"{shlex.quote(PENDING_DIR)}/firewall',
        'rec() { echo "@@FIREWALL_$1 $2 $3 $4"; mkdir -p "${FWP%/*}"'
        f' && printf \'%s %s %s %s\\n\' {kind} "$2" "$3" "$4"'
        ' >> "$FWP" || RC=1; }',
    ]


def _script_head(root):
    return [
        "set -u",
        _C_LOCALE,
        f"R={shlex.quote(root)}",
        "umask 077",
        "RC=0",
        'D=$(mktemp -d) || { echo "@@FIREWALL_FAILED workdir"; echo "@@END";'
        " exit 1; }",
        "trap 'rm -rf \"$D\"' EXIT",
        "trap 'exit 129' HUP INT TERM",
    ]


def _script_tail():
    return ['echo "@@END"', 'exit "$RC"', ""]


def _ufw_script(rules, action, root=""):
    """ufw : la règle de l'outil est la ligne exacte `ufw allow <spec>
    comment 'erplibre-call <service>'` de `ufw show added`. Toute autre
    ligne qui porte « <spec> » appartient à l'administrateur, quelle que
    soit son action (deny, reject, limit), son journal ou son sens : elle
    n'est ni ajoutée ni consignée (FOREIGN), et donc jamais retirée. ufw
    remplace une règle qui ne diffère de la nôtre que par l'action ou le
    journal et répond « Rule updated » : cette réponse est FOREIGN aussi.
    ufw garde ses règles d'un démarrage à l'autre."""
    show = (
        'ufw show added > "$D/added" 2>/dev/null'
        ' || { echo "@@FIREWALL_FAILED show"; echo "@@END"; exit 1; }'
    )
    if action == "allow":
        lines = _script_head(root) + _record_lines("ufw") + [show]
    else:
        lines = _script_head(root) + _when_present("ufw", show, '"$D/added"')
    for rule in rules:
        spec = _ufw_spec(rule)
        mine = shlex.quote(f"ufw allow {spec} comment {_comment(rule)!r}")
        other = shlex.quote(f" {spec}( |$)")
        lines.append(
            f'if grep -qxF {mine} "$D/added"; then L=mine;'
            f' elif grep -qE {other} "$D/added"; then L=other; else L=; fi'
        )
        if action == "allow":
            command = f"ufw allow {spec} comment {shlex.quote(_comment(rule))}"
            lines += [
                'case "$L" in',
                f"  mine) rec KEPT {_rule_words(rule)} ;;",
                f'  other) echo "{_marker("FOREIGN", rule)}" ;;',
                f"  *) if O=$({command} 2>&1); then",
                '    case "$O" in',
                f'      *Skipping*|*updated*) echo "{_marker("FOREIGN", rule)}"'
                " ;;",
                f"      *) rec ADDED {_rule_words(rule)} ;;",
                "    esac",
                f'  else echo "{_marker("FAILED", rule)}"; RC=1; fi ;;',
                "esac",
            ]
        else:
            lines += [
                'case "$L" in',
                "  mine)",
                f"    if ufw delete allow {spec} </dev/null >/dev/null; then"
                f' echo "{_marker("REMOVED", rule)}";',
                f'    else echo "{_marker("FAILED", rule)}"; RC=1; fi ;;',
                f'  other) echo "{_marker("FOREIGN", rule)}" ;;',
                f'  *) echo "{_marker("ABSENT", rule)}" ;;',
                "esac",
            ]
    if action == "allow":
        lines.append('[ "$RC" = 0 ] && echo "@@FIREWALL_PERSISTED yes"')
    return "\n".join(lines + _script_tail())


def _when_present(command, listing, target):
    """Lignes `sh` du retrait : `listing` remplit `target` quand `command`
    existe ; sans elle, `target` reste vide et chaque règle se dit ABSENT.
    Un pare-feu désinstallé depuis ne porte plus aucune règle de l'outil,
    et le retrait se termine au lieu d'échouer à chaque relance."""
    return [
        f"if command -v {command} >/dev/null 2>&1; then",
        f"  {listing}",
        f"else : > {target}; fi",
    ]


def _nft_find(rule):
    """Commande `sh` qui imprime « famille table chaîne handle » de chaque
    règle de l'outil pour `rule` dans "$D/handles"."""
    return (
        f"awk -v m={shlex.quote(_nft_match(rule) + ' ')}"
        f" -v k={shlex.quote(f'comment {chr(34)}{_comment(rule)}{chr(34)}')}"
        f' {shlex.quote(_NFT_HANDLES_AWK)} "$D/handles"'
    )


def _nft_allow(rules):
    """nftables : les règles sont insérées en tête de LA chaîne de base
    input en drop, d'une seule transaction (`nft -f`) ; zéro ou plusieurs
    chaînes, ou un nom inattendu : `@@FIREWALL_MANUAL <n>` et rien ne
    change. Une règle de l'outil déjà présente est gardée (KEPT).

    Persistance : seulement quand NFT_CONF inclut NFT_PERSIST_DIR ; le
    fichier reçoit les mêmes lignes, puis `nft -c -f NFT_CONF` vérifie que
    la configuration se charge encore. Sinon, ou si la vérification
    échoue (fichier remis comme avant) : `@@FIREWALL_RUNTIME_ONLY`."""
    conf, persist = _host(NFT_CONF), _host(NFT_PERSIST_FILE)
    lines = [
        'nft list ruleset > "$D/ruleset" 2>/dev/null'
        ' || { echo "@@FIREWALL_FAILED list"; echo "@@END"; exit 1; }',
        f'awk {shlex.quote(_NFT_CHAINS_AWK)} "$D/ruleset" > "$D/chains"',
        "N=$(awk 'END { print NR }' \"$D/chains\")",
        "USABLE=0",
        'if [ "$N" = 1 ]; then',
        '  read -r F T C X < "$D/chains"',
        "  USABLE=1",
        '  [ -n "$X" ] && USABLE=0',
        '  case "$F" in ip|ip6|inet) ;; *) USABLE=0 ;; esac',
        '  case "$T" in ""|*[!A-Za-z0-9_.-]*) USABLE=0 ;; esac',
        '  case "$C" in ""|*[!A-Za-z0-9_.-]*) USABLE=0 ;; esac',
        "fi",
        'if [ "$USABLE" != 1 ]; then',
        '  echo "@@FIREWALL_MANUAL $N"; echo "@@END"; exit 0',
        "fi",
        'echo "@@FIREWALL_CHAIN $F $T $C"',
        'nft -a list ruleset > "$D/handles" 2>/dev/null'
        ' || { echo "@@FIREWALL_FAILED list"; echo "@@END"; exit 1; }',
        ': > "$D/add.nft"; : > "$D/added"; : > "$D/lines"',
    ]
    for rule in rules:
        body = shlex.quote(_nft_rule(rule))
        lines += [
            f'printf "insert rule %s %s %s %s\\n" "$F" "$T" "$C" {body}'
            ' >> "$D/lines"',
            f'if [ -n "$({_nft_find(rule)})" ]; then',
            f"  rec KEPT {_rule_words(rule)}",
            "else",
            f'  printf "insert rule %s %s %s %s\\n" "$F" "$T" "$C" {body}'
            ' >> "$D/add.nft"',
            f"  echo {shlex.quote(_marker('ADDED', rule)[2:])}"
            ' >> "$D/added"',
            "fi",
        ]
    lines += [
        'if [ -s "$D/add.nft" ]; then',
        '  if nft -f "$D/add.nft"; then',
        '    while read -r M P Q S; do rec "${M#FIREWALL_}" "$P" "$Q" "$S";'
        ' done < "$D/added"',
        "  else",
        "    sed 's/^/@@/; s/@@FIREWALL_ADDED/@@FIREWALL_FAILED/'"
        ' "$D/added"',
        "    RC=1",
        "  fi",
        "fi",
        'if [ "$RC" = 0 ]; then',
        f"  if [ -f {conf} ] && grep -Eq {shlex.quote(_NFT_INCLUDE_ERE)}"
        f" {conf}; then",
        f'    if [ -f {persist} ]; then cp {persist} "$D/persist";'
        f' cp -p {persist} "$D/previous";',
        f'    else echo {shlex.quote(MARKER)} > "$D/persist"; fi',
        "    while IFS= read -r LINE; do",
        '      grep -qxF "$LINE" "$D/persist"'
        ' || printf "%s\\n" "$LINE" >> "$D/persist"',
        '    done < "$D/lines"',
        f"    if mkdir -p {_host(NFT_PERSIST_DIR)}"
        f' && cp "$D/persist" {_host(NFT_PERSIST_FILE + ".new")}'
        f" && chmod 0644 {_host(NFT_PERSIST_FILE + '.new')}"
        f" && mv -f {_host(NFT_PERSIST_FILE + '.new')} {persist}"
        f" && nft -c -f {conf} >/dev/null 2>&1; then",
        '      echo "@@FIREWALL_PERSISTED yes"',
        "    else",
        f"      rm -f {_host(NFT_PERSIST_FILE + '.new')}",
        '      if [ -f "$D/previous" ]; then'
        f' cp -p "$D/previous" {persist}; else rm -f {persist}; fi',
        '      echo "@@FIREWALL_RUNTIME_ONLY check"',
        "    fi",
        "  else",
        '    echo "@@FIREWALL_RUNTIME_ONLY"',
        "  fi",
        "fi",
    ]
    return lines


def _nft_delete(rules):
    """nftables : chaque règle de l'outil est retrouvée par son commentaire
    dans tout le jeu (`nft -a list ruleset`), puis retirée par son handle ;
    une règle sans ce commentaire n'est jamais touchée. Ses lignes partent
    aussi de NFT_PERSIST_FILE, effacé quand il n'en reste aucune, que nft
    soit encore là ou non."""
    persist = _host(NFT_PERSIST_FILE)
    listing = (
        'nft -a list ruleset > "$D/handles" 2>/dev/null'
        ' || { echo "@@FIREWALL_FAILED list"; echo "@@END"; exit 1; }'
    )
    lines = _when_present("nft", listing, '"$D/handles"') + ["set --"]
    for rule in rules:
        lines += [
            f'{_nft_find(rule)} > "$D/found"',
            'if [ ! -s "$D/found" ]; then',
            f'  echo "{_marker("ABSENT", rule)}"',
            "else",
            "  GONE=1",
            "  while read -r F T C H; do",
            '    case "$F" in ip|ip6|inet) ;; *) GONE=0; continue ;; esac',
            '    case "$T" in ""|*[!A-Za-z0-9_.-]*) GONE=0; continue ;; esac',
            '    case "$C" in ""|*[!A-Za-z0-9_.-]*) GONE=0; continue ;; esac',
            '    case "$H" in ""|*[!0-9]*) GONE=0; continue ;; esac',
            '    nft delete rule "$F" "$T" "$C" handle "$H" || GONE=0',
            '  done < "$D/found"',
            '  if [ "$GONE" = 1 ]; then',
            f'    echo "{_marker("REMOVED", rule)}"',
            "  else",
            f'    echo "{_marker("FAILED", rule)}"; RC=1',
            "  fi",
            "fi",
            f'set -- "$@" -e {shlex.quote(_nft_rule(rule))}',
        ]
    lines += [
        f"if [ -f {persist} ]; then",
        f'  grep -vF "$@" {persist} > "$D/persist"',
        "  if grep -q '^insert rule' \"$D/persist\"; then",
        f'    chmod 0644 "$D/persist" && cp "$D/persist"'
        f" {_host(NFT_PERSIST_FILE + '.new')}"
        f" && mv -f {_host(NFT_PERSIST_FILE + '.new')} {persist} || RC=1",
        "  else",
        f"    rm -f {persist} || RC=1",
        "  fi",
        "fi",
    ]
    return lines


def firewall_script(kind, rules, action, root=""):
    """Script `sh`, lancé en root, qui ajoute (`allow`) ou retire
    (`delete`) `rules` du pare-feu actif ; "" pour « none » et « unknown »
    ou sans règle.

    Il n'active jamais un pare-feu, ne change aucune politique, ne vide
    rien et ne touche aucune règle qu'il n'a pas posée : chacune porte le
    commentaire « erplibre-call <service> ». Une ligne par règle :
    `@@FIREWALL_ADDED|KEPT|FOREIGN|REMOVED|ABSENT|FAILED <proto> <port>
    <service>` ; puis `@@FIREWALL_PERSISTED yes` ou
    `@@FIREWALL_RUNTIME_ONLY`, `@@FIREWALL_MANUAL <n>` quand nftables n'a
    pas exactement une chaîne input en drop, et `@@END`. Code non nul
    après un échec. `firewall_record` lit cette sortie. Un ajout inscrit
    aussi chaque règle ADDED ou KEPT dans la fiche `PENDING_DIR/firewall`
    (`_record_lines`). `root` préfixe les fichiers de l'hôte (tests).
    """
    rules = _check_kind(kind, rules, action)
    if kind in ("none", "unknown") or not rules:
        return ""
    if kind == "ufw":
        return _ufw_script(rules, action, root)
    if action == "allow":
        body = _record_lines("nftables") + _nft_allow(rules)
    else:
        body = _nft_delete(rules)
    return "\n".join(_script_head(root) + body + _script_tail())


def firewall_record(kind, output, previous=None, pending=()):
    """`state["firewall"]` après un passage de `firewall_script` :
    `{"kind", "rules": [[proto, port, service], ...], "persisted"}`.

    Partant des règles de `previous` (du même `kind`) et de celles de
    `pending` (`HostFacts.firewall_pending`) du même `kind`, les ADDED et KEPT
    s'ajoutent, les REMOVED et ABSENT partent ; FOREIGN et FAILED ne sont
    pas consignées : l'outil ne retirera que ce qu'il a posé. `persisted`
    suit `@@FIREWALL_PERSISTED` / `@@FIREWALL_RUNTIME_ONLY`, sinon reste
    celui de `previous`.
    """
    if kind not in FIREWALLS:
        raise ValueError(f"firewall kind: {kind!r}")
    same = isinstance(previous, dict) and previous.get("kind") == kind
    rules = set(rules_from_state({"firewall": previous}) if same else ())
    rules |= {found for found_kind, found in pending if found_kind == kind}
    persisted = bool(same and previous.get("persisted"))
    for name, value in marker_lines(output or ""):
        if name == "FIREWALL_PERSISTED":
            persisted = True
        elif name == "FIREWALL_RUNTIME_ONLY":
            persisted = False
        elif name.startswith("FIREWALL_"):
            parts = value.split()
            if len(parts) != 3:
                continue
            rule = Rule(*parts)
            try:
                _check_rule(rule)
            except ValueError:
                continue
            if name in ("FIREWALL_ADDED", "FIREWALL_KEPT"):
                rules.add(rule)
            elif name in ("FIREWALL_REMOVED", "FIREWALL_ABSENT"):
                rules.discard(rule)
    ordered = sorted(rules, key=lambda r: (r.proto, r.port, r.service))
    return {
        "kind": kind,
        "rules": [[r.proto, r.port, r.service] for r in ordered],
        "persisted": persisted if ordered else False,
    }


def merge_pending_firewall(state, pending):
    """Copie de `state` dont « firewall » porte aussi les règles de
    `pending` : la désinstallation retire ce qu'un passage a posé sans
    pouvoir le consigner. Le type est celui de l'état, sinon celui de la
    fiche. `state` tel quel quand il n'est pas un dict ou sans fiche."""
    if not isinstance(state, dict) or not pending:
        return state
    record = state.get("firewall")
    kind = record.get("kind") if isinstance(record, dict) else None
    if kind not in ("ufw", "nftables"):
        kind = pending[0][0]
    return with_firewall(state, firewall_record(kind, "", record, pending))


def firewall_missing(facts, answers):
    """Vrai quand une relance doit encore proposer le pare-feu : une règle
    posée attend d'être consignée, ou une règle voulue que le pare-feu actif
    sait recevoir n'est pas consignée pour lui."""
    if facts.firewall_pending:
        return True
    rules = firewall_rules(answers)
    chain = facts.nft_chains[0] if len(facts.nft_chains) == 1 else None
    if not firewall_preview(facts.firewall, rules, chain):
        return False
    state = facts.state if isinstance(facts.state, dict) else {}
    record = state.get("firewall")
    same = isinstance(record, dict) and record.get("kind") == facts.firewall
    recorded = set(rules_from_state(state)) if same else set()
    return any(rule not in recorded for rule in rules)


def with_firewall(state, record):
    """Copie de `state` qui porte `record` sous « firewall »."""
    updated = copy.deepcopy(state) if isinstance(state, dict) else {}
    updated["firewall"] = copy.deepcopy(record)
    return updated


def state_write_script(state, root=""):
    """Script `sh`, lancé en root, qui remplace l'état de l'hôte par
    `state` (après `with_firewall`) : `.new` en 0600 puis renommage, puis
    la fiche `PENDING_DIR/firewall` retirée : l'appelant y a pris les
    règles (`firewall_record`, argument `pending`). Dernière ligne
    `@@SAVED yes`, ou `@@FAILED state` et `@@SAVED no`."""
    lines = [
        "set -u",
        f"R={shlex.quote(root)}",
        f'STATE="$R"{shlex.quote(STATE_PATH)}',
        "umask 077",
        'fail() { echo "@@FAILED $1"; echo "@@SAVED no"; exit 1; }',
        f'mkdir -p "$R"{shlex.quote(CALL_DIR)} || fail state',
        *_state_write_lines(state),
        f'rm -f "$R"{shlex.quote(PENDING_DIR)}/firewall',
        'echo "@@SAVED yes"',
        "",
    ]
    return "\n".join(lines)


# --- Vérification -----------------------------------------------------------

CHECK_USER = "erplibre-check"
# Un certificat qui expire dans moins de jours que ceci est signalé.
CERT_WARN_DAYS = 14
TLS_CERTS = {
    "coturn": f"{COTURN_TLS_DIR}/turn.crt",
    "ntfy": f"{NTFY_TLS_DIR}/ntfy.crt",
}
_HEX_KEY = re.compile(r"^[0-9a-f]{32}$")

# Clés i18n que porte `CheckLine.detail` ; chacune a sa traduction dans
# todo_i18n.py, avec les champs de `CheckLine.values` entre accolades.
CHECK_KEYS = (
    "call_infra_check_no_state",
    "call_infra_check_active",
    "call_infra_check_relayed",
    "call_infra_check_open_relay",
    "call_infra_check_turn_error",
    "call_infra_check_no_key",
    "call_infra_check_healthy",
    "call_infra_check_unhealthy",
    "call_infra_check_http_error",
    "call_infra_check_cert_unverified",
    "call_infra_check_cert_days",
    "call_infra_check_cert_missing",
    "call_infra_check_cert_unreadable",
    "call_infra_check_firewall_none",
    "call_infra_check_firewall_ok",
    "call_infra_check_firewall_missing",
)


@dataclasses.dataclass(frozen=True)
class CheckLine:
    """Une ligne du verdict de `check_local`.

    `ok` : True, False, ou None quand la chose n'a pas pu être vérifiée,
    la raison dans `detail`. `detail` est une clé de CHECK_KEYS, `values`
    les champs de son message (`t(detail).format(**values)`).
    """

    name: str
    ok: bool | None
    detail: str
    values: dict = dataclasses.field(default_factory=dict)


# `ufw show added` : la ligne exacte qu'écrit `_ufw_script` pour une règle
# de l'outil. Imprime « @@FIREWALL_RULE ufw <proto> <port> <service> ».
_CHECK_UFW_SED = (
    r"s/^ufw allow ([0-9]+(:[0-9]+)?)\/(tcp|udp) comment"
    f" '{FIREWALL_COMMENT} ({'|'.join(SERVICES)})'$"
    r"/@@FIREWALL_RULE ufw \3 \1 \4/p"
)
# `nft list ruleset` : une règle de l'outil, telle que `_nft_rule` la pose
# (une plage s'y écrit avec « - »).
_CHECK_NFT_SED = (
    r"s/.*[[:space:]](tcp|udp) dport ([0-9]+(-[0-9]+)?) accept comment"
    f' "{FIREWALL_COMMENT} ({"|".join(SERVICES)})".*'
    r"/@@FIREWALL_RULE nftables \1 \2 \4/p"
)


def check_remote_script(root=""):
    """Script `sh` en lecture seule, lancé en root, qui imprime ce que la
    vérification lit sur l'hôte.

    Lignes : `@@STATE <base64>` (l'état, s'il existe), `@@ACTIVE <service>
    <état systemd>` (« absent » sans unité), `@@CHECK_KEY <hex>` (la clé
    long terme du compte de contrôle, lue dans la base de coturn par
    `sqlite3 -readonly` sous le compte du service : root n'ouvre aucun
    fichier de ce dossier, qui appartient à ce compte), `@@CERT <service>
    <base64>` par certificat installé, `@@FIREWALL_RULE <ufw|nftables>
    <proto> <port> <service>` par règle de l'outil présente dans un pare-feu
    actif, puis `@@END`. `root` préfixe chaque chemin lu (tests).

    La ligne `@@CHECK_KEY` porte un secret : qui la lit s'authentifie
    auprès du relais sous le compte de contrôle. La sortie se capture sans
    être recopiée à l'écran.
    """
    query = f"select hmackey from turnusers_lt where name='{CHECK_USER}'"
    certs = " ".join(f"{svc}:{path}" for svc, path in TLS_CERTS.items())
    return "\n".join(
        [
            _C_LOCALE,
            f"R={shlex.quote(root)}",
            "echo",
            f'S="$R"{shlex.quote(STATE_PATH)}',
            'if [ -f "$S" ]; then echo "@@STATE $(base64 -w0 < "$S")"; fi',
            "CU=-",
            "for u in " + " ".join(COTURN_UNITS.values()) + "; do",
            '  if systemctl cat "$u" >/dev/null 2>&1; then CU=$u; break; fi',
            "done",
            'if [ "$CU" != - ]; then',
            '  A=$(systemctl is-active "$CU" 2>/dev/null)',
            '  echo "@@ACTIVE coturn ${A:-unknown}"',
            "else",
            '  echo "@@ACTIVE coturn absent"',
            "fi",
            f"if systemctl cat {NTFY_UNIT} >/dev/null 2>&1; then",
            f"  A=$(systemctl is-active {NTFY_UNIT} 2>/dev/null)",
            '  echo "@@ACTIVE ntfy ${A:-unknown}"',
            "else",
            '  echo "@@ACTIVE ntfy absent"',
            "fi",
            f'DB="$R"{shlex.quote(COTURN_DB)}',
            'if [ "$CU" != - ] && [ -f "$DB" ]'
            " && command -v sqlite3 >/dev/null 2>&1; then",
            '  U=$(systemctl show -p User --value "$CU" 2>/dev/null)',
            '  runuser -u "${U:-turnserver}" -- sqlite3 -readonly'
            f' -init /dev/null "$DB" "{query}" 2>/dev/null'
            " | sed 's/^/@@CHECK_KEY /'",
            "fi",
            f"for c in {certs}; do",
            '  f="$R${c#*:}"',
            '  if [ -f "$f" ]; then'
            ' echo "@@CERT ${c%%:*} $(base64 -w0 < "$f")"; fi',
            "done",
            "if command -v ufw >/dev/null 2>&1"
            " && ufw status 2>/dev/null | grep -q '^Status: active'; then",
            "  ufw show added 2>/dev/null"
            f" | sed -n -E {shlex.quote(_CHECK_UFW_SED)}",
            "fi",
            "if command -v nft >/dev/null 2>&1; then",
            "  nft list ruleset 2>/dev/null"
            f" | sed -n -E {shlex.quote(_CHECK_NFT_SED)}",
            "fi",
            'echo "@@END"',
            "",
        ]
    )


def parse_check_remote(output):
    """Dict de la sortie de `check_remote_script` : `state` (dict ou None),
    `active` {service: état}, `check_key` (32 chiffres hexa ou None),
    `firewall_rules` [(ufw|nftables, Rule)], `certs` {service: PEM}.

    Une règle hors format ou sur le port de ssh est écartée, comme dans
    `rules_from_state`. Refusal `call_infra_probe_incomplete` sans `@@END`.
    """
    state, active, key, rules, certs = None, {}, None, [], {}
    complete = False
    for name, value in marker_lines(output):
        if name == "STATE":
            state = _decode_json(value)
        elif name == "ACTIVE":
            svc, _, current = value.partition(" ")
            if svc in SERVICES:
                active[svc] = current.strip() or "unknown"
        elif name == "CHECK_KEY":
            candidate = value.strip().lower()
            if key is None and _HEX_KEY.match(candidate):
                key = candidate
        elif name == "FIREWALL_RULE":
            parts = value.split()
            if len(parts) != 4 or parts[0] not in ("ufw", "nftables"):
                continue
            found = Rule(parts[1], parts[2].replace("-", ":"), parts[3])
            try:
                _check_rule(found)
            except ValueError:
                continue
            if (parts[0], found) not in rules:
                rules.append((parts[0], found))
        elif name == "CERT":
            svc, _, encoded = value.partition(" ")
            text = _decode(encoded)
            if svc in SERVICES and text:
                certs[svc] = text
        elif name == "END":
            complete = True
    if not complete:
        raise Refusal("call_infra_probe_incomplete")
    return {
        "state": state,
        "active": active,
        "check_key": key,
        "firewall_rules": rules,
        "certs": certs,
    }


class _NamedHTTPS(http.client.HTTPConnection):
    """Connexion https vers `host` dont le certificat est vérifié sous
    `server_name` : l'adresse jointe et le nom attendu diffèrent quand on
    vérifie un hôte par son adresse."""

    def __init__(self, host, port, server_name, context, timeout):
        super().__init__(host, port, timeout=timeout)
        self.server_name = server_name
        self.tls_context = context

    def connect(self):
        super().connect()
        self.sock = self.tls_context.wrap_socket(
            self.sock, server_hostname=self.server_name
        )


def https_get(
    address, port, path, tls, server_name=None, cafile=None, timeout=5.0
):
    """(statut, corps) d'un GET sur `address`:`port`, en https si `tls`.

    Le certificat est vérifié sous `server_name` (sinon `address`) contre
    `cafile`, sinon contre les autorités du système ; un certificat que
    rien ne garantit lève ssl.SSLCertVerificationError. Les autres échecs
    lèvent OSError ou http.client.HTTPException. Corps lu sur 64 Kio au
    plus."""
    name = server_name or address
    if tls:
        context = ssl.create_default_context(cafile=cafile)
        connection = _NamedHTTPS(address, port, name, context, timeout)
    else:
        connection = http.client.HTTPConnection(address, port, timeout=timeout)
    try:
        connection.request(
            "GET", path, headers={"Host": f"{_url_host(name)}:{port}"}
        )
        response = connection.getresponse()
        body = response.read(65536).decode("utf-8", "replace")
        return response.status, body
    finally:
        connection.close()


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _turn_lines(settings, key, address, cafile, allocate, timeout):
    """Une allocation réelle par transport, sous le compte de contrôle.
    Sans autorité fournie, un échec TLS ne distingue pas un certificat que
    le système ne connaît pas d'une panne : la ligne vaut None."""
    turn_port = _int(settings.get("turn_port"), 3478)
    transports = [("udp", turn_port), ("tcp", turn_port)]
    if settings.get("tls") == "supplied":
        transports.append(("tls", _int(settings.get("turns_port"), 5349)))
    if not key:
        return [
            CheckLine(f"turn-{transport}", None, "call_infra_check_no_key")
            for transport, _ in transports
        ]
    lines = []
    for transport, port in transports:
        extra = {}
        if transport == "tls":
            extra = dict(
                cafile=cafile,
                server_name=settings.get("public_name") or address,
            )
        result = allocate(
            address,
            port,
            transport,
            CHECK_USER,
            bytes.fromhex(key),
            timeout=timeout,
            **extra,
        )
        name = f"turn-{transport}"
        if result.ok:
            host, relayed_port = result.relayed or ("?", 0)
            relayed = f"{_url_host(host)}:{relayed_port}"
            lines.append(
                CheckLine(
                    name,
                    True,
                    "call_infra_check_relayed",
                    {"relayed": relayed},
                )
            )
        elif result.error == "no-auth":
            lines.append(CheckLine(name, False, "call_infra_check_open_relay"))
        elif result.error == "tls" and transport == "tls" and not cafile:
            lines.append(
                CheckLine(name, None, "call_infra_check_cert_unverified")
            )
        else:
            lines.append(
                CheckLine(
                    name,
                    False,
                    "call_infra_check_turn_error",
                    {"error": result.error},
                )
            )
    return lines


def _ntfy_line(settings, address, cafile, https_get, timeout):
    tls = settings.get("tls") == "supplied"
    port = _int(
        settings.get("port"), NTFY_HTTPS_PORT if tls else NTFY_HTTP_PORT
    )
    name = "ntfy-health"
    try:
        status, body = https_get(
            address,
            port,
            "/v1/health",
            tls,
            server_name=settings.get("public_name") or address,
            cafile=cafile if tls else None,
            timeout=timeout,
        )
    except ssl.SSLCertVerificationError:
        return CheckLine(name, None, "call_infra_check_cert_unverified")
    except (OSError, http.client.HTTPException, ValueError) as exc:
        error = str(exc) or type(exc).__name__
        return CheckLine(
            name, False, "call_infra_check_http_error", {"error": error}
        )
    try:
        healthy = json.loads(body).get("healthy") is True
    except (ValueError, AttributeError):
        healthy = False
    if status == 200 and healthy:
        return CheckLine(name, True, "call_infra_check_healthy")
    return CheckLine(
        name, False, "call_infra_check_unhealthy", {"status": status}
    )


def _expiry_line(services, certs, now):
    """Le certificat installé qui expire le premier, parmi ceux des
    services en https ; sous CERT_WARN_DAYS jours, la ligne échoue."""
    name = "cert-expiry"
    earliest = None
    for svc in services:
        pem = certs.get(svc)
        if not pem:
            return CheckLine(
                name, False, "call_infra_check_cert_missing", {"service": svc}
            )
        try:
            not_after = _certificate_facts(pem)[0]
        except Refusal as refusal:
            return CheckLine(
                name,
                False,
                "call_infra_check_cert_unreadable",
                {"reason": refusal.values.get("reason", "")},
            )
        earliest = not_after if earliest is None else min(earliest, not_after)
    days = (earliest - now).days
    return CheckLine(
        name,
        days >= CERT_WARN_DAYS,
        "call_infra_check_cert_days",
        {"days": days, "date": earliest.strftime("%Y-%m-%d")},
    )


def _firewall_line(state, present):
    """Les règles consignées comparées à celles de l'outil que le pare-feu
    consigné porte encore ; une règle du même port dans un autre pare-feu
    ne compte pas."""
    record = state.get("firewall")
    kind = record.get("kind") if isinstance(record, dict) else "none"
    kind = kind if kind in FIREWALLS else "unknown"
    recorded = rules_from_state(state)
    if kind not in ("ufw", "nftables") or not recorded:
        return CheckLine(
            "firewall", None, "call_infra_check_firewall_none", {"kind": kind}
        )
    have = {found for found_kind, found in present if found_kind == kind}
    missing = [r for r in recorded if r not in have]
    if missing:
        text = ", ".join(_ufw_spec(r) for r in missing)
        return CheckLine(
            "firewall",
            False,
            "call_infra_check_firewall_missing",
            {"rules": text},
        )
    return CheckLine(
        "firewall",
        True,
        "call_infra_check_firewall_ok",
        {"count": len(recorded)},
    )


def check_local(
    facts_remote,
    address,
    cafile,
    allocate=turn_client.allocate,
    https_get=https_get,
    now=None,
    timeout=5.0,
):
    """Vérification depuis la machine qui lance `todo.py`.

    `facts_remote` vient de `parse_check_remote` ; `address` est le nom ou
    l'adresse par où l'hôte est joint ; `cafile` l'autorité d'un certificat
    fourni (None : celles du système). Lignes, pour les services consignés
    dans l'état : `turn-udp`, `turn-tcp`, `turn-tls` (avec un certificat ;
    allocations réelles sous le compte de contrôle), `ntfy-health`
    (`/v1/health`), `cert-expiry` (avec un certificat), `firewall`, puis
    `service-<service>`. Sans état : une seule ligne `state` en échec.
    """
    state = facts_remote.get("state")
    services = state.get("services") if isinstance(state, dict) else None
    records = {
        svc: services[svc]
        for svc in SERVICES
        if isinstance(services, dict) and isinstance(services.get(svc), dict)
    }
    if not records:
        return [CheckLine("state", False, "call_infra_check_no_state")]
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    settings = {
        svc: (
            record.get("settings")
            if isinstance(record.get("settings"), dict)
            else {}
        )
        for svc, record in records.items()
    }
    lines = []
    if "coturn" in records:
        lines += _turn_lines(
            settings["coturn"],
            facts_remote.get("check_key"),
            address,
            cafile,
            allocate,
            timeout,
        )
    if "ntfy" in records:
        lines.append(
            _ntfy_line(settings["ntfy"], address, cafile, https_get, timeout)
        )
    with_tls = [s for s in records if settings[s].get("tls") == "supplied"]
    if with_tls:
        lines.append(
            _expiry_line(with_tls, facts_remote.get("certs") or {}, now)
        )
    lines.append(
        _firewall_line(state, facts_remote.get("firewall_rules") or [])
    )
    active = facts_remote.get("active") or {}
    for svc in records:
        current = active.get(svc, "unknown")
        lines.append(
            CheckLine(
                f"service-{svc}",
                current == "active",
                "call_infra_check_active",
                {"state": current},
            )
        )
    return lines


# --- Désinstallation --------------------------------------------------------

PACKAGES = {"coturn": "coturn", "ntfy": "ntfy"}
COTURN_DATA_DIR = os.path.dirname(COTURN_DB)
NTFY_DATA_DIR = os.path.dirname(NTFY_AUTH_FILE)
NTFY_CACHE_DIR = "/var/cache/ntfy"
# L'unité et le binaire que pose install_ntfy.sh quand aucun paquet ne
# fournit ntfy ; sa ligne Description signe l'unité.
NTFY_TOOL_UNIT = "/etc/systemd/system/ntfy.service"
NTFY_TOOL_BINARY = "/usr/local/bin/ntfy"
NTFY_TOOL_DESCRIPTION = "Description=ntfy push notification server"
# La purge du paquet ntfy peut emporter ses dossiers (script postrm) : ce
# que l'outil garde y est mis de côté, sous HOLD_PREFIX<tampon>, le temps
# de la purge, puis remis. Une désinstallation coupée entre les deux le
# laisse là ; la suivante le remet en premier.
HOLD_PREFIX = "/var/lib/erplibre-call.hold-"
_HELD = (("ntfy-data", NTFY_DATA_DIR), ("ntfy-tls", NTFY_TLS_DIR))
_UNITS = {"coturn": tuple(COTURN_UNITS.values()), "ntfy": (NTFY_UNIT,)}
_TLS_FILES = {
    "coturn": {f"{COTURN_TLS_DIR}/turn.crt", f"{COTURN_TLS_DIR}/turn.key"},
    "ntfy": {f"{NTFY_TLS_DIR}/ntfy.crt", f"{NTFY_TLS_DIR}/ntfy.key"},
}
_HOST_PATH = re.compile(r"^(/[A-Za-z0-9._@+-]+)+$")


def _safe_path(path):
    """Chemin absolu fait de caractères sûrs, sans « . » ni « .. » : il
    vient de l'état de l'hôte et finit dans un script lancé en root."""
    return (
        isinstance(path, str)
        and bool(_HOST_PATH.match(path))
        and not any(part in (".", "..") for part in path.split("/"))
    )


def _uninstall_records(state):
    """[(service, fiche)] des services consignés, chaque valeur vérifiée :
    unité connue, chemins sûrs, copie `<config>.bak-<tampon>`, fichiers TLS
    de ceux que l'outil pose. Refusal `call_infra_state_invalid` sinon."""
    services = state.get("services", {})
    if not isinstance(services, dict):
        raise Refusal("call_infra_state_invalid", service="services")
    records = []
    for svc in SERVICES:
        if svc not in services:
            continue
        record = services[svc]
        invalid = Refusal("call_infra_state_invalid", service=svc)
        if not isinstance(record, dict):
            raise invalid
        config, backup = record.get("config"), record.get("backup")
        tls_files = record.get("tls_files") or []
        if record.get("unit") not in _UNITS[svc] or not _safe_path(config):
            raise invalid
        if backup is not None and not _is_backup_of(config, backup):
            raise invalid
        was_active = record.get("was_active")
        was_enabled = record.get("was_enabled")
        if was_active not in (True, False, None) or not (
            was_enabled is None
            or (
                isinstance(was_enabled, str) and _UNIT_STATE.match(was_enabled)
            )
        ):
            raise invalid
        if not isinstance(tls_files, list) or not all(
            isinstance(path, str) and path in _TLS_FILES[svc]
            for path in tls_files
        ):
            raise invalid
        records.append(
            (
                svc,
                {
                    "unit": record["unit"],
                    "config": config,
                    "installed_by_tool": bool(record.get("installed_by_tool")),
                    "adopted": bool(record.get("adopted")),
                    "backup": backup,
                    "was_active": was_active,
                    "was_enabled": was_enabled,
                    "admin_added": record.get("admin_added") is True,
                    "tls_files": sorted(tls_files),
                },
            )
        )
    return records


# États dpkg qu'une opération coupée (ssh perdu pendant apt) laisse au
# paquet : il est encore sur l'hôte et se purge, mais apt-get refuse toute
# action tant que « dpkg --configure -a » n'a pas tourné, comme le font
# install_coturn.sh et install_ntfy.sh avant d'installer.
_DPKG_INTERRUPTED = (
    "half-installed|unpacked|half-configured|triggers-awaited|triggers-pending"
)


def _uninstall_helpers():
    """Fonctions `sh` du script : famille du système (os-release, mêmes
    listes qu'`os_family`), paquet présent et purge, remise en place de ce
    qui a été mis de côté. Sur Debian, un paquet dans un état de
    _DPKG_INTERRUPTED compte comme présent, et sa purge passe d'abord par
    « dpkg --configure -a » ; « config-files » ne compte pas."""
    debian = "|".join(sorted(_DEBIAN_IDS))
    arch = "|".join(sorted(_ARCH_IDS))
    held = " ".join(f"{name}:{path}" for name, path in _HELD)
    return [
        "FAMILY=",
        'if [ -r "$R/etc/os-release" ]; then',
        '  FAMILY=$(. "$R/etc/os-release"; for i in "${ID:-}" ${ID_LIKE:-};'
        f' do case "$i" in {debian}) echo debian; break ;;'
        f" {arch}) echo arch; break ;; esac; done)",
        "fi",
        "dpkg_status() {",
        "  S=$(dpkg-query -W -f='${Status}' \"$1\" 2>/dev/null) || S=",
        '  echo "${S##* }"',
        "}",
        "pkg_installed() {",
        '  case "$FAMILY" in',
        '    debian) case "$(dpkg_status "$1")" in'
        f" installed|{_DPKG_INTERRUPTED}) return 0 ;; esac; return 1 ;;",
        '    arch) pacman -Qq "$1" >/dev/null 2>&1 ;;',
        "    *) return 1 ;;",
        "  esac",
        "}",
        "pkg_purge() {",
        '  case "$FAMILY" in',
        f'    debian) case "$(dpkg_status "$1")" in {_DPKG_INTERRUPTED})',
        "      DEBIAN_FRONTEND=noninteractive dpkg --configure -a"
        " --force-confdef --force-confold </dev/null ;;",
        "    esac",
        '    DEBIAN_FRONTEND=noninteractive apt-get purge -y "$1"'
        " </dev/null ;;",
        '    arch) pacman -Rn --noconfirm "$1" </dev/null ;;',
        "    *) return 1 ;;",
        "  esac",
        "}",
        "held_back() {",
        f"  for E in {held}; do",
        '    N=${E%%:*}; P="$R${E#*:}"',
        '    [ -e "$1/$N" ] || continue',
        '    if [ -d "$P" ]; then rmdir "$P" 2>/dev/null; fi',
        '    if [ -e "$P" ]; then failed "hold-$N"; continue; fi',
        '    mkdir -p "$(dirname "$P")" && mv "$1/$N" "$P"'
        ' || failed "hold-$N"',
        "  done",
        '  rmdir "$1" 2>/dev/null',
        "}",
    ]


def _is_managed_test(path):
    """Test `sh` vrai quand le fichier de l'hôte porte MARKER en tête."""
    host = _host(path)
    return (
        f'[ -f {host} ] && [ "$(head -n 1 {host})" = {shlex.quote(MARKER)} ]'
    )


def _stop_lines(svc, unit):
    quoted = shlex.quote(unit)
    return [
        f"if systemctl cat {quoted} >/dev/null 2>&1; then",
        f"  if systemctl disable --now {quoted} >/dev/null 2>&1; then"
        f' echo "@@REMOVED unit {unit}";',
        f"  else failed stop-{svc}; fi",
        "fi",
    ]


def _remove_managed_lines(svc, config):
    return [
        f"if {_is_managed_test(config)}; then",
        f'  if rm -f {_host(config)}; then echo "@@REMOVED config {config}";'
        f" else failed config-{svc}; fi",
        "fi",
    ]


def _ntfy_tool_files_lines():
    """L'unité qu'install_ntfy.sh a écrite (sa Description), et le binaire
    qu'elle lance s'il est celui qu'il a posé ; une unité d'une autre main
    reste."""
    unit, binary = _host(NTFY_TOOL_UNIT), _host(NTFY_TOOL_BINARY)
    return [
        f"if [ -f {unit} ] && grep -qxF"
        f" {shlex.quote(NTFY_TOOL_DESCRIPTION)} {unit}; then",
        "  B=$(sed -n -E 's/^ExecStart=([^[:space:]]+) serve.*/\\1/p'"
        f" {unit} | head -n 1)",
        f"  if rm -f {unit}; then"
        f' echo "@@REMOVED unit-file {NTFY_TOOL_UNIT}";'
        " else failed unit-file-ntfy; fi",
        "  systemctl daemon-reload >/dev/null 2>&1",
        f'  if [ "$B" = {NTFY_TOOL_BINARY} ] && [ -f {binary} ]; then',
        f"    if rm -f {binary}; then"
        f' echo "@@REMOVED binary {NTFY_TOOL_BINARY}";'
        " else failed binary-ntfy; fi",
        "  fi",
        "fi",
    ]


def _admin_removal_lines():
    """Retrait de NTFY_ADMIN_USER d'un ntfy adopté, sous la configuration
    de l'outil, encore en place, et sous le compte du service quand il
    existe (comme install_ntfy.sh) : root laisserait dans le dossier de la
    base des fichiers que ntfy ne peut plus écrire. Un compte déjà parti
    ne fait rien."""
    config, user = _host(NTFY_CONFIG), shlex.quote(NTFY_ADMIN_USER)
    found = shlex.quote(f"^user {NTFY_ADMIN_USER} ")
    return [
        "if command -v ntfy >/dev/null 2>&1; then",
        '  U=; id ntfy >/dev/null 2>&1 && U="runuser -u ntfy --"',
        f"  if $U ntfy user --config {config} list 2>&1 | grep -q {found};"
        " then",
        f"    if $U ntfy user --config {config} del {user} >/dev/null 2>&1;"
        f' then echo "@@REMOVED account {NTFY_ADMIN_USER}";',
        "    else failed account-ntfy; fi",
        "  fi",
        "fi",
    ]


def _restore_lines(svc, record):
    """Copie remise par `mv` (droits et propriétaire de l'original) ; une
    copie disparue alors que la configuration de l'outil est en place se
    dit (`@@BACKUP_MISSING`) et laisse le service tel que l'outil l'a
    configuré (KEEP_<service>=1, KEPT=1) : ni ses fichiers TLS, ni ses
    données, ni l'état ne partent, sans bloquer les autres services.

    L'unité retrouve ce qu'elle était avant l'outil, dont l'installateur
    l'a activée et démarrée : arrêtée si elle ne tournait pas, désactivée
    si `is-enabled` disait « disabled », relancée sinon (et pour un état
    qui ne le consigne pas)."""
    config, backup = record["config"], record["backup"]
    unit = shlex.quote(record["unit"])
    lines = []
    if backup:
        lines += [f"if [ -f {_host(backup)} ]; then"]
        if svc == "ntfy" and record.get("admin_added"):
            lines += ["  " + line for line in _admin_removal_lines()]
        lines += [
            f"  if mv -f {_host(backup)} {_host(config)}; then"
            f' echo "@@RESTORED {config} {backup}";',
            f"  else failed restore-{svc}; fi",
            f"elif {_is_managed_test(config)}; then",
        ]
    else:
        lines.append(f"if {_is_managed_test(config)}; then")
    lines += [
        f'  echo "@@BACKUP_MISSING {svc} {backup or "-"}";'
        f" KEEP_{svc}=1; KEPT=1",
        "fi",
        f'if [ "$KEEP_{svc}" = 0 ]; then',
    ]
    if record.get("was_active") is False:
        lines.append(
            f"  systemctl stop {unit} >/dev/null 2>&1 || failed stop-{svc}"
        )
    else:
        lines.append(
            f"  systemctl try-restart {unit} >/dev/null 2>&1"
            f' || echo "@@RESTART_FAILED {svc}"'
        )
    if record.get("was_enabled") == "disabled":
        lines.append(
            f"  systemctl disable {unit} >/dev/null 2>&1"
            f" || failed disable-{svc}"
        )
    lines.append("fi")
    return lines


def _put_back_lines(svc, record):
    """La copie d'origine remise par `mv` après la purge d'un service que
    l'outil a posé ET dont il a adopté la configuration (fichier resté sans
    paquet) : l'hôte retrouve son fichier, sans service à relancer. Une
    copie disparue se dit (`@@BACKUP_LOST`) sans rien bloquer : le paquet
    est déjà parti, il n'y a plus rien à garder."""
    config, backup = _host(record["config"]), _host(record["backup"])
    return [
        f"if [ -f {backup} ]; then",
        f"  if mv -f {backup} {config}; then"
        f' echo "@@RESTORED {record["config"]} {record["backup"]}";',
        f"  else failed restore-{svc}; fi",
        "else",
        f'  echo "@@BACKUP_LOST {svc} {record["backup"]}"',
        "fi",
    ]


def _service_uninstall_lines(svc, record, remove_data, stamp):
    """Lignes `sh` d'un service. Posé par l'outil : arrêt, purge du
    paquet, fichiers et configuration retirés, puis la configuration
    d'origine remise quand l'outil l'avait aussi adoptée. Adopté :
    configuration d'origine remise, unité rendue à son état d'avant
    l'outil, paquet laissé. Paquet déjà là sans configuration : arrêt et
    configuration de l'outil retirée. Puis ses fichiers TLS et ses
    données, retirés ou gardés selon `remove_data`."""
    installed = record["installed_by_tool"]
    hold = svc == "ntfy" and installed and not remove_data
    package = PACKAGES[svc]
    lines = [f"# {svc}", f"KEEP_{svc}=0"]
    if installed:
        lines += _stop_lines(svc, record["unit"])
        purge = [
            f"if pkg_installed {package}; then",
            f"  if pkg_purge {package}; then"
            f' echo "@@REMOVED package {package}";'
            f" else failed package-{svc}; fi",
            "fi",
        ]
        if hold:
            target = f'"$R"{shlex.quote(HOLD_PREFIX + stamp)}'
            lines += [f"H={target}", 'HOLD=1; mkdir -p "$H" || HOLD=0']
            for name, path in _HELD:
                lines.append(
                    f"if [ -e {_host(path)} ]; then"
                    f' mv {_host(path)} "$H/{name}" || HOLD=0; fi'
                )
            # Rien ne se purge tant que les données ne sont pas à l'abri.
            lines += ['if [ "$HOLD" = 1 ]; then']
            lines += ["  " + line for line in purge]
            lines += [f"else failed hold-{svc}; fi"]
        else:
            lines += purge
        if svc == "ntfy":
            lines += _ntfy_tool_files_lines()
        lines += _remove_managed_lines(svc, record["config"])
        if record["adopted"] and record["backup"]:
            lines += _put_back_lines(svc, record)
        if svc == "ntfy":
            cache = _host(NTFY_CACHE_DIR)
            lines.append(
                f"if [ -e {cache} ]; then rm -rf {cache}"
                f' && echo "@@REMOVED data {NTFY_CACHE_DIR}"'
                " || failed cache-ntfy; fi"
            )
            if hold:
                lines.append('held_back "$H"')
            else:
                data = _host(NTFY_DATA_DIR)
                lines.append(
                    f"if [ -e {data} ]; then rm -rf {data}"
                    f' && echo "@@REMOVED data {NTFY_DATA_DIR}"'
                    " || failed data-ntfy; fi"
                )
    elif record["adopted"]:
        lines += _restore_lines(svc, record)
    else:
        lines += _stop_lines(svc, record["unit"])
        lines += _remove_managed_lines(svc, record["config"])
    lines.append(f'if [ "$KEEP_{svc}" = 0 ]; then')
    for path in record["tls_files"]:
        host = _host(path)
        if remove_data:
            lines.append(
                f"  if [ -e {host} ]; then rm -f {host}"
                f' && echo "@@REMOVED tls {path}" || failed tls-{svc}; fi'
            )
        else:
            lines.append(f'  if [ -e {host} ]; then echo "@@KEPT {path}"; fi')
    if svc == "coturn":
        data = _host(COTURN_DATA_DIR)
        lines.append(
            f"  if [ -e {data} ]; then rm -rf {data}"
            f' && echo "@@REMOVED data {COTURN_DATA_DIR}"'
            " || failed data-coturn; fi"
        )
    else:
        auth = _host(NTFY_AUTH_FILE)
        lines += [
            f'  if [ -e {auth} ]; then echo "@@KEPT {NTFY_AUTH_FILE}"; fi',
            f"  rmdir {_host(NTFY_TLS_DIR)} 2>/dev/null",
            f"  rmdir {_host(os.path.dirname(NTFY_CONFIG))} 2>/dev/null",
        ]
    lines += ["  :", "fi"]
    return lines


def uninstall_script(state, remove_data, stamp, root=""):
    """Script `sh` de désinstallation, lancé en root sur l'hôte.

    Sans état (`state` None) : `@@PENDING <service>` pour chaque fiche
    d'une installation interrompue, puis `@@NOTHING` ; rien ne change.

    Avec un état, dans l'ordre : ce qu'une désinstallation coupée a laissé
    de côté revient ; les règles consignées partent du pare-feu
    (`firewall_script` « delete », ses lignes `@@FIREWALL_*` relayées) ;
    chaque service consigné est traité par `_service_uninstall_lines` ;
    puis, SEULEMENT si aucune étape n'a échoué, `/etc/erplibre-call` est
    retiré, sauf `tls/` (gardé sans `remove_data`) et les fiches des
    services que l'état ne consigne pas (`@@PENDING_LEFT <service>`), l'état
    en dernier (`@@REMOVED state`). Chaque retrait imprime `@@REMOVED
    <quoi> <chemin ou nom>`, chaque chose gardée `@@KEPT <chemin>`, une
    configuration remise `@@RESTORED <config> <copie>`, un échec `@@FAILED
    <étape>`. Dernière ligne `@@DONE yes` ; `@@DONE no` après un échec, ou
    `@@DONE partial` quand un service adopté sans copie d'origine reste
    configuré par l'outil (`@@BACKUP_MISSING`), avec un code non nul : l'état
    reste, et la relance reprend là où elle s'est arrêtée, chaque étape
    étant sans effet une fois faite. Le service gardé se défait à la relance
    qui suit la remise en place de sa configuration par l'administrateur.

    La base des comptes de ntfy n'est retirée, avec `remove_data`, que si
    l'outil a posé ntfy : celle d'un ntfy adopté porte les comptes et
    jetons d'avant lui ; seul le compte que l'installateur y a ajouté
    (`admin_added`) en part (`@@REMOVED account <nom>`). Refusal `call_infra_state_version` ou
    `call_infra_state_invalid` pour un état qu'on ne peut pas suivre.
    `root` préfixe chaque chemin de l'hôte (tests).
    """
    if not _STAMP.match(stamp or ""):
        raise ValueError(f"stamp: {stamp!r}")
    head = [
        "set -u",
        f"R={shlex.quote(root)}",
        f'CALL="$R"{shlex.quote(CALL_DIR)}',
        f'STATE="$R"{shlex.quote(STATE_PATH)}',
        f'PENDING="$R"{shlex.quote(PENDING_DIR)}',
    ]
    if not isinstance(state, dict):
        return "\n".join(
            head
            + [
                "for s in " + " ".join(SERVICES) + "; do",
                '  if [ -f "$PENDING/$s.json" ]; then echo "@@PENDING $s"; fi',
                "done",
                'echo "@@NOTHING"',
                "",
            ]
        )
    if state.get("version") != STATE_VERSION:
        raise Refusal(
            "call_infra_state_version",
            found=state.get("version"),
            expected=STATE_VERSION,
        )
    records = _uninstall_records(state)
    record = state.get("firewall")
    kind = record.get("kind") if isinstance(record, dict) else None
    rules = rules_from_state(state)
    firewall = (
        firewall_script(kind, rules, "delete", root=root)
        if kind in FIREWALLS
        else ""
    )
    lines = head + [
        "umask 077",
        "OK=1",
        "KEPT=0",
        'failed() { echo "@@FAILED $1"; OK=0; }',
        'D=$(mktemp -d) || { echo "@@FAILED workdir"; echo "@@DONE no";'
        " exit 1; }",
        "trap 'rm -rf \"$D\"' EXIT",
        "trap 'exit 129' HUP INT TERM",
        *_uninstall_helpers(),
        f'for H in "$R"{shlex.quote(HOLD_PREFIX)}*; do',
        '  if [ -d "$H" ]; then held_back "$H"; fi',
        "done",
    ]
    if firewall:
        lines += [
            "# pare-feu",
            _decode_to(_b64(firewall), '"$D/firewall.sh"')
            + " || failed firewall",
            'sh "$D/firewall.sh" > "$D/firewall.out"; FRC=$?',
            "grep -v '^@@END$' \"$D/firewall.out\"",
            '[ "$FRC" = 0 ] || failed firewall',
        ]
    for svc, svc_record in records:
        lines += _service_uninstall_lines(svc, svc_record, remove_data, stamp)
    recorded = [svc for svc, _ in records]
    others = [svc for svc in SERVICES if svc not in recorded]
    tls = '"$CALL/tls"'
    # Un service gardé (KEPT) est encore configuré par l'outil : l'état,
    # ses fiches et `tls/`, que sa configuration nomme, restent.
    lines += [
        'if [ "$OK" = 1 ] && [ "$KEPT" = 0 ]; then',
        *[f'  rm -f "$PENDING/{svc}.json"' for svc in recorded],
        *[
            f'  if [ -f "$PENDING/{svc}.json" ]; then'
            f' echo "@@PENDING_LEFT {svc}"; fi'
            for svc in others
        ],
        '  rm -f "$PENDING/firewall"',
        '  rmdir "$PENDING" 2>/dev/null',
        '  for E in "$CALL"/*; do',
        '    case "${E##*/}" in',
        "      tls|pending|state.json|\\*) ;;",
        '      *) rm -rf "$E" || failed call-dir ;;',
        "    esac",
        "  done",
    ]
    if remove_data:
        lines.append(
            f"  if [ -e {tls} ]; then rm -rf {tls}"
            f' && echo "@@REMOVED tls {COTURN_TLS_DIR}" || failed tls; fi'
        )
    else:
        lines.append(
            f'  if [ -e {tls} ]; then echo "@@KEPT {COTURN_TLS_DIR}"; fi'
        )
    lines += [
        '  if [ "$OK" = 1 ]; then',
        '    rm -f "$STATE" && echo "@@REMOVED state" || failed state',
        "  fi",
        '  rmdir "$CALL" 2>/dev/null',
        "fi",
        'if [ "$OK" = 0 ]; then echo "@@DONE no"; exit 1; fi',
        'if [ "$KEPT" = 1 ]; then echo "@@DONE partial"; exit 1; fi',
        'echo "@@DONE yes"',
        "",
    ]
    return "\n".join(lines)
