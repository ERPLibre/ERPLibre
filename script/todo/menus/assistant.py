#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus de la famille Assistant : LLM, ses serveurs connus et la
recherche d'un serveur.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place.

Une entrée qui efface, ou qui sonde sans confirmation des hôtes que
l'utilisateur a nommés ailleurs, porte `danger` : ni la TUI de télémétrie
ni la page web ne la lancent, son menu seul.
"""

from script.todo.ui.registry import Entry, FromMethod, Menu, Section

LLM = Menu(
    "prompt_assistant_llm",
    "LLM",
    [
        Section("Talk"),
        Entry("Free question", "_llm_conversation", suffix="_llm_talks_to"),
        Entry("gpt tools", "_llm_gpt_catalogue", suffix="_llm_gpt_count"),
        Section("Server"),
        Entry("Known servers", "_llm_servers", suffix="_llm_servers_count"),
        Entry("Search for a server…", "_llm_search"),
        Entry("Server card", "_llm_server_card", suffix="_llm_card_hint"),
    ],
    intro="A server, a gpt tool, a conversation.",
    back=None,
    abort_closes=True,
)

# Sans serveur connu, Servers passe à la recherche sans se dessiner
# (`opens`) ; sinon il liste les serveurs connus, relus à chaque dessin.
SERVERS = Menu(
    "_llm_servers",
    "Servers",
    [
        FromMethod("_llm_known_servers", "_llm_use_server", "server"),
        Section("Server"),
        Entry("Add a server by hand", "_llm_add_server"),
        Entry("Delete a server", "_llm_delete_server", danger=True),
    ],
    back=None,
    abort_closes=True,
    opens="_llm_servers_open",
)

# Search redit sa question avant chaque réponse (`before`), et offre les
# réseaux que la machine porte, relus à chaque dessin.
SEARCH = Menu(
    "_llm_search",
    "Search",
    [
        Entry("Here (127.0.0.1)", "_llm_search_here", suffix="_llm_here_hint"),
        # Les VM de la machine et les hôtes de ~/.ssh/config se sondent, onze
        # ports chacun, dès l'entrée choisie, sans confirmation : `danger`.
        Entry(
            "The QEMU VMs of this machine (virsh)",
            "_llm_search_qemu",
            danger=True,
        ),
        Entry("The hosts of ~/.ssh/config", "_llm_search_ssh", danger=True),
        FromMethod("_llm_networks", "_llm_search_network", "network"),
        Entry("An address I type", "_llm_add_server"),
        Entry("A network I type (CIDR)", "_llm_search_cidr"),
        Entry("The networks of a machine over SSH", "_llm_search_remote"),
    ],
    back=None,
    abort_closes=True,
    before="_llm_search_where",
)
