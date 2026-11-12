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
    """Un refus de l'API, avec son statut et le message de GitHub.
    `statut` porte le code HTTP quand la réponse en avait un."""

    def __init__(self, message, statut=None):
        super().__init__(message)
        self.statut = statut


def depot_github(url):
    """(propriétaire, dépôt) d'une URL GitHub, ou None hors de GitHub."""
    trouve = _URL.match((url or "").strip())
    return (trouve.group(1), trouve.group(2)) if trouve else None


def jeton(racine=".", environ=None, coffre=None):
    """Le jeton GitHub, ou "" : EL_GITHUB_TOKEN de l'environnement, sinon ce
    que rend `coffre()` (le coffre KeePass d'ERPLibre, lu par le menu),
    sinon EL_GITHUB_TOKEN d'env_var.sh. `coffre` n'est appelé que si
    l'environnement n'a rien : l'ouvrir peut demander le mot de passe
    maître."""
    environ = os.environ if environ is None else environ
    if environ.get("EL_GITHUB_TOKEN"):
        return environ["EL_GITHUB_TOKEN"]
    if coffre is not None:
        valeur = coffre()
        if valeur:
            return valeur
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


# Ce que verifier_jeton() peut signaler. Les PROBLÈMES font échouer
# l'action à coup sûr ; les AVERTISSEMENTS la font échouer dans certains
# cas seulement.
TEXTES_JETON = {
    "jeton_refuse": "GitHub refuses the token: expired, revoked or mistyped.",
    "sans_repo": (
        "The token has neither the repo nor the public_repo scope: forks,"
        " pull requests and branch deletion will be refused."
    ),
    "pas_membre": (
        "The account of the token is not a member of the organisation:"
        " a fork into it will be refused."
    ),
    "invitation": (
        "The invitation to the organisation is not accepted yet:"
        " accept it on GitHub first."
    ),
    "public_seulement": (
        "public_repo scope only: private repositories are out of reach."
    ),
    "sans_workflow": (
        "No workflow scope: GitHub refuses to merge an upstream whose"
        " commits change .github/workflows."
    ),
    "jeton_fin": (
        "Fine-grained token: GitHub does not announce its rights, a missing"
        " one shows only when the action is refused; the token assistant is"
        " then offered."
    ),
    "adhesion_illisible": (
        "Membership of the organisation unreadable: the token lacks the"
        " read:org scope."
    ),
}
PROBLEMES_JETON = {"jeton_refuse", "sans_repo", "pas_membre", "invitation"}


def verifier_jeton(client, organisation=None):
    """Ce que le jeton du `client` permet, avant d'agir : {login, portees,
    role, codes}. `codes` liste des clés de TEXTES_JETON, problèmes et
    avertissements mêlés (PROBLEMES_JETON les distingue). `organisation`,
    si donnée et autre que le compte, fait vérifier l'adhésion."""
    res = {"login": None, "portees": None, "role": None, "codes": []}
    try:
        res["login"], res["portees"] = client.identite()
    except ErreurGitHub as exc:
        if exc.statut == 401:
            res["codes"].append("jeton_refuse")
            return res
        raise
    portees = res["portees"]
    if portees is None:
        res["codes"].append("jeton_fin")
    else:
        if "repo" not in portees and "public_repo" not in portees:
            res["codes"].append("sans_repo")
        elif "repo" not in portees:
            res["codes"].append("public_seulement")
        if "workflow" not in portees:
            res["codes"].append("sans_workflow")
    if organisation and organisation.lower() != (res["login"] or "").lower():
        etat, res["role"] = client.adhesion(organisation)
        if etat == "absent":
            res["codes"].append("pas_membre")
        elif etat == "invitation":
            res["codes"].append("invitation")
        elif etat == "illisible":
            res["codes"].append("adhesion_illisible")
    return res


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
                f"{methode} {chemin} : {rep.status_code} {message}",
                rep.status_code,
            )
        return rep

    def depot(self, proprietaire, nom):
        """Le dépôt, ou None s'il n'existe pas (ou n'est pas visible)."""
        rep = self._appel("GET", f"/repos/{proprietaire}/{nom}", ok=(200, 404))
        return rep.json() if rep.status_code == 200 else None

    def identite(self):
        """(compte du jeton, portées) ; portées vaut None quand GitHub
        n'en annonce pas (jeton à granularité fine ou d'application), une
        liste sinon (jeton classique, en-tête X-OAuth-Scopes)."""
        rep = self._appel("GET", "/user")
        entete = (getattr(rep, "headers", None) or {}).get("X-OAuth-Scopes")
        portees = (
            None
            if entete is None
            else [p.strip() for p in entete.split(",") if p.strip()]
        )
        return rep.json().get("login", ""), portees

    def adhesion(self, organisation):
        """L'adhésion du compte du jeton à `organisation` : (« membre »,
        rôle), (« invitation », None) tant qu'elle n'est pas acceptée,
        (« absent », None), ou (« illisible », None) quand le jeton n'a pas
        le droit de la lire (portée read:org)."""
        rep = self._appel(
            "GET",
            f"/user/memberships/orgs/{organisation}",
            ok=(200, 403, 404),
        )
        if rep.status_code == 404:
            return "absent", None
        if rep.status_code == 403:
            return "illisible", None
        corps = rep.json()
        if corps.get("state") != "active":
            return "invitation", None
        return "membre", corps.get("role")

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

    def pull_requests_de(self, nom_complet, tete):
        """Les pull requests fermées de `nom_complet` dont la tête est
        `tete` (« propriétaire:branche ») ; [] si le dépôt n'est pas
        visible. `merged_at` y dit si elle a été fusionnée."""
        rep = self._appel(
            "GET",
            f"/repos/{nom_complet}/pulls",
            ok=(200, 404),
            params={"state": "closed", "head": tete, "per_page": 100},
        )
        return [] if rep.status_code == 404 else rep.json()

    def synchroniser_fork(self, nom_complet, branche):
        """POST merge-upstream : avance `branche` du fork `nom_complet` sur
        la branche du même nom de son parent GitHub. Rend (code HTTP,
        corps) : 200 porte `merge_type` (« fast-forward », « merge » ou
        « none »), 409 un conflit, 422 une branche que GitHub refuse."""
        rep = self._appel(
            "POST",
            f"/repos/{nom_complet}/merge-upstream",
            ok=(200, 409, 422),
            json={"branch": branche},
        )
        try:
            corps = rep.json()
        except ValueError:
            corps = {}
        return rep.status_code, corps

    def depots_du_compte(self, compte, pages=20):
        """Les dépôts de l'organisation ou du compte `compte`, toutes pages
        lues jusqu'à `pages` (100 par page). Un compte qui n'est pas une
        organisation se lit par /users ; None s'il n'existe pas."""
        for racine in (f"/orgs/{compte}/repos", f"/users/{compte}/repos"):
            res = []
            for page in range(1, pages + 1):
                rep = self._appel(
                    "GET",
                    racine,
                    ok=(200, 404),
                    params={"per_page": 100, "page": page},
                )
                if rep.status_code == 404:
                    break
                lot = rep.json()
                res.extend(lot)
                if len(lot) < 100:
                    return res
            else:
                return res
        return None

    def archiver(self, nom_complet):
        """Archive le dépôt : il passe en lecture seule, et se désarchive
        depuis ses réglages sur GitHub. Demande le rôle admin du dépôt."""
        return self._appel(
            "PATCH", f"/repos/{nom_complet}", json={"archived": True}
        ).json()

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
