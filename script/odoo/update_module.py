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
   Le fichier de configuration est relu comme Odoo le lira au redémarrage
   (`lib_ops/odoo_conf.py`, types de la version du `.odoo-version` du
   dossier de l'unité), avant la base : une clé répétée, un commentaire
   après une valeur typée ou de connexion, une valeur qu'optparse refuse ou
   une limite de mémoire écrite en Mo refusent ici, code 2 — sinon l'unité
   arrêtée ne repartirait pas, ou ne servirait pas. Avec `--odoo-conf`, le
   fichier de l'unité, celui de la relance, est validé aussi. Les
   avertissements s'affichent dans le plan.
   La sauvegarde est préparée ici aussi : dossiers de destination et
   d'état inscriptibles par le compte de l'unité (ou à créer), base lisible,
   espace disque suffisant pour `(taille de la base + filestore) × 1,2`.
   Les modules installés de la base viennent de cette lecture, ou d'une
   requête en lecture seule sans sauvegarde : `-u` ignore en silence un
   module que la base n'a pas installé, d'où un ATTN par module, et un
   refus (code 2) quand aucun ne l'est. Un état illisible est dit
   inconnu et ne retire aucun module.
2. Root exigé, puis le verrou de la base, partagé avec
   `script/database/odoo_backup.py` : deux opérations sur la même base ne
   se chevauchent pas (code 75). Les dossiers de la sauvegarde qui manquent
   sont créés ici, au compte de l'unité : un échec refuse encore avant
   l'arrêt (code 2).
3. Arrêt de l'unité. Si le port répond encore, si un processus Odoo
   tourne sur la même base hors de l'unité — par son `-d`, ou, pour un
   serveur de root ou du compte de l'unité, sans `-d` avec une
   configuration dont `db_name` est cette base, ou vide sans un autre
   `db_user` renseigné que celui de l'instance —, ou si
   des sessions restent connectées à la base dans `pg_stat_activity`
   après DELAI_SESSIONS secondes, la mise à jour est refusée (code 1),
   sauf `--force` : deux serveurs sur une base pendant un `-u` se
   disputent son schéma.
4. Sauvegarde, APRÈS l'arrêt pour être cohérente : `odoo_backup.sauvegarder`
   appelée en fonction, sous le verrou déjà tenu — pg_dump sous le compte
   de l'unité, zip au format d'Odoo écrit sous un nom provisoire, relu puis
   renommé, empreinte sha256, état de la base noté. Ni copie hors site ni
   rétention ici : la sauvegarde planifiée s'en charge.
5. Mise à jour : la ligne de commande de l'unité, privée de sa base
   (`-d`, `--database`), suivie de `-c CONFIG -d BASE -u MODULES
   --stop-after-init --no-http --workers=0 --max-cron-threads=0
   --limit-memory-hard=0 --log-level=info` — le `-c` répété garde la mise
   à jour sur le fichier que la détection et la sauvegarde ont lu ; la
   limite de mémoire du serveur ne la tue pas en cours de route —, sous
   le compte de l'unité (`runuser`), HOME tiré de passwd. Échec si le
   code est non nul, si le délai est dépassé, ou si un enregistrement
   ERROR ou CRITICAL paraît dans la sortie ou dans ce qui s'est AJOUTÉ au
   `logfile` configuré — Odoo y écrit au lieu de stderr quand il est
   posé. Les enregistrements sont lus par `lib_ops.journal` : une trace
   compte avec son en-tête, et le rapport groupe les traces par leur
   exception finale.
6. Redémarrage, si l'unité tournait avant : l'époque est prise AVANT
   `systemctl start`, pour que les erreurs du chargement entrent dans la
   fenêtre lue ensuite ; attente de `active` et du port, une requête HTTP
   qui force le chargement du registre, puis lecture du journal de
   l'unité — celui de son LogNamespace= quand elle en a un — et du
   `logfile` depuis cette époque.
7. Après une relance vérifiée seulement, verrou relâché et signaux rendus
   — un Ctrl-C n'y interrompt que cette étape : avec `--warmup-deep`, le
   préchauffage profond de `warmup_http.py` (pages publiques et paquets
   d'assets, sans clé), puis la vérification de santé de l'instance
   locale par `health_check.py`, puis une seconde lecture du journal
   depuis la même époque, après un court délai pour journald : une erreur
   au premier rendu d'une vue mise à jour n'y paraît qu'alors. Leurs
   constats sont des ATTN au plus : ils ne changent jamais le code de
   sortie.
8. Dans tous les cas où la mise à jour a été lancée, les journaux
   `update-<base>-<horodatage>.log` de plus de `--log-keep-days` jours
   (180 par défaut, 0 n'en retire aucun) sont retirés de leur dossier, les
   JOURNAUX_GARDES plus récents gardés quel que soit leur âge. Le rapport
   finit par la durée de chaque phase et par le temps où le site est
   resté coupé, de l'arrêt à la première réponse HTTP sous 500.

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

Les réglages durables d'une instance viennent de son profil de production
(`lib_ops/profil.py`, groupe `update_module`, `log_keep_days` compris,
plus `instance.db`, `backup.dest` et `backup.state_dir`) : `--profile
FICHIER`, sinon
`private/production/<unité>.json` de ce checkout. La ligne de commande
l'emporte sur chaque valeur, `--no-profile` l'ignore. Les modules, l'unité,
le compte, la configuration, `--force`, `--no-backup` et `--dry-run` ne
s'y lisent jamais. `--warmup-deep` reste anonyme, aux réglages par défaut
du préchauffage : il ne lit pas le groupe `warmup` du profil. Avec
`--no-profile`, l'abréviation `--no` devient ambiguë et argparse la
refuse.

Bibliothèque standard seulement, sans syntaxe postérieure à Python 3.7 :
le programme se lance aussi par le python3 d'un serveur de production.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import os
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

from script.database import odoo_backup  # noqa: E402
from script.lib_ops import (  # noqa: E402
    journal,
    lock,
    odoo_conf,
    odoo_instance,
    postgres,
    profil,
    report,
    service,
    systemd,
)
from script.odoo import health_check, warmup_http  # noqa: E402

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

# Groupe des réglages de cet outil dans un profil de production
# (`lib_ops/profil.py`).
GROUPE = "update_module"

DELAI_MISE_A_JOUR = 1800
DELAI_DEMARRAGE = 90
DELAI_SONDE = 120
# Délai de grâce entre TERM et KILL du groupe de la mise à jour.
GRACE_KILL = 30
INTERVALLE_DEMARRAGE = 2
DOSSIER_JOURNAUX = "/var/log/erplibre"
# Lignes de fin de journal montrées quand Odoo sort en erreur.
LIGNES_DE_FIN = 15
# Attente avant la seconde lecture du journal : journald reçoit les
# dernières lignes d'Odoo un peu après qu'il les a écrites.
DELAI_JOURNALD = 2
# Après l'arrêt, le temps laissé aux sessions PostgreSQL du serveur arrêté
# pour se fermer, relu chaque seconde.
DELAI_SESSIONS = 10
# Purge des journaux de mise à jour : les plus récents gardés quel que
# soit leur âge, et l'âge par défaut au-delà duquel les autres partent.
JOURNAUX_GARDES = 10
JOURS_JOURNAUX = 180
# Un code HTTP sous ce seuil dit le site rendu à ses visiteurs.
CODE_SERVI = 500

# L'issue d'un processus long : son code, s'il a été tué pour délai
# dépassé, s'il a été interrompu à la demande.
Issue = collections.namedtuple("Issue", "code tue interrompu")


# Refus avant tout arrêt : le message dit ce qui manque.
Refus = service.Refus
Interruption = service.Interruption
joindre = service.joindre
dossier_inscriptible = service.dossier_inscriptible


class Systeme(odoo_backup.Systeme):
    """Les effets de bord du programme, regroupés — ceux de la sauvegarde
    (PostgreSQL, espace disque, propriété des fichiers) compris.

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
        super().__init__(verbeux=verbeux, dossier_verrou=dossier_verrou)
        self.grace = grace
        self.interactif = (
            sys.stdin.isatty() if interactif is None else interactif
        )
        self.demander = demander or self._demander_interruption
        # Tant que faux, les gestionnaires de `proteger_signaux` ne lèvent
        # rien : le `finally` d'`executer` le remet à False avant la relance.
        self.arme = False

    def journal(self, unite, epoque, namespace=""):
        return systemd.journal_depuis(unite, epoque, self.lanceur, namespace)

    def port_ecoute(self, hote, port):
        try:
            with socket.create_connection((hote, port), timeout=1):
                return True
        except OSError:
            return False

    def processus(self):
        return odoo_instance.lister_processus("/proc")

    def dossier_processus(self, pid):
        return odoo_instance.dossier_processus(pid, "/proc")

    def uid_processus(self, pid):
        return odoo_instance.uid_processus(pid, "/proc")

    def pids_exclus(self):
        return (os.getpid(), os.getppid())

    def dormir(self, secondes):
        time.sleep(secondes)

    def sonder(self, cible, delai):
        """Le code HTTP de la première réponse de `cible`, 0 sans
        réponse dans `delai` secondes."""
        return warmup_http.premier_code(cible, delai_total=delai)

    def prechauffer(self, plan):
        """Le préchauffage profond de l'instance relancée : un Bilan."""
        return warmup_http.prechauffer_profond(
            f"http://{plan.hote}:{plan.port}", plan.base
        )

    def sante(self, plan):
        """La vérification de santé de l'instance locale : (version,
        [Resultat])."""
        return health_check.verifier_local(
            plan.hote, plan.port, plan.base, plan.list_db
        )

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
        # LogNamespace= de l'unité : le journal relu après la relance est
        # celui de ce namespace. `namespace_ecarte` garde un nom que
        # journalctl ne recevrait pas, alors laissé de côté.
        self.namespace = ""
        self.namespace_ecarte = ""
        self.config_path = ""
        self.origine_config = ""
        # La version majeure d'Odoo de l'instance (None si inconnue) et la
        # validation de son fichier de configuration.
        self.version_odoo = None
        self.verification_conf = None
        self.base = ""
        self.origine_base = ""
        self.hote = odoo_instance.HOTE_LOCAL
        self.port = odoo_instance.PORT_PAR_DEFAUT
        self.logfile = None
        # `list_db` de la configuration, brut : lu par la vérification de
        # santé après la relance.
        self.list_db = None
        self.modules = []
        self.motifs_vides = []
        # Les modules demandés que la base n'a pas installés ; quand l'état
        # ne se lit pas, `installes_inconnus` en porte la raison.
        self.non_installes = []
        self.installes_inconnus = ""
        self.sauvegarde = True
        # La Cible d'odoo_backup, et les dossiers qui manquent : l'exécution
        # réelle les crée avant l'arrêt. `cible_pg` sert aux requêtes de
        # lecture : la même Cible, ou une Cible construite sans sauvegarde.
        self.cible = None
        self.cible_pg = None
        self.dossiers_a_creer = []
        # L'évaluation de la sauvegarde (espace), None si inconnue.
        self.estimation = None
        # Remplie par la sauvegarde réussie.
        self.chemin_sauvegarde = ""
        self.journal = ""
        self.commande = []
        # Vrai quand la relance a été vérifiée (port, HTTP, journal).
        self.relance_verifiee = False
        # L'époque prise avant `systemctl start` et la taille du `logfile`
        # à cet instant : la seconde lecture du journal repart de là.
        self.epoque_relance = None
        self.debut_logfile_relance = 0
        # [(modèle N_ à `{duration}`, secondes)] des phases, dans l'ordre.
        self.durees = []
        # Site coupé : de l'instant d'avant `systemctl stop` (None si
        # l'unité ne tournait pas) à la première réponse sous CODE_SERVI.
        self.debut_coupure = None
        self.fin_coupure = None
        self.__dict__.update(valeurs)


def _horodatage(systeme, forme):
    return datetime.datetime.fromtimestamp(systeme.maintenant()).strftime(
        forme
    )


env_supplementaire = service.env_supplementaire
envelopper = service.envelopper


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
    l'analyseur d'Odoo (optparse, action `store`) retenant la dernière. Le
    `-c` répété remplace celui que run.sh pose de lui-même : la mise à
    jour lit ainsi le fichier de la détection et de la sauvegarde,
    `--odoo-conf` compris. La base de l'unité est retirée de sa ligne de
    commande : la commande ne porte qu'un `-d`, celui de la base détectée.

    `--limit-memory-hard=0` lève la limite RLIMIT_AS que le serveur
    threadé pose dès son démarrage, `-u` compris : 2560 Mio par défaut,
    même quand la configuration ne la nomme pas. Odoo valide la base
    module par module, et un MemoryError en cours de `-u` laisse une base
    à moitié migrée. `--log-level=info` garde les lignes INFO, que la
    configuration ou l'unité abaisserait, dans le journal de la mise à
    jour ; un `log_handler` de la configuration s'applique encore après
    lui, logger par logger. Les deux suivent la ligne de l'unité : une
    valeur qu'elle porterait déjà est remplacée. `--limit-time-*` n'est
    pas posé : ces limites ne s'appliquent qu'aux workers et aux requêtes
    HTTP, absents d'un `-u --no-http --workers=0`."""
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
        "--limit-memory-hard=0",
        "--log-level=info",
    ]
    return envelopper(argv, plan)


def _detecter_adresse(plan, config):
    plan.hote, plan.port = odoo_instance.adresse_http(plan.execstart, config)
    plan.logfile = odoo_instance.fichier_journal(
        plan.execstart, config, plan.wd
    )
    plan.list_db = config.get("list_db")


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

    Les dossiers `<dest>/<base>` et `<state-dir>/<base>` doivent être
    inscriptibles par le compte de l'unité, ou pouvoir être créés ; la base
    doit se lire, et l'espace libre suffire. Quand la base ne peut pas être
    lue sous ce compte (simulation par un autre compte), l'estimation est
    seulement annoncée inconnue ; un dossier que seul root peut créer est,
    en simulation, prévu sous sudo. Tout manque refuse, avec le conseil
    `--no-backup`.
    """
    plan.sauvegarde = not args.no_backup
    if not plan.sauvegarde:
        return
    plan.cible = odoo_backup.preparer_cible(
        plan, config, args.backup_dest, args.state_dir, systeme
    )
    try:
        plan.dossiers_a_creer = odoo_backup.dossiers_a_creer(
            plan.cible, systeme, args.dry_run
        )
        if plan.cible.interrogeable:
            plan.estimation = odoo_backup.evaluer(plan.cible, systeme)
    except Refus as err:
        raise Refus(
            t(
                "Backup impossible: {reason} (use --no-backup to skip it)."
            ).format(reason=err.message(t))
        )


def _modules_a_jour_possible(faits):
    """Les noms des modules que `-u` met à jour d'après `faits` : ceux à
    l'état `installed` (clé `modules`) et ceux à l'état `to upgrade` (clé
    `to_upgrade`), qu'Odoo sélectionne aussi."""
    noms = set(faits.get("modules") or {})
    noms.update(faits.get("to_upgrade") or [])
    return noms


def _modules_installes(systeme, plan):
    """(noms des modules installés ou `to upgrade` de la base, "") ;
    (None, raison) quand l'état ne se lit pas.

    Avec la sauvegarde, l'évaluation les a déjà lus
    (`postgres.REQUETE_FAITS`) ; sans elle, `postgres.REQUETE_MODULES` les
    lit en lecture seule. Une simulation sous un autre compte que celui de
    l'unité, sans root, ne lit pas la base."""
    if plan.estimation is not None:
        return _modules_a_jour_possible(plan.estimation.faits), ""
    if not plan.cible_pg.interrogeable:
        return None, t("requires sudo")
    try:
        faits = odoo_backup.interroger(
            plan.cible_pg, systeme, sql=postgres.REQUETE_MODULES
        )
    except odoo_backup.ErreurPg as err:
        return None, str(err)
    return _modules_a_jour_possible(faits), ""


def _verifier_installes(systeme, plan):
    """Pose `plan.non_installes`, ou `plan.installes_inconnus` quand l'état
    ne se lit pas. Odoo ignore en silence, dans `-u`, un module que la base
    n'a pas installé : refus (rien n'est arrêté) quand AUCUN module demandé
    ne l'est, avertissement sinon. Un module `to upgrade` compte comme
    installé : `-u` le met à jour. `all` n'est pas examiné. Un état
    inconnu ne retire ni ne refuse rien."""
    if plan.modules == ["all"]:
        return
    installes, raison = _modules_installes(systeme, plan)
    if installes is None:
        plan.installes_inconnus = raison
        return
    absents = [nom for nom in plan.modules if nom not in installes]
    if absents and len(absents) == len(plan.modules):
        raise Refus(
            service.N_(
                "No requested module is installed in {database}: {names}."
                " -u would do nothing; nothing was stopped."
            ),
            database=plan.base,
            names=", ".join(absents),
        )
    plan.non_installes = absents


def modules_mis_a_jour(plan):
    """Les modules que `-u` met vraiment à jour : ceux demandés, moins
    ceux que la base n'a pas installés."""
    return [nom for nom in plan.modules if nom not in plan.non_installes]


def _verifier_fichier(chemin, version):
    """La `odoo_conf.Verification` de `chemin`. Lève Refus quand il ne se
    lit pas, ou quand Odoo le refuserait ou ne pourrait pas servir avec
    lui, chaque erreur sur sa ligne."""
    try:
        verification = odoo_conf.verifier(chemin, version)
    except FileNotFoundError:
        raise Refus(
            service.N_("Configuration file not found: {path}."), path=chemin
        )
    except PermissionError:
        raise Refus(
            service.N_("Cannot read {path}: run with sudo."), path=chemin
        )
    except OSError as err:
        raise Refus(
            service.N_("Cannot read {path}: {error}"),
            path=chemin,
            error=err.strerror or err,
        )
    erreurs = verification.erreurs()
    if erreurs:
        raise Refus(
            service.N_(
                "{path}: Odoo would refuse it, or could not serve with it,"
                " at the next start ({count} error(s)): nothing was"
                " stopped.\n{details}"
            ),
            path=chemin,
            count=len(erreurs),
            details="\n".join("   " + c.decrire(t) for c in erreurs),
        )
    return verification


def valider_config(plan):
    """Relit `plan.config_path` comme Odoo le lira au redémarrage : pose
    `plan.version_odoo` et `plan.verification_conf`. Lève Refus quand Odoo
    refuserait le fichier : rien n'est encore arrêté, et une unité arrêtée
    sur ce fichier ne repartirait pas.

    Avec `--odoo-conf`, la mise à jour lit ce fichier-là, mais
    `systemctl start` relance l'unité sur le sien : celui-ci est validé
    aussi, et ses erreurs refusent de même."""
    plan.version_odoo = odoo_conf.version_instance(plan.wd, plan.execstart)
    plan.verification_conf = _verifier_fichier(
        plan.config_path, plan.version_odoo
    )
    if plan.origine_config != "--odoo-conf":
        return
    try:
        chemin, _origine = odoo_instance.trouver_config(
            plan.execstart, plan.wd, plan.env_unite
        )
    except odoo_instance.ErreurDetection:
        return
    if os.path.realpath(chemin) != os.path.realpath(plan.config_path):
        _verifier_fichier(chemin, plan.version_odoo)


def detecter(args, systeme, racine=RACINE):
    """Établit le Plan. Lève Refus sur tout ce qui manque, rien arrêté."""
    plan = Plan()
    config = service.detecter_instance(
        args, systeme, racine, plan, apres_config=valider_config
    )
    _detecter_adresse(plan, config)
    _detecter_modules(args, plan, config)
    _preparer_sauvegarde(args, systeme, plan, config)
    plan.cible_pg = plan.cible or odoo_backup.preparer_cible(
        plan, config, args.backup_dest, args.state_dir, systeme
    )
    _verifier_installes(systeme, plan)
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


def afficher_plan(plan, rapport, args=None):
    """Le plan détecté, puis le profil : une ligne par valeur venue du
    profil, un motif `--ignore-error` par ligne, un ATTN par clé inconnue
    ou valeur écartée. Une base venue du profil le dit au lieu de
    `--db`."""
    application = getattr(args, "profil", None)
    detecte = (
        "" if plan.origine_unite == "--service" else " " + t("(detected)")
    )
    rapport.champ(t("Service"), plan.unite + detecte)
    if plan.namespace:
        rapport.champ(t("Journal namespace"), plan.namespace)
    elif plan.namespace_ecarte:
        rapport.champ(
            t("Journal namespace"),
            t("{name} (invalid name: the default journal is read)").format(
                name=plan.namespace_ecarte
            ),
        )
    rapport.champ(t("Account"), plan.utilisateur)
    rapport.champ(t("Directory"), plan.wd)
    rapport.champ(
        t("Odoo config"), f"{plan.config_path} ({plan.origine_config})"
    )
    origine_base = profil.origine_affichee(
        application, "db", plan.origine_base, t
    )
    rapport.champ(t("Database"), f"{plan.base} ({origine_base})")
    rapport.champ(t("Address"), f"{plan.hote}:{plan.port}")
    rapport.champ(t("Modules"), ", ".join(plan.modules))
    if plan.sauvegarde:
        rapport.champ(t("Backup"), plan.cible.dossier)
        estimation = plan.estimation
        rapport.champ(
            t("Estimate"),
            t("{needed} needed, {free} free").format(
                needed=odoo_backup.humain(estimation.besoin),
                free=odoo_backup.humain(estimation.libre),
            )
            if estimation is not None
            else t("unknown (requires sudo)"),
        )
    else:
        rapport.champ(t("Backup"), t("none (--no-backup)"))
    rapport.champ(t("Log"), plan.journal)
    if application is not None:
        profil.afficher(application, rapport, t)
    if plan.verification_conf is not None:
        for constat in plan.verification_conf.avertissements():
            rapport.attn(
                t("Odoo config, {finding}").format(finding=constat.decrire(t))
            )
    for motif in plan.motifs_vides:
        rapport.attn(
            t("No module matches the pattern {pattern}.").format(pattern=motif)
        )
    if plan.non_installes:
        rapport.attn(
            t("Not installed in {database}, ignored by -u: {names}").format(
                database=plan.base, names=", ".join(plan.non_installes)
            )
        )
    if plan.installes_inconnus:
        rapport.attn(
            t(
                "Installed modules of {database} unknown ({reason}): -u"
                " ignores a module the database has not installed."
            ).format(database=plan.base, reason=plan.installes_inconnus)
        )


def creer_dossier_sauvegarde(plan, systeme, rapport):
    """Crée les dossiers de sauvegarde marqués par la détection, au compte
    de l'unité. Appelée avant l'arrêt : False si la création échoue, et
    rien n'a été arrêté."""
    if not plan.sauvegarde or not plan.dossiers_a_creer:
        return True
    if odoo_backup.creer_dossiers(
        plan.dossiers_a_creer, plan.cible, systeme, rapport
    ):
        return True
    rapport.erreur(t("Nothing was stopped."))
    return False


def simuler(plan, rapport, args):
    if plan.sauvegarde:
        for ligne in odoo_backup.commandes_creation(
            plan.dossiers_a_creer, plan.cible
        ):
            rapport.sim(ligne)
        if plan.cible.creation_sudo:
            rapport.attn(
                t(
                    "Some folders can only be created by root: the real run"
                    " creates them under sudo."
                )
            )
    rapport.sim(joindre(["systemctl", "stop", "--", plan.unite]))
    rapport.sim(
        t(
            "check that no Odoo process and no PostgreSQL session remain"
            " on {database}"
        ).format(database=plan.base)
        + "  # "
        + t("refused without --force")
    )
    dans_wd = f"cd {shlex.quote(plan.wd)} && "
    vers_journal = f" >> {shlex.quote(plan.journal)} 2>&1"
    if plan.sauvegarde:
        rapport.sim(
            odoo_backup.decrire(
                odoo_backup.argv_dump(plan.cible),
                odoo_backup.variables_pg(plan.cible),
            )
            + " → "
            + os.path.join(plan.cible.dossier, plan.base + "_<date>.zip")
        )
    rapport.sim(dans_wd + joindre(plan.commande) + vers_journal)
    rapport.sim(
        joindre(["systemctl", "start", "--", plan.unite])
        + "  # "
        + t("only if it was active")
    )
    adresse = f"http://{plan.hote}:{plan.port}"
    if args.warmup_deep:
        rapport.sim(
            t("deep cache warm-up of {url}").format(url=adresse)
            + "  # "
            + t("after a verified restart")
        )
    rapport.sim(
        t("health check of {url}").format(url=adresse)
        + "  # "
        + t("after a verified restart")
    )
    rapport.sim(
        t("second read of the Odoo log since the start")
        + "  # "
        + t("after a verified restart")
    )
    if args.log_keep_days:
        rapport.sim(
            t(
                "purge of the update logs of {database} in {path} older than"
                " {days} day(s), the {count} most recent kept"
            ).format(
                database=plan.base,
                path=os.path.dirname(plan.journal),
                days=args.log_keep_days,
                count=JOURNAUX_GARDES,
            )
        )
    rapport.ok(
        t("Simulation finished: nothing was stopped, written or started.")
    )


def _fin_du_journal(chemin, debut):
    return odoo_instance.lire_ajout(chemin, debut).splitlines()[
        -LIGNES_DE_FIN:
    ]


def _sauvegarder(plan, systeme, rapport, args):
    """La sauvegarde d'odoo_backup, sous le verrou déjà tenu.

    Elle retire elle-même son fichier provisoire sur tout échec. Un Ctrl-C
    pendant pg_dump arrête pg_dump, puis rend 130 : rien n'a été mis à
    jour. SIGTERM remonte, comme pendant la mise à jour.
    """
    try:
        resultat = odoo_backup.sauvegarder(
            plan.cible, systeme, rapport, args.timeout
        )
    except KeyboardInterrupt:
        rapport.fail(t("Backup interrupted: nothing was updated."))
        return CODE_INTERROMPU
    if resultat.code != CODE_OK:
        rapport.fail(t("Backup failed: nothing was updated."))
        return CODE_ECHEC
    plan.chemin_sauvegarde = resultat.chemin
    return CODE_OK


def erreurs_du_journal(texte, args):
    """L'Analyse (`lib_ops.journal`) des enregistrements de `texte` : une
    ligne d'en-tête ERROR ou CRITICAL et ses lignes de continuation (une
    trace) forment un enregistrement. Seul `--ignore-error` filtre, cherché
    dans la ligne d'en-tête et dans la ligne d'exception finale ; le bruit
    connu de `log_check.py` n'est pas écarté : après une mise à jour, tout
    ERROR mérite un regard."""
    return journal.analyser(
        journal.enregistrements(texte.splitlines()),
        ignorer=args.ignore_error,
        builtin=False,
    )


def montrer_groupes(rapport, analyse, limite):
    """Au plus `limite` groupes, du plus nombreux au moins nombreux :
    `[Nx] exception finale ou message (logger)`, puis la première ligne
    d'en-tête du groupe."""
    for groupe in analyse.groupes_a_revoir()[:limite]:
        titre = f"[{groupe.nombre}x] {groupe.titre}"
        if not groupe.titre.startswith(groupe.logger + ":"):
            titre += f" ({groupe.logger})"
        rapport.extrait([titre, f"    {groupe.echantillon[0]}"], 2)


def _noter_duree(plan, systeme, modele, depuis):
    """Ajoute à `plan.durees` la phase `modele` (anglais, `{duration}`),
    commencée à `depuis` et finie maintenant."""
    plan.durees.append((modele, max(0.0, systeme.maintenant() - depuis)))


def duree_lisible(secondes):
    """`45 s`, `3 min 05 s`, `1 h 02 min` : la durée arrondie à la
    seconde, sans unité vide en tête."""
    secondes = int(round(secondes))
    heures, reste = divmod(secondes, 3600)
    minutes, secondes = divmod(reste, 60)
    if heures:
        return f"{heures} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min {secondes:02d} s"
    return f"{secondes} s"


def sessions_restantes(plan, systeme, rapport):
    """Les sessions PostgreSQL encore connectées à la base après l'arrêt
    ([dict] de `postgres.REQUETE_SESSIONS`), relues chaque seconde pendant
    au plus DELAI_SESSIONS secondes : celles du serveur arrêté se ferment
    quand PostgreSQL voit la déconnexion. Une session qui reste vient d'un
    autre client — un Odoo sans `-d` d'une autre unité, ses crons, un psql
    ouvert — et écrirait pendant le `-u`. Une lecture impossible rend []
    avec un ATTN : la sauvegarde ou la mise à jour qui suivent ont besoin
    de la même connexion et le diront."""
    limite = systeme.maintenant() + DELAI_SESSIONS
    while True:
        try:
            faits = odoo_backup.interroger(
                plan.cible_pg, systeme, sql=postgres.REQUETE_SESSIONS
            )
        except odoo_backup.ErreurPg as err:
            rapport.attn(
                t(
                    "PostgreSQL sessions on {database} not checked: {error}"
                ).format(database=plan.base, error=err)
            )
            return []
        sessions = [s for s in faits.get("sessions") or [] if s]
        if not sessions or systeme.maintenant() >= limite:
            return sessions
        systeme.dormir(1)


def decrire_session(session):
    """`pid 4242, odoo, odoo-4242, 192.0.2.10, idle` : les champs
    renseignés d'une session de `pg_stat_activity`."""
    morceaux = ["pid {}".format(session.get("pid", "?"))]
    for cle in ("user", "application", "client", "state"):
        valeur = session.get(cle)
        if valeur:
            morceaux.append(str(valeur))
    return ", ".join(morceaux)


def _mettre_a_jour(plan, systeme, rapport, args):
    debut_journal = odoo_instance.taille(plan.journal)
    debut_logfile = odoo_instance.taille(plan.logfile)
    depart = systeme.maintenant()
    issue = systeme.lancer_long(
        plan.commande, plan.wd, os.environ.copy(), plan.journal, args.timeout
    )
    duree = int(systeme.maintenant() - depart)
    _noter_duree(plan, systeme, service.N_("update {duration}"), depart)
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
    analyse = erreurs_du_journal(texte, args)
    if analyse.a_revoir:
        rapport.fail(
            t(
                "{count} ERROR/CRITICAL record(s) in {groups} group(s) during"
                " the update."
            ).format(
                count=analyse.a_revoir,
                groups=len(analyse.groupes_a_revoir()),
            )
        )
        montrer_groupes(rapport, analyse, 10)
        return CODE_ECHEC
    rapport.ok(
        t("Odoo finished the update by itself in {seconds} s.").format(
            seconds=duree
        )
    )
    return CODE_OK


def _comptes_de_l_instance(plan, systeme):
    """Les uid dont un serveur Odoo sans `-d` est examiné : root et le
    compte de l'unité. Un compte inconnu de passwd laisse root seul."""
    uids = {0}
    try:
        uids.add(systeme.uid(plan.utilisateur))
    except (KeyError, TypeError):
        pass
    return uids


def _genes_apres_arret(plan, systeme):
    """Ce qui tient encore la base ou le port hors de l'unité arrêtée :
    une ligne par gêne — le port qui répond, un processus Odoo lancé avec
    `-d <base>`, un serveur Odoo sans `-d` de root ou du compte de l'unité
    dont la configuration vise la base
    (`odoo_instance.processus_odoo_sans_base`, avec le `db_user` de cette
    instance : un Odoo multi-bases d'un autre rôle ne la voit pas). Un
    serveur d'un autre compte n'est pas examiné ; ses sessions sur la base
    paraissent dans `pg_stat_activity`."""
    genes = []
    if systeme.port_ecoute(plan.hote, plan.port):
        genes.append(
            t("{host}:{port} still answers.").format(
                host=plan.hote, port=plan.port
            )
        )
    processus = systeme.processus()
    exclus = systeme.pids_exclus()
    for pid, argv in odoo_instance.processus_odoo(
        plan.base, processus, exclus
    ) + odoo_instance.processus_odoo_sans_base(
        plan.base,
        processus,
        exclus,
        systeme.dossier_processus,
        db_user=plan.cible_pg.config.get("db_user", ""),
        uid_de=systeme.uid_processus,
        uids=_comptes_de_l_instance(plan, systeme),
    ):
        genes.append(f"{pid} {' '.join(argv)[:200]}")
    return genes


def _arreter_et_mettre_a_jour(plan, systeme, rapport, args):
    lanceur = systeme.lanceur
    rapport.etape(t("Stopping {unit}").format(unit=plan.unite))
    debut_arret = systeme.maintenant()
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

    genes = _genes_apres_arret(plan, systeme)
    for gene in genes:
        rapport.detail(gene)
    sessions = sessions_restantes(plan, systeme, rapport)
    for session in sessions:
        rapport.detail(decrire_session(session))
    _noter_duree(plan, systeme, service.N_("stop {duration}"), debut_arret)
    if genes or sessions:
        if not args.force:
            if genes:
                rapport.fail(
                    t(
                        "Odoo still runs on this database or port outside"
                        " the service: refused (--force to go on)."
                    )
                )
            if sessions:
                rapport.fail(
                    t(
                        "{count} PostgreSQL session(s) still connected to"
                        " {database} after the stop: refused (--force to go"
                        " on)."
                    ).format(count=len(sessions), database=plan.base)
                )
            return CODE_ECHEC
        if genes:
            rapport.attn(t("--force: going on despite the Odoo found."))
        if sessions:
            rapport.attn(
                t("--force: going on despite the PostgreSQL sessions found.")
            )

    if plan.sauvegarde:
        rapport.etape(t("Backup of {database}").format(database=plan.base))
        debut = systeme.maintenant()
        code = _sauvegarder(plan, systeme, rapport, args)
        _noter_duree(plan, systeme, service.N_("backup {duration}"), debut)
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
            # Jamais arrêté (stop sans effet) : rien à relancer, et le site
            # n'a pas été coupé.
            plan.debut_coupure = None
            return True
        debut_logfile = odoo_instance.taille(plan.logfile)
        epoque = systeme.maintenant()
        plan.epoque_relance = epoque
        plan.debut_logfile_relance = debut_logfile
        code, sortie = systemd.demarrer(plan.unite, lanceur)
        rapport.etape(t("Starting {unit}").format(unit=plan.unite))
        if code != 0:
            # Le journal de l'unité vit dans son namespace : l'option suit
            # le nom de l'unité dans la commande conseillée.
            rapport.fail(
                t(
                    "systemctl start failed (journalctl -u {unit} -n 50)."
                ).format(
                    unit=" ".join(
                        [plan.unite] + systemd.option_namespace(plan.namespace)
                    )
                )
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
        _noter_duree(plan, systeme, service.N_("start {duration}"), epoque)
        cible = warmup_http.url(plan.hote, plan.port, plan.base)
        debut_sonde = systeme.maintenant()
        code_http = systeme.sonder(cible, DELAI_SONDE)
        if not code_http:
            rapport.fail(t("No HTTP answer from {url}.").format(url=cible))
            return False
        _noter_duree(
            plan, systeme, service.N_("first answer {duration}"), debut_sonde
        )
        if code_http < CODE_SERVI and plan.debut_coupure is not None:
            plan.fin_coupure = systeme.maintenant()
        rapport.ok(t("Service started and answering: {url}").format(url=cible))

        rapport.etape(t("Errors in the Odoo log since the start"))
        texte = systeme.journal(plan.unite, epoque, plan.namespace)
        texte += "\n" + odoo_instance.lire_ajout(plan.logfile, debut_logfile)
        analyse = erreurs_du_journal(texte, args)
        if analyse.a_revoir:
            rapport.fail(
                t(
                    "{count} ERROR/CRITICAL record(s) in {groups} group(s)"
                    " since the start."
                ).format(
                    count=analyse.a_revoir,
                    groups=len(analyse.groupes_a_revoir()),
                )
            )
            montrer_groupes(rapport, analyse, 8)
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
    apres = 4 + int(args.warmup_deep) if etait_actif else 0
    rapport.total = 2 + int(plan.sauvegarde) + apres
    code = CODE_ECHEC
    if etait_actif:
        plan.debut_coupure = systeme.maintenant()
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
                    plan.relance_verifiee = _relancer_quoi_qu_il_arrive(
                        plan, systeme, rapport, args
                    )
                    if not plan.relance_verifiee and code == CODE_OK:
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
    return code


def verifier_apres_relance(plan, systeme, rapport, args):
    """Préchauffage profond (`--warmup-deep`), santé de l'instance
    relancée, puis seconde lecture du journal (`relire_le_journal`).
    Appelée hors du verrou et des signaux protégés, seulement après une
    relance vérifiée. Ne lève pas : chaque constat est un ATTN au plus, un
    FAIL de la santé compris, et une erreur ou un Ctrl-C n'y arrête que
    l'étape en cours."""
    if args.warmup_deep:
        rapport.etape(t("Deep cache warm-up"))
        debut = systeme.maintenant()
        try:
            bilan = systeme.prechauffer(plan)
            resume = t(
                "{pages} page(s), {assets} asset bundle(s) in {seconds} s."
            ).format(
                pages=bilan.pages,
                assets=bilan.assets,
                seconds=f"{bilan.duree:.1f}",
            )
            if bilan.echecs:
                rapport.attn(
                    resume
                    + " "
                    + t("{count} request(s) failed.").format(
                        count=len(bilan.echecs)
                    )
                )
                rapport.extrait(
                    [f"{quoi}: {detail}" for quoi, detail in bilan.echecs], 5
                )
            else:
                rapport.ok(resume)
        except (Exception, KeyboardInterrupt) as err:  # noqa: BLE001
            rapport.attn(
                t("Warm-up not done: {error}").format(
                    error=str(err) or type(err).__name__
                )
            )
        _noter_duree(plan, systeme, service.N_("warm-up {duration}"), debut)
    rapport.etape(t("Health check of the instance"))
    debut = systeme.maintenant()
    try:
        _version, resultats = systeme.sante(plan)
        for resultat in resultats:
            if resultat.statut == health_check.OK:
                rapport.ok(resultat.message(t))
            elif resultat.statut in (health_check.ATTN, health_check.FAIL):
                rapport.attn(resultat.message(t))
                if resultat.conseil(t):
                    rapport.detail("→ " + resultat.conseil(t))
    except (Exception, KeyboardInterrupt) as err:  # noqa: BLE001
        rapport.attn(
            t("Health check not done: {error}").format(
                error=str(err) or type(err).__name__
            )
        )
    _noter_duree(plan, systeme, service.N_("health check {duration}"), debut)
    relire_le_journal(plan, systeme, rapport, args)


def relire_le_journal(plan, systeme, rapport, args):
    """Relit le journal de l'unité et le `logfile` depuis l'époque de la
    relance, après le préchauffage et la santé : une erreur levée au
    premier rendu d'une vue ou d'un gabarit mis à jour n'y paraît qu'à ce
    moment. La première lecture, juste après la première réponse, n'avait
    rien trouvé : tout enregistrement ERROR ou CRITICAL vu ici est un ATTN,
    sans changer le code de sortie. DELAI_JOURNALD secondes d'abord, pour
    que journald ait reçu les dernières lignes. Ne lève pas. Sans époque
    de relance (l'unité tournait déjà au moment de la relancer), rien
    n'est relu."""
    if plan.epoque_relance is None:
        return
    rapport.etape(t("Errors in the Odoo log after the checks"))
    try:
        systeme.dormir(DELAI_JOURNALD)
        texte = systeme.journal(
            plan.unite, plan.epoque_relance, plan.namespace
        )
        texte += "\n" + odoo_instance.lire_ajout(
            plan.logfile, plan.debut_logfile_relance
        )
        analyse = erreurs_du_journal(texte, args)
        if analyse.a_revoir:
            rapport.attn(
                t(
                    "{count} ERROR/CRITICAL record(s) in {groups} group(s)"
                    " since the start, after the warm-up and the health"
                    " check."
                ).format(
                    count=analyse.a_revoir,
                    groups=len(analyse.groupes_a_revoir()),
                )
            )
            montrer_groupes(rapport, analyse, 8)
        else:
            rapport.ok(t("Still no ERROR or CRITICAL line since the start."))
    except (Exception, KeyboardInterrupt) as err:  # noqa: BLE001
        rapport.attn(
            t("Second read of the Odoo log not done: {error}").format(
                error=str(err) or type(err).__name__
            )
        )


def resumer_durees(plan, rapport):
    """Deux lignes après une exécution qui a arrêté l'unité : la durée de
    chaque phase, puis le temps où le site est resté coupé, de l'instant
    d'avant `systemctl stop` à la première réponse HTTP sous CODE_SERVI.
    Sans cette réponse, la ligne dit depuis quand le site est coupé."""
    if plan.durees:
        rapport.champ(
            t("Durations"),
            ", ".join(
                t(modele).format(duration=duree_lisible(secondes))
                for modele, secondes in plan.durees
            ),
        )
    if plan.debut_coupure is None:
        return
    if plan.fin_coupure is not None:
        rapport.champ(
            t("Site down"),
            t(
                "{duration}, from the stop to the first answer below 500"
            ).format(
                duration=duree_lisible(plan.fin_coupure - plan.debut_coupure)
            ),
        )
    else:
        rapport.champ(
            t("Site down"),
            t("since {time}: no answer below 500 yet").format(
                time=datetime.datetime.fromtimestamp(
                    plan.debut_coupure
                ).strftime("%H:%M:%S")
            ),
        )


def journaux_a_purger(noms, base, maintenant, jours, garder=JOURNAUX_GARDES):
    """Les noms de `noms` à supprimer : les journaux `update-<base>-
    <AAAAMMJJ-HHMMSS>.log` de CETTE base, hors des `garder` plus récents,
    dont l'horodatage du nom a plus de `jours` jours au regard de
    `maintenant` (datetime local, comme l'horodatage). `jours` à 0 ne
    purge rien. Fonction pure : le disque n'est pas lu."""
    if jours <= 0:
        return []
    motif = re.compile(
        re.escape("update-" + base + "-") + r"(\d{8}-\d{6})\.log"
    )
    dates = []
    for nom in noms:
        trouve = motif.fullmatch(nom)
        if not trouve:
            continue
        try:
            moment = datetime.datetime.strptime(
                trouve.group(1), "%Y%m%d-%H%M%S"
            )
        except ValueError:
            continue
        dates.append((moment, nom))
    dates.sort(reverse=True)
    limite = maintenant - datetime.timedelta(days=jours)
    return sorted(nom for moment, nom in dates[garder:] if moment < limite)


def purger_journaux(plan, systeme, rapport, args):
    """Retire du dossier du journal de cette exécution les anciens
    journaux de la base (`journaux_a_purger`), jamais celui de cette
    exécution. Seul un fichier ordinaire part : un lien porté par un nom
    de journal, dans un dossier temporaire partagé, reste. Une suppression
    qui échoue est passée sous silence ; le nombre retiré s'affiche."""
    dossier = os.path.dirname(plan.journal)
    try:
        noms = os.listdir(dossier)
    except OSError:
        return
    maintenant = datetime.datetime.fromtimestamp(systeme.maintenant())
    retires = 0
    for nom in journaux_a_purger(
        noms, plan.base, maintenant, args.log_keep_days
    ):
        chemin = os.path.join(dossier, nom)
        if chemin == plan.journal:
            continue
        try:
            if not stat.S_ISREG(os.lstat(chemin).st_mode):
                continue
            os.remove(chemin)
        except OSError:
            continue
        retires += 1
    if retires:
        rapport.detail(
            t(
                "{count} update log(s) of {database} older than {days}"
                " day(s) removed from {path}."
            ).format(
                count=retires,
                database=plan.base,
                days=args.log_keep_days,
                path=dossier,
            )
        )


def conclure(plan, rapport, code):
    """Les durées (`resumer_durees`), puis la dernière ligne du rapport :
    réussite ou échec de la mise à jour. La réussite nomme les modules
    que `-u` a mis à jour, ceux que la base n'a pas installés exclus."""
    resumer_durees(plan, rapport)
    if code == CODE_OK:
        rapport.ok(
            t("Update finished: {modules}").format(
                modules=",".join(modules_mis_a_jour(plan))
            )
        )
    elif code == CODE_ECHEC:
        rapport.fail(t("Update failed."))


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


TYPES = service.types_argparse(t)


def _type_regex(valeur):
    try:
        return re.compile(valeur)
    except re.error as err:
        raise argparse.ArgumentTypeError(
            t("invalid regular expression: {error}").format(error=err)
        )


def construire_parseur():
    """Le parser de la ligne de commande, sans rien analyser ni lancer :
    le catalogue des réglages en tire les métadonnées des options."""
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
        type=TYPES.unite,
        help=t(
            "systemd unit; default: the unit whose WorkingDirectory is this"
            " checkout, else the only active one."
        ),
    )
    parser.add_argument(
        "--db",
        type=TYPES.base,
        help=t("Database; default: -d of the unit, else db_name."),
    )
    parser.add_argument(
        "--odoo-conf",
        help=t("Odoo configuration file; default: the one the unit reads."),
    )
    parser.add_argument(
        "--user",
        type=TYPES.utilisateur,
        help=t("Account running the update; default: User= of the unit."),
    )
    parser.add_argument(
        "--timeout",
        type=TYPES.secondes,
        default=DELAI_MISE_A_JOUR,
        help=t("Maximum seconds for the backup and for the update."),
    )
    parser.add_argument(
        "--start-wait",
        type=TYPES.secondes,
        default=DELAI_DEMARRAGE,
        help=t("Maximum seconds for the service to listen after start."),
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help=t("Do not back up the database before the update."),
    )
    parser.add_argument(
        "--backup-dest",
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
        help=t(
            "ERROR/CRITICAL records whose header line or final exception"
            " matches REGEX do not fail; repeatable."
        ),
    )
    parser.add_argument(
        "--log-dir",
        help=t("Directory of the update log; default: {path}.").format(
            path=DOSSIER_JOURNAUX
        ),
    )
    parser.add_argument(
        "--log-keep-days",
        type=TYPES.entier,
        default=JOURS_JOURNAUX,
        metavar="DAYS",
        help=t(
            "After the run, remove the update logs of the database older"
            " than DAYS days, the {count} most recent always kept; 0 keeps"
            " them all. Default: {days}."
        ).format(count=JOURNAUX_GARDES, days=JOURS_JOURNAUX),
    )
    parser.add_argument(
        "--warmup-deep",
        action="store_true",
        help=t(
            "After a verified restart, warm up public pages and asset"
            " bundles (warmup_http.py --deep)."
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
    return parser


def valider(parser, args):
    """Contrôles d'après analyse, profil déjà posé : aplatit
    `args.modules` et refuse `all` mêlé à d'autres modules (code 2, par
    `parser.error`)."""
    args.modules = [m for groupe in args.modules for m in groupe]
    if "all" in args.modules and len(args.modules) > 1:
        parser.error(t("'all' cannot be combined with other modules."))


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
    # Le système se construit après l'analyse (`--verbose`) : la devinette
    # de l'unité du profil passe alors par le lanceur par défaut.
    args = analyser(
        argv,
        lanceur=systeme.lanceur if systeme is not None else systemd.lancer,
    )
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
        rapport.erreur(err.message(t))
        return CODE_REFUS
    except KeyboardInterrupt:
        return CODE_INTERROMPU
    afficher_plan(plan, rapport, args)
    if args.dry_run:
        simuler(plan, rapport, args)
        return CODE_OK
    if systeme.euid() != 0:
        rapport.erreur(t("Root is required (sudo), except with --dry-run."))
        return CODE_REFUS
    # Construit dans le `try` : un verrou partagé dont le dossier manque
    # lève dès sa construction (voir lock.Verrou).
    try:
        verrou = systeme.verrou(plan.base)
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
        code = executer(plan, systeme, rapport, args)
    finally:
        verrou.relacher()
    if code == CODE_OK and plan.relance_verifiee:
        verifier_apres_relance(plan, systeme, rapport, args)
    purger_journaux(plan, systeme, rapport, args)
    conclure(plan, rapport, code)
    return code


if __name__ == "__main__":
    sys.exit(main())
