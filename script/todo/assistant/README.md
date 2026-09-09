
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

## Tests

```bash
make test_unit_file F=test/test_assistant_fingerprint.py
PYTHONPATH=. ./.venv.erplibre/bin/python test/test_assistant_servers.py
for f in test/test_assistant_*.py; do
  PYTHONPATH=. ./.venv.erplibre/bin/python "$f"
done
```