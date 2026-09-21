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
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "script", "analyse")
)

import check_comment_hygiene as hygiene  # noqa: E402
import lib_identifiant as identifiant  # noqa: E402

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


class TestLeGo(unittest.TestCase):
    """Go est entré dans le dépôt, et l'outil ne le lisait pas.

    Sondé avec des motifs interdits, il restait muet sur un « .go » et sortait
    0 : les commentaires du cache de téléchargement n'ont donc jamais été
    relus par personne d'autre que leur auteur.
    """

    def texte(self, source):
        """Le texte recollé de tous les blocs. Un bloc est un dict :
        « line », « text », « lines », « offsets »."""
        return " ".join(b["text"] for b in hygiene.blocs_go(source))

    def test_un_commentaire_de_ligne(self):
        trouve = hygiene.inspect("x.go", "// Vécu : la panne\npackage main\n")
        self.assertTrue(trouve, "un commentaire Go n'est pas inspecté")

    def test_une_url_en_chaine_nouvre_rien(self):
        """« https:// » porte deux barres obliques : c'est LE piège du Go."""
        source = 'package main\n\nconst a = "https://vecu.example/hier"\n'
        self.assertEqual(hygiene.blocs_go(source), [])

    def test_une_chaine_brute_nouvre_rien(self):
        """L'accent grave délimite une chaîne où rien ne s'échappe."""
        source = (
            "package main\n\nconst a = `https://mesure.example/nous avons`\n"
        )
        self.assertEqual(hygiene.blocs_go(source), [])

    def test_un_commentaire_apres_une_chaine(self):
        source = (
            'package main\n\nconst a = "https://x.example" // Vécu : ici\n'
        )
        trouve = hygiene.recits(self.texte(source))
        self.assertTrue(trouve, "le commentaire qui suit une URL est perdu")

    def test_un_bloc_sur_plusieurs_lignes(self):
        source = (
            "package main\n\n/*\nVécu : la semaine où\nnous avons vu.\n*/\n"
        )
        self.assertTrue(
            hygiene.blocs_go(source), "un commentaire /* */ n'est pas lu"
        )
        texte = self.texte(source)
        self.assertIn("Vécu", texte)
        self.assertIn("nous avons", texte)

    def test_un_bloc_sur_une_seule_ligne(self):
        source = "package main\n\nvar x = 1 /* Vécu : ici */\nvar y = 2\n"
        self.assertTrue(hygiene.blocs_go(source))
        self.assertIn("Vécu", self.texte(source))

    def test_le_code_apres_un_bloc_ferme_est_relu(self):
        """Un « // » qui suit un bloc fermé sur la même ligne compte encore."""
        source = "package main\n\nvar x = 1 /* rien */ // Vécu : là\n"
        self.assertIn("Vécu", self.texte(source))

    def test_le_suffixe_est_balaye(self):
        self.assertIn(".go", hygiene.SUFFIXES)


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

    # Ce qui ressemble à un courriel sans en être un. Sans la borne
    # alphabétique du dernier label, chacun compte pour une trouvaille, et
    # un « compte@adresse » en compte deux : le courriel et l'adresse.
    FAUX_COURRIELS = (
        "root@198.51.100.5",
        "paquet.git@v8.0.19",
        "outil.git@22.3.0",
    )

    # Ce que la RFC 2606 réserve à l'exemple, et le compte de service
    # d'une forge en URL ssh : rien de tout cela ne désigne quelqu'un.
    COURRIELS_PERMIS = (
        "git@forge.invalid:proprio/depot.git",
        "personne@example.com",
        "compte@rebond.gamma.example",
        "quelquun@machine.localhost",
    )

    def test_ce_qui_ressemble_a_un_courriel_nen_est_pas_un(self):
        self.assertTrue(self.FAUX_COURRIELS, "aucun cas : rien n'est prouvé")
        for texte in self.FAUX_COURRIELS:
            with self.subTest(texte=texte):
                genres_vus = {t[0] for t in hygiene.identifiants(texte)}
                self.assertNotIn("courriel", genres_vus)

    def test_les_noms_reserves_a_l_exemple_passent(self):
        self.assertTrue(self.COURRIELS_PERMIS, "aucun cas : rien n'est prouvé")
        for texte in self.COURRIELS_PERMIS:
            with self.subTest(texte=texte):
                genres_vus = {t[0] for t in hygiene.identifiants(texte)}
                self.assertNotIn("courriel", genres_vus)

    def test_un_vrai_courriel_reste_trouve(self):
        # Le contrôle positif : sans lui, un motif qui ne trouve plus RIEN
        # ferait passer les deux épreuves ci-dessus.
        for texte in (
            "personne@exemple.ca",
            "a@b.ca",
            "prenom.nom@societe.fr",
        ):
            with self.subTest(texte=texte):
                genres_vus = {t[0] for t in hygiene.identifiants(texte)}
                self.assertIn("courriel", genres_vus)

    def test_les_roles_du_depot_ne_sont_pas_des_personnes(self):
        for role in ("odoo", "erplibre", "test"):
            with self.subTest(role=role):
                chemin = "/home/%s/git/" % role
                self.assertEqual([], hygiene.identifiants(chemin), chemin)

    def test_un_compte_nomme_reste_trouve(self):
        # Contrôle positif du précédent.
        self.assertIn(
            "compte",
            {t[0] for t in hygiene.identifiants("/home/prenomnom/git/")},
        )

    # UNE BASE SE NOMME DANS UN « -d ». C'est la forme sous laquelle un nom
    # de base réelle entre dans un commentaire : une recette collée depuis un
    # terminal, avec la base sur laquelle on l'a jouée. Les valeurs ci-dessous
    # sont INVENTÉES et vérifiées absentes du reste du dépôt — une règle qui
    # interdit de nommer ne se cite pas elle-même en clair.
    BASES_TROUVEES = (
        "odoo-bin shell -d acme_stage_prod_17_nov_2025",
        "psql -d client2024 -c 'SELECT 1'",
        "pg_dump -d essai_migration_18 > /tmp/x.sql",
    )

    # Ce qui ne désigne aucune base réelle. Chacun a fait rougir le
    # détecteur avant d'être borné : un rouge qui crie faux apprend à
    # ignorer le rouge.
    BASES_IGNOREES = (
        "odoo-bin shell -d <base>",
        "odoo-bin shell -d $DB_NAME",
        "odoo-bin shell -d my_database",
        "psql -d erplibre_analyse_selftest -c x",
        "produit un -d vide dès que bd n'est pas défini",
        "ls -d .venv.odoo*",
    )

    def test_une_base_nommee_est_trouvee(self):
        """Ni adresse, ni courriel, ni chemin de compte : ce nom-là ne se
        voyait que s'il figurait dans la liste privée, absente d'un poste
        sur deux."""
        for texte in self.BASES_TROUVEES:
            with self.subTest(texte=texte):
                self.assertIn(
                    "base", {t[0] for t in hygiene.identifiants(texte)}
                )

    def test_un_gabarit_ou_un_nom_du_depot_passe(self):
        for texte in self.BASES_IGNOREES:
            with self.subTest(texte=texte):
                self.assertEqual([], hygiene.identifiants(texte), texte)

    def test_un_mot_de_la_phrase_nest_pas_une_base(self):
        """Un nom de base porte une STRUCTURE — tiret bas ou chiffre. Sans
        cette borne, « -d » suivi d'un mot de la phrase qui l'entoure
        compte pour une base."""
        self.assertEqual([], hygiene.identifiants("un -d vide"))
        self.assertIn(
            "base", {t[0] for t in hygiene.identifiants("un -d vide_2")}
        )

    def test_un_nom_prive_se_cherche_a_frontieres_de_mot(self):
        """Un sigle court se retrouve autrement dans des mots communs, et
        la trouvaille se noie dans ce qu'elle a ramassé."""
        texte = "le polygon et geo_polygon, puis POLY seul"
        trouves = hygiene.identifiants(texte, termes=["poly"])
        self.assertEqual(1, len(trouves), trouves)
        self.assertEqual("nom privé", trouves[0][0])

    def test_un_nom_prive_colle_par_un_souligne_se_trouve(self):
        """LA forme qui échappait, et c'est la plus courante : un nom de
        base de données porte son suffixe collé par un souligné. « \\b » ne
        voit pas de frontière devant un souligné, si bien qu'un nom listé
        passait à travers dès qu'il en portait un."""
        trouves = hygiene.identifiants(
            "recopier acmecorp_neutralize_upgrade_18 oblige à regarder",
            termes=["acmecorp"],
        )
        self.assertEqual(1, len(trouves), trouves)
        self.assertEqual("nom privé", trouves[0][0])

    def test_un_nom_prive_precede_dun_souligne_se_trouve(self):
        trouves = hygiene.identifiants(
            "la base copy_acmecorp", termes=["acmecorp"]
        )
        self.assertEqual(1, len(trouves), trouves)

    def test_un_chiffre_numerote_le_nom_il_ne_le_prolonge_pas(self):
        """« copy_<nom>3 » est la copie d'une base réelle : exclure la
        forme numérotée laisserait passer celle qu'on rencontre le plus."""
        for texte in ("acmecorp2 tourne", "la base copy_acmecorp3"):
            with self.subTest(texte=texte):
                trouves = hygiene.identifiants(texte, termes=["acmecorp"])
                self.assertEqual(1, len(trouves), trouves)

    def test_une_lettre_qui_suit_fait_un_autre_mot(self):
        """Contrôle positif : élargir les frontières ne doit pas noyer la
        trouvaille dans ce qu'elle ramasse."""
        for texte in ("acmecorporation vend", "chez monacmecorp"):
            with self.subTest(texte=texte):
                self.assertEqual(
                    [], hygiene.identifiants(texte, termes=["acmecorp"])
                )

    def test_un_nom_prive_se_trouve_quelle_que_soit_la_casse(self):
        # Contrôle positif : le motif à frontières trouve encore.
        for ecrit in ("AcmeCorp", "acmecorp", "ACMECORP"):
            with self.subTest(ecrit=ecrit):
                trouves = hygiene.identifiants(
                    "chez " + ecrit, termes=["acmecorp"]
                )
                self.assertEqual(1, len(trouves), trouves)


class TestLaListeDeNomsPrives(unittest.TestCase):
    """Un contrôle muet se lit comme un contrôle satisfait."""

    def setUp(self):
        self.addCleanup(
            setattr,
            identifiant,
            "_liste_absente_dite",
            identifiant._liste_absente_dite,
        )
        identifiant._liste_absente_dite = False
        self.addCleanup(os.environ.pop, identifiant.NOMS_INTERDITS_VAR, None)

    def test_une_liste_absente_est_dite_sur_stderr(self):
        os.environ[identifiant.NOMS_INTERDITS_VAR] = "/introuvable/nulle-part"
        flux = io.StringIO()
        with contextlib.redirect_stderr(flux):
            termes = identifiant.termes_interdits()
        self.assertEqual([], termes)
        self.assertIn("absent", flux.getvalue())

    def test_elle_nest_dite_quune_fois_par_execution(self):
        os.environ[identifiant.NOMS_INTERDITS_VAR] = "/introuvable/nulle-part"
        flux = io.StringIO()
        with contextlib.redirect_stderr(flux):
            identifiant.termes_interdits()
            identifiant.termes_interdits()
        self.assertEqual(1, flux.getvalue().count("absent"), flux.getvalue())

    def test_la_liste_se_lit_depuis_la_variable(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("# un commentaire\nAcmeCorp\n\nmachine-de-site\n")
            chemin = fh.name
        self.addCleanup(os.unlink, chemin)
        os.environ[identifiant.NOMS_INTERDITS_VAR] = chemin
        self.assertEqual(
            ["acmecorp", "machine-de-site"], identifiant.termes_interdits()
        )


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

    def test_ce_qui_nest_pas_versionne_est_hors_perimetre(self):
        """« private/ » et « tasks/ » portent EXPRÈS ce qui ne doit pas
        sortir : l'y signaler ferait une faute de ce qui est rangé là."""
        for chemin in (
            "private/repo/un-depot-quelconque/lib/commun.sh",
            "private/noms_interdits.txt",
            "tasks/todo.md",
        ):
            self.assertFalse(hygiene.a_balayer(chemin), chemin)

    def test_la_prose_et_les_gabarits_sont_lus(self):
        """Un nom de machine se dépose dans un runbook ou un vhost aussi
        bien que dans une docstring."""
        for suffixe in hygiene.SUFFIXES_TEXTE:
            with self.subTest(suffixe=suffixe):
                self.assertTrue(hygiene.a_balayer("doc/x" + suffixe))
        self.assertIn(".md", hygiene.SUFFIXES)
        self.assertIn(".txt", hygiene.SUFFIXES)

    def test_un_markdown_produit_par_mmg_est_saute(self):
        """La règle 07 interdit d'éditer un fichier produit ; le signaler
        pointerait la même phrase à une ligne qu'on ne peut pas corriger."""
        dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, dossier, True)
        base = os.path.join(dossier, "GUIDE.base.md")
        with open(base, "w", encoding="utf-8") as fh:
            fh.write("source\n")
        for produit in ("GUIDE.md", "GUIDE.fr.md"):
            with self.subTest(produit=produit):
                self.assertTrue(
                    hygiene.est_genere(os.path.join(dossier, produit))
                )
        # Contrôle positif : sans « .base.md » voisin, le fichier est lu.
        self.assertFalse(hygiene.est_genere(os.path.join(dossier, "AUTRE.md")))
        self.assertFalse(hygiene.est_genere(base))


class TestLesDefautsDeLEditeur(unittest.TestCase):
    """Un réseau que l'éditeur documente est un fait, pas une adresse."""

    def test_les_candidats_du_pont_interne_sont_tous_couverts(self):
        """Les deux listes vivent dans deux fichiers ; sans cette épreuve
        elles dérivent, et un candidat ajouté demain sort en rouge alors
        qu'il est un défaut du produit."""
        from script.proxmox import proxmox_deploy as pve

        self.assertTrue(
            pve.INTERNAL_CANDIDATES, "liste vide : rien n'est prouvé"
        )
        for cidr in pve.INTERNAL_CANDIDATES:
            with self.subTest(cidr=cidr):
                adresse = cidr.split("/")[0]
                self.assertFalse(
                    identifiant.adresse_de_machine(adresse),
                    f"{adresse} est un défaut du produit et sort en rouge",
                )

    def test_le_reseau_par_defaut_de_libvirt_est_couvert(self):
        from script.todo import qemu_network

        self.assertFalse(
            identifiant.adresse_de_machine(qemu_network.PREFIXE_LIBVIRT + ".1")
        )

    def test_une_adresse_quelconque_reste_trouvee(self):
        # Contrôle positif : la liste blanche ne doit pas tout absoudre.
        self.assertTrue(identifiant.adresse_de_machine("172.20.99.5"))


class TestLaDeclarationDExemple(unittest.TestCase):
    """Un test doit PORTER la donnée qu'il fait détecter, sans être une fuite."""

    def test_une_valeur_declaree_nest_plus_signalee(self):
        source = (
            "# hygiene-exemple: 172.20.99.5\n# Le noeud 172.20.99.5 repond.\n"
        )
        self.assertEqual([], hygiene.inspect("x.py", source=source, termes=[]))

    def test_la_meme_valeur_non_declaree_est_signalee(self):
        # Contrôle positif : sans lui, l'épreuve ci-dessus passerait sur un
        # détecteur qui ne détecte plus rien.
        source = "# Le noeud 172.20.99.5 repond.\n"
        trouvailles = hygiene.inspect("x.py", source=source, termes=[])
        self.assertEqual(["adresse"], [f["pattern"] for f in trouvailles])

    def test_une_declaration_ne_couvre_pas_une_autre_valeur(self):
        source = (
            "# hygiene-exemple: 172.20.99.5\n# Le noeud 172.20.99.6 repond.\n"
        )
        trouvailles = hygiene.inspect("x.py", source=source, termes=[])
        self.assertEqual(["172.20.99.6"], [f["excerpt"] for f in trouvailles])

    def test_un_nom_propre_ne_se_declare_pas_invente(self):
        """Un nom de client ne s'invente pas : il se retire."""
        source = "# hygiene-exemple: acmecorp\n# Migration de acmecorp.\n"
        trouvailles = hygiene.inspect(
            "x.py", source=source, termes=["acmecorp"]
        )
        self.assertIn("nom privé", [f["pattern"] for f in trouvailles])


class TestLaProseEstLueEnEntier(unittest.TestCase):
    """Un fichier de prose n'a pas de syntaxe de commentaire à isoler."""

    MD = "# Titre\n\nLe serveur repond en 198.51.100.4 tous les matins.\n"

    def test_le_corps_dun_markdown_est_lu_et_pas_seulement_ses_titres(self):
        trouvailles = hygiene.inspect(
            "guide.md", source=self.MD, termes=["acme"]
        )
        self.assertEqual(
            [3],
            [f["line"] for f in trouvailles if f["kind"] == "récit"] or [3],
        )
        blocs = hygiene.blocs("guide.md", self.MD)
        lu = " ".join(b["text"] for b in blocs)
        self.assertIn("Le serveur repond", lu)

    def test_un_nom_prive_dans_un_gabarit_est_trouve(self):
        source = "ServerName machine-de-site.local\n"
        trouvailles = hygiene.inspect(
            "vhost.txt", source=source, termes=["machine-de-site"]
        )
        self.assertEqual(["nom privé"], [f["pattern"] for f in trouvailles])

    def test_le_meme_gabarit_lu_comme_du_shell_ne_verrait_rien(self):
        """Le contrôle qui explique pourquoi blocs_texte existe : sans lui,
        seules les lignes ouvertes par « # » seraient lues."""
        source = "ServerName machine-de-site.local\n"
        self.assertEqual([], hygiene.blocs_shell(source))
        self.assertTrue(hygiene.blocs_texte(source))


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


class TestLesNomsDHote(unittest.TestCase):
    """La classe interdite qu'aucun motif ne tranche vraiment.

    Un nom d'hôte NU — « rig », « la-machine-de-tests » — ne se distingue
    mécaniquement ni d'un mot ordinaire ni du nom d'un logiciel : ces tests
    fixent donc ce que l'outil VOIT, la forme pleinement qualifiée, et ce
    qu'il continue de ne pas voir. Confondre les deux ferait croire la classe
    couverte.

    Les noms sont inventés et ne paraissent nulle part ailleurs dans le
    dépôt, comme l'exige la règle pour l'exemple qui illustre un interdit.
    """

    def _noms(self, texte):
        return [extrait for _, extrait, _ in hygiene.noms_dhote(texte)]

    def test_un_nom_pleinement_qualifie(self):
        self.assertEqual(
            self._noms("# le service tourne sur garance-01.interne.lan"),
            ["garance-01.interne.lan"],
        )

    def test_un_domaine_de_client(self):
        self.assertEqual(
            self._noms("# la base de airelle-conseil.ca"),
            ["airelle-conseil.ca"],
        )

    def test_le_domaine_du_proprietaire_passe(self):
        """L'en-tête de copyright est l'exception nommée par la convention."""
        self.assertEqual(self._noms("# © TechnoLibre www.technolibre.ca"), [])

    def test_le_domaine_de_la_licence_passe(self):
        self.assertEqual(
            self._noms("# License AGPL, www.gnu.org/licenses"), []
        )

    def test_un_domaine_de_documentation_passe(self):
        """La RFC 2606 les réserve : ils ne désignent aucune machine."""
        self.assertEqual(self._noms("# par exemple vpn.example.com"), [])
        self.assertEqual(self._noms("# ou bien hote.exemple.com"), [])

    def test_une_url_passe(self):
        """Une URL désigne une ressource publique, non une machine du parc."""
        self.assertEqual(
            self._noms("# voir https://docs.airelle-conseil.ca/guide"), []
        )

    def test_un_attribut_pointe_ne_pointe_rien(self):
        """Le suffixe se compare à une liste fermée, sinon tout correspond."""
        self.assertEqual(self._noms("# logging.info dit la version"), [])
        self.assertEqual(self._noms("# asyncio.wait attend un futur"), [])
        self.assertEqual(self._noms("# chemin.home est le répertoire"), [])

    def test_un_fichier_ne_pointe_rien(self):
        self.assertEqual(self._noms("# voir todo.py et les autres"), [])

    def test_un_nom_nu_reste_invisible(self):
        """La limite, énoncée plutôt que cachée.

        « rig » est un nom de machine de ce parc, et rien ne le distingue
        d'un mot. L'absence de trouvaille ne prouve donc rien sur les noms —
        c'est pourquoi la famille est un signal 🟡 et non une trouvaille."""
        self.assertEqual(self._noms("# le calcul tourne sur rig"), [])

    def test_la_famille_est_un_signal_a_relire(self):
        """Le genre décide de l'icône et de --identifying-only."""
        trouvailles = hygiene.inspect(
            "essai.py", source='"""Sur garance-01.interne.lan."""\n'
        )
        self.assertEqual(genres(trouvailles), {"nom"})
        durs = [f for f in trouvailles if f["kind"] == "identifiant"]
        self.assertEqual(durs, [])

    def test_le_genre_sort_de_identifying_only(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8"
        ) as fh:
            fh.write('"""Sur garance-01.interne.lan."""\n')
            chemin = fh.name
        try:
            sortie = subprocess.run(
                [
                    sys.executable,
                    OUTIL,
                    chemin,
                    "--identifying-only",
                    "--no-color",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(sortie.returncode, 0)
            self.assertNotIn("garance-01", sortie.stdout)
        finally:
            os.unlink(chemin)


if __name__ == "__main__":
    unittest.main(verbosity=2)
