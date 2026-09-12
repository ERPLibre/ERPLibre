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

import json
import os
import time
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
