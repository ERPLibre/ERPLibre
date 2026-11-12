#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Forker un dépôt GitHub dans une organisation, par l'API REST.

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
                message = rep.json().get("message", "")
            except ValueError:
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
