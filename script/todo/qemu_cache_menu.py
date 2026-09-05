#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le cache de téléchargement des VM QEMU : poser, constater, comprendre, mesurer.

Quatre gestes qui ne se ressemblent pas. L'installation touche au système et
demande sudo ; le diagnostic ne fait que LIRE ; le guide n'exécute rien ; les
tests créent de vraies machines. Les mêler dans une seule entrée obligeait à
lancer une installation pour savoir si le cache tournait.

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
                self._cache_guide()
            elif status == "4":
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
    # [3] Guide
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
            f"  {t('Turning it off for one VM')}",
            t(
                "    The deployment form carries a checkbox, offered only where the"
            ),
            t(
                "    host holds the authority. Unticked, the VM downloads directly."
            ),
            t("    On the command line, drop --cache-ca from deploy_qemu.py."),
            t("    To stop it for every VM: systemctl stop"),
            f"      {CACHE_SERVICE}",
            t(
                "    The rules leave with the service, so no VM stays redirected."
            ),
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
    # [4] Tests
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
