#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les séquences du moteur, et ce que todo en conduit — sans rien masquer.

Le Makefile du moteur ne dit nulle part dans quel ordre jouer ses cibles ; le
registre le dit. Une séquence dont on retirerait ce que todo ne lance pas
mentirait donc par omission, et le pire cas n'est pas théorique : une séquence
de trois étapes se réduirait à zéro, et une autre commencerait à son étape 2.

Ce qui est éprouvé ici : la lecture fermée par défaut, la règle de périmètre
écrite UNE fois, et le fait que chaque étape porte sa barrière plutôt que de
disparaître.

Les identifiants de runbook et de cible sont inventés et n'existent nulle part
ailleurs dans le dépôt.
"""

import os
import re
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.setops import ansible_env, engine, runner  # noqa: E402
from script.setops import runbooks as R  # noqa: E402

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def registre_reel():
    """Le registre du MOTEUR tel qu'il est sur ce poste, ou None s'il n'y est
    pas.

    Le chemin vient du manifeste, seule autorité : l'écrire ici en ferait une
    copie, qui dérive au premier déplacement. Un poste sans moteur rapatrié
    fait SAUTER les épreuves qui en dépendent, plutôt que rougir sur une
    absence qui n'est pas un défaut.
    """
    decl = engine.declaration(RACINE)
    if decl is None or not decl.path:
        return None
    moteur = os.path.join(RACINE, decl.path)
    if not os.path.isdir(moteur):
        return None
    vu = runner.jouer(
        R.ARGV_REGISTRE,
        env=ansible_env.environnement(RACINE, moteur, runner.base()),
        cwd=moteur,
    )
    return R.lit_registre(vu.sortie)


REEL = registre_reel()
AVEC_MOTEUR = unittest.skipUnless(
    REEL is not None, "registre du moteur illisible"
)

# La forme exacte que rend « runbooks.py lister --json ».
REGISTRE = """[
  {
    "id": "banc-fictif-sequence",
    "titre": "Une sequence de banc",
    "portee": "tenant",
    "but": "Eprouver la lecture.",
    "etapes": [
      {"cible": "banc-mesurer", "libelle": "Mesure", "portee": "toute",
       "nature": "mesure", "pourquoi": "Parce que.", "duree": "",
       "variables": [], "fixes": {}},
      {"cible": "banc-ecrire", "libelle": "Ecrit", "portee": "tenant",
       "nature": "ecriture", "pourquoi": "Parce que.", "duree": "long",
       "variables": [{"nom": "NOM", "invite": "Le nom", "facultatif": false},
                     {"nom": "SEUL", "invite": "Un seul", "facultatif": true}],
       "fixes": {}},
      {"cible": "banc-raser", "libelle": "Detruit", "portee": "site",
       "nature": "destructif", "pourquoi": "Parce que.", "duree": "",
       "variables": [], "fixes": {"CONFIRMER": "true"}},
      {"cible": "banc-garde", "libelle": "Garde du moteur", "portee": "toute",
       "nature": "ecriture", "pourquoi": "Parce que.", "duree": "",
       "variables": [], "fixes": {"CONFIRMER": "true"}}
    ]
  }
]
"""


def etape(**champs):
    base = dict(
        cible="banc-fictif",
        libelle="",
        portee=R.TOUTE,
        nature=R.MESURE,
        pourquoi="",
        duree="",
        variables=(),
        exige_confirmation=False,
        facultative=False,
    )
    base.update(champs)
    return R.Etape(**base)


class TestLaLectureDuRegistre(unittest.TestCase):
    def test_a_real_registry_is_read_in_order(self):
        """Le contrôle positif : sans lui, un lecteur qui refuse tout
        passerait chacun des refus éprouvés plus bas."""
        lus = R.lit_registre(REGISTRE)
        self.assertEqual(1, len(lus))
        self.assertEqual("banc-fictif-sequence", lus[0].id)
        self.assertEqual(
            ["banc-mesurer", "banc-ecrire", "banc-raser", "banc-garde"],
            [e.cible for e in lus[0].etapes],
        )

    def test_the_confirmation_a_step_demands_is_read(self):
        lus = R.lit_registre(REGISTRE)
        self.assertEqual(
            [False, False, True, True],
            [e.exige_confirmation for e in lus[0].etapes],
        )

    def test_a_warning_before_the_document_does_not_hide_it(self):
        """Un avertissement de Python sur la sortie ne doit pas rendre le
        registre illisible."""
        self.assertIsNotNone(
            R.lit_registre("DeprecationWarning: …\n" + REGISTRE)
        )

    def test_anything_that_is_not_a_list_is_unknown(self):
        for texte in ("{}", "rien", "", None, "[]"):
            with self.subTest(texte=texte):
                self.assertIsNone(R.lit_registre(texte))

    def test_a_step_whose_nature_is_unknown_refuses_the_whole_registry(self):
        """Une séquence partielle est pire qu'une absence : son ORDRE est ce
        qu'on vient y chercher."""
        self.assertIsNone(
            R.lit_registre(
                REGISTRE.replace('"nature": "mesure"', '"nature": "peut-etre"')
            )
        )

    def test_a_runbook_without_a_step_is_unknown(self):
        self.assertIsNone(
            R.lit_registre('[{"id": "x", "portee": "toute", "etapes": []}]')
        )

    def test_a_step_without_a_scope_refuses_the_whole_registry(self):
        """C'est sur la portée que `barriere` décide du périmètre. Tolérée
        absente, elle laissait une étape d'ÉCRITURE se conduire sans écosystème
        monté — donc sur ce qui se trouve être monté, ou sur rien. Une valeur
        inconnue était refusée et une valeur manquante ne l'était pas."""
        for sans in ('"portee": "toute",', '"portee":"toute",'):
            if sans in REGISTRE:
                self.assertIsNone(
                    R.lit_registre(REGISTRE.replace(sans, "", 1))
                )
                break
        else:
            self.fail("la fixture ne porte pas la forme attendue")

    def test_a_scope_that_is_null_refuses_it_too(self):
        self.assertIsNone(
            R.lit_registre(
                REGISTRE.replace('"portee": "toute"', '"portee": null', 1)
            )
        )

    def test_a_scope_outside_the_vocabulary_is_unknown(self):
        self.assertIsNone(
            R.lit_registre(
                REGISTRE.replace('"portee": "tenant"', '"portee": "ailleurs"')
            )
        )


class TestLaRegleDePerimetre(unittest.TestCase):
    """Écrite UNE fois, dans `barriere()`. Deux copies diraient tôt ou tard
    deux choses différentes du même geste."""

    def test_what_destroys_is_never_driven_from_here(self):
        self.assertEqual(
            R.DESTRUCTIVE,
            R.barriere(etape(nature=R.DESTRUCTIF), "eco", "site"),
        )

    def test_what_the_engine_gates_stays_with_the_engine(self):
        self.assertEqual(
            R.CONFIRMATION_MOTEUR,
            R.barriere(etape(exige_confirmation=True), "eco", "site"),
        )

    def test_a_tenant_step_needs_a_mounted_ecosystem(self):
        self.assertEqual(
            R.SANS_ECOSYSTEME, R.barriere(etape(portee=R.TENANT), "", "site")
        )
        self.assertEqual("", R.barriere(etape(portee=R.TENANT), "eco", ""))

    def test_a_site_step_needs_a_mounted_site(self):
        self.assertEqual(
            R.SANS_SITE, R.barriere(etape(portee=R.SITE), "eco", "")
        )
        self.assertEqual("", R.barriere(etape(portee=R.SITE), "", "site"))

    def test_a_station_step_needs_nothing(self):
        for portee in (R.POSTE, R.TOUTE):
            with self.subTest(portee=portee):
                self.assertEqual("", R.barriere(etape(portee=portee), "", ""))

    def test_an_unreadable_step_is_never_driven(self):
        self.assertEqual(R.FORME_INCONNUE, R.barriere(None, "eco", "site"))

    def test_every_barrier_named_is_in_the_closed_vocabulary(self):
        """Une barrière hors vocabulaire ne se traduirait pas à l'écran."""
        vues = {
            R.barriere(etape(nature=n, portee=p, exige_confirmation=c), "", "")
            for n in R.NATURES
            for p in R.PORTEES
            for c in (True, False)
        }
        for barriere in vues - {""}:
            with self.subTest(barriere=barriere):
                self.assertIn(barriere, R.BARRIERES)


class TestRienNestMasque(unittest.TestCase):
    """Le cœur du parti : ce qui ne se lance pas d'ici reste AFFICHÉ."""

    def setUp(self):
        self.runbook = R.lit_registre(REGISTRE)[0]

    def test_the_sequence_keeps_every_step_whatever_the_station(self):
        self.assertEqual(4, len(self.runbook.etapes))

    def test_the_count_says_how_many_of_how_many(self):
        """Une liste dont on ne sait pas combien elle offre se parcourt en
        entier pour le découvrir.

        LE PALIER COMPTE POUR CONDUISIBLE, parce que sa porte le conduit — elle
        demande une retape, elle ne refuse pas. Sans écosystème ni site : la
        mesure de portée « toute » et le geste du palier de même portée. Avec
        les deux montés : les quatre."""
        self.assertEqual((2, 4), R.compte(self.runbook, "", ""))
        self.assertEqual((4, 4), R.compte(self.runbook, "eco", "site"))

    def test_a_sequence_that_offers_nothing_still_shows_its_steps(self):
        """Le pire cas, et il n'est pas théorique : une séquence de quatre
        étapes se réduirait à zéro si l'on masquait les barrées.

        LE ZÉRO VIENT D'UNE IMPOSSIBILITÉ, non d'une précaution : toutes les
        étapes sont de portée site, et aucun site n'est monté. Le produire par
        la nature destructrice ne marcherait plus — confirmer la lève, parce que
        c'est une précaution, alors qu'un site absent ne s'invente pas."""
        toutes_de_site = REGISTRE.replace(
            '"portee": "toute"', '"portee": "site"'
        ).replace('"portee": "tenant"', '"portee": "site"')
        runbook = R.lit_registre(toutes_de_site)[0]
        self.assertEqual((0, 4), R.compte(runbook, "eco", ""))
        self.assertEqual(4, len(runbook.etapes))

    def test_the_precaution_and_the_impossibility_do_not_count_alike(self):
        """Le contrôle positif du précédent : la même séquence, site monté,
        offre tout. Sans lui, un compte toujours nul passerait."""
        toutes_de_site = REGISTRE.replace(
            '"portee": "toute"', '"portee": "site"'
        ).replace('"portee": "tenant"', '"portee": "site"')
        runbook = R.lit_registre(toutes_de_site)[0]
        self.assertEqual((4, 4), R.compte(runbook, "eco", "site"))


class TestLesVariablesSontDesTables(unittest.TestCase):
    """Le registre écrit {nom, invite, facultatif}, pas un nom.

    Les traiter comme des chaînes faisait demander une valeur pour
    « {'nom': 'HOTE', …} » et passait cette table à `make` comme nom de
    variable. La fixture disait « ["NOM"] » — une forme INVENTÉE, jamais
    capturée du moteur, et c'est ce qui a laissé passer le défaut.
    """

    def setUp(self):
        self.runbook = R.lit_registre(REGISTRE)[0]

    def test_a_variable_carries_the_prompt_the_engine_wrote(self):
        """Le reformuler ferait deux libellés pour la même question."""
        attendue = self.runbook.etapes[1].variables[0]
        self.assertEqual("NOM", attendue.nom)
        self.assertEqual("Le nom", attendue.invite)
        self.assertFalse(attendue.facultative)

    def test_an_optional_variable_says_it_is(self):
        """Sept des trente-quatre variables réelles sont facultatives :
        exiger une réponse les rendrait bloquantes."""
        self.assertTrue(self.runbook.etapes[1].variables[1].facultative)

    def test_a_variable_that_is_not_a_table_refuses_the_registry(self):
        self.assertIsNone(
            R.lit_registre(
                REGISTRE.replace('"variables": [', '"variables": ["NOM", ', 1)
            )
        )

    def test_a_variable_without_a_name_refuses_the_registry(self):
        self.assertIsNone(
            R.lit_registre(REGISTRE.replace('"nom": "NOM"', '"nom": "  "', 1))
        )


class TestCeQuiEcrit(unittest.TestCase):
    """Todo pose sa PROPRE confirmation sur une écriture : la ligne affichée
    porte `CONFIRMER=false`, et pour ces cibles-là le drapeau ne veut rien
    dire — elles écrivent quand même."""

    def test_a_write_is_named_as_such(self):
        self.assertTrue(R.ecrit(etape(nature=R.ECRITURE)))

    def test_a_measure_is_not(self):
        self.assertFalse(R.ecrit(etape(nature=R.MESURE)))

    def test_nothing_is_not_a_write(self):
        self.assertFalse(R.ecrit(None))


class TestLesPortes(unittest.TestCase):
    """Onze portes, dérivées du registre. Le nom de la méthode qui ouvre
    chacune se DÉDUIT de la cible, donc aucune table n'est à tenir."""

    def test_the_method_name_comes_from_the_target(self):
        self.assertEqual(
            "_setops_geste_instancier_appliquer",
            R.methode("instancier-appliquer"),
        )

    def test_every_door_names_a_distinct_target(self):
        self.assertEqual(len(R.PORTES), len(set(R.PORTES.values())))

    def test_a_target_declared_once_is_found(self):
        lus = R.lit_registre(REGISTRE)
        self.assertEqual("banc-ecrire", R.trouve(lus, "banc-ecrire").cible)

    def test_a_target_the_registry_ignores_is_not_found(self):
        lus = R.lit_registre(REGISTRE)
        self.assertIsNone(R.trouve(lus, "banc-fictif-jamais-declare"))
        self.assertIsNone(R.trouve(None, "banc-ecrire"))

    def test_two_sequences_declaring_the_same_target_alike_is_no_problem(self):
        """L'ordre d'une séquence à l'autre peut répéter une cible ; tant que
        la déclaration est la même, la porte en ouvre une sans ambiguïté."""
        deux = REGISTRE.replace("banc-fictif-sequence", "banc-fictif-bis")
        lus = R.lit_registre(REGISTRE[:-2] + "," + deux[1:])
        self.assertEqual(2, len(lus))
        self.assertIsNotNone(R.trouve(lus, "banc-ecrire"))

    def test_two_sequences_that_disagree_open_no_door(self):
        """Une porte qui trancherait au hasard lancerait parfois l'autre
        geste."""
        autre = REGISTRE.replace("banc-fictif-sequence", "banc-fictif-bis")
        autre = autre.replace('"libelle": "Ecrit"', '"libelle": "Autre chose"')
        lus = R.lit_registre(REGISTRE[:-2] + "," + autre[1:])
        self.assertEqual(2, len(lus))
        self.assertIsNone(R.trouve(lus, "banc-ecrire"))


class TestLesEcarts(unittest.TestCase):
    """Ce que todo sait et que le registre ne dit pas ENCORE."""

    def test_a_target_without_a_divergence_has_an_empty_one(self):
        """Jamais None : l'appelant lit toujours des champs."""
        vide = R.ecart("banc-fictif-sans-ecart")
        self.assertFalse(vide.remis or vide.ecrit or vide.drapeau)

    def test_an_assistant_that_writes_is_a_write_whatever_its_nature(self):
        etape = R.Etape(
            cible="config",
            libelle="",
            portee=R.TENANT,
            nature=R.MESURE,
            pourquoi="",
            duree="",
            variables=(),
            exige_confirmation=False,
            facultative=False,
        )
        self.assertTrue(R.ecrit(etape))
        self.assertTrue(R.remis(etape))

    def test_a_plain_measure_stays_a_measure(self):
        self.assertFalse(R.ecrit(etape(nature=R.MESURE)))
        self.assertFalse(R.remis(etape(nature=R.MESURE)))

    def test_the_switch_is_named_only_where_there_is_one(self):
        self.assertEqual(
            "FORCE", R.drapeau(etape(cible="instancier-appliquer"))
        )
        self.assertEqual("", R.drapeau(etape(cible="deployer")))
        self.assertEqual("", R.drapeau(None))

    def test_every_divergence_says_why_it_exists(self):
        """Une dérogation sans raison écrite est une dérogation qu'on
        reconduit sans savoir pourquoi."""
        for cible, vu in R.ECARTS.items():
            with self.subTest(cible=cible):
                self.assertTrue(vu.pourquoi, cible)


@AVEC_MOTEUR
class TestContreLeRegistreReel(unittest.TestCase):
    """Les épreuves qui interrogent le MOTEUR de ce poste. Elles sautent
    là où il n'est pas rapatrié : son absence n'est pas un défaut."""

    def test_every_door_names_a_target_the_engine_declares(self):
        """Une porte dont la cible a disparu du registre mène à un écran qui
        refuse, et le menu l'annonce quand même."""
        for cible in R.PORTES:
            with self.subTest(cible=cible):
                self.assertIsNotNone(R.trouve(REEL, cible), cible)

    def test_every_divergence_names_a_target_the_engine_declares(self):
        for cible in R.ECARTS:
            with self.subTest(cible=cible):
                self.assertIsNotNone(R.trouve(REEL, cible), cible)

    def test_the_write_divergence_is_still_one(self):
        """LE JOUR OÙ LE REGISTRE LE DIT LUI-MÊME, cette épreuve rougit et
        l'entrée d'`ECARTS` doit partir : la garder masquerait la correction
        en amont."""
        for cible, vu in R.ECARTS.items():
            if not vu.ecrit:
                continue
            with self.subTest(cible=cible):
                self.assertEqual(R.MESURE, R.trouve(REEL, cible).nature, cible)

    def test_every_handed_over_target_demands_the_variable_we_name(self):
        """LA TAUTOLOGIE LEVÉE. Le garde d'avant comparait la table à
        elle-même : que la variable soit LA BONNE n'était mesuré nulle part.
        Remise avec la mauvaise, la ligne se fait refuser par le moteur et la
        remise n'aurait rien donné."""
        decl = engine.declaration(RACINE)
        makefile = os.path.join(RACINE, decl.path, "Makefile")
        with open(makefile, encoding="utf-8") as tenu:
            texte = tenu.read()
        for cible, variable in R.remises().items():
            if not variable:
                continue
            with self.subTest(cible=cible):
                debut = texte.index(f"\n{cible}:")
                recette = texte[debut : texte.index("\n\n", debut)]
                exigees = set(re.findall(r"relancer avec ([A-Z]+)=", recette))
                self.assertEqual({variable}, exigees, cible)

    # Ce que le moteur écrit dans une recette qu'il réserve à un humain.
    RESERVEE = "A LANCER SOI-MEME"

    def cibles_reservees(self):
        """Les cibles que le Makefile du moteur réserve à un humain.

        Lues dans SA source : une liste tenue de notre côté ne suit pas la
        sienne, et c'est précisément ainsi qu'une quatrième cible avait été
        oubliée.
        """
        decl = engine.declaration(RACINE)
        chemin = os.path.join(RACINE, decl.path, "Makefile")
        with open(chemin, encoding="utf-8") as tenu:
            lignes = tenu.read().splitlines()
        trouvees, courante = set(), ""
        for ligne in lignes:
            entete = re.match(r"^([a-z][a-z0-9-]*):", ligne)
            if entete:
                courante = entete.group(1)
            elif ligne[:1] not in ("\t", " ", "#", ""):
                courante = ""
            if self.RESERVEE in ligne and courante:
                trouvees.add(courante)
        return trouvees

    def test_the_search_finds_what_the_engine_reserves(self):
        """Contrôle positif : sans lui, une recherche qui ne trouve jamais
        rien passerait le garde ci-dessous."""
        self.assertTrue(self.cibles_reservees())

    def test_every_target_the_engine_reserves_is_handed_over(self):
        """LE MANQUE QUI AVAIT LAISSÉ PASSER UNE CIBLE. Rien ne confrontait la
        liste à celle du moteur : une cible marquée en amont et absente d'ici
        se conduit depuis les écrans, alors que le moteur la réserve à un
        humain."""
        remises = set(R.remises())
        for cible in sorted(self.cibles_reservees()):
            with self.subTest(cible=cible):
                self.assertIn(cible, remises, cible)

    def test_every_handed_over_target_exists_in_the_engine(self):
        for cible in R.remises():
            with self.subTest(cible=cible):
                self.assertIsNotNone(R.trouve(REEL, cible), cible)

    def test_the_switch_divergence_is_still_one(self):
        """Même chose : si le registre déclare enfin ce drapeau comme une
        variable, l'entrée doit partir."""
        for cible, vu in R.ECARTS.items():
            if not vu.drapeau:
                continue
            with self.subTest(cible=cible):
                declarees = {v.nom for v in R.trouve(REEL, cible).variables}
                self.assertNotIn(vu.drapeau, declarees)


def etape_palier(**change):
    """Une étape du registre, que chaque épreuve altère d'un champ."""
    champs = dict(
        cible="une-cible",
        libelle="",
        portee="tenant",
        nature=R.ECRITURE,
        pourquoi="",
        duree="",
        variables=(),
        exige_confirmation=True,
        facultative=False,
    )
    champs.update(change)
    return R.Etape(**champs)


class TestLePalierDestructeurEstDerive(unittest.TestCase):
    """Une liste écrite dans todo vieillirait, et du MAUVAIS CÔTÉ : elle
    laisserait passer sans garde le geste que l'amont vient de rendre
    destructeur."""

    def test_a_declared_destructive_step_is_in(self):
        self.assertTrue(
            R.destructeur(
                etape_palier(nature=R.DESTRUCTIF, exige_confirmation=False)
            )
        )

    def test_a_step_that_merely_demands_confirmation_is_in_too(self):
        """LES DEUX CRITÈRES NE SE RECOUVRENT PAS : d'autres gestes exigent une
        confirmation sans être déclarés destructeurs, et leur effet est le même.
        Ce que le moteur PROTÈGE compte, pas ce qu'il nomme."""
        self.assertTrue(
            R.destructeur(
                etape_palier(nature=R.ECRITURE, exige_confirmation=True)
            )
        )

    def test_a_plain_write_is_out(self):
        """Le contrôle positif : sans lui, un palier qui contient tout
        passerait les deux épreuves ci-dessus."""
        self.assertFalse(
            R.destructeur(
                etape_palier(nature=R.ECRITURE, exige_confirmation=False)
            )
        )

    def test_a_measure_is_out(self):
        self.assertFalse(
            R.destructeur(
                etape_palier(nature=R.MESURE, exige_confirmation=False)
            )
        )

    def test_nothing_is_out(self):
        self.assertFalse(R.destructeur(None))


class TestCeQuOnFaitRetaper(unittest.TestCase):
    """La plupart des gestes du palier ne nomment aucune variable : il n'y a rien
    à leur emprunter. La portée, elle, dit toujours SUR QUOI le geste porte."""

    def test_the_scope_decides_what_is_retyped(self):
        for portee, attendu in (
            ("tenant", R.RETAPE_ECOSYSTEME),
            ("site", R.RETAPE_SITE),
            ("poste", R.RETAPE_HOTES),
        ):
            with self.subTest(portee=portee):
                self.assertEqual(
                    attendu, R.retape(etape_palier(portee=portee))
                )

    def test_what_is_not_in_the_tier_asks_nothing(self):
        """« » n'est pas « n'importe quoi convient » : l'appelant ne doit pas
        confondre les deux."""
        self.assertEqual(
            "",
            R.retape(etape_palier(nature=R.MESURE, exige_confirmation=False)),
        )

    def test_a_scope_outside_the_three_asks_nothing(self):
        """Fermé par défaut : une portée qu'on ne connaît pas ne fait pas
        inventer une question."""
        self.assertEqual("", R.retape(etape_palier(portee="inventee")))

    def test_every_answer_is_in_the_closed_vocabulary_or_empty(self):
        for portee in ("tenant", "site", "poste", "inventee", ""):
            with self.subTest(portee=portee):
                vu = R.retape(etape_palier(portee=portee))
                self.assertIn(vu, R.RETAPES + ("",))

    def test_the_expected_text_comes_from_what_is_mounted(self):
        self.assertEqual(
            "OPS-Un-Eco",
            R.attendu_retape(R.RETAPE_ECOSYSTEME, ecosysteme=" OPS-Un-Eco "),
        )
        self.assertEqual(
            "SITE-Un-Site",
            R.attendu_retape(R.RETAPE_SITE, site="SITE-Un-Site"),
        )

    def test_zero_hosts_is_a_count(self):
        """Un geste qui ne toucherait aucune machine se fait confirmer par « 0 »,
        ce qui est justement l'information utile."""
        self.assertEqual("0", R.attendu_retape(R.RETAPE_HOTES, hotes=0))

    def test_a_count_that_was_not_read_asks_nothing(self):
        """« » ARRÊTE LE GESTE chez l'appelant : un garde qui accepte n'importe
        quoi parce qu'il n'attend rien est pire que pas de garde, puisqu'il
        donne l'assurance d'en être un."""
        for hotes in (None, -1, True, "4", 4.0):
            with self.subTest(hotes=hotes):
                self.assertEqual(
                    "", R.attendu_retape(R.RETAPE_HOTES, hotes=hotes)
                )

    def test_nothing_mounted_asks_nothing(self):
        for quoi, champs in (
            (R.RETAPE_ECOSYSTEME, {"ecosysteme": "   "}),
            (R.RETAPE_SITE, {"site": ""}),
        ):
            with self.subTest(quoi=quoi):
                self.assertEqual("", R.attendu_retape(quoi, **champs))


class TestLaRetapeEstStricte(unittest.TestCase):
    """Le but n'est pas de vérifier qu'il sait écrire mais qu'il a REGARDÉ : une
    comparaison indulgente laisse confirmer de mémoire, et c'est précisément ce
    que ce garde existe pour empêcher."""

    def test_the_exact_text_passes(self):
        """Le contrôle positif de tous les refus ci-dessous."""
        self.assertTrue(R.retape_concorde("OPS-Un-Eco", "OPS-Un-Eco"))

    def test_border_whitespace_is_forgiven(self):
        """Il vient du copier-coller, non de la mémoire."""
        self.assertTrue(R.retape_concorde("OPS-Un-Eco", "  OPS-Un-Eco\n"))

    def test_another_case_is_refused(self):
        self.assertFalse(R.retape_concorde("OPS-Un-Eco", "ops-un-eco"))

    def test_a_prefix_is_refused(self):
        self.assertFalse(R.retape_concorde("OPS-Un-Eco", "OPS-Un"))

    def test_an_expected_that_is_empty_always_refuses(self):
        """Il dit qu'on n'a pas su quoi demander."""
        for tape in ("", "n-importe-quoi", None):
            with self.subTest(tape=tape):
                self.assertFalse(R.retape_concorde("", tape))

    def test_nothing_typed_is_refused(self):
        for tape in ("", "   ", None):
            with self.subTest(tape=tape):
                self.assertFalse(R.retape_concorde("OPS-Un-Eco", tape))


class TestLaBarriereNeSeLeveQueDeSesDeuxRefusDuPalier(unittest.TestCase):
    """Lever une précaution ne fait pas apparaître un site. Confirmé ou non, ce
    qui est IMPOSSIBLE reste barré ; seul ce qui était une précaution se lève."""

    def test_confirming_lifts_the_declared_destructive(self):
        self.assertEqual(
            "",
            R.barriere(
                etape_palier(nature=R.DESTRUCTIF), "eco", "site", confirme=True
            ),
        )

    def test_confirming_lifts_the_demanded_confirmation(self):
        self.assertEqual(
            "", R.barriere(etape_palier(), "eco", "site", confirme=True)
        )

    def test_confirming_does_not_lift_a_missing_scope(self):
        """LA PROPRIÉTÉ : c'est une impossibilité, non une précaution. Un geste
        de site sans site monté n'a rien sur quoi porter."""
        self.assertEqual(
            R.SANS_ECOSYSTEME,
            R.barriere(
                etape_palier(portee=R.TENANT), "", "site", confirme=True
            ),
        )
        self.assertEqual(
            R.SANS_SITE,
            R.barriere(etape_palier(portee=R.SITE), "eco", "", confirme=True),
        )

    def test_confirming_does_not_lift_an_unreadable_form(self):
        for etape in (None, etape_palier(nature="inventee")):
            with self.subTest(etape=etape):
                self.assertEqual(
                    R.FORME_INCONNUE,
                    R.barriere(etape, "eco", "site", confirme=True),
                )

    def test_the_default_confirms_nothing(self):
        """CE QUI REND L'AJOUT SÛR : aucun appelant existant n'élargit son
        périmètre sans l'avoir écrit. Un défaut vrai aurait ouvert d'un coup
        tout le palier à chaque écran qui demande « celui-ci se conduit-il ? »."""
        self.assertEqual(
            R.DESTRUCTIVE,
            R.barriere(etape_palier(nature=R.DESTRUCTIF), "eco", "site"),
        )
        self.assertEqual(
            R.CONFIRMATION_MOTEUR, R.barriere(etape_palier(), "eco", "site")
        )

    def test_a_step_handed_upstream_stays_barred(self):
        """Un geste remis à l'amont n'est pas une précaution qu'on lève : todo
        ne le conduit plus du tout."""
        for remise in R.remises():
            etape = etape_palier(cible=remise)
            if R.barriere(etape, "eco", "site") != R.A_REMETTRE:
                continue
            with self.subTest(cible=remise):
                self.assertEqual(
                    R.A_REMETTRE,
                    R.barriere(etape, "eco", "site", confirme=True),
                )
            break
        else:
            self.skipTest("aucune remise ne tombe sur cette barrière")

    def test_every_answer_stays_in_the_closed_vocabulary(self):
        for confirme in (False, True):
            for portee in (R.TENANT, R.SITE, "poste"):
                for nature in R.NATURES:
                    with self.subTest(
                        confirme=confirme, portee=portee, nature=nature
                    ):
                        vu = R.barriere(
                            etape_palier(portee=portee, nature=nature),
                            "",
                            "",
                            confirme=confirme,
                        )
                        self.assertIn(vu, R.BARRIERES + ("",))


class TestLaCibleQuiCompteLesHotesResteUneMesure(unittest.TestCase):
    """Le palier la joue pour obtenir le nombre qu'il fait retaper. Devenue
    ÉCRITURE en amont, elle serait dès lors jouée avant CHAQUE destruction, sans
    que rien ne le dise — et le geste qu'on croyait préparer en aurait déjà
    changé l'état."""

    def registre(self):
        """Le registre du moteur, ou un saut si le clone n'est pas là."""
        import os
        import subprocess
        import sys

        racine = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        moteur = os.path.join(racine, "private", "repo", "Set-OPS-Public")
        if not os.path.isdir(moteur):
            self.skipTest("le clone du moteur n'est pas là")
        sys.path.insert(0, racine)
        from script.setops import runner

        # L'ENVIRONNEMENT NEUF SUFFIT : le recenseur du registre est du python
        # pur, sans ansible. Y monter le venv du moteur ferait dépendre cette
        # épreuve d'une bibliothèque que la lecture n'emploie pas.
        vu = runner.jouer(
            R.ARGV_REGISTRE,
            env=runner.base(),
            cwd=moteur,
            fusionner=False,
            delai=180,
        )
        lus = R.lit_registre(vu.sortie)
        if lus is None:
            self.skipTest("le registre du moteur ne s'est pas lu")
        return lus

    def etapes_de(self, lus, cible):
        return [e for rb in lus for e in rb.etapes if e.cible == cible]

    def test_the_engine_declares_it_a_measure(self):
        vues = self.etapes_de(self.registre(), R.CIBLE_SERVEURS)
        self.assertNotEqual(
            [], vues, f"« {R.CIBLE_SERVEURS} » absente du registre"
        )
        for etape in vues:
            with self.subTest(portee=etape.portee):
                self.assertEqual(R.MESURE, etape.nature)
                self.assertFalse(etape.exige_confirmation)

    def test_it_is_therefore_outside_the_tier(self):
        """La conséquence qui compte : la jouer ne demande aucune confirmation,
        donc la porte du palier ne se rappelle pas elle-même."""
        for etape in self.etapes_de(self.registre(), R.CIBLE_SERVEURS):
            with self.subTest(portee=etape.portee):
                self.assertFalse(R.destructeur(etape))

    def test_the_check_would_notice_a_write(self):
        """Le contrôle positif : sans lui, une recherche qui ne trouve jamais
        d'écriture passerait les deux épreuves ci-dessus."""
        lus = self.registre()
        ecritures = [
            e for rb in lus for e in rb.etapes if e.nature == R.ECRITURE
        ]
        self.assertNotEqual(
            [], ecritures, "le registre ne déclare aucune écriture"
        )


class TestChaqueGesteDuPalierPeutEtreGarde(unittest.TestCase):
    """L'ÉPREUVE DE COUVERTURE. Un geste du palier dont la portée n'a rien à
    faire retaper est INCONDUISIBLE : sa porte refuse faute de savoir quoi
    demander. C'est le sens SÛR du refus, mais il se lit comme une panne, et rien
    ne dirait d'où il vient. Cette épreuve le dit le jour où l'amont rend
    destructeur un geste d'une portée que la porte ne sait pas garder."""

    def registre(self):
        import os
        import sys

        racine = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        moteur = os.path.join(racine, "private", "repo", "Set-OPS-Public")
        if not os.path.isdir(moteur):
            self.skipTest("le clone du moteur n'est pas là")
        sys.path.insert(0, racine)
        from script.setops import runner

        vu = runner.jouer(
            R.ARGV_REGISTRE,
            env=runner.base(),
            cwd=moteur,
            fusionner=False,
            delai=180,
        )
        lus = R.lit_registre(vu.sortie)
        if lus is None:
            self.skipTest("le registre du moteur ne s'est pas lu")
        return lus

    def palier(self, lus):
        vues = {}
        for runbook in lus:
            for etape in runbook.etapes:
                if R.destructeur(etape):
                    vues.setdefault(etape.cible, etape)
        return vues

    def test_every_tier_gesture_has_something_to_retype(self):
        vues = self.palier(self.registre())
        self.assertNotEqual(
            {}, vues, "le registre ne déclare aucun geste du palier"
        )
        muets = sorted(c for c, e in vues.items() if not R.retape(e))
        self.assertEqual(
            [],
            muets,
            f"ces gestes du palier n'ont rien à faire retaper : {muets}",
        )

    def test_a_scope_the_door_cannot_gate_would_be_caught(self):
        """Le contrôle positif : sans lui, une recherche qui ne trouve jamais de
        geste muet passerait l'épreuve ci-dessus. La portée « toute » existe dans
        le registre — huit étapes la portent — et n'a rien à faire retaper."""
        lus = self.registre()
        portees = {e.portee for rb in lus for e in rb.etapes}
        sans_retape = {
            p
            for p in portees
            if not R.retape(
                R.Etape("c", "", p, R.DESTRUCTIF, "", "", (), True, False)
            )
        }
        self.assertNotEqual(
            set(),
            sans_retape,
            "aucune portée n'est ingardable : le contrôle ne prouve rien",
        )


if __name__ == "__main__":
    unittest.main()
