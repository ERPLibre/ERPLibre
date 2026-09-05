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

Les messages sont traduits. Les assertions qui citent du texte fixent donc la
langue à « fr » pour la durée du module : sinon elles dépendraient de EL_LANG,
et un poste en anglais les ferait toutes échouer.
"""

# Ces épreuves doivent PORTER une donnée détectée : c'est tout ce
# qu'elles prouvent. Les valeurs sont inventées et déclarées ici.
# hygiene-exemple: 172.20.99.152
# hygiene-exemple: 172.20.99.5
# hygiene-exemple: a@b.ca
# hygiene-exemple: a@y.ca

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "script", "git")
)

from script.todo import todo_i18n  # noqa: E402

# Relevée AVANT d'épingler : c'est la langue que lira un hook lancé en
# sous-processus, qui relit env_var.sh et ignore ce que ce module épingle.
LANGUE_DEPOT = todo_i18n.get_lang()
_LANGUE_ORIGINE = todo_i18n._current_lang

EN_FRANCAIS = unittest.skipUnless(
    LANGUE_DEPOT == "fr",
    "le dépôt est en « %s » : ce test lit du texte français" % LANGUE_DEPOT,
)


def setUpModule():
    """Fixe « fr » en mémoire. set_lang() écrirait env_var.sh, qui est suivi."""
    todo_i18n._current_lang = "fr"


def tearDownModule():
    todo_i18n._current_lang = _LANGUE_ORIGINE


import commit_msg_lib  # noqa: E402
from commit_msg_lib import (  # noqa: E402
    MAX,
    MAX_BODY,
    body_of,
    check,
    subject_of,
)

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
        sujet = "[FIX] déploiement : " + "é" * (
            MAX - len("[FIX] déploiement : ")
        )
        self.assertEqual(MAX, len(sujet))
        self.assertGreater(len(sujet.encode("utf-8")), MAX)
        self.assertEqual([], check(sujet))

    def test_ce_que_git_ecrit_lui_meme(self):
        for genere in (
            "Merge branch 'develop' into master",
            "Merge remote-tracking branch 'origin/develop'",
            'Revert "[FIX] portée : quelque chose"',
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
            problemes = check(
                f"[FIX] proxmox : {ouvrant}il manque le stockage{ouvrant}"
            )
            self.assertEqual(1, len(problemes), ouvrant)
            self.assertIn("citation", problemes[0])

    def test_une_citation_ailleurs_dans_le_sujet_passe(self):
        """Seule l'OUVERTURE est refusée : citer en fin de sujet reste permis."""
        self.assertEqual(
            [], check("[FIX] proxmox : pmxcfs à terre, dit « aucun stockage »")
        )

    def test_deux_problemes_sont_rapportes_ensemble(self):
        problemes = check(
            "proxmox : « un sujet sans tag et beaucoup trop long » " + "a" * 40
        )
        self.assertEqual(3, len(problemes))


def _message(corps):
    return "[FIX] portée : quelque chose\n\n" + corps + "\n"


class TestLeCorps(unittest.TestCase):
    """Le corps est vérifié sur deux plans : sa longueur, et l'identifiant."""

    def test_un_corps_conforme(self):
        self.assertEqual([], check(_message("Une raison, en trois mots.")))

    def test_un_sujet_seul_na_pas_de_corps(self):
        self.assertEqual("", body_of("[FIX] portée : sujet\n"))
        self.assertEqual([], check("[FIX] portée : sujet\n"))

    def test_dix_lignes_par_langue_passent(self):
        moitie = "\n".join(f"ligne {n}" for n in range(MAX_BODY))
        corps = f"{moitie}\n\n--- FR ---\n\n{moitie}"
        self.assertEqual([], check(_message(corps)))

    def test_onze_lignes_pour_une_langue_sont_refusees(self):
        moitie = "\n".join(f"ligne {n}" for n in range(MAX_BODY + 1))
        problemes = check(_message(moitie))
        self.assertEqual(1, len(problemes))
        self.assertIn(f"{MAX_BODY + 1} lignes", problemes[0])

    def test_la_longueur_est_par_langue_et_non_par_message(self):
        """Le bilinguisme achète la concision : il ne double pas le budget."""
        moitie = "\n".join(f"ligne {n}" for n in range(MAX_BODY + 1))
        self.assertTrue(check(_message(f"{moitie}\n\n--- FR ---\n\n{moitie}")))

    def test_les_lignes_vides_ne_comptent_pas(self):
        corps = "\n\n".join(f"ligne {n}" for n in range(MAX_BODY))
        self.assertEqual([], check(_message(corps)))

    def test_les_trailers_et_le_report_ne_comptent_pas(self):
        corps = "\n".join(f"ligne {n}" for n in range(MAX_BODY))
        corps += "\n\nAssisted-by: Claude Opus 5"
        corps += "\nCo-authored-by: Quelqu'un <personne@exemple.ca>"
        corps += "\n(cherry picked from commit 0123456789abcdef)"
        self.assertEqual([], check(_message(corps)))

    def test_une_adresse_ip(self):
        problemes = check(_message("La VM répondait en 172.31.7.42."))
        self.assertEqual(1, len(problemes))
        self.assertIn("172.31.7.42", problemes[0])

    def test_les_adresses_sans_porteur_passent(self):
        """0.0.0.0 et 127.0.0.1 ne désignent aucune machine du parc."""
        self.assertEqual(
            [], check(_message("Le service écoute sur 127.0.0.1."))
        )
        self.assertEqual(
            [], check(_message("Lié à 0.0.0.0, masque 255.255.255.0."))
        )

    def test_une_version_nest_pas_une_adresse(self):
        self.assertEqual([], check(_message("Passage de 17.0 à 18.0.")))

    def test_un_courriel_dans_le_corps(self):
        problemes = check(_message("Signalé par personne@exemple.ca."))
        self.assertEqual(1, len(problemes))
        self.assertIn("courriel", problemes[0])

    def test_un_chemin_de_compte(self):
        problemes = check(
            _message("Le venv vit dans /home/sireine/git/erplibre/.")
        )
        self.assertEqual(1, len(problemes))
        self.assertIn("chemin de compte", problemes[0])

    def test_un_chemin_en_gabarit_passe(self):
        self.assertEqual(
            [], check(_message("Le venv vit dans /home/<utilisateur>/."))
        )

    def test_une_ligne_checked_reste_du_corps(self):
        """« Checked: » ressemble à un trailer : il ne doit pas s'y soustraire."""
        self.assertTrue(check(_message("Checked: 172.20.99.152 répond.")))

    def test_la_liste_privee_absente_ne_refuse_rien(self):
        origine = commit_msg_lib.NOMS_INTERDITS
        commit_msg_lib.NOMS_INTERDITS = os.path.join(
            os.path.dirname(origine), "absent_de_ce_depot.txt"
        )
        try:
            self.assertEqual([], check(_message("Migration de acmecorp.")))
        finally:
            commit_msg_lib.NOMS_INTERDITS = origine

    def test_la_liste_privee_refuse_le_nom_quelle_porte(self):
        origine = commit_msg_lib.NOMS_INTERDITS
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("# un commentaire\n\nacmecorp\n")
            commit_msg_lib.NOMS_INTERDITS = fh.name
        try:
            problemes = check(_message("Migration de AcmeCorp, six paliers."))
            self.assertEqual(1, len(problemes))
            self.assertIn("nom refusé", problemes[0])
        finally:
            os.unlink(commit_msg_lib.NOMS_INTERDITS)
            commit_msg_lib.NOMS_INTERDITS = origine

    def test_un_merge_nest_pas_juge(self):
        """git écrit le corps d'un merge : le refuser refuserait le merge."""
        self.assertEqual(
            [], check("Merge branch 'develop'\n\n" + "ligne\n" * 40)
        )

    def test_une_version_de_manifeste_odoo_nest_pas_une_adresse(self):
        """« 18.0.1.0 » a quatre nombres et n'est pas une machine."""
        for version in ("18.0.1.0", "17.0.1.3", "12.0.2.1"):
            self.assertEqual(
                [],
                check(_message(f"Le manifeste passe à {version}.")),
                version,
            )

    def test_le_diff_de_cleanup_scissors_nest_pas_le_corps(self):
        """Sous la ligne de ciseaux, tout appartient à git."""
        corps = "Une raison.\n\n"
        corps += "# ------------------------ >8 ------------------------\n"
        corps += "diff --git a/x b/x\n"
        corps += "".join("+une ligne avec 10.10.10.5\n" for _ in range(30))
        self.assertEqual([], check(_message(corps)))

    def test_le_courriel_dun_trailer_est_legitime(self):
        corps = "Une raison.\n\nCo-authored-by: Quelquun <personne@exemple.ca>"
        self.assertEqual([], check(_message(corps)))

    def test_un_nom_prive_dans_un_trailer_est_refuse(self):
        """Un « Refs: » publie autant qu'une phrase du corps."""
        origine = commit_msg_lib.NOMS_INTERDITS
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("acmecorp\n")
            commit_msg_lib.NOMS_INTERDITS = fh.name
        try:
            problemes = check(_message("Une raison.\n\nRefs: acmecorp-42"))
            self.assertEqual(1, len(problemes))
            self.assertIn("nom refusé", problemes[0])
        finally:
            os.unlink(commit_msg_lib.NOMS_INTERDITS)
            commit_msg_lib.NOMS_INTERDITS = origine

    def test_body_of_rend_les_trailers_sur_demande(self):
        message = _message("Une raison.\n\nAssisted-by: Un modèle")
        self.assertNotIn("Assisted-by", body_of(message))
        self.assertIn("Assisted-by", body_of(message, trailers=True))


class TestLesDeuxLangues(unittest.TestCase):
    """Un refus se lit dans la langue du dépôt, pas seulement en français."""

    def setUp(self):
        self.addCleanup(setattr, todo_i18n, "_current_lang", "fr")

    def _en(self, message):
        todo_i18n._current_lang = "en"
        return check(message)

    def test_le_tag_manquant_se_dit_en_anglais(self):
        probleme = self._en("pas de tag")[0]
        self.assertIn("must start with a tag", probleme)
        self.assertNotIn("doit commencer", probleme)

    def test_la_longueur_du_sujet_se_dit_en_anglais(self):
        probleme = self._en("[FIX] portée : " + "a" * 80)[0]
        self.assertIn("characters", probleme)
        self.assertIn("KEYWORDS", probleme)

    def test_les_identifiants_se_disent_en_anglais(self):
        corps = "[FIX] portée : sujet\n\nUne raison, 172.20.99.5 et a@b.ca.\n"
        problemes = " ".join(self._en(corps))
        self.assertIn("IP address", problemes)
        self.assertIn("e-mail address", problemes)

    def test_les_deux_langues_signalent_AUTANT_de_problemes(self):
        """Traduire ne doit ni ajouter ni perdre un refus."""
        corps = "[FIX] portée : sujet\n\nUne raison, 172.20.99.5 et a@b.ca.\n"
        todo_i18n._current_lang = "fr"
        fr = len(check(corps))
        self.assertEqual(fr, len(self._en(corps)))

    def test_une_cle_sans_traduction_rend_la_cle(self):
        """Le repli de t() ne doit jamais faire tomber le hook."""
        self.assertEqual([], check("[FIX] portée : quelque chose"))


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
        """Le code de sortie et le chemin de la règle ne sont pas traduits."""
        r = self._lancer("[FIX] portée : " + "a" * 80 + "\n")
        self.assertEqual(1, r.returncode)
        self.assertIn(".claude/rules/04-code-conventions.md", r.stderr)

    @EN_FRANCAIS
    def test_il_dit_pourquoi_en_francais(self):
        r = self._lancer("[FIX] portée : " + "a" * 80 + "\n")
        self.assertIn("hors convention", r.stderr)
        self.assertIn("MOTS-CLÉS", r.stderr)

    def test_il_dit_pourquoi_dans_la_langue_du_depot(self):
        """Le sous-processus rend la langue d'env_var.sh, quelle qu'elle soit."""
        todo_i18n._current_lang = LANGUE_DEPOT
        try:
            attendu = todo_i18n.t("commit message off convention")
        finally:
            todo_i18n._current_lang = "fr"
        r = self._lancer("[FIX] portée : " + "a" * 80 + "\n")
        self.assertIn(attendu, r.stderr)

    def test_il_nomme_le_contournement(self):
        """Sans issue annoncée, un hook se contourne en le supprimant."""
        r = self._lancer("pas de tag\n")
        self.assertIn("--no-verify", r.stderr)

    def test_sans_argument_il_echoue_proprement(self):
        r = subprocess.run(
            [sys.executable, HOOK], capture_output=True, text=True
        )
        self.assertEqual(1, r.returncode)
        self.assertIn("commit-msg", r.stderr)

    @EN_FRANCAIS
    def test_sans_argument_il_le_dit_en_francais(self):
        r = subprocess.run(
            [sys.executable, HOOK], capture_output=True, text=True
        )
        self.assertIn("aucun fichier", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
