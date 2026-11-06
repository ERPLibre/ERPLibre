# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Vérifier le certificat d'un serveur courriel, ou le comparer à une
empreinte épinglée.

Une connexion TLS vérifie par défaut la chaîne ET le nom du serveur contre
les autorités du système (`verified_context`). Aucune fonction de ce module
ne désactive cette vérification pour un point d'accès sans épingle.

Une épingle est l'empreinte SHA-256 du certificat FEUILLE (DER), acceptée
par un geste humain pour un compte et un point d'accès `hôte:port`. Elle
REMPLACE la vérification pour ce point d'accès : la poignée de main se fait
sans rien vérifier (`pinning_context`), puis `check_pin` compare
l'empreinte présentée à l'épingle AVANT toute authentification ; une autre
empreinte est refusée (`changed`). Le nom et les dates ne sont alors plus
vérifiés.

Une poignée de main refusée ne rend pas le certificat refusé : la sonde
(`peer_certificate`) le lit par une seconde connexion, qui mène le
protocole jusqu'au TLS, lit le certificat et ferme sans jamais
s'authentifier. `certificate_error` rend l'erreur d'un refus, empreinte
comprise, pour qu'un humain puisse décider de l'épingler.

N'importe que la bibliothèque standard et `erplibre_mail_core.i18n`.
"""

from __future__ import annotations

import hashlib
import hmac
import imaplib
import logging
import smtplib
import ssl

from erplibre_mail_core.i18n import t

FINGERPRINT_PREFIX = "sha256:"
PROTOCOLS = ("imap", "smtp")
SECURITIES = ("ssl", "starttls")
REASONS = ("untrusted", "hostname", "validity", "nonconforming", "changed")
# Codes X509_V_ERR d'OpenSSL : nom d'hôte, courriel ou adresse IP qui ne
# correspondent pas au certificat ; certificat pas encore ou plus valide ;
# contrôles que seul VERIFY_X509_STRICT déclenche (OpenSSL 3, codes 80 à
# 94). Le code 79 (`INVALID_CA`) n'en est pas : OpenSSL le lève aussi hors
# mode strict, quand un certificat qui n'est pas une autorité a signé le
# suivant — le schéma d'une chaîne forgée —, et il reste `untrusted`.
HOSTNAME_CODES = frozenset({62, 63, 64})
VALIDITY_CODES = frozenset({9, 10})
NONCONFORMING_CODES = frozenset(range(80, 95))
# Longueur d'une empreinte SHA-256 en hexadécimal.
_HEX_LEN = 64
_HEX = frozenset("0123456789abcdef")

_logger = logging.getLogger(__name__)


class TlsCertificateError(Exception):
    """Le certificat d'un serveur est refusé : vérification ou épingle.

    Hérite d'`Exception` seulement : ni `OSError` (une panne réseau se
    réessaie et rouvre le lien, un refus de certificat non), ni une erreur
    de protocole IMAP ou SMTP (le serveur n'a rien refusé, aucun
    identifiant n'est parti). `permanent` vaut False : pour une file
    d'envoi, le refus est transitoire, il cesse quand un humain épingle le
    certificat ou que le serveur en change.

    `fingerprint` est l'empreinte présentée (64 hex minuscules, `""` si
    elle n'a pas pu être lue), `pinned` l'épingle refusée pour `changed`
    (None sinon), `names` les noms du certificat pour `hostname`, `detail`
    le texte d'OpenSSL, réservé au journal. Le texte de l'erreur tient sur
    une ligne et se compose à la construction, dans la langue en vigueur.
    """

    permanent = False

    def __init__(
        self,
        *,
        protocol: str,
        host: str,
        port: int,
        reason: str,
        fingerprint: str = "",
        pinned: str | None = None,
        detail: str = "",
        names: tuple = (),
    ):
        self.protocol = protocol
        self.host = host
        self.port = int(port)
        self.reason = reason
        self.fingerprint = fingerprint or ""
        self.pinned = pinned
        self.detail = detail or ""
        self.names = tuple(names or ())
        super().__init__(message_for(self))

    @property
    def endpoint(self) -> str:
        """Le point d'accès, sous la forme d'une clé d'épingle."""
        return pin_key(self.host, self.port)

    @property
    def pinnable(self) -> bool:
        """Vrai si l'empreinte présentée a pu être lue."""
        return bool(self.fingerprint)


def fingerprint(der: bytes) -> str:
    """L'empreinte SHA-256 d'un certificat DER, en 64 hex minuscules."""
    return hashlib.sha256(der).hexdigest()


def format_fingerprint(fp: str | None) -> str:
    """L'empreinte en octets hexadécimaux MAJUSCULES séparés par « : »,
    la forme d'`openssl x509 -fingerprint -sha256` ; une empreinte vide ou
    illisible se dit en toutes lettres."""
    hexa = parse_pin(fp) if fp else None
    if hexa is None:
        return t("mail_tls_fingerprint_unreadable")
    return ":".join(hexa[i : i + 2].upper() for i in range(0, len(hexa), 2))


def parse_pin(value) -> str | None:
    """L'empreinte de `value` en 64 hex minuscules, ou None.

    Le préfixe `sha256:` est facultatif ; deux-points, blancs et casse
    sont ignorés. Toute autre forme rend None.
    """
    if not isinstance(value, str):
        return None
    texte = value.strip()
    if texte.lower().startswith(FINGERPRINT_PREFIX):
        texte = texte[len(FINGERPRINT_PREFIX) :]
    hexa = "".join(texte.split()).replace(":", "").lower()
    if len(hexa) != _HEX_LEN or not set(hexa) <= _HEX:
        return None
    return hexa


def pin_value(fp: str) -> str:
    """La valeur écrite d'une épingle : `sha256:` puis 64 hex minuscules.

    Lève `ValueError` sur une empreinte invalide.
    """
    hexa = parse_pin(fp)
    if hexa is None:
        raise ValueError(fp)
    return FINGERPRINT_PREFIX + hexa


def _host_of_key(host: str) -> str:
    texte = str(host).strip()
    if texte.startswith("[") and texte.endswith("]"):
        texte = texte[1:-1]
    return texte.lower().rstrip(".")


def pin_key(host: str, port: int) -> str:
    """La clé d'épingle d'un point d'accès : hôte sans blancs, en
    minuscules, sans point final, entre crochets s'il contient « : »
    (IPv6), puis `:port`. La sécurité (SSL ou STARTTLS) n'en fait pas
    partie : un même port sert un même certificat."""
    hote = _host_of_key(host)
    if ":" in hote:
        hote = f"[{hote}]"
    return f"{hote}:{int(port)}"


def split_pin_key(key) -> tuple[str, int] | None:
    """L'inverse de `pin_key` : `(hôte, port)` normalisés, ou None pour
    une clé illisible (hôte vide, port hors de 1–65535)."""
    if not isinstance(key, str):
        return None
    texte = key.strip()
    if texte.startswith("["):
        fin = texte.find("]")
        if fin < 0 or texte[fin + 1 : fin + 2] != ":":
            return None
        hote, port = texte[1:fin], texte[fin + 2 :]
    else:
        hote, sep, port = texte.rpartition(":")
        if not sep or ":" in hote:
            return None
    hote = _host_of_key(hote)
    if not hote or not port.isdigit():
        return None
    numero = int(port)
    if not 1 <= numero <= 65535:
        return None
    return hote, numero


def account_pin(pins, host: str, port: int) -> str | None:
    """L'épingle d'un point d'accès dans `pins` ({clé: valeur}), en 64 hex
    minuscules ; None sans épingle lisible pour ce point d'accès."""
    if not pins or not hasattr(pins, "get"):
        return None
    try:
        return parse_pin(pins.get(pin_key(host, port)))
    except (TypeError, ValueError):
        return None


def reason_of(exc: BaseException) -> str:
    """La raison d'un refus de vérification, lue dans son code OpenSSL."""
    code = getattr(exc, "verify_code", None)
    if code in HOSTNAME_CODES:
        return "hostname"
    if code in VALIDITY_CODES:
        return "validity"
    if code in NONCONFORMING_CODES:
        return "nonconforming"
    return "untrusted"


# La clé du catalogue de chaque raison, écrite en entier.
_REASON_KEYS = {
    "untrusted": "mail_tls_reason_untrusted",
    "hostname": "mail_tls_reason_hostname",
    "validity": "mail_tls_reason_validity",
    "nonconforming": "mail_tls_reason_nonconforming",
    "changed": "mail_tls_reason_changed",
}


def reason_text(reason: str) -> str:
    """La raison en clair, dans la langue en vigueur ; une raison inconnue
    se rend telle quelle."""
    cle = _REASON_KEYS.get(reason)
    return t(cle) if cle else str(reason)


def message_for(exc: TlsCertificateError) -> str:
    """Le texte d'une ligne d'un refus.

    Il s'assemble de clés-préfixes et des valeurs : une clé absente du
    catalogue s'affiche telle quelle, et le point d'accès, le protocole et
    les empreintes restent lisibles.
    """
    proto = exc.protocol.upper()
    tete = f"{exc.endpoint} ({proto})"
    presentee = (
        f"{t('mail_tls_presented')} {format_fingerprint(exc.fingerprint)}"
    )
    if exc.reason == "changed":
        return (
            f"{t('mail_tls_changed')} {tete}"
            f" — {t('mail_tls_pinned')} {format_fingerprint(exc.pinned)}"
            f" — {presentee}"
        )
    return (
        f"{t('mail_tls_refused')} {tete} — {reason_text(exc.reason)}"
        f" — {presentee}"
    )


def _tls12_minimum(context: ssl.SSLContext) -> ssl.SSLContext:
    """Relève la version minimale du contexte à TLS 1.2 si elle est plus
    basse ; une version déjà plus haute reste telle quelle."""
    minimum = context.minimum_version
    if minimum == ssl.TLSVersion.MINIMUM_SUPPORTED or (
        minimum < ssl.TLSVersion.TLSv1_2
    ):
        context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def verified_context(cafile: str | None = None) -> ssl.SSLContext:
    """Le contexte qui vérifie la chaîne et le nom du serveur.

    `create_default_context` : `CERT_REQUIRED`, `check_hostname`,
    autorités du système, ou celles de `SSL_CERT_FILE`/`SSL_CERT_DIR`
    quand ces variables sont posées. `cafile` remplace ces autorités par
    celle d'un fichier ; aucun appel de ce module ne le passe.
    """
    return _tls12_minimum(ssl.create_default_context(cafile=cafile))


def chain_context() -> ssl.SSLContext:
    """Le contexte qui vérifie la chaîne sans le nom : il sert à la sonde
    d'un refus de nom, pour lire les noms que porte le certificat."""
    context = verified_context()
    context.check_hostname = False
    return context


def pinning_context() -> ssl.SSLContext:
    """Le contexte qui ne vérifie RIEN, ni chaîne ni nom.

    Il ne sert que là où l'empreinte est comparée aussitôt après la
    poignée de main (`check_pin`), ou pour lire un certificat sans rien
    envoyer (`peer_certificate`). `check_hostname` tombe avant
    `verify_mode` : l'ordre inverse lève `ValueError`.
    """
    context = _tls12_minimum(ssl.create_default_context())
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def context_for(pin: str | None) -> ssl.SSLContext:
    """Le contexte d'une connexion : celui de l'épingle s'il y en a une,
    sinon le contexte vérifiant, sans argument."""
    if pin:
        return pinning_context()
    return verified_context()


def peer_fingerprint(sock) -> str:
    """L'empreinte du certificat que présente `sock` ; `""` sans
    certificat, ou pour un objet qui n'en rend pas."""
    try:
        der = sock.getpeercert(binary_form=True)
    except Exception:
        return ""
    if not der:
        return ""
    return fingerprint(der)


def _log_refusal(exc: TlsCertificateError, code=None) -> None:
    epingle = f" pinned={exc.pinned}" if exc.reason == "changed" else ""
    code_txt = f" code={code}" if code is not None else ""
    _logger.warning(
        "certificat TLS refusé : %s %s %s%s sha256=%s%s",
        exc.protocol.upper(),
        exc.endpoint,
        exc.reason,
        code_txt,
        exc.fingerprint or "-",
        epingle,
    )


def check_pin(sock, pin: str, *, protocol: str, host: str, port: int) -> None:
    """Compare l'empreinte du certificat de `sock` à `pin`.

    Égale : rien. Différente, illisible, ou épingle illisible : ligne
    `WARNING` au journal et `TlsCertificateError` `changed`, avec les deux
    empreintes.
    """
    presentee = peer_fingerprint(sock)
    attendue = parse_pin(pin)
    if (
        presentee
        and attendue
        and hmac.compare_digest(presentee.encode(), attendue.encode())
    ):
        return
    exc = TlsCertificateError(
        protocol=protocol,
        host=host,
        port=port,
        reason="changed",
        fingerprint=presentee,
        pinned=attendue,
    )
    _log_refusal(exc)
    raise exc


def _names_of(cert: dict | None) -> tuple[str, ...]:
    noms = []
    for genre, valeur in (cert or {}).get("subjectAltName", ()):
        if genre in ("DNS", "IP Address"):
            noms.append(str(valeur).strip())
    return tuple(noms)


def peer_certificate(
    protocol: str,
    host: str,
    port: int,
    security: str,
    timeout: float,
    *,
    context=None,
) -> tuple[bytes, tuple[str, ...]] | None:
    """Lit le certificat que présente le serveur, sans s'authentifier.

    Mène le protocole jusqu'au TLS (`STARTTLS` compris), lit le DER du
    certificat feuille et ferme la socket sans LOGOUT ni QUIT. Sans
    `context`, rien n'est vérifié et les noms rendus sont vides ; avec un
    contexte qui vérifie la chaîne (`chain_context`), les noms du
    certificat sont lus aussi. Rend `(der, noms)`, ou None pour un
    protocole ou une sécurité sans TLS, et pour toute panne.
    """
    if protocol not in PROTOCOLS or security not in SECURITIES:
        return None
    contexte = context if context is not None else pinning_context()
    client = None
    try:
        if protocol == "imap":
            if security == "ssl":
                client = imaplib.IMAP4_SSL(
                    host, port, ssl_context=contexte, timeout=timeout
                )
            else:
                client = imaplib.IMAP4(host, port, timeout=timeout)
                client.starttls(ssl_context=contexte)
        else:
            if security == "ssl":
                client = smtplib.SMTP_SSL(
                    host, port, timeout=timeout, context=contexte
                )
            else:
                client = smtplib.SMTP(host, port, timeout=timeout)
                client.starttls(context=contexte)
        der = client.sock.getpeercert(binary_form=True)
        if not der:
            return None
        noms = _names_of(client.sock.getpeercert()) if context else ()
        return der, noms
    except Exception as exc:
        _logger.info(
            "sonde TLS sans certificat : %s %s %s",
            protocol.upper(),
            pin_key(host, port),
            type(exc).__name__,
        )
        return None
    finally:
        if client is not None:
            try:
                if protocol == "imap":
                    client.shutdown()
                else:
                    client.close()
            except Exception:
                # La socket peut déjà être fermée ; la sonde n'a rien à
                # rendre de plus.
                pass


def certificate_error(
    exc: BaseException,
    *,
    protocol: str,
    host: str,
    port: int,
    security: str,
    timeout: float,
) -> TlsCertificateError:
    """L'erreur d'un refus de vérification, empreinte lue par la sonde.

    Pour un nom faux, la sonde vérifie la chaîne sans le nom et lit les
    noms du certificat ; si elle échoue, la sonde ordinaire lit le DER
    seul. Écrit une ligne `WARNING` au journal ; rend l'erreur sans la
    lever.
    """
    raison = reason_of(exc)
    lu = None
    if raison == "hostname":
        lu = peer_certificate(
            protocol, host, port, security, timeout, context=chain_context()
        )
    if lu is None:
        lu = peer_certificate(protocol, host, port, security, timeout)
    der, noms = lu if lu is not None else (b"", ())
    erreur = TlsCertificateError(
        protocol=protocol,
        host=host,
        port=port,
        reason=raison,
        fingerprint=fingerprint(der) if der else "",
        detail=getattr(exc, "verify_message", "") or "",
        names=noms,
    )
    _log_refusal(erreur, getattr(exc, "verify_code", None))
    return erreur
