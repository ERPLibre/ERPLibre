#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'un tour de conversation a coûté, et ce qui en descend sur le disque.

Le module ne parle pas et ne dessine rien : il fabrique une mesure, la met en
ligne de journal, et l'écrit. Ce qui s'affiche appartient au menu et à
l'écran, qui portent les traductions ; ici tout est en nombres, donc une
mesure se vérifie sans terminal.

**Chaque chiffre dit sa source.** La durée et le délai du premier jeton se
mesurent D'ICI, à l'horloge de l'appelant, et existent toujours. Les comptes
de jetons viennent du SERVEUR, qui ne les rend pas tous ni toujours : un flux
n'en porte que si on a demandé l'option, et certains logiciels n'en portent
pas du tout. Un compte absent vaut `None` et se lit « inconnu », jamais zéro —
un débit calculé sur un zéro supposé annoncerait un serveur à l'arrêt.

**Le débit porte sur ce que le modèle PRODUIT, pas sur ce qui s'affiche.** Un
modèle qui raisonne rend ses jetons de réflexion dans un champ séparé du
texte : la réponse visible est plus courte que ce que le serveur compte, et
les deux nombres sont justes pour deux questions différentes.

**Le journal ne porte aucun texte d'échange.** Ni la question, ni la réponse.
Il vit sous `private/`, qui est le seul endroit du dépôt autorisé à porter une
donnée de machine — et qui devient public avec un fork public. Une empreinte
courte de la question y remplace la question : elle regroupe les répétitions,
et ne se remonte pas.

Le fichier est mensuel et s'écrit en AJOUT, une ligne par tour. L'ajout est ce
qui rend deux écritures simultanées inoffensives tant que la ligne tient dans
un bloc, là où une relecture-réécriture perdrait l'une des deux.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

# Le dossier du journal, sous la racine du dépôt. `private/` est le seul
# endroit qui a le droit de porter un nom d'hôte ou un nom de modèle.
JOURNAL_DIR = ("private", "assistant")

# Le radical d'un fichier mensuel. Un fichier unique grossit sans fin et se
# relit mal ; un fichier par jour en ferait des centaines. Le mois est la
# granularité qui laisse un `grep` utilisable et un dossier lisible.
JOURNAL_STEM = "mesures"

# La longueur d'une empreinte de question. Douze caractères hexadécimaux
# séparent des milliards de questions, ce qui suffit à reconnaître une
# répétition ; ils ne se remontent pas vers le texte.
EMPREINTE_LEN = 12

# Les modes de fin qu'on nomme quand le serveur n'en donne aucun. Distinguer
# les deux compte : une réponse coupée par la limite de jetons se lit comme
# une réponse complète si rien ne le dit.
FIN_INCONNUE = ""


@dataclass(frozen=True)
class Mesure:
    """Un tour, tel qu'on peut le compter.

    `duree` et `premier` sont en SECONDES et viennent de l'horloge de
    l'appelant ; `premier` vaut `None` quand rien n'est arrivé au fil, ce qui
    est le cas d'un envoi d'un seul bloc comme d'une panne avant le premier
    jeton.

    `invite`, `reponse` et `debit` valent `None` quand le serveur n'a rendu
    aucun compte. C'est « inconnu » et non zéro : l'écran affiche alors un
    tiret, et aucune moyenne ne les compte.

    `erreur` porte la CLASSE d'une panne — jamais son message, qui recopie
    volontiers ce que le serveur a dit, et que le serveur remplit de ce qu'on
    lui a demandé.
    """

    seance: str
    rang: int
    horodatage: str
    hote: str
    port: int
    logiciel: str
    modele: str
    outil: str
    duree: float
    premier: float | None
    invite: int | None
    reponse: int | None
    debit: float | None
    fin: str
    interrompu: bool
    erreur: str
    empreinte: str


def empreinte(texte: str) -> str:
    """L'empreinte courte d'une question. Fonction PURE.

    Elle regroupe les répétitions d'une même question sans la garder : deux
    tours qui portent la même empreinte ont posé la même question, et rien
    dans le journal ne dit laquelle.
    """
    brut = (texte or "").strip().encode("utf-8", "replace")
    return hashlib.sha256(brut).hexdigest()[:EMPREINTE_LEN]


def debit(reponse, duree) -> float | None:
    """Les jetons par seconde, ou `None` si le calcul n'a pas de sens.

    Fonction PURE. Rend `None` sur un compte inconnu et sur une durée nulle
    ou négative : une division par une durée que l'horloge n'a pas su séparer
    rendrait un débit infini, qui se lit comme une mesure.
    """
    if not reponse or not isinstance(reponse, int):
        return None
    if not duree or duree <= 0:
        return None
    return reponse / duree


def _compte(usage, cle) -> int | None:
    """Un compte de jetons d'un `usage` de serveur, ou `None`.

    Le corps vient d'un tiers : la clé peut manquer, valoir `null`, ou porter
    autre chose qu'un entier. Aucun de ces cas n'est un zéro.
    """
    if not isinstance(usage, dict):
        return None
    valeur = usage.get(cle)
    return (
        valeur
        if isinstance(valeur, int) and not isinstance(valeur, bool)
        else None
    )


def mesurer(
    *,
    seance: str,
    rang: int,
    serveur,
    outil: str = "",
    question: str = "",
    duree: float,
    premier: float | None = None,
    faits: dict | None = None,
    interrompu: bool = False,
    erreur: str = "",
    maintenant=None,
) -> Mesure:
    """La mesure d'un tour. Fonction PURE une fois l'horloge injectée.

    `serveur` porte l'hôte, le port, le logiciel et le modèle ; `faits` est ce
    que le backend rapporte — modèle réellement servi, `usage`, raison de fin.
    Le modèle du rapport PRIME sur celui de la demande : un serveur qui sert
    autre chose que ce qu'on nomme est précisément ce que le journal doit
    montrer.

    `maintenant` rend l'horodatage ; son injection est ce qui rend une ligne
    de journal vérifiable sans attendre que le temps passe.
    """
    faits = faits or {}
    usage = faits.get("usage")
    reponse = _compte(usage, "completion_tokens")
    if maintenant is None:
        maintenant = _maintenant
    return Mesure(
        seance=seance,
        rang=rang,
        horodatage=maintenant(),
        hote=getattr(serveur, "host", ""),
        port=getattr(serveur, "port", 0),
        logiciel=getattr(serveur, "software", ""),
        modele=faits.get("model") or getattr(serveur, "model", ""),
        outil=outil,
        duree=round(float(duree), 3),
        premier=None if premier is None else round(float(premier), 3),
        invite=_compte(usage, "prompt_tokens"),
        reponse=reponse,
        debit=_arrondi(debit(reponse, duree)),
        fin=faits.get("finish_reason") or FIN_INCONNUE,
        interrompu=bool(interrompu),
        erreur=erreur,
        empreinte=empreinte(question),
    )


def _arrondi(valeur):
    """Un débit à une décimale, ou `None`. Un dixième de jeton par seconde
    est déjà sous le bruit d'une mesure d'un seul tour."""
    return None if valeur is None else round(valeur, 1)


def _maintenant() -> str:
    """L'instant, en ISO 8601 avec son décalage.

    Le décalage est gardé parce qu'un journal se relit ailleurs qu'où il
    s'écrit : une heure nue ne se compare pas d'un fuseau à l'autre.
    """
    return (
        datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    )


def ligne(mesure: Mesure) -> str:
    """La ligne JSON d'une mesure, sans saut de ligne. Fonction PURE.

    Les clés sont écrites dans l'ordre du dataclass et les non-ASCII sortent
    tels quels : un journal se lit à l'œil autant qu'au programme.
    """
    return json.dumps(asdict(mesure), ensure_ascii=False, sort_keys=False)


def chemin(horodatage: str, *, racine=None) -> Path:
    """Le fichier mensuel où cette mesure s'écrit.

    Le mois se lit dans l'horodatage plutôt qu'à l'horloge : une mesure
    réécrite plus tard retombe dans le fichier de son mois, et non dans celui
    du jour où on la rejoue.
    """
    if racine is None:
        from script.todo.assistant.context import repo_root

        racine = repo_root()
    mois = (horodatage or "")[:7] or "0000-00"
    return Path(racine, *JOURNAL_DIR, f"{JOURNAL_STEM}-{mois}.jsonl")


def ecrire(mesure: Mesure, *, racine=None) -> Path | None:
    """Ajoute la mesure à son fichier mensuel. Rend le chemin, ou `None`.

    Rend `None` sans lever quand l'écriture échoue — disque plein, dossier en
    lecture seule, chemin pris par autre chose. Un journal est une commodité
    d'analyse : perdre une ligne est un moindre mal, et une conversation ne
    doit pas s'arrêter parce qu'on n'a pas pu compter.

    L'ouverture en AJOUT est ce qui rend deux écrivains inoffensifs l'un pour
    l'autre : chacun écrit sa ligne entière à la fin, là où une
    relecture-réécriture perdrait celle de l'autre.
    """
    cible = chemin(mesure.horodatage, racine=racine)
    try:
        os.makedirs(cible.parent, exist_ok=True)
        with open(cible, "a", encoding="utf-8") as fichier:
            fichier.write(ligne(mesure) + "\n")
    except OSError:
        return None
    return cible


def lire(chemin_fichier) -> list[dict]:
    """Les mesures d'un fichier de journal, les lignes abîmées écartées.

    Une ligne coupée par un disque plein ne fait pas perdre les voisines : le
    journal est une suite de lignes indépendantes, et c'est ce qui le rend
    réparable en le tronquant.
    """
    trouves: list[dict] = []
    try:
        with open(chemin_fichier, encoding="utf-8") as fichier:
            for brut in fichier:
                brut = brut.strip()
                if not brut:
                    continue
                try:
                    entree = json.loads(brut)
                except ValueError:
                    continue
                if isinstance(entree, dict):
                    trouves.append(entree)
    except OSError:
        return []
    return trouves
