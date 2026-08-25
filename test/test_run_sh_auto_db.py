#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""« ./run.sh » sans argument choisit sa base — sans jamais bloquer.

Le danger n'est pas le menu, c'est l'endroit où il ne doit PAS s'ouvrir.
`script/systemd/install_daemon.sh:34` écrit `ExecStart=/bin/bash …/run.sh`
sans le moindre argument, avec `Restart=always` et `RestartSec=5` : une
question posée là ne serait pas une pause, ce serait une boucle de
redémarrage, chacun repayant 0,8 s d'import Odoo.

D'où la forme des épreuves : on mesure d'abord ce qui NE doit pas arriver
— la sonde jamais lancée, aucun `-d` injecté, la ligne d'arguments intacte
à l'octet — et seulement ensuite le menu, derrière un vrai
pseudo-terminal, seul moyen de rendre `-t 0` et `-t 2` vrais ensemble.
"""

import os
import pathlib
import pty
import select
import shutil
import subprocess
import tempfile
import time
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "run.sh"
LIB = RACINE / "script" / "database" / "lib_db_select.sh"

DELAI = 30

# Le bouchon joue les DEUX rôles : la sonde (`db --list`) et le lancement
# d'Odoo. `$1` vaut « db » dans un cas et « -c » dans l'autre, le
# discriminant est donc fiable.
#
# `[%s]` par argument, et non `$*` : c'est ce format qui prouve qu'un
# argument vide et un argument à espaces traversent intacts. Une chaîne
# recollée les aurait perdus sans que rien ne le dise.
BOUCHON = """#!/usr/bin/env bash
case "$1" in
  db) touch ./SONDE_APPELEE; %s ;;
  *)  printf 'ARGS:'; printf '[%%s]' "$@"; printf '\\n' ;;
esac
"""

TROIS_BASES = BOUCHON % "printf '%s\\n' _cache_odoo18.0_base demo prod"
UNE_BASE = BOUCHON % "printf '%s\\n' _cache_odoo18.0_base demo"
QUE_DU_CACHE = BOUCHON % "printf '%s\\n' _cache_odoo18.0_base"
AUCUNE_BASE = BOUCHON % ":"
# Le cas qui compte pour la fusion des flux : la sonde RÉUSSIT, et parle
# quand même sur stderr. Le CLI « db » n'appelle jamais parse_config(),
# donc aucun journal n'est configuré et tout enregistrement part nu par là.
SONDE_BAVARDE = BOUCHON % (
    "printf 'WARNING odoo.modules.module: module xyz not loadable\\n' >&2;"
    " printf '%s\\n' demo"
)
SONDE_CASSEE = BOUCHON % (
    "printf 'Traceback (most recent call last):\\n"
    '  File \\"x.py\\", line 1\\nOperationalError\\n\' >&2; exit 1'
)


class Banc:
    """Un dépôt jetable : run.sh ne fait aucun `cd` et résout tout du cwd."""

    def __init__(
        self, bouchon=TROIS_BASES, config="[options]\ndb_name = False\n"
    ):
        self.dossier = tempfile.mkdtemp(prefix="el_run_sh_")
        chemin = pathlib.Path(self.dossier)
        (chemin / "script" / "database").mkdir(parents=True)
        shutil.copy(SCRIPT, chemin / "run.sh")
        shutil.copy(LIB, chemin / "script" / "database" / "lib_db_select.sh")
        (chemin / "config.conf").write_text(config, encoding="utf-8")
        stub = chemin / "odoo_bin.sh"
        stub.write_text(bouchon, encoding="utf-8")
        stub.chmod(0o755)
        self.chemin = chemin

    def sonde_appelee(self):
        return (self.chemin / "SONDE_APPELEE").exists()

    def lancer(self, *argv, env=None, entree=None):
        milieu = dict(os.environ)
        milieu.pop("ODOO_MODE_TEST", None)
        milieu.pop("ODOO_MODE_COVERAGE", None)
        if env:
            milieu.update(env)
        return subprocess.run(
            ["./run.sh", *argv],
            cwd=self.dossier,
            capture_output=True,
            text=True,
            timeout=DELAI,
            input=entree if entree is not None else "",
            env=milieu,
        )

    def conduire(self, *argv, frappe=""):
        """Derrière un vrai pseudo-terminal — le seul `-t 0` et `-t 2` vrais."""
        maitre, esclave = pty.openpty()
        proc = subprocess.Popen(
            ["./run.sh", *argv],
            cwd=self.dossier,
            stdin=esclave,
            stdout=esclave,
            stderr=esclave,
            close_fds=True,
        )
        os.close(esclave)
        if frappe:
            time.sleep(0.4)
            os.write(maitre, frappe.encode())
        morceaux = []
        # ÉCHÉANCE sur la LECTURE, pas seulement sur l'attente du fils.
        # `os.read` sur un pseudo-terminal bloque tant que le maître est
        # ouvert : si une régression ouvre un menu là où le test ne tape
        # rien, la suite entière pend au lieu d'échouer. Mesuré — une
        # mutation du filtre « _cache_ » a fait durer 600 s.
        limite = time.monotonic() + DELAI
        depasse = False
        try:
            while True:
                reste = limite - time.monotonic()
                if reste <= 0:
                    depasse = True
                    break
                pret, _, _ = select.select([maitre], [], [], reste)
                if not pret:
                    depasse = True
                    break
                try:
                    bloc = os.read(maitre, 4096)
                except OSError:
                    break
                if not bloc:
                    break
                morceaux.append(bloc)
        finally:
            if depasse:
                proc.kill()
            code = proc.wait(timeout=DELAI)
            os.close(maitre)
        texte = b"".join(morceaux).decode(errors="replace").replace("\r", "")
        if depasse:
            raise AssertionError(
                f"run.sh n'a pas rendu la main en {DELAI} s — il attend"
                f" sans doute une réponse. Vu :\n{texte}"
            )
        return code, texte

    def nettoyer(self):
        shutil.rmtree(self.dossier, ignore_errors=True)


class BancTest(unittest.TestCase):
    bouchon = TROIS_BASES
    config = "[options]\ndb_name = False\n"

    def setUp(self):
        self.banc = Banc(self.bouchon, self.config)
        self.addCleanup(self.banc.nettoyer)


class TestTheScriptsAreValid(unittest.TestCase):
    def test_both_files_parse(self):
        for chemin in (SCRIPT, LIB):
            with self.subTest(chemin=chemin.name):
                res = subprocess.run(
                    ["bash", "-n", str(chemin)],
                    capture_output=True,
                    text=True,
                    timeout=DELAI,
                )
                self.assertEqual(0, res.returncode, res.stderr)

    def test_run_sh_is_still_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK), SCRIPT)

    def test_the_library_announces_itself_sourceable(self):
        # Convention du dépôt : lib_pip_provider.sh, lib_python_provider.sh.
        self.assertIn(
            "Bibliothèque SOURÇABLE", LIB.read_text(encoding="utf-8")
        )

    def test_the_library_sets_no_shell_option(self):
        # Une bibliothèque sourcée imposerait ses options à run.sh, qui lit
        # $ODOO_MODE_TEST sans valeur par défaut : `set -u` le tuerait.
        for ligne in LIB.read_text(encoding="utf-8").splitlines():
            self.assertFalse(
                ligne.strip().startswith("set -"), f"« {ligne.strip()} »"
            )


class TestNothingHappensWhereNobodyAsked(BancTest):
    """Le contrat de non-régression : systemd, la migration, les scripts."""

    def test_zero_argument_without_a_terminal_never_probes(self):
        # Le cas systemd. La sonde coûte 0,8 s et se paierait à chaque
        # redémarrage d'un service en boucle.
        res = self.banc.lancer()
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertFalse(self.banc.sonde_appelee(), res.stderr)

    def test_zero_argument_without_a_terminal_injects_nothing(self):
        res = self.banc.lancer()
        self.assertIn("ARGS:", res.stdout)
        self.assertNotIn("[-d]", res.stdout)

    def test_the_forwarded_line_is_byte_for_byte_what_it_always_was(self):
        res = self.banc.lancer()
        self.assertEqual(
            "ARGS:[-c][./config.conf][--limit-time-real][99999]"
            "[--limit-time-cpu][99999][--limit-memory-hard=0]",
            res.stdout.strip(),
            res.stderr,
        )

    def test_an_empty_argument_and_one_with_spaces_survive(self):
        # « ./run.sh -d $(bd) » de make.robotlibre produit un -d vide dès
        # que bd n'est pas défini : reconstruire la ligne le perdrait.
        res = self.banc.lancer("--log-handler", "a b", "-d", "")
        self.assertIn("[--log-handler][a b][-d][]", res.stdout, res.stderr)

    def test_the_test_mode_branch_behaves_the_same(self):
        res = self.banc.lancer(env={"ODOO_MODE_TEST": "true"})
        self.assertIn("[--test-enable]", res.stdout, res.stderr)
        self.assertNotIn("[-d]", res.stdout)
        self.assertFalse(self.banc.sonde_appelee())

    def test_the_test_mode_branch_also_receives_the_chosen_database(self):
        # Deux branches lancent Odoo. Oublier l'une des deux ne se voit
        # nulle part ailleurs : « make test » passerait sans base et l'on
        # chercherait la cause dans Odoo.
        banc = Banc(UNE_BASE, self.config)
        self.addCleanup(banc.nettoyer)
        res = banc.lancer("--auto-erplibre", env={"ODOO_MODE_TEST": "true"})
        self.assertIn("[--test-enable]", res.stdout, res.stderr)
        self.assertIn("[-d][demo]", res.stdout, res.stderr)

    def test_a_database_already_named_disarms_everything(self):
        # Les quatre formes qu'optparse accepte, plus « -d » nu — ce que
        # produit « ./run.sh -d $(bd) » quand bd n'est pas défini. On ne
        # complète jamais le choix de l'appelant, et l'on ne paie pas la
        # sonde pour rien.
        for forme in (
            ["-d", "demo"],
            ["-ddemo"],
            ["--database", "demo"],
            ["--database=demo"],
            ["-d"],
        ):
            with self.subTest(forme=" ".join(forme)):
                banc = Banc(self.bouchon, self.config)
                self.addCleanup(banc.nettoyer)
                res = banc.lancer("--auto-erplibre", *forme)
                self.assertFalse(banc.sonde_appelee(), res.stderr)
                # Rien d'ajouté : la ligne se termine sur ce que l'appelant
                # a écrit, sans « -d » de plus derrière.
                attendu = "".join(f"[{arg}]" for arg in forme)
                self.assertTrue(
                    res.stdout.strip().endswith(attendu), res.stdout
                )


class TestTheExitContractIsUnchanged(unittest.TestCase):
    """run.sh convertit tout échec d'Odoo en 1, et laisse passer le succès.

    L'analyse des options a inséré du code ENTRE le lancement d'Odoo et le
    `retVal=$?` de la fin. Des commentaires ne touchent pas `$?` — vérifié
    — mais une ligne exécutable ajoutée là volerait le code de sortie sans
    que rien ne le dise.
    """

    def banc_qui_sort(self, code):
        b = Banc(TROIS_BASES)
        self.addCleanup(b.nettoyer)
        (b.chemin / "odoo_bin.sh").write_text(
            f"#!/usr/bin/env bash\nexit {code}\n", encoding="utf-8"
        )
        (b.chemin / "odoo_bin.sh").chmod(0o755)
        return b

    def test_a_failing_odoo_becomes_one(self):
        res = self.banc_qui_sort(7).lancer("--workers", "0")
        self.assertEqual(1, res.returncode, res.stderr)

    def test_a_successful_odoo_stays_zero(self):
        res = self.banc_qui_sort(0).lancer("--workers", "0")
        self.assertEqual(0, res.returncode, res.stderr)


class TestTheTwoOptionsNeverReachOdoo(BancTest):
    def test_both_are_stripped(self):
        res = self.banc.lancer(
            "--auto-erplibre", "--no-cli-erplibre", "--workers", "0"
        )
        self.assertNotIn("auto-erplibre", res.stdout, res.stdout)
        self.assertNotIn("no-cli-erplibre", res.stdout, res.stdout)
        self.assertIn("[--workers][0]", res.stdout)

    def test_a_neighbouring_option_is_not_eaten(self):
        # Une correspondance trop large avalerait des options d'Odoo.
        for voisine in (
            "--auto-erplibr",
            "--auto",
            "--no-cli",
            "--auto-erplibrex",
        ):
            with self.subTest(voisine=voisine):
                banc = Banc(self.bouchon, self.config)
                self.addCleanup(banc.nettoyer)
                res = banc.lancer(voisine)
                self.assertIn(f"[{voisine}]", res.stdout, res.stderr)

    def test_odoo_never_sees_them_even_when_they_do_something(self):
        banc = Banc(UNE_BASE, self.config)
        self.addCleanup(banc.nettoyer)
        res = banc.lancer("--auto-erplibre")
        self.assertIn("[-d][demo]", res.stdout, res.stderr)
        self.assertNotIn("erplibre]", res.stdout)


class TestWhatTheProbeReturns(unittest.TestCase):
    def banc(self, bouchon, config="[options]\ndb_name = False\n"):
        b = Banc(bouchon, config)
        self.addCleanup(b.nettoyer)
        return b

    def test_a_single_database_is_taken_without_asking(self):
        banc = self.banc(UNE_BASE)
        res = banc.lancer("--auto-erplibre")
        self.assertIn("[-d][demo]", res.stdout, res.stderr)

    def test_template_databases_are_not_candidates(self):
        # `_cache_…` est une base-modèle. Sur une machine qui vient de
        # tester, ce peut être la seule : sans filtre, la règle « une
        # seule base » démarrerait Odoo sur un modèle.
        banc = self.banc(QUE_DU_CACHE)
        res = banc.lancer("--auto-erplibre")
        self.assertNotIn("[-d]", res.stdout, res.stderr)
        self.assertNotIn("_cache_", res.stdout)
        self.assertEqual(0, res.returncode)

    def test_no_database_at_all_starts_anyway(self):
        banc = self.banc(AUCUNE_BASE)
        res = banc.lancer("--auto-erplibre")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertNotIn("[-d]", res.stdout)
        self.assertIn("ARGS:", res.stdout)

    def test_a_warning_on_stderr_never_becomes_a_database_name(self):
        # Une sonde qui RÉUSSIT en parlant sur stderr : c'est là que la
        # fusion des flux se voit. Avec `2>&1`, l'avertissement devient
        # une seconde « base », la règle « une seule » ne s'applique plus
        # et l'on ouvre un menu pour un texte de journal. Le défaut exact
        # que script/database/db_drop_all.py porte encore.
        banc = self.banc(SONDE_BAVARDE)
        res = banc.lancer("--auto-erplibre")
        self.assertIn("[-d][demo]", res.stdout, res.stdout)
        self.assertNotIn("WARNING", res.stdout, res.stdout)

    def test_a_failing_probe_never_becomes_a_database_name(self):
        # Fusionner stdout et stderr ferait de chaque ligne d'une trace un
        # nom de base — le défaut que database_manager.py a déjà corrigé.
        banc = self.banc(SONDE_CASSEE)
        res = banc.lancer("--auto-erplibre")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertNotIn("[-d]", res.stdout)
        self.assertNotIn("Traceback", res.stdout)
        self.assertNotIn("OperationalError", res.stdout)
        # …et le message doit dire « je n'ai pas pu lire », pas « il n'y
        # en a pas ». Les deux mènent au même démarrage, mais pas au même
        # endroit où chercher : PostgreSQL à terre n'est pas une machine
        # neuve. Le CLI d'Odoo confond déjà les deux en rendant 0 sur une
        # liste vide ; au moins ne pas ajouter notre propre confusion là
        # où le code de sortie, lui, sait.
        self.assertIn("lister", res.stderr, res.stderr)
        self.assertNotIn("Aucune base", res.stderr, res.stderr)

    def test_an_empty_list_says_something_else_than_a_failure(self):
        banc = self.banc(AUCUNE_BASE)
        res = banc.lancer("--auto-erplibre")
        self.assertIn("Aucune base", res.stderr, res.stderr)
        self.assertNotIn("lister", res.stderr, res.stderr)

    def test_a_configuration_that_names_its_database_is_left_alone(self):
        # L'option de ligne de commande l'emporte sur le fichier : injecter
        # écraserait en silence le choix d'une production.
        banc = self.banc(UNE_BASE, "[options]\ndb_name = prod\n")
        res = banc.lancer("--auto-erplibre")
        self.assertFalse(banc.sonde_appelee(), res.stderr)
        self.assertNotIn("[-d]", res.stdout)

    def test_db_name_false_is_not_a_name(self):
        for valeur in ("False", "false", "None"):
            with self.subTest(valeur=valeur):
                banc = self.banc(UNE_BASE, f"[options]\ndb_name = {valeur}\n")
                res = banc.lancer("--auto-erplibre")
                self.assertIn("[-d][demo]", res.stdout, res.stderr)


class TestWhenSeveralAndNoWayToAsk(unittest.TestCase):
    def banc(self, bouchon=TROIS_BASES):
        b = Banc(bouchon)
        self.addCleanup(b.nettoyer)
        return b

    def test_no_cli_erplibre_picks_nothing_and_says_so(self):
        banc = self.banc()
        res = banc.lancer("--auto-erplibre", "--no-cli-erplibre")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertNotIn("[-d]", res.stdout)
        self.assertIn("no-cli-erplibre", res.stderr, res.stderr)

    def test_no_terminal_picks_nothing_and_says_so(self):
        banc = self.banc()
        res = banc.lancer("--auto-erplibre")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertNotIn("[-d]", res.stdout)
        self.assertIn("2", res.stderr, res.stderr)

    def test_no_cli_erplibre_still_takes_a_lone_database(self):
        # L'option interdit le MENU, pas le choix. Sinon elle ferait
        # doublon avec « ne pas écrire --auto-erplibre ».
        banc = self.banc(UNE_BASE)
        res = banc.lancer("--auto-erplibre", "--no-cli-erplibre")
        self.assertIn("[-d][demo]", res.stdout, res.stderr)


class TestTheMenuBehindARealTerminal(unittest.TestCase):
    """Un pseudo-terminal : seul moyen de rendre `-t 0` et `-t 2` vrais."""

    def banc(self, bouchon=TROIS_BASES):
        b = Banc(bouchon)
        self.addCleanup(b.nettoyer)
        return b

    def test_zero_argument_opens_the_menu_and_honours_the_choice(self):
        code, texte = self.banc().conduire(frappe="2\n")
        self.assertEqual(0, code, texte)
        self.assertIn("[1] demo", texte)
        self.assertIn("[2] prod", texte)
        self.assertIn("[-d][prod]", texte)

    def test_the_template_database_is_absent_from_the_menu(self):
        code, texte = self.banc().conduire(frappe="1\n")
        self.assertNotIn("_cache_", texte, texte)
        self.assertIn("[-d][demo]", texte)

    def test_an_invalid_answer_asks_again_rather_than_guessing(self):
        code, texte = self.banc().conduire(frappe="9\nzzz\n1\n")
        self.assertEqual(0, code, texte)
        self.assertIn("[-d][demo]", texte)
        self.assertGreaterEqual(texte.count("Choix invalide"), 2, texte)

    def test_cancelling_starts_nothing_and_returns_130(self):
        # 130, pas 1 : run.sh réserve déjà 1 à « Odoo a échoué ».
        code, texte = self.banc().conduire(frappe="0\n")
        self.assertEqual(130, code, texte)
        self.assertNotIn("ARGS:", texte, texte)

    def test_end_of_input_is_a_refusal_not_a_hang(self):
        code, texte = self.banc().conduire(frappe="\x04")
        self.assertEqual(130, code, texte)
        self.assertNotIn("ARGS:", texte)

    def test_a_lone_database_asks_nothing_at_all(self):
        code, texte = self.banc(UNE_BASE).conduire(frappe="")
        self.assertEqual(0, code, texte)
        self.assertNotIn("Choix", texte, texte)
        self.assertIn("[-d][demo]", texte)

    def test_no_cli_erplibre_silences_the_menu_even_on_a_terminal(self):
        code, texte = self.banc().conduire("--no-cli-erplibre", frappe="")
        self.assertEqual(0, code, texte)
        self.assertNotIn("Choix", texte, texte)
        self.assertNotIn("[-d]", texte)


class TestTheLibraryOnItsOwn(unittest.TestCase):
    """Les fonctions, hors de run.sh, en remplaçant le garde de terminal."""

    def bash(self, corps, entree="", cwd=None):
        return subprocess.run(
            ["bash", "-c", f". {LIB}\n{corps}"],
            capture_output=True,
            text=True,
            timeout=DELAI,
            input=entree,
            cwd=cwd or str(RACINE),
        )

    def test_it_recognises_every_way_of_naming_a_database(self):
        for forme in ("-d x", "-dx", "--database x", "--database=x", "-d"):
            with self.subTest(forme=forme):
                res = self.bash(f"el_db_already_chosen {forme} && echo OUI")
                self.assertIn("OUI", res.stdout, res.stderr)

    def test_it_does_not_mistake_a_neighbour_for_a_database(self):
        for forme in ("--dev x", "--data-dir /tmp", "--db-filter x", "-u all"):
            with self.subTest(forme=forme):
                res = self.bash(f"el_db_already_chosen {forme} || echo NON")
                self.assertIn("NON", res.stdout, res.stderr)

    def test_the_menu_writes_nothing_to_stdout_but_the_name(self):
        # Le menu part sur stdout et il devient une partie du nom de base.
        res = self.bash("el_db_choose alpha zebre", entree="2\n")
        self.assertEqual("zebre", res.stdout.strip(), res.stdout)
        self.assertIn("[1] alpha", res.stderr)

    def test_the_guard_tests_stdin_and_stderr_not_stdout(self):
        # Dans `$( … )`, stdout est TOUJOURS un tube : tester -t 1 fermerait
        # le menu même devant un vrai terminal. Mesuré, puis corrigé.
        #
        # Les commentaires sont retirés : ils PARLENT de « -t 1 », et un
        # test qui les lit accuserait la documentation du défaut qu'elle
        # explique.
        texte = LIB.read_text(encoding="utf-8")
        debut = texte.index("_el_db_tty()")
        corps = "\n".join(
            ligne
            for ligne in texte[debut : texte.index("}", debut)].splitlines()
            if not ligne.strip().startswith("#")
        )
        self.assertIn("-t 0", corps)
        self.assertIn("-t 2", corps)
        self.assertNotIn("-t 1", corps)

    def test_the_guard_refuses_a_pipe_on_stderr(self):
        # Le cas du TUI de todo.py : stdout et stderr en tube, stdin intact.
        res = subprocess.run(
            ["bash", "-c", f". {LIB}\n_el_db_tty && echo ARME || echo REPOS"],
            capture_output=True,
            text=True,
            timeout=DELAI,
            cwd=str(RACINE),
        )
        self.assertIn("REPOS", res.stdout, res.stdout)


if __name__ == "__main__":
    unittest.main()
