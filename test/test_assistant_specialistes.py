#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le catalogue des agents spécialisés : ce qui se lit, et ce qui se refuse.

Tous les agents de ce fichier sont INVENTÉS, et vivent dans un dossier
temporaire. Aucun test ne lit `.claude/agents/` du dépôt ni le dossier
personnel de qui lance la suite : le premier changerait le verdict à chaque
agent ajouté, le second le rendrait différent d'une machine à l'autre.

Trois régressions sont visées par leur nom.

**Le fichier qui n'est pas un agent.** Un dossier d'agents porte aussi des
README et des brouillons. Les proposer au menu ferait lancer un harnais sur
un texte qui n'est pas une consigne, et la panne arriverait après l'appel.

**Le champ deviné.** Un en-tête dont la forme sort de l'ordinaire doit rendre
le champ ABSENT, pas une valeur reconstruite : un champ manquant se voit à
l'écran, une valeur inventée non.

**Les deux origines qui se doublent.** Un même nom peut venir du dépôt et du
dossier personnel. Afficher les deux ferait choisir entre deux entrées
identiques dont une seule sera lue.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.todo.assistant.agents import specialistes as sp  # noqa: E402

AGENT = """---
name: specialiste-invente
description: Use this agent to do the invented thing. Invoke when the invented case shows up.
model: modele-invente-1
tools: [Read, Grep, Bash]
---

Tu es un spécialiste inventé.
"""


class UnEnTeteDAgent(unittest.TestCase):
    def test_les_champs_declares_se_lisent(self):
        champs = sp.entete(AGENT)
        self.assertEqual("specialiste-invente", champs["name"])
        self.assertEqual("modele-invente-1", champs["model"])
        self.assertEqual("[Read, Grep, Bash]", champs["tools"])

    def test_un_markdown_sans_borne_n_est_pas_un_agent(self):
        """Un dossier d'agents porte aussi des README : lire leur corps
        rendrait des champs tirés d'un texte qui n'en déclare aucun."""
        for pas_un in ("# Un titre\n\nname: piege\n", "", "   ", None):
            with self.subTest(pas_un=pas_un):
                self.assertEqual({}, sp.entete(pas_un))

    def test_le_corps_n_est_jamais_lu(self):
        """La seconde borne ferme l'en-tête : ce qui suit appartient à
        l'invite système, où une ligne à deux-points est ordinaire."""
        champs = sp.entete(AGENT + "\nmodel: pris-dans-le-corps\n")
        self.assertEqual("modele-invente-1", champs["model"])

    def test_une_forme_inconnue_est_ignoree_et_non_devinee(self):
        texte = "---\nname: un-agent\ntools:\n  - Read\n  - Grep\n---\n"
        champs = sp.entete(texte)
        self.assertEqual("un-agent", champs["name"])
        self.assertEqual("", champs.get("tools", ""))


class UneListeDOutils(unittest.TestCase):
    def test_les_crochets_et_les_espaces_se_retirent(self):
        self.assertEqual(("A", "B", "C"), sp.liste("[A, B , C]"))

    def test_un_outil_seul_sans_crochets_reste_lisible(self):
        self.assertEqual(("Read",), sp.liste("Read"))

    def test_rien_rend_un_tuple_vide(self):
        for vide in ("", "   ", "[]", "[ , ]", None):
            with self.subTest(vide=vide):
                self.assertEqual((), sp.liste(vide))


class LeRoleEnUneLigne(unittest.TestCase):
    def test_seule_la_premiere_phrase_est_gardee(self):
        """Ce qui suit explique QUAND appeler l'agent ; une ligne de liste
        n'a la place que de dire ce qu'il fait."""
        self.assertEqual(
            "Use this agent to do the invented thing",
            sp.role(
                "Use this agent to do the invented thing."
                " Invoke when the invented case shows up."
            ),
        )

    def test_une_phrase_trop_longue_est_coupee(self):
        long = "mot " * 80
        self.assertLessEqual(len(sp.role(long)), sp.ROLE_MAX)

    def test_une_description_absente_ne_fait_pas_lever(self):
        for vide in ("", None, "   "):
            with self.subTest(vide=vide):
                self.assertEqual("", sp.role(vide))


class LeCatalogue(unittest.TestCase):
    def setUp(self):
        self.depot = tempfile.TemporaryDirectory()
        self.perso = tempfile.TemporaryDirectory()
        self.addCleanup(self.depot.cleanup)
        self.addCleanup(self.perso.cleanup)
        self.chemins = [
            ("dépôt", Path(self.depot.name)),
            ("personnel", Path(self.perso.name)),
        ]

    def _poser(self, ou, nom, texte=AGENT):
        cible = Path(ou.name) / f"{nom}.md"
        cible.write_text(texte, encoding="utf-8")
        return cible

    def test_un_agent_pose_se_retrouve_avec_ses_champs(self):
        self._poser(self.depot, "specialiste-invente")
        (un,) = sp.catalogue(chemins=self.chemins)
        self.assertEqual("specialiste-invente", un.cle)
        self.assertEqual("modele-invente-1", un.modele)
        self.assertEqual(("Read", "Grep", "Bash"), un.outils)
        self.assertEqual("dépôt", un.origine)

    def test_la_cle_est_le_nom_de_FICHIER_et_non_le_champ(self):
        """C'est le nom de fichier que le harnais va chercher ; un champ
        `name` qui en diffère ferait viser un agent qui n'existe pas."""
        self._poser(self.depot, "radical-du-fichier")
        (un,) = sp.catalogue(chemins=self.chemins)
        self.assertEqual("radical-du-fichier", un.cle)
        self.assertEqual("specialiste-invente", un.nom)

    def test_un_fichier_sans_en_tete_n_entre_pas_au_catalogue(self):
        self._poser(self.depot, "specialiste-invente")
        self._poser(self.depot, "README", "# Des agents\n\nUn mot dessus.\n")
        cles = [un.cle for un in sp.catalogue(chemins=self.chemins)]
        self.assertEqual(["specialiste-invente"], cles)

    def test_un_en_tete_sans_nom_n_entre_pas_non_plus(self):
        self._poser(
            self.depot, "brouillon", "---\ndescription: sans nom\n---\n"
        )
        self.assertEqual([], sp.catalogue(chemins=self.chemins))

    def test_le_depot_l_emporte_sur_le_personnel(self):
        """Afficher les deux ferait choisir entre deux entrées identiques
        dont une seule sera lue."""
        self._poser(self.depot, "specialiste-invente")
        self._poser(
            self.perso,
            "specialiste-invente",
            AGENT.replace("modele-invente-1", "modele-invente-2"),
        )
        (un,) = sp.catalogue(chemins=self.chemins)
        self.assertEqual("modele-invente-1", un.modele)
        self.assertEqual("dépôt", un.origine)

    def test_un_agent_personnel_seul_est_gardé_et_se_dit(self):
        self._poser(self.perso, "specialiste-a-moi")
        (un,) = sp.catalogue(chemins=self.chemins)
        self.assertEqual("personnel", un.origine)

    def test_un_dossier_absent_ne_fait_pas_lever(self):
        chemins = [("dépôt", Path("/chemin-invente/absent"))]
        self.assertEqual([], sp.catalogue(chemins=chemins))

    def test_le_catalogue_sort_par_cle(self):
        for nom in ("zeta-invente", "alpha-invente", "mu-invente"):
            self._poser(self.depot, nom)
        cles = [un.cle for un in sp.catalogue(chemins=self.chemins)]
        self.assertEqual(sorted(cles), cles)

    def test_un_fichier_illisible_est_saute(self):
        self.assertIsNone(sp.lire("/chemin-invente/absent.md"))


if __name__ == "__main__":
    unittest.main()
