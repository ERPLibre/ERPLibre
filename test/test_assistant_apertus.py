#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installateur Apertus : l'ordre des étapes, et ce que l'état garde.

Ces tests tiennent quatre choses qu'aucune exécution ne dirait tout haut.

**L'ordre.** La vérification de version précède le téléchargement. Un moteur
antérieur à l'activation xIELU accepte le fichier puis produit du charabia :
placer le contrôle après « tirer » coûte plusieurs gigaoctets pour apprendre
un numéro de version. Rien dans le code ne rend cet ordre obligatoire, et
une étape déplacée reste verte partout ailleurs.

**Le texte des commandes.** Les deux modules sont purs : ils rendent des
chaînes que l'appelant lance. Une chaîne mal citée ne se voit qu'à
l'exécution, sur la machine de quelqu'un d'autre, au milieu d'une
installation — `bash -n` la voit ici, sans hôte ni réseau.

**La séparation des deux dictionnaires d'état.** `cibles` se remet à neuf à
chaque tentative, `echecs` ne fait que croître. Les fondre rendrait l'écran
de reprise vide au moment précis où il sert.

**Ce qui ne doit paraître nulle part.** Aucune adresse, aucun courriel,
aucun chemin de compte dans les deux modules : ils suivent le dépôt en amont
et deviennent publics avec lui.

Aucun fichier réel n'est écrit : les tests d'état déplacent le répertoire
personnel vers un répertoire temporaire, et vérifient que la racine du dépôt
n'a rien gagné. Les hôtes cités sont INVENTÉS — le TLD « .invalid » est
réservé à cet usage et ne peut désigner aucune machine.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.todo.assistant import apertus  # noqa: E402
from script.todo.assistant import apertus_state  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]

# Un hôte qui n'existe pas, et ne peut pas exister.
HOTE = "atelier-nord.invalid"

CIBLE_LOCALE = {"kind": "local", "destination": ""}
CIBLE_SSH = {"kind": "ssh", "destination": HOTE}

# L'ordre attendu, écrit une seule fois. Les deux tests d'ordre le lisent :
# l'un vérifie la liste entière, l'autre la seule contrainte qui compte.
ORDRE = [
    "atteindre",
    "sudo",
    "place",
    "paquet",
    "version",
    "service",
    "tirer",
    "ecouter",
    "repondre",
]


def toutes_les_commandes():
    """Chaque chaîne de shell que les deux générateurs savent produire.

    Rend un ensemble : les quatre moteurs partagent des étapes identiques,
    et `bash -n` sur un doublon ne prouve rien de plus.
    """
    vues = set()
    for moteur in apertus.MOTEURS:
        for modele in apertus.MODELES:
            for cible in (CIBLE_LOCALE, CIBLE_SSH):
                liste = apertus.etapes(moteur, modele, cible)
                liste += apertus.desinstaller(moteur, modele, cible)
                for etape in liste:
                    vues.add(etape.commande)
                    if etape.deja_fait:
                        vues.add(etape.deja_fait)
    return vues


class LOrdreDesEtapes(unittest.TestCase):
    def test_un_moteur_sans_plateforme_rend_les_neuf_etapes_connues(self):
        """Neuf étapes, mêmes clés, même rang : la clé sert de reprise, donc
        un moteur qui en saute une rendrait une progression illisible."""
        for moteur, spec in apertus.MOTEURS.items():
            if spec.plateforme:
                continue
            with self.subTest(moteur=moteur):
                liste = apertus.etapes(
                    moteur, apertus.MODELE_DEFAUT, CIBLE_LOCALE
                )
                self.assertEqual(9, len(liste))
                self.assertEqual(ORDRE, [e.cle for e in liste])

    def test_un_moteur_lie_a_une_plateforme_la_verifie_en_deuxieme(self):
        """La garde passe AVANT la place disque et avant l'installation.

        Mesurer un disque ou compiler une roue pour un moteur qui n'existe
        pas sur ce noyau est du travail perdu, et le diagnostic arriverait
        après. Elle suit « atteindre » parce qu'il faut d'abord joindre la
        cible pour lui demander son noyau.
        """
        for moteur, spec in apertus.MOTEURS.items():
            if not spec.plateforme:
                continue
            with self.subTest(moteur=moteur):
                cles = [
                    e.cle
                    for e in apertus.etapes(
                        moteur, apertus.MODELE_DEFAUT, CIBLE_LOCALE
                    )
                ]
                self.assertEqual("plateforme", cles[1], cles)
                self.assertLess(
                    cles.index("plateforme"), cles.index("place"), cles
                )
                self.assertLess(
                    cles.index("plateforme"), cles.index("paquet"), cles
                )

    def test_le_modele_precede_le_service_quand_le_moteur_l_exige(self):
        """L'ordre n'est pas une préférence.

        Un moteur qui charge un chemin au démarrage exige que ce chemin
        EXISTE : à l'envers, le service échouerait sur un répertoire absent et
        la conversion suivrait un serveur déjà mort. La conversion devient
        alors critique, un service lancé sur rien n'apprenant rien.
        """
        for moteur, spec in apertus.MOTEURS.items():
            with self.subTest(moteur=moteur):
                liste = apertus.etapes(
                    moteur, apertus.MODELE_DEFAUT, CIBLE_LOCALE
                )
                cles = [e.cle for e in liste]
                par_cle = {e.cle: e for e in liste}
                if spec.modele_avant_service:
                    self.assertLess(
                        cles.index("tirer"), cles.index("service"), cles
                    )
                    self.assertTrue(par_cle["tirer"].critique)
                else:
                    self.assertLess(
                        cles.index("service"), cles.index("tirer"), cles
                    )

    def test_la_version_se_verifie_avant_le_telechargement(self):
        """L'invariant qui porte tout le reste.

        Un moteur antérieur à l'activation xIELU charge mal le modèle, ou pas
        du tout. Le contrôle placé après « tirer » ferait payer cinq
        gigaoctets de téléchargement pour apprendre un numéro de version que
        « version » lit en une seconde. L'échec doit être tôt et gratuit.
        """
        for moteur in apertus.MOTEURS:
            for modele in apertus.MODELES:
                with self.subTest(moteur=moteur, modele=modele):
                    cles = [
                        e.cle
                        for e in apertus.etapes(moteur, modele, CIBLE_LOCALE)
                    ]
                    self.assertLess(
                        cles.index("version"),
                        cles.index("tirer"),
                        "la version doit se vérifier avant de télécharger",
                    )

    def test_le_choix_de_modele_ne_deplace_aucune_etape(self):
        """L'ordre dépend du MOTEUR et de lui seul.

        Un ordre qui varierait avec le modèle rendrait la reprise fausse : le
        rang enregistré désignerait une autre étape après un changement de
        modèle sur la même cible.
        """
        for moteur in apertus.MOTEURS:
            attendu = [
                e.cle
                for e in apertus.etapes(
                    moteur, apertus.MODELE_DEFAUT, CIBLE_LOCALE
                )
            ]
            for modele in apertus.MODELES:
                with self.subTest(moteur=moteur, modele=modele):
                    liste = apertus.etapes(moteur, modele, CIBLE_LOCALE)
                    self.assertEqual(attendu, [e.cle for e in liste])

    def test_le_service_est_la_seule_etape_non_critique(self):
        """Un hôte sans systemd sert quand même le modèle : c'est « ecouter »
        qui tranche, et un arrêt sur « service » y serait un faux négatif."""
        for moteur in apertus.MOTEURS:
            with self.subTest(moteur=moteur):
                souples = [
                    e.cle
                    for e in apertus.etapes(
                        moteur, apertus.MODELE_DEFAUT, CIBLE_LOCALE
                    )
                    if not e.critique
                ]
                self.assertEqual(["service"], souples)

    def test_la_desinstallation_arrete_avant_de_retirer(self):
        """Retirer les poids d'un moteur qui les tient ouvertes échoue sur
        certains moteurs, et le moteur lui-même n'est jamais désinstallé."""
        for moteur in apertus.MOTEURS:
            with self.subTest(moteur=moteur):
                liste = apertus.desinstaller(
                    moteur, apertus.MODELE_DEFAUT, CIBLE_LOCALE
                )
                self.assertEqual(["arret", "retrait"], [e.cle for e in liste])
                self.assertTrue(all(not e.critique for e in liste))


class LeTexteDesCommandes(unittest.TestCase):
    def test_chaque_commande_parse_sous_bash(self):
        """Une citation ratée ne se voit qu'à l'exécution, sur la machine de
        quelqu'un d'autre. `bash -n` lit sans exécuter : aucun hôte, aucun
        réseau, aucun paquet posé."""
        for commande in sorted(toutes_les_commandes()):
            with self.subTest(commande=commande[:60]):
                fini = subprocess.run(
                    ["bash", "-n"],
                    input=commande,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(0, fini.returncode, fini.stderr)

    def test_aucune_commande_n_affaiblit_la_confiance_d_hote(self):
        """Forcer `StrictHostKeyChecking=no` accepterait la clé de n'importe
        quelle machine qui répond à l'adresse : l'hôte déclaré dans la
        configuration ssh de l'utilisateur garde la sienne."""
        for commande in toutes_les_commandes():
            self.assertNotIn("StrictHostKeyChecking", commande)
            self.assertNotIn("UserKnownHostsFile", commande)

    def test_toute_url_generee_vise_la_boucle_locale(self):
        """Les sondes interrogent le moteur DEPUIS la cible : une adresse
        autre que la boucle locale sortirait de la machine visée."""
        for commande in toutes_les_commandes():
            for hote in re.findall(r"https?://([^/\s'\"]+)", commande):
                sans_port = hote.split(":")[0]
                if sans_port[0].isdigit():
                    self.assertEqual("127.0.0.1", sans_port, commande)

    def test_le_plan_nomme_chaque_etape_et_sa_commande(self):
        liste = apertus.etapes(
            apertus.MOTEUR_DEFAUT, apertus.MODELE_DEFAUT, CIBLE_LOCALE
        )
        plan = apertus.plan_lisible(liste)
        lignes = plan.split("\n")
        self.assertEqual(len(liste), len(lignes))
        for rang, etape in enumerate(liste, 1):
            self.assertIn(f"{rang}. {etape.cle}", lignes[rang - 1])
            self.assertIn(etape.commande, lignes[rang - 1])


class LEnrobage(unittest.TestCase):
    def test_une_cible_locale_recoit_la_commande_telle_quelle(self):
        self.assertEqual(
            "echo 'a b'", apertus.enrobe(CIBLE_LOCALE, "echo 'a b'")
        )

    def test_une_cible_distante_cite_la_destination_et_la_commande(self):
        """`shlex.split` de la sortie rend les deux morceaux intacts : c'est
        la preuve que la citation tient, et non un simple test d'inclusion."""
        enrobe = apertus.enrobe(CIBLE_SSH, "echo 'a b'")
        morceaux = shlex.split(enrobe)
        self.assertEqual("ssh", morceaux[0])
        self.assertEqual(HOTE, morceaux[-2])
        self.assertEqual("echo 'a b'", morceaux[-1])

    def test_une_cible_distante_ne_peut_pas_attendre_un_mot_de_passe(self):
        """Sans `BatchMode=yes`, une invite de mot de passe sous un ssh non
        interactif attend sans rien afficher, et le menu paraît figé."""
        enrobe = apertus.enrobe(CIBLE_SSH, "true")
        self.assertIn("-o BatchMode=yes", enrobe)
        self.assertIn("-o ConnectTimeout=", enrobe)

    def test_l_enrobage_atteint_les_deux_commandes_de_l_etape(self):
        """Le test de complétion se lance sur la MÊME machine que l'étape :
        oublié, il interrogerait l'hôte d'où part l'installation."""
        for etape in apertus.etapes(
            apertus.MOTEUR_DEFAUT, apertus.MODELE_DEFAUT, CIBLE_SSH
        ):
            self.assertTrue(etape.commande.startswith("ssh -o BatchMode=yes"))
            if etape.deja_fait:
                self.assertTrue(
                    etape.deja_fait.startswith("ssh -o BatchMode=yes")
                )


class LeContexteDeReprise(unittest.TestCase):
    def _liste(self):
        return apertus.etapes(
            apertus.MOTEUR_DEFAUT, apertus.MODELE_DEFAUT, CIBLE_LOCALE
        )

    def test_il_ne_touche_aucun_fichier(self):
        """L'écran texte et l'écran plein rendent TOUS DEUX ce dictionnaire.
        Une lecture ici en ferait deux sources, qui divergeraient le jour où
        l'une lirait un fichier que l'autre vient d'écrire."""
        with patch("builtins.open") as ouvre:
            apertus.contexte_reprise({"etape_faite": 3}, self._liste())
        ouvre.assert_not_called()

    def test_un_etat_arrete_a_quatre_sur_neuf_se_reprend_a_cinq(self):
        etat = {
            "cible": HOTE,
            "moteur": "ollama",
            "modele": "8b-q4",
            "etape_faite": 4,
            "etape_echouee": "version",
            "code": 1,
            "erreur": "version trop ancienne",
            "tentatives": 2,
            "secondes": 192,
        }
        vue = apertus.contexte_reprise(etat, self._liste())
        self.assertEqual(4, vue["faites"])
        self.assertEqual(9, vue["total"])
        self.assertEqual(5, vue["reprise_a"])
        self.assertEqual(2, vue["tentatives"])
        self.assertEqual(192, vue["secondes"])
        self.assertEqual(1, vue["code"])
        icones = [e["icone"] for e in vue["etapes"]]
        self.assertEqual(["✅"] * 4, icones[:4])
        self.assertEqual("⛔", icones[4])
        self.assertEqual(["⬜"] * 4, icones[5:])
        self.assertEqual("version", vue["etapes"][4]["cle"])

    def test_un_etat_vierge_reprend_a_la_premiere_etape(self):
        vue = apertus.contexte_reprise({}, self._liste())
        self.assertEqual(0, vue["faites"])
        self.assertEqual(1, vue["reprise_a"])
        self.assertEqual(["⬜"] * 9, [e["icone"] for e in vue["etapes"]])
        self.assertEqual("", vue["erreur"])

    def test_un_etat_complet_ne_depasse_pas_le_dernier_rang(self):
        """Neuf étapes faites sur neuf : « reprendre à la dixième » n'existe
        pas, et un rang hors liste ferait lever l'affichage."""
        vue = apertus.contexte_reprise({"etape_faite": 9}, self._liste())
        self.assertEqual(9, vue["reprise_a"])

    def test_les_rangs_commencent_a_un_et_se_suivent(self):
        vue = apertus.contexte_reprise({"etape_faite": 2}, self._liste())
        self.assertEqual(
            list(range(1, 10)), [e["rang"] for e in vue["etapes"]]
        )


class LesVersions(unittest.TestCase):
    def test_ollama_refuse_ce_qui_precede_l_activation(self):
        """0.12.5 ne connaît pas xIELU, 0.12.6 oui, et aucune note de version
        ne le dit : seul le numéro tranche."""
        self.assertFalse(
            apertus.version_suffisante("ollama", "ollama version is 0.12.3")
        )
        self.assertTrue(
            apertus.version_suffisante("ollama", "ollama version is 0.12.6")
        )
        self.assertTrue(
            apertus.version_suffisante("ollama", "ollama version is 0.13.0")
        )

    def test_llamacpp_se_compare_par_numero_de_construction(self):
        """« b6671 » n'est pas un numéro sémantique : la comparaison porte
        sur l'entier, sinon « b670 » passerait pour plus récent."""
        self.assertFalse(apertus.version_suffisante("llamacpp", "b6670"))
        self.assertTrue(apertus.version_suffisante("llamacpp", "b6671"))
        self.assertTrue(
            apertus.version_suffisante("llamacpp", "version: 7000 (b7000)")
        )
        self.assertFalse(apertus.version_suffisante("llamacpp", "b5882"))

    def test_une_sortie_muette_ne_passe_pas_pour_suffisante(self):
        """Un binaire absent rend une chaîne vide, et l'absence de numéro ne
        prouve rien : la seule réponse sûre est le refus."""
        for moteur in apertus.MOTEURS:
            with self.subTest(moteur=moteur):
                self.assertFalse(apertus.version_suffisante(moteur, ""))
                self.assertFalse(
                    apertus.version_suffisante(moteur, "command not found")
                )

    def test_chaque_moteur_atteint_son_propre_minimum(self):
        for cle, moteur in apertus.MOTEURS.items():
            with self.subTest(moteur=cle):
                self.assertTrue(
                    apertus.version_suffisante(cle, moteur.version_min)
                )


class LeCatalogue(unittest.TestCase):
    def test_la_reference_ollama_n_est_jamais_le_nu_apertus(self):
        """`ollama pull apertus` n'existe pas : Apertus n'est pas dans la
        bibliothèque officielle, et l'étiquette nue rendrait un 404 chez
        chaque utilisateur. Le pont HuggingFace est obligatoire."""
        for cle, modele in apertus.MODELES.items():
            with self.subTest(modele=cle):
                reference = modele.reference["ollama"]
                self.assertNotEqual("apertus", reference)
                self.assertTrue(reference.startswith("hf.co/"), reference)
        for commande in toutes_les_commandes():
            self.assertNotIn("ollama pull apertus", commande)
            self.assertNotIn("local-ai run apertus", commande)

    def test_chaque_moteur_a_sa_forme_de_reference(self):
        """Les quatre veulent quatre formes incompatibles pour les mêmes
        poids : une clé manquante lèverait au moment de l'installation."""
        for cle, modele in apertus.MODELES.items():
            with self.subTest(modele=cle):
                self.assertEqual(
                    sorted(apertus.MOTEURS), sorted(modele.reference)
                )

    def test_les_depots_vises_sont_ceux_de_l_editeur(self):
        self.assertEqual(
            {
                "swiss-ai/Apertus-8B-Instruct-2509",
                "swiss-ai/Apertus-70B-Instruct-2509",
                "swiss-ai/Apertus-v1.1-1.5B-Instruct",
                "swiss-ai/Apertus-v1.1-0.5B-Instruct",
            },
            {m.depot for m in apertus.MODELES.values()},
        )
        self.assertEqual(
            "swiss-ai/Apertus-8B-Instruct-2509",
            apertus.MODELES[apertus.MODELE_DEFAUT].depot,
        )

    def test_aucune_variante_ne_vise_la_famille_1_5(self):
        """Elle porte une autre architecture, exige un fork épinglé de la
        bibliothèque de transformeurs et un compte pour être téléchargée :
        sur une machine distante, l'échec serait un 401 inattendu."""
        source = Path(apertus.__file__).read_text(encoding="utf-8")
        self.assertNotIn("v1.5", source)
        for modele in apertus.MODELES.values():
            self.assertNotIn("v1.5", modele.depot)
            for reference in modele.reference.values():
                self.assertNotIn("v1.5", reference)

    def test_le_contexte_demande_reste_sous_le_plafond(self):
        """Le cache clé-valeur d'un 8B coûte 128 Kio par jeton : accepter les
        65 536 jetons du modèle réserverait 8 Gio par-dessus les poids."""
        for cle, modele in apertus.MODELES.items():
            with self.subTest(modele=cle):
                utile = apertus.contexte_utile(modele)
                self.assertLessEqual(utile, apertus.CONTEXTE_PLAFOND)
                self.assertLessEqual(utile, modele.contexte)
        self.assertEqual(
            4096, apertus.contexte_utile(apertus.MODELES["mini-1.5b"])
        )

    def test_la_place_exigee_depasse_la_taille_du_modele(self):
        for cle, modele in apertus.MODELES.items():
            with self.subTest(modele=cle):
                self.assertGreater(
                    apertus.place_requise(modele), modele.taille
                )

    def test_les_quatre_moteurs_sont_sous_licence_libre(self):
        for cle, moteur in apertus.MOTEURS.items():
            with self.subTest(moteur=cle):
                self.assertIn(moteur.licence, ("MIT", "Apache-2.0"))
                self.assertTrue(moteur.chemin.startswith("/"))
                self.assertGreater(moteur.port, 0)


class RienDIdentifiant(unittest.TestCase):
    """Les deux modules suivent le dépôt en amont, et deviennent publics."""

    ADRESSE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
    COURRIEL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    COMPTE = re.compile(r"/home/[^/\s\"']+/")

    def _sources(self):
        for module in (apertus, apertus_state):
            yield module.__name__, Path(module.__file__).read_text(
                encoding="utf-8"
            )

    def test_la_seule_adresse_est_la_boucle_locale(self):
        for nom, source in self._sources():
            with self.subTest(module=nom):
                trouvees = set(self.ADRESSE.findall(source))
                self.assertLessEqual(trouvees, {"127.0.0.1"}, trouvees)

    def test_aucun_courriel_ni_chemin_de_compte(self):
        for nom, source in self._sources():
            with self.subTest(module=nom):
                self.assertEqual([], self.COURRIEL.findall(source))
                self.assertEqual([], self.COMPTE.findall(source))

    def test_aucune_commande_generee_ne_nomme_un_compte(self):
        """Les commandes passent par `$HOME`, que la cible étend elle-même :
        un chemin de compte écrit ici viendrait de la machine d'ici."""
        for commande in toutes_les_commandes():
            self.assertEqual([], self.COMPTE.findall(commande), commande)


class UnEtatHorsDuDepot(unittest.TestCase):
    """L'état vit dans le répertoire personnel, jamais dans l'arbre du dépôt.

    Le répertoire personnel est déplacé vers un répertoire temporaire pour la
    durée de chaque test, et la racine du dépôt est relevée avant et après :
    une progression nomme sa machine, et un fichier né sous le dépôt partirait
    avec le prochain commit.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._racine_avant = sorted(os.listdir(RACINE))
        self._patches = [
            patch.dict(os.environ, {"HOME": self._tmp.name}),
            patch.object(
                Path, "home", staticmethod(lambda: Path(self._tmp.name))
            ),
        ]
        for morceau in self._patches:
            morceau.start()
        self.addCleanup(self._fin)

    def _fin(self):
        for morceau in reversed(self._patches):
            morceau.stop()
        self.assertEqual(self._racine_avant, sorted(os.listdir(RACINE)))
        self._tmp.cleanup()

    def _fichier(self):
        return Path(self._tmp.name) / ".erplibre" / "apertus_install.json"

    def test_le_fichier_nait_sous_le_repertoire_personnel(self):
        apertus_state.ecrire(HOTE, etape_faite=1)
        self.assertTrue(self._fichier().exists(), "rien n'a été écrit")
        self.assertFalse((RACINE / ".erplibre").exists())
        self.assertFalse((RACINE / "apertus_install.json").exists())

    def test_le_cycle_complet_se_relit(self):
        liste = apertus.etapes(
            apertus.MOTEUR_DEFAUT, apertus.MODELE_DEFAUT, CIBLE_LOCALE
        )
        apertus_state.commencer(HOTE, "ollama", "8b-q4", len(liste))
        etat = apertus_state.lire(HOTE)
        self.assertEqual(1, etat["tentatives"])
        self.assertEqual(0, etat["etape_faite"])
        self.assertEqual(9, etat["etapes_total"])

        apertus_state.avancer(HOTE, 4, secondes=12)
        self.assertEqual(4, apertus_state.lire(HOTE)["etape_faite"])
        self.assertFalse(apertus_state.a_reprendre(HOTE))

        apertus_state.terminer(HOTE, secondes=30)
        etat = apertus_state.lire(HOTE)
        self.assertTrue(etat["fin"])
        self.assertEqual(30, etat["secondes"])
        self.assertFalse(apertus_state.a_reprendre(HOTE))

    def test_une_tentative_qui_recommence_s_ajoute_a_la_precedente(self):
        """Une reprise qui échoue encore doit se distinguer d'une première
        séance, et le compteur ne s'incrémente qu'à l'ouverture."""
        apertus_state.commencer(HOTE, "ollama", "8b-q4", 9)
        apertus_state.commencer(HOTE, "ollama", "8b-q4", 9)
        self.assertEqual(2, apertus_state.lire(HOTE)["tentatives"])

    def test_un_echec_se_relit_dans_l_etat_et_dans_l_historique(self):
        apertus_state.commencer(HOTE, "ollama", "8b-q4", 9)
        apertus_state.avancer(HOTE, 4)
        apertus_state.noter_echec(HOTE, "version", "Check", 1, "trop ancien")
        etat = apertus_state.lire(HOTE)
        self.assertEqual("version", etat["etape_echouee"])
        self.assertEqual(1, etat["code"])
        self.assertTrue(apertus_state.a_reprendre(HOTE))
        dernier = apertus_state.dernier_echec(HOTE)
        self.assertEqual("version", dernier["etape"])
        self.assertEqual("trop ancien", dernier["queue"])

    def test_l_etat_enregistre_alimente_l_ecran_de_reprise(self):
        """Le bout en bout : ce que le disque garde doit rendre exactement
        l'écran que décrit `contexte_reprise`."""
        liste = apertus.etapes(
            apertus.MOTEUR_DEFAUT, apertus.MODELE_DEFAUT, CIBLE_LOCALE
        )
        apertus_state.commencer(HOTE, "ollama", "8b-q4", len(liste))
        apertus_state.avancer(HOTE, 4, secondes=192)
        apertus_state.noter_echec(HOTE, "version", "Check", 1, "trop ancien")
        vue = apertus.contexte_reprise(apertus_state.lire(HOTE), liste)
        self.assertEqual(4, vue["faites"])
        self.assertEqual(5, vue["reprise_a"])
        self.assertEqual("⛔", vue["etapes"][4]["icone"])

    def test_oublier_efface_la_progression_et_garde_l_historique(self):
        """C'est la raison d'être des deux dictionnaires. Si l'historique
        vivait dans `cibles`, « tout recommencer » effacerait justement ce
        que l'écran de reprise doit montrer."""
        apertus_state.commencer(HOTE, "ollama", "8b-q4", 9)
        apertus_state.noter_echec(HOTE, "version", "Check", 1, "trop ancien")
        apertus_state.oublier(HOTE)
        self.assertEqual({}, apertus_state.lire(HOTE))
        self.assertFalse(apertus_state.a_reprendre(HOTE))
        dernier = apertus_state.dernier_echec(HOTE)
        self.assertEqual("version", dernier["etape"])
        self.assertEqual("trop ancien", dernier["queue"])

    def test_oublier_une_cible_inconnue_ne_leve_pas(self):
        apertus_state.oublier("jamais-vu.invalid")
        self.assertEqual({}, apertus_state.lire("jamais-vu.invalid"))

    def test_deux_cibles_ne_se_melangent_pas(self):
        autre = "poste-sud.invalid"
        apertus_state.commencer(HOTE, "ollama", "8b-q4", 9)
        apertus_state.commencer(autre, "vllm", "mini-0.5b", 9)
        self.assertEqual("ollama", apertus_state.lire(HOTE)["moteur"])
        self.assertEqual("vllm", apertus_state.lire(autre)["moteur"])
        apertus_state.oublier(HOTE)
        self.assertEqual("vllm", apertus_state.lire(autre)["moteur"])

    def test_une_sortie_bavarde_est_tronquee_par_la_fin(self):
        """La cause est à la FIN : un début de compilation ne dit rien de
        l'erreur qui l'a close."""
        queue = "DEBUT" + "x" * apertus_state.QUEUE_MAX + "FIN"
        apertus_state.noter_echec(HOTE, "paquet", "Install", 2, queue)
        garde = apertus_state.lire(HOTE)["erreur"]
        self.assertEqual(apertus_state.QUEUE_MAX, len(garde))
        self.assertTrue(garde.endswith("FIN"))
        self.assertNotIn("DEBUT", garde)
        self.assertEqual(garde, apertus_state.dernier_echec(HOTE)["queue"])

    def test_l_historique_se_borne_aux_dernieres_entrees(self):
        """L'historique sert à comprendre la dernière séance, pas à tenir un
        journal : sans borne, le fichier croît sans fin."""
        for rang in range(apertus_state.ECHECS_MAX + 5):
            apertus_state.noter_echec(HOTE, "paquet", "Install", 1, str(rang))
        data = json.loads(self._fichier().read_text())
        self.assertEqual(apertus_state.ECHECS_MAX, len(data["echecs"]))
        self.assertEqual(
            str(apertus_state.ECHECS_MAX + 4), data["echecs"][-1]["queue"]
        )

    def test_un_etat_inexistant_est_un_dictionnaire_vide(self):
        self.assertEqual({}, apertus_state.lire(HOTE))
        self.assertEqual({}, apertus_state.dernier_echec(HOTE))
        self.assertFalse(apertus_state.a_reprendre(HOTE))
        self.assertEqual("never run", apertus_state.resume(HOTE))

    def test_un_fichier_abime_rend_un_etat_vide_sans_lever(self):
        """Perdre une reprise coûte un téléchargement ; empêcher le CLI de
        démarrer coûte davantage."""
        abimes = [
            "{ceci n'est pas du json",
            "[]",
            '"une chaîne"',
            json.dumps({"version": 99, "cibles": {HOTE: {"fin": "x"}}}),
            json.dumps({"version": 1, "cibles": [], "echecs": {}}),
        ]
        for contenu in abimes:
            with self.subTest(contenu=contenu[:24]):
                chemin = self._fichier()
                chemin.parent.mkdir(parents=True, exist_ok=True)
                chemin.write_text(contenu)
                self.assertEqual({}, apertus_state.lire(HOTE))
                self.assertEqual({}, apertus_state.dernier_echec(HOTE))
                self.assertFalse(apertus_state.a_reprendre(HOTE))

    def test_un_fichier_illisible_rend_un_etat_vide_sans_lever(self):
        """Un répertoire à la place du fichier tient lieu de disque plein ou
        de répertoire personnel en lecture seule : la lecture lève, et le
        module rend vide."""
        chemin = self._fichier()
        chemin.mkdir(parents=True, exist_ok=True)
        self.assertEqual({}, apertus_state.lire(HOTE))
        apertus_state.ecrire(HOTE, etape_faite=1)
        self.assertEqual({}, apertus_state.lire(HOTE))
        chemin.rmdir()

    def test_le_resume_dit_l_etat_en_un_mot(self):
        """Une CLÉ de traduction, jamais une phrase : la traduction
        appartient à l'appelant, et le module n'importe pas le CLI."""
        apertus_state.commencer(HOTE, "ollama", "8b-q4", 9)
        self.assertEqual("in progress", apertus_state.resume(HOTE))
        apertus_state.noter_echec(HOTE, "version", "Check", 1, "x")
        self.assertEqual("step %s/%s - failed", apertus_state.resume(HOTE))
        apertus_state.terminer(HOTE)
        self.assertEqual("installed on %s", apertus_state.resume(HOTE))


class LaFrontiere(unittest.TestCase):
    def test_les_deux_modules_ne_tirent_pas_todo(self):
        """Importer `script.todo.todo` coûte près d'une seconde et imprime
        sur la sortie : le paquet doit rester importable seul."""
        self.assertNotIn("script.todo.todo", sys.modules)


class LeMoteurApple(unittest.TestCase):
    """MLX : la pile d'Apple, et ce qu'elle change au reste."""

    def test_le_chemin_du_compte_s_etend_vraiment(self):
        """La faute à ne pas refaire.

        Un chemin cité par `shlex.quote` arrive dans le script entre
        apostrophes simples, et « $HOME » n'y est plus une variable mais
        quatre caractères. Le modèle serait alors converti dans un répertoire
        littéralement nommé « $HOME », et servi depuis un chemin qui n'existe
        pas. Le dollar doit rester hors de la citation.
        """
        chemin = apertus.sous_le_compte(".apertus-mlx/essai")
        vu = subprocess.run(
            ["sh", "-c", f"printf %s {chemin}"],
            env={"HOME": "/tmp/compte-invente", "PATH": os.environ["PATH"]},
            capture_output=True,
            text=True,
        )
        self.assertEqual("/tmp/compte-invente/.apertus-mlx/essai", vu.stdout)

    def test_la_conversion_ecrit_sous_le_compte_et_non_dans_le_depot(self):
        """Des dizaines de gigaoctets ne vivent jamais dans le dépôt."""
        etape = self._etape("mlx", "70b-q4", "tirer")
        self.assertIn('"$HOME"/.apertus-mlx/', etape.commande)
        self.assertNotIn("'$HOME", etape.commande)

    def test_le_moteur_est_borne_a_apple(self):
        self.assertEqual("Darwin", apertus.MOTEURS["mlx"].plateforme)
        self.assertEqual(
            [],
            [
                c
                for c, m in apertus.MOTEURS.items()
                if c != "mlx" and m.plateforme
            ],
        )

    def test_chaque_modele_a_sa_reference_mlx(self):
        for cle, modele in apertus.MODELES.items():
            with self.subTest(modele=cle):
                self.assertIn("mlx", modele.reference)
                self.assertTrue(modele.reference["mlx"])

    def test_seul_le_70b_se_convertit(self):
        """Les autres ont un build publié ; lui n'en a aucun."""
        a_convertir = [c for c, m in apertus.MODELES.items() if m.mlx_source]
        self.assertEqual(["70b-q4"], a_convertir)
        for cle in a_convertir:
            modele = apertus.MODELES[cle]
            # La source est le dépôt en poids pleins, la cible un chemin local.
            self.assertIn("swiss-ai/", modele.mlx_source)
            self.assertTrue(
                modele.reference["mlx"].startswith(apertus.MLX_LOCAL)
            )
            self.assertGreater(modele.mlx_source_taille, modele.taille)

    def test_les_builds_publies_sont_des_depots_et_non_des_chemins(self):
        for cle, modele in apertus.MODELES.items():
            if modele.mlx_source:
                continue
            with self.subTest(modele=cle):
                reference = modele.reference["mlx"]
                self.assertIn("/", reference)
                self.assertFalse(reference.startswith("."))
                self.assertNotIn("$", reference)

    def test_la_place_requise_compte_la_conversion(self):
        """Annoncer la seule taille finale tromperait de plus de 100 Go.

        La conversion tire les poids pleins AVANT d'écrire la version
        quantifiée, et les deux coexistent sur le disque. L'échec arriverait
        après une heure de téléchargement.
        """
        modele = apertus.MODELES["70b-q4"]
        sans = apertus.place_requise(modele, "ollama")
        avec = apertus.place_requise(modele, "mlx")
        self.assertGreater(avec, sans + modele.mlx_source_taille - 1)
        # Un modèle qui a son build publié ne paie rien de plus sur MLX.
        publie = apertus.MODELES["8b-q4"]
        self.assertEqual(
            apertus.place_requise(publie, "mlx"),
            apertus.place_requise(publie, "ollama"),
        )

    def test_la_version_minimale_est_celle_qui_connait_xielu(self):
        """En dessous, l'activation d'Apertus n'existe pas dans la pile."""
        self.assertEqual("0.27.1", apertus.MOTEURS["mlx"].version_min)
        self.assertTrue(apertus.version_suffisante("mlx", "0.27.1"))
        self.assertTrue(apertus.version_suffisante("mlx", "1.0.0"))
        self.assertFalse(apertus.version_suffisante("mlx", "0.27.0"))
        self.assertFalse(apertus.version_suffisante("mlx", ""))

    def _etape(self, moteur, modele, cle):
        for e in apertus.etapes(moteur, modele, CIBLE_LOCALE):
            if e.cle == cle:
                return e
        self.fail(f"étape {cle} absente de {moteur}/{modele}")


if __name__ == "__main__":
    unittest.main()
