#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Parler à une forge Forgejo ou Gitea, qui servent la même API v1.

CE MODULE DÉCIDE ET N'AFFICHE RIEN. Il rend des verdicts nommés ; l'appelant
les écrit comme son menu les écrit. Séparer les deux est ce qui rend la
décision vérifiable sans forge, et ce qui permet au même code de servir un
menu, un script et une épreuve.

LE JETON NE VOYAGE QUE DANS UN EN-TÊTE. Jamais dans l'URL : une adresse
atterrit dans le journal d'accès du serveur, dans celui de tout mandataire
entre les deux, et dans l'historique du shell. L'en-tête, lui, n'est
journalisé par défaut nulle part. La différence n'est pas théorique — un
jeton d'API de forge donne le droit d'écrire dans tous les dépôts.

QUATRE REFUS SE RESSEMBLENT ET NE SE CORRIGENT PAS PAREIL. Un jeton absent,
un jeton refusé, un certificat non approuvé et une cible en plage privée
donnent tous « ça ne marche pas ». Le dernier est le plus trompeur : la
forge répond un refus de permission, qui se lit comme un mauvais jeton et
envoie régénérer un jeton parfaitement valide. C'est le réglage
« ALLOW_LOCALNETWORKS » de la forge, pas le jeton.
"""
from __future__ import annotations

from typing import NamedTuple
from urllib.parse import quote, urlsplit

# Le vocabulaire des verdicts, clos. Un cas de plus se déclare ici, où les
# appelants le verront, plutôt que de se glisser dans une chaîne libre.
OK = "ok"
NO_TOKEN = "no-token"
BAD_TOKEN = "bad-token"
LOCALNETWORK_REFUSED = "localnetwork-refused"
NOT_FOUND = "not-found"
ALREADY_EXISTS = "already-exists"
TLS_UNTRUSTED = "tls-untrusted"
UNREACHABLE = "unreachable"
REFUSED = "refused"
VERDICTS = (
    OK,
    NO_TOKEN,
    BAD_TOKEN,
    LOCALNETWORK_REFUSED,
    NOT_FOUND,
    ALREADY_EXISTS,
    TLS_UNTRUSTED,
    UNREACHABLE,
    REFUSED,
)

# Ce que la forge dit quand elle refuse une cible en plage privée. PLUSIEURS
# FORMULATIONS, parce qu'elles ont changé entre les versions de Gitea et de
# Forgejo, et qu'en manquer une fait conclure à un mauvais jeton. Comparées
# en minuscules, sur une sous-chaîne : le message complet porte l'hôte.
DITS_PLAGE_PRIVEE = (
    "private ip address",
    "local network",
    "not allowed to import local repositories",
    "resolve to a private",
)

# Ce que dit une bibliothèque TLS quand la chaîne ne se vérifie pas. Le
# certificat auto-signé d'une forge de laboratoire est le cas courant, et il
# se corrige en approuvant l'autorité — pas en changeant de jeton.
DITS_TLS = (
    "certificate verify failed",
    "self signed certificate",
    "self-signed certificate",
    "sslerror",
    "ssl: ",
)

# Ce que Forgejo met sur une page de liste quand rien ne le demande. Le
# demander EXPLICITEMENT est ce qui rend la pagination prévisible : le défaut
# du serveur se change dans sa configuration, et un client qui s'y fie
# s'arrête au bout d'une page sans le dire.
PAGE_SIZE = 50

# Un appel qui ne répond pas doit rendre la main. Sans borne, un menu se fige
# sur une forge éteinte et il ne reste que Ctrl-C.
TIMEOUT = 20


class Reponse(NamedTuple):
    """Ce que l'appel a conclu, et de quoi l'écrire.

    `data` porte ce que la forge a rendu quand `kind` vaut OK ; ailleurs il
    vaut None. `detail` est la ligne qui APPREND quelque chose — ce que la
    forge a répondu, tronqué, et jamais le jeton.
    """

    kind: str
    data: object = None
    status: int = 0
    detail: str = ""


def api_url(base: str, chemin: str) -> str:
    """L'URL d'un point d'API, à partir de l'adresse de base d'un profil.

    Les segments du chemin sont ÉCHAPPÉS un à un : un nom de dépôt porte ce
    que son propriétaire y a mis, et une espace non échappée changerait le
    point appelé. La barre oblique reste un séparateur, donc elle n'est pas
    échappée — mais les segments sont découpés avant.

    « . » ET « .. » SONT REFUSÉS, ils ne sont pas échappés. `quote` les
    laisse passer intacts — le point est non réservé en RFC 3986 — si bien
    qu'un segment « .. » remonte le chemin et appelle un autre point d'API
    que celui demandé. Les échapper serait pire encore : ils désigneraient
    alors un dépôt nommé « .. », qui n'existe pas. Un appelant qui en
    fabrique un a un défaut, et le lui dire vaut mieux que d'appeler
    ailleurs.
    """
    base = (base or "").rstrip("/")
    segments = [s for s in (chemin or "").strip("/").split("/") if s]
    for segment in segments:
        if segment in (".", ".."):
            raise ValueError(
                f"chemin d'API refusé : le segment « {segment} » remonte"
                f" le chemin ({chemin!r})."
            )
    propre = "/".join(quote(s, safe="") for s in segments)
    return f"{base}/api/v1/{propre}"


def headers(token: str) -> dict:
    """Les en-têtes d'un appel authentifié.

    « Authorization: token <jeton> » est la forme que Gitea et Forgejo
    attendent — « Bearer » marche aussi sur les versions récentes, mais pas
    sur les anciennes, et celle-ci marche partout.
    """
    entetes = {"Accept": "application/json"}
    if token:
        entetes["Authorization"] = f"token {token}"
    return entetes


def _contient(texte: str, formulations) -> bool:
    bas = (texte or "").lower()
    return any(dit in bas for dit in formulations)


def verdict_de_statut(status: int, corps: str) -> str:
    """Le verdict que porte un code HTTP, affiné par ce que la forge a dit.

    LE CORPS AVANT LE CODE pour la plage privée : la forge répond un refus
    de permission, exactement comme pour un jeton refusé. Sans lire le
    corps, les deux se confondent — et l'un se corrige dans la
    configuration de la forge, l'autre en changeant de jeton.
    """
    if _contient(corps, DITS_PLAGE_PRIVEE):
        return LOCALNETWORK_REFUSED
    if status in (401, 403):
        return BAD_TOKEN
    if status == 404:
        return NOT_FOUND
    if status == 409:
        return ALREADY_EXISTS
    if status == 422 and _contient(corps, ("already exist",)):
        return ALREADY_EXISTS
    if 200 <= status < 300:
        return OK
    return REFUSED


def verdict_de_panne(erreur: BaseException) -> str:
    """Le verdict que porte une panne de transport, sans en lire le type.

    Le TEXTE plutôt que la classe : `requests` enveloppe l'erreur TLS dans
    plusieurs exceptions selon sa version et selon la pile installée, et
    tester la classe ferait manquer le cas sur la moitié des postes.
    """
    if _contient(str(erreur), DITS_TLS):
        return TLS_UNTRUSTED
    return UNREACHABLE


def resume(corps: str, limite: int = 200) -> str:
    """La réponse de la forge, sur une ligne et bornée.

    Une page d'erreur HTML fait des kilo-octets : la déverser dans un menu
    noierait la seule ligne utile.
    """
    plat = " ".join((corps or "").split())
    return plat[:limite] + ("…" if len(plat) > limite else "")


# Les plages que la forge refuse quand « ALLOW_LOCALNETWORKS » est faux.
# ÉNUMÉRÉES, et non déduites de `ipaddress.is_private` : Python range dans
# « privé » tout ce que l'IANA marque à usage spécial, les plages de
# DOCUMENTATION comprises (192.0.2.0/24, 2001:db8::/32). La forge, elle, ne
# refuse que les plages ci-dessous. S'appuyer sur le prédicat de Python
# rendrait ce module PLUS strict que la forge : il refuserait sans appeler
# une opération que la forge aurait acceptée, et la seule trace serait un
# message parlant d'un réglage qui n'y est pour rien.
PLAGES_LOCALES = (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
)


def clone_est_en_plage_privee(url: str) -> bool:
    """Vrai si l'adresse à cloner vise une adresse littérale locale.

    Sert à PRÉVENIR plutôt qu'à guérir : le refus de la forge se lit comme
    un mauvais jeton, alors on le voit venir depuis l'appelant. Un NOM
    d'hôte rend faux — il se résout côté forge, et personne ici ne sait où.
    """
    import ipaddress

    hote = urlsplit(url or "").hostname or ""
    try:
        adresse = ipaddress.ip_address(hote.strip("[]"))
    except ValueError:
        return False
    return any(
        adresse in ipaddress.ip_network(plage)
        for plage in PLAGES_LOCALES
        if adresse.version == ipaddress.ip_network(plage).version
    )


class ForgeClient:
    """Les appels d'API d'un profil, avec son jeton.

    `session` est INJECTABLE : une session `requests` en production, un
    objet de banc dans les épreuves. C'est ce qui permet d'éprouver la
    pagination, les verdicts et le non-passage du jeton dans l'URL sans
    forge, sans réseau et sans jeton.

    Le client ne LIT PAS le coffre : le jeton lui est donné. Un module qui
    va chercher un secret tout seul se retrouve à demander une phrase de
    passe au milieu d'un affichage de liste.
    """

    def __init__(self, profile: dict, token: str = "", session=None):
        self._profile = dict(profile or {})
        self._token = token or ""
        self._session = session

    # ------------------------------------------------------------------
    # Le transport
    # ------------------------------------------------------------------
    def _requests(self):
        if self._session is not None:
            return self._session
        import requests

        self._session = requests.Session()
        return self._session

    def _appel(self, methode: str, chemin: str, **options) -> Reponse:
        """Un appel, et son verdict. Ne lève JAMAIS.

        Une panne de réseau est un VERDICT et non une exception : l'appelant
        est un menu, et un menu qui remonte une pile d'appels a perdu la
        conversation. Le jeton n'apparaît nulle part dans ce qui remonte —
        ni dans l'URL, ni dans le détail.
        """
        if not self._token:
            return Reponse(NO_TOKEN, detail="aucun jeton pour ce profil")
        url = api_url(self._profile.get("url", ""), chemin)
        try:
            reponse = self._requests().request(
                methode,
                url,
                headers=headers(self._token),
                verify=bool(self._profile.get("verify_tls", True)),
                timeout=TIMEOUT,
                **options,
            )
        except Exception as panne:  # noqa: BLE001
            # LARGE À DESSEIN : `requests` lève des types différents selon
            # sa version et selon la pile TLS installée, et un type manqué
            # remonterait au menu sous forme de trace. Le verdict, lui, est
            # décidé sur le TEXTE, qui ne dépend d'aucune de ces variantes.
            return Reponse(verdict_de_panne(panne), detail=resume(str(panne)))
        corps = reponse.text or ""
        kind = verdict_de_statut(reponse.status_code, corps)
        if kind != OK:
            return Reponse(
                kind, status=reponse.status_code, detail=resume(corps)
            )
        try:
            donnees = reponse.json()
        except ValueError:
            donnees = None
        return Reponse(OK, data=donnees, status=reponse.status_code)

    # ------------------------------------------------------------------
    # Les appels
    # ------------------------------------------------------------------
    def whoami(self) -> Reponse:
        """Le compte que le jeton représente.

        Le premier appel à faire : il coûte un aller-retour et distingue les
        quatre pannes qui se ressemblent, AVANT qu'une opération d'écriture
        échoue à moitié.
        """
        return self._appel("GET", "user")

    def repos(self) -> Reponse:
        """TOUS les dépôts du compte, pages comprises.

        La forge en rend une page à la fois. Un client qui lit la première
        et s'arrête annonce trente dépôts là où il y en a deux cents, sans
        rien dire — et « créer les dépôts manquants » en recréerait alors
        cent soixante-dix qui existent déjà.
        """
        tous = []
        page = 1
        while True:
            reponse = self._appel(
                "GET",
                "user/repos",
                params={"page": page, "limit": PAGE_SIZE},
            )
            if reponse.kind != OK:
                return reponse
            lot = reponse.data if isinstance(reponse.data, list) else []
            tous.extend(lot)
            # Une page INCOMPLÈTE est la dernière. S'arrêter sur une page
            # vide ferait un aller-retour de plus à chaque appel, et
            # tournerait sans fin si le serveur bornait « limit » plus bas
            # que ce qu'on demande.
            if len(lot) < PAGE_SIZE:
                return Reponse(OK, data=tous, status=reponse.status)
            page += 1

    def create_repo(self, name: str, private=True, description="") -> Reponse:
        """Crée un dépôt sous le compte du jeton.

        PRIVÉ par défaut : un dépôt de client créé public est visible le
        temps qu'on s'en aperçoive, et ce qui a été vu ne se reprend pas.
        """
        return self._appel(
            "POST",
            "user/repos",
            json={
                "name": name,
                "private": bool(private),
                "description": description or "",
            },
        )

    def migrate(self, clone_addr: str, name: str, mirror=True) -> Reponse:
        """Importe un dépôt distant, en miroir par défaut.

        SI LA CIBLE EST EN PLAGE PRIVÉE, le verdict est rendu SANS appeler :
        la forge refuse tant que « ALLOW_LOCALNETWORKS » n'est pas posé, et
        son refus se présente comme un problème de permission. Le dire ici
        épargne un aller-retour et surtout la mauvaise piste.
        """
        if clone_est_en_plage_privee(clone_addr):
            return Reponse(
                LOCALNETWORK_REFUSED,
                detail=(
                    "cible en plage privée : la forge la refuse tant que"
                    " FORGEJO_ALLOW_LOCALNETWORKS n'est pas posé à 1"
                ),
            )
        return self._appel(
            "POST",
            "repos/migrate",
            json={
                "clone_addr": clone_addr,
                "repo_name": name,
                "mirror": bool(mirror),
                "private": True,
            },
        )
