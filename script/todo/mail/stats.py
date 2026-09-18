#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Statistiques du courriel : la composition, sans aucune interface.

Le cache fait les agrégats — il détient le SQL, le verrou et les clés. Ce
module n'en fait aucun : il compose ce que `Store` rend en un rapport
affichable, et rien ici n'a besoin d'un terminal pour être testé.

La séparation n'est pas décorative : un histogramme calculé dans un widget
Textual ne se vérifie qu'en montant une application, ce qui coûte des
minutes de suite et masque les erreurs de calcul derrière des erreurs
d'affichage.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BARRE = "█"


def median(valeurs) -> float:
    """La médiane, ou 0.0 sans valeur.

    Médiane et non moyenne : un seul message répondu six mois plus tard
    déplace une moyenne bien plus que la réalité qu'on veut décrire.
    """
    ordonnees = sorted(valeurs)
    if not ordonnees:
        return 0.0
    milieu = len(ordonnees) // 2
    if len(ordonnees) % 2:
        return float(ordonnees[milieu])
    return (ordonnees[milieu - 1] + ordonnees[milieu]) / 2


def top(comptes: dict, limite: int = 10) -> list[tuple]:
    """Les correspondants les plus fréquents, du plus grand au plus petit.

    À nombre égal on trie par adresse : sans ce second critère, deux
    exécutions sur les mêmes données pourraient rendre un ordre différent,
    et un écran qui bouge sans raison passe pour un bogue.
    """
    return sorted(comptes.items(), key=lambda kv: (-kv[1], kv[0]))[:limite]


def bars(lignes, largeur: int = 24) -> list[tuple]:
    """(étiquette, nombre, barre) — la barre est proportionnelle au maximum.

    Normalisé sur le maximum de la série, jamais sur un plafond fixe : un
    mois à 12 messages et un mois à 12 000 doivent tous deux remplir
    l'écran, sinon la forme de la distribution disparaît.
    """
    if not lignes:
        return []
    maximum = max(nombre for _, nombre, *_ in lignes) or 1
    sorties = []
    for etiquette, nombre, *reste in lignes:
        pleine = round(nombre * largeur / maximum)
        # Un nombre non nul garde AU MOINS un bloc : une barre vide se lit
        # « aucun message », ce qui serait faux.
        sorties.append(
            (etiquette, nombre, BARRE * max(1, pleine) if nombre else "")
        )
    return sorties


def humain(secondes: float) -> str:
    """Une durée en secondes, dite comme on la dit."""
    secondes = int(secondes)
    if secondes <= 0:
        return "—"
    if secondes < 3600:
        return f"{secondes // 60} min"
    if secondes < 86400:
        return f"{secondes // 3600} h"
    return f"{secondes // 86400} j"


@dataclass
class Report:
    """Ce qu'un écran a besoin d'afficher, et rien de plus."""

    volume: list = field(default_factory=list)
    folders: list = field(default_factory=list)
    senders: list = field(default_factory=list)
    recipients: list = field(default_factory=list)
    reply_median: float = 0.0
    reply_count: int = 0
    undated: int = 0
    total: int = 0
    total_size: int = 0
    unseen: int = 0

    @property
    def unseen_share(self) -> float:
        return (self.unseen / self.total) if self.total else 0.0


def build_report(
    store,
    bucket: str = "day",
    folder_id=None,
    since=None,
    until=None,
    limite: int = 10,
) -> Report:
    """Assemble le rapport d'UN compte à partir de son cache."""
    volume = store.stats_volume(bucket, folder_id, since, until)
    # La même borne que le volume : le total et les non-lus s'impriment sur
    # une seule ligne, et deux bornes différentes y mettraient une part de
    # non-lus qui ne se rapporte à rien.
    dossiers = store.stats_folders(since)
    delais = store.stats_reply_delays(folder_id, since, until)
    if folder_id is not None:
        # `stats_folders` couvre TOUS les dossiers : filtrer ici évite une
        # requête de plus, mais il faut que la clé existe — sinon le filtre
        # ne matche jamais et retombe en silence sur l'ensemble.
        dossiers = [d for d in dossiers if d["id"] == folder_id]
    return Report(
        volume=bars(volume),
        folders=dossiers,
        senders=top(
            store.stats_correspondents("from", folder_id, since, until), limite
        ),
        recipients=top(
            store.stats_correspondents("to", folder_id, since, until), limite
        ),
        reply_median=median(delais),
        reply_count=len(delais),
        undated=store.stats_undated(folder_id),
        total=sum(n for _, n, _ in volume),
        total_size=sum(o for _, _, o in volume),
        unseen=sum(d["unseen"] or 0 for d in dossiers),
    )


# Au-delà, l'histogramme cesse d'être lisible et Textual doit mesurer puis
# replier un bloc de plusieurs centaines de milliers de caractères. Une
# boîte tenue depuis vingt ans dépasse les 7000 barres quotidiennes.
MAX_BARRES = 180

# Seuils de bascule automatique, en secondes couvertes par la boîte.
_AN = 365 * 86400


def choisir_bucket(span_secondes: float) -> str:
    """Le pas qui garde l'histogramme sous `MAX_BARRES` sans le demander.

    Une boîte de deux semaines se lit par jour ; dix ans d'archives par
    mois, et au-delà par année — cent quatre-vingts barres est la limite
    qui fait passer d'un pas au suivant. Choisir d'après l'étendue réelle
    évite d'ouvrir sur un écran illisible qu'il faut ensuite corriger à la
    main.
    """
    if span_secondes <= 0:
        return "day"
    if span_secondes / 86400 <= MAX_BARRES:
        return "day"
    if span_secondes / (7 * 86400) <= MAX_BARRES:
        return "week"
    if span_secondes / (30 * 86400) <= MAX_BARRES:
        return "month"
    return "year"


def derniers(lignes, limite: int = MAX_BARRES) -> list:
    """Les `limite` dernières tranches — les plus récentes intéressent.

    Une coupe est préférable à un écran qu'on ne peut pas parcourir : le
    total, lui, reste calculé sur TOUT et s'affiche à part.
    """
    return lignes[-limite:] if len(lignes) > limite else lignes


@dataclass
class Overview:
    """Ce qui s'affiche DÈS la touche `i` : uniquement du SQL.

    Ni correspondants ni délais de réponse : les premiers déchiffrent
    chaque ligne, les seconds joignent la table avec elle-même. Sur une
    grande boîte ils coûtent des secondes, et les payer avant le premier
    affichage fige l'écran au moment où l'utilisateur attend une réponse.
    """

    volume: list = field(default_factory=list)
    folders: list = field(default_factory=list)
    bucket: str = "day"
    undated: int = 0
    total: int = 0
    total_size: int = 0
    unseen: int = 0
    tronque: int = 0

    @property
    def unseen_share(self) -> float:
        return (self.unseen / self.total) if self.total else 0.0


@dataclass
class Details:
    """Ce qui se calcule à la demande, et qui peut durer."""

    senders: list = field(default_factory=list)
    recipients: list = field(default_factory=list)
    reply_median: float = 0.0
    reply_count: int = 0


def build_overview(store, bucket=None, folder_id=None, since=None) -> Overview:
    """La vue d'ensemble. Aucune colonne scellée n'est ouverte ici."""
    nombre, plus_vieux, plus_recent = store.stats_span(folder_id, since)
    if bucket is None:
        bucket = choisir_bucket(plus_recent - plus_vieux)
    volume = store.stats_volume(bucket, folder_id, since)
    # La MÊME borne que l'histogramme : le total et les non-lus se lisent
    # sur une seule ligne, et une part de non-lus tirée de deux périodes
    # différentes peut dépasser cent pour cent.
    dossiers = store.stats_folders(since)
    if folder_id is not None:
        dossiers = [d for d in dossiers if d["id"] == folder_id]
    montre = derniers(volume)
    return Overview(
        volume=bars(montre),
        folders=dossiers,
        bucket=bucket,
        undated=store.stats_undated(folder_id),
        total=sum(n for _, n, _ in volume),
        total_size=sum(o for _, _, o in volume),
        unseen=sum(d["unseen"] or 0 for d in dossiers),
        tronque=len(volume) - len(montre),
    )


def build_details(
    store, folder_id=None, limite: int = 10, progress=None, since=None
) -> Details:
    """Les correspondants et les délais. Appelable depuis un fil de travail.

    `progress(faits, total)` est appelé pendant le balayage : sur une
    grande boîte cette fonction dure des secondes, et une barre qui avance
    dit que le programme travaille plutôt qu'il ne s'est figé.

    `since` est la même borne que la vue d'ensemble : les deux blocs
    s'affichent sous un seul en-tête de période, et un classement des
    correspondants qui couvrirait vingt ans sous un titre « trente
    derniers jours » ne dirait pas de quoi il parle.
    """
    total, _, _ = store.stats_span(folder_id, since)

    def relais(faits):
        if progress is not None:
            progress(faits, total)

    expediteurs = store.stats_correspondents(
        "from", folder_id, since, progress=relais
    )
    destinataires = store.stats_correspondents(
        "to", folder_id, since, progress=relais
    )
    delais = store.stats_reply_delays(folder_id, since)
    return Details(
        senders=top(expediteurs, limite),
        recipients=top(destinataires, limite),
        reply_median=median(delais),
        reply_count=len(delais),
    )
