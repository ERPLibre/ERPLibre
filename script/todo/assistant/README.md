
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

**Time spent is not time elapsed, and the table shows the first.** A session's
clock counts everything that passed, including the hours nobody was watching —
it reports hundreds of hours as soon as a session stays open for days. The
attention column sums the gaps between hook events instead, each gap capped by
an inactivity threshold this package chooses and names. Nothing is collected
for it: the hook log already carries the instant of every event. Without hooks
installed the column shows a dash, never a zero, a zero saying "this session
did no work" where the truth is "nothing is measured".

**The time series was on disk all along.** Every assistant message carries its
instant and its model — present on all ten thousand sampled. Tokens per day and
per model therefore come from summing messages, not from reading a
`cost-state`: no compaction resets them, no segment is lost, and they add up
across sessions without the reserve that weighs on cost. The day is read in UTC
as the transcript writes it; converting to local time would move messages from
one day to another depending on who is looking.

**A tool call ends in one of four ways, and the screen tells them apart.** It
finished, it failed, it was interrupted, or nothing ever closed it. One count
for all four gave a figure no gesture answers: a failure is corrected, an
interruption is relaunched, and an unclosed call says nothing at all. The
`PostToolUseFailure` event carries the difference in `is_interrupt`.

**The duration is the one the tool measured, not the gap between two
instants.** That gap INCLUDES the time spent in front of a permission prompt,
so a call approved after four minutes read as a four-minute call and inflated
the per-tool median. The closing event carries `duration_ms`; the gap remains
only as a fallback for a binary that does not. Both fields are integers, and a
string-only filter dropped them silently — the same defect the neighbouring
module already paid for on a hook's exit code.

**The bottom panel switches rather than stacks.** A terminal has no room for
three tables, and stacking them would leave four lines each. The `v` key
cycles: per tool, which answers "which one is slow", and the stream of the
latest calls, which answers "why has it been stuck for two minutes". Neither
shows any content — a tool name, a duration, an ending. The outcome column
stays empty for a finished call, the ordinary case that has nothing to report,
and the three bad endings name themselves in the singular: a row describes one
call, where the per-tool table counts many.

**The screen acts, and says what it may not do.** A third panel lists the
detached agents running right now — live AND detached, because the fleet joins
two sources: the registry says what RUNS, a sweep of the transcripts says what
RESUMES, and a dormant session comes out of it with neither kind nor process.
Offering it would propose `stop` on a file, and the tool answers "No job
matching" with a NULL exit code, so nothing would look like it failed.

`n` starts an agent, its prompt read on standard input and never in the argv,
where `/proc/<pid>/cmdline` exposes it to every account. `s` stops the
highlighted one — its conversation is kept, so nothing to confirm. `a` attaches
and therefore CLOSES the screen: `claude attach` takes the terminal and cannot
share it. A key pressed in another panel does nothing, rather than acting on a
highlighted row nobody can see.

**The stream shows the command, and nothing was collected for it.** "Bash ·
1.2 s · failure" says that something failed without saying what. The hook log
keeps `tool_use_id` and nothing else of the call — no command, no answer —
because writing `tool_input` there would put every shell command on disk for
fourteen days, which is keeping and not showing. The command is read back from
the TRANSCRIPT, where Claude Code had already written it, at the moment
someone asks. Three hundredths of a second per lookup in thirty megabytes: the
substring pre-filter does the work.

An added trap, and it hides a third of the calls: a tool launched by a
SUBAGENT is written in the subagent's own file, under the session directory,
while the hook announces it under the PARENT session's identifier. Both places
are searched, the main transcript first.

A detail pane opens on the highlighted call and shows the command with its
output. It is the only pane of the package that displays content, so it says
so, in the first line rather than the last — a long output would push the
warning off screen.

**The tables fit the terminal, because they were measured against it.** The
columns had piled up one per feature without anyone checking the width: twelve
of them wanted 124 characters, and the stream 95 of which 55 for the command
alone. An eighty-column terminal — the commonest default — showed neither.
Nothing was broken, Textual scrolls; but a dashboard you have to scroll no
longer reads at a glance.

Two fixes, both measured. The command column takes WHAT IS LEFT rather than a
fixed sixty, so it neither overflows a narrow terminal nor wastes a wide one.
And the session table shows only the columns that fit, in order of importance
— which session, which project, what it costs, how full its context is —
rebuilding them only when the count changes, since redoing them every two
seconds would reset the cursor under the reader's fingers. A project name is
cut on the LEFT: a family of repositories shares its prefix and differs by
what follows.

**Two gestures cost something, and the gap between their guards is the point.**
`l` restarts the highlighted agent on the current binary — the work in progress
is cut, so a yes is asked, but the conversation survives and that is what sets
it apart. `x` deletes the session AND its worktree, and nothing brings it back:
the whole identifier is retyped, the long one and not the eight characters. A
tap on "y" is given by reflex; copying thirty-six characters makes you look at
what you are destroying. Both act with the SHORT identifier, the only one the
subcommands accept — the retyping is a guard, not an argument.

**The stream's column shows what situates, never what was said.** A call
carries a shell command, a path, a URL — or free text: the prompt given to a
subagent, a search pattern. The first three fit a table row without revealing
anything of the conversation; the last does not, and a `Task` call, having no
command, used to spread its whole prompt across a column that declares it
shows no content. It now says "content", and the detail pane — which warns —
is where that is read. A URL loses what authenticates it, here as in the MCP
module: the boundary that was relaxed covers CONTENT, never secrets.

**Everything that comes from a cost-state falls silent when none was read.**
Nine of the eighteen transcripts on an ordinary machine carry none — an
interrupted session, an older version, a fresh one. Cost already said so with
a dash; the durations and the lines touched, which come from the same record,
were showing "0 ms" and "+0/−0", which reads "measured, and nil".

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
| `agents/detail.py` | a tool call's command and answer, read back from the transcript and never collected |
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

## Tests

```bash
make test_unit_file F=test/test_assistant_fingerprint.py
PYTHONPATH=. ./.venv.erplibre/bin/python test/test_assistant_servers.py
for f in test/test_assistant_*.py; do
  PYTHONPATH=. ./.venv.erplibre/bin/python "$f"
done
```