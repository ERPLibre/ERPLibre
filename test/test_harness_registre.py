#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les harnais d'agent : ce qui est gris, et ce qui est dit en le grisant.

Ce que ces tests défendent est une DISTINCTION, pas une fonctionnalité. Trois
états se ressemblent en surface et n'appellent pas le même geste : le binaire
manque — il faut installer ; le binaire est là mais aucun adaptateur ne le
couvre — il faut écrire du code ; tout est prêt. Un menu qui confond les deux
premiers envoie chercher une installation là où c'est du code qui manque, et
c'est le genre d'erreur qui coûte une demi-heure sans jamais lever.

Une quatrième chose ne grise pas et doit se dire quand même : un répertoire
de configuration absent. Le binaire suffit à travailler, et un harnais lancé
une première fois crée son répertoire lui-même — mais c'est ce qui explique
une liste de sessions vide, donc l'écran le signale.

La détection est PURE et les deux accesseurs sont injectés : aucun test ne
touche le PATH ni le système de fichiers. Les noms de binaire des harnais
sont ceux de logiciels publics, pas des machines — la règle du dépôt sur les
noms ne s'y applique pas.
"""

import unittest

from script.todo.assistant.harness import registre as R

CLAUDE = R.Harnais(
    cle="essai-mesure",
    nom="Essai mesuré",
    icone="🧪",
    binaire="essai-mesure",
    maison="~/.essai-mesure",
    verifie=True,
    actions=(R.LISTER, R.QUESTION),
)
BRUT = R.Harnais(
    cle="essai-brut", nom="Essai brut", icone="🧫", binaire="essai-brut"
)


def _which(present):
    """Un `which` qui ne connaît que les noms donnés."""
    return lambda nom: f"/faux/bin/{nom}" if nom in present else None


class TestLesTroisVerdicts(unittest.TestCase):
    def test_binary_missing_says_so(self):
        etat = R.etat_de(CLAUDE, which=_which(()), exists=lambda p: False)
        self.assertEqual(etat.verdict, R.ABSENT)
        self.assertEqual(etat.raison, R.SANS_BINAIRE)

    def test_binary_present_without_adapter(self):
        """Le cas qui compte : installé, et pourtant inutilisable ici."""
        etat = R.etat_de(
            BRUT, which=_which({"essai-brut"}), exists=lambda p: True
        )
        self.assertEqual(etat.verdict, R.NON_VERIFIE)
        self.assertEqual(etat.raison, R.SANS_ADAPTATEUR)

    def test_measured_and_installed_is_ready(self):
        etat = R.etat_de(
            CLAUDE, which=_which({"essai-mesure"}), exists=lambda p: True
        )
        self.assertEqual(etat.verdict, R.OK)
        self.assertEqual(etat.raison, "")

    def test_missing_binary_wins_over_missing_adapter(self):
        """Sans binaire, la justesse de l'adaptateur ne se pose pas encore.

        Annoncer « adaptateur non mesuré » sur une machine où le logiciel
        n'est pas installé envoie écrire du code au lieu d'installer."""
        etat = R.etat_de(BRUT, which=_which(()), exists=lambda p: False)
        self.assertEqual(etat.verdict, R.ABSENT)


class TestLaMaison(unittest.TestCase):
    def test_a_missing_home_does_not_grey_out(self):
        """Le binaire suffit : un premier lancement crée son répertoire."""
        etat = R.etat_de(
            CLAUDE, which=_which({"essai-mesure"}), exists=lambda p: False
        )
        self.assertEqual(etat.verdict, R.OK)
        self.assertEqual(etat.raison, R.SANS_MAISON)

    def test_a_home_nobody_declared_is_unknown(self):
        """None et False ne disent pas la même chose.

        Un harnais sans répertoire déclaré n'a pas de répertoire ABSENT : ce
        dépôt ne sait pas où il vit. Rendre False ferait afficher une absence
        qui n'a pas été constatée."""
        etat = R.etat_de(
            BRUT, which=_which({"essai-brut"}), exists=lambda p: False
        )
        self.assertIsNone(etat.maison_presente)

    def test_the_home_is_expanded_before_the_test(self):
        vus = []

        def exists(chemin):
            vus.append(chemin)
            return True

        R.etat_de(CLAUDE, which=_which({"essai-mesure"}), exists=exists)
        self.assertTrue(vus)
        self.assertNotIn("~", vus[0])


class TestLesActions(unittest.TestCase):
    def test_a_ready_harness_accepts_what_it_declares(self):
        etat = R.etat_de(
            CLAUDE, which=_which({"essai-mesure"}), exists=lambda p: True
        )
        self.assertTrue(etat.accepte(R.LISTER))
        self.assertFalse(etat.accepte(R.ARRIERE_PLAN))

    def test_an_absent_harness_accepts_nothing(self):
        """Même une action qu'il déclare : le menu ne doit rien en offrir."""
        etat = R.etat_de(CLAUDE, which=_which(()), exists=lambda p: True)
        self.assertFalse(etat.accepte(R.LISTER))


class TestLaListe(unittest.TestCase):
    def test_the_order_is_the_declaration_order(self):
        """Un harnais garde sa place quand il s'installe ou disparaît.

        Sinon les numéros du menu changeraient sous les doigts d'une fois sur
        l'autre, ce qui est la faute que le fil d'Ariane a déjà coûté."""
        liste = R.etats(
            which=_which({"essai-brut"}),
            exists=lambda p: True,
            connus=(CLAUDE, BRUT),
        )
        self.assertEqual(
            [e.harnais.cle for e in liste], [c.cle for c in (CLAUDE, BRUT)]
        )

    def test_nothing_is_dropped_from_the_list(self):
        """Un harnais absent est NOMMÉ, jamais omis."""
        liste = R.etats(
            which=_which(()), exists=lambda p: False, connus=(CLAUDE, BRUT)
        )
        self.assertEqual(len(liste), 2)
        self.assertEqual(R.prets(liste), [])

    def test_only_the_ready_ones_are_ready(self):
        liste = R.etats(
            which=_which({"essai-mesure", "essai-brut"}),
            exists=lambda p: True,
            connus=(CLAUDE, BRUT),
        )
        self.assertEqual(
            [e.harnais.cle for e in R.prets(liste)], ["essai-mesure"]
        )


class TestCeQueLeDepotDeclare(unittest.TestCase):
    """Les harnais réels : ce qui est affirmé et ce qui ne l'est pas."""

    def test_only_the_measured_harnesses_are_declared_so(self):
        """« Mesuré » veut dire qu'un adaptateur a été écrit CONTRE le vrai
        logiciel, et non qu'on en connaît le nom. Les autres restent en
        « non vérifié », ce qui envoie chercher du code plutôt qu'une
        installation."""
        mesures = [h.cle for h in R.HARNAIS if h.verifie]
        self.assertEqual(mesures, ["claude", "opencode"])

    def test_a_measured_harness_declares_only_what_it_can_do(self):
        """Open Code ne déclare que la lecture : son `run` écrit dans l'arbre
        de travail sans demander, donc une entrée « question libre » y serait
        un piège."""
        par_cle = {h.cle: h for h in R.HARNAIS}
        self.assertEqual(par_cle["opencode"].actions, (R.LISTER,))
        self.assertIn(R.QUESTION, par_cle["claude"].actions)

    def test_every_harness_has_a_binary_name(self):
        for h in R.HARNAIS:
            self.assertTrue(h.binaire, h.cle)

    def test_every_harness_carries_an_icon(self):
        """Une entrée nue au milieu d'entrées décorées se lit comme un défaut.

        L'icône ne peut pas vivre dans une valeur traduite comme le font les
        autres étiquettes : un nom de produit ne se traduit pas."""
        for h in R.HARNAIS:
            self.assertTrue(h.icone, h.cle)

    def test_the_icons_are_distinct(self):
        icones = [h.icone for h in R.HARNAIS]
        self.assertEqual(len(icones), len(set(icones)))

    def test_a_home_is_declared_only_where_it_is_known(self):
        """Un chemin supposé afficherait une devinette comme un fait."""
        avec = {h.cle for h in R.HARNAIS if h.maison}
        self.assertEqual(avec, {"claude", "hermes", "opencode"})

    def test_an_unmeasured_harness_declares_no_action(self):
        """Déclarer une action sans adaptateur offrirait ce qui échoue."""
        for h in R.HARNAIS:
            if not h.verifie:
                self.assertEqual(h.actions, (), h.cle)


if __name__ == "__main__":
    unittest.main()
