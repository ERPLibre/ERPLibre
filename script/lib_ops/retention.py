# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le nom des sauvegardes d'une base, et lesquelles garder.

Une sauvegarde s'appelle `<base>_<AAAA-MM-JJ>_<HH>h<MM>m<SS>s.zip`. Seul ce
nom exact, pour CETTE base, est une sauvegarde de l'outil : dans le
dossier de `demo`, `demo_bar_<horodatage>.zip` appartient à une autre base
(ou à personne) et n'est jamais candidat. La date se lit dans le nom et
non dans la date de modification du fichier, qu'une copie ou une
restauration de fichiers change.

`a_supprimer` est une fonction pure : elle reçoit des noms et rend ceux
à supprimer, sans toucher au disque. Trois règles indépendantes gardent
chacune la sauvegarde la plus RÉCENTE de chaque période, en partant de la
plus récente :

- `quotidien` : les N jours les plus récents qui ONT une sauvegarde ;
- `hebdo` : les N semaines ISO (`isocalendar`), même définition ;
- `mensuel` : les N mois, même définition.

Compter les périodes qui ont une sauvegarde, et non des jours de
calendrier, fait qu'une interruption des sauvegardes n'efface jamais tout :
après un mois sans sauvegarde, les N dernières restent. `recents_jours`
garde en plus TOUT ce qui date des N derniers jours, aujourd'hui compris —
une sauvegarde prise avant une mise à jour survit ainsi à la sauvegarde
planifiée du même jour. La plus récente n'est jamais supprimée, quelles
que soient les valeurs.

Bibliothèque standard seulement.
"""

from __future__ import annotations

import datetime
import re

# Le format d'horodatage du nom, pour strftime et strptime.
FORMAT = "%Y-%m-%d_%Hh%Mm%Ss"
RE_HORODATAGE = r"\d{4}-\d{2}-\d{2}_\d{2}h\d{2}m\d{2}s"
# Le même horodatage en motif de filtre rsync (`[0-9]` par chiffre).
GLOB_HORODATAGE = (
    "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"
    "_[0-9][0-9]h[0-9][0-9]m[0-9][0-9]s"
)
EXTENSION = ".zip"
SUFFIXE_SHA = ".sha256"
SUFFIXE_PARTIEL = ".partial"


def nom_sauvegarde(base, moment):
    """Le nom de la sauvegarde de `base` prise à `moment` (datetime)."""
    return f"{base}_{moment.strftime(FORMAT)}{EXTENSION}"


def _motif(base, suffixe=""):
    return re.compile(
        "^"
        + re.escape(base)
        + "_("
        + RE_HORODATAGE
        + ")"
        + re.escape(EXTENSION + suffixe)
        + "$"
    )


def motifs_rsync(base):
    """Les motifs de filtre rsync, ancrés au dossier transféré, des
    sauvegardes de `base` et de leurs empreintes : rien d'autre, ni
    fichier provisoire ni archive d'une autre base. Les noms de base admis
    (`postgres.RE_BASE`) ne portent aucun caractère spécial de motif."""
    nom = f"/{base}_{GLOB_HORODATAGE}{EXTENSION}"
    return [nom, nom + SUFFIXE_SHA]


def date_de(nom, base):
    """Le datetime d'une sauvegarde de `base`, ou None si `nom` n'en est pas
    une — autre base, autre forme, date impossible."""
    trouve = _motif(base).match(nom)
    if trouve is None:
        return None
    try:
        return datetime.datetime.strptime(trouve.group(1), FORMAT)
    except ValueError:
        return None


def est_partiel(nom, base):
    """True si `nom` est le fichier provisoire d'une sauvegarde de `base`."""
    return _motif(base, SUFFIXE_PARTIEL).match(nom) is not None


def sauvegardes(noms, base):
    """[(datetime, nom)] des sauvegardes de `base` parmi `noms`, la plus
    récente d'abord."""
    trouves = []
    for nom in noms:
        moment = date_de(nom, base)
        if moment is not None:
            trouves.append((moment, nom))
    trouves.sort(reverse=True)
    return trouves


def plus_recente(noms, base):
    """Le nom de la sauvegarde la plus récente de `base`, ou None."""
    liste = sauvegardes(noms, base)
    return liste[0][1] if liste else None


def _semaine(moment):
    # isocalendar() rend un tuple sous Python 3.7, un objet nommé ensuite :
    # l'indexer marche dans les deux cas.
    iso = moment.isocalendar()
    return (iso[0], iso[1])


def _garder_par_periode(liste, nombre, periode):
    """Les noms gardés par une règle : la plus récente de chacune des
    `nombre` premières périodes distinctes."""
    gardes = set()
    vues = []
    for moment, nom in liste:
        if len(vues) >= nombre:
            break
        cle = periode(moment)
        if cle in vues:
            continue
        vues.append(cle)
        gardes.add(nom)
    return gardes


def a_supprimer(
    noms,
    base,
    quotidien,
    hebdo,
    mensuel,
    recents_jours=0,
    aujourd_hui=None,
):
    """L'ensemble des sauvegardes de `base` à supprimer parmi `noms`.

    Les noms qui ne sont pas des sauvegardes de `base` n'y figurent jamais.
    Les sidecars `.sha256` ne sont pas rendus : l'appelant supprime celui
    de chaque zip qu'il supprime. ValueError sur un nombre négatif.
    """
    for valeur in (quotidien, hebdo, mensuel, recents_jours):
        if valeur < 0:
            raise ValueError(valeur)
    liste = sauvegardes(noms, base)
    if not liste:
        return set()
    gardes = {liste[0][1]}
    gardes |= _garder_par_periode(liste, quotidien, lambda m: m.date())
    gardes |= _garder_par_periode(liste, hebdo, _semaine)
    gardes |= _garder_par_periode(liste, mensuel, lambda m: (m.year, m.month))
    if recents_jours:
        jour = aujourd_hui or datetime.date.today()
        limite = jour - datetime.timedelta(days=recents_jours - 1)
        gardes |= {nom for moment, nom in liste if moment.date() >= limite}
    return {nom for _moment, nom in liste if nom not in gardes}


# Marge ajoutée au plus grand écart entre deux sauvegardes planifiées : la
# durée d'une sauvegarde et le démarrage différé d'une minuterie
# `Persistent=true` y tiennent.
MARGE_SEUIL_HEURES = 2


def seuil_age_heures(instants, delai_aleatoire_s=0, marge=MARGE_SEUIL_HEURES):
    """Le seuil d'âge, en heures entières, au-delà duquel la dernière
    sauvegarde réussie est en retard sur le calendrier : le plus grand
    écart entre deux `instants` consécutifs (datetime, triés ici), plus le
    délai aléatoire de la minuterie, plus `marge`, arrondi à l'heure
    supérieure. None quand moins de deux instants sont donnés : un écart
    ne se mesure pas."""
    tries = sorted(instants)
    if len(tries) < 2:
        return None
    ecart = max(
        (suivant - courant).total_seconds()
        for courant, suivant in zip(tries, tries[1:])
    )
    secondes = ecart + max(0, delai_aleatoire_s or 0) + marge * 3600
    return int(-(-secondes // 3600))
