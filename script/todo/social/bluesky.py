#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lire et publier sur un dépôt de données personnel.

Le second réseau du paquet, et trois choses l'éloignent du premier.

L'authentification est une SESSION, pas un jeton posé une fois pour toutes.
Un mot de passe d'application l'ouvre et rend deux jetons : un d'ACCÈS, court,
et un de RAFRAÎCHISSEMENT, durable. L'accès expire en cours de session — le
serveur le nomme — et c'est le second qui en obtient un neuf. Confondre ce
refus avec un mot de passe refusé ferait redemander un secret qui est bon.

La suite d'une page est un CURSEUR dans le corps de la réponse, là où l'autre
réseau l'écrit dans un en-tête. Le cache n'a pas à le savoir : il garde une
chaîne opaque et la rend telle quelle, ce qui lui permet de servir les deux.

Publier, enfin, n'est pas « poster un billet » mais ÉCRIRE UN ENREGISTREMENT
à une adresse qu'on choisit. Il n'y a donc pas de clé d'idempotence à
envoyer : c'est l'adresse qui tient ce rôle, réécrire la même remplaçant au
lieu d'ajouter. Le client choisit donc l'adresse et la garde, exactement
comme il garde une clé ailleurs.

Rien de ce module n'écrit dans le cache : il RAPPORTE, et l'appelant décide.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from script.todo.social.mastodon import (
    DELAI,
    INSTANT,
    SocialAuthError,
    SocialError,
    SocialRateLimited,
    SocialRefused,
    instant_de_reprise,
)
from script.todo.social.store import Media, PostMeta
from script.todo.todo_i18n import t

FIL_ACCUEIL = "home"

CHEMIN_SESSION = "/xrpc/com.atproto.server.createSession"
CHEMIN_REPRISE = "/xrpc/com.atproto.server.refreshSession"
CHEMIN_FIL = "/xrpc/app.bsky.feed.getTimeline"
CHEMIN_ECRIRE = "/xrpc/com.atproto.repo.putRecord"

COLLECTION = "app.bsky.feed.post"

# Ce que le service accepte par billet. La limite se compte en grappes de
# caractères et non en octets : un émoji en vaut une, pas quatre.
LIMITE_CARACTERES = 300

PAGE_MAX = 50

# Le nom que le serveur donne au jeton d'accès périmé. C'est LUI qui sépare
# « rafraîchis » de « redemande le mot de passe » ; sans ce partage, un
# client redemanderait son secret à chaque expiration, c'est-à-dire souvent.
ERREUR_EXPIRE = "ExpiredToken"


def _quand(valeur: str) -> int:
    """La date ISO 8601 en secondes depuis l'époque. Zéro si illisible —
    un billet mal daté se range mal, une page qui ne charge pas ne se lit
    pas du tout."""
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


def _rkey(uri: str) -> str:
    """La dernière partie d'une adresse d'enregistrement.

    C'est elle qui identifie le billet DANS son dépôt, et c'est ce qu'il
    faut renvoyer pour le réécrire.
    """
    return (uri or "").rsplit("/", 1)[-1]


# L'alphabet TRIÉ des adresses d'enregistrement : le service range un dépôt
# par adresse, donc l'ordre des caractères doit suivre l'ordre du temps. Ce
# n'est pas l'alphabet base32 courant, où « 2 » précède « a » — s'en servir
# produit des adresses qui remontent le temps une fois sur quinze.
ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"

# Le dernier identifiant rendu, pour qu'une horloge qui recule ou qui ne
# bouge pas entre deux appels n'en produise pas deux fois le même.
_dernier = 0


def nouvelle_adresse() -> str:
    """Une adresse d'enregistrement neuve, croissante dans le temps.

    Treize caractères de l'alphabet trié : les microsecondes depuis l'époque
    décalées de dix bits, et dix bits d'identifiant d'horloge pour que deux
    clients de la même personne ne se marchent pas dessus. Le bit de poids
    fort reste nul, donc le premier caractère tombe dans la première moitié
    de l'alphabet — le service refuse tout le reste.

    Croissante parce que le service range un dépôt par adresse : des
    adresses tirées au hasard y mêleraient les billets. L'appelant la GARDE
    d'un essai à l'autre — c'est elle qui rend une reprise sûre, et en tirer
    une neuve à chaque fois publierait deux fois.
    """
    import os

    global _dernier
    valeur = (int(time.time() * 1_000_000) << 10) | (
        int.from_bytes(os.urandom(2), "big") & 0x3FF
    )
    # Strictement croissant même si l'horloge recule ou stagne : deux appels
    # dans la même microseconde rendraient sinon la même adresse, donc le
    # second billet écraserait le premier.
    valeur = max(valeur, _dernier + 1)
    _dernier = valeur
    # 63 bits utiles, le bit de poids fort laissé à zéro.
    valeur &= (1 << 63) - 1
    sortie = []
    for _ in range(13):
        sortie.append(ALPHABET[valeur & 0x1F])
        valeur >>= 5
    return "".join(reversed(sortie))


def _fil_de(parent) -> dict:
    """Les deux références qu'une réponse doit porter.

    `parent` est le billet auquel on répond, tel que le cache le rend. La
    RACINE est la sienne s'il est lui-même une réponse, sinon lui-même : un
    fil n'a qu'une racine, et en nommer une autre le scinde en deux.

    Lève plutôt que de deviner : une référence incomplète est refusée par le
    service, et une adresse reconstruite de mémoire désignerait un autre
    billet — sous le dépôt de qui répond, et non de qui a écrit.
    """
    uri = getattr(parent, "uri", "")
    cid = getattr(parent, "cid", "")
    if not uri or not cid:
        raise SocialRefused(t("social_err_reply_needs_parent"))
    reference = {"uri": uri, "cid": cid}
    racine = (
        {"uri": parent.root_uri, "cid": parent.root_cid}
        if getattr(parent, "root_uri", "") and getattr(parent, "root_cid", "")
        else reference
    )
    return {"root": racine, "parent": reference}


def billet_depuis_entree(entree: dict) -> PostMeta:
    """Une entrée de fil en `PostMeta`.

    Ce qui dit qu'un billet est PARTAGÉ vit à côté de lui, non dedans :
    l'auteur reste celui qui a écrit, et le partage est noté à part.
    """
    poste = entree.get("post") or {}
    enregistrement = poste.get("record") or {}
    auteur = poste.get("author") or {}
    raison = entree.get("reason") or {}
    partage = "reasonRepost" in str(raison.get("$type", ""))
    fil = enregistrement.get("reply") or {}
    parent = fil.get("parent") or {}
    racine = fil.get("root") or {}
    incruste = poste.get("embed") or {}
    return PostMeta(
        post_id=_rkey(poste.get("uri") or ""),
        created_at=_quand(enregistrement.get("createdAt") or ""),
        author=str(auteur.get("handle") or ""),
        author_name=str(auteur.get("displayName") or ""),
        text=str(enregistrement.get("text") or ""),
        url=str(poste.get("uri") or ""),
        uri=str(poste.get("uri") or ""),
        # L'EMPREINTE à côté de l'adresse : répondre à ce billet exigera les
        # deux, et rien ne permet de la recalculer après coup.
        cid=str(poste.get("cid") or ""),
        # La racine du fil, gardée telle quelle : répondre à une réponse doit
        # nommer la MÊME racine, sinon le fil se scinde en deux.
        root_uri=str(racine.get("uri") or ""),
        root_cid=str(racine.get("cid") or ""),
        reply_to=_rkey(parent.get("uri") or "") if parent else "",
        boost_of=_rkey(poste.get("uri") or "") if partage else "",
        media=[
            Media(
                url=str(i.get("fullsize") or i.get("thumb") or ""),
                kind="image",
                description=str(i.get("alt") or ""),
            )
            for i in (incruste.get("images") or [])
            if isinstance(i, dict)
        ],
    )


class BlueskyTransport:
    """Le lien vers UN dépôt, pour UN compte.

    Porte une SESSION : ses deux jetons vivent ici, et le jeton d'accès y
    est remplacé quand il expire. C'est la seule pièce du paquet qui garde
    un état entre deux appels, et c'est le protocole qui l'impose.
    """

    def __init__(self, account, mot_de_passe: str, timeout: int = 30):
        self.account = account
        self.mot_de_passe = mot_de_passe
        self.timeout = timeout
        self.base_url = (account.base_url or "").rstrip("/")
        self.did = ""
        self._acces = ""
        self._reprise = ""

    # -- La session -----------------------------------------------------

    def ouvrir(self) -> dict:
        """Ouvre la session à partir du mot de passe d'application.

        Le mot de passe du COMPTE n'a rien à faire ici : un mot de passe
        d'application se révoque seul, sans changer celui du compte ni
        couper les autres clients.
        """
        donnees = self._appel(
            "POST",
            self.base_url + CHEMIN_SESSION,
            charge={
                "identifier": self.account.handle,
                "password": self.mot_de_passe,
            },
            authentifie=False,
        )
        self._garder(donnees)
        return {
            "handle": str(donnees.get("handle") or ""),
            "did": self.did,
        }

    def _garder(self, donnees) -> None:
        if not isinstance(donnees, dict) or not donnees.get("accessJwt"):
            raise SocialError(t("social_err_session_without_token"))
        self.did = str(donnees.get("did") or self.did)
        self._acces = str(donnees["accessJwt"])
        self._reprise = str(donnees.get("refreshJwt") or self._reprise)

    def _rafraichir(self) -> None:
        """Échange le jeton de rafraîchissement contre un accès neuf.

        C'est le jeton DURABLE qui se présente ici, pas celui qui vient
        d'expirer — les envoyer à l'envers fait refuser les deux.
        """
        if not self._reprise:
            raise SocialAuthError(t("social_err_no_refresh"))
        donnees = self._appel(
            "POST",
            self.base_url + CHEMIN_REPRISE,
            authentifie=False,
            entetes={"Authorization": f"Bearer {self._reprise}"},
        )
        self._garder(donnees)

    def _assurer_session(self) -> None:
        if not self._acces:
            self.ouvrir()

    # -- Les appels ------------------------------------------------------

    def _appel(
        self,
        methode: str,
        url: str,
        charge=None,
        authentifie: bool = True,
        entetes: dict | None = None,
    ):
        tete = {"Accept": "application/json"}
        if authentifie:
            tete["Authorization"] = f"Bearer {self._acces}"
        if charge is not None:
            tete["Content-Type"] = "application/json"
        tete.update(entetes or {})
        corps = json.dumps(charge).encode() if charge is not None else None
        requete = urllib.request.Request(
            url, data=corps, headers=tete, method=methode
        )
        try:
            with urllib.request.urlopen(
                requete, timeout=self.timeout
            ) as reponse:
                brut = reponse.read()
        except urllib.error.HTTPError as exc:
            self._lever(exc)
        except Exception as exc:
            raise SocialError(f"{t('social_err_unreachable')} {exc}") from exc
        try:
            return json.loads(brut.decode("utf-8", "replace"))
        except ValueError as exc:
            raise SocialError(t("social_err_answer_not_json")) from exc

    def _avec_session(self, action):
        """Exécute `action()`, avec UNE reprise si le jeton d'accès a expiré.

        Une seule : un rafraîchissement qui ne suffit pas signifie autre
        chose qu'un jeton périmé, et réessayer sans fin ferait tourner le
        client indéfiniment.
        """
        self._assurer_session()
        try:
            return action()
        except SocialRefused as exc:
            if ERREUR_EXPIRE not in str(exc):
                raise
        self._rafraichir()
        return action()

    def _lever(self, exc) -> None:
        detail, nom = "", ""
        try:
            brut = exc.read()
            charge = json.loads(brut.decode("utf-8", "replace"))
            if isinstance(charge, dict):
                nom = str(charge.get("error") or "")
                detail = f"{nom} {charge.get('message') or ''}".strip()
        except Exception:
            # Le corps d'une erreur est un bonus ; son absence ne doit pas
            # remplacer le code par une panne de lecture.
            pass
        finally:
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
                instant_de_reprise(
                    exc.headers,
                    (("RateLimit-Reset", INSTANT), ("Retry-After", DELAI)),
                ),
            ) from exc
        if 400 <= exc.code < 500:
            # Le jeton périmé passe PAR ICI : le serveur le range dans les
            # demandes invalides, et seul son nom le distingue d'un refus
            # que rien ne réparerait.
            raise SocialRefused(
                f"{t('social_err_refused')} {exc.code} {detail}"
            ) from exc
        raise SocialError(
            f"{t('social_err_refused')} {exc.code} {detail}"
        ) from exc

    # -- Ce que le client demande ---------------------------------------

    def verify(self) -> dict:
        """Le compte que le mot de passe ouvre."""
        return self.ouvrir()

    def nouvelle_cle(self) -> str:
        """Ici la clé EST l'adresse de l'enregistrement : réécrire la même
        remplace au lieu d'ajouter."""
        return nouvelle_adresse()

    def limite_caracteres(self) -> int:
        """La limite est celle du protocole, non d'un dépôt : il n'y a rien
        à demander au serveur."""
        return LIMITE_CARACTERES

    def home_timeline(self, cursor: str = "", limit: int = PAGE_MAX) -> tuple:
        """Une page du fil. Rend `(billets, curseur_suivant)`.

        Le curseur est celui du CORPS de la réponse précédente, opaque. Son
        absence est la façon dont le service dit « c'est tout ».
        """
        limite = max(1, min(int(limit), PAGE_MAX))

        def demander():
            params = {"limit": limite}
            if cursor:
                params["cursor"] = cursor
            return self._appel(
                "GET",
                f"{self.base_url}{CHEMIN_FIL}?"
                + urllib.parse.urlencode(params),
            )

        donnees = self._avec_session(demander)
        if not isinstance(donnees, dict):
            raise SocialError(t("social_err_answer_not_a_feed"))
        entrees = donnees.get("feed")
        if not isinstance(entrees, list):
            raise SocialError(t("social_err_answer_not_a_feed"))
        billets = [
            billet_depuis_entree(e) for e in entrees if isinstance(e, dict)
        ]
        return billets, str(donnees.get("cursor") or "")

    def publish(
        self,
        texte: str,
        *,
        cle: str = "",
        visibilite: str = "public",
        repond_a: str = "",
        avertissement: str = "",
        parent=None,
    ) -> PostMeta:
        """Écrit un billet. Rend celui que le dépôt porte désormais.

        `cle` est l'ADRESSE de l'enregistrement, et joue ici le rôle qu'une
        clé d'idempotence joue ailleurs : réécrire la même adresse remplace
        au lieu d'ajouter, donc rejouer un envoi dont la réponse s'est
        perdue ne publie pas deux fois. L'appelant la garde d'un essai à
        l'autre ; en tirer une neuve reviendrait à ne pas en avoir.

        `visibilite` est accepté pour que l'appelant n'ait pas à distinguer
        les réseaux, et IGNORÉ : ce protocole ne porte pas cette notion, et
        prétendre l'honorer laisserait croire à une confidentialité qui
        n'existe pas.

        `parent` est le billet auquel on répond, tel que le cache le rend,
        et il est EXIGÉ dès que `repond_a` l'est : une réponse nomme ici
        deux billets par référence forte — adresse et empreinte — et un
        identifiant seul ne suffit pas à les reconstituer. Les réseaux qui
        se contentent d'un identifiant l'ignorent.
        """
        if not texte.strip():
            raise SocialRefused(t("social_compose_empty"))
        if len(texte) > LIMITE_CARACTERES:
            raise SocialRefused(f"{t('social_compose_too_long')} {len(texte)}")
        adresse = cle or nouvelle_adresse()
        enregistrement = {
            "$type": COLLECTION,
            "text": texte,
            "createdAt": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        if repond_a:
            enregistrement["reply"] = _fil_de(parent)

        def ecrire():
            return self._appel(
                "POST",
                self.base_url + CHEMIN_ECRIRE,
                charge={
                    "repo": self.did,
                    "collection": COLLECTION,
                    "rkey": adresse,
                    "record": enregistrement,
                },
            )

        donnees = self._avec_session(ecrire)
        if not isinstance(donnees, dict) or not donnees.get("uri"):
            raise SocialError(t("social_err_answer_not_json"))
        return PostMeta(
            post_id=_rkey(str(donnees["uri"])),
            created_at=_quand(enregistrement["createdAt"]),
            author=self.account.handle,
            author_name=self.account.display_name or self.account.handle,
            text=texte,
            url=str(donnees["uri"]),
            uri=str(donnees["uri"]),
            reply_to=repond_a,
        )
