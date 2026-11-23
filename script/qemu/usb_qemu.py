#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Passer un périphérique USB de l'hôte libvirt à une VM, sans question.

Le CLI exécute les plans que bâtit qemu_usb.py ; il n'en double aucune
logique. Il ne pose AUCUNE question : ce qui demande un accord (arrêter le
service Stream Deck de l'hôte) se donne par --yes, et sans lui la commande
s'arrête en le disant, code 3.

    usb_qemu.py list [--json] [--uri URI]
    usb_qemu.py attach DOMAINE SÉLECTEUR [--uri URI] [--live] [--config]
                       [--yes]
    usb_qemu.py detach DOMAINE SÉLECTEUR [--uri URI] [--live] [--config]
                       [--yes]
    usb_qemu.py reattach --sysname 3-2
    usb_qemu.py install-autoreattach [--prefix DIR] [--vendor VID ...]
    usb_qemu.py remove-autoreattach [--prefix DIR] [--purge]
    usb_qemu.py mapping list|add|remove ...

SÉLECTEUR : « VID:PID » (0fd9:0080) ou « BUS.DEV » (3.5). La persistance
se choisit à chaque appel : --live, --config, ou les deux ; aucune n'est
implicite.

Privilège. Pour qemu:///system, un utilisateur non root essaie d'abord
virsh sans sudo — le groupe libvirt suffit —, et préfixe sinon « sudo -n »,
après un « sudo -v » quand un terminal peut répondre. Une URI distante
(qemu+ssh) ne prend jamais sudo : les droits sont ceux du compte distant,
et virsh lit le fichier XML localement pour l'envoyer par le RPC.

Rattachement automatique. install-autoreattach pose la règle udev,
l'unité gabarit systemd, et COPIE ce fichier avec qemu_usb.py dans
LIBEXEC_DIR : l'unité tourne en root, et n'exécute donc jamais un fichier
que l'utilisateur peut réécrire dans son checkout. La copie installée
charge qemu_usb.py depuis son propre répertoire ; depuis le dépôt, elle le
prend dans ../todo/. Codes de sortie : 0 succès ou rien à faire, 1 échec,
2 usage, 3 accord requis.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))

# Unité du service Stream Deck d'ERPLibre Home : la même chaîne que
# erplibre_home_service.UNIT_NAME, recopiée parce que la copie installée
# tourne hors du dépôt. Un test garde les deux égales.
DECK_SERVICE = "erplibre-home-streamdeck.service"

# Délais des commandes capturées : virsh attach-device attend QEMU, ssh peut
# attendre le réseau.
TIMEOUT_VIRSH = 120
TIMEOUT_SSH = 20

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_CONFIRM = 0, 1, 2, 3

# Interpréteur des relances root, le même que l'ExecStart de l'unité.
SYSTEM_PYTHON = "/usr/bin/python3"


def _load_lib():
    """qemu_usb.py chargé par CHEMIN : (module, chemin du fichier).

    Le répertoire de ce fichier passe en premier — c'est la copie installée
    dans LIBEXEC_DIR, lancée en « python3 -I », où ni le répertoire du
    script ni le dépôt ne sont dans sys.path. À défaut, ../todo/qemu_usb.py
    du dépôt ; la racine du dépôt est alors AJOUTÉE en fin de sys.path, ce
    qui donne à qemu_usb son t() et son DECK_VENDOR sans masquer un module
    de la bibliothèque standard.
    """
    path = os.path.join(HERE, "qemu_usb.py")
    if not os.path.isfile(path):
        path = os.path.join(os.path.dirname(HERE), "todo", "qemu_usb.py")
        root = os.path.dirname(os.path.dirname(HERE))
        if root not in sys.path:
            sys.path.append(root)
    spec = importlib.util.spec_from_file_location("erplibre_qemu_usb", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, path


QU, LIB_PATH = _load_lib()
t = QU.t


# ---------------------------------------------------------------------------
# Exécution


def run_cmd(argv, env=None, interactive=False, timeout=None):
    """Lance `argv` sans shell, rend un subprocess.CompletedProcess.

    Capturé par défaut, stdin fermé : un « sudo -n » ne peut alors rien
    demander. interactive=True laisse le terminal à la commande (sudo -v,
    relance sous sudo) et ne capture rien. Une commande absente rend 127,
    un délai dépassé 124 : l'appelant lit un code, jamais une exception.
    """
    try:
        if interactive:
            res = subprocess.run(list(argv), env=env, timeout=timeout)
            return subprocess.CompletedProcess(argv, res.returncode, "", "")
        return subprocess.run(
            list(argv),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as err:
        return subprocess.CompletedProcess(argv, 127, "", str(err))
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", "timeout")
    except OSError as err:
        return subprocess.CompletedProcess(argv, 126, "", str(err))


def c_env():
    """Environnement du processus avec LC_ALL=C : virsh traduit « running »
    et ses messages, et la sortie se lit alors en anglais. sudo garde
    LC_ALL dans sa liste env_keep par défaut."""
    return dict(os.environ, LC_ALL="C")


def is_local(uri) -> bool:
    """Vrai pour une URI sans hôte ni transport (qemu:///system)."""
    parts = urllib.parse.urlsplit(uri or QU.DEFAULT_URI)
    return "+" not in parts.scheme and not parts.netloc


def ssh_argv(uri):
    """Préfixe « ssh … hôte » qui joint l'hôte d'une URI qemu+ssh, ou None.

    BatchMode : aucune invite de mot de passe dans une commande sans
    terminal. Un hôte qui commence par « - » est refusé : ssh le lirait
    comme une option.
    """
    parts = urllib.parse.urlsplit(uri or "")
    host = parts.hostname or ""
    if parts.scheme != "qemu+ssh" or not host or host.startswith("-"):
        return None
    if parts.username:
        if parts.username.startswith("-"):
            return None
        host = f"{parts.username}@{host}"
    argv = ["ssh", "-o", "BatchMode=yes"]
    try:
        port = parts.port
    except ValueError:
        return None
    if port:
        argv += ["-p", str(port)]
    return argv + [host]


class Ctx:
    """Ce que partagent les sous-commandes : URI, exécuteur, privilège.

    run(argv, env=None, interactive=False, timeout=None) est injectable :
    les tests y branchent un faux hôte. Le préfixe sudo se décide au
    premier virsh, une fois par URI.
    """

    def __init__(
        self,
        uri=QU.DEFAULT_URI,
        run=None,
        dry_run=False,
        no_sudo=False,
        sysfs_root="/sys",
        out=None,
        err=None,
    ):
        self.uri = uri or QU.DEFAULT_URI
        self.run = run or run_cmd
        self.dry_run = dry_run
        self.no_sudo = no_sudo
        self.sysfs_root = sysfs_root
        self.out = out or (lambda text: print(text, flush=True))
        self.err = err or (
            lambda text: print(text, file=sys.stderr, flush=True)
        )
        self._sudo = {}

    def sudo(self) -> list:
        """[] ou ["sudo", "-n"] pour virsh sur self.uri.

        Comme qemu_privilege.needs_sudo : root n'en a jamais besoin, une
        URI distante ou de session non plus ; pour qemu:///system, l'essai
        de « virsh list » sans sudo tranche. virsh absent (127) rend [] :
        l'échec dira « command not found » plutôt qu'une invite de mot de
        passe. Avant le premier « sudo -n », un « sudo -v » interactif
        ouvre le ticket quand un terminal peut répondre.
        """
        if self.uri in self._sudo:
            return self._sudo[self.uri]
        prefix = []
        if (
            not self.no_sudo
            and os.geteuid() != 0
            and is_local(self.uri)
            and self.uri.startswith("qemu:///system")
        ):
            probe = self.run(
                QU.virsh_uri_argv(self.uri, "list", "--name"),
                env=c_env(),
                timeout=TIMEOUT_SSH,
            )
            if probe.returncode not in (0, 127):
                prefix = ["sudo", "-n"]
                if not self.dry_run and _isatty():
                    self.out(
                        t(
                            "sudo is needed: {uri} is open to root only"
                            " (the libvirt group would avoid it)."
                        ).format(uri=self.uri)
                    )
                    self.run(["sudo", "-v"], interactive=True)
        self._sudo[self.uri] = prefix
        return prefix

    def virsh(self, *args, timeout=TIMEOUT_VIRSH):
        """virsh sur self.uri, sous LC_ALL=C, avec sudo si besoin."""
        argv = self.sudo() + QU.virsh_uri_argv(self.uri, *args)
        return self.run(argv, env=c_env(), timeout=timeout)


def _isatty() -> bool:
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _first_line(res) -> str:
    text = (res.stderr or res.stdout or "").strip()
    return text.splitlines()[0] if text else f"exit {res.returncode}"


def domain_running(ctx, domain):
    """True / False selon « virsh domstate », None si virsh échoue (le
    message est déjà dit). Seul « running » compte : une VM en pause ne
    reçoit pas de périphérique."""
    res = ctx.virsh("domstate", domain)
    if res.returncode != 0:
        ctx.err(
            t("Cannot read the state of {domain}: {error}").format(
                domain=domain, error=_first_line(res)
            )
        )
        return None
    return res.stdout.strip() == "running"


def domain_state(ctx, domain, inactive=False):
    """usb_state() d'une vue du domaine, ou None si dumpxml échoue."""
    argv = QU.dumpxml_argv(ctx.uri, domain, inactive=inactive)
    res = ctx.virsh(*argv[3:])
    if res.returncode != 0:
        ctx.err(
            t("Cannot read the definition of {domain}: {error}").format(
                domain=domain, error=_first_line(res)
            )
        )
        return None
    return QU.usb_state(res.stdout)


def execute(ctx, steps) -> int:
    """Exécute un plan de qemu_usb. Rend le nombre d'étapes en échec.

    Chaque étape lancée écrit son XML dans un fichier temporaire, propre à
    l'étape et effacé après elle. Une étape en échec n'arrête pas les
    suivantes : les vues live et config sont indépendantes, et un
    détachement d'adresse morte raté n'empêche pas l'attachement.
    --dry-run montre la commande et le XML, sans rien lancer.
    """
    failures = 0
    for step in steps:
        if "skip" in step:
            ctx.out(f"- {step['what']}: {step['skip']}")
            continue
        ctx.out(f"> {step['what']}")
        if ctx.dry_run:
            ctx.out("  $ " + shlex.join(ctx.sudo() + step["argv"]))
            for line in step["xml"].rstrip("\n").splitlines():
                ctx.out("    " + line)
            continue
        fd, path = tempfile.mkstemp(prefix="erplibre-usb-", suffix=".xml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(step["xml"])
            argv = ctx.sudo() + QU.bind_xml(step["argv"], path)
            ctx.out("  $ " + shlex.join(argv))
            res = ctx.run(argv, env=c_env(), timeout=TIMEOUT_VIRSH)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        if res.returncode != 0:
            failures += 1
            ctx.err("  " + t("FAILED: {error}").format(error=_first_line(res)))
        else:
            ctx.out("  OK")
    return failures


# ---------------------------------------------------------------------------
# Périphériques


def parse_nodedev(text):
    """Un périphérique lu dans « virsh nodedev-dumpxml », à la forme de
    qemu_usb.read_usb_device, ou None s'il n'est pas un usb_device.

    libvirt ne rend ni le numéro de série ni la classe : serial et
    device_class restent vides, et seul le vendeur 1d6b écarte les
    concentrateurs racines. Le nom sysfs est le dernier segment de <path>.
    """
    try:
        root = ET.fromstring(text or "")
    except ET.ParseError:
        return None
    cap = root.find("capability[@type='usb_device']")
    if cap is None:
        return None
    vendor, product = cap.find("vendor"), cap.find("product")
    try:
        busnum = int(cap.findtext("bus", "").strip())
        devnum = int(cap.findtext("device", "").strip())
    except ValueError:
        return None
    vid = QU.norm_hex(vendor.get("id")) if vendor is not None else ""
    pid = QU.norm_hex(product.get("id")) if product is not None else ""
    if not vid or not pid:
        return None
    return {
        "sysname": os.path.basename(root.findtext("path", "").strip()),
        "busnum": busnum,
        "devnum": devnum,
        "vid": vid,
        "pid": pid,
        "product": (product.text or "").strip(),
        "manufacturer": (vendor.text or "").strip(),
        "serial": "",
        "device_class": "",
        "is_deck": vid == QU.DECK_VENDOR,
    }


def host_devices(ctx):
    """Périphériques passables de l'hôte LIBVIRT, decks en tête, ou None.

    URI locale : sysfs, qui donne aussi le numéro de série. URI distante :
    « virsh nodedev-list --cap usb_device » puis un nodedev-dumpxml par
    périphérique, par la même connexion que l'attachement — le sysfs local
    serait celui du mauvais hôte.
    """
    if is_local(ctx.uri):
        return QU.host_usb_devices(ctx.sysfs_root)
    res = ctx.virsh("nodedev-list", "--cap", "usb_device")
    if res.returncode != 0:
        ctx.err(
            t("Cannot list the USB devices of {uri}: {error}").format(
                uri=ctx.uri, error=_first_line(res)
            )
        )
        return None
    devs = []
    for name in res.stdout.split():
        one = ctx.virsh("nodedev-dumpxml", name)
        dev = parse_nodedev(one.stdout) if one.returncode == 0 else None
        if dev and QU.is_usable(dev):
            devs.append(dev)
    return QU.sort_devices(devs)


# ---------------------------------------------------------------------------
# Service Stream Deck de l'hôte


def deck_service_argv(uri, *verb):
    """argv de « systemctl --user VERBE… DECK_SERVICE » sur l'hôte libvirt,
    ou None quand ce compte ne se joint pas.

    Le service est une unité UTILISATEUR. En local non root : le
    gestionnaire du compte courant. En root : celui de SUDO_USER, par
    --machine USER@.host ; root sans SUDO_USER n'a pas de session à
    viser. URI qemu+ssh : le compte distant, par ssh.
    """
    base = ["systemctl", "--user"]
    if is_local(uri):
        if os.geteuid() == 0:
            user = os.environ.get("SUDO_USER", "")
            if not user or user == "root" or user.startswith("-"):
                return None
            base += ["--machine", f"{user}@.host"]
        return base + list(verb) + [DECK_SERVICE]
    ssh = ssh_argv(uri)
    if not ssh:
        return None
    return ssh + base + list(verb) + [DECK_SERVICE]


def deck_service_state(ctx):
    """{"loaded": bool, "active": bool} du service deck de l'hôte, ou None
    quand on ne sait pas le lire (le service est alors réputé absent)."""
    argv = deck_service_argv(
        ctx.uri, "show", "--property=LoadState,ActiveState"
    )
    if not argv:
        return None
    res = ctx.run(argv, timeout=TIMEOUT_SSH)
    if res.returncode != 0:
        return None
    props = dict(
        line.split("=", 1) for line in res.stdout.splitlines() if "=" in line
    )
    return {
        "loaded": props.get("LoadState") == "loaded",
        "active": props.get("ActiveState") in ("active", "activating"),
    }


def deck_service_do(ctx, verb) -> bool:
    """Lance systemctl --user VERBE sur le service deck ; vrai si réussi."""
    argv = deck_service_argv(ctx.uri, verb)
    ctx.out("  $ " + shlex.join(argv))
    if ctx.dry_run:
        return True
    res = ctx.run(argv, timeout=TIMEOUT_SSH)
    if res.returncode != 0:
        ctx.err("  " + t("FAILED: {error}").format(error=_first_line(res)))
        return False
    return True


# ---------------------------------------------------------------------------
# attach / detach


def _check_domain(ctx, domain) -> bool:
    """Refuse un nom de domaine qui commence par « - » : virsh le lirait
    comme une option."""
    if not domain or domain.startswith("-"):
        ctx.err(t("Invalid domain name: {domain}").format(domain=domain))
        return False
    return True


def cmd_usb(ctx, args, action) -> int:
    """attach / detach : résout le sélecteur, lit l'état, exécute le plan.

    Le sélecteur se résout parmi les périphériques de l'hôte libvirt.
    want_for() épingle l'adresse seulement quand deux périphériques
    identiques sont branchés. Un VID:PID absent de l'hôte reste possible
    pour un détachement, et pour un attachement --config seul (la VM le
    prendra à son démarrage, startupPolicy optionnel).

    Deck et service deck de l'hôte actif : un attachement live le prend
    au service, qui ne s'arrête qu'avec --yes (sinon code 3). Après un
    détachement live, --yes relance le service ; sans lui, la commande de
    relance est affichée.
    """
    if not (args.live or args.config):
        ctx.err(t("Choose --live, --config, or both."))
        return EXIT_USAGE
    if not _check_domain(ctx, args.domain):
        return EXIT_USAGE
    sel = QU.parse_selector(args.selector)
    if not sel:
        ctx.err(
            t(
                "Unreadable selector {selector}: expected VID:PID or BUS.DEV."
            ).format(selector=args.selector)
        )
        return EXIT_USAGE
    devs = host_devices(ctx)
    if devs is None:
        return EXIT_FAIL
    found = QU.find_devices(devs, **sel)
    if len(found) > 1:
        ctx.err(
            t(
                "{selector} matches several devices; choose one by BUS.DEV:"
            ).format(selector=args.selector)
        )
        for dev in found:
            ctx.err("  " + QU.device_line(dev))
        return EXIT_USAGE
    if found:
        want = QU.want_for(found[0], devs)
        if action == "detach" and "bus" in sel:
            # Un BUS.DEV explicite garde son adresse : un <hostdev> défini
            # par adresse seule (virt-manager, deux decks identiques) n'a
            # pas de VID:PID, et ne se retrouve que par elle.
            want["bus"], want["dev"] = sel["bus"], sel["dev"]
    elif "vid" not in sel:
        ctx.err(
            t("No USB device at {selector} on the host.").format(
                selector=args.selector
            )
        )
        return EXIT_FAIL
    elif action == "attach" and args.live:
        ctx.err(
            t(
                "{device} is not plugged into the host: only --config can"
                " declare it ahead."
            ).format(device=QU.device_id(sel["vid"], sel["pid"]))
        )
        return EXIT_FAIL
    else:
        want = {"vid": sel["vid"], "pid": sel["pid"], "bus": None, "dev": None}
    want["action"] = action

    running = domain_running(ctx, args.domain)
    if running is None:
        return EXIT_FAIL
    live_state = config_state = None
    if args.live and running:
        live_state = domain_state(ctx, args.domain)
        if live_state is None:
            return EXIT_FAIL
    if args.config:
        config_state = domain_state(ctx, args.domain, inactive=True)
        if config_state is None:
            return EXIT_FAIL
    steps = QU.usb_plan(
        live_state,
        config_state,
        want,
        args.live,
        args.config,
        running,
        args.domain,
        ctx.uri,
    )
    is_deck = want["vid"] == QU.DECK_VENDOR
    live_runs = any(s["view"] == "live" and "argv" in s for s in steps)

    if action == "attach" and is_deck:
        service = deck_service_state(ctx)
        if service and service["active"]:
            if live_runs:
                if not args.yes:
                    ctx.err(
                        t(
                            "The ERPLibre Home Stream Deck service runs on"
                            " the libvirt host and holds the deck. Run"
                            " again with --yes to stop it during the"
                            " passthrough."
                        )
                    )
                    return EXIT_CONFIRM
                ctx.out(t("Stopping the host Stream Deck service"))
                if not deck_service_do(ctx, "stop"):
                    return EXIT_FAIL
            else:
                ctx.out(
                    t(
                        "Note: the host Stream Deck service runs; the VM"
                        " takes the deck from it at its next start."
                    )
                )

    failures = execute(ctx, steps)

    if action == "detach" and is_deck and not failures:
        if live_runs or not running:
            service = deck_service_state(ctx)
            if service and service["loaded"] and not service["active"]:
                if args.yes:
                    ctx.out(t("Restarting the host Stream Deck service"))
                    if not deck_service_do(ctx, "start"):
                        return EXIT_FAIL
                else:
                    ctx.out(
                        t(
                            "The host Stream Deck service is stopped;"
                            " restart it with:"
                        )
                    )
                    ctx.out(
                        "  " + shlex.join(deck_service_argv(ctx.uri, "start"))
                    )
    return EXIT_FAIL if failures else EXIT_OK


# ---------------------------------------------------------------------------
# list


def cmd_list(ctx, args) -> int:
    devs = host_devices(ctx)
    if devs is None:
        return EXIT_FAIL
    if args.json:
        ctx.out(json.dumps(devs, indent=2, sort_keys=True))
        return EXIT_OK
    if not devs:
        ctx.out(t("No USB device found on the host."))
        return EXIT_OK
    for dev in devs:
        ctx.out(("* " if dev.get("is_deck") else "  ") + QU.device_line(dev))
    return EXIT_OK


# ---------------------------------------------------------------------------
# Fichiers système


def system_paths(prefix=""):
    """Chemins posés par install-autoreattach, sous `prefix` s'il est
    donné (arborescence de test ou de préparation)."""

    def under(path):
        return os.path.join(prefix, path.lstrip("/")) if prefix else path

    return {
        "rule": under(QU.UDEV_RULE_PATH),
        "unit": under(QU.UNIT_PATH),
        "cli": under(QU.LIBEXEC_CLI),
        "lib": under(QU.LIBEXEC_LIB),
        "libexec": under(QU.LIBEXEC_DIR).rstrip("/"),
        "mapping": under(QU.MAPPING),
    }


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def write_file(ctx, path, content, mode) -> bool:
    """Écrit `content` dans `path` avec les droits `mode`, sauf s'il y est
    déjà à l'identique. Rend vrai quand le fichier change.

    Écriture atomique : fichier temporaire du même répertoire, puis
    os.replace ; udev ou systemd ne lisent jamais un fichier à moitié
    écrit. Les répertoires manquants sont créés en 0755.
    """
    try:
        same_mode = (os.stat(path).st_mode & 0o7777) == mode
    except OSError:
        same_mode = False
    if _read(path) == content and same_mode:
        ctx.out("  = " + path)
        return False
    ctx.out("  + " + path)
    if ctx.dry_run:
        return True
    folder = os.path.dirname(path)
    os.makedirs(folder, mode=0o755, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".erplibre-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True


def remove_file(ctx, path) -> bool:
    """Retire `path` s'il existe ; rend vrai quand il a été retiré."""
    if not os.path.lexists(path):
        return False
    ctx.out("  - " + path)
    if not ctx.dry_run:
        os.unlink(path)
    return True


def reload_system(ctx) -> int:
    """systemctl daemon-reload puis udevadm control --reload-rules. Rend le
    nombre d'échecs."""
    failures = 0
    for argv in (
        ["systemctl", "daemon-reload"],
        ["udevadm", "control", "--reload-rules"],
    ):
        ctx.out("  $ " + shlex.join(argv))
        if ctx.dry_run:
            continue
        res = ctx.run(argv, timeout=TIMEOUT_VIRSH)
        if res.returncode != 0:
            failures += 1
            ctx.err("  " + t("FAILED: {error}").format(error=_first_line(res)))
    return failures


def load_mapping(path):
    """Entrées du fichier de correspondance ; fichier absent -> [].
    ValueError pour un JSON illisible."""
    return QU.mapping_loads(_read(path) or "")


def rule_vendors(entries, extra=()):
    """Vendeurs de la règle udev : le deck, ceux de la correspondance, et
    ceux demandés."""
    vids = {QU.DECK_VENDOR}
    vids |= {e["vid"] for e in entries}
    vids |= {QU.norm_hex(v) for v in extra if QU.norm_hex(v)}
    return sorted(vids)


def needs_root(args) -> bool:
    """Vrai quand l'opération écrit dans le système sans en avoir le droit :
    non root, sans --prefix, et cible non inscriptible."""
    if os.geteuid() == 0 or getattr(args, "prefix", ""):
        return False
    targets = getattr(args, "_targets", ())
    for path in targets:
        probe = path
        while probe and not os.path.exists(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        if not os.access(probe, os.W_OK):
            return True
    return False


def root_python() -> str:
    """L'interpréteur que root lance : SYSTEM_PYTHON, celui de l'unité, et
    non sys.executable, qui peut être le python d'un venv — un binaire et
    des fichiers .pth que l'utilisateur réécrit. sys.executable ne sert
    que sur un système sans SYSTEM_PYTHON."""
    if os.access(SYSTEM_PYTHON, os.X_OK):
        return SYSTEM_PYTHON
    return sys.executable or SYSTEM_PYTHON


def reexec_root(ctx, raw_argv) -> int:
    """Relance cette même commande sous sudo, par root_python().

    -I écarte les variables PYTHON*, le site de l'utilisateur et le
    répertoire du script ; -S écarte aussi les site-packages et leurs
    .pth, que -I laisse à un venv ; -B n'écrit aucun __pycache__ root
    dans le checkout. Il ne reste que la bibliothèque standard, et
    qemu_usb.py se charge par chemin. « sudo -n » sans terminal pour
    répondre."""
    sudo = ["sudo"] if _isatty() else ["sudo", "-n"]
    argv = sudo + [
        root_python(),
        "-I",
        "-S",
        "-B",
        os.path.abspath(__file__),
        *raw_argv,
    ]
    ctx.out(t("Root is needed; running:"))
    ctx.out("  $ " + shlex.join(argv))
    if ctx.dry_run:
        return EXIT_OK
    return ctx.run(argv, interactive=True).returncode


# ---------------------------------------------------------------------------
# install-autoreattach / remove-autoreattach


def cmd_install(ctx, args) -> int:
    """Pose règle, unité, copies du CLI et de qemu_usb.py, et le fichier de
    correspondance s'il manque ; recharge systemd et udev quand un fichier
    a changé. Sans --prefix seulement : une arborescence préparée n'est
    pas le système qui tourne."""
    paths = system_paths(args.prefix)
    try:
        entries = load_mapping(paths["mapping"])
    except ValueError as err:
        ctx.err(
            t("Unreadable mapping {path}: {error}").format(
                path=paths["mapping"], error=err
            )
        )
        return EXIT_FAIL
    with open(os.path.abspath(__file__), encoding="utf-8") as fh:
        cli_text = fh.read()
    with open(LIB_PATH, encoding="utf-8") as fh:
        lib_text = fh.read()
    ctx.out(t("Installing USB auto-reattach"))
    changed = False
    changed |= write_file(
        ctx,
        paths["rule"],
        QU.udev_rule_text(rule_vendors(entries, args.vendor or ())),
        0o644,
    )
    changed |= write_file(ctx, paths["unit"], QU.unit_text(), 0o644)
    changed |= write_file(ctx, paths["cli"], cli_text, 0o755)
    changed |= write_file(ctx, paths["lib"], lib_text, 0o644)
    if not os.path.exists(paths["mapping"]):
        changed |= write_file(
            ctx, paths["mapping"], QU.mapping_dumps([]), 0o644
        )
    failures = 0
    if changed and not args.prefix:
        failures = reload_system(ctx)
    ctx.out(t("Test it by replugging the device, then read:"))
    ctx.out("  journalctl -u 'erplibre-usb-reattach@*'")
    return EXIT_FAIL if failures else EXIT_OK


def cmd_remove(ctx, args) -> int:
    """Retire règle, unité et copies ; le fichier de correspondance reste,
    sauf --purge : il porte des choix de l'utilisateur."""
    paths = system_paths(args.prefix)
    ctx.out(t("Removing USB auto-reattach"))
    changed = False
    for key in ("rule", "unit", "cli", "lib"):
        changed |= remove_file(ctx, paths[key])
    if args.purge:
        remove_file(ctx, paths["mapping"])
    if not ctx.dry_run:
        # La copie installée charge qemu_usb.py par chemin : lancée sans
        # -B, Python y écrit __pycache__, qui bloquerait le rmdir. Seuls
        # les dossiers vidés partent ; celui de la correspondance n'est
        # vidé que par --purge, et garde tout autre fichier qu'on y aurait
        # mis.
        shutil.rmtree(
            os.path.join(paths["libexec"], "__pycache__"), ignore_errors=True
        )
        dirs = [paths["libexec"]]
        if args.purge:
            dirs.append(os.path.dirname(paths["mapping"]))
        for path in dirs:
            try:
                os.rmdir(path)
            except OSError:
                pass
    if changed and not args.prefix:
        return EXIT_FAIL if reload_system(ctx) else EXIT_OK
    return EXIT_OK


# ---------------------------------------------------------------------------
# mapping


def mapping_path(args):
    return args.mapping or system_paths(args.prefix)["mapping"]


def refresh_rule(ctx, args, entries) -> int:
    """Réécrit la règle udev déjà posée quand la correspondance ajoute un
    vendeur, et recharge udev hors --prefix. Rien quand la règle n'est
    pas posée : install-autoreattach la créera. Rien non plus pour un
    fichier désigné par --mapping, étranger à la règle posée."""
    rule = system_paths(args.prefix)["rule"]
    if args.mapping or not os.path.exists(rule):
        return EXIT_OK
    if not write_file(
        ctx, rule, QU.udev_rule_text(rule_vendors(entries)), 0o644
    ):
        return EXIT_OK
    if args.prefix or ctx.dry_run:
        return EXIT_OK
    res = ctx.run(["udevadm", "control", "--reload-rules"])
    return EXIT_OK if res.returncode == 0 else EXIT_FAIL


def cmd_mapping(ctx, args) -> int:
    """list / add / remove sur le fichier de correspondance.

    add : SÉLECTEUR VID:PID, ou BUS.DEV résolu sur l'hôte ; dans ce cas,
    deux périphériques identiques branchés font retenir le numéro de série,
    qui seul les départage au rebranchement.
    """
    path = mapping_path(args)
    try:
        entries = load_mapping(path)
    except ValueError as err:
        ctx.err(
            t("Unreadable mapping {path}: {error}").format(
                path=path, error=err
            )
        )
        return EXIT_FAIL
    if args.mapping_cmd == "list":
        if args.json:
            ctx.out(json.dumps(entries, indent=2, sort_keys=True))
        elif not entries:
            ctx.out(t("No device mapped to a VM."))
        for e in [] if args.json else entries:
            line = f"{QU.device_id(e['vid'], e['pid'])} -> {e['domain']}"
            if e.get("serial"):
                line += f"  [{e['serial']}]"
            if e.get("uri"):
                line += f"  ({e['uri']})"
            ctx.out(line)
        return EXIT_OK

    sel = QU.parse_selector(args.selector)
    if not sel:
        ctx.err(
            t(
                "Unreadable selector {selector}: expected VID:PID or BUS.DEV."
            ).format(selector=args.selector)
        )
        return EXIT_USAGE
    serial = args.serial
    if "vid" not in sel:
        devs = QU.host_usb_devices(ctx.sysfs_root)
        found = QU.find_devices(devs, **sel)
        if not found:
            ctx.err(
                t("No USB device at {selector} on the host.").format(
                    selector=args.selector
                )
            )
            return EXIT_FAIL
        dev = found[0]
        sel = {"vid": dev["vid"], "pid": dev["pid"]}
        if serial is None and QU.ambiguous(devs, dev["vid"], dev["pid"]):
            serial = dev["serial"] or None

    if args.mapping_cmd == "add":
        if not _check_domain(ctx, args.domain):
            return EXIT_USAGE
        entry = {"vid": sel["vid"], "pid": sel["pid"], "domain": args.domain}
        if serial:
            entry["serial"] = serial
        if args.uri and args.uri != QU.DEFAULT_URI:
            entry["uri"] = args.uri
        entries = QU.mapping_set(entries, entry)
    else:
        before = len(entries)
        entries = QU.mapping_remove(
            entries, sel["vid"], sel["pid"], serial, args.domain
        )
        if len(entries) == before:
            ctx.out(t("No matching entry."))
            return EXIT_OK
    write_file(ctx, path, QU.mapping_dumps(entries), 0o644)
    return refresh_rule(ctx, args, entries)


# ---------------------------------------------------------------------------
# reattach


def cmd_reattach(ctx, args) -> int:
    """Lancé par erplibre-usb-reattach@<nom sysfs>.service, en root.

    Lit le périphérique sous sysfs, cherche sa VM dans la correspondance,
    et exécute reattach_plan : détacher les <hostdev> d'adresse morte,
    attacher en live à la nouvelle adresse. Une ligne par décision, pour
    le journal. Rien à faire — périphérique reparti, aucune VM associée,
    VM arrêtée — rend 0 : l'unité ne doit pas finir en échec pour un
    périphérique qui ne concerne aucune VM.
    """
    name = args.sysname
    if not QU.valid_sysname(name):
        ctx.err(t("Invalid sysfs name: {name}").format(name=name))
        return EXIT_USAGE
    dev = QU.read_usb_device(name, ctx.sysfs_root)
    if dev is None:
        ctx.out(t("{name}: device gone, nothing to do.").format(name=name))
        return EXIT_OK
    path = mapping_path(args)
    try:
        entries = load_mapping(path)
    except ValueError as err:
        ctx.err(
            t("Unreadable mapping {path}: {error}").format(
                path=path, error=err
            )
        )
        return EXIT_FAIL
    entry = QU.mapping_match(entries, dev)
    label = f"{name} {QU.device_line(dev)}"
    if not entry:
        ctx.out(t("{device}: mapped to no VM.").format(device=label))
        return EXIT_OK
    ctx.uri = entry.get("uri") or QU.DEFAULT_URI
    ctx.out(f"{label} -> {entry['domain']}")
    running = domain_running(ctx, entry["domain"])
    if running is None:
        return EXIT_FAIL
    live_state = None
    if running:
        live_state = domain_state(ctx, entry["domain"])
        if live_state is None:
            return EXIT_FAIL
    steps = QU.reattach_plan(
        dev,
        entry,
        running,
        live_state,
        QU.host_usb_devices(ctx.sysfs_root),
    )
    return EXIT_FAIL if execute(ctx, steps) else EXIT_OK


# ---------------------------------------------------------------------------
# Ligne de commande


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the commands and the XML, change nothing.",
    )
    common.add_argument(
        "--no-sudo",
        action="store_true",
        help="Never add sudo (libvirt group member).",
    )
    # Racine sysfs : un faux arbre pour les tests.
    common.add_argument("--sysfs-root", default="/sys", help=argparse.SUPPRESS)

    p = argparse.ArgumentParser(
        prog="usb_qemu.py",
        description="Pass host USB devices (Stream Deck first) to libvirt"
        " VMs.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", parents=[common], help="List host devices.")
    s.add_argument("--json", action="store_true")
    s.add_argument("--uri", default=QU.DEFAULT_URI)

    for name in ("attach", "detach"):
        s = sub.add_parser(name, parents=[common], help=f"{name} a device.")
        s.add_argument("domain")
        s.add_argument("selector", help="VID:PID or BUS.DEV")
        s.add_argument("--uri", default=QU.DEFAULT_URI)
        s.add_argument("--live", action="store_true")
        s.add_argument("--config", action="store_true")
        s.add_argument(
            "--yes",
            action="store_true",
            help="Stop (attach) or restart (detach) the host Stream Deck"
            " service.",
        )

    s = sub.add_parser(
        "reattach", parents=[common], help="udev/systemd replug handler."
    )
    s.add_argument("--sysname", required=True)
    s.add_argument("--mapping", default="")
    s.add_argument("--prefix", default="")

    s = sub.add_parser("install-autoreattach", parents=[common])
    s.add_argument("--prefix", default="")
    s.add_argument("--vendor", action="append", default=[])

    s = sub.add_parser("remove-autoreattach", parents=[common])
    s.add_argument("--prefix", default="")
    s.add_argument("--purge", action="store_true")

    s = sub.add_parser("mapping", help="Replug mapping file.")
    msub = s.add_subparsers(dest="mapping_cmd", required=True)
    m = msub.add_parser("list", parents=[common])
    m.add_argument("--json", action="store_true")
    m = msub.add_parser("add", parents=[common])
    m.add_argument("domain")
    m.add_argument("selector", help="VID:PID or BUS.DEV")
    m.add_argument("--serial", default=None)
    m.add_argument("--uri", default="")
    m = msub.add_parser("remove", parents=[common])
    m.add_argument("selector", help="VID:PID or BUS.DEV")
    m.add_argument("--domain", default=None)
    m.add_argument("--serial", default=None)
    for m in msub.choices.values():
        m.add_argument("--mapping", default="")
        m.add_argument("--prefix", default="")
    return p


def main(argv=None, run=None, out=None, err=None) -> int:
    """Point d'entrée ; rend le code de sortie. run / out / err : exécuteur
    et sorties injectables (tests)."""
    raw = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw)
    ctx = Ctx(
        uri=getattr(args, "uri", "") or QU.DEFAULT_URI,
        run=run,
        dry_run=args.dry_run,
        no_sudo=args.no_sudo,
        sysfs_root=args.sysfs_root,
        out=out,
        err=err,
    )
    if args.cmd == "list":
        return cmd_list(ctx, args)
    if args.cmd in ("attach", "detach"):
        return cmd_usb(ctx, args, args.cmd)
    if args.cmd == "reattach":
        return cmd_reattach(ctx, args)

    # Les sous-commandes qui écrivent dans /etc et /usr/local se relancent
    # sous sudo plutôt que d'échouer à mi-chemin sur un fichier refusé.
    # --dry-run n'écrit rien et reste donc sous le compte courant.
    if args.cmd in ("install-autoreattach", "remove-autoreattach"):
        args._targets = () if args.prefix else ("/",)
    elif args.mapping_cmd != "list":
        args._targets = (mapping_path(args),)
    else:
        args._targets = ()
    if args._targets and not args.dry_run and needs_root(args):
        return reexec_root(ctx, raw)
    if args.cmd == "install-autoreattach":
        return cmd_install(ctx, args)
    if args.cmd == "remove-autoreattach":
        return cmd_remove(ctx, args)
    return cmd_mapping(ctx, args)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
