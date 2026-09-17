#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les outils d'assistance et leur pré-configuration, dans une VM.

rtk, starship et UN agent — Claude Code ou opencode — sont des installateurs
amont, donc autant de curl vers l'extérieur lancés sur un SSH sans terminal.
Autour d'eux : trois paquets de terminal, les réglages git, les hooks du
dépôt, les commandes Claude et une entrée d'historique.

L'outil travaille en DEUX temps, et c'est le partage que ces tests gardent en
premier : ce qui s'installe avant le clone, puis ce qui a besoin du dépôt.

Ce que ces tests gardent :

- une seule autorité pour les URL amont : l'hôte et la VM posent les mêmes
  outils, et deux copies dérivent dès que l'amont en change une ;
- aucune pose ne peut PENDRE : « || true » couvre l'échec, pas l'attente
  d'une réponse que personne ne donnera ;
- toute ligne ajoutée à un fichier du HOME l'est UNE fois, sinon chaque
  redéploiement d'une même VM le rallonge ;
- la pré-configuration rend TOUJOURS 0 : c'est l'installation qui porte le
  verdict de la VM, pas un confort ;
- ce qui manque sans clone est NOMMÉ, jamais tu ;
- l'identité git saisie prime sur celle de l'hôte, champ par champ.
"""

import importlib.util
import shlex
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.argv = ["todo.py"]
from script.todo import dev_tools  # noqa: E402
from script.todo.deploy_form_lib import build_spec  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]


def _deploy_qemu():
    chemin = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()


class UneSeuleAutorite(unittest.TestCase):
    """Les mêmes outils se posent sur l'hôte et dans une VM."""

    def test_the_host_reads_the_shared_table(self):
        """Deux copies d'une URL dérivent dès que l'amont en change une, et
        la seconde est celle qu'on oublie."""
        self.assertIs(TODO._UPSTREAM_TOOLS, dev_tools.AGENTS)
        self.assertIs(TODO._STARSHIP_LINE, dev_tools.STARSHIP_LINE)
        self.assertEqual(TODO._STARSHIP_UPSTREAM, dev_tools.STARSHIP_UPSTREAM)

    def test_both_agents_are_offered(self):
        self.assertEqual(["claude", "opencode"], sorted(dev_tools.AGENTS))

    def test_the_default_agent_is_one_of_them(self):
        """Le premier de la table ferait dépendre le défaut de l'ordre
        d'écriture d'un dictionnaire."""
        self.assertIn(dev_tools.AGENT_DEFAUT, dev_tools.AGENTS)


class LeCatalogue(unittest.TestCase):
    def test_the_tool_exists_and_needs_no_desktop(self):
        """On s'en sert en SSH : une VM serveur le prend aussi, et aucune
        architecture n'est exclue."""
        spec = TODO._QEMU_VM_TOOLS["aidev"]
        self.assertFalse(spec["needs_desktop"])
        self.assertEqual((), spec["arches"])

    def test_it_is_bounded_to_the_imperative_families(self):
        """Trois installateurs « curl | sh » qui posent des binaires liés
        dynamiquement, plus des paquets par le gestionnaire du système :
        aucun des deux gestes n'existe sur un système déclaratif, où ce qui
        est installé à la main ne survit pas à la reconstruction."""
        spec = TODO._QEMU_VM_TOOLS["aidev"]
        self.assertEqual(("apt", "dnf", "pacman", "zypper"), spec["families"])
        self.assertEqual(
            [],
            TODO._qemu_tools_for(("aidev",), "amd64", "", "nixos"),
        )

    def test_it_is_posed_before_the_clone(self):
        """« before » est la phase où chaque outil se garde lui-même. En
        « after », un curl sans réponse rendrait la VM rouge."""
        self.assertEqual("before", TODO._QEMU_VM_TOOLS["aidev"]["phase"])


class LaCommandeDistante(unittest.TestCase):
    def _cmd(self, agent=""):
        return TODO.__new__(TODO)._qemu_aidev_remote_cmd(agent)

    def test_it_poses_the_three_tools(self):
        cmd = self._cmd("claude")
        self.assertIn("rtk", cmd)
        self.assertIn("starship", cmd)
        self.assertIn("claude.ai", cmd)

    def test_the_chosen_agent_is_the_one_posed(self):
        """Un seul agent, celui qu'on a demandé : poser les deux
        installerait un outil que personne n'a coché."""
        claude = self._cmd("claude")
        opencode = self._cmd("opencode")
        self.assertIn("claude.ai", claude)
        self.assertNotIn("opencode.ai", claude)
        self.assertIn("opencode.ai", opencode)
        self.assertNotIn("claude.ai", opencode)

    def test_an_unknown_agent_falls_back(self):
        """Une valeur inattendue ne doit pas faire tomber un déploiement."""
        self.assertIn("claude.ai", self._cmd("gemini"))
        self.assertIn("claude.ai", self._cmd(""))

    def test_no_pose_can_hang(self):
        """« || true » couvre l'ÉCHEC, pas l'ATTENTE. Un installateur qui
        pose une question resterait pendu sur un SSH sans terminal, et le
        déploiement avec lui.

        L'invariant est vérifié pose par pose plutôt que par un compte : un
        compte figé se contente d'être mis à jour quand une pose s'ajoute,
        sans rien dire de la nouvelle."""
        cmd = self._cmd("claude")
        bornees = [x for x in cmd.split("; ") if "timeout " in x]
        self.assertGreaterEqual(len(bornees), 4)
        for morceau in bornees:
            self.assertIn("</dev/null", morceau)
            self.assertIn("|| true", morceau)

    def test_starship_is_told_not_to_ask(self):
        """Sans « -y », son installateur attend une confirmation."""
        self.assertIn("-s -- -y", self._cmd("claude"))

    def test_the_rc_lines_are_written_once(self):
        """Sans le « grep » qui précède, chaque redéploiement d'une même VM
        rallonge son ~/.bashrc — ou son historique — d'une ligne identique.

        Aucun ajout n'échappe à la règle : on compte les « >> » et non les
        greps, pour qu'une ligne ajoutée sans garde fasse tomber le test.
        Chaque « >> » doit clore l'idiome ENTIER — grep, puis « || echo » de
        la ligne citée —, lu d'un seul motif : la ligne citée peut porter
        elle-même des « ; », et un découpage sur « ; » la couperait."""
        import re

        cite = r"(?:'(?:[^']|'\"'\"')*'|[^\s']+)"
        garde = re.compile(
            rf"grep -qF {cite} \S+ 2>/dev/null \|\| echo {cite} >> \S+"
        )
        for agent in ("claude", "opencode"):
            cmd = self._cmd(agent)
            with self.subTest(agent=agent):
                self.assertEqual(cmd.count(">> "), cmd.count("grep -qF"))
                self.assertEqual(cmd.count(">> "), len(garde.findall(cmd)))

    def test_the_local_bin_is_on_the_path_for_every_agent(self):
        """rtk se pose dans ~/.local/bin. La ligne de l'agent ne couvre ce
        répertoire que pour Claude Code : avec opencode, qui s'installe
        ailleurs, rtk resterait introuvable dans la VM."""
        for agent in ("claude", "opencode"):
            with self.subTest(agent=agent):
                self.assertIn(
                    'export PATH="$HOME/.local/bin:$PATH"', self._cmd(agent)
                )

    def test_an_identical_path_line_is_not_written_twice(self):
        """Claude Code S'INSTALLE dans ~/.local/bin : deux lignes identiques
        n'auraient qu'un effet, et deux fois la place dans le journal."""
        cmd = self._cmd("claude")
        self.assertEqual(1, cmd.count("$HOME/.local/bin:$PATH"))

    def test_the_terminal_tools_are_posed(self):
        """tig, htop et vim portent le même nom dans les quatre familles :
        aucune n'a de raison de les rater."""
        cmd = self._cmd("claude")
        for gestionnaire in ("apt-get", "dnf", "zypper", "pacman"):
            self.assertIn(gestionnaire, cmd)
        self.assertEqual(4, cmd.count("tig htop vim"))

    def test_the_venv_activation_reaches_the_history(self):
        """La commande qu'on veut retrouver à la flèche du haut, dans le
        fichier que bash relit, et une seule fois."""
        cmd = self._cmd("claude")
        ligne = "source .venv.erplibre/bin/activate"
        self.assertIn(f"echo '{ligne}' >> ~/.bash_history", cmd)
        self.assertIn(f"grep -qF '{ligne}' ~/.bash_history", cmd)

    def test_the_history_keeps_the_rights_bash_gives_it(self):
        """Créé par une redirection, le fichier suit l'umask — lisible par
        tous sur les images visées, là où bash le crée en 600."""
        self.assertIn("chmod 600 ~/.bash_history", self._cmd("claude"))

    def test_the_rtk_hook_is_called_by_absolute_path(self):
        """Le PATH de cette commande distante a été figé au démarrage du
        shell SSH, avant que l'installateur ne pose le binaire : « rtk » nu
        rendrait 127 sans dire que le hook n'a pas été écrit."""
        cmd = self._cmd("claude")
        self.assertIn('RTK="$(command -v rtk || echo "$HOME', cmd)
        self.assertIn('"$RTK" init --global', cmd)

    def test_git_is_configured_without_taking_the_editor_over(self):
        """zdiff3 est posé sans condition. L'éditeur, lui, ne l'est que s'il
        n'y en a pas : deploy_qemu transmet celui de l'hôte, et deux
        autorités sur un même réglage en font une de trop."""
        cmd = self._cmd("claude")
        self.assertIn("git config --global merge.conflictStyle zdiff3", cmd)
        self.assertIn(
            "git config --global --get core.editor >/dev/null 2>&1"
            " || git config --global core.editor vim",
            cmd,
        )

    def test_the_git_settings_survive_a_vm_without_git(self):
        """La phase « before » d'une VM sans installation ERPLibre n'a pas vu
        l'amorçage qui pose git : hors d'un « if », « set -e » ferait tomber
        le déploiement sur une commande introuvable."""
        cmd = self._cmd("claude")
        self.assertIn("if command -v git >/dev/null 2>&1; then", cmd)

    def test_the_path_uses_home_not_a_tilde(self):
        """Entre guillemets, le tilde n'est pas étendu : le PATH porterait
        un répertoire nommé « ~ », qui n'existe pas."""
        cmd = self._cmd("opencode")
        self.assertIn('export PATH="$HOME/.opencode/bin:$PATH"', cmd)
        self.assertNotIn('PATH="~/', cmd)

    def test_it_is_valid_shell(self):
        """Une commande mal citée casse tout le bloc des outils, pas
        seulement le sien."""
        for agent in ("claude", "opencode", ""):
            with self.subTest(agent=agent):
                fini = subprocess.run(
                    ["bash", "-n"],
                    input=self._cmd(agent),
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(0, fini.returncode, fini.stderr)

    def test_nothing_is_posed_without_the_box(self):
        todo = TODO.__new__(TODO)
        cmd = todo._qemu_erplibre_remote_cmd("develop", tools=())
        self.assertNotIn("starship", cmd)

    def test_the_agent_reaches_the_remote_command(self):
        """L'épreuve du bout en bout : le choix doit traverser toute la
        chaîne, sans quoi il reste un réglage sans effet."""
        todo = TODO.__new__(TODO)
        cmd = todo._qemu_erplibre_remote_cmd(
            "develop", tools=("aidev",), ai_agent="opencode"
        )
        self.assertIn("opencode.ai", cmd)


class LeComplementApresClone(unittest.TestCase):
    """Ce que la pré-configuration ne peut poser qu'une fois le dépôt là."""

    def _cmd(self, prod=False):
        return TODO.__new__(TODO)._qemu_aidev_after_cmd(prod)

    def test_the_hooks_point_at_the_checkout(self):
        """« git -C » et non le cwd : le dépôt porte des dépôts imbriqués, et
        core.hooksPath écrit dans l'un d'eux laisserait la racine sans
        garde-fou, sans le moindre message."""
        cmd = self._cmd()
        self.assertIn(
            "git -C $HOME/git/erplibre config core.hooksPath"
            " script/git/hooks",
            cmd,
        )

    def test_the_hooks_get_their_execution_bit(self):
        """git saute SANS RIEN DIRE un hook qui ne l'a pas, et le garde-fou du
        message de commit passe alors inaperçu."""
        cmd = self._cmd()
        for hook in TODO._GIT_HOOKS:
            self.assertIn(f"hooks/{hook}", cmd)
        self.assertIn("chmod +x", cmd)

    def test_every_claude_command_is_deployed(self):
        """Une commande absente de la liste est une commande que la VM n'aura
        pas, et personne ne s'en aperçoit avant d'en avoir besoin."""
        cmd = self._cmd()
        for nom, gabarit in TODO._QEMU_AIDEV_CLAUDE_CMDS:
            self.assertIn(f"conf/{gabarit}", cmd)
            self.assertIn(f"~/.claude/commands/{nom}.md", cmd)

    def test_the_two_todo_commands_travel_together(self):
        """/todo_plan_max produit la spécification que /todo_add_command
        implémente : l'une sans l'autre laisse la moitié de la chaîne."""
        noms = [nom for nom, _g in TODO._QEMU_AIDEV_CLAUDE_CMDS]
        self.assertIn("todo_plan_max", noms)
        self.assertIn("todo_add_command", noms)

    def test_the_identity_is_substituted_literally(self):
        """En python3 et non en sed : un nom qui porterait « & » ou le
        séparateur choisi changerait de sens dans un « s/// »."""
        cmd = self._cmd()
        self.assertIn("python3 -c", cmd)
        for marque, cle in TODO._QEMU_AIDEV_PLACEHOLDERS:
            self.assertIn(marque, cmd)
            self.assertIn(cle, cmd)

    def test_it_follows_production_to_opt(self):
        cmd = self._cmd(True)
        self.assertIn("/opt/erplibre/conf/", cmd)
        self.assertNotIn("$HOME/git/erplibre", cmd)

    def test_nothing_in_it_can_fail_the_vm(self):
        """Une pré-configuration est un confort. Chaque commande se garde, et
        la dernière — un compte-rendu — rend 0 par construction."""
        for prod in (False, True):
            with self.subTest(prod=prod):
                cmd = self._cmd(prod)
                for morceau in cmd.split("; "):
                    if not morceau.strip() or morceau.startswith("echo "):
                        continue
                    self.assertIn("|| true", morceau)

    def test_it_is_valid_shell(self):
        for prod in (False, True):
            with self.subTest(prod=prod):
                fini = subprocess.run(
                    ["bash", "-n"],
                    input=self._cmd(prod),
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(0, fini.returncode, fini.stderr)

    def test_it_leads_the_after_phase(self):
        """En tête : quelques secondes de copies, contre une minute pour
        Forgejo et une heure pour le SDK Android."""
        todo = TODO.__new__(TODO)
        cmd = todo._qemu_after_remote_cmd(("aidev", "forgejo"), False)
        self.assertLess(
            cmd.index("core.hooksPath"), cmd.index("install_forgejo.sh")
        )

    def test_it_reaches_the_full_remote_command(self):
        """L'épreuve du bout en bout : sans cela, la moitié « dépôt » de la
        case resterait un réglage sans effet."""
        todo = TODO.__new__(TODO)
        cmd = todo._qemu_erplibre_remote_cmd("develop", tools=("aidev",))
        self.assertIn("core.hooksPath", cmd)
        self.assertIn("~/.claude/commands/commit.md", cmd)

    def test_a_vm_without_a_checkout_says_what_it_skips(self):
        """Écarter en silence laisse croire qu'une case cochée a été
        honorée. Les installations, elles, ont bien lieu."""
        todo = TODO.__new__(TODO)
        cmd = todo._qemu_erplibre_remote_cmd(
            "", tools=("aidev",), desktop="gnome"
        )
        self.assertIn("starship", cmd)
        self.assertNotIn("core.hooksPath", cmd)
        self.assertIn("⚠", cmd)


class LIdentiteGit(unittest.TestCase):
    """Le formulaire montre l'identité de l'hôte et permet de la changer."""

    def _args(self, **kw):
        argv = ["--distro", "ubuntu", "--hostname", "vm"]
        for cle, valeur in kw.items():
            argv += [f"--{cle.replace('_', '-')}", valeur]
        return DQ.build_parser().parse_args(argv)

    def _identite(self, cc):
        lu = {}
        for ligne in cc.split("\n"):
            for champ in ("name", "email"):
                if ligne.strip().startswith(f"{champ} = "):
                    lu[champ] = ligne.split(" = ", 1)[1]
        return lu

    def test_what_was_typed_wins(self):
        cc = DQ.build_cloud_config(
            self._args(
                git_name="Une Personne", git_email="qui@exemple.invalid"
            ),
            None,
            [],
        )
        self.assertEqual(
            {"name": "Une Personne", "email": "qui@exemple.invalid"},
            self._identite(cc),
        )

    def test_each_field_stands_alone(self):
        """Remplir le seul courriel ne doit pas effacer le nom : les deux
        retombent sur l'hôte SÉPARÉMENT."""
        cc = DQ.build_cloud_config(
            self._args(git_email="qui@exemple.invalid"), None, []
        )
        lu = self._identite(cc)
        self.assertEqual("qui@exemple.invalid", lu.get("email"))
        self.assertNotEqual("", lu.get("name", ""))

    def test_the_option_reaches_the_command(self):
        """Le réglage doit atteindre deploy_qemu, sinon il n'existe pas."""
        todo = TODO.__new__(TODO)
        cmd = todo._qemu_build_deploy_parts(
            "ubuntu",
            "24.04",
            "amd64",
            "vm",
            2048,
            2,
            "20G",
            "",
            "",
            True,
            git_name="Une Personne",
            git_email="qui@exemple.invalid",
        )
        self.assertIn("--git-name", cmd)
        self.assertIn("Une Personne", cmd)
        self.assertIn("--git-email", cmd)

    def test_an_empty_identity_says_nothing(self):
        """Vide, deploy_qemu recopie l'hôte : ajouter l'option avec une
        valeur vide écraserait cette identité par du rien."""
        todo = TODO.__new__(TODO)
        cmd = todo._qemu_build_deploy_parts(
            "ubuntu", "24.04", "amd64", "vm", 2048, 2, "20G", "", "", True
        )
        self.assertNotIn("--git-name", cmd)
        self.assertNotIn("--git-email", cmd)


class LaSpec(unittest.TestCase):
    def test_the_three_settings_reach_the_spec(self):
        """Absents de l'assemblée, les réglages du formulaire n'atteignent
        jamais le déploiement — la case resterait décorative."""
        spec = build_spec(
            [],
            [],
            {
                "res_label": "x1",
                "ssh_key": "",
                "install": None,
                "add_ssh_config": False,
                "parallelism": 1,
                "ai_agent": "opencode",
                "git_name": "Une Personne",
                "git_email": "qui@exemple.invalid",
            },
        )
        self.assertEqual("opencode", spec["ai_agent"])
        self.assertEqual("Une Personne", spec["git_name"])
        self.assertEqual("qui@exemple.invalid", spec["git_email"])


# Outils réels prêtés à la commande distante dans un bac à sable : aucun ne
# touche au réseau, aux paquets ni aux droits.
_OUTILS_INOFFENSIFS = (
    "sh",
    "bash",
    "env",
    "timeout",
    "grep",
    "chmod",
    "head",
    "mktemp",
    "rm",
    "cat",
    "mkdir",
    "touch",
)


def _bac_a_sable(test, faux, outils=_OUTILS_INOFFENSIFS):
    """Un PATH qui ne porte QUE des faux et des outils inoffensifs.

    `faux` : nom -> corps d'un script sh posé dans ce PATH. curl, sudo et
    les gestionnaires de paquets n'y sont que FAUX, ou pas du tout : la
    commande distante tourne pour de vrai sans jamais atteindre le réseau
    ni l'hôte. Le HOME est jetable. Rend (env, répertoire du PATH, HOME).
    """
    import os
    import shutil
    import tempfile

    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    racine = Path(tmp.name)
    faux_bin = racine / "bin"
    home = racine / "home"
    faux_bin.mkdir()
    home.mkdir()
    for outil in outils:
        os.symlink(shutil.which(outil), faux_bin / outil)
    for nom, corps in faux.items():
        chemin = faux_bin / nom
        chemin.write_text("#!/bin/sh\n" + corps, encoding="utf-8")
        chemin.chmod(0o755)
    env = {
        "PATH": str(faux_bin),
        "HOME": str(home),
        "TMPDIR": str(racine),
        "FAUXBIN": str(faux_bin),
    }
    return env, faux_bin, home


# Faux curl : à chaque installateur amont, un script qui pose un binaire
# factice là où le vrai le poserait — starship dans le PATH, comme en root.
# Avec ECHEC, il rend 22 sans rien écrire, comme sur un 504.
_FAUX_CURL = (
    'if [ -n "$ECHEC" ]; then echo "curl: (22) 504" >&2; exit 22; fi\n'
    'case "$*" in\n'
    "  *rtk*) echo 'poser rtk \"$HOME/.local/bin\"' ;;\n"
    "  *starship*) echo 'poser starship \"$FAUXBIN\"' ;;\n"
    "  *claude.ai*) echo 'poser claude \"$HOME/.local/bin\"' ;;\n"
    "  *opencode*) echo 'poser opencode \"$HOME/.opencode/bin\"' ;;\n"
    "  *) exit 22 ;;\n"
    "esac\n"
)
_FAUX_POSER = (
    'mkdir -p "$2"\n'
    'printf \'#!/bin/sh\\necho "%s 0.0.1"\\n\' "$1" > "$2/$1"\n'
    'chmod +x "$2/$1"\n'
)
# Trace, puis exécute SANS privilège ; « env » lit les « VAR=valeur » de
# tête comme le fait sudo.
_FAUX_SUDO = 'echo "$*" >> "$HOME/sudo.trace"\nexec env "$@"\n'


class LeVerdictDesOutilsAmont(unittest.TestCase):
    """Après chaque installateur amont, une ligne qui dit s'il a abouti.

    Le code de sortie de la pose ne le peut pas : sans pipefail, un tube
    rend le statut de l'interpréteur, 0 sur une entrée vide. La commande
    distante tourne ici pour de vrai, sous « set -e », dans un bac à sable
    où curl et sudo sont faux.
    """

    def _lancer(self, agent, **env_en_plus):
        from unittest import mock

        with mock.patch("script.todo.qemu_install.t", lambda k: k):
            cmd = TODO.__new__(TODO)._qemu_aidev_remote_cmd(agent)
        env, faux_bin, home = _bac_a_sable(
            self,
            {"curl": _FAUX_CURL, "poser": _FAUX_POSER, "sudo": _FAUX_SUDO},
        )
        env.update(env_en_plus)
        fini = subprocess.run(
            [str(faux_bin / "bash"), "-c", "set -e\n" + cmd + "\necho FIN"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return fini, home

    def test_without_a_download_each_tool_is_named_missing(self):
        """Et l'installation continue : aucun outil optionnel ne la fait
        tomber, pas même sa ligne de verdict."""
        for agent in ("claude", "opencode"):
            with self.subTest(agent=agent):
                fini, _home = self._lancer(agent, ECHEC="1")
                self.assertEqual(0, fini.returncode, fini.stderr[-400:])
                self.assertIn("FIN", fini.stdout)
                for nom in ("rtk", "starship", agent):
                    self.assertIn(
                        f"⚠ {nom} not installed (see above)", fini.stdout
                    )

    def test_a_posed_tool_gives_its_version(self):
        """opencode s'installe hors du PATH de ce shell : c'est le chemin
        de repli qui le trouve."""
        for agent in ("claude", "opencode"):
            with self.subTest(agent=agent):
                fini, _home = self._lancer(agent)
                self.assertEqual(0, fini.returncode, fini.stderr[-400:])
                for nom in ("rtk", "starship", agent):
                    self.assertIn(f"{nom}: {nom} 0.0.1", fini.stdout)
                self.assertNotIn("⚠", fini.stdout)

    def test_starship_is_installed_as_root(self):
        """En root, /usr/local/bin est inscriptible : l'installateur n'atteint
        jamais « sudo -v », que sudo-rs refuse sans mot de passe même à un
        compte NOPASSWD. L'hôte, lui, garde son installateur sans sudo."""
        self.assertIn(
            shlex.quote(dev_tools.STARSHIP_UPSTREAM_VM),
            TODO.__new__(TODO)._qemu_aidev_remote_cmd("claude"),
        )
        self.assertIn("| sudo timeout -k ", dev_tools.STARSHIP_UPSTREAM_VM)
        self.assertNotIn("sudo", dev_tools.STARSHIP_UPSTREAM)
        _fini, home = self._lancer("claude")
        self.assertIn(
            f"timeout -k {dev_tools.STARSHIP_ROOT_KILL_AFTER}"
            f" {dev_tools.STARSHIP_ROOT_TIMEOUT} sh -s -- -y",
            (home / "sudo.trace").read_text(),
        )

    def test_the_root_installer_is_bounded_behind_sudo(self):
        """Un « timeout » sans privilège ne tue pas un processus root : la
        borne de l'installateur doit passer DERRIÈRE sudo. « -k » envoie
        SIGKILL à un installateur qui ignore SIGTERM ; borne et délai
        additionnés tombent avant la borne de la pose, qui ne tient plus que
        curl."""
        import re

        vm = dev_tools.STARSHIP_UPSTREAM_VM
        dedans = re.search(r"\| sudo timeout -k (\d+) (\d+) sh -s -- -y$", vm)
        self.assertIsNotNone(dedans, vm)
        cmd = TODO.__new__(TODO)._qemu_aidev_remote_cmd("claude")
        dehors = re.search(
            r"timeout (\d+) sh -c " + re.escape(shlex.quote(vm)), cmd
        )
        self.assertIsNotNone(dehors, "la pose de starship n'est plus bornée")
        self.assertLess(
            int(dedans.group(1)) + int(dedans.group(2)), int(dehors.group(1))
        )


class LeHookDuPrompt(unittest.TestCase):
    """La ligne que le fichier du shell reçoit pour starship, lue par un vrai
    shell.

    Le fichier est lu SEUL, sous « set -e », et rien ne suit la lecture : la
    ligne est la dernière du fichier, dont le statut est donc le sien. Une
    commande placée après masquerait ce statut.
    """

    def _sourcer(self, faux, shell="bash"):
        binaire = shutil.which(shell)
        if binaire is None:
            self.skipTest(f"{shell} absent de cet hôte")
        env, faux_bin, home = _bac_a_sable(self, faux, outils=())
        rc = home / f".{shell}rc"
        rc.write_text(dev_tools.STARSHIP_LINE[shell] + "\n", encoding="utf-8")
        # Ni ~/.bashrc ni ~/.zshrc lus d'office : seul `rc` est lu.
        options = ["--norc"] if shell == "bash" else ["-f"]
        return subprocess.run(
            [binaire, *options, "-c", f'set -e; . "{rc}"'],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_without_the_binary_it_stays_silent_and_returns_zero(self):
        """Une pose ratée, un binaire retiré : sans garde, chaque shell
        ouvert écrirait « command not found ». Et la lecture rend 0 : un
        script sous « set -e » qui lit ce fichier ne s'y arrête pas."""
        for shell in ("bash", "zsh"):
            with self.subTest(shell=shell):
                fini = self._sourcer({}, shell)
                self.assertEqual("", fini.stderr)
                self.assertEqual(0, fini.returncode)

    def test_with_the_binary_it_starts_starship(self):
        for shell in ("bash", "zsh"):
            with self.subTest(shell=shell):
                fini = self._sourcer(
                    {"starship": 'echo "echo INIT-$2"\n'}, shell
                )
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertIn(f"INIT-{shell}", fini.stdout)

    def test_the_guard_is_an_if_in_every_posix_shell(self):
        """Le même « if … fi » pour bash et zsh : un hôte sans zsh ne lit
        la ligne de zsh par aucun shell, sa forme reste donc vérifiée."""
        for shell in ("bash", "zsh"):
            with self.subTest(shell=shell):
                ligne = dev_tools.STARSHIP_LINE[shell]
                self.assertTrue(ligne.startswith("if command -v starship "))
                self.assertTrue(ligne.endswith("; fi"), ligne)

    def test_the_dedup_pattern_survives_the_guard(self):
        """L'hôte comme la VM reconnaissent une ligne déjà écrite à
        « starship init » : la garde ne doit pas le masquer."""
        for shell, ligne in dev_tools.STARSHIP_LINE.items():
            with self.subTest(shell=shell):
                self.assertIn(f"starship init {shell}", ligne)


class UneApostropheTraduite(unittest.TestCase):
    def test_the_tool_blocks_stay_valid_shell(self):
        """Les messages sont traduits, et le français est plein
        d'apostrophes : une seule mal placée casse la commande distante
        ENTIÈRE. On remplace la traduction elle-même — « set_lang » la
        persisterait dans env_var.sh."""
        from unittest import mock

        # Un nombre IMPAIR d'apostrophes : entre apostrophes, un nombre pair
        # se referme de lui-même, et « bash -n » ne verrait rien.
        piege = "l'outil n'a pas « fini » aujourd'hui"
        with mock.patch("script.todo.qemu_install.t", lambda k: piege):
            todo = TODO.__new__(TODO)
            blocs = {
                f"aidev({agent})": todo._qemu_aidev_remote_cmd(agent)
                for agent in dev_tools.AGENTS
            }
            blocs["mise"] = todo._qemu_mise_remote_cmd("mise")
        for nom, cmd in blocs.items():
            with self.subTest(bloc=nom):
                self.assertIn(piege, cmd)
                fini = subprocess.run(
                    ["bash", "-n"], input=cmd, text=True, capture_output=True
                )
                self.assertEqual(0, fini.returncode, fini.stderr[:400])


if __name__ == "__main__":
    unittest.main()
