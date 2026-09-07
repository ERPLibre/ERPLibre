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
COMMANDES_PHASE_1 = ("/?", "/q", "/new", "/srv", "/ctx", "/m", "/save")

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
                self._llm_servers()
            elif status == "3":
                self._llm_search()
            elif status == "4":
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
                t("Type the server name in full to delete it:")
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
                            f"{t('local network')}  {interface.cidr}"
                            f" · {interface.name}{pont}"
                        )
                    }
                )
            choices.append({"prompt_description": t("An address I type")})
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

    def _llm_search_network(self, interface):
        """Balayer un /24, une fois seulement que le CIDR a été nommé.

        C'est la seule action de ce menu qui atteigne des machines que
        personne n'a désignées : la confirmation nomme donc le réseau et les
        comptes exacts, et le défaut se limite aux hôtes que la table de
        voisinage dit avoir déjà parlé — ils ne coûtent rien à connaître et
        ne supposent aucun droit.

        La lettre « t » élargit aux 254. Un troisième numéro juste après un
        menu numéroté invite à retaper un numéro de menu ; une lettre dit
        qu'on répond à autre chose.
        """
        from script.todo.assistant import discover as llm_disc

        jobs = llm_disc.plan_sweep(
            interface.cidr, skip=self._qemu_host_addresses()
        )
        if not jobs:
            print(f"⚠ {t('Wider than a /24 is refused.')}")
            print(
                t(
                    "The /24 is an assumption: a prefix does not follow from"
                    " an address."
                )
            )
            return
        voisins = llm_disc.neigh_hosts(llm_disc.run_ip(["neigh"]))
        connus = [
            adresse
            for adresse in voisins
            if any(adresse == ip for ip, _ in jobs)
        ]
        print(
            f"⚠ {t('Sweeping the network reaches machines you did not name.')}"
        )
        if connus:
            print(
                f"  {t('Only the hosts that have already spoken (ip neigh)')}"
                f" : {self._llm_count(len(connus), 'host', 'hosts')}"
            )
            cibles = connus
        else:
            cibles = sorted({ip for ip, _ in jobs})
        question = t("Sweep %s addresses × %s ports on %s?") % (
            len(cibles),
            len(llm_fp.PORTS),
            interface.cidr,
        )
        try:
            reponse = click.prompt(f"{question} (o/N, « t » = 254)")
        except (KeyboardInterrupt, click.exceptions.Abort):
            print()
            return
        if reponse.strip().lower() == "t":
            cibles = sorted({ip for ip, _ in jobs})
        elif not self._is_yes(reponse):
            return
        self._llm_probe_and_keep(cibles, cible=interface.cidr)

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

    def _llm_probe_and_keep(self, adresses, *, cible=None):
        """Frapper, reconnaître, puis proposer de garder.

        Le balayage n'ouvre que des connexions ; la reconnaissance, elle,
        coûte une requête HTTP par étage et ne part donc QUE vers les hôtes
        qui ont accepté. C'est ce qui rend un /24 abordable.
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
            touches = llm_disc.sweep(jobs, on_event=self._llm_sweep_printer())
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
    # La conversation

    def _llm_openai_key(self):
        """La clé du coffre, ou une chaîne vide quand il n'en porte aucune.

        La clé reste en mémoire du processus : /proc expose la ligne de
        commande de chaque processus à tout compte de la machine, et un
        `redact_secrets` qui ne reconnaît pas « API_KEY » ne la masquerait pas
        non plus dans une trace.
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
        backend = llm_backends.HttpBackend(
            serveur, serveur.model, api_key=cle or None
        )
        conversation = llm_chat.Conversation(backend)
        invite = (
            f"{self._llm_label(serveur)}"
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
