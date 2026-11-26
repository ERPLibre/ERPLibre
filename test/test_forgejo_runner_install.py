#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""script/forgejo/install_forgejo_runner.sh, sans forge ni réseau.

Le script est exécuté sur ses chemins de refus — architecture, version,
somme de contrôle —, qui précèdent toute élévation de privilège ; ses
fonctions sont sourcées seules (EL_RUNNER_LIB_ONLY=1). Le reste est gardé
par la lecture de son texte : le secret ne passe jamais en argument, chaque
écriture est précédée d'une comparaison, et les redémarrages sont
conditionnels. Les commandes externes sont des doublures sur le PATH ;
« sudo » refuse en le disant. Les valeurs sont inventées.
"""

import os
import pathlib
import re
import subprocess
import tempfile
import unittest

import yaml

SCRIPT = (
    pathlib.Path(__file__).resolve().parent.parent
    / "script/forgejo/install_forgejo_runner.sh"
)
SUDO_REFUSE = {"sudo": 'echo "sudo refusé par le test : $*" >&2; exit 1'}
# Une doublure de curl qui écrit un fichier pour « -o », et échoue sur les
# chemins de `ECHOUE` (motif shell) ; chaque appel est noté dans $JOURNAL.
CURL = r"""
echo "$*" >> "$JOURNAL"
dest=""; url=""
while [ $# -gt 0 ]; do
    case "$1" in -o) dest="$2"; shift ;; http*) url="$1" ;; esac
    shift
done
case "$url" in $ECHOUE) exit 22 ;; esac
[ -n "$dest" ] && echo contenu > "$dest"
exit 0
"""


def lancer(stubs, env=None, args=()):
    stubs = {**SUDO_REFUSE, **stubs}
    with tempfile.TemporaryDirectory() as tmp:
        dossier = pathlib.Path(tmp) / "bin"
        dossier.mkdir()
        for nom, corps in stubs.items():
            (dossier / nom).write_text(f"#!/bin/bash\n{corps}\n")
            (dossier / nom).chmod(0o755)
        journal = pathlib.Path(tmp) / "curl.log"
        journal.touch()
        res = subprocess.run(
            ["bash", str(SCRIPT), *args],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PATH": f"{dossier}:/usr/bin:/bin",
                "JOURNAL": str(journal),
                "ECHOUE": "__rien__",
                **(env or {}),
            },
            timeout=120,
        )
        res.curl = journal.read_text()
    return res


def bash_lib(code, env=None):
    """Exécute `code` après avoir sourcé le script en bibliothèque."""
    return subprocess.run(
        ["bash", "-c", f'EL_RUNNER_LIB_ONLY=1 . "$0"\n{code}', str(SCRIPT)],
        capture_output=True,
        text=True,
        env=dict(os.environ, **(env or {})),
        timeout=30,
    )


class TestLeScript(unittest.TestCase):
    def test_executable_and_valid_shell(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        res = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_help_lists_every_setting(self):
        res = lancer({}, args=["--help"])
        self.assertEqual(res.returncode, 0, res.stderr)
        reglages = set(
            re.findall(r"\$\{(FORGEJO_RUNNER_[A-Z]+)", SCRIPT.read_text())
        )
        self.assertGreaterEqual(len(reglages), 7)
        for nom in reglages | {"FORGEJO_HTTP_PORT", "FORGEJO_USER"}:
            self.assertIn(nom, res.stdout)
        self.assertIn("FORGEJO_RUNNER_PACKAGES", reglages)
        # L'aide est l'en-tête entier, jusqu'à sa dernière ligne, et rien
        # du code qui suit.
        self.assertIn("binaire remplacé depuis.", res.stdout)
        self.assertNotIn("Fonctions sans effet", res.stdout)
        self.assertNotIn("#!/usr/bin/env", res.stdout)

    def test_unpublished_architectures_are_refused_by_name(self):
        for arch in ("s390x", "armv7l"):
            res = lancer({"uname": f"echo {arch}"})
            self.assertNotEqual(res.returncode, 0)
            self.assertIn(arch, res.stderr)
            self.assertNotIn("sudo refusé", res.stderr)

    def test_an_unreachable_feed_names_the_version(self):
        res = lancer({"uname": "echo x86_64", "curl": "exit 7"})
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Version", res.stderr)

    def test_a_pinned_version_never_reads_the_feed(self):
        res = lancer(
            {"uname": "echo x86_64", "curl": CURL},
            env={"FORGEJO_RUNNER_VERSION": "9.9.9", "ECHOUE": "*.sha256"},
        )
        self.assertNotIn("releases/latest", res.curl)
        self.assertIn("9.9.9", res.stdout + res.stderr)

    def test_a_missing_checksum_stops_before_any_install(self):
        res = lancer(
            {"uname": "echo x86_64", "curl": CURL},
            env={"FORGEJO_RUNNER_VERSION": "9.9.9", "ECHOUE": "*.sha256"},
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("somme de contrôle introuvable", res.stderr)
        self.assertNotIn("sudo refusé", res.stderr)

    def test_a_wrong_checksum_stops_too(self):
        res = lancer(
            {"uname": "echo x86_64", "curl": CURL},
            env={"FORGEJO_RUNNER_VERSION": "9.9.9"},
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("somme de contrôle invalide", res.stderr)

    def test_a_capacity_other_than_one_is_refused(self):
        """ci_venv.sh élague des venvs qu'un job concurrent utiliserait
        encore : une capacité de plus d'un job est refusée d'emblée."""
        for capacite in ("2", "0", "x"):
            with self.subTest(capacite=capacite):
                res = lancer(
                    {"uname": "echo x86_64", "curl": CURL},
                    env={"FORGEJO_RUNNER_CAPACITY": capacite},
                )
                self.assertNotEqual(res.returncode, 0)
                self.assertIn("FORGEJO_RUNNER_CAPACITY", res.stderr)
                self.assertIn("ci_venv.sh", res.stderr)
                self.assertNotIn("sudo refusé", res.stderr)
                self.assertEqual(res.curl, "")

    def test_a_label_that_would_break_the_yaml_is_refused(self):
        res = lancer(
            {"uname": "echo x86_64"},
            env={"FORGEJO_RUNNER_LABEL": 'x"\n  y: z'},
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("FORGEJO_RUNNER_LABEL", res.stderr)


class TestLesFonctions(unittest.TestCase):
    SECRET = "0123456789abcdef0123456789abcdef01234567"
    UUID = "01234567-89ab-cdef-0123-456789abcdef"

    def test_valid_secrets(self):
        for valeur, attendu in (
            (self.SECRET, 0),
            (self.SECRET[:-1], 1),
            (self.SECRET.upper().replace("0", "A"), 1),
            ("z" * 40, 1),
            ("", 1),
        ):
            res = bash_lib('secret_valide "$S"', {"S": valeur})
            self.assertEqual(res.returncode, attendu, valeur)

    def config(self, secret):
        res = bash_lib(
            'config_runner "http://127.0.0.1:3000/" "$U" "$S" erplibre-host'
            " 2 /var/lib/forgejo-runner",
            {"U": self.UUID, "S": secret},
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout

    def test_the_runner_config(self):
        texte = self.config(self.SECRET)
        conf = yaml.safe_load(texte)
        self.assertEqual(conf["runner"]["labels"], ["erplibre-host:host"])
        self.assertEqual(conf["runner"]["capacity"], 2)
        self.assertEqual(
            conf["runner"]["envs"]["EL_CI_CACHE"],
            "/var/lib/forgejo-runner/cache",
        )
        self.assertEqual(
            conf["host"]["workdir_parent"], "/var/lib/forgejo-runner/work"
        )
        self.assertIs(conf["cache"]["enabled"], False)
        self.assertEqual(
            conf["server"]["connections"]["forgejo"],
            {
                "url": "http://127.0.0.1:3000/",
                "uuid": self.UUID,
                "token": self.SECRET,
            },
        )

    def test_a_digit_only_secret_stays_a_string(self):
        for secret in ("1" * 40, "1" * 20 + "e" + "1" * 19):
            conf = yaml.safe_load(self.config(secret))
            self.assertEqual(
                conf["server"]["connections"]["forgejo"]["token"], secret
            )

    def test_the_installer_reads_its_own_token_back(self):
        corps = SCRIPT.read_text()
        lecteur = re.search(r"awk '(/\^ \*token:/[^']*)'", corps).group(1)
        res = subprocess.run(
            ["awk", lecteur],
            input=self.config(self.SECRET),
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.stdout.strip(), self.SECRET)

    def position(self, aide):
        with tempfile.TemporaryDirectory() as tmp:
            faux = pathlib.Path(tmp) / "forgejo"
            faux.write_text(f"#!/bin/bash\necho '{aide}'\n")
            faux.chmod(0o755)
            sudo = pathlib.Path(tmp) / "sudo"
            sudo.write_text('#!/bin/bash\nshift 2\nexec "$@"\n')
            sudo.chmod(0o755)
            res = bash_lib(
                f'FORGEJO_USER=git FORGEJO_BIN="{faux}" position_config',
                {"PATH": f"{tmp}:/usr/bin:/bin"},
            )
        return res.stdout.strip()

    def perime(self, main_pid, exe):
        """`runner_perime` avec un systemctl qui rend `main_pid` et un
        readlink qui rend `exe`, derrière un sudo qui exécute tel quel."""
        with tempfile.TemporaryDirectory() as tmp:
            for nom, corps in (
                ("systemctl", f"echo '{main_pid}'"),
                ("sudo", 'exec "$@"'),
                ("readlink", f"echo '{exe}'"),
            ):
                faux = pathlib.Path(tmp) / nom
                faux.write_text(f"#!/bin/bash\n{corps}\n")
                faux.chmod(0o755)
            res = bash_lib(
                "runner_perime /usr/local/bin/forgejo-runner",
                {"PATH": f"{tmp}:/usr/bin:/bin"},
            )
        return res.returncode == 0

    def test_a_daemon_running_a_replaced_binary_is_stale(self):
        bin_ = "/usr/local/bin/forgejo-runner"
        self.assertFalse(self.perime(1234, bin_))
        self.assertTrue(self.perime(1234, bin_ + " (deleted)"))
        self.assertTrue(self.perime(1234, "/opt/ancien/forgejo-runner"))
        self.assertFalse(self.perime(0, bin_ + " (deleted)"))
        self.assertFalse(self.perime(1234, ""))

    def test_the_config_position_is_probed(self):
        self.assertEqual(
            self.position("--config value  --secret-file"), "apres"
        )
        self.assertEqual(self.position("--name value --secret-file"), "avant")


class TestLesPaquets(unittest.TestCase):
    """Les outils que les jobs appellent sur l'hôte : make, psql, openssl,
    git. Le gestionnaire, dpkg-query, rpm et sudo sont des doublures ; sudo
    note sa ligne de commande dans $JOURNAL au lieu de l'exécuter."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bin = pathlib.Path(tmp.name) / "bin"
        self.bin.mkdir()
        self.journal = pathlib.Path(tmp.name) / "sudo.log"
        self.journal.touch()
        self.doublure("sudo", 'echo "$*" >> "$JOURNAL"')

    def doublure(self, nom, corps):
        (self.bin / nom).write_text(f"#!/bin/bash\n{corps}\n")
        (self.bin / nom).chmod(0o755)

    def lib(self, code):
        # /bin et /usr/bin portent bash, dirname, tr… mais aussi peut-être
        # un vrai gestionnaire : seules les doublures et un dossier d'outils
        # sans gestionnaire sont sur le PATH.
        outils = self.bin.parent / "outils"
        outils.mkdir(exist_ok=True)
        for nom in ("bash", "cat", "dirname"):
            cible = outils / nom
            if not cible.exists():
                cible.symlink_to(
                    subprocess.check_output(
                        ["bash", "-c", f"command -v {nom}"], text=True
                    ).strip()
                )
        return bash_lib(
            code,
            {"PATH": f"{self.bin}:{outils}", "JOURNAL": str(self.journal)},
        )

    def test_the_first_known_manager_is_found(self):
        self.assertEqual(self.lib("gestionnaire_paquets").stdout, "")
        self.doublure("pacman", "exit 0")
        self.assertEqual(self.lib("gestionnaire_paquets").stdout, "pacman\n")
        self.doublure("dnf", "exit 0")
        self.assertEqual(self.lib("gestionnaire_paquets").stdout, "dnf\n")
        self.doublure("apt-get", "exit 0")
        self.assertEqual(self.lib("gestionnaire_paquets").stdout, "apt-get\n")

    def test_every_manager_gets_the_four_tools(self):
        for gestionnaire, psql in (
            ("apt-get", "postgresql-client"),
            ("dnf", "postgresql"),
            ("zypper", "postgresql"),
            ("pacman", "postgresql"),
        ):
            with self.subTest(gestionnaire=gestionnaire):
                res = self.lib(f"paquets_ci {gestionnaire}")
                self.assertEqual(
                    res.stdout.split(), ["make", psql, "openssl", "git"]
                )
        self.assertEqual(self.lib("paquets_ci inconnu").stdout, "")

    def test_only_what_is_missing_is_installed(self):
        """dpkg-query dit git et make installés : seuls le client
        PostgreSQL et openssl partent, après une relecture des index."""
        self.doublure(
            "dpkg-query",
            'case "${@: -1}" in git|make) printf "install ok installed";;'
            " *) exit 1;; esac",
        )
        res = self.lib(
            "prerequis_ci apt-get make postgresql-client openssl git"
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.split(), ["postgresql-client", "openssl"])
        lignes = self.journal.read_text().splitlines()
        self.assertEqual(len(lignes), 2, lignes)
        self.assertIn("apt-get", lignes[0])
        self.assertIn(" update", lignes[0])
        self.assertIn("DEBIAN_FRONTEND=noninteractive", lignes[1])
        self.assertTrue(
            lignes[1].endswith(
                "install -y --no-install-recommends"
                " postgresql-client openssl"
            ),
            lignes[1],
        )

    def test_a_second_pass_calls_no_manager(self):
        self.doublure("dpkg-query", 'printf "install ok installed"')
        self.doublure("rpm", "exit 0")
        self.doublure("pacman", "exit 0")
        for gestionnaire in ("apt-get", "dnf", "zypper", "pacman"):
            with self.subTest(gestionnaire=gestionnaire):
                res = self.lib(
                    f"prerequis_ci {gestionnaire} make postgresql openssl git"
                )
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertEqual(res.stdout, "")
        self.assertEqual(self.journal.read_text(), "")

    def test_a_removed_package_half_known_to_dpkg_is_missing(self):
        """« deinstall ok config-files » : le paquet a été retiré, seule sa
        configuration reste ; il est à reposer."""
        self.doublure("dpkg-query", 'printf "deinstall ok config-files"')
        res = self.lib("prerequis_ci apt-get make")
        self.assertEqual(res.stdout.split(), ["make"])

    def test_the_other_managers_install_non_interactively(self):
        self.doublure("rpm", "exit 1")
        self.doublure("pacman", "exit 1")
        for gestionnaire, attendu in (
            ("dnf", "dnf install -y -q make"),
            ("zypper", "zypper --non-interactive --quiet install make"),
            ("pacman", "pacman -S --needed --noconfirm make"),
        ):
            with self.subTest(gestionnaire=gestionnaire):
                self.journal.write_text("")
                res = self.lib(f"prerequis_ci {gestionnaire} make")
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertEqual(self.journal.read_text().strip(), attendu)

    def test_a_refused_install_fails(self):
        self.doublure("sudo", "exit 100")
        self.doublure("rpm", "exit 1")
        res = self.lib("prerequis_ci dnf make")
        self.assertNotEqual(res.returncode, 0)

    def test_a_package_list_that_would_inject_is_refused(self):
        for valeur in ("make; rm -rf /", "make $(id)", "make\ngit", "*"):
            with self.subTest(valeur=valeur):
                res = lancer(
                    {"uname": "echo x86_64", "curl": CURL},
                    env={"FORGEJO_RUNNER_PACKAGES": valeur},
                )
                self.assertNotEqual(res.returncode, 0)
                self.assertIn("FORGEJO_RUNNER_PACKAGES", res.stderr)
                self.assertNotIn("sudo refusé", res.stderr)
                self.assertEqual(res.curl, "")


class TestLesGardes(unittest.TestCase):
    def setUp(self):
        self.corps = SCRIPT.read_text()
        self.code = "\n".join(
            ligne
            for ligne in self.corps.splitlines()
            if ligne.strip() and not ligne.lstrip().startswith("#")
        )

    def test_the_secret_never_goes_through_argv(self):
        self.assertIn("--secret-file", self.code)
        self.assertIsNone(re.search(r"--secret[ =]", self.code))
        self.assertNotIn("--secret-stdin", self.code)

    def test_the_package_manager_only_installs(self):
        """Le gestionnaire de paquets pose les outils des jobs, rien
        d'autre : ni retrait, ni mise à niveau du système."""
        self.assertIsNone(
            re.search(
                r"\b(remove|purge|autoremove|upgrade|dist-upgrade|erase)\b"
                r"|-Syu|-R[ns]",
                self.code,
            )
        )
        self.assertIn('prerequis_ci "$GESTIONNAIRE"', self.code)

    def test_the_job_tools_precede_the_account(self):
        """Les outils sont posés après la vérification du binaire, avant le
        compte et le démon qui lancera les jobs."""
        outils = self.code.index('prerequis_ci "$GESTIONNAIRE"')
        self.assertLess(self.code.index("generate-config"), outils)
        self.assertLess(outils, self.code.index("useradd"))

    def test_no_privileged_group(self):
        self.assertNotIn("usermod", self.code)
        self.assertIsNone(re.search(r"-G\s*sudo|\bsudo:", self.code))

    def test_every_write_is_compared_first(self):
        for cible in ('"$FORGEJO_CONF"', '"$CONF"', '"$UNIT"'):
            comparaison = self.code.index("cmp -s")
            ecriture = re.search(
                r"sudo install -m 0\d{3}[^\n]*" + re.escape(cible) + "$",
                self.code,
                re.M,
            )
            self.assertIsNotNone(ecriture, cible)
            precedent = self.code.rfind("cmp -s", 0, ecriture.start())
            self.assertGreaterEqual(precedent, comparaison, cible)
            self.assertIn(cible, self.code[precedent : ecriture.start()])

    def test_secret_bearing_temps_are_made_by_root(self):
        self.assertIn("t=$(sudo mktemp)", self.code)
        self.assertEqual(self.code.count("$(temp_root)"), 2)
        self.assertIn('sudo test -f "$FORGEJO_CONF"', self.code)
        self.assertIn('sudo cat "$FORGEJO_CONF"', self.code)

    def test_a_stale_daemon_owes_a_restart(self):
        """Un passage interrompu entre la pose du binaire et le redémarrage
        laisse le démon sur l'ancien fichier : le passage suivant le voit
        et doit le relancer."""
        garde = self.code.index('runner_perime "$BIN"')
        self.assertLess(
            self.code.index('sudo install -m 0755 "$src" "$BIN"'), garde
        )
        self.assertIn("CHANGED_RUNNER=1", self.code[garde : garde + 120])
        self.assertLess(garde, self.code.index('if [ "$CHANGED_RUNNER" = 1 ]'))

    def test_the_capability_check_precedes_app_ini_and_registration(self):
        """Un binaire sans server.connections s'arrête avant d'éditer
        app.ini et d'enregistrer un runner dont le secret ne serait jamais
        sauvegardé."""
        verification = self.code.index("generate-config")
        self.assertEqual(self.code.count("generate-config"), 1)
        self.assertLess(
            self.code.index('sudo install -m 0755 "$src" "$BIN"'),
            verification,
        )
        for geste in (
            "ini_poser actions ENABLED",
            '--secret-file "$f"',
            "useradd",
        ):
            self.assertLess(verification, self.code.index(geste), geste)

    def test_restarts_are_conditional(self):
        self.assertIn('if [ "$CHANGED_FORGEJO" = 1 ]', self.code)
        self.assertIn('if [ "$CHANGED_RUNNER" = 1 ]', self.code)
        self.assertNotIn("enable --now", self.code)

    def test_the_unit_is_hardened(self):
        for ligne in (
            "NoNewPrivileges=yes",
            "ProtectHome=yes",
            "EnvironmentFile=-/etc/environment",
            "PrivateTmp=yes",
        ):
            self.assertIn(ligne, self.code)

    def test_a_single_exit_trap(self):
        self.assertEqual(len(re.findall(r"\btrap\b.*\bEXIT\b", self.code)), 1)


if __name__ == "__main__":
    unittest.main()
