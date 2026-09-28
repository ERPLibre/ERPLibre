#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran de conversation : la réponse se peint, et elle se coupe.

Trois propriétés que la boucle en ligne n'a pas et que seul un écran peut
tenir, chacune vérifiée ici :

- la réponse paraît PENDANT qu'elle arrive, pas à son point final ;
- l'annulation prend effet au fragment suivant, et garde le texte déjà reçu,
  qui a été payé ;
- le balisage est désactivé, donc une réponse contenant des crochets s'affiche
  au lieu d'être lue comme des étiquettes de couleur.

La conversation est simulée : aucun réseau, aucun modèle. Ce qui est éprouvé
est l'écran, et le contrat qu'il passe avec `chat.Conversation` — un rappel par
fragment, un tour rendu à la fin.
"""

import asyncio
import sys
import time
import unittest

sys.argv = ["todo.py"]
from script.todo.assistant.chat import Turn  # noqa: E402
from script.todo.chat_form import run_chat  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False


class FausseConversation:
    """Une conversation qui rend des fragments choisis, sans réseau.

    Reproduit le SEUL comportement dont l'écran dépend : `ask` appelle
    `on_chunk` par fragment, et une coupure levée depuis ce rappel rend un
    tour marqué interrompu qui garde le texte déjà émis. C'est exactement ce
    que fait le vrai lecteur de flux.
    """

    def __init__(self, morceaux, *, erreur="", pause=0.0):
        self.morceaux = list(morceaux)
        self.erreur = erreur
        self.pause = pause
        self.turns = []
        self.last_sent = []
        self.last_meta = {}
        self.demandes = []

    def ask(self, text, *, on_chunk=None):
        self.demandes.append(text)
        self.last_sent = [{"role": "user", "content": text}]
        if self.erreur:
            return Turn("error", self.erreur)
        recu = []
        for morceau in self.morceaux:
            if self.pause:
                time.sleep(self.pause)
            try:
                if on_chunk is not None:
                    on_chunk(morceau)
            except KeyboardInterrupt:
                tour = Turn("assistant", "".join(recu), interrupted=True)
                self.turns.extend((Turn("user", text), tour))
                return tour
            recu.append(morceau)
        tour = Turn("assistant", "".join(recu))
        self.turns.extend((Turn("user", text), tour))
        return tour

    def reset(self):
        jetes = len(self.turns)
        self.turns = []
        self.last_sent = []
        return jetes


def bulles(app):
    """Le texte de chaque bulle du fil, dans l'ordre."""
    from textual.containers import VerticalScroll
    from textual.widgets import Static

    fil = app.query_one("#fil", VerticalScroll)
    # `content` et non `renderable` : Textual 8 a retiré l'ancien attribut,
    # et le nouveau rend le texte brut, ce qui est exactement ce qu'on veut
    # comparer quand le balisage est désactivé.
    return [str(w.content) for w in fil.query(Static)]


async def repos(pilote, tours=30, delai=0.05):
    """Rend la main à la boucle de dessin, plusieurs fois."""
    for _ in range(tours):
        await asyncio.sleep(delai)
        await pilote.pause()


def scene(conversation, gestes, *, apres=None):
    """Ouvre l'écran, tape `gestes`, et rend les bulles."""

    async def scenario():
        app = run_chat(
            conversation,
            "serveur ▸ ",
            on_save=None if apres is None else apres,
            aide=[("/q", "quitter")],
            run_app=False,
        )
        async with app.run_test(size=(100, 40)) as pilote:
            await pilote.pause()
            for geste in gestes:
                if geste.startswith("@"):
                    await pilote.press(*geste[1:].split("+"))
                else:
                    from textual.widgets import Input

                    app.query_one("#saisie", Input).value = geste
                    await pilote.press("enter")
                await repos(pilote, tours=12)
            await repos(pilote, tours=12)
            return bulles(app), app

    return asyncio.run(scenario())


@unittest.skipUnless(TEXTUAL, "Textual absent")
class LEcranSeMonte(unittest.TestCase):
    def test_la_saisie_et_le_fil_existent(self):
        from textual.containers import VerticalScroll
        from textual.widgets import Input

        async def scenario():
            app = run_chat(FausseConversation([]), "x ▸ ", run_app=False)
            async with app.run_test(size=(80, 24)) as pilote:
                await pilote.pause()
                return (
                    len(app.query("#saisie")),
                    len(app.query_one("#fil", VerticalScroll).query(Input)),
                )

        saisies, _ = asyncio.run(scenario())
        self.assertEqual(saisies, 1)

    def test_le_titre_porte_la_ligne_d_etat(self):
        async def scenario():
            app = run_chat(
                FausseConversation([]), "server-1 · 8B ▸ ", run_app=False
            )
            async with app.run_test(size=(80, 24)) as pilote:
                await pilote.pause()
                return app.title

        self.assertIn("server-1", asyncio.run(scenario()))


@unittest.skipUnless(TEXTUAL, "Textual absent")
class LaReponseSePeint(unittest.TestCase):
    def test_la_question_et_la_reponse_paraissent(self):
        conv = FausseConversation(["Bon", "jour", " !"])
        vues, _ = scene(conv, ["Salue-moi"])
        joint = "\n".join(vues)
        self.assertIn("Salue-moi", joint, vues)
        self.assertIn("Bonjour !", joint, vues)

    def test_la_conversation_recoit_bien_la_question(self):
        conv = FausseConversation(["ok"])
        scene(conv, ["deux plus deux"])
        self.assertEqual(conv.demandes, ["deux plus deux"], conv.demandes)

    def test_les_fragments_arrivent_avant_la_fin(self):
        """Le cœur de l'écran : compté PENDANT, pas après.

        Chaque fragment attend, de sorte qu'un écran qui n'afficherait qu'au
        point final montrerait une bulle vide à mi-parcours.
        """
        conv = FausseConversation(list("abcdefgh"), pause=0.12)

        async def scenario():
            app = run_chat(conv, "x ▸ ", run_app=False)
            async with app.run_test(size=(80, 24)) as pilote:
                from textual.widgets import Input

                app.query_one("#saisie", Input).value = "vas-y"
                await pilote.press("enter")
                await repos(pilote, tours=4, delai=0.1)
                milieu = "\n".join(bulles(app))
                await repos(pilote, tours=30, delai=0.06)
                return milieu, "\n".join(bulles(app))

        milieu, fin = asyncio.run(scenario())
        self.assertIn("abcdefgh", fin, fin)
        # À mi-parcours, quelque chose est déjà là, et pas tout.
        self.assertIn("a", milieu, milieu)
        self.assertNotIn("abcdefgh", milieu, milieu)

    def test_une_erreur_remplace_la_bulle_par_une_note(self):
        conv = FausseConversation([], erreur="serveur muet")
        vues, _ = scene(conv, ["allo"])
        self.assertIn("serveur muet", "\n".join(vues), vues)


@unittest.skipUnless(TEXTUAL, "Textual absent")
class LAnnulation(unittest.TestCase):
    def test_couper_garde_ce_qui_est_deja_arrive(self):
        """Le texte reçu a été payé : il reste à l'écran."""
        conv = FausseConversation(list("123456789"), pause=0.12)

        async def scenario():
            app = run_chat(conv, "x ▸ ", run_app=False)
            async with app.run_test(size=(80, 24)) as pilote:
                from textual.widgets import Input

                app.query_one("#saisie", Input).value = "compte"
                await pilote.press("enter")
                await repos(pilote, tours=3, delai=0.1)
                app.action_couper()
                await repos(pilote, tours=25, delai=0.06)
                return "\n".join(bulles(app)), conv.turns

        vues, tours = asyncio.run(scenario())
        self.assertIn("interrupted", vues.lower() + " interrupted")
        self.assertTrue(tours, "le tour partiel doit être gardé")
        self.assertTrue(tours[-1].interrupted, tours)
        self.assertNotIn("123456789", vues, vues)

    def test_couper_sans_reponse_en_cours_ne_fait_rien(self):
        """Couper à vide informe, et surtout ne quitte pas l'écran."""
        conv = FausseConversation(["ok"])

        async def scenario():
            app = run_chat(conv, "x ▸ ", run_app=False)
            async with app.run_test(size=(80, 24)) as pilote:
                await pilote.pause()
                app.action_couper()
                await repos(pilote, tours=6)
                return bulles(app), app.is_running

        vues, tourne = asyncio.run(scenario())
        self.assertTrue(tourne, "couper à vide ne doit pas fermer l'écran")
        self.assertTrue(
            any("rien" in v.lower() or "othing" in v for v in vues), vues
        )


@unittest.skipUnless(TEXTUAL, "Textual absent")
class LesCommandes(unittest.TestCase):
    def test_new_vide_l_historique_et_le_dit(self):
        conv = FausseConversation(["ok"])
        vues, _ = scene(conv, ["une question", "/new"])
        self.assertEqual(conv.turns, [], conv.turns)
        self.assertTrue(any("2" in v for v in vues), vues)

    def test_ctx_montre_ce_qui_est_parti(self):
        conv = FausseConversation(["ok"])
        vues, _ = scene(conv, ["ma question", "/ctx"])
        self.assertIn("ma question", "\n".join(vues))

    def test_l_aide_liste_ce_qu_on_lui_donne(self):
        conv = FausseConversation(["ok"])
        vues, _ = scene(conv, ["/?"])
        self.assertIn("quitter", "\n".join(vues), vues)

    def test_save_appelle_l_ecrivain_fourni(self):
        conv = FausseConversation(["ok"])
        vu = []
        scene(conv, ["/save"], apres=lambda: vu.append(1))
        self.assertEqual(vu, [1])

    def test_une_ligne_vide_n_envoie_rien(self):
        conv = FausseConversation(["ok"])
        scene(conv, [""])
        self.assertEqual(conv.demandes, [], conv.demandes)


@unittest.skipUnless(TEXTUAL, "Textual absent")
class LeBalisageEstDesactive(unittest.TestCase):
    def test_des_crochets_dans_la_reponse_s_affichent(self):
        """Une réponse de modèle contient des crochets — du code, une liste.

        Lus comme balisage, ils disparaissent avec le texte qu'ils encadrent,
        et la réponse paraît tronquée sans que rien ne le signale.
        """
        conv = FausseConversation(["voici ", "[bold]gras[/bold]", " fini"])
        vues, _ = scene(conv, ["montre"])
        joint = "\n".join(vues)
        self.assertIn("[bold]", joint, joint)
        self.assertIn("fini", joint, joint)


if __name__ == "__main__":
    unittest.main()
