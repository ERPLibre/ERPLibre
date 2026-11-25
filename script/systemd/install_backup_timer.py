#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Installer ou retirer la sauvegarde planifiée d'une base Odoo.

Deux unités par base, dans /etc/systemd/system :

- `erplibre-backup-<base>.service` (`Type=oneshot`) lance
  `script/database/odoo_backup.py` SOUS LE COMPTE de l'unité Odoo
  (`User=`, `Group=` son groupe principal), depuis le checkout de
  l'instance, avec ses arguments écrits dans `ExecStart` : rien d'autre
  ne la configure, que le profil nommé par `--profile`. Root n'exécute
  ainsi aucun code que ce compte peut modifier.
- `erplibre-backup-<base>.timer` la déclenche (`OnCalendar`, par défaut
  CALENDRIER, `RandomizedDelaySec`, `Persistent=true` : une échéance
  manquée machine éteinte part au démarrage).

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

Les options se lisent aussi dans le profil de production de l'instance
(`lib_ops/profil.py`, groupe `backup_timer`) : `--on-calendar`,
`--randomized-delay` et `--verbose` dans ce groupe ; `--db` dans
`instance` ; `--dest`, `--state-dir`, `--keep-*`, `--copy-to`,
`--copy-prune` et `--copy-prune-max` dans `backup`, les réglages de l'outil
de sauvegarde. Les deux derniers ne s'écrivent qu'avec `--copy-to`.

Le seuil d'âge de `odoo_backup --status` suit le calendrier : le plus
grand écart entre deux des 64 prochaines échéances (`systemd-analyze
calendar --iterations`), plus le délai aléatoire et deux heures
(`retention.seuil_age_heures`), noté dans l'état de la base sous
`expected_max_age_hours`. Un seuil qui ne se déduit pas (systemd trop
ancien pour `--iterations`, sortie illisible) laisse le seuil par défaut,
avec un avertissement, et retire de l'état celui d'une installation
précédente. L'installation se
termine par le rappel d'un essai de restauration. La ligne de commande
gagne toujours, `--no-profile` coupe le profil.

`ExecStart` prend l'une de deux formes :

- mode profil, quand un profil est retenu, que le compte de l'unité peut
  le lire (`runuser -u COMPTE -- test -r`) et que l'outil du checkout
  retenu l'applique (lecture statique de son texte, rien n'est exécuté) :
  l'identité détectée (`--service`, `--db`, `--odoo-conf`, `--user`), les
  champs fixés à l'installation (`--dest`, `--state-dir`, `--copy-to`)
  quelle que soit leur origine, les autres (`--keep-*`) seulement s'ils
  sont tapés, puis `--profile <chemin absolu> --profile-required`. La
  sauvegarde relit le profil à chaque passage : une rétention éditée vaut
  dès la nuit suivante, et un profil devenu invalide la fait échouer
  (code 2, visible par `--status`) plutôt que de perdre `--copy-to` en
  silence. Le profil ne se lit sous root que s'il n'est inscriptible ni
  par son groupe ni par les autres, lui comme son dossier, et appartient
  à root, au propriétaire du checkout ou à l'appelant de sudo : un tiers
  ne choisit pas les dossiers où la sauvegarde écrit.
- mode figé dans tous les autres cas : toutes les valeurs écrites, comme
  tapées, et `--no-profile` quand l'outil connaît le profil. Avec un
  profil présent, un avertissement dit qu'une édition du profil demande
  de réinstaller.

`--credential NOM=CHEMIN` transmet un secret que l'outil lancé déclare
(`profil.SECRETS`, groupe `backup`) : le fichier, lu par root sans
suivre de lien, devient un credential systemd de l'unité
(`lib_ops/credentials.py`), chiffré à partir de systemd 250, en clair
0600 root de 247 à 249 avec un avertissement ; avant 247, l'installation
refuse (code 2) avant d'écrire quoi que ce soit. Un secret que le profil
déclare sans `--credential` garde le fichier déjà rangé, celui que cite
l'unité en place d'abord, même si le stockage a changé depuis, et refuse
s'il n'y en a pas ; `--dry-run` n'en lit aucun. Une réinstallation retire
la ligne et le fichier d'un secret que le profil ne déclare plus. Un
fichier rangé par une installation qui échoue avant d'écrire le service
est retiré aussitôt.

`--uninstall` arrête et désactive la minuterie, arrête le service, retire
les trois fichiers et les credentials de l'unité, et recharge systemd ;
les sauvegardes, l'état et le fichier du verrou restent. Les credentials
de l'unité sont ceux que cite le service (sous `/etc/credstore*`, nom
préfixé par l'unité), plus `<dossier>/<unité>.<nom>` pour chaque secret
connu de l'outil et les restes temporaires d'une écriture interrompue :
un fichier qu'aucune unité ne cite plus ne survit pas. Sans root, un
dossier `/etc/credstore*` ne se traverse pas : la simulation montre alors
le `rm` de chaque chemin cité, marqué « s'il existe ». `--dry-run` affiche
les valeurs du profil, les deux unités, les credentials et les commandes,
sans rien écrire ni lire de secret. Root est exigé, sauf
`--dry-run`. `--root DIR` préfixe tous les chemins écrits (un test y met
un dossier temporaire).

Codes de sortie : 0 réussi ; 1 systemctl, systemd-tmpfiles ou
systemd-creds en échec ; 2 refusé avant tout changement.

Bibliothèque standard seulement, sans syntaxe postérieure à Python 3.7.
"""

from __future__ import annotations

import argparse
import datetime
import grp
import os
import pwd
import re
import shutil
import stat
import sys
import tempfile
import types

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.database import odoo_backup  # noqa: E402
from script.lib_ops import (  # noqa: E402
    credentials,
    lock,
    profil,
    report,
    retention,
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
CODE_ECHEC = 1
CODE_REFUS = 2

# Groupe des réglages de cet outil dans un profil de production
# (`lib_ops/profil.py`).
GROUPE = "backup_timer"
# Groupe de l'outil que lance l'unité : ses secrets deviennent des
# credentials de l'unité.
GROUPE_OUTIL = "backup"

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
# Texte que porte un outil qui applique le profil, et accepte donc ses
# méta-options : elles viennent de `lib_ops/profil.py` du même checkout,
# qui doit porter `--profile-required` pour le mode profil.
MARQUE_PROFIL = "profil.analyser("
BIBLIOTHEQUE_PROFIL = os.path.join("script", "lib_ops", "profil.py")
MARQUE_REQUIS = '"--profile-required"'
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


def _montrer(valeur):
    """`valeur` telle qu'un message d'erreur peut la citer : entre
    apostrophes et échappée si elle porte un caractère de contrôle."""
    return repr(valeur) if RE_CONTROLE.search(valeur) else valeur


def type_calendrier(valeur):
    """Type argparse de `--on-calendar` : la forme de `RE_CALENDRIER`, sans
    caractère de contrôle. Le profil passe par le même contrôle ;
    `systemd-analyze calendar` tranche ensuite à l'installation."""
    if RE_CONTROLE.search(valeur) or not RE_CALENDRIER.fullmatch(valeur):
        raise argparse.ArgumentTypeError(
            t("Invalid OnCalendar value: {value}").format(
                value=_montrer(valeur)
            )
        )
    return valeur


def type_delai(valeur):
    """Type argparse de `--randomized-delay` : la forme de `RE_DUREE`, sans
    caractère de contrôle."""
    if RE_CONTROLE.search(valeur) or not RE_DUREE.fullmatch(valeur):
        raise argparse.ArgumentTypeError(
            t("Invalid RandomizedDelaySec value: {value}").format(
                value=_montrer(valeur)
            )
        )
    return valeur


def type_credential(valeur):
    """Type argparse de `--credential NOM=CHEMIN` : (nom, chemin absolu).
    Le fichier n'est pas lu ici."""
    nom, egal, chemin = valeur.partition("=")
    if (
        not egal
        or not credentials.nom_valide(nom)
        or not chemin
        or RE_CONTROLE.search(chemin)
    ):
        raise argparse.ArgumentTypeError(
            t("expected NAME=PATH: {value}").format(value=_montrer(valeur))
        )
    return nom, os.path.abspath(chemin)


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
    """(service, minuterie) de la sauvegarde de `base`
    (`systemd.unites_sauvegarde`, que `odoo_backup --status` lit aussi)."""
    return systemd.unites_sauvegarde(base)


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


def contenu_service(base, utilisateur, groupe, checkout, argv, lignes=()):
    """Le texte du service ; `lignes` sont les `LoadCredential*=`."""
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
        ]
        + list(lignes)
        + ["ExecStart=" + ligne_execstart(argv), ""]
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


def _contient(chemin, marque):
    """True si le fichier `chemin` contient `marque` ; False s'il est
    illisible."""
    try:
        with open(chemin, encoding="utf-8", errors="replace") as fichier:
            return marque in fichier.read()
    except OSError:
        return False


def outil_lit_le_profil(checkout):
    """True si l'outil de `checkout` applique le profil de production
    (`MARQUE_PROFIL` dans son texte). Lecture statique, rien n'est
    exécuté ; un outil illisible ou antérieur au profil rend False, et ne
    reçoit pas une option qu'il refuserait."""
    return _contient(os.path.join(checkout, OUTIL), MARQUE_PROFIL)


def outil_exige_le_profil(checkout):
    """True si l'outil de `checkout` applique le profil ET que la
    bibliothèque du même checkout connaît `--profile-required` : le mode
    profil ne lui écrit rien qu'il refuserait. Lecture statique."""
    return outil_lit_le_profil(checkout) and _contient(
        os.path.join(checkout, BIBLIOTHEQUE_PROFIL), MARQUE_REQUIS
    )


# Les champs des réglages de la sauvegarde écrits à l'installation quelle
# que soit leur origine (`profil.INSTALLATION`), puis ceux que l'outil
# relit dans le profil à chaque passage : écrits seulement s'ils sont tapés.
OPTIONS_INSTALLATION = (("dest", "--dest"), ("state_dir", "--state-dir"))
OPTIONS_DIRECTES = (
    ("keep_daily", "--keep-daily"),
    ("keep_weekly", "--keep-weekly"),
    ("keep_monthly", "--keep-monthly"),
    ("keep_recent_days", "--keep-recent-days"),
)


# Les réglages de la copie hors site, écrits avec `--copy-to` seulement :
# sans destination, ils ne veulent rien dire. Même règle que
# OPTIONS_DIRECTES en mode profil.
OPTIONS_COPIE = (
    ("copy_prune", "--copy-prune"),
    ("copy_prune_max", "--copy-prune-max"),
)


def _valeur_option(args, dest):
    if dest in ("dest", "state_dir"):
        return os.path.abspath(getattr(args, dest))
    return str(getattr(args, dest))


def argv_outil(
    args, plan, checkout, python, sans_profil=False, profil_abs=None
):
    """La commande de sauvegarde.

    Sans `profil_abs` (mode figé), toutes les valeurs sont écrites ;
    `sans_profil` ajoute `--no-profile`. Avec `profil_abs` (mode profil),
    l'identité, les champs d'installation et les seuls champs directs tapés
    sur la ligne de commande sont écrits, puis `--profile <profil_abs>
    --profile-required`."""
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
    ]
    application = getattr(args, "profil", None)
    for dest, option in OPTIONS_INSTALLATION:
        argv += [option, _valeur_option(args, dest)]
    for dest, option in OPTIONS_DIRECTES:
        if (
            profil_abs is None
            or application is None
            or application.origine(dest) == "cli"
        ):
            argv += [option, _valeur_option(args, dest)]
    if args.copy_to:
        argv += ["--copy-to", args.copy_to]
        for dest, option in OPTIONS_COPIE:
            if profil_abs is not None and (
                application is None or application.origine(dest) != "cli"
            ):
                continue
            if dest == "copy_prune" and args.copy_prune:
                argv.append(option)
            elif dest == "copy_prune_max" and args.copy_prune:
                argv += [option, str(args.copy_prune_max)]
    if profil_abs is not None:
        argv += ["--profile", profil_abs, "--profile-required"]
    elif sans_profil:
        argv.append("--no-profile")
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


# Les échéances lues pour mesurer l'écart entre deux sauvegardes : de quoi
# couvrir une semaine même à plusieurs passages par jour.
ITERATIONS = 64
# Une échéance de `systemd-analyze calendar --iterations` : `Next elapse:`,
# puis `Iter. #N:` ou `Iteration #N:` selon la version de systemd, suivis du
# jour, de la date et de l'heure en heure locale ; la ligne `(in UTC):` qui
# suit, absente quand le fuseau est UTC, est ignorée.
RE_ECHEANCE = re.compile(
    r"^\s*(?:Next elapse|Iter(?:\.|ation) #\d+):\s+\S+\s+"
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",
    re.M,
)
# Unités de RandomizedDelaySec, en secondes (systemd.time(7)).
UNITES_DUREE = {
    "": 1,
    "s": 1,
    "sec": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "w": 604800,
    "week": 604800,
    "weeks": 604800,
}
RE_MORCEAU_DUREE = re.compile(r"([0-9]+) ?([a-z]*)")


def echeances(sortie):
    """Les datetime (heure locale, naïfs) des échéances que liste
    `systemd-analyze calendar --iterations`."""
    instants = []
    for texte in RE_ECHEANCE.findall(sortie or ""):
        try:
            instants.append(
                datetime.datetime.strptime(texte, "%Y-%m-%d %H:%M:%S")
            )
        except ValueError:
            continue
    return instants


def duree_secondes(texte):
    """Les secondes d'une durée systemd (`30min`, `1h 30min`), ou None pour
    une unité inconnue."""
    total = 0
    for nombre, unite in RE_MORCEAU_DUREE.findall(texte or ""):
        if unite not in UNITES_DUREE:
            return None
        total += int(nombre) * UNITES_DUREE[unite]
    return total


def seuil_du_calendrier(calendrier, delai, systeme):
    """Le seuil d'âge de `--status`, en heures, déduit des échéances de
    `calendrier` (`retention.seuil_age_heures`, délai aléatoire compris),
    ou None quand systemd-analyze n'en liste pas deux (absent, trop ancien
    pour `--iterations`, ou sortie illisible)."""
    code, sortie = systeme.lanceur(
        [
            "systemd-analyze",
            "calendar",
            f"--iterations={ITERATIONS}",
            "--",
            calendrier,
        ],
        30,
    )
    if code != 0:
        return None
    return retention.seuil_age_heures(
        echeances(sortie), duree_secondes(delai) or 0
    )


def noter_seuil(args, plan, heures, systeme, rapport):
    """Écrit `heures` dans l'état de la base, sous `odoo_backup.CLE_SEUIL`,
    au compte de l'unité ; None y efface le seuil d'une installation
    précédente (`--status` reprend AGE_MAX). Un échec n'est qu'un
    avertissement : `--status` garde alors son seuil par défaut. Après un
    retrait de la minuterie, la clé reste, et `--status` ne la lit plus tant
    que la minuterie manque. Rend True si l'état est écrit."""
    etat_dir = systeme.chemin(os.path.abspath(args.state_dir))
    cible = odoo_backup.Cible(
        base=plan.base,
        utilisateur=plan.utilisateur,
        etat_dir=etat_dir,
        dossier_etat=os.path.join(etat_dir, plan.base),
        root=systeme.euid() == 0,
    )
    try:
        odoo_backup.ecrire_etat(
            cible, systeme, {odoo_backup.CLE_SEUIL: heures}
        )
    except (OSError, KeyError) as err:
        rapport.attn(
            t("Cannot record the state in {path}: {error}").format(
                path=cible.dossier_etat, error=err
            )
        )
        return False
    return True


def _effacer_seuil(args, plan, systeme, rapport):
    """Efface le seuil noté par une installation précédente quand le
    calendrier n'en donne pas : `--status` ne garde pas celui d'un autre
    calendrier. Sans état, rien n'est écrit."""
    etat_dir = systeme.chemin(os.path.abspath(args.state_dir))
    chemin = odoo_backup.chemin_etat(etat_dir, plan.base)
    if os.path.lexists(chemin):
        noter_seuil(args, plan, None, systeme, rapport)


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


def compte_lit(plan, chemin, systeme):
    """True si le compte de l'unité peut lire `chemin` (`runuser -u COMPTE
    -- test -r`), False sinon, None hors root (non vérifié)."""
    if systeme.euid() != 0:
        return None
    code, _sortie = systeme.lanceur(
        ["runuser", "-u", plan.utilisateur, "--", "test", "-r", chemin], 30
    )
    return code == 0


def choisir_mode(args, plan, checkout, systeme, rapport):
    """Le chemin absolu du profil pour le mode profil, ou None pour le mode
    figé ; un ATTN dit pourquoi un profil présent n'est pas relu par la
    sauvegarde planifiée."""
    application = getattr(args, "profil", None)
    if application is None or not application.actif:
        return None
    chemin = os.path.abspath(application.chemin)
    if not outil_exige_le_profil(checkout):
        rapport.attn(
            t(
                "The tool of {path} predates the profile: ExecStart holds"
                " every value, and an edit of the profile needs a reinstall."
            ).format(path=checkout)
        )
        return None
    if compte_lit(plan, chemin, systeme) is False:
        rapport.attn(
            t(
                "{user} cannot read the profile {path}: ExecStart holds every"
                " value, and an edit of the profile needs a reinstall."
            ).format(user=plan.utilisateur, path=chemin)
        )
        return None
    return chemin


def secrets_outil():
    """{nom du credential: clé} des secrets de l'outil lancé
    (`profil.SECRETS`, groupe `GROUPE_OUTIL`)."""
    return {
        nom: cle
        for (groupe, cle), nom in profil.SECRETS.items()
        if groupe == GROUPE_OUTIL
    }


def secrets_declares(args):
    """Les noms des secrets de l'outil que le profil retenu déclare (clé
    présente dans le groupe `GROUPE_OUTIL`, référence KeePass ou chemin),
    triés."""
    application = getattr(args, "profil", None)
    document = getattr(application, "document", None) or {}
    groupe = document.get(GROUPE_OUTIL)
    if not isinstance(groupe, dict):
        return []
    return sorted(nom for nom, cle in secrets_outil().items() if cle in groupe)


def texte_unite(chemin):
    """Le texte d'une unité marquée, "" si elle manque ou ne porte pas la
    marque : seules les lignes écrites ici désignent des fichiers à
    retirer."""
    if not porte_la_marque(chemin):
        return ""
    try:
        with open(chemin, encoding="utf-8", errors="replace") as fichier:
            return fichier.read()
    except OSError:
        return ""


def credentials_de_l_unite(unite, texte, systeme, garder=()):
    """[(chemin réel, certain)] des fichiers de credential de l'unité à
    retirer, hors des chemins (non préfixés) de `garder`.

    Candidats : les chemins que cite le texte d'unité marqué `texte`
    (`credentials.chemins_a_retirer`), `<dossier>/<unité>.<nom>` pour
    chaque secret connu de l'outil, et les restes temporaires de ces
    fichiers. Un candidat absent est écarté. `certain` est faux quand son
    existence ne se vérifie pas (EACCES, hors root) : seul un chemin cité
    est alors rendu, la simulation le montre « s'il existe »."""
    cites = credentials.chemins_a_retirer(texte, unite)
    connus = credentials.fichiers_de_l_unite(unite, sorted(secrets_outil()))
    trouves, vus = [], set()
    for final in cites + connus:
        if final in garder or final in vus:
            continue
        vus.add(final)
        reel = systeme.chemin(final)
        etat = credentials.present(reel)
        if etat or (etat is None and final in cites):
            trouves.append((reel, bool(etat)))
    bases = sorted({os.path.basename(final) for final in cites + connus})
    for dossier in credentials.DOSSIERS:
        for reste in credentials.restes(systeme.chemin(dossier), bases):
            trouves.append((reste, True))
    return trouves


def preparer_credentials(args, unite, chemin_service, systeme, rapport):
    """Les credentials de l'unité, vérifiés avant toute écriture :
    `(lignes, a_ranger, a_retirer)`.

    `a_ranger` : [(nom, chemin, réel, stockage, donnees, fourni)],
    `donnees` None quand le fichier déjà rangé est gardé ou en simulation
    (rien n'est lu), `fourni` vrai pour un secret donné par `--credential`.
    Un secret sans `--credential` garde d'abord le fichier que cite
    l'unité en place, avec sa directive, même si le stockage choisi
    aujourd'hui diffère (systemd mis à jour, `systemd-creds` installé
    depuis) ; sinon celui du stockage d'aujourd'hui.
    `a_retirer` : [(réel, certain)] de `credentials_de_l_unite`, les
    fichiers de l'unité qu'une réinstallation retire. Lève
    service.Refus."""
    fournis = dict(args.credential or ())
    noms = sorted(set(secrets_declares(args)) | set(fournis))
    texte = texte_unite(chemin_service)
    a_moi = set(credentials.chemins_a_retirer(texte, unite))
    cites = {
        nom: (directive, cite)
        for directive, nom, cite in credentials.lignes_citees(texte)
        if cite in a_moi
        and os.path.basename(cite) == f"{unite}.{nom}"
        and credentials.stockage_cite(directive, None).dossier
        == os.path.dirname(cite)
    }
    lignes, a_ranger, garder, en_clair = [], [], set(), []
    if noms:
        try:
            version, avec_creds = credentials.detecter(systeme.lanceur)
            stockage = credentials.choisir_stockage(version, avec_creds)
        except credentials.ErreurCredential as err:
            raise service.Refus(err.modele, **err.valeurs)
        for nom in noms:
            utilise = stockage
            final = credentials.chemin(stockage, unite, nom)
            ancien = cites.get(nom) if nom not in fournis else None
            if ancien and (
                ancien[0] == "LoadCredential"
                or version >= credentials.VERSION_CHIFFREE
            ):
                reel_ancien = systeme.chemin(ancien[1])
                if credentials.present(reel_ancien) is not False:
                    utilise = credentials.stockage_cite(ancien[0], version)
                    final = ancien[1]
            reel = systeme.chemin(final)
            donnees = None
            if nom in fournis and not args.dry_run:
                try:
                    donnees = credentials.lire_secret(fournis[nom])
                except credentials.ErreurCredential as err:
                    raise service.Refus(err.modele, **err.valeurs)
            elif (
                nom not in fournis
                and not args.dry_run
                and not os.path.isfile(reel)
            ):
                raise service.Refus(
                    service.N_(
                        "The profile declares the secret {name}, but no"
                        " --credential gives it and {path} does not exist."
                    ),
                    name=nom,
                    path=final,
                )
            if not utilise.chiffre:
                en_clair.append((nom, final))
            lignes.append(credentials.ligne_unite(utilise, unite, nom))
            a_ranger.append(
                (nom, final, reel, utilise, donnees, nom in fournis)
            )
            garder.add(final)
        if en_clair and not stockage.chiffre:
            rapport.attn(
                t(
                    "Credentials stored in clear at rest in {path}, readable"
                    " by root only (systemd {version} < 250, or no"
                    " systemd-creds)."
                ).format(path=stockage.dossier, version=version)
            )
            en_clair = []
        # Un fichier en clair gardé alors que l'hôte sait chiffrer.
        for nom, final in en_clair:
            rapport.attn(
                t(
                    "The stored credential {path} stays in clear at rest:"
                    " give --credential {name}=PATH to store it encrypted."
                ).format(path=final, name=nom)
            )
    a_retirer = credentials_de_l_unite(unite, texte, systeme, garder)
    return lignes, a_ranger, a_retirer


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
    profil_abs = choisir_mode(args, plan, checkout, systeme, rapport)
    argv = argv_outil(
        args,
        plan,
        checkout,
        python,
        outil_lit_le_profil(checkout),
        profil_abs=profil_abs,
    )
    try:
        ligne_execstart(argv)
    except ValueError as err:
        raise service.Refus(
            service.N_("Control character in an argument: {value}"),
            value=repr(str(err)),
        )
    verifier_acces(plan, checkout, python, systeme, rapport)
    lignes, a_ranger, a_retirer = preparer_credentials(
        args, unites[0], chemins[0], systeme, rapport
    )
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
    seuil = seuil_du_calendrier(
        args.on_calendar, args.randomized_delay, systeme
    )
    if seuil is None:
        rapport.attn(
            t(
                "The age threshold of --status is not derived from {value}"
                " (systemd-analyze calendar --iterations unavailable or"
                " unreadable): it stays {hours} h unless --max-age is given."
            ).format(value=args.on_calendar, hours=odoo_backup.AGE_MAX)
        )
    textes = [
        contenu_service(
            plan.base, plan.utilisateur, groupe, checkout, argv, lignes
        ),
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
        profil=profil_abs,
        credentials=a_ranger,
        credentials_a_retirer=a_retirer,
        seuil=seuil,
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
    for (
        nom,
        _final,
        reel,
        stockage,
        _donnees,
        fourni,
    ) in installation.credentials:
        etat = False if fourni else credentials.present(reel)
        if etat:
            note = t("(stored file kept)")
        elif etat is None:
            note = t("(stored file kept if present)")
        else:
            note = t("(provided at installation)")
        rapport.sim(_commande_credential(stockage, nom, reel) + "  " + note)
    for chemin, texte in zip(
        installation.chemins + [installation.tmpfiles],
        installation.textes + [installation.texte_tmpfiles],
    ):
        rapport.sim(chemin)
        for ligne in texte.splitlines():
            rapport.texte("      " + ligne)
    _simuler_retraits(installation.credentials_a_retirer, rapport)
    if installation.seuil is not None:
        rapport.sim(
            t("state.json: {key} = {hours}").format(
                key=odoo_backup.CLE_SEUIL, hours=installation.seuil
            )
        )
    rapport.sim(
        service.joindre(
            ["systemd-tmpfiles", "--create", "--", installation.tmpfiles]
        )
    )
    rapport.sim("systemctl daemon-reload")
    rapport.sim(f"systemctl enable --now {installation.unites[1]}")
    rapport.ok(t("Simulation finished: nothing was written."))
    return CODE_OK


def _simuler_retraits(credentials_a_retirer, rapport):
    """Montre le `rm` de chaque `(réel, certain)`, « s'il existe » quand
    son existence ne se vérifie pas sans root."""
    for reel, certain in credentials_a_retirer:
        options = ["-r", "--"] if _est_dossier(reel) else ["--"]
        commande = service.joindre(["rm"] + options + [reel])
        if not certain:
            commande += "  " + t("(if present)")
        rapport.sim(commande)


def _est_dossier(chemin):
    """True si `chemin` est un dossier, sans suivre de lien."""
    try:
        return stat.S_ISDIR(os.lstat(chemin).st_mode)
    except OSError:
        return False


def _commande_credential(stockage, nom, reel):
    """La commande montrée pour ranger le credential `nom` : le secret
    passe sur l'entrée standard, jamais sur la ligne."""
    if stockage.chiffre:
        return service.joindre(
            [
                "systemd-creds",
                "encrypt",
                f"--name={nom}",
                "--with-key=host",
                "-",
                reel,
            ]
        )
    return service.joindre(["install", "-m", "0600", "/dev/stdin", reel])


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
    # Un credential créé ici n'est cité que par le service : tant que le
    # service n'est pas écrit, aucune désinstallation ne le retrouverait
    # par l'unité, d'où son retrait sur tout échec d'ici là.
    crees = []
    if not _ranger_credentials(installation, systeme, rapport, crees):
        _retirer(crees, rapport)
        return CODE_ECHEC
    for chemin, texte in zip(installation.chemins, installation.textes):
        try:
            ecrire_unite(chemin, texte)
        except OSError as err:
            rapport.erreur(
                t("Cannot write {path}: {error}").format(
                    path=chemin, error=err
                )
            )
            if chemin == installation.chemins[0]:
                _retirer(crees, rapport)
            return CODE_ECHEC
        rapport.ok(t("Written: {path}").format(path=chemin))
    # Le service écrit ne cite plus ces fichiers : ils partent avant toute
    # étape qui pourrait encore échouer.
    if not _retirer(
        [reel for reel, _certain in installation.credentials_a_retirer],
        rapport,
    ):
        return CODE_ECHEC
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
    code = CODE_OK
    if installation.seuil is None:
        _effacer_seuil(args, plan, systeme, rapport)
    elif noter_seuil(args, plan, installation.seuil, systeme, rapport):
        rapport.ok(
            t(
                "--status fails when the last backup is older than"
                " {hours} h (derived from the schedule)."
            ).format(hours=installation.seuil)
        )
    rapport.detail(f"systemctl list-timers {unite_minuterie}")
    rapport.detail(f"systemctl start {unite_service}")
    rapport.detail(f"journalctl -u {unite_service}")
    rapport.detail(
        t(
            "Run a test restore once the first backup is written: {command}"
        ).format(
            command=service.joindre(
                [
                    "sudo",
                    os.path.join("script", "database", "odoo_backup.py"),
                    "--test-restore",
                    "--db",
                    plan.base,
                ]
            )
        )
    )
    return code


def _ranger_credentials(installation, systeme, rapport, crees):
    """Range chaque secret fourni dans son fichier de credential, avant les
    unités qui le citent ; un secret sans données garde le fichier rangé.
    Ajoute à `crees` chaque fichier qui n'existait pas avant, y compris
    celui en cours d'écriture : l'appelant les retire si l'installation
    échoue avant d'écrire le service. False, message écrit, sur un
    échec."""
    for (
        nom,
        _final,
        reel,
        stockage,
        donnees,
        _fourni,
    ) in installation.credentials:
        if donnees is None:
            rapport.ok(t("Stored credential kept: {path}").format(path=reel))
            continue
        if not os.path.lexists(reel):
            crees.append(reel)
        try:
            credentials.preparer_dossier(os.path.dirname(reel))
            if stockage.chiffre:
                credentials.chiffrer(
                    reel, nom, donnees, systeme.lanceur_entree
                )
            else:
                credentials.ecrire_clair(reel, donnees)
        except credentials.ErreurCredential as err:
            rapport.fail(err.message(t))
            return False
        except OSError as err:
            rapport.fail(
                t("Cannot write {path}: {error}").format(path=reel, error=err)
            )
            return False
        rapport.ok(t("Credential stored: {path}").format(path=reel))
    return True


def _retirer(chemins, rapport):
    """Retire chaque fichier de `chemins`, ou dossier (le reste d'un
    chiffrement interrompu), sans suivre de lien ; False, message écrit, si
    l'un résiste."""
    reussi = True
    for chemin in chemins:
        try:
            if _est_dossier(chemin):
                shutil.rmtree(chemin)
            else:
                os.remove(chemin)
            rapport.ok(t("Removed: {path}").format(path=chemin))
        except FileNotFoundError:
            continue
        except OSError as err:
            rapport.fail(
                t("Cannot delete {path}: {error}").format(
                    path=chemin, error=err
                )
            )
            reussi = False
    return reussi


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
    a_retirer = credentials_de_l_unite(
        unite_service, texte_unite(chemins[0]), systeme
    )
    presents = [c for c in chemins if os.path.lexists(c)]
    if not presents and not a_retirer:
        rapport.ok(
            t("Nothing to remove for {database}.").format(database=base)
        )
        return CODE_OK
    if not presents:
        # Des credentials sans unité (une installation interrompue) : rien
        # à arrêter ni à recharger, systemctl échouerait sur une unité
        # inconnue.
        if args.dry_run:
            _simuler_retraits(a_retirer, rapport)
            rapport.ok(t("Simulation finished: nothing was written."))
            return CODE_OK
        if not _retirer([reel for reel, _certain in a_retirer], rapport):
            return CODE_ECHEC
        return CODE_OK
    if args.dry_run:
        rapport.sim(f"systemctl disable --now {unite_minuterie}")
        rapport.sim(f"systemctl stop {unite_service}")
        for chemin in presents:
            rapport.sim(service.joindre(["rm", "--", chemin]))
        _simuler_retraits(a_retirer, rapport)
        rapport.sim("systemctl daemon-reload")
        rapport.ok(t("Simulation finished: nothing was written."))
        return CODE_OK
    code = CODE_OK
    if not _systemctl(systeme, rapport, "disable", "--now", unite_minuterie):
        code = CODE_ECHEC
    if not _systemctl(systeme, rapport, "stop", unite_service):
        code = CODE_ECHEC
    if not _retirer(
        presents + [reel for reel, _certain in a_retirer], rapport
    ):
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


def construire_parseur():
    """Le parser de la ligne de commande, sans rien analyser ni lancer :
    le catalogue des réglages en tire les métadonnées des options."""
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
        "--copy-prune",
        action="store_true",
        help=t(
            "With --copy-to: also apply the retention to the backups at the"
            " destination, except those kept locally; only this tool's names"
            " for this database."
        ),
    )
    parser.add_argument(
        "--copy-prune-max",
        type=types_.entier,
        default=odoo_backup.SUPPRESSIONS_COPIE_MAX,
        help=t(
            "--copy-prune deletes at most this many backups per run;"
            " default: {value}."
        ).format(value=odoo_backup.SUPPRESSIONS_COPIE_MAX),
    )
    parser.add_argument(
        "--on-calendar",
        type=type_calendrier,
        default=CALENDRIER,
        help=t("When the backup runs (OnCalendar); default: {value}.").format(
            value=CALENDRIER
        ),
    )
    parser.add_argument(
        "--randomized-delay",
        type=type_delai,
        default=DELAI_ALEATOIRE,
        help=t("RandomizedDelaySec of the timer; default: {value}.").format(
            value=DELAI_ALEATOIRE
        ),
    )
    parser.add_argument(
        "--credential",
        action="append",
        type=type_credential,
        metavar="NAME=PATH",
        help=t(
            "Secret NAME of the backup tool, read by root from the file PATH"
            " and stored as a systemd credential of the unit, never on a"
            " command line; repeatable."
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
    return parser


def valider(parser, args):
    """Contrôles d'après analyse, profil déjà posé ; refus par
    `parser.error` (code 2) : un `--credential` doit nommer, une seule
    fois, un secret de l'outil lancé. Les types de `--on-calendar` et
    `--randomized-delay` refusent déjà une forme invalide, et le reste se
    vérifie à l'installation."""
    if args.copy_prune_max < 1:
        parser.error(t("--copy-prune-max must be at least 1."))
    vus = set()
    connus = secrets_outil()
    for nom, _chemin in args.credential or ():
        if nom not in connus:
            parser.error(
                t(
                    "--credential {name}: not a secret of the backup tool"
                    " (known: {names})."
                ).format(name=nom, names=", ".join(sorted(connus)) or "-")
            )
        if nom in vus:
            parser.error(
                t("--credential {name} is given twice.").format(name=nom)
            )
        vus.add(nom)


def analyser(argv=None, lanceur=None):
    """Analyse `argv` avec le profil de l'instance, puis le valide.

    Sans `lanceur`, l'unité n'est jamais devinée pour trouver le profil :
    seuls `--profile` et `--service` le désignent. `args.profil` porte ce
    que le profil a posé ou écarté."""
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


def main(argv=None, systeme=None, rapport=None):
    # Le système se construit après l'analyse (`--verbose`, `--root`) : la
    # devinette de l'unité du profil passe alors par le lanceur par défaut.
    args = analyser(
        argv,
        lanceur=systeme.lanceur if systeme is not None else systemd.lancer,
    )
    systeme = systeme or Systeme(verbeux=args.verbose, racine=args.root)
    rapport = rapport or report.Rapport()
    if systeme.euid() != 0 and not args.dry_run:
        rapport.erreur(t("Root is required (sudo), except with --dry-run."))
        return CODE_REFUS
    if args.uninstall and args.db:
        profil.afficher(args.profil, rapport, t)
        return desinstaller(args, args.db, systeme, rapport)
    plan = types.SimpleNamespace()
    try:
        service.detecter_instance(args, systeme, RACINE, plan)
    except service.Refus as err:
        rapport.erreur(err.message(t))
        return CODE_REFUS
    origine_base = profil.origine_affichee(
        args.profil, "db", plan.origine_base, t
    )
    rapport.champ(t("Service"), plan.unite)
    rapport.champ(t("Account"), plan.utilisateur)
    rapport.champ(t("Odoo config"), plan.config_path)
    rapport.champ(t("Database"), f"{plan.base} ({origine_base})")
    # Avant les unités et les commandes simulées : ce qui vient du profil
    # se lit avant ce qu'il produit.
    profil.afficher(args.profil, rapport, t)
    if args.uninstall:
        return desinstaller(args, plan.base, systeme, rapport)
    return installer(args, plan, systeme, rapport)


if __name__ == "__main__":
    sys.exit(main())
