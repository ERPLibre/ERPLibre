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

La base gelée et le fast-forward
--------------------------------
L'amont est la « cible » du diagnostic : « <remote>/<branche> », la
branche de suivi du remote amont nommé, ou FETCH_HEAD pour un amont
récupéré par l'URL. Le rebase ordinaire, « rebase <cible> », est la
règle : git y écarte de lui-même, par leur patch-id, nos commits que
l'amont a déjà repris, et il ne rejoue que ce que l'amont n'a pas.
« rebase --onto <cible> <base> » ne rejoue que les commits posés depuis la
base gelée du fork (« fork-upstream-freeze-revision »), sans cet écart :
il ne sert que lorsque l'amont a été RÉÉCRIT (la base n'est plus ancêtre
de la cible), où un rebase ordinaire rejouerait l'ancien amont comme s'il
était à nous.
Encore faut-il que la base décrive HEAD : le commit gelé doit être HEAD ou
son ancêtre, et la base l'ancêtre du commit gelé. Une base périmée — le
fork a intégré un amont plus récent depuis le gel — ferait rejouer comme
nôtres les commits amont posés entre elle et HEAD, puis les publierait.
Le mode retenu et sa raison s'inscrivent dans « mode ». Un fork sans
commit propre ne se rebase pas : sa branche datée avance sur l'amont
(« merge --ff-only »).

La passe sans menu
------------------
« repo_apply.py --apply » applique une passe sans terminal, pour un
appelant qui a déjà montré l'essai à sec et recueilli le consentement
(le module Odoo erplibre_info). Trois écarts au menu la bornent. Seuls
les verdicts sans conflit prédit s'appliquent (VERDICTS_SANS_CONFLIT).
Un dépôt qui bute malgré tout voit son rebase abandonné et revient sur
son départ (« conflit_annule ») : hors du menu, personne ne reprend la
file, et un arbre en conflit est un code que le serveur chargerait. La
liste des dépôts consentie (« --expect ») doit être celle que le
diagnostic refait à l'instant, et chaque dépôt épinglé doit avoir gardé le
commit amont et le HEAD montrés ; sinon rien ne s'écrit (code 4).

La publication
--------------
Seule la publication sort du dépôt local. Elle pousse la pointe de la
branche datée sur la branche du fork, toujours sous
« --force-with-lease » : le bail porte la pointe distante inscrite dans
la passe, et git refuse le push si le distant n'y est plus. Une pointe
suivie qui diffère déjà de cette inscription refuse la publication avant
tout envoi : la passe est à refaire. Avant un push forcé, l'ancienne pointe
distante et le commit gelé doivent rester atteignables par un tag ou une
autre branche que le distant porte (« git ls-remote ») ; sinon le push est
refusé, et c'est au menu de faire poser cette référence.
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.git import manifest_freeze, repo_upgrade  # noqa: E402
from script.git.repo_upgrade import (  # noqa: E402
    DELAI_GIT,
    REPO_ROOT,
    git,
    t,
)

# L'enregistrement des passes. Sous « tasks/ », qui n'est pas versionné :
# une trace d'exécution n'a rien à faire dans l'historique du dépôt, et le
# rapport durable est l'instantané de manifeste, pas ce journal.
DOSSIER_PASSES = os.path.join("tasks", "git_repo_upgrade")

VERDICTS_A_APPLIQUER = ("a_rebaser", "en_conflit", "absorbe", "en_retard")

# Les états d'un dépôt dont la branche datée est prête à publier.
ETATS_PUBLIABLES = ("rebase", "avance")

# Les états qu'un rebase terminé hors du menu laisse périmés.
ETATS_A_RECONCILIER = ("conflit", "rebase_refuse")

# Les valeurs de « mode », le choix du rebase et sa raison.
MODE_ONTO = "onto: upstream rewritten"
MODE_SANS_BASE = "plain: no frozen base"
MODE_BASE_AMONT = "plain: upstream still holds the frozen base"
MODE_BASE_ABSENTE = "plain: frozen base absent from the clone"
MODE_GEL_HORS_HEAD = "plain: frozen commit not in HEAD"
MODE_BASE_HORS_GEL = "plain: frozen base not under the frozen commit"


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


def sha_de(chemin, ref):
    """Le commit que `ref` désigne, ou None si elle ne désigne rien."""
    out, _err, code = git(
        ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], chemin
    )
    return out.strip() if code == 0 and out.strip() else None


def est_ancetre(chemin, ancetre, descendant):
    """True, False, ou None quand git ne tranche pas (commit absent)."""
    _out, _err, code = git(
        ["merge-base", "--is-ancestor", ancetre, descendant], chemin
    )
    if code in (0, 1):
        return code == 0
    return None


def arbre_sale(chemin):
    """Des fichiers suivis sont-ils modifiés ? Un échec de git compte comme
    oui : le rebase qui suivrait n'a pas plus de chances de réussir."""
    out, _err, code = git(
        ["status", "--porcelain", "--untracked-files=no"], chemin
    )
    return bool(code or out.strip())


def suivi_distant(chemin, remote, revision):
    """La pointe que le clone connaît de la branche du fork, ou None.

    « refs/remotes/<remote>/<revision> », que « repo sync » rafraîchit. Une
    `revision` qui est un commit n'a pas de branche à suivre.
    """
    if not remote or not revision or manifest_freeze.is_sha(revision):
        return None
    return sha_de(chemin, f"refs/remotes/{remote}/{revision}")


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


def choisir_rebase(chemin, base, gel, cible="FETCH_HEAD"):
    """(onto, mode) : faut-il « rebase --onto <cible> <base> » ?

    `base` est la base amont gelée, `gel` le commit gelé du fork, `cible`
    la référence de l'amont. True seulement quand l'amont a perdu `base`
    (réécrit), que `gel` est HEAD ou son ancêtre, et que `base` est
    l'ancêtre de `gel`. `mode` est l'une des valeurs MODE_*, qui nomme la
    condition décisive.
    """
    if not base:
        return False, MODE_SANS_BASE
    dans_amont = est_ancetre(chemin, base, cible)
    if dans_amont is None:
        return False, MODE_BASE_ABSENTE
    if dans_amont:
        return False, MODE_BASE_AMONT
    if not gel or est_ancetre(chemin, gel, "HEAD") is not True:
        return False, MODE_GEL_HORS_HEAD
    if est_ancetre(chemin, base, gel) is not True:
        return False, MODE_BASE_HORS_GEL
    return True, MODE_ONTO


def appliquer(constat, horodatage, racine=REPO_ROOT, delai=DELAI_GIT):
    """Rebase un dépôt sur son amont dans une branche datée.

    Rend l'enregistrement de CE dépôt. Ne lève jamais : un dépôt qui bute
    est un résultat que la passe doit rapporter, pas une exception qui
    emporterait les quatorze autres.

    « cible » est la référence de l'amont que le diagnostic vient de
    récupérer (« <remote>/<branche> », ou FETCH_HEAD sans elle) : le rebase
    et le fast-forward la nomment, si bien que le reflog dit sur quoi la
    branche datée a été posée. Son commit s'inscrit dans « amont », qu'une
    récupération suivante ne déplace plus. « base » est le commit d'où nos
    commits se rejouent, « onto » dit si c'est la base gelée et « mode »
    pourquoi (voir `choisir_rebase`). « remote », « revision », « gel »
    (le commit gelé) et « distant » (la pointe suivie de la branche du
    fork, None sans elle) servent à la publication : « distant » y devient
    le bail.

    Deux refus précèdent toute écriture : un arbre de travail modifié
    (« sale »), sur lequel git refuserait le rebase, et une branche du fork
    dont la pointe connue n'est pas ancêtre de HEAD (« distant_en_avance ») :
    le distant porte des commits que HEAD n'a pas, et publier le résultat
    les perdrait.
    """
    chemin = os.path.join(racine, constat["chemin"] or "")
    cible = constat.get("cible") or "FETCH_HEAD"
    depart, _err, _code = git(["rev-parse", "HEAD"], chemin)
    resultat = {
        "chemin": constat["chemin"],
        "verdict_avant": constat.get("verdict"),
        "cible": cible,
        "remote": constat.get("remote"),
        "revision": constat.get("revision"),
        "gel": constat.get("gel"),
        "branche": None,
        "depart": depart.strip(),
        "arrivee": None,
        "amont": None,
        "base": None,
        "onto": False,
        "mode": None,
        "distant": None,
        "publie": None,
        "etat": "ignore",
        "conflits": [],
        "sortie": "",
        "restaure": None,
    }

    if constat.get("verdict") not in VERDICTS_A_APPLIQUER:
        return resultat
    if rebase_en_cours(chemin):
        resultat["etat"] = "rebase_deja_en_cours"
        resultat["conflits"] = fichiers_en_conflit(chemin)
        return resultat
    if arbre_sale(chemin):
        resultat["etat"] = "sale"
        return resultat
    distant = suivi_distant(
        chemin, constat.get("remote"), constat.get("revision")
    )
    resultat["distant"] = distant
    if distant and est_ancetre(chemin, distant, "HEAD") is not True:
        resultat["etat"] = "distant_en_avance"
        return resultat
    resultat["amont"] = sha_de(chemin, cible)

    branche = nom_branche(constat.get("revision") or "HEAD", horodatage)
    resultat["branche"] = branche
    if branche_existe(chemin, branche):
        # Écraser une branche datée effacerait le travail d'une passe
        # précédente du même jour, y compris des conflits résolus à la main.
        resultat["etat"] = "branche_existante"
        return resultat

    branche_depart = branche_courante(chemin)
    hors_suivi = fichiers_hors_suivi(chemin)
    out, err, code = git(["checkout", "-b", branche], chemin, delai)
    if code:
        resultat["etat"] = "branche_refusee"
        resultat["sortie"] = (out + err).strip()
        return resultat

    if constat.get("verdict") == "en_retard":
        out, err, code = git(["merge", "--ff-only", cible], chemin, delai)
        resultat["sortie"] = (out + err).strip()
        resultat["etat"] = "avance_refusee" if code else "avance"
        if code:
            resultat["restaure"], sortie = restaurer(
                chemin, resultat, branche_depart, hors_suivi, delai
            )
            resultat["sortie"] = "\n".join(
                x for x in (resultat["sortie"], sortie) if x
            )
        else:
            resultat["arrivee"] = sha_de(chemin, "HEAD")
        return resultat

    base = constat.get("base_gelee")
    onto, resultat["mode"] = choisir_rebase(
        chemin, base, constat.get("gel"), cible
    )
    if onto:
        commande = ["rebase", "--onto", cible, base]
        resultat["base"], resultat["onto"] = base, True
    else:
        commande = ["rebase", cible]
        resultat["base"] = constat.get("base")
    out, err, code = git(commande, chemin, delai)
    resultat["sortie"] = (out + err).strip()
    if code == 0:
        arrivee, _err, _c = git(["rev-parse", "HEAD"], chemin)
        resultat["arrivee"] = arrivee.strip()
        resultat["etat"] = "rebase"
        return resultat

    # Le rebase est LAISSÉ EN L'ÉTAT : c'est là que la résolution se fera.
    # L'abandonner ici obligerait à tout refaire pour reprendre la main.
    # Un échec sans rebase en cours ni fichier en conflit n'est pas un
    # conflit : git a refusé de commencer, et la file n'aurait rien à
    # reprendre ; le dépôt est alors remis où la passe l'a pris.
    resultat["conflits"] = fichiers_en_conflit(chemin)
    if resultat["conflits"] or rebase_en_cours(chemin):
        resultat["etat"] = "conflit"
    else:
        resultat["etat"] = "rebase_refuse"
        resultat["restaure"], sortie = restaurer(
            chemin, resultat, branche_depart, hors_suivi, delai
        )
        resultat["sortie"] = "\n".join(
            x for x in (resultat["sortie"], sortie) if x
        )
    return resultat


def fichiers_hors_suivi(chemin):
    """Les fichiers non suivis de l'arbre, ignorés compris, en ensemble.

    Le relevé d'AVANT une opération : `restaurer` n'efface que ce qui est
    apparu depuis, jamais un fichier que l'arbre portait déjà.
    """
    out, _err, code = git(["ls-files", "--others", "-z"], chemin)
    return set(x for x in out.split("\0") if x) if not code else set()


def restaurer(chemin, resultat, branche_depart, hors_suivi, delai=DELAI_GIT):
    """Remet le dépôt sur son départ après un rebase ou une avance refusés.

    Un checkout que git interrompt (un lien symbolique qu'un système de
    fichiers distant refuse, un dossier sans droit d'écriture) laisse
    l'arbre à moitié écrit : des fichiers suivis au contenu de l'amont, des
    fichiers de l'amont posés hors suivi, et HEAD sur la branche datée.
    Trois gestes le défont :

    - « checkout -f » vers `branche_depart`, ou HEAD détachée sur
      « depart » sans elle. Le « -f » ne peut rien perdre : `appliquer` n'a
      commencé que sur un arbre sans modification suivie ;
    - l'effacement des fichiers non suivis apparus depuis le relevé
      `hors_suivi` ET présents dans l'amont relevé, puis de leurs dossiers
      devenus vides ;
    - la suppression de la branche datée, qui pointe encore « depart ».

    Rend (restauré, sortie). Une branche datée supprimée quitte
    `resultat["branche"]`. Un échec garde la branche datée, et la sortie
    donne la commande à lancer à la main.
    """
    depart, branche = resultat["depart"], resultat["branche"]
    if branche_depart:
        retour = ["checkout", "-f", branche_depart]
    else:
        retour = ["checkout", "-f", "--detach", depart]
    out, err, code = git(retour, chemin, delai)
    if code:
        manuel = " ".join(["git", "-C", resultat["chemin"]] + retour)
        return False, f"{(out + err).strip()}\n{t('To run by hand:')} {manuel}"
    de_l_amont = set()
    if resultat["amont"]:
        amont, _err, code = git(
            ["ls-tree", "-r", "--name-only", "-z", resultat["amont"]], chemin
        )
        de_l_amont = set(amont.split("\0")) if not code else set()
    for relatif in sorted(fichiers_hors_suivi(chemin) - hors_suivi):
        if relatif not in de_l_amont:
            continue
        try:
            os.remove(os.path.join(chemin, relatif))
        except OSError:
            continue
        dossier = os.path.dirname(relatif)
        while dossier:
            try:
                os.rmdir(os.path.join(chemin, dossier))
            except OSError:
                break
            dossier = os.path.dirname(dossier)
    _out, _err, code = git(["branch", "-D", branche], chemin, delai)
    if not code:
        resultat["branche"] = None
    return True, ""


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
    _ecrire_charge(dossier, charge)
    for res in resultats:
        if not res.get("sortie"):
            continue
        nom = (res["chemin"] or "inconnu").replace("/", "_") + ".log"
        with open(os.path.join(dossier, nom), "w") as fh:
            fh.write(res["sortie"] + "\n")
    return dossier


def _ecrire_charge(dossier, charge):
    with open(os.path.join(dossier, "passe.json"), "w") as fh:
        json.dump(charge, fh, indent=2, ensure_ascii=False, default=sorted)


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


def mettre_a_jour_passe(horodatage, chemin_projet, champs, racine=REPO_ROOT):
    """Réécrit dans passe.json l'enregistrement du dépôt `chemin_projet`.

    `champs` remplace les clés qu'il nomme et laisse les autres. Rend
    l'enregistrement mis à jour, ou None quand la passe ou le dépôt
    manque : rien n'est alors écrit.
    """
    passe = lire_passe(horodatage, racine)
    if not passe:
        return None
    for res in passe.get("resultats") or []:
        if res.get("chemin") == chemin_projet:
            res.update(champs)
            _ecrire_charge(dossier_passe(passe["horodatage"], racine), passe)
            return res
    return None


def noter_resolution(horodatage, res, etat, racine=REPO_ROOT):
    """Inscrit l'issue d'une résolution manuelle dans la passe et dans `res`.

    `etat` vaut « rebase » (le rebase s'est terminé : « arrivee » prend la
    HEAD du dépôt), « abandonne » ou « revenu » (plus rien à publier).
    Rend l'enregistrement de la passe, ou None si elle ne l'a pas.
    """
    chemin = os.path.join(racine, res["chemin"] or "")
    champs = {
        "etat": etat,
        "conflits": [],
        "arrivee": sha_de(chemin, "HEAD") if etat == "rebase" else None,
    }
    res.update(champs)
    return mettre_a_jour_passe(horodatage, res["chemin"], champs, racine)


def branche_courante(chemin):
    """Le nom court de la branche extraite, ou None en HEAD détachée."""
    out, _err, code = git(
        ["symbolic-ref", "--quiet", "--short", "HEAD"], chemin
    )
    return out.strip() if code == 0 and out.strip() else None


def reconcilier_passe(passe, racine=REPO_ROOT):
    """Relit dans git l'issue des rebases finis hors des gestes du menu.

    Un dépôt inscrit « conflit » ou « rebase_refuse » sans rebase en cours
    prend « rebase » (« arrivee » = la pointe de sa branche datée) quand
    cette branche contient l'amont relevé, où que HEAD se trouve : c'est la
    branche que la publication pousse. Sinon, il prend « revenu » quand il
    est détaché sur son « depart ». Ailleurs, l'enregistrement reste tel
    quel.

    Modifie `passe` en place et réécrit passe.json quand un état change.
    Rend une liste de (enregistrement, état d'avant, état d'après), où
    l'état d'après vaut None pour un dépôt laissé tel quel.
    """
    notes = []
    for res in passe.get("resultats") or []:
        if res.get("etat") not in ETATS_A_RECONCILIER:
            continue
        chemin = os.path.join(racine, res.get("chemin") or "")
        if rebase_en_cours(chemin):
            continue
        avant = res["etat"]
        head = sha_de(chemin, "HEAD")
        pointe = (
            sha_de(chemin, f"refs/heads/{res['branche']}")
            if res.get("branche")
            else None
        )
        if (
            pointe
            and res.get("amont")
            and est_ancetre(chemin, res["amont"], pointe) is True
        ):
            res.update(etat="rebase", arrivee=pointe, conflits=[])
        elif (
            head
            and branche_courante(chemin) is None
            and head == res.get("depart")
        ):
            res.update(etat="revenu", arrivee=None, conflits=[])
        notes.append(
            (res, avant, None if res["etat"] == avant else res["etat"])
        )
    if any(apres for _res, _avant, apres in notes):
        _ecrire_charge(dossier_passe(passe["horodatage"], racine), passe)
    return notes


# ── Publier ────────────────────────────────────────────────────────────


def publiable(res):
    """Le dépôt a-t-il une branche datée prête à pousser sur son fork ?"""
    return (
        res.get("etat") in ETATS_PUBLIABLES
        and bool(res.get("branche"))
        and bool(res.get("remote"))
        and not manifest_freeze.is_sha(res.get("revision"))
    )


def refs_du_fork(chemin, remote, delai=DELAI_GIT):
    """{ref: commit} des branches et des tags que `remote` porte, ou None.

    Lu au distant par « git ls-remote » : une référence locale ou un suivi
    périmé ne dit pas ce que le distant garde. Un tag annoté vaut le commit
    qu'il désigne (sa ligne « ^{} »). None quand le distant ne répond pas.
    Passe par le réseau : réservé à la publication.
    """
    out, _err, code = git(["ls-remote", remote], chemin, delai)
    if code:
        return None
    refs = {}
    for ligne in out.splitlines():
        sha, _sep, ref = ligne.strip().partition("\t")
        if not ref.startswith(("refs/heads/", "refs/tags/")):
            continue
        if ref.endswith("^{}"):
            refs[ref[:-3]] = sha
        else:
            refs.setdefault(ref, sha)
    return refs


def _retenant(chemin, sha, revision, refs):
    """Les références de `refs` qui contiennent `sha`, une à une.

    `refs` vient de `refs_du_fork` ; « refs/heads/<revision> », que la
    publication réécrit, ne compte pas. Une référence compte quand son
    commit est présent dans le clone et que `sha` en est l'ancêtre ou
    l'égal. Chaque commit distinct ne se teste qu'une fois.
    """
    exclue = f"refs/heads/{revision}"
    vus = {}
    for ref in sorted(refs or {}):
        if ref == exclue:
            continue
        cible = refs[ref]
        if cible not in vus:
            vus[cible] = est_ancetre(chemin, sha, cible) is True
        if vus[cible]:
            yield ref


def retenu_par(chemin, sha, remote, revision, refs=None):
    """Les références du distant qui gardent `sha` atteignable sans la
    branche `revision` du fork, triées. `refs` (voir `refs_du_fork`) évite
    une seconde lecture du distant ; None la lance."""
    if refs is None:
        refs = refs_du_fork(chemin, remote)
    return list(_retenant(chemin, sha, revision, refs))


def a_retenir(chemin, ancien, gel, nouveau, remote, revision, refs=None):
    """Les commits qu'un push forcé de `nouveau` rendrait inatteignables.

    Les candidats sont l'ancienne pointe distante `ancien` et le commit
    gelé `gel` quand il en est ancêtre : ailleurs, la branche réécrite ne
    le portait pas. Un candidat ancêtre de `nouveau`, ou contenu dans une
    référence que le distant porte (voir `retenu_par`), reste atteignable.
    Une référence posée sur `ancien` retient aussi `gel`. Le distant n'est
    lu qu'une fois, et seulement s'il reste un candidat à vérifier.
    """
    candidats = [ancien] if ancien else []
    if gel and gel != ancien and ancien and est_ancetre(chemin, gel, ancien):
        candidats.append(gel)
    restants = [
        sha for sha in candidats if not est_ancetre(chemin, sha, nouveau)
    ]
    if restants and refs is None:
        refs = refs_du_fork(chemin, remote)
    return [
        sha
        for sha in restants
        if next(_retenant(chemin, sha, revision, refs), None) is None
    ]


def _refs_au_bail(chemin, remote, revision, ancien):
    """(refs du distant, refus) avant un push forcé.

    La pointe que le distant annonce pour « refs/heads/<revision> » doit
    être `ancien`, celle de la passe : un suivi local non rafraîchi ne voit
    pas un distant qui a bougé, et la question de rétention pousserait alors
    un tag ou une branche avant que le bail ne refuse le push principal.
    Rend (None, raison) quand le distant ne répond pas ou a bougé.
    """
    refs = refs_du_fork(chemin, remote)
    if refs is None:
        return None, t("fork remote unreachable")
    if refs.get(f"refs/heads/{revision}") != ancien:
        return None, t("remote moved since the pass: run the pass again")
    return refs, None


def plan_publication(chemin, res):
    """Ce que la publication de `res` pousserait, ou None si rien.

    dict : « remote », « revision » (la branche du fork), « branche » (la
    branche datée), « ancien » (la pointe distante inscrite dans la passe,
    « distant » dans `res`, None si la branche n'existait pas au distant),
    « nouveau » (la pointe de la branche datée), « gel » (le commit gelé),
    « force » (l'ancien n'est pas ancêtre du nouveau), « a_retenir » (voir
    `a_retenir`, vide sans force) et « refus » : None, ou la raison qui
    interdit de publier. La pointe suivie qui diffère du relevé de la passe
    est un refus : le distant a reçu des commits que la branche datée
    ignore. Pour un push forcé, le distant est lu (voir `_refs_au_bail`) :
    une pointe distante qui n'est plus celle de la passe, ou un distant
    muet, est aussi un refus. Un refus laisse « a_retenir » vide.
    """
    if not publiable(res):
        return None
    nouveau = sha_de(chemin, f"refs/heads/{res['branche']}")
    if not nouveau:
        return None
    ancien = res.get("distant")
    refus = None
    if suivi_distant(chemin, res["remote"], res["revision"]) != ancien:
        refus = t("remote moved since the pass: run the pass again")
    force = bool(ancien) and not est_ancetre(chemin, ancien, nouveau)
    refs = None
    if force and not refus:
        refs, refus = _refs_au_bail(
            chemin, res["remote"], res["revision"], ancien
        )
    return {
        "remote": res["remote"],
        "revision": res["revision"],
        "branche": res["branche"],
        "ancien": ancien,
        "nouveau": nouveau,
        "gel": res.get("gel"),
        "force": force,
        "refus": refus,
        "a_retenir": (
            a_retenir(
                chemin,
                ancien,
                res.get("gel"),
                nouveau,
                res["remote"],
                res["revision"],
                refs=refs,
            )
            if force and not refus
            else []
        ),
    }


def nom_par_defaut_tag(version_erplibre, version_odoo, existants, horodatage):
    """« ERPLibre/v<version>_odoo<version d'Odoo> », suffixé du jour
    « _<AAAAMMJJ> » quand ce nom figure dans `existants`."""
    nom = f"ERPLibre/v{version_erplibre}_odoo{version_odoo}"
    return f"{nom}_{horodatage[:8]}" if nom in existants else nom


def nom_par_defaut_branche(revision, horodatage):
    """« <branche>_avant_maj_<AAAAMMJJ> »."""
    return f"{revision}_avant_maj_{horodatage[:8]}"


def tags(chemin):
    """Les noms des tags du clone."""
    out, _err, code = git(["tag", "--list"], chemin)
    return set() if code else {x.strip() for x in out.splitlines() if x}


def version_erplibre(racine=REPO_ROOT):
    """La version d'ERPLibre, lue dans la section « [tool.poetry] » de
    « pyproject.toml », ou "" introuvable."""
    try:
        with open(os.path.join(racine, "pyproject.toml")) as fh:
            texte = fh.read()
    except OSError:
        return ""
    section = re.search(
        r"^\[tool\.poetry\]\s*$(.*?)(?=^\[|\Z)", texte, re.M | re.S
    )
    if not section:
        return ""
    trouve = re.search(r'^version\s*=\s*"([^"]+)"', section.group(1), re.M)
    return trouve.group(1) if trouve else ""


def retenir(chemin, sha, remote, genre, nom, delai=DELAI_GIT):
    """Pose le tag ou la branche `nom` sur `sha` et le pousse au remote.

    `genre` vaut « tag » ou « branche ». La branche ne se crée qu'au
    distant, par un push dont le bail vide exige qu'elle n'y existe pas :
    une branche homonyme n'est jamais déplacée. Le tag se crée d'abord dans
    le clone, et git refuse un nom déjà pris ; un push refusé le retire,
    car un tag local ne retient rien au distant et bloquerait un second
    essai du même nom. Rend (sortie, erreur, code).
    """
    if genre == "tag":
        out, err, code = git(["tag", nom, sha], chemin)
        if code:
            return out, err, code
        ref = f"refs/tags/{nom}"
        out, err, code = git(["push", remote, f"{ref}:{ref}"], chemin, delai)
        if code:
            git(["tag", "-d", nom], chemin)
        return out, err, code
    ref = f"refs/heads/{nom}"
    return git(
        ["push", f"--force-with-lease={ref}:", remote, f"{sha}:{ref}"],
        chemin,
        delai,
    )


def publier(chemin, plan, delai=DELAI_GIT):
    """Pousse la branche datée sur la branche du fork. (sortie, erreur, code)

    Le push porte toujours « --force-with-lease » sur `plan["ancien"]`, la
    pointe inscrite dans la passe (bail vide : la branche ne doit pas
    exister au distant) : git refuse si le distant n'y est plus. Avant tout
    envoi, trois refus : un « refus » du plan, une pointe suivie qui a
    quitté cette inscription, et, pour un push forcé, un commit de `a_retenir` qu'aucune
    référence du distant ne retient. Une fois le push accepté, le dépôt est
    détaché sur le commit poussé : c'est l'état que git-repo attend, et la
    branche datée reste.
    """
    revision, ancien = plan["revision"], plan["ancien"]
    if plan.get("refus"):
        return "", plan["refus"], 1
    if suivi_distant(chemin, plan["remote"], revision) != ancien:
        return "", t("remote moved since the pass: run the pass again"), 1
    if plan["force"]:
        refs, refus = _refs_au_bail(chemin, plan["remote"], revision, ancien)
        if refus:
            return "", refus, 1
        restants = a_retenir(
            chemin,
            ancien,
            plan.get("gel"),
            plan["nouveau"],
            plan["remote"],
            revision,
            refs=refs,
        )
        if restants:
            raison = t("commits retained by no tag or branch")
            return "", f"{raison}: {' '.join(restants)}", 1
    args = [
        "push",
        f"--force-with-lease=refs/heads/{revision}:{ancien or ''}",
        plan["remote"],
        f"refs/heads/{plan['branche']}:refs/heads/{revision}",
    ]
    out, err, code = git(args, chemin, delai)
    if code:
        return out, err, code
    _o, err_detache, _c = git(
        ["checkout", "--detach", plan["nouveau"]], chemin, delai
    )
    return out, err + err_detache, 0


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
    c'est le seul repère juste : détacher sur la cible poserait le dépôt
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


# ── passe sans menu ─────────────────────────────────────────────────────

# Les verdicts qu'une passe sans menu applique : ceux pour lesquels le
# diagnostic ne prédit aucun conflit.
VERDICTS_SANS_CONFLIT = ("a_rebaser", "en_retard")

EXIT_USAGE = 2
EXIT_PLAN_CHANGE = 4


def annuler_conflit(chemin, res, branche_depart, delai=DELAI_GIT):
    """Abandonne le rebase en conflit de `res` et remet le dépôt sur son
    départ : la branche `branche_depart`, ou la HEAD détachée « depart ».

    Après « rebase --abort » l'arbre est propre et HEAD sur la branche
    datée, que `restaurer` quitte puis supprime. Le relevé des fichiers
    hors suivi est pris APRÈS l'abandon : aucun fichier n'est effacé.
    « etat » devient « conflit_annule » ; « conflits » garde la liste des
    fichiers qui ont buté.
    """
    out, err, code = abandonner_rebase(chemin, delai)
    if code:
        res["restaure"] = False
        res["sortie"] = "\n".join(
            x for x in (res.get("sortie"), (out + err).strip()) if x
        )
        return res
    res["restaure"], sortie = restaurer(
        chemin, res, branche_depart, fichiers_hors_suivi(chemin), delai
    )
    res["etat"] = "conflit_annule"
    res["sortie"] = "\n".join(x for x in (res.get("sortie"), sortie) if x)
    return res


def lire_attendu(texte):
    """(chemin, épingle) d'un argument « --expect ».

    « CHEMIN » seul ne consent qu'à la liste des dépôts ; « CHEMIN=CIBLE:HEAD »
    épingle en plus le commit amont et le HEAD que l'essai à sec a montrés
    (« cible_sha » et « head » du diagnostic) : l'épingle vaut alors
    {"cible_sha", "head"}, None sans elle. Un « = » sans deux commits
    complets lève ValueError.
    """
    chemin, egal, reste = texte.partition("=")
    if not egal:
        return texte, None
    cible, deux_points, head = reste.partition(":")
    if not (
        deux_points
        and manifest_freeze.is_sha(cible)
        and manifest_freeze.is_sha(head)
    ):
        raise ValueError(
            f"--expect {texte}: expected PATH=TARGET_SHA:HEAD_SHA"
        )
    return chemin, {"cible_sha": cible, "head": head}


def derives(retenus, epingles):
    """[{chemin, cle, attendu, trouve}] des forks retenus dont la cible ou le
    HEAD n'est plus celui de leur épingle ; un fork sans épingle n'est
    comparé à rien."""
    lst = []
    for constat in retenus:
        epingle = (epingles or {}).get(constat["chemin"])
        if not epingle:
            continue
        for cle in ("cible_sha", "head"):
            if constat.get(cle) != epingle[cle]:
                lst.append(
                    {
                        "chemin": constat["chemin"],
                        "cle": cle,
                        "attendu": epingle[cle],
                        "trouve": constat.get(cle),
                    }
                )
    return lst


def passe_sans_menu(
    version,
    attendus,
    racine=REPO_ROOT,
    horodatage=None,
    delai=DELAI_GIT,
    epingles=None,
):
    """Refait le diagnostic, vérifie le plan consenti, applique et inscrit.

    `attendus` est la liste des chemins que l'appelant a montrée et fait
    valider, `epingles` {chemin: {cible_sha, head}} l'état de chacun qu'il
    a montré (voir `lire_attendu`). Rend (charge, code) : code 0 quand la
    passe a tourné (les refus par dépôt sont dans « resultats »),
    EXIT_PLAN_CHANGE quand le diagnostic ne retient plus les mêmes dépôts,
    ou qu'un dépôt épinglé a un autre commit amont ou un autre HEAD
    (« derives ») — rien n'est alors écrit : le rebase irait sur un amont
    que personne n'a vu. « laisses » nomme les forks dont un conflit est
    prédit, à reprendre dans le menu. Rien n'est jamais poussé.
    """
    dossier = os.path.join(racine, "manifest")
    lst = repo_upgrade.passe_diagnostic(version, dossier, racine=racine)
    retenus = [c for c in lst if c.get("verdict") in VERDICTS_SANS_CONFLIT]
    plan = sorted(c["chemin"] for c in retenus)
    charge = {
        "version": version,
        "horodatage": None,
        "dossier": None,
        "plan": plan,
        "attendus": sorted(set(attendus)),
        "laisses": sorted(
            c["chemin"]
            for c in lst
            if c.get("verdict") in VERDICTS_A_APPLIQUER
            and c.get("verdict") not in VERDICTS_SANS_CONFLIT
        ),
        "resultats": [],
        "derives": [],
        "error": None,
    }
    if plan != charge["attendus"]:
        charge["error"] = "plan_changed"
        return charge, EXIT_PLAN_CHANGE
    charge["derives"] = derives(retenus, epingles)
    if charge["derives"]:
        charge["error"] = "plan_changed"
        return charge, EXIT_PLAN_CHANGE
    if not retenus:
        return charge, 0

    import datetime

    horodatage = horodatage or datetime.datetime.now().strftime("%Y%m%dT%H%M")
    departs = {
        c["chemin"]: branche_courante(os.path.join(racine, c["chemin"]))
        for c in retenus
    }
    resultats = passe_appliquer(retenus, horodatage, racine, delai=delai)
    for res in resultats:
        if res["etat"] == "conflit":
            annuler_conflit(
                os.path.join(racine, res["chemin"]),
                res,
                departs.get(res["chemin"]),
                delai,
            )
    dossier_ecrit = ecrire_passe(horodatage, version, lst, resultats, racine)
    charge["horodatage"] = horodatage
    charge["dossier"] = os.path.relpath(dossier_ecrit, racine)
    charge["resultats"] = resultats
    return charge, 0


def main(argv=None):
    """« --apply --confirm <version> [--expect CHEMIN[=CIBLE:HEAD]]… » : la
    passe sans menu, sortie JSON sur stdout. Code 2 pour un usage refusé
    (version retapée fausse, épingle illisible), 4 pour un plan changé, 1
    pour une erreur interne."""
    import argparse
    import traceback

    parser = argparse.ArgumentParser(
        description="Apply an upgrade pass without the menu (JSON output)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the forks without predicted conflict; never pushes",
    )
    parser.add_argument(
        "--confirm",
        metavar="VERSION",
        default="",
        help="the active Odoo version, typed again",
    )
    parser.add_argument(
        "--expect",
        metavar="PATH[=TARGET_SHA:HEAD_SHA]",
        action="append",
        default=[],
        help="a repository of the plan shown by the dry run, optionally "
        "pinned to the upstream commit and the HEAD it showed (repeatable)",
    )
    parser.add_argument("--root", default=REPO_ROOT)
    parser.add_argument(
        "--json",
        action="store_true",
        help="accepted for compatibility: the output is always JSON",
    )
    args = parser.parse_args(argv)
    racine = os.path.realpath(args.root)
    version = repo_upgrade.version_active(racine)

    def sortir(charge, code):
        json.dump(charge, sys.stdout, ensure_ascii=False, default=sorted)
        sys.stdout.write("\n")
        return code

    if not args.apply:
        return sortir({"error": "usage: --apply is required"}, EXIT_USAGE)
    if not version or args.confirm != version:
        return sortir(
            {"version": version, "error": "confirm_mismatch"}, EXIT_USAGE
        )
    try:
        lus = [lire_attendu(x) for x in args.expect]
    except ValueError as exc:
        return sortir({"version": version, "error": str(exc)}, EXIT_USAGE)
    attendus = [chemin for chemin, _e in lus]
    epingles = {chemin: e for chemin, e in lus if e}
    try:
        charge, code = passe_sans_menu(
            version, attendus, racine, epingles=epingles
        )
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return sortir({"error": f"internal: {type(exc).__name__}: {exc}"}, 1)
    return sortir(charge, code)


if __name__ == "__main__":
    sys.exit(main())
