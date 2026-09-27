#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'API REST d'une instance Dolibarr : module, utilisateur technique, clé.

    ./script/dolibarr/api.py enable --instance erp [--login erplibre_api]
        [--rotate] [--confirm erp]
    ./script/dolibarr/api.py status --instance erp
    ./script/dolibarr/api.py disable --instance erp [--confirm erp]

enable allume le module API et crée l'utilisateur technique, en lecture
seule : il reçoit chaque droit de lecture (type « r », ou lire/read) et
aucun autre. Sa clé DOLAPIKEY, tirée ici, voyage vers PHP par stdin et
jamais par argv ; Dolibarr la garde chiffrée par la clé d'instance, ERPLibre
dans private/dolibarr/api/<instance>.key (0600, dossier 0700), à côté du
registre et des sauvegardes. Relancé, enable garde la clé ; --rotate en
tire une autre, comme une clé perdue.

status appelle /api/index.php/status avec la clé : 200 et la version prouvent
que la clé ouvre l'API ; 401 dit une clé refusée, 404 ou 501 un module
éteint. L'explorateur (swagger) est à /api/index.php/explorer/.

Une production exige son nom retapé pour enable et disable : l'API ouvre
ses données à qui détient la clé. Le serveur MCP de Dolibarr 24, encore
expérimental, viendra ensuite.
"""

import argparse
import json
import os
import re
import secrets
import ssl
import string
import sys
import urllib.error
import urllib.request

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import backup, debug, lib_dolibarr  # noqa: E402
from script.dolibarr.fleet import _local_base  # noqa: E402

ROOT = new_path
t = backup.t

KEYS = os.path.join("private", "dolibarr", "api")
_LOGIN = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
_ALPHABET = string.ascii_letters + string.digits

# %s : master.inc.php. Le login et la clé (vide : garder la sienne)
# arrivent sur stdin, en JSON.
_PHP_ENABLE = (
    'require "%s"; require_once DOL_DOCUMENT_ROOT."/core/lib/admin.lib.php";'
    ' require_once DOL_DOCUMENT_ROOT."/user/class/user.class.php";'
    " $in = json_decode(trim(stream_get_contents(STDIN)), true);"
    ' $r = activateModule("modApi"); if (!empty($r["errors"])) {'
    ' echo "ERPLIBRE_API_ERRORS ", json_encode($r["errors"]), "\\n"; exit(1); }'
    ' $res = $db->query("SELECT rowid FROM ".MAIN_DB_PREFIX."user'
    ' WHERE admin = 1 AND statut = 1 ORDER BY rowid");'
    " $o = $res ? $db->fetch_object($res) : null; if (!$o) {"
    ' echo "ERPLIBRE_API_ERRORS [\\"no active administrator\\"]\\n"; exit(1); }'
    " $admin = new User($db); $admin->fetch((int) $o->rowid);"
    ' $u = new User($db); if ($u->fetch(0, $in["login"]) <= 0) {'
    ' $u = new User($db); $u->login = $in["login"];'
    ' $u->lastname = "ERPLibre API"; $u->admin = 0;'
    " if ($u->create($admin) <= 0) {"
    ' echo "ERPLIBRE_API_ERRORS ", json_encode(array_merge(array($u->error),'
    ' $u->errors)), "\\n"; exit(1); } $u->fetch(0, $in["login"]); }'
    ' if ($in["key"] !== "") { $u->api_key = $in["key"];'
    " if ($u->update($admin) < 0) {"
    ' echo "ERPLIBRE_API_ERRORS ", json_encode(array_merge(array($u->error),'
    ' $u->errors)), "\\n"; exit(1); } }'
    ' $res = $db->query("SELECT id FROM ".MAIN_DB_PREFIX."rights_def'
    " WHERE (type = 'r' OR perms IN ('lire', 'read')"
    " OR subperms IN ('lire', 'read')) AND entity = \".((int) $conf->entity));"
    " $n = 0; while ($res && ($d = $db->fetch_object($res))) {"
    " if ($u->addrights((int) $d->id) > 0) { $n++; } }"
    ' echo "ERPLIBRE_API_OK ", $u->id, " ", $n, "\\n";'
)
_PHP_DISABLE = (
    'require "%s"; require_once DOL_DOCUMENT_ROOT."/core/lib/admin.lib.php";'
    ' $e = unActivateModule("modApi"); if ($e) {'
    ' echo "ERPLIBRE_API_ERRORS ", json_encode(array($e)), "\\n"; exit(1); }'
    ' echo "ERPLIBRE_API_OK\\n";'
)


class System(backup.System):
    def http(self, url, host, headers):
        """(code HTTP, corps) ; 0 si rien n'a répondu. Le certificat n'est
        pas vérifié : une autorité locale doit se lire."""
        req = urllib.request.Request(url, headers=dict(headers, Host=host))
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                return r.status, r.read(65536).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read(65536).decode("utf-8", "replace")
        except OSError as e:
            return 0, f"ERROR {e}"


def new_key():
    return "".join(secrets.choice(_ALPHABET) for _ in range(32))


def _key_path(root, name):
    return os.path.join(root, KEYS, f"{name}.key")


def _write_key(path, key):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    os.chmod(os.path.dirname(path), 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    os.chmod(path, 0o600)


def _read_key(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _php(entry, system, code, stdin_text=None):
    target = debug.Target(entry, system)
    rc, out = target.php(code % target.master, stdin_text)
    m = re.search(r"^ERPLIBRE_API_OK\b(.*)$", out, re.M)
    if rc or not m:
        errors = re.search(r"^ERPLIBRE_API_ERRORS (.*)$", out, re.M)
        print(t("Dolibarr refused:"))
        print(
            "; ".join(json.loads(errors.group(1)))
            if errors
            else out.strip()[-1000:]
        )
        return None
    return m.group(1).split()


def _version(body):
    """La version que rend /status, ou None si le corps n'en est pas un."""
    try:
        return str(json.loads(body)["success"]["dolibarr_version"]) or None
    except (ValueError, KeyError, TypeError):
        return None


def check(name, entry, root, system):
    key = _read_key(_key_path(root, name))
    if not key:
        print(t("No API key for %s: run api.py enable.") % name)
        return 1
    base, host = _local_base(entry)
    code, body = system.http(
        base + "/api/index.php/status", host, {"DOLAPIKEY": key}
    )
    version = _version(body) if code == 200 else None
    if version:
        print(
            t("API of %s answers with its key: Dolibarr %s.") % (name, version)
        )
        print(
            t("Explorer: %s")
            % (entry.get("url", base) + "/api/index.php/explorer/")
        )
        return 0
    if code == 401:
        print(t("API of %s refuses the key (401).") % name)
    elif code in (200, 404, 501):
        # Module éteint, Dolibarr répond 200 et une phrase, pas le JSON.
        print(t("API of %s is off: run api.py enable.") % name)
    else:
        print(t("API of %s does not answer: %s") % (name, body.strip()[-300:]))
    return 1


def enable(name, entry, login, rotate, root, system):
    path = _key_path(root, name)
    kept = _read_key(path)
    key = "" if kept and not rotate else new_key()
    answer = _php(
        entry, system, _PHP_ENABLE, json.dumps({"login": login, "key": key})
    )
    if answer is None:
        return 1
    if key:
        _write_key(path, key)
    rights = answer[1] if len(answer) > 1 else "?"
    print(
        t("API on for %s: user %s, %s read right(s), key in %s (0600).")
        % (name, login, rights, os.path.relpath(path, root))
    )
    return check(name, entry, root, system)


def disable(name, entry, system):
    if _php(entry, system, _PHP_DISABLE) is None:
        return 1
    print(t("API off for %s; its key stays for a later enable.") % name)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("enable", "status", "disable"):
        p = sub.add_parser(action)
        p.add_argument("--instance", required=True)
        if action != "status":
            p.add_argument("--confirm", default="")
        if action == "enable":
            p.add_argument("--login", default="erplibre_api")
            p.add_argument("--rotate", action="store_true")
    return parser


def main(argv=None, root=None, system=None):
    args = build_parser().parse_args(argv)
    root = root or ROOT
    system = system or System()
    try:
        known = lib_dolibarr.load_registry(root)
    except lib_dolibarr.RegistryError as e:
        print(t("Dolibarr registry unreadable: %s") % e)
        return 2
    entry = known.get(args.instance)
    if entry is None:
        print(t("No instance named %s.") % args.instance)
        return 2
    if args.action == "status":
        return check(args.instance, entry, root, system)
    if entry.get("mode") == "prod" and args.confirm != args.instance:
        print(
            t("%s is a production: retype its name with --confirm.")
            % args.instance
        )
        return 2
    if args.action == "disable":
        return disable(args.instance, entry, system)
    if not _LOGIN.match(args.login):
        print(t("Invalid login: %s") % args.login)
        return 2
    return enable(args.instance, entry, args.login, args.rotate, root, system)


if __name__ == "__main__":
    sys.exit(main())
