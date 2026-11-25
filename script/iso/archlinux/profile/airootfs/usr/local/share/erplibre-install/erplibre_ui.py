#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'interface de l'installateur ERPLibre, lancée par erplibre-install
sur tty1 au démarrage du live (ou à la main).

Elle choisit son mode, puis tourne en boucle : l'écran d'accueil rend
une action, ce module l'exécute en lui laissant le terminal, puis
l'accueil revient.

- Mode Textual par défaut.
- Mode texte (erplibre_ui_plain) avec --plain, ou d'office quand TERM
  vaut « dumb », quand l'entrée ou la sortie n'est pas un terminal, sur
  une console série, ou quand textual ne s'importe pas.

Actions : « todo » lance TODO_BIN, « archinstall » l'archinstall guidé
pré-rempli de l'étape 1b, « reboot » redémarre, « shell » rend la main
au shell de root (code 0). L'installation elle-même tourne DANS
l'écran, par le cœur erplibre-installer.

--dry-run passe --dry-run au cœur : formulaire, récapitulatif et plan
complets, rien n'est écrit sur le disque.
"""

import argparse
import os
import re
import subprocess
import sys

import erplibre_ui_flow as flow
import erplibre_ui_i18n as i18n

# Les consoles série : un écran plein n'y a ni la taille ni les touches.
SERIAL_TTY_RE = re.compile(
    r"^/dev/(ttyS|ttyUSB|ttyACM|ttyAMA|ttymxc|hvc|ttysclp)\d*$"
)
DUMB_TERMS = frozenset({"", "dumb", "unknown"})


def _ttyname(fd):
    try:
        return os.ttyname(fd)
    except OSError:
        return ""


def textual_available():
    try:
        import textual  # noqa: F401
    except Exception:
        return False
    return True


def choose_mode(
    plain=False,
    env=None,
    isatty=os.isatty,
    ttyname=_ttyname,
    textual_ok=textual_available,
):
    """« plain » ou « tui », et la raison du mode texte (None en tui)."""
    env = os.environ if env is None else env
    if plain:
        return "plain", "option"
    if env.get("TERM", "") in DUMB_TERMS:
        return "plain", "term"
    if not (isatty(0) and isatty(1)):
        return "plain", "not-a-tty"
    if SERIAL_TTY_RE.match(ttyname(0) or ""):
        return "plain", "serial"
    if not textual_ok():
        return "plain", "no-textual"
    return "tui", None


def _parser():
    parser = argparse.ArgumentParser(
        description="ERPLibre installer: home screen, form, summary."
    )
    parser.add_argument(
        "--plain", action="store_true", help="line-by-line text mode"
    )
    parser.add_argument("--lang", choices=i18n.LANGS, help="fr or en")
    parser.add_argument("--machine", help="machine profile file (override)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ask everything, show the plan, erase nothing",
    )
    return parser


def run_action(action, donnee, ctx, tr, run=subprocess.run, write=print):
    """Exécute l'action rendue par l'accueil ; rend le code de sortie de
    l'interface, ou None pour revenir à l'accueil."""
    if action in ("todo", "archinstall"):
        _clear()
    if action == "todo":
        if not os.access(flow.TODO_BIN, os.X_OK):
            write(tr("ERPLibre TODO is not on this key."))
            _pause(tr)
            return None
        env = dict(os.environ, EL_LANG=tr.lang)
        rc = run([flow.TODO_BIN], check=False, env=env).returncode
        # L'accueil efface l'écran en revenant : un TODO qui sort en
        # erreur garde sa dernière sortie lisible jusqu'à Entrée.
        if rc != 0:
            write(tr("ERPLibre TODO returned {rc}.", rc=rc))
            _pause(tr)
        return None
    if action == "archinstall":
        config, archinstall = flow.archinstall_commands(
            ctx, donnee, _ttyname(0)
        )
        os.makedirs(os.path.dirname(archinstall[-1]), exist_ok=True)
        if run(config, check=False).returncode != 0:
            write(tr("Configuration not written."))
            _pause(tr)
            return None
        rc = run(archinstall, check=False).returncode
        if rc != 0:
            write(tr("archinstall returned {rc}.", rc=rc))
        _pause(tr)
        return None
    if action == "reboot":
        run(["systemctl", "reboot"], check=False)
        return 0
    return 0


def _clear():
    """Efface la console avant de la passer à un autre programme : l'écran
    quitté y laisse sinon sa dernière image."""
    if os.isatty(1):
        sys.stdout.write("\033[H\033[2J")
        sys.stdout.flush()


def _pause(tr):
    try:
        input(tr("Press Enter to go back to the home screen… "))
    except EOFError:
        pass


def main(argv=None):
    args = _parser().parse_args(argv)
    ctx = flow.load_context(lang=args.lang, override=args.machine)
    tr = i18n.translator(ctx["paths"]["share"], ctx["lang"])
    mode, raison = choose_mode(args.plain)
    while True:
        if mode == "tui":
            import erplibre_ui_tui as tui

            action, donnee, tr = tui.session(ctx, tr, dry_run=args.dry_run)
        else:
            import erplibre_ui_plain as plain

            if raison and raison != "option":
                print(f"[erplibre] text mode ({raison})")
                raison = None
            action, donnee, tr = plain.PlainUI(
                ctx, tr, dry_run=args.dry_run
            ).session()
        ctx["lang"] = tr.lang
        rc = run_action(action, donnee, ctx, tr)
        if rc is not None:
            return rc


if __name__ == "__main__":
    sys.exit(main())
