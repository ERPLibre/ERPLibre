<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# The LLM assistant — who answers, and what may be said to them

`script/todo/assistant/` is what `Assistant › LLM` runs: it recognises the
model server listening on a port, reads what that server announces it can do,
keeps the ones you chose, and holds the conversation.

## A port says where to knock, never who answers

This is the one thing to understand before reading any of the code. Port 8080
hosts llama.cpp, LocalAI **and** Open WebUI; port 5000 hosts
text-generation-webui **and** TabbyAPI; `/v1/models` is served by eleven of
the twelve families. A port therefore opens the question — it never answers
it.

Identity is read in the **body** of a response, by a ladder of thirteen
stages over eleven ports, first agreement wins. The order of that ladder
carries the whole reasoning. LocalAI re-serves Ollama's native API **in
full** — `/api/tags`, `/api/show`, `/api/ps`, `/api/version` — down to the
`Ollama is running` string on `/`. The endpoints that look like Ollama's
therefore do not identify Ollama. LocalAI is separated **first**, by
`GET /readyz`, which Ollama does not have and answers 404 on; the Ollama
stage is reachable only because that separation already happened. Moving the
LocalAI stage further down names every LocalAI machine "ollama".

`identify()` is pure — it takes bytes already read — so the order of the
ladder is verified without opening a socket. `collect()` is transport only,
and it emits GET alone, with no body and no `Authorization` header: a scan
must not be able to load a model or spend a token.

## An address never becomes prompt text

An SSH alias, a host name, an IP address, a VM name all designate machines
that announce themselves nowhere else. Each retained server therefore carries
an opaque **handle** — `server-1` — assigned by its rank at load, and that is
the only form allowed to circulate: `redacted()` renders `server-1 (ollama)`,
and that is what may reach a prompt, a command argument or a file the
repository tracks. The host, the port and the label serve the menu display
and the private configuration, and stop there.

The restraint is structural because it **cannot** be a filter. The
repository's detector recognises addresses, e-mails and account paths, and
returns an empty list in front of a host name, an SSH alias or a database
name. What no guard rail ever sees go past must not be in a position to go
past.

## The menu

`Assistant › LLM` carries four entries today. `[2] gpt tools` does not exist
yet, and an entry answering "not yet" would be worse than its absence: phase
3 inserts it and renumbers.

| Entry | What it does |
|-------|--------------|
| Free question | the conversation with the server in use, or the remote fallback when no local one answered |
| Known servers | list, pick, add by hand, delete |
| Search for a server… | here on the loopback, or an address you type |
| Server card | what the server in use announces it can do |

A third-party destination has to be **retyped** before the first send —
once per session, and for that destination only. A keystroke on "y" is given
by reflex; copying the address makes you look at where the text goes.

The conversation history lives **in memory and nowhere else** — nothing in
`chat.py` opens a file. It dies with the menu, and `/save` is the only way to
keep a trace of it, which the header says before the conversation that
deserved keeping. Every command carries a leading slash and no bare number is
one: a question pasted over several lines becomes that many turns, and a
pasted line reading `0` would otherwise trigger a menu entry.

Host discovery beyond the loopback — QEMU domains, `~/.ssh/config`, a sweep
of the local `/24` — arrives with `discover.py` in phase 2.

## Where a server is written, and what is not

Writing goes through `config_file.set_config_value()`, and through it alone.
Of the three files the read merges, it is the only one that is gitignored:

| Path | Status |
|------|--------|
| `script/todo/todo.json` | tracked, follows the repository upstream |
| `private/todo/todo_override.json` | not ignored — committable, and public on a fork made public |
| `private/todo/todo_override_private.json` | gitignored — where a server is written |

`set_config_value()` merges instead of overwriting, and writes atomically: a
temporary created 0600 in the same directory, then `os.replace`. One section
is written, under the key path `assistant › servers`, seven fields per
server, every one of them chosen by you or read from the server you pointed
at. The handle is not written: it is reassigned by rank at load, and a rank
frozen on disk would outlive the deletion of a neighbour.

Nothing else is written — **no scan report, no liveness table, no negative
result, no timestamped log**. The list of who answered among the 254
addresses of a `/24` describes machines nobody designated, where a retained
server designates exactly one, on purpose.

## The modules

| File | What it owns |
|------|--------------|
| `__init__.py` | the two rules that govern everything below |
| `fingerprint.py` | who answers on a port: the ladder, and its transport |
| `capabilities.py` | what a server announces it can do, in three tiers of honesty, and matching a requirement against it |
| `servers.py` | the retained servers: opaque handles, reading and writing |
| `backends.py` | speaking to one destination: an HTTP server, or the `claude` CLI |
| `chat.py` | the turns of a conversation, and the commands that drive it |
| `../assistant_menu.py` | the mixin: asking and displaying, outside the package |

None of these modules imports `todo.py`, which costs close to a second and
prints on its way in. The menu mixin is what wires them onto the CLI, and a
subprocess test in `test_assistant_menu.py` fails the day one of them
reaches for it.

<!-- [fr] -->
# L'assistant LLM — qui répond, et ce qu'on a le droit de lui dire

`script/todo/assistant/` est ce que lance `Assistant › LLM` : il reconnaît le
serveur de modèle qui écoute sur un port, lit ce que ce serveur annonce
savoir faire, garde ceux qu'on a choisis, et tient la conversation.

## Un port dit où frapper, jamais qui répond

C'est la seule chose à comprendre avant de lire une ligne du code. Le port
8080 héberge llama.cpp, LocalAI **et** Open WebUI ; le port 5000 héberge
text-generation-webui **et** TabbyAPI ; `/v1/models` est servi par onze des
douze familles. Un port ouvre donc la question — il n'y répond jamais.

L'identité se lit dans le **corps** d'une réponse, par une échelle de treize
étages sur onze ports, arrêt au premier accord. L'ordre de cette échelle
porte tout le raisonnement. LocalAI réémet l'API native d'Ollama **en
entier** — `/api/tags`, `/api/show`, `/api/ps`, `/api/version` — jusqu'à la
chaîne `Ollama is running` sur `/`. Les points de terminaison qui ressemblent
à ceux d'Ollama n'identifient donc pas Ollama. LocalAI s'écarte le
**premier**, par `GET /readyz`, qu'Ollama ne possède pas et où il rend 404 ;
l'étage Ollama n'est atteignable que parce que cet écart a déjà eu lieu.
Déplacer l'étage LocalAI plus bas nomme « ollama » toutes les machines
LocalAI.

`identify()` est pure — elle ne reçoit que des octets déjà lus — donc l'ordre
de l'échelle se vérifie sans ouvrir une socket. `collect()` ne fait que le
transport, et n'émet que des GET, sans corps et sans en-tête
`Authorization` : un balayage ne doit pouvoir ni charger un modèle, ni
dépenser un jeton.

## Une adresse ne devient jamais du texte de prompt

Un alias SSH, un nom d'hôte, une adresse IP, un nom de VM désignent des
machines qui ne s'annoncent nulle part ailleurs. Chaque serveur retenu porte
donc une **poignée** opaque — `server-1` — attribuée par son rang au
chargement, et c'est la seule forme qui a le droit de circuler : `redacted()`
rend `server-1 (ollama)`, et c'est cela qui peut atteindre une invite, un
argument de commande ou un fichier que le dépôt suit. L'hôte, le port et le
libellé servent à l'affichage du menu et à la configuration privée, et
s'arrêtent là.

La retenue est structurelle parce qu'elle ne **peut pas** être un filtre. Le
détecteur du dépôt reconnaît les adresses, les courriels et les chemins de
compte, et rend une liste vide devant un nom d'hôte, un alias SSH ou un nom
de base de données. Ce qu'aucun garde-fou ne voit passer ne doit pas être en
position de passer.

## Le menu

`Assistant › LLM` porte quatre entrées aujourd'hui. `[2] Outils gpt`
n'existe pas encore, et une entrée qui répondrait « pas encore » serait pire
que son absence : la phase 3 l'insère et renumérote.

| Entrée | Ce qu'elle fait |
|--------|-----------------|
| Question libre | la conversation avec le serveur en usage, ou le repli distant quand aucun local n'a répondu |
| Serveurs connus | lister, choisir, ajouter à la main, supprimer |
| Chercher un serveur… | ici sur la boucle locale, ou une adresse qu'on tape |
| Fiche du serveur | ce que le serveur en usage annonce savoir faire |

Une destination tierce doit être **retapée** avant le premier envoi — une
fois par session, et pour cette destination seulement. Une frappe sur « o »
se donne par réflexe ; recopier l'adresse oblige à regarder où part le
texte.

L'historique de la conversation vit **en mémoire et nulle part ailleurs** —
rien dans `chat.py` n'ouvre un fichier. Il meurt avec le menu, et `/save` est
le seul moyen d'en garder une trace, ce que l'en-tête dit AVANT la
conversation qui méritait d'être gardée. Toute commande porte une barre
oblique initiale et aucun nombre nu n'en est une : une question collée sur
plusieurs lignes devient autant de tours, et une ligne collée valant `0`
déclencherait sinon une entrée de menu.

La découverte d'hôtes au-delà de la boucle locale — domaines QEMU,
`~/.ssh/config`, balayage du `/24` local — arrive avec `discover.py` en
phase 2.

## Où s'écrit un serveur, et ce qui ne s'écrit pas

L'écriture passe par `config_file.set_config_value()`, et par lui seul. Des
trois fichiers que la lecture fusionne, c'est le seul qui soit gitignored :

| Chemin | État |
|--------|------|
| `script/todo/todo.json` | suivi, il suit le dépôt en amont |
| `private/todo/todo_override.json` | non ignoré — commitable, et public sur un fork rendu public |
| `private/todo/todo_override_private.json` | gitignored — là où s'écrit un serveur |

`set_config_value()` fusionne au lieu d'écraser, et écrit atomiquement : un
temporaire créé en 0600 dans le même dossier, puis `os.replace`. Une seule
section est écrite, sous le chemin de clés « assistant › servers », sept
champs par serveur, tous fournis par l'utilisateur ou lus sur le serveur
qu'il a désigné. La poignée n'est pas écrite : elle se rattribue par le rang
au chargement, et un rang figé sur le disque survivrait à la suppression d'un
voisin.

Rien d'autre n'est écrit — **ni rapport de balayage, ni table de qui est
vivant, ni résultat négatif, ni journal horodaté**. La liste de qui a répondu
parmi les 254 adresses d'un `/24` décrit des machines que personne n'a
désignées, là où un serveur retenu en désigne une seule, volontairement.

## Les modules

| Fichier | Ce qu'il porte |
|---------|----------------|
| `__init__.py` | les deux règles qui gouvernent tout ce qui suit |
| `fingerprint.py` | qui répond sur un port : l'échelle, et son transport |
| `capabilities.py` | ce qu'un serveur annonce savoir faire, en trois paliers d'honnêteté, et l'appariement d'une exigence |
| `servers.py` | les serveurs retenus : poignées opaques, lecture et écriture |
| `backends.py` | parler à une destination : un serveur HTTP, ou le CLI `claude` |
| `chat.py` | les tours d'une conversation, et les commandes qui la pilotent |
| `../assistant_menu.py` | le mixin : demander et afficher, hors du paquet |

Aucun de ces modules n'importe `todo.py`, qui coûte près d'une seconde et
imprime en arrivant. C'est le mixin du menu qui les branche sur le CLI, et un
test par sous-processus dans `test_assistant_menu.py` tombe en rouge le jour
où l'un d'eux y touche.

<!-- [en] -->
## Tests

<!-- [fr] -->
## Tests

<!-- [common] -->
```bash
make test_unit_file F=test/test_assistant_fingerprint.py
PYTHONPATH=. ./.venv.erplibre/bin/python test/test_assistant_servers.py
for f in test/test_assistant_*.py; do
  PYTHONPATH=. ./.venv.erplibre/bin/python "$f"
done
```
