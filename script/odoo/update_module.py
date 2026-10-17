#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Mettre à jour des modules installés sur une instance servie par systemd.

Le déroulé
----------
1. Détection, sans rien arrêter : l'unité (`--service`, sinon celle dont
   WorkingDirectory est ce checkout, sinon la seule active), son compte,
   son dossier, sa ligne de commande et son environnement lus par
   `systemctl show` ; le fichier de configuration, la base, l'adresse
   HTTP, puis les modules, développés sur l'addons_path. Tout ce qui
   manque ou se contredit refuse ici, code 2, le service intact.
2. Root exigé, puis un verrou par base : deux mises à jour de la même
   base ne se chevauchent pas (code 75). Le dossier `image_db` de la
   sauvegarde, s'il manque, est créé ici, au compte de l'unité : un échec
   refuse encore avant l'arrêt (code 2).
3. Arrêt de l'unité. Si le port répond encore, ou si un processus Odoo
   tourne sur la même base hors de l'unité, la mise à jour est refusée
   (code 1), sauf `--force` : deux serveurs sur une base pendant un `-u`
   se disputent son schéma.
4. Sauvegarde, APRÈS l'arrêt pour être cohérente : `odoo_bin.sh db
   --backup` dans le dossier de l'unité, sous son compte, avec ODOO_RC
   pointant sa configuration. Elle s'écrit sous un nom provisoire
   (`.partial.zip`), relu puis renommé : un fichier au nom définitif est
   toujours une sauvegarde complète.
5. Mise à jour : la ligne de commande de l'unité, privée de sa base
   (`-d`, `--database`), suivie de `-c CONFIG -d BASE -u MODULES
   --stop-after-init --no-http --workers=0 --max-cron-threads=0` — le
   `-c` répété garde la mise à jour sur le fichier que la détection et
   la sauvegarde ont lu —, sous le compte de l'unité (`runuser`), HOME
   tiré de passwd. Échec si le
   code est non nul, si le délai est dépassé, ou si une ligne ERROR ou
   CRITICAL paraît dans la sortie ou dans ce qui s'est AJOUTÉ au
   `logfile` configuré — Odoo y écrit au lieu de stderr quand il est
   posé.
6. Redémarrage, si l'unité tournait avant : l'époque est prise AVANT
   `systemctl start`, pour que les erreurs du chargement entrent dans la
   fenêtre lue ensuite ; attente de `active` et du port, une requête HTTP
   qui force le chargement du registre, puis lecture du journal de
   l'unité et du `logfile` depuis cette époque.

L'invariant
-----------
Aucun chemin après l'arrêt ne laisse arrêtée une unité qui tournait : un
`finally` relance le service quelle que soit l'issue, exception comprise.
SIGTERM et SIGHUP sont convertis en exception pour y passer aussi, mais
seulement tant que le programme est « armé » : le `finally` désarme en
premier, par une simple affectation, si bien qu'un signal arrivé à ce
moment ne peut plus en sortir avant la relance. Une unité dont l'état
avant l'arrêt est inconnu n'est pas arrêtée (code 2). Le rapport écrit au
mieux : un terminal raccroché ne fait pas lever la relance.

Le processus de mise à jour tourne dans sa propre session : un Ctrl-C du
terminal n'atteint que ce programme, qui demande s'il faut interrompre ;
oui arrête le groupe du processus (TERM, puis KILL après un délai de
grâce), ATTEND sa fin, et seulement ensuite relance le service. Ce qui
est attendu, ce sont les processus ; la session PostgreSQL d'un `-u` tué
peut, elle, finir son instruction en cours et garder ses verrous jusqu'à
ce que le serveur remarque la déconnexion. Le redémarrage peut donc
attendre ces verrous ; un avertissement le dit.

Rien n'est restauré : ce programme ne remplace pas le code, il n'a donc
rien à remettre. La sauvegarde est là pour une restauration décidée par
une personne.

Codes de sortie : 0 réussi ; 1 mise à jour en échec, service relancé ;
2 refusé avant tout arrêt ; 75 verrou pris ; 130 interrompu.

`--dry-run` fait toute la détection, affiche les commandes exactes, et
n'arrête, n'écrit ni ne démarre rien ; il ne demande ni root ni verrou.

Bibliothèque standard seulement, sans syntaxe postérieure à Python 3.7 :
le programme se lance aussi par le python3 d'un serveur de production.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import grp
import os
import pwd
import re
import shlex
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.analyse import lib_analyse  # noqa: E402
from script.lib_ops import lock, odoo_instance, report, systemd  # noqa: E402
from script.odoo import warmup_http  # noqa: E402

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
CODE_VERROU = 75
CODE_INTERROMPU = 130

DELAI_MISE_A_JOUR = 1800
DELAI_DEMARRAGE = 90
DELAI_SONDE = 120
# Délai de grâce entre TERM et KILL du groupe de la mise à jour.
GRACE_KILL = 30
INTERVALLE_DEMARRAGE = 2
DOSSIER_JOURNAUX = "/var/log/erplibre"
# Lignes de fin de journal montrées quand Odoo sort en erreur.
LIGNES_DE_FIN = 15
# Ajouté au nom de la sauvegarde pendant son écriture ; Odoo y ajoute .zip.
SUFFIXE_PARTIEL = ".partial"

RE_UTILISATEUR = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_.-]*")

# L'issue d'un processus long : son code, s'il a été tué pour délai
# dépassé, s'il a été interrompu à la demande.
Issue = collections.namedtuple("Issue", "code tue interrompu")


class Refus(Exception):
    """Refus avant tout arrêt : le message dit ce qui manque."""


class Interruption(BaseException):
    """SIGTERM ou SIGHUP reçu. Hérite de BaseException comme
    KeyboardInterrupt : un `except Exception` d'étape ne l'avale pas."""


def joindre(argv):
    """La commande telle qu'on la taperait dans un shell."""
    return " ".join(shlex.quote(str(a)) for a in argv)


class Systeme:
    """Les effets de bord du programme, regroupés.

    Un test en dérive une classe qui remplace chaque méthode : aucune
    commande réelle n'est alors lancée, aucune horloge réelle lue.
    """

    def __init__(
        self,
        verbeux=False,
        dossier_verrou=None,
        grace=GRACE_KILL,
        interactif=None,
        demander=None,
    ):
        self.verbeux = verbeux
        self.dossier_verrou = dossier_verrou
        self.grace = grace
        self.interactif = (
            sys.stdin.isatty() if interactif is None else interactif
        )
        self.demander = demander or self._demander_interruption
        # Tant que faux, les gestionnaires de `proteger_signaux` ne lèvent
        # rien : le `finally` d'`executer` le remet à False avant la relance.
        self.arme = False

    def _tracer(self, argv):
        if self.verbeux:
            print(f"+ {joindre(argv)}", file=sys.stderr, flush=True)

    def lanceur(self, argv, timeout=60):
        """Le lanceur passé à `systemd` : (code, sortie), ne lève pas."""
        self._tracer(argv)
        return systemd.lancer(argv, timeout)

    def journal(self, unite, epoque):
        return systemd.journal_depuis(unite, epoque, self.lanceur)

    def euid(self):
        return os.geteuid()

    def utilisateur_courant(self):
        try:
            return pwd.getpwuid(os.geteuid()).pw_name
        except KeyError:
            return str(os.geteuid())

    def home(self, utilisateur):
        """Le dossier personnel de passwd. `runuser -u` garde celui de
        root, où Odoo poserait son data_dir et chercherait le filestore."""
        try:
            return pwd.getpwnam(utilisateur).pw_dir
        except KeyError:
            return "/nonexistent"

    def port_ecoute(self, hote, port):
        try:
            with socket.create_connection((hote, port), timeout=1):
                return True
        except OSError:
            return False

    def processus(self):
        return odoo_instance.lister_processus("/proc")

    def pids_exclus(self):
        return (os.getpid(), os.getppid())

    def maintenant(self):
        return time.time()

    def dormir(self, secondes):
        time.sleep(secondes)

    def sonder(self, cible, delai):
        return warmup_http.sonder(cible, delai_total=delai)

    def verrou(self, base):
        return lock.Verrou(f"erplibre-db-{base}", self.dossier_verrou)

    def inscriptible(self, dossier, utilisateur):
        return dossier_inscriptible(dossier, utilisateur)

    def creer_dossier(self, dossier, utilisateur):
        """Crée `dossier` (mode 0750) et le donne au compte `utilisateur`,
        groupe principal de passwd compris. Lève OSError ou KeyError ; un
        dossier créé dont le chown échoue est retiré, pour qu'il ne reste
        pas un dossier de root où le compte ne peut pas écrire."""
        compte = pwd.getpwnam(utilisateur)
        os.mkdir(dossier, 0o750)
        try:
            os.chown(dossier, compte.pw_uid, compte.pw_gid)
        except OSError:
            os.rmdir(dossier)
            raise

    def proteger_signaux(self):
        """Arme le programme : SIGTERM et SIGHUP lèvent Interruption, SIGINT
        KeyboardInterrupt. Rend la restauration.

        Chaque gestionnaire lit `self.arme` au moment où il s'exécute :
        désarmé, il ne lève rien. CPython exécute un gestionnaire entre deux
        instructions, parfois après l'arrivée du signal ; un signal arrivé
        avant le désarmement mais traité après est donc ignoré lui aussi.
        """

        def lever(numero, _frame):
            if self.arme:
                raise Interruption(numero)

        def lever_ctrl_c(_numero, _frame):
            if self.arme:
                raise KeyboardInterrupt

        self.arme = True
        return self._poser(
            {
                signal.SIGINT: lever_ctrl_c,
                signal.SIGTERM: lever,
                signal.SIGHUP: lever,
            }
        )

    def ignorer_interruptions(self):
        """Ignore SIGINT, SIGTERM et SIGHUP. Rend la restauration.

        Posé pendant le redémarrage : interrompre ce qui relance le
        service laisserait le service arrêté.
        """
        ignorer = signal.SIG_IGN
        return self._poser(
            {
                signal.SIGINT: ignorer,
                signal.SIGTERM: ignorer,
                signal.SIGHUP: ignorer,
            }
        )

    @staticmethod
    def _poser(gestionnaires):
        anciens = {}
        try:
            for numero, gestionnaire in gestionnaires.items():
                anciens[numero] = signal.signal(numero, gestionnaire)
        except ValueError:
            # Hors du fil principal, les signaux ne se posent pas.
            pass

        def restaurer():
            for numero, ancien in anciens.items():
                signal.signal(numero, ancien)

        return restaurer

    def _demander_interruption(self):
        """Oui sur o/oui/y/yes, un second Ctrl-C ou la fin de l'entrée."""
        try:
            reponse = input(
                "\n"
                + t(
                    "Interrupt the update? Odoo will be stopped, then the"
                    " service restarted. [y/N] "
                )
            )
        except (EOFError, KeyboardInterrupt):
            return True
        return reponse.strip().lower() in ("o", "oui", "y", "yes")

    def lancer_long(self, argv, cwd, env, journal, delai):
        """Lance `argv` dans sa propre session, sortie ajoutée à `journal`.

        Rend une Issue. Au-delà de `delai` secondes, le groupe est tué et
        `tue` est vrai. Un Ctrl-C pose la question (sur un terminal) ; oui,
        ou pas de terminal, arrête le groupe et rend `interrompu`. Toute
        autre exception arrête le groupe, attend sa fin, puis remonte.
        """
        self._tracer(argv)
        with open(journal, "ab") as sortie:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=sortie,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        fin = time.monotonic() + delai
        try:
            while True:
                reste = fin - time.monotonic()
                if reste <= 0:
                    self._terminer(proc)
                    return Issue(proc.returncode, True, False)
                try:
                    code = proc.wait(timeout=min(reste, 1.0))
                    return Issue(code, False, False)
                except subprocess.TimeoutExpired:
                    continue
                except KeyboardInterrupt:
                    if self.interactif and not self.demander():
                        print(t("Resuming."), flush=True)
                        continue
                    self._terminer(proc)
                    return Issue(proc.returncode, False, True)
        except BaseException:
            self._terminer(proc)
            raise

    def _terminer(self, proc):
        """TERM au groupe, KILL après le délai de grâce, puis ATTEND.

        Les interruptions reçues pendant l'attente sont ignorées : rendre
        la main avant la fin du processus laisserait un `-u` en cours
        pendant que le service redémarre.
        """
        if proc.poll() is not None:
            return
        self._signaler(proc, signal.SIGTERM)
        limite = time.monotonic() + self.grace
        while proc.poll() is None:
            try:
                proc.wait(timeout=max(0.1, limite - time.monotonic()))
            except subprocess.TimeoutExpired:
                break
            except (KeyboardInterrupt, Interruption):
                continue
        # Le meneur parti, des membres du groupe peuvent rester.
        self._signaler(proc, signal.SIGKILL)
        while proc.poll() is None:
            try:
                proc.wait()
            except (KeyboardInterrupt, Interruption):
                continue

    @staticmethod
    def _signaler(proc, numero):
        try:
            os.killpg(proc.pid, numero)
        except (ProcessLookupError, PermissionError):
            if proc.poll() is None:
                proc.send_signal(numero)


def dossier_inscriptible(dossier, utilisateur):
    """True si le compte `utilisateur` peut créer un fichier dans `dossier`.

    Lit le propriétaire, le groupe et le mode du dossier et les compare au
    compte (uid, groupe principal et groupes secondaires de passwd/group) :
    `os.access` répondrait pour le compte courant, root le plus souvent.
    Il faut l'écriture ET la traversée de la classe qui s'applique — la
    première qui correspond, comme le noyau. False si le dossier ou le
    compte n'existe pas.
    """
    try:
        info = os.stat(dossier)
        compte = pwd.getpwnam(utilisateur)
    except (OSError, KeyError):
        return False
    if not stat.S_ISDIR(info.st_mode):
        return False
    if compte.pw_uid == 0:
        return True
    if info.st_uid == compte.pw_uid:
        bits = stat.S_IWUSR | stat.S_IXUSR
    else:
        try:
            groupes = os.getgrouplist(utilisateur, compte.pw_gid)
        except OSError:
            groupes = [compte.pw_gid] + [
                g.gr_gid for g in grp.getgrall() if utilisateur in g.gr_mem
            ]
        if info.st_gid in groupes:
            bits = stat.S_IWGRP | stat.S_IXGRP
        else:
            bits = stat.S_IWOTH | stat.S_IXOTH
    return info.st_mode & bits == bits


class Plan:
    """Tout ce que la détection a établi, et les commandes qui en sortent."""

    def __init__(self, **valeurs):
        self.unite = ""
        self.origine_unite = ""
        self.utilisateur = ""
        self.courant = ""
        self.home = ""
        self.wd = ""
        self.execstart = []
        self.env_unite = {}
        self.config_path = ""
        self.origine_config = ""
        self.base = ""
        self.origine_base = ""
        self.hote = odoo_instance.HOTE_LOCAL
        self.port = odoo_instance.PORT_PAR_DEFAUT
        self.logfile = None
        self.modules = []
        self.motifs_vides = []
        self.sauvegarde = True
        self.nom_sauvegarde = ""
        self.chemin_sauvegarde = ""
        self.chemin_partiel = ""
        self.dossier_sauvegarde = ""
        # Vrai si `dossier_sauvegarde` manque : l'exécution réelle le crée
        # avant l'arrêt.
        self.creer_dossier_sauvegarde = False
        self.journal = ""
        self.commande = []
        self.commande_sauvegarde = []
        self.__dict__.update(valeurs)


def _horodatage(systeme, forme):
    return datetime.datetime.fromtimestamp(systeme.maintenant()).strftime(
        forme
    )


def env_supplementaire(plan):
    """Les variables posées devant la commande, dans cet ordre : HOME de
    passwd, l'Environment de l'unité, puis LD_LIBRARY_PATH préfixé de
    NIX_LD_LIBRARY_PATH quand il existe — psycopg2 en a besoin sous
    NixOS, et seul run.sh le fait de lui-même."""
    supp = {"HOME": plan.home}
    supp.update(plan.env_unite)
    nix = plan.env_unite.get("NIX_LD_LIBRARY_PATH") or os.environ.get(
        "NIX_LD_LIBRARY_PATH", ""
    )
    if nix:
        ld = plan.env_unite.get("LD_LIBRARY_PATH") or os.environ.get(
            "LD_LIBRARY_PATH", ""
        )
        supp["LD_LIBRARY_PATH"] = nix + (":" + ld if ld else "")
    return supp


def envelopper(argv, plan, extra=None):
    """`argv` précédé de `env K=V…`, et de `runuser -u COMPTE --` quand le
    compte de l'unité n'est pas le compte courant."""
    supp = env_supplementaire(plan)
    supp.update(extra or {})
    prefixe = []
    if plan.utilisateur and plan.utilisateur != plan.courant:
        prefixe = ["runuser", "-u", plan.utilisateur, "--"]
    return (
        prefixe
        + ["env"]
        + [f"{cle}={valeur}" for cle, valeur in supp.items()]
        + list(argv)
    )


def sans_option_base(argv):
    """`argv` privé de ses options de base — `-d X`, `--database X`,
    `--database=X`, `-dX` —, tout le reste recopié tel quel. Le premier
    élément, le programme lancé, n'est jamais examiné, ni la valeur d'une
    option retirée."""
    garde = list(argv[:1])
    index = 1
    while index < len(argv):
        argument = argv[index]
        if argument in ("-d", "--database"):
            index += 2
            continue
        if argument.startswith("--database=") or (
            argument.startswith("-d") and not argument.startswith("--")
        ):
            index += 1
            continue
        garde.append(argument)
        index += 1
    return garde


def commande_mise_a_jour(plan):
    """La ligne de commande de l'unité, suivie de ce qui en fait un `-u`
    sans serveur : les options répétées l'emportent sur celles de l'unité,
    l'analyseur d'Odoo retenant la dernière. Le `-c` répété remplace celui
    que run.sh pose de lui-même : la mise à jour lit ainsi le fichier de la
    détection et de la sauvegarde, `--odoo-conf` compris. La base de
    l'unité est retirée de sa ligne de commande : la commande ne porte
    qu'un `-d`, celui de la base détectée."""
    argv = sans_option_base(plan.execstart) + [
        "-c",
        plan.config_path,
        "-d",
        plan.base,
        "-u",
        ",".join(plan.modules),
        "--stop-after-init",
        "--no-http",
        "--workers=0",
        "--max-cron-threads=0",
    ]
    return envelopper(argv, plan)


def commande_sauvegarde(plan):
    """`odoo_bin.sh db --backup` vers le nom PROVISOIRE : Odoo ouvre la
    cible en écriture avant le dump, un échec y laisse un zip tronqué."""
    argv = [
        "bash",
        "./odoo_bin.sh",
        "db",
        "--backup",
        "--database",
        plan.base,
        "--restore_image",
        plan.nom_sauvegarde + SUFFIXE_PARTIEL,
    ]
    return envelopper(argv, plan, {"ODOO_RC": plan.config_path})


def _sauvegarde_interdite(config):
    return str(config.get("list_db", "")).strip().lower() in (
        "false",
        "0",
        "no",
        "off",
    )


def _detecter_unite(args, systeme, racine, plan):
    """Nomme l'unité dans `plan` et rend ses propriétés `systemctl show`."""
    lanceur = systeme.lanceur
    if args.service:
        plan.unite, plan.origine_unite = args.service, "--service"
    else:
        try:
            plan.unite, plan.origine_unite = systemd.deviner_unite(
                racine, lanceur
            )
        except systemd.ErreurUnite as err:
            if err.candidates and str(err) == "ambiguous":
                raise Refus(
                    t(
                        "Several Odoo services are possible, choose one"
                        " with --service: {names}"
                    ).format(names=", ".join(err.candidates))
                )
            raise Refus(t("No Odoo service found: name it with --service."))

    try:
        props = systemd.lire_proprietes(plan.unite, lanceur=lanceur)
    except systemd.ErreurUnite as err:
        raise Refus(
            t("Cannot read the service {unit}: {error}").format(
                unit=plan.unite, error=err
            )
        )
    if props["LoadState"] in ("", "not-found"):
        raise Refus(
            t("Service {unit} not found (systemctl).").format(unit=plan.unite)
        )
    return props


def _detecter_compte_et_dossier(args, systeme, plan, props):
    """Compte, HOME, ExecStart, Environment et dossier de travail."""
    plan.courant = systeme.utilisateur_courant()
    plan.utilisateur = args.user or props["User"] or plan.courant
    plan.home = systeme.home(plan.utilisateur)
    plan.execstart = systemd.argv_execstart(props["ExecStart"])
    if not plan.execstart:
        raise Refus(
            t("The service {unit} has no ExecStart.").format(unit=plan.unite)
        )
    plan.env_unite = systemd.environnement(props["Environment"])
    plan.wd = systemd.dossier_de_travail(props["WorkingDirectory"], plan.home)
    if not plan.wd and odoo_instance.lance_run_sh(plan.execstart):
        run_sh = [a for a in plan.execstart if os.path.basename(a) == "run.sh"]
        plan.wd = os.path.dirname(run_sh[0])
    if not plan.wd or not os.path.isdir(plan.wd):
        raise Refus(
            t("The working directory of {unit} is unknown or missing.").format(
                unit=plan.unite
            )
        )


def _detecter_config(args, plan):
    """Le fichier de configuration dans `plan` ; rend son contenu."""
    try:
        plan.config_path, plan.origine_config = odoo_instance.trouver_config(
            plan.execstart, plan.wd, plan.env_unite, args.odoo_conf
        )
    except odoo_instance.ErreurDetection:
        raise Refus(t("No Odoo configuration file found (try --odoo-conf)."))
    try:
        return odoo_instance.lire_config(plan.config_path)
    except OSError:
        raise Refus(
            t("Cannot read {path}: run with sudo.").format(
                path=plan.config_path
            )
        )


def _detecter_base_et_adresse(args, plan, config):
    plan.base, plan.origine_base = odoo_instance.trouver_base(
        args.db, plan.execstart, config
    )
    if not plan.base:
        raise Refus(
            t(
                "Database not found in the service nor in its configuration:"
                " specify --db."
            )
        )
    if not lib_analyse.valid_database_name(plan.base):
        raise Refus(
            t("Invalid database name: {database}").format(database=plan.base)
        )
    plan.hote, plan.port = odoo_instance.adresse_http(plan.execstart, config)
    plan.logfile = odoo_instance.fichier_journal(
        plan.execstart, config, plan.wd
    )


def _detecter_modules(args, plan, config):
    if args.modules == ["all"]:
        plan.modules = ["all"]
        return
    chemins = odoo_instance.chemins_addons(config, plan.wd)
    if not chemins:
        raise Refus(
            t("No addons_path directory found in {path}.").format(
                path=plan.config_path
            )
        )
    modules, absents, vides = odoo_instance.developper_modules(
        args.modules, chemins
    )
    if absents:
        raise Refus(
            t("Module not found in addons_path: {names}").format(
                names=", ".join(absents)
            )
        )
    if not modules:
        raise Refus(t("No module matches the requested patterns."))
    plan.modules, plan.motifs_vides = modules, vides


def _preparer_sauvegarde(args, systeme, plan, config):
    """Vérifie, avant tout arrêt, ce dont la sauvegarde aura besoin.

    Odoo écrit dans `WD/image_db` sans le créer, sous le compte de
    l'unité : le dossier existant doit lui être inscriptible. Absent, il
    est marqué à créer (`creer_dossier_sauvegarde`) si le compte peut
    écrire dans WD, c'est-à-dire l'y créer lui-même ; sinon refus. Un
    fichier au nom définitif déjà présent refuse aussi — la sauvegarde ne
    l'écrase pas.
    """
    plan.sauvegarde = not args.no_backup
    if not plan.sauvegarde:
        return
    odoo_bin = os.path.join(plan.wd, "odoo_bin.sh")
    if not os.path.isfile(odoo_bin):
        raise Refus(
            t(
                "Backup impossible: {path} is missing (use --no-backup"
                " to skip it)."
            ).format(path=odoo_bin)
        )
    if _sauvegarde_interdite(config):
        raise Refus(
            t(
                "Backup impossible: list_db = False forbids it (use"
                " --no-backup to skip it)."
            )
        )
    dossier = os.path.join(plan.wd, "image_db")
    plan.dossier_sauvegarde = dossier
    if not os.path.lexists(dossier):
        if not systeme.inscriptible(plan.wd, plan.utilisateur):
            raise Refus(
                t(
                    "Backup impossible: {path} is missing and {user} cannot"
                    " create it in {parent} (create it, or use --no-backup"
                    " to skip it)."
                ).format(path=dossier, user=plan.utilisateur, parent=plan.wd)
            )
        plan.creer_dossier_sauvegarde = True
    elif not os.path.isdir(dossier) or not systeme.inscriptible(
        dossier, plan.utilisateur
    ):
        raise Refus(
            t(
                "Backup impossible: {path} is not a directory writable by"
                " {user} (create it, or use --no-backup to skip it)."
            ).format(path=dossier, user=plan.utilisateur)
        )
    plan.nom_sauvegarde = "{}_pre_update_{}".format(
        plan.base, _horodatage(systeme, "%Y-%m-%d_%Hh%Mm%Ss")
    )
    plan.chemin_sauvegarde = os.path.join(
        dossier, plan.nom_sauvegarde + ".zip"
    )
    plan.chemin_partiel = os.path.join(
        dossier, plan.nom_sauvegarde + SUFFIXE_PARTIEL + ".zip"
    )
    if os.path.exists(plan.chemin_sauvegarde):
        raise Refus(
            t("The backup file already exists: {path}").format(
                path=plan.chemin_sauvegarde
            )
        )
    plan.commande_sauvegarde = commande_sauvegarde(plan)


def detecter(args, systeme, racine=RACINE):
    """Établit le Plan. Lève Refus sur tout ce qui manque, rien arrêté."""
    plan = Plan()
    props = _detecter_unite(args, systeme, racine, plan)
    _detecter_compte_et_dossier(args, systeme, plan, props)
    config = _detecter_config(args, plan)
    _detecter_base_et_adresse(args, plan, config)
    _detecter_modules(args, plan, config)
    _preparer_sauvegarde(args, systeme, plan, config)
    plan.journal = os.path.join(
        args.log_dir or DOSSIER_JOURNAUX,
        "update-{}-{}.log".format(
            plan.base, _horodatage(systeme, "%Y%m%d-%H%M%S")
        ),
    )
    plan.commande = commande_mise_a_jour(plan)
    return plan


def preparer_journal(plan):
    """Crée le dossier du journal ; se replie sur le dossier temporaire
    s'il ne peut pas l'être ou n'est pas inscriptible."""
    dossier = os.path.dirname(plan.journal)
    try:
        os.makedirs(dossier, mode=0o750, exist_ok=True)
        if os.access(dossier, os.W_OK):
            return plan.journal
    except OSError:
        pass
    plan.journal = os.path.join(
        tempfile.gettempdir(), os.path.basename(plan.journal)
    )
    return plan.journal


def afficher_plan(plan, rapport):
    detecte = (
        "" if plan.origine_unite == "--service" else " " + t("(detected)")
    )
    rapport.champ(t("Service"), plan.unite + detecte)
    rapport.champ(t("Account"), plan.utilisateur)
    rapport.champ(t("Directory"), plan.wd)
    rapport.champ(
        t("Odoo config"), f"{plan.config_path} ({plan.origine_config})"
    )
    rapport.champ(t("Database"), f"{plan.base} ({plan.origine_base})")
    rapport.champ(t("Address"), f"{plan.hote}:{plan.port}")
    rapport.champ(t("Modules"), ", ".join(plan.modules))
    rapport.champ(
        t("Backup"),
        plan.chemin_sauvegarde if plan.sauvegarde else t("none (--no-backup)"),
    )
    rapport.champ(t("Log"), plan.journal)
    for motif in plan.motifs_vides:
        rapport.attn(
            t("No module matches the pattern {pattern}.").format(pattern=motif)
        )


def commande_creation(plan):
    """La création du dossier de sauvegarde, en commandes de shell."""
    dossier = plan.dossier_sauvegarde
    return "{} && {}".format(
        joindre(["mkdir", "-m", "0750", "--", dossier]),
        joindre(["chown", plan.utilisateur + ":", "--", dossier]),
    )


def creer_dossier_sauvegarde(plan, systeme, rapport):
    """Crée le dossier de sauvegarde marqué par la détection, au compte de
    l'unité. Appelée avant l'arrêt : False si la création échoue, et rien
    n'a été arrêté."""
    if not plan.creer_dossier_sauvegarde:
        return True
    try:
        systeme.creer_dossier(plan.dossier_sauvegarde, plan.utilisateur)
    except (OSError, KeyError) as err:
        rapport.erreur(
            t("Cannot create {path}: {error}. Nothing was stopped.").format(
                path=plan.dossier_sauvegarde, error=err
            )
        )
        return False
    rapport.ok(
        t("Created {path}, owned by {user}.").format(
            path=plan.dossier_sauvegarde, user=plan.utilisateur
        )
    )
    return True


def simuler(plan, rapport):
    if plan.creer_dossier_sauvegarde:
        rapport.sim(commande_creation(plan))
    rapport.sim(joindre(["systemctl", "stop", "--", plan.unite]))
    dans_wd = f"cd {shlex.quote(plan.wd)} && "
    vers_journal = f" >> {shlex.quote(plan.journal)} 2>&1"
    if plan.sauvegarde:
        rapport.sim(dans_wd + joindre(plan.commande_sauvegarde) + vers_journal)
    rapport.sim(dans_wd + joindre(plan.commande) + vers_journal)
    rapport.sim(
        joindre(["systemctl", "start", "--", plan.unite])
        + "  # "
        + t("only if it was active")
    )
    rapport.ok(
        t("Simulation finished: nothing was stopped, written or started.")
    )


def _fin_du_journal(chemin, debut):
    return odoo_instance.lire_ajout(chemin, debut).splitlines()[
        -LIGNES_DE_FIN:
    ]


def _retirer(chemin):
    try:
        os.remove(chemin)
    except FileNotFoundError:
        pass


def _sauvegarder(plan, systeme, rapport, args):
    """Écrit la sauvegarde sous son nom provisoire, la relit, la renomme.

    Le fichier provisoire est retiré sur tout échec, exception comprise :
    un zip tronqué ressemble à une sauvegarde. Seul un zip relu et complet
    prend le nom définitif.
    """
    cible = plan.chemin_sauvegarde
    partiel = plan.chemin_partiel
    if os.path.exists(cible):
        rapport.fail(
            t("The backup file already exists: {path}").format(path=cible)
        )
        return CODE_ECHEC
    _retirer(partiel)
    debut = odoo_instance.taille(plan.journal)
    try:
        issue = systeme.lancer_long(
            plan.commande_sauvegarde,
            plan.wd,
            os.environ.copy(),
            plan.journal,
            args.timeout,
        )
    except BaseException:
        _retirer(partiel)
        raise
    if issue.interrompu or issue.tue or issue.code != 0:
        _retirer(partiel)
        if issue.interrompu:
            rapport.fail(t("Backup interrupted: nothing was updated."))
            return CODE_INTERROMPU
        rapport.fail(
            t("Backup failed (code {code}): nothing was updated.").format(
                code=issue.code
            )
        )
        rapport.extrait(_fin_du_journal(plan.journal, debut), LIGNES_DE_FIN)
        return CODE_ECHEC
    ok, problemes = odoo_instance.verifier_sauvegarde(partiel)
    if not ok:
        _retirer(partiel)
        rapport.fail(
            t(
                "The backup is incomplete ({missing}): nothing was updated."
            ).format(missing=", ".join(problemes))
        )
        return CODE_ECHEC
    os.rename(partiel, cible)
    if "filestore" in problemes:
        rapport.attn(t("The backup holds no filestore."))
    rapport.ok(t("Backup written: {path}").format(path=cible))
    return CODE_OK


def _mettre_a_jour(plan, systeme, rapport, args):
    debut_journal = odoo_instance.taille(plan.journal)
    debut_logfile = odoo_instance.taille(plan.logfile)
    depart = systeme.maintenant()
    issue = systeme.lancer_long(
        plan.commande, plan.wd, os.environ.copy(), plan.journal, args.timeout
    )
    duree = int(systeme.maintenant() - depart)
    if issue.interrompu or issue.tue:
        if issue.interrompu:
            rapport.fail(
                t("Update interrupted: Odoo was stopped before the restart.")
            )
        else:
            rapport.fail(
                t("The update exceeded {seconds} s: process killed.").format(
                    seconds=args.timeout
                )
            )
            rapport.extrait(_fin_du_journal(plan.journal, debut_journal), 15)
        # Tuer le processus n'arrête pas sa session PostgreSQL : elle finit
        # son instruction en cours, verrous compris, avant de voir la
        # déconnexion.
        rapport.attn(
            t(
                "The database session of the killed update may still hold"
                " locks for a while: the restart can wait for them."
            )
        )
        return CODE_INTERROMPU if issue.interrompu else CODE_ECHEC
    if issue.code != 0:
        rapport.fail(
            t("Odoo finished with code {code}.").format(code=issue.code)
        )
        rapport.extrait(_fin_du_journal(plan.journal, debut_journal), 15)
        return CODE_ECHEC
    texte = odoo_instance.lire_ajout(plan.journal, debut_journal)
    texte += "\n" + odoo_instance.lire_ajout(plan.logfile, debut_logfile)
    erreurs = odoo_instance.lignes_erreur(texte, args.ignore_error)
    if erreurs:
        rapport.fail(
            t("{count} ERROR/CRITICAL line(s) during the update.").format(
                count=len(erreurs)
            )
        )
        rapport.extrait(erreurs, 10)
        return CODE_ECHEC
    rapport.ok(
        t("Odoo finished the update by itself in {seconds} s.").format(
            seconds=duree
        )
    )
    return CODE_OK


def _arreter_et_mettre_a_jour(plan, systeme, rapport, args):
    lanceur = systeme.lanceur
    rapport.etape(t("Stopping {unit}").format(unit=plan.unite))
    code_arret, sortie = systemd.arreter(plan.unite, lanceur)
    # Arrêté veut dire `inactive` ou `failed` après un stop qui a réussi :
    # `deactivating`, ou un stop dont le client a expiré, laisse l'ancien
    # serveur finir ses requêtes sur la base.
    etat = systemd.etat(plan.unite, lanceur)
    if code_arret != 0 or not systemd.est_arrete(etat):
        rapport.fail(
            t(
                "The service is not stopped after systemctl stop (code"
                " {code}, state {state}): nothing was changed."
            ).format(code=code_arret, state=etat or "?")
        )
        rapport.extrait(sortie.splitlines(), 5)
        return CODE_ECHEC
    rapport.ok(t("Service stopped."))

    genes = []
    if systeme.port_ecoute(plan.hote, plan.port):
        genes.append(
            t("{host}:{port} still answers.").format(
                host=plan.hote, port=plan.port
            )
        )
    for pid, argv in odoo_instance.processus_odoo(
        plan.base, systeme.processus(), systeme.pids_exclus()
    ):
        genes.append(f"{pid} {' '.join(argv)[:200]}")
    if genes:
        for gene in genes:
            rapport.detail(gene)
        if not args.force:
            rapport.fail(
                t(
                    "Odoo still runs on this database or port outside the"
                    " service: refused (--force to go on)."
                )
            )
            return CODE_ECHEC
        rapport.attn(t("--force: going on despite the Odoo found."))

    if plan.sauvegarde:
        rapport.etape(t("Backup of {database}").format(database=plan.base))
        code = _sauvegarder(plan, systeme, rapport, args)
        if code != CODE_OK:
            return code

    rapport.etape(
        t("Update of {modules} in {database}").format(
            modules=",".join(plan.modules), database=plan.base
        )
    )
    rapport.detail(t("Log: {path}").format(path=plan.journal))
    code = _mettre_a_jour(plan, systeme, rapport, args)
    if code != CODE_OK and plan.sauvegarde:
        rapport.detail(
            t("Backup taken before the update: {path}").format(
                path=plan.chemin_sauvegarde
            )
        )
    return code


def _relancer(plan, systeme, rapport, args):
    """Démarre l'unité et vérifie qu'elle sert. True si tout va bien.

    Ne lève pas : elle s'exécute dans le `finally` qui tient l'invariant.
    `systemctl start` part AVANT toute écriture du rapport, pour qu'aucune
    erreur de sortie ne puisse le sauter.
    """
    lanceur = systeme.lanceur
    try:
        if systemd.est_actif(plan.unite, lanceur):
            # Jamais arrêté (stop sans effet) : rien à relancer.
            return True
        debut_logfile = odoo_instance.taille(plan.logfile)
        epoque = systeme.maintenant()
        code, sortie = systemd.demarrer(plan.unite, lanceur)
        rapport.etape(t("Starting {unit}").format(unit=plan.unite))
        if code != 0:
            rapport.fail(
                t(
                    "systemctl start failed (journalctl -u {unit} -n 50)."
                ).format(unit=plan.unite)
            )
            rapport.extrait(sortie.splitlines(), 5)
            return False
        limite = systeme.maintenant() + args.start_wait
        actif = ecoute = False
        while True:
            actif = systemd.est_actif(plan.unite, lanceur)
            ecoute = actif and systeme.port_ecoute(plan.hote, plan.port)
            if ecoute or systeme.maintenant() >= limite:
                break
            systeme.dormir(INTERVALLE_DEMARRAGE)
        if not actif:
            rapport.fail(
                t("The service is not active after {seconds} s.").format(
                    seconds=args.start_wait
                )
            )
            return False
        if not ecoute:
            rapport.fail(
                t(
                    "The service is active but nothing listens on"
                    " {host}:{port} after {seconds} s."
                ).format(
                    host=plan.hote, port=plan.port, seconds=args.start_wait
                )
            )
            return False
        cible = warmup_http.url(plan.hote, plan.port, plan.base)
        if not systeme.sonder(cible, DELAI_SONDE):
            rapport.fail(t("No HTTP answer from {url}.").format(url=cible))
            return False
        rapport.ok(t("Service started and answering: {url}").format(url=cible))

        rapport.etape(t("Errors in the Odoo log since the start"))
        texte = systeme.journal(plan.unite, epoque)
        texte += "\n" + odoo_instance.lire_ajout(plan.logfile, debut_logfile)
        erreurs = odoo_instance.lignes_erreur(texte, args.ignore_error)
        if erreurs:
            rapport.fail(
                t("{count} ERROR/CRITICAL line(s) since the start.").format(
                    count=len(erreurs)
                )
            )
            rapport.extrait(erreurs, 8)
            return False
        rapport.ok(t("No ERROR or CRITICAL line since the start."))
        return True
    except Exception as err:  # noqa: BLE001 - le finally ne doit pas lever
        rapport.fail(t("Restart check failed: {error}").format(error=err))
        return False


def _relancer_quoi_qu_il_arrive(plan, systeme, rapport, args):
    """`_relancer`, avec un dernier recours si elle lève malgré tout :
    `systemctl start` direct, sans vérification. Rend True si la relance
    a été vérifiée."""
    try:
        return _relancer(plan, systeme, rapport, args)
    except BaseException:  # noqa: B036 - le service doit repartir
        systemd.demarrer(plan.unite, systeme.lanceur)
        return False


def executer(plan, systeme, rapport, args):
    """Arrêt, sauvegarde, mise à jour, puis relance si l'unité tournait.

    Rend le code de sortie. La relance est dans un `finally` : exception,
    Ctrl-C ou SIGTERM, l'unité qui tournait est relancée.

    L'état d'avant se lit dans ActiveState. Tout état autre que `inactive`
    ou `failed` compte pour « tournait » (`activating`, `reloading`…) ;
    sans réponse de systemctl, rien n'est arrêté (code 2) : une unité
    dont on ignore l'état ne serait pas relancée à coup sûr.
    """
    etat = systemd.etat(plan.unite, systeme.lanceur)
    if not etat:
        rapport.erreur(
            t(
                "Cannot read the state of {unit} (systemctl): nothing was"
                " stopped."
            ).format(unit=plan.unite)
        )
        return CODE_REFUS
    etait_actif = not systemd.est_arrete(etat)
    rapport.total = 2 + int(plan.sauvegarde) + (2 if etait_actif else 0)
    code = CODE_ECHEC
    restaurer = systeme.proteger_signaux()
    try:
        try:
            code = _arreter_et_mettre_a_jour(plan, systeme, rapport, args)
        except (KeyboardInterrupt, Interruption):
            # Un second signal ne doit pas interrompre le rapport du premier.
            systeme.arme = False
            rapport.fail(t("Interrupted."))
            code = CODE_INTERROMPU
        except Exception as err:  # noqa: BLE001 - la relance doit suivre
            rapport.fail(t("Unexpected error: {error}").format(error=err))
            code = CODE_ECHEC
        finally:
            # Première instruction, une simple affectation : aucun
            # gestionnaire de signal ne lève plus à partir d'ici.
            systeme.arme = False
            liberer = systeme.ignorer_interruptions()
            try:
                if etait_actif:
                    if (
                        not _relancer_quoi_qu_il_arrive(
                            plan, systeme, rapport, args
                        )
                        and code == CODE_OK
                    ):
                        code = CODE_ECHEC
                else:
                    rapport.attn(
                        t(
                            "The service was not running before: it is left"
                            " stopped."
                        )
                    )
            finally:
                liberer()
    finally:
        restaurer()
    if code == CODE_OK:
        rapport.ok(
            t("Update finished: {modules}").format(
                modules=",".join(plan.modules)
            )
        )
    elif code == CODE_ECHEC:
        rapport.fail(t("Update failed."))
    return code


def _type_motifs(valeur):
    motifs = [m.strip() for m in valeur.split(",") if m.strip()]
    if not motifs:
        raise argparse.ArgumentTypeError(t("empty module list"))
    for motif in motifs:
        if not odoo_instance.motif_valide(motif):
            raise argparse.ArgumentTypeError(
                t("invalid module pattern: {pattern}").format(pattern=motif)
            )
    return motifs


def _type_unite(valeur):
    try:
        return systemd.nom_unite(valeur)
    except ValueError:
        raise argparse.ArgumentTypeError(
            t("invalid service name: {name}").format(name=valeur)
        )


def _type_base(valeur):
    if not lib_analyse.valid_database_name(valeur):
        raise argparse.ArgumentTypeError(
            t("Invalid database name: {database}").format(database=valeur)
        )
    return valeur


def _type_utilisateur(valeur):
    if RE_UTILISATEUR.fullmatch(valeur) is None:
        raise argparse.ArgumentTypeError(
            t("invalid user name: {name}").format(name=valeur)
        )
    return valeur


def _type_secondes(valeur):
    try:
        secondes = int(valeur)
    except ValueError:
        secondes = 0
    if secondes < 1:
        raise argparse.ArgumentTypeError(
            t("expected an integer >= 1: {value}").format(value=valeur)
        )
    return secondes


def _type_regex(valeur):
    try:
        return re.compile(valeur)
    except re.error as err:
        raise argparse.ArgumentTypeError(
            t("invalid regular expression: {error}").format(error=err)
        )


def analyser(argv=None):
    parser = argparse.ArgumentParser(
        description=t(
            "Update installed Odoo modules of an instance run by systemd:"
            " stop, back up, update, restart, check."
        )
    )
    parser.add_argument(
        "--module",
        dest="modules",
        action="append",
        type=_type_motifs,
        required=True,
        help=t(
            "Module(s) to update; repeatable, commas allowed, * and ?"
            " patterns, or 'all'."
        ),
    )
    parser.add_argument(
        "--service",
        type=_type_unite,
        help=t(
            "systemd unit; default: the unit whose WorkingDirectory is this"
            " checkout, else the only active one."
        ),
    )
    parser.add_argument(
        "--db",
        type=_type_base,
        help=t("Database; default: -d of the unit, else db_name."),
    )
    parser.add_argument(
        "--odoo-conf",
        help=t("Odoo configuration file; default: the one the unit reads."),
    )
    parser.add_argument(
        "--user",
        type=_type_utilisateur,
        help=t("Account running the update; default: User= of the unit."),
    )
    parser.add_argument(
        "--timeout",
        type=_type_secondes,
        default=DELAI_MISE_A_JOUR,
        help=t("Maximum seconds for the backup and for the update."),
    )
    parser.add_argument(
        "--start-wait",
        type=_type_secondes,
        default=DELAI_DEMARRAGE,
        help=t("Maximum seconds for the service to listen after start."),
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help=t("Do not back up the database before the update."),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=t("Go on even if Odoo still runs on this database or port."),
    )
    parser.add_argument(
        "--ignore-error",
        action="append",
        type=_type_regex,
        default=[],
        metavar="REGEX",
        help=t("ERROR/CRITICAL lines matching REGEX do not fail; repeatable."),
    )
    parser.add_argument(
        "--log-dir",
        help=t("Directory of the update log; default: {path}.").format(
            path=DOSSIER_JOURNAUX
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=t("Detect and show the commands; stop, write or start nothing."),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=t("Show each system command on stderr."),
    )
    args = parser.parse_args(argv)
    args.modules = [m for groupe in args.modules for m in groupe]
    if "all" in args.modules and len(args.modules) > 1:
        parser.error(t("'all' cannot be combined with other modules."))
    return args


def main(argv=None, systeme=None, rapport=None):
    args = analyser(argv)
    systeme = systeme or Systeme(verbeux=args.verbose)
    rapport = rapport or report.Rapport()
    rapport.texte(
        "{} — {}".format(
            t("Odoo module update"), _horodatage(systeme, "%Y-%m-%d %H:%M")
        )
    )
    try:
        plan = detecter(args, systeme)
    except Refus as err:
        rapport.erreur(str(err))
        return CODE_REFUS
    except KeyboardInterrupt:
        return CODE_INTERROMPU
    afficher_plan(plan, rapport)
    if args.dry_run:
        simuler(plan, rapport)
        return CODE_OK
    if systeme.euid() != 0:
        rapport.erreur(t("Root is required (sudo), except with --dry-run."))
        return CODE_REFUS
    verrou = systeme.verrou(plan.base)
    try:
        verrou.acquerir()
    except lock.VerrouPris as err:
        rapport.erreur(
            t("Another update of {database} is running (lock {path}).").format(
                database=plan.base, path=err.chemin
            )
        )
        return CODE_VERROU
    except OSError as err:
        rapport.erreur(t("Cannot take the lock: {error}").format(error=err))
        return CODE_REFUS
    try:
        preparer_journal(plan)
        if not creer_dossier_sauvegarde(plan, systeme, rapport):
            return CODE_REFUS
        return executer(plan, systeme, rapport, args)
    finally:
        verrou.relacher()


if __name__ == "__main__":
    sys.exit(main())
