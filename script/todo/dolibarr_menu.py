#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Dolibarr dans TODO : l'entrée du menu Installation et son parcours.

Le menu DEMANDE et AFFICHE ; script/dolibarr/ décide et exécute. Ce qui est
une décision — l'épinglage, ce que l'hôte permet, la commande à lancer — vit
dans script/dolibarr/lib_dolibarr.py, sans sortie, et se teste sans TODO.
Les faits de l'hôte (système, famille de paquets, systemd, moteur de
conteneurs) sont lus en UN point, _dolibarr_host_facts, que les tests
remplacent.

Aucun import tiers au niveau du module : prompt_install sert aussi de repli
quand TODO démarre mal, et cette entrée doit s'y afficher.
"""

import getpass
import os
import platform
import shlex
import shutil

from script.dolibarr import lib_dolibarr, web_config
from script.todo import todo_install
from script.todo.todo_i18n import t

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

DEFAULT_INSTANCE = "dolibarr"
DEFAULT_LOGIN = "admin"
DEFAULT_PORT = 8080

# Lancer, arrêter, suivre une instance de développement.
RUN_CLI = f"{lib_dolibarr.PYTHON} -u script/dolibarr/run.py"
# Relever l'épinglage ; PIN_PENDING est le code de pin.py quand un essai à
# blanc a trouvé quoi changer (sa valeur ici évite d'importer pin.py).
PIN_CLI = f"{lib_dolibarr.PYTHON} -u script/dolibarr/pin.py"
PIN_PENDING = 3
# Trouver les installations Dolibarr, sur ce poste ou par SSH.
DETECT_CLI = f"{lib_dolibarr.PYTHON} -u script/dolibarr/detect.py"
# Bilan de santé, sécurité et intégrité de chaque instance inscrite.
DOCTOR_CLI = f"{lib_dolibarr.PYTHON} -u script/dolibarr/doctor.py"
# Sauvegarde d'une instance, sous private/dolibarr/backups/.
BACKUP_CLI = f"{lib_dolibarr.PYTHON} -u script/dolibarr/backup.py"
# Profil de déverminage d'une instance (DebugBar, Syslog 7, mode strict).
DEBUG_CLI = f"{lib_dolibarr.PYTHON} -u script/dolibarr/debug.py"
# Modules d'une instance de développement : créer, lier, activer.
MODULE_CLI = f"{lib_dolibarr.PYTHON} -u script/dolibarr/module.py"
# Paquet d'un module et précontrôle DoliStore.
PACKAGE_CLI = f"{lib_dolibarr.PYTHON} -u script/dolibarr/package.py"
# phpcs et PHPStan sur un module, depuis le conteneur d'outils épinglé.
QUALITY_CLI = f"{lib_dolibarr.PYTHON} -u script/dolibarr/quality.py"
# Monter une instance à la version épinglée.
UPGRADE_CLI = f"{lib_dolibarr.PYTHON} -u script/dolibarr/upgrade.py"
# Le parc : lister les instances, en retirer une.
FLEET_CLI = f"{lib_dolibarr.PYTHON} -u script/dolibarr/fleet.py"
SYNC_SCRIPT = "./script/manifest/update_manifest_local_dolibarr.sh"

# Le script qui bâtit le venv d'outillage quand il manque, comme le fait
# mobile/install_and_run.sh avant de s'en servir.
INSTALL_ERPLIBRE = "./script/install/install_erplibre.sh"


class DolibarrMenuMixin:
    # -- Entrée du menu Installation -----------------------------------

    def _dolibarr_install_entry(self, key):
        """(clé, libellé, None) pour prompt_install, ou None si l'épinglage
        est illisible — la raison est alors affichée, l'entrée absente."""
        try:
            pin = lib_dolibarr.read_pin(ROOT)
        except lib_dolibarr.PinError as e:
            print(t("Dolibarr pin unreadable: %s") % e)
            return None
        installed = os.path.exists(
            os.path.join(ROOT, pin["path"], "htdocs", "version.inc.php")
        )
        return key, lib_dolibarr.install_label(key, pin, installed), None

    # -- Exécution › Dolibarr ------------------------------------------

    def prompt_execute_dolibarr(self):
        """Installer, lancer, arrêter et suivre les instances Dolibarr."""
        import click

        choices = [
            {"section": t("Development instances")},
            {"prompt_description": t("Dolibarr - Install an instance")},
            {"prompt_description": t("Dolibarr - Start an instance")},
            {"prompt_description": t("Dolibarr - Stop an instance")},
            {"prompt_description": t("Dolibarr - Instance status")},
            {"prompt_description": t("Dolibarr - Instance logs")},
            {"section": t("Maintenance")},
            {"prompt_description": t("Dolibarr - Update the pinned commit")},
            {"prompt_description": t("Dolibarr - Upgrade an instance")},
            {
                "prompt_description": t(
                    "Dolibarr - Health, security and integrity"
                )
            },
            {"prompt_description": t("Dolibarr - Back up an instance")},
            {"prompt_description": t("Dolibarr - Restore a backup")},
            {"section": t("Inventory")},
            {"prompt_description": t("Dolibarr - List the instances")},
            {"prompt_description": t("Dolibarr - Remove an instance")},
            {
                "prompt_description": t(
                    "Dolibarr - Find installations (local or SSH)"
                )
            },
            {"section": t("Development tools")},
            {"prompt_description": t("Dolibarr - Debug profile")},
            {
                "prompt_description": t(
                    "Dolibarr - Modules: create, link, enable"
                )
            },
            {
                "prompt_description": t(
                    "Dolibarr - Package a module (DoliStore)"
                )
            },
            {
                "prompt_description": t(
                    "Dolibarr - Code quality of a module (phpcs, PHPStan)"
                )
            },
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.prompt_install_dolibarr()
            elif status == "2":
                self._dolibarr_run("start")
            elif status == "3":
                self._dolibarr_run("stop")
            elif status == "4":
                self._dolibarr_run("status")
            elif status == "5":
                self._dolibarr_run("logs")
            elif status == "6":
                self._dolibarr_pin()
            elif status == "7":
                self._dolibarr_upgrade()
            elif status == "8":
                self._dolibarr_doctor()
            elif status == "9":
                self._dolibarr_backup()
            elif status == "10":
                self._dolibarr_restore()
            elif status == "11":
                self._dolibarr_fleet_list()
            elif status == "12":
                self._dolibarr_remove()
            elif status == "13":
                self._dolibarr_detect()
            elif status == "14":
                self._dolibarr_debug()
            elif status == "15":
                self._dolibarr_module()
            elif status == "16":
                self._dolibarr_package()
            elif status == "17":
                self._dolibarr_quality()
            else:
                print(t("Command not found !"))

    def _dolibarr_upgrade(self):
        """upgrade.py sur l'instance choisie, après un oui : il sauvegarde
        d'abord et revient en arrière seul en cas d'échec."""
        try:
            known = lib_dolibarr.load_registry(ROOT)
        except lib_dolibarr.RegistryError as e:
            print(t("Dolibarr registry unreadable: %s") % e)
            return
        names = sorted(known)
        if not names:
            print(t("No Dolibarr instance."))
            return
        name = (
            names[0]
            if len(names) == 1
            else self._dolibarr_choose(t("Instance:"), [(n, n) for n in names])
        )
        if name is None:
            return
        print(
            t(
                "The instance stops during the upgrade; a backup comes"
                " first and a failure rolls back."
            )
        )
        if not self._is_yes(
            input(t("Upgrade %s to the pinned version? (y/N): ") % name)
            .strip()
            .lower()
        ):
            print(t("Cancelled."))
            return
        self.execute.exec_command_live(
            f"{UPGRADE_CLI} --instance {shlex.quote(name)}",
            source_erplibre=False,
        )

    def _dolibarr_doctor(self):
        """doctor.py sur toutes les instances ; il dit lui-même ce qui va."""
        self.execute.exec_command_live(
            f"{DOCTOR_CLI} --all", source_erplibre=False
        )

    def _dolibarr_backup(self):
        """backup.py sur l'instance choisie, production comprise ; une
        seule instance est prise sans question."""
        try:
            known = lib_dolibarr.load_registry(ROOT)
        except lib_dolibarr.RegistryError as e:
            print(t("Dolibarr registry unreadable: %s") % e)
            return
        names = sorted(known)
        if not names:
            print(t("No Dolibarr instance."))
            return
        name = (
            names[0]
            if len(names) == 1
            else self._dolibarr_choose(t("Instance:"), [(n, n) for n in names])
        )
        if name is None:
            return
        self.execute.exec_command_live(
            f"{BACKUP_CLI} create --instance {shlex.quote(name)}",
            source_erplibre=False,
        )

    def _dolibarr_restore(self):
        """Destructif : l'instance, son archive (la plus récente d'abord),
        puis son nom retapé en entier ; restore.py le vérifie encore et
        prend une sauvegarde de sûreté avant d'écrire."""
        from script.dolibarr import backup

        try:
            known = lib_dolibarr.load_registry(ROOT)
        except lib_dolibarr.RegistryError as e:
            print(t("Dolibarr registry unreadable: %s") % e)
            return
        saved = {n: backup.archives(ROOT, n) for n in sorted(known)}
        names = [n for n, found in saved.items() if found]
        if not names:
            print(t("No backup to restore."))
            return
        name = (
            names[0]
            if len(names) == 1
            else self._dolibarr_choose(t("Instance:"), [(n, n) for n in names])
        )
        if name is None:
            return
        archive = self._dolibarr_choose(
            t("Backup to restore:"),
            [(p, os.path.basename(p)) for p in saved[name]],
        )
        if archive is None:
            return
        print(
            t(
                "This overwrites the database, documents and modules of %s;"
                " a safety backup comes first."
            )
            % name
        )
        if input(t("Retype %s to confirm: ") % name).strip() != name:
            print(t("Cancelled."))
            return
        relative = os.path.relpath(archive, ROOT)
        self.execute.exec_command_live(
            f"{BACKUP_CLI} restore --instance {shlex.quote(name)}"
            f" --archive {shlex.quote(relative)} --confirm {shlex.quote(name)}",
            source_erplibre=False,
        )

    def _dolibarr_fleet_list(self):
        """fleet.py list : chaque instance, son exécution, ce qu'elle sert."""
        self.execute.exec_command_live(
            f"{FLEET_CLI} list", source_erplibre=False
        )

    def _dolibarr_remove(self):
        """Destructif : le plan à blanc, une sauvegarde proposée (son échec
        arrête tout), puis le nom retapé en entier."""
        try:
            known = lib_dolibarr.load_registry(ROOT)
        except lib_dolibarr.RegistryError as e:
            print(t("Dolibarr registry unreadable: %s") % e)
            return
        names = sorted(known)
        if not names:
            print(t("No Dolibarr instance."))
            return
        name = (
            names[0]
            if len(names) == 1
            else self._dolibarr_choose(t("Instance:"), [(n, n) for n in names])
        )
        if name is None:
            return
        quoted = shlex.quote(name)
        self.execute.exec_command_live(
            f"{FLEET_CLI} remove --instance {quoted} --dry-run",
            source_erplibre=False,
        )
        if self._is_yes(
            input(t("Back up the instance first? (Y/n): ")).strip().lower()
            or "y"
        ):
            if self.execute.exec_command_live(
                f"{BACKUP_CLI} create --instance {quoted}",
                source_erplibre=False,
            ):
                print(t("The backup failed: nothing was removed."))
                return
        if input(t("Retype %s to confirm: ") % name).strip() != name:
            print(t("Cancelled."))
            return
        self.execute.exec_command_live(
            f"{FLEET_CLI} remove --instance {quoted} --confirm {quoted}",
            source_erplibre=False,
        )

    def _dolibarr_debug(self):
        """debug.py : allumer, éteindre, état, ou suivre le journal filtré.
        Une production exige son nom retapé pour on et off."""
        try:
            known = lib_dolibarr.load_registry(ROOT)
        except lib_dolibarr.RegistryError as e:
            print(t("Dolibarr registry unreadable: %s") % e)
            return
        names = sorted(known)
        if not names:
            print(t("No Dolibarr instance."))
            return
        name = (
            names[0]
            if len(names) == 1
            else self._dolibarr_choose(t("Instance:"), [(n, n) for n in names])
        )
        if name is None:
            return
        action = self._dolibarr_choose(
            t("Debug profile:"),
            [
                ("on", t("Turn on (DebugBar, Syslog level 7, strict mode)")),
                ("off", t("Turn off, previous settings back")),
                ("status", t("Status")),
                ("tail", t("Follow dolibarr.log")),
            ],
        )
        if action is None:
            return
        args = [action, "--instance", name]
        if action == "tail":
            pattern = input(
                t("Filter (regular expression, Enter for everything): ")
            ).strip()
            if pattern:
                args += ["--filter", pattern]
        elif action in ("on", "off") and known[name].get("mode") == "prod":
            if input(t("Retype %s to confirm: ") % name).strip() != name:
                print(t("Cancelled."))
                return
            args += ["--confirm", name]
        self.execute.exec_command_live(
            f"{DEBUG_CLI} {shlex.join(args)}", source_erplibre=False
        )

    def _dolibarr_dev_instance(self):
        """(nom, registre) d'une instance de développement, prise d'office
        si elle est seule ; None si aucune ou sur Retour."""
        try:
            known = lib_dolibarr.load_registry(ROOT)
        except lib_dolibarr.RegistryError as e:
            print(t("Dolibarr registry unreadable: %s") % e)
            return None
        names = sorted(n for n in known if known[n].get("mode") != "prod")
        if not names:
            print(t("No development instance."))
            return None
        name = (
            names[0]
            if len(names) == 1
            else self._dolibarr_choose(t("Instance:"), [(n, n) for n in names])
        )
        return None if name is None else (name, known)

    def _dolibarr_module(self):
        """module.py sur une instance de développement : une production ne
        se développe pas, un conteneur ne se voit pas offrir le lien."""
        chosen = self._dolibarr_dev_instance()
        if chosen is None:
            return
        name, known = chosen
        options = [("create", t("Create from the ModuleBuilder template"))]
        if known[name].get("runtime") != "container":
            options.append(
                ("link", t("Link a module kept in its own directory"))
            )
        options += [
            ("enable", t("Enable a module")),
            ("disable", t("Disable a module")),
        ]
        action = self._dolibarr_choose(t("Module:"), options)
        if action is None:
            return
        args = [action, "--instance", name]
        if action == "link":
            path = input(t("Module directory: ")).strip()
            if not path:
                print(t("Cancelled."))
                return
            args += ["--path", path]
        else:
            module = input(t("Module name (letters and digits): ")).strip()
            if not module:
                print(t("Cancelled."))
                return
            args += ["--name", module]
        if action == "create":
            numero = input(
                t("Module ID (Enter: first free from 500000): ")
            ).strip()
            if numero and not numero.isdigit():
                print(t("A module ID is a number."))
                return
            if numero:
                args += ["--id", numero]
            if self._is_yes(
                input(t("Enable it now? (y/N): ")).strip().lower()
            ):
                args.append("--enable")
        self.execute.exec_command_live(
            f"{MODULE_CLI} {shlex.join(args)}", source_erplibre=False
        )

    def _dolibarr_package(self):
        """package.py : contrôler, bâtir le zip, ou le bâtir seulement s'il
        satisfait DoliStore."""
        chosen = self._dolibarr_dev_instance()
        if chosen is None:
            return
        name, _known = chosen
        action = self._dolibarr_choose(
            t("Package:"),
            [
                ("check", t("Check only")),
                ("build", t("Build the zip")),
                ("dolistore", t("Build the zip only if DoliStore-ready")),
            ],
        )
        if action is None:
            return
        module = input(t("Module name (letters and digits): ")).strip()
        if not module:
            print(t("Cancelled."))
            return
        args = [
            "check" if action == "check" else "build",
            "--instance",
            name,
            "--name",
            module,
        ]
        if action == "dolistore":
            args.append("--dolistore")
        self.execute.exec_command_live(
            f"{PACKAGE_CLI} {shlex.join(args)}", source_erplibre=False
        )

    def _dolibarr_quality(self):
        """quality.py : phpcs et PHPStan, ou l'un des deux."""
        chosen = self._dolibarr_dev_instance()
        if chosen is None:
            return
        name, _known = chosen
        only = self._dolibarr_choose(
            t("Quality tools:"),
            [
                ("both", t("phpcs and PHPStan")),
                ("phpcs", t("phpcs only (Dolibarr rules)")),
                ("phpstan", t("PHPStan only")),
            ],
        )
        if only is None:
            return
        module = input(t("Module name (letters and digits): ")).strip()
        if not module:
            print(t("Cancelled."))
            return
        args = ["--instance", name, "--name", module]
        if only != "both":
            args += ["--only", only]
        self.execute.exec_command_live(
            f"{QUALITY_CLI} {shlex.join(args)}", source_erplibre=False
        )

    def _dolibarr_detect(self):
        """Ce poste, un hôte de ~/.ssh/config ou tous : detect.py sonde et
        range son rapport sous private/dolibarr/inventory/."""
        aliases = self._ssh_config_hosts()
        options = [("local", t("This machine"))]
        if aliases:
            options.append(("all", t("Every host of ~/.ssh/config")))
            options += [(a, a) for a in aliases]
        target = self._dolibarr_choose(
            t("Where to look for Dolibarr?"), options
        )
        if target is None:
            return
        if target == "local":
            args = ["--local"]
        else:
            hosts = aliases if target == "all" else [target]
            args = [x for h in hosts for x in ("--ssh", h)]
        self.execute.exec_command_live(
            f"{DETECT_CLI} {shlex.join(args)}", source_erplibre=False
        )

    def _dolibarr_pin(self):
        """pin.py à blanc ; s'il trouve quoi changer, l'appliquer puis
        synchroniser le checkout, chaque fois sur confirmation."""
        if (
            self.execute.exec_command_live(
                f"{PIN_CLI} update", source_erplibre=False
            )
            != PIN_PENDING
        ):
            return
        if not self._is_yes(input(t("Apply this pin? (y/N): ")).strip()):
            return
        if self.execute.exec_command_live(
            f"{PIN_CLI} update --apply", source_erplibre=False
        ):
            return
        if self._is_yes(
            input(t("Sync the Dolibarr checkout now? (y/N): ")).strip()
        ):
            self.execute.exec_command_live(SYNC_SCRIPT, source_erplibre=False)

    def _dolibarr_run(self, action):
        """script/dolibarr/run.py `action` sur une instance de développement.

        Une seule instance est prise d'office, plusieurs se choisissent ;
        « status » les couvre toutes, sans choix.
        """
        try:
            known = lib_dolibarr.load_registry(ROOT)
        except lib_dolibarr.RegistryError as e:
            print(t("Dolibarr registry unreadable: %s") % e)
            return
        dev = sorted(
            name
            for name, e in known.items()
            if e.get("mode") == "dev"
            and e.get("runtime") in ("native", "container")
        )
        if not dev:
            print(t("No development Dolibarr instance."))
            return
        command = f"{RUN_CLI} {action}"
        if action != "status":
            if len(dev) == 1:
                name = dev[0]
            else:
                name = self._dolibarr_choose(
                    t("Dolibarr instance:"), [(n, n) for n in dev]
                )
                if name is None:
                    return
            command += f" --instance {name}"
        self.execute.exec_command_live(command, source_erplibre=False)

    # -- Parcours d'installation ---------------------------------------

    def prompt_install_dolibarr(self):
        """Environnement, exécution, base, paramètres, puis le script.

        Chaque question offre « 0: Back », qui rend la main sans rien lancer.
        Rien n'est installé avant la confirmation du récapitulatif.
        """
        try:
            pin = lib_dolibarr.read_pin(ROOT)
        except lib_dolibarr.PinError as e:
            print(t("Dolibarr pin unreadable: %s") % e)
            return
        modes = [
            (
                "dev",
                t("Development - your user, local port, debugging allowed"),
            ),
            (
                "prod",
                t("Production - system services, hardened, scheduled jobs"),
            ),
        ]
        delivered = {m for m, _r in lib_dolibarr.AVAILABLE}
        mode = self._dolibarr_choose(
            t("Dolibarr environment:"),
            [(m, label) for m, label in modes if m in delivered],
        )
        if mode is None:
            return
        runtimes, reasons = self._dolibarr_runtimes(mode)
        for reason in reasons:
            print(reason)
        if not runtimes:
            return
        runtime = self._dolibarr_choose(t("Dolibarr runtime:"), runtimes)
        if runtime is None:
            return
        if runtime == "native":
            db = self._dolibarr_choose(
                t("Dolibarr database:"),
                [
                    ("mariadb", t("MariaDB (recommended)")),
                    ("postgresql", t("PostgreSQL (the ERPLibre server)")),
                ],
            )
            if db is None:
                return
        else:
            print(
                t(
                    "Docker / Podman: MariaDB only, the official image"
                    " installs itself on MariaDB alone."
                )
            )
            db = "mariadb"
        params = self._dolibarr_ask_instance(mode, runtime)
        if params is None:
            return
        password = self._dolibarr_ask_admin_password()
        if password is None:
            return
        choice = dict(params, mode=mode, runtime=runtime, db=db)
        choice["admin_password"] = password
        argv, env = lib_dolibarr.install_argv(choice)
        command = shlex.join(argv)

        print()
        print(
            t("Dolibarr %s (%s) will be installed:")
            % (pin["version"], pin["commit"][:7])
        )
        print(f"  {t('Instance: %s') % choice['instance']}")
        if choice.get("port"):
            print(f"  {t('Web port: %s') % choice['port']}")
        if choice.get("domain"):
            print(f"  {t('Domain: %s') % choice['domain']}")
        if runtime == "container":
            print(f"  {t('Image: %s') % pin['docker_image']}")
        print(f"{t('Will execute:')}\n{command}")
        if not self._is_yes(input(t("Confirm? (y/N): ")).strip().lower()):
            print(t("Cancelled."))
            return

        if not self._dolibarr_python_ready():
            print(f"{t('Will execute:')}\n{INSTALL_ERPLIBRE}")
            if self.execute.exec_command_live(
                INSTALL_ERPLIBRE, source_erplibre=False
            ):
                print(t("Installation failed, see the output above."))
                return
        status = self.execute.exec_command_live(
            command, source_erplibre=False, new_env=env or None
        )
        if status:
            print(t("Installation failed, see the output above."))

    def _dolibarr_choose(self, question, options):
        """Liste numérotée de `options` [(valeur, libellé)] plus « 0: Back ».

        Rend la valeur choisie, ou None pour Retour. Même forme que le choix
        du type d'installation de prompt_install.
        """
        choices = {str(i): option for i, option in enumerate(options, start=1)}
        lines = [f"{k}: {label}" for k, (_v, label) in choices.items()]
        lines.append(f"0: {t('Back')}")
        answer = ""
        while answer not in choices and answer != "0":
            if answer:
                print(f"{t('Error, cannot understand value')} '{answer}'")
            answer = input(
                f"💬 {question}\n\t"
                + "\n\t".join(lines)
                + f"\n{t('Select: ')}"
            ).strip()
        if answer == "0":
            return None
        return choices[answer][0]

    def _dolibarr_runtimes(self, mode):
        """([(valeur, libellé)] des exécutions proposées, [raisons])."""
        facts = self._dolibarr_host_facts()
        delivered = {r for m, r in lib_dolibarr.AVAILABLE if m == mode}
        options, reasons = [], []
        ok, why = lib_dolibarr.native_support(
            facts["system"],
            facts["family"],
            facts["is_nixos"],
            facts["has_systemd"],
            mode,
        )
        if "native" not in delivered:
            pass
        elif ok:
            options.append(("native", t("Native - nginx + PHP-FPM")))
        else:
            reasons.append(t("Native is not offered here: %s") % t(why))
        ok, why = lib_dolibarr.container_support(
            facts["system"], facts["family"], facts["engine_usable"]
        )
        if "container" not in delivered:
            pass
        elif ok:
            options.append(
                (
                    "container",
                    t("Docker / Podman - official dolibarr/dolibarr image"),
                )
            )
        else:
            reasons.append(
                t("Docker / Podman is not offered here: %s") % t(why)
            )
        return options, reasons

    def _dolibarr_ask_instance(self, mode, runtime):
        """Nom, port, domaine et identifiant ; None si on ne peut continuer."""
        try:
            known = lib_dolibarr.load_registry(ROOT)
        except lib_dolibarr.RegistryError as e:
            print(t("Dolibarr registry unreadable: %s") % e)
            return None
        while True:
            name = (
                input(t("Instance name (default: %s): ") % DEFAULT_INSTANCE)
                .strip()
                .lower()
                or DEFAULT_INSTANCE
            )
            if lib_dolibarr.valid_instance_name(name):
                break
            print(
                t(
                    "Invalid name: lowercase letters, digits and _, starting"
                    " with a letter."
                )
            )
        if name in known:
            print(t("This instance already exists: %s") % name)
            return None
        params = {"instance": name}

        # La production native passe par nginx sur 80/443 : pas de port.
        if not (mode == "prod" and runtime == "native"):
            default = lib_dolibarr.free_port(
                DEFAULT_PORT, self._dolibarr_port_is_free
            )
            if default is None:
                print(t("No free web port from %s.") % DEFAULT_PORT)
                return None
            while True:
                port = lib_dolibarr.parse_port(
                    input(t("Web port (default: %s): ") % default), default
                )
                if port is not None:
                    break
                print(t("Invalid port: a number from 1024 to 65535."))
            params["port"] = port

        if mode == "prod":
            domain = self._dolibarr_ask_domain(runtime == "native")
            if domain:
                tls = self._dolibarr_choose(
                    t("HTTPS certificate:"),
                    [
                        ("certbot", t("Let's Encrypt (public name, certbot)")),
                        ("local", t("Local CA (tests)")),
                        ("none", t("None (HTTP only)")),
                    ],
                )
                if tls is None:
                    return None
                params.update(domain=domain, tls=tls)
                if tls == "certbot":
                    email = input(
                        t("Email for certbot (empty for none): ")
                    ).strip()
                    if email:
                        params["email"] = email

        while True:
            login = (
                input(t("Administrator login (default: admin): ")).strip()
                or DEFAULT_LOGIN
            )
            if lib_dolibarr.valid_login(login):
                break
            print(
                t(
                    "Invalid login: letters, digits and . _ @ -, starting"
                    " with a letter or a digit."
                )
            )
        params["admin_login"] = login
        return params

    def _dolibarr_ask_domain(self, required):
        """Nom sous lequel nginx sert l'instance, en minuscules.

        Redemandé tant qu'il est invalide ; vide accepté seulement quand il
        n'est pas `required` — le natif de production le demande toujours.
        """
        question = (
            t("Domain name (e.g.: example.com): ")
            if required
            else t("Domain name (empty for none): ")
        )
        while True:
            domain = input(question).strip().lower()
            if not domain and not required:
                return ""
            if web_config.valid_domain(domain):
                return domain
            print(t("Invalid domain name: letters, digits, dots and hyphens."))

    def _dolibarr_ask_admin_password(self):
        """Mot de passe saisi deux fois ; "" = généré par le script ; None
        si la saisie est interrompue."""
        try:
            while True:
                first = getpass.getpass(
                    t(
                        "Administrator password (empty = generated and"
                        " saved for this instance): "
                    )
                )
                if not first:
                    return ""
                if getpass.getpass(t("Confirm the password: ")) == first:
                    return first
                print(t("Passwords differ."))
        except (EOFError, KeyboardInterrupt):
            print()
            return None

    # -- Faits de l'hôte (remplacés en test) ---------------------------

    def _dolibarr_host_facts(self):
        """Système, famille de paquets, NixOS, systemd, moteur utilisable."""
        system = platform.system()
        family = None
        if system == "Linux":
            family = todo_install.family()
        elif system == "Darwin" and shutil.which("brew"):
            family = "brew"
        engine_usable = False
        try:
            from script.todo import container_runtime

            engine_usable = any(
                container_runtime.utilisable(fiche)
                for fiche in container_runtime.etats()
            )
        except Exception:
            # Un moteur qu'on ne sait pas interroger n'est pas utilisable ;
            # la voie reste proposée là où il peut s'installer.
            engine_usable = False
        return {
            "system": system,
            "family": family,
            "is_nixos": todo_install.os_id() == "nixos",
            "has_systemd": os.path.isdir("/run/systemd/system"),
            "engine_usable": engine_usable,
        }

    def _dolibarr_port_is_free(self, port):
        """Vrai si un serveur peut écouter sur 127.0.0.1:`port`."""
        from script.dolibarr import run

        return run.port_is_free(port)

    def _dolibarr_python_ready(self):
        """Vrai si l'interpréteur des scripts d'outillage est là."""
        return os.access(os.path.join(ROOT, lib_dolibarr.PYTHON), os.X_OK)
