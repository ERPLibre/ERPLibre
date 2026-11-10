#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Mettre à niveau le serveur PostgreSQL qui porte les bases d'ERPLibre.

TODO › Execute › Database › « Upgrade the PostgreSQL server ».

Debian et Ubuntu seulement : le travail repose sur postgresql-common —
pg_lsclusters, pg_upgradecluster, pg_dropcluster. Ailleurs, la fonction dit
que rien n'est pris en charge et ce qu'il reste à faire à la main.

Le cluster visé est celui du port PORT_DEFAUT, que libpq — donc Odoo sans
« db_port » — joint par défaut. La version visée est le minimum qu'exige la
version d'Odoo active (version_manager.postgresql_requise) ; sans exigence,
la plus récente installée ou le maximum du catalogue.

Ordre, chaque étape vérifiée avant la suivante : plan et confirmation (défaut
non) ; arrêt du service d'ERPLibre s'il tourne ; une sauvegarde pg_dump -Fc
par base, dans un dossier daté sous image_db/ ; pose de postgresql-<cible>
par « make install_os PG_VERSION=<cible> » s'il manque ; retrait du cluster
VIDE que l'installation du paquet crée sous le même nom ; pg_upgradecluster ;
contrôle que le nouveau cluster sert le même port et les mêmes bases ;
redémarrage du service. L'ancien cluster reste sur le disque, arrêté : la
commande qui le retire s'affiche, elle ne s'exécute pas.

Un échec arrête tout. Avant pg_upgradecluster, l'ancien cluster n'a pas été
touché : le service est relancé et rien d'autre n'est à défaire. Après, le
message donne les commandes qui ramènent l'ancien cluster.

Les commandes passent par todo_journal.lancer_au_terminal : sudo y demande
son mot de passe au terminal, et le journal de session reçoit chaque commande
et son code.
"""

import datetime
import json
import os
import shutil
import subprocess

from script.todo import todo_journal, version_manager
from script.todo.todo_i18n import t

# Le port par défaut de libpq : le cluster qui l'occupe porte les bases
# qu'Odoo joint quand sa configuration ne nomme pas de port.
PORT_DEFAUT = 5432
# Les binaires de chaque version majeure posée par les paquets Debian.
RACINE_BINAIRES = "/usr/lib/postgresql"
# Les sauvegardes de TODO, hors du suivi de git (.gitignore).
DOSSIER_SAUVEGARDES = "image_db"
# Les bases d'un cluster et leur taille, une par ligne, « nom<TAB>taille ».
# « postgres » et les gabarits sont recréés par initdb : rien à sauvegarder.
REQUETE_BASES = (
    "SELECT datname, pg_size_pretty(pg_database_size(datname))"
    " FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres'"
    " ORDER BY datname"
)


def _oui(reponse):
    """« Défaut non » : seule une réponse explicite accepte, FR ou EN."""
    return reponse.strip().lower() in ("y", "yes", "o", "oui")


def majeure(version):
    """« 9.6 » -> (9, 6), « 18 » -> (18,) : une clé qui compare les
    versions de PostgreSQL en nombres, anciennes numérotations comprises."""
    return tuple(int(p) for p in str(version).split(".") if p.isdigit())


def lire_clusters(texte):
    """Les clusters de « pg_lsclusters -h », une ligne chacun : « version
    nom port état propriétaire données journal ». Rend une liste de
    {"version", "nom", "port", "etat"} ; une ligne illisible est sautée."""
    clusters = []
    for ligne in texte.splitlines():
        champs = ligne.split()
        if len(champs) < 4 or not champs[2].isdigit():
            continue
        clusters.append(
            {
                "version": champs[0],
                "nom": champs[1],
                "port": int(champs[2]),
                "etat": champs[3],
            }
        )
    return clusters


def versions_installees():
    """Les versions majeures dont le SERVEUR est posé sous RACINE_BINAIRES,
    de la plus ancienne à la plus récente. Le client seul (libpq, psql) ne
    porte pas bin/postgres et n'est pas compté."""
    try:
        noms = os.listdir(RACINE_BINAIRES)
    except OSError:
        return []
    return sorted(
        (
            nom
            for nom in noms
            if majeure(nom)
            and os.path.isfile(
                os.path.join(RACINE_BINAIRES, nom, "bin", "postgres")
            )
        ),
        key=majeure,
    )


def maximum_du_catalogue():
    """La plus haute « postgresql_version » du catalogue, ou None."""
    with open(version_manager.VERSION_DATA_FILE) as handle:
        entrees = json.load(handle).values()
    versions = [
        int(e["postgresql_version"])
        for e in entrees
        if str(e.get("postgresql_version") or "").isdigit()
    ]
    return max(versions) if versions else None


def version_cible(odoo_version):
    """(version majeure visée, exigée par Odoo ?) ; (None, False) quand rien
    ne désigne de version.

    L'exigence de la version d'Odoo active prime. Sans elle, la plus récente
    des versions entières installées et du maximum du catalogue."""
    requise = (
        version_manager.postgresql_requise(odoo_version)
        if odoo_version
        else None
    )
    if requise:
        return requise, True
    candidates = [int(v) for v in versions_installees() if v.isdigit()]
    plafond = maximum_du_catalogue()
    if plafond:
        candidates.append(plafond)
    return (max(candidates) if candidates else None), False


def odoo_active(racine):
    """La version d'Odoo du checkout (.odoo-version), ou None."""
    try:
        with open(
            os.path.join(racine, version_manager.ODOO_VERSION_FILE)
        ) as handle:
            return handle.read().strip() or None
    except OSError:
        return None


def services_candidats(racine):
    """Les unités systemd qui font tourner ERPLibre depuis ce checkout :
    celle de script/systemd/install_daemon.sh, nommée d'après le dossier
    (EL_CONFIG d'env_var.sh), et celle des installations de VM."""
    nom = os.path.basename(os.path.normpath(racine))
    return [f"erplibre_{nom}.service", "erplibre.service"]


def _lancer(argv, capturer=False):
    """Lance `argv` au terminal ; rend (code, sortie).

    La sortie n'est lue que si `capturer` ; sinon elle reste à l'écran et
    « sortie » est vide. sudo garde le terminal pour son mot de passe dans
    les deux cas : il le lit sur /dev/tty, pas sur la sortie. Un programme
    introuvable rend 127, comme le shell."""
    kwargs = {"check": False}
    if capturer:
        kwargs.update(stdout=subprocess.PIPE, text=True)
    try:
        fini = todo_journal.lancer_au_terminal(argv, **kwargs)
    except (OSError, subprocess.SubprocessError) as err:
        print(f"❌ {err}")
        return 127, ""
    return fini.returncode, (fini.stdout or "") if capturer else ""


def _code(argv):
    """Lance `argv` au terminal, sortie à l'écran ; rend son code."""
    return _lancer(argv)[0]


def lire_les_clusters():
    """Les clusters présents, ou None quand pg_lsclusters échoue."""
    code, sortie = _lancer(["pg_lsclusters", "-h"], capturer=True)
    return None if code else lire_clusters(sortie)


def lister_bases(port, en_postgres=False):
    """[(nom, taille)] des bases du cluster de `port`, ou None si psql
    échoue.

    Sous le compte courant, le rôle qu'ERPLibre crée pour lui. Un cluster
    que l'installation vient de créer ne connaît que le rôle postgres :
    `en_postgres` passe alors par « sudo -u postgres »."""
    argv = ["psql", "-p", str(port), "-d", "postgres", "-At"]
    argv += ["-F", "\t", "-c", REQUETE_BASES]
    if en_postgres:
        argv = ["sudo", "-u", "postgres", *argv]
    code, sortie = _lancer(argv, capturer=True)
    if code:
        return None
    bases = []
    for ligne in sortie.splitlines():
        if ligne.strip():
            nom, _, taille = ligne.partition("\t")
            bases.append((nom.strip(), taille.strip()))
    return bases


def paquet_installe(version):
    """postgresql-<version> est-il posé, d'après dpkg ?"""
    code, sortie = _lancer(
        ["dpkg-query", "-W", "-f=${Status}", f"postgresql-{version}"],
        capturer=True,
    )
    return code == 0 and "install ok installed" in sortie


def expliquer_non_pris_en_charge():
    """Hors de Debian et d'Ubuntu : ce qui manque, et la voie manuelle."""
    print(
        "❌ "
        + t(
            "Upgrading the PostgreSQL server needs postgresql-common"
            " (pg_lsclusters, pg_upgradecluster): Debian and Ubuntu only."
        )
    )
    print("   " + t("Elsewhere, by hand:"))
    print("   1. " + t("back up each database: pg_dump -Fc -f BASE.dump BASE"))
    print("   2. " + t("install the new PostgreSQL version and start it"))
    print(
        "   3. " + t("restore each one: pg_restore -C -d postgres BASE.dump")
    )
    print("   " + t("or follow pg_upgrade in your distribution guide."))


class MiseANiveau:
    """Une mise à niveau, de la lecture des clusters au contrôle final.

    `demander` lit la confirmation (input par défaut), `maintenant` date
    le dossier des sauvegardes, `racine` est le checkout : image_db/ s'y
    trouve, .odoo-version aussi."""

    def __init__(self, racine=None, demander=input, maintenant=None):
        self.racine = racine or os.getcwd()
        self.demander = demander
        self.maintenant = maintenant or datetime.datetime.now()
        self.ancien = None
        self.cible = None
        self.dossier = None
        self.bases = []
        self.a_installer = False
        self.services_arretes = []

    # --- lecture et plan -------------------------------------------------

    def executer(self):
        """Rend True quand le serveur est à la version visée à la sortie,
        qu'il le fût déjà ou qu'il vienne de l'être ; False sinon."""
        if not (
            shutil.which("pg_lsclusters") and shutil.which("pg_upgradecluster")
        ):
            expliquer_non_pris_en_charge()
            return False
        clusters = lire_les_clusters()
        if clusters is None:
            print("❌ " + t("pg_lsclusters failed: cannot read the clusters."))
            return False
        self.ancien = next(
            (c for c in clusters if c["port"] == PORT_DEFAUT), None
        )
        if self.ancien is None:
            print(
                "❌ "
                + t("No PostgreSQL cluster on port {port}.").format(
                    port=PORT_DEFAUT
                )
            )
            return False
        odoo = odoo_active(self.racine)
        self.cible, requise = version_cible(odoo)
        if self.cible is None:
            print("❌ " + t("No PostgreSQL version to upgrade to."))
            return False
        version = self.ancien["version"]
        if majeure(version) >= (self.cible,):
            print(
                "✅ "
                + t(
                    "PostgreSQL {version} already meets {cible}: nothing to"
                    " do."
                ).format(version=version, cible=self.cible)
            )
            return True
        bases = lister_bases(self.ancien["port"])
        if bases is None:
            print(
                "❌ "
                + t("Cannot list the databases of cluster {cluster}.").format(
                    cluster=self._nom(version)
                )
            )
            return False
        self.bases = bases
        horodatage = self.maintenant.strftime("%Y-%m-%d_%Hh%Mm%Ss")
        self.dossier = os.path.join(
            self.racine,
            DOSSIER_SAUVEGARDES,
            f"postgresql_{version}_to_{self.cible}_{horodatage}",
        )
        services = [
            s
            for s in services_candidats(self.racine)
            if _code(["systemctl", "is-active", "--quiet", s]) == 0
        ]
        self.a_installer = not paquet_installe(self.cible)
        self._afficher_plan(odoo, requise, services)
        reponse = self.demander("💬 " + t("Upgrade now? (y/N): "))
        if not _oui(reponse):
            print(t("Cancelled."))
            return False
        return self._appliquer(services)

    def _nom(self, version):
        return f"{version}/{self.ancien['nom']}"

    def _afficher_plan(self, odoo, requise, services):
        ancien = self.ancien
        print("\n🐘 " + t("PostgreSQL upgrade plan"))
        print(
            "   "
            + t("Cluster {cluster}, port {port}").format(
                cluster=self._nom(ancien["version"]), port=ancien["port"]
            )
        )
        print(
            "   "
            + t("Version {ancien} -> {cible}").format(
                ancien=ancien["version"], cible=self.cible
            )
        )
        if requise:
            raison = t("the minimum Odoo {odoo} requires").format(odoo=odoo)
        else:
            raison = t("the newest available, no minimum set by Odoo")
        print(f"   ({raison})")
        print(
            "   " + t("Databases ({nombre}):").format(nombre=len(self.bases))
        )
        for nom, taille in self.bases:
            print(f"     - {nom}  {taille}")
        print("   " + t("Backups, pg_dump -Fc, one file per database, in:"))
        print(f"     {self.dossier}")
        if self.a_installer:
            print(
                "   "
                + t("postgresql-{cible} installed by: {commande}").format(
                    cible=self.cible,
                    commande=f"make install_os PG_VERSION={self.cible}",
                )
            )
        for service in services:
            print(
                "   "
                + t("Service {service} stopped, then restarted.").format(
                    service=service
                )
            )
        print(
            "   "
            + t(
                "The old cluster {cluster} is kept, stopped, until you drop"
                " it."
            ).format(cluster=self._nom(ancien["version"]))
        )
        print()

    # --- application ----------------------------------------------------

    def _appliquer(self, services):
        for service in services:
            if _code(["sudo", "systemctl", "stop", service]):
                return self._echec_avant(
                    t("Cannot stop {service}.").format(service=service)
                )
            self.services_arretes.append(service)
        if not self._sauvegarder():
            return False
        if self.a_installer:
            print(f"📦 make install_os PG_VERSION={self.cible}")
            code = _code(["make", "install_os", f"PG_VERSION={self.cible}"])
            if code or not paquet_installe(self.cible):
                return self._echec_avant(
                    t("postgresql-{cible} could not be installed.").format(
                        cible=self.cible
                    )
                )
        if not self._retirer_cluster_vide():
            return False
        version, nom = self.ancien["version"], self.ancien["nom"]
        code = _code(
            ["sudo", "pg_upgradecluster", "-v", str(self.cible), version, nom]
        )
        if code:
            return self._echec_apres(
                t("pg_upgradecluster failed (exit code {code}).").format(
                    code=code
                )
            )
        if not self._verifier():
            return False
        self._relancer_services()
        print(
            "\n✅ "
            + t(
                "PostgreSQL {cible} now serves the databases on port {port}."
            ).format(cible=self.cible, port=self.ancien["port"])
        )
        print("   " + t("Backups:") + f" {self.dossier}")
        print("   " + t("Once everything works, drop the old cluster with:"))
        print(f"     sudo pg_dropcluster {version} {nom}")
        return True

    def _sauvegarder(self):
        """Une sauvegarde par base ; False, après le message d'échec, dès
        qu'une échoue."""
        os.makedirs(self.dossier, exist_ok=True)
        for nom, _taille in self.bases:
            fichier = os.path.join(self.dossier, f"{nom}.dump")
            print(f"💾 {nom} -> {fichier}")
            code = _code(
                [
                    "pg_dump",
                    "-Fc",
                    "-p",
                    str(self.ancien["port"]),
                    "-f",
                    fichier,
                    nom,
                ]
            )
            if code or not os.path.isfile(fichier):
                self._echec_avant(
                    t("Backup of {base} failed (exit code {code}).").format(
                        base=nom, code=code
                    )
                )
                return False
        return True

    def _retirer_cluster_vide(self):
        """L'installation du paquet crée un cluster <cible>/main vide ; sous
        le même nom que l'ancien, il bloque pg_upgradecluster. Il n'est
        retiré que s'il ne porte aucune base."""
        clusters = lire_les_clusters()
        if clusters is None:
            return self._echec_avant(
                t("pg_lsclusters failed: cannot read the clusters.")
            )
        nom = self.ancien["nom"]
        neuf = next(
            (
                c
                for c in clusters
                if majeure(c["version"]) == (self.cible,) and c["nom"] == nom
            ),
            None,
        )
        if neuf is None:
            return True
        bases = lister_bases(neuf["port"], en_postgres=True)
        if bases is None:
            return self._echec_avant(
                t(
                    "Cannot tell whether cluster {cluster} is empty: check it,"
                    " then drop it with pg_dropcluster --stop {cible} {nom}."
                ).format(
                    cluster=self._nom(neuf["version"]),
                    cible=neuf["version"],
                    nom=nom,
                )
            )
        if bases:
            return self._echec_avant(
                t(
                    "Cluster {cluster} already holds databases: {bases}."
                ).format(
                    cluster=self._nom(neuf["version"]),
                    bases=", ".join(b for b, _ in bases),
                )
            )
        code = _code(
            ["sudo", "pg_dropcluster", "--stop", neuf["version"], nom]
        )
        if code:
            return self._echec_avant(
                t("Cannot drop the empty cluster {cluster}.").format(
                    cluster=self._nom(neuf["version"])
                )
            )
        return True

    def _verifier(self):
        """Le nouveau cluster est en ligne, sur le port de l'ancien, et
        porte les mêmes bases."""
        port = self.ancien["port"]
        clusters = lire_les_clusters() or []
        neuf = next(
            (
                c
                for c in clusters
                if majeure(c["version"]) == (self.cible,)
                and c["nom"] == self.ancien["nom"]
            ),
            None,
        )
        if (
            neuf is None
            or neuf["port"] != port
            or not neuf["etat"].startswith("online")
        ):
            return self._echec_apres(
                t("Cluster {cluster} is not online on port {port}.").format(
                    cluster=self._nom(self.cible), port=port
                )
            )
        apres = lister_bases(port)
        avant = sorted(b for b, _ in self.bases)
        if apres is None or sorted(b for b, _ in apres) != avant:
            return self._echec_apres(
                t("The new cluster does not list the same databases.")
            )
        return True

    def _relancer_services(self):
        for service in self.services_arretes:
            if _code(["sudo", "systemctl", "start", service]):
                print(
                    "⚠️  "
                    + t("Cannot restart {service}.").format(service=service)
                )
        self.services_arretes = []

    # --- échecs -----------------------------------------------------------

    def _echec_avant(self, raison):
        """Échec AVANT pg_upgradecluster : l'ancien cluster sert toujours
        les bases, seul le service est à relancer. Rend False."""
        print(f"\n❌ {raison}")
        print(
            "   "
            + t(
                "Upgrade stopped. Cluster {cluster} was not touched and still"
                " serves port {port}."
            ).format(
                cluster=self._nom(self.ancien["version"]),
                port=self.ancien["port"],
            )
        )
        self._relancer_services()
        return False

    def _echec_apres(self, raison):
        """Échec PENDANT ou APRÈS pg_upgradecluster : l'ancien cluster est
        toujours sur le disque ; le message donne de quoi y revenir.
        Rend False."""
        version, nom = self.ancien["version"], self.ancien["nom"]
        port = self.ancien["port"]
        print(f"\n❌ {raison}")
        print(
            "   "
            + t(
                "Upgrade stopped. The old cluster {cluster} is still on disk."
                " To go back to it:"
            ).format(cluster=self._nom(version))
        )
        print(f"     sudo pg_dropcluster --stop {self.cible} {nom}")
        print(f"     sudo pg_ctlcluster {version} {nom} start")
        print(
            "   "
            + t(
                "If pg_lsclusters then shows it on a port other than {port},"
                " set port = {port} in {conf} and restart it."
            ).format(
                port=port,
                conf=f"/etc/postgresql/{version}/{nom}/postgresql.conf",
            )
        )
        for service in self.services_arretes:
            print(f"     sudo systemctl start {service}")
        print("   " + t("Backups:") + f" {self.dossier}")
        return False


def mettre_a_niveau(racine=None, demander=input, maintenant=None):
    """Point d'entrée du menu ; voir MiseANiveau.executer."""
    return MiseANiveau(racine, demander, maintenant).executer()
