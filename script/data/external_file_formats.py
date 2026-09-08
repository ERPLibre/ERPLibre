#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les formats : lire, décrire, nettoyer, écrire, convertir.

Séparé d'`external_file.py`, qui porte les RÈGLES. La frontière n'est pas
esthétique : `external_file.py` doit s'importer sous `.venv.erplibre`, qui
n'a ni openpyxl ni xlrd, sinon les tests des règles pures tombent tous à
l'import. Ici, chaque bibliothèque tierce est importée DANS la fonction qui
en a besoin, pour la même raison.

Le contrat externe reste `external_file.py --report/--plan/--apply` : la
coupure est interne.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import sys
import tempfile
import warnings
import xml.etree.ElementTree as ET
import zipfile

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.data import external_file as noyau  # noqa: E402
from script.data.external_file import (  # noqa: E402
    _INTACTE,
    Correspondance,
    anonymise_cellule,
    cellule_en_portee,
    classer,
    coercer_texte,
    colonne_plancher,
    detect_format,
    format_divergent,
    has_macros,
    nom_de_fichier_sur,
    normaliser_access,
    normaliser_xls,
    progres,
    valeur_forme_identifiant,
    valeur_hors_tableur,
    verifier_copie,
    vivier_de_mots,
)

# openpyxl avertit sur stderr (« DrawingML support is incomplete »), et
# stderr est le canal de progression : un avertissement s'y lirait comme
# une ligne de progrès.
warnings.simplefilter("ignore")

CIBLES_CONVERSION = ("xlsx", "csv", "json", "xml")

# Le nom de feuille d'un format qui n'en porte pas. Reprendre le nom du
# FICHIER le recrachait dans la copie convertie — clé de premier niveau d'un
# JSON, nom d'onglet d'un xlsx — alors que le dialogue promet que le nom du
# fichier n'est pas anonymisé.
NOM_FEUILLE_NEUTRE = "feuille_1"

# `csv` refuse un champ de plus de 128 Kio par défaut, et un mémo de
# commande les dépasse. Le refus arrivait en « format non reconnu » sur un
# CSV parfaitement valide.
csv.field_size_limit(16 * 1024 * 1024)


class ErreurMoteur(Exception):
    """Un refus motivé, porteur d'une clé d'`ERREURS`."""

    def __init__(self, cle, detail=""):
        super().__init__(cle)
        self.cle = cle
        self.detail = detail


# ----------------------------------------------------------------------
# Ce que cette machine sait lire
# ----------------------------------------------------------------------
def _importable(nom):
    try:
        __import__(nom)
        return True
    except Exception:
        return False


def capabilities():
    """Format -> lisible ici. Les formats stdlib le sont toujours."""
    excel = _importable("openpyxl")
    return {
        "csv": True,
        "json": True,
        "xml": True,
        "xlsx": excel,
        "xls": _importable("xlrd"),
        "xlsb": False,
        "access": _importable("access_parser"),
        "images": _importable("PIL"),
        "mots": _importable("randomwordfr"),
    }


# ----------------------------------------------------------------------
# La grille — la forme commune à tous les lecteurs
# ----------------------------------------------------------------------
class Feuille:
    """Un tableau nommé : des lignes de valeurs, déjà normalisées.

    Chaque lecteur ramène ses types aux types des règles AVANT de rendre
    une feuille. C'est là que se joue la correction d'un `.xls` dont les
    dates sont des flottants ou d'un Access dont les dates sont des
    chaînes : la règle ne doit jamais avoir à deviner.
    """

    def __init__(self, nom, lignes, masquee=False, source=None):
        self.nom = nom
        self.lignes = lignes
        self.masquee = masquee
        self.source = source
        # (ligne, colonne) -> (conteneur, clé). Hors tableur, l'écriture
        # passait par un SECOND parcours de l'arbre, qui ignorait la portée,
        # le plancher et les colonnes intactes — au point de détruire un
        # external ID que le plancher venait de protéger. Une ancre par
        # cellule rend l'écriture solidaire de la marche à blanc.
        self.ancres = {}
        # L'arbre JSON ou XML dont ces ancres sont les branches.
        self.arbre = None
        # L'index 1-based de la colonne qui porte de la STRUCTURE, ou None.
        # Le LECTEUR seul le sait : une grille (clé, valeur) en a une, un
        # tableau de vrais champs n'en a aucune. Le déduire du FORMAT
        # recopiait en clair le premier champ d'un tableau d'objets.
        self.colonne_structure = None
        # Vrai quand la ligne 1 de la grille est une ÉTIQUETTE fabriquée
        # par le lecteur (« cle »/« valeur », « chemin »/« valeur ») :
        # absente du fichier, elle n'est ni de la donnée ni un en-tête, et
        # aucune ancre ne peut l'écrire.
        self.ligne1_fabriquee = False
        # Le porteur d'une racine SCALAIRE (`"x"`, `42` — du JSON valide).
        # Un str ou un int ne se réécrit pas en place : sans cette case
        # réinscriptible, l'ancre porte None et l'écriture déréférence None.
        self.porteur = None

    @property
    def etiquettes(self):
        return list(self.lignes[0]) if self.lignes else []


def _etiquettes_par_colonne(feuilles):
    """{(feuille, colonne 1-based): étiquette}, lu AVANT toute écriture.

    Avant, parce que répondre « oui » à l'anonymisation de la ligne
    d'en-tête remplacerait l'étiquette que la question des colonnes
    intactes cherche ensuite.
    """
    table = {}
    for feuille in feuilles:
        for index, etiquette in enumerate(feuille.etiquettes, start=1):
            if isinstance(etiquette, str) and etiquette.strip():
                table[(feuille.nom, index)] = etiquette.strip()
    return table


def _stats_colonnes(feuille):
    """Par colonne : étiquette, type dominant, remplies, distinctes, bornes.

    Le coût est nul — la passe visite déjà chaque cellule — et c'est elle
    qui produit les BORNES dont la règle du nombre a besoin, en même temps
    que les étiquettes que teste le plancher. Sans ce bloc, les questions
    sur les colonnes et sur la ligne d'en-tête sont impossibles à
    répondre : il faudrait ouvrir le fichier dans Excel d'abord, ce que
    cette entrée existe pour supprimer.
    """
    largeur = max((len(l) for l in feuille.lignes), default=0)
    colonnes = []
    etiquettes = feuille.etiquettes
    for index in range(largeur):
        familles = {}
        distinctes = set()
        remplies = 0
        forme = True
        forme_rel = True
        mini = maxi = None
        for numero, ligne in enumerate(feuille.lignes, start=1):
            if numero == 1:
                continue
            valeur = ligne[index] if index < len(ligne) else None
            famille = classer(valeur)
            if famille == "vide":
                continue
            remplies += 1
            forme = forme and valeur_forme_identifiant(valeur)
            forme_rel = forme_rel and noyau.valeur_forme_relation(valeur)
            familles[famille] = familles.get(famille, 0) + 1
            if len(distinctes) < 10000:
                try:
                    distinctes.add(valeur)
                except TypeError:
                    distinctes.add(repr(valeur))
            if (
                famille == "nombre"
                and not isinstance(valeur, bool)
                and math.isfinite(valeur)
            ):
                # NaN et l'infini ne bornent rien : `min` et `max` les
                # ignorent selon l'ORDRE des arguments, ce qui n'est pas
                # une garantie sur laquelle asseoir un intervalle de
                # tirage.
                mini = valeur if mini is None else min(mini, valeur)
                maxi = valeur if maxi is None else max(maxi, valeur)
        etiquette = etiquettes[index] if index < len(etiquettes) else None
        dominant = (
            max(familles.items(), key=lambda kv: kv[1])[0]
            if familles
            else "vide"
        )
        colonnes.append(
            {
                "index": index + 1,
                "etiquette": (
                    str(etiquette).strip()
                    if isinstance(etiquette, str)
                    else None
                ),
                "type": dominant,
                "remplies": remplies,
                "distinctes": len(distinctes),
                "min": mini,
                "max": maxi,
                "forme_identifiant": forme,
                "forme_relation": forme_rel,
                "plancher": colonne_plancher(etiquette, forme, forme_rel),
            }
        )
    return colonnes


def _formes_par_colonne(rapport, cle="forme_identifiant"):
    """{(feuille, colonne): son contenu a-t-il cette forme mesurée}."""
    return {
        (feuille["nom"], colonne["index"]): bool(colonne.get(cle))
        for feuille in rapport.get("feuilles", [])
        for colonne in feuille.get("colonnes", [])
    }


def _bornes_par_colonne(rapport):
    """{(feuille, colonne): (min, max)} depuis le rapport déjà calculé."""
    bornes = {}
    for feuille in rapport.get("feuilles", []):
        for colonne in feuille.get("colonnes", []):
            if colonne.get("min") is not None:
                bornes[(feuille["nom"], colonne["index"])] = (
                    colonne["min"],
                    colonne["max"],
                )
    return bornes


# ----------------------------------------------------------------------
# Les lecteurs
# ----------------------------------------------------------------------
def _lire_xlsx(chemin, garder_vba=False):
    """Le classeur, et ses feuilles de calcul.

    `wb.worksheets` et JAMAIS `wb.sheetnames` : ce dernier mêle les
    feuilles graphiques, et `wb[nom]` rend alors un `Chartsheet`, qui n'a
    ni `max_row`, ni `max_column`, ni `iter_rows`.
    """
    from openpyxl import load_workbook

    try:
        classeur = load_workbook(
            chemin,
            data_only=False,
            keep_links=False,
            keep_vba=bool(garder_vba),
        )
    except ErreurMoteur:
        raise
    except Exception as exc:
        # La bibliothèque ne lit pas tout ce qu'Excel écrit : une feuille
        # graphique DÉPOURVUE de graphique fait lever `AttributeError`
        # dans son lecteur de relations, en 3.1.2. Ce refus nomme la
        # cause ; sans lui, un fichier qui s'ouvre dans Excel ressort en
        # « format non reconnu » suivi d'un message Python.
        raise ErreurMoteur(
            "lecture_impossible", f"{type(exc).__name__}: {exc}"
        )
    feuilles = []
    for onglet in classeur.worksheets:
        lignes = [
            [cellule.value for cellule in ligne]
            for ligne in onglet.iter_rows()
        ]
        feuilles.append(
            Feuille(
                onglet.title,
                lignes,
                masquee=onglet.sheet_state != "visible",
                source=onglet,
            )
        )
    return classeur, feuilles


def _lire_xls(chemin):
    import xlrd

    # `logfile` vaut sys.stdout par défaut, et xlrd y écrit dès qu'un
    # classeur n'a pas de CODEPAGE : la ligne se mêlait à l'unique objet
    # JSON de stdout, et l'appelant refusait un fichier lisible sans un mot
    # de diagnostic.
    classeur = xlrd.open_workbook(
        chemin, formatting_info=False, logfile=sys.stderr
    )
    feuilles = []
    for onglet in classeur.sheets():
        lignes = []
        for numero in range(onglet.nrows):
            lignes.append(
                [
                    normaliser_xls(
                        onglet.cell_type(numero, colonne),
                        onglet.cell_value(numero, colonne),
                        classeur.datemode,
                    )
                    for colonne in range(onglet.ncols)
                ]
            )
        feuilles.append(
            Feuille(onglet.name, lignes, masquee=onglet.visibility != 0)
        )
    return feuilles


def _lire_access(chemin):
    """Les tables d'un `.mdb`/`.accdb`, reconstruites ligne par ligne.

    Deux pièges d'`access-parser`, tous deux dans sa source :

    `_parse_catalog` ajoute `MSysObjects` AVANT le filtre des objets
    système, sans condition. Itérer `db.catalog` livrerait donc le
    catalogue d'objets d'Access — noms, propriétaires, et pour une table
    liée le chemin source. On écarte tout `MSys*`.

    `parse_table` rend un dictionnaire de colonnes de LONGUEURS INÉGALES :
    `_parse_row` sort tôt après avoir déjà alimenté les colonnes de
    longueur fixe. Reconstruire par `zip(*valeurs)` tronquerait à la plus
    courte et apparierait un nom avec les nombres d'une autre ligne —
    pire qu'une erreur, parce que la sortie a l'air correcte. On aligne
    donc sur la plus LONGUE, en comblant par `None`.
    """
    from access_parser import AccessParser

    base = AccessParser(chemin)
    feuilles = []
    for nom in base.catalog:
        if str(nom).startswith("MSys"):
            continue
        try:
            colonnes = base.parse_table(nom)
        except Exception as exc:  # une table illisible n'arrête pas tout
            progres(f"{nom}: {type(exc).__name__}")
            continue
        etiquettes = list(colonnes.keys())
        # Le TYPE déclaré de chaque colonne, pour normaliser avant que
        # l'anonymiseur voie quoi que ce soit : `access-parser` rend une
        # date et un montant en CHAÎNE, et la règle du texte les prendrait
        # pour du texte du client.
        types = {}
        try:
            for col in base.get_table(nom).columns.values():
                types[col.col_name_str] = col.type
        except Exception as exc:  # pragma: no cover - table hors norme
            progres(f"{nom}: types indisponibles ({type(exc).__name__})")
        hauteur = max((len(v) for v in colonnes.values()), default=0)
        lignes = [etiquettes]
        for index in range(hauteur):
            lignes.append(
                [
                    normaliser_access(
                        (
                            colonnes[cle][index]
                            if index < len(colonnes[cle])
                            else None
                        ),
                        types.get(cle),
                    )
                    for cle in etiquettes
                ]
            )
        feuilles.append(Feuille(str(nom), lignes))
    return feuilles


def _encodage_csv(chemin):
    """(encodage, par quoi il a été décidé).

    Le BOM d'abord, `chardet` ensuite s'il est là, puis un décodage d'essai
    du FICHIER ENTIER — pas d'un préfixe, qui couperait une séquence
    multi-octets et ferait passer de l'UTF-8 valide pour du cp1252 — et
    `cp1252` en dernier, qui ne lève jamais. Le rapport dit lequel a
    répondu, pour qu'une supposition ne se lise pas comme une mesure.
    """
    with open(chemin, "rb") as fh:
        octets = fh.read()
    for bom, nom in (
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe\x00\x00", "utf-32"),
        (b"\x00\x00\xfe\xff", "utf-32"),
        (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"),
    ):
        if octets.startswith(bom):
            return nom, "bom"
    try:
        import chardet

        devine = chardet.detect(octets)
        if devine and devine.get("encoding") and devine["confidence"] > 0.8:
            return devine["encoding"], "chardet"
    except Exception:
        pass
    try:
        octets.decode("utf-8")
        return "utf-8", "repli"
    except UnicodeDecodeError:
        return "cp1252", "repli"


def _delimiteur_csv(texte):
    """(délimiteur, par quoi il a été décidé).

    `csv.Sniffer().sniff()` LÈVE sur un CSV à une seule colonne et sur un
    fichier en dents de scie — exactement les deux formes que le rapport
    promet de couvrir — et rend une LETTRE prise dans la donnée si on ne le
    borne pas. Son verdict est donc borné, rattrapé, puis VALIDÉ : est
    retenu le candidat qui donne le même nombre de champs sur les vingt
    premières lignes non vides.
    """
    candidats = [",", ";", "\t", "|"]
    echantillon = texte[:65536]
    try:
        devine = csv.Sniffer().sniff(echantillon, delimiters=",;\t|")
        if devine.delimiter in candidats:
            candidats.insert(
                0, candidats.pop(candidats.index(devine.delimiter))
            )
            mesure = "sniffer"
        else:
            mesure = "repli"
    except csv.Error:
        mesure = "repli"

    lignes = [l for l in echantillon.splitlines() if l.strip()][:20]
    for candidat in candidats:
        largeurs = {len(l.split(candidat)) for l in lignes}
        if len(largeurs) == 1 and largeurs != {1}:
            return candidat, mesure if candidat == candidats[0] else "mesure"
    return ",", "repli"


def _lire_csv(chemin):
    encodage, source_enc = _encodage_csv(chemin)
    with open(chemin, "r", encoding=encodage, errors="replace") as fh:
        texte = fh.read()
    delimiteur, source_del = _delimiteur_csv(texte)
    # `csv.reader` ne rend que des chaînes : un champ numérique doit
    # retrouver son type ici, sinon la colonne de montants est traitée
    # comme du texte et chaque montant devient un mot.
    # L'EN-TÊTE garde son type d'origine : la coercition le rendait en
    # entier, donc en étiquette absente, et « 1 » ne désignait plus la
    # colonne étiquetée « 1 » mais la première colonne.
    lignes = []
    for numero, ligne in enumerate(
        csv.reader(io.StringIO(texte), delimiter=delimiteur), start=1
    ):
        lignes.append(
            list(ligne)
            if numero == 1
            else [coercer_texte(champ) for champ in ligne]
        )
    nom = NOM_FEUILLE_NEUTRE
    meta = {
        "encodage": encodage,
        "encodage_source": source_enc,
        "delimiteur": delimiteur,
        "delimiteur_source": source_del,
    }
    return Feuille(nom, lignes), meta


# ----------------------------------------------------------------------
# Les rapports
# ----------------------------------------------------------------------
def _rapport_commun(chemin, format_lu):
    return {
        "chemin": chemin,
        "format": format_lu,
        "taille": os.path.getsize(chemin),
        "divergence": format_divergent(chemin, format_lu),
        "vivier": len(vivier_de_mots()),
        "vivier_complet": _importable("randomwordfr"),
        "lecture_seule": format_lu in noyau.FORMATS_LECTURE_SEULE,
        "feuilles": [],
        "comptes": {},
        "hors_cellules": {},
        "avertissements": [],
    }


def _comptes_de(feuilles):
    comptes = {}
    for feuille in feuilles:
        for numero, ligne in enumerate(feuille.lignes, start=1):
            for valeur in ligne:
                famille = classer(valeur)
                if famille == "vide":
                    continue
                comptes[famille] = comptes.get(famille, 0) + 1
    return comptes


def _feuilles_en_rapport(feuilles):
    resume = []
    for feuille in feuilles:
        colonnes = _stats_colonnes(feuille)
        formules = sum(
            1
            for ligne in feuille.lignes
            for valeur in ligne
            if classer(valeur) == "formule"
        )
        litteraux = sum(
            1
            for ligne in feuille.lignes
            for valeur in ligne
            if classer(valeur) == "formule" and '"' in str(valeur)
        )
        resume.append(
            {
                "nom": feuille.nom,
                "lignes": len(feuille.lignes),
                "colonnes_n": max((len(l) for l in feuille.lignes), default=0),
                "masquee": feuille.masquee,
                "formules": formules,
                "formules_litteral": litteraux,
                "colonnes": colonnes,
            }
        )
    return resume


def _hors_cellules_xlsx(classeur, chemin):
    """Ce qui porte du texte sans être une cellule.

    Les plages nommées se lisent dans les DEUX collections : openpyxl 3.1 a
    scindé l'espace de noms, et `ws.defined_names` porte les noms locaux à
    une feuille, invisibles à `wb.defined_names`.

    Les liens externes et les hyperliens de cellule se comptent SÉPARÉMENT :
    ce sont des objets différents, et un seul des deux tombe avec
    `keep_links=False`.
    """
    plages = list(classeur.defined_names.keys())
    hyperliens, cibles, commentaires, auteurs = 0, set(), 0, set()
    entetes, validations, conditionnelles, graphiques = 0, 0, 0, 0
    croises = 0
    for onglet in classeur.worksheets:
        plages.extend(onglet.defined_names.keys())
        graphiques += len(getattr(onglet, "_charts", []) or [])
        croises += len(getattr(onglet, "_pivots", []) or [])
        validations += len(
            getattr(onglet.data_validations, "dataValidation", []) or []
        )
        conditionnelles += sum(1 for _ in onglet.conditional_formatting)
        for entete in (
            onglet.oddHeader,
            onglet.evenHeader,
            onglet.firstHeader,
            onglet.oddFooter,
            onglet.evenFooter,
            onglet.firstFooter,
        ):
            for partie in (entete.left, entete.center, entete.right):
                if getattr(partie, "text", None):
                    entetes += 1
        for ligne in onglet.iter_rows():
            for cellule in ligne:
                if cellule.comment is not None:
                    commentaires += 1
                    if cellule.comment.author:
                        auteurs.add(cellule.comment.author)
                if cellule.hyperlink is not None:
                    hyperliens += 1
                    cible = getattr(cellule.hyperlink, "target", None)
                    if cible:
                        cibles.add(str(cible))
    proprietes = classeur.properties
    return {
        "createur": proprietes.creator,
        "modifie_par": proprietes.lastModifiedBy,
        "titre": proprietes.title,
        "mots_cles": proprietes.keywords,
        "proprietes_perso": len(
            list(getattr(classeur, "custom_doc_props", []) or [])
        ),
        "commentaires": commentaires,
        "auteurs_commentaires": len(auteurs),
        "hyperliens": hyperliens,
        "cibles_liens": sorted(cibles)[:20],
        "liens_externes": len(getattr(classeur, "_external_links", []) or []),
        "plages_nommees": sorted(set(plages))[:40],
        "entetes_pieds": entetes,
        "validations": validations,
        "conditionnelles": conditionnelles,
        "graphiques": graphiques,
        "croises": croises,
        "feuilles_graphiques": len(getattr(classeur, "chartsheets", []) or []),
        "images": noyau.compter_media(chemin),
        "macros": has_macros(chemin),
    }


def report(chemin):
    """Le rapport, avant toute question."""
    format_lu = detect_format(chemin)
    if format_lu == "protege":
        raise ErreurMoteur("protege", chemin)
    if format_lu == "xlsb":
        rapport = _rapport_commun(chemin, "xlsb")
        rapport["hors_cellules"] = {"macros": has_macros(chemin)}
        rapport["arret"] = noyau.ERREURS["illisible_ici"]
        return rapport
    if not format_lu:
        raise ErreurMoteur("format_inconnu", os.path.basename(chemin))

    rapport = _rapport_commun(chemin, format_lu)
    if format_lu == "xlsx":
        progres(os.path.basename(chemin))
        classeur, feuilles = _lire_xlsx(chemin)
        rapport["hors_cellules"] = _hors_cellules_xlsx(classeur, chemin)
    elif format_lu == "xls":
        feuilles = _lire_xls(chemin)
        rapport["avertissements"].append(
            "This format stores no formula readable here."
        )
    elif format_lu == "access":
        feuilles = _lire_access(chemin)
        rapport["avertissements"].append(
            "Saved queries are not readable in pure Python."
        )
    elif format_lu == "csv":
        feuille, meta = _lire_csv(chemin)
        feuilles = [feuille]
        rapport.update(meta)
    elif format_lu == "json":
        feuilles = _lire_json(chemin)[0]
    elif format_lu == "xml":
        feuilles = _lire_xml(chemin)[0]
    else:  # pragma: no cover - detect_format ne rend rien d'autre
        raise ErreurMoteur("format_inconnu", format_lu)

    rapport["feuilles"] = _feuilles_en_rapport(feuilles)
    rapport["comptes"] = _comptes_de(feuilles)
    if not rapport["vivier_complet"]:
        rapport["avertissements"].append(
            "Only 20 fallback words are available: randomwordfr is missing."
        )
    return rapport


# ----------------------------------------------------------------------
# JSON et XML — hors tableur, une valeur est aussi un attribut
# ----------------------------------------------------------------------
def _lire_json(chemin):
    """Un JSON ramené à une grille, pour que le rapport parle.

    Les CLÉS sont de la structure et ne bougent pas ; seules les valeurs
    passent par les règles.
    """
    with open(chemin, "r", encoding="utf-8") as fh:
        arbre = json.load(fh)
    lignes = []
    ancres = {}
    colonne_structure = None
    ligne1_fabriquee = False
    porteur = None
    # Le tableau d'enregistrements exige que TOUTE entrée soit un objet :
    # une entrée nue (chaîne, nombre, null, liste) n'a pas de clés, et
    # `element.get` la faisait mourir. Un tableau mêlé retombe sur
    # l'aplatissement, qui ancre chaque feuille — la sauter écrirait
    # l'entrée en clair, non annoncée.
    if (
        isinstance(arbre, list)
        and arbre
        and all(isinstance(e, dict) for e in arbre)
    ):
        cles = []
        for element in arbre:
            for cle in element:
                if cle not in cles:
                    cles.append(cle)
        lignes.append(cles)
        for element in arbre:
            lignes.append([element.get(cle) for cle in cles])
            for index, cle in enumerate(cles, start=1):
                if cle in element:
                    ancres[(len(lignes), index)] = (element, cle)
    else:
        colonne_structure = 1
        ligne1_fabriquee = True
        lignes.append(["cle", "valeur"])
        porteur = None if isinstance(arbre, (dict, list)) else [arbre]
        for cle, valeur, conteneur, index in _aplatir_json(
            arbre,
            conteneur=porteur,
            index=None if porteur is None else 0,
        ):
            lignes.append([cle, valeur])
            ancres[(len(lignes), 2)] = (conteneur, index)
    feuille = Feuille(NOM_FEUILLE_NEUTRE, lignes)
    feuille.ancres = ancres
    feuille.arbre = arbre
    feuille.colonne_structure = colonne_structure
    feuille.ligne1_fabriquee = ligne1_fabriquee
    feuille.porteur = porteur
    return [feuille], arbre


def _aplatir_json(noeud, prefixe="", conteneur=None, index=None):
    """(chemin, valeur, conteneur, clé) — la clé permet de RÉÉCRIRE."""
    if isinstance(noeud, dict):
        for cle, valeur in noeud.items():
            yield from _aplatir_json(
                valeur, f"{prefixe}.{cle}".strip("."), noeud, cle
            )
    elif isinstance(noeud, list):
        for rang, valeur in enumerate(noeud):
            yield from _aplatir_json(valeur, f"{prefixe}[{rang}]", noeud, rang)
    else:
        yield prefixe, noeud, conteneur, index


def _lire_xml(chemin):
    """(feuilles, arbre). L'analyse désamorce les entités externes."""
    from defusedxml.ElementTree import parse

    arbre = parse(chemin)
    racine = arbre.getroot()
    lignes = [["chemin", "valeur"]]
    ancres = {}
    for element in racine.iter():
        if element.text and element.text.strip():
            lignes.append([element.tag, coercer_texte(element.text.strip())])
            ancres[(len(lignes), 2)] = (element, None)
        for cle, valeur in element.attrib.items():
            lignes.append([f"{element.tag}@{cle}", coercer_texte(valeur)])
            ancres[(len(lignes), 2)] = (element, cle)
        # La QUEUE d'un élément : le texte qui suit sa balise fermante. Un
        # export d'ERP nommé « .xls » qui est en réalité du HTML arrive
        # ici, et la moitié d'une cellule y vit — « Client <b>X</b> Nom »
        # porte « Nom » en queue de <b>.
        if element.tail and element.tail.strip():
            lignes.append(
                [f"{element.tag}#tail", coercer_texte(element.tail.strip())]
            )
            ancres[(len(lignes), 2)] = (element, "#tail")
    feuille = Feuille(NOM_FEUILLE_NEUTRE, lignes)
    feuille.ancres = ancres
    feuille.arbre = arbre
    feuille.colonne_structure = 1
    feuille.ligne1_fabriquee = True
    return [feuille], arbre


# ----------------------------------------------------------------------
# Le nettoyage hors cellules
# ----------------------------------------------------------------------
def nettoyer_hors_cellules(classeur, table, options):
    """Effacer ce qui porte du texte sans être une cellule. AVANT la grille.

    Sur les 24 vecteurs qu'un `.xlsx` peut porter, ce bloc en efface 19.
    Les cinq qui restent — plages nommées globale et locale, nom de
    tableau, littéral de formule, nom de feuille — sont référencés par des
    formules : les supprimer casserait ce que la règle de la formule vient
    de préserver, donc ils sont RAPPORTÉS et non effacés.

    La liste qui suit tient à un attribut privé près, et c'est le test de
    fuite de `test_transform_external.py` qui la garde : il assert la liste
    EXACTE des survivants, de sorte qu'un vecteur rouvert par une montée de
    version d'openpyxl fait tomber le test au lieu de passer inaperçu.
    """
    from openpyxl.packaging.core import DocumentProperties
    from openpyxl.packaging.custom import CustomPropertyList

    vivier = options["vivier"]
    comptes = {"proprietes": 0, "commentaires": 0, "hyperliens": 0}

    # `creator` vaut « openpyxl » par DÉFAUT : sans creator=None, l'élément
    # <dc:creator> ne disparaît pas, il est REMPLI. Mesuré.
    classeur.properties = DocumentProperties(creator=None)
    classeur.custom_doc_props = CustomPropertyList()
    comptes["proprietes"] += 1

    for onglet in classeur.worksheets:
        onglet._pivots = []
        onglet._images = []
        onglet.auto_filter.filterColumn = []
        onglet.data_validations.dataValidation = []
        onglet.conditional_formatting._cf_rules.clear()
        for entete in (
            onglet.oddHeader,
            onglet.evenHeader,
            onglet.firstHeader,
            onglet.oddFooter,
            onglet.evenFooter,
            onglet.firstFooter,
        ):
            for partie in (entete.left, entete.center, entete.right):
                partie.text = None
        if options.get("garder_graphiques"):
            _nettoyer_graphiques(onglet)
        else:
            onglet._charts = []
        for ligne in onglet.iter_rows():
            for cellule in ligne:
                if cellule.comment is not None:
                    cellule.comment = None
                    comptes["commentaires"] += 1
                if cellule.hyperlink is not None:
                    cellule.hyperlink = None
                    comptes["hyperliens"] += 1
        _anonymiser_noms_locaux(onglet, table, vivier)

    _anonymiser_noms_locaux(classeur, table, vivier)
    comptes["formats"] = _anonymiser_formats_de_nombre(classeur, table, vivier)
    comptes["styles"] = _renommer_styles_nommes(classeur)
    return comptes


# Un littéral entre guillemets dans un format de nombre personnalisé.
_LITTERAL_FORMAT = re.compile(r'"([^"]*)"')


def _anonymiser_formats_de_nombre(classeur, table, vivier):
    """Le texte libre d'un format de nombre personnalisé.

    Excel laisse suffixer un nombre d'un libellé — `#,##0" Nom du client"` —
    et ce libellé vit dans `xl/styles.xml`, hors de toute cellule. Aucune
    règle ne le voyait, et le filet le refusait sans jamais l'assainir : un
    classeur portant un nom dans un format personnalisé était inécrivable.

    La liste est REMPLACÉE dans son ordre, jamais réécrite cellule par
    cellule : les cellules référencent un format par son INDEX, et le
    setter d'openpyxl AJOUTE une entrée plutôt que de modifier la sienne —
    l'ancien format, littéral compris, repartait alors dans le fichier.

    Un littéral court — une devise, une unité — reste : il ne porte aucune
    donnée du client, et le remplacer abîmerait le classeur sans rien
    protéger. Le seuil est celui du filet, pour que ce qu'on garde ici soit
    exactement ce qu'il ne refusera pas.
    """
    from openpyxl.utils.indexed_list import IndexedList

    from script.data.external_file import nouveau_mot

    touches = 0

    def remplacer(trouve):
        nonlocal touches
        interieur = trouve.group(1)
        noyau_texte = interieur.strip()
        if len(noyau_texte) < noyau.LONGUEUR_VERIFIABLE:
            return trouve.group(0)
        touches += 1
        tete = interieur[: len(interieur) - len(interieur.lstrip())]
        queue = interieur[len(interieur.rstrip()) :]
        return '"%s%s%s"' % (
            tete,
            nouveau_mot(noyau_texte, table, vivier),
            queue,
        )

    formats = list(getattr(classeur, "_number_formats", []) or [])
    if not formats:
        return 0
    classeur._number_formats = IndexedList(
        [_LITTERAL_FORMAT.sub(remplacer, f) for f in formats]
    )
    return touches


def _renommer_styles_nommes(classeur):
    """Le NOM d'un style nommé part aussi dans `xl/styles.xml`.

    Renommé en place : une cellule référence son style par l'index de la
    liste, que renommer l'objet ne déplace pas. « Normal » est le style par
    défaut d'Excel et n'est pas un nom donné par quelqu'un.
    """
    touches = 0
    for rang, style in enumerate(
        getattr(classeur, "_named_styles", []) or [], start=1
    ):
        if style.name != "Normal":
            style.name = f"style_{rang}"
            touches += 1
    return touches


def _nettoyer_graphiques(onglet):
    """Le chemin optionnel : garder le graphique, vider ce qu'il porte.

    `s.tx = None` est INDISPENSABLE et le nettoyage des caches ne le
    remplace pas : un titre de série a deux formes — `<tx><v>littéral</v>`
    quand il est tapé, `<tx><strRef><f>réf</f>` quand il vient des données
    — et ni l'une ni l'autre n'est un cache : vider `strCache` et
    `numCache` les laisse toutes deux en place.
    """
    for graphique in onglet._charts:
        graphique.title = None
        for axe in (
            getattr(graphique, "x_axis", None),
            getattr(graphique, "y_axis", None),
            getattr(graphique, "z_axis", None),
        ):
            if axe is not None:
                axe.title = None
        for serie in graphique.series:
            for source in (
                serie.cat,
                serie.val,
                getattr(serie, "xVal", None),
                getattr(serie, "yVal", None),
                getattr(serie, "bubbleSize", None),
            ):
                if source is None:
                    continue
                for reference in ("numRef", "strRef", "multiLvlStrRef"):
                    porteur = getattr(source, reference, None)
                    if porteur is None:
                        continue
                    for cache in (
                        "numCache",
                        "strCache",
                        "multiLvlStrCache",
                    ):
                        if hasattr(porteur, cache):
                            setattr(porteur, cache, None)
            serie.tx = None


def _anonymiser_noms_locaux(porteur, table, vivier):
    """La constante littérale d'une plage nommée passe par la table.

    Le NOM ne se supprime pas — une formule le référencerait dans le vide,
    alors que la règle de la formule vient de la préserver. Sa VALEUR, en
    revanche, se remplace quand c'est une constante littérale, et le nom
    reste résolvable. Mesuré comme survivant tant qu'on ne le fait pas.
    """
    from script.data.external_file import nouveau_mot

    noms = getattr(porteur, "defined_names", None)
    if not noms:
        return
    for nom in list(noms.keys()):
        defini = noms[nom]
        texte = getattr(defini, "attr_text", "") or ""
        if len(texte) > 1 and texte.startswith('"') and texte.endswith('"'):
            interieur = texte[1:-1]
            if interieur:
                defini.attr_text = '"%s"' % nouveau_mot(
                    interieur, table, vivier
                )


# ----------------------------------------------------------------------
# La marche à blanc et l'écriture
# ----------------------------------------------------------------------
def _preparer(chemin, options):
    """(format, feuilles, classeur, rapport, options complétées)."""
    format_lu = detect_format(chemin)
    if format_lu == "protege":
        raise ErreurMoteur("protege", chemin)
    if format_lu == "xlsb":
        raise ErreurMoteur("illisible_ici", chemin)
    if not format_lu:
        raise ErreurMoteur("format_inconnu", os.path.basename(chemin))

    rapport = report(chemin)
    options = dict(options)
    options["vivier"] = vivier_de_mots()
    options.setdefault("nombres", True)
    options.setdefault("texte", True)
    options.setdefault("entetes", False)
    options["colonnes_intactes"] = set(options.get("colonnes_intactes") or [])

    classeur = None
    if format_lu == "xlsx":
        classeur, feuilles = _lire_xlsx(
            chemin, garder_vba=options.get("garder_macros")
        )
    elif format_lu == "xls":
        feuilles = _lire_xls(chemin)
    elif format_lu == "access":
        feuilles = _lire_access(chemin)
    elif format_lu == "csv":
        feuilles = [_lire_csv(chemin)[0]]
    elif format_lu == "json":
        feuilles = _lire_json(chemin)[0]
    else:
        feuilles = _lire_xml(chemin)[0]

    connues = {f.nom for f in feuilles}
    demandees = options.get("feuilles") or []
    inconnues = [n for n in demandees if n not in connues]
    if inconnues:
        raise ErreurMoteur("aucune_feuille", ", ".join(inconnues))
    options["feuilles"] = list(demandees) or None
    options["etiquettes"] = _etiquettes_par_colonne(feuilles)
    options["bornes"] = _bornes_par_colonne(rapport)
    options["formes"] = _formes_par_colonne(rapport)
    options["formes_relation"] = _formes_par_colonne(rapport, "forme_relation")
    # Hors tableur, la colonne 1 de la grille porte des NOMS de balise ou des
    # chemins de clé : de la structure, que le graveur ne touche jamais. Les
    # compter comme remplacées désarmait le refus « rien à faire » et brûlait
    # le vivier sur des noms de champ.
    options["colonnes_structure"] = {
        (f.nom, f.colonne_structure) for f in feuilles if f.colonne_structure
    }
    # Hors tableur, l'ancre est la SEULE voie d'écriture, et aucune ancre ne
    # porte la ligne 1 : ni l'étiquette que le lecteur a fabriquée, ni les
    # clés d'objet d'un tableau d'enregistrements. La compter en portée la
    # fait annoncer comme remplacée alors que la copie la garde en clair, et
    # le filet qui relit les octets refuse alors TOUTE copie. Une conversion
    # sort par un autre graveur, qui écrit bien cette ligne : elle y reste
    # en portée.
    ecrit_par_ancres = (
        format_lu in ("xml", "json")
        and (options.get("conversion") or format_lu) == format_lu
    )
    options["lignes_structure"] = {
        (f.nom, 1) for f in feuilles if f.ligne1_fabriquee or ecrit_par_ancres
    }
    return format_lu, feuilles, classeur, rapport, options


def _parcourir(
    feuilles, options, table, rng, appliquer=None, gardees_out=None
):
    """La passe unique : compte, et écrit si `appliquer` est donné.

    Un seul parcours pour la marche à blanc et pour l'écriture : deux
    chemins divergeraient, et c'est la marche à blanc qui perdrait la
    confiance qu'on lui accorde.
    """
    bilan = {
        "remplacees": 0,
        "texte": 0,
        "nombre": 0,
        "hors_portee": 0,
        "intactes": {},
        "apercu": [],
        "entete_gardee": [],
    }
    for feuille in feuilles:
        for numero, ligne in enumerate(feuille.lignes, start=1):
            for index, valeur in enumerate(ligne, start=1):
                famille = classer(valeur)
                if famille == "vide":
                    continue
                if not cellule_en_portee(feuille.nom, numero, index, options):
                    bilan["hors_portee"] += 1
                    if gardees_out is not None:
                        texte = str(valeur_hors_tableur(valeur) or "").strip()
                        if len(texte) >= noyau.LONGUEUR_VERIFIABLE:
                            gardees_out.setdefault(feuille.nom, set()).add(
                                texte
                            )
                    if (
                        numero == 1
                        and not options.get("entetes")
                        and famille == "texte"
                        and len(bilan["entete_gardee"]) < 12
                    ):
                        # La ligne 1 est PRÉSUMÉE d'en-tête, jamais
                        # mesurée : un CSV sans en-tête, ou un titre de
                        # rapport en A1, y met de la donnée. Un compteur
                        # global ne dit pas qu'un nom de client est dedans.
                        bilan["entete_gardee"].append(
                            {
                                "feuille": feuille.nom,
                                "cellule": f"L1C{index}",
                                "valeur": valeur_hors_tableur(valeur),
                            }
                        )
                    continue
                bornes = options["bornes"].get((feuille.nom, index))
                if isinstance(valeur, (dict, list)):
                    # Un conteneur imbriqué n'est pas une cellule : sans
                    # cette récursion, tout ce qu'il porte sort en clair.
                    # Le compte des FEUILLES réécrites décide : reconstruit
                    # à l'identique, le conteneur reste intact.
                    neuve, compte = _transformer_json(
                        valeur, options, table, rng
                    )
                    if not compte:
                        neuve = _INTACTE
                else:
                    neuve = anonymise_cellule(
                        valeur, options, table, rng, bornes=bornes
                    )
                    compte = {famille: 1}
                if neuve is _INTACTE:
                    bilan["intactes"][famille] = (
                        bilan["intactes"].get(famille, 0) + 1
                    )
                    if gardees_out is not None:
                        texte = str(valeur_hors_tableur(valeur) or "").strip()
                        if len(texte) >= noyau.LONGUEUR_VERIFIABLE:
                            gardees_out.setdefault(feuille.nom, set()).add(
                                texte
                            )
                    continue
                for fam, feuilles_reecrites in compte.items():
                    bilan["remplacees"] += feuilles_reecrites
                    if fam in ("texte", "nombre"):
                        bilan[fam] += feuilles_reecrites
                if len(bilan["apercu"]) < 5:
                    bilan["apercu"].append(
                        {
                            "feuille": feuille.nom,
                            "cellule": f"L{numero}C{index}",
                            "avant": valeur_hors_tableur(valeur),
                            "apres": valeur_hors_tableur(neuve),
                        }
                    )
                if appliquer is not None:
                    appliquer(feuille, numero, index, neuve)
    return bilan


def _colonnes_ecartees(rapport, options):
    ecartees = []
    for feuille in rapport.get("feuilles", []):
        for colonne in feuille.get("colonnes", []):
            if colonne.get("plancher"):
                ecartees.append(
                    {
                        "feuille": feuille["nom"],
                        "etiquette": colonne["etiquette"],
                        "raison": "plancher",
                    }
                )
            elif (
                colonne.get("etiquette")
                and colonne["etiquette"] in options["colonnes_intactes"]
            ):
                ecartees.append(
                    {
                        "feuille": feuille["nom"],
                        "etiquette": colonne["etiquette"],
                        "raison": "question",
                    }
                )
            elif (
                not colonne.get("etiquette")
                and str(colonne["index"]) in options["colonnes_intactes"]
            ):
                # Une colonne sans étiquette ne se désigne que par son
                # index ; l'aperçu ne la nommait pas du tout.
                ecartees.append(
                    {
                        "feuille": feuille["nom"],
                        "etiquette": f"#{colonne['index']}",
                        "raison": "question",
                    }
                )
    return ecartees


def plan(chemin, options):
    """Ce qui SERAIT écrit. Rien n'est ouvert en écriture.

    La convention du dépôt pour l'action de menu qui écrit : montrer, puis
    demander. Une question posée avant de savoir ce qui sera touché n'est
    pas un consentement.
    """
    import random

    format_lu, feuilles, _classeur, rapport, options = _preparer(
        chemin, options
    )
    table = Correspondance.charger(options.get("table_chemin"))
    graine = options.get("graine")
    rng = (
        random.Random(graine) if graine not in (None, "") else random.Random()
    )
    bilan = _parcourir(feuilles, options, table, rng)
    bilan["colonnes_ecartees"] = _colonnes_ecartees(rapport, options)
    bilan["format"] = format_lu
    bilan["fichiers"] = _fichiers_prevus(chemin, feuilles, options)
    # La marche à blanc est ce sur quoi l'opérateur consent : elle doit
    # refuser là où l'écriture refuserait.
    _refuser_table_confondue(
        chemin,
        options.get("table_chemin"),
        bilan["fichiers"] + [options.get("destination")],
    )
    bilan["avertissements"] = _avertissements(rapport, options)
    return bilan


def _fichiers_prevus(chemin, feuilles, options):
    """Les chemins qui seront écrits — calculés AVANT toute écriture."""
    destination = options.get("destination") or ""
    cible = options.get("conversion") or ""
    if cible and _un_fichier_par_feuille(cible, feuilles, options):
        pris = set()
        return [
            os.path.join(
                destination, f"{nom_de_fichier_sur(f.nom, pris)}.{cible}"
            )
            for f in feuilles
            if not options["feuilles"] or f.nom in options["feuilles"]
        ]
    return [destination] if destination else []


def _un_fichier_par_feuille(cible, feuilles, options):
    retenues = [
        f
        for f in feuilles
        if not options["feuilles"] or f.nom in options["feuilles"]
    ]
    return cible in ("csv",) and len(retenues) > 1


def _avertissements(rapport, options):
    """Ce que la copie perd ou garde, dit plutôt que découvert."""
    dits = []
    hors = rapport.get("hors_cellules") or {}
    if rapport.get("format") == "xlsx":
        dits.append(
            "Cached formula results are dropped;"
            " the sheet recomputes on open."
        )
        dits.append("Document properties were cleared on the copy.")
    if hors.get("croises") or hors.get("graphiques"):
        dits.append(
            "Pivot tables and chart caches are removed: they hold an"
            " unanonymised copy of the source."
        )
    if hors.get("images"):
        dits.append("Images and drawings are not carried over to the copy.")
    if hors.get("graphiques") and not options.get("garder_graphiques"):
        dits.append("Charts are not carried over to the copy.")
    if hors.get("graphiques") and options.get("garder_graphiques"):
        dits.append(
            "Charts are kept: their caches are cleaned through private"
            " attributes."
        )
    if hors.get("liens_externes"):
        dits.append(
            "External links were dropped; formulas that used them"
            " show #REF!."
        )
    if hors.get("plages_nommees"):
        dits.append(
            "Range and table names are kept so formulas resolve;"
            " they may hold identifying strings."
        )
    if rapport.get("format") in ("xlsx", "xls", "access"):
        # Le nom d'onglet survit dans workbook.xml, qu'une formule le
        # référence ou non : conditionner cet avertissement à la présence
        # d'un littéral de formule le taisait sur le cas le plus courant.
        dits.append(
            "Sheet names are kept so formulas resolve; they may identify."
        )
    if options.get("feuilles"):
        dits.append(
            "Sheets outside the selection are dropped from the copy;"
            " formulas that referenced them show #REF!."
        )
    if hors.get("feuilles_graphiques"):
        dits.append(
            "Chart sheets are dropped from the copy: their titles and"
            " series caches are not cells."
        )
    if rapport.get("format") == "json":
        dits.append("Object keys are kept as structure; they may identify.")
    if rapport.get("format") == "xml":
        dits.append(
            "Element and attribute names are kept as structure;"
            " they may identify."
        )
    if options.get("garder_macros"):
        dits.append(
            "The VBA project and its companions (form controls, ActiveX,"
            " VML shapes, ribbon, EMF images) are copied as they are and"
            " were not reviewed."
        )
    return dits


def _ecrire_atomique(destination, ecrivain):
    """Un temporaire du même répertoire, puis `os.replace()`.

    Le `try/finally` n'est pas une politesse : sans lui, une exception
    laisse de la donnée client sur le disque, sous un nom que personne
    n'annonce. Le mode 0600 dès la création, parce que le temporaire porte
    cette donnée avant d'être renommé.
    """
    parent = os.path.dirname(os.path.abspath(destination)) or "."
    os.makedirs(parent, mode=0o700, exist_ok=True)
    descripteur, temporaire = tempfile.mkstemp(
        dir=parent, prefix=".transform-", suffix=".part"
    )
    os.close(descripteur)
    os.chmod(temporaire, 0o600)
    try:
        ecrivain(temporaire)
        os.replace(temporaire, destination)
        temporaire = None
    finally:
        if temporaire and os.path.exists(temporaire):
            os.unlink(temporaire)


def _refuser_si_source(chemin, destination):
    """La destination ne peut JAMAIS être la source.

    C'est le seul chemin par lequel l'original disparaîtrait, et la
    confirmation par nom — qui porte sur « le fichier existe déjà » — ne le
    distinguerait pas d'un écrasement ordinaire. `samefile` couvre le lien
    symbolique, `realpath` le couvre avant qu'il existe.
    """
    if os.path.exists(destination):
        try:
            if os.path.samefile(chemin, destination):
                raise ErreurMoteur("destination_source", destination)
        except OSError:
            pass
    if os.path.realpath(chemin) == os.path.realpath(destination):
        raise ErreurMoteur("destination_source", destination)


def _valeurs_gardees(classeur, feuilles, format_lu):
    """Ce que le moteur conserve SCIEMMENT, et qui a été annoncé.

    La vérification d'après écriture refuse tout ce qui subsiste ; cette
    liste est la seule tolérance, et elle doit rester courte et justifiée.
    Chaque entrée est conservée parce que la retirer casserait ce que la
    règle de la formule vient de préserver.
    """
    gardees = set()
    for feuille in feuilles or ():
        # `ligne[0]` n'est de la structure que là où il porte VRAIMENT un
        # chemin de clé. La colonne 1 d'un tableau d'objets porte des
        # VALEURS, et les tolérer aveuglait le filet sur la colonne même
        # qu'il doit surveiller.
        if feuille.colonne_structure != 1:
            continue
        for ligne in feuille.lignes:
            if ligne and isinstance(ligne[0], str):
                gardees.add(ligne[0])
                gardees.update(re.split(r"[.\[\]@#]", ligne[0]))
    if classeur is None:
        return gardees
    for onglet in classeur.worksheets:
        gardees.add(onglet.title)
        gardees.update(onglet.defined_names.keys())
        for tableau in getattr(onglet, "tables", {}) or {}:
            gardees.add(str(tableau))
        for ligne in onglet.iter_rows():
            for cellule in ligne:
                # Le TEXTE d'une formule : la règle 1 interdit d'y toucher,
                # et le rapport le compte et l'annonce.
                if isinstance(cellule.value, str) and cellule.value.startswith(
                    "="
                ):
                    gardees.add(cellule.value)
                    gardees.update(re.findall(r'"([^"]*)"', cellule.value))
    gardees.update(classeur.defined_names.keys())
    return gardees


def ecrire(chemin, destination, options):
    """Écrire la copie. L'original n'est jamais modifié."""
    import random

    _refuser_si_source(chemin, destination)
    format_lu, feuilles, classeur, rapport, options = _preparer(
        chemin, options
    )
    options["destination"] = destination
    prevus = _fichiers_prevus(chemin, feuilles, options)
    _refuser_table_confondue(
        chemin, options.get("table_chemin"), prevus + [destination]
    )
    table = Correspondance.charger(options.get("table_chemin"))
    graine = options.get("graine")
    rng = (
        random.Random(graine) if graine not in (None, "") else random.Random()
    )
    hors_cellules = {}
    if format_lu == "xlsx":
        hors_cellules = nettoyer_hors_cellules(classeur, table, options)

    def appliquer(feuille, numero, index, neuve):
        feuille.lignes[numero - 1][index - 1] = neuve
        if feuille.source is not None:
            feuille.source.cell(row=numero, column=index).value = neuve
        # Hors tableur, l'ancre est la SEULE voie d'écriture : sans elle,
        # le graveur reparcourait l'arbre et ignorerait la portée.
        ancre = feuille.ancres.get((numero, index))
        if ancre is None:
            return
        conteneur, cle = ancre
        if isinstance(conteneur, (dict, list)):
            conteneur[cle] = neuve
        elif cle is None:
            conteneur.text = _garder_espaces(conteneur.text, neuve)
        elif cle == "#tail":
            conteneur.tail = _garder_espaces(conteneur.tail, neuve)
        else:
            conteneur.attrib[cle] = "" if neuve is None else str(neuve)

    hors_portee_gardees = {}
    bilan = _parcourir(
        feuilles,
        options,
        table,
        rng,
        appliquer=appliquer,
        gardees_out=hors_portee_gardees,
    )
    if not bilan["remplacees"] and not options.get("conversion"):
        if options["colonnes_intactes"] or not (
            options["nombres"] or options["texte"]
        ):
            raise ErreurMoteur("tout_exclu", "")
        raise ErreurMoteur("rien_a_faire", "")

    cible = options.get("conversion") or ""
    if format_lu == "xlsx":
        _resynchroniser_tableaux(classeur)
        # Récolter les tolérances sur le classeur qui SERA enregistré : un
        # littéral de formule ou un titre pris sur une feuille que la copie
        # ne porte pas taisait le filet au nom d'une formule que le
        # destinataire ne verra jamais.
        if not (cible and cible != format_lu):
            _retirer_feuilles_hors_portee(classeur, options)
    gardees = _valeurs_gardees(classeur, feuilles, format_lu)
    # Une cellule hors portée reste EN CLAIR par décision, et l'aperçu la
    # nomme : sa valeur n'est pas une fuite. Seules comptent les feuilles
    # qui partent dans la copie — celles que `_retirer_feuilles_hors_portee`
    # supprime n'y sont plus, et une de leurs valeurs qui reparaîtrait dans
    # un cache est une fuite comme une autre.
    retenues = options.get("feuilles")
    for nom, valeurs_vues in hors_portee_gardees.items():
        if retenues and nom is not None and nom not in retenues:
            continue
        gardees.update(valeurs_vues)

    if cible and cible != format_lu:
        fichiers = convertir(
            chemin,
            destination,
            cible,
            options,
            feuilles=feuilles,
            table=table,
        )
    elif format_lu == "xlsx":
        _ecrire_atomique(destination, classeur.save)
        fichiers = [destination]
    elif format_lu == "csv":
        fichiers = _ecrire_csv(destination, feuilles[0], options)
    elif format_lu in ("json", "xml"):
        fichiers = _ecrire_arbre(destination, feuilles[0], format_lu)
    else:
        # `.xls` et Access n'ont pas de graveur : la copie repart en .xlsx
        fichiers = convertir(
            chemin,
            destination,
            "xlsx",
            options,
            feuilles=feuilles,
            table=table,
        )

    # Le filet : relire les OCTETS écrits. Il ne dépend d'aucune
    # énumération de vecteurs, donc un endroit du format que personne n'a
    # pensé à nettoyer produit un refus, là où une liste de parties à
    # vérifier produirait un silence.
    fuites, non_vues = verifier_copie(fichiers, table, gardees)
    if fuites:
        for fichier in fichiers:
            if fichier and os.path.isfile(fichier):
                os.unlink(fichier)
        apercu = "; ".join(
            f"{v!r} -> {', '.join(sorted(set(parties))[:2])}"
            for v, parties in sorted(fuites.items())[:5]
        )
        raise ErreurMoteur("fuite_detectee", f"{len(fuites)} — {apercu}")

    chemin_table = options.get("table_chemin")
    if chemin_table:
        try:
            table.ecrire(chemin_table)
        except OSError:
            # Une copie sans sa table reçoit les mêmes mots que le fichier
            # suivant du lot, et deux clients fusionnent sur un seul mot.
            for fichier in fichiers:
                if fichier and os.path.isfile(fichier):
                    os.unlink(fichier)
            raise

    bilan["fichiers"] = fichiers
    bilan["hors_cellules"] = hors_cellules
    bilan["colonnes_ecartees"] = _colonnes_ecartees(rapport, options)
    bilan["avertissements"] = _avertissements(rapport, options)
    bilan["table"] = chemin_table or ""
    bilan["valeurs_non_verifiees"] = non_vues
    return bilan


def _garder_espaces(brut, neuve):
    """Réécrire un texte sans perdre son encadrement.

    Le texte d'un élément XML porte l'indentation du document et l'espace
    qui sépare deux mots d'un contenu mixte. Écrire la valeur nue collait
    « acai<b> » et aplatissait le document.
    """
    if neuve is None:
        return ""
    brut = brut or ""
    tete = brut[: len(brut) - len(brut.lstrip())]
    queue = brut[len(brut.rstrip()) :]
    return f"{tete}{neuve}{queue}"


def _retirer_feuilles_hors_portee(classeur, options):
    """Une feuille écartée de la portée ne part pas dans la copie.

    `classeur.save` grave le classeur ENTIER : répondre « Ventes » à la
    question des feuilles laissait les autres — dont une feuille masquée —
    intactes dans le fichier livré, avec pour seule trace « N cellules
    laissées hors portée ». Les autres cibles les retirent déjà.
    """
    # Une feuille graphique n'a AUCUNE cellule : la passe sur la grille ne
    # la voit pas, `worksheets` l'exclut par construction, et son titre,
    # ses titres d'axes, son en-tête et ses caches de série ne passent donc
    # par aucune règle. Rien ne peut l'anonymiser — elle part, toujours, et
    # l'avertissement le dit. La retirer seulement quand une sélection de
    # feuilles existe faisait mentir cet avertissement dans tous les autres
    # cas.
    for onglet in list(getattr(classeur, "chartsheets", []) or []):
        classeur.remove(onglet)

    retenues = options.get("feuilles")
    if not retenues:
        return
    for nom in [
        onglet.title
        for onglet in classeur.worksheets
        if onglet.title not in retenues
    ]:
        del classeur[nom]


def _resynchroniser_tableaux(classeur):
    """Un tableau porte une COPIE du texte de sa cellule d'en-tête.

    OOXML exige que `tableColumn.name` égale la cellule d'en-tête. Après
    l'anonymisation de celle-ci les deux divergent : rien n'est plus
    préservé au bénéfice d'une formule, et le texte d'origine reste
    simplement derrière. `totalsRowLabel` n'est jamais une cellule et
    survivait quelles que soient les options.

    Appelé APRÈS la passe sur la grille, contrairement au nettoyage hors
    cellules : il lui faut la valeur d'en-tête déjà remplacée.
    """
    for onglet in classeur.worksheets:
        for tableau in list((getattr(onglet, "tables", {}) or {}).values()):
            debut = tableau.ref.split(":")[0]
            ligne = onglet[debut].row
            colonne = onglet[debut].column
            for rang, tcol in enumerate(tableau.tableColumns):
                cellule = onglet.cell(row=ligne, column=colonne + rang)
                if isinstance(cellule.value, str) and cellule.value:
                    tcol.name = cellule.value
                if getattr(tcol, "totalsRowLabel", None):
                    tcol.totalsRowLabel = None


def _refuser_table_confondue(chemin, chemin_table, fichiers):
    """La table ne peut être NI la source NI un fichier écrit.

    Elle est gravée APRÈS la copie, en écrasant sa cible : confondue avec
    la source, elle détruit l'original ; confondue avec la copie, elle
    laisse sous le nom de la copie la liste en clair de toutes les valeurs
    réelles, et le menu annonce « Written: <destination> ».
    """
    if not chemin_table:
        return
    reel = os.path.realpath(chemin_table)
    if reel == os.path.realpath(chemin):
        raise ErreurMoteur("table_source", chemin_table)
    for fichier in fichiers:
        if fichier and reel == os.path.realpath(fichier):
            raise ErreurMoteur("table_source", chemin_table)


def _ecrire_arbre(destination, feuille, format_lu):
    """Graver l'arbre JSON ou XML que les ancres viennent de modifier.

    Aucun second parcours : ce que `_parcourir` a décidé est déjà DANS
    l'arbre, par les ancres. Un graveur qui reparcourait la source
    ignorerait la portée, le plancher et les colonnes intactes.
    """
    arbre = feuille.arbre

    def ecrivain(cible):
        if format_lu == "json":
            # Le porteur d'une racine scalaire : l'ancre a écrit DANS sa
            # case, c'est elle qu'il faut sérialiser. Pour un dict ou une
            # liste il vaut None, et `arbre` est déjà l'objet muté.
            charge = arbre if feuille.porteur is None else feuille.porteur[0]
            with open(cible, "w", encoding="utf-8") as fh:
                json.dump(charge, fh, ensure_ascii=False, indent=1)
        else:
            arbre.write(cible, encoding="utf-8", xml_declaration=True)

    _ecrire_atomique(destination, ecrivain)
    return [destination]


def _ecrire_csv(destination, feuille, options):
    def ecrivain(cible):
        with open(cible, "w", encoding="utf-8", newline="") as fh:
            graveur = csv.writer(
                fh, delimiter=options.get("delimiteur") or ","
            )
            for ligne in feuille.lignes:
                graveur.writerow(
                    [
                        "" if v is None else valeur_hors_tableur(v)
                        for v in ligne
                    ]
                )

    _ecrire_atomique(destination, ecrivain)
    return [destination]


def _transformer_json(noeud, options, table, rng):
    """(valeur, compte). Les CLÉS sont de la structure et restent.

    `compte` porte, par famille, le nombre de FEUILLES réécrites. Il est
    vide quand le sous-arbre revient identique : l'appelant en fait alors un
    « intact ». Sans ce compte, un conteneur reconstruit à l'identique
    valait une cellule remplacée — ce qui désarmait les refus « rien à
    faire » et « tout exclu », et faisait écrire une copie identique à la
    source en l'annonçant anonymisée.
    """
    if isinstance(noeud, (dict, list)):
        compte = {}
        entrees = (
            noeud.items() if isinstance(noeud, dict) else enumerate(noeud)
        )
        neuf = {} if isinstance(noeud, dict) else [None] * len(noeud)
        for cle, valeur in entrees:
            neuf[cle], partiel = _transformer_json(valeur, options, table, rng)
            for fam, feuilles_reecrites in partiel.items():
                compte[fam] = compte.get(fam, 0) + feuilles_reecrites
        return neuf, compte
    neuve = anonymise_cellule(noeud, options, table, rng)
    if neuve is _INTACTE:
        return noeud, {}
    return neuve, {classer(noeud): 1}


def _nom_de_feuille_anonyme(feuille, table, options):
    """Le nom d'une feuille, remplacé, pour une CONVERSION.

    Une table Access ou une feuille `.xls` porte souvent le nom du client,
    et la conversion l'écrit tel quel : en nom d'onglet, en clé de premier
    niveau d'un JSON, en nom de fichier. Contrairement au classeur d'où
    une formule le référence, ici RIEN ne le résout — c'est donc de la
    donnée, et le tolérer aurait laissé le nom du client dans la copie
    tout en faisant refuser le fichier au filet.

    Il passe par la MÊME table que les cellules : la feuille et les
    valeurs qui la nomment reçoivent le même mot.
    """
    from script.data.external_file import nouveau_mot

    if table is None or not feuille.nom:
        return feuille.nom
    return nouveau_mot(str(feuille.nom), table, options["vivier"])


def convertir(chemin, destination, cible, options, feuilles=None, table=None):
    """Écrire la copie dans un AUTRE format. Rend la liste des fichiers.

    Quand la cible ne peut pas porter la forme de la source — un classeur
    de plusieurs feuilles vers csv, une base Access vers csv — la
    destination est un RÉPERTOIRE, un fichier par feuille. Le menu le dit
    avant d'écrire.
    """
    if cible not in CIBLES_CONVERSION:
        raise ErreurMoteur("format_inconnu", cible)
    if feuilles is None:
        feuilles = _preparer(chemin, options)[1]
    retenues = [
        f
        for f in feuilles
        if not options.get("feuilles") or f.nom in options["feuilles"]
    ]
    if not retenues:
        raise ErreurMoteur("aucune_feuille", "")

    noms = {
        f.nom: _nom_de_feuille_anonyme(f, table, options) for f in retenues
    }
    if cible == "xlsx":
        return _convertir_vers_xlsx(destination, retenues, noms)
    if cible == "csv":
        if len(retenues) == 1:
            return _ecrire_csv(destination, retenues[0], options)
        return _convertir_vers_repertoire(destination, retenues, options, noms)
    if cible == "json":
        return _convertir_vers_json(destination, retenues, noms)
    return _convertir_vers_xml(destination, retenues)


def _convertir_vers_xlsx(destination, feuilles, noms=None):
    from openpyxl import Workbook

    classeur = Workbook()
    classeur.remove(classeur.active)
    pris = set()
    for feuille in feuilles:
        brut = (noms or {}).get(feuille.nom, feuille.nom)
        onglet = classeur.create_sheet(nom_de_fichier_sur(brut, pris)[:31])
        for ligne in feuille.lignes:
            onglet.append([_valeur_pour_xlsx(v) for v in ligne])
    _ecrire_atomique(destination, classeur.save)
    return [destination]


def _valeur_pour_xlsx(valeur):
    """La valeur telle qu'un classeur la porte, sans passer par du texte.

    `valeur_hors_tableur` est écrite pour csv, json et xml, trois formats
    sans types : elle rend une date en chaîne ISO. openpyxl, lui, porte
    nativement `datetime`, `int`, `float` et `bool` — convertir en texte
    faisait perdre le type, et la copie portait du texte là où une date
    était attendue, donc ne se réimportait plus comme telle.
    """
    if valeur is None or isinstance(valeur, (bool, int, float, str)):
        return valeur
    texte = getattr(valeur, "text", None)
    if isinstance(texte, str):
        return texte
    if isinstance(valeur, (bytes, bytearray)):
        return None
    return valeur


def _preparer_repertoire(destination):
    if os.path.isdir(destination) and os.listdir(destination):
        raise ErreurMoteur("repertoire_non_vide", destination)
    os.makedirs(destination, mode=0o700, exist_ok=True)


def _convertir_vers_repertoire(destination, feuilles, options, noms=None):
    _preparer_repertoire(destination)
    pris = set()
    ecrits = []
    for feuille in feuilles:
        nom = nom_de_fichier_sur(
            (noms or {}).get(feuille.nom, feuille.nom), pris
        )
        cible = os.path.join(destination, f"{nom}.csv")
        ecrits.extend(_ecrire_csv(cible, feuille, options))
    return ecrits


def _convertir_vers_json(destination, feuilles, noms=None):
    sortie = {}
    for feuille in feuilles:
        etiquettes = [
            str(v) if v is not None else f"c{i}"
            for i, v in enumerate(feuille.etiquettes, start=1)
        ]
        enregistrements = []
        for ligne in feuille.lignes[1:]:
            enregistrements.append(
                {
                    etiquettes[i]: valeur_hors_tableur(v)
                    for i, v in enumerate(ligne)
                    if i < len(etiquettes)
                }
            )
        sortie[(noms or {}).get(feuille.nom, feuille.nom)] = enregistrements

    def ecrivain(cible):
        with open(cible, "w", encoding="utf-8") as fh:
            json.dump(sortie, fh, ensure_ascii=False, indent=1)

    _ecrire_atomique(destination, ecrivain)
    return [destination]


def _nom_de_balise_sur(etiquette, rang):
    """Une étiquette rendue légale comme nom d'élément XML.

    XML interdit à un nom de commencer par un chiffre : une colonne
    intitulée « 2024 » produisait `<2024>`, écrit sans broncher, annoncé
    comme écrit, et refusé par tout analyseur — y compris celui du dépôt.
    """
    brut = re.sub(r"[^A-Za-z0-9_.-]", "_", str(etiquette or "")).strip("_")
    if not brut:
        return f"c{rang}"
    if not re.match(r"[A-Za-z_]", brut[0]):
        return f"c{rang}_{brut}"
    return brut


def _convertir_vers_xml(destination, feuilles):
    if len(feuilles) > 1:
        raise ErreurMoteur("format_inconnu", "xml")
    feuille = feuilles[0]
    racine = ET.Element("table")
    etiquettes = [
        _nom_de_balise_sur(v, i)
        for i, v in enumerate(feuille.etiquettes, start=1)
    ]
    for ligne in feuille.lignes[1:]:
        noeud = ET.SubElement(racine, "ligne")
        for index, valeur in enumerate(ligne):
            if index >= len(etiquettes):
                continue
            champ = ET.SubElement(noeud, etiquettes[index])
            rendu = valeur_hors_tableur(valeur)
            champ.text = "" if rendu is None else str(rendu)

    def ecrivain(cible):
        ET.ElementTree(racine).write(
            cible, encoding="utf-8", xml_declaration=True
        )

    _ecrire_atomique(destination, ecrivain)
    return [destination]
