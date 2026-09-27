#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""phpcs et PHPStan sur un module Dolibarr, selon les règles de Dolibarr.

    ./script/dolibarr/quality.py --instance erp --name Zorglub \\
        [--only phpcs|phpstan] [--engine docker|podman]

Les outils tournent dans l'image composer épinglée (tools_image de
conf/supported_version_dolibarr.json), installés une fois dans un volume
nommé d'après l'image et leurs versions : rien sur l'hôte, le même
chemin sur tout système qui a Docker ou Podman. PHPStan prend la version
du CI du Dolibarr épinglé ; phpcs, que ce CI ne fixe pas, la dernière 3.x,
celle que visent les règles maison de Dolibarr.

Le checkout du cœur (celui de l'instance en natif, le checkout épinglé
pour un conteneur) et le module sont montés en lecture seule. phpcs part
de la racine du checkout avec dev/setup/codesniffer/ruleset.xml.
PHPStan prend phpstan.neon.dist, le cœur pour symboles et l'amorce du CI ;
la ligne de base du gabarit ModuleBuilder y suit le module renommé, pour
que seul ce que le développeur a écrit ressorte. Le module étant analysé
hors de l'arbre de Dolibarr, les inclusions de main.inc.php ne s'y
résolvent pas : elles sont tues, package.py juge leurs essais multiples.

Sortie 0 sans constat, 1 avec constats, 2 si un outil n'a pas pu aller au
bout. Une production est refusée.
"""

import argparse
import hashlib
import os
import re
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

PHPCS = "3.13.6"
# Si le flux CI du checkout ne dit pas la sienne.
PHPSTAN = "2.1.12"
RULESET = "dev/setup/codesniffer/ruleset.xml"
PHPSTAN_DIST = "phpstan.neon.dist"
BOOTSTRAP = "dev/build/phpstan/bootstrap_action.php"
BASELINE = "dev/build/phpstan/phpstan-baseline.neon"
_TEMPLATE = "../../../htdocs/modulebuilder/template/"
_BIN = "/tools/php/vendor/bin"

# Exécutable, l'outil est là ; sinon composer l'installe dans le volume.
_INSTALL = (
    "test -x {bin}/phpcs && test -x {bin}/phpstan || {{ mkdir -p /tools/php"
    " && composer require --working-dir=/tools/php --no-interaction"
    " --no-progress squizlabs/php_codesniffer:{phpcs}"
    " phpstan/phpstan:{phpstan}; }}"
)
# Hors de l'arbre de Dolibarr, aucun chemin relatif vers main.inc.php ne
# se résout ; une autre inclusion introuvable reste un constat.
_MAIN_INCLUDE = (
    "\t\t-\n"
    "\t\t\tmessage: '#^Path in (include|require)(_once)?\\(\\)"
    ' "[^"]*(main|master)\\.inc\\.php" is not a file#\'\n'
    "\t\t\tidentifier: include.fileNotFound\n"
)


def phpstan_version(checkout):
    """La version de PHPStan du CI de Dolibarr (.github/workflows)."""
    try:
        with open(
            os.path.join(checkout, ".github", "workflows", "phpstan.yml"),
            encoding="utf-8",
        ) as f:
            m = re.search(r"\bphpstan:(\d+\.\d+\.\d+)", f.read())
    except OSError:
        m = None
    return m.group(1) if m else PHPSTAN


def tools_volume(image, phpcs, phpstan):
    key = hashlib.sha256(f"{image}|{phpcs}|{phpstan}".encode()).hexdigest()
    return f"erplibre-dolibarr-quality-{key[:12]}"


def _baseline_entries(text):
    """Les entrées de la ligne de base : {clé: valeur brute neon}."""
    entries, current = [], None
    for line in text.splitlines():
        s = line.strip()
        if s == "-":
            current = {}
            entries.append(current)
            continue
        m = re.match(r"^(message|rawMessage|identifier|count|path): (.*)$", s)
        if m and current is not None:
            current[m.group(1)] = m.group(2)
    return entries


def _rename(text, case):
    return (
        text.replace("MYMODULE", case.upper())
        .replace("MyModule", case)
        .replace("mymodule", case.lower())
    )


def template_ignores(baseline, module_dir, lower, case):
    """Les entrées du gabarit, sur les fichiers du module qui en sont nés :
    même constat, même compte, chemin et jetons renommés comme le
    ModuleBuilder les renomme."""
    kept = []
    for entry in _baseline_entries(baseline):
        path = entry.get("path", "")
        if not path.startswith(_TEMPLATE):
            continue
        if entry.get("identifier") == "include.fileNotFound":
            continue
        rel = path[len(_TEMPLATE) :]
        rel = rel.replace("mymodule", lower).replace("MyModule", case)
        if not os.path.isfile(os.path.join(module_dir, rel)):
            continue
        mapped = {
            k: _rename(v, case)
            for k, v in entry.items()
            if k in ("message", "rawMessage", "identifier", "count")
        }
        mapped["path"] = f"/module/{lower}/{rel}"
        kept.append(mapped)
    return kept


def phpstan_config(baseline, module_dir, lower, case):
    lines = [
        "includes:",
        f"\t- /dolibarr/{PHPSTAN_DIST}",
        "parameters:",
        "\ttmpDir: /tools/cache/phpstan",
        "\tscanDirectories:",
        "\t\t- /dolibarr/htdocs",
        "\tbootstrapFiles:",
        f"\t\t- /dolibarr/{BOOTSTRAP}",
        "\tignoreErrors:",
    ]
    text = "\n".join(lines) + "\n" + _MAIN_INCLUDE
    for entry in template_ignores(baseline, module_dir, lower, case):
        text += "\t\t-\n" + "".join(
            f"\t\t\t{k}: {v}\n" for k, v in entry.items()
        )
    return text


class System(backup.System):
    """Commandes réelles ; stream laisse passer la sortie de l'outil."""

    def stream(self, argv):
        try:
            return subprocess.run(argv).returncode
        except OSError as e:
            print(e)
            return 127

    def fiches(self):
        from script.todo import container_runtime

        return container_runtime.etats()


class QualityError(Exception):
    """Refus avant tout lancement : sortie 2."""


def _module_dir(entry, name):
    """(dossier réel du module sur cette machine, nom en minuscules, nom
    avec la casse de sa classe, lue sur le fichier du descripteur)."""
    if entry.get("runtime") == "container":
        custom = entry["custom_dir"]
    else:
        custom = os.path.join(entry["code_root"], "htdocs", "custom")
    lower = name.lower()
    path = os.path.join(custom, lower)
    wanted = f"mod{lower}.class.php"
    try:
        names = os.listdir(os.path.join(path, "core", "modules"))
    except OSError:
        names = []
    found = [f for f in names if f.lower() == wanted]
    if not found:
        raise QualityError(t("No module %s in %s.") % (name, custom))
    case = found[0][len("mod") : -len(".class.php")]
    return os.path.realpath(path), lower, case


def _checkout(entry, root):
    if entry.get("runtime") == "container":
        try:
            pin = lib_dolibarr.read_pin(root)
        except lib_dolibarr.PinError as e:
            raise QualityError(t("Dolibarr pin unreadable: %s") % e)
        checkout = os.path.join(root, pin["path"])
    else:
        checkout = entry["code_root"]
    for rel in (RULESET, PHPSTAN_DIST, BOOTSTRAP):
        if not os.path.isfile(os.path.join(checkout, rel)):
            raise QualityError(
                t("The Dolibarr checkout lacks %s: %s") % (rel, checkout)
            )
    return checkout


def _engine(entry, wanted, system):
    if entry.get("runtime") == "container":
        return system.engine(entry["engine"])
    from script.dolibarr.install_container import choose_engine

    fiche = choose_engine(system.fiches(), wanted)
    if fiche is None:
        raise QualityError(
            t("Docker / Podman is not offered here: %s")
            % t(lib_dolibarr.NO_ENGINE)
        )
    return fiche


def _verdict(tool, code, findings):
    """(niveau, ligne) : 0 propre, `findings` constats, autre cassé."""
    if code == 0:
        return 0, f"  ✓ {tool}: " + t("no finding")
    if code in findings:
        return 1, f"  ✗ {tool}: " + t("findings above")
    return 2, f"  ✗ {tool}: " + t("did not run to the end (code %d)") % code


def run(entry, name, only, wanted, root, system):
    module_dir, lower, case = _module_dir(entry, name)
    checkout = _checkout(entry, root)
    try:
        image = lib_dolibarr.read_pin(root)["tools_image"]
    except lib_dolibarr.PinError as e:
        raise QualityError(t("Dolibarr pin unreadable: %s") % e)
    fiche = _engine(entry, wanted, system)
    from script.todo import container_runtime

    def cmd(args):
        return container_runtime.commande(fiche, args)

    phpstan = phpstan_version(checkout)
    volume = tools_volume(image, PHPCS, phpstan)
    code, out = system.run(
        cmd(
            ["run", "--rm", "-v", f"{volume}:/tools"]
            + ["-e", "COMPOSER_HOME=/tools/composer", image, "sh", "-c"]
            + [_INSTALL.format(bin=_BIN, phpcs=PHPCS, phpstan=phpstan)]
        )
    )
    if code:
        print(t("The quality tools could not be installed:"))
        print(out.strip()[-2000:])
        return 2
    mounts = ["-v", f"{volume}:/tools", "-v", f"{checkout}:/dolibarr:ro"]
    mounts += ["-v", f"{module_dir}:/module/{lower}:ro"]
    verdicts = []
    if only in (None, "phpcs"):
        print(f"== phpcs {PHPCS} — {RULESET}", flush=True)
        code = system.stream(
            cmd(
                ["run", "--rm", *mounts, "-w", "/dolibarr", image]
                + ["php", "-d", "memory_limit=-1", f"{_BIN}/phpcs"]
                + [f"--standard={RULESET}", "--report=full", "-s"]
                + ["--no-colors", f"/module/{lower}"]
            )
        )
        verdicts.append(_verdict("phpcs", code, (1, 2)))
    if only in (None, "phpstan"):
        print(f"== PHPStan {phpstan} — {PHPSTAN_DIST}", flush=True)
        try:
            with open(os.path.join(checkout, BASELINE), encoding="utf-8") as f:
                baseline = f.read()
        except OSError:
            baseline = ""
        with tempfile.TemporaryDirectory() as work:
            with open(os.path.join(work, "phpstan.neon"), "w") as f:
                f.write(phpstan_config(baseline, module_dir, lower, case))
            code = system.stream(
                cmd(
                    ["run", "--rm", *mounts, "-v", f"{work}:/work:ro", image]
                    + ["php", f"{_BIN}/phpstan", "analyse"]
                    + ["-c", "/work/phpstan.neon", "--no-progress"]
                    + ["--error-format=table", "--memory-limit=4G"]
                    + [f"/module/{lower}"]
                )
            )
        verdicts.append(_verdict("PHPStan", code, (1,)))
    for _level, line in verdicts:
        print(line)
    return max(level for level, _line in verdicts)


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    parser.add_argument("--instance", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--only", choices=("phpcs", "phpstan"))
    parser.add_argument("--engine", choices=("docker", "podman"))
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
    if entry.get("mode") == "prod":
        print(
            t(
                "%s is a production: modules are developed on a development instance."
            )
            % args.instance
        )
        return 2
    try:
        return run(entry, args.name, args.only, args.engine, root, system)
    except QualityError as e:
        print(e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
