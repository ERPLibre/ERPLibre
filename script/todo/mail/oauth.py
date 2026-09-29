#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les jetons OAuth : les ranger, les rafraîchir.

Un jeton d'accès vit une heure ; le jeton de rafraîchissement qui le
renouvelle vit jusqu'à ce que son propriétaire le révoque. Le client ne voit
donc jamais d'écran d'autorisation en régime courant : il échange en
silence, avant chaque ouverture de session.

Ce module ne fait QUE l'échange HTTP, sur `urllib` — aucune dépendance
nouvelle pour une requête de formulaire et une réponse JSON.

Trois issues, et l'appelant doit les distinguer parce que le remède diffère :
le jeton neuf est arrivé ; l'autorisation est révoquée et aucun nouvel essai
ne la rendra (`RefreshRefused`) ; le fournisseur n'a pas répondu ou a répondu
n'importe quoi (`OAuthError`), auquel cas le jeton en place reste valable et
l'on réessaiera plus tard.

Aucun identifiant client n'est livré dans ce dépôt : `client_id` vient de la
configuration de celui qui déploie. Un champ vide est donc l'état NORMAL
d'une installation neuve, et le message le dit plutôt que de laisser le
fournisseur répondre « invalid_client ».
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import time
import webbrowser
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from script.todo.todo_i18n import t

# Marge avant l'expiration. Rafraîchir À l'échéance laisse partir une
# connexion avec un jeton qui meurt pendant la poignée de main : le serveur
# refuse, et le refus ressemble à une révocation.
MARGE_SECONDES = 60

# Personne n'est devant l'écran pendant un rafraîchissement : sans délai, une
# synchronisation se fige pour toujours sur un point de jeton muet.
DELAI_SECONDES = 30


class OAuthError(Exception):
    """L'échange a échoué. Le jeton en place reste ce qu'il était."""


class RefreshRefused(OAuthError):
    """Le fournisseur a REFUSÉ le jeton de rafraîchissement.

    Distinct d'une panne : aucun nouvel essai ne le réparera, il faut refaire
    autoriser le compte par son propriétaire. Les confondre ferait réessayer
    pour toujours un jeton que le fournisseur a révoqué.
    """


@dataclass(frozen=True)
class TokenSet:
    """Ce qu'un compte OAuth garde au coffre, en UNE chaîne.

    Le coffre ne transporte qu'une chaîne par référence : trois valeurs y
    demanderaient trois entrées, donc trois écritures à garder cohérentes.
    Une seule chaîne JSON tient dans l'entrée qui existe déjà.
    """

    refresh_token: str = ""
    access_token: str = ""
    expires_at: float = 0.0

    def to_json(self) -> str:
        return json.dumps(
            {
                "refresh_token": self.refresh_token,
                "access_token": self.access_token,
                "expires_at": self.expires_at,
            }
        )

    @classmethod
    def from_json(cls, brut) -> "TokenSet":
        """Lit ce que le coffre rend, y compris quand ce n'est pas du JSON.

        Ce qu'un utilisateur colle à la main est un jeton de rafraîchissement
        nu, obtenu ailleurs. Le refuser l'obligerait à fabriquer un objet
        JSON pour une valeur qu'il vient de copier.
        """
        if not brut:
            return cls()
        try:
            donnees = json.loads(brut)
        except (TypeError, ValueError):
            return cls(refresh_token=str(brut).strip())
        if not isinstance(donnees, dict):
            return cls(refresh_token=str(brut).strip())
        return cls(
            refresh_token=donnees.get("refresh_token", "") or "",
            access_token=donnees.get("access_token", "") or "",
            expires_at=float(donnees.get("expires_at") or 0.0),
        )

    def is_stale(self) -> bool:
        """Vrai s'il faut rafraîchir AVANT d'ouvrir une connexion."""
        if not self.access_token:
            return True
        return time.time() + MARGE_SECONDES >= self.expires_at


def _depuis_charge(corps: bytes, ancien: TokenSet) -> TokenSet:
    """La réponse du fournisseur → un jeu de jetons complet.

    Le jeton de rafraîchissement de l'ANCIEN jeu est conservé quand la
    réponse n'en porte pas : Google ne le renvoie pas à chaque échange, et
    l'écraser par du vide déconnecterait le compte au premier
    rafraîchissement réussi. Quand la réponse en porte un — Microsoft en
    renvoie un chaque fois — c'est le nouveau qui vaut, l'ancien cessant
    d'être accepté.
    """
    try:
        donnees = json.loads(corps.decode("utf-8", "replace"))
    except ValueError as exc:
        raise OAuthError(f"{t('mail_err_token_response_unreadable')} {exc}")
    if not isinstance(donnees, dict) or not donnees.get("access_token"):
        raise OAuthError(t("mail_err_token_response_no_token"))
    duree = donnees.get("expires_in")
    try:
        duree = float(duree) if duree is not None else 3600.0
    except (TypeError, ValueError):
        duree = 3600.0
    return TokenSet(
        refresh_token=donnees.get("refresh_token") or ancien.refresh_token,
        access_token=donnees["access_token"],
        expires_at=time.time() + duree,
    )


def _echanger(token_url: str, champs: dict, timeout: int) -> bytes:
    """POST du formulaire, et rend le corps. Traduit les pannes.

    Un 400 portant `invalid_grant` est le SEUL cas définitif : tout le reste
    — 5xx, socket coupée, DNS muet — se réessaie plus tard.
    """
    corps = urllib.parse.urlencode(champs).encode()
    requete = urllib.request.Request(
        token_url,
        data=corps,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as reponse:
            return reponse.read()
    except urllib.error.HTTPError as exc:
        detail = b""
        try:
            detail = exc.read()
        except Exception:
            pass
        if _est_revoque(detail):
            raise RefreshRefused(
                f"{t('mail_err_token_revoked')} {_message(detail)}"
            ) from exc
        raise OAuthError(
            f"{t('mail_err_token_endpoint_refused')} {exc.code}"
            f" {_message(detail)}"
        ) from exc
    except Exception as exc:
        # Socket coupée en plein corps, DNS muet, délai dépassé : le jeton en
        # place reste valable, donc l'appelant réessaiera.
        raise OAuthError(
            f"{t('mail_err_token_endpoint_unreachable')} {exc}"
        ) from exc


def _est_revoque(detail: bytes) -> bool:
    try:
        donnees = json.loads(detail.decode("utf-8", "replace"))
    except ValueError:
        return False
    return isinstance(donnees, dict) and donnees.get("error") in (
        "invalid_grant",
        "unauthorized_client",
    )


def _message(detail: bytes) -> str:
    """Le texte du fournisseur, ou rien — jamais une trace entière."""
    try:
        donnees = json.loads(detail.decode("utf-8", "replace"))
    except ValueError:
        return ""
    if not isinstance(donnees, dict):
        return ""
    return str(donnees.get("error_description") or donnees.get("error") or "")


def _verificateur() -> tuple:
    """(vérificateur, empreinte) de PKCE, en S256.

    Le vérificateur est tiré au hasard et ne quitte jamais la machine ;
    seule son empreinte part avec la demande d'autorisation. Un code
    intercepté ne suffit donc pas à obtenir un jeton : il faut aussi le
    vérificateur, que l'intercepteur n'a pas.
    """
    verificateur = secrets.token_urlsafe(64)
    empreinte = (
        base64.urlsafe_b64encode(
            hashlib.sha256(verificateur.encode("ascii")).digest()
        )
        .decode("ascii")
        .rstrip("=")
    )
    return verificateur, empreinte


def authorization_url(
    reglages: dict,
    *,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    login_hint: str = "",
    reclamer_hors_ligne: bool = False,
) -> str:
    """L'adresse de la page de consentement, paramètres compris.

    `reclamer_hors_ligne` demande explicitement un jeton de
    rafraîchissement : Google n'en rend pas sans `access_type=offline`, et
    n'en rend plus à qui a déjà consenti sans `prompt=consent` — le compte
    cesserait alors de fonctionner au bout d'une heure.
    """
    params = {
        "response_type": "code",
        "client_id": reglages["client_id"],
        "redirect_uri": redirect_uri,
        "scope": reglages["scope"],
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if login_hint:
        params["login_hint"] = login_hint
    if reclamer_hors_ligne:
        params["access_type"] = "offline"
        params["prompt"] = "consent"
    separateur = "&" if "?" in reglages["auth_url"] else "?"
    return reglages["auth_url"] + separateur + urllib.parse.urlencode(params)


class _RedirectionHandler(http.server.BaseHTTPRequestHandler):
    """Reçoit la redirection du fournisseur, et rien d'autre."""

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):  # noqa: N802 - nom imposé par http.server
        params = dict(
            urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query)
        )
        self.server.recu = params
        fini = params.get("code") and not params.get("error")
        corps = t("mail_oauth_page_ok") if fini else t("mail_oauth_page_ko")
        charge = (
            "<html><head><meta charset='utf-8'></head><body><p>"
            f"{corps}</p></body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(charge)))
        self.end_headers()
        self.wfile.write(charge)


def authorize(
    account,
    *,
    config_get=None,
    open_browser=None,
    timeout: int = 180,
) -> TokenSet:
    """Fait autoriser le compte, et rend le jeu de jetons obtenu.

    Le client écoute sur un port éphémère de la BOUCLE LOCALE — jamais sur
    toutes les interfaces, qui exposerait le code d'autorisation au réseau
    local le temps du parcours — ouvre la page de consentement, et attend
    UNE redirection.

    Trois refus avant l'échange : un état qui ne correspond pas à la
    demande (n'importe quelle page ouverte sur ce poste peut sinon faire
    échanger SON code), un refus de l'utilisateur, et le délai — personne
    ne doit attendre indéfiniment devant un navigateur fermé.

    La socket se referme dans tous les cas, y compris sur ces refus.
    """
    reglages = settings_for(account, config_get)
    if not reglages["client_id"]:
        # Avant d'ouvrir quoi que ce soit : une page qui affiche
        # « invalid_client » fait chercher la panne chez le fournisseur.
        raise OAuthError(t("mail_err_no_client_id"))

    verificateur, empreinte = _verificateur()
    etat = secrets.token_urlsafe(16)
    serveur = http.server.HTTPServer(("127.0.0.1", 0), _RedirectionHandler)
    serveur.recu = None
    serveur.timeout = timeout
    try:
        redirect_uri = f"http://127.0.0.1:{serveur.server_address[1]}/"
        url = authorization_url(
            reglages,
            redirect_uri=redirect_uri,
            state=etat,
            code_challenge=empreinte,
            login_hint=getattr(account, "email", ""),
            reclamer_hors_ligne=True,
        )
        (open_browser or webbrowser.open)(url)
        serveur.handle_request()
        recu = serveur.recu
    finally:
        serveur.server_close()

    if not recu:
        raise OAuthError(t("mail_err_authorization_timeout"))
    if recu.get("state") != etat:
        raise OAuthError(t("mail_err_authorization_state"))
    if recu.get("error"):
        raise OAuthError(
            f"{t('mail_err_authorization_refused')} {recu['error']}"
        )
    if not recu.get("code"):
        raise OAuthError(t("mail_err_authorization_no_code"))

    champs = {
        "grant_type": "authorization_code",
        "code": recu["code"],
        "redirect_uri": redirect_uri,
        "client_id": reglages["client_id"],
        "code_verifier": verificateur,
    }
    if reglages.get("client_secret"):
        champs["client_secret"] = reglages["client_secret"]
    return _depuis_charge(
        _echanger(reglages["token_url"], champs, DELAI_SECONDES), TokenSet()
    )


def settings_for(account, config_get=None) -> dict:
    """Les réglages OAuth d'un compte : points de service ET identité.

    Les points de service viennent du préréglage : ils sont publics et
    changent rarement. L'identité — `client_id`, et le secret quand le
    fournisseur en exige un — vient de CELUI QUI DÉPLOIE, parce que le dépôt
    n'en livre aucune : un identifiant embarqué engage un domaine, une
    politique de confidentialité et un quota partagés par tous ceux qui
    installent le logiciel.

    Trois sources, dans l'ordre : la configuration TODO
    (`mail.oauth.<préréglage>.client_id`), puis la variable d'environnement
    propre au préréglage, puis la variable générale. La configuration gagne :
    c'est celle que l'utilisateur a écrite exprès.
    """
    from script.todo.mail.accounts import PRESETS

    preset = PRESETS.get(account.preset, {})
    points = preset.get("oauth")
    if not points:
        raise OAuthError(
            f"{t('mail_err_provider_without_oauth')} {account.preset}"
        )

    def regle(nom: str) -> str:
        if config_get is not None:
            valeur = config_get(["mail", "oauth", account.preset, nom])
            if valeur:
                return str(valeur)
        propre = f"ERPLIBRE_MAIL_OAUTH_{nom.upper()}_{account.preset.upper()}"
        general = f"ERPLIBRE_MAIL_OAUTH_{nom.upper()}"
        return os.environ.get(propre) or os.environ.get(general) or ""

    reglages = dict(points)
    reglages["client_id"] = regle("client_id")
    reglages["client_secret"] = regle("client_secret")
    for nom in ("auth_url", "token_url", "scope"):
        # Un serveur d'entreprise peut porter ses propres points : la
        # configuration les remplace sans toucher au code.
        remplacement = regle(nom)
        if remplacement:
            reglages[nom] = remplacement
    return reglages


def secret_for(account, secrets, *, config_get=None, refresh_fn=None) -> str:
    """Le secret à présenter au serveur pour CE compte.

    Un seul point de décision : l'appelant passe ce qu'on lui rend à
    `connect()` sans avoir à savoir si c'est un mot de passe ou un jeton.

    Un jeton périmé se rafraîchit ici, et le jeu neuf est rangé au coffre
    AUSSITÔT : sans cette écriture, chaque ouverture de session rafraîchirait
    de nouveau, et le fournisseur compte ces échanges.
    """
    if getattr(account, "auth", "login") != "oauth":
        return secrets.get(account.secret_ref) or ""

    jeu = TokenSet.from_json(secrets.get(account.refresh_token_ref()))
    if not jeu.refresh_token:
        raise RefreshRefused(t("mail_err_no_refresh_token"))
    if not jeu.is_stale():
        return jeu.access_token

    reglages = settings_for(account, config_get)
    neuf = (refresh_fn or refresh)(
        jeu,
        token_url=reglages["token_url"],
        client_id=reglages["client_id"],
        client_secret=reglages.get("client_secret", ""),
    )
    secrets.set(account.refresh_token_ref(), neuf.to_json())
    return neuf.access_token


def refresh(
    tokens: TokenSet,
    *,
    token_url: str,
    client_id: str,
    client_secret: str = "",
    timeout: int = DELAI_SECONDES,
) -> TokenSet:
    """Échange le jeton de rafraîchissement contre un jeton d'accès neuf.

    Les deux refus qui se voient AVANT le réseau sortent avant d'ouvrir une
    socket : sans jeton il n'y a rien à échanger, et sans `client_id` le
    fournisseur répondrait « invalid_client », message qui n'apprend rien à
    qui n'a simplement pas encore configuré le sien.
    """
    if not tokens.refresh_token:
        raise RefreshRefused(t("mail_err_no_refresh_token"))
    if not client_id:
        raise OAuthError(t("mail_err_no_client_id"))
    champs = {
        "grant_type": "refresh_token",
        "refresh_token": tokens.refresh_token,
        "client_id": client_id,
    }
    # Un client installé n'a pas toujours de secret, et en envoyer un VIDE
    # fait refuser l'échange par certains fournisseurs.
    if client_secret:
        champs["client_secret"] = client_secret
    return _depuis_charge(_echanger(token_url, champs, timeout), tokens)
