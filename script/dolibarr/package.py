#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le paquet d'un module Dolibarr, et ce que DoliStore en exige.

    ./script/dolibarr/package.py check --instance erp --name Zorglub
    ./script/dolibarr/package.py build --instance erp --name Zorglub \\
        [--dolistore]

build fait ce que fait « Générer le paquet » du ModuleBuilder :
<module>/bin/module_<nom>-<version>.zip, le dossier du module à la racine,
sans bin/ ni ce qui ressemble à .git, .old, .back, .ssh. Ces exclusions sont
jugées sur le chemin DANS le module ; le ModuleBuilder les juge sur le
chemin réel, où un dossier parent nommé *.git exclurait tout.

Le contrôle a trois étages :
- ce qui empêche tout déploiement, et donc le zip : descripteur illisible,
  nom de paquet que « Déployer un module externe » refuse (version non
  numérique), erreur de syntaxe PHP ;
- ce que DoliStore refuse : numéro hors des plages distribuables (95000 à
  99999, 100000 à 499999 réservé sur le wiki ; 500000 et plus ne se
  distribue pas), en_US absent ou incomplet, page qui n'essaie
  main.inc.php qu'à un seul endroit, script sans « #!/usr/bin/env php »,
  copie d'un fichier du cœur ; bloquant avec --dolistore ;
- des avis : « Dolibarr » comme mot du nom (marque de l'Association
  Dolibarr), éditeur sans nom ou sans URL.

Le descripteur est lu par le PHP de l'instance (version, numéro, éditeur) :
une instance en conteneur doit tourner. Une production est refusée.
"""

import argparse
import json
import os
import re
import shlex
import sys
import zipfile

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import (  # noqa: E402
    backup,
    debug,
    integrity,
    lib_dolibarr,
    module,
)

ROOT = new_path
t = backup.t

# Le nom qu'admin/modules.php exige d'un paquet à déployer.
DEPLOY_NAME = re.compile(
    r"^(module[a-zA-Z0-9]*_|theme_|).*\-([0-9][0-9\.]*)(\s\(\d+\)\s)?\.zip$",
    re.I,
)
# Les exclusions de « Générer le paquet », sur "/" + chemin dans le module.
EXCLUDED = re.compile(r"/bin/|\.git|\.old|\.back|\.ssh")
_INCLUDE = re.compile(
    r"\b(?:include|require)(?:_once)?\b[^;]*\b(?:main|master)\.inc\.php"
)
_LANG_KEY = re.compile(r"^\s*([^#=\s][^=]*?)\s*=")
_CODE = re.compile(r"\.(php|js|css)$", re.I)
_WORDS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

# %s : master.inc.php, dossier du module, classe, classe.
_PHP_FACTS = (
    'require "%s";'
    ' require_once DOL_DOCUMENT_ROOT."/core/modules/DolibarrModules.class.php";'
    ' if (!dol_include_once("/%s/core/modules/%s.class.php")) {'
    ' echo "descriptor not found\\n"; exit(1); }'
    ' $m = new %s($db); echo "ERPLIBRE_PACKAGE ", json_encode(array('
    ' "version" => (string) $m->version, "numero" => (int) $m->numero,'
    ' "editor_name" => (string) $m->editor_name,'
    ' "editor_url" => (string) $m->editor_url)), "\\n";'
)
# Lancé depuis le dossier du module : chaque PHP qui ne passe pas php -l.
_LINT = (
    "find . -name '*.php' -exec sh -c 'for f; do out=$(php -l \"$f\" 2>&1)"
    ' || echo "ERPLIBRE_LINT $f: $(echo "$out" | grep -i -m1 error)"; done'
    "' sh {} +; echo ERPLIBRE_LINT_DONE"
)

OK, FAIL, WARN = "✓", "✗", "!"


class PackageError(Exception):
    """Refus avant tout contrôle : sortie 2."""


def _empty(part):
    """empty() de PHP sur un morceau de version."""
    return part in ("", "0")


def zip_name(lower, version):
    """Le nom du ModuleBuilder : majeur, mineur (.0 s'il manque), correctif
    s'il y en a un non nul ; explode() en trois garde le reste entier."""
    parts = version.split(".", 2) + ["", ""]
    text = parts[0] + (".0" if _empty(parts[1]) else "." + parts[1])
    text += "" if _empty(parts[2]) else "." + parts[2]
    return f"module_{lower}-{text}.zip"


def members(module_dir):
    """[(chemin dans le module, chemin sur disque)] des fichiers du paquet,
    triés : un dossier lié n'est pas parcouru, un fichier lié l'est."""
    found = []
    for base, dirs, files in os.walk(module_dir):
        dirs.sort()
        for name in files:
            full = os.path.join(base, name)
            rel = os.path.relpath(full, module_dir).replace(os.sep, "/")
            if EXCLUDED.search("/" + rel) or not os.path.isfile(full):
                continue
            found.append((rel, full))
    return sorted(found)


def build_zip(module_dir, lower, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, full in members(module_dir):
            z.write(full, f"{lower}/{rel}")


def _lang_keys(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return {m.group(1) for m in map(_LANG_KEY.match, f) if m}


def lang_gaps(module_dir):
    """None si en_US manque ; sinon {langue/fichier: [clés absentes
    d'en_US]}."""
    langs = os.path.join(module_dir, "langs")
    en = os.path.join(langs, "en_US")
    if not os.path.isdir(en) or not any(
        f.endswith(".lang") for f in os.listdir(en)
    ):
        return None
    gaps = {}
    for lang in sorted(os.listdir(langs)):
        if lang == "en_US" or not os.path.isdir(os.path.join(langs, lang)):
            continue
        for name in sorted(os.listdir(os.path.join(langs, lang))):
            if not name.endswith(".lang"):
                continue
            ref = os.path.join(en, name)
            known = _lang_keys(ref) if os.path.exists(ref) else set()
            missing = sorted(
                _lang_keys(os.path.join(langs, lang, name)) - known
            )
            if missing:
                gaps[f"{lang}/{name}"] = missing
    return gaps


def _texts(module_dir, pattern):
    for rel, full in members(module_dir):
        if pattern.search(rel):
            with open(full, encoding="utf-8", errors="replace") as f:
                yield rel, f.read()


def single_includes(module_dir):
    """Les pages hors test/ qui n'essaient main.inc.php (ou master) qu'à un
    endroit : ailleurs que dans custom/, elles ne se chargent plus."""
    return [
        rel
        for rel, text in _texts(module_dir, re.compile(r"\.php$", re.I))
        if not rel.startswith("test/") and len(_INCLUDE.findall(text)) == 1
    ]


def bad_scripts(module_dir):
    return [
        rel
        for rel, text in _texts(module_dir, re.compile(r"^scripts/.*\.php$"))
        if not text.startswith("#!/usr/bin/env php")
    ]


def core_copies(module_dir, core_blobs):
    """Les fichiers de code identiques, octet pour octet, à un fichier du
    cœur."""
    return [
        rel
        for rel, full in members(module_dir)
        if _CODE.search(rel)
        and os.path.getsize(full)
        and integrity.blob_hash(full) in core_blobs
    ]


def trademark(names):
    """Les noms où « Dolibarr » est un mot, hors « for/from Dolibarr » et
    mention « (non official) » ; « Doli… » en mot-valise est permis."""
    flagged = []
    for name in names:
        words = [w.lower() for w in _WORDS.findall(name)]
        if "(non official)" in name.lower():
            continue
        for i, word in enumerate(words):
            if word == "dolibarr" and (
                i == 0 or words[i - 1] not in ("for", "from")
            ):
                flagged.append(name)
                break
    return flagged


def id_verdict(numero):
    if 95000 <= numero <= 499999:
        return OK, t("ID %d in a distributable range") % numero
    if numero >= 500000:
        return FAIL, t(
            "ID %d is private (500000 and up): reserve one from 100000 to"
            " 499999 on the Dolibarr wiki (List_of_modules_id)"
        ) % numero
    return FAIL, t("ID %d is in the core range (below 95000)") % numero


def core_blobs(tree):
    """Les blobs d'un `git ls-tree -r`, hors gabarit du ModuleBuilder : il
    est fait pour être copié, et buildzip.php en sort identique."""
    blobs = set()
    for line in tree.splitlines():
        meta, _tab, path = line.partition("\t")
        fields = meta.split()
        if len(fields) == 3 and fields[1] == "blob":
            if not path.startswith("htdocs/modulebuilder/template/"):
                blobs.add(fields[2])
    return blobs


def _core_blobs(entry, root, system):
    """Les blobs du checkout du cœur : celui de l'instance en natif, le
    checkout épinglé pour un conteneur ; None s'il n'y en a pas ici."""
    if entry.get("runtime") == "container":
        try:
            checkout = os.path.join(root, lib_dolibarr.read_pin(root)["path"])
        except lib_dolibarr.PinError:
            return None
    else:
        checkout = entry["code_root"]
    code, out = system.run(["git", "-C", checkout, "ls-tree", "-r", "HEAD"])
    if code:
        return None
    return core_blobs(out)


class Module:
    """Un module de custom/ d'une instance : où il est sur cette machine,
    et comment son PHP s'y lance."""

    def __init__(self, entry, name, system):
        self.entry, self.system = entry, system
        place = module.Place(entry, system)
        inventory = place.inventory()
        if inventory is None:
            raise PackageError(module._unreachable(name))
        found = inventory.modules.get("mod" + name.lower())
        if found is None or not found[1].startswith("custom/"):
            raise PackageError(
                t("No module %s in the custom/ of this instance.") % name
            )
        self.cls = found[0]
        self.dirname = found[1].split("/")[1]
        self.path = os.path.join(place.custom, self.dirname)
        self.place = place

    def facts(self):
        target = debug.Target(self.entry, self.system)
        code, out = target.php(
            _PHP_FACTS % (target.master, self.dirname, self.cls, self.cls)
        )
        m = re.search(r"^ERPLIBRE_PACKAGE (\{.*\})$", out, re.M)
        if code or not m:
            return None, out.strip()[-500:]
        return json.loads(m.group(1)), ""

    def lint(self):
        if self.place.container:
            where = f"/var/www/html/custom/{self.dirname}"
            argv = self.place.cmd(
                ["exec", self.place.web, "sh", "-c", f"cd {where} && {_LINT}"]
            )
        else:
            argv = ["sh", "-c", f"cd {shlex.quote(self.path)} && {_LINT}"]
        _code, out = self.system.run(argv)
        if "ERPLIBRE_LINT_DONE" not in out:
            return [out.strip()[-300:]]
        return [
            line[len("ERPLIBRE_LINT ") :].removeprefix("./")
            for line in out.splitlines()
            if line.startswith("ERPLIBRE_LINT ")
        ]


def _deploy_checks(mod, facts, error):
    """(résultats, nom du zip ou None) de l'étage qui bloque tout."""
    if facts is None:
        return [(FAIL, t("Module descriptor: %s") % error)], None
    results = [(OK, t("Module descriptor: version %s") % facts["version"])]
    name = zip_name(mod.dirname, facts["version"])
    if DEPLOY_NAME.match(name):
        results.append((OK, t("Package name: %s") % name))
    else:
        results.append(
            (
                FAIL,
                t(
                    "Package name %s is refused by Dolibarr: numeric version needed"
                )
                % name,
            )
        )
        name = None
    broken = mod.lint()
    results.append(
        (FAIL, t("PHP syntax: %s") % "; ".join(broken))
        if broken
        else (OK, t("PHP syntax"))
    )
    return results, name


def _dolistore_checks(mod, facts, core_blobs):
    results = [id_verdict(facts["numero"])]
    gaps = lang_gaps(mod.path)
    if gaps is None:
        results.append((FAIL, t("en_US language file missing")))
    elif gaps:
        detail = "; ".join(
            f"{k}: {', '.join(v[:5])}" for k, v in sorted(gaps.items())
        )
        results.append((FAIL, t("Keys missing from en_US: %s") % detail))
    else:
        results.append((OK, t("en_US language file, complete")))
    single = single_includes(mod.path)
    results.append(
        (
            FAIL,
            t("Pages that try main.inc.php in one place only: %s")
            % ", ".join(single),
        )
        if single
        else (OK, t("Pages try main.inc.php in several places"))
    )
    scripts = bad_scripts(mod.path)
    results.append(
        (
            FAIL,
            t("Scripts without #!/usr/bin/env php: %s") % ", ".join(scripts),
        )
        if scripts
        else (OK, t("Command-line scripts"))
    )
    if core_blobs is None:
        results.append(
            (
                WARN,
                t("Copies of core files not checked: no core checkout here"),
            )
        )
    else:
        copies = core_copies(mod.path, core_blobs)
        results.append(
            (FAIL, t("Copies of Dolibarr core files: %s") % ", ".join(copies))
            if copies
            else (OK, t("No copy of a Dolibarr core file"))
        )
    return results


def _notices(mod, facts):
    label = os.path.join(mod.path, "langs", "en_US")
    names = [mod.cls[3:]]
    key = f"Module{facts['numero']}Name"
    for name in sorted(os.listdir(label)) if os.path.isdir(label) else []:
        with open(
            os.path.join(label, name), encoding="utf-8", errors="replace"
        ) as f:
            for line in f:
                k, sep, v = line.partition("=")
                if sep and k.strip() == key:
                    names.append(v.strip())
    results = [
        (WARN, t("%s uses the Dolibarr trademark as a word of the name") % n)
        for n in trademark(names)
    ]
    if not facts["editor_name"] or not facts["editor_url"]:
        results.append((WARN, t("Editor name or URL empty in the descriptor")))
    return results


def run(name, entry, build, dolistore, root, system):
    mod = Module(entry, name, system)
    facts, error = mod.facts()
    results, zipname = _deploy_checks(mod, facts, error)
    deployable = all(level != FAIL for level, _m in results)
    if facts is not None:
        store = _dolistore_checks(mod, facts, _core_blobs(entry, root, system))
        results += store + _notices(mod, facts)
    for level, message in results:
        print(f"  {level} {message}")
    ready = all(level != FAIL for level, _m in results)
    if not build:
        return 0 if ready else 1
    if not deployable or (dolistore and not ready):
        print(t("No package built."))
        return 1
    dest = os.path.join(mod.path, "bin", zipname)
    build_zip(mod.path, mod.dirname, dest)
    print(t("Package: %s") % dest)
    if not ready:
        print(t("Not ready for DoliStore: see the ✗ above."))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("check", "build"):
        p = sub.add_parser(action)
        p.add_argument("--instance", required=True)
        p.add_argument("--name", required=True)
        if action == "build":
            p.add_argument("--dolistore", action="store_true")
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
    if entry.get("mode") == "prod":
        print(
            t(
                "%s is a production: modules are developed on a development instance."
            )
            % args.instance
        )
        return 2
    try:
        return run(
            args.name,
            entry,
            args.action == "build",
            getattr(args, "dolistore", False),
            root,
            system,
        )
    except PackageError as e:
        print(e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
