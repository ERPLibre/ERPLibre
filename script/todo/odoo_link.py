#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Accès à une base Odoo 18, par son API web ou par `odoo-bin shell`.

Stdlib seule. Deux classes offrent les mêmes méthodes, que le menu de
l'infrastructure d'appel appelle sans savoir par quel chemin il passe :
`facts()`, `install_module()`, `set_params()`, `replace_rows()` et
`whoami()`.

- `WebApi` parle à `/jsonrpc` : `common.version`, puis `common.login`,
  puis `object.execute_kw`, avec un mot de passe ou une clé d'API (un
  administrateur en double authentification n'entre que par une clé). Le
  compte doit être dans `base.group_system`. Version, connexion et droits
  sont vérifiés une fois, avant le premier appel objet : une base qui
  n'est pas en 18, un mot de passe faux ou une base inconnue sont refusés
  avant toute écriture.
- `OdooShell` envoie un corps Python à `./odoo_bin.sh shell` dans le
  dossier ERPLibre de l'hôte, par un runner de `ntfy_mobile` (`LocalHost`
  ou `SshHost`). Le script `sh` part en root, donc par le fichier 0600 du
  runner : le corps Python, secrets compris, n'arrive à `odoo-bin` que par
  son entrée standard, jamais dans un argv. `odoo-bin` tourne sous le
  propriétaire du dossier. Son journal reste sur l'hôte ; seules les lignes
  `@@ODOO_*` reviennent.

Aucune des deux ne relit un secret en clair : `facts().params` donne
`erplibre_turn.secret` sous la forme de `secret_digest()`, et les lignes
`mail.ice.server` sans leur `credential`. Les messages d'erreur qui
remontent d'Odoo sont expurgés des secrets envoyés par l'appel.

Une base Odoo se désigne par `odoo_key(url, base)` : l'URL réduite à son
origine (schéma, nom et port en minuscules, port par défaut retiré), puis
`|`, puis le nom de base. `owned_username()` en tire le nom d'utilisateur
des lignes `mail.ice.server` que l'outil écrit ; `replace_rows()` ne
touche qu'aux lignes qui portent exactement ce nom.
"""

import base64
import dataclasses
import hashlib
import http.client
import ipaddress
import json
import logging
import re
import shlex
import urllib.error
import urllib.parse
import urllib.request

_logger = logging.getLogger(__name__)

MODULE = "erplibre_turn"
PARAM_SECRET = "erplibre_turn.secret"
PARAM_URLS = "erplibre_turn.urls"
PARAM_TTL = "erplibre_turn.ttl_hours"
PARAM_KEYS = (PARAM_SECRET, PARAM_URLS, PARAM_TTL)
SUPPORTED_MAJOR = 18
ADMIN_GROUP = "base.group_system"
ICE_MODEL = "mail.ice.server"
ROW_FIELDS = ("server_type", "uri", "username")
# Les seuls types que le champ `server_type` de mail.ice.server accepte.
SERVER_TYPES = ("stun", "turn")
# `button_immediate_install` recharge le registre de la base dans la même
# requête : bien plus long qu'une lecture.
INSTALL_TIMEOUT = 600
SECRET_DIGEST_PREFIX = "sha256:"

_DEFAULT_PORTS = {"http": 80, "https": 443}
# Forme d'un nom de base qu'Odoo accepte (`odoo.service.db.DBNAME_PATTERN`).
_DBNAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]+$")
_OWNED = re.compile(r"^erplibre-[0-9a-f]{8}$")
_MARKER = re.compile(r"^@@ODOO_([A-Z]+)(?: (.*))?$")
# Un message d'Odoo est coupé à sa première ligne et à cette longueur.
_MESSAGE_MAX = 300


class OdooError(Exception):
    """Refus ou échec : `key` est une clé i18n, `values` les champs de son
    message (`t(key).format(**values)`)."""

    def __init__(self, key, **values):
        super().__init__(key)
        self.key = key
        self.values = values


class _RpcFault(Exception):
    """Réponse `error` de JSON-RPC ; `message` est déjà expurgé."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


@dataclasses.dataclass(frozen=True)
class OdooFacts:
    """Ce qu'une base Odoo dit d'elle-même.

    `module_state` : l'état d'`erplibre_turn` dans `ir.module.module`
    (« installed », « uninstalled » quand il est sur le chemin des addons,
    ou tout autre état tel quel), « absent » sans ligne pour le module ;
    un module posé sur le chemin sans mise à jour de la liste des
    applications se lit aussi « absent ».
    `params` : ceux des trois paramètres `erplibre_turn.*` présents, le
    secret sous la forme de `secret_digest()`.
    `rows` : chaque ligne de `mail.ice.server` (`id`, `server_type`, `uri`,
    `username`, ce dernier vide quand la ligne n'en a pas), jamais son
    `credential`.
    `host_name` : le nom d'hôte de l'URL de la base.
    """

    version: str
    major: int
    module_state: str
    params: dict
    rows: tuple
    host_name: str


def normalize_url(url):
    """L'origine de `url` : `http(s)://nom[:port]`, schéma et nom en
    minuscules, port par défaut retiré, chemin, requête et fragment
    ignorés. Refuse (`call_infra_odoo_url`) un autre schéma, une URL sans
    nom, un port invalide, ou un compte dans l'URL."""
    try:
        parts = urllib.parse.urlsplit(str(url).strip())
        port = parts.port
    except ValueError:
        raise OdooError("call_infra_odoo_url") from None
    scheme = parts.scheme.lower()
    host = parts.hostname
    if scheme not in _DEFAULT_PORTS or not host or "@" in parts.netloc:
        raise OdooError("call_infra_odoo_url")
    try:
        if ipaddress.ip_address(host).version == 6:
            host = f"[{host}]"
    except ValueError:
        pass
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        host = f"{host}:{port}"
    return f"{scheme}://{host}"


def _check_database(database):
    if not isinstance(database, str) or not _DBNAME.match(database):
        raise OdooError("call_infra_odoo_database")


def odoo_key(url, database):
    """La clé d'une base Odoo dans l'état de l'hôte : `<origine>|<base>`."""
    _check_database(database)
    return f"{normalize_url(url)}|{database}"


def owned_username(url, database):
    """`erplibre-<8 hex>` : le début du SHA-256 de `odoo_key(url, base)`,
    le nom des lignes `mail.ice.server` que l'outil écrit pour cette base."""
    digest = hashlib.sha256(odoo_key(url, database).encode("utf-8"))
    return "erplibre-" + digest.hexdigest()[:8]


def secret_digest(value):
    """`sha256:<hex>` de `value` : la forme sous laquelle `facts()` montre
    le secret d'Odoo, comparable à l'empreinte d'un secret tiré."""
    return (
        SECRET_DIGEST_PREFIX
        + hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    )


def major_of(version):
    """Le numéro majeur d'une version d'Odoo (« 18.0 » → 18) ; 0 pour une
    version qui ne commence pas par des chiffres (`saas~18.2`)."""
    match = re.match(r"^(\d+)(?:\.|$)", str(version))
    return int(match.group(1)) if match else 0


def _check_version(version):
    if major_of(version) != SUPPORTED_MAJOR:
        raise OdooError("call_infra_odoo_version", version=version)


def _redact(text, secrets):
    """`text` réduit à sa première ligne non vide et à `_MESSAGE_MAX`
    caractères, chaque valeur de `secrets` remplacée par « *** »."""
    text = str(text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return (lines[0] if lines else "")[:_MESSAGE_MAX]


def _check_params(values):
    """Les paramètres à écrire : seulement les trois du module, chacun une
    chaîne ou None (retiré)."""
    for key, value in values.items():
        if key not in PARAM_KEYS:
            raise ValueError(f"not an {MODULE} parameter: {key}")
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{key}: a string or None")
    return dict(values)


def _check_rows(owned, rows):
    """Copie des lignes à créer pour `owned`. Chacune porte exactement le
    nom `owned` : une ligne que l'outil ne saurait pas retrouver ensuite
    n'est jamais écrite, et un nom qui n'a pas la forme
    `owned_username()` ne désigne jamais les lignes d'un autre."""
    if not isinstance(owned, str) or not _OWNED.match(owned):
        raise ValueError("owned username must look like erplibre-<8 hex>")
    checked = []
    for row in rows:
        if row.get("username") != owned:
            raise ValueError("every row carries the owned username")
        if row.get("server_type") not in SERVER_TYPES or not row.get("uri"):
            raise ValueError("server_type stun or turn, and a uri")
        clean = {
            "server_type": row["server_type"],
            "uri": str(row["uri"]),
            "username": owned,
        }
        if row.get("credential"):
            clean["credential"] = str(row["credential"])
        checked.append(clean)
    return checked


def _row(record):
    return {
        "id": int(record["id"]),
        "server_type": record.get("server_type") or "",
        "uri": record.get("uri") or "",
        "username": record.get("username") or "",
    }


class WebApi:
    """Une base Odoo par son API JSON-RPC.

    `secret` est le mot de passe ou la clé d'API de `login` ; il ne vit que
    dans cet objet et n'est ni journalisé ni repris dans un message.
    `opener` fournit `request.urlopen` (le module `urllib` par défaut).
    """

    def __init__(
        self, url, database, login, secret, timeout=20, opener=urllib
    ):
        self.url = normalize_url(url)
        _check_database(database)
        self.database = database
        self.login = login
        self._secret = secret
        self.timeout = timeout
        self.opener = opener
        self._uid = None
        self._version = None
        self._seq = 0

    def _post(self, service, method, args, timeout=None, secrets=()):
        self._seq += 1
        _logger.debug("jsonrpc %s.%s", service, method)
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "call",
                "params": {"service": service, "method": method, "args": args},
                "id": self._seq,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url + "/jsonrpc",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.request.urlopen(
                request, timeout=timeout or self.timeout
            ) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            error.close()
            raise OdooError(
                "call_infra_odoo_unreachable",
                url=self.url,
                reason=f"HTTP {error.code}",
            ) from None
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            OSError,
            ValueError,
        ) as error:
            reason = getattr(error, "reason", None) or error
            raise OdooError(
                "call_infra_odoo_unreachable", url=self.url, reason=str(reason)
            ) from None
        try:
            answer = json.loads(body)
        except ValueError:
            answer = None
        if not isinstance(answer, dict) or not (
            "result" in answer or "error" in answer
        ):
            raise OdooError(
                "call_infra_odoo_unreachable",
                url=self.url,
                reason="not a JSON-RPC answer",
            )
        if "error" in answer:
            error = (
                answer["error"] if isinstance(answer["error"], dict) else {}
            )
            data = (
                error.get("data")
                if isinstance(error.get("data"), dict)
                else {}
            )
            message = data.get("message") or error.get("message") or "error"
            raise _RpcFault(_redact(message, (self._secret,) + tuple(secrets)))
        return answer["result"]

    def _call(
        self, uid, model, method, args, kwargs=None, timeout=None, secrets=()
    ):
        _logger.debug("execute_kw %s.%s", model, method)
        return self._post(
            "object",
            "execute_kw",
            [
                self.database,
                uid,
                self._secret,
                model,
                method,
                args,
                kwargs or {},
            ],
            timeout=timeout,
            secrets=secrets,
        )

    def _connect(self):
        """L'uid du compte, après version, connexion et droits vérifiés ;
        une seule fois par objet."""
        if self._uid is not None:
            return self._uid
        try:
            info = self._post("common", "version", [])
        except _RpcFault as fault:
            raise OdooError(
                "call_infra_odoo_unreachable",
                url=self.url,
                reason=fault.message,
            ) from None
        if not isinstance(info, dict):
            info = {}
        version = str(info.get("server_version") or "")
        _check_version(version)
        try:
            uid = self._post(
                "common", "login", [self.database, self.login, self._secret]
            )
        except _RpcFault:
            uid = False
        if not uid:
            raise OdooError("call_infra_odoo_login", database=self.database)
        try:
            admin = self._call(
                uid, "res.users", "has_group", [[uid], ADMIN_GROUP]
            )
        except _RpcFault:
            admin = False
        if not admin:
            raise OdooError("call_infra_odoo_not_admin", login=self.login)
        self._version = version
        self._uid = uid
        return uid

    def _execute(
        self, model, method, args, kwargs=None, timeout=None, secrets=()
    ):
        uid = self._connect()
        try:
            return self._call(
                uid, model, method, args, kwargs, timeout, secrets
            )
        except _RpcFault as fault:
            raise OdooError(
                "call_infra_odoo_rpc_error", message=fault.message
            ) from None

    def _module_state(self):
        found = self._execute(
            "ir.module.module",
            "search_read",
            [[["name", "=", MODULE]]],
            {"fields": ["state"], "limit": 1},
        )
        return (
            (found[0]["id"], found[0]["state"]) if found else (None, "absent")
        )

    def facts(self):
        self._connect()
        _, state = self._module_state()
        params = {}
        for record in self._execute(
            "ir.config_parameter",
            "search_read",
            [[["key", "in", list(PARAM_KEYS)]]],
            {"fields": ["key", "value"]},
        ):
            key, value = record.get("key"), record.get("value")
            if key not in PARAM_KEYS or value is False or value is None:
                continue
            params[key] = (
                secret_digest(value) if key == PARAM_SECRET else str(value)
            )
        rows = tuple(
            _row(record)
            for record in self._execute(
                ICE_MODEL, "search_read", [[]], {"fields": list(ROW_FIELDS)}
            )
        )
        return OdooFacts(
            version=self._version,
            major=major_of(self._version),
            module_state=state,
            params=params,
            rows=rows,
            host_name=urllib.parse.urlsplit(self.url).hostname or "",
        )

    def install_module(self):
        """Installe `erplibre_turn` (`button_immediate_install`) quand il
        ne l'est pas ; refuse (`call_infra_odoo_install_failed`) quand il
        n'est pas installé ensuite, « absent » compris."""
        self._connect()
        module_id, state = self._module_state()
        if module_id is not None and state != "installed":
            self._execute(
                "ir.module.module",
                "button_immediate_install",
                [[module_id]],
                timeout=INSTALL_TIMEOUT,
            )
            _, state = self._module_state()
        if state != "installed":
            raise OdooError("call_infra_odoo_install_failed", state=state)

    def set_params(self, values):
        """Écrit chaque paramètre `erplibre_turn.*` de `values`, dans leur
        ordre ; None le retire (`ir.config_parameter.set_param`)."""
        values = _check_params(values)
        self._connect()
        secrets = tuple(v for v in values.values() if v)
        for key, value in values.items():
            self._execute(
                "ir.config_parameter",
                "set_param",
                [key, value],
                secrets=secrets,
            )

    def replace_rows(self, owned, rows):
        """Remplace les lignes `mail.ice.server` de nom `owned` par `rows`.

        Les nouvelles sont créées avant que les anciennes soient effacées :
        un échec entre les deux laisse des lignes en double, que la relance
        efface, plutôt qu'une base sans serveur. Seuls les ids dont le nom
        relu vaut exactement `owned` sont effacés.
        """
        rows = _check_rows(owned, rows)
        self._connect()
        found = self._execute(
            ICE_MODEL,
            "search_read",
            [[["username", "=", owned]]],
            {"fields": ["username"]},
        )
        old_ids = [r["id"] for r in found if r.get("username") == owned]
        if rows:
            secrets = tuple(r["credential"] for r in rows if "credential" in r)
            self._execute(ICE_MODEL, "create", [rows], secrets=secrets)
        if old_ids:
            self._execute(ICE_MODEL, "unlink", [old_ids])

    def whoami(self):
        """L'identifiant du compte, tel qu'Odoo le relit."""
        uid = self._connect()
        (record,) = self._execute(
            "res.users", "read", [[uid]], {"fields": ["login"]}
        )
        return record["login"]


# Début de tout corps Python : version imprimée, puis arrêt (code 4) sur
# une autre version que 18, avant toute écriture.
_PY_HEAD = """import base64
import hashlib
import json

import odoo.release

print("@@ODOO_VERSION", odoo.release.version, flush=True)
if odoo.release.version_info[0] != {major}:
    raise SystemExit(4)
"""

_PY_FACTS = """module = env["ir.module.module"].sudo().search(
    [("name", "=", {module!r})], limit=1
)
print("@@ODOO_MODULE", module.state if module else "absent")
print("@@ODOO_USER", env.user.login)
Param = env["ir.config_parameter"].sudo()
for key in {keys!r}:
    value = Param.get_param(key)
    if value is False or value is None:
        continue
    if key == {secret_key!r}:
        value = {prefix!r} + hashlib.sha256(value.encode("utf-8")).hexdigest()
    print("@@ODOO_PARAM", key, base64.b64encode(value.encode("utf-8")).decode())
for row in env[{model!r}].sudo().search_read([], {fields!r}):
    row = {{
        "id": row["id"],
        "server_type": row["server_type"] or "",
        "uri": row["uri"] or "",
        "username": row["username"] or "",
    }}
    print("@@ODOO_ROW", base64.b64encode(json.dumps(row).encode()).decode())
"""

_PY_SET_PARAMS = """Param = env["ir.config_parameter"].sudo()
for key, value in json.loads({values!r}):
    Param.set_param(key, value)
"""

_PY_REPLACE_ROWS = """Ice = env[{model!r}].sudo()
old = Ice.search([("username", "=", {owned!r})])
rows = json.loads({rows!r})
if rows:
    Ice.create(rows)
old.unlink()
"""

# `button_immediate_install` remplace le registre : l'état se relit en SQL,
# hors du cache de l'ancien environnement.
_PY_INSTALL = """module = env["ir.module.module"].sudo().search(
    [("name", "=", {module!r})], limit=1
)
if module and module.state != "installed":
    module.button_immediate_install()
env.cr.execute(
    "SELECT state FROM ir_module_module WHERE name = %s", [{module!r}]
)
found = env.cr.fetchone()
print("@@ODOO_MODULE", found[0] if found else "absent")
"""

# Le script root qui lance `odoo-bin shell`. `{payload}` est le corps
# Python en base64 : `printf` est une commande interne de `sh`, le corps ne
# passe donc par aucun argv, ni de `sh` ni de `runuser`. Le journal
# d'Odoo va dans un fichier temporaire de root, effacé en sortie ; seules
# ses lignes `@@ODOO_*` sont recopiées, puis, sur un échec, sa dernière
# ligne non vide en base64 (`@@ODOO_LAST`). Le code rendu est celui
# d'`odoo-bin`.
_SH = """set -u
LC_ALL=C; export LC_ALL; unset LANGUAGE
dir={directory}
if [ ! -x "$dir/odoo_bin.sh" ]; then
    printf '@@ODOO_LAST %s\\n' "$(printf 'no executable odoo_bin.sh in %s' "$dir" | base64 | tr -d '\\n')"
    exit 3
fi
owner=$(stat -c %U "$dir") || exit 3
log=$(mktemp) || exit 3
trap 'rm -f "$log"' EXIT
if [ "$(id -un)" = "$owner" ]; then
    set --
else
    set -- runuser -u "$owner" --
fi
cd "$dir" || exit 3
printf %s {payload} | base64 -d | "$@" ./odoo_bin.sh shell -d {database} --no-http >"$log" 2>&1
rc=$?
grep '^@@ODOO_' "$log"
if [ "$rc" -ne 0 ]; then
    printf '@@ODOO_LAST %s\\n' "$(grep -v '^[[:space:]]*$' "$log" | tail -n 1 | base64 | tr -d '\\n')"
fi
exit "$rc"
"""


def parse_markers(output):
    """[(nom, valeur)] des lignes `@@ODOO_<NOM> valeur` de `output`."""
    found = []
    for line in output.splitlines():
        match = _MARKER.match(line.rstrip("\r"))
        if match:
            found.append((match.group(1), match.group(2) or ""))
    return found


def _b64_text(value):
    try:
        return base64.b64decode(value, validate=True).decode(
            "utf-8", "replace"
        )
    except (ValueError, TypeError):
        return ""


class OdooShell:
    """Une base Odoo par `odoo-bin shell` sur son hôte.

    `host` est un runner de `ntfy_mobile` (`run(script, sudo_user)` →
    `(code, sortie)`) ; `erplibre_dir`, le dossier ERPLibre de l'hôte, qui
    porte `odoo_bin.sh` ; `url`, quand on la connaît, donne `host_name`.
    Chaque méthode lance un `odoo-bin shell`, sous le superutilisateur
    d'Odoo, qui finit par `env.cr.commit()` : un corps qui lève ne valide
    rien.
    """

    def __init__(self, host, erplibre_dir, database, url=None):
        if (
            not isinstance(erplibre_dir, str)
            or not erplibre_dir.startswith("/")
            or any(ord(c) < 32 for c in erplibre_dir)
        ):
            raise OdooError("call_infra_odoo_dir", directory=str(erplibre_dir))
        _check_database(database)
        self.host = host
        self.erplibre_dir = erplibre_dir
        self.database = database
        self.url = normalize_url(url) if url else None
        self._user = None

    def script(self, python):
        """Le script `sh` (root) qui envoie `python` à `odoo-bin shell`."""
        payload = base64.b64encode(python.encode("utf-8")).decode("ascii")
        return _SH.format(
            directory=shlex.quote(self.erplibre_dir),
            payload=payload,
            database=shlex.quote(self.database),
        )

    def _run(self, op, body, secrets=()):
        """Les marqueurs d'un `odoo-bin shell` qui a joué `body` puis
        imprimé `@@ODOO_DONE <op>` et validé. Refus : version (avant tout
        autre), hôte injoignable (code 255 de ssh sans aucun marqueur),
        échec avec la dernière ligne du journal expurgée de `secrets`."""
        python = (
            _PY_HEAD.format(major=SUPPORTED_MAJOR)
            + body
            + f'print("@@ODOO_DONE {op}")\nenv.cr.commit()\n'
        )
        code, out = self.host.run(self.script(python), sudo_user=None)
        markers = parse_markers(out)
        versions = [value for name, value in markers if name == "VERSION"]
        if versions:
            _check_version(versions[0])
        if code == 0 and ("DONE", op) in markers:
            return markers
        if code == 255 and not markers:
            target = getattr(self.host, "target", None) or "localhost"
            raise OdooError(
                "call_infra_odoo_unreachable",
                url=target,
                reason=_redact(
                    (out.strip().splitlines() or [""])[-1], secrets
                ),
            )
        last = [_b64_text(value) for name, value in markers if name == "LAST"]
        if last:
            line = last[-1]
        else:
            plain = [ln for ln in out.splitlines() if ln.strip()]
            line = plain[-1] if plain else f"exit {code}"
        raise OdooError(
            "call_infra_odoo_shell_failed", line=_redact(line, secrets)
        )

    def facts(self):
        body = _PY_FACTS.format(
            module=MODULE,
            keys=PARAM_KEYS,
            secret_key=PARAM_SECRET,
            prefix=SECRET_DIGEST_PREFIX,
            model=ICE_MODEL,
            fields=list(ROW_FIELDS),
        )
        markers = self._run("facts", body)
        version, state, params, rows = "", "absent", {}, []
        for name, value in markers:
            if name == "VERSION" and not version:
                version = value
            elif name == "MODULE":
                state = value
            elif name == "USER":
                self._user = value
            elif name == "PARAM":
                key, _, encoded = value.partition(" ")
                if key in PARAM_KEYS:
                    params[key] = _b64_text(encoded)
            elif name == "ROW":
                try:
                    rows.append(_row(json.loads(_b64_text(value))))
                except (ValueError, KeyError, TypeError):
                    continue
        if self.url:
            host_name = urllib.parse.urlsplit(self.url).hostname or ""
        else:
            host_name = (
                getattr(self.host, "hostname", None)
                or getattr(self.host, "target", None)
                or ""
            )
        return OdooFacts(
            version=version,
            major=major_of(version),
            module_state=state,
            params=params,
            rows=tuple(rows),
            host_name=host_name,
        )

    def install_module(self):
        markers = self._run(
            "install_module", _PY_INSTALL.format(module=MODULE)
        )
        states = [value for name, value in markers if name == "MODULE"]
        state = states[-1] if states else "absent"
        if state != "installed":
            raise OdooError("call_infra_odoo_install_failed", state=state)

    def set_params(self, values):
        values = _check_params(values)
        body = _PY_SET_PARAMS.format(values=json.dumps(list(values.items())))
        self._run(
            "set_params", body, secrets=tuple(v for v in values.values() if v)
        )

    def replace_rows(self, owned, rows):
        rows = _check_rows(owned, rows)
        body = _PY_REPLACE_ROWS.format(
            model=ICE_MODEL, owned=owned, rows=json.dumps(rows)
        )
        secrets = tuple(r["credential"] for r in rows if "credential" in r)
        self._run("replace_rows", body, secrets=secrets)

    def whoami(self):
        """L'identifiant du compte sous lequel le shell écrit (le
        superutilisateur d'Odoo), relu par `facts()` au premier appel."""
        if self._user is None:
            self.facts()
        return self._user
