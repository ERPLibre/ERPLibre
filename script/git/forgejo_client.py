#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Parler à une forge Forgejo par son API REST (v1).

Le client sert à préparer une forge qui reçoit les dépôts du manifeste :
vérifier qu'elle répond, s'assurer que chaque organisation existe (la créer
privée sinon), créer un dépôt privé quand la forge ne crée pas les dépôts
au premier push, déposer une clé SSH, et lister ou ouvrir des pull
requests. Chaque appel « assurer_* » est idempotent : ce qui existe déjà
est rendu tel quel, jamais recréé ni modifié.

L'API vit sous « <base>/api/v1 », la base étant l'URL web de la forge
(« https://hôte[:port] »), qui diffère de l'URL SSH des remotes. Le jeton
d'accès passe dans l'en-tête « Authorization: token … » ; il n'est jamais
écrit dans une URL, ni affiché, ni journalisé, et un message d'erreur qui
le contiendrait le masque. Il vient de EL_FORGEJO_TOKEN, sinon de ce que
rend `coffre(forge)` : une entrée du coffre KeePass d'ERPLibre par forge,
hôte et port (`cle_forge`).

La session que le client crée ignore l'environnement (« trust_env ») : une
entrée ~/.netrc pour l'hôte remplacerait sinon le jeton par un mot de
passe, et la forge agirait au nom d'un autre compte. Aucune redirection
n'est suivie : une redirection transformerait une création (POST) en
lecture (GET) et porterait l'en-tête du jeton vers une autre URL ; elle est
rapportée avec sa cible. Une réponse qui n'est pas le JSON attendu (une
page HTML derrière un mandataire, par exemple) est une ErreurForgejo comme
une autre.

Forgejo traite les noms d'organisation sans tenir compte de la casse :
deux propriétaires qui ne diffèrent que par elle ne font qu'une
organisation (`organisations_requises`). Le push-to-create ne crée jamais
le propriétaire : il doit exister avant le premier push. Un propriétaire
peut aussi être un COMPTE : celui du jeton reçoit ses dépôts par
« /user/repos » (`nature_proprietaire`), un autre compte n'est pas touché.

Une création concurrente répond « existe déjà » (422 pour une
organisation, 409 pour un dépôt ou une pull request) : les appels
« assurer_* » relisent alors l'existant au lieu d'échouer.
"""

import argparse
import os
import re
import shlex
import sys
import urllib.parse

DELAI_RESEAU = 30
# Taille de page demandée ; le serveur la plafonne à son MAX_RESPONSE_ITEMS,
# 50 par défaut et réglable : la lecture s'arrête donc sur une page vide.
PAGE = 50
# Les noms qu'accepte Forgejo : organisations (comme les comptes, 40
# caractères au plus) et dépôts (100 au plus).
_NOM_ORGANISATION = re.compile(r"^[\da-zA-Z][-.\w]*$")
_SEPARATEURS = re.compile(r"[-._]{2,}|[-._]$")
_NOM_DEPOT = re.compile(r"^[-.\w]+$")
# Un jeton ne contient ni blanc ni caractère de contrôle : requests refuse
# l'en-tête et recopie sa valeur dans son message d'erreur.
_JETON = re.compile(r"[\x21-\x7e]+")


def nom_organisation_valide(nom):
    """Vrai si Forgejo accepte `nom` comme organisation : lettres ASCII,
    chiffres, « - », « _ » et « . », un premier caractère alphanumérique,
    aucun séparateur doublé ni final, 40 caractères au plus."""
    return bool(
        nom
        and len(nom) <= 40
        and _NOM_ORGANISATION.match(nom)
        and nom.isascii()
        and not _SEPARATEURS.search(nom)
    )


def nom_depot_valide(nom):
    """Vrai si Forgejo accepte `nom` (sans « .git ») comme dépôt."""
    return bool(
        nom and len(nom) <= 100 and nom.isascii() and _NOM_DEPOT.match(nom)
    )


class ErreurForgejo(Exception):
    """Un refus de l'API, avec son statut HTTP quand il y en a un."""

    def __init__(self, message, statut=None):
        super().__init__(message)
        self.statut = statut


def base_web(url):
    """La base web d'une forge : « schéma://hôte[:port] » plus un éventuel
    sous-chemin, sans « / » final ni « /api/v1 ». None si `url` n'est pas
    une URL http(s)."""
    url = (url or "").strip().rstrip("/")
    if not re.match(r"^https?://[^/]+", url):
        return None
    return re.sub(r"/api/v1$", "", url)


def hote_de(url):
    """L'hôte, en minuscules, d'une URL http(s) ou ssh ; "" sinon."""
    url = (url or "").strip()
    m = re.match(r"^(?:[a-z+]+://)?(?:[^@/]+@)?([^/:]+)", url)
    return m.group(1).lower() if m else ""


def cle_forge(url):
    """« hôte[:port] » en minuscules d'une URL web : deux forges du même
    hôte sur deux ports ont chacune leur jeton. "" hors http(s)."""
    racine = base_web(url)
    if not racine:
        return ""
    return urllib.parse.urlsplit(racine).netloc.rsplit("@", 1)[-1].lower()


def est_locale(url):
    """Vrai si l'hôte de `url` est la machine elle-même (« localhost »,
    127.0.0.0/8, « ::1 ») : HTTP en clair n'y quitte pas l'hôte."""
    hote = urllib.parse.urlsplit(base_web(url) or "").hostname or ""
    return hote == "localhost" or hote == "::1" or hote.startswith("127.")


def jeton_valide(valeur):
    """Vrai si `valeur` peut passer dans un en-tête : ni blanc ni
    caractère de contrôle."""
    return bool(valeur) and bool(_JETON.fullmatch(valeur))


def jeton(forge, environ=None, coffre=None):
    """(jeton, source) de la forge `forge` (voir `cle_forge`), ou ("", "").

    EL_FORGEJO_TOKEN de l'environnement (source « env »), sinon
    `coffre(forge)` (source « coffre »). Le coffre n'est appelé que si
    l'environnement n'a rien : l'ouvrir peut demander le mot de passe
    maître. Les blancs qui entourent la valeur sont retirés. Aucun fichier
    versionné n'est lu : env_var.sh suit le dépôt."""
    environ = os.environ if environ is None else environ
    valeur = (environ.get("EL_FORGEJO_TOKEN") or "").strip()
    if valeur:
        return valeur, "env"
    if coffre is not None:
        valeur = (coffre(forge) or "").strip()
        if valeur:
            return valeur, "coffre"
    return "", ""


# Les chemins et le compte système de l'installateur du dépôt
# (script/forgejo/install_forgejo.sh).
FORGEJO_BIN = "/usr/local/bin/forgejo"
FORGEJO_CONF = "/etc/forgejo/app.ini"
FORGEJO_UTILISATEUR = "git"
PORTEES = ("write:organization", "write:repository", "write:user")


def commande_jeton_cli(compte, nom, portees=PORTEES):
    """La commande à lancer sur l'hôte de la forge pour créer le jeton
    `nom` du compte `compte` par la CLI d'administration de Forgejo.

    « sudo -n » : sans droit sudo sans mot de passe, elle échoue au lieu
    d'attendre une saisie que personne ne verrait. « --raw » ne rend que la
    valeur du jeton."""
    argv = [
        "sudo",
        "-n",
        "-u",
        FORGEJO_UTILISATEUR,
        FORGEJO_BIN,
        "admin",
        "user",
        "generate-access-token",
        "--username",
        compte,
        "--token-name",
        nom,
        "--scopes",
        ",".join(portees),
        "--raw",
        "--config",
        FORGEJO_CONF,
    ]
    return " ".join(shlex.quote(a) for a in argv)


def creer_jeton_par_ssh(cible, compte, nom, portees=PORTEES, lancer=None):
    """(jeton, "") créé sur l'hôte `cible` (« utilisateur@hôte ») par SSH,
    ou ("", motif). La valeur est la dernière ligne de la sortie ; elle
    n'est ni affichée ni journalisée. `lancer` remplace subprocess.run."""
    import subprocess

    lancer = lancer or subprocess.run
    try:
        fini = lancer(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=15",
                # Un hôte jamais contacté est accepté et retenu ; une clé
                # d'hôte qui a changé reste refusée.
                "-o",
                "StrictHostKeyChecking=accept-new",
                cible,
                commande_jeton_cli(compte, nom, portees),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", f"ssh {cible}: {exc}"
    if fini.returncode:
        erreur = (fini.stderr or "").strip().splitlines()
        return "", (erreur[-1] if erreur else f"code {fini.returncode}")
    lignes = [l.strip() for l in (fini.stdout or "").splitlines() if l.strip()]
    valeur = lignes[-1] if lignes else ""
    if not jeton_valide(valeur):
        return "", "the command returned no token"
    return valeur, ""


def organisations_requises(proprietaires):
    """Les organisations à assurer pour `proprietaires`, une par nom sans
    égard à la casse, la première écriture rencontrée retenue, triées. Les
    valeurs vides sont ignorées."""
    vues = {}
    for nom in proprietaires:
        if nom and nom.lower() not in vues:
            vues[nom.lower()] = nom
    return sorted(vues.values(), key=str.lower)


def _cle_ssh(cle):
    """Le type et le contenu d'une clé publique, sans son commentaire."""
    return " ".join((cle or "").split()[:2])


class ClientForgejo:
    """Les appels dont la préparation d'une forge a besoin.

    `session` répond à request() comme une requests.Session ; un test en
    passe une fausse. `jeton_api` s'envoie en « Authorization: token » ;
    sans lui, `identifiants` (utilisateur, mot de passe) passe en
    authentification basique, le temps d'amorcer une forge neuve.
    """

    def __init__(self, base, jeton_api=None, session=None, identifiants=None):
        racine = base_web(base)
        if not racine:
            raise ErreurForgejo(f"not a forge URL: {base!r}")
        if jeton_api and not jeton_valide(jeton_api):
            raise ErreurForgejo(
                "the token contains a blank or a control character"
            )
        if session is None:
            import requests

            session = requests.Session()
            session.trust_env = False
        self.base = racine
        self.api = f"{racine}/api/v1"
        self.session = session
        self.entetes = {"Accept": "application/json"}
        self.auth = None
        self._secrets = []
        if jeton_api:
            self.entetes["Authorization"] = f"token {jeton_api}"
            self._secrets.append(jeton_api)
        elif identifiants:
            self.auth = tuple(identifiants)
            self._secrets.extend(v for v in identifiants[1:] if v)
        self._compte = None

    def _masque(self, texte):
        for secret in self._secrets:
            texte = texte.replace(secret, "***")
        return texte

    def _appel(self, methode, chemin, ok=(200,), attendu=dict, **kw):
        """(statut, corps décodé). Le corps d'un statut 2xx doit être du
        type `attendu` (dict ou list) ; celui d'un autre statut admis par
        `ok` (un 404 « absent ») n'est pas lu et vaut None."""
        try:
            rep = self.session.request(
                methode,
                f"{self.api}{chemin}",
                headers=self.entetes,
                auth=self.auth,
                timeout=DELAI_RESEAU,
                allow_redirects=False,
                **kw,
            )
        except OSError as exc:
            raise ErreurForgejo(
                self._masque(f"{methode} {chemin} : {exc}")
            ) from None
        statut = rep.status_code
        if 300 <= statut < 400:
            cible = (getattr(rep, "headers", None) or {}).get("Location", "?")
            raise ErreurForgejo(
                f"{methode} {chemin} : {statut}, the forge redirects to"
                f" {cible}: use that URL",
                statut,
            )
        if statut not in ok:
            try:
                corps = rep.json()
                message = (
                    corps.get("message", "") if isinstance(corps, dict) else ""
                )
            except (ValueError, AttributeError):
                message = ""
            raise ErreurForgejo(
                self._masque(
                    f"{methode} {chemin} : {statut} {message}"
                ).rstrip(),
                statut,
            )
        if not 200 <= statut < 300:
            return statut, None
        try:
            corps = rep.json()
        except ValueError:
            corps = None
        if not isinstance(corps, attendu):
            raise ErreurForgejo(
                f"{methode} {chemin} : {statut}, not a Forgejo API response",
                statut,
            )
        return statut, corps

    @staticmethod
    def _q(nom):
        return urllib.parse.quote(nom, safe="")

    # ── Forge et comptes ─────────────────────────────────────────────

    def version(self):
        """La version de la forge ; sans authentification."""
        return self._appel("GET", "/version")[1].get("version", "")

    def identite(self):
        """Le compte du jeton (ou des identifiants), lu une fois."""
        if self._compte is None:
            self._compte = self._appel("GET", "/user")[1].get("login", "")
        return self._compte

    def utilisateur(self, nom):
        """Le compte `nom`, ou None s'il n'existe pas."""
        statut, corps = self._appel(
            "GET", f"/users/{self._q(nom)}", ok=(200, 404)
        )
        return corps if statut == 200 else None

    def creer_jeton(self, nom, portees):
        """Crée un jeton d'accès `nom` aux `portees` (« write:organization »…)
        pour le compte des identifiants, et rend sa valeur. Forgejo ne la
        montre qu'une fois. Exige l'authentification basique : un jeton ne
        peut pas en créer un autre."""
        if not self.auth:
            raise ErreurForgejo("creating a token needs the account password")
        corps = self._appel(
            "POST",
            f"/users/{self._q(self.auth[0])}/tokens",
            ok=(201,),
            json={"name": nom, "scopes": list(portees)},
        )[1]
        valeur = corps.get("sha1") or ""
        if not valeur:
            raise ErreurForgejo("the forge returned no token value")
        self._secrets.append(valeur)
        return valeur

    def cles_ssh(self):
        """Les clés publiques du compte."""
        return self._appel("GET", "/user/keys", attendu=list)[1]

    def ajouter_cle_ssh(self, titre, cle):
        """Dépose la clé publique `cle` sur le compte. Rend True si elle
        est ajoutée, False si le compte porte déjà cette clé.

        Forgejo répond 422 à bien des refus : clé invalide, SSH désactivé,
        titre déjà pris, clé portée par un autre compte. Seule une clé de
        même contenu sur CE compte vaut « déjà présente » ; tout autre 422
        est une erreur."""
        try:
            self._appel(
                "POST",
                "/user/keys",
                ok=(201,),
                json={"title": titre, "key": cle.strip()},
            )
            return True
        except ErreurForgejo as exc:
            if exc.statut != 422:
                raise
            contenu = _cle_ssh(cle)
            if any(_cle_ssh(k.get("key")) == contenu for k in self.cles_ssh()):
                return False
            raise

    # ── Organisations ────────────────────────────────────────────────

    def organisation(self, nom):
        """L'organisation, ou None si elle n'existe pas (ou n'est pas
        visible du compte). Un COMPTE du même nom rend aussi None : voir
        `nature_proprietaire`."""
        statut, corps = self._appel(
            "GET", f"/orgs/{self._q(nom)}", ok=(200, 404)
        )
        return corps if statut == 200 else None

    def nature_proprietaire(self, nom):
        """« organisation », « compte » (celui du jeton), « utilisateur »
        (un autre compte) ou « absent »."""
        if self.organisation(nom) is not None:
            return "organisation"
        if nom.lower() == (self.identite() or "").lower():
            return "compte"
        if self.utilisateur(nom) is not None:
            return "utilisateur"
        return "absent"

    def creer_organisation(self, nom, visibilite="private"):
        """Crée l'organisation `nom`, dont le compte devient propriétaire."""
        return self._appel(
            "POST",
            "/orgs",
            ok=(201,),
            json={"username": nom, "visibility": visibilite},
        )[1]

    def assurer_organisation(self, nom, visibilite="private"):
        """(« existante » | « creee », organisation). Une organisation
        existante n'est pas modifiée, sa visibilité comprise."""
        org = self.organisation(nom)
        if org is not None:
            return "existante", org
        try:
            return "creee", self.creer_organisation(nom, visibilite)
        except ErreurForgejo as exc:
            org = self.organisation(nom) if exc.statut == 422 else None
            if org is None:
                raise
            return "existante", org

    # ── Dépôts ───────────────────────────────────────────────────────

    def depot(self, proprietaire, nom):
        """Le dépôt, ou None s'il n'existe pas (ou n'est pas visible)."""
        statut, corps = self._appel(
            "GET",
            f"/repos/{self._q(proprietaire)}/{self._q(nom)}",
            ok=(200, 404),
        )
        return corps if statut == 200 else None

    def commit_de_branche(self, proprietaire, nom, branche):
        """Le commit de la branche `branche` du dépôt, ou None si la branche
        ou le dépôt manque. Une branche à « / » garde ses barres : la route
        de Forgejo les accepte telles quelles."""
        statut, corps = self._appel(
            "GET",
            f"/repos/{self._q(proprietaire)}/{self._q(nom)}/branches/"
            + urllib.parse.quote(branche, safe="/"),
            ok=(200, 404),
        )
        if statut != 200:
            return None
        return (corps.get("commit") or {}).get("id")

    def creer_depot(self, proprietaire, nom, prive=True, organisation=True):
        """Crée le dépôt vide `nom` dans l'organisation `proprietaire`, ou
        sur le compte du jeton quand `organisation` est faux."""
        chemin = (
            f"/orgs/{self._q(proprietaire)}/repos"
            if organisation
            else "/user/repos"
        )
        return self._appel(
            "POST",
            chemin,
            ok=(201,),
            json={"name": nom, "private": prive, "auto_init": False},
        )[1]

    def assurer_depot(self, proprietaire, nom, prive=True):
        """(« existant » | « cree », dépôt), le dépôt créé vide et privé
        par défaut. Il va dans l'organisation `proprietaire`, ou sur le
        compte du jeton quand `proprietaire` est ce compte ; un autre
        compte est refusé, le jeton ne pouvant y créer."""
        nom = nom[: -len(".git")] if nom.endswith(".git") else nom
        depot = self.depot(proprietaire, nom)
        if depot is not None:
            return "existant", depot
        nature = self.nature_proprietaire(proprietaire)
        if nature in ("utilisateur", "absent"):
            raise ErreurForgejo(
                f"{proprietaire}: {'another user account' if nature == 'utilisateur' else 'no such organisation'}"
            )
        try:
            return "cree", self.creer_depot(
                proprietaire, nom, prive, organisation=nature == "organisation"
            )
        except ErreurForgejo as exc:
            depot = (
                self.depot(proprietaire, nom) if exc.statut == 409 else None
            )
            if depot is None:
                raise
            return "existant", depot

    # ── Pull requests ────────────────────────────────────────────────

    def pull_requests(self, proprietaire, nom, etat="open", **filtres):
        """Les pull requests de `etat` (« open », « closed », « all »),
        toutes pages lues jusqu'à une page vide, ou jusqu'à une page qui
        répète la précédente. `filtres` passe tel quel dans la requête
        (« base », « head » : noms de branches)."""
        res = []
        page = 1
        precedent = None
        while True:
            lot = self._appel(
                "GET",
                f"/repos/{self._q(proprietaire)}/{self._q(nom)}/pulls",
                attendu=list,
                params=dict(filtres, state=etat, page=page, limit=PAGE),
            )[1]
            lot = [pr for pr in lot if isinstance(pr, dict)]
            # Une page identique à la précédente : le serveur ignore la
            # pagination, et relire ne rendrait jamais une page vide.
            numeros = [pr.get("number") for pr in lot]
            if not lot or numeros == precedent:
                return res
            res.extend(lot)
            precedent = numeros
            page += 1

    def pull_request_ouverte(self, proprietaire, nom, tete, base):
        """La pull request ouverte de la branche `tete` vers `base`, ou
        None. Le filtre de la requête est revérifié sur chaque réponse : un
        serveur qui l'ignore rend toutes les pull requests ouvertes."""
        for pr in self.pull_requests(proprietaire, nom, base=base, head=tete):
            if (pr.get("head") or {}).get("ref") == tete and (
                pr.get("base") or {}
            ).get("ref") == base:
                return pr
        return None

    def creer_pull_request(
        self, proprietaire, nom, tete, base, titre, corps=""
    ):
        """Ouvre une pull request de la branche `tete` vers `base` dans le
        même dépôt. Rend la pull request créée (« number », « html_url »)."""
        return self._appel(
            "POST",
            f"/repos/{self._q(proprietaire)}/{self._q(nom)}/pulls",
            ok=(201,),
            json={"head": tete, "base": base, "title": titre, "body": corps},
        )[1]

    def assurer_pull_request(
        self, proprietaire, nom, tete, base, titre, corps=""
    ):
        """(« existante » | « creee », pull request) : une pull request
        ouverte de `tete` vers `base` est reprise, jamais doublée."""
        pr = self.pull_request_ouverte(proprietaire, nom, tete, base)
        if pr is not None:
            return "existante", pr
        try:
            return "creee", self.creer_pull_request(
                proprietaire, nom, tete, base, titre, corps
            )
        except ErreurForgejo as exc:
            pr = (
                self.pull_request_ouverte(proprietaire, nom, tete, base)
                if exc.statut == 409
                else None
            )
            if pr is None:
                raise
            return "existante", pr


def plan_proprietaires(client, noms):
    """{nom: nature} de chaque propriétaire (voir `nature_proprietaire`),
    ou « erreur: <message> » quand la forge refuse la lecture."""
    res = {}
    for nom in noms:
        try:
            res[nom] = client.nature_proprietaire(nom)
        except ErreurForgejo as exc:
            res[nom] = f"erreur: {exc}"
    return res


def assurer_organisations(client, noms, visibilite="private"):
    """{nom: (etat, message)} pour chaque organisation : « existante »,
    « creee », ou « erreur » avec le refus de l'API ou du nom. Une erreur
    n'arrête pas les suivantes."""
    res = {}
    for nom in noms:
        if not nom_organisation_valide(nom):
            res[nom] = ("erreur", "name refused by Forgejo")
            continue
        try:
            etat, _org = client.assurer_organisation(nom, visibilite)
            res[nom] = (etat, "")
        except ErreurForgejo as exc:
            res[nom] = ("erreur", str(exc))
    return res


def get_config(argv=None):
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Prepare a Forgejo forge for the repositories of the active Odoo"
            " version: check it answers, create each missing organisation"
            " (private), and optionally each missing repository. The token"
            " comes from EL_FORGEJO_TOKEN only."
        ),
    )
    parser.add_argument(
        "--url", required=True, help="Web URL of the forge (https://…)."
    )
    parser.add_argument(
        "--create-repos",
        action="store_true",
        help=(
            "Also create the missing repositories, private and empty:"
            " needed when the forge does not create them on push."
        ),
    )
    parser.add_argument(
        "--allow-http",
        action="store_true",
        help=(
            "Accept a plain http:// URL on another host than this machine:"
            " the token then crosses the network in clear."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the missing organisations and repositories, create nothing.",
    )
    return parser.parse_args(argv)


def main(argv=None, client=None):
    """Prépare la forge pour les projets de `push_remote.projets_actifs`.

    Rend 0, 1 si la forge, son URL ou le jeton est refusé, 2 si une
    création échoue. Un propriétaire qui est un autre compte que celui du
    jeton est signalé et laissé tel quel."""
    config = get_config(argv)
    sys.path.append(
        os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    )
    from script.git import push_remote

    if (
        (config.url or "").startswith("http://")
        and not est_locale(config.url)
        and not config.allow_http
    ):
        print(
            "ERROR: plain http:// would send the token in clear;"
            " use https:// or --allow-http."
        )
        return 1
    os.chdir(push_remote.new_path)
    try:
        if client is None:
            client = ClientForgejo(
                config.url, jeton_api=jeton(cle_forge(config.url))[0]
            )
        print(f"Forgejo {client.version()} · {client.identite()}")
        projets = [
            p for p in push_remote.projets_actifs() if p["proprietaire"]
        ]
        natures = plan_proprietaires(
            client, organisations_requises(p["proprietaire"] for p in projets)
        )
    except ErreurForgejo as exc:
        print(f"ERROR: {exc}")
        return 1
    echecs = 0
    absentes = [n for n, nature in natures.items() if nature == "absent"]
    for nom, nature in natures.items():
        if nature.startswith("erreur") or nature == "utilisateur":
            print(f"  {nom}: {nature}")
            echecs += nature.startswith("erreur")
    print(
        f"Organisations: {len(natures)}, missing: {', '.join(absentes) or '-'}"
    )
    if not config.dry_run:
        for nom, (etat, message) in assurer_organisations(
            client, absentes
        ).items():
            print(f"  {nom}: {etat} {message}".rstrip())
            echecs += etat == "erreur"
    if config.create_repos:
        for p in projets:
            nom = (
                p["nom"][: -len(".git")]
                if p["nom"].endswith(".git")
                else p["nom"]
            )
            try:
                if config.dry_run:
                    if client.depot(p["proprietaire"], nom) is None:
                        print(
                            f"  missing repository: {p['proprietaire']}/{nom}"
                        )
                    continue
                etat, _ = client.assurer_depot(p["proprietaire"], nom)
            except ErreurForgejo as exc:
                etat = f"erreur {exc}"
                echecs += 1
            if etat != "existant":
                print(f"  {p['proprietaire']}/{nom}: {etat}")
    return 2 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
