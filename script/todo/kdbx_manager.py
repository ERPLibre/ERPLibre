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


def _open_vault(opener, path, password):
    """Ouvre le coffre par `opener` (la classe `PyKeePass`) et retient
    l'identité du fichier lu.

    L'identité est prise AVANT la lecture : un fichier remplacé pendant
    qu'on le lit diffère de celle retenue, et la prochaine lecture
    fraîche (`SecretStore.get(fresh=True)`) le relit au lieu de le manquer.
    """
    from script.todo import kdbx_write

    identity = kdbx_write.file_identity(path)
    kp = opener(path, password=password)
    kdbx_write.note_loaded(kp, identity)
    return kp


class KdbxManager:
    """Ouvre le coffre KeePass désigné par la configuration, une fois.

    `interactive=True` (le CLI) : sélecteur de fichier si aucun chemin
    n'est configuré, saisie du mot de passe au terminal, messages imprimés.
    `interactive=False` (le service sans interface) : rien n'est demandé ni
    imprimé ; le mot de passe vient de `password`, sinon de `kdbx.password`
    dans la configuration. Un échec est mémorisé dans `last_error` et les
    appels suivants rendent None sans rouvrir le fichier ni redériver la
    clé.
    """

    # Valeurs de `last_error`, "" tant que rien n'a échoué.
    ERRORS = (
        "not_configured",
        "no_pykeepass",
        "no_password",
        "wrong_password",
        "unreadable",
    )

    def __init__(
        self,
        config_file,
        *,
        password: str | None = None,
        interactive: bool = True,
    ) -> None:
        self._config_file = config_file
        self._kdbx = None
        self._password = password
        self._interactive = interactive
        self._failed = False
        self.last_error = ""

    def get_kdbx(self, attempts: int = 3):
        if self._kdbx:
            return self._kdbx
        if not self._interactive:
            return self._get_kdbx_headless()

        kdbx_file_path = self._config_file.get_config_value(["kdbx", "path"])
        if not kdbx_file_path:
            if tk is None:
                _logger.error("tkinter is not available")
                return None
            root = tk.Tk()
            root.withdraw()
            kdbx_file_path = filedialog.askopenfilename(
                title="Select a File",
                filetypes=(("KeepassX files", "*.kdbx"),),
            )
        if not kdbx_file_path:
            _logger.error(
                "KDBX is not configured, please fill"
                f" {self._config_file.CONFIG_FILE}"
            )
            return None

        try:
            from pykeepass import PyKeePass
            from pykeepass.exceptions import CredentialsError
        except ModuleNotFoundError:
            _logger.error("pykeepass is not installed")
            return None

        kdbx_password = self._config_file.get_config_value(
            ["kdbx", "password"]
        )
        if kdbx_password:
            # Mot de passe pris dans la configuration : personne à qui
            # redemander, mais il peut être faux — le dire au lieu de
            # laisser remonter une trace de la bibliothèque.
            try:
                self._kdbx = _open_vault(
                    PyKeePass, kdbx_file_path, kdbx_password
                )
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
                return None
            if not password:
                print(t("kdbx_give_up"))
                return None
            try:
                self._kdbx = _open_vault(PyKeePass, kdbx_file_path, password)
            except CredentialsError:
                print(t("kdbx_wrong_password"))
                continue
            return self._kdbx
        print(t("kdbx_give_up"))
        return None

    def _config_value(self, keys: list):
        """La valeur de configuration sous `keys`, None si elle manque.

        `ConfigFile.get_config_value` lève `TypeError` sur une clé absente
        de premier niveau : ici une absence est une réponse, pas une panne.
        """
        try:
            return self._config_file.get_config_value(keys)
        except Exception:
            return None

    def _fail(self, reason: str):
        self._failed = True
        self.last_error = reason
        return None

    def _get_kdbx_headless(self):
        """Ouverture sans terminal ni fenêtre ; None et `last_error` posé
        sur échec, mémorisé pour les appels suivants."""
        if self._failed:
            return None
        path = self._config_value(["kdbx", "path"])
        path = os.path.expanduser(path) if isinstance(path, str) else ""
        if not path:
            return self._fail("not_configured")
        try:
            from pykeepass import PyKeePass
            from pykeepass.exceptions import CredentialsError
        except ModuleNotFoundError:
            return self._fail("no_pykeepass")
        password = self._password or self._config_value(["kdbx", "password"])
        if not password or not isinstance(password, str):
            return self._fail("no_password")
        try:
            self._kdbx = _open_vault(PyKeePass, path, password)
        except CredentialsError:
            return self._fail("wrong_password")
        except Exception as exc:
            # Le type seulement : le texte d'une erreur de lecture peut
            # citer le chemin du coffre.
            _logger.info("coffre illisible (%s)", type(exc).__name__)
            return self._fail("unreadable")
        self.last_error = ""
        return self._kdbx

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
