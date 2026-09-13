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
import time
from urllib.parse import urljoin, urlsplit

import click

from script.qemu import cache_offline
from script.todo.todo_i18n import t

# Ce que l'installateur pose. Ces chemins sont comparés à ceux du script par
# un test : le menu qui chercherait ailleurs annoncerait un cache absent.
CACHE_BIN = "/usr/local/bin/erplibre_go_qemu_cache"
CACHE_CA = "/var/lib/erplibre_go_qemu_cache/ca.crt"
CACHE_SERVICE = "erplibre-go-qemu-cache.service"
CACHE_CONF = "/etc/erplibre_go_qemu_cache/env"
CACHE_TABLE = "erplibre_qemu_cache"
CACHE_BYPASS = "/etc/erplibre_go_qemu_cache/bypass"
CACHE_MIROIR_GIT = "/var/cache/erplibre_go_qemu_cache/git"
CACHE_DIR = "/var/cache/erplibre_go_qemu_cache"
# L'installateur, tel qu'il se lance depuis un checkout ERPLibre. Le chemin
# reste RELATIF : il est imprimé pour une AUTRE machine, dont le répertoire
# de travail n'a aucune raison d'être celui d'ici.
INSTALLATEUR = "script/install/install_qemu_cache.sh"
# Le fichier que le mode en deux temps dépose dans le compte d'arrivée. Il
# pèse autant que le magasin — un cache ne contient que des paquets et des
# archives git, déjà comprimés — et la dernière commande le retire, le pic
# d'occupation valant sinon deux fois le magasin.
TRANSFERT_FICHIER = "erplibre_cache.tar.zst"
# La racine du dépôt, d'où se lance le lecteur du journal d'accès : le menu
# tourne depuis n'importe quel répertoire, et un chemin relatif n'y survit pas.
RACINE_DEPOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
# L'unité que l'installateur écrit. Remplir un miroir lui reprend
# l'environnement qu'elle donne à git, plutôt que d'en tenir une copie.
CACHE_UNITE = f"/etc/systemd/system/{CACHE_SERVICE}"

# Combler ce qui a manqué hors ligne : les jours de journal relus, le délai
# d'un rejeu, et les redirections suivies — autant que le cache en suit
# lui-même (maxRedirections) avant de renoncer.
JOURS_RECENTS = 7
REJEU_DELAI = 60
SAUTS_MAX = 5
REDIRECTIONS = (301, 302, 303, 307, 308)
# Les points de négociation git : la liste vit dans cache_offline, que le
# pré-vol du formulaire lit aussi ; un test la compare au Go.
GIT_NEGOCIATION = cache_offline.GIT_NEGOCIATION
# Les marques que les lectures de la coupure et du guet écrivent quand leur
# commande réussit. Une marque à nous plutôt qu'un message de nft, de sudo
# ou de systemctl : les leurs se traduisent selon la langue du compte.
NFT_LISIBLE = "erplibre-nft-lisible"
GUET_ACTIF = "erplibre-guet-actif"
# La source Go qui déclare les hôtes passés d'office en tunnel.
MITM_GO = os.path.join("script", "qemu_cache", "mitm.go")

# L'ordre d'affichage des issues du journal. Ce n'est PAS une liste de ce qui
# existe : tout ce que le journal porte est montré, ce qui n'est pas nommé ici
# venant à la fin. Une liste fermée avait déjà tu les deux issues les plus
# nombreuses, faute d'avoir été relue quand elles sont apparues.
ORDRE_ISSUES = (
    "hit",
    "mirror",
    "stored",
    "stale",
    "stored-status",
    "stale-status",
    "keep",
    "offline-miss",
    "fetched",
    "passthrough",
    "error",
)
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
    def _cache_amont_coupe(cls):
        """La coupure d'amont est-elle posée ? True, False, ou None quand on
        ne peut pas le savoir.

        Lue par « sudo -n », qui échoue plutôt que de demander un mot de
        passe. Sur un hôte où sudo en exige un, rien ne se lit : conclure
        « pas coupé » ferait rejouer sous la coupure, et chaque rejeu
        n'ajouterait qu'un manque. La marque NFT_LISIBLE n'est écrite que si
        nft a répondu ; sans elle, la réponse est None, et l'appelant
        tranche. None est faux en contexte booléen : un diagnostic ne crie
        pas à la coupure sur une lecture impossible.

        La coupure survit LÉGITIMEMENT au déploiement qui la pose tant que le
        guet tourne (`_cache_guet_actif`) : les installations sont
        détachées, et le guet ne la lève qu'à la fin de la dernière, 12 h au
        plus. Sans guet, elle ne survit qu'à ce qu'un « finally » ne rattrape
        pas : un processus tué net, une panne de courant. Le cache rend alors
        « 504 » à chaque VM, l'installation échoue sur « failed retrieving
        file … 504 » depuis TOUS les miroirs, et rien dans ce message ne
        parle d'une règle de pare-feu.
        """
        vu = cls._cache_lire(
            f"sudo -n nft list tables >/dev/null 2>&1 && echo {NFT_LISIBLE};"
            f" sudo -n nft list table inet {cache_offline.TABLE}"
        )
        if "meta skuid" in vu:
            return True
        return False if NFT_LISIBLE in vu.split() else None

    @classmethod
    def _cache_guet_actif(cls):
        """Le guet d'un déploiement hors ligne tourne-t-il ?

        Tant qu'il tourne, la coupure est tenue exprès, jusqu'à la fin de la
        dernière installation détachée. Sans sudo : l'état d'une unité se lit
        de tout compte. Passe par `_cache_lire`, qui ne lève jamais : une
        lecture impossible rend False.
        """
        vu = cls._cache_lire(
            f"{cache_offline.guet_actif_cmd()} && echo {GUET_ACTIF}"
        )
        return GUET_ACTIF in vu.split()

    @staticmethod
    def _cache_dire_coupure_tenue(marque, *entre):
        """Les lignes d'une coupure que le guet tient.

        Le geste donné ARRÊTE le guet, dont la levée retire la table. Retirer
        la table seule laisserait le guet tourner pour rien, et le
        déploiement hors ligne suivant serait refusé tant qu'il tourne.
        `entre` : lignes ajoutées avant le coût de la levée.
        """
        print(
            f"  {marque} {t('Upstream CUT by an offline deployment still installing,')}"
        )
        print(
            f"    {t('held until its last installation ends (12 h at most).')}"
        )
        for ligne in entre:
            print(f"    {ligne}")
        print(
            f"    {t('Lifting it now makes those installations finish online.')}"
        )
        print(
            f"    {t('Lift it now with:')} {cache_offline.lever_maintenant_cmd()}"
        )

    def _cache_diag_coupure(self):
        """Les lignes du diagnostic sur la coupure d'amont et le guet.

        Muet quand tout va bien — une ligne « amont branché » à chaque
        diagnostic n'apprendrait rien. Le guet d'abord : tant qu'il tourne,
        la coupure est tenue exprès, et donner le retrait de la table ferait
        finir en ligne les installations qui tournent encore. Une lecture de
        nft impossible (None) ne dément pas le guet. Un guet sans coupure est
        nommé : resté sans rien à lever, il ferait refuser le déploiement
        hors ligne suivant.
        """
        coupe = self._cache_amont_coupe()
        guet = self._cache_guet_actif()
        if guet and coupe is not False:
            self._cache_dire_coupure_tenue("⚠")
        elif guet:
            print(
                f"  ⚠ {t('The lift watcher still runs, with no cut left to lift.')}"
            )
            print(
                f"    {t('Stop it with:')} {cache_offline.lever_maintenant_cmd()}"
            )
        elif coupe:
            print(
                f"  ✗ {t('Upstream CUT: the cache can pull nothing from the internet')}"
            )
            print(f"    {t('Every VM then gets a 504 from every mirror.')}")
            print(
                f"    {t('The VMs have no direct way out either: only the host answers them.')}"
            )
            print(f"    {t('Lift it with:')} {cache_offline.restore_cmd()}")
        elif coupe is None:
            print(
                f"  · {t('Cannot tell whether the upstream is cut: reading nft needs a sudo password here.')}"
            )

    def _cache_combler_permis(self):
        """Le rejeu de l'entrée 9 peut-il partir ? Dit pourquoi sinon.

        Il faut le binaire et le service. Sous la coupure, un rejeu
        n'ajouterait que des manques au journal. Le guet est lu d'abord,
        sans sudo : tant qu'il tourne, la coupure est tenue exprès, et le
        geste donné l'arrête. Une coupure illisible — sudo exige un mot de
        passe — n'est pas prise pour une absence : le menu le dit et
        demande, non par défaut.
        """
        if not os.path.isfile(CACHE_BIN):
            print(f"  ✗ {t('Not installed:')} {CACHE_BIN}\n")
            return False
        if not self._cache_actif():
            print(f"  ✗ {t('Service:')} {t('Service is stopped')}")
            print(f"    {t('Start it from entry 3 of this menu.')}\n")
            return False
        if self._cache_guet_actif():
            self._cache_dire_coupure_tenue(
                "✗", t("A replay now would only record more misses.")
            )
            print()
            return False
        coupe = self._cache_amont_coupe()
        if coupe:
            print(
                f"  ✗ {t('Upstream CUT: the cache can pull nothing from the internet')}"
            )
            print(f"    {t('A replay now would only record more misses.')}")
            print(f"    {t('Lift it with:')} {cache_offline.restore_cmd()}\n")
            return False
        if coupe is None:
            print(
                f"  ⚠ {t('Cannot tell whether the upstream is cut: reading nft needs a sudo password here.')}"
            )
            print(
                f"    {t('Under the cut, a replay would only record more misses.')}"
            )
            if not click.confirm(t("Replay anyway?"), default=False):
                print()
                return False
        return True

    @classmethod
    def _cache_prefixe_libvirt(cls):
        """Les trois premiers octets que libvirt sert vraiment, ou ""."""
        vu = cls._cache_lire("virsh -c qemu:///system net-dumpxml default")
        m = re.search(r"address='(\d+\.\d+\.\d+)\.", vu)
        return m.group(1) if m else ""

    @classmethod
    def _cache_actif(cls):
        """Le service tourne-t-il ? La première ligne doit valoir
        « active » ENTIÈRE : « inactive » la contient, et un test
        d'inclusion lirait un service arrêté comme en marche."""
        vu = cls._cache_lire(f"systemctl is-active {CACHE_SERVICE}")
        return vu.split("\n")[0].strip() == "active"

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
            {"prompt_description": t("Cache - Git mirrors: fill them ahead")},
            {"prompt_description": t("Cache - Age and cleanup")},
            {"prompt_description": t("Cache - Guide: how it works")},
            {"prompt_description": t("Cache - Tests and performance report")},
            {"prompt_description": t("Cache - Fill what offline runs lacked")},
            {"prompt_description": t("Cache - Logs")},
            {"prompt_description": t("Cache - Copy it to another machine")},
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
                self._cache_miroir_git()
            elif status == "6":
                self._cache_age()
            elif status == "7":
                self._cache_guide()
            elif status == "8":
                self._cache_tests()
            elif status == "9":
                self._cache_combler()
            elif status == "10":
                self._cache_journaux()
            elif status == "11":
                self._cache_transfert()
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

        # Après le détournement : c'est la même classe de fait, une règle
        # posée sur l'hôte.
        self._cache_diag_coupure()

        print(f"  · {t('Authority:')} {CACHE_CA}")
        # Le répertoire du miroir est passé au relevé : sans lui, le binaire
        # ne mesure que les objets, et les dépôts git — qui pèsent bien plus —
        # disparaissent du seul endroit où l'on surveille la place.
        releve = self._cache_lire(
            f"{CACHE_BIN} --status --git-mirror-dir {CACHE_MIROIR_GIT}",
            delai=60,
        )
        for ligne in [
            l
            for l in releve.split("\n")
            if l.strip()
            and not l.startswith(("autorité", "empreinte", "exceptions"))
        ][:5]:
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

        # Par MACHINE, et pas seulement en tout. Un doute sur
        # l'accélération ne s'instruit pas sur un total : il faut pouvoir
        # séparer ce qu'une VM a tiré du réseau de ce qu'une autre a été
        # servie du disque, et le journal ne le disait pas.
        par_vm = self._cache_par_machine()
        if par_vm:
            print(f"\n  {t('What each VM pulled:')}")
            print(
                f"    {t('address'):<18}{t('from disk'):>12}"
                f"{t('upstream'):>12}"
            )
            for adresse, (disque, amont) in par_vm:
                print(
                    f"    {adresse:<18}{self._cache_humain(disque):>12}"
                    f"{self._cache_humain(amont):>12}"
                )

        compte = self._cache_compte_issues()
        if compte:
            print(f"\n  {t('What the cache has done:')}")
            # L'ordre est celui de la lecture — ce qui a servi d'abord, ce qui
            # est sorti ensuite. Mais TOUT ce que le journal porte est montré,
            # y compris une issue que cette liste ne connaît pas : la version
            # d'avant en écrivait cinq en dur et taisait les deux plus
            # nombreuses, dont celle qui porte le trafic git.
            for issue in ORDRE_ISSUES + tuple(
                sorted(set(compte) - set(ORDRE_ISSUES))
            ):
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

    @staticmethod
    def _cache_humain(n):
        for unite in ("o", "Kio", "Mio", "Gio"):
            if n < 1024 or unite == "Gio":
                return (
                    f"{n:.0f} {unite}" if unite == "o" else f"{n:.1f} {unite}"
                )
            n /= 1024
        return f"{n:.1f} Tio"

    @classmethod
    def _cache_par_machine(cls, limite=8):
        """(adresse, (octets du disque, octets de l'amont)) par VM.

        Les plus gros consommateurs d'abord : c'est ce qu'on cherche quand on
        se demande si une machine a été servie ou si elle a téléchargé. Les
        lignes sans client viennent d'un journal écrit avant que le champ
        existe — elles sont écartées plutôt que rangées sous un nom faux.
        """
        chemin = cls._cache_journal()
        if not chemin or not os.path.exists(chemin):
            return []
        par = {}
        try:
            with open(chemin, encoding="utf-8", errors="replace") as fh:
                for ligne in fh:
                    try:
                        d = json.loads(ligne)
                    except ValueError:
                        continue
                    client = d.get("client")
                    if not client:
                        continue
                    disque, amont = par.get(client, (0, 0))
                    octets = d.get("bytes", 0) or 0
                    if d.get("upstream"):
                        amont += octets
                    else:
                        disque += octets
                    par[client] = (disque, amont)
        except OSError:
            return []
        return sorted(par.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))[
            :limite
        ]

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
    # [10] Journaux
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # [11] Emporter le cache sur une autre machine
    # ------------------------------------------------------------------

    def _cache_transfert(self):
        """Copie le magasin vers une autre machine qui porte ERPLibre.

        Ce qui voyage est le MAGASIN, pas le service : les objets sont rangés
        sous une clé tirée de l'URL, jamais de la machine qui les a pris, et
        un dépôt git miroir est un dépôt. Les réglages, eux, restent : le
        pont, le sous-réseau et l'autorité appartiennent à l'hôte, et les
        emporter ferait servir une autorité dont aucune VM de là-bas n'a la
        clé.

        « tar » et non « rsync » : le second manque sur bien des hôtes, et le
        premier est partout. Le flux est compressé au passage — un magasin
        se compte en dizaines de gigaoctets, et un lien lent le rend
        autrement en une nuit.
        """
        print(f"\n📦 {t('Copy the cache to another machine')}")
        if not os.path.isfile(CACHE_BIN):
            print(f"  ✗ {t('Not installed:')} {CACHE_BIN}\n")
            return
        cache_dir = cache_offline.reglage("EL_CACHE_DIR", CACHE_CONF) or (
            CACHE_DIR
        )
        cible = click.prompt(
            t("Target machine (user@host, or an ssh alias)"), default=""
        ).strip()
        if not cible:
            print(f"  {t('Cancelled.')}\n")
            return
        # Trois pannes qu'un seul code de retour confondait : une machine
        # injoignable, un cache absent, un cache posé sans son compte de
        # service. Chacune appelle un geste différent, donc chacune a son
        # message. Le jeton « FIN » termine toujours la sonde : son absence
        # dénonce le LIEN, là où un code non nul seul accusait le cache.
        sonde = (
            f"test -x {shlex.quote(CACHE_BIN)} && echo binaire;"
            f" id -u {shlex.quote(cache_offline.SERVICE_USER)}"
            " >/dev/null 2>&1 && echo compte;"
            " sudo -n true 2>/dev/null && echo sudo;"
            " echo compte_ssh=$(id -un);"
            " echo place_magasin=$(df -B1 --output=avail"
            f" {shlex.quote(cache_dir)} 2>/dev/null | tail -1);"
            ' echo place_compte=$(df -B1 --output=avail "$HOME"'
            " 2>/dev/null | tail -1); echo FIN"
        )
        code, sortie = self._cache_ssh(cible, sonde)
        if code or "FIN" not in sortie:
            self._cache_dire_ssh_muet(cible)
            return
        if "binaire" not in sortie:
            self._cache_dire_poser_la_bas(cible)
            return
        # Le compte de service porte le magasin : sans lui, les fichiers
        # arriveraient à root et le service ne les lirait pas.
        if "compte" not in sortie:
            print(
                f"  ✗ {t('The cache is there but its service account is not:')}"
                f" {cache_offline.SERVICE_USER}"
            )
            print(
                "    "
                f"{t('Reinstall it there: the installer creates the account.')}"
            )
            print(f"      sudo bash {INSTALLATEUR}\n")
            return
        # Le magasin voyage dans l'entrée standard de ssh, qui porte des
        # octets et non un terminal : un sudo qui réclame un mot de passe
        # là-bas n'échoue pas à l'arrivée du flux, il l'empêche de partir.
        if "sudo" not in sortie:
            self._cache_sans_sudo_la_bas(cible, cache_dir, sortie)
            return
        print(f"  {t('What travels:')} {cache_dir}")
        for quoi, chemin in (
            (t("objects"), cache_dir),
            (t("git mirrors"), os.path.join(cache_dir, "git")),
        ):
            print(f"    {quoi:<14}{self._cache_poids(chemin)}")
        cmd = self._cache_transfert_cmd(cible, cache_dir)
        print(f"\n{t('Will execute:')} {cmd}")
        print(f"  {t('The settings stay here: bridge, subnet and authority')}")
        print(f"  {t('belong to this host, and are posed by entry 1 there.')}")
        if not click.confirm(t("Copy now?"), default=False):
            print(f"  {t('Cancelled.')}\n")
            return
        self.execute.exec_command_live(cmd, source_erplibre=False)

    @staticmethod
    def _cache_dire_ssh_muet(cible):
        """Le LIEN est en cause, pas le cache : la sonde n'a pas tourné.

        Le transfert tube « tar » dans ssh, sans terminal : un accès qui
        réclame un mot de passe échouerait au milieu du flux, après des
        gigaoctets. Il s'éprouve avant, par une commande qui ne coûte rien.
        """
        q = shlex.quote(cible)
        print(f"  ✗ {t('Cannot reach it over ssh:')} {cible}")
        print(f"    {t('This entry needs a password-less ssh access:')}")
        print(f"      ssh {q} true")
        print(f"    {t('If it asks for a password, post a key there:')}")
        print(f"      ssh-copy-id {q}\n")

    @staticmethod
    def _cache_branche_ici():
        """La branche de CE dépôt, ou '' si git ne répond pas.

        L'installateur et le menu sont des fichiers du dépôt : une machine
        restée sur une branche qui ne les porte pas ne les a tout
        simplement pas, et « sudo bash … » y répond « fichier introuvable »
        — une panne qui ne ressemble en rien à un cache manquant. Nommer la
        branche d'ici épargne de la deviner.
        """
        try:
            res = subprocess.run(
                [
                    "git",
                    "-C",
                    RACINE_DEPOT,
                    "rev-parse",
                    "--abbrev-ref",
                    "HEAD",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        nom = (res.stdout or "").strip()
        return "" if res.returncode or nom == "HEAD" else nom

    @classmethod
    def _cache_dire_poser_la_bas(cls, cible):
        """Les gestes à faire SUR la machine d'arrivée, un par ligne.

        L'entrée 1 pose le cache ICI : y renvoyer fait relancer une
        installation sur l'hôte qui en a déjà une, et la machine d'arrivée
        reste sans rien. Le magasin voyage ; le service, lui, se compile
        là-bas, contre la distribution de là-bas.

        L'installateur lit le réseau libvirt « default » pour trouver le
        pont. Sur un hôte où libvirt est arrêté, il meurt donc sur un réseau
        « introuvable » qui existe pourtant, et démarrer ce réseau seul ne
        suffit pas : sans hyperviseur joignable, rien ne répond. D'où les
        deux issues nommées ensemble — lever libvirt, ou nommer le pont.
        """
        q = shlex.quote(cible)
        # La branche d'ici, faute de pouvoir lire celle de là-bas : c'est
        # celle qui porte l'installateur, et un dépôt en tête détachée n'en
        # nomme aucune — la phrase générique vaut alors mieux qu'un nom faux.
        branche = cls._cache_branche_ici() or t("the branch used here")
        for ligne in (
            f"  ✗ {t('The target has no cache installed:')} {cible}",
            "    "
            f"{t('Entry 1 installs the cache HERE; the target needs its own.')}",
            f"    {t('Steps, ON the target machine:')}",
            f"      1. ssh {q}",
            f"      2. {t('go to its ERPLibre checkout, then:')}",
            f"         git fetch && git switch {branche}",
            f"         {t('without that branch, the installer is not there')}",
            f"      3. sudo bash {INSTALLATEUR}",
            "         "
            f"{t('or, in its own TODO: Execute > Deploy > QEMU cache, entry 1')}",
            "",
            f"    {t('The installer reads the « default » libvirt network to find')}",
            f"    {t('the bridge; a stopped libvirt makes it die on « not found »:')}",
            "      sudo systemctl start libvirtd.socket",
            "      sudo virsh -c qemu:///system net-start default",
            f"    {t('Or name the bridge by hand, libvirt being optional then:')}",
            "      sudo EL_BRIDGE=virbr0 EL_SUBNET=192.168.122.0/24 \\",
            f"        bash {INSTALLATEUR}",
            "",
            f"    {t('Then come back to this entry.')}",
            "",
        ):
            print(ligne)

    @staticmethod
    def _cache_jeton(sortie, nom):
        """La valeur d'un « nom=valeur » rendu par la sonde, ou ''."""
        for ligne in sortie.splitlines():
            if ligne.startswith(f"{nom}="):
                return ligne.split("=", 1)[1].strip()
        return ""

    def _cache_octets(self, chemin):
        """La taille du magasin en octets, ou 0 si elle ne se lit pas.

        Le privilège est nécessaire : les objets appartiennent au compte de
        service et ne sont pas lisibles autrement, si bien qu'un « du »
        ordinaire rendrait un total très inférieur au vrai — et ferait
        croire que la place suffit à l'arrivée.
        """
        try:
            res = subprocess.run(
                ["sudo", "-n", "du", "-sb", chemin],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            return 0
        morceau = (res.stdout or "").split("\t")[0].strip()
        return int(morceau) if morceau.isdigit() else 0

    def _cache_sans_sudo_la_bas(self, cible, cache_dir, sortie):
        """Sudo réclame un mot de passe à l'arrivée : deux issues, au choix.

        Le magasin occupe l'entrée standard de ssh — un canal d'octets, pas
        un terminal — et sudo refuse de lire un mot de passe ailleurs que
        sur un terminal. Un ticket pris d'avance n'y change rien : sudo
        l'attache au terminal qui l'a obtenu, et la session qui porte le
        flux n'en a aucun.

        Restent deux voies. Élargir les droits une fois, et le flux direct
        redevient possible. Ou passer par un fichier que le compte
        d'arrivée écrit lui-même — aucun privilège pendant le transfert —
        puis l'extraire dans SON terminal, où le mot de passe se tape. La
        seconde ne coûte aucun droit, mais demande de la place : le fichier
        et le magasin extrait coexistent le temps de l'extraction.
        """
        q = shlex.quote(cible)
        compte = self._cache_jeton(sortie, "compte_ssh") or "<compte>"
        print(f"  ✗ {t('sudo asks for a password on the target:')} {cible}")
        print(
            "    "
            f"{t('The store travels on ssh stdin, which carries no terminal,')}"
        )
        print(f"    {t('so nothing can type it. Two ways out:')}\n")
        print(f"    {t('1) Allow it there without a password, once:')}")
        print(f"      ssh -t {q} \\")
        print(
            f"        \"echo '{compte} ALL=(root) NOPASSWD: ALL'"
            ' | sudo tee /etc/sudoers.d/erplibre_cache"'
        )
        print(f"      {t('Then come back to this entry.')}\n")
        print(
            "    "
            f"{t('2) Carry it in two steps, the last one in your terminal there:')}"
        )
        taille = self._cache_octets(cache_dir)
        libre = min(
            int(self._cache_jeton(sortie, "place_magasin") or 0),
            int(self._cache_jeton(sortie, "place_compte") or 0),
        )
        if taille:
            print(
                f"      {t('needed there:')} {self._cache_humain(2 * taille)}"
                f"   {t('free there:')} {self._cache_humain(libre)}"
            )
        if taille and libre < 2 * taille:
            print(
                f"    ✗ {t('Not enough room there: the two-step mode is out.')}\n"
            )
            return
        if not click.confirm(
            t("Send it now, and print the command to finish there?"),
            default=False,
        ):
            print(f"  {t('Cancelled.')}\n")
            return
        code = self.execute.exec_command_live(
            self._cache_envoi_fichier_cmd(cible, cache_dir),
            source_erplibre=False,
        )
        if code:
            print(f"\n  ✗ {t('The send failed; nothing was extracted.')}\n")
            return
        print(
            f"\n  {t('Sent. To finish, ON the target machine, in a terminal:')}"
        )
        print(f"      {self._cache_finir_la_bas_cmd(cache_dir)}")
        print(f"    {t('The last command removes the file.')}\n")

    @staticmethod
    def _cache_envoi_fichier_cmd(cible, cache_dir):
        """Le temps 1 : le magasin part dans le compte d'arrivée.

        « cat » écrit dans le répertoire personnel du compte ssh, qui lui
        appartient : aucun privilège n'est donc demandé là-bas pendant le
        flux, et c'est exactement ce qui rend ce mode possible sans
        terminal.
        """
        q = shlex.quote
        return (
            f"sudo tar -C {q(cache_dir)} -cf - . | zstd -T0 -3"
            f" | ssh {q(cible)} {q('cat > ~/' + TRANSFERT_FICHIER)}"
        )

    @staticmethod
    def _cache_finir_la_bas_cmd(cache_dir):
        """Le temps 2, à taper dans le terminal de la machine d'arrivée.

        Une seule invocation privilégiée porte l'extraction ET le
        changement de propriétaire : en deux, la seconde redemanderait le
        mot de passe après des dizaines de minutes. Le fichier est retiré
        ensuite, son séjour étant ce qui double l'occupation.
        """
        q = shlex.quote
        interne = (
            f"tar -C {q(cache_dir)} -xf - --numeric-owner"
            f" && chown -R {cache_offline.SERVICE_USER}:"
            f"{cache_offline.SERVICE_USER} {q(cache_dir)}"
        )
        return (
            f"zstd -dc ~/{TRANSFERT_FICHIER} | sudo sh -c {q(interne)}"
            f" && rm -f ~/{TRANSFERT_FICHIER}"
        )

    @staticmethod
    def _cache_transfert_cmd(cible, cache_dir):
        """La commande qui emporte le magasin, en un seul flux.

        Lue d'un bout à l'autre : « tar » lit le magasin ici, « zstd » le
        comprime, « ssh » le porte, et là-bas le même trio le repose avant de
        rendre les fichiers au compte du service. Rien n'est écrit sur le
        disque entre les deux — un magasin de dizaines de gigaoctets n'a pas
        à exister deux fois.

        « --numeric-owner » à l'écriture et le « chown » à l'arrivée : le
        même compte porte rarement le même numéro d'une machine à l'autre.
        """
        q = shlex.quote
        # UNE seule invocation privilégiée à l'arrivée. En deux — « tar »
        # puis « chown » — un ticket sudo obtenu juste avant expire pendant
        # le transfert, et le second geste réclame alors un mot de passe que
        # plus rien ne peut saisir : le magasin serait posé, mais resterait
        # illisible pour le compte qui doit le servir.
        interne = (
            f"tar -C {q(cache_dir)} -xf - --numeric-owner"
            f" && chown -R {cache_offline.SERVICE_USER}:"
            f"{cache_offline.SERVICE_USER} {q(cache_dir)}"
        )
        distant = f"zstd -d | sudo sh -c {q(interne)}"
        return (
            f"sudo tar -C {q(cache_dir)} -cf - . | zstd -T0 -3"
            f" | ssh {q(cible)} {q(distant)}"
        )

    def _cache_ssh(self, cible, commande, timeout=30):
        """Une commande sur la machine d'arrivée. Rend (code, sortie)."""
        try:
            p = subprocess.run(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=10",
                    cible,
                    commande,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return 255, str(exc)
        return p.returncode, p.stdout

    @staticmethod
    def _cache_poids(chemin):
        """La place qu'occupe un chemin, ou « ? » quand on ne peut pas lire."""
        try:
            p = subprocess.run(
                ["du", "-sh", chemin],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return "?"
        return p.stdout.split("\t")[0] if p.returncode == 0 else "?"

    def _cache_journaux(self):
        """Les journaux en direct, pour regarder une installation passer.

        Le journal d'ACCÈS porte une ligne par requête et dit, pour chacune,
        si elle est sortie vers l'internet : c'est lui qui prouve qu'une VM
        traverse le cache, et lui qui ne montre plus aucune sortie sous une
        coupure. Le journal du SERVICE porte ce que le service dit de
        lui-même — démarrages, erreurs, hôtes retenus en tunnel.
        """
        chemin = self._cache_journal()
        print(f"\n📜 {t('Logs of the download cache')}")
        print(f"  {t('Access log:')} {chemin or '—'}")
        print(f"  {t('Ctrl-C ends a live follow.')}\n")
        choices = [
            {"prompt_description": t("Logs - Requests, live")},
            {
                "prompt_description": t(
                    "Logs - Only requests that went to the internet, live"
                )
            },
            {"prompt_description": t("Logs - Last 40 requests")},
            {"prompt_description": t("Logs - Service journal, live")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            if status in ("1", "2", "3") and not (
                chemin and os.path.exists(chemin)
            ):
                print(
                    f"  ✗ {t('No access log yet:')} {chemin or CACHE_CONF}\n"
                )
                continue
            if status == "1":
                self._cache_suivre(chemin)
            elif status == "2":
                self._cache_suivre(chemin, amont=True)
            elif status == "3":
                self._cache_suivre(chemin, suivre=False)
            elif status == "4":
                cmd = f"sudo journalctl -u {CACHE_SERVICE} -n 20 -f"
                print(f"{t('Will execute:')} {cmd}")
                self.execute.exec_command_live(cmd, source_erplibre=False)
            else:
                print(t("Command not found !"))

    def _cache_suivre(self, chemin, amont=False, suivre=True):
        """Le journal d'accès, mis en forme par `cache_journal.py`.

        « tail » garde le fichier ouvert et le lecteur met en forme ligne à
        ligne : un journal de plusieurs dizaines de Mio n'est jamais chargé
        en entier, et le suivi écrit dès qu'une requête est servie.
        """
        lecteur = os.path.join(
            RACINE_DEPOT, "script", "qemu", "cache_journal.py"
        )
        # « -u » : sans lui, Python met sa sortie en tampon dès qu'elle n'est
        # pas un terminal, et un tube l'est rarement.
        lire = f"python3 -u {shlex.quote(lecteur)}" + (
            " --amont" if amont else ""
        )
        cmd = (
            f"tail -n 40 {'-f ' if suivre else ''}{shlex.quote(chemin)}"
            f" | {lire}"
        )
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

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
    # [5] Miroirs git
    # ------------------------------------------------------------------

    def _cache_miroir_git(self):
        """Prendre l'avance sur les clonages, plutôt que les subir.

        À la demande, le miroir se remplit au fil des requêtes : la PREMIÈRE
        machine paie chaque clonage. Pour un dépôt qui en tire trois cents, ce
        n'est pas un coût qu'on supprime, c'est un coût qu'on déplace — sur la
        machine qui, justement, attend.
        """
        print(f"\n🪞 {t('Git mirrors of the ERPLibre manifests')}\n")
        if not os.path.isfile(CACHE_BIN):
            print(f"  ✗ {t('Not installed:')} {CACHE_BIN}\n")
            return
        depots, octets = self._cache_miroir_occupation()
        print(f"  {t('Already mirrored:')} {depots}, {octets}")

        racine = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        liste = depots_des_manifestes(racine)
        if not liste:
            print(f"  ✗ {t('No repository found in manifest/')}\n")
            return
        print(f"  {t('Declared by the manifests:')} {len(liste)}")
        # Un miroir est COMPLET : le dire en gigaoctets, pas en dépôts. Aucune
        # éviction n'est écrite, et la place ne se rend pas toute seule.
        print(f"\n  ⚠ {t('A mirror is complete: this can take tens of GiB')}")
        print(f"    {t('and hours on the first run. Nothing erases it.')}")
        print(f"    {t('Free space:')} {self._cache_place_libre()}\n")

        fichier = os.path.join(
            os.path.expanduser("~/.erplibre"), "miroirs_git.txt"
        )
        os.makedirs(os.path.dirname(fichier), exist_ok=True)
        with open(fichier, "w", encoding="utf-8") as fh:
            fh.write("\n".join(liste) + "\n")
        choices = [
            {
                "prompt_description": t(
                    "Mirrors - Fill them from the manifests"
                )
            },
            {"prompt_description": t("Mirrors - List them, heaviest first")},
            {"prompt_description": t("Mirrors - Remove one")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            if status == "1":
                self._cache_miroir_remplir(liste)
            elif status == "2":
                self._cache_miroir_lister()
            elif status == "3":
                self._cache_miroir_retirer()
            else:
                print(t("Command not found !"))

    def _cache_miroir_remplir(self, liste):
        """Remplir les miroirs sous le compte du SERVICE, jamais sous root.

        Le service rafraîchit ensuite ces dépôts sous son propre compte. Un
        objet que root y a posé lui est interdit en écriture : le
        rafraîchissement échoue, il est pris pour un amont muet, et le
        miroir se fige sans rien dire. L'environnement est celui que l'unité
        donne à git, relu dans l'unité plutôt que recopié ici.
        """
        fichier = os.path.join(
            os.path.expanduser("~/.erplibre"), "miroirs_git.txt"
        )
        os.makedirs(os.path.dirname(fichier), exist_ok=True)
        with open(fichier, "w", encoding="utf-8") as fh:
            fh.write("\n".join(liste) + "\n")
        # La liste n'a que des URL publiques. Lisible de tous, le compte du
        # service peut la rouvrir par /dev/stdin, qui ne parcourt pas le
        # répertoire personnel de l'opérateur, souvent fermé aux autres.
        os.chmod(fichier, 0o644)
        cmd = miroir_prefetch_cmd(fichier, environnement_de_l_unite())
        print(f"{t('Will execute:')} {cmd}")
        if not click.confirm(t("Fill the git mirrors now?")):
            return
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def _cache_miroir_lister(self):
        """Du plus lourd au plus léger : c'est ce qu'on cherche quand on
        surveille la place, et quelques dépôts font l'essentiel du total."""
        cmd = (
            f"{CACHE_BIN} --git-mirror-dir {CACHE_MIROIR_GIT}"
            f" --git-mirror-list"
        )
        print(f"{t('Will execute:')} {cmd}\n")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def _cache_miroir_retirer(self):
        """Effacer un miroir est sans danger : il se refait au prochain
        besoin, au prix du clonage. C'est ce qui permet de rendre de la place
        sans tout perdre."""
        nom = click.prompt(t("Repository to remove (as listed)")).strip()
        if not nom:
            return
        cmd = (
            f"sudo {CACHE_BIN} --git-mirror-dir {CACHE_MIROIR_GIT}"
            f" --git-mirror-remove {shlex.quote(nom)}"
        )
        print(f"\n{t('Will execute:')} {cmd}")
        print(f"  {t('It will be mirrored again when a VM needs it.')}")
        if not click.confirm(t("Remove this mirror?")):
            return
        self.execute.exec_command_live(cmd, source_erplibre=False)

    @classmethod
    def _cache_miroir_occupation(cls):
        """(nombre de dépôts, taille lisible) du miroir, lus du binaire."""
        for ligne in cls._cache_lire(
            f"{CACHE_BIN} --status --git-mirror-dir {CACHE_MIROIR_GIT}",
            delai=120,
        ).split("\n"):
            if ligne.startswith("dépôts git"):
                valeur = ligne.split(":", 1)[1].strip()
                nombre = valeur.split()[0]
                return nombre, valeur.split(",", 1)[-1].strip()
        return "0", "0 o"

    @staticmethod
    def _cache_place_libre():
        """Ce qui reste sur le système de fichiers qui porte le cache."""
        try:
            st = os.statvfs(os.path.dirname(CACHE_MIROIR_GIT))
        except OSError:
            return "?"
        libre = st.f_bavail * st.f_frsize
        for unite in ("o", "Kio", "Mio", "Gio", "Tio"):
            if libre < 1024 or unite == "Tio":
                return f"{libre:.1f} {unite}"
            libre /= 1024
        return "?"

    # ------------------------------------------------------------------
    # [6] Âge et nettoyage
    # ------------------------------------------------------------------

    def _cache_age(self):
        """Ce qui occupe, depuis quand, et de quoi en rendre.

        L'âge retenu est celui du dernier USAGE : le service remet la date
        d'un objet chaque fois qu'il le sert. « Vieux » veut donc dire « n'a
        plus servi », et non « est entré il y a longtemps » — un paquet servi
        tous les jours depuis un an n'est pas à jeter, l'effacer obligerait à
        le retélécharger le lendemain.
        """
        print(f"\n🧭 {t('Age of the cache, and cleanup')}\n")
        if not os.path.isfile(CACHE_BIN):
            print(f"  ✗ {t('Not installed:')} {CACHE_BIN}\n")
            return
        print(f"  {t('Free space:')} {self._cache_place_libre()}\n")
        choices = [
            {"prompt_description": t("Age - By day")},
            {"prompt_description": t("Age - By week")},
            {"prompt_description": t("Age - By month")},
            {
                "prompt_description": t(
                    "Clean - What has not served for a while"
                )
            },
            {"prompt_description": t("Clean - Everything")},
        ]
        grains = {"1": "jour", "2": "semaine", "3": "mois"}
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            if status in grains:
                self._cache_lancer(
                    f"--age-report --age-par {grains[status]}", sudo=False
                )
            elif status == "4":
                self._cache_nettoyer_age()
            elif status == "5":
                self._cache_nettoyer_tout()
            else:
                print(t("Command not found !"))

    def _cache_lancer(self, options, sudo=True):
        """La commande du cache, annoncée puis lancée."""
        cmd = (
            f"{'sudo ' if sudo else ''}{CACHE_BIN}"
            f" --cache-dir {CACHE_DIR} --git-mirror-dir {CACHE_MIROIR_GIT}"
            f" {options}"
        )
        print(f"{t('Will execute:')} {cmd}\n")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def _cache_nettoyer_age(self):
        """Le délai est DEMANDÉ, puis montré à blanc avant d'effacer.

        Une purge ne se rattrape pas : les octets sont rendus, il faut les
        retélécharger — et pour un dépôt en miroir, cela se compte en minutes.
        Voir d'abord ce qui partirait est le seul moyen de répondre à la
        question posée.
        """
        delai = click.prompt(
            t("Not served since (e.g. 30j, 12h)"), default="30j"
        ).strip()
        if not delai:
            return
        self._cache_lancer(
            f"--purge-older-than {shlex.quote(delai)} --dry-run"
        )
        if not click.confirm(t("Erase what is listed above?")):
            return
        self._cache_lancer(f"--purge-older-than {shlex.quote(delai)}")

    def _cache_nettoyer_tout(self):
        """Tout, objets ET dépôts. Montré à blanc d'abord, comme le reste."""
        print(f"  ⚠ {t('This empties the objects AND the git mirrors.')}")
        print(f"    {t('Refilling the mirrors takes minutes to hours.')}\n")
        self._cache_lancer("--purge --dry-run")
        if not click.confirm(t("Erase the whole cache?")):
            return
        self._cache_lancer("--purge")

    # ------------------------------------------------------------------
    # [7] Guide
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
            t("    Entry 10 follows it live: a request that goes out to the"),
            t("    internet shows there, and a cut leaves that view empty."),
            f"    {t('Git mirrors:')} {CACHE_MIROIR_GIT}",
            "",
            f"  {t('Git is mirrored, not cached')}",
            t("    Git's protocol is a negotiation: the server computes its"),
            t(
                "    answer from what the client already holds, so no answer is"
            ),
            t(
                "    reusable. A bare mirror per upstream repo is kept instead,"
            ),
            t("    and served locally. A mirror already held serves with no"),
            t("    network at all — but NOT what the cache may not decrypt:"),
            t("    npm and poetry carry their own trust store, so they are"),
            t("    tunnelled, and a tunnel carries nothing once cut."),
            t("    A mirror is COMPLETE: it weighs what the upstream repo"),
            t("    weighs, history included, and a few repositories make"),
            t("    most of the total. Entry 5 lists them heaviest first and"),
            t("    removes one — it comes back at the next need."),
            "",
            f"  {t('No eviction is written')}",
            t("    Neither the objects nor the mirrors shrink by themselves,"),
            t("    and both live on the orchestrator's disk. The diagnosis"),
            t("    entry says what each of the two occupies."),
            t("    Entry 6 groups them by AGE OF LAST USE — an object served"),
            t("    has its date renewed, so « old » means « no longer used »"),
            t("    — and gives back what has not served for a while, or all."),
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
            t(
                "    A Proxmox host that is itself a VM of this orchestrator crosses"
            ),
            t(
                "    this bridge: the machines it carries come out behind its address,"
            ),
            t(
                "    so the cache serves them, and the deployment poses the authority"
            ),
            t(
                "    in each of them. A host that lives elsewhere is not concerned —"
            ),
            t(
                "    install the cache ON it, the script being generic and Proxmox a"
            ),
            t(
                "    Debian. Reserve: a bridge switched onto the LAN is only seen by"
            ),
            t("    the rules when br_netfilter is enabled."),
            "",
            f"  {t('Carrying it to another machine')}",
            t("    Entry 11 copies the STORE, not the service: an object is"),
            t(
                "    keyed by URL and a git mirror is a repository, so both are"
            ),
            t(
                "    worth the same elsewhere. The settings stay here — bridge,"
            ),
            t("    subnet and authority belong to the host that serves them."),
            t("    The target must already carry the cache, installed from"),
            t("    ITS own checkout, and answer ssh without a password."),
            "",
        ):
            print(ligne)

    # ------------------------------------------------------------------
    # [8] Tests
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

    # ------------------------------------------------------------------
    # [9] Combler ce qui a manqué hors ligne
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_raison(verdict):
        """Ce qu'un verdict de rejeu veut dire, dans la langue du menu."""
        return {
            "rejouable": t("replay through the cache"),
            "jamais": t("never kept: the cache keeps only GET and HEAD"),
            "non-cachable": t("the cache does not keep this address"),
            "tunnel": t("host in tunnel: nothing to keep"),
            "git": t("git negotiation: fill the mirror from entry 5"),
            "adresse": t(
                "not a host name: a replay could loop back into the cache"
            ),
        }.get(verdict, verdict)

    @classmethod
    def _cache_refus_appris(cls):
        """Les hôtes que le service a appris à passer en tunnel.

        Ces refus ne vivent qu'en mémoire du service, qui ne les oublie pas,
        et seul son journal systemd les nomme. Lu sans privilège, puis par
        « sudo -n », qui échoue plutôt que de demander un mot de passe. Un
        journal illisible rend une liste vide.
        """
        lire = (
            f"journalctl -u {CACHE_SERVICE} -o cat --no-pager"
            " | grep -F 'tunnel opaque retenu pour'"
        )
        vu = cls._cache_lire(lire) + cls._cache_lire(f"sudo -n {lire}")
        return sorted(
            set(re.findall(r"tunnel opaque retenu pour (\S+) \(", vu))
        )

    def _cache_exclus(self):
        """Les hôtes que le cache passe en tunnel : déclarés dans ses
        sources, ajoutés par EL_EXCLUDE (séparés par des virgules, comme le
        service les lit), et appris au fil des refus."""
        racine = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        exclus = list(exclusions_declarees(racine))
        exclus += [
            e.strip()
            for e in cache_offline.reglage("EL_EXCLUDE", CACHE_CONF).split(",")
            if e.strip()
        ]
        appris = self._cache_refus_appris()
        if appris:
            print(
                f"  {t('Tunnel refusals learned by the service:')}"
                f" {', '.join(appris)}\n"
            )
        return exclus + appris

    @staticmethod
    def _cache_curl(argv, delai=REJEU_DELAI):
        """Les en-têtes que curl a reçus, ou "" s'il n'a rien obtenu.

        Les variables de mandataire héritées de l'opérateur sont retirées :
        un « https_proxy » enverrait le rejeu ailleurs que dans le cache, et
        un « no_proxy » ferait ignorer « -x ».
        """
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.lower().endswith("_proxy")
        }
        try:
            p = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=delai + 15,
                env=env,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return p.stdout or ""

    def _cache_rejouer(self, methode, url, ports, exclus):
        """Rejoue une adresse, puis sa chaîne de redirections, saut par saut.

        Rend [(url, statut)], le statut None quand curl n'a rien obtenu.

        Pas de « -L » : curl suivrait seul, et un saut vers l'autre schéma
        partirait par une connexion que le cache ne mène pas. Chaque saut
        est donc une commande de la même forme que la première, et n'est
        rejoué que s'il est lui-même rejouable, jamais deux fois. Seul un GET
        suit : un HEAD lit sa redirection et s'arrête, comme le client qui
        l'a émis.
        """
        sauts = []
        cible = url
        for _ in range(SAUTS_MAX + 1):
            sortie = self._cache_curl(
                rejeu_cmd(methode, cible, ports[0], ports[1], CACHE_CA)
            )
            statut, suivante = statut_et_cible(sortie, cible)
            sauts.append((cible, statut))
            if (
                methode.upper() != "GET"
                or statut not in REDIRECTIONS
                or not suivante
                or verdict_de_rejeu("GET", suivante, exclus) != "rejouable"
                or suivante in [u for u, _s in sauts]
            ):
                break
            cible = suivante
        return sauts

    def _cache_combler(self):
        """Rejouer, amont branché, ce que les VM hors ligne n'ont pas trouvé.

        Chaque rejeu traverse le cache sous la clé qu'une VM produirait : le
        nom d'hôte reste celui de l'URL, seule la connexion est menée à
        l'écoute locale. Ce qui entre alors au cache est ce que la VM y
        trouvera au prochain déploiement hors ligne.

        Refusé sous la coupure : le rejeu n'ajouterait que des manques au
        journal, et l'on croirait avoir rempli. Le guet est lu d'abord, sans
        sudo : tant qu'il tourne, la coupure est tenue exprès, et le geste
        donné est l'arrêt du guet. Une coupure illisible — sudo exige un mot
        de passe — n'est pas prise pour une absence : le menu le dit, et
        demande, non par défaut. Le plan est montré avant la confirmation du
        rejeu, avec ce qui ne se rejoue pas et pourquoi.
        """
        print(f"\n🩹 {t('What offline runs lacked')}\n")
        if not self._cache_combler_permis():
            return

        def reglage(nom, defaut=""):
            return cache_offline.reglage(nom, CACHE_CONF) or defaut

        chemin = self._cache_journal()
        manques = cache_offline.manques_recents(
            chemin, reglage("EL_SUBNET"), time.time() - JOURS_RECENTS * 86400
        )
        if not manques:
            print(
                f"  {t('No offline miss in the recent window: nothing to fill.')}\n"
            )
            return
        cache_dir = reglage("EL_CACHE_DIR", CACHE_DIR)
        verdicts = cache_offline.detient_interroger(
            [(m["methode"], m["url"]) for m in manques], CACHE_BIN, cache_dir
        )
        selon_journal = verdicts is None
        if selon_journal:
            verdicts = {}
            tenus = cache_offline.tenus_selon_journal(
                chemin,
                {(m["methode"], m["url"]): m["dernier"] for m in manques},
            )
        else:
            tenus = {
                c
                for c, v in verdicts.items()
                if v["verdict"] in cache_offline.DETENTION
            }
        restants = [
            m for m in manques if (m["methode"], m["url"]) not in tenus
        ]
        avis_journal = t("according to the log: a purge can make it wrong")
        if not restants:
            print(f"  ✓ {t('Everything that was missed is held now.')}")
            if selon_journal:
                print(f"    {avis_journal}")
            print()
            return

        exclus = self._cache_exclus()
        plan = []
        for m in restants:
            cle = (m["methode"], m["url"])
            if verdicts.get(cle, {}).get("verdict") == "non-cachable":
                verdict = "non-cachable"
            else:
                verdict = verdict_de_rejeu(m["methode"], m["url"], exclus)
            plan.append((m, verdict))
            marque = "↻" if verdict == "rejouable" else "·"
            print(f"  {marque} {m['methode']:<5}{m['url']}")
            print(f"        {self._cache_raison(verdict)} ({m['n']}×)")
        if selon_journal:
            print(f"\n  ⚠ {avis_journal}")
        rejouables = [m for m, v in plan if v == "rejouable"]
        if not rejouables:
            print(f"\n  {t('Nothing here can be replayed.')}\n")
            return

        # Le magasin ne tient compte ni de Vary ni des en-têtes de la
        # requête : il garde ce que curl reçoit, et le sert tel quel à la VM.
        entetes_1 = t(
            "The replay sends curl's own headers: a server that varies on"
        )
        entetes_2 = t(
            "User-Agent or Accept may keep another answer than the VM's."
        )
        print(f"\n  ⚠ {entetes_1}")
        print(f"    {entetes_2}")
        # Les ports par défaut de l'installateur, quand le réglage manque.
        ports = (
            reglage("EL_HTTP_PORT", "8898"),
            reglage("EL_TLS_PORT", "8899"),
        )
        premier = rejouables[0]
        exemple = rejeu_cmd(
            premier["methode"], premier["url"], ports[0], ports[1], CACHE_CA
        )
        print(f"\n{t('Will execute:')} {shlex.join(exemple)}")
        if not click.confirm(
            t("Replay these addresses through the cache now?")
        ):
            return

        resultats = [
            (m, self._cache_rejouer(m["methode"], m["url"], ports, exclus))
            for m in rejouables
        ]
        # Revérifié au MAGASIN : un 200 reçu par curl ne prouve pas que
        # l'objet a été gardé.
        verification = cache_offline.detient_interroger(
            [
                (m["methode"], url)
                for m, sauts in resultats
                for url, _s in sauts
            ],
            CACHE_BIN,
            cache_dir,
        )
        print()
        for m, sauts in resultats:
            for rang, (url, statut) in enumerate(sauts):
                cle = (m["methode"], url)
                if verification is None:
                    etat = t("not re-checked: this binary has no --detient")
                elif (
                    verification.get(cle, {}).get("verdict")
                    in cache_offline.DETENTION
                ):
                    etat = "✓ " + t("held")
                else:
                    etat = "✗ " + t("not held")
                recu = (
                    statut if statut is not None else t("curl got no answer")
                )
                debut = f"  {m['methode']:<5}" if rang == 0 else "    → "
                print(f"{debut}{url}")
                print(f"        [{recu}] {etat}")
        print()


def exclusions_declarees(racine):
    """Les hôtes que le cache passe d'office en tunnel, lus dans SA source.

    DefaultExclusions vit en Go. Le lire là plutôt que d'en tenir une copie
    empêche qu'un hôte ajouté côté Go soit rejoué d'ici. Une source illisible
    rend une liste vide.
    """
    try:
        with open(os.path.join(racine, MITM_GO), encoding="utf-8") as fh:
            src = fh.read()
    except OSError:
        return []
    bloc = re.search(r"var DefaultExclusions = \[\]string\{([^}]*)\}", src)
    return re.findall(r'"([^"]+)"', bloc.group(1)) if bloc else []


def hote_exclu(hote, exclus):
    """La règle du service : le nom exact, ou un suffixe qui commence par un
    point et couvre alors tout le domaine."""
    hote = (hote or "").lower()
    for e in exclus:
        e = (e or "").strip().lower()
        if e and (hote == e or (e.startswith(".") and hote.endswith(e))):
            return True
    return False


def _est_une_adresse_ip(hote):
    import ipaddress

    try:
        ipaddress.ip_address(hote)
    except ValueError:
        return False
    return True


def verdict_de_rejeu(methode, url, exclus=()):
    """Que faire d'une adresse manquée : « rejouable », « jamais », « git »,
    « tunnel » ou « adresse ».

    Seuls GET et HEAD se gardent. Une négociation git ne se garde pas : c'est
    un DÉPÔT que le cache tient, et l'entrée 5 le remplit. Un hôte en tunnel
    — https sur une adresse IP, sans SNI, ou hôte exclu — n'a rien à garder,
    et rejoué depuis l'hôte il revient dans le cache : sans détournement, la
    destination d'origine d'une connexion locale est l'écoute elle-même, et
    le tunnel s'y rappelle sans fin. Pour la même raison, une adresse IP ou
    « localhost » en http n'est pas rejouée.
    """
    if (methode or "").upper() not in cache_offline.METHODES_GARDABLES:
        return "jamais"
    try:
        morceaux = urlsplit(url)
        hote = (morceaux.hostname or "").lower()
    except ValueError:
        return "adresse"
    if morceaux.scheme not in ("http", "https") or not hote:
        return "adresse"
    if _est_une_adresse_ip(hote):
        return "tunnel" if morceaux.scheme == "https" else "adresse"
    if hote == "localhost":
        return "adresse"
    if cache_offline.depot_git(url):
        return "git"
    if morceaux.scheme == "https" and hote_exclu(hote, exclus):
        return "tunnel"
    return "rejouable"


def rejeu_cmd(methode, url, http_port, tls_port, ca, delai=REJEU_DELAI):
    """La commande curl qui rejoue une adresse PAR le cache, en arguments.

    http passe par le mandataire du cache (« -x »), qui rebâtit l'adresse
    depuis la ligne de requête. https garde son nom — SNI et en-tête Host —
    et seule sa connexion est menée à l'écoute TLS : « --connect-to » sans
    hôte ni port d'origine vaut pour tous. La clé est alors celle qu'une VM
    produirait. L'autorité du cache est APPROUVÉE par « --cacert », jamais
    contournée.

    « -D - » rend les en-têtes, qui portent la redirection ; le corps va à
    /dev/null, le cache le garde de son côté.

    « -q » en PREMIER argument — curl ne l'honore qu'à cette place — écarte
    le ~/.curlrc de l'opérateur : un « proxy » y enverrait le rejeu https
    ailleurs que dans le cache, et « location », « compressed » ou un
    en-tête changeraient ce qui entre au magasin sous la clé de la VM.
    """
    argv = ["curl", "-q", "-sS", "-o", "/dev/null", "-D", "-"]
    argv += ["--max-time", str(delai)]
    if urlsplit(url).scheme == "https":
        argv += ["--connect-to", f"::127.0.0.1:{tls_port}", "--cacert", ca]
    else:
        argv += ["-x", f"http://127.0.0.1:{http_port}"]
    if (methode or "").upper() == "HEAD":
        argv.append("-I")
    argv.append(url)
    return argv


def statut_et_cible(entetes, url):
    """(statut, cible absolue de la redirection ou "") lus dans « curl -D - ».

    Le DERNIER bloc compte : un « 100 Continue » précède la vraie réponse.
    Une cible relative est résolue contre l'adresse demandée. Rend (None, "")
    quand curl n'a rien reçu.
    """
    statut, cible = None, ""
    for ligne in (entetes or "").splitlines():
        ligne = ligne.strip()
        if ligne.startswith("HTTP/"):
            champs = ligne.split()
            statut = (
                int(champs[1])
                if len(champs) > 1 and champs[1].isdigit()
                else None
            )
            cible = ""
        elif ligne.lower().startswith("location:"):
            cible = urljoin(url, ligne.split(":", 1)[1].strip())
    return statut, cible


def environnement_de_l_unite(unite=None):
    """Les « NOM=valeur » que l'unité systemd donne au service, dans l'ordre.

    Lus dans l'unité posée, qui porte les valeurs résolues à l'installation.
    Une unité illisible rend une liste vide.
    """
    out = []
    try:
        with open(unite or CACHE_UNITE, encoding="utf-8") as fh:
            for ligne in fh:
                ligne = ligne.strip()
                if not ligne.startswith("Environment="):
                    continue
                try:
                    out.extend(shlex.split(ligne.split("=", 1)[1]))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def miroir_prefetch_cmd(fichier, environnement):
    """La commande qui remplit les miroirs sous le compte du service.

    La liste arrive sur l'entrée standard, ouverte par le shell de
    l'opérateur : « /dev/stdin » la rouvre sans parcourir le chemin, là où
    le compte du service ne traverse pas le répertoire personnel qui la
    porte.
    """
    mots = ["sudo", "-u", cache_offline.SERVICE_USER, "env"]
    mots += [shlex.quote(e) for e in environnement]
    mots += [
        CACHE_BIN,
        "--git-mirror-dir",
        CACHE_MIROIR_GIT,
        "--git-mirror-prefetch",
        "/dev/stdin",
        "<",
        shlex.quote(fichier),
    ]
    return " ".join(mots)


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


def depots_des_manifestes(racine):
    """Les dépôts git que les manifestes du dépôt déclarent, sans doublon.

    Un manifeste Google Repo nomme des « remote » — l'URL de base d'une forge —
    et des « project » qui s'y rattachent. L'URL complète est la concaténation
    des deux, et un même projet figure dans plusieurs manifestes, un par
    version d'Odoo.

    Un manifeste illisible est SAUTÉ plutôt que fatal : la liste sert à prendre
    de l'avance, et en perdre une partie vaut mieux que de ne rien prendre.
    """
    import glob
    import xml.etree.ElementTree as ET

    vus = set()
    out = []
    for fichier in sorted(
        glob.glob(os.path.join(racine, "manifest", "*.xml"))
    ):
        try:
            arbre = ET.parse(fichier).getroot()
        except (ET.ParseError, OSError):
            continue
        bases = {
            e.get("name"): (e.get("fetch") or "")
            for e in arbre.findall("remote")
        }
        for projet in arbre.findall("project"):
            base = bases.get(projet.get("remote"), "")
            nom = projet.get("name") or ""
            if not base or not nom:
                continue
            url = base.rstrip("/") + "/" + nom.lstrip("/")
            if url not in vus:
                vus.add(url)
                out.append(url)
    return out
