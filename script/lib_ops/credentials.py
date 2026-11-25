# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les secrets d'une unité systemd : credentials `LoadCredential*=`.

Un déployeur range chaque secret d'une unité dans un fichier à root, que
systemd remet au service au démarrage dans `$CREDENTIALS_DIRECTORY/<nom>`.
Le stockage dépend de la version de systemd (`choisir_stockage`) :

- 250 et plus, avec `systemd-creds` : le secret est chiffré par
  `systemd-creds encrypt --with-key=host`, qui le reçoit sur son entrée
  standard, dans `/etc/credstore.encrypted/<unité>.<nom>` ; la ligne
  d'unité est `LoadCredentialEncrypted=`. `--with-key=host` plutôt
  qu'`auto` : une clé liée au TPM casserait à la migration ou à la
  restauration d'une VM. Le fichier chiffré ne se lit qu'avec
  `/var/lib/systemd/credential.secret` de l'hôte : restaurer `/etc` seul
  rend l'unité incapable de démarrer.
- 247 à 249, ou `systemd-creds` absent : le secret est écrit en clair,
  0600 root, dans `/etc/credstore/<unité>.<nom>` ; la ligne est
  `LoadCredential=`.
- avant 247, ou version inconnue : refus, aucun fichier écrit.

Les chemins des lignes d'unité sont absolus : la recherche par nom dans
`/etc/credstore*` n'existe qu'à partir de systemd 252. Le secret ne passe
jamais sur une ligne de commande ni dans l'environnement : seuls des
chemins et des noms y paraissent.

Côté outil, `fichier` résout le fichier d'un secret : le credential de
l'unité d'abord, puis l'option de la ligne de commande, puis le chemin du
profil.

Ce module ne traduit rien : les messages sont des modèles anglais marqués
par `N_()`, que l'outil traduit par sa propre fonction `t`.

Bibliothèque standard seulement, sans syntaxe postérieure à Python 3.7.
"""

from __future__ import annotations

import collections
import os
import re
import shutil
import stat
import tempfile

from script.lib_ops import systemd

DOSSIER_CLAIR = "/etc/credstore"
DOSSIER_CHIFFRE = "/etc/credstore.encrypted"
DOSSIERS = (DOSSIER_CLAIR, DOSSIER_CHIFFRE)

# LoadCredential= paraît dans systemd 247, LoadCredentialEncrypted= et
# `systemd-creds` dans 250.
VERSION_MINIMALE = 247
VERSION_CHIFFREE = 250

# Taille maximale d'un credential que systemd accepte (CREDENTIAL_SIZE_MAX).
TAILLE_MAX = 1024 * 1024

MODE_FICHIER = 0o600
MODE_DOSSIER = 0o700

# Nom de credential admis : un nom de fichier sans « : », qui sépare le nom
# du chemin dans la ligne d'unité.
RE_NOM = re.compile(r"[A-Za-z0-9_.-]+")

RE_LIGNE = re.compile(
    r"^(LoadCredential|LoadCredentialEncrypted)=([^:\s]+):(\S+)[ \t]*$",
    re.M,
)

VARIABLE = "CREDENTIALS_DIRECTORY"


def N_(texte):
    """Marque un modèle de message à traduire par l'outil appelant."""
    return texte


class ErreurCredential(Exception):
    """Un credential refusé : `modele` (anglais) et ses `valeurs`, qui ne
    citent jamais le contenu d'un secret. `message(t)` le rend traduit."""

    def __init__(self, modele, **valeurs):
        self.modele = modele
        self.valeurs = valeurs
        super().__init__(modele.format(**valeurs) if valeurs else modele)

    def message(self, t=None):
        texte = t(self.modele) if t else self.modele
        return texte.format(**self.valeurs) if self.valeurs else texte


Stockage = collections.namedtuple(
    "Stockage", "chiffre version dossier directive"
)


def nom_valide(nom):
    """True si `nom` peut nommer un credential : dans `RE_NOM`, ni « . »
    ni « .. »."""
    return (
        bool(nom)
        and RE_NOM.fullmatch(nom) is not None
        and nom not in (".", "..")
    )


def detecter(lanceur):
    """(version de systemd ou None, `systemd-creds` présent) : lecture
    seule, par `lanceur(argv, timeout)`.

    Seul le code 127 (commande introuvable) dit `systemd-creds` absent.
    Tout autre échec (délai dépassé, 1, 126…) sur un systemd 250 ou plus
    lève ErreurCredential : le secret serait sinon rangé en clair sur un
    hôte qui sait le chiffrer."""
    version = systemd.version(lanceur)
    code, sortie = lanceur(["systemd-creds", "--version"], 30)
    if code == 0:
        return version, True
    if code == 127 or version is None or version < VERSION_CHIFFREE:
        return version, False
    raise ErreurCredential(
        N_(
            "systemd-creds --version failed (code {code}): {output}. Nothing"
            " was written."
        ),
        code=code,
        output=(sortie or "").strip()[:300],
    )


def choisir_stockage(version, avec_creds):
    """Le `Stockage` des credentials pour `version` (entier ou None) et la
    présence de `systemd-creds`. Lève ErreurCredential avant 247 ou sur une
    version inconnue."""
    if version is None:
        raise ErreurCredential(
            N_(
                "systemd version unknown: credentials need LoadCredential="
                " (systemd 247). Nothing was written."
            )
        )
    if version < VERSION_MINIMALE:
        raise ErreurCredential(
            N_(
                "systemd {version} has no credentials (LoadCredential= needs"
                " 247). Nothing was written."
            ),
            version=version,
        )
    if version >= VERSION_CHIFFREE and avec_creds:
        return Stockage(
            True, version, DOSSIER_CHIFFRE, "LoadCredentialEncrypted"
        )
    return Stockage(False, version, DOSSIER_CLAIR, "LoadCredential")


def stockage_cite(directive, version):
    """Le `Stockage` d'une ligne `directive=` d'une unité déjà écrite :
    `LoadCredentialEncrypted` dans le dossier chiffré, `LoadCredential`
    dans le dossier en clair."""
    chiffre = directive == "LoadCredentialEncrypted"
    return Stockage(
        chiffre,
        version,
        DOSSIER_CHIFFRE if chiffre else DOSSIER_CLAIR,
        directive,
    )


def chemin(stockage, unite, nom):
    """Le fichier du credential `nom` de l'unité :
    `<dossier>/<unité>.<nom>`."""
    return os.path.join(stockage.dossier, f"{unite}.{nom}")


def ligne_unite(stockage, unite, nom):
    """La ligne `LoadCredential*=NOM:CHEMIN` de l'unité."""
    return f"{stockage.directive}={nom}:{chemin(stockage, unite, nom)}"


def lignes_citees(texte):
    """[(directive, nom, chemin)] des lignes `LoadCredential*=` de
    `texte`."""
    return [m.groups() for m in RE_LIGNE.finditer(texte or "")]


def chemins_a_retirer(texte, unite):
    """Les fichiers de credential que cite le texte d'unité `texte` et qui
    appartiennent à `unite` : directement sous `/etc/credstore` ou
    `/etc/credstore.encrypted`, nom commençant par `<unité>.`. Un chemin
    qui sort de ces dossiers, ou qui nomme une autre unité, n'est jamais
    rendu."""
    trouves = []
    for _directive, _nom, cite in lignes_citees(texte):
        if os.path.normpath(cite) != cite:
            continue
        if os.path.dirname(cite) not in DOSSIERS:
            continue
        base = os.path.basename(cite)
        if not base.startswith(unite + ".") or base == unite + ".":
            continue
        if cite not in trouves:
            trouves.append(cite)
    return trouves


def fichiers_de_l_unite(unite, noms):
    """Les chemins `<dossier>/<unité>.<nom>` des deux dossiers, pour chaque
    nom valide de `noms` : ceux qu'un déployeur a pu écrire pour l'unité,
    même si aucune unité ne les cite plus. Un nom exact, jamais un
    préfixe : une autre base dont le nom prolonge celui-ci n'est pas
    touchée."""
    return [
        os.path.join(dossier, f"{unite}.{nom}")
        for dossier in DOSSIERS
        for nom in noms
        if nom_valide(nom)
    ]


def prefixe_provisoire(reel):
    """Le préfixe des fichiers et dossiers temporaires écrits à côté de
    `reel` : `.<nom du fichier>~`. « ~ » n'entre ni dans un nom d'unité ni
    dans un nom de credential : un reste se rattache à son seul fichier."""
    return "." + os.path.basename(reel) + "~"


def restes(reel_dossier, bases):
    """Les entrées temporaires (`prefixe_provisoire`) que laisse dans
    `reel_dossier` une écriture interrompue (SIGKILL, coupure) d'un des
    fichiers `bases` (noms de fichier). [] si le dossier ne se lit pas."""
    try:
        entrees = sorted(os.listdir(reel_dossier))
    except OSError:
        return []
    voulus = {"." + base for base in bases}
    return [
        os.path.join(reel_dossier, entree)
        for entree in entrees
        if "~" in entree and entree.partition("~")[0] in voulus
    ]


def present(reel):
    """True si `reel` existe (lien compris), False s'il n'existe pas, None
    si on ne peut pas le savoir : un compte autre que root ne traverse pas
    `/etc/credstore*` (0700) et y voit EACCES."""
    try:
        os.lstat(reel)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return None
    return True


def lire_secret(source):
    """Les octets du secret du fichier `source` : sans suivre de lien,
    fichier régulier, non vide, `TAILLE_MAX` octets au plus. Lève
    ErreurCredential, sans jamais citer le contenu. `O_NONBLOCK` : un tube
    nommé s'ouvre sans attendre d'écrivain, puis se voit refusé comme tout
    ce qui n'est pas un fichier régulier ; la lecture d'un fichier régulier
    n'en dépend pas."""
    try:
        fd = os.open(
            source,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
        )
    except OSError as err:
        if os.path.islink(source):
            raise ErreurCredential(
                N_("{path}: symbolic link refused"), path=source
            )
        raise ErreurCredential(
            N_("{path}: cannot read: {error}"),
            path=source,
            error=err.strerror,
        )
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ErreurCredential(
                N_("{path}: not a regular file"), path=source
            )
        morceaux = []
        taille = 0
        while taille <= TAILLE_MAX:
            bloc = os.read(fd, 65536)
            if not bloc:
                break
            morceaux.append(bloc)
            taille += len(bloc)
    finally:
        os.close(fd)
    if taille > TAILLE_MAX:
        raise ErreurCredential(
            N_("{path}: larger than {size} KiB"),
            path=source,
            size=TAILLE_MAX // 1024,
        )
    donnees = b"".join(morceaux)
    if not donnees.strip():
        raise ErreurCredential(N_("{path}: empty"), path=source)
    return donnees


def preparer_dossier(reel):
    """Crée le dossier `reel` en 0700 (parents en 0755) ; un dossier
    existant doit être fermé au groupe et aux autres. Lève
    ErreurCredential sur un lien, un non-dossier ou un dossier ouvert."""
    if os.path.islink(reel):
        raise ErreurCredential(N_("{path}: symbolic link refused"), path=reel)
    if os.path.lexists(reel):
        info = os.stat(reel)
        if not stat.S_ISDIR(info.st_mode):
            raise ErreurCredential(N_("{path} is not a directory."), path=reel)
        if info.st_mode & 0o077:
            raise ErreurCredential(
                N_(
                    "{path} is open to other accounts: chmod 700 it before"
                    " storing a secret there."
                ),
                path=reel,
            )
        return
    parent = os.path.dirname(reel)
    if not os.path.isdir(parent):
        os.makedirs(parent, 0o755)
    os.mkdir(reel, MODE_DOSSIER)
    os.chmod(reel, MODE_DOSSIER)


def ecrire_clair(reel, donnees):
    """Écrit `donnees` dans `reel` (0600) par fichier temporaire du même
    dossier puis renommage : le fichier n'est jamais lu à moitié écrit ni
    ouvert à d'autres comptes."""
    fd, provisoire = tempfile.mkstemp(
        prefix=prefixe_provisoire(reel), dir=os.path.dirname(reel)
    )
    try:
        try:
            os.fchmod(fd, MODE_FICHIER)
            reste = donnees
            while reste:
                reste = reste[os.write(fd, reste) :]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(provisoire, reel)
    except BaseException:
        try:
            os.unlink(provisoire)
        except OSError:
            pass
        raise


def chiffrer(reel, nom, donnees, lanceur_entree):
    """Chiffre `donnees` par `systemd-creds encrypt --name=NOM
    --with-key=host - SORTIE`, le secret sur l'entrée standard
    (`lanceur_entree(argv, donnees, timeout)`), puis place le résultat en
    `reel` (0600). La sortie est écrite dans un dossier temporaire créé DANS
    le dossier de `reel` (0700) : le renommage reste sur le même système de
    fichiers et rien ne passe ailleurs. Lève ErreurCredential si
    `systemd-creds` échoue ; le dossier temporaire est toujours retiré."""
    provisoire = tempfile.mkdtemp(
        prefix=prefixe_provisoire(reel), dir=os.path.dirname(reel)
    )
    try:
        sortie = os.path.join(provisoire, nom)
        code, message = lanceur_entree(
            [
                "systemd-creds",
                "encrypt",
                f"--name={nom}",
                "--with-key=host",
                "-",
                sortie,
            ],
            donnees,
            60,
        )
        if code != 0 or not os.path.isfile(sortie):
            raise ErreurCredential(
                N_("systemd-creds encrypt failed (code {code}): {output}"),
                code=code,
                output=(message or "").strip()[:300],
            )
        os.chmod(sortie, MODE_FICHIER)
        os.replace(sortie, reel)
    finally:
        shutil.rmtree(provisoire, ignore_errors=True)


def disponible(nom, environ=None):
    """Le fichier du credential `nom` que systemd a remis à l'unité
    (`$CREDENTIALS_DIRECTORY/<nom>`, fichier régulier), ou None. Hors
    d'une unité, la variable est absente."""
    environ = os.environ if environ is None else environ
    dossier = environ.get(VARIABLE, "")
    if not dossier or not nom_valide(nom):
        return None
    candidat = os.path.join(dossier, nom)
    try:
        info = os.lstat(candidat)
    except OSError:
        return None
    return candidat if stat.S_ISREG(info.st_mode) else None


def fichier(nom, valeur_option, valeur_profil, environ=None):
    """(chemin, origine) du fichier du secret `nom`, dans cet ordre : le
    credential de l'unité (`"systemd"`), qui passe avant la ligne de
    commande ; l'option (`"cli"`) ; un chemin du profil (`"profil"`) ; sinon
    `(None, None)`. Une référence KeePass du profil n'est jamais lue ici."""
    credential = disponible(nom, environ)
    if credential:
        return credential, "systemd"
    if valeur_option:
        return valeur_option, "cli"
    if isinstance(valeur_profil, str) and valeur_profil:
        return valeur_profil, "profil"
    return None, None
