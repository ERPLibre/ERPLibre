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
import csv
import json
import os
import re
import sys
import tempfile
import unicodedata
import zipfile

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.analyse.anonymize import (  # noqa: E402
    CHAMPS_INTERDITS,
    MOTS_PAR_DEFAUT,
)

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
    "table_source": "The mapping table would overwrite the source"
    " or the copy; nothing was written.",
    "fuite_detectee": "A source value survives in the copy;"
    " nothing was written: ",
    "lecture_impossible": "The library here cannot read this workbook: ",
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
ETIQUETTES_SOUS_CONDITION = frozenset(CHAMPS_INTERDITS) - PLANCHER_STRUCTUREL

# Un chemin d'identifiants Odoo, une valeur de sélection, un external ID.
_MOTIF_CHEMIN_ID = re.compile(r"[0-9]+(?:/[0-9]+)*/?")
_MOTIF_SELECTION = re.compile(r"[a-z0-9_]+")
_MOTIF_ID_TEXTE = re.compile(r"[A-Za-z0-9_.]+(?:,[A-Za-z0-9_.]+)*")


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
    return bool(_MOTIF_ID_TEXTE.fullmatch(texte)) and "." in texte


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

    VERSION = 1

    def __init__(self, mots=None, nombres=None):
        self.mots = dict(mots or {})
        self.nombres = dict(nombres or {})

    @classmethod
    def charger(cls, chemin):
        if not chemin or not os.path.isfile(chemin):
            return cls()
        with open(chemin, "r", encoding="utf-8") as fh:
            brut = json.load(fh)
        return cls(brut.get("mots"), brut.get("nombres"))

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
        return {"mots": dict(self.mots), "nombres": dict(self.nombres)}


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
    n = len(table.mots)
    taille = len(vivier)
    if n < taille:
        mot = vivier[n]
    else:
        rang = n - taille
        gauche, droite = divmod(rang, taille)
        if gauche < taille:
            mot = f"{vivier[gauche]}_{vivier[droite]}"
        else:
            mot = f"mot_{n}"
    table.mots[cle] = mot
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
        mini, maxi = bornes
        if mini is not None and maxi is not None and maxi > mini:
            bas, haut = float(mini), float(maxi)
    if valeur > 0:
        return max(bas, 0.0), haut if haut > 0 else 1000.0
    return (bas if bas < 0 else -1000.0), min(haut, 0.0)


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
    entier = isinstance(valeur, int)
    cle = f"{'i' if entier else 'f'}:{valeur!r}"
    if table is not None:
        connu = table.nombres.get(cle)
        if connu is not None:
            return connu
    bas, haut = _bornes_par_signe(valeur, bornes)
    if entier:
        plancher, plafond = int(bas), int(haut)
        if plafond <= plancher:
            plafond = plancher + 1
        tire = rng.randint(plancher, plafond)
        if tire == 0:
            # Un zéro tiré effacerait le signe que la règle promet de
            # garder, et se lirait comme une absence de valeur.
            tire = 1 if valeur > 0 else -1
    else:
        tire = round(rng.uniform(bas, haut), 2)
        if tire == 0:
            tire = 0.01 if valeur > 0 else -0.01
    if table is not None:
        table.nombres[cle] = tire
    return tire


# ----------------------------------------------------------------------
# La portée
# ----------------------------------------------------------------------
def colonne_plancher(etiquette, forme_identifiant=False):
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
    if not forme_identifiant:
        return False
    if any(bas.endswith(s) for s in SUFFIXES_IDENTIFIANTS):
        return True
    return bas in ETIQUETTES_SOUS_CONDITION


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
    feuilles = options.get("feuilles")
    if feuilles and feuille is not None and feuille not in feuilles:
        return False
    if ligne == 1 and not options.get("entetes"):
        return False
    etiquette = (options.get("etiquettes") or {}).get((feuille, colonne))
    forme = (options.get("formes") or {}).get((feuille, colonne), False)
    if colonne_plancher(etiquette, forme):
        return False
    intactes = options.get("colonnes_intactes") or set()
    if etiquette is not None:
        # L'index ne répond QUE pour une colonne sans étiquette. Sinon « 1 »
        # désigne à la fois la colonne étiquetée « 1 » et la première
        # colonne, et une seule réponse en épargne deux — dont celle des
        # noms, que l'aperçu n'annonçait pas.
        return str(etiquette).strip() not in intactes
    return str(colonne) not in intactes


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


def nom_de_fichier_sur(nom, pris):
    """Un nom de feuille ou de table, rendu sûr comme nom de fichier.

    `pris` est l'ensemble des noms déjà attribués : deux feuilles qui se
    réduisent au même après nettoyage doivent rester deux fichiers.
    """
    propre = re.sub(r"[^A-Za-z0-9._-]", "_", str(nom or ""))
    propre = propre.strip("_")
    if not propre or set(propre) <= {"_", ".", "-"}:
        propre = f"feuille_{len(pris) + 1}"
    candidat = propre
    suffixe = 1
    while candidat in pris:
        suffixe += 1
        candidat = f"{propre}_{suffixe}"
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

# Au-delà, la vérification dit ce qu'elle n'a pas pu regarder. Un plafond
# muet se lirait comme « rien ne fuit ».
MAX_VALEURS_VERIFIEES = 20000


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


def survivances(chemin, valeurs):
    """{valeur: [parties du fichier]} pour ce qui subsiste dans la copie.

    Un `.xlsx` est un zip : on balaie CHAQUE partie, sans en nommer aucune.
    Nommer les parties une à une est ce qui a laissé passer, tour à tour, le
    cache d'un graphique, un titre d'axe, un hyperlien de cellule et le nom
    d'une colonne de tableau.
    """
    if not valeurs:
        return {}
    morceaux = []
    try:
        with zipfile.ZipFile(chemin) as archive:
            for nom in archive.namelist():
                morceaux.append(
                    (nom, archive.read(nom).decode("utf-8", "ignore"))
                )
    except (zipfile.BadZipFile, OSError):
        try:
            with open(chemin, "rb") as fh:
                morceaux.append(
                    (
                        os.path.basename(chemin),
                        fh.read().decode("utf-8", "ignore"),
                    )
                )
        except OSError:
            return {}
    trouvees = {}
    for valeur in valeurs:
        for nom, texte in morceaux:
            if valeur in texte:
                trouvees.setdefault(valeur, []).append(nom)
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
    tolerees = {str(g).strip() for g in gardees if isinstance(g, str)}
    candidates = sorted(valeurs - tolerees)
    ecartees = 0
    if len(candidates) > MAX_VALEURS_VERIFIEES:
        ecartees = len(candidates) - MAX_VALEURS_VERIFIEES
        candidates = candidates[:MAX_VALEURS_VERIFIEES]
    fuites = {}
    for fichier in fichiers:
        if not fichier or not os.path.isfile(fichier):
            continue
        for valeur, parties in survivances(fichier, set(candidates)).items():
            fuites.setdefault(valeur, []).extend(
                f"{os.path.basename(fichier)}:{p}" for p in parties
            )
    return fuites, ecartees


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

    def echec(cle, detail=""):
        return rendre({"erreur": ERREURS.get(cle, cle), "detail": detail}, 1)

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
        return echec(exc.cle, exc.detail)
    except Exception as exc:  # pragma: no cover - filet de dernier recours
        import traceback

        traceback.print_exc(file=sys.stderr)
        return echec("format_inconnu", f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
