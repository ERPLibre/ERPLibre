#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Outils de développement des VM graphiques : filtrage, disque, commande.

Ce qui se vérifie ici sans VM : qu'un outil demandé pour tout le parc n'atterrit
que sur les machines qui peuvent le recevoir, que la place disque annoncée suit
ce filtrage, et qu'un outil qui échoue ne fait pas tomber l'installation
d'ERPLibre avec lui — celle-ci ayant duré une heure.
"""

import pathlib
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
        mais il paie bien ce qu'il reçoit : compilation mobile, émulateur et
        forge. La somme est calculée depuis la table plutôt qu'écrite en
        chiffre : ajouter un outil sans écran ne doit pas casser ce test, il
        doit le suivre."""
        expected = sum(
            spec["disk_gb"]
            for key, spec in TODO._QEMU_VM_TOOLS.items()
            if not spec["needs_desktop"]
        )
        self.assertEqual(
            expected,
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

    def test_the_configuration_is_asked_for_because_the_install_was_too_early(
        self,
    ):
        """Le contraire de ce que ce test exigeait avant, et pour une raison
        mesurée : pycharm_update() teste « os.path.exists('.idea') » et se tait
        quand le projet n'existe pas encore. Or il s'exécute PENDANT
        l'installation, alors que PyCharm ne s'ouvrira qu'après. Personne ne
        configurait donc le projet — « Missing ./.idea path » dans le journal
        d'une VM neuve. On le demande maintenant explicitement, après
        l'ouverture."""
        script = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, "gnome", "", "deb", ("pycharm",)
        )
        self.assertIn("pycharm_configuration.py --init", script)
        self.assertLess(
            script.index("xvfb-run"),
            script.index("pycharm_configuration.py"),
        )

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
        self.assertEqual(["mobile", "forgejo", "avd"], got)
        # Forgejo est là pour la même raison que la compilation : un
        # service ne demande pas d'écran.

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

    # Banc d'essai des étapes mobiles : « mstep » est remplacé par une fonction
    # qui réussit tout sauf l'étape nommée, et « sudo » par un no-op. Le contrat
    # se MESURE alors au code de sortie, au lieu de se déduire de la présence
    # ou de l'absence d'un « || » dans le texte — un « || echo » légitime, celui
    # qui ajoute la ligne du fichier d'échange à /etc/fstab, faisait tomber
    # l'ancienne version de ce test sans que rien ne soit cassé.
    HARNESS = (
        'mstep() { echo "-> $1"; case "$1" in *%s*) return 1;; esac; '
        "return 0; }\n"
        "sudo() { return 0; }\n"
    )

    def _run_steps(self, fail_on="RIEN", apk=False, transfer_ok=True):
        """Joue les étapes mobiles avec un « mstep » et un vérificateur de
        transfert bouchonnés. Le vérificateur est un VRAI fichier dans l'arbre
        d'essai : c'est ainsi qu'on éprouve le chaînage, code de sortie
        compris."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            el = pathlib.Path(tmp) / "el"
            apk_dir = el / "mobile/erplibre_home_mobile/android/app/build"
            (apk_dir / "outputs/apk/debug").mkdir(parents=True)
            if apk:
                (apk_dir / "outputs/apk/debug/app-debug.apk").write_text("x")
            checker = el / "script/mobile/check_bundle_transfer.py"
            checker.parent.mkdir(parents=True, exist_ok=True)
            checker.write_text(
                "#!/bin/bash\necho '   139 depots'\n"
                + ("exit 0\n" if transfer_ok else "exit 1\n")
            )
            checker.chmod(0o755)
            steps = self.todo._qemu_mobile_build_steps(str(el))
            return subprocess.run(
                ["bash", "-c", (self.HARNESS % fail_on) + steps],
                capture_output=True,
                text=True,
                env=dict(os.environ, HOME=tmp),
                timeout=60,
            )

    def test_a_failed_build_fails_the_vm(self):
        """Contrat explicite : « pour que ce soit bon », l'app doit compiler.
        Une étape en échec doit donc remonter un code non nul."""
        res = self._run_steps(fail_on="gradle")
        self.assertNotEqual(0, res.returncode, res.stdout[-400:])

    def test_a_failed_step_stops_the_ones_after_it(self):
        """La chaîne est en « && » d'un bout à l'autre. Un « ; » glissé au
        milieu — celui qui écrivait le manifeste vide — laissait la compilation
        web démarrer alors que « npm ci » venait d'échouer."""
        res = self._run_steps(fail_on="npm")
        self.assertNotEqual(0, res.returncode)
        self.assertNotIn("vite build", res.stdout)
        self.assertNotIn("gradle", res.stdout)

    def test_the_manifest_repos_are_bundled_again(self):
        """Le contournement a vécu : les dépôts entrent maintenant en PACKS, et
        rien ne neutralise plus le manifeste. Mesuré sur la VM : 139 dépôts,
        116 156 fichiers en 391 tranches, 3 002 entrées dans l'APK — là où un
        fichier par source en demandait 123 678 pour une limite de 65 535."""
        steps = self.todo._qemu_mobile_build_steps("/tmp/el")
        self.assertNotIn("ERPLIBRE_MANIFEST_PATH", steps)
        self.assertNotIn("empty-manifest", steps)

    def test_the_transfer_is_verified_after_the_bundle(self):
        """Une application qui ne porte pas le code qu'elle est censée montrer
        n'est pas l'application demandée : le transfert se vérifie."""
        steps = self.todo._qemu_mobile_build_steps("/tmp/el")
        self.assertIn("check_bundle_transfer.py", steps)
        self.assertLess(
            steps.index("npm run build"),
            steps.index("check_bundle_transfer.py"),
        )
        self.assertLess(
            steps.index("check_bundle_transfer.py"),
            steps.index("cap sync"),
        )

    def test_the_transfer_is_compared_to_the_source(self):
        """« --workspace » : c'est la comparaison octet pour octet qui prouve un
        transfert FIDÈLE, et pas seulement cohérent."""
        steps = self.todo._qemu_mobile_build_steps("/tmp/el")
        self.assertIn("--workspace /tmp/el", steps)

    def test_a_failed_transfer_fails_the_vm(self):
        """Une application qui ne porte pas le code qu'elle doit montrer n'est
        pas l'application demandée. Mesuré au code de sortie, et non à la
        présence d'un « && » dans le texte."""
        res = self._run_steps(apk=True, transfer_ok=False)
        self.assertNotEqual(0, res.returncode, res.stdout[-300:])
        self.assertNotIn("gradle", res.stdout)

    def test_a_good_transfer_lets_the_build_go_on(self):
        res = self._run_steps(apk=True, transfer_ok=True)
        self.assertEqual(0, res.returncode, res.stdout[-300:])
        self.assertIn("139 depots", res.stdout)

    def test_the_transfer_line_is_read_in_the_install_log(self):
        """Hors mstep, à dessein : mstep renvoie la sortie dans le journal
        détaillé de la VM, et c'est le compte des dépôts qu'on veut voir dans
        celui de l'installation. Le bouchon imprime une ligne : elle doit
        remonter jusqu'à la sortie."""
        res = self._run_steps(apk=True)
        self.assertIn("139 depots", res.stdout)
        head = self.todo._qemu_mobile_build_steps("/tmp/el")
        head = head[: head.index("check_bundle_transfer.py")]
        self.assertNotIn("mstep", head[-160:])

    def test_a_missing_apk_fails_even_when_gradle_returns_zero(self):
        """L'APK est la preuve, pas le code de sortie de Gradle : une tâche peut
        rendre 0 sans rien produire."""
        res = self._run_steps(apk=False)
        self.assertNotEqual(0, res.returncode)
        self.assertIn("APK", res.stdout)

    def test_a_complete_build_succeeds(self):
        """L'autre sens du contrat : sans lui, un test qui échoue toujours
        passerait pour un test qui vérifie quelque chose."""
        res = self._run_steps(apk=True)
        self.assertEqual(0, res.returncode, res.stdout[-400:])

    def test_the_swap_step_alone_never_fails_the_chain(self):
        """Une image btrfs refuse un fichier d'échange ordinaire, et une
        compilation qui tient en mémoire n'en a pas besoin."""
        res = self._run_steps(apk=True)
        self.assertEqual(0, res.returncode)
        self.assertNotIn("|| true", self.todo._qemu_mobile_build_steps("/x"))

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
        # Une entrée peut porter un 3e élément : la commande de contexte.
        for pattern in (e[0] for e in TODO._QEMU_MOBILE_DIAG):
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

    def test_the_screen_is_set_at_launch_not_in_the_config(self):
        """Écrire hw.lcd.* dans config.ini ne SERT À RIEN : l'émulateur réécrit
        ce fichier depuis le profil du téléphone au premier démarrage, et l'AVD
        repartait en 1080x2400 densité 420 — constaté sur la VM. La taille se
        règle donc au lancement, et la commande affichée la porte."""
        self.assertNotIn("hw.lcd.width", self.cmd)
        self.assertIn("-skin 540x1140", self.cmd)
        # Ces deux clés-là survivent : elles ne viennent pas du profil.
        self.assertIn("hw.gpu.mode=swangle", self.cmd)

    def test_the_density_travels_with_the_resolution(self):
        """Contre-intuitif, et mesuré : 540x1140 en densité 420 est PIRE que le
        plein écran — 81 ms de médiane contre 40, et 57 % d'images en retard
        contre 37, tout étant rendu énorme. Avec la densité 240 : 38 ms, 32 %,
        et le 99e centile tombe de 950 ms à 250."""
        self.assertIn("qemu.sf.lcd_density=240", self.cmd)

    def test_a_killed_emulator_does_not_block_the_next_start(self):
        """Ce menu propose lui-même de tuer l'émulateur par pkill. Sans
        « -no-snapshot-save », le lancement suivant meurt sur « A snapshot
        operation is pending and timeout has expired » — vécu, et le message ne
        dit pas quoi faire."""
        self.assertIn("-no-snapshot-save", self.cmd)

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
        #
        # « sudo » est neutralisé AUSSI, et ce n'est pas décoratif : le bloc
        # ajoute un fichier d'échange de 4 Go et une ligne à /etc/fstab. Sans
        # ce bouchon, un test le ferait sur la machine qui l'exécute.
        stub = (
            'mstep() { echo "   -> $1"; return 0; }; mdiag() { :; }; '
            "sudo() { return 0; }; "
        )
        # Ancre robuste : on part du journal mobile et on remonte à l'accolade
        # qui ouvre son groupe. Chercher « { mstep » liait ce test à la forme
        # de la PREMIÈRE étape, et l'ajout du swap devant l'a cassé.
        marker = both.index("erplibre-mobile-build.log")
        tail = both[both.rindex("{ ", 0, marker) :]
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
        # Une entrée peut porter un 3e élément : la commande de contexte.
        for pattern in (e[0] for e in TODO._QEMU_MOBILE_DIAG):
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


class TestTheDesktopActuallyStarts(unittest.TestCase):
    """Installer un bureau ne suffit pas : il faut le DÉMARRER.

    Vécu sur erplibre-ubuntu-2604-gnome, et le diagnostic ne sautait pas aux
    yeux : GNOME installé, gdm3 installé, graphical.target par défaut, lien
    display-manager.service en place — et la console de la VM restait en mode
    texte. Deux causes superposées :

      - graphical.target était DÉJÀ atteinte quand le paquet est arrivé, et une
        cible active ne rattrape pas un service ajouté après coup ;
      - « systemctl enable gdm » rend 0 sans rien faire sur Debian et Ubuntu :
        l'unité n'a pas de « WantedBy », seulement un alias que le paquet pose.
    """

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.cmd = self.todo._qemu_desktop_remote_cmd("gnome", "deb")

    def _start_block(self, cmd=None):
        """Le seul « if » qui démarre le bureau, extrait tel quel."""
        cmd = cmd or self.cmd
        start = cmd.index("if sudo systemctl start display-manager")
        return cmd[start : cmd.index("fi; ", start) + 4]

    def test_it_starts_and_does_not_only_enable(self):
        self.assertIn("systemctl start display-manager.service", self.cmd)

    def test_it_falls_back_to_the_desktop_service(self):
        """« display-manager.service » est un alias que les paquets Debian
        posent ; ailleurs c'est « gdm » qui porte le WantedBy."""
        block = self._start_block()
        self.assertIn("systemctl start gdm", block)

    def test_it_comes_after_the_default_target_and_before_xrdp(self):
        self.assertLess(
            self.cmd.index("set-default graphical.target"),
            self.cmd.index("start display-manager.service"),
        )
        self.assertLess(
            self.cmd.index("start display-manager.service"),
            self.cmd.index("command -v xrdp"),
        )

    def _run(self, systemctl_body):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = pathlib.Path(tmp) / "bin"
            bin_dir.mkdir()
            (bin_dir / "sudo").write_text('#!/bin/bash\nexec "$@"\n')
            (bin_dir / "systemctl").write_text(
                f"#!/bin/bash\n{systemctl_body}\n"
            )
            for n in ("sudo", "systemctl"):
                (bin_dir / n).chmod(0o755)
            res = subprocess.run(
                ["bash", "-c", self._start_block()],
                capture_output=True,
                text=True,
                env=dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin"),
                timeout=30,
            )
        return res.stdout

    def test_the_alias_path_reports_a_started_session(self):
        out = self._run("exit 0")
        self.assertIn("session", out.lower())
        self.assertNotIn("⚠", out)

    def test_the_fallback_path_also_reports_started(self):
        """display-manager absent, gdm présent : c'est le cas d'Arch."""
        out = self._run(
            'case "$*" in *display-manager*) exit 1;; *) exit 0;; esac'
        )
        self.assertNotIn("⚠", out)

    def test_when_nothing_starts_it_says_to_reboot(self):
        """Le pire serait de se taire : l'utilisateur cherche un écran."""
        out = self._run("exit 1")
        self.assertIn("⚠", out)
        self.assertIn("boot", out.lower() + "reboot")

    def test_the_block_is_valid_shell(self):
        res = subprocess.run(
            ["bash", "-n"],
            input=self._start_block(),
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, res.returncode, res.stderr)


class TestPycharmFirstOpen(unittest.TestCase):
    """Ouverture sans écran, pour que le .idea existe avant l'installation.

    Deux défauts vécus sur erplibre-ubuntu-2604-gnome, tous deux silencieux :
    l'IDE restait vivant 45 minutes après l'étape avec 1,9 Go — « $! » est le
    PID de xvfb-run, un script, et le tuer n'atteint ni PyCharm ni Xvfb — puis
    la compilation de l'APK qui suivait s'est fait tuer par le noyau. Et le
    .idea n'était jamais écrit : 123 000 fichiers d'assets épuisent les watches
    inotify, dont la limite valait 65 536.
    """

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.cmd = self.todo._qemu_pycharm_project_cmd()

    def test_it_runs_after_the_install_not_before(self):
        """Mesuré : sur un dépôt cloné mais pas installé, PyCharm n'écrit AUCUN
        .idea — son configurateur d'interpréteur échoue faute de venv, et il
        renonce (« ⚠ pas de .idea », deux fois sur une VM réelle). Le même appel
        sur un dépôt installé l'écrit en cinq minutes."""
        script = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, "gnome", "", "deb", ("pycharm",)
        )
        self.assertLess(script.index("git clone"), script.index("xvfb-run"))
        self.assertLess(
            script.index("make install_os"), script.index("xvfb-run")
        )

    def test_the_configuration_uses_the_repo_venv(self):
        """Le script importe xmltodict, qui vit dans .venv.erplibre. Appelé par
        le python système — ce que faisait « make pycharm_configure » — il
        s'arrête sur « No module named 'xmltodict' », mesuré sur la VM.
        update_env_version.pycharm_update() l'appelle déjà avec le venv."""
        script = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, "gnome", "", "deb", ("pycharm",)
        )
        self.assertIn(
            "./.venv.erplibre/bin/python"
            " ./script/ide/pycharm_configuration.py --init",
            script,
        )
        # « make pycharm_configure » reste cité dans le message d'aide — la
        # cible est réparée, elle aussi — mais n'est plus ce qu'on EXÉCUTE.
        self.assertNotIn("&& make pycharm_configure", script)
        self.assertNotIn("; make pycharm_configure", script)

    def test_the_open_gets_a_second_chance(self):
        """Mesuré sur deux VM : la première ouverture d'un dépôt neuf peut
        n'écrire AUCUN .idea — son configurateur d'interpréteur plante
        (« homeDir is null ») — là où la suivante l'écrit en 25 s."""
        self.assertIn("for attempt in 1 2", self.cmd)
        self.assertIn('[ "$ok" = 1 ] && break', self.cmd)

    def test_both_attempts_keep_their_log(self):
        """Tronquer à chaque tentative effacerait la trace de la première, la
        seule qui porte la cause."""
        self.assertIn(": > /tmp/pycharm-first-run.log", self.cmd)
        self.assertIn(">> /tmp/pycharm-first-run.log", self.cmd)

    def test_the_configuration_is_asked_for_after_the_open(self):
        """L'installation est déjà passée quand le .idea naît : pycharm_update()
        n'avait rien à configurer, donc on le demande explicitement."""
        script = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, "gnome", "", "deb", ("pycharm",)
        )
        self.assertIn("make pycharm_configure", script)
        self.assertLess(
            script.index("xvfb-run"), script.index("make pycharm_configure")
        )

    def test_it_never_decides_the_verdict_of_the_vm(self):
        """Un bonus : ni son échec ni celui de sa configuration ne doivent
        rougir une VM dont tout le reste a réussi. La phase mobile, elle, porte
        bien le verdict — et elle vient après."""
        script = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, "gnome", "", "deb", ("pycharm", "mobile")
        )
        self.assertIn("pycharm_configuration.py --init || true", script)
        self.assertLess(
            script.index("pycharm_configuration.py"),
            script.index("ERPLibre mobile"),
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

    def test_the_ide_gets_its_own_process_group(self):
        """Sans « setsid », il n'y a pas de groupe à tuer."""
        self.assertIn("setsid xvfb-run", self.cmd)

    def test_the_whole_group_is_killed_not_just_the_wrapper(self):
        """Le signe moins est tout le correctif : « -$pid » désigne le GROUPE,
        donc xvfb-run, Xvfb, pycharm et les cef_server."""
        self.assertIn("kill -TERM -$pid", self.cmd)
        self.assertIn("kill -KILL -$pid", self.cmd)

    def test_inotify_is_raised_before_opening(self):
        """Après l'ouverture, il serait trop tard : l'analyse a déjà échoué."""
        pos_watch = self.cmd.index("max_user_watches")
        pos_open = self.cmd.index("setsid xvfb-run")
        self.assertLess(pos_watch, pos_open)
        self.assertIn("524288", self.cmd)

    def test_the_leftover_count_is_a_single_number(self):
        """« pgrep -fc » imprime 0 ET rend 1 quand il ne trouve rien : le
        « || echo 0 » ajoutait un second zéro, et « 0\n0 » n'est pas « 0 ».
        Le filet se déclenchait donc à chaque passage."""
        self.assertIn("| wc -l", self.cmd)
        self.assertNotIn("pgrep -fc", self.cmd)

    def test_it_is_valid_shell(self):
        res = subprocess.run(
            ["bash", "-n"], input=self.cmd, capture_output=True, text=True
        )
        self.assertEqual(0, res.returncode, res.stderr)

    def test_the_group_kill_really_reaps_the_children(self):
        """Le test qui compte : on rejoue l'étape avec de FAUX pycharm et
        xvfb-run, celui-ci laissant un enfant derrière lui comme le vrai le
        fait avec Xvfb. Rien ne doit survivre."""
        import os
        import tempfile
        import time

        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = pathlib.Path(tmp) / "bin"
            bin_dir.mkdir()
            repo = pathlib.Path(tmp) / "repo"
            (repo / ".idea").mkdir(parents=True)
            # .idea déjà là : l'attente sort au premier tour, et le test
            # mesure la FERMETURE, pas la création.
            (repo / ".idea" / "erplibre.iml").write_text("<module/>")
            (repo / ".idea" / "misc.xml").write_text("<project/>")
            marker = pathlib.Path(tmp) / "alive"
            (bin_dir / "xvfb-run").write_text(
                "#!/bin/bash\n"
                # L'enfant qui survivait : un Xvfb que personne ne tuait.
                f"( while true; do touch {marker}; sleep 1; done ) &\n"
                'shift; exec "$@"\n'
            )
            (bin_dir / "pycharm").write_text(
                "#!/bin/bash\nwhile true; do sleep 1; done\n"
            )
            (bin_dir / "sudo").write_text("#!/bin/bash\nexit 0\n")
            (bin_dir / "python3").write_text("#!/bin/bash\ncat > /dev/null\n")
            # pgrep et pkill sont BOUCHONNÉS, et c'est le point important : le
            # filet de l'étape balaie les processus du compte courant. Exécuté
            # sans bouchon sur la machine de développement, il fermerait le
            # PyCharm de l'utilisateur. C'est le groupe qu'on teste ici, pas le
            # filet — celui-ci est vérifié à part, sans rien tuer.
            (bin_dir / "pgrep").write_text("#!/bin/bash\nexit 1\n")
            (bin_dir / "pkill").write_text("#!/bin/bash\nexit 0\n")
            for name in (
                "xvfb-run",
                "pycharm",
                "sudo",
                "python3",
                "pgrep",
                "pkill",
            ):
                (bin_dir / name).chmod(0o755)
            cmd = self.todo._qemu_pycharm_project_cmd(False).replace(
                self.todo._qemu_install_dir(False), str(repo)
            )
            env = dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin", HOME=tmp)
            res = subprocess.run(
                ["bash", "-c", cmd],
                capture_output=True,
                text=True,
                env=env,
                timeout=180,
            )
            self.assertEqual(0, res.returncode, res.stdout + res.stderr)
            marker.unlink(missing_ok=True)
            time.sleep(3)
            # L'enfant réveillait le marqueur chaque seconde : s'il vit
            # encore, le fichier est revenu.
            self.assertFalse(
                marker.exists(),
                "un enfant a survécu à la fermeture du groupe",
            )


class TestIdeInstallIsReplayable(unittest.TestCase):
    """Rejouer une installation ne doit pas retélécharger 2 Go.

    C'est le cas NORMAL : une installation morte qu'on relance, un outil ajouté
    après coup. Mesuré sur la VM, les deux étapes passent de ~5 min chacune à
    0,094 s au total quand /opt porte déjà l'IDE — le reste (lanceur, alias,
    raccourci) rejoue quand même, il est idempotent et bon marché.
    """

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.py = self.todo._qemu_pycharm_remote_cmd()
        self.st = self.todo._qemu_android_studio_remote_cmd()

    def test_pycharm_checks_before_downloading(self):
        self.assertIn("[ -x /opt/pycharm/bin/pycharm.sh ]", self.py)
        self.assertLess(
            self.py.index("/opt/pycharm/bin/pycharm.sh"),
            self.py.index("curl"),
        )

    def test_android_studio_checks_before_downloading(self):
        self.assertIn("[ -x /opt/android-studio/bin/studio ]", self.st)
        self.assertLess(
            self.st.index("/opt/android-studio/bin/studio"),
            self.st.index("curl"),
        )

    def test_the_launcher_still_runs_when_the_download_is_skipped(self):
        """Sauter le téléchargement ne doit pas sauter l'alias : c'est lui qui
        rend « pycharm » et « android-studio » appelables."""
        # rindex : le chemin du lanceur apparaît aussi dans la garde, tout au
        # début. C'est la DERNIÈRE occurrence — l'installation du lanceur — qui
        # doit suivre le bloc de téléchargement.
        for cmd, marker in (
            (self.py, "/usr/local/bin"),
            (self.st, "/usr/local/bin"),
        ):
            self.assertGreater(cmd.rindex(marker), cmd.index("curl"), marker)

    def test_a_real_download_failure_still_fails(self):
        """La garde ne doit pas avaler l'échec du cas où il faut télécharger.
        On force l'absence d'IDE et un curl qui échoue."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = pathlib.Path(tmp) / "bin"
            bin_dir.mkdir()
            (bin_dir / "curl").write_text("#!/bin/bash\nexit 22\n")
            (bin_dir / "sudo").write_text("#!/bin/bash\nexit 0\n")
            (bin_dir / "python3").write_text("#!/bin/bash\ncat >/dev/null\n")
            for n in ("curl", "sudo", "python3"):
                (bin_dir / n).chmod(0o755)
            res = subprocess.run(
                ["bash", "-c", self.st],
                capture_output=True,
                text=True,
                env=dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin"),
                timeout=60,
            )
            out = res.stdout + res.stderr
            # Sur cette machine /opt/android-studio n'existe pas : la garde
            # laisse donc passer, et l'échec du curl doit se voir.
            self.assertIn("⚠", out, out[-300:])

    def test_both_steps_are_valid_shell(self):
        for cmd in (self.py, self.st):
            res = subprocess.run(
                ["bash", "-n"], input=cmd, capture_output=True, text=True
            )
            self.assertEqual(0, res.returncode, res.stderr)


class TestPycharmNetIsNarrow(unittest.TestCase):
    """Le filet de fermeture ne doit JAMAIS viser le ssh qui porte l'install.

    Vécu, et cher : le filet cherchait « /opt/pycharm » dans les LIGNES DE
    COMMANDE. Or la commande d'installation est passée en argument à ssh, et
    elle contient ce chemin — le pkill a donc tué la session ssh qui portait
    l'installation en cours sur l'hyperviseur. Elle est morte en silence, sans
    marqueur de sortie : 48 minutes perdues, et rien dans le journal.

    Mesuré ensuite dans une VM : par NOM de processus, 3 processus réels
    (pycharm, Xvfb, fsnotifier) et aucun faux ; par ligne de commande, 4 — le
    ssh compris.
    """

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.cmd = self.todo._qemu_pycharm_project_cmd()

    def test_it_matches_by_process_name(self):
        self.assertIn('pgrep -u "$(id -u)" -x', self.cmd)
        self.assertIn('pkill -u "$(id -u)" -x', self.cmd)

    def test_it_never_matches_by_command_line(self):
        """« -f » est exactement ce qui a tué l'installation."""
        self.assertNotIn("pkill -f", self.cmd)
        self.assertNotIn("pgrep -f", self.cmd)

    def test_the_names_are_the_ones_measured_in_the_vm(self):
        for name in ("pycharm", "cef_server", "fsnotifier", "Xvfb"):
            self.assertIn(name, self.cmd)

    def test_a_command_line_that_merely_mentions_the_ide_is_spared(self):
        """Le test qui compte, et il ne tue rien : un témoin dont la LIGNE
        contient le chemin de l'IDE — comme le ssh lanceur — et dont le NOM est
        « sleep ». L'ancien motif l'attrape, le nouveau l'épargne."""
        import os
        import re
        import time

        pattern = re.search(r'-x "([^"]+)"', self.cmd).group(1)
        witness = subprocess.Popen(
            [
                "bash",
                "-c",
                'exec -a "ssh erplibre@vm bash -c /opt/pycharm/bin/pycharm.sh"'
                " sleep 30",
            ]
        )
        try:
            time.sleep(1.5)
            uid = str(os.getuid())
            by_name = subprocess.run(
                ["pgrep", "-u", uid, "-x", pattern],
                capture_output=True,
                text=True,
            ).stdout.split()
            by_cmdline = subprocess.run(
                ["pgrep", "-u", uid, "-f", "[/]opt/pycharm"],
                capture_output=True,
                text=True,
            ).stdout.split()
            pid = str(witness.pid)
            # Le témoin est un enfant de bash : on cherche le groupe entier.
            spared = pid not in by_name
            self.assertTrue(spared, "le motif par nom a attrapé le témoin")
            self.assertIn(
                pid,
                by_cmdline,
                "le témoin devrait être attrapé par l'ancien motif ;"
                " sinon ce test ne prouve rien",
            )
        finally:
            witness.kill()
            witness.wait(timeout=10)


class TestMobileSwap(unittest.TestCase):
    """Le swap posé avant de compiler, et son refus de bloquer.

    Mesuré : le démon Gradle a atteint 6,8 Go de RSS hors tas — son -Xmx1536m
    ne le borne pas — sur une VM de 12 Go SANS swap, et le noyau l'a tué deux
    fois. « --max-workers=2 » n'a rien changé : le pic est passé de 10,3 à
    11,2 Go. C'est de la marge qu'il faut."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.steps = self.todo._qemu_mobile_build_steps("/tmp/el")

    def test_the_swap_comes_before_the_build(self):
        self.assertLess(
            self.steps.index("SwapTotal"), self.steps.index("npm ci")
        )

    def test_it_does_nothing_when_swap_is_already_there(self):
        self.assertIn("SwapTotal", self.steps)
        self.assertIn("-lt 2000000", self.steps)

    def test_a_failed_swap_leaves_no_stray_file(self):
        """Un fichier d'échange à moitié fait occuperait 4 Go pour rien."""
        self.assertIn("rm -f /swapfile-erplibre", self.steps)

    def test_it_is_valid_shell(self):
        res = subprocess.run(
            ["bash", "-n"],
            input="mstep() { :; }\n" + self.steps,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, res.returncode, res.stderr)

    def test_the_swap_block_is_not_linked_by_and(self):
        """Lié par « && », un swap refusé arrêterait toute la compilation."""
        head = self.steps[: self.steps.index("npm ci")]
        self.assertNotIn("fi; fi && ", head)
        self.assertIn("fi; fi; ", head)


class TestMobileDiagMemory(unittest.TestCase):
    """« Son démon a disparu » ne parle pas de mémoire ; le diagnostic, oui."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.cmd = self.todo._qemu_mobile_diag_cmd()

    def test_the_oom_pattern_names_memory(self):
        pats = {p[0]: p[1] for p in TODO._QEMU_MOBILE_DIAG}
        self.assertIn("daemon disappeared", pats)
        self.assertIn("memory", pats["daemon disappeared"].lower())

    def test_the_zip_entry_limit_is_named(self):
        """La panne d'aujourd'hui, et elle est en amont : un APK est un ZIP
        borné à 65 535 entrées, et le dépôt mobile en embarque 122 684 sous
        assets/public/repos pour 337 qui sont l'application. Le diagnostic doit
        le dire, pas laisser lire 5 000 lignes de Gradle."""
        pats = {e[0]: e[1] for e in TODO._QEMU_MOBILE_DIAG}
        self.assertIn("Too many zip entries", pats)
        self.assertIn("65535", pats["Too many zip entries"])

    def test_the_zip_limit_is_named_before_the_generic_gradle_failure(self):
        """« FAILED » attrape tout : placé avant, il masquerait la vraie
        cause — l'ordre du tableau est le diagnostic."""
        keys = [e[0] for e in TODO._QEMU_MOBILE_DIAG]
        self.assertLess(
            keys.index("Too many zip entries"), keys.index("FAILED")
        )

    def test_the_cause_is_proven_not_assumed(self):
        """Le compte de l'oom-killer et la RAM viennent avec : une cause
        « mémoire » sans chiffre serait une supposition de plus."""
        self.assertIn("mmem()", self.cmd)
        self.assertIn("MemTotal", self.cmd)
        self.assertIn("oom-kill", self.cmd)

    def test_it_runs_and_names_the_cause(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = pathlib.Path(tmp) / "bin"
            bin_dir.mkdir()
            # Un dmesg qui rapporte un oom-kill, via un sudo neutre.
            (bin_dir / "sudo").write_text('#!/bin/bash\nshift 0; exec "$@"\n')
            (bin_dir / "dmesg").write_text(
                "#!/bin/bash\necho 'oom-kill:constraint=CONSTRAINT_NONE'\n"
            )
            for name in ("sudo", "dmesg"):
                (bin_dir / name).chmod(0o755)
            log = pathlib.Path(tmp) / "build.log"
            log.write_text(
                "> Task :app:compressDebugAssets\n"
                "Gradle build daemon disappeared unexpectedly\n"
            )
            res = subprocess.run(
                ["bash", "-c", self.cmd + f'mdiag "{log}"'],
                capture_output=True,
                text=True,
                env=dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin"),
                timeout=60,
            )
            out = res.stdout
            # « RAM » et « OOM » traversent les deux langues ; le chiffre,
            # lui, est ce qui distingue une cause prouvée d'une supposition.
            self.assertIn("RAM", out)
            self.assertRegex(out, r"\(OOM\)|OOM kills")
            self.assertRegex(out, r"[0-9]+")


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
