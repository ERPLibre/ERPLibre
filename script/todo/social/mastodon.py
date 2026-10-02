#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lire un fil chez une instance de microblogue fédéré.

Trois choses que l'API impose et qu'un client se trompe facilement à faire
autrement :

Le TEXTE d'un billet arrive en HTML. L'instance y met des paragraphes, des
sauts de ligne, des liens et des images d'émojis ; le rendre tel quel
afficherait des balises, et retirer les balises sans rétablir les entités
afficherait « &amp; » au milieu des mots.

La SUITE d'une page est annoncée dans un en-tête `Link`, pas dans le corps.
Reprendre plutôt à l'identifiant du dernier billet reçu paraît marcher et
saute des billets dès qu'un trou apparaît — un billet retiré entre deux
demandes suffit. Le curseur est donc gardé tel que l'instance l'a écrit.

Un PARTAGE enveloppe le billet d'autrui : le sien est vide, et le contenu à
lire est celui qu'il enveloppe. Lire le contenu du partage rend une ligne
blanche là où il y a un message.

Rien de ce module n'écrit dans le cache : il RAPPORTE, et c'est l'appelant
qui décide ce qu'il en garde.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from script.todo.social.store import Media, PostMeta
from script.todo.todo_i18n import t

# Le fil personnel. Le nom que porte le fil dans le cache, et le chemin que
# l'instance lui donne.
FIL_ACCUEIL = "home"
CHEMIN_ACCUEIL = "/api/v1/timelines/home"
CHEMIN_IDENTITE = "/api/v1/accounts/verify_credentials"
CHEMIN_PUBLIER = "/api/v1/statuses"
CHEMIN_INSTANCE = "/api/v1/instance"

# Ce qu'une instance accepte par défaut. DEMANDÉE plutôt que supposée : une
# instance relève ou abaisse cette limite, et un client qui la suppose fait
# refuser un billet sans pouvoir dire pourquoi.
LIMITE_PAR_DEFAUT = 500

# Qui voit le billet. `public` le met dans les fils publics ; `unlisted` le
# garde hors d'eux ; `private` le réserve aux abonnés ; `direct` aux seules
# personnes citées.
VISIBILITES = ("public", "unlisted", "private", "direct")

# Au-delà, l'instance rend ce qu'elle veut : 40 est le plafond documenté.
PAGE_MAX = 40

_LIEN = re.compile(r'<([^>]+)>;\s*rel="([^"]+)"')
_BLOCS = re.compile(r"(?i)</p\s*>|<br\s*/?>")
_BALISE = re.compile(r"<[^>]+>")


class SocialError(Exception):
    """L'instance n'a pas rendu ce qu'on lui demandait. Se réessaie."""


class SocialAuthError(SocialError):
    """Le jeton est refusé.

    À distinguer de tout le reste : aucun nouvel essai ne le répare, il faut
    refaire autoriser le compte. Les confondre ferait redemander un jeton
    valide à chaque hoquet du réseau.
    """


class SocialRefused(SocialError):
    """L'instance a répondu NON, et le répéter n'y changera rien.

    Un billet vide, un billet trop long, une visibilité qu'elle ne connaît
    pas : la demande est en cause, pas le réseau. À distinguer d'une panne,
    qui se réessaie — les confondre fait boucler sur un refus définitif.
    """


class SocialRateLimited(SocialError):
    """L'instance demande d'attendre.

    `reprise` porte la seconde à partir de laquelle redemander, quand
    l'instance la donne. Réessayer avant allonge la coupure au lieu de
    l'abréger.
    """

    def __init__(self, message: str, reprise: float | None = None):
        super().__init__(message)
        self.reprise = reprise


def texte_depuis_html(fragment: str) -> str:
    """Le texte lisible d'un contenu HTML de billet.

    Les fins de paragraphe et les `<br>` deviennent des sauts de ligne — les
    perdre collerait en un bloc un billet qui en comptait trois. Le reste
    des balises part, et les entités sont rétablies EN DERNIER : les
    rétablir avant ferait passer un « &lt;b&gt; » écrit par l'auteur pour
    une balise, et disparaître son texte.
    """
    if not fragment:
        return ""
    avec_sauts = _BLOCS.sub("\n", fragment)
    nu = _BALISE.sub("", avec_sauts)
    return html.unescape(nu).strip()


def _quand(valeur: str) -> int:
    """La date ISO 8601 de l'instance en secondes depuis l'époque.

    Une date illisible rend 0 plutôt que de faire échouer la page : un
    billet mal daté se range mal, un fil qui ne se charge pas ne se lit
    pas du tout.
    """
    if not valeur:
        return 0
    try:
        return int(
            datetime.fromisoformat(valeur.replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .timestamp()
        )
    except ValueError:
        return 0


def _suivant(lien: str) -> str:
    """L'URL de la page suivante, tirée de l'en-tête `Link`. Vide s'il n'y
    en a pas — ce qui est la façon dont l'instance dit « c'est tout »."""
    for url, relation in _LIEN.findall(lien or ""):
        if relation == "next":
            return url
    return ""


def billet_depuis_statut(brut: dict) -> PostMeta:
    """Un billet de l'API en `PostMeta`.

    Le `boost_of` porte l'identifiant du billet enveloppé, et le texte lu
    est le SIEN : celui d'un partage est vide.
    """
    partage = brut.get("reblog") or None
    source = partage if isinstance(partage, dict) else brut
    compte = brut.get("account") or {}
    return PostMeta(
        post_id=str(brut.get("id") or ""),
        created_at=_quand(brut.get("created_at") or ""),
        author=str(compte.get("acct") or ""),
        author_name=str(compte.get("display_name") or ""),
        text=texte_depuis_html(source.get("content") or ""),
        url=str(source.get("url") or ""),
        uri=str(source.get("uri") or ""),
        reply_to=str(brut.get("in_reply_to_id") or ""),
        boost_of=str(source.get("id") or "") if partage else "",
        media=[
            Media(
                url=str(p.get("url") or ""),
                kind=str(p.get("type") or ""),
                description=str(p.get("description") or ""),
            )
            for p in (source.get("media_attachments") or [])
            if isinstance(p, dict)
        ],
    )


class MastodonTransport:
    """Le lien vers UNE instance, pour UN compte.

    Sans état : chaque appel porte son jeton, et rien n'est gardé ouvert. Il
    n'y a pas de session à rouvrir comme en IMAP — une requête refusée se
    rejoue telle quelle.
    """

    def __init__(self, account, token: str, timeout: int = 30):
        self.account = account
        self.token = token
        self.timeout = timeout
        self.base_url = (account.base_url or "").rstrip("/")

    # -- Requêtes -------------------------------------------------------

    def _get(self, url: str) -> tuple:
        """GET authentifié. Rend `(donnees, entetes)`.

        Traduit les pannes en trois classes, parce que trois conduites
        s'ensuivent : un jeton refusé se redemande à son propriétaire, une
        limite de débit s'attend, et tout le reste se réessaie.
        """
        requete = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(
                requete, timeout=self.timeout
            ) as reponse:
                corps = reponse.read()
                # RENDUS TELS QUELS. Un `HTTPMessage` cherche sans égard à
                # la casse, ce que `dict(...)` détruit : l'instance écrit
                # `link` en minuscules — son cadre replie tout nom
                # d'en-tête — et un `get("Link")` sur un dict ordinaire n'y
                # trouve rien. La page suivante n'était alors jamais
                # annoncée, ce qui se lit comme une fin de fil.
                entetes = reponse.headers
        except urllib.error.HTTPError as exc:
            self._lever(exc)
        except Exception as exc:
            # Socket coupée, DNS muet, délai dépassé : le jeton reste bon,
            # donc l'appelant réessaiera.
            raise SocialError(f"{t('social_err_unreachable')} {exc}") from exc
        try:
            return json.loads(corps.decode("utf-8", "replace")), entetes
        except ValueError as exc:
            # Une passerelle qui intercale sa page d'erreur sous un code de
            # succès : le dire, plutôt que de planter sur le décodage.
            raise SocialError(t("social_err_answer_not_json")) from exc

    def _lever(self, exc) -> None:
        detail = ""
        try:
            detail = _message(exc.read())
        except Exception:
            # Le corps d'une erreur est un bonus : son absence ne doit pas
            # remplacer le code par une panne de lecture.
            pass
        finally:
            # `HTTPError` est un flux ouvert : sans cette fermeture, la
            # socket ne part qu'au ramasse-miettes, et une boucle qui
            # essuie des refus en tient autant d'ouvertes en même temps.
            try:
                exc.close()
            except Exception:
                pass
        if exc.code == 401:
            raise SocialAuthError(
                f"{t('social_err_token_refused')} {detail}"
            ) from exc
        if exc.code == 429:
            raise SocialRateLimited(
                f"{t('social_err_rate_limited')} {detail}",
                _reprise(exc.headers),
            ) from exc
        if 400 <= exc.code < 500:
            # L'instance a compris et refusé : la demande est en cause, pas
            # le réseau. Réessayer la même chose boucle sur le même non.
            raise SocialRefused(
                f"{t('social_err_refused')} {exc.code} {detail}"
            ) from exc
        raise SocialError(
            f"{t('social_err_refused')} {exc.code} {detail}"
        ) from exc

    # -- Ce que le client demande ---------------------------------------

    def verify(self) -> dict:
        """Le compte que le jeton ouvre. Sert à vérifier un compte neuf."""
        donnees, _ = self._get(self.base_url + CHEMIN_IDENTITE)
        if not isinstance(donnees, dict):
            raise SocialError(t("social_err_answer_not_json"))
        return {
            "acct": str(donnees.get("acct") or ""),
            "display_name": str(donnees.get("display_name") or ""),
            "url": str(donnees.get("url") or ""),
        }

    def _post(self, url: str, champs: dict, entetes: dict) -> tuple:
        """POST d'un formulaire. Rend `(donnees, entetes)`, comme `_get`."""
        corps = urllib.parse.urlencode(
            {k: v for k, v in champs.items() if v not in (None, "")}
        ).encode()
        tete = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        tete.update(entetes)
        requete = urllib.request.Request(
            url, data=corps, headers=tete, method="POST"
        )
        try:
            with urllib.request.urlopen(
                requete, timeout=self.timeout
            ) as reponse:
                brut = reponse.read()
                # Tels quels, pour la même raison que dans `_get`.
                recus = reponse.headers
        except urllib.error.HTTPError as exc:
            self._lever(exc)
        except Exception as exc:
            raise SocialError(f"{t('social_err_unreachable')} {exc}") from exc
        try:
            return json.loads(brut.decode("utf-8", "replace")), recus
        except ValueError as exc:
            raise SocialError(t("social_err_answer_not_json")) from exc

    def limite_caracteres(self) -> int:
        """La longueur maximale d'un billet, telle que l'instance l'annonce.

        Une instance relève ou abaisse cette limite. La demander évite de
        faire refuser un billet par le serveur sans savoir le dire d'avance
        à qui l'écrit ; une réponse qui ne la porte pas retombe sur la
        valeur du logiciel plutôt que d'empêcher de publier.
        """
        try:
            donnees, _ = self._get(self.base_url + CHEMIN_INSTANCE)
            valeur = (
                (donnees or {})
                .get("configuration", {})
                .get("statuses", {})
                .get("max_characters")
            )
            return int(valeur) if valeur else LIMITE_PAR_DEFAUT
        except (SocialError, AttributeError, TypeError, ValueError):
            return LIMITE_PAR_DEFAUT

    def publish(
        self,
        texte: str,
        *,
        cle: str = "",
        visibilite: str = "public",
        repond_a: str = "",
        avertissement: str = "",
    ) -> PostMeta:
        """Publie un billet. Rend celui que l'instance a créé.

        `cle` est la CLÉ D'IDEMPOTENCE, et c'est elle qui rend une reprise
        sûre : quand la réponse se perd — délai dépassé, socket coupée — le
        billet peut être posé sans que l'appelant l'apprenne. Rejouer la
        demande avec la MÊME clé rend le billet déjà créé au lieu d'en
        poser un second. Une clé neuve à chaque essai reviendrait à ne pas
        en avoir ; c'est pourquoi l'appelant la garde et la repasse.

        Un refus de l'instance — billet vide, trop long, visibilité
        inconnue — lève `SocialRefused` : le répéter n'y changera rien.
        """
        if visibilite not in VISIBILITES:
            raise SocialRefused(
                f"{t('social_err_unknown_visibility')} {visibilite!r}"
            )
        donnees, _ = self._post(
            self.base_url + CHEMIN_PUBLIER,
            {
                "status": texte,
                "visibility": visibilite,
                "in_reply_to_id": repond_a,
                "spoiler_text": avertissement,
            },
            {"Idempotency-Key": cle or _cle_idempotence()},
        )
        if not isinstance(donnees, dict):
            raise SocialError(t("social_err_answer_not_json"))
        return billet_depuis_statut(donnees)

    def home_timeline(self, cursor: str = "", limit: int = PAGE_MAX) -> tuple:
        """Une page du fil personnel. Rend `(billets, curseur_suivant)`.

        `cursor` est ce que l'appel PRÉCÉDENT a rendu, opaque : c'est l'URL
        complète que l'instance a écrite dans son en-tête `Link`. Vide, la
        page part du plus récent.

        Le curseur suivant est vide quand l'instance n'annonce plus de
        suite — c'est ainsi qu'elle dit « c'est tout », et le seul signal
        d'arrêt qui ne suppose rien sur le nombre de billets rendus.
        """
        if cursor:
            url = cursor
        else:
            limite = max(1, min(int(limit), PAGE_MAX))
            url = f"{self.base_url}{CHEMIN_ACCUEIL}?" + urllib.parse.urlencode(
                {"limit": limite}
            )
        donnees, entetes = self._get(url)
        if not isinstance(donnees, list):
            raise SocialError(t("social_err_answer_not_a_feed"))
        billets = [
            billet_depuis_statut(b) for b in donnees if isinstance(b, dict)
        ]
        return billets, _suivant(entetes.get("Link", ""))


def _cle_idempotence() -> str:
    """Une clé neuve, propre à une tentative de publication.

    C'est l'appelant qui la garde d'un essai à l'autre : elle n'a de sens
    que réutilisée, et en tirer une nouvelle à chaque reprise reviendrait à
    ne pas en avoir.
    """
    import uuid

    return uuid.uuid4().hex


def _message(detail: bytes) -> str:
    """Le message d'erreur de l'instance, quand elle en donne un."""
    try:
        donnees = json.loads(detail.decode("utf-8", "replace"))
    except ValueError:
        return ""
    if isinstance(donnees, dict):
        return str(donnees.get("error") or "")
    return ""


def _reprise(entetes) -> float | None:
    """La seconde à partir de laquelle redemander, si l'instance la dit."""
    for nom in ("X-RateLimit-Reset", "Retry-After"):
        valeur = entetes.get(nom) if entetes else None
        if valeur is None:
            continue
        try:
            return float(valeur)
        except (TypeError, ValueError):
            # Certaines instances y écrivent une date plutôt qu'un nombre :
            # ne pas la comprendre vaut mieux que d'inventer un délai.
            continue
    return None
