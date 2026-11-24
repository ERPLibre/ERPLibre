# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Classer l'échec d'envoi d'un courriel d'Odoo par sa cause SMTP.

Deux lecteurs partagent ce classement : `script/odoo/log_check.py`, sur le
texte d'un enregistrement du journal d'Odoo (trace comprise), et
`script/odoo/mail_retry.py`, sur le `failure_reason` d'un `mail.mail` en
échec. Chaque classe dit si la cause est PERMANENTE — un renvoi échoue de
nouveau tant que le réglage n'est pas corrigé — ou passagère, et quel
réglage d'Odoo regarder.

Le classement ne lit que des jetons indépendants de la langue : noms des
exceptions de smtplib et de ssl, codes SMTP (452, 535…), codes étendus
(4.4.5, 5.7.8…) et textes que le serveur distant renvoie en anglais.
Odoo traduit la phrase qui les entoure (« Mail delivery failed via SMTP
server… ») dans la langue de l'utilisateur : elle ne sert jamais de
repère.

Les classes sont essayées dans l'ordre de `CLASSES` et la première qui
répond l'emporte : une limite d'envoi (5.4.5) passe avant un refus
d'expéditeur, un « 503 Multiple MAIL » qui suit un premier échec passe
avant le refus générique.

Ce module ne traduit rien. Libellés et réglages sont des modèles anglais
marqués par `N_()` ; l'outil qui les affiche les traduit par sa fonction
`t()`, comme `service.Refus`. Les identifiants de classe (`rate_limit`,
`auth`…) sont stables et servent de clés dans le JSON des outils.

Bibliothèque standard seulement, sans syntaxe postérieure à Python 3.7.
"""

from __future__ import annotations

import collections
import re


def N_(texte):
    """Marque un modèle de message à traduire par l'outil appelant."""
    return texte


# Une classe de cause : identifiant stable, cause permanente ou non, motif
# cherché dans le texte, libellé court (modèle anglais).
Classe = collections.namedtuple("Classe", "id permanent motif libelle")

# Ce qu'un texte doit porter pour qu'une cause soit lue comme un échec
# d'envoi de courriel : sans ce garde, un « Connection refused » d'un
# géocodeur ou d'une API tierce serait classé « serveur SMTP injoignable ».
RE_CONTEXTE = re.compile(
    r"MailDeliveryException|smtplib|ir_mail_server|mail_mail|SMTP", re.I
)

_I = re.I | re.S

CLASSES = (
    Classe(
        "tls",
        True,
        re.compile(
            r"\bSSLError\b|CERTIFICATE_VERIFY_FAILED|certificate verify"
            r" failed|wrong[ _]version[ _]number|STARTTLS extension not"
            r" supported|SMTPNotSupportedError|unknown[ _]protocol",
            _I,
        ),
        N_("TLS or certificate error"),
    ),
    # 421, 450 et 451 sont aussi l'écart temporaire d'un serveur qui
    # pratique le greylisting, ou une erreur locale passagère : la cause
    # reste passagère dans tous les cas.
    Classe(
        "rate_limit",
        False,
        re.compile(
            r"SMTP\w*: \((?:421|450|451|452)\b|Maximum number of messages"
            r" per session|too many (?:messages|recipients|connections)|rate"
            r" limit|quota exceeded|sending limit|\b[45]\.4\.5\b|\b4\.7\.0\b"
            r".{0,80}(?:rate|limit)",
            _I,
        ),
        N_("sending rate or per-session limit (421/450/451/452)"),
    ),
    # Après un premier refus dans la même connexion, le serveur garde la
    # transaction ouverte et refuse chaque nouvelle commande MAIL : la
    # cause réelle est l'échec qui précède.
    Classe(
        "cascade_503",
        False,
        re.compile(r"Multiple MAIL commands|SMTPSenderRefused: \(503\b", _I),
        N_("'Multiple MAIL' after an earlier failure (503)"),
    ),
    Classe(
        "auth",
        True,
        re.compile(
            r"SMTPAuthenticationError|\(535,|\b5\.7\.8\b|Authentication"
            r" (?:failed|unsuccessful)|Username and Password not accepted",
            _I,
        ),
        N_("authentication refused (535)"),
    ),
    Classe(
        "relay",
        True,
        re.compile(
            r"Relay access denied|relay not permitted|Relaying denied"
            r"|\b5\.7\.1\b.{0,60}relay",
            _I,
        ),
        N_("relay refused"),
    ),
    Classe(
        "sender",
        True,
        re.compile(
            r"not allowed to send emails? as|Sender address rejected|Sender"
            r" verify failed|SMTPSenderRefused: \((?:550|553)\b|header"
            r" From.{0,60}envelope sender",
            _I,
        ),
        N_("sender refused (550/553)"),
    ),
    Classe(
        "recipient",
        True,
        re.compile(
            r"SMTPRecipientsRefused.{0,200}\((?:550|551|553)\b.{0,120}"
            r"(?:\b5\.1\.\d\b|User unknown|does not exist|no such user"
            r"|mailbox unavailable)",
            _I,
        ),
        N_("recipient refused"),
    ),
    Classe(
        "connection",
        False,
        re.compile(
            r"SMTPServerDisconnected|SMTPConnectError|Connection (?:refused"
            r"|timed out|reset)|\btimed out\b|Network is unreachable|Name or"
            r" service not known|Temporary failure in name resolution"
            r"|Unable to connect to SMTP Server",
            _I,
        ),
        N_("SMTP server unreachable"),
    ),
)

# Classe atteinte seulement par le `failure_type` d'un mail.mail :
# l'adresse du destinataire manque ou est mal formée, Odoo n'a rien
# envoyé.
ADRESSE_INVALIDE = Classe(
    "invalid_address", True, None, N_("invalid or missing recipient address")
)

PAR_ID = {classe.id: classe for classe in CLASSES + (ADRESSE_INVALIDE,)}

# Valeurs de `failure_type` (champ de mail.mail présent en 18, absent des
# versions plus anciennes) qui suffisent à classer, sans lire le texte.
# `mail_smtp`, `unknown` et l'absence de valeur — champ vide ou inexistant —
# laissent la décision au texte.
PAR_TYPE = {
    "mail_email_invalid": "invalid_address",
    "mail_email_missing": "invalid_address",
    "mail_from_invalid": "sender",
    "mail_from_missing": "sender",
}

# La dernière exception nommée d'un texte, module retiré :
# « smtplib.SMTPDataError: (452, … » → « SMTPDataError: (452, … ».
RE_CAUSE = re.compile(
    r"(?:\b[A-Za-z_]\w*\.)*\b([A-Za-z_]\w*(?:Error|Exception|Refused"
    r"|Disconnected)): ?"
)
LONGUEUR_CAUSE = 70


def classer(texte, contexte_requis=True):
    """La Classe de la cause d'échec lue dans `texte`, ou None.

    `contexte_requis` : le texte doit aussi parler d'envoi de courriel
    (`RE_CONTEXTE`). C'est le cas d'un enregistrement de journal, qui peut
    venir de n'importe quel module ; un `failure_reason` est déjà un échec
    d'envoi et s'en passe.
    """
    texte = texte or ""
    if contexte_requis and not RE_CONTEXTE.search(texte):
        return None
    for classe in CLASSES:
        if classe.motif.search(texte):
            return classe
    return None


def classer_echec(raison, type_echec=None):
    """La Classe de l'échec d'un mail.mail, ou None.

    `type_echec` (`failure_type`) l'emporte quand il désigne une
    adresse invalide ou un expéditeur manquant ; sinon le texte de
    `raison` (`failure_reason`) décide, sans garde de contexte.
    """
    identifiant = PAR_TYPE.get(type_echec or "")
    if identifiant:
        return PAR_ID[identifiant]
    return classer(raison, contexte_requis=False)


def cause_courte(raison):
    """La cause d'un `failure_reason` en au plus 70 caractères, sans la
    phrase traduite d'Odoo : à partir de la dernière exception nommée
    (`SMTPDataError: (452, …`), sinon la dernière ligne non vide. "" si
    la raison est vide."""
    raison = (raison or "").strip()
    if not raison:
        return ""
    trouvees = list(RE_CAUSE.finditer(raison))
    if trouvees:
        dernier = trouvees[-1]
        texte = dernier.group(1) + ": " + raison[dernier.end() :]
    else:
        lignes = [ligne.strip() for ligne in raison.splitlines()]
        texte = [ligne for ligne in lignes if ligne][-1]
    texte = " ".join(texte.split())
    if len(texte) > LONGUEUR_CAUSE:
        texte = texte[: LONGUEUR_CAUSE - 1] + "…"
    return texte


# Le réglage à regarder, par classe. `sender` dépend de la version : le
# filtre « De » du serveur sortant existe depuis 15, les domaines d'alias
# (expéditeur par défaut, catchall) remplacent les paramètres système
# `mail.default.from` et `mail.catchall.domain` depuis 17.
REGLAGE_LIMITE = N_(
    "System parameter mail.session.batch.size: lower than the provider's"
    " per-connection limit (try 10); also the provider's hourly and daily"
    " sending cap."
)
REGLAGES = {
    "tls": N_(
        "Port and encryption of the outgoing mail server (465 with SSL/TLS,"
        " 587 with STARTTLS) and its certificate; or smtp_port and smtp_ssl"
        " in the Odoo configuration file."
    ),
    "rate_limit": REGLAGE_LIMITE,
    "cascade_503": REGLAGE_LIMITE,
    "auth": N_(
        "Login and password of the outgoing mail server (Test Connection),"
        " or smtp_user and smtp_password in the Odoo configuration file; an"
        " application password where the provider requires one."
    ),
    "relay": N_(
        "Authentication on the outgoing mail server, and a From address in"
        " a domain this server accepts to relay."
    ),
    "recipient": N_(
        "The recipient address itself: the destination server does not"
        " know it."
    ),
    "invalid_address": N_(
        "The recipient address of the mail or of its contact: missing or"
        " malformed."
    ),
    "connection": N_(
        "Host and port of the outgoing mail server (or smtp_server and"
        " smtp_port in the Odoo configuration file), outgoing firewall and"
        " DNS of this host."
    ),
}
REGLAGE_EXPEDITEUR_14 = N_(
    "System parameters mail.default.from and mail.catchall.domain: the From"
    " address must be one the SMTP account may send as."
)
REGLAGE_EXPEDITEUR_16 = N_(
    "From Filter of the outgoing mail server (or from_filter in the Odoo"
    " configuration file), and the system parameters mail.default.from and"
    " mail.catchall.domain: the From address must be one the SMTP account"
    " may send as."
)
REGLAGE_EXPEDITEUR_17 = N_(
    "From Filter of the outgoing mail server (or from_filter in the Odoo"
    " configuration file), and Settings > Technical > Email > Alias Domains"
    " (default from, catchall): the From address must be one the SMTP"
    " account may send as."
)
REGLAGE_EXPEDITEUR = N_(
    "From Filter of the outgoing mail server or from_filter in the Odoo"
    " configuration file (15+); default sender: system parameters"
    " mail.default.from and mail.catchall.domain (up to 16), or Settings >"
    " Technical > Email > Alias Domains (17+)."
)


def reglage(identifiant, version_majeure=None):
    """Le réglage à regarder pour la classe `identifiant` (modèle anglais),
    selon la version majeure d'Odoo quand elle est connue ; "" pour une
    classe inconnue. Sans version, le texte nomme les variantes."""
    if identifiant != "sender":
        return REGLAGES.get(identifiant, "")
    if version_majeure is None:
        return REGLAGE_EXPEDITEUR
    if version_majeure <= 14:
        return REGLAGE_EXPEDITEUR_14
    if version_majeure <= 16:
        return REGLAGE_EXPEDITEUR_16
    return REGLAGE_EXPEDITEUR_17


def version_majeure(texte):
    """Le numéro majeur d'une version d'Odoo (« 18.0.1.3 » → 18, « 16.0 »
    → 16), ou None."""
    trouve = re.match(r"\s*(?:saas~)?(\d+)", str(texte or ""))
    return int(trouve.group(1)) if trouve else None
