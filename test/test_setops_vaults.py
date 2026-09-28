#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les voûtes : une absence voulue n'est pas une panne, et une clé ne s'écrase pas.

Deux propriétés portent tout le reste. La première est de LECTURE : sur le
runner d'un locataire, la clé du site manque EXPRÈS, et la présenter comme un
défaut enverrait réparer une séparation réussie. La seconde est d'ÉCRITURE :
une clé remplacée rend sa voûte définitivement illisible, donc la pose est
exclusive — et le contenu posé ne doit ressortir par aucun chemin.

Les noms d'écosystème, de dépôt et les chemins sont inventés ; ils n'existent
nulle part ailleurs dans le dépôt.
"""

import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.setops import vaults as V  # noqa: E402

# La forme exacte que rend « voutes.py etat » sur un runner de locataire : sa
# propre clé présente, celle de l'hébergeur absente parce qu'il ne doit pas
# pouvoir l'ouvrir, et un voisin sans clé.
RAPPORT = (
    "instance    Fabrique-Nord        cle presente  "
    "/home/exploitant/.config/setops-vault-fabrique-nord\n"
    "hebergeur   Terrain-Nord         sans cle      "
    "/home/exploitant/.config/setops-vault-terrain-nord\n"
    "voisin      Fabrique-Sud         sans cle      "
    "/home/exploitant/.config/setops-vault-fabrique-sud\n"
)

# Le même rapport quand c'est la clé qui décide du code de sortie qui manque.
# Le moteur ajoute alors sa prose et la commande qui règle le cas.
BLOQUE = (
    "instance    Fabrique-Nord        CLE ABSENTE   "
    "/home/exploitant/.config/setops-vault-fabrique-nord\n"
    "hebergeur   Terrain-Nord         sans cle      "
    "/home/exploitant/.config/setops-vault-terrain-nord\n"
    "\n"
    "La cle de l'instance montee manque — cette machine ne peut rien "
    "configurer.\n"
    "  umask 077; openssl rand -base64 48 | tr -d '\\n' > <chemin>\n"
)


class TestLaLectureDuRapport(unittest.TestCase):
    def test_a_real_report_is_read_in_order(self):
        """Le contrôle positif : sans lui, un lecteur qui refuse tout
        passerait chacun des refus éprouvés plus bas."""
        lues = V.lit_etat(RAPPORT)
        self.assertEqual(3, len(lues))
        self.assertEqual(
            [V.INSTANCE, V.HEBERGEUR, V.VOISIN], [v.role for v in lues]
        )
        self.assertEqual(
            ["Fabrique-Nord", "Terrain-Nord", "Fabrique-Sud"],
            [v.nom for v in lues],
        )
        self.assertEqual(
            [V.PRESENTE, V.SANS_CLE, V.SANS_CLE], [v.etat for v in lues]
        )

    def test_nothing_to_name_is_an_answer_not_a_failure(self):
        """« Aucune voûte » dit « ni instance montée ni underlay », ce qui est
        une réponse valide ; None dirait « rapport illisible »."""
        self.assertEqual(
            (),
            V.lit_etat(
                "Aucune voute a nommer : ni instance montee, ni underlay."
            ),
        )

    def test_the_prose_under_the_table_is_not_a_vault(self):
        """Le moteur explique le blocage et cite la commande qui le règle :
        les compter comme des voûtes en inventerait deux."""
        lues = V.lit_etat(BLOQUE)
        self.assertEqual(2, len(lues))
        self.assertEqual(
            "/home/exploitant/.config/setops-vault-fabrique-nord",
            lues[0].chemin,
        )

    def test_an_unknown_role_refuses_the_whole_report(self):
        """LE PIRE CAS EST UN CALME TROMPEUR : `bloquante` se décide sur le mot
        « instance », donc un rôle renommé en amont doit faire refuser la
        lecture plutôt que rendre « rien ne bloque » sur une machine qui ne
        peut rien configurer."""
        renomme = RAPPORT.replace("instance  ", "montee    ", 1)
        self.assertIsNone(V.lit_etat(renomme))

    def test_an_unknown_label_refuses_the_whole_report(self):
        self.assertIsNone(
            V.lit_etat(RAPPORT.replace("cle presente", "cle peut-etre", 1))
        )

    def test_a_path_with_a_space_keeps_all_of_itself(self):
        """Le chemin est pris après l'étiquette, pas comme dernier mot : coupé
        au blanc, todo proposerait de créer la clé ailleurs."""
        lues = V.lit_etat(
            "instance    Fabrique-Nord        cle presente  "
            "/home/exploitant/mes reglages/setops-vault-fabrique-nord\n"
        )
        self.assertEqual(
            "/home/exploitant/mes reglages/setops-vault-fabrique-nord",
            lues[0].chemin,
        )

    def test_the_table_wins_over_the_sentinel(self):
        """LE CALME TROMPEUR. La phrase « aucune voûte à nommer » se trouve
        aussi dans la prose du moteur ; cherchée partout, elle faisait rendre
        « rien à nommer » au moment précis où une clé bloquante manque, et
        l'écran s'en allait sans un mot."""
        vu = V.lit_etat(BLOQUE + "  " + V.AUCUNE + " pour les compagnons.\n")
        self.assertEqual(2, len(vu))
        self.assertIsNotNone(V.bloquante(vu))

    def test_an_unknown_role_refuses_wherever_it_sits(self):
        """Le refus ne dépend PAS de la place de la ligne. Avalée comme prose
        parce qu'une ligne valable la précédait, une voûte bloquante
        disparaîtrait sans bruit."""
        for rang in (0, 1, 2):
            with self.subTest(rang=rang):
                lignes = RAPPORT.splitlines(True)
                lignes[rang] = "montee" + lignes[rang].split(" ", 1)[1]
                self.assertIsNone(V.lit_etat("".join(lignes)))

    def test_an_unknown_label_refuses_wherever_it_sits(self):
        """Un rôle connu suffit à faire prétendre au tableau : une étiquette
        reformulée en amont ne doit pas passer pour de la prose."""
        for vieille in ("cle presente", "sans cle"):
            with self.subTest(etiquette=vieille):
                self.assertIsNone(
                    V.lit_etat(RAPPORT.replace(vieille, "cle peut-etre", 1))
                )

    def test_a_label_followed_by_more_words_is_not_a_label(self):
        """Le moteur pose DEUX espaces entre l'état et le chemin : sans cette
        borne, « cle presente mais vide » passait pour une clé présente et
        emportait sa propre phrase dans le chemin."""
        self.assertIsNone(
            V._ligne(
                "instance    Fabrique-Nord        cle presente mais vide"
                "   /chemin-fictif/v-a"
            )
        )

    def test_a_path_that_traverses_a_label_does_not_change_the_state(self):
        """LA PIRE DES DEUX : une ligne qui dit CLE ABSENTE se lisait
        « presente » dès que le chemin traversait un dossier ainsi nommé."""
        lue = V._ligne(
            "instance    Fabrique-Nord        CLE ABSENTE   "
            "/chemin-fictif/cle presente/v-a"
        )
        self.assertEqual(V.ABSENTE_BLOQUANTE, lue.etat)
        self.assertEqual("/chemin-fictif/cle presente/v-a", lue.chemin)

    def test_anything_else_is_unreadable(self):
        for texte in ("", None, "Traceback (most recent call last):"):
            with self.subTest(texte=texte):
                self.assertIsNone(V.lit_etat(texte))


class TestUneAbsenceVoulueNestPasUnePanne(unittest.TestCase):
    """Sur le runner d'un locataire, la clé du site DOIT manquer : ce runner
    porte la carte de la fabric et ne doit jamais pouvoir l'ouvrir."""

    def test_a_missing_host_key_blocks_nothing(self):
        self.assertIsNone(V.bloquante(V.lit_etat(RAPPORT)))

    def test_only_the_mounted_instance_blocks(self):
        bloque = V.bloquante(V.lit_etat(BLOQUE))
        self.assertIsNotNone(bloque)
        self.assertEqual(V.INSTANCE, bloque.role)
        self.assertEqual("Fabrique-Nord", bloque.nom)

    def test_what_this_machine_must_not_open_is_named_apart(self):
        """Comptées comme des manques, ces deux-là feraient poser des clés qui
        n'ouvriraient rien."""
        self.assertEqual(
            ["Terrain-Nord", "Fabrique-Sud"],
            [v.nom for v in V.separation(V.lit_etat(RAPPORT))],
        )

    def test_nothing_read_means_nothing_blocked_and_nothing_separated(self):
        self.assertIsNone(V.bloquante(None))
        self.assertEqual((), V.separation(None))


class TestLaPoseDuFichierCle(unittest.TestCase):
    """Une clé remplacée rend sa voûte définitivement illisible."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="setops-voutes-banc-")
        self.chemin = os.path.join(self.dossier, "setops-vault-banc")

    def tearDown(self):
        for nom in os.listdir(self.dossier):
            os.unlink(os.path.join(self.dossier, nom))
        os.rmdir(self.dossier)

    def test_a_key_is_posed_and_the_verdict_says_so(self):
        """Le contrôle positif : sans lui, une pose qui refuse toujours
        passerait les refus éprouvés plus bas."""
        pose = V.poser_cle(self.chemin)
        self.assertEqual(V.POSEE, pose.resultat)
        self.assertTrue(pose.reussi)
        self.assertTrue(os.path.isfile(self.chemin))

    def test_the_file_is_readable_by_nobody_else(self):
        """Posé large puis resserré, il serait lisible entre les deux."""
        V.poser_cle(self.chemin)
        mode = stat.S_IMODE(os.stat(self.chemin).st_mode)
        self.assertEqual(0, mode & (stat.S_IRWXG | stat.S_IRWXO))

    def test_the_mode_is_given_at_the_moment_of_creation(self):
        """Le garde porte sur LA CRÉATION, et non sur le mode final : créer
        large puis resserrer laisse une fenêtre où la clé est lisible par tout
        le monde, et le mode final ne la montre pas."""
        vus = []
        vrai = os.open

        def espion(chemin, drapeaux, mode=0o777, *a, **k):
            vus.append(mode)
            return vrai(chemin, drapeaux, mode, *a, **k)

        with mock.patch.object(os, "open", espion):
            V.poser_cle(self.chemin)
        self.assertEqual([V.MODE], vus)

    def test_the_key_is_one_draw_from_the_system_source(self):
        """La FORME ne dit rien de l'ALÉA : trois octets répétés seize fois
        donnent soixante-quatre caractères base64 tous différents d'une pose à
        l'autre, avec vingt-quatre bits d'entropie au lieu de trois cent
        quatre-vingt-quatre."""
        tires = []
        vrai = os.urandom

        def espion(n):
            tires.append(n)
            return vrai(n)

        with mock.patch.object(os, "urandom", espion):
            V.poser_cle(self.chemin)
        self.assertEqual([V.OCTETS], tires)

    def test_the_key_repeats_no_short_pattern(self):
        """Contrôle indépendant de l'espion : une clé bâtie en répétant un
        motif court le laisse voir dans ses octets."""
        import base64

        V.poser_cle(self.chemin)
        with open(self.chemin, "rb") as tenu:
            octets = base64.b64decode(tenu.read())
        self.assertEqual(V.OCTETS, len(octets))
        for periode in range(1, len(octets) // 2 + 1):
            with self.subTest(periode=periode):
                motif = octets[:periode]
                repete = (motif * (len(octets) // periode + 1))[: len(octets)]
                self.assertNotEqual(repete, octets)

    def test_the_key_is_one_line_of_the_documented_shape(self):
        """Le moteur documente 48 octets en base64 sur UNE ligne : un
        « \\n » de trop entre dans le secret qu'Ansible essaie, et une clé
        plus courte que ce plancher s'attaque."""
        V.poser_cle(self.chemin)
        with open(self.chemin, "rb") as tenu:
            contenu = tenu.read()
        # Le garde porte sur la constante, pas sur 64 : AGRANDIR la clé doit
        # passer, la rapetisser doit rougir. Épinglé au chiffre du jour, il
        # ferait l'inverse, et c'est l'inverse qui coûte cher.
        self.assertEqual(4 * ((V.OCTETS + 2) // 3), len(contenu))
        self.assertGreaterEqual(V.OCTETS, 48)
        self.assertNotIn(b"\n", contenu)

    def test_two_poses_do_not_give_the_same_key(self):
        """Une constante passerait tout ce qui précède."""
        V.poser_cle(self.chemin)
        with open(self.chemin, "rb") as tenu:
            premier = tenu.read()
        autre = os.path.join(self.dossier, "setops-vault-banc-deux")
        V.poser_cle(autre)
        with open(autre, "rb") as tenu:
            self.assertNotEqual(premier, tenu.read())

    def test_an_existing_key_is_never_overwritten(self):
        """LE CAS QUI COÛTE TOUT : la voûte ne s'ouvre qu'avec le secret qui
        l'a chiffrée. Le contenu doit être INTACT — et non seulement le verdict
        négatif, qu'une troncature suivie d'un refus rendrait aussi."""
        with open(self.chemin, "wb") as tenu:
            tenu.write(b"la-cle-qui-ouvre-deja-cette-voute")
        pose = V.poser_cle(self.chemin)
        self.assertEqual(V.DEJA_LA, pose.resultat)
        self.assertFalse(pose.reussi)
        with open(self.chemin, "rb") as tenu:
            self.assertEqual(b"la-cle-qui-ouvre-deja-cette-voute", tenu.read())

    def test_the_verdict_never_carries_the_key(self):
        """Un verdict qui porterait la clé la ferait imprimer par l'écran qui
        le rend, et journaliser par tout ce qui garde une trace."""
        pose = V.poser_cle(self.chemin)
        with open(self.chemin, "rb") as tenu:
            contenu = tenu.read().decode("ascii")
        ensemble = "".join(str(champ) for champ in pose)
        self.assertNotIn(contenu, ensemble)
        # Un fragment aussi : la clé ne doit pas fuir par morceaux.
        self.assertNotIn(contenu[:8], ensemble)

    def test_a_failed_write_leaves_no_file_behind(self):
        """UN FICHIER À MOITIÉ POSÉ EST PIRE QU'AUCUN : la pose suivante rend
        DEJA_LA, et l'écran affirme alors qu'une clé est là et que la remplacer
        rendrait la voûte définitivement illisible — la phrase même qui
        dissuadera de l'effacer."""
        with mock.patch.object(
            os, "write", side_effect=OSError(28, "No space left on device")
        ):
            pose = V.poser_cle(self.chemin)
        self.assertEqual(V.ECHEC, pose.resultat)
        self.assertFalse(os.path.exists(self.chemin))

    def test_a_short_write_is_a_failure_and_leaves_no_file(self):
        """Une écriture courte rendrait POSEE sur une clé tronquée, qui n'ouvre
        rien et ne se distingue pas d'une bonne."""
        with mock.patch.object(os, "write", return_value=3):
            pose = V.poser_cle(self.chemin)
        self.assertEqual(V.ECHEC, pose.resultat)
        self.assertFalse(os.path.exists(self.chemin))

    def test_an_interrupt_leaves_no_file_behind_either(self):
        """Ctrl-C n'est pas un `OSError` : sans son propre bras, la frappe
        laissait le fichier de zéro octet et le descripteur ouvert."""
        with mock.patch.object(os, "write", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                V.poser_cle(self.chemin)
        self.assertFalse(os.path.exists(self.chemin))

    def test_an_existing_file_is_never_removed_by_a_failure(self):
        """Le nettoyage ne porte que sur le chemin qu'`O_EXCL` vient de créer :
        un refus DEJA_LA ne doit rien retirer."""
        with open(self.chemin, "w", encoding="ascii") as tenu:
            tenu.write("la-cle-qui-ouvre-deja-cette-voute")
        with mock.patch.object(os, "write", side_effect=OSError(5, "EIO")):
            self.assertEqual(V.DEJA_LA, V.poser_cle(self.chemin).resultat)
        self.assertTrue(os.path.isfile(self.chemin))

    def test_no_path_poses_nothing(self):
        for vide in ("", "   ", None):
            with self.subTest(vide=vide):
                self.assertEqual(V.SANS_CHEMIN, V.poser_cle(vide).resultat)

    def test_a_path_that_cannot_be_written_says_why(self):
        pose = V.poser_cle(os.path.join(self.dossier, "absent", "cle"))
        self.assertEqual(V.ECHEC, pose.resultat)
        self.assertTrue(pose.souci)

    def test_every_verdict_is_in_the_closed_vocabulary(self):
        self.assertIn(V.poser_cle(self.chemin).resultat, V.POSES)
        self.assertIn(V.poser_cle(self.chemin).resultat, V.POSES)
        self.assertIn(V.poser_cle(None).resultat, V.POSES)


class TestCeQueTodoNeLancePas(unittest.TestCase):
    """La liste vit dans `runbooks`, avec le reste de la règle de périmètre.
    Une seconde ici laissait cet écran REMETTRE ce que l'écran des séquences
    CONDUISAIT."""

    def test_the_passphrase_gestures_are_named_as_handed_over(self):
        from script.setops import runbooks as R

        for cible in ("cles-exporter", "cles-compagnons", "cles-restaurer"):
            with self.subTest(cible=cible):
                self.assertIn(cible, R.remises())

    def test_the_read_only_target_is_not_among_them(self):
        from script.setops import runbooks as R

        self.assertNotIn(V.CIBLE_RECENSER, R.remises())

    def test_this_module_keeps_no_second_list(self):
        """Le défaut, nommé : deux endroits qui décident du même geste."""
        self.assertFalse(
            [
                n
                for n in dir(V)
                if n.startswith("CIBLES_") and n != "CIBLE_RECENSER"
            ]
        )


class TestLesIdentitesDeVoute(unittest.TestCase):
    """Une `Identite` est le COUPLE étiquette/clé : une étiquette sans sa clé
    n'ouvre rien, et une clé sans son étiquette ne dit pas quelle voûte elle
    ouvre. Une liste amputée fait échouer un déchiffrement sur un message qui ne
    parle que de mot de passe — et l'on cherche alors la clé, pas la liste."""

    REELLE = "une-etiquette@/config/une-cle,autre-etiquette@/config/autre-cle"

    def test_both_sides_of_each_pair_are_kept(self):
        lues = V.lit_identites(self.REELLE)
        self.assertEqual(
            [
                ("une-etiquette", "/config/une-cle"),
                ("autre-etiquette", "/config/autre-cle"),
            ],
            [(i.etiquette, i.cle) for i in lues],
        )

    def test_the_split_is_on_the_first_at_sign(self):
        """Une étiquette n'en contient pas ; un chemin pourrait."""
        lue = V.lit_identites("etiq@/config/cle@sauvegarde")[0]
        self.assertEqual(
            ("etiq", "/config/cle@sauvegarde"), (lue.etiquette, lue.cle)
        )

    def test_declaring_none_is_an_answer(self):
        """Et c'est un avertissement en soi : le moteur exporte alors sa
        variable d'identités VIDE, et toute cible ansible qu'il lance échoue."""
        for sortie in ("", "   ", "\n", None):
            with self.subTest(sortie=repr(sortie)):
                self.assertEqual((), V.lit_identites(sortie))

    def test_a_malformed_entry_refuses_the_whole_read(self):
        for sortie in (
            "sans-arobase",
            "@/config/cle",
            "etiq@",
            "etiq@   ",
            "bonne@/config/cle,mauvaise",
            "bonne@/config/cle,,autre@/config/cle2",
        ):
            with self.subTest(sortie=sortie):
                self.assertIsNone(V.lit_identites(sortie))

    def test_a_well_formed_list_is_not_refused(self):
        """Le contrôle positif : sans lui, un lecteur qui refuse toujours
        passerait les refus ci-dessus."""
        self.assertIsNotNone(V.lit_identites(self.REELLE))

    def test_the_argv_asks_the_engine_for_them(self):
        """Le couple est DÉRIVÉ du recenseur du moteur, pas recomposé depuis le
        nom d'un dépôt : c'est lui qui décide comment il nomme ses voûtes."""
        self.assertIn("identites", V.ARGV_IDENTITES)
        self.assertEqual(V.ARGV_ETAT[:-1], V.ARGV_IDENTITES[:-1])


if __name__ == "__main__":
    unittest.main()
