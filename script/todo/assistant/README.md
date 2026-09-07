
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

## Tests

```bash
make test_unit_file F=test/test_assistant_fingerprint.py
PYTHONPATH=. ./.venv.erplibre/bin/python test/test_assistant_servers.py
for f in test/test_assistant_*.py; do
  PYTHONPATH=. ./.venv.erplibre/bin/python "$f"
done
```