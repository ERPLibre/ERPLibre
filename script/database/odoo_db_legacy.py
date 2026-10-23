#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Traduire la nouvelle syntaxe « db », « module », « theme » vers les
anciens drapeaux des forks Odoo qui n'ont pas les commandes du module
erplibre_odoo_cli_base.

./odoo_bin.sh passe la main à ce script pour ces trois commandes quand le
cœur d'Odoo actif garde l'ancienne commande « db » à drapeaux (son
odoo/cli/db.py n'a pas le _check_target d'OCB) et l'option serveur
--uninstall ; le module, s'il est là, n'y enregistre alors rien. Les
appelants n'écrivent ainsi qu'une syntaxe, celle d'Odoo 18 :

    db list | list-incompatible | version
    db create [-f] [--demo] [--lang L] [--login U] [--password P]
              [--phone N] [--country C] BASE
    db drop [--if-exists] BASE
    db load [-f] [-n] [--move] [BASE] (FICHIER | --image IMAGE)
    db dump BASE (CHEMIN | --image IMAGE)
    db duplicate [-f] [-n] SOURCE CIBLE
    module uninstall [-c FICHIER] -d BASE a,b
    theme apply [-c FICHIER] -d BASE THEME

Chaque commande devient une liste d'étapes exécutées dans l'ordre ; la
première qui échoue arrête la suite et donne son code de sortie. Une
syntaxe que l'ancien fork ne sait pas rendre sort en 2, avec la raison.

Les enfants « ./odoo_bin.sh » reçoivent ERPLIBRE_ODOO_CLI_LEGACY=1, qui
les fait passer tout droit jusqu'à l'ancienne commande au lieu de revenir
ici.

Bibliothèque standard seulement, et syntaxe Python 3.7 : le script tourne
dans le venv de la version d'Odoo active, 3.7 pour Odoo 12 et 13.
"""

import argparse
import collections
import os
import subprocess
import sys
import urllib.parse

VARIABLE_LEGACY = "ERPLIBRE_ODOO_CLI_LEGACY"

# kind : « odoo_bin » (./odoo_bin.sh ARGS), « run_sh » (./run.sh ARGS) ou
# « require_db » (ARGS = [BASE], qui doit figurer dans « db --list »).
# env : variables ajoutées à l'environnement hérité pour cette étape.
# stdin : texte donné sur l'entrée standard d'une étape « odoo_bin », ou
# None pour hériter de celle du traducteur.
Step = collections.namedtuple(
    "Step", ["kind", "args", "env", "stdin"], defaults=(None,)
)

# Ce que l'ancienne commande ne sait pas faire, quelle que soit la version.
ANCIENNE_COMMANDE = "the old db command (no erplibre_odoo_cli_base)"

VARIABLE_THEME = "ERPLIBRE_THEME_APPLY"

# « theme apply » passe par « odoo_bin.sh shell » et non par l'ancien
# --install-theme : celui-ci appelle button_choose_theme pendant le
# chargement du registre, où l'installation immédiate des thèmes amont est
# refusée (« cannot be called on init or non loaded registries »), et sans
# site web installé le bouton n'existe pas. Dans le shell, le registre est
# chargé : le thème s'installe s'il le faut (website avec lui), puis
# reçoit ce que fait le bouton « Choisir ce thème » du site courant, sans
# l'action de redirection, qui exige une requête HTTP. Le nom du thème
# arrive par VARIABLE_THEME ; SystemExit sort en 1 avec son message.
SCRIPT_THEME = (
    """\
import os
import sys

import odoo

nom = os.environ["%s"]


def est_theme(e, module):
    if "website" not in e:
        return False
    Module = e["ir.module.module"]
    # get_themes_domain n'existe qu'à partir de 15 ; avant, un thème est un
    # module de la catégorie Theme ou d'une de ses sous-catégories.
    if hasattr(Module, "get_themes_domain"):
        domaine = Module.get_themes_domain()
    else:
        categorie = e.ref("base.module_category_theme").id
        domaine = [("category_id", "child_of", categorie)]
    domaine = domaine + [("id", "=", module.id)]
    return bool(Module.search_count(domaine))


theme = env["ir.module.module"].search([("name", "=", nom)], limit=1)
if not theme:
    raise SystemExit("No module named %%s." %% nom)
if "website" in env and not est_theme(env, theme):
    raise SystemExit("%%s is not a website theme." %% nom)
installe = False
if theme.state != "installed":
    theme.button_immediate_install()
    installe = True
# L'installation a remplacé le registre : un nouvel environnement le voit.
env = odoo.api.Environment(env.cr, odoo.SUPERUSER_ID, {})
theme = env["ir.module.module"].browse(theme.id)
if not est_theme(env, theme):
    suite = " It stays installed." if installe else ""
    raise SystemExit("%%s is not a website theme.%%s" %% (nom, suite))
site = env["website"].get_current_website()
theme._theme_remove(site)
site.theme_id = theme
theme._theme_upgrade_upstream()
env.cr.commit()
print("Theme %%s applied to website %%s." %% (nom, site.id), file=sys.stderr)
"""
    % VARIABLE_THEME
)

# Les options globales du « db » d'Odoo 18, écrites avant la
# sous-commande. Seule -c a un équivalent dans l'ancienne commande :
# ODOO_RC.
OPTIONS_GLOBALES = (
    ("-D", "--data-dir"),
    ("--addons-path",),
    ("-r", "--db_user"),
    ("-w", "--db_password"),
    ("--pg_path",),
    ("--db_host",),
    ("--db_port",),
    ("--db_sslmode",),
)


class LegacyUsageError(Exception):
    """Une syntaxe valide que l'ancien fork ne sait pas exécuter."""


class Parseur(argparse.ArgumentParser):
    """Un argparse qui lève LegacyUsageError au lieu de quitter.

    translate() reste ainsi une fonction : seul main() décide du code de
    sortie. -h/--help, lui, imprime l'aide et quitte en 0 comme partout.
    """

    def error(self, message):
        raise LegacyUsageError("%s: %s" % (self.prog, message))


def majeure(version):
    """« 14.0 » → 14 ; 0 pour une version illisible."""
    tete = str(version).strip().split(".")[0]
    return int(tete) if tete.isdigit() else 0


def resoudre_image(valeur):
    """Le zip désigné par --image, comme le fait le module d'Odoo 18.

    « .zip » s'ajoute s'il manque. Une valeur qui contient « / » est un
    chemin, gardé tel quel ; un nom nu vit dans ./image_db/.
    """
    if not valeur.endswith(".zip"):
        valeur += ".zip"
    if "/" in valeur:
        return valeur
    return os.path.join(".", "image_db", valeur)


def nom_image(valeur):
    """Le nom de base par défaut d'un --image : le nom du zip, sans .zip."""
    nom = os.path.basename(valeur)
    return nom[: -len(".zip")] if nom.endswith(".zip") else nom


def drapeaux_image(valeur):
    """--restore_image NOM pour un nom nu, --restore_db_file pour un chemin.

    L'ancien --restore_image joint sa valeur à ./image_db/ : un chemin
    relatif y serait cherché au mauvais endroit.
    """
    if "/" in valeur:
        return ["--restore_db_file", resoudre_image(valeur)]
    return ["--restore_image", valeur]


def _ajouter_globales(parseur):
    parseur.add_argument("-c", "--config", dest="config", metavar="FICHIER")
    for noms in OPTIONS_GLOBALES:
        dest = noms[-1].lstrip("-").replace("-", "_")
        parseur.add_argument(
            *noms, dest="g_" + dest, metavar="VALEUR", help=argparse.SUPPRESS
        )


def _globales_donnees(args):
    """[(option, valeur)] des options globales écrites, dans l'ordre fixe."""
    donnees = []
    for noms in OPTIONS_GLOBALES:
        dest = "g_" + noms[-1].lstrip("-").replace("-", "_")
        valeur = getattr(args, dest, None)
        if valeur is not None:
            donnees.append((noms[-1], valeur))
    return donnees


def _parseur_db():
    parseur = Parseur(
        prog="odoo_bin.sh db",
        allow_abbrev=False,
        description="Nouvelle syntaxe « db », traduite pour l'ancienne"
        " commande des forks sans erplibre_odoo_cli_base.",
    )
    _ajouter_globales(parseur)
    subs = parseur.add_subparsers(dest="sub", metavar="SOUS_COMMANDE")

    def sous(nom, aide=None):
        return subs.add_parser(nom, allow_abbrev=False, help=aide)

    sous("list", "db --list")
    sous("list-incompatible", "db --list_incompatible_db")
    sous("version", "db --version")

    create = sous("create", "db --create")
    create.add_argument("-f", "--force", action="store_true")
    create.add_argument("--demo", action="store_true")
    for option in ("--lang", "--login", "--password", "--phone", "--country"):
        create.add_argument(option)
    create.add_argument("database")

    drop = sous("drop", "db --drop")
    drop.add_argument("--if-exists", dest="if_exists", action="store_true")
    drop.add_argument("database")

    load = sous("load", "db --restore")
    load.add_argument("-f", "--force", action="store_true")
    load.add_argument("-n", "--neutralize", action="store_true")
    load.add_argument("--move", action="store_true")
    load.add_argument("--image")
    load.add_argument("positionnels", nargs="*")

    dump = sous("dump", "db --backup")
    dump.add_argument("--image")
    dump.add_argument("database")
    dump.add_argument("dump_path", nargs="?")

    duplicate = sous("duplicate", "db --clone")
    duplicate.add_argument("-f", "--force", action="store_true")
    duplicate.add_argument("-n", "--neutralize", action="store_true")
    duplicate.add_argument("source")
    duplicate.add_argument("target")

    rename = sous("rename", "absent de l'ancienne commande")
    rename.add_argument("-f", "--force", action="store_true")
    rename.add_argument("source")
    rename.add_argument("target")
    return parseur


def _parseur_action(commande, action, argument):
    """« module uninstall » et « theme apply » : -c et les globales après
    l'action, à côté de -d, comme dans le module d'Odoo 18."""
    parseur = Parseur(prog="odoo_bin.sh %s" % commande, allow_abbrev=False)
    subs = parseur.add_subparsers(dest="sub", metavar="ACTION")
    sous = subs.add_parser(action, allow_abbrev=False)
    _ajouter_globales(sous)
    sous.add_argument("-d", "--database", required=True)
    sous.add_argument(argument)
    return parseur


def _env_odoo_bin(config):
    env = {VARIABLE_LEGACY: "1"}
    if config:
        env["ODOO_RC"] = config
    return env


def _sans_sous_commande(parseur):
    parseur.print_help(sys.stderr)
    raise SystemExit(1)


class _Contexte:
    """Ce que chaque traduction de « db » partage : l'environnement des
    étapes et la version d'Odoo."""

    def __init__(self, config, version):
        self.env = _env_odoo_bin(config)
        self.v16 = majeure(version) >= 16

    def odoo(self, *argv):
        return Step("odoo_bin", ["db"] + list(argv), self.env)

    def dropper(self, base):
        return self.odoo("--drop", "--database", base)

    def exiger_16_pour_neutralize(self, args):
        if args.neutralize and not self.v16:
            raise LegacyUsageError("--neutralize needs Odoo 16")


def _db_create(args, ctx):
    etapes = [ctx.dropper(args.database)] if args.force else []
    argv = ["--create", "--database", args.database]
    if args.demo:
        argv.append("--demo")
    # Seules les options écrites passent : les défauts de l'ancienne
    # commande sont déjà ceux de la nouvelle.
    for nom, drapeau in (
        ("lang", "--user_lang"),
        ("login", "--user_login"),
        ("password", "--user_password"),
        ("phone", "--user_phone"),
        ("country", "--user_country_code"),
    ):
        valeur = getattr(args, nom)
        if valeur is not None:
            argv += [drapeau, valeur]
    return etapes + [ctx.odoo(*argv)]


def _db_drop(args, ctx):
    # L'ancien --drop se tait sur une base absente : sans --if-exists, la
    # nouvelle syntaxe en fait une erreur, vérifiée d'abord.
    if args.if_exists:
        etapes = []
    else:
        etapes = [Step("require_db", [args.database], ctx.env)]
    return etapes + [ctx.dropper(args.database)]


def _source_load(args):
    """(base, drapeaux de la source) d'un « db load »."""
    positionnels = args.positionnels
    if args.image is not None:
        if not args.image:
            raise LegacyUsageError("db load: --image needs a value")
        if len(positionnels) > 1:
            raise LegacyUsageError("db load: --image takes at most a database")
        base = positionnels[0] if positionnels else nom_image(args.image)
        return base, drapeaux_image(args.image)
    if len(positionnels) not in (1, 2):
        raise LegacyUsageError(
            "db load: expected [database] dump_file or --image NAME"
        )
    fichier = positionnels[-1]
    if urllib.parse.urlparse(fichier).scheme:
        raise LegacyUsageError(
            "db load from a URL is not supported by %s" % ANCIENNE_COMMANDE
        )
    if len(positionnels) == 2:
        base = positionnels[0]
    else:
        base = os.path.splitext(os.path.basename(fichier))[0]
    return base, ["--restore_db_file", fichier]


def _db_load(args, ctx):
    base, source = _source_load(args)
    ctx.exiger_16_pour_neutralize(args)
    etapes = [ctx.dropper(base)] if args.force else []
    argv = ["--restore", "--database", base] + source
    if args.neutralize:
        argv.append("--neutralize")
    # Avant 16, --restore restaure toujours en base déplacée (l'UUID est
    # gardé) : --move n'y change rien. Dès 16, il faut le demander.
    if args.move and ctx.v16:
        argv.append("--move_database")
    return etapes + [ctx.odoo(*argv)]


def _db_dump(args, ctx):
    if args.image is not None and args.dump_path is not None:
        raise LegacyUsageError("db dump: give a path or --image, not both")
    if args.image is not None:
        if not args.image:
            raise LegacyUsageError("db dump: --image needs a value")
        source = drapeaux_image(args.image)
    elif args.dump_path in (None, "-"):
        raise LegacyUsageError(
            "db dump to stdout is not supported by %s" % ANCIENNE_COMMANDE
        )
    else:
        source = ["--restore_db_file", args.dump_path]
    return [ctx.odoo("--backup", "--database", args.database, *source)]


def _db_duplicate(args, ctx):
    ctx.exiger_16_pour_neutralize(args)
    etapes = [ctx.dropper(args.target)] if args.force else []
    argv = ["--clone", "--from_database", args.source]
    argv += ["--database", args.target]
    if args.neutralize:
        argv.append("--neutralize")
    return etapes + [ctx.odoo(*argv)]


def _db_rename(args, ctx):
    raise LegacyUsageError(
        "db rename is not supported by %s" % ANCIENNE_COMMANDE
    )


TRADUCTIONS_DB = {
    "list": lambda args, ctx: [ctx.odoo("--list")],
    "list-incompatible": lambda args, ctx: [
        ctx.odoo("--list_incompatible_db")
    ],
    "version": lambda args, ctx: [ctx.odoo("--version")],
    "create": _db_create,
    "drop": _db_drop,
    "load": _db_load,
    "dump": _db_dump,
    "duplicate": _db_duplicate,
    "rename": _db_rename,
}


def _traduire_db(cmdargs, version):
    parseur = _parseur_db()
    args = parseur.parse_args(cmdargs)
    if args.sub is None:
        _sans_sous_commande(parseur)
    globales = _globales_donnees(args)
    if globales:
        raise LegacyUsageError(
            "option %s is not supported by %s"
            % (globales[0][0], ANCIENNE_COMMANDE)
        )
    return TRADUCTIONS_DB[args.sub](args, _Contexte(args.config, version))


def _lire_action(commande, action, argument, cmdargs):
    parseur = _parseur_action(commande, action, argument)
    args = parseur.parse_args(cmdargs)
    if args.sub is None:
        _sans_sous_commande(parseur)
    return args


def _options_serveur(args):
    """-c et les globales, rendues en options serveur après les autres."""
    argv = ["-c", args.config] if args.config else []
    for drapeau, valeur in _globales_donnees(args):
        argv += [drapeau, valeur]
    return argv


def _module_uninstall(cmdargs):
    args = _lire_action("module", "uninstall", "modules", cmdargs)
    argv = ["--no-http", "--stop-after-init", "-d", args.database]
    argv += ["--uninstall", args.modules] + _options_serveur(args)
    return [Step("run_sh", argv, {VARIABLE_LEGACY: "1"})]


def _theme_apply(cmdargs):
    args = _lire_action("theme", "apply", "theme", cmdargs)
    argv = ["shell", "--no-http", "-d", args.database]
    argv += _options_serveur(args)
    env = {VARIABLE_LEGACY: "1", VARIABLE_THEME: args.theme}
    return [Step("odoo_bin", argv, env, SCRIPT_THEME)]


def translate(argv, version):
    """argv de ./odoo_bin.sh (« db … », « module … », « theme … ») →
    [Step], dans l'ordre d'exécution. Lève LegacyUsageError."""
    if not argv:
        raise LegacyUsageError("expected db, module or theme")
    commande, cmdargs = argv[0], list(argv[1:])
    if commande == "db":
        return _traduire_db(cmdargs, version)
    if commande == "module":
        return _module_uninstall(cmdargs)
    if commande == "theme":
        return _theme_apply(cmdargs)
    raise LegacyUsageError("unknown command %s" % commande)


def _executer(etape):
    env = dict(os.environ)
    env.update(etape.env)
    if etape.kind == "odoo_bin" and etape.stdin is not None:
        return subprocess.run(
            ["./odoo_bin.sh"] + etape.args,
            input=etape.stdin,
            universal_newlines=True,
            env=env,
        ).returncode
    if etape.kind == "odoo_bin":
        return subprocess.call(["./odoo_bin.sh"] + etape.args, env=env)
    if etape.kind == "run_sh":
        return subprocess.call(["./run.sh"] + etape.args, env=env)
    # require_db : la liste sur stdout, une base par ligne ; les journaux
    # de stderr n'y entrent pas.
    base = etape.args[0]
    fait = subprocess.run(
        ["./odoo_bin.sh", "db", "--list"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        universal_newlines=True,
        env=env,
    )
    if fait.returncode:
        return fait.returncode
    if base in fait.stdout.splitlines():
        return 0
    print("Database %s does not exist." % base, file=sys.stderr)
    return 1


def lire_version(chemin=".odoo-version"):
    with open(chemin) as fichier:
        return fichier.read().strip()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        etapes = translate(argv, lire_version())
    except LegacyUsageError as erreur:
        print(erreur, file=sys.stderr)
        return 2
    for etape in etapes:
        code = _executer(etape)
        if code:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
