#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les sceaux PAdES de sign_oca_pades : générer, faire l'état, choisir sa clé.

Le module scelle chaque document signé avec un fichier PKCS#12 (`.p12`) qui
réunit la clé privée et son certificat. Ce menu produit ce fichier et le
certificat seul (`.crt`), à distribuer à qui vérifie les sceaux. Un sceau
auto-signé est le sceau interne de l'organisation : il prouve l'intégrité
partout, et l'identité là où son certificat est approuvé. Une autorité
reconnue n'ajoute que l'approbation chez des lecteurs qui ne le connaissent
pas ; le guide du menu explique les deux voies.

La clé n'est jamais écrite en clair : `openssl req` la chiffre avec le mot de
passe du `.p12`, `openssl pkcs12` la relit pour l'exporter, puis elle est
effacée. Le mot de passe passe par l'environnement du sous-processus, jamais
en argument, où `ps` le montrerait.

Le dossier ne doit pas pouvoir être commité. `private/` ne suffit pas : il est
versionné, sur un dépôt privé. `private/sceau/` est ignoré par `.gitignore`,
et `chemin_commitable` interroge le dépôt qui CONTIENT le dossier : un dossier
dans un dépôt d'addons est ignoré par la racine, mais pas par son propre
dépôt.

Le dossier étant libre, `registre.json`, dans `private/sceau/`, retient ceux où
un sceau a été généré : l'état les relit, avec le dossier par défaut.
"""

import datetime
import getpass
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile

from script.todo.todo_i18n import t

RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
DOSSIER_DEFAUT = os.path.join("private", "sceau")
REGISTRE = os.path.join(RACINE, DOSSIER_DEFAUT, "registre.json")
NOM_CRT = "sceau.crt"
NOM_P12 = "sceau.p12"
# La clé chiffrée, le temps de l'export, dans le sous-dossier de travail.
NOM_CLE = "sceau.key"
PREFIXE_TRAVAIL = ".sceau-"
JOURS_DEFAUT = 1095
# Sous ce seuil, l'état annonce l'échéance : le temps de générer un sceau et
# de redistribuer son certificat.
JOURS_ALERTE = 30
TAILLE_CLE = 3072
# pyHanko exige la non-répudiation d'un signataire : sans elle, les sceaux
# restent intacts, mais leur vérification les déclare non approuvés.
USAGE_CLE = "keyUsage=critical,digitalSignature,nonRepudiation"
VAR_MDP = "ERPLIBRE_SCEAU_MDP"
# Séparateurs de la syntaxe -subj d'openssl : un nom qui en porte serait
# découpé en d'autres attributs que le CN.
CARACTERES_INTERDITS = "/\\=+,"
# Limites du CN et du O dans X.509 (RFC 5280, ub-common-name et
# ub-organization-name).
LONGUEUR_NOM_MAX = 64
# Un nom de fichier qui porte une clé privée : sceau PKCS#12, .pfx, clé PKCS#8
# ou PEM, y compris leurs copies (« sceau.p12.bak », « cle.key~ »).
MOTIF_CLE = re.compile(r"\.(p12|pfx|p8|key)(\.|~|$)", re.IGNORECASE)
# Un .pem porte un certificat ou une clé : seul son contenu tranche.
MOTIF_PEM = re.compile(r"\.pem(\.|~|$)", re.IGNORECASE)
MARQUE_CLE_PEM = b"PRIVATE KEY-----"
# Les dépôts du checkout que Google Repo gère, un chemin relatif par ligne.
LISTE_DEPOTS = os.path.join(".repo", "project.list")
URL_AATL = "https://helpx.adobe.com/acrobat/kb/approved-trust-list1.html"
# Numéros des entrées du menu Sécurité que les textes citent.
ENTREE_ETAT = "2"
ENTREE_GUIDE = "3"
ENTREE_GENERER = "4"


def _depot_englobant(dossier):
    """Le plus proche dossier, de ``dossier`` jusqu'à la racine du système,
    qui porte une entrée ``.git`` : dossier d'un dépôt, ou fichier d'un
    sous-module et d'un worktree. None hors de tout dépôt."""
    courant = dossier
    while True:
        if os.path.lexists(os.path.join(courant, ".git")):
            return courant
        parent = os.path.dirname(courant)
        if parent == courant:
            return None
        courant = parent


def chemin_commitable(chemin):
    """Vrai quand git pourrait commiter un fichier à ``chemin``.

    Le dépôt interrogé est celui qui contient le plus proche dossier
    existant de ``chemin`` : le fichier n'a pas besoin d'exister. Hors de
    tout dépôt, rien ne peut le commiter. Dans un dépôt, il faut qu'une
    règle l'ignore ; un fichier déjà suivi n'est pas ignoré, même sous une
    règle. Un dépôt que git ne sait pas interroger (propriétaire douteux,
    ``.git`` qui pointe dans le vide, git absent) compte comme commitable :
    le doute refuse."""
    # Seul le dossier est résolu : os.replace écrit à l'emplacement du nom
    # et remplace un lien symbolique qui s'y trouve, au lieu de le suivre.
    dossier = os.path.realpath(os.path.dirname(os.path.abspath(chemin)))
    absolu = os.path.join(dossier, os.path.basename(chemin))
    existant = dossier
    while not os.path.isdir(existant):
        existant = os.path.dirname(existant)
    depot = _depot_englobant(existant)
    if depot is None:
        return False
    try:
        ignore = subprocess.run(
            ["git", "-C", depot, "check-ignore", "-q", absolu],
            capture_output=True,
        )
    except OSError:
        return True
    # 0 : ignoré ; 1 : pas ignoré ; 128 : git n'a pas pu répondre.
    return ignore.returncode != 0


def chemins_a_proteger(dossier):
    """Les chemins que la génération écrit dans ``dossier``, clé chiffrée
    du sous-dossier de travail comprise : chacun doit être hors de portée
    de git."""
    return [
        os.path.join(dossier, NOM_CRT),
        os.path.join(dossier, NOM_P12),
        os.path.join(dossier, f"{PREFIXE_TRAVAIL}x", NOM_CLE),
    ]


def sujet_openssl(nom_commun, organisation=""):
    """Le sujet ``-subj`` : le CN, puis le O quand l'organisation est
    nommée."""
    sujet = f"/CN={nom_commun}"
    if organisation:
        sujet += f"/O={organisation}"
    return sujet


def nom_refuse(nom):
    """La raison de refuser ``nom`` comme CN ou O, ou None : un séparateur
    de la syntaxe -subj, ou plus de ``LONGUEUR_NOM_MAX`` caractères."""
    if any(c in nom for c in CARACTERES_INTERDITS):
        return (
            t("The name cannot contain any of these characters: %s")
            % CARACTERES_INTERDITS
        )
    if len(nom) > LONGUEUR_NOM_MAX:
        return t("The name is limited to %s characters.") % LONGUEUR_NOM_MAX
    return None


def commandes_openssl(dossier, nom_commun, jours, organisation=""):
    """Les deux commandes, en listes d'arguments, qui produisent le sceau.

    La première crée la clé, chiffrée par le mot de passe lu dans
    ``VAR_MDP``, et le certificat auto-signé ; la seconde les réunit dans le
    ``.p12``, chiffré par le même mot de passe."""
    cle = os.path.join(dossier, NOM_CLE)
    crt = os.path.join(dossier, NOM_CRT)
    p12 = os.path.join(dossier, NOM_P12)
    return [
        [
            # -utf8 : un nom accentué arrive tel quel dans le sujet.
            # -quiet : sans la barre de progression de la génération RSA,
            # l'erreur d'openssl reste lisible.
            "openssl", "req", "-x509", "-utf8", "-quiet",
            "-newkey", f"rsa:{TAILLE_CLE}",
            "-days", str(jours),
            "-keyout", cle,
            "-out", crt,
            "-subj", sujet_openssl(nom_commun, organisation),
            "-addext", USAGE_CLE,
            "-passout", f"env:{VAR_MDP}",
        ],
        [
            "openssl", "pkcs12", "-export",
            "-inkey", cle,
            "-in", crt,
            "-out", p12,
            "-name", nom_commun,
            "-passin", f"env:{VAR_MDP}",
            "-passout", f"env:{VAR_MDP}",
        ],
    ]  # fmt: skip


def generer_sceau(dossier, nom_commun, jours, mot_de_passe, organisation=""):
    """Écrit ``sceau.crt`` et ``sceau.p12`` dans ``dossier`` et rend les
    deux chemins.

    openssl travaille dans un sous-dossier temporaire en 0700 ; les deux
    fichiers n'arrivent dans ``dossier`` qu'une fois le ``.p12`` exporté, par
    ``os.replace``. Un sceau existant est donc remplacé en entier ou pas du
    tout, et les fichiers arrivent en 0600 même quand l'ancien était plus
    ouvert. Le sous-dossier, et la clé chiffrée qu'il contient, sont effacés
    dans tous les cas. Lève ``subprocess.CalledProcessError`` quand openssl
    échoue."""
    os.makedirs(dossier, mode=0o700, exist_ok=True)
    env = dict(os.environ, **{VAR_MDP: mot_de_passe})
    travail = tempfile.mkdtemp(prefix=PREFIXE_TRAVAIL, dir=dossier)
    masque = os.umask(0o077)
    try:
        commandes = commandes_openssl(travail, nom_commun, jours, organisation)
        for commande in commandes:
            subprocess.run(commande, env=env, check=True, capture_output=True)
        rendus = []
        for nom in (NOM_CRT, NOM_P12):
            cible = os.path.join(dossier, nom)
            os.chmod(os.path.join(travail, nom), 0o600)
            os.replace(os.path.join(travail, nom), cible)
            rendus.append(cible)
    finally:
        os.umask(masque)
        shutil.rmtree(travail, ignore_errors=True)
    return tuple(rendus)


def a_la_non_repudiation(crt):
    """Vrai quand le certificat porte l'usage de clé que pyHanko exige."""
    sortie = subprocess.run(
        ["openssl", "x509", "-in", crt, "-noout", "-ext", "keyUsage"],
        capture_output=True,
        text=True,
    )
    return sortie.returncode == 0 and "Non Repudiation" in sortie.stdout


def _date_iso(valeur):
    """``AAAA-MM-JJ HH:MM:SSZ``, la forme de ``-dateopt iso_8601``, en
    datetime UTC ; None quand openssl a écrit autre chose."""
    try:
        return datetime.datetime.strptime(
            valeur.strip(), "%Y-%m-%d %H:%M:%SZ"
        ).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def infos_certificat(crt):
    """Ce que l'état affiche d'un certificat, ou None quand openssl ne le
    lit pas : ``sujet``, ``debut`` et ``fin`` (datetime UTC, ou None),
    ``empreinte`` (SHA-256, octets séparés par des deux-points) et
    ``non_repudiation``."""
    sortie = subprocess.run(
        ["openssl", "x509", "-in", crt, "-noout",
         "-subject", "-nameopt", "utf8,sep_comma_plus_space",
         "-dateopt", "iso_8601", "-startdate", "-enddate",
         "-fingerprint", "-sha256"],
        capture_output=True,
    )  # fmt: skip
    if sortie.returncode != 0:
        return None
    infos = {"sujet": "", "debut": None, "fin": None, "empreinte": ""}
    for ligne in sortie.stdout.decode(errors="replace").splitlines():
        cle, _, valeur = ligne.partition("=")
        cle = cle.strip().lower()
        if cle == "subject":
            infos["sujet"] = valeur.strip()
        elif cle == "notbefore":
            infos["debut"] = _date_iso(valeur)
        elif cle == "notafter":
            infos["fin"] = _date_iso(valeur)
        elif cle.endswith("fingerprint"):
            infos["empreinte"] = valeur.strip()
    infos["non_repudiation"] = a_la_non_repudiation(crt)
    return infos


def _charger_registre(registre):
    """Les dossiers du registre ; [] s'il n'existe pas. Lève ValueError
    quand le fichier existe mais n'est pas un registre."""
    try:
        with open(registre, encoding="utf-8") as fichier:
            entrees = json.load(fichier)
    except FileNotFoundError:
        return []
    if not isinstance(entrees, list):
        raise ValueError(registre)
    dossiers = []
    for entree in entrees:
        dossier = entree.get("dossier") if isinstance(entree, dict) else None
        if isinstance(dossier, str) and dossier not in dossiers:
            dossiers.append(dossier)
    return dossiers


def lire_registre(registre=None):
    """Les dossiers inscrits au registre, sans doublon, dans l'ordre
    d'inscription. Un registre absent ou illisible est vide."""
    try:
        return _charger_registre(registre or REGISTRE)
    except (OSError, ValueError):
        return []


def _ecrire_registre(dossiers, registre):
    """Remplace le registre par ``dossiers``, d'un seul ``os.replace`` : une
    interruption laisse l'ancien registre entier. Le registre ne porte que
    des chemins, aucun secret ; il est quand même écrit en 0600, dans un
    dossier en 0700, comme les sceaux."""
    os.makedirs(os.path.dirname(registre), mode=0o700, exist_ok=True)
    descripteur, provisoire = tempfile.mkstemp(
        prefix=".registre-", dir=os.path.dirname(registre)
    )
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
            json.dump(
                [{"dossier": d} for d in dossiers],
                fichier,
                ensure_ascii=False,
                indent=2,
            )
        os.replace(provisoire, registre)
    except BaseException:
        os.remove(provisoire)
        raise


def inscrire_sceau(dossier, registre=None):
    """Ajoute ``dossier`` au registre s'il n'y est pas. Un registre
    illisible n'est pas écrasé : ValueError, pour que l'appelant le dise."""
    registre = registre or REGISTRE
    dossiers = _charger_registre(registre)
    absolu = os.path.abspath(dossier)
    if absolu not in dossiers:
        _ecrire_registre(dossiers + [absolu], registre)


def retirer_du_registre(retires, registre=None):
    """Retire ``retires`` du registre ; les autres dossiers restent dans
    leur ordre."""
    registre = registre or REGISTRE
    dossiers = _charger_registre(registre)
    _ecrire_registre([d for d in dossiers if d not in retires], registre)


def sceaux_connus(registre=None, dossier_defaut=None):
    """Les dossiers dont l'état rend compte : ceux du registre, puis le
    dossier par défaut s'il porte un certificat sans y être inscrit."""
    dossiers = lire_registre(registre)
    defaut = os.path.abspath(
        dossier_defaut or os.path.join(RACINE, DOSSIER_DEFAUT)
    )
    if defaut not in dossiers and os.path.isfile(
        os.path.join(defaut, NOM_CRT)
    ):
        dossiers.append(defaut)
    return dossiers


def porte_une_cle(depot, nom):
    """Vrai quand le fichier ``nom`` du dépôt ``depot`` porte une clé
    privée : par son nom, ou par son contenu pour un ``.pem``. Un ``.pem``
    illisible, retiré de la copie de travail mais encore indexé par
    exemple, compte comme une clé : le doute signale."""
    if MOTIF_CLE.search(nom):
        return True
    if not MOTIF_PEM.search(nom):
        return False
    try:
        with open(os.path.join(depot, nom), "rb") as fichier:
            return MARQUE_CLE_PEM in fichier.read(65536)
    except OSError:
        return True


def depots_du_checkout(racine=None):
    """Le dépôt ``racine``, puis ceux de Google Repo présents sur le disque
    (``.repo/project.list``) : la racine ignore les dossiers d'addons, que
    leur propre dépôt peut commiter."""
    racine = racine or RACINE
    depots = [racine]
    try:
        with open(os.path.join(racine, LISTE_DEPOTS), encoding="utf-8") as f:
            chemins = [ligne.strip() for ligne in f if ligne.strip()]
    except OSError:
        chemins = []
    for chemin in chemins:
        depot = os.path.join(racine, chemin)
        if os.path.lexists(os.path.join(depot, ".git")):
            depots.append(depot)
    return depots


def _git_liste(depot, *options):
    """Les chemins que rend ``git ls-files -z`` avec ``options``, ou None
    quand git ne répond pas."""
    try:
        sortie = subprocess.run(
            ["git", "-C", depot, "ls-files", "-z", *options],
            capture_output=True,
        )
    except OSError:
        return None
    if sortie.returncode != 0:
        return None
    return [n for n in sortie.stdout.decode(errors="replace").split("\0") if n]


def _deja_commite(depot, nom):
    """Vrai quand ``nom`` figure dans un commit d'une branche ou d'une
    étiquette ; une erreur de git compte comme commité."""
    try:
        sortie = subprocess.run(
            ["git", "-C", depot, "log", "--all", "-1", "--format=%H",
             "--", nom],
            capture_output=True,
        )  # fmt: skip
    except OSError:
        return True
    return sortie.returncode != 0 or bool(sortie.stdout.strip())


def cles_du_depot(depot):
    """Les fichiers de clé que git voit dans ``depot`` : liste de
    ``(nom, état)``, où l'état est ``commité`` (dans l'historique),
    ``indexé`` (suivi, pas encore commité) ou ``non suivi`` (ni suivi ni
    ignoré). None quand git ne répond pas."""
    suivis = _git_liste(depot, "--cached")
    libres = _git_liste(depot, "--others", "--exclude-standard")
    if suivis is None or libres is None:
        return None
    cles = []
    for nom in suivis:
        if porte_une_cle(depot, nom):
            etat = "commité" if _deja_commite(depot, nom) else "indexé"
            cles.append((nom, etat))
    for nom in libres:
        if porte_une_cle(depot, nom):
            cles.append((nom, "non suivi"))
    return cles


def _empreinte_fichier(chemin):
    """Le SHA-256 du contenu de ``chemin``, ou None s'il est illisible."""
    try:
        with open(chemin, "rb") as fichier:
            return hashlib.sha256(fichier.read()).hexdigest()
    except OSError:
        return None


def est_un_de_nos_sceaux(chemin, empreintes):
    """Vrai quand ``chemin`` est un sceau de ce menu : nommé comme lui
    (``sceau.p12``, ``sceau.key``), ou identique à un ``.p12`` connu, dont
    ``empreintes`` porte les SHA-256."""
    nom = os.path.basename(chemin)
    if nom.startswith(os.path.splitext(NOM_P12)[0] + "."):
        return True
    return _empreinte_fichier(chemin) in empreintes


def cles_a_portee_de_git(racine=None, empreintes=frozenset()):
    """Les fichiers de clé que git voit dans les dépôts du checkout, et les
    dépôts que git n'a pas su lire : ``([(chemin relatif à racine, état),
    ...], [dépôt, ...])``.

    Dans le dépôt racine, toute clé compte. Dans un dépôt d'addons, une clé
    déjà commitée est d'ordinaire une donnée d'essai de l'amont (Odoo, OCA)
    : elle ne compte que si c'est un de nos sceaux (``est_un_de_nos_sceaux``,
    avec ``empreintes``). Une clé indexée ou non suivie y compte toujours :
    elle vient du checkout."""
    racine = racine or RACINE
    cles, muets = [], []
    for depot in depots_du_checkout(racine):
        trouvees = cles_du_depot(depot)
        if trouvees is None:
            muets.append(depot)
            continue
        for nom, etat in trouvees:
            chemin = os.path.join(depot, nom)
            if (
                depot != racine
                and etat == "commité"
                and not est_un_de_nos_sceaux(chemin, empreintes)
            ):
                continue
            cles.append((os.path.relpath(chemin, racine), etat))
    return cles, muets


def jours_restants(fin, maintenant=None):
    """Les jours de calendrier (UTC) jusqu'à ``fin`` : 0 le jour même,
    négatif une fois échu."""
    maintenant = maintenant or datetime.datetime.now(datetime.timezone.utc)
    return (fin.date() - maintenant.date()).days


class SealMenuMixin:
    def execute_seal_status(self):
        print(t("Status of the generated seals"))
        dossiers = sceaux_connus()
        if not dossiers:
            print(
                t("No seal generated yet: use entry « %s ».") % ENTREE_GENERER
            )
        vides = [d for d in dossiers if not self._seal_status_folder(d)]
        empreintes = {
            _empreinte_fichier(os.path.join(d, NOM_P12)) for d in dossiers
        } - {None}
        self._seal_status_keys_in_git(empreintes)
        print()
        print(
            t(
                "The Odoo database is not read here: the seal it uses shows"
                " in Sign › Settings › General settings, Document Sealing"
                " (PAdES) section."
            )
        )
        if vides and self._is_yes(
            input(
                f"💬 {t('Remove the %s folders without a seal from the registry? (y/N): ') % len(vides)}"
            )
        ):
            try:
                retirer_du_registre(vides)
            except (OSError, ValueError) as erreur:
                print(f"❌ {t('Cannot update the registry:')} {erreur}")

    def _seal_status_folder(self, dossier):
        """Affiche l'état du sceau de ``dossier`` ; faux quand il n'y reste
        ni certificat ni ``.p12``."""
        print(f"\n📁 {dossier}")
        crt = os.path.join(dossier, NOM_CRT)
        p12 = os.path.join(dossier, NOM_P12)
        if not os.path.isfile(crt) and not os.path.isfile(p12):
            print(f"\t❌ {t('No seal here anymore.')}")
            return False
        infos = infos_certificat(crt) if os.path.isfile(crt) else None
        if infos is None:
            print(f"\t❌ {t('No readable certificate:')} {crt}")
        else:
            print(f"\t{t('Subject:')} {infos['sujet']}")
            self._seal_status_validity(infos)
            print(f"\t{t('SHA-256 fingerprint:')} {infos['empreinte']}")
            if infos["non_repudiation"]:
                print(f"\t✅ {t('Non repudiation key usage')}")
            else:
                print(
                    f"\t❌ {t('No non repudiation key usage: pyHanko reports the seals as untrusted.')}"
                )
        if not os.path.isfile(p12):
            print(f"\t❌ {t('No .p12 file:')} {p12}")
        else:
            mode = stat.S_IMODE(os.stat(p12).st_mode)
            if mode & 0o077:
                print(
                    f"\t⚠️ {t('The .p12 file is readable by other accounts (%s): chmod 600.') % oct(mode)}"
                )
            else:
                print(
                    f"\t✅ {t('.p12 file present, readable by its owner only')}"
                )
        if any(chemin_commitable(p) for p in (crt, p12)):
            print(f"\t❌ {t('Git could commit this seal.')}")
        else:
            print(f"\t✅ {t('Out of reach of git')}")
        return True

    def _seal_status_validity(self, infos):
        debut, fin = infos["debut"], infos["fin"]
        if fin is None:
            print(f"\t⚠️ {t('Validity dates unreadable')}")
            return
        periode = f"{debut:%Y-%m-%d} → {fin:%Y-%m-%d}" if debut else ""
        reste = jours_restants(fin)
        if reste == 0:
            print(f"\t⚠️ {t('Validity:')} {periode}, {t('expires today')}")
        elif reste < 0:
            print(
                f"\t❌ {t('Validity:')} {periode},"
                f" {t('expired %s days ago') % -reste}"
            )
        elif reste < JOURS_ALERTE:
            print(
                f"\t⚠️ {t('Validity:')} {periode},"
                f" {t('expires in %s days') % reste}"
            )
        else:
            print(
                f"\t✅ {t('Validity:')} {periode},"
                f" {t('%s days left') % reste}"
            )

    def _seal_status_keys_in_git(self, empreintes=frozenset()):
        cles, muets = cles_a_portee_de_git(empreintes=empreintes)
        print(
            f"\n🔑 {t('Key files git can see in the repositories of the checkout:')}"
        )
        print(
            f"\t{t('Test keys the upstream repositories (Odoo, OCA) commit are not listed.')}"
        )
        for depot in muets:
            print(
                f"\t⚠️ {t('Git cannot be queried in %s: its key files are not checked.') % depot}"
            )
        if not cles:
            if not muets:
                print(f"\t✅ {t('No key file')}")
            return
        libelles = {
            "commité": ("❌", t("in the history: the key is exposed")),
            "indexé": ("❌", t("staged: it leaves with the next commit")),
            "non suivi": ("⚠️", t("not ignored, one git add away")),
        }
        for chemin, etat in cles:
            icone, libelle = libelles[etat]
            print(f"\t{icone} {chemin} — {libelle}")
        etats = {etat for _, etat in cles}
        if "commité" in etats:
            print(
                t(
                    "A committed key is exposed, even once deleted: generate"
                    " a new seal (entry « %s »), replace it in Odoo and on the"
                    " workstations, then untrack the file (git rm --cached)"
                    " and purge it from the history if it was pushed."
                )
                % ENTREE_GENERER
            )
        if "indexé" in etats:
            print(
                t(
                    "A staged key: git rm --cached <file> in its repository,"
                    " then delete it or move it into %s."
                )
                % DOSSIER_DEFAUT
            )
        if "non suivi" in etats:
            print(
                t(
                    "Delete these files, or move them out of the repository"
                    " or into %s."
                )
                % DOSSIER_DEFAUT
            )

    def execute_seal_guide(self):
        print(t("Internal or external key?"))
        print(f"\n{t('What a seal proves')}")
        for point in (
            t(
                "Integrity: the document has not changed since the seal."
                " Every certificate proves it, a self-signed one included."
            ),
            t(
                "Identity: the seal comes from your organisation. A PDF"
                " reader asserts it only when the certificate chains to a"
                " root it trusts: Adobe's AATL list, the eIDAS list in"
                " Europe, or a certificate imported on the workstation."
            ),
            t(
                "The timestamp is separate: a recognised timestamping server"
                " is trusted by Adobe even with an internal seal."
            ),
        ):
            print(f"\t• {point}")
        externe = self._is_yes(
            input(
                f"\n💬 {t('Are the sealed PDFs opened outside the organisation, in a reader nobody configures? (y/N): ')}"
            )
        )
        if externe:
            self._seal_guide_external()
        else:
            self._seal_guide_internal()

    def _seal_guide_internal(self):
        print(f"\n{t('Internal key: the official seal of the organisation')}")
        print(
            t(
                "A seal generated here is the official seal of your"
                " organisation. Odoo trusts it as is; the workstations of the"
                " organisation trust it once its certificate is imported."
            )
        )
        etapes = (
            t(
                "Generate the seal (entry « %s ») and upload the .p12 to"
                " Odoo, with its password."
            )
            % ENTREE_GENERER,
            t(
                "Distribute sceau.crt, never the .p12, to the workstations"
                " that read the PDFs."
            ),
            t(
                "Send its SHA-256 fingerprint (entry « %s ») through another"
                " channel, so everyone checks they import the right"
                " certificate."
            )
            % ENTREE_ETAT,
            t(
                "In Adobe: Preferences › Signatures › Identities & Trusted"
                " Certificates › More › Trusted Certificates › Import, then"
                " Edit Trust › tick « Use this certificate as a trusted root"
                " ». On a managed fleet, deploy it by group policy or Adobe's"
                " customization tool."
            ),
            t(
                "Before it expires (entry « %s »), generate a new seal and"
                " distribute its certificate again. An internal authority"
                " (openssl, step-ca, XCA, EJBCA) avoids that: only its root"
                " is imported, once."
            )
            % ENTREE_ETAT,
        )
        for numero, etape in enumerate(etapes, start=1):
            print(f"\t{numero}. {etape}")
        print(
            t(
                "A reader outside the organisation shows « signer untrusted »:"
                " the document stays intact and verifiable, only its"
                " identity is not recognised. For those readers, answer yes"
                " to the question: external key."
            )
        )

    def _seal_guide_external(self):
        print(f"\n{t('External key: trusted everywhere')}")
        for point in (
            t(
                "An authority on Adobe's AATL list checks the identity of the"
                " organisation; Adobe then trusts the seal for every"
                " recipient, with nothing to configure."
            ),
            t(
                "Its rules require the key to stay in certified hardware"
                " (FIPS 140-2 level 2 or higher): USB token, HSM or remote"
                " signing service. The key is never exportable: there is no"
                " .p12."
            ),
            t(
                "For a server that seals on its own, take a hosted HSM with"
                " an API, for instance Notarius CertifiO for organisations"
                " (in Canada), SSL.com eSigner, or the HSM offers of DigiCert"
                " and GlobalSign. Offers on a USB token only sign by hand."
            ),
            t(
                "sign_oca_pades reads only a .p12 today: an external key"
                " needs the module adapted (pyHanko signs through PKCS#11 or"
                " a remote service)."
            ),
            t(
                "Until then, an internal seal already works: only the display"
                " for outside readers differs."
            ),
        ):
            print(f"\t• {point}")
        print(f"\t{t('AATL members:')} {URL_AATL}")

    def _seal_ask_folder(self):
        """Le dossier du sceau, ou None : hors de portée de git, et un
        sceau existant n'y est remplacé que sur un oui."""
        reponse = input(
            f"💬 {t('Folder for the seal (default: %s): ') % DOSSIER_DEFAUT}"
        ).strip()
        dossier = os.path.abspath(
            os.path.join(RACINE, os.path.expanduser(reponse or DOSSIER_DEFAUT))
        )
        crt = os.path.join(dossier, NOM_CRT)
        p12 = os.path.join(dossier, NOM_P12)
        commitables = [
            p for p in chemins_a_proteger(dossier) if chemin_commitable(p)
        ]
        if commitables:
            print(
                f"❌ {t('Git could commit this file, which holds a private key:')}"
            )
            for p in commitables:
                print(f"\t{p}")
            print(
                t(
                    "Choose a folder that git ignores, such as %s, or a"
                    " folder outside every repository."
                )
                % DOSSIER_DEFAUT
            )
            return None
        existants = [p for p in (crt, p12) if os.path.exists(p)]
        if existants:
            print(t("A seal already exists here:"))
            for p in existants:
                print(f"\t{p}")
            if not self._is_yes(input(f"💬 {t('Replace it? (y/N): ')}")):
                return None
        return dossier

    def _seal_ask_identity(self):
        """``(organisation, nom commun, jours)``, ou None quand une réponse
        est refusée."""
        organisation = input(
            f"💬 {t('Organisation name (optional): ')}"
        ).strip()
        if organisation and nom_refuse(organisation):
            print(nom_refuse(organisation))
            return None
        defaut_cn = t("Document seal")
        nom_commun = (
            input(
                f"💬 {t('Certificate name (default: %s): ') % defaut_cn}"
            ).strip()
            or defaut_cn
        )
        if nom_refuse(nom_commun):
            print(nom_refuse(nom_commun))
            return None
        reponse = input(
            f"💬 {t('Validity in days (default: %s): ') % JOURS_DEFAUT}"
        ).strip()
        # isdecimal et non isdigit : « ² » est un chiffre, que int() refuse.
        if reponse and not (reponse.isdecimal() and int(reponse) > 0):
            print(f"{t('Error, cannot understand value')} '{reponse}'")
            return None
        jours = int(reponse or JOURS_DEFAUT)
        return organisation, nom_commun, jours

    def _seal_ask_password(self):
        """Le mot de passe du ``.p12``, saisi deux fois, ou None."""
        # getpass et non input : le mot de passe ne doit rester ni à
        # l'écran ni dans l'historique du terminal.
        mot_de_passe = getpass.getpass(t("Password of the .p12 file: "))
        if not mot_de_passe:
            print(t("The password cannot be empty."))
            return None
        if mot_de_passe != getpass.getpass(t("Password again: ")):
            print(t("The two passwords differ."))
            return None
        return mot_de_passe

    def execute_generate_seal(self):
        print(t("Generate an internal PAdES seal (self-signed)"))
        print(
            t(
                "A self-signed seal is the internal seal of your organisation:"
                " its seals prove the document has not changed, Odoo trusts"
                " it as is, and the workstations that import its certificate"
                " show it as trusted. A reader outside the organisation shows"
                " the signer as untrusted: see entry « %s »."
            )
            % ENTREE_GUIDE
        )
        dossier = self._seal_ask_folder()
        if dossier is None:
            return
        identite = self._seal_ask_identity()
        if identite is None:
            return
        organisation, nom_commun, jours = identite
        mot_de_passe = self._seal_ask_password()
        if mot_de_passe is None:
            return
        try:
            crt, p12 = generer_sceau(
                dossier, nom_commun, jours, mot_de_passe, organisation
            )
        except subprocess.CalledProcessError as erreur:
            print(f"❌ {t('openssl failed:')} {erreur}")
            if erreur.stderr:
                print(erreur.stderr.decode(errors="replace").strip())
            return
        except OSError as erreur:
            print(f"❌ {t('Cannot write the seal:')} {erreur}")
            return
        try:
            inscrire_sceau(dossier)
        except (OSError, ValueError) as erreur:
            print(
                f"⚠️ {t('The seal is written, but not its registration:')}"
                f" {erreur}"
            )
        if not a_la_non_repudiation(crt):
            print(
                f"⚠️ {t('The certificate lacks the non repudiation key usage: pyHanko will report its seals as untrusted.')}"
            )
        print(f"✅ {t('Seal written:')}")
        print(f"\t{p12}")
        print(f"\t{crt}")
        infos = infos_certificat(crt)
        if infos and infos["empreinte"]:
            print(
                t(
                    "SHA-256 fingerprint, to send through another channel"
                    " with sceau.crt:"
                )
            )
            print(f"\t{infos['empreinte']}")
        print(
            t(
                "Next: Sign › Settings › General settings, Document Sealing"
                " (PAdES) section, upload the .p12 with its password. Or, in"
                " odoo.conf [options]: sign_oca_pades_pkcs12_path and"
                " sign_oca_pades_pkcs12_password, then restart Odoo."
            )
        )
        print(
            t(
                "Then import sceau.crt as trusted on the workstations of the"
                " organisation: see entry « %s »."
            )
            % ENTREE_GUIDE
        )
