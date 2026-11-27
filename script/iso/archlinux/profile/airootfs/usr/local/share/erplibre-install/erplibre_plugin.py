#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Greffon ERPLibre pour archinstall (« archinstall --plugin <ce fichier> »).

archinstall charge ce fichier par son chemin, lit __archinstall__version__
puis instancie Plugin(). Ses accroches remplacent ce qu'archinstall ne sait
pas faire sur une racine LVM-sur-LUKS montée à l'avance :

- on_pacstrap : ajoute au tout premier pacstrap (celui qui porte « base »)
  les outils dont l'initramfs a besoin — lvm2 et cryptsetup, e2fsprogs ou
  xfsprogs, dosfstools —, présents avant on_mkinitcpio ;
- on_mkinitcpio : HOOKS systemd (sd-vconsole, sd-encrypt, lvm2),
  vconsole.conf, presets (image de secours ou UKI), puis « mkinitcpio
  -P » ; rend True, sans quoi archinstall réécrirait les HOOKS en
  udev/encrypt ;
- on_add_bootloader : systemd-boot (loader.conf, une entrée et une entrée
  de secours par noyau, ou des UKI) ou GRUB ; rend True ;
- on_install : locales, horloge matérielle, zram, e2scrub, crypttab du
  volume secret, makepkg natif, premier démarrage, verrou de root
  (politique « lock »), et les réglages résolus copiés dans
  /var/lib/erplibre-install ;
- on_user_created : le shell du compte ;
- on_genfstab : la ligne de swap si genfstab ne l'a pas écrite.

Ordre dans archinstall 4.5 : minimal_installation (pacstrap base,
on_mkinitcpio, on_install), puis le chargeur, les comptes, le profil
GNOME, les paquets, les services, custom_commands, genfstab. on_install
passe donc AVANT la création des comptes et des paquets supplémentaires :
ce qui dépend d'eux va dans on_user_created ou installe son paquet
lui-même.

zram appartient au greffon : la configuration archinstall porte « swap »
désactivé, car setup_swap() passe après on_install et réécrirait
zram-generator.conf avec le seul algorithme.

Tout le reste vient d'un fichier d'état JSON écrit par l'orchestrateur
(variable ERPLIBRE_PLUGIN_STATE) : réglages résolus, faits, UUID lus après
l'étape disque, clavier. Il ne porte aucun secret. Chaque accroche écrit
ce qu'elle a fait dans le journal et son verdict dans status_path ; une
accroche qui échoue lève, ce qui arrête archinstall.

Les constructeurs de texte et d'argv sont des fonctions pures, testées sans
archinstall. Plugin() refuse de démarrer (SystemExit, qu'archinstall ne
rattrape pas au chargement) si la version d'archinstall n'est pas
SUPPORTED_ARCHINSTALL ou si le fichier d'état manque.
"""

import json
import os
import re
import shlex
import time

# Lu par archinstall au chargement ; il compare ce nombre à sa propre
# version majeure.mineure et refuse un greffon plus ancien.
__archinstall__version__ = 4.5

# La version d'archinstall dont les accroches et leur ordre ont été lus
# dans les sources ; toute autre est refusée.
SUPPORTED_ARCHINSTALL = (4, 5)

STATE_ENV = "ERPLIBRE_PLUGIN_STATE"
DEFAULT_STATE = "/run/erplibre-install/plugin-state.json"

LUKS_MAPPER = "cryptlvm"
SECRET_MAPPER = "erplibre-secret"
ENTRY_PREFIX = "erplibre"
TARGET_STATE_DIR = "var/lib/erplibre-install"

# Modules de sécurité du noyau quand AppArmor est actif : la liste par
# défaut du noyau Arch, apparmor ajouté avant bpf.
APPARMOR_LSM = "landlock,lockdown,yama,integrity,apparmor,bpf"

# Réglages mémoire conseillés pour une swap en zram : la swap compressée
# est bien plus rapide que le disque, d'où une swappiness au-dessus de 100.
ZRAM_SYSCTL = (
    ("vm.swappiness", 180),
    ("vm.watermark_boost_factor", 0),
    ("vm.watermark_scale_factor", 125),
    ("vm.page-cluster", 0),
)

SHELL_PATHS = {
    "bash": "/bin/bash",
    "zsh": "/usr/bin/zsh",
    "fish": "/usr/bin/fish",
}
SHELL_PACKAGES = {"zsh": "zsh", "fish": "fish"}

AUR_HELPERS = {"yay": "yay-bin", "paru": "paru-bin"}
AUR_URL = "https://aur.archlinux.org/{pkg}.git"
FIRSTBOOT_UNIT = "erplibre-firstboot.service"
FIRSTBOOT_SCRIPT = "/usr/local/sbin/erplibre-firstboot"
FIRSTBOOT_SUDOERS = "/etc/sudoers.d/91-erplibre-firstboot"
FIRSTBOOT_DONE = "/var/lib/erplibre-install/firstboot.done"


# Version


def parse_version(texte):
    """(majeure, mineure) d'une version « 4.5 », « 4.5.1 » ou « 4.5-1 » ;
    None si elle ne se lit pas."""
    m = re.match(r"^\s*(\d+)\.(\d+)", str(texte or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def version_ok(found, supported=SUPPORTED_ARCHINSTALL):
    """Vrai si la version `found` a la majeure.mineure `supported`."""
    return parse_version(found) == tuple(supported)


def archinstall_version():
    """La version du paquet archinstall installé, ou None."""
    try:
        from importlib.metadata import version

        return version("archinstall")
    except Exception:
        return None


# Constructeurs purs


def _get(settings, path, default=None):
    courant = settings
    for morceau in path.split("."):
        if not isinstance(courant, dict) or morceau not in courant:
            return default
        courant = courant[morceau]
    return courant


def is_luks(settings):
    return _get(settings, "disk.layout") == "lvm_on_luks"


def keep_kms(settings):
    """Le hook kms charge le pilote graphique libre dans l'initramfs ; il
    est retiré pour le pilote NVIDIA (modules ouverts), qui ne doit pas
    voir nouveau prendre la carte avant lui."""
    return _get(settings, "gpu.driver") != "nvidia-open"


def mkinitcpio_hooks(settings):
    """Les HOOKS de l'initramfs systemd : sd-vconsole pour taper la phrase
    LUKS avec la disposition de la console, sd-encrypt puis lvm2 devant
    filesystems quand la racine est un LV dans LUKS."""
    hooks = ["base", "systemd", "autodetect", "microcode", "modconf"]
    if keep_kms(settings):
        hooks.append("kms")
    hooks += ["keyboard", "sd-vconsole", "block"]
    if is_luks(settings):
        hooks += ["sd-encrypt", "lvm2"]
    hooks += ["filesystems", "fsck"]
    return hooks


def edit_mkinitcpio_conf(text, hooks):
    """mkinitcpio.conf avec sa ligne HOOKS= active remplacée par `hooks`,
    ou ajoutée à la fin si le fichier n'en a pas."""
    ligne = f"HOOKS=({' '.join(hooks)})"
    nouveau, n = re.subn(r"(?m)^HOOKS=.*$", ligne, text)
    if n:
        return nouveau
    return text.rstrip("\n") + "\n" + ligne + "\n"


def vconsole_conf(keymap, text=""):
    """vconsole.conf `text` dont la ligne KEYMAP= devient `keymap`,
    ajoutée à la fin s'il n'en a pas. Les autres lignes restent : FONT=
    qu'archinstall a posée, et XKBLAYOUT=/XKBMODEL=… que localectl
    set-keymap y écrit et que systemd préfère pour la disposition X11."""
    ligne = f"KEYMAP={keymap}"
    nouveau, n = re.subn(r"(?m)^KEYMAP=.*$", ligne, text, count=1)
    if n:
        return nouveau
    return (text.rstrip("\n") + "\n" if text.strip() else "") + ligne + "\n"


def kernel_options(settings, disk):
    """Les options du noyau, dans l'ordre où elles s'écrivent.

    LUKS : rd.luks.name=<UUID>=cryptlvm (sd-encrypt ouvre l'en-tête par son
    UUID ; les discards persistants viennent de l'en-tête lui-même),
    root=/dev/<vg>/root, resume= quand l'hibernation est retenue et qu'un
    volume de swap existe. Sans LUKS : root=UUID=<racine>. Puis rw,
    zswap coupé quand zram sert de swap, lsm= quand AppArmor est actif."""
    opts = []
    if is_luks(settings):
        vg = _get(settings, "disk.lvm.vg") or "vg0"
        opts.append(f"rd.luks.name={disk['luks_uuid']}={LUKS_MAPPER}")
        opts.append(f"root=/dev/{vg}/root")
        if _get(settings, "boot.hibernation") is True and disk.get("swap_dev"):
            opts.append(f"resume={disk['swap_dev']}")
    else:
        opts.append(f"root=UUID={disk['root_uuid']}")
    opts.append("rw")
    if _get(settings, "system.zram.enabled"):
        opts.append("zswap.enabled=0")
    if _get(settings, "security.apparmor"):
        opts.append(f"lsm={APPARMOR_LSM}")
    return opts


def entry_name(kernel, fallback=False):
    suffixe = "-fallback" if fallback else ""
    return f"{ENTRY_PREFIX}-{kernel}{suffixe}.conf"


def loader_conf(default, timeout, editor):
    """loader.conf de systemd-boot : l'entrée par défaut, le délai, la
    plus grande résolution du mode texte, et l'éditeur de ligne de
    commande (qui permettrait init=/bin/sh au clavier) coupé sauf demande
    contraire."""
    return (
        f"default {default}\n"
        f"timeout {int(timeout)}\n"
        "console-mode max\n"
        f"editor {'yes' if editor else 'no'}\n"
    )


def loader_entry(kernel, options, fallback=False):
    """Une entrée BLS. Le microcode est dans l'initramfs (hook
    microcode) : une seule ligne initrd."""
    image = f"initramfs-{kernel}{'-fallback' if fallback else ''}.img"
    titre = f"Arch Linux ({kernel}{', fallback' if fallback else ''})"
    return (
        f"title   {titre}\n"
        f"linux   /vmlinuz-{kernel}\n"
        f"initrd  /{image}\n"
        f"options {' '.join(options)}\n"
    )


def uki_preset(kernel):
    """Le preset mkinitcpio d'un noyau en UKI : une image par défaut et
    une de secours dans /boot/EFI/Linux, où systemd-boot les trouve seul.
    La ligne de commande vient de /etc/kernel/cmdline."""
    return (
        f'ALL_kver="/boot/vmlinuz-{kernel}"\n'
        "PRESETS=('default' 'fallback')\n"
        f'default_uki="/boot/EFI/Linux/arch-{kernel}.efi"\n'
        f'fallback_uki="/boot/EFI/Linux/arch-{kernel}-fallback.efi"\n'
        'fallback_options="-S autodetect"\n'
    )


def image_preset(kernel):
    """Le preset mkinitcpio d'un noyau en initramfs : l'image par défaut
    et l'image de secours (sans autodetect, tous les modules), que
    l'entrée de secours de systemd-boot charge. Le preset que pose le
    paquet du noyau n'a plus que « default »."""
    return (
        f'ALL_kver="/boot/vmlinuz-{kernel}"\n'
        "PRESETS=('default' 'fallback')\n"
        f'default_image="/boot/initramfs-{kernel}.img"\n'
        f'fallback_image="/boot/initramfs-{kernel}-fallback.img"\n'
        'fallback_options="-S autodetect"\n'
    )


def uki_name(kernel):
    return f"arch-{kernel}.efi"


def grub_cmdline(options):
    """Les options de kernel_options() que GRUB_CMDLINE_LINUX doit porter :
    sans « root= » ni « rw », que grub-mkconfig écrit déjà sur chaque
    ligne linux d'après grub-probe ; les garder les doublerait."""
    return [o for o in options if o != "rw" and not o.startswith("root=")]


def edit_grub_default(text, options, timeout):
    """/etc/default/grub avec GRUB_CMDLINE_LINUX et GRUB_TIMEOUT posés,
    chaque ligne remplacée là où elle est ou ajoutée à la fin."""
    valeurs = {
        "GRUB_CMDLINE_LINUX": '"' + " ".join(options) + '"',
        "GRUB_TIMEOUT": str(int(timeout)),
    }
    for cle, valeur in valeurs.items():
        ligne = f"{cle}={valeur}"
        text, n = re.subn(rf"(?m)^#?\s*{cle}=.*$", ligne, text, count=1)
        if not n:
            text = text.rstrip("\n") + "\n" + ligne + "\n"
    return text


def grub_install_attempts(settings, disk):
    """Les grub-install à essayer dans l'ordre, jusqu'au premier qui
    réussit. En EFI, le second écrit EFI/BOOT/BOOTX64.EFI (ou BOOTIA32)
    sans toucher la NVRAM : grub-install appelle efibootmgr, qui échoue
    quand les variables EFI ne sont pas inscriptibles dans le chroot, et
    le chemin de repli suffit au micrologiciel pour démarrer le disque."""
    argv = grub_install_argv(settings, disk)
    if any(a.startswith("--efi-directory=") for a in argv):
        return [argv, argv + ["--removable", "--no-nvram"]]
    return [argv]


def grub_install_argv(settings, disk):
    """grub-install selon la cible résolue : le MBR du disque en i386-pc,
    l'ESP montée sur /boot sinon."""
    cible = (settings.get("derived") or {}).get("grub_target") or "x86_64-efi"
    if cible == "i386-pc":
        return ["grub-install", f"--target={cible}", disk["disk"]]
    return [
        "grub-install",
        f"--target={cible}",
        "--efi-directory=/boot",
        "--bootloader-id=GRUB",
    ]


def fstab_with_swap(text, swap_uuid, swap_dev):
    """fstab avec une ligne de swap : inchangé s'il en porte déjà une,
    sinon la swap ajoutée par UUID (par chemin si l'UUID manque)."""
    for ligne in text.splitlines():
        champs = ligne.split()
        if len(champs) >= 3 and not champs[0].startswith("#"):
            if champs[2] == "swap":
                return text
    source = f"UUID={swap_uuid}" if swap_uuid else swap_dev
    return text.rstrip("\n") + f"\n{source} none swap defaults 0 0\n"


def enable_locales(text, locales):
    """locale.gen avec chaque locale de `locales` décommentée. Une locale
    « fr_CA.UTF-8 » s'y écrit « #fr_CA.UTF-8 UTF-8 ». Une locale absente
    du fichier est ajoutée à la fin."""
    lignes = text.splitlines()
    for locale in locales:
        codage = (
            locale.split(".", 1)[1].split("@")[0] if "." in locale else "UTF-8"
        )
        entree = f"{locale} {codage}"
        trouve = False
        for i, ligne in enumerate(lignes):
            if ligne.lstrip("#").strip() == entree:
                lignes[i] = entree
                trouve = True
        if not trouve:
            lignes.append(entree)
    return "\n".join(lignes) + "\n"


def locale_conf(lang, lc_collate=None):
    texte = f"LANG={lang}\n"
    if lc_collate:
        texte += f"LC_COLLATE={lc_collate}\n"
    return texte


def zram_conf(size, algorithm):
    return (
        f"[zram0]\nzram-size = {size}\ncompression-algorithm = {algorithm}\n"
    )


def zram_sysctl():
    return "".join(f"{cle} = {valeur}\n" for cle, valeur in ZRAM_SYSCTL)


def e2scrub_conf(snap_size_mb):
    """e2scrub prend un instantané LVM de la racine dans l'espace libre du
    groupe : sa taille est celle que l'étape disque y laisse."""
    return f"snap_size_mb={int(snap_size_mb)}\n"


def crypttab_secret(uuid):
    """La ligne crypttab du volume secret : noauto, il reste fermé au
    démarrage et s'ouvre à la demande (systemctl start
    systemd-cryptsetup@erplibre\\x2dsecret)."""
    return f"{SECRET_MAPPER} UUID={uuid} none luks,noauto\n"


def makepkg_native_conf():
    """Drop-in de makepkg : compile pour le processeur de la machine, et
    sur tous ses cœurs. Lu après makepkg.conf, il modifie ses valeurs."""
    return (
        'CFLAGS="${CFLAGS/-march=x86-64 -mtune=generic/-march=native}"\n'
        'CXXFLAGS="${CFLAGS}"\n'
        'RUSTFLAGS="-C target-cpu=native"\n'
        'MAKEFLAGS="-j$(nproc)"\n'
    )


def firstboot_script(user, aur_helper):
    """Le script du premier démarrage : construit l'assistant AUR en tant
    que `user`, pacman autorisé sans mot de passe le temps de la
    construction, puis se désactive. Un échec (réseau absent) le laisse
    actif pour le démarrage suivant."""
    paquet = AUR_HELPERS[aur_helper]
    url = AUR_URL.format(pkg=paquet)
    u = shlex.quote(user)
    return f"""#!/usr/bin/env bash
# Premier démarrage ERPLibre : assistant AUR {aur_helper} pour {user}.
set -eu
exec >>/var/log/erplibre-firstboot.log 2>&1
echo "$(date -Is) start"
printf '%s ALL=(root) NOPASSWD: /usr/bin/pacman\\n' {u} >{FIRSTBOOT_SUDOERS}
chmod 0440 {FIRSTBOOT_SUDOERS}
trap 'rm -f {FIRSTBOOT_SUDOERS}' EXIT
work="$(runuser -u {u} -- mktemp -d)"
runuser -u {u} -- git clone --depth 1 {shlex.quote(url)} "$work/{paquet}"
cd "$work/{paquet}"
runuser -u {u} -- makepkg --syncdeps --install --noconfirm
mkdir -p "$(dirname {FIRSTBOOT_DONE})"
touch {FIRSTBOOT_DONE}
systemctl disable {FIRSTBOOT_UNIT}
echo "$(date -Is) done"
"""


def firstboot_unit():
    return f"""[Unit]
Description=ERPLibre first boot (AUR helper)
Wants=network-online.target
After=network-online.target
ConditionPathExists=!{FIRSTBOOT_DONE}

[Service]
Type=oneshot
ExecStart={FIRSTBOOT_SCRIPT}

[Install]
WantedBy=multi-user.target
"""


def early_packages(settings):
    """Les paquets que l'initramfs et les systèmes de fichiers exigent
    dès le pacstrap de base : en pré-monté, archinstall ne voit ni le LV
    racine ni LUKS, et n'ajoute rien de lui-même."""
    paquets = ["e2fsprogs", "dosfstools"]
    if _get(settings, "disk.lvm.root_fs") == "xfs":
        paquets.append("xfsprogs")
    if is_luks(settings):
        paquets += ["lvm2", "cryptsetup"]
    return paquets


def public_settings(settings):
    """Les réglages copiés dans la cible : tels quels, ils ne portent aucun
    secret (machine_profile refuse tout champ de mot de passe)."""
    return (
        json.dumps(settings, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    )


# Greffon (impur)


def _info(message):
    try:
        from archinstall.lib.log import info

        info(message)
    except Exception:
        print(message)


class Plugin:
    """Les accroches lues par archinstall ; voir la docstring du module.

    `state` (dict) et `version` remplacent la lecture du fichier d'état et
    de la version installée, `echo` faux coupe la copie du journal vers
    archinstall (ou l'écran) : les tests s'en servent."""

    def __init__(self, state=None, version=None, echo=True):
        if state is None:
            chemin = os.environ.get(STATE_ENV, DEFAULT_STATE)
            try:
                with open(chemin, encoding="utf-8") as fh:
                    state = json.load(fh)
            except (OSError, ValueError) as exc:
                raise SystemExit(
                    f"erplibre plugin: no state file {chemin}: {exc}"
                ) from exc
        trouvee = version if version is not None else archinstall_version()
        if not version_ok(trouvee):
            attendue = ".".join(map(str, SUPPORTED_ARCHINSTALL))
            raise SystemExit(
                f"erplibre plugin: archinstall {trouvee} is not supported "
                f"(expected {attendue}.x): refusing to install"
            )
        self.state = state
        self.settings = state.get("settings") or {}
        self.disk = state.get("disk") or {}
        self.status = {}
        self.echo = echo
        self._strapped = False

    # Journal et verdicts

    def log(self, message):
        ligne = f"[erplibre-plugin] {message}"
        if self.echo:
            _info(ligne)
        chemin = self.state.get("log_path")
        if chemin:
            try:
                os.makedirs(os.path.dirname(chemin), exist_ok=True)
                with open(chemin, "a", encoding="utf-8") as fh:
                    fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {ligne}\n")
            except OSError:
                pass

    def _record(self, hook, ok, detail=""):
        self.status[hook] = {"ok": ok, "detail": detail}
        chemin = self.state.get("status_path")
        if chemin:
            try:
                fd = os.open(
                    chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
                )
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self.status, fh, indent=2)
            except OSError:
                pass

    def _run_hook(self, hook, func, *args):
        self.log(f"{hook}: start")
        try:
            resultat = func(*args)
        except Exception as exc:
            self.log(f"{hook}: FAILED: {exc}")
            self._record(hook, False, str(exc))
            raise
        self._record(hook, True)
        self.log(f"{hook}: done")
        return resultat

    # Outils sur la cible

    @staticmethod
    def _target(installation):
        return str(installation.target)

    def _write(self, installation, rel, text, mode=0o644):
        chemin = os.path.join(self._target(installation), rel.lstrip("/"))
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(chemin, mode)
        self.log(f"wrote /{rel.lstrip('/')}")

    def _read(self, installation, rel, default=""):
        chemin = os.path.join(self._target(installation), rel.lstrip("/"))
        try:
            with open(chemin, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return default

    def _exists(self, installation, rel):
        return os.path.exists(
            os.path.join(self._target(installation), rel.lstrip("/"))
        )

    def _chroot(self, installation, argv):
        self.log(f"chroot: {shlex.join(argv)}")
        return installation.arch_chroot(shlex.join(argv))

    def _strap(self, installation, packages):
        self.log(f"pacstrap: {' '.join(packages)}")
        installation.pacman.strap(list(packages))

    def _kernels(self, installation):
        return list(
            getattr(installation, "kernels", None)
            or _get(self.settings, "system.kernels")
            or ["linux"]
        )

    # Accroches

    def on_pacstrap(self, packages):
        """Au pacstrap de base seulement (il porte « base »), ajoute
        early_packages() ; les suivants passent inchangés (None)."""
        if self._strapped or "base" not in packages:
            return None
        self._strapped = True
        ajout = [p for p in early_packages(self.settings) if p not in packages]
        self.log(f"on_pacstrap: adding {' '.join(ajout)}")
        return list(packages) + ajout

    def on_mkinitcpio(self, installation):
        self._run_hook("on_mkinitcpio", self._mkinitcpio, installation)
        return True

    def _mkinitcpio(self, installation):
        hooks = mkinitcpio_hooks(self.settings)
        texte = self._read(installation, "etc/mkinitcpio.conf")
        self._write(
            installation,
            "etc/mkinitcpio.conf",
            edit_mkinitcpio_conf(texte, hooks),
        )
        self.log(f"HOOKS=({' '.join(hooks)})")
        keymap = self.state.get("keymap") or "us"
        self._write(
            installation,
            "etc/vconsole.conf",
            vconsole_conf(
                keymap, self._read(installation, "etc/vconsole.conf")
            ),
        )
        uki = self._uki()
        if uki:
            options = kernel_options(self.settings, self.disk)
            self._write(
                installation, "etc/kernel/cmdline", " ".join(options) + "\n"
            )
            os.makedirs(
                os.path.join(self._target(installation), "boot/EFI/Linux"),
                exist_ok=True,
            )
        for noyau in self._kernels(installation):
            self._write(
                installation,
                f"etc/mkinitcpio.d/{noyau}.preset",
                uki_preset(noyau) if uki else image_preset(noyau),
            )
        self._chroot(installation, ["mkinitcpio", "-P"])

    def _uki(self):
        return (
            bool(_get(self.settings, "boot.uki"))
            and _get(self.settings, "boot.loader") == "systemd-boot"
        )

    def on_add_bootloader(self, installation):
        self._run_hook("on_add_bootloader", self._bootloader, installation)
        return True

    def _bootloader(self, installation):
        if _get(self.settings, "boot.loader") == "systemd-boot":
            self._systemd_boot(installation)
            nom = "erplibre-systemd-boot"
        else:
            self._grub(installation)
            nom = "erplibre-grub"
        flags = getattr(installation, "_helper_flags", None)
        if isinstance(flags, dict):
            flags["bootloader"] = nom

    def _bootctl(self, installation):
        """bootctl install sur l'ESP montée en /boot. arch-chroot passe
        pour un conteneur aux yeux de bootctl, qui saute alors les
        variables EFI : --variables=yes les force ; un bootctl qui ne
        connaît pas l'option, ou des variables en lecture seule, retombent
        sur l'installation sans entrée NVRAM (le chemin de secours
        EFI/BOOT/BOOTX64.EFI reste posé)."""
        essais = (
            ["bootctl", "--variables=yes", "--esp-path=/boot", "install"],
            ["bootctl", "--variables=no", "--esp-path=/boot", "install"],
            ["bootctl", "--esp-path=/boot", "install"],
        )
        derniere = None
        for argv in essais:
            try:
                return self._chroot(installation, argv)
            except Exception as exc:
                derniere = exc
                self.log(f"bootctl attempt failed: {exc}")
        raise RuntimeError(f"bootctl install failed: {derniere}")

    def _systemd_boot(self, installation):
        self._bootctl(installation)
        noyaux = self._kernels(installation)
        timeout = _get(self.settings, "boot.timeout", 3)
        editeur = bool(_get(self.settings, "boot.editor"))
        if self._uki():
            defaut = uki_name(noyaux[0])
        else:
            options = kernel_options(self.settings, self.disk)
            self.log(f"kernel options: {' '.join(options)}")
            for noyau in noyaux:
                self._write(
                    installation,
                    f"boot/loader/entries/{entry_name(noyau)}",
                    loader_entry(noyau, options),
                )
                if self._exists(
                    installation, f"boot/initramfs-{noyau}-fallback.img"
                ):
                    self._write(
                        installation,
                        f"boot/loader/entries/{entry_name(noyau, True)}",
                        loader_entry(noyau, options, fallback=True),
                    )
                else:
                    self.log(
                        f"no fallback image for {noyau}: no fallback entry"
                    )
            defaut = entry_name(noyaux[0])
        self._write(
            installation,
            "boot/loader/loader.conf",
            loader_conf(defaut, timeout, editeur),
        )
        installation.enable_service("systemd-boot-update.service")

    def _grub(self, installation):
        derive = self.settings.get("derived") or {}
        paquets = ["grub"]
        if derive.get("grub_target") != "i386-pc":
            paquets.append("efibootmgr")
        self._strap(installation, paquets)
        options = grub_cmdline(kernel_options(self.settings, self.disk))
        self.log(f"kernel options: {' '.join(options)}")
        texte = self._read(installation, "etc/default/grub")
        self._write(
            installation,
            "etc/default/grub",
            edit_grub_default(
                texte, options, _get(self.settings, "boot.timeout", 3)
            ),
        )
        derniere = None
        for argv in grub_install_attempts(self.settings, self.disk):
            try:
                self._chroot(installation, argv)
                break
            except Exception as exc:
                derniere = exc
                self.log(f"grub-install attempt failed: {exc}")
        else:
            raise RuntimeError(f"grub-install failed: {derniere}")
        self._chroot(
            installation, ["grub-mkconfig", "-o", "/boot/grub/grub.cfg"]
        )

    def on_genfstab(self, installation):
        self._run_hook("on_genfstab", self._genfstab, installation)
        return None

    def _genfstab(self, installation):
        swap_dev = self.disk.get("swap_dev")
        if not swap_dev:
            self.log("no swap volume")
            return
        texte = self._read(installation, "etc/fstab")
        nouveau = fstab_with_swap(texte, self.disk.get("swap_uuid"), swap_dev)
        if nouveau != texte:
            self._write(installation, "etc/fstab", nouveau)
            self.log("swap line added to fstab")
        else:
            self.log("fstab already has a swap line")

    def on_user_created(self, installation, user):
        self._run_hook("on_user_created", self._user, installation, user)
        return None

    def _user(self, installation, user):
        nom = getattr(user, "username", None)
        shell = _get(self.settings, "user.shell") or "bash"
        if nom != _get(self.settings, "user.name") or shell == "bash":
            return
        if shell in SHELL_PACKAGES:
            self._strap(installation, [SHELL_PACKAGES[shell]])
        self._chroot(
            installation, ["usermod", "--shell", SHELL_PATHS[shell], nom]
        )

    def on_install(self, installation):
        self._run_hook("on_install", self._install, installation)

    def _install(self, installation):
        s = self.settings
        locales = _get(s, "system.locales") or []
        lang = _get(s, "system.lang")
        if locales:
            texte = self._read(installation, "etc/locale.gen")
            self._write(
                installation, "etc/locale.gen", enable_locales(texte, locales)
            )
            self._chroot(installation, ["locale-gen"])
        if lang:
            self._write(
                installation,
                "etc/locale.conf",
                locale_conf(lang, _get(s, "system.lc_collate")),
            )
        try:
            self._chroot(installation, ["hwclock", "--systohc"])
        except Exception as exc:
            # Une horloge matérielle inaccessible depuis le chroot ne
            # compromet pas le système : timesyncd la corrige au démarrage.
            self.log(f"hwclock --systohc failed (ignored): {exc}")

        zram = _get(s, "system.zram") or {}
        if zram.get("enabled"):
            self._strap(installation, ["zram-generator"])
            self._write(
                installation,
                "etc/systemd/zram-generator.conf",
                zram_conf(zram.get("size"), zram.get("algorithm")),
            )
            if zram.get("sysctl_tuning"):
                self._write(
                    installation, "etc/sysctl.d/99-zram.conf", zram_sysctl()
                )

        if _get(s, "system.e2scrub"):
            if is_luks(s) and _get(s, "disk.lvm.vg_free_mib"):
                self._write(
                    installation,
                    "etc/e2scrub.conf",
                    e2scrub_conf(_get(s, "disk.lvm.vg_free_mib")),
                )
            else:
                self.log("e2scrub: no free space in a VG, not configured")

        if self.disk.get("secret_luks_uuid"):
            texte = self._read(installation, "etc/crypttab")
            if SECRET_MAPPER not in texte:
                self._write(
                    installation,
                    "etc/crypttab",
                    texte + crypttab_secret(self.disk["secret_luks_uuid"]),
                    0o600,
                )

        if _get(s, "firstboot.makepkg_native"):
            self._write(
                installation,
                "etc/makepkg.conf.d/erplibre-native.conf",
                makepkg_native_conf(),
            )

        helper = _get(s, "firstboot.aur_helper")
        if helper in AUR_HELPERS:
            self._write(
                installation,
                FIRSTBOOT_SCRIPT,
                firstboot_script(_get(s, "user.name"), helper),
                0o755,
            )
            self._write(
                installation,
                f"etc/systemd/system/{FIRSTBOOT_UNIT}",
                firstboot_unit(),
            )
            installation.enable_service(FIRSTBOOT_UNIT)

        if self.state.get("root_policy") == "lock":
            # usermod --lock préfixe le hash de « ! » et réussit aussi sur
            # un compte déjà verrouillé, là où passwd --lock échoue.
            self._chroot(installation, ["usermod", "--lock", "root"])

        self._write(
            installation,
            f"{TARGET_STATE_DIR}/settings.json",
            public_settings(s),
            0o600,
        )
        self._write(
            installation,
            f"{TARGET_STATE_DIR}/facts.json",
            public_settings(self.state.get("facts") or {}),
            0o600,
        )
