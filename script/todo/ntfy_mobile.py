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

`cli` remplace le mot `ntfy` de ces appels : le binaire de l'hôte par
défaut, ou le préfixe `<moteur> exec -e NTFY_PASSWORD ... ntfy` d'un ntfy
en conteneur (`call_infra.ntfy_cli`), texte `sh` déjà cité.
"""

import base64
import codecs
import contextlib
import difflib
import io
import os
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
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


def access_script(config, user, prefix, label="erplibre-mobile", cli="ntfy"):
    """Script `sh` qui ouvre l'accès d'un téléphone et crée son jeton.

    Anonyme : écriture seule sur `up*` (le serveur Odoo publie sans
    identité). Le téléphone : lecture seule sur `<prefix>*`, mot de passe
    aléatoire jeté, jeton sans expiration. Le jeton est la dernière sortie.
    `user` ne doit pas exister : ntfy refuse un nom pris et `set -e` arrête
    le script, plutôt que de fusionner deux téléphones sous un compte.

    Le mot de passe est tiré sur l'hôte et passe par NTFY_PASSWORD, posée
    pour la seule commande : avec un `cli` en conteneur, `exec -e
    NTFY_PASSWORD` sans valeur la reprend à cet environnement, aucun argv
    ne la porte.
    """
    cfg = shlex.quote(config)
    usr = shlex.quote(user)
    return "\n".join(
        [
            "set -e",
            f"{cli} access --config {cfg} everyone {shlex.quote('up*')}"
            " write-only",
            'NTFY_PASSWORD="$(head -c 32 /dev/urandom | base64)"'
            f" {cli} user --config {cfg} add {usr}",
            f"{cli} access --config {cfg} {usr}"
            f" {shlex.quote(prefix + '*')} read-only",
            f"{cli} token --config {cfg} add"
            f" {shlex.quote('--label=' + label)} {usr}",
            "",
        ]
    )


def version_script(cli="ntfy"):
    """Script qui imprime `@@VERSION <première ligne de --version>` par la
    commande `cli` : le binaire de l'hôte par défaut, la CLI dans son
    conteneur (`call_infra.ntfy_cli`) pour un ntfy en conteneur."""
    return f'echo "@@VERSION $({cli} --version 2>&1 | head -n 1)"\n'


def inspect_script(config, state_path=None):
    """Script qui imprime version, propriétaire, `server.yml`, santé et
    service.

    Une ligne `@@NOM valeur` par fait ; `parse_markers` les relit. UNIT est
    l'état de chargement systemd du service `ntfy` : `loaded`, `not-found`
    quand aucun service ne porte ce nom, `?` sans systemd. VERSION est celle
    du binaire `ntfy` de l'hôte (`version_script`) ; celle d'un ntfy en
    conteneur se lit ensuite par sa CLI. Avec `state_path`, `@@STATE <base64>` porte
    ce fichier quand il existe : l'état de l'infrastructure d'appel, qui dit
    si ntfy tourne en conteneur.
    """
    cfg = shlex.quote(config)
    state = []
    if state_path is not None:
        path = shlex.quote(state_path)
        state = [
            f'if [ -f {path} ]; then echo "@@STATE $(base64 -w0 {path})"; fi'
        ]
    return "\n".join(
        [
            f"C={cfg}",
            version_script().rstrip("\n"),
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
            'echo "@@UNIT $(systemctl show -p LoadState --value ntfy'
            ' 2>/dev/null || echo ?)"',
            *state,
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


def revoke_script(config, user, cli="ntfy"):
    """Supprime l'utilisateur, donc ses jetons et son accès."""
    return (
        f"set -e\n{cli} user --config {shlex.quote(config)} del "
        f"{shlex.quote(user)}\n"
    )


def list_script(config, cli="ntfy"):
    return f"{cli} access --config {shlex.quote(config)}\n"


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


RESTART = "systemctl restart ntfy"
ACTIVE = "systemctl is-active ntfy"


def restart_script(restart=RESTART, active=ACTIVE):
    """Redémarre ntfy par la commande `restart` puis imprime son état
    (`@@ACTIVE`), que la commande `active` écrit : l'unité systemd par
    défaut, l'outil de composition et `inspect` pour un ntfy en conteneur
    (`call_infra.ntfy_cli`)."""
    return f'{restart}\nsleep 2\necho "@@ACTIVE $({active})"\n'


def restore_command(config, stamp, restart=RESTART):
    """Commande root qui remet la copie `<config>.bak-<stamp>` et relance
    ntfy par `restart`, à afficher quand le redémarrage échoue."""
    cfg = shlex.quote(config)
    backup = shlex.quote(f"{config}.bak-{stamp}")
    return f"cp -p {backup} {cfg} && {restart}"


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


def ntfy_free_env(environ=None):
    """L'environnement (`os.environ` par défaut) sans les variables
    `NTFY_*` : la CLI les fait passer avant `--config`, et `NTFY_AUTH_FILE`
    viserait un autre fichier d'accès que celui de la configuration."""
    source = os.environ if environ is None else environ
    return {k: v for k, v in source.items() if not k.startswith("NTFY_")}


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


@contextlib.contextmanager
def _staged_file(script):
    """Chemin d'un fichier temporaire 0600 qui porte `script`, effacé en
    sortie, même sur une interruption."""
    fd, path = tempfile.mkstemp(prefix="erplibre-", suffix=".sh")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(script)
        yield path
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)


# Dépôt du script sur l'hôte, sous le compte de connexion : un dossier
# `mktemp -d` (0700) reçoit le script lu sur l'entrée standard, puis son
# chemin est imprimé.
_STAGE = 'umask 077; d=$(mktemp -d) && cat > "$d/s" && echo "$d"'
# Lancement du script déposé, `$1` étant son dossier : sudo le lit comme un
# fichier, puis le compte de connexion retire le dossier, que sudo ait
# réussi ou non ; le code rendu reste celui de sudo.
_STAGED_RUN = 'sudo sh "$1/s"; rc=$?; rm -rf "$1"; exit $rc'
_STAGED_DIR = re.compile(r"^/[A-Za-z0-9._/-]+$")


class LocalHost:
    """Exécute un script `sh` sur cette machine, sous sudo.

    Un script lancé en root (`sudo_user` None) passe par un fichier 0600
    de l'utilisateur courant, que root lit : l'argv, que `ps` montre à tout
    compte local, ne porte que son chemin, jamais le texte ni les secrets
    qu'il transporte. Sous un autre compte, qui ne lirait pas ce fichier,
    le script passe par `sh -c` (`argv`). `sudo=()` lance sous
    l'utilisateur courant (tests, banc).
    """

    def __init__(self, sudo=("sudo",)):
        self.sudo = tuple(sudo)

    def argv(self, script, sudo_user):
        argv = list(self.sudo)
        if self.sudo and sudo_user:
            argv += ["-u", sudo_user]
        return argv + ["sh", "-c", script]

    def staged_argv(self, path):
        return list(self.sudo) + ["sh", path]

    def run(self, script, sudo_user):
        env = ntfy_free_env()
        if sudo_user:
            return _tee_run(self.argv(script, sudo_user), env=env)
        with _staged_file(script) as path:
            return _tee_run(self.staged_argv(path), env=env)


class SshHost:
    """Exécute un script `sh` sous sudo sur `target`, par `ssh -t`.

    `target` est ce qu'on passe à ssh (un alias de `~/.ssh/config` compris) ;
    `hostname`, l'hôte réel qu'il désigne, quand on le connaît.

    Un script lancé en root voyage en deux connexions : `ssh -T` le dépose
    sur l'hôte par l'entrée standard, dans un dossier 0700 du compte de
    connexion (`_STAGE`), puis `ssh -t` le fait lire par sudo, dont l'invite
    garde le terminal (`_STAGED_RUN`). Aucun argv, ni ici ni sur l'hôte, ne
    porte son texte. Un échec du dépôt rend le code 255, celui d'une
    connexion ssh ratée, et rien n'est lancé. Une connexion coupée pendant
    le lancement laisse le dossier, lisible du seul compte de connexion.
    Sous un autre compte que root, le script passe par `sh -c` (`argv`).
    """

    def __init__(self, target, hostname=None):
        self.target = target
        self.hostname = hostname

    def argv(self, script, sudo_user):
        remote = ["sudo"]
        if sudo_user:
            remote += ["-u", sudo_user]
        remote += ["sh", "-c", shlex.quote(script)]
        return ["ssh", "-t", self.target, " ".join(remote)]

    def stage_argv(self):
        return ["ssh", "-T", self.target, "sh -c " + shlex.quote(_STAGE)]

    def staged_argv(self, directory):
        remote = (
            f"sh -c {shlex.quote(_STAGED_RUN)} sh {shlex.quote(directory)}"
        )
        return ["ssh", "-t", self.target, remote]

    def run(self, script, sudo_user):
        # La sortie des outils reste en anglais quelle que soit la locale.
        env = dict(os.environ, LC_ALL="C", LANG="C")
        if sudo_user:
            return _tee_run(self.argv(script, sudo_user), env=env)
        done = subprocess.run(
            self.stage_argv(),
            input=script.encode("utf-8"),
            stdout=subprocess.PIPE,
            env=env,
        )
        lines = done.stdout.decode("utf-8", "replace").strip().splitlines()
        directory = lines[-1] if lines else ""
        if done.returncode != 0 or not _STAGED_DIR.match(directory):
            return 255, done.stdout.decode("utf-8", "replace")
        return _tee_run(self.staged_argv(directory), env=env)
