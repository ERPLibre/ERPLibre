#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Sauvegardes vérifiées d'une base Odoo servie par systemd.

Les modes
---------
- (défaut) sauvegarder la base, puis la copier hors site (`--copy-to`) et
  appliquer la rétention ;
- `--status` : l'âge de la dernière sauvegarde réussie de chaque base ;
- `--test-restore` : restaurer la dernière sauvegarde (ou `--file`) dans
  une base TEMPORAIRE, la contrôler, puis la supprimer ;
- `--restore --file F --into NOUVELLE` : restaurer dans une base qui
  n'existe pas encore, jamais par-dessus une base existante.

L'instance se détecte comme pour `update_module` : l'unité (`--service`,
sinon celle dont WorkingDirectory est ce checkout, sinon la seule
active), son compte, sa configuration Odoo, la base (`--db`, sinon `-d`
de l'unité, sinon `db_name`), et son dossier de données, dans l'ordre
qu'Odoo suit (voir `odoo_instance.data_dir`).

La sauvegarde
-------------
Le format est celui d'Odoo, que `/web/database/manager` restaure tel
quel : un zip qui contient `dump.sql` (pg_dump au format texte, sans
propriétaires), `manifest.json` (les clés de `dump_db_manifest` d'Odoo)
et `filestore/`. La sortie de pg_dump s'écrit DIRECTEMENT dans le membre
`dump.sql` du zip, sans fichier intermédiaire : l'espace exigé, vérifié
avant d'écrire quoi que ce soit, est `(taille de la base + filestore) ×
1,2`. Le filestore est lu APRÈS le dump : une pièce jointe ajoutée pendant
le dump n'y manque pas. Seuls les fichiers ordinaires y entrent ; un lien
symbolique est écarté et signalé — lu par root, il ferait entrer dans la
sauvegarde la cible qu'un compte y aurait plantée.

Le zip s'écrit sous `<final>.partial`, relu en entier (CRC de chaque
membre, marque de fin de pg_dump au bout de `dump.sql`, manifeste lisible),
synchronisé sur disque, puis renommé : un fichier au nom définitif est
toujours une sauvegarde complète. Une empreinte `<final>.sha256` au format
de `sha256sum` l'accompagne. Nom : `<dest>/<base>/<base>_<AAAA-MM-JJ>_
<HH>h<MM>m<SS>s.zip`. Fichiers 0600, dossier de la base 0700, au compte
de l'unité.

Un filestore absent est un avertissement quand la base ne stocke aucune
pièce jointe sur disque, un échec sinon.

PostgreSQL et les comptes
-------------------------
pg_dump, psql, createdb et dropdb tournent sous le compte de l'unité :
directement si c'est le compte courant, par `runuser -u COMPTE --` sous
root ; tout autre compte est refusé (code 2), sauf `--dry-run` et
`--status`. La connexion est celle d'Odoo (`db_host`, `db_port`,
`db_user`, `db_password`, `db_sslmode`, et `pg_path` pour trouver les
outils), passée par l'environnement et jamais par la ligne de commande
(voir `lib_ops/postgres.py`). Aucun nom n'est interpolé dans du SQL.

Sous root, le compte de l'unité possède les dossiers où root écrit et
lit, et peut y remplacer un nom par un lien à tout moment. Le zip
provisoire, l'empreinte et l'état reçoivent donc mode et propriétaire par
leur DESCRIPTEUR, un état existant ne se lit pas à travers un lien, et le
filestore se lit par descripteurs (`_ecrire_filestore`). Le filestore
d'une restauration, lui, s'écrit dans un processus enfant devenu ce compte
(`SystemeBase.sous_le_compte`) : ce qu'il crée, il aurait pu le créer
lui-même.

La place d'une restauration
---------------------------
Une restauration, d'essai ou non, charge une copie complète dans le
même serveur PostgreSQL que la production : un volume plein y ferait
échouer toutes les bases. Avant createdb, l'espace libre du
`data_directory` doit couvrir l'estimation de `taille_base_estimee`,
marge comprise ; un `data_directory` illisible ou distant refuse, sauf
`--force-space`.

Le verrou
---------
Le mode sauvegarde prend le verrou de la base, `erplibre-db-<base>`, le
même qu'`update_module` : une sauvegarde ne court jamais pendant une mise
à jour. La fonction `sauvegarder()`, elle, ne le prend pas :
`update_module` l'appelle en le détenant déjà. La restauration prend le
verrou de la NOUVELLE base. La restauration d'essai n'en prend aucun :
elle garde le zip ouvert, et une rétention qui le supprimerait pendant ce
temps ne lui retire pas le fichier.

L'état
------
Chaque base a son fichier `<state-dir>/<base>/state.json` (dernier succès,
dernier échec, dernière copie), réécrit par fichier temporaire puis
renommage. Un échec n'écrase jamais le dernier succès. Fichier et
dossier sont lisibles par tous (0644, 0755) : `--status` se lance sans
sudo.

Codes de sortie : 0 réussi ; 1 échec (sauvegarde, vérification, copie,
état trop ancien ou absent, restauration d'essai) ; 2 refusé avant de
commencer ; 75 verrou pris ; 130 interrompu. Un fichier provisoire est
retiré sur interruption (Ctrl-C, SIGTERM, SIGHUP), et une base créée par
une restauration en échec est supprimée.

`--dry-run` fait toute la détection et affiche les commandes exactes
(mot de passe masqué) ; il n'écrit rien, ne prend aucun verrou et ne
demande pas root.

Bibliothèque standard seulement, sans syntaxe postérieure à Python 3.7 :
le programme se lance aussi par le python3 d'un serveur de production.
"""

from __future__ import annotations

import argparse
import datetime
import errno
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import types
import zipfile
import zlib

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.lib_ops import (  # noqa: E402
    lock,
    odoo_instance,
    postgres,
    report,
    retention,
    service,
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
CODE_VERROU = 75
CODE_INTERROMPU = 130

DEST_PAR_DEFAUT = "/var/backups/erplibre"
ETAT_PAR_DEFAUT = "/var/lib/erplibre-backup"
NOM_ETAT = "state.json"
GARDE_QUOTIDIEN = 7
GARDE_HEBDO = 4
GARDE_MENSUEL = 12
GARDE_RECENTS = 2
AGE_MAX = 26

# Marge sur l'estimation de l'espace : le zip d'un dump texte est plus
# petit que la base, mais un filestore déjà compressé ne rétrécit pas.
MARGE = 1.2
# Une base restaurée pèse jusqu'au double de son dump texte : le dump ne
# porte que la définition des index, le chargement les reconstruit.
FACTEUR_DUMP = 2
DELAI_REQUETE = 120
DELAI_SAUVEGARDE = 6 * 3600
DELAI_CHARGEMENT = 6 * 3600
DELAI_COPIE = 6 * 3600
DELAI_COMMANDE = 600
# Délai de grâce entre TERM et KILL d'un outil interrompu.
GRACE = 10
BLOC = 1024 * 1024
# Volume de stderr gardé par commande, et longueur montrée d'un échec.
LIMITE_ERREUR = 64 * 1024
EXTRAIT = 300
LIGNES_ERREUR_MAX = 2000

MODE_FICHIER = 0o600
MODE_DOSSIER = 0o700
# Taille lue au plus d'un fichier d'état : il en fait quelques centaines
# d'octets, et un fichier géant posé à sa place ne remplit pas la mémoire.
TAILLE_ETAT_MAX = 1024 * 1024
MODE_PARTAGE = 0o755
MODE_ETAT = 0o644

SSH_COPIE = "ssh -o BatchMode=yes -o ConnectTimeout=20"
# Destination d'une copie : `[compte@]hôte:/chemin` ou un chemin absolu.
RE_COPIE_DISTANTE = re.compile(r"(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9.-]+:/\S*")
RE_COPIE_LOCALE = re.compile(r"/\S*")

Refus = service.Refus
Interruption = service.Interruption
N_ = service.N_


class ErreurPg(Exception):
    """Une commande PostgreSQL a échoué ; porte son message d'erreur."""


class ManqueEspace(service.Refus):
    """L'espace libre manque, ou ne se lit pas : la sauvegarde est refusée
    avant d'écrire quoi que ce soit (code 2)."""


class Echec(Exception):
    """Une étape de la sauvegarde ou de la restauration a échoué ; le
    message, déjà traduit, dit laquelle."""


def humain(octets):
    """Une taille lisible : 1.5 GiB, 320.0 KiB, 12 B."""
    valeur = float(octets or 0)
    for unite in ("B", "KiB", "MiB", "GiB", "TiB"):
        if valeur < 1024 or unite == "TiB":
            if unite == "B":
                return f"{int(valeur)} B"
            return f"{valeur:.1f} {unite}"
        valeur /= 1024
    return f"{valeur:.1f} TiB"


class Systeme(service.SystemeBase):
    """Les effets de bord de l'outil : commandes PostgreSQL et rsync,
    espace disque, propriété des fichiers. Un test en dérive une classe et
    aucune commande réelle n'est lancée."""

    def requete(self, argv, env, delai=DELAI_REQUETE):
        """Lance `argv` et rend (code, stdout, stderr). Ne lève jamais : un
        binaire absent rend 127, un délai dépassé 124."""
        self._tracer(argv)
        try:
            fin = subprocess.run(
                argv,
                env=env,
                cwd="/",
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=delai,
            )
        except subprocess.TimeoutExpired:
            return 124, "", "timeout"
        except OSError as err:
            return 127, "", str(err)
        return fin.returncode, fin.stdout or "", fin.stderr or ""

    def flux(self, argv, env, recevoir, delai):
        """Lance `argv` et passe sa sortie à `recevoir(bloc)` au fil de
        l'eau : (code, stderr, tué).

        Le processus a sa propre session : un Ctrl-C du terminal n'atteint
        que ce programme, qui arrête alors le groupe (TERM, puis KILL),
        ATTEND sa fin, et laisse remonter l'exception. Au-delà de `delai`
        secondes, le groupe est tué et `tué` est vrai. Une exception de
        `recevoir` (disque plein) arrête aussi le processus.
        """
        self._tracer(argv)
        proc = subprocess.Popen(
            argv,
            env=env,
            cwd="/",
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        erreurs = []
        lecteur = threading.Thread(
            target=_lire_borne, args=(proc.stderr, erreurs), daemon=True
        )
        lecteur.start()
        expire = []
        minuterie = threading.Timer(
            delai, lambda: expire.append(1) or _signaler(proc, signal.SIGKILL)
        )
        minuterie.daemon = True
        minuterie.start()
        try:
            lire = getattr(proc.stdout, "read1", proc.stdout.read)
            while True:
                bloc = lire(BLOC)
                if not bloc:
                    break
                recevoir(bloc)
            code = proc.wait()
        except BaseException:
            _terminer(proc)
            raise
        finally:
            minuterie.cancel()
            proc.stdout.close()
            lecteur.join(5)
        texte = b"".join(erreurs).decode("utf-8", "replace")
        return code, texte, bool(expire)

    def alimenter(self, argv, env, morceaux, delai):
        """Lance `argv` en lui donnant `morceaux` (itérable d'octets) sur
        son entrée : (code, lignes de stderr, tué). Mêmes règles
        d'interruption et de délai que `flux`."""
        self._tracer(argv)
        proc = subprocess.Popen(
            argv,
            env=env,
            cwd="/",
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        lignes = []
        lecteur = threading.Thread(
            target=_lire_lignes, args=(proc.stderr, lignes), daemon=True
        )
        lecteur.start()
        expire = []
        minuterie = threading.Timer(
            delai, lambda: expire.append(1) or _signaler(proc, signal.SIGKILL)
        )
        minuterie.daemon = True
        minuterie.start()
        try:
            try:
                for morceau in morceaux:
                    proc.stdin.write(morceau)
                proc.stdin.close()
            except BrokenPipeError:
                pass
            code = proc.wait()
        except BaseException:
            _terminer(proc)
            raise
        finally:
            minuterie.cancel()
            lecteur.join(5)
        return code, lignes, bool(expire)

    def espace_libre(self, chemin):
        """Les octets disponibles pour un compte ordinaire. Lève OSError."""
        info = os.statvfs(chemin)
        return info.f_bavail * info.f_frsize

    def taille_dossier(self, chemin):
        """(octets, nombre) des fichiers ordinaires sous `chemin`, liens
        non suivis."""
        octets = nombre = 0
        for dossier, _sous, fichiers in os.walk(chemin):
            for nom in fichiers:
                try:
                    info = os.lstat(os.path.join(dossier, nom))
                except OSError:
                    continue
                if stat.S_ISREG(info.st_mode):
                    octets += info.st_size
                    nombre += 1
        return octets, nombre


def _lire_borne(flux, morceaux):
    """Lit `flux` jusqu'au bout en gardant au plus LIMITE_ERREUR octets :
    un outil bavard sur stderr ne remplit jamais le tube."""
    garde = 0
    for ligne in iter(flux.readline, b""):
        if garde < LIMITE_ERREUR:
            morceaux.append(ligne[: LIMITE_ERREUR - garde])
            garde += len(ligne)
    flux.close()


def _lire_lignes(flux, lignes):
    """Lit `flux` jusqu'au bout ; garde au plus LIGNES_ERREUR_MAX lignes."""
    for ligne in iter(flux.readline, b""):
        if len(lignes) < LIGNES_ERREUR_MAX:
            lignes.append(ligne.decode("utf-8", "replace").rstrip("\n"))
    flux.close()


def _signaler(proc, numero):
    try:
        os.killpg(proc.pid, numero)
    except (ProcessLookupError, PermissionError):
        if proc.poll() is None:
            try:
                proc.send_signal(numero)
            except OSError:
                pass


def _terminer(proc):
    """TERM au groupe, KILL après GRACE secondes, puis ATTEND sa fin ; les
    interruptions reçues pendant l'attente sont ignorées."""
    if proc.poll() is not None:
        return
    _signaler(proc, signal.SIGTERM)
    limite = time.monotonic() + GRACE
    while proc.poll() is None and time.monotonic() < limite:
        try:
            proc.wait(timeout=max(0.1, limite - time.monotonic()))
        except subprocess.TimeoutExpired:
            break
        except (KeyboardInterrupt, Interruption):
            continue
    _signaler(proc, signal.SIGKILL)
    while proc.poll() is None:
        try:
            proc.wait()
        except (KeyboardInterrupt, Interruption):
            continue


class Cible:
    """Ce qu'il faut savoir pour sauvegarder ou restaurer une base."""

    def __init__(self, **valeurs):
        self.unite = ""
        self.utilisateur = ""
        self.courant = ""
        self.home = ""
        self.wd = ""
        self.execstart = []
        self.env_unite = {}
        self.config_path = ""
        self.config = {}
        self.base = ""
        self.origine_base = ""
        self.data_dir = ""
        self.origine_data_dir = ""
        self.filestore = ""
        self.dest = DEST_PAR_DEFAUT
        self.dossier = ""
        self.etat_dir = ETAT_PAR_DEFAUT
        self.dossier_etat = ""
        # Vrai sous root : les fichiers créés sont donnés au compte.
        self.root = False
        # Vrai quand une simulation sans root a prévu un dossier que seul
        # root peut créer : l'exécution réelle le fera sous sudo.
        self.creation_sudo = False
        # Vrai si les commandes PostgreSQL peuvent tourner sous le compte
        # (root, ou le compte lui-même).
        self.interrogeable = False
        self.prefixe = []
        self.outils = {}
        self.__dict__.update(valeurs)


class Resultat:
    """L'issue d'une sauvegarde : code, chemin, taille, empreinte."""

    def __init__(self, code, chemin="", taille=0, sha256="", message=""):
        self.code = code
        self.chemin = chemin
        self.taille = taille
        self.sha256 = sha256
        self.message = message
        self.etat_ok = True


def preparer_cible(plan, config, dest, etat_dir, systeme):
    """La Cible d'une instance détectée (`plan` porte unite, utilisateur,
    courant, home, wd, execstart, env_unite, config_path, base)."""
    cible = Cible(
        unite=plan.unite,
        utilisateur=plan.utilisateur,
        courant=plan.courant,
        home=plan.home,
        wd=plan.wd,
        execstart=list(plan.execstart),
        env_unite=dict(plan.env_unite),
        config_path=plan.config_path,
        config=dict(config),
        base=getattr(plan, "base", "") or "",
        origine_base=getattr(plan, "origine_base", "") or "",
    )
    cible.data_dir, cible.origine_data_dir = odoo_instance.data_dir(
        cible.execstart, config, cible.home, cible.wd, cible.env_unite
    )
    if cible.base:
        cible.filestore = odoo_instance.filestore(cible.data_dir, cible.base)
    cible.dest = os.path.abspath(dest or DEST_PAR_DEFAUT)
    cible.etat_dir = os.path.abspath(etat_dir or ETAT_PAR_DEFAUT)
    if cible.base:
        cible.dossier = os.path.join(cible.dest, cible.base)
        cible.dossier_etat = os.path.join(cible.etat_dir, cible.base)
    cible.root = systeme.euid() == 0
    meme_compte = cible.utilisateur == cible.courant
    cible.interrogeable = meme_compte or cible.root
    if not meme_compte:
        cible.prefixe = ["runuser", "-u", cible.utilisateur, "--"]
    cible.outils = {
        nom: postgres.outil(nom, config)
        for nom in ("pg_dump", "psql", "createdb", "dropdb")
    }
    return cible


def argv_pg(cible, nom, *arguments):
    """La commande de l'outil PostgreSQL `nom`, sous le compte de l'unité."""
    return cible.prefixe + [cible.outils.get(nom, nom)] + list(arguments)


def variables_pg(cible, lecture_seule=False):
    """Les variables PostgreSQL de la cible, plus HOME du compte (où libpq
    cherche ~/.pgpass)."""
    variables = postgres.env_pg(cible.config, lecture_seule, DELAI_REQUETE)
    variables["HOME"] = cible.home
    return variables


def env_pg(cible, lecture_seule=False):
    env = os.environ.copy()
    env.update(variables_pg(cible, lecture_seule))
    return env


def decrire(argv, variables=None):
    """Une commande pour l'affichage : variables (secrets masqués) puis
    argv cité pour un shell."""
    devant = ""
    if variables:
        masquees = postgres.masquer(variables)
        devant = " ".join(
            "{}={}".format(
                cle,
                valeur
                if valeur == postgres.MASQUE
                else service.joindre([valeur]),
            )
            for cle, valeur in sorted(masquees.items())
            if cle.startswith("PG")
        )
    texte = service.joindre(argv)
    return f"{devant} {texte}".strip()


def argv_psql(cible, base, sql):
    return argv_pg(
        cible, "psql", "-X", "-w", "-q", "-tA", "-d", base, "-c", sql
    )


def argv_dump(cible):
    return argv_pg(cible, "pg_dump", "--no-owner", cible.base)


def argv_createdb(cible, nom):
    # Comme `_create_empty_database` d'Odoo : UTF-8, collation C, modèle
    # template0.
    return argv_pg(
        cible,
        "createdb",
        "-w",
        "-E",
        "UTF8",
        "-T",
        "template0",
        "--lc-collate=C",
        "--",
        nom,
    )


def argv_chargement(cible, nom):
    return argv_pg(cible, "psql", "-X", "-w", "-q", "-d", nom)


def argv_dropdb(cible, nom):
    return argv_pg(cible, "dropdb", "-w", "--", nom)


def interroger(cible, systeme, base=None, sql=postgres.REQUETE_FAITS):
    """Le JSON que rend `sql` sur `base` (la base de la cible par défaut),
    en lecture seule. ErreurPg si psql échoue ou ne rend pas de JSON."""
    code, sortie, erreur = systeme.requete(
        argv_psql(cible, base or cible.base, sql), env_pg(cible, True)
    )
    if code != 0:
        raise ErreurPg((erreur or sortie).strip()[:EXTRAIT] or f"code {code}")
    donnees = postgres.lire_json(sortie)
    if not isinstance(donnees, dict):
        raise ErreurPg(t("no JSON answer"))
    return donnees


def lister_bases(cible, systeme):
    """Les noms des bases du serveur. ErreurPg si psql échoue."""
    code, sortie, erreur = systeme.requete(
        argv_psql(cible, "postgres", postgres.REQUETE_BASES),
        env_pg(cible, True),
    )
    if code != 0:
        raise ErreurPg((erreur or sortie).strip()[:EXTRAIT] or f"code {code}")
    return {ligne.strip() for ligne in sortie.splitlines() if ligne.strip()}


def ancetre_existant(chemin):
    """Le premier dossier existant en remontant depuis `chemin`."""
    chemin = os.path.abspath(chemin)
    while not os.path.isdir(chemin):
        parent = os.path.dirname(chemin)
        if parent == chemin:
            break
        chemin = parent
    return chemin


def verifier_espace(systeme, chemin, besoin):
    """(libre, lieu) ; Refus si l'espace libre sous `chemin` est inférieur
    à `besoin`, ou s'il ne se lit pas : « vérifié avant » doit tenir."""
    lieu = ancetre_existant(chemin)
    try:
        libre = systeme.espace_libre(lieu)
    except OSError as err:
        raise ManqueEspace(
            N_("Cannot read the free space of {path}: {error}"),
            path=lieu,
            error=err,
        )
    if libre < besoin:
        raise ManqueEspace(
            N_("Not enough space in {path}: {free} free, {needed} needed."),
            path=lieu,
            free=humain(libre),
            needed=humain(besoin),
        )
    return libre, lieu


def evaluer(cible, systeme):
    """Lit la base et son filestore, vérifie l'espace : rend une
    évaluation (faits, filestore présent, octets et fichiers du filestore,
    besoin, libre). Refus sur tout ce qui ferait échouer la sauvegarde."""
    try:
        faits = interroger(cible, systeme)
    except ErreurPg as err:
        raise Refus(
            N_("Cannot read the database {database}: {error}"),
            database=cible.base,
            error=err,
        )
    if not faits.get("base"):
        raise Refus(
            N_(
                "{database} is not an Odoo database: no version for the"
                " base module."
            ),
            database=cible.base,
        )
    stockees = int(faits.get("stored_attachments") or 0)
    present = os.path.isdir(cible.filestore)
    if not present and stockees:
        raise Refus(
            N_(
                "The filestore {path} is missing while {count} attachment(s)"
                " are stored on disk."
            ),
            path=cible.filestore,
            count=stockees,
        )
    octets, nombre = (
        systeme.taille_dossier(cible.filestore) if present else (0, 0)
    )
    besoin = int((int(faits.get("size") or 0) + octets) * MARGE)
    libre, _lieu = verifier_espace(systeme, cible.dossier, besoin)
    return types.SimpleNamespace(
        faits=faits,
        filestore_present=present,
        octets_filestore=octets,
        fichiers_filestore=nombre,
        besoin=besoin,
        libre=libre,
    )


def manifeste(base, faits):
    """Le manifest.json d'Odoo (`dump_db_manifest`) pour `base`, depuis les
    faits lus dans la base. La version vient de `latest_version` du module
    base (`M.m.x.y`), `pg_version` de `server_version_num`."""
    morceaux = str(faits.get("base") or "").split(".")
    try:
        majeure, mineure = int(morceaux[0]), int(morceaux[1])
    except (IndexError, ValueError):
        raise Echec(
            t("Unreadable version of the base module: {version}").format(
                version=faits.get("base")
            )
        )
    version = f"{majeure}.{mineure}"
    return {
        "odoo_dump": "1",
        "db_name": base,
        "version": version,
        "version_info": [majeure, mineure, 0, "final", 0, ""],
        "major_version": version,
        "pg_version": postgres.version_pg(faits["server_version_num"]),
        "modules": dict(faits.get("modules") or {}),
    }


# --- Dossiers --------------------------------------------------------------


def refuser_liens(cible):
    """Refus quand le dossier propre à la base, `<dest>/<base>` ou
    `<state-dir>/<base>`, est un lien symbolique.

    `os.path.isdir` suit un lien : un lien posé par le compte de l'unité
    vers un dossier qu'il peut écrire ferait écrire la sauvegarde, l'état
    ou la rétention ailleurs que prévu, sous root. Le dossier commun
    (`--dest`, `--state-dir`) peut, lui, être un lien : c'est l'opérateur
    qui le choisit, et il appartient à root.
    """
    for chemin in (cible.dossier, cible.dossier_etat):
        if chemin and os.path.islink(chemin):
            raise Refus(N_("{path} is a symbolic link: refused."), path=chemin)


def dossiers_a_creer(cible, systeme, simulation=False):
    """[(chemin, mode, au_compte)] des dossiers à créer avant la sauvegarde,
    dans l'ordre, parents manquants compris. Refus quand un dossier existe
    sans être inscriptible par le compte, ou quand le compte courant ne
    pourrait pas le créer.

    Le dossier de la base est au compte (0700 pour les sauvegardes, 0755
    pour l'état) ; un dossier commun créé par root (`--dest`,
    `--state-dir`) reste à root, en 0755 : plusieurs instances, sous des
    comptes différents, y ont chacune le leur.

    `simulation` : un dossier que le compte courant ne peut pas créer est
    prévu quand même, comme root le créerait, et `cible.creation_sudo`
    le signale — la simulation précède l'exécution sous sudo.

    Un dossier de la base qui est un lien symbolique refuse
    (`refuser_liens`).
    """
    refuser_liens(cible)
    a_creer = []

    def hors_de_portee(parent, chemin):
        if cible.root or os.access(parent, os.W_OK):
            return
        if simulation:
            cible.creation_sudo = True
            return
        raise Refus(
            N_(
                "{path} is missing and cannot be created by {user}:"
                " run once with sudo, or install the scheduled"
                " backup."
            ),
            path=chemin,
            user=cible.courant,
        )

    for commun, propre, mode in (
        (cible.dest, cible.dossier, MODE_DOSSIER),
        (cible.etat_dir, cible.dossier_etat, MODE_PARTAGE),
    ):
        if not os.path.lexists(commun):
            hors_de_portee(ancetre_existant(os.path.dirname(commun)), commun)
            manquants = []
            courant = commun
            while not os.path.lexists(courant):
                manquants.append(courant)
                courant = os.path.dirname(courant)
            for chemin in reversed(manquants):
                if (chemin, MODE_PARTAGE, False) not in a_creer:
                    a_creer.append((chemin, MODE_PARTAGE, False))
            a_creer.append((propre, mode, True))
            continue
        if not os.path.isdir(commun):
            raise Refus(N_("{path} is not a directory."), path=commun)
        if not os.path.lexists(propre):
            hors_de_portee(commun, propre)
            a_creer.append((propre, mode, True))
        elif not os.path.isdir(propre) or not systeme.inscriptible(
            propre, cible.utilisateur
        ):
            raise Refus(
                N_("{path} is not a directory writable by {user}."),
                path=propre,
                user=cible.utilisateur,
            )
    return a_creer


def commandes_creation(a_creer, cible):
    """La création des dossiers, en commandes de shell, pour l'affichage.
    Quand seul root peut les créer (`cible.creation_sudo`), chaque commande
    est préfixée de `sudo` et le dossier de la base est donné au compte,
    comme le fera l'exécution réelle."""
    lignes = []
    sous_root = cible.root or cible.creation_sudo
    devant = ["sudo"] if cible.creation_sudo else []
    for chemin, mode, au_compte in a_creer:
        ligne = service.joindre(
            devant + ["mkdir", "-m", f"{mode:04o}", "--", chemin]
        )
        if au_compte and sous_root:
            ligne += " && " + service.joindre(
                devant + ["chown", cible.utilisateur + ":", "--", chemin]
            )
        lignes.append(ligne)
    return lignes


def creer_dossiers(a_creer, cible, systeme, rapport):
    """Crée les dossiers marqués par `dossiers_a_creer`. False, message
    écrit, si une création échoue."""
    for chemin, mode, au_compte in a_creer:
        try:
            if au_compte and cible.root:
                systeme.creer_dossier(chemin, cible.utilisateur, mode)
            else:
                systeme.mkdir(chemin, mode)
        except (OSError, KeyError) as err:
            rapport.erreur(
                t("Cannot create {path}: {error}").format(
                    path=chemin, error=err
                )
            )
            return False
        if au_compte and cible.root:
            rapport.ok(
                t("Created {path}, owned by {user}.").format(
                    path=chemin, user=cible.utilisateur
                )
            )
    return True


# --- État ------------------------------------------------------------------


def chemin_etat(etat_dir, base):
    return os.path.join(etat_dir, base, NOM_ETAT)


def ouvrir_ordinaire(chemin, proprietaires=None):
    """Un fichier ordinaire ouvert en lecture binaire, ou None s'il n'existe
    pas, est un lien symbolique, n'est pas un fichier ordinaire, ou
    appartient à un uid hors de `proprietaires` (quand il est donné).

    O_NOFOLLOW : root ne suit pas un lien posé à la place du fichier par le
    compte qui possède le dossier. O_NONBLOCK : un tube nommé ne bloque pas
    avant le contrôle de type. PermissionError remonte.
    """
    try:
        fd = os.open(chemin, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as err:
        if err.errno == errno.ELOOP:
            return None
        raise
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or (
        proprietaires is not None and info.st_uid not in proprietaires
    ):
        os.close(fd)
        return None
    return os.fdopen(fd, "rb")


def lire_etat(chemin, proprietaires=None):
    """Le dict d'état de `chemin` ; {} s'il n'existe pas, n'est pas un
    fichier ordinaire (voir `ouvrir_ordinaire`) ou ne se lit pas comme un
    objet JSON. Au plus TAILLE_ETAT_MAX octets sont lus. PermissionError
    remonte."""
    fichier = ouvrir_ordinaire(chemin, proprietaires)
    if fichier is None:
        return {}
    with fichier:
        try:
            donnees = json.loads(fichier.read(TAILLE_ETAT_MAX).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
    return donnees if isinstance(donnees, dict) else {}


def _ecrire_atomique(chemin, prefixe, texte, mode, cible, systeme):
    """Écrit `texte` dans `chemin` : fichier temporaire du même dossier,
    mode et propriétaire posés sur son DESCRIPTEUR, synchronisé, puis
    renommage. Sous root, dans un dossier du compte, le compte peut
    remplacer le nom du fichier temporaire par un lien à tout moment :
    un chmod ou un chown par chemin suivrait ce lien, le descripteur ne
    vise que l'inode créé ici. Un échec ne laisse ni fichier partiel ni
    fichier temporaire. Lève OSError ou KeyError."""
    fd, provisoire = tempfile.mkstemp(
        prefix=prefixe, suffix=".tmp", dir=os.path.dirname(chemin)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fichier:
            fichier.write(texte)
            fichier.flush()
            os.fchmod(fichier.fileno(), mode)
            if cible.root:
                systeme.fchown(fichier.fileno(), cible.utilisateur)
            os.fsync(fichier.fileno())
        os.replace(provisoire, chemin)
    except BaseException:
        _retirer(provisoire)
        raise


def ecrire_etat(cible, systeme, mise_a_jour):
    """Fusionne `mise_a_jour` dans l'état de la base et le réécrit
    (`_ecrire_atomique`). Sous root, l'état existant n'est repris que s'il
    appartient au compte ou à root. Lève OSError ou KeyError."""
    chemin = chemin_etat(cible.etat_dir, cible.base)
    proprietaires = None
    if cible.root:
        proprietaires = {0, systeme.uid(cible.utilisateur)}
    try:
        donnees = lire_etat(chemin, proprietaires)
    except OSError:
        donnees = {}
    donnees["db"] = cible.base
    donnees.update(mise_a_jour)
    texte = json.dumps(donnees, indent=2, sort_keys=True) + "\n"
    _ecrire_atomique(chemin, ".state.", texte, MODE_ETAT, cible, systeme)


def noter(cible, systeme, rapport, mise_a_jour):
    """`ecrire_etat`, l'échec signalé sans lever. Rend True si écrit."""
    try:
        ecrire_etat(cible, systeme, mise_a_jour)
        return True
    except (OSError, KeyError) as err:
        rapport.attn(
            t("Cannot record the state in {path}: {error}").format(
                path=cible.dossier_etat, error=err
            )
        )
        return False


# --- Sauvegarde ------------------------------------------------------------


def _retirer(chemin):
    try:
        os.remove(chemin)
    except FileNotFoundError:
        pass


def _date_zip(epoque):
    """La date d'un membre de zip ; le format n'admet rien avant 1980."""
    date = time.localtime(epoque)[:6]
    return date if date[0] >= 1980 else (1980, 1, 1, 0, 0, 0)


def _info(nom, epoque, mode=MODE_FICHIER):
    info = zipfile.ZipInfo(nom, date_time=_date_zip(epoque))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | (mode & 0o7777)) << 16
    return info


def _fsync_dossier(chemin):
    try:
        fd = os.open(chemin, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def empreinte(fichier):
    """Le sha256 hexadécimal de `fichier` (chemin ou fichier ouvert, relu
    depuis le début)."""
    somme = hashlib.sha256()
    if isinstance(fichier, str):
        with open(fichier, "rb") as ouvert:
            return empreinte(ouvert)
    fichier.seek(0)
    for bloc in iter(lambda: fichier.read(BLOC), b""):
        somme.update(bloc)
    fichier.seek(0)
    return somme.hexdigest()


def lire_sidecar(chemin):
    """L'empreinte notée dans `<chemin>.sha256`, None s'il n'existe pas,
    "" s'il ne se lit pas comme une empreinte — un lien symbolique ou un
    fichier spécial compris : l'archive est alors refusée. Format de
    sha256sum : `<hex>  <nom>`."""
    sidecar = chemin + retention.SUFFIXE_SHA
    if not os.path.lexists(sidecar):
        return None
    fichier = ouvrir_ordinaire(sidecar)
    if fichier is None:
        return ""
    with fichier:
        premier = fichier.read(200).decode("utf-8", "replace").split()
    return premier[0].lower() if premier else ""


def _ecrire_sidecar(final, somme, cible, systeme):
    nom = os.path.basename(final)
    _ecrire_atomique(
        final + retention.SUFFIXE_SHA,
        f".{nom}.",
        f"{somme}  {nom}\n",
        MODE_FICHIER,
        cible,
        systeme,
    )


def nettoyer_partiels(cible, rapport):
    """Retire les fichiers provisoires laissés par une sauvegarde de la base
    interrompue sans nettoyage (machine arrêtée). Appelée sous le verrou :
    aucun n'appartient à une sauvegarde en cours."""
    try:
        noms = os.listdir(cible.dossier)
    except OSError:
        return
    for nom in noms:
        if retention.est_partiel(nom, cible.base):
            try:
                os.remove(os.path.join(cible.dossier, nom))
                rapport.detail(
                    t("Removed a leftover partial file: {name}").format(
                        name=nom
                    )
                )
            except OSError:
                pass


def _ecrire_dump(archive, cible, systeme, delai, epoque):
    """pg_dump dans le membre `dump.sql`. Echec si pg_dump échoue, dépasse
    `delai` ou ne finit pas par la marque de fin."""
    queue = [b""]
    with archive.open(_info("dump.sql", epoque), "w", force_zip64=True) as m:

        def recevoir(bloc):
            m.write(bloc)
            queue[0] = (queue[0] + bloc)[-odoo_instance.TAILLE_FIN :]

        code, erreur, tue = systeme.flux(
            argv_dump(cible), env_pg(cible), recevoir, delai
        )
    if tue:
        raise Echec(
            t("pg_dump exceeded {seconds} s: stopped.").format(seconds=delai)
        )
    if code != 0:
        raise Echec(
            t("pg_dump failed (code {code}): {error}").format(
                code=code, error=erreur.strip()[:EXTRAIT]
            )
        )
    if odoo_instance.FIN_DE_DUMP not in queue[0]:
        raise Echec(t("The dump does not end with the pg_dump end marker."))


def _relatif(dossier, nom):
    return os.path.normpath(os.path.join(dossier, nom)).replace(os.sep, "/")


def _ecrire_filestore(archive, racine, uid=None):
    """Ajoute les fichiers ordinaires de `racine` sous `filestore/`, triés.
    Rend (nombre, écartés) : liens symboliques et fichiers spéciaux ne sont
    jamais lus. Un fichier disparu pendant la lecture est sauté.

    `racine` s'ouvre une seule fois par son chemin — un filestore qui est
    lui-même un lien vers un autre disque est suivi à cet endroit — et doit
    appartenir à `uid` quand il est donné (Echec sinon) : un lien posé à sa
    place vers un dossier de root ne fait pas entrer ce dossier dans la
    sauvegarde. Le reste se parcourt par descripteurs (`os.fwalk`, chaque
    fichier ouvert relativement au descripteur de son dossier, O_NOFOLLOW) :
    un sous-dossier remplacé par un lien pendant la lecture n'est pas
    suivi, au contraire d'un parcours par chemins où seul le dernier
    composant serait protégé.
    """
    nombre = 0
    ecartes = []
    fd_racine = os.open(racine, os.O_RDONLY | os.O_DIRECTORY | os.O_NONBLOCK)
    try:
        if uid is not None and os.fstat(fd_racine).st_uid != uid:
            raise Echec(
                t(
                    "The filestore {path} does not belong to the account of"
                    " the service: refused."
                ).format(path=racine)
            )
        for dossier, sous, fichiers, fd_dossier in os.fwalk(
            ".", dir_fd=fd_racine
        ):
            sous.sort()
            for nom in list(sous):
                try:
                    lien = stat.S_ISLNK(
                        os.stat(
                            nom, dir_fd=fd_dossier, follow_symlinks=False
                        ).st_mode
                    )
                except FileNotFoundError:
                    lien = False
                if lien:
                    sous.remove(nom)
                    ecartes.append(_relatif(dossier, nom))
            for nom in sorted(fichiers):
                relatif = _relatif(dossier, nom)
                try:
                    # O_NONBLOCK : ouvrir un tube nommé ne bloque pas avant
                    # le contrôle de type.
                    fd = os.open(
                        nom,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                        dir_fd=fd_dossier,
                    )
                except FileNotFoundError:
                    continue
                except OSError as err:
                    if err.errno != errno.ELOOP:
                        raise
                    ecartes.append(relatif)
                    continue
                with os.fdopen(fd, "rb") as fichier:
                    info = os.fstat(fichier.fileno())
                    if not stat.S_ISREG(info.st_mode):
                        ecartes.append(relatif)
                        continue
                    membre = _info(
                        "filestore/" + relatif, info.st_mtime, info.st_mode
                    )
                    with archive.open(membre, "w", force_zip64=True) as sortie:
                        shutil.copyfileobj(fichier, sortie, BLOC)
                    nombre += 1
    finally:
        os.close(fd_racine)
    return nombre, ecartes


def sauvegarder(cible, systeme, rapport, delai=DELAI_SAUVEGARDE):
    """Sauvegarde la base de `cible` ; rend un Resultat.

    Ne prend AUCUN verrou : l'appelant le détient déjà. Les dossiers
    doivent exister (`creer_dossiers`). Le succès comme l'échec sont notés
    dans l'état de la base, sans qu'un échec efface le dernier succès.
    Le fichier provisoire est retiré sur tout échec, exception comprise.
    """
    try:
        evaluation = evaluer(cible, systeme)
    except ManqueEspace as err:
        return _echec(cible, systeme, rapport, err.message(t), CODE_REFUS)
    except Refus as err:
        return _echec(cible, systeme, rapport, err.message(t))
    if not evaluation.filestore_present:
        rapport.attn(
            t(
                "No filestore at {path}: the database stores no attachment"
                " on disk."
            ).format(path=cible.filestore)
        )
    rapport.detail(
        t("Database {size}, filestore {fs} ({count} files).").format(
            size=humain(evaluation.faits.get("size")),
            fs=humain(evaluation.octets_filestore),
            count=evaluation.fichiers_filestore,
        )
    )
    epoque = systeme.maintenant()
    moment = datetime.datetime.fromtimestamp(epoque)
    final = os.path.join(
        cible.dossier, retention.nom_sauvegarde(cible.base, moment)
    )
    partiel = final + retention.SUFFIXE_PARTIEL
    nettoyer_partiels(cible, rapport)
    if os.path.lexists(final):
        return _echec(
            cible,
            systeme,
            rapport,
            t("The backup file already exists: {path}").format(path=final),
        )
    try:
        donnees = manifeste(cible.base, evaluation.faits)
        drapeaux = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = os.open(partiel, drapeaux, MODE_FICHIER)
        with os.fdopen(fd, "w+b") as fichier:
            if cible.root:
                systeme.fchown(fichier.fileno(), cible.utilisateur)
            with zipfile.ZipFile(
                fichier, "w", zipfile.ZIP_DEFLATED, allowZip64=True
            ) as archive:
                _ecrire_dump(archive, cible, systeme, delai, epoque)
                archive.writestr(
                    _info("manifest.json", epoque),
                    json.dumps(donnees, indent=4),
                )
                nombre, ecartes = (0, [])
                if evaluation.filestore_present:
                    nombre, ecartes = _ecrire_filestore(
                        archive,
                        cible.filestore,
                        systeme.uid(cible.utilisateur) if cible.root else None,
                    )
            fichier.flush()
            os.fsync(fichier.fileno())
            ok, problemes = odoo_instance.verifier_sauvegarde(fichier)
            if not ok:
                raise Echec(
                    t("The backup is incomplete ({missing}).").format(
                        missing=", ".join(problemes)
                    )
                )
            somme = empreinte(fichier)
            taille = os.fstat(fichier.fileno()).st_size
        os.rename(partiel, final)
    except Echec as err:
        _retirer(partiel)
        return _echec(cible, systeme, rapport, str(err))
    except (OSError, KeyError, zipfile.BadZipFile, zlib.error) as err:
        _retirer(partiel)
        return _echec(
            cible,
            systeme,
            rapport,
            t("Backup failed: {error}").format(error=err),
        )
    except BaseException:
        _retirer(partiel)
        raise
    for relatif in ecartes:
        rapport.attn(
            t("Skipped (not a regular file): filestore/{path}").format(
                path=relatif
            )
        )
    resultat = Resultat(CODE_OK, final, taille, somme)
    try:
        _ecrire_sidecar(final, somme, cible, systeme)
    except (OSError, KeyError) as err:
        rapport.fail(
            t("Cannot write {path}: {error}").format(
                path=final + retention.SUFFIXE_SHA, error=err
            )
        )
        resultat.code = CODE_ECHEC
    _fsync_dossier(cible.dossier)
    rapport.ok(
        t(
            "Backup written and verified: {path} ({size}, {count} files)"
        ).format(path=final, size=humain(taille), count=nombre)
    )
    resultat.etat_ok = noter(
        cible,
        systeme,
        rapport,
        {
            "last_success": {
                "time": int(epoque),
                "file": final,
                "size": taille,
                "sha256": somme,
            }
        },
    )
    return resultat


def _echec(cible, systeme, rapport, message, code=CODE_ECHEC):
    rapport.fail(message)
    if os.path.isdir(cible.dossier_etat):
        noter(
            cible,
            systeme,
            rapport,
            {
                "last_failure": {
                    "time": int(systeme.maintenant()),
                    "message": message[:500],
                }
            },
        )
    return Resultat(code, message=message)


# --- Copie hors site et rétention -----------------------------------------


def copie_valide(valeur):
    """True si `valeur` est une destination rsync admise :
    `[compte@]hôte:/chemin` ou un chemin absolu, sans tiret en tête."""
    if not valeur or valeur.startswith("-"):
        return False
    return bool(
        RE_COPIE_DISTANTE.fullmatch(valeur)
        or RE_COPIE_LOCALE.fullmatch(valeur)
    )


def argv_copie(cible, chemin, destination):
    """rsync du zip et de son empreinte vers `destination/<base>/`, sous le
    compte de l'unité (ses clés ssh et son known_hosts). rsync crée le
    dernier dossier du chemin de lui-même."""
    return cible.prefixe + [
        "rsync",
        "-a",
        "--partial",
        "-e",
        SSH_COPIE,
        chemin,
        chemin + retention.SUFFIXE_SHA,
        destination.rstrip("/") + "/" + cible.base + "/",
    ]


def copier(cible, systeme, rapport, chemin, destination):
    """Copie hors site ; True si réussie. L'échec est noté dans l'état et
    signalé, la sauvegarde locale reste."""
    env = os.environ.copy()
    env["HOME"] = cible.home
    code, sortie, erreur = systeme.requete(
        argv_copie(cible, chemin, destination), env, DELAI_COPIE
    )
    epoque = int(systeme.maintenant())
    if code == 0:
        rapport.ok(
            t("Copied to {destination}.").format(destination=destination)
        )
        noter(
            cible,
            systeme,
            rapport,
            {"last_copy": {"time": epoque, "ok": True, "message": ""}},
        )
        return True
    message = (erreur or sortie).strip()[:EXTRAIT]
    rapport.attn(
        t(
            "Off-site copy failed (rsync code {code}): {error}. The local"
            " backup is kept."
        ).format(code=code, error=message)
    )
    noter(
        cible,
        systeme,
        rapport,
        {
            "last_copy": {
                "time": epoque,
                "ok": False,
                "message": f"rsync code {code}: {message}",
            }
        },
    )
    return False


def appliquer_retention(cible, systeme, rapport, args):
    """Supprime les sauvegardes que la rétention ne garde pas, chacune avec
    son empreinte. Seuls les noms de l'outil pour cette base sont
    examinés."""
    try:
        noms = os.listdir(cible.dossier)
    except OSError as err:
        rapport.attn(t("Retention skipped: {error}").format(error=err))
        return
    jour = datetime.date.fromtimestamp(systeme.maintenant())
    supprimer = retention.a_supprimer(
        noms,
        cible.base,
        args.keep_daily,
        args.keep_weekly,
        args.keep_monthly,
        args.keep_recent_days,
        jour,
    )
    for nom in sorted(supprimer):
        for fichier in (nom, nom + retention.SUFFIXE_SHA):
            try:
                os.remove(os.path.join(cible.dossier, fichier))
            except FileNotFoundError:
                pass
            except OSError as err:
                rapport.attn(
                    t("Cannot delete {path}: {error}").format(
                        path=fichier, error=err
                    )
                )
    gardes = len(retention.sauvegardes(noms, cible.base)) - len(supprimer)
    rapport.ok(
        t("Retention: {kept} kept, {deleted} deleted.").format(
            kept=gardes, deleted=len(supprimer)
        )
    )


# --- État des sauvegardes (--status) --------------------------------------


def afficher_etat(etat_dir, base, age_max, systeme, rapport):
    """L'état de chaque base (ou de `base`) ; rend le code de sortie : 1
    s'il n'y a aucun état, ou qu'une base n'a pas de succès plus récent
    que `age_max` heures ; 2 si le dossier d'état ne se lit pas, ou si le
    dossier d'une base y est un lien symbolique — son état n'est alors pas
    lu (voir `refuser_liens`)."""
    try:
        if base:
            if os.path.islink(os.path.join(etat_dir, base)):
                rapport.erreur(
                    t("{path} is a symbolic link: refused.").format(
                        path=os.path.join(etat_dir, base)
                    )
                )
                return CODE_REFUS
            os.stat(chemin_etat(etat_dir, base))
            noms = [base]
        else:
            noms = sorted(
                nom
                for nom in os.listdir(etat_dir)
                if os.path.isfile(chemin_etat(etat_dir, nom))
            )
    except FileNotFoundError:
        noms = []
    except PermissionError:
        rapport.erreur(
            t("Cannot read {path}: run with sudo.").format(path=etat_dir)
        )
        return CODE_REFUS
    for nom in noms:
        if os.path.islink(os.path.join(etat_dir, nom)):
            rapport.erreur(
                t("{path} is a symbolic link: refused.").format(
                    path=os.path.join(etat_dir, nom)
                )
            )
            return CODE_REFUS
    if not noms:
        rapport.fail(
            t("No backup state in {path}.").format(
                path=os.path.join(etat_dir, base) if base else etat_dir
            )
        )
        return CODE_ECHEC
    maintenant = systeme.maintenant()
    code = CODE_OK
    for nom in noms:
        try:
            donnees = lire_etat(chemin_etat(etat_dir, nom))
        except PermissionError:
            rapport.erreur(
                t("Cannot read {path}: run with sudo.").format(
                    path=chemin_etat(etat_dir, nom)
                )
            )
            return CODE_REFUS
        if not _etat_d_une_base(nom, donnees, maintenant, age_max, rapport):
            code = CODE_ECHEC
    return code


def _etat_d_une_base(nom, donnees, maintenant, age_max, rapport):
    """Écrit l'état d'une base ; False si elle fait échouer `--status`."""
    succes = donnees.get("last_success") or {}
    echec = donnees.get("last_failure") or {}
    copie = donnees.get("last_copy") or {}
    bon = True
    if not succes.get("time"):
        rapport.fail(
            t("{database}: no successful backup recorded.").format(
                database=nom
            )
        )
        bon = False
    else:
        heures = (maintenant - float(succes["time"])) / 3600.0
        if heures > age_max:
            rapport.fail(
                t(
                    "{database}: last backup {hours:.1f} h old, more than"
                    " {limit} h."
                ).format(database=nom, hours=heures, limit=age_max)
            )
            bon = False
        else:
            rapport.ok(
                t("{database}: last backup {hours:.1f} h old.").format(
                    database=nom, hours=heures
                )
            )
        rapport.champ(t("File"), succes.get("file", ""))
        rapport.champ(t("Size"), humain(succes.get("size")))
        rapport.champ("sha256", succes.get("sha256", ""))
        try:
            os.lstat(succes.get("file") or "")
        except FileNotFoundError:
            rapport.attn(
                t("{database}: the recorded file is missing on disk.").format(
                    database=nom
                )
            )
        except OSError:
            pass
    if echec.get("time") and float(echec["time"]) > float(
        succes.get("time") or 0
    ):
        rapport.attn(
            t(
                "{database}: a failure is more recent than the last success:"
                " {message}"
            ).format(database=nom, message=echec.get("message", ""))
        )
    if copie and not copie.get("ok", True):
        rapport.attn(
            t("{database}: the last off-site copy failed: {message}").format(
                database=nom, message=copie.get("message", "")
            )
        )
    return bon


# --- Restauration -----------------------------------------------------------


class Archive:
    """Un zip de sauvegarde ouvert une fois pour toutes : le descripteur
    reste valide si le fichier est supprimé entre-temps."""

    def __init__(self, chemin):
        self.chemin = chemin
        self.fichier = open(chemin, "rb")
        self.zip = None

    def ouvrir(self):
        """Ouvre le zip ; Echec si ce n'en est pas un."""
        try:
            self.zip = zipfile.ZipFile(self.fichier)
        except (zipfile.BadZipFile, OSError) as err:
            raise Echec(
                t("{path} is not a readable zip: {error}").format(
                    path=self.chemin, error=err
                )
            )
        return self.zip

    def fermer(self):
        if self.zip is not None:
            self.zip.close()
        self.fichier.close()


def controler_archive(archive, rapport):
    """Empreinte, membres et manifeste d'une archive : rend (membres à
    extraire, manifeste). Echec sur une empreinte fausse, un membre qui
    sortirait du dossier d'extraction, un dump.sql absent. Une empreinte
    absente est un avertissement."""
    attendue = lire_sidecar(archive.chemin)
    if attendue is None:
        rapport.attn(
            t(
                "No checksum file next to {path}: integrity not checked."
            ).format(path=archive.chemin)
        )
    elif attendue != empreinte(archive.fichier):
        raise Echec(
            t("Checksum mismatch for {path}: refused.").format(
                path=archive.chemin
            )
        )
    else:
        rapport.ok(t("Checksum verified."))
    zf = archive.ouvrir()
    noms = zf.namelist()
    extraire, dangereux = odoo_instance.membres_a_extraire(noms)
    if dangereux:
        raise Echec(
            t("Dangerous paths in the archive, refused: {names}").format(
                names=", ".join(dangereux[:5])
            )
        )
    if "dump.sql" not in extraire:
        raise Echec(t("The archive holds no dump.sql."))
    donnees = {}
    if "manifest.json" in noms:
        try:
            donnees = json.loads(zf.read("manifest.json").decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            donnees = {}
    if not isinstance(donnees, dict):
        donnees = {}
    modules = donnees.get("modules") or {}
    rapport.champ(t("Original db"), donnees.get("db_name", "?"))
    rapport.champ(t("Odoo"), donnees.get("version", "?"))
    rapport.champ("PostgreSQL", donnees.get("pg_version", "?"))
    rapport.champ(t("Modules"), len(modules))
    return extraire, donnees


def _octets_filestore(zf, membres):
    return sum(
        zf.getinfo(nom).file_size
        for nom in membres
        if nom.startswith("filestore/")
    )


def _morceaux(zf, nom):
    with zf.open(nom) as membre:
        for bloc in iter(lambda: membre.read(BLOC), b""):
            yield bloc


def charger(cible, systeme, rapport, zf, nom, manifeste_lu):
    """Charge dump.sql dans la base `nom` (déjà créée) et la contrôle.
    Echec sur une erreur SQL non bénigne ou un contrôle raté ; rend le
    nombre de fichiers que la base attend dans son filestore."""
    code, lignes, tue = systeme.alimenter(
        argv_chargement(cible, nom),
        env_pg(cible),
        _morceaux(zf, "dump.sql"),
        DELAI_CHARGEMENT,
    )
    graves = postgres.erreurs_graves(lignes)
    if tue:
        raise Echec(t("Loading the dump exceeded the time limit."))
    if code != 0 or graves:
        rapport.extrait(graves or lignes, 10)
        raise Echec(
            t(
                "Loading the dump failed (code {code}, {count} SQL error(s))."
            ).format(code=code, count=len(graves))
        )
    rapport.ok(t("Dump loaded into {database}.").format(database=nom))
    try:
        controle = interroger(cible, systeme, nom, postgres.REQUETE_CONTROLE)
    except ErreurPg as err:
        raise Echec(
            t("The restored database cannot be read: {error}").format(
                error=err
            )
        )
    if not int(controle.get("tables") or 0):
        raise Echec(t("The restored database has no table."))
    if controle.get("base") != "installed":
        raise Echec(
            t("The base module is not installed in the restored database.")
        )
    attendus = set((manifeste_lu.get("modules") or {}).keys())
    installes = set(controle.get("modules") or [])
    if attendus and attendus != installes:
        ecart = sorted(attendus ^ installes)
        raise Echec(
            t(
                "The installed modules differ from the manifest: {names}"
            ).format(names=", ".join(ecart[:10]))
        )
    rapport.ok(
        t(
            "Checks passed: {tables} tables, {modules} modules installed."
        ).format(tables=controle.get("tables"), modules=len(installes))
    )
    return int(controle.get("stored_files") or 0)


def extraire_filestore(zf, membres, destination):
    """Écrit les membres `filestore/…` sous `destination` (qui existe) ;
    rend le nombre de fichiers. Chaque fichier est créé (O_EXCL, sans
    suivre de lien) en 0600, chaque dossier en 0700.

    Les chemins se résolvent par leur nom, liens des dossiers parents
    compris : la fonction tourne donc sous le compte de l'unité
    (`SystemeBase.sous_le_compte`), jamais sous root dans un dossier que
    ce compte contrôle."""
    nombre = 0
    for nom in membres:
        if not nom.startswith("filestore/"):
            continue
        relatif = nom[len("filestore/") :]
        chemin = os.path.join(destination, *relatif.split("/"))
        dossier = os.path.dirname(chemin)
        a_creer = []
        courant = dossier
        while not os.path.isdir(courant):
            a_creer.append(courant)
            courant = os.path.dirname(courant)
        for sous in reversed(a_creer):
            os.mkdir(sous, MODE_DOSSIER)
        drapeaux = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = os.open(chemin, drapeaux, MODE_FICHIER)
        with os.fdopen(fd, "wb") as sortie, zf.open(nom) as entree:
            shutil.copyfileobj(entree, sortie, BLOC)
        nombre += 1
    return nombre


def essayer_filestore(zf, membres, dossier):
    """Extrait le filestore dans un dossier provisoire `.restoretest-*` de
    `dossier`, puis le retire quoi qu'il arrive ; rend le nombre de
    fichiers. Sous le compte de l'unité (voir `extraire_filestore`)."""
    provisoire = tempfile.mkdtemp(prefix=".restoretest-", dir=dossier)
    try:
        return extraire_filestore(zf, membres, provisoire)
    finally:
        shutil.rmtree(provisoire, ignore_errors=True)


def placer_filestore(zf, membres, final):
    """Écrit le filestore dans `final`, qui ne doit pas exister : parents
    créés au besoin (0700), puis `.<nom>.partial` à côté, renommé une fois
    complet ; tout échec retire le provisoire. Rend le nombre de fichiers.
    Sous le compte de l'unité (voir `extraire_filestore`) : les dossiers
    créés lui appartiennent sans chown."""
    parent = os.path.dirname(final)
    partiel = os.path.join(parent, f".{os.path.basename(final)}.partial")
    _creer_chemin(parent)
    for chemin in (final, partiel):
        if os.path.lexists(chemin):
            raise FileExistsError(errno.EEXIST, "already exists", chemin)
    os.mkdir(partiel, MODE_DOSSIER)
    try:
        nombre = extraire_filestore(zf, membres, partiel)
        os.rename(partiel, final)
    except BaseException:
        shutil.rmtree(partiel, ignore_errors=True)
        raise
    return nombre


def derniere_sauvegarde(cible):
    """Le chemin de la sauvegarde la plus récente de la base, par son nom ;
    None s'il n'y en a pas. PermissionError remonte."""
    try:
        noms = os.listdir(cible.dossier)
    except FileNotFoundError:
        return None
    nom = retention.plus_recente(noms, cible.base)
    return os.path.join(cible.dossier, nom) if nom else None


def _dropdb(cible, systeme, rapport, nom):
    code, sortie, erreur = systeme.requete(
        argv_dropdb(cible, nom), env_pg(cible), DELAI_COMMANDE
    )
    if code == 0:
        rapport.ok(t("Database {database} dropped.").format(database=nom))
        return True
    rapport.fail(
        t(
            "Cannot drop {database} ({error}); drop it by hand: {command}"
        ).format(
            database=nom,
            error=(erreur or sortie).strip()[:EXTRAIT],
            command=service.joindre(argv_dropdb(cible, nom)),
        )
    )
    return False


def _createdb(cible, systeme, nom):
    code, sortie, erreur = systeme.requete(
        argv_createdb(cible, nom), env_pg(cible), DELAI_COMMANDE
    )
    if code != 0:
        raise Echec(
            t(
                "createdb failed: {error} (the PostgreSQL role needs"
                " CREATEDB)."
            ).format(error=(erreur or sortie).strip()[:EXTRAIT])
        )


def _ouvrir_pour_essai(cible, rapport, fichier, temporaire, simulation):
    """L'Archive à essayer, ou le code de sortie quand il n'y en a pas (ou
    que la simulation s'arrête faute de droits)."""
    try:
        chemin = fichier or derniere_sauvegarde(cible)
    except PermissionError:
        if simulation:
            rapport.attn(
                t("Backups in {path}: unknown (requires sudo).").format(
                    path=cible.dossier
                )
            )
            return _simuler_restauration(cible, rapport, temporaire, True)
        rapport.erreur(
            t("Cannot read {path}: run with sudo.").format(path=cible.dossier)
        )
        return CODE_REFUS
    if not chemin:
        rapport.fail(
            t("No backup of {database} in {path}.").format(
                database=cible.base, path=cible.dossier
            )
        )
        return CODE_ECHEC
    rapport.champ(t("File"), chemin)
    rapport.champ(t("Temporary db"), temporaire)
    try:
        return Archive(chemin)
    except PermissionError as err:
        if simulation:
            rapport.attn(
                t("Cannot open {path}: {error}").format(path=chemin, error=err)
            )
            return _simuler_restauration(cible, rapport, temporaire, True)
        rapport.erreur(
            t("Cannot read {path}: run with sudo.").format(path=chemin)
        )
        return CODE_REFUS
    except OSError as err:
        rapport.fail(
            t("Cannot open {path}: {error}").format(path=chemin, error=err)
        )
        return CODE_ECHEC


def dossier_pg(cible, systeme):
    """Le `data_directory` du serveur PostgreSQL, ou "" s'il est inconnu.

    Inconnu d'office quand `db_host` vise un autre hôte : l'espace libre
    d'un chemin distant ne se lit pas d'ici. Sinon `SHOW data_directory`,
    d'abord sous le compte de l'unité (un rôle superutilisateur ou membre
    de `pg_read_all_settings` le lit), puis, sous root, sous le compte
    système `postgres` par la socket locale (authentification peer), au
    port de la configuration.
    """
    if not postgres.hote_local(cible.config):
        return ""
    code, sortie, _erreur = systeme.requete(
        argv_psql(cible, "postgres", postgres.REQUETE_DOSSIER),
        env_pg(cible, True),
    )
    lieu = sortie.strip() if code == 0 else ""
    if lieu.startswith("/"):
        return lieu
    if not cible.root:
        return ""
    env = {
        cle: valeur
        for cle, valeur in os.environ.items()
        if not cle.startswith("PG")
    }
    env.update(postgres.env_pg_local(cible.config, DELAI_REQUETE))
    code, sortie, _erreur = systeme.requete(
        ["runuser", "-u", postgres.COMPTE_SYSTEME, "--"]
        + [cible.outils.get("psql", "psql"), "-X", "-w", "-q", "-tA"]
        + ["-d", "postgres", "-c", postgres.REQUETE_DOSSIER],
        env,
    )
    lieu = sortie.strip() if code == 0 else ""
    return lieu if lieu.startswith("/") else ""


def taille_base_estimee(cible, systeme, zf, manifeste_lu):
    """Les octets qu'occupera la base restaurée, avant marge : le double du
    `dump.sql` décompressé (un dump texte ne porte pas les index, que le
    chargement reconstruit), ou la taille de la base source quand elle est
    sur ce serveur et plus grande."""
    taille = zf.getinfo("dump.sql").file_size * FACTEUR_DUMP
    if cible.base and manifeste_lu.get("db_name") == cible.base:
        try:
            faits = interroger(cible, systeme)
            taille = max(taille, int(faits.get("size") or 0))
        except (ErreurPg, ValueError, TypeError):
            pass
    return taille


def _place_pour(
    cible,
    systeme,
    rapport,
    archive,
    membres,
    nom,
    dossier,
    manifeste_lu,
    traces,
):
    """Refus si la base `nom` existe déjà, si l'espace manque sous
    `dossier` pour le filestore de l'archive, ou dans le dossier de données
    de PostgreSQL pour la base elle-même : rend un message, ou "".

    Une base chargée dans un volume plein fait échouer les écritures de
    TOUTES les bases du serveur, celle de production comprise : l'espace
    de PostgreSQL inconnu (`dossier_pg`) refuse donc, sauf
    `--force-space` ; en simulation, il est seulement signalé.
    """
    try:
        if nom in lister_bases(cible, systeme):
            return t(
                "The database {database} already exists: refused."
            ).format(database=nom)
        besoin = int(_octets_filestore(archive.zip, membres) * MARGE)
        verifier_espace(systeme, dossier, besoin)
        besoin = int(
            taille_base_estimee(cible, systeme, archive.zip, manifeste_lu)
            * MARGE
        )
        lieu = dossier_pg(cible, systeme)
        if lieu:
            verifier_espace(systeme, lieu, besoin)
        elif traces.get("forcer_espace"):
            rapport.attn(
                t(
                    "Free space of PostgreSQL not checked (--force-space):"
                    " {needed} needed."
                ).format(needed=humain(besoin))
            )
        elif traces.get("simulation"):
            rapport.attn(
                t(
                    "Free space of PostgreSQL unknown: the real run checks"
                    " it under sudo, or refuses without --force-space."
                )
            )
        else:
            return t(
                "Cannot check the free space of PostgreSQL ({needed}"
                " needed): its data directory is unreadable or on another"
                " host. Check it, then rerun with --force-space."
            ).format(needed=humain(besoin))
    except ErreurPg as err:
        return str(err)
    except Refus as err:
        return err.message(t)
    return ""


def _essai(cible, systeme, rapport, archive, temporaire, traces):
    """Le corps de la restauration d'essai ; `traces` note la base créée
    (`cree`), pour que l'appelant la supprime. Le filestore s'extrait sous
    le compte de l'unité, dans un dossier provisoire retiré par
    `essayer_filestore` elle-même."""
    try:
        membres, manifeste_lu = controler_archive(archive, rapport)
    except Echec as err:
        rapport.fail(str(err))
        return CODE_ECHEC
    if traces["simulation"]:
        return _simuler_restauration(cible, rapport, temporaire, True)
    refus = _place_pour(
        cible,
        systeme,
        rapport,
        archive,
        membres,
        temporaire,
        cible.dossier,
        manifeste_lu,
        traces,
    )
    if refus:
        rapport.fail(refus)
        return CODE_ECHEC
    try:
        _createdb(cible, systeme, temporaire)
        traces["cree"] = True
        attendus = charger(
            cible, systeme, rapport, archive.zip, temporaire, manifeste_lu
        )
        nombre = systeme.sous_le_compte(
            cible.utilisateur,
            essayer_filestore,
            archive.zip,
            membres,
            cible.dossier,
        )
    except Echec as err:
        rapport.fail(str(err))
        return CODE_ECHEC
    except (OSError, zipfile.BadZipFile, zlib.error) as err:
        rapport.fail(t("Test restore failed: {error}").format(error=err))
        return CODE_ECHEC
    prevus = len([m for m in membres if m.startswith("filestore/")])
    if nombre != prevus:
        rapport.fail(
            t("Filestore: {count} of {total} files extracted.").format(
                count=nombre, total=prevus
            )
        )
        return CODE_ECHEC
    rapport.ok(t("Filestore extracted: {count} files.").format(count=nombre))
    if attendus > nombre:
        rapport.attn(
            t(
                "The database references {expected} stored files, the"
                " backup holds {count}."
            ).format(expected=attendus, count=nombre)
        )
    rapport.ok(t("Test restore passed: the backup is restorable."))
    return CODE_OK


def restauration_essai(
    cible,
    systeme,
    rapport,
    fichier=None,
    simulation=False,
    forcer_espace=False,
):
    """Restaure la dernière sauvegarde (ou `fichier`) dans une base
    temporaire, la contrôle, puis la supprime ; rend le code de sortie.

    La base source n'est jamais touchée. La base temporaire n'est
    supprimée que si CETTE exécution l'a créée : un nom déjà pris refuse
    avant createdb. Une suppression qui échoue fait échouer l'essai (code
    1), même réussi : une base `_restoretest_` reste sur le serveur.
    """
    horodatage = datetime.datetime.fromtimestamp(
        systeme.maintenant()
    ).strftime("%Y%m%d%H%M%S")
    temporaire = postgres.nom_temporaire(cible.base, horodatage)
    archive = _ouvrir_pour_essai(
        cible, rapport, fichier, temporaire, simulation
    )
    if not isinstance(archive, Archive):
        return archive
    traces = {
        "cree": False,
        "simulation": simulation,
        "forcer_espace": forcer_espace,
    }
    code = CODE_ECHEC
    try:
        code = _essai(cible, systeme, rapport, archive, temporaire, traces)
    finally:
        if traces["cree"] and not _dropdb(cible, systeme, rapport, temporaire):
            code = CODE_ECHEC
        archive.fermer()
    return code


def _simuler_restauration(cible, rapport, nom, essai, filestore=None):
    rapport.sim(decrire(argv_createdb(cible, nom), variables_pg(cible)))
    rapport.sim(
        decrire(argv_chargement(cible, nom), variables_pg(cible))
        + " < dump.sql"
    )
    rapport.sim(
        decrire(argv_psql(cible, nom, "<checks>"), variables_pg(cible, True))
    )
    if essai:
        rapport.sim(decrire(argv_dropdb(cible, nom), variables_pg(cible)))
    elif filestore:
        rapport.sim(t("filestore/ → {path}").format(path=filestore))
    rapport.ok(t("Simulation finished: nothing was created or written."))
    return CODE_OK


def _restaurer_dans(cible, systeme, rapport, archive, nouvelle, traces):
    """Le corps de la restauration ; `traces` note la base créée (`cree`),
    pour que l'appelant la supprime en cas d'échec. Le filestore se place
    sous le compte de l'unité (`placer_filestore`), qui retire lui-même son
    provisoire en cas d'échec."""
    try:
        membres, manifeste_lu = controler_archive(archive, rapport)
    except Echec as err:
        rapport.erreur(str(err))
        return CODE_REFUS
    for chemin in (traces["final"], traces["chemin_partiel"]):
        if os.path.lexists(chemin):
            rapport.erreur(
                t("{path} already exists: refused.").format(path=chemin)
            )
            return CODE_REFUS
    fs_parent = os.path.dirname(traces["final"])
    if not cible.interrogeable:
        rapport.attn(t("Existing databases: unknown (requires sudo)."))
    else:
        refus = _place_pour(
            cible,
            systeme,
            rapport,
            archive,
            membres,
            nouvelle,
            fs_parent,
            manifeste_lu,
            traces,
        )
        if refus:
            rapport.erreur(refus)
            return CODE_REFUS
    if traces["simulation"]:
        return _simuler_restauration(
            cible, rapport, nouvelle, False, traces["final"]
        )
    try:
        _createdb(cible, systeme, nouvelle)
        traces["cree"] = True
        charger(cible, systeme, rapport, archive.zip, nouvelle, manifeste_lu)
        nombre = systeme.sous_le_compte(
            cible.utilisateur,
            placer_filestore,
            archive.zip,
            membres,
            traces["final"],
        )
    except Echec as err:
        rapport.fail(str(err))
        return CODE_ECHEC
    except (OSError, KeyError, zipfile.BadZipFile, zlib.error) as err:
        rapport.fail(t("Restore failed: {error}").format(error=err))
        return CODE_ECHEC
    traces["reussi"] = True
    rapport.ok(
        t(
            "Restored into {database}, filestore {path} ({count} files)."
        ).format(database=nouvelle, path=traces["final"], count=nombre)
    )
    _rappels(cible, rapport, nouvelle, manifeste_lu)
    return CODE_OK


def restaurer(
    cible,
    systeme,
    rapport,
    fichier,
    nouvelle,
    simulation=False,
    forcer_espace=False,
):
    """Restaure `fichier` dans la base `nouvelle`, qui ne doit pas exister,
    et son filestore dans `<data_dir>/filestore/<nouvelle>`, qui ne doit
    pas exister non plus ; rend le code de sortie.

    Refus (code 2) avant toute création sur ce qui manque ou existe déjà.
    Le filestore s'écrit sous le compte de l'unité, d'abord dans
    `.<nouvelle>.partial`, renommé une fois complet. Après createdb, tout
    échec supprime la base et le filestore provisoire que CETTE exécution
    a créés, et rien d'autre.
    """
    if not postgres.nom_valide(nouvelle):
        rapport.erreur(
            t("Invalid database name: {database}").format(database=nouvelle)
        )
        return CODE_REFUS
    final = odoo_instance.filestore(cible.data_dir, nouvelle)
    traces = {
        "final": final,
        "chemin_partiel": os.path.join(
            os.path.dirname(final), f".{nouvelle}.partial"
        ),
        "cree": False,
        "reussi": False,
        "simulation": simulation,
        "forcer_espace": forcer_espace,
    }
    rapport.champ(t("File"), fichier)
    rapport.champ(t("New database"), nouvelle)
    rapport.champ(t("Filestore"), final)
    try:
        archive = Archive(fichier)
    except OSError as err:
        message = t("Cannot open {path}: {error}").format(
            path=fichier, error=err
        )
        if simulation and isinstance(err, PermissionError):
            rapport.attn(message)
            return _simuler_restauration(
                cible, rapport, nouvelle, False, final
            )
        rapport.erreur(message)
        return CODE_REFUS
    try:
        return _restaurer_dans(
            cible, systeme, rapport, archive, nouvelle, traces
        )
    finally:
        if not traces["reussi"] and traces["cree"]:
            _dropdb(cible, systeme, rapport, nouvelle)
        archive.fermer()


def _creer_chemin(dossier):
    """Crée `dossier` et ses parents manquants (0700), au compte courant —
    celui de l'unité, sous `sous_le_compte`."""
    a_creer = []
    courant = dossier
    while not os.path.isdir(courant):
        a_creer.append(courant)
        courant = os.path.dirname(courant)
    for chemin in reversed(a_creer):
        os.mkdir(chemin, MODE_DOSSIER)


def _rappels(cible, rapport, nouvelle, manifeste_lu):
    """Ce qu'il reste à faire avant de démarrer Odoo sur la copie."""
    try:
        majeure = int(
            str(manifeste_lu.get("major_version", "0")).split(".")[0]
        )
    except ValueError:
        majeure = 0
    if majeure >= 16:
        commande = service.joindre(
            ["odoo-bin", "neutralize", "-c", cible.config_path, "-d", nouvelle]
        )
        rapport.attn(
            t(
                "Neutralize it before starting Odoo on it (crons, outgoing"
                " mail): {command}"
            ).format(command=commande)
        )
    else:
        rapport.attn(
            t(
                "Neutralize it by hand before starting Odoo on it: disable"
                " the crons and the outgoing mail servers."
            )
        )
    rapport.attn(
        t(
            "database.uuid is the same as in the source: Odoo's own copy"
            " regenerates it, this restore does not."
        )
    )


# --- Programme --------------------------------------------------------------


def detecter(args, systeme, racine=RACINE, base_exigee=True):
    """L'instance et sa Cible. Refus sur ce qui manque."""
    plan = types.SimpleNamespace()
    props = service.detecter_unite(args.service, systeme, racine, plan)
    service.detecter_compte_et_dossier(args.user, systeme, plan, props)
    config = service.detecter_config(args.odoo_conf, plan)
    try:
        service.detecter_base(args.db, plan, config)
    except Refus:
        if base_exigee:
            raise
        plan.base, plan.origine_base = "", ""
    cible = preparer_cible(plan, config, args.dest, args.state_dir, systeme)
    refuser_liens(cible)
    return cible


def afficher_cible(cible, rapport):
    rapport.champ(t("Service"), cible.unite)
    rapport.champ(t("Account"), cible.utilisateur)
    rapport.champ(t("Odoo config"), cible.config_path)
    if cible.base:
        rapport.champ(t("Database"), f"{cible.base} ({cible.origine_base})")
    rapport.champ(
        t("Data dir"), f"{cible.data_dir} ({cible.origine_data_dir})"
    )
    if cible.base:
        rapport.champ(t("Destination"), cible.dossier)


def simuler_sauvegarde(cible, systeme, rapport, a_creer, args):
    """Ce que la sauvegarde ferait : dossiers, estimation, commandes."""
    for ligne in commandes_creation(a_creer, cible):
        rapport.sim(ligne)
    if cible.creation_sudo:
        rapport.attn(
            t(
                "Some folders can only be created by root: the real run"
                " creates them under sudo."
            )
        )
    if cible.interrogeable:
        try:
            evaluation = evaluer(cible, systeme)
            rapport.champ(
                t("Estimate"),
                t("{needed} needed, {free} free").format(
                    needed=humain(evaluation.besoin),
                    free=humain(evaluation.libre),
                ),
            )
        except Refus as err:
            rapport.fail(err.message(t))
            return CODE_REFUS
    else:
        rapport.champ(t("Estimate"), t("unknown (requires sudo)"))
    exemple = retention.nom_sauvegarde(
        cible.base, datetime.datetime.fromtimestamp(systeme.maintenant())
    )
    rapport.sim(
        decrire(argv_dump(cible), variables_pg(cible))
        + " → "
        + os.path.join(cible.dossier, exemple)
    )
    if args.copy_to:
        rapport.sim(
            service.joindre(
                argv_copie(
                    cible, os.path.join(cible.dossier, exemple), args.copy_to
                )
            )
        )
    rapport.sim(
        t(
            "retention: {daily} daily, {weekly} weekly, {monthly} monthly,"
            " everything from the last {recent} day(s)"
        ).format(
            daily=args.keep_daily,
            weekly=args.keep_weekly,
            monthly=args.keep_monthly,
            recent=args.keep_recent_days,
        )
    )
    rapport.ok(t("Simulation finished: nothing was created or written."))
    return CODE_OK


def _prendre_verrou(systeme, rapport, base):
    """Le verrou acquis, ou le code de sortie (75, 2). Construction et
    acquisition dans le même `try` : un verrou partagé dont le dossier
    manque lève dès sa construction (voir lock.Verrou)."""
    try:
        verrou = systeme.verrou(base)
        verrou.acquerir()
    except lock.VerrouPris as err:
        rapport.erreur(
            t(
                "Another operation on {database} is running (lock {path})."
            ).format(database=base, path=err.chemin)
        )
        return None, CODE_VERROU
    except OSError as err:
        rapport.erreur(t("Cannot take the lock: {error}").format(error=err))
        return None, CODE_REFUS
    return verrou, CODE_OK


def mode_sauvegarde(cible, systeme, rapport, args):
    try:
        a_creer = dossiers_a_creer(cible, systeme, args.dry_run)
    except Refus as err:
        rapport.erreur(err.message(t))
        return CODE_REFUS
    if args.dry_run:
        return simuler_sauvegarde(cible, systeme, rapport, a_creer, args)
    verrou, code = _prendre_verrou(systeme, rapport, cible.base)
    if verrou is None:
        return code
    try:
        if not creer_dossiers(a_creer, cible, systeme, rapport):
            return CODE_REFUS
        rapport.etape(t("Backup of {database}").format(database=cible.base))
        resultat = sauvegarder(cible, systeme, rapport, args.timeout)
        if resultat.code != CODE_OK and not resultat.chemin:
            return resultat.code
        code = resultat.code if resultat.etat_ok else CODE_ECHEC
        if args.copy_to:
            rapport.etape(t("Off-site copy"))
            if not copier(
                cible, systeme, rapport, resultat.chemin, args.copy_to
            ):
                code = CODE_ECHEC
        rapport.etape(t("Retention"))
        appliquer_retention(cible, systeme, rapport, args)
        return code
    finally:
        verrou.relacher()


def _type_copie(valeur):
    if not copie_valide(valeur):
        raise argparse.ArgumentTypeError(
            t("invalid copy destination: {value}").format(value=valeur)
        )
    return valeur


def analyser(argv=None):
    types_ = service.types_argparse(t)
    parser = argparse.ArgumentParser(
        description=t(
            "Verified backups of an Odoo database run by systemd: back up,"
            " status, test restore, restore into a new database."
        )
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--status",
        action="store_true",
        help=t("Show the age of the last successful backup of each database."),
    )
    modes.add_argument(
        "--test-restore",
        action="store_true",
        help=t(
            "Restore the latest backup (or --file) into a temporary database,"
            " check it, then drop it."
        ),
    )
    modes.add_argument(
        "--restore",
        action="store_true",
        help=t("Restore --file into the new database --into."),
    )
    parser.add_argument("--file", help=t("Backup file (.zip) to restore."))
    parser.add_argument(
        "--into",
        type=types_.base,
        help=t("New database for --restore; must not exist."),
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
        default=DEST_PAR_DEFAUT,
        help=t("Backup directory; default: {path}.").format(
            path=DEST_PAR_DEFAUT
        ),
    )
    parser.add_argument(
        "--state-dir",
        default=ETAT_PAR_DEFAUT,
        help=t("State directory; default: {path}.").format(
            path=ETAT_PAR_DEFAUT
        ),
    )
    parser.add_argument(
        "--keep-daily",
        type=types_.entier,
        default=GARDE_QUOTIDIEN,
        help=t("Daily backups kept; default: {value}.").format(
            value=GARDE_QUOTIDIEN
        ),
    )
    parser.add_argument(
        "--keep-weekly",
        type=types_.entier,
        default=GARDE_HEBDO,
        help=t("Weekly backups kept; default: {value}.").format(
            value=GARDE_HEBDO
        ),
    )
    parser.add_argument(
        "--keep-monthly",
        type=types_.entier,
        default=GARDE_MENSUEL,
        help=t("Monthly backups kept; default: {value}.").format(
            value=GARDE_MENSUEL
        ),
    )
    parser.add_argument(
        "--keep-recent-days",
        type=types_.entier,
        default=GARDE_RECENTS,
        help=t(
            "Keep every backup of the last N days; default: {value}."
        ).format(value=GARDE_RECENTS),
    )
    parser.add_argument(
        "--copy-to",
        type=_type_copie,
        help=t(
            "Off-site copy with rsync over ssh: [user@]host:/path or an"
            " absolute path; disabled by default."
        ),
    )
    parser.add_argument(
        "--max-age",
        type=types_.secondes,
        default=AGE_MAX,
        help=t(
            "--status fails when the last success is older than this many"
            " hours; default: {value}."
        ).format(value=AGE_MAX),
    )
    parser.add_argument(
        "--force-space",
        action="store_true",
        help=t(
            "--test-restore, --restore: go on when the free space of"
            " PostgreSQL cannot be checked."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=types_.secondes,
        default=DELAI_SAUVEGARDE,
        help=t("Maximum seconds for pg_dump; default: {value}.").format(
            value=DELAI_SAUVEGARDE
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=t("Detect and show the commands; write nothing."),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=t("Show each system command on stderr."),
    )
    args = parser.parse_args(argv)
    if args.restore and not (args.file and args.into):
        parser.error(t("--restore requires --file and --into."))
    if args.into and not args.restore:
        parser.error(t("--into is only used with --restore."))
    if args.file and not (args.restore or args.test_restore):
        parser.error(
            t("--file is only used with --restore or --test-restore.")
        )
    return args


def _proteger_signaux():
    """SIGTERM et SIGHUP lèvent Interruption ; rend la restauration."""

    def lever(numero, _frame):
        raise Interruption(numero)

    anciens = {}
    try:
        for numero in (signal.SIGTERM, signal.SIGHUP):
            anciens[numero] = signal.signal(numero, lever)
    except ValueError:
        pass

    def restaurer():
        for numero, ancien in anciens.items():
            signal.signal(numero, ancien)

    return restaurer


def main(argv=None, systeme=None, rapport=None):
    args = analyser(argv)
    systeme = systeme or Systeme(verbeux=args.verbose)
    rapport = rapport or report.Rapport()
    if args.status:
        return afficher_etat(
            os.path.abspath(args.state_dir),
            args.db,
            args.max_age,
            systeme,
            rapport,
        )
    rapport.texte(
        "{} — {}".format(
            t("Odoo backup"),
            datetime.datetime.fromtimestamp(systeme.maintenant()).strftime(
                "%Y-%m-%d %H:%M"
            ),
        )
    )
    try:
        cible = detecter(args, systeme, base_exigee=not args.restore)
    except Refus as err:
        rapport.erreur(err.message(t))
        return CODE_REFUS
    except KeyboardInterrupt:
        return CODE_INTERROMPU
    afficher_cible(cible, rapport)
    if not args.dry_run and not cible.interrogeable:
        rapport.erreur(
            t(
                "Run as root (sudo) or as {user}; other accounts only with"
                " --dry-run or --status."
            ).format(user=cible.utilisateur)
        )
        return CODE_REFUS
    restaurer_signaux = _proteger_signaux()
    try:
        if args.test_restore:
            rapport.etape(
                t("Test restore of {database}").format(database=cible.base)
            )
            return restauration_essai(
                cible,
                systeme,
                rapport,
                args.file,
                args.dry_run,
                args.force_space,
            )
        if args.restore:
            if args.dry_run:
                return restaurer(
                    cible,
                    systeme,
                    rapport,
                    args.file,
                    args.into,
                    True,
                    args.force_space,
                )
            verrou, code = _prendre_verrou(systeme, rapport, args.into)
            if verrou is None:
                return code
            try:
                return restaurer(
                    cible,
                    systeme,
                    rapport,
                    args.file,
                    args.into,
                    False,
                    args.force_space,
                )
            finally:
                verrou.relacher()
        return mode_sauvegarde(cible, systeme, rapport, args)
    except (KeyboardInterrupt, Interruption):
        rapport.fail(t("Interrupted."))
        return CODE_INTERROMPU
    finally:
        restaurer_signaux()


if __name__ == "__main__":
    sys.exit(main())
