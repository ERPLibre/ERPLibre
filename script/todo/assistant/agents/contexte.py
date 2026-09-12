#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'une session porte comme contexte, lu dans sa transcription.

À ne pas confondre avec `Afficher le contexte fourni à Claude`, qui décrit ce
que LE DÉPÔT offre à n'importe quelle session — le `CLAUDE.md`, les règles,
les skills, les commandes déployées. Ici c'est l'inverse : ce que CETTE
session-là a réellement chargé, le modèle qui lui répond, la machine qu'elle
voit. Les deux écrans sont complémentaires et ne partagent aucun champ.

**Un delta n'est pas un état, et c'est le piège principal.** Plusieurs de ces
enregistrements sont émis à répétition et ne portent qu'un changement. Lire la
dernière occurrence donne « un fichier d'instructions » là où sept sont
chargés, et « une skill » là où trente-neuf le sont. Deux formes se
distinguent :

- `skill_listing` porte `isInitial` : l'entrée initiale fait autorité, et les
  suivantes sont des changements. Le compte vient donc de l'initiale.
- `instructions` renvoie, en cours de session, les seuls fichiers CHANGÉS.
  Remplacer la liste fait tomber une session de sept fichiers à un seul.
  L'accumulation se fait donc par chemin.
- `command_permissions` ne porte QUE `allowedTools` — ni marqueur initial, ni
  ajout, ni retrait. Ses tailles successives redescendent — 10, 0, 0, 6, 6,
  11, 6, 6, 11 sur une session réelle — donc ce n'est pas un
  cumul, et rien ne dit si une entrée ajoute ou remplace. Aucun total n'est
  donc affiché — seulement le NOMBRE d'annonces et la taille de la dernière,
  ce qui est vrai sans supposer la sémantique.

**Rien de ce qui est du texte libre ne sort.** La règle du paquet disait « la
structure oui, le contenu d'un message non ». Elle ne suffit plus : la
transcription porte maintenant le contenu intégral des fichiers d'instructions,
celui des skills, l'invite système en quinze chaînes, et la sortie brute des
hooks — qui ne sont pas des messages et passeraient la règle telle qu'énoncée.
La forme opérante ici : on affiche un chemin, un nom, un compte, une taille ou
une durée, jamais un champ dont la valeur est du texte libre de longueur non
bornée.

**Tout ceci dépend de la version du CLI.** Une session lancée par une version
antérieure ne porte pas ces enregistrements : une session lancée par une
version assez ancienne n'a aucun `instructions`. L'absence se DIT, elle ne
s'affiche pas en zéro.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace

# Les sous-types d'`attachment` que ce module lit. Tout le reste est ignoré
# sans bruit : une transcription en porte une trentaine, et le module n'a
# aucune raison de connaître les autres.
LUS = (
    "instructions",
    "skill_listing",
    "command_permissions",
    "environment",
    "model",
    "hook_success",
)

# Combien de fichiers d'instructions l'écran nomme avant de compter le reste.
# Sept sur une configuration ordinaire : les lister tous tient, mais la borne
# protège d'une configuration qui en chargerait trente.
INSTRUCTIONS_MAX = 12


@dataclass(frozen=True)
class Fichier:
    """Un fichier d'instructions chargé : son chemin et sa TAILLE.

    Jamais son contenu. La transcription le porte en entier — jusqu'à huit
    mille caractères pour une seule règle — et un écran de menu n'a rien à
    gagner à recopier ce qu'un `cat` donne mieux.
    """

    chemin: str
    octets: int = 0

    @property
    def origine(self) -> str:
        """« utilisateur » ou « dépôt », déduit du CHEMIN.

        Le champ `source` de la transcription vaut `None` : l'origine se lit
        donc dans le chemin, qui est là.
        """
        maison = os.path.expanduser("~/.claude")
        return "utilisateur" if self.chemin.startswith(maison) else "dépôt"


@dataclass(frozen=True)
class Contexte:
    """Ce qu'une session porte. Les champs vides disent « non porté ».

    `porte` distingue « cette version du CLI n'écrit pas cet enregistrement »
    de « la valeur est zéro ». Un écran qui les confond annonce « aucune
    skill » sur une session qui en a trente-neuf.
    """

    modele: str = ""
    modele_id: str = ""
    coupure: str = ""
    plateforme: str = ""
    shell: str = ""
    repertoire: str = ""
    depot_git: bool = False
    worktree: bool = False
    instructions: tuple[Fichier, ...] = ()
    skills: int = -1
    skills_initiales: bool = False
    annonces_permissions: int = 0
    derniere_permission: int = 0
    hooks: tuple[tuple[str, str, str], ...] = ()
    porte: frozenset = field(default_factory=frozenset)

    def a(self, quoi: str) -> bool:
        """Cette session porte-t-elle cet enregistrement ?"""
        return quoi in self.porte


def _texte(valeur) -> str:
    return valeur if isinstance(valeur, str) else ""


def _chiffre(valeur) -> str:
    """Un nombre rendu en texte, et rien d'autre.

    `exitCode` et `durationMs` sont des ENTIERS dans la transcription. Les
    faire passer par `_texte` les rend vides à tous les coups, et la colonne
    d'un hook reste blanche alors que la donnée est là.
    """
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return ""
    return str(valeur)


def replier(contexte: Contexte, objet) -> Contexte:
    """Replier UNE ligne décodée. Fonction pure.

    Ne lit que les lignes `attachment` dont le sous-type est connu. Les
    enregistrements répétés écrasent le précédent, SAUF `skill_listing`, où
    l'entrée initiale fait autorité, et `command_permissions`, qui se compte.
    """
    if not isinstance(objet, dict) or objet.get("type") != "attachment":
        return contexte
    piece = objet.get("attachment")
    if not isinstance(piece, dict):
        return contexte
    genre = piece.get("type")
    if genre not in LUS:
        return contexte
    contexte = replace(contexte, porte=contexte.porte | {genre})

    if genre == "model":
        identite = piece.get("identity")
        if not isinstance(identite, dict):
            return contexte
        return replace(
            contexte,
            modele=_texte(identite.get("marketingName")),
            modele_id=_texte(identite.get("modelId")),
            coupure=_texte(identite.get("knowledgeCutoff")),
        )

    if genre == "environment":
        vue = piece.get("snapshot")
        if not isinstance(vue, dict):
            return contexte
        return replace(
            contexte,
            plateforme=" ".join(
                x
                for x in (
                    _texte(vue.get("platform")),
                    _texte(vue.get("osVersion")),
                )
                if x
            ),
            shell=_texte(vue.get("shell")),
            repertoire=_texte(vue.get("workingDirectory")),
            depot_git=bool(vue.get("isGitRepo")),
            worktree=bool(vue.get("isWorktree")),
        )

    if genre == "instructions":
        # Un enregistrement suivant ne renvoie que les fichiers CHANGÉS :
        # remplacer la liste ferait tomber une session de sept fichiers à un
        # seul. L'accumulation se fait donc par chemin, la dernière taille
        # connue l'emportant, et l'ordre de première apparition est gardé.
        par_chemin = {f.chemin: f for f in contexte.instructions}
        for f in piece.get("files") or ():
            if not isinstance(f, dict):
                continue
            chemin = _texte(f.get("path"))
            if not chemin:
                continue
            par_chemin[chemin] = Fichier(
                chemin=chemin, octets=len(_texte(f.get("content")))
            )
        return replace(contexte, instructions=tuple(par_chemin.values()))

    if genre == "skill_listing":
        # L'initiale fait autorité : une entrée suivante annonce un
        # changement, et la prendre pour l'état donne « une skill ».
        if contexte.skills_initiales and not piece.get("isInitial"):
            return contexte
        compte = piece.get("skillCount")
        return replace(
            contexte,
            skills=compte if isinstance(compte, int) else -1,
            skills_initiales=bool(piece.get("isInitial")),
        )

    if genre == "command_permissions":
        outils = piece.get("allowedTools")
        return replace(
            contexte,
            annonces_permissions=contexte.annonces_permissions + 1,
            derniere_permission=len(outils) if isinstance(outils, list) else 0,
        )

    if genre == "hook_success":
        entree = (
            _texte(piece.get("hookName")),
            _chiffre(piece.get("exitCode")),
            _chiffre(piece.get("durationMs")),
        )
        if entree in contexte.hooks:
            return contexte
        return replace(contexte, hooks=contexte.hooks + (entree,))

    return contexte


def lire(chemin, *, ouvrir=None) -> Contexte:
    """Le contexte d'une session, lu dans sa transcription.

    Une ligne illisible est sautée : une session qui travaille écrit pendant
    qu'on lit, et sa dernière ligne est régulièrement tronquée.
    """
    if ouvrir is None:

        def ouvrir(nom):
            return open(nom, encoding="utf-8", errors="replace")

    contexte = Contexte()
    try:
        with ouvrir(chemin) as fh:
            for ligne in fh:
                if '"attachment"' not in ligne:
                    continue
                try:
                    contexte = replier(contexte, json.loads(ligne))
                except (ValueError, TypeError):
                    continue
    except OSError:
        return contexte
    return contexte


def instructions_affichables(contexte) -> tuple[tuple[str, str, int], ...]:
    """(chemin abrégé, origine, octets) pour l'écran, borné en nombre.

    Le chemin est abrégé sur la MAISON seulement — jamais sur le dépôt, dont
    le nom est celui du travail en cours et sert à se situer.
    """
    maison = os.path.expanduser("~")
    sorties = []
    for f in contexte.instructions[:INSTRUCTIONS_MAX]:
        chemin = f.chemin
        if chemin.startswith(maison):
            chemin = "~" + chemin[len(maison) :]
        sorties.append((chemin, f.origine, f.octets))
    return tuple(sorties)
