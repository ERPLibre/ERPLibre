#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le garde-fou du sujet de commit refuse-t-il ce qu'il doit, et rien d'autre ?

Un hook qui refuse trop est désinstallé dans la semaine. Ces tests pèsent donc
autant les refus que les acceptations : un « Merge branch » que git écrit
lui-même, un sujet français de 70 caractères dont les accents pèsent 2 octets,
un fixup de rebase — tout cela doit passer.

La part de la convention qu'aucun hook ne juge — « ce sujet dit-il sur quoi
porte le code » — n'est pas testée ici parce qu'elle n'est pas vérifiable.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "script", "git"))

from commit_msg_lib import MAX, check, subject_of  # noqa: E402

HOOK = os.path.join(
    os.path.dirname(__file__), "..", "script", "git", "hooks", "commit-msg"
)


class TestCeQuiPasse(unittest.TestCase):
    def test_un_sujet_conforme(self):
        self.assertEqual([], check("[FIX] proxmox : signaler pmxcfs à terre"))

    def test_les_huit_tags_de_la_convention(self):
        for tag in ("ADD", "FIX", "UPD", "IMP", "REF", "REM", "MOV", "I18N"):
            self.assertEqual([], check(f"[{tag}] portée : quelque chose"), tag)

    def test_un_sujet_de_72_caracteres_pile(self):
        sujet = "[FIX] portée : " + "a" * (MAX - len("[FIX] portée : "))
        self.assertEqual(MAX, len(sujet))
        self.assertEqual([], check(sujet))

    def test_les_accents_comptent_pour_un_caractere(self):
        """« é » pèse 2 octets : une limite en octets refuserait ce sujet."""
        sujet = "[FIX] déploiement : " + "é" * (MAX - len("[FIX] déploiement : "))
        self.assertEqual(MAX, len(sujet))
        self.assertGreater(len(sujet.encode("utf-8")), MAX)
        self.assertEqual([], check(sujet))

    def test_ce_que_git_ecrit_lui_meme(self):
        for genere in (
            "Merge branch 'develop' into master",
            "Merge remote-tracking branch 'origin/develop'",
            "Revert \"[FIX] portée : quelque chose\"",
            "fixup! [FIX] portée : quelque chose",
            "squash! [FIX] portée : quelque chose",
        ):
            self.assertEqual([], check(genere), genere)

    def test_un_message_vide_ou_commente(self):
        """Un commit abandonné : git s'en occupe, le hook ne s'en mêle pas."""
        self.assertEqual([], check(""))
        self.assertEqual([], check("# Please enter the commit message\n#\n"))

    def test_le_sujet_est_la_premiere_ligne_utile(self):
        self.assertEqual(
            "[FIX] portée : sujet",
            subject_of("#\n# commentaire\n\n[FIX] portée : sujet\n\ncorps\n"),
        )


class TestCeQuiEstRefuse(unittest.TestCase):
    def test_un_sujet_sans_tag(self):
        problemes = check("corriger le pont NAT")
        self.assertEqual(1, len(problemes))
        self.assertIn("tag", problemes[0])

    def test_un_tag_inconnu(self):
        self.assertTrue(check("[WIP] portée : quelque chose"))

    def test_un_sujet_de_73_caracteres(self):
        sujet = "[FIX] portée : " + "a" * (MAX + 1 - len("[FIX] portée : "))
        self.assertEqual(MAX + 1, len(sujet))
        problemes = check(sujet)
        self.assertEqual(1, len(problemes))
        self.assertIn("73 caractères", problemes[0])

    def test_le_message_de_longueur_enseigne_les_mots_cles(self):
        """Tronquer est le réflexe et c'est le mauvais : le hook doit le dire."""
        probleme = check("[FIX] portée : " + "a" * 80)[0]
        self.assertIn("MOTS-CLÉS", probleme)
        self.assertIn("Ne le tronquez pas", probleme)

    def test_un_sujet_qui_ouvre_sur_une_citation(self):
        for ouvrant in ("«", '"', "'", "`", "“"):
            problemes = check(f"[FIX] proxmox : {ouvrant}il manque le stockage{ouvrant}")
            self.assertEqual(1, len(problemes), ouvrant)
            self.assertIn("citation", problemes[0])

    def test_une_citation_ailleurs_dans_le_sujet_passe(self):
        """Seule l'OUVERTURE est refusée : citer en fin de sujet reste permis."""
        self.assertEqual(
            [], check("[FIX] proxmox : pmxcfs à terre, dit « aucun stockage »")
        )

    def test_deux_problemes_sont_rapportes_ensemble(self):
        problemes = check("proxmox : « un sujet sans tag et beaucoup trop long » " + "a" * 40)
        self.assertEqual(3, len(problemes))


class TestLeHookLuiMeme(unittest.TestCase):
    """Le module peut être juste et le hook faux : on l'exécute vraiment."""

    def _lancer(self, message):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(message)
            chemin = fh.name
        try:
            return subprocess.run(
                [sys.executable, HOOK, chemin],
                capture_output=True,
                text=True,
            )
        finally:
            os.unlink(chemin)

    def test_il_sort_en_zero_sur_un_sujet_conforme(self):
        r = self._lancer("[FIX] portée : quelque chose\n")
        self.assertEqual(0, r.returncode, r.stderr)

    def test_il_sort_en_un_et_dit_pourquoi(self):
        r = self._lancer("[FIX] portée : " + "a" * 80 + "\n")
        self.assertEqual(1, r.returncode)
        self.assertIn("hors convention", r.stderr)
        self.assertIn("MOTS-CLÉS", r.stderr)

    def test_il_nomme_le_contournement(self):
        """Sans issue annoncée, un hook se contourne en le supprimant."""
        r = self._lancer("pas de tag\n")
        self.assertIn("--no-verify", r.stderr)

    def test_sans_argument_il_echoue_proprement(self):
        r = subprocess.run(
            [sys.executable, HOOK], capture_output=True, text=True
        )
        self.assertEqual(1, r.returncode)
        self.assertIn("aucun fichier", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
