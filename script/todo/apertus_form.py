#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installation d'Apertus en plein écran : une étape par bloc.

Le rendu texte et ce rendu-ci jouent la MÊME liste d'étapes et s'arrêtent au
même endroit ; seul l'affichage change. Les deux tirent leur état d'un
dictionnaire produit sans entrée-sortie, ce qui est la seule façon de
garantir qu'ils ne décrivent jamais deux installations différentes.

Les commandes sont lancées ICI, par `Popen`, et non par le lanceur du CLI :
celui-ci écrit sur la sortie standard, que Textual possède pendant qu'il
dessine. Une ligne imprimée par-dessous déchire l'écran.

L'écran est SÉQUENTIEL et s'arrête à la première étape critique en échec.
C'est ce qui le distingue du suivi de déploiement, qui mène des travaux
parallèles et les mène tous : ici, l'étape qui vérifie la version du moteur
précède celle qui télécharge le modèle, et poursuivre après son échec
coûterait plusieurs gigaoctets pour rien.

Un bloc reste DÉPLIÉ tant que son étape tourne, se replie dès qu'elle passe,
et reste ouvert si elle échoue — puisque c'est celui-là qu'on veut lire.
"""
from __future__ import annotations

import time

from script.todo.todo_i18n import t


def run_apertus_progress(etapes, depart, on_step=None, run_app: bool = True):
    """Joue `etapes` à partir du rang `depart`, un bloc repliable par étape.

    `etapes` est une liste d'objets portant `cle`, `label`, `commande`,
    `deja_fait` et `critique`. `on_step(rang, cle, code, texte, secondes)`
    est appelé après chaque étape, depuis le fil de travail, pour que la
    progression descende sur le disque au fur et à mesure plutôt qu'à la
    fermeture de l'écran.

    Rend le rang de l'étape en échec, ou 0 si tout est passé. `run_app=False`
    rend l'application sans la lancer, pour un test sans terminal.
    """
    import subprocess

    from textual.app import App, ComposeResult
    from textual.containers import VerticalScroll
    from textual.widgets import Collapsible, Footer, Header, RichLog, Static

    resultat = {"echec": 0}

    def slug(cle):
        """Identifiant de widget : Textual refuse un point ou un tiret en
        tête, et une clé d'étape n'est pas garantie d'en être exempte."""
        return "e_" + "".join(c if c.isalnum() else "_" for c in cle)

    def lance(commande):
        """Une commande, son code de retour et sa sortie fusionnée."""
        try:
            proc = subprocess.Popen(
                commande,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                stdin=subprocess.DEVNULL,
            )
        except OSError as souci:
            return 1, str(souci)
        sortie, _ = proc.communicate()
        return proc.returncode, sortie or ""

    class Progress(App):
        CSS = """
        #blocs { height: 1fr; }
        RichLog { height: 12; border: solid $panel; }
        #resume { height: auto; color: $accent; padding: 0 1; }
        """
        BINDINGS = [("q", "quit", t("Quit"))]

        def __init__(self):
            super().__init__()
            self._t0 = time.time()

        def compose(self) -> ComposeResult:
            yield Header()
            with VerticalScroll(id="blocs"):
                for rang, etape in enumerate(etapes, 1):
                    etat = "⬜" if rang >= depart else "✅"
                    with Collapsible(
                        title=f"{etat} {rang} {t(etape.label)}",
                        collapsed=rang < depart,
                        id=slug(etape.cle),
                    ):
                        yield RichLog(
                            id=f"log_{slug(etape.cle)}",
                            highlight=False,
                            markup=False,
                            max_lines=2000,
                        )
            yield Static("", id="resume")
            yield Footer()

        def on_mount(self):
            self.run_worker(self._jouer, thread=True)

        def _titre(self, etape, rang, icone):
            bloc = self.query_one(f"#{slug(etape.cle)}", Collapsible)
            bloc.title = f"{icone} {rang} {t(etape.label)}"

        def _ecrire(self, etape, texte):
            if not texte:
                return
            journal = self.query_one(f"#log_{slug(etape.cle)}", RichLog)
            for ligne in texte.splitlines():
                journal.write(ligne)

        def _replier(self, etape, ferme):
            self.query_one(f"#{slug(etape.cle)}", Collapsible).collapsed = (
                ferme
            )

        def _jouer(self):
            """Le fil de travail : les étapes dans l'ordre, arrêt sur échec.

            Chaque retouche d'un widget repasse par `call_from_thread` —
            Textual dessine sur son propre fil et ne tolère pas qu'un autre
            y touche.
            """
            for rang, etape in enumerate(etapes, 1):
                if rang < depart:
                    continue
                self.call_from_thread(self._titre, etape, rang, "⏳")
                debut = time.time()
                if etape.deja_fait:
                    fait, _ = lance(etape.deja_fait)
                    if fait == 0:
                        self.call_from_thread(self._titre, etape, rang, "⏭")
                        self.call_from_thread(self._replier, etape, True)
                        if on_step:
                            on_step(rang, etape.cle, 0, "", 0)
                        continue
                code, texte = lance(etape.commande)
                secondes = int(time.time() - debut)
                self.call_from_thread(self._ecrire, etape, texte)
                if on_step:
                    on_step(rang, etape.cle, code, texte, secondes)
                if code == 0:
                    self.call_from_thread(self._titre, etape, rang, "✅")
                    self.call_from_thread(self._replier, etape, True)
                    continue
                if not etape.critique:
                    self.call_from_thread(self._titre, etape, rang, "⚠️")
                    continue
                self.call_from_thread(self._titre, etape, rang, "⛔")
                self.call_from_thread(self._replier, etape, False)
                resultat["echec"] = rang
                self.call_from_thread(
                    self._conclure,
                    t("Step %s/%s (%s) failed with code %s.")
                    % (rang, len(etapes), t(etape.label), code),
                )
                return
            self.call_from_thread(
                self._conclure, t("Apertus answers on this target.")
            )

        def _conclure(self, message):
            ecoule = int(time.time() - self._t0)
            self.query_one("#resume", Static).update(
                f"{message}   {ecoule // 60}:{ecoule % 60:02d}"
                f"   ({t('Quit')} : q)"
            )

    app = Progress()
    # Le rang en échec vit dans une fermeture, que l'application ne porte pas.
    # L'y accrocher est la seule façon de le lire quand `run_app=False` rend
    # l'application au lieu de la faire tourner.
    app.resultat = resultat
    if not run_app:
        return app
    app.run()
    return resultat["echec"]
