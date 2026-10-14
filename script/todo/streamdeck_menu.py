#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Stream Deck de TODO : jeux, installations, service, état.

Il réunit sous une entrée d'Exécution ce qui touche au Stream Deck : les
jeux, les deux installations locales d'ERPLibre Home, le service systemd
--user erplibre-home-streamdeck.service et ses réglages, l'état du poste et
son diagnostic, la désinstallation, l'extension GNOME.

Les commandes longues ou interactives (systemctl, journalctl -f,
l'installateur, make) passent par self.execute.exec_command_live, en
direct ; les sondes muettes par _streamdeck_probe, que les tests
remplacent. L'état et le diagnostic viennent d'erplibre_home_status.
"""

import os
import shlex

import click

from script.todo import erplibre_home_service as service
from script.todo import erplibre_home_status as statut
from script.todo.todo_i18n import t

# La racine du dépôt, d'où partent l'installateur et make.
RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
INSTALLER = "./script/install/install_erplibre_home.sh"
EXTENSION_UUID = "erplibre-home@technolibre.ca"


class StreamDeckMenuMixin:
    def prompt_execute_streamdeck(self):
        choices = [
            {"prompt_description": t("Games - Stream Deck games")},
            {
                "prompt_description": t(
                    "Status - What is installed and what runs"
                )
            },
            {
                "prompt_description": t(
                    "Service - Start, stop, restart, live log"
                )
            },
            {
                "prompt_description": t(
                    "Deck program - Tiler, controller or none"
                )
            },
            {"prompt_description": t("Autostart - Enable or disable")},
            {
                "prompt_description": t(
                    "Diagnosis - What is wrong and how to fix it"
                )
            },
            {"prompt_description": t("Install ERPLibre Home (local)")},
            {
                "prompt_description": t(
                    "Install ERPLibre Home Stream Deck (local)"
                )
            },
            {
                "prompt_description": t(
                    "Uninstall - Stream Deck level or everything"
                )
            },
            {"prompt_description": t("Extension - Reload or preferences")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.prompt_execute_streamdeck_games()
            elif status == "2":
                self._streamdeck_status()
            elif status == "3":
                self._streamdeck_service()
            elif status == "4":
                self._streamdeck_program()
            elif status == "5":
                self._streamdeck_autostart()
            elif status == "6":
                self._streamdeck_diagnosis()
            elif status == "7":
                self._erplibre_home_install_local()
            elif status == "8":
                self._erplibre_home_streamdeck_install_local()
            elif status == "9":
                self._streamdeck_uninstall()
            elif status == "10":
                self._streamdeck_extension()
            else:
                print(t("Command not found !"))

    # -------------------------------------------------------------- #
    # Sondes et choix

    @staticmethod
    def _streamdeck_probe(argv):
        """(code, sortie) d'une commande muette ; les tests la remplacent."""
        return service.run_command(argv)

    @staticmethod
    def _streamdeck_choice(question, options, defaut="1"):
        """Affiche `question` puis `options`, des couples (valeur,
        libellé), numérotés à partir de 1, le défaut marqué d'une étoile.
        Rend la valeur choisie, celle du défaut sur une réponse vide, None
        sur 0. Une réponse hors liste le dit et repose la question."""
        print(question)
        for rang, (_valeur, libelle) in enumerate(options, 1):
            marque = " *" if str(rang) == defaut else ""
            print(f"  [{rang}] {libelle}{marque}")
        print(f"  [0] {t('Back')}")
        while True:
            reponse = input(t("Choice: ")).strip() or defaut
            if reponse == "0":
                return None
            if reponse.isdigit() and 1 <= int(reponse) <= len(options):
                return options[int(reponse) - 1][0]
            print(t("Invalid selection!"))

    @staticmethod
    def _streamdeck_programs():
        """Les PROGRAMS en couples (valeur, libellé traduit) pour
        _streamdeck_choice : la valeur va dans les réglages et les
        options, le libellé seul s'affiche."""
        libelles = {
            "tiler": t("Tiler"),
            "controller": t("Controller"),
            "none": t("No program"),
        }
        return [(p, libelles.get(p, p)) for p in service.PROGRAMS]

    @classmethod
    def _streamdeck_program_label(cls, programme):
        """Le libellé traduit de `programme`, ou la valeur brute quand elle
        n'est pas dans PROGRAMS."""
        return dict(cls._streamdeck_programs()).get(programme, programme)

    @staticmethod
    def _streamdeck_program_default(programme):
        """Le rang, compté à partir de 1, de `programme` dans PROGRAMS ;
        "1" quand il n'y est pas."""
        if programme in service.PROGRAMS:
            return str(service.PROGRAMS.index(programme) + 1)
        return "1"

    def _streamdeck_unit_installed(self):
        """Vrai quand l'unité du service existe ; sinon le dit avec la
        commande qui l'installe."""
        if os.path.exists(service.unit_path()):
            return True
        print(
            t(
                "The Stream Deck service is not installed:"
                " make erplibre_home_streamdeck_install"
            )
        )
        return False

    def _streamdeck_systemctl(self, *args):
        """systemctl --user <args> en direct, sortie affichée."""
        commande = "systemctl --user " + " ".join(shlex.quote(a) for a in args)
        self.execute.exec_command_live(commande, source_erplibre=False)

    # -------------------------------------------------------------- #
    # Entrées

    def _streamdeck_status(self):
        faits = statut.collect(self._streamdeck_probe, RACINE)
        for ligne in statut.status_lines(faits):
            print(f"  {ligne}")

    def _streamdeck_diagnosis(self):
        faits = statut.collect(self._streamdeck_probe, RACINE)
        problemes = statut.diagnosis_lines(faits)
        if not problemes:
            print(f"✅ {t('Nothing to fix.')}")
            return
        for probleme, correction in problemes:
            print(f"❌ {probleme}")
            print(f"   → {correction}")

    def _streamdeck_service(self):
        if not self._streamdeck_unit_installed():
            return
        choix = self._streamdeck_choice(
            t("Service action:"),
            (
                ("start", t("Start")),
                ("stop", t("Stop")),
                ("restart", t("Restart")),
                ("log", t("live log (Ctrl-C to leave)")),
            ),
        )
        if choix is None:
            return
        if choix != "log":
            self._streamdeck_systemctl(choix, service.UNIT_NAME)
            return
        try:
            self.execute.exec_command_live(
                f"journalctl --user -u {service.UNIT_NAME} -f",
                source_erplibre=False,
            )
        except KeyboardInterrupt:
            print()

    def _streamdeck_program(self):
        """Réécrit DECK_PROGRAM, puis redémarre l'unité si elle tournait,
        pour qu'elle lance le nouveau programme."""
        if not self._streamdeck_unit_installed():
            return
        chemin = service.settings_path()
        actuel = service.read_settings(chemin)["DECK_PROGRAM"]
        choix = self._streamdeck_choice(
            f"{t('Deck program:')} {self._streamdeck_program_label(actuel)}",
            self._streamdeck_programs(),
            self._streamdeck_program_default(actuel),
        )
        if choix is None:
            return
        if not service.write_settings(chemin, {"DECK_PROGRAM": choix}):
            print(t("Unchanged."))
            return
        print(f"{t('Deck program:')} {self._streamdeck_program_label(choix)}")
        code, _sortie = self._streamdeck_probe(statut.cmd_unit("is-active"))
        if code == 0:
            self._streamdeck_systemctl("restart", service.UNIT_NAME)

    def _streamdeck_autostart(self):
        if not self._streamdeck_unit_installed():
            return
        _code, sortie = self._streamdeck_probe(statut.cmd_unit("is-enabled"))
        choix = self._streamdeck_choice(
            f"{t('Autostart:')} {sortie.strip() or '?'}",
            (("enable", t("Enable")), ("disable", t("Disable"))),
        )
        if choix is not None:
            self._streamdeck_systemctl(choix, service.UNIT_NAME)

    def _streamdeck_uninstall(self):
        options = self._streamdeck_choice(
            t("Uninstall what?"),
            (
                ("--uninstall --stream-deck", t("The Stream Deck level")),
                ("--uninstall", t("Everything, the extension too")),
            ),
        )
        if options is None:
            return
        commande = f"{INSTALLER} {options}"
        print(f"{t('Will execute:')} {commande}")
        if not self._is_yes(input(t("Confirm? (y/N): "))):
            return
        self._erplibre_home_run_installer(
            commande,
            succes="ERPLibre Home uninstalled.",
            echec="ERPLibre Home uninstall failed, see the output above.",
        )

    def _streamdeck_extension(self):
        commande = self._streamdeck_choice(
            t("Extension action:"),
            (
                ("make erplibre_home_reload", t("Reload the extension")),
                (
                    f"gnome-extensions prefs {EXTENSION_UUID}",
                    t("Open its preferences"),
                ),
            ),
        )
        if commande is not None:
            self.execute.exec_command_live(commande, source_erplibre=False)

    # -------------------------------------------------------------- #
    # Questions de l'installation Stream Deck

    def _erplibre_home_streamdeck_options(self):
        """Les quatre questions de l'installation Stream Deck, chacune
        devenue une option de l'installateur. Le programme et la relance
        après un jeu passent toujours leur option, défaut compris : leurs
        défauts sont les valeurs des réglages en place, si bien qu'Entrée
        partout les réécrit telles quelles ; sans réglages, ce sont ceux de
        DEFAULTS. Le démarrage automatique et les outils facultatifs n'ont
        pas d'option négative : « non » n'ajoute rien. Rend la liste des
        options dans l'ordre des questions, ou None quand la première est
        abandonnée par 0."""
        reglages = service.read_settings(service.settings_path())
        programme = self._streamdeck_choice(
            t("Deck program:"),
            self._streamdeck_programs(),
            self._streamdeck_program_default(reglages["DECK_PROGRAM"]),
        )
        if programme is None:
            return None
        options = [f"--deck-program={programme}"]
        if self._is_yes(input(t("Start the deck program at login? (y/N): "))):
            options.append("--autostart")
        if reglages["RESTART_AFTER_GAME"] == "no":
            relance = self._is_yes(
                input(t("Restart the deck program after a game? (y/N): "))
            )
        else:
            relance = not self._is_no(
                input(t("Restart the deck program after a game? (Y/n): "))
            )
        if relance:
            options.append("--restart-after-game")
        else:
            options.append("--no-restart-after-game")
        if self._is_yes(
            input(t("Install the optional tools (--with-extras)? (y/N): "))
        ):
            options.append("--with-extras")
        return options
