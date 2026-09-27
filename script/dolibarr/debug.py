#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le profil de déverminage d'une instance Dolibarr.

    ./script/dolibarr/debug.py on --instance erp [--xdebug]
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

--xdebug, en développement natif seulement, charge Xdebug 3 dans le PHP-FPM
de l'instance et nulle part ailleurs : un .ini sous <état>/run/php.d, que
run.py ajoute au dossier que PHP lit déjà. Mode déclenché (XDEBUG_TRIGGER,
ou l'extension de navigateur), port 9003. php-fpm -m tranche : Xdebug déjà
chargé pour tout l'hôte (Debian et Fedora l'allument à l'installation)
n'est pas chargé une seconde fois ; absent, son paquet s'installe. Le
checkout reçoit .vscode/launch.json (son .gitignore l'ignore), fusionné
par nom ; PhpStorm se règle à la main, la marche à suivre est affichée.
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

from script.dolibarr import backup, lib_dolibarr, packages  # noqa: E402

ROOT = new_path
t = backup.t

_KEYS = (
    "MAIN_FEATURES_LEVEL",
    "SYSLOG_LEVEL",
    "MAIN_MODULE_SYSLOG",
    "MAIN_MODULE_DEBUGBAR",
)
_CONF = {"dolibarr_main_prod": "0", "dolibarr_strict_mode": "1"}
XDEBUG_INI = "90-erplibre-xdebug.ini"
XDEBUG_PORT = 9003

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


class System(backup.System):
    def interactive(self, argv):
        """Code de sortie ; le terminal reste branché (mot de passe sudo)."""
        try:
            return subprocess.run(argv).returncode
        except OSError as e:
            print(e)
            return 127


def _fpm_binary():
    from script.dolibarr import run

    return run._local_binaries()[0]


def _family():
    from script.todo import todo_install

    return todo_install.family()


def _install_argv(family):
    from script.todo import todo_install

    return todo_install.install_command(
        [packages.xdebug_package(family)], family
    )


def restart_fpm(name, root):
    """Relance les démons de l'instance : PHP-FPM relit ses .ini."""
    from script.dolibarr import run

    run.main(["stop", "--instance", name], root=root)
    return run.main(["start", "--instance", name], root=root)


def xdebug_ini(load):
    """Le .ini de l'instance ; `load` ajoute zend_extension, à omettre
    quand l'hôte charge déjà Xdebug."""
    lines = ["zend_extension=xdebug.so"] if load else []
    lines += [
        "xdebug.mode=debug",
        "xdebug.start_with_request=trigger",
        "xdebug.client_host=127.0.0.1",
        f"xdebug.client_port={XDEBUG_PORT}",
    ]
    return "\n".join(lines) + "\n"


def launch_config(name):
    return {
        "name": f"Dolibarr {name} (Xdebug)",
        "type": "php",
        "request": "launch",
        "port": XDEBUG_PORT,
    }


def merge_launch(text, name):
    """launch.json avec la configuration de `name`, remplacée si elle y
    est ; None si `text` n'est pas du JSON pur (VS Code tolère des
    commentaires, que ce module ne réécrirait pas)."""
    if text is None:
        data = {"version": "0.2.0", "configurations": []}
    else:
        try:
            data = json.loads(text)
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
    config = launch_config(name)
    kept = [
        c
        for c in data.get("configurations", [])
        if c.get("name") != config["name"]
    ]
    data["configurations"] = kept + [config]
    data.setdefault("version", "0.2.0")
    return json.dumps(data, indent=4, ensure_ascii=False) + "\n"


def _loads_xdebug(system, fpm, env=None):
    """Xdebug figure-t-il dans la liste des modules de php-fpm -m ? Une
    ligne entière : l'avertissement d'un .so absent le nomme aussi."""
    _code, out = system.run([fpm, "-m"], env)
    return any(line.strip().lower() == "xdebug" for line in out.splitlines())


def xdebug_on(name, entry, system, root):
    """Charge Xdebug dans le pool de l'instance ; True si fait."""
    fpm = _fpm_binary()
    if not fpm:
        print(t("PHP-FPM is missing: install the instance again."))
        return False
    from script.dolibarr import run

    inst = run.Instance(name, entry)
    ini = os.path.join(inst.php_d, XDEBUG_INI)
    os.makedirs(inst.php_d, exist_ok=True)
    for attempt in (1, 2):
        host = _loads_xdebug(system, fpm)
        with open(ini, "w", encoding="utf-8") as f:
            f.write(xdebug_ini(load=not host))
        # L'environnement même de run.py : ce que le pool chargera.
        if _loads_xdebug(system, fpm, run.fpm_env(inst)):
            break
        if attempt == 2:
            os.remove(ini)
            print(t("Xdebug does not load in PHP-FPM after its install."))
            return False
        argv = _install_argv(_family())
        print(t("Xdebug is missing; installing it: %s") % " ".join(argv))
        if system.interactive(argv):
            os.remove(ini)
            print(t("Xdebug could not be installed."))
            return False
    if host:
        print(
            t(
                "This host's PHP already loads Xdebug for every program;"
                " step debugging is switched on in this pool only."
            )
        )
    restart_fpm(name, root)
    _write_launch(name, entry)
    print(
        t(
            "PhpStorm: Settings › PHP › Debug, Xdebug port %d; Settings ›"
            " PHP › Servers, host 127.0.0.1, port %s, debugger Xdebug, no"
            " path mapping; then Run › Start Listening for PHP Debug"
            " Connections."
        )
        % (XDEBUG_PORT, entry.get("port", "?"))
    )
    print(
        t(
            "Trigger a request with the Xdebug helper of your browser, or"
            " add ?XDEBUG_TRIGGER=1 to the address."
        )
    )
    return True


def _write_launch(name, entry):
    path = os.path.join(entry["code_root"], ".vscode", "launch.json")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = None
    merged = merge_launch(text, name)
    if merged is None:
        print(
            t("%s holds comments and is left as is; add this configuration:")
            % path
        )
        print(json.dumps(launch_config(name), indent=4))
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(merged)
    print(
        t("VS Code: configuration « %s » in %s")
        % (launch_config(name)["name"], path)
    )


def xdebug_off(name, entry, root):
    from script.dolibarr import run

    ini = os.path.join(run.Instance(name, entry).php_d, XDEBUG_INI)
    try:
        os.remove(ini)
    except FileNotFoundError:
        pass
    restart_fpm(name, root)


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


def _save(state, saved):
    fd = os.open(state, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(saved, indent=4, sort_keys=True) + "\n")


def turn_on(name, entry, system, xdebug=False, root=None):
    state = _state_file(entry)
    if os.path.exists(state):
        with open(state, encoding="utf-8") as f:
            saved = json.load(f)
        if not xdebug or saved.get("xdebug"):
            print(t("Debug already on for %s.") % name)
            return 0
        if not xdebug_on(name, entry, system, root):
            return 1
        saved["xdebug"] = True
        _save(state, saved)
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
    saved["xdebug"] = bool(xdebug) and xdebug_on(name, entry, system, root)
    _save(state, saved)
    print(
        t("Debug on for %s: DebugBar, Syslog level 7, development features.")
        % name
    )
    print(t("Follow the log with: debug.py tail --instance %s") % name)
    return 1 if xdebug and not saved["xdebug"] else 0


def turn_off(name, entry, system, root=None):
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
    if saved.get("xdebug"):
        xdebug_off(name, entry, root)
    os.remove(state)
    print(t("Debug off for %s: the previous settings are back.") % name)
    return 0


def status(name, entry):
    state = _state_file(entry)
    if os.path.exists(state):
        with open(state, encoding="utf-8") as f:
            saved = json.load(f)
        print(t("Debug on for %s since %s.") % (name, saved["date"]))
        if saved.get("xdebug"):
            print(t("Xdebug on, port %d.") % XDEBUG_PORT)
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
        if action == "on":
            p.add_argument("--xdebug", action="store_true")
        if action == "tail":
            p.add_argument("--filter")
            p.add_argument("--lines", type=int, default=50)
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
        return status(args.instance, entry)
    if args.action == "tail":
        return tail(entry, system, args.filter, args.lines)
    if getattr(args, "xdebug", False) and (
        entry.get("mode") == "prod" or entry.get("runtime") == "container"
    ):
        print(t("Xdebug is offered on native development instances only."))
        return 2
    if entry.get("mode") == "prod" and args.confirm != args.instance:
        print(
            t("%s is a production: retype its name with --confirm.")
            % args.instance
        )
        return 2
    if args.action == "on":
        return turn_on(args.instance, entry, system, args.xdebug, root)
    return turn_off(args.instance, entry, system, root)


if __name__ == "__main__":
    sys.exit(main())
