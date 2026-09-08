#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le catalogue d'outils gpt : un fichier Markdown par outil.

Un gpt porte un en-tête YAML — identité, exigences, paramètres du modèle,
entrées, contexte déclaré — puis un corps coupé par des marqueurs en deux
parties : l'invite système et le gabarit de question. RIEN dans un gpt ne
s'exécute au nom du modèle : le contexte déclaré est LU, jamais évalué, et
c'est `context.py` qui décide ce qu'il a le droit de lire.

Le corps se coupe par des marqueurs `<!-- [x] -->` plutôt que par des
scalaires YAML : le dépôt lit déjà cette forme dans ses `.base.md`, et une
longue prose dans un bloc YAML est là où vivent les fautes d'indentation.

**`yaml.safe_load` n'est pas un validateur**, et c'est la contrainte qui
gouverne ce module. Un en-tête qui est une LISTE rend une `list`, un scalaire
nu rend une `str`, un fichier vide rend `None`, et une clé RÉPÉTÉE est résolue
en silence sur la dernière. Aucun de ces quatre cas ne lève.
Le dernier est le pire : deux blocs `requires` font passer un gpt de
`loopback` à `any` sans un mot, donc changent sa classe de sûreté. D'où un
contrôle de TYPE, et une relecture du texte BRUT à la recherche des clés
répétées, avant toute lecture de champ.

**Un fichier abîmé ne casse jamais le menu.** Chaque gpt est analysé dans son
propre rattrapage, les échecs s'accumulent dans une liste de problèmes, et le
catalogue s'affiche avec ce qui reste. Jamais fatal, jamais silencieux non
plus : un outil cassé qui se tait se confond avec un outil absent.

Les problèmes portent une CLÉ d'internationalisation et non une phrase :
l'affichage appartient au menu, comme pour la raison que rend
`capabilities.match`.

Deux racines, la seconde l'emportant par nom de fichier. Celle du dépôt est
publique et ne porte rien d'identifiant ; celle de l'utilisateur vit sous son
répertoire personnel, n'est jamais versionnée, et n'a passé aucune relecture —
d'où deux restrictions sur elle : `hosting` y est forcé à `loopback`, et un
gpt qui y déclarerait une COMMANDE est refusé. Un fichier qu'on n'a pas relu
n'est pas une donnée, c'est de la configuration exécutable.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# La version du schéma que ce module sait lire. Un fichier qui en annonce une
# plus récente est GRISÉ avec sa raison, jamais deviné : deviner un champ dont
# on ne connaît pas le sens est la façon la plus sûre de trahir un gpt.
SCHEMA = 1

# Les marqueurs qui coupent le corps. Le gabarit de question est OBLIGATOIRE —
# sans lui, un gpt n'a rien à demander au modèle et n'est qu'une invite.
MARQUEUR_SYSTEME = "<!-- [system] -->"
MARQUEUR_QUESTION = "<!-- [question] -->"

# `make doc_markdown` ne balaie que les `*.base.md` : un gpt ainsi nommé
# serait réécrit par la chaîne de documentation, qui y verrait une source
# bilingue. Le suffixe est donc refusé au chargement plutôt que découvert au
# prochain `make doc_markdown`.
SUFFIXE_INTERDIT = ".base.md"

# L'extension d'un gpt, et la seule.
SUFFIXE = ".md"

# Le répertoire des gpts de l'utilisateur, sous son répertoire personnel.
RACINE_UTILISATEUR = "~/.erplibre/gpt"

# Les clés attendues à la racine de l'en-tête. Une clé inconnue n'est pas une
# erreur — le schéma peut grandir — mais elle est SIGNALÉE, parce qu'une faute
# de frappe sur « requires » retirerait toutes les exigences en silence.
CLES_CONNUES = frozenset(
    {
        "gpt",
        "name",
        "name_fr",
        "description",
        "requires",
        "params",
        "inputs",
        "context",
    }
)

# Une clé de premier niveau dans le texte BRUT de l'en-tête : en début de
# ligne, sans indentation. C'est ce qui permet de voir une répétition que
# `yaml.safe_load` a déjà écrasée.
CLE_BRUTE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:", re.MULTILINE)

# Le séparateur d'en-tête, en tête de fichier puis en fermeture.
BORNE = "---"

# Les problèmes que le chargement peut rendre. Nommés une fois ici : le
# module les rend, le test les lit, et une reformulation ne peut pas faire
# diverger les deux. Ce sont des clés d'internationalisation, donc la
# chaîne anglaise elle-même — `t()` rend une clé absente inchangée, ce qui
# dégrade en anglais correct plutôt qu'en jargon.
SANS_ENTETE = "No front-matter: a gpt opens with ---"
ENTETE_NON_FERMEE = "Front-matter is not closed"
ENTETE_PAS_UN_DICTIONNAIRE = "Front-matter is not a mapping"
ENTETE_ILLISIBLE = "Front-matter is unreadable"
CLE_REPETEE = "Repeated key in front-matter:"
SCHEMA_ABSENT = "No schema version: gpt is required"
SCHEMA_TROP_RECENT = "Schema too recent for this version of TODO"
NOM_ABSENT = "No name"
DESCRIPTION_ABSENTE = "No description"
MARQUEUR_QUESTION_ABSENT = "Missing marker <!-- [question] -->"
CLE_INCONNUE = "Unknown key in front-matter:"
NAME_FR_HORS_PLACE = "name_fr belongs in the translations file"
HORS_DEPOT_SANS_COMMANDE = (
    "A gpt from outside the repository may not declare any command."
)
ECRASE = "Overrides the one from"
FICHIER_ILLISIBLE = "Unreadable file:"
NOM_BASE_MD_REFUSE = "A gpt may not be named *.base.md"
PYYAML_ABSENT = (
    "PyYAML is missing: the gpt catalogue stays closed, the free question"
    " works."
)


@dataclass(frozen=True)
class Probleme:
    """Ce qui empêche un gpt d'être utilisable, ou mérite d'être relu.

    `key` est une clé d'internationalisation et `detail` le fragment concret
    à montrer à côté — un nom de clé répétée, une valeur refusée. Le menu
    traduit la première et imprime la seconde telle quelle.

    `fatal` distingue un gpt qui ne se charge pas d'un gpt utilisable dont
    quelque chose est à relire : le premier disparaît du catalogue, le second
    y reste avec sa remarque.
    """

    stem: str
    key: str
    detail: str = ""
    fatal: bool = True


@dataclass
class Gpt:
    """Un outil du catalogue, tel que son fichier le déclare.

    `stem` est le nom de fichier sans extension, et c'est l'IDENTITÉ : il n'y
    a pas de champ `id`, parce que deux sources de vérité pour un nom finissent
    par diverger. Renommer le fichier renomme le gpt.

    `name` et `description` portent la chaîne ANGLAISE, qui EST la clé
    d'internationalisation — `t()` rend une clé inconnue inchangée, donc un
    gpt non traduit s'affiche en anglais au lieu de rien.
    """

    stem: str
    name: str
    description: str
    system: str = ""
    question: str = ""
    requires: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    inputs: tuple = ()
    context: dict = field(default_factory=dict)
    name_fr: str = ""
    root: str = ""
    from_repo: bool = True


def repo_root() -> Path:
    """La racine des gpts livrés avec le dépôt.

    Dérivée de l'emplacement de ce module plutôt que d'un chemin écrit :
    le paquet reste déplaçable, et un checkout ailleurs fonctionne sans
    réglage.
    """
    return Path(__file__).resolve().parent / "gpt"


def default_roots(*, home=None) -> list[Path]:
    """Les racines à charger, dans l'ordre où elles se recouvrent.

    Celle du dépôt d'abord, celle de l'utilisateur ensuite : à nom de fichier
    égal, la seconde l'emporte, ce qui permet d'adapter un gpt livré sans
    modifier un fichier versionné.

    Chaque racine est rendue avec sa CONFIANCE : le dépôt est relu, le
    répertoire de l'utilisateur non. La confiance est une donnée et non une
    comparaison de chemins — déduite, elle serait indéductible en test, et un
    chargeur qu'on ne peut pas exercer sur ses deux niveaux de confiance
    n'exerce en pratique que le permissif.

    `home` remplace le répertoire personnel, pour qu'un test n'aille pas lire
    celui de la machine qui le lance.
    """
    base = Path(home) if home else Path(os.path.expanduser("~"))
    utilisateur = base / RACINE_UTILISATEUR.removeprefix("~/")
    return [(repo_root(), True), (utilisateur, False)]


def parse(text, *, stem, from_repo=True):
    """Un gpt et ses problèmes, lus dans `text`. Fonction PURE.

    Rend `(gpt, problemes)`. `gpt` vaut `None` quand un problème fatal
    empêche de le construire ; les problèmes non fatals accompagnent un gpt
    utilisable.
    """
    problemes: list[Probleme] = []

    def refus(key, detail=""):
        problemes.append(Probleme(stem, key, detail))
        return None, problemes

    entete_brute, corps, erreur = _decouper(text or "")
    if erreur:
        return refus(erreur)

    repetee = _cle_repetee(entete_brute)
    if repetee:
        # Écrasée en silence par l'analyseur : la valeur retenue est la
        # DERNIÈRE, donc un second bloc `requires` change la classe de sûreté
        # du gpt sans que rien ne le dise.
        return refus(CLE_REPETEE, repetee)

    entete, erreur = _charger_yaml(entete_brute)
    if erreur:
        return refus(erreur)
    if not isinstance(entete, dict):
        return refus(ENTETE_PAS_UN_DICTIONNAIRE, type(entete).__name__)

    version = entete.get("gpt")
    if not isinstance(version, int) or isinstance(version, bool):
        return refus(SCHEMA_ABSENT)
    if version > SCHEMA:
        return refus(SCHEMA_TROP_RECENT, str(version))

    name = _texte(entete.get("name"))
    if not name:
        return refus(NOM_ABSENT)
    description = _texte(entete.get("description"))
    if not description:
        return refus(DESCRIPTION_ABSENTE)

    if MARQUEUR_QUESTION not in corps:
        return refus(MARQUEUR_QUESTION_ABSENT)
    system, question = _corps(corps)

    for clef in sorted(set(entete) - CLES_CONNUES):
        # Pas une erreur — le schéma peut grandir — mais une faute de frappe
        # sur « requires » retirerait toutes les exigences sans un mot.
        problemes.append(Probleme(stem, CLE_INCONNUE, clef, fatal=False))

    requires = _mapping(entete.get("requires"))
    params = _mapping(entete.get("params"))
    context = _mapping(entete.get("context"))
    name_fr = _texte(entete.get("name_fr"))

    if from_repo and name_fr:
        # Dans le dépôt, la traduction vit dans le fichier des traductions,
        # qui est la source unique. Un `name_fr` ici en créerait une seconde.
        problemes.append(Probleme(stem, NAME_FR_HORS_PLACE, "", False))
    if not from_repo:
        if context.get("commands"):
            # Un fichier hors du dépôt n'a passé aucune relecture : lui
            # laisser déclarer une commande en ferait de la configuration
            # exécutable, et la liste d'autorisation vit dans le dépôt.
            return refus(HORS_DEPOT_SANS_COMMANDE)
        requires = dict(requires)
        requires["hosting"] = "loopback"

    gpt = Gpt(
        stem=stem,
        name=name,
        description=description,
        system=system,
        question=question,
        requires=requires,
        params=params,
        inputs=_entrees(entete.get("inputs")),
        context=context,
        name_fr=name_fr,
        from_repo=from_repo,
    )
    return gpt, problemes


def load_all(*, roots=None, read=None, home=None):
    """Le catalogue et ses problèmes, lus dans les racines.

    Rend `(gpts, problemes)`, les gpts triés par nom de fichier. Une racine
    absente n'est pas une erreur : le répertoire de l'utilisateur n'existe
    d'ordinaire pas.

    `read(chemin)` rend le texte d'un fichier, et `roots` remplace la liste
    des racines par des couples (chemin, relu) : les deux coutures permettent
    à un test de décrire un catalogue entier, aux deux niveaux de confiance,
    sans toucher au disque de la machine.

    Sans PyYAML, le catalogue rend une liste VIDE et un seul problème qui le
    dit. Le catalogue est un supplément ; la question libre, elle, marche sans
    lui.
    """
    problemes: list[Probleme] = []
    if not _yaml_disponible():
        return [], [
            Probleme(
                "",
                PYYAML_ABSENT,
                "",
                True,
            )
        ]

    lecteur = read or _lire
    trouves: dict[str, Gpt] = {}
    sources = roots if roots is not None else default_roots(home=home)
    for racine, depot in sources:
        racine = Path(racine)
        for chemin in _fichiers(racine):
            stem = chemin.name[: -len(SUFFIXE)]
            if chemin.name.endswith(SUFFIXE_INTERDIT):
                problemes.append(
                    Probleme(stem, NOM_BASE_MD_REFUSE, chemin.name)
                )
                continue
            try:
                texte = lecteur(chemin)
            except OSError as panne:
                problemes.append(Probleme(stem, FICHIER_ILLISIBLE, str(panne)))
                continue
            try:
                gpt, soucis = parse(texte, stem=stem, from_repo=depot)
            except Exception as panne:  # pragma: no cover - filet
                # Le filet de sécurité : une forme d'en-tête imprévue ne doit
                # pas emporter le catalogue entier avec elle.
                problemes.append(Probleme(stem, FICHIER_ILLISIBLE, str(panne)))
                continue
            problemes.extend(soucis)
            if gpt is None:
                continue
            gpt.root = str(racine)
            if stem in trouves:
                problemes.append(
                    Probleme(
                        stem,
                        ECRASE,
                        trouves[stem].root,
                        fatal=False,
                    )
                )
            trouves[stem] = gpt
    return [trouves[cle] for cle in sorted(trouves)], problemes


def _fichiers(racine):
    """Les fichiers `.md` d'une racine, triés. Vide si elle n'existe pas.

    Sans récursion : un catalogue plat se lit d'un coup d'œil, et un
    sous-répertoire y cacherait un gpt.
    """
    try:
        return sorted(
            chemin
            for chemin in racine.iterdir()
            if chemin.is_file() and chemin.name.endswith(SUFFIXE)
        )
    except OSError:
        return []


def _lire(chemin):
    """Le texte d'un fichier de gpt."""
    return Path(chemin).read_text(encoding="utf-8")


def _yaml_disponible():
    """PyYAML est-il là ? Son absence ferme le catalogue, pas le menu."""
    try:
        import yaml  # noqa: F401
    except ImportError:
        return False
    return True


def _decouper(text):
    """(en-tête brut, corps, clé d'erreur) — la coupe du fichier.

    L'en-tête ouvre le fichier et se ferme sur une ligne de bornes. Un
    fichier sans en-tête est refusé plutôt que traité comme un corps nu : un
    gpt sans exigences ni identité n'est pas un gpt.
    """
    lignes = text.splitlines()
    if not lignes or lignes[0].strip() != BORNE:
        return "", "", SANS_ENTETE
    for rang in range(1, len(lignes)):
        if lignes[rang].strip() == BORNE:
            return (
                "\n".join(lignes[1:rang]),
                "\n".join(lignes[rang + 1 :]),
                "",
            )
    return "", "", ENTETE_NON_FERMEE


def _cle_repetee(entete_brute):
    """La première clé de premier niveau qui paraît deux fois, ou "".

    Lue dans le texte BRUT : l'analyseur YAML a déjà écrasé la première
    occurrence quand on lui pose la question, donc lui demander ne sert à
    rien.
    """
    vues = set()
    for nom in CLE_BRUTE.findall(entete_brute):
        if nom in vues:
            return nom
        vues.add(nom)
    return ""


def _charger_yaml(entete_brute):
    """(objet, clé d'erreur) — l'en-tête analysé, ou la raison du refus."""
    import yaml

    try:
        return yaml.safe_load(entete_brute), ""
    except yaml.YAMLError:
        return None, ENTETE_ILLISIBLE


def _corps(corps):
    """(invite système, gabarit de question) — le corps coupé.

    L'invite système est ce qui précède le marqueur de question, son propre
    marqueur retiré s'il est présent. Le marqueur de question a déjà été
    exigé par l'appelant.
    """
    avant, _, apres = corps.partition(MARQUEUR_QUESTION)
    avant = avant.replace(MARQUEUR_SYSTEME, "")
    return avant.strip(), apres.strip()


def _mapping(valeur):
    """Le dictionnaire quand c'en est un, sinon un dictionnaire vide.

    Une valeur d'un autre type est JETÉE plutôt que devinée : une liste sous
    `requires` viendrait d'une indentation fautive, et en tirer des exigences
    inventerait une classe de sûreté.
    """
    return dict(valeur) if isinstance(valeur, dict) else {}


def _entrees(valeur):
    """Les entrées déclarées, chacune réduite à un dictionnaire nommé.

    Une entrée sans nom est écartée : elle ne pourrait ni se demander ni se
    substituer dans le gabarit.
    """
    if not isinstance(valeur, list):
        return ()
    gardees = []
    for entree in valeur:
        if isinstance(entree, dict) and _texte(entree.get("name")):
            gardees.append(dict(entree))
    return tuple(gardees)


def _texte(valeur):
    """La valeur quand c'est une chaîne non vide, sans ses bords ; sinon "".

    Une valeur d'un autre type n'est pas passée par `str()` : la
    représentation d'un dictionnaire entrerait dans un libellé de menu, et de
    là dans une clé de traduction.
    """
    return valeur.strip() if isinstance(valeur, str) else ""
