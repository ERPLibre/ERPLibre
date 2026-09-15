#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'un appel d'outil a fait : sa commande, et ce qu'elle a répondu.

**Ce module MONTRE du contenu, et c'est le seul du paquet.** Partout ailleurs,
un écran affiche un chemin, un nom, un compte, une taille ou une durée, jamais
un champ de texte libre. Ici la commande shell et sa sortie paraissent en
entier, parce que « Bash · 1,2 s · échec » dit qu'une chose a raté sans dire
laquelle. La frontière se déplace donc, et il faut dire exactement où :

- ce qui est montré n'est jamais ÉCRIT — ni dans le journal des hooks, ni
  dans un fichier du dépôt, ni dans un message de commit ;
- l'écran qui s'en sert le DIT, pour qu'un partage d'écran ne se fasse pas
  par distraction.

**Rien n'est collecté pour ça.** Le journal des hooks garde `tool_use_id` et
rien d'autre de l'appel : pas la commande, pas la réponse. Ce module va les
chercher dans la TRANSCRIPTION, où Claude Code les a déjà écrites, au moment
où quelqu'un les demande. Écrire `tool_input` dans le journal mettrait chaque
commande de la machine sur le disque pour quatorze jours, ce qui est garder et
non montrer.

**Le balayage est bon marché, contre toute attente.** Une transcription pèse
des dizaines de mégaoctets, mais un identifiant d'appel est une chaîne rare :
le pré-filtre par sous-chaîne écarte tout sans décoder, et retrouver un appel
dans trente mégaoctets prend trois centièmes de seconde. Décoder chaque ligne
prendrait mille fois plus.

La transcription porte les deux moitiés dans des messages DIFFÉRENTS : le bloc
`tool_use` dans un message d'assistant, le `tool_result` dans la réponse de
l'utilisateur. Les deux se rejoignent par l'identifiant, et une moitié peut
manquer — un appel encore en cours n'a pas de résultat.
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass

# Où Claude Code écrit ses transcriptions. DEUX endroits, et l'oubli du second
# laisse un appel sur trois introuvable : les outils lancés par un SOUS-AGENT
# s'écrivent dans son propre fichier, sous le répertoire de la session, alors
# que le hook les annonce sous l'identifiant de la session PARENTE.
TRANSCRIPTIONS = "~/.claude/projects/*/{session}.jsonl"
SOUS_AGENTS = "~/.claude/projects/*/{session}/**/*.jsonl"

# Ce qu'on montre au plus d'une sortie. Au-delà, on ne lit plus : le volet
# répond à « qu'est-ce qui a raté », pas à « tout ce qui est sorti ».
SORTIE_MAX = 4000

# La commande réduite à une ligne de tableau. Les sauts de ligne y sont
# écrasés : une commande multiligne casserait la rangée en trois.
COLONNE_MAX = 60


@dataclass(frozen=True)
class Detail:
    """Une commande et sa réponse, telles que la transcription les porte.

    `sortie` vaut None quand le résultat manque — un appel en cours, ou une
    transcription qu'on n'a pas su lire. Une chaîne vide dirait « la commande
    n'a rien répondu », ce qui est une autre chose.
    """

    outil: str = ""
    commande: str = ""
    description: str = ""
    sortie: str | None = None
    erreur: bool = False

    @property
    def trouve(self) -> bool:
        """Vrai si la transcription a rendu au moins la commande."""
        return bool(self.outil or self.commande)


def chemins_de_session(session, *, motifs=None, lister=None) -> list[str]:
    """Les fichiers où chercher un appel de cette session, le principal d'abord.

    Trouvés par l'identifiant et non par le nom de répertoire de projet :
    celui-ci encode le chemin de travail en tirets, et la transformation ne
    s'inverse pas.

    Les transcriptions de SOUS-AGENTS suivent, et les oublier laisse un appel
    sur trois introuvable : un outil lancé par un sous-agent s'écrit dans le
    fichier de celui-ci, tandis que le hook l'annonce sous l'identifiant de la
    session parente. Elles viennent après parce qu'elles sont nombreuses et
    petites, là où la principale est unique et grosse.
    """
    if not session:
        return []
    lister = lister or glob.glob
    chemins = []
    for motif in motifs or (TRANSCRIPTIONS, SOUS_AGENTS):
        trouves = lister(
            os.path.expanduser(motif.format(session=session)), recursive=True
        )
        chemins.extend(sorted(t for t in trouves if t not in chemins))
    return chemins


def _entree(bloc) -> tuple[str, str]:
    """(commande, description) d'un bloc `tool_use`, quel que soit l'outil.

    `command` est le champ de Bash ; les autres outils nomment leur argument
    autrement, et il vaut mieux montrer le premier champ textuel que rien.
    """
    entree = bloc.get("input")
    if not isinstance(entree, dict):
        return "", ""
    description = entree.get("description")
    description = description if isinstance(description, str) else ""
    commande = entree.get("command")
    if isinstance(commande, str):
        return commande, description
    for cle in ("file_path", "pattern", "prompt", "path", "query", "url"):
        valeur = entree.get(cle)
        if isinstance(valeur, str) and valeur:
            return valeur, description
    return "", description


def _sortie(bloc) -> str:
    """Le contenu d'un `tool_result`, quelle que soit sa forme.

    Il vient en chaîne, ou en liste de blocs dont seuls les textuels comptent.
    Une forme inattendue rend le vide plutôt que son `repr`, qui afficherait
    du Python à un lecteur qui attend une sortie de commande.
    """
    contenu = bloc.get("content")
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        morceaux = [
            m.get("text")
            for m in contenu
            if isinstance(m, dict) and isinstance(m.get("text"), str)
        ]
        return "\n".join(morceaux)
    return ""


def replier(detail: Detail, objet, identifiant: str) -> Detail:
    """Replier UNE ligne décodée sur l'appel cherché. Fonction PURE.

    Les deux moitiés vivent dans des messages différents, donc cette fonction
    est appelée sur toute la transcription et ne retient que ce qui porte
    l'identifiant.
    """
    if not isinstance(objet, dict):
        return detail
    message = objet.get("message")
    if not isinstance(message, dict):
        return detail
    for bloc in message.get("content") or ():
        if not isinstance(bloc, dict):
            continue
        genre = bloc.get("type")
        if genre == "tool_use" and bloc.get("id") == identifiant:
            commande, description = _entree(bloc)
            nom = bloc.get("name")
            detail = Detail(
                outil=nom if isinstance(nom, str) else "",
                commande=commande,
                description=description,
                sortie=detail.sortie,
                erreur=detail.erreur,
            )
        elif genre == "tool_result" and bloc.get("tool_use_id") == identifiant:
            detail = Detail(
                outil=detail.outil,
                commande=detail.commande,
                description=detail.description,
                sortie=_sortie(bloc),
                erreur=bool(bloc.get("is_error")),
            )
    return detail


def lire(chemin, identifiant, *, ouvrir=None) -> Detail:
    """La commande et la réponse d'un appel, cherchées dans un fichier.

    Le pré-filtre par sous-chaîne est ce qui rend l'opération gratuite :
    décoder chaque ligne d'une transcription de trente mégaoctets prendrait
    mille fois plus que de n'en décoder que les trois qui portent la chaîne
    cherchée.
    """
    if not chemin or not identifiant:
        return Detail()
    if ouvrir is None:

        def ouvrir(nom):
            return open(nom, encoding="utf-8", errors="replace")

    detail = Detail()
    try:
        with ouvrir(chemin) as fh:
            for ligne in fh:
                if identifiant not in ligne:
                    continue
                try:
                    detail = replier(detail, json.loads(ligne), identifiant)
                except (ValueError, TypeError):
                    continue
    except OSError:
        return detail
    return detail


def pour(appel, *, motifs=None, lister=None, ouvrir=None) -> Detail:
    """Le détail d'un `Appel` du journal, ou un détail vide.

    Les fichiers sont essayés dans l'ordre et la recherche S'ARRÊTE au premier
    qui répond : un identifiant d'appel n'est écrit qu'une fois, et balayer la
    suite ne changerait rien qu'en temps.
    """
    identifiant = getattr(appel, "identifiant", "")
    for chemin in chemins_de_session(
        getattr(appel, "session", ""), motifs=motifs, lister=lister
    ):
        detail = lire(chemin, identifiant, ouvrir=ouvrir)
        if detail.trouve:
            return detail
    return Detail()


def une_ligne(texte, largeur=COLONNE_MAX) -> str:
    """Un texte réduit à UNE ligne de tableau. Fonction PURE.

    Les blancs sont écrasés avant la coupe : une commande multiligne casserait
    la rangée en trois, et couper d'abord laisserait un saut de ligne dans les
    soixante premiers caractères.
    """
    if not texte:
        return ""
    plat = " ".join(str(texte).split())
    if len(plat) <= largeur:
        return plat
    return plat[: max(1, largeur - 1)] + "…"


def bornee(texte, maximum=SORTIE_MAX) -> str:
    """Une sortie bornée, qui DIT ce qu'elle a coupé.

    Couper en silence ferait lire une sortie tronquée comme une sortie
    complète, et chercher une erreur dans ce qui n'est plus affiché.
    """
    if texte is None:
        return ""
    texte = str(texte)
    if len(texte) <= maximum:
        return texte
    reste = len(texte) - maximum
    return f"{texte[:maximum]}\n… (+{reste})"
