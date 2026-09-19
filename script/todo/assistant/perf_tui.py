#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran vivant d'une conversation : ce qu'on demande, ce que ça coûte.

Le calcul est séparé de l'affichage, comme dans l'écran des agents. Les
faiseuses de lignes rendent des chaînes et se vérifient sans terminal ; la
classe Textual ne fait plus que les poser. Ce partage est ce qui permet de
défendre une colonne, une unité ou un cas vide sans monter un écran.

**Le flux vit sur un FIL, jamais sur la boucle d'événements.** Une génération
dure des secondes à des minutes ; la mener sur la boucle gèle l'écran entier,
touches comprises, et rien ne dirait qu'il est vivant. Les fragments arrivent
donc par un travailleur et reviennent par `call_from_thread`, qui est le seul
point autorisé à toucher un widget.

**Ce qui s'affiche pendant, et ce qui s'affiche après, ne sont pas la même
mesure.** Pendant, on compte les FRAGMENTS reçus et le temps écoulé : deux
grandeurs que cette machine-ci observe. Le compte de JETONS vient du serveur
et n'arrive qu'à la fin, dans une trame que certains logiciels n'envoient que
si on l'a demandée. Afficher un débit en jetons avant de l'avoir serait une
extrapolation présentée comme une lecture, et l'écran des agents a déjà payé
cette confusion : un tableau qui mélange une mesure et une approximation sans
le dire est pire qu'un tableau vide.

**Une absence s'affiche en tiret.** Un serveur qui ne rend aucun compte n'a
pas répondu « zéro ». Le tiret est ce qui empêche une moyenne de le compter.
"""
from __future__ import annotations

from script.todo.todo_i18n import t

# Les colonnes du tableau des tours, dans l'ordre d'importance. Le rang et la
# durée passent d'abord : ils situent le tour et disent ce qu'il a coûté au
# lecteur, là où les comptes de jetons décrivent la machine.
COLONNES: tuple[tuple[str, str], ...] = (
    ("rang", "turn"),
    ("duree", "duration"),
    ("invite", "prompt"),
    ("reponse", "answer"),
    ("debit", "tok/s"),
    ("premier", "first token"),
    ("fin", "end"),
)

# La largeur qu'on prête à une colonne pour décider combien tiennent. Le même
# nombre que l'écran des agents : les colonnes y sont du même genre, courtes
# et numériques.
COLONNE_LARGEUR = 12

# Ce qu'on affiche à la place d'un nombre que personne n'a mesuré. Un zéro
# dirait que le serveur a répondu zéro.
INCONNU = "—"

# Sous cette durée, la seconde arrondit à zéro et ment : un tour servi depuis
# un cache se compte en dizaines de millisecondes.
SEUIL_MS = 1.0


def secondes(valeur) -> str:
    """« 1 m 12 », « 12.4 s », « 340 ms », ou le tiret. Fonction PURE.

    Le palier des millisecondes existe pour la même raison que dans l'écran
    des agents : un délai de premier jeton se compte en dizaines de
    millisecondes sur un modèle chargé, et l'arrondi à la seconde y afficherait
    « 0 s », qui est le mensonge d'un zéro mis à la place d'une valeur.
    """
    if valeur is None:
        return INCONNU
    try:
        valeur = float(valeur)
    except (TypeError, ValueError):
        return INCONNU
    if valeur < 0:
        return INCONNU
    if valeur < SEUIL_MS:
        return f"{int(round(valeur * 1000))} ms"
    if valeur >= 60:
        return f"{int(valeur) // 60} m {int(valeur) % 60:02d}"
    return f"{valeur:.1f} s"


def compte(valeur) -> str:
    """Un nombre de jetons, ou le tiret. Fonction PURE."""
    if not isinstance(valeur, int) or isinstance(valeur, bool):
        return INCONNU
    return str(valeur)


def debit(valeur) -> str:
    """Un débit en jetons par seconde, ou le tiret. Fonction PURE."""
    if valeur is None:
        return INCONNU
    try:
        return f"{float(valeur):.1f}"
    except (TypeError, ValueError):
        return INCONNU


def _fin(mesure) -> str:
    """La raison de fin, celle qui compte d'abord.

    Une interruption et une erreur priment sur ce que le serveur annonce :
    un tour coupé à la main porte souvent « stop » dans ses faits, et le
    lecteur veut savoir que c'est LUI qui a coupé.
    """
    if getattr(mesure, "erreur", ""):
        return t("error")
    if getattr(mesure, "interrompu", False):
        return t("cut")
    return getattr(mesure, "fin", "") or INCONNU


def lignes(mesures) -> list[dict]:
    """Une ligne de tableau par tour. Fonction PURE.

    Rend des dictionnaires de CHAÎNES, plus une clé « cle » distincte des
    colonnes affichées. La clé est le RANG et jamais l'heure : deux tours
    dans la même seconde sont l'ordinaire d'une conversation, et une clé en
    double lève dans le tableau — ce qui ferme l'application entière, et non
    la seule rangée fautive.
    """
    rendues = []
    for mesure in mesures or ():
        rendues.append(
            {
                "cle": str(getattr(mesure, "rang", 0)),
                "rang": str(getattr(mesure, "rang", 0)),
                "duree": secondes(getattr(mesure, "duree", None)),
                "invite": compte(getattr(mesure, "invite", None)),
                "reponse": compte(getattr(mesure, "reponse", None)),
                "debit": debit(getattr(mesure, "debit", None)),
                "premier": secondes(getattr(mesure, "premier", None)),
                "fin": _fin(mesure),
            }
        )
    return rendues


def colonnes_visibles(largeur_ecran, colonnes=None) -> tuple:
    """Les colonnes qui tiennent, dans l'ordre d'importance. Fonction PURE.

    Toujours au moins les deux premières : un tableau qui ne dirait ni de
    quel tour ni de quelle durée il parle ne dirait rien, et mieux vaut alors
    déborder et se faire défiler.
    """
    colonnes = colonnes or COLONNES
    combien = max(2, int(largeur_ecran or 0) // COLONNE_LARGEUR)
    return tuple(colonnes[:combien])


def entete(serveur, outil="") -> str:
    """La ligne qui dit à qui l'on parle. Fonction PURE.

    Le modèle y figure parce que c'est lui qui explique les chiffres : deux
    tours du même serveur sur deux modèles ne se comparent pas.
    """
    if serveur is None:
        return t("no server yet")
    logiciel = getattr(serveur, "software", "") or INCONNU
    modele = getattr(serveur, "model", "") or INCONNU
    part = f"{logiciel} · {modele}"
    return f"{part} · {outil}" if outil else part


def accord(nombre, singulier, pluriel) -> str:
    """« 1 tour » ou « 3 tours » : le nombre, et le nom qui s'accorde.

    Le français comme l'anglais accordent le nom sur le nombre, et une ligne
    de résumé qui annonce « 1 tours » se lit comme un défaut de l'outil —
    c'est alors la seule chose qu'on retienne de la ligne.
    """
    return f"{nombre} {t(singulier if abs(nombre) == 1 else pluriel)}"


def resume(mesures) -> str:
    """Le total de la séance, en une ligne. Fonction PURE.

    Les tours dont le serveur ne rend aucun compte sont EXCLUS du total de
    jetons, et le résumé dit combien ils sont : un total qui porte sur une
    partie des tours, sans dire laquelle, se lit comme un total sur
    l'ensemble.
    """
    mesures = list(mesures or ())
    if not mesures:
        return t("no turn yet")
    total = sum(float(getattr(m, "duree", 0) or 0) for m in mesures)
    comptes = [
        getattr(m, "reponse", None)
        for m in mesures
        if isinstance(getattr(m, "reponse", None), int)
    ]
    ligne = "%s · %s" % (
        accord(len(mesures), "turn", "turns"),
        t("%s total") % secondes(total),
    )
    if comptes:
        ligne += " · " + accord(sum(comptes), "token", "tokens")
    manquants = len(mesures) - len(comptes)
    if manquants:
        ligne += " · " + t("%s without a count") % manquants
    return ligne


def pied(mesure) -> str:
    """Le pied d'une réponse, à l'invite texte. Fonction PURE.

    Il dit ce que le tour a coûté sans qu'on ait à ouvrir un écran. Le délai
    du premier jeton n'y figure que s'il existe : un envoi d'un seul bloc n'en
    a pas, et un zéro y ferait croire à une réponse instantanée.
    """
    parts = [secondes(getattr(mesure, "duree", None))]
    reponse = getattr(mesure, "reponse", None)
    if isinstance(reponse, int):
        parts.append(accord(reponse, "token", "tokens"))
    if getattr(mesure, "debit", None) is not None:
        parts.append(t("%s tok/s") % debit(mesure.debit))
    if getattr(mesure, "premier", None) is not None:
        parts.append(t("first at %s") % secondes(mesure.premier))
    return " · ".join(parts)


# Ce qui ouvre une question dans la transcription. Le même chevron que
# l'invite texte : l'écran et l'invite montrent la même conversation, et deux
# marques différentes feraient croire à deux fils.
MARQUE_QUESTION = "▸ "


def echange(turns, question="", reponse="") -> str:
    """La conversation, telle qu'elle se lit. Fonction PURE.

    `turns` sont les tours déjà clos, en couples question-réponse ; `question`
    et `reponse` portent celui qui arrive, et la réponse y grandit à chaque
    fragment.

    Les durées disent ce qu'un tour a coûté, jamais ce qui s'est dit : un
    écran qui ne montrerait que des chiffres obligerait à quitter pour relire
    la réponse qu'on vient de demander, et l'historique meurt avec le menu.

    Un tour COUPÉ garde son texte et se marque : ce qui est arrivé a été
    payé, et le lire comme une réponse entière ferait croire le modèle plus
    bref qu'il n'est.
    """
    parties = []
    for tour in turns or ():
        role = getattr(tour, "role", "")
        texte = getattr(tour, "text", "") or ""
        if role == "user":
            parties.append(f"{MARQUE_QUESTION}{texte}")
        elif role == "assistant":
            marque = (
                f"  [{t('cut')}]"
                if getattr(tour, "interrupted", False)
                else ""
            )
            parties.append(f"{texte}{marque}")
    if question:
        parties.append(f"{MARQUE_QUESTION}{question}")
    if reponse:
        parties.append(reponse)
    return "\n\n".join(parties)


def en_cours(fragments, caracteres, ecoule, premier) -> str:
    """Ce qu'on peut dire PENDANT que la réponse arrive. Fonction PURE.

    Trois grandeurs, et pas une de plus : les fragments reçus, les caractères
    reçus et le temps écoulé. Les trois s'observent d'ici. Le compte de
    JETONS n'en fait pas partie — il vient du serveur, à la fin, et une règle
    de trois sur les fragments l'approcherait sans être lui.
    """
    parts = [
        accord(int(fragments or 0), "fragment", "fragments"),
        accord(int(caracteres or 0), "character", "characters"),
        secondes(ecoule),
    ]
    if premier is not None:
        parts.append(t("first at %s") % secondes(premier))
    return " · ".join(parts)


# La cadence du rafraîchissement du compteur pendant une génération. Elle ne
# lit rien : elle redessine le temps écoulé, qui avance même quand aucun
# fragment n'arrive — et c'est précisément quand rien n'arrive qu'un écran
# figé se distingue mal d'un écran mort.
PAS = 0.2


def run_tui(
    conversation,
    serveur,
    *,
    mesures=None,
    outil="",
    seance="",
    depart=0,
    journal=None,
    horloge=None,
    run_app: bool = True,
):
    """L'écran. `run_app=False` rend l'application sans la lancer, pour test.

    `mesures` est la liste des tours DÉJÀ joués ; l'écran y ajoute les siens,
    donc elle est partagée avec l'invite texte et la séance garde une seule
    suite de rangs. `journal` écrit une mesure et vaut `mesure.ecrire` par
    défaut ; `horloge` est monotone et s'injecte pour qu'un test avance le
    temps sans attendre.

    Rien dans le montage ne touche le réseau : l'écran s'ouvre sur ce qui est
    déjà mesuré, et la première requête part d'une question tapée.
    """
    import time

    from textual import work
    from textual.app import App, ComposeResult
    from textual.containers import VerticalScroll
    from textual.widgets import DataTable, Footer, Header, Input, Static

    from script.todo.assistant import mesure as ms

    mesures = [] if mesures is None else mesures
    journal = ms.ecrire if journal is None else journal
    horloge = time.monotonic if horloge is None else horloge

    class Perf(App):
        """Le tableau des tours, le flux en cours, et la question suivante."""

        CSS = """
        #entete, #resume, #etat { height: auto; padding: 0 1; }
        #echange { height: auto; padding: 0 1; }
        #defile { height: 1fr; }
        DataTable { height: auto; max-height: 40%; }
        """

        # Des touches que la SAISIE ne consomme pas. Elle garde le focus
        # pendant toute la vie de l'écran — c'est de là qu'on pose ses
        # questions — donc une lettre nue n'atteint jamais un raccourci : elle
        # s'écrit dans le champ, et le raccourci passe pour mort.
        BINDINGS = [
            ("escape", "quit", t("back")),
            ("ctrl+t", "durees", t("timings")),
            ("ctrl+c", "interrompre", t("interrupt")),
        ]

        def __init__(self):
            super().__init__()
            self._colonnes = ()
            self._monte = False
            self._occupe = False
            self._debut = 0.0
            self._premier = None
            self._fragments = 0
            self._texte = ""
            self._question = ""
            self._rang = depart

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static(entete(serveur, outil), id="entete")
            yield DataTable(id="tours", cursor_type="row")
            yield Static(resume(mesures), id="resume")
            with VerticalScroll(id="defile"):
                yield Static("", id="echange")
            yield Static("", id="etat")
            yield Input(id="saisie", placeholder=t("Your question"))
            yield Footer()

        def on_mount(self) -> None:
            self._poser_les_colonnes()
            self._peindre()
            self._ecrire_echange()
            self._monte = True
            self.query_one("#saisie", Input).focus()

        def on_resize(self, _evenement=None) -> None:
            # Avant le montage, la taille n'est pas encore celle du terminal :
            # repeindre là poserait des colonnes qu'il faudrait refaire.
            if self._monte:
                self._poser_les_colonnes()
                self._peindre()

        def _poser_les_colonnes(self) -> None:
            """Les colonnes qui tiennent. Ne les refait QUE si leur nombre
            change : les recréer à chaque tour remettrait le curseur en tête.
            """
            voulues = colonnes_visibles(self.size.width)
            if voulues == self._colonnes:
                return
            table = self.query_one("#tours", DataTable)
            table.clear(columns=True)
            for _cle, titre in voulues:
                table.add_column(t(titre))
            self._colonnes = voulues

        def _peindre(self) -> None:
            table = self.query_one("#tours", DataTable)
            table.clear()
            for ligne in lignes(mesures):
                table.add_row(
                    *[ligne[cle] for cle, _ in self._colonnes],
                    key=ligne["cle"],
                )
            self.query_one("#resume", Static).update(resume(mesures))

        def _ecrire_echange(self) -> None:
            """Repose la conversation et descend au dernier mot.

            Le défilement suit l'arrivée parce qu'une réponse qui dépasse la
            hauteur du panneau se lirait par son début, c'est-à-dire par ce
            qu'on a déjà lu.
            """
            vue = self.query_one("#echange", Static)
            vue.update(
                echange(
                    getattr(conversation, "turns", ()),
                    self._question,
                    self._texte,
                )
            )
            self.query_one("#defile", VerticalScroll).scroll_end(animate=False)

        def action_durees(self) -> None:
            """Replier le tableau des durées pour rendre sa place au texte.

            Les deux se disputent la hauteur d'un terminal, et ce qu'on veut
            voir change selon qu'on lit une réponse ou qu'on compare des
            tours.
            """
            table = self.query_one("#tours", DataTable)
            table.display = not table.display
            self.query_one("#resume", Static).display = table.display

        def on_input_submitted(self, evenement) -> None:
            texte = (evenement.value or "").strip()
            evenement.input.value = ""
            if not texte or self._occupe:
                return
            self._occupe = True
            self._debut = horloge()
            self._premier = None
            self._fragments = 0
            self._texte = ""
            self._question = texte
            self._ecrire_echange()
            self._battre()
            self._minuteur = self.set_interval(PAS, self._battre)
            self._demander(texte)

        @work(thread=True)
        def _demander(self, texte) -> None:
            """La génération, HORS de la boucle d'événements.

            La mener sur la boucle gèlerait l'écran pour toute sa durée, qui
            se compte en minutes sur un modèle local : ni les touches ni le
            compteur ne répondraient, et rien ne dirait que l'écran est vivant.
            """

            def au_fil(morceau):
                self.call_from_thread(self._fragment, morceau)

            try:
                tour = conversation.ask(texte, on_chunk=au_fil)
            except Exception as souci:  # noqa: BLE001
                # Un fil qui meurt laisse l'écran occupé pour toujours, et
                # aucune trace ne dit pourquoi : la panne revient par le même
                # chemin que la réussite.
                self.call_from_thread(self._fini, None, texte, souci)
                return
            self.call_from_thread(self._fini, tour, texte, None)

        def _fragment(self, morceau) -> None:
            """Un fragment arrivé. Seul `call_from_thread` mène ici."""
            if self._premier is None:
                self._premier = horloge() - self._debut
            self._fragments += 1
            self._texte += morceau or ""
            self._ecrire_echange()
            self._battre()

        def _battre(self) -> None:
            """Redessine le panneau du flux, fragments ou pas.

            Le temps écoulé avance même quand rien n'arrive, et c'est
            justement là qu'un écran figé se distingue mal d'un écran mort.
            """
            if not self._occupe:
                return
            ecoule = horloge() - self._debut
            self.query_one("#etat", Static).update(
                en_cours(
                    self._fragments, len(self._texte), ecoule, self._premier
                )
            )

        def _fini(self, tour, question, souci) -> None:
            """Le tour est clos : on mesure, on journalise, on repeint."""
            minuteur = getattr(self, "_minuteur", None)
            if minuteur is not None:
                minuteur.stop()
                self._minuteur = None
            duree = horloge() - self._debut
            faits = getattr(conversation, "last_meta", {}) or {}
            erreur = ""
            if souci is not None:
                erreur = type(souci).__name__
            elif tour is not None and getattr(tour, "role", "") == "error":
                erreur = "BackendError"
            self._rang += 1
            prise = ms.mesurer(
                seance=seance,
                rang=self._rang,
                serveur=serveur,
                outil=outil,
                question=question,
                duree=duree,
                premier=self._premier,
                faits=faits,
                interrompu=bool(getattr(tour, "interrupted", False)),
                erreur=erreur,
            )
            mesures.append(prise)
            try:
                journal(prise)
            except Exception:  # noqa: BLE001
                # Compter ne doit jamais interrompre une conversation.
                pass
            self._occupe = False
            self._question = ""
            self._texte = ""
            self._ecrire_echange()
            etat = self.query_one("#etat", Static)
            etat.update(pied(prise) if not erreur else f"⚠ {erreur}")
            self._peindre()
            self.query_one("#saisie", Input).focus()

        def action_interrompre(self) -> None:
            """Ctrl+C ferme l'écran, comme il rend la main à l'invite texte.

            Interrompre une génération déjà partie demanderait de couper le
            fil qui la porte, ce que Textual ne fait pas ; fermer l'écran rend
            au moins la main, et la conversation garde ses tours.
            """
            self.exit(None)

    app = Perf()
    return app.run() if run_app else app
