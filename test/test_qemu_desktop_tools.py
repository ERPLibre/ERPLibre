#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Outils de développement des VM graphiques : filtrage, disque, commande.

Ce qui se vérifie ici sans VM : qu'un outil demandé pour tout le parc n'atterrit
que sur les machines qui peuvent le recevoir, que la place disque annoncée suit
ce filtrage, et qu'un outil qui échoue ne fait pas tomber l'installation
d'ERPLibre avec lui — celle-ci ayant duré une heure.
"""

import subprocess
import sys
import unittest

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402


class TestToolFiltering(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.all = tuple(TODO._QEMU_VM_TOOLS)

    def test_a_server_gets_no_graphical_tool(self):
        """Un IDE sans bureau n'a rien pour s'afficher. La compilation mobile,
        elle, reste : elle compile, elle n'affiche pas."""
        got = self.todo._qemu_tools_for(self.all, "amd64", "", "ubuntu")
        for graphical in ("pycharm", "android", "gnome_ext"):
            self.assertNotIn(graphical, got)

    def test_android_studio_is_x86_64_only(self):
        """Google ne publie aucune archive Linux aarch64 : toutes les variantes
        de l'URL rendent 404, et product-info.json ne déclare que Linux/amd64.
        """
        self.assertIn(
            "android",
            self.todo._qemu_tools_for(self.all, "amd64", "gnome", "ubuntu"),
        )
        for arch in ("arm64", "s390x"):
            self.assertNotIn(
                "android",
                self.todo._qemu_tools_for(self.all, arch, "gnome", "ubuntu"),
                arch,
            )

    def test_pycharm_follows_jetbrains_two_architectures(self):
        for arch in ("amd64", "arm64"):
            self.assertIn(
                "pycharm",
                self.todo._qemu_tools_for(self.all, arch, "gnome", "ubuntu"),
                arch,
            )
        self.assertNotIn(
            "pycharm",
            self.todo._qemu_tools_for(self.all, "s390x", "gnome", "ubuntu"),
        )

    def test_gnome_extensions_only_under_gnome(self):
        self.assertIn(
            "gnome_ext",
            self.todo._qemu_tools_for(self.all, "amd64", "gnome", "ubuntu"),
        )
        self.assertNotIn(
            "gnome_ext",
            self.todo._qemu_tools_for(self.all, "amd64", "cinnamon", "ubuntu"),
        )

    def test_unknown_key_is_ignored(self):
        self.assertEqual(
            [],
            self.todo._qemu_tools_for(("nope",), "amd64", "gnome", "ubuntu"),
        )


class TestToolDisk(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.all = tuple(TODO._QEMU_VM_TOOLS)

    def test_disk_follows_the_filtering(self):
        """Une VM qui ne recevra pas un outil ne doit pas se voir gonfler son
        disque de sa taille. En arm64 il en manque DEUX : Android Studio, que
        Google ne publie qu'en x86_64, et la compilation mobile, qui en
        dépend."""
        full = self.todo._qemu_tools_disk_gb(
            self.all, "amd64", "gnome", "ubuntu"
        )
        arm = self.todo._qemu_tools_disk_gb(
            self.all, "arm64", "gnome", "ubuntu"
        )
        self.assertEqual(
            full - arm,
            TODO._QEMU_VM_TOOLS["android"]["disk_gb"]
            + TODO._QEMU_VM_TOOLS["mobile"]["disk_gb"]
            + TODO._QEMU_VM_TOOLS["avd"]["disk_gb"],
        )

    def test_a_server_only_pays_for_what_it_gets(self):
        """Un serveur ne porte aucun IDE, donc il n'en paie pas le disque —
        mais il paie bien ce qu'il reçoit : compilation mobile et émulateur."""
        self.assertEqual(
            TODO._QEMU_VM_TOOLS["mobile"]["disk_gb"]
            + TODO._QEMU_VM_TOOLS["avd"]["disk_gb"],
            self.todo._qemu_tools_disk_gb(self.all, "amd64", "", "ubuntu"),
        )

    def test_the_deploy_command_grows_the_disk(self):
        """Le disque demandé à deploy_qemu.py doit inclure les outils : c'est
        la seule valeur qui compte, celle du qcow2 réellement créé."""
        spec = {
            "ssh_key": "",
            "desktop": "gnome",
            "vm_tools": self.all,
            "install": {
                "branch": "develop",
                "prod": False,
                "cmd": "make install_os && make install_odoo_18",
                "label": "x",
                "monitor": True,
            },
        }
        vm = {
            "distro": "ubuntu",
            "version": "24.04",
            "arch": "amd64",
            "name": "v",
            "ram": 3072,
            "vcpus": 4,
            "disk": "20G",
            "desktop": "gnome",
        }
        parts = self.todo._qemu_deploy_parts_for(vm, spec, dry_run=True)
        size = parts[parts.index("--disk-size") + 1]
        expected = (
            20
            + TODO.ERPLIBRE_EXTRA_DISK_GB
            + TODO.QEMU_DESKTOP_EXTRA_DISK_GB
            + sum(s["disk_gb"] for s in TODO._QEMU_VM_TOOLS.values())
        )
        self.assertEqual(f"{expected}G", size)


class TestToolRemoteCommand(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.all = tuple(TODO._QEMU_VM_TOOLS)

    def _sh_ok(self, script):
        """Le shell accepte-t-il ce script ? « bash -n » ne l'exécute pas."""
        return subprocess.run(
            ["bash", "-n"], input=script, text=True, capture_output=True
        )

    def test_every_combination_is_valid_shell(self):
        combos = [
            (),
            ("pycharm",),
            ("android",),
            ("gnome_ext",),
            self.all,
        ]
        for tools in combos:
            script = self.todo._qemu_erplibre_remote_cmd(
                "develop", None, False, "gnome", "mise", "deb", tools
            )
            res = self._sh_ok(script)
            self.assertEqual(0, res.returncode, f"{tools} : {res.stderr}")

    def test_tools_come_before_the_clone_and_the_make(self):
        """L'ordre est ce qui fait marcher la configuration du projet : PyCharm
        écrit le .idea du dépôt en l'ouvrant une fois, et c'est l'installation
        qui, ENSUITE, y lance pycharm_configuration.py."""
        script = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, "gnome", "", "deb", ("pycharm",)
        )
        self.assertLess(script.index("PyCharm"), script.index("git clone"))
        self.assertLess(
            script.index("PyCharm"), script.index("make install_os")
        )

    def test_the_install_owns_the_project_configuration(self):
        """update_env_version.pycharm_update() lance déjà le script, et sait se
        taire sans .idea. Doubler l'appel n'écrivait qu'une erreur dans le
        journal d'une VM neuve."""
        script = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, "gnome", "", "deb", ("pycharm",)
        )
        self.assertNotIn("pycharm_configuration", script)

    def test_a_failing_tool_never_masks_a_failing_install(self):
        """Le code de sortie doit rester celui de l'installation : c'est lui que
        lit le tableau de bord pour dire ✅ ou ❌."""
        script = (
            "set -e\n"
            "curl() { return 7; }; sudo() { return 7; }\n"
            + self.todo._qemu_tools_remote_cmd(("pycharm", "android"), False)
            + "\nexit 3\n"  # l'installation qui suit, en échec
        )
        res = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True
        )
        self.assertEqual(3, res.returncode, res.stdout + res.stderr)

    def test_a_failing_tool_still_returns_zero(self):
        """Le bloc d'outils est lui-même gardé : PyCharm indisponible ne doit
        pas transformer une installation réussie en échec."""
        script = "set -e\n" + self.todo._qemu_tools_remote_cmd(self.all, False)
        # Tout ce qui pourrait réussir est neutralisé : ni réseau, ni sudo.
        stub = (
            "curl() { return 7; }; sudo() { return 7; }; tar() { return 7; }; "
            "export -f curl sudo tar 2>/dev/null || true\n"
        )
        res = subprocess.run(
            ["bash", "-c", stub + script], capture_output=True, text=True
        )
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertIn("PyCharm", res.stdout)


class TestToolDiscoverability(unittest.TestCase):
    """Ce qui est installé doit pouvoir être TROUVÉ. Vécu : Android Studio
    posé dans /opt, lanceur nommé « studio », et l'utilisateur conclut à un
    échec parce que « android-studio » ne répond pas."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_android_studio_answers_to_both_names(self):
        cmd = self.todo._qemu_android_studio_remote_cmd()
        self.assertIn("/usr/local/bin/studio;", cmd)
        self.assertIn("/usr/local/bin/android-studio;", cmd)

    def test_the_sdk_is_shared_with_the_desktop_session(self):
        """install-android.sh écrit ses exports dans ~/.bashrc, que GNOME ne
        lit pas : sans environment.d, Android Studio lancé depuis le menu
        proposerait de télécharger un SECOND SDK."""
        cmd = self.todo._qemu_android_studio_remote_cmd()
        self.assertIn(".config/environment.d", cmd)
        self.assertIn("ANDROID_HOME=", cmd)
        # Le même emplacement que celui où la compilation mobile l'installe.
        self.assertIn("/android", cmd)
        self.assertIn("ANDROID_HOME", self.todo._qemu_mobile_remote_cmd())

    def test_the_log_says_where_it_landed(self):
        pycharm = self.todo._qemu_pycharm_remote_cmd()
        android = self.todo._qemu_android_studio_remote_cmd()
        self.assertIn("/opt/pycharm", pycharm)
        self.assertIn("/opt/android-studio", android)

    def test_pycharm_says_what_creates_the_project(self):
        """Le .idea n'existe qu'après une première ouverture de PyCharm : le
        journal le dit, plutôt que de laisser croire à un échec."""
        cmd = self.todo._qemu_pycharm_remote_cmd()
        self.assertIn(".idea", cmd)


class TestMobileBuild(unittest.TestCase):
    """Compilation ERPLibre mobile : la seule étape qui peut faire échouer la
    VM, et la seule qui n'exige pas de bureau."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.all = tuple(TODO._QEMU_VM_TOOLS)

    def test_it_runs_on_a_server_vm(self):
        """Elle compile, elle n'affiche rien : un bureau serait du gaspillage.
        L'émulateur non plus n'en a pas besoin — il s'affiche par ssh -X."""
        got = self.todo._qemu_tools_for(self.all, "amd64", "", "ubuntu")
        self.assertEqual(["mobile", "avd"], got)

    def test_it_is_bounded_to_apt(self):
        """install-android.sh du dépôt mobile commence par « sudo apt install
        openjdk-17-jdk » : ailleurs il s'arrête là."""
        for distro in ("fedora", "rocky", "opensuse", "arch"):
            self.assertNotIn(
                "mobile",
                self.todo._qemu_tools_for(self.all, "amd64", "gnome", distro),
                distro,
            )
        self.assertIn(
            "mobile",
            self.todo._qemu_tools_for(self.all, "amd64", "gnome", "debian"),
        )

    def test_it_coexists_with_android_studio(self):
        """Combinaison croisée : la VM graphique reçoit les deux, et un seul
        SDK — celui de $HOME/android, que ANDROID_HOME désigne."""
        got = self.todo._qemu_tools_for(self.all, "amd64", "gnome", "ubuntu")
        self.assertIn("android", got)
        self.assertIn("mobile", got)
        self.assertIn("ANDROID_HOME", self.todo._qemu_mobile_remote_cmd())

    def test_it_runs_after_the_install_not_before(self):
        """Elle a besoin du dépôt, du venv qui synchronise le manifeste, et de
        node que « make install_os » installe."""
        script = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, "", "", "deb", ("mobile",)
        )
        self.assertLess(
            script.index("make install_os"),
            script.index("erplibre-mobile-build.log"),
        )

    def test_a_failed_build_fails_the_vm(self):
        """Contrat explicite : « pour que ce soit bon », l'app doit compiler.
        Le bloc est donc lié par « && » et n'est PAS gardé, à la différence des
        outils graphiques."""
        script = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, "", "", "deb", ("mobile",)
        )
        tail = script[script.index("erplibre-mobile-build.log") :]
        self.assertNotIn("|| true", tail)
        self.assertNotIn("|| echo", tail)

    def test_the_build_covers_apk_and_tests(self):
        cmd = self.todo._qemu_mobile_remote_cmd()
        for step in (
            "update_manifest_local_mobile.sh",
            "./install-android.sh",
            "npm ci",
            "npm run build",
            "npx cap sync android",
            "./gradlew --no-daemon assembleDebug",
            "npm test",
        ):
            self.assertIn(step, cmd, step)

    def test_the_platform_comes_from_the_project(self):
        """L'installateur amont pose android-34, variables.gradle demande
        compileSdk 36 : on lit le chiffre plutôt que de le figer."""
        cmd = self.todo._qemu_mobile_remote_cmd()
        self.assertIn("android/variables.gradle", cmd)
        self.assertIn("platforms;android-$v", cmd)
        self.assertNotIn("platforms;android-36", cmd)

    def test_the_apk_is_the_proof(self):
        """Une tâche Gradle peut rendre 0 sans rien produire."""
        cmd = self.todo._qemu_mobile_remote_cmd()
        self.assertIn("outputs/apk/debug/*.apk", cmd)

    def test_both_apk_locations_are_searched(self):
        """Avec une ABI injectée, AGP écrit dans intermediates et non dans
        outputs : mesuré, une compilation RÉUSSIE était rapportée « aucun APK
        produit » parce qu'un seul des deux chemins était regardé."""
        cmd = self.todo._qemu_mobile_remote_cmd()
        self.assertIn("intermediates/apk/debug/*.apk", cmd)

    def test_no_apk_means_non_zero(self):
        """Éprouvé plutôt que relu : sans APK, le bloc DOIT rendre non nul.
        Une ligne d'information placée après le « fi » suffisait à rendre 0 et
        à faire repasser la VM au vert."""
        cmd = self.todo._qemu_mobile_remote_cmd()
        tail = cmd[cmd.index("apk=$(ls") :]
        res = subprocess.run(
            ["bash", "-c", "set -e\n" + tail], capture_output=True, text=True
        )
        self.assertNotEqual(0, res.returncode, res.stdout)

    def test_every_failure_names_a_cause(self):
        """Un journal de dizaines de mégaoctets ne se relit pas : le diagnostic
        doit dire pourquoi."""
        cmd = self.todo._qemu_mobile_remote_cmd()
        for pattern, _cause in TODO._QEMU_MOBILE_DIAG:
            self.assertIn(pattern, cmd, pattern)
        self.assertIn('tail -12 "$1"', cmd)

    def test_heavy_output_stays_out_of_the_install_log(self):
        """Des centaines de lignes Gradle portant le mot « error » sans être
        des pannes rendraient le compteur du tableau de bord inutilisable."""
        cmd = self.todo._qemu_mobile_remote_cmd()
        self.assertIn('>> "$M" 2>&1', cmd)


class TestAndroidEmulator(unittest.TestCase):
    """Émulateur Android : visible depuis le poste par « ssh -X »."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.cmd = self.todo._qemu_avd_remote_cmd()

    def test_no_desktop_needed_in_the_vm(self):
        """Il s'affiche sur l'écran de qui s'y connecte, pas dans la VM."""
        self.assertFalse(TODO._QEMU_VM_TOOLS["avd"]["needs_desktop"])
        self.assertIn(
            "avd", self.todo._qemu_tools_for(("avd",), "amd64", "", "ubuntu")
        )

    def test_the_screen_is_small_enough_to_travel(self):
        """Le profil Pixel donne 1080x2400 : 2,6 Mpixels par image à pousser
        dans SSH, et « ça se lance mais c'est trop lent ». Mesuré après
        réduction : 540x1140 confirmé par « wm size », et la capture pleine
        page tombe de 220 Ko à 49 Ko."""
        for key in (
            "hw.lcd.width=540",
            "hw.lcd.height=1140",
            "hw.lcd.density=240",
        ):
            self.assertIn(key, self.cmd, key)

    def test_the_printed_command_compresses_the_display(self):
        """« -XC » plutôt que « -X » sur un écran distant."""
        self.assertIn("ssh -XC erplibre@$ip", self.cmd)
        self.assertNotIn("ssh -X erplibre@$ip", self.cmd.replace("-XC", ""))

    def test_software_rendering_is_written_into_the_avd(self):
        """Par « ssh -X » il n'y a pas de GLX direct : en « auto »,
        l'émulateur s'ouvre sur un écran noir. Le réglage va dans config.ini
        pour qu'« emulator -avd erplibre » suffise."""
        self.assertIn("hw.gpu.mode=swangle", self.cmd)
        self.assertIn("config.ini", self.cmd)
        # « swiftshader_indirect » n'existe plus : l'émulateur 37.1 le refuse,
        # affiche deux erreurs et retombe sur swangle de lui-même. Mesuré.
        self.assertNotIn("swiftshader_indirect", self.cmd)

    def test_xauth_is_installed(self):
        """Sans xauth dans la VM, « ssh -X » n'ouvre aucun affichage — et le
        paquet manque des images cloud."""
        self.assertIn("xauth", self.cmd)

    def test_it_says_when_kvm_is_missing(self):
        """Un émulateur x86 sans KVM refuse de démarrer : le dire là où c'est
        réparable, sur l'hôte, plutôt qu'au premier lancement."""
        self.assertIn("/dev/kvm", self.cmd)

    def test_the_pixel_is_chosen_at_runtime(self):
        """« le plus récent, le plus petit écran » se demande au SDK : figer un
        modèle le rendrait faux à la prochaine génération."""
        self.assertIn("avdmanager list device", self.cmd)
        self.assertIn("pixel_", self.cmd)
        self.assertIn("pro|xl|fold|tablet", self.cmd)
        self.assertIn("sort -t_ -k2 -n", self.cmd)

    def test_the_system_image_falls_back(self):
        """Google ne publie pas d'image pour toutes les API : on descend."""
        self.assertIn("for a in $v 36 35 34", self.cmd)

    def test_it_prints_the_command_to_open_it(self):
        """Un émulateur dont on ignore comment l'ouvrir ne sert à personne."""
        self.assertIn("ssh -XC erplibre@$ip", self.cmd)
        self.assertIn("adb install -r", self.cmd)

    def test_the_printed_commands_use_absolute_paths(self):
        """« ssh hôte 'commande' » ne lit ni ~/.profile ni ~/.bashrc — Ubuntu y
        met même un « return » pour les shells non interactifs. Une commande
        affichée qui compte sur le PATH répond « command not found ». Vécu."""
        self.assertIn("$HOME/android/emulator/emulator", self.cmd)
        self.assertIn("$HOME/android/platform-tools/adb", self.cmd)
        self.assertNotIn('"emulator -avd', self.cmd)
        self.assertNotIn('"adb install', self.cmd)

    def test_the_windowed_emulator_gets_its_audio_library(self):
        """Deux binaires qemu : seul le « headless » se passe de PulseAudio.
        Celui qui ouvre une fenêtre lie libpulse.so.0, absente des images
        cloud, et échoue même avec « -no-audio »."""
        self.assertIn("libpulse0", self.cmd)

    def test_one_prologue_and_one_sdk_for_both_options(self):
        """Deux prologues, et le second tronquerait le journal du premier."""
        both = self.todo._qemu_after_remote_cmd(("mobile", "avd"))
        self.assertEqual(1, both.count("mstep() {"))
        self.assertEqual(1, both.count('M="$HOME/erplibre-mobile-build.log"'))

    def test_the_emulator_cannot_mask_a_build_failure(self):
        """ÉPROUVÉ, pas relu. Sans accolades autour de chaque groupe, « && » ne
        lie que la première commande du suivant : mesuré sur une VM, un APK
        manquant laissait tourner l'émulateur puis rendait 0 — la VM repassait
        au vert alors que rien n'avait compilé."""
        both = self.todo._qemu_after_remote_cmd(("mobile", "avd"))
        # On neutralise les étapes : seul le CHAÎNAGE est en cause ici.
        stub = 'mstep() { echo "   -> $1"; return 0; }; mdiag() { :; }; '
        tail = both[both.index('{ mstep "') :]
        res = subprocess.run(
            ["bash", "-c", "set -e; " + stub + tail],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(0, res.returncode, res.stdout)
        # Et l'émulateur ne doit PAS avoir été touché.
        self.assertNotIn("Pixel", res.stdout)

    def test_valid_shell_in_every_combination(self):
        for tools in (("mobile",), ("avd",), ("mobile", "avd")):
            cmd = self.todo._qemu_after_remote_cmd(tools)
            res = subprocess.run(
                ["bash", "-n"], input=cmd, text=True, capture_output=True
            )
            self.assertEqual(0, res.returncode, f"{tools}: {res.stderr}")

    def test_no_diagnostic_pattern_carries_an_apostrophe(self):
        """Ces motifs partent dans un « grep -q '<motif>' » : une apostrophe
        fermait la chaîne et rendait tout le bloc invalide. Vécu."""
        for pattern, _cause in TODO._QEMU_MOBILE_DIAG:
            self.assertNotIn("'", pattern, pattern)


class TestPycharmCommunity(unittest.TestCase):
    """PyCharm doit s'ouvrir sans compte : c'est toute la différence entre une
    VM utilisable au premier démarrage et une VM qui demande une licence."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.cmd = self.todo._qemu_pycharm_remote_cmd()

    def test_the_community_line_is_what_is_looked_up(self):
        """Mesuré dans une VM : le build unifié s'arrête sur
        « NoValidIdeLicense » et n'ouvre jamais le projet."""
        self.assertIn("pycharm-community-", self.cmd)
        self.assertIn("data.services.jetbrains.com", self.cmd)

    def test_no_version_is_frozen_in_the_repository(self):
        """Le flux donne la plus récente : rien à mettre à jour ici quand
        JetBrains publie un correctif."""
        self.assertNotIn("2025.2.6", self.cmd)
        self.assertNotIn("pycharm-community-2", self.cmd)

    def test_both_architectures_are_asked_for(self):
        self.assertIn("linuxARM64", self.cmd)
        self.assertIn("jb=linux", self.cmd)

    def test_the_fallback_names_its_cost(self):
        """Le repli sert le build unifié : le dire, plutôt que de le laisser
        découvrir au premier lancement."""
        self.assertIn("code=PCC&latest", self.cmd)
        self.assertIn("JetBrains", self.cmd)


class TestPycharmFirstOpen(unittest.TestCase):
    """Ouverture sans écran, pour que le .idea existe avant l'installation."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.cmd = self.todo._qemu_pycharm_project_cmd()

    def test_it_runs_between_the_clone_and_the_make(self):
        script = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, "gnome", "", "deb", ("pycharm",)
        )
        self.assertLess(script.index("git clone"), script.index("xvfb-run"))
        self.assertLess(
            script.index("xvfb-run"), script.index("make install_os")
        )

    def test_only_when_pycharm_was_asked_for(self):
        script = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, "gnome", "", "deb", ("android",)
        )
        self.assertNotIn("xvfb-run", script)

    def test_the_first_run_dialogs_are_answered_in_advance(self):
        """Sans réponse, la session attend un clic que personne ne donnera.

        Celle de la CONFIANCE est la plus coûteuse à rater : mesuré, le journal
        s'arrête 1,3 s après le démarrage et le projet ne s'ouvre jamais."""
        self.assertIn("idea.trust.all.projects=true", self.cmd)
        self.assertIn("jb.consents.confirmation.enabled=false", self.cmd)
        self.assertIn("consentOptions", self.cmd)
        # Le consentement est écrit REFUSÉ : aucune statistique ne part.
        self.assertIn("rsch.send.usage.stat:1.1:0:", self.cmd)

    def test_xvfb_package_names_are_per_family(self):
        """« xvfb » n'existe que chez Debian : ailleurs le paquet s'appelle
        autrement, et un nom inventé ne s'installerait pas."""
        self.assertEqual("xvfb", TODO._QEMU_XVFB_PKG["apt"])
        self.assertEqual("xorg-x11-server-Xvfb", TODO._QEMU_XVFB_PKG["dnf"])
        self.assertEqual("xorg-server-xvfb", TODO._QEMU_XVFB_PKG["pacman"])

    def test_it_gives_up_rather_than_hangs(self):
        """Un IDE qui ne s'ouvre pas ne doit pas retenir l'installation : le
        budget est borné et le processus tué."""
        self.assertIn("kill -TERM", self.cmd)
        self.assertIn("kill -KILL", self.cmd)
        self.assertIn(f"seq 1 {TODO._QEMU_PYCHARM_OPEN_TRIES}", self.cmd)

    def test_valid_shell(self):
        res = subprocess.run(
            ["bash", "-n"],
            input="set -e\n" + self.cmd,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, res.returncode, res.stderr)


class TestAvdStep(unittest.TestCase):
    """L'étape AVD, et ce qu'elle laisse comme piste dans le journal.

    Le tunnel adb lui-même est vérifié dans test_qemu_emulator_menu.py, qui
    couvre aussi le démarrage sans fenêtre et la question de la fenêtre.
    """

    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_the_avd_step_points_at_the_tunnel(self):
        """La question vient juste après « c'est trop lent » : la réponse doit
        être à portée de journal."""
        self.assertIn("tunnel > 4", self.todo._qemu_avd_remote_cmd())


class TestGnomeSiteExtensions(unittest.TestCase):
    """Extensions posées depuis extensions.gnome.org, par leur UUID."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.block = self.todo._qemu_gnome_ext_remote_cmd()

    def test_the_three_requested_extensions_are_there(self):
        for uuid in (
            "gTile@vibou",
            "freon@UshakovVasilii_Github.yahoo.com",
            "tracker@aliakseiz.github.com",
        ):
            self.assertIn(uuid, self.block, uuid)

    def test_the_archive_follows_the_running_gnome(self):
        """Le site sert une archive DIFFERENTE selon la version demandée —
        gTile v59 en GNOME 46, v62 en 48 : figer une URL poserait une archive
        faite pour une autre version."""
        self.assertIn("shell_version=$sv", self.block)
        self.assertIn("gnome-shell --version", self.block)

    def test_valid_shell_and_never_fails_the_install(self):
        script = "set -e\n" + self.block
        self.assertEqual(
            0,
            subprocess.run(
                ["bash", "-n"], input=script, text=True, capture_output=True
            ).returncode,
        )
        # Sans gnome-shell dans le PATH, le bloc doit se taire proprement.
        res = subprocess.run(
            ["bash", "-c", "PATH=/nonexistent; " + script],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, res.returncode, res.stderr)

    def test_a_session_bus_is_provided_for_dconf(self):
        """Un « ssh hote commande » n'a pas de bus de session : sans lui,
        l'activation ne peut rien ecrire dans dconf."""
        self.assertIn("dbus-run-session", self.block)


if __name__ == "__main__":
    unittest.main()
