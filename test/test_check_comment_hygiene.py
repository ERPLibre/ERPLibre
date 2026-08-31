#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'outil voit-il ce qu'il doit, et se tait-il sur le reste ?

Un outil de style qui crie pour rien se fait ignorer en entier : ces tests
pèsent donc les silences autant que les trouvailles. Le présent de l'indicatif
(« mesure le temps »), une version Odoo à quatre nombres, la boucle locale et
un chemin en gabarit doivent passer sans un mot.

La part qu'aucun motif ne juge — « cette phrase énonce-t-elle un fait durable
ou raconte-t-elle une journée » — n'est pas testée : elle n'est pas décidable.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "script", "analyse")
)

import check_comment_hygiene as hygiene  # noqa: E402

OUTIL = os.path.join(
    os.path.dirname(__file__),
    "..",
    "script",
    "analyse",
    "check_comment_hygiene.py",
)


def genres(trouvailles):
    return {f["kind"] for f in trouvailles}


def motifs(trouvailles):
    return {f["pattern"] for f in trouvailles}


class TestLesAdresses(unittest.TestCase):
    """Quatre nombres séparés par des points ne font pas une machine."""

    def test_une_adresse_de_machine(self):
        self.assertTrue(hygiene.adresse_de_machine("172.31.7.42"))
        self.assertTrue(hygiene.adresse_de_machine("172.20.4.9"))

    def test_une_version_odoo(self):
        for version in ("18.0.1.3", "17.0.1.0", "12.0.2.1"):
            self.assertFalse(hygiene.adresse_de_machine(version), version)

    def test_la_boucle_locale_et_les_masques(self):
        for valeur in ("127.0.0.1", "127.0.1.1", "0.0.0.0", "255.255.255.255"):
            self.assertFalse(hygiene.adresse_de_machine(valeur), valeur)

    def test_une_adresse_de_reseau(self):
        """Un dernier octet nul nomme une plage, pas un hôte."""
        self.assertFalse(hygiene.adresse_de_machine("192.168.122.0"))

    def test_les_blocs_documentaires(self):
        self.assertFalse(hygiene.adresse_de_machine("192.0.2.5"))
        self.assertFalse(hygiene.adresse_de_machine("203.0.113.9"))

    def test_un_octet_hors_bornes(self):
        self.assertFalse(hygiene.adresse_de_machine("999.1.1.1"))


class TestLeTemoignage(unittest.TestCase):
    """L'accent sépare le passé qui témoigne du présent qui décrit."""

    def _recits(self, texte):
        return hygiene.recits(texte)

    def test_le_participe_passe(self):
        for phrase in (
            "Vécu sur une machine du parc.",
            "Mesuré : trois secondes.",
            "Vécu, sur la base intermédiaire.",
            "Rapporté au premier essai.",
            "Mesuré — deux fois de suite.",
        ):
            self.assertTrue(self._recits(phrase), phrase)

    def test_le_present_de_lindicatif(self):
        """« mesure le temps » dit ce que le code fait : rien à signaler."""
        for phrase in (
            "La sonde mesure le temps de réponse.",
            "Le pilote signale au menu que l'étape est finie.",
            "L'écran constate au démarrage que le service répond.",
        ):
            self.assertEqual([], self._recits(phrase), phrase)

    def test_une_date_absolue(self):
        self.assertIn(
            "date", {t[0] for t in self._recits("Relevé le 2026-08-12.")}
        )
        self.assertIn(
            "date", {t[0] for t in self._recits("Le 24 août 2026, la VM.")}
        )

    def test_la_premiere_personne(self):
        for phrase in (
            "Ma conclusion était fausse.",
            "j'avais écrit le contraire.",
        ):
            self.assertIn(
                "personne", {t[0] for t in self._recits(phrase)}, phrase
            )

    def test_le_nom_releve_nest_pas_le_verbe(self):
        """« dans le relevé du serveur » nomme une chose, ne témoigne pas."""
        for phrase in (
            "Dans le relevé du serveur, la valeur est vide.",
            "Le constaté au démarrage sert de référence.",
        ):
            self.assertEqual([], self._recits(phrase), phrase)

    def test_hier_ne_se_trouve_pas_dans_hierarchie(self):
        for phrase in (
            "La hiérarchie des modèles.",
            "The hierarchy of models.",
        ):
            self.assertEqual([], self._recits(phrase), phrase)

    def test_reproduit_est_aussi_du_present(self):
        """Présent et participe s'écrivent pareil : le motif ne tranche pas."""
        self.assertEqual([], self._recits("Le pilote reproduit la config."))

    def test_toutes_les_occurrences_dun_bloc(self):
        """Un bloc qui répète le marqueur ne cache pas le reste du travail."""
        trouves = self._recits("Mesuré sur la base. Puis vécu sur la copie.")
        self.assertEqual(2, len({t[1].lower() for t in trouves}))


class TestLesIdentifiants(unittest.TestCase):
    def test_un_courriel(self):
        self.assertIn(
            "courriel", {t[0] for t in hygiene.identifiants("a@exemple.ca")}
        )

    def test_le_courriel_du_proprietaire_passe(self):
        self.assertEqual([], hygiene.identifiants("contact@technolibre.ca"))

    def test_un_chemin_de_compte(self):
        self.assertIn(
            "compte",
            {t[0] for t in hygiene.identifiants("/home/quelquun/git/")},
        )

    def test_un_chemin_en_gabarit_passe(self):
        for chemin in ("/home/<utilisateur>/git/", "/home/$USER/git/"):
            self.assertEqual([], hygiene.identifiants(chemin), chemin)

    def test_la_liste_privee(self):
        trouves = hygiene.identifiants(
            "migration de AcmeCorp", termes=["acmecorp"]
        )
        self.assertEqual([("nom privé", "acmecorp", 13)], trouves)

    def test_sans_liste_privee_rien_nest_refuse(self):
        self.assertEqual([], hygiene.identifiants("migration de AcmeCorp"))


class TestCeQuiEstLu(unittest.TestCase):
    """Les commentaires et les docstrings, et rien d'autre du code."""

    def test_une_docstring_de_module(self):
        source = '"""Vécu sur une machine du parc."""\n\n\nX = 1\n'
        trouvailles = hygiene.inspect("x.py", source=source, termes=[])
        self.assertEqual({"récit"}, genres(trouvailles))

    def test_une_docstring_de_fonction(self):
        source = 'def f():\n    """Mesuré sur la copie."""\n    return 1\n'
        trouvailles = hygiene.inspect("x.py", source=source, termes=[])
        self.assertEqual(2, trouvailles[0]["line"])

    def test_une_chaine_de_code_nest_pas_un_commentaire(self):
        """Seule la PREMIÈRE expression d'une portée est une docstring."""
        source = 'def f():\n    return "Vécu sur la copie"\n'
        self.assertEqual([], hygiene.inspect("x.py", source=source, termes=[]))

    def test_les_lignes_consecutives_forment_un_bloc(self):
        """Une phrase coupée en deux lignes reste une phrase."""
        source = (
            "# une raison, puis mesuré\n# sur la copie de la base\nX = 1\n"
        )
        trouvailles = hygiene.inspect("x.py", source=source, termes=[])
        self.assertEqual(1, len(trouvailles))

    def test_un_trou_separe_deux_blocs(self):
        source = "# mesuré sur la copie\nX = 1\n# vécu sur la copie\nY = 2\n"
        trouvailles = hygiene.inspect("x.py", source=source, termes=[])
        self.assertEqual([1, 3], [f["line"] for f in trouvailles])

    def test_la_ligne_pointee_est_celle_du_marqueur(self):
        """Pointer le début d'un bloc de vingt lignes ne guide personne."""
        source = "# une raison\n# une autre\n# vécu sur la copie\nX = 1\n"
        trouvailles = hygiene.inspect("x.py", source=source, termes=[])
        self.assertEqual([3], [f["line"] for f in trouvailles])

    def test_un_source_illisible_se_replie_sur_les_lignes(self):
        """Rendre un rapport vide dirait « propre » d'un fichier non lu."""
        source = "def f(:\n    # vécu sur la copie\n"
        trouvailles = hygiene.inspect("x.py", source=source, termes=[])
        self.assertEqual([2], [f["line"] for f in trouvailles])

    def test_un_mot_qui_en_contient_un_autre_ne_pointe_rien(self):
        """« je » vit dans « sujet » et « projeté » : pas une trouvaille."""
        source = (
            "# Le sujet est la decision, pas la connexion. Avec une ABI\n"
            "# injectee, rien ne bouge. Le trajet reste projete.\n"
            "# Ici seulement je regarde le resultat.\n"
            "X = 1\n"
        )
        trouvailles = hygiene.inspect("x.py", source=source, termes=[])
        self.assertEqual([3], [f["line"] for f in trouvailles])

    def test_un_commentaire_shell_de_fin_de_ligne(self):
        source = "#!/bin/sh\nrsync -a src dst   # copie vers 10.0.0.42\n"
        trouvailles = hygiene.inspect("x.sh", source=source, termes=[])
        self.assertEqual(
            [(2, "adresse")], [(f["line"], f["pattern"]) for f in trouvailles]
        )

    def test_un_diese_entre_guillemets_nouvre_rien(self):
        source = '#!/bin/sh\necho "# vécu sur la copie"\n'
        self.assertEqual([], hygiene.inspect("x.sh", source=source, termes=[]))

    def test_un_diese_colle_a_un_mot_nouvre_rien(self):
        """`${VAR#prefixe}` et une URL à ancre ne sont pas des commentaires."""
        source = "#!/bin/sh\necho ${CHEMIN#vécu sur la copie}\n"
        self.assertEqual([], hygiene.inspect("x.sh", source=source, termes=[]))

    def test_un_script_shell(self):
        source = "#!/bin/bash\n# vécu sur la copie\necho ok\n"
        trouvailles = hygiene.inspect("x.sh", source=source, termes=[])
        self.assertEqual([2], [f["line"] for f in trouvailles])

    def test_le_shebang_nest_pas_un_commentaire(self):
        self.assertEqual(
            [],
            hygiene.inspect(
                "x.sh", source="#!/bin/bash\necho ok\n", termes=[]
            ),
        )


class TestLePerimetre(unittest.TestCase):
    def test_le_code_tiers_est_hors_perimetre(self):
        for chemin in (
            "script/OCA_maintainer-tools/tools/x.py",
            "addons/quelque_chose/models/x.py",
            ".venv.erplibre/lib/x.py",
        ):
            self.assertFalse(hygiene.a_balayer(chemin), chemin)

    def test_le_code_du_depot_est_dans_le_perimetre(self):
        for chemin in (
            "script/todo/todo.py",
            "test/test_x.py",
            "long_test/x.py",
        ):
            self.assertTrue(hygiene.a_balayer(chemin), chemin)


class TestLaLigneDeCommande(unittest.TestCase):
    """Le module peut être juste et le programme faux : on l'exécute."""

    def _lancer(self, source, suffixe=".py", args=()):
        with tempfile.NamedTemporaryFile(
            "w", suffix=suffixe, delete=False, encoding="utf-8"
        ) as fh:
            fh.write(source)
            chemin = fh.name
        try:
            return subprocess.run(
                [sys.executable, OUTIL, chemin, "--no-color", *args],
                capture_output=True,
                text=True,
            )
        finally:
            os.unlink(chemin)

    def test_zero_quand_il_ny_a_rien_a_signaler(self):
        r = self._lancer("# la sonde mesure le temps\nX = 1\n")
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertEqual("", r.stdout.strip())

    def test_un_quand_il_y_a_des_trouvailles(self):
        """0 rien à signaler, 1 des trouvailles, 2 l'outil a échoué."""
        r = self._lancer("# vécu sur la copie\nX = 1\n")
        self.assertEqual(1, r.returncode)
        self.assertIn("témoignage", r.stdout)

    def test_le_json_porte_le_compte_et_les_trouvailles(self):
        import json

        r = self._lancer("# vécu sur la copie\nX = 1\n", args=("--json",))
        rendu = json.loads(r.stdout)
        self.assertEqual(1, rendu["scanned"])
        self.assertEqual(1, len(rendu["findings"]))

    def test_identifying_only_laisse_le_recit_dehors(self):
        r = self._lancer(
            "# vécu sur la copie\nX = 1\n", args=("--identifying-only",)
        )
        self.assertEqual(0, r.returncode)

    def test_sans_chemin_il_le_dit(self):
        r = subprocess.run(
            [sys.executable, OUTIL], capture_output=True, text=True
        )
        self.assertEqual(2, r.returncode)


class TestLeHook(unittest.TestCase):
    """Le hook informe : il ne bloque jamais un commit sur du style."""

    HOOK = os.path.join(
        os.path.dirname(__file__), "..", "script", "git", "hooks", "pre-commit"
    )

    def _depot_jetable(self, contenu):
        """Un dépôt git neuf, l'outil et le hook posés où le hook les cherche."""
        import shutil

        racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, racine, True)
        for relatif in ("script/analyse", "script/git/hooks"):
            os.makedirs(os.path.join(racine, relatif))
        shutil.copy(OUTIL, os.path.join(racine, "script", "analyse"))
        shutil.copy(
            os.path.join(os.path.dirname(OUTIL), "..", "lib_identifiant.py"),
            os.path.join(racine, "script"),
        )
        shutil.copy(self.HOOK, os.path.join(racine, "script", "git", "hooks"))
        chemin = os.path.join(racine, "exemple.py")
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write(contenu)
        for commande in (
            ["git", "init", "-q"],
            ["git", "add", "exemple.py"],
        ):
            subprocess.run(
                commande, cwd=racine, check=True, capture_output=True
            )
        return racine

    def _lancer_dans(self, racine):
        return subprocess.run(
            [
                sys.executable,
                os.path.join(racine, "script/git/hooks/pre-commit"),
            ],
            capture_output=True,
            text=True,
            cwd=racine,
        )

    def test_il_rapporte_ce_qui_est_indexe(self):
        racine = self._depot_jetable(
            "# vécu sur la copie, en 10.0.0.42\nX = 1\n"
        )
        r = self._lancer_dans(racine)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("exemple.py", r.stderr)
        self.assertIn("10.0.0.42", r.stderr)
        self.assertIn("PAS bloqué", r.stderr)

    def test_il_se_tait_sur_un_fichier_propre(self):
        racine = self._depot_jetable('"""Rend le code de sortie."""\nX = 1\n')
        r = self._lancer_dans(racine)
        self.assertEqual(0, r.returncode)
        self.assertEqual("", r.stderr.strip())

    def test_il_sort_toujours_en_zero(self):
        r = subprocess.run(
            [sys.executable, self.HOOK], capture_output=True, text=True
        )
        self.assertEqual(0, r.returncode, r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
