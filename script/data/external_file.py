#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Décrire un fichier externe, puis en tirer une copie anonymisée.

Excel, Access, CSV, XML et JSON. Aucune IA, aucun appel réseau : des mots
pris dans une liste locale et des nombres tirés dans l'étendue mesurée de
leur colonne.

Ce qui rend la chose délicate n'est pas de remplacer une cellule, c'est de
savoir CE QUI PORTE DE LA DONNÉE. Un classeur en porte dans une douzaine
d'endroits qui ne sont pas des cellules — d'où `nettoyer_hors_cellules`, et
d'où le fait que sa liste sorte d'une MESURE et non d'une lecture du schéma.

Deux interpréteurs, un seul module
----------------------------------
Les formats en pur stdlib — CSV, JSON, XML, et la détection de macros qui
n'est qu'un `zipfile.namelist()` — tournent sous l'interpréteur du CLI.
Excel et Access exigent un venv dédié. Le module doit donc s'importer sous
les deux : AUCUN import de bibliothèque tierce au niveau du module, chacun
vit dans la fonction qui en a besoin. Les tests unitaires du dépôt tournent
sous `.venv.erplibre`, qui n'a pas openpyxl : un import au niveau du module
les ferait tomber tous, y compris ceux des règles pures.

Le canal de sortie
------------------
stdout ne porte QUE du JSON, un seul objet. Tout le reste — progression,
avertissements de bibliothèque — va sur stderr. Un appelant qui lit stdout
n'a donc rien à filtrer.
"""

from __future__ import annotations

import argparse
import datetime
import decimal
import html
import json
import math
import os
import re
import sys
import tempfile
import unicodedata
import zipfile

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.analyse.anonymize import MOTS_PAR_DEFAUT  # noqa: E402

# Les clés d'erreur, à UN seul endroit. Le moteur n'écrit jamais un libellé
# ailleurs : `t()` rend la clé quand elle manque, sans lever, donc un libellé
# dispersé se traduirait en silence par de l'anglais. Le test de §10 balaie
# CETTE constante contre TRANSLATIONS.
ERREURS = {
    "format_inconnu": "Format not recognised: ",
    "illisible_ici": "Recognised format, unreadable here"
    " — re-save it as .xlsx.",
    "protege": "Protected by a password, or not a workbook"
    " — unreadable here.",
    "vide": "Empty file.",
    "droits": "Not readable: check the permissions.",
    "pas_un_fichier": "Not an ordinary file.",
    "destination_source": "The destination is the source file;"
    " nothing was written.",
    "repertoire_non_vide": "The destination directory exists"
    " and is not empty.",
    "aucune_feuille": "The selection matches no sheet;"
    " nothing was written.",
    "tout_exclu": "Nothing was anonymised: every region was excluded.",
    "rien_a_faire": "Nothing to anonymise in this file.",
    "place": "Not enough room to write.",
    "conversion_impossible": "This target cannot hold the source's" " shape: ",
    "table_source": "The mapping table would overwrite the source"
    " or the copy; nothing was written.",
    "fuite_detectee": "A source value survives in the copy;"
    " nothing was written: ",
    "lecture_impossible": "The library here cannot read this file: ",
}

# Les sept constantes d'erreur d'Excel. Elles arrivent en `str` SANS `=` en
# tête : la règle de la formule ne les retient pas, et celle du texte les
# changerait en mot — ce qui fait répondre FAUX à un SIERREUR resté intact
# à côté. La liste est RECOPIÉE et non importée d'openpyxl : les règles
# pures doivent se tester sans lui.
VALEURS_ERREUR = frozenset(
    {
        "#NULL!",
        "#DIV/0!",
        "#VALUE!",
        "#REF!",
        "#NAME?",
        "#NUM!",
        "#N/A",
    }
)

# xlrd stocke une cellule d'erreur par son CODE BIFF, en entier. Sans cette
# traduction, la règle du nombre en fait un montant plausible, et celle de
# l'erreur — qui teste les sept chaînes — ne se déclenche jamais. Le code 0
# est le piège : « 0 reste 0 » le laisserait passer pour un zéro légitime.
CODES_ERREUR_XLS = {
    0: "#NULL!",
    7: "#DIV/0!",
    15: "#VALUE!",
    23: "#REF!",
    29: "#NAME?",
    36: "#NUM!",
    42: "#N/A",
}

# Une étiquette de colonne qui porte un identifiant. `anonymize.py` refuse
# par le NOM avant de regarder la moindre valeur, et sa docstring dit ce que
# ça lui a coûté : des champs `selection` où « écrire un mot au hasard casse
# l'ORM, pas la confidentialité », et des relations entières dont la
# randomisation mélangerait toute la base. Un export tableur de cette même
# base porte les mêmes colonnes sous les mêmes étiquettes.
# Une étiquette dont le CONTENU n'est jamais du texte libre : le plancher
# peut tomber sur le nom seul sans rien laisser passer.
PLANCHER_STRUCTUREL = frozenset(
    {
        "id",
        "create_uid",
        "write_uid",
        "create_date",
        "write_date",
        "sequence",
        "active",
        "color",
        "res_field",
        "__last_update",
        "arch_fs",
    }
)
SUFFIXES_STRUCTURELS = ("/id", "/.id")

# Une étiquette qui PEUT porter du texte libre. Un export Odoo
# import-compatible met le nom affiché de la relation dans « partner_id », et
# « State », « Key » ou « Model » d'un classeur ordinaire ne sont pas les
# champs d'Odoo. Le plancher n'y tombe que si le contenu MESURÉ a la forme
# d'un identifiant : décider sur le nom seul recopiait textuellement les
# colonnes les plus identifiantes du fichier.
SUFFIXES_IDENTIFIANTS = ("_id", "_ids")
# Les étiquettes dont le contenu légitime EST une clé technique en
# minuscules. `display_name` n'en fait pas partie : dans un fichier plat il
# EST la donnée, et aucune forme mesurée ne doit le sauver.
# Ces étiquettes portent légitimement un jeton POINTÉ — un nom de modèle,
# un external ID. Elles exigent la même preuve qu'une relation.
ETIQUETTES_POINTEES = frozenset({"key", "model", "res_model", "arch_db"})

# `state` porte une valeur de SÉLECTION : un jeton minuscule pris dans un
# ensemble fermé et petit. Le seul test de forme accepterait n'importe quel
# mot minuscule — une colonne de provinces, ou de créneaux nommés par des
# personnes — d'où la borne sur le nombre de valeurs distinctes.
ETIQUETTES_SELECTION = frozenset({"state"})

# Au-delà, ce n'est plus une sélection : c'est une colonne de texte dont
# les valeurs se trouvent être en minuscules.
SELECTION_MAX_DISTINCTES = 12

# Un chemin d'identifiants Odoo, une valeur de sélection, un external ID.
_MOTIF_CHEMIN_ID = re.compile(r"[0-9]+(?:/[0-9]+)*/?")
_MOTIF_SELECTION = re.compile(r"[a-z0-9_]+")
# Un external ID, un nom de modèle : minuscules et AU MOINS un point. Ne pas
# borner le nombre de points — « account.move.line » en porte deux.
_MOTIF_POINTE = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)+")
# Un nom de fichier a la forme d'un external ID : des mots, des chiffres,
# des points. C'est l'EXTENSION qui le trahit, et un fichier de paie porte
# le nom de la personne.
EXTENSIONS_FICHIER = frozenset(
    {
        "pdf",
        "doc",
        "docx",
        "odt",
        "xls",
        "xlsx",
        "xlsm",
        "csv",
        "ods",
        "ppt",
        "pptx",
        "odp",
        "txt",
        "rtf",
        "zip",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "svg",
        "eml",
        "msg",
        "xml",
        "json",
        "html",
        "htm",
    }
)


def _pointe_identifiant(texte):
    """Vrai pour « account.move.line », faux pour « rapport.pdf »."""
    if not _MOTIF_POINTE.fullmatch(texte):
        return False
    return texte.rsplit(".", 1)[1] not in EXTENSIONS_FICHIER


def valeur_forme_identifiant(valeur):
    """Vrai si cette valeur a la forme d'un identifiant, non d'un nom.

    Le doute profite à l'ANONYMISATION : ce qui n'est pas franchement un
    identifiant est traité comme du texte, donc remplacé. L'inverse — croire
    identifiant ce qui est un nom — recopie la donnée en clair et l'annonce
    comme protégée.
    """
    if isinstance(valeur, bool) or isinstance(valeur, int):
        return True
    if isinstance(valeur, float):
        return valeur.is_integer()
    if not isinstance(valeur, str):
        return False
    texte = valeur.strip()
    if not texte:
        return True
    if _MOTIF_CHEMIN_ID.fullmatch(texte):
        return True
    if _MOTIF_SELECTION.fullmatch(texte):
        return True
    # Un external ID porte un point ; la virgule tient la liste d'un m2m.
    # Exiger les MINUSCULES et refuser une extension de fichier : sinon
    # « Paie_Marie_2025_03.pdf » et « clinique.exemple.com » passaient pour
    # des identifiants, et le plancher les recopiait en clair.
    return all(_pointe_identifiant(p) for p in texte.split(","))


# Un external ID PROUVÉ : un local numéroté, ou le module sentinelle
# qu'Odoo écrit lui-même à l'export.
_MOTIF_XMLID_NUMEROTE = re.compile(r"[a-z0-9_]+\.[a-z0-9_]*_[0-9]+")
_MODULES_EXPORT = ("__export__.", "__import__.")


def _cible_externe(texte):
    """Vrai pour un external ID PROUVÉ, faux pour un login pointé.

    « base.res_partner_7 » et « jean.tremblay » ont exactement la même
    forme, et compter les préfixes communs d'une colonne ne tranchait pas :
    une équipe entière de logins partage son domaine, et une colonne à une
    seule valeur n'a aucun préfixe à comparer. Ce qui PROUVE un external
    ID est le numéro de son local, ou le module sentinelle de l'export.

    Sans preuve, la valeur est du texte et part au remplacement : le doute
    profite à l'anonymisation. Une colonne de noms de modèles — `res_model`
    portant « account.move » — est donc anonymisée elle aussi, faute de
    pouvoir la distinguer d'une colonne de personnes.
    """
    brut = texte.strip()
    if not _pointe_identifiant(brut):
        return False
    if brut.startswith(_MODULES_EXPORT):
        return True
    return bool(_MOTIF_XMLID_NUMEROTE.fullmatch(brut))


def valeur_forme_relation(valeur):
    """Vrai si cette valeur peut être la CIBLE d'une relation.

    Plus étroit que `valeur_forme_identifiant` : un mot en minuscules n'est
    pas une valeur de relation. C'est ce qui laissait « user_id » porter un
    login et « department_id » un nom de service, tous deux recopiés en
    clair et annoncés comme protégés.
    """
    if isinstance(valeur, bool) or isinstance(valeur, int):
        return True
    if isinstance(valeur, float):
        return valeur.is_integer()
    if not isinstance(valeur, str):
        return False
    texte = valeur.strip()
    if not texte:
        return True
    if _MOTIF_CHEMIN_ID.fullmatch(texte):
        return True
    return all(_cible_externe(p) for p in texte.split(","))


# Les octets de tête qui tranchent, quand l'extension mentirait.
SIGNATURES = (
    (b"PK\x03\x04", "opc"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole2"),
)

EXTENSIONS = {
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".xlsb": "xlsb",
    ".xls": "xls",
    ".mdb": "access",
    ".accdb": "access",
    ".csv": "csv",
    ".xml": "xml",
    ".json": "json",
}

FORMATS_STDLIB = frozenset({"csv", "xml", "json"})
FORMATS_LECTURE_SEULE = frozenset({"xls", "xlsb", "access"})


def progres(message):
    """Une ligne de progression, sur stderr. stdout est réservé au JSON."""
    print(f"# {message}", file=sys.stderr, flush=True)


# ----------------------------------------------------------------------
# La porte d'entrée
# ----------------------------------------------------------------------
def verifier_source(chemin):
    """None si le fichier est exploitable, sinon une clé d'`ERREURS`.

    Appelée AVANT `detect_format` : un répertoire, un lien cassé ou un
    fichier sans droit de lecture ne doivent pas arriver jusqu'à une
    bibliothèque, qui les rapporterait par une exception en anglais.
    """
    if not os.path.isfile(chemin):
        return "pas_un_fichier"
    if not os.access(chemin, os.R_OK):
        return "droits"
    try:
        if os.path.getsize(chemin) == 0:
            return "vide"
    except OSError:
        return "droits"
    return None


def signature(chemin):
    """La famille de conteneur, lue dans les premiers octets."""
    try:
        with open(chemin, "rb") as fh:
            tete = fh.read(8)
    except OSError:
        return ""
    for octets, nom in SIGNATURES:
        if tete.startswith(octets):
            return nom
    if tete[:1] == b"<":
        return "balise"
    return "texte"


def detect_format(chemin):
    """Le format, décidé par le CONTENU ; l'extension n'est qu'un indice.

    Le cas fréquent est le fichier qui mente sur son extension : un export
    d'ERP nommé `.xls` qui est du HTML, un `.xlsx` qui est un `.xls`, un
    classeur protégé par mot de passe — lequel est un conteneur OLE2, donc
    indiscernable d'un `.xls` par l'extension seule et indiscernable d'un
    fichier corrompu si l'on se contente de l'exception d'openpyxl.
    """
    extension = os.path.splitext(chemin)[1].lower()
    attendu = EXTENSIONS.get(extension, "")
    sig = signature(chemin)

    if attendu == "xlsb":
        return "xlsb"
    if sig == "opc":
        return "xlsb" if attendu == "xlsb" else "xlsx"
    if sig == "ole2":
        # OLE2 sous une extension OOXML : protégé ou non conforme. Jamais
        # passé à openpyxl, qui ne saurait pas distinguer les deux cas.
        return "xls" if attendu in ("xls", "") else "protege"
    if sig == "balise":
        if attendu == "json":
            return "xml"
        return attendu if attendu in ("xml",) else "xml"
    if attendu in ("csv", "json", "access", "xml"):
        return attendu
    return attendu or ""


def format_divergent(chemin, format_lu):
    """Vrai si le contenu et l'extension ne disent pas la même chose."""
    extension = os.path.splitext(chemin)[1].lower()
    attendu = EXTENSIONS.get(extension, "")
    return bool(attendu) and attendu != format_lu


def has_macros(chemin):
    """Un projet VBA est-il présent ? PRÉSENCE seule, jamais un compte.

    Le zip ne porte qu'une entrée, `xl/vbaProject.bin` : la liste des
    modules vit dans le compound OLE qu'elle contient, et la compter
    exigerait un lecteur OLE, absent des deux venvs.

    `zipfile` LÈVE sur tout ce qui n'est pas un zip — un OLE2, un fichier
    vide, un fichier tronqué — et le chemin `.xlsb` passe par cette
    fonction et par elle seule. Le contrat `-> bool` l'exige donc d'être
    close.
    """
    try:
        with zipfile.ZipFile(chemin) as z:
            return "xl/vbaProject.bin" in z.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def compter_media(chemin):
    """Les images du classeur, comptées par `zipfile`.

    openpyxl ne les voit que si Pillow est là, et ne les recopie jamais :
    `find_images` rend une liste vide sans Pillow. Le compte doit donc venir
    du conteneur, pour que le rapport puisse annoncer ce que la copie perd.
    """
    try:
        with zipfile.ZipFile(chemin) as z:
            return sum(1 for n in z.namelist() if n.startswith("xl/media/"))
    except (zipfile.BadZipFile, OSError):
        return 0


# ----------------------------------------------------------------------
# Le vivier de mots
# ----------------------------------------------------------------------
def _deplier(mot):
    """Un mot sans accent ni majuscule.

    Translittérer plutôt que rejeter : « acédie » devient « acedie » au
    lieu de disparaître, ce qui rend 354 mots sur 1404. Et la sortie reste
    sûre partout — une valeur de cellule, un nom de fichier et un
    identifiant réimporté n'ont pas la même tolérance à l'accent, et aucun
    n'en a besoin.
    """
    plie = unicodedata.normalize("NFKD", mot)
    return "".join(c for c in plie if not unicodedata.combining(c)).lower()


def vivier_de_mots():
    """Les mots disponibles, triés et dédoublonnés.

    TRIÉ obligatoirement : l'ordre d'un `set` varie d'un processus à
    l'autre, et l'attribution étant indexée, une table réutilisée d'une
    exécution à l'autre rendrait d'autres mots pour les mêmes valeurs.

    Repli sur les 20 mots d'`anonymize` si `randomwordfr` manque — le
    rapport le dit plutôt que de laisser croire au vivier complet.
    """
    try:
        import randomwordfr

        mots = {
            _deplier(entree["word"])
            for entree in randomwordfr.data
            if " " not in entree["word"]
        }
        mots = {m for m in mots if re.fullmatch(r"[a-z_]+", m)}
        if mots:
            return tuple(sorted(mots))
    except Exception:  # pragma: no cover - repli si le paquet manque
        pass
    return tuple(sorted(MOTS_PAR_DEFAUT))


def _entetes_lisibles(brut):
    """Les lignes d'en-tête d'une table, réduites à ce qui s'en lit.

    Une table est un fichier du disque : elle arrive tronquée, éditée à la
    main, ou d'une version que ce code ne connaît pas. Ce qui ne se lit
    pas est SAUTÉ, jamais levé — la mémoire de lot est un confort, et la
    perdre vaut mieux que perdre le travail. Cinq formes malformées
    faisaient lever, dont une chaîne à la place d'une liste, qui s'itère
    caractère par caractère.
    """
    if not isinstance(brut, dict):
        return {}
    rendu = {}
    for nom, lignes in brut.items():
        if isinstance(lignes, (str, bytes)) or not hasattr(lignes, "__iter__"):
            continue
        rendu[str(nom)] = lignes_entieres(lignes)
    return rendu


def lignes_entieres(lignes):
    """Des numéros de ligne 1-based, réduits à ce qui s'en lit.

    Une seule écriture de la règle : elle sert à la lecture d'une table du
    disque comme à l'enregistrement d'une réponse venue d'un JSON, et deux
    copies auraient fini par accepter des choses différentes.
    """
    if isinstance(lignes, (str, bytes)) or not hasattr(lignes, "__iter__"):
        return []
    gardees = set()
    for ligne in lignes:
        try:
            numero = int(ligne)
        except (TypeError, ValueError):
            continue
        if numero >= 1:
            gardees.add(numero)
    return sorted(gardees)


class Correspondance:
    """La table qui donne son intégrité référentielle à la copie.

    Deux dictionnaires, parce que les deux espaces ne se mélangent pas : un
    texte rend un mot, un nombre rend un nombre. L'attribution est SANS
    REMISE et indexée par un compteur — jamais un tirage. Sur 20 mots tirés
    au hasard, six valeurs distinctes ont déjà 56 % de chance d'en partager
    un, et deux clients qui reçoivent le même mot fusionnent en une seule
    clé : la RECHERCHEV résout encore, mais sur la mauvaise ligne.

    Sérialisable en JSON, pour que la question de la réutilisation puisse
    porter la table d'un fichier à l'autre d'un même lot. C'est aussi le
    seul objet produit qui RÉ-IDENTIFIE la copie : il vit dans `private/`.
    """

    # 2 depuis que la table se rappelle les lignes d'en-tête. Une table
    # de version 1 se charge toujours : `charger` lit une clé ABSENTE
    # comme un dictionnaire vide, faute de quoi le deuxième fichier d'un
    # lot commencé avant refuserait la table du premier.
    VERSION = 2

    def __init__(self, mots=None, nombres=None, entetes=None):
        self.mots = dict(mots or {})
        self.nombres = dict(nombres or {})
        # {nom de feuille: [lignes d'en-tête]} — ce que l'opérateur a
        # RÉPONDU sur un fichier de ce lot. Le deuxième fichier d'un même
        # export porte les mêmes feuilles, si bien que la correction n'est
        # à faire qu'une fois. Elle n'est JAMAIS appliquée en silence :
        # l'écran la montre pré-cochée, une réponse fausse appliquée sans
        # être vue étant exactement comment une erreur gagne tout un lot.
        self.entetes = _entetes_lisibles(entetes)
        # Les nombres DÉJÀ attribués. Reconstruits au chargement, pour
        # qu'une table réutilisée d'un fichier à l'autre continue de
        # garantir l'unicité sur tout le lot.
        self.nombres_pris = set(self.nombres.values())
        # Les mots DÉJÀ attribués, pour la même raison — et parce que le
        # saut d'identité ci-dessous peut retomber sur l'un d'eux.
        self.mots_pris = set(self.mots.values())

    @classmethod
    def charger(cls, chemin):
        if not chemin or not os.path.isfile(chemin):
            return cls()
        with open(chemin, "r", encoding="utf-8") as fh:
            brut = json.load(fh)
        return cls(brut.get("mots"), brut.get("nombres"), brut.get("entetes"))

    def ecrire(self, chemin):
        """Écrite en 0600, et par un temporaire renommé.

        Le mode compte parce que ce fichier porte chaque valeur d'origine en
        clair : il ré-identifie les copies à lui seul. `os.open` n'applique
        son mode QU'À la création, donc une table arrivée en 0644 par un
        clone, un `cp` ou un `tar -x` le resterait — d'où le `fchmod`.

        L'atomicité compte parce que la table s'écrit APRÈS les copies : une
        interruption laisserait sur le disque une table tronquée au milieu
        d'une chaîne, alors que les fichiers qu'elle seule ré-identifie sont
        déjà livrables. Le fichier suivant du lot échouerait alors à la
        charger, sur un message qui accuse sa source.
        """
        parent = os.path.dirname(os.path.abspath(chemin)) or "."
        os.makedirs(parent, mode=0o700, exist_ok=True)
        descripteur, temporaire = tempfile.mkstemp(
            dir=parent, prefix=".table-", suffix=".part"
        )
        try:
            os.fchmod(descripteur, 0o600)
            with os.fdopen(descripteur, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "version": self.VERSION,
                        "mots": self.mots,
                        "nombres": self.nombres,
                        "entetes": self.entetes,
                    },
                    fh,
                    ensure_ascii=False,
                    indent=1,
                    sort_keys=True,
                )
            os.replace(temporaire, chemin)
            temporaire = None
        finally:
            if temporaire and os.path.exists(temporaire):
                os.unlink(temporaire)

    def en_dict(self):
        return {
            "mots": dict(self.mots),
            "nombres": dict(self.nombres),
            "entetes": {
                nom: list(lignes) for nom, lignes in self.entetes.items()
            },
        }


def nouveau_mot(valeur, table, vivier):
    """Le mot attribué à cette chaîne. Stable dans toute la table.

    Au-delà du vivier, DEUX MOTS APPARIÉS — 1366² fait 1 866 756
    combinaisons — et non `mot_<n>` : la demande était un mot d'un
    dictionnaire, et une sortie numérotée cesse d'en être un exactement au
    moment où le fichier est assez gros pour que ça compte. `mot_<n>` ne
    subsiste qu'en troisième repli, au-delà de 1,8 million de valeurs
    distinctes — jamais atteint par un tableur.
    """
    cle = str(valeur)
    connu = table.mots.get(cle)
    if connu is not None:
        return connu
    taille = len(vivier)
    # Le mot tiré peut ÊTRE la valeur : le vivier est un dictionnaire, et
    # une cellule peut porter un de ses mots. Rendre ce mot compte un
    # remplacement que la copie ne porte pas — la valeur y part en clair.
    # On avance alors d'un rang plutôt que de rendre l'identité.
    # `mots_pris` est indispensable : le saut d'identité seul peut retomber
    # sur un mot DÉJÀ attribué à une autre valeur, et deux clients
    # fusionnent alors sur un seul mot — la RECHERCHEV résout encore, mais
    # sur la mauvaise ligne. Reconstruit au chargement, il vaut pour tout
    # un lot.
    pris = getattr(table, "mots_pris", None)
    if pris is None:
        pris = table.mots_pris = set(table.mots.values())
    n = len(table.mots)
    while True:
        if n < taille:
            mot = vivier[n]
        else:
            rang = n - taille
            gauche, droite = divmod(rang, taille)
            if gauche < taille:
                mot = f"{vivier[gauche]}_{vivier[droite]}"
            else:
                mot = f"mot_{n}"
        if mot != cle and mot not in pris:
            break
        n += 1
    table.mots[cle] = mot
    pris.add(mot)
    return mot


def _bornes_par_signe(valeur, bornes):
    """L'intervalle de tirage, du côté du signe de la valeur.

    Le signe est préservé ET le tirage reste dans l'étendue mesurée : ces
    deux promesses ne tiennent ensemble qu'en découpant l'étendue au zéro.
    Une valeur négative implique que le minimum mesuré l'est aussi, donc le
    sous-intervalle négatif existe toujours quand on en a besoin.
    """
    bas, haut = 0.0, 1000.0
    if bornes:
        # Un troisième terme peut suivre — l'intégralité de la colonne —,
        # que cette fonction ignore : elle ne décide que de l'intervalle.
        mini, maxi = bornes[0], bornes[1]
        if mini is not None and maxi is not None and maxi > mini:
            bas, haut = float(mini), float(maxi)
    if valeur > 0:
        return max(bas, 0.0), haut if haut > 0 else 1000.0
    return (bas if bas < 0 else -1000.0), min(haut, 0.0)


# Essais aléatoires avant de passer au parcours des places. Dix suffisent
# tant que la plage est large ; le parcours tranche quand elle est étroite.
ESSAIS_UNICITE = 10

# Le parcours des places est borné : sur une plage de plusieurs milliers de
# valeurs, l'aléatoire a déjà répondu, et une plage vraiment saturée doit
# s'élargir plutôt que se faire fouiller.
PLACES_PARCOURUES = 8192

# Pas d'agrandissement, une fois la plage saturée. On grandit D'UN PAS à
# la fois, du côté qui s'éloigne du zéro : avec N valeurs dans N places et
# l'interdiction de rendre l'identité, la dernière place libre EST parfois
# l'identité, et la plage se sature sans être trop petite. Un taux qui
# passe de 0,20 à 0,21 reste un taux ; le même élargi dix fois ne l'est
# plus.
PAS_AGRANDIS = 32

# Paliers ×10, dernier recours quand même l'agrandissement ne suffit pas.
PALIERS_ELARGISSEMENT = 5


def _tirer_libre(valeur, rng, bas, haut, entier, pris):
    """Un tirage dans une place LIBRE de l'étendue mesurée.

    Élargir dès le premier échec faisait sortir la valeur de la plage
    mesurée alors qu'elle avait encore des places : une heure de la
    journée devenait 189, un taux dépassait l'unité. L'élargissement n'est
    plus qu'un dernier recours, quand la plage est vraiment saturée.

    La valeur d'origine compte parmi les places prises : un nombre rendu à
    lui-même serait compté et annoncé comme remplacé alors que la copie le
    porte inchangé.
    """
    # La résolution est celle de la COLONNE, jamais celle de la valeur :
    # « 0,2 » en porte une et « 0,15 » deux, et suivre chaque valeur faisait
    # arrondir la plage [0,15 ; 0,20] au dixième — donc sortir par le bas,
    # à 0,1. Les bornes sont mesurées sur toute la colonne, elles sont le
    # bon repère.
    decimales = (
        2
        if entier
        else max(_decimales(bas), _decimales(haut), _decimales(valeur))
    )
    pas = 1 if entier else 10.0**-decimales
    # Une étendue dont le quotient par le pas dépasse le flottant — un
    # nombre au plafond d'Excel dans une colonne à deux décimales —
    # rendait `inf`, et `int(round(inf))` levait. La plage est alors bien
    # trop large pour se faire parcourir : la compter comme telle est la
    # réponse, refuser la copie n'en est pas une.
    etendue = (haut - bas) / pas
    places = (
        int(round(etendue)) + 1
        if math.isfinite(etendue)
        else PLACES_PARCOURUES + 1
    )
    interdit = (valeur,)
    for _ in range(ESSAIS_UNICITE):
        tire = _tirer(valeur, rng, bas, haut, entier, decimales)
        if tire not in pris and tire not in interdit:
            return tire
    if 0 < places <= PLACES_PARCOURUES:
        # Parcourir depuis un point au hasard : sans point de départ
        # aléatoire, une plage étroite se remplirait toujours dans le même
        # ordre et la copie deviendrait devinable.
        depart = rng.randrange(places)
        for decalage in range(places):
            brut = bas + ((depart + decalage) % places) * pas
            candidat = int(brut) if entier else round(brut, decimales)
            if candidat == 0 or candidat in interdit:
                continue
            if candidat not in pris:
                return candidat
        # Saturée : grandir d'un pas à la fois, du côté qui s'éloigne du
        # zéro, plutôt que de multiplier l'étendue par dix.
        vers_le_haut = haut > 0
        for rang in range(1, PAS_AGRANDIS + 1):
            brut = (haut + rang * pas) if vers_le_haut else (bas - rang * pas)
            candidat = int(brut) if entier else round(brut, decimales)
            if candidat == 0 or candidat in interdit:
                continue
            if candidat not in pris:
                return candidat
    for palier in range(1, PALIERS_ELARGISSEMENT + 1):
        facteur = 10**palier
        for _ in range(ESSAIS_UNICITE):
            tire = _tirer(
                valeur,
                rng,
                bas * facteur,
                haut * facteur,
                entier,
                decimales,
            )
            if tire not in pris and tire not in interdit:
                return tire
    # Toutes les places connues sont prises : rendre un doublon vaut mieux
    # que refuser une copie propre — une collision ne fait rien fuir. Mais
    # JAMAIS l'identité : elle laisse la valeur d'origine dans la copie en
    # la comptant comme remplacée, ce qui est une fuite annoncée propre.
    for _ in range(ESSAIS_UNICITE):
        tire = _tirer(valeur, rng, bas, haut, entier, decimales)
        if tire not in interdit:
            return tire
    ecart = 1 if entier else 10.0**-decimales
    return valeur + ecart if valeur > 0 else valeur - ecart


def _decimales(valeur):
    """Le nombre de décimales que porte cette valeur, au plus dix.

    Arrondir tout flottant à deux décimales laissait presque aucune place
    à une colonne plus fine — un taux à sept décimales n'en avait qu'une
    poignée — ce qui saturait la plage et forçait l'élargissement, lequel
    brisait la promesse de rester dans l'étendue mesurée.
    """
    texte = repr(float(valeur))
    if "e" in texte or "E" in texte:
        # `repr` passe en notation exposant sous 1e-4 : compter l'exposant
        # plutôt que rendre 2. Un pas de 0,01 sur une étendue de 1e-7 ne
        # laisse aucune place, et la colonne entière sort de la plage
        # mesurée sur un seul nombre, le même quelle que soit la graine.
        exposant = decimal.Decimal(texte).as_tuple().exponent
        return min(max(-exposant, 2), 17)
    _entier, _point, fraction = texte.partition(".")
    return min(len(fraction.rstrip("0")) or 2, 10)


def _tirer(valeur, rng, bas, haut, entier, decimales=2):
    """Un tirage dans l'intervalle, du même signe que la valeur.

    Un zéro tiré effacerait le signe que la règle promet de garder, et se
    lirait comme une absence de valeur.
    """
    if entier:
        plancher, plafond = int(bas), int(haut)
        if plafond <= plancher:
            plafond = plancher + 1
        tire = rng.randint(plancher, plafond)
        if tire == 0:
            return 1 if valeur > 0 else -1
        return tire
    tire = round(rng.uniform(bas, haut), decimales)
    if tire == 0:
        menu = 10.0**-decimales
        return menu if valeur > 0 else -menu
    return tire


def nouveau_nombre(valeur, rng, bornes=None, table=None):
    """Un nombre du même signe, dans l'étendue MESURÉE de sa colonne.

    « 0 à 1000 » était l'intention, et `anonymize.py` a mesuré que c'est
    faux pour tout nombre qui porte un sens borné : un taux de 0,15 devenu
    743, une année devenue 12, une heure de la journée tirée à 957 qui fait
    lever l'ORM. L'étendue réelle de la colonne l'emporte donc, et 0-1000
    ne sert plus que de repli pour une colonne vide ou constante.

    Zéro reste zéro : il n'a pas de signe à préserver, et un zéro qui
    devient 743 fabrique de la donnée là où il n'y en avait pas.

    `table` donne au nombre l'intégrité référentielle que le texte a déjà :
    sans elle, la même clé de jointure rend un nombre différent à chaque
    ligne, et toute relation d'un export ou d'une base Access se
    désagrège.
    """
    if isinstance(valeur, bool) or valeur is None:
        return valeur
    if valeur == 0:
        return valeur
    # La clé de la table reste celle de la VALEUR : la faire dépendre de
    # la colonne donnerait deux clés à un même nombre vu dans deux
    # colonnes de résolutions différentes, et la jointure qui les relie se
    # désagrégerait.
    cle = f"{'i' if isinstance(valeur, int) else 'f'}:{valeur!r}"
    # Le TIRAGE, lui, suit la colonne. `isinstance` ne peut pas en
    # répondre : le format `.xls` ne stocke que des doubles, si bien que
    # son lecteur rend 100 en `100.0` et que toute colonne d'entiers
    # ressortait décimale — une copie qui ne se réimporte plus dans un
    # champ entier. C'est la même leçon que pour la résolution : le type
    # d'UNE valeur ne dit pas la nature de sa colonne.
    entier = isinstance(valeur, int)
    if bornes is not None and len(bornes) > 2 and bornes[2] is not None:
        entier = bool(bornes[2])
    if table is not None:
        connu = table.nombres.get(cle)
        if connu is not None:
            return connu
    bas, haut = _bornes_par_signe(valeur, bornes)
    # SANS REMISE, comme pour le texte. Le tirage seul collisionne par le
    # paradoxe des anniversaires : mesuré, 100 valeurs distinctes dans une
    # étendue de 100 ne rendent que 66 sorties distinctes. Deux clés
    # primaires qui reçoivent le même nombre font une fixture qui ne se
    # réimporte plus — et c'est justement l'intégrité que la table apporte
    # au texte, refusée en silence aux nombres.
    pris = table.nombres_pris if table is not None else ()
    tire = _tirer_libre(valeur, rng, bas, haut, entier, pris)
    if table is not None:
        table.nombres[cle] = tire
        table.nombres_pris.add(tire)
    return tire


# ----------------------------------------------------------------------
# La portée
# ----------------------------------------------------------------------
def colonne_plancher(
    etiquette,
    forme_identifiant=False,
    forme_relation=False,
    selection=False,
):
    """Vrai si cette colonne porte un identifiant, non un nom.

    Le plancher s'applique AVANT la question des colonnes intactes et
    indépendamment d'elle : sans lui, accepter tous les défauts détruit
    `id`, `partner_id/id` et les relations, pour une entrée dont tout
    l'objet est un jeu de test qui FONCTIONNE.

    Mais le NOM ne suffit pas à décider. `CHAMPS_INTERDITS` vient d'un
    anonymiseur de BASE, où `display_name` est refusé parce que le serveur le
    RECALCULE depuis `name` ; un fichier plat ne recalcule rien, la colonne
    EST la donnée. Et dans un export import-compatible, `partner_id` porte le
    nom affiché de la relation, pas un entier. `forme_identifiant` dit si le
    CONTENU mesuré de la colonne a la forme d'un identifiant ; sans lui, le
    plancher recopie en clair les colonnes les plus identifiantes du fichier
    et l'annonce comme une protection.
    """
    if not etiquette:
        return False
    bas = str(etiquette).strip().lower()
    if not bas:
        return False
    if bas in PLANCHER_STRUCTUREL:
        return True
    if any(bas.endswith(s) for s in SUFFIXES_STRUCTURELS):
        return True
    # Une relation exige la forme d'une CIBLE de relation : un entier, un
    # chemin d'ids, un external ID. Un mot en minuscules n'en est pas une.
    if any(bas.endswith(s) for s in SUFFIXES_IDENTIFIANTS):
        return bool(forme_relation)
    if bas in ETIQUETTES_POINTEES:
        return bool(forme_relation)
    if bas in ETIQUETTES_SELECTION:
        # La forme SEULE accepterait n'importe quel mot minuscule : une
        # colonne de provinces, ou de créneaux nommés par des personnes.
        return bool(forme_identifiant) and bool(selection)
    return False


def cellule_en_portee(feuille, ligne, colonne, options):
    """La portée se décide sur les COORDONNÉES, jamais sur la valeur.

    `feuille` est un nom, `None` hors tableur. `ligne` et `colonne` sont
    des entiers 1-based, comme openpyxl les compte.
    """
    # Une colonne de STRUCTURE : les noms de balise d'un XML, les clés
    # aplaties d'un JSON. Le graveur ne les touche jamais, et les compter
    # comme remplacées désarmait le refus « rien à faire » et brûlait le
    # vivier sur des noms de champ.
    if (feuille, colonne) in (options.get("colonnes_structure") or ()):
        return False
    # Une LIGNE de structure : les clés d'objet, l'étiquette que le lecteur
    # a fabriquée. Rien ne peut l'écrire, donc la compter en portée annonce
    # un remplacement que la copie ne porte pas.
    if (feuille, ligne) in (options.get("lignes_structure") or ()):
        return False
    feuilles = options.get("feuilles")
    if feuilles and feuille is not None and feuille not in feuilles:
        return False
    if not options.get("entetes"):
        # L'ABSENCE de la clé vaut « la ligne 1 est l'en-tête » — le
        # comportement d'avant la mesure. Un appelant qui ne mesure pas
        # (le gabarit d'options des tests de portée ne porte que quelques
        # clés) mettrait sinon la ligne de champs en portée : ses libellés
        # remplacés, la copie illisible, et une RECHERCHEV du destinataire
        # résolue sur la mauvaise ligne.
        #
        # Une clé PRÉSENTE et vide veut dire « cette feuille n'a pas
        # d'en-tête », et sa ligne 1 entre en portée. C'est là qu'une
        # première ligne de DONNÉES cesse d'être recopiée en clair.
        empan = options.get("lignes_entete")
        if empan is None:
            if ligne == 1:
                return False
        elif (feuille, ligne) in empan:
            return False
    etiquette = (options.get("etiquettes") or {}).get((feuille, colonne))
    formes = options.get("formes") or {}
    forme = formes.get((feuille, colonne), False)
    forme_rel = (options.get("formes_relation") or {}).get(
        (feuille, colonne), False
    )
    selection = (options.get("selections") or {}).get(
        (feuille, colonne), False
    )
    if colonne_plancher(etiquette, forme, forme_rel, selection):
        return False
    return not colonne_repondue(feuille, colonne, etiquette, options)


def colonne_repondue(feuille, colonne, etiquette, options):
    """L'opérateur a-t-il demandé de laisser CETTE colonne intacte ?

    Deux ensembles, consultés dans cet ordre : celui de la FEUILLE, puis
    le plat. Le plat était seul, et il est global : répondre « 3 » gelait
    la colonne 3 des dix feuilles d'un classeur. Un écran qui laisse
    cocher la colonne 3 de la septième feuille tiendrait donc une promesse
    fausse — et l'erreur va du mauvais côté, neuf feuilles restant
    sous-anonymisées.

    L'index ne répond QUE pour une colonne sans étiquette. Sinon « 1 »
    désigne à la fois la colonne étiquetée « 1 » et la première colonne,
    et une seule réponse en épargne deux — dont celle des noms, que
    l'aperçu n'annonçait pas.

    Un ÉCRAN, lui, désigne par l'index sans ambiguïté : il tient l'objet
    colonne, il ne tape pas une chaîne. Et l'index est la seule désignation
    qui survit à une correction d'en-tête, qui RENOMME les colonnes —
    répondre par l'étiquette faisait tomber la réponse sur une autre
    colonne, ou sur aucune, en silence. D'où deux ensembles distincts
    plutôt qu'un : des entiers pour l'écran, des chaînes pour l'invite.

    La règle vit ICI et nulle part ailleurs : `_colonnes_ecartees` et
    `_colonnes_saturees` la reprenaient chacune à sa façon, ce qui fait
    trois occasions de divergence.
    """
    par_index = (options.get("colonnes_intactes_index_par_feuille") or {}).get(
        feuille
    )
    if par_index and colonne in par_index:
        return True
    if etiquette is not None and str(etiquette).strip():
        reponse = str(etiquette).strip()
    else:
        reponse = str(colonne)
    par_feuille = (options.get("colonnes_intactes_par_feuille") or {}).get(
        feuille
    )
    if par_feuille and reponse in par_feuille:
        return True
    return reponse in (options.get("colonnes_intactes") or set())


def anonymise_cellule(valeur, options, table, rng, bornes=None):
    """La valeur de remplacement, ou `_INTACTE` si la cellule ne bouge pas.

    L'ordre des tests est la règle elle-même. Chaque garde ferme un piège
    que le suivant ne verrait pas.
    """
    if valeur is None or valeur == "":
        return _INTACTE
    # `isinstance(True, int)` vaut True : sans cette ligne d'abord, toute
    # case à cochée deviendrait un montant.
    if isinstance(valeur, bool):
        return _INTACTE
    # Un document, une pièce jointe : jamais recopié, toujours vidé.
    if isinstance(valeur, (bytes, bytearray)):
        return None
    if isinstance(valeur, str):
        texte = valeur
        if texte.startswith("="):
            return _INTACTE
        if texte in VALEURS_ERREUR:
            return _INTACTE
        if not options.get("texte", True):
            return _INTACTE
        return nouveau_mot(texte, table, options["vivier"])
    if isinstance(valeur, (int, float)):
        if not options.get("nombres", True):
            return _INTACTE
        return nouveau_nombre(valeur, rng, bornes=bornes, table=table)
    # `datetime`, `date`, `time` et tout objet d'un lecteur : intacts. Les
    # tirer au hasard casserait les tris et les échéances.
    return _INTACTE


class _Intacte:
    """Le témoin « cette cellule ne bouge pas ».

    `None` ne peut pas jouer ce rôle : vider une cellule EST une décision
    (une colonne binaire d'Access), et il faut la distinguer de « ne pas y
    toucher ».
    """

    __slots__ = ()

    def __repr__(self):  # pragma: no cover - confort de débogage
        return "INTACTE"


_INTACTE = _Intacte()


def classer(valeur):
    """La famille d'une valeur, pour les comptes du rapport."""
    if valeur is None or valeur == "":
        return "vide"
    if isinstance(valeur, bool):
        return "booleen"
    if isinstance(valeur, (bytes, bytearray)):
        return "binaire"
    if isinstance(valeur, str):
        if valeur.startswith("="):
            return "formule"
        if valeur in VALEURS_ERREUR:
            return "erreur"
        return "texte"
    if isinstance(valeur, (int, float)):
        return "nombre"
    return "date"


# ----------------------------------------------------------------------
# La sérialisation hors tableur
# ----------------------------------------------------------------------
def valeur_hors_tableur(valeur):
    """La valeur telle qu'elle s'écrit en CSV, JSON ou XML.

    Ces trois formats ne portent aucun type d'openpyxl. Sans ce passage,
    un `csv.writer` GRAVE l'adresse mémoire d'un `ArrayFormula` dans le
    fichier — l'objet ne définit pas `__str__` — et `json.dumps` lève sur
    la première date rencontrée.

    Le texte de formule n'est PAS préfixé d'une apostrophe : l'apostrophe
    n'est pas une échappe CSV, `csv.reader` la rend dans la valeur.
    """
    if valeur is None:
        return None
    if isinstance(valeur, bool):
        return valeur
    if isinstance(valeur, (int, float, str)):
        return valeur
    texte = getattr(valeur, "text", None)
    if isinstance(texte, str):
        return texte
    iso = getattr(valeur, "isoformat", None)
    if callable(iso):
        return iso()
    return str(valeur)


def nom_de_fichier_sur(nom, pris, maximum=None):
    """Un nom de feuille ou de table, rendu sûr comme nom de fichier.

    `pris` est l'ensemble des noms déjà attribués : deux feuilles qui se
    réduisent au même après nettoyage doivent rester deux fichiers.

    `maximum` borne la longueur — un onglet Excel n'en accepte que 31.
    La coupe vient AVANT l'unicité, et le candidat suffixé est revérifié :
    unicifier d'abord puis couper faisait retomber deux noms distincts sur
    le même, et le classeur perdait une feuille en silence.
    """
    propre = re.sub(r"[^A-Za-z0-9._-]", "_", str(nom or ""))
    propre = propre.strip("_")
    if not propre or set(propre) <= {"_", ".", "-"}:
        propre = f"feuille_{len(pris) + 1}"
    if maximum:
        propre = propre[:maximum].rstrip("._-") or f"feuille_{len(pris) + 1}"
    candidat = propre
    suffixe = 1
    while candidat in pris:
        suffixe += 1
        marque = f"_{suffixe}"
        base = propre[: maximum - len(marque)] if maximum else propre
        candidat = f"{base}{marque}"
    pris.add(candidat)
    return candidat


# Un nombre écrit en toutes lettres décimales, et rien d'autre. Le motif
# REFUSE délibérément : les zéros de tête (« 007 » est un code, pas une
# quantité, et le tourner en 7 lui ôte son sens), la notation
# exponentielle, « NaN » et « inf » — que `float()` accepte pourtant — et
# les séparateurs de milliers.
_NOMBRE_TEXTE = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")


def coercer_texte(valeur):
    """Le type d'un champ qui arrive en chaîne faute de mieux.

    `csv.reader` ne rend QUE des chaînes, et un attribut XML non plus n'a
    pas de type. Sans ce passage, une colonne de montants est vue comme du
    texte : chaque montant devient un mot, la colonne perd ses bornes, et
    le fichier produit ne se réimporte plus ni ne s'additionne — ce qui
    vide de son sens un jeu de test.

    Le doute profite à la chaîne : ce qui n'est pas franchement un nombre
    en reste une, et reçoit un mot.
    """
    if not isinstance(valeur, str):
        return valeur
    texte = valeur.strip()
    if not texte or not _NOMBRE_TEXTE.fullmatch(texte):
        return valeur
    return float(texte) if "." in texte else int(texte)


# La vérification ne regarde pas les chaînes trop courtes : « 12 » ou « ok »
# apparaissent dans n'importe quel XML de conteneur et noieraient le signal.
LONGUEUR_VERIFIABLE = 4

# Le socle du graveur, lu une seule fois.
_SOCLE = None


def valeurs_a_verifier(table):
    """Les chaînes que le moteur a DIT avoir remplacées.

    `table.mots` est exactement l'ensemble des valeurs texte vues EN
    PORTÉE : `nouveau_mot` n'est appelé nulle part ailleurs. Une de ces
    valeurs qui subsiste dans la copie est donc une fuite sans ambiguïté —
    le moteur a annoncé son remplacement et une copie en a survécu
    ailleurs, dans un cache, un nom de colonne de tableau ou une feuille
    qu'on croyait retirée.

    Ce qui est hors portée n'est PAS regardé ici : ces valeurs restent par
    décision, et c'est `colonnes_ecartees` et `entete_gardee` qui les
    nomment à l'écran. Les mêler ici rendrait la garde bruyante au point
    d'être désactivée, ce qui est la seule manière de la rendre inutile.
    """
    return {
        valeur
        for valeur in table.mots
        if isinstance(valeur, str)
        and len(valeur.strip()) >= LONGUEUR_VERIFIABLE
    }


def _socle_du_graveur():
    """Le texte que le graveur écrit TOUJOURS, quel que soit le contenu.

    Un classeur vide porte déjà « Microsoft », « Calibri », « Normal »,
    « office ». Sans ce socle, une cellule qui porte un de ces mots refuse
    la copie pour toujours, en nommant une partie sur laquelle l'opérateur
    ne peut rien. Compter les occurrences EN SURPLUS du socle garde le
    balayage aveugle aux vecteurs sans le rendre inutilisable.
    """
    global _SOCLE
    if _SOCLE is not None:
        return _SOCLE
    _SOCLE = {}
    try:
        import openpyxl
    except ImportError:
        return _SOCLE
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as dossier:
            temoin = os.path.join(dossier, "socle.xlsx")
            openpyxl.Workbook().save(temoin)
            with zipfile.ZipFile(temoin) as archive:
                for nom in archive.namelist():
                    _SOCLE[nom] = archive.read(nom).decode("utf-8", "ignore")
    except (OSError, zipfile.BadZipFile):
        _SOCLE = {}
    return _SOCLE


# Le texte d'un nœud XML, et la valeur d'un attribut. Une valeur de cellule
# vit TOUJOURS dans l'un des deux : le balisage ne peut pas la traverser.
_TEXTE_XML = re.compile(r">([^<>]+)<")
_ATTRIBUT_XML = re.compile(r"=\"([^\"]*)\"|='([^']*)'")


def _est_xml(nom, brut):
    """Cette partie est-elle du XML ?

    C'est la NATURE de la partie qui doit décider de la matière fouillée,
    jamais le fait que deux expressions y aient capturé quelque chose. Un
    seul couple « > … < » dans un fichier plat — un fragment HTML dans une
    colonne gardée suffit — ramenait sinon le balayage à ce qui les sépare,
    et toute valeur hors de cet intervalle sortait sans refus.
    """
    if nom.endswith((".xml", ".rels", ".vml")):
        return True
    # Le préfixe seulement : une partie fait plusieurs mégaoctets, et
    # `brut.lstrip()` la recopierait à chaque appel. Le BOM est dans
    # l'ensemble à retirer, pour qu'un XML qui en porte reste reconnu.
    tete = brut[:512].lstrip("\ufeff \t\r\n")
    return tete.startswith("<?xml") or tete.startswith("<")


def _chaines_distinctes(brut):
    """Quatre ensembles : tout, puis les seuls NŒUDS DE TEXTE.

    Le balayage cherchait chaque valeur dans le document entier, où elle
    est justement absente : un classeur de cent mille cellules fait dix
    mégaoctets, et cent mille recherches infructueuses dessus ne finissent
    pas. Or l'anonymisation ramène le contenu à quelques milliers de mots :
    la matière DISTINCTE tient en quelques kilooctets.

    Dans une partie XML, rien n'est perdu : une valeur de cellule vit
    toujours dans un nœud de texte ou une valeur d'attribut, le balisage ne
    pouvant pas la traverser. Les parties qui ne sont PAS du XML — un
    binaire, un projet VBA, un fichier plat — ne passent pas ici du tout,
    voir `_matiere`.

    La forme écrite et la forme déséchappée sont rendues SÉPARÉMENT :
    mêlées dans un seul ensemble, une même chaîne portant « & » s'y compte
    deux fois, et le total des occurrences dépasse alors la tolérance
    annoncée — un refus sur du travail légitime.

    Les nœuds de texte sont rendus À PART parce qu'une valeur PUREMENT
    numérique ne peut pas se chercher dans un attribut : un XML y porte
    ses index de ligne, de style et ses compteurs, si bien que tout
    nombre à quatre chiffres se retrouve dans `<row r="1203">` d'une
    feuille de plus de mille lignes. Une valeur de cellule, elle, vit
    dans un nœud de texte — `<v>` —, donc restreindre la recherche là
    n'abandonne rien de ce que le filet doit voir. Énumérer plutôt les
    attributs de structure serait à refaire au premier format inconnu.
    """
    ecrites = set()
    nues = set()
    texte_ecrites = set()
    texte_nues = set()

    def ajouter(morceau, noeud_de_texte):
        # Un `.xlsx` est un zip de XML : la valeur y est ÉCHAPPÉE.
        # Chercher les octets bruts d'un nom portant « & », « < » ou « > »
        # n'y trouve rien, et la copie part avec.
        nu = html.unescape(morceau) if "&" in morceau else morceau
        ecrites.add(morceau)
        nues.add(nu)
        if noeud_de_texte:
            texte_ecrites.add(morceau)
            texte_nues.add(nu)

    for morceau in _TEXTE_XML.findall(brut):
        ajouter(morceau, True)
    for double, simple in _ATTRIBUT_XML.findall(brut):
        for morceau in (double, simple):
            if morceau:
                ajouter(morceau, False)
    return ecrites, nues, texte_ecrites, texte_nues


def _matiere(nom, brut, reductible=True):
    """Quatre blocs : écrit, déséchappé, puis les mêmes en TEXTE seul.

    Du XML se réduit à ses chaînes distinctes ; tout le reste est fouillé
    ENTIER.

    Sur une partie qui n'est pas du XML, les deux derniers blocs sont les
    deux premiers : un champ de csv est de la donnée où qu'il soit, et
    l'y restreindre aveuglerait le filet sur le format le plus simple.

    `reductible=False` pour une copie PLATE : elle est UNE seule partie, la
    réduire n'achète rien, et le contenu ne peut pas décider de la
    couverture. Un export d'ERP qui est du HTML sous une extension `.csv`
    ou `.txt` commence par « < » et passerait pour du XML : le balayage se
    réduirait alors au premier nœud, et tout le reste du fichier sortirait
    sans refus.
    """
    if reductible and _est_xml(nom, brut):
        ecrites, nues, t_ecrites, t_nues = _chaines_distinctes(brut)
        return (
            _joindre(ecrites),
            _joindre(nues),
            _joindre(t_ecrites),
            _joindre(t_nues),
        )
    # Un graveur de fichier plat ÉCHAPPE : `csv` double le guillemet d'une
    # valeur qui en porte un, `json.dump` le préfixe d'une barre oblique.
    # Chercher les octets bruts d'un nom portant un guillemet n'y trouvait
    # alors rien. On déchiffre le FOIN une fois, plutôt que de réencoder
    # chaque aiguille — les parties d'un zip restent intactes.
    vues = {brut}
    if "&" in brut:
        vues.add(html.unescape(brut))
    if '""' in brut:
        vues.add(brut.replace('""', '"'))
    if "\\" in brut:
        vues.add(
            brut.replace('\\"', '"').replace("\\/", "/").replace("\\\\", "\\")
        )
    tout = _joindre(vues)
    return brut, tout, brut, tout


# Le préfiltre : un bit par empreinte de n-gramme. 2^22 bits font 512 Kio,
# quelle que soit la taille du document. Il ne rend JAMAIS de faux négatif —
# c'est ce qui autorise à s'y fier pour écarter une valeur — et ses faux
# positifs retombent sur le comptage exact, qui tranche.
_BITS_PREFILTRE = 1 << 22
_MASQUE_PREFILTRE = _BITS_PREFILTRE - 1

# En deçà, le comptage direct est déjà plus rapide que la construction du
# préfiltre. Le seuil n'est pas un réglage fin : il sépare « quelques
# centaines de valeurs » de « des dizaines de milliers ».
SEUIL_PREFILTRE = 2000


def _prefiltre(bloc):
    """Les empreintes des n-grammes du bloc, en bitmap.

    Le balayage cherche des dizaines de milliers de valeurs dans un
    document où elles sont justement ABSENTES : chaque recherche parcourt
    tout le bloc pour ne rien trouver, et le coût est le produit des deux
    tailles. Une valeur ne peut apparaître que si son premier n-gramme
    apparaît ; le vérifier coûte un accès, et écarte presque tout.
    """
    bits = bytearray(_BITS_PREFILTRE >> 3)
    taille = LONGUEUR_VERIFIABLE
    for depart in range(len(bloc) - taille + 1):
        empreinte = hash(bloc[depart : depart + taille]) & _MASQUE_PREFILTRE
        bits[empreinte >> 3] |= 1 << (empreinte & 7)
    return bits


def _peut_contenir(bits, valeur):
    """Faux si la valeur ne peut PAS être dans le bloc. Jamais l'inverse."""
    if bits is None or len(valeur) < LONGUEUR_VERIFIABLE:
        return True
    empreinte = hash(valeur[:LONGUEUR_VERIFIABLE]) & _MASQUE_PREFILTRE
    return bool(bits[empreinte >> 3] & (1 << (empreinte & 7)))


def _joindre(chaines):
    """Un bloc unique, les chaînes séparées par un octet nul.

    L'octet nul n'apparaît dans aucun document : il empêche une valeur de
    se former à cheval sur deux chaînes voisines, ce qu'une simple
    concaténation permettrait. Trié pour que deux exécutions rendent le
    même bloc.
    """
    return "\x00".join(sorted(c for c in chaines if c))


_MOTIF_TOUT_CHIFFRE = re.compile(r"^[0-9]+$")


def _motif_borne(valeur):
    """Le motif d'une valeur PUREMENT numérique, ou None.

    Une valeur de chiffres est indiscernable, en sous-chaîne, des chiffres
    qui vivent légitimement ailleurs : un code postal « 0512 » se retrouve
    dans l'identifiant 10512, « 1081 » dans 10815. Sur une base ordinaire
    cela suffit : seize valeurs faisaient refuser une copie saine, sans
    qu'aucune ne fuie.

    Le remède n'affaiblit rien : une VRAIE survivance est bordée de ce qui
    n'est pas un chiffre — `>0512<`, `"0512"` —, donc elle est toujours
    vue. Ce qui cesse de compter est la valeur courte NOYÉE dans un nombre
    plus long, qui n'en est jamais une occurrence.

    Bordent : les chiffres, les LETTRES et le point. Les lettres, parce
    qu'un attribut de référence de cellule — `r="A1010"` — met un numéro
    de LIGNE à côté d'une lettre de colonne, et que la feuille de plus de
    mille lignes fait alors refuser toute valeur à quatre chiffres ; plus
    généralement, des chiffres collés à une lettre font un seul jeton, et
    une vraie survivance porterait la lettre dans sa valeur. Le point,
    parce que « 1203 » dans 1203,5 est un autre nombre.

    Ne bordent PAS : la virgule, qui SÉPARE les champs d'un csv — l'y
    mettre aveuglait le filet sur le format le plus simple, là où un
    séparateur de milliers coupe déjà la suite de chiffres et ne pose donc
    pas le problème qu'on croyait. Ni le signe moins : mêmes chiffres, et
    refuser est le côté sur lequel pencher.
    """
    if _MOTIF_TOUT_CHIFFRE.match(valeur):
        return re.compile(r"(?<![\w.])%s(?![\w.])" % re.escape(valeur))
    # Une valeur qui porte des lettres se borne aussi, mais par les seuls
    # caractères de mot : « Document » vit dans l'URI `officeDocument` que
    # tout classeur écrit, et le socle du graveur ne l'excuse pas — il est
    # MINIMAL, si bien que chaque type de partie que la source a en plus
    # apporte une URI distincte de plus. Le point ne borne pas ici : il
    # suit un mot en fin de phrase sans en faire un autre mot.
    return re.compile(r"(?<!\w)%s(?!\w)" % re.escape(valeur))


def _compter(texte, valeur, motif):
    """Les occurrences de `valeur`, bornées quand elle est numérique.

    `str.count` reste le chemin rapide et sert de préfiltre : il ne peut
    pas manquer une occurrence, seulement en compter de trop. Le motif ne
    se paie donc que là où il y a quelque chose à départager.
    """
    compte = texte.count(valeur)
    if not compte or motif is None:
        return compte
    return len(motif.findall(texte))


def survivances(chemin, valeurs, tolerees=()):
    """{valeur: [parties du fichier]} pour ce qui subsiste dans la copie.

    Un `.xlsx` est un zip : on balaie CHAQUE partie, sans en nommer aucune.
    Nommer les parties une à une est ce qui a laissé passer, tour à tour, le
    cache d'un graphique, un titre d'axe, un hyperlien de cellule et le nom
    d'une colonne de tableau.

    On compare des OCCURRENCES et non une appartenance : la portée se décide
    par cellule, le balayage ne sait lire que le fichier, et une valeur qui
    ne subsiste QUE dans ce que le moteur a annoncé garder n'est pas une
    fuite. Le grain est la chaîne distincte — une fuite ajoute toujours une
    chaîne que le socle n'a pas.
    """
    if not valeurs:
        return {}
    morceaux = []
    try:
        socle = _socle_du_graveur()
        with zipfile.ZipFile(chemin) as archive:
            for nom in archive.namelist():
                brut = archive.read(nom).decode("utf-8", "ignore")
                morceaux.append(
                    (
                        nom,
                        _matiere(nom, brut),
                        _matiere(nom, socle.get(nom, "")),
                    )
                )
    except (zipfile.BadZipFile, OSError):
        try:
            with open(chemin, "rb") as fh:
                brut = fh.read().decode("utf-8", "ignore")
        except OSError:
            return {}
        nom_plat = os.path.basename(chemin)
        morceaux.append(
            (
                nom_plat,
                _matiere(nom_plat, brut, reductible=False),
                ("", "", "", ""),
            )
        )
    bloc_garde = _joindre(tolerees)
    # L'appartenance à un bloc joint est un test de SOUS-CHAÎNE : toute
    # chaîne tolérée qui CONTIENT la valeur la tolérait, y compris une
    # valeur qui fuit ailleurs. Le saut ne vaut donc que pour l'ÉGALITÉ ;
    # le reste retourne au comptage d'occurrences, qui compare ce que la
    # copie porte à ce que le moteur a annoncé.
    tolerees_exactes = {str(g) for g in tolerees if g}
    # Le préfiltre ne se paie que quand il rapporte.
    assez = len(valeurs) >= SEUIL_PREFILTRE
    bits_garde = _prefiltre(bloc_garde) if assez else None
    filtres = [
        (
            nom,
            paire,
            paire_socle,
            _prefiltre("\x00".join(paire)) if assez else None,
        )
        for nom, paire, paire_socle in morceaux
    ]

    trouvees = {}
    for valeur in valeurs:
        # `str.count` est du C : c'est ce qui rend le balayage tenable.
        # Une boucle Python sur les chaînes coûtait cinquante secondes pour
        # vingt mille valeurs, là où le compte sur un bloc joint en prend
        # une fraction — même travail, même grain.
        # Annoncée gardée À L'IDENTIQUE : ce n'est pas une fuite, où
        # qu'elle reparaisse. Une cellule hors portée, un titre de feuille,
        # un littéral de formule sont déjà dans la copie en clair, et une
        # occurrence de plus ne divulgue rien de neuf — c'est ce que le
        # comptage par occurrence refusait à tort.
        if valeur in tolerees_exactes:
            continue
        motif = _motif_borne(valeur)
        # Tolérée seulement comme PARTIE d'une chaîne annoncée : le compte
        # tranche, sinon une chaîne gardée qui contient la valeur la
        # couvrirait même là où elle fuit.
        excuses = (
            _compter(bloc_garde, valeur, motif)
            if _peut_contenir(bits_garde, valeur)
            else 0
        )
        vus = 0
        parties = []
        for nom, paire, paire_socle, bits in filtres:
            if not _peut_contenir(bits, valeur):
                continue
            # Le MAX des deux vues, jamais leur somme : une même chaîne
            # portant « & » apparaît dans les deux, et l'additionner
            # gonflait le compte au-delà de la tolérance annoncée.
            # Une valeur de chiffres n'est cherchée que dans les nœuds
            # de texte, où vit une valeur de cellule ; ailleurs, partout.
            vues = paire[2:] if motif is not None else paire[:2]
            compte = max(_compter(v, valeur, motif) for v in vues)
            if not compte:
                continue
            vus += compte
            # EN SURPLUS du socle : « Normal » que le graveur écrit
            # toujours dans `xl/styles.xml` n'est pas une fuite ; une
            # seconde occurrence en est une.
            # Le socle se compte par les MÊMES vues et la même règle de
            # bornes : comparer un compte borné à un compte non borné
            # laisserait l'excuse et l'occurrence parler de choses
            # différentes.
            socle_vues = (
                paire_socle[2:] if motif is not None else paire_socle[:2]
            )
            excuses += max(_compter(v, valeur, motif) for v in socle_vues)
            if nom not in parties:
                parties.append(nom)
        if vus > excuses:
            trouvees[valeur] = parties
    return trouvees


def verifier_copie(fichiers, table, gardees=()):
    """Relire les octets écrits, et refuser la copie qui porte la source.

    C'est un filet, non la règle : les règles décident ce qu'on remplace,
    et cette fonction constate ce qui est SORTI. Sa valeur est de ne
    dépendre d'aucune énumération de vecteurs — un endroit du format que
    personne n'a pensé à nettoyer produit un refus, là où une liste de
    parties à vérifier produirait un silence.

    `gardees` est ce que le moteur conserve SCIEMMENT et a annoncé : noms de
    feuille, plages nommées, littéraux de formule, clés d'objet, noms de
    balise. Tout le reste qui subsiste est un refus.

    Rend (survivances non annoncées, nombre de valeurs non regardées).
    """
    valeurs = valeurs_a_verifier(table)
    tolerees = {str(g) for g in gardees if isinstance(g, str) and g.strip()}
    # Un mot du vivier attribué à une AUTRE valeur reparaît dans la copie
    # comme remplacement, non comme survivance. `cle != mot` garde le cas de
    # l'identité — une valeur rendue à elle-même — comme un refus.
    tolerees.update(
        str(mot)
        for cle, mot in getattr(table, "mots", {}).items()
        if isinstance(mot, str) and str(cle) != str(mot)
    )
    # Le même raisonnement pour les NOMBRES, qui n'en bénéficiaient pas :
    # un nombre tiré pour une colonne peut égaler, chiffre pour chiffre,
    # une valeur texte d'une autre colonne — un identifiant tiré à 10785
    # et un code postal « 10785 ». Sa présence est expliquée par le
    # tirage, non par une survivance, et sans cette ligne une copie saine
    # se faisait refuser.
    tolerees.update(
        str(nombre)
        for cle, nombre in (getattr(table, "nombres", {}) or {}).items()
        if str(cle) != str(nombre)
    )
    # AUCUNE troncature, et pas de plafond. `candidates[:N]` d'une liste
    # TRIÉE fait suivre la couverture à l'alphabet plutôt qu'au risque : de
    # trois colonnes de texte, seule la première est relue, de façon
    # déterministe, donc une reprise n'y change rien — et l'écran annonce
    # une écriture propre. Le coût que ce plafond épargnait est de l'ordre
    # de six secondes pour 24 000 valeurs sur neuf parties.
    candidates = sorted(valeurs)
    ecartees = 0
    fuites = {}
    for fichier in fichiers:
        if not fichier or not os.path.isfile(fichier):
            continue
        for valeur, parties in survivances(
            fichier, set(candidates), tolerees
        ).items():
            fuites.setdefault(valeur, []).extend(
                f"{os.path.basename(fichier)}:{p}" for p in parties
            )
    return fuites, ecartees


# Les types déclarés d'Access dont la valeur arrive en CHAÎNE. Comme pour
# `.xls`, c'est le TYPE qui décide et jamais la forme de la valeur : une
# colonne de texte peut légitimement porter « AAAA-MM-JJ hh:mm:ss », et la
# convertir en date la mettrait hors d'atteinte de la règle du texte.
ACCESS_DATETIME = 8
ACCESS_MONETAIRE = frozenset({5, 16})

_MOTIF_DATE_ACCESS = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})"
)


def normaliser_access(valeur, type_colonne):
    """La valeur d'une cellule Access, ramenée aux types de la règle.

    `access-parser` rend une date par `str(datetime)` et un montant par sa
    représentation localisée (« $1,995.50 ») : sans cette normalisation,
    une colonne de dates et une colonne monétaire sont vues comme du
    texte, chaque valeur devient un mot, la colonne perd ses bornes, et la
    copie ne se réimporte plus.
    """
    if not isinstance(valeur, str):
        return valeur
    texte = valeur.strip()
    if not texte:
        return None
    if type_colonne == ACCESS_DATETIME:
        # Le marqueur d'Access pour une date qu'il ne sait pas représenter.
        # Il ne porte aucune donnée : la vider vaut mieux que la remplacer
        # par un mot, qui la ferait passer pour du texte du client.
        if texte == "(Invalid Date)":
            return None
        trouve = _MOTIF_DATE_ACCESS.fullmatch(texte)
        if not trouve:
            return None
        try:
            return datetime.datetime(*(int(g) for g in trouve.groups()))
        except ValueError:
            return None
    if type_colonne in ACCESS_MONETAIRE:
        # `eE+` sont gardés : la branche scientifique de la bibliothèque
        # rend « 3.24e+01 », et retirer l'exposant en faisait 3,2401.
        nu = re.sub(r"[^0-9.,()eE+-]", "", texte)
        negatif = nu.startswith("(") and nu.endswith(")")
        nu = nu.strip("()").replace(",", "")
        try:
            nombre = float(nu)
        except ValueError:
            return valeur
        if "." not in nu:
            # `access-parser` a DEUX sorties pour une colonne monétaire.
            # Reconnaît-il le format de la colonne, il place le point
            # décimal et rend « $14.00 » ; ne le reconnaît-il pas, il rend
            # l'entier de stockage TEL QUEL — et Access garde un Currency
            # en entier multiplié par dix mille. Un fret de 47,42 arrivait
            # donc à 474200, la colonne prenait des bornes gonflées de
            # quatre ordres de grandeur, et la copie portait un fret à six
            # chiffres. Les deux formes cohabitent dans un même fichier.
            #
            # Le point décimal tranche sans deviner : toutes les branches
            # qui aboutissent en insèrent un, celle qui renonce n'en met
            # pas. Le diviseur est celui de la bibliothèque, qui coupe les
            # quatre derniers chiffres.
            nombre /= 10000.0
        return -nombre if negatif else nombre
    return valeur


def normaliser_xls(ctype, valeur, datemode):
    """La valeur d'une cellule `.xls`, ramenée aux types de la règle.

    `xlrd` porte le type dans `ctype` et non dans la valeur : sans cette
    normalisation, une date sort en flottant, un booléen en entier, une
    cellule vide en chaîne vide, et une erreur en ENTIER — et les règles du
    nombre et du texte les prennent pour ce qu'ils ne sont pas.
    """
    if ctype in (0, 6):
        return None
    if ctype == 3:
        from xlrd.xldate import xldate_as_datetime

        return xldate_as_datetime(valeur, datemode)
    if ctype == 4:
        return bool(valeur)
    if ctype == 5:
        return CODES_ERREUR_XLS.get(valeur, "#N/A")
    return valeur


def main(
    argv=None,
):  # pragma: no cover - couvert par les tests de bout en bout
    """Le point d'entrée. stdout ne porte QUE l'objet JSON du résultat."""
    from script.data import external_file_formats as formats

    analyseur = argparse.ArgumentParser(add_help=True)
    analyseur.add_argument("--report", metavar="CHEMIN")
    analyseur.add_argument("--plan", metavar="CHEMIN")
    analyseur.add_argument("--apply", metavar="CHEMIN")
    analyseur.add_argument("--out", metavar="CHEMIN")
    analyseur.add_argument("--options", metavar="JSON", default="{}")
    analyseur.add_argument("--table", metavar="CHEMIN")
    analyseur.add_argument("--capabilities", action="store_true")
    args = analyseur.parse_args(argv)

    def rendre(objet, code=0):
        # `allow_nan=False` : json.dump émet sinon « NaN » et « Infinity »
        # nus, que la norme JSON interdit. L'appelant les relirait — Python
        # les accepte — mais tout autre lecteur du résultat le refuserait,
        # et le moteur aurait écrit un document non conforme en annonçant
        # un succès. Mieux vaut lever ici, là où la cause est visible.
        json.dump(objet, sys.stdout, ensure_ascii=False, allow_nan=False)
        sys.stdout.write("\n")
        return code

    def echec(cle, detail="", conseil=""):
        objet = {"erreur": ERREURS.get(cle, cle), "detail": detail}
        if conseil:
            objet["conseil"] = conseil
        return rendre(objet, 1)

    if args.capabilities:
        return rendre(formats.capabilities())

    chemin = args.report or args.plan or args.apply
    if not chemin:
        return echec("format_inconnu", "")
    souci = verifier_source(chemin)
    if souci:
        return echec(souci, chemin)

    try:
        if args.report:
            return rendre(formats.report(chemin))
        options = json.loads(args.options or "{}")
        options["table_chemin"] = args.table
        if args.plan:
            return rendre(formats.plan(chemin, options))
        if not args.out:
            return echec("format_inconnu", "--out")
        return rendre(formats.ecrire(chemin, args.out, options))
    except formats.ErreurMoteur as exc:
        return echec(exc.cle, exc.detail, getattr(exc, "conseil", ""))
    except Exception as exc:  # pragma: no cover - filet de dernier recours
        import traceback

        traceback.print_exc(file=sys.stderr)
        return echec("format_inconnu", f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
