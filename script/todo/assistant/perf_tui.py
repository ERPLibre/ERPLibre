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

import re

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


# Les réglages de l'écran, et leur défaut. Ils vivent dans les préférences de
# l'utilisateur — ~/.erplibre — et non dans le dépôt : l'apparence d'un écran
# appartient à qui le regarde, pas au projet.
REGLAGES = {
    "assistant_tui_theme": "textual-dark",
    "assistant_tui_question": "$accent",
    "assistant_tui_reponse": "",
    "assistant_tui_raisonnement": False,
    "assistant_tui_durees": True,
    "assistant_tui_horodatage": False,
    "assistant_tui_colonnes": [cle for cle, _titre in COLONNES],
}

# Les rôles de couleur qu'un thème définit. Les nommer plutôt que de figer
# une valeur est ce qui garde l'écran lisible quand le thème change : un bleu
# choisi sur fond sombre disparaît sur fond clair, un rôle suit.
ROLES = (
    "$accent",
    "$primary",
    "$secondary",
    "$success",
    "$warning",
    "$error",
    "$text-muted",
    "",
)

# Une couleur écrite à la main. Trois ou six chiffres hexadécimaux, ce que
# tout terminal en couleurs vraies comprend. Rien d'autre n'est accepté :
# une chaîne libre qui n'est ni un rôle ni une couleur rendrait un balisage
# que Rich refuse, et l'écran se fermerait sur l'exception.
HEXA = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def resoudre_couleur(valeur) -> str:
    """Une couleur utilisable, ou la chaîne vide. Fonction PURE.

    La chaîne vide veut dire « la couleur du texte », et c'est un choix
    valide : le corps d'une réponse n'a pas besoin d'être teinté pour se
    distinguer d'une question qui, elle, porte un chevron.

    Tout ce qui n'est ni un rôle du thème ni une couleur hexadécimale rend la
    chaîne vide plutôt que de lever : la valeur vient d'un fichier que
    l'utilisateur peut éditer à la main, et un écran qui refuse de s'ouvrir
    sur une faute de frappe est pire qu'un écran sans couleur.
    """
    if not isinstance(valeur, str):
        return ""
    valeur = valeur.strip()
    if valeur in ROLES:
        return valeur
    return valeur if HEXA.match(valeur) else ""


def resoudre_theme(valeur, disponibles) -> str:
    """Un nom de thème que Textual connaît, ou celui par défaut. PURE.

    Un thème retiré d'une version à l'autre ne doit pas empêcher l'écran de
    s'ouvrir : la préférence est un souhait, la liste fait foi.
    """
    defaut = REGLAGES["assistant_tui_theme"]
    liste = tuple(disponibles or ())
    if isinstance(valeur, str) and valeur in liste:
        return valeur
    return defaut if defaut in liste or not liste else liste[0]


def resoudre_colonnes(valeur) -> tuple:
    """Les colonnes retenues, dans l'ordre d'importance. Fonction PURE.

    Jamais vide et jamais dans l'ordre du fichier : un tableau sans colonne
    ne montre rien, et un ordre venu des préférences ferait de la place à
    « fin » avant « durée » sur un terminal étroit.
    """
    voulues = valeur if isinstance(valeur, (list, tuple)) else ()
    gardees = tuple((cle, titre) for cle, titre in COLONNES if cle in voulues)
    return gardees or COLONNES[:2]


def resoudre_oui(valeur, defaut=False) -> bool:
    """Un booléen lu dans un fichier éditable à la main. Fonction PURE."""
    return valeur if isinstance(valeur, bool) else defaut


def teinter(texte, couleur) -> str:
    """Le texte en balisage Rich, sa couleur posée. Fonction PURE.

    Le texte est ÉCHAPPÉ, et c'est la seule chose qui compte ici : une
    réponse de modèle porte volontiers des crochets — une note en bas de
    page, un extrait de code, un tableau — et le rendu les lirait comme des
    balises. Le texte disparaîtrait alors en partie, ou le rendu lèverait,
    ce qui ferme l'écran entier.

    L'échappement est celui de TEXTUAL et non celui de Rich, parce que c'est
    Textual qui analysera la chaîne : les deux balisages se ressemblent mais
    ne se recouvrent pas — un rôle de thème comme « $accent » n'est une
    balise que pour l'un des deux, et l'autre lève sur la fermeture qui le
    suit.
    """
    from textual.markup import escape

    brut = escape(texte or "")
    return f"[{couleur}]{brut}[/]" if couleur else brut


# Ce qui ouvre une question dans la transcription. Le même chevron que
# l'invite texte : l'écran et l'invite montrent la même conversation, et deux
# marques différentes feraient croire à deux fils.
MARQUE_QUESTION = "▸ "


def echange(
    turns,
    question="",
    reponse="",
    *,
    couleur_question="",
    couleur_reponse="",
    raisonnement=False,
    heures=(),
) -> str:
    """La conversation, telle qu'elle se lit. Fonction PURE.

    Rend du BALISAGE Rich, et tout ce qui vient du modèle ou de
    l'utilisateur y est échappé : une réponse porte volontiers des crochets,
    que Rich lirait comme des balises.

    `turns` sont les tours déjà clos, en couples question-réponse ; `question`
    et `reponse` portent celui qui arrive, et la réponse y grandit à chaque
    fragment. `heures` donne une étiquette d'heure par tour, à l'index du
    tour ; une chaîne vide n'en met aucune.

    `raisonnement` montre les jetons de réflexion d'un modèle qui raisonne.
    Ils sont comptés dans les jetons de réponse et payés comme eux : les
    taire fait décrire au débit un travail qu'on ne voit nulle part. Ils sont
    grisés, parce qu'ils accompagnent la réponse sans en être.

    Un tour COUPÉ garde son texte et se marque : ce qui est arrivé a été
    payé, et le lire comme une réponse entière ferait croire le modèle plus
    bref qu'il n'est.
    """
    parties = []
    for rang, tour in enumerate(turns or ()):
        role = getattr(tour, "role", "")
        texte = getattr(tour, "text", "") or ""
        heure = heures[rang] if rang < len(heures) else ""
        if role == "user":
            parties.append(_demande(texte, couleur_question, heure))
        elif role == "assistant":
            if raisonnement:
                pensee = getattr(tour, "reasoning", "") or ""
                if pensee:
                    parties.append(teinter(pensee, "$text-muted"))
            marque = (
                f"  [{t('cut')}]"
                if getattr(tour, "interrupted", False)
                else ""
            )
            parties.append(teinter(texte + marque, couleur_reponse))
    if question:
        parties.append(_demande(question, couleur_question, ""))
    if reponse:
        parties.append(teinter(reponse, couleur_reponse))
    return "\n\n".join(parties)


def _demande(texte, couleur, heure="") -> str:
    """Une question, son chevron et son heure. Fonction PURE.

    L'heure précède le chevron et n'est pas teintée : elle situe le tour, et
    la couleur de la question sert à la distinguer de la réponse, pas à
    peindre tout ce qui se trouve sur la ligne.
    """
    tete = f"{heure} " if heure else ""
    return f"{tete}{teinter(MARQUE_QUESTION + texte, couleur)}"


# Le préfixe d'un réglage de COLONNE. Les colonnes se règlent une par une,
# donc leur clé se fabrique ; la nommer d'un préfixe est ce qui permet de la
# reconnaître sans tenir une seconde liste à jour.
CLE_COLONNE = "colonne:"

# Les réglages du panneau, dans l'ordre où ils paraissent : ce qui change
# tout l'écran d'abord, ce qui ajuste un détail ensuite. Le troisième champ
# dit comment la valeur se fait tourner.
REGLAGE_LIGNES = (
    ("assistant_tui_theme", "theme", "choix"),
    ("assistant_tui_question", "question colour", "couleur"),
    ("assistant_tui_reponse", "answer colour", "couleur"),
    ("assistant_tui_raisonnement", "show reasoning", "oui"),
    ("assistant_tui_durees", "timings at start", "oui"),
    ("assistant_tui_horodatage", "time of each turn", "oui"),
)

# La largeur du libellé d'un réglage, pour que les valeurs s'alignent. Un
# panneau dont les valeurs zigzaguent se relit mot à mot.
LIBELLE_LARGEUR = 26


def reglages(valeurs, themes=()) -> list[dict]:
    """Les lignes du panneau de personnalisation. Fonction PURE.

    Rend un dictionnaire par réglage : sa clé, son libellé prêt à afficher,
    sa valeur résolue et le genre de tour qu'il accepte. Les colonnes du
    tableau y figurent une par une, parce qu'on en garde ou en retire une, et
    non un ensemble.
    """
    valeurs = valeurs if isinstance(valeurs, dict) else {}
    lus = []
    for cle, libelle, genre in REGLAGE_LIGNES:
        brut = valeurs.get(cle, REGLAGES[cle])
        if genre == "choix":
            valeur = resoudre_theme(brut, themes)
            montre = valeur
        elif genre == "couleur":
            valeur = resoudre_couleur(brut)
            montre = valeur or t("text colour")
        else:
            valeur = resoudre_oui(brut, REGLAGES[cle])
            montre = t("yes") if valeur else t("no")
        lus.append(
            {
                "cle": cle,
                "genre": genre,
                "valeur": valeur,
                "libelle": f"{t(libelle):<{LIBELLE_LARGEUR}}{montre}",
            }
        )
    gardees = [
        cle
        for cle, _titre in resoudre_colonnes(
            valeurs.get(
                "assistant_tui_colonnes", REGLAGES["assistant_tui_colonnes"]
            )
        )
    ]
    for cle, titre in COLONNES:
        vu = cle in gardees
        lus.append(
            {
                "cle": f"{CLE_COLONNE}{cle}",
                "genre": "colonne",
                "valeur": vu,
                "libelle": (
                    f"{t('column') + ' ' + t(titre):<{LIBELLE_LARGEUR}}"
                    f"{t('yes') if vu else t('no')}"
                ),
            }
        )
    return lus


def tourner(genre, valeur, sens=1, themes=()) -> object:
    """La valeur suivante d'un réglage qu'on fait tourner. Fonction PURE.

    Les listes BOUCLENT : un panneau où la dernière valeur bloque oblige à
    revenir en arrière pour retrouver la première, et rien ne dit qu'on est
    au bout.
    """
    if genre in ("oui", "colonne"):
        return not resoudre_oui(valeur, False)
    liste = tuple(themes or ()) if genre == "choix" else ROLES
    if not liste:
        return valeur
    try:
        rang = liste.index(valeur)
    except ValueError:
        rang = 0
        sens = 0
    return liste[(rang + sens) % len(liste)]


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
    archiver=None,
    horloge=None,
    montre=None,
    prefs=None,
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
    from textual.theme import BUILTIN_THEMES
    from textual.widgets import (
        DataTable,
        Footer,
        Header,
        Input,
        OptionList,
        Static,
    )

    from script.todo import todo_prefs

    from script.todo.assistant import mesure as ms

    mesures = [] if mesures is None else mesures
    journal = ms.ecrire if journal is None else journal
    # L'écran pose des tours dans la MÊME conversation que l'invite texte :
    # sans archiviste, ceux-là seuls manqueraient à la séance gardée, et la
    # relecture montrerait un trou là où l'on avait basculé d'écran.
    archiver = (lambda _tour: None) if archiver is None else archiver
    horloge = time.monotonic if horloge is None else horloge
    # Deux horloges, et elles ne sont pas interchangeables. `horloge` est
    # MONOTONE et mesure des durées : celle du mur recule à un changement
    # d'heure, ce qui rendrait une durée négative. `montre` donne l'heure
    # qu'il est, qui ne se déduit d'aucune mesure monotone.
    montre = (lambda: time.strftime("%H:%M")) if montre is None else montre
    prefs = todo_prefs if prefs is None else prefs
    THEMES = tuple(sorted(BUILTIN_THEMES))

    class Perf(App):
        """Le tableau des tours, le flux en cours, et la question suivante."""

        CSS = """
        #entete, #resume, #etat { height: auto; padding: 0 1; }
        #echange { height: auto; padding: 0 1; }
        #defile { height: 1fr; }
        #reglages { height: auto; max-height: 60%; }
        #aide-options { height: auto; padding: 0 1; color: $text-muted; }
        DataTable { height: auto; max-height: 40%; }
        """

        # Des touches que la SAISIE ne consomme pas. Elle garde le focus
        # pendant toute la vie de l'écran — c'est de là qu'on pose ses
        # questions — donc une lettre nue n'atteint jamais un raccourci : elle
        # s'écrit dans le champ, et le raccourci passe pour mort.
        BINDINGS = [
            ("escape", "fermer", t("back")),
            ("ctrl+t", "durees", t("timings")),
            ("f2", "options", t("options")),
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
            self._reglages = dict(REGLAGES)
            self._heures = []
            self._rang = depart

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static(entete(serveur, outil), id="entete")
            yield DataTable(id="tours", cursor_type="row")
            yield Static(resume(mesures), id="resume")
            with VerticalScroll(id="defile"):
                yield Static("", id="echange")
            yield Static("", id="etat")
            yield OptionList(id="reglages")
            yield Static(
                t("h: type a colour · enter: cycle · escape: close"),
                id="aide-options",
            )
            yield Input(
                id="hexa", placeholder=t("Colour in hexadecimal, or empty")
            )
            yield Input(id="saisie", placeholder=t("Your question"))
            yield Footer()

        def on_mount(self) -> None:
            self._fermer_options()
            self._lire_reglages()
            self._poser_les_colonnes()
            self._peindre()
            self._ecrire_echange()
            self._monte = True
            self.query_one("#saisie", Input).focus()

        def _lire_reglages(self) -> None:
            """Relit les préférences et applique ce qui se voit tout de suite.

            Une préférence illisible ne doit jamais empêcher l'écran de
            s'ouvrir : chaque valeur passe par son résolveur, qui retombe sur
            un défaut plutôt que de lever.
            """
            lus = {}
            for cle in REGLAGES:
                try:
                    lus[cle] = prefs.get(cle, REGLAGES[cle])
                except Exception:  # noqa: BLE001
                    lus[cle] = REGLAGES[cle]
            self._reglages = lus
            self.theme = resoudre_theme(lus["assistant_tui_theme"], THEMES)
            table = self.query_one("#tours", DataTable)
            table.display = resoudre_oui(lus["assistant_tui_durees"], True)
            self.query_one("#resume", Static).display = table.display

        def _valeur(self, cle):
            return self._reglages.get(cle, REGLAGES.get(cle))

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
            voulues = colonnes_visibles(
                self.size.width,
                resoudre_colonnes(self._valeur("assistant_tui_colonnes")),
            )
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
                    couleur_question=resoudre_couleur(
                        self._valeur("assistant_tui_question")
                    ),
                    couleur_reponse=resoudre_couleur(
                        self._valeur("assistant_tui_reponse")
                    ),
                    raisonnement=resoudre_oui(
                        self._valeur("assistant_tui_raisonnement")
                    ),
                    heures=self._heures,
                )
            )
            self.query_one("#defile", VerticalScroll).scroll_end(animate=False)

        def _fermer_options(self) -> None:
            """Cache le panneau et rend le focus à la question."""
            for quoi in ("#reglages", "#aide-options", "#hexa"):
                self.query_one(quoi).display = False
            if self._monte:
                self.query_one("#saisie", Input).focus()

        def action_fermer(self) -> None:
            """Échap ferme le panneau s'il est ouvert, l'écran sinon.

            La même touche pour les deux, en cascade : une touche qui ferme
            l'écran entier alors qu'un panneau est ouvert fait perdre la
            conversation pour un réglage qu'on voulait seulement quitter.
            """
            if self.query_one("#reglages").display:
                self._fermer_options()
                return
            self.exit(None)

        def action_options(self) -> None:
            """Ouvre le panneau de personnalisation, et lui donne le focus.

            Le focus DOIT bouger : la saisie le garde le reste du temps, et
            sans ce déplacement les flèches et « entrée » iraient au champ de
            question au lieu du panneau.
            """
            panneau = self.query_one("#reglages", OptionList)
            if panneau.display:
                self._fermer_options()
                return
            self._peindre_options()
            panneau.display = True
            self.query_one("#aide-options").display = True
            panneau.focus()

        def _peindre_options(self) -> None:
            """Repose les lignes du panneau, le curseur là où il était."""
            panneau = self.query_one("#reglages", OptionList)
            avant = panneau.highlighted
            panneau.clear_options()
            self._lignes_options = reglages(self._reglages, THEMES)
            panneau.add_options(
                [ligne["libelle"] for ligne in self._lignes_options]
            )
            # Une ligne EST surlignée dès l'ouverture, sans quoi « entrée »
            # et « h » n'ont rien à viser : le panneau s'ouvre, répond aux
            # flèches, et passe pour cassé à la première frappe.
            if avant is not None and avant < len(self._lignes_options):
                panneau.highlighted = avant
            elif self._lignes_options:
                panneau.highlighted = 0

        def on_option_list_option_selected(self, evenement) -> None:
            """Entrée fait tourner la valeur du réglage surligné."""
            self._changer(evenement.option_index)

        def _changer(self, rang, sens=1) -> None:
            """Fait tourner un réglage, l'écrit, et l'applique aussitôt.

            L'écriture précède l'application : un thème appliqué mais non
            gardé se perd au prochain démarrage, et rien ne dit pourquoi.
            """
            lignes = getattr(self, "_lignes_options", ())
            if rang is None or not 0 <= rang < len(lignes):
                return
            ligne = lignes[rang]
            if ligne["genre"] == "colonne":
                self._basculer_colonne(ligne["cle"][len(CLE_COLONNE) :])
            else:
                self._poser(
                    ligne["cle"],
                    tourner(ligne["genre"], ligne["valeur"], sens, THEMES),
                )
            self._peindre_options()

        def _basculer_colonne(self, colonne) -> None:
            gardees = [
                cle
                for cle, _titre in resoudre_colonnes(
                    self._valeur("assistant_tui_colonnes")
                )
            ]
            if colonne in gardees:
                gardees.remove(colonne)
            else:
                gardees.append(colonne)
            self._poser("assistant_tui_colonnes", gardees)

        def _poser(self, cle, valeur) -> None:
            """Garde un réglage et le rend visible sans rouvrir l'écran."""
            self._reglages[cle] = valeur
            try:
                prefs.set(cle, valeur)
            except Exception:  # noqa: BLE001
                # Un disque plein ne doit pas faire perdre la conversation :
                # le réglage vaut alors pour cette séance seulement.
                pass
            if cle == "assistant_tui_theme":
                self.theme = resoudre_theme(valeur, THEMES)
            elif cle == "assistant_tui_durees":
                garde = resoudre_oui(valeur, True)
                self.query_one("#tours", DataTable).display = garde
                self.query_one("#resume", Static).display = garde
            elif cle == "assistant_tui_colonnes":
                self._colonnes = ()
                self._poser_les_colonnes()
                self._peindre()
            self._ecrire_echange()

        def on_key(self, evenement) -> None:
            """« h » saisit une couleur à la main, panneau ouvert.

            La touche n'est lue QUE lorsque le panneau a le focus : partout
            ailleurs elle appartient à la question qu'on est en train de
            taper.
            """
            if evenement.key != "h":
                return
            panneau = self.query_one("#reglages", OptionList)
            if not panneau.has_focus:
                return
            lignes = getattr(self, "_lignes_options", ())
            rang = panneau.highlighted
            if rang is None or not 0 <= rang < len(lignes):
                return
            if lignes[rang]["genre"] != "couleur":
                return
            evenement.stop()
            champ = self.query_one("#hexa", Input)
            champ.value = str(lignes[rang]["valeur"] or "")
            champ.display = True
            champ.focus()

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
            if evenement.input.id == "hexa":
                self._poser_couleur(evenement.value)
                return
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

        def _poser_couleur(self, brut) -> None:
            """Range la couleur tapée dans le réglage surligné.

            Une saisie que le résolveur refuse retombe sur « couleur du
            texte » : elle est rendue telle quelle à l'écran, donc la faute
            se voit au lieu de se deviner.
            """
            lignes = getattr(self, "_lignes_options", ())
            panneau = self.query_one("#reglages", OptionList)
            rang = panneau.highlighted
            if rang is not None and 0 <= rang < len(lignes):
                self._poser(lignes[rang]["cle"], resoudre_couleur(brut))
            champ = self.query_one("#hexa", Input)
            champ.display = False
            self._peindre_options()
            panneau.focus()

        def _noter_heures(self) -> None:
            """Donne son heure au tour qui vient d'entrer dans l'historique.

            L'heure se pose par INDEX de tour et non par rang de mesure : un
            tour en panne ne rejoint pas l'historique, donc les deux suites
            se décalent dès la première erreur.
            """
            tours = getattr(conversation, "turns", ())
            maintenant = montre()
            while len(self._heures) < len(tours):
                rang = len(self._heures)
                role = getattr(tours[rang], "role", "")
                self._heures.append(maintenant if role == "user" else "")

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
            self._noter_heures()
            if tour is not None and tour.role != "error":
                from script.todo.assistant.chat import Turn

                archiver(Turn("user", question))
                archiver(tour)
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
