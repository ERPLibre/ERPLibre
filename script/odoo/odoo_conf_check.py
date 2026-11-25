#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Valider le fichier de configuration d'une instance Odoo, sans la
démarrer.

Le fichier est celui de `--file`, sinon celui que lit l'unité systemd
(`--service`, sinon l'unité dont le WorkingDirectory est ce checkout,
sinon la seule active), trouvé comme le fait `update_module.py`. Il est
relu comme Odoo le lira au prochain démarrage (`lib_ops/odoo_conf.py`) :
clés et sections répétées, lignes hors section ou sans `=`, commentaire
après une valeur, valeurs refusées par les conversions d'optparse,
limites de mémoire écrites en Mo plutôt qu'en octets, limite douce
au-dessus de la dure, limites du processus gevent, anciens noms.

Les types suivent la version d'Odoo : `--odoo-version`, sinon le
`.odoo-version` du dossier de l'unité (ou du dossier du fichier avec
`--file`), sinon un chemin `odooNN.0` de la ligne de commande de l'unité ;
inconnue, seuls les types communs aux versions 12 à 18 sont vérifiés. Les
conseils de workers et de mémoire suivent `--cpus` et `--memory-mb`,
sinon ce poste.

Lecture seule : le fichier n'est jamais modifié, Odoo n'est jamais lancé.
La valeur d'une clé qui ressemble à un secret n'est jamais citée.

Le groupe `odoo_conf` du profil de l'instance (`lib_ops/profil.py`) donne
`cpus`, `memory_mb` et `verbose` ; la ligne de commande gagne toujours.
`--file`, `--service`, `--odoo-version` et `--json` n'en viennent jamais.

Sortie : une ligne par constat, puis le bilan. `--json` rend des clés
stables, en anglais, jamais traduites.

Codes de sortie : 0 aucune erreur (les avertissements sont listés) ; 1 au
moins une erreur — Odoo refuserait le fichier ou ne pourrait pas servir
avec lui ; 2 la vérification n'a pas pu se faire (usage, détection,
fichier illisible : conseil sudo) ; 130 interrompu.

Bibliothèque standard seulement, sans syntaxe postérieure à Python 3.7 :
le programme se lance aussi par le python3 d'un serveur de production.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import types

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.lib_ops import (  # noqa: E402
    odoo_conf,
    odoo_instance,
    profil,
    report,
    service,
    systemd,
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

CODE_OK = 0
CODE_ERREUR = 1
CODE_REFUS = 2
CODE_INTERROMPU = 130

# Groupe des réglages de cet outil dans un profil de production.
GROUPE = "odoo_conf"

N_ = service.N_
Refus = service.Refus


class Systeme(service.SystemeBase):
    """Les effets de bord : systemctl (`lanceur`, hérité) et les
    ressources de ce poste. Un test en dérive une classe."""

    def ressources(self):
        """(processeurs, mémoire en Mo) de ce poste, None si illisible."""
        return odoo_conf.ressources_hote()


def detecter(args, systeme):
    """(chemin, version, unité) du fichier à valider. Lève Refus sur ce qui
    manque."""
    if args.file:
        chemin = os.path.abspath(args.file)
        version = args.odoo_version or odoo_conf.version_du_dossier(
            os.path.dirname(chemin)
        )
        return chemin, version, ""
    application = getattr(args, "profil", None)
    plan = types.SimpleNamespace()
    props = service.detecter_unite(
        args.service,
        systeme,
        RACINE,
        plan,
        devinee=getattr(application, "unite_devinee", None),
    )
    service.detecter_compte_et_dossier(None, systeme, plan, props)
    try:
        chemin, _origine = odoo_instance.trouver_config(
            plan.execstart, plan.wd, plan.env_unite
        )
    except odoo_instance.ErreurDetection:
        raise Refus(N_("No Odoo configuration file found (try --file)."))
    version = args.odoo_version or odoo_conf.version_instance(
        plan.wd, plan.execstart
    )
    return chemin, version, plan.unite


def lire(chemin, version, cpus, memoire):
    """La `Verification` du fichier ; Refus s'il ne se lit pas (conseil
    sudo pour un refus de permission)."""
    try:
        return odoo_conf.verifier(chemin, version, cpus, memoire)
    except PermissionError:
        raise Refus(N_("Cannot read {path}: run with sudo."), path=chemin)
    except OSError as err:
        raise Refus(
            N_("Cannot read {path}: {error}"),
            path=chemin,
            error=err.strerror or err,
        )


def ecrire_texte(
    rapport, verification, unite, cpus, memoire, application=None
):
    """Le titre, le profil lu, le fichier visé, puis un constat par ligne
    et le bilan."""
    rapport.texte(
        "{} — {}".format(
            t("Odoo configuration check"),
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
    )
    if application is not None:
        profil.afficher(application, rapport, t)
    fichier = verification.chemin
    if unite:
        fichier = t("{path} (unit {unit})").format(path=fichier, unit=unite)
    rapport.champ(t("File"), fichier)
    rapport.champ(
        t("Odoo version"),
        str(verification.version) if verification.version else t("unknown"),
    )
    if cpus and memoire:
        rapport.champ(
            t("This machine"),
            t("{cpus} CPU, {memory} MB").format(cpus=cpus, memory=memoire),
        )
    for constat in verification.constats:
        texte = constat.decrire(t)
        if constat.niveau == odoo_conf.ERREUR:
            rapport.fail(texte)
        elif constat.niveau == odoo_conf.AVERTISSEMENT:
            rapport.attn(texte)
        else:
            rapport.detail("ℹ " + texte)
    compte = verification.compter()
    rapport.texte()
    if verification.refuse:
        rapport.fail(
            t(
                "{count} error(s): Odoo refuses this file at its next start,"
                " or cannot serve with it."
            ).format(count=compte[odoo_conf.ERREUR])
        )
    else:
        rapport.ok(
            t(
                "No error: Odoo reads this file ({warnings} warning(s))."
            ).format(warnings=compte[odoo_conf.AVERTISSEMENT])
        )


def resume_json(verification, unite, cpus, memoire, code, application=None):
    """Le résumé JSON, clés stables en anglais."""
    resume = {"tool": "odoo_conf_check", "service": unite or None}
    resume.update(verification.json())
    resume["host"] = {"cpus": cpus, "memory_mb": memoire}
    resume["exit_code"] = code
    bloc = application.json() if application is not None else None
    if bloc is not None:
        resume["profile"] = bloc
    return resume


# --- Programme -------------------------------------------------------------

TYPES = service.types_argparse(t)


def _type_version(valeur):
    version = odoo_conf.version_majeure(valeur)
    if version is None:
        raise argparse.ArgumentTypeError(
            t("expected an Odoo version from 12 to 18: {value}").format(
                value=valeur
            )
        )
    return version


def construire_parseur():
    """Le parser seul, aides dans la langue courante : ni analyse, ni
    effet de bord."""
    parser = argparse.ArgumentParser(
        description=t(
            "Check an Odoo configuration file the way Odoo reads it at its"
            " next start: repeated keys, comments after a value, types,"
            " memory limits; workers and memory advice. Read-only."
        )
    )
    parser.add_argument(
        "--file",
        metavar="PATH",
        help=t(
            "Configuration file to check; default: the one the systemd unit"
            " reads."
        ),
    )
    parser.add_argument(
        "--service",
        type=TYPES.unite,
        help=t(
            "systemd unit; default: the unit whose WorkingDirectory is this"
            " checkout, else the only active one."
        ),
    )
    parser.add_argument(
        "--odoo-version",
        type=_type_version,
        metavar="VERSION",
        help=t(
            "Odoo version whose types apply (12 to 18); default: the"
            " .odoo-version of the unit's directory, or of the file's"
            " directory."
        ),
    )
    parser.add_argument(
        "--cpus",
        type=TYPES.secondes,
        metavar="N",
        help=t(
            "Processors for the workers advice; default: those of this"
            " machine."
        ),
    )
    parser.add_argument(
        "--memory-mb",
        type=TYPES.secondes,
        metavar="MB",
        help=t(
            "Memory in MB for the workers and memory advice; default: that"
            " of this machine."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=t("Print the summary as JSON (untranslated keys)."),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=t("Show each system command on stderr."),
    )
    return parser


def valider(parser, args):
    """Les contrôles d'après analyse, profil déjà posé ; un refus sort par
    `parser.error` (code 2)."""
    if args.file and args.service:
        parser.error(t("--service cannot be combined with --file."))


def analyser(argv=None, lanceur=None):
    """Les arguments, profil appliqué (`args.profil`). Avec `--file`,
    l'unité n'est pas devinée : seul `--profile` donne un profil."""
    parser = construire_parseur()
    args, _application = profil.analyser(
        parser,
        argv,
        GROUPE,
        t,
        RACINE,
        lanceur=lanceur,
        utilise_service=profil.outil(GROUPE).avec_service,
    )
    valider(parser, args)
    return args


def _refuser(args, flux, message):
    if args.json:
        resume = {
            "tool": "odoo_conf_check",
            "exit_code": CODE_REFUS,
            "error": message,
        }
        bloc = getattr(args, "profil", None)
        bloc = bloc.json() if bloc is not None else None
        if bloc is not None:
            resume["profile"] = bloc
        print(json.dumps(resume, ensure_ascii=False), file=flux)
    print(f"❌ {message}", file=sys.stderr)
    return CODE_REFUS


def executer(args, systeme, flux):
    application = getattr(args, "profil", None)
    try:
        chemin, version, unite = detecter(args, systeme)
        cpus, memoire = systeme.ressources()
        cpus = args.cpus or cpus
        memoire = args.memory_mb or memoire
        verification = lire(chemin, version, cpus, memoire)
    except Refus as err:
        return _refuser(args, flux, err.message(t))
    code = CODE_ERREUR if verification.refuse else CODE_OK
    if args.json:
        if application is not None:
            avertir = report.Rapport(flux=sys.stderr)
            for ligne in application.avertissements(t):
                avertir.attn(ligne)
        print(
            json.dumps(
                resume_json(
                    verification, unite, cpus, memoire, code, application
                ),
                ensure_ascii=False,
                indent=2,
            ),
            file=flux,
        )
        return code
    rapport = report.Rapport(flux=flux)
    ecrire_texte(rapport, verification, unite, cpus, memoire, application)
    return code


def main(argv=None, systeme=None, flux=None):
    # Le système réel se construit après l'analyse (`--verbose`) : la
    # devinette du profil passe alors par `systemd.lancer`.
    args = analyser(
        argv, lanceur=systeme.lanceur if systeme else systemd.lancer
    )
    systeme = systeme or Systeme(verbeux=args.verbose)
    flux = flux or sys.stdout
    try:
        return executer(args, systeme, flux)
    except KeyboardInterrupt:
        print(t("Interrupted."), file=sys.stderr)
        return CODE_INTERROMPU


if __name__ == "__main__":
    sys.exit(main())
