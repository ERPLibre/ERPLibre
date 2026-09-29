#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Publier sur un réseau professionnel, et ne pas prétendre y lire.

Le troisième réseau du paquet, et celui qui oblige à dire NON deux fois.

Non au fil. Récupérer celui d'un membre demande une autorisation accordée à
quelques développeurs choisis, et l'API de fil d'activité est dépréciée. Ce
transport ne tente donc rien : il refuse tout de suite, avec une phrase qui
dit pourquoi. Appeler pour se faire jeter par le serveur ferait passer une
limite connue pour une panne.

Non à la reprise automatique. Les deux autres réseaux offrent de quoi rejouer
un envoi sans publier deux fois — une clé d'idempotence ici, une adresse
d'enregistrement là. Celui-ci n'offre RIEN : deux demandes identiques font
deux publications. Quand la réponse se perd, le client ne peut donc pas
savoir, et il le DIT au lieu de réessayer. `SocialUnknownOutcome` existe pour
cela : ce n'est ni un refus — qu'on corrige — ni une panne — qu'on réessaie —
mais un doute, que seule la personne peut lever en allant regarder.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from script.todo.social.mastodon import (
    SocialAuthError,
    SocialError,
    SocialRateLimited,
    SocialRefused,
)
from script.todo.social.store import PostMeta
from script.todo.todo_i18n import t

CHEMIN_IDENTITE = "/v2/userinfo"
CHEMIN_PUBLIER = "/v2/ugcPosts"

# Ce que l'API accepte dans le commentaire d'un partage.
LIMITE_CARACTERES = 3000

# La version du protocole REST que l'API attend dans un en-tête. Sans elle,
# elle répond par une forme plus ancienne que ce module ne lit pas.
PROTOCOLE = "2.0.0"


class SocialUnknownOutcome(SocialError):
    """L'envoi est parti, et on ne sait pas s'il a abouti.

    Le cas propre aux services qui n'offrent aucun moyen de rejouer une
    demande sans la refaire. Réessayer publierait peut-être deux fois ;
    abandonner perdrait peut-être ce qui est passé. Le client ne tranche
    pas à la place de la personne : il dit ce qu'il sait, et ce qu'il ne
    sait pas.
    """


class LinkedInTransport:
    """Le lien vers l'API de partage, pour UN compte.

    Sans état : chaque appel porte son jeton. L'URN du membre est retenu
    après le premier appel qui le donne, parce que publier l'exige et qu'il
    ne change pas.
    """

    def __init__(self, account, token: str, timeout: int = 30):
        self.account = account
        self.token = token
        self.timeout = timeout
        self.base_url = (account.base_url or "").rstrip("/")
        self.urn = ""

    # -- Les appels ------------------------------------------------------

    def _appel(self, methode: str, url: str, charge=None) -> tuple:
        tete = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "X-Restli-Protocol-Version": PROTOCOLE,
        }
        corps = None
        if charge is not None:
            tete["Content-Type"] = "application/json"
            corps = json.dumps(charge).encode()
        requete = urllib.request.Request(
            url, data=corps, headers=tete, method=methode
        )
        try:
            with urllib.request.urlopen(
                requete, timeout=self.timeout
            ) as reponse:
                brut = reponse.read()
                entetes = dict(reponse.headers.items())
        except urllib.error.HTTPError as exc:
            self._lever(exc)
        except Exception as exc:
            # La réponse n'est jamais arrivée. Pour une LECTURE c'est une
            # panne ordinaire ; c'est l'appelant qui sait si sa demande
            # écrivait, et `publish` le traduit alors autrement.
            raise SocialError(f"{t('social_err_unreachable')} {exc}") from exc
        try:
            return json.loads(brut.decode("utf-8", "replace")), entetes
        except ValueError as exc:
            raise SocialError(t("social_err_answer_not_json")) from exc

    def _lever(self, exc) -> None:
        detail = ""
        try:
            charge = json.loads(exc.read().decode("utf-8", "replace"))
            if isinstance(charge, dict):
                detail = str(charge.get("message") or "")
        except Exception:
            pass
        finally:
            try:
                exc.close()
            except Exception:
                pass
        if exc.code in (401, 403):
            raise SocialAuthError(
                f"{t('social_err_token_refused')} {detail}"
            ) from exc
        if exc.code == 429:
            raise SocialRateLimited(
                f"{t('social_err_rate_limited')} {detail}",
                _reprise(exc.headers),
            ) from exc
        if 400 <= exc.code < 500:
            raise SocialRefused(
                f"{t('social_err_refused')} {exc.code} {detail}"
            ) from exc
        raise SocialError(
            f"{t('social_err_refused')} {exc.code} {detail}"
        ) from exc

    # -- Ce que le client demande ---------------------------------------

    def verify(self) -> dict:
        """Le membre que le jeton ouvre, et son URN, qu'il faut pour
        publier."""
        donnees, _ = self._appel("GET", self.base_url + CHEMIN_IDENTITE)
        if not isinstance(donnees, dict) or not donnees.get("sub"):
            raise SocialError(t("social_err_answer_not_json"))
        self.urn = f"urn:li:person:{donnees['sub']}"
        return {
            "acct": str(donnees.get("sub") or ""),
            "display_name": str(donnees.get("name") or ""),
            "urn": self.urn,
        }

    def limite_caracteres(self) -> int:
        """Celle de l'API, non d'un serveur : rien à demander."""
        return LIMITE_CARACTERES

    def home_timeline(self, cursor: str = "", limit: int = 0) -> tuple:
        """Refuse tout de suite, sans rien appeler.

        La lecture d'un fil de membre n'est pas en libre-service, et cela ne
        dépend ni du compte ni du jeton. Tenter l'appel ferait revenir un
        refus du serveur que l'écran montrerait comme une panne, là où c'est
        une limite connue d'avance.
        """
        raise SocialRefused(t("social_err_no_feed_here"))

    def publish(
        self,
        texte: str,
        *,
        cle: str = "",
        visibilite: str = "public",
        repond_a: str = "",
        avertissement: str = "",
    ) -> PostMeta:
        """Publie un partage. Rend celui que l'API a créé.

        `cle` est ACCEPTÉE et sans effet : ce service n'offre rien pour
        reconnaître une demande déjà reçue. La garder au dossier de la
        signature évite à l'appelant de distinguer les réseaux, mais elle ne
        promet rien ici, et le docstring le dit plutôt que de le taire.

        `repond_a` est refusé : répondre à un billet n'est pas un partage,
        et faire passer l'un pour l'autre publierait une réponse comme un
        message public.

        Une réponse perdue lève `SocialUnknownOutcome` : rejouer publierait
        peut-être deux fois, et rien ici ne permet de l'éviter.
        """
        if not texte.strip():
            raise SocialRefused(t("social_compose_empty"))
        if len(texte) > LIMITE_CARACTERES:
            raise SocialRefused(f"{t('social_compose_too_long')} {len(texte)}")
        if repond_a:
            raise SocialRefused(t("social_err_no_reply_here"))
        if not self.urn:
            self.verify()
        charge = {
            "author": self.urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": texte},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": (
                    "PUBLIC" if visibilite == "public" else "CONNECTIONS"
                )
            },
        }
        try:
            donnees, entetes = self._appel(
                "POST", self.base_url + CHEMIN_PUBLIER, charge=charge
            )
        except (SocialAuthError, SocialRateLimited, SocialRefused):
            # Le service a RÉPONDU non : rien n'est parti, et l'appelant
            # peut corriger puis recommencer sans risque.
            raise
        except SocialError as exc:
            # Le service n'a pas répondu, ou a répondu 5xx après avoir
            # peut-être enregistré. Personne ne peut trancher d'ici.
            raise SocialUnknownOutcome(
                f"{t('social_err_unknown_outcome')} {exc}"
            ) from exc
        urn = str(
            (donnees or {}).get("id") or entetes.get("x-restli-id") or ""
        )
        return PostMeta(
            post_id=urn,
            created_at=0,
            author=self.account.handle,
            author_name=self.account.display_name or self.account.handle,
            text=texte,
            url=urn,
            uri=urn,
        )


def _reprise(entetes) -> float | None:
    valeur = entetes.get("Retry-After") if entetes else None
    try:
        return float(valeur) if valeur is not None else None
    except (TypeError, ValueError):
        return None
