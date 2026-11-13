#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La seule couche qui parle vraiment IMAP.

Choix qui explique tout le reste du fichier : on ne décode PAS `ENVELOPE`.
`BODY.PEEK[HEADER.FIELDS (...)]` rend des en-têtes RFC822 bruts, que le module
`email` de la stdlib sait déjà lire — encodages, mots encodés, dates comprises.
Analyser `ENVELOPE` à la main coûterait cent lignes de plus, toutes fausses
sur un cas limite ou l'autre.

`BODY.PEEK` et non `BODY` : lire un message dans le TUI ne doit pas le marquer
lu sur le serveur à l'insu de l'utilisateur.

En SSL comme en STARTTLS, le certificat du serveur est vérifié (chaîne et
nom), sauf si le compte en épingle l'empreinte pour ce point d'accès : seule
cette empreinte est alors acceptée (`erplibre_mail_core.tls`).

Les lecteurs de réponses, les en-têtes des garde-fous, les classes de données
et la revendication viennent du noyau (`erplibre_mail_core.imap`) et restent
importables ici sous leur nom ; ce module garde l'ouverture de la connexion
et le reste du transport.
"""

from __future__ import annotations

import imaplib
import ssl

from script.todo.mail import _core_path  # noqa: F401

# isort: split
from erplibre_mail_core import tls
from erplibre_mail_core.imap import (  # noqa: F401
    EXTRA_HEADERS,
    HEADER_FIELDS,
    SPECIAL_USE,
    FolderInfo,
    HeaderInfo,
    ImapAuthError,
    ImapConnection,
    ImapError,
    SelectInfo,
    decode_header_value,
    decode_mailbox,
    extra_headers,
    fail_fast,
    internaldate_epoch,
    parse_fetch_headers,
    parse_list_line,
    starttls_context,
    xoauth2_chain,
)

from script.todo.todo_i18n import t

# Les échecs après lesquels la socket reste saine (`_abandon`). Liés à
# l'import : `imaplib.IMAP4` remplacé par un double ne les change pas.
_IMAP_ABORT = imaplib.IMAP4.abort
_POLITE_FAILURES = (imaplib.IMAP4.error, ImapAuthError, UnicodeEncodeError)


class ImaplibTransport(ImapConnection):
    """`ImapTransport` réalisé sur `imaplib`. Le client est injecté : les tests
    passent un double, la production passe une connexion TLS. SELECT,
    lecture des drapeaux et revendication viennent d'`ImapConnection`."""

    def list_folders(self) -> list[FolderInfo]:
        data = self._ok(self.client.list(), "LIST")
        return [parse_list_line(line) for line in data if line]

    def range_par_etiquettes(self) -> bool:
        """Vrai si le serveur annonce ranger par ÉTIQUETTES.

        `X-GM-EXT-1` est le seul discriminant qui vaille. Un nom de dossier
        n'en est pas un : son préfixe et sa casse appartiennent au
        fournisseur et changent avec la langue du compte. Et l'attribut
        `\\All` seul n'en est pas un non plus : ailleurs il désigne une
        archive ordinaire, dont les messages sont DISTINCTS de ceux de la
        boîte de réception.

        Ce que cela change : chez un tel serveur, un message n'est détenu
        qu'une fois et les dossiers en sont des vues, donc certains ne font
        que redire le contenu d'un autre (voir `VUES_REDONDANTES`).
        """
        return "X-GM-EXT-1" in (self.client.capabilities or ())

    def search_uids(self, since_uid: int) -> list[int]:
        data = self._ok(
            self.client.uid("SEARCH", None, f"UID {since_uid}:*"), "SEARCH"
        )
        raw = (data[0] or b"").split()
        # `UID n:*` rend toujours au moins un UID, même inférieur à n quand la
        # boîte est plus courte : on refiltre côté client.
        return [int(u) for u in raw if int(u) >= since_uid]

    def search(self, query: str, limit: int = 500) -> list[int]:
        """Les UID que LE SERVEUR trouve dans le dossier sélectionné.

        Une seule clé, `TEXT` : elle couvre les en-têtes et le corps, donc
        un sur-ensemble de ce que la recherche locale compare.

        Le critère part en OCTETS, terme encodé en UTF-8 dans la chaîne
        citée. `imaplib` encode ses arguments `str` en ASCII : un terme
        accentué lèverait `UnicodeEncodeError` avant d'atteindre le serveur.
        `CHARSET UTF-8` n'accompagne que les termes qui en ont besoin — un
        serveur ancien peut répondre BAD à un jeu de caractères qu'il ne
        connaît pas, et l'ASCII n'en demande aucun.

        Les plus récents d'abord, comme la recherche locale, et le même
        plafond.
        """
        terme = (query or "").strip()
        if not terme:
            # Chercher la chaîne vide rendrait toute la boîte, ce qui n'est
            # pas une recherche — et coûterait un aller-retour pour rien.
            return []
        # Un guillemet non échappé couperait la chaîne IMAP en deux et
        # ferait lire la suite comme une autre clé de recherche.
        citation = terme.replace("\\", "\\\\").replace('"', '\\"')
        critere = f'TEXT "{citation}"'.encode("utf-8")
        entete = ("CHARSET", "UTF-8") if not terme.isascii() else (None,)
        try:
            data = self._ok(
                self.client.uid("SEARCH", *entete, critere), "SEARCH"
            )
        except ImapError:
            raise
        except Exception as exc:
            raise ImapError(
                f"{t('mail_err_server_search_failed')} {exc}"
            ) from exc
        uids = [int(u) for u in (data[0] or b"").split()]
        return sorted(uids, reverse=True)[:limit]

    def fetch_headers(self, uids: list[int]) -> list[HeaderInfo]:
        if not uids:
            return []
        spec = (
            "(UID FLAGS INTERNALDATE RFC822.SIZE"
            f" BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})])"
        )
        data = self._ok(
            self.client.uid("FETCH", ",".join(str(u) for u in uids), spec),
            "FETCH HEADERS",
        )
        return parse_fetch_headers(data)

    def fetch_body(self, uid: int) -> bytes:
        data = self._ok(
            self.client.uid("FETCH", str(uid), "(BODY.PEEK[])"), "FETCH BODY"
        )
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                return item[1]
        raise ImapError(f"{t('mail_err_no_body_for_uid')} {uid}")

    def move(self, uids: list[int], target: str) -> bool:
        """Déplace des messages vers `target`, dans l'ordre qui protège.

        IMAP n'a pas de verbe « déplacer » que tous les serveurs
        connaissent : le chemin portable est COPY, puis `\\Deleted` sur la
        source, puis EXPUNGE.

        L'ORDRE n'est pas négociable. La copie d'abord : son échec arrête
        tout, et le message reste où il est. L'inverse — marquer supprimé
        puis découvrir que la copie ne passe pas — donnerait le pire
        résultat possible, un message retiré de sa source sans être arrivé
        nulle part.

        Le retrait de la source passe par `UID EXPUNGE`, qui NOMME ce qu'il
        retire. L'EXPUNGE nu emporterait tous les messages marqués supprimés
        du dossier, y compris ceux qu'un autre client a marqués ailleurs :
        un client de courriel n'a pas le droit de détruire ce qu'il n'a pas
        déplacé. Un serveur sans UIDPLUS ne permet pas ce geste — le message
        reste alors dans la source, marqué supprimé, et la fonction rend
        `False` pour que l'appelant puisse le dire.
        """
        if not uids:
            return True
        liste = ",".join(str(u) for u in uids)
        try:
            self._ok(self.client.uid("COPY", liste, target), "COPY")
        except ImapError:
            raise
        except Exception as exc:
            raise ImapError(f"{t('mail_err_move_failed')} {exc}") from exc
        return self.discard(uids)

    def discard(self, uids: list[int]) -> bool:
        """Retire du dossier sélectionné les messages NOMMÉS, et dit s'il a
        pu le faire.

        Le second temps de tout déplacement : la copie est arrivée quelque
        part, la source n'a plus lieu d'être. Séparé de `move` parce qu'un
        déplacement entre DEUX comptes ne peut pas copier — il dépose chez
        l'autre par APPEND, puis appelle ceci.

        `UID EXPUNGE` nomme ce qu'il retire. Sans UIDPLUS il ne reste que
        l'EXPUNGE nu, qui emporterait aussi ce qu'un autre client a marqué
        ailleurs dans ce dossier : la fonction s'en abstient, laisse les
        messages barrés sur place, et rend `False` pour que l'appelant
        puisse le dire.
        """
        if not uids:
            return True
        liste = ",".join(str(u) for u in uids)
        try:
            self._ok(
                self.client.uid("STORE", liste, "+FLAGS", "(\\Deleted)"),
                "STORE +FLAGS",
            )
            if "UIDPLUS" not in self.client.capabilities:
                return False
            self._ok(self.client.uid("EXPUNGE", liste), "UID EXPUNGE")
        except ImapError:
            raise
        except Exception as exc:
            raise ImapError(f"{t('mail_err_move_failed')} {exc}") from exc
        return True

    def empty_folder(self, folder: str) -> int:
        """Détruit DÉFINITIVEMENT tout le contenu de `folder`, et rend le
        nombre de messages retirés.

        C'est le seul geste du client qui ne se répare pas : IMAP n'a pas de
        corbeille pour ce qui sort d'une corbeille. L'appelant demande
        confirmation ; cette méthode, elle, ne discute pas.

        `move` refuse l'EXPUNGE nu parce qu'il emporterait des messages
        qu'elle n'a pas nommés. Ici la question ne se pose pas : le dossier
        est vidé ENTIER, donc tout ce qui y porte `\\Deleted` est soit ce
        que cette méthode vient de marquer, soit ce qu'un autre client a
        marqué dans ce même dossier — que le geste détruit de toute façon.
        Un message livré après le relevé des UID n'est, lui, pas marqué, et
        survit.
        """
        self.select(folder)
        uids = self.search_uids(1)
        if not uids:
            return 0
        liste = ",".join(str(u) for u in uids)
        try:
            self._ok(
                self.client.uid("STORE", liste, "+FLAGS", "(\\Deleted)"),
                "STORE +FLAGS",
            )
            if "UIDPLUS" in self.client.capabilities:
                self._ok(self.client.uid("EXPUNGE", liste), "UID EXPUNGE")
            else:
                self._ok(self.client.expunge(), "EXPUNGE")
        except ImapError:
            raise
        except Exception as exc:
            raise ImapError(f"{t('mail_err_empty_failed')} {exc}") from exc
        return len(uids)

    def store_flags(self, uid: int, add: list[str], remove: list[str]) -> None:
        if add:
            self._ok(
                self.client.uid(
                    "STORE", str(uid), "+FLAGS", f"({' '.join(add)})"
                ),
                "STORE +FLAGS",
            )
        if remove:
            self._ok(
                self.client.uid(
                    "STORE", str(uid), "-FLAGS", f"({' '.join(remove)})"
                ),
                "STORE -FLAGS",
            )

    def store_flags_all(self, add: list[str], remove: list[str]) -> None:
        """Pose ou retire des drapeaux sur TOUT le dossier sélectionné.

        `1:*` en UID : la plage ouverte évite d'énumérer des dizaines de
        milliers d'identifiants dans une commande, qu'un serveur peut
        refuser pour sa seule longueur.
        """
        if add:
            self._ok(
                self.client.uid(
                    "STORE", "1:*", "+FLAGS", f"({' '.join(add)})"
                ),
                "STORE +FLAGS 1:*",
            )
        if remove:
            self._ok(
                self.client.uid(
                    "STORE", "1:*", "-FLAGS", f"({' '.join(remove)})"
                ),
                "STORE -FLAGS 1:*",
            )

    def create_folder(self, name: str) -> None:
        self._ok(self.client.create(f'"{name}"'), f"CREATE {name}")

    def rename_folder(self, ancien: str, nouveau: str) -> None:
        self._ok(
            self.client.rename(f'"{ancien}"', f'"{nouveau}"'),
            f"RENAME {ancien}",
        )

    def delete_folder(self, name: str) -> None:
        """Détruit le dossier ET son contenu sur le SERVEUR.

        IMAP n'a pas de corbeille pour les dossiers : ce qui part ici ne se
        récupère que depuis une sauvegarde du serveur. L'appelant demande
        confirmation ; cette méthode, elle, ne discute pas.
        """
        self._ok(self.client.delete(f'"{name}"'), f"DELETE {name}")

    def append(
        self, folder: str, raw: bytes, flags: list[str], date=None
    ) -> None:
        """Dépose un message dans `folder`.

        `date` est la date INTERNE, celle que le serveur donne au message
        déposé. Sans elle il l'horodate à maintenant, et un message venu
        d'un autre compte remonterait en tête de la boîte comme s'il
        arrivait à l'instant.

        Un APPEND accepté ne prouve pas à lui seul que le message est
        rangé là où on croit : c'est `contient_message_id` qui le
        confirme, et c'est lui qu'interroge tout ce qui détruit ensuite la
        source.

        Toute panne du lien sort en `ImapError`, comme un refus du
        serveur : l'appelant n'a qu'un genre d'échec à connaître.
        """
        try:
            self._ok(
                self.client.append(
                    f'"{folder}"',
                    f"({' '.join(flags)})",
                    self._date_interne(date),
                    raw,
                ),
                f"APPEND {folder}",
            )
        except ImapError:
            raise
        except Exception as exc:
            raise ImapError(f"APPEND {folder} : {exc}") from exc

    @staticmethod
    def _date_interne(date):
        """L'horodatage IMAP d'une date en secondes, ou rien.

        `imaplib` accepte plusieurs formes ; celle qu'il fabrique lui-même
        est la seule dont la mise en forme est sûre sur toutes les
        locales.
        """
        if date is None:
            return None
        import imaplib

        try:
            return imaplib.Time2Internaldate(date)
        except Exception:
            # Une date aberrante ne doit pas empêcher le dépôt : le serveur
            # horodatera à maintenant, ce qui est faux mais pas perdu.
            return None

    def contient_message_id(self, folder: str, msgid: str) -> bool:
        """Vrai si `folder` contient déjà un message portant ce Message-ID.

        Sert à CONFIRMER un dépôt quand le serveur n'a pas nommé ce qu'il
        rangeait. La clé est `HEADER Message-ID`, pas `TEXT` : `TEXT`
        trouverait aussi une réponse qui cite ce Message-ID dans son
        `In-Reply-To`, et confirmer un dépôt qui n'a pas eu lieu ferait
        détruire la source.

        Un Message-ID vide ne prouve rien et rend `False` : c'est ce que
        doit faire une vérification qui n'a rien à vérifier.
        """
        if not msgid:
            return False
        self.select(folder)
        critere = msgid.encode("utf-8")
        data = self._ok(
            self.client.uid(
                "SEARCH", None, b'HEADER Message-ID "' + critere + b'"'
            ),
            "SEARCH HEADER",
        )
        return bool((data[0] or b"").split())

    def logout(self) -> None:
        """LOGOUT poli, puis la socket fermée quoi qu'il arrive ; ne lève
        jamais.

        `imaplib` ne ferme la socket qu'après un LOGOUT réussi. Sur un lien
        abandonné ou coupé, LOGOUT lève : seule la socket se ferme, sans
        attendre de réponse.
        """
        try:
            self.client.logout()
            return
        except Exception:
            # Lien abandonné ou coupé : la fermeture de la socket suffit.
            pass
        try:
            self.client.shutdown()
        except Exception:
            # Déjà fermée : rien à rendre.
            pass


def _delai_lecture() -> int:
    """Le délai d'une lecture IMAP, en secondes.

    Il borne CHAQUE lecture, pas la passe : un LIST qui dépasse abandonne
    le lien (`fail_fast`) : toute commande suivante y échoue aussitôt sans
    rien envoyer au serveur. Réglable parce que 30 secondes
    suffisent partout sauf sur les boîtes les plus chargées.

    Une préférence illisible ne doit pas empêcher de se connecter : toute
    valeur qui n'est pas un entier positif retombe sur le défaut.
    """
    defaut = 30
    try:
        from script.todo import todo_prefs

        valeur = int(todo_prefs.get("mail_timeout_sec", defaut))
    except Exception:
        return defaut
    return valeur if valeur > 0 else defaut


def _abandon(client, exc: BaseException) -> None:
    """Ferme `client` après un échec, sans jamais lever.

    Un refus du serveur (`IMAP4.error` hors `abort`, `ImapAuthError`) ou
    un mot de passe non ASCII, qui n'est jamais parti, laissent une
    socket saine : LOGOUT la ferme poliment. Toute autre panne (`abort`,
    délai, coupure) peut l'avoir laissée morte, et LOGOUT y attendrait un
    délai de lecture entier : seule la socket est fermée.
    """
    poli = isinstance(exc, _POLITE_FAILURES) and not isinstance(
        exc, _IMAP_ABORT
    )
    if poli:
        try:
            client.logout()
            return
        except Exception:
            pass
    try:
        client.shutdown()
    except Exception:
        # La socket peut déjà être fermée ; la cause d'origine prime.
        pass


def connect(account, secret: str) -> ImaplibTransport:
    """Ouvre une connexion TLS et s'authentifie. Lève `ImapError` sur refus.

    `secret` est un mot de passe ou un jeton d'accès selon `account.auth` :
    l'appelant n'a pas à choisir de fonction, il passe le secret que le
    coffre lui a rendu. Tout échec après l'ouverture ferme la connexion
    (`_abandon`) avant que l'erreur ne sorte, sans la remplacer ; une
    ouverture qui échoue ferme elle-même ce qu'elle a ouvert
    (`IMAP4.__init__`). Le lien s'abandonne à la première lecture ou
    écriture qui lève (`fail_fast`) : l'appelant en ouvre un autre.

    En `ssl` comme en `starttls`, le certificat est vérifié (chaîne et
    nom), sauf si le compte épingle une empreinte pour ce point d'accès
    (`tls_pins`, lu par `getattr` : un compte qui ne porte pas le champ
    est vérifié) ; l'empreinte présentée est alors comparée à l'épingle
    avant toute authentification. Un refus sort en
    `tls.TlsCertificateError`, empreinte comprise, jamais en `ImapError`,
    et la socket se ferme sans LOGOUT. En `starttls`, des octets reçus en
    clair avec la réponse `OK`, avant la poignée de main, font refuser le
    lien, et les réponses non étiquetées reçues en clair avant elle sont
    oubliées (`starttls_context`).
    """
    import imaplib

    conf = account.imap
    delai = _delai_lecture()
    tls_actif = conf.security in tls.SECURITIES
    pin = (
        tls.account_pin(
            getattr(account, "tls_pins", None), conf.host, conf.port
        )
        if tls_actif
        else None
    )
    contexte = tls.context_for(pin) if tls_actif else None
    try:
        if conf.security == "ssl":
            client = imaplib.IMAP4_SSL(
                conf.host, conf.port, ssl_context=contexte, timeout=delai
            )
        else:
            client = imaplib.IMAP4(conf.host, conf.port, timeout=delai)
        fail_fast(client)
        try:
            if conf.security == "starttls":
                client.starttls(ssl_context=starttls_context(client, contexte))
            if pin:
                tls.check_pin(
                    client.sock,
                    pin,
                    protocol="imap",
                    host=conf.host,
                    port=conf.port,
                )
            if getattr(account, "auth", "login") == "oauth":
                chaine = xoauth2_chain(conf.user, secret)
                try:
                    client.authenticate("XOAUTH2", lambda _: chaine)
                except imaplib.IMAP4.abort:
                    # Un dialogue rompu (coupure, fin de flux, BYE), pas un
                    # refus du jeton : le rattrapage général en fait une
                    # panne de connexion.
                    raise
                except imaplib.IMAP4.error as exc:
                    # Le serveur a parlé, et c'était un refus. Le distinguer
                    # ici, pendant qu'on sait encore que la socket était
                    # bonne.
                    raise ImapAuthError(
                        f"{t('mail_err_token_refused')} {conf.host} : {exc}"
                    ) from exc
            else:
                client.login(conf.user, secret)
        except BaseException as exc:
            _abandon(client, exc)
            raise
    except UnicodeEncodeError as exc:
        # `imaplib` encode la commande LOGIN en ASCII : un mot de passe
        # accentué n'atteint même pas le serveur. Ce cas sort AVANT le
        # rattrapage général, dont le préfixe dit « refusée » — or personne
        # n'a rien refusé, et l'ancien message « ordinal not in range(128) »
        # accusait le serveur d'un refus qu'il n'a jamais prononcé.
        raise ImapError(t("mail_err_password_not_ascii")) from exc
    except (ImapAuthError, tls.TlsCertificateError):
        # Déjà qualifié : le rattrapage général en ferait une panne de
        # connexion, et l'appelant cesserait de savoir qu'il peut
        # rafraîchir son jeton, ou épingler un certificat.
        raise
    except ssl.SSLCertVerificationError as exc:
        # La vérification a refusé le certificat : la sonde lit celui que
        # présente le serveur, pour que l'erreur porte son empreinte.
        raise tls.certificate_error(
            exc,
            protocol="imap",
            host=conf.host,
            port=conf.port,
            security=conf.security,
            timeout=delai,
        ) from exc
    except Exception as exc:
        # Toute panne réseau ou d'authentification devient une seule erreur
        # de haut niveau, pour un message utile à l'utilisateur.
        raise ImapError(
            f"{t('mail_err_imap_connection_prefix')} {conf.host}"
            f" {t('mail_err_connection_refused_suffix')} {exc}"
        ) from exc
    return ImaplibTransport(client)
