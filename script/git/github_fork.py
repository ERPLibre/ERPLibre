#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Forker un dépôt GitHub dans une organisation, et en lister ou ouvrir
les pull requests, par l'API REST.

GitHub crée un fork en arrière-plan : POST /repos/{owner}/{repo}/forks
répond 202 avant que le dépôt existe vraiment, d'où `attendre()`, qui le
relit jusqu'à ce qu'il réponde. Le fork peut ne copier que la branche par
défaut (« default_branch_only ») ; une autre branche s'y crée ensuite par
une ref posée sur un commit du RÉSEAU de forks, que GitHub partage entre
le fork et sa source sans rien pousser.

Un dépôt du même nom déjà présent dans l'organisation est repris s'il
appartient au même réseau de forks, et refusé sinon : forker par-dessus
renommerait le nouveau fork en « nom-1 » sans le dire.

Le jeton vient de EL_GITHUB_TOKEN, dans l'environnement ou dans
env_var.sh ; il n'est jamais écrit ni affiché.
"""

import os
import re
import time

API = "https://api.github.com"
DELAI_RESEAU = 30
# GitHub annonce « quelques minutes » au pire pour un gros dépôt.
ATTENTE_FORK = 300
PAS_ATTENTE = 3

_URL = re.compile(
    r"^(?:https?://(?:[^@/]+@)?github\.com/|git@github\.com:|"
    r"ssh://git@github\.com/)([^/]+)/([^/]+?)(?:\.git)?/?$"
)


class ErreurGitHub(Exception):
    """Un refus de l'API, avec son statut et le message de GitHub."""


def depot_github(url):
    """(propriétaire, dépôt) d'une URL GitHub, ou None hors de GitHub."""
    trouve = _URL.match((url or "").strip())
    return (trouve.group(1), trouve.group(2)) if trouve else None


def jeton(racine=".", environ=None):
    """EL_GITHUB_TOKEN de l'environnement, sinon d'env_var.sh, ou ""."""
    environ = os.environ if environ is None else environ
    if environ.get("EL_GITHUB_TOKEN"):
        return environ["EL_GITHUB_TOKEN"]
    chemin = os.path.join(racine, "env_var.sh")
    try:
        with open(chemin, encoding="utf-8") as fh:
            for ligne in fh:
                cle, egal, valeur = ligne.strip().partition("=")
                if egal and cle.strip() == "EL_GITHUB_TOKEN":
                    return valeur.strip().strip("\"'")
    except OSError:
        pass
    return ""


class ClientGitHub:
    """Les appels dont le fork a besoin. `session` répond à request() comme
    une requests.Session ; un test en passe une fausse."""

    def __init__(self, jeton_api, session=None, dormir=time.sleep):
        if session is None:
            import requests

            session = requests.Session()
        self.session = session
        self.dormir = dormir
        self.entetes = {
            "Authorization": f"Bearer {jeton_api}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _appel(self, methode, chemin, ok=(200,), **kw):
        rep = self.session.request(
            methode,
            f"{API}{chemin}",
            headers=self.entetes,
            timeout=DELAI_RESEAU,
            **kw,
        )
        if rep.status_code not in ok:
            try:
                corps = rep.json()
                details = [
                    e.get("message") or e.get("code") or ""
                    for e in corps.get("errors") or []
                    if isinstance(e, dict)
                ]
                message = " ; ".join(
                    m for m in [corps.get("message", "")] + details if m
                )
            except (ValueError, AttributeError):
                message = ""
            raise ErreurGitHub(
                f"{methode} {chemin} : {rep.status_code} {message}"
            )
        return rep

    def depot(self, proprietaire, nom):
        """Le dépôt, ou None s'il n'existe pas (ou n'est pas visible)."""
        rep = self._appel("GET", f"/repos/{proprietaire}/{nom}", ok=(200, 404))
        return rep.json() if rep.status_code == 200 else None

    def utilisateur(self):
        """Le compte du jeton."""
        return self._appel("GET", "/user").json().get("login", "")

    def branche(self, nom_complet, branche):
        """Le commit de tête de `branche`, ou None si elle n'existe pas."""
        rep = self._appel(
            "GET", f"/repos/{nom_complet}/branches/{branche}", ok=(200, 404)
        )
        if rep.status_code != 200:
            return None
        return rep.json().get("commit", {}).get("sha")

    def forker(self, proprietaire, nom, organisation, toutes_branches):
        """Le fork de proprietaire/nom dans `organisation` : (dépôt, créé).

        Un dépôt du même nom déjà dans l'organisation est rendu tel quel
        (créé vaut False) s'il est du même réseau de forks ; sinon refus."""
        source = self.depot(proprietaire, nom)
        if source is None:
            raise ErreurGitHub(f"{proprietaire}/{nom} : 404")
        reseau = (source.get("source") or source).get("full_name")
        existant = self.depot(organisation, nom)
        if existant is not None:
            sien = (existant.get("source") or existant).get("full_name")
            if existant.get("fork") and sien == reseau:
                return existant, False
            raise ErreurGitHub(
                f"{organisation}/{nom} existe et n'est pas un fork de {reseau}"
            )
        corps = {"default_branch_only": not toutes_branches}
        # Forker vers son propre compte se demande sans « organization ».
        if organisation.lower() != self.utilisateur().lower():
            corps["organization"] = organisation
        rep = self._appel(
            "POST", f"/repos/{proprietaire}/{nom}/forks", ok=(202,), json=corps
        )
        return rep.json(), True

    def attendre(self, nom_complet, delai=ATTENTE_FORK, pas=PAS_ATTENTE):
        """Relit le fork jusqu'à ce qu'il réponde. Vrai s'il est prêt."""
        ecoule = 0
        while ecoule <= delai:
            proprietaire, nom = nom_complet.split("/", 1)
            if self.depot(proprietaire, nom) is not None:
                return True
            self.dormir(pas)
            ecoule += pas
        return False

    def pull_requests(self, nom_complet, etat="open", pages=10):
        """Les pull requests de `nom_complet` dans l'état `etat`, toutes
        pages lues jusqu'à `pages` (100 par page) ; None si le dépôt
        n'existe pas ou n'est pas visible."""
        res = []
        for page in range(1, pages + 1):
            rep = self._appel(
                "GET",
                f"/repos/{nom_complet}/pulls",
                ok=(200, 404),
                params={"state": etat, "per_page": 100, "page": page},
            )
            if rep.status_code == 404:
                return None
            lot = rep.json()
            res.extend(lot)
            if len(lot) < 100:
                break
        return res

    def mes_pull_requests(self, auteur, pages=3):
        """Les pull requests de `auteur`, tous dépôts et tous états, les
        plus récemment mises à jour d'abord, jusqu'à `pages` pages de 100.
        Ce sont des résultats de recherche : `repository_url` nomme le
        dépôt, `pull_request.merged_at` dit si elle est fusionnée."""
        res = []
        for page in range(1, pages + 1):
            lot = (
                self._appel(
                    "GET",
                    "/search/issues",
                    params={
                        "q": f"is:pr author:{auteur}",
                        "sort": "updated",
                        "order": "desc",
                        "per_page": 100,
                        "page": page,
                    },
                )
                .json()
                .get("items", [])
            )
            res.extend(lot)
            if len(lot) < 100:
                break
        return res

    def pull_request(self, nom_complet, numero):
        """Le détail d'une pull request : sa tête (`head.sha`), `draft`."""
        return self._appel(
            "GET", f"/repos/{nom_complet}/pulls/{numero}"
        ).json()

    def avis(self, nom_complet, numero):
        """Les revues d'une pull request, dans l'ordre où elles ont été
        données."""
        return self._appel(
            "GET",
            f"/repos/{nom_complet}/pulls/{numero}/reviews",
            params={"per_page": 100},
        ).json()

    def verifications(self, nom_complet, sha):
        """(statut combiné, check-runs) du commit `sha` : les deux systèmes
        de CI de GitHub, que les dépôts emploient l'un ou l'autre."""
        statut = self._appel(
            "GET", f"/repos/{nom_complet}/commits/{sha}/status"
        ).json()
        checks = self._appel(
            "GET",
            f"/repos/{nom_complet}/commits/{sha}/check-runs",
            params={"per_page": 100},
        ).json()
        return statut, checks.get("check_runs", [])

    def creer_pull_request(
        self, nom_complet, tete, base, titre, corps="", brouillon=False
    ):
        """Ouvre une pull request sur `nom_complet`, de `tete`
        (« propriétaire:branche ») vers la branche `base`. Rend la pull
        request créée."""
        rep = self._appel(
            "POST",
            f"/repos/{nom_complet}/pulls",
            ok=(201,),
            json={
                "title": titre,
                "head": tete,
                "base": base,
                "body": corps,
                "draft": brouillon,
            },
        )
        return rep.json()

    def creer_branche(self, nom_complet, branche, sha):
        """Pose refs/heads/`branche` sur `sha` dans le fork. Une branche déjà
        sur ce commit passe ; sur un autre, refus."""
        rep = self._appel(
            "POST",
            f"/repos/{nom_complet}/git/refs",
            ok=(201, 422),
            json={"ref": f"refs/heads/{branche}", "sha": sha},
        )
        if rep.status_code == 201:
            return True
        actuel = self.branche(nom_complet, branche)
        if actuel == sha:
            return False
        raise ErreurGitHub(
            f"{nom_complet} : la branche {branche} existe déjà sur {actuel}"
        )
