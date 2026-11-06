#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import getpass
import logging
import os

from script.todo.todo_i18n import t

_logger = logging.getLogger(__name__)

# pykeepass s'importe dans `get_kdbx`, au moment d'ouvrir le coffre : le
# charger ici coûtait un cinquième de l'import de TODO, qui crée ce
# gestionnaire au démarrage sans ouvrir le coffre pour autant.
#
# tkinter reste à part : il ne sert QU'au sélecteur de fichier quand aucun
# chemin n'est configuré, et son absence ne doit pas empêcher d'ouvrir le
# coffre sur une machine sans interface graphique — un serveur.
try:
    import tkinter as tk
    from tkinter import filedialog
except ModuleNotFoundError:
    tk = None
    filedialog = None

from script.config.config_file import CONFIG_OVERRIDE_PRIVATE_FILE

# Le mot de passe du coffre, pour un script lancé sans terminal (conteneur,
# tâche planifiée) : le CHEMIN d'un fichier qui le porte, un secret docker
# monté sous /run/secrets par exemple. La valeur elle-même ne passe ni par
# l'environnement, que « docker inspect » et /proc/<pid>/environ montrent, ni
# par la configuration JSON. Prioritaire sur kdbx.password.
ENV_PASSWORD_FILE = "KDBX_PASSWORD_FILE"


def lire_mot_de_passe_fichier(chemin: str) -> str:
    """Le mot de passe que porte le fichier ``chemin``, fin de ligne finale
    retirée, ou une chaîne vide, avec la raison affichée, si le fichier ne se
    lit pas ou ne porte rien."""
    try:
        with open(chemin, encoding="utf-8") as fh:
            mot_de_passe = fh.read().rstrip("\r\n")
    except OSError as e:
        print(
            f"{t('kdbx_password_file_unreadable')}"
            f" {ENV_PASSWORD_FILE}={chemin} : {e.strerror}"
        )
        return ""
    if not mot_de_passe:
        print(
            f"{t('kdbx_password_file_unreadable')}"
            f" {ENV_PASSWORD_FILE}={chemin} : {t('kdbx_password_file_empty')}"
        )
    return mot_de_passe


def choisir_fichier_kdbx() -> str:
    """Le chemin du coffre choisi dans un sélecteur de fichier Tk, ou une
    chaîne vide : choix annulé, tkinter absent, ou aucun affichage.

    Sans affichage — un serveur, un conteneur, une session ssh sans
    redirection X — Tk ne s'ouvre pas et lève TclError ; le chemin vient
    alors de kdbx.path dans la configuration, que l'appelant réclame.
    """
    if tk is None:
        _logger.error("tkinter is not available: no file picker")
        return ""
    try:
        root = tk.Tk()
    except tk.TclError as e:
        _logger.error("No display for the file picker: %s", e)
        return ""
    try:
        root.withdraw()
        return filedialog.askopenfilename(
            title="Select a File",
            filetypes=(("KeepassX files", "*.kdbx"),),
        )
    finally:
        root.destroy()


class KdbxManager:
    def __init__(self, config_file) -> None:
        self._config_file = config_file
        self._kdbx = None

    def get_kdbx(self, attempts: int = 3):
        if self._kdbx:
            return self._kdbx

        kdbx_file_path = self._config_file.get_config_value(["kdbx", "path"])
        if not kdbx_file_path:
            kdbx_file_path = choisir_fichier_kdbx()
        if not kdbx_file_path:
            _logger.error(
                "KDBX is not configured, please fill kdbx.path in %s",
                CONFIG_OVERRIDE_PRIVATE_FILE,
            )
            return None

        try:
            from pykeepass import PyKeePass
            from pykeepass.exceptions import CredentialsError
        except ModuleNotFoundError:
            _logger.error("pykeepass is not installed")
            return None

        chemin_secret = os.environ.get(ENV_PASSWORD_FILE)
        if chemin_secret:
            kdbx_password = lire_mot_de_passe_fichier(chemin_secret)
            if not kdbx_password:
                return None
        else:
            kdbx_password = self._config_file.get_config_value(
                ["kdbx", "password"]
            )
        if kdbx_password:
            # Mot de passe pris dans la configuration : personne à qui
            # redemander, mais il peut être faux — le dire au lieu de
            # laisser remonter une trace de la bibliothèque.
            try:
                self._kdbx = PyKeePass(kdbx_file_path, password=kdbx_password)
            except CredentialsError:
                print(t("kdbx_wrong_password"))
                return None
            return self._kdbx

        # Saisie interactive. Un mot de passe refusé est le cas NORMAL ici,
        # pas une panne : la bibliothèque lève `CredentialsError` et, sans
        # ce rattrapage, la trace remontait jusqu'à tuer le CLI. On nomme
        # aussi le coffre — l'invite ne disait pas DE QUOI elle parlait.
        # `flush` : l'invite de getpass part vers le terminal, ce `print`
        # vers la sortie standard — qui est un TUBE quand le menu nous lance.
        # Sans vidage, on lisait « Mot de passe du coffre : Coffre KeePass :
        # /chemin » — la question avant ce dont elle parle.
        print(f"{t('kdbx_vault_is')} {kdbx_file_path}", flush=True)
        for _ in range(attempts):
            # Sans terminal, `getpass` lève — `termios.error` quand il ne
            # peut pas couper l'écho, `EOFError` quand l'entrée standard
            # est déjà fermée. Renoncer proprement plutôt que de laisser la
            # trace tuer le CLI : l'appelant sait dire « coffre non
            # joignable », et un script lancé sans terminal ne peut de
            # toute façon pas répondre.
            try:
                password = getpass.getpass(prompt=t("kdbx_ask_password"))
            except (EOFError, OSError):
                print(t("kdbx_no_terminal"))
                print(t("kdbx_no_terminal_hint"))
                return None
            if not password:
                print(t("kdbx_give_up"))
                return None
            try:
                self._kdbx = PyKeePass(kdbx_file_path, password=password)
            except CredentialsError:
                print(t("kdbx_wrong_password"))
                continue
            return self._kdbx
        print(t("kdbx_give_up"))
        return None

    def adopt(self, kdbx) -> None:
        """Prend pour la session une base DÉJÀ ouverte.

        Sert au moment où le coffre vient d'être CRÉÉ : `create_database`
        rend la base ouverte, et sans cela le mot de passe maître serait
        redemandé dans la seconde qui suit — à quelqu'un qui vient de le
        taper deux fois.
        """
        self._kdbx = kdbx

    def get_extra_command_user(
        self, kdbx_key: str | list | None
    ) -> tuple[str | list, dict]:
        """(fragments de commande, variables d'environnement à poser).

        Le mot de passe ne rejoint PAS la ligne de commande : seul le NOM
        d'une variable y figure. /proc/<pid>/cmdline est lisible par tout
        utilisateur de la machine, /proc/<pid>/environ par son seul
        propriétaire — et un mot de passe KeePass n'a rien à faire dans la
        liste des processus.

        Un nom par entrée : plusieurs identifiants partent dans UNE seule
        commande « parallel », donc une variable unique ne suffirait pas.
        """
        values = []
        env = {}
        if kdbx_key:
            kp = self.get_kdbx()
            if not kp:
                return "", {}
            if type(kdbx_key) is not list:
                kdbx_keys = [kdbx_key]
            else:
                kdbx_keys = kdbx_key
            for key in kdbx_keys:
                entry = kp.find_entries_by_title(key, first=True)
                try:
                    odoo_user = entry.username
                except AttributeError:
                    _logger.error(f"Cannot find username from keys {key}")
                try:
                    odoo_password = entry.password
                except AttributeError:
                    _logger.error(f"Cannot find password from keys {key}")
                var = f"EL_WEB_LOGIN_PWD_{len(values)}"
                env[var] = odoo_password
                values.append(
                    " --default_email_auth"
                    f" {odoo_user} --default_password_auth_env {var}"
                )
        if len(values) == 0:
            return "", {}
        elif len(values) == 1:
            return values[0], env
        return values, env
