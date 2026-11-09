#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""script/docker/docker_copy_file.sh devant un faux « docker » : aucun
conteneur n'est touché.

Le faux docker exécute LOCALEMENT, dans un répertoire temporaire, les
commandes que le script passe à docker exec — le parcours de la destination
comme l'écriture — sans changer de compte ; il note l'uid demandé par -u. Un
parcours peut aussi être imposé pour un uid par FAUX_PARCOURS_<uid>, ce qui
simule un conteneur dont les répertoires appartiennent à root.

Ce que ces tests gardent :

- le fichier arrive intact, les répertoires créés en 755 et le fichier en
  644, malgré le umask 0000 de docker exec ;
- le premier parcours tourne sous le propriétaire de /ERPLibre ; un parcours
  arrêté par un répertoire se reprend sous le propriétaire de ce répertoire,
  une seule fois par compte ;
- l'écrivain est le propriétaire de l'ancêtre existant ; root n'écrit que si
  tout le chemin lui appartient et que l'ancêtre n'est ouvert ni au groupe ni
  aux autres, sinon le propriétaire de /ERPLibre écrit ;
- root n'écrit que sur un parcours fait sous root : un parcours d'un autre
  compte qui désigne root se refait sous root, qui doit rendre le même chemin
  canonique et un chemin sûr, sinon le propriétaire de /ERPLibre écrit ;
- sans destination, le fichier va dans /home/odoo ;
- le chemin écrit est le chemin canonique : un lien de la destination n'est
  pas suivi une seconde fois ;
- une destination relative, un non-répertoire, une réponse qui n'est pas un
  entier arrêtent le script sans écrire.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SCRIPT = RACINE / "script" / "docker" / "docker_copy_file.sh"
PROPRIETAIRE = "4242"

# Chaque appel tient sur une ligne du journal, le parcours compris.
# « inspect » dit tout conteneur en marche ; « exec » note son uid, répond au
# stat de /ERPLibre par FAUX_PROPRIETAIRE, sert FAUX_PARCOURS_<uid> au
# parcours quand il est posé, et exécute sinon la commande sur l'hôte, entrée
# standard comprise et umask 0000 comme docker exec.
FAUX_DOCKER = r"""#!/usr/bin/env bash
appel="$*"
echo "${appel//$'\n'/ }" >> "${FAUX_DOCKER_JOURNAL}"
case "$1" in
  version) echo "29.0" ;;
  compose) ;;
  inspect) echo true ;;
  exec)
    shift
    uid=""
    while [[ "$1" == -* ]]; do
      case "$1" in
        -u) uid="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    shift
    if [[ "$*" == "stat -c %u /ERPLibre" ]]; then
      echo "${FAUX_PROPRIETAIRE}"; exit 0
    fi
    if [[ "$*" == *realpath* ]]; then
      canned="FAUX_PARCOURS_${uid}"
      if [[ -n "${!canned:-}" ]]; then printf '%b' "${!canned}"; exit 0; fi
    fi
    umask 0000
    exec "$@" ;;
esac
"""


class Bac:
    """Un répertoire temporaire, un faux docker et un fichier source."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self._tmp.name).resolve()
        faux = self.racine / "bin"
        faux.mkdir()
        (faux / "docker").write_text(FAUX_DOCKER, encoding="utf-8")
        (faux / "docker").chmod(0o755)
        self.projet = self.racine / "projet"
        self.projet.mkdir()
        self.contenu = bytes(range(256)) * 64 + "é\n".encode()
        (self.projet / "source.bin").write_bytes(self.contenu)
        self.journal = self.racine / "journal"
        self.journal.touch()
        self.env = dict(
            os.environ,
            PATH=f"{faux}:{os.environ['PATH']}",
            FAUX_DOCKER_JOURNAL=str(self.journal),
            FAUX_PROPRIETAIRE=PROPRIETAIRE,
        )

    def fermer(self):
        self._tmp.cleanup()

    def lancer(self, destination, **variables):
        """Lance le script vers destination, ou sans destination si elle
        vaut None."""
        self.journal.write_text("", encoding="utf-8")
        env = dict(self.env)
        env.update({k: str(v) for k, v in variables.items()})
        arguments = [str(SCRIPT), "source.bin"]
        if destination is not None:
            arguments.append(destination)
        sortie = subprocess.run(
            arguments,
            cwd=self.projet,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        appels = self.journal.read_text(encoding="utf-8").splitlines()
        return sortie, [a for a in appels if a.startswith("exec ")]


def uid_de(appel):
    """L'uid passé à -u d'un appel « exec »."""
    mots = appel.split()
    return mots[mots.index("-u") + 1]


def parcours(appels):
    return [uid_de(a) for a in appels if "realpath" in a]


def ecritures(appels):
    return [a for a in appels if "cat >" in a]


def reponse(*champs):
    """Un parcours imposé, un champ par ligne, au format de printf %b."""
    return "".join(f"{c}\\n" for c in champs)


class TestDockerCopyFile(unittest.TestCase):
    def setUp(self):
        self.bac = Bac()
        self.addCleanup(self.bac.fermer)

    def test_fichier_intact_modes_755_644(self):
        dest = self.bac.racine / "neuf" / "sous dossier"
        sortie, appels = self.bac.lancer(str(dest))
        self.assertEqual(sortie.returncode, 0, sortie.stdout + sortie.stderr)
        fichier = dest / "source.bin"
        self.assertEqual(self.bac.contenu, fichier.read_bytes())
        self.assertEqual(0o644, fichier.stat().st_mode & 0o777)
        for rep in (dest, dest.parent):
            self.assertEqual(0o755, rep.stat().st_mode & 0o777, rep)
        # Le parcours sous le propriétaire du code, l'écriture sous celui de
        # l'ancêtre existant, ici le compte qui lance le test.
        self.assertEqual([PROPRIETAIRE], parcours(appels))
        self.assertEqual(
            [str(os.getuid())], [uid_de(a) for a in ecritures(appels)]
        )

    def test_un_lien_mene_au_chemin_canonique(self):
        cible = self.bac.racine / "cible"
        cible.mkdir()
        (self.bac.racine / "lien").symlink_to(cible)
        sortie, appels = self.bac.lancer(str(self.bac.racine / "lien" / "x"))
        self.assertEqual(sortie.returncode, 0, sortie.stdout + sortie.stderr)
        self.assertTrue((cible / "x" / "source.bin").is_file())
        self.assertIn(f"{cible}/x", ecritures(appels)[0])
        self.assertNotIn("/lien", ecritures(appels)[0])

    def test_un_fichier_en_destination_est_refuse(self):
        (self.bac.racine / "fichier").write_text("x", encoding="utf-8")
        sortie, appels = self.bac.lancer(str(self.bac.racine / "fichier"))
        self.assertEqual(sortie.returncode, 1)
        self.assertIn("is not a directory", sortie.stdout)
        self.assertEqual([], ecritures(appels))

    def test_une_destination_relative_est_refusee(self):
        sortie, appels = self.bac.lancer("relatif/x")
        self.assertEqual(sortie.returncode, 1)
        self.assertIn("must be absolute", sortie.stdout)
        self.assertEqual([], appels)

    def test_bloque_puis_repris_sous_root(self):
        """Un répertoire 700 de root arrête le propriétaire du code ; root,
        maître de tout le chemin, écrit."""
        canon = self.bac.racine / "racine_root" / "x"
        sortie, appels = self.bac.lancer(
            "/racine_root/x",
            **{
                f"FAUX_PARCOURS_{PROPRIETAIRE}": reponse(
                    "blocked", "0", "/racine_root"
                ),
                "FAUX_PARCOURS_0": reponse(
                    "ok", "0", "700", "1", "/racine_root", canon
                ),
            },
        )
        self.assertEqual(sortie.returncode, 0, sortie.stdout + sortie.stderr)
        self.assertEqual([PROPRIETAIRE, "0"], parcours(appels))
        self.assertEqual(["0"], [uid_de(a) for a in ecritures(appels)])
        self.assertEqual(self.bac.contenu, (canon / "source.bin").read_bytes())

    def test_bloque_par_un_compte_deja_essaye(self):
        sortie, appels = self.bac.lancer(
            "/ailleurs/x",
            **{
                f"FAUX_PARCOURS_{PROPRIETAIRE}": reponse(
                    "blocked", PROPRIETAIRE, "/ailleurs"
                )
            },
        )
        self.assertEqual(sortie.returncode, 1)
        self.assertIn("can traverse '/ailleurs'", sortie.stdout)
        self.assertEqual([PROPRIETAIRE], parcours(appels))
        self.assertEqual([], ecritures(appels))

    def test_root_n_ecrit_pas_dans_un_repertoire_ouvert_a_tous(self):
        """/tmp est à root mais ouvert à tous : le compte d'Odoo écrit."""
        canon = self.bac.racine / "x"
        sortie, appels = self.bac.lancer(
            "/tmp/x",
            **{
                f"FAUX_PARCOURS_{PROPRIETAIRE}": reponse(
                    "ok", "0", "1777", "1", "/tmp", canon
                )
            },
        )
        self.assertEqual(sortie.returncode, 0, sortie.stdout + sortie.stderr)
        self.assertEqual(
            [PROPRIETAIRE], [uid_de(a) for a in ecritures(appels)]
        )

    def test_root_n_ecrit_pas_au_bout_d_un_chemin_qui_n_est_pas_a_lui(self):
        """Un lien d'un autre compte vers un répertoire de root : le
        propriétaire du code écrit, que ce répertoire refusera."""
        canon = self.bac.racine / "x"
        sortie, appels = self.bac.lancer(
            "/ERPLibre/lien/x",
            **{
                f"FAUX_PARCOURS_{PROPRIETAIRE}": reponse(
                    "ok", "0", "755", "0", "/etc", canon
                )
            },
        )
        self.assertEqual(sortie.returncode, 0, sortie.stdout + sortie.stderr)
        self.assertEqual(
            [PROPRIETAIRE], [uid_de(a) for a in ecritures(appels)]
        )

    def test_root_ecrit_apres_un_second_parcours_sous_root(self):
        """Le parcours du propriétaire du code désigne root : root refait
        le parcours, le confirme, et écrit."""
        canon = self.bac.racine / "x"
        champs = reponse("ok", "0", "755", "1", "/etc", canon)
        sortie, appels = self.bac.lancer(
            "/etc/x",
            **{
                f"FAUX_PARCOURS_{PROPRIETAIRE}": champs,
                "FAUX_PARCOURS_0": champs,
            },
        )
        self.assertEqual(sortie.returncode, 0, sortie.stdout + sortie.stderr)
        self.assertEqual([PROPRIETAIRE, "0"], parcours(appels))
        self.assertEqual(["0"], [uid_de(a) for a in ecritures(appels)])
        self.assertEqual(self.bac.contenu, (canon / "source.bin").read_bytes())

    def test_root_n_ecrit_pas_sans_la_confirmation_de_son_parcours(self):
        """Un parcours sous root qui ne confirme pas celui du propriétaire
        du code laisse l'écriture à ce dernier."""
        canon = self.bac.racine / "x"
        premier = reponse("ok", "0", "755", "1", "/etc", canon)
        for nom, second in (
            (
                "autre chemin",
                reponse("ok", "0", "755", "1", "/etc", "/etc/autre"),
            ),
            (
                "chemin pas sûr",
                reponse("ok", "0", "755", "0", "/etc", canon),
            ),
            (
                "ancêtre ouvert",
                reponse("ok", "0", "775", "1", "/etc", canon),
            ),
            (
                "ancêtre d'un autre",
                reponse("ok", PROPRIETAIRE, "755", "1", "/etc", canon),
            ),
            ("bloqué", reponse("blocked", "0", "/etc")),
            ("mode invalide", reponse("ok", "0", "7a5", "1", "/etc", canon)),
        ):
            with self.subTest(nom):
                sortie, appels = self.bac.lancer(
                    "/etc/x",
                    **{
                        f"FAUX_PARCOURS_{PROPRIETAIRE}": premier,
                        "FAUX_PARCOURS_0": second,
                    },
                )
                self.assertEqual(
                    sortie.returncode, 0, sortie.stdout + sortie.stderr
                )
                self.assertEqual([PROPRIETAIRE, "0"], parcours(appels))
                self.assertEqual(
                    [PROPRIETAIRE], [uid_de(a) for a in ecritures(appels)]
                )
                self.assertIn(f"{canon}", ecritures(appels)[0])

    def test_pas_de_second_parcours_quand_root_a_deja_parcouru(self):
        """Un propriétaire du code root parcourt déjà sous root : un seul
        parcours."""
        canon = self.bac.racine / "x"
        sortie, appels = self.bac.lancer(
            "/etc/x",
            FAUX_PROPRIETAIRE="0",
            FAUX_PARCOURS_0=reponse("ok", "0", "755", "1", "/etc", canon),
        )
        self.assertEqual(sortie.returncode, 0, sortie.stdout + sortie.stderr)
        self.assertEqual(["0"], parcours(appels))
        self.assertEqual(["0"], [uid_de(a) for a in ecritures(appels)])

    def test_sans_destination_le_fichier_va_dans_home_odoo(self):
        canon = self.bac.racine / "home_odoo"
        sortie, appels = self.bac.lancer(
            None,
            **{
                f"FAUX_PARCOURS_{PROPRIETAIRE}": reponse(
                    "ok", PROPRIETAIRE, "700", "0", "/home/odoo", canon
                )
            },
        )
        self.assertEqual(sortie.returncode, 0, sortie.stdout + sortie.stderr)
        self.assertTrue(any(a.endswith(" /home/odoo") for a in appels), appels)
        self.assertEqual(self.bac.contenu, (canon / "source.bin").read_bytes())

    def test_une_reponse_non_entiere_est_refusee(self):
        for champs in (
            ("ok", "0", "7a5", "1", "/x", "/x"),
            ("ok", "$(id)", "755", "1", "/x", "/x"),
            ("ok", "0"),
            ("ok", "0", "755", "1", "/x", "relatif/x"),
        ):
            with self.subTest(champs=champs):
                sortie, appels = self.bac.lancer(
                    "/x",
                    **{f"FAUX_PARCOURS_{PROPRIETAIRE}": reponse(*champs)},
                )
                self.assertEqual(sortie.returncode, 1)
                self.assertIn("unexpected answer", sortie.stdout)
                self.assertEqual([], ecritures(appels))


if __name__ == "__main__":
    unittest.main()
