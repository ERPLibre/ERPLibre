#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""ntfy pour ERPLibre mobile : contrôles, accès du téléphone, lien, QR.

Fonctions pures (stdlib seule au niveau du module) : le menu de `todo.py` et
le banc d'essai les appellent, les scripts shell qu'elles construisent sont
exécutés par `LocalHost` ou `SshHost`.

Chaque appel `ntfy` d'un script porte `--config <fichier>` : sans lui la CLI
lit `/etc/ntfy/server.yml`. Pour `ntfy user` et `ntfy token`, `--config`
précède la sous-commande ; `ntfy access` l'accepte avant ses arguments.
"""

import base64
import codecs
import difflib
import io
import os
import re
import secrets
import shlex
import subprocess
import sys
import unicodedata
import urllib.parse

DEFAULT_CONFIG = "/etc/ntfy/server.yml"
PHONE_USER_PREFIX = "erm_"
LINK_SCHEME = "erplibre-ntfy:"

DEFAULT_CACHE_SECONDS = 43200
EXEMPT_HOSTS_KEY = "visitor-request-limit-exempt-hosts"
RATE_LIMITING_KEY = "visitor-subscriber-rate-limiting"

_PREFIX_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
_KEY_LINE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?:\s+(.*))?$")
_TOKEN_LINE = re.compile(r"token (tk_[A-Za-z0-9]+) created")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def random_prefix(rng=secrets):
    """`up` + 8 caractères de `[a-z0-9]` : préfixe des sujets d'un téléphone."""
    return "up" + "".join(rng.choice(_PREFIX_ALPHABET) for _ in range(8))


def phone_user(label):
    """Nom d'utilisateur ntfy d'un téléphone : `erm_` + libellé assaini.

    Le libellé est décomposé (NFD), ses marques retirées, mis en minuscules,
    et les caractères hors `[a-z0-9_-]` sont écartés.
    ValueError quand il ne reste rien.
    """
    folded = unicodedata.normalize("NFD", label)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    kept = re.sub(r"[^a-z0-9_-]", "", folded.lower())
    if not kept:
        raise ValueError("empty phone label")
    return PHONE_USER_PREFIX + kept


def _yml_value(raw):
    """Valeur d'une ligne `clé: valeur` : guillemets retirés, note coupée."""
    raw = (raw or "").strip()
    if raw[:1] in ("'", '"'):
        end = raw.find(raw[0], 1)
        return raw[1:end] if end > 0 else raw[1:]
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip()


def read_yml_keys(text):
    """Clés de premier niveau d'un `server.yml` plat, sans bibliothèque YAML.

    Les lignes indentées et les commentaires sont ignorés ; la dernière
    occurrence d'une clé gagne.
    """
    keys = {}
    for line in text.splitlines():
        if not line or line[0] in " \t#":
            continue
        match = _KEY_LINE.match(line.rstrip())
        if match:
            keys[match.group(1)] = _yml_value(match.group(2))
    return keys


def config_problems(keys):
    """Clés i18n des défauts du serveur incompatibles avec l'usage mobile."""
    problems = []
    if not keys.get("auth-file"):
        problems.append("ntfy_mobile_no_auth_file")
    if keys.get("auth-default-access") != "deny-all":
        problems.append("ntfy_mobile_not_deny_all")
    if keys.get(RATE_LIMITING_KEY, "").lower() in ("true", "yes", "on", "1"):
        problems.append("ntfy_mobile_subscriber_rate_limiting")
    return problems


def cache_seconds(keys):
    """`cache-duration` en secondes (`12h`, `30m`, `3600s`, `2d`) ; 12 h sinon."""
    match = re.fullmatch(
        r"(\d+)\s*([smhd]?)", keys.get("cache-duration", "").strip()
    )
    if not match:
        return DEFAULT_CACHE_SECONDS
    return int(match.group(1)) * _UNITS[match.group(2) or "s"]


def _set_key(text, key, value, quoted):
    """Remplace la première ligne active de `key`, ou en ajoute une.

    Les autres lignes restent identiques à l'octet près.
    """
    shown = f'"{value}"' if quoted else value
    new_line = f"{key}: {shown}"
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if re.match(rf"{re.escape(key)}\s*:", line):
            ending = line[len(line.rstrip("\r\n")) :]
            lines[index] = new_line + ending
            return "".join(lines)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + new_line + "\n"


def with_exempt_hosts(text, hosts):
    """`visitor-request-limit-exempt-hosts` = valeur présente ∪ `hosts`.

    Liste séparée par des virgules, ordre conservé, sans doublon. Rien n'est
    modifié quand tous les hôtes y sont déjà.
    """
    present = read_yml_keys(text).get(EXEMPT_HOSTS_KEY, "")
    old = [h.strip() for h in present.split(",") if h.strip()]
    merged = old + [h for h in dict.fromkeys(hosts) if h not in old]
    if merged == old and (present or not hosts):
        return text
    return _set_key(text, EXEMPT_HOSTS_KEY, ",".join(merged), True)


def with_subscriber_rate_limiting_off(text):
    """Met `visitor-subscriber-rate-limiting` à `false` ; rien si déjà fait."""
    if read_yml_keys(text).get(RATE_LIMITING_KEY, "").lower() == "false":
        return text
    return _set_key(text, RATE_LIMITING_KEY, "false", False)


def unified_diff(old, new, path):
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=path,
            tofile=path,
        )
    )


def access_script(config, user, prefix, label="erplibre-mobile"):
    """Script `sh` qui ouvre l'accès d'un téléphone et crée son jeton.

    Anonyme : écriture seule sur `up*` (le serveur Odoo publie sans
    identité). Le téléphone : lecture seule sur `<prefix>*`, mot de passe
    aléatoire jeté, jeton sans expiration. Le jeton est la dernière sortie.
    """
    cfg = shlex.quote(config)
    usr = shlex.quote(user)
    return "\n".join(
        [
            "set -e",
            f"ntfy access --config {cfg} everyone {shlex.quote('up*')}"
            " write-only",
            'NTFY_PASSWORD="$(head -c 32 /dev/urandom | base64)"'
            f" ntfy user --config {cfg} add --ignore-exists {usr}",
            f"ntfy access --config {cfg} {usr}"
            f" {shlex.quote(prefix + '*')} read-only",
            f"ntfy token --config {cfg} add"
            f" {shlex.quote('--label=' + label)} {usr}",
            "",
        ]
    )


def inspect_script(config):
    """Script qui imprime version, propriétaire, `server.yml` et santé.

    Une ligne `@@NOM valeur` par fait ; `parse_markers` les relit.
    """
    cfg = shlex.quote(config)
    return "\n".join(
        [
            f"C={cfg}",
            'echo "@@VERSION $(ntfy --version 2>&1 | head -n 1)"',
            'key() { sed -n "s/^$1:[[:space:]]*[\\"\']\\{0,1\\}'
            '\\([^\\"\'#]*\\).*/\\1/p" "$C" 2>/dev/null | head -n 1; }',
            'A="$(key auth-file)"',
            'echo "@@OWNER $(stat -c %U "$A" 2>/dev/null || echo ?)"',
            'echo "@@YML $(base64 -w0 "$C" 2>/dev/null)"',
            'L="$(key listen-http)"',
            'P="${L##*:}"',
            'H="?"',
            'if [ -n "$P" ]; then',
            '  U="http://127.0.0.1:$P/v1/health"',
            '  H="$(curl -fsS --max-time 3 "$U" 2>/dev/null'
            ' || wget -qO- -T 3 "$U" 2>/dev/null || echo ?)"',
            "fi",
            'echo "@@HEALTH $(printf %s "$H" | tr -d \'\\n\')"',
            "",
        ]
    )


def parse_markers(output):
    """{NOM: valeur} des lignes `@@NOM valeur` d'une sortie."""
    found = {}
    for line in output.splitlines():
        match = re.match(r"@@([A-Z]+)(?: (.*))?$", line.rstrip("\r"))
        if match:
            found[match.group(1)] = match.group(2) or ""
    return found


def parse_token(output):
    """Jeton de `token tk_… created for user …` ; None sans cette ligne."""
    match = _TOKEN_LINE.search(output)
    return match.group(1) if match else None


def revoke_script(config, user):
    """Supprime l'utilisateur, donc ses jetons et son accès."""
    return (
        f"set -e\nntfy user --config {shlex.quote(config)} del "
        f"{shlex.quote(user)}\n"
    )


def list_script(config):
    return f"ntfy access --config {shlex.quote(config)}\n"


def phone_users(output):
    """Utilisateurs `erm_*` d'une sortie de `ntfy access`, sans doublon."""
    users = []
    for line in output.splitlines():
        match = re.match(r"user (\S+)", line)
        if match and match.group(1).startswith(PHONE_USER_PREFIX):
            if match.group(1) not in users:
                users.append(match.group(1))
    return users


def write_yml_script(config, new_text, stamp):
    """Remplace `config` par `new_text` après une copie `<config>.bak-<stamp>`.

    Le contenu voyage en base64 ; le nouveau fichier reprend propriétaire et
    mode de l'ancien avant de le remplacer.
    """
    payload = base64.b64encode(new_text.encode("utf-8")).decode("ascii")
    cfg = shlex.quote(config)
    backup = shlex.quote(f"{config}.bak-{stamp}")
    tmp = shlex.quote(f"{config}.new")
    return "\n".join(
        [
            "set -e",
            "umask 077",
            f"cp -p {cfg} {backup}",
            f"printf %s {shlex.quote(payload)} | base64 -d > {tmp}",
            f"chown --reference={cfg} {tmp}",
            f"chmod --reference={cfg} {tmp}",
            f"mv {tmp} {cfg}",
            "",
        ]
    )


def restart_script():
    """Redémarre le service ntfy puis imprime son état (`@@ACTIVE`)."""
    return (
        "systemctl restart ntfy\n"
        "sleep 2\n"
        'echo "@@ACTIVE $(systemctl is-active ntfy)"\n'
    )


def build_link(phone_url, token, prefix, cache_s, odoo_url=None):
    """Lien de configuration `erplibre-ntfy:setup?v=1&…`, valeurs encodées."""
    fields = [
        ("v", "1"),
        ("url", phone_url),
        ("token", token),
        ("prefix", prefix),
        ("cache", str(cache_s)),
    ]
    if odoo_url:
        fields.append(("odoo", odoo_url))
    query = "&".join(
        f"{name}={urllib.parse.quote(value, safe='')}"
        for name, value in fields
    )
    return f"{LINK_SCHEME}setup?{query}"


def render_qr(link):
    """QR du lien en caractères de terminal ; None sans `segno`."""
    try:
        import segno
    except ImportError:
        return None
    out = io.StringIO()
    segno.make(link, error="m").terminal(out=out, compact=True)
    return out.getvalue()


def _tee_run(argv, env=None):
    """Lance `argv`, recopie sa sortie au terminal octet par octet.

    Retourne (code, sortie). stdin reste celui du terminal : l'invite de
    sudo ou de ssh s'y affiche et s'y répond.
    """
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env
    )
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    captured = bytearray()
    fd = proc.stdout.fileno()
    while True:
        chunk = os.read(fd, 1)
        if not chunk:
            break
        captured += chunk
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            sys.stdout.flush()
            buffer.write(chunk)
            buffer.flush()
        else:
            sys.stdout.write(decoder.decode(chunk))
            sys.stdout.flush()
    proc.stdout.close()
    return proc.wait(), captured.decode("utf-8", "replace")


class LocalHost:
    """Exécute un script `sh` sur cette machine, sous sudo.

    `sudo=()` lance `sh -c` sous l'utilisateur courant (tests, banc).
    """

    def __init__(self, sudo=("sudo",)):
        self.sudo = tuple(sudo)

    def argv(self, script, sudo_user):
        argv = list(self.sudo)
        if self.sudo and sudo_user:
            argv += ["-u", sudo_user]
        return argv + ["sh", "-c", script]

    def run(self, script, sudo_user):
        return _tee_run(self.argv(script, sudo_user))


class SshHost:
    """Exécute un script `sh` sous sudo sur `target`, par `ssh -t`."""

    def __init__(self, target):
        self.target = target

    def argv(self, script, sudo_user):
        remote = ["sudo"]
        if sudo_user:
            remote += ["-u", sudo_user]
        remote += ["sh", "-c", shlex.quote(script)]
        return ["ssh", "-t", self.target, " ".join(remote)]

    def run(self, script, sudo_user):
        # La sortie des outils reste en anglais quelle que soit la locale.
        env = dict(os.environ, LC_ALL="C", LANG="C")
        return _tee_run(self.argv(script, sudo_user), env=env)
