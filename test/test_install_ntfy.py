#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installateur ntfy : ce qu'il refuse de laisser en place.

Le script annonce un acces refuse par defaut. Il respectait pourtant une
configuration deja presente sans regarder ce qu'elle disait — celle d'une
distribution autorise la lecture ET l'ecriture anonymes sur tous les sujets,
sur toutes les interfaces. Une posture annoncee et non appliquee est pire que
pas de script : on croit le serveur ferme.
"""
import os
import subprocess
import sys
import tempfile
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(RACINE, "script/install/install_ntfy.sh")


def extraire_fonction(nom):
    """Rend la fonction shell demandee, seule, executable dans un bac a sable.

    Le script entier exige root et installe pour de vrai : on en extrait la
    decision a eprouver, qui ne depend que du fichier de configuration.
    """
    with open(SCRIPT, encoding="utf-8") as flux:
        texte = flux.read()
    debut = texte.index("%s()" % nom)
    fin = texte.index("\n}\n", debut) + 3
    return texte[debut:fin]


class TestConfigurationDejaEnPlace(unittest.TestCase):
    def _jouer(self, contenu_yml, environnement=None):
        """Joue la fonction de configuration sur un server.yml donne."""
        with tempfile.TemporaryDirectory() as dossier:
            if contenu_yml is not None:
                with open(os.path.join(dossier, "server.yml"), "w") as flux:
                    flux.write(contenu_yml)
            enveloppe = (
                "set -e\n"
                "log() { echo \"$*\"; }\n"
                "die() { echo \"ERREUR: $*\" >&2; exit 1; }\n"
                # Le compte systeme et les droits ne sont pas ce qu'on
                # eprouve ici, et les poser demanderait root.
                "id() { return 1; }\n"
                "chown() { :; }\n"
                "CONFIG_DIR=%s\n"
                "CACHE_DIR=%s/cache\n"
                "NTFY_PORT=8080\nNTFY_BASE_URL=http://localhost:8080\n"
                "NTFY_PUBLIC=0\nNTFY_CERT_FILE=\nNTFY_KEY_FILE=\n"
                % (dossier, dossier)
            ) + extraire_fonction("configure_ntfy") + "\nconfigure_ntfy\n"
            env = dict(os.environ)
            env.update(environnement or {})
            fait = subprocess.run(["bash", "-c", enveloppe], capture_output=True,
                                  text=True, env=env, timeout=30)
            yml = os.path.join(dossier, "server.yml")
            ecrit = open(yml).read() if os.path.exists(yml) else ""
            return fait, ecrit

    def test_une_config_permissive_arrete_l_installateur(self):
        """Celle d'une distribution ne declare aucun controle d'acces."""
        fait, ecrit = self._jouer('listen-http: ":8080"\n')
        self.assertNotEqual(fait.returncode, 0, fait.stdout)
        self.assertIn("aucun controle d'acces", fait.stderr.lower())
        # Elle n'est pas remplacee en silence : le script dit comment faire.
        self.assertIn("server.yml.origine", fait.stderr)
        self.assertEqual(ecrit, 'listen-http: ":8080"\n')

    def test_une_config_qui_declare_son_acces_est_respectee(self):
        """Elle peut porter des reglages d'exploitation qu'on ignore."""
        posee = 'listen-http: ":8080"\nauth-default-access: "deny-all"\n'
        fait, ecrit = self._jouer(posee)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(ecrit, posee)

    def test_on_peut_garder_la_permissive_en_le_disant(self):
        """Un choix, pas un oubli : il faut le declarer."""
        fait, _ = self._jouer('listen-http: ":8080"\n',
                              {"NTFY_GARDER_CONFIG": "1"})
        self.assertEqual(fait.returncode, 0, fait.stderr)

    def test_sans_config_l_installateur_ecrit_la_sienne(self):
        fait, ecrit = self._jouer(None)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("auth-default-access", ecrit)
        self.assertIn("deny-all", ecrit)


if __name__ == "__main__":
    sys.exit(not unittest.main(exit=False).result.wasSuccessful())
