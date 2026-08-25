#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu QEMU/KVM : atteindre une VM \u2014 SSH, tunnels, consoles, \u00e9mulateur.\n\nTout ce qui relie l'humain \u00e0 une machine d\u00e9j\u00e0 d\u00e9ploy\u00e9e : ~/.ssh/config et ses\nProxyJump, la d\u00e9couverte des VM imbriqu\u00e9es, les tunnels de bureau distant, la\nconsole s\u00e9rie et graphique (virt-viewer), et l'\u00e9mulateur Android d'une VM\ngraphique avec son tunnel adb.\n\nS\u00e9par\u00e9 du reste parce que c'est le seul bloc qui parle de R\u00c9SEAU et de\nsessions interactives, jamais de cr\u00e9ation ni de destruction de VM."""

import os
import shutil
import socket
import subprocess
import time

from script.todo.todo_i18n import t


class QemuAccessMixin:
    """Menu QEMU/KVM : atteindre une VM \u2014 SSH, tunnels, consoles, \u00e9mulateur.\n\nTout ce qui relie l'humain \u00e0 une machine d\u00e9j\u00e0 d\u00e9ploy\u00e9e : ~/.ssh/config et ses\nProxyJump, la d\u00e9couverte des VM imbriqu\u00e9es, les tunnels de bureau distant, la\nconsole s\u00e9rie et graphique (virt-viewer), et l'\u00e9mulateur Android d'une VM\ngraphique avec son tunnel adb.\n\nS\u00e9par\u00e9 du reste parce que c'est le seul bloc qui parle de R\u00c9SEAU et de\nsessions interactives, jamais de cr\u00e9ation ni de destruction de VM."""

    # Compte créé par cloud-init dans les VM déployées ici. Sert de défaut
    # quand ~/.ssh/config ne déclare aucun `User` pour l'hôte adopté.
    QEMU_VM_USER = "erplibre"

    # Profondeur d'exploration par défaut : hôte -> VM -> VM imbriquée. Le
    # profil « ERPLibre Déploiement (+ QEMU + dev) » installe QEMU DANS la VM,
    # donc un parc à deux niveaux est le cas courant.
    _QEMU_SSH_DEPTH = 2

    # Sonde exécutée SUR une machine. Première ligne « LIBVIRT<TAB>yes|no »,
    # puis un couple « nom<TAB>ip » par VM. Une seule connexion SSH par
    # niveau plutôt qu'une par VM ; le bail dnsmasq peut manquer, d'où le
    # repli sur l'agent invité.
    #
    # La première ligne est indispensable : sans virsh, la boucle ne tourne
    # simplement pas et la sonde sortirait VIDE avec un code 0 — impossible
    # alors de distinguer « pas de QEMU ici » de « QEMU présent, aucune VM ».
    # Sonde exécutée à DISTANCE, dans une session SSH non interactive.
    #
    # « sudo virsh » y échoue dès que l'hôte demande un mot de passe — vécu sur
    # erplibre01 (sudo-rs) — et la sonde répondait alors « pas de QEMU » sur une
    # machine qui en fait tourner. On essaie donc virsh SANS sudo d'abord, via
    # qemu:///system : appartenir au groupe libvirt suffit, sans tty.
    #
    # « --connect qemu:///system » est indispensable dans ce cas : sans lui, un
    # utilisateur non root tombe sur qemu:///session, qui répond correctement…
    # une liste VIDE. On aurait alors « QEMU présent, aucune VM », ce qui est
    # pire qu'une erreur puisque c'est plausible.
    #
    # Trois réponses et non deux : « denied » distingue « virsh est là mais
    # inaccessible » de « pas de QEMU ici », deux situations qui appellent des
    # gestes opposés.
    _QEMU_SSH_PROBE = (
        'vsh() { virsh --connect qemu:///system "$@" 2>/dev/null '
        '|| sudo -n virsh --connect qemu:///system "$@" 2>/dev/null; }; '
        "if ! command -v virsh >/dev/null 2>&1; then "
        "printf 'LIBVIRT\\tno\\n'; exit 0; fi; "
        "vms=$(vsh list --all --name) || "
        "{ printf 'LIBVIRT\\tdenied\\n'; exit 0; }; "
        "printf 'LIBVIRT\\tyes\\n'; "
        "for n in $vms; do "
        'ip=$(vsh domifaddr "$n" --source lease '
        "| grep -oE '([0-9]{1,3}\\.){3}[0-9]{1,3}' | head -1); "
        'if [ -z "$ip" ]; then '
        'ip=$(vsh domifaddr "$n" --source agent '
        "| grep -oE '([0-9]{1,3}\\.){3}[0-9]{1,3}' "
        "| grep -v '^127\\.' | head -1); fi; "
        'printf "%s\\t%s\\n" "$n" "$ip"; done'
    )

    def _qemu_ssh_pick_roots(self):
        """D'où partir pour configurer ~/.ssh/config. Renvoie une liste de
        racines [{alias, ip|None}], ou [] pour renoncer.

        Trois provenances, parce que « la machine à configurer » n'est pas
        toujours une VM d'ici : elle peut être un hôte déjà connu de
        ~/.ssh/config, ou une adresse qu'on vient d'obtenir."""
        print(f"\n{t('Where should the machines come from?')}")
        print(f"  [1] {t('Local QEMU VMs (virsh)')} *")
        print(f"  [2] {t('Hosts from ~/.ssh/config')}")
        print(f"  [3] {t('Type a host or an IP')}")
        print(f"  [0] {t('Back')}")
        answer = input(t("Choice (0-3, default 1): ")).strip()
        if answer == "0":
            return []

        if answer == "2":
            hosts = self._ssh_config_hosts()
            if not hosts:
                print(f"  {t('~/.ssh/config holds no host.')}")
                return []
            for i, name in enumerate(hosts, 1):
                print(f"  [{i}] {name}")
            raw = input(
                t("Which hosts? (numbers, comma-separated; blank = all): ")
            ).strip()
            chosen = (
                hosts if not raw else self._parse_index_selection(raw, hosts)
            )
            # Déjà dans ~/.ssh/config : leur adresse y est, rien à réécrire.
            # Le `User` déclaré est repris tel quel : ces hôtes ne sont pas
            # forcément des VM ERPLibre, et leurs invitées suivent la même
            # convention que leur parent.
            return [
                {
                    "alias": name,
                    "ip": None,
                    "user": self._ssh_config_user(name),
                }
                for name in chosen or hosts
            ]

        if answer == "3":
            target = input(f"{t('Host or IP:')} ").strip()
            if not target:
                return []
            if target in self._ssh_config_hosts():
                return [
                    {
                        "alias": target,
                        "ip": None,
                        "user": self._ssh_config_user(target),
                    }
                ]
            # « utilisateur@hôte » est accepté : c'est la forme qu'on tape
            # naturellement, et elle évite une question de plus.
            user, _, address = target.rpartition("@")
            # Une IP brute n'est pas un alias : on lui en donne un, sinon ni
            # le ProxyJump des enfants ni virt-manager n'auraient de nom.
            default_alias = "qemu-" + address.replace(".", "-")
            alias = (
                input(
                    f"{t('Name for ~/.ssh/config')} ({default_alias}): "
                ).strip()
                or default_alias
            )
            if not user:
                user = (
                    input(f"{t('User')} ({self.QEMU_VM_USER}): ").strip()
                    or self.QEMU_VM_USER
                )
            return [{"alias": alias, "ip": address, "user": user}]

        names = self._qemu_pick_domains()
        if not names:
            return []
        ip_map = self._qemu_resolve_ips(names, timeout=60)
        roots = []
        for name in names:
            ip = ip_map.get(name)
            if not ip:
                print(f"  ⏭  {name}: {t('no IP')}")
                continue
            roots.append({"alias": name, "ip": ip})
        return roots

    # Ports du bureau distant, par gestionnaire de paquets de la VM. Ils
    # viennent de _QEMU_DESKTOP_REMOTE, seule source : xrdp sur 3389 partout,
    # sauf Arch qui reçoit TigerVNC sur 5901.
    @classmethod
    def _qemu_desktop_port(cls, distro):
        if distro == "arch":
            return cls._QEMU_DESKTOP_REMOTE["pacman"]["port"], "VNC"
        return cls._QEMU_DESKTOP_REMOTE["apt"]["port"], "RDP"

    @staticmethod
    def _qemu_self_address():
        """Adresse par laquelle l'utilisateur a JOINT cet hôte.

        SSH_CONNECTION porte « ip_client port_client ip_serveur port_serveur » :
        le troisième champ est exactement l'adresse à remettre dans la commande
        de tunnel, bien mieux qu'un « hostname » qui peut ne rien résoudre
        depuis le poste de travail. Hors session SSH, on retombe sur le nom
        d'hôte, en le signalant."""
        conn = os.environ.get("SSH_CONNECTION", "").split()
        if len(conn) >= 3:
            return conn[2], True
        return socket.gethostname(), False

    def _qemu_tunnel_menu(self):
        """Commande de tunnel SSH vers le bureau distant d'une machine.

        La source des cibles est ~/.ssh/config, PAS le libvirt local. La VM
        graphique est souvent imbriquee : un orchestrateur QEMU tourne dans une
        VM, et la machine a bureau vit DANS cet orchestrateur. Le « virsh » du
        poste ne voit alors que l'orchestrateur, et proposer sa liste menait
        droit a la mauvaise machine — vecu.

        ~/.ssh/config, lui, connait les deux, ProxyJump compris : c'est la
        seule vue qui traverse les niveaux. Les domaines libvirt LOCAUX sont
        ajoutes en complement quand ils ne s'y trouvent pas deja.
        """
        print(f"\n🖥  {t('Remote desktop tunnel')}")
        hosts = list(self._ssh_config_hosts())
        targets = [(h, "ssh_config") for h in hosts]
        # Complement local, sans sudo tant qu'on n'en a pas besoin : la
        # plupart des cibles utiles sont deja dans ssh_config.
        if not targets:
            for name in self._qemu_list_domains():
                targets.append((name, "virsh"))
        if not targets:
            print(f"  {t('No host in ~/.ssh/config and no local VM.')}")
            return
        for i, (name, src) in enumerate(targets, 1):
            mark = "" if src == "ssh_config" else f"  ({t('local VM')})"
            print(f"  [{i}] {name}{mark}")
        answer = input(f"{t('Which VM?')} [1]: ").strip() or "1"
        if not answer.isdigit() or not (1 <= int(answer) <= len(targets)):
            print(t("Cancelled."))
            return
        name, src = targets[int(answer) - 1]

        # Le port ne se devine pas pour un hote de ssh_config : on ne connait
        # ni sa distribution ni son bureau. On propose, l'utilisateur tranche.
        print(f"\n  {t('Remote desktop kind:')}")
        print(f"  [1] RDP 3389 (xrdp) *")
        print(f"  [2] VNC 5901 (TigerVNC, Arch)")
        print(
            f"  [3] {t('Hypervisor console (QEMU screen, no guest server)')}"
        )
        print(f"  [4] {t('Android emulator (adb 5555, then scrcpy)')}")
        print(f"  [5] {t('Graphical console (virt-viewer, built-in tunnel)')}")
        kind_answer = input(f"{t('Choice')} [1]: ").strip() or "1"
        if kind_answer == "3":
            self._qemu_console_tunnel(name, src)
            return
        if kind_answer == "4":
            self._qemu_scrcpy_tunnel(name, src)
            return
        if kind_answer == "5":
            self._qemu_virt_viewer(name, src)
            return
        port, kind = (5901, "VNC") if kind_answer == "2" else (3389, "RDP")
        local = port + 1

        print(f"\n  {t('Run this on YOUR workstation:')}")
        if src == "ssh_config":
            # « localhost » est resolu par le DERNIER saut, donc par la machine
            # elle-meme : le ProxyJump de ssh_config traverse les niveaux.
            print(f"\n    ssh -N -L {local}:localhost:{port} {name}\n")
            print(f"  {t('(through the ProxyJump already in ~/.ssh/config)')}")
        else:
            ip = self._qemu_resolve_ips([name]).get(name)
            if not ip:
                print(f"  {t('No IP for this VM; is it running?')}")
                return
            host, from_ssh = self._qemu_self_address()
            user = os.environ.get("USER", "user")
            if not from_ssh:
                print(
                    f"  ⚠ {t('Not in an SSH session: check the host address.')}"
                )
            print(f"\n    ssh -N -L {local}:{ip}:{port} {user}@{host}\n")
            print(f"  ⚠ {t('No ~/.ssh/config entry; see SSH configuration.')}")
        print(
            f"  {t('then point your client at')} localhost:{local}  ({kind})"
        )
        print(f"  {t('The tunnel stays open as long as that ssh runs.')}")

    @staticmethod
    def _qemu_ssh_opts(src):
        """Options ssh selon la provenance de la cible.

        Une VM libvirt locale est jointe par son IP, et son IP est recyclée d'un
        déploiement à l'autre : sa clé d'hôte change sous le même adresse, et
        ssh refuse alors de se connecter — « Host key verification failed »,
        vécu. C'est la raison pour laquelle le suivi d'installation et l'attente
        de sshd emploient déjà ces deux options.

        Un hôte de ~/.ssh/config, lui, est une machine que l'utilisateur a
        configurée : on ne touche PAS à sa politique de clés. Sa clé est un
        garde-fou qui lui appartient."""
        if src == "ssh_config":
            return ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
        return [
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
        ]

    def _qemu_ssh_target(self, name, src):
        """Destination ssh d'une cible du menu, selon sa provenance.

        Un hôte de ~/.ssh/config se nomme tel quel — c'est lui qui porte le
        ProxyJump, et le réécrire à la main reviendrait à le deviner. Un domaine
        libvirt local, lui, n'a qu'une IP, et l'utilisateur des VM ERPLibre est
        « erplibre ». Renvoie une chaîne vide quand l'IP manque."""
        if src == "ssh_config":
            return name
        ip = self._qemu_resolve_ips([name]).get(name)
        return f"erplibre@{ip}" if ip else ""

    # Commande de l'émulateur dans la VM. Le chemin est ABSOLU : un
    # « ssh hôte 'commande' » ne lit ni ~/.profile ni ~/.bashrc.
    _QEMU_EMULATOR_BIN = "$HOME/android/emulator/emulator"

    # Drapeaux passés à CHAQUE lancement, et non écrits dans le config.ini de
    # l'AVD : l'émulateur réécrit ce fichier depuis le profil du téléphone au
    # premier démarrage, et les hw.lcd.* y étaient effacés — l'AVD repartait en
    # 1080x2400 densité 420, quatre fois les pixels voulus. Mesuré.
    #
    # La résolution et la DENSITÉ vont ensemble, et c'est contre-intuitif :
    # 540x1140 en densité 420 est PIRE que le plein écran — 81 ms de médiane
    # contre 40, et 57 % d'images en retard contre 37, tout étant rendu énorme.
    # Avec la densité 240, la queue s'effondre : 99e centile à 250 ms contre
    # 950, et 32 % d'images en retard.
    #
    # « -no-snapshot-save » : sans lui, un émulateur tué par pkill — ce que ce
    # menu propose lui-même — laisse un instantané en cours, et le lancement
    # SUIVANT meurt sur « A snapshot operation is pending and timeout has
    # expired ». Vécu, et le message ne dit pas quoi faire.
    # « -gpu » reste sur swangle par DÉFAUT, même quand la VM a la 3D : un
    # « -gpu host » qui échoue ne rend pas la main, l'émulateur reste pendu, et
    # ce n'est pas un défaut à imposer sans l'avoir mesuré sur la machine.
    # EL_EMULATOR_GPU permet de l'essayer sans toucher au code, une fois le
    # nœud de rendu présent dans l'invité (voir script/qemu/README).
    _QEMU_EMULATOR_GPU = os.environ.get("EL_EMULATOR_GPU") or "swangle"

    _QEMU_EMULATOR_FLAGS = (
        "-no-audio -no-boot-anim -no-snapshot-save"
        f" -gpu {_QEMU_EMULATOR_GPU}"
        " -skin 540x1140 -prop qemu.sf.lcd_density=240"
    )

    _QEMU_AVD_NAME = "erplibre"

    def _qemu_emulator_running(self, target, src="virsh"):
        """Nombre d'émulateurs en cours dans la VM.

        Deux sur le même AVD, et le second s'arrête sur « Running multiple
        emulators with the same AVD is an experimental feature ». Le savoir
        AVANT de lancer évite de lire cette phrase sans la comprendre — vécu,
        deux fois."""
        try:
            res = subprocess.run(
                ["ssh"]
                + self._qemu_ssh_opts(src)
                + [target, "pgrep -c qemu-system 2>/dev/null || echo 0"],
                capture_output=True,
                text=True,
                timeout=25,
            )
            return int((res.stdout or "0").strip().splitlines()[-1])
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return -1

    def _qemu_emulator_ready(self, target, src="virsh"):
        """La VM a-t-elle de quoi émuler ? Rend (prêt, raison).

        Le binaire ET l'AVD, en une seule lecture : sans cette vérification le
        démarrage détaché rendait 0 sur une VM sans SDK, et le menu annonçait
        « Démarré » quand le journal disait « not found ». Une VM déployée sans
        cocher l'outil Émulateur Android est le cas normal, pas une panne."""
        probe = (
            f"test -x {self._QEMU_EMULATOR_BIN} || echo NO_SDK; "
            f"test -d $HOME/.android/avd/{self._QEMU_AVD_NAME}.avd"
            " || echo NO_AVD"
        )
        try:
            res = subprocess.run(
                ["ssh"] + self._qemu_ssh_opts(src) + [target, probe],
                capture_output=True,
                text=True,
                timeout=25,
            )
        except (OSError, subprocess.SubprocessError):
            return False, t("Cannot reach this VM.")
        out = res.stdout or ""
        if "NO_SDK" in out:
            return False, t("No Android SDK in this VM: no emulator binary.")
        if "NO_AVD" in out:
            return False, t("No AVD named erplibre in this VM.")
        return True, ""

    def _qemu_emulator_menu(self):
        """Démarre l'émulateur Android d'une VM, et donne la suite qui va avec.

        La question qui décide de tout est celle de la FENÊTRE :
          - avec fenêtre, l'écran voyage en pixels bruts par X11, et la commande
            doit partir du poste qui possède l'affichage — donc pas d'ici ;
          - sans fenêtre, on peut la lancer d'ici, détachée, et l'image arrive
            ensuite par scrcpy en H.264. C'est la voie fluide.
        """
        print(f"\n📱 {t('Android emulator')}")
        targets = [(h, "ssh_config") for h in self._ssh_config_hosts()]
        if not targets:
            targets = [(n, "virsh") for n in self._qemu_list_domains()]
        if not targets:
            print(f"  {t('No host in ~/.ssh/config and no local VM.')}")
            return
        for i, (nm, sr) in enumerate(targets, 1):
            mark = "" if sr == "ssh_config" else f"  ({t('local VM')})"
            print(f"  [{i}] {nm}{mark}")
        answer = input(f"{t('Which VM?')} [1]: ").strip() or "1"
        if not answer.isdigit() or not (1 <= int(answer) <= len(targets)):
            print(t("Cancelled."))
            return
        name, src = targets[int(answer) - 1]
        target = self._qemu_ssh_target(name, src)
        if not target:
            print(f"  {t('No IP for this VM; is it running?')}")
            return

        running = self._qemu_emulator_running(target, src)
        if running > 0:
            print(f"\n  ⚠ {t('An emulator is already running on this VM.')}")
            print(f"  {t('Only one per AVD; close it first:')}")
            print(f"\n    ssh {target} 'pkill -f \"[q]emu-system-x86_64\"'\n")
            if not self._is_yes(input(t("Close it now? (y/N): "))):
                return
            subprocess.run(
                ["ssh"]
                + self._qemu_ssh_opts(src)
                + [target, 'pkill -f "[q]emu-system-x86_64"'],
                capture_output=True,
                timeout=30,
            )
            print(f"  {t('Closed.')}")

        ready, why = self._qemu_emulator_ready(target, src)
        if not ready:
            print(f"\n  ⚠ {why}")
            print(f"  {t('Tick the Android emulator tool when deploying.')}")
            return

        print(f"\n  {t('Show a window?')}")
        print(f"  [1] {t('No window - stream with scrcpy (smoother)')} *")
        print(f"  [2] {t('Window over ssh -X (raw pixels, slower)')}")
        kind = input(f"{t('Choice')} [1]: ").strip() or "1"
        # Sans cette validation, TOUT ce qui n'est pas « 2 » démarrait
        # l'émulateur : une frappe de travers (« n ») lançait le démarrage,
        # observé. Un menu à deux crans n'a pas de troisième réponse.
        if kind not in ("1", "2"):
            print(t("Cancelled."))
            return
        emu = self._QEMU_EMULATOR_BIN
        avd = self._QEMU_AVD_NAME

        if kind == "2":
            # L'affichage appartient au POSTE : cette commande ne peut pas
            # partir d'ici, où il n'y a pas d'écran à lui donner.
            print(f"\n  {t('Run this on YOUR workstation:')}")
            print(
                f"\n    ssh -XC {target} '{emu} -avd {avd} "
                f"{self._QEMU_EMULATOR_FLAGS}'\n"
            )
            print(
                f"  {t('X11 compression is on (-XC); the screen is 540x1140.')}"
            )
            return

        print(f"\n  {t('Starting the emulator without a window...')}")
        # « sg kvm » : l'appartenance au groupe est posée à l'installation, mais
        # une VM créée avant ce correctif ne l'a pas dans sa session — sans KVM
        # l'émulateur refuse de démarrer. setsid le détache, pour qu'il survive
        # à la fermeture de ce ssh.
        start = (
            f'setsid -f sg kvm -c "{emu} -avd {avd} -no-window '
            f"{self._QEMU_EMULATOR_FLAGS}"
            ' > /tmp/erplibre-emulator.log 2>&1"'
        )
        res = subprocess.run(
            ["ssh"] + self._qemu_ssh_opts(src) + [target, start],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if res.returncode:
            print(f"  ⚠ {t('Could not start it:')} {res.stderr.strip()[:200]}")
            return
        # « setsid » détache : le code de retour ne dit RIEN de l'émulateur.
        # Le menu annonçait « Démarré » pendant que le journal de la VM disait
        # « not found » — mesuré sur une VM sans SDK. On attend donc de voir le
        # processus, et à défaut on rapporte le journal.
        for _ in range(5):
            if self._qemu_emulator_running(target, src) > 0:
                break
            time.sleep(2)
        else:
            print(f"  ⚠ {t('It did not start; the VM log says:')}")
            log = subprocess.run(
                ["ssh"]
                + self._qemu_ssh_opts(src)
                + [target, "tail -5 /tmp/erplibre-emulator.log 2>/dev/null"],
                capture_output=True,
                text=True,
                timeout=25,
            )
            for line in (log.stdout or "").strip().splitlines():
                print(f"    {line}")
            return
        print(
            f"  {t('Started. Boot takes about a minute; log in the VM:')}"
            " /tmp/erplibre-emulator.log"
        )
        self._qemu_scrcpy_tunnel(name, src, started=True)

    def _qemu_scrcpy_tunnel(self, name, src, started=False):
        """Tunnel adb vers l'émulateur Android d'une VM, pour scrcpy.

        Pourquoi cette voie plutôt que « ssh -X » : par X11, chaque image de
        l'écran traverse le réseau en pixels bruts — 0,62 Mpixel par image même
        après réduction, en rendu logiciel. scrcpy, lui, reçoit un flux H.264
        encodé PAR l'appareil et le décode sur le poste. L'émulateur tourne
        alors SANS fenêtre : plus de X11 du tout, ni sur l'hôte ni dans la VM.

        Le port est celui de l'émulateur, pas celui du serveur adb. Un émulateur
        écoute sur 5554 (console) et 5555 (adb), tous deux sur le localhost de
        la VM — vérifié par « ss -ltn ». C'est 5555 qu'il faut, et non 5037 :
        tunneler le serveur adb obligerait à tuer celui du poste, qui occupe le
        même port.

        Vérifié de bout en bout à travers le tunnel : une poignée de main adb
        (paquet CNXN) reçoit « device::ro.product.name=sdk_gphone64_x86 » de
        l'émulateur lui-même — c'est exactement ce que fait « adb connect ».
        """
        port = 5555
        target = self._qemu_ssh_target(name, src)
        if not target:
            print(f"  {t('No IP for this VM; is it running?')}")
            return
        print(f"\n  📱 {t('Android emulator over adb + scrcpy')}")
        if started:
            # Inutile de redire comment le démarrer : on vient de le faire.
            print(f"\n  {t('1. Emulator started, without a window.')}")
        else:
            print(
                f"\n  {t('1. In the VM, start the emulator WITHOUT a window:')}"
            )
            print(
                f"\n    ssh {target} '{self._QEMU_EMULATOR_BIN} "
                f"-avd {self._QEMU_AVD_NAME} -no-window "
                f"{self._QEMU_EMULATOR_FLAGS}'\n"
            )
        print(f"  {t('2. Open the tunnel from YOUR workstation:')}")
        if src == "ssh_config":
            # « localhost » est résolu par le DERNIER saut, donc par la VM
            # elle-même : le ProxyJump de ssh_config traverse les niveaux.
            print(f"\n    ssh -N -L {port}:localhost:{port} {name}\n")
            print(f"  {t('(through the ProxyJump already in ~/.ssh/config)')}")
        else:
            host, from_ssh = self._qemu_self_address()
            user = os.environ.get("USER", "user")
            vm_ip = target.split("@")[-1]
            if not from_ssh:
                print(
                    f"  ⚠ {t('Not in an SSH session: check the host address.')}"
                )
            # DEUX sauts, et non un seul vers l'hyperviseur : l'émulateur
            # n'écoute que sur le 127.0.0.1 de la VM — « ss -ltn » le montre, et
            # l'hyperviseur reçoit un refus sur IP_VM:5555. Or « localhost » se
            # résout sur le DERNIER hôte de la chaîne : la VM doit donc être ce
            # dernier saut, l'hyperviseur n'étant que le relais (-J).
            print(
                f"\n    ssh -N -L {port}:localhost:{port}"
                f" -J {user}@{host} erplibre@{vm_ip}\n"
            )
            print(
                f"  {t('(the hypervisor only relays; -J puts the VM last)')}"
            )
        print(f"  {t('3. Then, still on your workstation:')}")
        print(f"\n    adb connect localhost:{port}")
        print(f"    scrcpy -s localhost:{port}\n")
        print(f"  {t('The tunnel stays open as long as that ssh runs.')}")
        print(f"  {t('scrcpy on Debian/Ubuntu:')} sudo apt install scrcpy adb")

        # Ouvrir le tunnel D'ICI n'a de sens que si scrcpy tournera ici : le
        # port ressort sur CETTE machine. On le propose donc en le disant,
        # plutôt que de le faire d'office depuis un hyperviseur sans écran.
        print(f"\n  {t('If scrcpy will run on THIS machine, I can open it.')}")
        if not self._is_yes(input(t("Open the tunnel now? (y/N): "))):
            return
        if self._port_in_use(port):
            print(f"  ⚠ {t('Port already in use here:')} {port}")
            print(
                f"  {t('Close the other tunnel first:')}"
                f' pkill -f "{port}:localhost:{port}"'
            )
            return
        # « ExitOnForwardFailure » : sans lui, un ssh détaché rend 0 alors que
        # la redirection a échoué — un succès annoncé pour un tunnel absent.
        cmd = (
            ["ssh", "-f", "-N", "-o", "ExitOnForwardFailure=yes"]
            + self._qemu_ssh_opts(src)
            + ["-L", f"{port}:localhost:{port}", target]
        )
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        if res.returncode:
            print(f"  ⚠ {t('Tunnel failed:')} {res.stderr.strip()[:200]}")
            return
        print(f"  ✅ {t('Tunnel open on localhost:')}{port}")
        print(
            f"  {t('Then:')} adb connect localhost:{port}"
            f" && scrcpy -s localhost:{port}"
        )
        print(f'  {t("To close it:")} pkill -f "{port}:localhost:{port}"')

    # Un paquet, quatre familles. virt-viewer porte le même nom partout, ce qui
    # est rare et bienvenu : seule la commande d'installation change.
    _QEMU_VIRT_VIEWER_INSTALL = (
        ("apt-get", "sudo apt-get install -y virt-viewer"),
        ("dnf", "sudo dnf install -y virt-viewer"),
        ("pacman", "sudo pacman -S --needed --noconfirm virt-viewer"),
        ("zypper", "sudo zypper --non-interactive install virt-viewer"),
    )

    def _qemu_ensure_virt_viewer(self):
        """virt-viewer sur CETTE machine, installé s'il manque.

        Installé seulement là où il va SERVIR : sur un hyperviseur sans écran,
        poser un client graphique ne rendrait service à personne. C'est
        l'appelant qui a vérifié l'affichage."""
        if shutil.which("virt-viewer"):
            return True
        print(f"\n  {t('virt-viewer is missing here; installing it.')}")
        for tool, cmd in self._QEMU_VIRT_VIEWER_INSTALL:
            if shutil.which(tool):
                print(f"  {t('Will execute:')} {cmd}")
                self.execute.exec_command_live(cmd, source_erplibre=False)
                break
        else:
            print(f"  ⚠ {t('no known package manager here.')}")
            return False
        if shutil.which("virt-viewer"):
            print(f"  ✅ virt-viewer")
            return True
        print(f"  ⚠ {t('virt-viewer still missing after the install.')}")
        return False

    def _qemu_virt_viewer(self, name, src):
        """Ouvre l'écran d'une VM avec virt-viewer, qui monte SON tunnel.

        C'est la voie la plus courte : virt-viewer parle à libvirt par
        « qemu+ssh:// » et n'a besoin d'aucun « ssh -L » à tenir ouvert. Il lit
        aussi le port de l'écran par libvirt, donc rien à deviner.

        La seule question qui compte est celle de l'AFFICHAGE. virt-viewer
        ouvre une fenêtre : il doit tourner là où il y a un écran. Deux cas, et
        c'est l'environnement qui tranche, pas une question de plus :
          - un affichage est là (poste de travail, ou « ssh -X ») : on installe
            virt-viewer au besoin et on le lance, détaché ;
          - aucun affichage : on donne la commande à lancer sur le poste, sous
            la forme qemu+ssh, avec l'adresse par laquelle cette machine a été
            jointe.
        """
        domain = name.rsplit("+", 1)[-1] if src == "ssh_config" else name
        display = os.environ.get("DISPLAY") or os.environ.get(
            "WAYLAND_DISPLAY"
        )
        if src == "ssh_config":
            # L'hyperviseur est le ProxyJump déclaré : c'est lui qui fait
            # tourner le QEMU de cette VM, pas la VM elle-même.
            jump = self._ssh_proxyjump(name)
            if not jump:
                print(
                    f"\n  ⚠ {t('No ProxyJump for this host in ~/.ssh/config.')}"
                )
                print(f"  {t('Cannot tell which machine runs its QEMU.')}")
                return
            uri = f"qemu+ssh://{jump}/system"
        else:
            uri = "qemu:///system"

        if display:
            if not self._qemu_ensure_virt_viewer():
                return
            cmd = ["virt-viewer", "-c", uri, domain]
            print(f"\n  {t('Opening')} : {' '.join(cmd)}")
            try:
                with open("/tmp/erplibre-virt-viewer.log", "ab") as log:
                    subprocess.Popen(
                        cmd,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,
                    )
            except OSError as exc:
                print(f"  ⚠ {t('Could not start it:')} {exc}")
                return
            print(f"  {t('Window opening on your display')} ({display}).")
            print(f"  {t('Log:')} /tmp/erplibre-virt-viewer.log")
            return

        host, from_ssh = self._qemu_self_address()
        user = os.environ.get("USER", "user")
        print(f"\n  {t('No display here; run this on YOUR workstation:')}")
        print(
            f"\n    virt-viewer -c qemu+ssh://{user}@{host}/system {domain}\n"
        )
        if not from_ssh:
            print(f"  ⚠ {t('Not in an SSH session: check the host address.')}")
        print(f"  {t('A ~/.ssh/config alias works there too.')}")
        print(f"  {t('It builds its own tunnel; no ssh -L to keep open.')}")
        print(
            f"  {t('Missing? Install virt-viewer:')} apt / dnf / pacman"
            " / zypper"
        )

    def _qemu_console_tunnel(self, name, src):
        """Tunnel vers l'ÉCRAN QEMU d'une VM, pas vers un serveur de l'invité.

        Les deux autres choix du menu supposent un service DANS l'invité —
        xrdp, TigerVNC — donc une session de bureau déjà ouverte et un mot de
        passe posé. La console de l'hyperviseur, elle, existe dès l'amorçage et
        ne demande rien à l'invité : c'est ce que montre virt-manager.

        Le port n'est pas devinable : libvirt l'attribue au démarrage. On le
        lit donc, et l'absence de port est un diagnostic à part entière — avec
        « listen=none » QEMU n'ouvre AUCUN socket, et aucun tunnel n'y peut
        rien tant que le domaine n'est pas redéfini.
        """
        if src != "ssh_config":
            jump, domain = "", name
        else:
            # L'écran VNC appartient à QEMU, donc à l'HYPERVISEUR — pas à
            # l'invité. Tunneler vers la VM elle-même ne trouve rien : le
            # socket n'existe pas de ce côté. Vécu, et c'est aussi ce qui
            # rendait le premier jet de ce menu inutile hors machine locale.
            #
            # L'hyperviseur est le ProxyJump déclaré dans ssh_config, lu par
            # « ssh -G » : c'est la seule lecture qui couvre toutes les formes
            # d'écriture (Host, Match, wildcards, includes). Le nom composé
            # « saut+vm » n'est qu'un libellé, il ne fait pas autorité.
            jump = self._ssh_proxyjump(name)
            domain = name.rsplit("+", 1)[-1]
            if not jump:
                print(
                    f"\n  ⚠ {t('No ProxyJump for this host in ~/.ssh/config.')}"
                )
                print(f"  {t('Cannot tell which machine runs its QEMU.')}")
                return
        port = self._qemu_vnc_port(domain, jump)
        # Les commandes de réparation se lancent SUR l'hyperviseur : le préfixe
        # évite de les copier sur la mauvaise machine, l'erreur naturelle ici.
        pre = f"ssh {jump} " if jump else ""
        if not port and self._hypervisor_is_proxmox(jump):
            self._pve_console_hint(jump, domain)
            return
        if not port:
            print(f"\n  ⚠ {t('This VM exposes no VNC port.')}")
            print(f"  {t('Its display is likely spice with listen=none:')}")
            print(
                f"    {pre}sudo virsh dumpxml {domain} | grep -A2 '<graphics'"
            )
            print(
                f"  {t('To open it on the loopback (VM restart required):')}"
            )
            print(f"    {pre}sudo virsh destroy {domain}")
            print(
                f"    {pre}sudo virsh edit {domain}   # <graphics type='vnc'"
                " port='-1' autoport='yes' listen='127.0.0.1'/>"
            )
            print(f"    {pre}sudo virsh start {domain}")
            print(f"\n  {t('New VMs get this by default; see deploy_qemu.')}")
            return
        if jump:
            target = jump
        else:
            host, from_ssh = self._qemu_self_address()
            user = os.environ.get("USER", "user")
            if not from_ssh:
                print(
                    f"  ⚠ {t('Not in an SSH session: check the host address.')}"
                )
            target = f"{user}@{host}"
        print(f"\n  {t('Run this on YOUR workstation:')}")
        print(f"\n    ssh -N -L {port}:127.0.0.1:{port} {target}\n")
        if jump:
            print(
                f"  {t('Target is the hypervisor')} ({jump}), "
                f"{t('not the VM: the socket is QEMU-side.')}"
            )
        print(f"  {t('then point your VNC client at')} localhost:{port}")
        print(f"  {t('The tunnel stays open as long as that ssh runs.')}")

    @staticmethod
    def _hypervisor_is_proxmox(jump) -> bool:
        """Cet hyperviseur est-il un Proxmox VE ?

        La question se pose quand « virsh vncdisplay » n'a rien rendu : un
        Proxmox n'a PAS de libvirt, donc l'absence de port n'y veut pas dire
        « écran fermé », elle veut dire « mauvaise question ». Sans cette
        distinction, on conseillait « virsh edit » sur une machine où la
        commande n'existe pas.

        « qm » et non « pveversion » : c'est le binaire dont on parle ensuite.
        """
        if not jump:
            # Un Proxmox n'est jamais l'hôte local ici : ce menu tourne sur le
            # poste de travail, et un Proxmox se joint par ssh.
            return False
        try:
            res = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", jump, "command -v qm"],
                capture_output=True,
                text=True,
                timeout=25,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return res.returncode == 0 and bool(res.stdout.strip())

    def _pve_console_hint(self, jump, domain) -> None:
        """Les deux vraies façons de voir l'écran d'une VM Proxmox.

        Proxmox ne sert pas son écran par un port VNC qu'on tunnelise : il le
        sert par un TICKET, sur son interface web (« qm vncproxy » ouvre un
        websocket authentifié, pas un socket qu'on relaie). Un « ssh -L » vers
        un port VNC n'y trouve rien, quel que soit le port."""
        print(
            f"\n  ⚠ {t('This hypervisor is Proxmox VE: it has no libvirt.')}"
        )
        print(f"  {t('Its screen is served by a ticket, not by a VNC port.')}")
        print(f"\n  {t('Two ways in:')}")
        print(f"  • {t('the serial console, VMID from the Proxmox menu:')}")
        print(f"      ssh {jump} sudo qm list   # {domain}")
        print(f"      ssh -t {jump} sudo qm terminal <VMID>")
        print(f"  • {t('the web interface, through a tunnel:')}")
        print(f"      ssh -N -L 8006:127.0.0.1:8006 {jump}")
        print(f"      https://localhost:8006  →  {t('VM')} → Console")
        print(
            f"\n  {t('TODO > Execute > Deploy > Proxmox VE does the first.')}"
        )

    @staticmethod
    def _qemu_vnc_port(domain, jump=""):
        """Port VNC réel d'un domaine, localement ou sur un hyperviseur distant.

        Il ne se devine pas : libvirt l'attribue au démarrage. « virsh
        vncdisplay » rend « 127.0.0.1:0 », où le suffixe est le NUMÉRO d'écran
        — 0 vaut 5900, 1 vaut 5901.

        Sans sudo d'abord : l'appartenance au groupe libvirt suffit souvent, et
        « sudo -n » distant échouerait sur l'absence de TTY. On ne retombe sur
        « sudo -n » que si le premier essai n'a rien donné.
        """
        base = ["virsh", "--connect", "qemu:///system", "vncdisplay", domain]
        for argv in (base, ["sudo", "-n"] + base):
            cmd = (
                (["ssh", "-o", "BatchMode=yes", jump] + argv) if jump else argv
            )
            try:
                res = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=25
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if res.returncode != 0:
                continue
            disp = res.stdout.strip().rsplit(":", 1)
            if len(disp) == 2 and disp[1].isdigit():
                return 5900 + int(disp[1])
        return 0

    def _qemu_ssh_config_menu(self):
        """Écrit les entrées ~/.ssh/config du parc QEMU.

        Un seul flux : les deux anciennes entrées (« VM locales » et
        « imbriquées, récursif ») écrivaient la même chose et ne différaient
        que par la profondeur — c'est donc une question, pas un menu."""
        print(f"🔑 {t('SSH configuration for QEMU VMs')}")
        roots = self._qemu_ssh_pick_roots()
        if not roots:
            return
        raw = input(
            f"{t('Depth (1 = these machines only, default:')}"
            f" {self._QEMU_SSH_DEPTH}): "
        ).strip()
        try:
            max_depth = max(1, int(raw)) if raw else self._QEMU_SSH_DEPTH
        except ValueError:
            max_depth = self._QEMU_SSH_DEPTH
        # Aucune question sur la clé ici : tant que rien n'a échoué, elle
        # serait prématurée. Elle est posée à la première identité refusée.
        self._qemu_ssh_walk(roots, max_depth)

    def _qemu_pick_domains(self):
        """Fait choisir des VM parmi celles définies. Vide = toutes."""
        names = self._qemu_list_domains()
        if not names:
            print(t("No VM found."))
            return []
        for i, name in enumerate(names, 1):
            print(f"  [{i}] {name}")
        raw = input(
            t("Which VMs? (numbers, comma-separated; blank = all): ")
        ).strip()
        if not raw:
            return names
        chosen = self._parse_index_selection(raw, names)
        return chosen or names

    def _qemu_ssh_retry_with_key(self, alias, message):
        """ssh a refusé l'identité : proposer la clé, puis resonder une fois.

        Posée ICI et pas au début : tant que rien n'échoue, la question est
        prématurée — et si l'accès passe déjà par une clé d'agent ou un autre
        mécanisme, elle n'aurait jamais lieu d'être."""
        print(f"\n  🔒 {alias}: {t('SSH refused the identity.')}")
        print(f"     {message}")
        pub = self._qemu_default_ssh_key()
        if pub:
            print(f"     {t('Existing key:')} {pub}")
            question = t("Deploy it on this host (ssh-copy-id)? (Y/n): ")
        else:
            print(f"     {t('No SSH key in ~/.ssh.')}")
            question = t("Create one and deploy it? (Y/n): ")
        if not self._is_yes_default_yes(input(f"     {question}")):
            return "auth", message
        if not self._ssh_ensure_key():
            return "auth", message
        self._ssh_deploy_keys([alias])
        return self._qemu_ssh_probe_remote(alias)

    def _qemu_ssh_probe_remote(self, alias):
        """Sonde `alias`. Renvoie (statut, données) :

            ("ok", [(nom, ip)])   libvirt répond, voici ses VM
            ("nolibvirt", [])     joignable, mais pas de QEMU
            ("auth", message)     ssh a refusé l'identité
            ("net", message)      injoignable (éteint, DNS, port fermé…)

        Passe par « ssh <alias> », donc par le bloc ~/.ssh/config qu'on vient
        d'écrire : le ProxyJump du parent s'applique tout seul et la même
        sonde marche à n'importe quelle profondeur.

        « libvirt présent » et « a des VM » sont deux choses distinctes : une
        machine avec QEMU mais sans VM mérite quand même sa connexion
        virt-manager, une machine sans QEMU n'en veut aucune."""
        cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            alias,
            self._QEMU_SSH_PROBE,
        ]
        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True, timeout=90
            )
        except subprocess.TimeoutExpired:
            return "net", t("timed out")
        except (OSError, subprocess.SubprocessError) as exc:
            return "net", str(exc)
        if res.returncode != 0:
            detail = (res.stderr or "").strip().splitlines()
            message = detail[-1] if detail else f"exit {res.returncode}"
            return self._ssh_error_kind(res.stderr), message
        libvirt = "no"
        found = []
        for line in res.stdout.splitlines():
            parts = line.strip().split("\t")
            if len(parts) != 2 or not parts[0]:
                continue
            if parts[0] == "LIBVIRT":
                libvirt = parts[1].strip()
                continue
            found.append((parts[0], parts[1].strip()))
        if libvirt == "yes":
            return "ok", found
        # « denied » : virsh est installé mais refuse de répondre — sudo
        # interactif, ou utilisateur hors du groupe libvirt. Le confondre avec
        # « pas de QEMU » envoyait chercher un problème qui n'existe pas.
        return ("denied" if libvirt == "denied" else "nolibvirt"), found

    def _qemu_ssh_walk(self, roots, max_depth):
        """Descend le parc depuis `roots` et écrit un ProxyJump par niveau.

        Une VM du profil « Déploiement » héberge elle-même des VM : celles-ci
        n'ont pas d'IP joignable depuis l'hôte, seulement depuis leur parent.
        ProxyJump enchaîne les sauts, et la chaîne se construit d'elle-même
        puisque le parent est déjà dans ~/.ssh/config quand on écrit l'enfant.

        Une racine sans IP est un hôte DÉJÀ décrit dans ~/.ssh/config : son
        adresse y est, on ne la réécrit pas, on part simplement de lui.
        """
        # Clé existante s'il y en a une : elle va dans IdentityFile. Si une
        # clé est créée plus tard, en réaction à un refus, les entrées
        # suivantes la reprendront.
        identity = self._ssh_private_key(self._qemu_default_ssh_key())

        entries = []  # un enregistrement par machine écrite
        taken = set()  # tous les noms d'hôte déjà attribués
        chain_of = {}  # alias -> nom chaîné « parent+enfant »
        user_of = {}  # alias -> compte de connexion
        hosts_libvirt = []  # machines qui font tourner QEMU
        frontier = []
        for root in roots:
            alias, ip = root["alias"], root.get("ip")
            # Le compte vient de ~/.ssh/config quand il y est déclaré : un
            # hôte adopté n'est pas forcément une VM ERPLibre.
            user_of[alias] = root.get("user") or self.QEMU_VM_USER
            if ip:
                self._write_ssh_config_entry(
                    alias, user_of[alias], ip, identity_file=identity
                )
                entries.append(
                    {
                        "names": [alias],
                        "ip": ip,
                        "parent": None,
                        "user": user_of[alias],
                    }
                )
            taken.add(alias)
            chain_of[alias] = alias
            frontier.append(alias)

        # `max_depth` compte les NIVEAUX de machines, racines comprises : une
        # profondeur de 1 s'arrête donc ici, sans rien sonder.
        for depth in range(1, max_depth):
            if not frontier:
                break
            print(
                f"\n🔎 {t('Level')} {depth + 1} — "
                f"{len(frontier)} {t('machines to probe')}"
            )
            next_frontier = []
            for parent in frontier:
                status, found = self._qemu_ssh_probe_remote(parent)
                if status == "auth":
                    # C'EST ici qu'une clé manquante se manifeste, pas avant :
                    # on ne parle d'identité qu'une fois l'identité refusée.
                    status, found = self._qemu_ssh_retry_with_key(
                        parent, found
                    )
                    # Une clé a pu naître de cet échange : les entrées
                    # écrites ensuite doivent la nommer.
                    identity = (
                        self._ssh_private_key(self._qemu_default_ssh_key())
                        or identity
                    )
                if status in ("auth", "net"):
                    label = (
                        t("access refused")
                        if status == "auth"
                        else t("unreachable")
                    )
                    print(f"  ⏭  {parent}: {label} — {found}")
                    continue
                if status == "denied":
                    # virsh est là mais ne répond pas : c'est un DROIT qui
                    # manque, pas un logiciel. Le dire, et donner le geste.
                    print(
                        f"  🔒 {parent}: "
                        f"{t('virsh present but not accessible')}"
                    )
                    print(
                        f"       {t('Add the user to the libvirt group there:')}"
                    )
                    continue
                if status != "ok":
                    print(f"  ·  {parent}: {t('no QEMU/libvirt here')}")
                    continue
                # Une machine avec QEMU vaut sa connexion virt-manager, même
                # sans VM : c'est là qu'on pourra en créer.
                hosts_libvirt.append(parent)
                if not found:
                    print(f"  ·  {parent}: {t('QEMU present, no VM')}")
                    continue
                for child, ip in found:
                    if not ip:
                        print(f"  ⏭  {parent} › {child}: {t('no IP')}")
                        continue
                    # UN SEUL nom, le nom CHAÎNÉ : il dit où vit la VM et ne
                    # peut heurter aucune autre machine. Y ajouter le nom
                    # court ne ferait que répéter la fin de la chaîne.
                    chain = f"{chain_of[parent]}+{child}"
                    if chain in taken:
                        continue  # déjà vu (cycle)
                    # L'invitée hérite du compte de son parent : elle a été
                    # créée par lui, avec la même convention.
                    user_of[chain] = user_of[parent]
                    self._write_ssh_config_entry(
                        chain,
                        user_of[chain],
                        ip,
                        proxy_jump=parent,
                        identity_file=identity,
                    )
                    entries.append(
                        {
                            "names": [chain],
                            "ip": ip,
                            "parent": parent,
                            "user": user_of[chain],
                        }
                    )
                    taken.add(chain)
                    chain_of[chain] = chain
                    next_frontier.append(chain)
            frontier = next_frontier

        print(f"\n── {t('SSH hosts written')} ──")
        for item in entries:
            via = f"  ({t('via')} {item['parent']})" if item["parent"] else ""
            print(
                f"  ssh {' '.join(item['names']):<40}"
                f" {item['user']}@{item['ip']}{via}"
            )

        # Les machines qui hébergent QEMU sont celles qui valent d'être
        # ajoutées à virt-manager : c'est de là qu'on pilote leurs invitées.
        # On y présente le nom CHAÎNÉ, pour que l'imbrication se lise aussi
        # dans l'interface graphique et pas seulement dans ~/.ssh/config.
        self._virt_manager_offer(
            [
                (chain_of.get(alias, alias), user_of.get(alias, ""))
                for alias in hosts_libvirt
            ]
        )
