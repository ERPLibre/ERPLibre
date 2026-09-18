#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Clavier de composition et poste téléphonique pour le modem cellulaire.

Un vrai clavier plutôt qu'une invite de saisie : on compose comme sur un
téléphone, on voit le numéro se former, et on appelle d'un geste distinct du
geste de saisie.

Trois contraintes ont façonné ce fichier :

- **Composer engage de l'argent et joint une personne.** Le bouton d'appel
  refuse tant que le numéro n'est pas valide, et le journal RÉPÈTE le numéro
  normalisé, qui est celui qui partira. Une erreur de frappe ne doit pas
  pouvoir sonner chez un inconnu.
- **Le son appartient au binaire, pas à cette interface.** Elle lui envoie
  des commandes et affiche ce qu'il publie ; elle ne garde aucune copie de
  l'état. Deux copies d'un même état divergent tôt ou tard, et c'est alors
  l'affichage qui ment pendant que le son fait autre chose.
- **Rien ne s'écrit dans l'interface depuis un fil.** Le pilote lit la sortie
  du binaire dans le sien : tout repasse par `call_from_thread`, sans quoi le
  rendu se corrompt.
"""
from __future__ import annotations

import math
import threading
from collections import deque

from script.todo.modem import audio as audio_mod
from script.todo.modem import calls as calls_mod
from script.todo.modem import device as device_mod
from script.todo.modem import sipgo as sipgo_mod

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


TOUCHES = [
    ["1", "2", "3"],
    ["4", "5", "6"],
    ["7", "8", "9"],
    ["*", "0", "#"],
]

#: Les memes caracteres, frappes au clavier physique. Les deux entrees
#: composent le MEME numero : la souris pour qui decouvre, le clavier pour
#: qui compose vite, et rien n'oblige a choisir.
TOUCHES_FRAPPEES = {c for rangee in TOUCHES for c in rangee}

#: Pas de réglage du volume, en pour cent. Dix se remarque à peine sur une
#: bande passante téléphonique, cinquante saute d'inaudible à saturé.
PAS_GAIN = 20

#: Borne basse du volume. La HAUTE vient du binaire, qui la publie : la
#: figer ici en donnerait deux, et l'interface refuserait un cran que le
#: binaire accepte.
GAIN_MIN = 0
GAIN_MAX_DEFAUT = 1000

#: Le modem n'a que six crans d'écoute, de 0 à 5. Les monter vaut mieux que
#: le gain logiciel : ils amplifient AVANT que le souffle ne s'ajoute.
CLVL_MIN, CLVL_MAX = 0, 5

#: Le gain de montee du modem, en virgule fixe sur seize bits.
QMIC_MAX = 65535

#: Longueur de l'historique tracé. Vingt-quatre points à cinq par seconde
#: font près de cinq secondes : assez pour voir une phrase passer.
HISTOIRE = 24

#: Du plus faible au plus fort. Un graphique en une ligne, sans dépendance.
BLOCS = " ▁▂▃▄▅▆▇█"

#: Plancher de l'échelle en décibels. Sous -60 dBFS il n'y a plus de voix,
#: seulement le bruit du convertisseur.
DBFS_PLANCHER = -60.0


def en_dbfs(niveau):
    """Convertit une valeur efficace 16 bits en décibels pleine échelle.

    Le décibel est ce qui se compare d'une source à l'autre : un niveau brut
    ne dit rien sans son échelle, là où -20 dBFS veut dire la même chose
    partout.
    """
    if niveau <= 0:
        return DBFS_PLANCHER
    return max(DBFS_PLANCHER, 20.0 * math.log10(niveau / 32767.0))


def courbe(histoire):
    """Trace un historique de niveaux en une ligne."""
    points = []
    for db in histoire:
        part = (db - DBFS_PLANCHER) / (0.0 - DBFS_PLANCHER)
        indice = max(0, min(len(BLOCS) - 1, int(part * (len(BLOCS) - 1))))
        points.append(BLOCS[indice])
    return "".join(points).rjust(HISTOIRE)


def barre(niveau, echelle):
    """Dessine un niveau sur dix caractères."""
    if echelle <= 0:
        return "[..........]"
    n = max(0, min(10, niveau * 10 // echelle))
    return "[" + "#" * n + "." * (10 - n) + "]"


def lancer(index_modem, numero_initial=""):
    """Ouvre le poste. Renvoie False si Textual n'est pas installé.

    `numero_initial` pre-remplit le numero sans l'appeler : l'appel reste un
    geste de l'utilisateur, qui voit ce qui va etre compose.
    """
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.widgets import (Button, Footer, Header, Log, Select,
                                     Static, Switch)
    except ImportError:
        return False

    carte_modem, _nom_carte = calls_mod.carte_son()

    # Lues UNE fois, puis remplacees par le bouton de rafraichissement.
    # L'interface s'y refere pour savoir ce qui est proposable, sans lire
    # l'interieur des widgets.
    listes = {"dev_entree": audio_mod.entrees(carte_modem),
              "dev_sortie": audio_mod.sorties(carte_modem)}

    class Poste(App):
        CSS = """
        /* Chaque ligne compte : en vingt-quatre rangees, l'en-tete, les
           onglets, le resume, le clavier, le journal et le pied s'ajoutent
           deja au-dela. Une ligne de trop et les rangees de touches se
           chevauchent au lieu de s'empiler. */
        #numero { height: 1; content-align: center middle; text-style: bold; }
        .touche { width: 1fr; height: 3; }
        /* Les rangees DOIVENT declarer leur hauteur. Sans elle, elles se
           partagent la place restante : quatre rangees de trois lignes dans
           moins de douze se chevauchent, et les touches se recouvrent. */
        .rangee { height: 3; }
        #appeler { background: $success; }
        #raccrocher { background: $error; }
        .rang   { height: 3; align: left middle; }
        .titre  { width: 8; content-align: left middle; }
        .niveau { width: 12; content-align: left middle; }
        .valeur { width: 6; content-align: center middle; }
        .pas    { width: 3; min-width: 3; }
        Log { height: 1fr; min-height: 1; border: round $primary; }
        /* Les deux vues occupent la MEME place et s'excluent. Cote a cote,
           l'une des deux perd des colonnes en quatre-vingts caracteres : le
           clavier y a perdu sa troisieme rangee de touches sans que rien ne
           le signale. Chacune a donc toute la largeur, a son tour. */
        #clavier { width: 1fr; }
        #audio   { width: 1fr; }
        #resume  { height: 1; content-align: center middle; }
        #onglets { height: 3; }
        .onglet  { width: 1fr; }
        Select   { width: 1fr; }
        /* Filet de securite pour un terminal plus court que prevu : mieux
           vaut faire defiler que tronquer sans le dire. */
        /* height: auto est INDISPENSABLE. Sans elle, le journal en 1fr
           s'empare de la place et RECOUVRE le bas de la vue : la derniere
           rangee de touches et les boutons d'appel restent dessines mais
           deviennent incliquables, le clic atterrissant sur le journal. Le
           symptome ne ressemble pas a la cause — on croit a un bouton mort. */
        #clavier, #audio, #signal { height: auto; }
        #signal  { width: 1fr; }
        .mesure  { width: 11; content-align: right middle; }
        .trace   { width: 26; content-align: left middle; }
        """
        BINDINGS = [
            ("q", "quit", t("mail_quit_binding")),
            ("backspace", "effacer", t("Erase")),
            ("f1", "vue_clavier", t("modem_tui_tab_keys")),
            ("f2", "vue_audio", t("modem_tui_tab_audio")),
            ("f3", "vue_signal", t("modem_tui_tab_signal")),
        ]

        def __init__(self):
            super().__init__()
            self.numero = numero_initial
            self.pilote = None
            self.vue = "clavier"
            self.entrant_vu = ""
            # DERNIER etat publie par le binaire, et rien d'autre. Ce n'est
            # pas une seconde source de verite : c'est le cache de la
            # premiere, dont on a besoin pour calculer un increment.
            self.dernier_etat = {}
            self.histoire_mic = deque(maxlen=HISTOIRE)
            self.histoire_hp = deque(maxlen=HISTOIRE)

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("", id="numero")
            with Horizontal(id="onglets"):
                yield Button(t("modem_tui_tab_keys"), id="tab_clavier",
                             classes="onglet")
                yield Button(t("modem_tui_tab_audio"), id="tab_audio",
                             classes="onglet")
                yield Button(t("modem_tui_tab_signal"), id="tab_signal",
                             classes="onglet")
            # Le resume reste visible dans les DEUX vues : savoir si le micro
            # est ouvert ne doit pas demander de changer d'onglet.
            yield Static("", id="resume")
            with Vertical(id="clavier"):
                for rangee in TOUCHES:
                    with Horizontal(classes="rangee"):
                        for touche in rangee:
                            yield Button(touche, id=f"k{ord(touche)}",
                                         classes="touche")
                # Quatre boutons pour trois situations : un seul jeu est
                # montre a la fois. Un bouton visible mais sans effet fait
                # douter de l'appareil plutot que du geste.
                with Horizontal(classes="rangee"):
                    yield Button(t("Appeler"), id="appeler")
                    yield Button(t("Veille"), id="veille")
                    yield Button(t("Repondre"), id="repondre")
                    yield Button(t("Ajouter un appel"), id="ajouter")
                    yield Button(t("Raccrocher"), id="raccrocher")
                    yield Button(t("Fusionner"), id="fusionner")
            with Vertical(id="audio"):
                with Horizontal(classes="rang"):
                    yield Static(t("modem_tui_mic"), classes="titre")
                    yield Switch(value=False, id="sw_micro")
                    yield Button("−", id="mic_moins", classes="pas")
                    yield Static("100%", id="g_micro", classes="valeur")
                    yield Button("+", id="mic_plus", classes="pas")
                    yield Static(barre(0, 1), id="n_micro",
                                 classes="niveau")
                with Horizontal(classes="rang"):
                    yield Static(t("modem_tui_hp"), classes="titre")
                    yield Switch(value=True, id="sw_hp")
                    yield Button("−", id="hp_moins", classes="pas")
                    yield Static("100%", id="g_hp", classes="valeur")
                    yield Button("+", id="hp_plus", classes="pas")
                    yield Static(barre(0, 1), id="n_hp", classes="niveau")
                with Horizontal(classes="rang"):
                    yield Static(t("modem_tui_micgain"), classes="titre")
                    yield Button("−", id="qmic_moins", classes="pas")
                    yield Static("—", id="v_qmic", classes="valeur")
                    yield Button("+", id="qmic_plus", classes="pas")
                    # Les deux gains DU MODEM cote a cote : ils amplifient
                    # avant la carte, la ou le gain logiciel amplifie apres
                    # la capture et multiplie le souffle avec la voix.
                    yield Static(t("modem_tui_ecogain"), classes="titre")
                    yield Button("−", id="deco_moins", classes="pas")
                    yield Static("—", id="v_deco", classes="valeur")
                    yield Button("+", id="deco_plus", classes="pas")
                with Horizontal(classes="rang"):
                    yield Static(t("modem_tui_in"), classes="titre")
                    # Un seul bouton pour les DEUX listes : brancher un
                    # casque change souvent l'entree et la sortie ensemble.
                    yield Button("⟳", id="rafraichir", classes="pas")
                    yield Select(
                        [(lib, ident) for ident, lib
                         in listes["dev_entree"]],
                        value="", allow_blank=False, id="dev_entree")
                with Horizontal(classes="rang"):
                    yield Static(t("modem_tui_out"), classes="titre")
                    yield Select(
                        [(lib, ident) for ident, lib
                         in listes["dev_sortie"]],
                        value="", allow_blank=False, id="dev_sortie")
            with Vertical(id="signal"):
                with Horizontal(classes="rang"):
                    yield Static(t("modem_tui_net"), classes="titre")
                    yield Static("—", id="s_dbm", classes="mesure")
                    yield Static("", id="s_detail", classes="trace")
                with Horizontal(classes="rang"):
                    yield Static(t("modem_tui_quality_mic"), classes="titre")
                    yield Static("—", id="q_micro", classes="mesure")
                    yield Static("", id="c_micro", classes="trace")
                with Horizontal(classes="rang"):
                    yield Static(t("modem_tui_quality_hp"), classes="titre")
                    yield Static("—", id="q_hp", classes="mesure")
                    yield Static("", id="c_hp", classes="trace")
                with Horizontal(classes="rang"):
                    yield Static(t("modem_tui_clvl"), classes="titre")
                    yield Button("−", id="clvl_moins", classes="pas")
                    yield Static("—", id="v_clvl", classes="valeur")
                    yield Button("+", id="clvl_plus", classes="pas")
                    yield Static(t("modem_tui_fns"), classes="titre")
                    yield Switch(value=True, id="sw_fns")
                with Horizontal(classes="rang"):
                    yield Static(t("modem_tui_echo"), classes="titre")
                    yield Switch(value=True, id="sw_echo")
                    yield Static(t("modem_tui_clean"), classes="titre")
                    yield Switch(value=True, id="sw_filtre")
                    yield Static(t("modem_tui_ring"), classes="titre")
                    yield Switch(value=True, id="sw_sonnerie")
            yield Log(id="journal")
            yield Footer()

        def on_mount(self):
            self.title = t("Clavier du modem")
            self._montrer("clavier")
            self._resumer({})
            self._peindre()
            self._maj_boutons()
            self._dire("·  " + t("modem_tui_typing"))
            # On annonce l'absence de son AVANT le premier appel : le
            # decouvrir en direct, correspondant au bout du fil, est la pire
            # facon de l'apprendre.
            ok, motif = calls_mod.voix_disponible()
            if not ok:
                self._dire("⚠  " + motif)

        # ----- affichage -------------------------------------------------

        def _maj_boutons(self):
            """N'affiche que les boutons qui ont un sens ici et maintenant.

            Appeler n'a pas de sens pendant un appel, ni Raccrocher en
            dehors ; Fusionner exige deux appels, ce que seul le modem sait.
            """
            ouvert = self.pilote is not None
            appels = int(self.dernier_etat.get("appels_voix", -1))
            sonne = bool(self.dernier_etat.get("appel_entrant"))
            # En veille, le binaire tourne sans conversation : « en ligne »
            # ne se deduit donc PAS de sa presence.
            en_ligne = ouvert and bool(self.dernier_etat.get("en_ligne", True))
            for ident, montrer in (
                ("appeler", not ouvert),
                ("veille", not ouvert),
                ("repondre", ouvert and sonne and not en_ligne),
                ("ajouter", en_ligne),
                ("raccrocher", ouvert),
                ("fusionner", en_ligne and appels >= 2),
            ):
                self.query_one(f"#{ident}", Button).display = montrer

        def _montrer(self, vue):
            """Affiche une vue et cache l'autre.

            Elles occupent la meme place : les laisser toutes deux visibles
            les fait se partager la largeur, et chacune y perd des colonnes
            sans que rien ne l'annonce.
            """
            self.vue = vue
            for nom in ("clavier", "audio", "signal"):
                self.query_one(f"#{nom}").display = (nom == vue)
                onglet = self.query_one(f"#tab_{nom}", Button)
                onglet.variant = "primary" if nom == vue else "default"

        def _resumer(self, etat):
            """Ligne d'etat du son, visible dans les DEUX vues."""
            def voyant(ouvert):
                return "ON " if ouvert else "OFF"

            echelle = etat.get("echelle_niveau") or 1
            self.query_one("#resume", Static).update(
                f"{t('modem_tui_mic')} {voyant(etat.get('micro'))}"
                f" {etat.get('gain_micro', 100)}%"
                f" {barre(etat.get('niveau_micro', 0), echelle)}"
                f"   {t('modem_tui_hp')} {voyant(etat.get('hp', True))}"
                f" {etat.get('gain_hp', 100)}%"
                f" {barre(etat.get('niveau_hp', 0), echelle)}"
            )

        def action_vue_clavier(self):
            self._montrer("clavier")

        def action_vue_audio(self):
            self._montrer("audio")

        def action_vue_signal(self):
            self._montrer("signal")

        def on_key(self, event):
            """Compose au clavier physique, sans desactiver les boutons.

            Uniquement dans la vue clavier : ailleurs, un chiffre appartient
            au widget qui a le focus — une liste deroulante s'en sert pour
            chercher, et le lui voler rendrait le choix impossible.

            Les touches consommees sont ARRETEES ici, sinon Textual les
            propose ensuite aux raccourcis et un « 1 » finirait par declencher
            autre chose.
            """
            if self.vue != "clavier":
                return
            caractere = event.character or ""
            if caractere in TOUCHES_FRAPPEES:
                self._touche(caractere)
                event.stop()
            elif event.key == "enter":
                self._demander_appel()
                event.stop()

        def _vivante(self):
            """L'interface est-elle encore montee ?

            Les rappels du pilote arrivent d'un autre fil et peuvent survivre
            a la fermeture : le binaire se termine apres, et toucher un
            widget demonte leve une exception au lieu de ne rien faire.
            """
            return self.is_running

        def _dire(self, texte):
            if not self._vivante():
                return
            self.query_one("#journal", Log).write_line(texte)

        def _peindre(self):
            """Le numéro et son verdict sur UNE ligne.

            Deux lignes coûtaient une rangée de touches : la place manquait
            plus bas, et les rangées se chevauchaient.
            """
            if self.entrant_vu:
                # Qui sonne prime sur ce qu'on est en train de composer.
                self.query_one("#numero", Static).update(
                    t("modem_tui_ringing") % self.entrant_vu)
                return
            valide = calls_mod.numero_valide(self.numero)
            if not self.numero:
                texte = "—"
            elif valide:
                texte = f"+{valide}   {t('Numéro valide')}"
            else:
                texte = f"{self.numero}   {t('Numéro incomplet')}"
            self.query_one("#numero", Static).update(texte)

        def _maj_etat(self, etat):
            """Reflète l'état publié par le binaire. SEULE source de vérité."""
            if not self._vivante():
                return
            self.dernier_etat = etat
            self._resumer(etat)
            self._maj_boutons()
            entrant = etat.get("appel_entrant") or ""
            if entrant != self.entrant_vu:
                self.entrant_vu = entrant
                if entrant:
                    # Annonce une seule fois : republier a chaque etat
                    # noierait le journal cinq fois par seconde.
                    self._dire("🔔  " + t("modem_tui_ringing") % entrant)
                self._peindre()
            echelle = etat.get("echelle_niveau") or 1
            self.query_one("#g_micro", Static).update(
                f"{etat.get('gain_micro', 100)}%")
            self.query_one("#g_hp", Static).update(
                f"{etat.get('gain_hp', 100)}%")
            self.query_one("#n_micro", Static).update(
                barre(etat.get("niveau_micro", 0), echelle))
            self.query_one("#n_hp", Static).update(
                barre(etat.get("niveau_hp", 0), echelle))
            self._maj_signal(etat)
            self._maj_peripheriques(etat)
            for ident, cle in (("#sw_micro", "micro"), ("#sw_hp", "hp"),
                               ("#sw_echo", "anti_echo"),
                               ("#sw_fns", "bruit_modem"),
                               ("#sw_filtre", "filtre_micro"),
                               ("#sw_sonnerie", "sonnerie")):
                inter = self.query_one(ident, Switch)
                voulu = bool(etat.get(cle))
                if inter.value != voulu:
                    # Sans garde, réécrire la même valeur relance l'événement
                    # de changement, qui renvoie une commande, qui republie un
                    # état : la boucle ne s'arrête plus.
                    with inter.prevent(Switch.Changed):
                        inter.value = voulu

        def _maj_peripheriques(self, etat):
            """Fait suivre les listes a l'etat REEL du binaire.

            Un choix peut etre refuse — le serveur audio tient la carte — et
            le binaire revient alors au peripherique du systeme. Laisser la
            liste afficher le choix refuse ferait croire qu'il s'applique, et
            l'on chercherait le defaut ailleurs.
            """
            for ident, cle in (("dev_entree", "entree"),
                               ("dev_sortie", "sortie")):
                voulu = etat.get(cle, "")
                liste = self.query_one(f"#{ident}", Select)
                if liste.value == voulu:
                    continue
                if voulu not in {c for c, _ in listes[ident]}:
                    continue
                # Sans la garde, reposer la valeur relance l'evenement de
                # changement, qui renvoie une commande, qui republie un
                # etat : la boucle ne s'arrete plus.
                with liste.prevent(Select.Changed):
                    liste.value = voulu

        def _maj_signal(self, etat):
            """Remplit la vue signal : réseau, qualité, volume du modem."""
            echelle = etat.get("echelle_niveau") or 1
            dbm = etat.get("signal_dbm") or 0
            if dbm:
                # -113 dBm est le plancher du 3GPP, -51 le plafond ; la barre
                # place la mesure entre les deux.
                part = max(0, min(62, dbm + 113))
                self.query_one("#s_dbm", Static).update(f"{dbm} dBm")
                self.query_one("#s_detail", Static).update(
                    barre(part, 62) + " " + (etat.get("signal_detail") or ""))
            for cle, champ, trace, histoire in (
                ("niveau_micro", "#q_micro", "#c_micro", self.histoire_mic),
                ("niveau_hp", "#q_hp", "#c_hp", self.histoire_hp),
            ):
                db = en_dbfs(etat.get(cle, 0))
                histoire.append(db)
                self.query_one(champ, Static).update(f"{db:.0f} dBFS")
                self.query_one(trace, Static).update(courbe(histoire))
            # Négatif veut dire « jamais posé », et non « réglé à zéro » :
            # afficher 0/5 ferait chercher un volume coupé là où il n'y a
            # pas de modem sous la main.
            unite = int(etat.get("gain_micro_unite", 8192)) or 8192
            for cle, champ in (("gain_micro_modem", "#v_qmic"),
                               ("gain_ecoute_modem", "#v_deco")):
                g = int(etat.get(cle, -1))
                # Le multiple de l'unite plutot que la valeur brute : 24576
                # ne dit rien, « x3.0 » se compare d'un coup d'oeil.
                self.query_one(champ, Static).update(
                    f"x{g / unite:.1f}" if g >= 0 else "—")
            cran = etat.get("volume_modem", -1)
            self.query_one("#v_clvl", Static).update(
                f"{cran}/{CLVL_MAX}" if cran is not None and cran >= 0 else "—")

        def _fin_appel(self, resultat):
            self.pilote = None
            if not self._vivante():
                return
            self.dernier_etat = {}
            self._maj_boutons()
            if not resultat:
                self._dire("■  " + t("Appel terminé"))
                return
            duree = resultat.get("duree_seconds", 0)
            if resultat.get("decroche"):
                self._dire(f"■  {t('Appel terminé')} — {duree} s")
            else:
                self._dire("✖  " + (resultat.get("erreur")
                                    or t("Appel terminé")))

        # ----- actions ---------------------------------------------------

        def _en_conversation(self):
            """Une conversation est-elle etablie ?

            Meme regle que pour les boutons : en veille le binaire tourne sans
            conversation, sa seule presence ne suffit donc pas.
            """
            return self.pilote is not None and bool(
                self.dernier_etat.get("en_ligne", True))

        def _touche(self, caractere):
            """Une touche du clavier, frappee ou cliquee.

            Pendant une conversation elle part AUSSI en tonalite, comme sur
            tout telephone : c'est ce qui permet de piloter une messagerie. Elle
            reste ajoutee au numero, pour qu'« Ajouter un appel » garde de quoi
            composer ; le prix est que le correspondant entend les chiffres
            d'un second numero, ce qu'un telephone ordinaire fait aussi.
            """
            if self._en_conversation():
                self.pilote.touches(caractere)
                self._dire("♪  " + t("modem_tui_dtmf") + " " + caractere)
            self.numero += caractere
            self._peindre()

        def action_effacer(self):
            self.numero = self.numero[:-1]
            self._peindre()

        def on_button_pressed(self, event):
            bouton = event.button.id or ""
            if bouton.startswith("k"):
                self._touche(chr(int(bouton[1:])))
            elif bouton == "appeler":
                self._demander_appel()
            elif bouton == "raccrocher":
                self._raccrocher()
            elif bouton == "ajouter":
                self._ajouter_appel()
            elif bouton == "fusionner":
                self._fusionner()
            elif bouton == "veille":
                self._veiller()
            elif bouton == "repondre":
                self._repondre()
            elif bouton in ("mic_moins", "mic_plus"):
                self._pas_gain("micro", 1 if bouton == "mic_plus" else -1)
            elif bouton in ("hp_moins", "hp_plus"):
                self._pas_gain("hp", 1 if bouton == "hp_plus" else -1)
            elif bouton == "tab_clavier":
                self._montrer("clavier")
            elif bouton == "tab_audio":
                self._montrer("audio")
            elif bouton == "tab_signal":
                self._montrer("signal")
            elif bouton in ("clvl_moins", "clvl_plus"):
                self._pas_clvl(1 if bouton == "clvl_plus" else -1)
            elif bouton in ("qmic_moins", "qmic_plus"):
                self._pas_gain_modem("micro", 1 if bouton == "qmic_plus" else -1)
            elif bouton in ("deco_moins", "deco_plus"):
                self._pas_gain_modem("ecoute", 1 if bouton == "deco_plus" else -1)
            elif bouton == "rafraichir":
                self._rafraichir_peripheriques()

        def on_switch_changed(self, event):
            if not self.pilote:
                return
            if event.switch.id == "sw_micro":
                self.pilote.micro(event.value)
            elif event.switch.id == "sw_hp":
                self.pilote.haut_parleurs(event.value)
            elif event.switch.id == "sw_echo":
                self.pilote.anti_echo(event.value)
            elif event.switch.id == "sw_fns":
                self.pilote.bruit_modem(event.value)
            elif event.switch.id == "sw_filtre":
                self.pilote.filtre(event.value)
            elif event.switch.id == "sw_sonnerie":
                self.pilote.sonnerie(event.value)

        def on_select_changed(self, event):
            if not self.pilote:
                # Le choix n'est pas perdu : il sera lu au prochain appel.
                return
            valeur = event.value if isinstance(event.value, str) else ""
            if event.select.id == "dev_entree":
                self.pilote.entree(valeur)
            elif event.select.id == "dev_sortie":
                self.pilote.sortie(valeur)

        def _pas_gain(self, quoi, sens):
            """Décale le volume d'un pas depuis la valeur PUBLIÉE.

            On part de l'état du binaire et non du texte affiché : lire son
            propre affichage pour décider fait dériver dès qu'un rendu
            échoue, et le widget ne rend pas toujours sa valeur.
            """
            if not self.pilote:
                return
            cle = "gain_micro" if quoi == "micro" else "gain_hp"
            valeur = int(self.dernier_etat.get(cle, 100))
            plafond = int(self.dernier_etat.get("gain_max", GAIN_MAX_DEFAUT))
            valeur = max(GAIN_MIN, min(plafond, valeur + sens * PAS_GAIN))
            if quoi == "micro":
                self.pilote.gain_micro(valeur)
            else:
                self.pilote.gain_hp(valeur)

        def _pas_clvl(self, sens):
            """Décale le volume DU MODEM d'un cran.

            Six crans seulement, mais ils valent mieux que le gain logiciel :
            ils amplifient avant que le souffle ne s'ajoute, là où un gain
            appliqué après coup multiplie les deux également.
            """
            if not self.pilote:
                return
            cran = int(self.dernier_etat.get("volume_modem", CLVL_MAX))
            cran = max(CLVL_MIN, min(CLVL_MAX, cran + sens))
            self.pilote.volume_modem(cran)

        def _pas_gain_modem(self, sens_flux, sens):
            """Décale un gain DU MODEM, montée ou descente.

            Ils amplifient dans le modem, là où le gain logiciel amplifie
            après la capture : à niveau égal, ce qui passe y perd moins de
            qualité, le souffle n'étant pas multiplié avec la voix.
            """
            if not self.pilote:
                return
            unite = int(self.dernier_etat.get("gain_micro_unite", 8192))
            cle = ("gain_micro_modem" if sens_flux == "micro"
                   else "gain_ecoute_modem")
            actuel = int(self.dernier_etat.get(cle, -1))
            if actuel < 0:
                actuel = unite
            # Un demi-pas d'unité : assez pour s'entendre, assez fin pour
            # trouver le point avant la saturation.
            valeur = max(0, min(QMIC_MAX, actuel + sens * (unite // 2)))
            if sens_flux == "micro":
                self.pilote.gain_micro_modem(valeur)
            else:
                self.pilote.gain_ecoute_modem(valeur)

        def _rafraichir_peripheriques(self):
            """Relit les listes sans quitter, ni interrompre l'appel.

            ALSA n'annonce pas les branchements : les listes sont lues une
            fois au demarrage, et un casque branche apres ne s'y trouve pas.

            Le choix courant est RETABLI s'il existe encore. Sans cela,
            relire la liste ramenerait au peripherique du systeme, ce qui,
            en pleine conversation, coupe le son sans prevenir.
            """
            for ident, lister in (("dev_entree", audio_mod.entrees),
                                  ("dev_sortie", audio_mod.sorties)):
                liste = lister(carte_modem)
                listes[ident] = liste
                widget = self.query_one(f"#{ident}", Select)
                avant = widget.value if isinstance(widget.value, str) else ""
                widget.set_options([(lib, cle) for cle, lib in liste])
                connus = {cle for cle, _ in liste}
                if avant and avant not in connus:
                    self._dire("⚠  " + t("modem_tui_refresh_lost") % avant)
                    avant = ""
                # On repose la valeur SANS relancer l'evenement : reposer la
                # meme enverrait au binaire un changement qui n'en est pas
                # un, et rouvrirait le flux pour rien.
                with widget.prevent(Select.Changed):
                    widget.value = avant
            self._dire("·  " + t("modem_tui_refresh_done")
                       % (len(listes["dev_entree"]), len(listes["dev_sortie"])))

        def _peripheriques_choisis(self):
            entree = self.query_one("#dev_entree", Select).value
            sortie = self.query_one("#dev_sortie", Select).value
            return (entree if isinstance(entree, str) else "",
                    sortie if isinstance(sortie, str) else "")

        def _demander_appel(self):
            if self.pilote:
                self._dire("·  " + t("Un appel est deja en cours"))
                return
            norm = calls_mod.numero_valide(self.numero)
            if not norm:
                self._dire("✖  " + t("Numéro invalide, appel refusé"))
                return
            if not sipgo_mod.installe():
                self._dire("✖  " + t("voip_not_installed"))
                return
            micro = self.query_one("#sw_micro", Switch).value
            args = sipgo_mod.commande_appel(norm, combine=True, micro=micro,
                                            pilotage=True)
            # Le journal REPETE le numero normalise : c'est lui qui part, pas
            # la suite de touches telle qu'elle a ete tapee.
            self._dire("▶  " + t("Appel de") + f" +{norm} …")
            pilote = sipgo_mod.PiloteAppel(
                args,
                sur_etat=lambda e: self.call_from_thread(self._maj_etat, e),
                sur_fin=lambda r: self.call_from_thread(self._fin_appel, r),
                sur_journal=lambda m: self.call_from_thread(self._dire, m),
            )
            if not pilote.demarrer():
                self._dire("✖  " + t("voip_call_fail"))
                return
            self.pilote = pilote
            self._maj_boutons()
            entree, sortie = self._peripheriques_choisis()
            if entree:
                pilote.entree(entree)
            if sortie:
                pilote.sortie(sortie)

        def _veiller(self):
            """Tient la ligne, prete a decrocher.

            Le binaire garde le port AT et la carte du modem pour toute la
            duree : on le dit, car plus rien d'autre ne pourra composer ni
            interroger le modem pendant ce temps.
            """
            if self.pilote:
                return
            if not sipgo_mod.installe():
                self._dire("✖  " + t("voip_not_installed"))
                return
            self._dire("·  " + t("modem_tui_standby_on"))
            pilote = sipgo_mod.PiloteAppel(
                sipgo_mod.commande_veille(),
                sur_etat=lambda e: self.call_from_thread(self._maj_etat, e),
                sur_fin=lambda r: self.call_from_thread(self._fin_appel, r),
                sur_journal=lambda m: self.call_from_thread(self._dire, m),
            )
            if not pilote.demarrer():
                self._dire("✖  " + t("voip_call_fail"))
                return
            self.pilote = pilote
            self._maj_boutons()
            entree, sortie = self._peripheriques_choisis()
            if entree:
                pilote.entree(entree)
            if sortie:
                pilote.sortie(sortie)

        def _repondre(self):
            if not self.pilote:
                return
            self._dire("▶  " + t("Repondre"))
            self.pilote.repondre()

        def _ajouter_appel(self):
            """Compose un second numéro pendant l'appel en cours.

            Le premier passe en attente, et c'est LE RÉSEAU qui le fait : le
            modem ne mélange rien, il transmet la demande.
            """
            if not self.pilote:
                return
            norm = calls_mod.numero_valide(self.numero)
            if not norm:
                self._dire("✖  " + t("Numéro invalide, appel refusé"))
                return
            self._dire("▶  " + t("Appel de") + f" +{norm} …")
            self.pilote.composer(norm)
            self.numero = ""
            self._peindre()

        def _fusionner(self):
            if not self.pilote:
                return
            self._dire("·  " + t("modem_tui_merge_hint"))
            self.pilote.fusionner()

        def _raccrocher(self):
            if self.pilote:
                # Le binaire tient la ligne : c'est a lui de la rendre, par
                # ATH et par la fermeture du canal voix.
                pilote, self.pilote = self.pilote, None
                self.dernier_etat = {}
                self._maj_boutons()
                threading.Thread(target=pilote.raccrocher,
                                 daemon=True).start()
                return
            # Aucun appel de cette interface : il reste la commande AT, qui
            # raccroche ce qui traine par ailleurs.
            self._dire("·  " + t("Raccroché"))
            threading.Thread(target=calls_mod.raccrocher, daemon=True).start()

        def on_unmount(self):
            # Quitter ne doit pas laisser un appel ouvert derriere soi.
            if self.pilote:
                self.pilote.raccrocher()

    _ = device_mod  # index_modem sert a l'appelant, pas ici
    Poste().run()
    return True
