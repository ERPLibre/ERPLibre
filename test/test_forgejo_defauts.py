#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que la forge accorde à qui atteint son port, avant qu'on lui parle.

Forgejo n'écoute pas la boucle locale : c'est une forge, elle est faite pour
être jointe. Ses défauts d'installation décident donc seuls de ce qu'un
inconnu peut faire — ouvrir un compte, ou se connecter avec un identifiant
que le script publie.

TROIS RÉGLAGES, ET LEUR SENS.

« DISABLE_REGISTRATION » ferme l'inscription libre : l'administrateur crée
les comptes, ouvrir se demande.

« ALLOW_LOCALNETWORKS » reste faux. Forgejo refuse par défaut de migrer ou
de miroiter depuis une adresse de plage privée — sa protection contre une
forge qui atteindrait ce que son visiteur n'atteint pas. Le refus se
présente en « 401 Permission denied », qui se lit comme un jeton invalide.

Le mot de passe de l'administrateur est TIRÉ AU SORT quand personne n'en
fournit. Un mot de passe écrit dans un script publié est une clé publiée.

LA CONFIGURATION EST RENDUE, PAS RELUE. Le bloc qui écrit app.ini est
extrait du script et joué par bash avec un faux binaire : ce qui est éprouvé
est le fichier obtenu, et non l'allure de la source. Un « $ » oublié ou une
variable renommée d'un côté se voit ici, là où un grep passerait.
"""

import os
import pathlib
import re
import subprocess
import unittest

RACINE = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = RACINE / "script/forgejo/install_forgejo.sh"

DEBUT = "    disable_registration=true"
FIN = "CONFEOF"


def bloc_de_configuration():
    """Le code du script qui produit app.ini, du calcul des booléens à la
    fin du document en ligne, « sudo tee » remplacé par « cat »."""
    lignes = SCRIPT.read_text(encoding="utf-8").splitlines()
    debut = [i for i, ligne in enumerate(lignes) if ligne == DEBUT]
    assert len(debut) == 1, f"ancre de début absente ou dédoublée : {debut}"
    fin = [i for i, ligne in enumerate(lignes) if ligne == FIN]
    assert len(fin) == 1, f"ancre de fin absente ou dédoublée : {fin}"
    assert fin[0] > debut[0]
    bloc = "\n".join(lignes[debut[0] : fin[0] + 1])
    return bloc.replace(
        'sudo tee "$CONF" >/dev/null <<CONFEOF', "cat <<CONFEOF"
    )


def rendre(**environnement):
    """app.ini tel que le script l'écrirait, sans rien installer.

    Le faux binaire rend une chaîne fixe pour « generate secret » : les vrais
    secrets ne servent à rien ici, et en tirer coûterait un binaire Forgejo.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as coffre:
        faux = pathlib.Path(coffre) / "forgejo"
        faux.write_text("#!/bin/sh\necho SECRET-DE-BANC\n", encoding="utf-8")
        faux.chmod(0o755)
        programme = "\n".join(
            [
                "set -euo pipefail",
                'OPEN_REGISTRATION="${OPEN_REGISTRATION:-0}"',
                'ALLOW_LOCALNETWORKS="${ALLOW_LOCALNETWORKS:-0}"',
                f'BIN="{faux}"',
                "RUN_USER=git",
                "DATA=/var/lib/forgejo",
                "HTTP_PORT=3000",
                "SSH_PORT=2222",
                "host=192.0.2.10",
                bloc_de_configuration(),
            ]
        )
        milieu = dict(os.environ)
        milieu.update({cle: str(val) for cle, val in environnement.items()})
        resultat = subprocess.run(
            ["bash", "-c", programme],
            capture_output=True,
            text=True,
            env=milieu,
            timeout=30,
        )
    assert resultat.returncode == 0, resultat.stderr
    return resultat.stdout


def valeur(config, cle):
    """La valeur d'une clé d'app.ini, ou None si elle n'y est pas."""
    trouve = re.search(rf"^{re.escape(cle)}\s*=\s*(.+)$", config, re.M)
    return trouve.group(1).strip() if trouve else None


class TestLaConfigurationRendue(unittest.TestCase):
    def test_the_rendering_produces_a_real_config(self):
        """Un bloc mal découpé rendrait du vide, et tout le reste passerait
        sans avoir rien mesuré."""
        config = rendre()
        self.assertIn("[server]", config)
        self.assertIn("[service]", config)
        self.assertNotIn("CONFEOF", config)

    def test_no_variable_is_left_unexpanded(self):
        """Un « $nom » survivant dans app.ini est une clé sans valeur, que
        Forgejo lit comme une chaîne littérale."""
        config = rendre()
        restants = re.findall(r"\$\{?[A-Za-z_][A-Za-z0-9_]*", config)
        self.assertEqual([], restants, config)

    def test_registration_is_closed_by_default(self):
        """Sinon quiconque atteint le port se fait un compte."""
        self.assertEqual("true", valeur(rendre(), "DISABLE_REGISTRATION"))

    def test_registration_can_be_opened_and_has_to_be_asked_for(self):
        """Contrôle positif : la fermer toujours retirerait l'usage."""
        config = rendre(OPEN_REGISTRATION="1")
        self.assertEqual("false", valeur(config, "DISABLE_REGISTRATION"))

    def test_local_networks_are_refused_by_default(self):
        config = rendre()
        self.assertEqual("false", valeur(config, "ALLOW_LOCALNETWORKS"))

    def test_local_networks_can_be_allowed_and_have_to_be_asked_for(self):
        config = rendre(ALLOW_LOCALNETWORKS="1")
        self.assertEqual("true", valeur(config, "ALLOW_LOCALNETWORKS"))

    def test_the_two_settings_are_independent(self):
        """Les lier ferait ouvrir l'inscription en demandant un miroir."""
        config = rendre(ALLOW_LOCALNETWORKS="1")
        self.assertEqual("true", valeur(config, "DISABLE_REGISTRATION"))
        config = rendre(OPEN_REGISTRATION="1")
        self.assertEqual("false", valeur(config, "ALLOW_LOCALNETWORKS"))

    def test_the_booleans_are_words_and_never_digits(self):
        """app.ini lit « 1 » comme faux, sans un mot dans le journal :
        l'inscription resterait ouverte alors qu'on l'a fermée."""
        for options in (
            {},
            {"OPEN_REGISTRATION": "1"},
            {"ALLOW_LOCALNETWORKS": "1"},
        ):
            config = rendre(**options)
            for cle in ("DISABLE_REGISTRATION", "ALLOW_LOCALNETWORKS"):
                with self.subTest(options=options, cle=cle):
                    self.assertIn(valeur(config, cle), ("true", "false"))

    def test_an_unexpected_value_does_not_open_anything(self):
        """« true », « yes », « oui » ne sont pas 1 : le script exige la
        valeur documentée plutôt que d'interpréter une intention."""
        for dit in ("true", "yes", "oui", "0", "", "01"):
            with self.subTest(valeur=dit):
                config = rendre(OPEN_REGISTRATION=dit)
                self.assertEqual(
                    "true", valeur(config, "DISABLE_REGISTRATION")
                )


class TestLAideDitTousLesReglages(unittest.TestCase):
    """Un réglage que le script honore mais que l'aide tait n'existe pas.

    « --help » découpait l'en-tête à des NUMÉROS DE LIGNE écrits en dur.
    Ajouter un réglage sous la borne le fait disparaître de l'aide sans un
    mot : le script l'honore, et personne ne peut le découvrir. L'épreuve
    compare ce que le script LIT à ce que l'aide MONTRE, donc elle tient
    quelle que soit la façon dont l'aide est produite.
    """

    def aide(self):
        res = subprocess.run(
            ["bash", str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, res.returncode, res.stderr)
        return res.stdout

    def variables_lues(self):
        """Les « FORGEJO_* » que le script consulte dans une expansion."""
        source = SCRIPT.read_text(encoding="utf-8")
        sans_commentaires = "\n".join(
            ligne
            for ligne in source.splitlines()
            if not ligne.lstrip().startswith("#")
        )
        return set(re.findall(r"\$\{(FORGEJO_[A-Z_]+)", sans_commentaires))

    def test_the_script_reads_some_settings(self):
        """Une extraction cassée rendrait un ensemble vide, et la
        comparaison passerait sans avoir rien comparé."""
        self.assertTrue(self.variables_lues())

    def test_the_help_shows_something(self):
        self.assertIn("FORGEJO_", self.aide())

    def test_every_setting_the_script_reads_is_in_the_help(self):
        aide = self.aide()
        for variable in sorted(self.variables_lues()):
            with self.subTest(variable=variable):
                self.assertIn(variable, aide)

    def test_the_help_stops_at_the_end_of_the_header(self):
        """Une borne trop lâche déverse les commentaires INTERNES dans
        l'aide — les raisons d'implémentation, qui n'y ont rien à faire.

        Le code, lui, ne fuit pas : le second sed ne garde que ce qui
        commence par « # ». C'est donc sur les commentaires qu'il faut
        mesurer, et non sur les instructions.
        """
        aide = self.aide()
        lignes = SCRIPT.read_text(encoding="utf-8").splitlines()
        # L'en-tête finit à la première ligne, après la cinquième, qui n'est
        # ni un commentaire ni vide.
        fin = next(
            i
            for i, ligne in enumerate(lignes)
            if i >= 4 and ligne and not ligne.lstrip().startswith("#")
        )
        internes = [
            ligne.lstrip("# ").strip()
            for ligne in lignes[fin:]
            if ligne.lstrip().startswith("#")
            and len(ligne.lstrip("# ").strip()) > 30
        ]
        self.assertTrue(internes, "aucun commentaire interne relu")
        for phrase in internes:
            with self.subTest(phrase=phrase[:50]):
                self.assertNotIn(phrase, aide)


class TestLIdentifiantQueLeScriptNePubliePas(unittest.TestCase):
    """Un mot de passe écrit dans un script publié est une clé publiée."""

    def setUp(self):
        self.source = SCRIPT.read_text(encoding="utf-8")

    def test_no_password_is_written_into_the_script(self):
        trouve = re.search(
            r'ADMIN_PASSWORD="\$\{FORGEJO_ADMIN_PASSWORD:-([^"]*)\}"',
            self.source,
        )
        self.assertIsNotNone(trouve, "l'affectation a changé de forme")
        self.assertEqual("", trouve.group(1), "un défaut est écrit en clair")

    def test_the_drawn_password_is_never_printed(self):
        """La sortie part dans les journaux d'installation et dans toute
        capture de CI ; c'est le CHEMIN qui s'annonce."""
        for ligne in self.source.splitlines():
            depouille = ligne.strip()
            if depouille.startswith("#") or "say " not in depouille:
                continue
            with self.subTest(ligne=depouille[:60]):
                self.assertNotIn("$ADMIN_PASSWORD", depouille)
                self.assertNotIn("${ADMIN_PASSWORD", depouille)

    def test_the_file_is_created_restricted_before_being_filled(self):
        """« tee » puis « chmod » laisse le secret lisible par tous le temps
        de deux appels système."""
        pose = self.source.index("install -m 600")
        remplissage = self.source.index('sudo tee "$PASSWORD_FILE"')
        self.assertLess(pose, remplissage)

    def test_the_drawing_is_long_enough_to_be_worth_drawing(self):
        """Un tirage qui rendrait trois caractères passerait inaperçu."""
        self.assertIn("${#ADMIN_PASSWORD} -ge 16", self.source)


class TestLeTirageEstJouable(unittest.TestCase):
    """La chaîne de tubes du tirage, jouée telle qu'elle est écrite.

    « tr -dc < /dev/urandom | head -c N » lit un flux SANS FIN : head prend
    ses N caractères, ferme le tube, tr meurt sur SIGPIPE, et « pipefail »
    fait échouer toute l'affectation — code 141, à tous les coups. Borner la
    lecture EN AMONT est ce qui l'évite : les octets tiennent alors dans le
    tampon du tube et tr a fini d'écrire avant que head ne parte.

    Un piège que seul le shell révèle : la source des deux formes se
    ressemble, et leur comportement ne se ressemble pas du tout.
    """

    def commande(self):
        source = SCRIPT.read_text(encoding="utf-8")
        trouve = re.search(
            r"ADMIN_PASSWORD=\$\((head -c.*?)\)\n", source, re.S
        )
        self.assertIsNotNone(trouve, "le tirage a changé de forme")
        return trouve.group(1).replace("\\\n", " ")

    def test_it_runs_clean_under_pipefail(self):
        tirage = self.commande()
        for _ in range(5):
            res = subprocess.run(
                [
                    "bash",
                    "-c",
                    f"set -euo pipefail\np=$({tirage})\necho -n $p",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(0, res.returncode, res.stderr)
            self.assertGreaterEqual(len(res.stdout), 16, res.stdout)

    def test_two_drawings_differ(self):
        """Un tirage constant serait un mot de passe écrit en clair, en
        plus long."""
        tirage = self.commande()
        vus = set()
        for _ in range(5):
            res = subprocess.run(
                ["bash", "-c", f"set -euo pipefail\necho -n $({tirage})"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            vus.add(res.stdout)
        self.assertEqual(5, len(vus), vus)

    def test_it_stays_typable(self):
        """Le mot de passe se recopie à la main depuis une console : un
        caractère hors alphanumérique s'y perd selon la disposition.

        VINGT TIRAGES, ET NON UN. base64 emploie « / » et « + », soit deux
        symboles sur soixante-quatre : un tirage de vingt-quatre caractères
        n'en contient aucun une fois sur deux. Un seul échantillon
        déclarerait l'alphabet propre la moitié du temps.
        """
        tirage = self.commande()
        for essai in range(20):
            res = subprocess.run(
                ["bash", "-c", f"set -euo pipefail\necho -n $({tirage})"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            with self.subTest(essai=essai):
                self.assertTrue(res.stdout.isalnum(), repr(res.stdout))


if __name__ == "__main__":
    unittest.main()
