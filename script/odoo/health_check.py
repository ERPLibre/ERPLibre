#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Vérifier qu'une instance Odoo répond, et qu'elle n'expose rien de trop.

Les cibles
----------
- `--url URL` (répétable) : la sonde passe par le proxy inverse, comme un
  navigateur. Un hôte nu devient `https://hote` ; seuls `http` et `https`
  sont admis, et une URL qui porte un identifiant (`compte:mdp@`) est
  refusée — l'outil n'en envoie jamais.
- `--local` : l'unité systemd détectée comme le fait `update_module.py`
  (ou `--service`), jointe là où Odoo écoute (`http://127.0.0.1:<port>`),
  avec `?db=` quand la base est connue. La configuration de l'unité donne
  aussi `list_db`.

Les vérifications
-----------------
Chacune rend OK, ATTN, FAIL ou SKIP, avec un conseil d'une ligne :

1. `http_login` : GET /web/login, trois redirections au plus sur le même
   hôte ; le statut et la durée.
2. `web_health` : /web/health?db_server_status=1. Une route absente (404)
   est un SKIP : la décision suit la réponse, pas une table de versions.
3. `tls_certificate` (https) : chaîne et nom vérifiés par le contexte par
   défaut de `ssl`, jours avant l'expiration (ATTN sous 21, FAIL sous 7).
4. `http_redirect` (https) : `http://hote/` doit rediriger vers https.
5. `hsts` (https) : l'en-tête Strict-Transport-Security, lu sur la réponse
   200 de /web/login — nginx n'envoie pas un `add_header` sans `always`
   sur une erreur.
6. `db_manager`, `db_selector` : /web/database/manager et /selector. Le
   corps est lu, pas seulement le statut : avec `list_db = False`, Odoo 18
   répond 200 avec la page « disabled ». `list_db` (local) : la valeur de
   la configuration.
7. `websocket` (URL) : le chemin du bus (/websocket dès 16, sinon
   /longpolling/poll) doit être relayé par le proxy — tout sauf 404 et
   502/503/504. Pas de poignée de main : un GET simple suffit.
8. `robots` (URL) : ATTN au plus, quand robots.txt interdit tout alors
   qu'il nomme un sitemap (site web public).
9. `mail_spf`, `mail_dmarc`, `mail_dkim`, avec `--mail-domain` (et
   `--dkim-selector`) : les enregistrements TXT, lus par `dig` ou `host` —
   la bibliothèque standard n'a pas de résolveur. Sans l'un ni l'autre,
   SKIP. Une recherche en échec est un SKIP, jamais « enregistrement
   absent ».

La version d'Odoo vient de /web/webclient/version_info (JSON-RPC sans
authentification) ; inconnue, les vérifications qui en dépendent sondent.

Ce que la sonde ne fait pas
---------------------------
Lecture seule : des GET, et un POST JSON-RPC sans identifiant pour la
version. Aucun cookie gardé ni envoyé, aucun en-tête Authorization ; les
variables de proxy de l'environnement sont ignorées ; les corps sont lus
jusqu'à 1 Mio. Chaque requête, connexion TLS et recherche DNS a son délai
(`--timeout`). Aucun service web tiers n'est contacté, rien n'est écrit.

Le certificat n'est jugé que par `tls_certificate` : les autres requêtes
HTTPS ne le vérifient pas, pour qu'un certificat refusé donne un FAIL et
laisse les autres vérifications répondre.

Sortie : une ligne par vérification, puis `OK n · ATTN n · FAIL n · SKIP
n`. `--json` rend des clés stables, en anglais, jamais traduites.

Codes de sortie : 0 aucun FAIL (les ATTN sont listés) ; 1 au moins un
FAIL ; 2 la vérification n'a pas pu se faire (usage, détection,
configuration illisible : conseil sudo) ; 130 interrompu.

Bibliothèque standard seulement, sans syntaxe postérieure à Python 3.7 :
le programme se lance aussi par le python3 d'un serveur de production.
"""

from __future__ import annotations

import argparse
import calendar
import datetime
import http.client
import json
import os
import re
import shutil
import socket
import ssl
import sys
import time
import types
import urllib.error
import urllib.parse
import urllib.request

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.lib_ops import odoo_instance, report, service  # noqa: E402

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

CODE_OK = 0
CODE_FAIL = 1
CODE_REFUS = 2
CODE_INTERROMPU = 130

OK = "OK"
ATTN = "ATTN"
FAIL = "FAIL"
SKIP = "SKIP"
STATUTS = (OK, ATTN, FAIL, SKIP)

DELAI_PAR_DEFAUT = 10.0
CORPS_MAX = 1024 * 1024
REDIRECTIONS_MAX = 3
# Au-delà, /web/login est « lent » : une première requête après un
# démarrage, qui charge le registre, dépasse ce seuil.
LENTEUR = 5.0
JOURS_ATTN = 21
JOURS_FAIL = 7
# max-age HSTS en deçà duquel l'en-tête ne protège presque rien.
HSTS_MIN = 86400
AGENT = "ERPLibre-health-check"

# Un nom DNS (domaine ou sélecteur DKIM) : jamais de « - » en tête, qui
# ferait d'un argument de dig ou host une option.
RE_DOMAINE = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?")
RE_HOST_TXT = re.compile(r"descriptive text (.+)$")
RE_GUILLEMETS = re.compile(r'"((?:[^"\\]|\\.)*)"')
# Le statut de l'en-tête d'une réponse de dig (`+comments`) ; seuls
# NOERROR et NXDOMAIN sont des réponses définitives sur l'existence d'un
# enregistrement.
RE_DIG_STATUT = re.compile(r"->>HEADER<<-.*?\bstatus:\s*([A-Z]+)")
DIG_DEFINITIFS = ("NOERROR", "NXDOMAIN")
# Les dates d'un certificat DER : UTCTime (0x17, 13 octets) ou
# GeneralizedTime (0x18, 15 octets).
RE_TEMPS_DER = re.compile(rb"\x17\x0d(\d{12}Z)|\x18\x0f(\d{14}Z)")

# Ce qu'Odoo écrit dans la page du gestionnaire de bases (gabarit
# database_manager) : désactivé par `list_db = False`, mot de passe
# maître absent ou resté `admin`, et les marques du formulaire.
GESTIONNAIRE_DESACTIVE = (
    "The database manager has been disabled by the administrator"
)
GESTIONNAIRE_NON_PROTEGE = "database manager is not protected"
MARQUES_GESTIONNAIRE = (
    "o_database_list",
    'name="master_pwd"',
    "/web/database/backup",
)

# Codes de vérification d'OpenSSL (X509_V_ERR_*) nommés par le message.
TLS_NOM = 62
TLS_EXPIRE = 10
TLS_AUTOSIGNE = (18, 19)
TLS_EMETTEUR = (20, 21)

N_ = service.N_
Refus = service.Refus


class Resultat:
    """Le verdict d'une vérification.

    `ident` est stable (anglais, clé de `--json`) ; `statut` est l'un de
    STATUTS. Le message et le conseil sont des MODÈLES anglais avec leurs
    valeurs : `message(t)` et `conseil(t)` les rendent traduits, `json()`
    en anglais. `donnees` (dict) porte les valeurs brutes ; `cible`,
    l'URL ou le domaine vérifié.
    """

    def __init__(
        self, ident, statut, modele, valeurs=None, conseil="", donnees=None
    ):
        self.ident = ident
        self.statut = statut
        self.modele = modele
        self.valeurs = dict(valeurs or {})
        self.modele_conseil = conseil
        self.donnees = dict(donnees or {})
        self.cible = ""

    def _former(self, modele, t):
        if not modele:
            return ""
        texte = t(modele) if t else modele
        try:
            return texte.format(**self.valeurs)
        except (KeyError, IndexError, ValueError):
            # Une traduction qui nomme une valeur absente rend le modèle
            # brut plutôt que de faire tomber le rapport.
            return texte

    def message(self, t=None):
        return self._former(self.modele, t)

    def conseil(self, t=None):
        return self._former(self.modele_conseil, t)

    def json(self):
        return {
            "id": self.ident,
            "target": self.cible,
            "status": self.statut,
            "message": self.message(),
            "hint": self.conseil(),
            "data": self.donnees,
        }


class Reponse:
    """Une réponse HTTP : `statut` (0 sans réponse : refus, délai, TLS —
    `erreur` dit lequel), `entetes` aux noms en minuscules, `corps` lu
    jusqu'à CORPS_MAX et décodé en UTF-8."""

    def __init__(self, statut=0, entetes=None, corps="", erreur=""):
        self.statut = statut
        self.entetes = dict(entetes or {})
        self.corps = corps
        self.erreur = erreur

    def entete(self, nom):
        return self.entetes.get(nom.lower(), "")


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    """Une redirection est rendue telle quelle (statut 3xx et Location) :
    l'appelant décide s'il la suit."""

    def redirect_request(self, *args, **kwargs):
        return None


def _lire(reponse):
    return reponse.read(CORPS_MAX).decode("utf-8", "replace")


def _entetes(message):
    return {cle.lower(): valeur for cle, valeur in message.items()}


def ouvrir_http(url, delai, donnees=None, entetes=None):
    """Une requête (GET, ou POST quand `donnees` est donné) : Reponse.

    Ni proxy de l'environnement, ni cookie, ni redirection suivie, ni
    vérification du certificat (voir l'en-tête). Ne lève pas.
    """
    contexte = ssl.create_default_context()
    contexte.check_hostname = False
    contexte.verify_mode = ssl.CERT_NONE
    ouvreur = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _SansRedirection(),
        urllib.request.HTTPSHandler(context=contexte),
    )
    tete = {"User-Agent": AGENT, "Accept-Encoding": "identity"}
    tete.update(entetes or {})
    requete = urllib.request.Request(url, data=donnees, headers=tete)
    try:
        with ouvreur.open(requete, timeout=delai) as reponse:
            return Reponse(
                reponse.getcode(), _entetes(reponse.headers), _lire(reponse)
            )
    except urllib.error.HTTPError as err:
        try:
            corps = _lire(err)
        except (OSError, http.client.HTTPException):
            corps = ""
        return Reponse(err.code, _entetes(err.headers or {}), corps)
    except (OSError, http.client.HTTPException, ValueError) as err:
        raison = getattr(err, "reason", None) or err
        return Reponse(0, erreur=str(raison) or type(raison).__name__)


class Systeme(service.SystemeBase):
    """Les effets de bord : HTTP (`ouvrir`), TLS (`certificat`,
    `certificat_brut`), binaires (`quel`), commandes (`lanceur`, hérité :
    127 pour un binaire absent, 124 pour un délai), horloges. Un test en
    dérive une classe et rien de réel n'est contacté."""

    def ouvrir(self, url, delai, donnees=None, entetes=None):
        return ouvrir_http(url, delai, donnees, entetes)

    def horloge(self):
        return time.monotonic()

    def quel(self, nom):
        return shutil.which(nom)

    def certificat(self, hote, port, delai):
        """Le certificat présenté pour `hote` (SNI), chaîne et nom vérifiés :
        dict de `getpeercert()`. Lève ssl.SSLCertVerificationError sur un
        refus, OSError sur une connexion impossible."""
        contexte = ssl.create_default_context()
        with socket.create_connection((hote, port), timeout=delai) as brut:
            with contexte.wrap_socket(brut, server_hostname=hote) as tls:
                return tls.getpeercert()

    def certificat_brut(self, hote, port, delai):
        """Le certificat en DER, sans vérification : lu seulement pour dater
        un certificat refusé."""
        contexte = ssl.create_default_context()
        contexte.check_hostname = False
        contexte.verify_mode = ssl.CERT_NONE
        with socket.create_connection((hote, port), timeout=delai) as brut:
            with contexte.wrap_socket(brut, server_hostname=hote) as tls:
                return tls.getpeercert(binary_form=True)


# --- Cibles ----------------------------------------------------------------


def _netloc(hote, port, schema):
    """`hote[:port]` pour une URL : crochets autour d'une IPv6, port omis
    quand c'est celui du schéma."""
    texte = f"[{hote}]" if ":" in hote else hote
    defaut = 443 if schema == "https" else 80
    return texte if port == defaut else f"{texte}:{port}"


def normaliser_url(texte):
    """La cible d'une URL donnée : namespace (`kind`, `url` sans chemin,
    `schema`, `hote`, `port`, `base`, `list_db`). Un hôte nu devient
    https. ValueError (modèle anglais) : schéma autre que http(s), hôte
    vide ou invalide, identifiant dans l'URL."""
    texte = (texte or "").strip()
    if not texte:
        raise ValueError(N_("empty URL"))
    if "://" not in texte:
        texte = "https://" + texte
    morceaux = urllib.parse.urlsplit(texte)
    schema = morceaux.scheme.lower()
    if schema not in ("http", "https"):
        raise ValueError(N_("only http:// and https:// URLs are accepted"))
    if "@" in morceaux.netloc:
        raise ValueError(N_("no credentials in the URL: none is ever sent"))
    try:
        hote = morceaux.hostname or ""
        port = morceaux.port or (443 if schema == "https" else 80)
    except ValueError:
        raise ValueError(N_("invalid port in the URL"))
    if not hote or any(c.isspace() for c in hote):
        raise ValueError(N_("no host in the URL"))
    return types.SimpleNamespace(
        kind="url",
        url=f"{schema}://{_netloc(hote, port, schema)}",
        schema=schema,
        hote=hote,
        port=port,
        base=None,
        list_db=None,
        unite="",
        version=None,
    )


def cible_locale(hote, port, base=None, list_db=None, unite=""):
    """La cible d'une instance locale, jointe en http sur `hote:port`."""
    return types.SimpleNamespace(
        kind="local",
        url=f"http://{_netloc(hote, port, 'http')}",
        schema="http",
        hote=hote,
        port=port,
        base=base,
        list_db=list_db,
        unite=unite,
        version=None,
    )


def detecter_locale(explicite, systeme):
    """La cible de l'unité `explicite` ou détectée : adresse, base et
    `list_db` lus dans sa configuration. Refus sur ce qui manque, dont une
    configuration illisible (conseil sudo)."""
    plan = types.SimpleNamespace()
    props = service.detecter_unite(explicite, systeme, RACINE, plan)
    service.detecter_compte_et_dossier(None, systeme, plan, props)
    config = service.detecter_config(None, plan)
    hote, port = odoo_instance.adresse_http(plan.execstart, config)
    base, _origine = odoo_instance.trouver_base(None, plan.execstart, config)
    return cible_locale(hote, port, base, config.get("list_db"), plan.unite)


def version_odoo(cible, systeme, delai):
    """La version majeure d'Odoo, lue par /web/webclient/version_info
    (route JSON-RPC sans authentification), ou None."""
    corps = json.dumps(
        {"jsonrpc": "2.0", "method": "call", "params": {}, "id": 1}
    ).encode("utf-8")
    rep = systeme.ouvrir(
        cible.url + "/web/webclient/version_info",
        delai,
        corps,
        {"Content-Type": "application/json"},
    )
    if rep.statut != 200:
        return None
    try:
        info = json.loads(rep.corps).get("result") or {}
        version = info.get("server_version_info") or []
        return int(version[0])
    except (ValueError, TypeError, AttributeError, IndexError, KeyError):
        return None


# --- HTTP : page de connexion et /web/health ------------------------------


def _meme_hote(url, cible):
    morceaux = urllib.parse.urlsplit(url)
    return (morceaux.hostname or "").lower() == cible.hote.lower()


def suivre(url, cible, systeme, delai):
    """GET `url` en suivant au plus REDIRECTIONS_MAX redirections sur le
    même hôte : (Reponse, url finale, raison d'arrêt).

    La raison vaut "" quand la chaîne est allée au bout ; "selector" pour
    une redirection vers le sélecteur de bases ; "http" pour un retour au
    clair depuis https ; "other_host" pour un autre hôte. La redirection
    qui arrête la chaîne n'est pas suivie et sa réponse est rendue.
    """
    for _saut in range(REDIRECTIONS_MAX + 1):
        rep = systeme.ouvrir(url, delai)
        location = rep.entete("location")
        if not (300 <= rep.statut < 400 and location):
            return rep, url, ""
        suivante = urllib.parse.urljoin(url, location)
        morceaux = urllib.parse.urlsplit(suivante)
        if morceaux.path.startswith("/web/database/selector"):
            return rep, suivante, "selector"
        if cible.schema == "https" and morceaux.scheme == "http":
            return rep, suivante, "http"
        if not _meme_hote(suivante, cible):
            return rep, suivante, "other_host"
        url = suivante
    return rep, url, "too_many"


def url_connexion(cible):
    url = cible.url + "/web/login"
    if cible.base:
        url += "?db=" + urllib.parse.quote(cible.base)
    return url


def classer_login(rep, finale, raison, duree):
    """Le verdict de /web/login : Resultat `http_login`."""
    donnees = {
        "status": rep.statut,
        "seconds": round(duree, 3),
        "url": finale,
    }
    valeurs = {
        "status": rep.statut,
        "seconds": f"{duree:.2f}",
        "url": finale,
        "error": rep.erreur,
    }

    def r(statut, modele, conseil=""):
        return Resultat(
            "http_login", statut, modele, valeurs, conseil, donnees
        )

    if rep.statut == 0:
        return r(
            FAIL,
            N_("Login page: no answer ({error})."),
            N_(
                "Check that the service runs (systemctl status) and that the"
                " proxy reaches it."
            ),
        )
    if raison == "selector":
        return r(
            ATTN,
            N_("Login page: redirects to the database selector."),
            N_(
                "Several databases and no filter: set dbfilter or db_name in"
                " the Odoo configuration."
            ),
        )
    if raison == "http":
        return r(
            ATTN,
            N_("Login page: redirects to plain HTTP ({url})."),
            N_(
                "Set proxy_mode = True in Odoo and send X-Forwarded-Proto"
                " from the proxy."
            ),
        )
    if rep.statut >= 500:
        return r(
            FAIL,
            N_("Login page: HTTP {status}."),
            N_("Odoo or its proxy fails: read the Odoo log (log_check.py)."),
        )
    if 300 <= rep.statut < 400:
        return r(
            ATTN,
            N_("Login page: redirects to {url}."),
            N_("Check the proxy redirections for this host."),
        )
    if rep.statut != 200:
        return r(
            FAIL,
            N_("Login page: HTTP {status}."),
            N_("The proxy or Odoo refuses /web/login: check both."),
        )
    if duree > LENTEUR:
        return r(
            ATTN,
            N_("Login page: HTTP 200, slow ({seconds} s)."),
            N_(
                "A first request after a start loads the registry: warm up"
                " the cache (warmup_http.py --deep)."
            ),
        )
    return r(OK, N_("Login page: HTTP 200 in {seconds} s."))


def classer_sante(rep):
    """Le verdict de /web/health?db_server_status=1 : `web_health`."""
    valeurs = {"status": rep.statut, "error": rep.erreur}
    donnees = {"status": rep.statut}
    if rep.statut == 0:
        return Resultat(
            "web_health",
            FAIL,
            N_("/web/health: no answer ({error})."),
            valeurs,
            N_("Check that the service runs and that the proxy reaches it."),
            donnees,
        )
    if rep.statut == 404:
        return Resultat(
            "web_health",
            SKIP,
            N_("/web/health does not exist in this Odoo version."),
            valeurs,
            donnees=donnees,
        )
    try:
        etat = json.loads(rep.corps).get("status")
    except (ValueError, AttributeError):
        etat = None
    donnees["health"] = etat
    if rep.statut == 200 and etat == "pass":
        return Resultat(
            "web_health",
            OK,
            N_("/web/health: pass, PostgreSQL reachable."),
            valeurs,
            donnees=donnees,
        )
    if rep.statut == 500 or etat == "fail" or rep.statut > 500:
        return Resultat(
            "web_health",
            FAIL,
            N_("/web/health: HTTP {status}, the server or PostgreSQL fails."),
            valeurs,
            N_(
                "Check PostgreSQL (systemctl status postgresql) and db_host,"
                " db_port in the Odoo configuration."
            ),
            donnees,
        )
    return Resultat(
        "web_health",
        ATTN,
        N_("/web/health: unexpected answer (HTTP {status})."),
        valeurs,
        N_("The proxy may serve another page for /web/health."),
        donnees,
    )


# --- TLS, redirection vers https, HSTS ------------------------------------


def epoque_expiration(texte):
    """Les secondes Unix d'une date `notAfter` de `getpeercert()`
    (« Jun  1 00:00:00 2030 GMT »). Lève ValueError."""
    return ssl.cert_time_to_seconds(texte)


def jours_restants(fin, maintenant):
    """Les jours ENTIERS de `maintenant` à `fin` (secondes Unix), arrondis
    vers le bas : négatif une fois la date passée."""
    return int((fin - maintenant) // 86400)


def classer_expiration(jours):
    """FAIL sous JOURS_FAIL jours (expiré compris), ATTN sous JOURS_ATTN,
    OK au-delà."""
    if jours < JOURS_FAIL:
        return FAIL
    if jours < JOURS_ATTN:
        return ATTN
    return OK


def classer_erreur_tls(code, message):
    """Le modèle du message d'un certificat refusé, selon le code
    `verify_code` d'OpenSSL ; le message brut pour un code inconnu."""
    if code == TLS_NOM:
        return N_("Certificate refused: it does not match the host name.")
    if code == TLS_EXPIRE:
        return N_("Certificate refused: it has expired.")
    if code in TLS_AUTOSIGNE:
        return N_("Certificate refused: self-signed.")
    if code in TLS_EMETTEUR:
        return N_(
            "Certificate refused: unknown issuer (incomplete chain served?)."
        )
    return N_("Certificate refused: {reason}.")


def fin_validite_der(der):
    """L'époque `notAfter` d'un certificat DER, ou None.

    Validity est la première paire de dates d'un certificat X.509
    (TBSCertificate : version, série, algorithme, émetteur, puis
    validité) : la seconde date trouvée est notAfter. Une UTCTime à deux
    chiffres d'année vaut 19YY de 50 à 99, 20YY sinon (RFC 5280).
    """
    trouvees = RE_TEMPS_DER.findall(der or b"")
    if len(trouvees) < 2:
        return None
    court, long_ = trouvees[1]
    try:
        if court:
            texte = court.decode("ascii")
            siecle = "19" if int(texte[:2]) >= 50 else "20"
            texte = siecle + texte
        else:
            texte = long_.decode("ascii")
        return calendar.timegm(time.strptime(texte, "%Y%m%d%H%M%SZ"))
    except ValueError:
        return None


def _date(epoque):
    return time.strftime("%Y-%m-%d", time.gmtime(epoque))


def verifier_tls(cible, systeme, delai):
    """`tls_certificate` d'une cible https."""
    try:
        cert = systeme.certificat(cible.hote, cible.port, delai)
    except ssl.SSLCertVerificationError as err:
        return _tls_refuse(cible, systeme, delai, err)
    except (OSError, ValueError) as err:
        return Resultat(
            "tls_certificate",
            FAIL,
            N_("TLS connection impossible: {error}"),
            {"error": err, "port": cible.port},
            N_("Check that port {port} is open and served by the proxy."),
        )
    try:
        fin = epoque_expiration(cert["notAfter"])
    except (KeyError, TypeError, ValueError):
        return Resultat(
            "tls_certificate",
            ATTN,
            N_("Certificate accepted, expiry date unreadable."),
        )
    jours = jours_restants(fin, systeme.maintenant())
    valeurs = {"days": jours, "date": _date(fin), "port": cible.port}
    donnees = {"days_left": jours, "not_after": _date(fin)}
    statut = classer_expiration(jours)
    if statut == OK:
        return Resultat(
            "tls_certificate",
            OK,
            N_("Certificate valid for {days} days (until {date})."),
            valeurs,
            donnees=donnees,
        )
    modele = (
        N_("Certificate expired since {date}.")
        if jours < 0
        else N_("Certificate expires in {days} days ({date}).")
    )
    return Resultat(
        "tls_certificate",
        statut,
        modele,
        valeurs,
        N_(
            "The automatic renewal seems to fail: certbot renew --dry-run,"
            " then systemctl list-timers."
        ),
        donnees,
    )


def _tls_refuse(cible, systeme, delai, err):
    code = getattr(err, "verify_code", None)
    raison = getattr(err, "verify_message", "") or str(err)
    donnees = {"verify_code": code, "reason": raison}
    try:
        fin = fin_validite_der(
            systeme.certificat_brut(cible.hote, cible.port, delai)
        )
    except (OSError, ValueError):
        fin = None
    if fin is not None:
        donnees["not_after"] = _date(fin)
        donnees["days_left"] = jours_restants(fin, systeme.maintenant())
    return Resultat(
        "tls_certificate",
        FAIL,
        classer_erreur_tls(code, raison),
        {"reason": raison, "host": cible.hote},
        N_(
            "Serve a certificate for {host} with its full chain"
            " (certbot: fullchain.pem)."
        ),
        donnees,
    )


def classer_redirection(rep, hote):
    """Le verdict de `http://hote/` : `http_redirect`."""
    location = rep.entete("location")
    valeurs = {
        "status": rep.statut,
        "location": location,
        "error": rep.erreur,
        "host": hote,
    }
    donnees = {"status": rep.statut, "location": location}

    def r(statut, modele, conseil=""):
        return Resultat(
            "http_redirect", statut, modele, valeurs, conseil, donnees
        )

    if rep.statut == 0:
        return r(
            ATTN,
            N_("Port 80 does not answer ({error})."),
            N_(
                "Open port 80 and redirect it to HTTPS: the certbot HTTP-01"
                " renewal needs it too."
            ),
        )
    if rep.statut in (301, 302, 307, 308):
        morceaux = urllib.parse.urlsplit(location)
        if morceaux.scheme == "https":
            if (morceaux.hostname or "").lower() == hote.lower():
                return r(OK, N_("HTTP redirects to HTTPS ({location})."))
            return r(
                ATTN,
                N_("HTTP redirects to another host ({location})."),
                N_("Redirect http://{host}/ to https on the same host."),
            )
        return r(
            ATTN,
            N_("HTTP redirects to {location}, not to HTTPS."),
            N_("Redirect port 80 to https://$host$request_uri in nginx."),
        )
    if rep.statut == 200:
        return r(
            FAIL,
            N_("The site is served in clear text over HTTP."),
            N_("Redirect port 80 to https://$host$request_uri in nginx."),
        )
    return r(
        ATTN,
        N_("Port 80 answers HTTP {status} instead of a redirection."),
        N_("Redirect port 80 to https://$host$request_uri in nginx."),
    )


def classer_hsts(valeur):
    """Le verdict de l'en-tête Strict-Transport-Security : `hsts`."""
    conseil = N_(
        'add_header Strict-Transport-Security "max-age=31536000" always;'
        " in the nginx server block."
    )
    if not valeur:
        return Resultat(
            "hsts",
            ATTN,
            N_("No Strict-Transport-Security header."),
            {},
            conseil,
        )
    trouve = re.search(r"max-age\s*=\s*\"?(\d+)", valeur, re.I)
    age = int(trouve.group(1)) if trouve else 0
    valeurs = {"value": valeur, "seconds": age}
    if age < HSTS_MIN:
        return Resultat(
            "hsts",
            ATTN,
            N_("HSTS max-age is short ({seconds} s)."),
            valeurs,
            conseil,
            {"max_age": age},
        )
    return Resultat(
        "hsts", OK, N_("HSTS: {value}"), valeurs, donnees={"max_age": age}
    )


# --- Gestionnaire de bases ---------------------------------------------------


def classer_gestionnaire(rep, page, publique):
    """Le verdict de /web/database/<page> (`manager` ou `selector`) :
    `db_manager` ou `db_selector`. `publique` : la page est vue par le
    proxy (--url) ; en local, elle est joignable par construction et
    l'exposition n'est qu'un ATTN."""
    ident = "db_manager" if page == "manager" else "db_selector"
    chemin = "/web/database/" + page
    valeurs = {"path": chemin, "status": rep.statut, "error": rep.erreur}
    donnees = {"status": rep.statut}
    conseil = N_(
        "Set list_db = False in the Odoo configuration, or deny /web/database"
        " in the proxy."
    )
    grave = FAIL if publique else ATTN

    def r(statut, modele, conseil=""):
        return Resultat(ident, statut, modele, valeurs, conseil, donnees)

    if rep.statut == 0 or rep.statut >= 500:
        return r(
            ATTN,
            N_("{path}: undetermined (HTTP {status} {error})."),
            N_("Open the page by hand to check what it shows."),
        )
    if rep.statut != 200:
        return r(OK, N_("{path}: blocked (HTTP {status})."))
    corps = rep.corps
    if GESTIONNAIRE_DESACTIVE in corps:
        return r(OK, N_("{path}: disabled by list_db = False."))
    if GESTIONNAIRE_NON_PROTEGE in corps:
        return r(
            grave,
            N_("{path}: reachable, and the master password is not set."),
            N_(
                "Set a strong admin_passwd, then list_db = False or deny"
                " /web/database in the proxy."
            ),
        )
    if any(marque in corps for marque in MARQUES_GESTIONNAIRE):
        if page == "manager":
            return r(
                grave,
                N_("{path}: the database manager is reachable."),
                conseil,
            )
        return r(ATTN, N_("{path}: the database list is reachable."), conseil)
    return r(OK, N_("{path}: HTTP 200 without the database manager page."))


def classer_list_db(valeur):
    """Le verdict de `list_db` lu dans la configuration : `list_db`.
    Absent, Odoo le tient pour vrai."""
    texte = str(valeur).strip() if valeur is not None else ""
    if texte.lower() in ("false", "0", "no", "off"):
        return Resultat(
            "list_db",
            OK,
            N_("list_db = False in the configuration."),
            donnees={"value": texte},
        )
    modele = (
        N_("list_db is {value}: the database manager is enabled.")
        if texte
        else N_(
            "list_db is absent (True by default): the database manager"
            " is enabled."
        )
    )
    return Resultat(
        "list_db",
        ATTN,
        modele,
        {"value": texte},
        N_(
            "Set list_db = False in the Odoo configuration, or deny"
            " /web/database in the proxy."
        ),
        {"value": texte or None},
    )


# --- Bus, robots.txt ---------------------------------------------------------


def chemin_bus(version):
    """Le chemin du bus que le proxy relaie : /websocket dès Odoo 16,
    /longpolling/poll avant."""
    if version is not None and version <= 15:
        return "/longpolling/poll"
    return "/websocket"


def classer_bus(rep, chemin):
    """Le verdict d'un GET sans Upgrade sur le chemin du bus : `websocket`.
    Odoo répond 400 ou 426 à un tel GET : tout code hors 404 et 502/503/504
    prouve que le proxy relaie."""
    valeurs = {"path": chemin, "status": rep.statut, "error": rep.erreur}
    donnees = {"path": chemin, "status": rep.statut}
    if rep.statut == 0:
        return Resultat(
            "websocket",
            ATTN,
            N_("{path}: no answer ({error})."),
            valeurs,
            N_("Check the proxy location for {path}."),
            donnees,
        )
    if rep.statut in (502, 503, 504):
        return Resultat(
            "websocket",
            FAIL,
            N_("{path}: HTTP {status}, the proxy does not reach the bus."),
            valeurs,
            N_(
                "Odoo serves the bus on gevent_port (longpolling_port) only"
                " with workers > 0: match the proxy upstream."
            ),
            donnees,
        )
    if rep.statut == 404:
        return Resultat(
            "websocket",
            ATTN,
            N_("{path}: not found (HTTP 404)."),
            valeurs,
            N_("The proxy does not forward {path} to Odoo's bus port."),
            donnees,
        )
    return Resultat(
        "websocket",
        OK,
        N_("{path}: forwarded to Odoo (HTTP {status})."),
        valeurs,
        donnees=donnees,
    )


def classer_robots(rep):
    """Le verdict de /robots.txt : `robots`, ATTN au plus.

    Sans le module website, Odoo 18 sert « Disallow: / » de lui-même (une
    instance de gestion n'a rien à indexer), sans ligne Sitemap. Le
    gabarit de website nomme toujours son sitemap, et ajoute
    « Disallow: / » quand l'URL employée n'est pas le domaine du site.
    D'où l'ATTN seulement quand les deux lignes sont là. Le sitemap
    lui-même n'est pas demandé : Odoo le génère et le met en cache à la
    première demande.
    """
    valeurs = {"status": rep.statut}
    donnees = {"status": rep.statut}
    if rep.statut == 404:
        return Resultat(
            "robots",
            SKIP,
            N_("No robots.txt (no website module)."),
            valeurs,
            donnees=donnees,
        )
    if rep.statut != 200:
        return Resultat(
            "robots",
            ATTN,
            N_("robots.txt: HTTP {status}."),
            valeurs,
            N_("Check what the proxy serves for /robots.txt."),
            donnees,
        )
    bloque = re.search(r"^\s*disallow\s*:\s*/\s*$", rep.corps, re.I | re.M)
    plan_du_site = re.search(r"^\s*sitemap\s*:", rep.corps, re.I | re.M)
    donnees["disallow_all"] = bool(bloque)
    donnees["sitemap"] = bool(plan_du_site)
    if bloque and plan_du_site:
        return Resultat(
            "robots",
            ATTN,
            N_("robots.txt forbids everything while the site has a sitemap."),
            valeurs,
            N_(
                "Check the domain in the Website settings: Odoo forbids"
                " indexing when the URL used is not that domain."
            ),
            donnees,
        )
    if bloque:
        return Resultat(
            "robots",
            OK,
            N_("robots.txt forbids indexing (no public website)."),
            valeurs,
            donnees=donnees,
        )
    return Resultat(
        "robots", OK, N_("robots.txt served."), valeurs, donnees=donnees
    )


# --- DNS du courriel ---------------------------------------------------------


def outil_dns(systeme):
    """`dig`, sinon `host`, sinon None."""
    for nom in ("dig", "host"):
        if systeme.quel(nom):
            return nom
    return None


def commande_txt(outil, nom):
    """La commande de recherche TXT. dig garde l'en-tête de la réponse
    (`+comments`) : son statut distingue « aucun enregistrement » d'une
    recherche en échec, que `+short` confondrait en une sortie vide."""
    if outil == "dig":
        return [
            "dig",
            "+time=3",
            "+tries=1",
            "+noall",
            "+comments",
            "+answer",
            "TXT",
            nom,
        ]
    return ["host", "-W", "3", "-t", "TXT", nom]


def joindre_txt(ligne):
    """Un enregistrement TXT en une chaîne : `"a" "b"` → `ab`."""
    morceaux = RE_GUILLEMETS.findall(ligne)
    return "".join(morceaux) if morceaux else ligne


def lire_txt(outil, code, sortie):
    """Les enregistrements TXT de la sortie de `outil` : une liste (vide :
    aucun), ou None quand la recherche a échoué (délai, aucun serveur,
    SERVFAIL, REFUSED…).

    dig rend 0 pour toute réponse reçue, quel qu'en soit le statut : seul
    le statut de l'en-tête (le dernier, si dig a dû réessayer) tranche.
    NOERROR rend les TXT de la section réponse — un CNAME qui y figure
    n'en est pas un —, NXDOMAIN une liste vide, tout autre statut ou son
    absence None. host rend 1 pour un nom inexistant (NXDOMAIN) comme pour
    un délai ou un SERVFAIL, d'où la lecture du message.
    """
    lignes = [ligne.strip() for ligne in sortie.splitlines() if ligne.strip()]
    if outil == "host":
        if code != 0:
            return [] if "NXDOMAIN" in sortie else None
        lignes = [
            trouve.group(1)
            for trouve in (RE_HOST_TXT.search(ligne) for ligne in lignes)
            if trouve
        ]
        return [joindre_txt(ligne) for ligne in lignes]
    statuts = RE_DIG_STATUT.findall(sortie)
    if code != 0 or not statuts or statuts[-1] not in DIG_DEFINITIFS:
        return None
    if statuts[-1] == "NXDOMAIN":
        return []
    enregistrements = []
    for ligne in lignes:
        if ligne.startswith(";"):
            continue
        champs = ligne.split(None, 4)
        if len(champs) == 5 and champs[3].upper() == "TXT":
            enregistrements.append(joindre_txt(champs[4]))
    return enregistrements


def classer_spf(enregistrements, domaine):
    """Le verdict SPF : `mail_spf`."""
    spf = [e for e in enregistrements if e.lower().startswith("v=spf1")]
    valeurs = {"domain": domaine, "count": len(spf)}
    donnees = {"records": spf}
    if not spf:
        return Resultat(
            "mail_spf",
            FAIL,
            N_("No SPF record for {domain}."),
            valeurs,
            N_(
                'Publish one TXT record "v=spf1 ... -all" naming the servers'
                " that send for {domain}."
            ),
            donnees,
        )
    if len(spf) > 1:
        return Resultat(
            "mail_spf",
            FAIL,
            N_("{count} SPF records for {domain}: only one is valid."),
            valeurs,
            N_("Merge them into a single record."),
            donnees,
        )
    valeurs["record"] = spf[0]
    if re.search(r"(^|\s)\+all\b", spf[0]):
        return Resultat(
            "mail_spf",
            FAIL,
            N_("The SPF record of {domain} allows any server (+all)."),
            valeurs,
            N_("End the record with -all or ~all."),
            donnees,
        )
    if not re.search(r"(^|\s)[-~]all\b", spf[0]):
        return Resultat(
            "mail_spf",
            ATTN,
            N_("The SPF record of {domain} does not end with -all or ~all."),
            valeurs,
            N_("End the record with -all or ~all."),
            donnees,
        )
    return Resultat(
        "mail_spf", OK, N_("SPF: {record}"), valeurs, donnees=donnees
    )


def classer_dmarc(enregistrements, domaine):
    """Le verdict DMARC de `_dmarc.<domaine>` : `mail_dmarc`."""
    dmarc = [e for e in enregistrements if e.lower().startswith("v=dmarc1")]
    valeurs = {"domain": domaine}
    if not dmarc:
        return Resultat(
            "mail_dmarc",
            ATTN,
            N_("No DMARC record for {domain}."),
            valeurs,
            N_('Publish _dmarc.{domain} TXT "v=DMARC1; p=none" at least.'),
            {"records": []},
        )
    trouve = re.search(r"(?:^|;)\s*p\s*=\s*(\w+)", dmarc[0], re.I)
    valeurs["policy"] = trouve.group(1) if trouve else "?"
    return Resultat(
        "mail_dmarc",
        OK,
        N_("DMARC of {domain}: policy {policy}."),
        valeurs,
        donnees={"records": dmarc, "policy": valeurs["policy"]},
    )


def classer_dkim(enregistrements, domaine, selecteur):
    """Le verdict DKIM de `<selecteur>._domainkey.<domaine>` : `mail_dkim`.
    Une clé vide (`p=`) est une clé révoquée."""
    nom = f"{selecteur}._domainkey.{domaine}"
    valeurs = {"name": nom}
    cles = []
    for enregistrement in enregistrements:
        trouve = re.search(r"(?:^|;)\s*p\s*=\s*([^;\s]*)", enregistrement)
        if trouve:
            cles.append(trouve.group(1))
    donnees = {"name": nom, "found": bool(cles)}
    if any(cles):
        return Resultat(
            "mail_dkim",
            OK,
            N_("DKIM key found: {name}."),
            valeurs,
            "",
            donnees,
        )
    if cles:
        return Resultat(
            "mail_dkim",
            FAIL,
            N_("The DKIM key {name} is empty (revoked)."),
            valeurs,
            N_("Publish the public key given by the sending service."),
            donnees,
        )
    return Resultat(
        "mail_dkim",
        FAIL,
        N_("No DKIM key at {name}."),
        valeurs,
        N_(
            "Publish the public key given by the sending service, or check"
            " the selector."
        ),
        donnees,
    )


def verifier_courriel(domaine, selecteur, systeme, delai):
    """`mail_spf`, `mail_dmarc` et `mail_dkim` (avec un sélecteur). Les
    noms sont validés par l'analyse des options, avant tout appel."""
    noms = [("mail_spf", domaine), ("mail_dmarc", "_dmarc." + domaine)]
    if selecteur:
        noms.append(("mail_dkim", f"{selecteur}._domainkey.{domaine}"))
    outil = outil_dns(systeme)
    resultats = []
    for ident, nom in noms:
        if outil is None:
            resultat = Resultat(
                ident,
                SKIP,
                N_("Neither dig nor host is installed: DNS not checked."),
                conseil=N_("Install dnsutils (dig) or bind9-host (host)."),
            )
        else:
            code, sortie = systeme.lanceur(commande_txt(outil, nom), delai)
            enregistrements = lire_txt(outil, code, sortie)
            if enregistrements is None:
                resultat = Resultat(
                    ident,
                    SKIP,
                    N_("DNS lookup of {name} failed (code {code})."),
                    {"name": nom, "code": code},
                    N_("Check the DNS resolver of this host."),
                )
            elif ident == "mail_spf":
                resultat = classer_spf(enregistrements, domaine)
            elif ident == "mail_dmarc":
                resultat = classer_dmarc(enregistrements, domaine)
            else:
                resultat = classer_dkim(enregistrements, domaine, selecteur)
        resultat.cible = domaine
        resultats.append(resultat)
    return resultats


# --- Une cible entière ------------------------------------------------------


# Les SKIP d'une cible locale (ces vérifications concernent le proxy ou
# le nom public) et d'une URL en clair.
SAUTS_LOCAL = {
    "tls_certificate": N_(
        "TLS certificate: not checked on the local address (use --url)."
    ),
    "http_redirect": N_(
        "HTTPS redirect: not checked on the local address (use --url)."
    ),
    "hsts": N_("HSTS: not checked on the local address (use --url)."),
    "websocket": N_("Bus path: not checked on the local address (use --url)."),
    "robots": N_("robots.txt: judged on the public URL only (use --url)."),
}
SAUTS_CLAIR = {
    "tls_certificate": N_("TLS certificate: not an HTTPS URL."),
    "http_redirect": N_("HTTPS redirect: not an HTTPS URL."),
    "hsts": N_("HSTS: not an HTTPS URL."),
}


def _saute(ident, modele):
    return Resultat(ident, SKIP, modele)


def verifier_https(cible, systeme, delai, rep_login):
    """`tls_certificate`, `http_redirect` et `hsts` d'une cible --url ;
    SKIP pour une cible locale, `https` en ATTN pour une URL en clair."""
    idents = ("tls_certificate", "http_redirect", "hsts")
    if cible.kind == "local":
        return [_saute(ident, SAUTS_LOCAL[ident]) for ident in idents]
    if cible.schema != "https":
        clair = Resultat(
            "https",
            ATTN,
            N_("The URL is plain HTTP: nothing is encrypted."),
            conseil=N_(
                "Serve the site over HTTPS (deploy_nginx_and_certbot.py)."
            ),
        )
        return [clair] + [_saute(i, SAUTS_CLAIR[i]) for i in idents]
    resultats = [verifier_tls(cible, systeme, delai)]
    clair = f"http://{_netloc(cible.hote, 80, 'http')}/"
    resultats.append(
        classer_redirection(systeme.ouvrir(clair, delai), cible.hote)
    )
    if rep_login.statut == 200:
        resultats.append(
            classer_hsts(rep_login.entete("strict-transport-security"))
        )
    else:
        resultats.append(
            _saute(
                "hsts", N_("HSTS: no HTTP 200 on /web/login to read it on.")
            )
        )
    return resultats


def verifier_bus(cible, systeme, delai):
    """`websocket` d'une cible --url ; une version inconnue essaie
    /websocket, puis /longpolling/poll sur un 404."""
    if cible.kind == "local":
        return _saute("websocket", SAUTS_LOCAL["websocket"])
    chemin = chemin_bus(cible.version)
    rep = systeme.ouvrir(cible.url + chemin, delai)
    if rep.statut == 404 and cible.version is None:
        chemin = "/longpolling/poll"
        rep = systeme.ouvrir(cible.url + chemin, delai)
    return classer_bus(rep, chemin)


def verifier_cible(cible, systeme, delai):
    """Toutes les vérifications HTTP d'une cible, dans l'ordre de
    l'en-tête ; chaque Resultat porte `cible.url`."""
    debut = systeme.horloge()
    rep_login, finale, raison = suivre(
        url_connexion(cible), cible, systeme, delai
    )
    duree = systeme.horloge() - debut
    resultats = [classer_login(rep_login, finale, raison, duree)]
    resultats.append(
        classer_sante(
            systeme.ouvrir(cible.url + "/web/health?db_server_status=1", delai)
        )
    )
    resultats.extend(verifier_https(cible, systeme, delai, rep_login))
    publique = cible.kind == "url"
    for page in ("manager", "selector"):
        rep = systeme.ouvrir(cible.url + "/web/database/" + page, delai)
        resultats.append(classer_gestionnaire(rep, page, publique))
    if cible.kind == "local":
        resultats.append(classer_list_db(cible.list_db))
    resultats.append(verifier_bus(cible, systeme, delai))
    if publique:
        robots = systeme.ouvrir(cible.url + "/robots.txt", delai)
        resultats.append(classer_robots(robots))
    else:
        resultats.append(_saute("robots", SAUTS_LOCAL["robots"]))
    for resultat in resultats:
        resultat.cible = cible.url
    return resultats


def verifier_local(
    hote, port, base=None, list_db=None, delai=DELAI_PAR_DEFAUT, systeme=None
):
    """L'API en processus d'`update_module` : (version, [Resultat]) de
    l'instance qui écoute sur `hote:port`. Ne lève pas pour un échec HTTP :
    il devient un Resultat."""
    systeme = systeme or Systeme()
    cible = cible_locale(hote, port, base, list_db)
    cible.version = version_odoo(cible, systeme, delai)
    return cible.version, verifier_cible(cible, systeme, delai)


# --- Sortie ------------------------------------------------------------------


def compter(resultats):
    totaux = {statut.lower(): 0 for statut in STATUTS}
    for resultat in resultats:
        totaux[resultat.statut.lower()] += 1
    return totaux


def code_de_sortie(resultats):
    return CODE_FAIL if any(r.statut == FAIL for r in resultats) else CODE_OK


def afficher_resultat(rapport, resultat):
    """Une ligne au verdict, puis le conseil, sauf pour OK."""
    message = resultat.message(t)
    ecrire = {
        OK: rapport.ok,
        ATTN: rapport.attn,
        FAIL: rapport.fail,
        SKIP: rapport.skip,
    }[resultat.statut]
    ecrire(message)
    conseil = resultat.conseil(t)
    if conseil and resultat.statut != OK:
        rapport.detail("→ " + conseil)


def _titre(cible):
    if cible.kind == "local":
        titre = t("{url} (local, {unit})").format(
            url=cible.url, unit=cible.unite or "?"
        )
    else:
        titre = cible.url
    if cible.version:
        titre += " — Odoo {}".format(cible.version)
    return titre


def ecrire_texte(rapport, cibles, sections, courriel, domaine):
    rapport.texte(
        "{} — {}".format(
            t("Odoo health check"),
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
    )
    rapport.total = len(cibles) + (1 if courriel else 0)
    for cible, resultats in zip(cibles, sections):
        rapport.etape(_titre(cible))
        for resultat in resultats:
            afficher_resultat(rapport, resultat)
    if courriel:
        rapport.etape(
            t("Outgoing mail DNS of {domain}").format(domain=domaine)
        )
        for resultat in courriel:
            afficher_resultat(rapport, resultat)
    tous = [r for section in sections for r in section] + courriel
    totaux = compter(tous)
    rapport.texte()
    rapport.texte(
        "OK {ok} · ATTN {attn} · FAIL {fail} · SKIP {skip}".format(**totaux)
    )
    a_revoir = [r for r in tous if r.statut in (ATTN, FAIL)]
    if a_revoir:
        rapport.texte(
            t("To review: {checks}").format(
                checks=", ".join(f"{r.ident} ({r.statut})" for r in a_revoir)
            )
        )


def resume_json(cibles, resultats, code):
    versions = [c.version for c in cibles if c.version]
    return {
        "tool": "health_check",
        "odoo_version": versions[0] if versions else None,
        "targets": [
            {"kind": c.kind, "url": c.url, "odoo_version": c.version}
            for c in cibles
        ],
        "checks": [r.json() for r in resultats],
        "summary": compter(resultats),
        "exit_code": code,
    }


# --- Programme -------------------------------------------------------------

TYPES = service.types_argparse(t)


def _type_url(valeur):
    try:
        return normaliser_url(valeur)
    except ValueError as err:
        raise argparse.ArgumentTypeError(
            t("invalid URL ({reason}): {value}").format(
                reason=t(str(err)), value=valeur
            )
        )


def _type_domaine(valeur):
    if RE_DOMAINE.fullmatch(valeur or "") is None:
        raise argparse.ArgumentTypeError(
            t("invalid DNS name: {value}").format(value=valeur)
        )
    return valeur.lower().rstrip(".")


def _type_delai(valeur):
    try:
        nombre = float(valeur)
    except ValueError:
        nombre = 0
    if not 0 < nombre <= 300:
        raise argparse.ArgumentTypeError(
            t("expected seconds between 0 and 300: {value}").format(
                value=valeur
            )
        )
    return nombre


def analyser(argv=None):
    parser = argparse.ArgumentParser(
        description=t(
            "Check that an Odoo instance answers and exposes nothing it"
            " should not: login page, /web/health, TLS, HTTPS redirect,"
            " HSTS, database manager, bus, robots.txt, mail DNS."
        )
    )
    parser.add_argument(
        "--url",
        action="append",
        type=_type_url,
        default=[],
        help=t(
            "Public URL to probe through the proxy; repeatable. A bare host"
            " means https://host."
        ),
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help=t(
            "Probe the local instance of the systemd unit, where Odoo listens."
        ),
    )
    parser.add_argument(
        "--service",
        type=TYPES.unite,
        help=t(
            "With --local: systemd unit; default: the unit whose"
            " WorkingDirectory is this checkout, else the only active one."
        ),
    )
    parser.add_argument(
        "--mail-domain",
        type=_type_domaine,
        metavar="DOMAIN",
        help=t("Check the SPF and DMARC records of this sending domain."),
    )
    parser.add_argument(
        "--dkim-selector",
        type=_type_domaine,
        metavar="SELECTOR",
        help=t("With --mail-domain: also check this DKIM selector."),
    )
    parser.add_argument(
        "--timeout",
        type=_type_delai,
        default=DELAI_PAR_DEFAUT,
        help=t(
            "Seconds for each request, TLS connection and DNS lookup;"
            " default: {seconds}."
        ).format(seconds=int(DELAI_PAR_DEFAUT)),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=t("Print the summary as JSON (untranslated keys)."),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=t("Show each system command on stderr."),
    )
    args = parser.parse_args(argv)
    if not args.url and not args.local:
        parser.error(t("Give --url URL, --local, or both."))
    if args.service and not args.local:
        parser.error(t("--service requires --local."))
    if args.dkim_selector and not args.mail_domain:
        parser.error(t("--dkim-selector requires --mail-domain."))
    return args


def executer(args, systeme, flux):
    cibles = list(args.url)
    try:
        if args.local:
            cibles.append(detecter_locale(args.service, systeme))
    except Refus as err:
        return _refuser(args, flux, err.message(t))
    sections = []
    for cible in cibles:
        cible.version = version_odoo(cible, systeme, args.timeout)
        sections.append(verifier_cible(cible, systeme, args.timeout))
    courriel = []
    if args.mail_domain:
        courriel = verifier_courriel(
            args.mail_domain, args.dkim_selector, systeme, args.timeout
        )
    tous = [r for section in sections for r in section] + courriel
    code = code_de_sortie(tous)
    if args.json:
        print(
            json.dumps(
                resume_json(cibles, tous, code), ensure_ascii=False, indent=2
            ),
            file=flux,
        )
        return code
    rapport = report.Rapport(flux=flux)
    ecrire_texte(rapport, cibles, sections, courriel, args.mail_domain)
    return code


def _refuser(args, flux, message):
    if args.json:
        print(
            json.dumps(
                {
                    "tool": "health_check",
                    "exit_code": CODE_REFUS,
                    "error": message,
                },
                ensure_ascii=False,
            ),
            file=flux,
        )
    print(f"❌ {message}", file=sys.stderr)
    return CODE_REFUS


def main(argv=None, systeme=None, flux=None):
    args = analyser(argv)
    systeme = systeme or Systeme(verbeux=args.verbose)
    flux = flux or sys.stdout
    try:
        return executer(args, systeme, flux)
    except KeyboardInterrupt:
        print(t("Interrupted."), file=sys.stderr)
        return CODE_INTERROMPU
    except Exception as err:
        # Python sortirait en 1, « un FAIL » : une erreur imprévue est une
        # vérification qui n'a pas pu se faire, code 2.
        return _refuser(
            args,
            flux,
            t("Unexpected error: {error}").format(error=err),
        )


if __name__ == "__main__":
    sys.exit(main())
