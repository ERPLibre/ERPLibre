#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installation des dépendances ERPLibre sur NixOS.

Les quatre autres scripts de distribution POSENT des paquets ; celui-ci n'en
pose aucun. Il dépose une déclaration et demande au système de s'y conformer,
parce que c'est la seule façon dont une dépendance dure là-bas : ce qui est
installé à la main vit hors de la configuration et disparaît à la
reconstruction suivante.

Ce que ces tests gardent :

- l'aiguillage reconnaît « nixos ». Sans cette branche, install_dev.sh tombe
  dans son « else », appelle le script Debian, et celui-ci sort en erreur dès
  la détection du système — avant même d'essayer un apt-get qui n'existe pas ;
- les DEUX options qui portent tout le reste sont déclarées. Sans envfs, /bin
  et /usr/bin restent vides : le Makefile force « SHELL := /bin/bash » et
  toute cible échoue avant sa première ligne, tandis que
  lib_python_provider.sh ne cherche l'interpréteur du système qu'en
  /usr/bin/pythonX.Y. Sans nix-ld, aucune roue manylinux ni aucun binaire
  téléchargé ne s'exécute ;
- la version de Python déclarée répond à celle que le dépôt demande ;
- le compte du rôle PostgreSQL est substitué, jamais écrit en dur.
"""

import re
import subprocess
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
MODULE = RACINE / "conf/nixos/erplibre.nix"
SCRIPT = RACINE / "script/install/install_nixos_dependency.sh"
AIGUILLAGE = RACINE / "script/install/install_dev.sh"


def _deploy_qemu():
    """deploy_qemu.py chargé comme module, comme le fait todo.py."""
    import importlib.util
    import sys

    sys.argv = ["todo.py"]
    chemin = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()


class LAiguillage(unittest.TestCase):
    def setUp(self):
        self.src = AIGUILLAGE.read_text(encoding="utf-8")

    def test_nixos_has_its_own_branch(self):
        self.assertIn('"${ID}" == "nixos"', self.src)
        self.assertIn("install_nixos_dependency.sh", self.src)

    def test_it_is_decided_before_the_debian_fallback(self):
        """Le « else » de fin appelle le script Debian : une branche placée
        après lui ne serait jamais atteinte."""
        self.assertLess(
            self.src.index('"${ID}" == "nixos"'),
            self.src.rindex("install_debian_dependency.sh"),
        )

    def test_the_supported_list_names_it(self):
        """Le message de repli énumère les systèmes supportés : en omettre un
        qu'on supporte fait douter de celui qu'on lit."""
        ligne = [x for x in self.src.splitlines() if "not supported" in x][-1]
        self.assertIn("NixOS", ligne)


class LeScript(unittest.TestCase):
    def setUp(self):
        self.src = SCRIPT.read_text(encoding="utf-8")

    def test_it_is_valid_shell(self):
        fini = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(0, fini.returncode, fini.stderr)

    def test_it_is_executable(self):
        """git saute silencieusement un script sans bit d'exécution, et
        install_dev.sh l'appelle directement."""
        import os

        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_it_refuses_another_system(self):
        """Déposer un module NixOS ailleurs ne ferait rien de bon, et le
        « nixos-rebuild » qui suit n'existerait pas."""
        self.assertIn("ID=nixos", self.src)

    def test_the_import_is_added_once(self):
        """Relancé, le script ne doit pas empiler les imports : la
        configuration ne compilerait plus."""
        self.assertIn('grep -q "erplibre.nix"', self.src)

    def test_it_says_when_there_is_no_imports_block(self):
        """Une configuration sans « imports = [ » laisserait le module mort :
        NixOS ne lit que ce que la configuration importe."""
        self.assertIn("imports = [", self.src)
        self.assertIn("exit 1", self.src)

    def test_the_python_version_comes_from_the_repository(self):
        """Une version écrite ici dériverait de .python-odoo-version au
        premier changement."""
        self.assertIn(".python-odoo-version", self.src)

    def test_it_verifies_what_the_module_promised(self):
        """Sans /bin/bash, la moindre cible make échoue avant sa première
        ligne : le dire ici plutôt qu'une heure plus tard, ailleurs."""
        for chemin in ("/bin/bash", "/usr/bin/env"):
            self.assertIn(chemin, self.src)


class LeModule(unittest.TestCase):
    def setUp(self):
        self.src = MODULE.read_text(encoding="utf-8")

    def test_the_two_hinges_are_declared(self):
        """envfs pour /bin et /usr/bin, nix-ld pour les binaires étrangers :
        sans l'une des deux, rien de ce dépôt ne fonctionne."""
        self.assertIn("services.envfs.enable = true;", self.src)
        self.assertIn("programs.nix-ld.enable = true;", self.src)

    def test_what_compiles_here_is_also_given_to_the_loader(self):
        """Un module compilé sur place n'a pas de RPATH : son « .so » ne
        retrouve sa bibliothèque à l'IMPORT que par LD_LIBRARY_PATH, donc par
        ce que nix-ld déclare. Déclarer l'en-tête sans la bibliothèque fait
        réussir la compilation et échouer l'import."""
        entetes = ("openldap", "cups", "libmysqlclient")
        loader = self.src.split("programs.nix-ld.libraries")[1].split("];")[0]
        for lib in entetes:
            with self.subTest(lib=lib):
                self.assertIn(lib, loader)

    def test_pg_config_is_its_own_derivation(self):
        """Il n'est ni dans postgresql ni dans sa sortie « .dev », et
        psycopg2 s'arrête sur « pg_config executable not found »."""
        self.assertIn("postgresql.pg_config", self.src)

    def test_the_dynamic_loader_gets_what_the_wheels_ask(self):
        """Une roue manylinux qui ne trouve pas sa bibliothèque échoue à
        l'IMPORT, pas à l'installation : bien plus tard, et sans rapport
        apparent avec pip."""
        for lib in ("libpq", "libxml2", "libxslt", "openssl", "zlib"):
            with self.subTest(lib=lib):
                self.assertIn(lib, self.src)

    def test_the_python_matches_what_the_repository_wants(self):
        """DÉPENDANCE DÉCLARÉE : « .python-odoo-version » est ÉCRIT par
        l'installation, pas suivi par git. Un checkout qui n'a pas encore
        installé ne le porte pas, et le lire sans condition faisait lever
        cette épreuve au lieu de la dire ignorée — la même règle que le
        lanceur applique au dépôt mobile.
        """
        marque = RACINE / ".python-odoo-version"
        if not marque.exists():
            self.skipTest(
                f"{marque.name} absent : installation pas encore faite"
            )
        voulu = marque.read_text().strip()
        majeur, mineur = voulu.split(".")[:2]
        self.assertIn(f"python{majeur}{mineur}", self.src)

    def test_the_database_role_is_substituted(self):
        """Le nom du compte varie d'un déploiement à l'autre ; l'écrire en dur
        donnerait un rôle qui ne correspond à personne."""
        self.assertIn("@EL_USER@", self.src)
        self.assertIn("ensureClauses.superuser = true;", self.src)

    def test_the_placeholder_is_the_one_the_script_replaces(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marque in set(re.findall(r"@[A-Z_]+@", self.src)):
            with self.subTest(marque=marque):
                self.assertIn(marque, script)

    def test_what_npm_cannot_install_is_declared_instead(self):
        """Les quatre autres scripts posent lessc et rtlcss par « npm install
        -g ». Ici le préfixe npm EST le store, en lecture seule : le geste
        échoue. nixpkgs porte les deux, et une déclaration ne s'installe
        pas — elle tient."""
        self.assertIn("nodePackages.less", self.src)
        self.assertIn("nodePackages.rtlcss", self.src)
        self.assertNotIn("npm install -g", self.src)

    def test_the_pager_and_the_less_compiler_are_two_things(self):
        """« less » le paginateur et « less » le compilateur LESS portent le
        même nom et ne se remplacent pas : les deux sont déclarés."""
        lignes = [x.strip() for x in self.src.splitlines()]
        self.assertIn("less", lignes)
        self.assertIn("nodePackages.less", lignes)

    def test_postgis_is_a_server_plugin_not_a_package(self):
        """Déclarée hors du serveur, l'extension ne serait pas chargeable par
        « CREATE EXTENSION »."""
        self.assertIn("extensions = ps:", self.src)
        self.assertIn("postgis", self.src)

    def test_a_compiler_outside_a_nix_shell_finds_the_headers(self):
        """Sans ces variables, ce qui n'a pas de roue amont ne se compile pas :
        gcc ne cherche ni en-têtes ni bibliothèques dans le profil système."""
        for var in ("CPATH", "LIBRARY_PATH", "PKG_CONFIG_PATH"):
            with self.subTest(var=var):
                self.assertIn(var, self.src)

    def test_the_variables_reach_a_non_interactive_ssh(self):
        """« environment.variables » n'écrit que dans /etc/set-environment,
        que seul un shell de CONNEXION lit. Le déploiement, lui, installe par
        « ssh hôte 'commande' » : la variable y serait vide."""
        self.assertIn("environment.sessionVariables", self.src)
        self.assertNotIn("environment.variables", self.src)

    def test_the_html_manuals_are_left_out(self):
        """NixOS installe la sortie « doc » de CHAQUE paquet du système
        (extraOutputsToInstall vaut « man info doc »). Celle de CPython n'est
        pas dans le cache binaire : le premier rebuild la BÂTIT, un Sphinx de
        trois mille pages qui domine le temps d'installation et fait cesser de
        répondre une machine étroite.

        « documentation.doc » et non « documentation » : les pages de manuel
        et info restent, elles se lisent depuis un terminal."""
        self.assertIn("documentation.doc.enable = false;", self.src)
        self.assertNotIn("documentation.enable", self.src)

    def test_the_install_reads_the_paths_off_the_filesystem(self):
        """Une session reçoit les variables du module à son OUVERTURE, par
        pam_env. L'installation applique le module (« make install_os ») puis
        compile (« make install_odoo_18 ») dans la MÊME session : la sienne
        est plus vieille que ce qu'elle vient de déclarer.

        Les trois paquets du verrou qui n'ont pas de roue amont s'arrêtaient
        alors sur « lber.h », « cups/http.h » et « mysql.h » — au PREMIER
        passage seulement, ce qui est la pire des pannes : le second réussit
        et donne raison à tort. env_var.sh relit donc le profil courant du
        système, un lien sur le disque, plutôt qu'une variable héritée."""
        env = (RACINE / "env_var.sh").read_text(encoding="utf-8")
        self.assertIn("if [ -d /run/current-system/sw ]", env)
        for var in ("CPATH", "LIBRARY_PATH", "PKG_CONFIG_PATH"):
            with self.subTest(var=var):
                self.assertIn(f"export {var}=", env)
                self.assertIn("/run/current-system/sw", env)

    def test_nothing_is_exported_off_nixos(self):
        """Le garde est le répertoire lui-même : ailleurs, aucune de ces
        variables n'est touchée."""
        env = (RACINE / "env_var.sh").read_text(encoding="utf-8")
        bloc = env.split("if [ -d /run/current-system/sw ]")[1].split("fi")[0]
        self.assertNotIn("\nexport", bloc.replace("\n  export", ""))

    def test_the_headers_are_linked_into_the_profile(self):
        """Le profil ne porte pas « /include » par défaut : sans cette ligne,
        déclarer une sortie « .dev » ne met les en-têtes nulle part, et
        « fatal error: lber.h » reste entier."""
        self.assertIn("environment.pathsToLink", self.src)
        self.assertIn('"/include"', self.src)


class LHoteSansGestionnaire(unittest.TestCase):
    """Ce que le menu répond sur un système où rien ne s'installe.

    « Aucun gestionnaire connu » est vrai sur NixOS et n'y mène nulle part :
    la phrase seule ferme la porte, alors que deux gestes l'ouvrent — le shell
    jetable pour essayer, la déclaration pour ce qui reste.
    """

    def setUp(self):
        from script.todo import todo_install

        self.ti = todo_install
        self._vrai = todo_install.os_id
        self.addCleanup(setattr, todo_install, "os_id", self._vrai)

    def test_a_nixos_host_is_told_what_works_instead(self):
        self.ti.os_id = lambda: "nixos"
        conseil = self.ti.conseil_sans_gestionnaire()
        self.assertIn("nix-shell -p", conseil)
        self.assertIn("configuration.nix", conseil)

    def test_nothing_is_invented_elsewhere(self):
        """Sur une machine dont on ne sait rien, inventer un conseil vaut
        moins que de se taire."""
        for ident in ("debian", "fedora", "arch", ""):
            with self.subTest(ident=ident):
                self.ti.os_id = lambda ident=ident: ident
                self.assertEqual("", self.ti.conseil_sans_gestionnaire())

    def test_both_dead_ends_carry_it(self):
        """Deux endroits impriment « aucun gestionnaire » : celui que tout le
        menu partage, et celui de virt-viewer."""
        for chemin in (
            "script/todo/todo_install.py",
            "script/todo/qemu_access.py",
        ):
            with self.subTest(chemin=chemin):
                src = (RACINE / chemin).read_text(encoding="utf-8")
                i = src.index("no known package manager here.")
                self.assertIn("conseil_sans_gestionnaire", src[i : i + 400])


class LeServiceEstDeclare(unittest.TestCase):
    """Sur NixOS, /etc est généré depuis le store et monté en lecture seule.

    L'installation dépose l'unité par « tee /etc/systemd/system/
    erplibre.service » sur toute autre distribution ; ici le tee échoue sur
    « Read-only file system », et l'installation entière rend 1 à sa dernière
    étape, après que le dépôt, le venv, les modules compilés et un démarrage
    d'Odoo ont tous réussi. L'unité vient donc de la configuration.
    """

    def setUp(self):
        self.src = MODULE.read_text(encoding="utf-8")
        self.script = SCRIPT.read_text(encoding="utf-8")

    def test_the_unit_is_declared_in_the_module(self):
        self.assertIn("systemd.services.erplibre", self.src)
        self.assertIn('Type = "simple";', self.src)
        self.assertIn('User = "@EL_USER@";', self.src)

    def test_it_starts_at_boot_without_a_symlink(self):
        """« systemctl enable » activerait par un lien dans /etc, que le
        système refuse d'écrire. « wantedBy » en est l'équivalent déclaratif,
        et c'est la seule forme d'activation qui tienne ici.

        L'absence de « systemctl enable » se vérifie sur la COMMANDE du menu,
        plus bas : un module Nix n'exécute rien, et l'y chercher interdirait
        au commentaire de nommer ce qu'il explique."""
        self.assertIn('wantedBy = [ "multi-user.target" ];', self.src)

    def test_the_interpreter_comes_from_the_store(self):
        """/bin et /usr/bin sont un montage FUSE d'envfs, et systemd résout
        l'exécutable d'ExecStart lui-même, hors de portée de ce montage :
        « /bin/bash » y rend « 203/EXEC ». Avec Restart=always, l'unité boucle
        indéfiniment."""
        self.assertIn('ExecStart = "${pkgs.bash}/bin/bash', self.src)
        self.assertNotIn('ExecStart = "/bin/bash', self.src)
        self.assertNotIn('ExecStart = "/usr/bin/env', self.src)

    def test_the_unit_carries_the_path_its_scripts_need(self):
        """Une unité ne reçoit pas le PATH d'une session. run.sh lance des
        scripts dont le shebang est « env bash » : env est dans le PATH par
        défaut, bash non, et run.sh s'arrête avant Odoo."""
        self.assertIn("path = with pkgs; [ bash python312 ];", self.src)

    def test_the_repository_is_not_guessed(self):
        """Le service lance le dépôt QUI A POSÉ le module. Écrire
        « /home/$USER/git/erplibre » se tromperait sur une installation de
        production, qui vit sous /opt."""
        self.assertIn('WorkingDirectory = "@EL_DIR@";', self.src)
        self.assertIn("EL_DIR=${EL_DIR:-${PWD}}", self.script)

    def test_both_placeholders_are_substituted(self):
        """Un marqueur non substitué partirait tel quel dans /etc/nixos et
        ferait échouer l'évaluation du module."""
        for marqueur in ("@EL_USER@", "@EL_DIR@"):
            with self.subTest(marqueur=marqueur):
                self.assertIn(marqueur, self.src)
                self.assertIn(marqueur, self.script)


class CeQueLeDepotAPPELLE_ParSonNomNu(unittest.TestCase):
    """Un système déclaratif n'a que ce qui est écrit.

    Les quatre autres distributions posent ces outils par leur gestionnaire
    de paquets ; ici, l'absence ne se voit qu'à l'usage, et tard.
    """

    def setUp(self):
        self.src = MODULE.read_text(encoding="utf-8")

    def test_xmlsec_is_declared(self):
        """Le manifeste d'auth_saml (OCA server-auth, dans l'addons_path)
        déclare « bin: ["xmlsec1"] » : Odoo REFUSE d'installer et de mettre à
        niveau le module tant que le binaire n'est pas dans le PATH."""
        self.assertIn("\n    xmlsec\n", self.src)

    def test_the_tools_called_by_bare_name_are_declared(self):
        """« parallel » et « shfmt » sont invoqués sans chemin. Sans
        parallel, « make db_drop_all » annonce des bases détruites qui ne
        l'ont pas été."""
        for outil in ("parallel", "shfmt"):
            with self.subTest(outil=outil):
                self.assertIn(f"\n    {outil}\n", self.src)

    def test_growpart_has_a_provider(self):
        """L'agrandissement s'écrit « sudo growpart … || true » : sans le
        binaire il rend 0 sans rien agrandir, et la VM garde la taille de son
        image pendant que le déploiement annonce celle demandée."""
        self.assertIn("\n    cloud-utils\n", self.src)


class LAgentInviteVientDuDepot(unittest.TestCase):
    """L'image épinglée active déjà l'agent — et c'est le problème : la
    garantie appartient alors au tiers qui la rebâtit.

    Les quatre autres distributions le reçoivent du runcmd, qui appelle leur
    gestionnaire de paquets. Sur un système déclaratif, c'est cette ligne ou
    rien.
    """

    def setUp(self):
        self.src = MODULE.read_text(encoding="utf-8")

    def test_the_agent_is_declared(self):
        self.assertIn("services.qemuGuest.enable = true;", self.src)

    def test_its_path_carries_what_guest_exec_runs(self):
        """Une unité systemd n'hérite pas du profil du système. « guest-exec »
        exécute les commandes du produit DANS ce PATH, et l'agrandissement
        commence par « findmnt -no SOURCE / » : absent, code 127 dès la
        première ligne."""
        i = self.src.index("systemd.services.qemu-guest-agent.path")
        bloc = self.src[i : self.src.index("];", i)]
        for paquet in ("util-linux", "e2fsprogs", "cloud-utils"):
            with self.subTest(paquet=paquet):
                self.assertIn(paquet, bloc)


class LesReglagesRegionauxDemandes(unittest.TestCase):
    """cloud-init applique la locale par locale-gen et update-locale, qui
    n'existent pas ici : la VM gardait le défaut de NixOS. Mesuré —
    « fr_CA.UTF-8 » demandé, « en_US.UTF-8 » obtenu.

    Le fuseau, lui, marchait déjà : cloud-init pose /etc/localtime, que NixOS
    laisse mutable tant que l'option n'est pas déclarée. Le déclarer ne
    répare rien, il fait passer la garantie du côté du module.
    """

    def setUp(self):
        self.src = MODULE.read_text(encoding="utf-8")
        self.script = SCRIPT.read_text(encoding="utf-8")

    def test_both_are_declared(self):
        self.assertIn("i18n.defaultLocale", self.src)
        self.assertIn("time.timeZone", self.src)

    def test_nothing_is_imposed_when_nothing_was_asked(self):
        """Sur une NixOS que l'on avait déjà — installée par « --hote » —
        l'option ne doit pas être définie du tout : un défaut écrit ici
        écraserait le réglage de son propriétaire sans le dire."""
        for marqueur in ("@EL_LOCALE@", "@EL_TZ@"):
            with self.subTest(marqueur=marqueur):
                self.assertIn(f'lib.mkIf ("{marqueur}" != "")', self.src)

    def test_the_values_come_from_what_the_deployment_asked(self):
        """Lues là où cloud-init garde ce qu'il a reçu, et non devinées."""
        self.assertIn("cloud-config.txt", self.script)
        self.assertIn("lire_seed locale", self.script)
        self.assertIn("lire_seed timezone", self.script)

    def test_both_markers_are_substituted(self):
        """Un marqueur non substitué partirait tel quel dans /etc/nixos et
        ferait échouer l'évaluation du module."""
        for marqueur in ("@EL_LOCALE@", "@EL_TZ@"):
            with self.subTest(marqueur=marqueur):
                self.assertIn(marqueur, self.script)

    def test_the_cost_is_written_down(self):
        """Une reconstruction qui bâtit glibc-locales est longue et muette :
        prise pour un blocage, elle se fait interrompre."""
        self.assertIn("glibc-locales", self.src)


class LAutoriteAtteintToutCeQuiTelecharge(unittest.TestCase):
    """nix a son fragment de service ; curl, git et le reste n'ont rien.

    Les quatre familles impératives posent l'autorité dans le magasin du
    système et tout la trouve seul. Ici l'autorité est un faisceau sous un
    chemin inscriptible, que rien ne consulte sans qu'on le dise — et le
    clone du dépôt échouait donc sur « self-signed certificate in
    certificate chain » alors que nix, lui, téléchargeait très bien.

    Deux moitiés qui se relaient : la commande d'installation porte ses
    variables elle-même, car elle tourne AVANT la première reconstruction et
    aucun chemin PAM n'est inscriptible d'ici là — mesuré, le pam_env de
    sshd porte « readenv=0 » et son fichier est un lien vers le store. Le
    module prend le relais pour les sessions d'après.
    """

    def setUp(self):
        self.src = MODULE.read_text(encoding="utf-8")
        self.script = SCRIPT.read_text(encoding="utf-8")

    def _exports(self):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        return TODO.__new__(TODO)._qemu_ca_exports()

    def test_the_command_carries_them_itself(self):
        exports = self._exports()
        for var in ("SSL_CERT_FILE", "GIT_SSL_CAINFO", "CURL_CA_BUNDLE"):
            with self.subTest(var=var):
                self.assertIn(var, exports)

    def test_nothing_is_exported_where_there_is_no_bundle(self):
        """Pointer SSL_CERT_FILE sur un fichier absent couperait TLS partout,
        et les quatre autres familles n'ont pas ce faisceau."""
        self.assertIn("if [ -r ", self._exports())
        # Un « if » et non un « && » : sous « set -e », une garde fausse en
        # fin de liste ET-OU est un cas limite qui dépend du shell.
        self.assertNotIn("] && export", self._exports())

    def test_the_module_takes_over_afterwards(self):
        """Sans cela un « git pull » plus tard échouerait comme le clone."""
        self.assertIn("GIT_SSL_CAINFO", self.src)
        self.assertIn("@EL_CA_BUNDLE@", self.src)

    def test_a_machine_without_a_cache_declares_nothing(self):
        """« optionalAttrs » et non un défaut : le faisceau n'existe pas
        partout, et l'installeur laisse le marqueur vide dans ce cas."""
        self.assertIn('lib.optionalAttrs ("@EL_CA_BUNDLE@" != "")', self.src)
        self.assertIn(
            '[ -r "${EL_CA_BUNDLE}" ] || EL_CA_BUNDLE=""', self.script
        )


class SudoNEffacePasLAutorite(unittest.TestCase):
    """L'installation reconstruit le système par « sudo », et sudo remet
    l'environnement à zéro.

    Le fragment de service donné au démon nix ne couvre pas ce cas : mesuré
    sur une VM, « sudo nix store info » rend « Store URL: local » et un
    NIX_REMOTE vide. Le nix de root parle DIRECTEMENT au magasin local, sans
    jamais passer par le démon — c'est lui qui télécharge, avec
    l'environnement que sudo lui laisse, et il n'en laisse aucun.

    Le mode de défaillance : chaque objet que la reconstruction doit chercher
    est demandé sans l'autorité, et le seul journal est une répétition de
    « unable to download ... narinfo: SSL peer certificate ... was not OK ».
    Le système n'est pas activé, et rien ne nomme la cause.

    Le remède est celui des autres familles, « Defaults env_keep », et non un
    second : NixOS lit bien /etc/sudoers.d — son /etc/sudoers porte
    « #includedir », le répertoire existe, et visudo est dans le PATH de root.
    """

    def _commandes(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".crt") as fh:
            fh.write("-----BEGIN CERTIFICATE-----\n")
            fh.flush()
            args = DQ.build_parser().parse_args(
                ["--distro", "nixos", "--hostname", "x", "--cache-ca", fh.name]
            )
            return DQ.cache_commands(args)

    def test_the_variables_cross_sudo(self):
        joint = " ".join(self._commandes())
        self.assertIn(DQ.CACHE_SUDOERS, joint)
        self.assertIn("env_keep", joint)

    def test_every_variable_the_session_exports_is_kept(self):
        """Les deux listes sont lues ensemble ou pas du tout : une variable
        exportée que sudo efface est exactement le défaut qu'on répare, et
        une variable gardée que rien n'exporte ne garde rien."""
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        exportees = set(
            re.findall(
                r"(\w+)=/var/lib/erplibre/ca-bundle\.crt",
                TODO.__new__(TODO)._qemu_ca_exports(),
            )
        )
        self.assertTrue(exportees, "la commande n'exporte rien")
        self.assertEqual(exportees, set(DQ.NIX_CA_VARS))

    def test_the_rebuild_is_the_one_that_needs_it(self):
        """Le garde-fou pointe la ligne qui justifie tout le reste : si la
        reconstruction cessait de passer par sudo, ce mécanisme n'aurait plus
        de raison d'être, et personne ne s'en apercevrait."""
        self.assertIn(
            "sudo nixos-rebuild switch",
            SCRIPT.read_text(encoding="utf-8"),
        )


class LePortDOdooTraverseLePareFeu(unittest.TestCase):
    """NixOS active un pare-feu par défaut ; aucune des images cloud des
    quatre autres distributions n'en active un.

    Le service écoute bien sur 0.0.0.0:8069 et répond en local, mais
    l'extérieur ne reçoit RIEN — pas un refus, un silence, donc une attente
    jusqu'au délai. Ce qui sonde depuis l'hôte conclut « Odoo absent » sur une
    machine où il tourne, et le journal de l'installation ne porte aucune
    trace de la cause.
    """

    def setUp(self):
        self.src = MODULE.read_text(encoding="utf-8")

    def _port_sonde(self):
        """Le port que l'hôte sonde VRAIMENT, lu de sa signature : une
        constante recopiée ici vieillirait sans que rien ne le dise."""
        import inspect
        import sys

        sys.path.insert(0, str(RACINE))
        from script.todo.qemu_install_monitor import _port_open

        return inspect.signature(_port_open).parameters["port"].default

    def test_the_port_probed_from_the_host_is_the_one_opened(self):
        port = self._port_sonde()
        self.assertIn(
            f"networking.firewall.allowedTCPPorts = [ {port} ];", self.src
        )

    def test_the_firewall_is_not_simply_turned_off(self):
        """Le couper ouvrirait TOUT. PostgreSQL n'écoute aujourd'hui que sur
        la boucle locale, mais un module qui désactive le pare-feu ne le
        protégerait plus le jour où cela changerait."""
        self.assertNotIn("networking.firewall.enable = false", self.src)

    def test_only_what_serves_is_opened(self):
        """Odoo ne lie le port websocket qu'en mode multi-processus, que cette
        configuration n'emploie pas : rien n'y écoute, et l'ouvrir donnerait
        un port béant sans service derrière."""
        i = self.src.index("allowedTCPPorts")
        ligne = self.src[i : self.src.index("\n", i)]
        self.assertNotIn("8072", ligne)
        self.assertNotIn("5432", ligne)


class LeMenuNEcritPasDansEtcSurNixos(unittest.TestCase):
    def _cmd(self, prod=False):
        import sys

        sys.argv = ["todo.py"]
        sys.path.insert(0, str(RACINE))
        from script.todo.todo import TODO

        return TODO.__new__(TODO)._qemu_odoo_service_cmd(prod=prod)

    def test_nixos_is_recognised_before_the_write(self):
        """Reconnu DANS la VM : la même commande sert au déploiement, au test
        long et à un « --hote » qu'on n'a pas créé."""
        for prod in (False, True):
            with self.subTest(prod=prod):
                cmd = self._cmd(prod)
                self.assertLess(
                    cmd.index("ID=nixos"),
                    cmd.index("tee /etc/systemd/system"),
                )

    def test_the_declarative_branch_only_restarts(self):
        """L'unité existe déjà — le module l'a déclarée. « enable » écrirait
        un lien dans /etc, que le système refuse."""
        cmd = self._cmd()
        nix = cmd[cmd.index("ID=nixos") : cmd.index("tee /etc/systemd/system")]
        self.assertIn("systemctl restart erplibre.service", nix)
        self.assertNotIn("systemctl enable", nix)

    def test_a_missing_unit_is_named_and_fails(self):
        """Sans le module, « restart » rendrait une erreur de systemd sans
        dire ce qui manque ni où le prendre."""
        cmd = self._cmd()
        self.assertIn("systemctl cat erplibre.service", cmd)
        self.assertIn("make install_os", cmd)


class LAutoriteEstExporteeApresQueCloudInitLAEcrite(unittest.TestCase):
    """L'ordre entre l'attente et les exports, qui n'est pas un détail.

    Le faisceau est écrit par cloud-init, et la session ssh est ouverte
    AVANT lui : mesuré sur une VM, ssh est accepté à 13:18:27 et le fichier
    apparaît à 13:18:28. Une garde « if [ -r … ] » évaluée en tête de
    commande est donc fausse, n'exporte rien, et tout ce qui suit dans ce
    shell perd l'autorité — le clone du dépôt échoue sur « self-signed
    certificate » alors que nix, qui lit son fragment au moment de s'en
    servir, télécharge très bien. Le symptôme accuse le réseau ; la cause est
    une seconde d'écart.

    Le remède est STRUCTUREL : les exports vivent dans l'attente elle-même,
    à côté de la relecture des variables que les autres familles y font déjà.
    Trois commandes distantes sont bâties à des endroits différents, et
    aucune ne peut plus les oublier ni les mettre trop tôt.
    """

    def _todo(self):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        return TODO.__new__(TODO)

    def test_the_exports_live_inside_the_wait(self):
        attente = self._todo()._qemu_cloud_init_wait()
        self.assertIn("ca-bundle.crt", attente)

    def test_they_come_after_the_unit_that_writes_the_bundle(self):
        """« cloud-init status --wait » rend la main trop tôt : c'est
        l'attente de l'unité finale qui garantit le fichier écrit."""
        attente = self._todo()._qemu_cloud_init_wait()
        self.assertLess(
            attente.index("cloud-final"), attente.index("ca-bundle.crt")
        )

    def test_every_remote_command_carries_them_exactly_once(self):
        """Les trois points de sortie — bureau seul, bureau et outils,
        installation complète — passent tous par l'attente."""
        todo = self._todo()
        for cas in (
            {"branch": None, "desktop": False},
            {"branch": None, "desktop": True},
            {"branch": "master", "desktop": False},
        ):
            with self.subTest(**cas):
                cmd = todo._qemu_erplibre_remote_cmd(**cas)
                self.assertEqual(
                    cmd.count("if [ -r /var/lib/erplibre/ca-bundle.crt ]"),
                    1,
                    "les exports doivent y être, et une seule fois",
                )

    def test_no_caller_puts_them_back_in_front(self):
        """Un appelant qui les rajouterait en tête ramènerait le défaut sans
        que rien d'autre ne change."""
        source = (RACINE / "script/todo/qemu_deploy.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("_qemu_ca_exports()", source)


class LeServiceAttendQuOdooSoitLa(unittest.TestCase):
    """L'unité est déclarée par le module, donc démarrée par la
    reconstruction — laquelle a lieu PENDANT « make install_os ».

    La source d'Odoo, elle, n'arrive qu'à « make install_odoo_18 ». Entre les
    deux, run.sh échoue sur un odoo-bin absent et « Restart = always » le
    rejoue toutes les cinq secondes : vingt et un échecs mesurés sur une pose
    ordinaire, et un « nixos-rebuild » qui rend 4 au lieu de 0 parce qu'une
    unité n'a pas démarré. Le journal d'une machine neuve s'ouvre alors sur
    une avalanche qui n'accuse rien de réel.

    Une CONDITION plutôt qu'une dépendance : mesuré sur une VM, systemd saute
    l'unité en le disant une fois — « was skipped because of an unmet
    condition check » — sans la marquer en échec, puis la démarre d'elle-même
    une fois le fichier là.
    """

    def setUp(self):
        self.src = MODULE.read_text(encoding="utf-8")

    def test_the_unit_waits_for_what_run_sh_executes(self):
        self.assertIn(
            'unitConfig.ConditionPathExistsGlob = "@EL_DIR@/odoo*/odoo/'
            'odoo-bin";',
            self.src,
        )

    def test_the_odoo_version_is_not_frozen_in_the_module(self):
        """Une version écrite ici vieillirait en silence : l'unité cesserait
        de démarrer le jour où le dépôt passe à la suivante."""
        condition = [l for l in self.src.splitlines() if "ConditionPath" in l]
        self.assertEqual(len(condition), 1)
        self.assertNotIn("odoo18", condition[0])

    def test_it_is_a_condition_and_not_a_dependency(self):
        """« requires » sur un chemin n'existe pas, et « after » ne
        garantirait rien : seule une condition SAUTE au lieu d'échouer."""
        self.assertNotIn('odoo-bin" ]', self.src)
        self.assertIn("ConditionPathExistsGlob", self.src)

    def test_the_marker_is_substituted_everywhere(self):
        """Le chemin du dépôt apparaît désormais deux fois dans le module ;
        un sed sans « g » n'en remplacerait qu'une, et la condition porterait
        un « @EL_DIR@ » littéral que rien ne satisfait jamais."""
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("s#@EL_DIR@#${EL_DIR}#g", script)
        self.assertGreater(self.src.count("@EL_DIR@"), 1)


if __name__ == "__main__":
    unittest.main()
