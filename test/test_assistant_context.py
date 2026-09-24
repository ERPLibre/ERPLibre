#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que le contexte déclaré d'un gpt n'a pas le droit de lire, ni de taire.

Deux portes se contournent par le nom, et ce fichier les ferme. « Suivi par
git » et « ignoré par git » n'en sont ni l'une ni l'autre : `private/` est
partiellement suivi, `tasks/` n'est pas dans `.gitignore`. Et un lien
symbolique au nom anodin pointant dans `private/` traverserait une liste de
refus comparée sur le nom — d'où la résolution du chemin RÉEL avant toute
comparaison.

Le filtre du dépôt reconnaît les adresses, les courriels et les chemins de
compte. Il ne reconnaît PAS les noms — d'hôte, de client, de base — sauf si
une liste les énumère, et cette liste n'existe pas d'ordinaire. Une absence
de trouvaille ne prouve donc rien sur les noms, et la porte doit refuser un
tiers dans ce cas plutôt que de laisser croire à un contrôle complet.

Aucun test ne lit le disque de la machine ni ne lance de vraie commande : la
racine, le lecteur, le lanceur et la liste des termes sont tous injectés. Les
valeurs identifiantes des cas sont INVENTÉES — une règle qui interdit de
nommer ne se cite pas elle-même en clair, et un test fige pour toujours ce
qu'il porte.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from script.todo.assistant import context as C  # noqa: E402

# Une adresse et un compte INVENTÉS, vérifiés absents du reste du dépôt.
#
# L'adresse n'est PAS prise dans un bloc documentaire : le filtre écarte
# volontairement ceux-là, donc une adresse d'exemple y serait trop sage pour
# l'exercer. Elle est dans une plage privée, ce qui la rend indiscernable
# d'une machine réelle POUR LE FILTRE — et c'est ce qu'un test de filtre doit
# lui présenter — tout en n'en désignant aucune.
ADRESSE = "10.83.4.19"
COMPTE = "/home/quelquun-invente/notes"

# Une commande de la liste d'autorisation, et une qui n'y est pas.
PERMISE = ["git", "log", "-3"]
REFUSEE = ["curl", "http://ailleurs.invalid"]


class LesCheminsRefuses(unittest.TestCase):
    """La liste de refus, résolue sur le chemin réel."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        for dossier in ("private", "tasks", ".git", ".ssh", ".venv.erplibre"):
            (self.base / dossier).mkdir()
            (self.base / dossier / "dedans.txt").write_text("x")
        (self.base / "ordinaire.txt").write_text("du contenu")
        (self.base / "coffre.kdbx").write_text("x")

    def _refus(self, chemin):
        with self.assertRaises(C.ContextRefused) as pris:
            C.resolve_file(chemin, root=self.base)
        return str(pris.exception)

    def test_private_est_refuse_meme_s_il_est_suivi_par_git(self):
        """`private/` porte des fichiers suivis : « est-ce ignoré » n'est
        donc pas la question, et ne peut pas être la porte."""
        self.assertIn("private", self._refus("private/dedans.txt"))

    def test_tasks_est_refuse_meme_s_il_n_est_pas_gitignore(self):
        """`tasks/` n'est pas dans `.gitignore` : il n'est pas suivi parce
        qu'il n'existe pas encore, ce qui n'est pas une garantie."""
        self.assertIn("tasks", self._refus("tasks/dedans.txt"))

    def test_le_depot_git_le_coffre_ssh_et_le_venv_sont_refuses(self):
        for chemin in (
            ".git/dedans.txt",
            ".ssh/dedans.txt",
            ".venv.erplibre/dedans.txt",
        ):
            self.assertTrue(self._refus(chemin))

    def test_un_chemin_de_kdbx_est_refuse(self):
        self.assertIn("suffixe", self._refus("coffre.kdbx"))

    def test_un_chemin_hors_du_depot_est_refuse(self):
        """« ../ » est le chemin le plus court vers le répertoire personnel."""
        self.assertIn("hors du dépôt", self._refus("../ailleurs.txt"))

    def test_un_lien_symbolique_vers_private_est_refuse(self):
        """Le cas que la comparaison sur le nom laisserait passer : le nom du
        lien est anodin, sa cible ne l'est pas."""
        lien = self.base / "innocent.txt"
        lien.symlink_to(self.base / "private" / "dedans.txt")
        self.assertIn("private", self._refus("innocent.txt"))

    def test_un_chemin_ordinaire_passe(self):
        """Sans ce cas, une liste qui refuse tout passerait les autres."""
        reel = C.resolve_file("ordinaire.txt", root=self.base)
        self.assertEqual(reel.name, "ordinaire.txt")


class LesCommandes(unittest.TestCase):
    """Un argv, jamais une chaîne, et jamais hors de la liste."""

    def test_une_commande_est_un_argv_jamais_une_chaine_shell(self):
        """Une chaîne voudrait dire qu'un interpréteur la relira."""
        with self.assertRaises(C.ContextRefused) as pris:
            C.check_argv("git diff")
        self.assertIn("liste", str(pris.exception))

    def test_une_commande_vide_est_refusee(self):
        with self.assertRaises(C.ContextRefused):
            C.check_argv([])

    def test_un_metacaractere_dans_un_argument_est_refuse_pas_echappe(self):
        """Sans interpréteur il n'y a rien à injecter : ce refus dit que
        l'auteur croyait écrire du shell, donc que son gpt ne fera pas ce
        qu'il voulait."""
        with self.assertRaises(C.ContextRefused) as pris:
            C.check_argv(["git", "diff", "--cached;whoami"])
        self.assertIn("métacaractère", str(pris.exception))

    def test_une_commande_hors_liste_est_refusee(self):
        with self.assertRaises(C.ContextRefused) as pris:
            C.check_argv(REFUSEE)
        self.assertIn("autorisation", str(pris.exception))

    def test_un_argument_non_textuel_est_refuse(self):
        with self.assertRaises(C.ContextRefused):
            C.check_argv(["git", "log", 3])

    def test_une_commande_permise_est_rendue_telle_quelle(self):
        self.assertEqual(C.check_argv(PERMISE), tuple(PERMISE))

    def test_la_liste_d_autorisation_n_est_pas_vide(self):
        """Une liste vide refuserait tout, et les tests de refus passeraient
        pour la mauvaise raison."""
        self.assertTrue(C.AUTORISEES)


class LesPlafonds(unittest.TestCase):
    """Un contexte qu'on ne peut plus relire n'est plus déclaré."""

    def test_la_coupe_se_fait_sur_une_frontiere_de_ligne_avec_une_marque(
        self,
    ):
        texte = "\n".join(f"ligne {i}" for i in range(500))
        borne = C.borner(texte, 100)
        self.assertLess(len(borne), 140)
        self.assertIn(C.MARQUE_COUPE, borne)
        corps = borne.replace("\n" + C.MARQUE_COUPE, "")
        self.assertTrue(corps)
        for ligne in corps.splitlines():
            self.assertTrue(ligne.startswith("ligne "), ligne)

    def test_un_texte_sous_le_plafond_n_est_pas_touche(self):
        self.assertEqual(C.borner("court", 100), "court")

    def test_le_plafond_total_arrete_l_assemblage_et_le_dit(self):
        gros = "x" * (C.MAX_PAR_SOURCE + 500)
        with tempfile.TemporaryDirectory() as dossier:
            base = Path(dossier).resolve()
            noms = []
            for rang in range(6):
                nom = f"source{rang}.txt"
                (base / nom).write_text(gros)
                noms.append(nom)
            texte, _ = C.assemble(files=noms, termes=(), root=base)
        self.assertLessEqual(len(texte), C.MAX_TOTAL + 400)
        self.assertIn(C.MARQUE_COUPE, texte)


class LeBalayage(unittest.TestCase):
    """Ce que le filtre voit, et ce qu'il ne voit pas."""

    def _assembler(self, contenu, termes=()):
        with tempfile.TemporaryDirectory() as dossier:
            base = Path(dossier).resolve()
            (base / "source.txt").write_text(contenu)
            return C.assemble(files=["source.txt"], termes=termes, root=base)

    def test_une_adresse_et_un_chemin_de_compte_sont_trouves(self):
        texte, trouvailles = self._assembler(
            f"la machine {ADRESSE} et {COMPTE}/x"
        )
        self.assertTrue(trouvailles, "le filtre n'a rien vu")
        motifs = {t["motif"] for t in trouvailles}
        self.assertIn("adresse", motifs)
        self.assertIn("compte", motifs)
        for trouvaille in trouvailles:
            self.assertEqual(trouvaille["source"], "source.txt")

    def test_un_nom_d_hote_n_est_pas_vu_sans_liste_de_termes(self):
        """La limite à connaître : le filtre ne reconnaît pas les noms. Sans
        liste, une absence de trouvaille ne prouve rien à leur sujet."""
        _, trouvailles = self._assembler("serveur-invente-01", termes=())
        self.assertEqual(trouvailles, [])

    def test_un_nom_d_hote_est_vu_quand_la_liste_le_nomme(self):
        _, trouvailles = self._assembler(
            "serveur-invente-01", termes=("serveur-invente-01",)
        )
        self.assertTrue(trouvailles)

    def test_un_fichier_refuse_est_annonce_pas_tu(self):
        """Un contexte amputé en silence fait répondre le modèle sur ce
        qu'il n'a pas reçu."""
        with tempfile.TemporaryDirectory() as dossier:
            base = Path(dossier).resolve()
            (base / "private").mkdir()
            (base / "private" / "x.txt").write_text("secret")
            texte, _ = C.assemble(
                files=["private/x.txt"], termes=(), root=base
            )
        self.assertIn("private", texte)
        self.assertNotIn("secret", texte)

    def test_un_fichier_absent_est_annonce_pas_tu(self):
        with tempfile.TemporaryDirectory() as dossier:
            texte, _ = C.assemble(
                files=["nulle-part.txt"], termes=(), root=Path(dossier)
            )
        self.assertIn("nulle-part.txt", texte)


class LesCommandesAssemblees(unittest.TestCase):
    """Le lanceur est injecté : aucun sous-processus ne part d'un test."""

    def test_la_sortie_d_une_commande_entre_dans_le_contexte(self):
        appels = []

        def lanceur(argv, delai):
            appels.append((tuple(argv), delai))
            return "trois lignes\nde sortie\nici"

        texte, _ = C.assemble(
            commands=[{"label": "Journal", "argv": PERMISE}],
            run=lanceur,
            termes=(),
        )
        self.assertEqual(len(appels), 1)
        self.assertEqual(appels[0][0], tuple(PERMISE))
        self.assertIn("Journal", texte)
        self.assertIn("de sortie", texte)

    def test_le_libelle_de_l_auteur_nomme_la_commande(self):
        """C'est cet aperçu que l'utilisateur relit avant d'envoyer."""
        texte, _ = C.assemble(
            commands=[{"label": "Trouvailles", "argv": PERMISE}],
            run=lambda argv, delai: "",
            termes=(),
        )
        self.assertIn("Trouvailles", texte)

    def test_une_commande_refusee_est_annoncee_et_non_lancee(self):
        appels = []
        texte, _ = C.assemble(
            commands=[{"argv": REFUSEE}],
            run=lambda argv, delai: appels.append(argv) or "",
            termes=(),
        )
        self.assertEqual(appels, [])
        self.assertIn("autorisation", texte)

    def test_une_commande_qui_leve_est_annoncee_pas_fatale(self):
        def lanceur(argv, delai):
            raise OSError("commande absente")

        texte, _ = C.assemble(
            commands=[{"argv": PERMISE}], run=lanceur, termes=()
        )
        self.assertIn("commande absente", texte)

    def test_le_delai_total_borne_les_commandes(self):
        """Le budget est TOTAL : trois commandes ne peuvent pas prendre trois
        fois le délai d'une seule."""
        delais = []
        C.assemble(
            commands=[{"argv": PERMISE} for _ in range(4)],
            run=lambda argv, delai: delais.append(delai) or "",
            termes=(),
        )
        self.assertTrue(delais)
        self.assertLessEqual(sum(delais), C.DELAI_TOTAL)


class LaPorte(unittest.TestCase):
    """Qui reçoit décide de ce qu'une trouvaille autorise."""

    TROUVE = [
        {
            "source": "s",
            "motif": "adresse",
            "extrait": ADRESSE,
            "position": 0,
        }
    ]

    def test_rien_a_signaler_passe(self):
        self.assertEqual(C.gate([], "loopback")[0], C.OK)
        self.assertEqual(C.gate([], "lan")[0], C.OK)

    def test_une_trouvaille_avertit_seulement_en_local(self):
        """Rien ne quitte la machine : l'opérateur décide chez lui."""
        for hote in ("loopback", "lan"):
            verdict, cle = C.gate(self.TROUVE, hote)
            self.assertEqual(verdict, C.AVERTIR, hote)
            self.assertTrue(cle)

    def test_une_trouvaille_bloque_un_tiers_sans_passe_droit(self):
        verdict, cle = C.gate(self.TROUVE, "global")
        self.assertEqual(verdict, C.BLOQUER)
        self.assertEqual(cle, C.TROUVAILLE_BLOQUE_UN_TIERS)

    def test_une_liste_de_noms_vide_refuse_un_tiers_meme_sans_trouvaille(
        self,
    ):
        """La moitié « noms » du filtre est alors inerte : l'absence de
        trouvaille ne prouve plus rien, donc elle n'autorise plus rien."""
        verdict, cle = C.gate([], "global", names_checkable=False)
        self.assertEqual(verdict, C.BLOQUER)
        self.assertEqual(
            cle,
            C.NOMS_INVERIFIABLES,
        )

    def test_une_liste_vide_n_empeche_pas_un_envoi_local(self):
        """Le refus vise la divulgation, pas la lecture : en local il n'y a
        personne à qui divulguer."""
        self.assertEqual(
            C.gate([], "loopback", names_checkable=False)[0], C.OK
        )


class LaFrontiere(unittest.TestCase):
    """Le paquet doit rester importable sans le CLI."""

    def test_le_contexte_n_importe_pas_todo(self):
        # Dans un interpréteur NEUF : la suite complète importe todo par
        # ailleurs, et le sys.modules de ce processus en garderait la trace
        # quel que soit le module éprouvé ici.
        sortie = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, script.todo.assistant.context;"
                " print('script.todo.todo' in sys.modules)",
            ],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        self.assertEqual(sortie.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
