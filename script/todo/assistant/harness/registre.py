#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Quels harnais d'agent cette machine porte, et lesquels manquent.

La détection est PURE : `which` et `exists` sont INJECTÉS, donc l'ordre des
verdicts se vérifie sans toucher au PATH ni au système de fichiers. Ce qui
sort de la vraie machine se lit une seule fois, dans `etats()`.

Le verdict distingue trois états, et cette distinction est tout l'intérêt du
module : le binaire manque, ou il est là mais l'adaptateur n'a pas été mesuré,
ou tout est prêt. Un menu qui confond les deux premiers envoie chercher une
installation là où c'est du code qui manque, et inversement.

Le répertoire de configuration n'est déclaré que là où il est CONNU. Pour les
harnais dont ce dépôt n'a mesuré ni l'installation ni la configuration, il
reste vide, et la détection se repose sur le binaire seul — annoncer un
chemin non vérifié serait une devinette affichée comme un fait.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

# Les verdicts, dans l'ordre où le menu les traite. « ok » seul est utilisable.
OK = "ok"
ABSENT = "absent"
NON_VERIFIE = "non_verifie"

# Les raisons, en clés-texte-anglais comme le reste du paquet — la clé EST la
# chaîne anglaise, et `t()` rend une clé inconnue inchangée.
SANS_BINAIRE = "binary not found"
SANS_MAISON = "binary found, its configuration directory is not"
SANS_ADAPTATEUR = "no adapter measured against this software yet"

# Les actions qu'un harnais peut accepter. Un adaptateur les déclare ; le menu
# n'offre que ce qui est déclaré.
LISTER = "lister"
QUESTION = "question"
REPRENDRE = "reprendre"
ARRIERE_PLAN = "arriere_plan"


@dataclass(frozen=True)
class Harnais:
    """Un harnais déclaré : ce qu'on cherche, et ce qu'on sait de lui.

    `maison` est le répertoire de configuration attendu, ou la chaîne vide
    quand ce dépôt ne l'a pas vérifié. `verifie` dit qu'un adaptateur a été
    mesuré contre le vrai logiciel : c'est une donnée, jamais une déduction.

    `nom` et `icone` ne passent PAS par l'internationalisation : un nom de
    produit ne se traduit pas, donc l'icône ne peut pas vivre dans une valeur
    traduite comme le font les autres étiquettes du menu. Elle vit ici, à
    côté du nom qu'elle décore, et chaque harnais en porte une — une entrée
    nue au milieu d'entrées décorées se lit comme un défaut.
    """

    cle: str
    nom: str
    icone: str
    binaire: str
    maison: str = ""
    verifie: bool = False
    actions: tuple[str, ...] = ()


# Les harnais que ce dépôt connaît de nom. `claude` est le seul mesuré.
#
# Les répertoires : « ~/.claude » est lu par le paquet depuis la première
# phase. « ~/.hermes » est nommé par la documentation du harnais, qui y place
# son fichier d'instructions global. Les quatre autres n'ont pas de répertoire
# déclaré ici — ce dépôt ne les a jamais installés, et un chemin supposé
# afficherait une devinette comme un fait.
HARNAIS: tuple[Harnais, ...] = (
    Harnais(
        cle="claude",
        nom="Claude Code",
        icone="🤖",
        binaire="claude",
        maison="~/.claude",
        verifie=True,
        actions=(LISTER, QUESTION, REPRENDRE, ARRIERE_PLAN),
    ),
    # Open Code ne déclare que la LECTURE. Son `run` écrit dans l'arbre de
    # travail sans demander — une consigne de trois mots suffit à faire créer
    # un fichier — donc une entrée « question libre » y serait un piège.
    Harnais(
        cle="opencode",
        nom="Open Code",
        icone="🧊",
        binaire="opencode",
        maison="~/.local/share/opencode",
        verifie=True,
        actions=(LISTER,),
    ),
    Harnais(
        cle="hermes",
        nom="Hermes",
        icone="🪯",
        binaire="hermes",
        maison="~/.hermes",
    ),
    Harnais(cle="codex", nom="Codex", icone="📐", binaire="codex"),
    Harnais(cle="gemini", nom="Gemini CLI", icone="💎", binaire="gemini"),
    Harnais(cle="aider", nom="Aider", icone="🔩", binaire="aider"),
    Harnais(cle="goose", nom="Goose", icone="🦆", binaire="goose"),
)


@dataclass(frozen=True)
class Etat:
    """Ce qu'on a LU d'un harnais, et le verdict qui en sort.

    `chemin` est le binaire trouvé ou la chaîne vide ; `maison_presente` vaut
    None quand aucun répertoire n'est déclaré — l'inconnu, qui ne doit pas se
    lire comme une absence.
    """

    harnais: Harnais
    chemin: str = ""
    maison_presente: bool | None = None

    @property
    def verdict(self) -> str:
        """Absent d'abord, non vérifié ensuite, prêt en dernier.

        L'ordre porte le raisonnement : sans binaire, la justesse de
        l'adaptateur ne se pose pas encore, et annoncer « adaptateur non
        mesuré » sur une machine où le logiciel n'est même pas installé
        enverrait écrire du code au lieu d'installer.
        """
        if not self.chemin:
            return ABSENT
        if not self.harnais.verifie:
            return NON_VERIFIE
        return OK

    @property
    def raison(self) -> str:
        """La clé i18n qui dit ce qui manque, ou la chaîne vide si rien.

        Une maison absente ne grise PAS : le binaire suffit à travailler, et
        un harnais lancé une première fois crée son répertoire lui-même. Elle
        se signale parce qu'elle explique une liste de sessions vide.
        """
        verdict = self.verdict
        if verdict == ABSENT:
            return SANS_BINAIRE
        if verdict == NON_VERIFIE:
            return SANS_ADAPTATEUR
        if self.maison_presente is False:
            return SANS_MAISON
        return ""

    def accepte(self, action: str) -> bool:
        """Vrai si ce harnais est prêt ET déclare cette action."""
        return self.verdict == OK and action in self.harnais.actions


def etat_de(harnais, *, which=None, exists=None) -> Etat:
    """L'état d'UN harnais. `which` et `exists` sont injectés."""
    if which is None:
        which = shutil.which
    if exists is None:
        exists = os.path.isdir

    chemin = which(harnais.binaire) or ""
    maison = None
    if harnais.maison:
        maison = bool(exists(os.path.expanduser(harnais.maison)))
    return Etat(harnais=harnais, chemin=chemin, maison_presente=maison)


def etats(*, which=None, exists=None, connus=None) -> list[Etat]:
    """L'état de tous les harnais, dans l'ordre de déclaration.

    L'ordre est celui de `HARNAIS` et non celui du verdict : un harnais garde
    sa place dans la liste quand il s'installe ou disparaît, sinon les numéros
    du menu changeraient sous les doigts d'une fois sur l'autre.
    """
    return [
        etat_de(h, which=which, exists=exists)
        for h in (connus if connus is not None else HARNAIS)
    ]


def prets(liste) -> list[Etat]:
    """Ceux qu'on peut utiliser. Le menu grise le reste plutôt que de le taire."""
    return [e for e in liste if e.verdict == OK]
