#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les agents spécialisés que ce dépôt déclare, et ce qu'ils annoncent.

Un agent est un fichier Markdown dont l'en-tête dit son nom, son rôle, son
modèle et les outils qu'on lui confie ; le corps est son invite système. Ce
module ne lit que l'EN-TÊTE : le corps part au harnais tel quel, et le relire
ici n'apprendrait rien qu'on affiche.

**L'en-tête se lit à la main, sans bibliothèque YAML.** Deux formes y
suffisent — `clé: valeur` et `clé: [a, b, c]` — et les deux se lisent en dix
lignes. Tirer une dépendance pour cela la ferait payer à tout ce qui importe
le paquet, y compris au menu qui ne demande qu'une liste de noms. Une forme
que ce lecteur ne connaît pas est IGNORÉE plutôt que devinée : un agent dont
l'en-tête sort de l'ordinaire paraît alors sans ce champ-là, ce qui se voit,
au lieu de porter une valeur inventée, qui ne se voit pas.

**Deux origines, et le dépôt gagne.** Un agent peut venir du dépôt — il suit
alors le code et vaut pour tout le monde — ou du dossier personnel, où il
n'engage que son auteur. À nom égal, celui du dépôt l'emporte, comme le fait
le harnais lui-même : afficher les deux ferait choisir entre deux entrées
identiques dont une seule sera lue.

**Rien ici ne lance quoi que ce soit.** Le catalogue décrit ; c'est le menu
qui demande, et le harnais qui exécute.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# Où les agents se déclarent. Le premier est celui du dépôt, le second celui
# de l'utilisateur ; l'ordre EST la priorité.
DOSSIERS = (
    (".claude", "agents"),
    ("~", ".claude", "agents"),
)

# La borne de l'en-tête : une ligne de trois tirets, seule. Le corps commence
# après la seconde.
BORNE = "---"

# Une entrée d'en-tête : une clé en minuscules, deux-points, le reste. Ce qui
# n'a pas cette forme — une liste sur plusieurs lignes, un bloc indenté —
# n'est pas lu, et le champ manque plutôt que de valoir une devinette.
ENTREE = re.compile(r"^([a-z][a-z0-9_-]*)\s*:\s*(.*)$")

# La longueur d'un rôle dans une liste. Une description tient en plusieurs
# phrases ; une ligne de menu n'en montre que la première, bornée.
ROLE_MAX = 72


@dataclass(frozen=True)
class Specialiste:
    """Un agent déclaré, tel que son en-tête le décrit.

    `cle` est le RADICAL du fichier, et c'est lui qu'on passe au harnais :
    le champ `name` peut en différer, et c'est le nom de fichier qui fait foi
    pour qui va le chercher.

    `modele` et `outils` valent la chaîne vide et le tuple vide quand
    l'en-tête ne les déclare pas — ce qui est normal, un agent héritant alors
    de ce que le harnais lui donne.
    """

    cle: str
    nom: str
    description: str
    modele: str
    outils: tuple[str, ...]
    origine: str
    chemin: str


def entete(texte: str) -> dict:
    """Les champs de l'en-tête d'un fichier d'agent. Fonction PURE.

    Rend `{}` quand le texte n'ouvre pas sur une borne : un Markdown sans
    en-tête n'est pas un agent, et le lire quand même rendrait des champs
    tirés de son corps.
    """
    lignes = (texte or "").splitlines()
    if not lignes or lignes[0].strip() != BORNE:
        return {}
    champs = {}
    for ligne in lignes[1:]:
        if ligne.strip() == BORNE:
            break
        trouve = ENTREE.match(ligne)
        if trouve:
            champs[trouve.group(1)] = trouve.group(2).strip()
    return champs


def liste(valeur: str) -> tuple[str, ...]:
    """Une liste `[a, b, c]` en tuple de chaînes. Fonction PURE.

    Une valeur qui n'est pas entre crochets rend un tuple d'un seul élément :
    un en-tête qui déclare un outil unique sans crochets reste lisible.
    """
    brut = (valeur or "").strip()
    if brut.startswith("[") and brut.endswith("]"):
        brut = brut[1:-1]
    trouves = [part.strip() for part in brut.split(",")]
    return tuple(part for part in trouves if part)


def role(description: str, largeur: int = ROLE_MAX) -> str:
    """La première phrase d'une description, bornée. Fonction PURE.

    Ce qui suit la première phrase explique QUAND appeler l'agent ; une ligne
    de liste n'a la place que de dire ce qu'il fait.
    """
    plat = " ".join((description or "").split())
    if not plat:
        return ""
    tete = plat.split(". ", 1)[0].rstrip(".")
    if len(tete) > largeur:
        return tete[: largeur - 1] + "…"
    return tete


def lire(chemin, origine="") -> Specialiste | None:
    """Un agent depuis son fichier, ou None s'il n'en est pas un.

    Rend None sur un fichier illisible comme sur un Markdown sans en-tête :
    un dossier d'agents peut contenir un README, et le proposer au menu
    ferait lancer un harnais sur un fichier qui n'est pas une consigne.
    """
    cible = Path(chemin)
    try:
        texte = cible.read_text(encoding="utf-8")
    except OSError:
        return None
    champs = entete(texte)
    if not champs.get("name"):
        return None
    return Specialiste(
        cle=cible.stem,
        nom=champs.get("name", ""),
        description=champs.get("description", ""),
        modele=champs.get("model", ""),
        outils=liste(champs.get("tools", "")),
        origine=origine,
        chemin=str(cible),
    )


def dossiers(racine=None) -> list[tuple[str, Path]]:
    """Les dossiers d'agents, dans l'ordre de priorité. Jamais None.

    `racine` remplace celle du dépôt ; le dossier personnel suit toujours,
    sauf quand `racine` le porte aussi — un test qui les veut tous les deux
    les nomme lui-même.
    """
    trouves = []
    for parts in DOSSIERS:
        if parts[0] == "~":
            chemin = Path(os.path.expanduser(os.path.join(*parts)))
            trouves.append(("personnel", chemin))
        else:
            base = Path(racine) if racine else _repo()
            trouves.append(("dépôt", base.joinpath(*parts)))
    return trouves


def _repo() -> Path:
    """La racine du dépôt, sans passer par le CLI."""
    from script.todo.assistant.context import repo_root

    return repo_root()


def catalogue(*, racine=None, chemins=None) -> list[Specialiste]:
    """Les agents connus, par nom, le dépôt l'emportant sur le personnel.

    `chemins` remplace la découverte par une suite `(origine, dossier)`, ce
    qui permet de l'éprouver sans toucher ni au dépôt ni au dossier
    personnel de qui lance les tests.
    """
    vus: dict[str, Specialiste] = {}
    for origine, dossier in chemins or dossiers(racine):
        try:
            fichiers = sorted(Path(dossier).glob("*.md"))
        except OSError:
            continue
        for fichier in fichiers:
            un = lire(fichier, origine=origine)
            # Le PREMIER dossier gagne : la découverte les rend dans l'ordre
            # de priorité, donc ne rien écraser suffit à la tenir.
            if un is not None and un.cle not in vus:
                vus[un.cle] = un
    return sorted(vus.values(), key=lambda un: un.cle)
