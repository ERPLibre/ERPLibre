#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le message du hook SessionStart de Claude Code pour ce dépôt.

Claude Code le lance à l'ouverture d'une session et à sa reprise (voir
.claude/settings.json). Il écrit sur stdout un objet JSON : « systemMessage »
s'affiche dans le terminal, « hookSpecificOutput.additionalContext » entre
dans le contexte du modèle avant le premier message. Les deux portent le
même texte :

- l'état d'ERPLibre, le bilan que le TODO affiche à son ouverture ;
- la branche, le nombre de fichiers non commités et de commits non
  poussés, comparés aux refs distantes déjà connues, sans git fetch ;
- les cases non cochées de tasks/todo.md, le plan en cours ;
- le rappel de .claude/session_start_message.txt, s'il existe.

Tout est lu localement, en lecture seule, chaque commande git bornée par un
délai. Le script ne lève jamais et sort toujours avec le code 0 : un hook
qui échoue ne doit pas gêner l'ouverture d'une session. Il ne demande que
la bibliothèque standard, et tourne donc sans le venv d'ERPLibre.

    python3 script/claude/session_start.py < entree_du_hook.json
"""

import json
import os
import re
import subprocess
import sys

RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
sys.path.insert(0, RACINE)

PLAN = os.path.join("tasks", "todo.md")
RAPPEL = os.path.join(".claude", "session_start_message.txt")
# Au-delà, la liste noierait le reste du message.
CASES_MAX = 8
DELAI_GIT = 3
CASE_OUVERTE = re.compile(r"^\s*[-*] \[ \]\s+(.*\S)")


def _git(racine, *args):
    """La sortie de `git -C racine args`, ou None si git échoue."""
    try:
        fait = subprocess.run(
            ["git", "-C", racine, *args],
            capture_output=True,
            text=True,
            timeout=DELAI_GIT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return fait.stdout.strip() if fait.returncode == 0 else None


def lignes_travail(racine, t):
    """La branche, les fichiers non commités et les commits non poussés ;
    [] hors d'un checkout git."""
    branche = _git(racine, "rev-parse", "--abbrev-ref", "HEAD")
    if branche is None:
        return []
    statut = _git(racine, "status", "--porcelain") or ""
    non_commites = len([x for x in statut.splitlines() if x.strip()])
    non_pousses = _git(
        racine, "rev-list", "--count", "HEAD", "--not", "--remotes"
    )
    ligne = f"🌿 {t('Branch:')} {branche}"
    morceaux = []
    if non_commites:
        morceaux.append(f"{non_commites} {t('uncommitted files')}")
    if non_pousses and non_pousses != "0":
        morceaux.append(f"{non_pousses} {t('unpushed commits')}")
    if morceaux:
        ligne += " · " + " · ".join(morceaux)
    return [ligne]


def lignes_plan(racine, t):
    """Les cases non cochées de tasks/todo.md, CASES_MAX au plus."""
    try:
        with open(os.path.join(racine, PLAN), encoding="utf-8") as fh:
            ouvertes = [m.group(1) for m in map(CASE_OUVERTE.match, fh) if m]
    except OSError:
        return []
    if not ouvertes:
        return []
    lignes = [f"📋 {t('Plan in progress')} ({PLAN}) : {len(ouvertes)}"]
    lignes += [f"   - [ ] {texte}" for texte in ouvertes[:CASES_MAX]]
    if len(ouvertes) > CASES_MAX:
        lignes.append(f"   … +{len(ouvertes) - CASES_MAX}")
    return lignes


def lignes_rappel(racine):
    """Le texte de .claude/session_start_message.txt, lignes vides
    retirées ; [] s'il manque."""
    try:
        with open(os.path.join(racine, RAPPEL), encoding="utf-8") as fh:
            return [f"📌 {x.strip()}" for x in fh if x.strip()]
    except OSError:
        return []


def message(racine, source=None):
    """Le texte du message, une ligne par élément ; `source` vaut ce que
    Claude Code passe au hook (« startup », « resume »…)."""
    from script.todo import todo_etat
    from script.todo.todo_i18n import t

    titre = (
        t("ERPLibre — session resumed")
        if source == "resume"
        else t("ERPLibre — new session")
    )
    lignes = [titre]
    for partie in (
        lambda: todo_etat.bilan(racine),
        lambda: lignes_travail(racine, t),
        lambda: lignes_plan(racine, t),
        lambda: lignes_rappel(racine),
    ):
        try:
            lignes += partie()
        except Exception:
            continue
    return "\n".join(lignes)


def sortie_hook(texte):
    """L'objet JSON que Claude Code lit sur stdout."""
    return {
        "systemMessage": texte,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": texte,
        },
    }


def lire_source(flux):
    """Le champ « source » de l'entrée JSON du hook, ou None."""
    try:
        if flux.isatty():
            return None
        return json.loads(flux.read() or "{}").get("source")
    except (ValueError, OSError, AttributeError):
        return None


def main():
    try:
        source = lire_source(sys.stdin)
        # todo_i18n lit la langue dans ./env_var.sh : depuis la racine.
        os.chdir(RACINE)
        print(json.dumps(sortie_hook(message(RACINE, source))))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
