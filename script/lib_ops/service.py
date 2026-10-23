# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Détecter l'instance Odoo qu'une unité systemd fait tourner.

Ce que plusieurs outils d'exploitation partagent : retrouver l'unité, son
compte, son dossier de travail, sa ligne de commande, son environnement,
le fichier de configuration qu'Odoo lit et la base visée ; construire une
commande lancée sous le compte de l'unité, ou y exécuter une fonction
(`SystemeBase.sous_le_compte`) ; savoir si ce compte peut écrire dans un
dossier.

Les fonctions `detecter_*` remplissent un objet `plan` quelconque, par
attributs (`unite`, `utilisateur`, `wd`, `execstart`, `config_path`,
`base`…), et lèvent `Refus` sur ce qui manque. Ce module ne traduit rien :
`Refus` porte le MODÈLE anglais du message et ses valeurs, et l'outil qui
l'attrape le traduit par sa propre fonction `t()` (`message(t)`). Les
modèles sont marqués par `N_()`, qui ne fait rien à l'exécution et permet
à un test de vérifier qu'ils ont tous une traduction.

`SystemeBase` regroupe les effets de bord communs ; un test en dérive une
classe qui les remplace, et aucune commande réelle n'est lancée.

Bibliothèque standard seulement, sans syntaxe postérieure à Python 3.7.
"""

from __future__ import annotations

import argparse
import errno
import grp
import json
import os
import pwd
import re
import shlex
import stat
import sys
import time
import types

from script.lib_ops import lock, odoo_instance, postgres, systemd

RE_UTILISATEUR = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_.-]*")


def N_(texte):
    """Marque un modèle de message à traduire par l'outil appelant."""
    return texte


class Refus(Exception):
    """Refus avant toute action : `modele` (anglais) et ses `valeurs`.

    `str()` rend le message anglais formé ; `message(t)` le rend traduit.
    Un message déjà traduit et formé passe aussi, sans valeurs.
    """

    def __init__(self, modele, **valeurs):
        self.modele = modele
        self.valeurs = valeurs
        super().__init__(modele.format(**valeurs) if valeurs else modele)

    def message(self, t=None):
        texte = t(self.modele) if t else self.modele
        return texte.format(**self.valeurs) if self.valeurs else texte


class Interruption(BaseException):
    """SIGTERM ou SIGHUP reçu. Hérite de BaseException comme
    KeyboardInterrupt : un `except Exception` d'étape ne l'avale pas."""


class EchecSousCompte(OSError):
    """La fonction lancée par `SystemeBase.sous_le_compte` a levé dans le
    processus enfant ; porte son message. Hérite d'OSError : l'appelant
    qui traite déjà l'échec d'une écriture traite aussi celui-ci."""


def nom_verrou(base):
    """Le nom du verrou d'une base, partagé par tous les outils qui la
    touchent : `erplibre-db-<base>` (fichier `<nom>.lock`)."""
    return f"erplibre-db-{base}"


def joindre(argv):
    """La commande telle qu'on la taperait dans un shell."""
    return " ".join(shlex.quote(str(a)) for a in argv)


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


class SystemeBase:
    """Les effets de bord communs aux outils d'exploitation.

    `verbeux` trace chaque commande sur stderr (`+ commande`).
    `dossier_verrou` remplace /run/lock (un test y met un dossier
    temporaire).
    """

    def __init__(self, verbeux=False, dossier_verrou=None):
        self.verbeux = verbeux
        self.dossier_verrou = dossier_verrou

    def _tracer(self, argv):
        if self.verbeux:
            print(f"+ {joindre(argv)}", file=sys.stderr, flush=True)

    def lanceur(self, argv, timeout=60):
        """Le lanceur passé à `systemd` : (code, sortie), ne lève pas."""
        self._tracer(argv)
        return systemd.lancer(argv, timeout)

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

    def maintenant(self):
        return time.time()

    def verrou(self, base):
        """Le verrou de la base, partagé entre outils et entre comptes : il
        ne se replie jamais ailleurs que /run/lock (voir lock.py). Le
        dossier absent lève VerrouIndisponible dès la construction."""
        return lock.Verrou(nom_verrou(base), self.dossier_verrou, True)

    def inscriptible(self, dossier, utilisateur):
        return dossier_inscriptible(dossier, utilisateur)

    def uid(self, utilisateur):
        """L'uid du compte. Lève KeyError s'il n'existe pas."""
        return pwd.getpwnam(utilisateur).pw_uid

    def chown(self, chemin, utilisateur):
        """Donne `chemin` au compte, groupe principal de passwd compris,
        sans suivre un lien symbolique. Lève OSError ou KeyError."""
        compte = pwd.getpwnam(utilisateur)
        os.chown(chemin, compte.pw_uid, compte.pw_gid, follow_symlinks=False)

    def fchown(self, fd, utilisateur):
        """Donne au compte le fichier ouvert sur `fd` : le changement vise
        l'inode ouvert, quoi que soit devenu son nom entre-temps. Lève
        OSError ou KeyError."""
        compte = pwd.getpwnam(utilisateur)
        os.fchown(fd, compte.pw_uid, compte.pw_gid)

    def mkdir(self, dossier, mode):
        """Crée `dossier` au compte courant, `mode` appliqué malgré
        l'umask, sur le dossier créé lui-même (voir `_ouvrir_cree`)."""
        os.mkdir(dossier, mode)
        try:
            fd = _ouvrir_cree(dossier)
            try:
                os.fchmod(fd, mode)
            finally:
                os.close(fd)
        except OSError:
            _retirer_vide(dossier)
            raise

    def creer_dossier(self, dossier, utilisateur, mode=0o750):
        """Crée `dossier` (`mode`, umask ignoré) et le donne au compte
        `utilisateur`. Lève OSError ou KeyError ; un dossier créé dont le
        chown échoue est retiré, pour qu'il ne reste pas un dossier de root
        où le compte ne peut pas écrire.

        Mode et propriétaire se posent par descripteur sur le dossier que
        CET appel a créé : un nom remplacé entre `mkdir` et le `chown` par
        un lien, ou par un autre dossier, refuse au lieu de donner sa cible
        au compte."""
        compte = pwd.getpwnam(utilisateur)
        os.mkdir(dossier, mode)
        try:
            fd = _ouvrir_cree(dossier)
            try:
                os.fchmod(fd, mode)
                os.fchown(fd, compte.pw_uid, compte.pw_gid)
            finally:
                os.close(fd)
        except OSError:
            _retirer_vide(dossier)
            raise

    def devenir(self, utilisateur):
        """Prend l'identité du compte dans le processus courant : groupes
        secondaires, groupe principal, puis uid, dans cet ordre — après
        `setuid`, plus rien ne se change. Sans retour possible : réservé
        au processus enfant de `sous_le_compte`."""
        compte = pwd.getpwnam(utilisateur)
        os.setgroups(os.getgrouplist(utilisateur, compte.pw_gid))
        os.setgid(compte.pw_gid)
        os.setuid(compte.pw_uid)

    def sous_le_compte(self, utilisateur, fonction, *arguments):
        """`fonction(*arguments)` exécutée sous le compte `utilisateur` ;
        rend sa valeur, qui doit s'écrire en JSON.

        Hors root, l'appel est direct : le compte courant est déjà le bon.
        Sous root, un processus enfant (`fork`) prend l'identité du compte
        (`devenir`) avant d'appeler `fonction`, et renvoie sa valeur ou son
        erreur par un tube. Tout ce que `fonction` écrit l'est donc avec
        les droits du compte : un lien qu'il aurait posé ne mène nulle part
        où il ne pourrait pas écrire lui-même. L'enfant hérite des
        descripteurs ouverts (un zip déjà ouvert se lit), sort par
        `os._exit` sans vider les tampons du parent, et le parent attend
        sa fin même interrompu. Lève EchecSousCompte si `fonction` lève.
        """
        if self.euid() != 0:
            return fonction(*arguments)
        lecture, ecriture = os.pipe()
        pid = os.fork()
        if pid == 0:  # pragma: no cover - processus enfant
            os.close(lecture)
            code = 1
            try:
                self.devenir(utilisateur)
                reponse = {"valeur": fonction(*arguments)}
                code = 0
            except BaseException as err:
                reponse = {"erreur": str(err) or type(err).__name__}
            try:
                donnees = json.dumps(reponse).encode("utf-8")
                while donnees:
                    donnees = donnees[os.write(ecriture, donnees) :]
            finally:
                os._exit(code)
        os.close(ecriture)
        morceaux = []
        try:
            while True:
                bloc = os.read(lecture, 65536)
                if not bloc:
                    break
                morceaux.append(bloc)
        finally:
            os.close(lecture)
            _attendre(pid)
        try:
            reponse = json.loads(b"".join(morceaux).decode("utf-8"))
        except ValueError:
            reponse = {}
        if "valeur" in reponse:
            return reponse["valeur"]
        raise EchecSousCompte(
            reponse.get("erreur") or f"{utilisateur}: no answer"
        )


def _ouvrir_cree(dossier):
    """Un descripteur sur le dossier que l'appelant vient de créer : sans
    suivre de lien (O_NOFOLLOW), et au compte courant — un dossier d'un
    autre compte mis à sa place refuse (EPERM)."""
    fd = os.open(dossier, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    if os.fstat(fd).st_uid != os.geteuid():
        os.close(fd)
        raise OSError(errno.EPERM, "replaced after its creation", dossier)
    return fd


def _retirer_vide(dossier):
    """Retire `dossier` s'il est vide ; un échec est ignoré (rmdir ne
    suit pas de lien et ne vide rien)."""
    try:
        os.rmdir(dossier)
    except OSError:
        pass


def _attendre(pid):
    """Attend la fin du processus `pid`, interruptions ignorées : un
    enfant n'est jamais laissé derrière."""
    while True:
        try:
            os.waitpid(pid, 0)
            return
        except ChildProcessError:
            return
        except (KeyboardInterrupt, Interruption):
            continue


def detecter_unite(explicite, systeme, racine, plan):
    """Nomme l'unité dans `plan` (`unite`, `origine_unite`) et rend ses
    propriétés `systemctl show`."""
    lanceur = systeme.lanceur
    if explicite:
        plan.unite, plan.origine_unite = explicite, "--service"
    else:
        try:
            plan.unite, plan.origine_unite = systemd.deviner_unite(
                racine, lanceur
            )
        except systemd.ErreurUnite as err:
            if err.candidates and str(err) == "ambiguous":
                raise Refus(
                    N_(
                        "Several Odoo services are possible, choose one"
                        " with --service: {names}"
                    ),
                    names=", ".join(err.candidates),
                )
            raise Refus(N_("No Odoo service found: name it with --service."))
    try:
        props = systemd.lire_proprietes(plan.unite, lanceur=lanceur)
    except systemd.ErreurUnite as err:
        raise Refus(
            N_("Cannot read the service {unit}: {error}"),
            unit=plan.unite,
            error=err,
        )
    if props["LoadState"] in ("", "not-found"):
        raise Refus(
            N_("Service {unit} not found (systemctl)."), unit=plan.unite
        )
    return props


def detecter_compte_et_dossier(explicite, systeme, plan, props):
    """Compte (`utilisateur`, `courant`, `home`), ExecStart, Environment et
    dossier de travail (`wd`) dans `plan`."""
    plan.courant = systeme.utilisateur_courant()
    plan.utilisateur = explicite or props["User"] or plan.courant
    plan.home = systeme.home(plan.utilisateur)
    plan.execstart = systemd.argv_execstart(props["ExecStart"])
    if not plan.execstart:
        raise Refus(
            N_("The service {unit} has no ExecStart."), unit=plan.unite
        )
    plan.env_unite = systemd.environnement(props["Environment"])
    plan.wd = systemd.dossier_de_travail(props["WorkingDirectory"], plan.home)
    if not plan.wd and odoo_instance.lance_run_sh(plan.execstart):
        run_sh = [a for a in plan.execstart if os.path.basename(a) == "run.sh"]
        plan.wd = os.path.dirname(run_sh[0])
    if not plan.wd or not os.path.isdir(plan.wd):
        raise Refus(
            N_("The working directory of {unit} is unknown or missing."),
            unit=plan.unite,
        )


def detecter_config(explicite, plan):
    """Le fichier de configuration dans `plan` (`config_path`,
    `origine_config`) ; rend son contenu."""
    try:
        plan.config_path, plan.origine_config = odoo_instance.trouver_config(
            plan.execstart, plan.wd, plan.env_unite, explicite
        )
    except odoo_instance.ErreurDetection:
        raise Refus(N_("No Odoo configuration file found (try --odoo-conf)."))
    try:
        return odoo_instance.lire_config(plan.config_path)
    except OSError:
        raise Refus(
            N_("Cannot read {path}: run with sudo."), path=plan.config_path
        )


def detecter_base(explicite, plan, config):
    """La base dans `plan` (`base`, `origine_base`), validée."""
    plan.base, plan.origine_base = odoo_instance.trouver_base(
        explicite, plan.execstart, config
    )
    if not plan.base:
        raise Refus(
            N_(
                "Database not found in the service nor in its configuration:"
                " specify --db."
            )
        )
    if not postgres.nom_valide(plan.base):
        raise Refus(
            N_("Invalid database name: {database}"), database=plan.base
        )


def detecter_instance(args, systeme, racine, plan):
    """Unité, compte, dossier, configuration et base, dans `plan`, depuis
    `args.service`, `args.user`, `args.odoo_conf` et `args.db`. Rend la
    configuration lue."""
    props = detecter_unite(args.service, systeme, racine, plan)
    detecter_compte_et_dossier(args.user, systeme, plan, props)
    config = detecter_config(args.odoo_conf, plan)
    detecter_base(args.db, plan, config)
    return config


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
    compte de l'unité n'est pas le compte courant. Les valeurs sont
    visibles dans la ligne de commande : jamais de secret ici."""
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


def types_argparse(t):
    """Les convertisseurs argparse communs, messages traduits par `t` :
    `unite`, `base`, `utilisateur`, `secondes` (entier ≥ 1), `entier`
    (entier ≥ 0)."""

    def unite(valeur):
        try:
            return systemd.nom_unite(valeur)
        except ValueError:
            raise argparse.ArgumentTypeError(
                t("invalid service name: {name}").format(name=valeur)
            )

    def base(valeur):
        if not postgres.nom_valide(valeur):
            raise argparse.ArgumentTypeError(
                t("Invalid database name: {database}").format(database=valeur)
            )
        return valeur

    def utilisateur(valeur):
        if RE_UTILISATEUR.fullmatch(valeur) is None:
            raise argparse.ArgumentTypeError(
                t("invalid user name: {name}").format(name=valeur)
            )
        return valeur

    def secondes(valeur):
        try:
            nombre = int(valeur)
        except ValueError:
            nombre = 0
        if nombre < 1:
            raise argparse.ArgumentTypeError(
                t("expected an integer >= 1: {value}").format(value=valeur)
            )
        return nombre

    def entier(valeur):
        try:
            nombre = int(valeur)
        except ValueError:
            nombre = -1
        if nombre < 0:
            raise argparse.ArgumentTypeError(
                t("expected an integer >= 0: {value}").format(value=valeur)
            )
        return nombre

    return types.SimpleNamespace(
        unite=unite,
        base=base,
        utilisateur=utilisateur,
        secondes=secondes,
        entier=entier,
    )
