#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Infrastructure d'appel en conteneurs : ce qui est propre à Docker et à
Podman, en fonctions pures.

Stdlib seule, et rien n'est lancé d'ici : `call_infra` (qui importe ce
module sous le nom `cc`) place les lignes `sh` rendues ici dans ses scripts
root, les exécute sur l'hôte et relit leur sortie `@@NOM valeur`.

- Images épinglées (`IMAGES`, `IMAGE_VERSIONS`) et noms fixes : projet,
  conteneurs, fichier compose, compte rootless.
- `engine_probe_lines` : la section de la sonde qui lit les moteurs, leur
  outil de composition, les comptes et les conteneurs de l'outil, sans
  rien écrire ; `parse_engine_lines` en fait un `EngineFacts`.
- `compose_text` / `compose_resolved` : le fichier compose, réseau de
  l'hôte et montages aux chemins de la méthode par paquets, de sorte que
  l'hôte garde ses lecteurs (`sqlite3`, pare-feu, nginx) inchangés.
- `engine_argv` / `compose_argv` : la commande du moteur pour le bloc
  `container` de l'état, directe en root ou par `runuser` en rootless ;
  `container_block_problem` refuse un bloc altéré avant qu'il ne serve.
- `engine_packages`, `classify_pull`, `version_older`,
  `foreign_containers` : petites règles que le plan et les scripts
  partagent.
"""

import base64
import binascii
import dataclasses
import json
import re

# Images officielles, épinglées par condensat : le condensat l'emporte sur
# l'étiquette pour les deux moteurs, et le nom complet, registre compris,
# évite que Podman refuse un nom court sans registre de recherche.
IMAGES = {
    "coturn": "docker.io/coturn/coturn:4.18.0@sha256:"
    "bbefd3e1fdfdc0d58770fe01b581fd8b00d9f3a5580d00acb77cf719a6bc78e3",
    "ntfy": "docker.io/binwiederhier/ntfy:v2.36.0@sha256:"
    "fb48c413eb11d50339962b5d62cddce0f800e7f77c626d638a7c20cb7e9c4465",
}
IMAGE_VERSIONS = {"coturn": "4.18.0", "ntfy": "2.36.0"}

# Les mêmes que `container_runtime.MOTEURS` (un test le garde) : écrits ici
# pour que ce module n'importe que la stdlib.
ENGINES = ("docker", "podman")

# Outil de composition par moteur, dans l'ordre de préférence. Docker : le
# greffon v2, puis le binaire. Podman : podman-compose appelé directement ;
# « podman compose » n'est qu'un relais qui préfère docker-compose et parle
# alors à la socket de Podman.
COMPOSE_PROVIDERS = {
    "docker": (("docker", "compose"), ("docker-compose",)),
    "podman": (("podman-compose",),),
}

PROJECT = "erplibre-call"
CONTAINERS = {"coturn": "erplibre-call-coturn", "ntfy": "erplibre-call-ntfy"}
COMPOSE_FILE = "/etc/erplibre-call/compose.yml"
ROOTLESS_ACCOUNT = "erplibre-call"
ROOTLESS_HOME = "/var/lib/erplibre-call-podman"
# coturn tourne sous le compte du paquet quand il existe, sinon sous le
# compte système que l'outil crée.
COTURN_ACCOUNTS = ("turnserver", "erplibre-coturn")
NTFY_ACCOUNT = "ntfy"
# `\Z` et non `$`, qui accepte un saut de ligne final : un nom de compte
# tient sur une ligne des sorties `@@NOM valeur` et du hook de déploiement.
ACCOUNT_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}\Z")
# Comptes dont la sonde rend uid et gid.
PROBED_ACCOUNTS = COTURN_ACCOUNTS + (NTFY_ACCOUNT, ROOTLESS_ACCOUNT)

# Première ligne du fichier compose : la même marque que les fichiers que
# `call_infra` écrit (MARKER), un test garde l'égalité.
MANAGED_LINE = "# erplibre-call: managed"

# Montages aux chemins de la méthode par paquets (les mêmes constantes que
# `call_infra`, un test garde l'égalité) : la base de coturn, ses copies
# TLS, la configuration de ntfy (TLS propre compris), son cache et sa base
# d'utilisateurs.
COTURN_DATA_DIR = "/var/lib/erplibre-call"
COTURN_TLS_DIR = "/etc/erplibre-call/tls"
NTFY_CONFIG_DIR = "/etc/ntfy"
NTFY_CACHE_DIR = "/var/cache/ntfy"
NTFY_DATA_DIR = "/var/lib/ntfy"

# Stockage de Podman en root : sans lui, « podman ps » le créerait.
PODMAN_ROOT_STORAGE = "/var/lib/containers/storage"
# Stockage rootless, relatif au dossier personnel du compte.
PODMAN_USER_STORAGE = ".local/share/containers/storage"

# Refus du registre pour excès de requêtes : Docker Hub répond HTTP 429 et
# « toomanyrequests ». Motif lu de même par `re` (re.I | re.M) et par
# `LC_ALL=C grep -iE`, pour qu'un script shell applique la même règle : ni
# `\t` ni classe nommée, que l'ERE de POSIX ne lit pas comme `re`. « 429 »
# compte seul, entre deux caractères qui ne sont ni lettre ni chiffre.
PULL_RATE_LIMIT = r"toomanyrequests|(^|[^0-9A-Za-z])429([^0-9A-Za-z]|$)"

# Paquets par famille : moteur, outil de composition, newuidmap pour le
# rootless (dans « shadow », toujours là, sur Arch).
_ENGINE_PACKAGES = {
    "debian": {"docker": "docker.io", "podman": "podman"},
    "arch": {"docker": "docker", "podman": "podman"},
}
_COMPOSE_PACKAGES = {
    "debian": {"docker": "docker-compose", "podman": "podman-compose"},
    "ubuntu": {"docker": "docker-compose-v2", "podman": "podman-compose"},
    "arch": {"docker": "docker-compose", "podman": "podman-compose"},
}
# Ubuntu et ses dérivées nomment « docker-compose » l'ancien v1 ; le v2 y
# est « docker-compose-v2 ».
_UBUNTU_IDS = {"ubuntu", "linuxmint", "pop"}

# Marqueurs de la section des moteurs dans la sortie de la sonde.
ENGINE_MARKERS = frozenset(
    {
        "ENGINE",
        "COMPOSE",
        "DOCKER_SERVICE",
        "PODMAN_RESTART",
        "UNPRIV_PORT",
        "ACCOUNT",
        "ROOTLESS",
        "CONTAINER",
        "IMAGE",
        "NTFY_HOST",
        "SQLITE",
        "COMPOSE_FILE",
    }
)

_VERSION = re.compile(r"^v?[0-9][0-9A-Za-z.+~-]*$")
_UNIT_ANSWER = re.compile(r"^[a-z-]+$")
_CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_STATUS = re.compile(r"^[a-z]+$")
_IMAGE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]*$")
_CONFIG_PATH = re.compile(r"^/[A-Za-z0-9._/-]+$")
_USER = re.compile(r"^([0-9]+):([0-9]+)$")
_USER_TOKEN = re.compile(r"@USER_([A-Z]+)@")
_MAX_ID = 2**31 - 1
# Format de `ps` commun aux deux moteurs : nom, état, image.
_PS_FORMAT = "{{.Names}} {{.State}} {{.Image}}"
# Filtre de `ps` : les conteneurs de l'outil par leur nom, et tout
# conteneur lancé d'une image coturn ou ntfy officielle, sous un autre nom.
_PS_AWK = (
    "$1 ~ /^erplibre-call-/ || $3 ~ /(^|\\/)coturn\\/coturn([:@]|$)/"
    " || $3 ~ /(^|\\/)binwiederhier\\/ntfy([:@]|$)/"
    ' { print "@@CONTAINER " $1 " " e " " r " " $2 " " $3 }'
)
_VERSION_SED = (
    "s/^.*[Vv]ersion[[:space:]][[:space:]]*v\\{0,1\\}"
    "\\([0-9][^[:space:],]*\\).*/\\1/p"
)
_NTFY_VERSION_SED = (
    "s/^ntfy[[:space:]][[:space:]]*v\\{0,1\\}\\([0-9][^[:space:]]*\\).*/\\1/p"
)


@dataclasses.dataclass(frozen=True)
class EngineFacts:
    """Ce que la section des moteurs de la sonde a lu.

    `engines` : moteur → version du client (`--version`, sans démon).
    `compose` : moteur → premier outil de composition trouvé, en mots
    (`("docker", "compose")`, `("docker-compose",)`, `("podman-compose",)`).
    `docker_service` : (is-active, is-enabled) de docker.service, None
    sans Docker. `podman_restart` : is-enabled de podman-restart.service en
    root, None sans Podman. `unpriv_port_start` : premier port qu'un compte
    sans privilège peut lier. `accounts` : nom → (uid, gid) des comptes de
    PROBED_ACCOUNTS qui existent. `rootless` : faits du compte
    ROOTLESS_ACCOUNT quand il existe (`subuid`, `subgid`, `linger`,
    `newuidmap` : bool, `user_restart` : is-enabled du podman-restart de
    l'utilisateur, None sans session), None sinon ; `newuidmap` est aussi
    rendu seul, compte ou non, pour dire s'il faut le paquet.
    `containers` : (nom, moteur, rootless, état, image) de chaque conteneur
    de l'outil ou lancé d'une image coturn ou ntfy. `images` : (moteur,
    rootless, référence) de chaque image épinglée présente.
    `ntfy_host_version` : version du binaire ntfy de l'hôte, None sans lui.
    `sqlite3` : le client sqlite3 de l'hôte est là. `compose_text` : le
    fichier COMPOSE_FILE présent, vide sans lui.
    """

    engines: dict = dataclasses.field(default_factory=dict)
    compose: dict = dataclasses.field(default_factory=dict)
    docker_service: tuple | None = None
    podman_restart: str | None = None
    unpriv_port_start: int = 1024
    accounts: dict = dataclasses.field(default_factory=dict)
    rootless: dict | None = None
    containers: tuple = ()
    images: tuple = ()
    ntfy_host_version: str | None = None
    sqlite3: bool = False
    compose_text: str = ""
    newuidmap: bool = False


# --- Commandes ----------------------------------------------------------------


def _prefix_words(account, uid_text):
    return [
        "runuser",
        "-u",
        account,
        "--",
        "env",
        f"XDG_RUNTIME_DIR=/run/user/{uid_text}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid_text}/bus",
    ]


def rootless_prefix(account, uid):
    """Préfixe qui lance une commande, depuis root, sous le compte rootless
    et dans sa session : Podman y trouve son stockage et son runtime, et
    `systemctl --user` le bus de l'utilisateur."""
    return _prefix_words(account, str(int(uid)))


def rootless_prefix_sh(account, uid_var):
    """Le préfixe de `rootless_prefix` en texte `sh`, l'uid pris à la
    variable `uid_var` du script au moment de l'appel : un script root qui
    crée le compte ne connaît son uid qu'en cours de route."""
    if not _valid_account(account) or not re.match(
        r"^[A-Z_][A-Z0-9_]*$", uid_var or ""
    ):
        raise ValueError(f"rootless prefix: {account!r} {uid_var!r}")
    return " ".join(_sh_word(w) for w in _prefix_words(account, f"${uid_var}"))


def _valid_id(value):
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 1 <= value <= _MAX_ID
    )


def _valid_account(value):
    return (
        isinstance(value, str)
        and bool(ACCOUNT_RE.match(value))
        and value != "root"
    )


def _block_problem(block):
    """Nom du premier champ invalide du bloc `container`, ou None."""
    if not isinstance(block, dict):
        return "container"
    engine = block.get("engine")
    if engine not in ENGINES:
        return "engine"
    rootless = block.get("rootless")
    if not isinstance(rootless, bool) or (rootless and engine != "podman"):
        return "rootless"
    if rootless:
        if not _valid_account(block.get("account")):
            return "account"
        if not _valid_id(block.get("uid")):
            return "uid"
    else:
        # En root, chaque service a son compte : le bloc n'en porte aucun.
        if block.get("account") is not None:
            return "account"
        if block.get("uid") is not None:
            return "uid"
    compose = block.get("compose")
    if not isinstance(compose, (list, tuple)) or tuple(
        compose
    ) not in COMPOSE_PROVIDERS.get(engine, ()):
        return "compose"
    if block.get("compose_file", COMPOSE_FILE) != COMPOSE_FILE:
        return "compose_file"
    if block.get("project", PROJECT) != PROJECT:
        return "project"
    return None


def container_block_problem(state):
    """Nom du premier champ invalide de l'état en mode conteneur, ou None.

    Le bloc `container` : moteur de ENGINES, `rootless` booléen (Podman
    seulement), compte (ACCOUNT_RE, jamais root) et uid (1 à 2³¹−1) du
    compte rootless, ou tous deux None en root, outil de composition parmi
    COMPOSE_PROVIDERS du moteur, fichier et projet fixes. Chaque service :
    `container` égal à CONTAINERS, `account`, `uid` et `gid` valides. Un
    état altéré n'atteint ainsi aucune commande root.
    """
    if not isinstance(state, dict):
        return "container"
    problem = _block_problem(state.get("container"))
    if problem:
        return problem
    services = state.get("services", {})
    if not isinstance(services, dict):
        return "services"
    for svc, record in services.items():
        if svc not in CONTAINERS or not isinstance(record, dict):
            return f"services.{svc}"
        if record.get("container") != CONTAINERS[svc]:
            return f"services.{svc}.container"
        if not _valid_account(record.get("account")):
            return f"services.{svc}.account"
        for key in ("uid", "gid"):
            if not _valid_id(record.get(key)):
                return f"services.{svc}.{key}"
    return None


def _checked_block(block):
    problem = _block_problem(block)
    if problem:
        raise ValueError(f"container block: invalid {problem}")
    return block


def engine_argv(block):
    """Commande du moteur pour le bloc `container` de l'état : `["docker"]`
    ou `["podman"]` en root, précédée de `rootless_prefix` en rootless.
    ValueError pour un bloc invalide."""
    block = _checked_block(block)
    prefix = []
    if block["rootless"]:
        prefix = rootless_prefix(block["account"], block["uid"])
    return prefix + [block["engine"]]


def compose_argv(block):
    """Commande de composition pour le bloc `container` : l'outil consigné,
    puis `-f COMPOSE_FILE -p PROJECT` ; précédée de `rootless_prefix` en
    rootless. ValueError pour un bloc invalide."""
    block = _checked_block(block)
    prefix = []
    if block["rootless"]:
        prefix = rootless_prefix(block["account"], block["uid"])
    return (
        prefix + list(block["compose"]) + ["-f", COMPOSE_FILE, "-p", PROJECT]
    )


# --- Fichier compose ---------------------------------------------------------


def _mounts(svc, coturn_conf_path):
    if svc == "coturn":
        return (
            f"{COTURN_DATA_DIR}:{COTURN_DATA_DIR}",
            f"{COTURN_TLS_DIR}:{COTURN_TLS_DIR}:ro",
            f"{coturn_conf_path}:{coturn_conf_path}:ro",
        )
    return (
        f"{NTFY_CONFIG_DIR}:{NTFY_CONFIG_DIR}:ro",
        f"{NTFY_CACHE_DIR}:{NTFY_CACHE_DIR}",
        f"{NTFY_DATA_DIR}:{NTFY_DATA_DIR}",
    )


def compose_text(services, coturn_conf_path, rootless):
    """Gabarit du fichier compose, services dans l'ordre de CONTAINERS.

    Réseau de l'hôte (aucun port publié : le pare-feu et nginx restent
    ceux de la méthode par paquets), `restart: always` (le seul que
    podman-restart relance au démarrage), `user: "@USER_<SVC>@"` que
    `compose_resolved` remplace par l'uid:gid lu sur l'hôte, et en
    rootless `userns_mode: keep-id` pour que les fichiers montés gardent
    leur propriétaire de l'hôte. Aucun `no-new-privileges` : en root, coturn
    lie 443 par la capacité posée sur son binaire. `x-podman: in_pod:
    false` empêche podman-compose de grouper les conteneurs en pod, où
    Podman refuse le réseau de l'hôte et `--userns` ; Docker ignore une
    clé `x-`.
    """
    chosen = [svc for svc in CONTAINERS if svc in services]
    if not chosen or set(services) - set(CONTAINERS):
        raise ValueError(f"compose services: {sorted(services)}")
    if not _CONFIG_PATH.match(coturn_conf_path or ""):
        raise ValueError(f"coturn config path: {coturn_conf_path!r}")
    commands = {"coturn": ["-c", coturn_conf_path], "ntfy": ["serve"]}
    lines = [MANAGED_LINE, "x-podman:", "  in_pod: false", "services:"]
    for svc in chosen:
        lines += [
            f"  {svc}:",
            f"    image: {IMAGES[svc]}",
            f"    container_name: {CONTAINERS[svc]}",
            "    network_mode: host",
            "    restart: always",
            f'    user: "@USER_{svc.upper()}@"',
        ]
        if rootless:
            lines.append("    userns_mode: keep-id")
        lines.append(f"    command: {json.dumps(commands[svc])}")
        lines.append("    volumes:")
        lines += [
            f"      - {mount}" for mount in _mounts(svc, coturn_conf_path)
        ]
    return "\n".join(lines) + "\n"


def compose_resolved(template, users):
    """Le gabarit de `compose_text`, chaque `@USER_<SVC>@` remplacé par
    `users[svc]` (« uid:gid », ids de 1 à 2³¹−1 : jamais root).
    ValueError pour un service sans valeur ou une valeur hors de cette
    forme."""

    def user(match):
        svc = match.group(1).lower()
        value = users.get(svc)
        found = _USER.match(value) if isinstance(value, str) else None
        if not found or not all(
            1 <= int(part) <= _MAX_ID for part in found.groups()
        ):
            raise ValueError(f"compose user for {svc}: {value!r}")
        return value

    return _USER_TOKEN.sub(user, template)


# --- Sonde -------------------------------------------------------------------


def _sh_word(word):
    """Un mot de commande pour `sh` : entre guillemets doubles s'il porte
    une variable à développer, sinon entre apostrophes au besoin."""
    if "$" in word:
        return f'"{word}"'
    if re.match(r"^[A-Za-z0-9_./:=@-]+$", word):
        return word
    return "'" + word.replace("'", "'\\''") + "'"


def _quote(text):
    return "'" + text.replace("'", "'\\''") + "'"


def engine_probe_lines(root=""):
    """Lignes `sh` (root, lecture seule) de la section des moteurs.

    `root` préfixe chaque chemin lu ; vide sur un vrai hôte. Chaque appel
    d'un moteur passe par `timeout 20`, et ceux du compte rootless par
    `rootless_prefix`. Rien n'est créé ni réveillé : les versions viennent
    du client (`--version`) ; Docker n'est interrogé (`ps`, `image
    inspect`) que si docker.service tourne déjà, puisqu'une socket active
    lancerait le démon ; Podman en root seulement si son stockage existe,
    que `ps` créerait ; le compte rootless seulement s'il existe et que
    /run/user/<uid> et son stockage existent.

    Lignes : `@@ENGINE <moteur> <version>`, `@@COMPOSE <moteur> <mots>`,
    `@@DOCKER_SERVICE <actif> <activé>`, `@@PODMAN_RESTART <activé>`,
    `@@UNPRIV_PORT <n>`, `@@ACCOUNT <nom> <uid> <gid>`, `@@ROOTLESS
    <subuid> <subgid> <linger> <newuidmap> <podman-restart utilisateur>`
    (0|1, « - » sans session), `@@CONTAINER <nom> <moteur> <0|1> <état>
    <image>`, `@@IMAGE <moteur> <0|1> <référence>` par image épinglée
    présente, `@@NTFY_HOST <version>`, `@@SQLITE <0|1>`, `@@COMPOSE_FILE
    <base64>`.
    """
    refs = " ".join(_quote(ref) for ref in IMAGES.values())
    acct = ROOTLESS_ACCOUNT
    rl = " ".join(_sh_word(w) for w in _prefix_words(acct, "$E_RU"))
    ps = f"ps -a --format {_quote(_PS_FORMAT)}"
    version = f"sed -n {_quote(_VERSION_SED)} | head -n 1"
    return [
        f"R={_quote(root)}",
        # Moteurs : la version du client, qui répond sans démon.
        "E_D=; E_P=",
        "if command -v docker >/dev/null 2>&1; then",
        f"  E_D=$(timeout 20 docker --version 2>/dev/null | {version})",
        '  echo "@@ENGINE docker ${E_D:--}"',
        "fi",
        "if command -v podman >/dev/null 2>&1; then",
        f"  E_P=$(timeout 20 podman --version 2>/dev/null | {version})",
        '  echo "@@ENGINE podman ${E_P:--}"',
        "fi",
        "if command -v docker >/dev/null 2>&1"
        " && timeout 20 docker compose version >/dev/null 2>&1; then",
        '  echo "@@COMPOSE docker docker compose"',
        "elif command -v docker-compose >/dev/null 2>&1; then",
        '  echo "@@COMPOSE docker docker-compose"',
        "fi",
        "if command -v podman-compose >/dev/null 2>&1; then",
        '  echo "@@COMPOSE podman podman-compose"',
        "fi",
        "E_DA=",
        "if command -v docker >/dev/null 2>&1; then",
        "  E_DA=$(systemctl is-active docker.service 2>/dev/null)",
        "  E_DE=$(systemctl is-enabled docker.service 2>/dev/null)",
        '  echo "@@DOCKER_SERVICE ${E_DA:--} ${E_DE:--}"',
        "fi",
        "if command -v podman >/dev/null 2>&1; then",
        "  E_PR=$(systemctl is-enabled podman-restart.service 2>/dev/null)",
        '  echo "@@PODMAN_RESTART ${E_PR:--}"',
        "fi",
        'E_UP=$(cat "$R/proc/sys/net/ipv4/ip_unprivileged_port_start"'
        " 2>/dev/null)",
        'case "$E_UP" in ""|*[!0-9]*) E_UP=1024 ;; esac',
        'echo "@@UNPRIV_PORT $E_UP"',
        f"for E_A in {' '.join(PROBED_ACCOUNTS)}; do",
        '  getent passwd "$E_A" 2>/dev/null | awk -F: -v a="$E_A"'
        ' \'NR == 1 { print "@@ACCOUNT " a " " $3 " " $4 }\'',
        "done",
        # Compte rootless : uid et dossier personnel du passwd.
        f"E_RP=$(getent passwd {acct} 2>/dev/null | head -n 1)",
        "E_RU=$(printf '%s\\n' \"$E_RP\" | awk -F: '{ print $3 }')",
        "E_RH=$(printf '%s\\n' \"$E_RP\" | awk -F: '{ print $6 }')",
        'case "$E_RU" in ""|*[!0-9]*) E_RU= ;; esac',
        "E_SU=0; E_SG=0; E_LI=0; E_NU=0; E_UR=-; E_RS=",
        'if [ -n "$E_RU" ]; then',
        f'  grep -qE "^({acct}|$E_RU):" "$R/etc/subuid" 2>/dev/null'
        " && E_SU=1",
        f'  grep -qE "^({acct}|$E_RU):" "$R/etc/subgid" 2>/dev/null'
        " && E_SG=1",
        f'  [ -e "$R/var/lib/systemd/linger/{acct}" ] && E_LI=1',
        '  if [ -d "$R/run/user/$E_RU" ]; then',
        f"    E_UR=$(timeout 20 {rl} systemctl --user is-enabled"
        " podman-restart.service 2>/dev/null)",
        f'    [ -n "$E_RH" ] && [ -d "$R$E_RH/{PODMAN_USER_STORAGE}" ]'
        " && E_RS=1",
        "  fi",
        "fi",
        "command -v newuidmap >/dev/null 2>&1 && E_NU=1",
        'echo "@@ROOTLESS $E_SU $E_SG $E_LI $E_NU ${E_UR:--}"',
        # Conteneurs et images épinglées, sans réveiller ni créer.
        'if [ -n "$E_D" ] && [ "$E_DA" = active ]; then',
        f"  timeout 20 docker {ps} 2>/dev/null"
        f" | awk -v e=docker -v r=0 {_quote(_PS_AWK)}",
        f"  for E_I in {refs}; do",
        '    timeout 20 docker image inspect "$E_I" >/dev/null 2>&1'
        ' && echo "@@IMAGE docker 0 $E_I"',
        "  done",
        "fi",
        f'if [ -n "$E_P" ] && [ -d "$R{PODMAN_ROOT_STORAGE}" ]; then',
        f"  timeout 20 podman {ps} 2>/dev/null"
        f" | awk -v e=podman -v r=0 {_quote(_PS_AWK)}",
        f"  for E_I in {refs}; do",
        '    timeout 20 podman image exists "$E_I" >/dev/null 2>&1'
        ' && echo "@@IMAGE podman 0 $E_I"',
        "  done",
        "fi",
        'if [ -n "$E_P" ] && [ -n "$E_RS" ]; then',
        f"  timeout 20 {rl} podman {ps} 2>/dev/null"
        f" | awk -v e=podman -v r=1 {_quote(_PS_AWK)}",
        f"  for E_I in {refs}; do",
        f'    timeout 20 {rl} podman image exists "$E_I" >/dev/null 2>&1'
        ' && echo "@@IMAGE podman 1 $E_I"',
        "  done",
        "fi",
        "if command -v ntfy >/dev/null 2>&1; then",
        "  E_NV=$(timeout 20 ntfy --version 2>/dev/null"
        f" | sed -n {_quote(_NTFY_VERSION_SED)} | head -n 1)",
        '  [ -n "$E_NV" ] && echo "@@NTFY_HOST $E_NV"',
        "fi",
        "if command -v sqlite3 >/dev/null 2>&1; then echo '@@SQLITE 1';"
        " else echo '@@SQLITE 0'; fi",
        f'if [ -f "$R{COMPOSE_FILE}" ]; then',
        f'  echo "@@COMPOSE_FILE $(base64 -w0 < "$R{COMPOSE_FILE}")"',
        "fi",
    ]


def _flag(value):
    return {"0": False, "1": True}.get(value)


def _decode(value):
    try:
        return base64.b64decode(value.strip(), validate=True).decode(
            "utf-8", "replace"
        )
    except (binascii.Error, ValueError):
        return None


def parse_engine_lines(pairs):
    """`EngineFacts` des paires (NOM, valeur) de la section des moteurs ;
    les autres noms sont ignorés, une ligne mal formée aussi."""
    engines, compose, accounts = {}, {}, {}
    containers, images = [], []
    docker_service, podman_restart, port = None, None, 1024
    rootless_line, ntfy, sqlite3, text = None, None, False, ""
    for name, value in pairs:
        parts = value.split()
        if name == "ENGINE":
            if (
                len(parts) == 2
                and parts[0] in ENGINES
                and _VERSION.match(parts[1])
            ):
                engines[parts[0]] = parts[1]
        elif name == "COMPOSE":
            if parts and parts[0] in ENGINES:
                words = tuple(parts[1:])
                if words in COMPOSE_PROVIDERS[parts[0]]:
                    compose.setdefault(parts[0], words)
        elif name == "DOCKER_SERVICE":
            if len(parts) == 2 and all(
                p == "-" or _UNIT_ANSWER.match(p) for p in parts
            ):
                docker_service = (parts[0], parts[1])
        elif name == "PODMAN_RESTART":
            current = value.strip()
            if current != "-" and _UNIT_ANSWER.match(current):
                podman_restart = current
        elif name == "UNPRIV_PORT":
            current = value.strip()
            if current.isdigit() and int(current) <= 65536:
                port = int(current)
        elif name == "ACCOUNT":
            if (
                len(parts) == 3
                and parts[0] in PROBED_ACCOUNTS
                and parts[1].isdigit()
                and parts[2].isdigit()
            ):
                accounts[parts[0]] = (int(parts[1]), int(parts[2]))
        elif name == "ROOTLESS":
            flags = [_flag(p) for p in parts[:4]]
            if len(parts) == 5 and None not in flags:
                rootless_line = flags + [parts[4]]
        elif name == "CONTAINER":
            if (
                len(parts) == 5
                and _CONTAINER_NAME.match(parts[0])
                and parts[1] in ENGINES
                and _flag(parts[2]) is not None
                and _STATUS.match(parts[3])
                and _IMAGE_REF.match(parts[4])
            ):
                entry = (
                    parts[0],
                    parts[1],
                    _flag(parts[2]),
                    parts[3],
                    parts[4],
                )
                if entry not in containers:
                    containers.append(entry)
        elif name == "IMAGE":
            if (
                len(parts) == 3
                and parts[0] in ENGINES
                and _flag(parts[1]) is not None
                and parts[2] in IMAGES.values()
            ):
                entry = (parts[0], _flag(parts[1]), parts[2])
                if entry not in images:
                    images.append(entry)
        elif name == "NTFY_HOST":
            current = value.strip()
            if _VERSION.match(current):
                ntfy = current
        elif name == "SQLITE":
            sqlite3 = value.strip() == "1"
        elif name == "COMPOSE_FILE":
            text = _decode(value) or ""
    newuidmap = bool(rootless_line and rootless_line[3])
    rootless = None
    if rootless_line and ROOTLESS_ACCOUNT in accounts:
        restart = rootless_line[4]
        rootless = {
            "subuid": rootless_line[0],
            "subgid": rootless_line[1],
            "linger": rootless_line[2],
            "newuidmap": rootless_line[3],
            "user_restart": (
                restart
                if restart != "-" and _UNIT_ANSWER.match(restart)
                else None
            ),
        }
    return EngineFacts(
        engines=engines,
        compose=compose,
        docker_service=docker_service,
        podman_restart=podman_restart,
        unpriv_port_start=port,
        accounts=accounts,
        rootless=rootless,
        containers=tuple(containers),
        images=tuple(images),
        ntfy_host_version=ntfy,
        sqlite3=sqlite3,
        compose_text=text,
        newuidmap=newuidmap,
    )


# --- Règles partagées --------------------------------------------------------


def engine_packages(os_id, family, engine, rootless, facts):
    """Paquets de la distribution qui manquent pour `engine` : le moteur,
    son outil de composition, et pour le rootless newuidmap (« uidmap »
    sur Debian et Ubuntu). `facts` (EngineFacts, ou None : rien n'est là)
    dit ce qui est déjà présent. ValueError pour un moteur, une famille ou
    un rootless hors de ce que l'outil installe."""
    if engine not in ENGINES or family not in _ENGINE_PACKAGES:
        raise ValueError(f"engine packages: {engine} on {family}")
    if rootless and engine != "podman":
        raise ValueError("rootless needs podman")
    facts = facts or EngineFacts()
    flavour = "ubuntu" if os_id in _UBUNTU_IDS else family
    wanted = []
    if engine not in facts.engines:
        wanted.append(_ENGINE_PACKAGES[family][engine])
    if engine not in facts.compose:
        wanted.append(_COMPOSE_PACKAGES[flavour][engine])
    if rootless and family == "debian" and not facts.newuidmap:
        wanted.append("uidmap")
    return tuple(wanted)


def classify_pull(output):
    """« rate-limit » quand la sortie d'un pull dit le refus du registre
    pour excès de requêtes (PULL_RATE_LIMIT), « failed » sinon."""
    if re.search(PULL_RATE_LIMIT, output or "", re.I | re.M):
        return "rate-limit"
    return "failed"


def _version_tuple(text):
    match = re.match(r"^v?([0-9]+(?:\.[0-9]+)*)", text.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def version_older(found, pinned):
    """`found` est-il antérieur à `pinned` ? Seul le préfixe numérique
    compte (« 26.1.5+dfsg1 » vaut 26.1.5, « v2.36.0 » vaut 2.36.0). Une
    version `found` illisible compte pour plus ancienne : le doute ne doit
    pas laisser un binaire relire une base qu'il refuserait. ValueError
    pour un `pinned` illisible."""
    want = _version_tuple(pinned)
    if want is None:
        raise ValueError(f"pinned version: {pinned!r}")
    have = _version_tuple(found or "")
    if have is None:
        return True
    width = max(len(have), len(want))
    return have + (0,) * (width - len(have)) < want + (0,) * (
        width - len(want)
    )


def foreign_containers(facts, state):
    """Noms triés des conteneurs vus par la sonde que l'état ne consigne pas
    comme les siens : ceux de l'outil quand l'état n'est pas en mode
    conteneur, sous un autre moteur ou mode, ou pour un service qu'il ne
    consigne pas, et tout conteneur d'une image coturn ou ntfy sous un autre
    nom."""
    if facts is None:
        return ()
    ours = set()
    if isinstance(state, dict) and state.get("method") == "container":
        block = state.get("container")
        services = state.get("services")
        if isinstance(block, dict) and isinstance(services, dict):
            for svc, record in services.items():
                if isinstance(record, dict) and svc in CONTAINERS:
                    if record.get("container") == CONTAINERS[svc]:
                        ours.add(
                            (
                                CONTAINERS[svc],
                                block.get("engine"),
                                block.get("rootless"),
                            )
                        )
    return tuple(
        sorted(
            {
                name
                for name, engine, rootless, _, _ in facts.containers
                if (name, engine, rootless) not in ours
            }
        )
    )
