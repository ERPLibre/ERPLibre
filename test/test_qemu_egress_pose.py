#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Poser un fichier de règles sans rien changer pour ceux qui n'en veulent pas.

Le déploiement sert tous les jours et ne rend rien de nouveau ici : sans le
drapeau, la configuration produite doit être celle d'avant, à l'octet. C'est
l'assertion qui compte le plus de ce fichier — une option qui déborde sur le
cas courant coûte plus qu'elle n'apporte.

DEUX VOIES D'AMORCE, UNE SEULE SOURCE. La liste des fichiers d'accueil est
lue par cloud-init, par le late_command de l'installateur et par le
rangement dans l'initrd : une entrée de plus les couvre toutes les trois,
et c'est pourquoi elle passe par là plutôt que par un mécanisme neuf.

LES CONSTANTES SONT RECOPIÉES, DONC ÉPINGLÉES. Le script de déploiement se
charge seul, sans le dépôt sur le chemin d'import, et n'importe que la
bibliothèque standard : il ne PEUT pas importer le module qui rend les
règles. L'épreuve tient les deux valeurs égales à leur source, ce qui
remplace l'import impossible.
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(str(RACINE))

from script.lib_valid import ValidationError  # noqa: E402
from script.posture import plan  # noqa: E402


def _deploy_qemu():
    """deploy_qemu.py chargé comme module, comme le fait todo.py."""
    chemin = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules["deploy_qemu"] = module
    spec.loader.exec_module(module)
    return module


DQ = _deploy_qemu()

REGLES = "table inet erplibre {\n}\n"


def args_de_banc(regles=None, unite=None):
    args = DQ.build_parser().parse_args(["--name", "banc"])
    args.hostname = "banc"
    if regles is not None:
        args.egress_rules = regles
    if unite is not None:
        args.egress_unit_text = unite
    return args


class TestSansLeDrapeauRienNeBouge(unittest.TestCase):
    def test_the_cloud_config_says_nothing_about_rules(self):
        texte = DQ.build_cloud_config(args_de_banc(), None, [])
        for trace in ("egress", "nft -f", DQ.EGRESS_GUEST_PATH):
            with self.subTest(trace=trace):
                self.assertNotIn(trace, texte)

    def test_the_installer_path_says_nothing_either(self):
        texte = DQ.build_preseed(args_de_banc(), None, [])
        self.assertNotIn("egress", texte)

    def test_the_welcome_files_are_the_ones_that_were_there(self):
        chemins = [entree[0] for entree in DQ.guide_files(args_de_banc())]
        self.assertNotIn(DQ.EGRESS_GUEST_PATH, chemins)
        self.assertIn("/etc/motd", chemins)

    def test_an_empty_rendering_is_the_same_as_none(self):
        """Un déploiement sans posture bornée rend une chaîne vide : elle ne
        doit pas produire une entrée qui ne contiendrait rien."""
        texte = DQ.build_cloud_config(args_de_banc(""), None, [])
        self.assertNotIn("egress", texte)


class TestAvecLeDrapeau(unittest.TestCase):
    def config(self):
        return DQ.build_cloud_config(args_de_banc(REGLES), None, [])

    def test_the_file_is_written_with_a_quoted_mode(self):
        """« permissions: 600 » non quoté est lu en DÉCIMAL et appliqué tel
        quel, sans le moindre avertissement."""
        texte = self.config()
        self.assertIn(f"  - path: {DQ.EGRESS_GUEST_PATH}", texte)
        self.assertIn(f"    permissions: '{DQ.EGRESS_GUEST_MODE}'", texte)

    def test_the_write_is_not_deferred(self):
        """Un propriétaire imposerait « defer: true », donc une pose à
        l'étape finale — trop tard pour un fichier chargé au démarrage."""
        entree = [
            e
            for e in DQ.guide_files(args_de_banc(REGLES))
            if e[0] == DQ.EGRESS_GUEST_PATH
        ][0]
        self.assertEqual("", entree[3])

    def test_the_content_travels_whole(self):
        self.assertIn("table inet erplibre", self.config())

    def test_the_load_line_is_the_very_last(self):
        """Le code de sortie d'un script est celui de sa dernière commande :
        ailleurs dans la liste, la panne se perdrait dans les « || true »
        qui suivent."""
        lignes = self.config().rstrip("\n").splitlines()
        self.assertEqual(f"  - nft -f {DQ.EGRESS_GUEST_PATH}", lignes[-1])

    def test_the_load_line_tolerates_no_failure(self):
        """C'est la SEULE ligne de runcmd sans repli, et c'est le point :
        un confinement qui ne se charge pas doit se voir."""
        derniere = self.config().rstrip("\n").splitlines()[-1]
        self.assertNotIn("|| true", derniere)
        avec_repli = [
            l
            for l in self.config().splitlines()
            if l.startswith("  - ") and l.endswith("|| true")
        ]
        self.assertTrue(avec_repli, "aucune ligne à repli : rien n'est prouvé")

    def test_the_installer_path_copies_it_too(self):
        texte = DQ.build_preseed(args_de_banc(REGLES), None, [])
        plat = DQ.installer_guide_name(DQ.EGRESS_GUEST_PATH)
        self.assertIn(f"cp /{plat} /target{DQ.EGRESS_GUEST_PATH}", texte)
        self.assertIn(f"chmod {DQ.EGRESS_GUEST_MODE}", texte)

    def test_the_name_kept_in_the_initrd_is_flat(self):
        """Le cpio est déplié séquentiellement et ne crée pas les parents
        manquants : une barre oblique ferait échouer le dépliage ENTIER,
        donc l'installation."""
        plat = DQ.installer_guide_name(DQ.EGRESS_GUEST_PATH)
        self.assertNotIn("/", plat)


class TestLUnitePoseeEtArmee(unittest.TestCase):
    """Les règles disent CE QUI passe, l'unité dit QUAND elles sont
    chargées. Sans elle, la voie de l'installateur posait le fichier et
    rien ne le chargeait jamais."""

    def config(self):
        return DQ.build_cloud_config(
            args_de_banc(REGLES, plan.unit_text()), None, []
        )

    def test_the_unit_is_written_where_systemd_reads_it(self):
        texte = self.config()
        self.assertIn(f"  - path: {DQ.EGRESS_UNIT_PATH}", texte)
        self.assertIn(f"    permissions: '{DQ.EGRESS_UNIT_MODE}'", texte)

    def test_the_first_boot_arms_it_before_loading(self):
        derniere = self.config().rstrip("\n").splitlines()[-1]
        self.assertLess(
            derniere.index(DQ.EGRESS_UNIT_NAME),
            derniere.index("nft -f"),
        )
        self.assertNotIn("|| true", derniere)

    def test_the_installer_path_arms_it_because_it_has_no_runcmd(self):
        """C'est LA raison de l'unité sur ce chemin : rien d'autre n'y
        charge les règles, ni au premier démarrage ni aux suivants."""
        texte = DQ.build_preseed(
            args_de_banc(REGLES, plan.unit_text()), None, []
        )
        self.assertIn(
            f"in-target systemctl enable {DQ.EGRESS_UNIT_NAME}", texte
        )
        plat = DQ.installer_guide_name(DQ.EGRESS_UNIT_PATH)
        self.assertIn(f"cp /{plat} /target{DQ.EGRESS_UNIT_PATH}", texte)

    def test_the_unit_name_kept_in_the_initrd_is_flat(self):
        """Une barre oblique ferait échouer le dépliage de l'initrd
        ENTIER, donc l'installation."""
        self.assertNotIn("/", DQ.installer_guide_name(DQ.EGRESS_UNIT_PATH))

    def test_rules_without_a_unit_keep_the_line_they_had(self):
        """Les deux drapeaux restent indépendants : un déploiement qui
        n'envoie que les règles doit se comporter comme avant."""
        derniere = (
            DQ.build_cloud_config(args_de_banc(REGLES), None, [])
            .rstrip("\n")
            .splitlines()[-1]
        )
        self.assertEqual(f"  - nft -f {DQ.EGRESS_GUEST_PATH}", derniere)

    def test_no_rules_means_no_unit_either(self):
        """Poser une unité qui chargerait un fichier absent la ferait
        échouer à chaque démarrage, sur une machine qui n'a rien demandé."""
        texte = DQ.build_cloud_config(args_de_banc(), None, [])
        self.assertNotIn(DQ.EGRESS_UNIT_NAME, texte)


class TestLeModeDEmploiDitLeTrou(unittest.TestCase):
    """Ce moteur s'enseigne en appels directs, et il ne confine rien seul.

    Il pose ce qu'on lui DONNE — son aide le dit — donc un appel direct
    sans règles crée une machine à sortie libre, quelle que soit
    l'intention. Le taire est ce qui ferait croire qu'une VM faite « à la
    main » vaut celle du menu, alors que la règle d'or est tenue au point
    de passage unique de CELUI-CI.

    Le contrôle porte sur la source bilingue, et les drapeaux qu'elle
    enseigne doivent EXISTER : un mode d'emploi qui nomme une option
    absente envoie taper une commande qui refuse.
    """

    @staticmethod
    def source():
        chemin = os.path.join(RACINE, "script", "qemu", "README.base.md")
        with open(chemin, encoding="utf-8") as fichier:
            return fichier.read()

    @classmethod
    def blocs(cls, marque):
        """Tout ce qui vit sous une marque, recollé.

        Ce fichier ALTERNE les marques une dizaine de fois, là où les
        autres n'en ont qu'une de chaque : couper au premier séparateur ne
        rendrait que le premier paragraphe, et le contrôle passerait au
        vert sur une section absente.
        """
        morceaux, courante = [], None
        for ligne in cls.source().splitlines():
            nue = ligne.strip()
            if nue.startswith("<!-- [") and nue.endswith("] -->"):
                courante = nue[6:-5]
                continue
            if courante == marque:
                morceaux.append(ligne)
        return "\n".join(morceaux)

    def test_each_language_says_it_confines_nothing_alone(self):
        """La phrase, dans CHAQUE langue : la retirer d'une moitié
        laisserait l'autre complète, et un lecteur sur deux ne saurait pas
        qu'il vient de créer une machine à sortie libre."""
        self.assertIn("free egress", self.blocs("en"))
        self.assertIn("sortie libre", self.blocs("fr"))

    def test_the_example_that_confines_it_is_in_the_common_block(self):
        """Une commande ne se traduit pas : la poser dans une moitié la
        ferait disparaître de l'autre au prochain rendu."""
        commun = self.blocs("common")
        for drapeau in ("--egress-file", "--egress-unit"):
            with self.subTest(drapeau=drapeau):
                self.assertIn(drapeau, commun)

    def test_the_flags_it_teaches_exist_in_the_engine(self):
        """Nommer une option absente envoie taper une commande refusée."""
        source = open(
            os.path.join(RACINE, "script", "qemu", "deploy_qemu.py"),
            encoding="utf-8",
        ).read()
        for drapeau in ("--egress-file", "--egress-unit"):
            with self.subTest(drapeau=drapeau):
                self.assertIn(f'"{drapeau}"', source)

    def test_the_posture_it_renders_in_the_example_exists(self):
        """Un exemple qui nomme une posture retirée ne tourne pas."""
        from script.posture import registry

        texte = self.source()
        nommees = [
            nom
            for nom in registry.posture_names()
            if f"get_posture('{nom}')" in texte
        ]
        self.assertTrue(nommees, "l'exemple ne rend aucune posture connue")


class TestLesConstantesRecopieesSontEpinglees(unittest.TestCase):
    """L'import est impossible ; l'égalité, elle, se vérifie."""

    def test_the_guest_path_is_the_one_the_renderer_names(self):
        self.assertEqual(plan.RULES_PATH, DQ.EGRESS_GUEST_PATH)

    def test_the_mode_is_the_one_the_renderer_names(self):
        self.assertEqual(plan.RULES_MODE, DQ.EGRESS_GUEST_MODE)

    def test_the_unit_path_is_the_one_the_renderer_names(self):
        self.assertEqual(plan.UNIT_PATH, DQ.EGRESS_UNIT_PATH)
        self.assertEqual(plan.UNIT_NAME, DQ.EGRESS_UNIT_NAME)
        self.assertEqual(plan.UNIT_MODE, DQ.EGRESS_UNIT_MODE)

    def test_the_rules_entry_is_the_one_the_renderer_composes(self):
        """Le TUPLE entier, et non ses seules constantes. Les trois
        premières sont épinglées ci-dessus ; ce qui ne l'était pas est leur
        ASSEMBLAGE, et une entrée mal composée pose un fichier au bon
        chemin avec le mauvais mode, ou sous le mauvais propriétaire."""
        entrees = DQ.guide_files(args_de_banc(REGLES, plan.unit_text()))
        self.assertIn(plan.file_entry(REGLES), entrees)

    def test_the_unit_entry_is_the_one_the_renderer_composes(self):
        entrees = DQ.guide_files(args_de_banc(REGLES, plan.unit_text()))
        self.assertIn(plan.unit_entry(), entrees)

    def test_rules_that_are_only_blank_are_posed_by_neither(self):
        """Le composeur REFUSE un contenu vide — « un fichier vide se
        chargerait sans rien appliquer, et la machine se lirait comme
        confinée ». Le chemin recopié teste la vérité de la chaîne, ce qui
        laisse passer des espaces. Les deux doivent refuser, sans quoi
        l'épinglage ne tient que sur le cas facile."""
        with self.assertRaises(ValidationError):
            plan.file_entry("   \n  ")
        entrees = DQ.guide_files(args_de_banc("   \n  ", plan.unit_text()))
        self.assertEqual(
            [], [e for e in entrees if e[0] == DQ.EGRESS_GUEST_PATH]
        )

    def test_a_unit_that_is_only_blank_is_not_posed_either(self):
        """La symétrique de la précédente. Une unité vide s'installerait et
        échouerait à chaque démarrage, sur une machine qui n'a rien
        demandé — le fichier de règles et l'unité vont par paire."""
        entrees = DQ.guide_files(args_de_banc(REGLES, "  \n "))
        self.assertEqual(
            [], [e for e in entrees if e[0] == DQ.EGRESS_UNIT_PATH]
        )

    def test_the_first_boot_line_is_the_one_the_renderer_names(self):
        lignes = (
            DQ.build_cloud_config(
                args_de_banc(REGLES, plan.unit_text()), None, []
            )
            .rstrip("\n")
            .splitlines()
        )
        self.assertEqual(f"  - {plan.first_boot_command()}", lignes[-1])

    def test_the_load_line_is_the_one_the_renderer_names(self):
        lignes = (
            DQ.build_cloud_config(args_de_banc(REGLES), None, [])
            .rstrip("\n")
            .splitlines()
        )
        self.assertEqual(f"  - {plan.load_command()}", lignes[-1])

    def test_the_script_still_imports_nothing_from_the_repository(self):
        """Il se charge seul, sans le dépôt sur le chemin d'import : un
        « from script.… » le casserait quand il est lancé en direct, et
        seulement là — donc jamais sous le menu, qui est où on l'essaie."""
        import ast

        chemin = RACINE / "script/qemu/deploy_qemu.py"
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        noms = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                noms.update(alias.name for alias in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                noms.add(noeud.module)
        self.assertTrue(noms, "aucun import lu : rien n'est prouvé")
        du_depot = [nom for nom in noms if nom.split(".")[0] == "script"]
        self.assertEqual([], du_depot)


class TestLeModeDEmploiNeRecopiePasLeCatalogue(unittest.TestCase):
    """Une page qui recopie un catalogue vieillit, et sans un mot.

    Deux recopies ont dérivé ici : « --distro : ubuntu, debian ou fedora »
    quand le catalogue en sert huit, et des minimums de disque figés
    (Debian 10G, Fedora 15G) quand toutes les entrées disent 20G. Aucune
    des deux ne s'annonce fausse à la lecture.

    La garde n'interdit pas de citer un exemple : elle refuse une LISTE
    FERMÉE de distributions et des chiffres de dimensionnement, qui sont
    exactement ce que `--list-images` rend et que la page n'a pas à
    doubler.
    """

    @staticmethod
    def source():
        chemin = os.path.join(RACINE, "script", "qemu", "README.base.md")
        with open(chemin, encoding="utf-8") as fichier:
            return fichier.read()

    @classmethod
    def ligne_distro(cls):
        for ligne in cls.source().splitlines():
            if ligne.strip().startswith("- `--distro`"):
                yield ligne

    def test_the_distro_option_names_no_closed_list(self):
        """Nommer trois distributions sur huit se lit comme le catalogue
        entier ; le lecteur n'a aucun moyen de savoir qu'il en manque."""
        DQ = _deploy_qemu()
        for ligne in self.ligne_distro():
            cites = {d for d in DQ.DISTROS if f"`{d}`" in ligne}
            with self.subTest(ligne=ligne.strip()[:60]):
                self.assertLessEqual(
                    len(cites),
                    1,
                    f"la page fige {sorted(cites)} sur"
                    f" {len(DQ.DISTROS)} du catalogue",
                )

    def test_the_page_repeats_no_sizing_figure_of_the_catalogue(self):
        """Les minimums vivent dans le catalogue et changent avec lui.

        Le contrôle porte sur les DEUX langues : un chiffre corrigé d'un
        seul côté laisse l'autre mentir, et une page complète se lit
        comme une page.
        """
        DQ = _deploy_qemu()
        disques = set()
        for versions, _defaut in DQ.DISTROS.values():
            for spec in versions.values():
                disques.add(str(spec[3]))
        anglais, _s, francais = self.source().partition("<!-- [fr] -->")
        for moitie, langue in ((anglais, "en"), (francais, "fr")):
            for ligne in moitie.splitlines():
                if not ligne.strip().startswith("- `--memory`"):
                    continue
                bloc = moitie[moitie.index(ligne) :].split("\n- ")[0]
                for taille in disques:
                    with self.subTest(langue=langue, taille=taille):
                        self.assertNotIn(f"/{taille}", bloc)


class TestLireLeFichierRendu(unittest.TestCase):
    def test_nothing_asked_reads_nothing(self):
        self.assertEqual("", DQ.load_posed_file("", "Règles"))

    def test_a_missing_file_stops_before_anything_is_created(self):
        with self.assertRaises(SystemExit):
            DQ.load_posed_file("/nexiste-pas.invalid/regles.nft", "Règles")

    def test_an_empty_file_is_refused_like_a_missing_one(self):
        """Chargé, il s'accepterait sans rien appliquer, et la machine se
        lirait comme confinée alors que rien ne la borne."""
        with tempfile.NamedTemporaryFile("w", suffix=".nft") as fichier:
            fichier.write("   \n")
            fichier.flush()
            with self.assertRaises(SystemExit):
                DQ.load_posed_file(fichier.name, "Règles")

    def test_a_real_file_comes_back_whole(self):
        with tempfile.NamedTemporaryFile("w", suffix=".nft") as fichier:
            fichier.write(REGLES)
            fichier.flush()
            self.assertEqual(
                REGLES, DQ.load_posed_file(fichier.name, "Règles")
            )


class TestLAnalyseurVientAvecLesRegles(unittest.TestCase):
    """La voie de l'installateur POSE des règles sur un système qui ne
    portait pas de quoi les charger.

    Les images cloud des autres distributions apportent nftables d'origine.
    Le preseed, lui, installe ce qu'il ÉNUMÈRE, et l'analyseur n'y était
    pas : l'unité échoue alors à chaque amorçage, la machine revient DEBOUT
    et sort librement en portant un fichier de règles — l'apparence exacte
    du contraire.

    Son armement est en « || true » sur ce chemin, donc rien ne s'arrête ;
    et la relecture d'après déploiement, seule à le voir, n'a lieu qu'une
    fois.
    """

    def paquets(self, texte):
        """Les paquets que le preseed demande à installer."""
        for ligne in texte.splitlines():
            if "pkgsel/include" in ligne:
                return ligne.split("string", 1)[1].split()
        return []

    def test_the_installer_path_brings_the_loader(self):
        texte = DQ.build_preseed(
            args_de_banc(
                REGLES,
                (
                    DQ.EGRESS_UNIT_TEXT
                    if hasattr(DQ, "EGRESS_UNIT_TEXT")
                    else plan.unit_text()
                ),
            ),
            None,
            [],
        )
        self.assertIn("nftables", self.paquets(texte))

    def test_it_brings_it_even_with_no_posture_asked(self):
        """Le preseed est écrit une fois pour l'image ; une VM dont on
        resserre la posture plus tard trouverait sinon un système sans de
        quoi la tenir."""
        self.assertIn(
            "nftables",
            self.paquets(DQ.build_preseed(args_de_banc(), None, [])),
        )

    def test_the_other_packages_are_still_there(self):
        """Contrôle : réécrire la ligne ne doit rien perdre."""
        paquets = self.paquets(DQ.build_preseed(args_de_banc(), None, []))
        for attendu in (
            "openssh-server",
            "sudo",
            "python3",
            "qemu-guest-agent",
            "ca-certificates",
        ):
            self.assertIn(attendu, paquets)

    def test_the_loader_the_unit_calls_is_the_one_installed(self):
        """DÉRIVÉ : l'unité nomme le binaire qu'elle lance, et le preseed
        nomme le paquet. Les deux sont écrits à des endroits différents, et
        un renommage de l'un sans l'autre rendrait l'installation inutile
        sans qu'un mot le dise."""
        binaire = ""
        for ligne in plan.unit_text().splitlines():
            if ligne.startswith("ExecStart="):
                # « … -c 'exec nft -f … ' » : le mot qui suit « exec ».
                morceaux = ligne.split("exec ", 1)[1].split()
                binaire = morceaux[0]
        self.assertTrue(binaire, "l'unité ne nomme aucun analyseur")
        paquets = self.paquets(DQ.build_preseed(args_de_banc(), None, []))
        # Le paquet Debian de « nft » est « nftables ».
        self.assertTrue(
            any(binaire in p for p in paquets),
            f"l'unité lance « {binaire} » et le preseed n'installe rien"
            f" qui le porte : {paquets}",
        )


if __name__ == "__main__":
    unittest.main()
