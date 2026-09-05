#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le cache des VM QEMU : poser, constater, conduire, comprendre, mesurer.

Cinq gestes qui ne se ressemblent pas. L'installation touche au système et
demande sudo ; le diagnostic ne fait que LIRE ; conduire le service allume et
éteint ; le guide n'exécute rien ; les tests créent de vraies machines. Les
mêler dans une seule entrée obligeait à lancer une installation pour savoir
si le cache tournait.

Le service a son propre sous-menu parce que l'ARRÊTER est le seul moyen de
désactiver le cache : l'unité retire ses règles en partant. Retirer l'autorité
d'une VM ne la soustrait pas au détournement, cela lui fait seulement refuser
un certificat qu'elle ne reconnaît plus.

Le diagnostic existe pour une panne précise, et elle est silencieuse : le
réseau libvirt « default » ne sert pas toujours 192.168.122.0/24 — il est
déplacé sur un /24 libre dès que ce préfixe entre en collision, ce qui est le
cas de tout orchestrateur qui est lui-même une VM. Des règles posées sur
l'autre préfixe existent bel et bien dans le noyau, l'installation réussit,
et aucune VM ne traverse le cache. Rien ne le dit. Comparer les deux
préfixes est donc le premier contrôle, pas le dernier.
"""

import json
import os
import re
import shlex
import subprocess

import click

from script.todo.todo_i18n import t

# Ce que l'installateur pose. Ces chemins sont comparés à ceux du script par
# un test : le menu qui chercherait ailleurs annoncerait un cache absent.
CACHE_BIN = "/usr/local/bin/erplibre_go_qemu_cache"
CACHE_CA = "/var/lib/erplibre_go_qemu_cache/ca.crt"
CACHE_SERVICE = "erplibre-go-qemu-cache.service"
CACHE_CONF = "/etc/erplibre_go_qemu_cache/env"
CACHE_TABLE = "erplibre_qemu_cache"
CACHE_BYPASS = "/etc/erplibre_go_qemu_cache/bypass"
CACHE_SET = "bypass"
LONGTEST = "long_test/qemu_cache.py"


class QemuCacheMenuMixin:
    # ------------------------------------------------------------------
    # Lectures : aucune ne modifie quoi que ce soit
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_lire(cmd, delai=15):
        """Sortie d'une commande, ou "". Ne lève jamais : un diagnostic qui
        s'interrompt sur sa première mesure absente ne diagnostique rien."""
        try:
            p = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=delai,
            )
            return (p.stdout or "") + (p.stderr or "")
        except (OSError, subprocess.SubprocessError):
            return ""

    @classmethod
    def _cache_prefixe_regles(cls):
        """Les trois premiers octets que les règles détournent, ou ""."""
        vu = cls._cache_lire(f"sudo -n nft list table ip {CACHE_TABLE}")
        m = re.search(r"saddr (\d+\.\d+\.\d+)\.", vu)
        return m.group(1) if m else ""

    @classmethod
    def _cache_prefixe_libvirt(cls):
        """Les trois premiers octets que libvirt sert vraiment, ou ""."""
        vu = cls._cache_lire("virsh -c qemu:///system net-dumpxml default")
        m = re.search(r"address='(\d+\.\d+\.\d+)\.", vu)
        return m.group(1) if m else ""

    @classmethod
    def _cache_actif(cls):
        return (
            "active"
            in cls._cache_lire(f"systemctl is-active {CACHE_SERVICE}").split(
                "\n"
            )[0]
        )

    @staticmethod
    def _cache_journal():
        """Chemin du journal d'accès, lu dans la configuration du service."""
        try:
            with open(CACHE_CONF, encoding="utf-8") as fh:
                for ligne in fh:
                    if ligne.startswith("EL_ACCESS_LOG="):
                        return ligne.split("=", 1)[1].strip()
        except OSError:
            pass
        return ""

    @classmethod
    def _cache_compte_issues(cls):
        """Ce que le cache a fait, par issue. Le journal EST la mesure."""
        chemin = cls._cache_journal()
        compte = {}
        if not chemin or not os.path.exists(chemin):
            return compte
        try:
            with open(chemin, encoding="utf-8", errors="replace") as fh:
                for ligne in fh:
                    try:
                        issue = json.loads(ligne).get("outcome", "?")
                    except ValueError:
                        continue
                    compte[issue] = compte.get(issue, 0) + 1
        except OSError:
            pass
        return compte

    # ------------------------------------------------------------------
    # Le menu
    # ------------------------------------------------------------------

    def prompt_execute_qemu_cache(self):
        print(f"📦 {t('QEMU download cache for local VMs')}")
        choices = [
            {"prompt_description": t("Cache - Install or reinstall")},
            {"prompt_description": t("Cache - Diagnose: does it serve?")},
            {"prompt_description": t("Cache - Service state")},
            {"prompt_description": t("Cache - VMs kept out of the cache")},
            {"prompt_description": t("Cache - Guide: how it works")},
            {"prompt_description": t("Cache - Tests and performance report")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._deploy_qemu_cache()
            elif status == "2":
                self._cache_diagnostic()
            elif status == "3":
                self._cache_service()
            elif status == "4":
                self._cache_exceptions()
            elif status == "5":
                self._cache_guide()
            elif status == "6":
                self._cache_tests()
            else:
                print(t("Command not found !"))

    # ------------------------------------------------------------------
    # [2] Diagnostic
    # ------------------------------------------------------------------

    def _cache_diagnostic(self):
        """Constate, ne répare pas. Chaque ligne est une lecture."""
        print(f"\n{t('Diagnosis of the QEMU download cache')}\n")

        actif = self._cache_actif()
        print(
            f"  {'✓' if actif else '✗'} {t('Service:')} "
            f"{t('Service is running') if actif else t('Service is stopped')}"
        )
        if not os.path.isfile(CACHE_BIN):
            print(f"  ✗ {t('Not installed:')} {CACHE_BIN}")
            print(f"\n  {t('Install it from entry 1 of this menu.')}\n")
            return

        # LE contrôle. Deux préfixes qui divergent, et le cache ne sert
        # personne pendant que tout paraît réussi.
        regles = self._cache_prefixe_regles()
        libvirt = self._cache_prefixe_libvirt()
        if regles and regles == libvirt:
            print(f"  ✓ {t('Redirection:')} {libvirt}.x → {t('the cache')}")
        elif not regles:
            print(f"  ✗ {t('No redirection rule is posted')}")
        else:
            print(
                f"  ✗ {t('MISMATCH — rules on')} {regles}.x, "
                f"{t('libvirt serves')} {libvirt or '?'}.x"
            )
            print(f"    {t('Reinstall: the cache reads libvirt by itself.')}")

        print(f"  · {t('Authority:')} {CACHE_CA}")
        for ligne in self._cache_lire(f"{CACHE_BIN} --status", delai=60).split(
            "\n"
        )[:4]:
            if ligne.strip():
                print(f"  · {ligne.strip()}")

        # Une VM exceptée ne traverse pas le cache, et c'est voulu ; une
        # exception dont la VM n'existe plus ne l'est pas, et elle est
        # invisible partout ailleurs — la machine qui hérite de la MAC
        # télécharge normalement, le journal reste seulement muet sur elle.
        exceptions = self._cache_bypass_lire()
        if exceptions:
            orphelines = self._cache_bypass_orphelines(exceptions)
            marque = "⚠" if orphelines else "·"
            print(
                f"  {marque} {t('Exceptions:')} {len(exceptions)}"
                f" ({len(orphelines)} {t('with no VM left')})"
            )
            if orphelines:
                print(f"    {t('Remove them from entry 4 of this menu.')}")

        compte = self._cache_compte_issues()
        if compte:
            print(f"\n  {t('What the cache has done:')}")
            for issue in ("hit", "stored", "stale", "offline-miss", "fetched"):
                if issue in compte:
                    print(f"    {issue:<14} {compte[issue]}")
        else:
            print(
                f"\n  ⚠ {t('The access log is empty: nothing has gone through the cache.')}"
            )
            print(
                f"    {t('A VM that installs while this stays at zero does not use it.')}"
            )
        print()

    # ------------------------------------------------------------------
    # [3] État du service
    # ------------------------------------------------------------------

    def _cache_systemctl(self, verbe, montrer=True):
        """Un geste systemd, la commande annoncée avant d'être lancée.

        Arrêter n'éteint pas seulement le service : l'unité retire ses règles
        en partant, donc plus aucune VM n'est détournée. C'est ce qui fait de
        « stop » le seul moyen vrai de désactiver le cache, et c'est dit à
        l'écran plutôt que dans une note qu'on ne lit pas.
        """
        cmd = f"sudo systemctl {verbe} {CACHE_SERVICE}"
        print(f"\n{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)
        if montrer:
            print(f"\n  {t('Service:')} {self._cache_etat_court()}")

    def _cache_etat_court(self):
        """« actif, au démarrage » et ce qu'il en manque, en une ligne."""
        actif = self._cache_actif()
        # « is-enabled » rend un mot par ligne : enabled, enabled-runtime,
        # disabled, static, masked. Comparer le MOT et non l'y chercher —
        # une sous-chaîne ferait passer « masked » pour un service au boot le
        # jour où systemd ajoute un état composé.
        au_boot = self._cache_lire(
            f"systemctl is-enabled {CACHE_SERVICE}"
        ).split("\n")[0].strip() in ("enabled", "enabled-runtime")
        return (
            f"{t('Service is running') if actif else t('Service is stopped')}"
            f", {t('starts at boot') if au_boot else t('not at boot')}"
        )

    def _cache_service(self):
        print(f"\n⚙ {t('State of the cache service')}")
        print(f"  {self._cache_etat_court()}")
        print(
            f"  {t('Stopping it removes the rules: no VM is redirected.')}\n"
        )
        choices = [
            {"prompt_description": t("Service - Start (start)")},
            {"prompt_description": t("Service - Start at boot (enable)")},
            {
                "prompt_description": t(
                    "Service - Do not start at boot (disable)"
                )
            },
            {"prompt_description": t("Service - Stop (stop)")},
            {"prompt_description": t("Service - Detailed state (status)")},
            {"prompt_description": t("Service - Logs (log)")},
        ]
        verbes = {"1": "start", "2": "enable", "3": "disable", "4": "stop"}
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            if status in verbes:
                self._cache_systemctl(verbes[status])
            elif status == "5":
                self._cache_systemctl("status --no-pager", montrer=False)
            elif status == "6":
                self._cache_journal_service()
            else:
                print(t("Command not found !"))

    def _cache_journal_service(self):
        """Deux journaux, et ils ne disent pas la même chose.

        Celui de systemd porte ce que le service dit de lui-même — démarrages,
        erreurs, hôtes retenus en tunnel. Le journal d'ACCÈS porte ce qu'il a
        servi, une ligne par requête : c'est celui qui prouve qu'une VM le
        traverse.
        """
        cmd = f"sudo journalctl -u {CACHE_SERVICE} -n 40 --no-pager"
        print(f"\n{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

        chemin = self._cache_journal()
        if not chemin or not os.path.exists(chemin):
            return
        print(f"\n  {t('Access log, last requests:')} {chemin}")
        try:
            with open(chemin, encoding="utf-8", errors="replace") as fh:
                lignes = fh.readlines()[-10:]
        except OSError:
            return
        for ligne in lignes:
            try:
                d = json.loads(ligne)
            except ValueError:
                continue
            print(
                f"    {d.get('outcome', '?'):<13}"
                f"{str(d.get('url', '')).rsplit('/', 1)[-1][:58]}"
            )

    # ------------------------------------------------------------------
    # [4] Exceptions : les VM soustraites au détournement
    # ------------------------------------------------------------------

    @classmethod
    def _cache_bypass_lire(cls):
        """Les exceptions posées, en couples (MAC, nom de VM).

        Lues par le BINAIRE et non par ce fichier : lui seul sait normaliser
        une adresse et sauter une ligne fautive, et une seconde lecture écrite
        ici dériverait de la sienne.
        """
        if not os.path.isfile(CACHE_BIN):
            return []
        sortie = cls._cache_lire(
            f"{CACHE_BIN} --bypass-list --bypass-file {CACHE_BYPASS}"
        )
        out = []
        for ligne in sortie.split("\n"):
            champs = ligne.split(None, 1)
            if champs and ":" in champs[0]:
                out.append((champs[0], champs[1] if len(champs) > 1 else ""))
        return out

    @staticmethod
    def _cache_domaines():
        """Les noms de domaine que libvirt connaît, VM éteintes comprises."""
        sortie = QemuCacheMenuMixin._cache_lire(
            "virsh -c qemu:///system list --all --name"
        )
        return {l.strip() for l in sortie.split("\n") if l.strip()}

    @classmethod
    def _cache_bypass_orphelines(cls, entrees=None):
        """Les exceptions dont la VM n'existe plus.

        C'est LE danger de cette liste. Une adresse MAC se réattribue : une
        exception laissée derrière une VM détruite soustrairait au cache une
        machine neuve qui hériterait de l'adresse, sans que personne l'ait
        demandé et sans que rien ne le dise. Une entrée sans nom ne peut pas
        être jugée — elle a été posée à la main — et n'est jamais orpheline.
        """
        vivants = cls._cache_domaines()
        return [
            (mac, nom)
            for mac, nom in (
                entrees if entrees is not None else cls._cache_bypass_lire()
            )
            if nom and nom not in vivants
        ]

    def _cache_bypass_retirer(self, mac):
        cmd = bypass_retrait_cmd(mac)
        print(f"\n{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def _cache_exceptions(self):
        print(f"\n🎫 {t('VMs kept out of the download cache')}\n")
        if not os.path.isfile(CACHE_BIN):
            print(f"  ✗ {t('Not installed:')} {CACHE_BIN}\n")
            return
        entrees = self._cache_bypass_lire()
        if not entrees:
            print(f"  {t('No exception: every VM goes through the cache.')}")
            print(f"  {t('Tick the box when deploying to add one.')}\n")
            return

        orphelines = dict(self._cache_bypass_orphelines(entrees))
        print(f"  {'MAC':<20}{t('VM')}")
        print("  " + "─" * 52)
        for mac, nom in entrees:
            marque = " ⚠ " + t("VM gone") if mac in orphelines else ""
            print(f"  {mac:<20}{nom or '—'}{marque}")
        print()
        if orphelines:
            print(f"  ⚠ {t('A freed MAC gets reused: such an entry would')}")
            print(f"    {t('quietly keep a NEW VM out of the cache.')}\n")

        choices = [
            {"prompt_description": t("Exceptions - Remove the stale ones")},
            {"prompt_description": t("Exceptions - Remove one by its MAC")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            if status == "1":
                if not orphelines:
                    print(t("Nothing is stale."))
                    continue
                for mac in orphelines:
                    self._cache_bypass_retirer(mac)
                return True
            if status == "2":
                mac = click.prompt(t("MAC to give back to the cache")).strip()
                if mac:
                    self._cache_bypass_retirer(mac)
                return True
            print(t("Command not found !"))

    # ------------------------------------------------------------------
    # [5] Guide
    # ------------------------------------------------------------------

    def _cache_guide(self):
        """N'exécute rien. Dit ce qui n'est pas devinable en lisant l'écran."""
        for ligne in (
            "",
            t("How the QEMU download cache works"),
            "",
            t("  Two VMs of the same distribution pull the same packages."),
            t(
                "  The cache keeps what comes down and serves the copy to the next."
            ),
            "",
            f"  {t('What is served from disk')}",
            t(
                "    A package file: its name carries its version, so it never changes."
            ),
            t(
                "    The host name is ignored: a rotating mirror list still hits."
            ),
            "",
            f"  {t('What is always taken from upstream')}",
            t(
                "    A repository index: it names the versions that exist right now."
            ),
            t(
                "    Serving a stale one makes an install fail on a withdrawn package."
            ),
            t(
                "    It is stored anyway, and only comes back out when upstream is mute."
            ),
            "",
            f"  {t('Where things live')}",
            f"    {t('Objects:')}   /var/cache/erplibre_go_qemu_cache",
            f"    {t('Authority:')} {CACHE_CA}",
            f"    {t('Settings:')}  {CACHE_CONF}",
            f"    {t('Access log:')} {self._cache_journal() or '—'}",
            "",
            f"  {t('No eviction is written')}",
            t("    This cache never shrinks by itself, and it lives on the"),
            t("    orchestrator's disk. Watch it with the diagnosis entry."),
            "",
            f"  {t('Turning it off')}",
            t("    Interception is transparent and covers the whole bridge:"),
            t(
                "    a VM cannot opt out from the inside. Omitting the authority"
            ),
            t(
                "    does not bypass anything — the VM is redirected all the same"
            ),
            t("    and fails on « self-signed certificate in chain »."),
            "",
            t("    For ONE VM: tick « keep this VM out of the cache » when"),
            t(
                "    deploying, or pass --cache-bypass. Its MAC address is fixed"
            ),
            t(
                "    before creation and an exception is posted on the host, so"
            ),
            t(
                "    nothing redirects it. Entry 4 lists them; an exception whose"
            ),
            t("    VM is gone must be removed, a freed MAC being reused."),
            "",
            t("    For EVERY VM: stop the service, entry 3 or"),
            f"      systemctl stop {CACHE_SERVICE}",
            t("    The rules leave with it, so no VM stays redirected."),
            "",
            f"  {t('Proxmox')}",
            t("    A Proxmox VM is born on a REMOTE host: its traffic never"),
            t(
                "    crosses this bridge, so this cache cannot serve it. Install the"
            ),
            t(
                "    cache ON that host instead — the script is generic, and Proxmox"
            ),
            t(
                "    is a Debian. Reserve: a bridge switched onto the LAN is only"
            ),
            t("    seen by the rules when br_netfilter is enabled."),
            "",
        ):
            print(ligne)

    # ------------------------------------------------------------------
    # [6] Tests
    # ------------------------------------------------------------------

    def _cache_tests(self):
        print(f"\n{t('Cache tests: real VMs, several minutes')}\n")
        choices = [
            {"prompt_description": t("Test - The plan only (dry-run)")},
            {"prompt_description": t("Test - Two VMs, measure the gain")},
            {"prompt_description": t("Test - Add the offline counter-proof")},
            {
                "prompt_description": t(
                    "Test - Control run: two VMs WITHOUT the cache"
                )
            },
            {"prompt_description": t("Test - Performance report")},
            {"prompt_description": t("Test - Undo the machines created")},
        ]
        args = {
            "1": "--dry-run",
            "2": "",
            "3": "--hors-ligne",
            "4": "--sans-cache",
            "5": "--rapport",
            "6": "--detruire",
        }
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            if status in args:
                # Chaque mode a ses propres machines : le dire AVANT, sans
                # quoi trois lots de VM apparaissent dans « virsh list » sans
                # qu'on sache lequel vient de quel essai.
                prefixe = {
                    "2": "el-cache-test",
                    "3": "el-offline-test",
                    "4": "el-no-cache-test",
                }.get(status)
                if prefixe:
                    print(f"  {t('Machines created:')} {prefixe}-1, -2…")
                if status == "4":
                    # Le témoin ne prouve rien sur le cache : il mesure ce que
                    # son absence coûte. Le dire évite qu'un résultat lent
                    # passe pour une panne.
                    print(
                        f"  {t('The control run measures what NOT caching costs.')}"
                    )
                self._longtest_run("qemu_cache.py", args[status])
            else:
                print(t("Command not found !"))


def bypass_retrait_cmd(mac):
    """La commande qui retire une exception du fichier ET du noyau.

    Les deux, parce qu'ils ne disent pas la même chose : le fichier est ce que
    le service reposera au prochain démarrage, l'ensemble du noyau est ce qui
    s'applique en ce moment. N'en faire qu'un laisse l'exception vivante
    jusqu'au redémarrage, ou la fait revenir après.
    """
    return (
        f"sudo {CACHE_BIN} --bypass-del {shlex.quote(mac)}"
        f" --bypass-file {CACHE_BYPASS} | sudo nft -f -"
    )


def bypass_menage(execute):
    """Retire les exceptions dont la VM n'existe plus. Rend leur nombre.

    Appelée après une suppression de VM. Sans ce ménage, une adresse MAC
    libérée puis réattribuée soustrairait au cache une machine neuve que
    personne n'a exceptée, et rien ne le dirait : ni la VM, qui télécharge
    normalement, ni le cache, dont le journal reste simplement muet à son
    sujet.

    Ne fait rien quand le cache n'est pas posé : il n'y a alors aucune liste.
    """
    if not os.path.isfile(CACHE_BIN):
        return 0
    orphelines = QemuCacheMenuMixin._cache_bypass_orphelines()
    for mac, _nom in orphelines:
        execute.exec_command_live(
            bypass_retrait_cmd(mac), source_erplibre=False
        )
    return len(orphelines)
