#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'agent passerelle du modem, vu par la démonstration.

Il tourne TOUJOURS sur ce poste, quel que soit le mode : le modem est
branché ici, en USB. En mode VM, Odoo est ailleurs et l'agent l'interroge
par le réseau ; en mode local, les deux sont sur la même machine. C'est ce
qui distingue ce fichier de `local.py`, dont tout dépend du mode.

Le processus est détaché dans sa propre session, comme le serveur de
démonstration : l'agent doit survivre à la fermeture du menu, sans quoi la
passerelle retomberait en panne dès qu'on quitte l'écran qui l'a lancée.
"""
from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time
from pathlib import Path

from script.todo.modem import passerelle as agent_mod
from script.todo.sms.spec import BASE, DemoSpec, ensure_secret

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


AGENT_PID = BASE / "passerelle.pid"
AGENT_LOG = BASE / "passerelle.log"

#: Delai laisse a l'agent pour mourir de lui-meme quand la configuration est
#: refusee. Il rend la main tout de suite dans ce cas ; au-dela, il tourne.
DEMARRAGE = 3


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def venv_python() -> Path | None:
    """L'interpreteur qui porte les dependances des scripts ERPLibre."""
    chemin = repo_root() / ".venv.erplibre" / "bin" / "python"
    return chemin if chemin.exists() else None


def server_url(spec: DemoSpec, vm_ip: str = "") -> str:
    """L'adresse a laquelle l'agent trouvera Odoo.

    En mode VM c'est celle de la machine ; en local, la boucle. L'agent ne
    passe par aucun renvoi USB, contrairement au telephone : il est sur le
    poste, il joint directement.
    """
    hote = vm_ip if (vm_ip and spec.mode != "local") else "127.0.0.1"
    return f"http://{hote}:{spec.odoo_port}"


def environnement(spec: DemoSpec, secret: str, vm_ip: str = "") -> dict:
    """Les trois variables que l'agent exige, ajoutees a l'environnement."""
    return dict(
        os.environ,
        **{
            agent_mod.VARIABLE_URL: server_url(spec, vm_ip),
            agent_mod.VARIABLE_APPAREIL: spec.device_id,
            agent_mod.VARIABLE_SECRET: secret,
        },
    )


def modem_pret():
    """(pret, motif) — le modem repond-il, et sa SIM est-elle au reseau."""
    return agent_mod.ModemManagerSMS().pret()


def agent_pid() -> int:
    """Le PID de l'agent, ou 0 s'il ne tourne plus.

    On verifie que le processus EXISTE encore : un fichier PID survit a son
    processus, et s'y fier ferait croire a une passerelle vivante devant un
    serveur que plus personne n'interroge.
    """
    try:
        pid = int(AGENT_PID.read_text().strip())
    except (OSError, ValueError):
        return 0
    try:
        os.kill(pid, 0)
    except OSError:
        return 0
    return pid


def start_agent(state):
    """Lance l'agent en arriere-plan. Rend (ok, detail)."""
    existant = agent_pid()
    if existant:
        return True, f"{t('sms_agent_running')} (PID {existant})"

    python = venv_python()
    if python is None:
        return False, t("sms_local_no_venv")

    BASE.mkdir(parents=True, exist_ok=True)
    commande = (
        f"cd {shlex.quote(str(repo_root()))} && "
        f"exec {shlex.quote(str(python))} -m script.todo.modem.passerelle"
    )
    with open(AGENT_LOG, "ab") as journal:
        # `exec` fait remplacer bash par l'agent : le PID rendu reste valable
        # pour toute la duree du processus. `start_new_session` le detache du
        # terminal du menu, qui peut alors se fermer.
        processus = subprocess.Popen(
            ["bash", "-c", commande],
            stdout=journal,
            stderr=journal,
            stdin=subprocess.DEVNULL,
            env=environnement(state.spec, ensure_secret(), state.vm_ip),
            start_new_session=True,
        )
    AGENT_PID.write_text(str(processus.pid))

    # Une configuration refusee fait rendre la main tout de suite : on laisse
    # ce delai passer pour distinguer « parti » de « mort a la premiere
    # ligne », plutot que d'annoncer un succes que le journal dementira.
    for _ in range(DEMARRAGE * 2):
        if processus.poll() is not None:
            return False, f"{_derniere_ligne()} — {AGENT_LOG}"
        time.sleep(0.5)
    return True, f"PID {processus.pid} — {server_url(state.spec, state.vm_ip)}"


def stop_agent():
    pid = agent_pid()
    if not pid:
        return False, t("sms_agent_stopped")
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for _ in range(20):
        if not agent_pid():
            break
        time.sleep(0.5)
    try:
        AGENT_PID.unlink()
    except OSError:
        pass
    return True, t("sms_agent_stopped")


def _derniere_ligne() -> str:
    """La derniere ligne du journal, qui porte la cause d'un depart rate."""
    try:
        lignes = [
            ligne.strip()
            for ligne in AGENT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
            if ligne.strip()
        ]
    except OSError:
        return t("sms_agent_died")
    return lignes[-1][:300] if lignes else t("sms_agent_died")


def render_agent_config(spec: DemoSpec, secret: str, vm_ip: str = "") -> str:
    """Ce que l'agent recevra, affiche avant de le lancer.

    Rien n'est a recopier ici, contrairement au telephone : l'agent lit ces
    valeurs de son environnement. On les montre quand meme parce qu'un 404 ou
    un 403 se diagnostique en les comparant a la fiche dans Odoo, et qu'aller
    les chercher dans un journal detache est justement ce qu'on veut eviter.
    """
    largeur = 68
    barre = "=" * largeur
    return "\n".join([
        barre,
        "  AGENT PASSERELLE DU MODEM   (aucune saisie, tout est automatique)",
        barre,
        f"  URL du serveur    {server_url(spec, vm_ip)}",
        f"  Identifiant       {spec.device_id}",
        f"  Secret partage    {secret or '*** non genere ***'}",
        f"  Journal           {AGENT_LOG}",
        barre,
        "",
        "  L'agent interroge Odoo en HTTPS sortant, envoie par la carte SIM",
        "  du modem et rend compte. Il tourne sur CE poste dans les deux",
        "  modes : le modem y est branche en USB.",
        "",
        "  Il ne place PAS d'appels — il les refuse avec un motif, faute de",
        "  quoi un appel reclame resterait « publie » pour toujours.",
    ])
