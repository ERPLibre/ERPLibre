#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran vivant d'une conversation : ce qu'il calcule, puis ce qu'il montre.

Deux étages, comme l'écran des agents. Les faiseuses de chaînes se vérifient
sans terminal : c'est là que se défendent les unités, les colonnes et les cas
où il n'y a rien à montrer. La dernière classe MONTE l'application et tape des
touches, parce qu'une colonne que le tableau ne demande pas, un panneau qu'on
n'affiche jamais et une saisie qui ne rend pas la main ne se voient sur aucun
dictionnaire.

Trois régressions sont visées par leur nom.

**Le zéro mis à la place d'une absence.** Un serveur qui ne rend aucun compte
de jetons n'a pas répondu « zéro ». Une colonne qui afficherait `0` ferait
lire un modèle à l'arrêt, et une moyenne le compterait.

**Le débit affiché avant d'être connu.** Le compte de jetons arrive du serveur
À LA FIN. Pendant la génération, seuls les fragments, les caractères et le
temps s'observent d'ici ; une règle de trois sur les fragments approcherait le
débit sans être lui, et l'écran présenterait une extrapolation comme une
lecture.

**Le flux mené sur la boucle d'événements.** Une génération dure des minutes.
Sur la boucle, l'écran gèle entier — touches comprises — et rien ne dit qu'il
est vivant. Un test monte l'application, pose une question dont la réponse
arrive fragment par fragment, et exige que l'écran ait continué de répondre.

Aucun test ici n'ouvre de socket ni n'écrit dans le journal réel : le backend
est un double, et l'écriture est neutralisée.
"""

import asyncio
import importlib.util
import os
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.todo.assistant import mesure as ms  # noqa: E402
from script.todo.assistant import perf_tui as pf  # noqa: E402
from script.todo.assistant.servers import Server  # noqa: E402

INSTANT = "2026-03-04T05:06:07-05:00"

SERVEUR = Server(
    handle="server-1",
    label="essai",
    host="192.0.2.21",
    port=8000,
    software="logiciel-invente",
    model="famille-inventee/modele-a",
    hosting="lan",
    secret_ref="",
)


def une_mesure(rang=1, **ecarts):
    """Une mesure d'essai, ses défauts nommés une seule fois."""
    arguments = {
        "seance": "seance-inventee",
        "rang": rang,
        "serveur": SERVEUR,
        "question": "une question inventée",
        "duree": 12.0,
        "premier": 0.5,
        "faits": {
            "usage": {"prompt_tokens": 120, "completion_tokens": 300},
            "finish_reason": "stop",
        },
        "maintenant": lambda: INSTANT,
    }
    arguments.update(ecarts)
    return ms.mesurer(**arguments)


class LesUnites(unittest.TestCase):
    def test_une_duree_courte_se_dit_en_millisecondes(self):
        """Un délai de premier jeton se compte en dizaines de millisecondes
        sur un modèle chargé ; l'arrondi à la seconde y afficherait « 0 s »,
        qui est le mensonge d'un zéro mis à la place d'une valeur."""
        self.assertEqual("338 ms", pf.secondes(0.338))
        self.assertEqual("12 ms", pf.secondes(0.0124))
        self.assertEqual("1.5 s", pf.secondes(1.546))
        self.assertEqual("1 m 12", pf.secondes(72.4))

    def test_une_absence_est_un_tiret_et_jamais_un_zero(self):
        for absent in (None, "", "douze", [], object()):
            with self.subTest(absent=absent):
                self.assertEqual(pf.INCONNU, pf.secondes(absent))
        self.assertEqual(pf.INCONNU, pf.compte(None))
        self.assertEqual(pf.INCONNU, pf.debit(None))
        self.assertNotIn("0", pf.INCONNU)

    def test_un_booleen_n_est_pas_un_compte_de_jetons(self):
        """`True` est un entier en Python, et un champ de serveur peut
        porter n'importe quoi."""
        self.assertEqual(pf.INCONNU, pf.compte(True))
        self.assertEqual("0", pf.compte(0))


class LeTableauDesTours(unittest.TestCase):
    def test_chaque_tour_rend_une_ligne_complete(self):
        (ligne,) = pf.lignes([une_mesure()])
        self.assertEqual("1", ligne["rang"])
        self.assertEqual("12.0 s", ligne["duree"])
        self.assertEqual("120", ligne["invite"])
        self.assertEqual("300", ligne["reponse"])
        self.assertEqual("25.0", ligne["debit"])
        self.assertEqual("500 ms", ligne["premier"])
        self.assertEqual("stop", ligne["fin"])

    def test_chaque_colonne_annoncee_est_remplie(self):
        """Une colonne que le tableau demande et que la ligne ne porte pas
        lève à la pose, ce qui ferme l'application entière."""
        (ligne,) = pf.lignes([une_mesure()])
        for cle, _titre in pf.COLONNES:
            with self.subTest(cle=cle):
                self.assertIn(cle, ligne)

    def test_la_cle_est_distincte_des_colonnes_affichees(self):
        """Une clé en double lève dans le tableau, et une exception dans un
        gestionnaire de message ferme l'application entière."""
        lignes = pf.lignes([une_mesure(rang=n) for n in (1, 2, 3)])
        cles = [ligne["cle"] for ligne in lignes]
        self.assertEqual(len(cles), len(set(cles)))
        self.assertNotIn("cle", dict(pf.COLONNES))

    def test_un_tour_sans_compte_montre_des_tirets(self):
        (ligne,) = pf.lignes([une_mesure(faits={})])
        self.assertEqual(pf.INCONNU, ligne["reponse"])
        self.assertEqual(pf.INCONNU, ligne["debit"])

    def test_une_coupure_et_une_panne_priment_sur_la_raison_du_serveur(self):
        """Un tour coupé à la main porte souvent « stop » dans ses faits, et
        le lecteur veut savoir que c'est LUI qui a coupé."""
        from script.todo.todo_i18n import t

        coupe = une_mesure(interrompu=True)
        self.assertEqual(t("cut"), pf.lignes([coupe])[0]["fin"])
        rate = une_mesure(erreur="BackendError")
        self.assertEqual(t("error"), pf.lignes([rate])[0]["fin"])
        # La raison du serveur reste visible quand rien ne la couvre.
        self.assertEqual("stop", pf.lignes([une_mesure()])[0]["fin"])

    def test_aucun_tour_ne_rend_aucune_ligne(self):
        self.assertEqual([], pf.lignes([]))
        self.assertEqual([], pf.lignes(None))


class LesColonnesQuiTiennent(unittest.TestCase):
    def test_un_terminal_etroit_garde_au_moins_le_tour_et_la_duree(self):
        """Un tableau qui ne dirait ni de quel tour ni de quelle durée il
        parle ne dirait rien du tout."""
        for largeur in (0, 1, 12, 20):
            with self.subTest(largeur=largeur):
                self.assertEqual(2, len(pf.colonnes_visibles(largeur)))

    def test_un_terminal_large_les_montre_toutes(self):
        self.assertEqual(len(pf.COLONNES), len(pf.colonnes_visibles(200)))

    def test_les_colonnes_gardent_leur_ordre_d_importance(self):
        voulues = pf.colonnes_visibles(48)
        self.assertEqual(pf.COLONNES[: len(voulues)], voulues)


class LeResume(unittest.TestCase):
    def test_il_dit_combien_de_tours_n_ont_pas_de_compte(self):
        """Un total qui porte sur une partie des tours, sans dire laquelle,
        se lit comme un total sur l'ensemble."""
        texte = pf.resume([une_mesure(rang=1), une_mesure(rang=2, faits={})])
        self.assertIn("300", texte)
        self.assertIn("1", texte)

    def test_sans_aucun_compte_il_n_annonce_aucun_jeton(self):
        from script.todo.todo_i18n import t

        texte = pf.resume([une_mesure(faits={})])
        self.assertNotIn(t("%s tokens") % 0, texte)

    def test_le_nom_s_accorde_sur_le_nombre(self):
        """« 1 tours » se lit comme un défaut de l'outil, et c'est alors la
        seule chose qu'on retienne de la ligne."""
        from script.todo.todo_i18n import t

        self.assertEqual(f"1 {t('turn')}", pf.accord(1, "turn", "turns"))
        self.assertEqual(f"2 {t('turns')}", pf.accord(2, "turn", "turns"))
        self.assertEqual(f"0 {t('turns')}", pf.accord(0, "turn", "turns"))
        un = pf.resume([une_mesure(faits={"usage": {"completion_tokens": 1}})])
        self.assertIn(f"1 {t('turn')}", un)
        self.assertIn(f"1 {t('token')}", un)

    def test_une_seance_vide_le_dit(self):
        self.assertTrue(pf.resume([]))
        self.assertTrue(pf.resume(None))


class LePiedEtLeFlux(unittest.TestCase):
    def test_le_pied_porte_ce_que_le_tour_a_coute(self):
        texte = pf.pied(une_mesure())
        for attendu in ("12.0 s", "300", "25.0", "500 ms"):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, texte)

    def test_un_envoi_d_un_bloc_n_annonce_pas_un_premier_jeton(self):
        """Un zéro y ferait croire à une réponse instantanée."""
        texte = pf.pied(une_mesure(premier=None))
        self.assertNotIn(pf.INCONNU, texte)
        self.assertNotIn("0 ms", texte)

    def test_le_panneau_vivant_ne_parle_jamais_de_jetons(self):
        """Le compte vient du serveur, à la fin. Une règle de trois sur les
        fragments l'approcherait sans être lui, et l'écran présenterait une
        extrapolation comme une lecture."""
        texte = pf.en_cours(142, 830, 5.3, 0.31)
        self.assertIn("142", texte)
        self.assertIn("830", texte)
        self.assertIn("5.3 s", texte)
        for interdit in ("tok/s", "j/s", "tokens", "jetons"):
            with self.subTest(interdit=interdit):
                self.assertNotIn(interdit, texte)

    def test_le_panneau_vivant_tient_avant_le_premier_fragment(self):
        """Entre l'envoi et le premier jeton, il n'y a rien à compter et le
        temps avance quand même : c'est là qu'un écran figé se distingue mal
        d'un écran mort."""
        texte = pf.en_cours(0, 0, 0.4, None)
        self.assertIn("400 ms", texte)


class LaTranscription(unittest.TestCase):
    """Ce qui s'est DIT, et pas seulement ce que ça a coûté."""

    class Tour:
        def __init__(self, role, text, interrupted=False):
            self.role = role
            self.text = text
            self.interrupted = interrupted

    def test_les_questions_et_les_reponses_paraissent_toutes_deux(self):
        """Un écran qui ne montrerait que des chiffres obligerait à quitter
        pour relire la réponse qu'on vient de demander, et l'historique meurt
        avec le menu."""
        turns = [
            self.Tour("user", "première question inventée"),
            self.Tour("assistant", "première réponse inventée"),
            self.Tour("user", "seconde question inventée"),
            self.Tour("assistant", "seconde réponse inventée"),
        ]
        texte = pf.echange(turns)
        for attendu in (
            "première question inventée",
            "première réponse inventée",
            "seconde question inventée",
            "seconde réponse inventée",
        ):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, texte)
        self.assertEqual(2, texte.count(pf.MARQUE_QUESTION))

    def test_le_tour_en_cours_se_pose_en_dernier(self):
        """La réponse grandit à chaque fragment : la relire depuis le début
        obligerait à remonter à chaque mot."""
        turns = [
            self.Tour("user", "ancienne question"),
            self.Tour("assistant", "ancienne réponse"),
        ]
        texte = pf.echange(turns, "question en cours", "début de rép")
        self.assertTrue(texte.endswith("début de rép"))
        self.assertLess(
            texte.index("ancienne question"), texte.index("question en cours")
        )

    def test_une_reponse_coupee_se_marque(self):
        """Ce qui est arrivé a été payé ; le lire comme une réponse entière
        ferait croire le modèle plus bref qu'il n'est."""
        from script.todo.todo_i18n import t

        turns = [self.Tour("assistant", "moitié de rép", interrupted=True)]
        self.assertIn(t("cut"), pf.echange(turns))
        entier = [self.Tour("assistant", "réponse entière")]
        self.assertNotIn(t("cut"), pf.echange(entier))

    def test_une_conversation_vide_ne_fait_pas_lever(self):
        self.assertEqual("", pf.echange([]))
        self.assertEqual("", pf.echange(None))


class LesClesDeTraduction(unittest.TestCase):
    """La garde AST du menu ne balaie QUE `assistant_menu.py`.

    Une chaîne affichée depuis ce module-ci lui échappe, et s'afficherait en
    anglais dans une séance française sans que rien ne tombe en rouge.
    """

    def test_chaque_cle_de_l_ecran_est_declaree(self):
        import ast

        from script.todo.todo_i18n import TRANSLATIONS

        with open(pf.__file__, encoding="utf-8") as fichier:
            source = ast.parse(fichier.read())
        cles = set()
        for noeud in ast.walk(source):
            if (
                isinstance(noeud, ast.Call)
                and isinstance(noeud.func, ast.Name)
                and noeud.func.id == "t"
                and noeud.args
                and isinstance(noeud.args[0], ast.Constant)
                and isinstance(noeud.args[0].value, str)
            ):
                cles.add(noeud.args[0].value)
        # Les titres de colonnes passent par une variable : la marche de
        # l'arbre ne les voit pas, et ce sont eux qu'on oublie.
        cles.update(titre for _cle, titre in pf.COLONNES)
        self.assertTrue(cles, "aucune clé relevée : le module a changé")
        self.assertEqual(
            [], sorted(cle for cle in cles if cle not in TRANSLATIONS)
        )


class FauxBackend:
    """Un backend qui rend son texte fragment par fragment, sans socket."""

    keeps_history = False

    def __init__(self, morceaux=("bon", "jour"), usage=None):
        self.morceaux = morceaux
        self.usage = usage or {"prompt_tokens": 7, "completion_tokens": 2}

    def send(self, messages, *, on_chunk=None):
        for morceau in self.morceaux:
            if on_chunk is not None:
                on_chunk(morceau)
        return "".join(self.morceaux), {
            "model": SERVEUR.model,
            "usage": dict(self.usage),
            "finish_reason": "stop",
        }


async def calme(pilote, tours=3):
    """Rendre la main jusqu'à ce que le travailleur ait posé son résultat.

    La génération se fait HORS de la boucle d'événements. Une simple pause
    rend la main avant que le fil ait rien posé, et le test lirait un écran
    encore vide.
    """
    for _ in range(tours):
        await pilote.pause()
        await pilote.app.workers.wait_for_complete()
        await pilote.pause()


@unittest.skipUnless(
    importlib.util.find_spec("textual") is not None, "textual absent"
)
class LEcranTourneVraiment(unittest.IsolatedAsyncioTestCase):
    """Le montage, la saisie, le flux et le retour — avec un vrai pilote."""

    def _app(self, mesures=None, backend=None):
        from script.todo.assistant import chat as llm_chat

        conversation = llm_chat.Conversation(backend or FauxBackend())
        return pf.run_tui(
            conversation,
            SERVEUR,
            mesures=mesures if mesures is not None else [],
            seance="seance-inventee",
            journal=lambda _m: None,
            run_app=False,
        )

    async def test_le_montage_ne_touche_pas_le_reseau(self):
        """L'écran s'ouvre sur ce qui est déjà mesuré ; la première requête
        part d'une question tapée, jamais du montage."""

        class Interdit(FauxBackend):
            def send(self, messages, *, on_chunk=None):
                raise AssertionError("le montage a parlé au serveur")

        app = self._app(backend=Interdit())
        async with app.run_test(size=(160, 40)) as pilote:
            await calme(pilote)
            self.assertTrue(app.query_one("#tours").display)

    async def test_les_tours_deja_joues_sont_au_tableau_des_l_ouverture(self):
        mesures = [une_mesure(rang=1), une_mesure(rang=2)]
        app = self._app(mesures=mesures)
        async with app.run_test(size=(160, 40)) as pilote:
            await calme(pilote)
            self.assertEqual(2, app.query_one("#tours").row_count)

    async def test_une_question_posee_ajoute_son_tour_et_le_mesure(self):
        mesures = []
        app = self._app(mesures=mesures)
        async with app.run_test(size=(160, 40)) as pilote:
            await calme(pilote)
            app.query_one("#saisie").value = "une question inventée"
            await pilote.press("enter")
            await calme(pilote)
            self.assertEqual(1, app.query_one("#tours").row_count)
        self.assertEqual(1, len(mesures))
        self.assertEqual(2, mesures[0].reponse)
        self.assertIsNotNone(mesures[0].premier)

    async def test_le_rang_continue_celui_de_l_invite_texte(self):
        """L'écran reprend la conversation en cours : une séance a une seule
        suite de rangs, et repartir de un rendrait deux tours « 1 »."""
        mesures = [une_mesure(rang=1)]
        from script.todo.assistant import chat as llm_chat

        app = pf.run_tui(
            llm_chat.Conversation(FauxBackend()),
            SERVEUR,
            mesures=mesures,
            seance="seance-inventee",
            depart=len(mesures),
            journal=lambda _m: None,
            run_app=False,
        )
        async with app.run_test(size=(160, 40)) as pilote:
            await calme(pilote)
            app.query_one("#saisie").value = "une autre question"
            await pilote.press("enter")
            await calme(pilote)
        self.assertEqual([1, 2], [m.rang for m in mesures])

    async def test_une_question_vide_ne_part_pas(self):
        mesures = []
        app = self._app(mesures=mesures)
        async with app.run_test(size=(160, 40)) as pilote:
            await calme(pilote)
            app.query_one("#saisie").value = "   "
            await pilote.press("enter")
            await calme(pilote)
        self.assertEqual([], mesures)

    async def test_l_ecran_reste_vivant_pendant_la_generation(self):
        """Le mode de défaillance : une génération menée sur la boucle gèle
        l'écran entier pour toute sa durée, touches comprises."""
        commence = asyncio.Event()
        libere = asyncio.Event()
        boucle = asyncio.get_running_loop()

        class Lent(FauxBackend):
            def send(self, messages, *, on_chunk=None):
                boucle.call_soon_threadsafe(commence.set)
                # Le fil attend ; si la boucle était bloquée, le test
                # n'arriverait jamais jusqu'au relâchement.
                while not libere.is_set():
                    import time

                    time.sleep(0.01)
                return "fini", {"usage": {"completion_tokens": 1}}

        app = self._app(backend=Lent())
        async with app.run_test(size=(160, 40)) as pilote:
            await pilote.pause()
            app.query_one("#saisie").value = "une question lente"
            await pilote.press("enter")
            await asyncio.wait_for(commence.wait(), timeout=5)
            # L'écran répond ENCORE, alors que la génération n'est pas finie.
            await pilote.pause()
            self.assertTrue(app.query_one("#echange").display)
            boucle.call_soon_threadsafe(libere.set)
            await calme(pilote)
            self.assertIn("fini", str(app.query_one("#echange").render()))

    async def test_aucun_raccourci_n_est_avale_par_la_saisie(self):
        """Le mode de défaillance : la saisie garde le focus pendant toute la
        vie de l'écran — c'est de là qu'on pose ses questions — donc une
        LETTRE NUE s'écrit dans le champ au lieu d'atteindre son action, et
        le raccourci passe pour mort sans que rien ne le signale."""
        app = self._app()
        async with app.run_test(size=(160, 40)) as pilote:
            await calme(pilote)
            self.assertTrue(app.BINDINGS, "aucun raccourci déclaré")
            for touche, _action, _nom in app.BINDINGS:
                with self.subTest(touche=touche):
                    self.assertNotEqual(
                        1, len(touche), f"« {touche} » s'écrira dans la saisie"
                    )
            for touche, _action, _nom in app.BINDINGS:
                if touche.startswith("ctrl+") and touche != "ctrl+c":
                    await pilote.press(touche)
                    await pilote.pause()
            self.assertEqual("", app.query_one("#saisie").value)

    async def test_le_tableau_des_durees_se_replie(self):
        """Les durées et le texte se disputent la hauteur d'un terminal, et
        ce qu'on veut voir change selon qu'on lit ou qu'on compare."""
        app = self._app(mesures=[une_mesure()])
        async with app.run_test(size=(160, 40)) as pilote:
            await calme(pilote)
            self.assertTrue(app.query_one("#tours").display)
            await pilote.press("ctrl+t")
            await pilote.pause()
            self.assertFalse(app.query_one("#tours").display)
            await pilote.press("ctrl+t")
            await pilote.pause()
            self.assertTrue(app.query_one("#tours").display)

    async def test_la_conversation_reste_a_l_ecran_apres_le_tour(self):
        """Le tour clos, la question et la réponse restent lisibles : les
        chiffres disent ce qu'il a coûté, jamais ce qui s'est dit."""
        app = self._app(backend=FauxBackend(morceaux=("bon", "soir")))
        async with app.run_test(size=(160, 40)) as pilote:
            await calme(pilote)
            app.query_one("#saisie").value = "une question inventée"
            await pilote.press("enter")
            await calme(pilote)
            vu = str(app.query_one("#echange").render())
        self.assertIn("une question inventée", vu)
        self.assertIn("bonsoir", vu)

    async def test_un_terminal_etroit_ne_pose_que_ce_qui_tient(self):
        app = self._app(mesures=[une_mesure()])
        async with app.run_test(size=(30, 24)) as pilote:
            await calme(pilote)
            self.assertEqual(2, len(app.query_one("#tours").columns))


if __name__ == "__main__":
    unittest.main()
