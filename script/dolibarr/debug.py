#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le profil de déverminage d'une instance Dolibarr.

    ./script/dolibarr/debug.py on --instance erp
    ./script/dolibarr/debug.py off --instance erp
    ./script/dolibarr/debug.py status --instance erp
    ./script/dolibarr/debug.py tail --instance erp [--filter ERR] [--lines 50]

on : fonctionnalités en développement visibles (MAIN_FEATURES_LEVEL=2),
modules Syslog et DebugBar actifs, journal au niveau 7 (chaque requête SQL),
et en développement natif conf.php à prod=0 et en mode strict (toutes les
notices PHP). L'état d'avant est retenu dans <état>/debug.json, une seule
fois : off le remet tel quel, constante absente comprise, puis l'oublie.

En conteneur, conf.php n'est pas touché : l'image le réécrit depuis ses
variables à chaque recréation, et DOLI_PROD vaut déjà 0 en développement.
Une production est refusée sans --confirm égal à son nom : le niveau 7
écrit les identifiants de session dans dolibarr.log.
"""

import argparse
import datetime
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import backup, lib_dolibarr  # noqa: E402

ROOT = new_path
t = backup.t

_KEYS = (
    "MAIN_FEATURES_LEVEL",
    "SYSLOG_LEVEL",
    "MAIN_MODULE_SYSLOG",
    "MAIN_MODULE_DEBUGBAR",
)
_CONF = {"dolibarr_main_prod": "0", "dolibarr_strict_mode": "1"}

# %s : chemin de master.inc.php. Rend l'état d'avant, puis allume.
_PHP_ON = (
    'require "%s"; require_once DOL_DOCUMENT_ROOT."/core/lib/admin.lib.php";'
    ' $keys = array("' + '", "'.join(_KEYS) + '"); $prev = array();'
    # La ligne de l'entité courante, pas $conf->global : il mêle l'entité 0,
    # et off y écrirait une ligne qui n'existait pas.
    ' foreach ($keys as $k) { $r = $db->query("SELECT value FROM "'
    ' .MAIN_DB_PREFIX."const WHERE name = \x27".$db->escape($k)'
    ' ."\x27 AND entity = ".((int) $conf->entity));'
    " $o = $r ? $db->fetch_object($r) : null;"
    " $prev[$k] = $o ? (string) $o->value : null; }"
    ' activateModule("modSyslog"); activateModule("modDebugBar");'
    ' dolibarr_set_const($db, "MAIN_FEATURES_LEVEL", "2", "chaine", 0, "",'
    " $conf->entity);"
    ' dolibarr_set_const($db, "SYSLOG_LEVEL", "7", "chaine", 0, "",'
    " $conf->entity);"
    ' echo "ERPLIBRE_DEBUG_ON\\n", "ERPLIBRE_DEBUG ", json_encode($prev), "\\n";'
)
# L'état d'avant arrive sur stdin, en JSON.
_PHP_OFF = (
    'require "%s"; require_once DOL_DOCUMENT_ROOT."/core/lib/admin.lib.php";'
    " $prev = json_decode(trim(stream_get_contents(STDIN)), true);"
    ' foreach (array("MAIN_FEATURES_LEVEL", "SYSLOG_LEVEL") as $k) {'
    " if ($prev[$k] === null) { dolibarr_del_const($db, $k, $conf->entity); }"
    ' else { dolibarr_set_const($db, $k, $prev[$k], "chaine", 0, "",'
    " $conf->entity); } }"
    ' if (empty($prev["MAIN_MODULE_DEBUGBAR"])) unActivateModule("modDebugBar");'
    ' if (empty($prev["MAIN_MODULE_SYSLOG"])) unActivateModule("modSyslog");'
    ' echo "ERPLIBRE_DEBUG_OFF\\n";'
)


def set_php_var(text, name, value):
    """conf.php où `$name` vaut `value` ; None ôte la ligne."""
    pattern = re.compile(rf"^\${re.escape(name)}\s*=.*;[ \t]*\n?", re.M)
    if value is None:
        return pattern.sub("", text)
    line = f"${name}='{value}';\n"
    text, count = pattern.subn(line, text)
    if not count:
        text = (text if text.endswith("\n") else text + "\n") + line
    return text


def get_php_var(text, name):
    m = re.search(rf"^\${re.escape(name)}\s*=\s*'([^']*)'", text, re.M)
    return m.group(1) if m else None


def matching(lines, pattern):
    """Les lignes qui contiennent `pattern` (expression régulière)."""
    regex = re.compile(pattern) if pattern else None
    for line in lines:
        if regex is None or regex.search(line):
            yield line


class Target:
    """Où lancer PHP pour une instance, et où est son journal."""

    def __init__(self, entry, system):
        self.entry, self.system = entry, system
        self.container = entry.get("runtime") == "container"
        if self.container:
            from script.todo import container_runtime

            fiche = system.engine(entry["engine"])
            self.cmd = lambda args: container_runtime.commande(fiche, args)
            self.web = entry["containers"][1]
            self.master = "/var/www/html/master.inc.php"
            self.log = "/var/www/documents/dolibarr.log"
        else:
            self.htdocs = os.path.join(entry["code_root"], "htdocs")
            self.master = os.path.join(self.htdocs, "master.inc.php")
            self.log = os.path.join(entry["data_root"], "dolibarr.log")

    def php(self, code, stdin_text=None):
        if self.container:
            # En www-data, comme le site : un dossier créé par root dans
            # documents/ lui serait fermé en écriture.
            argv = self.cmd(
                ["exec"]
                + (["-i"] if stdin_text else [])
                + ["-u", "www-data", self.web, "php", "-r", code]
            )
        else:
            argv = [
                "sh",
                "-c",
                f"cd {shlex.quote(self.htdocs)} && exec php -r {shlex.quote(code)}",
            ]
        if stdin_text is None:
            return self.system.run(argv)
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(stdin_text)
        try:
            return self.system.run(argv, stdin_path=f.name)
        finally:
            os.remove(f.name)

    def conf_path(self):
        return (
            None
            if self.container
            else os.path.join(self.htdocs, "conf", "conf.php")
        )


def _state_file(entry):
    return os.path.join(entry["state_dir"], "debug.json")


def _write_keep_mode(path, text):
    """Réécrit `path` en place : ouvrir un fichier existant garde son mode."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def turn_on(name, entry, system):
    state = _state_file(entry)
    if os.path.exists(state):
        print(t("Debug already on for %s.") % name)
        return 0
    target = Target(entry, system)
    code, out = target.php(_PHP_ON % target.master)
    m = re.search(r"^ERPLIBRE_DEBUG (\{.*\})$", out, re.M)
    if code or not m:
        print(t("Debug could not be turned on:"))
        print(out.strip()[-1000:])
        return 1
    saved = {
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "constants": json.loads(m.group(1)),
        "conf": {},
    }
    conf = target.conf_path()
    if conf:
        with open(conf, encoding="utf-8") as f:
            text = f.read()
        saved["conf"] = {k: get_php_var(text, k) for k in _CONF}
        for k, v in _CONF.items():
            text = set_php_var(text, k, v)
        _write_keep_mode(conf, text)
    else:
        print(
            t(
                "conf.php is left as is: the image rewrites it on each recreation."
            )
        )
    fd = os.open(state, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(saved, indent=4, sort_keys=True) + "\n")
    print(
        t("Debug on for %s: DebugBar, Syslog level 7, development features.")
        % name
    )
    print(t("Follow the log with: debug.py tail --instance %s") % name)
    return 0


def turn_off(name, entry, system):
    state = _state_file(entry)
    if not os.path.exists(state):
        print(t("Debug is not on for %s.") % name)
        return 0
    with open(state, encoding="utf-8") as f:
        saved = json.load(f)
    target = Target(entry, system)
    code, out = target.php(
        _PHP_OFF % target.master, json.dumps(saved["constants"])
    )
    if code or "ERPLIBRE_DEBUG_OFF" not in out:
        print(t("Debug could not be turned off:"))
        print(out.strip()[-1000:])
        return 1
    conf = target.conf_path()
    if conf and saved.get("conf"):
        with open(conf, encoding="utf-8") as f:
            text = f.read()
        for k, v in saved["conf"].items():
            text = set_php_var(text, k, v)
        _write_keep_mode(conf, text)
    os.remove(state)
    print(t("Debug off for %s: the previous settings are back.") % name)
    return 0


def status(name, entry):
    state = _state_file(entry)
    if os.path.exists(state):
        with open(state, encoding="utf-8") as f:
            print(
                t("Debug on for %s since %s.") % (name, json.load(f)["date"])
            )
    else:
        print(t("Debug is not on for %s.") % name)
    return 0


def tail(entry, system, pattern, lines):
    """Suit dolibarr.log jusqu'à Ctrl-C, filtré par `pattern`."""
    target = Target(entry, system)
    argv = ["tail", "-n", str(lines), "-F", target.log]
    if target.container:
        argv = target.cmd(["exec", target.web] + argv)
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, text=True)
    try:
        # Ligne par ligne : dans un tube (grep, less), la sortie serait
        # sinon retenue en tampon jusqu'à l'arrêt.
        for line in matching(proc.stdout, pattern):
            print(line, end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("on", "off", "status", "tail"):
        p = sub.add_parser(action)
        p.add_argument("--instance", required=True)
        p.add_argument("--confirm", default="")
        if action == "tail":
            p.add_argument("--filter")
            p.add_argument("--lines", type=int, default=50)
    return parser


def main(argv=None, root=None, system=None):
    args = build_parser().parse_args(argv)
    root = root or ROOT
    system = system or backup.System()
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
        return status(args.instance, entry)
    if args.action == "tail":
        return tail(entry, system, args.filter, args.lines)
    if entry.get("mode") == "prod" and args.confirm != args.instance:
        print(
            t("%s is a production: retype its name with --confirm.")
            % args.instance
        )
        return 2
    if args.action == "on":
        return turn_on(args.instance, entry, system)
    return turn_off(args.instance, entry, system)


if __name__ == "__main__":
    sys.exit(main())
