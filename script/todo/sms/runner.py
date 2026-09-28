#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Exécution des étapes de la démonstration.

Ce module est le seul du paquet à connaître QEMU et SSH. `steps` décrit,
`runner` fait — la séparation permet de tester la logique d'enchaînement sans
machine virtuelle, et de remplacer l'exécution sans toucher au reste.

Chaque fonction d'étape renvoie `(ok: bool, message: str)` et n'écrit jamais
dans l'état : c'est l'appelant qui décide de marquer l'étape, pour que le
menu et le tableau de bord aient la même politique.
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from script.todo.sms import gateway as gw
from script.todo.sms.spec import DemoSpec, ensure_secret

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


#: Racine d'ERPLibre dans la VM, telle que la pose `_qemu_erplibre_remote_cmd`
#: hors mode production.
REMOTE_ROOT = "~/git/erplibre"

#: Où le module doit atterrir dans la VM.
REMOTE_ADDONS = f"{REMOTE_ROOT}/odoo18.0/addons/addons"


def repo_root() -> Path:
    """La racine du dépôt hôte, déduite de l'emplacement de ce fichier."""
    return Path(__file__).resolve().parents[3]


def module_path(spec: DemoSpec):
    """Le module de la demonstration, cherche dans les depots d'addons.

    Rend None quand il est introuvable : c'est a l'appelant de le dire, avec
    le nom cherche plutot qu'un chemin invente.
    """
    from script.todo.sms.spec import trouver_module

    return trouver_module(spec.module)


# ----------------------------------------------------------------------
# SSH
# ----------------------------------------------------------------------


def ssh_target(todo, spec: DemoSpec, state=None) -> str:
    """`erplibre@<ip>`, ou une chaîne vide si la VM n'a pas d'adresse.

    On REUTILISE l'adresse deja decouverte quand on l'a. Sans cela, chaque
    commande SSH rappelle `_qemu_ssh_target`, qui re-resout l'adresse par
    `sudo virsh domifaddr` avec un plafond de cinq minutes — et une
    demonstration compte au moins quatre commandes SSH. Une session sudo
    expiree entre deux etapes suffirait a relancer la rafale de mots de
    passe que ce module est cense avoir supprimee.
    """
    if state is not None and getattr(state, "vm_ip", ""):
        return f"erplibre@{state.vm_ip}"
    return todo._qemu_ssh_target(spec.vm_name, "libvirt")


def ssh_run(
    todo, spec: DemoSpec, command: str, timeout: int = 900, state=None
):
    """Exécute une commande dans la VM. Renvoie `subprocess.CompletedProcess`.

    La commande est passée quotée : elle traverse un shell distant, et une
    apostrophe dans un secret ou un corps de message suffirait sinon à la
    couper en deux.
    """
    cible = ssh_target(todo, spec, state)
    if not cible:
        raise RuntimeError(t("sms_err_no_ip"))
    argv = ["ssh"] + list(todo._qemu_ssh_opts("libvirt")) + [cible, command]
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout
    )


# ----------------------------------------------------------------------
# Confirmation de l'envoi
# ----------------------------------------------------------------------

#: Etats depuis lesquels plus rien ne bougera.
TERMINAUX = ("delivered", "failed", "expired")

#: Combien de temps guetter avant de rendre la main. Un SMS met quelques
#: secondes ; au-dela, c'est que le telephone n'interroge pas, et attendre
#: plus longtemps n'apprend rien de neuf.
CONFIRM_TIMEOUT_S = 180


def dispatch_state(spec: DemoSpec, uuid: str, todo=None, state=None):
    """(etat, code) de l'envoi dans la VM, lu par psql au travers de SSH."""
    requete = (
        "SELECT state || '|' || coalesce(android_code,'') "
        "FROM erplibre_sms_dispatch WHERE sms_uuid = "
        + "'"
        + str(uuid).replace("'", "''")
        + "' LIMIT 1"
    )
    res = ssh_run(
        todo,
        spec,
        f"psql -d {shlex.quote(spec.db_name)} -tAc {shlex.quote(requete)}",
        timeout=60,
        state=state,
    )
    ligne = (res.stdout or "").strip()
    if not ligne:
        return None, ""
    etat, _, code = ligne.partition("|")
    return etat.strip(), code.strip()


def _parse_results(sortie: str) -> dict:
    """Relit les lignes `RESULTAT_CLE=valeur` d'un script distant.

    Les scripts impriment leur résultat plutôt que de renvoyer un code : un
    `odoo-bin shell` sort en 0 même quand la logique métier a échoué, donc le
    code de sortie ne prouve rien.
    """
    trouve = {}
    for ligne in (sortie or "").splitlines():
        if ligne.startswith("RESULTAT_"):
            cle, _, valeur = ligne.partition("=")
            trouve[cle[len("RESULTAT_") :]] = valeur.strip()
    return trouve


# ----------------------------------------------------------------------
# Étape 1 — la VM
# ----------------------------------------------------------------------


def sudo_disponible() -> bool:
    """Vrai si `sudo` passe SANS demander de mot de passe.

    Le mode VM en a besoin partout : `deploy_qemu.py` s'execute sous sudo, et
    la resolution d'adresse appelle `sudo virsh --connect qemu:///system` A
    CHAQUE TOUR de son attente. Sans session sudo en cache, cela produit une
    demande de mot de passe par tour — mesure sur le terrain : trente en trois
    minutes, pour une VM qui n'existait meme pas.
    """
    try:
        res = subprocess.run(
            ["sudo", "-n", "true"], capture_output=True, timeout=15
        )
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def vm_definie(nom: str) -> bool:
    """Vrai si le domaine existe cote systeme. UNE seule invocation."""
    try:
        res = subprocess.run(
            [
                "sudo",
                "-n",
                "virsh",
                "--connect",
                "qemu:///system",
                "domstate",
                nom,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def build_vm_spec(todo, spec: DemoSpec) -> dict:
    """La spécification attendue par `_qemu_run_spec`.

    On réutilise le chemin de déploiement existant au lieu d'appeler
    `virt-install` nous-mêmes : il gère déjà le cache d'images, cloud-init,
    la résolution d'IP, l'écriture de `~/.ssh/config` et le suivi.
    """
    vm = todo._qemu_make_vm(
        spec.distro,
        spec.version,
        "amd64",
        spec.memory_mb,
        spec.disk_gb,
        2,
        spec.vm_name,
    )
    return {
        "res_label": "SMS",
        "vms": [vm],
        "existing": [],
        "ssh_key": "",
        "timezone": "",
        "locale": "",
        "desktop": False,
        "vm_tools": (),
        "python_provider": "",
        "app_store": "deb",
        "install": {
            "branch": "master",
            "prod": False,
            "label": "ERPLibre + Odoo 18",
            "cmd": "make install_os && make install_odoo_18",
            "monitor": True,
        },
        "monitor": True,
        "add_ssh_config": True,
        "parallelism": 1,
    }


def step_vm(todo, state):
    """Crée la VM et y installe ERPLibre + Odoo 18.

    C'est de loin l'étape la plus longue — téléchargement d'image, installation
    système, compilation des dépendances Python. Elle délègue au suivi
    d'installation existant, qui détache les processus : fermer le menu
    n'interrompt pas l'installation.
    """
    spec = state.spec
    # Verifier sudo AVANT tout : sans session en cache, la suite demande un
    # mot de passe a chaque tour de boucle, des dizaines de fois.
    if not sudo_disponible():
        return False, t("sms_err_sudo")

    vm_spec = build_vm_spec(todo, spec)
    todo._qemu_run_spec(vm_spec)

    # Ne PAS attendre une adresse pour une machine qui n'existe pas : c'est
    # exactement ce qui produisait la rafale de demandes de mot de passe.
    if not vm_definie(spec.vm_name):
        # `vm_definie` emploie `sudo -n` : une session expiree pendant la
        # longue installation echoue sans invite et ressemblerait a une VM
        # absente. On distingue les deux, sinon le message envoie chercher
        # au mauvais endroit.
        if not sudo_disponible():
            return False, t("sms_err_sudo")
        return False, t("sms_err_vm_absente")

    ip = todo._qemu_vm_ip(spec.vm_name, timeout=180)
    if not ip:
        return False, t("sms_err_no_ip")
    state.vm_ip = ip

    # Une adresse qui repond ne prouve PAS qu'ERPLibre est installe : le
    # tableau de bord d'installation peut etre ferme avant la fin, et
    # l'installation continue alors en arriere-plan. Sans cette verification,
    # l'etape se dirait reussie et c'est l'etape suivante qui echouerait sur
    # « venv Odoo introuvable » — un diagnostic qui designe le mauvais
    # coupable.
    sonde = ssh_run(
        todo,
        spec,
        f"ls -d {REMOTE_ROOT}/.venv.odoo18.0_python* >/dev/null 2>&1",
        timeout=60,
        state=state,
    )
    if sonde.returncode != 0:
        return False, t("sms_err_install_en_cours")
    return True, ip


# ----------------------------------------------------------------------
# Étape 2 — le module dans la VM
# ----------------------------------------------------------------------


def step_odoo(todo, state):
    """Copie le module depuis l'arbre de travail et l'installe dans la VM.

    On copie depuis l'hôte plutôt que de tirer une branche : la démonstration
    doit montrer le code qu'on a sous la main, y compris ce qui n'est pas
    encore commité. C'est aussi ce qui la rend utilisable pendant le
    développement du module lui-même.
    """
    spec = state.spec
    source = module_path(spec)
    if source is None:
        return False, f"{t('sms_err_module_missing')} : {spec.module}"

    cible = ssh_target(todo, spec, state)
    if not cible:
        return False, t("sms_err_no_ip")

    # rsync plutôt que scp : rejouable sans tout retransférer, et `--delete`
    # garantit qu'un fichier supprimé sur l'hôte disparaît aussi de la VM —
    # sans quoi un module renommé laisserait ses deux versions en place.
    opts = " ".join(shlex.quote(o) for o in todo._qemu_ssh_opts("libvirt"))
    argv = [
        "rsync",
        "-a",
        "--delete",
        "--exclude",
        "__pycache__",
        "-e",
        f"ssh {opts}",
        f"{source}/",
        f"{cible}:{REMOTE_ADDONS}/{spec.module}/",
    ]
    prep = ssh_run(
        todo, spec, f"mkdir -p {REMOTE_ADDONS}", timeout=60, state=state
    )
    if prep.returncode != 0:
        return False, prep.stderr.strip()[:500]
    copie = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    if copie.returncode != 0:
        return False, copie.stderr.strip()[:500]

    secret = ensure_secret()
    distant = (
        f"cd {REMOTE_ROOT} && "
        # Le nom du venv porte les DEUX versions et change avec elles : on le
        # découvre au lieu de le composer, comme le veut le dépôt.
        "VENV=$(ls -d .venv.odoo18.0_python* 2>/dev/null | head -1) && "
        '[ -n "$VENV" ] || { echo "venv Odoo introuvable" >&2; exit 2; } && '
        f"export {gw.ENV_SECRET}={shlex.quote(secret)} && "
        f"(createdb {shlex.quote(spec.db_name)} 2>/dev/null || true) && "
        f'"$VENV/bin/python" odoo18.0/odoo/odoo-bin '
        f"-c config.conf -d {shlex.quote(spec.db_name)} "
        f"-i {shlex.quote(spec.module)} --stop-after-init "
        f"--http-port={spec.odoo_port} --log-level=warn"
    )
    res = ssh_run(todo, spec, distant, timeout=2400, state=state)
    if res.returncode != 0:
        return False, (res.stderr or res.stdout).strip()[-800:]
    return True, t("sms_module_installed")


# ----------------------------------------------------------------------
# Étape 3 — la passerelle
# ----------------------------------------------------------------------


def step_gateway(todo, state):
    """Règle le fournisseur SMS et crée la fiche passerelle."""
    spec = state.spec
    secret = ensure_secret()
    script = gw.render_setup_script(spec)
    distant = (
        f"cd {REMOTE_ROOT} && "
        "VENV=$(ls -d .venv.odoo18.0_python* 2>/dev/null | head -1) && "
        f"export {gw.ENV_SECRET}={shlex.quote(secret)} && "
        f'"$VENV/bin/python" odoo18.0/odoo/odoo-bin shell '
        f"-c config.conf -d {shlex.quote(spec.db_name)} "
        f"--no-http --log-level=error <<'FIN_DU_SCRIPT'\n{script}\nFIN_DU_SCRIPT"
    )
    res = ssh_run(todo, spec, distant, timeout=600, state=state)
    trouve = _parse_results(res.stdout)
    if not trouve.get("DEVICE_ID"):
        return False, (res.stderr or res.stdout).strip()[-800:]
    if trouve.get("SECRET_PRESENT") != "True":
        # Le secret manquait dans l'environnement du shell : la fiche existe
        # mais le téléphone se ferait refuser en 401. Mieux vaut échouer ici
        # que laisser découvrir la panne au moment de la démonstration.
        return False, t("sms_err_secret_absent")
    return True, f"{trouve['DEVICE_ID']} ({t('sms_provider_set')})"


# ----------------------------------------------------------------------
# Étape 4 — le téléphone
# ----------------------------------------------------------------------


def mobile_instructions(state) -> str:
    """Le pense-bête à recopier dans l'application."""
    from script.todo.sms import phone

    host = phone.host_lan_ip() if state.spec.transport == "wifi" else ""
    return gw.render_mobile_config(
        state.spec, ensure_secret(), state.vm_ip, host
    )


def adb_reverse(spec: DemoSpec):
    """Ouvre le renvoi USB vers la VM, si `adb` est là et un appareil aussi."""
    if not _which("adb"):
        return False, t("sms_err_no_adb")
    port = spec.odoo_port
    res = subprocess.run(
        ["adb", "reverse", f"tcp:{port}", f"tcp:{port}"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if res.returncode != 0:
        return False, (res.stderr or res.stdout).strip()[:300]
    return True, f"adb reverse tcp:{port} tcp:{port}"


def _which(binaire: str) -> str:
    from shutil import which

    return which(binaire) or ""


# ----------------------------------------------------------------------
# Étape 5 — l'essai
# ----------------------------------------------------------------------


def step_verify(todo, state, number: str):
    """Envoie un SMS d'essai et rapporte l'état de l'envoi."""
    spec = state.spec
    secret = ensure_secret()
    script = gw.render_test_script(number, spec)
    distant = (
        f"cd {REMOTE_ROOT} && "
        "VENV=$(ls -d .venv.odoo18.0_python* 2>/dev/null | head -1) && "
        f"export {gw.ENV_SECRET}={shlex.quote(secret)} && "
        f'"$VENV/bin/python" odoo18.0/odoo/odoo-bin shell '
        f"-c config.conf -d {shlex.quote(spec.db_name)} "
        f"--no-http --log-level=error <<'FIN_DU_SCRIPT'\n{script}\nFIN_DU_SCRIPT"
    )
    res = ssh_run(todo, spec, distant, timeout=600, state=state)
    trouve = _parse_results(res.stdout)
    etat = trouve.get("ETAT")
    if not etat:
        return False, (res.stderr or res.stdout).strip()[-800:]
    state.last_uuid = trouve.get("UUID", "")
    # `queued` n'est pas un échec : le téléphone n'a simplement pas encore
    # interrogé. C'est l'état NORMAL juste après l'envoi, et le confondre avec
    # une panne ferait conclure trop vite.
    return True, etat
