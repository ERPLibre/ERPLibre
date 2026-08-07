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

import logging
import threading
from dataclasses import dataclass

from script.todo.mail.imap_sync import Syncer
from script.todo.mail.store import Store, sweep_orphan_ephemeral

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
    ):
        self.account = account
        self.store = store
        self.syncer = syncer
        self.error = error
        self.password = password

    @property
    def online(self) -> bool:
        return self.syncer is not None

    def sync(self, progress=None):
        if self.syncer is None:
            return None
        return self.syncer.sync(progress=progress)

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


def open_session(account, secrets, base=None, connect_fn=None) -> Session:
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
        password = secrets.get(account.secret_ref) or ""
        if not password:
            raise ValueError(t("mail_no_password_stored"))
        syncer = Syncer(store, connect_fn(account, password))
    except Exception as exc:
        error = str(exc)
    return Session(account, store, syncer, error, password)


def open_sessions(
    accounts, secrets, base=None, connect_fn=None
) -> list[Session]:
    """Ouvre le cache de chaque compte actif, puis tente le réseau.

    L'ordre compte : un mot de passe absent ou un serveur muet ne doit pas
    priver l'utilisateur de ce qu'il a déjà téléchargé.
    """
    if connect_fn is None:
        from script.todo.mail.imap_transport import connect as connect_fn

    sweep_orphan_ephemeral()
    sessions = [
        open_session(account, secrets, base=base, connect_fn=connect_fn)
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
    """« a@y.ca; Alice <b@y.ca> » → deux entrées. Virgule ou point-virgule."""
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


def deliver(session, msg, send_fn=None, connect_fn=None) -> str:
    """Envoie, puis dépose une copie dans Envoyés. Rend le texte de statut.

    L'ordre n'est pas négociable : l'APPEND vient APRÈS l'envoi, et son échec
    n'annule rien. Le message est déjà parti ; le signaler comme un échec
    pousserait l'utilisateur à l'envoyer deux fois.
    """
    from script.todo.mail.smtp_send import SmtpError
    from script.todo.mail.smtp_send import connect as smtp_connect
    from script.todo.mail.smtp_send import send as smtp_send_fn
    from script.todo.mail.smtp_send import without_bcc

    if not session.online:
        raise SmtpError(t("mail_offline_cannot_send"))

    send_fn = send_fn or smtp_send_fn
    transport = None
    if send_fn is smtp_send_fn:
        connect_fn = connect_fn or smtp_connect
        transport = connect_fn(session.account, session.password)
    try:
        served = send_fn(session.account, msg, transport)
    finally:
        if transport is not None:
            transport.quit()

    status = f"{t('mail_sent_to')} {', '.join(served)}"
    sent_folder = resolve_sent_folder(session)
    try:
        # Le Cci ne doit pas ressortir par cette porte non plus : `send()`
        # l'a déjà retiré avant l'envoi SMTP, mais la copie déposée ici part
        # par IMAP — sans `without_bcc`, le Cci redeviendrait un en-tête
        # lisible sur le serveur.
        session.syncer.transport.append(
            sent_folder,
            without_bcc(msg).as_bytes(),
            ["\\Seen"],
        )
    except Exception as exc:
        _logger.exception(
            "%s : APPEND vers %r a échoué", session.account.name, sent_folder
        )
        # En SUFFIXE, cet échec disparaissait en bout d'une ligne de statut
        # qui peut être longue (plusieurs destinataires) — sur la barre
        # d'une seule ligne de haut, la fin est justement ce qui se perd. En
        # PRÉFIXE, en gras rouge, il reste visible même tronqué.
        status = f"[b red]⚠ {t('mail_sent_not_filed')} ({exc})[/] — {status}"
    else:
        # Écriture locale immédiate (design, ligne 308) : une sync ciblée
        # sur Envoyés seul, pour que le message apparaisse sans attendre la
        # prochaine passe complète. `sync_one` ne lève jamais — voir sa
        # docstring — donc un envoi déjà réussi ne peut pas se lire comme un
        # échec parce que cette relecture aurait raté.
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
    reproduirait exactement la plainte que cette fonction existe pour
    résoudre : « j'ai une erreur, mais aucun log ».
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
        from textual.screen import ModalScreen
        from textual.widgets import (
            Button,
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
    from script.todo.mail import account_setup
    from script.todo.mail import accounts as mail_accounts
    from script.todo.mail import tui_text
    from script.todo.mail.accounts import PRESETS
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
            # l'aide elle-même. Mesuré dans les deux sens sur Textual 8.2.8
            # avant d'écrire ceci.
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
            Binding("s", "mark_seen", t("mail_mark_seen_binding")),
            Binding("u", "mark_unseen", t("mail_mark_unseen_binding")),
            Binding("w", "save_attachment", t("mail_save_attachment_binding")),
            Binding("c", "compose", t("mail_compose_binding")),
            Binding("a", "reply", t("mail_reply_binding")),
            Binding("A", "reply_all", t("mail_reply_all_binding")),
            Binding("f", "forward", t("mail_forward_binding")),
            Binding("n", "add_account", t("mail_add_account_binding")),
            Binding("l", "show_log", t("mail_log_binding")),
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

        def select_ref(self, ref: MailboxRef) -> None:
            self.current_ref = ref
            session = self.session_for(ref.account_name)
            state = session.store.folder_state(ref.folder_name)
            self.metas = (
                session.store.list_messages(state["id"]) if state else []
            )
            self.refresh_list()

        def refresh_list(self) -> None:
            import time

            table = self.query_one("#list", DataTable)
            table.clear()
            now = int(time.time())
            for meta in tui_text.filter_messages(self.metas, self.query):
                table.add_row(
                    "●" if tui_text.is_unread(meta.flags) else " ",
                    tui_text.truncate(tui_text.short_addr(meta.frm), 22),
                    tui_text.truncate(
                        meta.subject or t("mail_no_subject"), 48
                    ),
                    tui_text.format_date(meta.date, now),
                    key=str(meta.uid),
                )

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
            current_uid = current.uid if current is not None else None
            state = session.store.folder_state(self.current_ref.folder_name)
            self.metas = (
                session.store.list_messages(state["id"]) if state else []
            )
            self.refresh_list()
            if current_uid is None:
                return
            from textual.widgets.data_table import RowDoesNotExist

            table = self.query_one("#list", DataTable)
            try:
                row_index = table.get_row_index(str(current_uid))
            except RowDoesNotExist:
                # Le message qui avait le focus a disparu du dossier (purge
                # de synchronisation, suppression ailleurs) : `refresh_list`
                # a déjà laissé le curseur là où `DataTable.clear()` le
                # remet — en tête de liste, seul choix qui ne pointe pas
                # dans le vide.
                return
            table.move_cursor(row=row_index)

        def current_meta(self):
            table = self.query_one("#list", DataTable)
            if table.cursor_row is None or not self.metas:
                return None
            shown = tui_text.filter_messages(self.metas, self.query)
            if table.cursor_row >= len(shown):
                return None
            return shown[table.cursor_row]

        # -- événements -------------------------------------------------

        def on_tree_node_selected(self, event) -> None:
            data = getattr(event.node, "data", None)
            if data == ADD_ACCOUNT_NODE:
                self.action_add_account()
            elif isinstance(data, MailboxRef):
                self.select_ref(data)

        def on_data_table_row_highlighted(self, event) -> None:
            self.show_preview()

        def on_input_changed(self, event) -> None:
            if event.input.id != "search" or event.value == self.query:
                # `clear_search` a déjà mis `self.query` à jour ET rafraîchi
                # la liste avant que Textual ne poste ce message — sans ce
                # garde-fou, `refresh_list()` tournerait une seconde fois
                # pour rien dès que le champ change de valeur.
                return
            self.query = event.value
            self.refresh_list()

        def show_preview(self) -> None:
            meta = self.current_meta()
            preview = self.query_one("#preview", Static)
            if meta is None or self.current_ref is None:
                preview.update("")
                return
            session = self.session_for(self.current_ref.account_name)
            header = (
                f"[b]{t('mail_from')}[/b] {meta.frm}\n"
                f"[b]{t('mail_to')}[/b] {meta.to}\n"
                f"[b]{t('mail_subject')}[/b] {meta.subject}\n"
                f"[b]{t('mail_date')}[/b] "
                f"{tui_text.format_date_full(meta.date)}\n"
                f"{tui_text.format_size(meta.size)}\n\n"
            )
            if not session.online and not meta.has_body:
                preview.update(header + t("mail_body_needs_network"))
                return
            try:
                raw = (
                    session.syncer.fetch_body(
                        self.current_ref.folder_name, meta.uid
                    )
                    if session.online
                    else session.store.read_body(
                        self.current_ref.folder_name, meta.uid
                    )
                )
            except Exception as exc:
                preview.update(header + f"{t('mail_body_error')} {exc}")
                return
            body, attachments = tui_text.extract_body(raw or b"")
            if attachments:
                listing = "\n".join(
                    f"  📎 {a.filename}  {tui_text.format_size(a.size)}"
                    for a in attachments
                )
                header += f"{t('mail_attachments')}\n{listing}\n\n"
            preview.update(header + body)

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
            partage (tâche 25) insérée ENTRE eux a une taille FIXE
            (`_SPLITTER_SIZE`) qui n'appartient à NI L'UN NI L'AUTRE. La
            compter dans le total partageable laisserait le voisin
            `sibling_minimum - (taille de la barre)` au plafond plutôt que
            `sibling_minimum` — la même erreur d'une cellule que la bordure
            (tâche 24), sous une autre forme. Mesurée sur le widget RÉEL de
            la barre, jamais recopiée depuis la CSS : une seule source de
            vérité pour sa taille.

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

        def _set_flag(self, flag: str, add: bool) -> None:
            meta = self.current_meta()
            if meta is None or self.current_ref is None:
                return
            session = self.session_for(self.current_ref.account_name)
            state = session.store.folder_state(self.current_ref.folder_name)
            flags = set(meta.flags.split()) if meta.flags else set()
            flags.add(flag) if add else flags.discard(flag)
            session.store.update_flags(
                state["id"], meta.uid, " ".join(sorted(flags))
            )
            if session.online:
                try:
                    session.syncer.transport.select(
                        self.current_ref.folder_name
                    )
                    session.syncer.transport.store_flags(
                        meta.uid, [flag] if add else [], [] if add else [flag]
                    )
                except Exception as exc:
                    self.set_status(f"{t('mail_flag_error')} {exc}")
            self.select_ref(self.current_ref)

        def action_sync_current(self) -> None:
            self.run_worker(self.sync_current_worker, thread=True)

        def action_sync_all(self) -> None:
            self.run_worker(self.sync_all_worker, thread=True)

        def set_status(self, text: str) -> None:
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
            # Sérialise TOUTE la passe, pas seulement l'appel réseau : deux
            # `run_worker(thread=True)` (auto-refresh et `r`/`R` manuel)
            # partageraient sinon le même socket imaplib, qui n'est pas
            # thread-safe.
            with self._sync_lock:
                for session in sessions:
                    if session is None or not session.online:
                        continue
                    self.set_status(
                        f"{t('mail_syncing')} {session.account.name}…"
                    )
                    try:
                        report = session.sync()
                    except Exception as exc:
                        _logger.exception(
                            "sync de %s a échoué", session.account.name
                        )
                        self.set_status(f"{session.account.name} : {exc}")
                        # Le statut ci-dessus est ÉPHÉMÈRE (le prochain
                        # message l'efface) : `LogScreen` (touche `l`)
                        # existe précisément pour regarder APRÈS coup, donc
                        # la panne la plus grave — la synchronisation
                        # entière qui a levé, pas seulement un dossier —
                        # doit y rester lisible, dans la même forme que les
                        # entrées de `report.errors` ci-dessous.
                        self.session_errors[session.account.name] = [str(exc)]
                        continue
                    # La DERNIÈRE passe l'emporte, même vide : un compte qui
                    # se remet à synchroniser proprement ne doit pas garder
                    # affichée, dans `LogScreen`, une erreur qui ne décrit
                    # plus l'état courant.
                    self.session_errors[session.account.name] = list(
                        report.errors
                    )
                    message = (
                        f"{session.account.name} : {report.new_messages}"
                        f" {t('mail_new_messages')}"
                    )
                    if report.errors:
                        # Le premier message d'erreur EN ENTIER, pas
                        # seulement leur compte : un « 1 erreur » n'a jamais
                        # dit à personne ce qui a échoué. Le journal (voir
                        # `imap_sync.Syncer.sync`) garde les autres au cas où
                        # il y en aurait plus d'un.
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
                if self._thread_id_differs():
                    self.call_from_thread(self.reload_folders)
                else:
                    self.reload_folders()

        def action_save_attachment(self) -> None:
            meta = self.current_meta()
            if meta is None or self.current_ref is None:
                return
            session = self.session_for(self.current_ref.account_name)
            raw = session.store.read_body(
                self.current_ref.folder_name, meta.uid
            )
            if raw is None:
                self.set_status(t("mail_body_needs_network"))
                return
            _, attachments = tui_text.extract_body(raw)
            if not attachments:
                self.set_status(t("mail_no_attachment"))
                return
            try:
                target = save_attachment(raw, 0, "~/Téléchargements")
            except Exception as exc:
                self.set_status(f"{t('mail_save_failed')} {exc}")
                return
            self.set_status(f"{t('mail_saved_to')} {target}")

        def action_compose(self) -> None:
            session = self._session_or_first()
            if session:
                self.push_screen(ComposeScreen(session), self._after_compose)

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
            session = self.session_for(self.current_ref.account_name)
            raw = session.store.read_body(
                self.current_ref.folder_name, meta.uid
            )
            if raw is None and session.online:
                raw = session.syncer.fetch_body(
                    self.current_ref.folder_name, meta.uid
                )
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
            self.push_screen(
                ComposeScreen(
                    session,
                    {
                        "to": draft["To"] or "",
                        "cc": draft["Cc"] or "",
                        "subject": draft["Subject"] or "",
                        "body": draft.get_content(),
                        "in_reply_to": draft["In-Reply-To"],
                        "references": draft["References"],
                    },
                ),
                self._after_compose,
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

        def action_add_account(self) -> None:
            if self.config_file is None or self.secret_store is None:
                self.set_status(t("mail_account_add_unavailable"))
                return
            if account_setup.kdbx_is_configured(self.config_file):
                self.push_screen(
                    AccountScreen(self.secret_store),
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
                AccountScreen(self.secret_store), self._after_account_added
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

        Une fenêtre qui s'ouvre VIDE reproduirait exactement la plainte qui
        justifie son existence (« j'ai une erreur, mais aucun log ») :
        chaque état — journal absent, vide, illisible, aucune erreur de
        session — se dit en toutes lettres, jamais en silence.
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
                    "mail_help_close_hint",
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
            self.dismiss(None)

        def on_button_pressed(self, event) -> None:
            if event.button.id == "send":
                self.action_send()
            elif event.button.id == "browse_files":
                self._browse_files()

        def _browse_start_dir(self, raw_files: str) -> str:
            import os

            paths = parse_paths(raw_files)
            if paths:
                candidate = os.path.dirname(os.path.expanduser(paths[-1]))
                if candidate and os.path.isdir(candidate):
                    return candidate
            return os.path.expanduser("~")

        def _browse_files(self) -> None:
            # `todo_file_browser` est bâti sur urwid, qui possède son propre
            # `urwid.MainLoop` — deux boucles ne peuvent pas tenir le
            # terminal en même temps. `suspend()` rend le terminal à urwid
            # le temps du `with`, puis Textual le reprend et redessine.
            #
            # L'IMPORT est fait DANS le `with`, pas avant, et ce n'est pas
            # cosmétique : `urwid.raw_display.Screen.__init__` a pour
            # défaut `output=sys.stdout`, résolu une seule fois, à
            # l'IMPORT du module — donc à la première exécution de cette
            # méthode dans le processus. Importer `todo_file_browser`
            # AVANT `suspend()` fige ce défaut sur le `sys.stdout`
            # qu'App.run() redirige pendant tout le cycle de vie de
            # l'appli (`redirect_stdout(self._capture_stdout)`), et PAS le
            # vrai terminal — `Screen.get_cols_rows()` plante alors sur un
            # descripteur -1. Constaté par un test manuel (voir le
            # rapport) ; importer ici, une fois le terminal rendu par
            # `suspend()`, fige le bon `sys.stdout` à la place.
            files_input = self.query_one("#files", Input)
            initial = self._browse_start_dir(files_input.value)
            chosen: dict = {}

            try:
                with self.app.suspend():
                    from script.todo import todo_file_browser

                    def _on_selected(path: str) -> None:
                        chosen["path"] = path
                        todo_file_browser.exit_program()

                    browser = todo_file_browser.FileBrowser(
                        initial, _on_selected
                    )
                    browser.run_main_frame()
            except Exception as exc:
                # Un sélecteur qui échoue à s'ouvrir (terminal incompatible,
                # `suspend()` non supporté, etc.) ne doit pas emporter le
                # brouillon en cours : l'écran reste utilisable, seul le
                # statut change.
                self.query_one("#compose_status", Static).update(
                    f"{t('mail_browse_failed')} {exc}"
                )
                return

            if "path" in chosen:
                files_input.value = append_attachment_path(
                    files_input.value, chosen["path"]
                )

        def action_send(self) -> None:
            from script.todo.mail.smtp_send import build_message

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
                self.dismiss(deliver(self.session, msg))
            except Exception as exc:
                # On ne ferme PAS l'écran : le brouillon reste à l'écran, avec
                # l'erreur exacte du serveur, prêt à être corrigé et renvoyé.
                status.update(f"[b red]{exc}[/]")

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

        def __init__(self, secret_store):
            super().__init__()
            self.secret_store = secret_store

        def compose(self):
            with Vertical(id="account_form"):
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
                yield Input(
                    placeholder=t("mail_ask_password"),
                    password=True,
                    id="acc_password",
                )
                yield Static("", id="account_status")
                yield Button(t("mail_account_save"), id="acc_save")

        def action_cancel(self) -> None:
            self.dismiss(None)

        def on_button_pressed(self, event) -> None:
            if event.button.id == "acc_save":
                self.action_save()

        def on_select_changed(self, event) -> None:
            if event.select.id != "acc_preset":
                return
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
