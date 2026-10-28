#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le client courriel à l'écran : trois volets, et la lecture en plein écran.

Textual s'importe DANS `run_tui`, jamais au niveau module — c'est le motif du
reste de `script/todo/`. Conséquence utile : la moitié basse de ce fichier
(sessions, dossiers) se teste sans écran et sans dépendance.

Une session = un compte ouvert. Elle survit à une panne réseau : le cache
s'ouvre d'abord, la connexion est tentée ensuite, et son échec ne fait que
poser un drapeau `online = False`. Une boîte hors ligne reste lisible.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import imaplib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from types import SimpleNamespace

from script.todo.mail.imap_sync import Syncer
from script.todo.mail.store import Store, sweep_orphan_ephemeral

# Comptes synchronisés de front. Un fil par compte transforme des attentes
# réseau en série en une seule attente ; au-delà d'une poignée, les
# fournisseurs refusent les connexions simultanées et le gain disparaît.
# Ce qui signe un lien IMAP mort, par opposition à un serveur qui répond
# non. `imaplib` laisse remonter les pannes de socket telles quelles :
# `TimeoutError` est un `OSError`, et `IMAP4.abort` est ce qu'il lève quand
# le dialogue est rompu en cours de commande. Aucune de ces trois ne se
# répare en insistant sur le même lien ; toutes se réparent en en ouvrant
# un autre.
LIEN_MORT = (OSError, imaplib.IMAP4.abort)

SYNC_PARALLELE = 4
# Liens simultanés vers UN MÊME compte, pour que ses dossiers se
# synchronisent ensemble. Un `imaplib` n'a qu'un dossier sélectionné à la
# fois : sans second lien, une boîte de trente dossiers les parcourt un par
# un. Trois, pas plus : les fournisseurs plafonnent les connexions
# simultanées d'un compte, et ce plafond est partagé avec les autres
# clients de la personne — téléphone, client de bureau — qui gardent le
# leur ouvert en permanence.
SYNC_DOSSIERS_PARALLELE = 3

# Messages chargés d'un coup dans la liste. Le dossier arrive par pages :
# tout charger construirait autant de lignes qu'il y a de messages, à
# chaque ouverture et à chaque frappe de recherche.
PAGE = 500
# Lignes avant le bas où la page suivante part. Attendre la dernière ferait
# marquer un arrêt au défilement, le temps que le cache réponde.
MARGE_PAGE = 20

# Le mot à taper pour détruire un dossier. SANS ACCENT : il doit se taper
# sur n'importe quelle disposition de clavier, y compris celle d'un poste
# qu'on emprunte. Une question fermée se valide par réflexe ; un mot
# recopié oblige à lire ce qu'on détruit.
MOT_SUPPRESSION = "supprimer"

# La PORTÉE d'une recherche, dans l'ordre où `p` les fait défiler. Le
# dossier ouvert d'abord : c'est la seule portée qui réponde sans
# déchiffrer d'autres dossiers en mode chiffré, donc la seule qui puisse
# suivre la frappe.
_PORTEES = ("folder", "account", "all")

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


_logger = logging.getLogger(__name__)


ROLE_ORDER = {
    "inbox": 0,
    "drafts": 1,
    "sent": 2,
    "archive": 3,
    "junk": 4,
    "trash": 5,
}

# `data` du nœud "+ Ajouter un compte" au pied de l'arbre des comptes — un
# marqueur, pas une donnée métier, distingué d'un `MailboxRef` par son type.
ADD_ACCOUNT_NODE = "__add_account__"

# Les dispositions de volets, dans l'ordre de cycle de la touche `v`. Chaque
# entrée est (identifiant, clé i18n du nom affiché) — AUCUNE liste de
# `if layout == ...` ailleurs dans ce module : l'arrangement vient d'une
# classe CSS (`layout-{id}`) posée sur `#panes`, voir la CSS de `MailApp`.
# Ajouter une disposition = ajouter UNE entrée ici et UN bloc CSS assorti.
MAIL_LAYOUTS = [
    ("columns", "mail_layout_columns"),
    ("split", "mail_layout_split"),
    ("stacked", "mail_layout_stacked"),
]
_LAYOUT_IDS = [layout_id for layout_id, _ in MAIL_LAYOUTS]
_LAYOUT_I18N_KEYS = dict(MAIL_LAYOUTS)


def resolve_layout(value: str) -> str:
    """La disposition retenue pour `value`, sinon `columns`.

    Même motif que `store.resolve_mode` pour `mail_cache_mode` : une valeur
    absente ou corrompue dans `todo_prefs` (édition manuelle, ancienne
    version qui listait moins de dispositions) ne doit jamais empêcher le
    client de s'ouvrir — elle retombe sur la disposition par défaut.
    """
    return value if value in _LAYOUT_IDS else _LAYOUT_IDS[0]


def next_layout(current: str) -> str:
    """La disposition suivante dans le cycle, avec retour au début après la
    dernière. `resolve_layout` d'abord : une valeur inconnue ne doit pas
    lever `ValueError` dans `.index()`, elle doit se comporter comme si on
    partait de la première disposition.
    """
    index = _LAYOUT_IDS.index(resolve_layout(current))
    return _LAYOUT_IDS[(index + 1) % len(_LAYOUT_IDS)]


# Chaque disposition a EXACTEMENT deux volets ajustables : `folders` (face à
# `#right`) et `list_pane` (face à `#preview`). Le voisin de chaque paire
# reste TOUJOURS `1fr` et n'est jamais stocké — c'est le modèle Textual qui
# lui redonne ce que l'autre cède, donc « agrandir un volet rétrécit son
# voisin » ne demande aucune comptabilité couplée. La DIMENSION que ce
# nombre ajuste (largeur ou hauteur) n'est PAS une table Python par
# disposition : elle se lit, à l'application, sur la disposition CSS
# réellement posée (`styles.layout.name` du conteneur parent) — voir
# `MailApp._pane_dimension`. Ajouter une disposition ne touche donc rien
# ici, seulement le bloc CSS de `MAIL_LAYOUTS`.
_PANE_SLOTS = ("folders", "list_pane")
PANE_SIZE_MIN = 4  # cellules ; plancher commun largeur/hauteur.
PANE_SIZE_STEP = 4

# Barre de partage (tâche 25) : un widget FEUILLE, de taille FIXE, inséré
# ENTRE `slot` et son voisin `1fr` — glissable à la souris, mais
# n'appartenant à NI L'UN NI L'AUTRE des deux volets qu'il sépare, jamais
# stocké, jamais lui-même ajustable. `_SPLITTER_IDS` donne l'identifiant DOM
# de la barre propre à chaque volet réglable : un widget créé UNE FOIS
# dans `compose()`, jamais reconstruit au changement de disposition — seule
# son orientation (largeur ou hauteur) suit celle du volet qu'il jouxte, en
# CSS, un bloc par disposition comme les volets eux-mêmes (voir la CSS de
# `MailApp`) — jamais une table Python par disposition.
_SPLITTER_IDS = {"folders": "folders_splitter", "list_pane": "list_splitter"}
# cellules ; DOIT rester en phase avec la CSS (`width: 1`/`height: 1` de
# chaque barre). `MailApp._pane_total` ne s'en sert PAS — elle mesure le
# widget réel, donc son calcul du plafond est immunisé contre un futur
# désaccord entre les deux. `_PANE_SIBLING_MIN["folders"]` ci-dessous, en
# revanche, additionne CETTE constante directement (un dict de module ne
# peut pas mesurer un widget) : si la CSS change sans que cette valeur ne
# suive, seul `_PANE_SIBLING_MIN` dérive silencieusement, pas `_pane_total`.
_SPLITTER_SIZE = 1

# `#right` n'est PAS un volet-feuille comme `#preview` : il héberge à son
# tour `list_pane`/`preview` ET la barre de partage qui les sépare
# (`#list_splitter`), qui ont chacun besoin d'au moins `PANE_SIZE_MIN`
# (`_SPLITTER_SIZE` pour la barre). Ne réserver que `PANE_SIZE_MIN` au
# voisin de `#folders` suffirait à ne pas écraser `#right` LUI-MÊME, mais
# pas à empêcher ses enfants de s'écraser l'un l'autre une fois `#right`
# réduit à ce seul plancher — d'où le double, `+1` pour la barre. `list_pane`
# n'a pas ce problème : son voisin (`#preview`) est une feuille, sans enfant
# ni barre à protéger derrière lui. Ce n'est pas une branche PAR
# DISPOSITION : `#right` héberge toujours la même paire imbriquée, dans les
# trois dispositions (le DOM fixe de la tâche 23) — c'est un fait de
# STRUCTURE, pas de disposition. `+ _SPLITTER_SIZE` compte UN SEUL enfant
# fixe connu (`#list_splitter`) — pas une formule pour un nombre arbitraire
# d'enfants futurs : si `#right` héberge un jour autre chose que
# `list_pane` + `list_splitter` + `preview`, cette valeur devra être revue
# à la main, comme `_pane_total` ci-dessous (même limite, même raison).
_PANE_SIBLING_MIN = {
    "folders": 2 * PANE_SIZE_MIN + _SPLITTER_SIZE,
    "list_pane": PANE_SIZE_MIN,
}

# Le plancher de `#list_pane` est une CONTRAINTE DE MISE EN PAGE, pas une
# correction mesurée puis reposée en Python : il n'y a RIEN à mesurer pour le
# tenir, donc plus aucune mesure à lire trop tôt. C'est ce qui a retiré
# (tâche 27) la relecture de région post-effacement qui laissait `list_pane`
# figé sous son plancher.
#
# UN SEUL enfant `fr` contraint PAR CONTENEUR — c'est une règle, pas une
# économie. `resolve_fraction_unit` (`_resolve.py:190-214`) épingle à son
# minimum chaque enfant `fr` qui descendrait sous lui ET le RETIRE du
# réservoir de fractions ; si TOUS les frères `fr` s'épinglent,
# `remaining_fraction` tombe à zéro et la fonction rend `initial_space` —
# c'est-à-dire que `1fr` vaut alors TOUT l'espace restant, et CHAQUE frère
# est dimensionné à la totalité. En « stacked » sur 80x20, `#list_pane` et
# `#preview` (`1fr` chacun) voulaient 3,5 pour un plancher de 4 : les deux
# s'épinglaient, les deux recevaient 7 dans un conteneur de 8, et `#preview`
# commençait une ligne SOUS le bas de `#panes` — jamais composité, aucune
# barre de défilement, `Tab` ne l'atteignant pas. Ne contraindre que
# `#list_pane` laisse toujours `#preview` dans le réservoir : le cas « tous
# épinglés » devient INATTEIGNABLE, et `#preview` absorbe le reste.
#
# Le plancher de `#preview`, lui, ne vient pas d'une règle CSS mais de la
# réserve faite à `#right` (`_PANE_SIBLING_MIN["folders"]`, appliquée par
# `_apply_pane_size_for_slot`) : `#right` gardant au moins deux planchers
# plus la barre, le partage `fr` qui suit donne au moins son plancher à
# chacun de ses deux enfants sans que personne n'ait à s'épingler.
#
# `border-box` (le défaut) : `_resolve_extrema` (`widget.py:2489-2493`) retire
# la bordure du minimum, et `_get_box_model` (`widget.py:1814`, `1862`)
# l'applique APRÈS avoir résolu l'échelle, `fr` compris — `min-width: N` veut
# donc bien dire `region.width >= N`, la convention que tout ce fichier mesure
# sur `.region`. Une réserve toutefois : `constrain_width`
# (`widget.py:1829-1830`) s'applique APRÈS le minimum, et seul
# `layouts/grid.py:337` l'active — poser un jour `layout: grid` sur `#panes`
# ou `#right` annulerait donc ce plancher en silence.
#
# GÉNÉRÉ depuis la constante, jamais recopié : une valeur en dur ici
# dériverait en silence le jour où `PANE_SIZE_MIN` change, et le plancher
# affiché ne serait plus celui que `clamp_pane_size` fait respecter.
_PANE_MIN_CSS = f"""
        #list_pane {{
            min-width: {PANE_SIZE_MIN};
            min-height: {PANE_SIZE_MIN};
        }}
"""


def clamp_pane_size(
    value,
    total: int | None,
    minimum: int = PANE_SIZE_MIN,
    sibling_minimum: int | None = None,
) -> int | None:
    """`value`, borné pour ne jamais écraser le volet NI son voisin.

    Rend `None` quand `total` (l'espace total dont ce volet et son voisin se
    partagent) est inconnu ou non positif — un widget pas encore rendu,
    notamment — puisqu'il n'y a alors aucune borne calculable. Sinon,
    jamais sous `minimum`, et jamais au point de laisser le voisin sous
    `sibling_minimum` (par défaut `minimum` — un voisin ordinaire ; plus,
    pour `folders`, quand ce voisin est lui-même un conteneur à protéger,
    voir `_PANE_SIBLING_MIN`).
    """
    if total is None or total <= 0:
        return None
    if sibling_minimum is None:
        sibling_minimum = minimum
    ceiling = max(minimum, total - sibling_minimum)
    return max(minimum, min(int(value), ceiling))


def resolve_pane_sizes(stored, layout_id: str) -> dict:
    """Les tailles personnalisées de `layout_id` dans `stored`
    (`todo_prefs.get("mail_pane_sizes")`), filtrées et validées.

    Même motif que `resolve_layout`/`store.resolve_mode` : un magasin
    absent, du mauvais type, une entrée de disposition absente ou du
    mauvais type, une clé de volet inconnue, ou une valeur non numérique,
    booléenne (un `bool` EST un `int` en Python — jamais une taille valide)
    ou non positive ne lèvent jamais — ils sont silencieusement ignorés,
    laissant le volet concerné à la valeur de sa feuille de style.
    """
    per_layout = stored.get(layout_id) if isinstance(stored, dict) else None
    if not isinstance(per_layout, dict):
        return {}
    result = {}
    for slot in _PANE_SLOTS:
        value = per_layout.get(slot)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > 0
        ):
            result[slot] = int(value)
    return result


@dataclass
class MailboxRef:
    account_name: str
    folder_name: str
    display: str
    unseen: int


class Session:
    """Un compte ouvert : son cache, et son lien réseau s'il tient."""

    def __init__(
        self,
        account,
        store: Store,
        syncer: Syncer | None,
        error: str = "",
        password: str = "",
        secrets=None,
        config_get=None,
        connect_fn=None,
    ):
        self.account = account
        self.store = store
        self.syncer = syncer
        self.error = error
        self.password = password
        # Gardés pour pouvoir REDEMANDER le secret : un jeton d'accès vit
        # une heure, et une session peut durer plus longtemps.
        self.secrets = secrets
        self.config_get = config_get
        self.connect_fn = connect_fn

    def current_secret(self) -> str:
        """Le secret à présenter MAINTENANT, rafraîchi s'il a vieilli.

        Le secret capté à l'ouverture cesse de valoir en cours de session
        pour un compte OAuth. Tout ce qui rouvre une connexion — un envoi
        SMTP, une reprise après refus — passe donc par ici plutôt que de
        rejouer ce qui a été lu au démarrage.

        Sans coffre, rend ce qu'on a : les sessions montées à la main n'en
        ont pas, et lever ici les casserait toutes. Un échec de
        rafraîchissement rend de même — l'appelant verra le refus du
        serveur, qui dit la même chose sans faire tomber l'écran.
        """
        if getattr(self.account, "auth", "login") != "oauth":
            return self.password
        if self.secrets is None:
            return self.password
        from script.todo.mail.oauth import OAuthError, secret_for

        try:
            self.password = secret_for(
                self.account, self.secrets, config_get=self.config_get
            )
        except OAuthError as exc:
            _logger.info("rafraîchissement du jeton refusé : %s", exc)
        return self.password

    @property
    def online(self) -> bool:
        return self.syncer is not None

    def avec_lien(self, action, progress=None):
        """Exécute `action(transport)`, avec UNE reprise si le lien est mort.

        Tout ce qui parle au serveur passe par ici — la passe de
        synchronisation comme le rangement, la corbeille, le marquage ou la
        recherche serveur. Réserver la reprise à la synchronisation laissait
        les autres gestes cassés jusqu'à la passe suivante : une socket
        marquée morte par Python fait échouer toute lecture ultérieure en
        quelques millisecondes, sans rien demander au serveur.

        Deux façons pour un lien de cesser de servir, et les deux se
        réparent en en ouvrant un autre : le SECRET a expiré — un jeton
        d'accès vit une heure, une session dure plus —, ou la SOCKET est
        morte, une lecture ayant dépassé le délai.

        Une seule reprise. Une erreur de PROTOCOLE (`ImapError` : le serveur
        a répondu, et c'était non) n'en déclenche aucune — rouvrir n'y
        changerait rien, et réessayer sans fin ferait tourner le client
        indéfiniment.

        L'appelant garde la charge du verrou : `imaplib` n'est pas sûr entre
        fils, et c'est lui qui sait quelle suite d'échanges doit rester
        indivisible.
        """
        if self.syncer is None:
            return None
        from script.todo.mail.imap_transport import ImapAuthError

        try:
            return action(self.syncer.transport)
        except ImapAuthError:
            if (
                getattr(self.account, "auth", "login") != "oauth"
                or self.secrets is None
                or self.connect_fn is None
            ):
                raise
            raison = "jeton refusé"
        except LIEN_MORT as exc:
            if self.connect_fn is None:
                raise
            raison = f"lien mort ({exc})"
        _logger.info(
            "%s en cours de session : réouverture de %s",
            raison,
            self.account.name,
        )
        try:
            self.syncer.transport.logout()
        except Exception:
            # Le lien est déjà mort : ce qui compte est celui qui le
            # remplace, pas la politesse de la fermeture.
            pass
        # Le transport est remplacé, le `Syncer` reste : il ne porte que le
        # cache et le lien, et le reconstruire obligerait cette méthode à
        # savoir comment on en fabrique un.
        self.syncer.transport = self.connect_fn(
            self.account, self.current_secret()
        )
        return action(self.syncer.transport)

    def sync(self, progress=None):
        """Une passe, avec la même reprise que tout le reste."""
        if self.syncer is None:
            return None
        return self.avec_lien(
            lambda _transport: self.syncer.sync(progress=progress)
        )

    def close(self) -> None:
        if self.syncer is not None:
            try:
                self.syncer.transport.logout()
            except Exception:
                pass
        if self.store is not None:
            if self.store.mode == "ephemeral":
                self.store.cleanup()
            else:
                self.store.close()


def open_session(
    account, secrets, base=None, connect_fn=None, config_get=None
) -> Session:
    """Ouvre le cache d'UN compte, puis tente le réseau — voir
    `open_sessions` pour l'ordre et sa justification, identique ici.

    Extrait du corps de boucle d'`open_sessions` pour être rappelable seul :
    le TUI s'en sert après l'ajout d'un compte, sans ré-ouvrir tous les
    autres ni ré-enregistrer les gestionnaires de signaux (voir
    `_register_ephemeral_cleanup`).
    """
    if connect_fn is None:
        from script.todo.mail.imap_transport import connect as connect_fn

    store = Store(account, secrets=secrets, base=base)
    try:
        store.open()
    except Exception as exc:
        # Un cache corrompu, une clé introuvable ou un disque plein ne
        # doivent pas empêcher les AUTRES comptes de s'ouvrir. On garde la
        # session, sans cache, avec son erreur affichable — c'est le même
        # principe que pour une panne réseau, appliqué au disque.
        return Session(account, None, None, str(exc), "")

    syncer, error, password = None, "", ""
    try:
        # Le secret dépend du genre du compte : mot de passe, ou jeton
        # d'accès rafraîchi au besoin. Le rafraîchissement a lieu ICI, dans
        # le fil principal et avant toute passe — `SecretStore.set` réécrit
        # le coffre entier, et deux fils de synchronisation qui y
        # écriraient ensemble le corrompraient.
        from script.todo.mail.oauth import secret_for

        password = secret_for(account, secrets, config_get=config_get)
        if not password:
            raise ValueError(t("mail_no_password_stored"))
        syncer = Syncer(
            store,
            connect_fn(account, password),
            parallele=SYNC_DOSSIERS_PARALLELE,
        )
    except Exception as exc:
        error = str(exc)
    session = Session(
        account,
        store,
        syncer,
        error,
        password,
        secrets=secrets,
        config_get=config_get,
        connect_fn=connect_fn,
    )
    if syncer is not None:
        # Le secret DÉJÀ obtenu, pas un rafraîchissement : cette fabrique
        # est appelée depuis le fil de synchronisation, et plusieurs
        # comptes y avancent ensemble. `SecretStore.set` réécrit le coffre
        # entier — deux fils qui le rafraîchiraient en même temps le
        # corrompraient. Un jeton périmé fait échouer l'ouverture du lien
        # supplémentaire, son lot revient au lien principal, et c'est lui
        # qui déclenche l'unique reprise de `Session.sync`.
        syncer.open_transport = lambda: connect_fn(account, session.password)
    return session


def open_sessions(
    accounts, secrets, base=None, connect_fn=None, config_get=None
) -> list[Session]:
    """Ouvre le cache de chaque compte actif, puis tente le réseau.

    L'ordre compte : un mot de passe absent ou un serveur muet ne doit pas
    priver l'utilisateur de ce qu'il a déjà téléchargé.
    """
    if connect_fn is None:
        from script.todo.mail.imap_transport import connect as connect_fn

    sweep_orphan_ephemeral()
    sessions = [
        open_session(
            account,
            secrets,
            base=base,
            connect_fn=connect_fn,
            config_get=config_get,
        )
        for account in accounts
        if account.enabled
    ]
    _register_ephemeral_cleanup(sessions)
    return sessions


def _register_ephemeral_cleanup(sessions) -> None:
    """`atexit` ne s'exécute pas sur un signal, et un cache éphémère qui
    survit au processus est exactement ce que le mode promet d'éviter."""
    import atexit
    import os
    import signal

    targets = [
        s
        for s in sessions
        if s.store is not None and s.store.mode == "ephemeral"
    ]
    if not targets:
        return

    def _cleanup(*_):
        for session in targets:
            try:
                session.store.cleanup()
            except Exception:
                # Sortie best-effort : on ne relève jamais depuis un handler.
                pass

    atexit.register(_cleanup)
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous = signal.getsignal(sig)

        def _chained(signum, frame, _previous=previous):
            _cleanup()
            if callable(_previous):
                _previous(signum, frame)
                return
            # `SIG_DFL` et `SIG_IGN` sont des entiers, pas des appelables :
            # s'arrêter là AVALERAIT le signal, et un `kill` ou un
            # `systemctl stop` ne terminerait plus le processus. On
            # réinstalle la disposition d'origine puis on se renvoie le
            # signal, pour que l'action par défaut ait bien lieu — après le
            # nettoyage.
            signal.signal(signum, _previous)
            os.kill(os.getpid(), signum)

        try:
            signal.signal(sig, _chained)
        except ValueError:
            # `signal.signal` n'est utilisable que depuis le thread principal.
            pass


def mailbox_refs(sessions: list[Session]) -> list[MailboxRef]:
    """Les dossiers de tous les comptes, boîte de réception en tête."""
    refs = []
    for session in sessions:
        if session.store is None:
            # Compte dont le cache n'a pas pu s'ouvrir : il apparaît dans
            # l'arbre avec son erreur, mais il n'a aucun dossier à lister.
            continue
        folders = sorted(
            session.store.folders(),
            key=lambda f: (ROLE_ORDER.get(f["role"], 99), f["name"].lower()),
        )
        for folder in folders:
            refs.append(
                MailboxRef(
                    account_name=session.account.name,
                    folder_name=folder["name"],
                    display=folder["display"] or folder["name"],
                    unseen=folder["unseen"] or 0,
                )
            )
    return refs


def save_attachment(raw: bytes, index: int, directory) -> "pathlib.Path":
    """Écrit la pièce jointe `index` du message dans `directory`.

    Le nom vient du message, donc d'une source non fiable : on n'en garde que
    le nom de base, et on refuse de sortir du dossier demandé.
    """
    import email
    import email.policy
    import pathlib

    from script.todo.mail.tui_text import extract_body

    _, attachments = extract_body(raw)
    match = next((a for a in attachments if a.index == index), None)
    if match is None:
        raise ValueError(t("mail_attachment_not_found"))

    message = email.message_from_bytes(raw, policy=email.policy.default)
    parts = [
        part
        for part in (message.walk() if message.is_multipart() else [message])
        if part.get_content_maintype() != "multipart"
        and (part.get_content_disposition() or "").lower()
        in ("attachment", "inline")
    ]
    payload = parts[index].get_payload(decode=True) or b""

    directory = pathlib.Path(directory).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / pathlib.Path(match.filename).name
    target.write_bytes(payload)
    return target


def parse_recipients(raw: str) -> list[str]:
    """Un champ de destinataires → une entrée par destinataire.

    La virgule et le point-virgule séparent tous deux, et les deux formes
    d'un en-tête RFC 5322 sont acceptées : l'adresse nue et « Libellé
    <adresse> », dont le libellé est conservé tel quel.
    """
    if not raw:
        return []
    parts = raw.replace(";", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def parse_paths(raw: str) -> list[str]:
    """« a.pdf; "Facture, T3.pdf" » → deux chemins.

    Point-virgule SEUL : contrairement à un destinataire, une virgule est
    légale dans un nom de fichier — la scinder dessus aussi transformerait
    silencieusement un seul fichier en deux chemins inexistants.
    """
    if not raw:
        return []
    out = []
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        if len(part) >= 2 and part[0] == part[-1] and part[0] in "'\"":
            part = part[1:-1]
        out.append(part)
    return out


def append_attachment_path(current: str, new_path: str) -> str:
    """Ajoute `new_path` au champ `#files`, séparé par le « ; » qu'attend
    `parse_paths`.

    Le champ peut être vide, contenir déjà un ou plusieurs chemins, ou finir
    par un « ; » — dans tous les cas un seul séparateur sépare l'ancien
    contenu du nouveau, jamais un « ; » en tête ni doublé.
    """
    current = (current or "").strip()
    if not current:
        return new_path
    if current.endswith(";"):
        return f"{current} {new_path}"
    return f"{current}; {new_path}"


def browse_start_dir(raw_paths: str) -> str:
    """Le dossier où ouvrir le sélecteur : celui du dernier chemin saisi
    s'il existe, sinon le dossier personnel."""
    import os

    paths = parse_paths(raw_paths)
    if paths:
        candidate = os.path.dirname(os.path.expanduser(paths[-1]))
        if candidate and os.path.isdir(candidate):
            return candidate
    return os.path.expanduser("~")


def browse_one_path(app, start_dir: str) -> str | None:
    """Ouvre le sélecteur de fichiers sur `start_dir` ; rend le chemin
    choisi, ou None si l'utilisateur sort sans choisir.

    `todo_file_browser` est bâti sur urwid, qui possède son propre
    `urwid.MainLoop` : deux boucles ne tiennent pas le terminal en même
    temps. `app.suspend()` rend le terminal à urwid le temps du `with`,
    puis Textual le reprend et redessine.

    L'IMPORT est fait DANS le `with` : `urwid.raw_display.Screen` fige son
    `output=sys.stdout` à l'import du module. Importé avant `suspend()`, il
    figerait le `sys.stdout` que `App.run()` redirige pendant toute la vie
    de l'application, et non le vrai terminal (`get_cols_rows()` lève
    alors sur un descripteur -1).

    Une panne du sélecteur (terminal incompatible, `suspend()` refusé)
    remonte à l'appelant, qui l'affiche dans sa propre ligne d'état.
    """
    chosen: dict = {}
    with app.suspend():
        from script.todo import todo_file_browser

        def _on_selected(path: str) -> None:
            chosen["path"] = path
            todo_file_browser.exit_program()

        browser = todo_file_browser.FileBrowser(start_dir, _on_selected)
        browser.run_main_frame()
    return chosen.get("path")


# Messages en cache de la boîte de réception sur lesquels l'éditeur de
# règle évalue son filtre pour l'aperçu.
RULES_PREVIEW_MESSAGES = 200
# Temps cumulé, en secondes, accordé aux expressions régulières de cet
# aperçu, qui s'évalue dans le fil de l'interface.
RULES_PREVIEW_REGEX_S = 2.0
# Lignes du texte d'une réponse automatique montrées sous la file d'envoi.
OUTBOX_PREVIEW_LINES = 20
# Messages récents de la boîte de réception proposés à l'essai d'une règle.
TRIAL_MESSAGES = 50


def format_epoch(epoch: int) -> str:
    """Une époque en date et heure LOCALES, à la minute."""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(epoch)))


def rule_node_label(node) -> str:
    """Libellé d'un nœud du filtre d'une règle : groupe ou condition.

    Texte BRUT : la valeur d'une condition est saisie par l'utilisateur,
    et l'appelant l'enveloppe dans `Text` avant de l'afficher. Une valeur
    inconnue (fichier édité à la main) s'affiche sous sa clé.
    """
    from script.todo.mail.rules.model import Group

    if isinstance(node, Group):
        return t(f"mail_rules_group_{node.op}")
    parts = [
        t(f"mail_rules_field_{node.field}"),
        t(f"mail_rules_op_{node.op}"),
    ]
    if node.op != "glob":
        parts.append(f"({t(f'mail_rules_mode_{node.mode}')})")
    parts.append(f'"{node.value}"')
    return " ".join(parts)


def rule_filter_summary(node) -> str:
    """Le filtre entier sur une ligne : « ET — toutes (De …, NON (…)) ».

    Un groupe ET vide se lit « Tous les messages », ce qu'il évalue.
    """
    from script.todo.mail.rules.model import Group

    if not isinstance(node, Group):
        return rule_node_label(node)
    if not node.children and node.op == "all":
        return t("mail_rules_match_all")
    inner = ", ".join(rule_filter_summary(child) for child in node.children)
    return f"{rule_node_label(node)} ({inner})"


def _filter_uses_field(node, field: str) -> bool:
    from script.todo.mail.rules.model import Group

    if isinstance(node, Group):
        return any(_filter_uses_field(child, field) for child in node.children)
    return getattr(node, "field", None) == field


def rules_arm_point(store):
    """Le point d'armement d'une règle activée maintenant, ou None.

    `Armed` sur l'UIDVALIDITY et l'UIDNEXT de la boîte de réception en
    cache : la règle ne verra que ce qui arrive après. None quand la boîte
    ou l'un de ces deux nombres est inconnu ; le moteur arme alors la règle
    à sa passe suivante.
    """
    from script.todo.mail.rules.engine import find_inbox
    from script.todo.mail.rules.model import Armed

    try:
        inbox = find_inbox(store)
        fstate = store.folder_state(inbox) if inbox else None
    except Exception:
        return None
    if (
        not fstate
        or not fstate.get("uidvalidity")
        or not fstate.get("uidnext")
    ):
        return None
    return Armed(
        int(fstate["uidvalidity"]), int(fstate["uidnext"]), int(time.time())
    )


def rules_filter_preview(store, root) -> str:
    """Combien des derniers messages en cache de la boîte de réception le
    filtre `root` retient, en une ou deux lignes traduites.

    Évaluation SANS corps : un message dont le verdict dépend du corps est
    compté « inconnu », jamais retenu ni écarté. Le cache ne garde pas Cc :
    un filtre qui teste À/Cc le dit. Une règle fautive (expression
    régulière refusée, NON sans enfant) rend le texte de son erreur.
    """
    from script.todo.mail.rules.engine import find_inbox
    from script.todo.mail.rules.filter import BodyUnavailable, evaluate
    from script.todo.mail.rules.model import RuleError, message_view
    from script.todo.mail.rules.regex_worker import time_budget

    inbox = find_inbox(store)
    fstate = store.folder_state(inbox) if inbox else None
    metas = (
        store.list_messages(fstate["id"], limit=RULES_PREVIEW_MESSAGES)
        if fstate
        else []
    )
    uidvalidity = (fstate or {}).get("uidvalidity") or 0
    matches = unknown = 0
    try:
        # Le fil de l'interface attend au plus ce budget, quel que soit le
        # nombre de messages qu'une expression régulière lente ralentit.
        with time_budget(RULES_PREVIEW_REGEX_S):
            for meta in metas:
                try:
                    if evaluate(root, message_view(meta, uidvalidity), None):
                        matches += 1
                except BodyUnavailable:
                    unknown += 1
    except RuleError as exc:
        return f"{t('mail_rules_preview')} : {exc}"
    text = f"{t('mail_rules_preview_matches')} {matches}/{len(metas)}"
    if unknown:
        text += f" · {t('mail_rules_preview_body_unknown')} {unknown}"
    if _filter_uses_field(root, "to_cc"):
        text += f"\n{t('mail_rules_preview_to_only')}"
    return text


def outbox_entry_preview(raw: bytes) -> tuple[list, list, list]:
    """Ce qu'une entrée de la file enverra : (lignes, en ligne, jointes).

    Les `OUTBOX_PREVIEW_LINES` premières lignes de la partie texte, puis les
    noms des images citées par le HTML (`Content-Disposition: inline`) et
    ceux des pièces jointes. Un message joint (`message/rfc822`, ou tout
    type `message/*` qui contient des parties) compte pour UNE pièce
    jointe, sous son nom : ses propres parties ne sont pas listées. Une
    partie illisible donne une liste vide plutôt qu'une exception :
    l'aperçu ne bloque jamais la file.
    """
    import email
    import email.policy

    msg = email.message_from_bytes(raw or b"", policy=email.policy.default)
    lines: list = []
    try:
        body = msg.get_body(preferencelist=("plain",))
        if body is not None:
            lines = body.get_content().splitlines()[:OUTBOX_PREVIEW_LINES]
    except Exception:
        lines = []
    inline, attached = [], []
    pile = [msg]
    while pile:
        part = pile.pop()
        joint = part is not msg and part.get_content_maintype() == "message"
        if part.is_multipart() and not joint:
            # Ordre du message : la pile rend la première partie d'abord.
            pile.extend(reversed(part.get_payload()))
            continue
        # Un message d'une seule partie EST son texte : rien à lister.
        if part is msg:
            continue
        if joint:
            attached.append(part.get_filename() or part.get_content_type())
            continue
        disposition = part.get_content_disposition()
        name = part.get_filename() or ""
        if disposition == "attachment":
            attached.append(name or part.get_content_type())
        elif part.get_content_maintype() == "image":
            inline.append(name or part.get_content_type())
    return lines, inline, attached


def _one_line(value) -> str:
    """`value` sur une ligne : caractères de contrôle et de format remplacés
    par une espace, blancs réduits."""
    import unicodedata

    texte = "".join(
        " " if unicodedata.category(c) in ("Cc", "Cf") else c
        for c in str(value or "")
    )
    return " ".join(texte.split())


def forward_preview_headers(outgoing) -> list[tuple[str, str]]:
    """Les en-têtes montrés par l'essai d'une règle forward : (nom, valeur).

    Transfert (`EmailMessage`) : From, To, Reply-To, Subject,
    Auto-Submitted, puis « Bcc » = destinations lues dans `X-ERPLibre-Bcc`,
    seul endroit où l'essai les montre parmi les en-têtes. Redirection
    (`smtp_send.RawOutgoing`) : Resent-From et Resent-Date du bloc posé en
    tête, puis From, To, Subject de l'original, lus par `BytesHeaderParser`
    sur la section d'en-têtes. Valeurs décodées, sur une ligne ; un
    en-tête absent ou illisible n'est pas listé.
    """
    import email.parser
    import email.policy

    from script.todo.mail.smtp_send import RawOutgoing

    if isinstance(outgoing, RawOutgoing):
        msg = email.parser.BytesHeaderParser(
            policy=email.policy.default
        ).parsebytes(outgoing.raw or b"")
        names = [
            ("Resent-From", "Resent-From"),
            ("Resent-Date", "Resent-Date"),
            ("From", "From"),
            ("To", "To"),
            ("Subject", "Subject"),
        ]
    else:
        msg = outgoing
        names = [
            ("From", "From"),
            ("To", "To"),
            ("Reply-To", "Reply-To"),
            ("Subject", "Subject"),
            ("Auto-Submitted", "Auto-Submitted"),
            ("Bcc", "X-ERPLibre-Bcc"),
        ]
    headers = []
    for label, name in names:
        try:
            value = msg.get(name)
        except Exception:
            continue
        if value is None:
            continue
        value = _one_line(value)
        if value:
            headers.append((label, value))
    return headers


def rule_forward_summary(rule) -> str:
    """« mode : destinations » d'une règle forward, « » pour un autre
    type ; des options illisibles rendent le texte de leur `RuleError`."""
    from script.todo.mail.rules import model

    if rule.action.kind != "forward":
        return ""
    try:
        opts = model.forward_options(rule.action)
    except model.RuleError as exc:
        return str(exc)
    return (
        f"{t(f'mail_rules_fwd_mode_{opts.mode}')} : {', '.join(opts.targets)}"
    )


def trial_simulation(
    session,
    rule,
    meta,
    *,
    folder: str,
    uidvalidity: int,
    rules_base,
    verrou=None,
):
    """Ce que `rule` ferait du message d'INBOX `meta` (ligne du cache).

    En ligne, les en-têtes complets sont relus du serveur et le corps
    arrive par FETCH, sous `verrou`. Hors ligne, si la boîte a été
    renumérotée depuis `uidvalidity`, ou si la relecture échoue, la ligne
    du cache sert d'en-têtes (sans Cc ni en-têtes supplémentaires, la
    simulation le dit) et le corps vient du cache, `BodyUnavailable` à
    défaut. Les octets complets d'une règle forward suivent le même
    chemin : `engine.make_raw_loader` en ligne (taille annoncée vérifiée
    avant tout téléchargement), le cache sinon, `MessageTooBig` au-delà de
    `FORWARD_MAX_BYTES`. Rend une `engine.Simulation` ; ne lève pas.
    """
    from script.todo.mail.rules import engine
    from script.todo.mail.rules.filter import BODY_TEXT_MAX, BodyUnavailable
    from script.todo.mail.rules.model import FORWARD_MAX_BYTES

    header = engine.fetch_inbox_header(
        session, meta.uid, uidvalidity=uidvalidity, verrou=verrou
    )
    if header is not None:
        loader = engine.make_body_loader(
            session, folder, meta.uid, verrou=verrou
        )
        raw_loader = engine.make_raw_loader(
            session,
            folder,
            meta.uid,
            verrou=verrou,
            size=int(getattr(header, "size", 0) or 0),
        )
    else:
        store = session.store

        def loader() -> str:
            from script.todo.mail.tui_text import extract_body

            raw = store.read_body(folder, meta.uid)
            if raw is None:
                raise BodyUnavailable(online=False)
            return extract_body(raw)[0][:BODY_TEXT_MAX]

        def raw_loader() -> bytes:
            raw = store.read_body(folder, meta.uid)
            if raw is None:
                raise BodyUnavailable(online=False)
            if len(raw) > FORWARD_MAX_BYTES:
                raise engine.MessageTooBig(len(raw))
            return bytes(raw)

    return engine.simulate(
        session,
        rule,
        header if header is not None else meta,
        uidvalidity=uidvalidity,
        body_loader=loader,
        headers_complete=header is not None,
        rules_base=rules_base,
        raw_loader=raw_loader,
    )


def _forward_trial_lines(preview) -> list[tuple[str, str]]:
    """La section de l'essai d'une règle forward (`engine.ForwardPreview`),
    à la place de la ligne du destinataire : mode, destinations retenues
    et retirées avec leur raison, taille, puis le message qui partirait
    (en-têtes, début du texte, pièces), et l'erreur de construction."""
    from script.todo.mail.smtp_send import RawOutgoing

    lines: list[tuple[str, str]] = [
        (
            f"{t('mail_rules_trial_fwd_mode')} "
            f"{t(f'mail_rules_fwd_mode_{preview.mode}')}",
            "",
        )
    ]
    if preview.targets:
        lines.append(
            (
                f"{t('mail_rules_trial_fwd_targets')} "
                f"{', '.join(preview.targets)}",
                "",
            )
        )
    else:
        lines.append((t("mail_rules_trial_fwd_no_target"), ""))
    for address, code in preview.removed:
        lines.append(
            (
                f"  {t('mail_rules_trial_fwd_removed')} {address} — "
                f"{t(f'mail_rules_fwd_removed_{code}')}",
                "dim",
            )
        )
    if preview.size > 0:
        lines.append((f"{t('mail_rules_trial_fwd_size')} {preview.size}", ""))
    outgoing = preview.outgoing
    if outgoing is not None:
        lines.append(("", ""))
        lines.append((t("mail_rules_trial_fwd_headers"), "bold"))
        if preview.preview_self:
            lines.append((t("mail_rules_trial_fwd_preview_self"), "dim"))
        lines.extend(
            (f"{nom}: {valeur}", "")
            for nom, valeur in forward_preview_headers(outgoing)
        )
        if isinstance(outgoing, RawOutgoing):
            lines.append((t("mail_rules_trial_fwd_unchanged"), "dim"))
        lines.append(("", ""))
        try:
            texte, en_ligne, jointes = outbox_entry_preview(
                outgoing.as_bytes()
            )
        except Exception as exc:
            lines.append((str(exc) or type(exc).__name__, "bold red"))
        else:
            lines.extend((ligne, "") for ligne in texte)
            lines.extend(
                (f"  {nom} — {t('mail_rules_image_inline')}", "dim")
                for nom in en_ligne
            )
            lines.extend(
                (f"  {nom} — {t('mail_rules_image_attached')}", "dim")
                for nom in jointes
            )
    if preview.error:
        lines.append((preview.error, "bold red"))
    return lines


def rule_trial_lines(sim) -> list[tuple[str, str]]:
    """L'essai d'une règle ligne par ligne : (texte, style).

    `sim` est une `engine.Simulation`. Pour une règle forward, le verdict
    d'envoi se lit « transférerait » et la ligne du destinataire laisse la
    place à la section de `_forward_trial_lines`, ou à rien quand l'aperçu
    manque : l'expéditeur n'est jamais une destination. Le style (« »,
    « bold », « dim », « yellow », « bold red ») ne sert qu'à l'écran ; le
    menu imprime le texte seul. Le texte est BRUT : sujet, adresses, valeurs du filtre et
    corps viennent des messages ou de la règle, et l'appelant les affiche
    sans les interpréter.
    """
    from script.todo.mail.rules.guards import SEND

    relais = sim.forward is not None or sim.kind == "forward"

    def verdict(code: str) -> str:
        if code == SEND:
            if relais:
                return t("mail_rules_trial_would_forward")
            return t("mail_rules_trial_would_send")
        if relais and code == "no_target":
            return t("mail_rules_trial_fwd_no_sender")
        return t(f"mail_rules_reason_{code}")

    lines: list[tuple[str, str]] = []
    if not sim.rule_enabled:
        lines.append((t("mail_rules_trial_disabled"), "yellow"))
    if sim.filter_lines:
        lines.append((t("mail_rules_trial_filter"), "bold"))
        for line in sim.filter_lines:
            mark = {True: "✓", False: "✗"}.get(line.result, "?")
            lines.append(
                (
                    f"{'  ' * (line.depth + 1)}{mark} "
                    f"{rule_node_label(line.node)}",
                    "",
                )
            )
        cle = {
            True: "mail_rules_trial_match",
            False: "mail_rules_trial_no_match",
        }.get(sim.matched, "mail_rules_trial_unknown")
        lines.append((t(cle), ""))
    # Le plafond quotidien d'un rapport écarte la demande, sans file ni
    # retenue : c'est le verdict, et rien n'est à libérer.
    capped = sim.hold == "stats_cap"
    if sim.reason:
        code = "stats_cap" if capped and sim.reason == SEND else sim.reason
        lines.append(
            (f"{t('mail_rules_trial_verdict')} {verdict(code)}", "bold")
        )
    if sim.reason_if_new and sim.reason_if_new != sim.reason:
        lines.append(
            (
                f"{t('mail_rules_trial_verdict_if_new')} "
                f"{verdict(sim.reason_if_new)}",
                "",
            )
        )
    if sim.hold and not capped:
        lines.append(
            (
                f"{t('mail_rules_trial_held')} "
                f"{t(f'mail_rules_reason_{sim.hold}')}",
                "yellow",
            )
        )
    if sim.authenticated is not None:
        if sim.auth_serv_id:
            lines.append(
                (f"{t('mail_rules_trial_authserv')} {sim.auth_serv_id}", "")
            )
        else:
            lines.append((t("mail_rules_trial_no_authserv"), "dim"))
        if sim.authenticated:
            lines.append((t("mail_rules_trial_authenticated"), ""))
        else:
            lines.append((t("mail_rules_trial_not_authenticated"), "yellow"))
        if sim.auth_serv_unset:
            lines.append((t("mail_stats_report_auth_serv_unset"), "dim"))
    if sim.forward is not None:
        lines.extend(_forward_trial_lines(sim.forward))
    elif relais:
        # Sans aperçu, aucune destination n'est connue : pas de ligne,
        # `sim.error` dit pourquoi.
        pass
    elif sim.target:
        lines.append((f"{t('mail_rules_trial_target')} {sim.target}", ""))
    else:
        lines.append((t("mail_rules_trial_no_target"), ""))
    rendu = sim.rendered
    if rendu is not None:
        lines.append((f"{t('mail_rules_trial_subject')} {sim.subject}", ""))
        lines.append(("", ""))
        lines.extend((ligne, "") for ligne in rendu.text.splitlines())
        images = [
            (part.filename, "mail_rules_image_inline") for part in rendu.inline
        ] + [
            (part.filename, "mail_rules_image_attached")
            for part in rendu.attachments
        ]
        if images:
            lines.append(("", ""))
            lines.append((t("mail_rules_images"), "bold"))
            lines.extend((f"  {nom} — {t(cle)}", "dim") for nom, cle in images)
    if sim.error:
        lines.append((sim.error, "bold red"))
    if not sim.headers_complete:
        lines.append((t("mail_rules_trial_headers_partial"), "dim"))
    return lines


def edit_in_external_editor(
    text: str, editor: str | None = None, runner=None
) -> str:
    """Ouvre `$EDITOR` sur le corps et rend ce qui en revient.

    Si l'éditeur manque ou sort en erreur, on garde le texte de départ : perdre
    un brouillon parce que `vim` n'est pas installé serait inacceptable.
    """
    import os
    import subprocess
    import tempfile

    editor = editor or os.environ.get("EDITOR") or "nano"
    runner = runner or (lambda cmd: subprocess.call(cmd))
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".txt", delete=False, encoding="utf-8"
    )
    path = handle.name
    try:
        handle.write(text or "")
        handle.close()
        try:
            code = runner([editor, path])
        except Exception:
            return text
        if code != 0:
            return text
        with open(path, encoding="utf-8") as opened:
            return opened.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def resolve_sent_folder(session) -> str:
    """Le dossier Envoyés tel que le SERVEUR l'a annoncé.

    Le préréglage n'est qu'une supposition : un serveur peut nommer le sien
    « INBOX.Sent », « Sent Items » ou autrement, et il le déclare lui-même
    par l'attribut \\Sent que `parse_list_line` traduit en rôle. On croit
    donc le serveur d'abord, et le préréglage seulement s'il n'a rien dit —
    par exemple avant la toute première synchronisation.
    """
    if session.store is not None:
        try:
            folders = session.store.folders()
        except Exception:
            # Un cache verrouillé ou corrompu ne doit jamais transformer un
            # envoi déjà réussi en échec signalé au niveau du bouton
            # Envoyer : le contrat de cette fonction ("le préréglage si on
            # ne sait pas mieux") doit rester vrai même quand « ne pas
            # savoir » vient d'une exception plutôt que d'une absence de
            # rôle.
            folders = []
        for folder in folders:
            if folder["role"] == "sent":
                return folder["name"]
    return session.account.sent_folder


def file_in_sent(session, msg, verrou=None) -> Exception | None:
    """Dépose une copie de `msg` dans Envoyés, marquée lue. Rend l'erreur.

    Le Cci ne ressort pas par cette porte : la copie part par IMAP, et sans
    `without_bcc` il redeviendrait un en-tête lisible sur le serveur.
    `verrou` protège la connexion IMAP de la session ; l'APPEND passe par
    `avec_lien` quand la session en a un (reprise sur lien mort), par le
    transport sinon. Ne lève jamais : un message déjà parti ne devient pas
    un échec parce que son classement a raté, et l'appelant décide de ce
    qu'il dit de l'erreur rendue.
    """
    from script.todo.mail.smtp_send import without_bcc

    garde = verrou if verrou is not None else contextlib.nullcontext()
    try:
        sent_folder = resolve_sent_folder(session)

        def deposer(transport):
            transport.append(
                sent_folder,
                without_bcc(msg).as_bytes(),
                ["\\Seen"],
            )

        reprise = getattr(session, "avec_lien", None)
        with garde:
            if reprise is None:
                deposer(session.syncer.transport)
            else:
                reprise(deposer)
    except Exception as exc:
        return exc
    return None


def _flush_rules(session, rules_base):
    """Les règles du compte pour la vidange : (règles par id, lisibles).

    Fichier absent, cache éphémère ou fichier illisible : (None, False).
    Les entrées automatiques restent alors en file, ni envoyées ni
    supprimées ; elles expirent d'elles-mêmes.
    """
    from script.todo.mail.rules import storage
    from script.todo.mail.rules.model import RuleError

    base = rules_base
    if base is None:
        base = storage.base_of(session.store)
    if base is None:
        return None, False
    name = session.account.name
    try:
        if not storage.rules_exist(name, base):
            return None, False
        return {rule.id: rule for rule in storage.load(name, base)}, True
    except RuleError:
        _logger.error("%s : règles illisibles, file automatique gardée", name)
        return None, False


def flush_outbox(
    session,
    send_fn=None,
    connect_fn=None,
    verrou=None,
    now=None,
    rules_base=None,
) -> tuple:
    """Envoie ce qui attend. Rend (partis, retenus, échoués).

    Appelée à chaque passe de synchronisation : le retour du réseau est
    exactement le moment où la file doit se vider, sans que personne ait à
    y penser. Un message RETENU est sauté — c'est le sens de la retenue,
    et seul un geste la lève.

    Pour chaque entrée, dans l'ordre :
    - une réservation (`outbox_claim`) l'enlève à toute autre vidange,
      même d'un autre processus ; une entrée réservée ailleurs est en cours
      d'envoi et n'est ni retirée ni envoyée ici ;
    - passée son `expires_at`, elle est retirée et son journal passe
      `expired`, retenue ou non ;
    - automatique, elle n'est envoyée que si sa règle existe, est active
      et garde l'empreinte de la mise en file ; sinon elle est retirée
      (`rule_disabled`, `rule_changed`), et une entrée déjà `sent` au
      journal est retirée sans renvoi ;
    - retenue, relu dans la base et non dans l'instantané, elle reste et
      sa réservation est rendue ;
    - après un échec de connexion au serveur SMTP, les entrées suivantes
      restent en file sans nouvel essai : chacune attendrait le même
      délai de connexion ;
    - envoyée, elle est retirée et classée dans Envoyés (`file_in_sent`,
      sous `verrou`), sauf une redirection ; un APPEND raté ne compte pas
      comme échec d'envoi ;
    - refusée, l'erreur est gardée scellée ; après `max_attempts` refus
      PERMANENTS (5xx), un message écrit à la main est retenu (jamais
      détruit), une réponse automatique est retirée
      (`attempts_exhausted`). Un échec transitoire n'est pas plafonné.

    Selon son type (`kind`) :
    - `manual` : envoi écrit à la main, enveloppe lue dans ses octets ;
    - `auto_reply` : réponse d'une règle, enveloppe lue dans ses octets ;
    - `auto_forward` : transfert d'une règle, même chemin qu'une réponse
      (destinations dans le Cci interne des octets) ;
    - `auto_redirect` : redirection d'une règle, remise telle quelle
      (`RawOutgoing`) à l'enveloppe relue dans `sealed_to` par
      `parse_envelope` ; illisible, l'entrée est retirée
      (`failed/build_error`) sans connexion ; jamais classée dans Envoyés ;
    - tout autre type (cache écrit par un code plus récent) est retiré
      (`failed/build_error`) sans connexion, jamais envoyé.

    Les règles sont lues une fois, et seulement si la file porte une entrée
    automatique ; fichier absent ou illisible : ces entrées restent telles
    quelles. `rules_base` vaut par défaut `storage.base_of(session.store)`.
    N'appelle jamais `deliver`, qui classerait une seconde copie. Ne lève
    jamais pour une entrée : un envoi qui échoue n'empêche pas les suivants
    de partir.
    """
    import email
    import email.policy

    from script.todo.mail.rules.engine import smtp_failure_is_permanent
    from script.todo.mail.smtp_send import (
        RawOutgoing,
        SmtpError,
        parse_envelope,
    )
    from script.todo.mail.smtp_send import connect as smtp_connect
    from script.todo.mail.smtp_send import send as smtp_send_fn
    from script.todo.mail.store import OUTBOX_AUTO_KINDS

    if not session.online:
        return (0, 0, 0)
    send_fn = send_fn or smtp_send_fn
    connect_fn = connect_fn or smtp_connect
    clock = now or time.time
    store = session.store
    name = session.account.name
    entrees = store.outbox()
    regles, lisibles = None, False
    if any(e.get("kind", "manual") != "manual" for e in entrees):
        regles, lisibles = _flush_rules(session, rules_base)
    partis = retenus = echoues = 0
    injoignable = False
    for entree in entrees:
        ident = entree["id"]
        kind = entree.get("kind", "manual")
        manuelle = kind == "manual"
        rule_id = entree.get("rule_id")
        source = entree.get("source_key")
        instant = int(clock())
        if not store.outbox_claim(ident, instant):
            continue

        def clore(outcome, reason, ident=ident, rule_id=rule_id, src=source):
            store.drop_queued(ident)
            if rule_id:
                store.rule_log_set_outcome(rule_id, src, outcome, reason)
            _logger.info(
                "%s : file %s retirée, %s/%s", name, ident, outcome, reason
            )

        if kind not in ("manual",) + OUTBOX_AUTO_KINDS:
            clore("failed", "build_error")
            continue
        expire = entree.get("expires_at")
        if expire and instant > expire:
            clore("expired", "expired")
            continue
        if not manuelle:
            if not lisibles:
                store.outbox_release(ident)
                continue
            if rule_id and store.rule_log_outcome(rule_id, source) == "sent":
                store.drop_queued(ident)
                continue
            regle = regles.get(rule_id) if rule_id else None
            if regle is None or not regle.enabled:
                clore("expired", "rule_disabled")
                continue
            if store.rule_log_fingerprint(rule_id, source) != (
                regle.fingerprint()
            ):
                clore("expired", "rule_changed")
                continue
        if store.outbox_held(ident):
            store.outbox_release(ident)
            retenus += 1
            continue
        enveloppe = None
        if kind == "auto_redirect":
            try:
                enveloppe = parse_envelope(entree.get("to") or "")
            except SmtpError:
                clore("failed", "build_error")
                continue
        if injoignable:
            store.outbox_release(ident)
            continue
        brut = store.queued_raw(ident)
        if brut is None:
            store.drop_queued(ident)
            continue
        transport = None
        # None avant la connexion, faux pendant, vrai après.
        connecte = None
        try:
            if enveloppe is not None:
                message = RawOutgoing(
                    brut, enveloppe, entree.get("subject") or ""
                )
            else:
                message = email.message_from_bytes(
                    brut, policy=email.policy.default
                )
            connecte = False
            transport = connect_fn(session.account, session.current_secret())
            connecte = True
            send_fn(session.account, message, transport)
        except Exception as exc:
            injoignable = injoignable or connecte is False
            info = store.record_send_failure(
                ident, str(exc), permanent=smtp_failure_is_permanent(exc)
            )
            echoues += 1
            if info["perm_attempts"] >= info["max_attempts"]:
                if manuelle:
                    store.set_held(ident, True)
                else:
                    clore("failed", "attempts_exhausted")
            continue
        finally:
            if transport is not None:
                try:
                    transport.quit()
                except Exception:
                    pass
        if rule_id:
            store.rule_log_set_outcome(rule_id, source, "sent")
        store.drop_queued(ident)
        partis += 1
        if enveloppe is not None:
            continue
        erreur = file_in_sent(session, message, verrou)
        if erreur is not None:
            _logger.error(
                "%s : file %s partie, APPEND vers Envoyés en échec (%s)",
                name,
                ident,
                type(erreur).__name__,
            )
    return (partis, retenus, echoues)


class DeliverOffline(Exception):
    """`deliver(..., queue_offline=False)` sur une session hors ligne."""


def deliver(
    session,
    msg,
    send_fn=None,
    connect_fn=None,
    verrou=None,
    *,
    queue_offline=True,
) -> str:
    """Envoie, puis dépose une copie dans Envoyés. Rend le texte de statut.

    L'ordre n'est pas négociable : l'APPEND vient APRÈS l'envoi, et son échec
    n'annule rien. Le message est déjà parti ; le signaler comme un échec
    pousserait l'utilisateur à l'envoyer deux fois.

    `verrou` est celui qui protège la connexion IMAP de la session. L'APPEND
    et la relecture ciblée d'Envoyés passent par lui : sans cela ils
    partageraient la socket avec une passe de synchronisation en cours, et
    l'un des deux dialogues lirait la réponse de l'autre. Facultatif pour un
    appelant qui monte sa session à la main et n'a donc aucune passe
    concurrente à craindre. Comme il peut attendre une passe entière,
    `deliver` ne s'appelle jamais depuis le fil de l'interface.

    Hors ligne, le message part dans la file comme un envoi MANUEL ; avec
    `queue_offline=False`, `deliver` lève `DeliverOffline` sans rien
    écrire, pour un appelant qui met lui-même en file sous une autre
    forme (réponse automatique : règle, échéance, journal).

    Un `RawOutgoing` (redirection) lève `DeliverOffline` hors ligne quel
    que soit `queue_offline` : une entrée manuelle perdrait son enveloppe.
    En ligne, il part à son enveloppe et n'est NI classé dans Envoyés NI
    suivi d'une relecture d'Envoyés : sa copie porterait le From d'un tiers.
    """
    from script.todo.mail.smtp_send import RawOutgoing, recipients
    from script.todo.mail.smtp_send import connect as smtp_connect
    from script.todo.mail.smtp_send import send as smtp_send_fn

    garde = verrou if verrou is not None else contextlib.nullcontext()

    brut = isinstance(msg, RawOutgoing)
    if not session.online:
        if not queue_offline or brut:
            raise DeliverOffline()
        # Mise en file plutôt qu'un refus : le message est écrit, le perdre
        # parce que le réseau manque serait le pire des trois résultats
        # possibles. Il part au retour, sauf s'il est retenu.
        session.store.queue_message(
            msg.as_bytes(),
            ", ".join(recipients(msg)),
            msg.get("Subject", ""),
        )
        return t("mail_queued")

    send_fn = send_fn or smtp_send_fn
    transport = None
    if send_fn is smtp_send_fn:
        connect_fn = connect_fn or smtp_connect
        transport = connect_fn(session.account, session.current_secret())
    try:
        served = send_fn(session.account, msg, transport)
    finally:
        if transport is not None:
            transport.quit()

    status = f"{t('mail_sent_to')} {', '.join(served)}"
    if brut:
        return status
    sent_folder = resolve_sent_folder(session)
    exc = file_in_sent(session, msg, verrou)
    if exc is not None:
        _logger.error(
            "%s : APPEND vers %r a échoué",
            session.account.name,
            sent_folder,
            exc_info=exc,
        )
        # En SUFFIXE, cet échec disparaissait en bout d'une ligne de statut
        # qui peut être longue (plusieurs destinataires) — sur la barre
        # d'une seule ligne de haut, la fin est justement ce qui se perd. En
        # PRÉFIXE, en gras rouge, il reste visible même tronqué.
        status = f"[b red]⚠ {t('mail_sent_not_filed')} ({exc})[/] — {status}"
    else:
        # Écriture locale immédiate : une sync ciblée sur Envoyés seul,
        # pour que le message apparaisse sans attendre la prochaine passe
        # complète. `sync_one` ne lève jamais — voir sa docstring — donc un
        # envoi déjà réussi ne peut pas se lire comme un échec parce que
        # cette relecture aurait raté.
        with garde:
            session.syncer.sync_one(sent_folder)
    return status


_LOG_TAIL_LINES = 200


def read_log_tail(
    path, max_lines: int = _LOG_TAIL_LINES
) -> tuple[list[str], str]:
    """Les `max_lines` dernières lignes de `path`, SANS le charger en
    entier — un journal grossit sans limite pendant toute une session, et
    l'ouvrir en entier après plusieurs heures ferait attendre l'utilisateur
    sur des dizaines de mégaoctets pour n'en montrer que la fin. On lit
    donc par blocs DEPUIS LA FIN du fichier, jusqu'à tenir assez de sauts de
    ligne.

    Rend `(lignes, message)` : `message` est vide quand `lignes` est
    utilisable, sinon il dit POURQUOI elle ne l'est pas — absent, vide,
    illisible. Une fenêtre qui s'ouvre en silence sur une liste vide
    reproduit le défaut que cette fonction corrige : une erreur signalée
    quelque part, et aucun journal pour la lire.
    """
    if not path.exists():
        return [], t("mail_log_missing")
    try:
        size = path.stat().st_size
        if size == 0:
            return [], t("mail_log_empty")
        chunk_size = 8192
        data = b""
        with open(path, "rb") as handle:
            remaining = size
            while remaining > 0 and data.count(b"\n") <= max_lines:
                step = min(chunk_size, remaining)
                remaining -= step
                handle.seek(remaining)
                data = handle.read(step) + data
    except OSError as exc:
        # Frontière de résilience DÉLIBÉRÉE : permissions refusées, fichier
        # supprimé entre le `exists()` et l'ouverture, dossier au lieu d'un
        # fichier, etc. — lire le journal ne doit JAMAIS pouvoir faire
        # tomber le client, l'exacte raison pour laquelle cette fenêtre
        # existe.
        return [], f"{t('mail_log_unreadable')} : {exc}"
    # `errors="replace"` : le journal peut contenir des octets qui ne sont
    # pas de l'UTF-8 valide (texte serveur reproduit tel quel dans un
    # message d'exception) — jamais une raison de faire échouer la lecture.
    lines = data.decode("utf-8", "replace").splitlines()[-max_lines:]
    if not lines:
        # `size > 0` au `stat()` ci-dessus ne garantit PAS que `data` soit
        # non vide ici : le fichier peut avoir été TRONQUÉ entre le
        # `stat()` et la lecture (rotation de journal, notamment) —
        # `read()` rend alors `b""` malgré une taille annoncée non nulle.
        # Sans cette garde, ce cas silencieux (aucune ligne, aucun
        # message) reproduirait exactement la plainte que cette fonction
        # existe pour résoudre.
        return [], t("mail_log_empty")
    return lines, ""


def run_tui(
    run_app: bool = True,
    sessions=None,
    config_file=None,
    secret_store=None,
    connect_fn=None,
    base=None,
) -> None:
    """Ouvre le client. `run_app=False` construit l'application sans la lancer,
    ce qui permet de vérifier qu'elle se compose sans écran.

    `config_file`/`secret_store` restent optionnels : sans eux, l'écran
    d'ajout de compte se refuse poliment plutôt que de planter — c'est le cas
    des tests qui montent l'application sans passer par `menu._open_tui`.
    """
    try:
        # `rich` dans le MÊME `try` que `textual` : Textual en dépend
        # durement (ses propres modules l'importent partout, et `Static`
        # accepte un rendu Rich), donc l'absence de l'un ou de l'autre se
        # soigne par le même « installez textual » ci-dessous. `Table` sert
        # à la fenêtre d'aide (`HelpScreen`), la seule vue de ce module qui
        # ait besoin d'une colonne qui se replie sans casser l'alignement.
        from rich.table import Table
        from rich.text import Text
        from textual.app import App, ComposeResult
        from textual.binding import Binding
        from textual.containers import (
            Container,
            Horizontal,
            Vertical,
            VerticalScroll,
        )
        from textual.css.query import NoMatches
        from textual.screen import ModalScreen
        from textual.widgets import (
            Button,
            Checkbox,
            DataTable,
            Footer,
            Header,
            Input,
            Log,
            Select,
            Static,
            TextArea,
            Tree,
        )
    except ImportError:
        print(t("mail_install_textual"))
        return

    from script.todo import todo_prefs
    from script.todo.mail import account_setup, stats, tui_text
    from script.todo.mail import accounts as mail_accounts
    from script.todo.mail.accounts import PRESETS
    from script.todo.mail.rules import engine as rules_engine
    from script.todo.mail.rules import guards as rules_guards
    from script.todo.mail.rules import model as rules_model
    from script.todo.mail.rules import report as rules_report
    from script.todo.mail.rules import storage as rules_storage
    from script.todo.mail.rules.filter import normalize_address, sole_address
    from script.todo.mail.secrets import SecretStore

    class _SearchInput(Input):
        """Le champ de recherche : Échap le vide plutôt que de remonter à
        `MailApp` — visible au pied d'écran (`show=True`, par défaut) SEULEMENT
        tant que ce champ a le focus, contrairement au « Retour » (plein
        écran) de `MailApp`, qui reste cette liaison globale, masquée
        (`show=False`), et inchangée.

        Textual fusionne les liaisons du nœud focalisé et de ses ancêtres
        pour une même touche, et donne priorité à la plus proche du focus
        (`Screen._binding_chain`, vérifié dans la source de Textual) : la
        liaison ci-dessous intercepte donc Échap avant que `MailApp` ne la
        voie, sans code de répartition à écrire à la main — et sa
        description, traduite, n'apparaît au pied d'écran QUE lorsque ce
        champ est le nœud focalisé, exactement le moment où l'action est
        pertinente.
        """

        BINDINGS = [Binding("escape", "clear", t("mail_search_clear"))]

        def action_clear(self) -> None:
            self.app.clear_search()

    class _PanesContainer(Container):
        """`#panes` : reborne les tailles de volets à chaque redimensionnement
        RÉEL du terminal (rétrécir la fenêtre sans toucher à aucun volet ne
        passe par aucune action clavier/souris — sans ce point d'entrée, un
        volet grandi resterait figé à son ancienne taille et écraserait son
        voisin jusqu'à zéro, sans qu'aucune touche ne puisse le récupérer :
        le plafond du volet écrasé se calculerait alors contre SA PROPRE
        région, déjà nulle).

        `Resize` (`bubble=False`, `events.py`) est envoyé DIRECTEMENT au
        widget dont la taille vient de changer — pas à `MailApp` : un essai
        avec `on_resize` sur `MailApp` a mesuré `#panes.region` encore à
        L'ANCIENNE taille au moment où le gestionnaire tournait (le
        redimensionnement RÉEL de l'écran, posté par `App._check_resize`
        vers `Screen`, n'a lieu qu'après un minuteur interne de `1/120` s —
        l'App reçoit l'évènement AVANT ce minuteur, pas après). Ici, en
        recevant l'évènement DE `#panes` lui-même, `self.region` est
        garanti à jour : c'est précisément ce dont ce widget vient de nous
        informer.
        """

        def on_resize(self, event) -> None:
            self.app._apply_pane_sizes()

    class _PaneSplitter(Static):
        """Barre de partage entre `slot` et son voisin — glissable à la
        souris (tâche 25) pour redimensionner les deux, en direct.

        AUCUN état de glissement propre : il vit entièrement sur `MailApp`
        (`_begin_pane_drag`/`_drag_pane_to`/`_end_pane_drag`), qui possède
        déjà `_pane_widgets`/`_pane_dimension`/`_store_pane_size` — une
        taille glissée traverse donc le MÊME `_store_pane_size` que `+`/`-`
        au clavier (tâche 24), jamais un second magasin.

        `can_focus = False` : ce n'est pas un widget de navigation clavier —
        `+`/`-`/`0` redimensionnent déjà le volet qui a le focus, et ajouter
        cette barre à la chaîne de tabulation lui donnerait le focus par
        défaut (`Screen.AUTO_FOCUS`) sans lui offrir la moindre action au
        clavier.

        La capture de souris (`Widget.capture_mouse`, `App.capture_mouse`,
        vérifiées dans la source de Textual 8.2.8) fait que `MouseMove`/
        `MouseUp` atteignent CETTE barre même quand le pointeur a quitté sa
        région d'un seul cellule — `Screen._forward_event` redirige tout
        évènement souris vers `self.app.mouse_captured` dès qu'il est posé,
        quelle que soit la position réelle du pointeur — exactement ce
        qu'un glissement demande. `on_mouse_release` (PAS seulement
        `on_mouse_up`) termine aussi le glissement : `App.capture_mouse`
        poste `MouseRelease` à CE widget dès que la capture change, y
        compris vers `None` — ce qu'`App.push_screen` fait explicitement
        avant d'empiler un écran modal (`l`/`c`/`n`/le coffre), sans jamais
        poster de `MouseUp` — voir `on_mouse_release` ci-dessous pour la
        conséquence si ce signal n'est pas reçu.
        """

        can_focus = False

        def __init__(self, slot: str, **kwargs) -> None:
            # `classes="pane-splitter"` posée ici, pas laissée au site
            # d'appel : les DEUX barres (`compose()`) partagent ainsi le
            # même style (voir `.pane-splitter` dans la CSS de `MailApp`)
            # sans dépendre d'un `classes=` répété à chaque
            # `yield _PaneSplitter(...)`.
            super().__init__("", classes="pane-splitter", **kwargs)
            self._slot = slot
            self.tooltip = t("mail_pane_splitter_tooltip")

        def on_mouse_down(self, event) -> None:
            event.stop()
            self.capture_mouse()
            self.app._begin_pane_drag(
                self._slot, event.screen_x, event.screen_y
            )

        def on_mouse_move(self, event) -> None:
            self.app._drag_pane_to(event.screen_x, event.screen_y)

        def on_mouse_up(self, event) -> None:
            self.app._end_pane_drag()

        def on_mouse_release(self, event) -> None:
            # `App.capture_mouse` (`app.py:3222`, vérifié dans la source de
            # Textual 8.2.8) poste TOUJOURS `MouseRelease` au widget qui
            # ÉTAIT capturé dès que la capture change — y compris vers
            # `None`, ce que `App.push_screen` fait EXPLICITEMENT
            # (`app.py:2937`) avant d'empiler un nouvel écran modal, SANS
            # jamais poster de `MouseUp`. Un glissement encore actif au
            # moment où `l`/`c`/`n`/le coffre pousse un écran perdrait donc
            # sa capture sans que `_end_pane_drag` ne tourne -- l'état de
            # glissement de `MailApp` resterait pointé sur CE volet, et le
            # tout premier `MouseMove` (synthétique, précédant son propre
            # `MouseDown`) d'un glissement SUIVANT et SANS RAPPORT, ailleurs,
            # lui serait appliqué par erreur avant que son `MouseDown` n'ait
            # eu la chance de corriger l'état. Même point de sortie que
            # `on_mouse_up`, `on_app_blur` et `action_toggle_fullscreen` :
            # `_end_pane_drag` est déjà idempotent (`_drag_slot` déjà `None`
            # ne fait rien), donc le recevoir en plus d'un `on_mouse_up`
            # normal (qui appelle lui-même `capture_mouse(None)`, et déclenche
            # donc AUSSI ce `MouseRelease`) est sans danger.
            self.app._end_pane_drag()

    class MailApp(App):
        CSS = """
        #panes { height: 1fr; }
        /* La gouttière est RÉSERVÉE en permanence : sans elle la barre
           apparaît et disparaît selon le nombre de messages, la largeur du
           tableau change sous le curseur, et rien n'indique qu'une liste
           courte l'est vraiment. */
        #list { scrollbar-gutter: stable; }
        #folders { scrollbar-gutter: stable; }
        #preview { padding: 0 1; }
        #status { height: 1; background: $panel; }
        #search_row { display: none; height: auto; }
        #search_row.visible { display: block; }
        #search_row > Input { width: 1fr; }
        #search_row > Button { width: auto; }
        /* `#list_pane`, pas `#list` : le plein écran doit effacer le
        VOLET (recherche + liste), pas seulement son contenu — sinon le
        conteneur garde la taille que lui donne le bloc de la disposition
        active, et laisse un bloc vide à la place de la liste cachée. Une
        seule règle, hors de tout bloc de disposition : elle vaut pour les
        trois, et pour toute disposition ajoutée plus tard. Les deux barres
        de partage (tâche 25) suivent le même sort : plein écran ne laisse
        plus qu'UN volet, rien à partager tant qu'il dure — `action_toggle_
        fullscreen` termine d'ailleurs tout glissement en cours avant de
        poser cette classe, une barre masquée ne pouvant plus recevoir son
        `MouseUp`. */
        .fullscreen #folders, .fullscreen #list_pane,
        .fullscreen #folders_splitter, .fullscreen #list_splitter {
            display: none;
        }
        #attachments_row { height: auto; }
        #attachments_row > Input { width: 1fr; }
        #attachments_row > Button { width: auto; }

        /* Barre de partage (tâche 25) : l'ancienne bordure de `#folders`/
        `#preview` (bloc ci-dessus, avant ce commit) faisait déjà office de
        séparateur visuel — cette classe la REMPLACE par un widget réel,
        glissable, sans ajouter de largeur/hauteur : un widget partagé
        (`_PaneSplitter`) plutôt qu'une bordure signifie aussi UNE seule
        déclaration ici pour les DEUX barres, au lieu d'une bordure séparée
        par volet bordé. `:hover`/`.dragging` sont un signal PUREMENT visuel
        pour la souris — le clavier redimensionne par `+`/`-`/`0`, entièrement
        indépendant de cette barre (voir `MailApp._resize_focused_pane`). */
        .pane-splitter { background: $panel; }
        .pane-splitter:hover, .pane-splitter.dragging { background: $accent; }

        /* Une disposition = une classe sur #panes ; `#right` regroupe
        `#list_pane` (recherche + liste) et `#preview` pour que « split »
        et « stacked » puissent les empiler À CÔTÉ des dossiers, sans
        toucher au reste de l'arbre. Ajouter une disposition n'ajoute
        qu'une entrée à MAIL_LAYOUTS et un bloc comme un de ceux-ci —
        jamais de branche Python par disposition (voir `action_cycle_layout`
        ci-dessous, qui bascule cette classe). Chaque bloc donne aussi
        l'orientation des DEUX barres de partage : une cellule le long de
        l'axe que ce bloc partage déjà (largeur en horizontal, hauteur en
        vertical), `1fr` sur l'autre axe pour occuper tout le volet en face
        — jamais une décision Python, exactement comme les volets eux-mêmes. */
        #panes.layout-columns { layout: horizontal; }
        #panes.layout-columns #folders { width: 28; height: 1fr; }
        #panes.layout-columns #folders_splitter { width: 1; height: 1fr; }
        #panes.layout-columns #right { width: 1fr; height: 1fr; layout: horizontal; }
        #panes.layout-columns #list_pane { width: 2fr; height: 1fr; }
        #panes.layout-columns #list_splitter { width: 1; height: 1fr; }
        #panes.layout-columns #preview { width: 3fr; height: 1fr; }

        #panes.layout-split { layout: horizontal; }
        #panes.layout-split #folders { width: 28; height: 1fr; }
        #panes.layout-split #folders_splitter { width: 1; height: 1fr; }
        #panes.layout-split #right { width: 1fr; height: 1fr; layout: vertical; }
        #panes.layout-split #list_pane { width: 1fr; height: 1fr; }
        #panes.layout-split #list_splitter { width: 1fr; height: 1; }
        #panes.layout-split #preview { width: 1fr; height: 1fr; }

        #panes.layout-stacked { layout: vertical; }
        #panes.layout-stacked #folders { width: 1fr; height: 1fr; }
        #panes.layout-stacked #folders_splitter { width: 1fr; height: 1; }
        #panes.layout-stacked #right { width: 1fr; height: 1fr; layout: vertical; }
        #panes.layout-stacked #list_pane { width: 1fr; height: 1fr; }
        #panes.layout-stacked #list_splitter { width: 1fr; height: 1; }
        #panes.layout-stacked #preview { width: 1fr; height: 1fr; }
        """
        # Hors de la chaîne littérale : ce bloc est GÉNÉRÉ depuis
        # `PANE_SIZE_MIN` (voir `_PANE_MIN_CSS`). Une seule règle pour les
        # trois dispositions et pour toute disposition ajoutée plus tard —
        # le plancher ne dépend d'aucune d'elles.
        CSS += _PANE_MIN_CSS

        BINDINGS = [
            # `h` EN PREMIER : le pied d'écran affiche ces liaisons dans
            # l'ordre de cette liste et n'a pas la largeur de les montrer
            # toutes — la seule qui doive rester visible quand on ne sait
            # plus quoi presser est celle qui explique les autres.
            #
            # SANS `priority=True`, et pas pour la raison qu'on croit : dans
            # le champ de recherche, NI l'une NI l'autre forme ne vole la
            # frappe, parce que `Screen._binding_chain` retire les liaisons
            # de tout caractère imprimable dès que le widget focalisé
            # déclare pouvoir le consommer (`Input.check_consume_key` ;
            # `Screen._binding_chain`, `screen.py:428-435`), avant même la
            # répartition. Ce qu'une priorité changerait est ailleurs : elle
            # est cherchée sur la chaîne NON tronquée aux écrans modaux
            # (`App._check_bindings` lit `Screen._binding_chain` quand
            # `priority=True`, et `_modal_binding_chain` sinon,
            # `app.py:3978`) — `h` ouvrirait
            # alors l'aide PAR-DESSUS l'écran d'écriture, le coffre, ou
            # l'aide elle-même. Le comportement diffère selon la présence
            # de `priority` sur Textual 8.2.8.
            Binding("h", "show_help", t("mail_help_binding")),
            Binding("q", "quit", t("mail_quit_binding")),
            Binding("r", "sync_current", t("mail_sync_current_binding")),
            Binding("R", "sync_all", t("mail_sync_all_binding")),
            # PAS `enter` : `Tree`/`DataTable` (`#folders`/`#list`, les deux
            # seuls widgets focalisables de cet écran) lient déjà `enter` à
            # leur propre `select_cursor`, et Textual donne toujours la
            # priorité à la liaison la plus proche du nœud focalisé
            # (`App._check_bindings`, chaîne `focused.ancestors_with_self` —
            # voir le commentaire de `_SearchInput`). L'un des deux a
            # TOUJOURS le focus par défaut, donc `enter` ici ne se
            # déclenchait en pratique JAMAIS depuis le clavier — confirmé
            # identique au commit de base (défaut préexistant, tâche 23).
            # `z`, libre (grep de tous les `Binding(` de ce module, et de
            # `Tree.BINDINGS`/`DataTable.BINDINGS`/`Input.BINDINGS` dans
            # Textual 8.2.8 : aucun ne revendique une lettre nue), le
            # remplace. Caractère simple, donc SANS `priority=True`, même
            # raison que pour `v` (tâche 23) et que pour `h` ci-dessus, dont
            # le commentaire porte le mécanisme mesuré. L'effet serait ici
            # SILENCIEUX, donc pire : mesuré, un `z` prioritaire frappé sous
            # un écran modal pose bien `fullscreen` sur `#panes`, sans que
            # rien ne bouge à l'écran (le modal la couvre) — et la classe y
            # est ENCORE au renvoi du modal, arbre et liste disparus, sans
            # lien visible avec la touche qui l'a causé. (Ce commentaire a
            # longtemps dit qu'une priorité « casserait la frappe partout
            # ailleurs » : faux, `Input` est servi avant toute liaison —
            # corrigé tâche 26.)
            Binding("z", "toggle_fullscreen", t("mail_fullscreen_binding")),
            Binding(
                "escape",
                "leave_fullscreen",
                t("mail_back_binding"),
                show=False,
            ),
            Binding("slash", "focus_search", t("mail_search_binding")),
            Binding("S", "search_server", t("mail_search_server_binding")),
            Binding("d", "trash_message", t("mail_trash_binding")),
            Binding("m", "move_message", t("mail_move_binding")),
            Binding("D", "empty_trash", t("mail_empty_trash_binding")),
            Binding("p", "cycle_scope", t("mail_scope_binding")),
            Binding("s", "mark_seen", t("mail_mark_seen_binding")),
            Binding("u", "mark_unseen", t("mail_mark_unseen_binding")),
            Binding("asterisk", "toggle_flagged", t("mail_flagged_binding")),
            Binding("M", "mark_all_seen", t("mail_all_seen_binding")),
            # `x` et NON `space` : `Tree` — l'arbre des dossiers, qui a le
            # focus au démarrage — lie déjà l'espace au repli d'un nœud et
            # le consomme avant les liaisons de l'application. `x` est
            # aussi la touche que les clients web emploient pour cocher.
            Binding("x", "toggle_selection", t("mail_select_binding")),
            Binding("w", "save_attachment", t("mail_save_attachment_binding")),
            Binding("c", "compose", t("mail_compose_binding")),
            Binding("a", "reply", t("mail_reply_binding")),
            Binding("A", "reply_all", t("mail_reply_all_binding")),
            Binding("f", "forward", t("mail_forward_binding")),
            Binding("n", "add_account", t("mail_add_account_binding")),
            Binding("l", "show_log", t("mail_log_binding")),
            Binding("i", "show_stats", t("mail_stats_binding")),
            Binding(
                "I", "show_report_settings", t("mail_stats_report_binding")
            ),
            Binding("g", "cycle_list_mode", t("mail_list_mode_binding")),
            Binding("F", "manage_folders", t("mail_folder_binding")),
            Binding("o", "show_outbox", t("mail_outbox_binding")),
            Binding("e", "show_rules", t("mail_rules_binding")),
            Binding("v", "cycle_layout", t("mail_layout_binding")),
            Binding("plus", "grow_pane", t("mail_pane_grow_binding")),
            Binding("minus", "shrink_pane", t("mail_pane_shrink_binding")),
            Binding("0", "reset_pane_sizes", t("mail_pane_reset_binding")),
        ]

        def __init__(
            self,
            sessions,
            config_file=None,
            secret_store=None,
            connect_fn=None,
            base=None,
        ):
            super().__init__()
            self.sessions = sessions
            self.config_file = config_file
            self.secret_store = secret_store
            self.connect_fn = connect_fn
            self.base = base
            self.refs: list[MailboxRef] = []
            self.current_ref: MailboxRef | None = None
            self.metas = []
            self.query = ""
            self.search_scope = "folder"
            # Les messages cochés, par leur clé de ligne. Un dictionnaire et
            # non un ensemble : le message lui-même doit survivre au
            # rechargement de la liste, sans quoi cocher puis synchroniser
            # perdrait ce qu'on avait désigné.
            self.selection = {}
            # Lue ici, PAS dans `on_mount` : `compose()` a besoin de la
            # classe CSS de disposition dès le premier rendu, avant que
            # `on_mount` ne tourne. `resolve_layout` protège contre une
            # valeur absente ou corrompue dans `todo_prefs`.
            self.mail_layout = resolve_layout(
                todo_prefs.get("mail_layout", _LAYOUT_IDS[0])
            )
            # Les erreurs de la DERNIÈRE synchronisation de chaque compte
            # (`report.errors`, voir `_sync` ci-dessous) — lues par
            # `LogScreen` (touche `l`). Elles comptent parce qu'elles
            # peuvent ne JAMAIS atteindre le fichier : si
            # `_configure_mail_logging` échoue à écrire (dossier
            # `~/.erplibre` refusé, disque plein), ce dictionnaire reste le
            # seul endroit où l'utilisateur peut encore les lire.
            self.session_errors: dict[str, list[str]] = {}
            # L'auto-refresh et un `r`/`R` manuel lancent chacun `_sync` via
            # `run_worker(thread=True)`, sans exclusivité : deux passes
            # peuvent tourner en vrais threads en même temps, et `imaplib`
            # n'est pas thread-safe. L'annulation ne protège pas contre ça
            # (elle ne s'applique pas aux workers de type thread) — ce verrou
            # sérialise donc les accès réseau à sa place.
            self._sync_lock = threading.RLock()
            # État d'un glissement de barre de partage EN COURS (souris,
            # tâche 25) ; `None` hors glissement. Vit sur l'App — pas sur la
            # barre elle-même (`_PaneSplitter`) — puisque c'est ici que
            # vivent déjà `_pane_widgets`/`_pane_dimension`/`_store_pane_size`,
            # et que `on_app_blur` doit pouvoir terminer un glissement sans
            # savoir QUELLE des deux barres l'a commencé.
            self._drag_slot: str | None = None
            self._drag_dimension: str | None = None
            self._drag_origin: int | None = None
            self._drag_base: int | None = None
            self._drag_last_value: int | None = None

        # -- composition ------------------------------------------------

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            # La classe posée ici — pas dans `on_mount` — donne la bonne
            # disposition dès le premier rendu, sans reconstruire l'arbre au
            # changement : `action_cycle_layout` ne fait ensuite que
            # basculer cette classe.
            with _PanesContainer(id="panes", classes=self._layout_class()):
                yield Tree(t("mail_accounts"), id="folders")
                # Barre de partage (tâche 25) : glissable à la souris pour
                # redimensionner `folders`/`right` — voir `_PaneSplitter` et
                # `_pane_total` (le total partagé par les deux volets
                # ADJUSTABLE exclut cette barre, de taille fixe).
                yield _PaneSplitter("folders", id="folders_splitter")
                # `#right` regroupe la liste et l'aperçu en UN volet, pour
                # que « split » et « stacked » puissent les empiler l'un
                # sur l'autre à côté des dossiers — un arrangement qu'un
                # simple `Horizontal`/`Vertical` à plat sur les trois volets
                # ne peut pas exprimer (voir la CSS de la classe).
                with Container(id="right"):
                    with Vertical(id="list_pane"):
                        with Horizontal(id="search_row"):
                            yield _SearchInput(
                                placeholder=t("mail_search"), id="search"
                            )
                            yield Button(
                                "✕",
                                id="search_clear",
                                # Ce survol est un bonus pour la souris, PAS
                                # le chemin accessible : Textual ne
                                # déclenche les tooltips que sur
                                # `MouseMove` (`screen.py:_handle_mouse_move`
                                # / `_handle_tooltip_timer`, vérifié dans la
                                # source) — aucun clavier n'y mène. Le
                                # chemin traduit et découvrable au clavier
                                # est la liaison Échap de `_SearchInput`,
                                # visible au pied d'écran pendant que ce
                                # champ a le focus.
                                tooltip=t("mail_search_clear"),
                            )
                        yield DataTable(id="list", cursor_type="row")
                    # Barre de partage entre `list_pane` et `preview` — même
                    # motif que `folders_splitter` ci-dessus, un volet plus
                    # bas dans l'arbre.
                    yield _PaneSplitter("list_pane", id="list_splitter")
                    yield Static("", id="preview")
            yield Static("", id="status")
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#list", DataTable)
            table.add_columns(
                " ", t("mail_from"), t("mail_subject"), t("mail_date")
            )
            self.reload_folders()
            self.run_worker(self.sync_all_worker, thread=True)
            interval = todo_prefs.get("mail_refresh_sec", 300)
            if interval:
                # Minuterie posée à l'ouverture, retirée avec l'écran : aucune
                # synchronisation ne tourne quand le TUI n'est pas là.
                self.set_interval(
                    interval,
                    lambda: self.run_worker(self.sync_all_worker, thread=True),
                )
            # Différé : à `on_mount`, `#panes`/`#right` n'ont pas encore
            # forcément leur taille réelle (le premier passage de mise en
            # page n'a pas eu lieu) — `clamp_pane_size` ne pourrait alors
            # rien borner. `call_after_refresh` attend ce premier rendu.
            # Les redimensionnements SUIVANTS du terminal sont couverts par
            # `_PanesContainer.on_resize`, pas ici (voir son commentaire :
            # un `on_resize` posé sur `MailApp` mesurait encore l'ANCIENNE
            # taille de `#panes` au moment où il tournait).
            self.call_after_refresh(self._apply_pane_sizes)

        # -- données ----------------------------------------------------

        def reload_folders(self) -> None:
            self.refs = mailbox_refs(self.sessions)
            tree = self.query_one("#folders", Tree)
            tree.clear()
            by_account: dict[str, list[MailboxRef]] = {}
            for ref in self.refs:
                by_account.setdefault(ref.account_name, []).append(ref)
            for session in self.sessions:
                mark = "" if session.online else " ⚠"
                node = tree.root.add(
                    f"{session.account.name}{mark}", expand=True
                )
                for ref in by_account.get(session.account.name, []):
                    label = ref.display
                    if ref.unseen:
                        label = f"{label}  {ref.unseen}"
                    node.add_leaf(label, data=ref)
            tree.root.add_leaf(
                f"+ {t('mail_account_add')}", data=ADD_ACCOUNT_NODE
            )
            tree.root.expand()
            if self.current_ref is None and self.refs:
                self.select_ref(self.refs[0])
            else:
                # Un dossier est déjà ouvert : `select_ref` ne le
                # rappellerait pas ici, mais ce que la synchronisation vient
                # d'écrire au cache — un message qui arrive, un « lu »
                # changé ailleurs — doit tout de même atteindre l'écran,
                # SANS redémarrer le client pour le voir.
                self.refresh_current_folder()

        def session_for(self, name: str) -> Session | None:
            return next(
                (s for s in self.sessions if s.account.name == name), None
            )

        def refresh_folder_counts(self) -> None:
            """Réécrit les compteurs de l'arbre depuis le cache, EN PLACE.

            `reload_folders` rebâtit l'arbre et ramène son curseur à la
            racine : marquer un message lu au clavier ne doit pas déplacer
            la sélection de qui le fait. Seuls les libellés changent ici.

            Sans cet appel, l'arbre garde le compteur de la dernière passe
            de synchronisation — jusqu'à cinq minutes par défaut — et
            affiche « 201 » à côté d'une ligne de statut qui vient
            d'annoncer « Marqués lus : 201 ».
            """
            try:
                tree = self.query_one("#folders", Tree)
            except NoMatches:
                return
            frais = {
                (r.account_name, r.folder_name): r.unseen
                for r in mailbox_refs(self.sessions)
            }
            for compte in tree.root.children:
                for feuille in compte.children:
                    ref = feuille.data
                    if not isinstance(ref, MailboxRef):
                        continue
                    unseen = frais.get((ref.account_name, ref.folder_name), 0)
                    if unseen == ref.unseen:
                        continue
                    # `ref` est l'objet que porte le nœud ET celui de
                    # `self.refs` : le corriger suffit pour les deux.
                    ref.unseen = unseen
                    feuille.set_label(
                        f"{ref.display}  {unseen}" if unseen else ref.display
                    )

        def select_ref(self, ref: MailboxRef) -> None:
            self.current_ref = ref
            session = self.session_for(ref.account_name)
            state = session.store.folder_state(ref.folder_name)
            self.metas = (
                session.store.list_messages(state["id"], limit=PAGE)
                if state
                else []
            )
            self.refresh_list()
            self.refresh_folder_counts()

        def charger_la_suite(self) -> bool:
            """Ajoute la page suivante du dossier ouvert. Vrai si elle est
            venue.

            Le dossier n'est pas chargé d'un coup : une boîte de trente
            mille messages construirait trente mille lignes à chaque
            ouverture et à chaque frappe de recherche, là où l'écran répond
            aujourd'hui tout de suite. Il arrive donc par pages, et c'est le
            curseur qui approche du bas qui appelle la suivante — sans quoi
            la liste s'arrêterait à la première page sans le dire, ce qui se
            lit comme un cache incomplet.
            """
            if self.current_ref is None or self.query:
                # Avec une requête, la liste n'est plus le dossier mais le
                # résultat, qui a son propre plafond.
                return False
            session = self.session_for(self.current_ref.account_name)
            if session is None:
                return False
            etat = session.store.folder_state(self.current_ref.folder_name)
            if not etat:
                return False
            suite = session.store.list_messages(
                etat["id"], limit=PAGE, offset=len(self.metas)
            )
            if not suite:
                return False
            self.metas.extend(suite)
            return True

        def reste_a_charger(self) -> int:
            """Ce que le CACHE tient encore et que la liste ne montre pas.

            Le compte du cache, pas le `total` du dossier : celui-ci vient
            du serveur et compte des messages dont le cache n'a parfois
            aucun.
            """
            if self.current_ref is None:
                return 0
            session = self.session_for(self.current_ref.account_name)
            if session is None:
                return 0
            etat = session.store.folder_state(self.current_ref.folder_name)
            if not etat:
                return 0
            try:
                return max(
                    0,
                    session.store.count_messages(etat["id"]) - len(self.metas),
                )
            except Exception:
                return 0

        def action_cycle_list_mode(self) -> None:
            self.list_mode = tui_text.next_list_mode(
                getattr(self, "list_mode", "flat")
            )
            self.set_status(t(f"mail_list_mode_{self.list_mode}"))
            self.refresh_list()

        def visible_metas(self) -> list:
            """Les messages à afficher : le dossier, ou le résultat.

            Sans requête, la page chargée. Avec une requête, le CACHE
            ENTIER — `filter_messages` ne voyait que les 500 messages de la
            page courante et rendait « aucun résultat » sur une boîte qui
            en contenait des milliers, sans jamais dire qu'elle n'avait pas
            regardé plus loin.
            """
            if not self.query:
                return list(self.metas)
            if not getattr(self, "recherche_complete", True):
                return tui_text.filter_messages(self.metas, self.query)
            if self.current_ref is None:
                return tui_text.filter_messages(self.metas, self.query)
            try:
                return self._resultats()
            except Exception:
                # Un cache verrouillé ou un index absent ne doit pas vider
                # la liste : on retombe sur ce qui est chargé.
                return tui_text.filter_messages(self.metas, self.query)

        def _resultats(self) -> list:
            """Le résultat de la recherche, selon la portée choisie.

            Chaque message rapporte D'OÙ il vient. Sans cette provenance,
            une ligne venue d'un autre dossier ne serait plus qu'un UID, et
            un UID ne désigne rien tout seul : le même nombre nomme un
            autre message dans chaque dossier.
            """
            portee = getattr(self, "search_scope", "folder")
            if portee == "all":
                return self._resultats_partout()
            session = self.session_for(self.current_ref.account_name)
            folder_id = None
            if portee == "folder":
                etat = session.store.folder_state(self.current_ref.folder_name)
                folder_id = (etat or {}).get("id")
                if folder_id is None:
                    return tui_text.filter_messages(self.metas, self.query)
            return self._signer(
                session.store.search(self.query, folder_id=folder_id),
                session,
            )

        def _resultats_partout(self) -> list:
            """Tous les comptes, du plus récent au plus ancien.

            Le plafond s'applique à la liste ASSEMBLÉE : sans lui, dix
            comptes rendraient dix fois le plafond d'un seul, et la fenêtre
            afficherait une liste qu'aucune touche ne parcourt.
            """
            trouves: list = []
            for session in self.sessions:
                try:
                    trouves.extend(
                        self._signer(session.store.search(self.query), session)
                    )
                except Exception:
                    # Le cache d'un compte peut être fermé ou verrouillé :
                    # les autres comptes répondent quand même.
                    _logger.exception(
                        "recherche dans %s", session.account.name
                    )
            trouves.sort(key=lambda m: m.date, reverse=True)
            return trouves[:500]

        @staticmethod
        def _signer(metas: list, session) -> list:
            """Pose le compte sur des résultats que le cache, qui n'en
            connaît qu'un, ne peut pas signer lui-même."""
            for meta in metas:
                meta.account = session.account.name
            return metas

        def meta_origin(self, meta):
            """(session, dossier) d'où vient ce message.

            Un message de la liste ordinaire ne porte pas de provenance :
            il vient du dossier ouvert. Un résultat de recherche élargie,
            lui, la porte — et c'est elle qui doit servir, sinon l'écran
            lirait le corps du message qui porte le même UID dans le
            dossier courant, et les touches de rangement agiraient dessus.
            """
            defaut_compte = (
                self.current_ref.account_name if self.current_ref else ""
            )
            defaut_dossier = (
                self.current_ref.folder_name if self.current_ref else ""
            )
            session = self.session_for(
                getattr(meta, "account", "") or defaut_compte
            )
            return session, (getattr(meta, "folder", "") or defaut_dossier)

        def action_cycle_scope(self) -> None:
            """`p` : dossier ouvert → compte entier → tous les comptes.

            La portée est un choix EXPLICITE. Élargir d'office ferait
            déchiffrer, en mode chiffré, des dossiers que personne n'a
            demandés, à chaque frappe.
            """
            suivante = _PORTEES[
                (_PORTEES.index(getattr(self, "search_scope", "folder")) + 1)
                % len(_PORTEES)
            ]
            self.search_scope = suivante
            self.set_status(t(f"mail_scope_{suivante}"))
            self.recherche_complete = True
            self.refresh_list()

        def lignes_a_afficher(self) -> list:
            """(message, niveau d'indentation) pour le mode courant.

            Le niveau vaut 0 partout sauf en mode fil : la colonne du sujet
            le porte, ce qui évite une colonne de plus dans une largeur
            déjà comptée.
            """
            metas = self.visible_metas()
            mode = getattr(self, "list_mode", "flat")
            if mode == "threads":
                return tui_text.group_threads(metas)
            if mode == "unread":
                return [(m, 0) for m in tui_text.only_unread(metas)]
            return [(m, 0) for m in metas]

        def refresh_list(self) -> None:
            import time

            table = self.query_one("#list", DataTable)
            table.clear()
            now = int(time.time())
            for meta, niveau in self.lignes_a_afficher():
                table.add_row(
                    self._marques(meta),
                    tui_text.truncate(tui_text.short_addr(meta.frm), 22),
                    tui_text.truncate(
                        ("  ↳ " * niveau)
                        + self._provenance(meta)
                        + (meta.subject or t("mail_no_subject")),
                        48,
                    ),
                    tui_text.format_date(meta.date, now),
                    key=self._cle(meta),
                )

        def _marques(self, meta) -> str:
            """La colonne d'état : non-lu, suivi, ou les deux.

            Deux caractères et non un : un message peut être non lu ET
            suivi, et faire choisir une seule marque en perdrait une.
            """
            return (
                ("✓" if self._cle(meta) in self.selection else " ")
                + ("●" if tui_text.is_unread(meta.flags) else " ")
                + ("★" if tui_text.is_flagged(meta.flags) else " ")
            )

        def _provenance(self, meta) -> str:
            """« [Archives] » devant le sujet d'un résultat venu d'ailleurs.

            Rien devant un message du dossier ouvert : le répéter sur
            chaque ligne d'une liste ordinaire mangerait la largeur du
            sujet sans rien apprendre.
            """
            dossier = getattr(meta, "folder", "")
            compte = getattr(meta, "account", "")
            courant = self.current_ref
            if not dossier or (
                courant
                and dossier == courant.folder_name
                and (not compte or compte == courant.account_name)
            ):
                return ""
            if compte and courant and compte != courant.account_name:
                return f"[{compte}/{dossier}] "
            return f"[{dossier}] "

        @staticmethod
        def _cle(meta) -> str:
            """La clé d'une ligne du tableau, unique dans TOUTE la liste.

            L'UID seul ne l'est pas : le même nombre nomme un message
            différent dans chaque dossier, et une recherche élargie les
            met côte à côte. `DataTable` refuse deux fois la même clé.
            """
            compte = getattr(meta, "account", "")
            dossier = getattr(meta, "folder", "")
            return f"{compte}\x1f{dossier}\x1f{meta.uid}"

        def refresh_current_folder(self) -> None:
            """Recharge les messages du dossier affiché depuis le cache et
            redessine la liste, SANS perdre le curseur ni le filtre de
            recherche en cours.

            Appelée après une synchronisation (`_sync`, via
            `reload_folders`) ou un envoi (`_after_compose`) : contrairement
            à `select_ref` — changement DÉLIBÉRÉ de dossier, où revenir en
            tête de liste est attendu — celle-ci s'exécute pendant que
            l'utilisateur regarde peut-être déjà cette liste, ce qui rend le
            curseur et le filtre aussi importants à préserver que les
            données elles-mêmes.
            """
            if self.current_ref is None:
                return
            session = self.session_for(self.current_ref.account_name)
            if session is None:
                return
            # Capturé AVANT de recharger `self.metas` : `current_meta()` lit
            # encore l'ancienne liste et la position actuelle du curseur.
            current = self.current_meta()
            current_cle = self._cle(current) if current is not None else None
            state = session.store.folder_state(self.current_ref.folder_name)
            # AUTANT de messages qu'il y en avait : une passe de
            # synchronisation ne doit pas rendre à la liste la taille d'une
            # page, sous un curseur qui était descendu bien plus bas.
            combien = max(PAGE, len(self.metas))
            self.metas = (
                session.store.list_messages(state["id"], limit=combien)
                if state
                else []
            )
            self.refresh_list()
            self.refresh_folder_counts()
            if current_cle is None:
                return
            from textual.widgets.data_table import RowDoesNotExist

            table = self.query_one("#list", DataTable)
            try:
                row_index = table.get_row_index(current_cle)
            except RowDoesNotExist:
                # Le message qui avait le focus a disparu du dossier (purge
                # de synchronisation, suppression ailleurs) : `refresh_list`
                # a déjà laissé le curseur là où `DataTable.clear()` le
                # remet — en tête de liste, seul choix qui ne pointe pas
                # dans le vide.
                return
            table.move_cursor(row=row_index)

        def action_toggle_selection(self) -> None:
            """`x` : coche ou décoche le message sous le curseur.

            Le curseur descend d'une ligne ensuite : cocher se fait en
            rafale, et remonter d'une ligne après chaque coche serait le
            geste le plus fatigant de l'écran.
            """
            meta = self.current_meta()
            if meta is None:
                return
            cle = self._cle(meta)
            if cle in self.selection:
                del self.selection[cle]
            else:
                self.selection[cle] = meta
            table = self.query_one("#list", DataTable)
            ligne = table.cursor_row
            self.refresh_list()
            if ligne is not None and ligne + 1 < table.row_count:
                table.move_cursor(row=ligne + 1)
            elif ligne is not None and ligne < table.row_count:
                table.move_cursor(row=ligne)
            self.set_status(
                f"{t('mail_select_count')} {len(self.selection)}"
                if self.selection
                else t("mail_select_none")
            )

        def cibles(self) -> list:
            """Ce sur quoi la prochaine touche agit : les cochés, ou celui
            sous le curseur.

            Une sélection vide ne veut pas dire « rien » mais « ce qui est
            désigné » : sans cela, chaque touche exigerait de cocher
            d'abord, et le geste à un seul message coûterait une frappe de
            plus qu'avant.
            """
            if self.selection:
                return list(self.selection.values())
            meta = self.current_meta()
            return [meta] if meta is not None else []

        def _vider_selection(self) -> None:
            """À la fin d'un lot : ce qui a été traité n'est plus désigné.

            Le garder ferait agir la touche suivante sur des messages déjà
            partis ailleurs — et sur un déplacement, sur des UID qui ne
            valent plus rien dans leur dossier d'origine.
            """
            self.selection = {}

        def current_meta(self):
            table = self.query_one("#list", DataTable)
            if table.cursor_row is None or not self.metas:
                return None
            # Le MÊME ordre que l'affichage : en mode fil, `visible_metas`
            # seul rendrait le message d'une autre ligne que celle où le
            # curseur se trouve.
            shown = self.lignes_a_afficher()
            if table.cursor_row >= len(shown):
                return None
            return shown[table.cursor_row][0]

        # -- événements -------------------------------------------------

        def on_tree_node_selected(self, event) -> None:
            data = getattr(event.node, "data", None)
            if data == ADD_ACCOUNT_NODE:
                self.action_add_account()
            elif isinstance(data, MailboxRef):
                self.select_ref(data)

        def on_data_table_row_highlighted(self, event) -> None:
            self._charger_si_au_bas(event.cursor_row)
            self.show_preview()

        def _charger_si_au_bas(self, ligne: int) -> None:
            """Charge la page suivante quand le curseur en approche.

            À quelques lignes du bas, PAS sur la dernière : la page arrive
            alors avant qu'on la demande, et le défilement ne marque pas
            d'arrêt.
            """
            if self.query or ligne is None:
                return
            if ligne < len(self.lignes_a_afficher()) - MARGE_PAGE:
                return
            if not self.charger_la_suite():
                return
            table = self.query_one("#list", DataTable)
            position = table.cursor_row
            self.refresh_list()
            # `refresh_list` vide le tableau, donc le curseur : sans cette
            # remise en place, charger la suite ramènerait en tête de liste
            # celui qui descendait.
            if position is not None and position < table.row_count:
                table.move_cursor(row=position)

        def on_input_changed(self, event) -> None:
            if event.input.id != "search" or event.value == self.query:
                # `clear_search` a déjà mis `self.query` à jour ET rafraîchi
                # la liste avant que Textual ne poste ce message — sans ce
                # garde-fou, `refresh_list()` tournerait une seconde fois
                # pour rien dès que le champ change de valeur.
                return
            self.query = event.value
            # Sans index, chaque frappe déchiffrerait toute la boîte : plus
            # de quatre secondes par lettre sur une grande boîte, sur le fil
            # de l'interface. On s'en tient alors à ce qui est chargé, et
            # Entrée lance la recherche complète.
            self.recherche_complete = self.search_is_live()
            self.refresh_list()
            if not self.recherche_complete and event.value:
                self.set_status(t("mail_search_press_enter"))

        def on_input_submitted(self, event) -> None:
            if event.input.id != "search":
                return
            self.recherche_complete = True
            self.refresh_list()

        def search_is_live(self) -> bool:
            """Vrai si la recherche peut suivre la frappe.

            L'index répond en millisecondes ; le balayage déchiffré coûte
            des secondes et ne peut pas se rejouer à chaque lettre.
            """
            if self.current_ref is None:
                return True
            try:
                session = self.session_for(self.current_ref.account_name)
                return session.store.search_is_indexed()
            except Exception:
                return False

        @staticmethod
        def _entete(meta) -> Text:
            """Rend l'en-tête d'un aperçu : étiquettes en gras, valeurs du
            message, taille, puis une ligne vide.

            Un `Text`, PAS une chaîne de balisage : expéditeur, sujet et
            corps viennent du message, donc de n'importe qui. Un jeton de
            suivi contenant « [...] » est analysé comme une balise et fait
            lever `MarkupError` à l'affichage. `escape()` ne suffit pas : il
            laisse justement ces formes intactes. Un `Text` n'est jamais
            analysé.
            """
            header = Text()
            for etiquette, valeur in (
                (t("mail_from"), meta.frm),
                (t("mail_to"), meta.to),
                (t("mail_subject"), meta.subject),
                (t("mail_date"), tui_text.format_date_full(meta.date)),
            ):
                header.append(f"{etiquette} ", style="bold")
                header.append(f"{valeur}\n")
            header.append(f"{tui_text.format_size(meta.size)}\n\n")
            return header

        def show_preview(self) -> None:
            meta = self.current_meta()
            preview = self.query_one("#preview", Static)
            if meta is None or self.current_ref is None:
                preview.update("")
                return
            session, dossier = self.meta_origin(meta)
            if session is None:
                preview.update("")
                return
            header = self._entete(meta)
            # Le cache d'abord : c'est du SQLite, il a son propre verrou, et
            # rien n'y attend le réseau.
            raw = session.store.read_body(dossier, meta.uid)
            if raw is not None:
                self._peindre_corps(preview, header, raw)
                return
            if not session.online:
                preview.update(header + Text(t("mail_body_needs_network")))
                return
            # Le corps manque : il faut le réseau, donc un FIL DE TRAVAIL.
            # Le lire ici tiendrait le dialogue IMAP sur le fil de
            # l'interface, sans le verrou que prennent tous les autres
            # échanges — deux fils sur une même socket, l'un lisant la
            # réponse de l'autre. Un fil y lève « abort command: UID =>
            # unexpected response », l'autre attend trente secondes puis
            # « timed out », et la socket reste condamnée pour la session.
            preview.update(header + Text(t("mail_body_loading")))
            self.run_worker(
                lambda: self._corps_en_fond(
                    session, dossier, meta, self._cle(meta)
                ),
                thread=True,
            )

        def _corps_en_fond(self, session, dossier, meta, cle) -> None:
            """Télécharge un corps SOUS le verrou, puis le fait peindre.

            `cle` est la ligne qui l'a demandé : le curseur a pu bouger
            pendant l'aller-retour, et peindre alors ce corps afficherait le
            message d'une autre ligne que celle désignée.
            """
            try:
                with self._sync_lock:
                    raw = session.avec_lien(
                        lambda _t: session.syncer.fetch_body(dossier, meta.uid)
                    )
            except Exception as exc:
                _logger.exception("corps de %s/%s", dossier, meta.uid)
                self.call_from_thread(self._corps_a_echoue, cle, exc)
                return
            self.call_from_thread(self._corps_est_la, cle, raw)

        def _corps_est_la(self, cle, raw) -> None:
            """Peint le corps arrivé, si la ligne qui l'a demandé tient
            encore l'écran.

            `NoMatches` est le cas ordinaire et non une anomalie : l'aperçu
            n'existe plus quand un écran modal l'a couvert ou que le client
            se ferme pendant l'aller-retour. Laisser lever ferait échouer un
            fil de travail pour un corps que plus personne ne regarde.
            """
            try:
                courant = self.current_meta()
                if courant is None or self._cle(courant) != cle:
                    return
                # Peindre le corps REÇU, plutôt que de repasser par
                # `show_preview` : celui-ci relit le cache et, s'il n'y
                # trouve rien, relance un fil de travail — un cache qui
                # refuse l'écriture donnerait une suite sans fin de
                # téléchargements du même corps.
                self._peindre_corps(
                    self.query_one("#preview", Static),
                    self._entete(courant),
                    raw,
                )
            except NoMatches:
                return

        def _corps_a_echoue(self, cle, exc) -> None:
            """Dit l'échec DANS l'aperçu, et non dans la barre d'état.

            Celle-ci porte le résultat du dernier geste demandé — « 2
            marqués lus », « déplacé vers Archives ». Un corps qui ne vient
            pas l'effacerait sans que l'utilisateur ait rien demandé, alors
            que l'aperçu est justement l'endroit où il regarde.
            """
            try:
                courant = self.current_meta()
                if courant is None or self._cle(courant) != cle:
                    return
                self.query_one("#preview", Static).update(
                    self._entete(courant)
                    + Text(f"{t('mail_body_error')} {exc}")
                )
            except NoMatches:
                return

        @staticmethod
        def _peindre_corps(preview, header, raw) -> None:
            body, attachments = tui_text.extract_body(raw or b"")
            if attachments:
                # Le nom de fichier vient lui aussi du message.
                header.append(f"{t('mail_attachments')}\n")
                for piece in attachments:
                    header.append(
                        f"  📎 {piece.filename}  "
                        f"{tui_text.format_size(piece.size)}\n"
                    )
                header.append("\n")
            preview.update(header + Text(body))

        # -- actions ----------------------------------------------------

        def action_toggle_fullscreen(self) -> None:
            # `.fullscreen` masque `#folders_splitter`/`#list_splitter`
            # (voir la CSS) : un glissement EN COURS sur l'une des deux
            # perdrait alors la capture de souris sans jamais recevoir son
            # `MouseUp` (le widget capturé devient introuvable pour
            # `Screen._forward_event`, vérifié dans la source de Textual) —
            # terminer le glissement AVANT de masquer, comme une levée
            # normale, plutôt que de laisser l'app coincée en glissement.
            self._end_pane_drag()
            self.query_one("#panes").toggle_class("fullscreen")

        def action_leave_fullscreen(self) -> None:
            self.query_one("#panes").remove_class("fullscreen")

        def _layout_class(self) -> str:
            return f"layout-{self.mail_layout}"

        def action_cycle_layout(self) -> None:
            """Touche `v` : la disposition suivante, appliquée SANS
            reconstruire les volets — seule la classe CSS de `#panes`
            change, donc le dossier sélectionné, le message en surbrillance,
            le filtre de recherche et le plein écran (une AUTRE classe du
            même nœud, jamais touchée ici) traversent le changement intacts.
            """
            self.mail_layout = next_layout(self.mail_layout)
            panes = self.query_one("#panes")
            for layout_id in _LAYOUT_IDS:
                panes.remove_class(f"layout-{layout_id}")
            panes.add_class(self._layout_class())
            todo_prefs.set("mail_layout", self.mail_layout)
            # La disposition qui vient de prendre la classe a peut-être SA
            # PROPRE personnalisation de tailles (ou aucune) — jamais celle
            # de la précédente, qui resterait sinon posée en style en ligne
            # sur les mêmes widgets (ils ne sont pas reconstruits).
            self._apply_pane_sizes()
            self.set_status(
                f"{t('mail_layout_switched')}"
                f" {t(_LAYOUT_I18N_KEYS[self.mail_layout])}"
            )

        # -- tailles des volets (`+`/`-`/`0`) -----------------------------

        def _pane_widgets(self, slot: str):
            """Le volet réglable `slot`, et le conteneur PARENT dont il
            partage l'espace avec son unique voisin — `#panes` pour
            `folders` (voisin `#right`), `#right` pour `list_pane` (voisin
            `#preview`). Le voisin lui-même n'est jamais retourné : il reste
            toujours `1fr`, jamais stocké ni fixé.
            """
            if slot == "folders":
                return self.query_one("#folders"), self.query_one("#panes")
            return self.query_one("#list_pane"), self.query_one("#right")

        def _pane_dimension(self, container) -> str:
            """« width » si `container` range ses enfants horizontalement,
            sinon « height ». Lue sur la disposition RÉELLEMENT posée
            (`styles.layout`, calculée depuis la classe CSS active de
            `#panes`/`#right`) — jamais une table `if layout == ...` :
            ajouter une disposition n'ajoute qu'un bloc CSS, jamais une
            entrée ici.
            """
            layout = container.styles.layout
            return (
                "width"
                if layout is not None and layout.name == "horizontal"
                else "height"
            )

        def _pane_total(self, slot: str, parent) -> int:
            """L'espace que `slot` et son unique voisin `1fr` se partagent
            RÉELLEMENT — jamais `parent.region` telle quelle : la barre de
            partage insérée ENTRE eux a une taille FIXE (`_SPLITTER_SIZE`)
            qui n'appartient à NI L'UN NI L'AUTRE. La compter dans le total
            partageable laisserait le voisin `sibling_minimum - (taille de
            la barre)` au plafond plutôt que `sibling_minimum` — la même
            erreur d'une cellule que la bordure, sous une autre forme. La
            taille est lue sur le widget RÉEL de la barre, jamais recopiée
            depuis la CSS : une seule source de vérité.

            Généralise à « un seul voisin FIXE et CONNU » (la barre), pas à
            un nombre arbitraire d'enfants supplémentaires : si `#panes`/
            `#right` héberge un jour un TROISIÈME enfant fixe en plus de
            `slot`, de son voisin `1fr` et de CETTE barre, cette soustraction
            devra en tenir compte explicitement — elle ne les détecte pas
            toute seule.
            """
            dimension = self._pane_dimension(parent)
            splitter = self.query_one(f"#{_SPLITTER_IDS[slot]}")
            return getattr(parent.region, dimension) - getattr(
                splitter.region, dimension
            )

        def _focused_pane_slot(self) -> str | None:
            """Le volet réglable qui contient le nœud focalisé, déterminé
            par ASCENDANCE (`ancestors_with_self`) — jamais par le TYPE du
            widget focalisé (`Tree`, `DataTable`, `Input`) : `#list` et le
            champ de recherche vivent tous deux dans `#list_pane`, donc les
            deux mènent au même volet sans code séparé pour chacun. Rend
            `None` si rien n'a le focus ou si le focus est ailleurs (aucun
            volet réglable aujourd'hui n'est hors de `#folders`/`#list_pane`,
            mais un futur widget focalisable hors des deux ne doit pas
            planter ici).
            """
            focused = self.focused
            if focused is None:
                return None
            chain = focused.ancestors_with_self
            if self.query_one("#folders") in chain:
                return "folders"
            if self.query_one("#list_pane") in chain:
                return "list_pane"
            return None

        def _clear_pane_size(self, slot: str) -> None:
            """Retire toute surcharge en ligne des DEUX dimensions de
            `slot` : une disposition précédente a pu en fixer une (largeur
            OU hauteur selon SA propre orientation), et la laisser traîner
            entrerait en conflit avec la feuille de style de la disposition
            actuelle. `styles.X = None` efface la règle et redonne la main
            à la feuille de style (`ScalarProperty.__set__`, vérifié dans
            Textual 8.2.8) — c'est aussi, exactement, ce que « réinitialiser »
            doit faire.

            Les DEUX plafonds partent avec : `_apply_pane_size_for_slot` en
            pose un (`max_width`/`max_height`) plutôt qu'une taille fixe
            quand la feuille de style laisse le volet élastique, et un
            plafond calculé pour un terminal ou une disposition précédente
            est tout aussi périmé qu'une taille.
            """
            pane, _ = self._pane_widgets(slot)
            pane.styles.width = None
            pane.styles.height = None
            pane.styles.max_width = None
            pane.styles.max_height = None

        def _apply_pane_size_for_slot(
            self, slot: str, stored: dict, then=None
        ) -> None:
            """Pose — ou efface — la surcharge de taille d'UN SEUL volet.

            RÈGLE STRUCTURELLE (tâche 27) : cette méthode ne lit JAMAIS la
            région du volet qu'elle règle. Elle vient d'effacer sa
            surcharge (`_clear_pane_size`) ; sa région est donc, jusqu'au
            prochain calcul de mise en page, celle de l'ANCIENNE règle. La
            version précédente s'en servait comme base quand rien n'était
            stocké, et différait la lecture d'un `call_after_refresh` en
            espérant que la mise en page ait eu lieu entre-temps. Elle
            avait lieu presque toujours ; « presque » a coûté 3 % des
            exécutions, dans lesquelles la base valait l'ancienne
            surcharge, le bornage retombait donc sur elle, la branche
            « rien à corriger » sautait l'écriture, et le volet restait
            DÉFINITIVEMENT à la part que la feuille de style lui donne
            (`2fr` de `#right`, soit 3 cellules) — rien n'étant reprogrammé
            pour le rattraper.

            Un tour de plus, ou une reprise, n'aurait fait que rendre le
            cas plus rare. La lecture est donc SUPPRIMÉE, pas retardée :

            - le PLANCHER ne se mesure plus du tout, il est déclaré
              (`_PANE_MIN_CSS`) et tenu par le moteur de mise en page ;
            - la seule base de bornage restante est une valeur DÉCLARÉE :
              la taille stockée, ou, à défaut, la largeur/hauteur que la
              feuille de style donne à ce volet quand elle est exprimée en
              CELLULES (`#folders { width: 28 }`), la seule qui puisse
              écraser le voisin. Une fraction (`2fr`, `1fr`) occupe par
              définition ce qui reste : rien à borner, et son plancher est
              déjà garanti.

            Un `Scalar` de `styles` est une RÈGLE, pas une mesure d'écran :
            il ne peut pas être « pré-rafraîchissement ». Pour qu'une
            lecture périmée revienne ici, il faudrait qu'on réintroduise
            une lecture de `.region` d'un widget que ce même appel vient de
            modifier — il n'en reste aucune sur le volet lui-même, et
            `test_mail_tui_resize.py` en fait un test.

            `parent.region` (via `_pane_total`) reste mesurée : elle n'est
            jamais invalidée par ce que ce volet vient de faire, seulement
            par ce qu'un volet PRÉCÉDENT de la chaîne a fait — d'où `then`,
            qui enchaîne `list_pane` après `folders` pour que `#right` soit
            mesuré après le rafraîchissement qui suit le réglage de
            `folders`, jamais avant.
            """
            self._clear_pane_size(slot)

            def _settle() -> None:
                pane, parent = self._pane_widgets(slot)
                dimension = self._pane_dimension(parent)
                # `.region` (via `_pane_total`), pas `.size` : `box_sizing`
                # par défaut est `border-box` (Textual), donc
                # `styles.width = N` fixe la boîte ENTIÈRE (bordure
                # comprise) à N — exactement ce que `.region` mesure.
                # `.size` est l'aire de CONTENU, plus petite d'une cellule
                # sur un volet bordé (`#folders`, `#preview`) ; s'en servir
                # ici désynchroniserait le nombre stocké de ce que l'écran
                # affiche réellement.
                total = self._pane_total(slot, parent)
                basis = self._pane_size_basis(pane, dimension, stored, slot)
                # `basis is None` : la feuille de style laisse ce volet
                # ÉLASTIQUE (`1fr`). On ne lui fixe alors pas de taille —
                # ce serait perdre son élasticité — mais on lui pose le
                # PLAFOND qui réserve à son voisin de quoi tenir ses
                # propres planchers. Sans lui, `#folders` en « stacked »
                # (`1fr`) prenait la moitié de `#panes` et laissait `#right`
                # trop court pour ses deux enfants. `clamp_pane_size(total,
                # ...)` rend exactement ce plafond : le maximum qu'un volet
                # puisse demander sans écraser le voisin, calculé par la
                # MÊME règle que tous les autres bornages ici.
                value = clamp_pane_size(
                    total if basis is None else basis,
                    total,
                    sibling_minimum=_PANE_SIBLING_MIN[slot],
                )
                # `value is None` : `parent` n'a pas encore de taille
                # mesurable (premier montage), rien à poser cette fois — le
                # premier `Resize` de `#panes` repassera.
                if value is not None:
                    name = (
                        dimension if basis is not None else f"max_{dimension}"
                    )
                    setattr(pane.styles, name, value)
                if then is not None:
                    then()

            self.call_after_refresh(_settle)

        def _pane_size_basis(
            self, pane, dimension: str, stored: dict, slot: str
        ):
            """La taille à FIXER pour `slot`, ou `None` si la feuille de
            style le laisse élastique — toujours DÉCLARÉE, jamais mesurée
            sur l'écran.

            La taille stockée si l'utilisateur en a réglé une ; sinon celle
            que la feuille de style donne au volet, et seulement si elle est
            exprimée en CELLULES (`#folders { width: 28 }`). Une fraction
            rend `None` : l'appelant lui pose un PLAFOND au lieu d'une
            taille, ce qui réserve la place du voisin sans figer un volet
            que la feuille de style veut élastique.
            """
            stored_value = stored.get(slot)
            if stored_value is not None:
                return stored_value
            declared = getattr(pane.styles, dimension)
            if declared is None or not declared.is_cells:
                return None
            return int(declared.value)

        def _apply_pane_sizes(self) -> None:
            """Pose — ou efface — la surcharge de taille de chaque volet
            pour la disposition ACTIVE, à partir de `todo_prefs`. Appelée au
            montage (différée, voir `on_mount`), après chaque changement de
            disposition, et à chaque redimensionnement du TERMINAL (voir
            `on_resize`) : les moments où les tailles affichées doivent
            changer, ou être recontrôlées contre l'espace RÉELLEMENT
            disponible.

            `list_pane` est enchaîné APRÈS `folders` (`then=`) : son total
            (`#right`) dépend de la taille RETENUE pour `folders`, qui n'est
            elle-même connue qu'après le rafraîchissement que
            `_apply_pane_size_for_slot` attend déjà pour `folders` — un
            second rafraîchissement, pas le même, sépare donc les deux
            mesures.
            """
            stored = resolve_pane_sizes(
                todo_prefs.get("mail_pane_sizes", {}), self.mail_layout
            )
            self._apply_pane_size_for_slot(
                "folders",
                stored,
                then=lambda: self._apply_pane_size_for_slot(
                    "list_pane", stored
                ),
            )

        def _store_pane_size(self, slot: str, value: int | None) -> None:
            """Écrit (ou efface, si `value` est `None`) la taille de `slot`
            pour la disposition ACTIVE dans `todo_prefs`, sans jamais muter
            en place le dictionnaire qu'il rend : `todo_prefs.get` peut
            rendre l'objet `DEFAULTS` PARTAGÉ quand rien n'est encore
            enregistré — le modifier sur place corromprait ce défaut pour
            tout le processus.
            """
            sizes = todo_prefs.get("mail_pane_sizes", {})
            if not isinstance(sizes, dict):
                sizes = {}
            per_layout = dict(sizes.get(self.mail_layout) or {})
            if value is None:
                per_layout.pop(slot, None)
            else:
                per_layout[slot] = value
            sizes = dict(sizes)
            sizes[self.mail_layout] = per_layout
            todo_prefs.set("mail_pane_sizes", sizes)

        def _apply_new_pane_size(
            self, slot: str, value: int, persist: bool = True
        ) -> int | None:
            """Borne `value` et la pose comme taille EN DIRECT de `slot` ;
            l'écrit aussi dans `todo_prefs` (`_store_pane_size`) SAUF si
            `persist=False`. Partagée par le clavier (`+`/`-`, TOUJOURS
            persisté — une pression est un évènement rare) et le glissement
            à la souris (`persist=False` PENDANT le glissement lui-même :
            `_store_pane_size` fait un aller-retour disque à CHAQUE appel,
            et un glissement poste potentiellement des dizaines de
            `MouseMove` par seconde ; `persist` ne redevient vrai qu'une
            fois, à la levée — voir `_end_pane_drag`). Rend la valeur
            RETENUE (après bornage), ou `None` si `total` n'était pas
            encore mesurable — dans les deux cas, jamais de relecture de
            région après avoir écrit un style, la même prudence que
            partout ailleurs dans ce fichier.
            """
            pane, parent = self._pane_widgets(slot)
            dimension = self._pane_dimension(parent)
            total = self._pane_total(slot, parent)
            new_value = clamp_pane_size(
                value, total, sibling_minimum=_PANE_SIBLING_MIN[slot]
            )
            if new_value is None:
                return None
            setattr(pane.styles, dimension, new_value)
            if persist:
                self._store_pane_size(slot, new_value)
            if slot == "folders":
                # `#folders` grandi peut avoir affamé `list_pane`/`preview`
                # sous LEUR plancher (`_PANE_SIBLING_MIN["folders"]` réserve
                # de la place à #right, mais pas encore à SES propres
                # enfants) : `_apply_pane_size_for_slot` attend déjà, seule,
                # le rafraîchissement qui suit avant de mesurer `#right` —
                # rien à différer ici en plus. `list_pane`, lui, n'a pas ce
                # problème — son voisin `#preview` est une feuille. Ce
                # correctif tourne QUE `persist` soit vrai ou non : il lit
                # la taille PERSISTÉE de `list_pane` (jamais celle de
                # `folders`, non concernée), donc un glissement de
                # `folders` pas encore relâché doit re-corriger `list_pane`
                # exactement comme le clavier le fait déjà.
                stored = resolve_pane_sizes(
                    todo_prefs.get("mail_pane_sizes", {}), self.mail_layout
                )
                self._apply_pane_size_for_slot("list_pane", stored)
            return new_value

        def _resize_focused_pane(self, delta: int) -> None:
            slot = self._focused_pane_slot()
            if slot is None:
                return
            pane, parent = self._pane_widgets(slot)
            dimension = self._pane_dimension(parent)
            # `.region` ici aussi, même raison que dans `_apply_pane_sizes`.
            current = getattr(pane.region, dimension)
            self._apply_new_pane_size(slot, current + delta)

        # -- glissement de la barre de partage (souris, tâche 25) --------

        def _begin_pane_drag(
            self, slot: str, screen_x: int, screen_y: int
        ) -> None:
            """`MouseDown` sur la barre de partage de `slot` (voir
            `_PaneSplitter`) : mémorise le POINT de départ, en coordonnées
            ÉCRAN (`event.screen_x`/`screen_y` — jamais `event.x`/`event.y`,
            relatifs à la barre elle-même et donc TOUJOURS nuls une fois la
            souris capturée : voir `MouseEvent._apply_offset`, qui ne
            touche jamais `_screen_x`/`_screen_y`, vérifié dans la source
            de Textual 8.2.8), et la taille ACTUELLE du volet — pour
            calculer un delta à chaque `MouseMove` suivant, sans jamais
            relire de région en cours de route.
            """
            pane, parent = self._pane_widgets(slot)
            dimension = self._pane_dimension(parent)
            self._drag_slot = slot
            self._drag_dimension = dimension
            self._drag_origin = screen_x if dimension == "width" else screen_y
            self._drag_base = getattr(pane.region, dimension)
            self._drag_last_value = None
            # Signal visuel PUR (voir la CSS `.pane-splitter.dragging`) :
            # aucune décision de redimensionnement n'en dépend, seulement
            # posé/retiré ici et dans `_end_pane_drag`, jamais sur la barre
            # elle-même — un seul endroit qui connaît l'état du glissement.
            self.query_one(f"#{_SPLITTER_IDS[slot]}").add_class("dragging")

        def _drag_pane_to(self, screen_x: int, screen_y: int) -> None:
            """`MouseMove` pendant un glissement : redimensionne EN DIRECT,
            sans persister (`persist=False`, voir `_apply_new_pane_size`) —
            seule la levée (`_end_pane_drag`) écrit sur disque, une fois.
            Hors glissement (`_drag_slot` encore `None`, par exemple un
            `MouseMove` qui précède le tout premier `MouseDown` — voir
            `Pilot.mouse_down`), ne fait rien.
            """
            if self._drag_slot is None:
                return
            current = screen_x if self._drag_dimension == "width" else screen_y
            applied = self._apply_new_pane_size(
                self._drag_slot,
                self._drag_base + (current - self._drag_origin),
                persist=False,
            )
            if applied is not None:
                self._drag_last_value = applied

        def _end_pane_drag(self) -> None:
            """Termine un glissement — `MouseUp`/`MouseRelease` sur la
            barre (voir `_PaneSplitter.on_mouse_up`/`on_mouse_release` : la
            capture peut être révoquée SANS `MouseUp`, par exemple par
            `App.push_screen` avant d'empiler un écran modal), OU l'app qui
            perd le focus (`on_app_blur`), OU un passage en plein écran qui
            masquerait la barre en cours de glissement
            (`action_toggle_fullscreen`) : UN SEUL point de sortie pour ces
            quatre signaux, qui persiste la DERNIÈRE taille appliquée
            (`_drag_last_value` — jamais une relecture de région, la même
            prudence que le reste de ce fichier). Un simple clic sans
            mouvement (`_drag_last_value` resté `None`) ne persiste rien.
            Toujours sûr à appeler hors glissement (`_drag_slot` déjà
            `None`) : plusieurs appelants le font sans savoir si un
            glissement est réellement en cours, et certains (un `MouseUp`
            normal PUIS le `MouseRelease` que sa propre `capture_mouse(None)`
            déclenche en retour) l'appellent deux fois pour le MÊME
            glissement — la seconde fois est un no-op.
            """
            if self._drag_slot is None:
                return
            if self._drag_last_value is not None:
                self._store_pane_size(self._drag_slot, self._drag_last_value)
            splitter_id = _SPLITTER_IDS[self._drag_slot]
            self._drag_slot = None
            self._drag_dimension = None
            self._drag_origin = None
            self._drag_base = None
            self._drag_last_value = None
            self.capture_mouse(None)
            self.query_one(f"#{splitter_id}").remove_class("dragging")

        def on_app_blur(self) -> None:
            """L'app perd le focus (terminal minimisé, alt-tab, perte de la
            fenêtre) : un glissement en cours ne recevra alors PLUS JAMAIS
            son `MouseUp` — le terminer ici comme une levée normale plutôt
            que de laisser l'app coincée en glissement (capture de souris
            comprise) jusqu'à la prochaine action de souris, qui peut ne
            jamais venir.
            """
            self._end_pane_drag()

        def action_grow_pane(self) -> None:
            self._resize_focused_pane(PANE_SIZE_STEP)

        def action_shrink_pane(self) -> None:
            self._resize_focused_pane(-PANE_SIZE_STEP)

        def action_reset_pane_sizes(self) -> None:
            for slot in _PANE_SLOTS:
                self._clear_pane_size(slot)
                self._store_pane_size(slot, None)
            self.set_status(t("mail_pane_reset_done"))

        def action_move_message(self) -> None:
            """`m` : ouvre la liste des dossiers et range le message choisi.

            La liste ne propose PAS le dossier courant : s'y déplacer ne
            ferait rien, et le proposer laisse croire le contraire.
            """
            metas = self.cibles()
            if not metas or self.current_ref is None:
                return
            session, source = self.meta_origin(metas[0])
            if session is None or not session.online:
                self.set_status(t("mail_trash_offline"))
                return

            def ranger(choix):
                if not choix:
                    return
                destination, cible = choix
                self.set_status(t("mail_move_across_working"))
                self._vider_selection()
                self.run_worker(
                    lambda: self._ranger_lot(metas, destination, cible),
                    thread=True,
                )

            self.push_screen(
                MoveScreen(session, source, self.sessions), ranger
            )

        def _ranger_lot(self, metas, destination, cible) -> None:
            """Range un lot dans `destination`/`cible`, chaque message
            depuis SON dossier.

            Les messages d'un même dossier partent ensemble — un COPY, un
            retrait — plutôt qu'un aller-retour par message. Une recherche
            élargie en mêle de plusieurs dossiers et même de plusieurs
            comptes : le regroupement est donc fait ici, et non supposé.
            """
            groupes = {}
            for meta in metas:
                session, dossier = self.meta_origin(meta)
                if session is None:
                    continue
                groupes.setdefault((id(session), dossier), (session, []))
                groupes[(id(session), dossier)][1].append(meta)
            faits, erreur, vide_partout = 0, None, True
            for (_, dossier), (session, lot) in groupes.items():
                if session is destination:
                    try:
                        with self._sync_lock:

                            def ranger(transport, dossier=dossier, lot=lot):
                                transport.select(dossier)
                                return transport.move(
                                    [m.uid for m in lot], cible
                                )

                            vide = session.avec_lien(ranger)
                    except Exception as exc:
                        _logger.exception("rangement vers %s", cible)
                        erreur = erreur or exc
                        continue
                    vide_partout = vide_partout and vide
                    etat = session.store.folder_state(dossier) or {}
                    if etat.get("id") is not None:
                        for meta in lot:
                            session.store.forget_message(etat["id"], meta.uid)
                    faits += len(lot)
                    continue
                # Vers un AUTRE compte : aucun COPY ne relie deux serveurs,
                # chaque message est déposé puis confirmé un par un.
                for meta in lot:
                    fait, souci = self._deplacer_ailleurs(
                        session, dossier, meta, destination, cible, seul=False
                    )
                    erreur = erreur or souci
                    if fait:
                        faits += 1
                    else:
                        vide_partout = False
            self.call_from_thread(
                self._lot_range, cible, faits, len(metas), erreur, vide_partout
            )

        def _lot_range(
            self, cible, faits, demandes, erreur, vide_partout
        ) -> None:
            if erreur is not None:
                self.set_status(str(erreur))
            elif faits < demandes:
                self.set_status(
                    f"{t('mail_trash_done')} {cible} — {faits}/{demandes}"
                )
            elif not vide_partout:
                self.set_status(
                    f"{t('mail_trash_done')} {cible}"
                    f" — {t('mail_trash_source_kept')}"
                )
            else:
                self.set_status(f"{t('mail_trash_done')} {cible} ({faits})")
            if self.current_ref is not None:
                self.select_ref(self.current_ref)

        def action_trash_message(self) -> None:
            """`d` : déplace le message vers la corbeille du compte.

            Rien n'est détruit ici — une corbeille se vide ailleurs, et
            c'est ce qui rend le geste réparable. Le cache n'est mis à jour
            qu'APRÈS l'accord du serveur : le devancer ferait revenir à la
            passe suivante un message disparu de l'écran.
            """
            metas = self.cibles()
            if not metas or self.current_ref is None:
                return
            session, source = self.meta_origin(metas[0])
            if session is None or not session.online:
                self.set_status(t("mail_trash_offline"))
                return
            corbeille = self._corbeille(session)
            if corbeille is None:
                # Inventer un nom créerait chez le fournisseur un dossier
                # que personne n'a demandé.
                self.set_status(t("mail_trash_no_folder"))
                return
            # Un lot peut mêler des dossiers : ceux qui sont DÉJÀ dans la
            # corbeille du compte sont écartés plutôt que de faire échouer
            # le geste entier.
            restants = [
                m
                for m in metas
                if self.meta_origin(m)[1] != corbeille
                or self.meta_origin(m)[0] is not session
            ]
            if not restants:
                self.set_status(t("mail_trash_already_there"))
                return
            self._vider_selection()
            self.run_worker(
                lambda: self._ranger_lot(restants, session, corbeille),
                thread=True,
            )

        @staticmethod
        def _corbeille(session) -> str | None:
            """Le dossier que le SERVEUR désigne comme corbeille, ou rien.

            Le rôle vient de l'annonce du fournisseur, jamais d'un nom
            deviné : inventer « Trash » créerait chez lui un dossier que
            personne n'a demandé, et le vrai resterait plein.
            """
            return next(
                (
                    f["name"]
                    for f in session.store.folders()
                    if f["role"] == "trash"
                ),
                None,
            )

        def action_empty_trash(self) -> None:
            """`D` : détruit définitivement le contenu de la corbeille.

            Le seul geste du client qui ne se répare pas, et le seul qui
            exige de TAPER un mot plutôt que d'appuyer sur une touche — la
            confirmation d'un geste irréversible ne doit pas pouvoir
            s'obtenir par la frappe de trop.
            """
            if self.current_ref is None:
                return
            session = self.session_for(self.current_ref.account_name)
            if session is None or not session.online:
                self.set_status(t("mail_empty_trash_offline"))
                return
            corbeille = self._corbeille(session)
            if corbeille is None:
                self.set_status(t("mail_empty_trash_no_folder"))
                return
            # PAS de refus anticipé sur le compte du cache : il retarde
            # toujours sur la corbeille, que `d` remplit côté serveur sans
            # rien y ajouter localement. Un « déjà vide » tiré de là
            # refuserait le geste juste après avoir jeté un message. Le
            # nombre affiché se donne donc pour ce qu'il est, et le seul
            # qui compte — celui du serveur — est annoncé à la fin.
            etat = session.store.folder_state(corbeille) or {}

            def vider(confirme):
                if not confirme:
                    return
                self.set_status(t("mail_empty_trash_working"))
                self.run_worker(
                    lambda: self._vider(session, corbeille),
                    thread=True,
                )

            self.push_screen(
                EmptyTrashScreen(corbeille, etat.get("total") or 0), vider
            )

        def _vider(self, session, corbeille) -> None:
            """Le fil de travail de `D`.

            Le cache n'est purgé qu'APRÈS l'accord du serveur, et le nombre
            annoncé est celui que le SERVEUR a retiré, pas celui que le
            cache croyait détenir.
            """
            try:
                with self._sync_lock:
                    nombre = session.avec_lien(
                        lambda transport: transport.empty_folder(corbeille)
                    )
            except Exception as exc:
                _logger.exception("vidage de %s", corbeille)
                self.call_from_thread(self.set_status, str(exc))
                return
            session.store.purge_folder(corbeille)
            self.call_from_thread(self._vide, nombre)

        def _vide(self, nombre: int) -> None:
            self.set_status(
                f"{t('mail_empty_trash_done')} {nombre}"
                if nombre
                else t("mail_empty_trash_already")
            )
            if self.current_ref is not None:
                self.select_ref(self.current_ref)

        def _deplacer_ailleurs(
            self, session, source, meta, destination, cible, seul=True
        ) -> tuple:
            """Le fil de travail d'un déplacement entre DEUX comptes.

            Rien ne relie deux serveurs : le message est relu en entier,
            DÉPOSÉ chez l'autre, puis seulement retiré d'ici. Un retrait
            qui précéderait le dépôt perdrait le message pour de bon —
            aucun serveur ne le rendrait, et il ne passerait par aucune
            corbeille.

            Le dépôt accepté ne suffit pas : on redemande au serveur s'il
            contient bien ce Message-ID. Sans cette confirmation la source
            RESTE, et l'écran le dit — un message en double se corrige, un
            message disparu, non. Un message sans Message-ID n'est donc
            jamais retiré de sa source : il n'y a rien à quoi le
            reconnaître là-bas.
            """
            try:
                with self._sync_lock:
                    raw = session.avec_lien(
                        lambda _t: session.syncer.fetch_body(source, meta.uid)
                    )
                    drapeaux = [d for d in (meta.flags or "").split() if d]

                    def deposer(transport):
                        transport.append(cible, raw, drapeaux, meta.date)
                        return transport.contient_message_id(cible, meta.msgid)

                    arrive = destination.avec_lien(deposer)
                    vide = False
                    if arrive:

                        def retirer(transport):
                            transport.select(source)
                            return transport.discard([meta.uid])

                        vide = session.avec_lien(retirer)
            except Exception as exc:
                _logger.exception(
                    "déplacement vers %s/%s", destination.account.name, cible
                )
                if seul:
                    self.call_from_thread(self.set_status, str(exc))
                return False, exc
            if arrive:
                etat = session.store.folder_state(source) or {}
                if etat.get("id") is not None:
                    session.store.forget_message(etat["id"], meta.uid)
            try:
                # Le message est chez l'autre compte : sans cette relecture
                # il n'y apparaîtrait qu'à la prochaine passe complète.
                destination.syncer.sync_one(cible)
            except Exception:
                _logger.exception("relecture de %s", cible)
            if not seul:
                # Dans un lot, c'est l'appelant qui parle à l'écran : cent
                # messages ne doivent pas écrire cent fois dans la barre
                # d'état, chacun effaçant le précédent. La CAUSE remonte
                # quand même — « 0 sur 1 » sans le refus du serveur ne dit
                # pas quoi corriger.
                return bool(arrive and vide), None
            self.call_from_thread(
                self._deplace_ailleurs, destination, cible, arrive, vide
            )
            return bool(arrive and vide), None

        def _deplace_ailleurs(
            self, destination, cible, arrive: bool, vide: bool
        ) -> None:
            nom = f"{destination.account.name} — {cible}"
            if not arrive:
                self.set_status(f"{t('mail_move_across_unconfirmed')} {nom}")
            elif not vide:
                self.set_status(
                    f"{t('mail_trash_done')} {nom}"
                    f" — {t('mail_trash_source_kept')}"
                )
            else:
                self.set_status(f"{t('mail_trash_done')} {nom}")
            if self.current_ref is not None:
                self.select_ref(self.current_ref)

        def _deplace_ailleurs(
            self, destination, cible, arrive: bool, vide: bool
        ) -> None:
            nom = f"{destination.account.name} — {cible}"
            if not arrive:
                self.set_status(f"{t('mail_move_across_unconfirmed')} {nom}")
            elif not vide:
                self.set_status(
                    f"{t('mail_trash_done')} {nom}"
                    f" — {t('mail_trash_source_kept')}"
                )
            else:
                self.set_status(f"{t('mail_trash_done')} {nom}")
            if self.current_ref is not None:
                self.select_ref(self.current_ref)

        def _deplace(self, cible: str, vide: bool) -> None:
            message = f"{t('mail_trash_done')} {cible}"
            if not vide:
                # Sans UIDPLUS, la source garde le message barré : un autre
                # client le montrera, et le taire ferait passer ça pour un
                # bogue.
                message += f" — {t('mail_trash_source_kept')}"
            self.set_status(message)
            if self.current_ref is not None:
                self.select_ref(self.current_ref)

        def action_search_server(self) -> None:
            """Pose au SERVEUR la question que `/` pose au cache.

            Un geste à part, jamais automatique : étendre à chaque frappe
            ferait payer un aller-retour réseau à une recherche qui répond
            déjà. Le travail part dans un fil — une requête réseau sur le
            fil de l'interface gèlerait la fenêtre — et chaque refus se DIT,
            une touche silencieuse se lisant comme une touche cassée.
            """
            if not self.query:
                self.set_status(t("mail_search_server_no_term"))
                return
            if self.current_ref is None:
                return
            session = self.session_for(self.current_ref.account_name)
            if session is None or not session.online:
                self.set_status(t("mail_search_server_offline"))
                return
            self.set_status(t("mail_search_server_asking"))
            cibles = self._cibles_serveur(session)
            terme = self.query
            self.run_worker(
                lambda: self._chercher_serveur(cibles, terme),
                thread=True,
            )

        def _cibles_serveur(self, session) -> list:
            """Les (session, dossier) où poser la question, selon la portée.

            La même portée que la recherche locale : une touche qui cherche
            dans le dossier ouvert et une autre qui interroge le serveur
            sur tout le compte rendraient deux listes qu'on croirait
            comparables.

            Les comptes hors ligne sont écartés ici plutôt que d'échouer un
            par un dans le fil de travail.
            """
            portee = getattr(self, "search_scope", "folder")
            if portee == "folder":
                return [(session, self.current_ref.folder_name)]
            sessions = self.sessions if portee == "all" else [session]
            cibles = []
            for autre in sessions:
                if not autre.online:
                    continue
                cibles.extend(
                    (autre, dossier["name"])
                    for dossier in autre.store.folders()
                )
            return cibles

        def _chercher_serveur(self, cibles, terme) -> None:
            """Le fil de travail : SELECT, SEARCH, puis les en-têtes manquants.

            Sous `_sync_lock` : `imaplib` n'est pas sûr entre fils, et une
            passe de synchronisation peut tourner en même temps sur la MÊME
            connexion.

            Un dossier qui refuse — non sélectionnable, disparu depuis la
            dernière passe — n'arrête pas les autres : sur un compte entier,
            un seul dossier fâché rendrait la touche inutilisable. Le compte
            des refusés est rendu pour que l'écran puisse le dire.
            """
            ramenes, refuses, derniere = 0, 0, None
            for session, dossier in cibles:
                try:
                    with self._sync_lock:

                        def chercher(transport, dossier=dossier):
                            transport.select(dossier)
                            return transport.search(terme)

                        uids = session.avec_lien(chercher)
                        ramenes += session.syncer.fetch_uids(dossier, uids)
                except Exception as exc:
                    _logger.exception("recherche serveur sur %s", dossier)
                    refuses += 1
                    derniere = exc
            if cibles and refuses == len(cibles):
                # Tout a refusé : l'erreur elle-même en dit plus qu'un
                # décompte.
                self.call_from_thread(self.set_status, str(derniere))
                return
            self.call_from_thread(self._serveur_a_repondu, ramenes, refuses)

        def _serveur_a_repondu(self, ramenes: int, refuses: int = 0) -> None:
            if ramenes:
                message = f"{t('mail_search_server_found')} {ramenes}"
            else:
                message = t("mail_search_server_nothing")
            if refuses:
                message += f" — {refuses} {t('mail_search_server_skipped')}"
            self.set_status(message)
            # Ce que le serveur a ramené est DANS le cache : relire le
            # dossier le fait apparaître, sans rien retaper.
            if self.current_ref is not None:
                self.select_ref(self.current_ref)

        def action_focus_search(self) -> None:
            self.query_one("#search_row").add_class("visible")
            self.query_one("#search", Input).focus()

        def clear_search(self) -> None:
            """Vide le champ ET `self.query` — les deux, pas seulement le
            champ : sinon la liste resterait filtrée par une requête devenue
            invisible, pire que pas de bouton du tout.
            """
            self.query_one("#search", Input).value = ""
            self.query = ""
            self.refresh_list()

        def on_button_pressed(self, event) -> None:
            if event.button.id == "search_clear":
                self.clear_search()

        def action_mark_seen(self) -> None:
            self._set_flag("\\Seen", add=True)

        def action_mark_unseen(self) -> None:
            self._set_flag("\\Seen", add=False)

        def action_toggle_flagged(self) -> None:
            """`*` : pose ou retire le drapeau « suivi ».

            Une bascule et non deux touches : contrairement à lu/non lu, où
            l'on veut souvent forcer l'état d'un message déjà dans l'autre,
            le suivi se met et s'enlève sur le même message.

            Sur un lot, le sens de la bascule est celui du GROUPE : on ne
            retire que si tout est déjà suivi. Basculer chacun de son côté
            rendrait le résultat imprévisible — un lot mi-suivi
            s'inverserait sans que rien ne dise dans quel état il finit.
            """
            metas = self.cibles()
            if not metas:
                return
            tous = all(tui_text.is_flagged(m.flags) for m in metas)
            self._set_flag("\\Flagged", add=not tous)

        def _set_flag(self, flag: str, add: bool) -> None:
            """Pose ou retire `flag` sur ce que `cibles()` désigne.

            Le cache d'abord, le serveur ensuite, et un refus du serveur se
            DIT sans défaire le cache : un drapeau est la seule chose que
            la passe suivante corrige d'elle-même, en relisant l'état du
            serveur. C'est ce qui distingue ce chemin du rangement, où le
            cache ne doit jamais devancer.
            """
            metas = self.cibles()
            if not metas or self.current_ref is None:
                return
            a_porter = []
            for meta in metas:
                session, dossier = self.meta_origin(meta)
                if session is None:
                    continue
                state = session.store.folder_state(dossier)
                if not state:
                    continue
                flags = set(meta.flags.split()) if meta.flags else set()
                flags.add(flag) if add else flags.discard(flag)
                session.store.update_flags(
                    state["id"], meta.uid, " ".join(sorted(flags))
                )
                if session.online:
                    a_porter.append((session, dossier, meta.uid))
            self._vider_selection()
            self.select_ref(self.current_ref)
            if a_porter:
                # Le serveur est prévenu depuis un FIL DE TRAVAIL : un STORE
                # sur le fil de l'interface partagerait la socket avec les
                # échanges d'une passe en cours, sans le verrou qu'ils
                # prennent — deux dialogues sur un lien, et le perdant
                # attend trente secondes une réponse partie ailleurs.
                self.run_worker(
                    lambda: self._porter_drapeau(a_porter, flag, add),
                    thread=True,
                )

        def _porter_drapeau(self, a_porter, flag, add) -> None:
            """Pose le drapeau sur le SERVEUR, sous le verrou.

            Le cache a déjà été mis à jour : un drapeau est la seule chose
            que la passe suivante corrige d'elle-même en relisant l'état du
            serveur, ce qui rend l'ordre inverse — cache d'abord — sans
            danger ici, contrairement au rangement.
            """
            erreur = None
            for session, dossier, uid in a_porter:
                try:
                    with self._sync_lock:

                        def poser(transport, dossier=dossier, uid=uid):
                            transport.select(dossier)
                            transport.store_flags(
                                uid,
                                [flag] if add else [],
                                [] if add else [flag],
                            )

                        session.avec_lien(poser)
                except Exception as exc:
                    # Le premier refus suffit à le dire : un lot de cent
                    # messages sur un serveur fâché en afficherait cent.
                    _logger.exception("drapeau sur %s/%s", dossier, uid)
                    erreur = erreur or exc
            if erreur is not None:
                self.call_from_thread(
                    self.set_status, f"{t('mail_flag_error')} {erreur}"
                )

        def action_mark_all_seen(self) -> None:
            """`M` : marque lu TOUT le dossier ouvert.

            Exige d'être en ligne, et ce n'est pas une facilité : une passe
            de synchronisation relit les drapeaux depuis le serveur, donc
            un marquage posé hors ligne serait défait à la passe suivante.
            Le dire vaut mieux que le laisser s'effacer tout seul.

            Demande confirmation — le geste ne détruit rien, mais rien ne le
            défait commodément : « rendre non lus ceux qui l'étaient »
            n'existe pas, la liste de départ étant perdue.
            """
            if self.current_ref is None:
                return
            session = self.session_for(self.current_ref.account_name)
            if session is None or not session.online:
                self.set_status(t("mail_all_seen_offline"))
                return
            dossier = self.current_ref.folder_name
            etat = session.store.folder_state(dossier) or {}
            if etat.get("id") is None:
                return
            non_lus = session.store.count_unseen(etat["id"])
            if not non_lus:
                self.set_status(t("mail_all_seen_nothing"))
                return

            def confirme(oui):
                if not oui:
                    return
                self.run_worker(
                    lambda: self._tout_lire(session, dossier, etat["id"]),
                    thread=True,
                )

            self.push_screen(
                ConfirmScreen(
                    f"{t('mail_all_seen_ask')} {non_lus}"
                    f" ({self.current_ref.display})"
                ),
                confirme,
            )

        def _tout_lire(self, session, dossier, folder_id) -> None:
            """Le fil de travail de `M` : le serveur d'abord, le cache
            ensuite.

            L'ordre habituel de ce client : un cache qui devancerait un
            serveur ayant refusé afficherait un dossier lu qui reviendrait
            non lu à la passe suivante.
            """
            try:
                with self._sync_lock:

                    def tout_lire(transport):
                        transport.select(dossier)
                        transport.store_flags_all(["\\Seen"], [])

                    session.avec_lien(tout_lire)
            except Exception as exc:
                _logger.exception("tout marquer lu dans %s", dossier)
                self.call_from_thread(self.set_status, str(exc))
                return
            combien = session.store.mark_all_seen(folder_id)
            self.call_from_thread(self._tout_lu, combien)

        def _tout_lu(self, combien: int) -> None:
            """Rien à rebâtir : seuls des drapeaux ont changé.

            `reload_folders` referait l'arbre entier et ramènerait son
            curseur à la racine, alors que `select_ref` recharge la liste et
            corrige les compteurs en place.
            """
            self.set_status(f"{t('mail_all_seen_done')} {combien}")
            if self.current_ref is not None:
                self.select_ref(self.current_ref)
            else:
                self.refresh_folder_counts()

        def action_sync_current(self) -> None:
            self.run_worker(self.sync_current_worker, thread=True)

        def action_sync_all(self) -> None:
            self.run_worker(self.sync_all_worker, thread=True)

        def set_status(self, text: str) -> None:
            # Plusieurs appelants y glissent le message d'une exception.
            # Un crochet NU traverse le balisage sans dommage ; ce
            # qui lève `MarkupError`, c'est un crochet contenant un « = »,
            # donc ressemblant à une balise avec valeur — une URL de suivi
            # dans un message d'erreur suffit. Le statut disparaîtrait au
            # moment PRÉCIS où il sert. On tente donc le balisage —
            # `deliver` s'en sert pour son ⚠ en gras rouge — et on retombe
            # sur du littéral dès qu'il ne tient pas.
            if isinstance(text, str):
                try:
                    text = Text.from_markup(text)
                except Exception:
                    text = Text(text)
            (
                self.call_from_thread(
                    self.query_one("#status", Static).update, text
                )
                if self._thread_id_differs()
                else self.query_one("#status", Static).update(text)
            )

        def _thread_id_differs(self) -> bool:
            return threading.current_thread() is not threading.main_thread()

        def sync_current_worker(self) -> None:
            if self.current_ref is None:
                return
            self._sync([self.session_for(self.current_ref.account_name)])

        def sync_all_worker(self) -> None:
            self._sync(self.sessions)

        def _sync(self, sessions) -> None:
            # Sérialise la PASSE, pas les comptes : deux passes concurrentes
            # (rafraîchissement automatique et `r`/`R`) partageraient le
            # socket imaplib d'un même compte, qui n'est pas sûr à
            # plusieurs fils. Deux comptes DIFFÉRENTS ont chacun leur socket
            # et leur cache verrouillé : ceux-là peuvent avancer ensemble.
            paires = []
            with self._sync_lock:
                vivantes = [s for s in sessions if s is not None and s.online]
                if not vivantes:
                    pass
                elif len(vivantes) == 1:
                    paires.append((vivantes[0], self._sync_une(vivantes[0])))
                else:
                    self.set_status(f"{t('mail_syncing')} {len(vivantes)}…")
                    with ThreadPoolExecutor(
                        max_workers=min(SYNC_PARALLELE, len(vivantes))
                    ) as pool:
                        # Plafonné : un compte par fil est utile, trente
                        # connexions simultanées se font refuser par les
                        # fournisseurs et n'accélèrent rien.
                        futurs = {
                            pool.submit(self._sync_une, s): s for s in vivantes
                        }
                        rapports = {}
                        for futur in as_completed(futurs):
                            rapports[futurs[futur]] = futur.result()
                    # Les règles passent ensuite dans l'ordre des comptes,
                    # pas dans celui où leurs passes ont fini.
                    paires = [(s, rapports.get(s)) for s in vivantes]
            # Hors du verrou : `reload_folders` passe par la boucle de
            # l'interface, qui peut elle-même attendre ce verrou.
            if self._thread_id_differs():
                self.call_from_thread(self.reload_folders)
            else:
                self.reload_folders()
            # Les règles APRÈS la passe et hors du verrou : un envoi
            # automatique reprend `_sync_lock` pour son APPEND, ce qui, depuis
            # un fil du pool, attendrait le fil parent qui tient le verrou en
            # attendant le pool. Ici, un seul fil, compte après compte.
            self._run_rules([(s, r) for s, r in paires if r is not None])

        def _run_rules(self, paires) -> None:
            """Une passe des règles par compte synchronisé, puis UNE ligne
            de bilan ajoutée au statut. Ne lève jamais.

            Fil de travail, `_sync_lock` relâché : le moteur le reprend pour
            chacun de ses échanges IMAP et ne parle jamais à l'interface ;
            le bilan n'est rendu qu'après le retour de toutes les passes.
            Un compte sans règle active ne change ni le statut ni
            `session_errors`.
            """
            if not paires:
                return
            try:
                from script.todo.mail.rules import engine

                rapports = [
                    engine.run_pass(
                        session, report=rapport, verrou=self._sync_lock
                    )
                    for session, rapport in paires
                ]
                for rapport in rapports:
                    if not rapport.errors:
                        continue
                    if rapport.active_rules:
                        self.session_errors.setdefault(
                            rapport.account, []
                        ).extend(rapport.errors)
                    else:
                        _logger.info(
                            "règles %s : %s", rapport.account, rapport.status
                        )
                ligne = engine.summary_line(rapports)
                if ligne:
                    precedent = self._status_text()
                    self.set_status(
                        f"{precedent} — {ligne}" if precedent else ligne
                    )
                if sum(r.sent for r in rapports) > 0:
                    if self._thread_id_differs():
                        self.call_from_thread(self.refresh_current_folder)
                    else:
                        self.refresh_current_folder()
            except Exception:
                _logger.exception("passe des règles en échec")

        def _status_text(self) -> str:
            """Le texte de `#status`, lu sur le fil de l'interface."""

            def lire() -> str:
                try:
                    return str(self.query_one("#status", Static).content)
                except Exception:
                    return ""

            if self._thread_id_differs():
                return self.call_from_thread(lire)
            return lire()

        def _sync_une(self, session):
            """Une passe pour UN compte ; rend son `SyncReport`, ou None si
            la passe a levé. Ne lève jamais : un compte qui échoue ne doit
            pas emporter ceux qui avancent en parallèle.

            La file part sans verrou : le fil parent tient déjà
            `_sync_lock`, et le reprendre depuis un fil du pool
            l'attendrait pour toujours."""
            self.set_status(f"{t('mail_syncing')} {session.account.name}…")
            # La file part AVANT la relecture : le retour du réseau est
            # exactement le moment où elle doit se vider, et un message
            # envoyé apparaît alors dans la passe qui suit.
            try:
                partis, _, echoues = flush_outbox(session)
                if partis or echoues:
                    self.set_status(
                        f"{t('mail_outbox_flushed')} {partis}"
                        + (
                            f" — {t('mail_outbox_failed')} {echoues}"
                            if echoues
                            else ""
                        )
                    )
            except Exception:
                _logger.exception("vidange de la file a échoué")
            try:
                report = session.sync()
            except Exception as exc:
                _logger.exception("sync de %s a échoué", session.account.name)
                self.set_status(f"{session.account.name} : {exc}")
                # Le statut est ÉPHÉMÈRE : `LogScreen` (touche `l`) existe
                # pour regarder après coup, donc la panne la plus grave —
                # la passe entière qui a levé — y reste lisible, dans la
                # même forme que les entrées de `report.errors`.
                self.session_errors[session.account.name] = [str(exc)]
                return None
            # La DERNIÈRE passe l'emporte, même vide : un compte qui se
            # remet à synchroniser proprement ne doit pas garder affichée
            # une erreur qui ne décrit plus l'état courant.
            self.session_errors[session.account.name] = list(report.errors)
            message = (
                f"{session.account.name} : {report.new_messages}"
                f" {t('mail_new_messages')}"
            )
            if report.errors:
                # Le premier message EN ENTIER, pas seulement leur compte :
                # un « 1 erreur » n'a jamais dit ce qui a échoué.
                message += f" — {report.errors[0]}"
                extra = len(report.errors) - 1
                if extra:
                    message += f" (+{extra} {t('mail_errors')})"
            if report.purged:
                message += (
                    f" — {t('mail_folders_resynced')}"
                    f" {', '.join(report.purged)}"
                )
            self.set_status(message)
            return report

        def action_save_attachment(self) -> None:
            meta = self.current_meta()
            if meta is None or self.current_ref is None:
                return
            session, dossier = self.meta_origin(meta)
            if session is None:
                return
            raw = session.store.read_body(dossier, meta.uid)
            if raw is None:
                self.set_status(t("mail_body_needs_network"))
                return
            _, attachments = tui_text.extract_body(raw)
            if not attachments:
                self.set_status(t("mail_no_attachment"))
                return
            if len(attachments) == 1:
                # Une seule : poser la question serait une frappe pour
                # rien, et la réponse était déjà connue.
                self._enregistrer(raw, attachments[0].index)
                return
            self.push_screen(
                AttachmentScreen(attachments),
                lambda index: (
                    None if index is None else self._enregistrer(raw, index)
                ),
            )

        def _enregistrer(self, raw: bytes, index: int) -> None:
            try:
                target = save_attachment(raw, index, "~/Téléchargements")
            except Exception as exc:
                self.set_status(f"{t('mail_save_failed')} {exc}")
                return
            self.set_status(f"{t('mail_saved_to')} {target}")

        @staticmethod
        def _avec_signature(session, corps: str) -> str:
            """`corps`, suivi de la signature du compte s'il en a une.

            Le délimiteur est « -- » suivi d'une ESPACE puis d'un saut de
            ligne, forme que les clients reconnaissent pour replier ou
            griser une signature. L'espace en fin de ligne n'est pas une
            coquille : sans elle, ce n'est plus un délimiteur mais deux
            tirets ordinaires.

            Elle arrive dans le formulaire, donc visible et modifiable
            avant l'envoi — plutôt qu'ajoutée au dernier moment, où
            personne ne l'aurait relue.
            """
            signature = (
                getattr(session.account, "signature", "") or ""
            ).strip("\n")
            if not signature:
                return corps
            return f"{corps}\n\n-- \n{signature}"

        def action_compose(self) -> None:
            session = self._session_or_first()
            if session:
                self.push_screen(
                    ComposeScreen(
                        session, {"body": self._avec_signature(session, "")}
                    ),
                    self._after_compose,
                )

        def action_reply(self) -> None:
            self._open_reply(reply_all=False)

        def action_reply_all(self) -> None:
            self._open_reply(reply_all=True)

        def action_forward(self) -> None:
            self._open_with_original(forward=True)

        def _session_or_first(self):
            if self.current_ref:
                return self.session_for(self.current_ref.account_name)
            return self.sessions[0] if self.sessions else None

        def _original_message(self):
            meta = self.current_meta()
            if meta is None or self.current_ref is None:
                return None, None
            session, dossier = self.meta_origin(meta)
            if session is None:
                return None, None
            raw = session.store.read_body(dossier, meta.uid)
            if raw is None and session.online:
                # Le corps manque et il faut le réseau : on le prend SOUS le
                # verrou, comme tout échange IMAP. Ce chemin-ci reste
                # synchrone — l'écran d'écriture a besoin de l'original pour
                # se construire — mais il ne partage plus la socket avec une
                # passe en cours.
                try:
                    with self._sync_lock:
                        raw = session.avec_lien(
                            lambda _t: session.syncer.fetch_body(
                                dossier, meta.uid
                            )
                        )
                except Exception:
                    _logger.exception("corps de %s/%s", dossier, meta.uid)
                    return session, None
            if raw is None:
                return session, None
            import email
            import email.policy

            return session, email.message_from_bytes(
                raw, policy=email.policy.default
            )

        def _open_reply(self, reply_all: bool) -> None:
            from script.todo.mail.smtp_send import build_reply

            session, original = self._original_message()
            if session is None or original is None:
                self.set_status(t("mail_nothing_to_reply_to"))
                return
            draft = build_reply(
                session.account, original, "", reply_all=reply_all
            )
            # Les drapeaux voyagent avec la demande : le cache ne se lit pas
            # par (dossier, UID), et `\Answered` s'ajoute à ceux déjà là.
            meta = self.current_meta()
            answer_of = None
            if meta is not None:
                _session, dossier = self.meta_origin(meta)
                answer_of = (dossier, meta.uid, meta.flags or "")
            self.push_screen(
                ComposeScreen(
                    session,
                    {
                        "to": draft["To"] or "",
                        "cc": draft["Cc"] or "",
                        "subject": draft["Subject"] or "",
                        "body": self._avec_signature(
                            session, draft.get_content()
                        ),
                        "in_reply_to": draft["In-Reply-To"],
                        "references": draft["References"],
                        "answer_of": answer_of,
                    },
                ),
                self._after_compose,
            )

        def mark_answered(self, session, dossier, uid, flags) -> None:
            """Pose `\\Answered` sur l'original d'une réponse MANUELLE partie.

            Le cache d'abord, drapeaux existants conservés, puis le serveur
            dans un fil, sous le verrou, par le même chemin que `s`/`u`. Une
            réponse automatique ne passe jamais par ici : elle ne compte pas
            comme une réponse dans les statistiques.
            """
            state = session.store.folder_state(dossier)
            if state is not None:
                drapeaux = set((flags or "").split()) | {"\\Answered"}
                session.store.update_flags(
                    state["id"], uid, " ".join(sorted(drapeaux))
                )
            self.run_worker(
                lambda: self._porter_drapeau(
                    [(session, dossier, uid)], "\\Answered", True
                ),
                thread=True,
            )

        def _open_with_original(self, forward: bool) -> None:
            session, original = self._original_message()
            if session is None or original is None:
                self.set_status(t("mail_nothing_to_forward"))
                return
            # `build_forward` exige un destinataire réel (il construit le
            # message final, prêt à partir) : lui en passer un vide — le
            # temps de ne connaître QUE le sujet, avant que l'utilisateur
            # n'ait rempli le formulaire — lève `SmtpError`. Le préfixe
            # « Fwd: » est donc calculé ici, sans passer par `build_message`.
            subject = original.get("Subject", "") or ""
            if not subject.lower().startswith("fwd:"):
                subject = f"Fwd: {subject}"
            self.push_screen(
                ComposeScreen(
                    session,
                    {
                        "subject": subject,
                        "body": "",
                        # Le message d'origine voyage à part : `action_send`
                        # reconstruit le courriel depuis le formulaire, donc
                        # sans ça le transfert partirait VIDE, avec le seul
                        # objet « Fwd: ».
                        "forward_of": original,
                    },
                ),
                self._after_compose,
            )

        def _after_compose(self, status) -> None:
            if status:
                self.set_status(status)
                # `deliver()` a classé une copie dans Envoyés (`sync_one`,
                # tâche 19) — si c'est le dossier déjà ouvert, l'écran doit
                # la montrer tout de suite, pas seulement après un
                # redémarrage. `status` est vide seulement sur annulation
                # (`action_cancel` → `dismiss(None)`), où rien n'a changé.
                self.refresh_current_folder()

        def action_show_log(self) -> None:
            from script.todo.mail.menu import mail_log_path

            self.push_screen(LogScreen(mail_log_path(), self.session_errors))

        def action_show_help(self) -> None:
            self.push_screen(HelpScreen())

        def action_show_outbox(self) -> None:
            if self.current_ref is None:
                self.set_status(t("mail_stats_no_account"))
                return
            self.push_screen(
                OutboxScreen(self.session_for(self.current_ref.account_name))
            )

        def action_show_rules(self) -> None:
            session = self._session_or_first()
            if session is None:
                self.set_status(t("mail_stats_no_account"))
                return
            self.push_screen(RulesScreen(session))

        def action_show_report_settings(self) -> None:
            """Touche `I` : les paramètres du rapport du compte ouvert ;
            l'expéditeur du message sous le curseur préremplit le
            demandeur de l'aperçu."""
            session = self._session_or_first()
            if session is None:
                self.set_status(t("mail_stats_no_account"))
                return
            demandeur = ""
            try:
                meta = self.current_meta()
            except NoMatches:
                meta = None
            if meta is not None:
                demandeur = sole_address(meta.frm or "")
            self.push_screen(
                ReportSettingsScreen(session, requester=demandeur)
            )

        def action_manage_folders(self) -> None:
            if self.current_ref is None:
                self.set_status(t("mail_stats_no_account"))
                return
            session = self.session_for(self.current_ref.account_name)
            if not session.online:
                # Créer ou détruire un dossier passe par le serveur : hors
                # ligne, l'écran ne pourrait qu'échouer à chaque geste.
                self.set_status(t("mail_folder_needs_network"))
                return
            self.push_screen(FolderScreen(session))

        def action_show_stats(self) -> None:
            if self.current_ref is None:
                self.set_status(t("mail_stats_no_account"))
                return
            session = self.session_for(self.current_ref.account_name)
            etat = session.store.folder_state(self.current_ref.folder_name)
            self.push_screen(
                StatsScreen(
                    session.store,
                    folder_id=(etat or {}).get("id"),
                    folder_name=self.current_ref.display,
                )
            )

        def _config_get(self):
            """La lecture de la configuration TODO, ou rien.

            Un TUI monté sans fichier de configuration — les tests en
            montent — retombe sur les variables d'environnement plutôt que
            de lever.
            """
            lire = getattr(self.config_file, "get_config_value", None)
            return lire if callable(lire) else None

        def action_add_account(self) -> None:
            if self.config_file is None or self.secret_store is None:
                self.set_status(t("mail_account_add_unavailable"))
                return
            if account_setup.kdbx_is_configured(self.config_file):
                self.push_screen(
                    AccountScreen(self.secret_store, self._config_get()),
                    self._after_account_added,
                )
            else:
                self.push_screen(VaultScreen(), self._after_vault_screen)

        def _after_vault_screen(self, store) -> None:
            # `store` est `None` si l'écran a été annulé : la création de
            # compte ne doit PAS s'ouvrir sans coffre derrière elle.
            if store is None:
                return
            self.secret_store = store
            self.push_screen(
                AccountScreen(self.secret_store, self._config_get()),
                self._after_account_added,
            )

        def _after_account_added(self, account) -> None:
            if account is None:
                return
            session = open_session(
                account,
                self.secret_store,
                base=self.base,
                connect_fn=self.connect_fn,
            )
            self.sessions.append(session)
            if session.store is not None and session.store.mode == (
                "ephemeral"
            ):
                # `open_sessions()` réinstallerait les gestionnaires de
                # signaux ET rouvrirait TOUS les comptes existants : on
                # n'enregistre le nettoyage QUE pour cette session neuve.
                _register_ephemeral_cleanup([session])
            self.reload_folders()
            self.set_status(t("mail_account_saved"))
            self.run_worker(lambda: self._sync([session]), thread=True)

        def on_unmount(self) -> None:
            for session in self.sessions:
                session.close()

    class LogScreen(ModalScreen):
        """Touche `l` : la fin du journal, et les erreurs de synchronisation
        de la session en cours — sans quitter le client pour les lire dans
        `~/.erplibre/mail.log`.

        Une fenêtre qui s'ouvre VIDE reproduit le défaut qu'elle corrige —
        une erreur signalée, aucun journal pour la lire : chaque état —
        journal absent, vide, illisible, aucune erreur de session — se dit
        en toutes lettres, jamais en silence.
        """

        BINDINGS = [
            Binding("escape", "close_log", t("mail_log_close")),
        ]

        CSS = """
        #log_tail { height: 1fr; border: solid $panel; }
        #log_errors { height: auto; padding: 0 1; }
        """

        def __init__(self, log_path, session_errors):
            super().__init__()
            self.log_path = log_path
            # Référence, pas copie : ce que `MailApp._sync` y a déjà écrit
            # au moment de l'ouverture est exactement ce que cet écran doit
            # montrer, sans logique de synchronisation à lui seul.
            self.session_errors = session_errors

        def compose(self):
            with Vertical(id="log_screen"):
                yield Static(t("mail_log_tail_heading"))
                yield Log(id="log_tail")
                yield Static(t("mail_log_errors_heading"))
                yield Static("", id="log_errors")

        def on_mount(self) -> None:
            lines, message = read_log_tail(self.log_path)
            log_widget = self.query_one("#log_tail", Log)
            if message:
                log_widget.write_line(message)
            else:
                log_widget.write_lines(lines)
            self.query_one("#log_errors", Static).update(
                self._session_errors_text()
            )

        def _session_errors_text(self) -> str:
            rows = [
                f"{account_name} — {error}"
                for account_name, errors in self.session_errors.items()
                for error in errors
            ]
            return "\n".join(rows) if rows else t("mail_log_no_errors")

        def action_close_log(self) -> None:
            self.dismiss()

    class OutboxScreen(ModalScreen):
        """Touche `o` : ce qui attend de partir.

        Chaque ligne porte à sa GAUCHE un bouton qui retient le message ou
        le relâche. Un message retenu ne part jamais seul : seul ce bouton
        lève la retenue. Une réponse automatique porte en plus son
        échéance : passé `expires_at`, la vidange la retire de la file sans
        l'envoyer, retenue ou non.

        `#outbox_preview` montre ce que partira l'entrée automatique dont
        le bouton a le focus (sans focus sur la file, la première
        automatique) : destinataire et sujet, début du texte, images en
        ligne et jointes, échéance. Le focus sur une entrée manuelle le
        vide : un texte resté affiché se lirait comme le sien. Approuver le
        premier envoi d'une règle, c'est relâcher une réponse qu'on a lue.
        Un transfert ou une redirection d'une règle le dit sous l'en-tête ;
        le message d'origine joint ou redirigé y est listé comme le reste.

        Une entrée de transfert peut peser des dizaines de Mio : ses octets
        sont déchiffrés et analysés dans un fil, jamais sur celui de
        l'interface. L'en-tête et l'échéance s'affichent aussitôt, le texte
        à son arrivée ; un aperçu arrivé après un changement de focus est
        ignoré.
        """

        BINDINGS = [
            Binding("escape", "close_outbox", t("mail_outbox_close")),
        ]

        CSS = """
        #outbox_list { height: 1fr; border: solid $panel; }
        #outbox_hint { height: auto; padding: 0 1; color: $text-muted; }
        #outbox_preview { height: auto; max-height: 50%; padding: 0 1; }
        .outbox_row { height: auto; }
        .outbox_row Button { width: 12; }
        .outbox_row Static { width: 1fr; padding: 0 1; }
        """

        def __init__(self, session):
            super().__init__()
            self.session = session
            # Entrées affichées, par identifiant de file.
            self._entrees: dict = {}
            # Numéro du dernier aperçu demandé : un résultat plus ancien,
            # arrivé en retard, n'écrase pas le plus récent.
            self._generation = 0

        def compose(self):
            with Vertical():
                yield Static("", id="outbox_hint")
                yield VerticalScroll(id="outbox_list")
                yield Static("", id="outbox_preview")

        def on_mount(self) -> None:
            self.reload_outbox()

        def reload_outbox(self) -> None:
            zone = self.query_one("#outbox_list", VerticalScroll)
            zone.remove_children()
            try:
                entrees = self.session.store.outbox()
            except Exception as exc:
                self.query_one("#outbox_hint", Static).update(
                    Text(f"{t('mail_outbox_error')} {exc}")
                )
                return
            self.query_one("#outbox_hint", Static).update(
                Text(
                    t("mail_outbox_empty")
                    if not entrees
                    else f"{t('mail_outbox_count')} {len(entrees)}"
                )
            )
            self._entrees = {e["id"]: e for e in entrees}
            for entree in entrees:
                zone.mount(self._ligne(entree))
            visee = self._entree_du_focus()
            if visee is None:
                visee = next(
                    (e for e in entrees if e["kind"] != "manual"), None
                )
            self._montrer_apercu(visee)

        def _entree_du_focus(self):
            ident = str(getattr(self.focused, "id", "") or "")
            if not ident.startswith("hold_"):
                return None
            return self._entrees.get(int(ident.removeprefix("hold_")))

        def on_descendant_focus(self, event) -> None:
            entree = self._entree_du_focus()
            if entree is not None:
                self._montrer_apercu(entree)

        def _montrer_apercu(self, entree) -> None:
            """Remplit `#outbox_preview` pour une entrée automatique ; le
            vide pour une entrée manuelle ou sans entrée.

            L'en-tête (destinataires, sujet, type d'envoi) et l'échéance
            s'affichent tout de suite ; les octets de l'entrée sont lus et
            analysés dans un fil, puis remplacent la ligne d'attente.
            """
            apercu = self.query_one("#outbox_preview", Static)
            self._generation += 1
            generation = self._generation
            if entree is None or entree["kind"] == "manual":
                apercu.update("")
                return
            texte = self._tete_apercu(entree)
            texte.append(f"\n{t('mail_rules_outbox_loading')}", style="dim")
            texte.append_text(self._pied_apercu(entree))
            apercu.update(texte)
            store, ident = self.session.store, entree["id"]

            def travail() -> None:
                try:
                    resultat = outbox_entry_preview(
                        store.queued_raw(ident) or b""
                    )
                    erreur = ""
                except Exception as exc:
                    resultat, erreur = None, str(exc) or type(exc).__name__
                self.app.call_from_thread(
                    self._apercu_pret, generation, entree, resultat, erreur
                )

            self.run_worker(
                travail,
                thread=True,
                exclusive=True,
                group="outbox_preview",
            )

        @staticmethod
        def _tete_apercu(entree) -> "Text":
            texte = Text()
            texte.append(t("mail_outbox_preview"), style="bold")
            # `Text.append` : le destinataire et le sujet viennent du
            # message reçu ; aucun n'est lu comme du balisage.
            texte.append(
                f"\n{entree.get('to') or ''} — {entree.get('subject') or ''}",
                style="bold",
            )
            genre = {
                "auto_forward": "mail_rules_outbox_forward",
                "auto_redirect": "mail_rules_outbox_redirect",
            }.get(entree.get("kind"))
            if genre:
                texte.append(f"\n{t(genre)}", style="dim")
            return texte

        @staticmethod
        def _pied_apercu(entree) -> "Text":
            texte = Text()
            if entree.get("expires_at"):
                texte.append(
                    f"\n{t('mail_outbox_expires')}"
                    f" {format_epoch(entree['expires_at'])}",
                    style="dim",
                )
            return texte

        def _apercu_pret(self, generation, entree, resultat, erreur) -> None:
            """Affiche l'aperçu lu par le fil, s'il est encore le dernier
            demandé : un résultat en retard n'écrase pas celui d'une
            entrée choisie depuis."""
            if generation != self._generation:
                return
            try:
                apercu = self.query_one("#outbox_preview", Static)
            except NoMatches:
                return
            texte = self._tete_apercu(entree)
            if resultat is None:
                texte.append(f"\n{t('mail_outbox_error')} {erreur}")
            else:
                lignes, en_ligne, jointes = resultat
                # `Text.append` : le corps vient de la règle ou du message
                # d'origine, les noms des pièces aussi ; aucun n'est lu
                # comme du balisage.
                for ligne in lignes:
                    texte.append(f"\n{ligne}")
                for nom in en_ligne:
                    texte.append(
                        f"\n{nom} — {t('mail_rules_image_inline')}",
                        style="dim",
                    )
                for nom in jointes:
                    texte.append(
                        f"\n{nom} — {t('mail_rules_image_attached')}",
                        style="dim",
                    )
            texte.append_text(self._pied_apercu(entree))
            apercu.update(texte)

        def _ligne(self, entree):
            libelle = (
                t("mail_outbox_release")
                if entree["held"]
                else t("mail_outbox_hold")
            )
            ligne = Horizontal(classes="outbox_row")
            bouton = Button(libelle, id=f"hold_{entree['id']}")
            # `Text` et non du balisage : destinataire et sujet viennent du
            # message, donc de qui l'a écrit.
            texte = Text()
            automatique = entree.get("kind", "manual") != "manual"
            if automatique:
                texte.append(f"{t('mail_outbox_auto')} ", style="bold")
            texte.append(entree["subject"] or t("mail_no_subject"))
            texte.append(f"\n{entree['to']}", style="dim")
            if automatique and entree.get("expires_at"):
                texte.append(
                    f"\n{t('mail_outbox_expires')}"
                    f" {format_epoch(entree['expires_at'])}",
                    style="dim",
                )
            if entree["last_error"]:
                texte.append(
                    f"\n{t('mail_outbox_last_error')} {entree['last_error']}"
                    f" ({entree['attempts']})",
                    style="dim",
                )
            ligne.compose_add_child(bouton)
            ligne.compose_add_child(Static(texte))
            return ligne

        def on_button_pressed(self, event) -> None:
            ident = str(event.button.id or "")
            if not ident.startswith("hold_"):
                return
            queue_id = int(ident.removeprefix("hold_"))
            entrees = {e["id"]: e for e in self.session.store.outbox()}
            entree = entrees.get(queue_id)
            if entree is None:
                self.reload_outbox()
                return
            self.session.store.set_held(queue_id, not entree["held"])
            self.reload_outbox()

        def action_close_outbox(self) -> None:
            self.dismiss(None)

    class MoveScreen(ModalScreen):
        """Les dossiers où ranger le message : ceux du compte, puis ceux
        des autres.

        Le compte du message vient en premier, sans être nommé — c'est le
        cas courant, et préfixer chaque ligne du nom du compte ouvert
        mangerait la largeur sans rien apprendre. Les dossiers d'un autre
        compte portent le sien : un déplacement qui change de compte n'est
        pas le même geste, et se lit.

        Distincte de `FolderScreen` (`F`), qui CRÉE et DÉTRUIT : mêler un
        choix anodin à des gestes destructeurs met la suppression d'un
        dossier à une touche d'un rangement quotidien.
        """

        BINDINGS = [
            Binding("escape", "cancel", t("mail_move_close")),
            Binding("enter", "choose", t("mail_move_choose")),
        ]

        CSS = """
        #move_list { height: 1fr; border: solid $panel; }
        #move_hint { height: auto; padding: 0 1; color: $text-muted; }
        """

        def __init__(self, session, source: str, sessions=None):
            super().__init__()
            self.session = session
            self.source = source
            # Le compte du message d'abord : c'est là que la plupart des
            # rangements vont, et le curseur y est déjà.
            self.sessions = [session] + [
                autre
                for autre in (sessions or [])
                if autre is not session and autre.online
            ]
            # (session, dossier) — un nom de dossier ne suffit plus à
            # désigner une cible dès que plusieurs comptes sont listés.
            self.cibles: list = []

        def compose(self):
            with Vertical():
                yield Static(Text(t("mail_move_hint")), id="move_hint")
                yield DataTable(id="move_list")

        def on_mount(self) -> None:
            table = self.query_one("#move_list", DataTable)
            table.cursor_type = "row"
            table.add_columns(t("mail_folder_name"), t("mail_stats_total"))
            for session in self.sessions:
                try:
                    dossiers = session.store.folders()
                except Exception as exc:
                    # Le cache d'un compte peut être fermé ou verrouillé :
                    # les autres comptes restent proposables.
                    _logger.exception("dossiers de %s", session.account.name)
                    self.query_one("#move_hint", Static).update(
                        Text(f"{t('mail_folder_error')} {exc}")
                    )
                    continue
                ici = session is self.session
                for dossier in dossiers:
                    if ici and dossier["name"] == self.source:
                        continue
                    nom = dossier["display"] or dossier["name"]
                    table.add_row(
                        nom if ici else f"{session.account.name} — {nom}",
                        str(dossier["total"] or 0),
                        key=f"{session.account.name}\x1f{dossier['name']}",
                    )
                    self.cibles.append((session, dossier["name"]))
            table.focus()

        @property
        def dossiers(self) -> list:
            """Les dossiers proposés, par leur seul nom.

            Gardée pour ce qui ne s'intéresse qu'au contenu du compte
            ouvert ; le choix, lui, passe par `cibles`, un nom de dossier
            ne désignant rien à lui seul dès qu'il y a plusieurs comptes.
            """
            return [nom for _, nom in self.cibles]

        def action_cancel(self) -> None:
            self.dismiss(None)

        def action_choose(self) -> None:
            table = self.query_one("#move_list", DataTable)
            if table.cursor_row is None or table.cursor_row >= len(
                self.cibles
            ):
                return
            self.dismiss(self.cibles[table.cursor_row])

        def on_data_table_row_selected(self, event) -> None:
            self.action_choose()

    class AttachmentScreen(ModalScreen):
        """Laquelle des pièces jointes enregistrer.

        `w` n'en connaissait qu'une : la première. Les autres restaient
        inatteignables depuis le client, sans que rien ne dise qu'elles
        existaient — le nombre s'affiche pourtant dans l'aperçu.

        Ne s'ouvre qu'à partir de deux : poser la question pour une seule
        serait une frappe de plus dont la réponse est connue d'avance.
        """

        BINDINGS = [
            Binding("escape", "cancel", t("mail_attachment_close")),
            Binding("enter", "choose", t("mail_attachment_choose")),
        ]

        CSS = """
        #attach_list { height: 1fr; border: solid $panel; }
        #attach_hint { height: auto; padding: 0 1; color: $text-muted; }
        """

        def __init__(self, attachments):
            super().__init__()
            self.attachments = list(attachments)

        def compose(self):
            with Vertical():
                yield Static(Text(t("mail_attachment_hint")), id="attach_hint")
                yield DataTable(id="attach_list")

        def on_mount(self) -> None:
            table = self.query_one("#attach_list", DataTable)
            table.cursor_type = "row"
            table.add_columns(
                t("mail_attachment_name"),
                t("mail_attachment_type"),
                t("mail_attachment_size"),
            )
            for piece in self.attachments:
                table.add_row(
                    # Le nom vient du message, donc de n'importe qui : il
                    # est tronqué pour l'affichage, et c'est
                    # `save_attachment` qui le rend sûr à l'écriture.
                    tui_text.truncate(piece.filename or "?", 48),
                    piece.content_type or "?",
                    tui_text.format_size(piece.size),
                    key=str(piece.index),
                )
            table.focus()

        def action_cancel(self) -> None:
            self.dismiss(None)

        def action_choose(self) -> None:
            table = self.query_one("#attach_list", DataTable)
            if table.cursor_row is None or table.cursor_row >= len(
                self.attachments
            ):
                return
            self.dismiss(self.attachments[table.cursor_row].index)

        def on_data_table_row_selected(self, event) -> None:
            self.action_choose()

    class ConfirmScreen(ModalScreen):
        """Une question fermée : `Entrée` accepte, `Échap` renonce.

        Distincte de `EmptyTrashScreen`, qui fait TAPER un mot : celle-ci
        garde un geste qui ne détruit rien mais que rien ne défait
        commodément. Exiger un mot pour ça userait la vigilance qu'on veut
        garder intacte là où elle compte vraiment.
        """

        BINDINGS = [
            Binding("escape", "refuse", t("mail_confirm_no")),
            Binding("enter", "accepte", t("mail_confirm_yes")),
        ]

        CSS = """
        #confirm_text { height: auto; padding: 1; }
        """

        def __init__(self, question: str):
            super().__init__()
            self.question = question

        def compose(self):
            with Vertical():
                yield Static(
                    Text(f"{self.question}\n\n{t('mail_confirm_hint')}"),
                    id="confirm_text",
                )

        def action_refuse(self) -> None:
            self.dismiss(False)

        def action_accepte(self) -> None:
            self.dismiss(True)

    class EmptyTrashScreen(ModalScreen):
        """La confirmation d'un geste qui ne se répare pas.

        Elle exige de TAPER un mot, comme la suppression d'un dossier :
        c'est la seule forme de confirmation qu'une frappe de trop ne peut
        pas donner par accident. Elle nomme aussi ce qui va disparaître —
        une confirmation qui ne dit pas sur quoi elle porte n'en est pas
        une.
        """

        BINDINGS = [
            Binding("escape", "cancel", t("mail_empty_trash_close")),
        ]

        CSS = """
        #empty_hint { height: auto; padding: 1; }
        """

        def __init__(self, corbeille: str, total: int):
            super().__init__()
            self.corbeille = corbeille
            self.total = total

        def compose(self):
            with Vertical():
                yield Static(
                    Text(
                        f"« {self.corbeille} » — {self.total}"
                        f" {t('mail_empty_trash_count')}\n\n"
                        f"{t('mail_empty_trash_ask')} {MOT_SUPPRESSION}"
                    ),
                    id="empty_hint",
                )
                yield Input(id="empty_input")

        def on_mount(self) -> None:
            self.query_one("#empty_input", Input).focus()

        def action_cancel(self) -> None:
            self.dismiss(False)

        def on_input_submitted(self, event) -> None:
            self.dismiss(
                (event.value or "").strip().lower() == MOT_SUPPRESSION
            )

    class FolderScreen(ModalScreen):
        """Touche `F` : créer, renommer et supprimer un dossier.

        La suppression détruit le dossier ET son contenu sur le SERVEUR,
        sans corbeille : IMAP n'en a pas pour les dossiers. Elle exige donc
        de taper un mot, pas de confirmer.
        """

        BINDINGS = [
            Binding("escape", "close_folders", t("mail_folder_close")),
            Binding("n", "start_create", t("mail_folder_create")),
            Binding("r", "start_rename", t("mail_folder_rename")),
            Binding("d", "start_delete", t("mail_folder_delete")),
        ]

        CSS = """
        #folder_list { height: 1fr; border: solid $panel; }
        #folder_hint { height: auto; padding: 0 1; color: $text-muted; }
        #folder_input { display: none; }
        #folder_input.visible { display: block; }
        """

        def __init__(self, session):
            super().__init__()
            self.session = session
            self.action = None

        def compose(self):
            with Vertical():
                yield Static("", id="folder_hint")
                yield DataTable(id="folder_list")
                yield Input(id="folder_input")

        def on_mount(self) -> None:
            table = self.query_one("#folder_list", DataTable)
            table.cursor_type = "row"
            table.add_columns(t("mail_folder_name"), t("mail_stats_total"))
            self.reload_folders()
            self.query_one("#folder_hint", Static).update(
                Text(t("mail_folder_hint"))
            )

        def reload_folders(self) -> None:
            table = self.query_one("#folder_list", DataTable)
            table.clear()
            try:
                dossiers = self.session.store.folders()
            except Exception as exc:
                self.query_one("#folder_hint", Static).update(
                    Text(f"{t('mail_folder_error')} {exc}")
                )
                return
            for dossier in dossiers:
                table.add_row(
                    dossier["display"] or dossier["name"],
                    str(dossier["total"] or 0),
                    key=dossier["name"],
                )
            self.dossiers = [d["name"] for d in dossiers]

        def selection(self):
            table = self.query_one("#folder_list", DataTable)
            noms = getattr(self, "dossiers", [])
            if table.cursor_row is None or table.cursor_row >= len(noms):
                return None
            return noms[table.cursor_row]

        def _demander(self, action, invite, valeur="") -> None:
            self.action = action
            champ = self.query_one("#folder_input", Input)
            champ.value = valeur
            champ.placeholder = invite
            champ.add_class("visible")
            champ.focus()
            self.query_one("#folder_hint", Static).update(Text(invite))

        def action_start_create(self) -> None:
            self._demander("create", t("mail_folder_ask_new"))

        def action_start_rename(self) -> None:
            courant = self.selection()
            if courant is None:
                return
            self._demander("rename", t("mail_folder_ask_rename"), courant)

        def action_start_delete(self) -> None:
            courant = self.selection()
            if courant is None:
                return
            self._demander(
                "delete",
                f"{t('mail_folder_ask_delete')} « {courant} » — "
                f"{MOT_SUPPRESSION}",
            )

        def on_input_submitted(self, event) -> None:
            saisie = (event.value or "").strip()
            action, self.action = self.action, None
            champ = self.query_one("#folder_input", Input)
            champ.remove_class("visible")
            champ.value = ""
            if not action or not saisie:
                return
            try:
                self._appliquer(action, saisie)
            except Exception as exc:
                self.query_one("#folder_hint", Static).update(
                    Text(f"{t('mail_folder_error')} {exc}")
                )
                return
            self.reload_folders()
            self.query_one("#folder_hint", Static).update(
                Text(t("mail_folder_done"))
            )

        def _appliquer(self, action, saisie) -> None:
            """Le serveur D'ABORD, le cache ensuite.

            Si le serveur refuse, le cache ne doit pas décrire un état qui
            n'existe nulle part — un dossier absent de l'arbre distant et
            présent dans le nôtre ne se resynchronise jamais.
            """
            transport = self.session.syncer.transport
            if action == "create":
                transport.create_folder(saisie)
                self.session.store.upsert_folder(saisie, saisie, None)
            elif action == "rename":
                courant = self.selection()
                if courant is None or courant == saisie:
                    return
                transport.rename_folder(courant, saisie)
                self.session.store.rename_folder(courant, saisie)
            elif action == "delete":
                if saisie.lower() != MOT_SUPPRESSION:
                    raise ValueError(t("mail_folder_not_confirmed"))
                courant = self.selection()
                if courant is None:
                    return
                transport.delete_folder(courant)
                self.session.store.forget_folder(courant)

        def action_close_folders(self) -> None:
            self.dismiss(None)

    class StatsScreen(ModalScreen):
        """Touche `i` : ce que le cache sait déjà dire du compte ouvert.

        Aucune requête réseau : tout vient du cache, donc l'écran répond
        hors ligne et instantanément. `d`, `w` et `m` changent le pas de
        l'histogramme ; `f` restreint au dossier ouvert ou l'élargit à tout
        le compte.
        """

        BINDINGS = [
            Binding("escape", "close_stats", t("mail_stats_close")),
            Binding("d", "bucket_day", t("mail_stats_by_day")),
            Binding("w", "bucket_week", t("mail_stats_by_week")),
            Binding("m", "bucket_month", t("mail_stats_by_month")),
            Binding("f", "toggle_folder", t("mail_stats_folder_filter")),
            Binding("enter", "load_details", t("mail_stats_details")),
        ]

        CSS = """
        /* `auto` et NON `1fr` sur le contenu : `1fr` le contraint à la
           hauteur de la fenêtre, la hauteur virtuelle du conteneur devient
           égale à la hauteur visible, et il n'y a plus rien à faire
           défiler — le texte est tronqué, pas débordant. Le conteneur, lui,
           prend la place restante. */
        #stats_scroll { height: 1fr; border: solid $panel; }
        #stats_body { height: auto; padding: 0 1; }
        #stats_head { height: auto; padding: 0 1; color: $text-muted; }
        #stats_choix { height: auto; padding: 0 1; }
        #stats_choix Select { width: 1fr; }
        """

        def __init__(self, store, folder_id=None, folder_name=""):
            super().__init__()
            self.store = store
            self.folder_id = folder_id
            self.folder_name = folder_name
            # `None` : le pas se choisit d'après l'étendue de la boîte au
            # premier affichage. Une fois qu'une touche l'a fixé, il reste.
            self.bucket = None
            self.restreint = False
            self.details = None
            self.calcul_en_cours = False
            # 0 = pas de borne. Exprimé en jours, converti en date au
            # moment de la requête : une borne calculée à l'ouverture
            # vieillirait sur un écran laissé ouvert.
            self.periode_jours = 0
            # Section d'activité : (jours, tableau texte) ou texte
            # d'erreur, calculée au premier affichage puis gardée : elle ne
            # dépend ni de la période ni de la portée choisies.
            self._activite = None

        # (valeur, clé i18n). L'ordre est celui de la liste déroulante.
        PAS = (
            ("day", "mail_stats_by_day"),
            ("week", "mail_stats_by_week"),
            ("month", "mail_stats_by_month"),
            ("year", "mail_stats_by_year"),
        )
        # (valeur, clé i18n, jours). Des chaînes et non des entiers : un
        # `Select` refuse une valeur fausse au sens booléen, et « toute la
        # période » vaudrait naturellement 0.
        PERIODES = (
            ("all", "mail_stats_period_all", 0),
            ("year", "mail_stats_period_year", 365),
            ("5years", "mail_stats_period_5years", 1825),
            ("month", "mail_stats_period_month", 30),
        )

        def compose(self):
            with Vertical():
                with Horizontal(id="stats_choix"):
                    yield Select(
                        [(t(cle), valeur) for valeur, cle in self.PAS],
                        # `Select.NULL`, PAS `Select.BLANK` : dans Textual
                        # 8 cette dernière vaut littéralement `False`, que
                        # le widget refuse comme valeur. Aucune sélection au
                        # départ — le pas se déduit de l'étendue de la boîte
                        # et la liste s'aligne dessus au premier affichage.
                        value=Select.NULL,
                        prompt=t("mail_stats_step"),
                        id="stats_pas",
                    )
                    yield Select(
                        [(t(cle), valeur) for valeur, cle, _ in self.PERIODES],
                        value="all",
                        allow_blank=False,
                        id="stats_periode",
                    )
                    yield Select(
                        [
                            (t("mail_stats_all_folders"), "all"),
                            (
                                self.folder_name or t("mail_stats_folder"),
                                "folder",
                            ),
                        ],
                        value="all",
                        allow_blank=False,
                        id="stats_portee",
                    )
                yield Static("", id="stats_head")
                yield VerticalScroll(
                    Static("", id="stats_body"), id="stats_scroll"
                )

        def on_mount(self) -> None:
            self.refresh_stats()
            # Le focus va au conteneur défilable, pas à la première liste :
            # les flèches font alors défiler dès l'ouverture, et `enter`
            # atteint la liaison de l'écran au lieu de déplier une liste.
            self.query_one("#stats_scroll").focus()

        def refresh_stats(self) -> None:
            """La vue d'ensemble, et elle seule.

            Uniquement du SQL : ni correspondants ni délais de réponse. Les
            premiers ouvrent chaque colonne scellée, les seconds joignent la
            table avec elle-même ; sur une grande boîte ils coûtent des
            secondes, et les payer avant le premier affichage fige l'écran
            au moment précis où l'utilisateur attend une réponse.
            """
            cible = self.folder_id if self.restreint else None
            depuis = self._depuis()
            try:
                apercu = stats.build_overview(
                    self.store,
                    bucket=self.bucket,
                    folder_id=cible,
                    since=depuis,
                )
            except Exception as exc:
                self.query_one("#stats_body", Static).update(
                    Text(f"{t('mail_stats_error')} {exc}")
                )
                return
            self.bucket = apercu.bucket
            if self._activite is None:
                self._activite = self._calculer_activite()
            portee = (
                self.folder_name
                if self.restreint and self.folder_name
                else t("mail_stats_all_folders")
            )
            self.query_one("#stats_head", Static).update(
                Text(
                    f"{t('mail_stats_scope')} {portee}"
                    f"   ·   {t(f'mail_stats_by_{self.bucket}')}"
                )
            )
            self.query_one("#stats_body", Static).update(self._rendu(apercu))

        def _rendu(self, apercu) -> "Text":
            """Le rapport en texte enrichi.

            `Text` et non du balisage : les adresses viennent des messages,
            donc de n'importe qui, et un crochet dans une adresse serait lu
            comme une balise.
            """
            sortie = Text()

            def titre(cle):
                sortie.append(f"\n{t(cle)}\n", style="bold")

            sortie.append_text(self._rendu_activite())
            sortie.append(
                f"{t('mail_stats_total')} {apercu.total}"
                f"   {tui_text.format_size(apercu.total_size)}"
                f"   {t('mail_stats_unseen')} {apercu.unseen}"
                f" ({apercu.unseen_share:.0%})\n"
            )
            if apercu.undated:
                sortie.append(
                    f"{t('mail_stats_undated')} {apercu.undated}\n",
                    style="dim",
                )

            titre("mail_stats_volume")
            if apercu.tronque:
                # Le total porte sur TOUT ; seule la liste est coupée. Le
                # taire ferait un histogramme qui ne se recoupe pas avec le
                # nombre affiché juste au-dessus.
                sortie.append(
                    f"  {t('mail_stats_truncated')} {apercu.tronque}\n",
                    style="dim",
                )
            for etiquette, nombre, barre in apercu.volume:
                sortie.append(f"  {etiquette}  {nombre:>5}  {barre}\n")

            titre("mail_stats_folders")
            for dossier in apercu.folders:
                sortie.append(
                    f"  {dossier['display']}  {dossier['count']}"
                    f"  ({dossier['unseen']} {t('mail_stats_unseen')})"
                    f"  {tui_text.format_size(dossier['size'])}\n"
                )

            sortie.append_text(self._rendu_details())
            return sortie

        def _calculer_activite(self):
            """Reçus, lus et répondus par jour clos de la boîte de
            réception, sur les jours des réglages du rapport du compte.

            Du SQL seul (`collect_mailbox`), sans colonne scellée : la
            section s'affiche avec la vue d'ensemble. Des réglages
            illisibles, ou un cache sans base de règles, donnent les
            réglages par défaut. Rend (jours, tableau) ou un texte
            d'erreur.
            """
            reglages = rules_storage.ReportSettings()
            base = rules_storage.base_of(self.store)
            if base is not None:
                try:
                    reglages = rules_storage.load_report(
                        self.store.account.name, base=base
                    )
                except rules_model.RuleError:
                    reglages = rules_storage.ReportSettings()
            try:
                boite = rules_report.collect_mailbox(
                    self.store, reglages, now=int(time.time())
                )
            except Exception as exc:
                return f"{t('mail_stats_error')} {exc}"
            return (
                len(boite.days),
                rules_report.text_table(boite.days, "day", ""),
            )

        def _rendu_activite(self) -> "Text":
            sortie = Text()
            activite = self._activite
            if isinstance(activite, str):
                sortie.append(f"{activite}\n\n", style="dim")
                return sortie
            if activite is None:
                return sortie
            jours, tableau = activite
            sortie.append(
                t("mail_stats_activity_title").replace("{n}", str(jours))
                + "\n",
                style="bold",
            )
            for ligne in tableau.splitlines():
                sortie.append(f"  {ligne}\n")
            sortie.append("\n")
            return sortie

        def _rendu_details(self) -> "Text":
            """Les correspondants et les délais, ou l'invitation à les
            calculer. Ils balaient toute la boîte : on ne les impose pas à
            qui vient seulement regarder le volume."""
            sortie = Text()
            if self.calcul_en_cours:
                sortie.append(f"\n{t('mail_stats_computing')}\n", style="dim")
                return sortie
            if self.details is None:
                sortie.append(
                    f"\n{t('mail_stats_details_hint')}\n", style="dim"
                )
                return sortie

            sortie.append(f"\n{t('mail_stats_senders')}\n", style="bold")
            for adresse, nombre in self.details.senders:
                sortie.append(f"  {nombre:>5}  {adresse}\n")
            sortie.append(f"\n{t('mail_stats_recipients')}\n", style="bold")
            for adresse, nombre in self.details.recipients:
                sortie.append(f"  {nombre:>5}  {adresse}\n")
            sortie.append(f"\n{t('mail_stats_reply')}\n", style="bold")
            if self.details.reply_count:
                sortie.append(
                    f"  {t('mail_stats_reply_median')} "
                    f"{stats.humain(self.details.reply_median)}"
                    f"  ({self.details.reply_count})\n"
                )
            else:
                sortie.append(f"  {t('mail_stats_reply_none')}\n", style="dim")
            return sortie

        def action_load_details(self) -> None:
            """Lance le balayage dans un fil de travail.

            Sur le fil de l'interface, ces secondes gèleraient la fenêtre —
            y compris Échap, donc sans moyen d'en sortir.
            """
            if self.calcul_en_cours:
                return
            self.calcul_en_cours = True
            self.refresh_stats()
            self.run_worker(self._calculer_details, thread=True)

        def _depuis(self):
            """Le début de la période choisie, ou `None` pour « tout ».

            Un seul endroit la calcule : la vue d'ensemble et le balayage
            des détails s'affichent sous le MÊME en-tête de période, et
            deux calculs séparés finiraient par diverger.
            """
            if not self.periode_jours:
                return None
            return time.time() - self.periode_jours * 86400

        def _calculer_details(self) -> None:
            cible = self.folder_id if self.restreint else None

            def progression(faits, total):
                self.app.call_from_thread(self._dire_progression, faits, total)

            try:
                details = stats.build_details(
                    self.store,
                    folder_id=cible,
                    progress=progression,
                    since=self._depuis(),
                )
            except Exception as exc:
                self.app.call_from_thread(self._details_en_erreur, exc)
                return
            self.app.call_from_thread(self._details_prets, details)

        def _dire_progression(self, faits, total) -> None:
            part = f"{faits}/{total}" if total else str(faits)
            self.query_one("#stats_head", Static).update(
                Text(f"{t('mail_stats_computing')} {part}")
            )

        def _details_prets(self, details) -> None:
            self.details = details
            self.calcul_en_cours = False
            self.refresh_stats()

        def _details_en_erreur(self, exc) -> None:
            self.calcul_en_cours = False
            self.details = None
            self.query_one("#stats_head", Static).update(
                Text(f"{t('mail_stats_error')} {exc}")
            )

        def on_select_changed(self, event) -> None:
            """Les listes déroulantes et les touches mènent au même état.

            Deux chemins vers un seul réglage : sans cette remise à jour de
            `self.bucket`, la liste afficherait un pas et l'écran en
            montrerait un autre.
            """
            if event.value is Select.NULL:
                return
            if event.select.id == "stats_pas":
                self.bucket = event.value
            elif event.select.id == "stats_periode":
                self.periode_jours = next(
                    jours
                    for valeur, _, jours in self.PERIODES
                    if valeur == event.value
                )
            elif event.select.id == "stats_portee":
                self.restreint = event.value == "folder"
            # Toute la sélection change : les détails portaient sur l'autre.
            self.details = None
            self.refresh_stats()

        def _set_bucket(self, bucket) -> None:
            self.bucket = bucket
            # La liste doit suivre la touche, sinon elle annonce un pas que
            # l'écran n'utilise pas.
            self.query_one("#stats_pas", Select).value = bucket
            self.refresh_stats()

        def action_bucket_day(self) -> None:
            self._set_bucket("day")

        def action_bucket_week(self) -> None:
            self._set_bucket("week")

        def action_bucket_month(self) -> None:
            self._set_bucket("month")

        def action_toggle_folder(self) -> None:
            self.restreint = not self.restreint
            self.query_one("#stats_portee", Select).value = (
                "folder" if self.restreint else "all"
            )
            # Les détails portaient sur l'autre portée : les garder
            # afficherait des correspondants qui ne sont plus ceux du
            # filtre annoncé juste au-dessus.
            self.details = None
            self.refresh_stats()

        def action_close_stats(self) -> None:
            self.dismiss(None)

    class ReportSettingsScreen(ModalScreen):
        """Touche `I` : les paramètres du rapport de statistiques d'un
        compte (clé `report` de `rules.json`) et l'aperçu du bloc
        `{{rapport}}` sur la boîte réelle.

        L'aperçu lit les réglages DES CHAMPS, enregistrés ou non, et
        calcule en direct, sans instantané, dans un fil de travail : il
        parcourt jusqu'à un an de la boîte de réception. Un demandeur saisi
        y ajoute la ligne de son propre délai. Le texte affiché est la
        valeur TEXTE du bloc, en `Text`. Un champ invalide met l'erreur en
        statut et ne calcule rien.

        `ctrl+s` écrit dans un fil (`save_report`, sous le verrou du
        compte) ; l'écran reste ouvert. Le fuseau est celui du processus,
        affiché et non modifiable. Un cache éphémère ou non ouvert n'a pas
        de réglages : l'écran n'affiche que sa bannière.
        """

        BINDINGS = [
            Binding("ctrl+s", "save_report", t("mail_rules_save")),
            Binding("escape", "close_report", t("mail_rules_close")),
        ]

        CSS = """
        #report_screen { height: 1fr; }
        #report_title { height: auto; padding: 0 1; text-style: bold; }
        #report_banner { height: auto; padding: 1; }
        .report_row { height: auto; }
        .report_row Static { width: 44; padding: 1 1 0 1; }
        .report_row Input { width: 1fr; }
        .report_row Select { width: 1fr; }
        #report_auth_warn { height: auto; padding: 0 1; color: $text-muted; }
        #report_tz { height: auto; padding: 0 1; }
        #report_preview { height: auto; padding: 0 1; border: solid $panel; }
        #report_status { height: auto; padding: 0 1; }
        #report_buttons { height: auto; }
        #report_buttons Button { width: auto; }
        """

        # Valeur du `Select` de langue → langue des réglages. « ui » tient
        # la place de « » : un `Select` refuse une valeur fausse au sens
        # booléen.
        LANGUES = (
            ("ui", "", "mail_stats_report_lang_ui"),
            ("fr", "fr", "mail_stats_report_lang_fr"),
            ("en", "en", "mail_stats_report_lang_en"),
        )

        def __init__(self, session, requester: str = ""):
            super().__init__()
            self.session = session
            self.account_name = session.account.name
            store = getattr(session, "store", None)
            self.base = (
                rules_storage.base_of(store) if store is not None else None
            )
            self.requester = requester or ""
            # Numéro du dernier aperçu demandé : un résultat plus ancien,
            # arrivé en retard, n'écrase pas le plus récent.
            self._generation = 0
            self._ecriture = False

        def _ligne(self, cle: str, widget):
            ligne = Horizontal(classes="report_row")
            ligne.compose_add_child(Static(t(cle)))
            ligne.compose_add_child(widget)
            return ligne

        def compose(self):
            with VerticalScroll(id="report_screen"):
                yield Static(
                    Text(
                        f"{t('mail_stats_report_title')} {self.account_name}"
                    ),
                    id="report_title",
                )
                if self.base is None:
                    yield Static(self._banniere(), id="report_banner")
                    return
                yield self._ligne(
                    "mail_stats_report_days",
                    Input(type="integer", id="report_days"),
                )
                yield self._ligne(
                    "mail_stats_report_weeks",
                    Input(type="integer", id="report_weeks"),
                )
                yield self._ligne(
                    "mail_stats_report_window",
                    Input(type="integer", id="report_window"),
                )
                yield self._ligne(
                    "mail_stats_report_format",
                    Select(
                        [
                            (t(f"mail_rules_format_{f}"), f)
                            for f in rules_model.FORMATS
                        ],
                        value="markdown",
                        allow_blank=False,
                        id="report_format",
                    ),
                )
                yield self._ligne(
                    "mail_stats_report_lang",
                    Select(
                        [(t(cle), valeur) for valeur, _, cle in self.LANGUES],
                        value="ui",
                        allow_blank=False,
                        id="report_lang",
                    ),
                )
                yield self._ligne(
                    "mail_stats_report_auth_serv",
                    Input(id="report_auth_serv"),
                )
                yield Static("", id="report_auth_warn")
                yield Static(
                    Text(
                        f"{t('mail_stats_report_tz')} "
                        f"{time.strftime('%Z (UTC%z)')}"
                    ),
                    id="report_tz",
                )
                yield self._ligne(
                    "mail_stats_report_requester",
                    Input(value=self.requester, id="report_requester"),
                )
                yield Button(
                    t("mail_stats_report_refresh"), id="report_refresh"
                )
                yield Static("", id="report_preview")
                yield Static("", id="report_status")
                with Horizontal(id="report_buttons"):
                    yield Button(
                        t("mail_rules_save"),
                        id="report_save",
                        variant="primary",
                    )
                    yield Button(t("mail_rules_cancel"), id="report_cancel")

        def _banniere(self) -> Text:
            store = getattr(self.session, "store", None)
            if getattr(store, "mode", None) == "ephemeral":
                return Text(t("mail_rules_ephemeral"))
            erreur = getattr(self.session, "error", "") or ""
            return Text(f"{t('mail_rules_no_cache')} {erreur}".strip())

        def on_mount(self) -> None:
            if self.base is None:
                return
            erreur = ""
            try:
                reglages = rules_storage.load_report(
                    self.account_name, base=self.base
                )
            except rules_model.RuleError as exc:
                reglages = rules_storage.ReportSettings()
                erreur = str(exc)
            self.query_one("#report_days", Input).value = str(reglages.days)
            self.query_one("#report_weeks", Input).value = str(reglages.weeks)
            self.query_one("#report_window", Input).value = str(
                reglages.delay_window_days
            )
            self.query_one("#report_format", Select).value = reglages.format
            self.query_one("#report_lang", Select).value = next(
                valeur
                for valeur, langue, _ in self.LANGUES
                if langue == reglages.lang
            )
            self.query_one(
                "#report_auth_serv", Input
            ).value = reglages.auth_serv_id
            self._avertir_auth_serv()
            self._apercu()
            if erreur:
                self._status(erreur, error=True)
            self.query_one("#report_days", Input).focus()

        def _status(self, text: str, *, error: bool = False) -> None:
            try:
                status = self.query_one("#report_status", Static)
            except NoMatches:
                return
            status.update(Text(text, style="bold red" if error else ""))

        def _avertir_auth_serv(self) -> None:
            vide = not self.query_one("#report_auth_serv", Input).value.strip()
            self.query_one("#report_auth_warn", Static).update(
                Text(t("mail_stats_report_auth_serv_unset") if vide else "")
            )

        def on_input_changed(self, event) -> None:
            if event.input.id == "report_auth_serv":
                self._avertir_auth_serv()

        def _reglages(self):
            """Les réglages lus des champs ; `RuleError` (nommant le
            champ) si l'un est hors bornes ou n'est pas un entier."""

            def entier(selecteur: str):
                texte = self.query_one(selecteur, Input).value.strip()
                try:
                    return int(texte)
                except ValueError:
                    # Laissé en texte : `report_from_dict` le refuse en
                    # nommant le champ.
                    return texte

            choix = self.query_one("#report_lang", Select).value
            langue = next(
                (lg for valeur, lg, _ in self.LANGUES if valeur == choix), ""
            )
            return rules_storage.report_from_dict(
                {
                    "days": entier("#report_days"),
                    "weeks": entier("#report_weeks"),
                    "delay_window_days": entier("#report_window"),
                    "format": self.query_one("#report_format", Select).value,
                    "lang": langue,
                    "auth_serv_id": self.query_one(
                        "#report_auth_serv", Input
                    ).value.strip(),
                }
            )

        def _apercu(self) -> None:
            """Recalcule l'aperçu dans un fil, sur les réglages des
            champs."""
            if self.base is None:
                return
            try:
                reglages = self._reglages()
            except rules_model.RuleError as exc:
                self._status(str(exc), error=True)
                return
            self._status("")
            self._generation += 1
            generation = self._generation
            demandeur = normalize_address(
                self.query_one("#report_requester", Input).value.strip()
            )
            self.query_one("#report_preview", Static).update(
                Text(t("mail_stats_computing"), style="dim")
            )
            store = self.session.store

            def travail() -> None:
                try:
                    donnees = rules_report.build_data(
                        store,
                        reglages,
                        now=int(time.time()),
                        sender=demandeur or None,
                    )
                    texte, erreur = (
                        rules_report.values(donnees)["rapport"][0],
                        "",
                    )
                except Exception as exc:
                    texte, erreur = "", str(exc) or type(exc).__name__
                self.app.call_from_thread(
                    self._apercu_pret, generation, texte, erreur
                )

            self.run_worker(travail, thread=True)

        def _apercu_pret(self, generation: int, texte: str, erreur: str):
            if generation != self._generation:
                return
            try:
                apercu = self.query_one("#report_preview", Static)
            except NoMatches:
                return
            if erreur:
                apercu.update(
                    Text(f"{t('mail_stats_error')} {erreur}", style="bold red")
                )
            else:
                apercu.update(Text(texte))

        def action_save_report(self) -> None:
            if self.base is None or self._ecriture:
                return
            try:
                reglages = self._reglages()
            except rules_model.RuleError as exc:
                self._status(str(exc), error=True)
                return
            self._ecriture = True
            self._status("")
            self.query_one("#report_save", Button).disabled = True
            nom, base = self.account_name, self.base

            def travail() -> None:
                erreur = ""
                try:
                    rules_storage.save_report(nom, reglages, base=base)
                except Exception as exc:
                    erreur = str(exc) or type(exc).__name__
                self.app.call_from_thread(self._enregistre, erreur)

            self.run_worker(travail, thread=True)

        def _enregistre(self, erreur: str) -> None:
            self._ecriture = False
            try:
                self.query_one("#report_save", Button).disabled = False
            except NoMatches:
                return
            if erreur:
                self._status(erreur, error=True)
            else:
                self._status(t("mail_stats_report_saved"))

        def on_button_pressed(self, event) -> None:
            ident = event.button.id
            if ident == "report_refresh":
                self._apercu()
            elif ident == "report_save":
                self.action_save_report()
            elif ident == "report_cancel":
                self.action_close_report()

        def action_close_report(self) -> None:
            self.dismiss(None)

    class RulesScreen(ModalScreen):
        """Touche `e` : les règles du courrier entrant d'un compte.

        Une ligne par règle, dans l'ordre où le moteur les applique ; la
        clé de chaque ligne est l'`id` de la règle, et le curseur suit la
        règle quand une touche la déplace ou la modifie. ÉDITER passe par
        `on_data_table_row_selected` et non par une liaison `enter`, que
        le `DataTable` focalisé consomme pour son propre `select_cursor`.

        Chaque mutation (`rules_storage`) prend le verrou du compte, qu'une
        passe du moteur peut tenir : elle tourne donc dans un fil de
        travail, et `RulesBusy`/`RuleError` s'affichent dans
        `#rules_status`, au-dessus de la modale, jamais sous elle. Une
        seule mutation à la fois : une touche pressée pendant l'attente du
        verrou est ignorée, l'interface reste vivante.

        `s` ouvre l'essai de la règle sous le curseur (`TrialScreen`).
        Les plafonds d'envois du compte (clé `caps` de `rules.json`) se
        règlent sous la table. Un cache éphémère n'a pas de règles :
        l'écran n'affiche que sa bannière.
        """

        BINDINGS = [
            Binding("n", "new_rule", t("mail_rules_new")),
            Binding("space", "toggle_rule", t("mail_rules_toggle")),
            Binding("k", "move_up", t("mail_rules_up")),
            Binding("j", "move_down", t("mail_rules_down")),
            Binding("t", "toggle_stop", t("mail_rules_stop_toggle")),
            Binding("x", "delete_rule", t("mail_rules_delete")),
            Binding("s", "trial_rule", t("mail_rules_trial")),
            Binding("l", "show_journal", t("mail_rules_journal")),
            Binding("escape", "close_rules", t("mail_rules_close")),
        ]

        CSS = """
        #rules_title { height: auto; padding: 0 1; text-style: bold; }
        #rules_banner { height: auto; padding: 1; }
        #rules_table { height: 1fr; border: solid $panel; }
        #rules_caps { height: auto; }
        #rules_caps Static { width: auto; padding: 1 1 0 1; }
        #rules_caps Input { width: 12; }
        #rules_caps Button { width: auto; }
        #rules_hint { height: auto; padding: 0 1; color: $text-muted; }
        #rules_status { height: auto; padding: 0 1; }
        """

        def __init__(self, session):
            super().__init__()
            self.session = session
            self.account_name = session.account.name
            store = getattr(session, "store", None)
            # `base_of` est la seule source de la base ; None (cache
            # éphémère, ou pas de cache) n'est jamais transmis à
            # `rules_storage`, qui le lirait comme le dossier personnel.
            self.base = (
                rules_storage.base_of(store) if store is not None else None
            )
            self.rules: list = []
            self._mutation_en_cours = False

        def compose(self):
            with Vertical(id="rules_screen"):
                yield Static(
                    Text(f"{t('mail_rules_title')} {self.account_name}"),
                    id="rules_title",
                )
                if self.base is None:
                    yield Static(self._banniere(), id="rules_banner")
                else:
                    yield DataTable(id="rules_table", cursor_type="row")
                    with Horizontal(id="rules_caps"):
                        yield Static(t("mail_rules_caps_per_pass"))
                        yield Input(type="integer", id="caps_per_pass")
                        yield Static(t("mail_rules_caps_per_hour"))
                        yield Input(type="integer", id="caps_per_hour")
                        yield Button(t("mail_rules_caps_save"), id="caps_save")
                    yield Static("", id="rules_hint")
                    yield Static("", id="rules_status")

        def _banniere(self) -> Text:
            """Pourquoi il n'y a pas de règles : cache éphémère, ou cache
            que l'ouverture n'a pas pu lire (son erreur suit)."""
            store = getattr(self.session, "store", None)
            if getattr(store, "mode", None) == "ephemeral":
                return Text(t("mail_rules_ephemeral"))
            erreur = getattr(self.session, "error", "") or ""
            return Text(f"{t('mail_rules_no_cache')} {erreur}".strip())

        def on_mount(self) -> None:
            if self.base is None:
                return
            table = self.query_one("#rules_table", DataTable)
            table.add_columns(
                t("mail_rules_col_order"),
                t("mail_rules_col_active"),
                t("mail_rules_col_name"),
                t("mail_rules_col_kind"),
                t("mail_rules_col_stop"),
                t("mail_rules_col_last"),
            )
            self.query_one("#rules_hint", Static).update(
                Text(self._hint_text())
            )
            self.reload_rules()
            self._load_caps()
            table.focus()

        def _hint_text(self) -> str:
            """Les liaisons de l'écran, engendrées depuis `BINDINGS` comme
            l'aide `h` ; `enter` (édition par la table) s'y ajoute."""
            parts = [
                f"{self.app.get_key_display(binding)} {binding.description}"
                for binding in Binding.make_bindings(self.BINDINGS)
            ]
            enter = Binding("enter", "", t("mail_rules_edit"))
            parts.insert(
                1, f"{self.app.get_key_display(enter)} {enter.description}"
            )
            return " · ".join(parts)

        def _status(self, text, *, error: bool = False) -> None:
            try:
                status = self.query_one("#rules_status", Static)
            except NoMatches:
                return
            status.update(Text(text, style="bold red" if error else ""))

        def _current_rule_id(self):
            table = self.query_one("#rules_table", DataTable)
            if table.row_count == 0:
                return None
            try:
                cle = table.coordinate_to_cell_key(table.cursor_coordinate)
            except Exception:
                return None
            return cle.row_key.value

        def _current_rule(self):
            ident = self._current_rule_id()
            return next((r for r in self.rules if r.id == ident), None)

        def _last_result(self, rule_id: str):
            """Date, issue et raison traduites de la dernière ligne du
            journal de la règle ; « » si elle n'a encore rien journalisé."""
            try:
                lignes = self.session.store.rule_log_entries(rule_id, 1)
            except Exception:
                return Text("")
            if not lignes:
                return Text("")
            ligne = lignes[0]
            issue = t(f"mail_rules_outcome_{ligne['outcome']}")
            raison = ligne["reason"]
            if raison:
                issue = f"{issue} ({t(f'mail_rules_reason_{raison}')})"
            return Text(f"{format_epoch(ligne['at'])} {issue}")

        def reload_rules(self, select_id=None) -> None:
            """Relit `rules.json` et reconstruit la table, curseur posé sur
            `select_id` (à défaut, sur la règle qu'il désignait)."""
            table = self.query_one("#rules_table", DataTable)
            visee = select_id or self._current_rule_id()
            table.clear()
            try:
                self.rules = rules_storage.load(
                    self.account_name, base=self.base
                )
            except rules_model.RuleError as exc:
                self.rules = []
                self._status(str(exc), error=True)
                return
            for rang, rule in enumerate(self.rules, start=1):
                genre = rule.action.kind
                # `Text` partout : nom et type viennent du fichier, que
                # l'utilisateur écrit ; « [auto] » doit s'afficher tel quel.
                table.add_row(
                    str(rang),
                    "☑" if rule.enabled else "☐",
                    Text(rule.name or rule.id),
                    Text(t(f"mail_rules_kind_{genre}")),
                    "☑" if rule.stop_after else "☐",
                    self._last_result(rule.id),
                    key=rule.id,
                )
            self._status("" if self.rules else t("mail_rules_none"))
            if visee and any(r.id == visee for r in self.rules):
                table.move_cursor(row=table.get_row_index(visee))

        def _load_caps(self) -> None:
            try:
                caps = rules_storage.load_caps(
                    self.account_name, base=self.base
                )
            except rules_model.RuleError as exc:
                caps = rules_storage.Caps()
                self._status(str(exc), error=True)
            self.query_one("#caps_per_pass", Input).value = str(caps.per_pass)
            self.query_one("#caps_per_hour", Input).value = str(caps.per_hour)

        def _mutate(self, fonction, rule_id=None, succes: str = "") -> None:
            """Exécute `fonction` (une mutation de `rules_storage`) dans un
            fil de travail, puis relit la table sur le fil de l'interface.

            Sans effet si une mutation est déjà en cours : deux mutations
            de front se disputeraient le curseur de la table.
            """
            if self.base is None or self._mutation_en_cours:
                return
            self._mutation_en_cours = True
            self._status("")

            def travail() -> None:
                erreur = None
                try:
                    fonction()
                except Exception as exc:
                    erreur = str(exc) or type(exc).__name__
                self.app.call_from_thread(
                    self._apres_mutation, rule_id, erreur, succes
                )

            self.run_worker(travail, thread=True)

        def _apres_mutation(self, rule_id, erreur, succes) -> None:
            self._mutation_en_cours = False
            try:
                self.reload_rules(rule_id)
            except NoMatches:
                return
            if erreur:
                self._status(erreur, error=True)
            elif succes:
                self._status(succes)

        def action_new_rule(self) -> None:
            if self.base is None:
                return
            self.app.push_screen(
                RuleEditorScreen(
                    self.session,
                    self.base,
                    rules_model.new_rule("reply"),
                    new=True,
                ),
                self._apres_edition,
            )

        def on_data_table_row_selected(self, event) -> None:
            ident = event.row_key.value
            rule = next((r for r in self.rules if r.id == ident), None)
            if rule is None:
                return
            self.app.push_screen(
                RuleEditorScreen(self.session, self.base, rule),
                self._apres_edition,
            )

        def _apres_edition(self, rule_id) -> None:
            if not rule_id:
                return
            self.reload_rules(rule_id)
            self._status(t("mail_rules_saved"))

        def action_toggle_rule(self) -> None:
            rule = self._current_rule() if self.base else None
            if rule is None:
                return
            activer = not rule.enabled
            # Activer arme sur l'UIDNEXT connu : la règle ne répond pas à
            # ce qui attendait déjà dans la boîte.
            arme = rules_arm_point(self.session.store) if activer else None
            nom, base = self.account_name, self.base
            self._mutate(
                lambda: rules_storage.set_enabled(
                    nom, rule.id, activer, armed=arme, base=base
                ),
                rule.id,
            )

        def _move(self, delta: int) -> None:
            rule = self._current_rule() if self.base else None
            if rule is None:
                return
            nom, base = self.account_name, self.base
            self._mutate(
                lambda: rules_storage.move_rule(
                    nom, rule.id, delta, base=base
                ),
                rule.id,
            )

        def action_move_up(self) -> None:
            self._move(-1)

        def action_move_down(self) -> None:
            self._move(1)

        def action_toggle_stop(self) -> None:
            rule = self._current_rule() if self.base else None
            if rule is None:
                return
            nom, base, ident = self.account_name, self.base, rule.id

            def basculer() -> None:
                # Relue dans le fil : la copie de la table peut dater, et
                # `upsert_rule` garde l'armement du disque.
                for fraiche in rules_storage.load(nom, base=base):
                    if fraiche.id == ident:
                        fraiche.stop_after = not fraiche.stop_after
                        rules_storage.upsert_rule(nom, fraiche, base=base)
                        return

            self._mutate(basculer, ident)

        def action_delete_rule(self) -> None:
            rule = self._current_rule() if self.base else None
            if rule is None:
                return
            nom, base = self.account_name, self.base

            def confirme(accepte) -> None:
                if accepte:
                    self._mutate(
                        lambda: rules_storage.delete_rule(
                            nom, rule.id, base=base
                        )
                    )

            self.app.push_screen(
                ConfirmScreen(
                    f"{t('mail_rules_delete_confirm')} {rule.name or rule.id}"
                ),
                confirme,
            )

        def action_trial_rule(self) -> None:
            rule = self._current_rule() if self.base else None
            if rule is None:
                return
            self.app.push_screen(TrialScreen(self.session, self.base, rule))

        def action_show_journal(self) -> None:
            if self.base is None:
                return
            self.app.push_screen(
                RuleLogScreen(
                    self.session.store,
                    {rule.id: rule.name or rule.id for rule in self.rules},
                )
            )

        def on_button_pressed(self, event) -> None:
            if event.button.id != "caps_save":
                return
            try:
                caps = rules_storage.Caps(
                    per_pass=int(
                        self.query_one("#caps_per_pass", Input).value
                    ),
                    per_hour=int(
                        self.query_one("#caps_per_hour", Input).value
                    ),
                )
            except ValueError:
                self._status(f"{t('mail_rules_err_invalid')} caps", error=True)
                return
            nom, base = self.account_name, self.base
            self._mutate(
                lambda: rules_storage.save_caps(nom, caps, base=base),
                self._current_rule_id(),
                t("mail_rules_caps_saved"),
            )

        def action_close_rules(self) -> None:
            self.dismiss(None)

    class RuleLogScreen(ModalScreen):
        """Touche `l` de la liste des règles : les dernières lignes du
        journal, la plus récente d'abord.

        Issue et raison sont traduites ; expéditeur et sujet viennent des
        messages, donc de qui les a écrits, et passent en `Text`.
        """

        BINDINGS = [
            Binding("escape", "close_journal", t("mail_rules_close")),
        ]

        CSS = """
        #rules_log_table { height: 1fr; border: solid $panel; }
        #rules_log_status { height: auto; padding: 0 1; }
        """

        LIGNES = 200

        def __init__(self, store, names: dict):
            super().__init__()
            self.store = store
            self.names = names

        def compose(self):
            with Vertical():
                yield Static(t("mail_rules_journal"))
                yield DataTable(id="rules_log_table", cursor_type="row")
                yield Static("", id="rules_log_status")

        def on_mount(self) -> None:
            table = self.query_one("#rules_log_table", DataTable)
            table.add_columns(
                t("mail_rules_col_date"),
                t("mail_rules_col_name"),
                t("mail_rules_col_outcome"),
                t("mail_rules_col_reason"),
                t("mail_rules_col_sender"),
                t("mail_rules_col_subject"),
            )
            status = self.query_one("#rules_log_status", Static)
            try:
                lignes = self.store.rule_log_entries(None, self.LIGNES)
            except Exception as exc:
                status.update(Text(str(exc), style="bold red"))
                return
            for ligne in lignes:
                raison = ligne["reason"]
                table.add_row(
                    format_epoch(ligne["at"]),
                    Text(self.names.get(ligne["rule_id"], ligne["rule_id"])),
                    Text(t(f"mail_rules_outcome_{ligne['outcome']}")),
                    Text(t(f"mail_rules_reason_{raison}") if raison else ""),
                    Text(ligne["sender"] or ""),
                    Text(ligne["subject"] or ""),
                )
            if not lignes:
                status.update(t("mail_rules_log_empty"))
            table.focus()

        def action_close_journal(self) -> None:
            self.dismiss(None)

    class TrialScreen(ModalScreen):
        """Touche `s` de la liste des règles : ce que la règle ferait d'un
        message récent de la boîte de réception, sans rien écrire.

        La table liste les `TRIAL_MESSAGES` messages les plus récents
        d'INBOX en cache (clé = UID). Choisir une ligne lance
        `trial_simulation` dans un fil (en-têtes complets en ligne) ; le
        résultat (`rule_trial_lines`) s'affiche en `Text`. Une boîte de
        réception inconnue du cache, ou sans UIDVALIDITY, ne liste rien.

        `#trial_send` envoie la réponse simulée, ou le transfert ou la
        redirection d'une règle forward, à l'adresse du compte SEULEMENT
        (`engine.send_trial`, dans un fil) ; il reste grisé tant que rien
        n'est envoyable (`Simulation.sendable`), et pendant l'envoi.
        """

        BINDINGS = [
            Binding("escape", "close_trial", t("mail_rules_close")),
        ]

        CSS = """
        #trial_title { height: auto; padding: 0 1; text-style: bold; }
        #trial_pick { height: auto; padding: 0 1; color: $text-muted; }
        #trial_messages { height: 12; border: solid $panel; }
        #trial_scroll { height: 1fr; border: solid $panel; }
        #trial_result { height: auto; padding: 0 1; }
        #trial_status { height: auto; padding: 0 1; }
        #trial_send { width: auto; }
        """

        def __init__(self, session, base, rule):
            super().__init__()
            self.session = session
            self.base = base
            self.rule = copy.deepcopy(rule)
            self.folder = None
            self.uidvalidity = 0
            self.metas: dict = {}
            self.sim = None
            # Numéro de la dernière simulation demandée : un résultat plus
            # ancien, arrivé en retard, n'écrase pas le plus récent.
            self._generation = 0
            self._envoi = False

        def compose(self):
            with Vertical(id="trial_screen"):
                yield Static(
                    Text(
                        f"{t('mail_rules_trial_title')} "
                        f"{self.rule.name or self.rule.id}"
                    ),
                    id="trial_title",
                )
                yield Static(t("mail_rules_trial_pick"), id="trial_pick")
                yield DataTable(id="trial_messages", cursor_type="row")
                with VerticalScroll(id="trial_scroll"):
                    yield Static("", id="trial_result")
                yield Static("", id="trial_status")
                yield Button(
                    t("mail_rules_trial_send"), id="trial_send", disabled=True
                )

        def on_mount(self) -> None:
            table = self.query_one("#trial_messages", DataTable)
            table.add_columns(
                t("mail_rules_col_date"),
                t("mail_rules_col_sender"),
                t("mail_rules_col_subject"),
            )
            store = self.session.store
            inbox = rules_engine.find_inbox(store)
            etat = store.folder_state(inbox) if inbox else None
            if not etat or not etat.get("uidvalidity"):
                self._status(t("mail_rules_no_inbox"))
                return
            self.folder = inbox
            self.uidvalidity = int(etat["uidvalidity"])
            metas = store.list_messages(etat["id"], limit=TRIAL_MESSAGES)
            for meta in metas:
                cle = str(meta.uid)
                self.metas[cle] = meta
                # `Text` : expéditeur et sujet viennent de n'importe qui.
                table.add_row(
                    format_epoch(
                        getattr(meta, "received_at", 0) or meta.date or 0
                    ),
                    Text(meta.frm or ""),
                    Text(meta.subject or ""),
                    key=cle,
                )
            if not metas:
                self._status(t("mail_rules_trial_none"))
                return
            table.focus()

        def _status(self, text: str, *, error: bool = False) -> None:
            try:
                status = self.query_one("#trial_status", Static)
            except NoMatches:
                return
            status.update(Text(text, style="bold red" if error else ""))

        def on_data_table_row_selected(self, event) -> None:
            meta = self.metas.get(event.row_key.value)
            if meta is None:
                return
            self._generation += 1
            generation = self._generation
            self.sim = None
            self.query_one("#trial_send", Button).disabled = True
            self.query_one("#trial_result", Static).update(
                Text(t("mail_stats_computing"), style="dim")
            )
            self._status("")
            session, rule, base = self.session, self.rule, self.base
            folder, uidvalidity = self.folder, self.uidvalidity
            verrou = getattr(self.app, "_sync_lock", None)

            def travail() -> None:
                sim = trial_simulation(
                    session,
                    rule,
                    meta,
                    folder=folder,
                    uidvalidity=uidvalidity,
                    rules_base=base,
                    verrou=verrou,
                )
                self.app.call_from_thread(self._resultat, generation, sim)

            self.run_worker(travail, thread=True)

        def _resultat(self, generation: int, sim) -> None:
            if generation != self._generation:
                return
            self.sim = sim
            texte = Text()
            for ligne, style in rule_trial_lines(sim):
                texte.append(f"{ligne}\n", style=style or None)
            try:
                self.query_one("#trial_result", Static).update(texte)
                self.query_one("#trial_send", Button).disabled = (
                    not sim.sendable or self._envoi
                )
            except NoMatches:
                return

        def on_button_pressed(self, event) -> None:
            if event.button.id != "trial_send":
                return
            sim = self.sim
            if sim is None or not sim.sendable or self._envoi:
                return
            self._envoi = True
            event.button.disabled = True
            self._status("")
            session, rule = self.session, self.rule
            verrou = getattr(self.app, "_sync_lock", None)

            def travail() -> None:
                statut, erreur = "", ""
                try:
                    statut = rules_engine.send_trial(
                        session, rule, sim, verrou=verrou
                    )
                except Exception as exc:
                    erreur = str(exc) or type(exc).__name__
                self.app.call_from_thread(self._envoye, statut, erreur)

            self.run_worker(travail, thread=True)

        def _envoye(self, statut, erreur: str) -> None:
            self._envoi = False
            try:
                self.query_one("#trial_send", Button).disabled = (
                    self.sim is None or not self.sim.sendable
                )
            except NoMatches:
                return
            if erreur:
                self._status(erreur, error=True)
            else:
                self._status(f"{t('mail_rules_trial_sent')} {statut or ''}")

        def action_close_trial(self) -> None:
            self.dismiss(None)

    class RuleEditorScreen(ModalScreen):
        """Créer ou modifier une règle : limites, filtre, réponse.

        Le `Group` du modèle (`self.rule.filter`) est la SEULE source de
        vérité du filtre : chaque nœud de `#rule_filter` porte en `data`
        son chemin d'index (`()` = racine) ; après toute modification,
        l'arbre est reconstruit depuis le modèle et le curseur replacé par
        chemin. La cible des boutons est toujours `tree.cursor_node`.

        Le champ des minutes est grisé tant que la limite est décochée ;
        son état initial est posé à la composition, car `Checkbox`
        n'émet pas `Changed` pour sa valeur de départ. Décocher avec une
        valeur illisible y remet la dernière valeur valide : un champ grisé
        ne porte jamais une erreur que l'utilisateur ne peut plus corriger.

        `#rule_kind` choisit le type d'action parmi `reply`, `stats` et
        `forward` (un type inconnu, venu d'un fichier édité à la main,
        s'affiche grisé). Changer de type fait suivre la limite et le corps
        restés à la valeur par défaut de l'ancien type ; une règle NEUVE
        passée à `stats` prend le format des réglages du rapport ; passer à
        `forward` complète les options qui lui manquent. `#reply_form`
        ouvre `ForwardFormScreen` pour une règle forward,
        `ReplyFormScreen` sinon. Rien n'est perdu tant que l'éditeur reste
        ouvert : ce que le type ne lit pas n'est retiré qu'à
        l'enregistrement (`clean_action`).

        `ctrl+s` valide puis écrit dans un fil (`upsert_rule`) ; une erreur
        s'affiche dans `#rule_status` et l'écran reste ouvert. Pendant
        l'écriture, `#rule_form` est grisé : aucun sous-écran ne s'ouvre
        sur une règle déjà partie vers le disque, et aucune retouche ne
        s'y perd. Rend l'`id` de la règle enregistrée, ou None.
        """

        BINDINGS = [
            Binding("ctrl+s", "save_rule", t("mail_rules_save")),
            Binding("escape", "cancel_rule", t("mail_rules_cancel")),
        ]

        CSS = """
        #rule_form { height: 1fr; }
        #rule_title { height: auto; padding: 0 1; text-style: bold; }
        .rule_row { height: auto; }
        .rule_row Static { width: auto; padding: 1 1 0 1; }
        .rule_row Input { width: 14; }
        #rule_kind { width: 40; }
        #rule_filter { height: 12; border: solid $panel; }
        .filter_buttons { height: auto; }
        .filter_label { width: 24; padding: 1 1 0 1; }
        .filter_buttons Button { width: auto; }
        .filter_buttons Select { width: 28; }
        #filter_preview { height: auto; padding: 0 1; color: $text-muted; }
        #rule_status { height: auto; padding: 0 1; }
        #rule_buttons { height: auto; }
        #rule_buttons Button { width: auto; }
        """

        def __init__(self, session, base, rule, *, new: bool = False):
            super().__init__()
            self.session = session
            self.base = base
            self.new = new
            # Copie : annuler ne doit rien laisser dans la liste appelante.
            self.rule = copy.deepcopy(rule)
            # Une règle neuve compte comme « désactivée » : l'activer à
            # l'enregistrement l'arme sur l'UIDNEXT connu.
            self.was_enabled = bool(rule.enabled) and not new
            defaut = rules_model.KIND_DEFAULTS.get(
                rule.action.kind, rules_model.KIND_DEFAULTS["reply"]
            )["throttle_minutes"]
            self._minutes_valides = (
                rule.throttle_minutes
                if self._minutes_ok(rule.throttle_minutes)
                else defaut
            )
            self._enregistrement = False
            # `id` écrit pendant qu'un autre écran couvrait celui-ci : la
            # fermeture attend son retour au premier plan.
            self._enregistre = None
            self._focus_avant = None

        @staticmethod
        def _minutes_ok(value) -> bool:
            try:
                minutes = int(str(value).strip())
            except ValueError:
                return False
            return 1 <= minutes <= rules_model.THROTTLE_MINUTES_MAX

        @staticmethod
        def _options_groupe():
            return [
                (t(f"mail_rules_group_{op}"), op)
                for op in rules_model.GROUP_OPS
            ]

        # Types qu'on peut choisir ; un type inconnu s'ajoute, grisé, pour
        # rester affiché tel qu'il est.
        TYPES = ("reply", "stats", "forward")

        def _options_type(self):
            types = list(self.TYPES)
            if self.rule.action.kind not in types:
                types.append(self.rule.action.kind)
            return [(t(f"mail_rules_kind_{k}"), k) for k in types]

        def compose(self):
            rule = self.rule
            minutes = (
                rule.throttle_minutes
                if rule.throttle_enabled
                else self._minutes_valides
            )
            racine = (
                rule.filter.op
                if rule.filter.op in rules_model.GROUP_OPS
                else "all"
            )
            with VerticalScroll(id="rule_form"):
                yield Static(
                    t("mail_rules_new") if self.new else t("mail_rules_edit"),
                    id="rule_title",
                )
                with Horizontal(classes="rule_row"):
                    yield Static(t("mail_rules_kind"))
                    yield Select(
                        self._options_type(),
                        value=rule.action.kind,
                        allow_blank=False,
                        disabled=rule.action.kind not in self.TYPES,
                        id="rule_kind",
                    )
                yield Input(
                    value=rule.name,
                    placeholder=t("mail_rules_name"),
                    id="rule_name",
                )
                yield Checkbox(
                    t("mail_rules_enabled"), rule.enabled, id="rule_enabled"
                )
                yield Checkbox(
                    t("mail_rules_stop_after"),
                    rule.stop_after,
                    id="rule_stop",
                )
                with Horizontal(classes="rule_row"):
                    yield Checkbox(
                        t("mail_rules_throttle"),
                        rule.throttle_enabled,
                        id="rule_throttle",
                    )
                    yield Input(
                        value=str(minutes),
                        type="integer",
                        disabled=not rule.throttle_enabled,
                        id="rule_minutes",
                    )
                    yield Static(t("mail_rules_throttle_minutes"))
                with Horizontal(classes="rule_row"):
                    yield Static(t("mail_rules_max_age"))
                    yield Input(
                        value=str(rule.max_age_hours),
                        type="integer",
                        id="rule_max_age",
                    )
                with Horizontal(classes="rule_row"):
                    yield Static(t("mail_rules_hold_first"))
                    yield Input(
                        value=str(rule.hold_first),
                        type="integer",
                        id="rule_hold_first",
                    )
                yield Static(t("mail_rules_filter"))
                arbre = Tree(Text(""), data=(), id="rule_filter")
                arbre.auto_expand = False
                yield arbre
                with Horizontal(classes="filter_buttons"):
                    yield Static(
                        t("mail_rules_new_group_op"), classes="filter_label"
                    )
                    yield Select(
                        self._options_groupe(),
                        value="all",
                        allow_blank=False,
                        id="new_group_op",
                    )
                    yield Button(
                        t("mail_rules_add_condition"), id="add_condition"
                    )
                    yield Button(t("mail_rules_add_group"), id="add_group")
                with Horizontal(classes="filter_buttons"):
                    yield Static(
                        t("mail_rules_group_op"), classes="filter_label"
                    )
                    yield Select(
                        self._options_groupe(),
                        value=racine,
                        allow_blank=False,
                        id="group_op",
                    )
                    yield Button(t("mail_rules_edit_node"), id="edit_node")
                    yield Button(t("mail_rules_delete_node"), id="delete_node")
                yield Static("", id="filter_preview")
                yield Button(
                    t(self._cle_bouton_reponse(rule.action.kind)),
                    id="reply_form",
                )
                yield Static("", id="rule_status")
                with Horizontal(id="rule_buttons"):
                    yield Button(
                        t("mail_rules_save"), id="rule_save", variant="primary"
                    )
                    yield Button(t("mail_rules_cancel"), id="rule_cancel")

        def on_mount(self) -> None:
            self._rebuild_tree(())
            self._refresh_preview()
            self.query_one("#rule_name", Input).focus()

        # -- Filtre ---------------------------------------------------

        def _node_at(self, path):
            node = self.rule.filter
            for index in path:
                node = node.children[index]
            return node

        def _target_path(self) -> tuple:
            """Le chemin du nœud sous le curseur ; la racine à défaut."""
            node = self.query_one("#rule_filter", Tree).cursor_node
            path = getattr(node, "data", None)
            if not isinstance(path, tuple):
                return ()
            try:
                self._node_at(path)
            except (IndexError, AttributeError):
                return ()
            return path

        def _target_group_path(self) -> tuple:
            """Le groupe où ajouter : le nœud visé s'il est un groupe,
            sinon le groupe qui contient la condition visée."""
            path = self._target_path()
            if isinstance(self._node_at(path), rules_model.Group):
                return path
            return path[:-1]

        def _root_label(self) -> str:
            racine = self.rule.filter
            if not racine.children and racine.op == "all":
                return t("mail_rules_match_all")
            return rule_node_label(racine)

        def _ajouter_enfants(self, tree_node, group, path) -> None:
            for index, child in enumerate(group.children):
                child_path = path + (index,)
                # `Text` : la valeur d'une condition est saisie par
                # l'utilisateur, « [x] y » doit s'afficher crochets compris.
                label = Text(rule_node_label(child))
                if isinstance(child, rules_model.Group):
                    branche = tree_node.add(
                        label, data=child_path, expand=True
                    )
                    self._ajouter_enfants(branche, child, child_path)
                else:
                    tree_node.add_leaf(label, data=child_path)

        def _rebuild_tree(self, cursor_path) -> None:
            """Reconstruit l'arbre depuis le modèle, curseur sur
            `cursor_path` (sur la racine s'il n'existe plus)."""
            tree = self.query_one("#rule_filter", Tree)
            tree.clear()
            tree.root.data = ()
            tree.root.set_label(Text(self._root_label()))
            self._ajouter_enfants(tree.root, self.rule.filter, ())
            tree.root.expand()
            cible, ligne = tree.root, 0
            while True:
                node = tree.get_node_at_line(ligne)
                if node is None:
                    break
                if node.data == tuple(cursor_path):
                    cible = node
                    break
                ligne += 1
            tree.move_cursor(cible)
            self._sync_controls()

        def _sync_controls(self) -> None:
            """Accorde boutons et `#group_op` au nœud sous le curseur."""
            path = self._target_path()
            node = self._node_at(path)
            groupe = self._node_at(self._target_group_path())
            plein = groupe.op == "not" and len(groupe.children) >= 1
            self.query_one("#add_condition", Button).disabled = plein
            self.query_one("#add_group", Button).disabled = plein
            self.query_one("#edit_node", Button).disabled = not isinstance(
                node, rules_model.Condition
            )
            selecteur = self.query_one("#group_op", Select)
            if groupe.op in rules_model.GROUP_OPS:
                # Sans `prevent`, le `Changed` de cette affectation
                # arriverait après le déplacement du curseur et écrirait
                # l'op sur le nœud suivant.
                with selecteur.prevent(Select.Changed):
                    selecteur.value = groupe.op
            selecteur.disabled = not isinstance(node, rules_model.Group)

        def on_tree_node_highlighted(self, event) -> None:
            self._sync_controls()

        def _after_tree_change(self, cursor_path) -> None:
            self._rebuild_tree(cursor_path)
            self._refresh_preview()

        def _refresh_preview(self) -> None:
            """Recalculé après chaque modification de l'arbre, jamais à la
            frappe : l'évaluation lit 200 messages du cache."""
            apercu = self.query_one("#filter_preview", Static)
            try:
                texte = rules_filter_preview(
                    self.session.store, self.rule.filter
                )
            except Exception as exc:
                texte = f"{t('mail_rules_preview')} : {exc}"
            apercu.update(Text(texte))

        def _insert(self, group_path, node) -> None:
            if node is None:
                return
            groupe = self._node_at(group_path)
            if groupe.op == "not" and groupe.children:
                self._rule_status(t("mail_rules_err_not_one_child"))
                return
            groupe.children.append(node)
            self._after_tree_change(
                tuple(group_path) + (len(groupe.children) - 1,)
            )

        def _replace(self, path, node) -> None:
            if node is None:
                return
            if not path:
                return
            self._node_at(path[:-1]).children[path[-1]] = node
            self._after_tree_change(path)

        def _delete_target(self) -> None:
            path = self._target_path()
            if not path:
                self.rule.filter.children = []
                self._after_tree_change(())
                return
            del self._node_at(path[:-1]).children[path[-1]]
            self._after_tree_change(path[:-1])

        @staticmethod
        def _cle_bouton_reponse(kind: str) -> str:
            if kind == "stats":
                return "mail_rules_action_stats"
            if kind == "forward":
                return "mail_rules_action_forward"
            return "mail_rules_action_reply"

        def _changer_type(self, nouveau) -> None:
            """Passe la règle au type `nouveau`.

            La limite affichée, si elle vaut le défaut de l'ancien type,
            prend celui du nouveau ; un corps resté au corps par défaut de
            l'ancien type prend celui du nouveau, un corps écrit à la main
            est gardé. Une règle NEUVE passée à `stats` prend le format des
            réglages du rapport, et le corps par défaut si le sien est vide.
            Passer à `forward` pose les options par défaut qui manquent ;
            celles déjà présentes sont gardées.
            """
            action = self.rule.action
            ancien = action.kind
            if nouveau == ancien or nouveau not in self.TYPES:
                return
            defaut_ancien = rules_model.KIND_DEFAULTS[ancien]
            defaut_nouveau = rules_model.KIND_DEFAULTS[nouveau]
            champ = self.query_one("#rule_minutes", Input)
            if champ.value.strip() == str(defaut_ancien["throttle_minutes"]):
                champ.value = str(defaut_nouveau["throttle_minutes"])
                self._minutes_valides = defaut_nouveau["throttle_minutes"]
            case = self.query_one("#rule_throttle", Checkbox)
            if case.value == defaut_ancien["throttle_enabled"]:
                case.value = defaut_nouveau["throttle_enabled"]
            if action.body == rules_model.new_rule(ancien).action.body:
                action.body = rules_model.new_rule(nouveau).action.body
            if self.new and nouveau == "stats":
                try:
                    action.format = rules_storage.load_report(
                        self.session.account.name, base=self.base
                    ).format
                except rules_model.RuleError:
                    pass
                if not action.body:
                    action.body = t("mail_stats_default_body")
            if nouveau == "forward":
                for cle, valeur in rules_model.forward_defaults().items():
                    action.options.setdefault(cle, valeur)
            action.kind = nouveau
            self.query_one("#reply_form", Button).label = t(
                self._cle_bouton_reponse(nouveau)
            )

        def on_select_changed(self, event) -> None:
            if event.select.id == "rule_kind":
                self._changer_type(event.value)
                return
            if event.select.id != "group_op":
                return
            path = self._target_path()
            node = self._node_at(path)
            if not isinstance(node, rules_model.Group):
                return
            valeur = event.value
            if valeur not in rules_model.GROUP_OPS or valeur == node.op:
                return
            if valeur == "not" and len(node.children) > 1:
                self._rule_status(t("mail_rules_err_not_one_child"))
                with event.select.prevent(Select.Changed):
                    event.select.value = node.op
                return
            node.op = valeur
            self._rule_status("")
            self._after_tree_change(path)

        def on_button_pressed(self, event) -> None:
            # Le grisé de `#rule_form` arrête la souris et le clavier, pas
            # un `Button.press()` : la garde vaut pour tous les chemins.
            if self._enregistrement:
                return
            ident = event.button.id
            if ident == "add_condition":
                group_path = self._target_group_path()
                self.app.push_screen(
                    ConditionScreen(),
                    lambda cond: self._insert(group_path, cond),
                )
            elif ident == "add_group":
                op = self.query_one("#new_group_op", Select).value
                self._insert(
                    self._target_group_path(), rules_model.Group(op=op)
                )
            elif ident == "edit_node":
                path = self._target_path()
                node = self._node_at(path)
                if isinstance(node, rules_model.Condition):
                    self.app.push_screen(
                        ConditionScreen(copy.deepcopy(node)),
                        lambda cond: self._replace(path, cond),
                    )
            elif ident == "delete_node":
                self._delete_target()
            elif ident == "reply_form":
                formulaire = (
                    ForwardFormScreen
                    if self.rule.action.kind == "forward"
                    else ReplyFormScreen
                )
                self.app.push_screen(
                    formulaire(self.session, self.base, self.rule.action),
                    self._apres_reponse,
                )
            elif ident == "rule_save":
                self.action_save_rule()
            elif ident == "rule_cancel":
                self.action_cancel_rule()

        def _apres_reponse(self, action) -> None:
            if action is not None:
                self.rule.action = action

        # -- Limites --------------------------------------------------

        def on_checkbox_changed(self, event) -> None:
            if event.checkbox.id != "rule_throttle":
                return
            champ = self.query_one("#rule_minutes", Input)
            if not event.value and not self._minutes_ok(champ.value):
                champ.value = str(self._minutes_valides)
            champ.disabled = not event.value

        def on_input_changed(self, event) -> None:
            if event.input.id == "rule_minutes" and self._minutes_ok(
                event.value
            ):
                self._minutes_valides = int(event.value.strip())

        def _entier(self, selector: str, cle: str) -> int:
            try:
                return int(self.query_one(selector, Input).value.strip())
            except ValueError:
                raise rules_model.RuleError(t(cle)) from None

        def _rule_status(self, text: str) -> None:
            self.query_one("#rule_status", Static).update(
                Text(text, style="bold red")
            )

        # -- Enregistrer ----------------------------------------------

        def action_save_rule(self) -> None:
            if self._enregistrement:
                return
            try:
                rule = dataclasses.replace(
                    self.rule,
                    name=self.query_one("#rule_name", Input).value.strip(),
                    enabled=self.query_one("#rule_enabled", Checkbox).value,
                    stop_after=self.query_one("#rule_stop", Checkbox).value,
                    throttle_enabled=self.query_one(
                        "#rule_throttle", Checkbox
                    ).value,
                    throttle_minutes=self._entier(
                        "#rule_minutes", "mail_rules_err_minutes"
                    ),
                    max_age_hours=self._entier(
                        "#rule_max_age", "mail_rules_err_max_age"
                    ),
                    hold_first=self._entier(
                        "#rule_hold_first", "mail_rules_err_hold_first"
                    ),
                    action=rules_model.clean_action(self.rule.action),
                )
                rules_model.validate(rule)
            except rules_model.RuleError as exc:
                self._rule_status(str(exc))
                return
            # Faux → vrai (ou règle neuve active) : armée sur l'UIDNEXT
            # connu, sinon à la passe suivante. Sinon `upsert_rule` garde
            # l'armement du disque, que le moteur a pu poser entre-temps.
            rearm = None
            if rule.enabled and not self.was_enabled:
                rearm = rules_arm_point(self.session.store)
            self._enregistrement = True
            self._rule_status("")
            self._focus_avant = self.focused
            self.query_one("#rule_form").disabled = True
            nom, base = self.session.account.name, self.base

            def travail() -> None:
                try:
                    rules_storage.upsert_rule(
                        nom, rule, rearm=rearm, base=base
                    )
                except Exception as exc:
                    self.app.call_from_thread(self._echec, exc)
                    return
                self.app.call_from_thread(self._enregistree, rule.id)

            self.run_worker(travail, thread=True)

        def _echec(self, exc) -> None:
            self._enregistrement = False
            try:
                self.query_one("#rule_form").disabled = False
                self._rule_status(str(exc) or type(exc).__name__)
            except NoMatches:
                return
            focus = self._focus_avant
            if focus is not None and focus.is_attached:
                focus.focus()

        def _enregistree(self, rule_id: str) -> None:
            if self.app.screen is self:
                self.dismiss(rule_id)
            else:
                self._enregistre = rule_id

        def on_screen_resume(self) -> None:
            # Écriture finie sous un autre écran : sans cette fermeture,
            # `_enregistrement` resterait vrai et l'écran ignorerait
            # `escape` comme `ctrl+s` pour toujours.
            if self._enregistre is not None:
                self.dismiss(self._enregistre)

        def action_cancel_rule(self) -> None:
            # Pendant l'écriture, fermer laisserait croire à une annulation
            # alors que la règle est peut-être déjà sur le disque.
            if self._enregistrement:
                return
            self.dismiss(None)

    class ConditionScreen(ModalScreen):
        """Une condition du filtre : champ, comparaison, valeur, mode.

        `ctrl+s` la valide SEULE (`validate_node`) avant de la rendre : un
        glob sur le sujet ou une expression régulière refusée restent à
        l'écran, l'erreur dans `#cond_status`. Le mode est grisé pour un
        motif glob, qui l'ignore. Rend la `Condition`, ou None.
        """

        BINDINGS = [
            Binding("ctrl+s", "save_condition", t("mail_rules_save")),
            Binding("escape", "cancel_condition", t("mail_rules_cancel")),
        ]

        CSS = """
        #cond_form { height: auto; padding: 1; }
        #cond_status { height: auto; padding: 0 1; }
        #cond_buttons { height: auto; }
        #cond_buttons Button { width: auto; }
        """

        def __init__(self, condition=None):
            super().__init__()
            self.condition = condition or rules_model.Condition(
                field="from", value=""
            )

        @staticmethod
        def _valeur_sure(valeur, permises, defaut):
            return valeur if valeur in permises else defaut

        def compose(self):
            cond = self.condition
            with Vertical(id="cond_form"):
                yield Select(
                    [
                        (t(f"mail_rules_field_{f}"), f)
                        for f in rules_model.FIELDS
                    ],
                    value=self._valeur_sure(
                        cond.field, rules_model.FIELDS, "from"
                    ),
                    allow_blank=False,
                    id="cond_field",
                )
                yield Select(
                    [(t(f"mail_rules_op_{o}"), o) for o in rules_model.OPS],
                    value=self._valeur_sure(
                        cond.op, rules_model.OPS, "contains"
                    ),
                    allow_blank=False,
                    id="cond_op",
                )
                yield Input(value=cond.value, id="cond_value")
                yield Select(
                    [
                        (t(f"mail_rules_mode_{m}"), m)
                        for m in rules_model.MODES
                    ],
                    value=self._valeur_sure(
                        cond.mode, rules_model.MODES, "substring_ci"
                    ),
                    allow_blank=False,
                    disabled=cond.op == "glob",
                    id="cond_mode",
                )
                yield Static("", id="cond_status")
                with Horizontal(id="cond_buttons"):
                    yield Button(
                        t("mail_rules_save"), id="cond_save", variant="primary"
                    )
                    yield Button(t("mail_rules_cancel"), id="cond_cancel")

        def on_mount(self) -> None:
            self.query_one("#cond_value", Input).focus()

        def on_select_changed(self, event) -> None:
            if event.select.id == "cond_op":
                self.query_one("#cond_mode", Select).disabled = (
                    event.value == "glob"
                )

        def on_button_pressed(self, event) -> None:
            if event.button.id == "cond_save":
                self.action_save_condition()
            elif event.button.id == "cond_cancel":
                self.action_cancel_condition()

        def action_save_condition(self) -> None:
            cond = rules_model.Condition(
                field=self.query_one("#cond_field", Select).value,
                value=self.query_one("#cond_value", Input).value,
                op=self.query_one("#cond_op", Select).value,
                mode=self.query_one("#cond_mode", Select).value,
            )
            try:
                rules_model.validate_node(cond)
            except rules_model.RuleError as exc:
                self.query_one("#cond_status", Static).update(
                    Text(str(exc), style="bold red")
                )
                return
            self.dismiss(cond)

        def action_cancel_condition(self) -> None:
            self.dismiss(None)

    class ReplyFormScreen(ModalScreen):
        """La réponse personnalisée d'une règle : format, sujet, corps,
        images, et l'aperçu de ce qui partira.

        Trois formats (`markdown`, `html`, `text`). Les images sont copiées
        dans le dossier des médias du compte par `#add_images` (fil de
        travail) ; la liste montre le nom STOCKÉ, que l'import peut avoir
        renommé, et le rôle que lui donne `render_reply` : en ligne si le
        corps HTML la cite par ce nom, pièce jointe sinon. `#browse_image`
        ne fait qu'ajouter un chemin au champ. Rend une `Action`, ou None.

        `ctrl+s` refuse, motif dans `#reply_status`, un gabarit fautif
        (`template_fault`), une réponse que `render_reply` ne sait pas
        construire (image absente, modifiée, trop lourde) et un champ de
        chemins encore rempli : une règle enregistrée telle quelle
        échouerait à chaque message, ou perdrait en silence l'image
        choisie mais jamais ajoutée.

        Pour une règle `stats`, le corps est un gabarit : `#stats_vars`
        liste les variables, `#stats_var_insert` insère celle de
        `#stats_var_pick` au curseur du corps. L'aperçu rend le gabarit
        sur les vraies statistiques de la boîte, sans demandeur ; ces
        données se calculent une fois, dans un fil, à l'ouverture.
        """

        BINDINGS = [
            Binding("ctrl+s", "save_reply", t("mail_rules_save")),
            Binding("escape", "cancel_reply", t("mail_rules_cancel")),
        ]

        CSS = """
        #reply_scroll { height: 1fr; }
        #reply_body { height: 10; }
        #image_row { height: auto; }
        #image_row Input { width: 1fr; }
        #image_row Button { width: auto; }
        #reply_images { height: auto; }
        .reply_image_row { height: auto; }
        .reply_image_row Static { width: 1fr; padding: 1 1 0 1; }
        .reply_image_row Button { width: auto; }
        #stats_vars { height: auto; padding: 0 1; color: $text-muted; }
        #stats_var_row { height: auto; }
        #stats_var_row Select { width: 40; }
        #stats_var_row Button { width: auto; }
        #stats_preview_note { height: auto; padding: 0 1; color: $text-muted; }
        #reply_preview { height: auto; padding: 0 1; border: solid $panel; }
        #reply_status { height: auto; padding: 0 1; }
        #reply_buttons { height: auto; }
        #reply_buttons Button { width: auto; }
        """

        def __init__(self, session, base, action):
            super().__init__()
            self.session = session
            self.base = base
            self.action = copy.deepcopy(action)
            # Octets des images déjà lus, par nom stocké.
            self._media: dict = {}
            # Erreurs de la dernière lecture des images : la vraie cause,
            # que `render_reply` réduirait à « introuvable ».
            self._erreurs_media: list = []
            self._import_en_cours = False
            self._stats = self.action.kind == "stats"
            # Données du rapport pour l'aperçu d'une règle stats : None tant
            # que le fil ne les a pas rendues ; `_erreur_donnees` dit
            # pourquoi elles manquent.
            self._donnees = None
            self._erreur_donnees = ""

        def compose(self):
            action = self.action
            with VerticalScroll(id="reply_scroll"):
                yield Static(
                    t(
                        "mail_rules_action_stats"
                        if self._stats
                        else "mail_rules_action_reply"
                    ),
                    id="reply_title",
                )
                yield Static(t("mail_rules_format"))
                yield Select(
                    [
                        (t(f"mail_rules_format_{f}"), f)
                        for f in rules_model.FORMATS
                    ],
                    value=(
                        action.format
                        if action.format in rules_model.FORMATS
                        else "markdown"
                    ),
                    allow_blank=False,
                    id="reply_format",
                )
                yield Static(t("mail_rules_subject"))
                yield Input(
                    value=action.subject,
                    placeholder="Auto: {subject}",
                    id="reply_subject",
                )
                yield Static(t("mail_rules_body"))
                yield TextArea(action.body, id="reply_body")
                if self._stats:
                    yield Static(self._texte_variables(), id="stats_vars")
                    with Horizontal(id="stats_var_row"):
                        yield Select(
                            [
                                ("{{" + nom + "}}", nom)
                                for nom in rules_model.STATS_VARIABLES
                            ],
                            value=rules_model.STATS_VARIABLES[0],
                            allow_blank=False,
                            id="stats_var_pick",
                        )
                        yield Button(
                            t("mail_rules_stats_insert"),
                            id="stats_var_insert",
                        )
                yield Static(t("mail_rules_images"))
                with Horizontal(id="image_row"):
                    yield Input(
                        placeholder=t("mail_rules_image_paths"),
                        id="image_paths",
                    )
                    yield Button(t("mail_rules_browse"), id="browse_image")
                    yield Button(t("mail_rules_add_images"), id="add_images")
                yield Vertical(id="reply_images")
                yield Static(t("mail_rules_preview"))
                if self._stats:
                    yield Static(
                        t("mail_rules_stats_preview_note"),
                        id="stats_preview_note",
                    )
                yield Static("", id="reply_preview")
                yield Static("", id="reply_status")
                with Horizontal(id="reply_buttons"):
                    yield Button(
                        t("mail_rules_save"),
                        id="reply_save",
                        variant="primary",
                    )
                    yield Button(t("mail_rules_cancel"), id="reply_cancel")

        def on_mount(self) -> None:
            self._refresh_images()
            if self._stats:
                self.run_worker(self._calculer_donnees, thread=True)

        @staticmethod
        def _texte_variables() -> "Text":
            lignes = [t("mail_rules_stats_variables")]
            lignes.extend(
                "{{" + nom + "}} — " + t(f"mail_stats_var_{nom}")
                for nom in rules_model.STATS_VARIABLES
            )
            return Text("\n".join(lignes))

        def _calculer_donnees(self) -> None:
            """Les statistiques de la boîte, sans demandeur, pour l'aperçu.

            Les réglages viennent du rapport du compte (défauts s'ils sont
            illisibles) ; le calcul est direct, sans instantané.
            """
            nom, base = self.session.account.name, self.base
            try:
                try:
                    reglages = rules_storage.load_report(nom, base=base)
                except rules_model.RuleError:
                    reglages = rules_storage.ReportSettings()
                donnees = rules_report.build_data(
                    self.session.store,
                    reglages,
                    now=int(time.time()),
                    sender=None,
                )
            except Exception as exc:
                self.app.call_from_thread(
                    self._donnees_pretes, None, str(exc) or type(exc).__name__
                )
                return
            self.app.call_from_thread(self._donnees_pretes, donnees, "")

        def _donnees_pretes(self, donnees, erreur: str) -> None:
            self._donnees = donnees
            self._erreur_donnees = erreur
            try:
                self._refresh_preview()
            except NoMatches:
                return

        def _current_action(self):
            return rules_model.Action(
                kind=self.action.kind,
                format=self.query_one("#reply_format", Select).value,
                subject=self.query_one("#reply_subject", Input).value,
                body=self.query_one("#reply_body", TextArea).text,
                images=list(self.action.images),
                options=dict(self.action.options),
            )

        def _load_media(self) -> list:
            """Lit les images pas encore lues ; rend les erreurs, aussi
            gardées dans `_erreurs_media` pour les aperçus suivants."""
            erreurs = []
            nom = self.session.account.name
            for ref in self.action.images:
                if ref.file in self._media:
                    continue
                try:
                    self._media[ref.file] = rules_storage.read_media(
                        nom, ref, base=self.base
                    )
                except Exception as exc:
                    erreurs.append(str(exc))
            self._erreurs_media = erreurs
            return erreurs

        def _rendre_reponse(self):
            """La réponse rendue. Règle `stats` : gabarit contrôlé d'abord
            (`TemplateError`), puis rendu sur les données du rapport ; tant
            qu'elles manquent, le corps est rendu sans substitution, ce qui
            suffit aux rôles des images."""
            from script.todo.mail.rules.markup import render_reply

            action = self._current_action()
            domaine = self.session.account.email.rpartition("@")[2]
            if self._stats:
                faute = rules_model.template_fault(action)
                if faute is not None:
                    raise rules_model.TemplateError(faute)
                if self._donnees is not None:
                    return rules_report.render_stats_reply(
                        action, self._media, domaine, self._donnees
                    )
            return render_reply(action, self._media, domaine)

        def _roles(self, rendu) -> dict:
            """Rôle de chaque image : « pièce jointe » si elle part jointe,
            « en ligne » sinon (citée, ou de même contenu qu'une citée)."""
            jointes = {part.filename for part in rendu.attachments}
            return {
                ref.file: t(
                    "mail_rules_image_attached"
                    if ref.file in jointes
                    else "mail_rules_image_inline"
                )
                for ref in self.action.images
            }

        def _refresh_images(self) -> None:
            """Reconstruit l'aperçu, puis la liste des images.

            Chaque libellé naît avec son rôle : `mount` n'attend pas, et
            les lignes neuves n'existent pas encore quand l'aperçu cherche
            les libellés à mettre à jour.
            """
            self._load_media()
            roles = self._refresh_preview()
            zone = self.query_one("#reply_images", Vertical)
            zone.remove_children()
            for index, ref in enumerate(self.action.images):
                ligne = Horizontal(classes="reply_image_row")
                ligne.compose_add_child(
                    Static(
                        Text(self._libelle(ref.file, roles)),
                        classes="reply_image_label",
                        name=ref.file,
                    )
                )
                # Sans `id` : la liste est remontée à chaque changement, et
                # deux boutons de même `id` se croiseraient le temps du
                # retrait. L'index voyage dans `name`.
                ligne.compose_add_child(
                    Button(
                        t("mail_rules_remove_image"),
                        name=str(index),
                        classes="remove_image",
                    )
                )
                zone.mount(ligne)

        @staticmethod
        def _libelle(nom: str, roles: dict) -> str:
            role = roles.get(nom, "")
            return f"{nom} — {role}" if role else nom

        def _refresh_preview(self) -> dict:
            """Met à jour l'aperçu et les libellés montés ; rend le rôle de
            chaque image, vide si la réponse ne se construit pas.

            Une erreur de lecture d'image passe AVANT celle du rendu, qui
            n'en est que la conséquence.
            """
            apercu = self.query_one("#reply_preview", Static)
            erreurs = self._erreurs_media
            try:
                rendu = self._rendre_reponse()
            except Exception as exc:
                apercu.update(
                    Text("\n".join(erreurs) or str(exc), style="bold red")
                )
                return {}
            roles = self._roles(rendu)
            for label in self.query(".reply_image_label").results(Static):
                label.update(Text(self._libelle(label.name or "", roles)))
            if self._stats and self._donnees is None:
                texte = Text(
                    self._erreur_donnees or t("mail_stats_computing"),
                    style="bold red" if self._erreur_donnees else "dim",
                )
            else:
                texte = Text(rendu.text)
            for ref in self.action.images:
                texte.append(
                    f"\n{self._libelle(ref.file, roles)}", style="dim"
                )
            for erreur in erreurs:
                texte.append(f"\n{erreur}", style="bold red")
            apercu.update(texte)
            return roles

        def on_select_changed(self, event) -> None:
            if event.select.id == "reply_format":
                self._refresh_preview()

        def on_text_area_changed(self, event) -> None:
            self._refresh_preview()

        def on_button_pressed(self, event) -> None:
            bouton = event.button
            if bouton.has_class("remove_image"):
                index = int(bouton.name or -1)
                if 0 <= index < len(self.action.images):
                    del self.action.images[index]
                    self._refresh_images()
            elif bouton.id == "browse_image":
                self._browse_image()
            elif bouton.id == "stats_var_insert":
                self._inserer_variable()
            elif bouton.id == "add_images":
                self._add_images()
            elif bouton.id == "reply_save":
                self.action_save_reply()
            elif bouton.id == "reply_cancel":
                self.action_cancel_reply()

        def _status(self, text: str) -> None:
            self.query_one("#reply_status", Static).update(
                Text(text, style="bold red")
            )

        def _inserer_variable(self) -> None:
            """Insère « {{nom}} » de `#stats_var_pick` au curseur du corps."""
            nom = self.query_one("#stats_var_pick", Select).value
            if nom not in rules_model.STATS_VARIABLES:
                return
            corps = self.query_one("#reply_body", TextArea)
            corps.insert("{{" + nom + "}}")
            corps.focus()

        def _browse_image(self) -> None:
            champ = self.query_one("#image_paths", Input)
            try:
                chemin = browse_one_path(
                    self.app, browse_start_dir(champ.value)
                )
            except Exception as exc:
                self._status(f"{t('mail_browse_failed')} {exc}")
                return
            if chemin:
                champ.value = append_attachment_path(champ.value, chemin)

        def _add_images(self) -> None:
            """Copie chaque chemin du champ dans les médias du compte, dans
            un fil ; les chemins refusés restent dans le champ."""
            import os
            from pathlib import Path

            chemins = parse_paths(self.query_one("#image_paths", Input).value)
            if not chemins or self._import_en_cours:
                return
            self._import_en_cours = True
            nom, base = self.session.account.name, self.base

            def travail() -> None:
                refs, fautes, restes = [], [], []
                for chemin in chemins:
                    try:
                        refs.append(
                            rules_storage.import_media(
                                nom,
                                Path(os.path.expanduser(chemin)),
                                base=base,
                            )
                        )
                    except Exception as exc:
                        fautes.append(str(exc) or type(exc).__name__)
                        restes.append(chemin)
                self.app.call_from_thread(
                    self._images_ajoutees, refs, fautes, restes
                )

            self.run_worker(travail, thread=True)

        def _images_ajoutees(self, refs, fautes, restes) -> None:
            self._import_en_cours = False
            for ref in refs:
                # Même nom stocké : même fichier, empreinte peut-être
                # renouvelée ; la référence est remplacée, pas doublée.
                self.action.images = [
                    r for r in self.action.images if r.file != ref.file
                ]
                self.action.images.append(ref)
                self._media.pop(ref.file, None)
            try:
                self.query_one("#image_paths", Input).value = "; ".join(restes)
            except NoMatches:
                return
            self._status("\n".join(fautes))
            self._refresh_images()

        def action_save_reply(self) -> None:
            if self._import_en_cours:
                return
            if self.query_one("#image_paths", Input).value.strip():
                self._status(t("mail_rules_err_images_pending"))
                return
            faute = rules_model.template_fault(self._current_action())
            if faute is not None:
                self._status(faute)
                return
            # Toutes relues : une image a pu changer sur le disque depuis
            # sa première lecture, et l'empreinte se vérifie à la lecture.
            self._media.clear()
            erreurs = self._load_media()
            try:
                self._rendre_reponse()
            except Exception as exc:
                self._status("\n".join(erreurs) or str(exc))
                self._refresh_preview()
                return
            self.dismiss(self._current_action())

        def action_cancel_reply(self) -> None:
            if self._import_en_cours:
                return
            self.dismiss(None)

    class ForwardFormScreen(ModalScreen):
        """La redirection d'une règle : mode, destinations, texte
        d'introduction, et la case « Ignorer listes et robots ».

        Chaque destination passe à l'ajout par
        `check_forward_target` des garde-fous (syntaxe, adresse de ce compte ou
        d'un autre compte configuré, doublon, plafond), chaque refus avec
        son motif dans `#fwd_status`, le champ gardé ; acceptée, elle est
        listée dans sa forme d'envoi. L'avertissement SPF/DMARC n'est
        affiché qu'en vraie redirection, où l'introduction, que ce mode
        n'envoie pas, est grisée sans être effacée.

        `ctrl+s` refuse une adresse saisie mais pas ajoutée, puis contrôle
        l'action par `model.validate` sur une règle neutre ; une erreur
        laisse l'écran ouvert. Les options lues sont FUSIONNÉES dans celles
        de l'action : une clé que ce formulaire ne connaît pas est gardée.
        Rien n'est écrit sur le disque : l'éditeur de règle enregistre.
        Rend une `Action` (copie modifiée), ou None.
        """

        BINDINGS = [
            Binding("ctrl+s", "save_forward", t("mail_rules_save")),
            Binding("escape", "cancel_forward", t("mail_rules_cancel")),
        ]

        CSS = """
        #fwd_scroll { height: 1fr; }
        #fwd_title { height: auto; padding: 0 1; text-style: bold; }
        #fwd_mode { width: 50; }
        #fwd_redirect_warning { height: auto; padding: 0 1; }
        #fwd_targets { height: auto; }
        .fwd_target_item { height: auto; }
        .fwd_target_item Static { width: 1fr; padding: 1 1 0 1; }
        .fwd_target_item Button { width: auto; }
        #fwd_target_entry { height: auto; }
        #fwd_target_entry Input { width: 1fr; }
        #fwd_target_entry Button { width: auto; }
        #fwd_intro { height: 8; }
        #fwd_status { height: auto; padding: 0 1; }
        #fwd_buttons { height: auto; }
        #fwd_buttons Button { width: auto; }
        """

        def __init__(self, session, base, action):
            super().__init__()
            self.session = session
            self.base = base
            self.action = copy.deepcopy(action)
            self.own = rules_engine.account_addresses(session.account)
            try:
                self.others = rules_engine.other_account_addresses(
                    session.account
                )
            except Exception:
                self.others = frozenset()
            # Options illisibles (fichier édité à la main) : relues au plus
            # près, l'erreur montrée à l'ouverture ; l'enregistrement les
            # contrôle de nouveau.
            self._erreur_options = ""
            try:
                opts = rules_model.forward_options(self.action)
                cibles = list(opts.targets)
                mode, ignorer = opts.mode, opts.skip_lists
            except rules_model.RuleError as exc:
                self._erreur_options = str(exc)
                brutes = self.action.options or {}
                lues = brutes.get("targets")
                cibles = [
                    c
                    for c in (lues if isinstance(lues, list) else [])
                    if isinstance(c, str)
                ]
                mode = brutes.get("mode")
                ignorer = brutes.get("skip_lists") is True
            if mode not in rules_model.FORWARD_MODES:
                mode = "inline"
            self.targets: list = cibles
            self._mode_initial = mode
            self._ignorer_initial = bool(ignorer)

        def compose(self):
            with VerticalScroll(id="fwd_scroll"):
                yield Static(t("mail_rules_action_forward"), id="fwd_title")
                yield Static(t("mail_rules_fwd_mode"))
                yield Select(
                    [
                        (t(f"mail_rules_fwd_mode_{m}"), m)
                        for m in rules_model.FORWARD_MODES
                    ],
                    value=self._mode_initial,
                    allow_blank=False,
                    id="fwd_mode",
                )
                yield Static(
                    Text(
                        t("mail_rules_fwd_redirect_warning"),
                        style="bold yellow",
                    ),
                    id="fwd_redirect_warning",
                )
                yield Static(t("mail_rules_fwd_targets"))
                yield Vertical(id="fwd_targets")
                with Horizontal(id="fwd_target_entry"):
                    yield Input(
                        placeholder=t("mail_rules_fwd_target_placeholder"),
                        id="fwd_target_input",
                    )
                    yield Button(
                        t("mail_rules_fwd_target_add"), id="fwd_target_add"
                    )
                yield Static(t("mail_rules_fwd_intro"))
                yield TextArea(self.action.body or "", id="fwd_intro")
                yield Checkbox(
                    t("mail_rules_fwd_skip_lists"),
                    self._ignorer_initial,
                    id="fwd_skip_lists",
                )
                yield Static("", id="fwd_status")
                with Horizontal(id="fwd_buttons"):
                    yield Button(
                        t("mail_rules_save"), id="fwd_save", variant="primary"
                    )
                    yield Button(t("mail_rules_cancel"), id="fwd_cancel")

        def on_mount(self) -> None:
            self._refresh_targets()
            self._accorder_mode()
            if self._erreur_options:
                self._status(self._erreur_options)
            self.query_one("#fwd_target_input", Input).focus()

        def _mode(self) -> str:
            valeur = self.query_one("#fwd_mode", Select).value
            return valeur if valeur in rules_model.FORWARD_MODES else "inline"

        def _accorder_mode(self) -> None:
            """Avertissement visible et introduction grisée en vraie
            redirection seulement ; le texte de l'introduction reste."""
            redirection = self._mode() == "redirect"
            self.query_one(
                "#fwd_redirect_warning", Static
            ).display = redirection
            self.query_one("#fwd_intro", TextArea).disabled = redirection

        def _refresh_targets(self) -> None:
            zone = self.query_one("#fwd_targets", Vertical)
            zone.remove_children()
            for index, cible in enumerate(self.targets):
                ligne = Horizontal(classes="fwd_target_item")
                # `Text` : l'adresse est saisie, ou lue d'un fichier.
                ligne.compose_add_child(Static(Text(cible)))
                # Sans `id` : la liste est remontée à chaque changement, et
                # deux boutons de même `id` se croiseraient le temps du
                # retrait. L'index voyage dans `name`.
                ligne.compose_add_child(
                    Button(
                        t("mail_rules_fwd_target_remove"),
                        name=str(index),
                        classes="remove_target",
                    )
                )
                zone.mount(ligne)

        def _status(self, text: str) -> None:
            self.query_one("#fwd_status", Static).update(
                Text(text, style="bold red")
            )

        def _ajouter(self) -> None:
            champ = self.query_one("#fwd_target_input", Input)
            texte = champ.value.strip()
            if not texte:
                return
            try:
                forme = rules_guards.check_forward_target(
                    texte,
                    own=self.own,
                    others=self.others,
                    current=self.targets,
                )
            except rules_model.RuleError as exc:
                self._status(str(exc))
                return
            self.targets.append(forme)
            champ.value = ""
            self._status("")
            self._refresh_targets()

        def on_input_submitted(self, event) -> None:
            if event.input.id == "fwd_target_input":
                self._ajouter()

        def on_select_changed(self, event) -> None:
            if event.select.id == "fwd_mode":
                self._accorder_mode()

        def on_button_pressed(self, event) -> None:
            bouton = event.button
            if bouton.has_class("remove_target"):
                try:
                    index = int(bouton.name or -1)
                except ValueError:
                    return
                if 0 <= index < len(self.targets):
                    del self.targets[index]
                    self._refresh_targets()
            elif bouton.id == "fwd_target_add":
                self._ajouter()
            elif bouton.id == "fwd_save":
                self.action_save_forward()
            elif bouton.id == "fwd_cancel":
                self.action_cancel_forward()

        def _current_action(self):
            options = dict(self.action.options or {})
            options.update(
                {
                    "targets": list(self.targets),
                    "mode": self._mode(),
                    "skip_lists": bool(
                        self.query_one("#fwd_skip_lists", Checkbox).value
                    ),
                }
            )
            return dataclasses.replace(
                self.action,
                body=self.query_one("#fwd_intro", TextArea).text,
                options=options,
            )

        def action_save_forward(self) -> None:
            if self.query_one("#fwd_target_input", Input).value.strip():
                self._status(t("mail_rules_err_fwd_pending"))
                return
            action = self._current_action()
            # Contrôlée nettoyée, comme l'éditeur l'enregistrera : des
            # images héritées d'une réponse ne bloquent pas le formulaire,
            # qui ne sait pas les retirer.
            neutre = dataclasses.replace(
                rules_model.new_rule("forward"),
                action=rules_model.clean_action(action),
            )
            try:
                rules_model.validate(neutre)
            except rules_model.RuleError as exc:
                self._status(str(exc))
                return
            self.dismiss(action)

        def action_cancel_forward(self) -> None:
            self.dismiss(None)

    class HelpScreen(ModalScreen):
        """Touche `h` : les raccourcis du client, et le peu qu'une liste de
        touches ne peut pas dire.

        La liste n'est JAMAIS écrite à la main — elle est engendrée, à
        chaque ouverture, depuis `MailApp.BINDINGS` (voir
        `_shortcuts_table`). Six liaisons (`z`, `l`, `v`, `+`, `-`, `0`) ont
        été ajoutées ou changées pendant ce seul plan : une liste recopiée
        serait déjà fausse aujourd'hui, et enseignerait ensuite avec aplomb
        des touches qui n'existent plus. Engendrée, elle ne peut pas
        dériver.

        Elle ne montre PAS les liaisons de Textual lui-même (`App.BINDINGS`,
        `ctrl+q`/`ctrl+c`) : ce sont les raccourcis DU CLIENT qu'on vient
        chercher ici, pas ceux du cadre applicatif.

        `escape` ferme cette fenêtre, et n'apparaît pas dans le tableau : la
        liaison `escape` de `MailApp` est le « Retour » du plein écran,
        déclarée `show=False` pour ne pas se lire comme un raccourci
        général — son rôle ICI est dit en prose (`mail_help_close_hint`),
        pas emprunté à une liaison qui parle d'autre chose.

        Un second `h` pendant que cette fenêtre est ouverte ne fait rien (il
        n'empile pas une deuxième aide) : dès qu'un écran MODAL est posé,
        les liaisons de `MailApp` ne sont plus consultées —
        `Screen._modal_binding_chain` (`screen.py:449`) tronque la chaîne au
        dernier écran modal, et c'est elle qu'`App._check_bindings`
        (`app.py:3978`) parcourt pour une liaison sans priorité. Mesuré sur
        Textual 8.2.8, et c'est aussi ce qui interdit `priority=True` sur
        `h` (voir `MailApp.BINDINGS`).
        """

        BINDINGS = [
            Binding("escape", "close_help", t("mail_help_close")),
        ]

        CSS = """
        /* Le titre reste visible, le reste défile : ~19 raccourcis plus les
        remarques dépassent un terminal de 24 lignes, et une aide tronquée
        SANS ascenseur cacherait précisément les touches ajoutées en
        dernier. La marge est posée sur le CONTENEUR, pas sur chaque enfant :
        un bloc ajouté ici s'aligne alors tout seul sur les autres. */
        #help_title { padding: 0 1; }
        #help_body { height: 1fr; padding: 0 1; }
        #help_notes { padding-top: 1; }
        #help_close { padding: 0 1; }
        """

        def compose(self):
            with Vertical(id="help_screen"):
                yield Static(t("mail_help_title"), id="help_title")
                with VerticalScroll(id="help_body"):
                    yield Static(t("mail_help_keys_heading"))
                    yield Static(self._shortcuts_table(), id="help_keys")
                    yield Static(t("mail_help_notes_heading"))
                    # `markup=False` : ces phrases sont des données de
                    # traduction, pas du balisage — un crochet dans une
                    # traduction future doit s'afficher, pas se faire lire
                    # comme une balise de style (et disparaître).
                    yield Static(
                        self._notes_text(), id="help_notes", markup=False
                    )
                # HORS du bloc qui défile : la phrase qui dit comment
                # SORTIR ne doit pas pouvoir passer sous le pli. La liste
                # des raccourcis, au-dessus d'elle, dépasse 45 lignes — la
                # hauteur d'un grand terminal — et grandit à chaque touche
                # ajoutée ; une sortie qu'il faut aller chercher en
                # défilant n'en est pas une.
                yield Static(
                    t("mail_help_close_hint"),
                    id="help_close",
                    markup=False,
                )

        def _shortcuts_table(self):
            """Le tableau touche → description, construit depuis
            `MailApp.BINDINGS`.

            Un tableau Rich, et pas un `DataTable` : une description longue
            doit rester LISIBLE, or `DataTable` coupe une cellule trop large
            au lieu de la replier. Ici la colonne des descriptions se replie
            DANS sa colonne, sous elle-même, l'alignement du tableau intact —
            sans qu'aucun code d'ici n'ait à mesurer quoi que ce soit.

            `App.get_key_display` — la MÊME fonction que le pied d'écran —
            met la touche en forme : `plus`/`minus`/`slash` s'y lisent
            `+`/`-`/`/` et `r`/`R` restent distincts (`format_key`,
            `textual/keys.py:290`, vérifié dans Textual 8.2.8). Une table de
            correspondance écrite ici serait un deuxième endroit à tenir à
            jour, qui dirait un jour autre chose que le pied d'écran.
            """
            table = Table(box=None, show_header=False, padding=(0, 2, 0, 0))
            table.add_column(no_wrap=True)
            table.add_column(overflow="fold")
            # `make_bindings` normalise : `MailApp.BINDINGS` peut légalement
            # contenir des tuples ou des chaînes plutôt que des `Binding`
            # (Textual l'accepte), et cette fenêtre ne doit pas être ce qui
            # casse le jour où quelqu'un en écrit un.
            for binding in Binding.make_bindings(self.app.BINDINGS):
                if not binding.show:
                    continue
                # `Text(...)` plutôt que la chaîne nue : Rich lirait sinon
                # un crochet dans une description comme du balisage.
                table.add_row(
                    Text(self.app.get_key_display(binding)),
                    Text(binding.description),
                )
            return table

        def _notes_text(self) -> str:
            return "\n\n".join(
                t(key)
                for key in (
                    "mail_help_mouse",
                    "mail_help_layouts",
                    "mail_help_sync",
                    "mail_help_files",
                    "mail_rules_help",
                )
            )

        def action_close_help(self) -> None:
            self.dismiss()

    class ComposeScreen(ModalScreen):
        BINDINGS = [
            Binding("ctrl+s", "send", "Envoyer"),
            # `priority=True` : `Input` et `TextArea` lient déjà `ctrl+e` eux-
            # mêmes (style Emacs, « fin de ligne ») et la consommeraient
            # avant qu'elle n'atteigne cet écran — exactement le problème
            # que ce changement corrige (`e` nu, avalé par le widget qui a
            # le focus), sous une autre forme. `priority=True` fait vérifier
            # cette liaison AVANT le widget focalisé (`App._check_bindings`,
            # appelé avec `priority=True` avant le transfert de l'évènement),
            # donc elle marche depuis À, Cc, Objet, Pièces jointes ou le
            # corps — pas seulement quand le focus est par hasard sur un
            # bouton.
            Binding("ctrl+e", "external_editor", "Éditeur", priority=True),
            Binding("escape", "cancel", "Annuler"),
        ]

        def __init__(self, session, msg_defaults=None):
            super().__init__()
            self.session = session
            self.defaults = msg_defaults or {}

        def compose(self):
            with Vertical(id="compose"):
                yield Static(
                    f"{t('mail_from')} {self.session.account.from_header()}"
                )
                yield Input(
                    value=self.defaults.get("to", ""),
                    placeholder=t("mail_to"),
                    id="to",
                )
                yield Input(
                    value=self.defaults.get("cc", ""),
                    placeholder=t("mail_cc"),
                    id="cc",
                )
                yield Input(
                    value=self.defaults.get("subject", ""),
                    placeholder=t("mail_subject"),
                    id="subject",
                )
                with Horizontal(id="attachments_row"):
                    yield Input(
                        placeholder=t("mail_attachments_paths"), id="files"
                    )
                    yield Button(t("mail_browse"), id="browse_files")
                yield TextArea(self.defaults.get("body", ""), id="body")
                yield Static("", id="compose_status")
                yield Button(t("mail_send"), id="send")

        def action_external_editor(self) -> None:
            # `edit_in_external_editor` lance `vim`/`nano` par `subprocess`,
            # qui a besoin du terminal — Textual le tient encore et continue
            # d'y dessiner tant qu'on ne le lui a pas repris. `suspend()`
            # rend le terminal le temps du `with`, puis Textual le reprend
            # et redessine.
            area = self.query_one("#body", TextArea)
            with self.app.suspend():
                new_text = edit_in_external_editor(area.text)
            area.text = new_text

        def action_cancel(self) -> None:
            # Pendant l'envoi, fermer l'écran n'arrêterait pas le message :
            # l'annulation est ignorée tant que l'issue n'est pas connue.
            if getattr(self, "_envoi_en_cours", False):
                return
            self.dismiss(None)

        def on_button_pressed(self, event) -> None:
            if event.button.id == "send":
                self.action_send()
            elif event.button.id == "browse_files":
                self._browse_files()

        def on_screen_resume(self) -> None:
            # Envoi réussi pendant qu'un autre écran couvrait celui-ci : il
            # se ferme dès qu'il revient au premier plan, sans offrir un
            # second `ctrl+s` sur un brouillon déjà parti.
            envoye = getattr(self, "_envoye", None)
            if envoye is not None:
                self.dismiss(envoye)

        def _browse_start_dir(self, raw_files: str) -> str:
            return browse_start_dir(raw_files)

        def _browse_files(self) -> None:
            # Le sélecteur suspend l'application : voir `browse_one_path`.
            files_input = self.query_one("#files", Input)
            initial = self._browse_start_dir(files_input.value)

            try:
                chemin = browse_one_path(self.app, initial)
            except Exception as exc:
                # Un sélecteur qui échoue à s'ouvrir (terminal incompatible,
                # `suspend()` non supporté, etc.) ne doit pas emporter le
                # brouillon en cours : l'écran reste utilisable, seul le
                # statut change.
                self.query_one("#compose_status", Static).update(
                    f"{t('mail_browse_failed')} {exc}"
                )
                return

            if chemin is not None:
                files_input.value = append_attachment_path(
                    files_input.value, chemin
                )

        def action_send(self) -> None:
            """Construit le message ici, puis l'envoie dans un fil.

            Les erreurs de saisie restent affichées sans fermer l'écran.
            L'envoi, lui, attend `_sync_lock` le temps d'une passe en cours :
            depuis le fil de l'interface, cette attente gèlerait
            l'application pendant que la passe attend l'interface pour son
            statut. Pendant l'envoi, le bouton est grisé, un second
            `ctrl+s` et `escape` sont ignorés ; après un succès, ils le
            restent.
            """
            from script.todo.mail.smtp_send import build_message

            if getattr(self, "_envoi_en_cours", False):
                return
            status = self.query_one("#compose_status", Static)
            try:
                paths = parse_paths(self.query_one("#files", Input).value)
                msg = build_message(
                    self.session.account,
                    parse_recipients(self.query_one("#to", Input).value),
                    self.query_one("#subject", Input).value,
                    self.query_one("#body", TextArea).text,
                    cc=parse_recipients(self.query_one("#cc", Input).value),
                    attachments=paths,
                    in_reply_to=self.defaults.get("in_reply_to"),
                    references=self.defaults.get("references"),
                )
                forwarded = self.defaults.get("forward_of")
                if forwarded is not None:
                    # `subtype=` seul : pour un `Message`, `add_attachment`
                    # dispatche vers `set_message_content`, qui n'a pas de
                    # paramètre `maintype` (vérifié à la tâche 7).
                    msg.add_attachment(forwarded, subtype="rfc822")
            except Exception as exc:
                # On ne ferme PAS l'écran : le brouillon reste à l'écran, avec
                # l'erreur exacte, prêt à être corrigé et renvoyé.
                status.update(f"[b red]{exc}[/]")
                return
            self._envoi_en_cours = True
            status.update("")
            self._bouton_envoi(False)
            session, app = self.session, self.app
            verrou = app._sync_lock
            answer_of = self.defaults.get("answer_of")

            def envoyer() -> None:
                etait_en_ligne = session.online
                try:
                    statut = deliver(session, msg, verrou=verrou)
                except Exception as exc:
                    app.call_from_thread(self._echec_envoi, exc)
                    return
                app.call_from_thread(
                    self._apres_envoi,
                    statut,
                    answer_of if etait_en_ligne else None,
                )

            self.run_worker(envoyer, thread=True)

        def _bouton_envoi(self, actif: bool) -> None:
            try:
                self.query_one("#send", Button).disabled = not actif
            except Exception:
                pass

        def _echec_envoi(self, exc) -> None:
            """Fil de l'interface : l'erreur du serveur, écran gardé."""
            self._envoi_en_cours = False
            self._bouton_envoi(True)
            try:
                self.query_one("#compose_status", Static).update(
                    f"[b red]{exc}[/]"
                )
            except Exception:
                self.app.set_status(f"[b red]{exc}[/]")

        def _apres_envoi(self, statut, answer_of) -> None:
            """Fil de l'interface : `\\Answered` sur l'original, puis
            fermeture.

            Hors ligne (`answer_of` None), le message est en file et rien
            n'est posé. `_envoi_en_cours` reste vrai : le brouillon est
            parti, aucun geste ne le renvoie. Couvert par un autre écran,
            celui-ci se ferme à son retour (`on_screen_resume`).
            """
            if answer_of:
                try:
                    self.app.mark_answered(self.session, *answer_of)
                except Exception:
                    _logger.exception("\\Answered après une réponse")
            if self.app.screen is self:
                self.dismiss(statut)
                return
            self._envoye = statut
            self.app.set_status(statut)

    class _OpenKdbxManager:
        """Un `KdbxManager` minimal, dont le mot de passe est déjà connu —
        saisi à l'instant dans `VaultScreen` — pour que `get_kdbx()` n'ait
        jamais besoin de `getpass.getpass()` : Textual possède déjà le
        terminal, un tel appel n'a nulle part où s'afficher proprement."""

        def __init__(self, path: str, password: str):
            self._path = path
            self._password = password
            self._kdbx = None

        def get_kdbx(self):
            if self._kdbx is None:
                from pykeepass import PyKeePass

                self._kdbx = PyKeePass(self._path, password=self._password)
            return self._kdbx

    class VaultScreen(ModalScreen):
        """Poussé en premier quand aucun kdbx n'est configuré : créer un
        nouveau coffre ou en adopter un déjà présent sur disque. Annuler
        annule tout le flux — `AccountScreen` n'est jamais poussé."""

        BINDINGS = [
            Binding("escape", "cancel", "Annuler"),
        ]

        def compose(self):
            with Vertical(id="vault_form"):
                yield Static(t("mail_kdbx_none_configured"))
                yield Input(
                    value=account_setup.DEFAULT_KDBX_PATH,
                    placeholder=t("mail_kdbx_ask_path_new"),
                    id="vault_path",
                )
                yield Input(
                    placeholder=t("mail_kdbx_ask_password"),
                    password=True,
                    id="vault_password",
                )
                yield Input(
                    placeholder=t("mail_kdbx_ask_password_confirm"),
                    password=True,
                    id="vault_password_confirm",
                )
                yield Static("", id="vault_status")
                yield Button(t("mail_kdbx_menu_create"), id="vault_create")
                yield Button(t("mail_kdbx_menu_choose"), id="vault_choose")

        def action_cancel(self) -> None:
            self.dismiss(None)

        def on_button_pressed(self, event) -> None:
            if event.button.id == "vault_create":
                self._create()
            elif event.button.id == "vault_choose":
                self._choose()

        def _create(self) -> None:
            status = self.query_one("#vault_status", Static)
            try:
                # RÈGLE STRUCTURELLE (round 3) : dès que `password` est lu
                # ci-dessous, PLUS AUCUNE instruction de cette méthode ne
                # doit tourner hors de ce `try` — trois manches de revue ont
                # chacune trouvé un appel oublié hors garde (`create_vault`,
                # `get_kdbx`) pendant que `password`, en clair, restait une
                # variable locale de CETTE fonction. Une exception qui s'en
                # échappe atterrit dans `App._handle_exception`, qui affiche
                # un `rich.traceback.Traceback(show_locals=True, …)` — donc
                # `except Exception` large à dessein.
                #
                # Le `try` couvre le CORPS, PAS `dismiss()` (round 4) :
                # `password`/`confirm` restent des noms liés dans CETTE
                # fonction jusqu'à son retour, garde ou pas. Vérifié dans
                # Textual 8.2.8 : `Screen.dismiss()` ne rappelle PAS le
                # callback de résultat directement —
                # `ResultCallback.__call__` (`screen.py:130`) fait
                # `self.requester.call_next(self.callback, result)`, qui ne
                # fait qu'EMPILER l'appel (`message_pump.py:507`) ; il ne
                # tourne qu'après le retour complet de cette méthode, dans
                # un cadre d'appel disjoint (confirmé empiriquement : ce
                # cadre-ci n'apparaît PAS dans la pile du callback). Rien ne
                # prouve donc qu'un échec dans ce callback exposerait
                # `password`/`confirm` d'ICI — mais les effacer avant
                # `dismiss()` ne coûte rien et retire le doute pour de bon :
                # une traceback ne peut rien afficher d'un nom qui ne
                # référence plus rien.
                path = self.query_one("#vault_path", Input).value.strip()
                password = self.query_one("#vault_password", Input).value
                confirm = self.query_one(
                    "#vault_password_confirm", Input
                ).value
                if password != confirm:
                    status.update(t("mail_kdbx_password_mismatch"))
                    return

                account_setup.create_vault(
                    self.app.config_file, path, password
                )

                # Ouvre le coffre MAINTENANT, symétriquement à `_choose` :
                # un coffre créé mais inouvrable (pykeepass lève
                # `CredentialsError`, `HeaderChecksumError`, etc. — aucune
                # n'étant une `OSError`) se signale ICI, où l'utilisateur
                # peut encore agir dessus, pas plus tard sur `AccountScreen`.
                manager = _OpenKdbxManager(path, password)
                manager.get_kdbx()
            except Exception as exc:
                status.update(str(exc))
                return
            password = None
            confirm = None
            self.dismiss(SecretStore(kdbx_manager=manager, use_keyring=True))

        def _choose(self) -> None:
            status = self.query_one("#vault_status", Static)
            try:
                # Même règle structurelle qu'au-dessus dans `_create`, et
                # même vérification sur la portée de `password` face à
                # `dismiss()` (round 4, voir le commentaire détaillé
                # là-bas).
                path = self.query_one("#vault_path", Input).value.strip()
                password = self.query_one("#vault_password", Input).value

                account_setup.use_existing_vault(self.app.config_file, path)

                manager = _OpenKdbxManager(path, password)
                # Ouvre le coffre MAINTENANT plutôt que d'attendre le premier
                # `SecretStore.set()` : un mauvais mot de passe s'affiche ici,
                # sur cet écran, au lieu d'échouer plus tard sans explication.
                manager.get_kdbx()
            except Exception as exc:
                status.update(str(exc))
                return
            password = None
            self.dismiss(SecretStore(kdbx_manager=manager, use_keyring=True))

    class AccountScreen(ModalScreen):
        """Le formulaire d'ajout de compte : mêmes champs que le CLI
        (`menu._add_account`), mais un mot de passe erroné ou un nom invalide
        se lit sur `#account_status`, jamais comme un plantage."""

        BINDINGS = [
            Binding("ctrl+s", "save", "Enregistrer"),
            Binding("escape", "cancel", "Annuler"),
        ]

        CSS = """
        /* Le formulaire défile : onze champs et deux boutons dépassent un
        terminal de 24 lignes, et le bouton d'enregistrement est justement
        le dernier — hors de l'écran, il devient introuvable à la souris.
        `height: auto` sur le contenu et `1fr` sur le conteneur : sans ça,
        le contenu se replie à la taille de la fenêtre et rien ne défile. */
        #account_form { height: 1fr; }
        """

        def __init__(self, secret_store, config_get=None):
            super().__init__()
            self.secret_store = secret_store
            # Les réglages OAuth de celui qui déploie : sans eux, le
            # parcours d'autorisation ne peut pas être proposé.
            self.config_get = config_get

        def compose(self):
            with VerticalScroll(id="account_form"):
                yield Static(t("mail_account_add"))
                yield Input(placeholder=t("mail_ask_name"), id="acc_name")
                yield Input(placeholder=t("mail_ask_email"), id="acc_email")
                yield Input(
                    placeholder=t("mail_ask_display_name"), id="acc_display"
                )
                yield Static(t("mail_ask_preset"))
                yield Select(
                    [(PRESETS[key]["label"], key) for key in PRESETS],
                    id="acc_preset",
                    value="generic",
                    allow_blank=False,
                )
                yield Input(placeholder=t("mail_ask_imap_host"), id="acc_imap")
                yield Input(placeholder=t("mail_ask_smtp_host"), id="acc_smtp")
                # Désactivée tant qu'un préréglage n'est pas choisi : le
                # genre d'authentification n'est une QUESTION que chez un
                # fournisseur qui accepte les deux.
                yield Select(
                    [
                        (t("mail_auth_choice_password"), "login"),
                        (t("mail_auth_choice_oauth"), "oauth"),
                    ],
                    id="acc_auth",
                    value="login",
                    allow_blank=False,
                    disabled=True,
                )
                yield Input(
                    placeholder=t("mail_ask_password"),
                    password=True,
                    id="acc_password",
                )
                bouton = Button(
                    t("mail_oauth_choice_browser"), id="acc_authorize"
                )
                # Caché, pas désactivé : un bouton grisé invite à chercher
                # ce qui l'activerait, alors qu'il n'y a rien à faire sans
                # identifiant client.
                bouton.display = False
                yield bouton
                yield Static("", id="account_status")
                yield Button(t("mail_account_save"), id="acc_save")

        def action_cancel(self) -> None:
            self.dismiss(None)

        def on_button_pressed(self, event) -> None:
            if event.button.id == "acc_save":
                self.action_save()
            elif event.button.id == "acc_authorize":
                self.action_authorize()

        def action_authorize(self) -> None:
            """Mène le parcours d'autorisation dans un fil de travail.

            Sur le fil de l'interface, l'attente de la redirection gèlerait
            la fenêtre — y compris Échap, donc sans moyen d'abandonner.
            """
            self.query_one("#account_status", Static).update(
                t("mail_oauth_opening_browser")
            )
            self.run_worker(self._autoriser, thread=True)

        def _autoriser(self) -> None:
            from script.todo.mail import oauth

            preset_key = self.query_one("#acc_preset", Select).value
            compte = SimpleNamespace(
                preset=preset_key,
                email=self.query_one("#acc_email", Input).value.strip(),
                auth="oauth",
            )
            try:
                jeu = oauth.authorize(compte, config_get=self.config_get)
            except Exception as exc:
                # Large À DESSEIN : une exception qui s'échappe d'un fil de
                # travail atterrit dans `App._handle_exception`, dont la
                # trace affiche les variables locales — et l'une d'elles
                # porterait le secret.
                self.app.call_from_thread(self._autorisation_ratee, str(exc))
                return
            self.app.call_from_thread(self._autorisation_reussie, jeu)

        def _autorisation_reussie(self, jeu) -> None:
            self.query_one("#acc_password", Input).value = jeu.refresh_token
            self.query_one("#account_status", Static).update(
                t("mail_token_saved")
            )

        def _autorisation_ratee(self, message: str) -> None:
            self.query_one("#account_status", Static).update(Text(message))

        def on_select_changed(self, event) -> None:
            if event.select.id == "acc_auth":
                self._accorder_champ_secret(event.value)
                return
            if event.select.id != "acc_preset":
                return
            self._accorder_authentification(event.value)
            imap_input = self.query_one("#acc_imap", Input)
            smtp_input = self.query_one("#acc_smtp", Input)
            preset_key = event.value
            if preset_key == "generic":
                imap_input.value = ""
                smtp_input.value = ""
                imap_input.disabled = False
                smtp_input.disabled = False
            else:
                preset = PRESETS[preset_key]
                imap_input.value = preset["imap"]["host"]
                smtp_input.value = preset["smtp"]["host"]
                imap_input.disabled = True
                smtp_input.disabled = True

        def _accorder_authentification(self, preset_key) -> None:
            """Accorde la liste d'authentification au préréglage choisi.

            La liste n'est active que lorsqu'il y a un CHOIX : un
            fournisseur sans OAuth ne doit pas se voir proposer une voie qui
            n'existe pas, et celui qui n'accepte plus de mot de passe ne
            doit pas se voir proposer une impasse.
            """
            preset = PRESETS.get(preset_key, {})
            auth = self.query_one("#acc_auth", Select)
            if not preset.get("oauth"):
                auth.value = "login"
                auth.disabled = True
            elif not preset.get("app_password"):
                auth.value = "oauth"
                auth.disabled = True
            else:
                auth.disabled = False
            self._accorder_champ_secret(auth.value)

        def _accorder_bouton(self, preset_key, auth) -> None:
            """Le bouton n'apparaît que s'il a une page à ouvrir.

            Il faut un compte OAuth, un fournisseur qui en offre, et un
            identifiant client configuré : sans lui, la page répondrait
            « invalid_client » et la panne se chercherait chez le
            fournisseur.
            """
            from script.todo.mail import oauth

            possible = False
            if auth == "oauth":
                compte = SimpleNamespace(preset=preset_key, auth="oauth")
                try:
                    possible = bool(
                        oauth.settings_for(compte, self.config_get)[
                            "client_id"
                        ]
                    )
                except oauth.OAuthError:
                    possible = False
            self.query_one("#acc_authorize", Button).display = possible

        def _accorder_champ_secret(self, auth) -> None:
            """Le champ du secret dit ce qu'on y attend.

            « Mot de passe » devant un champ qui veut un jeton fait coller
            un mot de passe, que le serveur refusera sans dire pourquoi.
            """
            champ = self.query_one("#acc_password", Input)
            champ.placeholder = t(
                "mail_ask_refresh_token"
                if auth == "oauth"
                else "mail_ask_password"
            )
            self._accorder_bouton(
                self.query_one("#acc_preset", Select).value, auth
            )

        def action_save(self) -> None:
            status = self.query_one("#account_status", Static)
            try:
                # RÈGLE STRUCTURELLE (round 3) : dès que `password` est lu
                # ci-dessous, PLUS AUCUNE instruction de cette méthode ne
                # doit tourner hors de ce `try` — trois manches de revue ont
                # chacune trouvé un appel oublié hors garde
                # (`mail_accounts.load()`, `secret_store.available_backends()`,
                # `account_setup.save_new_account`) pendant que `password`,
                # en clair, restait une variable locale de CETTE fonction.
                # Une exception qui s'en échappe atterrit dans
                # `App._handle_exception`, qui affiche un
                # `rich.traceback.Traceback(show_locals=True, …)` — donc
                # `except Exception` large à dessein.
                #
                # Le `try` couvre le CORPS, PAS `dismiss()` (round 4) :
                # `password` reste un nom lié dans CETTE fonction jusqu'à
                # son retour, garde ou pas. Vérifié dans Textual 8.2.8 :
                # `Screen.dismiss()` ne rappelle PAS le callback de résultat
                # (ici `_after_account_added` → `reload_folders()` →
                # `mailbox_refs()`) directement — `ResultCallback.__call__`
                # (`screen.py:130`) fait `self.requester.call_next(self.callback,
                # result)`, qui ne fait qu'EMPILER l'appel
                # (`message_pump.py:507`) ; il ne tourne qu'après le retour
                # complet de cette méthode, dans un cadre d'appel disjoint
                # (confirmé empiriquement : ce cadre-ci n'apparaît PAS dans
                # la pile du callback). Rien ne prouve donc qu'un échec dans
                # ce callback exposerait `password` d'ICI — mais l'effacer
                # avant `dismiss()` ne coûte rien et retire le doute pour de
                # bon : une traceback ne peut rien afficher d'un nom qui ne
                # référence plus rien.
                name = self.query_one("#acc_name", Input).value.strip()
                email_addr = self.query_one("#acc_email", Input).value.strip()
                display = self.query_one("#acc_display", Input).value.strip()
                preset_key = self.query_one("#acc_preset", Select).value
                auth = self.query_one("#acc_auth", Select).value
                password = self.query_one("#acc_password", Input).value

                if not name or not email_addr or not password:
                    status.update(t("mail_account_missing_fields"))
                    return

                vault = (
                    "kdbx"
                    if "kdbx" in self.secret_store.available_backends()
                    else "keyring"
                )
                account = mail_accounts.account_from_preset(
                    name,
                    email_addr,
                    preset_key,
                    display_name=display,
                    vault=vault,
                    auth=auth,
                )

                if preset_key == "generic":
                    account.imap.host = self.query_one(
                        "#acc_imap", Input
                    ).value.strip()
                    account.smtp.host = self.query_one(
                        "#acc_smtp", Input
                    ).value.strip()

                existing = [
                    a for a in mail_accounts.load() if a.name != account.name
                ]
                account_setup.save_new_account(
                    self.secret_store,
                    existing + [account],
                    account,
                    password,
                )
            except Exception as exc:
                status.update(str(exc))
                return

            password = None
            self.dismiss(account)

    app = MailApp(
        sessions or [],
        config_file=config_file,
        secret_store=secret_store,
        connect_fn=connect_fn,
        base=base,
    )
    if run_app:
        app.run()
