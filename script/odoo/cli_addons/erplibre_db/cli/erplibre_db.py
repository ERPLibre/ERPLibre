# -*- coding: utf-8 -*-
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""odoo-bin erplibre_db : la commande « db » d'ERPLibre, pour un Odoo amont.

Les options sont celles de la commande « db » du fork ERPLibre d'Odoo, que
script/database/db_restore.py et la migration appellent par
« ./odoo_bin.sh db ». odoo_bin.sh réécrit cet appel vers cette commande
quand l'Odoo actif n'a pas la sienne.

Le nom n'est pas « db » : Odoo 19 et 20 livrent une commande « db »
d'une autre interface, et une commande intégrée l'emporte sur celle d'un
addon.

Le code tourne de Python 2.7 à 3.14 : ni f-string, ni argument nommé seul.
Deux API servent la gestion des bases :
  odoo.service.db    Odoo 10 à 19, fonctions exp_* et *_db ;
  odoo.modules.db    Odoo 20, arguments nommés obligatoires.
Un paramètre qu'une version ne connaît pas — neutralize_database et phone
en Odoo 10 et 11 — est retiré de l'appel plutôt que d'y échouer.
"""
from __future__ import print_function

import inspect
import optparse
import os
import sys

import odoo
import odoo.api
from odoo.cli import Command
from odoo.tools import config

try:
    from odoo.service import db as _db_legacy
except ImportError:
    _db_legacy = None
if _db_legacy is None or not hasattr(_db_legacy, "exp_duplicate_database"):
    _db_legacy = None
    from odoo.modules import db as _db_moderne


def _parametres(fonction):
    """Noms des paramètres qu'accepte la fonction."""
    try:
        return set(inspect.signature(fonction).parameters)
    except AttributeError:  # Python 2
        return set(inspect.getargspec(fonction).args)


def _appeler(fonction, *args, **kwargs):
    """Appelle la fonction avec les seuls arguments nommés qu'elle connaît.

    Un argument écarté à la valeur non nulle est signalé : l'appelant a
    demandé une chose que cette version d'Odoo ne sait pas faire.
    """
    connus = _parametres(fonction)
    for nom in [n for n in kwargs if n not in connus]:
        if kwargs[nom]:
            print(
                "Option ignoree, absente de cette version d'Odoo : %s" % nom,
                file=sys.stderr,
            )
        del kwargs[nom]
    return fonction(*args, **kwargs)


def _mot_de_passe_maitre(opt):
    """L'environnement l'emporte : un argument se lit dans ps."""
    return os.environ.get("MASTER_PWD") or opt.master_password or "admin"


def _verifier_mot_de_passe_maitre(mot):
    if _db_legacy is not None:
        _db_legacy.check_super(mot)
    else:
        _db_moderne.verify_admin_password(mot)


def lister():
    if _db_legacy is not None:
        return _db_legacy.list_dbs(True)
    return _db_moderne.list_dbs(force=True)


def lister_incompatibles(bases):
    fonction = getattr(_db_legacy, "list_db_incompatible", None)
    if fonction is None:
        try:
            from odoo.addons.web.controllers.database import (
                list_db_incompatible as fonction,
            )
        except ImportError:
            return []
    return fonction(bases)


def creer(opt):
    kwargs = dict(
        user_password=opt.user_password,
        login=opt.user_login,
        country_code=opt.user_country_code,
        phone=opt.user_phone,
    )
    if _db_legacy is not None:
        return _appeler(
            _db_legacy.exp_create_database,
            opt.db_name,
            opt.demo,
            opt.user_lang,
            **kwargs
        )
    kwargs["user_login"] = kwargs.pop("login")
    return _appeler(
        _db_moderne.create,
        opt.db_name,
        demo=opt.demo,
        lang=opt.user_lang,
        **kwargs
    )


def cloner(source, cible, neutraliser):
    if _db_legacy is not None:
        return _appeler(
            _db_legacy.exp_duplicate_database,
            source,
            cible,
            neutralize_database=neutraliser,
        )
    return _appeler(
        _db_moderne.duplicate, source, cible, neutralize_database=neutraliser
    )


def supprimer(nom):
    if _db_legacy is not None:
        return _db_legacy.exp_drop(nom)
    return _db_moderne.drop(nom)


def sauvegarder(nom, flux):
    if _db_legacy is not None:
        return _db_legacy.dump_db(nom, flux, backup_format="zip")
    return _db_moderne.dump(nom, flux, backup_format="zip")


def restaurer(nom, chemin, copie, neutraliser):
    if _db_legacy is not None:
        return _appeler(
            _db_legacy.restore_db,
            nom,
            chemin,
            copy=copie,
            neutralize_database=neutraliser,
        )
    return _appeler(
        _db_moderne.restore,
        nom,
        chemin,
        copy=copie,
        neutralize_database=neutraliser,
    )


def version():
    if _db_legacy is not None:
        return _db_legacy.exp_server_version()
    return odoo.release.version


def chemin_image(opt):
    """--restore_image désigne ./image_db/<nom>.zip, --restore_db_file un
    chemin tel quel."""
    if opt.restore_image:
        nom = opt.restore_image
        if not nom.endswith(".zip"):
            nom += ".zip"
        return os.path.join(".", "image_db", nom)
    return opt.restore_db_file


def _exec_pg_command(name, *args):
    """exec_pg_command d'Odoo 10 et 11, à /dev/null près : ils l'ouvrent en
    LECTURE seule pour la sortie de pg_dump, pg_restore et psql, et un client
    PostgreSQL 18 refuse alors d'écrire — « n'a pas pu ouvrir stdout pour
    l'ajout » —, ce qui fait échouer toute sauvegarde et toute restauration."""
    import subprocess

    from odoo.tools import misc

    programme = misc.find_pg_tool(name)
    env = misc.exec_pg_environ()
    with open(os.devnull, "w") as vide:
        code = subprocess.call(
            (programme,) + args, env=env, stdout=vide, stderr=subprocess.STDOUT
        )
    if code:
        raise Exception(
            "Postgres subprocess %s error %s" % ((programme,) + args, code)
        )


def corriger_exec_pg_command():
    """Remplace, dans ce processus seulement, l'exec_pg_command qui ouvre
    /dev/null en lecture. Les versions qui ne l'ouvrent pas ainsi gardent la
    leur."""
    import odoo.tools
    from odoo.tools import misc

    source = getattr(misc, "exec_pg_command", None)
    if source is None:
        return
    try:
        texte = inspect.getsource(source)
    except (IOError, OSError, TypeError):
        return
    if "open(os.devnull)" not in texte:
        return
    misc.exec_pg_command = _exec_pg_command
    if getattr(odoo.tools, "exec_pg_command", None) is source:
        odoo.tools.exec_pg_command = _exec_pg_command


class _SansContexte(object):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def contexte_orm():
    """Odoo 10 et 11 n'exécutent l'ORM que dans Environment.manage(), que
    leur serveur et leur shell ouvrent ; la création d'une base y échoue sur
    « AttributeError: environments » sans lui. Odoo 19 et 20 n'en ont plus."""
    environnement = getattr(odoo.api, "Environment", None)
    gerer = getattr(environnement, "manage", None)
    return gerer() if gerer is not None else _SansContexte()


def mourir(condition, message, code=1):
    if condition:
        print(message, file=sys.stderr)
        sys.exit(code)


class Erplibre_db(Command):
    """Gestion des bases d'ERPLibre (liste, création, clone, restauration)"""

    # Odoo 19 et 20 prennent ce nom, et exigent qu'il soit celui du fichier ;
    # Odoo 10 et 11 le déduisent du nom de la classe mis en minuscules — d'où
    # ce nom de classe.
    name = "erplibre_db"

    def run(self, cmdargs):
        parser = optparse.OptionParser(
            prog="%s erplibre_db" % sys.argv[0].split(os.path.sep)[-1],
            description=self.__doc__,
        )
        parser.add_option("-d", "--database", dest="db_name", default=None)
        parser.add_option("--from_database", dest="db_name_from", default=None)
        parser.add_option("--restore_db_file")
        parser.add_option("--restore_image")
        parser.add_option("--master_password")
        parser.add_option("--demo", action="store_true")
        parser.add_option("--user_lang", default="fr_CA")
        parser.add_option("--user_password", default="admin")
        parser.add_option("--user_login", default="admin")
        parser.add_option("--user_phone")
        parser.add_option("--user_country_code", default="ca")
        parser.add_option("--backup", action="store_true")
        parser.add_option("--drop", action="store_true")
        parser.add_option("--neutralize", action="store_true")
        parser.add_option("--move_database", action="store_true")
        parser.add_option("--create", action="store_true")
        parser.add_option("--clone", action="store_true")
        parser.add_option("--restore", action="store_true")
        parser.add_option("--list", action="store_true")
        parser.add_option("--list_incompatible_db", action="store_true")
        parser.add_option("--version", action="store_true")
        opt, _args = parser.parse_args(cmdargs)

        commandes = [
            opt.drop,
            opt.restore,
            opt.list,
            opt.version,
            opt.list_incompatible_db,
            opt.create,
        ]
        mourir(
            sum(bool(c) for c in commandes) > 1,
            "Can only run one command, --create, --drop, --list, --version,"
            " --list_incompatible_db or --restore.",
        )
        mourir(
            bool(opt.restore_db_file) and bool(opt.restore_image),
            "Cannot support both argument --restore_db_file and"
            " --restore_image",
        )
        for actif, exige, message in (
            (opt.restore, chemin_image(opt), "--restore_db_file or --restore_image"),
            (opt.backup, chemin_image(opt), "--restore_db_file or --restore_image"),
            (opt.restore or opt.backup or opt.create, opt.db_name, "--database"),
            (opt.clone or opt.drop, opt.db_name, "--database"),
            (opt.clone, opt.db_name_from, "--from_database"),
        ):
            mourir(actif and not exige, "Missing argument %s." % message)

        # La base, l'hôte et le mot de passe maître viennent du fichier que
        # désigne ODOO_RC, posé par odoo_bin.sh.
        # Odoo 20 demande si la journalisation est à lui ; avant, il la
        # prenait sans qu'on le dise.
        if "setup_logging" in _parametres(config.parse_config):
            config.parse_config([], setup_logging=True)
        else:
            config.parse_config([])
        # Odoo 10 ne transmet pas db_password à pg_dump ni à pg_restore, qui
        # héritent de l'environnement : sans PGPASSWORD, la sauvegarde et la
        # restauration échouent sur un serveur qui exige un mot de passe.
        if config.get("db_password") and not os.environ.get("PGPASSWORD"):
            os.environ["PGPASSWORD"] = config["db_password"]
        corriger_exec_pg_command()
        with contexte_orm():
            self.executer(opt, parser)

    def executer(self, opt, parser):
        if opt.list:
            for nom in lister():
                print(nom)
        elif opt.list_incompatible_db:
            for nom in lister_incompatibles(lister()):
                print(nom)
        elif opt.drop:
            _verifier_mot_de_passe_maitre(_mot_de_passe_maitre(opt))
            supprimer(opt.db_name)
        elif opt.create:
            creer(opt)
        elif opt.backup:
            chemin = chemin_image(opt)
            with open(chemin, "wb") as flux:
                sauvegarder(opt.db_name, flux)
            print("Generate %s" % chemin)
        elif opt.restore:
            restaurer(
                opt.db_name,
                chemin_image(opt),
                not opt.move_database,
                opt.neutralize,
            )
        elif opt.clone:
            cloner(opt.db_name_from, opt.db_name, opt.neutralize)
        elif opt.version:
            print(version())
        else:
            parser.print_help(sys.stderr)
            mourir(True, "ERROR, missing command")
