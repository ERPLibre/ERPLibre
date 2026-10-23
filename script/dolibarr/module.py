#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les modules Dolibarr d'une instance de développement.

    ./script/dolibarr/module.py create --instance erp --name Zorglub \\
        [--id 500123] [--author "Nom <courriel>"] [--editor-name X] \\
        [--editor-url https://...] [--version 1.0] [--picto fa-file] \\
        [--enable]
    ./script/dolibarr/module.py link --instance erp --path ~/src/zorglub
    ./script/dolibarr/module.py enable --instance erp --name Zorglub
    ./script/dolibarr/module.py disable --instance erp --name Zorglub

create refait « Nouveau module » du ModuleBuilder, depuis le gabarit de
l'instance elle-même (htdocs/modulebuilder/template) : copie renommée,
fichiers d'objet et d'options retirés, jetons remplacés, avec ses listes et
dans son ordre. Le module se poursuit ensuite dans le ModuleBuilder. Il naît
dans custom/ : htdocs/custom du checkout en natif, le custom/ de l'hôte monté
dans le conteneur sinon.

Le numéro est le premier libre à partir de 500000, plage jamais distribuée ;
de 100000 à 499999, un numéro se réserve sur le wiki de Dolibarr pour un
module publié. L'auteur vient de --author, sinon de l'identité git ;
l'éditeur est l'auteur, sauf --editor-name.

link pose custom/<nom> en lien symbolique vers un module tenu ailleurs, dans
son propre dépôt, nommé d'après son descripteur. Un conteneur ne voit que
son custom/ : le module s'y crée ou s'y copie.

enable et disable passent par activateModule et unActivateModule, comme la
page des modules : dépendances, constantes, droits et menus compris.
Une production est refusée : on y déploie un paquet, on n'y développe pas.
"""

import argparse
import datetime
import json
import os
import re
import shlex
import shutil
import sys
import tarfile
import tempfile
import unicodedata

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import backup, debug, lib_dolibarr, restore  # noqa: E402

ROOT = new_path
t = backup.t

FIRST_FREE = 500000
LOWEST = 100000
# Les fichiers dont le ModuleBuilder remplace le texte, jugés sur leur nom.
EDITED = re.compile(r"\.(php|MD|js|sql|txt|xml|lang)$", re.I)

# Ce que « Nouveau module » retire après la copie, dans son ordre : tree ôte
# un dossier et son contenu, file un fichier, empty un dossier resté vide.
# « functionnal » est l'orthographe du ModuleBuilder : functional/ reste.
PRUNE = (
    ("tree", "/ajax"),
    ("tree", "/build/doxygen"),
    ("tree", "/core/modules/mailings"),
    ("tree", "/core/modules/{lower}"),
    ("tree", "/core/tpl"),
    ("tree", "/core/triggers"),
    ("tree", "/doc"),
    ("tree", "/core/boxes"),
    ("file", "/admin/myobject_extrafields.php"),
    ("file", "/class/actions_{lower}.class.php"),
    ("file", "/class/api_{lower}.class.php"),
    ("file", "/css/{lower}.css.php"),
    ("file", "/js/{lower}.js.php"),
    ("file", "/scripts/{lower}.php"),
    ("file", "/sql/data.sql"),
    ("file", "/sql/update_x.x.x-y.y.y.sql"),
    ("file", "/myobject_card.php"),
    ("file", "/myobject_contact.php"),
    ("file", "/myobject_note.php"),
    ("file", "/myobject_document.php"),
    ("file", "/myobject_agenda.php"),
    ("file", "/myobject_list.php"),
    ("file", "/lib/{lower}_myobject.lib.php"),
    ("file", "/test/phpunit/functional/{case}FunctionalTest.php"),
    ("file", "/test/phpunit/MyObjectTest.php"),
    ("file", "/sql/llx_{lower}_myobject.sql"),
    ("file", "/sql/llx_{lower}_myobject_extrafields.sql"),
    ("file", "/sql/llx_{lower}_myobject.key.sql"),
    ("file", "/sql/llx_{lower}_myobject_extrafields.key.sql"),
    ("file", "/class/myobject.class.php"),
    ("file", "/class/myobjectstats.class.php"),
    ("empty", "/class"),
    ("empty", "/css"),
    ("empty", "/js"),
    ("empty", "/scripts"),
    ("empty", "/sql"),
    ("empty", "/test/phpunit/functionnal"),
    ("empty", "/test/phpunit"),
    ("empty", "/test"),
)

# Lancé depuis htdocs : ses entrées, puis le numéro de chaque descripteur,
# du cœur et de custom/.
_INVENTORY = (
    "ls -1A && echo ERPLIBRE_MODULES && "
    "{ grep -H -o -E 'numero[[:space:]]*=[[:space:]]*[0-9]+'"
    " core/modules/mod*.class.php custom/*/core/modules/mod*.class.php"
    " 2>/dev/null; echo ERPLIBRE_END; }"
)
_DESCRIPTOR = re.compile(r"^(.*/(mod\w+)\.class\.php):numero\s*=\s*(\d+)$")

# %s : chemin de master.inc.php, puis nom exact de la classe.
_PHP_HEAD = (
    'require "%s"; require_once DOL_DOCUMENT_ROOT."/core/lib/admin.lib.php";'
)
_PHP_ENABLE = _PHP_HEAD + (
    ' $r = activateModule("%s"); if (!empty($r["errors"])) {'
    ' echo "ERPLIBRE_MODULE_ERRORS ", json_encode($r["errors"]), "\\n";'
    ' exit(1); } echo "ERPLIBRE_MODULE_OK\\n";'
)
_PHP_DISABLE = _PHP_HEAD + (
    ' $e = unActivateModule("%s"); if ($e) {'
    ' echo "ERPLIBRE_MODULE_ERRORS ", json_encode(array($e)), "\\n";'
    ' exit(1); } echo "ERPLIBRE_MODULE_OK\\n";'
)

_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,29}$")
_PICTO = re.compile(r"^[A-Za-z0-9_@.-]{1,64}$")
_URL = re.compile(r"^https?://[^\s'\"\\<>]+$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ModuleError(Exception):
    """Refus avant toute écriture : sortie 2."""


def normalize_name(raw):
    """Le nom tel que le ModuleBuilder le garde : accents ôtés, première
    lettre en capitale, lettres et chiffres seulement."""
    text = unicodedata.normalize("NFKD", raw)
    text = "".join(c for c in text if not unicodedata.combining(c))
    if not re.fullmatch(r"[A-Za-z0-9]+", text):
        raise ValueError(raw)
    return text[0].upper() + text[1:]


def licence(year, name, email):
    """La ligne de copyright du ModuleBuilder : l'année, deux tabulations,
    le nom, puis le courriel aligné sur la colonne 31."""
    info = name
    if email:
        info += "\t" * int(max(0, (31 - len(name)) / 4)) + f"<{email}>"
    return f"{year}\t\t{info}"


def php_quote(text):
    """`text` sûr entre apostrophes PHP."""
    return text.replace("\\", "\\\\").replace("'", "\\'")


def substitutions(case, numero, lic, editor_name, editor_url, version, picto):
    """Les remplacements de « Nouveau module », dans l'ordre où il les
    applique : chaque paire agit sur le résultat des précédentes."""
    lower = case.lower()
    return [
        ("MYMODULE", case.upper()),
        ("MyModule", case),
        ("My module", case),
        ("my module", lower),
        ("Mon module", case),
        ("mon module", lower),
        ("mymodule", lower),
        ("htdocs/modulebuilder/template", lower),
        ("---Put here your own copyright and developer email---", lic),
        ("---Replace with your own copyright and developer email---", lic),
        ("Editor name", php_quote(editor_name)),
        ("https://www.example.com", editor_url),
        ("$this->version = '1.0'", f"$this->version = '{version}'"),
        ("$this->picto = 'generic';", f"$this->picto = '{picto}';"),
        ("modulefamily", "other"),
        ("$this->numero = 500000", f"$this->numero = {numero}"),
    ]


def _copy(src, dest, case):
    """Comme dolCopyDir : liens ignorés, « mymodule » puis « MyModule »
    remplacés dans chaque nom."""
    os.makedirs(dest, exist_ok=True)
    for name in sorted(os.listdir(src)):
        path = os.path.join(src, name)
        if os.path.islink(path):
            continue
        new = name.replace("mymodule", case.lower()).replace("MyModule", case)
        target = os.path.join(dest, new)
        if os.path.isdir(path):
            _copy(path, target, case)
        else:
            shutil.copyfile(path, target)


def _prune(dest, case):
    for kind, pattern in PRUNE:
        path = dest + pattern.format(lower=case.lower(), case=case)
        if kind == "tree":
            shutil.rmtree(path, ignore_errors=True)
            continue
        try:
            (os.remove if kind == "file" else os.rmdir)(path)
        except OSError:
            pass


def _edit(directory, pairs):
    """Remplace dans les fichiers retenus par EDITED, en octets ; une entrée
    cachée, dossier ou fichier, est sautée comme dol_dir_list la saute."""
    encoded = [(a.encode(), b.encode()) for a, b in pairs]
    for name in os.listdir(directory):
        if name.startswith("."):
            continue
        path = os.path.join(directory, name)
        if os.path.isdir(path):
            _edit(path, pairs)
        elif EDITED.search(name):
            with open(path, "rb") as f:
                content = f.read()
            for old, new in encoded:
                content = content.replace(old, new)
            with open(path, "wb") as f:
                f.write(content)


def generate(template, dest, case, pairs):
    _copy(template, dest, case)
    _prune(dest, case)
    _edit(dest, pairs)


def free_id(used, start=FIRST_FREE):
    numero = start
    while numero in used:
        numero += 1
    return numero


class Inventory:
    """Les entrées de htdocs (en minuscules) et les descripteurs de modules,
    par nom de classe en minuscules : (classe, chemin, numéro)."""

    def __init__(self, entries, modules):
        self.entries, self.modules = entries, modules

    def holder(self, numero):
        for cls, _path, n in self.modules.values():
            if n == numero:
                return cls
        return None

    def taken(self, case):
        """Pourquoi `case` ne peut pas servir, ou None."""
        lower = case.lower()
        if f"mod{lower}" in self.modules:
            return t("module %s exists: %s") % (
                self.modules[f"mod{lower}"][0],
                self.modules[f"mod{lower}"][1],
            )
        if lower in self.entries:
            return t("htdocs/%s exists") % lower
        return None


def parse_inventory(out):
    if "ERPLIBRE_MODULES\n" not in out or "ERPLIBRE_END" not in out:
        return None
    head, _sep, rest = out.partition("ERPLIBRE_MODULES\n")
    entries = {x.strip().lower() for x in head.splitlines() if x.strip()}
    modules = {}
    for line in rest.partition("ERPLIBRE_END")[0].splitlines():
        m = _DESCRIPTOR.match(line.strip())
        if m and m.group(2).lower() not in modules:
            modules[m.group(2).lower()] = (
                m.group(2),
                m.group(1),
                int(m.group(3)),
            )
    return Inventory(entries, modules)


class Place:
    """Où vit le code d'une instance, vu de cette machine."""

    def __init__(self, entry, system):
        self.entry, self.system = entry, system
        self.container = entry.get("runtime") == "container"
        if self.container:
            from script.todo import container_runtime

            fiche = system.engine(entry["engine"])
            self.cmd = lambda args: container_runtime.commande(fiche, args)
            self.web = entry["containers"][1]
            self.custom = entry["custom_dir"]
        else:
            self.htdocs = os.path.join(entry["code_root"], "htdocs")
            self.custom = os.path.join(self.htdocs, "custom")

    def inventory(self):
        if self.container:
            argv = self.cmd(
                [
                    "exec",
                    self.web,
                    "sh",
                    "-c",
                    f"cd /var/www/html && {_INVENTORY}",
                ]
            )
        else:
            argv = [
                "sh",
                "-c",
                f"cd {shlex.quote(self.htdocs)} && {_INVENTORY}",
            ]
        _code, out = self.system.run(argv)
        return parse_inventory(out)

    def template(self, work):
        """Le gabarit de l'instance : en place en natif ; hors d'un conteneur,
        en tar extrait par ce compte, jamais par root."""
        if not self.container:
            return os.path.join(self.htdocs, "modulebuilder", "template")
        archive = os.path.join(work, "template.tar")
        code, out = self.system.run_to_file(
            self.cmd(
                ["cp", f"{self.web}:/var/www/html/modulebuilder/template", "-"]
            ),
            archive,
        )
        if code:
            raise OSError(out.strip()[-300:])
        with tarfile.open(archive) as tar:
            restore._extract(tar, work)
        return os.path.join(work, "template")


def _unreachable(name):
    return (
        t(
            "The code of %s cannot be read; a container instance must be"
            " running (run.py start)."
        )
        % name
    )


def _author(args, system):
    """(nom, courriel) : --author « Nom <courriel> », sinon git config."""
    if args.author is not None:
        m = re.fullmatch(r"\s*(.*?)\s*(?:<([^<>]*)>)?\s*", args.author)
        return m.group(1), m.group(2) or ""
    found = []
    for key in ("user.name", "user.email"):
        code, out = system.run(["git", "config", "--get", key])
        found.append(out.strip() if code == 0 else "")
    return found[0], found[1]


def _check_text(args, name, email):
    if not _VERSION.match(args.version):
        raise ModuleError(t("Invalid version: %s") % args.version)
    if not _PICTO.match(args.picto):
        raise ModuleError(t("Invalid picto: %s") % args.picto)
    if args.editor_url and not _URL.match(args.editor_url):
        raise ModuleError(t("Invalid editor URL: %s") % args.editor_url)
    for value in (name, email, args.editor_name or ""):
        # La ligne d'auteur va dans des commentaires /* */ et -- .
        if "*/" in value or _CONTROL.search(value):
            raise ModuleError(t("Invalid author or editor: %s") % value)


def create(name, entry, args, system):
    try:
        case = normalize_name(args.name)
    except ValueError:
        raise ModuleError(
            t("Invalid module name %r: letters and digits only.") % args.name
        )
    author, email = _author(args, system)
    _check_text(args, author, email)
    place = Place(entry, system)
    inventory = place.inventory()
    if inventory is None:
        print(_unreachable(name))
        return 1
    reason = inventory.taken(case)
    dest = os.path.join(place.custom, case.lower())
    if reason is None and os.path.lexists(dest):
        reason = t("%s exists") % dest
    if reason:
        raise ModuleError(t("Name %s is taken: %s") % (case, reason))
    used = {n for _c, _p, n in inventory.modules.values()}
    if args.id is None:
        numero = free_id(used)
    else:
        numero = args.id
        if numero < LOWEST:
            raise ModuleError(t("A module ID starts at %d.") % LOWEST)
        if numero in used:
            raise ModuleError(
                t("ID %d is used by %s.") % (numero, inventory.holder(numero))
            )
    lic = licence(datetime.date.today().year, author, email)
    editor = author if args.editor_name is None else args.editor_name
    pairs = substitutions(
        case, numero, lic, editor, args.editor_url, args.version, args.picto
    )
    with tempfile.TemporaryDirectory() as work:
        try:
            template = place.template(work)
        except (OSError, tarfile.TarError) as e:
            print(_unreachable(name))
            print(str(e))
            return 1
        try:
            generate(template, dest, case, pairs)
        except OSError as e:
            # Un module à moitié écrit ferait refuser le nom à la relance.
            shutil.rmtree(dest, ignore_errors=True)
            print(t("Module not created: %s") % e)
            return 1
    print(t("Module %s created: %s (ID %d).") % (case, dest, numero))
    if numero < FIRST_FREE:
        print(
            t(
                "IDs below 500000 are reserved one by one on the Dolibarr"
                " wiki (List_of_modules_id): keep this one only if it is"
                " reserved for this module."
            )
        )
    if args.enable:
        return switch(name, entry, case, True, system)
    return 0


def link(name, entry, args, system):
    place = Place(entry, system)
    if place.container:
        raise ModuleError(
            t(
                "A container only sees its custom/: create or copy the module into %s."
            )
            % place.custom
        )
    source = os.path.abspath(os.path.expanduser(args.path))
    descriptors = sorted(
        f[: -len(".class.php")]
        for f in _listdir(os.path.join(source, "core", "modules"))
        if re.fullmatch(r"mod\w+\.class\.php", f)
    )
    if not descriptors:
        raise ModuleError(
            t("No module descriptor in %s/core/modules.") % source
        )
    cls = descriptors[0]
    dest = os.path.join(place.custom, cls[3:].lower())
    if os.path.islink(dest) and os.readlink(dest) == source:
        print(t("%s already links to %s.") % (dest, source))
        return 0
    inventory = place.inventory()
    if inventory is None:
        print(_unreachable(name))
        return 1
    reason = inventory.taken(cls[3:])
    if reason is None and os.path.lexists(dest):
        reason = t("%s exists") % dest
    if reason:
        raise ModuleError(t("Name %s is taken: %s") % (cls[3:], reason))
    os.symlink(source, dest)
    print(t("%s links to %s.") % (dest, source))
    return 0


def _listdir(path):
    try:
        return os.listdir(path)
    except OSError:
        return []


def switch(name, entry, module_name, on, system):
    """activateModule ou unActivateModule sur la classe exacte, trouvée
    sans égard à la casse parmi les descripteurs de l'instance."""
    inventory = Place(entry, system).inventory()
    if inventory is None:
        print(_unreachable(name))
        return 1
    found = inventory.modules.get("mod" + module_name.lower())
    if found is None:
        raise ModuleError(t("No module %s on %s.") % (module_name, name))
    target = debug.Target(entry, system)
    code, out = target.php(
        (_PHP_ENABLE if on else _PHP_DISABLE) % (target.master, found[0])
    )
    if code or "ERPLIBRE_MODULE_OK" not in out:
        print(t("Dolibarr refused: %s") % found[0])
        m = re.search(r"^ERPLIBRE_MODULE_ERRORS (.*)$", out, re.M)
        print("; ".join(json.loads(m.group(1))) if m else out.strip()[-1000:])
        return 1
    print(
        (t("%s enabled on %s.") if on else t("%s disabled on %s."))
        % (found[0], name)
    )
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("create")
    p.add_argument("--instance", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--id", type=int)
    p.add_argument("--author")
    p.add_argument("--editor-name")
    p.add_argument("--editor-url", default="")
    p.add_argument("--version", default="1.0")
    p.add_argument("--picto", default="fa-file")
    p.add_argument("--enable", action="store_true")
    p = sub.add_parser("link")
    p.add_argument("--instance", required=True)
    p.add_argument("--path", required=True)
    for action in ("enable", "disable"):
        p = sub.add_parser(action)
        p.add_argument("--instance", required=True)
        p.add_argument("--name", required=True)
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
        if args.action == "create":
            return create(args.instance, entry, args, system)
        if args.action == "link":
            return link(args.instance, entry, args, system)
        return switch(
            args.instance, entry, args.name, args.action == "enable", system
        )
    except ModuleError as e:
        print(e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
