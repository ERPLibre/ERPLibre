#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une conversation avec un modèle, en plein écran.

Le pendant de la boucle en ligne du menu, et rien de plus : les deux parlent
à la même `Conversation`, acceptent les mêmes commandes en barre oblique et
gardent le même historique. Ce qui change est que la réponse se peint dans une
bulle qui grandit, et que l'annulation n'attend pas la fin.

TROIS CHOSES QUE CE MODULE FAIT ET QU'AUCUN AUTRE ÉCRAN DU DÉPÔT NE FAIT.

**Le travail vit sur un fil séparé.** Un appel au modèle dure des secondes à
des minutes ; le tenir sur le fil de dessin figerait l'écran, la saisie et
l'annulation avec lui. D'où `run_worker(thread=True)`, et `call_from_thread`
pour chaque retouche de widget — la bibliothèque dessine sur son propre fil et
ne tolère pas qu'un autre y touche.

**L'annulation lève `KeyboardInterrupt`, pas `Interrupted`.** Le lecteur de
flux n'attrape que la première, et c'est en l'attrapant qu'il FERME la socket
avant de relever `Interrupted` avec le texte déjà reçu. Lever `Interrupted`
directement depuis le rappel la ferait échapper au lecteur, et la socket
resterait ouverte derrière une réponse abandonnée.

**Le serveur et la clé arrivent construits.** La `Conversation` est passée
faite : le paquet de l'assistant n'a pas le droit d'importer le CLI, et ce
module n'a pas à savoir d'où vient un serveur retenu ni où dort une clé.

Le texte est peint avec le balisage DÉSACTIVÉ. Une réponse de modèle contient
des crochets — un extrait de code, une liste — et la bibliothèque les lirait
comme des étiquettes de couleur, ce qui avale le texte au lieu de l'afficher.
"""
from __future__ import annotations

from script.todo.todo_i18n import t

# Ce qui précède chaque tour dans le fil. Le symbole distingue les deux voix
# sans dépendre d'une couleur, qui se perd sur un terminal monochrome.
MARQUE_HUMAIN = "▸"
MARQUE_MODELE = "◂"


def run_chat(
    conversation,
    invite,
    *,
    on_save=None,
    aide=(),
    run_app: bool = True,
):
    """Ouvre la conversation en plein écran.

    `conversation` est une `chat.Conversation` déjà construite. `invite` est la
    ligne d'état — serveur, modèle, hébergement — affichée en titre.
    `on_save()` écrit la transcription ; `aide` est une suite de
    `(commande, explication)` pour `/?`.

    Rend le nombre de tours de la conversation à la fermeture. `run_app=False`
    rend l'application sans la lancer, pour un contrôle sans terminal.
    """
    from textual.app import App, ComposeResult
    from textual.containers import VerticalScroll
    from textual.widgets import Footer, Header, Input, Static

    from script.todo.assistant import chat as llm_chat

    class Chat(App):
        CSS = """
        #fil { height: 1fr; padding: 0 1; }
        .humain { color: $accent; margin-top: 1; }
        .modele { margin-top: 0; }
        .note { color: $text-muted; margin-top: 1; }
        #saisie { dock: bottom; }
        """
        BINDINGS = [
            # L'annulation et la sortie sont séparées : couper une réponse
            # trop longue est le geste courant, quitter l'est moins.
            ("ctrl+c", "couper", t("Cancel")),
            ("ctrl+s", "sauver", t("Save the conversation")),
            ("ctrl+n", "neuf", t("New conversation")),
            ("ctrl+q", "quit", t("Quit")),
        ]

        def __init__(self):
            super().__init__()
            self.title = invite
            # Vrai pendant qu'une réponse arrive. Ce qui décide si Ctrl+C
            # coupe la réponse ou ne fait rien.
            self._occupe = False
            self._annule = False
            self._tampon = ""
            self._bulle = None

        def compose(self) -> ComposeResult:
            yield Header()
            yield VerticalScroll(id="fil")
            yield Input(placeholder=t("Free question"), id="saisie")
            yield Footer()

        def on_mount(self):
            self._noter(
                t(
                    "The history lives in memory and dies with this menu."
                    " /save writes it to a file."
                )
            )
            self.query_one("#saisie", Input).focus()

        # ---- peinture ----

        def _ajouter(self, texte, classe):
            """Une bulle de plus au bas du fil, et le fil suit."""
            fil = self.query_one("#fil", VerticalScroll)
            bulle = Static(texte, markup=False, classes=classe)
            fil.mount(bulle)
            fil.scroll_end(animate=False)
            return bulle

        def _noter(self, texte):
            self._ajouter(texte, "note")

        def _peindre(self):
            """Redessine la bulle en cours avec ce qui est arrivé."""
            if self._bulle is None:
                return
            self._bulle.update(f"{MARQUE_MODELE} {self._tampon}")
            self.query_one("#fil", VerticalScroll).scroll_end(animate=False)

        # ---- envoi ----

        def _envoyer(self, texte):
            self._occupe = True
            self._annule = False
            self._tampon = ""
            self._ajouter(f"{MARQUE_HUMAIN} {texte}", "humain")
            self._bulle = self._ajouter(f"{MARQUE_MODELE} ", "modele")
            self.query_one("#saisie", Input).disabled = True
            self.run_worker(
                lambda: self._travail(texte), thread=True, exclusive=True
            )

        def _travail(self, texte):
            """Le fil de travail : l'appel au modèle, fragment par fragment."""

            def fragment(morceau):
                # `KeyboardInterrupt` et non `Interrupted` : c'est la
                # première que le lecteur de flux attrape, et c'est en
                # l'attrapant qu'il ferme la socket.
                if self._annule:
                    raise KeyboardInterrupt
                self._tampon += morceau
                self.call_from_thread(self._peindre)

            tour = conversation.ask(texte, on_chunk=fragment)
            self.call_from_thread(self._fini, tour)

        def _fini(self, tour):
            self._occupe = False
            if tour.role == "error":
                if self._bulle is not None:
                    self._bulle.remove()
                self._bulle = None
                self._noter(f"⚠ {tour.text}")
            else:
                # Le tour rendu fait foi : un dos d'appel qui ne diffuse pas
                # n'a rempli aucun tampon, et la bulle serait restée vide.
                self._tampon = tour.text or self._tampon
                self._peindre()
                if tour.interrupted:
                    self._noter(f"⏹ {t('answer interrupted')}")
            self._bulle = None
            saisie = self.query_one("#saisie", Input)
            saisie.disabled = False
            saisie.focus()

        # ---- commandes ----

        def on_input_submitted(self, evenement):
            texte = (evenement.value or "").strip()
            evenement.input.value = ""
            if not texte or self._occupe:
                return
            commande, reste = llm_chat.parse_command(texte)
            if commande == "/q":
                self.exit()
                return
            if commande == "/?":
                for nom, explication in aide:
                    self._noter(f"  {nom}  {explication}")
                return
            if commande == "/new":
                self.action_neuf()
                return
            if commande == "/save":
                self.action_sauver()
                return
            if commande == "/ctx":
                for message in conversation.last_sent:
                    self._noter(f"  [{message['role']}] {message['content']}")
                return
            if commande and not reste:
                # Une commande que cet écran ne sert pas — celles qui
                # ouvraient un autre menu n'ont pas de sens ici.
                self._noter(t("Command not found !"))
                return
            self._envoyer(reste if commande else texte)

        def action_couper(self):
            """Coupe la réponse en cours ; ne quitte jamais.

            Le drapeau est lu par le rappel de fragment, sur l'autre fil : la
            coupure prend effet au prochain morceau, et le texte déjà reçu est
            gardé puisqu'il a été payé.
            """
            if self._occupe:
                self._annule = True
                return
            self._noter(t("Nothing to do."))

        def action_sauver(self):
            if on_save is None:
                self._noter(t("Nothing to do."))
                return
            on_save()

        def action_neuf(self):
            jetes = conversation.reset()
            self._noter(f"{jetes} {t('turns dropped')}")

    app = Chat()
    if not run_app:
        return app
    app.run()
    return len(conversation.turns)
