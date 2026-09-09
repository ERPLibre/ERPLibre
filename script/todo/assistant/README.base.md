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

`Assistant › LLM` carries five entries.

| Entry | What it does |
|-------|--------------|
| Free question | the conversation with the server in use, or the remote fallback when no local one answered |
| gpt tools | the catalogue, compatible ones first, picked by letter |
| Known servers | list, pick, add by hand, delete |
| Search for a server… | six sources, from the loopback to a typed network |
| Server card | what the server in use announces it can do |

Entries are picked by number, the catalogue by LETTER. A second numbered list
right after a numbered menu invites retyping a menu entry, and this repository
has already paid for that once. A digit is still accepted there as a rank,
because the finger has just typed one.

A third-party destination has to be **retyped** before the first send —
once per session, and for that destination only. A keystroke on "y" is given
by reflex; copying the address makes you look at where the text goes.

The conversation history lives **in memory and nowhere else** — nothing in
`chat.py` opens a file. It dies with the menu, and `/save` is the only way to
keep a trace of it, which the header says before the conversation that
deserved keeping. Every command carries a leading slash and no bare number is
one: a question pasted over several lines becomes that many turns, and a
pasted line reading `0` would otherwise trigger a menu entry.

## Finding a server that is not here

Four sources answer "where should I look": the loopback, the QEMU domains of
this machine, the hosts of `~/.ssh/config`, and a swept `/24`. Two of them are
INJECTED — enumerating libvirt domains and resolving an SSH alias already
exist as methods of the CLI class, which this package may not import.

A server often lives on a network this machine does not CARRY, reachable
through the gateway: when the CLI runs inside a virtual machine, the "local
network" it sees is the hypervisor's. Two sources answer that — a typed CIDR,
and the networks read over SSH on another machine then swept from here. The
neighbour table cannot: it is link-local, so a routed host never appears in
it.

Anything wider than a `/24` is refused, and the refusal happens BEFORE
enumeration — measuring a `/8` by materialising it would cost sixteen million
addresses. The pool is sized by WAVE COUNT and never by core count: these
threads wait on the network. And the connection timeout is the one setting
here that manufactures FALSE NEGATIVES — a host reachable in one millisecond
when idle is missed at five hundredths under a thousand simultaneous
connections, so it does not follow from measured latency.

## The gpt catalogue

A gpt is one Markdown file: YAML front-matter, a system prompt, and a declared
READ-ONLY context. Nothing in it runs on the model's behalf.

Its requirements are matched against what the server announces, and one rule
governs the display: UNKNOWN NEVER GREYS OUT. Only a requirement contradicted
by a field actually read from the server does — greying on the unknown would
empty the catalogue in front of a server that announces nothing, which is to
say in front of most of them. An estimated value never greys either.

`yaml.safe_load` is no validator, and that shapes the loader. Front-matter
that is a list returns a list, a scalar returns a string, an empty file
returns nothing, and a REPEATED key resolves silently to the last — so two
`requires` blocks changed a gpt's safety class without a word. Hence a type
check and a re-read of the raw text.

A gpt from outside the repository is forced to loopback and may declare no
command at all: a file nobody reviewed is configuration, not data.

## What a declared context may read

The deny list comes first and resolves the REAL path: neither "tracked by
git" nor "ignored by git" is a usable gate, since `private/` is partly tracked
and `tasks/` is in no ignore file. A symlink is therefore resolved before it
is compared.

A command is an argv, never an interpreter string, and it is checked against
an allowlist that lives in the repository. Substitution of a typed input
happens BEFORE that check, never after: validating a template and then
injecting a value would validate what is not run.

Every assembled byte passes the repository's detector — and the honest limit
is stated rather than hidden. It recognises addresses, e-mails and account
paths. It does NOT recognise names, unless a list enumerates them, and that
list does not usually exist. An absence of findings therefore proves nothing
about names, and a send to a third party is REFUSED in that case even with no
finding at all.

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

## The machine's Claude Code sessions

A session open elsewhere already holds a piece of work, and asking it one
question without retyping that is worth the trip. It sits under `GPT code`
rather than the LLM submenu: a session is a process addressed by identifier, a
server is a host addressed by port, and mixing the two in one numbered list
would make two mental models share the same digits.

Two hazards had to be measured before offering it. A pid does not prove a
session lives — pids are recycled, so liveness needs the pid AND the process's
start time. And the tool does not REFUSE to resume a session a terminal holds,
its guard skipping interactive holders; two writers then split the transcript
and one branch is orphaned. A copy is branched by default, and writing into a
held session requires retyping the holder's pid.

The privacy boundary is the one the system already drew. The registry is
world-readable, so pid, directory, name and identifier are no secret there.
Transcripts are not: only two STRUCTURAL fields come out of them — the working
directory and the git branch — never a title, a prompt or a message. The
working directory is read there rather than derived from the containing
directory's name, because that transformation turns separators, dots and
underscores all into dashes and so cannot be inverted.

## The modules

| File | What it owns |
|------|--------------|
| `__init__.py` | the two rules that govern everything below |
| `fingerprint.py` | who answers on a port: the ladder, and its transport |
| `capabilities.py` | what a server announces it can do, in three tiers of honesty, and matching a requirement against it |
| `servers.py` | the retained servers: opaque handles, reading and writing |
| `backends.py` | speaking to one destination: an HTTP server, or the `claude` CLI |
| `chat.py` | the turns of a conversation, and the commands that drive it |
| `discover.py` | which (host, port) pairs are worth a fingerprint, and the knock |
| `gpt.py` | the catalogue: loading, refusing, and never crashing the menu |
| `context.py` | what a declared context may read, and what the gate allows |
| `claude_sessions.py` | the machine's Claude Code sessions: which live, which resume |
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

`Assistant › LLM` porte cinq entrées.

| Entrée | Ce qu'elle fait |
|--------|-----------------|
| Question libre | la conversation avec le serveur en usage, ou le repli distant quand aucun local n'a répondu |
| Outils gpt | le catalogue, les compatibles en tête, choisis par lettre |
| Serveurs connus | lister, choisir, ajouter à la main, supprimer |
| Chercher un serveur… | six sources, de la boucle locale à un réseau saisi |
| Fiche du serveur | ce que le serveur en usage annonce savoir faire |

Les entrées se choisissent par numéro, le catalogue par LETTRE. Une seconde
liste numérotée juste après un menu numéroté invite à retaper une entrée de
menu, et ce dépôt l'a déjà payé une fois. Un chiffre y reste accepté comme
rang, parce que le doigt vient d'en taper un.

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
`~/.ssh/config`, balayage du `/24` local — repose sur quatre sources, dont
deux sont INJECTÉES : l'énumération des domaines libvirt et la résolution d'un
alias SSH existent déjà comme méthodes de la classe du CLI, que ce paquet n'a
pas le droit d'importer.

Un serveur vit souvent sur un réseau que cette machine ne PORTE pas, joignable
par la passerelle : quand le CLI tourne dans une machine virtuelle, le
« réseau local » qu'il voit est celui de l'hyperviseur. Deux sources y
répondent — un CIDR saisi, et les réseaux lus en SSH sur une autre machine
puis balayés d'ici. La table de voisinage, elle, ne peut pas : elle est
link-local, donc un hôte routé n'y figure jamais.

Plus large qu'un `/24` est refusé, et le refus précède l'énumération —
mesurer un `/8` en le matérialisant coûterait seize millions d'adresses. La
piscine se dimensionne par NOMBRE DE VAGUES et jamais par nombre de cœurs :
ces fils attendent le réseau. Et le délai de connexion est le seul réglage
d'ici qui fabrique des FAUX NÉGATIFS — un hôte joignable en une milliseconde
au repos se manque à cinq centièmes sous mille connexions simultanées, donc il
ne se déduit pas de la latence mesurée.

## Le catalogue d'outils gpt

Un gpt est un fichier Markdown : en-tête YAML, invite système, contexte
READ-ONLY déclaré. Rien n'y s'exécute au nom du modèle.

Ses exigences sont confrontées à ce que le serveur annonce, et une règle
gouverne l'affichage : L'INCONNU NE GRISE JAMAIS. Seule une exigence
contredite par un champ réellement lu sur le serveur grise — griser sur
l'inconnu viderait le catalogue devant un serveur qui n'annonce rien,
c'est-à-dire devant la plupart. Une valeur estimée ne grise pas non plus.

`yaml.safe_load` n'est pas un validateur, et cela façonne le chargeur. Un
en-tête qui est une liste rend une liste, un scalaire rend une chaîne, un
fichier vide ne rend rien, et une clé RÉPÉTÉE est résolue en silence sur la
dernière — deux blocs `requires` changeaient donc la classe de sûreté d'un gpt
sans un mot. D'où un contrôle de type et une relecture du texte brut.

Un gpt hors du dépôt est forcé en boucle locale et ne peut déclarer aucune
commande : un fichier que personne n'a relu est de la configuration, pas une
donnée.

## Ce qu'un contexte déclaré a le droit de lire

La liste de refus passe la première et se résout sur le chemin RÉEL : ni
« suivi par git » ni « ignoré par git » n'est une porte utilisable, puisque
`private/` est partiellement suivi et que `tasks/` n'est dans aucun fichier
d'exclusion. Un lien symbolique est donc résolu avant d'être comparé.

Une commande est un argv, jamais une chaîne d'interpréteur, et elle est
confrontée à une liste d'autorisation qui vit dans le dépôt. La substitution
d'une entrée saisie précède ce contrôle, jamais l'inverse : vérifier un
gabarit puis y injecter une valeur vérifierait ce qu'on n'exécute pas.

Chaque octet assemblé passe par le détecteur du dépôt — et sa limite est dite
plutôt que cachée. Il reconnaît les adresses, les courriels et les chemins de
compte. Il ne reconnaît PAS les noms, sauf si une liste les énumère, et cette
liste n'existe pas d'ordinaire. Une absence de trouvaille ne prouve donc rien
sur les noms, et un envoi vers un tiers est REFUSÉ dans ce cas, même sans
aucune trouvaille.

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

## Les sessions Claude Code de la machine

Une session ouverte ailleurs porte déjà le contexte d'un travail, et lui poser
une question sans le retaper vaut le détour. Elle vit sous « GPT code » et non
sous le sous-menu LLM : une session est un processus adressé par identifiant,
un serveur est un hôte adressé par port, et les mêler dans une seule liste
numérotée ferait partager les mêmes chiffres à deux modèles mentaux.

Deux dangers ont dû être mesurés avant de le proposer. Un pid ne prouve pas
qu'une session vit — les pids se recyclent, donc la vivacité exige le pid ET
le moment de démarrage du processus. Et l'outil ne REFUSE pas de reprendre une
session qu'un terminal tient, son garde-fou écartant les détenteurs
interactifs ; deux écritures scindent alors la transcription et une branche est
orpheline. Une copie est branchée par défaut, et écrire dans une session tenue
exige de retaper le pid du détenteur.

La frontière de vie privée est celle que le système a déjà tracée. Le registre
est lisible par tous, donc pid, répertoire, nom et identifiant n'y sont pas des
secrets. Les transcriptions ne le sont pas : il n'en sort que deux champs de
STRUCTURE — le répertoire de travail et la branche git — jamais un titre, une
invite ou un message. Le répertoire y est LU plutôt que dérivé du nom du
répertoire qui la contient, parce que cette transformation change les
séparateurs, les points et les tirets bas en tirets et ne s'inverse donc pas.

## Les modules

| Fichier | Ce qu'il porte |
|---------|----------------|
| `__init__.py` | les deux règles qui gouvernent tout ce qui suit |
| `fingerprint.py` | qui répond sur un port : l'échelle, et son transport |
| `capabilities.py` | ce qu'un serveur annonce savoir faire, en trois paliers d'honnêteté, et l'appariement d'une exigence |
| `servers.py` | les serveurs retenus : poignées opaques, lecture et écriture |
| `backends.py` | parler à une destination : un serveur HTTP, ou le CLI `claude` |
| `chat.py` | les tours d'une conversation, et les commandes qui la pilotent |
| `discover.py` | quels couples (hôte, port) méritent une reconnaissance, et la frappe |
| `gpt.py` | le catalogue : charger, refuser, et ne jamais casser le menu |
| `context.py` | ce qu'un contexte déclaré peut lire, et ce que la porte autorise |
| `claude_sessions.py` | les sessions Claude Code de la machine : lesquelles vivent |
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
