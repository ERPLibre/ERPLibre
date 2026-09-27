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
import signal
import subprocess
import sys
import termios
import threading
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
# reproductible, il ne manque que ce qui ne doit pas être lu. Une option ne
# commence ni juste après un caractère de mot ni après un tiret, et n'est lue
# que si un blanc ou un « = » la suit : sans ces bornes, une longue suite de
# tirets, ou un mot qui répète « token », fait essayer chaque départ ou chaque
# occurrence jusqu'au bout du mot, en un temps au carré de sa longueur.
_SECRET_OPTION = re.compile(
    r"(?P<opt>(?<![\w-])--?(?=[\w-]*[\s=])[\w-]*"
    r"(?:password|passwd|pwd|secret|token|api[-_]?key)[\w-]*"
    r"(?:\s+|=))"
    r"(?P<val>'[^']*'|\"[^\"]*\"|\S+)",
    re.IGNORECASE,
)
# Une variable dont le nom porte le mot d'un secret, ou « _PWD »
# (MASTER_PWD) ; PWD et OLDPWD, des répertoires, restent. Le nom n'est lu que
# suivi de « = », pour la même raison de temps.
_SECRET_ENV = re.compile(
    r"(?P<var>\b(?=\w*=)\w*"
    r"(?:PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|_PWD)\w*=)"
    r"(?P<val>'[^']*'|\"[^\"]*\"|\S+)"
)
# Un jeton porté par un en-tête n'a ni nom d'option ni nom de variable : il
# suit le mot « Bearer », et les deux règles ci-dessus passent à côté. Le
# schéma est nommé par la RFC 7235 et se compare sans casse, la valeur allant
# jusqu'à la fin de la ligne — un jeton ne porte pas d'espace.
_SECRET_HEADER = re.compile(
    r"(?P<schema>\bAuthorization:\s*(?:Bearer|Basic)\s+)(?P<val>\S+)",
    re.IGNORECASE,
)
# Une URL porte ses identifiants dans l'« userinfo » (RFC 3986 §3.2.1) :
# « scheme://utilisateur:secret@hôte », que git, libpq et curl acceptent. On
# masque ce qui suit le deux-points jusqu'au DERNIER @ avant l'hôte (glouton) :
# un mot de passe tapé avec un « @ » non encodé (la RFC l'interdit, ça arrive
# quand même) reste ainsi caché en entier plutôt qu'à moitié. Il ne franchit
# jamais un espace ni un « / ». Il s'arrête d'abord avant « ? », « # », une
# virgule ou un guillemet, qui finissent l'autorité ou l'URL : un « @ » plus
# loin sur la ligne n'est pas celui de l'hôte, qui reste le vrai. Sans « @ »
# avant eux, il va jusqu'au dernier « @ », et un mot de passe qui en porte un
# reste caché en entier. Un port (« hôte:8069/ ») n'est jamais suivi d'un @ et
# reste. Le schéma est borné (32 caractères, RFC 3986 §3.1 l'autorise
# largement) pour qu'une ligne sans « :// » ne fasse pas remonter un temps de
# retour en arrière proportionnel à sa longueur.
_SECRET_URL_PASSWORD = re.compile(
    r"(?P<head>\b[a-z][a-z0-9+.-]{0,31}://[^\s/:@]*:)"
    r"(?P<val>[^\s/?#\"',]+(?=@)|[^\s/]+(?=@))",
    re.IGNORECASE,
)
# Un jeton peut aussi tenir lieu de nom d'utilisateur, sans deux-points, ou
# être SUIVI d'un mot de passe (GitHub : « <jeton>:x-oauth-basic@hôte »). Le
# lookahead accepte donc un « :quelquechose » optionnel avant l'@ ; sans lui,
# la règle du mot de passe ci-dessus masque déjà ce second segment (il ne
# reste que « :***@ ») et celle-ci ne voit alors plus jamais l'@ juste après
# le jeton, qui passe en clair. Un jeton se reconnaît à son préfixe (GitHub,
# GitLab) ou à défaut à sa longueur : 32 caractères opaques et plus. Un nom
# ordinaire (« git@ », « alice@ ») reste.
_SECRET_URL_TOKEN = re.compile(
    r"(?P<head>\b[a-z][a-z0-9+.-]{0,31}://)"
    r"(?P<val>(?:gh[pousr]_|github_pat_|glpat-)[\w-]+|[\w-]{32,})"
    r"(?=(?::[^\s/@]*)?@)",
    re.IGNORECASE,
)


def redact_secrets(text):
    """Remplace la valeur des options, variables, en-têtes et identifiants
    d'URL de secret.

    Appliqué à CHAQUE affichage d'une commande. Filtrer au point d'affichage
    plutôt qu'à la construction est ce qui rend la garantie tenable : il n'y a
    qu'une poignée de sorties ici, alors que les commandes se construisent
    partout dans le dépôt.
    """
    if not text:
        return text
    text = _SECRET_OPTION.sub(lambda m: m.group("opt") + "'***'", text)
    text = _SECRET_ENV.sub(lambda m: m.group("var") + "'***'", text)
    text = _SECRET_HEADER.sub(lambda m: m.group("schema") + "'***'", text)
    text = _SECRET_URL_PASSWORD.sub(lambda m: m.group("head") + "***", text)
    return _SECRET_URL_TOKEN.sub(lambda m: m.group("head") + "***", text)


# Une ligne de sortie qui imprime un mot de passe le fait sans nom d'option ni
# de variable : « Password: … », « password=… », « passwd … », « mot de
# passe : … », ou par une clé de configuration (« admin_passwd = … »,
# « POSTGRES_PASSWORD: … ») ou de JSON (« "password": … »). Le mot, sans
# casse, seul ou au bout d'un nom joint par « _ », un guillemet éventuel,
# puis sur la même ligne un deux-points, un signe égal ou des blancs
# (l'espace insécable comprise), fait masquer tout le reste de la ligne. Une
# invite qui attend encore sa réponse (« Password: ») n'a rien à masquer.
_PASSWORD_LINE = re.compile(
    r"(?P<head>(?<![^\W_])(?:password|passwd|mot de passe)\b[\"']?"
    r"(?:[^\S\n]*[:=][^\S\n]*|[^\S\n]+))(?P<val>\S.*)",
    re.IGNORECASE,
)
# Mots sans lesquels aucun motif de `redact_for_storage` ne masque rien,
# cherchés dans la ligne passée par casefold, qui rend comme la comparaison
# sans casse des motifs « ſ » en « s ». Aucun ne porte de « i » : le « ı »
# sans point l'égale sans casse, et casefold ne le rend pas.
_TRIGGERS = ("pass", "pwd", "secret", "token", "key", "auth", "://")


def redact_for_storage(text):
    """`redact_secrets(text)`, puis, sur chaque ligne qui imprime un mot de
    passe (`_PASSWORD_LINE`), ce qui suit le mot remplacé par « *** ».

    Pour ce que le hub garde sur disque, jamais pour l'affichage : à
    l'écran, « No password needed » se lit en entier ; dans un journal, il
    devient « No password *** », et un mot de passe imprimé n'y reste pas.
    Un texte sans aucun mot de `_TRIGGERS` est rendu tel quel sans essayer
    de motif : le hub passe chaque ligne de sortie d'une session dans sa
    boucle, que les autres sessions attendent.
    """
    if not text:
        return text
    folded = text.casefold()
    if not any(word in folded for word in _TRIGGERS):
        return text
    text = redact_secrets(text)
    return _PASSWORD_LINE.sub(lambda m: m.group("head") + "***", text)


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


def _set_foreground(fd, pgid):
    """Donne le terminal `fd` au groupe de processus `pgid`.

    Hors du premier plan, tcsetpgrp envoie SIGTTOU à l'appelant, ce qui
    l'arrête ; bloqué le temps de l'appel dans ce thread, le signal n'est
    pas émis et l'appel aboutit (POSIX).
    """
    old = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTTOU})
    try:
        os.tcsetpgrp(fd, pgid)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old)


class Execute:
    # Contrôle de tâches, posé par le worker d'une session web et jamais par
    # le CLI. Vrai, une commande a son propre groupe de processus, au
    # premier plan du terminal de contrôle le temps qu'elle tourne : l'octet
    # Ctrl+C écrit sur ce terminal n'interrompt qu'elle (code -2), et le
    # processus qui l'a lancée continue. Faux, la commande partage le groupe
    # de l'appelant, et Ctrl+C les interrompt tous deux. Une commande tuée
    # par un signal laisse le terminal vidé de ce qu'elle n'a pas lu. Sans
    # shell pour la reprendre, Ctrl+Z n'y suspend jamais rien : le terminal
    # de contrôle refuse de produire SIGTSTP.
    job_control = False
    # Crochet posé par le worker d'une session web et par le mode
    # enregistrement, jamais par le CLI : reçoit `run_start` (la commande
    # caviardée) avant le lancement et `run_end` (code, durée) à la fin.
    # Attribut de classe, il doit être une méthode liée ou une fonction
    # intégrée (`list.append` d'une liste) : une fonction simple recevrait
    # l'instance d'Execute en premier argument.
    events = None

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
        output_lines = []
        # Annoncée avant d'ouvrir le terminal : un échec ou une interruption
        # à l'ouverture a sa fin (`finally`), et aucun descripteur ouvert
        # ne précède le `try` qui le ferme.
        self._event({"t": "run_start", "cmd": redact_secrets(command)})
        tty = None

        try:
            tty = self._job_control_tty()
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
                **({"process_group": 0} if tty is not None else {}),
            )
            if tty is not None:
                try:
                    _set_foreground(tty, process.pid)
                    # Lancée hors du premier plan, la commande a pu lire le
                    # terminal avant de le recevoir : SIGTTIN l'a alors
                    # arrêtée.
                    os.killpg(process.pid, signal.SIGCONT)
                except OSError:
                    # Sans le premier plan, personne ne suivrait la commande.
                    # SIGKILL : arrêtée par SIGTTIN, elle garderait SIGTERM
                    # en attente.
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    raise

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

            def retenir(ligne):
                """Journaliser et retenir une ligne complète, caviardée."""
                nonlocal sink
                # La sortie du sous-processus passe par le MÊME filtre que la
                # commande : un outil qui réaffiche ses propres arguments
                # (« set -x », une trace, odoo_bin.sh) y remettrait le secret
                # que l'affichage de la commande venait d'écarter.
                clean = redact_secrets(ligne)
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
                    if not quiet:
                        print(redact_secrets(ligne[shown:]), end="")
                    shown = 0
                    retenir(ligne)
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
                retenir(pending)

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
            if not quiet:
                print(f"Error: Command '{redact_secrets(command)}' not found.")
        except Exception as e:
            exit_code = 1
            if not quiet:
                print(f"An error occurred: {redact_secrets(str(e))}")
        finally:
            if tty is not None:
                try:
                    _set_foreground(tty, os.getpgrp())
                    # Comme Ctrl+C au terminal, une commande tuée par un
                    # signal ne laisse pas ce qu'on lui a tapé répondre à la
                    # question suivante.
                    if exit_code is not None and exit_code < 0:
                        termios.tcflush(tty, termios.TCIFLUSH)
                except OSError:
                    pass  # terminal raccroché : plus rien à reprendre
                finally:
                    os.close(tty)
            # Une commande annoncée a toujours sa fin, même interrompue par
            # Ctrl+C sans contrôle de tâches : `rc` vaut alors None.
            secs = round(time.time() - process_start_time, 3)
            self._event({"t": "run_end", "rc": exit_code, "secs": secs})
        process_end_time = time.time()
        duration_sec = process_end_time - process_start_time
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

    def _event(self, message):
        """Donne `message` au crochet `events`, s'il est posé ; une erreur
        du crochet ne touche jamais la commande."""
        if self.events is None:
            return
        try:
            self.events(message)
        except Exception:
            pass

    def _job_control_tty(self):
        """Descripteur du terminal de contrôle, ouvert pour une commande
        lancée avec le contrôle de tâches ; None sans `job_control`, hors du
        fil principal (deux fils se disputeraient le premier plan) ou sans
        terminal de contrôle, et la commande tourne alors comme au CLI.
        VSUSP y est désactivé (comme `stty susp undef`) : sans shell pour
        reprendre une tâche suspendue, Ctrl+Z resterait bloqué en position
        arrêtée (état T) jusqu'à raccrocher la session entière."""
        main = threading.current_thread() is threading.main_thread()
        if not self.job_control or not main:
            return None
        try:
            tty = os.open("/dev/tty", os.O_RDWR)
        except OSError:
            return None
        try:
            attrs = termios.tcgetattr(tty)
            attrs[6][termios.VSUSP] = os.fpathconf(tty, "PC_VDISABLE")
            termios.tcsetattr(tty, termios.TCSANOW, attrs)
        except (OSError, termios.error):
            pass  # pas un terminal (tests) : rien à désactiver
        return tty
