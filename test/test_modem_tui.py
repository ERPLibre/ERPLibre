#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le poste téléphonique : ce qui se teste SANS modem ni carte son.

Deux défauts ont motivé ce fichier, et aucun des deux ne se voit en lisant
le code :

- le panneau audio SORTAIT de l'écran en quatre-vingts colonnes, parce que
  deux conteneurs se partageaient la largeur à parts égales ; les commandes
  existaient et restaient hors d'atteinte ;
- les boutons de volume lisaient la valeur affichée pour calculer la
  suivante, par un attribut de widget qui n'existe plus.

D'où la forme des tests : on CLIQUE sur chaque commande, et on vérifie que
l'affichage suit l'état publié plutôt qu'une copie locale.
"""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from textual.app import App
    from textual.widgets import Button, Switch

    TEXTUAL = True
except ImportError:  # pragma: no cover - Textual est optionnel
    TEXTUAL = False

from script.todo.modem import tui as tui_mod

#: Le plus petit terminal qu'on puisse supposer. Vérifier en grand ne prouve
#: rien : c'est en 80x24 que la mise en page casse.
TAILLE = (80, 24)

#: Les DOUZE touches, et non un échantillon : c'est une colonne entière qui
#: a disparu quand les deux vues se partageaient la largeur, et cliquer la
#: seule touche « 1 » ne l'avait pas vu.
TOUCHES = tuple(f"#k{ord(c)}" for rangée in tui_mod.TOUCHES for c in rangée)

#: Commandes de chaque vue. Une commande hors écran n'existe pas.
#: Hors appel, seul « Appeler » a un sens ; les autres sont cachés.
COMMANDES_CLAVIER = TOUCHES + ("#appeler", "#veille")
COMMANDES_AUDIO = (
    "#sw_micro", "#sw_hp", "#mic_moins", "#mic_plus",
    "#hp_moins", "#hp_plus", "#qmic_moins", "#qmic_plus",
    "#deco_moins", "#deco_plus", "#rafraichir",
    "#dev_entree", "#dev_sortie",
)
COMMANDES_SIGNAL = ("#clvl_moins", "#clvl_plus", "#sw_fns", "#sw_echo",
                    "#sw_filtre", "#sw_sonnerie")


class PiloteInerte:
    """Doublure d'un appel en cours : accepte tout, ne fait rien.

    Un simple objet ne suffit pas : l'interface raccroche en se fermant, et
    l'absence de la methode ferait echouer le demontage plutot que le test.
    """

    def __init__(self):
        self.recu = []

    def __getattr__(self, nom):
        def note(*args):
            self.recu.append((nom, args))
            return True

        return note


def construire():
    """Rend l'application que `lancer` aurait fait tourner.

    On intercepte `App.run` plutôt que de recopier la fabrique : recopier
    donnerait une seconde mise en page, et c'est la vraie qu'on veut
    éprouver.
    """
    capture = {}
    vrai_run = App.run

    def faux_run(self, *a, **k):
        capture["app"] = self
        raise SystemExit

    App.run = faux_run
    try:
        tui_mod.lancer(0)
    except SystemExit:
        pass
    finally:
        App.run = vrai_run
    return capture.get("app")


@unittest.skipUnless(TEXTUAL, "Textual absent")
class PosteTelephonique(unittest.TestCase):
    def test_barre_de_niveau(self):
        self.assertEqual(tui_mod.barre(0, 8000), "[..........]")
        self.assertEqual(tui_mod.barre(4000, 8000), "[#####.....]")
        self.assertEqual(tui_mod.barre(8000, 8000), "[##########]")
        # Au-delà de l'échelle, la barre sature au lieu de déborder.
        self.assertEqual(tui_mod.barre(99999, 8000), "[##########]")
        # Une échelle absente ne doit pas diviser par zéro.
        self.assertEqual(tui_mod.barre(10, 0), "[..........]")

    def test_toutes_les_commandes_sont_atteignables(self):
        """Etre dans l'ecran ne suffit pas : il faut etre AU-DESSUS.

        Un journal en 1fr s'est deja empare de la place et a recouvert la
        derniere rangee de touches et les boutons d'appel. Ils restaient
        dessines et cliquables sans effet, le clic atterrissant sur le
        journal — un bouton mort, sans rien dans les traces.
        """
        app = construire()
        self.assertIsNotNone(app, "l'application ne s'est pas construite")

        def couvert_par(app, cible):
            """Rend le widget reellement touche au centre de `cible`."""
            région = app.query_one(cible).region
            dessus, _ = app.get_widget_at(région.x + région.width // 2,
                                          région.y + région.height // 2)
            noeud = dessus
            while noeud is not None:
                if f"#{getattr(noeud, 'id', None)}" == cible:
                    return None
                noeud = noeud.parent
            return dessus

        async def essai():
            async with app.run_test(size=TAILLE) as pilote:
                await pilote.pause()
                for onglet, commandes in (
                    ("#tab_clavier", COMMANDES_CLAVIER),
                    ("#tab_audio", COMMANDES_AUDIO),
                    ("#tab_signal", COMMANDES_SIGNAL),
                ):
                    await pilote.click(onglet)
                    await pilote.pause()
                    # On verifie TOUT avant de cliquer quoi que ce soit :
                    # ouvrir une liste deroulante deploie un panneau qui
                    # recouvre la commande suivante, ce qui est normal et
                    # ferait echouer un controle entrelace aux clics.
                    for cible in commandes:
                        with self.subTest(vue=onglet, commande=cible):
                            écran = app.screen.region
                            région = app.query_one(cible).region
                            self.assertGreater(région.width, 0)
                            self.assertTrue(écran.contains_region(région),
                                            "hors de l'écran")
                            voleur = couvert_par(app, cible)
                            self.assertIsNone(
                                voleur,
                                f"recouvert par {getattr(voleur, 'id', voleur)}")
                    for cible in commandes:
                        await pilote.click(cible)
                        await pilote.pause()
                        # Referme un eventuel panneau deroulant.
                        await pilote.press("escape")
                        await pilote.pause()

        asyncio.run(essai())

    def test_les_rangees_du_clavier_ne_se_chevauchent_pas(self):
        """Une rangée sans hauteur déclarée se partage la place restante.

        Le symptôme ne ressemble pas à la cause : les touches se recouvrent
        au lieu de s'empiler, et une rangée disparaît sous la suivante. Le
        cliquer ne le montre pas — la géométrie, si.
        """
        app = construire()

        async def essai():
            async with app.run_test(size=TAILLE) as pilote:
                await pilote.pause()
                écran = app.screen.region
                bas = None
                for rangée in tui_mod.TOUCHES:
                    régions = [app.query_one(f"#k{ord(c)}", Button).region
                               for c in rangée]
                    for touche, r in zip(rangée, régions):
                        with self.subTest(touche=touche):
                            self.assertGreater(r.width, 0)
                            self.assertGreater(r.height, 0)
                            self.assertTrue(écran.contains_region(r))
                    # Les trois touches d'une rangée sont alignées et
                    # distinctes : sinon une colonne est perdue.
                    self.assertEqual(len({r.y for r in régions}), 1)
                    self.assertEqual(len({r.x for r in régions}), len(rangée))
                    haut = régions[0].y
                    if bas is not None:
                        self.assertGreaterEqual(
                            haut, bas,
                            "les rangées du clavier se chevauchent")
                    bas = haut + régions[0].height

        asyncio.run(essai())

    def test_repondre_a_un_appel_entrant(self):
        """Le mode veille tient la ligne ; « Repondre » n apparait qu a la
        sonnerie, et disparait une fois la conversation prise."""
        app = construire()

        def visibles():
            return {i for i in ("appeler", "veille", "repondre", "ajouter",
                                "raccrocher", "fusionner")
                    if app.query_one(f"#{i}", Button).display}

        async def essai():
            async with app.run_test(size=TAILLE) as pilote:
                await pilote.pause()
                self.assertEqual(visibles(), {"appeler", "veille"})

                # Le mode veille demarre : rien ne sonne encore.
                app.pilote = PiloteInerte()
                app._maj_etat({"type": "etat", "appel_entrant": "",
                               "en_ligne": False, "echelle_niveau": 8000})
                await pilote.pause()
                self.assertEqual(visibles(), {"raccrocher"})

                # Le telephone sonne.
                app._maj_etat({"type": "etat", "appel_entrant": "+15145550142",
                               "en_ligne": False, "echelle_niveau": 8000})
                await pilote.pause()
                self.assertEqual(visibles(), {"repondre", "raccrocher"})
                # Le numero passe AVANT ce qu'on etait en train de composer.
                self.assertIn("5145550142",
                              str(app.query_one("#numero").render()))

                # On prend l'appel.
                app._maj_etat({"type": "etat", "appel_entrant": "",
                               "en_ligne": True, "appels_voix": 1,
                               "echelle_niveau": 8000})
                await pilote.pause()
                self.assertEqual(visibles(), {"ajouter", "raccrocher"})

        asyncio.run(essai())

    def test_les_boutons_d_appel_suivent_l_etat(self):
        """Un bouton visible mais sans effet fait douter de l'appareil.

        Appeler n'a pas de sens pendant un appel, ni Raccrocher en dehors ;
        Fusionner exige deux appels, ce que seul le modem sait.
        """
        app = construire()

        def visibles():
            return {i for i in ("appeler", "ajouter", "raccrocher",
                                "fusionner")
                    if app.query_one(f"#{i}", Button).display}

        async def essai():
            async with app.run_test(size=TAILLE) as pilote:
                await pilote.pause()
                self.assertEqual(visibles(), {"appeler"})

                # Un appel sortant s'ouvre : « en ligne » y est implicite,
                # le combine ne s'ouvrant qu'une fois decroche.
                app.pilote = PiloteInerte()
                app._maj_boutons()
                await pilote.pause()
                self.assertEqual(visibles(), {"ajouter", "raccrocher"})

                # Le modem annonce un second appel : la fusion devient
                # possible, et pas avant.
                app.dernier_etat = {"appels_voix": 2}
                app._maj_boutons()
                await pilote.pause()
                self.assertEqual(visibles(),
                                 {"ajouter", "raccrocher", "fusionner"})

                # Un compte inconnu ne doit pas proposer la fusion.
                app.dernier_etat = {"appels_voix": -1}
                app._maj_boutons()
                await pilote.pause()
                self.assertNotIn("fusionner", visibles())

                # Fin de l'appel : retour au seul bouton utile.
                app.pilote = None
                app.dernier_etat = {}
                app._maj_boutons()
                await pilote.pause()
                self.assertEqual(visibles(), {"appeler"})

        asyncio.run(essai())

    def test_composer_au_clavier_physique(self):
        """Les deux entrées composent le MÊME numéro.

        La souris pour qui découvre, le clavier pour qui compose vite ; rien
        n'oblige à choisir, et les deux doivent pouvoir s'alterner au milieu
        d'un numéro.
        """
        app = construire()

        async def essai():
            async with app.run_test(size=TAILLE) as pilote:
                await pilote.pause()
                for c in "514555":
                    await pilote.press(c)
                await pilote.pause()
                self.assertEqual(app.numero, "514555")
                # On alterne : bouton, puis clavier.
                await pilote.click("#k48")
                # Une pause entre le clic et la frappe : le bouton publie son
                # message de facon differee, et l'enchainer sans repos perd
                # le chiffre du clic.
                await pilote.pause()
                await pilote.press("1", "4", "2")
                await pilote.pause()
                self.assertEqual(app.numero, "5145550142")
                # Les touches de service du clavier téléphonique aussi.
                await pilote.press("asterisk", "number_sign")
                await pilote.pause()
                self.assertEqual(app.numero, "5145550142*#")
                await pilote.press("backspace", "backspace")
                await pilote.pause()
                self.assertEqual(app.numero, "5145550142")

        asyncio.run(essai())

    def test_en_ligne_les_touches_partent_en_tonalites(self):
        """Une messagerie d'operateur se pilote au clavier : mot de passe,
        « 1 pour ecouter ». Hors appel, un chiffre ne fait que composer."""
        app = construire()

        async def essai():
            async with app.run_test(size=TAILLE) as pilote:
                await pilote.pause()
                await pilote.press("1")
                await pilote.pause()
                self.assertEqual(app.numero, "1")

                app.pilote = PiloteInerte()
                app._maj_etat({"type": "etat", "en_ligne": True,
                               "appels_voix": 1, "echelle_niveau": 8000})
                await pilote.pause()
                await pilote.press("4")
                await pilote.click("#k35")
                await pilote.pause()
                envoyees = [a[0] for nom, a in app.pilote.recu if nom == "touches"]
                self.assertEqual(envoyees, ["4", "#"])
                # Le numero garde les chiffres, pour « Ajouter un appel ».
                self.assertEqual(app.numero, "14#")

        asyncio.run(essai())

    def test_le_numero_initial_est_pose_sans_appeler(self):
        """L'appel reste un geste : on voit le numero avant de composer."""
        capture = {}
        vrai_run = App.run

        def faux_run(self, *a, **k):
            capture["app"] = self
            raise SystemExit

        App.run = faux_run
        try:
            tui_mod.lancer(0, numero_initial="+15145550142")
        except SystemExit:
            pass
        finally:
            App.run = vrai_run
        app = capture["app"]
        self.assertEqual(app.numero, "+15145550142")
        self.assertIsNone(app.pilote)

    def test_les_chiffres_n_appartiennent_pas_aux_autres_vues(self):
        """Ailleurs, un chiffre appartient au widget qui a le focus.

        Une liste déroulante s'en sert pour chercher : le lui voler rendrait
        le choix d'un périphérique impossible.
        """
        app = construire()

        async def essai():
            async with app.run_test(size=TAILLE) as pilote:
                await pilote.pause()
                await pilote.press("5", "1", "4")
                await pilote.pause()
                for vue in ("audio", "signal"):
                    await pilote.click(f"#tab_{vue}")
                    await pilote.pause()
                    avant = app.numero
                    await pilote.press("7", "8", "9")
                    await pilote.pause()
                    self.assertEqual(app.numero, avant,
                                     f"la vue {vue} a compose un numero")

        asyncio.run(essai())

    def test_entree_ne_lance_pas_un_numero_invalide(self):
        """La touche Entrée passe par la même garde que le bouton."""
        app = construire()

        async def essai():
            async with app.run_test(size=TAILLE) as pilote:
                await pilote.pause()
                await pilote.press("1", "2")
                await pilote.press("enter")
                await pilote.pause()
                self.assertIsNone(app.pilote)

        asyncio.run(essai())

    def test_une_seule_vue_a_la_fois(self):
        """Les deux vues occupent la même place et s'excluent.

        Visibles ensemble, elles se partagent la largeur et chacune y perd
        des colonnes — le clavier a ainsi perdu sa troisième rangée.
        """
        app = construire()

        async def essai():
            async with app.run_test(size=TAILLE) as pilote:
                await pilote.pause()
                self.assertTrue(app.query_one("#clavier").display)
                self.assertFalse(app.query_one("#audio").display)
                for vue in ("audio", "signal", "clavier"):
                    await pilote.click(f"#tab_{vue}")
                    await pilote.pause()
                    for autre in ("clavier", "audio", "signal"):
                        self.assertEqual(
                            app.query_one(f"#{autre}").display, autre == vue,
                            f"{autre} devrait être {'visible' if autre == vue else 'caché'}")

        asyncio.run(essai())

    def test_decibels_et_courbe(self):
        """Le décibel se compare d'une source à l'autre ; le niveau brut non."""
        self.assertEqual(tui_mod.en_dbfs(32767), 0.0)
        self.assertAlmostEqual(tui_mod.en_dbfs(3277), -20.0, places=1)
        # Un niveau nul ne doit pas faire diverger le logarithme.
        self.assertEqual(tui_mod.en_dbfs(0), tui_mod.DBFS_PLANCHER)
        self.assertEqual(tui_mod.en_dbfs(-5), tui_mod.DBFS_PLANCHER)
        # La courbe est cadrée à largeur fixe, sinon la colonne d'à côté
        # bouge au fil des mesures.
        self.assertEqual(len(tui_mod.courbe([])), tui_mod.HISTOIRE)
        self.assertEqual(len(tui_mod.courbe([-60] * 5)), tui_mod.HISTOIRE)
        pleine = tui_mod.courbe([0.0] * tui_mod.HISTOIRE)
        self.assertEqual(len(pleine), tui_mod.HISTOIRE)
        self.assertEqual(pleine[-1], tui_mod.BLOCS[-1])

    def test_la_vue_signal_suit_l_etat(self):
        app = construire()

        async def essai():
            async with app.run_test(size=TAILLE) as pilote:
                await pilote.pause()
                await pilote.click("#tab_signal")
                await pilote.pause()
                app._maj_etat({
                    "type": "etat", "micro": True, "hp": True,
                    "gain_micro": 100, "gain_hp": 100,
                    "niveau_micro": 3277, "niveau_hp": 0,
                    "entree": "", "sortie": "", "echelle_niveau": 8000,
                    "signal_dbm": -83, "signal_detail": '"LTE",1,2,3,4',
                    "volume_modem": 5, "bruit_modem": True,
                    "anti_echo": True, "gain_max": 1000,
                    "filtre_micro": False,
                    "gain_micro_modem": 20480, "gain_micro_unite": 8192,
                    "gain_ecoute_modem": 24576,
                })
                await pilote.pause()
                self.assertIn("-83", str(app.query_one("#s_dbm").render()))
                self.assertIn("LTE", str(app.query_one("#s_detail").render()))
                self.assertIn("-20", str(app.query_one("#q_micro").render()))
                self.assertIn("5/5", str(app.query_one("#v_clvl").render()))
                # Le multiple de l'unite, pas la valeur brute.
                self.assertIn("x2.5", str(app.query_one("#v_qmic").render()))
                self.assertIn("x3.0", str(app.query_one("#v_deco").render()))
                self.assertTrue(app.query_one("#sw_fns", Switch).value)
                self.assertTrue(app.query_one("#sw_echo", Switch).value)
                self.assertFalse(app.query_one("#sw_filtre", Switch).value)

        asyncio.run(essai())

    def test_le_plafond_de_gain_vient_du_binaire(self):
        """Le figer dans l'interface en donnerait deux, et elle refuserait un
        cran que le binaire accepte."""
        app = construire()
        envoyés = []

        class PiloteFactice:
            def gain_micro(self, v):
                envoyés.append(v)

            gain_hp = gain_micro

        app.pilote = PiloteFactice()
        app.dernier_etat = {"gain_micro": 980, "gain_max": 1000}
        app._pas_gain("micro", +1)
        self.assertEqual(envoyés, [1000])
        # Un plafond plus bas publié par le binaire doit être respecté.
        envoyés.clear()
        app.dernier_etat = {"gain_micro": 380, "gain_max": 400}
        app._pas_gain("micro", +1)
        self.assertEqual(envoyés, [400])

    def test_les_listes_suivent_l_etat_publie(self):
        """Un choix refuse ne doit pas rester affiche comme s'il s'appliquait.

        Le serveur audio du bureau possede les cartes de la machine et
        refuse l'ouverture directe ; le binaire revient alors au
        peripherique du systeme. Laisser la liste montrer le choix refuse
        ferait chercher le defaut ailleurs.
        """
        from textual.widgets import Select

        app = construire()

        async def essai():
            async with app.run_test(size=TAILLE) as pilote:
                await pilote.pause()
                await pilote.click("#tab_audio")
                await pilote.pause()
                liste = app.query_one("#dev_entree", Select)
                proposes = [v for _, v in liste._options if v]
                if not proposes:
                    self.skipTest("aucun peripherique a proposer")

                # L'utilisateur choisit ; le binaire l'accepte.
                app._maj_etat({"type": "etat", "entree": proposes[0],
                               "sortie": "", "echelle_niveau": 8000})
                await pilote.pause()
                self.assertEqual(liste.value, proposes[0])

                # Le binaire le refuse et revient au systeme : la liste doit
                # le montrer.
                app._maj_etat({"type": "etat", "entree": "", "sortie": "",
                               "echelle_niveau": 8000})
                await pilote.pause()
                self.assertEqual(liste.value, "")

        asyncio.run(essai())

    def test_relire_les_peripheriques_sans_quitter(self):
        """ALSA n'annonce pas les branchements : les listes sont lues une
        fois, et un casque branche apres ne s'y trouve pas."""
        from script.todo.modem import audio as audio_mod
        from textual.widgets import Select

        app = construire()
        vraies = audio_mod.entrees

        async def essai():
            async with app.run_test(size=TAILLE) as pilote:
                await pilote.pause()
                await pilote.click("#tab_audio")
                await pilote.pause()
                liste = app.query_one("#dev_entree", Select)
                avant = len(liste._options)

                # Un micro apparait.
                audio_mod.entrees = lambda ex=None: (
                    vraies(ex) + [("hw:9,0", "hw:9,0  Micro d essai")])
                await pilote.click("#rafraichir")
                await pilote.pause()
                self.assertEqual(len(liste._options), avant + 1)
                self.assertIn("hw:9,0", [v for _, v in liste._options])

                # On le choisit, puis on relit : le choix DOIT survivre.
                # Le perdre en pleine conversation couperait le son.
                liste.value = "hw:9,0"
                await pilote.click("#rafraichir")
                await pilote.pause()
                self.assertEqual(liste.value, "hw:9,0")

                # Il disparait : retour au peripherique du systeme.
                audio_mod.entrees = vraies
                await pilote.click("#rafraichir")
                await pilote.pause()
                self.assertEqual(liste.value, "")

        try:
            asyncio.run(essai())
        finally:
            audio_mod.entrees = vraies

    def test_le_gain_du_modem_part_de_l_unite_publiee(self):
        """Le gain de montee du modem s'ajuste par demi-pas d'unite.

        Partir d'un gain inconnu doit viser l'unite et non zero : un zero
        implicite couperait la voix au premier clic.
        """
        app = construire()
        envoyés = []

        class PiloteFactice:
            def gain_micro_modem(self, v):
                envoyés.append(v)

        app.pilote = PiloteFactice()
        app.dernier_etat = {"gain_micro_modem": -1, "gain_micro_unite": 8192}
        app._pas_gain_modem("micro", +1)
        self.assertEqual(envoyés, [8192 + 4096])
        envoyés.clear()
        app.dernier_etat = {"gain_micro_modem": 20000, "gain_micro_unite": 8192}
        app._pas_gain_modem("micro", -1)
        self.assertEqual(envoyés, [20000 - 4096])
        # Les bornes du modem sont respectees.
        envoyés.clear()
        app.dernier_etat = {"gain_micro_modem": 0, "gain_micro_unite": 8192}
        app._pas_gain_modem("micro", -1)
        app.dernier_etat = {"gain_micro_modem": tui_mod.QMIC_MAX,
                            "gain_micro_unite": 8192}
        app._pas_gain_modem("micro", +1)
        self.assertEqual(envoyés, [0, tui_mod.QMIC_MAX])

        # La DESCENTE a son propre gain, et sa propre commande : les
        # confondre monterait le micro en croyant monter l'ecoute.
        recus = []

        class PiloteDeux:
            def gain_micro_modem(self, v):
                recus.append(("micro", v))

            def gain_ecoute_modem(self, v):
                recus.append(("ecoute", v))

        app.pilote = PiloteDeux()
        app.dernier_etat = {"gain_ecoute_modem": 8192, "gain_micro_unite": 8192}
        app._pas_gain_modem("ecoute", +1)
        self.assertEqual(recus, [("ecoute", 8192 + 4096)])

    def test_le_volume_du_modem_reste_dans_ses_six_crans(self):
        app = construire()
        envoyés = []

        class PiloteFactice:
            def volume_modem(self, v):
                envoyés.append(v)

        app.pilote = PiloteFactice()
        app.dernier_etat = {"volume_modem": tui_mod.CLVL_MAX}
        app._pas_clvl(+1)
        app.dernier_etat = {"volume_modem": tui_mod.CLVL_MIN}
        app._pas_clvl(-1)
        self.assertEqual(envoyés, [tui_mod.CLVL_MAX, tui_mod.CLVL_MIN])

    def test_le_resume_du_son_reste_visible_sur_le_clavier(self):
        """Savoir si le micro est ouvert ne doit pas demander de changer
        d'onglet."""
        app = construire()

        async def essai():
            async with app.run_test(size=TAILLE) as pilote:
                await pilote.pause()
                app._maj_etat({
                    "type": "etat", "micro": True, "hp": False,
                    "gain_micro": 140, "gain_hp": 60,
                    "niveau_micro": 0, "niveau_hp": 0,
                    "entree": "", "sortie": "", "echelle_niveau": 8000,
                })
                await pilote.pause()
                # On est resté sur le clavier : le résumé doit tout de même
                # porter l'état du son.
                self.assertTrue(app.query_one("#clavier").display)
                resume = str(app.query_one("#resume").render())
                self.assertIn("140%", resume)
                self.assertIn("60%", resume)
                self.assertIn("ON", resume)
                self.assertIn("OFF", resume)

        asyncio.run(essai())

    def test_l_affichage_suit_l_etat_publie(self):
        app = construire()

        async def essai():
            async with app.run_test(size=TAILLE) as pilote:
                await pilote.pause()
                app._maj_etat({
                    "type": "etat", "micro": True, "hp": False,
                    "gain_micro": 140, "gain_hp": 60,
                    "niveau_micro": 4000, "niveau_hp": 8000,
                    "entree": "", "sortie": "", "echelle_niveau": 8000,
                })
                await pilote.pause()
                self.assertTrue(app.query_one("#sw_micro", Switch).value)
                self.assertFalse(app.query_one("#sw_hp", Switch).value)
                self.assertIn("140%", str(app.query_one("#g_micro").render()))
                self.assertIn("60%", str(app.query_one("#g_hp").render()))
                self.assertEqual(str(app.query_one("#n_micro").render()),
                                 "[#####.....]")
                self.assertEqual(str(app.query_one("#n_hp").render()),
                                 "[##########]")

        asyncio.run(essai())

    def test_le_volume_part_de_l_etat_publie(self):
        """Le pas de volume se calcule sur ce que le binaire a publié.

        Lire son propre affichage pour décider dérive dès qu'un rendu change
        de forme — et c'est ce qui est arrivé.
        """
        app = construire()
        app.dernier_etat = {"gain_micro": 140, "gain_hp": 60}
        envoyés = []

        class PiloteFactice:
            def gain_micro(self, v):
                envoyés.append(("micro", v))

            def gain_hp(self, v):
                envoyés.append(("hp", v))

        app.pilote = PiloteFactice()
        app._pas_gain("micro", +1)
        app._pas_gain("hp", -1)
        self.assertEqual(envoyés,
                         [("micro", 140 + tui_mod.PAS_GAIN),
                          ("hp", 60 - tui_mod.PAS_GAIN)])

    def test_le_volume_reste_dans_ses_bornes(self):
        """Plancher a zero, et plafond par defaut tant que rien n'est publie.

        L'etat manquant est le cas ordinaire au premier clic : le binaire
        n'a pas encore parle, et un plafond absent ne doit pas laisser le
        gain filer.
        """
        app = construire()
        envoyés = []

        class PiloteFactice:
            def gain_micro(self, v):
                envoyés.append(v)

            gain_hp = gain_micro

        app.pilote = PiloteFactice()
        app.dernier_etat = {"gain_micro": tui_mod.GAIN_MIN}
        app._pas_gain("micro", -1)
        app.dernier_etat = {"gain_micro": tui_mod.GAIN_MAX_DEFAUT}
        app._pas_gain("micro", +1)
        self.assertEqual(envoyés,
                         [tui_mod.GAIN_MIN, tui_mod.GAIN_MAX_DEFAUT])

    def test_un_numero_invalide_ne_lance_aucun_appel(self):
        """Une erreur de frappe ne doit pas pouvoir sonner chez un inconnu."""
        app = construire()

        async def essai():
            async with app.run_test(size=TAILLE) as pilote:
                await pilote.pause()
                app.numero = "12"
                app._demander_appel()
                await pilote.pause()
                self.assertIsNone(app.pilote)

        asyncio.run(essai())

    def test_les_peripheriques_excluent_la_carte_du_modem(self):
        """La choisir comme micro ou sortie brancherait la ligne sur
        elle-même."""
        from script.todo.modem import audio as audio_mod

        for lister in (audio_mod.entrees, audio_mod.sorties):
            with self.subTest(liste=lister.__name__):
                complet = lister()
                sans = lister(exclure_carte=0)
                self.assertTrue(
                    all(not i.startswith("hw:0,") for i, _ in sans),
                    "la carte exclue reste dans la liste")
                # Le périphérique du système reste TOUJOURS proposé : sans
                # lui, on ne pourrait plus annuler un choix.
                self.assertEqual(sans[0][0], "")
                self.assertLessEqual(len(sans), len(complet))


if __name__ == "__main__":
    unittest.main()
