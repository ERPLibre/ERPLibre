#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

# Annotations différées : la migration charge ce module sous le Python
# d'Odoo 12 — 3.7 — où « dict | None » et « tuple[str, str] » n'existent
# pas encore. Sans ceci, l'annotation est ÉVALUÉE au chargement et la
# migration meurt sur un TypeError avant d'avoir rien fait.
from __future__ import annotations

import codecs
import datetime
import logging
import os
import re
import shutil
import subprocess
import sys
import time

try:
    import humanize
except ModuleNotFoundError as e:
    humanize = None

VENV_ERPLIBRE = ".venv.erplibre"

# Une commande construite ailleurs peut porter un secret en clair : todo.py et
# kdbx_manager.py y mettent « --default_password_auth '<mot de passe KeePass>' ».
# Cette commande est affichée avant et après l'exécution, et journalisée en
# erreur : le secret finissait donc dans le terminal, dans les journaux et dans
# toute sortie CI qui les capture.
#
# Ce filtre reste le dernier rempart, pas le premier : un secret n'a rien à
# faire sur argv, que /proc/<pid>/cmdline expose à tout utilisateur de la
# machine et qu'aucun caviardage n'atteint. db_restore.py est passé à
# MASTER_PWD dans l'environnement pour cette raison.
#
# On caviarde la VALEUR, jamais le nom de l'option : la commande reste lisible et
# reproductible, il ne manque que ce qui ne doit pas être lu.
_SECRET_OPTION = re.compile(
    r"(?P<opt>--?[\w-]*"
    r"(?:password|passwd|pwd|secret|token|api[-_]?key)[\w-]*"
    r"(?:\s+|=))"
    r"(?P<val>'[^']*'|\"[^\"]*\"|\S+)",
    re.IGNORECASE,
)
_SECRET_ENV = re.compile(
    r"(?P<var>\b\w*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY)\w*=)"
    r"(?P<val>'[^']*'|\"[^\"]*\"|\S+)",
    re.IGNORECASE,
)
# Un jeton porté par un en-tête n'a ni nom d'option ni nom de variable : il
# suit le mot « Bearer », et les deux règles ci-dessus passent à côté. Le
# schéma est nommé par la RFC 7235 et se compare sans casse, la valeur allant
# jusqu'à la fin de la ligne — un jeton ne porte pas d'espace.
_SECRET_HEADER = re.compile(
    r"(?P<schema>\bAuthorization:\s*(?:Bearer|Basic)\s+)(?P<val>\S+)",
    re.IGNORECASE,
)


# Les formes qui ne portent pas le mot « password » dans un nom d'option ou de
# variable. Chacune garde ce qui précède la valeur — l'option, la clé,
# l'utilisateur — pour que la ligne reste lisible.
#
# Une ligne de configuration, « db_password = x » ou « password: x » : le
# blanc autour du séparateur la distingue de « PGPASSWORD=x psql », dont
# _SECRET_ENV masque la valeur seule sans avaler la commande qui suit.
_SECRET_CONFIG = re.compile(
    r"(?P<cle>^[ \t]*[\w.-]*(?:passw|pwd|secret|token|api[-_]?key)[\w.-]*"
    r"(?:[ \t]+[=:][ \t]*|[=:][ \t]+))(?P<val>\S.*?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_SECRET_JSON = re.compile(
    r'(?P<cle>"[^"\n]*(?:passw|pwd|secret|token|api[-_]?key)[^"\n]*"\s*:\s*)'
    r'(?P<val>"(?:[^"\\\n]|\\.)*")',
    re.IGNORECASE,
)
# « scheme://utilisateur:motdepasse@hôte » : l'utilisateur reste.
_SECRET_URL = re.compile(
    r"(?P<pre>\b[a-z][a-z0-9+.-]*://[^\s/:@]+:)(?P<val>[^\s@/]+)(?=@)",
    re.IGNORECASE,
)
# Les jetons d'accès de GitHub et GitLab se reconnaissent à leur préfixe, même
# seuls dans une URL (« https://ghp_…@github.com »).
_SECRET_JETON = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|glpat-[\w-]{20,})"
)
# Les options courtes qui portent un mot de passe, propres à un outil : « -w »
# d'odoo-bin (db_password), « -p » de sshpass, « -pVALEUR » collé de mysql,
# « -u user:pass » de curl. Ailleurs ces lettres veulent dire autre chose
# (« grep -w », « docker exec -u odoo:odoo ») et restent intactes.
_SECRET_OUTIL = re.compile(
    r"(?P<opt>\bodoo(?:-bin|_bin\.sh)?\b[^\n]*?\s-w\s+"
    r"|\bsshpass\b[^\n]*?\s-p\s*"
    r"|\b(?:mysql|mariadb|mysqldump)\b[^\n]*?\s-p(?=[^\s'\"])"
    r"|\bcurl\b[^\n]*?\s(?:-u|--user)\s*['\"]?[^\s:'\"]+:)"
    r"(?P<val>'[^']*'|\"[^\"]*\"|[^\s'\"]+)"
)
# Une clé privée PEM entière dans un même texte (un message, un traceback).
# La sortie d'une commande arrive, elle, ligne par ligne : voir
# _caviarder_ligne, qui suit l'état d'une ligne à l'autre.
_PEM_DEBUT = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_PEM_FIN = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY-----")
_PEM_BLOC = re.compile(
    r"(?P<debut>-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----).*?"
    r"(?P<fin>-----END [A-Z0-9 ]*PRIVATE KEY-----)",
    re.DOTALL,
)


def redact_secrets(text):
    """Remplace la valeur des options, variables et en-têtes de secret.

    Appliqué à CHAQUE affichage d'une commande. Filtrer au point d'affichage
    plutôt qu'à la construction est ce qui rend la garantie tenable : il n'y a
    qu'une poignée de sorties ici, alors que les commandes se construisent
    partout dans le dépôt.

    Un dernier rempart, pas une garantie : un secret qu'un programme imprime
    sous une forme imprévue passe.
    """
    if not text:
        return text
    masque = "'***'"
    text = _PEM_BLOC.sub(
        lambda m: m.group("debut") + masque + m.group("fin"), text
    )
    text = _SECRET_OPTION.sub(lambda m: m.group("opt") + masque, text)
    text = _SECRET_OUTIL.sub(lambda m: m.group("opt") + masque, text)
    text = _SECRET_ENV.sub(lambda m: m.group("var") + masque, text)
    text = _SECRET_CONFIG.sub(lambda m: m.group("cle") + masque, text)
    text = _SECRET_JSON.sub(lambda m: m.group("cle") + '"***"', text)
    text = _SECRET_URL.sub(lambda m: m.group("pre") + masque, text)
    text = _SECRET_JETON.sub(masque, text)
    return _SECRET_HEADER.sub(lambda m: m.group("schema") + masque, text)


def _caviarder_ligne(ligne, dans_cle):
    """Une ligne de sortie caviardée, et si la suivante est dans une clé PEM.

    Entre « -----BEGIN … PRIVATE KEY----- » et sa fin, chaque ligne devient
    '***' : le corps d'une clé n'a aucun mot qui la signale.
    """
    if dans_cle:
        if _PEM_FIN.search(ligne):
            return ligne, False
        fin = ligne[len(ligne.rstrip("\r\n")) :]
        return "'***'" + fin, True
    if _PEM_DEBUT.search(ligne) and not _PEM_FIN.search(ligne):
        return ligne, True
    return redact_secrets(ligne), False


new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)


logging.basicConfig(
    format=(
        "%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d]"
        " %(message)s"
    ),
    datefmt="%Y-%m-%d:%H:%M:%S",
    level=logging.INFO,
)
_logger = logging.getLogger(__name__)

# Le journal de session : un fichier texte ouvert par celui qui lance le
# processus (script/todo/todo_journal.py pour le TODO), où exec_command_live
# recopie chaque commande, sa sortie et son code de retour, caviardés comme à
# l'écran. Commun à toutes les instances d'Execute du processus, à côté du
# log_sink propre à une instance. None : rien n'est recopié.
_session_journal = None


def set_session_journal(handle):
    """Désigne le fichier du journal de session, ou None pour l'arrêter."""
    global _session_journal
    _session_journal = handle


def _journaliser(texte, deja_caviarde=True):
    """Écrit dans le journal de session ; une erreur l'arrête, sans lever.

    `deja_caviarde=False` fait passer le texte par redact_secrets : pour ce
    qui ne vient pas de exec_command_live, comme un traceback.

    Un disque plein ou un fichier effacé ne doit jamais faire échouer la
    commande qu'on est en train de suivre.
    """
    global _session_journal
    if _session_journal is None:
        return
    try:
        if not deja_caviarde:
            texte = redact_secrets(texte)
        _session_journal.write(texte)
    except Exception:
        _session_journal = None


class Execute:
    def __init__(self) -> None:
        self.cmd_source_erplibre: str = ""
        self.cmd_source_default: str = ""
        exec_path_gnome_terminal = shutil.which("gnome-terminal")
        if exec_path_gnome_terminal:
            self.cmd_source_erplibre = (
                f"gnome-terminal -- bash -c 'source"
                f" ./{VENV_ERPLIBRE}/bin/activate;%s'"
            )
            self.cmd_source_default = f"gnome-terminal -- bash -c '%s'"
        else:
            exec_path_tell = shutil.which("osascript")
            if exec_path_tell:
                self.cmd_source_erplibre = (
                    "osascript -e 'tell application \"Terminal\"'"
                )
                self.cmd_source_erplibre += " -e 'tell application \"System Events\" to keystroke \"t\" using {command down}' -e 'delay 0.1' -e 'do script \""
                self.cmd_source_erplibre += f"cd {os.getcwd()}; source ./{VENV_ERPLIBRE}/bin/activate; %s\" in front window'"
                self.cmd_source_erplibre += " -e 'end tell'"
            else:
                self.cmd_source_erplibre = (
                    f"source ./{VENV_ERPLIBRE}/bin/activate;%s"
                )

    def exec_command_live(
        self,
        command: str,
        source_erplibre: bool = True,
        quiet: bool = False,
        single_source_erplibre: bool = False,
        new_window: bool = False,
        single_source_odoo: bool = False,
        source_odoo: str = "",
        new_env: dict | None = None,
        return_status_and_command: bool = False,
        return_status_and_output: bool = False,
        return_status_and_output_and_command: bool = False,
    ) -> (
        int
        | tuple[int, str]
        | tuple[int, list[str]]
        | tuple[int, str, list[str]]
    ):
        """
        Execute a command and display its output live.

        Args:
            command (str): The command to execute.
        """

        my_env = os.environ.copy()
        if new_env:
            my_env.update(new_env)

        process_start_time = time.time()
        exit_code = None
        if source_erplibre:
            # command = f"source ./{VENV_ERPLIBRE}/bin/activate && " + command
            # cmd = (
            #     f"gnome-terminal --tab -- bash -c 'source"
            #     f" ./{VENV_ERPLIBRE}/bin/activate;{command}'"
            # )
            command = self.cmd_source_erplibre % command
            # os.system(f"./script/terminal/open_terminal.sh {command}")
        elif single_source_erplibre:
            command = f"source ./{VENV_ERPLIBRE}/bin/activate && %s" % command
        elif single_source_odoo:
            if not source_odoo and os.path.exists("./.erplibre-version"):
                with open("./.erplibre-version") as f:
                    source_odoo = f.read()
            if not source_odoo:
                _logger.error(
                    "You cannot execute Odoo command if no version is"
                    f" installed. Command : {redact_secrets(command)}"
                )
                # Return the SAME shape the caller asked for. A bare int here
                # made callers doing « status, cmd = exec_command_live(...) »
                # crash with ValueError instead of seeing the failure.
                if return_status_and_output_and_command:
                    return 1, command, []
                if return_status_and_command:
                    return 1, command
                if return_status_and_output:
                    return 1, []
                return 1
            command = f"source ./.venv.{source_odoo}/bin/activate && {command}"
        if new_window and self.cmd_source_default:
            command = self.cmd_source_default % command

        if not quiet:
            print("🏠 ⬇ Execute command :\n")
            print(redact_secrets(command))
        _journaliser(
            f"\n[{datetime.datetime.now():%H:%M:%S}] $ {redact_secrets(command)}\n"
        )
        output_lines = []

        try:
            process = subprocess.Popen(
                command,
                shell=True,
                executable="/bin/bash",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                # Octets bruts, SANS tampon. « readline » attendait le saut de
                # ligne pour rendre la main : une invite qui n'en porte pas —
                # « Continuer ? [o/N] » — restait donc invisible jusqu'à ce que
                # la réponse soit déjà tapée. La question s'affichait APRÈS la
                # réponse, et l'on répondait à l'aveugle.
                bufsize=0,
                env=my_env,
            )

            sink = getattr(self, "log_sink", None)
            # Le tube porte des octets, et une lecture peut couper un caractère
            # accentué ou un emoji en deux. Le décodeur incrémental garde le
            # morceau incomplet en attente au lieu de rendre un « ? ».
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            fd = process.stdout.fileno()
            # « pending » est la ligne en cours, pas encore terminée ; « shown »
            # compte ce qui en a déjà été envoyé au terminal, pour ne jamais
            # afficher deux fois le même morceau d'invite quand la ligne finit
            # par se terminer.
            pending = ""
            shown = 0

            # Vrai entre le début et la fin d'une clé privée affichée.
            dans_cle = False

            def retenir(clean):
                """Journaliser et retenir une ligne complète, DÉJÀ caviardée.

                La sortie du sous-processus passe par le MÊME filtre que la
                commande : un outil qui réaffiche ses propres arguments
                (« set -x », une trace, odoo_bin.sh) y remettrait le secret
                que l'affichage de la commande venait d'écarter.
                """
                nonlocal sink
                _journaliser(clean)
                if sink:
                    # Chaque ligne passe DÉJÀ ici : c'est le seul endroit où
                    # journaliser sans rien changer à ce que le terminal
                    # montre. Une erreur d'écriture ne doit jamais faire
                    # échouer la commande qu'on est en train de suivre.
                    try:
                        sink.write(clean)
                    except Exception:
                        sink = None
                if (
                    return_status_and_output
                    or return_status_and_output_and_command
                ):
                    # Remove last \n char
                    output_lines.append(
                        clean.removesuffix("\r\n")
                        .removesuffix("\n")
                        .removesuffix("\r")
                    )

            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                pending += decoder.decode(chunk)
                while True:
                    coupe = pending.find("\n")
                    if coupe < 0:
                        break
                    ligne = pending[: coupe + 1]
                    pending = pending[coupe + 1 :]
                    clean, dans_cle = _caviarder_ligne(ligne, dans_cle)
                    if not quiet:
                        # Un début de ligne déjà montré comme invite ne se
                        # réaffiche pas : seule la suite part à l'écran.
                        if shown:
                            print(redact_secrets(ligne[shown:]), end="")
                        else:
                            print(clean, end="")
                    shown = 0
                    retenir(clean)
                if not quiet:
                    if len(pending) > shown:
                        # Le reliquat sans saut de ligne EST l'invite : la
                        # montrer tout de suite, avant que la commande ne se
                        # bloque sur la lecture de la réponse.
                        print(redact_secrets(pending[shown:]), end="")
                        shown = len(pending)
                    # Sans vidage explicite, cette invite resterait dans le
                    # tampon de Python : second endroit où la question se
                    # perdait, la sortie n'étant vidée qu'au saut de ligne.
                    sys.stdout.flush()

            pending += decoder.decode(b"", True)
            if pending:
                if not quiet:
                    print(redact_secrets(pending[shown:]), end="")
                    sys.stdout.flush()
                retenir(_caviarder_ligne(pending, dans_cle)[0])
                if not pending.endswith("\n"):
                    # Le code de retour qui suit ouvre sa propre ligne.
                    _journaliser("\n")

            process.wait()
            exit_code = process.returncode
            if process.returncode != 0 and not quiet:
                print(f"Command returned error code: {process.returncode}")

        # An exception MUST report a failure. exit_code stays None otherwise,
        # and None is falsy: callers testing « if not status: » would mark the
        # step as done, and « if status and wait_at_error » would skip the error
        # prompt. A crashed command was therefore recorded as a success.
        except FileNotFoundError:
            exit_code = 1
            _journaliser("Error: command not found.\n")
            if not quiet:
                print(f"Error: Command '{redact_secrets(command)}' not found.")
        except Exception as e:
            exit_code = 1
            _journaliser(f"An error occurred: {redact_secrets(str(e))}\n")
            if not quiet:
                print(f"An error occurred: {redact_secrets(str(e))}")
        process_end_time = time.time()
        duration_sec = process_end_time - process_start_time
        _journaliser(f"[code {exit_code}, {duration_sec:.1f} s]\n")
        if humanize:
            duration_delta = datetime.timedelta(seconds=duration_sec)
            human_time = humanize.precisedelta(duration_delta)
            if not quiet:
                print(f"🏠 ⬆ Executed ({human_time}) :\n")
        else:
            if not quiet:
                print(f"🏠 ⬆ Executed ({duration_sec:.2f} sec.) :\n")
        if not quiet:
            print(redact_secrets(command))
            print()
        if return_status_and_output_and_command:
            return exit_code, command, output_lines
        if return_status_and_command:
            return exit_code, command
        if return_status_and_output:
            return exit_code, output_lines
        return exit_code
