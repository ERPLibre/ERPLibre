#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Appliquer une mise à niveau : une branche datée, un rebase, une file.

Ce module ÉCRIT. Il crée une branche, rejoue des commits, et laisse
délibérément un rebase en cours lorsqu'il bute. Tout ce qu'il fait est
inscrit dans un enregistrement de passe, sans quoi un arbre à demi rebasé
sur une quinzaine de dépôts ne se démêlerait plus.

La branche datée
----------------
Le rebase ne se fait PAS sur la branche du fork mais sur une copie datée.
La branche d'origine reste donc intacte, ce qui rend la comparaison
avant/après possible et le retour en arrière gratuit. Sur une quinzaine de
dépôts, une passe ratée se rattrape mal quand l'état d'avant n'existe plus
que dans le reflog.

Un dépôt géré par git-repo est en HEAD détachée. Créer une branche l'en
sort, donc l'enregistrement retient laquelle a été créée et où elle part :
c'est ce qui permet de revenir à l'état que git-repo attend.

Un conflit n'arrête pas la passe
--------------------------------
Chaque dépôt est un répertoire git indépendant. Un rebase en pause dans
l'un n'empêche rien dans les autres, donc la passe continue et le dépôt
qui bute rejoint une file. Interrompre les quinze autres pour attendre une
décision humaine sur le douzième ne ferait gagner de temps à personne.

L'inversion d'« ours » et de « theirs » pendant un rebase
---------------------------------------------------------
Git rejoue NOS commits par-dessus l'amont, donc pendant l'opération c'est
l'AMONT qui occupe la place de « ours » et notre commit celle de
« theirs ». Le piège est constant et coûte le contraire de ce qu'on
voulait garder. Les fonctions ci-dessous sont donc nommées par INTENTION,
et la traduction vers le drapeau git se fait ici, une fois pour toutes.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.git.repo_upgrade import (  # noqa: E402
    DELAI_GIT,
    REPO_ROOT,
    git,
)

# L'enregistrement des passes. Sous « tasks/ », qui n'est pas versionné :
# une trace d'exécution n'a rien à faire dans l'historique du dépôt, et le
# rapport durable est l'instantané de manifeste, pas ce journal.
DOSSIER_PASSES = os.path.join("tasks", "git_repo_upgrade")

VERDICTS_A_APPLIQUER = ("a_rebaser", "en_conflit", "absorbe")


def nom_branche(revision, horodatage):
    """« <branche>_maj_<AAAAMMJJ> », le nom de la copie datée.

    Le jour suffit : deux passes le même jour visent le même nom, et la
    seconde se voit refuser la création plutôt que d'écraser la première.
    """
    return f"{revision}_maj_{horodatage[:8]}"


def branche_existe(chemin, nom):
    _out, _err, code = git(
        ["rev-parse", "--verify", "--quiet", f"refs/heads/{nom}"], chemin
    )
    return code == 0


def rebase_en_cours(chemin):
    """Un rebase interrompu attend-il dans ce dépôt ?

    Les deux répertoires que git pose selon la forme du rebase. Leur
    présence est le seul signal fiable : « git status » change de mots
    d'une version à l'autre.
    """
    out, _err, code = git(["rev-parse", "--git-path", "rebase-merge"], chemin)
    if code == 0 and os.path.isdir(os.path.join(chemin, out.strip())):
        return True
    out, _err, code = git(["rev-parse", "--git-path", "rebase-apply"], chemin)
    return code == 0 and os.path.isdir(os.path.join(chemin, out.strip()))


def fichiers_en_conflit(chemin):
    """Les fichiers que git laisse non résolus, ou une liste vide."""
    out, _err, code = git(["diff", "--name-only", "--diff-filter=U"], chemin)
    return (
        [x.strip() for x in out.splitlines() if x.strip()] if not code else []
    )


def appliquer(constat, horodatage, racine=REPO_ROOT, delai=DELAI_GIT):
    """Rebase un dépôt sur son amont dans une branche datée.

    Rend l'enregistrement de CE dépôt. Ne lève jamais : un dépôt qui bute
    est un résultat que la passe doit rapporter, pas une exception qui
    emporterait les quatorze autres.
    """
    chemin = os.path.join(racine, constat["chemin"] or "")
    depart, _err, _code = git(["rev-parse", "HEAD"], chemin)
    resultat = {
        "chemin": constat["chemin"],
        "verdict_avant": constat.get("verdict"),
        "branche": None,
        "depart": depart.strip(),
        "arrivee": None,
        "etat": "ignore",
        "conflits": [],
        "sortie": "",
    }

    if constat.get("verdict") not in VERDICTS_A_APPLIQUER:
        return resultat
    if rebase_en_cours(chemin):
        resultat["etat"] = "rebase_deja_en_cours"
        resultat["conflits"] = fichiers_en_conflit(chemin)
        return resultat

    branche = nom_branche(constat.get("revision") or "HEAD", horodatage)
    resultat["branche"] = branche
    if branche_existe(chemin, branche):
        # Écraser une branche datée effacerait le travail d'une passe
        # précédente du même jour, y compris des conflits résolus à la main.
        resultat["etat"] = "branche_existante"
        return resultat

    out, err, code = git(["checkout", "-b", branche], chemin, delai)
    if code:
        resultat["etat"] = "branche_refusee"
        resultat["sortie"] = (out + err).strip()
        return resultat

    out, err, code = git(["rebase", "FETCH_HEAD"], chemin, delai)
    resultat["sortie"] = (out + err).strip()
    if code == 0:
        arrivee, _err, _c = git(["rev-parse", "HEAD"], chemin)
        resultat["arrivee"] = arrivee.strip()
        resultat["etat"] = "rebase"
        return resultat

    # Le rebase est LAISSÉ EN L'ÉTAT : c'est là que la résolution se fera.
    # L'abandonner ici obligerait à tout refaire pour reprendre la main.
    resultat["etat"] = "conflit"
    resultat["conflits"] = fichiers_en_conflit(chemin)
    return resultat


def passe_appliquer(
    lst, horodatage, racine=REPO_ROOT, parallele=4, delai=DELAI_GIT
):
    """Applique la mise à niveau à tous les dépôts qui la demandent.

    Le parallélisme est plus bas que celui de la lecture : un rebase écrit
    dans le magasin d'objets partagé par tous les dépôts, et en lancer
    huit ne va pas deux fois plus vite qu'en lancer quatre.
    """
    from concurrent.futures import ThreadPoolExecutor

    a_faire = [c for c in lst if c.get("verdict") in VERDICTS_A_APPLIQUER]
    if not a_faire:
        return []
    with ThreadPoolExecutor(max_workers=parallele) as pool:
        return list(
            pool.map(
                lambda c: appliquer(c, horodatage, racine, delai), a_faire
            )
        )


def dossier_passe(horodatage, racine=REPO_ROOT):
    return os.path.join(racine, DOSSIER_PASSES, horodatage)


def ecrire_passe(horodatage, version, diagnostic, resultats, racine=REPO_ROOT):
    """Inscrit la passe sur le disque et rend le chemin du dossier.

    Le diagnostic est gardé avec les résultats : sans lui, un conflit à
    reprendre trois jours plus tard ne dit plus de quel amont il vient.
    """
    dossier = dossier_passe(horodatage, racine)
    os.makedirs(dossier, exist_ok=True)
    charge = {
        "horodatage": horodatage,
        "version": version,
        "diagnostic": diagnostic,
        "resultats": resultats,
    }
    with open(os.path.join(dossier, "passe.json"), "w") as fh:
        json.dump(charge, fh, indent=2, ensure_ascii=False, default=sorted)
    for res in resultats:
        if not res.get("sortie"):
            continue
        nom = (res["chemin"] or "inconnu").replace("/", "_") + ".log"
        with open(os.path.join(dossier, nom), "w") as fh:
            fh.write(res["sortie"] + "\n")
    return dossier


def passes(racine=REPO_ROOT):
    """Les horodatages des passes enregistrées, de la plus récente d'abord."""
    dossier = os.path.join(racine, DOSSIER_PASSES)
    if not os.path.isdir(dossier):
        return []
    return sorted(
        (
            x
            for x in os.listdir(dossier)
            if os.path.isfile(os.path.join(dossier, x, "passe.json"))
        ),
        reverse=True,
    )


def lire_passe(horodatage=None, racine=REPO_ROOT):
    """La passe demandée, ou la dernière. None s'il n'y en a aucune."""
    if horodatage is None:
        lst = passes(racine)
        if not lst:
            return None
        horodatage = lst[0]
    chemin = os.path.join(dossier_passe(horodatage, racine), "passe.json")
    try:
        with open(chemin) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ── Résoudre un conflit ────────────────────────────────────────────────
#
# Les deux fonctions ci-dessous portent l'inversion expliquée en tête de
# fichier. Pendant un rebase, git appelle « ours » la base sur laquelle il
# rejoue — donc l'AMONT — et « theirs » le commit rejoué — donc le NÔTRE.


def garder_le_notre(chemin, fichiers):
    """Garde la version du fork pour ces fichiers.

    « --theirs » et non « --ours » : pendant un rebase, le commit rejoué
    est celui que git nomme « theirs ».
    """
    return git(["checkout", "--theirs", "--"] + list(fichiers), chemin)


def prendre_l_amont(chemin, fichiers):
    """Prend la version de l'amont pour ces fichiers.

    « --ours » désigne ici la base du rebase, c'est-à-dire l'amont.
    """
    return git(["checkout", "--ours", "--"] + list(fichiers), chemin)


def marquer_resolus(chemin, fichiers):
    return git(["add", "--"] + list(fichiers), chemin)


def continuer_rebase(chemin, delai=DELAI_GIT):
    """Reprend le rebase là où il s'est arrêté.

    « GIT_EDITOR=true » : git ouvrirait un éditeur pour le message du
    commit rejoué, et un menu n'a pas de terminal à lui prêter.
    """
    return git(
        ["-c", "core.editor=true", "rebase", "--continue"], chemin, delai
    )


def abandonner_rebase(chemin, delai=DELAI_GIT):
    """Annule le rebase en cours et rend la branche à son état d'avant."""
    return git(["rebase", "--abort"], chemin, delai)


def sauter_le_commit(chemin, delai=DELAI_GIT):
    """Abandonne le commit en cours de rejeu et passe au suivant.

    C'est le geste qui répond à un module repris en amont : notre commit
    n'a plus d'objet, et le sauter laisse la branche sur la version de
    l'amont.
    """
    return git(["rebase", "--skip"], chemin, delai)


def revenir_a_repo(chemin, depart, delai=DELAI_GIT):
    """Ramène le dépôt à la HEAD détachée d'où la passe est partie.

    « depart » est le commit relevé AVANT la création de la branche, et
    c'est le seul repère juste : détacher sur FETCH_HEAD poserait le dépôt
    sur l'amont, c'est-à-dire précisément là où la mise à niveau voulait
    l'emmener, et non là d'où elle venait.

    Un rebase en cours est d'abord abandonné : sans cela le détachement
    échoue et le dépôt reste à mi-chemin.
    """
    if not depart:
        return "", "aucun point de départ enregistré", 1
    if rebase_en_cours(chemin):
        abandonner_rebase(chemin, delai)
    return git(["checkout", "--detach", depart], chemin, delai)
