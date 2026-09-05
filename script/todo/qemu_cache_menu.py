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

    # Les trois essais, dans l'ordre où l'assistant les propose et les enchaîne.
    # Chaque entrée est (option de ligne de commande, libellé) : le NOM des
    # machines n'est pas écrit ici, il est demandé au script. Une seconde
    # fabrique du nom dériverait, et le menu annoncerait alors des VM qui ne
    # sont pas celles qui naissent — pire que de ne rien annoncer.
    _CACHE_ESSAIS = (
        ("", "The cache: two VMs, measure the gain"),
        ("--hors-ligne", "The offline counter-proof"),
        ("--sans-cache", "The control: two VMs WITHOUT the cache"),
    )

    _CACHE_CHARGES = (
        ("minimum", "Minimum: a batch of packages, minutes"),
        ("erplibre", "ERPLibre + Odoo 18: the real thing, hours"),
    )

    @staticmethod
    def _cache_module_test():
        """Le script du test long, chargé comme module.

        À l'appel et non au démarrage du menu : il tire le catalogue du
        déploiement, qui est lourd, et personne ne doit le payer pour afficher
        un menu qu'il ne visite pas.

        C'est LUI qui décide des systèmes offerts et du nom des machines. Le
        menu ne recopie ni l'un ni l'autre : ce qui est annoncé à l'écran est
        alors, par construction, ce qui va se passer.
        """
        import importlib.util

        chemin = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ),
            LONGTEST,
        )
        spec = importlib.util.spec_from_file_location(
            "qemu_cache_long", chemin
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @classmethod
    def _cache_systemes(cls):
        """Les systèmes que le TEST accepte, avec leur libellé."""
        module = cls._cache_module_test()
        return [
            (d, module.distro_label(d, module.DISTROS[d][1]))
            for d in sorted(module.systemes_mesurables())
        ]

    @classmethod
    def _cache_nom_des_machines(cls, options, distro, charge):
        """Le début du nom des VM de cet essai, demandé au script."""
        module = cls._cache_module_test()
        prefixe = {
            "--sans-cache": module.NOM_BASE_SANS_CACHE,
            "--hors-ligne": module.NOM_BASE_HORS_LIGNE,
        }.get(options, module.NOM_BASE)
        return module.nom_de_base(
            prefixe, distro, module.DISTROS[distro][1], charge
        )

    def _cache_choisir(self, titre, options):
        """Une question numérotée, le premier choix par défaut.

        Rend l'indice choisi, ou None si l'on renonce. Les trois questions de
        l'assistant partagent cette forme : une seule façon de répondre, et
        « 0 » ramène en arrière partout.
        """
        print(f"\n{titre}")
        for i, libelle in enumerate(options, 1):
            print(f"  [{i}] {libelle}")
        print(f"  [0] {t('Back')}")
        while True:
            reponse = click.prompt(t("Choice"), default="1").strip()
            if reponse == "0":
                return None
            if reponse.isdigit() and 1 <= int(reponse) <= len(options):
                return int(reponse) - 1
            print(t("Command not found !"))

    def _cache_assistant(self):
        """Trois questions, puis les essais choisis, l'un après l'autre.

        Une seule confirmation à la fin, et non une par essai : la question
        porte sur le LOT, et la reposer trois fois la rendrait machinale
        — c'est ce qui fait qu'on cesse de la lire.
        """
        essais = self._cache_choisir(
            t("Which test?"),
            [t(e[1]) for e in self._CACHE_ESSAIS]
            + [t("All three, one after another")],
        )
        if essais is None:
            return
        choisis = (
            list(self._CACHE_ESSAIS)
            if essais == len(self._CACHE_ESSAIS)
            else [self._CACHE_ESSAIS[essais]]
        )

        charge = self._cache_choisir(
            t("Which load?"), [t(c[1]) for c in self._CACHE_CHARGES]
        )
        if charge is None:
            return
        charge = self._CACHE_CHARGES[charge][0]

        systemes = self._cache_systemes()
        systeme = self._cache_choisir(
            t("Which system?"), [libelle for _d, libelle in systemes]
        )
        if systeme is None:
            return
        distro = systemes[systeme][0]

        commun = f"--distro {distro} --charge {charge}"
        print(f"\n{t('About to run, one after another:')}")
        for options, _libelle in choisis:
            ligne = f"{LONGTEST} {commun} {options}".rstrip()
            print(f"  {ligne}")
            nom = self._cache_nom_des_machines(options, distro, charge)
            print(f"    {t('Machines created:')} {nom}-1, -2…")
        if charge == "erplibre":
            # Des heures et non des minutes : une VM qui installe ERPLibre
            # entier n'a rien à voir avec le lot de paquets, et découvrir la
            # différence en cours de route est trop tard.
            print(
                f"\n  ⚠ {t('The real load takes hours per VM, not minutes.')}"
            )
        if not click.confirm(t("Run these long tests?")):
            return
        for options, _libelle in choisis:
            self._longtest_run(
                "qemu_cache.py", f"{commun} {options}".rstrip(), demander=False
            )

    def _cache_tests(self):
        print(f"\n{t('Cache tests: real VMs, several minutes')}\n")
        choices = [
            {"prompt_description": t("Test - Choose and run")},
            {"prompt_description": t("Test - The plan only (dry-run)")},
            {"prompt_description": t("Test - Performance report")},
            {"prompt_description": t("Test - Undo the machines created")},
        ]
        args = {"2": "--dry-run", "3": "--rapport", "4": "--detruire"}
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            if status == "1":
                self._cache_assistant()
            elif status in args:
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
