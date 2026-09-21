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

    def test_bounding_ports_only_gets_the_single_token_that_fits(self):
        """Les autres jetons porteraient sur un rendu qui n'existe pas."""
        self.assertEqual(
            (rules.NO_RENDERING,),
            rules.unenforced(R.get_posture("connected")),
        )

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


if __name__ == "__main__":
    unittest.main()
