#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Installer ou retirer la sauvegarde planifiée d'une base Odoo.

Deux unités par base, dans /etc/systemd/system :

- `erplibre-backup-<base>.service` (`Type=oneshot`) lance
  `script/database/odoo_backup.py` SOUS LE COMPTE de l'unité Odoo
  (`User=`, `Group=` son groupe principal), depuis le checkout de
  l'instance, avec tous ses arguments écrits dans `ExecStart` : rien
  d'autre ne la configure. Root n'exécute ainsi aucun code que ce compte
  peut modifier.
- `erplibre-backup-<base>.timer` la déclenche (`OnCalendar`, par défaut
  chaque jour à 03:00, `RandomizedDelaySec`, `Persistent=true` : une
  échéance manquée machine éteinte part au démarrage).

Une troisième pièce, `/etc/tmpfiles.d/erplibre-backup-<base>.conf`, crée
au démarrage le fichier du verrou de la base,
`/run/lock/erplibre-db-<base>.lock`, à root en 0644 ; l'installation le
crée aussi tout de suite (`systemd-tmpfiles --create`). Le verrou est
partagé avec `update_module`, qui tourne sous root, et ne se replie jamais
ailleurs : là où /run/lock est à root en 0755, le compte ne pourrait pas
le créer lui-même, et chaque sauvegarde planifiée refuserait. Ouvrir un
fichier existant suffit au verrou (voir lock.py).

L'instance se détecte comme pour l'outil de sauvegarde (unité, compte,
configuration, base). Le checkout lancé est le dossier de travail de
l'unité s'il contient l'outil, sinon celui de ce script ; l'interpréteur
est son `.venv.erplibre/bin/python` s'il existe, sinon /usr/bin/python3.
Sous root, l'installation vérifie SOUS LE COMPTE (`runuser -u COMPTE --
test`) qu'il peut exécuter l'interpréteur et lire l'outil et la
configuration Odoo ; un manque refuse avant d'écrire quoi que ce soit,
plutôt qu'une sauvegarde qui échouerait chaque nuit.

Chaque fichier écrit commence par une ligne de marque. Un fichier qui
existe SANS cette marque n'a pas été écrit ici : il n'est ni remplacé
ni retiré (code 2), et rien n'est changé. Les dossiers
`<dest>/<base>` (0700) et `<state-dir>/<base>` (0755) sont créés au
compte de l'unité ; un dossier commun créé ici reste à root, en 0755.
Un dossier existant où le compte ne peut pas écrire refuse.

`ExecStart` est cité pour systemd et non pour un shell : `%` devient
`%%`, `$` devient `$$`, et un argument qui porte un espace, un guillemet,
une barre oblique inverse ou un point-virgule est mis entre guillemets
doubles. Un caractère de contrôle refuse : un saut de ligne ajouterait
une directive à l'unité.

`--uninstall` arrête et désactive la minuterie, arrête le service, retire
les trois fichiers et recharge systemd ; les sauvegardes, l'état et le
fichier du verrou restent. `--dry-run` affiche les deux unités et les commandes, sans rien
écrire. Root est exigé, sauf `--dry-run`. `--root DIR` préfixe tous les
chemins écrits (un test y met un dossier temporaire).

Codes de sortie : 0 réussi ; 1 systemctl ou systemd-tmpfiles en échec ;
2 refusé avant tout changement.

Bibliothèque standard seulement, sans syntaxe postérieure à Python 3.7.
"""

from __future__ import annotations

import argparse
import grp
import os
import pwd
import re
import sys
import tempfile
import types

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.database import odoo_backup  # noqa: E402
from script.lib_ops import lock, report, service, systemd  # noqa: E402

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

CODE_OK = 0
CODE_ECHEC = 1
CODE_REFUS = 2

DOSSIER_UNITES = "/etc/systemd/system"
DOSSIER_TMPFILES = "/etc/tmpfiles.d"
MARQUE = (
    "# Managed by script/systemd/install_backup_timer.py:"
    " rerun it instead of editing this file."
)
CALENDRIER = "*-*-* 03:00:00"
DELAI_ALEATOIRE = "30min"
# Minuterie d'un outil privé antérieur : deux minuteries feraient deux
# sauvegardes.
ANCIENNES = ("odoo-backup.timer",)
OUTIL = os.path.join("script", "database", "odoo_backup.py")
PYTHON_SYSTEME = "/usr/bin/python3"
MODE_UNITE = 0o644

RE_CALENDRIER = re.compile(r"[A-Za-z0-9*:/.,~ +-]+")
RE_DUREE = re.compile(r"[0-9]+ ?[a-z]*( [0-9]+ ?[a-z]*)*")
RE_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")
RE_A_CITER = re.compile(r"[\s\"'\\;]")


def citer(argument):
    """Un argument d'ExecStart, cité pour systemd (voir l'en-tête).
    ValueError sur un caractère de contrôle."""
    if RE_CONTROLE.search(argument):
        raise ValueError(argument)
    argument = argument.replace("%", "%%").replace("$", "$$")
    if not argument or RE_A_CITER.search(argument):
        echappe = argument.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{echappe}"'
    return argument


def ligne_execstart(argv):
    return " ".join(citer(a) for a in argv)


def nom_tmpfiles(base):
    """Le fichier tmpfiles.d qui crée le verrou de `base`."""
    return f"erplibre-backup-{base}.conf"


def chemin_verrou(base):
    """Le fichier du verrou de `base`, tel que les outils l'ouvrent."""
    return os.path.join(
        lock.DOSSIER_PAR_DEFAUT, service.nom_verrou(base) + ".lock"
    )


def contenu_tmpfiles(base):
    return "\n".join([MARQUE, f"f {chemin_verrou(base)} 0644 root root -", ""])


def noms_unites(base):
    """(service, minuterie) de la sauvegarde de `base`."""
    return (
        systemd.nom_unite(f"erplibre-backup-{base}.service"),
        systemd.nom_unite(f"erplibre-backup-{base}.timer"),
    )


class Systeme(service.SystemeBase):
    """Les effets de bord de l'installation ; `racine` préfixe chaque
    chemin écrit ou lu sous /etc et sous les dossiers de données."""

    def __init__(self, verbeux=False, racine="/"):
        super().__init__(verbeux=verbeux)
        self.racine = racine or "/"

    def chemin(self, absolu):
        return os.path.join(self.racine, absolu.lstrip("/"))

    def groupe(self, utilisateur):
        """Le nom du groupe principal du compte. Lève KeyError."""
        gid = pwd.getpwnam(utilisateur).pw_gid
        try:
            return grp.getgrgid(gid).gr_name
        except KeyError:
            return str(gid)


def contenu_service(base, utilisateur, groupe, checkout, argv):
    return "\n".join(
        [
            MARQUE,
            "[Unit]",
            f"Description=ERPLibre verified backup of {base}",
            "After=postgresql.service",
            "",
            "[Service]",
            "Type=oneshot",
            f"User={utilisateur}",
            f"Group={groupe}",
            "WorkingDirectory=" + checkout.replace("%", "%%"),
            "Nice=10",
            "IOSchedulingClass=idle",
            "NoNewPrivileges=yes",
            "PrivateTmp=yes",
            "ProtectSystem=full",
            "ExecStart=" + ligne_execstart(argv),
            "",
        ]
    )


def contenu_minuterie(base, unite_service, calendrier, delai):
    return "\n".join(
        [
            MARQUE,
            "[Unit]",
            f"Description=Schedule of the ERPLibre verified backup of {base}",
            "",
            "[Timer]",
            f"OnCalendar={calendrier}",
            f"RandomizedDelaySec={delai}",
            "Persistent=true",
            f"Unit={unite_service}",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )


def porte_la_marque(chemin):
    """True si le fichier commence par la ligne de marque."""
    try:
        with open(chemin, encoding="utf-8", errors="replace") as fichier:
            return fichier.readline().rstrip("\n") == MARQUE
    except OSError:
        return False


def choisir_checkout(wd, existe=os.path.isfile):
    """(checkout, interpréteur) : le dossier de travail de l'unité s'il
    porte l'outil, sinon le checkout de ce script."""
    checkout = wd if wd and existe(os.path.join(wd, OUTIL)) else RACINE
    python = os.path.join(checkout, ".venv.erplibre", "bin", "python")
    if not existe(python):
        python = PYTHON_SYSTEME
    return checkout, python


def argv_outil(args, plan, checkout, python):
    """La commande de sauvegarde, arguments explicites."""
    argv = [
        python,
        os.path.join(checkout, OUTIL),
        "--service",
        plan.unite,
        "--db",
        plan.base,
        "--odoo-conf",
        plan.config_path,
        "--user",
        plan.utilisateur,
        "--dest",
        os.path.abspath(args.dest),
        "--state-dir",
        os.path.abspath(args.state_dir),
        "--keep-daily",
        str(args.keep_daily),
        "--keep-weekly",
        str(args.keep_weekly),
        "--keep-monthly",
        str(args.keep_monthly),
        "--keep-recent-days",
        str(args.keep_recent_days),
    ]
    if args.copy_to:
        argv += ["--copy-to", args.copy_to]
    return argv


def verifier_calendrier(valeur, systeme, rapport):
    """Refus si `valeur` n'est pas une expression OnCalendar admise.
    `systemd-analyze calendar` tranche quand il est là."""
    if not RE_CALENDRIER.fullmatch(valeur or ""):
        raise service.Refus(
            service.N_("Invalid OnCalendar value: {value}"), value=valeur
        )
    code, _sortie = systeme.lanceur(
        ["systemd-analyze", "calendar", "--", valeur], 30
    )
    if code == 127:
        rapport.attn(
            t("systemd-analyze is missing: {value} not validated.").format(
                value=valeur
            )
        )
    elif code != 0:
        raise service.Refus(
            service.N_("Invalid OnCalendar value: {value}"), value=valeur
        )


def verifier_acces(plan, checkout, python, systeme, rapport):
    """Refus si le compte de l'unité ne peut pas exécuter `python`, ou lire
    l'outil ou la configuration Odoo. Le test tourne SOUS le compte
    (`runuser -u COMPTE -- test`) : le noyau tranche, dossiers parents,
    groupes et liens compris. Hors root, rien n'est vérifié et un
    avertissement le dit."""
    lire = service.N_(
        "{user} cannot read {path}: every scheduled backup would fail."
        " Give it access, or install from a checkout it can read."
    )
    controles = (
        (
            "-x",
            python,
            service.N_(
                "{user} cannot execute {path}: every scheduled backup would"
                " fail. Give it access, or install from a checkout it can"
                " read."
            ),
        ),
        ("-r", os.path.join(checkout, OUTIL), lire),
        ("-r", os.path.abspath(plan.config_path), lire),
    )
    if systeme.euid() != 0:
        rapport.attn(
            t(
                "Access of {user} to the tool and its configuration: not"
                " checked (requires sudo)."
            ).format(user=plan.utilisateur)
        )
        return
    for option, chemin, modele in controles:
        code, _sortie = systeme.lanceur(
            ["runuser", "-u", plan.utilisateur, "--", "test", option, chemin],
            30,
        )
        if code != 0:
            raise service.Refus(modele, user=plan.utilisateur, path=chemin)


def dossiers(args, plan):
    """[(commun, propre, mode)] des dossiers de données de la base."""
    dest = os.path.abspath(args.dest)
    etat = os.path.abspath(args.state_dir)
    return [
        (dest, os.path.join(dest, plan.base), odoo_backup.MODE_DOSSIER),
        (etat, os.path.join(etat, plan.base), odoo_backup.MODE_PARTAGE),
    ]


def preparer_dossiers(args, plan, systeme):
    """[(chemin réel, mode, au_compte)] à créer, parents compris ; Refus
    si un dossier de la base existe sans être inscriptible par le
    compte."""
    a_creer = []
    for commun, propre, mode in dossiers(args, plan):
        reel_commun = systeme.chemin(commun)
        reel_propre = systeme.chemin(propre)
        manquants = []
        courant = reel_commun
        while not os.path.isdir(courant):
            if os.path.lexists(courant):
                raise service.Refus(
                    service.N_("{path} is not a directory."), path=courant
                )
            manquants.append(courant)
            courant = os.path.dirname(courant)
        for chemin in reversed(manquants):
            if (chemin, odoo_backup.MODE_PARTAGE, False) not in a_creer:
                a_creer.append((chemin, odoo_backup.MODE_PARTAGE, False))
        if not os.path.lexists(reel_propre):
            a_creer.append((reel_propre, mode, True))
        elif not os.path.isdir(reel_propre) or not systeme.inscriptible(
            reel_propre, plan.utilisateur
        ):
            raise service.Refus(
                service.N_("{path} is not a directory writable by {user}."),
                path=propre,
                user=plan.utilisateur,
            )
    return a_creer


def ecrire_unite(chemin, contenu):
    """Écrit `contenu` par fichier temporaire du même dossier, mode 0644,
    puis renommage : une unité n'est jamais lue à moitié écrite."""
    fd, provisoire = tempfile.mkstemp(
        prefix=".erplibre-backup.", dir=os.path.dirname(chemin)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fichier:
            fichier.write(contenu)
            fichier.flush()
            os.fsync(fichier.fileno())
        os.chmod(provisoire, MODE_UNITE)
        os.replace(provisoire, chemin)
    except BaseException:
        try:
            os.remove(provisoire)
        except FileNotFoundError:
            pass
        raise


def _systemctl(systeme, rapport, *arguments):
    code, sortie = systeme.lanceur(["systemctl"] + list(arguments), 120)
    if code != 0:
        rapport.fail(
            t("systemctl {command} failed (code {code}): {output}").format(
                command=" ".join(arguments),
                code=code,
                output=sortie.strip()[:300],
            )
        )
        return False
    return True


def _refuser_unites_etrangeres(chemins):
    for chemin in chemins:
        if os.path.lexists(chemin) and not porte_la_marque(chemin):
            raise service.Refus(
                service.N_(
                    "{path} exists and was not written by this script:"
                    " nothing was changed."
                ),
                path=chemin,
            )


def preparer(args, plan, systeme, rapport):
    """Tout ce que l'installation écrira, vérifié avant d'écrire : une
    description (`chemins`, `textes`, `a_creer`, `groupe`, `unites`).
    Refus sur ce qui empêche l'installation."""
    unites = noms_unites(plan.base)
    chemins = [
        systeme.chemin(os.path.join(DOSSIER_UNITES, nom)) for nom in unites
    ]
    tmpfiles = systeme.chemin(
        os.path.join(DOSSIER_TMPFILES, nom_tmpfiles(plan.base))
    )
    checkout, python = choisir_checkout(plan.wd)
    if checkout != plan.wd:
        rapport.attn(
            t(
                "The unit's working directory has no {tool}: this checkout"
                " is used, {path}."
            ).format(tool=OUTIL, path=checkout)
        )
    _refuser_unites_etrangeres(chemins + [tmpfiles])
    verifier_calendrier(args.on_calendar, systeme, rapport)
    if not RE_DUREE.fullmatch(args.randomized_delay or ""):
        raise service.Refus(
            service.N_("Invalid RandomizedDelaySec value: {value}"),
            value=args.randomized_delay,
        )
    try:
        groupe = systeme.groupe(plan.utilisateur)
    except KeyError:
        raise service.Refus(
            service.N_("Unknown account: {user}"), user=plan.utilisateur
        )
    argv = argv_outil(args, plan, checkout, python)
    try:
        ligne_execstart(argv)
    except ValueError as err:
        raise service.Refus(
            service.N_("Control character in an argument: {value}"),
            value=repr(str(err)),
        )
    verifier_acces(plan, checkout, python, systeme, rapport)
    a_creer = preparer_dossiers(args, plan, systeme)
    for ancienne in ANCIENNES:
        chemin = systeme.chemin(os.path.join(DOSSIER_UNITES, ancienne))
        if os.path.lexists(chemin):
            rapport.attn(
                t(
                    "{unit} from an older tool is installed: two timers would"
                    " back up twice. Remove one of them."
                ).format(unit=ancienne)
            )
    textes = [
        contenu_service(plan.base, plan.utilisateur, groupe, checkout, argv),
        contenu_minuterie(
            plan.base, unites[0], args.on_calendar, args.randomized_delay
        ),
    ]
    return types.SimpleNamespace(
        unites=unites,
        chemins=chemins,
        textes=textes,
        tmpfiles=tmpfiles,
        texte_tmpfiles=contenu_tmpfiles(plan.base),
        a_creer=a_creer,
        groupe=groupe,
    )


def simuler(installation, plan, rapport):
    for chemin, mode, au_compte in installation.a_creer:
        commande = service.joindre(
            ["mkdir", "-m", f"{mode:04o}", "--", chemin]
        )
        if au_compte:
            commande += " && " + service.joindre(
                [
                    "chown",
                    f"{plan.utilisateur}:{installation.groupe}",
                    "--",
                    chemin,
                ]
            )
        rapport.sim(commande)
    for chemin, texte in zip(
        installation.chemins + [installation.tmpfiles],
        installation.textes + [installation.texte_tmpfiles],
    ):
        rapport.sim(chemin)
        for ligne in texte.splitlines():
            rapport.texte("      " + ligne)
    rapport.sim(
        service.joindre(
            ["systemd-tmpfiles", "--create", "--", installation.tmpfiles]
        )
    )
    rapport.sim("systemctl daemon-reload")
    rapport.sim(f"systemctl enable --now {installation.unites[1]}")
    rapport.ok(t("Simulation finished: nothing was written."))
    return CODE_OK


def installer(args, plan, systeme, rapport):
    """Installe (ou simule) les deux unités ; rend le code de sortie."""
    try:
        installation = preparer(args, plan, systeme, rapport)
    except service.Refus as err:
        rapport.erreur(err.message(t))
        return CODE_REFUS
    if args.dry_run:
        return simuler(installation, plan, rapport)
    for chemin, mode, au_compte in installation.a_creer:
        try:
            if au_compte:
                systeme.creer_dossier(chemin, plan.utilisateur, mode)
            else:
                systeme.mkdir(chemin, mode)
        except (OSError, KeyError) as err:
            rapport.erreur(
                t("Cannot create {path}: {error}").format(
                    path=chemin, error=err
                )
            )
            return CODE_REFUS
        rapport.ok(t("Created {path}.").format(path=chemin))
    for chemin, texte in zip(installation.chemins, installation.textes):
        try:
            ecrire_unite(chemin, texte)
        except OSError as err:
            rapport.erreur(
                t("Cannot write {path}: {error}").format(
                    path=chemin, error=err
                )
            )
            return CODE_ECHEC
        rapport.ok(t("Written: {path}").format(path=chemin))
    if not _creer_verrou(installation, systeme, rapport):
        return CODE_ECHEC
    unite_service, unite_minuterie = installation.unites
    if not _systemctl(systeme, rapport, "daemon-reload"):
        return CODE_ECHEC
    if not _systemctl(systeme, rapport, "enable", "--now", unite_minuterie):
        return CODE_ECHEC
    rapport.ok(
        t("Scheduled backup installed: {timer} ({calendar}).").format(
            timer=unite_minuterie, calendar=args.on_calendar
        )
    )
    rapport.detail(f"systemctl list-timers {unite_minuterie}")
    rapport.detail(f"systemctl start {unite_service}")
    rapport.detail(f"journalctl -u {unite_service}")
    return CODE_OK


def _creer_verrou(installation, systeme, rapport):
    """Écrit le fichier tmpfiles.d (son dossier créé au besoin) et crée le
    verrou tout de suite ; False, message écrit, sur un échec."""
    dossier = os.path.dirname(installation.tmpfiles)
    try:
        if not os.path.isdir(dossier):
            systeme.mkdir(dossier, odoo_backup.MODE_PARTAGE)
        ecrire_unite(installation.tmpfiles, installation.texte_tmpfiles)
    except OSError as err:
        rapport.fail(
            t("Cannot write {path}: {error}").format(
                path=installation.tmpfiles, error=err
            )
        )
        return False
    rapport.ok(t("Written: {path}").format(path=installation.tmpfiles))
    code, sortie = systeme.lanceur(
        ["systemd-tmpfiles", "--create", "--", installation.tmpfiles], 60
    )
    if code != 0:
        rapport.fail(
            t(
                "systemd-tmpfiles failed (code {code}): {output}. The lock"
                " file is missing until the next boot."
            ).format(code=code, output=sortie.strip()[:300])
        )
        return False
    return True


def desinstaller(args, base, systeme, rapport):
    """Retire les unités et le fichier tmpfiles.d écrits ici ; rend le code
    de sortie. Les sauvegardes, l'état et le fichier du verrou restent."""
    unite_service, unite_minuterie = noms_unites(base)
    chemins = [
        systeme.chemin(os.path.join(DOSSIER_UNITES, nom))
        for nom in (unite_service, unite_minuterie)
    ] + [systeme.chemin(os.path.join(DOSSIER_TMPFILES, nom_tmpfiles(base)))]
    try:
        _refuser_unites_etrangeres(chemins)
    except service.Refus as err:
        rapport.erreur(err.message(t))
        return CODE_REFUS
    presents = [c for c in chemins if os.path.lexists(c)]
    if not presents:
        rapport.ok(
            t("Nothing to remove for {database}.").format(database=base)
        )
        return CODE_OK
    if args.dry_run:
        rapport.sim(f"systemctl disable --now {unite_minuterie}")
        rapport.sim(f"systemctl stop {unite_service}")
        for chemin in presents:
            rapport.sim(service.joindre(["rm", "--", chemin]))
        rapport.sim("systemctl daemon-reload")
        rapport.ok(t("Simulation finished: nothing was written."))
        return CODE_OK
    code = CODE_OK
    if not _systemctl(systeme, rapport, "disable", "--now", unite_minuterie):
        code = CODE_ECHEC
    if not _systemctl(systeme, rapport, "stop", unite_service):
        code = CODE_ECHEC
    for chemin in presents:
        try:
            os.remove(chemin)
            rapport.ok(t("Removed: {path}").format(path=chemin))
        except OSError as err:
            rapport.fail(
                t("Cannot delete {path}: {error}").format(
                    path=chemin, error=err
                )
            )
            code = CODE_ECHEC
    if not _systemctl(systeme, rapport, "daemon-reload"):
        code = CODE_ECHEC
    rapport.detail(
        t("Backups and state are kept: {dest}, {state}.").format(
            dest=os.path.join(os.path.abspath(args.dest), base),
            state=os.path.join(os.path.abspath(args.state_dir), base),
        )
    )
    return code


def analyser(argv=None):
    types_ = service.types_argparse(t)
    parser = argparse.ArgumentParser(
        description=t(
            "Install or remove the scheduled verified backup of an Odoo"
            " database: a systemd service and timer run as the unit's"
            " account."
        )
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help=t("Stop and remove the timer and the service; keep backups."),
    )
    parser.add_argument(
        "--service",
        type=types_.unite,
        help=t(
            "systemd unit; default: the unit whose WorkingDirectory is this"
            " checkout, else the only active one."
        ),
    )
    parser.add_argument(
        "--db",
        type=types_.base,
        help=t("Database; default: -d of the unit, else db_name."),
    )
    parser.add_argument(
        "--odoo-conf",
        help=t("Odoo configuration file; default: the one the unit reads."),
    )
    parser.add_argument(
        "--user",
        type=types_.utilisateur,
        help=t(
            "Account running PostgreSQL tools; default: User= of the unit."
        ),
    )
    parser.add_argument(
        "--dest",
        default=odoo_backup.DEST_PAR_DEFAUT,
        help=t("Backup directory; default: {path}.").format(
            path=odoo_backup.DEST_PAR_DEFAUT
        ),
    )
    parser.add_argument(
        "--state-dir",
        default=odoo_backup.ETAT_PAR_DEFAUT,
        help=t("State directory; default: {path}.").format(
            path=odoo_backup.ETAT_PAR_DEFAUT
        ),
    )
    for option, defaut, aide in (
        (
            "--keep-daily",
            odoo_backup.GARDE_QUOTIDIEN,
            "Daily backups kept; default: {value}.",
        ),
        (
            "--keep-weekly",
            odoo_backup.GARDE_HEBDO,
            "Weekly backups kept; default: {value}.",
        ),
        (
            "--keep-monthly",
            odoo_backup.GARDE_MENSUEL,
            "Monthly backups kept; default: {value}.",
        ),
        (
            "--keep-recent-days",
            odoo_backup.GARDE_RECENTS,
            "Keep every backup of the last N days; default: {value}.",
        ),
    ):
        parser.add_argument(
            option,
            type=types_.entier,
            default=defaut,
            help=t(aide).format(value=defaut),
        )
    parser.add_argument(
        "--copy-to",
        type=odoo_backup._type_copie,
        help=t(
            "Off-site copy with rsync over ssh: [user@]host:/path or an"
            " absolute path; disabled by default."
        ),
    )
    parser.add_argument(
        "--on-calendar",
        default=CALENDRIER,
        help=t("When the backup runs (OnCalendar); default: {value}.").format(
            value=CALENDRIER
        ),
    )
    parser.add_argument(
        "--randomized-delay",
        default=DELAI_ALEATOIRE,
        help=t("RandomizedDelaySec of the timer; default: {value}.").format(
            value=DELAI_ALEATOIRE
        ),
    )
    parser.add_argument(
        "--root",
        default="/",
        help=t("Prefix of every path written (tests); default: /."),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=t("Show both units and the commands; write nothing."),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=t("Show each system command on stderr."),
    )
    return parser.parse_args(argv)


def main(argv=None, systeme=None, rapport=None):
    args = analyser(argv)
    systeme = systeme or Systeme(verbeux=args.verbose, racine=args.root)
    rapport = rapport or report.Rapport()
    if systeme.euid() != 0 and not args.dry_run:
        rapport.erreur(t("Root is required (sudo), except with --dry-run."))
        return CODE_REFUS
    if args.uninstall and args.db:
        return desinstaller(args, args.db, systeme, rapport)
    plan = types.SimpleNamespace()
    try:
        service.detecter_instance(args, systeme, RACINE, plan)
    except service.Refus as err:
        rapport.erreur(err.message(t))
        return CODE_REFUS
    rapport.champ(t("Service"), plan.unite)
    rapport.champ(t("Account"), plan.utilisateur)
    rapport.champ(t("Odoo config"), plan.config_path)
    rapport.champ(t("Database"), f"{plan.base} ({plan.origine_base})")
    if args.uninstall:
        return desinstaller(args, plan.base, systeme, rapport)
    return installer(args, plan, systeme, rapport)


if __name__ == "__main__":
    sys.exit(main())
