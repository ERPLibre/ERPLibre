#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu de l'assistant LLM : quel serveur, et la conversation.

La frontière avec `script/todo/assistant/` est nette : ici on DEMANDE (quel
serveur, quelle adresse, quelle question) et on affiche ; là-bas on reconnaît,
on classe et on parle. Ce fichier ne connaît ni l'ordre des sondes, ni la forme
d'une réponse d'API.

Mixin de la classe TODO : ses méthodes vivent sur la même instance que celles
des autres fichiers, elles s'appellent donc par « self. » sans rien importer.
Le fil d'Ariane l'exige — `_menu_header` dérive les miettes de la pile
d'appels en retenant les cadres dont la variable locale `self` EST l'instance
TODO. Une fonction de module n'en laisse aucune, et c'est pourquoi le
sous-menu VPN n'apparaît pas dans son propre fil.

Trois contraintes d'affichage sont mesurées, pas supposées.

`click.prompt` réimprime TOUTE sa chaîne d'invite à chaque entrée vide, et une
question collée sur plusieurs lignes lui devient autant de tours — une ligne
collée valant « 0 » déclenche alors une entrée de menu. La conversation lit
donc par `input()`, sur une invite d'une seule ligne, et toute commande porte
une barre oblique initiale.

`click.prompt` lève `Abort` sur Ctrl+C comme sur Ctrl+D, et le seul rattrapage
vit dans `__main__` : sans capture locale, une interruption pendant une
réponse termine le CLI entier. Chaque boucle d'ici l'attrape et rend la main
au menu.

Le dépôt n'a ni pager, ni progression sur place : la sortie s'ajoute ligne à
ligne. Une réponse longue se ferme sur une ligne de pied, jamais sur un
défilement piloté.
"""
from __future__ import annotations

import os
import time

import click

from script.todo.assistant import capabilities as llm_caps
from script.todo.assistant import fingerprint as llm_fp
from script.todo.assistant import servers as llm_servers
from script.todo.todo_i18n import t

# Les commandes que cette boucle sert. `chat.COMMANDS` en porte une de plus,
# « /gpt », qui suppose un catalogue d'outils : l'annoncer dans « /? » avant
# qu'il existe promettrait une entrée qui n'aboutit pas.
COMMANDES_PHASE_1 = (
    "/?",
    "/q",
    "/new",
    "/gpt",
    "/srv",
    "/ctx",
    "/m",
    "/save",
)

# Le catalogue se choisit par LETTRE. Le menu qui précède numérote ses
# entrées ; une seconde liste numérotée juste après invite à retaper un
# numéro de menu, et c'est une régression que le menu VPN a déjà payée. Un
# chiffre reste accepté comme rang, parce que le doigt vient d'en taper un.
LETTRES = "abcdefghijklmnopqrstuvwxyz"

# Les marques de compatibilité. Seule une exigence CONTREDITE par un champ
# réellement lu sur le serveur grise ; l'inconnu et l'estimé restent
# exécutables, sans quoi le catalogue se viderait devant un serveur qui
# n'annonce rien — c'est-à-dire devant la plupart.
MARQUE = {"ok": "✅", "unknown": "⚠️", "no": "⛔"}

# Ce qu'une description a le droit d'occuper. Le dépôt n'interroge jamais la
# largeur du terminal ; soixante-dix caractères tiennent partout, indentation
# comprise.
LARGEUR = 70

# Le serveur distant que le coffre sait déjà servir. Il porte une poignée comme
# les autres : c'est elle, et non son adresse, qui a le droit de circuler.
REPLI_OPENAI = llm_servers.Server(
    handle="server-0",
    label="OpenAI",
    host="api.openai.com",
    port=443,
    software="openai",
    model="gpt-4o",
    hosting="global",
    secret_ref="kdbx",
)


class AssistantMenuMixin:
    """Le menu de l'assistant LLM : quel serveur, et la conversation."""

    def _llm_state(self):
        """L'état de la session : serveur choisi, sonde locale, destinations
        déjà confirmées.

        Vit sur l'instance et meurt avec le CLI. Rien n'en descend sur le
        disque : une table de qui a répondu décrit des machines que personne
        n'a désignées.
        """
        if getattr(self, "_llm_session", None) is None:
            self._llm_session = {
                "serveur": None,
                "sonde": None,
                "confirmes": set(),
                "contextes": set(),
                "gpt": None,
                "gpts": None,
            }
        return self._llm_session

    def _llm_probe_loopback(self):
        """Ce qui écoute sur la boucle locale, sondé une fois par session.

        Les onze ports se testent en quelques millisecondes : la sonde est
        donc gratuite et ne mérite aucune question. Son résultat nourrit les
        étiquettes du menu, pour qu'une première utilisation n'ait pas à
        choisir entre configurer et abandonner.
        """
        state = self._llm_state()
        if state["sonde"] is not None:
            return state["sonde"]
        trouves = []
        for port in llm_fp.PORTS:
            corps = llm_fp.collect("127.0.0.1", port, budget=0.4)
            if not corps:
                continue
            empreinte = llm_fp.identify(corps, port=port, host="127.0.0.1")
            if empreinte.software:
                trouves.append((port, empreinte))
        state["sonde"] = trouves
        return trouves

    def _llm_current(self):
        """Le serveur en usage : celui qu'on a choisi, le premier connu, ou
        celui que la boucle locale vient d'offrir. `None` quand il n'y en a
        aucun, et le repli distant prend alors la question."""
        state = self._llm_state()
        if state["serveur"]:
            return state["serveur"]
        connus = llm_servers.load(get_config=self._llm_get_config)
        if connus:
            state["serveur"] = connus[0]
            return connus[0]
        for port, empreinte in self._llm_probe_loopback():
            serveur = llm_servers.Server(
                handle="server-1",
                label=empreinte.software,
                host="127.0.0.1",
                port=port,
                software=empreinte.software,
                model=empreinte.models[0] if empreinte.models else "",
                hosting="loopback",
                secret_ref="",
            )
            state["serveur"] = serveur
            return serveur
        return None

    def _llm_get_config(self, keys):
        return self.config_file.get_config_value(keys)

    def _llm_set_config(self, keys, value):
        self.config_file.set_config_value(keys, value)

    @staticmethod
    def _llm_count(nombre, singulier, pluriel):
        """« 1 hôte » ou « 254 hôtes » : le nombre, et le nom qui s'accorde.

        Le français comme l'anglais accordent le nom sur le nombre. Une ligne
        de résumé qui annonce « 1 hôtes » se lit comme un défaut de l'outil,
        et c'est la seule chose qu'on retienne de la ligne.
        """
        return f"{nombre} {t(singulier if abs(nombre) == 1 else pluriel)}"

    @staticmethod
    def _llm_label(serveur):
        """« ollama · petit-modele:7b » — ce qui tient dans une étiquette.

        Le logiciel et le modèle suffisent à situer une destination ; l'adresse
        n'y figure pas, elle appartient à la fiche du serveur.
        """
        if serveur is None:
            return t("no server yet")
        if serveur.model:
            return f"{serveur.software} · {serveur.model}"
        return serveur.software

    def prompt_assistant_llm(self):
        """Le sous-menu : parler à un serveur, ou décider auquel."""
        print(f"🤖 {t('A server, a gpt tool, a conversation.')}")
        while True:
            serveur = self._llm_current()
            if serveur is None:
                repli = t("no local server — via api.openai.com")
                parler = f"{t('Free question')}  ({repli})"
            else:
                parler = f"{t('Free question')}  ({self._llm_label(serveur)})"
            connus = llm_servers.load(get_config=self._llm_get_config)
            compte = f"{len(connus)}" if connus else t("no server yet")
            choices = [
                {"section": t("Talk")},
                {"prompt_description": parler},
                {"prompt_description": self._llm_gpt_label()},
                {"section": t("Server")},
                {"prompt_description": (f"{t('Known servers')}  ({compte})")},
                {"prompt_description": t("Search for a server…")},
                {
                    "prompt_description": (
                        f"{t('Server card')}  ({t('what it says it can do')})"
                    )
                },
            ]
            try:
                status = click.prompt(self.fill_help_info(choices))
            except (KeyboardInterrupt, click.exceptions.Abort):
                print()
                return
            print()
            if status == "0":
                return
            elif status == "1":
                self._llm_conversation()
            elif status == "2":
                self._llm_gpt_catalogue()
            elif status == "3":
                self._llm_servers()
            elif status == "4":
                self._llm_search()
            elif status == "5":
                self._llm_server_card()
            else:
                print(t("Command not found !"))

    # ------------------------------------------------------------------
    # Les serveurs

    def _llm_servers(self):
        """Lister, choisir, ajouter à la main, supprimer.

        Une liste vide tombe dans la recherche plutôt que d'imprimer une
        erreur : l'entrée n'a jamais de raison d'être une impasse.
        """
        connus = llm_servers.load(get_config=self._llm_get_config)
        if not connus:
            print(t("no server yet"))
            self._llm_search()
            return
        while True:
            state = self._llm_state()
            choices = []
            for serveur in connus:
                marque = (
                    f"  ({t('in use')})"
                    if state["serveur"]
                    and state["serveur"].handle == serveur.handle
                    else ""
                )
                choices.append(
                    {
                        "prompt_description": (
                            f"{serveur.label} — {self._llm_label(serveur)}"
                            f"{marque}"
                        )
                    }
                )
            choices.append({"section": t("Server")})
            choices.append({"prompt_description": t("Add a server by hand")})
            choices.append({"prompt_description": t("Delete a server")})
            try:
                status = click.prompt(self.fill_help_info(choices))
            except (KeyboardInterrupt, click.exceptions.Abort):
                print()
                return
            print()
            if status == "0":
                return
            try:
                rang = int(status)
            except ValueError:
                print(t("Command not found !"))
                continue
            if 1 <= rang <= len(connus):
                self._llm_state()["serveur"] = connus[rang - 1]
                print(f"✅ {self._llm_label(connus[rang - 1])}")
            elif rang == len(connus) + 1:
                self._llm_add_server()
                connus = llm_servers.load(get_config=self._llm_get_config)
            elif rang == len(connus) + 2:
                self._llm_delete_server(connus)
                connus = llm_servers.load(get_config=self._llm_get_config)
            else:
                print(t("Command not found !"))

    def _llm_add_server(self):
        """Saisir un hôte et un port, puis reconnaître ce qui répond.

        La reconnaissance passe par le corps de la réponse : un port ne dit
        jamais quel logiciel écoute derrière lui.
        """
        try:
            host = click.prompt(t("Host or IP")).strip()
            port = int(click.prompt(t("Port")).strip())
        except (KeyboardInterrupt, click.exceptions.Abort):
            print()
            return
        except ValueError:
            print(t("Command not found !"))
            return
        corps = llm_fp.collect(host, port, budget=2.0)
        empreinte = llm_fp.identify(corps, port=port, host=host)
        if not empreinte.software:
            print(f"⚠ {t('Answered, not identified')}")
        label = click.prompt(t("Name for this server")).strip() or host
        connus = llm_servers.load(get_config=self._llm_get_config)
        connus.append(
            llm_servers.Server(
                handle="",
                label=label,
                host=host,
                port=port,
                software=empreinte.software or "",
                model=empreinte.models[0] if empreinte.models else "",
                hosting=llm_caps.classify_hosting(host),
                secret_ref="",
            )
        )
        llm_servers.save(
            llm_servers.assign_handles(connus),
            set_config=self._llm_set_config,
        )
        print(f"✅ {label}")

    def _llm_delete_server(self, connus):
        """Supprimer un serveur, son nom retapé en entier.

        Une frappe sur « o » se donne par réflexe ; recopier un nom oblige à
        regarder ce qu'on retire.
        """
        noms = [s.label for s in connus]
        for rang, nom in enumerate(noms, 1):
            print(f"[{rang}] {nom}")
        try:
            choisis = self._parse_index_selection(
                click.prompt(t("Delete a server")), noms
            )
            if not choisis:
                return
            frappe = click.prompt(
                t("Type the server name in full to delete it:"),
                prompt_suffix=" ",
            ).strip()
        except (KeyboardInterrupt, click.exceptions.Abort):
            print()
            return
        if frappe != choisis[0]:
            print(t("Destination not retyped — nothing was sent."))
            return
        restants = [s for s in connus if s.label != choisis[0]]
        llm_servers.save(
            llm_servers.assign_handles(restants),
            set_config=self._llm_set_config,
        )
        state = self._llm_state()
        if state["serveur"] and state["serveur"].label == choisis[0]:
            state["serveur"] = None

    def _llm_search(self):
        """Où chercher un serveur.

        La question se pose ICI, au moment où l'on cherche, et non à l'entrée
        du menu : une première utilisation doit pouvoir répondre sans avoir
        rien à configurer.

        Les réseaux détectés sont LISTÉS, jamais devinés. Une machine porte
        souvent deux /24 — celui qui sort et celui d'un pont de
        virtualisation — et « le réseau local » ne désigne alors rien de
        précis ; le pont est signalé comme tel et le choix reste entier.
        """
        from script.todo.assistant import discover as llm_disc

        while True:
            reseaux = llm_disc.local_networks()
            choices = [
                {
                    "prompt_description": (
                        f"{t('Here (127.0.0.1)')}"
                        f"  ({t('11 ports, instant')})"
                    )
                },
                {
                    "prompt_description": t(
                        "The QEMU VMs of this machine (virsh)"
                    )
                },
                {"prompt_description": t("The hosts of ~/.ssh/config")},
            ]
            for interface in reseaux:
                pont = (
                    f" ({t('libvirt bridge')})" if interface.is_bridge else ""
                )
                choices.append(
                    {
                        "prompt_description": (
                            f"{t('local network of this machine')}"
                            f"  {interface.cidr}"
                            f" · {interface.name}{pont}"
                        )
                    }
                )
            choices.append({"prompt_description": t("An address I type")})
            choices.append(
                {"prompt_description": t("A network I type (CIDR)")}
            )
            choices.append(
                {"prompt_description": t("The networks of a machine over SSH")}
            )
            print(t("Where should I look for a server?"))
            try:
                status = click.prompt(self.fill_help_info(choices))
            except (KeyboardInterrupt, click.exceptions.Abort):
                print()
                return
            print()
            if status == "0":
                return
            try:
                rang = int(status)
            except ValueError:
                print(t("Command not found !"))
                continue
            if rang == 1:
                self._llm_state()["sonde"] = None
                self._llm_probe_and_keep(["127.0.0.1"])
            elif rang == 2:
                self._llm_search_qemu()
            elif rang == 3:
                self._llm_search_ssh()
            elif 4 <= rang <= 3 + len(reseaux):
                self._llm_search_network(reseaux[rang - 4])
            elif rang == 4 + len(reseaux):
                self._llm_add_server()
            elif rang == 5 + len(reseaux):
                self._llm_search_cidr()
            elif rang == 6 + len(reseaux):
                self._llm_search_remote()
            else:
                print(t("Command not found !"))

    def _llm_search_qemu(self):
        """Les VM libvirt de la machine comme cibles.

        Le résolveur d'adresse est celui qui ne PATIENTE pas : celui qui
        attend tient le menu jusqu'à dix minutes par VM, et une VM éteinte
        suffit à le déclencher.
        """
        from script.todo.assistant import discover as llm_disc

        vms = llm_disc.qemu_hosts(
            list_domains=self._qemu_list_domains,
            vm_ip=self._qemu_vm_ip_now,
        )
        if not vms:
            print(t("libvirt answers, no VM defined"))
            return
        adresses = []
        for nom, adresse in vms:
            if adresse:
                adresses.append(adresse)
            else:
                print(
                    f"  {nom} —"
                    f" {t('Host without an address — listed as unknown')}"
                )
        if adresses:
            self._llm_probe_and_keep(adresses)

    def _llm_search_ssh(self):
        """Les machines déjà connues de la configuration SSH comme cibles.

        Une entrée sans `HostName` n'est jamais écartée : `ssh -G` rend alors
        l'alias comme nom d'hôte, et le DNS ou /etc/hosts le résout souvent.
        """
        from script.todo.assistant import discover as llm_disc

        hotes = llm_disc.ssh_hosts(
            list_aliases=self._ssh_config_hosts,
            resolve=self._ssh_resolve,
        )
        if not hotes:
            print(t("~/.ssh/config absent — nothing to probe"))
            return
        self._llm_probe_and_keep([hote for _, hote, _ in hotes])

    def _llm_search_cidr(self):
        """Balayer un réseau que la machine ne porte pas.

        Les réseaux proposés sont ceux que les interfaces portent. Or un
        serveur vit souvent AILLEURS, derrière la passerelle : quand le CLI
        tourne dans une VM, le « réseau local » qu'il voit est celui de
        l'hyperviseur, et le vrai parc est hors-lien. Rien d'autre dans ce
        menu n'atteint ce cas — la saisie d'une adresse ne prend qu'un hôte,
        et la table de voisinage est link-local, donc elle ne connaîtra
        jamais un hôte routé.
        """
        try:
            cidr = click.prompt(t("Network in CIDR form")).strip()
        except (KeyboardInterrupt, click.exceptions.Abort):
            print()
            return
        self._llm_sweep_cidr(cidr)

    def _llm_search_remote(self):
        """Lire les réseaux d'une machine joignable en SSH, et en balayer un.

        La machine du dessus porte les bons préfixes quand celle-ci n'en voit
        que ceux de son hyperviseur. Les réseaux se LISENT là-bas et se
        balayent D'ICI : la table de routage locale décide de l'accès, et une
        route par défaut suffit d'ordinaire. L'hôte distant n'a besoin que
        d'un accès en lecture, et rien n'est balayé depuis lui.
        """
        from script.todo.assistant import discover as llm_disc

        try:
            alias = click.prompt(t("Host reachable over SSH")).strip()
        except (KeyboardInterrupt, click.exceptions.Abort):
            print()
            return
        if not alias:
            return
        print(f"  {t('Reading the networks it carries…')}", flush=True)
        reseaux = llm_disc.remote_networks(alias)
        if not reseaux:
            print(f"⚠ {t('That host did not answer, or carries no network.')}")
            return
        choices = []
        for interface in reseaux:
            pont = f" ({t('libvirt bridge')})" if interface.is_bridge else ""
            choices.append(
                {
                    "prompt_description": (
                        f"{interface.cidr} · {interface.name}{pont}"
                    )
                }
            )
        print(t("read on %s, swept from here") % alias)
        try:
            status = click.prompt(self.fill_help_info(choices))
        except (KeyboardInterrupt, click.exceptions.Abort):
            print()
            return
        print()
        if status == "0":
            return
        try:
            rang = int(status)
        except ValueError:
            print(t("Command not found !"))
            return
        if 1 <= rang <= len(reseaux):
            self._llm_sweep_cidr(reseaux[rang - 1].cidr)
        else:
            print(t("Command not found !"))

    def _llm_search_network(self, interface):
        """Balayer un réseau porté par une interface."""
        self._llm_sweep_cidr(interface.cidr)

    def _llm_sweep_cidr(self, cidr):
        """Confirmer, puis balayer le réseau nommé.

        C'est la seule action de ce menu qui atteigne des machines que
        personne n'a désignées, d'où une confirmation qui nomme le réseau et
        les comptes exacts.

        Le défaut est le réseau ENTIER, et non les hôtes que la table de
        voisinage dit avoir déjà parlé. Rétrécir par défaut paraissait plus
        prudent, et se retourne : la table ne porte souvent que la
        passerelle, le balayage se réduit alors à une adresse, et le résumé
        annonce un /24 vide là où une seule adresse a été vue. Un faux
        négatif présenté comme un fait coûte plus cher que les connexions
        épargnées. La confirmation nomme le compte, donc le consentement est
        informé dans les deux sens.

        La lettre « v » restreint aux hôtes déjà vus, pour un réseau chargé
        où l'on cherche vite. Une lettre plutôt qu'un troisième numéro : un
        numéro juste après un menu numéroté invite à retaper une entrée de
        menu.
        """
        from script.todo.assistant import discover as llm_disc

        jobs = llm_disc.plan_sweep(cidr, skip=self._qemu_host_addresses())
        if not jobs:
            print(f"⚠ {t('Wider than a /24 is refused.')}")
            print(
                t(
                    "The /24 is an assumption: a prefix does not follow from"
                    " an address."
                )
            )
            return
        toutes = sorted({ip for ip, _ in jobs})
        voisins = set(llm_disc.neigh_hosts(llm_disc.run_ip(["neigh"])))
        deja_vus = [adresse for adresse in toutes if adresse in voisins]
        print(
            f"⚠ {t('Sweeping the network reaches machines you did not name.')}"
        )
        question = t("Sweep %s addresses × %s ports on %s?") % (
            len(toutes),
            len(llm_fp.PORTS),
            cidr,
        )
        rappel = (
            f", « v » = {self._llm_count(len(deja_vus), 'host', 'hosts')}"
            if deja_vus
            else ""
        )
        try:
            reponse = click.prompt(f"{question} (o/N{rappel})")
        except (KeyboardInterrupt, click.exceptions.Abort):
            print()
            return
        cibles = toutes
        restreint = False
        if reponse.strip().lower() == "v" and deja_vus:
            cibles = deja_vus
            restreint = True
        elif not self._is_yes(reponse):
            return
        self._llm_probe_and_keep(cibles, cible=cidr, restreint=restreint)

    @staticmethod
    def _llm_sweep_tuning():
        """Les réglages du balayage, lus dans les préférences.

        Le menu les lit et les passe ; le module de découverte ne connaît pas
        les préférences, ce qui le laisse testable sans le disque. Une valeur
        illisible ou hors bornes retombe sur le défaut du module plutôt que de
        propager un réglage qui fabriquerait des faux négatifs.
        """
        from script.todo import todo_prefs

        reglages = {}
        try:
            ouvriers = int(todo_prefs.get("assistant_sweep_workers"))
            if ouvriers > 0:
                reglages["workers"] = ouvriers
        except (TypeError, ValueError):
            pass
        try:
            delai = float(todo_prefs.get("assistant_sweep_timeout"))
            if delai > 0:
                reglages["timeout"] = delai
        except (TypeError, ValueError):
            pass
        return reglages

    def _llm_sweep_printer(self):
        """L'imprimeur d'événements du balayage.

        Les touches seulement, plus un battement : une ligne par hôte mort
        ferait 254 lignes de rien, et le silence d'un balayage de plusieurs
        secondes se lit comme un blocage.
        """

        def imprimer(event):
            genre = event[0]
            if genre == "hit":
                print(f"  ✓ {event[1]}:{event[2]}")
            elif genre == "heartbeat":
                print(
                    f"  ⏳ {event[1]}/{event[2]} {t('ports')}"
                    f" ({self._fmt_dur(event[3])})"
                )

        return imprimer

    def _llm_probe_and_keep(self, adresses, *, cible=None, restreint=False):
        """Frapper, reconnaître, puis proposer de garder.

        Le balayage n'ouvre que des connexions ; la reconnaissance, elle,
        coûte une requête HTTP par étage et ne part donc QUE vers les hôtes
        qui ont accepté. C'est ce qui rend un /24 abordable.

        `restreint` dit que les adresses sont un SOUS-ENSEMBLE de ce que
        `cible` nomme. L'absence de trouvaille se dit alors autrement : un
        réseau dont on n'a vu qu'une adresse n'est pas un réseau vide, et
        l'annoncer comme tel est un faux négatif.
        """
        from script.todo.assistant import discover as llm_disc

        adresses = list(dict.fromkeys(adresses))
        jobs = [
            (adresse, port) for adresse in adresses for port in llm_fp.PORTS
        ]
        etiquette = cible or ", ".join(adresses[:3])
        combien = self._llm_count(len(adresses), "host", "hosts")
        combien_ports = self._llm_count(len(llm_fp.PORTS), "port", "ports")
        # Vidée avant que la piscine démarre : un balayage silencieux de
        # plusieurs secondes se lit comme un blocage, et l'en-tête est ce qui
        # dit ce qu'on attend et comment l'interrompre.
        print(
            f"🔎 {etiquette} · {combien} × {combien_ports}"
            f" · {t('Ctrl+C interrupts')}",
            flush=True,
        )
        debut = time.monotonic()
        try:
            touches = llm_disc.sweep(
                jobs,
                on_event=self._llm_sweep_printer(),
                **self._llm_sweep_tuning(),
            )
        except KeyboardInterrupt:
            print(f"\n⏹ {t('answer interrupted')}")
            return
        duree = time.monotonic() - debut
        trouves = []
        for adresse, port in touches:
            corps = llm_fp.collect(adresse, port, budget=2.0)
            empreinte = llm_fp.identify(corps, port=port, host=adresse)
            if not empreinte.software:
                print(f"  ⚠ {adresse}:{port} {t('Answered, not identified')}")
                continue
            print(
                f"  → {adresse}:{port} · {empreinte.software}"
                f" {empreinte.version} ·"
                f" {self._llm_count(len(empreinte.models), 'model', 'models')}"
            )
            trouves.append((adresse, port, empreinte))
        if not trouves:
            print(
                f"⚠ "
                + t("No server on %s (%s, %s, %ss).")
                % (
                    etiquette,
                    self._llm_count(len(adresses), "host", "hosts"),
                    self._llm_count(len(llm_fp.PORTS), "port", "ports"),
                    f"{duree:.0f}",
                )
            )
            if restreint:
                print(f"  ⚠ {t('Only part of that network was swept.')}")
            self._llm_nothing_found()
            return
        mot = (
            t("server recognized")
            if len(trouves) == 1
            else t("servers recognized")
        )
        print(
            f"  {len(trouves)} {mot},"
            f" {self._llm_count(len(adresses), 'host swept', 'hosts swept')}"
            f" ({self._fmt_dur(duree)})"
        )
        self._llm_keep(trouves)

    def _llm_keep(self, trouves):
        """Proposer de garder ce qui a été reconnu.

        Seuls les serveurs RETENUS descendent sur le disque. Aucun rapport de
        balayage, aucune table de vivacité, aucun résultat négatif : la liste
        de qui a répondu parmi 254 adresses décrit des machines que personne
        n'a nommées, et elle est plus sensible que le serveur voulu.
        """
        try:
            reponse = click.prompt(f"{t('Keep them all')} (o/N)")
        except (KeyboardInterrupt, click.exceptions.Abort):
            print()
            return
        if not self._is_yes(reponse):
            print(t("nothing kept"))
            return
        connus = llm_servers.load(get_config=self._llm_get_config)
        for adresse, port, empreinte in trouves:
            connus.append(
                llm_servers.Server(
                    handle="",
                    label=f"{empreinte.software} ({adresse}:{port})",
                    host=adresse,
                    port=port,
                    software=empreinte.software,
                    model=empreinte.models[0] if empreinte.models else "",
                    hosting=llm_caps.classify_hosting(adresse),
                    secret_ref="",
                )
            )
        llm_servers.save(
            llm_servers.assign_handles(connus),
            set_config=self._llm_set_config,
        )
        print(f"✅ {len(trouves)} {t('kept')}")

    def _llm_nothing_found(self):
        """Les suites concrètes, pour qu'un balayage vide ne soit pas une
        impasse. Le repli distant en est une : il répond aujourd'hui.

        En prose, et sans crochets numérotés : la question « où chercher »
        revient juste après avec sa propre numérotation, et deux séries de
        numéros qui ne se correspondent pas font retaper le mauvais.
        """
        print(
            f"  {t('Look somewhere else')} · {t('Type an address')}"
            f" · {t('Carry on with the OpenAI API (key from the vault)')}"
        )
        print(
            f"  💡 {t('A local server: \"ollama serve\" listens on 11434.')}"
        )

    def _llm_server_card(self):
        """Ce que le serveur en usage annonce savoir faire.

        Une capacité qu'il n'annonce pas s'affiche comme inconnue, jamais
        comme absente : la plupart des serveurs n'annoncent rien, et confondre
        les deux ferait passer un silence pour un refus.
        """
        serveur = self._llm_current()
        if serveur is None:
            print(t("no server yet"))
            return
        print(f"  {serveur.label} — {serveur.host}:{serveur.port}")
        print(f"  {t(self._llm_hosting_key(serveur.hosting))}")
        empreinte = llm_fp.identify(
            llm_fp.collect(serveur.host, serveur.port, budget=2.0),
            port=serveur.port,
            host=serveur.host,
        )
        caps = llm_caps.read(empreinte, serveur.host, serveur.port)
        for nom in (
            "context_window",
            "parameters",
            "tool_calling",
            "vision",
            "json_output",
        ):
            valeur = getattr(caps, nom)
            marque = " (?)" if valeur is None else ""
            print(f"  {nom}: {valeur}{marque}")

    @staticmethod
    def _llm_hosting_key(hosting):
        """La clé i18n qui nomme une classe d'hébergement."""
        return {
            "loopback": "this machine",
            "lan": "local network",
            "global": "third party",
        }.get(hosting, "third party")

    # ------------------------------------------------------------------
    # Les sessions Claude Code de la machine

    def prompt_claude_sessions(self):
        """Voir les sessions locales, en interroger une, ou la reprendre.

        Sous « GPT code » et non sous le sous-menu LLM : une session est un
        processus adressé par identifiant, un serveur est un hôte adressé par
        port. Les mêler dans une seule liste numérotée ferait partager cinq
        numéros à deux modèles mentaux, alors que toutes les entrées Claude
        vivent déjà ici.
        """
        # L'emoji vit dans la valeur traduite, jamais dans le code : le
        # mettre aux deux endroits en imprime deux.
        print(t("Claude Code - local sessions"))
        while True:
            flotte = self._claude_flotte()
            vivantes = sum(1 for session in flotte if session.live)
            compte = (
                f"{len(flotte)} · {vivantes} {t('live')}"
                if flotte
                else t("No session on this machine.")
            )
            choices = [
                {
                    "prompt_description": (
                        f"{t('List local sessions')}  ({compte})"
                    )
                },
                {"prompt_description": t("Ask a question to a session")},
                {
                    "prompt_description": t(
                        "Resume a session in a new terminal"
                    )
                },
            ]
            try:
                status = click.prompt(self.fill_help_info(choices))
            except (KeyboardInterrupt, click.exceptions.Abort):
                print()
                return
            print()
            if status == "0":
                return
            elif status == "1":
                self._claude_lister(flotte)
            elif status == "2":
                self._claude_questionner(flotte)
            elif status == "3":
                self._claude_reprendre(flotte)
            else:
                print(t("Command not found !"))

    def _claude_flotte(self):
        """La flotte, relue à chaque tour du menu.

        Relue et non gardée : une session démarre ou s'arrête dans un autre
        terminal pendant qu'on regarde la liste, et une liste périmée
        proposerait d'écrire dans un processus qui n'est plus là.
        """
        from script.todo.assistant import claude_sessions as cs

        return cs.fleet()

    def _claude_lister(self, flotte):
        """Afficher la flotte, sans rien lire d'une transcription.

        Ce qui paraît vient du registre, que tout compte de la machine peut
        déjà lire. Le titre d'une session, lui, vit dans la transcription, et
        celle-ci est sous un répertoire que le système ferme à son
        propriétaire : cette frontière n'est pas à rouvrir pour décorer une
        liste.
        """
        from script.todo.assistant import claude_sessions as cs

        if not flotte:
            print(t("No session on this machine."))
            return
        for rang, session in enumerate(flotte, 1):
            vue = cs.displayable(session)
            if vue["live"]:
                etat = (
                    f"{vue['kind']} · {t(vue['status'] or 'idle')}"
                    f" · {t('held by pid %s') % vue['pid']}"
                )
            else:
                etat = t("resumable, not running")
            print(f"  [{rang}] {vue['id']}  {etat}")
            print(
                f"        {vue['dir']}"
                f"{'  ' + vue['branch'] if vue['branch'] else ''}"
                f"{'  ' + vue['version'] if vue['version'] else ''}"
            )

    def _claude_choisir(self, flotte):
        """La session désignée par un rang, ou `None`."""
        if not flotte:
            print(t("No session on this machine."))
            return None
        self._claude_lister(flotte)
        try:
            reponse = click.prompt(t("Choice")).strip()
        except (KeyboardInterrupt, click.exceptions.Abort):
            print()
            return None
        if not reponse.isdigit():
            return None
        rang = int(reponse) - 1
        return flotte[rang] if 0 <= rang < len(flotte) else None

    def _claude_questionner(self, flotte):
        """Poser UNE question à une session, sans ouvrir de terminal.

        Deux garde-fous, et le second vient d'une mesure. L'invite part sur
        l'entrée standard : la ligne de commande d'un processus est lisible
        par tout compte de la machine, et une question porte du contexte.

        Et l'outil ne REFUSE pas de reprendre une session qu'un terminal
        tient : son garde-fou écarte délibérément les détenteurs interactifs.
        Deux écritures simultanées scindent alors la transcription, et une
        branche est perdue de la continuation. Une copie est donc branchée par
        défaut, et écrire dans la session tenue exige de retaper le pid du
        détenteur — recopier un nombre oblige à regarder ce qu'on fait.
        """
        import shutil

        from script.todo.assistant import backends as llm_backends
        from script.todo.assistant import claude_sessions as cs

        if not shutil.which("claude"):
            print(t("claude is not on the PATH."))
            return
        session = self._claude_choisir(flotte)
        if session is None:
            return
        fork = True
        detenteur = cs.held_by(session)
        if detenteur:
            avis = t("This session is open elsewhere. A branch would be lost.")
            print(f"⚠ {avis}")
            print(f"  [1] {t('Branch a copy (recommended)')}")
            print(f"  [2] {t('Write into the held session')}")
            try:
                choix = click.prompt(t("Choice")).strip()
            except (KeyboardInterrupt, click.exceptions.Abort):
                print()
                return
            if choix == "2":
                try:
                    frappe = click.prompt(
                        t("Type the pid of the holder to write into it:"),
                        prompt_suffix=" ",
                    ).strip()
                except (KeyboardInterrupt, click.exceptions.Abort):
                    print()
                    return
                if frappe != detenteur:
                    print(t("Nothing has been sent."))
                    return
                fork = False
            elif choix != "1":
                return
        try:
            question = click.prompt(t("Write your question "))
        except (KeyboardInterrupt, click.exceptions.Abort):
            print()
            return
        print(f"  {t('read-only: Read, Glob, Grep')}")
        backend = llm_backends.ClaudeCliBackend(
            session_id=session.session_id, cwd=session.cwd, fork=fork
        )
        try:
            texte, faits = backend.send(
                [{"role": "user", "content": question}]
            )
        except Exception as panne:
            print(f"⚠ {panne}")
            return
        print(texte)
        cout = faits.get("cost_usd") or faits.get("total_cost_usd")
        if cout:
            print(f"── {cout} USD ──")

    def _claude_reprendre(self, flotte):
        """Reprendre une session dans sa propre fenêtre.

        Une session interactive est un programme plein écran : elle a besoin
        d'un vrai terminal, que le tube du lanceur ordinaire ne fournit pas.
        Sans fenêtre possible — ni gnome-terminal, ni son équivalent — la
        commande est IMPRIMÉE plutôt que lancée sur un tube où elle ne
        survivrait pas.
        """
        import shlex
        import shutil

        chemin = shutil.which("claude")
        if not chemin:
            print(t("claude is not on the PATH."))
            return
        session = self._claude_choisir(flotte)
        if session is None:
            return
        commande = (
            f"{shlex.quote(chemin)} --resume"
            f" {shlex.quote(session.session_id)}"
        )
        if not getattr(self.execute, "cmd_source_default", ""):
            print(t("No terminal can be opened here. Paste this command:"))
            print(f"  cd {shlex.quote(session.cwd)} && {commande}")
            return
        self.execute.exec_command_live(
            f"cd {shlex.quote(session.cwd)} && {commande}",
            source_erplibre=False,
            new_window=True,
        )

    # ------------------------------------------------------------------
    # Le catalogue d'outils gpt

    def _llm_gpts(self):
        """Le catalogue, chargé une fois par session, avec ses problèmes.

        Chargé une seule fois parce que la liste des fichiers ne change pas
        pendant qu'on parle, et qu'un rechargement à chaque affichage relirait
        le disque pour rien.
        """
        state = self._llm_state()
        if state.get("gpts") is None:
            from script.todo.assistant import gpt as llm_gpt

            state["gpts"], state["gpt_problemes"] = llm_gpt.load_all()
        return state["gpts"], state["gpt_problemes"]

    def _llm_gpt_label(self):
        """L'étiquette de l'entrée du catalogue, avec ses comptes.

        Le nombre de compatibles se dit dès le menu : ouvrir un catalogue pour
        y découvrir que rien ne convient est une visite perdue.
        """
        gpts, problemes = self._llm_gpts()
        if not gpts:
            fatals = [souci for souci in problemes if souci.fatal]
            if fatals:
                return f"{t('gpt tools')}  ({len(fatals)} ⚠)"
            return f"{t('gpt tools')}  ({t('no gpt tool yet')})"
        compatibles = sum(
            1 for _, verdict, _ in self._llm_apparier(gpts) if verdict == "ok"
        )
        return (
            f"{t('gpt tools')}  ({len(gpts)},"
            f" {compatibles} {t('compatible')})"
        )

    def _llm_apparier(self, gpts):
        """[(gpt, verdict, raison)] — chaque outil confronté au serveur.

        Les capacités sont lues UNE fois par session et par serveur : chaque
        lecture coûte une requête au serveur, et la réponse ne change pas
        entre deux affichages du même catalogue.
        """
        from script.todo.assistant import capabilities as caps_mod

        serveur = self._llm_current() or REPLI_OPENAI
        state = self._llm_state()
        cle = (serveur.host, serveur.port, serveur.model)
        if state.get("caps_cle") != cle:
            from script.todo.assistant import fingerprint as fp_mod

            empreinte = fp_mod.identify(
                fp_mod.collect(serveur.host, serveur.port, budget=2.0),
                port=serveur.port,
                host=serveur.host,
            )
            state["caps"] = caps_mod.read(
                empreinte, serveur.host, serveur.port
            )
            state["caps_cle"] = cle
        caps = state["caps"]
        hosting = serveur.hosting
        return [
            (outil,) + caps_mod.match(outil.requires, caps, hosting)
            for outil in gpts
        ]

    def _llm_gpt_catalogue(self):
        """Choisir un outil, par lettre.

        Une lettre plutôt qu'un numéro : le menu qui précède numérote ses
        entrées, et une seconde liste numérotée juste après fait retaper un
        numéro de menu. Un chiffre reste accepté comme rang, parce que le
        doigt vient d'en taper un.

        Un outil ⛔ imprime sa raison et re-demande : il n'est jamais avalé en
        silence, et jamais lancé.
        """
        gpts, problemes = self._llm_gpts()
        fatals = [souci for souci in problemes if souci.fatal]
        if not gpts:
            for souci in fatals:
                self._llm_dire_probleme(souci)
            if not fatals:
                print(t("no gpt tool yet"))
            return
        while True:
            appariement = self._llm_apparier(gpts)
            serveur = self._llm_current() or REPLI_OPENAI
            print(f"{t('Which gpt tool?')}    {self._llm_label(serveur)}")
            for rang, (outil, verdict, raison) in enumerate(appariement):
                marque = MARQUE.get(verdict, "")
                # Le nom sur sa ligne, la description en dessous : un nom de
                # gpt est une phrase, et les deux bout à bout dépassent la
                # largeur d'un terminal — une entrée qui s'enroule se lit
                # moins bien que deux lignes assumées.
                print(f"  [{LETTRES[rang]}] {marque} {t(outil.name)}")
                print(f"        {t(outil.description)[:LARGEUR]}")
            print(f"  [0] {t('Back')}")
            if any(v != "ok" for _, v, _ in appariement):
                print(
                    f"      ⚠️ {t('a requirement could not be checked')}"
                    f" · ⛔ {t('a requirement is contradicted')}"
                )
            if fatals:
                print(
                    f"      ⚠ {len(fatals)} {t('unreadable gpt files')}"
                    f" — [d] {t('details')}"
                )
            try:
                reponse = click.prompt(t("Choice")).strip().lower()
            except (KeyboardInterrupt, click.exceptions.Abort):
                print()
                return
            if reponse in ("0", ""):
                return
            if reponse == "d" and fatals:
                for souci in problemes:
                    self._llm_dire_probleme(souci)
                continue
            rang = self._llm_rang(reponse, len(appariement))
            if rang is None:
                print(t("Command not found !"))
                continue
            outil, verdict, raison = appariement[rang]
            if verdict == "no":
                print(f"  ⛔ {self._llm_raison(outil, raison)}")
                continue
            self._llm_state()["gpt"] = outil
            print(f"✅ {t(outil.name)}")
            self._llm_conversation()
            return

    @staticmethod
    def _llm_rang(reponse, combien):
        """Le rang désigné par une lettre ou par un chiffre, sinon `None`."""
        if len(reponse) == 1 and reponse in LETTRES:
            rang = LETTRES.index(reponse)
            return rang if rang < combien else None
        if reponse.isdigit():
            rang = int(reponse) - 1
            return rang if 0 <= rang < combien else None
        return None

    def _llm_raison(self, outil, raison):
        """La raison d'un refus, ses trous remplis.

        Les clés portent des `%s` que seul l'appelant peut remplir : lui seul
        tient à la fois l'exigence déclarée et ce que le serveur annonce.
        """
        modele = t(raison)
        if "%s" not in modele:
            return modele
        caps = self._llm_state().get("caps")
        serveur = self._llm_current() or REPLI_OPENAI
        for champ in ("context_window", "parameters"):
            if champ in raison:
                return modele % (
                    outil.requires.get(champ),
                    getattr(caps, champ, None),
                )
        return modele % (t(self._llm_hosting_key(serveur.hosting)),)

    @staticmethod
    def _llm_dire_probleme(souci):
        """Un problème de chargement, traduit, avec son détail brut."""
        nom = f"{souci.stem} : " if souci.stem else ""
        detail = f" {souci.detail}" if souci.detail else ""
        print(f"  ⚠ {nom}{t(souci.key)}{detail}")

    # ------------------------------------------------------------------
    # La porte du contexte déclaré

    def _llm_demander_entrees(self, outil):
        """Les entrées déclarées, demandées une par une. `None` si l'on sort.

        Une valeur saisie n'est PAS validée ici : elle est substituée dans la
        commande, et c'est le contrôle du contexte qui la voit ensuite, avec
        la liste d'autorisation et le refus des métacaractères. Valider deux
        fois inviterait à valider différemment.
        """
        valeurs = {}
        for entree in outil.inputs:
            nom = entree.get("name")
            defaut = entree.get("default") or ""
            invite = f"{nom}" + (f" [{defaut}]" if defaut else "")
            try:
                donnee = click.prompt(invite, default=defaut).strip()
            except (KeyboardInterrupt, click.exceptions.Abort):
                print()
                return None
            if not donnee and entree.get("required"):
                print(t("Nothing has been sent."))
                return None
            valeurs[nom] = donnee
        return valeurs

    def _llm_context_gate(self, outil, serveur):
        """Assembler le contexte déclaré, le montrer, et demander.

        Rend le texte à joindre, ou `None` quand rien ne doit partir.

        La confirmation vaut pour la session et pour ce couple (outil,
        serveur) : la re-demander à chaque tour ferait cliquer sans lire, ce
        qui est le contraire de ce qu'une porte sert à obtenir. Un tiers est
        la seule exception — là, il n'y a pas de rattrapage.
        """
        from script import lib_identifiant
        from script.todo.assistant import context as ctx

        sources = outil.context or {}
        if not sources.get("files") and not sources.get("commands"):
            return ""
        entrees = self._llm_demander_entrees(outil)
        if entrees is None:
            return None
        termes = lib_identifiant.termes_interdits()
        texte, trouvailles = ctx.assemble(
            files=sources.get("files") or (),
            commands=sources.get("commands") or (),
            inputs=entrees,
            termes=termes,
        )
        verdict, cle = ctx.gate(
            trouvailles, serveur.hosting, names_checkable=bool(termes)
        )
        if verdict == ctx.BLOQUER:
            print(f"⛔ {t(cle)}")
            return None
        state = self._llm_state()
        sceau = (outil.stem, serveur.host, serveur.port)
        if verdict == ctx.OK and sceau in state["contextes"]:
            return texte
        if not self._llm_montrer_contexte(texte, trouvailles, cle):
            return None
        state["contextes"].add(sceau)
        return texte

    def _llm_montrer_contexte(self, texte, trouvailles, cle):
        """Montrer ce qui va partir, et demander. Vrai si l'on continue.

        Ce que la porte montre est ce qui décide : la taille, la tête, la
        queue, et chaque trouvaille nommée par sa source. Un aperçu qu'on ne
        peut pas relire ne vaut pas mieux qu'aucun aperçu.
        """
        lignes = texte.splitlines()
        print(f"── {t('What is about to be sent')} ──")
        print(f"   {len(texte)} {t('characters')}, {len(lignes)} {t('lines')}")
        for ligne in lignes[:6]:
            print(f"   {ligne[:100]}")
        if len(lignes) > 12:
            print(f"   … {len(lignes) - 12} …")
        for ligne in lignes[-6:] if len(lignes) > 12 else []:
            print(f"   {ligne[:100]}")
        if trouvailles:
            print(f"   ⚠ {len(trouvailles)} {t(cle)}")
            for trouvaille in trouvailles[:8]:
                print(
                    f"     {trouvaille['source']} · {trouvaille['motif']}"
                    f" · {trouvaille['extrait']}"
                )
        print(f"   {t('What the filter checks')}")
        try:
            reponse = click.prompt(f"[c] {t('continue')} · [0] {t('cancel')}")
        except (KeyboardInterrupt, click.exceptions.Abort):
            print()
            return False
        if reponse.strip().lower() != "c":
            print(t("Nothing has been sent."))
            return False
        return True

    # ------------------------------------------------------------------
    # La conversation

    def _llm_openai_key(self):
        """La clé du coffre, ou une chaîne vide quand il n'en porte aucune.

        La clé reste en mémoire du processus : /proc expose la ligne de
        commande de chaque processus à tout compte de la machine, et aucun
        caviardage n'atteint argv. Le filtre du dépôt masque « API_KEY » et
        « Bearer » dans une trace, ce qui est le dernier rempart et non le
        premier.
        """
        kp = self.kdbx_manager.get_kdbx()
        if not kp:
            return ""
        titre = self.config_file.get_config_value(
            ["kdbx_config", "openai", "kdbx_key"]
        )
        entree = kp.find_entries_by_title(titre, first=True)
        return getattr(entree, "password", "") or ""

    def _llm_confirm_third_party(self, serveur):
        """Retaper la destination avant le premier envoi vers un tiers.

        Une frappe sur « o » se donne par réflexe ; recopier l'adresse oblige
        à regarder où part le texte. La confirmation vaut pour la session et
        pour cette destination seulement.
        """
        if serveur.hosting != "global":
            return True
        state = self._llm_state()
        if serveur.host in state["confirmes"]:
            return True
        avis = t("This destination is a third party. Retype it to confirm:")
        print(f"⚠ {avis}")
        try:
            frappe = click.prompt(serveur.host).strip()
        except (KeyboardInterrupt, click.exceptions.Abort):
            print()
            return False
        if frappe != serveur.host:
            print(t("Destination not retyped — nothing was sent."))
            return False
        state["confirmes"].add(serveur.host)
        return True

    def _llm_conversation(self):
        """La boucle de conversation.

        L'invite d'une ligne EST la ligne d'état : elle porte le serveur et le
        modèle, elle est réimprimée par la lecture à chaque tour, et elle ne
        peut donc pas défiler hors de l'écran. Le bloc d'en-tête, lui, ne
        s'imprime qu'une fois.
        """
        from script.todo.assistant import backends as llm_backends
        from script.todo.assistant import chat as llm_chat

        self._llm_quiet_http()
        serveur = self._llm_current()
        cle = ""
        if serveur is None:
            serveur = REPLI_OPENAI
            cle = self._llm_openai_key()
            if not cle:
                print(
                    t(
                        "The vault holds no OpenAI key: configure a server or"
                        " a key."
                    )
                )
                return
            print(f"↑ {t('via api.openai.com (key from the vault)')}")
        elif serveur.secret_ref:
            cle = self._llm_openai_key()
        if not self._llm_confirm_third_party(serveur):
            return
        print(
            t(
                "The history lives in memory and dies with this menu. /save"
                " writes it to a file."
            )
        )
        print(t("Commands start with a slash. /? lists them."))
        outil = self._llm_state().get("gpt")
        systeme = ""
        if outil is not None:
            joint = self._llm_context_gate(outil, serveur)
            if joint is None:
                # La porte a refusé, ou l'utilisateur a annulé : rien ne part,
                # et la conversation ne s'ouvre pas avec un contexte amputé.
                return
            systeme = "\n\n".join(
                part for part in (outil.system, joint) if part
            )
        backend = llm_backends.HttpBackend(
            serveur,
            serveur.model,
            api_key=cle or None,
            params=dict(outil.params) if outil is not None else None,
        )
        conversation = llm_chat.Conversation(backend, system=systeme)
        # Le RADICAL du nom de fichier, et non le nom traduit : celui-ci est
        # une phrase, et l'invite d'état est réimprimée à chaque tour. Un
        # radical est court, stable, et désigne le fichier sans ambiguïté.
        marque_outil = f" · {outil.stem}" if outil is not None else ""
        invite = (
            f"{self._llm_label(serveur)}{marque_outil}"
            f" · {t(self._llm_hosting_key(serveur.hosting))} ▸ "
        )
        while True:
            try:
                ligne = input(invite)
            except (KeyboardInterrupt, click.exceptions.Abort, EOFError):
                # Ctrl+C et Ctrl+D rendent la main au menu. Sans cette
                # capture, `Abort` remonterait jusqu'à `__main__`, qui termine
                # le CLI entier.
                print()
                return
            commande, reste = llm_chat.parse_command(ligne)
            if commande == "/q":
                return
            if commande == "/?":
                for nom in COMMANDES_PHASE_1:
                    print(f"  {nom}  {t(llm_chat.COMMANDS[nom])}")
                continue
            if commande == "/new":
                jetes = conversation.reset()
                print(f"  {jetes} {t('turns dropped')}")
                continue
            if commande == "/gpt":
                self._llm_gpt_catalogue()
                return
            if commande == "/srv":
                self._llm_servers()
                return
            if commande == "/ctx":
                for message in conversation.last_sent:
                    print(f"  [{message['role']}] {message['content']}")
                continue
            if commande == "/save":
                self._llm_save(conversation)
                continue
            if commande == "/m":
                reste = self._llm_multiline()
            elif commande is not None:
                print(t("Command not found !"))
                continue
            if not reste.strip():
                continue
            tour = conversation.ask(reste)
            if tour.role == "error":
                print(f"⚠ {tour.text}")
                continue
            print(tour.text)
            if tour.interrupted:
                print(f"⏹ {t('answer interrupted')}")
            # Le pied de ligne existe pour une réponse qui a défilé : il dit
            # sa longueur et où l'écrire. Sous deux lignes, il n'apprend rien
            # et le pluriel sonnerait faux.
            lignes = len(tour.text.splitlines())
            if lignes > 1:
                print(
                    f"── {lignes} {t('lines')} ·"
                    f" {t('/save to write it to a file')} ──"
                )

    @staticmethod
    def _llm_quiet_http():
        """Retirer la ligne de journal que le client HTTP écrit par requête.

        `todo.py` pose un gestionnaire sur le logger RACINE à l'import, et
        `httpx` journalise chaque requête en INFO : sans ceci, « HTTP Request:
        POST … 200 OK » s'imprime au-dessus de CHAQUE réponse, au milieu de la
        conversation.

        Brancher un niveau est le travail de L'APPLICATION, pas d'une
        bibliothèque : la méthode vit donc dans le menu, et non dans
        `backends.py`. `openai` porte son propre logger pour la même raison.

        La liste porte DEUX noms de transport parce que le client `openai` ne
        choisit pas toujours le même : le venv installe `httpx` et `httpx2`
        côte à côte, et c'est la version du client qui décide lequel émet.
        Ne nommer que l'un laisse la ligne passer sans que rien ne le signale,
        puisqu'une ligne de journal n'est pas une panne.
        """
        import logging

        for nom in ("httpx", "httpx2", "httpcore", "openai"):
            logging.getLogger(nom).setLevel(logging.WARNING)

    @staticmethod
    def _llm_multiline():
        """Une question sur plusieurs lignes, terminée par une ligne « . ».

        Une question collée ligne à ligne deviendrait autant de tours, donc
        autant d'appels facturés, et une ligne collée valant « 0 » aurait
        déclenché une entrée de menu avant que les commandes ne portent une
        barre oblique. Ce mode rend un envoi unique.
        """
        lignes = []
        while True:
            try:
                suite = input("… ")
            except (KeyboardInterrupt, EOFError):
                print()
                break
            if suite.strip() == ".":
                break
            lignes.append(suite)
        return "\n".join(lignes)

    def _llm_save(self, conversation):
        """Écrire la conversation sous ~/.erplibre/assistant/.

        Le répertoire se crée en 0700 et le fichier en 0600 : `~/.erplibre`
        est lisible par tous les comptes de la machine, et une conversation
        porte ce que la session y a collé.

        Le nom de fichier est tiré du compteur de tours, jamais d'une
        horloge : une date rendrait le fichier reconnaissable dans le temps
        sans rien apporter à qui le relit.
        """
        base = os.path.join(os.path.expanduser("~/.erplibre"), "assistant")
        os.makedirs(base, mode=0o700, exist_ok=True)
        os.chmod(base, 0o700)
        chemin = os.path.join(
            base, f"conversation-{len(conversation.turns)}.md"
        )
        drapeaux = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        with os.fdopen(os.open(chemin, drapeaux, 0o600), "w") as fichier:
            fichier.write(conversation.transcript())
        print(f"✅ {t('Conversation written to')} {chemin}")
