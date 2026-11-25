#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les réglages de production vus depuis todo : le profil d'une instance.

Le profil (`private/production/<service>.json`, voir `lib_ops/profil.py`)
porte, pour chaque outil de production, les valeurs qu'il recevrait sur sa
ligne de commande. Ce mixin et ses fonctions de module servent le menu
Production :

- l'instance visée, mémorisée dans `todo_prefs["ops_service"]` sous la
  racine du checkout : `~/.erplibre/todo_prefs.json` est commun à tous les
  checkouts d'un compte ;
- l'éditeur ligne par ligne (groupes, champs d'un groupe, un champ) et le
  formulaire Textual (`ops_settings_form.py`), qui partagent la logique
  pure d'ici : `lignes_reglages`, `convertir_saisie`, `diff`, `Brouillon` ;
- l'enregistrement : différences, vérification par les outils de ce
  checkout sur une copie, aperçu de rétention, unités qui citent le
  profil, coffre, écriture atomique, proposition de réinstallation ;
- l'affichage, la vérification et la suppression d'un profil ;
- les secrets : rangés dans KeePass (`SecretStore` sans trousseau), passés
  à un lancement manuel par un fichier 0600 d'un tmpfs, retiré dans tous
  les cas (`fichiers_secrets`) ;
- la construction d'une commande (`commande`) : todo ne développe pas le
  profil, il passe `--service` et `--profile` et l'outil l'applique ;
- `ask_ui(pref_key)`, la question « formulaire ou invites » que se
  partagent le déploiement QEMU, la migration et les réglages.

Aucun secret ne passe sur argv, dans le profil, dans un message ou dans
le formulaire : seuls un chemin absolu ou une référence KeePass circulent.
"""

import atexit
import collections
import contextlib
import copy
import functools
import getpass
import importlib
import io
import os
import re
import stat
import sys
import tempfile

import click

from script.lib_ops import profil, systemd
from script.todo import todo_prefs
from script.todo.system_menu import affichable, entier
from script.todo.todo_i18n import t

# Le checkout de todo : celui dont `private/production` reçoit les profils.
RACINE = profil.RACINE

PREF_SERVICE = "ops_service"
PREF_UI = "ops_settings_ui"

GROUPE_HOTE = profil.GROUPE_HOTE

# Préfixe des dossiers temporaires de secrets, suivi du PID du todo qui
# les crée (`erplibre-secret-<pid>-…`) : la purge les reconnaît et épargne
# ceux d'une session encore vivante.
PREFIXE_SECRET = "erplibre-secret-"
# Le tmpfs de repli quand `$XDG_RUNTIME_DIR` manque.
DEV_SHM = "/dev/shm"

# Le groupe KeePass des secrets de production :
# `<CHEMIN_KDBX>/<service>/<nom du secret>`.
CHEMIN_KDBX = "ERPLibre/Production"


def N_(texte):
    """Marque un texte à traduire plus tard par `t`."""
    return texte


# Aides des champs de l'audit, traduites à l'affichage : l'audit est un
# fichier unique, lancé aussi à distance, et ses aides restent en anglais.
AIDES_AUDIT = {
    "duration": N_(
        "Length of the measurement: 90 (seconds), 30s, 10m, 2h, 1h30m;"
        " 1 second to 7 days."
    ),
    "interval": N_(
        "Seconds between two samples; default 5, raised so that the number"
        " of samples stays bounded."
    ),
    "no_guests": N_("Do not measure each container and VM."),
    "top": N_(
        "Number of guests shown in the text report, busiest on the disks"
        " first."
    ),
    "verbose": N_("Show each external command run."),
}

# Notes ajoutées à l'aide d'un champ dont l'effet diffère de ce que son nom
# laisse attendre.
NOTES = {
    ("update_module", "warmup_deep"): N_(
        "Anonymous warm-up with the default settings: the Deep warm-up"
        " group does not apply to it."
    ),
}

# Champs dont l'outil détecte la valeur quand le profil n'en donne pas.
DETECTES = frozenset(
    [
        (profil.GROUPE_INSTANCE, "db"),
        ("update_module", "log_dir"),
        ("log_check", "namespace"),
        ("odoo_conf", "cpus"),
        ("odoo_conf", "memory_mb"),
        (GROUPE_HOTE, "interval"),
    ]
)


def nom_groupe(groupe):
    """Le nom affiché d'un groupe du profil."""
    noms = {
        profil.GROUPE_INSTANCE: t("Instance - shared by every tool"),
        "update_module": t("Update"),
        "backup": t("Verified backups"),
        "backup_timer": t("Backup timer"),
        "log_check": t("Odoo journal"),
        "mail_retry": t("Outgoing mail"),
        "health_check": t("Health check"),
        "warmup": t("Deep warm-up"),
        "odoo_conf": t("Odoo configuration check"),
        GROUPE_HOTE: t("Host audit"),
    }
    return noms.get(groupe, groupe)


# --- Interface : formulaire ou invites -------------------------------------


def ask_ui(pref_key, extras=(), annuler=False, demander=None):
    """L'interface choisie pour un écran : "tui", "cli", la valeur d'un
    choix de `extras`, ou None (annulation).

    La préférence `pref_key` tranche d'avance quand elle vaut "tui" ou
    "cli" ; "ask", une valeur inconnue ou une préférence illisible posent
    la question : [1] formulaire (défaut), [2] invites, puis un numéro par
    `(valeur, libellé)` de `extras` à partir de 3, et [0] avec `annuler`.
    `demander(question)` lit la réponse (`input` par défaut)."""
    try:
        pref = todo_prefs.get(pref_key)
    except Exception:
        pref = "ask"
    if pref in ("tui", "cli"):
        return pref
    print(f"\n{t('Interface:')}")
    print(f"  [1] {t('TUI form')} *")
    print(f"  [2] {t('Classic questions (line by line)')}")
    choix = {"2": "cli"}
    for numero, (valeur, libelle) in enumerate(extras, 3):
        print(f"  [{numero}] {libelle}")
        choix[str(numero)] = valeur
    if annuler:
        print(f"  [0] {t('Cancel')}")
        choix["0"] = None
    print(f"  {t('(change the default in TODO > Configuration)')}")
    question = t("Choice ({first}-{last}, default 1): ").format(
        first=0 if annuler else 1, last=2 + len(extras)
    )
    reponse = (demander or input)(question).strip()
    return choix.get(reponse, "tui")


# --- Catalogue --------------------------------------------------------------

Catalogue = collections.namedtuple("Catalogue", "champs alias parseurs")

Ligne = collections.namedtuple(
    "Ligne", "groupe champ valeur origine defaut portee"
)


def script_de(outil):
    """Le chemin du programme d'un `profil.Outil`, relatif à la racine du
    dépôt (le dossier courant de todo)."""
    return os.path.join(*outil.module.split(".")) + ".py"


def construire_parseurs(groupes=None):
    """{groupe: parser} des outils de `profil.OUTILS` (tous, ou ceux de
    `groupes`), par leur `construire_parseur()` : les aides sont dans la
    langue courante, et rien n'est lancé."""
    parseurs = collections.OrderedDict()
    for outil in profil.OUTILS:
        if groupes is not None and outil.groupe not in groupes:
            continue
        module = importlib.import_module(outil.module)
        parseurs[outil.groupe] = module.construire_parseur()
    return parseurs


def charger_catalogue(hote=False):
    """Le `Catalogue` du profil d'une instance, ou du profil d'hôte avec
    `hote` : `champs` ({groupe: [Champ]}), `alias` ({groupe: [Champ]},
    `groupe`/`cle` y nomment la cible) et `parseurs`."""
    if hote:
        groupes = (GROUPE_HOTE,)
    else:
        groupes = tuple(
            o.groupe for o in profil.OUTILS if o.groupe != GROUPE_HOTE
        )
    parseurs = construire_parseurs(groupes)
    champs = profil.catalogue(parseurs)
    alias = collections.OrderedDict(
        (groupe, profil.alias(parser, groupe))
        for groupe, parser in parseurs.items()
    )
    return Catalogue(champs, alias, parseurs)


def champ_cible(catalogue, groupe, cle):
    """Le `Champ` F `groupe.cle` du catalogue, ou None."""
    for champ in catalogue.champs.get(groupe, ()):
        if champ.cle == cle:
            return champ
    return None


def formater(brut):
    """Une valeur brute du profil, lisible et sans caractère de contrôle :
    « — » pour une absence, oui/non, les éléments d'une liste séparés par
    des virgules, la référence d'un secret rangé dans KeePass."""
    if brut is None:
        return "—"
    if isinstance(brut, bool):
        return t("yes") if brut else t("no")
    if isinstance(brut, dict) and "kdbx" in brut:
        return t("KeePass: {reference}").format(
            reference=affichable(brut["kdbx"])
        )
    if isinstance(brut, (list, tuple)):
        return ", ".join(affichable(element) for element in brut)
    return affichable(brut)


def defaut_affiche(champ):
    """Le défaut de l'outil pour `champ`, à afficher : « (détecté) » ou
    « (aucun) » quand l'outil n'en a pas."""
    defaut = champ.defaut
    if champ.genre in ("bool_vrai", "bool_faux"):
        return t("no")
    if defaut is None or defaut == []:
        if (champ.groupe, champ.cle) in DETECTES:
            return t("(detected)")
        return t("(none)")
    if isinstance(defaut, (list, tuple)):
        return ",".join(affichable(element) for element in defaut)
    return affichable(defaut)


def aide(champ):
    """L'aide d'un champ : celle de l'outil, traduite par lui, ou
    `AIDES_AUDIT` pour l'audit ; plus sa note éventuelle."""
    if champ.groupe == GROUPE_HOTE:
        texte = t(AIDES_AUDIT[champ.cle]) if champ.cle in AIDES_AUDIT else ""
    else:
        texte = champ.aide or ""
    note = NOTES.get((champ.groupe, champ.cle))
    if note:
        texte = f"{texte} {t(note)}".strip()
    return texte


def lignes_reglages(catalogue, doc):
    """Une `Ligne` par champ du catalogue, dans son ordre : `(groupe,
    Champ, valeur brute ou None, origine "profil" ou "defaut", défaut
    affiché, portée)`."""
    lignes = []
    for groupe, champs in catalogue.champs.items():
        valeurs = doc.get(groupe) or {}
        for champ in champs:
            present = champ.cle in valeurs
            lignes.append(
                Ligne(
                    groupe,
                    champ,
                    valeurs.get(champ.cle),
                    "profil" if present else "defaut",
                    defaut_affiche(champ),
                    champ.portee,
                )
            )
    return lignes


def nombre_valeurs(doc):
    """Le nombre de valeurs posées dans les groupes du profil `doc`."""
    return sum(
        len(valeurs)
        for groupe, valeurs in (doc or {}).items()
        if groupe in profil.CHAMPS and isinstance(valeurs, dict)
    )


# --- Saisie et validation ---------------------------------------------------


def _cle(champ):
    return f"{champ.groupe}.{champ.cle}"


def convertir_saisie(champ, texte):
    """La valeur brute du profil pour la saisie `texte` d'un champ à
    valeur, contrôlée par `profil.convertir`.

    Un résultat numérique exige une saisie ASCII : `int()` et `float()`
    acceptent « ٣ », et une valeur que le profil ne relit pas à
    l'identique n'a pas sa place dans un fichier relu par root. Une saisie
    faite de chiffres se garde en nombre JSON, un nombre à virgule aussi ;
    une durée comme « 10m » se garde telle quelle, comme la ligne de
    commande la recevrait. Lève ErreurProfil."""
    texte = texte.strip()
    converti = profil.convertir(champ, texte)
    numerique = isinstance(converti, (int, float)) and not isinstance(
        converti, bool
    )
    if not numerique:
        return texte
    if not texte.isascii():
        raise profil.ErreurProfil(
            N_("expected a number written with the digits 0 to 9"),
            _cle(champ),
        )
    nombre = entier(texte)
    if nombre is not None:
        return nombre
    if isinstance(converti, float):
        try:
            return float(texte)
        except ValueError:
            return texte
    return texte


def defauts_du_groupe(catalogue, groupe):
    """{clé: défaut de l'outil} des champs du groupe."""
    return {c.cle: c.defaut for c in catalogue.champs.get(groupe, ())}


def verifier_document(catalogue, doc):
    """{`groupe.cle`: message traduit} des valeurs du profil `doc` que
    `profil.convertir` ou la somme des rétentions refusent ; vide quand
    tout passe."""
    erreurs = collections.OrderedDict()
    for groupe, champs in catalogue.champs.items():
        valeurs = doc.get(groupe) or {}
        for champ in champs:
            if champ.cle not in valeurs:
                continue
            try:
                profil.convertir(champ, valeurs[champ.cle])
            except profil.ErreurProfil as err:
                erreurs[_cle(champ)] = err.message(t)
    groupe, cles, _minimum = profil.BORNE_SOMME
    if groupe in catalogue.champs:
        try:
            profil.verifier_somme(
                doc.get(groupe) or {}, defauts_du_groupe(catalogue, groupe)
            )
        except profil.ErreurProfil as err:
            erreurs[err.cle or groupe] = err.message(t)
    return erreurs


def diff(avant, apres):
    """[(groupe, cle, ancienne valeur, nouvelle valeur)] des valeurs qui
    changent entre les profils `avant` et `apres`, dans l'ordre du
    catalogue ; None vaut « absente »."""
    changements = []
    for groupe, cles in profil.CHAMPS.items():
        anciennes = avant.get(groupe) or {}
        nouvelles = apres.get(groupe) or {}
        for cle in cles:
            ancienne = anciennes.get(cle)
            nouvelle = nouvelles.get(cle)
            if ancienne != nouvelle:
                changements.append((groupe, cle, ancienne, nouvelle))
    return changements


def reference_secret(service, nom):
    """Le chemin KeePass d'un secret :
    `ERPLibre/Production/<service>/<nom>`."""
    return f"{CHEMIN_KDBX}/{service}/{nom}"


def ref_coffre(reference):
    """La référence `SecretStore` d'un chemin KeePass."""
    return "kdbx:" + reference


def references_kdbx(doc):
    """L'ensemble des chemins KeePass que les champs secrets de `doc`
    citent (`{"kdbx": chemin}`)."""
    citees = set()
    for groupe, cle in profil.SECRETS:
        brut = (doc.get(groupe) or {}).get(cle)
        if isinstance(brut, dict) and brut.get("kdbx"):
            citees.add(brut["kdbx"])
    return citees


class Brouillon:
    """Un profil en cours d'édition, écrit seulement à l'enregistrement.

    `doc` est la copie modifiée, `avant` le document lu, `empreinte` son
    sha256 ("" pour un fichier absent) : le verrou optimiste de
    `profil.ecrire`. `secrets_a_definir` ({chemin KeePass: valeur}) et
    `secrets_a_retirer` (chemins KeePass) attendent l'enregistrement ; la
    valeur d'un secret ne va jamais dans `doc`. `ignorees` nomme les clés
    inconnues lues, que l'enregistrement retire."""

    def __init__(self, chemin, doc, empreinte, catalogue, nom):
        self.chemin = chemin
        self.avant = copy.deepcopy(doc)
        self.doc = copy.deepcopy(doc)
        self.empreinte = empreinte
        self.catalogue = catalogue
        self.nom = nom
        self.secrets_a_definir = collections.OrderedDict()
        self.secrets_a_retirer = set()
        self.ignorees = []

    @classmethod
    def ouvrir(cls, chemin, catalogue, service=None, hote=None):
        """Le brouillon du profil `chemin` : un service (`service`) ou un
        hôte (`hote`). Un fichier absent donne un profil vide. Les groupes
        et clés inconnus sont retirés du brouillon et nommés dans
        `ignorees`. Lève ErreurProfil sur un fichier refusé."""
        if os.path.lexists(chemin):
            lu = profil.lire(chemin)
            profil.valider_document(lu.doc, chemin, hote=hote is not None)
            doc, empreinte = lu.doc, lu.empreinte
        else:
            doc = {"version": profil.VERSION}
            if hote is not None:
                doc["host"] = hote
            else:
                doc["service"] = service
            empreinte = ""
        brouillon = cls(chemin, {}, empreinte, catalogue, service or hote)
        propre = {}
        for nom, valeur in doc.items():
            if nom in profil.CLES_DOCUMENT:
                propre[nom] = valeur
            elif nom not in catalogue.champs or not isinstance(valeur, dict):
                brouillon.ignorees.append(nom)
            else:
                propre[nom] = {}
                for cle, brut in valeur.items():
                    if cle in profil.CHAMPS[nom]:
                        propre[nom][cle] = brut
                    else:
                        brouillon.ignorees.append(f"{nom}.{cle}")
                if not propre[nom]:
                    del propre[nom]
        brouillon.avant = copy.deepcopy(doc)
        brouillon.doc = propre
        return brouillon

    def valeur(self, champ):
        """La valeur brute du profil pour `champ`, ou None."""
        return (self.doc.get(champ.groupe) or {}).get(champ.cle)

    def effectif(self, champ):
        """Pour un booléen : vrai si l'option est passée à chaque
        lancement par le profil."""
        return bool(self.valeur(champ))

    def definir(self, champ, brut):
        """Pose `brut` pour `champ` après contrôle par `profil.convertir`
        et, pour une rétention, par la somme des `keep_*`. Lève
        ErreurProfil sans rien changer."""
        profil.convertir(champ, brut)
        groupe = self.doc.get(champ.groupe) or {}
        essai = dict(groupe)
        essai[champ.cle] = brut
        somme, cles, _minimum = profil.BORNE_SOMME
        if champ.groupe == somme and champ.cle in cles:
            profil.verifier_somme(
                essai, defauts_du_groupe(self.catalogue, somme)
            )
        self.doc[champ.groupe] = essai

    def definir_saisie(self, champ, texte):
        """Pose la saisie `texte` d'un champ à valeur (`convertir_saisie`).
        Lève ErreurProfil."""
        self.definir(champ, convertir_saisie(champ, texte))

    def retirer(self, champ):
        """Retire la valeur de `champ` : l'outil reprend son défaut."""
        groupe = self.doc.get(champ.groupe)
        if groupe is None:
            return
        groupe.pop(champ.cle, None)
        if not groupe:
            del self.doc[champ.groupe]

    def differences(self):
        """`diff` entre le document lu et le brouillon."""
        return diff(self.avant, self.doc)

    def modifie(self):
        """Vrai s'il reste un changement à enregistrer."""
        return bool(
            self.differences()
            or self.ignorees
            or self.secrets_a_definir
            or self.secrets_a_retirer
        )

    def enregistre(self, empreinte):
        """Le brouillon devient le document lu, d'empreinte `empreinte` ;
        les valeurs de secrets saisies sont oubliées."""
        self.avant = copy.deepcopy(self.doc)
        self.empreinte = empreinte
        self.secrets_a_definir.clear()
        self.secrets_a_retirer.clear()
        self.ignorees = []


# --- Vérification par les outils de ce checkout ----------------------------

Echec = collections.namedtuple("Echec", "groupe code message")


def presents_de(parser, argv):
    """Les `dest` que `argv` donne explicitement à `parser` (options
    longues ou courtes, `--opt=val`) ; rien après `--`."""
    presents = set()
    for argument in argv:
        if argument == "--":
            break
        if not argument.startswith("-"):
            continue
        nom = argument.split("=", 1)[0]
        action = parser._option_string_actions.get(nom)
        if action is not None:
            presents.add(action.dest)
    return frozenset(presents)


def verifier(chemin, service=None, hote=False):
    """Fait lire le profil `chemin` par l'entrée de chaque outil de ce
    checkout, en processus, sans lanceur : `argv_minimal`, `--service`
    quand l'outil vise une unité, puis `--profile`. Avec `hote`, seul
    l'audit lit le profil d'hôte. Rend les `Echec` des outils qui
    refusent (code non nul), avec ce qu'ils ont écrit."""
    echecs = []
    for outil in profil.OUTILS:
        if (outil.groupe == GROUPE_HOTE) != hote:
            continue
        module = importlib.import_module(outil.module)
        argv = list(outil.argv_minimal)
        if not hote and service:
            parser = module.construire_parseur()
            if outil.avec_service(presents_de(parser, argv)):
                argv += ["--service", service]
        argv += ["--profile", chemin]
        sortie = io.StringIO()
        code = 0
        with (
            contextlib.redirect_stdout(sortie),
            contextlib.redirect_stderr(sortie),
        ):
            try:
                getattr(module, outil.entree)(argv)
            except SystemExit as fin:
                code = fin.code if isinstance(fin.code, int) else 2
            except Exception as err:
                code = 1
                print(f"{type(err).__name__}: {err}")
        if code:
            echecs.append(
                Echec(
                    outil.groupe, code, affichable(sortie.getvalue().strip())
                )
            )
    return echecs


def verifier_brouillon(brouillon, hote=False):
    """`verifier` sur une copie du brouillon écrite dans un dossier
    temporaire, sous le nom que `profil.valider_document` exige. Un
    brouillon que `profil.ecrire` refuse donne un `Echec` du groupe
    `profile`."""
    with tempfile.TemporaryDirectory(prefix="erplibre-profil-") as dossier:
        chemin = os.path.join(dossier, os.path.basename(brouillon.chemin))
        try:
            profil.ecrire(chemin, brouillon.doc)
        except profil.ErreurProfil as err:
            message = err.message(t)
            if err.cle:
                message = f"{err.cle}: {message}"
            return [Echec("profile", 2, message)]
        return verifier(chemin, service=brouillon.nom, hote=hote)


# --- Commandes --------------------------------------------------------------


def commande(groupe, args_lancement, service, chemin_profil, parser=None):
    """`[python, programme] + [--service S] + [--profile ABS] + args`.

    `--service` n'est ajouté que si l'outil, avec les options de
    `args_lancement`, vise une unité (`Outil.avec_service`) : jamais pour
    la santé ou le préchauffage sans `--local`, ni pour l'audit.
    `--profile` ne l'est que si le fichier existe. Le profil n'est pas
    développé : l'outil l'applique lui-même."""
    outil = profil.outil(groupe)
    if parser is None:
        parser = construire_parseurs((groupe,))[groupe]
    argv = [sys.executable, script_de(outil)]
    if service and outil.avec_service(presents_de(parser, args_lancement)):
        argv += ["--service", service]
    if chemin_profil and os.path.isfile(chemin_profil):
        argv += ["--profile", os.path.abspath(chemin_profil)]
    return argv + list(args_lancement)


def valeur_du_groupe(doc, groupe, dest):
    """La valeur brute que l'outil `groupe` lirait du profil `doc` pour sa
    `dest`, alias compris ; None si le profil n'en donne pas."""
    cible = profil.ALIAS.get(groupe, {}).get(dest, (groupe, dest))
    return ((doc or {}).get(cible[0]) or {}).get(cible[1])


def resume_profil(doc, groupe, parser):
    """« --keep-daily 10, --copy-to … » : les valeurs que l'outil `groupe`
    lirait du profil `doc`, alias compris, affichables ; "" sans
    valeur."""
    morceaux = []
    for champ in profil.champs(parser, groupe) + profil.alias(parser, groupe):
        brut = ((doc or {}).get(champ.groupe) or {}).get(champ.cle)
        if brut is None:
            continue
        option = profil.option(champ.action)
        if brut is True:
            morceaux.append(option)
        elif brut is not False:
            morceaux.append(f"{option} {formater(brut)}")
    return ", ".join(morceaux)


def argv_audit(doc_hote, duree=None):
    """L'argv explicite de l'audit tiré d'un profil d'hôte : chaque valeur
    est validée par le parser de l'audit et rendue sous sa forme
    convertie (secondes, nombre, drapeau), pour un hôte distant qui n'a
    pas le fichier. `duree` (secondes) remplace la durée du profil. Lève
    ErreurProfil sur une valeur refusée."""
    parser = construire_parseurs((GROUPE_HOTE,))[GROUPE_HOTE]
    valeurs = dict((doc_hote or {}).get(GROUPE_HOTE) or {})
    if duree is not None:
        valeurs["duration"] = duree
    argv = []
    for champ in profil.champs(parser, GROUPE_HOTE):
        if champ.cle not in valeurs:
            continue
        converti = profil.convertir(champ, valeurs[champ.cle])
        if champ.genre in ("bool_vrai", "bool_faux"):
            if valeurs[champ.cle]:
                argv.append(champ.option)
            continue
        argv += [champ.option, str(converti)]
    return argv


# --- Secrets ----------------------------------------------------------------


class SecretsFournis:
    """Ce que `fichiers_secrets` a préparé : `argv` (chemins seulement),
    `manquants` (noms des secrets non résolus), `simules` (noms des
    secrets laissés de côté en simulation), `abandon` (posé par
    l'appelant qui renonce au geste)."""

    def __init__(self):
        self.argv = []
        self.manquants = []
        self.simules = []
        self.abandon = False


def dossier_tmpfs(environ=None):
    """Le dossier où créer un fichier de secret : `$XDG_RUNTIME_DIR` s'il
    existe et s'écrit, sinon `/dev/shm` ; None sans l'un ni l'autre."""
    environ = os.environ if environ is None else environ
    for dossier in (environ.get("XDG_RUNTIME_DIR") or "", DEV_SHM):
        if dossier and os.path.isdir(dossier) and os.access(dossier, os.W_OK):
            return dossier
    return None


def _nettoyer(dossier):
    """Retire les fichiers de `dossier` puis le dossier ; sans effet s'il
    n'existe plus. Ne suit aucun lien."""
    try:
        noms = os.listdir(dossier)
    except OSError:
        return
    for nom in noms:
        try:
            os.unlink(os.path.join(dossier, nom))
        except OSError:
            pass
    try:
        os.rmdir(dossier)
    except OSError:
        pass


def _session_vivante(nom):
    """Vrai si le dossier de secrets `nom` appartient à un processus encore
    vivant : PID lu après `PREFIXE_SECRET`. Un nom sans PID est un reste."""
    pid = entier(nom[len(PREFIXE_SECRET) :].partition("-")[0])
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        # Le PID existe sous un autre compte : rien ne prouve qu'il est
        # libre, le dossier reste.
        return True
    return True


def purger_secrets_restants(environ=None):
    """Retire les dossiers `erplibre-secret-*` de ce compte restés dans
    `$XDG_RUNTIME_DIR` et `/dev/shm` (un todo tué avant son nettoyage).
    Le dossier d'un todo encore vivant, un autre onglet par exemple, est
    épargné : un geste en cours y lit son secret. Rend leur nombre ;
    silencieux."""
    environ = os.environ if environ is None else environ
    retires = 0
    for base in (environ.get("XDG_RUNTIME_DIR") or "", DEV_SHM):
        if not base or not os.path.isdir(base):
            continue
        try:
            noms = os.listdir(base)
        except OSError:
            continue
        for nom in noms:
            if not nom.startswith(PREFIXE_SECRET) or _session_vivante(nom):
                continue
            chemin = os.path.join(base, nom)
            try:
                info = os.lstat(chemin)
            except OSError:
                continue
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                continue
            _nettoyer(chemin)
            retires += 1
    return retires


def options_secretes(groupe):
    """{clé: option} des champs secrets du groupe."""
    cles = [cle for (g, cle) in profil.SECRETS if g == groupe]
    if not cles:
        return {}
    parser = construire_parseurs((groupe,))[groupe]
    return {
        champ.cle: champ.option
        for champ in profil.champs(parser, groupe)
        if champ.cle in cles
    }


def _sur_la_ligne(option, argv):
    return any(a == option or a.startswith(option + "=") for a in argv)


@contextlib.contextmanager
def fichiers_secrets(
    doc,
    groupe,
    args_lancement=(),
    coffre=None,
    simulation=False,
    forme="option",
    environ=None,
):
    """Rend un `SecretsFournis` dont `argv` passe à l'outil `groupe` les
    secrets du profil `doc` rangés dans KeePass et absents de
    `args_lancement`.

    Chaque secret est lu par `coffre` (un `SecretStore`, ou une fonction
    qui le rend, appelée seulement s'il y a un secret à lire), écrit dans
    un fichier 0600 (`O_EXCL`, `O_NOFOLLOW`) d'un dossier `mkdtemp` du
    tmpfs de `dossier_tmpfs`, et seul son chemin va sur argv :
    `--api-key-file CHEMIN`, ou `--credential NOM=CHEMIN` avec `forme`
    "credential". Le dossier est retiré à la sortie du bloc, exception et
    Ctrl-C compris, et `atexit` en est le filet. Le bloc englobe toutes
    les tentatives d'un même geste, reprise sous sudo comprise.

    En `simulation`, aucun fichier n'est créé. Sans coffre, sans tmpfs ou
    sans valeur, le secret va dans `manquants` : l'outil écarte alors ses
    dépendants lui-même. Un secret donné par chemin absolu dans le profil
    est lu par l'outil et n'est pas traité ici."""
    fournis = SecretsFournis()
    a_resoudre = []
    valeurs = (doc or {}).get(groupe) or {}
    options = None
    for (groupe_secret, cle), nom in profil.SECRETS.items():
        brut = valeurs.get(cle)
        if groupe_secret != groupe or not isinstance(brut, dict):
            continue
        if options is None:
            options = options_secretes(groupe)
        option = options.get(cle)
        if option is None or _sur_la_ligne(option, args_lancement):
            continue
        a_resoudre.append((nom, option, brut.get("kdbx")))
    if not a_resoudre:
        yield fournis
        return
    if simulation:
        fournis.simules = [nom for nom, _option, _ref in a_resoudre]
        yield fournis
        return
    store = coffre() if callable(coffre) else coffre
    lus = []
    for nom, option, reference in a_resoudre:
        valeur = None
        if store is not None and reference:
            try:
                valeur = store.get(ref_coffre(reference))
            except Exception:
                valeur = None
        if valeur:
            lus.append((nom, option, valeur))
        else:
            fournis.manquants.append(nom)
    base = dossier_tmpfs(environ) if lus else None
    if lus and base is None:
        print(f"  ✗ {t('No tmpfs: the secret was not written.')}")
        fournis.manquants += [nom for nom, _option, _valeur in lus]
        lus = []
    if not lus:
        yield fournis
        return
    dossier = tempfile.mkdtemp(
        prefix=f"{PREFIXE_SECRET}{os.getpid()}-", dir=base
    )
    filet = functools.partial(_nettoyer, dossier)
    atexit.register(filet)
    try:
        for nom, option, valeur in lus:
            chemin = os.path.join(dossier, nom)
            fd = os.open(
                chemin,
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY
                | os.O_NOFOLLOW
                | os.O_CLOEXEC,
                0o600,
            )
            try:
                donnees = valeur.encode("utf-8")
                while donnees:
                    donnees = donnees[os.write(fd, donnees) :]
            finally:
                os.close(fd)
            if forme == "credential":
                fournis.argv += ["--credential", f"{nom}={chemin}"]
            else:
                fournis.argv += [option, chemin]
        yield fournis
    finally:
        _nettoyer(dossier)
        atexit.unregister(filet)


# --- Profils d'hôte ---------------------------------------------------------


def slug_hote(cible):
    """`local` pour ce poste, sinon `pve-<cible>` dont les caractères hors
    de `[A-Za-z0-9_.@-]` deviennent `_` : le préfixe évite la collision
    avec un alias ssh nommé `local`."""
    if cible in (None, "", "local"):
        return "local"
    return "pve-" + re.sub(r"[^A-Za-z0-9_.@-]", "_", cible)


def chemin_hote(slug):
    """`<racine des profils>/host/<slug>.json`."""
    return os.path.join(profil.racine_profils(RACINE), "host", f"{slug}.json")


def lire_hote(slug):
    """Le document du profil d'hôte `slug`, ou {} s'il n'existe pas.
    Lève ErreurProfil sur un fichier refusé."""
    chemin = chemin_hote(slug)
    if not os.path.lexists(chemin):
        return {}
    lu = profil.lire(chemin)
    profil.valider_document(lu.doc, chemin, hote=True)
    return lu.doc


# --- Unités -----------------------------------------------------------------


def dossier_unite(nom, dossier=None):
    """Le WorkingDirectory écrit dans l'unité installée `nom`, ou ""."""
    chemin = os.path.join(dossier or profil.DOSSIER_UNITES, nom)
    try:
        with open(chemin, encoding="utf-8") as fichier:
            for ligne in fichier:
                ligne = ligne.strip()
                if ligne.startswith("WorkingDirectory="):
                    return systemd.dossier_de_travail(ligne.partition("=")[2])
    except (OSError, UnicodeDecodeError):
        pass
    return ""


def meme_checkout(dossier):
    """Vrai si `dossier` est ce checkout."""
    return bool(dossier) and os.path.realpath(dossier) == os.path.realpath(
        RACINE
    )


# --- Mixin ------------------------------------------------------------------


def _sans_coffre():
    """Le message d'un coffre KeePass absent de la configuration."""
    return t("No KeePass file is configured (kdbx path in the configuration).")


_ABSENT = object()


class OpsSettingsMixin:
    """Réglages du menu Production. Voir l'en-tête du fichier."""

    # -- Interface -----------------------------------------------------

    def _ask_ui(self, pref_key, **options):
        """`ask_ui` : la question formulaire ou invites, tranchée d'avance
        par la préférence `pref_key`."""
        return ask_ui(pref_key, **options)

    # -- Instance ------------------------------------------------------

    def _ops_service(self, lanceur=None):
        """L'unité visée : celle mémorisée pour ce checkout, sinon celle
        que `systemd.deviner_unite` trouve (une fois par session), sinon
        None."""
        memo = todo_prefs.get(PREF_SERVICE) or {}
        if isinstance(memo, dict) and isinstance(memo.get(RACINE), str):
            return memo[RACINE]
        devinee = getattr(self, "_ops_service_devine", _ABSENT)
        if devinee is _ABSENT:
            try:
                devinee = systemd.deviner_unite(
                    RACINE, lanceur or systemd.lancer
                )[0]
            except (systemd.ErreurUnite, OSError):
                devinee = None
            self._ops_service_devine = devinee
        return devinee

    @staticmethod
    def _ops_retenir_service(service):
        """Mémorise `service` pour ce checkout seulement."""
        memo = todo_prefs.get(PREF_SERVICE) or {}
        memo = dict(memo) if isinstance(memo, dict) else {}
        memo[RACINE] = service
        todo_prefs.set(PREF_SERVICE, memo)

    def _ops_choisir_instance(self, lanceur=None):
        """Choisit l'unité parmi les candidates de cet hôte, ou par son nom
        tapé (normalisé par `systemd.nom_unite`). Un nom absent de l'hôte
        est accepté avec un avertissement : son profil reste éditable.
        Rend l'unité retenue, ou None."""
        lanceur = lanceur or systemd.lancer
        unites = [nom for nom, _actif in systemd.lister_unites(lanceur)]
        candidates = [n for n in unites if systemd.RE_CANDIDATE.fullmatch(n)]
        actuel = self._ops_service(lanceur)
        print(f"\n{t('Instance (systemd unit):')}")
        for numero, nom in enumerate(candidates, 1):
            marque = " *" if nom == actuel else ""
            print(f"  [{numero}] {affichable(nom)}{marque}")
        if not candidates:
            print(f"  {t('No Odoo or ERPLibre unit on this host.')}")
        reponse = input(
            t("Number or unit name (empty = keep {service}): ").format(
                service=actuel or "—"
            )
        ).strip()
        if not reponse:
            return actuel
        numero = entier(reponse)
        if numero == 0:
            return actuel
        if numero is not None:
            # Un nombre est toujours un rang de la liste, jamais un nom :
            # « 5 » ne devient pas l'unité `5.service`.
            if numero > len(candidates):
                print(f"  ✗ {t('No such number in the list.')}")
                return actuel
            nom = candidates[numero - 1]
        else:
            try:
                nom = systemd.nom_unite(reponse)
            except ValueError:
                print(f"  ✗ {t('Invalid unit name.')}")
                return actuel
            if nom not in unites:
                print(
                    "  ⚠ [ATTN] "
                    + t(
                        "{service} is not a unit of this host: its profile"
                        " can still be edited."
                    ).format(service=nom)
                )
        self._ops_retenir_service(nom)
        print(f"  ✓ {t('Instance:')} {nom}")
        return nom

    def _ops_chemin_profil(self, service=None):
        """Le chemin absolu du profil de `service` (l'instance visée par
        défaut), ou None sans instance."""
        service = service or self._ops_service()
        if not service:
            return None
        return os.path.abspath(profil.chemin_profil(service, RACINE))

    def _ops_document(self, service=None):
        """Le `profil.Lu` du profil de l'instance, ou None quand il
        n'existe pas ou se refuse (un avertissement le dit)."""
        chemin = self._ops_chemin_profil(service)
        if chemin is None or not os.path.lexists(chemin):
            return None
        try:
            lu = profil.lire(chemin)
            profil.valider_document(lu.doc, chemin)
        except profil.ErreurProfil as err:
            print(
                "  ⚠ [ATTN] "
                + t("Profile {path}: {error}").format(
                    path=chemin, error=err.message(t)
                )
            )
            return None
        return lu

    def _ops_entete(self, lanceur=None):
        """« 🏭 Instance : S · profil : chemin (n valeur(s)) » ou « aucun »,
        plus un avertissement quand le WorkingDirectory de l'unité n'est
        pas ce checkout."""
        service = self._ops_service(lanceur)
        if not service:
            return f"🏭 {t('Instance:')} — · {t('profile:')} {t('none')}"
        lu = self._ops_document(service)
        if lu is None:
            fichier = t("none")
        else:
            fichier = t("{path} ({count} value(s))").format(
                path=os.path.relpath(lu.chemin, RACINE),
                count=nombre_valeurs(lu.doc),
            )
        ligne = f"🏭 {t('Instance:')} {service} · {t('profile:')} {fichier}"
        alerte = self._ops_alerte_checkout(service, lanceur)
        if alerte:
            ligne += "\n" + alerte
        return ligne

    def _ops_alerte_checkout(self, service, lanceur=None):
        """« ⚠ [ATTN] L'unité fait tourner un autre checkout : … » quand le
        WorkingDirectory de `service` n'est pas ce checkout ; "" sinon, ou
        quand systemd ne répond pas."""
        if not service:
            return ""
        try:
            wd = systemd.lire_proprietes(
                service, ("WorkingDirectory",), lanceur or systemd.lancer
            )["WorkingDirectory"]
        except (systemd.ErreurUnite, OSError, KeyError):
            wd = ""
        dossier = systemd.dossier_de_travail(wd)
        if dossier and not meme_checkout(dossier):
            return "⚠ [ATTN] " + t(
                "The unit runs another checkout: {path}"
            ).format(path=affichable(dossier))
        return ""

    # -- Lancements ----------------------------------------------------

    def _ops_commande(self, groupe, args_lancement):
        """`commande` pour l'instance visée : le profil de l'instance, ou
        le profil d'hôte `local` pour l'audit."""
        if groupe == GROUPE_HOTE:
            return commande(groupe, args_lancement, None, chemin_hote("local"))
        return commande(
            groupe,
            args_lancement,
            self._ops_service(),
            self._ops_chemin_profil(),
        )

    def _ops_valeur(self, groupe, dest):
        """La valeur brute du profil de l'instance pour la `dest` de
        l'outil `groupe`, alias compris ; None sans profil ni valeur."""
        lu = self._ops_document()
        return valeur_du_groupe(lu.doc if lu else None, groupe, dest)

    def _ops_ligne_profil(self, groupe):
        """« Profile: --keep-daily 10, … », la ligne compacte imprimée
        avant une commande ; None quand le profil ne donne rien à cet
        outil."""
        if groupe == GROUPE_HOTE:
            try:
                doc = lire_hote("local")
            except profil.ErreurProfil:
                doc = {}
        else:
            lu = self._ops_document()
            doc = lu.doc if lu else {}
        parser = construire_parseurs((groupe,))[groupe]
        resume = resume_profil(doc, groupe, parser)
        if not resume:
            return None
        return f"{t('Profile:')} {resume}"

    def _ops_coffre(self):
        """Le `SecretStore` du coffre KeePass, ou None quand aucun fichier
        n'est configuré : `KdbxManager` ouvrirait sinon un sélecteur
        graphique au milieu du terminal."""
        from script.todo.modem import code_messagerie

        if not code_messagerie.kdbx_configure(self):
            print(f"  ✗ {_sans_coffre()}")
            return None
        from script.todo.mail.secrets import SecretStore

        # Sans service de secrets, le trousseau retombe sur keyrings.alt,
        # qui écrit en clair : KeePass seul.
        return SecretStore(self.kdbx_manager, use_keyring=False)

    @contextlib.contextmanager
    def _ops_fichiers_secrets(
        self, groupe, args_lancement, simulation=False, forme="option"
    ):
        """`fichiers_secrets` pour le profil de l'instance. Un secret
        manquant (coffre absent ou fermé, pas de tmpfs) fait demander si
        le geste continue sans lui ; un refus pose `abandon`. Aucune
        option n'est ajoutée pour le secret manquant : l'outil écarte son
        dépendant lui-même."""
        lu = self._ops_document()
        with fichiers_secrets(
            lu.doc if lu else {},
            groupe,
            args_lancement,
            coffre=self._ops_coffre,
            simulation=simulation,
            forme=forme,
        ) as fournis:
            if fournis.manquants:
                print(
                    f"  ✗ {t('A secret of the profile is not reachable:')}"
                    f" {', '.join(fournis.manquants)}"
                )
                if not click.confirm(
                    t("Continue without the authenticated warm-up?"),
                    default=True,
                ):
                    fournis.abandon = True
            yield fournis

    # -- Réglages : entrées du menu ------------------------------------

    def _ops_ouvrir_brouillon(self, hote=None):
        """Le `Brouillon` du profil de l'instance, ou du profil d'hôte de
        la cible `hote` ("local" pour ce poste) ; None (message affiché)
        sans instance ou sur un profil refusé."""
        if hote is not None:
            chemin = chemin_hote(slug_hote(hote))
            catalogue = charger_catalogue(hote=True)
            service = None
        else:
            service = self._ops_service()
            if not service:
                print(t("No instance chosen: choose the instance first."))
                return None
            chemin = self._ops_chemin_profil(service)
            catalogue = charger_catalogue()
        try:
            brouillon = Brouillon.ouvrir(
                chemin, catalogue, service=service, hote=hote
            )
        except profil.ErreurProfil as err:
            print(
                f"  ✗ "
                + t("Profile {path}: {error}").format(
                    path=chemin, error=err.message(t)
                )
            )
            return None
        for cle in brouillon.ignorees:
            print(
                "  ⚠ [ATTN] "
                + t("unknown key {key}: removed when saving").format(key=cle)
            )
        return brouillon

    def _ops_settings_edit(self):
        """Édite le profil de l'instance : formulaire ou invites, selon
        `ops_settings_ui`."""
        brouillon = self._ops_ouvrir_brouillon()
        if brouillon is not None:
            self._ops_editer(brouillon)

    def _ops_settings_host_local(self):
        """Édite le profil d'audit de ce poste."""
        brouillon = self._ops_ouvrir_brouillon(hote="local")
        if brouillon is not None:
            self._ops_editer(brouillon)

    def _ops_settings_host(self):
        """Édite le profil d'audit de ce poste ou de l'hôte Proxmox
        retenu."""
        print(f"\n{t('Audit settings of which host?')}")
        print(f"  [1] {t('This machine')}")
        hote_pve = None
        if hasattr(self, "_pve_host"):
            hote_pve = self._pve_host(ask=False)
            libelle = (hote_pve or {}).get("target") or t("to choose")
            print(f"  [2] {t('The Proxmox host')} : {affichable(libelle)}")
        choix = input(t("Choice: ")).strip()
        if choix == "1":
            self._ops_settings_host_local()
        elif choix == "2" and hasattr(self, "_pve_host"):
            hote_pve = hote_pve or self._pve_host(ask=True)
            if not hote_pve or not hote_pve.get("target"):
                print(t("Cancelled."))
                return
            brouillon = self._ops_ouvrir_brouillon(hote=hote_pve["target"])
            if brouillon is not None:
                self._ops_editer(brouillon)
        else:
            print(t("Cancelled."))

    def _ops_editer(self, brouillon):
        """L'interface d'édition retenue par `_ask_ui`, puis
        l'enregistrement. Rend True si le profil a été écrit."""
        if self._ask_ui(PREF_UI) == "tui":
            try:
                import textual  # noqa: F401
            except ImportError:
                print(t("Textual is not available: line-by-line questions."))
            else:
                return self._ops_reglages_formulaire(brouillon)
        return self._ops_reglages_groupes(brouillon)

    def _ops_settings_show(self):
        """Affiche le profil : chaque champ avec sa valeur, son défaut et
        son origine, les alias, puis les options que le profil ne règle
        pas et pourquoi."""
        brouillon = self._ops_ouvrir_brouillon()
        if brouillon is None:
            return
        catalogue = brouillon.catalogue
        existe = os.path.lexists(brouillon.chemin)
        print(
            f"\n{t('Profile:')} {brouillon.chemin}"
            + ("" if existe else f" ({t('absent')})")
        )
        for groupe, champs in catalogue.champs.items():
            print(f"\n── {nom_groupe(groupe)} ──")
            for champ in champs:
                print(f"  {self._ops_ligne_champ(brouillon, champ)}")
            for alias in catalogue.alias.get(groupe, ()):
                cible = champ_cible(catalogue, alias.groupe, alias.cle)
                if cible is not None:
                    print(
                        f"  {self._ops_ligne_alias(brouillon, alias, cible)}"
                    )
        print(f"\n── {t('Options the profile does not set')} ──")
        for groupe, parser in catalogue.parseurs.items():
            exclues = profil.exclusions(groupe)
            lignes = []
            for action in parser._actions:
                code = exclues.get(action.dest)
                if code is None or code == "aide":
                    continue
                lignes.append(
                    f"    {profil.option(action)} : {t(profil.RAISONS[code])}"
                )
            if lignes:
                print(f"  {nom_groupe(groupe)}")
                for ligne in lignes:
                    print(ligne)
        unites = profil.unites_citant(brouillon.chemin)
        if unites:
            print(f"\n{t('Units that use this profile:')} {', '.join(unites)}")

    def _ops_settings_check(self):
        """Fait lire le profil de l'instance, et le profil d'audit de ce
        poste, par les outils de ce checkout ; liste les refus par
        outil."""
        service = self._ops_service()
        chemin = self._ops_chemin_profil(service)
        verifies = 0
        if chemin and os.path.lexists(chemin):
            print(f"\n{t('Profile:')} {chemin}")
            self._ops_afficher_echecs(verifier(chemin, service=service))
            verifies += 1
        hote = chemin_hote("local")
        if os.path.lexists(hote):
            print(f"\n{t('Profile:')} {hote}")
            self._ops_afficher_echecs(verifier(hote, hote=True))
            verifies += 1
        if not verifies:
            print(t("No profile to check."))

    @staticmethod
    def _ops_afficher_echecs(echecs):
        if not echecs:
            print(f"  ✓ {t('Every tool accepts the profile.')}")
            return
        for echec in echecs:
            print(f"  ✗ {nom_groupe(echec.groupe)} ({t('code')} {echec.code})")
            for ligne in (echec.message or "").splitlines()[-6:]:
                print(f"      {ligne}")

    def _ops_settings_delete(self):
        """Supprime le profil de l'instance : refusé tant qu'une unité le
        cite, sinon après avoir tapé le nom du service."""
        service = self._ops_service()
        chemin = self._ops_chemin_profil(service)
        if not chemin or not os.path.lexists(chemin):
            print(t("No profile to delete."))
            return False
        unites = profil.unites_citant(chemin)
        if unites:
            print(
                f"  ✗ "
                + t(
                    "Refused: {units} use this profile. Remove the scheduled"
                    " backup first (systemd timers)."
                ).format(units=", ".join(unites))
            )
            return False
        tape = input(
            t("Type {service} to delete its profile: ").format(service=service)
        ).strip()
        if tape != service:
            print(t("Cancelled: nothing was deleted."))
            return False
        os.unlink(chemin)
        print(f"  ✓ {t('Profile deleted:')} {chemin}")
        return True

    def _ops_settings_secrets(self):
        """Les secrets du profil : leur état, puis l'édition de l'un d'eux
        et l'enregistrement."""
        brouillon = self._ops_ouvrir_brouillon()
        if brouillon is None:
            return False
        secrets = [
            champ
            for champs in brouillon.catalogue.champs.values()
            for champ in champs
            if champ.secret
        ]
        print(f"\n{t('Secrets of the profile')}")
        for numero, champ in enumerate(secrets, 1):
            print(
                f"  [{numero}] {nom_groupe(champ.groupe)} › {champ.option}"
                f"   {formater(brouillon.valeur(champ))}"
            )
        numero = entier(input(t("Choice: ")).strip())
        if numero is None or not 1 <= numero <= len(secrets):
            print(t("Cancelled."))
            return False
        self._ops_reglage_secret(brouillon, secrets[numero - 1])
        if not brouillon.modifie():
            return False
        return self._ops_enregistrer(brouillon)

    # -- Éditeur ligne par ligne ---------------------------------------

    def _ops_ligne_champ(self, brouillon, champ):
        """« --option   valeur (profil) | —   défaut : X   [à
        l'installation] »."""
        brut = brouillon.valeur(champ)
        if brut is None:
            valeur = "—"
        else:
            valeur = f"{formater(brut)} ({t('profile')})"
        texte = (
            f"{champ.option}   {valeur}   {t('default:')}"
            f" {defaut_affiche(champ)}"
        )
        if champ.portee == "installation":
            texte += f"   [{t('at installation')}]"
        return texte

    @staticmethod
    def _ops_ligne_alias(brouillon, alias, cible):
        """« --backup-dest   → Backups › --dest   valeur »."""
        return (
            f"{alias.option}   → {nom_groupe(cible.groupe)} › {cible.option}"
            f"   {formater(brouillon.valeur(cible))}"
        )

    @staticmethod
    def _ops_choix(menu):
        """Affiche le texte `menu` (rendu par `fill_help_info` dans l'écran
        appelant, qui porte l'étiquette du fil d'Ariane) et rend le numéro
        choisi, ou None pour une réponse qui n'en est pas un."""
        reponse = click.prompt(menu)
        print()
        return entier(str(reponse).strip())

    def _ops_reglages_groupes(self, brouillon):
        """Écran des groupes, `n réglés / total` ; puis Enregistrer et
        Différences. [0] avec des changements montre le diff et demande
        d'enregistrer (défaut non). Rend True si le profil a été écrit."""
        groupes = list(brouillon.catalogue.champs)
        while True:
            choices = []
            for groupe in groupes:
                total = len(brouillon.catalogue.champs[groupe])
                regles = len(brouillon.doc.get(groupe) or {})
                choices.append(
                    {
                        "prompt_description": (
                            f"{nom_groupe(groupe)} {regles}/{total}"
                        )
                    }
                )
            choices.append({"section": affichable(brouillon.chemin)})
            choices.append({"prompt_description": t("Save")})
            choices.append({"prompt_description": t("Differences")})
            numero = self._ops_choix(self.fill_help_info(choices))
            if numero == 0:
                if not brouillon.modifie():
                    return False
                self._ops_afficher_diff(brouillon)
                if click.confirm(t("Save the changes?"), default=False):
                    if self._ops_enregistrer(brouillon):
                        return True
                    continue
                print(t("Cancelled: nothing was written."))
                return False
            if numero is not None and 1 <= numero <= len(groupes):
                self._ops_reglages_champs(brouillon, groupes[numero - 1])
            elif numero == len(groupes) + 1:
                if self._ops_enregistrer(brouillon):
                    return True
            elif numero == len(groupes) + 2:
                self._ops_afficher_diff(brouillon)
            else:
                print(t("Command not found !"))

    def _ops_reglages_champs(self, brouillon, groupe):
        """Écran des champs d'un groupe ; un alias mène au champ qu'il
        lit."""
        catalogue = brouillon.catalogue
        while True:
            entrees = []
            choices = []
            for champ in catalogue.champs[groupe]:
                entrees.append(champ)
                choices.append(
                    {
                        "prompt_description": self._ops_ligne_champ(
                            brouillon, champ
                        )
                    }
                )
            for alias in catalogue.alias.get(groupe, ()):
                cible = champ_cible(catalogue, alias.groupe, alias.cle)
                if cible is None:
                    continue
                entrees.append(cible)
                choices.append(
                    {
                        "prompt_description": self._ops_ligne_alias(
                            brouillon, alias, cible
                        )
                    }
                )
            print(f"── {nom_groupe(groupe)} ──")
            numero = self._ops_choix(self.fill_help_info(choices))
            if numero == 0:
                return
            if numero is not None and 1 <= numero <= len(entrees):
                self._ops_reglages_champ(brouillon, entrees[numero - 1])
            else:
                print(t("Command not found !"))

    def _ops_reglages_champ(self, brouillon, champ):
        """Écran d'un champ : aide, genre, valeur et défaut, puis la saisie
        propre à son genre."""
        print(f"── {nom_groupe(champ.groupe)} › {champ.option} ──")
        texte = aide(champ)
        if texte:
            print(f"  {texte}")
        genres = {
            "bool_vrai": t("yes or no"),
            "bool_faux": t("yes or no"),
            "valeur": t("a value"),
            "liste_append": t("a list"),
            "liste_nargs": t("a list"),
        }
        print(
            f"  {t('Kind:')}"
            f" {t('secret') if champ.secret else genres[champ.genre]}"
        )
        print(f"  {t('Value:')} {formater(brouillon.valeur(champ))}")
        print(f"  {t('default:')} {defaut_affiche(champ)}")
        if champ.portee == "installation":
            print(f"  {t('Applies at the next installation of the timer.')}")
        if champ.secret:
            self._ops_reglage_secret(brouillon, champ)
        elif champ.genre in ("bool_vrai", "bool_faux"):
            self._ops_reglage_booleen(brouillon, champ)
        elif champ.genre in ("liste_append", "liste_nargs"):
            self._ops_reglage_liste(brouillon, champ)
        else:
            self._ops_reglage_valeur(brouillon, champ)

    @staticmethod
    def _ops_reglage_valeur(brouillon, champ):
        """Entrée garde la valeur, « - » revient au défaut ; une saisie
        refusée affiche la raison et repose la question."""
        while True:
            texte = input(t("New value (Enter = keep, - = default): ")).strip()
            if not texte:
                return
            if texte == "-":
                brouillon.retirer(champ)
                return
            try:
                brouillon.definir_saisie(champ, texte)
            except profil.ErreurProfil as err:
                print(f"  ✗ {err.message(t)}")
                continue
            return

    @staticmethod
    def _ops_reglage_booleen(brouillon, champ):
        """Oui pose l'option à chaque lancement ; non la retire du profil,
        ce qui rend le défaut de l'outil."""
        if click.confirm(
            t("Pass {option} on each run?").format(option=champ.option),
            default=brouillon.effectif(champ),
        ):
            brouillon.definir(champ, True)
        else:
            brouillon.retirer(champ)

    def _ops_reglage_liste(self, brouillon, champ):
        """Ajouter (validé), retirer l'élément n, vider."""
        while True:
            elements = list(brouillon.valeur(champ) or [])
            for numero, element in enumerate(elements, 1):
                print(f"  {numero}. {formater(element)}")
            if not elements:
                print(f"  {t('(empty)')}")
            numero = self._ops_choix(
                self.fill_help_info(
                    [
                        {"prompt_description": t("Add an element")},
                        {"prompt_description": t("Remove element n")},
                        {"prompt_description": t("Clear the list")},
                    ]
                )
            )
            if numero == 0:
                return
            if numero == 1:
                texte = input(t("Element to add: ")).strip()
                if not texte:
                    continue
                try:
                    brouillon.definir(champ, elements + [texte])
                except profil.ErreurProfil as err:
                    print(f"  ✗ {err.message(t)}")
            elif numero == 2:
                rang = entier(input(t("Number of the element: ")).strip())
                if rang is None or not 1 <= rang <= len(elements):
                    print(t("Cancelled."))
                    continue
                del elements[rang - 1]
                if elements:
                    brouillon.definir(champ, elements)
                else:
                    brouillon.retirer(champ)
            elif numero == 3:
                brouillon.retirer(champ)
            else:
                print(t("Command not found !"))

    def _ops_lire_secret(self):
        """Le secret tapé sans écho, ou None (vide, pas de terminal)."""
        try:
            valeur = getpass.getpass(t("Secret (not shown): "))
        except (EOFError, OSError):
            return None
        return valeur or None

    def _ops_reglage_secret(self, brouillon, champ):
        """[1] saisir (rangé dans KeePass à l'enregistrement), [2] chemin
        d'un fichier (absolu, existant, sans lien), [3] retirer, avec
        l'entrée du coffre sur accord. Le profil ne porte que la
        référence ou le chemin."""
        from script.todo.modem import code_messagerie

        reference = reference_secret(
            brouillon.nom, profil.SECRETS[(champ.groupe, champ.cle)]
        )
        numero = self._ops_choix(
            self.fill_help_info(
                [
                    {
                        "prompt_description": t(
                            "Type the secret - stored in KeePass when saving"
                        )
                    },
                    {
                        "prompt_description": t(
                            "Path of a file holding the secret"
                        )
                    },
                    {"prompt_description": t("Remove the secret")},
                ]
            )
        )
        if numero == 1:
            if not code_messagerie.kdbx_configure(self):
                print(f"  ✗ {_sans_coffre()}")
                return
            valeur = self._ops_lire_secret()
            if valeur is None:
                print(t("Cancelled."))
                return
            brouillon.definir(champ, {"kdbx": reference})
            brouillon.secrets_a_definir[reference] = valeur
            brouillon.secrets_a_retirer.discard(reference)
        elif numero == 2:
            chemin = input(t("Absolute path of the file: ")).strip()
            if (
                not os.path.isabs(chemin)
                or os.path.islink(chemin)
                or not os.path.isfile(chemin)
            ):
                print(
                    "  ✗ "
                    + t(
                        "Expected the absolute path of an existing file, not"
                        " a link."
                    )
                )
                return
            brouillon.definir(champ, chemin)
            brouillon.secrets_a_definir.pop(reference, None)
        elif numero == 3:
            actuel = brouillon.valeur(champ)
            brouillon.retirer(champ)
            brouillon.secrets_a_definir.pop(reference, None)
            if isinstance(actuel, dict) and click.confirm(
                t("Also delete the entry from KeePass?"), default=False
            ):
                brouillon.secrets_a_retirer.add(actuel["kdbx"])
        elif numero != 0:
            print(t("Command not found !"))

    # -- Formulaire ----------------------------------------------------

    def _ops_etats_secrets(self, brouillon):
        """{(groupe, clé): état} des secrets du brouillon, lu AVANT le
        formulaire : "kdbx" (dans le coffre), "kdbx_attente" (saisi, rangé
        à l'enregistrement), "kdbx_absent", "kdbx_inconnu" (coffre fermé),
        "fichier" ou "aucun"."""
        etats = {}
        store = _ABSENT
        for champs in brouillon.catalogue.champs.values():
            for champ in champs:
                if not champ.secret:
                    continue
                brut = brouillon.valeur(champ)
                if (
                    isinstance(brut, dict)
                    and brut.get("kdbx") in brouillon.secrets_a_definir
                ):
                    etat = "kdbx_attente"
                elif isinstance(brut, dict):
                    if store is _ABSENT:
                        store = self._ops_coffre()
                    etat = "kdbx_inconnu"
                    if store is not None:
                        try:
                            present = store.get(ref_coffre(brut["kdbx"]))
                        except Exception:
                            present = None
                        else:
                            etat = "kdbx" if present else "kdbx_absent"
                elif isinstance(brut, str):
                    etat = "fichier"
                else:
                    etat = "aucun"
                etats[(champ.groupe, champ.cle)] = etat
        return etats

    def _ops_reglages_formulaire(self, brouillon):
        """Le formulaire Textual, puis la saisie des secrets par getpass,
        terminal rendu, puis l'enregistrement. Un enregistrement refusé
        rouvre le formulaire sur le même brouillon, secrets déjà saisis
        compris, après une question qui laisse lire le refus. Rend True
        si le profil a été écrit."""
        from script.todo import ops_settings_form
        from script.todo.modem import code_messagerie

        while True:
            contexte = ops_settings_form.Contexte(
                catalogue=brouillon.catalogue,
                doc=copy.deepcopy(brouillon.doc),
                chemin=brouillon.chemin,
                nom=brouillon.nom,
                etats_secrets=self._ops_etats_secrets(brouillon),
                coffre_configure=code_messagerie.kdbx_configure(self),
            )
            resultat = ops_settings_form.run_settings_form(contexte)
            if resultat is None:
                print(t("Cancelled: nothing was written."))
                return False
            if not self._ops_appliquer_formulaire(brouillon, resultat):
                print(t("Cancelled: nothing was written."))
                return False
            if not brouillon.modifie():
                print(t("Nothing to save."))
                return False
            if self._ops_enregistrer(brouillon):
                return True
            if not click.confirm(t("Back to the form?"), default=True):
                print(t("Cancelled: nothing was written."))
                return False

    def _ops_appliquer_formulaire(self, brouillon, resultat):
        """Reporte le `Resultat` du formulaire dans `brouillon` : son
        document, chaque secret à définir lu par getpass, et chaque secret
        retiré, dont l'entrée KeePass n'est supprimée que sur accord
        (défaut non). Un secret saisi à un tour précédent et encore cité
        reste en attente sans être redemandé. Rend False si une saisie est
        abandonnée."""
        brouillon.doc = resultat.doc
        citees = references_kdbx(brouillon.doc)
        for reference in list(brouillon.secrets_a_definir):
            if reference not in citees:
                del brouillon.secrets_a_definir[reference]
        for reference in resultat.secrets_a_definir:
            print(f"{t('Secret')} {reference}")
            valeur = self._ops_lire_secret()
            if valeur is None:
                return False
            brouillon.secrets_a_definir[reference] = valeur
            brouillon.secrets_a_retirer.discard(reference)
        for reference in resultat.secrets_a_retirer:
            print(f"{t('Secret')} {reference}")
            if click.confirm(
                t("Also delete the entry from KeePass?"), default=False
            ):
                brouillon.secrets_a_retirer.add(reference)
        return True

    # -- Enregistrer ---------------------------------------------------

    def _ops_afficher_diff(self, brouillon):
        """Les changements du brouillon, secrets compris, sans valeur de
        secret."""
        differences = brouillon.differences()
        if not (differences or brouillon.modifie()):
            print(t("No change."))
            return
        for groupe, cle, ancienne, nouvelle in differences:
            print(
                f"  {nom_groupe(groupe)} › {cle} : {formater(ancienne)}"
                f" → {formater(nouvelle)}"
            )
        for cle in brouillon.ignorees:
            print(f"  {t('removed (unknown key):')} {cle}")
        for reference in brouillon.secrets_a_definir:
            print(f"  {t('KeePass entry to set:')} {reference}")
        for reference in sorted(brouillon.secrets_a_retirer):
            print(f"  {t('KeePass entry to delete:')} {reference}")

    def _ops_apercu_retention(self, brouillon):
        """Quand un `keep_*` change : combien de sauvegardes de
        `<dest>/<base>` le prochain passage supprimerait, et une
        confirmation (défaut non) s'il y en a. Rend False pour renoncer."""
        from script.lib_ops import retention

        groupe, cles, _minimum = profil.BORNE_SOMME
        if not any(
            g == groupe and c in cles
            for g, c, _a, _n in brouillon.differences()
        ):
            return True
        champs = {c.cle: c for c in brouillon.catalogue.champs.get(groupe, ())}

        def effectif(cle):
            brut = (brouillon.doc.get(groupe) or {}).get(cle)
            if brut is None:
                return champs[cle].defaut
            return profil.convertir(champs[cle], brut)

        base = (brouillon.doc.get(profil.GROUPE_INSTANCE) or {}).get("db")
        if not base:
            print(
                t(
                    "Retention preview unavailable: the database is detected"
                    " at run time."
                )
            )
            return True
        dossier = os.path.join(effectif("dest"), base)
        try:
            noms = os.listdir(dossier)
        except FileNotFoundError:
            return True
        except OSError:
            print(
                t(
                    "{path} is not readable without sudo: retention preview"
                    " unavailable."
                ).format(path=dossier)
            )
            return True
        supprimees = retention.a_supprimer(
            noms,
            base,
            effectif("keep_daily"),
            effectif("keep_weekly"),
            effectif("keep_monthly"),
            effectif("keep_recent_days"),
        )
        print(
            t("{count} backup(s) would be deleted at the next run.").format(
                count=len(supprimees)
            )
        )
        if not supprimees:
            return True
        return click.confirm(
            t("Keep these retention settings?"), default=False
        )

    def _ops_afficher_unites(self, unites):
        """Les unités qui citent le profil ; un avertissement pour celles
        qui font tourner un autre checkout."""
        if not unites:
            return
        print(f"{t('Units that use this profile:')} {', '.join(unites)}")
        for unite in unites:
            dossier = dossier_unite(unite)
            if dossier and not meme_checkout(dossier):
                print(
                    "  ⚠ [ATTN] "
                    + t(
                        "{unit} runs another checkout ({path}): it was"
                        " checked with this checkout's tools."
                    ).format(unit=unite, path=affichable(dossier))
                )

    def _ops_enregistrer(self, brouillon):
        """Enregistre le brouillon : différences, vérification par les
        outils, aperçu de rétention, unités qui citent le profil, coffre,
        écriture atomique sous verrou optimiste, puis proposition de
        réinstallation quand un champ « à l'installation » ou un secret
        change. Rend True si le profil a été écrit. Sur un refus, le profil
        n'est pas écrit et aucune entrée KeePass n'est supprimée ; une
        entrée déjà rangée est signalée."""
        if not brouillon.modifie():
            print(t("Nothing to save."))
            return False
        self._ops_afficher_diff(brouillon)
        hote = "host" in brouillon.doc
        echecs = verifier_brouillon(brouillon, hote=hote)
        if echecs:
            print(
                "  ✗ "
                + t("The tools refuse this profile: nothing was written.")
            )
            self._ops_afficher_echecs(echecs)
            return False
        if not self._ops_apercu_retention(brouillon):
            print(t("Cancelled: nothing was written."))
            return False
        unites = profil.unites_citant(brouillon.chemin)
        self._ops_afficher_unites(unites)
        differences = brouillon.differences()
        secrets_changes = bool(
            brouillon.secrets_a_definir or brouillon.secrets_a_retirer
        ) or any((g, c) in profil.SECRETS for g, c, _a, _n in differences)
        installation = any(
            (g, c) in profil.INSTALLATION for g, c, _a, _n in differences
        )
        # Une entrée définie est rangée AVANT l'écriture : le profil écrit
        # doit la résoudre. Une entrée retirée l'est APRÈS : sur un échec
        # de l'écriture, le profil resté sur disque la cite encore.
        a_retirer = sorted(
            brouillon.secrets_a_retirer - set(brouillon.secrets_a_definir)
        )
        definies = []
        store = None
        if brouillon.secrets_a_definir or a_retirer:
            store = self._ops_coffre()
            if store is None:
                print(t("Nothing was written."))
                return False
            try:
                for reference, valeur in brouillon.secrets_a_definir.items():
                    store.set(ref_coffre(reference), valeur)
                    definies.append(reference)
            except Exception as err:
                print(
                    f"  ✗ {t('KeePass refused:')} {affichable(err)}"
                    f" — {t('Nothing was written.')}"
                )
                self._ops_coffre_deja_change(definies)
                return False
        try:
            empreinte = profil.ecrire(
                brouillon.chemin, brouillon.doc, brouillon.empreinte
            )
        except profil.ErreurProfil as err:
            print(f"  ✗ {err.message(t)}")
            self._ops_coffre_deja_change(definies)
            return False
        except OSError as err:
            print(f"  ✗ {brouillon.chemin}: {err.strerror}")
            self._ops_coffre_deja_change(definies)
            return False
        if a_retirer:
            try:
                for reference in a_retirer:
                    store.delete(ref_coffre(reference))
            except Exception as err:
                print(
                    "  ⚠ [ATTN] "
                    + t("Profile saved, but KeePass kept {refs}:").format(
                        refs=", ".join(a_retirer)
                    )
                    + f" {affichable(err)}"
                )
        brouillon.enregistre(empreinte)
        print(f"  ✓ {t('Profile saved:')} {brouillon.chemin}")
        if unites and (installation or secrets_changes):
            self._ops_proposer_reinstallation(unites)
        return True

    @staticmethod
    def _ops_coffre_deja_change(definies):
        """Le profil n'est pas écrit mais KeePass porte déjà la nouvelle
        valeur de `definies` : le profil resté sur disque qui cite la même
        référence la lit dès maintenant. Sans effet sur une liste vide."""
        if definies:
            print(
                "  ⚠ [ATTN] "
                + t(
                    "The profile was not written, but KeePass already holds"
                    " the new secret: {refs}"
                ).format(refs=", ".join(definies))
            )

    def _ops_proposer_reinstallation(self, unites):
        """Une unité garde une copie prise à l'installation : propose de
        réinstaller la sauvegarde planifiée."""
        print(
            "  ⚠ [ATTN] "
            + t(
                "{units} keep a copy taken at installation: reinstall to"
                " apply the change."
            ).format(units=", ".join(unites))
        )
        installer = getattr(self, "_ops_backup_timer_install", None)
        if installer is None:
            return
        if click.confirm(
            t("Reinstall the scheduled backup now?"), default=True
        ):
            installer()
