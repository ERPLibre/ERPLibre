#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les fils à l'écran : trois volets, et la lecture en plein écran.

Textual s'importe DANS `run_tui`, jamais au niveau module — c'est le motif
du reste de `script/todo/`. Conséquence utile : la moitié haute de ce
fichier (sessions, fils) se teste sans écran et sans dépendance.

Un écran SÉPARÉ de celui du courriel, et non un onglet de plus dedans : un
fil n'a ni dossiers, ni UID croissants, ni brouillons, et les gestes qui
comptent n'y sont pas les mêmes. Ce qui se partage — le coffre, le
scellement, la mise en forme du texte — est importé plutôt que recopié.

Une session = un compte ouvert. Elle survit à une panne réseau : le cache
s'ouvre d'abord, le lien est tenté ensuite, et son échec ne fait que poser
`online = False`. Un fil déjà rapporté reste lisible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from script.todo.social.store import Store
from script.todo.todo_i18n import t

_logger = logging.getLogger(__name__)

# Billets qu'une passe rapporte, au plus. Une première passe sur un compte
# ancien remonterait sinon des années de fil en une fois, pour un écran qui
# n'en montre que le haut.
PAGES_PAR_PASSE = 5

# Le fil personnel, sous le même nom pour tous les réseaux : le cache range
# par nom de fil, et un nom par protocole y ferait deux fils pour une chose.
FIL_ACCUEIL = "home"

# Lignes chargées d'un coup dans la liste. Un fil se compte en dizaines de
# milliers de billets, et tout construire à chaque ouverture ferait attendre
# pour ce que personne ne fait défiler.
PAGE = 200


@dataclass
class FeedRef:
    """Un fil d'un compte, tel que l'arbre le désigne."""

    account_name: str
    feed_name: str
    display: str
    unseen: int


class Session:
    """Un compte ouvert : son cache, et son lien réseau s'il tient."""

    def __init__(
        self,
        account,
        store: Store,
        transport=None,
        error: str = "",
        token: str = "",
    ):
        self.account = account
        self.store = store
        self.transport = transport
        self.error = error
        self.token = token

    @property
    def online(self) -> bool:
        return self.transport is not None

    def peut_lire(self) -> bool:
        """Faux quand la PLATEFORME ne sert pas de fil.

        Ce n'est pas une panne et l'écran ne doit pas le montrer comme
        telle : certaines plateformes n'ouvrent la lecture d'un fil qu'à
        des applications qu'elles choisissent. Un compte pareil publie, et
        son fil reste vide pour toujours.
        """
        return self.account.peut_lire()

    def close(self) -> None:
        try:
            self.store.close()
        except Exception:
            # Fermer est un service rendu, pas une opération dont l'échec
            # doit empêcher de quitter l'écran.
            _logger.exception("fermeture du cache de %s", self.account.name)


def open_sessions(accounts, secrets=None, base=None) -> list:
    """Ouvre une session par compte. N'échoue jamais sur un compte.

    Un compte dont le cache refuse de s'ouvrir, ou dont le jeton manque,
    apparaît quand même dans l'arbre avec son erreur : le faire disparaître
    donnerait à croire qu'il n'est pas configuré.
    """
    from script.todo.social.store import resolve_mode

    sessions = []
    for account in accounts:
        if not account.enabled:
            continue
        store = None
        try:
            mode = resolve_mode(account)
            store = Store(account, mode=mode, secrets=secrets, base=base)
            store.open()
        except Exception as exc:
            _logger.exception("cache de %s", account.name)
            sessions.append(Session(account, store, None, error=str(exc)))
            continue
        jeton, transport, erreur = "", None, ""
        try:
            jeton = _jeton(account, secrets)
            transport = _transport(account, jeton)
        except Exception as exc:
            _logger.exception("lien de %s", account.name)
            erreur = str(exc)
        sessions.append(
            Session(account, store, transport, error=erreur, token=jeton)
        )
    return sessions


def _jeton(account, secrets) -> str:
    if secrets is None:
        return ""
    return secrets.get(account.secret_ref) or ""


def _transport(account, jeton: str):
    """Le transport de la plateforme du compte, ou None si elle n'en a pas.

    Une plateforme qui ne sert pas de fil n'a pas de transport de LECTURE à
    ouvrir ; elle en aura un pour publier. Rendre None plutôt que lever
    laisse le compte s'afficher.
    """
    if not jeton:
        return None
    if account.platform == "mastodon":
        from script.todo.social.mastodon import MastodonTransport

        return MastodonTransport(account, jeton)
    if account.platform == "bluesky":
        from script.todo.social.bluesky import BlueskyTransport

        # Le secret gardé pour ce réseau est un MOT DE PASSE
        # D'APPLICATION, non un jeton : c'est lui qui ouvre la session.
        return BlueskyTransport(account, jeton)
    if account.platform == "linkedin":
        from script.todo.social.linkedin import LinkedInTransport

        # Un transport quand même, bien que ce réseau ne serve aucun fil :
        # il sert à PUBLIER, et sans lui l'écran d'écriture se refuserait.
        return LinkedInTransport(account, jeton)
    return None


def feed_refs(sessions: list) -> list:
    """Les fils de tous les comptes, pour l'arbre."""
    refs = []
    for session in sessions:
        if session.store is None:
            continue
        for fil in session.store.feeds():
            refs.append(
                FeedRef(
                    account_name=session.account.name,
                    feed_name=fil["name"],
                    display=fil["display"] or fil["name"],
                    unseen=fil["unseen"] or 0,
                )
            )
    return refs


def sync_session(session: Session, pages: int = PAGES_PAR_PASSE) -> int:
    """Une passe sur le fil d'accueil. Rend le nombre de billets écrits.

    Reprend au CURSEUR gardé par le cache, et s'arrête soit quand
    l'instance n'annonce plus de suite, soit au bout de `pages` — une
    première passe sur un compte ancien remonterait sinon des années de fil
    pour un écran qui n'en montre que le haut.

    La pagination DESCEND vers le passé. Tant que le plafond interrompt la
    descente, le curseur la fait reprendre où elle en était, et les billets
    neufs du haut attendent qu'elle soit finie. L'instance cessant
    d'annoncer une suite, le curseur est effacé et la passe suivante repart
    du haut — un curseur gardé là ne désignerait plus rien à lire.

    Le curseur n'est écrit qu'APRÈS les billets de sa page : l'écrire avant
    ferait sauter cette page si le cache tombait entre les deux.
    """
    if not session.online or not session.peut_lire():
        return 0
    # Le nom du fil d'accueil est le même partout : c'est le cache qui le
    # porte, pas le protocole.
    fil_id = session.store.upsert_feed(FIL_ACCUEIL, t("social_feed_home"))
    etat = session.store.feed_state(FIL_ACCUEIL) or {}
    curseur = etat.get("cursor") or ""
    ecrits = 0
    for _ in range(max(1, pages)):
        billets, suite = session.transport.home_timeline(cursor=curseur)
        if billets:
            ecrits += session.store.upsert_posts(fil_id, billets)
        session.store.set_feed_state(FIL_ACCUEIL, cursor=suite or None)
        curseur = suite
        if not suite:
            break
    return ecrits


def run_tui(run_app: bool = True, sessions=None, base=None) -> None:
    """Ouvre l'écran des fils. `run_app=False` le construit sans le lancer,
    ce qui permet de vérifier qu'il se compose sans terminal."""
    try:
        from rich.text import Text
        from textual.app import App, ComposeResult
        from textual.binding import Binding
        from textual.containers import Container, Horizontal
        from textual.css.query import NoMatches
        from textual.screen import ModalScreen
        from textual.widgets import (
            DataTable,
            Footer,
            Header,
            Select,
            Static,
            TextArea,
            Tree,
        )
    except ImportError:
        print(t("social_err_textual_missing"))
        return

    from script.todo.mail import tui_text
    from script.todo.social.mastodon import (
        VISIBILITES,
        SocialError,
    )

    ADD_NOTHING = "__rien__"

    def _une_ligne(texte: str) -> str:
        """Le billet ramené à UNE ligne, pour la liste.

        Un billet porte des retours à la ligne ; les laisser passer ferait
        grandir la rangée et casserait l'alignement des colonnes.
        """
        return " ".join((texte or "").split())

    class ComposeScreen(ModalScreen):
        """Écrire un billet, et le publier.

        La CLÉ d'idempotence est tirée à l'ouverture et gardée tant que
        l'écran vit : un envoi qui échoue se rejoue avec la même, et
        l'instance rend alors le billet déjà posé au lieu d'en créer un
        second. C'est ce qui rend le bouton « envoyer » sûr à presser deux
        fois quand on ne sait pas si le premier est parti.
        """

        BINDINGS = [
            Binding("escape", "cancel", t("social_compose_cancel")),
            Binding("ctrl+s", "send", t("social_compose_send")),
        ]

        def __init__(self, session, repond_a: str = ""):
            super().__init__()
            self.session = session
            self.repond_a = repond_a
            from script.todo.social.mastodon import _cle_idempotence

            self.cle = _cle_idempotence()
            self.limite = 0

        def compose(self) -> ComposeResult:
            with Container(id="compose_box"):
                yield Static(t("social_compose_title"), id="compose_title")
                yield TextArea(id="compose_text")
                yield Select(
                    [(v, v) for v in VISIBILITES],
                    value="public",
                    id="compose_visibility",
                )
                yield Static("", id="compose_status")

        def on_mount(self) -> None:
            self.query_one("#compose_text", TextArea).focus()
            self.run_worker(self._demander_limite, thread=True)

        def _demander_limite(self) -> None:
            """La longueur permise vient de l'instance, pas d'une supposition.
            Demandée en fil de travail : l'écran doit s'ouvrir tout de suite."""
            try:
                limite = self.session.transport.limite_caracteres()
            except Exception:
                return
            self.app.call_from_thread(self._limite_connue, limite)

        def _limite_connue(self, limite: int) -> None:
            try:
                self.limite = limite
                self.query_one("#compose_title", Static).update(
                    f"{t('social_compose_title')}  ({limite})"
                )
            except NoMatches:
                # L'écran s'est refermé pendant l'aller-retour : il n'y a
                # plus rien à renseigner, et ce n'est pas une anomalie.
                return

        def action_cancel(self) -> None:
            self.dismiss(None)

        def action_send(self) -> None:
            texte = self.query_one("#compose_text", TextArea).text
            if not texte.strip():
                self._dire(t("social_compose_empty"))
                return
            if self.limite and len(texte) > self.limite:
                # Dit ICI plutôt que par un aller-retour refusé : la
                # personne corrige sans attendre le non de l'instance.
                self._dire(f"{t('social_compose_too_long')} {len(texte)}")
                return
            visibilite = self.query_one("#compose_visibility", Select).value
            self._dire(t("social_compose_sending"))
            self.run_worker(
                lambda: self._envoyer(texte, visibilite), thread=True
            )

        def _envoyer(self, texte: str, visibilite) -> None:
            try:
                billet = self.session.transport.publish(
                    texte,
                    cle=self.cle,
                    visibilite=visibilite or "public",
                    repond_a=self.repond_a,
                )
            except Exception as exc:
                _logger.exception(
                    "publication sur %s", self.session.account.name
                )
                self.app.call_from_thread(self._refus, exc)
                return
            self.app.call_from_thread(self.dismiss, billet)

        def _refus(self, exc) -> None:
            """Dit ce qui s'est passé et LAISSE l'écran ouvert, avec son
            texte et sa clé.

            Un doute ne se dit pas comme un refus. Sur les réseaux qui
            offrent de quoi rejouer, presser à nouveau est sûr et la phrase
            y invite. Sur celui qui n'offre rien, le billet est peut-être
            déjà parti : la phrase dit alors d'aller vérifier, parce que
            presser à nouveau publierait peut-être deux fois.
            """
            from script.todo.social.linkedin import SocialUnknownOutcome

            if isinstance(exc, SocialUnknownOutcome):
                self._dire(str(exc))
                return
            self._dire(f"{t('social_compose_refused')} {exc}")

        def _dire(self, texte: str) -> None:
            try:
                self.query_one("#compose_status", Static).update(Text(texte))
            except NoMatches:
                return

    class SocialApp(App):
        CSS = """
        #feeds { width: 30; }
        #list { width: 1fr; }
        #preview { width: 1fr; padding: 0 1; }
        #compose_box { width: 80%; height: 80%; background: $panel; }
        #compose_text { height: 1fr; }
        """
        BINDINGS = [
            Binding("q", "quit", t("social_quit_binding")),
            Binding("r", "sync_current", t("social_sync_binding")),
            Binding("R", "sync_all", t("social_sync_all_binding")),
            Binding("c", "compose", t("social_compose_binding")),
            Binding("a", "reply", t("social_reply_binding")),
            Binding("s", "mark_seen", t("social_seen_binding")),
            Binding("u", "mark_unseen", t("social_unseen_binding")),
            Binding("M", "mark_all_seen", t("social_all_seen_binding")),
        ]

        def __init__(self, sessions):
            super().__init__()
            self.sessions = sessions
            self.refs = []
            self.metas = []
            self.current_ref = None
            self.status = ""

        def compose(self) -> ComposeResult:
            yield Header()
            with Horizontal():
                yield Tree(t("social_accounts"), id="feeds")
                yield DataTable(id="list")
                yield Static("", id="preview")
            yield Static("", id="status")
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#list", DataTable)
            table.cursor_type = "row"
            table.add_columns(t("social_col_author"), t("social_col_text"))
            self.reload_feeds()

        # -- L'arbre ----------------------------------------------------

        def reload_feeds(self) -> None:
            self.refs = feed_refs(self.sessions)
            arbre = self.query_one("#feeds", Tree)
            arbre.clear()
            par_compte = {}
            for ref in self.refs:
                par_compte.setdefault(ref.account_name, []).append(ref)
            for session in self.sessions:
                marque = "" if session.online else " ⚠"
                noeud = arbre.root.add(
                    f"{session.account.name}{marque}", expand=True
                )
                fils = par_compte.get(session.account.name, [])
                if not fils and not session.peut_lire():
                    # Ce compte n'aura JAMAIS de fil : sa plateforme n'en
                    # sert pas. Le dire vaut mieux qu'un nœud vide, qui se
                    # lit comme une synchronisation qui n'a pas eu lieu.
                    noeud.add_leaf(t("social_no_feed"), data=ADD_NOTHING)
                for ref in fils:
                    libelle = ref.display
                    if ref.unseen:
                        libelle = f"{libelle}  {ref.unseen}"
                    noeud.add_leaf(libelle, data=ref)
            arbre.root.expand()
            if self.current_ref is None and self.refs:
                self.select_ref(self.refs[0])
            else:
                self.refresh_current()

        def refresh_feed_counts(self) -> None:
            """Réécrit les compteurs EN PLACE, sans rebâtir l'arbre.

            Rebâtir ramènerait son curseur à la racine : marquer un billet
            lu au clavier ne doit pas déplacer le fil qu'on avait choisi.
            """
            try:
                arbre = self.query_one("#feeds", Tree)
            except NoMatches:
                return
            frais = {
                (r.account_name, r.feed_name): r.unseen
                for r in feed_refs(self.sessions)
            }
            for compte in arbre.root.children:
                for feuille in compte.children:
                    ref = feuille.data
                    if not isinstance(ref, FeedRef):
                        continue
                    unseen = frais.get((ref.account_name, ref.feed_name), 0)
                    if unseen == ref.unseen:
                        continue
                    ref.unseen = unseen
                    feuille.set_label(
                        f"{ref.display}  {unseen}" if unseen else ref.display
                    )

        def on_tree_node_selected(self, event) -> None:
            if isinstance(event.node.data, FeedRef):
                self.select_ref(event.node.data)

        def session_for(self, nom: str):
            return next(
                (s for s in self.sessions if s.account.name == nom), None
            )

        # -- La liste ---------------------------------------------------

        def select_ref(self, ref: FeedRef) -> None:
            self.current_ref = ref
            session = self.session_for(ref.account_name)
            etat = session.store.feed_state(ref.feed_name) if session else None
            self.metas = (
                session.store.list_posts(etat["id"], limit=PAGE)
                if etat
                else []
            )
            self.refresh_list()
            self.refresh_feed_counts()

        def refresh_current(self) -> None:
            if self.current_ref is not None:
                self.select_ref(self.current_ref)

        def refresh_list(self) -> None:
            table = self.query_one("#list", DataTable)
            table.clear()
            for meta in self.metas:
                marque = "" if meta.seen else "●"
                auteur = meta.author_name or meta.author
                table.add_row(
                    f"{marque} {auteur}".strip(),
                    _une_ligne(meta.text),
                )
            self.show_preview()

        def current_meta(self):
            table = self.query_one("#list", DataTable)
            ligne = table.cursor_row
            if ligne is None or ligne >= len(self.metas):
                return None
            return self.metas[ligne]

        def on_data_table_row_highlighted(self, event) -> None:
            self.show_preview()

        # -- L'aperçu ---------------------------------------------------

        def show_preview(self) -> None:
            try:
                apercu = self.query_one("#preview", Static)
            except NoMatches:
                return
            meta = self.current_meta()
            if meta is None:
                apercu.update("")
                return
            apercu.update(self._entete(meta) + Text(meta.text or ""))

        @staticmethod
        def _entete(meta) -> "Text":
            """L'en-tête d'un billet. Un `Text`, PAS une chaîne de balisage :
            l'auteur et le texte viennent du réseau, donc de n'importe qui, et
            un crochet y serait analysé comme une balise."""
            entete = Text()
            for etiquette, valeur in (
                (t("social_from"), meta.author_name or meta.author),
                (t("social_handle"), meta.author),
                (
                    t("social_date"),
                    tui_text.format_date_full(meta.created_at),
                ),
            ):
                entete.append(f"{etiquette} ", style="bold")
                entete.append(f"{valeur}\n")
            if meta.boost_of:
                entete.append(f"{t('social_boost')}\n")
            for piece in meta.media or []:
                entete.append(
                    f"  📎 {piece.kind} {piece.description}\n".rstrip() + "\n"
                )
            entete.append("\n")
            return entete

        def set_status(self, texte: str) -> None:
            self.status = texte
            try:
                self.query_one("#status", Static).update(Text(texte))
            except NoMatches:
                return

        # -- Les gestes -------------------------------------------------

        def action_sync_current(self) -> None:
            if self.current_ref is None:
                return
            session = self.session_for(self.current_ref.account_name)
            if session is None:
                return
            self.run_worker(lambda: self._sync([session]), thread=True)

        def action_sync_all(self) -> None:
            self.run_worker(lambda: self._sync(self.sessions), thread=True)

        def _sync(self, sessions) -> None:
            total, souci = 0, ""
            for session in sessions:
                try:
                    total += sync_session(session)
                except SocialError as exc:
                    _logger.exception("passe sur %s", session.account.name)
                    souci = souci or str(exc)
            self.call_from_thread(self._synchronise, total, souci)

        def _synchronise(self, total: int, souci: str) -> None:
            self.set_status(souci or f"{t('social_sync_done')} {total}")
            self.reload_feeds()

        def _marquer(self, seen: bool) -> None:
            meta = self.current_meta()
            if meta is None or self.current_ref is None:
                return
            session = self.session_for(self.current_ref.account_name)
            etat = session.store.feed_state(self.current_ref.feed_name)
            if etat is None:
                return
            session.store.mark_seen(etat["id"], meta.post_id, seen)
            self.refresh_current()

        def action_mark_seen(self) -> None:
            self._marquer(True)

        def action_mark_unseen(self) -> None:
            self._marquer(False)

        def action_mark_all_seen(self) -> None:
            if self.current_ref is None:
                return
            session = self.session_for(self.current_ref.account_name)
            etat = session.store.feed_state(self.current_ref.feed_name)
            if etat is None:
                return
            combien = session.store.mark_all_seen(etat["id"])
            self.set_status(f"{t('social_all_seen_done')} {combien}")
            self.refresh_current()

        def action_compose(self) -> None:
            self._ecrire()

        def action_reply(self) -> None:
            meta = self.current_meta()
            self._ecrire(meta.post_id if meta else "")

        def _ecrire(self, repond_a: str = "") -> None:
            if self.current_ref is None:
                self.set_status(t("social_compose_no_account"))
                return
            session = self.session_for(self.current_ref.account_name)
            if session is None or not session.online:
                self.set_status(t("social_compose_offline"))
                return
            if not session.account.peut_publier():
                self.set_status(t("social_compose_cannot"))
                return

            def publie(billet):
                if billet is None:
                    return
                self.set_status(t("social_compose_done"))

            self.push_screen(ComposeScreen(session, repond_a), publie)

    app = SocialApp(sessions or [])
    if run_app:
        app.run()
