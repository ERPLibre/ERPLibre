#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'ordre des règles est une propriété, et voici ce qui casse s'il bouge.

Un jeu de règles qui contient les bonnes lignes dans le mauvais ordre ne
protège rien, et se relit comme s'il protégeait. Ces épreuves comparent des
INDICES de ligne, parce que « la ligne est présente » ne dit rien de ce qui
compte ici.

Rien n'exécute nftables. Ce n'est pas une facilité : sur cette station,
`nft -c` — qui ne fait qu'analyser — échoue déjà sur « Operation not
permitted », si bien qu'une épreuve qui l'appelle mesurerait le privilège
de qui la lance plutôt que le texte rendu. La syntaxe se vérifie à la main,
une fois, contre le vrai analyseur.

Les adresses citées sont des plages de documentation (RFC 5737, RFC 3849)
et les noms sont en « .example » (RFC 2606).
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.lib_valid import ValidationError  # noqa: E402
from script.posture import allowlist as A  # noqa: E402
from script.posture import registry as R  # noqa: E402
from script.posture import rules  # noqa: E402

RESOLVEUR = A.resolve("dns-resolver", ["198.51.100.53"])
FORGE = A.resolve("forge", ["198.51.100.0/24", "2001:db8::/32"])
BORNEE = [RESOLVEUR, FORGE]


def rendu(nom="paranoid", destinations=None):
    if destinations is None:
        destinations = BORNEE
    return rules.render_egress(R.get_posture(nom), destinations)


def lignes_de_chaine(texte, nom):
    """Les lignes d'UNE chaîne, accolade ouvrante exclue."""
    dedans = []
    ouvert = False
    for ligne in texte.splitlines():
        if ligne.strip() == f"chain {nom} {{":
            ouvert = True
            continue
        if ouvert:
            if ligne.strip() == "}":
                break
            dedans.append(ligne)
    return dedans


def lignes_du_symbole(texte, symbole):
    """Les règles d'UNE destination, commentaire de tête exclu.

    Mesurer l'ordre sur le fichier entier le mesurerait ENTRE destinations,
    qui suivent l'ordre de l'appelant : ce qui se prouve ici est l'ordre
    interne, celui que le rendu décide.
    """
    dedans = []
    ouvert = False
    for ligne in lignes_de_chaine(texte, "output"):
        nu = ligne.strip()
        if nu.startswith("# "):
            # Une raison se replie sur plusieurs lignes : seule celle qui
            # nomme un symbole connu ouvre un bloc, les suivantes le
            # continuent et ne doivent pas le refermer.
            tete = nu[2:].split(" : ")[0]
            if tete in A.SYMBOLS:
                ouvert = tete == symbole
            continue
        if ouvert:
            dedans.append(nu)
    return dedans


class TestLOrdreEstUnePropriete(unittest.TestCase):
    def test_the_policy_sits_on_the_line_that_declares_the_chain(self):
        """Une règle « drop » posée en dernier laisserait tout sortir
        jusqu'à ce que la ligne soit lue, à chaque rechargement."""
        for nom in ("output", "forward"):
            with self.subTest(chaine=nom):
                premiere = lignes_de_chaine(rendu(), nom)[0]
                self.assertIn("type filter hook", premiere)
                self.assertIn("policy drop;", premiere)

    def test_no_accept_precedes_the_policy(self):
        for nom in ("output", "forward"):
            dedans = lignes_de_chaine(rendu(), nom)
            politique = [
                i for i, l in enumerate(dedans) if "policy drop;" in l
            ]
            acceptes = [
                i for i, l in enumerate(dedans) if l.strip().endswith("accept")
            ]
            with self.subTest(chaine=nom):
                self.assertTrue(acceptes, "aucun accept : rien n'est prouvé")
                self.assertLess(max(politique), min(acceptes))

    def test_the_forward_chain_is_emitted_even_with_nothing_to_allow(self):
        """Absente, le trafic des conteneurs retombe sur le défaut du
        noyau : les règles afficheraient complet pendant qu'un conteneur
        sort par la fenêtre."""
        texte = rendu("local-only", [])
        dedans = lignes_de_chaine(texte, "forward")
        self.assertTrue(dedans)
        self.assertIn("policy drop;", dedans[0])

    def test_established_comes_before_the_destinations(self):
        """Après, la réponse au premier paquet autorisé serait jugée sur la
        liste, et une session ouverte se refermerait."""
        for nom in ("output", "forward"):
            dedans = lignes_de_chaine(rendu(), nom)
            etabli = [i for i, l in enumerate(dedans) if "ct state" in l]
            daddr = [i for i, l in enumerate(dedans) if "daddr" in l]
            with self.subTest(chaine=nom):
                self.assertTrue(etabli and daddr)
                self.assertLess(max(etabli), min(daddr))

    def test_loopback_is_allowed_where_it_means_something(self):
        """Dans « output » elle porte le trafic local ; dans « forward »
        elle n'a rien à décrire, et une ligne de plus se relit comme un
        oubli."""
        self.assertTrue(
            any('oif "lo"' in l for l in lignes_de_chaine(rendu(), "output"))
        )
        self.assertFalse(
            any('oif "lo"' in l for l in lignes_de_chaine(rendu(), "forward"))
        )

    def test_the_table_is_replaced_and_the_others_are_left_alone(self):
        """Purger le jeu de règles entier emporterait les tables des
        autres, et un conteneur perdrait son réseau au rechargement."""
        texte = rendu()
        self.assertIn(f"delete table inet {rules.TABLE}", texte)
        self.assertNotIn("flush ruleset", texte)


class TestCeQueLeFichierPorte(unittest.TestCase):
    def test_each_family_is_rendered_on_its_own_line(self):
        texte = rendu()
        self.assertIn("ip daddr { 198.51.100.0/24 }", texte)
        self.assertIn("ip6 daddr { 2001:db8::/32 }", texte)

    def test_the_families_keep_a_fixed_order_within_a_destination(self):
        """Deux appels identiques doivent écrire le même fichier : un diff
        signalerait autrement un changement qui n'a pas eu lieu.

        L'épreuve porte sur « forge », qui a les deux familles : sur le fichier
        entier, le résolveur en IPv4 précède la forge quel que soit l'ordre
        interne, et l'épreuve passerait sur un rendu inversé."""
        regles = lignes_du_symbole(rendu(), "forge")
        self.assertEqual(2, len(regles), regles)
        self.assertTrue(regles[0].startswith("ip daddr"), regles)
        self.assertTrue(regles[1].startswith("ip6 daddr"), regles)

    def test_every_protocol_of_a_symbol_gets_its_rule(self):
        """Le résolveur répond en UDP et bascule en TCP sur les réponses
        longues : n'ouvrir qu'un des deux casse la résolution au hasard de
        la taille de la réponse."""
        dedans = "\n".join(lignes_de_chaine(rendu(), "output"))
        for protocole in A.SYMBOLS["dns-resolver"].protocols:
            with self.subTest(protocole=protocole):
                self.assertIn(f"{protocole} dport {{ 53 }}", dedans)

    def test_the_reason_travels_with_the_rule(self):
        """Une règle qui ne dit pas pourquoi elle existe est une règle que
        personne n'ose retirer."""
        self.assertIn("Sans résolveur joignable", rendu())

    def test_no_line_is_wider_than_a_terminal(self):
        for ligne in rendu().splitlines():
            self.assertLessEqual(len(ligne), 79, ligne)

    def test_the_same_call_twice_gives_the_same_text(self):
        self.assertEqual(rendu(), rendu())

    def test_the_file_ends_with_a_newline(self):
        self.assertTrue(rendu().endswith("\n"))

    def test_the_posture_is_named_in_the_header(self):
        self.assertIn("paranoid", rendu().splitlines()[1])


class TestLesPortsBornesSansDestination(unittest.TestCase):
    """La troisième forme : borner les PORTS sans nommer de destination.

    Elle ne peut pas passer par la table de symboles, et c'est voulu :
    `allowlist` refuse « 0.0.0.0/0 » parce qu'une liste qui la porte ne
    borne aucune destination tout en s'annonçant bornée. Une posture qui
    borne ses ports n'a donc rien à nommer — le rendu ouvre des ports vers
    n'importe où, et le fichier le DIT au lieu de mimer une liste blanche.
    """

    def texte(self):
        return rules.render_egress(R.get_posture("connected"), ())

    def test_it_wants_rules_now_that_a_shape_exists(self):
        self.assertTrue(rules.wants_rules(R.get_posture("connected")))

    def test_the_policy_falls_on_the_line_that_declares_the_chain(self):
        texte = self.texte()
        self.assertIn("policy drop", texte)
        self.assertIn("ct state established,related accept", texte)
        self.assertIn('oif "lo" accept', texte)

    def test_the_declared_ports_are_the_ones_rendered(self):
        """Ils viennent du REGISTRE : le rendu n'en invente aucun, sinon
        deux endroits décriraient la même posture."""
        texte = self.texte()
        self.assertIn("udp dport { 53, 123 } accept", texte)
        self.assertIn("tcp dport { 22, 80, 443 } accept", texte)

    def test_it_names_no_destination_at_all(self):
        """Une adresse dans ce fichier le ferait lire comme une liste
        blanche, ce que le registre a déjà corrigé une fois."""
        self.assertNotIn("daddr", self.texte())

    def test_the_ports_reach_the_containers_too(self):
        """Même traitement que les destinations d'une liste blanche, qui
        sont émises dans les DEUX chaînes : sans cela un conteneur perd
        tout réseau en silence, là où la machine garde le sien."""
        for chaine in ("output", "forward"):
            with self.subTest(chaine=chaine):
                lignes = lignes_de_chaine(self.texte(), chaine)
                self.assertTrue(
                    [l for l in lignes if "tcp dport" in l], chaine
                )

    def test_the_header_does_not_promise_a_destination_list(self):
        """Le fichier se lit SUR la machine, des mois après. Y annoncer une
        liste qui vit « dans la configuration » enverrait chercher ce que
        cette posture n'a pas."""
        texte = self.texte()
        self.assertNotIn("liste des destinations", texte)
        self.assertIn("ports", texte.split("table inet")[0])

    def test_the_forward_chain_is_emitted_even_so(self):
        """Absente, le trafic relayé retombe sur le défaut du noyau, qui
        accepte : les règles afficheraient complet."""
        self.assertIn("chain forward {", self.texte())

    def test_the_ports_come_from_the_posture_and_not_from_the_renderer(self):
        sur_mesure = R.get_posture("connected")._replace(
            egress_ports=(("tcp", (8443,)),)
        )
        texte = rules.render_egress(sur_mesure, ())
        self.assertIn("tcp dport { 8443 } accept", texte)
        self.assertNotIn("443,", texte)

    def test_bounding_ports_with_none_declared_is_refused(self):
        """Le fichier ne porterait que « policy drop » sous un nom qui
        promet une sortie bornée — donc une coupure déguisée."""
        muette = R.get_posture("connected")._replace(egress_ports=())
        with self.assertRaises(ValidationError):
            rules.render_egress(muette, ())

    def test_a_port_out_of_range_is_refused_by_the_same_gate(self):
        """Le contrôle vit dans `allowlist`, et une seconde validation
        dériverait de la première."""
        fautive = R.get_posture("connected")._replace(
            egress_ports=(("tcp", (70000,)),)
        )
        with self.assertRaises(ValidationError):
            rules.render_egress(fautive, ())

    def test_bounding_neither_ports_nor_destinations_is_still_refused(self):
        ni_lun_ni_lautre = R.get_posture("connected")._replace(
            ports_bounded=False
        )
        self.assertFalse(rules.wants_rules(ni_lun_ni_lautre))
        with self.assertRaises(ValidationError):
            rules.render_egress(ni_lun_ni_lautre, ())


class TestCeQuOnNeRendPas(unittest.TestCase):
    """Refuser plutôt que rendre : un fichier vide se déposerait sur la
    machine et s'y lirait comme une politique."""

    def test_a_posture_that_bounds_nothing_is_refused_by_name(self):
        """Le contrôle des destinations la refuserait aussi. Ce que
        l'épreuve tient est le MESSAGE : « elle ne borne rien, et c'est
        assumé » ferme la question, « ses destinations ne sont pas
        bornées » envoie en chercher une liste qui n'existera jamais."""
        with self.assertRaises(ValidationError) as leve:
            rendu("open", [])
        self.assertIn("assumé", str(leve.exception))

    def test_bounding_ports_only_is_refused_and_said(self):
        """LE mensonge que le registre a déjà tué une fois : une liste qui
        porte la sortie entière se lit comme une liste blanche."""
        with self.assertRaises(ValidationError) as leve:
            rendu("connected", BORNEE)
        self.assertIn("destinations", str(leve.exception))

    def test_a_posture_that_lets_nothing_out_refuses_destinations(self):
        with self.assertRaises(ValidationError):
            rendu("local-only", BORNEE)

    def test_an_allowlist_posture_with_no_destination_is_refused(self):
        """Elle ne joint plus rien, ce qui est une AUTRE posture.

        Le résolveur absent la refuserait aussi : c'est le MESSAGE qui
        sépare « la liste est vide » de « il manque le résolveur », et le
        second enverrait ajouter une ligne à une liste qui n'existe pas."""
        with self.assertRaises(ValidationError) as leve:
            rendu("paranoid", [])
        self.assertIn("attend une liste", str(leve.exception))

    def test_a_named_resolver_missing_from_the_list_is_refused(self):
        """Sans lui, chaque échec se lit comme une panne de réseau plutôt
        que comme un nom qui ne se résout pas."""
        self.assertEqual("resolver", R.get_posture("paranoid").dns)
        with self.assertRaises(ValidationError) as leve:
            rendu("paranoid", [FORGE])
        self.assertIn("résolveur", str(leve.exception))

    def test_no_posture_at_all_is_refused(self):
        with self.assertRaises(ValidationError):
            rules.render_egress(None, BORNEE)

    def test_the_same_symbol_twice_is_refused(self):
        """L'un des deux serait rendu sans que rien ne le dise."""
        with self.assertRaises(ValidationError):
            rendu("paranoid", [RESOLVEUR, FORGE, FORGE])


class TestLeRaccourciEstRefuseAussi(unittest.TestCase):
    """Une destination se fabrique à la main aussi bien qu'elle se demande.

    Le seul endroit qui ÉCRIT est le seul où le refus tient : sans ce
    repassage, la table de symboles ne serait qu'une politesse.
    """

    @staticmethod
    def bricolee(**champs):
        base = dict(
            symbol="forge",
            protocols=("tcp",),
            ports=(443,),
            networks=("198.51.100.0/24",),
            reason="x" * 50,
        )
        base.update(champs)
        return A.Allowed(**base)

    def test_a_hand_built_destination_still_goes_through_the_door(self):
        """Contrôle positif : celle-ci est valide et passe."""
        self.assertIn(
            "198.51.100.0/24",
            rendu("paranoid", [RESOLVEUR, self.bricolee()]),
        )

    def test_a_hostname_never_reaches_the_file(self):
        with self.assertRaises(ValidationError):
            rendu(
                "paranoid", [RESOLVEUR, self.bricolee(networks=("f.example",))]
            )

    def test_the_default_route_never_reaches_the_file(self):
        with self.assertRaises(ValidationError):
            rendu(
                "paranoid", [RESOLVEUR, self.bricolee(networks=("0.0.0.0/0",))]
            )

    def test_a_port_out_of_range_never_reaches_the_file(self):
        with self.assertRaises(ValidationError):
            rendu("paranoid", [RESOLVEUR, self.bricolee(ports=(70000,))])

    def test_a_symbol_outside_the_table_never_reaches_the_file(self):
        with self.assertRaises(ValidationError):
            rendu("paranoid", [RESOLVEUR, self.bricolee(symbol="tout")])

    def test_the_reason_comes_from_the_table_and_not_from_the_caller(self):
        """Une raison fournie par l'appelant écrirait dans le fichier une
        justification que le tableau n'a jamais approuvée."""
        texte = rendu(
            "paranoid", [RESOLVEUR, self.bricolee(reason="parce que")]
        )
        self.assertNotIn("parce que", texte)
        self.assertIn("D'où viennent les sources", texte)


class TestDireEnJetonsCeQuiManque(unittest.TestCase):
    """Un mécanisme muet sur ce qu'il n'applique pas fait croire à un
    confinement qui n'existe pas."""

    def test_a_posture_held_by_its_own_network_expects_nothing(self):
        """« nat » ne promet que la sortie, que la traduction d'adresses
        donne ; un réseau isolé n'a pas de route du tout. Ni l'une ni
        l'autre n'attend un jeu de règles."""
        for nom in ("open", "local-only"):
            with self.subTest(posture=nom):
                self.assertEqual((), rules.unenforced(R.get_posture(nom)))

    def test_bounding_ports_only_names_what_its_rendering_misses(self):
        """Elle rend désormais : ses écarts sont ceux d'un jeu posé, et
        non l'absence de jeu. `no-rendering` porterait un mensonge."""
        self.assertEqual(
            (rules.RELOAD_FAILURE_UNSEEN, rules.CONTAINERS_UNPROVEN),
            rules.unenforced(R.get_posture("connected")),
        )

    def test_bounding_nothing_at_all_still_gets_no_rendering(self):
        nue = R.get_posture("connected")._replace(ports_bounded=False)
        self.assertEqual((rules.NO_RENDERING,), rules.unenforced(nue))

    def test_the_rendered_posture_names_what_is_still_missing(self):
        manques = rules.unenforced(R.get_posture("paranoid"))
        for jeton in (
            rules.RELOAD_FAILURE_UNSEEN,
            rules.CONTAINERS_UNPROVEN,
        ):
            with self.subTest(jeton=jeton):
                self.assertIn(jeton, manques)

    def test_no_posture_at_all_promises_nothing(self):
        self.assertEqual((), rules.unenforced(None))

    def test_every_token_is_in_the_closed_vocabulary(self):
        self.assertTrue(rules.UNENFORCED_TOKENS, "vocabulaire vidé")
        for nom in R.posture_names():
            for jeton in rules.unenforced(R.get_posture(nom)):
                with self.subTest(posture=nom, jeton=jeton):
                    self.assertIn(jeton, rules.UNENFORCED_TOKENS)

    def test_the_wording_of_the_tokens_is_pinned(self):
        """Écrits en toutes lettres, et non par leur constante : un écran
        les affichera et un rapport les comparera, si bien qu'un jeton
        renommé casse un consommateur sans qu'aucune constante bouge."""
        self.assertEqual(
            (
                "no-rendering",
                "reload-failure-unseen",
                "containers-unproven",
                "boot-window-open",
            ),
            rules.UNENFORCED_TOKENS,
        )


class TestLeJetonCommandeLaBascule(unittest.TestCase):
    """L'équivalence qui rend la bascule mécanique au lieu d'optimiste.

    Tant qu'un jeton reste, elle REFUSE de voir `egress_enforced` passer à
    vrai. Le jour où il n'en reste aucun, elle l'EXIGE. C'est le même geste
    que la règle des données réelles : déduire au lieu de déclarer, pour
    qu'aucun champ ne puisse annoncer un confinement que rien ne tient.
    """

    def test_the_flag_and_the_tokens_say_the_same_thing(self):
        for nom in R.posture_names():
            posture = R.get_posture(nom)
            with self.subTest(posture=nom):
                self.assertEqual(
                    posture.egress_enforced,
                    rules.unenforced(posture) == (),
                    f"« {nom} » : {rules.unenforced(posture)}",
                )

    def test_both_sides_of_the_equivalence_are_exercised(self):
        """Contrôle positif : si toutes les postures tombaient du même
        côté, l'équivalence tiendrait sans rien prouver."""
        reponses = {
            rules.unenforced(R.get_posture(nom)) == ()
            for nom in R.posture_names()
        }
        self.assertEqual({True, False}, reponses)

    def test_the_strict_posture_is_still_refused_and_the_tokens_say_why(self):
        """Le compteur du travail, vu du mécanisme : le jour où ces jetons
        disparaissent, la posture stricte accepte les données réelles, et
        cette épreuve tombe avec eux.

        Le nombre est écrit en toutes lettres pour qu'il faille le CHANGER :
        un compteur qui suit tout seul ne compte rien."""
        stricte = R.get_posture("paranoid")
        self.assertFalse(R.allows_real_data(stricte))
        self.assertEqual(2, len(rules.unenforced(stricte)))


class TestElleNAppliqueRien(unittest.TestCase):
    def test_the_module_runs_nothing(self):
        """Un rendu qui exécute ne se relit plus avant d'être posé, et ne
        s'éprouve plus sans la machine qu'il configure."""
        import ast

        chemin = os.path.join(RACINE, "script", "posture", "rules.py")
        with open(chemin, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        importes = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                importes.update(a.name for a in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                importes.add(noeud.module)
        self.assertTrue(importes, "aucun import lu : rien n'est prouvé")
        for interdit in ("subprocess", "os", "shutil"):
            self.assertNotIn(interdit, importes)


class TestQuellePostureVeutDesRegles(unittest.TestCase):
    """TROIS RAISONS D'EN VOULOIR, et une seule était consultée.

    Une liste bornée en donne une : il y a des adresses à nommer. Une
    sortie COUPÉE en donne une autre, et le rendu la sert depuis toujours —
    « policy drop », la boucle locale, les connexions établies. Des PORTS
    bornés en donnent une troisième : il y a une politique à poser, même
    sans une seule adresse à écrire.

    LE DÉFAUT QUE CE PRÉDICAT FERME : le chemin de déploiement demandait
    « as-tu une liste bornée à résoudre ». « local-only » n'en a pas — elle
    ne joint rien, il n'y a rien à nommer — donc il ne posait AUCUNE règle,
    et la posture qui promet que rien ne sort se déployait avec la sortie
    entière. Rien ne le disait.
    """

    def test_a_cut_egress_wants_rules_even_with_nothing_to_name(self):
        self.assertTrue(rules.wants_rules(R.get_posture("local-only")))

    def test_a_bounded_allowlist_wants_them_too(self):
        self.assertTrue(rules.wants_rules(R.get_posture("paranoid")))

    def test_an_assumed_open_egress_does_not(self):
        """Lui rendre un jeu donnerait l'apparence d'un confinement que le
        nom de la posture dément."""
        self.assertFalse(rules.wants_rules(R.get_posture("open")))

    def test_bounded_ports_want_them_without_a_single_address(self):
        """Ce qui les refusait était l'absence de FORME, pas l'absence de
        politique : sans troisième rendu, un fichier n'aurait pu que mimer
        une liste blanche portant la sortie entière."""
        self.assertTrue(rules.wants_rules(R.get_posture("connected")))

    def test_bounding_neither_one_nor_the_other_does_not(self):
        nue = R.get_posture("connected")._replace(ports_bounded=False)
        self.assertFalse(rules.wants_rules(nue))

    def test_no_posture_wants_nothing(self):
        self.assertFalse(rules.wants_rules(None))

    def test_every_posture_gets_an_answer(self):
        self.assertTrue(
            R.posture_names(), "aucune posture : rien n'est prouvé"
        )
        for nom in R.posture_names():
            with self.subTest(posture=nom):
                self.assertIsInstance(
                    rules.wants_rules(R.get_posture(nom)), bool
                )

    def test_a_fifth_posture_that_contradicts_itself_is_refused(self):
        """LE GARDE QUI PARAÎT REDONDANT. Aucune des quatre postures n'est
        à la fois « nat » et bornée, donc le retirer ne change rien
        aujourd'hui. Mais une cinquième qui le serait promettrait un
        fichier que le rendu REFUSE — « nat » est son premier refus — et le
        déploiement échouerait sur la machine, pas devant l'écran.

        La posture est INVENTÉE : elle n'existe nulle part dans le dépôt, et
        c'est le seul moyen d'exercer un garde que les quatre vraies ne
        peuvent pas atteindre.
        """
        contradictoire = R.get_posture("open")._replace(
            name="nat-et-bornee-inventee", destinations_bounded=True
        )
        self.assertEqual("nat", contradictoire.egress)
        self.assertFalse(rules.wants_rules(contradictoire))
        # L'accord : ce que le prédicat refuse, le rendu le refuse aussi.
        with self.assertRaises(ValidationError):
            rules.render_egress(contradictoire, ())

    def test_it_is_not_the_same_question_as_having_a_bounded_list(self):
        """LES DEUX NE COÏNCIDENT PAS, et c'est tout le sujet : les
        confondre est ce qui laissait « local-only » sans règles.

        Elles s'écartent désormais sur deux postures et pour des raisons
        opposées : « local-only » veut des règles sans avoir d'adresses à
        résoudre, « connected » veut des règles en n'ayant que des ports.
        La seconde question — « y a-t-il des adresses à résoudre » — est
        fausse sur les deux."""
        from script.posture import destinations as D

        differentes = [
            nom
            for nom in R.posture_names()
            if rules.wants_rules(R.get_posture(nom))
            != D.has_bounded_list(R.get_posture(nom))
        ]
        self.assertEqual(["connected", "local-only"], differentes)


class TestLAccordEntreLeVouloirEtLeRefus(unittest.TestCase):
    """`wants_rules` est faux EXACTEMENT là où le rendu refuse toujours.

    C'est l'invariant qui empêche les deux de dériver : un refus ajouté
    dans `_refuse_la_posture` sans toucher au prédicat rendrait une posture
    « voulante » dont le rendu échoue au déploiement — sur la machine, et
    non devant l'écran.
    """

    # Des listes de destinations à essayer. Celle qui est vide sert la
    # sortie coupée ; l'autre sert la liste blanche.
    @staticmethod
    def _listes():
        return ((), (A.resolve("dns-resolver", "192.0.2.53"),))

    def test_what_does_not_want_rules_never_renders(self):
        for nom in R.posture_names():
            posture = R.get_posture(nom)
            if rules.wants_rules(posture):
                continue
            for cibles in self._listes():
                with self.subTest(posture=nom, cibles=len(cibles)):
                    with self.assertRaises(ValidationError):
                        rules.render_egress(posture, cibles)

    def test_what_wants_rules_renders_for_at_least_one_list(self):
        """Sinon le prédicat promettrait un fichier que le rendu refuse, et
        le déploiement échouerait sur la machine."""
        voulantes = [
            nom
            for nom in R.posture_names()
            if rules.wants_rules(R.get_posture(nom))
        ]
        self.assertTrue(
            voulantes, "aucune posture voulante : rien n'est prouvé"
        )
        for nom in voulantes:
            posture = R.get_posture(nom)
            rendus = []
            for cibles in self._listes():
                try:
                    rendus.append(rules.render_egress(posture, cibles))
                except ValidationError:
                    continue
            with self.subTest(posture=nom):
                self.assertTrue(rendus, nom)

    def test_the_cut_egress_rendering_drops_by_default(self):
        """Ce que valent ces 548 octets : sans « policy drop », le fichier
        se déposerait et ne couperait rien."""
        texte = rules.render_egress(R.get_posture("local-only"), ())
        self.assertIn("policy drop", texte)
        self.assertIn('oif "lo" accept', texte)
        self.assertIn("ct state established,related accept", texte)

    def test_the_cut_egress_rendering_names_no_destination(self):
        """Une adresse nommée dans un fichier qui coupe tout dirait le
        contraire de ce qu'il fait."""
        texte = rules.render_egress(R.get_posture("local-only"), ())
        self.assertNotIn("192.0.2", texte)
        self.assertNotIn("dport", texte)


class TestLaFenetreDuPremierDemarrage(unittest.TestCase):
    """Elle appartient au CHEMIN de livraison, pas à la posture.

    Là où l'amorce écrit les règles avant le premier boot, il n'y a pas de
    fenêtre. Là où elles arrivent par un canal qui exige que la machine
    RÉPONDE déjà — donc après son démarrage — la machine sort librement
    pendant plusieurs minutes.

    Le drapeau `egress_enforced` ne peut pas en tenir compte : il est
    per-posture, et deux chemins livrent la même. D'où un paramètre, et un
    défaut qui laisse l'équivalence existante intacte.
    """

    def test_the_default_path_opens_no_window(self):
        """L'équivalence avec `egress_enforced` porte sur ce chemin-là :
        la changer par défaut casserait le contrat du drapeau."""
        for nom in R.posture_names():
            with self.subTest(posture=nom):
                self.assertNotIn(
                    rules.BOOT_WINDOW_OPEN,
                    rules.unenforced(R.get_posture(nom)),
                )

    def test_a_late_path_opens_one_where_rules_are_posed(self):
        for nom in ("paranoid", "local-only"):
            with self.subTest(posture=nom):
                self.assertIn(
                    rules.BOOT_WINDOW_OPEN,
                    rules.unenforced(R.get_posture(nom), after_boot=True),
                )

    def test_free_egress_has_no_window_to_open(self):
        """Rien n'est à poser, donc rien n'arrive en retard."""
        self.assertEqual(
            (), rules.unenforced(R.get_posture("open"), after_boot=True)
        )

    def test_a_posture_nothing_renders_gains_no_window_either(self):
        """Une fenêtre ne s'ouvre pas sur des règles qu'on ne pose JAMAIS :
        l'y ajouter ferait croire à un confinement tardif là où il n'y en a
        aucun.

        Aucune posture du registre n'est dans ce cas — celle qui y était
        borne désormais ses ports et rend. Le cas se fabrique donc, et il
        reste à tenir : le prédicat le décide, pas la table."""
        nue = R.get_posture("connected")._replace(ports_bounded=False)
        self.assertEqual(
            (rules.NO_RENDERING,), rules.unenforced(nue, after_boot=True)
        )

    def test_the_late_path_never_loses_a_token_of_the_early_one(self):
        """Le chemin tardif AJOUTE une faiblesse, il n'en retire aucune."""
        for nom in R.posture_names():
            with self.subTest(posture=nom):
                posture = R.get_posture(nom)
                tot = set(rules.unenforced(posture))
                tard = set(rules.unenforced(posture, after_boot=True))
                self.assertTrue(tot <= tard, (tot, tard))

    def test_no_posture_is_absent_from_the_answer(self):
        self.assertEqual((), rules.unenforced(None, after_boot=True))

    def test_every_token_it_can_return_is_in_the_vocabulary(self):
        for nom in R.posture_names():
            for tardif in (False, True):
                jetons = rules.unenforced(R.get_posture(nom), tardif)
                with self.subTest(posture=nom, tardif=tardif):
                    for jeton in jetons:
                        self.assertIn(jeton, rules.UNENFORCED_TOKENS)


if __name__ == "__main__":
    unittest.main()
