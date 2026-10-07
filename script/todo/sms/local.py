#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Démonstration sans machine virtuelle, sur le poste courant.

C'est le mode par défaut, et c'est le bon choix dans la plupart des cas :
la VM ajoute une heure d'installation, vingt gigaoctets, et surtout du
`sudo` — le déploiement QEMU passe par `qemu:///system`, donc par polkit, à
chaque interrogation d'adresse. Le mode local n'a besoin d'aucun privilège.

Ce qu'on y perd est réel et doit être dit : la démonstration s'exécute sur
le poste de développement, avec sa base PostgreSQL et son dépôt. Elle n'est
donc pas une preuve d'installation propre — pour ça, il faut la VM.

Odoo est lancé DÉTACHÉ. Le téléphone interroge le serveur toutes les trente
secondes ; un serveur qui mourrait en fermant le menu ferait retomber la
passerelle en panne sans que rien ne l'explique.
"""
from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time
from pathlib import Path

from script.todo.sms import gateway as gw
from script.todo.sms import spec as spec_mod
from script.todo.sms.spec import DemoSpec, ensure_secret

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


def pid_serveur(spec: DemoSpec) -> Path:
    """Le fichier PID du serveur de CETTE démonstration.

    Un fichier par matériel : les deux Odoo tournent en même temps, sur deux
    ports, et un PID commun ferait qu'arrêter l'un abattrait l'autre.
    """
    return spec_mod.dossier(spec.materiel) / "odoo.pid"


def journal_serveur(spec: DemoSpec) -> Path:
    return spec_mod.dossier(spec.materiel) / "odoo.log"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def find_venv() -> Path | None:
    """Le venv Odoo du dépôt.

    Son nom porte LES DEUX versions — Odoo et Python — et change avec elles.
    On le cherche donc au lieu de le composer, comme le veut le dépôt.
    """
    trouves = sorted(repo_root().glob(".venv.odoo*"))
    for chemin in trouves:
        if (chemin / "bin" / "python").exists():
            return chemin
    return None


def odoo_bin() -> Path:
    return repo_root() / "odoo18.0" / "odoo" / "odoo-bin"


# ----------------------------------------------------------------------
# Étape 1 — l'environnement
# ----------------------------------------------------------------------


def step_env(todo, state):
    """Vérifie que le poste peut jouer la démonstration.

    On échoue ici, avec un message clair, plutôt que trois étapes plus loin
    dans une trace Odoo de cinquante lignes.
    """
    manques = []

    venv = find_venv()
    if venv is None:
        manques.append(t("sms_local_no_venv"))
    if not odoo_bin().exists():
        manques.append(f"odoo-bin : {odoo_bin()}")

    from script.todo.sms.spec import trouver_module

    if trouver_module(state.spec.module) is None:
        manques.append(f"{t('sms_err_module_missing')} : {state.spec.module}")

    # PostgreSQL : on interroge, sans rien créer.
    try:
        res = subprocess.run(
            ["psql", "-lqt"], capture_output=True, text=True, timeout=30
        )
        if res.returncode != 0:
            manques.append(t("sms_local_no_postgres"))
    except (OSError, subprocess.SubprocessError):
        manques.append(t("sms_local_no_postgres"))

    if manques:
        return False, " | ".join(manques)

    state.vm_ip = "127.0.0.1"
    return True, f"{venv.name} | PostgreSQL"


# ----------------------------------------------------------------------
# Odoo, en local
# ----------------------------------------------------------------------


def _env_with_secret(spec: DemoSpec) -> dict:
    env = dict(os.environ)
    env[gw.ENV_SECRET] = ensure_secret(spec.materiel)
    return env


def _run_odoo(spec: DemoSpec, argv, timeout=2400, stdin_text=None):
    venv = find_venv()
    if venv is None:
        raise RuntimeError(t("sms_local_no_venv"))
    commande = [str(venv / "bin" / "python"), str(odoo_bin())] + argv
    return subprocess.run(
        commande,
        cwd=str(repo_root()),
        env=_env_with_secret(spec),
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def step_odoo(todo, state):
    """Crée la base et y installe le module.

    Le module n'a pas à être copié : en local, il est déjà dans le dépôt que
    lit Odoo. C'est tout l'intérêt de ce mode pendant le développement — on
    installe exactement ce qu'on vient d'écrire.
    """
    spec = state.spec
    subprocess.run(
        ["createdb", spec.db_name], capture_output=True, text=True, timeout=60
    )
    res = _run_odoo(
        spec,
        [
            "-c",
            "config.conf",
            "-d",
            spec.db_name,
            "-i",
            spec.module,
            "--stop-after-init",
            f"--http-port={spec.odoo_port}",
            "--log-level=warn",
        ]
    )
    if res.returncode != 0:
        return False, (res.stderr or res.stdout).strip()[-800:]
    return True, f"{spec.db_name} ← {spec.module}"


def step_gateway(todo, state):
    """Règle le fournisseur et crée la fiche passerelle."""
    spec = state.spec
    res = _run_odoo(
        spec,
        [
            "shell",
            "-c",
            "config.conf",
            "-d",
            spec.db_name,
            "--no-http",
            "--log-level=error",
        ],
        timeout=600,
        stdin_text=gw.render_setup_script(spec),
    )
    trouve = _parse(res.stdout)
    if not trouve.get("DEVICE_ID"):
        return False, (res.stderr or res.stdout).strip()[-800:]
    if trouve.get("SECRET_PRESENT") != "True":
        return False, t("sms_err_secret_absent")
    detail = t("sms_provider_set")
    if trouve.get("PROVIDER_PERIME"):
        detail += f" — {t('sms_provider_stale_cleared')}"
    return True, f"{trouve['DEVICE_ID']} ({detail})"


def step_verify(todo, state, number: str):
    """Envoie un SMS d'essai."""
    spec = state.spec
    res = _run_odoo(
        spec,
        [
            "shell",
            "-c",
            "config.conf",
            "-d",
            spec.db_name,
            "--no-http",
            "--log-level=error",
        ],
        timeout=600,
        stdin_text=gw.render_test_script(number, spec),
    )
    trouve = _parse(res.stdout)
    etat = trouve.get("ETAT")
    if not etat:
        return False, (res.stderr or res.stdout).strip()[-800:]
    # Retenu pour l'etape de confirmation : « le dernier envoi » ne suffit
    # pas, il faut CELUI-CI.
    state.last_uuid = trouve.get("UUID", "")
    return True, etat


# ----------------------------------------------------------------------
# Confirmation de l'envoi
# ----------------------------------------------------------------------

#: Etats depuis lesquels plus rien ne bougera.
TERMINAUX = ("delivered", "failed", "expired")

#: Combien de temps guetter avant de rendre la main. Un SMS met quelques
#: secondes ; au-dela, c'est que le telephone n'interroge pas, et attendre
#: plus longtemps n'apprend rien de neuf.
CONFIRM_TIMEOUT_S = 180


def dispatch_state(spec: DemoSpec, uuid: str):
    """(etat, code) de l'envoi, ou (None, "") s'il est introuvable.

    On interroge PostgreSQL directement plutot que `odoo-bin shell` : un
    shell Odoo met une dizaine de secondes a demarrer, ce qui interdit toute
    surveillance a intervalle court. Ici on lit, on n'ecrit pas.
    """
    res = subprocess.run(
        [
            "psql",
            "-d",
            spec.db_name,
            "-tAc",
            "SELECT state || '|' || coalesce(android_code,'') "
            "FROM erplibre_sms_dispatch WHERE sms_uuid = %s LIMIT 1"
            % _litteral(uuid),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    ligne = (res.stdout or "").strip()
    if not ligne:
        return None, ""
    etat, _, code = ligne.partition("|")
    return etat.strip(), code.strip()


def gateway_poll_age(spec: DemoSpec):
    """Secondes depuis la derniere interrogation, ou None si jamais.

    Lu par psql : c'est le seul fait qui prouve que le telephone parle. Une
    confirmation humaine ne prouve que la bonne volonte.
    """
    res = subprocess.run(
        [
            "psql",
            "-d",
            spec.db_name,
            "-tAc",
            "SELECT round(extract(epoch from now() at time zone 'UTC'"
            " - last_poll_at)) FROM erplibre_sms_gateway"
            " WHERE device_id = %s AND last_poll_at IS NOT NULL"
            % _litteral(spec.device_id),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    brut = (res.stdout or "").strip()
    try:
        return int(float(brut))
    except ValueError:
        return None


def taille_journal(spec: DemoSpec) -> int:
    """La taille du journal, pour ne relire ensuite que ce qui s'y ajoute."""
    try:
        return journal_serveur(spec).stat().st_size
    except OSError:
        return 0


def refus_recents(spec: DemoSpec, limite: int = 3, depuis_octet: int = 0):
    """Les derniers refus journalises par Odoo, avec leur motif.

    Traduit un echec muet en phrase utile : « signature invalide » designe le
    secret, « appareil inconnu » l'identifiant, et rien du tout le reseau.
    Sans cela, les trois pannes se ressemblent a l'ecran.

    `depuis_octet` borne la lecture a ce qui s'est ecrit DEPUIS un instant
    donne. Le journal est partage par tout ce qui interroge ce serveur :
    sans cette borne, le refus d'un autre agent, ou celui d'hier, est rendu
    comme la cause de l'attente qui vient d'echouer — et l'on va regler
    l'horloge d'un telephone dont l'horloge est juste.
    """
    motifs = {
        "signature invalide": "sms_diag_signature",
        "appareil inconnu": "sms_diag_device",
        "horodatage hors fenetre": "sms_diag_clock",
        "nonce rejoue": "sms_diag_nonce",
    }
    try:
        with open(journal_serveur(spec), "rb") as fichier:
            fichier.seek(max(0, depuis_octet))
            brut = fichier.read()
    except OSError:
        return []
    lignes = brut.decode("utf-8", errors="replace").splitlines()[-400:]
    trouves = []
    for ligne in reversed(lignes):
        for motif, cle in motifs.items():
            if motif in ligne:
                if cle not in trouves:
                    trouves.append(cle)
                break
        if len(trouves) >= limite:
            break
    return trouves


def _litteral(valeur: str) -> str:
    """Litteral SQL sur : on double les apostrophes plutot que d'esperer."""
    return "'" + str(valeur).replace("'", "''") + "'"


def _parse(sortie: str) -> dict:
    trouve = {}
    for ligne in (sortie or "").splitlines():
        if ligne.startswith("RESULTAT_"):
            cle, _, valeur = ligne.partition("=")
            trouve[cle[len("RESULTAT_") :]] = valeur.strip()
    return trouve


# ----------------------------------------------------------------------
# Le serveur, détaché
# ----------------------------------------------------------------------


def server_pid(spec: DemoSpec) -> int:
    """Le PID du serveur de démonstration, ou 0 s'il ne tourne pas.

    On vérifie que le processus existe ENCORE : un fichier PID survit à la
    mort de son processus, et se fier au fichier seul ferait croire à un
    serveur en vie devant un téléphone qui n'atteint rien.
    """
    try:
        pid = int(pid_serveur(spec).read_text().strip())
    except (OSError, ValueError):
        return 0
    try:
        os.kill(pid, 0)
    except OSError:
        return 0
    return pid


def start_server(spec: DemoSpec):
    """Lance Odoo en arrière-plan, et attend qu'il écoute.

    Détaché dans sa propre session : le téléphone interroge toutes les trente
    secondes, et un serveur qui s'arrêterait en fermant le menu ferait
    retomber la passerelle en panne sans explication.

    On attend que le port réponde avant de rendre la main. Sans cette
    attente, l'étape suivante annoncerait « prêt » alors qu'Odoo charge
    encore ses modules, et le téléphone se ferait éconduire sans motif.

    Un port déjà pris par un ÉTRANGER est refusé tout de suite, et nommé.
    Odoo s'arrête alors sur « Port is in use by another program » pendant que
    le port, lui, répond toujours : lire le port seul fait donc annoncer un
    serveur prêt pour un processus déjà mort, et la démonstration se poursuit
    contre un Odoo qui n'a ni la bonne base ni le bon secret.
    """
    existant = server_pid(spec)
    if existant:
        return True, f"{t('sms_local_server_running')} (PID {existant})"

    if _port_ouvert(spec.odoo_port):
        return False, f"{t('sms_local_port_taken')} ({spec.odoo_port})"

    venv = find_venv()
    if venv is None:
        return False, t("sms_local_no_venv")

    spec_mod._ensure_dossier(spec.materiel)
    commande = (
        f"cd {shlex.quote(str(repo_root()))} && "
        f"exec {shlex.quote(str(venv / 'bin' / 'python'))} "
        f"{shlex.quote(str(odoo_bin()))} -c config.conf "
        f"-d {shlex.quote(spec.db_name)} "
        f"--http-port={spec.odoo_port} --log-level=info"
    )
    with open(journal_serveur(spec), "ab") as journal:
        # PAS de commande `setsid` ici : `start_new_session=True` demande deja
        # a Python d'appeler setsid() dans l'enfant. Cumuler les deux fait que
        # le `setsid` externe se dedouble puis sort aussitot — on retenait
        # alors le PID d'un processus deja mort, et on croyait le serveur
        # tombe alors qu'il tournait. Resultat vecu : un Odoo orphelin sur le
        # port, que plus rien ne savait arreter.
        #
        # Le `exec` de la commande fait que bash est REMPLACE par Odoo : le
        # PID rendu par Popen reste donc valable pour la duree du serveur.
        processus = subprocess.Popen(
            ["bash", "-c", commande],
            stdout=journal,
            stderr=journal,
            stdin=subprocess.DEVNULL,
            env=_env_with_secret(spec),
            start_new_session=True,
        )
    pid_serveur(spec).write_text(str(processus.pid))

    # Attendre que le port réponde. Sans cette attente, l'étape suivante
    # dirait « prêt » alors qu'Odoo charge encore ses modules, et le
    # téléphone se ferait refuser sans qu'on sache pourquoi.
    for _ in range(60):
        # La mort du processus est lue AVANT le port : l'ordre inverse rendait
        # « prêt » pour un enfant mort dont un autre programme tenait le port.
        if processus.poll() is not None:
            return False, (
                f"{t('sms_local_server_died')} — {journal_serveur(spec)}"
            )
        if _port_ouvert(spec.odoo_port):
            return True, f"PID {processus.pid} — port {spec.odoo_port}"
        time.sleep(1)
    return False, f"{t('sms_local_server_slow')} — {journal_serveur(spec)}"


def stop_server(spec: DemoSpec):
    pid = server_pid(spec)
    if not pid:
        return False, t("sms_local_server_stopped")
    try:
        # Le groupe entier : `setsid` en a créé un, et tuer le seul chef
        # laisserait les ouvriers d'Odoo tenir le port.
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for _ in range(20):
        if not server_pid(spec):
            break
        time.sleep(0.5)
    try:
        pid_serveur(spec).unlink()
    except OSError:
        pass
    return True, t("sms_local_server_stopped")


def _port_ouvert(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prise:
        prise.settimeout(1.0)
        return prise.connect_ex(("127.0.0.1", port)) == 0
