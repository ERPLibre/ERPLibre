#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'une transcription dit d'une session : jetons, coût, durées, contexte.

Le pliage est PUR — `replier` prend un objet déjà décodé et rend un nouvel
agrégat — donc l'arithmétique se vérifie sans toucher au disque. Le seul
morceau qui lit est `lire`, et il est incrémental : il retient l'offset où il
s'est arrêté et ne replie que ce qui a été ajouté depuis.

Deux additions ne se font PAS ici, et c'est délibéré.

Les `cost-state` ne s'additionnent pas. Une transcription en porte plusieurs,
non monotones — une compaction remet le compteur à zéro — et les champs d'un
segment ne se composent pas avec ceux du précédent : la durée d'horloge y
grandit d'un segment au suivant pendant que les lignes de code ajoutées, elles,
diminuent. Le dernier segment est retenu, et l'écran dit que c'en est un.

Les jetons, eux, s'additionnent exactement : chaque message d'assistant
rapporte son propre `usage`, et la somme couvre toute la transcription,
compactions comprises.

Un `usage` porte aussi un champ `iterations`, qui détaille des appels
successifs derrière un seul message. Il n'est PAS lu : le total de tête ne se
retrouve pas dans le premier élément de la liste, donc rien ne dit que les deux
se composent, et additionner les deux compterait les mêmes jetons deux fois.
Le total de tête est ce qui est retenu.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace

# Les champs d'un `usage`, et le nom qu'ils portent dans l'agrégat. Le tableau
# est la seule liste de noms du module : ailleurs on parle de l'agrégat.
USAGE = (
    ("input_tokens", "entree"),
    ("output_tokens", "sortie"),
    ("cache_read_input_tokens", "cache_lu"),
    ("cache_creation_input_tokens", "cache_cree"),
)

# La taille de l'invite d'un tour : ce qui est envoyé au modèle, cache compris.
# C'est la seule mesure de « contexte » que le disque permette.
TAILLE = ("entree", "cache_lu", "cache_cree")

# Combien de tours la série de contexte retient. Une TUI trace une pente, pas
# dix mille points, et une transcription de dix mégaoctets en porte des
# milliers — les garder tous coûterait de la mémoire pour un tracé qui ne
# montrerait rien de plus.
SERIE_MAX = 240


@dataclass(frozen=True)
class Agregat:
    """Ce qui a été compté, et d'où chaque nombre vient.

    Les quatre premiers champs sont des SOMMES exactes de ce que chaque
    message a rapporté. `cout`, les trois durées et les lignes de code sont
    LUS dans le dernier `cost-state` — ils ne sont donc pas calculés ici, et
    `segments` dit combien de fois ce compteur a été remis à zéro.
    """

    tours: int = 0
    entree: int = 0
    sortie: int = 0
    cache_lu: int = 0
    cache_cree: int = 0
    reflexion: int = 0
    compactions: int = 0

    # Lus dans le dernier « cost-state », jamais additionnés entre segments.
    cout: float = 0.0
    duree_horloge: int = 0
    duree_api: int = 0
    duree_outils: int = 0
    lignes_ajoutees: int = 0
    lignes_retirees: int = 0
    segments: int = 0
    par_modele: dict = field(default_factory=dict)

    # La taille de l'invite, tour par tour, tronquée aux derniers SERIE_MAX.
    serie: tuple[int, ...] = ()

    # Deux champs de STRUCTURE, et les deux seuls : le répertoire de travail
    # et la branche git. Ce sont ceux que le module des sessions s'autorise
    # déjà à tirer d'une transcription — jamais un titre, une invite ou un
    # message. Le répertoire est LU ici plutôt que déduit du nom de répertoire
    # de projet, où les séparateurs, les points et les tirets bas sont tous
    # devenus des tirets : cette transformation ne s'inverse pas.
    cwd: str = ""
    branche: str = ""

    @property
    def total_jetons(self) -> int:
        """Tout ce qui a circulé, cache compris."""
        return self.entree + self.sortie + self.cache_lu + self.cache_cree

    @property
    def reutilisation(self) -> float | None:
        """La part de l'invite qui a été relue du cache, ou None sans invite.

        C'est le chiffre qui dit si une session coûte cher pour rien : un
        cache relu ne se repaie pas au prix d'un jeton d'entrée neuf.
        """
        prompt = self.entree + self.cache_lu + self.cache_cree
        if not prompt:
            return None
        return self.cache_lu / prompt

    @property
    def contexte(self) -> int:
        """La taille de la dernière invite, ou 0 si aucun tour n'a eu lieu."""
        return self.serie[-1] if self.serie else 0

    @property
    def pointe(self) -> int:
        """La plus grosse invite vue. Une compaction se lit dans l'écart."""
        return max(self.serie) if self.serie else 0


def _entier(valeur) -> int:
    """Un entier, ou zéro. Un champ absent ou nul ne doit pas lever."""
    return (
        valeur
        if isinstance(valeur, int) and not isinstance(valeur, bool)
        else 0
    )


def _reel(valeur) -> float:
    """Un réel, ou zéro. Le seul champ que `float()` prenait sans filet.

    `replier` n'est pas protégé par l'appelant : `replier_texte` n'entoure que
    le décodage JSON, donc une valeur bien formée mais d'un autre type — un
    objet, une liste — remonterait jusqu'à l'écran vivant et l'éteindrait.
    """
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return 0.0
    return float(valeur)


def _texte(valeur) -> str:
    """Une chaîne, ou vide. Un champ absent ne doit pas devenir « None »."""
    return valeur if isinstance(valeur, str) else ""


def replier(agregat: Agregat, objet) -> Agregat:
    """Replier UNE ligne décodée dans l'agrégat. Fonction pure.

    Trois formes de ligne comptent, et tout le reste est ignoré sans bruit :
    un message d'assistant porteur d'un `usage`, une ligne `cost-state`, et
    un résumé de compaction. Une transcription porte quinze types de ligne, et
    le paquet n'a aucune raison de connaître les douze autres.
    """
    if not isinstance(objet, dict):
        return agregat
    genre = objet.get("type")

    if genre == "cost-state":
        modeles = objet.get("modelUsage")
        return replace(
            agregat,
            cout=_reel(objet.get("totalCostUSD")),
            duree_horloge=_entier(objet.get("totalDuration")),
            duree_api=_entier(objet.get("totalAPIDuration")),
            duree_outils=_entier(objet.get("totalToolDuration")),
            lignes_ajoutees=_entier(objet.get("totalLinesAdded")),
            lignes_retirees=_entier(objet.get("totalLinesRemoved")),
            segments=agregat.segments + 1,
            par_modele=dict(modeles) if isinstance(modeles, dict) else {},
        )

    if not agregat.cwd or not agregat.branche:
        agregat = replace(
            agregat,
            cwd=agregat.cwd or _texte(objet.get("cwd")),
            branche=agregat.branche or _texte(objet.get("gitBranch")),
        )

    message = objet.get("message")
    if not isinstance(message, dict):
        return agregat

    if (
        message.get("isCompactSummary") is True
        or objet.get("isCompactSummary") is True
    ):
        agregat = replace(agregat, compactions=agregat.compactions + 1)

    usage = message.get("usage")
    if not isinstance(usage, dict):
        return agregat

    champs = {
        nom: getattr(agregat, nom) + _entier(usage.get(cle))
        for cle, nom in USAGE
    }
    details = usage.get("output_tokens_details")
    reflexion = 0
    if isinstance(details, dict):
        reflexion = _entier(details.get("thinking_tokens"))
    taille = sum(
        _entier(usage.get(cle)) for cle, nom in USAGE if nom in TAILLE
    )
    serie = (agregat.serie + (taille,))[-SERIE_MAX:]
    return replace(
        agregat,
        tours=agregat.tours + 1,
        reflexion=agregat.reflexion + reflexion,
        serie=serie,
        **champs,
    )


def replier_texte(agregat: Agregat, texte: str) -> Agregat:
    """Replier plusieurs lignes JSON. Une ligne illisible est SAUTÉE.

    Une transcription en cours d'écriture finit sur une ligne tronquée, et un
    agrégat qui lèverait là rendrait l'écran noir sur la session la plus
    intéressante — celle qui travaille.
    """
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            objet = json.loads(ligne)
        except (ValueError, TypeError):
            continue
        agregat = replier(agregat, objet)
    return agregat


@dataclass(frozen=True)
class Lecture:
    """Un agrégat et l'endroit où la lecture s'est arrêtée.

    `offset` est en octets et non en lignes : c'est ce qui permet de reprendre
    sans relire, et une transcription ne fait que croître par la fin.
    """

    agregat: Agregat = Agregat()
    offset: int = 0


def lire(chemin, lecture=None, *, ouvrir=None, taille=None) -> Lecture:
    """Replier ce qui a été AJOUTÉ depuis la lecture précédente.

    Rend une nouvelle `Lecture`. Sans lecture précédente, tout le fichier est
    lu ; avec, seuls les octets neufs le sont — une TUI qui se rafraîchit
    toutes les deux secondes ne peut pas relire dix mégaoctets à chaque fois.

    Un fichier qui a RÉTRÉCI est relu en entier : ce n'est plus la même
    transcription, ou elle a été réécrite, et reprendre à l'ancien offset
    plierait le milieu d'une ligne.

    La dernière ligne peut être incomplète — une session écrit pendant qu'on
    lit. L'offset s'arrête donc au dernier saut de ligne VU, et l'octet
    suivant sera replié au prochain passage.
    """
    if ouvrir is None:

        def ouvrir(nom):
            return open(nom, "rb")

    if taille is None:
        taille = os.path.getsize

    lecture = lecture or Lecture()
    try:
        fin = taille(chemin)
    except OSError:
        return lecture
    if fin < lecture.offset:
        lecture = Lecture()
    if fin == lecture.offset:
        return lecture

    try:
        with ouvrir(chemin) as fh:
            if lecture.offset:
                fh.seek(lecture.offset)
            brut = fh.read()
    except OSError:
        return lecture

    coupe = brut.rfind(b"\n")
    if coupe < 0:
        # Pas une seule ligne complète : rien à replier, on attend la suite.
        return lecture
    texte = brut[: coupe + 1].decode("utf-8", "replace")
    return Lecture(
        agregat=replier_texte(lecture.agregat, texte),
        offset=lecture.offset + coupe + 1,
    )


def somme(agregats) -> Agregat:
    """Les jetons de plusieurs sessions, additionnés ; le reste, non.

    Les jetons s'additionnent exactement — chaque message rapporte les siens.
    Le coût et les durées viennent d'un `cost-state` PAR session, et les
    ajouter donnerait un total dont rien ne garantit le sens ; ils sont donc
    additionnés pour ce qu'ils valent — un ordre de grandeur — et l'écran dit
    d'où ils viennent. Ce qui n'a aucun sens agrégé ne sort pas : ni série de
    contexte, ni compte de segments.
    """
    total = Agregat()
    for a in agregats:
        total = replace(
            total,
            tours=total.tours + a.tours,
            entree=total.entree + a.entree,
            sortie=total.sortie + a.sortie,
            cache_lu=total.cache_lu + a.cache_lu,
            cache_cree=total.cache_cree + a.cache_cree,
            reflexion=total.reflexion + a.reflexion,
            compactions=total.compactions + a.compactions,
            cout=total.cout + a.cout,
            duree_horloge=total.duree_horloge + a.duree_horloge,
            duree_api=total.duree_api + a.duree_api,
            duree_outils=total.duree_outils + a.duree_outils,
            lignes_ajoutees=total.lignes_ajoutees + a.lignes_ajoutees,
            lignes_retirees=total.lignes_retirees + a.lignes_retirees,
        )
    return total
