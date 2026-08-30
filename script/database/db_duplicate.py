#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Dupliquer une base, et la neutraliser si on le demande.

Pourquoi passer par Odoo plutôt que par `CREATE DATABASE … TEMPLATE`
-------------------------------------------------------------------
La commande PostgreSQL copie les tables, et RIEN d'autre. Odoo, lui, fait
quatre choses de plus que `exp_duplicate_database` réunit :

1. Il coupe les connexions ouvertes sur la source. Sans cela PostgreSQL
   refuse : « is being accessed by other users » — un shell Odoo laissé
   ouvert suffit à faire échouer la copie.
2. Il RÉGÉNÈRE le `database.uuid`. Deux bases qui partagent le leur se
   présentent comme la même instance au service de garantie d'Odoo.
3. Il copie le FILESTORE. Sans lui, chaque pièce jointe de la copie
   pointe vers un fichier qui n'existe pas — 57 Mo perdus en silence sur
   la base qui a servi à écrire ceci.
4. Il neutralise pour de bon, quand on le demande.

Ce que « neutraliser » veut dire, mesuré
----------------------------------------
Le dépôt a trois modules maison — `disable_mail_server`,
`disable_auto_backup`, `disable_payment_provider` — qui font trois gestes.
Aucun ne pose le drapeau, et l'un d'eux ouvre une porte : supprimer tous
les `ir.mail_server` fait retomber Odoo sur le `smtp_server` du fichier
de configuration.

`neutralize_database` d'Odoo exécute les 73 fichiers `neutralize.sql`
livrés par les modules INSTALLÉS. Mesuré sur une base migrée 12 → 18 :

    database.is_neutralized   ABSENT  →  true
    crons actifs                  33  →  1   (l'autovacuum, voulu)
    serveurs de courriel           0  →  1   le bouchon « invalid »
    clé Stripe présente            1  →  0

Deux techniques, selon la version
---------------------------------
`neutralize.py` n'existe qu'à partir d'Odoo 16 ; avant,
`exp_duplicate_database` ne prend que deux arguments. De 12 à 15 on
retombe donc sur la technique du dépôt : `update_prod_to_dev.sh`, qui
installe puis désinstalle `user_test`, `disable_mail_server`,
`disable_auto_backup` et `disable_payment_provider`.

Les deux n'obtiennent PAS la même chose, et il faut le savoir :

                              Odoo ≥ 16   script 12→15
    database.is_neutralized      posé       non posé
    crons désactivés             oui        non
    serveur de courriel        bouchon    supprimés (*)
    clés de paiement            mises à     laissées
                                  NULL      en place
    compte test/test             non          oui

(*) supprimer tous les `ir.mail_server` fait retomber Odoo sur le
`smtp_server` du fichier de configuration ; le bouchon d'Odoo existe
précisément pour boucher ce trou-là.

La technique employée est ANNONCÉE à chaque exécution : une copie dont
on ignore par quel chemin elle est passée ne se juge pas.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

# La neutralisation d'Odoo n'existe pas avant cette version.
PREMIERE_VERSION_NEUTRALISABLE = 16.0

# Comment on neutralise, selon ce que la version sait faire.
NEUTRALISATION_ODOO = "odoo"
NEUTRALISATION_SCRIPT = "script"
SCRIPT_PROD_TO_DEV = "./script/addons/update_prod_to_dev.sh"


def lire_version(nom):
    """Le contenu d'un fichier `.xxx-version`, ou None."""
    chemin = os.path.join(REPO_ROOT, nom)
    try:
        with open(chemin, "r", encoding="utf-8") as handle:
            return handle.read().strip() or None
    except OSError:
        return None


def chemins_odoo():
    """(python du venv, racine d'Odoo) — résolus comme odoo_bin.sh le fait.

    Le nom du venv porte les DEUX versions, Odoo et Python : le composer
    de tête revient à se tromper un jour sur l'une des deux.
    """
    erplibre = lire_version(".erplibre-version")
    odoo = lire_version(".odoo-version")
    if not erplibre or not odoo:
        return None, None
    python = os.path.join(REPO_ROOT, f".venv.{erplibre}", "bin", "python")
    racine = os.path.join(REPO_ROOT, f"odoo{odoo}", "odoo")
    return python, racine


# « rien n'a été passé » et « on m'a passé une version illisible » sont
# deux questions différentes, et un `None` ne doit pas se faire prendre
# pour l'autre : l'appelant dont la lecture a échoué se verrait répondre
# sur la version du checkout, c'est-à-dire sur autre chose.
_NON_FOURNI = object()


def supporte_neutralisation(version=_NON_FOURNI):
    """La version sait-elle neutraliser ? Sans argument : celle du checkout."""
    if version is _NON_FOURNI:
        version = lire_version(".odoo-version")
    try:
        return float(version) >= PREMIERE_VERSION_NEUTRALISABLE
    except (TypeError, ValueError):
        return False


def technique_neutralisation(version=_NON_FOURNI):
    """Par quel chemin neutraliser, pour cette version.

    On ne REFUSE plus sous 12→15 : le dépôt a sa technique, et une copie
    imparfaitement neutralisée vaut mieux qu'une copie brute. Ce qui
    compte est de dire laquelle a servi.
    """
    if supporte_neutralisation(version):
        return NEUTRALISATION_ODOO
    return NEUTRALISATION_SCRIPT


def nom_valide(nom):
    """Un nom de base acceptable — c'est aussi ce qui entre dans du SQL."""
    if not nom or len(nom) > 63:
        return False
    if not (nom[0].isalpha() or nom[0] == "_"):
        return False
    return all(c.isalnum() or c in "_-$" for c in nom)


def script_python(source, cible, neutraliser, config):
    """Le programme qu'on remet à l'interpréteur d'Odoo.

    `parse_config` est indispensable : sans lui, `Registry.new` ne sait ni
    où se connecter ni où sont les addons, et la duplication échoue après
    avoir DÉJÀ créé la base.
    """
    return (
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "import odoo\n"
        "odoo.tools.config.parse_config(['-c', %r])\n"
        "from odoo.service.db import exp_duplicate_database\n"
        "exp_duplicate_database(%r, %r%s)\n"
        % (
            chemins_odoo()[1],
            config,
            source,
            cible,
            ", True" if neutraliser else "",
        )
    )


def bases_existantes():
    """Les bases que PostgreSQL expose, ou None si on n'a pas pu demander."""
    try:
        fait = subprocess.run(
            [
                "psql",
                "-X",
                "-w",
                "-tA",
                "-d",
                "postgres",
                "-c",
                "SELECT datname FROM pg_database WHERE NOT datistemplate",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if fait.returncode:
        return None
    return {
        ligne.strip() for ligne in fait.stdout.splitlines() if ligne.strip()
    }


def verifier(source, cible, neutraliser):
    """Ce qui empêche de commencer. Rendre la liste des refus."""
    refus = []
    for nom, role in ((source, "source"), (cible, "cible")):
        if not nom_valide(nom):
            refus.append(f"{t('Invalid database name: ')}{nom!r} ({role})")
    if source == cible:
        refus.append(t("The source and the copy cannot share a name."))
    bases = bases_existantes()
    if bases is not None:
        if source not in bases:
            refus.append(f"{t('No such database: ')}{source}")
        if cible in bases:
            # Écraser une base sans le dire est la faute qu'on ne rattrape
            # pas : le contenu d'avant n'existe plus nulle part.
            refus.append(f"{t('This database already exists: ')}{cible}")
    if neutraliser and technique_neutralisation() == NEUTRALISATION_SCRIPT:
        # PAS un refus : de 12 à 15 on passe par update_prod_to_dev.sh.
        # Le script doit exister, sinon la copie sortirait brute en se
        # croyant neutralisée — le seul cas vraiment dangereux.
        if not os.path.isfile(os.path.join(REPO_ROOT, SCRIPT_PROD_TO_DEV)):
            refus.append(f"{t('Missing script: ')}{SCRIPT_PROD_TO_DEV}")
    return refus


def neutraliser_par_script(cible, timeout=3600):
    """La technique du dépôt, pour Odoo 12 à 15. Rendre (code, sortie).

    `update_prod_to_dev.sh` installe puis désinstalle quatre modules
    maison. Il tourne depuis la racine du dépôt : les chemins qu'il
    contient sont relatifs, et l'appeler d'ailleurs le fait échouer sur
    `install_addons_dev.sh` introuvable.
    """
    fait = subprocess.run(
        ["bash", SCRIPT_PROD_TO_DEV, cible],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if fait.returncode:
        return fait.returncode, (fait.stderr or fait.stdout).strip()
    return 0, (fait.stdout or "").strip()


def dupliquer(
    source, cible, neutraliser=False, config="config.conf", timeout=3600
):
    """Faire la copie, puis la neutraliser par le chemin de la version.

    La copie d'abord, la neutralisation ensuite : si la seconde échoue,
    la base existe et l'on sait qu'elle est BRUTE. L'inverse — une base
    à moitié neutralisée — ne se distinguerait pas d'une base traitée.
    """
    python, racine = chemins_odoo()
    if not python or not os.path.isfile(python):
        return 2, t("Cannot find the virtualenv for this checkout.")
    if not racine or not os.path.isdir(racine):
        return 2, t("Cannot find the Odoo source for this checkout.")

    par_odoo = neutraliser and (
        technique_neutralisation() == NEUTRALISATION_ODOO
    )
    fait = subprocess.run(
        [python, "-c", script_python(source, cible, par_odoo, config)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if fait.returncode:
        return fait.returncode, (fait.stderr or fait.stdout).strip()

    if neutraliser and not par_odoo:
        code, sortie = neutraliser_par_script(cible, timeout=timeout)
        if code:
            return code, sortie
    return 0, (fait.stdout or "").strip()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=t("Duplicate a database, filestore included."),
    )
    parser.add_argument("-s", "--source", required=True)
    parser.add_argument("-d", "--database", required=True, help=t("the copy"))
    parser.add_argument("-c", "--config", default="config.conf")
    parser.add_argument(
        "--neutralize",
        action="store_true",
        help=t("disable crons, outgoing mail and payment providers"),
    )
    args = parser.parse_args(argv)

    refus = verifier(args.source, args.database, args.neutralize)
    if refus:
        for ligne in refus:
            print(f"❌ {ligne}", file=sys.stderr)
        return 2

    technique = technique_neutralisation()
    if args.neutralize:
        # DIRE par quel chemin : les deux ne posent pas les mêmes gestes,
        # et une copie dont on ignore le traitement ne se juge pas.
        comment = (
            t("Odoo's own neutralisation")
            if technique == NEUTRALISATION_ODOO
            else f"{SCRIPT_PROD_TO_DEV} ({t('Odoo')}"
            f" {lire_version('.odoo-version')})"
        )
        print(f"🧬 {args.source} → {args.database} — {comment}")
    else:
        print(f"🧬 {args.source} → {args.database}")
    code, sortie = dupliquer(
        args.source, args.database, args.neutralize, args.config
    )
    if code:
        print(f"❌ {t('The duplication failed.')}", file=sys.stderr)
        if sortie:
            print(sortie[-2000:], file=sys.stderr)
        return 2
    print(f"✅ {t('Done:')} {args.database}")
    if args.neutralize and technique == NEUTRALISATION_SCRIPT:
        print(
            f"ℹ️  {t('This route does not set database.is_neutralized, does')}"
            f" {t('not disable crons, and leaves payment keys in place.')}"
        )
        print(f"ℹ️  {t('You can log in with test / test.')}")
    if not args.neutralize:
        print(
            f"⚠️  {t('NOT neutralised: its crons run, its mail leaves and')}"
            f" {t('its payment providers can charge.')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
