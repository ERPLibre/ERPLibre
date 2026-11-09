#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le sceau PAdES de sign_oca_pades : un certificat auto-signé, pour essai.

Le module scelle chaque document signé avec un fichier PKCS#12 (`.p12`) qui
réunit la clé privée et son certificat. Ce menu produit ce fichier et le
certificat seul (`.crt`), à distribuer à qui vérifie les sceaux.

La clé n'est jamais écrite en clair : `openssl req` la chiffre avec le mot de
passe du `.p12`, `openssl pkcs12` la relit pour l'exporter, puis elle est
effacée. Le mot de passe passe par l'environnement du sous-processus, jamais
en argument, où `ps` le montrerait.

Le dossier ne doit pas pouvoir être commité. `private/` ne suffit pas : il est
versionné, sur un dépôt privé. `private/sceau/` est ignoré par `.gitignore`,
et `chemin_commitable` interroge le dépôt qui CONTIENT le dossier : un dossier
dans un dépôt d'addons est ignoré par la racine, mais pas par son propre
dépôt.
"""

import getpass
import os
import shutil
import subprocess
import tempfile

from script.todo.todo_i18n import t

RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
DOSSIER_DEFAUT = os.path.join("private", "sceau")
NOM_CRT = "sceau.crt"
NOM_P12 = "sceau.p12"
# La clé chiffrée, le temps de l'export, dans le sous-dossier de travail.
NOM_CLE = "sceau.key"
PREFIXE_TRAVAIL = ".sceau-"
JOURS_DEFAUT = 1095
TAILLE_CLE = 3072
# pyHanko exige la non-répudiation d'un signataire : sans elle, les sceaux
# restent intacts, mais leur vérification les déclare non approuvés.
USAGE_CLE = "keyUsage=critical,digitalSignature,nonRepudiation"
VAR_MDP = "ERPLIBRE_SCEAU_MDP"
# Séparateurs de la syntaxe -subj d'openssl : un nom qui en porte serait
# découpé en d'autres attributs que le CN.
CARACTERES_INTERDITS = "/\\=+,"
# Limite du CN dans X.509 (RFC 5280, ub-common-name).
LONGUEUR_CN_MAX = 64


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


def commandes_openssl(dossier, nom_commun, jours):
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
            "-subj", f"/CN={nom_commun}",
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


def generer_sceau(dossier, nom_commun, jours, mot_de_passe):
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
        for commande in commandes_openssl(travail, nom_commun, jours):
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


class SealMenuMixin:
    def execute_generate_seal(self):
        print(t("Generate a PAdES signature seal"))
        print(
            t(
                "A self-signed certificate seals the documents of a test"
                " database: the seals are intact and valid, but PDF readers"
                " report the signer as untrusted. In production, use a"
                " certificate issued by a recognised authority."
            )
        )
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
            return
        existants = [p for p in (crt, p12) if os.path.exists(p)]
        if existants:
            print(t("A seal already exists here:"))
            for p in existants:
                print(f"\t{p}")
            if not self._is_yes(input(f"💬 {t('Replace it? (y/N): ')}")):
                return

        defaut_cn = t("Document seal (test)")
        nom_commun = (
            input(
                f"💬 {t('Certificate name (default: %s): ') % defaut_cn}"
            ).strip()
            or defaut_cn
        )
        if any(c in nom_commun for c in CARACTERES_INTERDITS):
            print(
                t("The name cannot contain any of these characters: %s")
                % CARACTERES_INTERDITS
            )
            return
        if len(nom_commun) > LONGUEUR_CN_MAX:
            print(t("The name is limited to %s characters.") % LONGUEUR_CN_MAX)
            return
        reponse = input(
            f"💬 {t('Validity in days (default: %s): ') % JOURS_DEFAUT}"
        ).strip()
        # isdecimal et non isdigit : « ² » est un chiffre, que int() refuse.
        if reponse and not (reponse.isdecimal() and int(reponse) > 0):
            print(f"{t('Error, cannot understand value')} '{reponse}'")
            return
        jours = int(reponse or JOURS_DEFAUT)

        # getpass et non input : le mot de passe ne doit rester ni à
        # l'écran ni dans l'historique du terminal.
        mot_de_passe = getpass.getpass(t("Password of the .p12 file: "))
        if not mot_de_passe:
            print(t("The password cannot be empty."))
            return
        if mot_de_passe != getpass.getpass(t("Password again: ")):
            print(t("The two passwords differ."))
            return

        try:
            crt, p12 = generer_sceau(dossier, nom_commun, jours, mot_de_passe)
        except subprocess.CalledProcessError as erreur:
            print(f"❌ {t('openssl failed:')} {erreur}")
            if erreur.stderr:
                print(erreur.stderr.decode(errors="replace").strip())
            return
        except OSError as erreur:
            print(f"❌ {t('Cannot write the seal:')} {erreur}")
            return
        if not a_la_non_repudiation(crt):
            print(
                f"⚠️ {t('The certificate lacks the non repudiation key usage: pyHanko will report its seals as untrusted.')}"
            )
        print(f"✅ {t('Seal written:')}")
        print(f"\t{p12}")
        print(f"\t{crt}")
        print(
            t(
                "Next: Sign › Settings › General settings, Document Sealing"
                " (PAdES) section, upload the .p12 with its password. Or, in"
                " odoo.conf [options]: sign_oca_pades_pkcs12_path and"
                " sign_oca_pades_pkcs12_password, then restart Odoo."
            )
        )
