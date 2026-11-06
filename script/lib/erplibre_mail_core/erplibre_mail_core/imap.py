# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qui, d'IMAP, ne demande ni stockage ni préférence : lire les réponses
du serveur (en-têtes, LIST, INTERNALDATE, drapeaux), les en-têtes que lisent
les garde-fous, et revendiquer un message sur une connexion déjà ouverte.
L'ouverture de la connexion et la synchronisation restent à l'appelant.

`BODY.PEEK[HEADER.FIELDS (...)]` rend des en-têtes RFC822 bruts, que le
module `email` de la stdlib sait déjà lire — encodages, mots encodés, dates
comprises : `ENVELOPE` n'est pas décodé.
"""

from __future__ import annotations

import email
import email.utils
import imaplib
import re
import time
from dataclasses import dataclass, field
from email.header import decode_header
from email.parser import BytesHeaderParser

from erplibre_mail_core.charset import decode_bytes
from erplibre_mail_core.claim import CLAIM_KEYWORD, ClaimProbe, has_claim
from erplibre_mail_core.i18n import t

# Les en-têtes que lisent les garde-fous des règles de courriel entrant
# (RFC 3834, listes, boucles, pourriels, authentification). `Resent-From`
# reconnaît une redirection revenue chez nous (boucle de redirection) ;
# `Content-Type` de tête reconnaît un rapport de remise (`multipart/report`,
# `message/delivery-status`). Ils restent en mémoire dans
# `HeaderInfo.extra` : la base de l'appelant ne les stocke pas.
EXTRA_HEADERS = (
    "Auto-Submitted",
    "Precedence",
    "List-Id",
    "List-Unsubscribe",
    "Return-Path",
    "Reply-To",
    "X-Auto-Response-Suppress",
    "X-Loop",
    "Authentication-Results",
    "X-Spam-Flag",
    "Content-Type",
    "Resent-From",
)
HEADER_FIELDS = (
    "FROM TO CC SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES "
    + " ".join(h.upper() for h in EXTRA_HEADERS)
)

SPECIAL_USE = {
    "\\Sent": "sent",
    "\\Drafts": "drafts",
    "\\Trash": "trash",
    "\\Junk": "junk",
    "\\Archive": "archive",
    "\\All": "archive",
}

_UID_RE = re.compile(rb"UID\s+(\d+)")
_SIZE_RE = re.compile(rb"RFC822\.SIZE\s+(\d+)")
_FLAGS_RE = re.compile(rb"FLAGS\s+\(([^)]*)\)")
_INTERNALDATE_RE = re.compile(rb'INTERNALDATE\s+"([^"]+)"')
_MODSEQ_RE = re.compile(rb"MODSEQ\s+\((\d+)\)")
_LIST_RE = re.compile(rb'^\(([^)]*)\)\s+("[^"]*"|NIL)\s+(.*)$')


class ImapAuthError(Exception):
    """Le serveur a REFUSÉ le secret. Distinct d'une panne réseau.

    Un refus se répare en rafraîchissant le jeton ou en redemandant le mot
    de passe ; un serveur muet, non. Les confondre ferait rafraîchir un
    jeton valide à chaque coupure de réseau, et boucler.
    """


class ImapError(Exception):
    """Le serveur a refusé, ou a répondu quelque chose d'inattendu."""


@dataclass
class FolderInfo:
    name: str
    display: str = ""
    role: str | None = None
    # `\Noselect` / `\NonExistent` : un NIVEAU de la hiérarchie, pas une
    # boîte. Un fournisseur qui préfixe ses dossiers expose ce préfixe ainsi,
    # simple parent des dossiers qu'il porte. Le SELECTionner répond NO —
    # c'est normal, et le serveur le dit d'avance dans les drapeaux de LIST.
    selectable: bool = True
    # Les drapeaux de la ligne LIST, tels quels. `role` n'en retient que le
    # rôle standard ; un serveur en annonce d'autres, et c'est ce qui permet
    # de reconnaître un dossier qui n'est qu'une VUE sur d'autres.
    attributes: tuple[str, ...] = ()


@dataclass
class SelectInfo:
    uidvalidity: int
    uidnext: int
    exists: int


@dataclass
class HeaderInfo:
    uid: int
    date: int
    size: int
    flags: str
    msgid: str
    frm: str
    to: str
    subject: str
    # Fils de discussion. Bruts : le hachage appartient à la base de
    # l'appelant, seule détentrice du sel.
    in_reply_to: str = ""
    references: str = ""
    # Tous avec défaut : un double de test qui ne les connaît pas
    # construit encore un `HeaderInfo` valide.
    cc: str = ""
    # L'INTERNALDATE du serveur, en secondes UTC ; 0 si inconnue. C'est la
    # date de RÉCEPTION, que l'expéditeur ne choisit pas, contrairement à
    # l'en-tête `Date`.
    internaldate: int = 0
    # Les en-têtes de `EXTRA_HEADERS` présents, clés en
    # minuscules. Plusieurs occurrences sont jointes par "\n" dans l'ordre
    # du message — la première est la plus haute, celle que le dernier MTA
    # a ajoutée — et chacune est dépliée : "\n" n'y sert que de
    # séparateur. Gardés en mémoire seulement, jamais dans la base.
    extra: dict = field(default_factory=dict)
    # From, To et Cc tels que reçus, dépliés, AVANT tout décodage RFC 2047 :
    # les adresses s'analysent sur eux, un libellé encodé y restant un
    # libellé (`rules.model.MessageView`). None : la source n'a que la
    # forme décodée. Jamais dans la base.
    frm_raw: str | None = None
    to_raw: str | None = None
    cc_raw: str | None = None


# Le plafond des en-têtes d'INBOX qu'un rapport transporte. Une première
# synchronisation, ou une UIDVALIDITY changée, rend toute la boîte « neuve » :
# sans plafond, le rapport garderait en mémoire des dizaines de milliers
# d'en-têtes que personne ne traitera.
INBOX_REPORT_MAX = 500


def decode_header_value(raw: str | None) -> str:
    """Un en-tête RFC 2047 rendu en texte lisible, sans jamais lever."""
    if not raw:
        return ""
    try:
        parts = decode_header(raw)
    except Exception:
        # `raw` vient du serveur : un en-tête mal formé ne doit jamais faire
        # tomber l'affichage d'un message.
        return str(raw)
    out = []
    for value, charset in parts:
        if isinstance(value, bytes):
            out.append(decode_bytes(value, charset))
        else:
            out.append(value)
    return "".join(out).strip()


def decode_mailbox(name: str) -> str:
    """Nom de boîte en UTF-7 modifié (RFC 3501) rendu lisible.

    Sur entrée invalide on rend le nom d'origine : un affichage imparfait vaut
    mieux qu'un dossier qu'on n'arrive plus à sélectionner.
    """
    if "&" not in name:
        return name
    try:
        out = []
        for chunk in name.split("&"):
            if not out:
                out.append(chunk)
                continue
            encoded, sep, rest = chunk.partition("-")
            if not sep:
                raise ValueError(t("mail_err_unterminated_ampersand"))
            if encoded == "":
                out.append("&" + rest)
            else:
                pad = "=" * (-len(encoded) % 4)
                decoded = (encoded.replace(",", "/") + pad).encode("ascii")
                import base64

                out.append(
                    base64.b64decode(decoded).decode("utf-16-be") + rest
                )
        return "".join(out)
    except Exception:
        # Nom de boîte mal formé : on garde l'original plutôt que de perdre
        # l'accès au dossier pour une simple erreur d'affichage.
        return name


def parse_list_line(line: bytes) -> FolderInfo:
    """Une ligne de réponse LIST → nom, nom affichable, rôle."""
    match = _LIST_RE.match(line.strip())
    if not match:
        raw_name = line.decode("utf-8", "replace").strip().strip('"')
        return FolderInfo(name=raw_name, display=decode_mailbox(raw_name))
    flags = match.group(1).decode("ascii", "replace").split()
    name = match.group(3).decode("utf-8", "replace").strip().strip('"')
    role = next((SPECIAL_USE[f] for f in flags if f in SPECIAL_USE), None)
    if role is None and name.upper() == "INBOX":
        role = "inbox"
    bas = {f.lower() for f in flags}
    return FolderInfo(
        name=name,
        display=decode_mailbox(name),
        role=role,
        selectable=not (bas & {"\\noselect", "\\nonexistent"}),
        attributes=tuple(flags),
    )


def internaldate_epoch(meta: bytes) -> int:
    """L'INTERNALDATE d'une ligne FETCH, en secondes UTC ; 0 si absente ou
    illisible.

    `imaplib.Internaldate2tuple` lit le nom du mois sans passer par la
    locale, ce que `strptime("%b")` ne garantit pas. Il rend un temps LOCAL
    qui porte son `tm_isdst`, et `time.mktime` le respecte : l'aller-retour
    reste exact jusque dans l'heure qui se répète au passage à l'heure
    normale.
    """
    match = _INTERNALDATE_RE.search(meta)
    if not match:
        return 0
    try:
        tt = imaplib.Internaldate2tuple(
            b'INTERNALDATE "' + match.group(1) + b'"'
        )
        return int(time.mktime(tt)) if tt is not None else 0
    except Exception:
        # Un mois inconnu lève KeyError, un champ hors bornes ValueError ou
        # OverflowError. Une date de réception illisible ne vaut pas la
        # perte du message : 0 dit « inconnue », et les garde-fous la
        # traitent comme telle.
        return 0


def extra_headers(msg) -> dict:
    """Les en-têtes d'`EXTRA_HEADERS` présents, clés en minuscules.

    Chaque occurrence est dépliée — une valeur pliée porte un CRLF — puis
    les occurrences sont jointes par un saut de ligne, dans l'ordre du
    message : la première est la plus haute, celle du dernier MTA. Les
    valeurs ne sont pas décodées RFC 2047 : ce sont des jetons machine, et
    `str()` absorbe la forme `Header` que prend un en-tête 8 bits.
    """
    out = {}
    for nom in EXTRA_HEADERS:
        valeurs = msg.get_all(nom)
        if valeurs:
            out[nom.lower()] = "\n".join(
                " ".join(str(v).split()) for v in valeurs
            )
    return out


def parse_fetch_headers(data: list) -> list[HeaderInfo]:
    """Réponse FETCH d'en-têtes → une liste de `HeaderInfo`."""
    parser = BytesHeaderParser()
    out = []
    for index, item in enumerate(data):
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        prefix, raw_headers = item[0], item[1]
        # Les attributs peuvent SUIVRE le littéral au lieu de le précéder :
        # RFC 3501 n'impose aucun ordre, et `imaplib` rend alors la fin de la
        # ligne dans l'entrée suivante, hors du tuple. Ne lire que le préfixe
        # ferait disparaître le message SANS erreur — et comme le moteur
        # avance `last_uid` derrière, il ne serait jamais réessayé.
        trailer = b""
        if index + 1 < len(data) and isinstance(
            data[index + 1], (bytes, bytearray)
        ):
            trailer = bytes(data[index + 1])
        meta = bytes(prefix) + b" " + trailer
        uid_match = _UID_RE.search(meta)
        if not uid_match:
            continue
        size_match = _SIZE_RE.search(meta)
        flags_match = _FLAGS_RE.search(meta)
        msg = parser.parsebytes(raw_headers)
        date_raw = msg.get("Date")
        try:
            # `str()` d'abord : un `Date:` porteur d'octets 8 bits bruts —
            # vu en boîte réelle — fait renvoyer un `Header` et non une
            # chaîne, et `parsedate_to_datetime` y lève un AttributeError
            # que ce `except` ne rattrapait pas. Une seule date illisible
            # emportait alors la synchro du dossier ENTIER.
            stamp = (
                int(
                    email.utils.parsedate_to_datetime(
                        str(date_raw)
                    ).timestamp()
                )
                if date_raw
                else 0
            )
        except (TypeError, ValueError, AttributeError, OverflowError):
            # Une date est une commodité d'affichage : aucune valeur
            # d'en-tête ne justifie de perdre le message.
            stamp = 0

        # `str()` comme pour la date : un en-tête porteur d'octets 8 bits
        # revient en `Header`, sur lequel `.strip()` lèverait — et la
        # synchronisation du dossier ENTIER tomberait, comme elle l'a déjà
        # fait pour une seule date illisible.
        def entete(nom: str) -> str:
            valeur = msg.get(nom)
            return str(valeur).strip() if valeur else ""

        # Non décodé, déplié : un libellé RFC 2047 qui cache « @ » ou « , »
        # y reste un mot encodé et ne devient pas une adresse.
        def brut(nom: str) -> str:
            valeur = msg.get(nom)
            return " ".join(str(valeur).split()) if valeur else ""

        out.append(
            HeaderInfo(
                uid=int(uid_match.group(1)),
                date=stamp,
                size=int(size_match.group(1)) if size_match else 0,
                flags=(
                    flags_match.group(1).decode("ascii", "replace")
                    if flags_match
                    else ""
                ),
                msgid=entete("Message-ID"),
                frm=decode_header_value(msg.get("From")),
                to=decode_header_value(msg.get("To")),
                subject=decode_header_value(msg.get("Subject")),
                in_reply_to=entete("In-Reply-To"),
                references=entete("References"),
                cc=decode_header_value(msg.get("Cc")),
                internaldate=internaldate_epoch(meta),
                extra=extra_headers(msg),
                frm_raw=brut("From"),
                to_raw=brut("To"),
                cc_raw=brut("Cc"),
            )
        )
    return out


def _lignes_fetch(data):
    """Les lignes FETCH de `data` qui portent un UID ET des FLAGS, dans
    l'ordre : `(uid, drapeaux, modseq)`, `modseq` None quand la ligne n'en
    porte pas.

    Une ligne sans FLAGS (un FETCH non sollicité `(UID u MODSEQ (m))`) ne
    dit rien des drapeaux ; une ligne sans UID (un FETCH non sollicité
    numéroté par séquence) ne désigne aucun message sûr. Les deux sont
    ignorées.
    """
    for line in data or ():
        raw = line[0] if isinstance(line, tuple) else line
        if not isinstance(raw, (bytes, bytearray)):
            continue
        uid_match = _UID_RE.search(raw)
        flags_match = _FLAGS_RE.search(raw)
        if not uid_match or not flags_match:
            continue
        modseq_match = _MODSEQ_RE.search(raw)
        yield (
            int(uid_match.group(1)),
            flags_match.group(1).decode("ascii", "replace"),
            int(modseq_match.group(1)) if modseq_match else None,
        )


def _ligne_de(data, uid: int):
    """`(drapeaux, modseq)` de la DERNIÈRE ligne de `data` qui porte `uid`
    et des FLAGS, ou None.

    La dernière, parce que `uid()` rend aussi les FETCH non sollicités
    reçus avant la réponse, qui portent des drapeaux plus anciens. Le
    MODSEQ est celui de CETTE ligne et jamais le plus grand vu : associé à
    des drapeaux plus anciens, un MODSEQ plus récent ferait réussir un
    STORE conditionnel sur un mot-clé posé entre les deux.
    """
    trouve = None
    for numero, flags, modseq in _lignes_fetch(data):
        if numero == uid:
            trouve = (flags, modseq)
    return trouve


def _uid_set(text) -> set[int]:
    """Les UID d'un ensemble IMAP sans `*` (« 1,3:5 »), vide s'il est
    illisible."""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("ascii", "replace")
    out: set[int] = set()
    for morceau in str(text or "").split(","):
        debut, _, fin = morceau.strip().partition(":")
        try:
            bas = int(debut)
            haut = int(fin) if fin else bas
        except ValueError:
            continue
        if haut < bas:
            bas, haut = haut, bas
        out.update(range(bas, haut + 1))
    return out


class ImapConnection:
    """Une connexion `imaplib` déjà authentifiée : SELECT, lecture des
    drapeaux et revendication d'un message.

    Le client est injecté : connexion TLS en production, double en test.
    L'état de la revendication est propre à la connexion.
    """

    def __init__(self, client) -> None:
        self.client = client
        # Les capacités lues APRÈS l'authentification, à la première sonde
        # de revendication ; `imaplib` ne remplit `capabilities` qu'avant,
        # et bien des serveurs n'y annoncent pas encore CONDSTORE.
        self._capacites: frozenset[str] | None = None
        # Vrai quand le serveur annonce CONDSTORE mais en refuse la
        # syntaxe (BAD) : la connexion revendique alors en mode simple.
        self._sans_condstore = False

    @staticmethod
    def _ok(result, label: str):
        status, data = result
        if status != "OK":
            raise ImapError(
                f"{label} {t('mail_err_server_replied')} {status} ({data!r})"
            )
        return data

    def select(self, folder: str) -> SelectInfo:
        data = self._ok(self.client.select(f'"{folder}"'), f"SELECT {folder}")
        exists = int(data[0]) if data and data[0] else 0
        return SelectInfo(
            uidvalidity=int(
                self._first(self.client.response("UIDVALIDITY")) or 0
            ),
            uidnext=int(self._first(self.client.response("UIDNEXT")) or 0),
            exists=exists,
        )

    @staticmethod
    def _first(response) -> bytes | None:
        _, data = response
        return data[0] if data and data[0] else None

    def fetch_flags(self, uids: list[int]) -> list[tuple[int, str]]:
        """Les drapeaux des `uids` du dossier sélectionné, `(uid, drapeaux)`.

        Une ligne FETCH sans FLAGS ne dit rien des drapeaux et est ignorée :
        une fois CONDSTORE activé dans la session, le serveur peut glisser
        des FETCH non sollicités `(UID u MODSEQ (m))`, et les lire comme
        « aucun drapeau » effacerait ceux de la base (un message lu
        redeviendrait non lu). Pour un même UID, la dernière ligne
        l'emporte : `uid()` rend aussi les FETCH accumulés avant la
        réponse, plus anciens qu'elle.
        """
        if not uids:
            return []
        data = self._ok(
            self.client.uid(
                "FETCH", ",".join(str(u) for u in uids), "(UID FLAGS)"
            ),
            "FETCH FLAGS",
        )
        out: dict[int, str] = {}
        for uid, flags, _modseq in _lignes_fetch(data):
            out[uid] = flags
        return list(out.items())

    # -- revendication d'un message ----------------------------------

    def _capacites_auth(self) -> frozenset[str]:
        """Les capacités du serveur lues par `CAPABILITY` une fois
        authentifié, en majuscules, gardées pour la connexion.

        Un échec de la commande retombe sur la liste d'avant connexion
        (`self.client.capabilities`), sans la garder : la sonde suivante
        réessaie.
        """
        if self._capacites is not None:
            return self._capacites
        try:
            typ, data = self.client.capability()
        except imaplib.IMAP4.abort:
            raise
        except imaplib.IMAP4.error:
            typ, data = "NO", []
        derniere = next(
            (d for d in reversed(data or ()) if d is not None), None
        )
        if typ != "OK" or derniere is None:
            return frozenset(
                str(c).upper() for c in (self.client.capabilities or ())
            )
        if isinstance(derniere, (bytes, bytearray)):
            derniere = bytes(derniere).decode("ascii", "replace")
        self._capacites = frozenset(str(derniere).upper().split())
        return self._capacites

    def _permanent_flags(self) -> tuple[str, ...] | None:
        """Les drapeaux que le dossier sélectionné garde d'une session à
        l'autre (code `PERMANENTFLAGS` du SELECT), None s'il n'en annonce
        pas : RFC 3501 dit alors que tout drapeau est permanent."""
        _, data = self.client.response("PERMANENTFLAGS")
        if not data or data[0] is None:
            return None
        brut = data[0]
        if isinstance(brut, (bytes, bytearray)):
            brut = bytes(brut).decode("ascii", "replace")
        return tuple(str(brut).strip().strip("()").split())

    def claim_probe(
        self, folder: str, uid: int, *, uidvalidity: int
    ) -> ClaimProbe:
        """Lit, sans rien écrire, si le message `uid` de `folder` peut être
        revendiqué, et dans quel mode.

        Le SELECT dit l'UIDVALIDITY (autre que `uidvalidity` :
        `renumbered`, avant tout le reste), `PERMANENTFLAGS` (sans `\\*` ni le mot-clé :
        `unsupported`, aucun FETCH) et `NOMODSEQ`. Le mode est `atomic`
        quand le serveur annonce CONDSTORE (ou QRESYNC) une fois
        authentifié, sans `NOMODSEQ` ni refus antérieur de la syntaxe, et
        que la ligne FETCH porte un MODSEQ ; `plain` sinon. Un BAD au
        FETCH avec MODSEQ fait passer la connexion en mode simple. Sans
        ligne FETCH de cet UID : `gone` ; mot-clé posé : `present` ;
        sinon `free`.

        Une boîte passée en lecture seule (`[READ-ONLY]`) n'est PAS un
        serveur sans revendication : la sonde lève `ImapError`, après
        avoir retiré `READ-ONLY` des réponses du client, sans quoi
        `imaplib` lèverait sur toute commande suivante de ce client.
        """
        try:
            info = self.select(folder)
        except imaplib.IMAP4.readonly as exc:
            self.client.untagged_responses.pop("READ-ONLY", None)
            raise ImapError(t("mail_err_claim_read_only")) from exc
        # Lu AVANT tout `response()` : `imaplib` rend `[None]` pour un code
        # absent comme pour un code présent sans donnée.
        nomodseq = "NOMODSEQ" in self.client.untagged_responses
        perm = self._permanent_flags()
        atomique = bool(
            {"CONDSTORE", "QRESYNC"} & self._capacites_auth()
            and not nomodseq
            and not self._sans_condstore
        )
        mode = "atomic" if atomique else "plain"
        if info.uidvalidity != uidvalidity:
            return ClaimProbe("renumbered", mode)
        if perm is not None:
            admis = {p.lower() for p in perm}
            if "\\*" not in admis and CLAIM_KEYWORD.lower() not in admis:
                return ClaimProbe("unsupported", "none", reason="keywords")
        data = None
        if atomique:
            try:
                data = self._ok(
                    self.client.uid("FETCH", str(uid), "(UID FLAGS MODSEQ)"),
                    "FETCH CLAIM",
                )
            except imaplib.IMAP4.abort:
                raise
            except imaplib.IMAP4.error:
                self._sans_condstore = True
                mode = "plain"
        if data is None:
            mode = "plain"
            data = self._ok(
                self.client.uid("FETCH", str(uid), "(UID FLAGS)"),
                "FETCH CLAIM",
            )
        ligne = _ligne_de(data, uid)
        if ligne is None:
            return ClaimProbe("gone", mode)
        drapeaux, modseq = ligne
        if mode == "atomic" and modseq is None:
            mode = "plain"
        if mode != "atomic":
            modseq = None
        if has_claim(drapeaux):
            return ClaimProbe("present", mode, modseq)
        return ClaimProbe("free", mode, modseq)

    def claim_store(self, uid: int, probe: ClaimProbe) -> str:
        """Pose le mot-clé sur `uid` dans le dossier que la sonde vient de
        sélectionner, et rend l'un de `claim.STORE_RESULTS`.

        En mode `atomic`, le STORE est conditionnel (RFC 7162) :
        `UNCHANGEDSINCE <modseq de la sonde>`. Un message changé depuis
        n'est pas modifié, et le serveur le nomme dans un code
        `[MODIFIED …]` de sa réponse étiquetée, qu'`imaplib` range dans
        `untagged_responses` comme un code non étiqueté : `modified`. Un
        BAD à cette syntaxe (serveur qui annonce CONDSTORE et le gère mal)
        fait passer la connexion en mode simple et rend `retry`, rien
        n'ayant été appliqué. Un NO, ou un BAD en mode simple, lève
        `ImapError`.

        Pas de `.SILENT` : la ligne FETCH que le serveur renvoie dit si le
        mot-clé est GARDÉ (`stored`) ou jeté par un serveur qui ignore les
        mots-clés (`refused`) ; un OK nu ne prouve ni l'un ni l'autre, ni
        même que le message existe encore. Sans ligne, les drapeaux sont
        relus : UID absent, `gone` ; relecture refusée (NO, BAD),
        `unknown`, car le STORE accepté a peut-être posé le mot-clé. En
        mode simple, deux machines entre la sonde et le STORE l'une de
        l'autre se croient toutes deux propriétaires : c'est la limite de
        ce mode.

        Une panne du lien traverse telle quelle.
        """
        # Un MODIFIED laissé par une commande précédente : `imaplib` ne
        # vide que OK, NO et BAD avant chaque commande.
        self.client.response("MODIFIED")
        atomique = probe.mode == "atomic" and probe.modseq is not None
        args = [str(uid)]
        if atomique:
            args.append(f"(UNCHANGEDSINCE {int(probe.modseq)})")
        args += ["+FLAGS", f"({CLAIM_KEYWORD})"]
        try:
            typ, data = self.client.uid("STORE", *args)
        except imaplib.IMAP4.abort:
            raise
        except imaplib.IMAP4.error as exc:
            if atomique:
                self._sans_condstore = True
                return "retry"
            raise ImapError(
                f"STORE CLAIM {t('mail_err_server_replied')} BAD"
            ) from exc
        if typ != "OK":
            raise ImapError(
                f"STORE CLAIM {t('mail_err_server_replied')} {typ}"
            )
        _, modifies = self.client.response("MODIFIED")
        for valeur in modifies or ():
            if valeur is not None and uid in _uid_set(valeur):
                return "modified"
        ligne = _ligne_de(data, uid)
        if ligne is None:
            try:
                relus = dict(self.fetch_flags([uid]))
            except ImapError:
                # Le STORE est accepté : le mot-clé est peut-être posé.
                return "unknown"
            if uid not in relus:
                return "gone"
            return "stored" if has_claim(relus[uid]) else "refused"
        return "stored" if has_claim(ligne[0]) else "refused"


def xoauth2_chain(user: str, token: str) -> bytes:
    """La chaîne SASL de XOAUTH2, telle que les serveurs l'attendent.

    Le format est imposé : `user=<compte>^Aauth=Bearer <jeton>^A^A`, où
    `^A` est l'octet 0x01. Une seule fonction pour IMAP et SMTP — deux
    copies finiraient par diverger d'un octet, et le refus qui s'ensuit ne
    dit jamais lequel.
    """
    return f"user={user}\x01auth=Bearer {token}\x01\x01".encode()
