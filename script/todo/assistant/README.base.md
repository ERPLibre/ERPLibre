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
question without retyping that is worth the trip. It sits under
`Assistant › AI`, in the **Agents** section and not among the servers: a
session is a process addressed by identifier, a server is a host addressed by
port, and putting the two in one section would make two mental models share
the same digits.

That screen lists the harnesses this repository knows by name, and it never
hides one. A harness whose binary is missing keeps its number, greyed, with
what is missing said on the same line — and the reason distinguishes two
things that call for opposite gestures: a binary to install, or an adapter
nobody has measured yet. Only `claude` is measured; declaring an action for
the others would offer what fails.

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

## What an agent costs, and what it carries

Three sources answer that, and they are not worth the same. The screen says
which one each figure comes from, because a table that mixes a measurement
with an approximation makes the wrong component look guilty.

**The disk already knows almost everything.** Every transcript carries a
`cost-state` line — cost in dollars, wall-clock, API and tool durations, lines
of code — and every assistant message carries its own token `usage`. Nothing
to install, nothing to switch on, no trace left behind. But those cost lines
are NOT monotonic: a compaction resets the counter, and one transcript carries
several segments whose fields do not compose. The last one is kept, and the
screen says it is a segment.

**What the disk does not know** is WHICH tool, how often, and for how long
each. `totalToolDuration` is an aggregate: it says nineteen minutes without
ever saying that one tool takes three quarters of it. A hook set says it, one
line per call — and no hook event carries a duration, so two events are
written, before and after, and their call identifier stitches them. A call
whose after is missing stays UNPAIRED rather than being given an invented
duration.

**A hook must never fail the call it observes.** A non-zero exit on
`PreToolUse` BLOCKS the tool call, so the script is wrapped end to end and
exits zero whatever happens. It imports nothing from the repository either: it
runs hundreds of times per session, in a fresh interpreter each time.

Neither the command nor the tool's response is written. The log counts calls;
it does not keep what they say. That holds even where the display boundary was
lifted — what is never written does not have to be protected later.

## What a session carries

A delta is not a state, and that is the trap of this whole area. Several
records are re-emitted mid-session and carry only what changed: reading the
last occurrence gives one instruction file where seven are loaded, and one
skill where thirty-nine are. Each is corrected according to its shape —
instructions accumulate by path, a skill listing keeps its initial entry — and
the one whose semantics cannot be determined is never totalled at all.

The package's old rule, "structure yes, message content no", no longer
suffices: a transcript now carries the full text of the instruction files, of
the skills, the system prompt and a hook's raw output, none of which is a
message. The operative form: **a path, a name, a count, a size or a duration;
never a field whose value is unbounded free text.**

An environment is read but not copied out. The kernel already reserves
`/proc/<pid>/environ` to the owner of the process, and a screen that prints a
value in clear breaks a boundary nobody had to write. A value is shown only if
its name is on a closed list AND its value has that name's expected shape; the
rest shows its shape. The pattern-based redaction used elsewhere in the
repository does not fit here — it only recognises `NAME=value` glued together,
and in an aligned two-column table it lets almost everything through.

## A second harness answers a different question

Open Code sits beside Claude Code in the menu, and the two look alike enough to
mislead. Three differences decide the shape of its screen, and each was
measured against the tool rather than assumed.

**Its listing is scoped to the CURRENT DIRECTORY.** `claude agents` answers
"what runs on this machine"; `opencode session list` answers "what happened
HERE", and no flag widens it. The screen therefore states its scope and prints
the directory before listing anything — otherwise it would announce "no
session" to someone who has twenty in the folder next door.

**A session's title is GENERATED by the model** from the conversation. It has
the shape of a structural field and is not one, so it never leaves the
adapter — the same rule that keeps a Claude Code session's title off screen.
What situates a session without quoting it is its identifier and its date; the
directory column is dropped, since it repeats the one the header just printed.

**Two sources answer, and they do not weigh the same.** The SQLite base the
tool keeps carries everything — cost, tokens, cache, lines touched, model,
agent, dates — in a read of under a millisecond, over EVERY session. The two
CLI commands take close to two seconds for less, and one of them truncates. So
the base is read first and the CLI is the fallback, its schema being a third
party's and promised stable by nobody. The screen names which one answered,
because only the base can leave the current directory.

**That same file holds secrets, and that is what bounds the read.** It keeps
the account's access and refresh tokens, its address, and the prompts typed by
the user. One table is therefore named, its columns are listed one by one, the
handle is read-only, and a test refuses any other table or any authenticating
column. `immutable=1` is refused too: it ignores the write-ahead log, which
runs to megabytes here, and returns ZERO rows on a populated base — a wrong
answer rather than an error, which is the worse of the two.

**Only reading is declared.** `opencode run` writes into the working tree
without asking — a three-word instruction is enough to have a file created —
so a menu entry called "free question" would be a trap. It stays at the CLI,
where one goes on purpose, as do `delete`, `uninstall` and `upgrade`.

Two output shapes trap the decoding, and the screen names the culprit rather
than blaming itself. An EMPTY listing is not `[]`, so decoding it raises; and
`export` truncates its own output past roughly 60 kB, exiting before its
buffer is flushed — three runs of the same export return three sizes, all cut
mid-string. The screen says Open Code cut its output, which is what a reader
needs to stop looking for a defect here.

The live telemetry screen shows both harnesses in one table, each row marked by
its harness icon. What Open Code does not measure — turns, context and its
slope, API and tool durations — shows a DASH and never a zero: a zero column
reads "measured, and nil", which is false and stops the reader looking for what
the other harness does give. The summary line keeps the two apart rather than
folding them into one total, Claude Code's cost being read from a cost-state
that a compaction resets while Open Code's is a stable database field.

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
| `harness/registre.py` | which agent harnesses this machine carries, and what is missing from the others |
| `harness/claude.py` | the argv of a detached agent's five subcommands, and what each one costs |
| `harness/opencode.py` | Open Code's sessions and their cost, read only, and the three shapes its output takes |
| `agents/statistiques.py` | what a transcript says of a session: tokens, cost, durations, context |
| `agents/tui.py` | the live screen, refreshed without re-reading what it already folded |
| `agents/journal.py` | the tool-call log: one line per event, and their pairing into durations |
| `agents/hooks/evenement.py` | the hook that writes an event, and must never fail the call |
| `agents/pose.py` | installing and removing the hooks, at either of the two places |
| `agents/disque.py` | what Claude Code occupies, per directory and per session |
| `agents/mcp.py` | the MCP servers: what is declared here, and what must be asked for |
| `agents/contexte.py` | what a session loaded: model, machine, instructions, skills |
| `agents/environnement.py` | a process's environment, read without copying it out |
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

## Trouver un serveur qui n'est pas là

Quatre sources répondent à « où chercher » : la boucle locale, les domaines
QEMU de cette machine, les hôtes de `~/.ssh/config`, et un `/24` balayé. Deux
d'entre elles sont INJECTÉES — énumérer les domaines libvirt et résoudre un
alias SSH sont déjà des méthodes de la classe du CLI, que ce paquet n'a pas le
droit d'importer.

Un serveur vit souvent sur un réseau que cette machine ne PORTE pas, joignable
par la passerelle : quand le CLI tourne dans une machine virtuelle, le
« réseau local » qu'il voit est celui de l'hyperviseur. Deux sources y
répondent — un CIDR saisi, et les réseaux lus en SSH sur une autre machine
puis balayés d'ici. La table de voisinage, elle, ne le peut pas : elle est
link-local, donc un hôte routé n'y paraît jamais.

Plus large qu'un `/24` est refusé, et le refus a lieu AVANT l'énumération —
mesurer un `/8` en le matérialisant coûterait seize millions d'adresses. La
réserve de fils se dimensionne au NOMBRE DE VAGUES et jamais au nombre de
cœurs : ces fils attendent le réseau. Et le délai de connexion est le seul
réglage d'ici qui fabrique des FAUX NÉGATIFS — un hôte joignable en une
milliseconde au repos se manque à cinq centièmes sous mille connexions
simultanées, donc il ne se déduit pas d'une latence mesurée.

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
une question sans le retaper vaut le détour. Elle vit sous « Assistant › IA »,
dans la section **Agents** et non parmi les serveurs : une session est un
processus adressé par identifiant, un serveur est un hôte adressé par port, et
les mettre dans une même section ferait partager les mêmes chiffres à deux
modèles mentaux.

Cet écran liste les harnais que ce dépôt connaît de nom, et il n'en cache
jamais un. Un harnais dont le binaire manque garde son numéro, grisé, avec ce
qui manque dit sur la même ligne — et la raison distingue deux choses qui
appellent des gestes opposés : un binaire à installer, ou un adaptateur que
personne n'a mesuré. Seul `claude` l'est ; déclarer une action pour les autres
offrirait ce qui échoue.

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

## Ce qu'un agent coûte, et ce qu'il porte

Trois sources y répondent et elles ne se valent pas. L'écran dit de laquelle
vient chaque chiffre, parce qu'un tableau qui mélange une mesure et une
approximation fait accuser le mauvais composant.

**Le disque sait déjà presque tout.** Chaque transcription porte une ligne
`cost-state` — coût en dollars, durée d'horloge, durée d'API, durée d'outils,
lignes de code — et chaque message d'assistant porte son propre `usage` de
jetons. Rien à installer, rien à activer, aucune trace posée. Mais ces lignes
de coût ne sont PAS monotones : une compaction remet le compteur à zéro, et
une transcription porte plusieurs segments dont les champs ne se composent
pas. La dernière est retenue, et l'écran dit que c'en est une.

**Ce que le disque ne sait pas**, c'est QUEL outil, combien de fois et combien
de temps chacun. `totalToolDuration` est un agrégat : il annonce dix-neuf
minutes sans jamais dire que l'un d'eux en prend les trois quarts. Un jeu de
hooks le dit, une ligne par appel — et aucun événement de hook ne porte de
durée, donc deux sont écrits, avant et après, et leur identifiant d'appel les
recoud. Un appel dont l'après manque reste NON APPARIÉ plutôt que de se voir
attribuer une durée inventée.

**Un hook ne doit jamais faire échouer l'appel qu'il observe.** Un code non
nul sur `PreToolUse` BLOQUE l'appel d'outil, donc le script est enveloppé de
bout en bout et sort à zéro quoi qu'il arrive. Il n'importe rien du dépôt non
plus : il tourne des centaines de fois par session, dans un interpréteur neuf
chaque fois.

Ni la commande ni la réponse de l'outil ne sont écrites. Le journal compte des
appels, il ne garde pas ce qu'ils disent. Cela tient même là où la frontière
d'affichage a été levée : ce qui n'est pas écrit n'a pas à être protégé plus
tard.

## Ce qu'une session porte

Un delta n'est pas un état, et c'est le piège de tout ce domaine. Plusieurs
enregistrements sont réémis en cours de session et ne portent que ce qui a
changé : lire la dernière occurrence donne un fichier d'instructions là où
sept sont chargés, et une skill là où trente-neuf le sont. Chacun se corrige
selon sa forme — les instructions s'accumulent par chemin, une liste de skills
retient son entrée initiale — et celui dont la sémantique n'est pas
déterminable n'est jamais totalisé.

L'ancienne règle du paquet, « la structure oui, le contenu d'un message non »,
ne suffit plus : une transcription porte maintenant le texte intégral des
fichiers d'instructions, celui des skills, l'invite système et la sortie brute
d'un hook, dont aucun n'est un message. La forme opérante : **un chemin, un
nom, un compte, une taille ou une durée ; jamais un champ dont la valeur est
du texte libre de longueur non bornée.**

Un environnement se lit sans se recopier. Le noyau réserve déjà
`/proc/<pid>/environ` au propriétaire du processus, et un écran qui en imprime
une valeur en clair casse une frontière que personne n'a eu à écrire. Une
valeur ne s'affiche que si son nom est sur une liste fermée ET que sa valeur a
la forme attendue de ce nom ; le reste montre sa forme. Le caviardage par
motifs employé ailleurs dans le dépôt ne convient pas ici : il ne reconnaît
que `NOM=valeur` collé, et en deux colonnes alignées il laisse passer presque
tout.

## Un second harnais répond à une autre question

Open Code voisine avec Claude Code dans le menu, et les deux se ressemblent
assez pour tromper. Trois différences décident de la forme de son écran, et
chacune a été mesurée contre l'outil plutôt que supposée.

**Son listage est cadré sur le RÉPERTOIRE COURANT.** `claude agents` répond
« ce qui tourne sur cette machine » ; `opencode session list` répond « ce qui
s'est passé ICI », et aucun drapeau n'élargit la portée. L'écran dit donc sa
portée et imprime le répertoire avant de lister quoi que ce soit — sans quoi
il annoncerait « aucune séance » à qui en a vingt dans le dossier d'à côté.

**Le titre d'une séance est ENGENDRÉ par le modèle** à partir de la
conversation. Il a la forme d'un champ structurel et n'en est pas un, donc il
ne sort pas de l'adaptateur — la même règle qui garde hors de l'écran le titre
d'une session de Claude Code. Ce qui situe une séance sans la citer est son
identifiant et sa date ; la colonne du répertoire disparaît, puisqu'elle
répète celui que l'en-tête vient d'imprimer.

**Deux sources répondent, et elles ne pèsent pas pareil.** La base SQLite que
l'outil tient porte tout — coût, jetons, cache, lignes touchées, modèle,
agent, dates — en une lecture de moins d'une milliseconde, sur TOUTES les
séances. Les deux commandes du CLI demandent près de deux secondes pour moins,
et l'une des deux se tronque. La base est donc lue d'abord et le CLI sert de
repli, son schéma étant celui d'un tiers que personne ne promet stable.
L'écran nomme celle qui a répondu, car seule la base sait sortir du répertoire
courant.

**Ce même fichier porte des secrets, et c'est ce qui borne la lecture.** Il
tient les jetons d'accès et de rafraîchissement du compte, son adresse, et les
invites tapées par l'utilisateur. Une seule table est donc nommée, ses
colonnes énumérées une à une, l'ouverture en lecture seule, et un test refuse
toute autre table comme toute colonne d'authentification. `immutable=1` est
refusé aussi : il ignore le journal d'écriture anticipée, qui pèse ici
plusieurs mégaoctets, et rend ZÉRO ligne sur une base pleine — une réponse
fausse plutôt qu'une erreur, ce qui est pire.

**Seule la lecture est déclarée.** `opencode run` écrit dans l'arbre de
travail sans demander — une consigne de trois mots suffit à faire créer un
fichier — donc une entrée « question libre » y serait un piège. Elle reste au
CLI, où l'on va exprès, comme `delete`, `uninstall` et `upgrade`.

Deux formes de sortie piègent le décodage, et l'écran nomme le coupable au
lieu de s'accuser. Un listage VIDE n'est pas `[]`, donc le décoder lève ; et
`export` tronque sa propre sortie au-delà d'une soixantaine de kilooctets, en
sortant avant d'avoir vidé son tampon — trois exécutions du même export
rendent trois tailles, toutes coupées au milieu d'une chaîne. L'écran dit
qu'Open Code a coupé, ce qu'il faut savoir pour cesser de chercher un défaut
ici.

L'écran vivant de télémétrie montre les deux harnais dans un seul tableau,
chaque ligne marquée de l'icône du sien. Ce qu'Open Code ne mesure pas — les
tours, le contexte et sa pente, les durées d'API et d'outils — affiche un
TIRET et jamais un zéro : une colonne à zéro se lit « mesuré, et nul », ce qui
est faux et décourage de chercher ailleurs ce que l'autre harnais donne. La
ligne de résumé garde les deux séparés plutôt que de les fondre en un total,
le coût de Claude Code étant lu dans un `cost-state` qu'une compaction remet à
zéro là où celui d'Open Code est un champ de base stable.

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
| `harness/registre.py` | quels harnais d'agent cette machine porte, et ce qui manque aux autres |
| `harness/claude.py` | l'argv des cinq sous-commandes d'un agent détaché, et ce que chacune coûte |
| `harness/opencode.py` | les séances d'Open Code et leur coût, en lecture seule, et les trois formes que prend sa sortie |
| `agents/statistiques.py` | ce qu'une transcription dit d'une session : jetons, coût, durées, contexte |
| `agents/tui.py` | l'écran vivant, rafraîchi sans relire ce qu'il a déjà replié |
| `agents/journal.py` | le journal des appels d'outils : une ligne par événement, et leur appariement |
| `agents/hooks/evenement.py` | le hook qui écrit un événement, et ne doit jamais faire échouer l'appel |
| `agents/pose.py` | poser et retirer les hooks, à l'un ou l'autre des deux endroits |
| `agents/disque.py` | ce que Claude Code occupe, par répertoire et par session |
| `agents/mcp.py` | les serveurs MCP : ce qui est déclaré ici, et ce qu'il faut demander |
| `agents/contexte.py` | ce qu'une session a chargé : modèle, machine, instructions, skills |
| `agents/environnement.py` | l'environnement d'un processus, lu sans le recopier |
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
